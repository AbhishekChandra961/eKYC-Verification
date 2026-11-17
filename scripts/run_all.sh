#!/usr/bin/env bash
# Start every eKYC service as a host process (Phase 7): orchestrator, API (http://localhost:8000, docs at /docs) and
# the four inference workers. Logs: logs/services/<name>.log. Ctrl+C (or SIGTERM) stops them all; each one finishes
# its current message first.
# Needs: docker compose up -d (Kafka, MongoDB, S3) and `ollama serve` (extraction-worker).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs/services
pids=()
start() {  # start <name> <command...>
  local name=$1; shift
  "$@" >> "logs/services/$name.log" 2>&1 &
  pids+=("$!")
  echo "started $name (pid $!) -> logs/services/$name.log"
}
start orchestrator .venv/bin/python services/orchestrator/main.py
start api .venv/bin/uvicorn app:app --app-dir services/api --host 127.0.0.1 --port 8000
for w in doc forgery face extraction; do
  start "$w-worker" .venv/bin/python "services/$w-worker/main.py"
done
trap 'echo "stopping: ${pids[*]}"; kill -TERM "${pids[@]}" 2>/dev/null || true; wait' INT TERM
wait
