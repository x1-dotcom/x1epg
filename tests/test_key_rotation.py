from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

import tools.key_rotation as kr


def openssl(*args: str) -> None:
    proc = subprocess.run(["openssl", *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))


def fingerprint(public_key: Path) -> str:
    proc = subprocess.run(["openssl", "pkey", "-pubin", "-in", str(public_key), "-outform", "DER"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace"))
    return hashlib.sha256(proc.stdout).hexdigest()


class KeyRotationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "keys").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def make_key(self, key_id: str) -> tuple[Path, str]:
        private = self.root / f"{key_id}-private.pem"
        public = self.root / "keys" / f"{key_id}.pem"
        openssl("genpkey", "-algorithm", "ED25519", "-out", str(private))
        openssl("pkey", "-in", str(private), "-pubout", "-out", str(public))
        return public, fingerprint(public)

    def test_empty_keyring_is_valid(self):
        payload = {"schemaVersion": 1, "activeKeyId": None, "keys": [], "transitions": []}
        result = kr.validate_keyring(payload, self.root)
        self.assertEqual(result["activeKeyId"], None)

    def test_single_active_key_is_valid(self):
        _, fp = self.make_key("key-2026")
        payload = {
            "schemaVersion": 1,
            "activeKeyId": "key-2026",
            "keys": [{
                "keyId": "key-2026",
                "algorithm": "Ed25519",
                "publicKeyPath": "keys/key-2026.pem",
                "fingerprintSha256": fp,
                "status": "active",
                "createdAt": "2026-08-19T00:00:00Z"
            }],
            "transitions": []
        }
        self.assertEqual(kr.validate_keyring(payload, self.root)["status"], "PASS")

    def test_two_active_keys_are_rejected(self):
        _, fp1 = self.make_key("key-a")
        _, fp2 = self.make_key("key-b")
        payload = {
            "schemaVersion": 1,
            "activeKeyId": "key-a",
            "keys": [
                {"keyId":"key-a","algorithm":"Ed25519","publicKeyPath":"keys/key-a.pem","fingerprintSha256":fp1,"status":"active","createdAt":"2026-08-19T00:00:00Z"},
                {"keyId":"key-b","algorithm":"Ed25519","publicKeyPath":"keys/key-b.pem","fingerprintSha256":fp2,"status":"active","createdAt":"2026-08-19T00:00:00Z"}
            ],
            "transitions": []
        }
        with self.assertRaises(RuntimeError):
            kr.validate_keyring(payload, self.root)

    def test_fingerprint_mismatch_is_rejected(self):
        self.make_key("key-a")
        payload = {
            "schemaVersion": 1,
            "activeKeyId": "key-a",
            "keys": [{"keyId":"key-a","algorithm":"Ed25519","publicKeyPath":"keys/key-a.pem","fingerprintSha256":"0"*64,"status":"active","createdAt":"2026-08-19T00:00:00Z"}],
            "transitions": []
        }
        with self.assertRaises(RuntimeError):
            kr.validate_keyring(payload, self.root)

    def test_rotation_transition_requires_known_keys(self):
        _, fp = self.make_key("key-a")
        payload = {
            "schemaVersion": 1,
            "activeKeyId": "key-a",
            "keys": [{"keyId":"key-a","algorithm":"Ed25519","publicKeyPath":"keys/key-a.pem","fingerprintSha256":fp,"status":"active","createdAt":"2026-08-19T00:00:00Z"}],
            "transitions": [{"transitionId":"rotate-1","fromKeyId":"missing","toKeyId":"key-a","effectiveAt":"2026-08-19T00:00:00Z","approvedBy":"owner","reason":"test"}]
        }
        with self.assertRaises(RuntimeError):
            kr.validate_keyring(payload, self.root)


if __name__ == "__main__":
    unittest.main()
