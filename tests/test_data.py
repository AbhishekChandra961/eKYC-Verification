"""Tests for src/ekyc/data.py: filename parsers, frame subsampling, grouping and splitting.

Run:  .venv/bin/python -m pytest
"""

import pandas as pd
import pytest

from ekyc import config
from ekyc.data import (
    UnionFind,
    assign_groups,
    evenly_spaced_indices,
    parse_clip_fake,
    parse_clip_real,
    parse_template_fake,
    parse_template_real,
    split_groups,
)


# ------------------------------------------------------------------ filename parsers
@pytest.mark.parametrize(
    "filename, doc_type, doc_id",
    [
        ("alb_id_00.jpg", "alb_id", "alb_id_00"),
        ("svk_id_99.jpg", "svk_id", "svk_id_99"),
        ("rus_internalpassport_07.jpg", "rus_internalpassport", "rus_internalpassport_07"),
    ],
)
def test_parse_template_real(filename, doc_type, doc_id):
    assert parse_template_real(filename) == {"doc_type": doc_type, "doc_id": doc_id}


@pytest.mark.parametrize(
    "filename, doc_type, fake_name, name_doc",
    [
        ("alb_id_00_fake_6_25.jpg", "alb_id", "alb_id_00_fake_6_25", "alb_id_00"),
        ("esp_id_23_fake_2_105.jpg", "esp_id", "esp_id_23_fake_2_105", "esp_id_23"),
        ("rus_internalpassport_16_fake_1_112.jpg", "rus_internalpassport",
         "rus_internalpassport_16_fake_1_112", "rus_internalpassport_16"),
    ],
)
def test_parse_template_fake(filename, doc_type, fake_name, name_doc):
    assert parse_template_fake(filename) == {"doc_type": doc_type, "fake_name": fake_name, "name_doc": name_doc}


@pytest.mark.parametrize(
    "filename, doc_type, doc_id, frame",
    [
        ("alb_id_00_frame_000001_template.jpg", "alb_id", "alb_id_00", 1),
        ("svk_id_99_frame_000373_template.jpg", "svk_id", "svk_id_99", 373),
        ("rus_internalpassport_45_frame_000127_template.jpg", "rus_internalpassport", "rus_internalpassport_45", 127),
    ],
)
def test_parse_clip_real(filename, doc_type, doc_id, frame):
    assert parse_clip_real(filename) == {"doc_type": doc_type, "doc_id": doc_id, "frame": frame}


@pytest.mark.parametrize(
    "filename, doc_type, fake_name, frame",
    [
        ("alb_id_14_fake_6_52_frame_00_dewarped.jpg", "alb_id", "alb_id_14_fake_6_52", 0),
        ("alb_id_14_fake_6_52_frame_06_dewarped.jpg", "alb_id", "alb_id_14_fake_6_52", 6),
        ("alb_id_14_fake_6_52_frame_102_dewarped.jpg", "alb_id", "alb_id_14_fake_6_52", 102),
        ("rus_internalpassport_45_fake_1_115_frame_12_dewarped.jpg", "rus_internalpassport",
         "rus_internalpassport_45_fake_1_115", 12),
    ],
)
def test_parse_clip_fake(filename, doc_type, fake_name, frame):
    parsed = parse_clip_fake(filename)
    assert (parsed["doc_type"], parsed["fake_name"], parsed["frame"]) == (doc_type, fake_name, frame)


def test_frames_parse_as_integers_so_they_sort_numerically():
    # "frame_102" must sort after "frame_12"; as text it would sort before it.
    numbers = ["102", "12", "06"]
    frames = [parse_clip_fake(f"alb_id_14_fake_6_52_frame_{n}_dewarped.jpg")["frame"] for n in numbers]
    assert sorted(frames) == [6, 12, 102]


@pytest.mark.parametrize(
    "parser, filename",
    [
        (parse_template_real, "alb_id_00.png"),  # wrong extension
        (parse_template_real, "xyz_id_00.jpg"),  # unknown document type
        (parse_template_real, "alb_id_00_fake_6_25.jpg"),  # a fake is not a real template
        (parse_template_real, "rus_00.jpg"),  # truncated type name must not match
        (parse_template_fake, "alb_id_00_fake_6.jpg"),  # missing second number
        (parse_clip_real, "alb_id_00_frame_000001_dewarped.jpg"),  # fake-clip suffix on a real clip
        (parse_clip_fake, "alb_id_14_fake_6_52_frame_00_template.jpg"),  # real-clip suffix on a fake clip
        (parse_clip_fake, "alb_id_14_fake_6_52_frame__dewarped.jpg"),  # empty frame number
    ],
)
def test_invalid_names_raise(parser, filename):
    with pytest.raises(ValueError):
        parser(filename)


def test_every_doc_type_parses():
    for doc_type in config.DOC_TYPES:
        assert parse_template_real(f"{doc_type}_42.jpg")["doc_type"] == doc_type


# ------------------------------------------------------------------ frame subsampling
@pytest.mark.parametrize("n, k", [(10, 4), (25, 8), (129, 8), (21, 20), (99, 20)])
def test_evenly_spaced_indices(n, k):
    idx = evenly_spaced_indices(n, k)
    assert len(idx) == k and len(set(idx)) == k  # exactly k, no duplicates
    assert idx[0] == 0 and idx[-1] == n - 1  # first and last frame always kept
    assert idx == sorted(idx)


def test_evenly_spaced_keeps_everything_when_short():
    assert evenly_spaced_indices(9, 20) == list(range(9))


# ------------------------------------------------------------------ grouping
def test_union_find_root_is_smallest_member():
    uf = UnionFind()
    uf.union("esp_id_94", "esp_id_23")
    uf.union("esp_id_23", "esp_id_50")
    assert {uf.find(d) for d in ["esp_id_94", "esp_id_23", "esp_id_50"]} == {"esp_id_23"}


def test_assign_groups_merges_second_src_transitively():
    table = pd.DataFrame(
        {
            "doc_id": ["esp_id_01", "esp_id_02", "esp_id_03", "esp_id_04", "esp_id_01", "esp_id_03"],
            "second_src": [None, None, None, None, "esp_id_02", "esp_id_02"],
        }
    )
    groups = assign_groups(table)
    assert set(groups[:3]) == {"esp_id_01"}  # 01-02 and 03-02 chain into one group
    assert groups[3] == "esp_id_04"  # untouched document keeps its own group


# ------------------------------------------------------------------ split
def test_split_is_by_group_stratified_and_reproducible():
    table = pd.DataFrame(
        {"group_id": [f"{t}_{i:02d}" for t in ("alb_id", "svk_id") for i in range(20)],
         "doc_type": ["alb_id"] * 20 + ["svk_id"] * 20}
    )
    first, second = split_groups(table, seed=42), split_groups(table, seed=42)
    assert first.equals(second)  # same seed -> same split
    per_type = table.assign(split=table["group_id"].map(first)).groupby(["doc_type", "split"]).size()
    for doc_type in ("alb_id", "svk_id"):  # 20 groups -> 14 / 3 / 3 within EACH type
        assert per_type[doc_type].to_dict() == {"test": 3, "train": 14, "val": 3}
