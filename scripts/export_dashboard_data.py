"""Export tidy, PII-free CSVs for the Tableau dashboard (Phase 9) to dashboard/data/.

    .venv/bin/python scripts/export_dashboard_data.py

Reads MongoDB (applications, check_results, audit_log), the batch ground truth (data/processed/batch/
ground_truth.csv, written by scripts/simulate_batch.py) and the saved model metrics in reports/. Writes:

  applications.csv     one row per application: document type, system outcome, final status, risk, timestamps,
                       end-to-end and per-check latency, officer action, queue age, ground truth (batch only)
  reasons.csv          one row per decision reason (code, label, effect, check)
  checks.csv           one row per check (status, score, band, latency)
  officer_actions.csv  one row per officer decision (action, waiting time, system risk, ground truth)
  model_metrics.csv    the offline model evaluations (doc classifier, forgery v1/v2/v3, face, extraction)

PRIVACY (Tableau Public publishes everything publicly): no names, dates of birth, document numbers, customer or user
ids, S3 keys, free-text officer reasons or extracted fields. Application ids are replaced by pseudonyms (C0001...,
numbered by submission time, a new mapping per export that is not saved anywhere); officers become officer_1...
Reason messages are replaced by fixed labels per reason code (some messages contain document dates).
All the data is synthetic (SIDTD test templates and simulated selfies).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd

from ekyc import config, store

OUT = config.PROJECT_ROOT / "dashboard" / "data"
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


def export_operations(db, truth: pd.DataFrame, exported_at: datetime) -> dict[str, pd.DataFrame]:
    apps = sorted(db.applications.find({}, projection={"_id": False, "applicant": False}), key=lambda a: a["created_at"])
    pseudonym = {a["application_id"]: f"C{i:04d}" for i, a in enumerate(apps, start=1)}
    checks_by_app: dict[str, dict] = {}
    for c in db.check_results.find({}, projection={"_id": False}):
        checks_by_app.setdefault(c["application_id"], {})[c["check_type"]] = c
    audit_by_app: dict[str, list] = {}
    for entry in db.audit_log.find({}, projection={"_id": False}).sort("at", 1):
        audit_by_app.setdefault(entry["application_id"], []).append(entry)
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
            "queue_age_min": (round(seconds_between(d.get("decided_at"), exported_at) / 60, 1)
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
            "officer_actions": pd.DataFrame(actions, columns=COLUMNS["officer_actions"])}


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


FORBIDDEN_COLUMNS = ("name", "birth", "dob", "customer", "user", "email", "document_key", "selfie_key",
                     "document_number", "application_id", "officer_id")


def main() -> None:
    exported_at = datetime.now(timezone.utc)
    truth = pd.read_csv(TRUTH_CSV, keep_default_na=False) if TRUTH_CSV.exists() else pd.DataFrame()
    tables = export_operations(store.connect(), truth, exported_at)
    tables["model_metrics"] = export_model_metrics()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        leaked = [c for c in table.columns if any(word in c.lower() for word in FORBIDDEN_COLUMNS)]
        assert not leaked, f"{name}: PII-like columns {leaked}"
        table.to_csv(OUT / f"{name}.csv", index=False)
        print(f"  dashboard/data/{name}.csv  {len(table):>4} rows x {len(table.columns)} columns")
    print(f"exported at {iso(exported_at)} UTC (queue ages are measured at this time)")


if __name__ == "__main__":
    main()
