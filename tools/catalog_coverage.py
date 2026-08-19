#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data" / "index.json"
OUT = ROOT / "data" / "catalog-coverage.json"


def main() -> None:
    payload = json.loads(INDEX.read_text(encoding="utf-8"))
    channels = payload.get("channels", [])

    countries: dict[str, dict] = {}
    for channel in channels:
        country = channel.get("country") or "UNKNOWN"
        row = countries.setdefault(country, {
            "channelCount": 0,
            "piconLinkedCount": 0,
            "piconMissingCount": 0,
            "testingCount": 0,
            "activeCount": 0,
            "sourceCounts": Counter(),
        })
        row["channelCount"] += 1
        if channel.get("piconId"):
            row["piconLinkedCount"] += 1
        else:
            row["piconMissingCount"] += 1
        status = channel.get("status")
        if status == "testing":
            row["testingCount"] += 1
        if status == "active":
            row["activeCount"] += 1
        for source in channel.get("sources", []):
            if source.get("enabled", True):
                row["sourceCounts"][source.get("sourceId", "UNKNOWN")] += 1

    normalized = {}
    for country, row in sorted(countries.items()):
        normalized[country] = {
            "channelCount": row["channelCount"],
            "piconLinkedCount": row["piconLinkedCount"],
            "piconMissingCount": row["piconMissingCount"],
            "piconCoveragePercent": round((row["piconLinkedCount"] / row["channelCount"] * 100), 2) if row["channelCount"] else 0,
            "testingCount": row["testingCount"],
            "activeCount": row["activeCount"],
            "sourceCounts": dict(sorted(row["sourceCounts"].items())),
        }

    result = {
        "schemaVersion": 1,
        "generatedAt": payload.get("generatedAt"),
        "totalChannels": len(channels),
        "countryCount": len(normalized),
        "countries": normalized,
        "policy": "Coverage counts describe the canonical X1 catalogue only. They do not imply runtime source health, redistribution rights or picon materialization.",
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Catalog coverage: {len(channels)} channels across {len(normalized)} countries")
    for country, row in normalized.items():
        print(f"{country}: {row['channelCount']} channels, {row['piconCoveragePercent']}% picon-linked")


if __name__ == "__main__":
    main()
