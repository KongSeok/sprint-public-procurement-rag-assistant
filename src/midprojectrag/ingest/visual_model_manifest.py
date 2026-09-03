"""Verify official local OCR assets; never rewrite a valid existing manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tarfile
import tempfile
import urllib.request
from pathlib import Path

# Independent pins from reviewed official paddle3.0.0 downloads (2026-09-02).
EXPECTED_FILES = {
    "PP-DocLayout-L_infer/inference.json": (1081389, "d25813273051801894d97c11725a246b529be6d3f0556298ac27a37305d2f21b"),
    "PP-DocLayout-L_infer/inference.pdiparams": (129021913, "4df69115349e1e6215629d058e3bc7f087cad7a0d2776ef40c463daf73c38982"),
    "PP-DocLayout-L_infer/inference.yml": (1871, "fbdbb903efd3d82db5800f9ae3e2477d2d84525956ef410ffe8e64bbaad02fa5"),
    "PP-OCRv5_server_det_infer/inference.json": (402480, "af5876933d8806a1b50d895867e0781e135cd92ff37381992828fc8d1b842d28"),
    "PP-OCRv5_server_det_infer/inference.pdiparams": (87932887, "183146fe9d9910352f68482f623bcbbb9fa7b9e8fa1463b9ad288cef00524d2d"),
    "PP-OCRv5_server_det_infer/inference.yml": (903, "28fb721efc3634fc8aa677e474b9602cb815a91cf569ef357a7a553d7b3ce685"),
    "korean_PP-OCRv5_mobile_rec_infer/inference.json": (217724, "562404e3c590c50c93778d5f0a94df21b47b5ab8f3ea6d47c7f8a7930c3bc844"),
    "korean_PP-OCRv5_mobile_rec_infer/inference.pdiparams": (13342671, "cac3e5f12cf04aaa77f6a5bc704e4e736ef2908476551891d84b41b4e9090462"),
    "korean_PP-OCRv5_mobile_rec_infer/inference.yml": (96039, "f757fa1c40e99edcf27e9cce879b93eb2a51fa46f5ef39095689b8c37dd75998"),
}
HEADER = {"schema_version": "1.0", "pipeline": "PP-StructureV3", "ocr_version": "PP-OCRv5",
          "language": "korean", "source_policy": "official-paddle-model-ecology"}
BASE_URL = "https://paddle-model-ecology.bj.bcebos.com/paddlex/official_inference_model/paddle3.0.0/"


class ModelManifestError(ValueError):
    """Content-free failure code, safe for public receipts."""


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _strict_pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelManifestError("duplicate_json_key")
        result[key] = value
    return result


def strict_json(text: str) -> dict:
    return json.loads(text, object_pairs_hook=_strict_pairs)


def checked_root(root: Path) -> Path:
    absolute = Path(os.path.abspath(root))
    if root.is_symlink() or absolute.resolve() != absolute:
        raise ModelManifestError("model_root_symlink_forbidden")
    return absolute


def expected_manifest() -> dict:
    return {**HEADER, "files": [{"path": name, "bytes": size, "sha256": digest}
                               for name, (size, digest) in sorted(EXPECTED_FILES.items())]}


def verify_files(root: Path) -> None:
    root = checked_root(root)
    if not root.is_dir():
        raise ModelManifestError("model_root_missing")
    actual = set()
    directories = {str(Path(name).parent) for name in EXPECTED_FILES}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ModelManifestError("model_symlink_forbidden")
        if path.is_dir() and name in directories:
            continue
        if not path.is_file():
            raise ModelManifestError("model_file_set_mismatch")
        if name != "model-manifest.json":
            actual.add(name)
    if actual != set(EXPECTED_FILES):
        raise ModelManifestError("model_file_set_mismatch")
    for name, (size, digest) in EXPECTED_FILES.items():
        path = root / name
        if path.stat().st_size != size or file_sha256(path) != digest:
            raise ModelManifestError("model_weight_checksum_mismatch")


def verify_manifest(root: Path) -> str:
    root = checked_root(root)
    verify_files(root)
    path = root / "model-manifest.json"
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ModelManifestError("model_manifest_missing_or_oversize")
    if strict_json(path.read_text(encoding="utf-8")) != expected_manifest():
        raise ModelManifestError("model_manifest_contract_mismatch")
    return file_sha256(path)


def publish_manifest(root: Path) -> str:
    root = checked_root(root)
    if (root / "model-manifest.json").exists():
        return verify_manifest(root)
    verify_files(root)
    payload = (json.dumps(expected_manifest(), ensure_ascii=False, indent=2) + "\n").encode()
    fd, name = tempfile.mkstemp(prefix=".manifest-", dir=root)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, root / "model-manifest.json")
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return verify_manifest(root)


def provision(root: Path, *, allow_download: bool = False) -> str:
    root = checked_root(root)
    if root.exists():
        return publish_manifest(root)
    if not allow_download:
        raise ModelManifestError("model_download_not_authorized")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ocr-provision-", dir=root.parent) as work:
        stage = Path(work) / "models"
        stage.mkdir(mode=0o700)
        for family in sorted({str(Path(name).parent) for name in EXPECTED_FILES}):
            archive = Path(work) / (family + ".tar")
            with urllib.request.urlopen(BASE_URL + family + ".tar", timeout=120) as response:
                with archive.open("xb") as output:
                    size = 0
                    while data := response.read(1024 * 1024):
                        size += len(data)
                        if size > 180 * 1024 * 1024:
                            raise ModelManifestError("model_download_size_exceeded")
                        output.write(data)
            seen = set()
            with tarfile.open(archive) as source:
                for member in source:
                    name = member.name.removeprefix("./")
                    if member.isdir() and name.rstrip("/") == family:
                        continue
                    if (not member.isfile() or name not in EXPECTED_FILES
                            or Path(name).parent.as_posix() != family or name in seen
                            or member.size != EXPECTED_FILES[name][0]):
                        raise ModelManifestError("model_archive_member_invalid")
                    seen.add(name)
                    target = stage / name
                    target.parent.mkdir(mode=0o700, exist_ok=True)
                    with source.extractfile(member) as content, target.open("xb") as output:
                        while data := content.read(1024 * 1024):
                            output.write(data)
        digest = publish_manifest(stage)
        if root.exists():
            raise ModelManifestError("model_root_concurrent_publication")
        stage.rename(root)
    return digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--download", action="store_true", help="Only fetch when root is absent")
    args = parser.parse_args()
    try:
        digest = provision(args.root, allow_download=args.download)
    except (OSError, ValueError, tarfile.TarError):
        print(json.dumps({"status": "failed", "code": "visual_model_provision_failed"}))
        return 2
    print(json.dumps({"status": "verified", "files": len(EXPECTED_FILES), "manifest_sha256": digest}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
