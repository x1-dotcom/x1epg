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
    global_source_channel_pairs: set[tuple[str, str]] = set()

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
            if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
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
            if "priority" in source and (not isinstance(source["priority"], int) or source["priority"] < 1):
                fail(f"{path}: {sid}: priority must be a positive integer")

        for channel in payload["channels"]:
            cid = channel.get("canonicalId")
            if not isinstance(cid, str) or not ID_RE.fullmatch(cid):
                fail(f"{path}: invalid canonicalId {cid!r}")
            if cid in global_channel_ids:
                fail(f"duplicate canonicalId across source manifests: {cid}")
            global_channel_ids.add(cid)

            has_legacy = isinstance(channel.get("sourceChannelId"), str) and bool(channel.get("sourceChannelId", "").strip())
            mappings = channel.get("sourceMappings")
            has_mappings = mappings is not None
            if has_legacy == has_mappings:
                fail(f"{path}: {cid}: use exactly one of sourceChannelId or sourceMappings")

            if has_legacy:
                if len(local_source_ids) != 1:
                    fail(f"{path}: {cid}: sourceChannelId is only valid when the manifest has exactly one source")
                mappings = [{
                    "sourceId": next(iter(local_source_ids)),
                    "channelId": channel["sourceChannelId"],
                    "priority": 100,
                    "enabled": True,
                }]
            elif not isinstance(mappings, list) or not mappings:
                fail(f"{path}: {cid}: sourceMappings must be a non-empty array")

            priorities: set[int] = set()
            source_ids_for_channel: set[str] = set()
            for mapping in mappings:
                if set(mapping) != {"sourceId", "channelId", "priority", "enabled"}:
                    fail(f"{path}: {cid}: source mapping has invalid fields")
                sid = mapping["sourceId"]
                channel_id = mapping["channelId"]
                priority = mapping["priority"]
                if sid not in local_source_ids:
                    fail(f"{path}: {cid}: source mapping references unknown local source {sid}")
                if sid in source_ids_for_channel:
                    fail(f"{path}: {cid}: source {sid} mapped more than once")
                source_ids_for_channel.add(sid)
                if not isinstance(channel_id, str) or not channel_id.strip():
                    fail(f"{path}: {cid}: empty source channel id")
                if not isinstance(priority, int) or priority < 1:
                    fail(f"{path}: {cid}: mapping priority must be a positive integer")
                if priority in priorities:
                    fail(f"{path}: {cid}: duplicate mapping priority {priority}")
                priorities.add(priority)
                if not isinstance(mapping["enabled"], bool):
                    fail(f"{path}: {cid}: mapping enabled must be boolean")
                pair = (sid, channel_id)
                if pair in global_source_channel_pairs:
                    fail(f"source/channel pair reused by multiple canonical channels: {pair}")
                global_source_channel_pairs.add(pair)

        print(f"{path.relative_to(ROOT)}: sources={len(payload['sources'])} channels={len(payload['channels'])} OK")


if __name__ == "__main__":
    main()
