"""Export tidy, PII-free CSVs for the dashboards (Phase 9) to dashboard/data/.

    .venv/bin/python scripts/export_dashboard_data.py          # the simulated batch only (the default)
    .venv/bin/python scripts/export_dashboard_data.py --all    # every application in MongoDB

Reads MongoDB (applications, check_results, audit_log), the batch ground truth (data/processed/batch/
ground_truth.csv, written by scripts/simulate_batch.py) and the saved model metrics in reports/. Writes:

  applications.csv     one row per application: document type, system outcome, final status, risk, timestamps,
                       end-to-end and per-check latency, officer action, queue age, ground truth (batch only)
  reasons.csv          one row per decision reason (code, label, effect, check)
  checks.csv           one row per check (status, score, band, latency)
  officer_actions.csv  one row per officer decision (action, waiting time, system risk, ground truth)
  model_metrics.csv    the offline model evaluations (doc classifier, forgery v1/v2/v3, face, extraction)

and, for the "Quick path" of dashboard/TABLEAU_GUIDE.md, one pre-joined file per dashboard in dashboard/data/tableau/
(friendly column names, the guide's calculated fields already computed as columns; built only from the five tables
above, so they cannot contain anything those do not):

  operations.csv         one row per application (KPIs, funnel, outcomes by document type, latency, queue age)
  risk_fraud.csv         one row per decision reason, application-level numbers on each case's first row only
  model_performance.csv  model_metrics.csv plus the chart each row belongs to

The in-app dashboards (Phase 12) read these three files: scripts/export_dashboard_snapshot.py bundles them with the
frontend (frontend/src/dashboards/snapshot.json). Run it after every export.

WHICH APPLICATIONS: by default only the simulated batch (the applications in the ground-truth file), so the numbers
match reports/phase9/batch_summary.md. MongoDB also holds test runs (end-to-end and smoke tests, the demo-site
recordings); --all includes them, marked "not_in_batch". Without a ground-truth file every application is exported.

WAITING TIMES (queue_age_min) are measured at the latest event recorded in the exported data, not at the time of the
export: re-exporting unchanged data gives identical files, and old waiting cases do not grow older with every export.

PRIVACY (Tableau Public publishes everything publicly): no names, dates of birth, document numbers, customer or user
ids, S3 keys, free-text officer reasons or extracted fields. Application ids are replaced by pseudonyms (C0001...,
numbered by submission time, a new mapping per export that is not saved anywhere); officers become officer_1...
Reason messages are replaced by fixed labels per reason code (some messages contain document dates).
All the data is synthetic (SIDTD test templates and simulated selfies).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import pandas as pd

from ekyc import config, store

OUT = config.PROJECT_ROOT / "dashboard" / "data"
TABLEAU_OUT = OUT / "tableau"
TRUTH_CSV = config.PROCESSED_DIR / "batch" / "ground_truth.csv"
CHECKS = ("doc", "face", "forgery", "extraction")
DOC_TYPE_LABELS = {"alb_id": "Albanian ID card", "aze_passport": "Azerbaijani passport", "esp_id": "Spanish ID card",
                   "est_id": "Estonian ID card", "fin_id": "Finnish ID card", "grc_passport": "Greek passport",
                   "lva_passport": "Latvian passport", "rus_internalpassport": "Russian internal passport",
                   "srb_passport": "Serbian passport", "svk_id": "Slovak ID card"}
REASON_LABELS = {  # fixed texts (the stored messages can contain document dates)
    "image_unreadable": "Image unreadable (no document visible)", "unrecognized_document": "Unrecognized document",
    "no_face_found": "No face found", "face_mismatch": "Selfie does not match the ID photo",
    "face_uncertain": "Face match uncertain", "forgery_suspected": "Forgery suspected",
    "forgery_uncertain": "Possible document edit", "extraction_failed": "Field extraction failed",
    "name_mismatch": "Name entered differs from the document", "dob_mismatch": "Date of birth entered differs",
    "dob_unverified": "Date of birth not readable", "document_expired": "Document expired (informational)",
}
# ground-truth column in data/processed/batch/ground_truth.csv -> column in applications.csv
TRUTH_COLUMNS = {"scenario": "truth_scenario", "truth_class": "truth_class", "document_truth": "truth_document",
                 "selfie_truth": "truth_selfie", "details_truth": "truth_details",
                 "expected_outcome": "truth_expected_outcome", "forgery_type": "truth_forgery_type",
                 "altered_field": "truth_altered_field", "unreadable_kind": "truth_unreadable_kind"}
COLUMNS = {  # fixed column lists, so that an empty table still has its header
    "reasons": ["case_id", "reason_code", "reason_label", "effect", "check_type", "system_outcome", "risk_level"],
    "checks": ["case_id", "check_type", "status", "score", "band", "latency_ms", "model_version"],
    "officer_actions": ["case_id", "officer", "action", "acted_at", "system_decided_at", "wait_min",
                        "system_risk_level", "system_risk_score", "truth_class", "truth_scenario"],
}


def iso(value) -> str | None:
    """UTC timestamp as 'YYYY-MM-DD HH:MM:SS' (Tableau reads it as a date & time)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return pd.Timestamp(value).tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S")


