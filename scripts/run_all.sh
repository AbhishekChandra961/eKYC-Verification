#!/usr/bin/env bash
# Start the whole eKYC system on this Mac: orchestrator, API (http://localhost:8000/docs), the four inference workers
# and the React frontend (http://localhost:5173). Every service runs as a host process; logs go to
# logs/services/<name>.log. Ctrl+C (or SIGTERM) stops them all; each one finishes its current message first.
#
# Needs (checked below): the Docker infrastructure (docker compose up -d), Ollama (ollama serve) for extraction,
# and the frontend packages (cd frontend && npm install). EKYC_NO_FRONTEND=1 starts only the backend.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs/services

# ---- prerequisites
problems=0
running=$(docker compose ps --status running --services 2>/dev/null || true)
for service in kafka mongo s3; do
  if ! grep -qx "$service" <<<"$running"; then
    echo "!! Docker service '$service' is not running: docker compose up -d"; problems=1
  fi
done
if ! curl -s --max-time 2 -o /dev/null http://localhost:11434/api/tags; then
  echo "!! Ollama is not reachable on :11434 (needed by the extraction worker): ollama serve"; problems=1
fi
if [[ "${EKYC_NO_FRONTEND:-0}" != "1" && ! -d frontend/node_modules ]]; then
  echo "!! frontend packages missing: (cd frontend && npm install)"; problems=1
fi
if [[ $problems -ne 0 ]]; then echo "Fix the problems above and run again."; exit 1; fi

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
if [[ "${EKYC_NO_FRONTEND:-0}" != "1" ]]; then
  start frontend npm --prefix frontend run dev -- --host localhost
fi

cat <<'EOF'

  SecureBank eKYC is starting (the workers need ~30 s to load their models).
    Frontend      http://localhost:5173       log in with DEMO_CUSTOMER_* or DEMO_OFFICER_* from .env
    API docs      http://localhost:8000/docs
    Kafka UI      http://localhost:8080
  Demo files:     .venv/bin/python scripts/make_demo_samples.py   (then see demo_samples/README.md)
  Tests:          .venv/bin/python scripts/e2e_api_smoke.py   |   cd frontend && npm run e2e
  Stop:           Ctrl+C

EOF
trap 'echo "stopping: ${pids[*]}"; kill -TERM "${pids[@]}" 2>/dev/null || true; wait' INT TERM
wait
