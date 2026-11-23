"""Model inference on uploaded images (Phase 6): one class per check, shared by the workers in services/.
Each takes the uploaded file's BYTES and returns a plain dict of outputs (JSON-serialisable for kyc.results).
The preprocessing is exactly the one each model was trained with (tests compare against the training caches).

    DocClassifier().classify(image)          blank-image gate + document type (Phase 2.1, 3A)
    ForgeryScorer().score(image)             tile forgery model, page score, band, top tile (Phase 3B v3)
    FaceVerifier().verify(id_image, selfie)  YuNet + SFace, cosine score and band (Phase 4)
    FieldExtractor().extract(image, type)    vision LLM fields + consistency rules (Phase 5)
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from ekyc import config, consistency, data, extraction, face, liveness

MODEL_DIR = config.PROJECT_ROOT / "models"
log = logging.getLogger(__name__)


def tensorflow_device() -> str:
    """The TensorFlow workers run on the CPU by default (EKYC_TF_DEVICE=gpu to use Metal). Measured in Phase 6 for
    one page at a time, the M-series CPU is FASTER (doc 88 vs 236 ms, forgery 507 vs 604 ms, warm-up 2.2 vs 5.3 s:
    for small batches the GPU's launch overhead dominates), and the GPU and its memory stay free for Ollama.
    Must run before TensorFlow builds a model; returns the device actually used."""
    import os

    import tensorflow as tf

    if os.environ.get("EKYC_TF_DEVICE", "cpu").lower() == "cpu":
        try:
            tf.config.set_visible_devices([], "GPU")
            return "cpu"
        except RuntimeError:  # TensorFlow already initialised the GPU in this process (e.g. inside pytest)
            log.warning("TensorFlow already initialised its devices; staying on them")
    return "gpu" if tf.config.get_visible_devices("GPU") else "cpu"


def file_version(path: Path) -> str:
    """'name@sha256:<first 12 hex>': identifies exactly which model file produced a result."""
    return f"{path.name}@sha256:{hashlib.sha256(path.read_bytes()).hexdigest()[:12]}"


def _noise_jpeg(width: int = 1280, height: int = 806) -> bytes:
    """A random-noise JPEG for warming up a model (noise, so the blank-image gate does not stop it)."""
    buffer = io.BytesIO()
    Image.fromarray(np.random.default_rng(0).integers(0, 255, (height, width, 3), dtype=np.uint8)).save(buffer, "JPEG")
    return buffer.getvalue()


def _rgb(image_bytes: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(image_bytes)) as image:
        return np.asarray(image.convert("RGB"))


# ---------------------------------------------------------------- document type (+ blank-image gate)

class DocClassifier:
    """Blank/quality gate (the is_empty rule of Phase 2.1) and the document-type classifier (Phase 3A).
    Preprocessing = the 512 px cache step (RGB, longest side 512, JPEG q92), then resize_with_pad to 224."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        import keras  # TensorFlow is only imported by the workers that need it

        self.device = tensorflow_device()
        self.info = json.loads((model_dir / "doc_classifier.json").read_text())
        self.model = keras.models.load_model(model_dir / "doc_classifier.keras")
        self.version = file_version(model_dir / "doc_classifier.keras")
        self.classify(_noise_jpeg())  # warm-up: TensorFlow builds its graph on the first call (~5 s), not on a customer's

    def classify(self, image_bytes: bytes) -> dict:
        import tensorflow as tf

        with Image.open(io.BytesIO(image_bytes)) as image:
            small = data.resized_jpeg_bytes(image, config.RESIZE_LONGEST, config.JPEG_QUALITY)
        pixel_std, dark_share = data.blank_frame_stats(io.BytesIO(small))
        gate = {"blank": bool(data.is_blank(pixel_std, dark_share)), "pixel_std": round(pixel_std, 2),
                "dark_share": round(dark_share, 3)}
        if gate["blank"]:  # no document in the picture: do not classify, ask for a new photo
            return {**gate, "recognized": False, "doc_type": None, "confidence": None,
                    "reason": "blank or almost black image"}
        size = self.info["input_size"]
        x = tf.image.resize_with_pad(tf.io.decode_jpeg(small, channels=3), size, size)[tf.newaxis]
        probs = self.model(x, training=False).numpy()[0]
        order = np.argsort(probs)[::-1]
        confidence, threshold = float(probs[order[0]]), float(self.info["confidence_threshold"])
        predicted = self.info["class_names"][order[0]]
        recognized = confidence >= threshold
        return {**gate, "recognized": recognized, "doc_type": predicted if recognized else None,
                "predicted_type": predicted, "confidence": round(confidence, 4), "threshold": round(threshold, 4),
                "top3": [{"doc_type": self.info["class_names"][i], "probability": round(float(probs[i]), 4)}
                         for i in order[:3]],
                "reason": None if recognized else f"confidence below {threshold:.2f}: unrecognized document"}


# ---------------------------------------------------------------- forgery

def forgery_band(score: float, review: float, suspected: float) -> str:
    """Threshold policy (Phase 3B v3): >= suspected -> forgery_suspected, >= review -> needs_review, else pass."""
    if score >= suspected:
        return "forgery_suspected"
    return "needs_review" if score >= review else "pass"


class ForgeryScorer:
    """The accepted tile model. Preprocessing EXACTLY as models/forgery_detector.json: RGB, JPEG q75 at the
    original size, longest side 1280 px (Lanczos, enlarged if smaller), JPEG q75, decoded by TensorFlow; then
    every 224 px tile (stride 112) is scored and the page score is the highest tile."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        import keras

        self.device = tensorflow_device()
        self.info = json.loads((model_dir / "forgery_detector.json").read_text())
        self.model = keras.models.load_model(model_dir / "forgery_detector.keras")
        self.version = file_version(model_dir / "forgery_detector.keras")
        self.review = float(self.info["thresholds"]["recall_0.90"]["threshold"])  # 0.729
        self.suspected = float(self.info["thresholds"]["f1_optimal"]["threshold"])  # 0.857383 (exact)
        self.tile, self.stride = int(self.info["tile_size"]), int(self.info["stride"])
        self.score(_noise_jpeg())  # warm-up (see DocClassifier)

    def score(self, image_bytes: bytes) -> dict:
        import tensorflow as tf

        from ekyc import tiles

        with Image.open(io.BytesIO(image_bytes)) as image:
            original_size = image.size
            page_jpeg = data.resized_jpeg_bytes(image, config.HIRES_LONGEST, config.HIRES_QUALITY, enlarge=True,
                                                pre_quality=config.GENUINE_PRE_QUALITY)
        page = tf.io.decode_jpeg(page_jpeg, channels=3)  # the decoder used in training
        height, width = int(page.shape[0]), int(page.shape[1])
        xy = tiles.tile_grid(width, height, self.tile, self.stride)
        batch = tf.cast(tiles.crop_tiles(page, tf.constant(xy, tf.int32), self.tile), tf.float32)
        scores = self.model.predict(batch, batch_size=64, verbose=0)[:, 0]
        top = int(np.argmax(scores))
        box = (int(xy[top][0]), int(xy[top][1]), self.tile, self.tile)
        page_score = float(scores[top])
        return {"score": round(page_score, 4), "band": forgery_band(page_score, self.review, self.suspected),
                "thresholds": {"needs_review": self.review, "forgery_suspected": self.suspected},
                "top_tile": {"score": round(page_score, 4), "box_1280": list(box),  # x, y, w, h on the 1280 px page
                             "box_original": [round(v) for v in tiles.scale_box(box, (width, height), original_size)]},
                # every tile, for the officer's heatmap: (x, y) on the 1280 px page + score (~80 tiles, ~2 KB)
                "tiles": {"size": self.tile, "count": len(xy), "xy": xy.tolist(),
                          "scores": [round(float(s), 3) for s in scores]},
                "page_size_1280": [width, height], "original_size": list(original_size)}


# ---------------------------------------------------------------- face match

FACE_MATCH_FROM = 0.556  # Phase 4 policy: on ID-style portraits, FAR 1 % needed ~0.556; below that = review


def face_band(score: float | None, threshold: float, match_from: float = FACE_MATCH_FROM) -> str:
    """None -> no_face_found; < threshold (0.2597, LFW) -> mismatch; < match_from -> needs_review; else match."""
    if score is None:
        return "no_face_found"
    if score < threshold:
        return "mismatch"
    return "needs_review" if score < match_from else "match"


class FaceVerifier:
    """YuNet + SFace (Phase 4). A real ID upload has no annotated photo box, so the portrait is the LARGEST face
    YuNet finds on the page (the small ghost image is ignored); the selfie's largest face is compared with it."""

    MAX_SIDE = 1600  # larger uploads are shrunk first: faster detection, the portrait stays hundreds of px wide

    def __init__(self, model_dir: Path = MODEL_DIR):
        self.detector, self.recognizer = face.load_face_models()
        cfg = json.loads((model_dir / "face_config.json").read_text())
        self.threshold = float(cfg["decision"]["threshold"])  # 0.2597
        self.match_from = float(cfg["decision"].get("review_below", FACE_MATCH_FROM))  # 0.556
        self.liveness_policy = liveness.policy_from_env(same_person_min_cosine=self.threshold)  # Phase 13
        self.version = f"{file_version(config.YUNET_ONNX)}, {file_version(config.SFACE_ONNX)}"

    def _face(self, image_bytes: bytes, with_landmarks: bool = False):
        rgb = _rgb(image_bytes)
        scale = min(1.0, self.MAX_SIDE / max(rgb.shape[:2]))
        if scale < 1.0:
            rgb = np.asarray(Image.fromarray(rgb).resize((round(rgb.shape[1] * scale), round(rgb.shape[0] * scale)),
                                                         Image.Resampling.LANCZOS))
        aligned, info = face.detect_and_align(rgb, self.detector, self.recognizer, pick="largest")
        summary = {"faces": info["faces"], "confidence": None if aligned is None else round(info["score"], 3),
                   "box": None if info["box"] is None else [round(v / scale) for v in info["box"]]}
        if with_landmarks:
            summary["landmarks"] = None if aligned is None else [[x / scale, y / scale] for x, y in info["landmarks"]]
        return (None if aligned is None else face.embed(aligned, self.recognizer)), summary

    def liveness(self, neutral_bytes: bytes, left_bytes: bytes | None, right_bytes: bytes | None) -> dict:
        """Active liveness (Phase 13): the selfie (= the frame looking at the camera) and the two head-turn frames.
        No turn frames (the customer uploaded a photo) -> {"status": "not_provided"}."""
        if left_bytes is None or right_bytes is None:
            return dict(liveness.NOT_PROVIDED)
        frames = []
        for image in (neutral_bytes, left_bytes, right_bytes):
            embedding, summary = self._face(image, with_landmarks=True)
            frames.append(liveness.FrameFace(summary["landmarks"], embedding))
        return liveness.evaluate(*frames, self.liveness_policy)

    def verify(self, id_bytes: bytes, selfie_bytes: bytes) -> dict:
        id_embedding, id_info = self._face(id_bytes)
        selfie_embedding, selfie_info = self._face(selfie_bytes)
        score = None
        if id_embedding is not None and selfie_embedding is not None:
            score = round(face.compare(id_embedding, selfie_embedding), 4)
        missing = [name for name, e in (("id_document", id_embedding), ("selfie", selfie_embedding)) if e is None]
        return {"score": score, "band": face_band(score, self.threshold, self.match_from),
                "thresholds": {"mismatch_below": self.threshold, "match_from": self.match_from},
                "id_face": id_info, "selfie_face": selfie_info,
                "reason": f"no face found on: {', '.join(missing)} (ask for a new photo or review)" if missing else None}


# ---------------------------------------------------------------- fields + consistency rules

def ollama_runner_mb() -> float:
    """Resident memory (MB) of Ollama's model runner processes (llama-server), 0 if none is running.
    Also 0 inside a container (Phase 9): there is no `ps` in the slim image, and Ollama runs on the host anyway, out
    of the container's sight. The guard then never fires, and Ollama's own keep_alive still unloads the model."""
    try:
        out = subprocess.run(["ps", "-axo", "rss=,comm="], capture_output=True, text=True).stdout
    except OSError:
        return 0.0
    return sum(int(line.split()[0]) for line in out.splitlines() if line.strip().endswith("llama-server")) / 1024


class FieldExtractor:
    """Frozen prompt v2 (Phase 5) through Ollama, with the Phase 5 lessons applied: an output cap (num_predict;
    the longest of 364 answers was 251 tokens), a mild repeat penalty, a request timeout, a fixed context and a
    short keep_alive; the model is unloaded if its runner grows past max_runner_mb (prompt cache, Phase 5).
    Then the consistency rules run on the fields; each failed rule carries its severity."""

    OPTIONS = {"num_predict": 512, "repeat_penalty": 1.05, "repeat_last_n": 64}

    def __init__(self, host: str = "http://localhost:11434", model: str = "qwen2.5vl:7b", keep_alive: str = "2m",
                 timeout: float = 180.0, max_runner_mb: float = 8192):
        self.ollama = extraction.OllamaExtractor(model=model, host=host, keep_alive=keep_alive, num_ctx=6144,
                                                 timeout=timeout, options=self.OPTIONS)
        self.max_runner_mb = max_runner_mb
        self.version = f"{model} prompt {extraction.PROMPT_VERSION}"

    def available(self) -> bool:
        return self.ollama.available()

    def guard_memory(self) -> float:
        mb = ollama_runner_mb()
        if mb > self.max_runner_mb:
            log.warning("Ollama runner at %.0f MB > %.0f MB: unloading the model", mb, self.max_runner_mb)
            self.ollama.unload()
        return mb

    def extract(self, image_bytes: bytes, doc_type: str) -> dict:
        """{'valid': False, 'error': ...} when the model gave no valid answer (the worker reports status
        'failed'); otherwise the fields, every rule's status, and the failed rules with their severity."""
        result = self.ollama.extract(extraction.prepare_image(image_bytes), doc_type)
        runner_mb = self.guard_memory()
        meta = {"attempts": result.attempts, "llm_latency_s": round(result.latency_s, 2),
                "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                "runner_mb": round(runner_mb), "prompt_version": extraction.PROMPT_VERSION}
        if not result.valid:
            return {"valid": False, "error": result.error, **meta}
        rules = consistency.run_rules(result.fields, doc_type)
        flags = [{"rule": r.rule, "severity": consistency.RULE_SEVERITY[r.rule], "detail": r.detail}
                 for r in rules if r.status == "fail" and r.level == "flag"]
        return {"valid": True, "fields": result.fields, "rules": {r.rule: r.status for r in rules},
                "flags": flags, "strong_flags": [f["rule"] for f in flags if f["severity"] == "strong"],
                "review_flags": [f["rule"] for f in flags if f["severity"] == "review"], **meta}