def seconds_between(start, end) -> float | None:
    if start is None or end is None:
        return None
    return round((pd.Timestamp(end) - pd.Timestamp(start)).total_seconds(), 1)


def reason_label(code: str) -> str:
    if code.startswith("rule_"):
        return "Document data inconsistent: " + code[5:].replace("_", " ")
    if code.endswith(("_timed_out", "_failed", "_skipped", "_missing")):
        check, _, status = code.partition("_")
        return f"{check.capitalize()} check {status.replace('_', ' ')}"
    return REASON_LABELS.get(code, code.replace("_", " "))


def check_score_and_band(check_type: str, check: dict) -> tuple[float | None, str | None]:
    o = check.get("outputs") or {}
    if check.get("status") != "ok":
        return None, check.get("status")
    if check_type == "doc":
        band = "blank" if o.get("blank") else "recognized" if o.get("recognized", True) else "unrecognized"
        return o.get("confidence"), band
    if check_type in ("face", "forgery"):
        return o.get("score"), o.get("band")
    flags = o.get("flags") or []  # extraction: how many consistency rules failed
    strong = sum(1 for f in flags if f.get("severity") == "strong")
    return float(len(flags)), "strong_flag" if strong else "review_flag" if flags else "all_rules_pass"


def latest_event(apps: list[dict], audit_by_app: dict[str, list]):
    """The newest moment recorded for these applications (a submission or any status change in the audit log).
    Waiting times are measured up to it (module docstring: WAITING TIMES)."""
    times = [a["created_at"] for a in apps]
    times += [entry["at"] for a in apps for entry in audit_by_app.get(a["application_id"], [])]
    return max(times) if times else datetime.now(timezone.utc)


