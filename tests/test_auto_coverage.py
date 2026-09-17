#!/usr/bin/env python3
"""自動涵蓋。守的是「它不准把自己推出來的當成親眼讀過的」。

HANDOVER_FAILURE §19.7 記著:涵蓋記錄靠自律,而這整套東西講的
就是自律不可靠。這支把那一塊拿掉 —— 每一次 Read 都已經在
transcript 裡了,不需要改工作流程,只要回頭讀那份紀錄。

但它有一個已知的偏誤方向:**它會高估。**
所以這一組測試有一半在守那個偏誤被誠實標出來。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import coverage as C  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "auto_coverage", REPO / "tools" / "auto-coverage.py")
AC = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = AC
spec.loader.exec_module(AC)


class Case(unittest.TestCase):

    def setUp(self):
        self.box = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.box, ignore_errors=True))
        self.old = os.environ.get("FORSETI_COVERAGE_LOG")
        os.environ["FORSETI_COVERAGE_LOG"] = str(self.box / "cov.jsonl")
        self.addCleanup(self._restore)

        self.doc = self.box / "doc.md"
        self.doc.write_text("\n".join(f"line {i}" for i in range(1, 101)),
                            encoding="utf-8")
        self.tr = self.box / "t.jsonl"

    def _restore(self):
        if self.old is None:
            os.environ.pop("FORSETI_COVERAGE_LOG", None)
        else:
            os.environ["FORSETI_COVERAGE_LOG"] = self.old

    def transcript(self, *calls):
        rows = []
        for c in calls:
            rows.append({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": c.get("name", "Read"),
                 "id": "x", "input": c.get("input", {})}]}})
        self.tr.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8")


class TestHarvest(Case):

    def test_it_finds_read_calls(self):
        self.transcript({"input": {"file_path": str(self.doc)}})
        reads = AC.harvest(self.tr)
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0]["path"], str(self.doc))

    def test_it_keeps_offset_and_limit(self):
        self.transcript({"input": {"file_path": str(self.doc),
                                   "offset": 20, "limit": 30}})
        r = AC.harvest(self.tr)[0]
        self.assertEqual((r["offset"], r["limit"]), (20, 30))

    def test_grep_is_not_counted(self):
        """grep 命中三行不等於讀了那三行的脈絡。

        把它算成涵蓋,會讓一個只掃過關鍵字的人看起來讀過了。
        """
        self.transcript({"name": "Grep",
                         "input": {"path": str(self.doc), "pattern": "x"}})
        self.assertEqual(AC.harvest(self.tr), [])

    def test_a_read_without_a_path_is_ignored(self):
        self.transcript({"input": {"offset": 1}})
        self.assertEqual(AC.harvest(self.tr), [])


class TestApply(Case):

    def test_a_ranged_read_covers_that_range(self):
        self.transcript({"input": {"file_path": str(self.doc),
                                   "offset": 10, "limit": 20}})
        AC.apply(AC.harvest(self.tr))
        log = C.CoverageLog()
        rec = log.merged_for(str(self.doc))
        self.assertEqual(rec.covered, [(10, 29)])
        self.assertEqual(rec.level(), "SAMPLED")

    def test_a_read_without_range_covers_everything(self):
        self.transcript({"input": {"file_path": str(self.doc)}})
        AC.apply(AC.harvest(self.tr))
        rec = C.CoverageLog().merged_for(str(self.doc))
        self.assertEqual(rec.level(), "FULL_READ")

    def test_two_partial_reads_merge(self):
        """分段讀完的檔案合起來算讀完。"""
        self.transcript(
            {"input": {"file_path": str(self.doc), "offset": 1, "limit": 50}},
            {"input": {"file_path": str(self.doc), "offset": 51, "limit": 50}})
        AC.apply(AC.harvest(self.tr))
        self.assertEqual(C.CoverageLog().merged_for(str(self.doc)).level(),
                         "FULL_READ")

    def test_a_missing_file_is_counted_not_crashed(self):
        self.transcript({"input": {"file_path": "/nope/nope.md"}})
        r = AC.apply(AC.harvest(self.tr))
        self.assertEqual(r["missing"], 1)
        self.assertEqual(r["added"], 0)

    def test_duplicate_reads_are_not_written_twice(self):
        self.transcript(
            {"input": {"file_path": str(self.doc), "offset": 1, "limit": 10}},
            {"input": {"file_path": str(self.doc), "offset": 1, "limit": 10}})
        r = AC.apply(AC.harvest(self.tr))
        self.assertEqual(r["added"], 1)

    def test_dry_run_writes_nothing(self):
        self.transcript({"input": {"file_path": str(self.doc)}})
        r = AC.apply(AC.harvest(self.tr), dry_run=True)
        self.assertEqual(r["added"], 1)
        self.assertTrue(r["dry_run"])
        self.assertIsNone(C.CoverageLog().merged_for(str(self.doc)))


class TestItAdmitsItOverestimates(Case):
    """這一組守的是那個已知偏誤有被誠實標出來。"""

    def test_every_auto_record_is_marked_inferred(self):
        """自動推出來的涵蓋率,不該跟親眼讀完的算同一級。"""
        self.transcript({"input": {"file_path": str(self.doc)}})
        AC.apply(AC.harvest(self.tr))
        rows = C.CoverageLog().read_all()
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(r.get("session"), "auto")
            self.assertIn("inferred", r.get("note", ""))

    def test_the_overestimate_is_documented_in_the_source(self):
        """偏誤方向要寫在原始碼裡,不是只寫在別的文件。

        一個只在文件裡承認的偏誤,改程式的人看不到。
        """
        src = (REPO / "tools" / "auto-coverage.py").read_text(encoding="utf-8")
        self.assertIn("高估", src)
        self.assertIn("截斷", src)

    def test_grep_exclusion_is_documented(self):
        src = (REPO / "tools" / "auto-coverage.py").read_text(encoding="utf-8")
        self.assertIn("Grep", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
