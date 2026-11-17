#!/usr/bin/env bash
# Start the four inference workers as host processes (Phase 6). Logs: logs/workers/<name>.log.
# Needs: docker compose up -d (Kafka, S3) and, for extraction, `ollama serve` on the host.
# Ctrl+C (or SIGTERM) stops all four: each finishes its current message first.
#   usage: scripts/run_workers.sh [doc forgery face extraction]   (default: all four)
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs/workers
workers=("${@:-doc forgery face extraction}")
read -r -a workers <<< "${workers[*]}"
pids=()
for w in "${workers[@]}"; do
  .venv/bin/python "services/$w-worker/main.py" >> "logs/workers/$w-worker.log" 2>&1 &
  pids+=("$!")
  echo "started $w-worker (pid $!) -> logs/workers/$w-worker.log"
done
trap 'echo "stopping: ${pids[*]}"; kill -TERM "${pids[@]}" 2>/dev/null || true; wait' INT TERM
wait
