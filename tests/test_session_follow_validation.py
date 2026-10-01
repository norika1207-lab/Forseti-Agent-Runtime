#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import session_follow_validation as V  # noqa: E402


class SessionFollowValidationTest(unittest.TestCase):
    def test_raw_tail_fingerprints_match_without_storing_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            rows = [
                {"type": "user", "sessionId": "s",
                 "message": {"content": "owner secret"}},
                {"type": "assistant", "sessionId": "s", "message": {
                    "content": [{"type": "text", "text": "answer secret"}]}},
            ]
            path.write_text("\n".join(json.dumps(x) for x in rows) + "\n",
                            encoding="utf-8")
            got = V.raw_tail_fingerprints(path)
            self.assertEqual(got["session_ids"], ["s"])
            self.assertEqual(got["owner_hash"], V._hash_text("owner secret"))
            self.assertEqual(got["assistant_hash"], V._hash_text("answer secret"))
            self.assertNotIn("owner secret", json.dumps(got))
            self.assertNotIn("answer secret", json.dumps(got))

    def test_system_injected_user_record_is_not_owner_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.jsonl"
            rows = [
                {"type": "user", "sessionId": "s",
                 "message": {"content": "real owner"}},
                {"type": "user", "sessionId": "s",
                 "message": {"content": "Contents of /tmp/CLAUDE.md"}},
            ]
            path.write_text("\n".join(json.dumps(x) for x in rows) + "\n",
                            encoding="utf-8")
            got = V.raw_tail_fingerprints(path)
            self.assertEqual(got["owner_hash"], V._hash_text("real owner"))
            self.assertEqual(got["excluded_system_user_records"], 1)

    def test_semantic_summary_does_not_upgrade_inference_to_truth(self):
        got = V._semantic_summary([
            {"path_semantics": {"state": "suspected", "epistemic": "INFERRED"}},
            {"corrected_by_owner": True,
             "path_semantics": {"state": "neutral", "epistemic": "UNKNOWN"}},
            {"path_semantics": {"state": "confirmed",
                                "epistemic": "OBSERVED+INFERRED"}},
        ])
        self.assertEqual(got["inferred_deviations"], 1)
        self.assertEqual(got["deterministic_deviations"], 1)
        self.assertEqual(got["owner_correction_missed_by_path_state_proxy"], 1)
        self.assertEqual(got["ground_truth_status"], "PARTIAL_PROXY_ONLY")

    def test_source_path_requires_one_exact_session_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "one").mkdir()
            (base / "two").mkdir()
            (base / "one" / "sid.jsonl").write_text("", encoding="utf-8")
            self.assertEqual(V._source_path("sid", base),
                             base / "one" / "sid.jsonl")
            (base / "two" / "sid.jsonl").write_text("", encoding="utf-8")
            self.assertIsNone(V._source_path("sid", base))
            self.assertIsNone(V._source_path("../sid", base))

    def test_validate_once_uses_current_focused_session_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "projects"
            source = base / "project" / "sid.jsonl"
            source.parent.mkdir(parents=True)
            source.write_text(
                json.dumps({"type": "user", "sessionId": "sid",
                            "message": {"content": "owner secret"}}) + "\n" +
                json.dumps({"type": "assistant", "sessionId": "sid",
                            "message": {"content": [
                                {"type": "text", "text": "answer secret"}]}}) + "\n",
                encoding="utf-8")
            row = {"owner_text": "owner secret", "ai_text": "answer secret",
                   "path_semantics": {"state": "neutral",
                                       "epistemic": "UNKNOWN"}}
            old_focused = V.desktop.focused_session
            old_strands = V.desktop.strands
            try:
                V.desktop.focused_session = lambda: "sid"
                V.desktop.strands = lambda persist=False: {
                    "session": "sid", "picked_by": "跟著你", "rows": [row]}
                report = V.validate_once(base, {})
            finally:
                V.desktop.focused_session = old_focused
                V.desktop.strands = old_strands
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["errors"], [])
            self.assertNotIn("owner secret", json.dumps(report["source"]))
            self.assertNotIn("answer secret", json.dumps(report["source"]))

    def test_run_rejects_invalid_iteration_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                V.run(0, 0, Path(tmp))
            with self.assertRaises(ValueError):
                V.run(1, -1, Path(tmp))


if __name__ == "__main__":
    unittest.main()
