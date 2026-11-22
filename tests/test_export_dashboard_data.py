"""The Tableau export (Phase 9, quick-path files added later): scripts/export_dashboard_data.py.

No services needed (runs in CI): a small in-memory stand-in for MongoDB, and hand-made tables for the pre-joined
quick-path files. Checks the batch-only default, the waiting-time reference, the pre-computed rates and counts, and
the privacy guard.
"""

import importlib.util
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from ekyc import config


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, config.PROJECT_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = load_script("export_dashboard_data")
T0 = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)


class Cursor(list):
    def sort(self, key, direction):
        return sorted(self, key=lambda doc: doc[key], reverse=direction < 0)


class Collection:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None, projection=None):
        return Cursor(self.docs)


class FakeDb:
    def __init__(self, applications, check_results, audit_log):
        self.applications = Collection(applications)
        self.check_results = Collection(check_results)
        self.audit_log = Collection(audit_log)


def application(app_id, minute, status, outcome, risk_level, risk_score, officer=None):
    decided = T0 + timedelta(minutes=minute, seconds=30)
    return {"application_id": app_id, "created_at": T0 + timedelta(minutes=minute), "status": status,
            "doc_type": "srb_passport", "officer_decision": officer,
            "decision": {"outcome": outcome, "risk_level": risk_level, "risk_score": risk_score,
                         "decided_at": decided, "early": False, "reasons": []}}


def audit(app_id, minute, to_status):
    return {"application_id": app_id, "at": T0 + timedelta(minutes=minute), "to_status": to_status}


@pytest.fixture
def db_and_truth():
    officer = {"officer_id": "user-officer-1", "action": "reject", "at": T0 + timedelta(minutes=50)}
    db = FakeDb(
        [application("app-b", 1, "DECIDED", "MANUAL_REVIEW", "medium", 20.0),
         application("app-a", 0, "REJECTED", "MANUAL_REVIEW", "high", 60.0, officer),
         application("app-test", 90, "APPROVED", "AUTO_APPROVED", "low", 2.0)],  # an e2e test run: no ground truth
        [],
        [audit("app-a", 0, "SUBMITTED"), audit("app-b", 1, "SUBMITTED"), audit("app-a", 50, "REJECTED"),
         audit("app-test", 91, "APPROVED")])
    truth = pd.DataFrame({source: [""] * 2 for source in export.TRUTH_COLUMNS})
    truth["application_id"] = ["app-a", "app-b"]
    truth["scenario"] = ["forged_own_selfie", "genuine"]
    truth["truth_class"] = ["fraud_or_mismatch", "legitimate"]
    return db, truth


def test_batch_only_by_default_and_waiting_measured_at_the_latest_event(db_and_truth):
    db, truth = db_and_truth
    tables, as_of = export.export_operations(db, truth)
    apps = tables["applications"].set_index("case_id")
    assert list(apps.index) == ["C0001", "C0002"]  # the test run is left out, the batch numbered by submission time
    assert as_of == T0 + timedelta(minutes=50)  # the officer's decision, the newest event of the exported cases
    assert apps.loc["C0002", "queue_age_min"] == 48.5  # decided at 1:30, measured at 50:00 (not at "now")
    assert pd.isna(apps.loc["C0001", "queue_age_min"])  # closed: not waiting
    assert tables["officer_actions"]["officer"].tolist() == ["officer_1"]  # pseudonym, not the user id

    everything, as_of_all = export.export_operations(db, truth, batch_only=False)
    assert everything["applications"]["truth_class"].tolist() == ["fraud_or_mismatch", "legitimate", "not_in_batch"]
    assert as_of_all == T0 + timedelta(minutes=91)


def base_tables():
    apps = pd.DataFrame([
        {"case_id": "C0001", "submitted_at": "2026-11-18 08:00:00", "decided_at": "2026-11-18 08:00:30",
         "closed_at": "2026-11-18 08:00:30", "doc_type_label": "Serbian passport", "system_outcome": "AUTO_APPROVED",
         "final_status": "APPROVED", "risk_level": "low", "risk_score": 4.0, "time_to_decision_s": 30.0,
         "officer_action": "none", "officer_wait_min": None, "awaiting_officer": False, "queue_age_min": None,
         "doc_latency_ms": 200.0, "face_latency_ms": 300.0, "forgery_latency_ms": 2000.0,
         "extraction_latency_ms": 21000.0, "truth_scenario": "stranger_selfie", "truth_class": "fraud_or_mismatch",
         "truth_forgery_type": None},
        {"case_id": "C0002", "submitted_at": "2026-11-18 08:01:00", "decided_at": "2026-11-18 08:01:40",
         "closed_at": "2026-11-18 08:30:00", "doc_type_label": "Spanish ID card", "system_outcome": "MANUAL_REVIEW",
         "final_status": "REJECTED", "risk_level": "high", "risk_score": 61.1, "time_to_decision_s": 40.0,
         "officer_action": "reject", "officer_wait_min": 28.3, "awaiting_officer": False, "queue_age_min": None,
         "doc_latency_ms": 250.0, "face_latency_ms": 350.0, "forgery_latency_ms": 2500.0,
         "extraction_latency_ms": None, "truth_scenario": "forged_own_selfie", "truth_class": "fraud_or_mismatch",
         "truth_forgery_type": "Inpaint_and_Rewrite"},
        {"case_id": "C0003", "submitted_at": "2026-11-18 08:02:00", "decided_at": "2026-11-18 08:02:50",
         "closed_at": None, "doc_type_label": "Serbian passport", "system_outcome": "MANUAL_REVIEW",
         "final_status": "DECIDED", "risk_level": "medium", "risk_score": 20.0, "time_to_decision_s": 50.0,
         "officer_action": "none", "officer_wait_min": None, "awaiting_officer": True, "queue_age_min": 30.2,
         "doc_latency_ms": 220.0, "face_latency_ms": 320.0, "forgery_latency_ms": 2200.0,
         "extraction_latency_ms": 25000.0, "truth_scenario": "genuine", "truth_class": "legitimate",
         "truth_forgery_type": None},
    ])
    reasons = pd.DataFrame([
        {"case_id": "C0002", "reason_label": "Forgery suspected", "effect": "high", "check_type": "forgery"},
        {"case_id": "C0002", "reason_label": "Selfie does not match the ID photo", "effect": "high",
         "check_type": "face"},
        {"case_id": "C0003", "reason_label": "Possible document edit", "effect": "medium", "check_type": "forgery"},
    ])
    return apps, reasons


