"""Deterministic consistency rules for ID documents (Phase 5): MRZ check digits (ICAO 9303), MRZ against the
printed (visual) fields, and date logic.

Why: a pixel-level forgery model misses most Crop_and_Replace edits (real printed text pasted from another
document, Phase 3B), but a pasted surname or date no longer agrees with the MRZ, whose check digits tie it together.

    results = run_rules(fields, doc_type)     # fields: canonical dict (schemas.IDFields / ground_truth_table)
    flags = failed_flags(results)             # names of failed rules whose level is "flag"

Each rule returns "pass", "fail" or "skip" (not applicable: no MRZ on this document type, or a value missing).
A rule's LEVEL is "flag" (a failure sends the case to review) or "info" (reported only). Rules that false-flag
too many GENUINE documents are demoted to "info" (see RULE_LEVEL_OVERRIDES and notebook 05).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from ekyc.schemas import DATE_FIELDS, MRZ_DOC_TYPES, parse_date, strip_diacritics

# ---------------------------------------------------------------- ICAO 9303 check digits + TD3 layout

_WEIGHTS = (7, 3, 1)


def check_digit(text: str) -> str:
    """ICAO 9303 check digit: digits count as themselves, A-Z as 10-35, '<' as 0; each value is multiplied by
    7, 3, 1, 7, 3, 1, ... and the sum's last digit is the check digit."""
    def value(c: str) -> int:
        if c.isdigit():
            return int(c)
        if "A" <= c <= "Z":
            return ord(c) - ord("A") + 10
        return 0  # '<' filler
    return str(sum(value(c) * _WEIGHTS[i % 3] for i, c in enumerate(text)) % 10)


@dataclass
class TD3:
    """The fields of a passport MRZ (TD3: two lines of 44 characters)."""
    surname: str
    given_names: str
    number: str  # document number with its fillers removed
    number_raw: str
    number_check: str
    nationality: str
    birth: str  # YYMMDD
    birth_check: str
    sex: str
    expiry: str  # YYMMDD
    expiry_check: str
    personal: str
    personal_check: str
    composite_check: str
    line1: str
    names_full: bool  # the 39-character name field has no filler left: ICAO truncates longer names here


def repair_line1_fillers(line1: str) -> tuple[str, bool]:
    """Fix a TD3 line 2 whose only fault is the NUMBER of '<' fillers in the personal-number field (LLMs miscount
    long filler runs; 45 or 43 characters would shift every position after it). Positions 1-28 (document number,
    nationality, dates, sex and their check digits) and the last two characters (check digits) are kept; the
    personal-number field in between keeps its characters and is re-padded with '<' to 14. No data character is
    changed, so a real error still fails its check digit. Returns (line, repaired)."""
    # only near-misses that still end in the composite check digit (always a digit): a cut-off line is not repaired
    if line1 is None or len(line1) == 44 or not 40 <= len(line1) <= 48 or not line1[-1].isdigit():
        return line1, False
    personal = line1[28:-2].rstrip("<")
    if len(personal) > 14:
        return line1, False  # more than filler is wrong: leave it to the format rule
    return line1[:28] + personal.ljust(14, "<") + line1[-2:], True


def parse_td3(line0: str, line1: str) -> TD3 | None:
    """Split the two TD3 lines into fields; None if line 2 is not 44 characters even after
    repair_line1_fillers (positions would be wrong). Line 1 positions: 1-2 type, 3-5 state, 6-44 names
    (SURNAME<<GIVEN<NAMES<<<...)."""
    if line0 is None or line1 is None:
        return None
    line1, _ = repair_line1_fillers(line1)
    if len(line1) != 44:
        return None
    names = line0[5:].rstrip("<")
    surname, _, given = names.partition("<<")
    return TD3(surname=surname.replace("<", " ").strip(), given_names=given.replace("<", " ").strip(),
               number=line1[0:9].replace("<", ""), number_raw=line1[0:9], number_check=line1[9],
               nationality=line1[10:13], birth=line1[13:19], birth_check=line1[19], sex=line1[20],
               expiry=line1[21:27], expiry_check=line1[27], personal=line1[28:42], personal_check=line1[42],
               composite_check=line1[43], line1=line1, names_full=len(line0) >= 44 and line0[43] != "<")


