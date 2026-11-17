"""extraction-worker (Phase 6): kyc.tasks.extraction -> kyc.results (check_type "extraction").
Ollama on the host (qwen2.5vl:7b, frozen prompt v2) with an output cap, repeat penalty, request timeout, fixed
context and short keep_alive; the model is unloaded if its runner exceeds ~8 GB. Then the consistency rules:
each failed rule carries a severity ("strong": reliable evidence; "review": e.g. MRZ name mismatches).
A failed extraction is a result with status "failed", not an exception.
Run: .venv/bin/python services/extraction-worker/main.py   (needs `ollama serve` on the host)"""

from ekyc.inference import FieldExtractor
from ekyc.messaging.events import ExtractionTask, Topics
from ekyc.messaging.worker import Outcome, Worker


class ExtractionWorker(Worker):
    check_type, task_topic, payload_type = "extraction", Topics.TASK_EXTRACTION, ExtractionTask

    def load(self):
        self.model = FieldExtractor(host=self.settings.ollama_host)
        if not self.model.available():
            self.log.warning("Ollama model %s not available at %s: extractions will report status failed",
                             self.model.ollama.model, self.settings.ollama_host)

    def model_versions(self):
        return {"extraction": self.model.version}

    def handle(self, payload: ExtractionTask) -> Outcome:
        result = self.model.extract(self.fetch(payload.document_key), payload.doc_type)
        if not result["valid"]:
            return Outcome({k: v for k, v in result.items() if k != "error"}, status="failed", error=result["error"])
        return Outcome(result)


if __name__ == "__main__":
    ExtractionWorker().run()
