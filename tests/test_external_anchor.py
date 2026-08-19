from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.external_anchor as ea


class ExternalAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        data = root / "data"
        data.mkdir()
        self.chain = data / "integrity-chain.json"
        self.provenance = data / "run-provenance.json"
        self.signed = data / "signed-integrity-head.json"
        self.request = data / "external-anchor-request.json"
        self.receipt = data / "external-anchor-receipt.json"
        self.chain.write_text(json.dumps({"sequence": 4, "headSha256": "a" * 64}), encoding="utf-8")
        self.provenance.write_text(json.dumps({"provenanceSha256": "b" * 64, "identity": {"repository":"x1-dotcom/x1epg","commitSha":"c"*40,"runId":"44","runAttempt":"1"}}), encoding="utf-8")
        self.patches = [
            patch.object(ea, "ROOT", root),
            patch.object(ea, "DATA", data),
            patch.object(ea, "CHAIN", self.chain),
            patch.object(ea, "PROVENANCE", self.provenance),
            patch.object(ea, "SIGNED", self.signed),
            patch.object(ea, "REQUEST", self.request),
            patch.object(ea, "RECEIPT", self.receipt),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def test_unsigned_anchor_request_is_still_buildable(self):
        payload = ea.build_request()
        self.assertEqual(payload["anchor"]["integritySequence"], 4)
        self.assertIsNone(payload["anchor"]["signatureBase64"])
        self.assertEqual(len(payload["anchorSha256"]), 64)

    def test_signed_anchor_binds_signature_fingerprint(self):
        self.signed.write_text(json.dumps({"keyFingerprintSha256":"d"*64,"signatureBase64":"YWJj"}), encoding="utf-8")
        payload = ea.build_request()
        self.assertEqual(payload["anchor"]["keyFingerprintSha256"], "d" * 64)
        self.assertEqual(payload["anchor"]["signatureBase64"], "YWJj")

    def test_tampered_request_fails_verification(self):
        ea.build_request()
        payload = json.loads(self.request.read_text(encoding="utf-8"))
        payload["anchor"]["integrityHeadSha256"] = "e" * 64
        self.request.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(RuntimeError):
            ea.verify()

    def test_matching_receipt_verifies(self):
        payload = ea.build_request()
        self.receipt.write_text(json.dumps({"receipt":{"anchorSha256":payload["anchorSha256"],"immutableId":"abc","anchoredAt":"2026-08-19T00:00:00Z"}}), encoding="utf-8")
        self.assertTrue(ea.verify()["receiptPresent"])


if __name__ == "__main__":
    unittest.main()
