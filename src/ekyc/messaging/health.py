"""Liveness for the Kafka loops (Phase 9, used by the Docker healthchecks).

A worker or the orchestrator calls beat() on every pass of its consume loop (at least once a second while idle).
That touches a file, if EKYC_HEARTBEAT_FILE is set (the containers set it; host processes do not). The container's
healthcheck runs

    python -m ekyc.messaging.health 300

which exits 1 ("unhealthy") when the file is older than 300 s or missing. A stuck loop (e.g. a hung broker call)
stops beating and is reported. The limit must exceed the longest legitimate message: the extraction worker's
Ollama call may take up to 180 s per attempt, 3 attempts, so its container uses 900 s (docker-compose.yml).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ENV = "EKYC_HEARTBEAT_FILE"
_last = 0.0


def beat(min_interval_s: float = 1.0) -> None:
    """Touch the heartbeat file (at most once per min_interval_s); does nothing when EKYC_HEARTBEAT_FILE is unset."""
    global _last
    path = os.environ.get(ENV)
    if not path or time.monotonic() - _last < min_interval_s:
        return
    Path(path).touch()
    _last = time.monotonic()


def is_alive(path: str | None, max_age_s: float) -> bool:
    try:
        return time.time() - os.path.getmtime(path) <= max_age_s
    except (OSError, TypeError):
        return False


if __name__ == "__main__":
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
    sys.exit(0 if is_alive(os.environ.get(ENV), limit) else 1)
