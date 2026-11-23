"""A small, honest evaluation of the active liveness check (Phase 13) -> reports/phase13/.

    .venv/bin/python scripts/evaluate_liveness.py

Every scenario goes through the PRODUCTION code: FaceVerifier.liveness() for frames given as JPEG bytes (SIDTD), or
the same liveness.evaluate() on YuNet + SFace results (LFW). Thresholds: the defaults in src/ekyc/config.py.

Scenarios (what the frames are, and where they come from):
  genuine, real head turns (LFW)      one person's photos: the most frontal one, one turned to their left, one to their
                                      right. REAL 3-D head turns of real people, but separate photos (not one video),
                                      and the turned photos are CHOSEN with the same yaw estimate (a turn of 25-50
                                      degrees), so this tests the same-person rule on turned faces, not the turn rule.
  genuine, synthetic turns (SIDTD)    each test-split portrait turned +-28 degrees by liveness_sim.synthetic_head_turn
                                      (no real head-turn video of these synthetic faces exists).
  static photo (3 identical frames)   a photo shown to the camera without moving (SIDTD portraits; LFW frontal photos).
  tilted printed photo                the same photo held flat and tilted left / right (perspective warp,
                                      liveness_sim.tilted_photo), by 40 and 55 degrees: the strongest planar attack
                                      that keeps the face detectable in the simulation.
  different people                    three different SIDTD portraits, each synthetically turned the right way (so only
                                      the same-person rule can catch them); and three different LFW people with real
                                      turns.
"""

from __future__ import annotations

import io
import json
from collections import Counter

import cv2
import numpy as np
import pandas as pd
from PIL import Image

from ekyc import config, data, face, inference, liveness, liveness_sim

OUT = config.REPORTS_DIR / "phase13"
LFW_IMAGES = config.LFW_DIR / "lfw_home" / "lfw_funneled"
TURN = 28.0  # synthetic turn, degrees (a typical prompted turn)
TILTS = (40.0, 55.0)
DECISION = {"passed": "no liveness reason", "failed": "RESUBMIT_REQUIRED (retake the selfie)",
            "different_person": "MANUAL_REVIEW high"}


def jpeg(rgb: np.ndarray, quality: int = 90) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(rgb).save(buffer, "JPEG", quality=quality)
    return buffer.getvalue()


def outcome(result: dict) -> str:
    if result["status"] == "passed":
        return "passed"
    return "different_person" if "different_person" in result["failures"] else "failed"


def sidtd_portraits() -> list[tuple[str, np.ndarray]]:
    """Every genuine TEST-split template's portrait, cut out with a margin (a selfie-like crop)."""
    manifest = pd.read_csv(config.MANIFEST_CSV)
    docs = manifest[(manifest["source"] == "template") & (manifest["label"] == 0) & (manifest["split"] == "test")]
    boxes = data.parse_ground_truth().query("field_name == 'photo'").drop_duplicates("doc_id").set_index("doc_id")
    portraits = []
    for row in docs.drop_duplicates("doc_id").itertuples():
        if row.doc_id not in boxes.index:
            continue
        with Image.open(config.PROJECT_ROOT / row.image_path) as image:
            page = np.asarray(image.convert("RGB"))
        portraits.append((row.doc_id, face.crop_with_margin(page, boxes.loc[row.doc_id, ["x", "y", "w", "h"]].to_numpy(),
                                                            margin=0.4)))
    return portraits


def run_sidtd(verifier: inference.FaceVerifier) -> tuple[dict[str, list[dict]], list[str]]:
    portraits = sidtd_portraits()
    usable, skipped = [], []
    for doc_id, rgb in portraits:  # the turn needs the portrait's landmarks
        _, info = face.detect_and_align(rgb, verifier.detector, verifier.recognizer)
        (usable if info["landmarks"] is not None else skipped).append((doc_id, rgb, info["landmarks"]))
    turned = {doc_id: (jpeg(liveness_sim.synthetic_head_turn(rgb, lm, TURN)),
                       jpeg(liveness_sim.synthetic_head_turn(rgb, lm, -TURN))) for doc_id, rgb, lm in usable}
    results: dict[str, list[dict]] = {k: [] for k in ("sidtd_genuine_synthetic", "sidtd_static", "sidtd_different",
                                                     *(f"sidtd_tilt_{int(t)}" for t in TILTS))}
    for i, (doc_id, rgb, _) in enumerate(usable):
        neutral = jpeg(rgb)
        results["sidtd_genuine_synthetic"].append(verifier.liveness(neutral, *turned[doc_id]))
        results["sidtd_static"].append(verifier.liveness(neutral, neutral, neutral))
        for tilt in TILTS:
            results[f"sidtd_tilt_{int(tilt)}"].append(verifier.liveness(
                neutral, jpeg(liveness_sim.tilted_photo(rgb, -tilt)), jpeg(liveness_sim.tilted_photo(rgb, tilt))))
        other_a, other_b = usable[(i + 1) % len(usable)][0], usable[(i + 2) % len(usable)][0]
        results["sidtd_different"].append(verifier.liveness(neutral, turned[other_a][0], turned[other_b][1]))
    return results, [d for d, *_ in skipped]


