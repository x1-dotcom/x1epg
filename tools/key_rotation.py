#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / "keys"
KEYRING = KEYS / "keyring.json"
SIGNING_PUBLIC_KEY = KEYS / "x1-epg-ed25519-public.pem"
KEY_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def load_keyring(path: Path = KEYRING) -> dict:
    if not path.exists():
        raise RuntimeError("keys/keyring.json missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("keyring must be a JSON object")
    return payload


def public_key_fingerprint(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"public key missing: {path}")
    proc = subprocess.run(
        ["openssl", "pkey", "-pubin", "-in", str(path), "-outform", "DER"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", errors="replace").strip() or "invalid public key")
    return hashlib.sha256(proc.stdout).hexdigest()


def validate_keyring(payload: dict, root: Path = ROOT) -> dict:
    if payload.get("schemaVersion") != 1:
        raise RuntimeError("keyring schemaVersion must be 1")
    keys = payload.get("keys")
    transitions = payload.get("transitions")
    if not isinstance(keys, list) or not isinstance(transitions, list):
        raise RuntimeError("keyring keys/transitions must be arrays")

    by_id: dict[str, dict] = {}
    active_ids: list[str] = []
    for row in keys:
        if not isinstance(row, dict):
            raise RuntimeError("keyring key rows must be objects")
        required = {"keyId", "algorithm", "publicKeyPath", "fingerprintSha256", "status", "createdAt"}
        if not required.issubset(row):
            raise RuntimeError(f"key row missing fields: {sorted(required - set(row))}")
        key_id = row["keyId"]
        if not isinstance(key_id, str) or not KEY_ID_RE.fullmatch(key_id):
            raise RuntimeError(f"invalid keyId: {key_id!r}")
        if key_id in by_id:
            raise RuntimeError(f"duplicate keyId: {key_id}")
        if row["algorithm"] != "Ed25519":
            raise RuntimeError(f"{key_id}: algorithm must be Ed25519")
        if row["status"] not in {"active", "retired"}:
            raise RuntimeError(f"{key_id}: invalid status")
        if row["status"] == "active":
            active_ids.append(key_id)
        fp = row["fingerprintSha256"]
        if not isinstance(fp, str) or not HEX64.fullmatch(fp):
            raise RuntimeError(f"{key_id}: invalid fingerprintSha256")
        rel = Path(row["publicKeyPath"])
        if rel.is_absolute() or ".." in rel.parts or not str(rel).startswith("keys/"):
            raise RuntimeError(f"{key_id}: publicKeyPath must stay under keys/")
        actual = public_key_fingerprint(root / rel)
        if actual != fp:
            raise RuntimeError(f"{key_id}: public key fingerprint mismatch")
        by_id[key_id] = row

    configured_active = payload.get("activeKeyId")
    if keys:
        if len(active_ids) != 1:
            raise RuntimeError("exactly one active key is required when keyring is non-empty")
        if configured_active != active_ids[0]:
            raise RuntimeError("activeKeyId does not match active key status")
    elif configured_active is not None:
        raise RuntimeError("empty keyring must have activeKeyId=null")

    seen_transition_ids: set[str] = set()
    for row in transitions:
        if not isinstance(row, dict):
            raise RuntimeError("transition rows must be objects")
        required = {"transitionId", "fromKeyId", "toKeyId", "effectiveAt", "approvedBy", "reason"}
        if not required.issubset(row):
            raise RuntimeError("transition record missing required fields")
        tid = row["transitionId"]
        if not isinstance(tid, str) or not KEY_ID_RE.fullmatch(tid):
            raise RuntimeError(f"invalid transitionId: {tid!r}")
        if tid in seen_transition_ids:
            raise RuntimeError(f"duplicate transitionId: {tid}")
        seen_transition_ids.add(tid)
        from_id = row["fromKeyId"]
        to_id = row["toKeyId"]
        if from_id is not None and from_id not in by_id:
            raise RuntimeError(f"{tid}: unknown fromKeyId")
        if to_id not in by_id:
            raise RuntimeError(f"{tid}: unknown toKeyId")
        if from_id == to_id:
            raise RuntimeError(f"{tid}: rotation cannot point to the same key")

    return {
        "status": "PASS",
        "keyCount": len(keys),
        "transitionCount": len(transitions),
        "activeKeyId": configured_active,
    }


def verify_signing_key_alignment(payload: dict | None = None, root: Path = ROOT) -> dict:
    payload = load_keyring(root / "keys" / "keyring.json") if payload is None else payload
    result = validate_keyring(payload, root)
    if result["keyCount"] == 0:
        if (root / "keys" / "x1-epg-ed25519-public.pem").exists():
            raise RuntimeError("legacy signing public key exists but keyring has no active authority")
        return {**result, "signingPublicKeyConfigured": False, "signingKeyAligned": True}

    active_id = result["activeKeyId"]
    active = next(row for row in payload["keys"] if row["keyId"] == active_id)
    signing_public = root / "keys" / "x1-epg-ed25519-public.pem"
    if not signing_public.exists():
        raise RuntimeError("active keyring authority exists but signing public key alias is missing")
    alias_fp = public_key_fingerprint(signing_public)
    if alias_fp != active["fingerprintSha256"]:
        raise RuntimeError("signing public key alias does not match active keyring authority")
    return {**result, "signingPublicKeyConfigured": True, "signingKeyAligned": True, "activeFingerprintSha256": alias_fp}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify", "status", "verify-signing-key"))
    args = parser.parse_args()
    if args.command == "verify-signing-key":
        result = verify_signing_key_alignment()
    else:
        result = validate_keyring(load_keyring())
    if args.command == "status":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif args.command == "verify-signing-key":
        print(f"Signing key alignment: PASS configured={result['signingPublicKeyConfigured']} active={result['activeKeyId']}")
    else:
        print(f"Keyring: PASS keys={result['keyCount']} transitions={result['transitionCount']} active={result['activeKeyId']}")


if __name__ == "__main__":
    main()
