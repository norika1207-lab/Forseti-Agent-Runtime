#!/usr/bin/env python3
"""人的訊息分類。階段 3 的第二項交付。

出口條件（`docs/build-plan.md:367`）裡最難的一條：

    「改變想法」與「糾正」分得開。

**那一條單獨開一個 class**，因為它是這個模組存在的理由。
把改變想法算成糾正，等於把她行使擁有者的權力記成 AI 的失誤；
反過來 AI 就永遠學不到它漏了什麼。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import owner as O  # noqa: E402


class TestMindChangeVsCorrection(unittest.TestCase):
    """出口條件的核心：這兩類分得開。"""

    CORRECTIONS = (
        "你沒有跑測試",
        "你沒跑測試",
        "你忘了加測試",
        "我說過要先讀規格",
        "不是叫你直接改 code",
        "這個重來",
        "你又搞錯了",
    )

    MIND_CHANGES = (
        "不用跑測試了",
        "算了，先跳過那個",
        "改成用 SQLite",
        "我改變主意，先做階段 3",
        "先不要動作，我們先對話",
    )

    # 【這一組是實測推翻我自己的假設，2026-09-11】
    #
    # 我原本把「先處理採集那個缺口」寫進上面那張表當 MIND_CHANGE。
    # 拿真實 transcript 跑之後才看清楚：那句話是採納建議加指定順序，
    # 也就是**新要求**，不是推翻原本的方向。
    #
    # 「先做 X」單獨看判不出是哪一種 —— 要分辨得知道「原本要做的是什麼」，
    # 而這個分類器是無狀態的。所以那條 pattern 已經從 MIND_CHANGE 拿掉。
    NOT_MIND_CHANGE = (
        "先處理採集那個缺口",
        "先做 B-10",
        "優先做階段 2",
    )

    def test_specifying_the_next_step_is_a_new_request(self):
        for t in self.NOT_MIND_CHANGE:
            with self.subTest(t):
                self.assertNotEqual(O.classify(t).kind, "MIND_CHANGE")

    def test_corrections_point_at_the_ai(self):
        for t in self.CORRECTIONS:
            with self.subTest(t):
                self.assertEqual(O.classify(t).kind, "CORRECTION")

    def test_mind_changes_point_at_the_goal(self):
        for t in self.MIND_CHANGES:
            with self.subTest(t):
                self.assertEqual(O.classify(t).kind, "MIND_CHANGE")

    def test_a_sentence_with_both_counts_as_correction(self):
        """兩者都有的句子算糾正。

        「你沒跑測試，算了不用跑了」的重點是前半 —— 她先指出了
        AI 漏掉的東西。算成改變想法會讓那個漏失消失。
        """
        r = O.classify("你沒跑測試，算了不用跑了")
        self.assertEqual(r.kind, "CORRECTION")

    def test_permission_is_not_blame(self):
        """「你沒有必要做那個」是允許，不是指責。

        這一條是 2026-09-11 連續踩兩次的地方：
        第一次排除清單只放進一個分支，第二次被 regex 回溯繞過。
        """
        for t in ("你沒有必要做那個", "你沒關係", "你沒想到的地方"):
            with self.subTest(t):
                self.assertNotEqual(O.classify(t).kind, "CORRECTION")


class TestPriorityOrder(unittest.TestCase):
    """優先序是設計的一部分，不是實作細節。"""

    def test_clarification_beats_mind_change(self):
        """「我的意思是」本身就在說「我沒有改變，是你誤解了」。

        2026-09-11 實測撞到：這句話被「先做」搶成了改變想法，
        而那等於把一次澄清算成一次方向變更。
        """
        r = O.classify("我的意思是要先做 B")
        self.assertEqual(r.kind, "CLARIFICATION")

    def test_a_long_message_starting_with_yes_is_not_an_acknowledgement(self):
        """「好，那你把 X 改成 Y」的重點在後半。"""
        r = O.classify("好，那你把 event_ledger 改成寫在 repo 裡")
        self.assertNotEqual(r.kind, "ACKNOWLEDGEMENT")

    def test_short_positive_replies_are_acknowledgements(self):
        for t in ("好", "對", "可以", "繼續", "OK", "收到", "沒錯"):
            with self.subTest(t):
                self.assertEqual(O.classify(t).kind, "ACKNOWLEDGEMENT")


class TestNoGuessing(unittest.TestCase):
    """bible Q-07：不確定的時候不定罪。"""

    def test_unclassifiable_goes_to_unknown(self):
        for t in ("天氣不錯", "嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯嗯"):
            with self.subTest(t):
                self.assertEqual(O.classify(t).kind, "UNKNOWN")

    def test_empty_is_unknown(self):
        for t in ("", "   ", None):
            self.assertEqual(O.classify(t).kind, "UNKNOWN")

    def test_unknown_says_why_it_matters(self):
        r = O.classify("天氣不錯")
        self.assertIn("猜錯", r.why)

    def test_every_result_can_explain_itself(self):
        """一個說不出理由的分類沒辦法被反駁。"""
        for t in ("你忘了", "算了", "好", "幫我改 a.py", "天氣不錯"):
            self.assertTrue(O.classify(t).why.strip(), t)

    def test_results_are_frozen(self):
        r = O.classify("好")
        with self.assertRaises(Exception):
            r.kind = "CORRECTION"


class TestKindsAreClosed(unittest.TestCase):

    def test_six_kinds_with_meanings(self):
        self.assertEqual(len(O.KINDS), 6)
        self.assertEqual(set(O.KIND_MEANING), set(O.KINDS))

    def test_illegal_kind_is_refused(self):
        with self.assertRaises(ValueError):
            O.OwnerMessage("差不多是糾正", "理由")



class TestOwnerGoalChangeEvent(unittest.TestCase):
    """build-plan.md:360 的 OWNER_GOAL_CHANGE 事件。"""

    def test_mind_change_becomes_owner_goal_change(self):
        ev = O.to_event(O.classify("改成用 SQLite"), session_id="s1")
        self.assertIsNotNone(ev)
        self.assertEqual(ev[1].type, "OWNER_GOAL_CHANGE")
        self.assertEqual(ev[1].category, "Cognitive")

    def test_correction_maps_to_the_spec_type(self):
        ev = O.to_event(O.classify("你忘了加測試"))
        self.assertEqual(ev[1].type, "CORRECTION")

    def test_acknowledgement_is_not_recorded(self):
        """「好」不是一個發生的事。

        記它只會讓帳本充滿雜訊，而雜訊會讓真的訊號變得不顯眼。
        """
        for t in ("好", "繼續", "OK"):
            self.assertIsNone(O.to_event(O.classify(t)), t)

    def test_unknown_is_not_recorded(self):
        self.assertIsNone(O.to_event(O.classify("天氣不錯")))

    def test_the_event_keeps_the_original_text(self):
        """raw 裡要留原文。正規化不得摧毀原始證據（v5.0 §6.1）。"""
        text = "算了，先跳過那個"
        raw, norm = O.to_event(O.classify(text))
        self.assertEqual(raw.payload["text"], text)
        self.assertEqual(raw.provider, "owner")

    def test_owner_goal_change_is_marked_as_not_from_the_spec(self):
        """這個 type 是本專案加的，不是 v5.0 §6.2 的。

        混在一起的話，下一個人會以為整張表都有規格背書。
        """
        import event_ledger as E
        self.assertIn("不是 v5.0", E.spec_source("OWNER_GOAL_CHANGE"))
        self.assertEqual(E.spec_source("TOOL_CALL"), "v5.0 §6.2")


class TestGoalChangeGap(unittest.TestCase):
    """她改了幾次方向，北極星換了幾版。"""

    def test_it_asks_a_question_instead_of_taking_an_action(self):
        """這個函式不自動換北極星。

        換北極星是權威行為 —— northstar.Chain.adopt() 強制要求具名的
        authority，就是為了讓「誰決定的」永遠答得出來。
        自動換版的話那個欄位會變成「系統」，就失去意義了。
        """
        import northstar as N
        self.assertFalse(hasattr(O, "auto_adopt"))
        g = O.goal_change_gap(5, 1)
        self.assertTrue(g["needs_review"])
        self.assertIn("在有人確認之前", g["note"])
        # 而真正換版的那條路仍然需要 authority
        with self.assertRaises(N.NorthStarError):
            N.Chain().adopt("新方向", authority="", why="x")

    def test_no_gap_when_versions_keep_up(self):
        g = O.goal_change_gap(2, 3)
        self.assertFalse(g["needs_review"])
        self.assertLessEqual(g["gap"], 0)

    def test_zero_changes_is_not_a_problem(self):
        g = O.goal_change_gap(0, 1)
        self.assertFalse(g["needs_review"])
        self.assertIn("沒有偵測到", g["note"])

    def test_a_single_version_means_zero_bumps(self):
        """第 1 版不算「換過一次」。它是起點。"""
        self.assertEqual(O.goal_change_gap(1, 1)["north_star_bumps"], 0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
