#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECOMMENDATIONS = ROOT / "data" / "quality-recommendations.json"
STATE = ROOT / "data" / "quality-state.json"
OUT = ROOT / "data" / "quality-decision-report.json"

REQUIRED_CONSECUTIVE_WINS = 3
MIN_SWITCH_INTERVAL_HOURS = 24.0


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def main() -> None:
    if not RECOMMENDATIONS.exists():
        raise SystemExit("quality recommendations missing")

    now = datetime.now(timezone.utc)
    rec = load_json(RECOMMENDATIONS, {})
    state = load_json(STATE, {"schemaVersion": 1, "channels": {}})
    channels_state = state.setdefault("channels", {})
    decisions = []

    for row in rec.get("channels", []):
        cid = row["canonicalId"]
        suggested = row.get("recommendedTechnicalSource")
        reason = row.get("reason")
        s = channels_state.setdefault(cid, {
            "currentTechnicalSource": None,
            "candidateTechnicalSource": None,
            "candidateWinStreak": 0,
            "lastSwitchAt": None,
            "lastObservedAt": None,
        })

        previous_candidate = s.get("candidateTechnicalSource")
        if suggested is None:
            s["candidateTechnicalSource"] = None
            s["candidateWinStreak"] = 0
            action = "HOLD_NO_TECHNICAL_WINNER"
        elif suggested == s.get("currentTechnicalSource"):
            s["candidateTechnicalSource"] = None
            s["candidateWinStreak"] = 0
            action = "HOLD_CURRENT_SOURCE"
        else:
            if suggested == previous_candidate:
                s["candidateWinStreak"] = int(s.get("candidateWinStreak") or 0) + 1
            else:
                s["candidateTechnicalSource"] = suggested
                s["candidateWinStreak"] = 1

            last_switch = parse_iso(s.get("lastSwitchAt"))
            cooldown_ok = last_switch is None or (now - last_switch).total_seconds() >= MIN_SWITCH_INTERVAL_HOURS * 3600
            streak_ok = s["candidateWinStreak"] >= REQUIRED_CONSECUTIVE_WINS

            if streak_ok and cooldown_ok:
                action = "SWITCH_ELIGIBLE_AFTER_GUARDS"
            elif not streak_ok:
                action = "HOLD_WAIT_CONSECUTIVE_WINS"
            else:
                action = "HOLD_SWITCH_COOLDOWN"

        s["lastObservedAt"] = now.isoformat()
        decisions.append({
            "canonicalId": cid,
            "name": row.get("name"),
            "currentTechnicalSource": s.get("currentTechnicalSource"),
            "recommendedTechnicalSource": suggested,
            "candidateTechnicalSource": s.get("candidateTechnicalSource"),
            "candidateWinStreak": s.get("candidateWinStreak", 0),
            "requiredConsecutiveWins": REQUIRED_CONSECUTIVE_WINS,
            "minimumSwitchIntervalHours": MIN_SWITCH_INTERVAL_HOURS,
            "action": action,
            "qualityReason": reason,
            "enforcement": "ADVISORY_ONLY_NO_MAPPING_MUTATION_NO_RIGHTS_CHANGE",
        })

    state["updatedAt"] = now.isoformat()
    state["policy"] = {
        "requiredConsecutiveWins": REQUIRED_CONSECUTIVE_WINS,
        "minimumSwitchIntervalHours": MIN_SWITCH_INTERVAL_HOURS,
        "mode": "advisory-only",
    }
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    OUT.write_text(json.dumps({
        "schemaVersion": 1,
        "generatedAt": now.isoformat(),
        "policy": {
            "requiredConsecutiveWins": REQUIRED_CONSECUTIVE_WINS,
            "minimumSwitchIntervalHours": MIN_SWITCH_INTERVAL_HOURS,
            "rightsGate": "Technical eligibility never changes ingestion, commercial-use or redistribution rights.",
            "mutationGate": "This report never changes source mappings automatically."
        },
        "channels": decisions,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    for d in decisions:
        counts[d["action"]] = counts.get(d["action"], 0) + 1
    print("Decision guard:", counts)


if __name__ == "__main__":
    main()
