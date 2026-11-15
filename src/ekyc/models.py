"""Model builders and training helpers for Phase 3.

Transfer learning recipe (as in the Keras fine-tuning guide):
  stage 1: ImageNet backbone frozen, only the new classification head is trained;
  stage 2: the top layers of the backbone are unfrozen and trained with a low learning rate.
The backbone is always called with training=False, so its BatchNormalization layers keep their
ImageNet statistics; updating them on small batches would undo the pretrained features.
"""

from __future__ import annotations

import time
from pathlib import Path

import keras
from keras import layers


def build_doc_classifier(num_classes: int, image_size: int = 224, dropout: float = 0.2,
                         weights: str | None = "imagenet") -> tuple[keras.Model, keras.Model]:
    """EfficientNetB0 backbone + a small softmax head. Returns (model, backbone).

    Input: float32 images of shape (image_size, image_size, 3) with raw 0-255 pixel values.
    Keras EfficientNet contains its own rescaling + normalisation layers, so images must NOT be
    divided by 255 beforehand.
    """
    backbone = keras.applications.EfficientNetB0(
        include_top=False, weights=weights, input_shape=(image_size, image_size, 3), pooling="avg")
    backbone.trainable = False

    inputs = keras.Input(shape=(image_size, image_size, 3), name="image")
    features = backbone(inputs, training=False)  # 1280 features per image
    features = layers.Dropout(dropout, name="head_dropout")(features)
    outputs = layers.Dense(num_classes, activation="softmax", name="doc_type")(features)
    return keras.Model(inputs, outputs, name="doc_classifier"), backbone


def unfreeze_top_layers(backbone: keras.Model, n_layers: int) -> int:
    """Make the last `n_layers` backbone layers trainable, except BatchNormalization layers.
    Returns the number of layers that are now trainable. The model must be re-compiled afterwards.
    """
    backbone.trainable = True
    for i, layer in enumerate(backbone.layers):
        in_top = i >= len(backbone.layers) - n_layers
        layer.trainable = in_top and not isinstance(layer, layers.BatchNormalization)
    return sum(layer.trainable for layer in backbone.layers)


class EpochTimer(keras.callbacks.Callback):
    """Records the wall-clock duration of every epoch (seconds) in `self.seconds`."""

    def on_train_begin(self, logs=None):
        self.seconds = []

    def on_epoch_begin(self, epoch, logs=None):
        self._start = time.perf_counter()

    def on_epoch_end(self, epoch, logs=None):
        self.seconds.append(time.perf_counter() - self._start)


def training_callbacks(checkpoint_path: Path, log_path: Path, patience: int = 3) -> list:
    """Early stopping on validation loss (best weights restored), best-model checkpoint, CSV log,
    and an EpochTimer (always the last element of the list)."""
    return [
        keras.callbacks.EarlyStopping(monitor="val_loss", patience=patience, restore_best_weights=True, verbose=1),
        keras.callbacks.ModelCheckpoint(str(checkpoint_path), monitor="val_loss", save_best_only=True, verbose=0),
        keras.callbacks.CSVLogger(str(log_path)),
        EpochTimer(),
    ]
