"""Simulated camera frames for the liveness EVALUATION and the test/demo fake camera (Phase 13). The pipeline never
uses this module: it only makes inputs whose truth is known.

- synthetic_head_turn: turns the head in a single photo by a given angle. The face is modelled as a 2.5-D surface
  (a half-ellipsoid plus a nose ridge, sized from the 5 landmarks) and rotated about the vertical axis with an
  orthographic projection; the background stays put. It imitates the GEOMETRY of a real head turn (the nose moves
  sideways more than the eyes, the far cheek narrows), not its appearance (no new pixels for the hidden side).
  Used for a "genuine" sequence where no real one exists (the SIDTD portraits are single synthetic photos), and to
  play a turning face to Chromium's fake webcam. NOTE: a frame made this way passes the liveness check, which is
  exactly why a digitally manipulated video fed to the server (an injection attack) is out of this check's reach.
- tilted_photo: a printed photo held in front of the camera and rotated about its vertical axis (a planar
  presentation attack), as a pinhole-camera perspective warp.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


def synthetic_head_turn(rgb: np.ndarray, landmarks, degrees: float) -> np.ndarray:
    """The photo with the head turned by `degrees` (positive = to the subject's LEFT, i.e. the nose moves to the
    right of the image). landmarks: YuNet's 5 points (x, y) for the face in `rgb`."""
    h, w = rgb.shape[:2]
    right_eye, left_eye, nose, right_mouth, left_mouth = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
    eye_distance = float(np.linalg.norm(left_eye - right_eye))
    cx = float((right_eye[0] + left_eye[0] + right_mouth[0] + left_mouth[0]) / 4)
    cy = float((right_eye[1] + left_eye[1] + right_mouth[1] + left_mouth[1]) / 4)
    rx, ry, depth = 1.15 * eye_distance, 1.7 * eye_distance, 0.9 * eye_distance  # head: half-ellipsoid
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    inside = np.clip(1 - ((xx - cx) / rx) ** 2 - ((yy - cy) / ry) ** 2, 0, None)
    z = depth * np.sqrt(inside)
    eye_y = (right_eye[1] + left_eye[1]) / 2
    ridge_y = (eye_y + nose[1]) / 2 + 0.1 * eye_distance
    z += 0.55 * eye_distance * np.exp(-((xx - nose[0]) / (0.28 * eye_distance)) ** 2
                                      - ((yy - ridge_y) / (0.5 * eye_distance)) ** 2)  # the nose ridge
    weight = np.clip(inside * 4, 0, 1)  # full motion on the face, fading out towards its outline
    a = math.radians(degrees)
    moved = cx + (xx - cx) * (math.cos(a) * weight + (1 - weight)) + z * math.sin(a) * weight  # where x goes
    map_x = np.empty_like(xx)
    for row in range(h):  # invert x -> moved(x) row by row (kept monotonic)
        map_x[row] = np.interp(np.arange(w, dtype=np.float32), np.maximum.accumulate(moved[row]), xx[row])
    return cv2.remap(np.ascontiguousarray(rgb), map_x, yy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)


def tilted_photo(rgb: np.ndarray, degrees: float, fov_deg: float = 60.0, fill: int = 0) -> np.ndarray:
    """A flat photo filling the camera's view (horizontal field of view `fov_deg`), rotated by `degrees` about its own
    vertical centre line, seen through a pinhole camera. A narrower photo in the view = weaker perspective."""
    h, w = rgb.shape[:2]
    f = (w / 2) / math.tan(math.radians(fov_deg) / 2)
    K = np.array([[f, 0, w / 2], [0, f, h / 2], [0, 0, 1.0]])
    a = math.radians(degrees)
    R = np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])
    d = f  # the photo plane (any depth gives the same picture: only the field of view matters)
    centre, normal = np.array([0, 0, d]), np.array([0, 0, 1.0])
    H = K @ (R + np.outer((np.eye(3) - R) @ centre, normal) / d) @ np.linalg.inv(K)  # rotate the plane about centre
    return cv2.warpPerspective(np.ascontiguousarray(rgb), H, (w, h), borderMode=cv2.BORDER_CONSTANT,
                               borderValue=(fill, fill, fill))
