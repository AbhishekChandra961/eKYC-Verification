"""The demo-site fixture exporter (Phase 11): scripts/export_demo_fixtures.py.

Only its pure parts: the TypeScript output, the sample descriptions, the web images and the batch-case choice. No
services, weights or data needed (runs in CI). The frontend's Vitest tests check the exported fixtures themselves.
"""

import importlib.util
import io
import json

import pandas as pd
import pytest
from PIL import Image

from ekyc import config


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, config.PROJECT_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = load_script("export_demo_fixtures")


def test_ts_literal_is_json_with_flat_lists_on_one_line():
    value = {"case": {"scores": [0.1, 0.25], "xy": [[0, 0], [112, 0]], "reasons": [{"code": "x"}], "name": "Šárka"}}
    text = export.ts_literal(value)
    assert json.loads(text) == value  # JSON is valid TypeScript: the same data, nothing lost
    assert '"xy": [[0, 0], [112, 0]]' in text  # heatmap tiles stay compact
    assert '"scores": [0.1, 0.25]' in text
    assert '"code": "x"' in text and "Šárka" in text  # objects one key per line, non-ASCII kept


@pytest.mark.parametrize("sample, title, words", [
    ({"name": "genuine_1", "document": "srb_passport_16 (genuine srb_passport)"}, "Serbian passport, genuine", "own selfie"),
    ({"name": "forged_1", "document": "aze_passport_75_fake_3_39 (forged aze_passport, edited field: surname_eng)"},
     "Azerbaijani passport, forged", "(surname)"),
    ({"name": "forged_2", "document": "esp_id_14_fake_2_85 (forged esp_id, edited field: surname_second)"},
     "Spanish ID card, forged", "(second surname)"),
    ({"name": "blank", "document": "an almost black image"}, "Unusable photo", "black image"),
])
def test_scenario_text_describes_the_sample_not_the_outcome(sample, title, words):
    got_title, description = export.scenario_text(sample)
    assert got_title == title
    assert words in description
    for outcome_word in ("approved", "review", "verified", "rejected"):  # the replay shows the outcome, not the picker
        assert outcome_word not in description.lower()


def test_web_jpeg_shrinks_and_drops_metadata():
    original = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make: must not survive
    Image.new("RGB", (2048, 1024), (200, 30, 30)).save(original, "JPEG", exif=exif)
    with Image.open(io.BytesIO(export.web_jpeg(original.getvalue(), 1024))) as small:
        assert small.size == (1024, 512)
        assert small.format == "JPEG"
        assert not small.getexif()
    with Image.open(io.BytesIO(export.web_jpeg(original.getvalue(), 4096))) as same:
        assert same.size == (2048, 1024)  # never enlarged


def test_pick_batch_cases_is_reproducible_and_refuses_a_reset_database(tmp_path, monkeypatch):
    truth = pd.DataFrame({"plan_index": [2, 0, 1, 3],
                          "application_id": ["app-c", "app-a", "app-b", "app-d"],
                          "scenario": ["genuine", "genuine", "genuine", "unreadable"]})
    path = tmp_path / "ground_truth.csv"
    truth.to_csv(path, index=False)
    monkeypatch.setattr(export, "BATCH_TRUTH", path)
    monkeypatch.setattr(export, "BATCH_PICKS", [("APPROVED", "AUTO_APPROVED", "genuine", 2)])
    rows = {a: {"status": "APPROVED", "outcome": "AUTO_APPROVED"} for a in ("app-a", "app-b", "app-c")}
    assert export.pick_batch_cases(rows) == [("app-a", "genuine"), ("app-b", "genuine")]  # plan order
    with pytest.raises(RuntimeError, match="was the database reset"):
        export.pick_batch_cases({"app-a": rows["app-a"]})
