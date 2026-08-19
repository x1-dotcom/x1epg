#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
PROVENANCE = DATA / "run-provenance.json"
LKG_DECISION = DATA / "lkg-decision.json"
INDEX = DATA / "index.json"
STATE = DATA / "integrity-chain.json"
HISTORY = DATA / "integrity-chain-history.jsonl"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str | None:
    return sha256_bytes(path.read_bytes()) if path.exists() else None


def canonical_json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def link_digest(link_core: dict) -> str:
    return sha256_bytes(canonical_json_bytes(link_core))


def read_history(path: Path = HISTORY) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"integrity history line {number} is invalid JSON") from exc
        if not isinstance(row, dict):
            raise RuntimeError(f"integrity history line {number} must be an object")
        rows.append(row)
    return rows


def verify_rows(rows: list[dict]) -> dict:
    previous: str | None = None
    for position, row in enumerate(rows, start=1):
        sequence = row.get("sequence")
        if sequence != position:
            raise RuntimeError(f"integrity sequence mismatch at position {position}: {sequence!r}")
        if row.get("previousHeadSha256") != previous:
            raise RuntimeError(f"integrity previous-head mismatch at sequence {position}")
        head = row.get("headSha256")
        core = {key: value for key, value in row.items() if key != "headSha256"}
        expected = link_digest(core)
        if head != expected:
            raise RuntimeError(f"integrity head digest mismatch at sequence {position}")
        previous = head
    return {
        "entryCount": len(rows),
        "headSha256": previous,
        "status": "PASS",
    }


def verify_state_against_history(rows: list[dict], state_path: Path = STATE) -> None:
    if not state_path.exists():
        if rows:
            raise RuntimeError("integrity history exists but chain state is missing")
        return
    state = json.loads(state_path.read_text(encoding="utf-8"))
    expected_sequence = len(rows)
    expected_head = rows[-1]["headSha256"] if rows else None
    if state.get("sequence") != expected_sequence:
        raise RuntimeError("integrity state sequence does not match history")
    if state.get("headSha256") != expected_head:
        raise RuntimeError("integrity state head does not match history")


def load_provenance(path: Path = PROVENANCE) -> dict:
    if not path.exists():
        raise RuntimeError("run provenance missing; generate it before integrity chaining")
    payload = json.loads(path.read_text(encoding="utf-8"))
    digest = payload.get("provenanceSha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise RuntimeError("run provenance has no valid provenanceSha256")
    return payload


def make_link_core(provenance: dict, previous_head: str | None, sequence: int, generated_at: str) -> dict:
    identity = provenance.get("identity", {}) if isinstance(provenance.get("identity"), dict) else {}
    return {
        "schemaVersion": 1,
        "sequence": sequence,
        "generatedAt": generated_at,
        "previousHeadSha256": previous_head,
        "provenanceSha256": provenance["provenanceSha256"],
        "repository": identity.get("repository"),
        "commitSha": identity.get("commitSha"),
        "runId": identity.get("runId"),
        "runAttempt": identity.get("runAttempt"),
        "activeIndexSha256": sha256_path(INDEX),
        "lkgDecisionSha256": sha256_path(LKG_DECISION),
        "policy": "Hash-chain tamper evidence for X1 EPG run records. This is not a digital signature or an external transparency-log anchor.",
    }


def append() -> dict:
    rows = read_history()
    verify_rows(rows)
    verify_state_against_history(rows)
    provenance = load_provenance()

    identity = provenance.get("identity", {}) if isinstance(provenance.get("identity"), dict) else {}
    run_key = (
        identity.get("runId"),
        identity.get("runAttempt"),
        provenance.get("provenanceSha256"),
    )
    if rows:
        last = rows[-1]
        last_key = (last.get("runId"), last.get("runAttempt"), last.get("provenanceSha256"))
        if run_key == last_key:
            print(f"Integrity chain: IDEMPOTENT sequence={last['sequence']} head={last['headSha256']}")
            return last

    generated_at = datetime.now(timezone.utc).isoformat()
    previous = rows[-1]["headSha256"] if rows else None
    core = make_link_core(provenance, previous, len(rows) + 1, generated_at)
    row = {**core, "headSha256": link_digest(core)}
    rows.append(row)

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text("".join(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for item in rows), encoding="utf-8")
    STATE.write_text(json.dumps({
        "schemaVersion": 1,
        "updatedAt": generated_at,
        "sequence": row["sequence"],
        "headSha256": row["headSha256"],
        "previousHeadSha256": row["previousHeadSha256"],
        "provenanceSha256": row["provenanceSha256"],
        "policy": "Current X1 EPG integrity-chain head. Verify against integrity-chain-history.jsonl before trusting it.",
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Integrity chain: APPENDED sequence={row['sequence']} head={row['headSha256']}")
    return row


def verify() -> dict:
    rows = read_history()
    result = verify_rows(rows)
    verify_state_against_history(rows)
    print(f"Integrity chain: PASS entries={result['entryCount']} head={result['headSha256']}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("append", "verify"))
    args = parser.parse_args()
    if args.command == "append":
        append()
    else:
        verify()


if __name__ == "__main__":
    main()
