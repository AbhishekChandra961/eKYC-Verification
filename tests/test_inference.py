"""Tests for the inference layer of the workers (Phase 6): bands and severities, exact preprocessing (byte-equal to
the training caches), forgery score equal to Phase 5, portrait choice on a real ID page, the blank gate, and the
extraction path with a simulated Ollama server. Tests needing models or data skip if those files are missing."""

import importlib.util
import io
import json

import httpx
import numpy as np
import pandas as pd
import pytest
from PIL import Image

from ekyc import config, consistency, data, inference

MANIFEST = config.MANIFEST_CSV
MODELS = config.PROJECT_ROOT / "models"
needs_data = pytest.mark.skipif(not MANIFEST.exists(), reason="manifest / images not available")


def test_bands_follow_the_policy():
    review, suspected = 0.729, 0.857383
    assert [inference.forgery_band(s, review, suspected) for s in (0.1, 0.729, 0.8573, 0.857383, 1.0)] == \
        ["pass", "needs_review", "needs_review", "forgery_suspected", "forgery_suspected"]
    assert [inference.face_band(s, 0.2597) for s in (None, 0.1, 0.2597, 0.4, 0.556, 0.9)] == \
        ["no_face_found", "mismatch", "needs_review", "needs_review", "match", "match"]


def test_rule_severities_match_the_phase5_policy():
    strong = {r for r, s in consistency.RULE_SEVERITY.items() if s == "strong"}
    assert strong == {"mrz_check_document_number", "mrz_check_birth_date", "mrz_check_expiry_date",
                      "mrz_check_composite", "mrz_vs_document_number", "mrz_vs_expiry_date", "date_order"}
    assert consistency.RULE_SEVERITY["mrz_vs_surname"] == consistency.RULE_SEVERITY["mrz_vs_given_names"] == "review"


@pytest.mark.data
@needs_data
def test_worker_preprocessing_is_byte_identical_to_the_training_caches():
    m = pd.read_csv(MANIFEST)
    templates = m[m["source"] == "template"]
    # The cache gave the extra q75 save at original size to GENUINE pages only (forged files already had it). The
    # worker applies it to every upload (policy in forgery_detector.json), so the byte comparison uses the cache's
    # own setting per class; on an already-q75 forged file the worker's extra save changes scores by ~1e-4.
    for label, pre_quality in ((0, config.GENUINE_PRE_QUALITY), (1, None)):
        row = templates[templates["label"] == label].iloc[3]
        hires_file = config.PROJECT_ROOT / data.cache_path_for(row.image_path, config.HIRES_EQ_DIR)
        if not hires_file.exists():
            pytest.skip("hi-res cache not built")
        # a fresh Image per call, as the workers do: Pillow's draft() (fast reduced-size JPEG decoding) only acts on an
        # image that has not been decoded yet, so re-using one opened image would take a different resize path
        with Image.open(config.PROJECT_ROOT / row.image_path) as image:
            assert data.resized_jpeg_bytes(image, config.HIRES_LONGEST, config.HIRES_QUALITY, True,
                                           pre_quality) == hires_file.read_bytes()
        with Image.open(config.PROJECT_ROOT / row.image_path) as image:
            assert data.resized_jpeg_bytes(image, config.RESIZE_LONGEST, config.JPEG_QUALITY) == \
                (config.PROJECT_ROOT / row.cache_path).read_bytes()


SCORES = config.REPORTS_DIR / "phase5" / "forgery_v3_page_scores_valtest.csv"


@needs_data
@pytest.mark.models
@pytest.mark.data
@pytest.mark.skipif(not (MODELS / "forgery_detector.keras").exists() or not SCORES.exists(), reason="model or scores missing")
def test_forgery_scorer_reproduces_the_evaluated_scores():
    scorer = inference.ForgeryScorer()
    assert scorer.suspected == pytest.approx(0.857383) and scorer.review == pytest.approx(0.729)
    rows = pd.read_csv(SCORES).groupby("label").head(1)
    for row in rows.itertuples():
        out = scorer.score((config.PROJECT_ROOT / row.image_path).read_bytes())
        assert out["score"] == pytest.approx(row.forgery_score, abs=1e-4)
        x, y, w, h = out["top_tile"]["box_1280"]
        assert w == h == 224 and 0 <= x <= out["page_size_1280"][0] - 224
        grid = out["tiles"]  # the full grid for the officer's heatmap
        assert grid["size"] == 224 and grid["count"] == len(grid["xy"]) == len(grid["scores"]) > 40
        assert max(grid["scores"]) == pytest.approx(out["score"], abs=1e-3) and [x, y] in grid["xy"]
        assert len(json.dumps(grid)) < 4000  # small enough to travel in every result event