def _mrz_name(text: str) -> str:
    """A printed name in MRZ form: diacritics dropped, upper case, anything but A-Z turned into spaces."""
    return " ".join(re.sub(r"[^A-Z]+", " ", strip_diacritics(text).upper()).split())


def _mrz_date(yymmdd: str, field: str) -> str | None:
    """MRZ date YYMMDD -> ISO, with the same century rule as printed two-digit years."""
    if not re.fullmatch(r"\d{6}", yymmdd or ""):
        return None
    return parse_date(f"{yymmdd[4:6]}.{yymmdd[2:4]}.{yymmdd[0:2]}", field)


# ---------------------------------------------------------------- the rules

@dataclass
class RuleResult:
    rule: str
    status: str  # "pass" | "fail" | "skip"
    level: str  # "flag" | "info"
    detail: str = ""


RULES = {  # name -> what it checks (shown to the officer)
    "mrz_format": "MRZ present and line 2 has the 44 characters of a passport MRZ",
    "mrz_check_document_number": "MRZ check digit of the document number",
    "mrz_check_birth_date": "MRZ check digit of the date of birth",
    "mrz_check_expiry_date": "MRZ check digit of the date of expiry",
    "mrz_check_composite": "MRZ composite check digit (number, birth, expiry and personal-number fields together)",
    "mrz_vs_surname": "surname printed on the page = surname in the MRZ",
    "mrz_vs_given_names": "given names printed on the page = given names in the MRZ (MRZ may truncate)",
    "mrz_vs_birth_date": "date of birth printed on the page = date of birth in the MRZ",
    "mrz_vs_document_number": "document number printed on the page = document number in the MRZ",
    "mrz_vs_expiry_date": "date of expiry printed on the page = date of expiry in the MRZ",
    "dates_parseable": "every printed date is a real calendar date",
    "date_order": "date of birth < date of issue < date of expiry",
}
MRZ_RULES = tuple(r for r in RULES if r.startswith("mrz_"))
# How much a FAILED rule weighs for the decision engine (Phase 5 findings, CLAUDE.md). "strong": reliable even on
# LLM-extracted fields (0-3.4 % false flags on genuine test passports): forgery-suspected-level evidence.
# "review": names and MRZ format/birth date suffer from 7B reading errors (up to 27 % false flags): needs review.
RULE_SEVERITY = {"mrz_check_document_number": "strong", "mrz_check_birth_date": "strong",
                 "mrz_check_expiry_date": "strong", "mrz_check_composite": "strong", "mrz_vs_document_number": "strong",
                 "mrz_vs_expiry_date": "strong", "date_order": "strong",
                 "mrz_format": "review", "mrz_vs_surname": "review", "mrz_vs_given_names": "review",
                 "mrz_vs_birth_date": "review", "dates_parseable": "review"}
assert set(RULE_SEVERITY) == set(RULES)
# Rules demoted to "info" for a document type because they false-flag > 5 % of GENUINE ground-truth documents
# there (filled in from the validation in notebook 05; key = (rule, doc_type), or (rule, "*") for all types).
RULE_LEVEL_OVERRIDES: dict[tuple[str, str], str] = {}


def rule_level(rule: str, doc_type: str) -> str:
    return RULE_LEVEL_OVERRIDES.get((rule, doc_type), RULE_LEVEL_OVERRIDES.get((rule, "*"), "flag"))


def _text(value) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    value = str(value).strip()
    return value or None


