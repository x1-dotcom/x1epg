#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data" / "index.json"
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
ALLOWED_STATUS = {"active", "testing", "disabled", "deprecated"}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != 1:
        fail("schemaVersion must be 1")
    if not isinstance(payload.get("generatedAt"), str):
        fail("generatedAt must be a string")
    channels = payload.get("channels")
    if not isinstance(channels, list):
        fail("channels must be an array")

    ids: set[str] = set()
    aliases: dict[str, str] = {}
    source_pairs: set[tuple[str, str]] = set()

    for pos, ch in enumerate(channels):
        if not isinstance(ch, dict):
            fail(f"channels[{pos}] must be an object")
        required = {"canonicalId", "name", "country", "timezone", "languages", "aliases", "sources", "status"}
        missing = required - ch.keys()
        if missing:
            fail(f"{ch.get('canonicalId', pos)} missing fields: {sorted(missing)}")

        cid = ch["canonicalId"]
        if not isinstance(cid, str) or not ID_RE.fullmatch(cid):
            fail(f"invalid canonicalId: {cid!r}")
        if cid in ids:
            fail(f"duplicate canonicalId: {cid}")
        ids.add(cid)

        if not COUNTRY_RE.fullmatch(ch["country"]):
            fail(f"{cid}: invalid country")
        if not isinstance(ch["timezone"], str) or "/" not in ch["timezone"]:
            fail(f"{cid}: invalid timezone")
        if ch["status"] not in ALLOWED_STATUS:
            fail(f"{cid}: invalid status")
        if not isinstance(ch["languages"], list) or not ch["languages"]:
            fail(f"{cid}: languages must be non-empty")
        if not isinstance(ch["aliases"], list):
            fail(f"{cid}: aliases must be an array")
        if not isinstance(ch["sources"], list) or not ch["sources"]:
            fail(f"{cid}: sources must be non-empty")

        seen_priorities: set[int] = set()
        for src in ch["sources"]:
            if not isinstance(src, dict):
                fail(f"{cid}: source entry must be an object")
            if set(src) != {"sourceId", "channelId", "priority", "enabled"}:
                fail(f"{cid}: source entry has invalid fields")
            if not ID_RE.fullmatch(src["sourceId"]):
                fail(f"{cid}: invalid sourceId {src['sourceId']!r}")
            if not isinstance(src["priority"], int) or src["priority"] < 1:
                fail(f"{cid}: invalid source priority")
            if src["priority"] in seen_priorities:
                fail(f"{cid}: duplicate source priority {src['priority']}")
            seen_priorities.add(src["priority"])
            pair = (src["sourceId"], src["channelId"])
            if pair in source_pairs:
                fail(f"source/channel pair reused by multiple canonical channels: {pair}")
            source_pairs.add(pair)

        for alias in [cid, ch["name"], *ch["aliases"], *ch.get("tvgIds", [])]:
            key = str(alias).strip().casefold()
            if not key:
                fail(f"{cid}: empty alias")
            owner = aliases.get(key)
            if owner and owner != cid:
                fail(f"alias collision: {alias!r} -> {owner} and {cid}")
            aliases[key] = cid

    print(f"X1 EPG catalog valid: {len(channels)} channels")


if __name__ == "__main__":
    main()
