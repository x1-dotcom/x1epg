from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tools.decision_guard import evaluate_action, normalize_state_entry


class DecisionGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 19, 13, 0, tzinfo=timezone.utc)

    def state(self):
        return {
            "currentTechnicalSource": None,
            "candidateTechnicalSource": None,
            "candidateWinStreak": 0,
            "lastSwitchAt": None,
            "lastObservedAt": self.now.isoformat(),
        }

    def test_candidate_only_source_never_becomes_switch_eligible(self):
        s = self.state()
        meta = {
            "approvedForIngest": False,
            "rightsStatus": "public-feed-no-license-found",
            "publishAllowed": False,
            "candidateOnly": True,
        }
        for _ in range(4):
            action, operational, rights_blocked = evaluate_action(
                suggested="doblem-global",
                state_entry=s,
                source_meta=meta,
                now=self.now,
            )
        self.assertEqual(action, "HOLD_SOURCE_NOT_APPROVED_FOR_INGEST")
        self.assertFalse(operational)
        self.assertTrue(rights_blocked)
        self.assertGreaterEqual(s["candidateWinStreak"], 3)

    def test_approved_ingest_source_requires_three_wins(self):
        s = self.state()
        meta = {
            "approvedForIngest": True,
            "rightsStatus": "public-feed-no-license-found",
            "publishAllowed": False,
            "candidateOnly": False,
        }
        action1, _, blocked1 = evaluate_action(
            suggested="epgshare01-es1", state_entry=s, source_meta=meta, now=self.now
        )
        action2, _, _ = evaluate_action(
            suggested="epgshare01-es1", state_entry=s, source_meta=meta, now=self.now
        )
        action3, operational3, blocked3 = evaluate_action(
            suggested="epgshare01-es1", state_entry=s, source_meta=meta, now=self.now
        )
        self.assertEqual(action1, "HOLD_WAIT_CONSECUTIVE_WINS")
        self.assertEqual(action2, "HOLD_WAIT_CONSECUTIVE_WINS")
        self.assertEqual(action3, "SWITCH_ELIGIBLE_AFTER_GUARDS")
        self.assertTrue(operational3)
        self.assertTrue(blocked1)
        self.assertTrue(blocked3)

    def test_no_recommendation_resets_streak(self):
        s = self.state()
        s["candidateTechnicalSource"] = "source-a"
        s["candidateWinStreak"] = 2
        action, _, _ = evaluate_action(
            suggested=None, state_entry=s, source_meta=None, now=self.now
        )
        self.assertEqual(action, "HOLD_NO_TECHNICAL_WINNER")
        self.assertIsNone(s["candidateTechnicalSource"])
        self.assertEqual(s["candidateWinStreak"], 0)

    def test_stale_state_resets_candidate_streak(self):
        s = self.state()
        s["candidateTechnicalSource"] = "source-a"
        s["candidateWinStreak"] = 2
        s["lastObservedAt"] = (self.now - timedelta(hours=100)).isoformat()
        normalize_state_entry(s, self.now)
        self.assertIsNone(s["candidateTechnicalSource"])
        self.assertEqual(s["candidateWinStreak"], 0)

    def test_naive_last_switch_is_discarded(self):
        s = self.state()
        s["lastSwitchAt"] = "2026-08-19T10:00:00"
        normalize_state_entry(s, self.now)
        self.assertIsNone(s["lastSwitchAt"])


if __name__ == "__main__":
    unittest.main()
