#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sync_epg import decode_source, fetch_bytes, validate_xmltv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "merge-report.json"


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def channel_mappings(manifest: dict, channel: dict) -> list[dict]:
    explicit = channel.get("sourceMappings")
    if explicit is not None:
        if not isinstance(explicit, list) or not explicit:
            fail(f"{channel.get('canonicalId')}: sourceMappings must be a non-empty array")
        return explicit

    legacy = channel.get("sourceChannelId")
    sources = manifest.get("sources", [])
    if legacy and len(sources) == 1:
        source = sources[0]
        return [{
            "sourceId": source["sourceId"],
            "channelId": legacy,
            "priority": int(source.get("priority", 100)),
            "enabled": True,
        }]
    if legacy:
        fail(f"{channel.get('canonicalId')}: sourceChannelId is ambiguous with multiple sources; use sourceMappings")
    fail(f"{channel.get('canonicalId')}: no source mapping")


def main() -> None:
    manifests = []
    source_defs: dict[str, dict] = {}
    source_runtime: dict[str, dict] = {}

    for path in sorted((ROOT / "sources").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["_path"] = str(path.relative_to(ROOT))
        manifests.append(payload)
        for source in payload.get("sources", []):
            sid = source["sourceId"]
            if sid in source_defs:
                fail(f"duplicate sourceId: {sid}")
            source_defs[sid] = {**source, "manifest": payload["_path"], "country": payload.get("country")}

    for sid, source in source_defs.items():
        if not source.get("ingestEnabled"):
            source_runtime[sid] = {"status": "DISABLED", "channels": set(), "programmes": {}}
            continue
        try:
            payload = fetch_bytes(source["url"])
            xml = decode_source(source["type"], payload)
            channels, programmes = validate_xmltv(xml)
            source_runtime[sid] = {
                "status": "OK",
                "channels": channels,
                "programmes": programmes,
                "compressedBytes": len(payload),
                "xmlBytes": len(xml),
            }
        except Exception as exc:
            source_runtime[sid] = {"status": "FAILED", "error": str(exc), "channels": set(), "programmes": {}}

    channel_rows = []
    unavailable = 0
    fallback_count = 0
    selected_rights_blocked = 0

    for manifest in manifests:
        for channel in manifest.get("channels", []):
            cid = channel["canonicalId"]
            mappings = sorted(
                [m for m in channel_mappings(manifest, channel) if m.get("enabled", True)],
                key=lambda m: (int(m.get("priority", 100)), m["sourceId"]),
            )
            attempted = []
            selected = None

            for position, mapping in enumerate(mappings):
                sid = mapping["sourceId"]
                if sid not in source_defs:
                    fail(f"{cid}: unknown sourceId {sid}")
                runtime = source_runtime[sid]
                source_channel_id = mapping["channelId"]
                count = runtime.get("programmes", {}).get(source_channel_id, 0)
                present = source_channel_id in runtime.get("channels", set())
                attempt = {
                    "sourceId": sid,
                    "channelId": source_channel_id,
                    "priority": int(mapping.get("priority", 100)),
                    "sourceStatus": runtime["status"],
                    "channelPresent": present,
                    "programmeCount": count,
                }
                attempted.append(attempt)
                if runtime["status"] == "OK" and present and count > 0:
                    selected = {**attempt, "fallbackPosition": position}
                    break

            if selected is None:
                unavailable += 1
                channel_rows.append({
                    "canonicalId": cid,
                    "country": channel.get("country", manifest.get("country")),
                    "status": "UNAVAILABLE",
                    "selected": None,
                    "attempted": attempted,
                    "publicationDecision": "BLOCKED_NO_EPG",
                })
                continue

            sid = selected["sourceId"]
            source = source_defs[sid]
            fallback_used = selected["fallbackPosition"] > 0
            if fallback_used:
                fallback_count += 1
            publish_ok = bool(source.get("publishAllowed")) and source.get("rightsStatus") == "verified-redistributable"
            if not publish_ok:
                selected_rights_blocked += 1
            channel_rows.append({
                "canonicalId": cid,
                "country": channel.get("country", manifest.get("country")),
                "status": "AVAILABLE",
                "selected": selected,
                "fallbackUsed": fallback_used,
                "attempted": attempted,
                "rightsStatus": source.get("rightsStatus"),
                "publicationDecision": "ALLOWED" if publish_ok else "BLOCKED_RIGHTS_UNVERIFIED",
            })

    source_rows = []
    for sid, source in sorted(source_defs.items()):
        runtime = source_runtime[sid]
        source_rows.append({
            "sourceId": sid,
            "manifest": source["manifest"],
            "country": source.get("country"),
            "status": runtime["status"],
            "publishAllowed": bool(source.get("publishAllowed")),
            "rightsStatus": source.get("rightsStatus"),
            "sourceChannelCount": len(runtime.get("channels", set())),
            "programmeCount": sum(runtime.get("programmes", {}).values()),
            **({"error": runtime["error"]} if runtime.get("error") else {}),
        })

    output = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "mode": "FALLBACK_SELECTION_PLAN_ONLY",
        "policy": "Selection is priority-ordered and fail-closed. Public XMLTV generation is allowed only when every selected programme source has verified redistribution rights.",
        "channelCount": len(channel_rows),
        "availableCount": len(channel_rows) - unavailable,
        "unavailableCount": unavailable,
        "fallbackUsedCount": fallback_count,
        "selectedRightsBlockedCount": selected_rights_blocked,
        "publicGenerationAllowed": unavailable == 0 and selected_rights_blocked == 0,
        "sources": source_rows,
        "channels": channel_rows,
    }
    OUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"X1 EPG merge plan: available={output['availableCount']}/{output['channelCount']} fallback={fallback_count} rightsBlocked={selected_rights_blocked} publicGenerationAllowed={output['publicGenerationAllowed']}")
    if unavailable:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
