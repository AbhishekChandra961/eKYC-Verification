"""Write a small demo set to demo_samples/ (gitignored) for trying the frontend by hand (Phase 8).

    .venv/bin/python scripts/make_demo_samples.py

Synthetic SIDTD documents from the TEST split only (no real people):
  genuine_1..3  a genuine template + a simulated selfie of its own portrait  -> expected AUTO_APPROVED
  forged_1..2   a forged template (inpaint-and-rewrite) + a stranger's selfie  -> expected MANUAL_REVIEW (high)
  blank         an almost black image as the ID document                        -> expected RESUBMIT_REQUIRED
plus README.md (what to type for each sample), manifest.json (the same, for the Playwright test) and, for the smart
selfie camera (Phase 13):
  camera/genuine_1_head_turn.y4m  a "fake webcam" video for Chromium (--use-file-for-fake-video-capture): the genuine_1
                                  selfie looking at the camera, then turned left, then right (looped), so the camera
                                  path, its head-turn challenge and the server's liveness check can be tested with a
                                  face that matches the ID. The turns are SYNTHETIC (ekyc.liveness_sim, +-25 degrees):
                                  no real head-turn video of these synthetic faces exists.
  genuine_1_camera_{neutral,left,right}.jpg  the same three frames as images (for scripts/e2e_api_smoke.py)
  ../frontend/e2e-demo/fixtures/camera/{neutral,left,right}.jpg  the same frames, committed for the demo site's
                                  Playwright test (CI has no SIDTD data; e2e-demo/fakeCamera.ts turns them into a video)

How the genuine documents were chosen: test-split templates whose saved Phase 3 forgery score is below 0.6 and whose
saved Phase 5 extraction passes every consistency rule and matches the true name and date of birth (73 of 147
qualify); one each of three document types, preferring documents that have not expired. The forged ones are
inpaint-and-rewrite fakes the forgery model scores 1.0. This is a demo selection, not an evaluation.

Needs only the SIDTD templates in data/interim/templates (README quickstart), not the clips or the Phase 2 manifest:
the sample ids are fixed below. If data/processed/manifest.csv exists, the script also checks they are TEST-split.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from ekyc import config, data, face, liveness_sim, schemas

OUT = config.PROJECT_ROOT / "demo_samples"
E2E_DEMO_CAMERA = config.PROJECT_ROOT / "frontend" / "e2e-demo" / "fixtures" / "camera"
HEAD_TURN_DEG = 35.0  # the fake webcam's synthetic turn: measured ~22 degrees in the browser (it asks for 20) and
# +35 / -28 on the server (it needs 20), same-person similarity ~0.35 (needs 0.2597)
GENUINE = ["srb_passport_16", "alb_id_81", "lva_passport_41"]
FORGED = ["aze_passport_75_fake_3_39", "esp_id_14_fake_2_85"]
STRANGER = "grc_passport_72"  # the "stranger" whose portrait becomes the selfie for the forged documents


def template(doc_id: str | None = None, fake_name: str | None = None) -> pd.Series:
    """One template straight from data/interim/templates (ekyc.data.template_record), with a clear message if missing."""
    try:
        return data.template_record(doc_id=doc_id, fake_name=fake_name)
    except FileNotFoundError as error:
        raise SystemExit(str(error))


def check_test_split() -> None:
    """The samples must come from the TEST split (never trained or tuned on). Checked when the manifest exists."""
    docs = GENUINE + [STRANGER] + [template(fake_name=f)["doc_id"] for f in FORGED]
    if not data.check_test_split(docs):
        print("note: data/processed/manifest.csv not found, test-split check skipped (the ids are fixed above)")


def selfie_jpeg(image_path: str, doc_id: str, boxes: pd.DataFrame, seed: int) -> np.ndarray:
    """The document's own portrait, made to look like a phone selfie (rotation, scale, light, blur, JPEG)."""
    with Image.open(config.PROJECT_ROOT / image_path) as image:
        page = np.asarray(image.convert("RGB"))
    crop = face.crop_with_margin(page, boxes.loc[doc_id, ["x", "y", "w", "h"]].to_numpy())
    return face.simulate_selfie(crop, np.random.default_rng(seed))[0]


