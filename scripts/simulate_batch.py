"""Simulate a realistic batch of KYC applications through the REAL pipeline (Phase 9), for the dashboard.

    .venv/bin/python scripts/simulate_batch.py --new        # plan a new batch and run it (about 1 hour for 150)
    .venv/bin/python scripts/simulate_batch.py              # resume an interrupted batch where it stopped
    .venv/bin/python scripts/simulate_batch.py --report     # only print the results of the current batch

Needs the system running (scripts/run_all.sh or the Docker "app" profile). Usually after reset_demo_data.py.

1. PLAN (seed 42): ~150 applications from TEST-split SIDTD templates only (synthetic documents, no real people).
   Scenario mix (shares of --n, rounded so they add up):
     genuine                 50 %  genuine document + a simulated selfie of its own portrait + the correct details
     forged_own_selfie       25 %  forged document + a selfie of the portrait on that forged document
     genuine_wrong_details    8 %  genuine document + own selfie, but a wrong date of birth or a misspelled name
     stranger_selfie          7 %  genuine document + a selfie of a DIFFERENT document's portrait (impostor)
     unreadable               5 %  a blank, white, almost black or non-document image as the "ID"
     forged_stranger          5 %  forged document + a stranger's selfie
   The details typed are the true ones of the (source) document; a fraudster types the original holder's details.
   Each application gets its own simulated customer account (the API has no sign-up: accounts are written to the
   store, like the demo accounts).
2. SUBMIT through POST /applications, one at a time, with random (exponential) gaps of --interval seconds on average,
   and never more than --max-open applications in progress, so the queue stays realistic. Every accepted submission
   is appended to the ground-truth CSV at once: an interrupted run resumes after the last one.
3. WAIT until every application of the batch is out of SUBMITTED / PROCESSING.
4. OFFICER: the demo officer works the review queue top-down (highest risk first), like a person would, until about
   --officer-share (70 %) of the batch's manual-review cases are decided: reject when the truth is a forgery, an
   impostor, wrong details or no document, approve otherwise (a false alarm). Reasons start with "Simulated officer".
   The rest stays open (DECIDED), so the dashboard has a queue with waiting times.
5. REPORT: outcome mix and system decision vs ground truth -> reports/phase9/batch_summary.{md,json}.

Files (local, gitignored, under data/processed/batch/):
  plan.csv          the full plan, including the name and date of birth to type (synthetic test documents)
  ground_truth.csv  one row per submitted application: application_id + scenario + the truth. NO names or DOBs.
"""

from __future__ import annotations

import argparse
import io
import json
import secrets
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import numpy as np
import pandas as pd
from dotenv import dotenv_values
from PIL import Image

from ekyc import config, face, schemas, security, store

API = "http://127.0.0.1:8000"
BATCH_DIR = config.PROCESSED_DIR / "batch"
PLAN_CSV = BATCH_DIR / "plan.csv"
TRUTH_CSV = BATCH_DIR / "ground_truth.csv"
REPORT_DIR = config.REPORTS_DIR / "phase9"
SCENARIOS = {"genuine": 0.50, "forged_own_selfie": 0.25, "genuine_wrong_details": 0.08, "stranger_selfie": 0.07,
             "unreadable": 0.05, "forged_stranger": 0.05}
UNREADABLE_KINDS = ("blank_black", "flat_white", "very_dark_photo", "not_a_document")
OPEN = ("SUBMITTED", "PROCESSING")
TRUTH_COLUMNS = ["plan_index", "application_id", "submitted_at", "scenario", "truth_class", "document_truth",
                 "selfie_truth", "details_truth", "expected_outcome", "doc_type", "source_document", "forgery_type",
                 "altered_field", "unreadable_kind"]


# ---------------------------------------------------------------- planning

def scenario_counts(n: int) -> dict[str, int]:
    """Largest-remainder rounding: the counts add up to n exactly."""
    raw = {s: share * n for s, share in SCENARIOS.items()}
    counts = {s: int(v) for s, v in raw.items()}
    for s in sorted(raw, key=lambda s: raw[s] - counts[s], reverse=True)[: n - sum(counts.values())]:
        counts[s] += 1
    return counts


def typed_name(given: str, surname: str, style: int) -> str:
    """How a customer might type their own name; all of these must match (case, accents and order are ignored)."""
    if style == 1:
        return " ".join(schemas.strip_diacritics(f"{given} {surname}").lower().split())
    if style == 2:
        return f"{surname} {given}"
    return f"{given} {surname}"


