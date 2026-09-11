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


class TestSilence(unittest.TestCase):
    """她的沉默（build-plan.md:363）。

    **這一組的核心是一件事：MOVED_ON 不等於同意。**

    沉默有兩種完全不同的意思 —— 她看過覺得沒問題，或者她根本沒看到。
    兩者在 transcript 裡長得一模一樣。合成一類的代價不對稱：
    一個她漏看的錯誤會被記成她同意過，而「owner 同意過」是這個系統裡
    最強的證據等級（E4 的 owner-confirmed）。
    """

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())

    def transcript(self, turns) -> Path:
        """turns 是 (type, text) 的序列。"""
        import json
        p = self.tmp / "t.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for kind, text in turns:
                if kind == "assistant":
                    rec = {"type": "assistant",
                           "message": {"content": [{"type": "text", "text": text}]}}
                else:
                    rec = {"type": "user", "message": {"content": text}}
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return p

    def test_explicit_ok_is_the_only_thing_that_counts_as_consent(self):
        p = self.transcript([("assistant", "做完了"), ("user", "好")])
        self.assertEqual(O.silence_map(p)[0].kind, "EXPLICIT_OK")

    def test_moving_on_is_not_consent(self):
        """她講了下一件事，那不是同意。"""
        p = self.transcript([("assistant", "做完了"), ("user", "幫我改 a.py")])
        s = O.silence_map(p)[0]
        self.assertEqual(s.kind, "MOVED_ON")
        self.assertNotEqual(s.kind, "EXPLICIT_OK")

    def test_the_summary_refuses_to_merge_moved_on_into_agreement(self):
        p = self.transcript([("assistant", "做完了"), ("user", "幫我改 a.py")])
        note = O.silence_summary(O.silence_map(p))["note"]
        self.assertIn("MOVED_ON 不等於同意", note)
        self.assertIn("她自己說出口", note)

    def test_responding_is_not_silence(self):
        p = self.transcript([("assistant", "做完了"), ("user", "你忘了加測試")])
        self.assertEqual(O.silence_map(p)[0].kind, "RESPONDED")

    def test_nothing_after_is_unobserved_not_agreement(self):
        """後面沒有她的訊息，那是「還沒看到」不是「沒有異議」。"""
        p = self.transcript([("user", "做這個"), ("assistant", "做完了")])
        self.assertEqual(O.silence_map(p)[0].kind, "UNOBSERVED")

    def test_one_round_not_one_block(self):
        """一輪回應有很多塊，她回應的是整輪。

        2026-09-11 實測：一份 transcript 有 713 段 AI 文字但只有
        105 則 owner 訊息。逐塊配對的話 MOVED_ON 會是 89%，
        而那個數字量的是「一輪有幾塊」，不是「她跳過了多少」。
        """
        p = self.transcript([
            ("user", "做這個"),
            ("assistant", "我先查一下"),
            ("assistant", "查到了"),
            ("assistant", "做完了，報告如下"),
            ("user", "好"),
        ])
        items = O.silence_map(p)
        self.assertEqual(len(items), 1, "三塊是一輪")
        self.assertIn("報告", items[0].ai_excerpt)

    def test_risky_needs_both_a_flag_and_silence(self):
        """有問題而且她跳過，兩個條件都要。

        只有其中一個都不值得特別拿出來問。
        """
        p = self.transcript([("assistant", "做完了"), ("user", "幫我改 a.py")])
        clean = O.silence_map(p)[0]
        self.assertFalse(clean.risky, "沒有被標記的就不算")

        flagged = O.silence_map(p, flagged_lines={1})[0]
        self.assertTrue(flagged.risky)

        p2 = self.transcript([("assistant", "做完了"), ("user", "好")])
        answered = O.silence_map(p2, flagged_lines={1})[0]
        self.assertFalse(answered.risky, "她明確說了好，那就不是沉默")

    def test_four_states_with_meanings(self):
        self.assertEqual(len(O.SILENCE), 4)
        self.assertEqual(set(O.SILENCE_MEANING), set(O.SILENCE))


class TestFullCorpusCalibration(unittest.TestCase):
    """2026-09-11 全量跑 30 個 session、4,139 則訊息之後補的。

    每一條都附當時抓到的實際句子。**沒有出處的規則不該存在** ——
    這張表是結構規則不是語意理解,漏掉的會落到 UNKNOWN(無害),
    誤判的要靠實測發現再補,不預先想像。
    """

    def test_full_width_ok_is_an_acknowledgement(self):
        """「ＯＫ」跟「OK」是同一個字,差別只在輸入法切到哪一邊。

        全量跑抓到的:UNKNOWN 裡有全形的 ＯＫ,而半形的在清單裡好好的。
        """
        m = O.classify("ＯＫ")
        self.assertEqual(m.kind, "ACKNOWLEDGEMENT")

    def test_normalisation_keeps_the_original_text(self):
        """正規化只用於比對。存進去的要是她真正打出來的字。

        證據不能被自己的前處理改寫。
        """
        m = O.classify("ＯＫ")
        self.assertEqual(m.text, "ＯＫ")

    def test_a_preventive_instruction_is_not_a_correction(self):
        """「邏輯要清楚不要搞錯」是在交代要求,不是在指出失誤。

        判準是位置不是語意:錯字詞緊接在否定祈使後面。
        """
        m = O.classify("將這幾頁做個總結，邏輯要清楚不要搞錯")
        self.assertNotEqual(m.kind, "CORRECTION")

    def test_a_real_correction_still_lands(self):
        """放寬不能把真的糾正一起殺掉。"""
        m = O.classify("那台是公司同事的機器，你搞錯了 IP")
        self.assertEqual(m.kind, "CORRECTION")

    def test_do_it_again_is_not_a_correction(self):
        """「再做一次同步吧」是新要求。

        單獨一句分不出「重來(因為你做壞了)」還是「再執行一次
        (因為時間到了)」,要分辨得知道上一輪發生什麼,
        而這個分類器是無狀態的。跟「先做」被拿掉是同一個理由。
        """
        m = O.classify("再做一次同步吧，快要到終點了")
        self.assertNotEqual(m.kind, "CORRECTION")


class TestSummaryDeclaresItsOwnUncertainty(unittest.TestCase):
    """統計要講出自己有多少是無知。

    全量跑量到:MOVED_ON 2,638 輪裡有 2,241 輪(85%)底下是 UNKNOWN。
    這張地圖現在主要在量「分類器分不出她在說什麼」,不是「她跳過了」。
    """

    def test_the_summary_says_how_much_is_ignorance(self):
        items = [
            O.Silence("MOVED_ON", 1, 2, "UNKNOWN"),
            O.Silence("MOVED_ON", 3, 4, "UNKNOWN"),
            O.Silence("MOVED_ON", 5, 6, "NEW_REQUEST"),
            O.Silence("EXPLICIT_OK", 7, 8, "ACKNOWLEDGEMENT"),
        ]
        out = O.silence_summary(items)
        self.assertEqual(out["moved_on_from_unknown"], 2)
        self.assertAlmostEqual(out["moved_on_unknown_share"], 0.667, places=2)
        self.assertIn("當線索看不是當結論", out["caveat"])

    def test_no_moved_on_means_no_division_by_zero(self):
        out = O.silence_summary([O.Silence("EXPLICIT_OK", 1, 2, "ACKNOWLEDGEMENT")])
        self.assertEqual(out["moved_on_unknown_share"], 0.0)



if __name__ == "__main__":
    unittest.main(verbosity=2)