def save_jpeg(array: np.ndarray, path: Path, quality: int = 92) -> None:
    Image.fromarray(array).save(path, format="JPEG", quality=quality)


def camera_frame(selfie: np.ndarray, size: tuple[int, int] = (640, 480)) -> np.ndarray:
    """What the fake webcam shows: the selfie centred on a grey background."""
    width, height = size
    canvas = Image.new("RGB", size, (128, 128, 128))
    photo = Image.fromarray(selfie)
    photo.thumbnail((width, height - 40))
    canvas.paste(photo, ((width - photo.width) // 2, (height - photo.height) // 2))
    return np.asarray(canvas)


def head_turn_frames(frame: np.ndarray) -> dict[str, np.ndarray]:
    """The frame looking at the camera, then with the head synthetically turned left and right (liveness_sim)."""
    detector, recognizer = face.load_face_models()
    _, info = face.detect_and_align(frame, detector, recognizer, pick="largest")
    if info["landmarks"] is None:
        raise SystemExit("no face found on the genuine_1 camera frame")
    return {"neutral": frame, "left": liveness_sim.synthetic_head_turn(frame, info["landmarks"], HEAD_TURN_DEG),
            "right": liveness_sim.synthetic_head_turn(frame, info["landmarks"], -HEAD_TURN_DEG)}


def write_y4m(frames: list[np.ndarray], path: Path, fps: int = 5, seconds_each: float = 2.0) -> None:
    """A Y4M video (I420): each frame held for `seconds_each`, in order. Chromium loops it as a webcam."""
    height, width = frames[0].shape[:2]
    with path.open("wb") as handle:
        handle.write(f"YUV4MPEG2 W{width} H{height} F{fps}:1 Ip A1:1 C420jpeg\n".encode())
        for frame in frames:
            ycbcr = np.asarray(Image.fromarray(frame).convert("YCbCr"))
            planes = ycbcr[:, :, 0].tobytes() + ycbcr[::2, ::2, 1].tobytes() + ycbcr[::2, ::2, 2].tobytes()  # 4:2:0
            for _ in range(round(fps * seconds_each)):
                handle.write(b"FRAME\n" + planes)


def main() -> None:
    check_test_split()
    fields = data.parse_ground_truth()  # the annotated boxes and values (what data/processed/fields_ground_truth.csv holds)
    boxes = fields.query("field_name == 'photo'").set_index("doc_id")
    truth = schemas.ground_truth_table(fields)
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "camera").mkdir(parents=True)

    samples = []
    for i, doc_id in enumerate(GENUINE, start=1):
        row = template(doc_id=doc_id)
        t = truth.loc[doc_id]
        shutil.copyfile(config.PROJECT_ROOT / row["image_path"], OUT / f"genuine_{i}_id.jpg")
        selfie = selfie_jpeg(row["image_path"], doc_id, boxes, seed=i)
        save_jpeg(selfie, OUT / f"genuine_{i}_selfie.jpg")
        if i == 1:
            turns = head_turn_frames(camera_frame(selfie))
            write_y4m([turns["neutral"], turns["left"], turns["right"]], OUT / "camera" / "genuine_1_head_turn.y4m")
            E2E_DEMO_CAMERA.mkdir(parents=True, exist_ok=True)
            for pose, frame in turns.items():
                save_jpeg(frame, OUT / f"genuine_1_camera_{pose}.jpg")
                save_jpeg(frame, E2E_DEMO_CAMERA / f"{pose}.jpg", quality=85)
        samples.append({"name": f"genuine_{i}", "id_image": f"genuine_{i}_id.jpg", "selfie": f"genuine_{i}_selfie.jpg",
                        "full_name": f"{t.given_names} {t.surname}",
                        "date_of_birth": schemas.parse_date(t.birth_date, "birth_date"),
                        "document": f"{doc_id} (genuine {row['doc_type']})",
                        "expected": "with the camera's head-turn frames: AUTO_APPROVED -> APPROVED (customer: Verified); "
                                    "with an uploaded photo: MANUAL_REVIEW, medium risk (no head-turn check)"})

    stranger = template(doc_id=STRANGER)
    stranger_selfie = selfie_jpeg(stranger["image_path"], STRANGER, boxes, seed=99)
    for i, fake_name in enumerate(FORGED, start=1):
        row = template(fake_name=fake_name)
        t = truth.loc[row["doc_id"]]  # the fraudster types the original holder's details
        shutil.copyfile(config.PROJECT_ROOT / row["image_path"], OUT / f"forged_{i}_id.jpg")
        save_jpeg(stranger_selfie, OUT / f"forged_{i}_selfie_stranger.jpg")
        samples.append({"name": f"forged_{i}", "id_image": f"forged_{i}_id.jpg", "selfie": f"forged_{i}_selfie_stranger.jpg",
                        "full_name": f"{t.given_names} {t.surname}",
                        "date_of_birth": schemas.parse_date(t.birth_date, "birth_date"),
                        "document": f"{fake_name} (forged {row['doc_type']}, edited field: {row.get('altered_field', 'see JSON')})",
                        "expected": "MANUAL_REVIEW, high risk (customer: Under review)"})

    save_jpeg(np.full((630, 1000, 3), 4, np.uint8), OUT / "blank_id.jpg")
    samples.append({"name": "blank", "id_image": "blank_id.jpg", "selfie": "genuine_1_selfie.jpg",
                    "full_name": samples[0]["full_name"], "date_of_birth": samples[0]["date_of_birth"],
                    "document": "an almost black image", "expected": "RESUBMIT_REQUIRED -> RESUBMIT_REQUESTED (customer: Please resubmit)"})

    (OUT / "manifest.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n")
    lines = ["# Demo samples (synthetic SIDTD test documents, not real people)", "",
             "Generated by `scripts/make_demo_samples.py`. Not committed (gitignored).", "",
             "Log in as the demo customer, click **Verify my identity**, type the name and date of birth below and upload "
             "the ID image. For the selfie, use the fake webcam below (your own face will not match a synthetic ID; it "
             "would go to manual review), or choose **Upload a photo instead**.", "",
             "| Sample | ID image | Selfie | Full name to type | Date of birth | Expected |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['name']} | `{s['id_image']}` | `{s['selfie']}` | {s['full_name']} | {s['date_of_birth']} | {s['expected']} |"
              for s in samples]
    lines += ["", "Documents: " + "; ".join(f"{s['name']} = {s['document']}" for s in samples), "",
              "## Webcam with a matching face (Chromium)", "",
              "`camera/genuine_1_head_turn.y4m` is a fake webcam: the genuine_1 selfie looking at the camera, then turned "
              f"left, then right (a SYNTHETIC +-{HEAD_TURN_DEG:.0f} degree turn, looped every 6 s), so the smart camera's "
              "head-turn challenge completes by itself and the server's liveness check passes. Start Chrome with:", "",
              "```bash", "open -na 'Google Chrome' --args --user-data-dir=/tmp/ekyc-demo-chrome "
              "--use-fake-ui-for-media-stream --use-fake-device-for-media-stream "
              f"--use-file-for-fake-video-capture={OUT / 'camera' / 'genuine_1_head_turn.y4m'} http://localhost:5173",
              "```", "", "Uploading a photo instead works too, but then there is no head-turn check, and even a genuine "
              "sample goes to a medium-risk manual review (Phase 13).", ""]
    (OUT / "README.md").write_text("\n".join(lines))
    print(f"wrote {len(list(OUT.rglob('*')))} files to {OUT.relative_to(config.PROJECT_ROOT)}/")
    for s in samples:
        print(f"  {s['name']:<9} {s['document']:<70} -> {s['expected']}")


if __name__ == "__main__":
    main()
