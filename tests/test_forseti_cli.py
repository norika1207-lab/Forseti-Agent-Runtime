#!/usr/bin/env python3
"""forseti CLI 的煙霧測試。

用標準庫的 unittest，不裝 pytest。階段 0 的原則是零依賴，
要 pytest 是階段 1 的事。

這裡測的不是「函式回傳對不對」，是「一個全新的 session 靠這個指令
能不能知道現況」。所以測的是 doctor 的輸出裡有沒有那四件事：
北極星、當前階段、沒讀完的、阻塞。
"""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import forseti  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]


class TestRepoDiscovery(unittest.TestCase):
    def test_finds_root_from_own_location(self):
        """從自己的位置往上找，不依賴 cwd。

        理由跟 hooks/forseti-hook.mjs 的 insideRepo() 一樣：
        cwd 會隨呼叫者變，檔案位置不會。
        """
        found = forseti.find_repo_root(ROOT / "apps" / "forseti-cli")
        self.assertEqual(found, ROOT)

    def test_returns_none_outside_project(self):
        self.assertIsNone(forseti.find_repo_root(Path("/tmp")))


class TestControlFileParsing(unittest.TestCase):
    def setUp(self):
        self.rep = forseti.build_report(ROOT)

    def test_north_star_is_the_real_one(self):
        """北極星不是 goal.json 那句 scope 定義。

        2026-09-08 我把「聚焦完成 Forseti」當成北極星，
        她問「你真的知道我的北極星？？」
        """
        self.assertIsNotNone(self.rep.north_star)
        self.assertIn("可觀測", self.rep.north_star)
        self.assertIn("保姆", self.rep.north_star)
        self.assertNotIn("聚焦完成 Forseti", self.rep.north_star)

    def test_phase_is_readable(self):
        self.assertIsNotNone(self.rep.phase)
        self.assertIn("階段", self.rep.phase)
        self.assertIsNotNone(self.rep.phase_state)

    def test_blockers_say_what_they_block(self):
        """一條阻塞要講清楚它擋住什麼，不然那叫待辦不叫阻塞。"""
        self.assertTrue(self.rep.blockers)
        for b in self.rep.blockers:
            self.assertIn("擋住", b, f"這條沒說擋住什麼：{b}")

    def test_unread_and_gates_are_separate_tables(self):
        """REQUIRED_READING.md 有兩張表，混在一起會把「階段 1」當成一份文件。

        這是第一版真的犯過的錯。
        """
        self.assertTrue(self.rep.unread)
        self.assertTrue(self.rep.gates)
        for u in self.rep.unread:
            self.assertFalse(u.startswith("階段"), f"文件表混進了階段：{u}")
        for g in self.rep.gates:
            self.assertTrue(g.startswith("階段"), f"門檻表混進了文件：{g}")

    def test_control_files_all_present(self):
        missing = [f.what for f in self.rep.missing]
        self.assertEqual(missing, [], f"缺控制檔：{missing}")


class TestDoctorOutput(unittest.TestCase):
    """出口條件的實測：一個全新 session 跑完能不能知道現況。"""

    def setUp(self):
        rep = forseti.build_report(ROOT)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.code = forseti.cmd_doctor(rep)
        self.out = buf.getvalue()

    def test_exit_zero_when_control_files_complete(self):
        self.assertEqual(self.code, 0)

    def test_reports_north_star(self):
        self.assertIn("北極星", self.out)
        self.assertIn("可觀測", self.out)

    def test_reports_current_phase(self):
        self.assertIn("當前階段", self.out)

    def test_reports_unread_documents(self):
        self.assertIn("沒讀完", self.out)

    def test_reports_blockers(self):
        self.assertIn("阻塞", self.out)

    def test_warns_about_goal_json_mismatch(self):
        """goal.json 那句是 scope 不是北極星，兩者不同時要講出來。"""
        self.assertIn("goal.json", self.out)

    def test_says_what_to_read_before_taking_over(self):
        self.assertIn("soul.md", self.out)
        self.assertIn("bible.md", self.out)


class TestTakeoverGate(unittest.TestCase):
    def test_questions_come_from_real_corrections(self):
        """題目必須來自她實際糾正過的地方，編出來的就是校規。"""
        joined = " ".join(q for q, _ in forseti.TAKEOVER_QUESTIONS)
        self.assertIn("北極星", joined)
        self.assertIn("讀完幾份", joined)
        self.assertIn("照妖鏡", joined)

    def test_gate_admits_it_cannot_verify_answers_yet(self):
        """這個版本只列題目不驗答案，要講出來，不要讓人以為它在把關。"""
        rep = forseti.build_report(ROOT)
        buf = io.StringIO()
        with redirect_stdout(buf):
            forseti.cmd_gate_takeover(rep)
        out = buf.getvalue()
        self.assertIn("不驗證答案", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
