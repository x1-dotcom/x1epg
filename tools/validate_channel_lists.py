#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tools.safe_http import fetch_bounded_https

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "channel-list-validation.json"
MAX_LIST_BYTES = 4 * 1024 * 1024
TEXT_CONTENT_TYPES = ("text/plain", "application/octet-stream")


def fetch_text(url: str) -> str:
    result = fetch_bounded_https(
        url,
        max_bytes=MAX_LIST_BYTES,
        timeout=30,
        accept="text/plain,application/octet-stream,*/*",
        allowed_content_types=TEXT_CONTENT_TYPES,
        retries=1,
        max_redirects=3,
    )
    return result.data.decode("utf-8-sig", errors="strict")


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
                        if cid in result:
                            raise RuntimeError(f"duplicate source channel mapping: {source_id}/{cid}")
                        result[cid] = canonical
            continue
        legacy = channel.get("sourceChannelId")
        if len(sources) == 1 and sources[0].get("sourceId") == source_id and isinstance(legacy, str) and legacy.strip():
            if legacy in result:
                raise RuntimeError(f"duplicate legacy source channel mapping: {source_id}/{legacy}")
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
                rows.append({"country": manifest.get("country"), "sourceId": source.get("sourceId"), "status": "FAILED", "error": "ingest-enabled source has no channelListUrl"})
                failed = True
                continue
            try:
                available = parse_channel_ids(fetch_text(list_url))
                row = validate_manifest_source(manifest, source, available)
                if row["status"] != "OK":
                    failed = True
            except Exception as exc:
                row = {"country": manifest.get("country"), "sourceId": source.get("sourceId"), "channelListUrl": list_url, "status": "FAILED", "error": str(exc)}
                failed = True
            rows.append(row)

    payload = {
        "schemaVersion": 2,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "networkPolicy": "HTTPS only; port 443 only; same-host HTTPS redirects only; bounded 4 MiB lists; content-type gate; transient retry only.",
        "policy": "Exact upstream channel-list membership preflight. No fuzzy matching and no automatic mapping mutation.",
        "sources": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in rows:
        print(f"{row['sourceId']}: {row['status']} present={row.get('mappedPresent', 0)}/{row.get('mappedExpected', 0)} missing={len(row.get('mappedMissing', []))}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
