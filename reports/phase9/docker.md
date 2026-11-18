# Phase 9: Docker packaging, measured (18 Nov 2026)

Machine: MacBook (Apple M5, 16 GB RAM), Docker Desktop with a **4 GB VM** (3.83 GiB usable), images built for
linux/arm64. Ollama ran on the host, as always.

## Images

| Image | Target | `docker image ls` | Inside | Notes |
|---|---|---:|---|---|
| `ekyc-worker:0.9.0` | `worker` | 2.42 GB | base 156 MB + venv 1.7 GB (TensorFlow 1.1 GB) | one image for all 4 workers |
| `ekyc-api:0.9.0` | `api` | 602 MB | base 156 MB + venv 285 MB (pandas 88 MB, numpy 63 MB, botocore 31 MB) | no TensorFlow, no OpenCV |
| `ekyc-orchestrator:0.9.0` | `orchestrator` | 602 MB | same layers as the API image | only the command and the healthcheck differ |
| `ekyc-frontend:0.9.0` | (frontend/Dockerfile) | 83 MB | nginx-unprivileged + the built app | |

- **`docker image ls` sizes** on Docker Desktop's containerd store are the disk usage, compressed layers included.
  The "Inside" column is `du` within a container.
- **Python versions:**
  - TensorFlow 2.18.1 (aarch64 CPU wheel), Keras 3.15.1, OpenCV 5.0.0 headless, numpy 2.0.2;
  - no tensorflow-metal;
  - checked with `import` inside the image; every package has the Mac's exact version (`-c requirements.txt`).
- **Users:** all images run as non-root: `ekyc` (uid 10001) for Python, `nginx` (uid 101) for the frontend.
- **Build:** 4 min from scratch (BuildKit, layers cached afterwards).
- **Build context:** 323 kB for the Python images (46 files) and 485 kB for the frontend. data/, .venv,
  models, reports and node_modules are excluded.

## Memory (`docker stats`, sampled every ~2 s)

| Container | Idle (MiB) | Peak during the smoke test (MiB) | Limit (Phase 9) |
|---|---:|---:|---:|
| kafka | 297 | 380 | 1 GiB |
| kafka-ui | 236 | 259 | 512 MiB |
| mongo | 231 | **766** | 768 MiB → **1 GiB** |
| s3 (RustFS) | 57 | 124 | 512 MiB |
| api | 85 | 80 | 384 MiB |
| orchestrator | 50 | 48 | 256 MiB |
| doc-worker | 309 | 344 | 1 GiB |
| forgery-worker | 505 | 751 sampled; **1,333 at the OOM kill** (kernel log) | 1.5 GiB → **2 GiB** |
| face-worker | 308 | 634 | 768 MiB → **1 GiB** |
| extraction-worker | 247 | 231 | 512 MiB |
| frontend | 11 | 12 | 64 MiB |
| **total** | **~2.3 GB** | **~3.3 GB** (2.67 GB highest sampled total + the forgery spike) | |

**Verdict: Docker's 4 GB VM is too small for the full stack.**
- **What happened:** during the smoke test the VM kernel ran out of memory. It was a *global* OOM, not a
  container limit, and the kernel killed the forgery worker while it scored a page (1.33 GB resident). The worker
  restarted by itself (`restart: unless-stopped`).
- **The MongoDB limit:** separately, MongoDB's own 768 MiB limit killed its `mongosh` healthcheck.
- **The VM's own needs:** besides the containers, it needs memory for its kernel, containerd and the page cache.
- **Recommendation: give Docker Desktop 6 GB** (Settings → Resources → Memory): ~3.3 GB of containers at peak
  plus ~1 GB VM overhead plus headroom.
- **The trade-off on a 16 GB Mac:** 6 GB for Docker plus 6-8 GB for Ollama leaves little for macOS. The host was
  already swapping 12-13 GB during these runs.
- **The lightweight host mode stays the practical choice** on this laptop: `docker compose up -d` for the infra
  only, plus `scripts/run_all.sh`.

## Containerized end-to-end smoke test (`scripts/e2e_api_smoke.py`, once)

Results: `reports/phase9/e2e_api_containers.json`.

| Case | Expected | Got | Why |
|---|---|---|---|
| 1 genuine + own selfie | AUTO_APPROVED → APPROVED | MANUAL_REVIEW (medium) | `extraction_timed_out`: no result within 180 s |
| 2 forged + stranger | MANUAL_REVIEW high | MANUAL_REVIEW high ✓ | face mismatch (0.21); forgery and extraction also timed out |
| 3 blank image | RESUBMIT_REQUIRED → RESUBMIT_REQUESTED | ✓ in 2.4 s | decided early |
| 4 genuine, wrong DOB | MANUAL_REVIEW | MANUAL_REVIEW (medium) ✓ | but via timeouts, not via `dob_mismatch` |

**Passed:**
- **Security:** all 6 checks (403 for the wrong role ×2, 404 for another customer's application, 401 for no,
  invalid or expired token ×3).
- **Officer:** the queue (highest risk first), the rejection with a reason, and the audit trail
  `SUBMITTED → PROCESSING → DECIDED → REJECTED`.
- **Presigned links:** the document URL opened from the host (HTTP 200). This confirms `S3_PUBLIC_ENDPOINT`: the
  API signs links for `localhost:9000` while it talks to `s3:9000` itself.
- **Ollama:** reachable from the containers at `host.docker.internal:11434` (two extractions completed: 164 s and
  63 s).
- **Healthchecks:** every app container reached *healthy* within ~20 s of start.
- **Frontend:** served at http://localhost:3000. Client-side routes fall back to `index.html`. `/config.js`
  carries the API address, and CORS allows `http://localhost:3000`.

**Failed: case 1 expected AUTO_APPROVED** and got MANUAL_REVIEW, because of memory, not logic:
1. The memory pressure stalled the Kafka broker for ~60 s ("Timed out ProduceRequest in flight", "Waiting for
   coordinator"), the same stall as Phase 6.
2. The OOM kill restarted the forgery worker, whose Python start-up then took ~7 minutes under swap.
3. The orchestrator's timeout sweeper therefore marked the missing checks `timed_out`.
4. That routes a case to manual review: the designed safe fallback. **No case was wrongly approved.**

The same four cases passed in host mode in Phase 7 (`reports/phase7/e2e_api_results.json`). The Phase 9 lifecycle
in host mode is covered by the Playwright run (4/4).
