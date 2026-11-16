"""tf.data input pipeline shared by all Phase 3 models.

Reads the training manifest (data/processed/manifest.csv), keeps one split, and streams the
512 px cached images (never the raw files, see CLAUDE.md "Phase 2 findings") from disk in batches.
Only file paths and labels are held in memory; images are decoded batch by batch.

Image format produced: float32, shape (size, size, 3), pixel values 0-255. Keras EfficientNet
models rescale/normalise internally, so no further preprocessing is applied here.
"""

from __future__ import annotations

from pathlib import Path

import keras
import numpy as np
import pandas as pd
import tensorflow as tf
from keras import layers

from ekyc import config

AUTOTUNE = tf.data.AUTOTUNE


def load_manifest(path: Path = config.MANIFEST_CSV, split: str | None = None) -> pd.DataFrame:
    """Read manifest.csv; optionally keep one split ("train", "val" or "test")."""
    manifest = pd.read_csv(path, low_memory=False)
    if split is not None:
        if split not in config.SPLIT_RATIOS:
            raise ValueError(f"Unknown split {split!r}")
        manifest = manifest[manifest["split"] == split].reset_index(drop=True)
    return manifest


def load_image(path: tf.Tensor, image_size: int) -> tf.Tensor:
    """Read one JPEG and fit it into a square of `image_size` px without distorting it.

    resize_with_pad scales the image so its longest side equals image_size and fills the rest
    with black bars. ID cards (~1.58:1) and passports (~1.42:1) have different shapes, and a plain
    resize would squash them differently.
    """
    image = tf.io.decode_jpeg(tf.io.read_file(path), channels=3)
    image = tf.image.resize_with_pad(image, image_size, image_size)  # -> float32, values 0-255
    return image


def pad_geometry(width: int, height: int, size: int) -> tuple[float, int, int]:
    """Where an image of width x height ends up inside the size x size output of resize_with_pad.

    Returns (scale, offset_x, offset_y): a point (x, y) of the image lands at
    (x * scale + offset_x, y * scale + offset_y). Same arithmetic as TensorFlow's implementation:
    scale so the longer side fits, then centre with floor((size - scaled side) / 2) padding.
    """
    ratio = max(width / size, height / size)
    offset_x = max(0, int(np.floor((size - width / ratio) / 2)))
    offset_y = max(0, int(np.floor((size - height / ratio) / 2)))
    return 1 / ratio, offset_x, offset_y


def build_augmenter(seed: int = config.SEED) -> keras.Sequential:
    """Light, realistic augmentation for training only.

    - small rotation (up to ~3.6 degrees) and shift (up to 5 %): photos are never perfectly aligned
    - brightness / contrast (up to 10 %): lighting differences between photos
    No horizontal flips (mirrored text never occurs on a real document) and no blur or JPEG
    compression (they would destroy the fine detail a forgery detector relies on).
    Empty areas created by rotation/shift are filled with black, like the resize padding;
    the default "reflect" fill would mirror text into the corners.
    """
    return keras.Sequential(
        [
            layers.RandomRotation(0.01, fill_mode="constant", fill_value=0.0, seed=seed),  # 0.01 x 360 deg
            layers.RandomTranslation(0.05, 0.05, fill_mode="constant", fill_value=0.0, seed=seed),
            layers.RandomBrightness(0.1, value_range=(0, 255), seed=seed),
            layers.RandomContrast(0.1, value_range=(0, 255), seed=seed),
        ],
        name="augment",
    )


def make_dataset(
    manifest: pd.DataFrame,
    target: str,
    class_names: list[str],
    image_size: int,
    batch_size: int = 32,
    training: bool = False,
    project_root: Path = config.PROJECT_ROOT,
    seed: int = config.SEED,
) -> tf.data.Dataset:
    """Batched (image, label) dataset for one manifest subset.

    target       manifest column to predict, e.g. "doc_type" or "label"
    class_names  label values in index order; label = position in this list
    training     True: shuffle every epoch and augment. False: fixed order (rows stay aligned
                 with `manifest`, which evaluation relies on) and no augmentation.
    """
    unknown = set(manifest[target]) - set(class_names)
    if unknown:
        raise ValueError(f"{target} values not in class_names: {sorted(map(str, unknown))}")
    index_of = {name: i for i, name in enumerate(class_names)}
    paths = [str(project_root / p) for p in manifest["cache_path"]]
    labels = manifest[target].map(index_of).astype("int32").to_numpy()

    ds = tf.data.Dataset.from_tensor_slices((paths, labels))
    if training:
        # Shuffling paths (short strings) is cheap; a full-size buffer gives a perfect shuffle.
        ds = ds.shuffle(len(paths), seed=seed, reshuffle_each_iteration=True)
    ds = ds.map(lambda p, y: (load_image(p, image_size), y), num_parallel_calls=AUTOTUNE)
    ds = ds.batch(batch_size)
    if training:
        augmenter = build_augmenter(seed)
        ds = ds.map(lambda x, y: (tf.clip_by_value(augmenter(x, training=True), 0.0, 255.0), y),
                    num_parallel_calls=AUTOTUNE)
    return ds.prefetch(AUTOTUNE)  # prepare the next batch on the CPU while the GPU trains


def make_dataset_from_paths(paths: list[str], image_size: int, batch_size: int = 32) -> tf.data.Dataset:
    """Images only (no labels), fixed order, no augmentation: for predicting on arbitrary files."""
    ds = tf.data.Dataset.from_tensor_slices([str(p) for p in paths])
    ds = ds.map(lambda p: load_image(p, image_size), num_parallel_calls=AUTOTUNE)
    return ds.batch(batch_size).prefetch(AUTOTUNE)