def export_operations(db, truth: pd.DataFrame, batch_only: bool = True) -> tuple[dict[str, pd.DataFrame], datetime]:
    """The four operational tables, and the moment the waiting times are measured at (latest_event)."""
    apps = sorted(db.applications.find({}, projection={"_id": False, "applicant": False}), key=lambda a: a["created_at"])
    if batch_only and len(truth):  # leave out test runs (no ground truth); before numbering, so the batch is C0001...
        batch = set(truth["application_id"])
        apps = [a for a in apps if a["application_id"] in batch]
    pseudonym = {a["application_id"]: f"C{i:04d}" for i, a in enumerate(apps, start=1)}
    checks_by_app: dict[str, dict] = {}
    for c in db.check_results.find({}, projection={"_id": False}):
        checks_by_app.setdefault(c["application_id"], {})[c["check_type"]] = c
    audit_by_app: dict[str, list] = {}
    for entry in db.audit_log.find({}, projection={"_id": False}).sort("at", 1):
        audit_by_app.setdefault(entry["application_id"], []).append(entry)
    as_of = latest_event(apps, audit_by_app)
    officers: dict[str, str] = {}
    truth_by_id = truth.set_index("application_id") if len(truth) else pd.DataFrame()

    applications, reasons, checks, actions = [], [], [], []
    for a in apps:
        app_id, case = a["application_id"], pseudonym[a["application_id"]]
        d = a.get("decision") or {}
        od = a.get("officer_decision") or {}
        app_checks = checks_by_app.get(app_id, {})
        closed = next((e["at"] for e in reversed(audit_by_app.get(app_id, [])) if e["to_status"] in store.CLOSED), None)
        t = truth_by_id.loc[app_id] if app_id in truth_by_id.index else None
        row = {
            "case_id": case, "submitted_at": iso(a["created_at"]), "decided_at": iso(d.get("decided_at")),
            "closed_at": iso(closed), "doc_type": a.get("doc_type") or "(not classified)",
            "doc_type_label": DOC_TYPE_LABELS.get(a.get("doc_type"), "Not classified"),
            "system_outcome": d.get("outcome") or "(pending)", "final_status": a["status"],
            "risk_level": d.get("risk_level") or ("none" if d else "(pending)"), "risk_score": d.get("risk_score"),
            "decided_early": bool(d.get("early")), "reason_count": len(d.get("reasons") or []),
            "time_to_decision_s": seconds_between(a["created_at"], d.get("decided_at")),
            "officer_action": od.get("action") or "none",
            "officer_wait_min": (round(seconds_between(d.get("decided_at"), od.get("at")) / 60, 1)
                                 if od and d.get("decided_at") else None),
            "awaiting_officer": a["status"] == "DECIDED",
            "queue_age_min": (round(seconds_between(d.get("decided_at"), as_of) / 60, 1)
                              if a["status"] == "DECIDED" and d.get("decided_at") else None),
            "in_batch": t is not None,
        }
        for check_type in CHECKS:  # worker processing time per check (ms); None if the check did not run
            row[f"{check_type}_latency_ms"] = (app_checks.get(check_type) or {}).get("latency_ms")
        for source, column in TRUTH_COLUMNS.items():
            if t is not None:
                row[column] = t[source] or None
            else:  # an application from outside the simulated batch (e.g. a manual demo): no ground truth
                row[column] = "not_in_batch" if source in ("scenario", "truth_class") else None
        applications.append(row)

        for r in d.get("reasons") or []:
            reasons.append({"case_id": case, "reason_code": r["code"], "reason_label": reason_label(r["code"]),
                            "effect": r["effect"], "check_type": r.get("check_type"),
                            "system_outcome": d.get("outcome"), "risk_level": d.get("risk_level") or "none"})
        for check_type, c in app_checks.items():
            score, band = check_score_and_band(check_type, c)
            checks.append({"case_id": case, "check_type": check_type, "status": c.get("status"), "score": score,
                           "band": band, "latency_ms": c.get("latency_ms"),
                           "model_version": json.dumps(c.get("model_versions") or {}, sort_keys=True)})
        if od:
            officer = officers.setdefault(od["officer_id"], f"officer_{len(officers) + 1}")
            actions.append({"case_id": case, "officer": officer, "action": od["action"],
                            "acted_at": iso(od["at"]), "system_decided_at": iso(d.get("decided_at")),
                            "wait_min": row["officer_wait_min"], "system_risk_level": d.get("risk_level"),
                            "system_risk_score": d.get("risk_score"), "truth_class": row["truth_class"],
                            "truth_scenario": row["truth_scenario"]})
    return {"applications": pd.DataFrame(applications), "reasons": pd.DataFrame(reasons, columns=COLUMNS["reasons"]),
            "checks": pd.DataFrame(checks, columns=COLUMNS["checks"]),
            "officer_actions": pd.DataFrame(actions, columns=COLUMNS["officer_actions"])}, as_of


