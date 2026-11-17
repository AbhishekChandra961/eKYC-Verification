"""Canonical ID-document fields (Phase 5): the Pydantic schema, the per-document-type mapping from SIDTD
annotation field names, and the normalisation used to compare extracted values with the ground truth.

Every document type prints a different subset of fields under its own labels. The extraction model returns
the CANONICAL fields below (all optional: null = not printed on this document), and DOC_FIELD_MAP says which
annotation field(s) hold each canonical value per document type.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

CANONICAL_FIELDS = ("surname", "given_names", "birth_date", "gender", "nationality", "document_number",
                    "personal_number", "issue_date", "expiry_date", "birth_place", "authority", "mrz_line0",
                    "mrz_line1")
DATE_FIELDS = ("birth_date", "issue_date", "expiry_date")
NUMBER_FIELDS = ("document_number", "personal_number")
MRZ_FIELDS = ("mrz_line0", "mrz_line1")


class IDFields(BaseModel):
    """The fields an extractor returns. Values are copied as printed (dates in the document's own format);
    a field that is not printed on the document is null."""

    model_config = ConfigDict(extra="forbid")  # an unknown key is a validation error (triggers a retry)

    surname: str | None = Field(None, description="family name(s) as printed, in Latin script")
    given_names: str | None = Field(None, description="given name(s) as printed, in Latin script")
    birth_date: str | None = Field(None, description="date of birth exactly as printed")
    gender: str | None = Field(None, description="sex as printed, e.g. M, F, K/M, V/M")
    nationality: str | None = Field(None, description="nationality as printed")
    document_number: str | None = Field(None, description="number of this card/passport")
    personal_number: str | None = Field(None, description="the holder's national personal identification number")
    issue_date: str | None = Field(None, description="date of issue exactly as printed")
    expiry_date: str | None = Field(None, description="date of expiry exactly as printed")
    birth_place: str | None = Field(None, description="place of birth as printed")
    authority: str | None = Field(None, description="issuing authority / office as printed")
    mrz_line0: str | None = Field(None, description="first machine-readable-zone line, character by character")
    mrz_line1: str | None = Field(None, description="second machine-readable-zone line, character by character")

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value):
        """Trim whitespace; empty strings and 'null'-like words mean 'not printed'."""
        if isinstance(value, str):
            value = value.strip()
            if value == "" or value.lower() in {"null", "none", "n/a", "na", "-"}:
                return None
        return value

    @field_validator(*MRZ_FIELDS)
    @classmethod
    def _mrz_characters(cls, value):
        """An MRZ line only contains A-Z, 0-9 and the filler '<'. Spaces are removed, letters upper-cased and
        diacritics dropped the way passports print them (Đ -> D, Ņ -> N: models tend to copy the visual name's
        letters); anything else is an error, so the extractor is asked again. The LENGTH is not enforced here:
        LLMs often miscount the long '<' fillers, and the check-digit rules (consistency.py) judge the content."""
        if value is None:
            return None
        value = strip_diacritics(re.sub(r"\s+", "", value).upper().replace("«", "<<").replace("‹", "<"))
        if not re.fullmatch(r"[A-Z0-9<]+", value):
            raise ValueError("an MRZ line may only contain A-Z, 0-9 and '<' (copy it character by character)")
        return value


# ---------------------------------------------------------------- per-document-type mapping
# canonical field -> annotation field, or a tuple of annotation fields joined in that order. Decisions:
# - number vs id_number: their meaning differs per type (see the comments); the canonical names are
#   document_number = the number OF THE DOCUMENT, personal_number = the holder's national personal code.
# - aze_passport and grc_passport print names twice: in the national form and as a Latin transliteration.
#   The canonical names are the transliteration lines (*_eng), which is what the MRZ encodes.
DOC_FIELD_MAP: dict[str, dict[str, str | tuple[str, ...]]] = {
    "alb_id": {"surname": "surname", "given_names": "name", "birth_date": "birth_date", "gender": "gender",
               "nationality": "nationality", "document_number": "number",  # "card no."
               "personal_number": "id_number",  # "personal no.", e.g. J11120296E
               "issue_date": "issue_date", "expiry_date": "expiry_date", "birth_place": "birth_place",
               "authority": "authority"},
    "aze_passport": {"surname": "surname_eng", "given_names": "name_eng", "birth_date": "birth_date",
                     "gender": "gender", "nationality": "nationality/nationality_eng",
                     "document_number": "number",  # "Passport No"
                     "personal_number": "id_number",  # "Personal No" (FIN code), e.g. 5188L2V
                     "issue_date": "issue_date", "expiry_date": "expiry_date", "birth_place": "birth_place",
                     "authority": "authority", "mrz_line0": "mrz_line0", "mrz_line1": "mrz_line1"},
    "esp_id": {"surname": ("surname", "surname_second"),  # PRIMER + SEGUNDO APELLIDO
               "given_names": "name", "birth_date": "birth_date", "gender": "gender", "nationality": "nationality",
               "document_number": "id_number",  # IDESP: the card's own number, e.g. AXT103442 (!)
               "personal_number": "number",  # DNI NÚM: the holder's DNI, e.g. 48518051Y (!)
               "issue_date": "issue_date", "expiry_date": "expiry_date"},
    "est_id": {"surname": "surname", "given_names": "name", "birth_date": "birth_date", "gender": "gender",
               "nationality": "nationality", "document_number": "number",  # DOCUMENT NUMBER, e.g. AA6557729
               "personal_number": "id_number",  # ISIKUKOOD / personal code, 11 digits
               "expiry_date": "expiry_date"},
    "fin_id": {"surname": "surname", "given_names": "name", "birth_date": "birth_date", "gender": "gender",
               "nationality": "nationality", "document_number": "number",  # Korttinumero / card number
               "personal_number": ("birth_date_2", "code"),  # henkilötunnus = DDMMYY + "-927N"
               "issue_date": "issue_date", "expiry_date": "expiry_date"},
    "grc_passport": {"surname": "surname_eng", "given_names": "name_eng", "birth_date": "birth_date",
                     "gender": "gender", "nationality": "nationality", "document_number": "number",
                     "issue_date": "issue_date", "expiry_date": "expiry_date", "birth_place": "birth_place_eng",
                     "authority": "authority", "mrz_line0": "mrz_line0", "mrz_line1": "mrz_line1"},
    "lva_passport": {"surname": "surname", "given_names": "name", "birth_date": "birth_date", "gender": "gender",
                     "nationality": "nationality", "document_number": "number",  # Passport No.
                     "personal_number": "id_number",  # Personas kods, e.g. 280974-14045
                     "issue_date": "issue_date", "expiry_date": "expiry_date", "birth_place": "birth_place",
                     "authority": ("authority_line0", "authority_line1"),
                     "mrz_line0": "mrz_line0", "mrz_line1": "mrz_line1"},
    "rus_internalpassport": {"surname": "surname", "given_names": ("name", "patronymic"),
                             "birth_date": "birth_date", "gender": "gender",
                             "document_number": "number",  # series + number printed vertically, e.g. 45 98 647461
                             "birth_place": ("birth_place_line0", "birth_place_line1", "birth_place_line2")},
    "srb_passport": {"surname": "surname", "given_names": "name", "birth_date": "birth_date", "gender": "gender",
                     "nationality": "nationality", "document_number": "number",  # Passport No
                     "personal_number": "id_number",  # JMBG / personal No, 13 digits
                     "issue_date": "issue_date", "expiry_date": "expiry_date", "birth_place": "birth_place",
                     "authority": "authority", "mrz_line0": "mrz_line0", "mrz_line1": "mrz_line1"},
    "svk_id": {"surname": "surname", "given_names": "name", "birth_date": "birth_date", "gender": "gender",
               "nationality": "nationality", "document_number": "number",  # Číslo / No., e.g. EU394022
               "personal_number": "id_number",  # Rodné číslo / Personal No., e.g. 550522/3941
               "issue_date": "issue_date", "expiry_date": "expiry_date", "authority": "issue_place"},  # Vydal
}
MRZ_DOC_TYPES = tuple(t for t, m in DOC_FIELD_MAP.items() if "mrz_line1" in m)
# annotation fields deliberately not mapped (duplicates, layout codes, or not part of the canonical schema)
UNMAPPED_FIELDS = {"photo", "signature", "face", "type", "code", "height", "number2", "number3", "birth_date_22",
                   "expiry_date_2", "expiry_date2", "residence_line0", "residence_line1", "name_code",
                   "birth_country", "authority_eng", "surname (aze, grc: national form)",
                   "name (aze, grc: national form)", "birth_place (grc: Greek form)"}


def mapping_table() -> pd.DataFrame:
    """The mapping as a table: one row per document type, one column per canonical field ("-" = not printed)."""
    rows = {t: {f: " + ".join(s) if isinstance(s, tuple) else s for f, s in m.items()} for t, m in DOC_FIELD_MAP.items()}
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=list(CANONICAL_FIELDS)).fillna("-")


def canonical_of(doc_type: str, annotation_field: str) -> str | None:
    """The canonical field an annotation field feeds (e.g. esp_id 'number' -> 'personal_number'), or None."""
    for canonical, source in DOC_FIELD_MAP[doc_type].items():
        if annotation_field == source or (isinstance(source, tuple) and annotation_field in source):
            return canonical
    return None


def ground_truth_table(fields_gt: pd.DataFrame) -> pd.DataFrame:
    """Canonical ground truth: one row per document (index doc_id), columns doc_type + CANONICAL_FIELDS.
    `fields_gt` is data/processed/fields_ground_truth.csv (doc_id, field_name, value, box)."""
    wide = fields_gt.pivot_table(index="doc_id", columns="field_name", values="value", aggfunc="first")
    rows = {}
    for doc_id, annotation in wide.iterrows():
        doc_type = doc_id.rsplit("_", 1)[0]
        row = {"doc_type": doc_type}
        for canonical, source in DOC_FIELD_MAP[doc_type].items():
            parts = [annotation.get(s) for s in (source if isinstance(source, tuple) else (source,))]
            parts = [str(p).strip() for p in parts if isinstance(p, str) and p.strip()]
            joiner = "" if (doc_type, canonical) == ("fin_id", "personal_number") else " "
            row[canonical] = joiner.join(parts) if parts else None
        rows[doc_id] = row
    return pd.DataFrame.from_dict(rows, orient="index").reindex(columns=["doc_type", *CANONICAL_FIELDS])


# ---------------------------------------------------------------- normalisation for comparison
_MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
                                         "NOV", "DEC"), start=1)}
_MONTHS |= {"OKT": 10, "MAI": 5, "DEZ": 12, "MÄR": 3}  # variants seen on SIDTD passports (grc: "13 Okt 74")


def _year(two_or_four: str, field: str, today: date) -> int:
    """Four digits as they are; two digits get a century: expiry dates are in the 2000s, birth and issue dates
    in the 2000s only if that is not in the future (so '87' -> 1987, '19' -> 2019)."""
    year = int(two_or_four)
    if len(two_or_four) == 4:
        return year
    if field == "expiry_date" or 2000 + year <= today.year:
        return 2000 + year
    return 1900 + year


def parse_date(text: str | None, field: str = "birth_date", today: date | None = None) -> str | None:
    """A printed date -> ISO 'YYYY-MM-DD', or None if it cannot be read. Handles the SIDTD formats
    '20-11-1991', '14.08.1994', '28.09.1974.', '01. 04. 1981', '31 01 1971', '02 Jan 87' (also 'ΙΑΝ/JAN'),
    '140915' (DDMMYY) and ISO itself."""
    if not text or not isinstance(text, str):
        return None
    today = today or date.today()
    s = text.strip().rstrip(".").upper()
    try:
        if m := re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s):  # already ISO
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        if m := re.fullmatch(r"(\d{1,2})\s*[.\-/ ]\s*(\d{1,2})\s*[.\-/ ]\s*(\d{4}|\d{2})", s):
            return date(_year(m[3], field, today), int(m[2]), int(m[1])).isoformat()
        if m := re.fullmatch(r"(\d{1,2})\s+(?:\S+/)?([A-ZÄ]{3})[A-Z]*\.?\s+(\d{4}|\d{2})", s):
            if m[2] in _MONTHS:
                return date(_year(m[3], field, today), _MONTHS[m[2]], int(m[1])).isoformat()
        if m := re.fullmatch(r"(\d{2})(\d{2})(\d{2})", s):  # compact DDMMYY on the card face
            return date(_year(m[3], field, today), int(m[2]), int(m[1])).isoformat()
        if m := re.fullmatch(r"(\d{2})(\d{2})(\d{4})", s):  # DDMMYYYY: a printed date with its spaces dropped
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
    except ValueError:  # e.g. month 13: not a real date
        return None
    return None


_GENDER = {"M": "M", "F": "F", "МУЖ": "M", "ЖЕН": "F",
           # national letters of the 10 SIDTD types, for answers that give only the first half of 'K/M':
           "K": "M", "Q": "F",  # aze: kişi / qadın
           "V": "M", "S": "F",  # lva: vīrietis / sieviete
           "N": "F", "Ž": "F"}  # est/fin: naine/nainen; srb: ženski


def normalize_gender(text: str | None) -> str | None:
    """'K/M', 'V/M', 'M / M', 'M' -> 'M'; 'Q/F', 'S/F', 'Ž / F', 'F' -> 'F'; 'МУЖ.' -> 'M', 'ЖЕН.' -> 'F'.
    The international letter is the part after the last '/'; a lone national letter (e.g. 'Ž') is mapped too.
    The national-letter map only covers the 10 SIDTD document types (e.g. 'K' means female in Swedish)."""
    if not text:
        return None
    s = text.strip().upper().split("/")[-1].strip().rstrip(".")
    return _GENDER.get(s, s)


# Greek and Cyrillic capitals that look exactly like Latin ones: on the image "Α.Ε.Α." (Greek) and "A.E.A."
# (Latin) cannot be told apart, so the normalized comparison treats them as the same letter.
_HOMOGLYPHS = str.maketrans("ΑΒΕΖΗΙΚΜΝΟΡΤΥΧАВЕКМНОРСТУХ", "ABEZHIKMNOPTYXABEKMHOPCTYX")


def normalize_value(field: str, value: str | None) -> str | None:
    """The comparison form of a value: dates in ISO, gender as M/F, numbers and MRZ lines without any
    whitespace, everything else case-folded with whitespace trimmed and collapsed, and look-alike Greek/Cyrillic
    capitals folded to Latin. Diacritics are KEPT (Mikuš and Mikus are different spellings). The first MRZ line
    ignores the number of trailing '<' fillers (pure padding after the names; LLMs miscount them); the second
    MRZ line is compared strictly (its fillers are positional). Spaces next to punctuation are ignored in text
    fields. Unparseable dates fall back to the text form."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None
    if field in DATE_FIELDS:
        return parse_date(text, field) or text.casefold()
    if field == "gender":
        return normalize_gender(text)
    if field == "mrz_line0":
        return text.replace(" ", "").upper().rstrip("<")
    if field in NUMBER_FIELDS or field in MRZ_FIELDS:
        return text.replace(" ", "").upper()
    text = re.sub(r"\s*([.,/\-])\s*", r"\1", text)  # "3. NODAĻA" = "3.NODAĻA": spacing around punctuation
    return text.upper().translate(_HOMOGLYPHS).casefold()


def levenshtein(a: str, b: str) -> int:
    """Edit distance: the fewest single-character insertions, deletions or substitutions turning a into b."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def cer(predicted: str | None, truth: str) -> float:
    """Character error rate = edit distance / length of the truth (0 = perfect; a missing value counts 1.0)."""
    if not predicted:
        return 1.0
    return levenshtein(predicted, truth) / max(len(truth), 1)


def compare_fields(predicted: dict, truth: dict) -> pd.DataFrame:
    """One row per canonical field that the TRUTH has (printed on this document type): the two values,
    exact match (identical after trimming the ends), normalized match (normalize_value) and CER on the
    normalized forms. Fields the truth lacks but the prediction fills are reported as 'spurious'."""
    rows = []
    for field in CANONICAL_FIELDS:
        t, p = truth.get(field), predicted.get(field)
        t = None if t is None or (isinstance(t, float) and pd.isna(t)) else str(t)
        p = None if p is None or (isinstance(p, float) and pd.isna(p)) else str(p)
        if t is None:
            if p is not None:
                rows.append({"field": field, "truth": None, "predicted": p, "exact": False, "normalized": False,
                             "cer": None, "spurious": True})
            continue
        nt, np_ = normalize_value(field, t), normalize_value(field, p)
        rows.append({"field": field, "truth": t, "predicted": p, "exact": p is not None and p.strip() == t.strip(),
                     "normalized": np_ is not None and np_ == nt, "cer": cer(np_, nt), "spurious": False})
    return pd.DataFrame(rows)


def strip_diacritics(text: str) -> str:
    """'VELIMIROVIĆ' -> 'VELIMIROVIC', 'AINĀRS' -> 'AINARS' (used by the MRZ name cross-check)."""
    special = {"Ə": "A", "ə": "a", "Ø": "O", "ø": "o", "Æ": "AE", "æ": "ae", "ß": "SS", "Đ": "D", "đ": "d",
               "Ł": "L", "ł": "l", "Þ": "TH", "þ": "th"}
    text = "".join(special.get(c, c) for c in text)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def score_extractions(results: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Compare a batch of extractions with the canonical ground truth: one row per (document, field printed on
    it) with doc_id, doc_type and the compare_fields columns. `results` has doc_id, doc_type and fields (a dict,
    or None for an invalid extraction: every field then counts as missing); `truth` = ground_truth_table(...)."""
    tables = []
    for row in results.itertuples():
        predicted = row.fields if isinstance(row.fields, dict) else {}
        table = compare_fields(predicted, truth.loc[row.doc_id].to_dict())
        table.insert(0, "doc_id", row.doc_id)
        table.insert(1, "doc_type", row.doc_type)
        tables.append(table)
    return pd.concat(tables, ignore_index=True)
