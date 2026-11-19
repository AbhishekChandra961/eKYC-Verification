"""The model release package (Phase 10): scripts/build_model_release.py + scripts/download_models.py.

Runs on tiny fake "models" in a temporary folder: no weights, services or data needed (runs in CI).
"""

import importlib.util
import zipfile

import pytest

from ekyc import config


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, config.PROJECT_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_script("build_model_release")
download = load_script("download_models")


@pytest.fixture
def release(tmp_path):
    """A small release zip with two files (one in a sub-folder), built by the real build function."""
    src = tmp_path / "src"
    (src / "face").mkdir(parents=True)
    (src / "a.keras").write_bytes(b"weights-a")
    (src / "face" / "b.onnx").write_bytes(b"weights-b")
    out = tmp_path / "release.zip"
    build.build_zip([("a.keras", src / "a.keras"), ("face/b.onnx", src / "face" / "b.onnx")], out, "readme\n")
    return out


def test_release_unpacks_verifies_and_is_idempotent(release, tmp_path):
    models = tmp_path / "models"
    first = download.install(release, models)
    assert sorted(first["installed"]) == ["README.txt", "a.keras", "face/b.onnx"]
    assert (models / "face" / "b.onnx").read_bytes() == b"weights-b"
    assert not list(models.rglob("*.part"))
    second = download.install(release, models)  # same files again: nothing to do
    assert second["installed"] == [] and len(second["skipped"]) == 3


def test_build_is_deterministic(release, tmp_path):
    again = tmp_path / "again.zip"
    with zipfile.ZipFile(release) as archive:
        files = []
        for name in ("a.keras", "face/b.onnx"):
            path = tmp_path / "copy" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(archive.read(name))
            files.append((name, path))
    build.build_zip(files, again, "readme\n")
    assert build.sha256_file(again) == build.sha256_file(release)


def test_a_changed_local_model_is_not_overwritten_without_force(release, tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "a.keras").write_bytes(b"my retrained model")
    with pytest.raises(FileExistsError):
        download.install(release, models)
    assert (models / "a.keras").read_bytes() == b"my retrained model"
    assert not (models / "face").exists()  # conflicts are found before anything is written
    download.install(release, models, force=True)
    assert (models / "a.keras").read_bytes() == b"weights-a"


def tampered_zip(path, sums_text, members):
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in members.items():
            archive.writestr(name, payload)
        archive.writestr("SHA256SUMS", sums_text)
    return path


def test_a_file_that_does_not_match_its_checksum_is_rejected(tmp_path):
    bad = tampered_zip(tmp_path / "bad.zip", f"{'0' * 64}  a.keras\n", {"a.keras": b"swapped"})
    with pytest.raises(ValueError, match="checksum mismatch"):
        download.install(bad, tmp_path / "models")
    assert not (tmp_path / "models" / "a.keras").exists()


@pytest.mark.parametrize("name", ["../evil.txt", "/etc/evil.txt"])
def test_zip_slip_names_are_rejected(tmp_path, name):
    bad = tampered_zip(tmp_path / "slip.zip", f"{'0' * 64}  {name}\n", {name: b"x"})
    with pytest.raises(ValueError, match="unsafe"):
        download.install(bad, tmp_path / "models")
    assert not (tmp_path / "evil.txt").exists()


def test_files_without_a_checksum_are_rejected(tmp_path):
    bad = tampered_zip(tmp_path / "extra.zip", "", {"unlisted.bin": b"x"})
    with pytest.raises(ValueError, match="without a checksum"):
        download.install(bad, tmp_path / "models")


def test_release_config_lists_only_the_production_models():
    names = set(config.MODEL_RELEASE_FILES)
    assert {"doc_classifier.keras", "forgery_detector.keras", "face/face_recognition_sface_2021dec.onnx"} <= names
    assert not any("v1" in n or "v2" in n or "stage" in n for n in names)  # comparison models and checkpoints stay out
    assert len(config.MODEL_RELEASE_SHA256) == 64
    assert config.MODEL_RELEASE_URL.endswith(f"/{config.MODEL_RELEASE_VERSION}/{config.MODEL_RELEASE_FILE}")
