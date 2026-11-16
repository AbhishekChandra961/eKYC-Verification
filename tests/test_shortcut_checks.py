"""Tests for the shortcut checks of tile forgery models (Phase 3B v3): the position-matched negative control,
the edit-hidden document AUC, the compression-history (round-trip) check, and the equalised hi-res cache."""

import keras
import numpy as np
import pandas as pd
import pytest
from PIL import Image
from sklearn.metrics import roc_auc_score

from ekyc import evaluation, tiles
from ekyc.data import build_cache, estimate_jpeg_quality, jpeg_round_trip, resize_to_cache


# ------------------------------------------------------------------ matched AUC
def test_matched_auc_equals_plain_auc_with_one_stratum():
    rng = np.random.default_rng(0)
    scores, is_test = rng.random(200), rng.random(200) < 0.3
    assert evaluation.matched_auc(scores, is_test, np.zeros(200)) == pytest.approx(roc_auc_score(is_test, scores))


def test_matched_auc_extremes_and_ties():
    strata = [0, 0, 1, 1]
    assert evaluation.matched_auc([0.9, 0.1, 0.8, 0.2], [True, False, True, False], strata) == 1.0
    assert evaluation.matched_auc([0.1, 0.9, 0.2, 0.8], [True, False, True, False], strata) == 0.0
    assert evaluation.matched_auc([0.5, 0.5, 0.3, 0.3], [True, False, True, False], strata) == 0.5  # ties = 1/2


def test_matched_auc_removes_the_position_blind_spot():
    # Text areas (stratum 0) score high on every page, plain areas (stratum 1) low. Within each area, forged
    # and genuine tiles score the same, but forged pages contribute their tiles mostly from plain areas
    # (their text tiles show the edit and are excluded). The plain AUC then calls forged pages "cleaner".
    scores = [0.8, 0.8, 0.8, 0.8, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]
    is_test = [True, False, False, False, True, True, True, True, False, False]
    strata = [0, 0, 0, 0, 1, 1, 1, 1, 1, 1]
    assert roc_auc_score(is_test, scores) < 0.4
    assert evaluation.matched_auc(scores, is_test, strata) == 0.5


# ------------------------------------------------------------------ synthetic pages and tiles
def _pages_and_tiles(shift_type_b: float = 0.0):
    """2 document types x (3 genuine + 3 forged pages), 9 tiles per page (3x3 grid). The edit is tile (0, 0)
    on every forged page (label 1, score 0.99); tile (112, 0) next to it is a sliver (label -1). A clean tile
    scores 0.05 x its grid position (0 ... 0.4) on every page, so clean tiles at the same position score the
    same; forged pages of type b get `shift_type_b` added to their clean tiles (a page-level shortcut)."""
    pages = pd.DataFrame([{"doc_type": d, "label": c} for d in ("a", "b") for c in (0, 0, 0, 1, 1, 1)])
    rows = []
    for page, row in pages.iterrows():
        for position, (y, x) in enumerate([(y, x) for y in (0, 112, 224) for x in (0, 112, 224)]):
            label = 0 if row.label == 0 else {(0, 0): 1, (112, 0): -1}.get((x, y), 0)
            score = 0.99 if label == 1 else 0.05 * position
            if row.label == 1 and label == 0 and row.doc_type == "b":
                score += shift_type_b
            rows.append({"page": page, "x": x, "y": y, "label": label, "far_from_edit": x + y >= 224,
                         "score": score})
    return pages, pd.DataFrame(rows)


