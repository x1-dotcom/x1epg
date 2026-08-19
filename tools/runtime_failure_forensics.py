#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "data" / "sync-report.json"
CHANNEL_LIST = ROOT / "data" / "channel-list-validation.json"
STATE = ROOT / "data" / "runtime-failure-state.json"
OUT = ROOT / "data" / "runtime-failure-forensics.json"


def load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def fingerprint(source_id: str, canonical_id: str | None, issue: str, upstream_id: str | None = None) -> str:
    raw = "|".join([source_id or "", canonical_id or "", issue or "", upstream_id or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def add_failure(rows: list[dict], *, country: str | None, source_id: str, issue: str,
                canonical_id: str | None = None, upstream_id: str | None = None,
                evidence: str, detail: str | None = None) -> None:
    action_map = {
        "CHANNEL_ID_MISSING_UPSTREAM": "Verify the exact upstream channel ID and update the manifest only with proven evidence.",
        "MAPPED_CHANNEL_MISSING_XMLTV": "Compare the current upstream channel list and XMLTV channel elements; do not fuzzy-remap automatically.",
        "MAPPED_CHANNEL_WITHOUT_PROGRAMMES": "Confirm whether the channel is temporarily empty or has moved to another proven source ID.",
        "MALFORMED_OR_NAIVE_XMLTV_TIMESTAMPS": "Reject the source until it provides timezone-aware valid XMLTV timestamps.",
        "STALE_OR_UNDATED_PROGRAMMES": "Keep last-known-good data and investigate upstream freshness before any source switch.",
        "FETCH_OR_PARSE_FAILURE": "Inspect network/content-type/redirect/XML parse evidence; do not bypass network safety gates.",
        "ZERO_ENABLED_MAPPINGS": "Fix manifest authority: an ingest-enabled source must have at least one explicit enabled mapping.",
    }
    rows.append({
        "fingerprint": fingerprint(source_id, canonical_id, issue, upstream_id),
        "country": country,
        "sourceId": source_id,
        "canonicalId": canonical_id,
        "upstreamChannelId": upstream_id,
        "issue": issue,
        "detail": detail,
        "evidence": evidence,
        "recommendedAction": action_map.get(issue, "Inspect the cited runtime evidence before changing source mappings."),
        "automaticMutationAllowed": False,
    })


def collect_failures(sync: dict, channel_list: dict) -> list[dict]:
    rows: list[dict] = []

    for source in channel_list.get("sources", []):
        source_id = source.get("sourceId") or "unknown"
        country = source.get("country")
        missing_ids = source.get("mappedMissing", []) or []
        missing_canonical = source.get("missingCanonicalIds", []) or []
        for idx, upstream_id in enumerate(missing_ids):
            canonical = missing_canonical[idx] if idx < len(missing_canonical) else None
            add_failure(rows, country=country, source_id=source_id, issue="CHANNEL_ID_MISSING_UPSTREAM",
                        canonical_id=canonical, upstream_id=upstream_id,
                        evidence="data/channel-list-validation.json")
        if source.get("status") == "FAILED" and source.get("error") and not missing_ids:
            add_failure(rows, country=country, source_id=source_id, issue="FETCH_OR_PARSE_FAILURE",
                        evidence="data/channel-list-validation.json", detail=str(source.get("error")))

    for source in sync.get("sources", []):
        source_id = source.get("sourceId") or "unknown"
        country = source.get("country")
        error = source.get("error")
        if error:
            issue = "ZERO_ENABLED_MAPPINGS" if "zero enabled canonical mappings" in str(error) else "FETCH_OR_PARSE_FAILURE"
            add_failure(rows, country=country, source_id=source_id, issue=issue,
                        evidence="data/sync-report.json", detail=str(error))
            continue

        for upstream_id in source.get("mappedMissing", []) or []:
            add_failure(rows, country=country, source_id=source_id, issue="MAPPED_CHANNEL_MISSING_XMLTV",
                        upstream_id=upstream_id, evidence="data/sync-report.json")
        for upstream_id in source.get("mappedWithoutProgrammes", []) or []:
            add_failure(rows, country=country, source_id=source_id, issue="MAPPED_CHANNEL_WITHOUT_PROGRAMMES",
                        upstream_id=upstream_id, evidence="data/sync-report.json")
        if int(source.get("malformedMappedTimestampCount") or 0) > 0:
            add_failure(rows, country=country, source_id=source_id, issue="MALFORMED_OR_NAIVE_XMLTV_TIMESTAMPS",
                        evidence="data/sync-report.json",
                        detail=f"count={int(source.get('malformedMappedTimestampCount') or 0)}")
        if source.get("fresh") is False:
            add_failure(rows, country=country, source_id=source_id, issue="STALE_OR_UNDATED_PROGRAMMES",
                        evidence="data/sync-report.json",
                        detail=f"ageHours={source.get('newestMappedProgrammeAgeHours')} limitHours={source.get('freshnessLimitHours')}")

    unique: dict[str, dict] = {}
    for row in rows:
        unique[row["fingerprint"]] = row
    return sorted(unique.values(), key=lambda r: (r.get("country") or "", r["sourceId"], r["issue"], r.get("canonicalId") or "", r.get("upstreamChannelId") or ""))


def update_state(failures: list[dict], now: datetime, previous: dict) -> tuple[dict, list[dict]]:
    previous_items = previous.get("failures", {}) if isinstance(previous, dict) else {}
    current_ids = {row["fingerprint"] for row in failures}
    state_items: dict[str, dict] = {}
    enriched: list[dict] = []

    for row in failures:
        fid = row["fingerprint"]
        old = previous_items.get(fid, {})
        first_seen = old.get("firstSeenAt") or now.isoformat()
        observations = int(old.get("consecutiveObservations") or 0) + 1
        state_row = {
            "firstSeenAt": first_seen,
            "lastSeenAt": now.isoformat(),
            "consecutiveObservations": observations,
            "lastIssue": row["issue"],
            "resolvedAt": None,
        }
        state_items[fid] = state_row
        enriched.append({**row, **state_row})

    resolved: list[dict] = []
    for fid, old in previous_items.items():
        if fid in current_ids:
            continue
        resolved.append({
            "fingerprint": fid,
            "firstSeenAt": old.get("firstSeenAt"),
            "lastSeenAt": old.get("lastSeenAt"),
            "resolvedAt": now.isoformat(),
            "lastIssue": old.get("lastIssue"),
        })

    state = {
        "schemaVersion": 1,
        "updatedAt": now.isoformat(),
        "failures": state_items,
        "recentlyResolved": resolved[-200:],
    }
    return state, enriched


def main() -> None:
    now = datetime.now(timezone.utc)
    sync = load_json(SYNC, {"sources": []})
    channel_list = load_json(CHANNEL_LIST, {"sources": []})
    failures = collect_failures(sync, channel_list)
    state, enriched = update_state(failures, now, load_json(STATE, {"failures": {}}))

    counts_by_issue: dict[str, int] = {}
    counts_by_country: dict[str, int] = {}
    for row in enriched:
        counts_by_issue[row["issue"]] = counts_by_issue.get(row["issue"], 0) + 1
        country = row.get("country") or "UNKNOWN"
        counts_by_country[country] = counts_by_country.get(country, 0) + 1

    payload = {
        "schemaVersion": 1,
        "generatedAt": now.isoformat(),
        "status": "PASS" if not enriched else "FAILURES_PRESENT",
        "policy": "Forensic and advisory only. No automatic source mapping mutation, rights change, fallback promotion or publication decision.",
        "failureCount": len(enriched),
        "countsByIssue": counts_by_issue,
        "countsByCountry": counts_by_country,
        "failures": enriched,
        "recentlyResolved": state["recentlyResolved"],
    }
    STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Runtime forensics: {payload['status']} failures={len(enriched)}")
    print("By issue:", counts_by_issue)
    print("By country:", counts_by_country)
    for row in enriched:
        print(row["country"], row["sourceId"], row["issue"], row.get("canonicalId"), row.get("upstreamChannelId"))


if __name__ == "__main__":
    main()
