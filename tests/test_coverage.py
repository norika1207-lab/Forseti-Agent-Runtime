#!/usr/bin/env python3
"""段落層級的閱讀涵蓋。守的是「它抓不抓得到 2026-09-11 早上那個錯」。

那天早上的事實：`.forseti/REQUIRED_READING.md` 有 353 行，
第 176 到 223 行是壓縮前寫下的整組模組規格記錄。
當天的 session 打開了那個檔案，讀了最底下那張表，沒有往上讀，
然後在七條回報裡說「補讀門檻全達標」。

`tools/reading-conformance.py` 的 hash 那一層抓不到這個 ——
只讀最後 20 行算出來的檔案 hash，跟讀完整份的一模一樣。

所以這一組測試的第一條，就是拿那個真實情境去測。
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import coverage as C  # noqa: E402


class TestTheRealIncident(unittest.TestCase):
    """2026-09-11 早上那個錯，現在抓得到嗎。"""

    def test_reading_only_the_last_table_is_sampled_not_full(self):
        rec = C.ReadRecord("REQUIRED_READING.md", 353, "abc123")
        rec.add(226, 353)
        self.assertEqual(rec.level(), "SAMPLED")
        self.assertFalse(rec.conformant())

    def test_it_names_the_exact_lines_that_were_missed(self):
        """「第 176 到 223 行你沒讀進來」——這句話是這整個模組存在的理由。

        hash 那一層只說得出「檔案沒變」。
        """
        rec = C.ReadRecord("REQUIRED_READING.md", 353, "abc123")
        rec.add(226, 353)
        self.assertEqual(rec.gaps(), [(1, 225)])
        missed = rec.gaps()[0]
        self.assertLessEqual(missed[0], 176)
        self.assertGreaterEqual(missed[1], 223)


class TestLevels(unittest.TestCase):

    def _rec(self, total=100, spans=()):
        r = C.ReadRecord("x.md", total, "h")
        for lo, hi in spans:
            r.add(lo, hi)
        return r

    def test_nothing_read_is_none(self):
        self.assertEqual(self._rec().level(), "NONE")

    def test_everything_read_is_full(self):
        self.assertEqual(self._rec(spans=[(1, 100)]).level(), "FULL_READ")

    def test_two_halves_add_up_to_full(self):
        """分兩次讀完，合起來算讀完。

        區間相鄰也要併，不然逐段讀完的檔案會因為破碎而看起來有缺口。
        """
        r = self._rec(spans=[(1, 50), (51, 100)])
        self.assertEqual(r.level(), "FULL_READ")
        self.assertEqual(r.gaps(), [])

    def test_a_few_opening_lines_is_title_only(self):
        self.assertEqual(self._rec(spans=[(1, 4)]).level(), "TITLE_ONLY")

    def test_header_lines_only_is_header_scan_not_sampled(self):
        """掃標題跟零散抽樣涵蓋率可能一樣，但意義差很多。

        掃標題的人知道有哪些節，零散抽樣的人連這個都不知道。
        """
        heads = {10, 20, 30, 40, 50, 60}
        r = C.ReadRecord("x.md", 100, "h")
        for n in heads:
            r.add(n, n)
        self.assertEqual(r.level(header_lines=heads), "HEADER_SCAN")

    def test_high_coverage_with_a_hole_is_structural(self):
        r = self._rec(spans=[(1, 90)])
        self.assertEqual(r.level(), "STRUCTURAL")
        self.assertFalse(r.conformant())

    def test_this_module_never_issues_the_top_level(self):
        """`VERIFIED_UNDERSTANDING` 要靠抽問，不是靠行號。

        把兩者混在一起，會讓一個掃過全文的人拿到跟讀懂的人一樣的等級。
        """
        self.assertEqual(C.MAX_MECHANICAL, "FULL_READ")
        r = self._rec(spans=[(1, 100)])
        self.assertNotEqual(r.level(), "VERIFIED_UNDERSTANDING")


class TestItRefusesToLie(unittest.TestCase):

    def test_claiming_lines_that_do_not_exist_is_refused(self):
        """宣稱讀了不存在的行，比少讀更嚴重。"""
        with self.assertRaises(C.CoverageError):
            C.ReadRecord("x.md", 10, "h", spans=[(1, 50)])
        r = C.ReadRecord("x.md", 10, "h")
        with self.assertRaises(C.CoverageError):
            r.add(5, 99)

    def test_bad_spans_are_refused(self):
        r = C.ReadRecord("x.md", 100, "h")
        for lo, hi in ((0, 5), (10, 3), (-1, 2)):
            with self.assertRaises(C.CoverageError):
                r.add(lo, hi)

    def test_staleness_is_unknown_when_it_cannot_be_measured(self):
        """量不到回 None，不回 False。跟 claims.py 的三態同一個原則。"""
        self.assertIsNone(C.ReadRecord("x.md", 10, "").is_stale_against())
        self.assertIsNone(
            C.ReadRecord("/nope/nope.md", 10, "abc").is_stale_against())

    def test_thresholds_declare_they_are_uncalibrated(self):
        """未校準的常數要自己說。這條由設計規則 §3.3 管。"""
        self.assertTrue(C.THRESHOLDS_UNCALIBRATED)
        r = C.ReadRecord("x.md", 10, "h")
        self.assertTrue(r.to_dict()["thresholds_uncalibrated"])


class TestLog(unittest.TestCase):

    def setUp(self):
        self.box = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.box, ignore_errors=True))
        self.old = os.environ.get("FORSETI_COVERAGE_LOG")
        os.environ["FORSETI_COVERAGE_LOG"] = str(self.box / "cov.jsonl")
        self.addCleanup(self._restore)
        self.log = C.CoverageLog()

    def _restore(self):
        if self.old is None:
            os.environ.pop("FORSETI_COVERAGE_LOG", None)
        else:
            os.environ["FORSETI_COVERAGE_LOG"] = self.old

    def test_two_partial_reads_merge_into_full(self):
        """先讀前半再讀後半，人確實讀完了。"""
        for lo, hi in ((1, 60), (61, 120)):
            r = C.ReadRecord("a.md", 120, "same")
            r.add(lo, hi)
            self.log.append(r)
        m = self.log.merged_for("a.md")
        self.assertEqual(m.level(), "FULL_READ")

    def test_records_from_a_different_file_version_are_not_merged(self):
        """檔案改過之後的記錄不能跟改之前的加起來。

        不然一份被大改過的檔案，會因為前後各半份的讀取而看起來讀完了。
        """
        old = C.ReadRecord("a.md", 120, "OLDHASH")
        old.add(1, 60)
        self.log.append(old)
        new = C.ReadRecord("a.md", 120, "NEWHASH")
        new.add(61, 120)
        self.log.append(new)
        m = self.log.merged_for("a.md")
        self.assertEqual(m.content_hash, "NEWHASH")
        self.assertNotEqual(m.level(), "FULL_READ")
        self.assertEqual(m.gaps(), [(1, 60)])

    def test_no_record_returns_none_not_zero(self):
        """沒有記錄不等於沒讀，也不等於讀了。回 None。

        回 0% 會冤枉一個真的讀過但沒記錄的人。
        """
        self.assertIsNone(self.log.merged_for("never-touched.md"))
        self.assertIsNone(self.log.best_for("never-touched.md"))

    def test_a_broken_line_does_not_kill_the_whole_log(self):
        r = C.ReadRecord("a.md", 10, "h")
        r.add(1, 10)
        self.log.append(r)
        with self.log.path.open("a", encoding="utf-8") as fh:
            fh.write("{ 這行壞掉\n")
        self.assertEqual(len(self.log.read_all()), 1)

    def test_the_log_is_append_only_in_practice(self):
        """寫兩筆就有兩筆，前一筆不會被蓋掉。

        「我讀到哪裡」不能是一個事後可以調整的數字。
        """
        for i in (1, 2):
            r = C.ReadRecord(f"{i}.md", 10, "h")
            r.add(1, 10)
            self.log.append(r)
        self.assertEqual(len(self.log.read_all()), 2)


class TestFullReadHelper(unittest.TestCase):

    def test_from_full_read_covers_everything(self):
        box = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(box, ignore_errors=True))
        p = box / "x.md"
        p.write_text("\n".join(f"line {i}" for i in range(1, 31)),
                     encoding="utf-8")
        rec = C.from_full_read(p)
        self.assertEqual(rec.total_lines, 30)
        self.assertEqual(rec.level(), "FULL_READ")
        self.assertTrue(rec.conformant())
        self.assertEqual(rec.content_hash,
                         hashlib.sha256(p.read_bytes()).hexdigest()[:12])

    def test_an_empty_file_is_none_not_full(self):
        """空檔案讀不出東西。回 NONE 而不是「讀完了」。"""
        box = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(box, ignore_errors=True))
        p = box / "empty.md"
        p.write_text("", encoding="utf-8")
        self.assertEqual(C.from_full_read(p).level(), "NONE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
