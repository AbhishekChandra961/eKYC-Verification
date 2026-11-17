"""Face verification (Phase 4): does the selfie show the person on the ID photo?

Production path (pretrained, used by the face worker):
    detector, recognizer = load_face_models()
    face_a, _ = detect_and_align(id_photo_rgb, detector, recognizer)   # 112x112 aligned face, or None
    face_b, _ = detect_and_align(selfie_rgb, detector, recognizer)
    score = compare(embed(face_a, recognizer), embed(face_b, recognizer))   # cosine similarity, -1 ... 1
    same_person = score >= threshold   (threshold from models/face_config.json, chosen for FAR <= 1 %)
- YuNet (OpenCV's FaceDetectorYN) finds faces and 5 landmarks (eyes, nose tip, mouth corners).
- SFace (OpenCV's FaceRecognizerSF) rotates and crops the face to 112x112 using those landmarks (alignCrop) and
  turns it into a 128-number embedding; faces of the same person have embeddings pointing the same way.

Deep-learning showcase: a Keras Siamese network (build_siamese) trained on LFW pairs in notebook 04.

Images are RGB numpy arrays (uint8 0-255, or float 0-1 as sklearn's LFW gives them). OpenCV works in BGR, so
the conversion happens inside this module only.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import keras
import numpy as np
import pandas as pd
from keras import layers

from ekyc import config

# ---------------------------------------------------------------- production path: YuNet + SFace

DETECTOR_SETTINGS = {
    "score_threshold": 0.6,  # minimum face confidence (opencv_zoo's demo uses 0.9; 0.6 also finds harder faces)
    "nms_threshold": 0.3,  # overlapping boxes above this IoU are merged into one face
    "top_k": 5000,  # candidate boxes kept before merging (OpenCV's default)
    "min_side": 224,  # images whose shorter side is smaller are enlarged to this first (LFW crops are 125x94)
    "pad_fraction": 0.25,  # black border added on every side, as a share of the longer side: faces that fill
}                          # the whole image (tight crops, ID photo boxes) are found more reliably with a margin


def load_face_models(yunet_path: Path = config.YUNET_ONNX, sface_path: Path = config.SFACE_ONNX,
                     settings: dict = DETECTOR_SETTINGS):
    """Load YuNet (detector) and SFace (recognizer) from their ONNX files."""
    detector = cv2.FaceDetectorYN.create(str(yunet_path), "", (320, 320), settings["score_threshold"],
                                         settings["nms_threshold"], settings["top_k"])
    recognizer = cv2.FaceRecognizerSF.create(str(sface_path), "")
    return detector, recognizer


def to_bgr_uint8(image: np.ndarray) -> np.ndarray:
    """RGB image (uint8 0-255, or float with values 0-1 or 0-255) -> BGR uint8, the format OpenCV expects."""
    image = np.asarray(image)
    if image.dtype != np.uint8:
        image = image * 255.0 if image.max() <= 1.0 else image
        image = np.clip(np.rint(image), 0, 255).astype(np.uint8)
    if image.ndim == 2:  # greyscale -> 3 channels
        image = np.stack([image] * 3, axis=-1)
    return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)


def detect_and_align(image_rgb: np.ndarray, detector, recognizer,
                     settings: dict = DETECTOR_SETTINGS) -> tuple[np.ndarray | None, dict]:
    """Find the most confident face and return it aligned (112x112 BGR uint8), plus detection details.

    Steps: enlarge small images (shorter side < min_side), add a black border, run YuNet, keep the face with the
    highest confidence, and let SFace rotate/crop it with the 5 landmarks. Returns (None, info) if no face is
    found; the caller decides what that means (for KYC: ask for a new photo or send to manual review).
    info: faces (how many were found), score (confidence of the kept face), box (x, y, w, h in the ORIGINAL
    image's pixels), scale (enlargement factor used).
    """
    bgr = to_bgr_uint8(image_rgb)
    height, width = bgr.shape[:2]
    scale = max(1.0, settings["min_side"] / min(height, width))
    if scale > 1.0:
        bgr = cv2.resize(bgr, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_CUBIC)
    pad = round(settings["pad_fraction"] * max(bgr.shape[:2]))
    bgr = cv2.copyMakeBorder(bgr, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    detector.setInputSize((bgr.shape[1], bgr.shape[0]))
    _, faces = detector.detect(bgr)  # None, or one row per face: x, y, w, h, 5 landmark (x, y) pairs, score
    if faces is None or len(faces) == 0:
        return None, {"faces": 0, "score": np.nan, "box": None, "scale": scale}
    best = faces[int(np.argmax(faces[:, -1]))]
    x, y, w, h = best[:4]
    box = ((x - pad) / scale, (y - pad) / scale, w / scale, h / scale)  # back to original image pixels
    aligned = recognizer.alignCrop(bgr, best)
    return aligned, {"faces": int(len(faces)), "score": float(best[-1]), "box": tuple(map(float, box)), "scale": scale}


def embed(aligned_bgr: np.ndarray, recognizer) -> np.ndarray:
    """SFace embedding of an aligned face, scaled to length 1 (so the dot product of two is their cosine)."""
    feature = recognizer.feature(aligned_bgr).reshape(-1).astype(np.float32)  # 128 numbers
    return feature / np.linalg.norm(feature)


def compare(embedding_a: np.ndarray, embedding_b: np.ndarray) -> float:
    """Cosine similarity of two unit-length embeddings: 1 = same direction (same person likely), about 0 =
    unrelated. Same value as SFace's own match(..., FR_COSINE)."""
    return float(np.dot(embedding_a, embedding_b))


def embed_images(images, detector, recognizer, settings: dict = DETECTOR_SETTINGS) -> tuple[np.ndarray, pd.DataFrame]:
    """Embed many images. Returns an (n, 128) array (rows of NaN where no face was found) and one row of
    detection details per image (found, faces, score)."""
    embeddings, details = [], []
    for image in images:
        aligned, info = detect_and_align(image, detector, recognizer, settings)
        embeddings.append(embed(aligned, recognizer) if aligned is not None else np.full(128, np.nan, np.float32))
        details.append({"found": aligned is not None, "faces": info["faces"], "score": info["score"]})
    return np.vstack(embeddings), pd.DataFrame(details)


def pair_scores(embeddings_a: np.ndarray, embeddings_b: np.ndarray) -> np.ndarray:
    """Cosine similarity of each row pair (NaN where a face was missing)."""
    return np.einsum("ij,ij->i", embeddings_a, embeddings_b)


# ---------------------------------------------------------------- LFW pairs

def lfw_pair_names(subset: str, lfw_dir: Path = config.LFW_DIR) -> pd.DataFrame:
    """Names of the two people in each LFW pair, in the order sklearn's fetch_lfw_pairs returns the pairs.
    subset "train" -> pairsDevTrain.txt, "test" -> pairsDevTest.txt. A line "name i j" is a same-person pair,
    "name_a i name_b j" a different-person pair (sklearn reads the lines in file order)."""
    path = lfw_dir / "lfw_home" / {"train": "pairsDevTrain.txt", "test": "pairsDevTest.txt"}[subset]
    lines = path.read_text().splitlines()
    rows = []
    for parts in (line.split("\t") for line in lines[1:]):
        if len(parts) == 3:
            rows.append({"name_a": parts[0], "name_b": parts[0], "same": 1})
        elif len(parts) == 4:
            rows.append({"name_a": parts[0], "name_b": parts[2], "same": 0})
    table = pd.DataFrame(rows)
    assert len(table) == 2 * int(lines[0]), f"{path.name}: expected {2 * int(lines[0])} pairs, parsed {len(table)}"
    return table


def identity_disjoint_split(names: pd.DataFrame, holdout: float = 0.15, seed: int = config.SEED) -> np.ndarray:
    """Boolean mask of held-out pairs such that no PERSON appears on both sides.

    People who appear in the same pair are linked (union-find, as for documents in Phase 2), and whole linked
    groups are moved to the held-out side, in random order, until it has `holdout` of the pairs.
    Why: the same person in training and validation pairs would make validation look better than new faces.
    """
    from ekyc.data import UnionFind  # local import: data.py is only needed here

    groups = UnionFind()
    for a, b in zip(names["name_a"], names["name_b"]):
        groups.union(a, b)
    group = names["name_a"].map(groups.find)
    order = np.random.default_rng(seed).permutation(group.unique())
    sizes = group.value_counts()
    held, total = set(), 0
    for g in order:
        if total >= holdout * len(names):
            break
        held.add(g)
        total += sizes[g]
    return group.isin(held).to_numpy()


# ---------------------------------------------------------------- ID-photo sanity check

def crop_with_margin(image: np.ndarray, box, margin: float = 0.15) -> np.ndarray:
    """Cut box = (x, y, w, h) out of an image, grown by `margin` x its size on every side (clipped to the image)."""
    x, y, w, h = box
    height, width = image.shape[:2]
    x0, y0 = max(0, int(x - margin * w)), max(0, int(y - margin * h))
    x1, y1 = min(width, int(x + w + margin * w)), min(height, int(y + h + margin * h))
    return image[y0:y1, x0:x1]


def simulate_selfie(face_rgb: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, dict]:
    """A synthetic 'selfie' of an ID photo: random rotation (+-15 degrees), scale (0.6-1.0, the face shrinks inside
    the frame), brightness (x0.6-1.4), Gaussian blur (sigma 0-2 px) and a JPEG save (quality 30-80).
    Returns the new RGB uint8 image and the parameters drawn. A crude stand-in for a real selfie: same face,
    same expression and lighting, so it tests robustness to image quality, not to a different photo."""
    params = {"angle": float(rng.uniform(-15, 15)), "scale": float(rng.uniform(0.6, 1.0)),
              "brightness": float(rng.uniform(0.6, 1.4)), "blur_sigma": float(rng.uniform(0, 2)),
              "jpeg_quality": int(rng.integers(30, 81))}
    image = np.asarray(face_rgb, dtype=np.uint8)
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), params["angle"], params["scale"])
    image = cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    image = np.clip(image.astype(np.float32) * params["brightness"], 0, 255).astype(np.uint8)
    if params["blur_sigma"] > 0.1:
        image = cv2.GaussianBlur(image, (0, 0), params["blur_sigma"])
    ok, encoded = cv2.imencode(".jpg", cv2.cvtColor(image, cv2.COLOR_RGB2BGR),
                               [cv2.IMWRITE_JPEG_QUALITY, params["jpeg_quality"]])
    image = cv2.cvtColor(cv2.imdecode(encoded, cv2.IMREAD_COLOR), cv2.COLOR_BGR2RGB)
    return image, params


