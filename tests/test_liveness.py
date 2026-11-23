"""Active liveness (Phase 13): the yaw estimate from 5 landmarks and the pass/fail rules (src/ekyc/liveness.py).

No models needed (runs in CI): landmarks come from a small 3-D face model rotated and projected here, so the true
yaw is known; embeddings are hand-made unit vectors.
"""

import math

import numpy as np
import pytest

from ekyc import liveness
from ekyc.liveness import FrameFace, LivenessPolicy, estimate_yaw, evaluate

# A frontal face in units of the eye distance: x to the image right, y down, z towards the camera.
# Eyes and mouth corners lie roughly in one plane; the nose tip sticks out by NOSE_DEPTH (0.5).
FACE_3D = np.array([[-0.5, 0.0, 0.0],    # right eye (the subject's right: image left)
                    [0.5, 0.0, 0.0],     # left eye
                    [0.0, 0.55, 0.5],    # nose tip
                    [-0.4, 1.1, 0.05],   # right mouth corner
                    [0.4, 1.1, 0.05]])   # left mouth corner


def landmarks(yaw_deg=0.0, roll_deg=0.0, scale=60.0, shift=(320.0, 240.0)):
    """Rotate the 3-D face (yaw: positive = the subject turns to THEIR left, so the nose moves to image right),
    tilt it in the image plane (roll), project orthographically and place it in a 640x480 image."""
    a = math.radians(yaw_deg)
    turned = FACE_3D @ np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]).T
    r = math.radians(roll_deg)
    flat = turned[:, :2] @ np.array([[math.cos(r), -math.sin(r)], [math.sin(r), math.cos(r)]]).T
    return (flat * scale + np.array(shift)).tolist()


def unit(*values):
    v = np.array(values + (0.0,) * (8 - len(values)), dtype=np.float32)
    return v / np.linalg.norm(v)


SAME, SIMILAR, OTHER = unit(1, 0.2), unit(1, 0.35), unit(-0.1, 1)  # cosines: SAME-SIMILAR 0.99, SAME-OTHER 0.10
POLICY = LivenessPolicy(same_person_min_cosine=0.2597)


# ------------------------------------------------------------------ yaw estimate
@pytest.mark.parametrize("true_yaw", [-40, -30, -20, -10, 0, 10, 20, 30, 40])
def test_yaw_follows_the_head_turn(true_yaw):
    """Orthographic face model: the estimate tracks the true yaw within a few degrees up to +-40."""
    assert estimate_yaw(landmarks(true_yaw)) == pytest.approx(true_yaw, abs=4.0)


def test_yaw_sign_is_the_subjects_left():
    assert estimate_yaw(landmarks(25)) > 15  # turned to their left: nose to the right of the image
    assert estimate_yaw(landmarks(-25)) < -15


@pytest.mark.parametrize("roll", [-25, -10, 10, 25])
def test_a_sideways_head_tilt_is_not_a_turn(roll):
    assert estimate_yaw(landmarks(0, roll_deg=roll)) == pytest.approx(0, abs=1.0)
    assert estimate_yaw(landmarks(30, roll_deg=roll)) == pytest.approx(estimate_yaw(landmarks(30)), abs=1.0)


def test_yaw_does_not_depend_on_face_size_or_position():
    base = estimate_yaw(landmarks(30))
    assert estimate_yaw(landmarks(30, scale=25, shift=(100, 80))) == pytest.approx(base)
    assert estimate_yaw(landmarks(30, scale=200, shift=(900, 500))) == pytest.approx(base)


def test_a_flat_face_cannot_turn():
    """No depth (a photo): a turn only narrows the face, the nose stays on the midline."""
    flat = FACE_3D.copy()
    flat[:, 2] = 0
    a = math.radians(35)
    turned = flat @ np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]]).T
    assert estimate_yaw((turned[:, :2] * 60 + 300).tolist()) == pytest.approx(0, abs=0.5)


def test_eyes_on_one_point_is_an_error():
    with pytest.raises(ValueError):
        estimate_yaw([[10, 10], [10, 10], [12, 20], [8, 30], [14, 30]])


# ------------------------------------------------------------------ the rules
def frame(yaw, embedding=SAME):
    return FrameFace(landmarks(yaw), embedding)


NO_FACE = FrameFace(None, None)


