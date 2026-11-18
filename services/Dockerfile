# syntax=docker/dockerfile:1
# Images of the Python services (Phase 9): ONE shared multi-stage Dockerfile, built from the repository root:
#   docker compose --profile app build                   (builds every target below)
#   docker build -f services/Dockerfile --target api .   (one target by hand)
#
# Why one file with targets instead of a Dockerfile per service:
# - All six services run the same code base (src/ekyc) and differ only in their command and their libraries.
# - Two dependency sets cover them: "light" (API, orchestrator: web, Kafka, MongoDB, S3 clients, numpy, pandas;
#   no TensorFlow) and "ml" (the four workers: light + TensorFlow 2.18.1 CPU + OpenCV).
# - The four workers share ONE image: its ~1 GB TensorFlow layer is stored once, and docker-compose picks the
#   worker with the container command.
# - The API and the orchestrator are two small targets on top of the same light layers: only the command and the
#   healthcheck differ.
# - Packages go into a virtual environment in a builder stage (deps-*). The runtime stages copy only that folder,
#   so pip, its cache and any build leftovers stay out of the final images.
# - Base: python:3.11.18-slim-trixie (Debian 13 slim, the same Python as the Mac venv). Every package has a
#   manylinux wheel for both x86_64 and aarch64, so no compiler is needed.
# - Runs as the non-root user "ekyc" (uid 10001).
# - The code is NOT pip-installed: PYTHONPATH=/app/src, so ekyc.config.PROJECT_ROOT is /app.
# - Models are NOT baked in: docker-compose mounts ./models read-only at /app/models.

ARG PYTHON_IMAGE=python:3.11.18-slim-trixie

# ---------------------------------------------------------------- shared base
FROM ${PYTHON_IMAGE} AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app/src
RUN groupadd --gid 10001 ekyc && useradd --uid 10001 --gid ekyc --create-home --shell /usr/sbin/nologin ekyc
WORKDIR /app

# ---------------------------------------------------------------- dependency builders (not shipped themselves)
FROM base AS deps-light
RUN python -m venv /opt/venv
# requirements.txt = the frozen Mac environment, used as CONSTRAINTS: every package gets the Mac's exact version;
# its macOS-only packages (tensorflow-metal, appnope) carry sys_platform markers and are skipped here
COPY requirements.txt requirements-api.txt ./
RUN pip install -r requirements-api.txt -c requirements.txt

FROM deps-light AS deps-ml
COPY requirements-worker.txt ./
RUN pip install -r requirements-worker.txt -c requirements.txt

# ---------------------------------------------------------------- light runtime: API + orchestrator
FROM base AS light
COPY --from=deps-light /opt/venv /opt/venv
COPY src/ src/
COPY services/ services/
USER ekyc

FROM light AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status != 200)"]
CMD ["uvicorn", "app:app", "--app-dir", "services/api", "--host", "0.0.0.0", "--port", "8000"]

FROM light AS orchestrator
ENV EKYC_HEARTBEAT_FILE=/tmp/heartbeat
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-m", "ekyc.messaging.health", "300"]
CMD ["python", "services/orchestrator/main.py"]

# ---------------------------------------------------------------- ml runtime: the four inference workers
FROM base AS worker
COPY --from=deps-ml /opt/venv /opt/venv
COPY src/ src/
COPY services/ services/
# TensorFlow on the CPU (no GPU in Docker on macOS); quieter TensorFlow start-up logs
ENV EKYC_TF_DEVICE=cpu \
    TF_CPP_MIN_LOG_LEVEL=2 \
    EKYC_HEARTBEAT_FILE=/tmp/heartbeat
USER ekyc
# the heartbeat is written by the consume loop; workers need ~30-60 s to load their models first
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD ["python", "-m", "ekyc.messaging.health", "300"]
CMD ["python", "services/doc-worker/main.py"]
