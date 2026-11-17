"""Table-driven tests of the decision engine (Phase 7): one row per rule branch (with the threshold boundaries),
the precedence between rules, the risk score order, the policy loader and the Phase 6 smoke-test cases."""

import copy
from datetime import date

import pytest

from ekyc import decision
from ekyc.decision import Policy, decide

POLICY = Policy(doc_min_confidence=0.77, forgery_review=0.729, forgery_suspected=0.857383,
                face_mismatch_below=0.2597, face_review_below=0.556)
TODAY = date(2026, 11, 17)
APPLICANT = {"full_name": "Krsto Velimirovic", "date_of_birth": "1974-08-15"}


def clean_checks():
    """A clean Serbian passport application (outputs shaped like the Phase 6 workers')."""
    return {
        "doc": {"status": "ok", "outputs": {"blank": False, "recognized": True, "doc_type": "srb_passport",
                                            "confidence": 0.9988, "predicted_type": "srb_passport"}},
        "face": {"status": "ok", "outputs": {"score": 0.92, "band": "match", "id_face": {"faces": 2},
                                             "selfie_face": {"faces": 1}}},
        "forgery": {"status": "ok", "outputs": {"score": 0.56, "band": "pass", "top_tile": {"box_original": [1, 2, 3, 4]}}},
        "extraction": {"status": "ok", "outputs": {"fields": {"surname": "VELIMIROVIĆ", "given_names": "KRSTO",
                                                              "birth_date": "15.08.1974", "expiry_date": "12.08.2030"},
                                                   "flags": []}},
    }


def setter(path, value):
    """A change to the clean case: path like 'face.outputs.score' (a value of DELETE removes the key)."""
    def apply(checks, applicant):
        root, *keys = path.split(".")
        target = applicant if root == "applicant" else checks
        if root != "applicant":
            keys = [root, *keys]
        for key in keys[:-1]:
            target = target[key]
        if value is DELETE:
            del target[keys[-1]]
        else:
            target[keys[-1]] = value
    return apply


DELETE = object()
STRONG = [{"rule": "mrz_vs_expiry_date", "severity": "strong", "detail": "page 2030-08-12 vs MRZ 2031-08-12"}]
REVIEW = [{"rule": "mrz_vs_surname", "severity": "review", "detail": "page 'X' vs MRZ 'Y'"}]

