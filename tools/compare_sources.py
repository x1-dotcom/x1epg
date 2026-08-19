#!/usr/bin/env python3
from __future__ import annotations

import gzip
import io
import json
import re
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "source-comparison-report.json"
UA = "X1-EPG/1.0 (+https://github.com/x1-dotcom/x1epg)"
MAX_BYTES = 300 * 1024 * 1024
DATE_RE = re.compile(r"^(\d{14})")

SOURCES = {
    "epgshare01-es1": {
        "url": "https://epgshare01.online/epgshare01/epg_ripper_ES1.xml.gz",
        "gzip": True,
    },
    "doblem-global": {
        "url": "https://raw.githubusercontent.com/davidmuma/EPG_dobleM/master/guiatv.xml",
        "gzip": False,
    },
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    value = re.sub(r"\b(?:uhd|fhd|hd|sd|1080p?|720p?|tv)\b", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def fetch(url: str, gz: bool) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml,text/xml,application/gzip,*/*"})
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise RuntimeError(f"source exceeds safety limit: {url}")
    if gz:
        data = gzip.decompress(data)
        if len(data) > MAX_BYTES:
            raise RuntimeError(f"decompressed source exceeds safety limit: {url}")
    return data


def parse(data: bytes) -> dict:
    channels: dict[str, set[str]] = {}
    programmes: dict[str, list[tuple[datetime | None, datetime | None]]] = defaultdict(list)
    latest: datetime | None = None
    earliest: datetime | None = None
    for _, elem in ET.iterparse(io.BytesIO(data), events=("end",)):
        if elem.tag == "channel":
            cid = elem.attrib.get("id", "").strip()
            names = {cid}
            for child in elem.findall("display-name"):
                if child.text and child.text.strip():
                    names.add(child.text.strip())
            if cid:
                channels[cid] = names
        elif elem.tag == "programme":
            cid = elem.attrib.get("channel", "").strip()
            start = parse_date(elem.attrib.get("start"))
            stop = parse_date(elem.attrib.get("stop"))
            programmes[cid].append((start, stop))
            for dt in (start, stop):
                if dt is None:
                    continue
                earliest = dt if earliest is None or dt < earliest else earliest
                latest = dt if latest is None or dt > latest else latest
        elem.clear()
    return {"channels": channels, "programmes": programmes, "earliest": earliest, "latest": latest}


def parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    m = DATE_RE.match(raw)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def candidate_names(channel: dict) -> set[str]:
    values = {channel["name"], channel["canonicalId"]}
    values.update(channel.get("aliases", []))
    values.update(channel.get("tvgIds", []))
    return {normalize(v) for v in values if isinstance(v, str) and v.strip()}


def resolve(channel: dict, parsed: dict, preferred_source: str) -> tuple[str | None, str]:
    if preferred_source == "epgshare01-es1":
        for mapping in channel.get("sources", []):
            if mapping.get("sourceId") == preferred_source and mapping.get("channelId") in parsed["channels"]:
                return mapping["channelId"], "EXACT_CANONICAL_MAPPING"
    wanted = candidate_names(channel)
    best: list[tuple[str, str]] = []
    for cid, names in parsed["channels"].items():
        normalized = {normalize(v) for v in names}
        common = wanted & normalized
        if common:
            best.append((cid, sorted(common, key=len, reverse=True)[0]))
    if not best:
        return None, "NO_MATCH"
    best.sort(key=lambda item: (-len(item[1]), item[0]))
    if len(best) > 1 and len(best[0][1]) == len(best[1][1]):
        return None, "AMBIGUOUS"
    return best[0][0], "NORMALIZED_NAME_MATCH"


def metrics(source_id: str, cid: str | None, parsed: dict, now: datetime) -> dict:
    if cid is None:
        return {"sourceId": source_id, "channelId": None, "programmeCount": 0, "futureProgrammeCount": 0, "latestProgramme": None, "hoursAhead": None}
    events = parsed["programmes"].get(cid, [])
    starts = [start for start, _ in events if start is not None]
    stops = [stop for _, stop in events if stop is not None]
    latest = max(stops or starts) if (stops or starts) else None
    future_count = sum(1 for start in starts if start >= now)
    hours_ahead = None if latest is None else round((latest - now).total_seconds() / 3600, 2)
    return {
        "sourceId": source_id,
        "channelId": cid,
        "programmeCount": len(events),
        "futureProgrammeCount": future_count,
        "latestProgramme": latest.isoformat() if latest else None,
        "hoursAhead": hours_ahead,
    }


def score(row: dict) -> tuple:
    return (
        1 if row["futureProgrammeCount"] > 0 else 0,
        row["hoursAhead"] if row["hoursAhead"] is not None else -10**9,
        row["futureProgrammeCount"],
        row["programmeCount"],
    )


def main() -> None:
    now = datetime.now(timezone.utc)
    index = json.loads((ROOT / "data" / "index.json").read_text(encoding="utf-8"))
    es_channels = [c for c in index.get("channels", []) if c.get("country") == "ES"]
    parsed_sources = {}
    source_health = {}
    for sid, cfg in SOURCES.items():
        raw = fetch(cfg["url"], cfg["gzip"])
        parsed = parse(raw)
        parsed_sources[sid] = parsed
        source_health[sid] = {
            "channelCount": len(parsed["channels"]),
            "programmeCount": sum(len(v) for v in parsed["programmes"].values()),
            "earliestProgramme": parsed["earliest"].isoformat() if parsed["earliest"] else None,
            "latestProgramme": parsed["latest"].isoformat() if parsed["latest"] else None,
            "hoursAhead": None if parsed["latest"] is None else round((parsed["latest"] - now).total_seconds() / 3600, 2),
        }

    comparisons = []
    winners = defaultdict(int)
    for channel in es_channels:
        source_rows = []
        match_info = {}
        for sid, parsed in parsed_sources.items():
            cid, match_type = resolve(channel, parsed, sid)
            row = metrics(sid, cid, parsed, now)
            row["matchType"] = match_type
            source_rows.append(row)
            match_info[sid] = match_type
        ranked = sorted(source_rows, key=score, reverse=True)
        winner = ranked[0]["sourceId"] if score(ranked[0]) > (0, -10**9, 0, 0) else None
        tie = len(ranked) > 1 and score(ranked[0]) == score(ranked[1])
        if tie:
            winner = None
        if winner:
            winners[winner] += 1
        comparisons.append({
            "canonicalId": channel["canonicalId"],
            "name": channel["name"],
            "winnerByTechnicalCoverage": winner,
            "tie": tie,
            "sources": source_rows,
            "rightsDecision": "TECHNICAL_ONLY_NO_AUTOMATIC_PROMOTION_OR_PUBLICATION",
        })

    payload = {
        "schemaVersion": 1,
        "generatedAt": now.isoformat(),
        "country": "ES",
        "policy": "Technical comparison only. Source selection here does not grant redistribution rights and does not mutate approved fallback mappings.",
        "sourceHealth": source_health,
        "winnerCounts": dict(winners),
        "channelsCompared": len(comparisons),
        "comparisons": comparisons,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Compared {len(comparisons)} Spanish canonical channels")
    for sid, count in sorted(winners.items()):
        print(f"{sid}: technical winner for {count} channels")


if __name__ == "__main__":
    main()