def export_model_metrics() -> pd.DataFrame:
    """Long format: one row per (model, version, split, metric). Every value is read from a saved report."""
    reports = config.REPORTS_DIR
    rows = []

    def add(model, version, order, split, metric, value, source, note=""):
        rows.append({"model": model, "version": version, "version_order": order, "split": split, "metric": metric,
                     "value": None if value is None else round(float(value), 4), "source": source, "note": note})

    doc = json.loads((reports / "phase3" / "doc_classifier_metrics.json").read_text())
    src = "reports/phase3/doc_classifier_metrics.json"
    add("Document classifier", "EfficientNetB0 (frozen)", 1, "val", "accuracy", doc["val_accuracy"], src)
    add("Document classifier", "EfficientNetB0 (frozen)", 1, "val", "macro F1", doc["val_macro_f1"], src)
    add("Document classifier", "EfficientNetB0 (frozen)", 1, "test", "accuracy", doc["test_accuracy"], src)
    add("Document classifier", "EfficientNetB0 (frozen)", 1, "test", "macro F1", doc["test_macro_f1"], src)
    add("Document classifier", "EfficientNetB0 (frozen)", 1, "test", "share rejected (below 0.77)",
        doc["test_rejected_share"], src)
    add("Document classifier", "EfficientNetB0 (frozen)", 1, "LFW faces", "share of faces rejected",
        doc["lfw_rejected_share"], src, "a non-document should be rejected; 16.5 % of faces pass")

    v1 = json.loads((reports / "phase3" / "forgery_metrics_val.json").read_text())
    src = "reports/phase3/forgery_metrics_val.json"
    by_source = pd.read_csv(reports / "phase3" / "forgery_breakdown_source_val.csv", header=[0, 1], index_col=0)
    v1_note = "whole image, templates + clip frames: learned shortcuts (recording style, JPEG quality)"
    add("Forgery detector", "v1 whole image", 1, "val", "document PR-AUC", v1["ranking"]["B2 stage 2"]["pr_auc"], src, v1_note)
    add("Forgery detector", "v1 whole image", 1, "val", "document ROC-AUC", v1["ranking"]["B2 stage 2"]["roc_auc"], src, v1_note)
    add("Forgery detector", "v1 whole image", 1, "val (templates only)", "document PR-AUC",
        by_source.loc["template", ("B2", "pr_auc")], "reports/phase3/forgery_breakdown_source_val.csv",
        "chance level 0.544 (179 forged of 329)")
    add("Forgery detector", "v1 whole image", 1, "val", "localisation (heat on the edit)",
        v1["gradcam_pointing"]["template"]["pointing score"], src, "Grad-CAM on the edit for 0 of 179 forged pages")

    v2v3 = pd.read_csv(reports / "phase3" / "forgery_v3_vs_v2_val.csv", index_col=0)
    src = "reports/phase3/forgery_v3_vs_v2_val.csv"
    for version, order, column, note in (
            ("v2 tiles", 2, "v2 (compression cue)", "224 px tiles of 1280 px templates; residual compression-history cue"),
            ("v3 tiles, equal history", 3, "v3 (equal history)", "accepted: every shortcut check passes")):
        for metric, label in (("document PR-AUC", "document PR-AUC"), ("document ROC-AUC", "document ROC-AUC"),
                              ("position-matched control, all types", "position-matched control AUC (~0.5 = no cue)"),
                              ("edit-hidden document ROC-AUC", "edit-hidden ROC-AUC (~0.5 or lower = no cue)"),
                              ("top tile on the edit (forged pages)", "localisation (heat on the edit)"),
                              ("precision at that threshold", "precision at the review threshold"),
                              ("recall at that threshold", "recall at the review threshold")):
            add("Forgery detector", version, order, "val", label, float(v2v3.loc[metric, column]), src, note)

    test = json.loads((reports / "phase3" / "forgery_v3_metrics_test.json").read_text())
    src = "reports/phase3/forgery_v3_metrics_test.json"
    version = "v3 tiles, equal history"
    add("Forgery detector", version, 3, "test", "document PR-AUC", test["doc_ranking"]["document PR-AUC"]["test"], src)
    add("Forgery detector", version, 3, "test", "document ROC-AUC", test["doc_ranking"]["document ROC-AUC"]["test"], src)
    for name, label in (("recall >= 0.90 (val)", "review threshold 0.729"), ("F1-optimal (val)", "suspected threshold 0.857")):
        t = test["thresholds"][name]
        for metric in ("precision", "recall", "F1", "false alarm rate"):
            add("Forgery detector", version, 3, "test", f"{metric} at the {label}", t[metric], src)
    for ctype, values in test["recall_by_ctype"].items():
        add("Forgery detector", version, 3, "test", f"recall at 0.857, {ctype}", values["recall at 0.857"], src)
    add("Forgery detector", version, 3, "test", "localisation (heat on the edit)",
        test["localisation"]["top tile touches the edit"], src)
    add("Forgery detector", version, 3, "test", "position-matched control AUC (~0.5 = no cue)",
        test["position_matched_control"]["all types"]["AUC"], src)

    face = json.loads((reports / "phase4" / "face_metrics.json").read_text())
    src = "reports/phase4/face_metrics.json"
    for version, order, key in (("SFace (production)", 2, "SFace (production)"), ("Siamese (showcase)", 1, "Siamese (showcase)")):
        m = face["lfw_test"][key]
        for metric, label in (("roc_auc", "ROC-AUC"), ("eer", "equal error rate"), ("tar_at_far_1%", "TAR at FAR 1 %"),
                              ("accuracy", "accuracy at the threshold"), ("far", "false accept rate"),
                              ("frr", "false reject rate")):
            add("Face verification", version, order, "LFW test", label, m[metric], src)
    sanity = face["id_sanity"]
    add("Face verification", "SFace (production)", 2, "synthetic ID pairs", "share of different people accepted",
        sanity["non-match (two documents)"]["accepted"], src, "why scores below 0.556 go to manual review")
    add("Face verification", "SFace (production)", 2, "synthetic ID pairs", "share of same person accepted",
        sanity["match (ID vs simulated selfie)"]["accepted"], src)

    p5 = json.loads((reports / "phase5" / "phase5_metrics.json").read_text())
    src = "reports/phase5/phase5_metrics.json"
    t = p5["test"]["ollama"]
    for metric, label in (("exact match", "exact field match"), ("normalized match", "normalized field match"),
                          ("JSON valid", "valid JSON"), ("latency p50 (s)", "latency p50 (seconds)"),
                          ("latency p95 (s)", "latency p95 (seconds)")):
        add("Field extraction", "qwen2.5vl:7b, prompt v2", 1, "test", label, t[metric], src)
    per_field = pd.read_csv(reports / "phase5" / "extraction_test_per_field.csv")
    for _, r in per_field.iterrows():
        add("Field extraction", "qwen2.5vl:7b, prompt v2", 1, "test (per field)", f"exact: {r['field']}", r["exact"],
            "reports/phase5/extraction_test_per_field.csv", f"{int(r['documents'])} documents")
        add("Field extraction", "qwen2.5vl:7b, prompt v2", 1, "test (per field)", f"normalized: {r['field']}",
            r["normalized"], "reports/phase5/extraction_test_per_field.csv", f"{int(r['documents'])} documents")
    return pd.DataFrame(rows)


