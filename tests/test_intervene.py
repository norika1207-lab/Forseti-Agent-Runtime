#!/usr/bin/env python3
"""介入的門檻。

守三件事：

一，**高溫不是動手的理由。** 每一個動作都要溫度加上一個可驗證的事實。
只有溫度就動手，等於拿一個沒有單位的數字當授權。

二，跟 `src/intervention.js` 的動作清單不准分岔。

三，探針不准問「你是不是飄移了」。問了只會拿到流利的否認，
而那個問題本身已經改變了被觀測的東西。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import intervene as I  # noqa: E402


class HotAloneIsNotEnough(unittest.TestCase):
    """規格 10：高溫不是動手的理由。"""

    def test_suggest_recovery_needs_a_fact_not_just_heat(self):
        hot_only = I.can_intervene("SUGGEST_RECOVERY", {"temperature": 0.95})
        self.assertFalse(hot_only["allowed"], "只有高溫就放行 = 沒有單位的授權")
        with_fact = I.can_intervene(
            "SUGGEST_RECOVERY",
            {"temperature": 0.95, "progress_stagnation": True})
        self.assertTrue(with_fact["allowed"])

    def test_freeze_retry_ignores_temperature(self):
        """重試預算跟溫度無關。用完就是用完。"""
        r = I.can_intervene("FREEZE_RETRY", {
            "temperature": 0.0,
            "retry_budget_exceeded": True, "progress_stagnation": True})
        self.assertTrue(r["allowed"])

    def test_freeze_retry_needs_both(self):
        one = I.can_intervene("FREEZE_RETRY", {"retry_budget_exceeded": True})
        self.assertFalse(one["allowed"], "重試多不等於該凍結，還要沒有進度")

    def test_block_high_risk_only_on_unknown_prerequisite(self):
        self.assertTrue(I.can_intervene(
            "BLOCK_HIGH_RISK", {"prerequisite_unknown": True})["allowed"])
        self.assertFalse(I.can_intervene(
            "BLOCK_HIGH_RISK", {"temperature": 1.0})["allowed"])

    def test_unknown_action_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            I.can_intervene("JUST_DO_SOMETHING", {})


class ProbeDoesNotAskTheUselessQuestion(unittest.TestCase):
    """規格 9.1：不可以持續盤問被觀測的模型。"""

    def test_forbidden_phrasings_are_listed(self):
        p = I.build_probe("測試")
        self.assertIn("你是不是飄移了", p["forbidden"])
        self.assertIn("你還在跟著目標嗎", p["forbidden"])

    def test_answer_is_capped_at_inferred(self):
        """回答本身是宣稱。對照現實之前不會升級成事實。"""
        self.assertEqual(I.build_probe()["answer_epistemic_ceiling"], "INFERRED")

    def test_probe_must_be_logged(self):
        self.assertTrue(I.build_probe()["must_log_as_intervention"])


class MatchesTheJsSource(unittest.TestCase):
    def test_same_action_list(self):
        js = (REPO / "src" / "intervention.js").read_text(encoding="utf-8")
        block = js.split("export const ACTIONS", 1)[1].split("]", 1)[0]
        names = re.findall(r"'([A-Z_]+)'", block)
        self.assertEqual(list(I.ACTIONS), names,
                         "Python 端跟 src/intervention.js 的動作清單分岔了")

    def test_every_action_has_a_meaning(self):
        self.assertEqual(set(I.ACTION_MEANING), set(I.ACTIONS))


class DecideExplainsItself(unittest.TestCase):
    """一個說不出理由的介入沒辦法被反駁。"""

    def test_every_allowed_action_carries_why(self):
        snap = {"total_dots": 100, "total_failed": 30, "betrayal_total": 2,
                "context": {"pct": 95, "headroom": 1000}, "rows": []}
        for a in I.decide(snap):
            self.assertTrue(a.get("why", "").strip(),
                            f"{a['action']} 沒有說憑什麼")

    def test_clean_session_triggers_nothing(self):
        """沒事的時候不准假裝有事。"""
        snap = {"total_dots": 100, "total_failed": 0, "betrayal_total": 0,
                "context": {"pct": 20, "headroom": 500000}, "rows": []}
        self.assertEqual(I.decide(snap), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
