"""Offline integrity validation and independent local copy of private PDF backups.

This does NOT read Neon credentials or signed URLs, alter remote storage, or
prove an S3 restore. It verifies user-supplied original bytes against the
authoritative database manifest, then verifies a new separate local copy.

Usage:
    python scripts/verify_hosted_pdf_recovery.py manifest.json PRIVATE_PDFS NEW_RESTORE_DIR
"""
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

KEY = re.compile(r"^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\.pdf$")
SHA = re.compile(r"^[0-9a-f]{64}$")
MAX_BYTES = 2 * 1024 * 1024


def check_file(path: Path, expected_sha: str, expected_size: int):
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Missing, non-regular or linked PDF: {path.name}")
    if path.stat().st_size != expected_size:
        raise ValueError(f"Incorrect private PDF size: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(256 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha:
        raise ValueError(f"SHA-256 mismatch: {path.name}")


def verify_and_copy(manifest_path: Path, source: Path, target: Path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    objects = manifest["objects"]
    if not isinstance(objects, list) or not objects:
        raise ValueError("Nonempty objects list required")
    seen = set()
    for item in objects:
        key, sha, size = item["key"], item["sha256"], item["size_bytes"]
        if (not isinstance(key, str) or not KEY.fullmatch(key)
                or key in seen or not isinstance(sha, str) or not SHA.fullmatch(sha)
                or type(size) is not int or not 0 < size <= MAX_BYTES):
            raise ValueError("Invalid/repeated private PDF metadata")
        seen.add(key)

    source = source.resolve(strict=True)
    if target.exists() or target.is_symlink():
        raise FileExistsError("Target must be a new, nonexisting directory")
    if source == target.resolve() or source in target.resolve().parents:
        raise ValueError("Target cannot contain or be inside source directory")
    # All originals must pass before any target directory is created.
    for item in objects:
        check_file(source / item["key"], item["sha256"], item["size_bytes"])

    target.mkdir(mode=0o700)
    for item in objects:
        old, new = source / item["key"], target / item["key"]
        with old.open("rb") as src, new.open("xb") as dst:
            try:
                os.chmod(new, 0o600)
            except OSError:
                pass  # Windows applies directory ACLs.
            shutil.copyfileobj(src, dst, length=256 * 1024)
        check_file(new, item["sha256"], item["size_bytes"])

    receipt = {
        "result": "PASS_LOCAL_FILE_RESTORE_ONLY",
        "count": len(objects),
        "bytes": sum(item["size_bytes"] for item in objects),
        "objects": [{k: item[k] for k in ("key", "sha256", "size_bytes")} for item in objects],
    }
    (target / "verification_receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    try:
        receipt = verify_and_copy(
            Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        sys.exit(f"RECOVERY CHECK FAILED: {exc}")
    print(f"PASS: {receipt['count']} PDF digests matched original and copied bytes")
