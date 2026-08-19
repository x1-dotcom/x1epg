#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECOMMENDATIONS = ROOT / "data" / "quality-recommendations.json"
STATE = ROOT / "data" / "quality-state.json"
OUT = ROOT / "data" / "quality-decision-report.json"
CANDIDATES = ROOT / "data" / "source-candidates.json"

REQUIRED_CONSECUTIVE_WINS = 3
MIN_SWITCH_INTERVAL_HOURS = 24.0
STATE_STALE_HOURS = 72.0


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def approved_sources() -> set[str]:
    result: set[str] = set()
    for path in sorted((ROOT / "sources").glob("*.json")):
        payload = load_json(path, {})
        for source in payload.get("sources", []):
            if source.get("ingestEnabled") is True and isinstance(source.get("sourceId"), str):
                result.add(source["sourceId"])
    return result


def source_policy() -> dict[str, dict]:
    policy: dict[str, dict] = {}
    approved = approved_sources()
    for sid in approved:
        policy[sid] = {
            "approvedForIngest": True,
            "rightsStatus": None,
            "publishAllowed": False,
            "candidateOnly": False,
        }

    for path in sorted((ROOT / "sources").glob("*.json")):
        payload = load_json(path, {})
        for source in payload.get("sources", []):
            sid = source.get("sourceId")
            if not isinstance(sid, str):
                continue
            policy[sid] = {
                "approvedForIngest": source.get("ingestEnabled") is True,
                "rightsStatus": source.get("rightsStatus"),
                "publishAllowed": source.get("publishAllowed") is True,
                "candidateOnly": False,
            }

    candidates = load_json(CANDIDATES, {})
    for candidate in candidates.get("candidates", []):
        sid = candidate.get("candidateId")
        if not isinstance(sid, str) or sid in policy:
            continue
        policy[sid] = {
            "approvedForIngest": False,
            "rightsStatus": candidate.get("rightsStatus"),
            "publishAllowed": candidate.get("publishAllowed") is True,
            "candidateOnly": True,
        }
    return policy


def normalize_state_entry(entry: dict, now: datetime) -> dict:
    last_observed = parse_iso(entry.get("lastObservedAt"))
    if last_observed is None or (now - last_observed).total_seconds() > STATE_STALE_HOURS * 3600:
        entry["candidateTechnicalSource"] = None
        entry["candidateWinStreak"] = 0
    last_switch = parse_iso(entry.get("lastSwitchAt"))
    if entry.get("lastSwitchAt") and last_switch is None:
        entry["lastSwitchAt"] = None
    return entry


def evaluate_action(
    *,
    suggested: str | None,
    state_entry: dict,
    source_meta: dict | None,
    now: datetime,
) -> tuple[str, bool, bool]:
    current = state_entry.get("currentTechnicalSource")
    previous_candidate = state_entry.get("candidateTechnicalSource")

    rights_blocked = bool(source_meta) and not (
        source_meta.get("rightsStatus") == "verified-redistributable"
        and source_meta.get("publishAllowed") is True
    )
    operational_eligible = bool(source_meta) and source_meta.get("approvedForIngest") is True

    if suggested is None:
        state_entry["candidateTechnicalSource"] = None
        state_entry["candidateWinStreak"] = 0
        return "HOLD_NO_TECHNICAL_WINNER", operational_eligible, rights_blocked

    if suggested == current:
        state_entry["candidateTechnicalSource"] = None
        state_entry["candidateWinStreak"] = 0
        return "HOLD_CURRENT_SOURCE", operational_eligible, rights_blocked

    if suggested == previous_candidate:
        state_entry["candidateWinStreak"] = int(state_entry.get("candidateWinStreak") or 0) + 1
    else:
        state_entry["candidateTechnicalSource"] = suggested
        state_entry["candidateWinStreak"] = 1

    if not operational_eligible:
        return "HOLD_SOURCE_NOT_APPROVED_FOR_INGEST", operational_eligible, rights_blocked

    last_switch = parse_iso(state_entry.get("lastSwitchAt"))
    cooldown_ok = last_switch is None or (now - last_switch).total_seconds() >= MIN_SWITCH_INTERVAL_HOURS * 3600
    streak_ok = state_entry["candidateWinStreak"] >= REQUIRED_CONSECUTIVE_WINS

    if streak_ok and cooldown_ok:
        return "SWITCH_ELIGIBLE_AFTER_GUARDS", operational_eligible, rights_blocked
    if not streak_ok:
        return "HOLD_WAIT_CONSECUTIVE_WINS", operational_eligible, rights_blocked
    return "HOLD_SWITCH_COOLDOWN", operational_eligible, rights_blocked


def main() -> None:
    if not RECOMMENDATIONS.exists():
        raise SystemExit("quality recommendations missing")

    now = datetime.now(timezone.utc)
    rec = load_json(RECOMMENDATIONS, {})
    state = load_json(STATE, {"schemaVersion": 2, "channels": {}})
    state["schemaVersion"] = 2
    channels_state = state.setdefault("channels", {})
    policies = source_policy()
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
        normalize_state_entry(s, now)

        meta = policies.get(suggested) if suggested else None
        action, operational_eligible, rights_blocked = evaluate_action(
            suggested=suggested,
            state_entry=s,
            source_meta=meta,
            now=now,
        )

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
            "stateStaleHours": STATE_STALE_HOURS,
            "sourceApprovedForIngest": operational_eligible,
            "rightsBlocked": rights_blocked,
            "rightsStatus": meta.get("rightsStatus") if meta else None,
            "publishAllowed": meta.get("publishAllowed") if meta else False,
            "candidateOnly": meta.get("candidateOnly") if meta else None,
            "action": action,
            "qualityReason": reason,
            "enforcement": "ADVISORY_ONLY_NO_MAPPING_MUTATION_NO_RIGHTS_CHANGE",
        })

    state["updatedAt"] = now.isoformat()
    state["policy"] = {
        "requiredConsecutiveWins": REQUIRED_CONSECUTIVE_WINS,
        "minimumSwitchIntervalHours": MIN_SWITCH_INTERVAL_HOURS,
        "stateStaleHours": STATE_STALE_HOURS,
        "mode": "advisory-only",
    }
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    OUT.write_text(json.dumps({
        "schemaVersion": 2,
        "generatedAt": now.isoformat(),
        "policy": {
            "requiredConsecutiveWins": REQUIRED_CONSECUTIVE_WINS,
            "minimumSwitchIntervalHours": MIN_SWITCH_INTERVAL_HOURS,
            "stateStaleHours": STATE_STALE_HOURS,
            "rightsGate": "Technical eligibility never grants ingestion, commercial-use or redistribution rights.",
            "operationalGate": "Only a source already approved with ingestEnabled=true may become switch-eligible.",
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
