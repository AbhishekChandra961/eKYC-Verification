"""Tests for face verification (Phase 4): src/ekyc/face.py and the verification metrics in evaluation.py.
Tests that need the downloaded ONNX models or the local LFW images are skipped when those files are missing."""

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from ekyc import config, evaluation, face

MODELS = pytest.mark.skipif(not (config.YUNET_ONNX.exists() and config.SFACE_ONNX.exists()),
                            reason="YuNet/SFace ONNX files not downloaded (models/face/)")
LFW_IMAGE = config.LFW_DIR / "lfw_home" / "lfw_funneled" / "Aaron_Peirsol" / "Aaron_Peirsol_0001.jpg"


# ------------------------------------------------------------------ verification metrics (evaluation.py)
# impostor (label 0) scores 0.1 0.2 0.3 0.7; genuine (label 1) scores 0.4 0.6 0.8 0.9
Y, S = [0, 0, 0, 0, 1, 1, 1, 1], [0.1, 0.2, 0.3, 0.7, 0.4, 0.6, 0.8, 0.9]


def test_threshold_at_far():
    assert evaluation.threshold_at_far(Y, S, 0.0) == {"threshold": 0.8, "far": 0.0, "tar": 0.5}  # above 0.7
    assert evaluation.threshold_at_far(Y, S, 0.25) == {"threshold": 0.4, "far": 0.25, "tar": 1.0}  # 1 impostor in


def test_equal_error_rate_and_report():
    assert evaluation.equal_error_rate(Y, S) == {"eer": 0.25, "threshold": 0.6}  # 1 of 4 wrong on each side
    r = evaluation.verification_report(Y, S, threshold=0.5)
    assert r["roc_auc"] == 0.875 and r["accuracy"] == 0.75 and r["far"] == 0.25 and r["frr"] == 0.25
    assert r["tar_at_far_1%"] == 0.5 and r["impostor pairs"] == 4


# ------------------------------------------------------------------ small helpers
def test_to_bgr_uint8_scales_and_swaps_channels():
    rgb = np.zeros((2, 2, 3), np.float32)
    rgb[..., 0] = 1.0  # pure red, as a 0-1 float image (sklearn's LFW format)
    bgr = face.to_bgr_uint8(rgb)
    assert bgr.dtype == np.uint8 and bgr[0, 0].tolist() == [0, 0, 255]


def test_compare_is_cosine_similarity():
    a, b = np.array([1.0, 0.0]), np.array([0.6, 0.8])
    assert face.compare(a, a) == 1.0 and face.compare(a, b) == pytest.approx(0.6)


def test_crop_with_margin_stays_inside_the_image():
    image = np.zeros((100, 200, 3), np.uint8)
    assert face.crop_with_margin(image, (10, 10, 50, 40), margin=0.1).shape == (48, 60, 3)  # 4 + 40 + 4, 5 + 50 + 5
    assert face.crop_with_margin(image, (0, 0, 100, 100), margin=0.5).shape == (100, 150, 3)  # clipped


def test_simulate_selfie_is_random_but_reproducible():
    image = np.random.default_rng(0).integers(0, 255, (80, 60, 3), dtype=np.uint8)
    out1, p1 = face.simulate_selfie(image, np.random.default_rng(5))
    out2, p2 = face.simulate_selfie(image, np.random.default_rng(5))
    assert out1.shape == image.shape and out1.dtype == np.uint8
    assert p1 == p2 and np.array_equal(out1, out2) and not np.array_equal(out1, image)
    assert -15 <= p1["angle"] <= 15 and 30 <= p1["jpeg_quality"] <= 80


# ------------------------------------------------------------------ LFW pair files and the identity split
def test_lfw_pair_names_parses_both_line_kinds(tmp_path):
    (tmp_path / "lfw_home").mkdir()
    (tmp_path / "lfw_home" / "pairsDevTrain.txt").write_text("1\nAnn\t1\t2\nBob\t1\tCid\t3\n")
    names = face.lfw_pair_names("train", lfw_dir=tmp_path)
    assert names.to_dict(orient="records") == [{"name_a": "Ann", "name_b": "Ann", "same": 1},
                                               {"name_a": "Bob", "name_b": "Cid", "same": 0}]