CASES = [  # (name, changes, outcome, risk level, reason codes in order)
    ("all clear", [], "AUTO_APPROVED", "low", []),
    # --- doc
    ("doc blank image", [setter("doc.outputs.blank", True)], "RESUBMIT_REQUIRED", None, ["image_unreadable"]),
    ("doc low confidence", [setter("doc.outputs.confidence", 0.60)], "RESUBMIT_REQUIRED", None, ["unrecognized_document"]),
    ("doc confidence at the threshold", [setter("doc.outputs.confidence", 0.77)], "AUTO_APPROVED", "low", []),
    ("doc timed out", [setter("doc.status", "timed_out")], "MANUAL_REVIEW", "medium", ["doc_timed_out"]),
    # --- face
    ("no face on the selfie", [setter("face.outputs.score", None), setter("face.outputs.selfie_face", {"faces": 0})],
     "RESUBMIT_REQUIRED", None, ["no_face_found"]),
    ("face mismatch", [setter("face.outputs.score", 0.10)], "MANUAL_REVIEW", "high", ["face_mismatch"]),
    ("face just below mismatch boundary", [setter("face.outputs.score", 0.2596)], "MANUAL_REVIEW", "high", ["face_mismatch"]),
    ("face at the mismatch boundary", [setter("face.outputs.score", 0.2597)], "MANUAL_REVIEW", "medium", ["face_uncertain"]),
    ("face uncertain", [setter("face.outputs.score", 0.40)], "MANUAL_REVIEW", "medium", ["face_uncertain"]),
    ("face at the match boundary", [setter("face.outputs.score", 0.556)], "AUTO_APPROVED", "low", []),
    ("face check failed", [setter("face.status", "failed")], "MANUAL_REVIEW", "medium", ["face_failed"]),
    ("face check timed out", [setter("face.status", "timed_out")], "MANUAL_REVIEW", "medium", ["face_timed_out"]),
    # --- forgery
    ("forgery suspected", [setter("forgery.outputs.score", 0.95)], "MANUAL_REVIEW", "high", ["forgery_suspected"]),
    ("forgery at the suspected boundary", [setter("forgery.outputs.score", 0.857383)], "MANUAL_REVIEW", "high",
     ["forgery_suspected"]),
    ("forgery just below suspected", [setter("forgery.outputs.score", 0.8573)], "MANUAL_REVIEW", "medium", ["forgery_uncertain"]),
    ("forgery at the review boundary", [setter("forgery.outputs.score", 0.729)], "MANUAL_REVIEW", "medium", ["forgery_uncertain"]),
    ("forgery just below review", [setter("forgery.outputs.score", 0.7289)], "AUTO_APPROVED", "low", []),
    ("forgery check missing", [setter("forgery", DELETE)], "MANUAL_REVIEW", "medium", ["forgery_missing"]),
    # --- extraction
    ("extraction failed", [setter("extraction.status", "failed")], "MANUAL_REVIEW", "medium", ["extraction_failed"]),
    ("extraction timed out", [setter("extraction.status", "timed_out")], "MANUAL_REVIEW", "medium", ["extraction_timed_out"]),
    ("reliable rule flag", [setter("extraction.outputs.flags", STRONG)], "MANUAL_REVIEW", "high", ["rule_mrz_vs_expiry_date"]),
    ("MRZ name flag", [setter("extraction.outputs.flags", REVIEW)], "MANUAL_REVIEW", "medium", ["rule_mrz_vs_surname"]),
    # --- applicant data
    ("name differs", [setter("applicant.full_name", "Marko Petrovic")], "MANUAL_REVIEW", "medium", ["name_mismatch"]),
    ("name: case, diacritics, order", [setter("applicant.full_name", "VELIMIROVIĆ krsto")], "AUTO_APPROVED", "low", []),
    ("name: one typo", [setter("applicant.full_name", "Krsto Velimirovik")], "AUTO_APPROVED", "low", []),
    ("name: document shows more names", [setter("extraction.outputs.fields.given_names", "KRSTO MILAN")],
     "AUTO_APPROVED", "low", []),
    ("date of birth differs", [setter("applicant.date_of_birth", "1974-08-16")], "MANUAL_REVIEW", "high", ["dob_mismatch"]),
    ("date of birth unreadable", [setter("extraction.outputs.fields.birth_date", "soon")], "MANUAL_REVIEW", "medium",
     ["dob_unverified"]),
    ("expired document is informational", [setter("extraction.outputs.fields.expiry_date", "12.08.2025")],
     "AUTO_APPROVED", "low", ["document_expired"]),
    # --- precedence
    ("blank image beats everything", [setter("doc.outputs.blank", True), setter("forgery.outputs.score", 0.99)],
     "RESUBMIT_REQUIRED", None, ["image_unreadable"]),
    ("suspected fraud is never just bounced back",
     [setter("face.outputs.score", None), setter("face.outputs.selfie_face", {"faces": 0}),
      setter("forgery.outputs.score", 0.99)], "MANUAL_REVIEW", "high", ["no_face_found", "forgery_suspected"]),
    ("retake beats a medium finding",
     [setter("face.outputs.score", None), setter("face.outputs.selfie_face", {"faces": 0}),
      setter("forgery.outputs.score", 0.80)], "RESUBMIT_REQUIRED", None, ["no_face_found", "forgery_uncertain"]),
    ("high and medium together", [setter("forgery.outputs.score", 0.95), setter("face.outputs.score", 0.40)],
     "MANUAL_REVIEW", "high", ["face_uncertain", "forgery_suspected"]),
]


@pytest.mark.parametrize("name, changes, outcome, risk, codes", CASES, ids=[c[0] for c in CASES])
def test_rule(name, changes, outcome, risk, codes):
    checks, applicant = clean_checks(), copy.deepcopy(APPLICANT)
    for change in changes:
        change(checks, applicant)
    d = decide(checks, applicant, POLICY, today=TODAY)
    assert (d.outcome, d.risk_level, [r.code for r in d.reasons]) == (outcome, risk, codes)
    assert all(r.check_type in {"doc", "face", "forgery", "extraction", "applicant"} for r in d.reasons)


