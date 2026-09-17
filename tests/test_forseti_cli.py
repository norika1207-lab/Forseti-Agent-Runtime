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

        2026-09-10 這條測試自己壞過一次，值得記：它原本斷言
        `rep.gates` 非空，而那天所有補讀門檻都達標了，空清單讓它失敗。
        **測試把「當時的資料狀態」寫成了「結構要求」。** 兩張表分不分得開
        是結構問題，跟現在有幾項未達標無關，所以改用自備 fixture 驗結構，
        真實檔案只驗兩邊沒有互相污染。
        """
        two_tables = (
            "## 源頭文件\n\n"
            "| 文件 | 字數 | Level | 讀取狀態 | 什麼時候必須補完 |\n"
            "|---|---|---|---|---|\n"
            "| 甲文件 | 100 | 2 | 約兩成 | 動階段 9 之前 |\n"
            "| 乙文件 | 200 | 5 | 逐段完整 | — |\n\n"
            "## 各階段動工前的補讀門檻\n\n"
            "| 要動哪一階 | 必須先讀完 | 現況 |\n"
            "|---|---|---|\n"
            "| 階段 9 甲線 | 甲文件 | **未達標** |\n"
            "| 階段 8 乙線 | 乙文件 | 已達標 |\n"
        )
        unread = forseti.extract_unread(two_tables)
        gates = forseti.extract_gates(two_tables)

        self.assertEqual(len(unread), 1, "只有 level 2 那份算未讀")
        self.assertIn("甲文件", unread[0])
        self.assertEqual(len(gates), 1, "只有未達標那階算門檻")
        self.assertIn("階段 9", gates[0])
        self.assertFalse(unread[0].startswith("階段"), "文件表混進了階段")
        self.assertTrue(gates[0].startswith("階段"), "門檻表混進了文件")

        # 真實檔案只驗「兩邊沒有互相污染」，不驗數量 ——
        # 數量會隨補讀進度變動，那是進度不是結構。
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

    def _sandbox_report(self):
        """把閘門指到一份臨時副本，不要讓測試往真實帳本寫考卷。

        `rep.missing` 仍然是對真 ROOT 算的，所以閘門該早退的時候照樣早退。
        """
        import dataclasses
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        (tmp / ".forseti").mkdir()
        for name in ("NORTH_STAR.md", "DECISION_LEDGER.md", "BLOCKERS.md",
                     "checkpoints.jsonl", "config.json"):
            src = ROOT / ".forseti" / name
            if src.is_file():
                shutil.copy2(src, tmp / ".forseti" / name)
        shutil.copy2(ROOT / "bible.md", tmp / "bible.md")
        return dataclasses.replace(forseti.build_report(ROOT), root=tmp)

    def test_gate_now_actually_grades_answers(self):
        """B-08 解除：閘門會出一份批改得了的考卷。

        先前這條測的是相反的事（「要講出來自己不驗答案」）。
        那句話當時是誠實的，現在它會變成謊話 ——
        `sufficiency.py` 接上之後這個指令真的批改。
        """
        buf = io.StringIO()
        with redirect_stdout(buf):
            forseti.cmd_gate_takeover(self._sandbox_report())
        out = buf.getvalue()
        self.assertIn("考卷", out)
        self.assertIn("gate submit", out)
        self.assertNotIn("不驗證答案", out)

    def test_gate_does_not_reveal_the_answers(self):
        """v5.0 §39 第 2 步：先看到答案再推導，推導出來的就是那個答案。"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            forseti.cmd_gate_takeover(self._sandbox_report())
        out = buf.getvalue()
        # 出題的原文裡這幾段是答案，印出來就等於把答案端到受測者面前。
        self.assertNotIn("環境裡實際是什麼", out)
        self.assertNotIn("grep 找答案，文件", out)

    def test_gate_says_which_half_it_cannot_verify(self):
        """六題開放題系統驗不了，要講清楚，不要讓人以為全部都在把關。"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            forseti.cmd_gate_takeover(self._sandbox_report())
        self.assertIn("系統驗不了", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
