"""Phase 2 data preparation for the SIDTD dataset.

Pipeline (each step is one function; the notebook 01_data_manifest calls them in order):
  1. build_image_table   - one row per image from the 4 sources (template/clip x real/fake)
  2. assign_groups       - union-find: a real document + all fakes and clips derived from it
  3. split_groups        - 70/15/15 train/val/test BY GROUP, stratified by document type
  4. mark_in_sample      - keep a few evenly spaced frames per clip (frames are near-duplicates)
  5. parse_ground_truth  - text-field and photo boxes from the VIA annotation files
  6. build_cache         - resized RGB JPEG copies under data/processed/images
  6b. flag_blank_frames  - marks video frames that show no document (Phase 2.1)
  7. check_leakage       - asserts that no document leaks across splits

All functions are pure (inputs -> outputs). Nothing here writes to data/raw or data/interim.
"""

from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from tqdm import tqdm  # plain text progress bar (works in terminals and in saved notebooks)

from ekyc import config

# Columns of the image table, in output order.
TABLE_COLUMNS = [
    "image_path",  # relative to the project root, e.g. data/interim/templates/Images/reals/alb_id_00.jpg
    "source",  # "template" (flat scan) or "clip" (video frame)
    "label",  # 0 = genuine, 1 = forged
    "doc_type",  # one of config.DOC_TYPES
    "doc_id",  # the REAL document the image originates from, e.g. "alb_id_00"
    "fake_name",  # forged images only, e.g. "alb_id_00_fake_6_25"
    "ctype",  # forged only: "Inpaint_and_Rewrite" or "Crop_and_Replace"
    "altered_field",  # forged only: the field that was changed, e.g. "surname"
    "second_src",  # Crop_and_Replace only: the donor document the pasted field came from
    "second_field",  # Crop_and_Replace only: the donor's field
    "frame",  # clips only: frame number within the video
]


# =============================================================== folders (case-insensitive)
def find_child_dir(parent: Path, name: str) -> Path:
    """Return the sub-folder of `parent` called `name`, ignoring upper/lower case.

    SIDTD spells folders inconsistently ("templates/Annotations" but "clips_cropped/annotations").
    macOS ignores case, so a hard-coded name would work here but break on Linux (e.g. in Docker).
    Looking the folder up returns its real on-disk spelling, so the manifest paths work everywhere.
    """
    matches = [p for p in parent.iterdir() if p.is_dir() and p.name.lower() == name.lower()]
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one folder named {name!r} in {parent}, found {matches}")
    return matches[0]


def find_dir(root: Path, *names: str) -> Path:
    """find_child_dir applied level by level, e.g. find_dir(clips, "annotations", "fakes")."""
    for name in names:
        root = find_child_dir(root, name)
    return root


def list_jpgs(folder: Path) -> list[Path]:
    """All .jpg files in a folder, sorted by name (ignores hidden files such as .DS_Store)."""
    return sorted(p for p in folder.iterdir() if p.suffix.lower() == ".jpg" and not p.name.startswith("."))


# =============================================================== filename parsers
# Document types are matched from the known list instead of splitting on "_", because every type
# name contains an underscore itself ("alb_id", "rus_internalpassport").
_TYPES = "|".join(config.DOC_TYPES)
_DOC = rf"(?P<doc_type>{_TYPES})_\d+"  # e.g. "alb_id_00"

_TEMPLATE_REAL = re.compile(rf"^(?P<doc_id>{_DOC})\.jpg$")
_TEMPLATE_FAKE = re.compile(rf"^(?P<fake_name>(?P<name_doc>{_DOC})_fake_\d+_\d+)\.jpg$")
_CLIP_REAL = re.compile(rf"^(?P<doc_id>{_DOC})_frame_(?P<frame>\d+)_template\.jpg$")
_CLIP_FAKE = re.compile(rf"^(?P<fake_name>(?P<name_doc>{_DOC})_fake_\d+_\d+)_frame_(?P<frame>\d+)_dewarped\.jpg$")