def test_identity_disjoint_split_keeps_people_on_one_side():
    rng = np.random.default_rng(1)
    people = [f"p{i}" for i in range(60)]
    rows = [{"name_a": p, "name_b": p, "same": 1} for p in people]
    rows += [{"name_a": a, "name_b": b, "same": 0} for a, b in rng.choice(people, (40, 2)) if a != b]
    names = pd.DataFrame(rows)
    held = face.identity_disjoint_split(names, holdout=0.15, seed=0)
    held_people = set(names.loc[held, "name_a"]) | set(names.loc[held, "name_b"])
    kept_people = set(names.loc[~held, "name_a"]) | set(names.loc[~held, "name_b"])
    assert not held_people & kept_people  # nobody on both sides
    assert held.mean() >= 0.15


# ------------------------------------------------------------------ Siamese network
def test_siamese_is_symmetric_and_survives_saving(tmp_path):
    import keras
    siamese, embedding, backbone = face.build_siamese(image_size=64, embedding_dim=16, weights=None)
    a, b = (np.random.default_rng(i).uniform(0, 255, (3, 64, 64, 3)).astype("float32") for i in (1, 2))
    p_ab, p_ba = siamese.predict([a, b], verbose=0), siamese.predict([b, a], verbose=0)
    np.testing.assert_allclose(p_ab, p_ba, atol=1e-6)  # swapping the two faces gives the same score
    assert np.allclose(np.linalg.norm(embedding.predict(a, verbose=0), axis=1), 1.0, atol=1e-5)  # unit length
    assert not backbone.trainable
    siamese.save(tmp_path / "s.keras")
    reloaded = keras.models.load_model(tmp_path / "s.keras")  # needs the registered AbsoluteDifference layer
    np.testing.assert_allclose(reloaded.predict([a, b], verbose=0), p_ab, atol=1e-6)


def test_make_pair_dataset_shapes():
    pairs = np.random.default_rng(0).integers(0, 255, (6, 2, 125, 94, 3), dtype=np.uint8)
    (fa, fb), y = next(iter(face.make_pair_dataset(pairs, np.array([1, 0] * 3), image_size=64, batch_size=4)))
    assert fa.shape == (4, 64, 64, 3) and fb.shape == (4, 64, 64, 3) and y.numpy().tolist() == [1, 0, 1, 0]


# ------------------------------------------------------------------ YuNet + SFace (downloaded models)
@pytest.mark.models
@MODELS
def test_detect_and_align_finds_no_face_on_a_blank_image():
    detector, recognizer = face.load_face_models()
    aligned, info = face.detect_and_align(np.full((120, 100, 3), 128, np.uint8), detector, recognizer)
    assert aligned is None and info["faces"] == 0


@MODELS
@pytest.mark.models
@pytest.mark.data
@pytest.mark.skipif(not LFW_IMAGE.exists(), reason="local LFW images not available")
def test_same_face_scores_high_and_box_is_in_original_pixels():
    detector, recognizer = face.load_face_models()
    image = np.asarray(Image.open(LFW_IMAGE).convert("RGB"))[70:195, 78:172]  # sklearn's 125x94 LFW crop
    aligned, info = face.detect_and_align(image, detector, recognizer)
    assert aligned.shape == (112, 112, 3) and info["faces"] >= 1 and info["score"] > 0.6
    x, y, w, h = info["box"]
    # roughly on the 94x125 crop; the top may lie above it, because LFW's tight crop cuts off the forehead
    assert -30 < x < 94 and -30 < y < 125 and 20 < w < 140
    e = face.embed(aligned, recognizer)
    assert e.shape == (128,) and np.linalg.norm(e) == pytest.approx(1.0, abs=1e-5)
    darker, _ = face.detect_and_align((image * 0.7).astype(np.uint8), detector, recognizer)
    assert face.compare(e, face.embed(darker, recognizer)) > 0.8  # same photo, darker: still the same person