@needs_data
@pytest.mark.models
@pytest.mark.data
@pytest.mark.skipif(not config.SFACE_ONNX.exists(), reason="face models not downloaded")
def test_face_verifier_takes_the_portrait_not_the_ghost_image():
    m = pd.read_csv(MANIFEST)
    row = m[(m["source"] == "template") & (m["label"] == 0) & (m["doc_type"] == "alb_id")].iloc[0]  # has a ghost photo
    box = pd.read_csv(config.FIELDS_GT_CSV).query("field_name == 'photo' and doc_id == @row.doc_id")[["x", "y", "w", "h"]].iloc[0]
    page = (config.PROJECT_ROOT / row.image_path).read_bytes()
    result = inference.FaceVerifier().verify(page, page)
    fx, fy, fw, fh = result["id_face"]["box"]
    assert result["id_face"]["faces"] >= 2  # portrait + ghost image
    assert box.x <= fx and box.y <= fy and fx + fw <= box.x + box.w + 5 and fy + fh <= box.y + box.h + 5  # inside the photo
    assert result["score"] == pytest.approx(1.0, abs=1e-3) and result["band"] == "match"
    blank = io.BytesIO()
    Image.new("RGB", (400, 300), (120, 120, 120)).save(blank, "JPEG")
    assert inference.FaceVerifier().verify(page, blank.getvalue())["band"] == "no_face_found"


@pytest.mark.models
@pytest.mark.skipif(not (MODELS / "doc_classifier.keras").exists(), reason="model missing")
def test_doc_classifier_blank_gate():
    buffer = io.BytesIO()
    Image.new("RGB", (900, 560), (5, 5, 5)).save(buffer, "JPEG")
    out = inference.DocClassifier().classify(buffer.getvalue())
    assert out["blank"] and not out["recognized"] and out["doc_type"] is None


# ------------------------------------------------------------------ extraction path with a fake Ollama
LINE0 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
LINE1 = "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
FIELDS = {"surname": "ERIKSSON", "given_names": "ANNA MARIA", "birth_date": "12.08.1974", "issue_date": "16.04.2007",
          "expiry_date": "15.04.2012", "document_number": "L898902C3", "mrz_line0": LINE0, "mrz_line1": LINE1}


def fake_extractor(answer: dict | None):
    def server(request):
        if answer is None:
            return httpx.Response(500, json={"error": "prediction aborted, token repeat limit reached"})
        body = json.loads(request.content)
        assert body["options"]["num_predict"] == 512 and body["options"]["repeat_penalty"] == 1.05
        assert body["keep_alive"] == "2m"
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}, "prompt_eval_count": 1700,
                                         "eval_count": 160})

    fe = inference.FieldExtractor(max_runner_mb=1e9)
    fe.ollama.client = httpx.Client(transport=httpx.MockTransport(server))
    return fe


def jpeg():
    buffer = io.BytesIO()
    Image.fromarray(np.full((300, 470, 3), 200, np.uint8)).save(buffer, "JPEG")
    return buffer.getvalue()


def test_extraction_without_inconsistencies_has_no_flags():
    out = fake_extractor(FIELDS).extract(jpeg(), "srb_passport")
    assert out["valid"] and out["flags"] == [] and out["fields"]["surname"] == "ERIKSSON" and out["output_tokens"] == 160


def test_extraction_flags_carry_their_severity():
    name = fake_extractor({**FIELDS, "surname": "PETROVIC"}).extract(jpeg(), "srb_passport")
    assert name["review_flags"] == ["mrz_vs_surname"] and name["strong_flags"] == []
    expiry = fake_extractor({**FIELDS, "expiry_date": "15.04.2014"}).extract(jpeg(), "srb_passport")
    assert expiry["strong_flags"] == ["mrz_vs_expiry_date"]


def test_failed_extraction_becomes_a_failed_result():
    fe = fake_extractor(None)
    out = fe.extract(jpeg(), "srb_passport")
    assert not out["valid"] and "token repeat limit" in out["error"]
    spec = importlib.util.spec_from_file_location("ew", config.PROJECT_ROOT / "services" / "extraction-worker" / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    worker = module.ExtractionWorker.__new__(module.ExtractionWorker)  # no Kafka connections needed for handle()
    worker.model, worker.fetch = fe, lambda key: jpeg()
    outcome = worker.handle(module.ExtractionTask(document_key="k", doc_type="srb_passport"))
    assert outcome.status == "failed" and "token repeat limit" in outcome.error


def test_ollama_memory_guard_without_ps(monkeypatch):
    """Phase 9: the slim container image has no `ps`; the guard must report 0 instead of failing every extraction."""
    def no_ps(*args, **kwargs):
        raise FileNotFoundError("ps")
    monkeypatch.setattr(inference.subprocess, "run", no_ps)
    assert inference.ollama_runner_mb() == 0.0
