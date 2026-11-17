"""Tests for the extraction layer (Phase 5) with fake model servers: no Ollama or API key needed."""

import io
import json

import httpx
import numpy as np
import pandas as pd
import pytest
from PIL import Image

from ekyc import extraction

VALID = json.dumps({"surname": "AGANI", "birth_date": "20-11-1991"})


def test_prepare_image_handles_cmyk_and_resizes(tmp_path):
    Image.fromarray(np.full((400, 800, 4), 60, np.uint8), mode="CMYK").save(tmp_path / "c.jpg")
    with Image.open(io.BytesIO(extraction.prepare_image(tmp_path / "c.jpg"))) as out:
        assert out.mode == "RGB" and out.format == "JPEG" and out.size == (1280, 640)


def test_prompt_is_doc_type_aware():
    esp = extraction.build_prompt("esp_id")
    assert "Spanish identity card" in esp and "IDESP" in esp and "NOT the DNI number" in esp
    assert "always null: birth_place, authority, mrz_line0, mrz_line1" in esp
    assert "mrz_line1" in extraction.build_prompt("srb_passport").split("always null")[0]


class Scripted(extraction.Extractor):
    """A fake extractor that returns prepared answers in order."""
    name, model = "fake", "scripted"

    def __init__(self, answers):
        self.answers, self.calls, self.conversation = list(answers), 0, None

    def _start(self, image_jpeg, prompt):
        self.conversation = [prompt]
        return self.conversation

    def _ask(self, conversation):
        self.calls += 1
        return extraction._Reply(self.answers.pop(0), 10, 5)

    def _follow_up(self, conversation, reply, message):
        conversation.append(message)


def test_retry_with_the_validation_error_then_success():
    ex = Scripted(['{"surname": 5', VALID])  # broken JSON first
    r = ex.extract(b"jpg", "alb_id", "alb_id_01")
    assert r.valid and r.attempts == 2 and r.retries == 1 and r.fields["surname"] == "AGANI"
    assert r.input_tokens == 20 and "not valid" in ex.conversation[-1]  # the error went back to the model


def test_gives_up_after_max_retries():
    r = Scripted(['{"height": "175"}'] * 3).extract(b"jpg", "alb_id")
    assert not r.valid and r.fields is None and r.attempts == extraction.MAX_RETRIES + 1 and "height" in r.error


def test_ollama_request_format():
    seen = {}

    def server(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": VALID}, "prompt_eval_count": 1500, "eval_count": 90})

    ex = extraction.OllamaExtractor(transport=httpx.MockTransport(server))
    r = ex.extract(b"\xff\xd8jpeg", "alb_id")
    assert r.valid and (r.input_tokens, r.output_tokens) == (1500, 90)
    assert seen["options"]["temperature"] == 0 and seen["format"]["properties"].keys() >= {"surname", "mrz_line1"}
    assert seen["keep_alive"] == "10m" and seen["messages"][1]["images"] and not seen["stream"]


def test_cloud_anthropic_uses_a_forced_tool_and_tool_results_for_retries():
    bodies = []
    answers = [{"surname": 5}, {"surname": "AGANI"}]

    def server(request):
        assert request.headers["x-api-key"] == "k" and request.url.path == "/v1/messages"
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"content": [{"type": "tool_use", "id": f"t{len(bodies)}",
                                                       "name": "record_fields", "input": answers[len(bodies) - 1]}],
                                         "usage": {"input_tokens": 1000, "output_tokens": 50}})

    ex = extraction.CloudExtractor("anthropic", "some-model", "k", transport=httpx.MockTransport(server))
    r = ex.extract(b"jpeg", "alb_id")
    assert r.valid and r.attempts == 2 and r.input_tokens == 2000
    assert bodies[0]["tool_choice"] == {"type": "tool", "name": "record_fields"} and bodies[0]["temperature"] == 0
    assert bodies[0]["messages"][0]["content"][0]["type"] == "image"
    assert bodies[1]["messages"][-1]["content"][0]["type"] == "tool_result"  # the correction answers the tool call


