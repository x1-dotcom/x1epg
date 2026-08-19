#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data" / "index.json"
OUT = ROOT / "data" / "global-validation.json"


def main() -> None:
    manifest_counts: Counter[str] = Counter()
    manifest_total = 0
    manifest_ids: set[str] = set()
    errors: list[str] = []

    for path in sorted((ROOT / "sources").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        country = payload.get("country")
        for channel in payload.get("channels", []):
            cid = channel.get("canonicalId")
            manifest_total += 1
            manifest_counts[country] += 1
            if cid in manifest_ids:
                errors.append(f"duplicate canonicalId in manifests: {cid}")
            manifest_ids.add(cid)

    if not INDEX.exists():
        errors.append("data/index.json missing")
        index = {"channels": []}
    else:
        index = json.loads(INDEX.read_text(encoding="utf-8"))

    index_channels = index.get("channels", [])
    index_ids = {row.get("canonicalId") for row in index_channels}
    index_counts = Counter(row.get("country") for row in index_channels)

    missing_from_index = sorted(manifest_ids - index_ids)
    orphaned_in_index = sorted(index_ids - manifest_ids)
    if missing_from_index:
        errors.append(f"index missing {len(missing_from_index)} canonical channels")
    if orphaned_in_index:
        errors.append(f"index contains {len(orphaned_in_index)} orphaned canonical channels")
    if len(index_channels) != manifest_total:
        errors.append(f"index channel count {len(index_channels)} != manifest count {manifest_total}")

    countries = sorted(set(manifest_counts) | set(index_counts))
    country_rows = []
    for country in countries:
        m = manifest_counts[country]
        i = index_counts[country]
        if m != i:
            errors.append(f"{country}: index count {i} != manifest count {m}")
        country_rows.append({"country": country, "manifestChannels": m, "indexChannels": i, "match": m == i})

    with_picon = sum(1 for row in index_channels if row.get("piconId"))
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not errors else "FAIL",
        "manifestChannelCount": manifest_total,
        "indexChannelCount": len(index_channels),
        "countries": country_rows,
        "piconCoverage": {
            "withPicon": with_picon,
            "withoutPicon": len(index_channels) - with_picon,
            "percent": round((with_picon / len(index_channels) * 100), 2) if index_channels else 0.0,
        },
        "missingFromIndex": missing_from_index,
        "orphanedInIndex": orphaned_in_index,
        "errors": errors,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Global validation: {payload['status']} manifests={manifest_total} index={len(index_channels)}")
    for row in country_rows:
        print(f"{row['country']}: manifests={row['manifestChannels']} index={row['indexChannels']} match={row['match']}")
    print(f"Picon coverage: {payload['piconCoverage']['withPicon']}/{len(index_channels)} ({payload['piconCoverage']['percent']}%)")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
