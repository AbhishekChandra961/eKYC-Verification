"""face-worker (Phase 6): kyc.tasks.face -> kyc.results (check_type "face").
YuNet finds the faces on the ID page (largest = the portrait) and on the selfie; SFace compares them (cosine).
Band: no face -> no_face_found (new photo or review); < 0.2597 mismatch; 0.2597-0.556 needs_review; >= 0.556 match.
Run: .venv/bin/python services/face-worker/main.py"""

from ekyc.inference import FaceVerifier
from ekyc.messaging.events import FaceTask, Topics
from ekyc.messaging.worker import Outcome, Worker


class FaceWorker(Worker):
    check_type, task_topic, payload_type = "face", Topics.TASK_FACE, FaceTask

    def load(self):
        self.model = FaceVerifier()

    def model_versions(self):
        return {"yunet+sface": self.model.version}

    def handle(self, payload: FaceTask) -> Outcome:
        return Outcome(self.model.verify(self.fetch(payload.document_key), self.fetch(payload.selfie_key)))


if __name__ == "__main__":
    FaceWorker().run()
