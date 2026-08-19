#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CHAIN = DATA / "integrity-chain.json"
PROVENANCE = DATA / "run-provenance.json"
PUBLIC_KEY = ROOT / "keys" / "x1-epg-ed25519-public.pem"
SIGNED_HEAD = DATA / "signed-integrity-head.json"
PRIVATE_ENV = "X1_EPG_ED25519_PRIVATE_KEY_PEM"


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def run_openssl(args: list[str], *, input_bytes: bytes | None = None) -> bytes:
    try:
        proc = subprocess.run(
            ["openssl", *args],
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("openssl executable is required for Ed25519 signing/verification") from exc
    if proc.returncode != 0:
        error = proc.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"openssl failed: {error or 'unknown error'}")
    return proc.stdout


def public_der_from_public_pem(path: Path) -> bytes:
    if not path.exists():
        raise RuntimeError(f"public key missing: {path.relative_to(ROOT)}")
    return run_openssl(["pkey", "-pubin", "-in", str(path), "-outform", "DER"])


def public_der_from_private_pem(private_pem: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        private_path = Path(tmp) / "private.pem"
        private_path.write_text(private_pem, encoding="utf-8")
        try:
            return run_openssl(["pkey", "-in", str(private_path), "-pubout", "-outform", "DER"])
        finally:
            private_path.write_text("", encoding="utf-8")


def key_fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def load_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"required file missing: {path.relative_to(ROOT)}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{path.relative_to(ROOT)} must contain a JSON object")
    return payload


def signing_payload(chain: dict, provenance: dict) -> dict:
    head = chain.get("headSha256")
    provenance_sha = provenance.get("provenanceSha256")
    if not isinstance(head, str) or len(head) != 64:
        raise RuntimeError("integrity-chain.json has no valid headSha256")
    if not isinstance(provenance_sha, str) or len(provenance_sha) != 64:
        raise RuntimeError("run-provenance.json has no valid provenanceSha256")
    identity = provenance.get("identity", {}) if isinstance(provenance.get("identity"), dict) else {}
    return {
        "schemaVersion": 1,
        "algorithm": "Ed25519",
        "integritySequence": chain.get("sequence"),
        "integrityHeadSha256": head,
        "provenanceSha256": provenance_sha,
        "repository": identity.get("repository"),
        "commitSha": identity.get("commitSha"),
        "runId": identity.get("runId"),
        "runAttempt": identity.get("runAttempt"),
    }


def sign() -> dict:
    private_pem = os.environ.get(PRIVATE_ENV)
    if not private_pem:
        raise RuntimeError(f"{PRIVATE_ENV} is not configured")

    chain = load_json(CHAIN)
    provenance = load_json(PROVENANCE)
    payload = signing_payload(chain, provenance)
    message = canonical_json_bytes(payload)

    expected_public_der = public_der_from_public_pem(PUBLIC_KEY)
    derived_public_der = public_der_from_private_pem(private_pem)
    expected_fp = key_fingerprint(expected_public_der)
    derived_fp = key_fingerprint(derived_public_der)
    if expected_fp != derived_fp:
        raise RuntimeError("private signing key does not match committed Ed25519 public key")

    with tempfile.TemporaryDirectory() as tmp:
        private_path = Path(tmp) / "private.pem"
        message_path = Path(tmp) / "message.bin"
        signature_path = Path(tmp) / "signature.bin"
        private_path.write_text(private_pem, encoding="utf-8")
        message_path.write_bytes(message)
        try:
            run_openssl([
                "pkeyutl", "-sign", "-rawin",
                "-inkey", str(private_path),
                "-in", str(message_path),
                "-out", str(signature_path),
            ])
            signature = signature_path.read_bytes()
        finally:
            private_path.write_text("", encoding="utf-8")

    record = {
        "schemaVersion": 1,
        "payload": payload,
        "keyFingerprintSha256": expected_fp,
        "signatureBase64": base64.b64encode(signature).decode("ascii"),
        "policy": "Ed25519 signature over the canonical integrity-head/provenance payload. The private key must remain outside the repository and is expected from GitHub Actions secret X1_EPG_ED25519_PRIVATE_KEY_PEM.",
    }
    SIGNED_HEAD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    verify()
    print(f"Signed integrity head: sequence={payload.get('integritySequence')} key={expected_fp}")
    return record


def verify() -> dict:
    record = load_json(SIGNED_HEAD)
    payload = record.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("signed-integrity-head.json payload missing")
    if payload.get("algorithm") != "Ed25519":
        raise RuntimeError("signed payload algorithm must be Ed25519")

    current_payload = signing_payload(load_json(CHAIN), load_json(PROVENANCE))
    if payload != current_payload:
        raise RuntimeError("signed payload does not match current integrity head and provenance")

    public_der = public_der_from_public_pem(PUBLIC_KEY)
    fingerprint = key_fingerprint(public_der)
    if record.get("keyFingerprintSha256") != fingerprint:
        raise RuntimeError("signed record key fingerprint does not match committed public key")

    signature_b64 = record.get("signatureBase64")
    if not isinstance(signature_b64, str):
        raise RuntimeError("signatureBase64 missing")
    try:
        signature = base64.b64decode(signature_b64, validate=True)
    except Exception as exc:
        raise RuntimeError("signatureBase64 is invalid") from exc

    message = canonical_json_bytes(payload)
    with tempfile.TemporaryDirectory() as tmp:
        message_path = Path(tmp) / "message.bin"
        signature_path = Path(tmp) / "signature.bin"
        message_path.write_bytes(message)
        signature_path.write_bytes(signature)
        run_openssl([
            "pkeyutl", "-verify", "-rawin", "-pubin",
            "-inkey", str(PUBLIC_KEY),
            "-in", str(message_path),
            "-sigfile", str(signature_path),
        ])

    result = {
        "status": "PASS",
        "algorithm": "Ed25519",
        "keyFingerprintSha256": fingerprint,
        "integritySequence": payload.get("integritySequence"),
        "integrityHeadSha256": payload.get("integrityHeadSha256"),
        "provenanceSha256": payload.get("provenanceSha256"),
    }
    print(f"Signed integrity head: PASS sequence={result['integritySequence']} key={fingerprint}")
    return result


def status() -> dict:
    configured = PUBLIC_KEY.exists()
    result = {
        "publicKeyConfigured": configured,
        "privateKeyAvailableInEnvironment": bool(os.environ.get(PRIVATE_ENV)),
        "signedHeadExists": SIGNED_HEAD.exists(),
    }
    if configured:
        result["keyFingerprintSha256"] = key_fingerprint(public_der_from_public_pem(PUBLIC_KEY))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("sign", "verify", "status"))
    args = parser.parse_args()
    if args.command == "sign":
        sign()
    elif args.command == "verify":
        verify()
    else:
        status()


if __name__ == "__main__":
    main()
