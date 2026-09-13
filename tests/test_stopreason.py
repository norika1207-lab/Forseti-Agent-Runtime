#!/usr/bin/env python3
"""停止理由分類法。F06 §4。

這一組守的是一句話：分類法的作用不是記錄停止，
是讓「不該停的停止」現形。

所以測試的重點不在「八個名字都在」，在「不該過的真的不會過」。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]
                       / "apps" / "forseti-cli"))

import stopreason as S  # noqa: E402


class TestTheEightReasons(unittest.TestCase):

    def test_the_list_comes_from_continuity_not_a_second_copy(self):
        """清單只能有一份。

        2026-09-11：這個模組原本自己又定義了一套 STOP_REASONS，
        而 `continuity.py` 早就有了。兩份清單遲早會分歧，
        而分歧的那一天沒有人會發現，因為兩邊各自的測試都會過。
        """
        import continuity as C
        self.assertIs(S.STOP_REASONS, C.STOP_REASONS)

    def test_exactly_the_eight_from_the_spec(self):
        self.assertEqual(len(S.STOP_REASONS), 8)
        self.assertEqual(set(S.STOP_REASONS), set(S.REASON_MEANING))

    def test_an_unlisted_reason_is_refused(self):
        """理由可以隨便取名，等於沒有分類法。

        2026-09-11 更新：措辭來自 `continuity.py`，這裡不再自己定義
        一套清單。斷言改成驗那一句的重點而不是逐字，
        因為逐字斷言會把兩個模組綁死在同一個字串上。
        """
        a = S.classify_stop("我累了")
        self.assertEqual(a.verdict, "INVALID_REASON")
        self.assertIn("F06 §4", a.why)
        self.assertIn("UNKNOWN_STOP", a.why)


class TestTheTwoNamedInvalidOnes(unittest.TestCase):
    """F06 §4 最後一句點名的兩個。"""

    def test_turn_ended_is_not_a_reason(self):
        a = S.classify_stop("turn ended")
        self.assertEqual(a.verdict, "INVALID_REASON")
        self.assertIn("不等於任務結束", a.why)

    def test_i_explained_it_is_not_a_reason(self):
        self.assertEqual(
            S.classify_stop("I explained it").verdict, "INVALID_REASON")

    def test_the_chinese_equivalents_too(self):
        """今天實際說過的話：報告完了、我講完了。"""
        for t in ("回合結束", "我解釋過了", "報告完了", "我講完了"):
            self.assertEqual(S.classify_stop(t).verdict, "INVALID_REASON", t)

    def test_an_empty_reason_is_refused(self):
        self.assertEqual(S.classify_stop("").verdict, "INVALID_REASON")
        self.assertEqual(S.classify_stop("   ").verdict, "INVALID_REASON")


class TestTheThreeGates(unittest.TestCase):
    """F06 §3 的三個放行條件，缺一就是 violation。"""

    def test_having_an_authorized_next_step_makes_stopping_a_violation(self):
        """今天一整晚的形狀：每一輪都有確定的下一步，而我停下來等人開口。"""
        a = S.classify_stop("UNKNOWN_STOP", has_authorized_next_action=True)
        self.assertEqual(a.verdict, "EXECUTION_CONTINUITY_VIOLATION")
        self.assertIn("authorized deterministic next action", a.why)

    def test_claiming_blocked_without_evidence_is_a_violation(self):
        """「我覺得卡住了」跟「卡住這件事有證據」是兩回事。"""
        a = S.classify_stop("BLOCKED_VERIFIED")
        self.assertEqual(a.verdict, "EXECUTION_CONTINUITY_VIOLATION")

    def test_blocked_with_evidence_is_valid(self):
        a = S.classify_stop("BLOCKED_VERIFIED",
                            blocker_evidence="port 5432 refused, 三次")
        self.assertTrue(a.ok)

    def test_claiming_owner_decision_when_none_is_needed_is_a_violation(self):
        """需要 owner「決定」跟需要 owner「催」是兩回事。"""
        a = S.classify_stop("NEEDS_HUMAN_DECISION",
                            needs_owner_decision=False)
        self.assertEqual(a.verdict, "EXECUTION_CONTINUITY_VIOLATION")

    def test_a_real_owner_decision_is_valid(self):
        self.assertTrue(S.classify_stop("NEEDS_HUMAN_DECISION",
                                        needs_owner_decision=True).ok)


class TestThreeReasonsSurviveAnAuthorizedNextStep(unittest.TestCase):
    """有下一步也該停的三種。

    政策邊界、資源上限、worker 掛掉。這三種跟「有沒有下一步」無關 ——
    硬要繼續會踩到真正的界線。
    """

    def test_policy_boundary(self):
        self.assertTrue(S.classify_stop(
            "POLICY_BOUNDARY", has_authorized_next_action=True).ok)

    def test_resource_limit(self):
        self.assertTrue(S.classify_stop(
            "RESOURCE_LIMIT", has_authorized_next_action=True).ok)

    def test_worker_failure(self):
        self.assertTrue(S.classify_stop(
            "WORKER_FAILURE", has_authorized_next_action=True).ok)

    def test_waiting_external_does_not_survive_it(self):
        """在等外面的東西，同時又有確定的下一步，那就該做那個下一步。"""
        self.assertFalse(S.classify_stop(
            "WAITING_EXTERNAL", has_authorized_next_action=True).ok)


class TestAssessmentRefusesToBeEmpty(unittest.TestCase):

    def test_a_verdict_without_a_reason_is_refused(self):
        with self.assertRaises(S.StopReasonError):
            S.StopAssessment("VALID", "WAITING_EXTERNAL", "")

    def test_an_unknown_verdict_is_refused(self):
        with self.assertRaises(S.StopReasonError):
            S.StopAssessment("PROBABLY_FINE", "WAITING_EXTERNAL", "x")


class TestBurden(unittest.TestCase):

    def test_violations_are_reported_separately_from_the_count(self):
        """停 20 次而 18 次合規，跟停 20 次而 18 次違規，
        在「停了幾次」上一模一樣。所以違規率要單獨列。"""
        good = [S.classify_stop("NEEDS_HUMAN_DECISION",
                                needs_owner_decision=True) for _ in range(8)]
        bad = [S.classify_stop("UNKNOWN_STOP",
                               has_authorized_next_action=True)
               for _ in range(2)]
        b = S.burden(good + bad)
        self.assertEqual(b["stops"], 10)
        self.assertEqual(b["violations"], 2)
        self.assertAlmostEqual(b["violation_rate"], 0.2)

    def test_no_stops_does_not_divide_by_zero(self):
        self.assertEqual(S.burden([])["violation_rate"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