def _match(pattern: re.Pattern, filename: str, kind: str) -> dict:
    match = pattern.match(filename)
    if match is None:
        raise ValueError(f"Not a valid {kind} filename: {filename!r}")
    parts = match.groupdict()
    if "frame" in parts:
        # Frame numbers are zero-padded inconsistently ("frame_06" vs "frame_102"), so we store
        # them as integers; sorting the text would put "102" before "12".
        parts["frame"] = int(parts["frame"])
    return parts


def parse_template_real(filename: str) -> dict:
    """'alb_id_00.jpg' -> {'doc_id': 'alb_id_00', 'doc_type': 'alb_id'}"""
    return _match(_TEMPLATE_REAL, filename, "real template")


def parse_template_fake(filename: str) -> dict:
    """'alb_id_00_fake_6_25.jpg' -> {'fake_name': 'alb_id_00_fake_6_25', 'name_doc': 'alb_id_00', 'doc_type': 'alb_id'}

    `name_doc` is only the document named in the filename. It is NOT always the source document:
    for many Crop_and_Replace fakes it is the donor. The true source comes from the fake's JSON.
    """
    return _match(_TEMPLATE_FAKE, filename, "fake template")


def parse_clip_real(filename: str) -> dict:
    """'alb_id_00_frame_000001_template.jpg' -> {'doc_id': 'alb_id_00', 'doc_type': 'alb_id', 'frame': 1}"""
    return _match(_CLIP_REAL, filename, "real clip frame")


def parse_clip_fake(filename: str) -> dict:
    """'alb_id_14_fake_6_52_frame_06_dewarped.jpg' -> {'fake_name': 'alb_id_14_fake_6_52', 'name_doc': 'alb_id_14',
    'doc_type': 'alb_id', 'frame': 6}"""
    return _match(_CLIP_FAKE, filename, "fake clip frame")


def doc_type_of(doc_id: str) -> str:
    """'rus_internalpassport_16' -> 'rus_internalpassport'"""
    return parse_template_real(f"{doc_id}.jpg")["doc_type"]


# =============================================================== fake annotations
def _clean(value: str | None) -> str | None:
    """SIDTD writes missing values as the STRING "None"; turn those into a real None."""
    return None if value in (None, "", "None") else value


def _doc_id_from_image_name(name: str | None) -> str | None:
    """'alb_id_00.jpg' -> 'alb_id_00' (the JSON refers to source documents by image filename)."""
    name = _clean(name)
    return None if name is None else Path(name).stem


