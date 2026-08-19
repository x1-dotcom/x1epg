#!/usr/bin/env python3
from __future__ import annotations

import gzip
import io
import json
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from tools.xmltv_time import parse_xmltv_time

ROOT = Path(__file__).resolve().parents[1]
MAX_COMPRESSED = 50 * 1024 * 1024
MAX_UNCOMPRESSED = 250 * 1024 * 1024
DEFAULT_FRESHNESS_HOURS = 48
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
    if source_type != "xmltv":
        raise RuntimeError(f"unsupported source type: {source_type}")
    if len(payload) > MAX_UNCOMPRESSED:
        raise RuntimeError("XML exceeds safety limit")
    return payload


def mappings_for_source(manifest: dict, source_id: str) -> dict[str, str]:
    result: dict[str, str] = {}
    sources = manifest.get("sources", [])
    for channel in manifest.get("channels", []):
        canonical_id = channel.get("canonicalId")
        mappings = channel.get("sourceMappings")
        if isinstance(mappings, list):
            for mapping in mappings:
                if mapping.get("sourceId") == source_id and mapping.get("enabled") is True:
                    source_channel_id = mapping.get("channelId")
                    if isinstance(source_channel_id, str) and source_channel_id.strip():
                        if source_channel_id in result:
                            raise RuntimeError(f"duplicate source channel mapping: {source_id}/{source_channel_id}")
                        result[source_channel_id] = canonical_id
            continue
        legacy = channel.get("sourceChannelId")
        if len(sources) == 1 and sources[0].get("sourceId") == source_id and isinstance(legacy, str) and legacy.strip():
            if legacy in result:
                raise RuntimeError(f"duplicate legacy source channel mapping: {source_id}/{legacy}")
            result[legacy] = canonical_id
    return result


def validate_xmltv(xml_bytes: bytes, mapped_ids: set[str]) -> tuple[set[str], dict[str, int], dict[str, datetime], int]:
    channels: set[str] = set()
    programme_counts: dict[str, int] = {}
    newest_by_channel: dict[str, datetime] = {}
    malformed_mapped_timestamps = 0
    try:
        for _, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("end",)):
            if elem.tag == "channel":
                cid = elem.attrib.get("id")
                if cid:
                    channels.add(cid)
            elif elem.tag == "programme":
                cid = elem.attrib.get("channel")
                if cid:
                    programme_counts[cid] = programme_counts.get(cid, 0) + 1
                if cid in mapped_ids:
                    raw = elem.attrib.get("stop") or elem.attrib.get("start")
                    try:
                        stamp = parse_xmltv_time(raw)
                    except (TypeError, ValueError):
                        malformed_mapped_timestamps += 1
                    else:
                        previous = newest_by_channel.get(cid)
                        if previous is None or stamp > previous:
                            newest_by_channel[cid] = stamp
            elem.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid XMLTV: {exc}") from exc
    return channels, programme_counts, newest_by_channel, malformed_mapped_timestamps


def main() -> None:
    reports = []
    failed = False
    now = datetime.now(timezone.utc)
    for manifest_path in sorted((ROOT / "sources").glob("*.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for source in manifest.get("sources", []):
            if not source.get("ingestEnabled"):
                continue
            source_id = source.get("sourceId")
            mappings = mappings_for_source(manifest, source_id)
            row = {"manifest": str(manifest_path.relative_to(ROOT)), "country": manifest.get("country"), "sourceId": source_id, "url": source.get("url"), "publishAllowed": source.get("publishAllowed", False), "rightsStatus": source.get("rightsStatus")}
            try:
                if not mappings:
                    raise RuntimeError("ingest-enabled source has zero enabled canonical mappings")
                compressed = fetch_bytes(source["url"])
                xml = decode_source(source["type"], compressed)
                source_channels, programme_counts, newest_by_channel, malformed = validate_xmltv(xml, set(mappings))
                mapped_present = sorted(cid for cid in mappings if cid in source_channels)
                mapped_missing = sorted(cid for cid in mappings if cid not in source_channels)
                mapped_without_programmes = sorted(cid for cid in mapped_present if programme_counts.get(cid, 0) == 0)
                programmes = sum(programme_counts.get(cid, 0) for cid in mapped_present)
                newest = max((newest_by_channel[cid] for cid in mapped_present if cid in newest_by_channel), default=None)
                age_hours = None if newest is None else round((now - newest).total_seconds() / 3600, 2)
                freshness_limit = int(source.get("maxProgrammeAgeHours", DEFAULT_FRESHNESS_HOURS))
                fresh = newest is not None and age_hours <= freshness_limit
                issues = []
                if mapped_missing:
                    issues.append("MAPPED_CHANNELS_MISSING")
                if mapped_without_programmes:
                    issues.append("MAPPED_CHANNELS_WITHOUT_PROGRAMMES")
                if malformed:
                    issues.append("MALFORMED_OR_NAIVE_XMLTV_TIMESTAMPS")
                if not fresh:
                    issues.append("STALE_OR_UNDATED_PROGRAMMES")
                row.update({"status": "OK" if not issues else "FAILED", "compressedBytes": len(compressed), "xmlBytes": len(xml), "sourceChannelCount": len(source_channels), "mappedExpected": len(mappings), "mappedPresent": len(mapped_present), "mappedMissing": mapped_missing, "mappedWithoutProgrammes": mapped_without_programmes, "mappedProgrammeCount": programmes, "malformedMappedTimestampCount": malformed, "newestMappedProgramme": newest.isoformat() if newest else None, "newestMappedProgrammeAgeHours": age_hours, "freshnessLimitHours": freshness_limit, "fresh": fresh, "issues": issues, "publicationDecision": "ALLOWED" if source.get("publishAllowed") and source.get("rightsStatus") == "verified-redistributable" else "BLOCKED_RIGHTS_UNVERIFIED"})
                if issues:
                    failed = True
            except Exception as exc:
                failed = True
                row.update({"status": "FAILED", "error": str(exc), "publicationDecision": "BLOCKED"})
            reports.append(row)
    output = {"schemaVersion": 2, "generatedAt": now.isoformat(), "mode": "INGEST_VALIDATE_ONLY", "policy": "X1 requires explicit source mappings, timezone-aware XMLTV timestamps, mapped programme presence and freshness. X1 never republishes an upstream EPG unless publishAllowed=true and rightsStatus=verified-redistributable.", "sources": reports}
    (ROOT / "data" / "sync-report.json").write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in reports:
        print(f"{row['sourceId']}: {row['status']} present={row.get('mappedPresent', 0)}/{row.get('mappedExpected', 0)} programmes={row.get('mappedProgrammeCount', 0)} fresh={row.get('fresh')} publish={row['publicationDecision']}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