def test_cloud_openai_json_mode():
    def server(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"} and request.headers["authorization"] == "Bearer k"
        assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
        return httpx.Response(200, json={"choices": [{"message": {"content": VALID}}],
                                         "usage": {"prompt_tokens": 900, "completion_tokens": 40}})

    r = extraction.CloudExtractor("openai", "m", "k", transport=httpx.MockTransport(server)).extract(b"j", "alb_id")
    assert r.valid and r.output_tokens == 40


def test_cloud_is_skipped_without_a_key(tmp_path, monkeypatch):
    for name in ("LLM_API_KEY", "LLM_PROVIDER", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("LLM_PROVIDER=anthropic\nLLM_MODEL=x\nLLM_API_KEY=\n")
    assert extraction.CloudExtractor.from_env(tmp_path / ".env") is None
    with pytest.raises(ValueError):
        extraction.CloudExtractor("other", "m", "k")


def test_run_batch_uses_the_cache(tmp_path):
    for name in ("a.jpg", "b.jpg"):
        Image.fromarray(np.full((50, 80, 3), 200, np.uint8)).save(tmp_path / name)
    docs = pd.DataFrame({"doc_id": ["a", "b"], "doc_type": ["alb_id", "alb_id"], "image_path": ["a.jpg", "b.jpg"]})
    ex = Scripted([VALID, VALID])
    first = extraction.run_batch(docs, ex, tmp_path / "cache.jsonl", project_root=tmp_path)
    again = extraction.run_batch(docs, Scripted([]), tmp_path / "cache.jsonl", project_root=tmp_path)  # no answers left
    assert ex.calls == 2 and first["valid"].all() and again["doc_id"].tolist() == ["a", "b"]
    assert len((tmp_path / "cache.jsonl").read_text().splitlines()) == 2


def test_run_batch_resends_failed_calls_but_not_invalid_answers(tmp_path):
    for name in ("a.jpg", "b.jpg"):
        Image.fromarray(np.full((50, 80, 3), 200, np.uint8)).save(tmp_path / name)
    docs = pd.DataFrame({"doc_id": ["a", "b"], "doc_type": ["alb_id", "alb_id"], "image_path": ["a.jpg", "b.jpg"]})

    class ServerDown(Scripted):
        def _ask(self, conversation):
            raise httpx.HTTPStatusError("500", request=httpx.Request("POST", "http://x"), response=httpx.Response(500))

    first = extraction.run_batch(docs.iloc[:1], ServerDown([]), tmp_path / "c.jsonl", project_root=tmp_path)
    assert not first["valid"].iloc[0] and first["error"].iloc[0].startswith("call failed")
    extraction.run_batch(docs.iloc[1:], Scripted(['{"height": 1}'] * 3), tmp_path / "c.jsonl", project_root=tmp_path)
    again = Scripted([VALID])  # only one answer: just the failed call may be sent again
    result = extraction.run_batch(docs, again, tmp_path / "c.jsonl", project_root=tmp_path)
    assert again.calls == 1 and result.set_index("doc_id")["valid"].to_dict() == {"a": True, "b": False}
    assert len((tmp_path / "c.jsonl").read_text().splitlines()) == 3  # the failed call stays on record
    # a document whose call failed twice is not sent a third time
    extraction.run_batch(docs.iloc[:1], ServerDown([]), tmp_path / "d.jsonl", project_root=tmp_path)
    extraction.run_batch(docs.iloc[:1], ServerDown([]), tmp_path / "d.jsonl", project_root=tmp_path)
    third = Scripted([VALID])
    assert not extraction.run_batch(docs.iloc[:1], third, tmp_path / "d.jsonl", project_root=tmp_path)["valid"].iloc[0]
    assert third.calls == 0


def test_summarize_case_falls_back_to_the_template():
    case = {"case_id": "C1", "decision": "approve", "forgery": {"score": 0.1, "band": "pass"},
            "consistency": {"flags": []}}
    text = extraction.summarize_case(case)  # no LLM
    assert "C1" in text and "0.1" in text and "All consistency rules passed" in text and "Face check: not available" in text

    class Broken(Scripted):
        def complete_text(self, system, user):
            raise httpx.ConnectError("down")

    assert extraction.summarize_case(case, Broken([])) == text

    class Echo(Scripted):
        def complete_text(self, system, user):
            assert "ONLY facts" in system and json.loads(user)["case_id"] == "C1"
            return " LLM summary. "

    assert extraction.summarize_case(case, Echo([])) == "LLM summary."
