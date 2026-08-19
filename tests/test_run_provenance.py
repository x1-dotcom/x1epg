from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.run_provenance import canonical_json_digest, manifest_inventory, upstream_inventory


class ProvenanceDigestTests(unittest.TestCase):
    def test_canonical_digest_ignores_key_order(self):
        self.assertEqual(canonical_json_digest({"a": 1, "b": 2}), canonical_json_digest({"b": 2, "a": 1}))

    def test_manifest_inventory_records_raw_and_canonical_digests(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sources").mkdir()
            payload = {
                "schemaVersion": 1,
                "sourceGroup": "spain",
                "country": "ES",
                "timezone": "Europe/Madrid",
                "languages": ["es-ES"],
                "sources": [{"sourceId": "source-a"}],
                "channels": [{"canonicalId": "channel-a"}],
            }
            (root / "sources" / "spain.json").write_text(json.dumps(payload), encoding="utf-8")
            rows = manifest_inventory(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["country"], "ES")
            self.assertEqual(rows[0]["channelCount"], 1)
            self.assertEqual(rows[0]["sourceIds"], ["source-a"])
            self.assertEqual(len(rows[0]["sha256"]), 64)
            self.assertEqual(len(rows[0]["canonicalJsonSha256"]), 64)


class UpstreamInventoryTests(unittest.TestCase):
    def test_upstream_digests_are_collected_without_payload_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "channel-list-validation.json").write_text(json.dumps({
                "sources": [{
                    "sourceId": "source-a",
                    "channelListUrl": "https://example.com/list.txt",
                    "channelListSha256": "a" * 64,
                    "channelListBytes": 123,
                    "status": "OK",
                }]
            }), encoding="utf-8")
            (data / "sync-report.json").write_text(json.dumps({
                "sources": [{
                    "sourceId": "source-a",
                    "url": "https://example.com/feed.xml.gz",
                    "compressedSha256": "b" * 64,
                    "compressedBytes": 456,
                    "xmlSha256": "c" * 64,
                    "xmlBytes": 789,
                    "status": "OK",
                }]
            }), encoding="utf-8")
            rows = upstream_inventory(data)
            self.assertEqual([r["kind"] for r in rows], ["channel-list", "xmltv-decoded", "xmltv-wire"])
            self.assertTrue(all("data" not in r for r in rows))


if __name__ == "__main__":
    unittest.main()
