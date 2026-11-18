# Phase 9 simulated batch

150 applications through the real pipeline (TEST-split synthetic templates); the ground truth is in `data/processed/batch/ground_truth.csv` (local).

## System outcome mix

| outcome | applications | share |
|---|---:|---:|
| MANUAL_REVIEW | 94 | 63% |
| AUTO_APPROVED | 49 | 33% |
| RESUBMIT_REQUIRED | 7 | 5% |

## Final status

| status | applications |
|---|---:|
| APPROVED | 59 |
| REJECTED | 56 |
| DECIDED | 28 |
| RESUBMIT_REQUESTED | 7 |

## System decision vs ground truth

| | AUTO_APPROVED | MANUAL_REVIEW | RESUBMIT_REQUIRED | total |
|---|---:|---:|---:|---:|
| fraud_or_mismatch | 1 | 67 | 0 | 68 |
| legitimate | 48 | 27 | 0 | 75 |
| unusable | 0 | 0 | 7 | 7 |
| total | 49 | 94 | 7 | 150 |

## Outcome per scenario

| | AUTO_APPROVED | MANUAL_REVIEW | RESUBMIT_REQUIRED | total |
|---|---:|---:|---:|---:|
| forged_own_selfie | 0 | 38 | 0 | 38 |
| forged_stranger | 0 | 7 | 0 | 7 |
| genuine | 48 | 27 | 0 | 75 |
| genuine_wrong_details | 0 | 12 | 0 | 12 |
| stranger_selfie | 1 | 10 | 0 | 11 |
| unreadable | 0 | 0 | 7 | 7 |
| total | 49 | 94 | 7 | 150 |

## Key numbers

- **applications:** 150
- **fraud_caught (not auto-approved):** 67/68
- **fraud_missed (auto-approved):** 1
- **legitimate_auto_approved:** 48/75
- **false_alarms (legitimate -> manual review):** 27
- **legitimate_asked_to_resubmit:** 0
- **officer_decided:** 66
- **officer_rejected:** 56
- **still_awaiting_officer:** 28
