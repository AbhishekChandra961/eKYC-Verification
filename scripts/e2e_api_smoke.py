"""End-to-end test through the API only (Phase 7). Needs the system running (and Ollama), either as host processes
(scripts/run_all.sh) or as containers (docker compose --profile app up -d, Phase 9): both serve the API on :8000.
    .venv/bin/python scripts/e2e_api_smoke.py                 # results: reports/phase7/e2e_api_results.json
    .venv/bin/python scripts/e2e_api_smoke.py --results reports/phase9/e2e_api_containers.json

As the demo CUSTOMER: submit four applications and follow each one over Server-Sent Events until it is decided:
  1. a genuine test passport + a simulated selfie of its own portrait + the right name/DOB  -> AUTO_APPROVED (APPROVED)
  2. a forged test passport + a stranger's selfie                                           -> MANUAL_REVIEW high (DECIDED)
  3. a blank (black) image as the ID document                        -> RESUBMIT_REQUIRED (RESUBMIT_REQUESTED)
  4. the genuine passport of case 1 with a wrong date of birth                              -> MANUAL_REVIEW (DECIDED)
As the demo OFFICER: list the queue (the forged case on top), open it, reject it with a reason, show its audit trail.
Security: customer -> officer endpoint (403), another customer's application (404), invalid/expired token (401).

Needs only the SIDTD templates (README quickstart): the three test-split documents are fixed below (they are the ones
the Phase 7 version picked from the manifest). If data/processed/manifest.csv exists, they are checked to be TEST-split.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import numpy as np
import pandas as pd
from dotenv import dotenv_values
from PIL import Image

from ekyc import config, data, face, schemas, security, store

API = os.environ.get("EKYC_API_URL", "http://127.0.0.1:8000")
ENV = dotenv_values(config.PROJECT_ROOT / ".env")
FINAL = ("DECIDED", "APPROVED", "REJECTED", "RESUBMIT_REQUESTED")  # the SSE stream ends at these (Phase 9 lifecycle)
EXPECTED_STATUS = {"AUTO_APPROVED": "APPROVED", "MANUAL_REVIEW": "DECIDED", "RESUBMIT_REQUIRED": "RESUBMIT_REQUESTED"}
GENUINE = "srb_passport_04"  # test split: the genuine applicant (cases 1, 3, 4)
FORGED = "aze_passport_75_fake_3_39"  # test split: an inpaint-and-rewrite forgery (case 2)
STRANGER = "lva_passport_09"  # test split: the stranger whose portrait becomes the fraudster's selfie (case 2)


def jpeg_bytes(array: np.ndarray, quality: int = 92) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="JPEG", quality=quality)
    return buffer.getvalue()


def selfie_of(image_path: str, doc_id: str, seed: int, boxes: pd.DataFrame) -> bytes:
    with Image.open(config.PROJECT_ROOT / image_path) as image:
        page = np.asarray(image.convert("RGB"))
    crop = face.crop_with_margin(page, boxes.loc[doc_id, ["x", "y", "w", "h"]].to_numpy())
    return jpeg_bytes(face.simulate_selfie(crop, np.random.default_rng(seed))[0])


def login(client: httpx.Client, email: str, password: str) -> dict:
    r = client.post("/auth/login", data={"username": email, "password": password})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def follow(application_id: str, headers: dict, started: float, out: dict) -> None:
    """Read the SSE stream until a final status; record every status with its time since submission."""
    timeline = []
    with httpx.stream("GET", f"{API}/applications/{application_id}/events", headers=headers, timeout=600) as r:
        for line in r.iter_lines():
            if line.startswith("data: "):
                view = json.loads(line[6:])
                timeline.append((round(time.perf_counter() - started, 1), view["status"], view["outcome"]))
                if view["status"] in FINAL:
                    break
    out[application_id] = timeline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="reports/phase7/e2e_api_results.json", help="where to save the results")
    results_path = config.PROJECT_ROOT / parser.parse_args().results
    client = httpx.Client(base_url=API, timeout=60)
    for _ in range(60):  # wait for the API
        try:
            if client.get("/health").json()["status"] == "ok":
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    print("health:", client.get("/health").json())
    customer = login(client, ENV["DEMO_CUSTOMER_EMAIL"], ENV["DEMO_CUSTOMER_PASSWORD"])
    officer = login(client, ENV["DEMO_OFFICER_EMAIL"], ENV["DEMO_OFFICER_PASSWORD"])

    # ---- the documents (test split; a functional test, not an evaluation)
    fields = data.parse_ground_truth()  # annotated values and boxes of the genuine templates
    boxes = fields.query("field_name == 'photo'").set_index("doc_id")
    truth = schemas.ground_truth_table(fields)
    genuine = data.template_record(doc_id=GENUINE)
    forged = data.template_record(fake_name=FORGED)
    stranger = data.template_record(doc_id=STRANGER)
    if not data.check_test_split([genuine.doc_id, forged.doc_id, stranger.doc_id]):
        print("note: no manifest, test-split check skipped (the documents are fixed above)")
    g = truth.loc[genuine.doc_id]
    f = truth.loc[forged.doc_id]  # what the fraudster types: the original holder's data
    # typed in lower case, without diacritics and in a different order: the fuzzy name match must still accept it
    genuine_name = " ".join(schemas.strip_diacritics(f"{g.surname} {g.given_names}").lower().split())
    genuine_dob = schemas.parse_date(g.birth_date, "birth_date")
    wrong_dob = (date.fromisoformat(genuine_dob) + timedelta(days=400)).isoformat()
    genuine_doc = (config.PROJECT_ROOT / genuine.image_path).read_bytes()
    genuine_selfie = selfie_of(genuine.image_path, genuine.doc_id, seed=1, boxes=boxes)
    cases = [
        ("1 genuine + own selfie", genuine_doc, genuine_selfie, genuine_name, genuine_dob, "AUTO_APPROVED"),
        ("2 forged + stranger", (config.PROJECT_ROOT / forged.image_path).read_bytes(),
         selfie_of(stranger.image_path, stranger.doc_id, seed=2, boxes=boxes), f"{f.given_names} {f.surname}",
         schemas.parse_date(f.birth_date, "birth_date"), "MANUAL_REVIEW"),
        ("3 blank image", jpeg_bytes(np.full((630, 1000, 3), 4, np.uint8)), genuine_selfie, genuine_name, genuine_dob,
         "RESUBMIT_REQUIRED"),
        ("4 genuine, wrong DOB", genuine_doc, genuine_selfie, genuine_name, wrong_dob, "MANUAL_REVIEW"),
    ]

    # ---- submit all four, then follow them in parallel
    submitted, timelines, threads = [], {}, []
    for name, doc, selfie, full_name, dob, expected in cases:
        started = time.perf_counter()
        r = client.post("/applications", headers=customer, data={"full_name": full_name, "date_of_birth": dob},
                        files={"id_image": ("id.jpg", doc, "image/jpeg"), "selfie": ("selfie.jpg", selfie, "image/jpeg")})
        assert r.status_code == 202, r.text
        app_id = r.json()["application_id"]
        submitted.append((name, app_id, expected, started))
        thread = threading.Thread(target=follow, args=(app_id, customer, started, timelines))
        thread.start()
        threads.append(thread)
        print(f"submitted {name}: {app_id} ({r.elapsed.total_seconds() * 1000:.0f} ms)")
    for thread in threads:
        thread.join(timeout=600)

    rows = []
    for name, app_id, expected, _ in submitted:
        detail = client.get(f"/officer/cases/{app_id}", headers=officer).json()
        d = detail["decision"] or {}
        timeline = timelines.get(app_id, [])
        status = detail["application"]["status"]
        rows.append({"case": name, "application_id": app_id, "outcome": d.get("outcome"), "status": status,
                     "risk": d.get("risk_level"), "score": d.get("risk_score"), "expected": expected,
                     "ok": d.get("outcome") == expected and status == EXPECTED_STATUS[expected],
                     "seconds to decision": timeline[-1][0] if timeline else None,
                     "statuses seen (SSE)": " > ".join(s for _, s, _ in timeline),
                     "reasons": [f"[{r['effect']}] {r['code']}" for r in d.get("reasons", [])],
                     "latency per check ms": {k: c.get("latency_ms") for k, c in detail["checks"].items()}})
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 120)
    table = pd.DataFrame(rows)
    print("\n" + table[["case", "outcome", "status", "risk", "score", "expected", "ok", "seconds to decision",
                        "statuses seen (SSE)"]]
          .to_string(index=False))
    for row in rows:
        print(f"\n{row['case']}: {row['reasons']}\n   worker latency (ms): {row['latency per check ms']}")

    # ---- officer: queue, case, rejection, audit trail
    ours = {app_id for _, app_id, _, _ in submitted}
    queue = [c for c in client.get("/officer/cases", params={"status": "DECIDED"}, headers=officer).json()
             if c["application_id"] in ours]
    print("\nofficer queue (this run, highest risk first):")
    for c in queue:
        print(f"   {c['application_id']}  {c['outcome']:<17} risk {c['risk_level']!s:<6} score {c['risk_score']}  {c['reason_codes']}")
    forged_id = submitted[1][1]
    detail = client.get(f"/officer/cases/{forged_id}", headers=officer).json()
    image = httpx.get(detail["images"]["document_url"], timeout=10)
    print(f"\ncase {forged_id}: top forgery tile {detail['forgery_top_tile']}; presigned document URL -> HTTP "
          f"{image.status_code}, {len(image.content)} bytes; summary: {detail['summary'][:160]}...")
    reject = client.post(f"/officer/cases/{forged_id}/decision", headers=officer,
                         json={"action": "reject", "reason": "Forgery suspected and the selfie does not match the portrait."})
    print(f"reject -> HTTP {reject.status_code}, status {reject.json().get('status')}")
    print("audit trail:")
    for entry in reject.json()["audit_trail"]:
        print(f"   {entry['at']}  {entry['from_status']!s:<10} -> {entry['to_status']:<10} {entry['actor']:<26} {entry['reason']}")

    # ---- security checks
    db = store.connect()
    other = store.upsert_user(db, "second-customer@demo.ekyc", security.hash_password("second-pass-123"), "CUSTOMER")
    other_headers = login(client, "second-customer@demo.ekyc", "second-pass-123")
    expired = security.create_token(other["user_id"], "CUSTOMER", ENV["JWT_SECRET"], minutes=1,
                                    now=datetime.now(timezone.utc) - timedelta(hours=2))
    first = submitted[0][1]
    security_checks = {
        "customer -> GET /officer/cases (403)": client.get("/officer/cases", headers=customer).status_code,
        "customer -> POST officer decision (403)": client.post(f"/officer/cases/{first}/decision", headers=customer,
                                                               json={"action": "approve", "reason": "trying it"}).status_code,
        "another customer -> GET this application (404)": client.get(f"/applications/{first}", headers=other_headers).status_code,
        "no token (401)": client.get(f"/applications/{first}").status_code,
        "invalid token (401)": client.get(f"/applications/{first}", headers={"Authorization": "Bearer not-a-token"}).status_code,
        "expired token (401)": client.get("/applications", headers={"Authorization": f"Bearer {expired}"}).status_code,
    }
    print("\nsecurity checks:")
    expected_codes = [403, 403, 404, 401, 401, 401]
    for (name, code), want in zip(security_checks.items(), expected_codes):
        print(f"   {'PASS' if code == want else 'FAIL'}  {name}: HTTP {code}")

    passed = all(r["ok"] for r in rows) and [c["application_id"] for c in queue][0] == forged_id \
        and reject.status_code == 200 and [c for c in security_checks.values()] == expected_codes
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps({"cases": rows, "queue": queue, "security": security_checks,
                                   "audit_trail": reject.json()["audit_trail"], "passed": passed}, indent=2, default=str))
    print(f"\n{'ALL PASSED' if passed else 'SOMETHING FAILED'}  -> {results_path.relative_to(config.PROJECT_ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
