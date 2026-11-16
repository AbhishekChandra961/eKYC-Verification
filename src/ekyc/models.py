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


def build_small_cnn(image_size: int = 512, filters: tuple[int, ...] = (16, 32, 64, 128, 256),
                    dropout: float = 0.3) -> keras.Model:
    """Baseline forgery detector trained from scratch (B1).

    Five blocks of 3x3 convolution -> BatchNormalization -> ReLU -> 2x2 max-pooling halve the image
    five times (512 -> 16 px), then global average pooling and one sigmoid output = P(forged).
    The first convolutions run at full 512 px resolution, so fine edit traces can be picked up.
    """
    inputs = keras.Input(shape=(image_size, image_size, 3), name="image")
    x = layers.Rescaling(1 / 255, name="scale_0_1")(inputs)  # this model has no built-in preprocessing
    for i, n_filters in enumerate(filters, start=1):
        x = layers.Conv2D(n_filters, 3, padding="same", use_bias=False, name=f"conv{i}")(x)
        x = layers.BatchNormalization(name=f"bn{i}")(x)
        x = layers.ReLU(name=f"relu{i}")(x)
        x = layers.MaxPooling2D(2, name=f"pool{i}")(x)
    x = layers.GlobalAveragePooling2D(name="gap")(x)
    x = layers.Dropout(dropout, name="head_dropout")(x)
    outputs = layers.Dense(1, activation="sigmoid", name="forged")(x)
    return keras.Model(inputs, outputs, name="small_cnn")


def build_forgery_detector(image_size: int = 512, dropout: float = 0.3,
                           weights: str | None = "imagenet") -> tuple[keras.Model, keras.Model]:
    """EfficientNetB0 backbone + sigmoid head (B2). Returns (model, backbone).

    Same structure as build_doc_classifier, but one output: P(forged). Input: raw 0-255 pixels.
    The output layer is named "forged" and the backbone "efficientnetb0"; gradcam.py relies on both.
    """
    backbone = keras.applications.EfficientNetB0(
        include_top=False, weights=weights, input_shape=(image_size, image_size, 3), pooling="avg")
    backbone.trainable = False

    inputs = keras.Input(shape=(image_size, image_size, 3), name="image")
    features = backbone(inputs, training=False)
    features = layers.Dropout(dropout, name="head_dropout")(features)
    outputs = layers.Dense(1, activation="sigmoid", name="forged")(features)
    return keras.Model(inputs, outputs, name="forgery_detector"), backbone


def compile_forgery_model(model: keras.Model, learning_rate: float, clipnorm: float = 1.0) -> None:
    """Binary cross-entropy + Adam with gradient clipping (clipnorm: the gradient vector is scaled down
    whenever its length exceeds this value, which prevents one bad batch from blowing up the weights).
    Tracked metrics: PR-AUC ("pr_auc", used for model selection) and ROC-AUC ("roc_auc")."""
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate, clipnorm=clipnorm),
        loss="binary_crossentropy",
        metrics=[keras.metrics.AUC(curve="PR", name="pr_auc"), keras.metrics.AUC(curve="ROC", name="roc_auc")],
    )


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


def training_callbacks(checkpoint_path: Path, log_path: Path, patience: int = 3, monitor: str = "val_loss",
                       mode: str = "min", reduce_lr_patience: int | None = None) -> list:
    """Callbacks used for every training run:
    - TerminateOnNaN: stop at once if the loss becomes NaN (happened in Phase 3A fine-tuning);
    - EarlyStopping on `monitor` (best weights restored at the end);
    - ModelCheckpoint: keep only the best model by `monitor`;
    - optional ReduceLROnPlateau: halve the learning rate when `monitor` stalls;
    - CSVLogger, and an EpochTimer (always the last element of the list).
    mode: "min" for losses, "max" for scores such as "val_pr_auc".
    """
    callbacks = [
        keras.callbacks.TerminateOnNaN(),
        keras.callbacks.EarlyStopping(monitor=monitor, mode=mode, patience=patience, restore_best_weights=True,
                                      verbose=1),
        keras.callbacks.ModelCheckpoint(str(checkpoint_path), monitor=monitor, mode=mode, save_best_only=True,
                                        verbose=0),
    ]
    if reduce_lr_patience is not None:
        callbacks.append(keras.callbacks.ReduceLROnPlateau(monitor=monitor, mode=mode, factor=0.5,
                                                           patience=reduce_lr_patience, min_lr=1e-7, verbose=1))
    callbacks += [keras.callbacks.CSVLogger(str(log_path)), EpochTimer()]
    return callbacks