def test_a_clear_left_and_right_turn_of_one_person_passes():
    result = evaluate(frame(2), frame(30, SIMILAR), frame(-28, SIMILAR), POLICY)
    assert result["status"] == "passed" and result["failures"] == []
    assert result["turn_deg"]["left"] == pytest.approx(28, abs=4) and result["turn_deg"]["right"] == pytest.approx(-30, abs=4)
    assert set(result["yaw_deg"]) == {"neutral", "left", "right"}
    assert result["same_person_cosine"]["left"] > 0.9
    assert result["thresholds"] == {"same_person_min_cosine": 0.2597, "min_turn_deg": 20.0, "max_neutral_yaw_deg": 15.0}


def test_static_photo_three_identical_frames_fails():
    result = evaluate(frame(1), frame(1), frame(1), POLICY)
    assert result["status"] == "failed" and result["failures"] == ["no_left_turn", "no_right_turn"]
    assert result["turn_deg"] == {"left": 0.0, "right": 0.0}


def test_turns_are_measured_from_the_neutral_frame():
    """A head already turned 12 degrees to the right in the 'neutral' frame must still turn 20 degrees each way FROM
    there: reaching +3 is only a ~15 degree turn to the left; +14 is ~26."""
    assert evaluate(frame(-12), frame(3), frame(-40), POLICY)["failures"] == ["no_left_turn"]
    assert evaluate(frame(-12), frame(14), frame(-40), POLICY)["status"] == "passed"


def test_turn_in_the_wrong_direction_fails():
    result = evaluate(frame(0), frame(-30), frame(30), POLICY)  # left and right swapped
    assert result["failures"] == ["no_left_turn", "no_right_turn"]


def test_turn_threshold_boundary():
    policy = LivenessPolicy(0.2597, min_turn_deg=20.0)
    base = estimate_yaw(landmarks(0))
    left = next(y for y in np.arange(15, 30, 0.1) if estimate_yaw(landmarks(y)) - base >= 20.0)
    assert evaluate(frame(0), frame(left), frame(-30), policy)["status"] == "passed"
    assert evaluate(frame(0), frame(left - 0.5), frame(-30), policy)["failures"] == ["no_left_turn"]


def test_neutral_frame_must_face_the_camera():
    result = evaluate(frame(25), frame(50), frame(-5), POLICY)
    assert "not_frontal" in result["failures"]


def test_frames_of_different_people_are_flagged():
    result = evaluate(frame(0), frame(30, OTHER), frame(-30, SIMILAR), POLICY)
    assert result["failures"] == ["different_person"]
    assert result["same_person_cosine"]["left"] < 0.2597 < result["same_person_cosine"]["right"]


def test_missing_faces_fail_without_crashing():
    result = evaluate(frame(0), NO_FACE, frame(-30), POLICY)
    assert result["failures"] == ["no_face_left"] and result["yaw_deg"]["left"] is None
    assert "left" not in result["turn_deg"] and "left" not in result["same_person_cosine"]
    nothing = evaluate(NO_FACE, NO_FACE, NO_FACE, POLICY)
    assert nothing["failures"] == ["no_face_neutral", "no_face_left", "no_face_right"]


def test_policy_from_env_overrides_the_defaults(monkeypatch, tmp_path):
    for name in ("MIN_TURN_DEG", "MAX_NEUTRAL_YAW_DEG", "NOSE_DEPTH"):
        monkeypatch.delenv(f"EKYC_LIVENESS_{name}", raising=False)
    defaults = liveness.policy_from_env(0.3, env_file=tmp_path / "missing.env")
    assert (defaults.min_turn_deg, defaults.max_neutral_yaw_deg, defaults.nose_depth) == (20.0, 15.0, 0.5)
    env_file = tmp_path / ".env"
    env_file.write_text("EKYC_LIVENESS_MIN_TURN_DEG=25\nEKYC_LIVENESS_MAX_NEUTRAL_YAW_DEG=12\n")
    monkeypatch.setenv("EKYC_LIVENESS_MAX_NEUTRAL_YAW_DEG", "10")  # the environment wins over .env
    policy = liveness.policy_from_env(0.3, env_file=env_file)
    assert (policy.min_turn_deg, policy.max_neutral_yaw_deg, policy.same_person_min_cosine) == (25.0, 10.0, 0.3)
