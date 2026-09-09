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

    def test_fully_read_documents_are_not_listed_as_unread(self):
        """level 5 逐段完整讀過的，不該出現在未讀清單。

        2026-09-09 這裡壞過：REQUIRED_READING 的表加了 Level 欄之後，
        解析器還在抓第三欄，於是九份全部被列成沒讀完，包括讀完的那幾份，
        而且顯示成一個孤零零的數字。當時 16 條測試全過，因為它們檢查
        表格結構不檢查語意。這條補的就是語意。
        """
        joined = " ".join(self.rep.unread)
        self.assertNotIn("Formal Specification", joined)
        self.assertNotIn("龍蝦", joined)
        for u in self.rep.unread:
            self.assertRegex(u, r"level [0-4]", f"未讀清單裡出現非 0-4 級：{u}")

    def test_platform_vision_docs_are_not_mixed_into_source_docs(self):
        """平台願景那五份是另一張表，不該混進源頭文件的未讀清單。

        它們是願景不是現在這條線的規格，混在一起會讓 doctor 報出
        「還有十四份沒讀完」這種嚇人又沒有用的數字。
        """
        joined = " ".join(self.rep.unread)
        for name in ("Vol1", "Vol2", "Vol3", "Vol4", "Design Evolution"):
            self.assertNotIn(name, joined)

    def test_resolved_blockers_are_not_counted(self):
        """已解除的不算阻塞。

        BLOCKERS.md 開頭自己寫著「擋不住任何東西的不叫阻塞」。
        doctor 報「9 項」而其中一項已經解除的話，那個數字是假的，
        而假的數字比沒有數字更糟。
        """
        joined = " ".join(self.rep.blockers)
        self.assertNotIn("B-02", joined, "B-02 已於 2026-09-09 解除，不該算進阻塞數")
        text = (ROOT / ".forseti" / "BLOCKERS.md").read_text(encoding="utf-8")
        self.assertIn("# 已解除", text, "解除的要留在檔案裡，只是不算數")
        self.assertIn("B-02", text.split("# 已解除")[1], "B-02 的全文要保留")

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
