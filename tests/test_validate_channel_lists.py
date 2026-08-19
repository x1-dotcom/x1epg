from __future__ import annotations

import unittest

from tools.validate_channel_lists import mappings_for_source, parse_channel_ids, validate_manifest_source


class ChannelListTests(unittest.TestCase):
    def test_parse_channel_ids_ignores_blank_and_comments(self):
        text = "\n# generated\nA.one\n B.two \nA.one\n"
        self.assertEqual(parse_channel_ids(text), {"A.one", "B.two"})

    def test_exact_mapping_membership(self):
        manifest = {
            "country": "XX",
            "sources": [{"sourceId": "source-a"}],
            "channels": [
                {
                    "canonicalId": "one",
                    "sourceMappings": [
                        {"sourceId": "source-a", "channelId": "A.one", "priority": 1, "enabled": True}
                    ],
                },
                {
                    "canonicalId": "two",
                    "sourceMappings": [
                        {"sourceId": "source-a", "channelId": "B.two", "priority": 1, "enabled": True}
                    ],
                },
            ],
        }
        source = {"sourceId": "source-a", "channelListUrl": "https://example.invalid/list.txt"}
        row = validate_manifest_source(manifest, source, {"A.one"})
        self.assertEqual(row["status"], "FAILED")
        self.assertEqual(row["mappedMissing"], ["B.two"])
        self.assertEqual(row["missingCanonicalIds"], ["two"])

    def test_disabled_mapping_is_ignored(self):
        manifest = {
            "country": "XX",
            "sources": [{"sourceId": "source-a"}],
            "channels": [
                {
                    "canonicalId": "one",
                    "sourceMappings": [
                        {"sourceId": "source-a", "channelId": "A.one", "priority": 1, "enabled": False}
                    ],
                }
            ],
        }
        self.assertEqual(mappings_for_source(manifest, "source-a"), {})


if __name__ == "__main__":
    unittest.main()
