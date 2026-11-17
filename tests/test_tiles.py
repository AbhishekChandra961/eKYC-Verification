"""Tests for src/ekyc/tiles.py (Phase 3B v2): tile grid, tile labels, cropping in tf.data, page scores."""

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from ekyc import tiles
from ekyc.data import estimate_jpeg_quality, resize_to_cache


def test_grid_covers_the_page_without_padding():
    assert tiles.grid_starts(224) == [0]
    assert tiles.grid_starts(500) == [0, 112, 224, 276]  # last tile flush with the edge: 276 + 224 = 500
    assert tiles.grid_starts(448) == [0, 112, 224]
    xy = tiles.tile_grid(500, 300)
    assert len(xy) == 4 * 2 and (xy[:, 0] + 224).max() == 500 and (xy[:, 1] + 224).max() == 300
    with pytest.raises(ValueError):
        tiles.grid_starts(200)


@pytest.mark.parametrize("tile_xy, expected", [
    ((0, 0), 1),       # contains the whole box (x 100-180, y 50-80)
    ((150, 0), -1),    # only 30 px of the 80 px box: a sliver
    ((0, 70), -1),     # only 10 of the 30 px of height
    ((300, 0), 0),     # no contact
])
def test_tile_label(tile_xy, expected):
    assert tiles.tile_label(tile_xy, edit_box=(100, 50, 80, 30)) == expected


def test_long_box_needs_56_px_and_ignore_box():
    mrz = (0, 400, 1000, 30)  # a 1000 px long text line
    assert tiles.tile_label((900, 300), mrz) == 1   # 100 px of it inside the tile
    assert tiles.tile_label((960, 300), mrz) == -1  # 40 px: too little
    assert tiles.tile_label((0, 0), None, ignore_box=(10, 10, 20, 20)) == -1
    assert tiles.tile_label((0, 0), None, None) == 0


def test_tile_table_flags():
    pages = pd.DataFrame({"hires_width": [448, 448], "hires_height": [224, 224],
                          "edit_x": [np.nan, 20], "edit_y": [np.nan, 20], "edit_w": [np.nan, 60], "edit_h": [np.nan, 20],
                          **{f"ignore_{k}": [np.nan, np.nan] for k in "xywh"}})
    table = tiles.build_tile_table(pages, far_margin=112)
    assert len(table) == 2 * 3 and (table.loc[table.page == 0, "label"] == 0).all()
    forged = table[table.page == 1].set_index("x")
    assert forged.loc[0, "label"] == 1 and forged.loc[0, "overlaps_edit"]
    # box spans x 20-80: the tile at x 112 does not touch it but lies within 112 px; the tile at x 224 is far
    assert forged.loc[112, "label"] == 0 and not forged.loc[112, "far_from_edit"]
    assert forged.loc[224, "label"] == 0 and forged.loc[224, "far_from_edit"]


def test_scale_box():
    assert tiles.scale_box((100, 50, 20, 10), (2000, 1000), (1000, 500)) == (50, 25, 10, 5)


def test_tf_tiles_match_numpy_slices(tmp_path):
    rng = np.random.default_rng(0)
    page = rng.integers(0, 256, (300, 448, 3), dtype=np.uint8)
    path = tmp_path / "page.png"  # PNG: lossless, so the decoded pixels equal `page` exactly
    Image.fromarray(page).save(path)
    pages = pd.DataFrame({"hires_path": [path.name], "hires_width": [448], "hires_height": [300],
                          **{f"{p}_{k}": [np.nan] for p in ("edit", "ignore") for k in "xywh"}})
    table = tiles.build_tile_table(pages)
    # decode_jpeg also decodes PNG files, so the real pipeline can be tested on a lossless page
    batches = list(tiles.make_tile_dataset(pages, table, batch_size=4, labelled_only=False, project_root=tmp_path))
    out = np.concatenate([b.numpy() for b in batches])
    assert out.shape == (len(table), 224, 224, 3) and out.dtype == np.float32
    for i, row in enumerate(table.itertuples()):
        np.testing.assert_array_equal(out[i], page[row.y:row.y + 224, row.x:row.x + 224])


def test_training_dataset_keeps_positives_and_samples_negatives(tmp_path):
    Image.fromarray(np.zeros((448, 672, 3), np.uint8)).save(tmp_path / "p.png")
    pages = pd.DataFrame({"hires_path": ["p.png"], "hires_width": [672], "hires_height": [448],
                          "edit_x": [10.0], "edit_y": [10.0], "edit_w": [50.0], "edit_h": [20.0],
                          **{f"ignore_{k}": [np.nan] for k in "xywh"}})
    table = tiles.build_tile_table(pages)
    ds = tiles.make_tile_dataset(pages, table, batch_size=64, training=True, negatives_per_page=3, project_root=tmp_path)
    images, labels = next(iter(ds))
    assert labels.numpy().sum() == (table.label == 1).sum() and len(labels) == (table.label == 1).sum() + 3
    assert images.shape[1:] == (224, 224, 3) and float(images.numpy().max()) <= 255.0
    assert tiles.epoch_tile_counts(table, 3) == {0: 3, 1: int((table.label == 1).sum())}
    # declared length (batches per pass) must match what the pipeline really yields
    for kwargs in ({"training": True, "negatives_per_page": 3}, {}, {"labelled_only": False}):
        ds = tiles.make_tile_dataset(pages, table, batch_size=4, project_root=tmp_path, **kwargs)
        assert int(ds.cardinality()) == sum(1 for _ in ds)


def test_page_scores_and_heatmap():
    t = pd.DataFrame({"page": [0, 0, 0, 0, 1], "score": [0.1, 0.9, 0.5, 0.4, 0.2]})
    assert tiles.page_scores(t, how="max").tolist() == [0.9, 0.2]
    assert tiles.page_scores(t, how="top3").round(4).tolist() == [0.6, 0.2]
    heat = tiles.tile_heatmap(448, 224, np.array([[0, 0], [112, 0]]), np.array([0.2, 0.7]))
    assert heat[0, 0] == pytest.approx(0.2) and heat[0, 150] == pytest.approx(0.7) and heat[0, 400] == 0


def test_hires_resize_enlarges_and_reencodes(tmp_path):
    """Both small and large originals end at exactly 1280 px and JPEG quality 75 (same code path)."""
    for name, size, quality in (("small.jpg", (929, 580), 92), ("big.jpg", (2167, 1360), 75)):
        Image.new("CMYK" if quality == 92 else "RGB", size).save(tmp_path / name, quality=quality)
        resize_to_cache(tmp_path / name, tmp_path / f"out_{name}", longest=1280, quality=75, enlarge=True)
        with Image.open(tmp_path / f"out_{name}") as out:
            assert max(out.size) == 1280 and out.mode == "RGB"
        assert estimate_jpeg_quality(tmp_path / f"out_{name}") == 75