def run_rules(fields: dict, doc_type: str) -> list[RuleResult]:
    """Every rule for one document. `fields` holds canonical values (missing / NaN = not available)."""
    f = {k: _text(v) for k, v in fields.items()}
    out: dict[str, tuple[str, str]] = {}

    # --- MRZ rules: only for document types that carry an MRZ
    if doc_type not in MRZ_DOC_TYPES:
        out.update({r: ("skip", "no MRZ on this document type") for r in MRZ_RULES})
    else:
        mrz = parse_td3(f.get("mrz_line0"), f.get("mrz_line1"))
        if mrz is None:
            out["mrz_format"] = ("fail", "MRZ missing or line 2 is not 44 characters")
            out.update({r: ("skip", "MRZ could not be parsed") for r in MRZ_RULES if r != "mrz_format"})
        else:
            repaired = repair_line1_fillers(f.get("mrz_line1"))[1]
            out["mrz_format"] = ("pass", "line 2 filler count repaired" if repaired else "")
            for rule, data, check in (("mrz_check_document_number", mrz.number_raw, mrz.number_check),
                                      ("mrz_check_birth_date", mrz.birth, mrz.birth_check),
                                      ("mrz_check_expiry_date", mrz.expiry, mrz.expiry_check),
                                      ("mrz_check_composite", mrz.line1[0:10] + mrz.line1[13:20] + mrz.line1[21:43],
                                       mrz.composite_check)):
                ok = check_digit(data) == check
                out[rule] = ("pass" if ok else "fail", "" if ok else f"expected {check_digit(data)}, MRZ has {check}")
            out["mrz_vs_surname"] = _same_name(f.get("surname"), mrz.surname, truncated=False)
            out["mrz_vs_given_names"] = _same_name(f.get("given_names"), mrz.given_names, truncated=mrz.names_full)
            out["mrz_vs_birth_date"] = _same_date(f.get("birth_date"), mrz.birth, "birth_date")
            out["mrz_vs_expiry_date"] = _same_date(f.get("expiry_date"), mrz.expiry, "expiry_date")
            number = f.get("document_number")
            if number is None:
                out["mrz_vs_document_number"] = ("skip", "no printed document number")
            else:
                printed = re.sub(r"\s+", "", number).upper()
                ok = printed == mrz.number
                out["mrz_vs_document_number"] = ("pass" if ok else "fail", "" if ok else f"page {printed} vs MRZ {mrz.number}")

    # --- date rules: every document type
    dates = {k: f.get(k) for k in DATE_FIELDS if f.get(k) is not None}
    parsed = {k: parse_date(v, k) for k, v in dates.items()}
    unreadable = [k for k, v in parsed.items() if v is None]
    if not dates:
        out["dates_parseable"] = ("skip", "no dates")
    else:
        out["dates_parseable"] = ("fail", "not a date: " + ", ".join(f"{k}={dates[k]!r}" for k in unreadable)) \
            if unreadable else ("pass", "")
    order = [parsed[k] for k in DATE_FIELDS if parsed.get(k)]
    if len(order) < 2:
        out["date_order"] = ("skip", "fewer than two readable dates")
    else:
        ok = all(a < b for a, b in zip(order, order[1:]))
        out["date_order"] = ("pass" if ok else "fail", "" if ok else
                             " / ".join(f"{k} {parsed[k]}" for k in DATE_FIELDS if parsed.get(k)))
    return [RuleResult(r, *out[r][:1], rule_level(r, doc_type), out[r][1]) for r in RULES]


def _same_name(printed: str | None, in_mrz: str, truncated: bool) -> tuple[str, str]:
    """Printed name (in MRZ form) = MRZ name. If the MRZ name field is full, the MRZ may have cut the printed
    name short (even mid-word), so then the printed name only has to START with the MRZ name."""
    if printed is None:
        return "skip", "no printed value"
    page = _mrz_name(printed)
    ok = page == in_mrz or (truncated and in_mrz != "" and page.startswith(in_mrz))
    return ("pass", "") if ok else ("fail", f"page {page!r} vs MRZ {in_mrz!r}")


def _same_date(printed: str | None, yymmdd: str, field: str) -> tuple[str, str]:
    if printed is None:
        return "skip", "no printed value"
    page, mrz = parse_date(printed, field), _mrz_date(yymmdd, field)
    if page is None or mrz is None:
        return "fail", f"unreadable date (page {printed!r}, MRZ {yymmdd!r})"
    return ("pass", "") if page == mrz else ("fail", f"page {page} vs MRZ {mrz}")


def failed_flags(results: list[RuleResult]) -> list[str]:
    """Names of the failed rules whose level is 'flag' (these send the case to manual review)."""
    return [r.rule for r in results if r.status == "fail" and r.level == "flag"]


def rules_table(documents: pd.DataFrame) -> pd.DataFrame:
    """Run every rule on every row of `documents` (index doc_id, columns doc_type + canonical fields).
    Long format: one row per (doc_id, rule) with doc_type, status, level and detail."""
    rows = []
    for doc_id, row in documents.iterrows():
        for r in run_rules(row.to_dict(), row["doc_type"]):
            rows.append({"doc_id": doc_id, "doc_type": row["doc_type"], "rule": r.rule, "status": r.status,
                         "level": r.level, "detail": r.detail})
    return pd.DataFrame(rows)
