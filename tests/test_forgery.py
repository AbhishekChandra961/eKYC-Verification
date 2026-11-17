"""Tests for the Phase 3B helpers: padding geometry, box mapping, thresholds, breakdowns,
model builders, Grad-CAM and callbacks (synthetic inputs only, no real data needed)."""

import keras
import numpy as np
import pandas as pd
import pytest
import tensorflow as tf

from ekyc import evaluation, gradcam, models
from ekyc.tfdata import pad_geometry


# ------------------------------------------------------------------ geometry
@pytest.mark.parametrize("width, height", [(300, 200), (200, 300), (512, 321), (512, 512)])
def test_pad_geometry_matches_tensorflow(width, height):
    """A white square drawn at a known place must land where pad_geometry predicts."""
    image = np.zeros((height, width, 3), np.float32)
    image[40:60, 50:70] = 255.0  # square: x 50-70, y 40-60
    padded = tf.image.resize_with_pad(image, 512, 512).numpy()
    ys, xs = np.where(padded[..., 0] > 127)
    scale, off_x, off_y = pad_geometry(width, height, 512)
    assert abs(xs.min() - (50 * scale + off_x)) <= 1.5 and abs(ys.min() - (40 * scale + off_y)) <= 1.5
    assert abs(xs.max() + 1 - (70 * scale + off_x)) <= 1.5 and abs(ys.max() + 1 - (60 * scale + off_y)) <= 1.5


def test_box_to_input_composes_cache_and_padding():
    # 2167 x 1360 template -> 512 x 321 cache -> 512 x 512 input (95 px of black bar on top).
    x, y, w, h = gradcam.box_to_input((1456, 846, 397, 43), (2167, 1360), (512, 321), 512)
    s = 512 / 2167
    assert np.allclose([x, y, w, h], [1456 * s, 846 * s + 95, 397 * s, 43 * s], atol=0.5)


def test_point_in_box_and_peak():
    heat = np.zeros((10, 10))
    heat[3, 7] = 1.0  # row 3, column 7
    assert gradcam.peak_location(heat) == (7, 3)
    assert gradcam.point_in_box((7, 3), (6, 2, 2, 2)) and not gradcam.point_in_box((7, 3), (0, 0, 5, 5))


# ------------------------------------------------------------------ thresholds and metrics
Y = np.array([0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
S = np.array([0.1, 0.2, 0.3, 0.75, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])


def test_threshold_for_recall_is_highest_threshold_meeting_target():
    result = evaluation.threshold_for_recall(Y, S, min_recall=0.9)
    assert result["recall"] >= 0.9
    predicted = S >= result["threshold"]
    assert predicted[Y == 1].mean() == result["recall"]
    # Any higher threshold would catch fewer than 90 % of the 6 forgeries.
    higher = S[S > result["threshold"]].min()
    assert (S[Y == 1] >= higher).mean() < 0.9


def test_f1_optimal_threshold_on_separable_scores():
    result = evaluation.f1_optimal_threshold(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.8, 0.9]))
    assert result["f1"] == 1.0 and 0.2 < result["threshold"] <= 0.8


def test_confusion_and_breakdown():
    cm = evaluation.confusion_at(Y, S, 0.5)
    assert cm.loc["forged", "predicted forged"] == 5 and cm.loc["genuine", "predicted forged"] == 1
    df = pd.DataFrame({"label": Y, "score": S, "group": ["a"] * 5 + ["b"] * 5})
    table = evaluation.breakdown(df, "group", 0.5)
    assert table.loc["a", "images"] == 5 and table.loc["b", "recall"] == 1.0
    # ROC-AUC = share of (forged, genuine) pairs ranked correctly: genuine 0.1/0.2/0.3 are beaten by all
    # 6 forged scores (18 pairs), genuine 0.75 only by 0.8 and 0.9 (2 pairs) -> 20 of 24 pairs.
    assert evaluation.ranking_scores(Y, S)["roc_auc"] == pytest.approx(20 / 24)


# ------------------------------------------------------------------ models, Grad-CAM, callbacks
def test_small_cnn_and_detector_shapes():
    assert models.build_small_cnn(image_size=64).output_shape == (None, 1)
    detector, backbone = models.build_forgery_detector(image_size=64, weights=None)
    assert detector.output_shape == (None, 1) and backbone.name == "efficientnetb0"
    assert not backbone.trainable


