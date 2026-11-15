"""Smoke test for the local "private mode" extraction path: one ID image -> Ollama vision model -> JSON.

Runs the model twice:
  1. cold run on IMAGE         (includes loading the model into memory)
  2. warm run on WARM_IMAGE    (model already loaded = the latency a user would see in steady state)
The warm run deliberately uses a DIFFERENT image: Ollama caches the processed prompt, so repeating
the same image would skip the expensive image-encoding step and give an unrealistically fast time.
Reports timings, peak memory of the Ollama model process, and the extracted fields.

Usage:  .venv/bin/python scripts/ollama_vision_smoke_test.py [model] [image_path] [warm_image_path]
"""

import base64
import json
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OLLAMA_URL = "http://localhost:11434"
MODEL = sys.argv[1] if len(sys.argv) > 1 else "qwen2.5vl:7b"
REALS = PROJECT_ROOT / "data/interim/templates/Images/reals"
IMAGE = Path(sys.argv[2]) if len(sys.argv) > 2 else REALS / "alb_id_00.jpg"
WARM_IMAGE = Path(sys.argv[3]) if len(sys.argv) > 3 else REALS / "alb_id_01.jpg"

# Key names follow the field_name vocabulary of the SIDTD template annotations, so the output can
# later be scored field-by-field against ground truth (Phase 5).
FIELDS = [
    "document_type", "issuing_country", "surname", "name", "birth_date", "birth_place", "gender",
    "nationality", "id_number", "document_number", "issue_date", "expiry_date", "authority",
]
PROMPT = (
    "You are reading a photo of an identity document. Extract the printed fields and answer with "
    "ONLY a JSON object using exactly these keys: " + ", ".join(FIELDS) + ". "
    "Copy each value exactly as printed on the document (keep the original date format). "
    "Use null for any field that is not on the document."
)


def ollama_post(endpoint: str, payload: dict) -> dict:
    request = urllib.request.Request(
        OLLAMA_URL + endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read())


def runner_pids() -> list[int]:
    """PIDs of Ollama's model-runner processes (each loaded model runs in its own child process).

    Ollama 0.34 names this process `llama-server`; older versions used `ollama runner`.
    """
    out = subprocess.run(["pgrep", "-f", "llama-server|ollama runner"], capture_output=True, text=True).stdout
    return [int(pid) for pid in out.split()]


def peak_footprint_mb(pid: int) -> float | None:
    """Kernel-tracked peak physical memory of a process (includes Metal/GPU buffers in unified memory)."""
    out = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True).stdout
    match = re.search(r"phys_footprint_peak:\s*([\d.]+)\s*(KB|MB|GB)", out)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2)
    return value * {"KB": 1 / 1024, "MB": 1, "GB": 1024}[unit]


class RssSampler(threading.Thread):
    """Polls the resident memory (RSS) of the runner process(es) every 0.25 s and keeps the peak."""

    def __init__(self):
        super().__init__(daemon=True)
        self.peak_rss_mb, self.pids, self.stop = 0.0, set(), threading.Event()

    def run(self):
        while not self.stop.is_set():
            for pid in runner_pids():
                self.pids.add(pid)
                rss_kb = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout
                if rss_kb.strip():
                    self.peak_rss_mb = max(self.peak_rss_mb, int(rss_kb) / 1024)
            time.sleep(0.25)


def generate(image: Path) -> tuple[dict, float]:
    image_b64 = base64.b64encode(image.read_bytes()).decode()  # read-only access to the source image
    payload = {
        "model": MODEL,
        "prompt": PROMPT,
        "images": [image_b64],
        "format": "json",  # constrain decoding to valid JSON
        "stream": False,
        "keep_alive": "5m",
        "options": {"temperature": 0, "seed": 42},
    }
    start = time.perf_counter()
    response = ollama_post("/api/generate", payload)
    return response, time.perf_counter() - start


def describe_timings(r: dict, wall_s: float) -> str:
    ns = 1e9
    return (
        f"wall {wall_s:.1f}s | load {r.get('load_duration', 0) / ns:.1f}s | "
        f"prompt (image+text) {r.get('prompt_eval_count', 0)} tokens in {r.get('prompt_eval_duration', 0) / ns:.1f}s | "
        f"output {r.get('eval_count', 0)} tokens in {r.get('eval_duration', 0) / ns:.1f}s "
        f"({r.get('eval_count', 0) / max(r.get('eval_duration', 1) / ns, 1e-9):.1f} tok/s)"
    )


def print_output(label: str, r: dict) -> None:
    print(f"\n{label} output:")
    try:
        print(json.dumps(json.loads(r["response"]), indent=2, ensure_ascii=False))
        print("-> valid JSON")
    except json.JSONDecodeError:
        print("INVALID JSON:\n" + r["response"])


def main() -> None:
    # Unload anything already in memory so the cold run really includes loading the model.
    ollama_post("/api/generate", {"model": MODEL, "keep_alive": 0})
    time.sleep(2)
    print(f"Model: {MODEL}")
    for label, path in (("Cold image", IMAGE), ("Warm image", WARM_IMAGE)):
        print(f"{label}: {path.relative_to(PROJECT_ROOT)} ({path.stat().st_size / 1e6:.1f} MB)")

    sampler = RssSampler()
    sampler.start()
    cold, cold_s = generate(IMAGE)
    warm, warm_s = generate(WARM_IMAGE)
    sampler.stop.set()
    sampler.join()

    print("\nCold run:", describe_timings(cold, cold_s))
    print("Warm run:", describe_timings(warm, warm_s))
    print("\n`ollama ps` while loaded:\n" + subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout)
    for pid in sorted(sampler.pids):
        print(f"Runner PID {pid}: peak physical footprint {peak_footprint_mb(pid) or float('nan'):.0f} MB "
              f"(peak sampled RSS {sampler.peak_rss_mb:.0f} MB)")

    print_output(f"Cold run ({IMAGE.name})", cold)
    print_output(f"Warm run ({WARM_IMAGE.name})", warm)

    # Unload the model so it does not keep ~6+ GB of the 16 GB RAM busy.
    ollama_post("/api/generate", {"model": MODEL, "keep_alive": 0})
    print("\nModel unloaded.")


if __name__ == "__main__":
    main()
#  tested-phase1