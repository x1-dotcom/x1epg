from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.integrity_chain import link_digest, read_history, verify_rows


class IntegrityChainTests(unittest.TestCase):
    def make_row(self, sequence: int, previous: str | None, provenance: str) -> dict:
        core = {
            "schemaVersion": 1,
            "sequence": sequence,
            "generatedAt": f"2026-08-19T13:0{sequence}:00+00:00",
            "previousHeadSha256": previous,
            "provenanceSha256": provenance,
            "repository": "x1-dotcom/x1epg",
            "commitSha": "a" * 40,
            "runId": str(100 + sequence),
            "runAttempt": "1",
            "activeIndexSha256": "b" * 64,
            "lkgDecisionSha256": "c" * 64,
            "policy": "test",
        }
        return {**core, "headSha256": link_digest(core)}

    def test_valid_chain_passes(self):
        first = self.make_row(1, None, "1" * 64)
        second = self.make_row(2, first["headSha256"], "2" * 64)
        result = verify_rows([first, second])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["entryCount"], 2)
        self.assertEqual(result["headSha256"], second["headSha256"])

    def test_tampered_payload_is_rejected(self):
        row = self.make_row(1, None, "1" * 64)
        row["commitSha"] = "f" * 40
        with self.assertRaises(RuntimeError):
            verify_rows([row])

    def test_deleted_middle_link_is_rejected(self):
        first = self.make_row(1, None, "1" * 64)
        second = self.make_row(2, first["headSha256"], "2" * 64)
        third = self.make_row(3, second["headSha256"], "3" * 64)
        with self.assertRaises(RuntimeError):
            verify_rows([first, third])

    def test_reordered_links_are_rejected(self):
        first = self.make_row(1, None, "1" * 64)
        second = self.make_row(2, first["headSha256"], "2" * 64)
        with self.assertRaises(RuntimeError):
            verify_rows([second, first])

    def test_history_parser_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            path.write_text('{"ok":true}\nnot-json\n', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                read_history(path)

    def test_history_parser_accepts_canonical_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.jsonl"
            row = self.make_row(1, None, "1" * 64)
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            loaded = read_history(path)
            self.assertEqual(loaded[0]["headSha256"], row["headSha256"])


if __name__ == "__main__":
    unittest.main()