# ---- Quick path: one pre-joined, Tableau-ready file per dashboard (dashboard/TABLEAU_GUIDE.md, "Quick path") ----
# Friendly values for the codes, so that charts and legends read well without renaming anything in Tableau.
OUTCOME_LABELS = {"AUTO_APPROVED": "Auto-approved", "MANUAL_REVIEW": "Manual review",
                  "RESUBMIT_REQUIRED": "Resubmit required", "(pending)": "Pending"}
RISK_LABELS = {"high": "High", "medium": "Medium", "low": "Low", "none": "None (resubmit)", "(pending)": "Pending"}
OFFICER_LABELS = {"approve": "Approved", "reject": "Rejected", "none": "No officer decision"}
TRUTH_CLASS_LABELS = {"legitimate": "Legitimate", "fraud_or_mismatch": "Fraud or mismatch",
                      "unusable": "Unusable image", "not_in_batch": "No ground truth"}
SCENARIO_LABELS = {"genuine": "Genuine", "genuine_wrong_details": "Genuine, wrong details typed",
                   "stranger_selfie": "Genuine, stranger's selfie", "forged_own_selfie": "Forged, own selfie",
                   "forged_stranger": "Forged, stranger's selfie", "unreadable": "Unusable image",
                   "not_in_batch": "No ground truth"}
