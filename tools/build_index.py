#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "index.json"


def mappings_for(manifest: dict, channel: dict) -> list[dict]:
    if isinstance(channel.get("sourceMappings"), list):
        return [
            {
                "sourceId": m["sourceId"],
                "channelId": m["channelId"],
                "priority": m["priority"],
                "enabled": m["enabled"],
            }
            for m in channel["sourceMappings"]
        ]
    sources = manifest.get("sources", [])
    if len(sources) == 1 and channel.get("sourceChannelId"):
        return [{
            "sourceId": sources[0]["sourceId"],
            "channelId": channel["sourceChannelId"],
            "priority": 1,
            "enabled": True,
        }]
    raise RuntimeError(f"{channel.get('canonicalId')}: no unambiguous source mappings")


def main() -> None:
    channels: list[dict] = []
    seen: set[str] = set()
    for path in sorted((ROOT / "sources").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        country = manifest["country"]
        timezone_name = manifest["timezone"]
        languages = manifest["languages"]
        for ch in manifest.get("channels", []):
            cid = ch["canonicalId"]
            if cid in seen:
                raise RuntimeError(f"duplicate canonicalId across manifests: {cid}")
            seen.add(cid)
            channels.append({
                "canonicalId": cid,
                "name": ch["name"],
                "country": country,
                "timezone": timezone_name,
                "languages": languages,
                "aliases": ch.get("aliases", []),
                "piconId": ch.get("piconId"),
                "tvgIds": ch.get("tvgIds", []),
                "sources": mappings_for(manifest, ch),
                "status": "testing",
            })

    channels.sort(key=lambda c: (c["country"], c["canonicalId"]))
    OUT.write_text(json.dumps({
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "channels": channels,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Built X1 EPG index: {len(channels)} channels from sources/")


if __name__ == "__main__":
    main()
