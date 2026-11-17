"""forgery-worker (Phase 6): kyc.tasks.forgery -> kyc.results (check_type "forgery").
The accepted tile model (Phase 3B v3) with the exact preprocessing of models/forgery_detector.json; page score =
highest tile; band: >= 0.857383 forgery_suspected, >= 0.729 needs_review, else pass. The top tile's box is
included for the officer UI heatmap. Run: .venv/bin/python services/forgery-worker/main.py"""

import os

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

from ekyc.inference import ForgeryScorer  # noqa: E402
from ekyc.messaging.events import ForgeryTask, Topics  # noqa: E402
from ekyc.messaging.worker import Outcome, Worker  # noqa: E402


class ForgeryWorker(Worker):
    check_type, task_topic, payload_type = "forgery", Topics.TASK_FORGERY, ForgeryTask

    def load(self):  # on the CPU unless EKYC_TF_DEVICE=gpu (faster per page, leaves the GPU to Ollama)
        self.model = ForgeryScorer()
        self.log.info("thresholds: needs_review %.6f, forgery_suspected %.6f", self.model.review, self.model.suspected)

    def model_versions(self):
        return {"device": self.model.device, "forgery_detector": self.model.version}

    def handle(self, payload: ForgeryTask) -> Outcome:
        return Outcome(self.model.score(self.fetch(payload.document_key)))


if __name__ == "__main__":
    ForgeryWorker().run()