def lfw_faces(verifier: inference.FaceVerifier, min_images: int = 10, per_person: int = 25) -> pd.DataFrame:
    """YuNet + SFace on up to `per_person` photos of every LFW person with at least `min_images` photos."""
    rows = []
    for person in sorted(p for p in LFW_IMAGES.iterdir() if p.is_dir()):
        photos = sorted(person.glob("*.jpg"))
        if len(photos) < min_images:
            continue
        for path in photos[:per_person]:
            embedding, summary = verifier._face(path.read_bytes(), with_landmarks=True)
            if embedding is None:
                continue
            rows.append({"person": person.name, "photo": path.name, "embedding": embedding,
                         "landmarks": summary["landmarks"], "yaw": liveness.estimate_yaw(summary["landmarks"])})
    return pd.DataFrame(rows)


def lfw_triplet(photos: pd.DataFrame, policy: liveness.LivenessPolicy):
    """The most frontal photo + the photos closest to a 30 degree turn each way (25-50 degrees from it), or None."""
    neutral = photos.loc[photos["yaw"].abs().idxmin()]
    if abs(neutral["yaw"]) > policy.max_neutral_yaw_deg:
        return None
    turn = photos["yaw"] - neutral["yaw"]
    sides = []
    for sign in (1, -1):
        band = photos[(sign * turn >= 25) & (sign * turn <= 50)]
        if band.empty:
            return None
        sides.append(band.loc[(sign * turn[band.index] - 30).abs().idxmin()])
    return neutral, sides[0], sides[1]


def run_lfw(verifier: inference.FaceVerifier) -> dict[str, list[dict]]:
    faces = lfw_faces(verifier)
    policy = verifier.liveness_policy
    frame = lambda row: liveness.FrameFace(row["landmarks"], row["embedding"])  # noqa: E731
    triplets = [t for _, photos in faces.groupby("person") if (t := lfw_triplet(photos, policy)) is not None]
    results = {"lfw_genuine_real_turns": [], "lfw_static": [], "lfw_different": []}
    for i, (neutral, left, right) in enumerate(triplets):
        results["lfw_genuine_real_turns"].append(liveness.evaluate(frame(neutral), frame(left), frame(right), policy))
        results["lfw_static"].append(liveness.evaluate(frame(neutral), frame(neutral), frame(neutral), policy))
        other_left, other_right = triplets[(i + 1) % len(triplets)][1], triplets[(i + 2) % len(triplets)][2]
        results["lfw_different"].append(liveness.evaluate(frame(neutral), frame(other_left), frame(other_right), policy))
    results["_lfw_people"] = [{"people_with_10_photos": int(faces["person"].nunique()), "triplets": len(triplets)}]
    return results


def summarise(name: str, results: list[dict]) -> dict:
    outcomes = Counter(outcome(r) for r in results)
    failures = Counter(f for r in results for f in r["failures"])
    turns = [r["turn_deg"] for r in results if r.get("turn_deg")]
    cosines = [min(r["same_person_cosine"].values()) for r in results if r.get("same_person_cosine")]
    left = [t["left"] for t in turns if "left" in t]
    right = [t["right"] for t in turns if "right" in t]
    def stats(values, digits=1):
        return {k: round(float(f(values)), digits) for k, f in (("min", np.min), ("median", np.median),
                                                                ("max", np.max))} if values else None

    return {"scenario": name, "n": len(results), "outcomes": dict(outcomes), "failures": dict(failures),
            "passed_share": round(outcomes["passed"] / len(results), 4) if results else None,
            "turn_left_deg": stats(left), "turn_right_deg": stats(right),
            "lowest_same_person_cosine": stats(cosines, 3)}


LABELS = {
    "lfw_genuine_real_turns": ("Genuine: real head turns (LFW, one person's photos)", "should pass"),
    "sidtd_genuine_synthetic": (f"Genuine: synthetic +-{TURN:.0f} degree turn (SIDTD test portraits)", "should pass"),
    "sidtd_static": ("Static photo: 3 identical frames (SIDTD)", "must fail"),
    "lfw_static": ("Static photo: 3 identical frames (LFW)", "must fail"),
    **{f"sidtd_tilt_{int(t)}": (f"Printed photo tilted +-{int(t)} degrees (SIDTD)", "must fail") for t in TILTS},
    "sidtd_different": ("Different people, each turned the right way (SIDTD, synthetic turns)", "must fail"),
    "lfw_different": ("Different people, real turns (LFW)", "must fail"),
}


