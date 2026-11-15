"""Phase 1 environment check: TensorFlow + Metal GPU, matmul speed, and LFW loading.

Run from anywhere:  .venv/bin/python scripts/verify_env.py
"""

import os
import time
from pathlib import Path

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")  # hide TF's verbose C++ info logs

import keras
import tensorflow as tf
from sklearn.datasets import fetch_lfw_pairs

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# sklearn caches the decoded LFW arrays (joblib) inside data_home and keys that cache on the
# exact path string. We pass the same ABSOLUTE path that was used when the data was downloaded,
# so this is a pure cache read. A relative path would miss the cache and write a new copy into
# data/raw, which we never modify.
LFW_HOME = str(PROJECT_ROOT / "data" / "raw" / "lfw")

MATMUL_SIZE = 4096


def time_matmul(device: str, repeats: int) -> float:
    """Return the average seconds for one MATMUL_SIZE x MATMUL_SIZE float32 matmul on `device`."""
    with tf.device(device):
        a = tf.random.normal((MATMUL_SIZE, MATMUL_SIZE))
        b = tf.random.normal((MATMUL_SIZE, MATMUL_SIZE))
        # Warm-up: the first call includes one-off kernel compilation / memory allocation.
        tf.reduce_sum(tf.matmul(a, b)).numpy()
        start = time.perf_counter()
        for _ in range(repeats):
            # .numpy() forces the (asynchronous) GPU work to finish before we stop the clock.
            tf.reduce_sum(tf.matmul(a, b)).numpy()
        return (time.perf_counter() - start) / repeats


def main() -> None:
    print(f"TensorFlow {tf.__version__} | Keras {keras.__version__}")
    gpus = tf.config.list_physical_devices("GPU")
    print("GPU devices:", gpus)

    # One matmul of two n x n matrices costs about 2 * n^3 floating-point operations.
    flops = 2 * MATMUL_SIZE**3
    cpu_s = time_matmul("/CPU:0", repeats=5)
    print(f"CPU: {cpu_s * 1000:8.1f} ms per matmul  ({flops / cpu_s / 1e9:7.0f} GFLOP/s)")
    if gpus:
        gpu_s = time_matmul("/GPU:0", repeats=20)
        print(f"GPU: {gpu_s * 1000:8.1f} ms per matmul  ({flops / gpu_s / 1e9:7.0f} GFLOP/s)")
        print(f"GPU speed-up: {cpu_s / gpu_s:.1f}x")

    for subset in ("train", "test"):
        start = time.perf_counter()
        lfw = fetch_lfw_pairs(
            subset=subset, data_home=LFW_HOME, color=True, resize=1.0, download_if_missing=False
        )
        n_same = int(lfw.target.sum())
        print(
            f"LFW {subset}: pairs {lfw.pairs.shape}, dtype {lfw.pairs.dtype}, "
            f"same-person {n_same} / different {len(lfw.target) - n_same}, "
            f"loaded in {time.perf_counter() - start:.1f}s"
        )


if __name__ == "__main__":
    main()
