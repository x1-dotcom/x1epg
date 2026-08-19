#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IN = ROOT / "data" / "source-comparison-report.json"
OUT = ROOT / "data" / "quality-recommendations.json"

MIN_FUTURE_PROGRAMMES = 8
MIN_HOURS_AHEAD = 24.0
SWITCH_MARGIN_HOURS = 12.0


def health(row: dict) -> dict:
    future = int(row.get("futureProgrammeCount") or 0)
    hours = row.get("hoursAhead")
    hours = float(hours) if hours is not None else -1e9
    usable = future >= MIN_FUTURE_PROGRAMMES and hours >= MIN_HOURS_AHEAD
    return {
        "usable": usable,
        "futureProgrammeCount": future,
        "hoursAhead": None if hours <= -1e8 else hours,
        "programmeCount": int(row.get("programmeCount") or 0),
    }


def choose(rows: list[dict]) -> tuple[str | None, str]:
    ranked = []
    for row in rows:
        h = health(row)
        if not h["usable"]:
            continue
        ranked.append((h["hoursAhead"], h["futureProgrammeCount"], h["programmeCount"], row["sourceId"]))
    if not ranked:
        return None, "NO_SOURCE_MEETS_MINIMUM_QUALITY"
    ranked.sort(reverse=True)
    winner = ranked[0]
    if len(ranked) == 1:
        return winner[3], "ONLY_SOURCE_MEETS_MINIMUM_QUALITY"
    runner = ranked[1]
    if winner[0] - runner[0] < SWITCH_MARGIN_HOURS:
        return None, "HOLD_NO_CLEAR_MARGIN"
    return winner[3], "CLEAR_TECHNICAL_MARGIN"


def main() -> None:
    if not IN.exists():
        raise SystemExit("source comparison report missing")

    report = json.loads(IN.read_text(encoding="utf-8"))
    recs = []
    counts: dict[str, int] = {}

    for item in report.get("comparisons", []):
        recommended, reason = choose(item.get("sources", []))
        if recommended:
            counts[recommended] = counts.get(recommended, 0) + 1
        recs.append({
            "canonicalId": item["canonicalId"],
            "name": item["name"],
            "recommendedTechnicalSource": recommended,
            "reason": reason,
            "sourceHealth": {
                row["sourceId"]: health(row)
                for row in item.get("sources", [])
            },
            "enforcement": "ADVISORY_ONLY_NO_MAPPING_MUTATION",
        })

    payload = {
        "schemaVersion": 1,
        "generatedAt": report.get("generatedAt"),
        "country": report.get("country"),
        "policy": {
            "minimumFutureProgrammes": MIN_FUTURE_PROGRAMMES,
            "minimumHoursAhead": MIN_HOURS_AHEAD,
            "switchMarginHours": SWITCH_MARGIN_HOURS,
            "mode": "advisory-only",
            "rightsGate": "A technical recommendation never grants ingestion, commercial-use or redistribution rights.",
            "antiFlap": "Do not recommend a switch unless the leading source has at least 12 more hours of future coverage than the runner-up."
        },
        "recommendationCounts": counts,
        "channels": recs,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Quality recommendations generated for {len(recs)} channels")
    print("Recommended source counts:", counts)


if __name__ == "__main__":
    main()
