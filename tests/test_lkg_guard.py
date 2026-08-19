from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import tools.lkg_guard as guard


class LkgGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = {
            "ROOT": guard.ROOT,
            "DATA": guard.DATA,
            "INDEX": guard.INDEX,
            "RUNTIME_DIR": guard.RUNTIME_DIR,
            "BACKUP_INDEX": guard.BACKUP_INDEX,
            "BASELINE": guard.BASELINE,
            "STATE": guard.STATE,
            "DECISION": guard.DECISION,
        }
        guard.ROOT = root
        guard.DATA = root / "data"
        guard.INDEX = guard.DATA / "index.json"
        guard.RUNTIME_DIR = root / ".runtime-lkg"
        guard.BACKUP_INDEX = guard.RUNTIME_DIR / "index.json"
        guard.BASELINE = guard.RUNTIME_DIR / "baseline.json"
        guard.STATE = guard.DATA / "lkg-state.json"
        guard.DECISION = guard.DATA / "lkg-decision.json"
        guard.DATA.mkdir(parents=True)

    def tearDown(self):
        for name, value in self.old.items():
            setattr(guard, name, value)
        self.tmp.cleanup()

    def write_index(self, ids):
        guard.INDEX.write_text(json.dumps({
            "schemaVersion": 1,
            "channels": [{"canonicalId": cid, "country": "PT"} for cid in ids],
        }), encoding="utf-8")

    def test_failed_gate_restores_previous_index(self):
        self.write_index(["old-a"])
        guard.snapshot()
        self.write_index(["new-a", "new-b"])
        guard.finalize("failure", "success", "success")
        active = json.loads(guard.INDEX.read_text(encoding="utf-8"))
        self.assertEqual([c["canonicalId"] for c in active["channels"]], ["old-a"])
        decision = json.loads(guard.DECISION.read_text(encoding="utf-8"))
        self.assertEqual(decision["decision"], "REJECTED_KEEP_PREVIOUS_LKG")
        self.assertTrue(decision["rollbackPerformed"])

    def test_all_gates_success_promotes_candidate(self):
        self.write_index(["old-a"])
        guard.snapshot()
        self.write_index(["new-a", "new-b"])
        guard.finalize("success", "success", "success")
        active = json.loads(guard.INDEX.read_text(encoding="utf-8"))
        self.assertEqual(len(active["channels"]), 2)
        state = json.loads(guard.STATE.read_text(encoding="utf-8"))
        self.assertEqual(state["index"]["channelCount"], 2)
        decision = json.loads(guard.DECISION.read_text(encoding="utf-8"))
        self.assertEqual(decision["decision"], "PROMOTED_NEW_LKG")
        self.assertFalse(decision["rollbackPerformed"])

    def test_empty_candidate_never_promotes(self):
        self.write_index(["old-a"])
        guard.snapshot()
        self.write_index([])
        guard.finalize("success", "success", "success")
        active = json.loads(guard.INDEX.read_text(encoding="utf-8"))
        self.assertEqual(len(active["channels"]), 1)
        decision = json.loads(guard.DECISION.read_text(encoding="utf-8"))
        self.assertIn("candidate-index-empty", decision["reasons"])

    def test_missing_previous_index_is_restored_to_absence(self):
        guard.snapshot()
        self.write_index(["candidate"])
        guard.finalize("success", "failure", "skipped")
        self.assertFalse(guard.INDEX.exists())


if __name__ == "__main__":
    unittest.main()