def test_position_matched_control_rows_and_shortcut_detection():
    pages, table = _pages_and_tiles(shift_type_b=1.0)  # type b: off-edit tiles of forged pages always higher
    control = evaluation.position_matched_control(table, pages, n_boot=50)
    assert list(control.index) == ["all types", "a", "b"]
    assert control.loc["a", "AUC"] == 0.5 and control.loc["b", "AUC"] == 1.0
    assert control.loc["all types", "AUC"] == 0.75  # both types contribute the same number of pairs
    assert control.loc["b", "forged-page tiles"] == 3 * 7 and control.loc["b", "genuine tiles"] == 3 * 9
    assert control.loc["a", "95% low"] == control.loc["a", "95% high"] == 0.5  # every resample gives 0.5
    assert (control["95% low"] <= control["AUC"]).all() and (control["AUC"] <= control["95% high"]).all()
    far = evaluation.position_matched_control(table, pages, far_only=True, n_boot=20)
    assert far.loc["a", "forged-page tiles"] == 3 * 6  # x + y >= 224: 6 of the 9 grid positions


def test_page_bootstrap_resamples_whole_pages():
    pages, table = _pages_and_tiles()
    table["page_label"] = pages["label"].to_numpy()[table["page"]]
    # every drawn page brings all of its 9 tiles, and each class keeps its page count -> always 12 pages
    low, high = evaluation.page_bootstrap_ci(table, lambda t: len(t) / 9, n_boot=30)
    assert low == high == len(pages)


def test_edit_hidden_doc_auc():
    pages, table = _pages_and_tiles()
    assert roc_auc_score(pages["label"], tiles.page_scores(table, how="max")) == 1.0  # the edit gives it away
    # hide the edit: the best remaining tile of every page is the same (0.4) -> forged look genuine
    assert evaluation.edit_hidden_doc_auc(table, pages, how="max") == 0.5
    # with a page-level shortcut on type b, its forged pages are still recognised without their edit:
    # 3 of 6 forged pages beat all 6 genuine ones, the other 3 tie -> (3 x 6 x 1 + 3 x 6 x 0.5) / 36
    pages, shifted = _pages_and_tiles(shift_type_b=1.0)
    assert evaluation.edit_hidden_doc_auc(shifted, pages, how="max") == 0.75


def test_compression_history_check():
    pages, table = _pages_and_tiles()
    same = evaluation.compression_history_check(table, pages, table["score"], threshold=0.6, how="max")
    assert same.columns.tolist() == ["as cached", "genuine re-saved"]
    assert same["as cached"].equals(same["genuine re-saved"])  # nothing changed -> identical columns
    assert same.loc["false alarms at threshold", "as cached"] == 0
    # re-saved genuine pages now score high everywhere: false alarms appear, the control drops below 0.5
    changed = evaluation.compression_history_check(table, pages, table["score"] + 0.6, threshold=0.6, how="max")
    assert changed.loc["false alarms at threshold", "genuine re-saved"] == 6
    assert changed.loc["position-matched control AUC", "genuine re-saved"] == 0.0


# ------------------------------------------------------------------ equalised compression history (data.py)
def _photo_like(path, quality=92, size=(300, 200)):
    rng = np.random.default_rng(1)
    gradient = np.linspace(0, 200, size[0])[None, :, None] + rng.integers(0, 40, (size[1], size[0], 3))
    Image.fromarray(gradient.astype("uint8")).save(path, format="JPEG", quality=quality)
    return path


def test_jpeg_round_trip_keeps_size_and_sets_quality(tmp_path):
    with Image.open(_photo_like(tmp_path / "g.jpg")) as image, jpeg_round_trip(image, 75) as saved:
        assert saved.size == image.size and saved.format == "JPEG"
        saved.save(tmp_path / "copy.jpg", quality="keep")  # "keep" re-uses the round trip's own tables
    assert estimate_jpeg_quality(tmp_path / "copy.jpg") == 75


def test_pre_quality_equals_the_manual_pipeline(tmp_path):
    src = _photo_like(tmp_path / "g.jpg")
    resize_to_cache(src, tmp_path / "pre.jpg", longest=400, quality=75, enlarge=True, pre_quality=75)
    resize_to_cache(src, tmp_path / "plain.jpg", longest=400, quality=75, enlarge=True)
    with Image.open(src) as image, jpeg_round_trip(image, 75) as saved:  # by hand: save at 300x200 first
        saved.convert("RGB").resize((400, 267), Image.Resampling.LANCZOS).save(tmp_path / "manual.jpg", quality=75)
    pre, plain, manual = (np.asarray(Image.open(tmp_path / n)) for n in ("pre.jpg", "plain.jpg", "manual.jpg"))
    assert np.array_equal(pre, manual)
    assert not np.array_equal(pre, plain)


