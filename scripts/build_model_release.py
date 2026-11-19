"""Build the model weights release package (Phase 10): release/ekyc-models-v1.0.zip.

    .venv/bin/python scripts/build_model_release.py

models/ is gitignored (weights are large binaries), so the trained models are published as ONE GitHub release asset
instead; scripts/download_models.py downloads, verifies and unpacks it. The zip holds exactly the files the running
system and the notebooks' final results need (config.MODEL_RELEASE_FILES):
  doc_classifier.keras + .json      document type classifier (Phase 3A)
  forgery_detector.keras + .json    forgery detector v3, the accepted model (Phase 3B v3)
  face/*.onnx + their licence files YuNet (MIT) + SFace (Apache 2.0) from the OpenCV Zoo (Phase 4, production path)
  face_config.json                  face thresholds (Phase 4)
  face_siamese.keras                the Siamese network (Phase 4 showcase, never used by the pipeline)
plus README.txt (what each file is) and SHA256SUMS (one line per file, `shasum -a 256 -c SHA256SUMS` format).

Left out on purpose: the v1/v2 forgery comparison models (forgery_detector_v1_confounded = shortcut learning,
forgery_detector_v2_compression_cue = residual compression cue; their small JSONs stay in git as the record), and the
training checkpoints (*_stage1/2, forgery_b1/b2, forgery_tiles_*, forgery_v3_tiles_*), which are intermediate copies.

The zip is deterministic: fixed file order, timestamps and permissions, so rebuilding it from the same models gives
the same bytes and the same SHA-256 (the value stored in config.MODEL_RELEASE_SHA256).
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

from ekyc import config

OUT = config.PROJECT_ROOT / "release" / config.MODEL_RELEASE_FILE
FIXED_TIME = (2026, 11, 19, 0, 0, 0)  # every entry gets this timestamp, so the zip bytes do not depend on file dates

README = """eKYC verification pipeline: trained models, release {version}

Unpack into the project's models/ folder (scripts/download_models.py does this and checks every file).
Check by hand:  cd models && shasum -a 256 -c SHA256SUMS

doc_classifier.keras / .json   document type classifier: EfficientNetB0 (frozen) + head, 224 px, 10 SIDTD types;
                               reject below max softmax 0.77
forgery_detector.keras / .json forgery detector v3: EfficientNetB0 on 224 px tiles of 1280 px pages; page score =
                               max tile score; apply the preprocessing in the JSON (q75 save at original size ->
                               resize -> q75); policy thresholds 0.729 (review) / 0.857383 (suspected)
face/face_detection_yunet_2023mar.onnx   YuNet face detector, OpenCV Zoo, MIT licence (LICENSE_yunet_MIT.txt)
face/face_recognition_sface_2021dec.onnx SFace face recognizer, OpenCV Zoo, Apache 2.0 (LICENSE_sface_Apache-2.0.txt)
face_config.json               face verification thresholds (cosine 0.2597 at the LFW 1% FAR target)
face_siamese.keras             Siamese network trained on LFW: a deep-learning showcase, NOT used by the pipeline

Trained on synthetic SIDTD documents (MIDV-2020 based) and LFW for research and education. Not validated on real
identity documents or real selfie-ID pairs: do not use for real KYC decisions.
Not included: the v1/v2 forgery comparison models and training checkpoints (see the project README).
"""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16  # rw-r--r--
    return info


def build_zip(files: list[tuple[str, Path]], out: Path, readme: str) -> dict[str, str]:
    """Write `files` ([(name inside the zip, source path)]) + README.txt + SHA256SUMS to `out`.
    Returns {name: sha256} as written to SHA256SUMS."""
    sums = {name: sha256_file(path) for name, path in files}
    sums["README.txt"] = hashlib.sha256(readme.encode()).hexdigest()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w") as archive:
        archive.writestr(_entry("README.txt"), readme)
        for name, path in sorted(files):
            with path.open("rb") as src, archive.open(_entry(name), "w") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
        archive.writestr(_entry("SHA256SUMS"), "".join(f"{sums[n]}  {n}\n" for n in sorted(sums)))
    tmp.replace(out)
    return sums


def main() -> int:
    files = [(name, config.MODELS_DIR / name) for name in config.MODEL_RELEASE_FILES]
    missing = [name for name, path in files if not path.is_file()]
    if missing:
        print(f"missing in models/: {missing}")
        return 1
    sums = build_zip(files, OUT, README.format(version=config.MODEL_RELEASE_VERSION))
    for name in sorted(sums):
        size = (config.MODELS_DIR / name).stat().st_size if name != "README.txt" else 0
        print(f"  {sums[name][:12]}  {size / 1e6:7.1f} MB  {name}")
    digest = sha256_file(OUT)
    print(f"\n{OUT.relative_to(config.PROJECT_ROOT)}: {OUT.stat().st_size / 1e6:.1f} MB, {len(sums)} files + SHA256SUMS")
    print(f"SHA-256 {digest}")
    if digest != config.MODEL_RELEASE_SHA256:
        print("NOTE: differs from config.MODEL_RELEASE_SHA256: update that value before publishing the release")
        return 2
    print("matches config.MODEL_RELEASE_SHA256")
    return 0


if __name__ == "__main__":
    sys.exit(main())
