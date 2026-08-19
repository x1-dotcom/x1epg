#!/usr/bin/env python3
from __future__ import annotations

import gzip
import io
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_COMPRESSED = 50 * 1024 * 1024
MAX_UNCOMPRESSED = 250 * 1024 * 1024
UA = "X1-EPG/1.0 (+https://github.com/x1-dotcom/x1epg)"


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml,text/xml,application/gzip,*/*"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = resp.read(MAX_COMPRESSED + 1)
    if len(data) > MAX_COMPRESSED:
        raise RuntimeError("compressed source exceeds safety limit")
    return data


def decode_source(source_type: str, payload: bytes) -> bytes:
    if source_type == "xmltv-gzip":
        with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as fh:
            xml = fh.read(MAX_UNCOMPRESSED + 1)
        if len(xml) > MAX_UNCOMPRESSED:
            raise RuntimeError("uncompressed XML exceeds safety limit")
        return xml
    if len(payload) > MAX_UNCOMPRESSED:
        raise RuntimeError("XML exceeds safety limit")
    return payload


def validate_xmltv(xml_bytes: bytes) -> tuple[set[str], dict[str, int]]:
    channels: set[str] = set()
    programme_counts: dict[str, int] = {}
    try:
        for event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
            if elem.tag == "channel":
                cid = elem.attrib.get("id")
                if cid:
                    channels.add(cid)
            elif elem.tag == "programme":
                cid = elem.attrib.get("channel")
                if cid:
                    programme_counts[cid] = programme_counts.get(cid, 0) + 1
            elem.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid XMLTV: {exc}") from exc
    return channels, programme_counts


def main() -> None:
    reports = []
    failed = False

    for manifest_path in sorted((ROOT / "sources").glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        mappings = {row["sourceChannelId"]: row["canonicalId"] for row in manifest.get("channels", [])}

        for source in manifest.get("sources", []):
            if not source.get("ingestEnabled"):
                continue
            row = {
                "manifest": str(manifest_path.relative_to(ROOT)),
                "country": manifest.get("country"),
                "sourceId": source.get("sourceId"),
                "url": source.get("url"),
                "publishAllowed": source.get("publishAllowed", False),
                "rightsStatus": source.get("rightsStatus"),
            }
            try:
                compressed = fetch_bytes(source["url"])
                xml = decode_source(source["type"], compressed)
                source_channels, programme_counts = validate_xmltv(xml)

                mapped_present = sorted(cid for cid in mappings if cid in source_channels)
                mapped_missing = sorted(cid for cid in mappings if cid not in source_channels)
                programmes = sum(programme_counts.get(cid, 0) for cid in mapped_present)

                row.update({
                    "status": "OK" if not mapped_missing else "PARTIAL",
                    "compressedBytes": len(compressed),
                    "xmlBytes": len(xml),
                    "sourceChannelCount": len(source_channels),
                    "mappedExpected": len(mappings),
                    "mappedPresent": len(mapped_present),
                    "mappedMissing": mapped_missing,
                    "mappedProgrammeCount": programmes,
                    "publicationDecision": "ALLOWED" if source.get("publishAllowed") else "BLOCKED_RIGHTS_UNVERIFIED",
                })
                if mapped_missing:
                    failed = True
            except Exception as exc:
                failed = True
                row.update({"status": "FAILED", "error": str(exc), "publicationDecision": "BLOCKED"})
            reports.append(row)

    output = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "INGEST_VALIDATE_ONLY",
        "policy": "X1 never republishes an upstream EPG unless publishAllowed=true and rightsStatus=verified-redistributable.",
        "sources": reports,
    }
    out = ROOT / "data" / "sync-report.json"
    out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for row in reports:
        print(f"{row['sourceId']}: {row['status']} present={row.get('mappedPresent', 0)}/{row.get('mappedExpected', 0)} programmes={row.get('mappedProgrammeCount', 0)} publish={row['publicationDecision']}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