def test_reasons_carry_their_evidence():
    checks = clean_checks()
    checks["forgery"]["outputs"]["score"] = 0.95
    (reason,) = decide(checks, APPLICANT, POLICY, today=TODAY).reasons
    assert reason.check_type == "forgery" and reason.evidence["score"] == 0.95
    assert reason.evidence["suspected_from"] == 0.857383 and reason.evidence["top_tile_box"] == [1, 2, 3, 4]


def test_dob_mismatch_does_not_repeat_the_dates():  # PII stays out of the stored reasons
    applicant = {**APPLICANT, "date_of_birth": "1974-08-16"}
    reason = decide(clean_checks(), applicant, POLICY, today=TODAY).reasons[0]
    assert "1974" not in str(reason.evidence) and "1974" not in reason.message


def test_expiry_settings():
    checks = clean_checks()
    checks["extraction"]["outputs"]["fields"]["expiry_date"] = "12.08.2025"
    strict = Policy(**{**POLICY.__dict__, "expired_is_informational": False})
    assert decide(checks, APPLICANT, strict, today=TODAY).outcome == "RESUBMIT_REQUIRED"
    as_of_2020 = Policy(**{**POLICY.__dict__, "expiry_as_of": date(2020, 1, 1)})
    assert decide(checks, APPLICANT, as_of_2020, today=TODAY).reasons == ()  # still valid on that date


def test_early_resubmit_needs_only_the_doc_result():
    blank = {"status": "ok", "outputs": {"blank": True}}
    assert decision.needs_early_resubmit(blank, POLICY)
    assert not decision.needs_early_resubmit(clean_checks()["doc"], POLICY)
    d = decide({"doc": blank}, APPLICANT, POLICY, today=TODAY)  # face/forgery/extraction never ran
    assert d.outcome == "RESUBMIT_REQUIRED" and [r.code for r in d.reasons] == ["image_unreadable"]


def test_risk_score_orders_the_queue():
    def score(**changes):
        checks = clean_checks()
        for path, value in changes.items():
            setter(path.replace("__", "."), value)(checks, {})
        return decide(checks, APPLICANT, POLICY, today=TODAY).risk_score

    clean, medium = score(), score(forgery__outputs__score=0.80)
    high = score(forgery__outputs__score=0.95)
    two_high = score(forgery__outputs__score=0.95, face__outputs__score=0.10)
    assert clean < medium < high < two_high <= 100


def test_load_policy_reads_the_model_jsons():
    policy = decision.load_policy()
    assert (policy.doc_min_confidence, policy.forgery_review, policy.forgery_suspected) == pytest.approx((0.77, 0.729, 0.857383))
    assert (policy.face_mismatch_below, policy.face_review_below) == pytest.approx((0.2597, 0.556))
    assert decision.load_policy(name_min_similarity=0.9).name_min_similarity == 0.9


# ------------------------------------------------------------------ the Phase 6 smoke-test cases
def test_phase6_case1_genuine_with_own_selfie_is_auto_approved():
    checks = clean_checks()  # srb_passport_04: doc 0.9988, forgery 0.56 pass, face 0.9226 match, no rule flags
    checks["face"]["outputs"]["score"] = 0.9226
    d = decide(checks, APPLICANT, POLICY, today=TODAY)
    assert d.outcome == "AUTO_APPROVED" and d.risk_score < 10


def test_phase6_case2_forged_with_strangers_selfie_is_high_risk_review():
    checks = clean_checks()  # aze_passport_75_fake_3_39: forgery 0.9997, face 0.2067, MRZ name flags
    checks["doc"]["outputs"].update(doc_type="aze_passport", confidence=0.9991)
    checks["forgery"]["outputs"]["score"] = 0.9997
    checks["face"]["outputs"].update(score=0.2067, band="mismatch")
    checks["extraction"]["outputs"]["flags"] = [{"rule": "mrz_vs_surname", "severity": "review", "detail": "x"},
                                                {"rule": "mrz_vs_given_names", "severity": "review", "detail": "y"}]
    d = decide(checks, APPLICANT, POLICY, today=TODAY)
    assert d.outcome == "MANUAL_REVIEW" and d.risk_level == "high"
    assert [r.code for r in d.reasons] == ["face_mismatch", "forgery_suspected", "rule_mrz_vs_surname",
                                           "rule_mrz_vs_given_names"]
    summary = decision.official_summary("app-2", d, checks)
    assert "manual review (risk high" in summary and "Forgery suspected" in summary and "KRSTO" not in summary
