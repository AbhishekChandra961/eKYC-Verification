"""doc-worker (Phase 6): kyc.tasks.doc -> kyc.results (check_type "doc").
Blank-image gate (Phase 2.1 is_empty rule), then the document-type classifier with its 0.77 confidence threshold
(below it: "unrecognized document"). Run: .venv/bin/python services/doc-worker/main.py"""

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

from ekyc.inference import DocClassifier  # noqa: E402
from ekyc.messaging.events import DocTask, Topics  # noqa: E402
from ekyc.messaging.worker import Outcome, Worker  # noqa: E402


class DocWorker(Worker):
    check_type, task_topic, payload_type = "doc", Topics.TASK_DOC, DocTask

    def load(self):  # on the CPU unless EKYC_TF_DEVICE=gpu (faster per page, leaves the GPU to Ollama)
        self.model = DocClassifier()

    def model_versions(self):
        return {"device": self.model.device, "doc_classifier": self.model.version}

    def handle(self, payload: DocTask) -> Outcome:
        return Outcome(self.model.classify(self.fetch(payload.document_key)))


if __name__ == "__main__":
    DocWorker().run()
