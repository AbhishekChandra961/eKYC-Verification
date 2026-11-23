"""Bundle the dashboard data with the frontend (Phase 12): dashboard/data/tableau/*.csv -> one compact JSON snapshot.

    .venv/bin/python scripts/export_dashboard_snapshot.py      # or, in frontend/: npm run gen:dashboards

Reads the three quick-path files written by scripts/export_dashboard_data.py (no MongoDB needed) and writes
frontend/src/dashboards/snapshot.json, which the in-app dashboards (Operations, Risk & fraud, Model performance) load.

COMPACT: only the columns the dashboards use, renamed to short keys; each table is a list of column names plus one
array of values per row (no key repeated per row), one row per line so a git diff shows what changed. Empty cells
become null. The pre-computed columns of the CSVs are kept as they are ((0/1) indicators, funnel stages): the
frontend only adds them up or averages them, so every rule is defined once, in export_dashboard_data.py.

PII-FREE, as the CSVs: the same column guard (pii_like_columns) plus a value check (no e-mail address, no real
application id). Case ids are the export's pseudonyms (C0001...). All the data is synthetic.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd

from ekyc import config
from export_dashboard_data import NO_REASON, TABLEAU_OUT, pii_like_columns

SNAPSHOT = config.PROJECT_ROOT / "frontend" / "src" / "dashboards" / "snapshot.json"
SCHEMA_VERSION = 1

# CSV column -> snapshot key, per file. The frontend (src/dashboards/snapshot.ts) expects exactly these keys.
FUNNEL = {f"Funnel {n} {stage}": f"funnel{n}" for n, stage in enumerate(
    ("Submitted", "Decided by the system", "Sent to an officer", "Decided by an officer", "Rejected by an officer"), 1)}
TABLES = {
    "operations": ("operations.csv", {
        "Case": "case", "Document type": "docType", "System outcome": "systemOutcome", "Outcome": "outcome",
        "Risk level": "riskLevel", "Applications": "applications", "Auto-approved (0/1)": "autoApproved",
        "Manual review (0/1)": "manualReview", "Resubmit required (0/1)": "resubmitRequired",
        "Time to decision (s)": "timeToDecisionS", "Doc check (s)": "docCheckS", "Face check (s)": "faceCheckS",
        "Forgery check (s)": "forgeryCheckS", "Extraction check (s)": "extractionCheckS", **FUNNEL,
        "Waiting for an officer (0/1)": "waitingForOfficer", "Queue age (min)": "queueAgeMin"}),
    "riskFraud": ("risk_fraud.csv", {
        "Case": "case", "Document type": "docType", "System outcome": "systemOutcome", "Outcome": "outcome",
        "Risk level": "riskLevel", "Risk score band": "riskScoreBand", "Truth class": "truthClass",
        "System vs truth": "systemVsTruth", "Reason": "reason", "Reason effect": "reasonEffect",
        "Raised by": "raisedBy", "Cases with this reason": "casesWithReason", "Applications": "applications",
        "Risk score": "riskScore", "Fraud caught (0/1)": "fraudCaught", "Missed fraud (0/1)": "missedFraud",
        "False alarm (0/1)": "falseAlarm", "Officer confirmed the flag (0/1)": "officerConfirmedFlag",
        "Officer agrees with truth (0/1)": "officerAgreesWithTruth"}),
    "modelPerformance": ("model_performance.csv", {
        "Model": "model", "Version": "version", "Version order": "versionOrder", "Split": "split", "Metric": "metric",
        "Value": "value", "Used in chart": "chart", "Field": "field", "Match type": "matchType", "Note": "note",
        "Source": "source"}),
}
PII_VALUES = re.compile(r"@|\bapp-[0-9a-f]{6,}|\buser-", re.IGNORECASE)  # e-mails, real application/user ids


def cell(value):
    """A JSON value: None for an empty cell, whole numbers as ints (1 instead of 1.0), everything else as is."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if hasattr(value, "item"):  # numpy scalar
        return cell(value.item())
    return value


def read_table(folder: Path, file: str, columns: dict[str, str]) -> pd.DataFrame:
    frame = pd.read_csv(folder / file, keep_default_na=True)
    if missing := [c for c in columns if c not in frame.columns]:
        raise ValueError(f"{file}: missing columns {missing} (re-run scripts/export_dashboard_data.py?)")
    return frame


def check_privacy(name: str, frame: pd.DataFrame) -> None:
    if leaked := pii_like_columns(frame):
        raise RuntimeError(f"{name}: PII-like columns {leaked}")
    text = frame.select_dtypes(exclude="number").to_numpy().ravel()
    if hits := sorted({str(v) for v in text if isinstance(v, str) and PII_VALUES.search(v)}):
        raise RuntimeError(f"{name}: values that look like e-mails or real ids {hits[:3]}")


def build_snapshot(folder: Path = TABLEAU_OUT) -> dict:
    frames = {name: read_table(folder, file, columns) for name, (file, columns) in TABLES.items()}
    as_of = frames["operations"]["Data as of (UTC)"].dropna().unique()
    if len(as_of) != 1:
        raise ValueError(f"operations.csv: expected one 'Data as of (UTC)' value, found {list(as_of)}")
    cases = set(frames["operations"]["Case"])
    if stray := set(frames["riskFraud"]["Case"]) - cases:
        raise ValueError(f"risk_fraud.csv: cases missing from operations.csv {sorted(stray)[:3]}")

    tables = {}
    for name, (_, columns) in TABLES.items():
        kept = frames[name][list(columns)].rename(columns=columns)
        check_privacy(name, frames[name][list(columns)])
        check_privacy(name, kept)
        tables[name] = {"columns": list(kept.columns),
                        "rows": [[cell(v) for v in row] for row in kept.itertuples(index=False, name=None)]}
    return {
        "about": "PII-free snapshot of dashboard/data/tableau/*.csv for the in-app dashboards (synthetic data). "
                 "GENERATED by scripts/export_dashboard_snapshot.py: do not edit.",
        "schemaVersion": SCHEMA_VERSION,
        "dataAsOf": pd.Timestamp(as_of[0]).strftime("%Y-%m-%dT%H:%M:%SZ"),  # the CSVs' times are UTC
        "synthetic": True,
        "funnelStages": [column.split(" ", 2)[2] for column in FUNNEL],
        "noReason": NO_REASON,
        "tables": tables,
    }


def to_json(snapshot: dict) -> str:
    """Compact, but one table row per line (readable diffs)."""
    def dump(value) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    head = {k: v for k, v in snapshot.items() if k != "tables"}
    lines = ["{" + ",".join(f"{dump(k)}:{dump(v)}" for k, v in head.items()) + ',"tables":{']
    for i, (name, table) in enumerate(snapshot["tables"].items()):
        rows = ",\n".join(dump(row) for row in table["rows"])
        end = "," if i < len(snapshot["tables"]) - 1 else ""
        lines.append(f'{dump(name)}:{{"columns":{dump(table["columns"])},"rows":[\n{rows}\n]}}{end}')
    lines.append("}}")
    return "\n".join(lines) + "\n"


def main() -> None:
    snapshot = build_snapshot()
    text = to_json(snapshot)
    json.loads(text)  # valid JSON, or this raises
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(text, encoding="utf-8")
    sizes = ", ".join(f"{name} {len(t['rows'])} rows x {len(t['columns'])}" for name, t in snapshot["tables"].items())
    print(f"wrote {SNAPSHOT.relative_to(config.PROJECT_ROOT)} ({len(text.encode()):,} bytes): {sizes}; "
          f"data as of {snapshot['dataAsOf']}")


if __name__ == "__main__":
    main()
