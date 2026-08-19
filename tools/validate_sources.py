#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RIGHTS = {"verified-redistributable", "public-feed-no-license-found", "permission-required", "unknown"}
TYPES = {"xmltv", "xmltv-gzip"}


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> None:
    manifests = sorted((ROOT / "sources").glob("*.json"))
    if not manifests:
        fail("no source manifests found")

    global_source_ids: set[str] = set()
    global_channel_ids: set[str] = set()

    for path in manifests:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for field in ("schemaVersion", "sourceGroup", "country", "timezone", "languages", "sources", "channels"):
            if field not in payload:
                fail(f"{path}: missing {field}")
        if payload["schemaVersion"] != 1:
            fail(f"{path}: schemaVersion must be 1")
        if not ID_RE.fullmatch(payload["sourceGroup"]):
            fail(f"{path}: invalid sourceGroup")
        if not re.fullmatch(r"[A-Z]{2}", payload["country"]):
            fail(f"{path}: invalid country")
        if not isinstance(payload["languages"], list) or not payload["languages"]:
            fail(f"{path}: languages must be non-empty")

        local_source_ids: set[str] = set()
        for source in payload["sources"]:
            required = {"sourceId", "type", "url", "ingestEnabled", "publishAllowed", "rightsStatus"}
            missing = required - source.keys()
            if missing:
                fail(f"{path}: source missing {sorted(missing)}")
            sid = source["sourceId"]
            if not ID_RE.fullmatch(sid):
                fail(f"{path}: invalid sourceId {sid!r}")
            if sid in global_source_ids:
                fail(f"duplicate sourceId across manifests: {sid}")
            global_source_ids.add(sid)
            local_source_ids.add(sid)
            if source["type"] not in TYPES:
                fail(f"{path}: {sid}: invalid type")
            parsed = urlparse(source["url"])
            if parsed.scheme != "https" or not parsed.netloc:
                fail(f"{path}: {sid}: source URL must be HTTPS")
            if source["rightsStatus"] not in RIGHTS:
                fail(f"{path}: {sid}: invalid rightsStatus")
            if not isinstance(source["ingestEnabled"], bool) or not isinstance(source["publishAllowed"], bool):
                fail(f"{path}: {sid}: ingestEnabled/publishAllowed must be boolean")
            if source["publishAllowed"] and source["rightsStatus"] != "verified-redistributable":
                fail(f"{path}: {sid}: publishAllowed requires verified-redistributable rights")

        seen_source_channel: set[tuple[str, str]] = set()
        for channel in payload["channels"]:
            cid = channel.get("canonicalId")
            source_channel = channel.get("sourceChannelId")
            if not isinstance(cid, str) or not ID_RE.fullmatch(cid):
                fail(f"{path}: invalid canonicalId {cid!r}")
            if cid in global_channel_ids:
                fail(f"duplicate canonicalId across source manifests: {cid}")
            global_channel_ids.add(cid)
            if not isinstance(source_channel, str) or not source_channel.strip():
                fail(f"{path}: {cid}: sourceChannelId required")
            pair = (next(iter(local_source_ids)) if len(local_source_ids) == 1 else "", source_channel)
            if pair in seen_source_channel:
                fail(f"{path}: source channel reused: {source_channel}")
            seen_source_channel.add(pair)

        print(f"{path.relative_to(ROOT)}: sources={len(payload['sources'])} channels={len(payload['channels'])} OK")


if __name__ == "__main__":
    main()
