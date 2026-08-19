from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.signed_provenance as sp


def openssl(*args: str) -> None:
    proc = subprocess.run(["openssl", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))


class SignedProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.keys = root / "keys"
        self.data.mkdir()
        self.keys.mkdir()
        self.private = root / "private.pem"
        self.public = self.keys / "x1-epg-ed25519-public.pem"
        openssl("genpkey", "-algorithm", "ED25519", "-out", str(self.private))
        openssl("pkey", "-in", str(self.private), "-pubout", "-out", str(self.public))
        self.chain = self.data / "integrity-chain.json"
        self.provenance = self.data / "run-provenance.json"
        self.signed = self.data / "signed-integrity-head.json"
        self.chain.write_text(json.dumps({
            "sequence": 7,
            "headSha256": "a" * 64,
        }), encoding="utf-8")
        self.provenance.write_text(json.dumps({
            "provenanceSha256": "b" * 64,
            "identity": {
                "repository": "x1-dotcom/x1epg",
                "commitSha": "c" * 40,
                "runId": "123",
                "runAttempt": "1",
            },
        }), encoding="utf-8")
        self.patches = [
            patch.object(sp, "ROOT", root),
            patch.object(sp, "DATA", self.data),
            patch.object(sp, "CHAIN", self.chain),
            patch.object(sp, "PROVENANCE", self.provenance),
            patch.object(sp, "PUBLIC_KEY", self.public),
            patch.object(sp, "SIGNED_HEAD", self.signed),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_sign_then_verify(self):
        with patch.dict(os.environ, {sp.PRIVATE_ENV: self.private.read_text(encoding="utf-8")}, clear=False):
            record = sp.sign()
        self.assertEqual(record["payload"]["algorithm"], "Ed25519")
        self.assertEqual(record["payload"]["integritySequence"], 7)
        result = sp.verify()
        self.assertEqual(result["status"], "PASS")

    def test_tampered_head_is_rejected(self):
        with patch.dict(os.environ, {sp.PRIVATE_ENV: self.private.read_text(encoding="utf-8")}, clear=False):
            sp.sign()
        self.chain.write_text(json.dumps({"sequence": 7, "headSha256": "d" * 64}), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            sp.verify()

    def test_wrong_private_key_is_rejected(self):
        other = Path(self.tmp.name) / "other.pem"
        openssl("genpkey", "-algorithm", "ED25519", "-out", str(other))
        with patch.dict(os.environ, {sp.PRIVATE_ENV: other.read_text(encoding="utf-8")}, clear=False):
            with self.assertRaises(RuntimeError):
                sp.sign()

    def test_missing_private_key_fails_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                sp.sign()

    def test_signature_tampering_is_rejected(self):
        with patch.dict(os.environ, {sp.PRIVATE_ENV: self.private.read_text(encoding="utf-8")}, clear=False):
            sp.sign()
        record = json.loads(self.signed.read_text(encoding="utf-8"))
        signature = record["signatureBase64"]
        record["signatureBase64"] = ("A" if signature[0] != "A" else "B") + signature[1:]
        self.signed.write_text(json.dumps(record), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            sp.verify()


if __name__ == "__main__":
    unittest.main()