def read_fake_annotation(path: Path) -> dict:
    """Read one fake's JSON (template or clip) into manifest columns.

    The JSON's `src` is the real document the fake image IS (we checked by pixel comparison);
    `field` is the altered field in that document. For Crop_and_Replace, `second_src` is the donor
    document the replacement content was cut from, and `second_field` the donor's field.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {
        "doc_id": _doc_id_from_image_name(data["src"]),
        "ctype": data["ctype"],
        "altered_field": _clean(data["field"]),
        "second_src": _doc_id_from_image_name(data["second_src"]),
        "second_field": _clean(data["second_field"]),
    }


# =============================================================== 1. image table
def build_image_table(
    templates_dir: Path = config.TEMPLATES_DIR,
    clips_dir: Path = config.CLIPS_DIR,
    project_root: Path = config.PROJECT_ROOT,
) -> pd.DataFrame:
    """One row per image across all four sources, with the columns in TABLE_COLUMNS."""
    rows = []

    def rel(path: Path) -> str:
        return path.relative_to(project_root).as_posix()

    # Real templates: the filename is the document id.
    for path in list_jpgs(find_dir(templates_dir, "images", "reals")):
        info = parse_template_real(path.name)
        rows.append({"image_path": rel(path), "source": "template", "label": 0, **info})

    # Fake templates: metadata from Annotations/fakes/<fake_name>.json.
    fake_json_dir = find_dir(templates_dir, "annotations", "fakes")
    for path in list_jpgs(find_dir(templates_dir, "images", "fakes")):
        info = parse_template_fake(path.name)
        annotation = read_fake_annotation(fake_json_dir / f"{info['fake_name']}.json")
        rows.append({"image_path": rel(path), "source": "template", "label": 1,
                     "doc_type": info["doc_type"], "fake_name": info["fake_name"], **annotation})

    # Real clip frames: no annotations; the document id is in the filename.
    for path in list_jpgs(find_dir(clips_dir, "images", "reals")):
        info = parse_clip_real(path.name)
        rows.append({"image_path": rel(path), "source": "clip", "label": 0, **info})

    # Fake clip frames: one JSON per frame, annotations/fakes/<name>_frame_<n>_info.json.
    clip_json_dir = find_dir(clips_dir, "annotations", "fakes")
    for path in list_jpgs(find_dir(clips_dir, "images", "fakes")):
        info = parse_clip_fake(path.name)
        annotation = read_fake_annotation(clip_json_dir / path.name.replace("_dewarped.jpg", "_info.json"))
        rows.append({"image_path": rel(path), "source": "clip", "label": 1, "doc_type": info["doc_type"],
                     "fake_name": info["fake_name"], "frame": info["frame"], **annotation})

    table = pd.DataFrame(rows).reindex(columns=TABLE_COLUMNS)
    table["frame"] = table["frame"].astype("Int64")  # integer column that allows "missing" for templates
    return table


def match_clip_fakes_to_templates(table: pd.DataFrame) -> dict:
    """Do clip fakes have a template fake of the same name, with identical metadata?"""
    meta = ["doc_id", "ctype", "altered_field", "second_src", "second_field"]
    fakes = table[table["label"] == 1]
    per_name = {src: df.drop_duplicates("fake_name").set_index("fake_name")[meta]
                for src, df in fakes.groupby("source")}
    clip, template = per_name["clip"], per_name["template"]
    matched = clip.index.intersection(template.index)
    # Compare metadata of matched names (fillna so that None == None counts as equal).
    differs = (clip.loc[matched].fillna("-") != template.loc[matched].fillna("-")).any(axis=1)
    return {
        "clip_fake_docs": len(clip),
        "matching_template_fake": len(matched),
        "without_template_match": sorted(clip.index.difference(template.index)),
        "matched_but_metadata_differs": sorted(matched[differs.to_numpy()]),
    }


def fake_name_prefix_mismatches(table: pd.DataFrame) -> pd.DataFrame:
    """Template fakes whose filename names a different document than their JSON `src`."""
    fakes = table[(table["label"] == 1) & (table["source"] == "template")].copy()
    fakes["name_doc"] = fakes["fake_name"].str.split("_fake_").str[0]
    fakes["name_doc_is"] = np.where(fakes["name_doc"] == fakes["doc_id"], "src",
                                    np.where(fakes["name_doc"] == fakes["second_src"], "second_src", "neither"))
    return fakes.loc[fakes["name_doc_is"] != "src", ["fake_name", "ctype", "doc_id", "second_src", "name_doc_is"]]


def mean_abs_difference(path_a: Path, path_b: Path, size: tuple[int, int] = (256, 160)) -> float:
    """Mean absolute grey-level difference (0-255) of two images after shrinking both to `size`.
    Near 0 = the same picture (apart from small local edits); large = different pictures.
    """
    def small_grey(path: Path) -> np.ndarray:
        with Image.open(path) as image:
            image.draft("L", size)  # fast reduced-size JPEG decode
            return np.asarray(image.convert("L").resize(size), dtype=np.float32)

    return float(np.abs(small_grey(path_a) - small_grey(path_b)).mean())


def image_mode(path: Path) -> str:
    """Colour mode of an image ("RGB", "CMYK", ...), read from the file header only."""
    with Image.open(path) as image:
        return image.mode


def image_mode_counts(table: pd.DataFrame, project_root: Path = config.PROJECT_ROOT) -> pd.DataFrame:
    """Number of template images per colour mode, by label and document type."""
    templates = table[table["source"] == "template"]
    modes = [image_mode(project_root / p) for p in templates["image_path"]]
    return (templates.assign(mode=modes)
            .groupby(["label", "doc_type", "mode"]).size().unstack("mode", fill_value=0))


# =============================================================== 2. grouping
class UnionFind:
    """Tracks which documents belong together. union(a, b) merges the groups of a and b.

    Each group is represented by its alphabetically smallest document id, so group ids are
    deterministic and readable (e.g. "esp_id_23").
    """

    def __init__(self):
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        root = x
        while self.parent[root] != root:  # walk up to the group's representative
            root = self.parent[root]
        while self.parent[x] != root:  # path compression: point everything on the way at the root
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            # The smaller id becomes the root, so the root is always the group's smallest member.
            self.parent[max(root_a, root_b)] = min(root_a, root_b)


def assign_groups(table: pd.DataFrame) -> pd.Series:
    """group_id for every row. A group = a real document, every fake made from it, and every clip
    frame of either. A Crop_and_Replace fake also involves its donor (second_src), so the two
    documents are merged into one group: both appear in that fake image.
    """
    uf = UnionFind()
    for doc_id in table["doc_id"].unique():
        uf.find(doc_id)
    pairs = table.loc[table["second_src"].notna() & (table["second_src"] != table["doc_id"]), ["doc_id", "second_src"]]
    for doc_id, second_src in pairs.drop_duplicates().itertuples(index=False):
        uf.union(doc_id, second_src)
    return table["doc_id"].map(uf.find).rename("group_id")


def groups_spanning_doc_types(table: pd.DataFrame) -> pd.Series:
    """Groups whose member documents have more than one document type (should be empty)."""
    members = pd.concat([table[["group_id", "doc_id"]],
                         table.loc[table["second_src"].notna(), ["group_id", "second_src"]]
                         .rename(columns={"second_src": "doc_id"})])
    types = members.drop_duplicates().assign(doc_type=lambda d: d["doc_id"].map(doc_type_of))
    n_types = types.groupby("group_id")["doc_type"].nunique()
    return n_types[n_types > 1]


# =============================================================== 3. split
def split_groups(table: pd.DataFrame, ratios: dict = config.SPLIT_RATIOS, seed: int = config.SEED) -> pd.Series:
    """Assign each group to train/val/test, separately within each document type.

    Splitting whole groups (not images) keeps a document, its fakes and its video frames together,
    so the model is never tested on a document it saw during training. Doing it per document type
    gives every split the same mix of types (stratification).
    Returns a Series: index = group_id, value = split name.
    """
    group_type = table.groupby("group_id")["doc_type"].first()
    rng = np.random.default_rng(seed)
    split_of = {}
    for doc_type in sorted(group_type.unique()):
        groups = rng.permutation(np.array(sorted(group_type.index[group_type == doc_type])))
        n_train = round(len(groups) * ratios["train"])
        n_val = round(len(groups) * ratios["val"])
        for i, group in enumerate(groups):  # the remaining groups (about 15%) go to test
            split_of[group] = "train" if i < n_train else ("val" if i < n_train + n_val else "test")
    return pd.Series(split_of, name="split").rename_axis("group_id")


# =============================================================== 4. clip-frame subsampling
def evenly_spaced_indices(n: int, k: int) -> list[int]:
    """Positions of k items spread evenly over 0..n-1, always including the first and last.
    Returns all n positions if n <= k. Example: evenly_spaced_indices(10, 4) -> [0, 3, 6, 9]
    """
    if n <= k:
        return list(range(n))
    positions = np.linspace(0, n - 1, k)
    # floor(x + 0.5) rounds halves up; with spacing > 1 this can never produce duplicates.
    return np.floor(positions + 0.5).astype(int).tolist()


def mark_in_sample(table: pd.DataFrame, max_real: int = config.MAX_REAL_FRAMES,
                   max_fake: int = config.MAX_FAKE_FRAMES) -> pd.Series:
    """True for rows used in training. Templates: always. Clip frames: up to max_real frames per
    real document and max_fake per fake, evenly spaced through the video so that different
    viewing angles are kept (taking consecutive frames would give near-identical images).
    """
    in_sample = pd.Series(table["source"] == "template", index=table.index, name="in_sample")
    clips = table[table["source"] == "clip"]
    # One "clip document" = all frames of one real document, or all frames of one fake.
    clip_doc = clips["fake_name"].where(clips["label"] == 1, clips["doc_id"])
    for _, frames in clips.groupby(clip_doc):
        limit = max_fake if frames["label"].iat[0] == 1 else max_real
        ordered = frames.sort_values("frame")
        keep = ordered.index[evenly_spaced_indices(len(ordered), limit)]
        in_sample.loc[keep] = True
    return in_sample


# =============================================================== 5. ground-truth fields
def parse_ground_truth(annotations_dir: Path | None = None) -> pd.DataFrame:
    """Text-field and photo boxes of the real templates, one row per annotated region:
    doc_id, field_name, value, x, y, w, h (pixels in the original template image).

    The VIA files key images by short name + file size ("00.jpg1859173", filename "00.jpg"), so
    the document type (from the JSON's own filename) is added in front: "alb_id_00".
    """
    if annotations_dir is None:
        annotations_dir = find_dir(config.TEMPLATES_DIR, "annotations", "reals")
    rows = []
    for path in sorted(annotations_dir.glob("*.json")):
        doc_type = path.stem
        if doc_type not in config.DOC_TYPES:
            raise ValueError(f"Unexpected annotation file {path.name}")
        with open(path, encoding="utf-8") as f:
            images = json.load(f)["_via_img_metadata"]
        for entry in images.values():
            doc_id = f"{doc_type}_{Path(entry['filename']).stem}"
            for region in entry["regions"]:
                shape, attrs = region["shape_attributes"], region["region_attributes"]
                if shape["name"] != "rect":
                    raise ValueError(f"{doc_id}: only rectangle boxes are supported, got {shape['name']}")
                rows.append({"doc_id": doc_id, "field_name": attrs.get("field_name"), "value": attrs.get("value"),
                             "x": shape["x"], "y": shape["y"], "w": shape["width"], "h": shape["height"]})
    return pd.DataFrame(rows)


# =============================================================== 6. resized image cache
def cache_path_for(image_path: str, cache_dir: Path = config.CACHE_DIR) -> str:
    """Mirror data/interim/... under `cache_dir` (default data/processed/images/...), relative to the project root."""
    interim = config.INTERIM_DIR.relative_to(config.PROJECT_ROOT)
    cache = cache_dir.relative_to(config.PROJECT_ROOT)
    return (cache / Path(image_path).relative_to(interim)).as_posix()


def jpeg_round_trip(image: Image.Image, quality: int) -> Image.Image:
    """Save `image` as an RGB JPEG at `quality` in memory and open the result again (same size).
    The returned image carries the traces of that save, exactly as if it had been stored that way on disk.
    Close it after use (or use it in a `with` block)."""
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    return Image.open(buffer)


def _shrink(image: Image.Image, new_size: tuple[int, int]) -> Image.Image:
    """Decode an opened JPEG and resize it to new_size as RGB (the common path of every cached image)."""
    # draft(): the JPEG decoder can decode directly at 1/2, 1/4 or 1/8 size. It picks the
    # smallest of those that is still >= new_size, which is faster and needs much less RAM.
    image.draft(image.mode, new_size)
    # convert("RGB"): half of the genuine templates are CMYK JPEGs, all fakes are RGB.
    # Converting everything to RGB removes a colour-format difference a model could exploit.
    return image.convert("RGB").resize(new_size, Image.Resampling.LANCZOS)


def resize_to_cache(src: Path, dst: Path, longest: int = config.RESIZE_LONGEST,
                    quality: int = config.JPEG_QUALITY, enlarge: bool = False,
                    pre_quality: int | None = None) -> tuple[int, int]:
    """Save a copy of `src` resized so its longest side is `longest` px, as an RGB JPEG.
    enlarge=False: images already smaller than `longest` keep their size (512 px cache);
    enlarge=True : every image ends up with exactly `longest` px (hi-res cache of Phase 3B v2).
    pre_quality  : if given, the image is first saved as a JPEG at this quality at its ORIGINAL size and
                   continues from that copy (Phase 3B v3: gives genuine templates the forged ones' history).
    Skips the work if `dst` already exists (so an interrupted run can resume).
    Returns the ORIGINAL (width, height), needed later to scale annotation boxes to the cache.
    """
    with Image.open(src) as image:
        original_size = image.size  # read from the file header; no pixels decoded yet
        if dst.exists():
            return original_size
        scale = longest / max(original_size)
        if not enlarge:
            scale = min(1.0, scale)
        new_size = (max(1, round(original_size[0] * scale)), max(1, round(original_size[1] * scale)))
        if pre_quality is None:
            small = _shrink(image, new_size)
        else:
            with jpeg_round_trip(image, pre_quality) as saved:  # full-size save, then the same path as above
                small = _shrink(saved, new_size)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")  # write-then-rename: a crash never leaves a half-written file
    small.save(tmp, format="JPEG", quality=quality)
    os.replace(tmp, dst)
    return original_size


def build_cache(manifest: pd.DataFrame, project_root: Path = config.PROJECT_ROOT,
                longest: int = config.RESIZE_LONGEST, quality: int = config.JPEG_QUALITY,
                cache_dir: Path = config.CACHE_DIR, enlarge: bool = False,
                path_column: str = "cache_path",
                genuine_pre_quality: int | None = None) -> tuple[pd.DataFrame, int]:
    """Resize every manifest image into `cache_dir`, one image at a time (low memory). Every image goes
    through exactly the same code path, whatever its class.
    genuine_pre_quality: if given, genuine images (label 0) first get a JPEG save at this quality at their
    original size (see resize_to_cache). This is the one class-dependent step, and it exists to make the
    classes' histories EQUAL: the forged templates were already saved that way when they were made.
    Returns (manifest with `path_column`, orig_width, orig_height columns; number of files written).
    """
    processed = config.PROCESSED_DIR.resolve()
    cache_paths, widths, heights, written = [], [], [], 0
    rows = zip(manifest["image_path"], manifest["label"])
    for image_path, label in tqdm(rows, total=len(manifest), desc="resizing", unit="img", mininterval=5):
        cache_path = cache_path_for(image_path, cache_dir)
        dst = project_root / cache_path
        if not dst.resolve().is_relative_to(processed):  # safety net: only ever write to data/processed
            raise RuntimeError(f"Refusing to write outside data/processed: {dst}")
        existed = dst.exists()
        pre_quality = genuine_pre_quality if label == 0 else None
        width, height = resize_to_cache(project_root / image_path, dst, longest, quality, enlarge, pre_quality)
        written += not existed
        cache_paths.append(cache_path)
        widths.append(width)
        heights.append(height)
    return manifest.assign(**{path_column: cache_paths}, orig_width=widths, orig_height=heights), written


# =============================================================== 6c. file-format checks (Phase 3B)
# The JPEG standard's example luminance quantisation table (used by libjpeg, and so by Pillow).
# A JPEG saved at quality q stores this table scaled by a factor that depends on q, so comparing a
# file's stored table with the scaled standard tables tells us which quality it was saved at.
_STANDARD_LUMA_TABLE = np.array([
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
])


def standard_luma_table(quality: int) -> np.ndarray:
    """The 64 luminance quantisation steps libjpeg writes for `quality` (1-100), same integer maths."""
    scale = 5000 // quality if quality < 50 else 200 - 2 * quality
    return np.clip((_STANDARD_LUMA_TABLE * scale + 50) // 100, 1, 255)


def estimate_jpeg_quality(path: Path) -> int | None:
    """Estimated JPEG quality (1-100) a file was saved at; None if the file is not a JPEG.
    The stored luminance table is compared with the standard table at every quality; both are sorted
    first, so the order in which the 64 values are stored does not matter. Larger steps = coarser
    compression = lower quality."""
    with Image.open(path) as image:
        tables = getattr(image, "quantization", None)  # read from the file header; PNG files have none
    if not tables:
        return None
    observed = np.sort(np.asarray(tables[0]))
    errors = [np.abs(np.sort(standard_luma_table(q)) - observed).sum() for q in range(1, 101)]
    return int(np.argmin(errors)) + 1


def image_format(path: Path) -> str:
    """Real file format ("JPEG", "PNG", ...) from the file's content, not its extension."""
    with Image.open(path) as image:
        return image.format


# =============================================================== 6b. blank video frames (Phase 2.1)
def blank_frame_stats(path: Path) -> tuple[float, float]:
    """(grey-level standard deviation, share of near-black pixels) of a tiny greyscale thumbnail.
    The 64x40 thumbnail averages away JPEG noise and makes the check fast."""
    with Image.open(path) as image:
        image.draft("L", (64, 64))  # fast reduced-size greyscale JPEG decode
        grey = np.asarray(image.convert("L").resize(config.BLANK_THUMBNAIL), dtype=np.float32)
    return float(grey.std()), float((grey < config.BLANK_DARK_LEVEL).mean())


def is_blank(pixel_std, dark_share):
    """The rule from config: an (almost) flat colour, or mostly black. Works on numbers or arrays."""
    return (pixel_std < config.BLANK_STD_MAX) | (dark_share > config.BLANK_DARK_SHARE_MIN)


def flag_blank_frames(manifest: pd.DataFrame, project_root: Path = config.PROJECT_ROOT) -> pd.DataFrame:
    """pixel_std, dark_share and is_empty for every row, measured on its cached image."""
    stats = [blank_frame_stats(project_root / p) for p in tqdm(manifest["cache_path"], desc="blank check",
                                                               unit="img", mininterval=5)]
    out = pd.DataFrame(stats, columns=["pixel_std", "dark_share"], index=manifest.index)
    out["is_empty"] = is_blank(out["pixel_std"], out["dark_share"])
    return out


def assert_splits_unchanged(previous: pd.DataFrame, current: pd.DataFrame) -> int:
    """Raise AssertionError if any image was added, removed or moved to another split compared with
    `previous` (e.g. the manifest saved by an earlier run). Returns the number of rows compared."""
    before = previous.set_index("image_path")["split"]
    after = current.set_index("image_path")["split"]
    assert set(before.index) == set(after.index), (
        f"image set changed: {len(set(before.index) - set(after.index))} removed, "
        f"{len(set(after.index) - set(before.index))} added")
    moved = before[before != after.loc[before.index]]
    assert moved.empty, f"{len(moved)} images changed split, e.g. {list(moved.index[:3])}"
    return len(before)


# =============================================================== 7. leakage checks
def check_leakage(manifest_full: pd.DataFrame, manifest: pd.DataFrame,
                  project_root: Path = config.PROJECT_ROOT) -> list[str]:
    """Assert the split is leakage-safe and all files exist. Raises AssertionError on any failure.
    Returns the list of checks that passed (for display).
    """
    passed = []

    assert manifest_full["split"].notna().all(), "some rows have no split"
    assert not manifest_full["image_path"].duplicated().any(), "duplicate image_path rows"
    passed.append("every row has a split, and no image appears twice")

    splits_per_group = manifest_full.groupby("group_id")["split"].nunique()
    leaking = splits_per_group[splits_per_group > 1]
    assert leaking.empty, f"{len(leaking)} groups appear in more than one split, e.g. {list(leaking.index[:5])}"
    passed.append("no group_id appears in more than one split")

    real_templates = manifest_full[(manifest_full["label"] == 0) & (manifest_full["source"] == "template")]
    split_of_doc = real_templates.set_index("doc_id")["split"]
    fakes = manifest_full[manifest_full["label"] == 1]
    bad_src = fakes[fakes["split"] != fakes["doc_id"].map(split_of_doc)]
    assert bad_src.empty, f"{len(bad_src)} fakes are in a different split than their src document"
    donors = fakes[fakes["second_src"].notna()]
    bad_donor = donors[donors["split"] != donors["second_src"].map(split_of_doc)]
    assert bad_donor.empty, f"{len(bad_donor)} fakes are in a different split than their second_src document"
    passed.append("every fake is in the same split as its src document (and its second_src)")

    missing_images = [p for p in manifest_full["image_path"] if not (project_root / p).exists()]
    assert not missing_images, f"{len(missing_images)} image_path files missing, e.g. {missing_images[:3]}"
    missing_cache = [p for p in manifest["cache_path"] if not (project_root / p).exists()]
    assert not missing_cache, f"{len(missing_cache)} cache_path files missing, e.g. {missing_cache[:3]}"
    passed.append(f"all {len(manifest_full):,} image_path files and {len(manifest):,} cache_path files exist")

    test_types = set(manifest.loc[manifest["split"] == "test", "doc_type"])
    missing_types = sorted(set(config.DOC_TYPES) - test_types)
    assert not missing_types, f"test split is missing document types {missing_types}"
    passed.append(f"test split contains all {len(config.DOC_TYPES)} document types")

    return passed
