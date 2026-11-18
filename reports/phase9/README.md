# Phase 9 reports

| File | What |
|---|---|
| `batch_summary.md` / `.json` | The simulated batch of 150 applications: outcome mix, final statuses, system decision vs ground truth, outcome per scenario (written by `scripts/simulate_batch.py`) |
| `docker.md` | Docker images (sizes, contents), measured memory per container, the 4 GB VM verdict, and the containerized end-to-end smoke test |
| `e2e_api_containers.json` | Raw results of `scripts/e2e_api_smoke.py` against the containers (`passed: false`; see `docker.md` for why) |

The dashboard data is in `dashboard/data/` (see `dashboard/DATA_DICTIONARY.md`).
