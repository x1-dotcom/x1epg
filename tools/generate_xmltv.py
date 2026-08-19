#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from sync_epg import decode_source, fetch_bytes

ROOT = Path(__file__).resolve().parents[1]
MERGE_REPORT = ROOT / "data" / "merge-report.json"
DIST = ROOT / "dist"
GEN_REPORT = ROOT / "data" / "generation-report.json"


def fail(message: str, code: int = 1) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(code)


def title_key(programme: ET.Element) -> str:
    title = programme.find("title")
    return "" if title is None or title.text is None else " ".join(title.text.split()).casefold()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate canonical X1 XMLTV only from redistribution-approved sources.")
    parser.add_argument("--check-rights", action="store_true", help="Only report whether public generation is currently permitted.")
    parser.add_argument("--output", default="dist/x1-epg.xml", help="Repository-relative XMLTV output path.")
    args = parser.parse_args()

    if not MERGE_REPORT.exists():
        fail("data/merge-report.json is missing; run tools/plan_merge.py first")
    merge = json.loads(MERGE_REPORT.read_text(encoding="utf-8"))

    if args.check_rights:
        allowed = bool(merge.get("publicGenerationAllowed"))
        print(f"X1 EPG public generation allowed: {allowed}")
        print(f"Unavailable channels: {merge.get('unavailableCount', 0)}")
        print(f"Rights-blocked selected channels: {merge.get('selectedRightsBlockedCount', 0)}")
        return

    if not merge.get("publicGenerationAllowed"):
        fail("public XMLTV generation blocked: one or more selected sources lack verified redistribution rights or channels are unavailable", 2)

    manifest_channels: dict[str, dict] = {}
    source_defs: dict[str, dict] = {}
    for path in sorted((ROOT / "sources").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for source in manifest.get("sources", []):
            source_defs[source["sourceId"]] = source
        for channel in manifest.get("channels", []):
            manifest_channels[channel["canonicalId"]] = channel

    selected: dict[str, tuple[str, str]] = {}
    for row in merge.get("channels", []):
        chosen = row.get("selected")
        if row.get("status") != "AVAILABLE" or not chosen:
            fail(f"cannot generate: {row.get('canonicalId')} is unavailable")
        selected[row["canonicalId"]] = (chosen["sourceId"], chosen["channelId"])

    by_source: dict[str, dict[str, str]] = {}
    for canonical_id, (source_id, source_channel_id) in selected.items():
        by_source.setdefault(source_id, {})[source_channel_id] = canonical_id

    programmes: list[ET.Element] = []
    seen: set[tuple[str, str, str, str]] = set()
    source_programme_counts: dict[str, int] = {}

    for source_id, mapping in sorted(by_source.items()):
        source = source_defs.get(source_id)
        if source is None:
            fail(f"selected source missing from manifests: {source_id}")
        if not source.get("publishAllowed") or source.get("rightsStatus") != "verified-redistributable":
            fail(f"source lost redistribution approval after planning: {source_id}")

        payload = fetch_bytes(source["url"])
        xml_bytes = decode_source(source["type"], payload)
        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            fail(f"{source_id}: invalid XMLTV during generation: {exc}")

        kept = 0
        for programme in root.findall("programme"):
            source_channel_id = programme.attrib.get("channel")
            canonical_id = mapping.get(source_channel_id or "")
            if canonical_id is None:
                continue
            clone = ET.fromstring(ET.tostring(programme, encoding="utf-8"))
            clone.attrib["channel"] = canonical_id
            key = (
                canonical_id,
                clone.attrib.get("start", ""),
                clone.attrib.get("stop", ""),
                title_key(clone),
            )
            if key in seen:
                continue
            seen.add(key)
            programmes.append(clone)
            kept += 1
        source_programme_counts[source_id] = kept

    tv = ET.Element("tv", {"generator-info-name": "X1 EPG", "generator-info-url": "https://github.com/x1-dotcom/x1epg"})
    for canonical_id in sorted(selected):
        metadata = manifest_channels.get(canonical_id, {})
        channel = ET.SubElement(tv, "channel", {"id": canonical_id})
        display = ET.SubElement(channel, "display-name")
        display.text = metadata.get("name", canonical_id)

    programmes.sort(key=lambda p: (p.attrib.get("channel", ""), p.attrib.get("start", ""), p.attrib.get("stop", ""), title_key(p)))
    for programme in programmes:
        tv.append(programme)

    xml_body = ET.tostring(tv, encoding="utf-8", xml_declaration=True)
    output_path = ROOT / args.output
    try:
        output_path.relative_to(ROOT)
    except ValueError:
        fail("output must stay inside the repository")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(xml_body)
    gzip_path = output_path.with_suffix(output_path.suffix + ".gz")
    with gzip.open(gzip_path, "wb", compresslevel=9) as fh:
        fh.write(xml_body)

    report = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "GENERATED",
        "channelCount": len(selected),
        "programmeCount": len(programmes),
        "sources": source_programme_counts,
        "output": str(output_path.relative_to(ROOT)),
        "gzipOutput": str(gzip_path.relative_to(ROOT)),
        "sha256": hashlib.sha256(xml_body).hexdigest(),
        "rightsGate": "VERIFIED_REDISTRIBUTABLE_ONLY",
    }
    GEN_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Generated {report['output']}: channels={report['channelCount']} programmes={report['programmeCount']} sha256={report['sha256']}")


if __name__ == "__main__":
    main()
