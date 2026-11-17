"""Phase 3B v2/v3: tile-based forgery detection on high-resolution templates.

Why tiles: an edited field covers a tiny part of the page (median about 0.4 % of its area). A whole-page model
must shrink the page and average over all of it, which hides the edit (the v1 models never looked at it).
Here every page (longest side 1280 px) is cut into overlapping 224 x 224 tiles with a stride of 112 px, so each
point of the page lies in up to four tiles and the model sees the edit at full resolution. The model scores
tiles; a page's score is the highest tile score (or the mean of its 3 highest; chosen on validation).

Tile labels, from the annotated box of the altered field rescaled to the hi-res page:
   1  the tile shows a substantial part of the edit: at least half of the field box's height and at least
      min(half the box's width, 56 px) of its length (56 px = a few characters);
   0  the tile does not touch the edit at all (every tile of a genuine page is 0);
  -1  "ignore": the tile touches the edit only partly (a sliver), or touches the donor-field box of a
      Crop_and_Replace page. Ignored tiles are left out of training and of tile-level metrics, but they are
      scored like all others when a whole page is judged.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf

from ekyc import config
from ekyc.data import cache_path_for

AUTOTUNE = tf.data.AUTOTUNE
MIN_RUN = 56  # px of a text line a positive tile must contain (if the box is longer than 2 x this)


# =============================================================== geometry and labels (pure Python / NumPy)
def grid_starts(length: int, tile: int = config.TILE_SIZE, stride: int = config.TILE_STRIDE) -> list[int]:
    """Tile start positions along one side: 0, stride, 2*stride, ... plus one last tile flush with the far
    edge, so the whole side is covered without padding."""
    if length < tile:
        raise ValueError(f"page side {length} px is shorter than one tile ({tile} px)")
    starts = list(range(0, length - tile + 1, stride))
    if starts[-1] != length - tile:
        starts.append(length - tile)
    return starts


def tile_grid(width: int, height: int, tile: int = config.TILE_SIZE,
              stride: int = config.TILE_STRIDE) -> np.ndarray:
    """(x, y) top-left corners of all tiles of a page, row by row. Shape (n_tiles, 2)."""
    return np.array([(x, y) for y in grid_starts(height, tile, stride) for x in grid_starts(width, tile, stride)])


def overlap(tile_xy, box_xywh, tile: int = config.TILE_SIZE) -> tuple[float, float]:
    """Width and height of the intersection of a tile and a box (0 if they do not touch)."""
    x, y = tile_xy
    bx, by, bw, bh = box_xywh
    ix = max(0.0, min(x + tile, bx + bw) - max(x, bx))
    iy = max(0.0, min(y + tile, by + bh) - max(y, by))
    return ix, iy


def tile_label(tile_xy, edit_box=None, ignore_box=None, tile: int = config.TILE_SIZE) -> int:
    """1 / 0 / -1 label of one tile (see the module docstring). Boxes are (x, y, w, h) or None."""
    if edit_box is not None:
        ix, iy = overlap(tile_xy, edit_box, tile)
        if ix > 0 and iy > 0:
            _, _, bw, bh = edit_box
            substantial = iy >= 0.5 * min(bh, tile) and ix >= min(0.5 * bw, MIN_RUN)
            return 1 if substantial else -1
    if ignore_box is not None:
        ix, iy = overlap(tile_xy, ignore_box, tile)
        if ix > 0 and iy > 0:
            return -1
    return 0


def scale_box(box_xywh, from_size: tuple[int, int], to_size: tuple[int, int]) -> tuple[float, ...]:
    """Rescale an (x, y, w, h) box from an image of size from_size=(w, h) to one of size to_size."""
    sx, sy = to_size[0] / from_size[0], to_size[1] / from_size[1]
    x, y, w, h = box_xywh
    return x * sx, y * sy, w * sx, h * sy


def _box(row, prefix: str):
    """(x, y, w, h) from columns prefix_x, prefix_y, ... of a page row, or None if missing."""
    values = [getattr(row, f"{prefix}_{k}") for k in "xywh"]
    return None if pd.isna(values[0]) else tuple(values)


def build_pages_table(templates: pd.DataFrame, fields_gt: pd.DataFrame,
                      project_root: Path = config.PROJECT_ROOT) -> pd.DataFrame:
    """One row per template page, with its hi-res size and the boxes in hi-res pixels.

    `templates`: manifest rows of templates with hires_path, orig_width, orig_height (data.build_cache).
    edit box   = the annotated box of the altered field in the source document (forged pages only). A pixel
                 comparison of forged pages with their source pages showed the change is inside this box.
    ignore box = Crop_and_Replace pages whose donor field (second_field) differs from the altered field: the
                 box of second_field on the page. That comparison showed no edit there (second_field names
                 the field in the donor document), so these tiles are neither forged nor clean examples.
    """
    from PIL import Image  # local import: only needed here

    boxes = fields_gt.dropna(subset=["field_name"]).set_index(["doc_id", "field_name"])[["x", "y", "w", "h"]]
    sizes = []
    for path in templates["hires_path"]:
        with Image.open(project_root / path) as image:  # header only
            sizes.append(image.size)
    pages = templates.reset_index(drop=True).assign(hires_width=[s[0] for s in sizes],
                                                    hires_height=[s[1] for s in sizes])
    edit, ignore = [], []
    for row in pages.itertuples(index=False):
        orig, hires = (row.orig_width, row.orig_height), (row.hires_width, row.hires_height)
        if row.label == 1:
            edit.append(scale_box(boxes.loc[(row.doc_id, row.altered_field)], orig, hires))
        else:
            edit.append((np.nan,) * 4)
        donor_elsewhere = (row.ctype == "Crop_and_Replace" and isinstance(row.second_field, str)
                           and row.second_field != row.altered_field)
        ignore.append(scale_box(boxes.loc[(row.doc_id, row.second_field)], orig, hires) if donor_elsewhere
                      else (np.nan,) * 4)
    for prefix, values in (("edit", edit), ("ignore", ignore)):
        for k, column in zip("xywh", np.array(values, dtype=float).T):
            pages[f"{prefix}_{k}"] = column
    return pages


def build_tile_table(pages: pd.DataFrame, tile: int = config.TILE_SIZE, stride: int = config.TILE_STRIDE,
                     far_margin: int = config.TILE_STRIDE) -> pd.DataFrame:
    """One row per tile of every page, in page order then row-major order.

    `pages` needs hires_width, hires_height and edit_x/y/w/h, ignore_x/y/w/h (hi-res px; NaN when absent).
    Columns: page (position of the page in `pages`), x, y, label (1/0/-1),
             overlaps_edit (touches the edit box at all; used for localisation),
             far_from_edit (no contact even with the edit box grown by `far_margin` px on every side).
    """
    rows = []
    for page, row in enumerate(pages.itertuples(index=False)):
        edit, ignore = _box(row, "edit"), _box(row, "ignore")
        grown = None if edit is None else (edit[0] - far_margin, edit[1] - far_margin,
                                           edit[2] + 2 * far_margin, edit[3] + 2 * far_margin)
        for x, y in tile_grid(int(row.hires_width), int(row.hires_height), tile, stride):
            touches = edit is not None and min(overlap((x, y), edit, tile)) > 0
            near = grown is not None and min(overlap((x, y), grown, tile)) > 0
            rows.append((page, int(x), int(y), tile_label((x, y), edit, ignore, tile), touches, not near))
    return pd.DataFrame(rows, columns=["page", "x", "y", "label", "overlaps_edit", "far_from_edit"])


# =============================================================== tf.data pipelines
def crop_tiles(page: tf.Tensor, xy: tf.Tensor, tile: int = config.TILE_SIZE) -> tf.Tensor:
    """Cut tiles out of one decoded page (H, W, 3) at the (x, y) corners `xy` (n, 2). Returns (n, tile, tile, 3)."""
    return tf.map_fn(lambda p: tf.slice(page, tf.stack([p[1], p[0], 0]), [tile, tile, 3]), xy,
                     fn_output_signature=tf.TensorSpec((tile, tile, 3), page.dtype))


def augment_tile(tile: tf.Tensor, label: tf.Tensor):
    """Training-time augmentation of one uint8 tile: random JPEG re-encoding at quality 60-95 (so the model
    cannot rely on compression traces), small brightness and contrast changes. No flips: mirrored text does
    not occur on real documents. Returns float32 pixels 0-255."""
    tile = tf.image.random_jpeg_quality(tile, 60, 95)
    tile = tf.cast(tile, tf.float32)
    tile = tf.image.random_brightness(tile, 20.0)  # +- 20 grey levels
    tile = tf.image.random_contrast(tile, 0.85, 1.15)
    return tf.clip_by_value(tile, 0.0, 255.0), label


def make_tile_dataset(pages: pd.DataFrame, tiles: pd.DataFrame, batch_size: int = 32, training: bool = False,
                      negatives_per_page: int | None = None, labelled_only: bool = True,
                      project_root: Path = config.PROJECT_ROOT, tile: int = config.TILE_SIZE,
                      shuffle_buffer: int = 2048) -> tf.data.Dataset:
    """Tiles cut on the fly from the hi-res pages (no tile is ever written to disk).

    Each page is decoded once and all its tiles are cut from it.
    training=True : every epoch, each page contributes all its label-1 tiles plus `negatives_per_page` randomly
                    chosen label-0 tiles; pages and tiles are shuffled and tiles augmented. Yields (tile, label).
    training=False: tiles in table order, no augmentation. labelled_only=True keeps labels 0/1 and yields
                    (tile, label) for tile-level metrics; labelled_only=False yields every tile (including -1)
                    without labels, for page-level scoring.
    Tiles are float32 with raw 0-255 pixels (EfficientNet rescales internally).
    """
    tiles = tiles.sort_values(["page", "y", "x"], kind="stable")  # the order build_tile_table produces
    counts = tiles.groupby("page").size().reindex(range(len(pages)), fill_value=0).to_numpy()
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    all_xy = tf.constant(tiles[["x", "y"]].to_numpy(np.int32))
    all_labels = tf.constant(tiles["label"].to_numpy(np.int32))
    paths = [str(project_root / p) for p in pages["hires_path"]]

    def load(path, start, count):
        page = tf.io.decode_jpeg(tf.io.read_file(path), channels=3)
        xy, labels = all_xy[start:start + count], all_labels[start:start + count]
        if training:
            positives = tf.where(labels == 1)[:, 0]
            negatives = tf.random.shuffle(tf.where(labels == 0)[:, 0])[:negatives_per_page]
            keep = tf.concat([positives, negatives], axis=0)
        elif labelled_only:
            keep = tf.where(labels >= 0)[:, 0]
        else:
            keep = tf.range(count, dtype=tf.int64)
        xy, labels = tf.gather(xy, keep), tf.gather(labels, keep)
        return crop_tiles(page, xy, tile), tf.cast(labels, tf.float32)

    ds = tf.data.Dataset.from_tensor_slices((paths, starts.astype(np.int32), counts.astype(np.int32)))
    if training:
        ds = ds.shuffle(len(paths), reshuffle_each_iteration=True)
    ds = ds.map(load, num_parallel_calls=AUTOTUNE, deterministic=not training).unbatch()
    if training:
        ds = ds.shuffle(shuffle_buffer, reshuffle_each_iteration=True)  # mixes tiles of different pages
        ds = ds.map(augment_tile, num_parallel_calls=AUTOTUNE)
    else:
        ds = ds.map(lambda t, y: (tf.cast(t, tf.float32), y), num_parallel_calls=AUTOTUNE)
        if not labelled_only:
            ds = ds.map(lambda t, y: t)
    # The number of tiles per pass is known in advance; declaring it lets Keras show real step counts (and
    # avoids its "input ran out of data" warning for datasets of unknown length).
    if training:
        n_tiles = sum(epoch_tile_counts(tiles, negatives_per_page).values())
    else:
        n_tiles = int((tiles["label"] >= 0).sum()) if labelled_only else len(tiles)
    n_batches = -(-n_tiles // batch_size)  # ceiling division
    return ds.batch(batch_size).apply(tf.data.experimental.assert_cardinality(n_batches)).prefetch(AUTOTUNE)


def epoch_tile_counts(tiles: pd.DataFrame, negatives_per_page: int | None) -> dict[int, int]:
    """Number of label-0 and label-1 tiles seen per training epoch (for class weights): every label-1 tile,
    plus up to `negatives_per_page` label-0 tiles of each page (all of them if None)."""
    negatives = tiles[tiles["label"] == 0].groupby("page").size().clip(upper=negatives_per_page).sum()
    return {0: int(negatives), 1: int((tiles["label"] == 1).sum())}


# =============================================================== page-level scoring and checks
def score_tiles(model, pages: pd.DataFrame, tiles: pd.DataFrame, batch_size: int = 64,
                project_root: Path = config.PROJECT_ROOT) -> np.ndarray:
    """Model score of every tile in `tiles` (all labels, including -1), returned in the row order of `tiles`.
    `pages` gives the image of each page (hires_path), so the same tile table can be scored on other copies
    of the pages, e.g. the same pages after a different compression history."""
    ordered = tiles.sort_values(["page", "y", "x"], kind="stable")  # the order make_tile_dataset yields
    ds = make_tile_dataset(pages, ordered, batch_size, labelled_only=False, project_root=project_root)
    scores = model.predict(ds, verbose=0)[:, 0]
    if len(scores) != len(tiles):
        raise RuntimeError(f"scored {len(scores)} tiles, expected {len(tiles)}")
    return pd.Series(scores, index=ordered.index).reindex(tiles.index).to_numpy()


def score_genuine_from_cache(model, pages: pd.DataFrame, tiles: pd.DataFrame, cache_dir: Path,
                             batch_size: int = 64, project_root: Path = config.PROJECT_ROOT) -> np.ndarray:
    """Tile scores of the GENUINE pages, with their images read from another cache folder: the same pages
    stored with a different compression history (data/processed/hires_q75 = their original history,
    hires_q75_eq = with the forged pages' extra quality-75 save). Same tiles, same model.
    Aligned with `tiles`; NaN for tiles of forged pages. Input of evaluation.compression_history_check."""
    genuine = np.flatnonzero(pages["label"].to_numpy() == 0)  # positions of genuine pages in `pages`
    other_pages = pages.iloc[genuine].reset_index(drop=True)
    other_pages["hires_path"] = [cache_path_for(p, cache_dir) for p in other_pages["image_path"]]
    rows = tiles["page"].isin(genuine).to_numpy()
    new_position = pd.Series(np.arange(len(genuine)), index=genuine)
    other_tiles = tiles[rows].assign(page=new_position[tiles.loc[rows, "page"]].to_numpy())
    scores = np.full(len(tiles), np.nan)
    scores[rows] = score_tiles(model, other_pages, other_tiles, batch_size, project_root)
    return scores


def page_scores(tiles: pd.DataFrame, score_column: str = "score", how: str = "max") -> pd.Series:
    """Page score from its tile scores: "max" = the highest tile, "top3" = mean of the 3 highest tiles."""
    grouped = tiles.groupby("page")[score_column]
    if how == "max":
        return grouped.max()
    if how == "top3":
        return grouped.apply(lambda s: s.nlargest(3).mean())
    raise ValueError(how)


def tile_heatmap(width: int, height: int, xy: np.ndarray, scores: np.ndarray,
                 tile: int = config.TILE_SIZE) -> np.ndarray:
    """(height, width) map: each pixel gets the highest score of the tiles that contain it."""
    heat = np.zeros((height, width), dtype=np.float32)
    for (x, y), score in zip(xy, scores):
        np.maximum(heat[y:y + tile, x:x + tile], score, out=heat[y:y + tile, x:x + tile])
    return heat
