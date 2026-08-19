from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tools.runtime_failure_forensics import collect_failures, fingerprint, update_state


class FailureCollectionTests(unittest.TestCase):
    def test_missing_channel_list_mapping_is_actionable(self):
        failures = collect_failures(
            {"sources": []},
            {"sources": [{
                "country": "PT",
                "sourceId": "epgshare01-pt1",
                "status": "FAILED",
                "mappedMissing": ["Old.Channel.pt"],
                "missingCanonicalIds": ["old-channel"],
            }]},
        )
        self.assertEqual(len(failures), 1)
        row = failures[0]
        self.assertEqual(row["issue"], "CHANNEL_ID_MISSING_UPSTREAM")
        self.assertEqual(row["canonicalId"], "old-channel")
        self.assertEqual(row["upstreamChannelId"], "Old.Channel.pt")
        self.assertFalse(row["automaticMutationAllowed"])

    def test_sync_failures_are_classified(self):
        failures = collect_failures(
            {"sources": [{
                "country": "ES",
                "sourceId": "epgshare01-es1",
                "mappedMissing": ["Missing.es"],
                "mappedWithoutProgrammes": ["Empty.es"],
                "malformedMappedTimestampCount": 2,
                "fresh": False,
                "newestMappedProgrammeAgeHours": 60,
                "freshnessLimitHours": 48,
            }]},
            {"sources": []},
        )
        issues = {row["issue"] for row in failures}
        self.assertEqual(issues, {
            "MAPPED_CHANNEL_MISSING_XMLTV",
            "MAPPED_CHANNEL_WITHOUT_PROGRAMMES",
            "MALFORMED_OR_NAIVE_XMLTV_TIMESTAMPS",
            "STALE_OR_UNDATED_PROGRAMMES",
        })

    def test_zero_mapping_error_is_not_generic(self):
        failures = collect_failures(
            {"sources": [{
                "country": "DE",
                "sourceId": "source-a",
                "error": "ingest-enabled source has zero enabled canonical mappings",
            }]},
            {"sources": []},
        )
        self.assertEqual(failures[0]["issue"], "ZERO_ENABLED_MAPPINGS")


class StatefulForensicsTests(unittest.TestCase):
    def test_fingerprint_is_stable(self):
        self.assertEqual(
            fingerprint("s", "c", "ISSUE", "u"),
            fingerprint("s", "c", "ISSUE", "u"),
        )

    def test_consecutive_observations_and_resolution(self):
        now1 = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
        row = {
            "fingerprint": fingerprint("source", "channel", "ISSUE"),
            "country": "PT",
            "sourceId": "source",
            "canonicalId": "channel",
            "upstreamChannelId": None,
            "issue": "ISSUE",
            "detail": None,
            "evidence": "x",
            "recommendedAction": "inspect",
            "automaticMutationAllowed": False,
        }
        state1, enriched1 = update_state([row], now1, {"failures": {}})
        self.assertEqual(enriched1[0]["consecutiveObservations"], 1)

        now2 = datetime(2026, 8, 19, 18, 0, tzinfo=timezone.utc)
        state2, enriched2 = update_state([row], now2, state1)
        self.assertEqual(enriched2[0]["consecutiveObservations"], 2)
        self.assertEqual(enriched2[0]["firstSeenAt"], now1.isoformat())

        now3 = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)
        state3, enriched3 = update_state([], now3, state2)
        self.assertEqual(enriched3, [])
        self.assertEqual(len(state3["recentlyResolved"]), 1)
        self.assertEqual(state3["recentlyResolved"][0]["resolvedAt"], now3.isoformat())


if __name__ == "__main__":
    unittest.main()