def test_operations_file_counts_each_application_once_and_rates_are_averages():
    apps, _ = base_tables()
    ops = export.tableau_operations(apps, "2026-11-18 09:00:00").set_index("Case")
    assert ops["Applications"].sum() == 3
    assert ops["Auto-approved (0/1)"].mean() == pytest.approx(1 / 3)  # AVG in Tableau = the auto-approval rate
    assert ops["Manual review (0/1)"].mean() == pytest.approx(2 / 3)
    assert [ops[f"Funnel {n}"].sum() for n in ("1 Submitted", "2 Decided by the system", "3 Sent to an officer",
                                                "4 Decided by an officer", "5 Rejected by an officer")] == [3, 3, 2, 1, 1]
    assert ops.loc["C0001", "Extraction check (s)"] == 21.0 and pd.isna(ops.loc["C0002", "Extraction check (s)"])
    assert ops["Outcome"].tolist() == ["Auto-approved", "Rejected by officer", "Awaiting officer"]
    assert ops["Waiting for an officer (0/1)"].sum() == 1 and ops["Queue age (min)"].max() == 30.2
    assert set(ops["Data as of (UTC)"]) == {"2026-11-18 09:00:00"}
    assert ops.loc["C0001", "Scenario (truth)"] == "Genuine, stranger's selfie"


def test_risk_fraud_file_has_a_row_per_reason_and_the_case_numbers_on_its_first_row_only():
    apps, reasons = base_tables()
    risk = export.tableau_risk_fraud(apps, reasons)
    assert risk["Case"].tolist() == ["C0001", "C0002", "C0002", "C0003"]  # C0001 has no reason: one "No reason" row
    assert risk.loc[0, "Reason"] == export.NO_REASON and pd.isna(risk.loc[0, "Cases with this reason"])
    assert risk["Cases with this reason"].sum() == 3
    assert risk["Applications"].sum() == 3  # C0002 has two rows but counts once
    assert pd.isna(risk.loc[2, "Risk score"]) and risk.loc[2, "System vs truth"] == "Caught: sent to review"
    # rates among the cases they apply to: empty elsewhere, so AVG in Tableau is the rate
    assert risk["Fraud caught (0/1)"].mean() == 0.5  # C0001 (a fraud) was auto-approved, C0002 was caught
    assert risk["Missed fraud (0/1)"].sum() == 1
    assert risk["False alarm (0/1)"].dropna().tolist() == [1]  # the legitimate C0003 went to review
    assert risk["Officer confirmed the flag (0/1)"].dropna().tolist() == [1]
    assert risk["Officer agrees with truth (0/1)"].dropna().tolist() == [1]
    assert risk["Risk score band"].tolist() == [0, 60, 60, 20]
    assert risk.loc[3, "Reason effect"] == "Medium" and risk.loc[3, "Raised by"] == "Forgery detector"


def test_model_performance_file_names_the_chart_of_each_row():
    metrics = pd.DataFrame([
        {"model": "Forgery detector", "version": "v1 whole image", "version_order": 1, "split": "val",
         "metric": "document PR-AUC", "value": 0.976, "source": "a.json", "note": "shortcuts"},
        {"model": "Forgery detector", "version": "v3 tiles, equal history", "version_order": 3, "split": "test",
         "metric": "document PR-AUC", "value": 0.984, "source": "b.json", "note": ""},
        {"model": "Face verification", "version": "SFace (production)", "version_order": 2, "split": "LFW test",
         "metric": "ROC-AUC", "value": 0.997, "source": "c.json", "note": ""},
        {"model": "Field extraction", "version": "qwen2.5vl:7b, prompt v2", "version_order": 1,
         "split": "test (per field)", "metric": "normalized: surname", "value": 0.95, "source": "d.csv", "note": ""},
    ])
    perf = export.tableau_model_performance(metrics)
    assert perf["Used in chart"].tolist() == ["Forgery story", "Metrics table only", "Face verification",
                                              "Extraction per field"]
    assert perf.loc[3, "Field"] == "surname" and perf.loc[3, "Match type"] == "Normalized"
    assert pd.isna(perf.loc[0, "Field"]) and pd.isna(perf.loc[1, "Note"])


def test_privacy_guard_reads_friendly_column_names_too():
    table = pd.DataFrame(columns=["Case", "Customer", "Date of birth", "Document number", "Officer id", "Risk level"])
    assert export.pii_like_columns(table) == ["Customer", "Date of birth", "Document number", "Officer id"]
    apps, reasons = base_tables()
    metrics = pd.DataFrame(columns=["model", "version", "version_order", "split", "metric", "value", "source", "note"])
    quick = export.tableau_tables({"applications": apps, "reasons": reasons, "model_metrics": metrics}, "x")
    assert all(not export.pii_like_columns(table) for table in quick.values())
