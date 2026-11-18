"""Phase 9 lifecycle migration: close the applications that the Phase 7/8 lifecycle left in DECIDED.

Before Phase 9 every decided application stayed in DECIDED, even when nobody had to act on it. Now:
    AUTO_APPROVED     -> APPROVED            (closed by the system)
    RESUBMIT_REQUIRED -> RESUBMIT_REQUESTED  (closed; the customer starts a new application)
    MANUAL_REVIEW     -> stays DECIDED       (waits for an officer)

Each moved application gets an audit entry (actor "system:migration"), so the trail shows that the migration, not
the orchestrator or an officer, closed it. Safe to run again: it only touches DECIDED applications with one of the
two outcomes, with an atomic conditional update.

    .venv/bin/python scripts/migrate_lifecycle.py --dry-run     # only count
    .venv/bin/python scripts/migrate_lifecycle.py               # migrate
"""

import argparse

from ekyc import store

ACTOR = "system:migration"
MOVES = {"AUTO_APPROVED": ("APPROVED", "Phase 9 lifecycle: an auto-approved application is closed as APPROVED"),
         "RESUBMIT_REQUIRED": ("RESUBMIT_REQUESTED",
                               "Phase 9 lifecycle: a resubmission request is closed as RESUBMIT_REQUESTED")}


def migrate(db, dry_run: bool = False) -> dict[str, int]:
    counts = {}
    for outcome, (to_status, reason) in MOVES.items():
        query = {"status": "DECIDED", "decision.outcome": outcome}
        ids = [a["application_id"] for a in db.applications.find(query, projection={"application_id": True})]
        moved = 0
        for application_id in ([] if dry_run else ids):
            # the same conditional update as store.move, but from DECIDED, which the new lifecycle no longer allows
            # for these outcomes (that is exactly what this migration repairs)
            updated = db.applications.find_one_and_update({"application_id": application_id, **query},
                                                          {"$set": {"status": to_status, "updated_at": store.now()}})
            if updated is not None:
                store.audit(db, application_id, ACTOR, "DECIDED", to_status, reason)
                moved += 1
        counts[f"{outcome} DECIDED -> {to_status}"] = len(ids) if dry_run else moved
    counts["MANUAL_REVIEW stays DECIDED"] = db.applications.count_documents(
        {"status": "DECIDED", "decision.outcome": "MANUAL_REVIEW"})
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="only count what would move")
    args = parser.parse_args()
    db = store.connect()
    print(f"{'would move' if args.dry_run else 'moved'} (database {db.name}):")
    for label, count in migrate(db, args.dry_run).items():
        print(f"  {label:<48} {count}")
    print("statuses now:", {s: db.applications.count_documents({"status": s}) for s in store.STATUSES})


if __name__ == "__main__":
    main()
