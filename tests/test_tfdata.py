"""Tests for src/ekyc/tfdata.py and src/ekyc/models.py using small synthetic images
(no dependency on the real dataset)."""

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from ekyc.models import build_doc_classifier, unfreeze_top_layers
from ekyc.tfdata import make_dataset


@pytest.fixture
def tiny_manifest(tmp_path):
    """Two white JPEGs: one landscape (ID-card-like), one portrait."""
    rows = []
    for name, size, doc_type in [("wide.jpg", (100, 50), "alb_id"), ("tall.jpg", (50, 100), "svk_id")]:
        Image.new("RGB", size, (255, 255, 255)).save(tmp_path / name, quality=95)
        rows.append({"cache_path": name, "doc_type": doc_type})
    return pd.DataFrame(rows), tmp_path


def test_images_are_square_float_0_255_and_padded(tiny_manifest):
    manifest, root = tiny_manifest
    images, labels = next(iter(make_dataset(manifest, "doc_type", ["alb_id", "svk_id"], 64,
                                            batch_size=2, project_root=root)))
    images = images.numpy()
    assert images.shape == (2, 64, 64, 3) and images.dtype == np.float32
    assert images.min() >= 0 and images.max() <= 255
    # Aspect ratio kept: the wide image gets black bars top/bottom, the tall one left/right.
    assert images[0, 0, 32].max() < 10 and images[0, 32, 32].min() > 245
    assert images[1, 32, 0].max() < 10 and images[1, 32, 32].min() > 245
    assert labels.numpy().tolist() == [0, 1]  # index in class_names


def test_evaluation_pipeline_is_deterministic(tiny_manifest):
    manifest, root = tiny_manifest
    ds = make_dataset(manifest, "doc_type", ["alb_id", "svk_id"], 64, batch_size=2, project_root=root)
    first, second = [next(iter(ds))[0].numpy() for _ in range(2)]
    np.testing.assert_array_equal(first, second)  # no augmentation, no shuffling


def test_training_pipeline_keeps_shape_and_range(tiny_manifest):
    manifest, root = tiny_manifest
    ds = make_dataset(manifest, "doc_type", ["alb_id", "svk_id"], 64, batch_size=2, training=True, project_root=root)
    images, labels = next(iter(ds))
    assert images.shape == (2, 64, 64, 3)
    assert 0 <= images.numpy().min() and images.numpy().max() <= 255
    assert sorted(labels.numpy().tolist()) == [0, 1]  # shuffled, but nothing lost


def test_unknown_label_raises(tiny_manifest):
    manifest, root = tiny_manifest
    with pytest.raises(ValueError):
        make_dataset(manifest, "doc_type", ["alb_id"], 64, project_root=root)


def test_classifier_head_and_unfreezing_keep_batchnorm_frozen():
    model, backbone = build_doc_classifier(num_classes=10, image_size=64, weights=None)
    assert model.output_shape == (None, 10)
    assert not any(layer.trainable for layer in backbone.layers)  # stage 1: backbone frozen
    n = unfreeze_top_layers(backbone, 20)
    top = backbone.layers[-20:]
    assert n == sum(layer.__class__.__name__ != "BatchNormalization" for layer in top)
    assert not any(layer.trainable for layer in backbone.layers if layer.__class__.__name__ == "BatchNormalization")
