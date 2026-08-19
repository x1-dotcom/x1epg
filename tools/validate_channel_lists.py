#!/usr/bin/env python3
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "channel-list-validation.json"
UA = "X1-EPG/1.0 (+https://github.com/x1-dotcom/x1epg)"
MAX_LIST_BYTES = 4 * 1024 * 1024


def fetch_text(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("channel list URL must be HTTPS")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/plain,*/*"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(MAX_LIST_BYTES + 1)
    if len(data) > MAX_LIST_BYTES:
        raise RuntimeError("channel list exceeds safety limit")
    return data.decode("utf-8-sig", errors="strict")


def parse_channel_ids(text: str) -> set[str]:
    ids: set[str] = set()
    for raw in text.splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        ids.add(value)
    return ids


def mappings_for_source(manifest: dict, source_id: str) -> dict[str, str]:
    result: dict[str, str] = {}
    sources = manifest.get("sources", [])
    for channel in manifest.get("channels", []):
        canonical = channel.get("canonicalId")
        mappings = channel.get("sourceMappings")
        if isinstance(mappings, list):
            for mapping in mappings:
                if mapping.get("sourceId") == source_id and mapping.get("enabled") is True:
                    cid = mapping.get("channelId")
                    if isinstance(cid, str) and cid.strip():
                        result[cid] = canonical
            continue
        legacy = channel.get("sourceChannelId")
        if len(sources) == 1 and sources[0].get("sourceId") == source_id and isinstance(legacy, str) and legacy.strip():
            result[legacy] = canonical
    return result


def validate_manifest_source(manifest: dict, source: dict, available: set[str]) -> dict:
    source_id = source["sourceId"]
    expected = mappings_for_source(manifest, source_id)
    missing = sorted(cid for cid in expected if cid not in available)
    return {
        "country": manifest["country"],
        "sourceId": source_id,
        "channelListUrl": source.get("channelListUrl"),
        "sourceListCount": len(available),
        "mappedExpected": len(expected),
        "mappedPresent": len(expected) - len(missing),
        "mappedMissing": missing,
        "missingCanonicalIds": [expected[cid] for cid in missing],
        "status": "OK" if expected and not missing else "FAILED",
    }


def main() -> None:
    rows: list[dict] = []
    failed = False
    for manifest_path in sorted((ROOT / "sources").glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for source in manifest.get("sources", []):
            if not source.get("ingestEnabled"):
                continue
            list_url = source.get("channelListUrl")
            if not isinstance(list_url, str) or not list_url.strip():
                rows.append({
                    "country": manifest.get("country"),
                    "sourceId": source.get("sourceId"),
                    "status": "FAILED",
                    "error": "ingest-enabled source has no channelListUrl",
                })
                failed = True
                continue
            try:
                available = parse_channel_ids(fetch_text(list_url))
                row = validate_manifest_source(manifest, source, available)
                if row["status"] != "OK":
                    failed = True
            except Exception as exc:
                row = {
                    "country": manifest.get("country"),
                    "sourceId": source.get("sourceId"),
                    "channelListUrl": list_url,
                    "status": "FAILED",
                    "error": str(exc),
                }
                failed = True
            rows.append(row)

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "policy": "Exact upstream channel-list membership preflight. No fuzzy matching and no automatic mapping mutation.",
        "sources": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in rows:
        print(
            f"{row['sourceId']}: {row['status']} "
            f"present={row.get('mappedPresent', 0)}/{row.get('mappedExpected', 0)} "
            f"missing={len(row.get('mappedMissing', []))}"
        )
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
