"""Download the trained models (a GitHub release asset), verify them and unpack them into models/ (Phase 10).

    .venv/bin/python scripts/download_models.py                    # from the GitHub release (config.MODEL_RELEASE_URL)
    .venv/bin/python scripts/download_models.py --zip release/ekyc-models-v1.0.zip   # a local copy, offline

Two integrity checks, so a broken or tampered download never reaches the services:
1. the whole zip's SHA-256 must equal config.MODEL_RELEASE_SHA256 (stored in git, so it cannot be swapped together
   with the download);
2. every file inside must match its line in the zip's SHA256SUMS. Each file is hashed while it is unpacked to a
   temporary name and only then renamed into place.

Safety rules:
- only names listed in SHA256SUMS are unpacked, and every name must stay inside models/ (no absolute paths, no "..",
  the "zip slip" attack);
- a file already in models/ with the right checksum is skipped; a DIFFERENT existing file (e.g. a model you retrained)
  is never overwritten unless you pass --force. All conflicts are checked BEFORE anything is written.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from ekyc import config

CHUNK = 1 << 20  # 1 MiB


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, dest: Path) -> None:
    """Stream `url` to `dest`, printing progress every 10 %. GitHub's release link redirects to its file storage;
    urllib follows the redirect. A generic User-Agent: no personal details go to the server."""
    request = urllib.request.Request(url, headers={"User-Agent": "ekyc-download-models"})
    with urllib.request.urlopen(request, timeout=60) as response, dest.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done, next_report = 0, 10
        for chunk in iter(lambda: response.read(CHUNK), b""):
            out.write(chunk)
            done += len(chunk)
            if total and done * 100 // total >= next_report:
                print(f"  {done / 1e6:6.1f} / {total / 1e6:.1f} MB")
                next_report += 10


def read_checksums(archive: zipfile.ZipFile) -> dict[str, str]:
    """SHA256SUMS ('<hex>  <name>' per line) -> {name: hex}, after checking every name is safe and present."""
    sums = {}
    for line in archive.read("SHA256SUMS").decode("utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        name = name.strip()
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name or len(digest) != 64:
            raise ValueError(f"unsafe or malformed SHA256SUMS line: {line!r}")
        sums[name] = digest.lower()
    names = set(archive.namelist()) - {"SHA256SUMS"}
    if extra := names - set(sums):
        raise ValueError(f"files in the zip without a checksum: {sorted(extra)}")
    if missing := set(sums) - names:
        raise ValueError(f"SHA256SUMS lists files the zip does not contain: {sorted(missing)}")
    return sums


def install(zip_path: Path, models_dir: Path, force: bool = False) -> dict[str, list[str]]:
    """Unpack the release zip into models_dir after the checks above. Returns {'installed': [...], 'skipped': [...]}."""
    models_dir = models_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        sums = read_checksums(archive)
        plan, conflicts = {}, []
        for name, digest in sorted(sums.items()):
            target = (models_dir / name).resolve()
            if models_dir not in target.parents:
                raise ValueError(f"{name} would be written outside {models_dir}")
            if target.exists() and sha256_file(target) == digest:
                plan[name] = "skip"
            else:
                plan[name] = "write"
                if target.exists() and not force:
                    conflicts.append(name)
        if conflicts:
            raise FileExistsError(f"these files in models/ differ from the release (use --force to replace them): {conflicts}")

        for name, action in plan.items():
            if action == "skip":
                continue
            target = models_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_name(target.name + ".part")
            digest = hashlib.sha256()
            with archive.open(name) as src, part.open("wb") as dst:
                for chunk in iter(lambda: src.read(CHUNK), b""):
                    digest.update(chunk)
                    dst.write(chunk)
            if digest.hexdigest() != sums[name]:
                part.unlink()
                raise ValueError(f"checksum mismatch for {name}: the zip is corrupted")
            part.replace(target)
        (models_dir / "SHA256SUMS").write_bytes(archive.read("SHA256SUMS"))  # so `shasum -a 256 -c` works later
    return {"installed": [n for n, a in plan.items() if a == "write"],
            "skipped": [n for n, a in plan.items() if a == "skip"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zip", type=Path, help="use this local zip instead of downloading")
    parser.add_argument("--url", default=config.MODEL_RELEASE_URL, help="release asset URL (default: config)")
    parser.add_argument("--sha256", default=config.MODEL_RELEASE_SHA256, help="expected SHA-256 of the zip")
    parser.add_argument("--force", action="store_true", help="replace files in models/ that differ from the release")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = args.zip
        if zip_path is None:
            zip_path = Path(tmp) / config.MODEL_RELEASE_FILE
            print(f"downloading {args.url}")
            download(args.url, zip_path)
        digest = sha256_file(zip_path)
        if digest != args.sha256.lower():
            print(f"ERROR: {zip_path.name} has SHA-256 {digest}, expected {args.sha256}. Nothing was unpacked.")
            return 1
        print(f"zip SHA-256 OK ({digest[:16]}...)")
        try:
            result = install(zip_path, config.MODELS_DIR, force=args.force)
        except (ValueError, FileExistsError) as error:
            print(f"ERROR: {error}")
            return 1
    print(f"models/: {len(result['installed'])} file(s) installed, {len(result['skipped'])} already up to date; "
          "every file matched SHA256SUMS")
    for name in result["installed"]:
        print(f"  + {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
