#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from tools.safe_http import SameHostHTTPSRedirectHandler, _assert_public_dns, _validate_https_url

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CHAIN = DATA / "integrity-chain.json"
SIGNED = DATA / "signed-integrity-head.json"
PROVENANCE = DATA / "run-provenance.json"
REQUEST = DATA / "external-anchor-request.json"
RECEIPT = DATA / "external-anchor-receipt.json"
ANCHOR_URL_ENV = "X1_EPG_EXTERNAL_ANCHOR_URL"
ANCHOR_TOKEN_ENV = "X1_EPG_EXTERNAL_ANCHOR_TOKEN"
MAX_RECEIPT_BYTES = 1024 * 1024


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.exists() else None


def load_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(f"required file missing: {path.relative_to(ROOT)}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def build_request() -> dict:
    chain = load_json(CHAIN)
    provenance = load_json(PROVENANCE)
    signed = load_json(SIGNED) if SIGNED.exists() else None
    core = {
        "schemaVersion": 1,
        "repository": provenance.get("identity", {}).get("repository") if isinstance(provenance.get("identity"), dict) else None,
        "commitSha": provenance.get("identity", {}).get("commitSha") if isinstance(provenance.get("identity"), dict) else None,
        "runId": provenance.get("identity", {}).get("runId") if isinstance(provenance.get("identity"), dict) else None,
        "runAttempt": provenance.get("identity", {}).get("runAttempt") if isinstance(provenance.get("identity"), dict) else None,
        "integritySequence": chain.get("sequence"),
        "integrityHeadSha256": chain.get("headSha256"),
        "provenanceSha256": provenance.get("provenanceSha256"),
        "signedIntegrityHeadSha256": sha256_path(SIGNED),
        "keyFingerprintSha256": signed.get("keyFingerprintSha256") if isinstance(signed, dict) else None,
        "signatureBase64": signed.get("signatureBase64") if isinstance(signed, dict) else None,
    }
    for field in ("integrityHeadSha256", "provenanceSha256"):
        value = core[field]
        if not isinstance(value, str) or len(value) != 64:
            raise RuntimeError(f"invalid {field}")
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "anchor": core,
        "anchorSha256": sha256_bytes(canonical_json_bytes(core)),
        "policy": "External transparency anchor request. A receipt only proves that an external service acknowledged this exact anchor hash; it does not grant source rights or imply runtime quality.",
    }
    REQUEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"External anchor request: {payload['anchorSha256']}")
    return payload


def submit() -> dict:
    url = os.environ.get(ANCHOR_URL_ENV)
    token = os.environ.get(ANCHOR_TOKEN_ENV)
    if not url:
        raise RuntimeError(f"{ANCHOR_URL_ENV} is not configured")
    if not token:
        raise RuntimeError(f"{ANCHOR_TOKEN_ENV} is not configured")
    payload = build_request()
    body = canonical_json_bytes(payload)

    host, _ = _validate_https_url(url)
    _assert_public_dns(host)
    opener = urllib.request.build_opener(SameHostHTTPSRedirectHandler(host, max_redirects=1))
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "User-Agent": "X1-EPG/1.0 (+https://github.com/x1-dotcom/x1epg)",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with opener.open(req, timeout=30) as resp:
            final_host, _ = _validate_https_url(resp.geturl())
            if final_host != host:
                raise RuntimeError("external anchor redirected to a different host")
            _assert_public_dns(final_host)
            data = resp.read(MAX_RECEIPT_BYTES + 1)
            if len(data) > MAX_RECEIPT_BYTES:
                raise RuntimeError("external anchor receipt exceeds safety limit")
            content_type = resp.headers.get_content_type() if resp.headers else None
            if content_type not in {"application/json", "text/json"}:
                raise RuntimeError(f"unexpected anchor receipt content type: {content_type!r}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"external anchor submission failed: {exc}") from exc

    try:
        receipt = json.loads(data.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("external anchor receipt is not valid UTF-8 JSON") from exc
    if not isinstance(receipt, dict):
        raise RuntimeError("external anchor receipt must be an object")
    if receipt.get("anchorSha256") != payload["anchorSha256"]:
        raise RuntimeError("external anchor receipt does not acknowledge the submitted anchor hash")
    if not receipt.get("immutableId") or not receipt.get("anchoredAt"):
        raise RuntimeError("external anchor receipt lacks immutableId/anchoredAt")

    record = {
        "schemaVersion": 1,
        "requestSha256": sha256_path(REQUEST),
        "anchorSha256": payload["anchorSha256"],
        "endpointHost": host,
        "receipt": receipt,
        "recordedAt": datetime.now(timezone.utc).isoformat(),
    }
    RECEIPT.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"External anchor: RECORDED id={receipt['immutableId']} hash={payload['anchorSha256']}")
    return record


def verify() -> dict:
    request = load_json(REQUEST)
    expected = request.get("anchorSha256")
    rebuilt = sha256_bytes(canonical_json_bytes(request.get("anchor")))
    if expected != rebuilt:
        raise RuntimeError("external anchor request hash mismatch")
    if RECEIPT.exists():
        record = load_json(RECEIPT)
        receipt = record.get("receipt")
        if not isinstance(receipt, dict) or receipt.get("anchorSha256") != expected:
            raise RuntimeError("external anchor receipt does not match request")
    print(f"External anchor: PASS hash={expected} receipt={'yes' if RECEIPT.exists() else 'no'}")
    return {"status": "PASS", "anchorSha256": expected, "receiptPresent": RECEIPT.exists()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "submit", "verify"))
    args = parser.parse_args()
    if args.command == "build":
        build_request()
    elif args.command == "submit":
        submit()
    else:
        verify()


if __name__ == "__main__":
    main()