def markdown(summary: list[dict], meta: dict) -> str:
    lines = ["# Phase 13: active liveness evaluation", "",
             "Generated by `scripts/evaluate_liveness.py`. Thresholds: turn >= "
             f"{meta['thresholds']['min_turn_deg']} degrees each way from the frame looking at the camera, that frame "
             f"within {meta['thresholds']['max_neutral_yaw_deg']} degrees of frontal, SFace cosine >= "
             f"{meta['thresholds']['same_person_min_cosine']} between the frames.", "",
             "| Scenario | Expected | Frames | Passed | Retake (failed) | Review high (different person) | Turns left / right (median) |",
             "|---|---|---:|---:|---:|---:|---|"]
    for s in summary:
        label, expected = LABELS[s["scenario"]]
        o = s["outcomes"]
        turns = (f"{s['turn_left_deg']['median']} / {s['turn_right_deg']['median']}"
                 if s["turn_left_deg"] and s["turn_right_deg"] else "–")
        lines.append(f"| {label} | {expected} | {s['n']} | {o.get('passed', 0)} | {o.get('failed', 0)} | "
                     f"{o.get('different_person', 0)} | {turns} |")
    lines += ["", "Failure reasons per scenario (a set of frames can have several):", ""]
    lines += [f"- {LABELS[s['scenario']][0]}: {s['failures'] or 'none'}" for s in summary]
    lines += ["", f"SIDTD portraits used: {meta['sidtd_portraits']} (no face found on {len(meta['sidtd_skipped'])}). "
              f"LFW: {meta['lfw']['triplets']} people with a frontal photo and a 25-50 degree turn each way, of "
              f"{meta['lfw']['people_with_10_photos']} with 10 or more photos.", ""]
    return "\n".join(lines) + "\n"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    verifier = inference.FaceVerifier()
    sidtd, skipped = run_sidtd(verifier)
    lfw = run_lfw(verifier)
    lfw_meta = lfw.pop("_lfw_people")[0]
    order = ["lfw_genuine_real_turns", "sidtd_genuine_synthetic", "sidtd_static", "lfw_static",
             *(f"sidtd_tilt_{int(t)}" for t in TILTS), "sidtd_different", "lfw_different"]
    everything = sidtd | lfw
    summary = [summarise(name, everything[name]) for name in order]
    meta = {"thresholds": {k: v for k, v in vars(verifier.liveness_policy).items() if k != "nose_depth"},
            "nose_depth": verifier.liveness_policy.nose_depth, "synthetic_turn_deg": TURN, "tilts_deg": list(TILTS),
            "sidtd_portraits": len(sidtd["sidtd_static"]), "sidtd_skipped": skipped, "lfw": lfw_meta,
            "decision": DECISION}
    (OUT / "liveness_eval.json").write_text(json.dumps({"meta": meta, "summary": summary}, indent=1))
    (OUT / "liveness_eval.md").write_text(markdown(summary, meta))
    print(markdown(summary, meta))
    contact_sheet(verifier)


def contact_sheet(verifier: inference.FaceVerifier, size: int = 200) -> None:
    """One SIDTD portrait through each scenario: neutral, left, right (with the measured yaw)."""
    doc_id, rgb = sidtd_portraits()[0]
    _, info = face.detect_and_align(rgb, verifier.detector, verifier.recognizer)
    rows = {"synthetic turn (genuine)": (rgb, liveness_sim.synthetic_head_turn(rgb, info["landmarks"], TURN),
                                         liveness_sim.synthetic_head_turn(rgb, info["landmarks"], -TURN)),
            "static photo": (rgb, rgb, rgb),
            f"tilted photo {int(TILTS[-1])} deg": (rgb, liveness_sim.tilted_photo(rgb, -TILTS[-1]),
                                                  liveness_sim.tilted_photo(rgb, TILTS[-1]))}
    sheet = []
    for title, frames in rows.items():
        result = verifier.liveness(*(jpeg(f) for f in frames))
        tiles = []
        for name, f in zip(("neutral", "left", "right"), frames):
            tile = cv2.resize(f, (size, round(size * f.shape[0] / f.shape[1])))[:size]
            tile = cv2.copyMakeBorder(tile, 0, size - tile.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
            yaw = result["yaw_deg"].get(name)
            label = f"{name} {'' if yaw is None else f'{yaw:+.0f}'}"
            cv2.putText(tile, label, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 4)  # white outline
            cv2.putText(tile, label, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1)
            tiles.append(tile)
        banner = np.full((28, size * 3, 3), 255, np.uint8)
        cv2.putText(banner, f"{title}: {result['status']} {result['failures'] or ''}", (6, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        sheet += [banner, np.hstack(tiles)]
    Image.fromarray(np.vstack(sheet)).save(OUT / "liveness_examples.png")
    print(f"wrote {OUT / 'liveness_examples.png'} (portrait {doc_id})")


if __name__ == "__main__":
    main()
