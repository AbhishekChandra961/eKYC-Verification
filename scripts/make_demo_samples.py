"""Write a small demo set to demo_samples/ (gitignored) for trying the frontend by hand (Phase 8).

    .venv/bin/python scripts/make_demo_samples.py

Synthetic SIDTD documents from the TEST split only (no real people):
  genuine_1..3  a genuine template + a simulated selfie of its own portrait  -> expected AUTO_APPROVED
  forged_1..2   a forged template (inpaint-and-rewrite) + a stranger's selfie  -> expected MANUAL_REVIEW (high)
  blank         an almost black image as the ID document                        -> expected RESUBMIT_REQUIRED
plus README.md (what to type for each sample), manifest.json (the same, for the Playwright test) and
camera/genuine_1.y4m: a "fake webcam" video for Chromium (--use-file-for-fake-video-capture), so the webcam path can
be tested with a face that matches the ID.

How the genuine documents were chosen: test-split templates whose saved Phase 3 forgery score is below 0.6 and whose
saved Phase 5 extraction passes every consistency rule and matches the true name and date of birth (73 of 147
qualify); one each of three document types, preferring documents that have not expired. The forged ones are
inpaint-and-rewrite fakes the forgery model scores 1.0. This is a demo selection, not an evaluation.
"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image

from ekyc import config, face, schemas

OUT = config.PROJECT_ROOT / "demo_samples"
GENUINE = ["srb_passport_16", "alb_id_81", "lva_passport_41"]
FORGED = ["aze_passport_75_fake_3_39", "esp_id_14_fake_2_85"]
STRANGER = "grc_passport_72"  # the "stranger" whose portrait becomes the selfie for the forged documents


def manifest_row(manifest: pd.DataFrame, doc_id: str | None = None, fake_name: str | None = None) -> pd.Series:
    rows = manifest[(manifest["source"] == "template") & (manifest["split"] == "test")]
    rows = rows[rows["fake_name"] == fake_name] if fake_name else rows[(rows["doc_id"] == doc_id) & (rows["label"] == 0)]
    if len(rows) != 1:
        raise SystemExit(f"expected one test template for {doc_id or fake_name}, found {len(rows)}")
    return rows.iloc[0]


def selfie_jpeg(image_path: str, doc_id: str, boxes: pd.DataFrame, seed: int) -> np.ndarray:
    """The document's own portrait, made to look like a phone selfie (rotation, scale, light, blur, JPEG)."""
    with Image.open(config.PROJECT_ROOT / image_path) as image:
        page = np.asarray(image.convert("RGB"))
    crop = face.crop_with_margin(page, boxes.loc[doc_id, ["x", "y", "w", "h"]].to_numpy())
    return face.simulate_selfie(crop, np.random.default_rng(seed))[0]


def save_jpeg(array: np.ndarray, path: Path, quality: int = 92) -> None:
    Image.fromarray(array).save(path, format="JPEG", quality=quality)


def write_y4m(selfie: np.ndarray, path: Path, frames: int = 5, size: tuple[int, int] = (640, 480)) -> None:
    """A tiny Y4M video (I420): the selfie centred on a grey background, repeated. Chromium loops it as a webcam."""
    width, height = size
    canvas = Image.new("RGB", size, (128, 128, 128))
    photo = Image.fromarray(selfie)
    photo.thumbnail((width, height - 40))
    canvas.paste(photo, ((width - photo.width) // 2, (height - photo.height) // 2))
    ycbcr = np.asarray(canvas.convert("YCbCr"))
    y = ycbcr[:, :, 0]
    u = ycbcr[::2, ::2, 1]  # 4:2:0 chroma subsampling
    v = ycbcr[::2, ::2, 2]
    with path.open("wb") as handle:
        handle.write(f"YUV4MPEG2 W{width} H{height} F30:1 Ip A1:1 C420jpeg\n".encode())
        for _ in range(frames):
            handle.write(b"FRAME\n" + y.tobytes() + u.tobytes() + v.tobytes())


def main() -> None:
    manifest = pd.read_csv(config.MANIFEST_CSV)
    fields = pd.read_csv(config.FIELDS_GT_CSV)
    boxes = fields.query("field_name == 'photo'").set_index("doc_id")
    truth = schemas.ground_truth_table(fields)
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "camera").mkdir(parents=True)

    samples = []
    for i, doc_id in enumerate(GENUINE, start=1):
        row = manifest_row(manifest, doc_id=doc_id)
        t = truth.loc[doc_id]
        shutil.copyfile(config.PROJECT_ROOT / row["image_path"], OUT / f"genuine_{i}_id.jpg")
        selfie = selfie_jpeg(row["image_path"], doc_id, boxes, seed=i)
        save_jpeg(selfie, OUT / f"genuine_{i}_selfie.jpg")
        if i == 1:
            write_y4m(selfie, OUT / "camera" / "genuine_1.y4m")
        samples.append({"name": f"genuine_{i}", "id_image": f"genuine_{i}_id.jpg", "selfie": f"genuine_{i}_selfie.jpg",
                        "full_name": f"{t.given_names} {t.surname}",
                        "date_of_birth": schemas.parse_date(t.birth_date, "birth_date"),
                        "document": f"{doc_id} (genuine {row['doc_type']})", "expected": "AUTO_APPROVED (customer: Verified)"})

    stranger = manifest_row(manifest, doc_id=STRANGER)
    stranger_selfie = selfie_jpeg(stranger["image_path"], STRANGER, boxes, seed=99)
    for i, fake_name in enumerate(FORGED, start=1):
        row = manifest_row(manifest, fake_name=fake_name)
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
                    "document": "an almost black image", "expected": "RESUBMIT_REQUIRED (customer: Please resubmit)"})

    (OUT / "manifest.json").write_text(json.dumps(samples, indent=2, ensure_ascii=False) + "\n")
    lines = ["# Demo samples (synthetic SIDTD test documents, not real people)", "",
             "Generated by `scripts/make_demo_samples.py`. Not committed (gitignored).", "",
             "Log in as the demo customer, click **Verify my identity**, type the name and date of birth below, upload "
             "the ID image, and for the selfie choose **Upload a photo instead** (your own face will not match a "
             "synthetic ID; it would go to manual review).", "",
             "| Sample | ID image | Selfie | Full name to type | Date of birth | Expected |", "|---|---|---|---|---|---|"]
    lines += [f"| {s['name']} | `{s['id_image']}` | `{s['selfie']}` | {s['full_name']} | {s['date_of_birth']} | {s['expected']} |"
              for s in samples]
    lines += ["", "Documents: " + "; ".join(f"{s['name']} = {s['document']}" for s in samples), "",
              "## Webcam with a matching face (Chromium)", "",
              "`camera/genuine_1.y4m` is a fake webcam showing the genuine_1 selfie. Start Chrome with:", "",
              "```bash", "open -na 'Google Chrome' --args --user-data-dir=/tmp/ekyc-demo-chrome "
              "--use-fake-ui-for-media-stream --use-fake-device-for-media-stream "
              f"--use-file-for-fake-video-capture={OUT / 'camera' / 'genuine_1.y4m'} http://localhost:5173", "```", ""]
    (OUT / "README.md").write_text("\n".join(lines))
    print(f"wrote {len(list(OUT.rglob('*')))} files to {OUT.relative_to(config.PROJECT_ROOT)}/")
    for s in samples:
        print(f"  {s['name']:<9} {s['document']:<70} -> {s['expected']}")


if __name__ == "__main__":
    main()
