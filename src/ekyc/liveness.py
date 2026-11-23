"""Active liveness (Phase 13): did a live person turn their head left and right in front of the camera?

The customer's browser shows a camera guide and asks for three frames: looking at the camera (this frame is the
selfie), head turned to the customer's LEFT, then to their RIGHT. The browser's own guidance only helps the customer;
it is never trusted. The face-worker decides here, from the frames alone, with the two models it already has:
- YuNet gives each face 5 landmarks (right eye, left eye, nose tip, right and left mouth corner) -> the head's yaw;
- SFace embeddings -> are all three frames the same person?

YAW (the turn about the vertical axis), estimated from where the nose tip sits relative to the face's midline:
  1. rotate the landmarks so that the eyes are level (removes a sideways head tilt, "roll");
  2. midline x = mean x of the two eyes and the two mouth corners; offset = nose x - midline x;
  3. yaw = atan(offset / (NOSE_DEPTH x eye distance)), in degrees.
Why: the nose tip sticks out about half an eye distance in front of the eyes and mouth. When the head turns by an
angle a, the nose moves sideways relative to them by about NOSE_DEPTH x eye distance x sin(a), while the eye distance
seen by the camera shrinks by cos(a): offset / eye distance ~ NOSE_DEPTH x tan(a). A FLAT photo has no such depth:
tilting a printed photo moves the nose together with the eyes and mouth, and only perspective adds a little offset
(Phase 13 evaluation: at most ~16 degrees for tilts up to 60 degrees; reports/phase13/).
Sign: positive = the subject turned to THEIR left (the nose points to the right of the unmirrored camera image).
This is a geometric approximation for a yes/no turn test, not a calibrated head-pose measurement.

RULES (LivenessPolicy):
- every frame shows a face (else "no_face_<frame>");
- the neutral frame is roughly frontal: |yaw| <= max_neutral_yaw_deg (else "not_frontal");
- left frame: yaw - neutral yaw >= +min_turn_deg (else "no_left_turn"); right frame: <= -min_turn_deg ("no_right_turn");
- the same person in all three: SFace cosine(neutral, left) and cosine(neutral, right) >= same_person_min_cosine
  (else "different_person").
The decision engine (decision.py) turns "different_person" into a high-risk manual review and any other failure into
a request to retake the selfie; frames not sent at all (the photo-upload fallback) into a medium-risk review.

    policy = policy_from_env(same_person_min_cosine=0.2597)
    result = evaluate(neutral, left, right, policy)       # FrameFace inputs; PURE, no models or I/O
"""

from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass

import numpy as np
from dotenv import dotenv_values

from ekyc import config

NOT_PROVIDED = {"status": "not_provided"}  # the customer uploaded a photo instead of using the camera


@dataclass(frozen=True)
class LivenessPolicy:
    same_person_min_cosine: float  # SFace cosine; the face check's mismatch threshold (models/face_config.json)
    min_turn_deg: float = config.LIVENESS_MIN_TURN_DEG
    max_neutral_yaw_deg: float = config.LIVENESS_MAX_NEUTRAL_YAW_DEG
    nose_depth: float = config.LIVENESS_NOSE_DEPTH


def policy_from_env(same_person_min_cosine: float, env_file=config.PROJECT_ROOT / ".env") -> LivenessPolicy:
    """The defaults of config.py, overridden by EKYC_LIVENESS_* in the environment or .env (the environment wins)."""
    values = {**dotenv_values(env_file), **os.environ}
    defaults = LivenessPolicy(same_person_min_cosine)

    def number(name: str, default: float) -> float:
        raw = values.get(f"EKYC_LIVENESS_{name}")
        return float(raw) if raw else default

    return LivenessPolicy(same_person_min_cosine,
                          min_turn_deg=number("MIN_TURN_DEG", defaults.min_turn_deg),
                          max_neutral_yaw_deg=number("MAX_NEUTRAL_YAW_DEG", defaults.max_neutral_yaw_deg),
                          nose_depth=number("NOSE_DEPTH", defaults.nose_depth))


def estimate_yaw(landmarks, nose_depth: float = config.LIVENESS_NOSE_DEPTH) -> float:
    """Approximate head yaw in degrees from YuNet's 5 landmarks [(x, y) of right eye, left eye, nose tip, right mouth
    corner, left mouth corner] in image pixels. Positive = turned to the subject's left. See the module docstring."""
    points = np.asarray(landmarks, dtype=float).reshape(5, 2)
    right_eye, left_eye = points[0], points[1]
    roll = math.atan2(left_eye[1] - right_eye[1], left_eye[0] - right_eye[0])
    cos, sin = math.cos(-roll), math.sin(-roll)
    level = (points - points.mean(axis=0)) @ np.array([[cos, -sin], [sin, cos]]).T  # eyes on one horizontal line
    eye_distance = abs(level[1, 0] - level[0, 0])
    if eye_distance < 1e-6:
        raise ValueError("eye landmarks coincide: no yaw can be estimated")
    midline = level[[0, 1, 3, 4], 0].mean()
    return math.degrees(math.atan((level[2, 0] - midline) / (nose_depth * eye_distance)))


@dataclass(frozen=True)
class FrameFace:
    """What one frame gave: the face's landmarks and its unit-length SFace embedding (None when no face was found)."""
    landmarks: list | None
    embedding: np.ndarray | None

    @property
    def found(self) -> bool:
        return self.landmarks is not None and self.embedding is not None


def evaluate(neutral: FrameFace, left: FrameFace, right: FrameFace, policy: LivenessPolicy) -> dict:
    """The liveness result: status passed / failed, the failures, and the measured values (the officer sees them).
    yaw_deg per frame; turn_deg = left and right yaw minus the neutral yaw; same_person_cosine = SFace cosine of the
    left and right frame with the neutral one."""
    frames = {"neutral": neutral, "left": left, "right": right}
    failures = [f"no_face_{name}" for name, frame in frames.items() if not frame.found]
    yaw = {name: (round(estimate_yaw(frame.landmarks, policy.nose_depth), 1) if frame.found else None)
           for name, frame in frames.items()}
    turn, cosine = {}, {}
    if neutral.found:
        if abs(yaw["neutral"]) > policy.max_neutral_yaw_deg:
            failures.append("not_frontal")
        for side, sign in (("left", 1), ("right", -1)):
            if not frames[side].found:
                continue
            turn[side] = round(yaw[side] - yaw["neutral"], 1)
            if sign * turn[side] < policy.min_turn_deg:
                failures.append(f"no_{side}_turn")
            cosine[side] = round(float(np.dot(neutral.embedding, frames[side].embedding)), 4)
        if any(value < policy.same_person_min_cosine for value in cosine.values()):
            failures.append("different_person")
    return {"status": "failed" if failures else "passed", "failures": failures, "yaw_deg": yaw, "turn_deg": turn,
            "same_person_cosine": cosine,
            "thresholds": {k: v for k, v in asdict(policy).items() if k != "nose_depth"}}
