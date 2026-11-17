"""Field extraction with a vision LLM (Phase 5): image preparation, doc-type-aware prompts, two extractors
behind one interface, validation with retries, a resumable batch runner, and the officer case summary.

    extractor = OllamaExtractor()                          # local "private mode": qwen2.5vl:7b
    extractor = CloudExtractor.from_env()                  # None if .env has no LLM_API_KEY
    result = extractor.extract(prepare_image(path), "srb_passport")
    result.fields     # dict of the canonical fields (schemas.IDFields), or None if no valid answer came back

Every answer is parsed into schemas.IDFields. If that fails, the model is asked again (at most MAX_RETRIES times)
with the validation error in the message, so it can correct its own JSON.
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
import pandas as pd
from PIL import Image
from pydantic import ValidationError

from ekyc import config
from ekyc.schemas import CANONICAL_FIELDS, DOC_FIELD_MAP, IDFields

PROMPT_VERSION = "v2"  # v1 -> v2 (dev set): aze passport number vs type code; copy Latin lines, never transliterate
MAX_RETRIES = 2
IMAGE_LONGEST = 1280  # px: a full-size template costs ~3,900 of qwen2.5vl's tokens; 1280 px about 1,300
IMAGE_QUALITY = 90

# ---------------------------------------------------------------- image preparation


def prepare_image(source: Path | bytes, longest: int = IMAGE_LONGEST, quality: int = IMAGE_QUALITY) -> bytes:
    """Raw template (a path, or the uploaded file's bytes) -> RGB (500 genuine templates are CMYK) -> longest
    side exactly `longest` px (Lanczos) -> JPEG bytes at `quality`. Nothing is written to disk."""
    with Image.open(io.BytesIO(source) if isinstance(source, bytes) else source) as image:
        image = image.convert("RGB")
        scale = longest / max(image.size)
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


# ---------------------------------------------------------------- prompts

DOC_TYPE_NAMES = {
    "alb_id": "Albanian identity card", "aze_passport": "Azerbaijani passport",
    "esp_id": "Spanish identity card (DNI)", "est_id": "Estonian identity card", "fin_id": "Finnish identity card",
    "grc_passport": "Greek passport", "lva_passport": "Latvian passport",
    "rus_internalpassport": "Russian internal passport", "srb_passport": "Serbian passport",
    "svk_id": "Slovak identity card",
}

_MRZ = ("the two machine-readable lines at the bottom (44 characters each): copy every character, "
        "including each '<' filler, without spaces")
# Where each canonical field is printed, by its label on the card. Written from training templates only.
# The number fields carry the format, because their labels are easy to confuse (esp_id swaps them!).
DOC_FIELD_HINTS: dict[str, dict[str, str]] = {
    "alb_id": {
        "surname": "'mbiemri/surname'", "given_names": "'emri/given name'",
        "birth_date": "'datëlindja/date of birth'", "gender": "'gjinia/sex'",
        "nationality": "'shtetësia/nationality'", "birth_place": "'vendlindja/place of birth'",
        "issue_date": "'data e lëshimit/date of issue'", "expiry_date": "'data e skadimit/date of expiry'",
        "authority": "'autoriteti lëshues/authority'",
        "document_number": "'nr. letërnjoftimi/card no.': 9 digits",
        "personal_number": "'nr. personal/personal no.': a letter, 8 digits and a letter"},
    "aze_passport": {
        "surname": "'Soyadı/Surname': printed on two lines; copy the SECOND line exactly as printed (do not "
                   "transliterate the first line yourself)",
        "given_names": "'Adı, atasının adı/Given name, patronymic': two lines; copy the SECOND, shorter line exactly",
        "birth_date": "'Doğulduğu tarix/Date of birth'", "gender": "'Cinsi/Sex', e.g. K/M or Q/F",
        "nationality": "'Vətəndaşlığı/Nationality'", "birth_place": "'Doğulduğu yer/Place of birth'",
        "issue_date": "'Verilmə tarixi/Date of issue'", "expiry_date": "'Etibarlılıq müddəti/Date of expiry'",
        "authority": "'Pasportu verən orqan/Issuing authority': only the FIRST line (national language)",
        "document_number": "'Pasportun nömrəsi/Passport No': the value at the TOP RIGHT, a letter followed by 8 "
                           "digits (NOT the 2-letter type code such as PC under 'Tip/Type')",
        "personal_number": "'Fərdi identifikasiya nömrəsi/Personal No': 7 letters/digits",
        "mrz_line0": _MRZ, "mrz_line1": _MRZ},
    "esp_id": {
        "surname": "'PRIMER APELLIDO' and 'SEGUNDO APELLIDO' joined with one space",
        "given_names": "'NOMBRE'", "gender": "'SEXO'", "nationality": "'NACIONALIDAD'",
        "birth_date": "'FECHA DE NACIMIENTO'", "expiry_date": "'VÁLIDO HASTA'",
        "issue_date": "the 6-digit date (DDMMYY) printed on the left, below the chip",
        "document_number": "'IDESP': 3 letters and 6 digits (this is NOT the DNI number)",
        "personal_number": "'DNI NÚM.' at the bottom left: 8 digits and a letter"},
    "est_id": {
        "surname": "'PEREKONNANIMI/SURNAME'", "given_names": "'EESNIMED/GIVEN NAMES'",
        "gender": "'SUGU/SEX', e.g. M/M or N/F", "nationality": "'KODAKONDSUS/CITIZENSHIP'",
        "birth_date": "'SÜNNIAEG/DATE OF BIRTH'", "expiry_date": "'KEHTIV KUNI/DATE OF EXPIRY'",
        "personal_number": "'ISIKUKOOD/PERSONAL CODE': 11 digits",
        "document_number": "'DOKUMENDI NUMBER/DOCUMENT NUMBER': 2 letters and 7 digits"},
    "fin_id": {
        "surname": "'Sukunimi/Efternamn'", "given_names": "'Etunimet/Förnamn'", "gender": "'Sukupuoli/Kön'",
        "nationality": "'Kansalaisuus/Nationalitet'", "birth_date": "'Syntymäaika/Födelsedatum'",
        "issue_date": "'Myönnetty/Utfärdat'", "expiry_date": "'Viim. voimassaolopäivä/Sista giltighetsdag'",
        "document_number": "'Korttinumero/Kortnummer': 9 digits",
        "personal_number": "the personal identity code: the date of birth as DDMMYY immediately followed by the "
                           "'Tunnus/Kod' code (e.g. DDMMYY-123A), without spaces"},
    "grc_passport": {
        "surname": "'Επώνυμο/Surname': two lines, Greek letters then Latin letters; copy the LATIN line exactly as "
                   "printed (it can differ from a transliteration of the Greek line: do not transliterate yourself)",
        "given_names": "'Όνομα/Name': copy the LATIN-letter line exactly as printed (do not transliterate)",
        "nationality": "'Ιθαγένεια/Nationality'", "gender": "'Φύλο/Sex'",
        "birth_date": "'Ημ. γέννησης/Date of birth'",
        "birth_place": "'Τόπος γέννησης/Place of birth': two lines; copy the second, LATIN-letter line exactly",
        "issue_date": "'Ημ. έκδοσης/Iss. date'", "expiry_date": "'Ημ. λήξης/Date of expiry'",
        "authority": "'Εκδ. Αρχή/Iss. office'",
        "document_number": "'Αρ. Διαβατηρίου/Passport No.': 2 letters and 7 digits",
        "mrz_line0": _MRZ, "mrz_line1": _MRZ},
    "lva_passport": {
        "surname": "'1. Uzvārds/Surname'", "given_names": "'2. Vārds(-i)/Given name(s)'",
        "nationality": "'3. Pilsonība/Nationality'", "gender": "'5. Dzimums/Sex', e.g. V/M or S/F",
        "birth_date": "'6. Dzimšanas datums/Date of birth'",
        "personal_number": "'7. Personas kods/Personal No.': 6 digits, a hyphen and 5 digits",
        "authority": "'8. Izdevējiestāde/Authority': both lines joined with one space",
        "birth_place": "'9. Dzimšanas vieta/Place of birth'", "issue_date": "'10. Izdošanas datums/Date of issue'",
        "expiry_date": "'11. Derīgs līdz/Date of expiry'",
        "document_number": "'Pases Nr./Passport No.' (top right): 2 letters and 7 digits",
        "mrz_line0": _MRZ, "mrz_line1": _MRZ},
    "rus_internalpassport": {
        "surname": "'Фамилия'", "given_names": "'Имя' and 'Отчество' joined with one space",
        "gender": "'Пол', e.g. МУЖ. or ЖЕН.", "birth_date": "'Дата рождения'",
        "birth_place": "'Место рождения': all its lines joined with one space",
        "document_number": "the red series and number printed vertically at the right edge: 2 + 2 + 6 digits"},
    "srb_passport": {
        "surname": "'Презиме/Surname'", "given_names": "'Име/Given names'",
        "nationality": "'Држављанство/Nationality'", "birth_date": "'Датум рођења/Date of birth'",
        "gender": "'Пол/Sex', e.g. M / M", "birth_place": "'Место рођења/Place of birth'",
        "authority": "'Издао/Authority'", "issue_date": "'Датум издавања/Date of issue'",
        "expiry_date": "'Важи до/Date of expiry'",
        "document_number": "'Бр. пасоша/Passport No': 9 digits",
        "personal_number": "'ЈМБГ/Personal No': 13 digits",
        "mrz_line0": _MRZ, "mrz_line1": _MRZ},
    "svk_id": {
        "surname": "'Priezvisko/Surname'", "given_names": "'Meno/Given names'",
        "nationality": "'Štátne občianstvo/Nationality'", "gender": "'Pohlavie/Sex'",
        "birth_date": "'Dátum narodenia/Date of birth'", "expiry_date": "'Dátum platnosti/Date of expiry'",
        "issue_date": "'Dátum vydania/Date of issue'", "authority": "'Vydal/Issued by' (a town)",
        "document_number": "'Číslo/No.': 2 letters and 6 digits, in large print",
        "personal_number": "'Rodné číslo/Personal No.': 6 digits, '/', 4 digits"},
}
assert all(set(DOC_FIELD_HINTS[t]) == set(DOC_FIELD_MAP[t]) for t in DOC_FIELD_MAP), "hints and mapping disagree"

SYSTEM_PROMPT = ("You read identity documents and return their fields as JSON. You copy text exactly as printed "
                 "and never guess.")


def build_prompt(doc_type: str) -> str:
    """The user prompt for one document type: which fields this document prints and where (by label), and
    which must be null. The document type comes from the classifier in the pipeline."""
    hints = DOC_FIELD_HINTS[doc_type]
    lines = [f"This image is a {DOC_TYPE_NAMES[doc_type]}. Return a JSON object with these keys.", "",
             "Fields printed on this document (where to find them):"]
    lines += [f"- {name}: {hints[name]}" for name in CANONICAL_FIELDS if name in hints]
    absent = [name for name in CANONICAL_FIELDS if name not in hints]
    if absent:
        lines += ["", "Not printed on this document, always null: " + ", ".join(absent)]
    lines += ["", "Rules: copy each value exactly as printed, keeping letter case, every diacritic (such as č, ć, "
              "ë, ā, ş) and the date format "
              "(do not translate, transliterate or reformat). Give the value only, without its label. "
              "If a value is unreadable, use null."]
    return "\n".join(lines)


# ---------------------------------------------------------------- result + common retry loop


@dataclass
class ExtractionResult:
    doc_id: str | None
    doc_type: str
    extractor: str
    model: str
    prompt_version: str
    valid: bool
    fields: dict | None
    attempts: int  # 1 = valid at once; MAX_RETRIES + 1 = all attempts used
    latency_s: float  # wall-clock time of all attempts together
    input_tokens: int | None = None
    output_tokens: int | None = None
    error: str | None = None
    raw: str | None = None  # the last raw answer (for inspection)

    @property
    def retries(self) -> int:
        return self.attempts - 1


@dataclass
class _Reply:
    text: str  # the model's JSON text
    input_tokens: int | None = None
    output_tokens: int | None = None
    extra: dict = field(default_factory=dict)  # provider details needed to continue the conversation


class Extractor:
    """Common logic. Subclasses implement _ask (one model call with the conversation so far) and _follow_up
    (how a correction request is appended for that provider)."""

    name = "base"
    model = ""

    def extract(self, image_jpeg: bytes, doc_type: str, doc_id: str | None = None) -> ExtractionResult:
        conversation = self._start(image_jpeg, build_prompt(doc_type))
        start, tokens_in, tokens_out, error, reply = time.perf_counter(), 0, 0, None, None
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                reply = self._ask(conversation)
            except (httpx.HTTPError, KeyError, ValueError) as exc:  # transport or response-format problem
                error = f"call failed: {exc}"
                break
            tokens_in += reply.input_tokens or 0
            tokens_out += reply.output_tokens or 0
            try:
                fields = IDFields.model_validate_json(reply.text).model_dump()
                return ExtractionResult(doc_id, doc_type, self.name, self.model, PROMPT_VERSION, True, fields,
                                        attempt, time.perf_counter() - start, tokens_in, tokens_out, None, reply.text)
            except ValidationError as exc:
                error = _short_error(exc)
                self._follow_up(conversation, reply, f"Your answer was not valid: {error}. Return the corrected "
                                                     "JSON object only.")
        return ExtractionResult(doc_id, doc_type, self.name, self.model, PROMPT_VERSION, False, None,
                                attempt, time.perf_counter() - start, tokens_in or None, tokens_out or None, error,
                                reply.text if reply else None)

    def complete_text(self, system: str, user: str) -> str:
        """A plain text answer (used for the officer summary)."""
        raise NotImplementedError

    # provider-specific parts
    def _start(self, image_jpeg: bytes, prompt: str) -> list:
        raise NotImplementedError

    def _ask(self, conversation: list) -> _Reply:
        raise NotImplementedError

    def _follow_up(self, conversation: list, reply: _Reply, message: str) -> None:
        raise NotImplementedError


def _short_error(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or 'answer'}: {e['msg']}" for e in exc.errors()[:5])


def json_schema() -> dict:
    """IDFields as a JSON schema, for providers that constrain the output to it."""
    return IDFields.model_json_schema()


# ---------------------------------------------------------------- Ollama (local, private mode)


class OllamaExtractor(Extractor):
    """qwen2.5vl:7b through Ollama's /api/chat. `format` = the JSON schema (Ollama then only generates text that
    fits it), temperature 0 (always the most likely token), a fixed seed and a context of 6,144 tokens (image
    ~1,300 + prompt ~600 + answer ~300, with room for two corrections). keep_alive keeps the model loaded
    between documents; unload() frees its memory at the end of a run."""

    name = "ollama"

    def __init__(self, model: str = "qwen2.5vl:7b", host: str = "http://localhost:11434", keep_alive: str = "10m",
                 num_ctx: int = 6144, timeout: float = 600.0, transport: httpx.BaseTransport | None = None,
                 options: dict | None = None):
        self.model, self.host, self.keep_alive, self.num_ctx = model, host.rstrip("/"), keep_alive, num_ctx
        self.options = options or {}  # extra generation options (the Phase 6 worker caps num_predict etc.)
        self.client = httpx.Client(timeout=timeout, transport=transport)  # transport: a fake server in tests

    def available(self) -> bool:
        try:
            names = [m["name"] for m in self.client.get(f"{self.host}/api/tags", timeout=5).json()["models"]]
            return self.model in names
        except (httpx.HTTPError, KeyError, ValueError):
            return False

    def unload(self) -> None:
        """Ask Ollama to drop the model from memory now (keep_alive 0)."""
        self.client.post(f"{self.host}/api/generate", json={"model": self.model, "keep_alive": 0})

    def _start(self, image_jpeg, prompt):
        return [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt, "images": [base64.b64encode(image_jpeg).decode()]}]

    def _chat(self, messages, format_schema=None) -> dict:
        body = {"model": self.model, "messages": messages, "stream": False, "keep_alive": self.keep_alive,
                "options": {"temperature": 0, "seed": config.SEED, "num_ctx": self.num_ctx, **self.options}}
        if format_schema is not None:
            body["format"] = format_schema
        response = self.client.post(f"{self.host}/api/chat", json=body)
        if response.status_code >= 400:  # keep Ollama's own reason, e.g. "token repeat limit reached"
            raise httpx.HTTPStatusError(f"{response.status_code} {response.text[:200]}", request=response.request,
                                        response=response)
        return response.json()

    def _ask(self, conversation):
        data = self._chat(conversation, json_schema())
        return _Reply(data["message"]["content"], data.get("prompt_eval_count"), data.get("eval_count"))

    def _follow_up(self, conversation, reply, message):
        conversation += [{"role": "assistant", "content": reply.text}, {"role": "user", "content": message}]

    def complete_text(self, system, user):
        return self._chat([{"role": "system", "content": system}, {"role": "user", "content": user}])["message"]["content"]


# ---------------------------------------------------------------- cloud API (main path when a key is set)


class CloudExtractor(Extractor):
    """A hosted vision model. Provider, model and key come from .env (LLM_PROVIDER, LLM_MODEL, LLM_API_KEY).
    Supported providers, called over HTTPS with httpx (no extra SDK):
    - "anthropic": Messages API; structured output by forcing a tool whose input schema is IDFields;
    - "openai": Chat Completions API with JSON mode; the schema is enforced by the Pydantic validation + retry."""

    name = "cloud"
    URLS = {"anthropic": "https://api.anthropic.com/v1/messages",
            "openai": "https://api.openai.com/v1/chat/completions"}

    def __init__(self, provider: str, model: str, api_key: str, timeout: float = 120.0,
                 transport: httpx.BaseTransport | None = None):
        if provider not in self.URLS:
            raise ValueError(f"LLM_PROVIDER must be one of {sorted(self.URLS)}, got {provider!r}")
        self.provider, self.model, self._key = provider, model, api_key
        self.name = f"cloud:{provider}"
        self.client = httpx.Client(timeout=timeout, transport=transport)

    @classmethod
    def from_env(cls, env_file: Path = config.PROJECT_ROOT / ".env") -> CloudExtractor | None:
        """The configured cloud extractor, or None if no API key is set (the cloud path is then skipped)."""
        from dotenv import dotenv_values

        values = {**dotenv_values(env_file), **{k: v for k, v in os.environ.items() if k.startswith("LLM_")}}
        if not values.get("LLM_API_KEY"):
            return None
        return cls(values.get("LLM_PROVIDER", "anthropic"), values.get("LLM_MODEL", ""), values["LLM_API_KEY"])

    def _post(self, body: dict) -> dict:
        if self.provider == "anthropic":
            headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01"}
        else:
            headers = {"Authorization": f"Bearer {self._key}"}
        response = self.client.post(self.URLS[self.provider], json=body, headers=headers)
        response.raise_for_status()
        return response.json()

    def _start(self, image_jpeg, prompt):
        data = base64.b64encode(image_jpeg).decode()
        if self.provider == "anthropic":
            return [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": prompt}]}]
        return [{"role": "system", "content": SYSTEM_PROMPT + " Answer with a JSON object only."},
                {"role": "user", "content": [{"type": "text", "text": prompt},
                                             {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}}]}]

    def _ask(self, conversation):
        if self.provider == "anthropic":
            data = self._post({"model": self.model, "max_tokens": 1024, "temperature": 0, "system": SYSTEM_PROMPT,
                               "messages": conversation,
                               "tools": [{"name": "record_fields", "description": "Record the extracted fields.",
                                          "input_schema": json_schema()}],
                               "tool_choice": {"type": "tool", "name": "record_fields"}})
            block = next(b for b in data["content"] if b["type"] == "tool_use")
            return _Reply(json.dumps(block["input"]), data["usage"]["input_tokens"], data["usage"]["output_tokens"],
                          {"content": data["content"], "tool_use_id": block["id"]})
        data = self._post({"model": self.model, "temperature": 0, "messages": conversation,
                           "response_format": {"type": "json_object"}})
        return _Reply(data["choices"][0]["message"]["content"], data["usage"]["prompt_tokens"],
                      data["usage"]["completion_tokens"])

    def _follow_up(self, conversation, reply, message):
        if self.provider == "anthropic":  # the correction answers the tool call
            conversation += [{"role": "assistant", "content": reply.extra["content"]},
                             {"role": "user", "content": [{"type": "tool_result", "tool_use_id": reply.extra["tool_use_id"],
                                                           "content": message, "is_error": True}]}]
        else:
            conversation += [{"role": "assistant", "content": reply.text}, {"role": "user", "content": message}]

    def complete_text(self, system, user):
        if self.provider == "anthropic":
            data = self._post({"model": self.model, "max_tokens": 1024, "temperature": 0, "system": system,
                               "messages": [{"role": "user", "content": user}]})
            return "".join(b["text"] for b in data["content"] if b["type"] == "text")
        data = self._post({"model": self.model, "temperature": 0,
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------- document sets


def template_documents(manifest: pd.DataFrame, splits: tuple[str, ...], label: int,
                       doc_types: tuple[str, ...] | None = None, per_type: int | None = None) -> pd.DataFrame:
    """Template pages to extract, in a fixed order (doc_type, doc_id, fake_name): columns doc_id, source_doc_id,
    doc_type, image_path, split, ctype, altered_field. per_type keeps the first n of each type (the dev set).
    Forged pages get their fake_name as doc_id, because one source document can have several forgeries."""
    t = manifest[(manifest["source"] == "template") & manifest["split"].isin(splits) & (manifest["label"] == label)]
    if doc_types:
        t = t[t["doc_type"].isin(doc_types)]
    t = t.sort_values(["doc_type", "doc_id", "fake_name"], na_position="first")
    if per_type:
        t = t.groupby("doc_type").head(per_type)
    t = t.assign(source_doc_id=t["doc_id"])
    if label == 1:
        t = t.assign(doc_id=t["fake_name"])
    return t[["doc_id", "source_doc_id", "doc_type", "image_path", "split", "ctype", "altered_field"]].reset_index(drop=True)


# ---------------------------------------------------------------- batch runs with a resumable cache


def run_batch(docs: pd.DataFrame, extractor: Extractor, cache_path: Path, project_root: Path = config.PROJECT_ROOT,
              progress_every: int = 10) -> pd.DataFrame:
    """Extract every document of `docs` (columns doc_id, doc_type, image_path) and return one row per document.

    Results are appended to `cache_path` (JSON lines) as soon as each document is done. A document already in
    the cache for the same extractor, model and PROMPT_VERSION is not sent again: an interrupted run continues
    where it stopped, and re-running a notebook re-uses the results instead of repeating a long (or one-time)
    run. Exception: if a document's latest record is a failed CALL (server or network error, so the model never
    answered), it is sent again ONCE; the failed record stays in the file. A document that failed twice keeps its
    failure (e.g. Ollama's "token repeat limit": the model got stuck repeating a character, which happens again
    at temperature 0). An invalid model ANSWER is a result and is never re-sent."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    key = (extractor.name, extractor.model, PROMPT_VERSION)
    done, call_failures = {}, {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            row = json.loads(line)
            if (row["extractor"], row["model"], row["prompt_version"]) == key:
                done[row["doc_id"]] = row  # later lines win: a re-sent document replaces its failed call
                if (row.get("error") or "").startswith("call failed"):
                    call_failures[row["doc_id"]] = call_failures.get(row["doc_id"], 0) + 1
    failed_calls = {d for d, row in done.items()
                    if (row.get("error") or "").startswith("call failed") and call_failures[d] < 2}
    todo = docs[~docs["doc_id"].isin(set(done) - failed_calls)]
    start = time.perf_counter()
    with cache_path.open("a") as cache:
        for i, row in enumerate(todo.itertuples(), start=1):
            result = extractor.extract(prepare_image(project_root / row.image_path), row.doc_type, row.doc_id)
            record = {**asdict(result), "retries": result.retries}
            cache.write(json.dumps(record, ensure_ascii=False) + "\n")
            cache.flush()
            done[row.doc_id] = record
            if progress_every and i % progress_every == 0:
                print(f"  {i}/{len(todo)} new documents, {(time.perf_counter() - start) / i:.1f} s each", flush=True)
    return pd.DataFrame([done[d] for d in docs["doc_id"]])


# ---------------------------------------------------------------- officer case summary

SUMMARY_SYSTEM = (
    "You write short case summaries for a bank's KYC compliance officer. Use ONLY facts present in the JSON you "
    "are given: never add facts, names, numbers or reasons that are not in it, and never change a number. If a "
    "check is missing from the JSON, say it was not available. Write 4-6 plain sentences: the overall decision "
    "first, then each check with its result, then what the officer should look at. No markdown, no headings.")


def summarize_case(results: dict, llm: Extractor | None = None) -> str:
    """A plain-language summary of all check results for the compliance officer.
    With `llm`: the model writes it (temperature 0, instructed to use only facts from the JSON).
    Without (or if the call fails): a fixed template fills in the same facts."""
    if llm is not None:
        try:
            return llm.complete_text(SUMMARY_SYSTEM, json.dumps(results, indent=2, ensure_ascii=False)).strip()
        except (httpx.HTTPError, KeyError, ValueError, NotImplementedError):
            pass  # fall back to the template below
    return template_summary(results)


def template_summary(results: dict) -> str:
    """Deterministic fallback: one sentence per check, in a fixed order, from the keys that are present."""
    parts = [f"Case {results.get('case_id', '(no id)')}: decision {results.get('decision', 'not available')}."]
    doc = results.get("document")
    if doc:
        parts.append(f"Document recognised as {doc.get('doc_type')} (classifier confidence "
                     f"{doc.get('classifier_confidence', 'n/a')}).")
    forgery = results.get("forgery")
    if forgery:
        parts.append(f"Forgery score {forgery.get('score')} ({forgery.get('band', 'no band given')}).")
    face = results.get("face")
    if face:
        parts.append(f"Face match score {face.get('score')} ({face.get('band', 'no band given')}).")
    extraction = results.get("extraction")
    if extraction:
        parts.append("Fields extracted and validated." if extraction.get("valid")
                     else "Field extraction did not return valid data.")
    rules = results.get("consistency")
    if rules is not None:
        flags = rules.get("flags", [])
        parts.append("All consistency rules passed." if not flags
                     else "Consistency flags: " + "; ".join(flags) + ".")
    for check in ("document", "forgery", "face", "extraction", "consistency"):
        if check not in results:
            parts.append(f"{check.capitalize()} check: not available.")
    return " ".join(parts)