# ---------------------------------------------------------------- deep-learning showcase: Siamese network

@keras.saving.register_keras_serializable(package="ekyc")
class AbsoluteDifference(layers.Layer):
    """|a - b| of two embeddings, number by number (registered so the saved model can be loaded again)."""

    def call(self, inputs):
        a, b = inputs
        return keras.ops.abs(a - b)


def build_siamese(image_size: int = 128, embedding_dim: int = 128, dropout: float = 0.2,
                  weights: str | None = "imagenet") -> tuple[keras.Model, keras.Model, keras.Model]:
    """Siamese network: ONE embedding network applied to both faces (shared weights), then a small head that
    turns the pair of embeddings into P(same person). Returns (siamese, embedding_model, backbone).

    Embedding network: raw 0-255 pixels -> scaled to [-1, 1] (what MobileNetV2 expects) -> frozen ImageNet
    MobileNetV2 (average-pooled, 1280 numbers) -> dropout -> Dense(embedding_dim) -> scaled to length 1.
    Head: |e_a - e_b| and e_a * e_b (both symmetric, so swapping the faces gives the same score) ->
    Dense(64, relu) -> Dense(1, sigmoid). Trained with binary cross-entropy (1 = same person).
    """
    backbone = keras.applications.MobileNetV2(include_top=False, weights=weights, pooling="avg",
                                              input_shape=(image_size, image_size, 3))
    backbone.trainable = False
    face = keras.Input((image_size, image_size, 3), name="face")
    x = layers.Rescaling(1 / 127.5, offset=-1.0, name="to_minus1_1")(face)
    x = backbone(x, training=False)  # training=False: BatchNormalization stays in inference mode
    x = layers.Dropout(dropout, name="embedding_dropout")(x)
    x = layers.Dense(embedding_dim, name="embedding_dense")(x)
    embedding_model = keras.Model(face, layers.UnitNormalization(name="embedding")(x), name="face_embedding")

    face_a = keras.Input((image_size, image_size, 3), name="face_a")
    face_b = keras.Input((image_size, image_size, 3), name="face_b")
    e_a, e_b = embedding_model(face_a), embedding_model(face_b)
    pair = layers.Concatenate(name="pair_features")([AbsoluteDifference(name="abs_difference")([e_a, e_b]),
                                                     layers.Multiply(name="product")([e_a, e_b])])
    x = layers.Dense(64, activation="relu", name="head_dense")(pair)
    same = layers.Dense(1, activation="sigmoid", name="same_person")(x)
    return keras.Model([face_a, face_b], same, name="face_siamese"), embedding_model, backbone