def misspell(name: str, rng: np.random.Generator, edits: int = 3) -> str:
    """Change `edits` letters of the surname: beyond the 0.85 similarity the name check tolerates for typos."""
    letters = list(name)
    positions = [i for i, c in enumerate(letters) if c.isalpha()]
    for i in rng.choice(positions, size=min(edits, len(positions)), replace=False):
        letters[i] = rng.choice([c for c in "AEIKMORSTUZ" if c != letters[i].upper()])
    return "".join(letters)


def build_plan(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    manifest = pd.read_csv(config.MANIFEST_CSV)
    fields = pd.read_csv(config.FIELDS_GT_CSV)
    photo_docs = set(fields.query("field_name == 'photo'")["doc_id"])
    truth = schemas.ground_truth_table(fields)
    truth["dob"] = [schemas.parse_date(v, "birth_date") for v in truth["birth_date"]]
    usable = set(truth.index[truth["surname"].notna() & truth["given_names"].notna() & truth["dob"].notna()]) & photo_docs
    test = manifest[(manifest["source"] == "template") & (manifest["split"] == "test")]
    genuine = test[(test["label"] == 0) & test["doc_id"].isin(usable)].sample(frac=1, random_state=seed)
    forged = test[(test["label"] == 1) & test["doc_id"].isin(usable)].sample(frac=1, random_state=seed)
    counts = scenario_counts(n)
    need_genuine = counts["genuine"] + counts["genuine_wrong_details"] + counts["stranger_selfie"] + counts["unreadable"]
    if need_genuine > len(genuine) or counts["forged_own_selfie"] + counts["forged_stranger"] > len(forged):
        raise SystemExit(f"not enough test templates for n={n} ({len(genuine)} genuine, {len(forged)} forged usable)")

    g_rows, f_rows = iter(genuine.itertuples()), iter(forged.itertuples())
    strangers = genuine.sample(frac=1, random_state=seed + 1)  # portraits for the impostor selfies
    plan = []

    def base(row, scenario: str, **extra) -> dict:
        t = truth.loc[row.doc_id]
        style = int(rng.integers(0, 3)) if scenario == "genuine" else 0
        return {"scenario": scenario, "doc_type": row.doc_type, "id_image_path": row.image_path,
                "source_document": row.fake_name if isinstance(row.fake_name, str) else row.doc_id,
                "holder_doc_id": row.doc_id, "selfie_image_path": row.image_path, "selfie_doc_id": row.doc_id,
                "full_name": typed_name(t.given_names, t.surname, style), "date_of_birth": t.dob,
                "forgery_type": row.ctype if isinstance(row.ctype, str) else "",
                "altered_field": row.altered_field if isinstance(row.altered_field, str) else "",
                "details_truth": "correct", "unreadable_kind": "", **extra}

    def stranger_for(doc_id: str, doc_type: str) -> tuple[str, str]:
        """A portrait from another genuine test document of a different type (a different person)."""
        candidates = strangers[(strangers["doc_id"] != doc_id) & (strangers["doc_type"] != doc_type)]
        pick = candidates.iloc[int(rng.integers(0, len(candidates)))]
        return pick["image_path"], pick["doc_id"]

    for _ in range(counts["genuine"]):
        plan.append(base(next(g_rows), "genuine"))
    for i in range(counts["genuine_wrong_details"]):
        row = next(g_rows)
        entry = base(row, "genuine_wrong_details")
        if i % 2 == 0:  # a wrong date of birth: off by 1-3 years and some days
            wrong = date.fromisoformat(entry["date_of_birth"]) + timedelta(days=int(rng.integers(30, 1100)) * int(rng.choice([-1, 1])))
            entry.update(date_of_birth=min(wrong, date.today()).isoformat(), details_truth="wrong_dob")
        else:
            t = truth.loc[row.doc_id]
            entry.update(full_name=f"{t.given_names} {misspell(t.surname, rng)}", details_truth="wrong_name")
        plan.append(entry)
    for _ in range(counts["stranger_selfie"]):
        row = next(g_rows)
        path, doc_id = stranger_for(row.doc_id, row.doc_type)
        plan.append(base(row, "stranger_selfie", selfie_image_path=path, selfie_doc_id=doc_id))
    for i in range(counts["unreadable"]):
        row = next(g_rows)  # its holder's details are typed and its portrait is the selfie
        plan.append(base(row, "unreadable", unreadable_kind=UNREADABLE_KINDS[i % len(UNREADABLE_KINDS)],
                         source_document="", doc_type=""))
    for _ in range(counts["forged_own_selfie"]):
        row = next(f_rows)  # the selfie shows the portrait printed on the forged page itself
        plan.append(base(row, "forged_own_selfie"))
    for _ in range(counts["forged_stranger"]):
        row = next(f_rows)
        path, doc_id = stranger_for(row.doc_id, row.doc_type)
        plan.append(base(row, "forged_stranger", selfie_image_path=path, selfie_doc_id=doc_id))

    df = pd.DataFrame(plan).sample(frac=1, random_state=seed).reset_index(drop=True)  # random arrival order
    df.insert(0, "plan_index", range(len(df)))
    df["selfie_seed"] = df["plan_index"] + 1000
    return df


def truth_fields(entry: pd.Series) -> dict:
    """The ground truth of one planned application (no names, no dates of birth)."""
    scenario = entry["scenario"]
    document = "forged" if scenario.startswith("forged") else "unusable" if scenario == "unreadable" else "genuine"
    selfie = "stranger" if scenario in ("stranger_selfie", "forged_stranger") else "own"
    if scenario == "genuine":
        truth_class, expected = "legitimate", "AUTO_APPROVED"
    elif scenario == "unreadable":
        truth_class, expected = "unusable", "RESUBMIT_REQUIRED"
    else:
        truth_class, expected = "fraud_or_mismatch", "MANUAL_REVIEW"
    return {"scenario": scenario, "truth_class": truth_class, "document_truth": document, "selfie_truth": selfie,
            "details_truth": entry["details_truth"], "expected_outcome": expected, "doc_type": entry["doc_type"],
            "source_document": entry["source_document"], "forgery_type": entry["forgery_type"],
            "altered_field": entry["altered_field"], "unreadable_kind": entry["unreadable_kind"]}


# ---------------------------------------------------------------- images

def jpeg(array: np.ndarray, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def page(path: str) -> np.ndarray:
    with Image.open(config.PROJECT_ROOT / path) as image:  # read-only access to data/interim
        return np.asarray(image.convert("RGB"))


def selfie(path: str, box_doc_id: str, boxes: pd.DataFrame, seed: int) -> bytes:
    """A simulated phone selfie of the portrait on a page (the photo box of `box_doc_id`, same layout)."""
    crop = face.crop_with_margin(page(path), boxes.loc[box_doc_id, ["x", "y", "w", "h"]].to_numpy())
    return jpeg(face.simulate_selfie(crop, np.random.default_rng(seed))[0])


def id_image(entry: pd.Series, boxes: pd.DataFrame, rng: np.random.Generator) -> bytes:
    kind = entry["unreadable_kind"]
    if not kind:
        return (config.PROJECT_ROOT / entry["id_image_path"]).read_bytes()  # the template file as it is
    if kind == "blank_black":
        return jpeg(np.full((630, 1000, 3), int(rng.integers(0, 12)), np.uint8))
    if kind == "flat_white":
        return jpeg(np.full((630, 1000, 3), int(rng.integers(235, 250)), np.uint8))
    if kind == "very_dark_photo":  # the real document, photographed with almost no light
        return jpeg((page(entry["id_image_path"]).astype(np.float32) * 0.04).astype(np.uint8))
    # not_a_document: a portrait (a selfie) uploaded as the ID document, enlarged to a page-like size
    crop = face.crop_with_margin(page(entry["selfie_image_path"]), boxes.loc[entry["selfie_doc_id"], ["x", "y", "w", "h"]].to_numpy())
    image = Image.fromarray(crop)
    return jpeg(np.asarray(image.resize((image.width * 3, image.height * 3))))


# ---------------------------------------------------------------- API helpers

class Api:
    def __init__(self, base_url: str, env: dict):
        self.client = httpx.Client(base_url=base_url, timeout=60)
        self.env = env
        self.db = store.connect()
        self._officer: tuple[dict, float] | None = None

    def login(self, email: str, password: str) -> dict:
        r = self.client.post("/auth/login", data={"username": email, "password": password})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def officer(self) -> dict:
        if self._officer is None or time.monotonic() - self._officer[1] > 20 * 60:  # tokens last 30 min
            self._officer = (self.login(self.env["DEMO_OFFICER_EMAIL"], self.env["DEMO_OFFICER_PASSWORD"]), time.monotonic())
        return self._officer[0]

    def customer(self, plan_index: int) -> dict:
        """A fresh simulated applicant account per application (new random password on every run)."""
        email, password = f"applicant-{plan_index:03d}@batch.ekyc", secrets.token_urlsafe(16)
        store.upsert_user(self.db, email, security.hash_password(password), "CUSTOMER")
        return self.login(email, password)

    def case(self, application_id: str) -> dict | None:
        r = self.client.get(f"/officer/cases/{application_id}", headers=self.officer())
        return None if r.status_code == 404 else r.raise_for_status().json()

    def statuses(self, ids: set[str]) -> dict[str, dict]:
        rows = self.client.get("/officer/cases", params={"limit": 500}, headers=self.officer()).raise_for_status().json()
        return {r["application_id"]: r for r in rows if r["application_id"] in ids}


# ---------------------------------------------------------------- the run

def read_truth() -> pd.DataFrame:
    return pd.read_csv(TRUTH_CSV, keep_default_na=False) if TRUTH_CSV.exists() else pd.DataFrame(columns=TRUTH_COLUMNS)


def append_truth(entry: pd.Series, application_id: str, submitted_at: str) -> None:
    row = {"plan_index": int(entry["plan_index"]), "application_id": application_id, "submitted_at": submitted_at,
           **truth_fields(entry)}
    pd.DataFrame([row], columns=TRUTH_COLUMNS).to_csv(TRUTH_CSV, mode="a", header=not TRUTH_CSV.exists(), index=False)


def reconcile(api: Api, plan: pd.DataFrame) -> int:
    """Adopt applications the API accepted but this script never recorded. That happens when the response is lost:
    e.g. the client timed out while the API, slowed down by a stalled broker, still finished the submission.
    Each plan row has its own account (applicant-NNN@batch.ekyc), so its applications are found by their owner.
    Without this, resuming would submit that row a second time and leave an application without ground truth."""
    known = set(read_truth()["application_id"])
    accounts = {u["user_id"]: int(u["email"].split("-")[1].split("@")[0])
                for u in api.db.users.find({"email": {"$regex": r"^applicant-\d{3}@batch\.ekyc$"}})}
    recorded = set(read_truth()["plan_index"].astype(int))
    by_index = plan.set_index("plan_index")
    adopted = 0
    for a in api.db.applications.find({"customer_id": {"$in": list(accounts)}}).sort("created_at", 1):
        index = accounts[a["customer_id"]]
        if a["application_id"] in known or index in recorded or index not in by_index.index:
            continue
        entry = by_index.loc[index].copy()
        entry["plan_index"] = index
        append_truth(entry, a["application_id"], a["created_at"].isoformat(timespec="seconds"))
        recorded.add(index)
        adopted += 1
        print(f"  adopted {a['application_id']} for plan row {index} (accepted by the API, response lost)")
    return adopted


def submit_all(api: Api, plan: pd.DataFrame, interval: float, max_open: int, seed: int) -> None:
    boxes = pd.read_csv(config.FIELDS_GT_CSV).query("field_name == 'photo'").set_index("doc_id")
    done = set(read_truth()["plan_index"].astype(int))
    todo = plan[~plan["plan_index"].isin(done)]
    rng = np.random.default_rng(seed + len(done))
    print(f"submitting {len(todo)} of {len(plan)} applications (mean gap {interval:.0f} s, at most {max_open} open)")
    ids = set(read_truth()["application_id"])
    for _, entry in todo.iterrows():
        while sum(1 for r in api.statuses(ids).values() if r["status"] in OPEN) >= max_open:
            time.sleep(2)  # back-pressure: like a quiet hour, arrivals wait while the pipeline is busy
        files = {"id_image": ("id.jpg", id_image(entry, boxes, rng), "image/jpeg"),
                 "selfie": ("selfie.jpg", selfie(entry["selfie_image_path"], entry["selfie_doc_id"], boxes,
                                                 int(entry["selfie_seed"])), "image/jpeg")}
        # a long timeout: under memory pressure the broker can stall for a minute (seen in Phase 6 and in this run);
        # if the response is lost anyway, reconcile() adopts the application on the next run
        r = api.client.post("/applications", headers=api.customer(int(entry["plan_index"])), timeout=300,
                            data={"full_name": entry["full_name"], "date_of_birth": entry["date_of_birth"]}, files=files)
        if r.status_code != 202:
            raise SystemExit(f"plan row {entry['plan_index']}: HTTP {r.status_code} {r.text[:200]}")
        app_id = r.json()["application_id"]
        ids.add(app_id)
        append_truth(entry, app_id, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        print(f"  {len(ids):>3}/{len(plan)}  {app_id}  {entry['scenario']}", flush=True)
        time.sleep(float(rng.exponential(interval)))


def wait_until_decided(api: Api, ids: set[str], limit_s: float = 1200) -> None:
    started = time.monotonic()
    while time.monotonic() - started < limit_s:
        open_ids = [i for i, r in api.statuses(ids).items() if r["status"] in OPEN]
        if not open_ids:
            print("every application of the batch has a decision")
            return
        print(f"  waiting for {len(open_ids)} application(s) still in progress", flush=True)
        time.sleep(10)
    print(f"WARNING: still in progress after {limit_s:.0f} s; continuing")


OFFICER_REASONS = {
    "forged_own_selfie": "Simulated officer: document altered; the heatmap and the field checks point to an edited field.",
    "forged_stranger": "Simulated officer: edited document, and the selfie shows a different person.",
    "stranger_selfie": "Simulated officer: the selfie shows a different person from the ID portrait.",
    "wrong_dob": "Simulated officer: the date of birth entered does not match the document.",
    "wrong_name": "Simulated officer: the name entered does not match the document.",
    "unreadable": "Simulated officer: the upload does not show a valid ID document.",
    "approve": "Simulated officer: checked by hand; genuine document and matching selfie, the flag was a false alarm.",
}


def officer_pass(api: Api, truth: pd.DataFrame, share: float, seed: int) -> None:
    rng = np.random.default_rng(seed + 7)
    by_id = truth.set_index("application_id")
    rows = api.statuses(set(truth["application_id"]))
    review = [i for i, r in rows.items() if r["outcome"] == "MANUAL_REVIEW"]
    already = [i for i in review if rows[i]["status"] in ("APPROVED", "REJECTED")]
    target = round(share * len(review))
    queue = sorted((i for i in review if rows[i]["status"] == "DECIDED"),  # the officer's queue order
                   key=lambda i: (-(rows[i]["risk_score"] or 0), rows[i]["created_at"]))
    todo = queue[: max(0, target - len(already))]
    print(f"officer: {len(review)} manual-review cases, {len(already)} already decided, deciding {len(todo)} more "
          f"(target {share:.0%} = {target})")
    for application_id in todo:
        t = by_id.loc[application_id]
        legitimate = t["truth_class"] == "legitimate"
        key = "approve" if legitimate else t["details_truth"] if t["scenario"] == "genuine_wrong_details" else t["scenario"]
        r = api.client.post(f"/officer/cases/{application_id}/decision", headers=api.officer(),
                            json={"action": "approve" if legitimate else "reject", "reason": OFFICER_REASONS[key]})
        print(f"  {application_id}  {t['scenario']:<22} -> {'approve' if legitimate else 'reject'} (HTTP {r.status_code})",
              flush=True)
        time.sleep(float(rng.uniform(2, 6)))  # reading the case


# ---------------------------------------------------------------- report

def report(api: Api, truth: pd.DataFrame) -> dict:
    rows = api.statuses(set(truth["application_id"]))
    df = truth.copy()
    df["outcome"] = df["application_id"].map(lambda i: (rows.get(i) or {}).get("outcome"))
    df["status"] = df["application_id"].map(lambda i: (rows.get(i) or {}).get("status"))
    df["risk_level"] = df["application_id"].map(lambda i: (rows.get(i) or {}).get("risk_level"))
    n = len(df)
    mix = df["outcome"].fillna("(none)").value_counts()
    statuses = df["status"].fillna("(missing)").value_counts()
    confusion = pd.crosstab(df["truth_class"], df["outcome"].fillna("(none)"), margins=True, margins_name="total")
    by_scenario = pd.crosstab(df["scenario"], df["outcome"].fillna("(none)"), margins=True, margins_name="total")
    fraud = df[df["truth_class"] == "fraud_or_mismatch"]
    legit = df[df["truth_class"] == "legitimate"]
    reviewed = df[df["status"].isin(["APPROVED", "REJECTED"]) & (df["outcome"] == "MANUAL_REVIEW")]
    metrics = {
        "applications": n,
        "fraud_caught (not auto-approved)": f"{(fraud['outcome'] != 'AUTO_APPROVED').sum()}/{len(fraud)}",
        "fraud_missed (auto-approved)": int((fraud["outcome"] == "AUTO_APPROVED").sum()),
        "legitimate_auto_approved": f"{(legit['outcome'] == 'AUTO_APPROVED').sum()}/{len(legit)}",
        "false_alarms (legitimate -> manual review)": int((legit["outcome"] == "MANUAL_REVIEW").sum()),
        "legitimate_asked_to_resubmit": int((legit["outcome"] == "RESUBMIT_REQUIRED").sum()),
        "officer_decided": len(reviewed), "officer_rejected": int((reviewed["status"] == "REJECTED").sum()),
        "still_awaiting_officer": int((df["status"] == "DECIDED").sum()),
    }
    lines = ["# Phase 9 simulated batch", "",
             f"{n} applications through the real pipeline (TEST-split synthetic templates); the ground truth is in "
             "`data/processed/batch/ground_truth.csv` (local).", "",
             "## System outcome mix", "", "| outcome | applications | share |", "|---|---:|---:|"]
    lines += [f"| {k} | {v} | {v / n:.0%} |" for k, v in mix.items()]
    lines += ["", "## Final status", "", "| status | applications |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in statuses.items()]
    for title, table in (("System decision vs ground truth", confusion), ("Outcome per scenario", by_scenario)):
        lines += ["", f"## {title}", "", "| | " + " | ".join(table.columns) + " |", "|---|" + "---:|" * len(table.columns)]
        lines += [f"| {idx} | " + " | ".join(str(v) for v in r) + " |" for idx, r in table.iterrows()]
    lines += ["", "## Key numbers", ""] + [f"- **{k}:** {v}" for k, v in metrics.items()] + [""]
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "batch_summary.md").write_text("\n".join(lines))
    summary = {"metrics": metrics, "outcome_mix": mix.to_dict(), "status_mix": statuses.to_dict(),
               "confusion": confusion.to_dict(), "by_scenario": by_scenario.to_dict()}
    (REPORT_DIR / "batch_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print("\n".join(lines))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--new", action="store_true", help="plan a new batch (the previous files are kept, renamed)")
    parser.add_argument("--report", action="store_true", help="only print the report of the current batch")
    parser.add_argument("--n", type=int, default=150, help="applications in a new batch (default 150)")
    parser.add_argument("--interval", type=float, default=20.0, help="mean seconds between submissions (default 20)")
    parser.add_argument("--max-open", type=int, default=3, help="at most this many applications in progress (default 3)")
    parser.add_argument("--officer-share", type=float, default=0.7, help="share of manual-review cases the officer decides")
    parser.add_argument("--seed", type=int, default=config.SEED)
    parser.add_argument("--api", default=API)
    args = parser.parse_args()
    api = Api(args.api, dotenv_values(config.PROJECT_ROOT / ".env"))
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    if args.new:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for path in (PLAN_CSV, TRUTH_CSV):
            if path.exists():
                path.rename(path.with_name(f"{path.stem}.{stamp}{path.suffix}"))
        build_plan(args.n, args.seed).to_csv(PLAN_CSV, index=False)
        print(f"planned {args.n} applications -> {PLAN_CSV.relative_to(config.PROJECT_ROOT)}: {scenario_counts(args.n)}")
    if not PLAN_CSV.exists():
        print("no batch planned yet: run with --new")
        return 1
    plan = pd.read_csv(PLAN_CSV, keep_default_na=False)
    truth = read_truth()
    if len(truth) and api.case(truth["application_id"].iloc[0]) is None:
        print("the applications of this batch are no longer in the system (reset?): run with --new")
        return 1
    if not args.report:
        started = time.monotonic()
        reconcile(api, plan)
        submit_all(api, plan, args.interval, args.max_open, args.seed)
        truth = read_truth()
        wait_until_decided(api, set(truth["application_id"]))
        officer_pass(api, truth, args.officer_share, args.seed)
        print(f"batch finished in {(time.monotonic() - started) / 60:.1f} min")
    report(api, read_truth())
    return 0


if __name__ == "__main__":
    sys.exit(main())
