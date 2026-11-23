"""The dashboards' bundled data (Phase 12): scripts/export_dashboard_snapshot.py.

No services needed (runs in CI): it reads the committed CSVs of dashboard/data/tableau/. Checks that the snapshot
bundled with the frontend is up to date with them, that the format is the compact one the frontend parses, and that
the privacy guard stops personal-looking columns and values.
"""

import importlib.util
import json
import shutil
import sys

import pandas as pd
import pytest

from ekyc import config

SCRIPTS = config.PROJECT_ROOT / "scripts"


def load_script(name):
    sys.path.insert(0, str(SCRIPTS))  # the script imports its sibling export_dashboard_data
    try:
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


snapshot_script = load_script("export_dashboard_snapshot")


def test_the_bundled_snapshot_is_up_to_date_with_the_csvs():
    expected = snapshot_script.to_json(snapshot_script.build_snapshot())
    assert snapshot_script.SNAPSHOT.read_text(encoding="utf-8") == expected, (
        "frontend/src/dashboards/snapshot.json is out of date: run scripts/export_dashboard_snapshot.py")


def test_compact_format_and_batch_numbers():
    snapshot = json.loads(snapshot_script.SNAPSHOT.read_text(encoding="utf-8"))
    assert snapshot["schemaVersion"] == 1 and snapshot["synthetic"] is True
    assert snapshot["dataAsOf"] == "2026-11-18T09:36:12Z"
    ops = snapshot["tables"]["operations"]
    rows = [dict(zip(ops["columns"], row)) for row in ops["rows"]]
    assert len(rows) == 150
    assert sum(r["applications"] for r in rows) == 150
    assert sum(r["autoApproved"] for r in rows) == 49  # whole numbers are ints, not 49.0
    assert all(isinstance(r["autoApproved"], int) for r in rows)
    assert any(r["queueAgeMin"] is None for r in rows)  # empty cells are null
    risk = snapshot["tables"]["riskFraud"]
    first_rows = [dict(zip(risk["columns"], row)) for row in risk["rows"] if row[risk["columns"].index("applications")] == 1]
    assert len(first_rows) == 150 and len({r["case"] for r in first_rows}) == 150  # case numbers once per case


@pytest.fixture
def tableau_copy(tmp_path):
    folder = tmp_path / "tableau"
    shutil.copytree(snapshot_script.TABLEAU_OUT, folder)
    return folder


def test_privacy_guard_stops_personal_columns(tableau_copy):
    ops = pd.read_csv(tableau_copy / "operations.csv")
    ops.insert(1, "Customer email", "x")
    ops.to_csv(tableau_copy / "operations.csv", index=False)
    snapshot_script.TABLES["operations"][1]["Customer email"] = "email"
    try:
        with pytest.raises(RuntimeError, match="PII-like columns"):
            snapshot_script.build_snapshot(tableau_copy)
    finally:
        del snapshot_script.TABLES["operations"][1]["Customer email"]


def test_privacy_guard_stops_emails_and_real_ids_in_values(tableau_copy):
    for leaked in ("someone@example.com", "app-6b6fd4213a30fbe8"):
        ops = pd.read_csv(snapshot_script.TABLEAU_OUT / "operations.csv")
        ops.loc[0, "Case"] = leaked
        ops.to_csv(tableau_copy / "operations.csv", index=False)
        risk = pd.read_csv(snapshot_script.TABLEAU_OUT / "risk_fraud.csv")
        risk.loc[0, "Case"] = leaked  # keep the two files consistent: only the guard should object
        risk.to_csv(tableau_copy / "risk_fraud.csv", index=False)
        with pytest.raises(RuntimeError, match="look like e-mails or real ids"):
            snapshot_script.build_snapshot(tableau_copy)


def test_missing_column_is_a_clear_error(tableau_copy):
    pd.read_csv(tableau_copy / "model_performance.csv").drop(columns="Used in chart").to_csv(
        tableau_copy / "model_performance.csv", index=False)
    with pytest.raises(ValueError, match="missing columns"):
        snapshot_script.build_snapshot(tableau_copy)