def make_pair_dataset(pairs: np.ndarray, labels: np.ndarray, image_size: int = 128, batch_size: int = 32,
                      training: bool = False, seed: int = config.SEED):
    """tf.data pipeline of face pairs for the Siamese network.

    pairs: (n, 2, height, width, 3) RGB uint8; labels: (n,) with 1 = same person. Each face is resized with
    padding (no stretching) to image_size x image_size; pixels stay 0-255 floats (the model rescales them).
    training=True: pairs are reshuffled every epoch and each face gets its own random rotation (+-10 degrees),
    zoom (+-10 %) and brightness change (+-20 %): small changes a camera could cause, never a different person.
    """
    import tensorflow as tf  # keras runs on TensorFlow here; imported where it is used

    augment = keras.Sequential([layers.RandomRotation(10 / 360, fill_mode="reflect", seed=seed),
                                layers.RandomZoom(0.1, fill_mode="reflect", seed=seed + 1),
                                layers.RandomBrightness(0.2, value_range=(0, 255), seed=seed + 2)], name="augment")

    def prepare(pair, label):
        faces = tf.image.resize_with_pad(tf.cast(pair, tf.float32), image_size, image_size)  # both faces at once
        return (faces[0], faces[1]), tf.cast(label, tf.float32)

    def augment_both(faces, label):
        return (augment(faces[0], training=True), augment(faces[1], training=True)), label

    ds = tf.data.Dataset.from_tensor_slices((pairs, labels))
    if training:
        ds = ds.shuffle(len(labels), seed=seed, reshuffle_each_iteration=True)
    ds = ds.map(prepare, num_parallel_calls=tf.data.AUTOTUNE).batch(batch_size)
    if training:
        ds = ds.map(augment_both, num_parallel_calls=tf.data.AUTOTUNE)
    return ds.prefetch(tf.data.AUTOTUNE)
