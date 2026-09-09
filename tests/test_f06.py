#!/usr/bin/env python3
"""F06-EXC-001 的 conformance tests。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F06-EXC-001  sha256 e2c0dfb0f965  §6 有五條 CT

這一組測的是 2026-09-09 那一場 HumanContinueBurden = 9 的機制修正。
九次都是同一個形狀：做完一件事、寫一份完整的報告、停下來等人說繼續。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import continuity as C  # noqa: E402
import ledger as L  # noqa: E402


class F06Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)
        self.t = self.led.accept("任務", [
            L.Step(f"s{i}", f"第 {i} 步", expected_outputs=[f"o{i}.txt"],
                   verifier=[f"file:o{i}.txt"],
                   dependencies=[f"s{i-1}"] if i > 1 else [])
            for i in (1, 2, 3)
        ])
        self.led.transition(self.t, "RUNNING", "開始")

    def tearDown(self):
        self.led.close()

    def produce(self, n):
        (self.tmp / f"o{n}.txt").write_text(f"out {n}", encoding="utf-8")


class TestF06(F06Case):

    def test_CT_F06_01_not_done_plus_authorized_next_step_auto_continues(self):
        """說「還沒做完」而下一步已授權 → 自己繼續。"""
        self.led.auto_dispatch(self.t, "w")
        self.produce(1)
        self.led.verify_step(self.led.sid(self.t, "s1"))

        self.led.report(self.t, "第一步好了，還沒做完")

        nxt = self.led.auto_dispatch(self.t, "w")
        self.assertIsNotNone(nxt, "還沒做完就該自己往下走")
        self.assertEqual(nxt["local_id"], "s2")
        self.assertEqual(self.led.continuity(self.t)["human_continue_burden"], 0)

    def test_CT_F06_02_partial_status_report_does_not_stop_workflow(self):
        """六成進度的狀態報告 → 流程照常。"""
        self.led.auto_dispatch(self.t, "w")
        self.led.report(self.t, "大約 60%，目前處理到第二個模組")
        self.assertEqual(self.led.state_of(self.t), "RUNNING")
        self.assertFalse(L.is_terminal(self.led.state_of(self.t)))
        self.assertIsNotNone(self.led.next_step(self.t))

    def test_CT_F06_03_i_explained_it_is_a_violation(self):
        """「我解釋過了」在已接受的任務上是違規。

        F06 §4 明文：「Turn ended」and「I explained it」are invalid
        stop reasons。這是規格直接說的，不是我加嚴。
        """
        for bad in ("I explained it", "解釋完了", "這一輪結束", "turn ended",
                    "等你說繼續", "做完了"):
            with self.assertRaises(C.ContinuityViolation, msg=bad):
                self.led.stop(self.t, bad)

        kinds = [e["kind"] for e in self.led.events_of(self.t)]
        self.assertEqual(kinds.count("EXECUTION_CONTINUITY_VIOLATION"), 6,
                         "每一次違規的嘗試都要留在帳本裡，失敗不代表沒發生過")

    def test_CT_F06_04_real_ambiguity_makes_needs_human_valid(self):
        """真的有歧義時，NEEDS_HUMAN 是合法的停止。

        重點是「真的」：這個理由必須講得出要誰決定什麼，
        不然它跟「我先停一下」沒有差別。
        """
        with self.assertRaises(C.ContinuityViolation):
            self.led.stop(self.t, "NEEDS_HUMAN_DECISION")  # 沒講要決定什麼

        r = self.led.stop(self.t, "NEEDS_HUMAN_DECISION",
                          "北極星要不要改成雙向版本，只有 owner 能決定")
        self.assertEqual(r, "NEEDS_HUMAN_DECISION")
        self.assertIn("EXECUTION_STOP", [e["kind"] for e in self.led.events_of(self.t)])

    def test_CT_F06_05_task_survives_turn_boundaries(self):
        """任務跨越回合邊界存活。

        回合邊界在這裡模擬成:把整個 Ledger 物件丟掉重開。
        那正是一輪對話結束對模型做的事。
        """
        self.led.auto_dispatch(self.t, "w")
        self.produce(1)
        self.led.verify_step(self.led.sid(self.t, "s1"))

        for _ in range(3):  # 三個回合邊界
            self.led.close()
            self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)

        self.assertEqual(self.led.state_of(self.t), "RUNNING")
        self.assertEqual(self.led.next_step(self.t)["local_id"], "s2")
        self.assertEqual(self.led.continuity(self.t)["human_continue_burden"], 0)


class TestStopTaxonomy(unittest.TestCase):
    """F06 §4。八種合法理由，其他一律違規。"""

    def test_all_eight_are_accepted(self):
        self.assertEqual(len(C.STOP_REASONS), 8)
        for r in C.STOP_REASONS:
            self.assertEqual(C.classify_stop(r, "有講理由"), r)

    def test_unknown_stop_is_legal_because_honesty_beats_invention(self):
        """UNKNOWN_STOP 是合法的。

        「不知道為什麼停了」是誠實的答案,比硬掰一個好。它本身是告警,
        不是正常出口,但誠實的告警勝過漂亮的謊。
        """
        self.assertEqual(C.classify_stop("UNKNOWN_STOP"), "UNKNOWN_STOP")

    def test_error_message_names_the_rule_you_broke(self):
        """錯誤訊息要講出踩到哪一條，不是只說不合法。"""
        with self.assertRaises(C.ContinuityViolation) as cm:
            C.classify_stop("我解釋過了")
        self.assertIn("解釋不是交付", str(cm.exception))


class TestMetrics(F06Case):
    """F06 §5 的兩個指標。"""

    def test_score_denominator_never_divides_by_zero(self):
        """沒有應該繼續的場合時，分數是 0 不是滿分。

        規格寫 max(ExpectedContinuation, 1)。這個選擇是對的:
        「沒機會證明自己會繼續」不該算滿分,預設不信任比預設信任安全。
        """
        self.assertEqual(C.continuity_score(0, 0), 0.0)
        self.assertEqual(C.continuity_score(3, 3), 1.0)

    def test_burden_is_counted_from_events_not_impressions(self):
        """burden 從事件算，不是從印象算。"""
        m = self.led.continuity(self.t)
        self.assertEqual(m["human_continue_burden"], 0)
        self.led.human_continue(self.t, "繼續做 F03")
        self.led.human_continue(self.t, "繼續")
        m = self.led.continuity(self.t)
        self.assertEqual(m["human_continue_burden"], 2)
        self.assertIn("可接受", m["burden_verdict"])

    def test_high_burden_says_the_user_was_used_as_a_heartbeat(self):
        """2026-09-09 那一場是 9 次。這條測的是那個判定講不講得出來。"""
        for i in range(9):
            self.led.human_continue(self.t, f"繼續 {i}")
        self.assertIn("心跳器", self.led.continuity(self.t)["burden_verdict"])

    def test_auto_dispatch_counts_toward_the_score(self):
        self.led.auto_dispatch(self.t, "w")
        self.produce(1)
        self.led.verify_step(self.led.sid(self.t, "s1"))
        self.led.report(self.t, "第一步好了")
        self.led.auto_dispatch(self.t, "w")
        m = self.led.continuity(self.t)
        # 派了兩次,第一次是起步不算接續,所以接上的是 1 次。
        self.assertGreaterEqual(m["auto_continued"], 1)
        self.assertGreater(m["score"], 0)
        self.assertLessEqual(m["score"], 1.0, "分數是比例，不該超過 1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
