"""Synthetic-only tests for the no-network PDF recovery verifier."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from verify_hosted_pdf_recovery import verify_and_copy


class PrivatePdfRecoveryTest(unittest.TestCase):
    def test_verified_independent_copy_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "downloaded-private-pdfs"
            original.mkdir()
            key = "12345678-1234-1234-1234-123456789abc.pdf"
            content = b"%PDF-1.4\nSynthetic test content only\n%%EOF"
            (original / key).write_bytes(content)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({
                "objects": [{
                    "key": key,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                }]
            }), encoding="utf-8")
            receipt = verify_and_copy(manifest, original, root / "restore")
            self.assertEqual(receipt["result"], "PASS_LOCAL_FILE_RESTORE_ONLY")
            self.assertEqual((root / "restore" / key).read_bytes(), content)
            (original / key).write_bytes(content + b"tampered")
            with self.assertRaises(ValueError):
                verify_and_copy(manifest, original, root / "should-not-exist")
            self.assertFalse((root / "should-not-exist").exists())

    def test_rejects_repeated_or_unsafe_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "files"
            source.mkdir()
            path = root / "manifest.json"
            for key in ("../not-a-pdf", "12345678-1234-1234-1234-123456789abc.pdf"):
                obj = {"key": key, "sha256": "0" * 64, "size_bytes": 10}
                path.write_text(json.dumps({"objects": [obj, obj]}), encoding="utf-8")
                with self.assertRaises(ValueError):
                    verify_and_copy(path, source, root / "restore")
                self.assertFalse((root / "restore").exists())


if __name__ == "__main__":
    unittest.main()