def test_gradcam_returns_normalised_maps_of_input_size():
    detector, _ = models.build_forgery_detector(image_size=64, weights=None)
    feature_model, output_layer = gradcam.gradcam_parts(detector)
    # NumPy, not tf.random: seeded TensorFlow random ops abort the process on the Metal GPU plugin.
    images = tf.constant(np.random.default_rng(0).uniform(0, 255, (2, 64, 64, 3)), dtype=tf.float32)
    heat = gradcam.gradcam(feature_model, output_layer, images)
    assert heat.shape == (2, 64, 64) and heat.min() >= 0 and heat.max() <= 1.0 + 1e-6


def test_closed_form_weights_equal_true_gradients():
    """The closed-form Grad-CAM weights must equal the real gradients d logit / d feature maps.
    Run on the CPU: back-propagation through convolutions aborts on the Metal GPU plugin."""
    with tf.device("/CPU:0"):
        detector, _ = models.build_forgery_detector(image_size=128, weights=None)
        head = detector.get_layer("forged")
        head.kernel.assign(np.random.default_rng(0).normal(0, 0.05, head.kernel.shape).astype("float32"))
        feature_model, output_layer = gradcam.gradcam_parts(detector)
        images = tf.constant(np.random.default_rng(1).uniform(0, 255, (2, 128, 128, 3)), dtype=tf.float32)
        with tf.GradientTape() as tape:
            feature_maps, pooled = feature_model(images, training=False)
            logit = tf.matmul(pooled, output_layer.kernel) + output_layer.bias
        true_weights = tf.reduce_mean(tape.gradient(logit, feature_maps), axis=(1, 2))  # (2, 1280)
        closed_form = gradcam.channel_weights(output_layer, feature_maps)
    np.testing.assert_allclose(true_weights.numpy(), np.tile(closed_form.numpy(), (2, 1)), atol=1e-7)


def test_training_callbacks():
    cbs = models.training_callbacks("x.keras", "x.csv", monitor="val_pr_auc", mode="max", reduce_lr_patience=1)
    kinds = [type(cb).__name__ for cb in cbs]
    assert kinds[0] == "TerminateOnNaN" and kinds[-1] == "EpochTimer"
    assert any(isinstance(cb, keras.callbacks.ReduceLROnPlateau) for cb in cbs)
    assert all(getattr(cb, "monitor", "val_pr_auc") == "val_pr_auc" for cb in cbs)
    assert not any(isinstance(cb, keras.callbacks.ReduceLROnPlateau) for cb in models.training_callbacks("x.keras", "x.csv"))
    assert isinstance(cbs[1], keras.callbacks.EarlyStopping)


def _resume_fit(tmp_path, resume_best):
    """One epoch (the 2nd) of a tiny model whose val_loss (mse >= 0) can never beat resume_best = -1."""
    log = tmp_path / "log.csv"
    log.write_text("epoch,learning_rate,loss,val_loss\n0,0.001,1.0,1.0\n")  # epoch 0, from the "first run"
    cbs = models.training_callbacks(tmp_path / "m.keras", log, patience=3, monitor="val_loss", mode="min",
                                    reduce_lr_patience=1, resume_best=resume_best)
    model = keras.Sequential([keras.layers.Input((2,)), keras.layers.Dense(1)])
    model.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse")
    x, y = np.zeros((8, 2)), np.ones((8, 1))
    model.fit(x, y, validation_data=(x, y), initial_epoch=1, epochs=2, callbacks=cbs, verbose=0)
    return model, cbs, log.read_text().splitlines()


def test_training_callbacks_resume_against_the_earlier_best(tmp_path):
    model, cbs, lines = _resume_fit(tmp_path, resume_best=-1.0)
    assert not (tmp_path / "m.keras").exists()  # not better than the earlier best: earlier checkpoint kept
    assert len(lines) == 3 and lines[1].startswith("0,")  # log continued: first-run row kept, epoch 1 added
    assert lines[2].startswith("1,")
    assert cbs[1].wait == 1  # early stopping counts this epoch as "no improvement"
    assert float(model.optimizer.learning_rate) == pytest.approx(5e-4)  # patience 1 -> learning rate halved


def test_training_callbacks_without_resume_start_fresh(tmp_path):
    model, cbs, lines = _resume_fit(tmp_path, resume_best=None)
    assert (tmp_path / "m.keras").exists()  # the first epoch of a fresh run is always the best so far
    assert len(lines) == 2  # log overwritten
    assert float(model.optimizer.learning_rate) == pytest.approx(1e-3)