EFFECT_LABELS = {"high": "High", "medium": "Medium", "resubmit": "Resubmit", "info": "Info only"}
RAISED_BY = {"doc": "Document classifier", "face": "Face match", "forgery": "Forgery detector",
             "extraction": "Field extraction", "applicant": "Typed details"}
CHECK_LABELS = {"doc": "Doc", "face": "Face", "forgery": "Forgery", "extraction": "Extraction"}
NO_REASON = "No reason"
CHARTS = {  # model_performance.csv "Used in chart": the sheet filters of TABLEAU_GUIDE.md §6, as one column
    "Forgery story": ("Forgery detector", "val",
                      {"document PR-AUC", "localisation (heat on the edit)", "position-matched control AUC (~0.5 = no cue)"}),
    "Face verification": ("Face verification", "LFW test", {"ROC-AUC", "TAR at FAR 1 %", "equal error rate"}),
}
WHOLE_NUMBER_COLUMNS = ("Applications", "Cases with this reason", "Risk score band", "Version order")


def friendly(code, labels: dict):
    """A code's friendly label; an unknown code is kept as it is (never dropped), an empty cell stays empty."""
    return None if code is None or pd.isna(code) else labels.get(code, code)


def yes_no(condition: bool, applies: bool = True) -> int | None:
    """A (0/1) column: 1 = yes, 0 = no, empty = does not apply. Its average is a rate, its sum a count (Tableau's
    AVG and SUM skip empty cells, so e.g. a rate among frauds only needs the column to be empty for non-frauds)."""
    return (1 if condition else 0) if applies else None


def seconds(ms) -> float | None:
    return None if ms is None or pd.isna(ms) else round(ms / 1000, 2)


def outcome_label(final_status: str, system_outcome: str) -> str:
    """TABLEAU_GUIDE.md §2.1 "Outcome (readable)": one label per final state."""
    if final_status == "APPROVED":
        return "Auto-approved" if system_outcome == "AUTO_APPROVED" else "Approved by officer"
    return {"REJECTED": "Rejected by officer", "DECIDED": "Awaiting officer",
            "RESUBMIT_REQUESTED": "Retake requested"}.get(final_status, "In progress")


def system_vs_truth(truth_class: str, system_outcome: str) -> str:
    """TABLEAU_GUIDE.md §2.1 "System vs truth": what the system decided, against what was really submitted."""
    if truth_class == "legitimate":
        return {"AUTO_APPROVED": "Correct: approved", "MANUAL_REVIEW": "False alarm: sent to review"}.get(
            system_outcome, "Legitimate, asked to resubmit")
    if truth_class == "fraud_or_mismatch":
        return {"AUTO_APPROVED": "Missed: auto-approved", "MANUAL_REVIEW": "Caught: sent to review"}.get(
            system_outcome, "Caught: asked to resubmit")
    if truth_class == "unusable":
        return "Correct: resubmit" if system_outcome == "RESUBMIT_REQUIRED" else "Unusable, not sent back"
    return "No ground truth"


def whole_numbers(rows: list[dict]) -> pd.DataFrame:
    """The rows as a table; counts and (0/1) columns as whole numbers with empty cells (plain pandas writes 1.0)."""
    table = pd.DataFrame(rows)
    for column in table.columns:
        if column.endswith("(0/1)") or column.startswith("Funnel ") or column in WHOLE_NUMBER_COLUMNS:
            table[column] = table[column].astype("Int64")
    return table


