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
REGISTRY = ROOT / "data" / "source-candidates.json"
OUT = ROOT / "data" / "source-candidate-report.json"
MAX_COMPRESSED_BYTES = 50 * 1024 * 1024
MAX_XML_BYTES = 250 * 1024 * 1024
UA = "X1-EPG/1.0 (+https://github.com/x1-dotcom/x1epg)"


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml,text/xml,application/gzip,*/*"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = resp.read(MAX_COMPRESSED_BYTES + 1)
    if len(data) > MAX_COMPRESSED_BYTES:
        raise RuntimeError("candidate exceeds compressed safety limit")
    return data


def decode(candidate_type: str, data: bytes) -> bytes:
    if candidate_type == "xmltv-gzip":
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as fh:
            xml = fh.read(MAX_XML_BYTES + 1)
        if len(xml) > MAX_XML_BYTES:
            raise RuntimeError("candidate exceeds uncompressed XML safety limit")
        return xml
    if candidate_type != "xmltv":
        raise RuntimeError(f"unsupported candidate type: {candidate_type}")
    if len(data) > MAX_XML_BYTES:
        raise RuntimeError("candidate XML exceeds safety limit")
    return data


def parse_xmltv(data: bytes) -> tuple[int, int, datetime | None, int]:
    channels = 0
    programmes = 0
    newest: datetime | None = None
    invalid_timestamps = 0
    try:
        for _, elem in ET.iterparse(io.BytesIO(data), events=("end",)):
            if elem.tag == "channel":
                channels += 1
            elif elem.tag == "programme":
                programmes += 1
                raw = elem.attrib.get("stop") or elem.attrib.get("start")
                try:
                    dt = parse_xmltv_time(raw)
                except (TypeError, ValueError):
                    invalid_timestamps += 1
                else:
                    if newest is None or dt > newest:
                        newest = dt
            elem.clear()
    except ET.ParseError as exc:
        raise RuntimeError(f"invalid XMLTV: {exc}") from exc
    return channels, programmes, newest, invalid_timestamps


def main() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    rows = []
    for c in registry.get("candidates", []):
        row = {"candidateId": c["candidateId"], "country": c["country"], "url": c["url"], "type": c.get("type"), "rightsStatus": c["rightsStatus"], "publishAllowed": c["publishAllowed"], "auditEnabled": c.get("auditEnabled", True)}
        if not c.get("auditEnabled", True):
            row.update({"status": "SKIPPED", "decision": "REJECT_TERMS_OR_PERMISSION_REQUIRED", "reason": c.get("notes", "candidate audit disabled by policy")})
            rows.append(row)
            continue
        try:
            raw = fetch(c["url"])
            xml = decode(c.get("type", "xmltv"), raw)
            channel_count, programme_count, newest, invalid_timestamps = parse_xmltv(xml)
            age_hours = None if newest is None else round((now - newest).total_seconds() / 3600, 2)
            fresh = newest is not None and age_hours <= c.get("maxProgrammeAgeHours", 48)
            rights_ok = c.get("publishAllowed") is True and c.get("rightsStatus") == "verified-redistributable"
            if programme_count == 0:
                decision = "REJECT_NO_PROGRAMMES"
            elif invalid_timestamps:
                decision = "REJECT_MALFORMED_OR_NAIVE_TIMESTAMPS"
            elif not fresh:
                decision = "REJECT_STALE"
            elif not rights_ok:
                decision = "QUALIFIED_INGEST_ONLY_RIGHTS_BLOCKED"
            else:
                decision = "QUALIFIED_FOR_PROMOTION"
            row.update({"status": "OK" if invalid_timestamps == 0 else "FAILED", "compressedBytes": len(raw), "xmlBytes": len(xml), "channelCount": channel_count, "programmeCount": programme_count, "invalidTimestampCount": invalid_timestamps, "newestProgramme": newest.isoformat() if newest else None, "newestProgrammeAgeHours": age_hours, "freshnessLimitHours": c.get("maxProgrammeAgeHours", 48), "fresh": fresh, "rightsVerifiedForPublication": rights_ok, "decision": decision})
        except Exception as exc:
            row.update({"status": "FAILED", "decision": "REJECT_FETCH_OR_PARSE", "error": str(exc)})
        rows.append(row)
    OUT.write_text(json.dumps({"schemaVersion": 2, "generatedAt": now.isoformat(), "policy": "Candidates never become fallback sources automatically. Promotion requires strict timezone-aware XMLTV timestamps, freshness, programme presence, coverage, stability and explicit rights review. Candidates blocked by terms or permission requirements are not fetched by the automated auditor.", "candidates": rows}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in rows:
        print(f"{row['candidateId']}: {row['decision']} channels={row.get('channelCount', 0)} programmes={row.get('programmeCount', 0)} invalidTimes={row.get('invalidTimestampCount', 0)} newest={row.get('newestProgramme')}")


if __name__ == "__main__":
    main()
