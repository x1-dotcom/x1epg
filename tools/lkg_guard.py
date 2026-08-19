#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
INDEX = DATA / "index.json"
RUNTIME_DIR = ROOT / ".runtime-lkg"
BACKUP_INDEX = RUNTIME_DIR / "index.json"
BASELINE = RUNTIME_DIR / "baseline.json"
STATE = DATA / "lkg-state.json"
DECISION = DATA / "lkg-decision.json"


def sha256_path(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_index(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "sha256": None, "channelCount": 0, "countries": {}}
    payload = json.loads(path.read_text(encoding="utf-8"))
    channels = payload.get("channels", [])
    if not isinstance(channels, list):
        raise RuntimeError("index channels must be an array")
    countries = Counter(str(row.get("country") or "UNKNOWN") for row in channels)
    return {
        "exists": True,
        "sha256": sha256_path(path),
        "channelCount": len(channels),
        "countries": dict(sorted(countries.items())),
    }


def snapshot() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if BACKUP_INDEX.exists():
        BACKUP_INDEX.unlink()
    baseline = inspect_index(INDEX)
    if INDEX.exists():
        shutil.copy2(INDEX, BACKUP_INDEX)
    BASELINE.write_text(json.dumps({
        "schemaVersion": 1,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "index": baseline,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"LKG snapshot: exists={baseline['exists']} channels={baseline['channelCount']} sha256={baseline['sha256']}")


def restore_baseline() -> dict:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {"index": {"exists": False}}
    existed = bool(baseline.get("index", {}).get("exists"))
    if existed:
        if not BACKUP_INDEX.exists():
            raise RuntimeError("baseline says index existed but backup is missing")
        shutil.copy2(BACKUP_INDEX, INDEX)
    elif INDEX.exists():
        INDEX.unlink()
    restored = inspect_index(INDEX)
    expected_sha = baseline.get("index", {}).get("sha256")
    if restored.get("sha256") != expected_sha:
        raise RuntimeError("restored index digest does not match captured baseline")
    return restored


def finalize(channel_list: str, sync: str, merge: str) -> None:
    if not BASELINE.exists():
        raise RuntimeError("LKG baseline missing; run snapshot before building candidate index")

    now = datetime.now(timezone.utc)
    candidate = inspect_index(INDEX)
    gates = {
        "channelList": channel_list,
        "liveSync": sync,
        "mergePlan": merge,
    }
    gate_success = all(value == "success" for value in gates.values())
    candidate_valid = candidate["exists"] and candidate["channelCount"] > 0
    promote = gate_success and candidate_valid

    if promote:
        state = {
            "schemaVersion": 1,
            "promotedAt": now.isoformat(),
            "index": candidate,
            "gates": gates,
            "policy": "Only a non-empty candidate index whose channel-list, live-ingestion and merge gates all succeeded becomes last-known-good.",
        }
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        decision = {
            "schemaVersion": 1,
            "generatedAt": now.isoformat(),
            "decision": "PROMOTED_NEW_LKG",
            "gates": gates,
            "candidate": candidate,
            "activeIndex": candidate,
            "rollbackPerformed": False,
            "automaticSourceMutationAllowed": False,
        }
        print(f"LKG promotion: PROMOTED channels={candidate['channelCount']} sha256={candidate['sha256']}")
    else:
        restored = restore_baseline()
        reasons = []
        for name, outcome in gates.items():
            if outcome != "success":
                reasons.append(f"{name}={outcome}")
        if not candidate["exists"]:
            reasons.append("candidate-index-missing")
        elif candidate["channelCount"] <= 0:
            reasons.append("candidate-index-empty")
        decision = {
            "schemaVersion": 1,
            "generatedAt": now.isoformat(),
            "decision": "REJECTED_KEEP_PREVIOUS_LKG",
            "reasons": reasons,
            "gates": gates,
            "candidate": candidate,
            "activeIndex": restored,
            "rollbackPerformed": True,
            "automaticSourceMutationAllowed": False,
        }
        print(f"LKG promotion: REJECTED reasons={reasons} restoredSha256={restored['sha256']}")

    DECISION.write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("snapshot")
    final = sub.add_parser("finalize")
    final.add_argument("--channel-list", required=True)
    final.add_argument("--sync", required=True)
    final.add_argument("--merge", required=True)
    args = parser.parse_args()

    if args.command == "snapshot":
        snapshot()
    else:
        finalize(args.channel_list, args.sync, args.merge)


if __name__ == "__main__":
    main()