def test_build_cache_pre_saves_only_genuine_pages(tmp_path, monkeypatch):
    from ekyc import config
    root, processed = tmp_path, tmp_path / "data" / "processed"
    interim = tmp_path / "data" / "interim"
    interim.mkdir(parents=True)
    monkeypatch.setattr(config, "PROJECT_ROOT", root)
    monkeypatch.setattr(config, "INTERIM_DIR", interim)
    monkeypatch.setattr(config, "PROCESSED_DIR", processed)
    _photo_like(interim / "real.jpg")
    _photo_like(interim / "fake.jpg")
    manifest = pd.DataFrame({"image_path": ["data/interim/real.jpg", "data/interim/fake.jpg"], "label": [0, 1]})
    for name, pre in (("eq", 75), ("plain", None)):
        build_cache(manifest, project_root=root, longest=400, quality=75, cache_dir=processed / name,
                    enlarge=True, path_column="hires_path", genuine_pre_quality=pre)
    pixels = {(d, f): np.asarray(Image.open(processed / d / f)) for d in ("eq", "plain") for f in ("real.jpg", "fake.jpg")}
    assert np.array_equal(pixels["eq", "fake.jpg"], pixels["plain", "fake.jpg"])  # forged: unchanged path
    assert not np.array_equal(pixels["eq", "real.jpg"], pixels["plain", "real.jpg"])  # genuine: pre-saved


# ------------------------------------------------------------------ scoring tiles
def _brightness_model():
    """Toy 'model': sum over the 3 channels of the mean pixel value of a tile (600 for a tile of value 200)."""
    return keras.Sequential([keras.layers.Input((224, 224, 3)), keras.layers.GlobalAveragePooling2D(),
                             keras.layers.Dense(1, use_bias=False, kernel_initializer="ones")])


def test_score_tiles_returns_scores_in_table_order(tmp_path):
    pixels = np.zeros((224, 448, 3), dtype=np.uint8)
    pixels[:, 224:] = 200  # right tile bright, left tile dark
    Image.fromarray(pixels).save(tmp_path / "p.png")  # PNG: lossless, so the pixel values are exact
    pages = pd.DataFrame({"hires_path": ["p.png"]})
    table = pd.DataFrame({"page": [0, 0], "x": [224, 0], "y": [0, 0], "label": [0, 0]})  # NOT in grid order
    scores = tiles.score_tiles(_brightness_model(), pages, table, project_root=tmp_path)
    assert scores == pytest.approx([600.0, 0.0])  # the first row is the bright tile


def test_score_genuine_from_cache_reads_the_other_copy(tmp_path, monkeypatch):
    from ekyc import config
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config, "INTERIM_DIR", tmp_path / "data" / "interim")
    other = tmp_path / "data" / "processed" / "other"
    other.mkdir(parents=True)
    for name, value in (("g1.png", 100), ("g2.png", 50)):  # the genuine pages' other copies
        Image.fromarray(np.full((224, 224, 3), value, np.uint8)).save(other / name)
    pages = pd.DataFrame({"image_path": ["data/interim/g1.png", "data/interim/f.png", "data/interim/g2.png"],
                          "label": [0, 1, 0], "hires_path": ["missing.png"] * 3})  # usual copies are never read
    table = pd.DataFrame({"page": [2, 1, 0], "x": [0, 0, 0], "y": [0, 0, 0], "label": [0, 1, 0]})
    scores = tiles.score_genuine_from_cache(_brightness_model(), pages, table, other, project_root=tmp_path)
    assert scores[0] == pytest.approx(150.0) and np.isnan(scores[1]) and scores[2] == pytest.approx(300.0)