def tableau_operations(apps: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """operations.csv (dashboard 1, Operations): one row per application, so every sum and average counts each
    application once. Replaces the relationship of applications.csv and checks.csv: the check latencies are columns."""
    rows = []
    for a in apps.to_dict("records"):
        outcome, action = a["system_outcome"], a["officer_action"]
        rows.append({
            "Case": a["case_id"], "Submitted (UTC)": a["submitted_at"],
            "Decided by the system (UTC)": a["decided_at"], "Closed (UTC)": a["closed_at"],
            "Document type": a["doc_type_label"], "System outcome": friendly(outcome, OUTCOME_LABELS),
            "Outcome": outcome_label(a["final_status"], outcome), "Risk level": friendly(a["risk_level"], RISK_LABELS),
            "Scenario (truth)": friendly(a["truth_scenario"], SCENARIO_LABELS),
            "Officer decision": friendly(action, OFFICER_LABELS),
            "Applications": 1,
            "Auto-approved (0/1)": yes_no(outcome == "AUTO_APPROVED"),
            "Manual review (0/1)": yes_no(outcome == "MANUAL_REVIEW"),
            "Resubmit required (0/1)": yes_no(outcome == "RESUBMIT_REQUIRED"),
            "Time to decision (s)": a["time_to_decision_s"],
            **{f"{label} check (s)": seconds(a[f"{check}_latency_ms"]) for check, label in CHECK_LABELS.items()},
            "Funnel 1 Submitted": 1,
            "Funnel 2 Decided by the system": yes_no(outcome != "(pending)"),
            "Funnel 3 Sent to an officer": yes_no(outcome == "MANUAL_REVIEW"),
            "Funnel 4 Decided by an officer": yes_no(action != "none"),
            "Funnel 5 Rejected by an officer": yes_no(action == "reject"),
            "Officer wait (min)": a["officer_wait_min"],
            "Waiting for an officer (0/1)": yes_no(a["awaiting_officer"]),
            "Queue age (min)": a["queue_age_min"],
            "Data as of (UTC)": as_of,  # the moment the queue ages are measured at (latest_event)
        })
    return whole_numbers(rows)


def tableau_risk_fraud(apps: pd.DataFrame, reasons: pd.DataFrame) -> pd.DataFrame:
    """risk_fraud.csv (dashboard 2, Risk & fraud): one row per decision reason, plus one "No reason" row for a case
    without any, so that no case is lost. A case's labels repeat on all its rows (every filter works on every row);
    its numbers sit on its FIRST row only, so SUM and AVG count each application once, however many reasons it has.
    Count reasons with "Cases with this reason". The officer decision is per case (at most one), so it is a case number."""
    reasons_by_case = {case: group.to_dict("records") for case, group in reasons.groupby("case_id", sort=False)}
    rows = []
    for a in apps.to_dict("records"):
        outcome, truth_class, action = a["system_outcome"], a["truth_class"], a["officer_action"]
        by_officer = action in ("approve", "reject")
        has_truth = truth_class in ("legitimate", "fraud_or_mismatch", "unusable")
        labels = {  # repeated on every row of the case
            "Case": a["case_id"], "Submitted (UTC)": a["submitted_at"], "Document type": a["doc_type_label"],
            "System outcome": friendly(outcome, OUTCOME_LABELS), "Outcome": outcome_label(a["final_status"], outcome),
            "Risk level": friendly(a["risk_level"], RISK_LABELS),
            "Risk score band": None if pd.isna(a["risk_score"]) else int(a["risk_score"] // 10 * 10),
            "Truth class": friendly(truth_class, TRUTH_CLASS_LABELS),
            "Scenario (truth)": friendly(a["truth_scenario"], SCENARIO_LABELS),
            "Forgery method (truth)": a["truth_forgery_type"],
            "System vs truth": system_vs_truth(truth_class, outcome),
            "Officer decision": friendly(action, OFFICER_LABELS),
        }
        numbers = {  # the case's first row only
            "Applications": 1, "Risk score": a["risk_score"],
            "Fraud caught (0/1)": yes_no(outcome != "AUTO_APPROVED", applies=truth_class == "fraud_or_mismatch"),
            "Missed fraud (0/1)": yes_no(outcome == "AUTO_APPROVED", applies=truth_class == "fraud_or_mismatch"),
            "False alarm (0/1)": yes_no(outcome == "MANUAL_REVIEW", applies=truth_class == "legitimate"),
            "Officer confirmed the flag (0/1)": yes_no(action == "reject", applies=by_officer),
            "Officer agrees with truth (0/1)": yes_no((action == "reject") == (truth_class != "legitimate"),
                                                     applies=by_officer and has_truth),
        }
        for i, r in enumerate(reasons_by_case.get(a["case_id"]) or [None]):
            reason = ({"Reason": r["reason_label"], "Reason effect": friendly(r["effect"], EFFECT_LABELS),
                       "Raised by": friendly(r["check_type"], RAISED_BY), "Cases with this reason": 1} if r else
                      {"Reason": NO_REASON, "Reason effect": None, "Raised by": None, "Cases with this reason": None})
            rows.append({**labels, **reason, **(numbers if i == 0 else dict.fromkeys(numbers))})
    return whole_numbers(rows)


def chart_of(metric: dict) -> str:
    if metric["split"] == "test (per field)":
        return "Extraction per field"
    for chart, (model, split, names) in CHARTS.items():
        if metric["model"] == model and metric["split"] == split and metric["metric"] in names:
            return chart
    return "Metrics table only"


def tableau_model_performance(metrics: pd.DataFrame) -> pd.DataFrame:
    """model_performance.csv (dashboard 3): model_metrics.csv with friendly names, the per-field extraction metrics
    split into Field and Match type, and the chart each row is drawn in (instead of three filters per sheet)."""
    rows = []
    for m in metrics.to_dict("records"):
        per_field = m["split"] == "test (per field)"
        match_type, _, field = m["metric"].partition(": ")  # "exact: surname" -> "exact", "surname"
        rows.append({"Model": m["model"], "Version": m["version"], "Version order": m["version_order"],
                     "Split": m["split"], "Metric": m["metric"], "Value": m["value"], "Used in chart": chart_of(m),
                     "Field": field if per_field else None, "Match type": match_type.capitalize() if per_field else None,
                     "Note": m["note"] or None, "Source": m["source"]})
    return whole_numbers(rows)


def tableau_tables(tables: dict[str, pd.DataFrame], as_of: str) -> dict[str, pd.DataFrame]:
    """The three quick-path files, built only from the five exported (PII-free) tables."""
    return {"operations": tableau_operations(tables["applications"], as_of),
            "risk_fraud": tableau_risk_fraud(tables["applications"], tables["reasons"]),
            "model_performance": tableau_model_performance(tables["model_metrics"])}


FORBIDDEN_COLUMNS = ("name", "birth", "dob", "customer", "user", "email", "document_key", "selfie_key",
                     "document_number", "application_id", "officer_id")


def pii_like_columns(table: pd.DataFrame) -> list[str]:
    """Column names that look like personal data (friendly names are read with spaces as underscores)."""
    return [c for c in table.columns if any(word in c.lower().replace(" ", "_") for word in FORBIDDEN_COLUMNS)]


def write(folder, tables: dict[str, pd.DataFrame], show_columns: bool = False) -> None:
    for name, table in tables.items():  # check everything before writing anything
        if leaked := pii_like_columns(table):
            raise RuntimeError(f"{name}: PII-like columns {leaked}")
    folder.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(folder / f"{name}.csv", index=False)
        path = (folder / f"{name}.csv").relative_to(config.PROJECT_ROOT)
        print(f"  {str(path):<44} {len(table):>4} rows x {len(table.columns)} columns")
        if show_columns:
            print("      " + " | ".join(table.columns))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Export PII-free CSVs for the dashboards.")
    parser.add_argument("--all", action="store_true", help="also export the applications without ground truth "
                        "(end-to-end and smoke tests, demo-site recordings, manual submissions)")
    args = parser.parse_args(argv)
    truth = pd.read_csv(TRUTH_CSV, keep_default_na=False) if TRUTH_CSV.exists() else pd.DataFrame()
    if not len(truth):
        print(f"no ground truth ({TRUTH_CSV.relative_to(config.PROJECT_ROOT)}): exporting every application")
    db = store.connect()
    tables, as_of = export_operations(db, truth, batch_only=not args.all)
    tables["model_metrics"] = export_model_metrics()
    write(OUT, tables)
    write(TABLEAU_OUT, tableau_tables(tables, iso(as_of)), show_columns=True)
    left_out = db.applications.count_documents({}) - len(tables["applications"])
    print(f"{len(tables['applications'])} applications exported"
          + (f", {left_out} without ground truth left out (--all includes them)" if left_out else ""))
    print(f"waiting times measured at {iso(as_of)} UTC (the latest recorded event)")


if __name__ == "__main__":
    main()
