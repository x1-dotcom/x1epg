#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "run-provenance.json"

TRACKED_FILES = [
    DATA / "index.json",
    DATA / "lkg-state.json",
    DATA / "lkg-decision.json",
    DATA / "global-validation.json",
    DATA / "catalog-coverage.json",
    DATA / "channel-list-validation.json",
    DATA / "sync-report.json",
    DATA / "runtime-failure-forensics.json",
    DATA / "merge-report.json",
    DATA / "quality-decision-report.json",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str | None:
    if not path.exists():
        return None
    return sha256_bytes(path.read_bytes())


def canonical_json_digest(payload: object) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(encoded)


def manifest_inventory(root: Path = ROOT) -> list[dict]:
    rows = []
    for path in sorted((root / "sources").glob("*.json")):
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        rows.append({
            "path": str(path.relative_to(root)),
            "sha256": sha256_bytes(raw),
            "canonicalJsonSha256": canonical_json_digest(payload),
            "sourceGroup": payload.get("sourceGroup"),
            "country": payload.get("country"),
            "channelCount": len(payload.get("channels", [])),
            "sourceIds": sorted(s.get("sourceId") for s in payload.get("sources", []) if s.get("sourceId")),
        })
    return rows


def upstream_inventory(data_dir: Path = DATA) -> list[dict]:
    rows: list[dict] = []
    channel_list_path = data_dir / "channel-list-validation.json"
    if channel_list_path.exists():
        payload = json.loads(channel_list_path.read_text(encoding="utf-8"))
        for source in payload.get("sources", []):
            if source.get("channelListSha256"):
                rows.append({
                    "sourceId": source.get("sourceId"),
                    "kind": "channel-list",
                    "url": source.get("channelListUrl"),
                    "sha256": source.get("channelListSha256"),
                    "bytes": source.get("channelListBytes"),
                    "status": source.get("status"),
                })
    sync_path = data_dir / "sync-report.json"
    if sync_path.exists():
        payload = json.loads(sync_path.read_text(encoding="utf-8"))
        for source in payload.get("sources", []):
            if source.get("compressedSha256"):
                rows.append({
                    "sourceId": source.get("sourceId"),
                    "kind": "xmltv-wire",
                    "url": source.get("url"),
                    "sha256": source.get("compressedSha256"),
                    "bytes": source.get("compressedBytes"),
                    "status": source.get("status"),
                })
            if source.get("xmlSha256"):
                rows.append({
                    "sourceId": source.get("sourceId"),
                    "kind": "xmltv-decoded",
                    "url": source.get("url"),
                    "sha256": source.get("xmlSha256"),
                    "bytes": source.get("xmlBytes"),
                    "status": source.get("status"),
                })
    return sorted(rows, key=lambda r: (r.get("sourceId") or "", r["kind"]))


def file_inventory(root: Path = ROOT) -> list[dict]:
    rows = []
    for path in TRACKED_FILES:
        actual = root / path.relative_to(ROOT) if root != ROOT else path
        rows.append({
            "path": str(actual.relative_to(root)),
            "exists": actual.exists(),
            "sha256": sha256_path(actual),
            "bytes": actual.stat().st_size if actual.exists() else None,
        })
    return rows


def build_provenance(root: Path = ROOT, data_dir: Path = DATA, env: dict[str, str] | None = None) -> dict:
    env = os.environ if env is None else env
    manifests = manifest_inventory(root)
    upstream = upstream_inventory(data_dir)
    files = file_inventory(root)
    identity = {
        "repository": env.get("GITHUB_REPOSITORY"),
        "commitSha": env.get("GITHUB_SHA"),
        "ref": env.get("GITHUB_REF"),
        "workflow": env.get("GITHUB_WORKFLOW"),
        "workflowRef": env.get("GITHUB_WORKFLOW_REF"),
        "runId": env.get("GITHUB_RUN_ID"),
        "runNumber": env.get("GITHUB_RUN_NUMBER"),
        "runAttempt": env.get("GITHUB_RUN_ATTEMPT"),
        "actor": env.get("GITHUB_ACTOR"),
        "eventName": env.get("GITHUB_EVENT_NAME"),
        "serverUrl": env.get("GITHUB_SERVER_URL"),
    }
    provenance_core = {
        "identity": identity,
        "manifests": manifests,
        "upstreamArtifacts": upstream,
        "outputs": files,
    }
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": "Forensic provenance only. Digests prove byte identity observed by this run; they do not grant redistribution rights or imply runtime success.",
        **provenance_core,
        "provenanceSha256": canonical_json_digest(provenance_core),
    }


def main() -> None:
    payload = build_provenance()
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Run provenance:", payload["provenanceSha256"])
    print("Commit:", payload["identity"].get("commitSha"))
    print("Run:", payload["identity"].get("runId"), "attempt", payload["identity"].get("runAttempt"))
    print("Manifests:", len(payload["manifests"]))
    print("Upstream artifacts:", len(payload["upstreamArtifacts"]))


if __name__ == "__main__":
    main()
