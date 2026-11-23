"""face-worker (Phase 6): kyc.tasks.face -> kyc.results (check_type "face").
YuNet finds the faces on the ID page (largest = the portrait) and on the selfie; SFace compares them (cosine).
Band: no face -> no_face_found (new photo or review); < 0.2597 mismatch; 0.2597-0.556 needs_review; >= 0.556 match.
Phase 13: also the active liveness check on the selfie + the two head-turn frames (outputs["liveness"]: passed /
failed with the measured yaw and same-person values, or not_provided when the customer uploaded a photo);
see src/ekyc/liveness.py. The server decides: the browser sends only images, never a liveness result.
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
        selfie = self.fetch(payload.selfie_key)
        outputs = self.model.verify(self.fetch(payload.document_key), selfie)
        turns = (payload.liveness_left_key, payload.liveness_right_key)
        left, right = (self.fetch(key) for key in turns) if all(turns) else (None, None)
        outputs["liveness"] = self.model.liveness(selfie, left, right)
        return Outcome(outputs)


if __name__ == "__main__":
    FaceWorker().run()
