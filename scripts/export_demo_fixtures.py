"""Fixtures for the static demo site (Phase 11): precomputed outputs of REAL pipeline runs, nothing invented.

The demo site (frontend demo mode, GitHub Pages) has no backend. It replays what the real system produced:
  run     As the demo CUSTOMER, submit the six demo samples (demo_samples/: 3 genuine, 2 forged, 1 blank) through the
          real API, one at a time, and record the live status stream (Server-Sent Events) of each, with the time of
          every event since the submission started. -> data/processed/demo_site/runs.json (local)
  export  As the demo OFFICER, read those six cases and a handful of Phase 9 batch cases through the real API (the
          queue rows and full case details: checks, heatmap, reasons with evidence, summaries, audit trail) and the
          images the pipeline received (from the S3 store, via the API's presigned links).
          -> frontend/src/demo/fixtures/fixtures.gen.ts and frontend/src/demo/fixtures/images/*.jpg (committed)

Needs the system running in host mode (scripts/run_all.sh, with Ollama) for `run`; `export` needs only the API, the
infrastructure and the data. Usage:
    .venv/bin/python scripts/export_demo_fixtures.py run
    .venv/bin/python scripts/export_demo_fixtures.py export
    .venv/bin/python scripts/export_demo_fixtures.py all

What is changed on export (presentation only, never a result):
  - the image links become bundled file names, and the images are resized and recompressed for the web
    (documents 1024 px longest side, selfies 360 px, JPEG, no metadata). The results come from the full-size uploads;
  - nothing else: statuses, outcomes, scores, reasons, summaries, timestamps and audit entries are as the API returned
    them. All data is synthetic (SIDTD documents with generated faces; the names and dates are printed on them).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import httpx
import pandas as pd
from dotenv import dotenv_values
from PIL import Image

from ekyc import config

API = os.environ.get("EKYC_API_URL", "http://127.0.0.1:8000")
ENV = dotenv_values(config.PROJECT_ROOT / ".env")
SAMPLES_DIR = config.PROJECT_ROOT / "demo_samples"
RUNS_JSON = config.PROJECT_ROOT / "data" / "processed" / "demo_site" / "runs.json"
BATCH_TRUTH = config.PROJECT_ROOT / "data" / "processed" / "batch" / "ground_truth.csv"
OUT_DIR = config.PROJECT_ROOT / "frontend" / "src" / "demo" / "fixtures"
FINAL = ("DECIDED", "APPROVED", "REJECTED", "RESUBMIT_REQUESTED")  # the stream ends at these (Phase 9 lifecycle)
DOCUMENT_PX, SELFIE_PX = 1024, 360  # longest side of the web copies
DOC_LABELS = {"alb_id": "Albanian ID card", "aze_passport": "Azerbaijani passport", "esp_id": "Spanish ID card",
              "est_id": "Estonian ID card", "fin_id": "Finnish ID card", "grc_passport": "Greek passport",
              "lva_passport": "Latvian passport", "rus_internalpassport": "Russian internal passport",
              "srb_passport": "Serbian passport", "svk_id": "Slovak ID card"}

FIELD_LABELS = {"surname_eng": "surname", "surname_second": "second surname", "name": "given name",
                "name_eng": "given name"}

# Phase 9 batch cases shown in the officer queue, so it looks like a working day: (status, system outcome, batch
# scenario, how many). The first matching cases in plan order are taken, so the choice is reproducible.
BATCH_PICKS = [
    ("DECIDED", "MANUAL_REVIEW", "genuine", 2),  # false alarms waiting for an officer
    ("DECIDED", "MANUAL_REVIEW", "genuine_wrong_details", 1),  # a typed detail differs from the document
    ("REJECTED", "MANUAL_REVIEW", "forged_own_selfie", 1),  # rejected by the simulated officer
    ("REJECTED", "MANUAL_REVIEW", "stranger_selfie", 1),
    ("APPROVED", "MANUAL_REVIEW", "genuine", 1),  # approved by the simulated officer after a review
    ("APPROVED", "AUTO_APPROVED", "genuine", 2),
    ("RESUBMIT_REQUESTED", "RESUBMIT_REQUIRED", "unreadable", 1),
]


def account(role: str) -> tuple[str, str]:
    email, password = ENV.get(f"DEMO_{role}_EMAIL"), ENV.get(f"DEMO_{role}_PASSWORD")
    if not email or not password:
        sys.exit(f"DEMO_{role}_EMAIL / DEMO_{role}_PASSWORD missing in .env")
    return email, password


def login(client: httpx.Client, role: str) -> dict:
    email, password = account(role)
    r = client.post("/auth/login", data={"username": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def samples() -> list[dict]:
    path = SAMPLES_DIR / "manifest.json"
    if not path.exists():
        sys.exit("demo_samples/ is missing: run scripts/make_demo_samples.py first")
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ run: the six samples through the real system

def run_sample(client: httpx.Client, headers: dict, sample: dict) -> dict:
    """Submit one sample and read its status stream to the end. Times are milliseconds since the upload started."""
    files = {"id_image": (sample["id_image"], (SAMPLES_DIR / sample["id_image"]).read_bytes(), "image/jpeg"),
             "selfie": (sample["selfie"], (SAMPLES_DIR / sample["selfie"]).read_bytes(), "image/jpeg")}
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    started = time.perf_counter()
    r = client.post("/applications", headers=headers, files=files,
                    data={"full_name": sample["full_name"], "date_of_birth": sample["date_of_birth"]})
    r.raise_for_status()
    application_id = r.json()["application_id"]
    submit_ms = round((time.perf_counter() - started) * 1000)
    events = []
    with httpx.stream("GET", f"{API}/applications/{application_id}/events", headers=headers, timeout=600) as stream:
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            view = json.loads(line[6:])
            events.append({"at_ms": round((time.perf_counter() - started) * 1000), "view": view})
            if view["status"] in FINAL:
                break
    if not events or events[-1]["view"]["status"] not in FINAL:
        raise RuntimeError(f"{sample['name']}: the stream ended before a final status")
    last = events[-1]
    print(f"  {sample['name']:10s} {application_id}  {last['view']['status']:18s} {last['view']['outcome'] or '-':18s}"
          f" {last['at_ms'] / 1000:5.1f} s  ({len(events)} status events)")
    return {"sample": sample["name"], "application_id": application_id, "recorded_at": recorded_at,
            "submit_ms": submit_ms, "events": events}


def run() -> None:
    with httpx.Client(base_url=API, timeout=120) as client:
        client.get("/health").raise_for_status()
        headers = login(client, "CUSTOMER")
        print(f"Submitting {len(samples())} demo samples one at a time (as a single visitor would):")
        runs = [run_sample(client, headers, s) for s in samples()]
    RUNS_JSON.parent.mkdir(parents=True, exist_ok=True)
    RUNS_JSON.write_text(json.dumps(runs, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"-> {RUNS_JSON.relative_to(config.PROJECT_ROOT)}")


# ------------------------------------------------------------------ export: officer data + web images

def web_jpeg(data: bytes, longest: int) -> bytes:
    """A smaller copy for the web: RGB, longest side <= `longest`, JPEG, no metadata (EXIF is not copied)."""
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        scale = longest / max(image.size)
        if scale < 1:
            image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, "JPEG", quality=72, optimize=True, progressive=True)
        return out.getvalue()


def pick_batch_cases(rows: dict[str, dict]) -> list[tuple[str, str]]:
    """(application_id, batch scenario) for BATCH_PICKS, from the Phase 9 batch ground truth (no names or dates)."""
    truth = pd.read_csv(BATCH_TRUTH).sort_values("plan_index")
    picked = []
    for status, outcome, scenario, count in BATCH_PICKS:
        found = [a for a, s in zip(truth.application_id, truth.scenario)
                 if s == scenario and a in rows and rows[a]["status"] == status and rows[a]["outcome"] == outcome]
        if len(found) < count:
            raise RuntimeError(f"only {len(found)} batch cases for {status}/{outcome}/{scenario}; was the database reset?")
        picked += [(a, scenario) for a in found[:count]]
    return picked


def scenario_text(sample: dict) -> tuple[str, str]:
    """A title and a one-line description of a demo sample (what is IN it; the outcome is left to the replay)."""
    if sample["name"] == "blank":
        return "Unusable photo", "An almost black image instead of an ID document, with a selfie."
    m = re.match(r"\S+ \((genuine|forged) (\w+)(?:, edited field: (\w+))?\)", sample["document"])
    if not m:
        raise ValueError(f"unexpected document description: {sample['document']}")
    kind, doc_type, field = m.groups()
    label = DOC_LABELS[doc_type]
    if kind == "genuine":
        return f"{label}, genuine", "With the holder's own selfie and the details printed on the document."
    readable = FIELD_LABELS.get(field, field.replace("_", " "))
    return f"{label}, forged", f"A field was rewritten ({readable}); the selfie shows a different person."


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ts_literal(value, indent: int = 0) -> str:
    """JSON (valid TypeScript) with one key per line, but lists of plain values (heatmap tiles) on one line."""
    pad = " " * indent
    flat = lambda v: not isinstance(v, (dict, list)) or (isinstance(v, list) and all(not isinstance(x, (dict, list)) for x in v))  # noqa: E731
    if isinstance(value, dict) and value:
        items = [f"{pad} {json.dumps(k, ensure_ascii=False)}: {ts_literal(v, indent + 1)}" for k, v in value.items()]
        return "{\n" + ",\n".join(items) + f"\n{pad}}}"
    if isinstance(value, list) and value and not all(flat(v) for v in value):
        items = [f"{pad} {ts_literal(v, indent + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + f"\n{pad}]"
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def export() -> None:
    if not RUNS_JSON.exists():
        sys.exit(f"{RUNS_JSON.relative_to(config.PROJECT_ROOT)} is missing: run `export_demo_fixtures.py run` first")
    runs = json.loads(RUNS_JSON.read_text(encoding="utf-8"))
    by_sample = {s["name"]: s for s in samples()}
    images_dir = OUT_DIR / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    for old in images_dir.glob("*.jpg"):  # only this script writes here
        old.unlink()

    with httpx.Client(base_url=API, timeout=120) as client:
        headers = login(client, "OFFICER")
        listed = client.get("/officer/cases", params={"limit": 500}, headers=headers)
        listed.raise_for_status()
        rows = {row["application_id"]: row for row in listed.json()}
        chosen = [(r["application_id"], "demo_sample", r["sample"]) for r in runs]
        chosen += [(a, "batch", scenario) for a, scenario in pick_batch_cases(rows)]

        cases, files = [], {}
        for application_id, source, label in chosen:
            r = client.get(f"/officer/cases/{application_id}", headers=headers)
            r.raise_for_status()
            detail = r.json()
            for kind, longest in (("document", DOCUMENT_PX), ("selfie", SELFIE_PX)):
                image = httpx.get(detail["images"][f"{kind}_url"], timeout=60)
                image.raise_for_status()
                web = web_jpeg(image.content, longest)
                name = f"{sha256(web)[:16]}.jpg"  # named by content: an image used by several cases is stored once
                files[name] = web
                detail["images"][f"{kind}_url"] = name  # the demo client turns this into the bundled image's URL
            cases.append({"source": source, "label": label, "row": rows[application_id], "detail": detail})

    for name, data in files.items():
        (images_dir / name).write_bytes(data)

    scenarios = []
    for r in runs:
        sample = by_sample[r["sample"]]
        title, description = scenario_text(sample)
        images = next(c["detail"]["images"] for c in cases if c["row"]["application_id"] == r["application_id"])
        document, selfie = images["document_url"], images["selfie_url"]
        scenarios.append({
            "id": sample["name"], "title": title, "description": description,
            "applicant": {"full_name": sample["full_name"], "date_of_birth": sample["date_of_birth"]},
            "document": {"file": document, "sha256": sha256(files[document])},
            "selfie": {"file": selfie, "sha256": sha256(files[selfie])},
            "run": {"application_id": r["application_id"], "recorded_at": r["recorded_at"], "submit_ms": r["submit_ms"],
                    "events": r["events"]},
        })

    fixtures = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": "scripts/export_demo_fixtures.py: real runs of the eKYC pipeline v1.0.0 (host mode)",
                "scenarios": scenarios, "cases": cases}
    body = ts_literal(fixtures)
    out = OUT_DIR / "fixtures.gen.ts"
    out.write_text("// GENERATED by scripts/export_demo_fixtures.py. Do not edit: re-run the script.\n"
                   "// Real pipeline outputs for the demo site (README: Live demo). All data is synthetic (SIDTD).\n"
                   "import type { DemoFixtures } from '../types'\n\n"
                   f"const fixtures: DemoFixtures = {body}\n\nexport default fixtures\n", encoding="utf-8")
    total = sum(len(d) for d in files.values())
    print(f"{len(scenarios)} scenarios, {len(cases)} cases ({sum(c['source'] == 'batch' for c in cases)} from the batch)")
    print(f"-> {out.relative_to(config.PROJECT_ROOT)} ({out.stat().st_size / 1024:.0f} KB)")
    print(f"-> {images_dir.relative_to(config.PROJECT_ROOT)}/ ({len(files)} images, {total / 1024:.0f} KB)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["run", "export", "all"])
    step = parser.parse_args().step
    if step in ("run", "all"):
        run()
    if step in ("export", "all"):
        export()
    return 0


if __name__ == "__main__":
    sys.exit(main())
