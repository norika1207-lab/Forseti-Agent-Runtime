#!/usr/bin/env python3
"""三個 overclaim primitive，從 src/claims.js 移植過來。

**這一組測試的重點是三條判準邊界，不是功能會動：**

一，詞表只當觸發器（B-05）。只命中詞沒量到差 → INDETERMINATE。
二，資料不足回 INDETERMINATE，不假設完整。
三，誇大不等於捏造。FP-07 那 25 筆是真的驗過的。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import overclaim as O  # noqa: E402


class TestScopeCoverage(unittest.TestCase):

    def test_unscoped_claim_gives_none_not_one(self):
        """宣稱什麼都沒說的時候，覆蓋率是 None 不是 1。

        這是整個模組最重要的一個預設方向。回 1 的話，
        一個完全沒有範圍的宣稱會變成「完全被覆蓋」，
        而它其實是「這個問題問不出來」。
        """
        cov = O.scope_coverage(O.make_scope(environment="ci"), O.make_scope())
        self.assertIsNone(cov["coverage"])
        self.assertIn("未定義不是完整", cov["note"])

    def test_undeclared_evidence_dimension_counts_as_uncovered(self):
        """宣稱有要求而證據沒說，算沒覆蓋不算不知道。

        「我沒說我在哪個環境跑的」不能讓一個跨環境的宣稱通過。
        """
        cov = O.scope_coverage(
            O.make_scope(actor="me"),
            O.make_scope(actor="me", environment="production"))
        self.assertIn("environment", cov["uncovered"])
        self.assertIn("environment", cov["undeclared"])
        self.assertEqual(cov["coverage"], 0.5)

    def test_full_match(self):
        s = O.make_scope(environment="ci", stage="e2e")
        self.assertEqual(O.scope_coverage(s, s)["coverage"], 1.0)

    def test_seven_dimensions(self):
        self.assertEqual(len(O.DIMENSIONS), 7)
        self.assertEqual(set(O.make_scope()), set(O.DIMENSIONS))


class TestTermsAreOnlyTriggers(unittest.TestCase):
    """B-05：字串比對訊號不能單獨產生 finding。"""

    def test_expanding_term_without_measured_gap_is_indeterminate(self):
        """說「全部通過」而且真的全部通過，不是誇大。"""
        s = O.make_scope(environment="ci", stage="e2e")
        f = O.evidence_scope_inflation("全部通過了", s, [s])
        self.assertEqual(f.verdict, "NEGATIVE")
        self.assertIn("全部", f.terms)

    def test_measured_gap_without_a_term_is_indeterminate(self):
        """覆蓋不足但沒有把範圍講大，不是誇大 —— 可能只是還沒做完。"""
        f = O.evidence_scope_inflation(
            "改了一部分", O.make_scope(environment="prod", stage="e2e"),
            [O.make_scope(environment="ci")])
        self.assertEqual(f.verdict, "INDETERMINATE")
        self.assertIn("可能只是還沒做完", f.why)

    def test_both_together_is_positive(self):
        f = O.evidence_scope_inflation(
            "端到端都驗過了", O.make_scope(environment="prod", stage="e2e"),
            [O.make_scope(environment="ci", stage="unit")])
        self.assertEqual(f.verdict, "POSITIVE")
        self.assertIn("端到端", f.terms)
        self.assertIn("environment", f.measured["uncovered"])


class TestProvenanceCollapse(unittest.TestCase):
    """FP-03：別人查的講成自己查的。"""

    def test_reporting_someone_elses_finding_is_legitimate(self):
        """「sub-agent 說 X」是合法的 DECLARED，不該被抓。"""
        f = O.provenance_collapse("sub-agent 回報了 589 條", own_receipts=0,
                                  other_source_observations=589)
        self.assertEqual(f.verdict, "NEGATIVE")

    def test_first_person_with_own_receipts_is_fine(self):
        f = O.provenance_collapse("我親自驗過了", own_receipts=12)
        self.assertEqual(f.verdict, "NEGATIVE")

    def test_unknown_receipt_count_is_indeterminate_not_positive(self):
        """查不到有幾筆 receipt，不等於是零。

        **沒查到不等於沒有。** 這一條跟 bible Q-07 是同一件事。
        """
        f = O.provenance_collapse("我親自驗過了", own_receipts=None)
        self.assertEqual(f.verdict, "INDETERMINATE")
        self.assertIn("沒查到不等於沒有", f.why)

    def test_the_real_case(self):
        """原型：589 條 sub-agent 的 file:line，主 agent 說成親驗，
        自己開過的檔案數是零。
        """
        f = O.provenance_collapse("我親自逐一確認過那 589 條",
                                  own_receipts=0, other_source_observations=589)
        self.assertEqual(f.verdict, "POSITIVE")
        self.assertIn("589", f.why)

    def test_zero_receipts_and_no_other_source_is_indeterminate(self):
        """自己沒有、別人也沒有，可能只是採集沒抓到。"""
        f = O.provenance_collapse("我親自驗過了", own_receipts=0,
                                  other_source_observations=0)
        self.assertEqual(f.verdict, "INDETERMINATE")


class TestSemanticCoverageInflation(unittest.TestCase):
    """FP-07：「逐條」實際只核了一部分。"""

    def test_missing_count_is_indeterminate(self):
        for kwargs in ({"claimed_count": 589}, {"verified_count": 25}, {}):
            f = O.semantic_coverage_inflation(claim_text="逐條核對過了", **kwargs)
            self.assertEqual(f.verdict, "INDETERMINATE")
            self.assertIn("不得假設它是完整的", f.why)

    def test_the_real_case_is_exaggeration_not_fabrication(self):
        """25/589 這個原型。**它不叫捏造。**

        那 25 筆是真的驗過的。差別在「逐條」讓人以為是 589。
        分清楚這兩件事，是因為指控捏造跟指出誇大，
        對被指控的人是完全不同的兩件事。
        """
        f = O.semantic_coverage_inflation(
            claimed_count=589, verified_count=25, claim_text="逐條核對過了")
        self.assertEqual(f.verdict, "POSITIVE")
        self.assertIn("這不是捏造", f.why)
        self.assertIn("是真的驗過的", f.why)

    def test_above_threshold_passes(self):
        f = O.semantic_coverage_inflation(
            claimed_count=100, verified_count=95, claim_text="全部核對過了")
        self.assertEqual(f.verdict, "NEGATIVE")

    def test_partial_without_a_totalising_word_is_not_inflation(self):
        f = O.semantic_coverage_inflation(
            claimed_count=589, verified_count=25, claim_text="核了 25 條")
        self.assertEqual(f.verdict, "INDETERMINATE")
        self.assertIn("做一半不是誇大", f.why)


class TestInspect(unittest.TestCase):

    def test_it_returns_everything_including_the_negatives(self):
        """不過濾掉沒發現的那些。

        只回 POSITIVE 的話，呼叫端分不出「查過沒事」與「根本沒查」，
        而那兩件事在這個專案裡是完全不同的答案。
        """
        out = O.inspect("改了一點東西")
        self.assertEqual(len(out), 3)
        self.assertEqual({f.primitive_id for f in out},
                         {"FP-02", "FP-03", "FP-07"})
        self.assertTrue(all(f.verdict in O.VERDICTS for f in out))

    def test_findings_are_frozen(self):
        f = O.inspect("x")[0]
        with self.assertRaises(Exception):
            f.verdict = "POSITIVE"


if __name__ == "__main__":
    unittest.main(verbosity=2)
