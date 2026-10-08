"""Strict, offline source recovery across a compaction boundary."""

import os
import sys
import json
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "forseti-cli"))
import rehydration as R  # noqa: E402


def row(n, owner="", ai=""):
    return {"n": n, "source_type": R.ORIGINAL,
            "source_ref": "session.jsonl:42", "owner_text": owner,
            "ai_text": ai}


class OriginalIntervalTest(unittest.TestCase):
    def recover(self, rows, **overrides):
        kwargs = {"source_rows": rows, "start_round": 1,
                  "compaction_round": 3, "goal": "Ship Forseti",
                  "task": "Check the original decision", "limit": 8000}
        kwargs.update(overrides)
        return R.recover_original_interval(**kwargs)

    def test_complete_original_interval_is_inspectable_not_injected(self):
        result = self.recover([row(2, ai="Original reason"),
                               row(1, owner="Owner correction")])
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["auto_inject"])
        packet = result["packet"]
        self.assertEqual([f["text"] for f in packet["original_fragments"]],
                         ["Owner correction", "Original reason"])
        self.assertTrue(all(f["source"] == R.ORIGINAL
                            and "session.jsonl:42" in f["provenance"]
                            for f in packet["original_fragments"]))
        self.assertEqual(packet["dropped_for_budget"], 0)

    def test_missing_source_or_round_is_unknown(self):
        for rows, reason in [(None, "missing_source"),
                             ([row(1, owner="A")], "missing_source_round")]:
            with self.subTest(reason=reason):
                result = self.recover(rows)
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertEqual(result["reason"], reason)
                self.assertIsNone(result["packet"])

    def test_empty_round_before_text_is_not_source_complete(self):
        result = self.recover([row(1, owner="", ai=""),
                               row(2, ai="Original reason")])
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "empty_original_round")
        self.assertIsNone(result["packet"])
        self.assertFalse(result["auto_inject"])

    def test_unattributed_or_summary_source_is_unknown(self):
        for change in ({"source_ref": ""}, {"source_type": R.SUMMARY},
                       {"owner_text": None}):
            with self.subTest(change=change):
                bad = row(1, owner="A") | change
                result = self.recover([bad, row(2, ai="B")])
                self.assertEqual(result["status"], "UNKNOWN")
                self.assertIsNone(result["packet"])

    def test_duplicate_round_is_unknown(self):
        result = self.recover([row(1, owner="A"), row(1, owner="B"),
                               row(2, ai="C")])
        self.assertEqual(result["reason"], "duplicate_source_round")

    def test_capacity_overflow_never_returns_partial_packet(self):
        result = self.recover([row(1, owner="A" * 200), row(2, ai="B")],
                              limit=100)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "capacity_overflow")
        self.assertIsNone(result["packet"])
        self.assertFalse(result["auto_inject"])

    def test_source_metadata_counts_against_capacity(self):
        rows = [row(1, owner="A"), row(2, ai="B")]
        rows[0]["source_ref"] = "session.jsonl:" + "x" * 500
        result = self.recover(rows, limit=450)
        self.assertEqual(result["reason"], "capacity_overflow")
        self.assertIsNone(result["packet"])

    def test_jsonl_source_ref_comes_from_physical_file_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.jsonl"
            records = [row(1, owner="Owner correction"),
                       row(2, ai="Original reason")]
            path.write_text("\n".join(json.dumps(r) for r in records) + "\n",
                            encoding="utf-8")
            result = R.recover_original_jsonl_interval(
                source_path=str(path), start_round=1, compaction_round=3,
                goal="Ship Forseti", task="Check reason")
            self.assertEqual(result["status"], "READY")
            self.assertFalse(result["auto_inject"])
            refs = result["packet"]["provenance_refs"]
            self.assertEqual(refs, [f"{path.resolve()}:1#1:owner_text",
                                    f"{path.resolve()}:2#2:ai_text"])

    def test_jsonl_source_with_empty_round_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in
                                      [row(1), row(2, ai="Original reason")]) + "\n",
                            encoding="utf-8")
            result = R.recover_original_jsonl_interval(
                source_path=str(path), start_round=1, compaction_round=3,
                goal="Ship Forseti", task="Check reason")
            self.assertEqual(result["reason"], "empty_original_round")
            self.assertIsNone(result["packet"])

    def test_missing_or_corrupt_jsonl_source_is_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "original.jsonl"
            kwargs = {"source_path": str(path), "start_round": 1,
                      "compaction_round": 3, "goal": "Goal", "task": "Task"}
            self.assertEqual(R.recover_original_jsonl_interval(**kwargs)["reason"],
                             "missing_source")
            path.write_text('{broken json}\n', encoding="utf-8")
            result = R.recover_original_jsonl_interval(**kwargs)
            self.assertEqual(result["status"], "UNKNOWN")
            self.assertEqual(result["reason"], "unreadable_source")
            self.assertIsNone(result["packet"])

    def test_invalid_round_range_does_not_read_source(self):
        result = R.recover_original_jsonl_interval(
            source_path="/does/not/exist", start_round="1",
            compaction_round=3, goal="Goal", task="Task")
        self.assertEqual(result["reason"], "invalid_round_range")


if __name__ == "__main__":
    unittest.main()
