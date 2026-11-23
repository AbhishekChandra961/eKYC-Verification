"""The KYC decision engine (Phase 7): turns the four check results + what the applicant typed into one outcome.
Phase 13 adds the active liveness result, which the face check carries (outputs["liveness"]).

    policy = load_policy()                                # thresholds from models/*.json (the only I/O here)
    decision = decide(checks, applicant, policy)          # PURE: same inputs -> same decision, no I/O
    decision.outcome, decision.risk_level, decision.risk_score, decision.reasons

Outcomes: AUTO_APPROVED, MANUAL_REVIEW (risk medium or high), RESUBMIT_REQUIRED. The system never rejects on its
own; only an officer rejects. Every reason names its check and carries the values behind it (evidence), so an
officer can see exactly why a case is in the queue.

`checks` maps check_type -> {"status": "ok" | "failed" | "timed_out", "outputs": {...}} as the workers produce
them (Phase 6); a check that is missing counts like one that timed out. `applicant` = {"full_name": ...,
"date_of_birth": "YYYY-MM-DD"} from the application form.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from ekyc import config
from ekyc.schemas import levenshtein, parse_date, strip_diacritics

Outcome = Literal["AUTO_APPROVED", "MANUAL_REVIEW", "RESUBMIT_REQUIRED"]
Effect = Literal["resubmit", "high", "medium", "info"]
REQUIRED_CHECKS = ("doc", "face", "forgery", "extraction")
POINTS = {"high": 50.0, "medium": 20.0, "resubmit": 0.0, "info": 0.0}  # risk score contributions


@dataclass(frozen=True)
class Policy:
    """Every threshold the engine uses. load_policy() fills them from the model JSONs."""
    doc_min_confidence: float  # doc_classifier.json: below = unrecognized document (0.77)
    forgery_review: float  # forgery_detector.json: >= needs review (0.729)
    forgery_suspected: float  # forgery_detector.json: >= forgery suspected (0.857383)
    face_mismatch_below: float  # face_config.json: < mismatch (0.2597)
    face_review_below: float  # face_config.json: < needs review (0.556)
    name_min_similarity: float = 0.85  # fuzzy name match (see names_match)
    expiry_as_of: date | None = None  # the date "expired" is judged against (None = today)
    expired_is_informational: bool = True  # 74 % of the SYNTHETIC templates are expired as of 2026-11-17


def load_policy(model_dir: Path = config.PROJECT_ROOT / "models", **overrides) -> Policy:
    doc = json.loads((model_dir / "doc_classifier.json").read_text())
    forgery = json.loads((model_dir / "forgery_detector.json").read_text())["thresholds"]
    face = json.loads((model_dir / "face_config.json").read_text())["decision"]
    values = {"doc_min_confidence": float(doc["confidence_threshold"]),
              "forgery_review": float(forgery["recall_0.90"]["threshold"]),
              "forgery_suspected": float(forgery["f1_optimal"]["threshold"]),
              "face_mismatch_below": float(face["threshold"]), "face_review_below": float(face["review_below"])}
    return Policy(**(values | overrides))


@dataclass(frozen=True)
class Reason:
    code: str  # stable identifier, e.g. "forgery_suspected"
    message: str  # for the officer / customer
    effect: Effect  # resubmit | high | medium | info
    check_type: str  # doc | face | forgery | extraction | applicant
    evidence: dict = field(default_factory=dict)  # the values behind the reason


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    risk_level: Literal["low", "medium", "high"] | None  # None for RESUBMIT_REQUIRED
    risk_score: float  # 0-100, for sorting the officer queue (higher = look first)
    reasons: tuple[Reason, ...]

    def to_dict(self) -> dict:
        return {"outcome": self.outcome, "risk_level": self.risk_level, "risk_score": self.risk_score,
                "reasons": [asdict(r) for r in self.reasons]}


# ---------------------------------------------------------------- applicant data vs the document

def name_tokens(text: str) -> list[str]:
    """Upper-case words without diacritics or punctuation: 'Velimirović, Krsto' -> ['KRSTO', 'VELIMIROVIC']."""
    return sorted(re.sub(r"[\W\d_]+", " ", strip_diacritics(text or "").upper()).split())


def names_match(typed: str, surname: str | None, given_names: str | None, min_similarity: float) -> tuple[bool, float]:
    """Case-, diacritic- and order-insensitive. A match if every typed word is on the document (the document may
    show more, e.g. a second surname or a patronymic), or if the sorted words are at least `min_similarity`
    similar (1 - edit distance / length: tolerates a typo)."""
    typed_tokens, doc_tokens = name_tokens(typed), name_tokens(f"{given_names or ''} {surname or ''}")
    if not typed_tokens or not doc_tokens:
        return False, 0.0
    if len(typed_tokens) >= 2 and set(typed_tokens) <= set(doc_tokens):
        return True, 1.0
    a, b = " ".join(typed_tokens), " ".join(doc_tokens)
    similarity = 1 - levenshtein(a, b) / max(len(a), len(b))
    return similarity >= min_similarity, round(similarity, 3)


# ---------------------------------------------------------------- per-check rules

def _unavailable(check_type: str, check: dict | None) -> Reason | None:
    status = (check or {}).get("status", "missing")
    if status == "ok":
        return None
    if status == "failed" and check_type == "extraction":
        return Reason("extraction_failed", "Fields could not be read from the document (extraction failed)",
                      "medium", "extraction", {"error": (check or {}).get("error")})
    return Reason(f"{check_type}_{status}", f"The {check_type} check did not complete ({status})", "medium",
                  check_type, {"status": status})


def _doc_reasons(check: dict | None, policy: Policy) -> list[Reason]:
    if (r := _unavailable("doc", check)) is not None:
        return [r]
    o = check["outputs"]
    if o.get("blank"):
        return [Reason("image_unreadable", "Image unreadable: no document visible, please upload a new photo",
                       "resubmit", "doc", {"pixel_std": o.get("pixel_std"), "dark_share": o.get("dark_share")})]
    confidence = o.get("confidence") or 0.0
    if confidence < policy.doc_min_confidence:
        return [Reason("unrecognized_document", "Unrecognized document: please upload a supported ID document",
                       "resubmit", "doc", {"confidence": confidence, "threshold": policy.doc_min_confidence,
                                           "predicted_type": o.get("predicted_type")})]
    return []


def _face_reasons(check: dict | None, policy: Policy) -> list[Reason]:
    if (r := _unavailable("face", check)) is not None:
        return [r]
    o = check["outputs"]
    score = o.get("score")
    if score is None:
        where = "selfie" if (o.get("selfie_face") or {}).get("faces", 0) == 0 else "document photo"
        return [Reason("no_face_found", f"No face found on the {where}: please retake the {where}", "resubmit",
                       "face", {"id_faces": (o.get("id_face") or {}).get("faces"),
                                "selfie_faces": (o.get("selfie_face") or {}).get("faces")})]
    evidence = {"score": score, "mismatch_below": policy.face_mismatch_below, "match_from": policy.face_review_below}
    if score < policy.face_mismatch_below:
        return [Reason("face_mismatch", "The selfie does not match the ID photo", "high", "face", evidence)]
    if score < policy.face_review_below:
        return [Reason("face_uncertain", "Face match uncertain: the selfie needs a manual comparison", "medium",
                       "face", evidence)]
    return []


LIVENESS_RETAKE = ("Please retake your selfie with the camera and follow the on-screen prompts: look at the camera, "
                   "then turn your head to the left, then to the right")  # shown to the customer: neutral wording


def _liveness_reasons(check: dict | None) -> list[Reason]:
    """Phase 13 active liveness, from the face check's outputs["liveness"] (src/ekyc/liveness.py):
    - frames of different people -> high (an officer looks: a retake would just invite another try);
    - any other failure (no clear left/right turn, not facing the camera, no face on a turn frame) -> resubmit;
    - not provided (photo uploaded instead of the camera; also a face result from before Phase 13) -> medium.
    Nothing when the face check itself did not complete or found no face on the selfie: that is already a reason."""
    if (check or {}).get("status") != "ok" or check["outputs"].get("score") is None:
        return []
    live = check["outputs"].get("liveness") or {"status": "not_provided"}
    if live.get("status") == "passed":
        return []
    if live.get("status") != "failed":
        return [Reason("liveness_not_provided", "No head-turn check: a photo was uploaded instead of using the camera",
                       "medium", "face", {"status": live.get("status", "not_provided")})]
    failures = list(live.get("failures") or [])
    evidence = {k: live.get(k) for k in ("failures", "yaw_deg", "turn_deg", "same_person_cosine", "thresholds")}
    reasons = []
    if "different_person" in failures:
        reasons.append(Reason("liveness_different_person", "The head-turn frames do not all show the same person",
                              "high", "face", evidence))
    if [f for f in failures if f != "different_person"]:
        reasons.append(Reason("liveness_failed", LIVENESS_RETAKE, "resubmit", "face", evidence))
    return reasons


def _forgery_reasons(check: dict | None, policy: Policy) -> list[Reason]:
    if (r := _unavailable("forgery", check)) is not None:
        return [r]
    o = check["outputs"]
    score = o.get("score", 0.0)
    evidence = {"score": score, "review_from": policy.forgery_review, "suspected_from": policy.forgery_suspected,
                "top_tile_box": (o.get("top_tile") or {}).get("box_original")}
    if score >= policy.forgery_suspected:
        return [Reason("forgery_suspected", "Forgery suspected: the document shows signs of an edited field",
                       "high", "forgery", evidence)]
    if score >= policy.forgery_review:
        return [Reason("forgery_uncertain", "Possible document edit: needs a manual look", "medium", "forgery",
                       evidence)]
    return []


def _extraction_reasons(check: dict | None) -> list[Reason]:
    if (r := _unavailable("extraction", check)) is not None:
        return [r]
    reasons = []
    for flag in check["outputs"].get("flags", []):
        strong = flag.get("severity") == "strong"
        reasons.append(Reason(f"rule_{flag['rule']}",
                              f"Inconsistent document data ({flag['rule']}): {flag.get('detail') or 'check failed'}",
                              "high" if strong else "medium", "extraction",
                              {"rule": flag["rule"], "severity": flag.get("severity"), "detail": flag.get("detail")}))
    return reasons


def _applicant_reasons(check: dict | None, applicant: dict, policy: Policy, today: date) -> list[Reason]:
    """Typed name / date of birth against the extracted fields, and the expiry date (needs a valid extraction)."""
    if (check or {}).get("status") != "ok":
        return []  # nothing to compare with (the extraction problem is already a reason)
    fields = check["outputs"].get("fields") or {}
    reasons = []
    ok, similarity = names_match(applicant.get("full_name", ""), fields.get("surname"), fields.get("given_names"),
                                 policy.name_min_similarity)
    if not ok:
        reasons.append(Reason("name_mismatch", "The name entered does not match the name on the document", "medium",
                              "applicant", {"similarity": similarity, "min_similarity": policy.name_min_similarity}))
    printed_dob = parse_date(fields.get("birth_date"), "birth_date")
    typed_dob = applicant.get("date_of_birth")
    if printed_dob is None:
        reasons.append(Reason("dob_unverified", "Date of birth could not be read from the document", "medium",
                              "applicant", {"printed": fields.get("birth_date")}))
    elif printed_dob != typed_dob:
        reasons.append(Reason("dob_mismatch", "The date of birth entered does not match the document", "high",
                              "applicant", {"matches": False}))  # the dates themselves are PII: not repeated here
    expiry = parse_date(fields.get("expiry_date"), "expiry_date")
    as_of = policy.expiry_as_of or today
    if expiry is not None and expiry < as_of.isoformat():
        if policy.expired_is_informational:
            reasons.append(Reason("document_expired", f"Document expired on {expiry} (informational for the synthetic "
                                  "test documents)", "info", "extraction", {"expiry_date": expiry, "as_of": str(as_of)}))
        else:
            reasons.append(Reason("document_expired", f"Document expired on {expiry}: please submit a valid document",
                                  "resubmit", "extraction", {"expiry_date": expiry, "as_of": str(as_of)}))
    return reasons


# ---------------------------------------------------------------- combining

def needs_early_resubmit(doc_check: dict | None, policy: Policy) -> bool:
    """True if the doc result alone already means RESUBMIT_REQUIRED (the orchestrator then skips the rest)."""
    return any(r.effect == "resubmit" for r in _doc_reasons(doc_check, policy))


def decide(checks: dict[str, dict], applicant: dict, policy: Policy, today: date | None = None) -> Decision:
    """The decision. Order of precedence:
    1. the document image itself is unusable (blank / unrecognized) -> RESUBMIT_REQUIRED, nothing else matters;
    2. any high reason -> MANUAL_REVIEW high (also when something else asks for a retake: a suspected fraud is
       never just bounced back for another try);
    3. any resubmit reason (e.g. no face on the selfie) -> RESUBMIT_REQUIRED;
    4. any medium reason -> MANUAL_REVIEW medium;
    5. otherwise AUTO_APPROVED (info reasons, such as an expired synthetic document, do not count)."""
    today = today or date.today()
    doc = _doc_reasons(checks.get("doc"), policy)
    if any(r.effect == "resubmit" for r in doc):
        return Decision("RESUBMIT_REQUIRED", None, 0.0, tuple(doc))
    reasons = (doc + _face_reasons(checks.get("face"), policy) + _liveness_reasons(checks.get("face"))
               + _forgery_reasons(checks.get("forgery"), policy)
               + _extraction_reasons(checks.get("extraction"))
               + _applicant_reasons(checks.get("extraction"), applicant, policy, today))
    effects = {r.effect for r in reasons}
    score = _risk_score(reasons, checks)
    if "high" in effects:
        return Decision("MANUAL_REVIEW", "high", score, tuple(reasons))
    if "resubmit" in effects:
        return Decision("RESUBMIT_REQUIRED", None, score, tuple(reasons))
    if "medium" in effects:
        return Decision("MANUAL_REVIEW", "medium", score, tuple(reasons))
    return Decision("AUTO_APPROVED", "low", score, tuple(reasons))


def _risk_score(reasons: list[Reason], checks: dict) -> float:
    """50 per high reason + 20 per medium reason, plus up to 10 from the forgery score and up to 10 from a weak face
    match as tie-breakers, capped at 100. Only used to order the officer queue."""
    score = sum(POINTS[r.effect] for r in reasons)
    forgery = ((checks.get("forgery") or {}).get("outputs") or {}).get("score")
    face = ((checks.get("face") or {}).get("outputs") or {}).get("score")
    score += 10 * (forgery or 0.0) + (10 * (1 - max(0.0, min(1.0, face))) if face is not None else 0.0)
    return round(min(100.0, score), 1)


def official_summary(application_id: str, decision: Decision, checks: dict[str, dict]) -> str:
    """The template case summary: the official record (an LLM note is optional and only an aid). Plain sentences
    from the decision and the check outputs; no names, dates of birth or document numbers."""
    lines = [f"Application {application_id}: {decision.outcome.replace('_', ' ').lower()}"
             + (f" (risk {decision.risk_level}, score {decision.risk_score})." if decision.risk_level else ".")]
    o = {k: (v or {}).get("outputs") or {} for k, v in checks.items()}
    if "doc" in o:
        lines.append(f"Document: {o['doc'].get('doc_type') or 'not recognized'} (confidence {o['doc'].get('confidence')}).")
    if "forgery" in o and o["forgery"]:
        lines.append(f"Forgery score {o['forgery'].get('score')} ({o['forgery'].get('band')}).")
    if "face" in o and o["face"]:
        lines.append(f"Face match score {o['face'].get('score')} ({o['face'].get('band')}).")
        live = o["face"].get("liveness") or {"status": "not_provided"}
        turns = live.get("turn_deg") or {}
        lines.append(f"Liveness: {live.get('status', 'not_provided').replace('_', ' ')}"
                     + (f" (turns {turns.get('left')} / {turns.get('right')} degrees)" if turns else "") + ".")
    if "extraction" in checks:
        status = checks["extraction"].get("status")
        lines.append("Document fields read and checked." if status == "ok" else f"Field extraction: {status}.")
    findings = [r for r in decision.reasons if r.effect != "info"]
    lines.append("Findings: " + "; ".join(f"[{r.effect}] {r.message}" for r in findings) + "." if findings
                 else "No findings.")
    notes = [r.message for r in decision.reasons if r.effect == "info"]
    if notes:
        lines.append("Notes: " + "; ".join(notes) + ".")
    return " ".join(lines)
