from __future__ import annotations

import unittest
from datetime import datetime, timezone

from tools.sync_epg import mappings_for_source
from tools.xmltv_time import parse_xmltv_time


class XmltvTimeTests(unittest.TestCase):
    def test_positive_offset_converts_to_utc(self):
        self.assertEqual(parse_xmltv_time("20260819143000 +0200"), datetime(2026, 8, 19, 12, 30, tzinfo=timezone.utc))

    def test_negative_offset_converts_to_utc(self):
        self.assertEqual(parse_xmltv_time("20260819143000 -0300"), datetime(2026, 8, 19, 17, 30, tzinfo=timezone.utc))

    def test_naive_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_xmltv_time("20260819143000")

    def test_invalid_offset_minutes_are_rejected(self):
        with self.assertRaises(ValueError):
            parse_xmltv_time("20260819143000 +1260")

    def test_invalid_offset_range_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_xmltv_time("20260819143000 +1430")

    def test_invalid_calendar_date_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_xmltv_time("20260230143000 +0000")

    def test_whitespace_is_normalized_only_at_edges(self):
        self.assertEqual(parse_xmltv_time(" 20260819143000 +0200 "), datetime(2026, 8, 19, 12, 30, tzinfo=timezone.utc))


class MappingTests(unittest.TestCase):
    def test_modern_source_mappings_are_used(self):
        manifest = {"sources": [{"sourceId": "source-a"}], "channels": [{"canonicalId": "channel-a", "sourceMappings": [{"sourceId": "source-a", "channelId": "Upstream.A", "priority": 1, "enabled": True}]}]}
        self.assertEqual(mappings_for_source(manifest, "source-a"), {"Upstream.A": "channel-a"})

    def test_disabled_mapping_is_not_ingested(self):
        manifest = {"sources": [{"sourceId": "source-a"}], "channels": [{"canonicalId": "channel-a", "sourceMappings": [{"sourceId": "source-a", "channelId": "Upstream.A", "priority": 1, "enabled": False}]}]}
        self.assertEqual(mappings_for_source(manifest, "source-a"), {})


if __name__ == "__main__":
    unittest.main()
