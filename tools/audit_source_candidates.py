#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "source-candidates.json"
OUT = ROOT / "data" / "source-candidate-report.json"
MAX_BYTES = 50 * 1024 * 1024
UA = "X1-EPG/1.0 (+https://github.com/x1-dotcom/x1epg)"
DATE_RE = re.compile(r"^(\d{14})")


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml,text/xml,*/*"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise RuntimeError("candidate exceeds safety limit")
    return data


def parse_xmltv(data: bytes) -> tuple[int, int, datetime | None]:
    root = ET.fromstring(data)
    if root.tag != "tv":
        raise RuntimeError("root element is not <tv>")
    channels = root.findall("channel")
    programmes = root.findall("programme")
    newest: datetime | None = None
    for p in programmes:
        raw = p.attrib.get("stop") or p.attrib.get("start") or ""
        m = DATE_RE.match(raw)
        if not m:
            continue
        dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        if newest is None or dt > newest:
            newest = dt
    return len(channels), len(programmes), newest


def main() -> None:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc)
    rows = []
    for c in registry.get("candidates", []):
        row = {
            "candidateId": c["candidateId"],
            "country": c["country"],
            "url": c["url"],
            "rightsStatus": c["rightsStatus"],
            "publishAllowed": c["publishAllowed"],
        }
        try:
            data = fetch(c["url"])
            channel_count, programme_count, newest = parse_xmltv(data)
            age_hours = None if newest is None else round((now - newest).total_seconds() / 3600, 2)
            fresh = newest is not None and age_hours <= c.get("maxProgrammeAgeHours", 48)
            rights_ok = c.get("publishAllowed") is True and c.get("rightsStatus") == "verified-redistributable"
            if not fresh:
                decision = "REJECT_STALE"
            elif not rights_ok:
                decision = "QUALIFIED_INGEST_ONLY_RIGHTS_BLOCKED"
            else:
                decision = "QUALIFIED_FOR_PROMOTION"
            row.update({
                "status": "OK",
                "bytes": len(data),
                "channelCount": channel_count,
                "programmeCount": programme_count,
                "newestProgramme": newest.isoformat() if newest else None,
                "newestProgrammeAgeHours": age_hours,
                "freshnessLimitHours": c.get("maxProgrammeAgeHours", 48),
                "fresh": fresh,
                "rightsVerifiedForPublication": rights_ok,
                "decision": decision,
            })
        except Exception as exc:
            row.update({"status": "FAILED", "decision": "REJECT_FETCH_OR_PARSE", "error": str(exc)})
        rows.append(row)

    OUT.write_text(json.dumps({
        "schemaVersion": 1,
        "generatedAt": now.isoformat(),
        "policy": "Candidates never become fallback sources automatically. Promotion requires freshness, coverage, stability and explicit rights review.",
        "candidates": rows,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for row in rows:
        print(f"{row['candidateId']}: {row['decision']} channels={row.get('channelCount', 0)} programmes={row.get('programmeCount', 0)} newest={row.get('newestProgramme')}")


if __name__ == "__main__":
    main()
