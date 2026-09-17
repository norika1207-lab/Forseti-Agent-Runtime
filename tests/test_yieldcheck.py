#!/usr/bin/env python3
"""過早交還發言權的判準。

守兩件事：

一，五個 verdict 的分界。BLOCKED 跟 PREMATURE 的處方相反 ——
零產出是卡住，有產出卻停下來是提早收工。判錯方向會給出反的建議。

二，**跟 `src/yield.js` 不准分岔。** 那邊是本尊，這裡是 Python 端。
FP-11 的家族今天才在兩個地方被寫成不同的值（`betrayal.py` 寫 B，
registry 寫 A），而兩邊各自看起來都對。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import yieldcheck as Y  # noqa: E402


class Verdicts(unittest.TestCase):
    def test_no_definition_of_done(self):
        """不知道還剩什麼，不等於沒剩。"""
        self.assertEqual(Y.judge(done_when=None)["verdict"], "CANNOT_DETERMINE")

    def test_asking_is_collaboration(self):
        """問了問題就停下來是協作，不是提早收工。"""
        r = Y.judge(done_when=["a"], unmet=["a"], awaiting=True,
                    produced_this_turn=5)
        self.assertEqual(r["verdict"], "AWAITING")

    def test_zero_output_is_blocked_not_premature(self):
        """零產出是卡住。兩者的處方相反，判錯會給出反的建議。"""
        r = Y.judge(done_when=["a"], unmet=["a"], produced_this_turn=0)
        self.assertEqual(r["verdict"], "BLOCKED")

    def test_produced_but_unfinished_is_premature(self):
        r = Y.judge(done_when=["a", "b"], unmet=["b"], produced_this_turn=3)
        self.assertEqual(r["verdict"], "PREMATURE")
        self.assertEqual(r["outstanding"], ["b"])

    def test_all_met_is_legitimate(self):
        r = Y.judge(done_when=["a"], unmet=[], produced_this_turn=3)
        self.assertEqual(r["verdict"], "LEGITIMATE")

    def test_awaiting_wins_over_unfinished(self):
        """在等人的時候，還有沒做完的事不該被算成提早收工。"""
        r = Y.judge(done_when=["a", "b"], unmet=["a", "b"], awaiting=True,
                    produced_this_turn=1)
        self.assertEqual(r["verdict"], "AWAITING")


class MatchesTheJsSource(unittest.TestCase):
    """跟 src/yield.js 的 VERDICTS 必須一字不差。"""

    def test_same_verdict_list(self):
        js = (REPO / "src" / "yield.js").read_text(encoding="utf-8")
        block = js.split("export const VERDICTS", 1)[1].split("]", 1)[0]
        names = re.findall(r"'([A-Z_]+)'", block)
        self.assertEqual(list(Y.VERDICTS), names,
                         "Python 端跟 src/yield.js 的 verdict 清單分岔了")

    def test_every_verdict_has_a_meaning(self):
        self.assertEqual(set(Y.VERDICT_MEANING), set(Y.VERDICTS))


class TwoSignalsNotOne(unittest.TestCase):
    """確認的提早收工要兩個訊號都成立。

    2026-09-15 實測：單看 PREMATURE 在真實資料上是 219 輪，
    因為帳本那兩條下一步一直掛著，每一輪都算「有事沒做」。
    加上「她下一句真的開口催了」之後落到 12 輪。

    一個訊號只能當觸發器，要證據才算數 —— 白點那次學到的同一條。
    """

    def test_premature_without_nudge_is_not_confirmed(self):
        class S:
            def __init__(self, n, owner="", ai="x", dots=None):
                self.n, self.owner_text, self.ai_text = n, owner, ai
                self.dots, self.growing = dots or [1], False
        # 第二輪她說的是新要求，不是催促
        rows = [S(1), S(2, owner="那接下來把設計稿改成深色")]
        self.assertEqual(Y.confirmed(rows), [])

    def test_asking_detection_is_conservative(self):
        """分不出來的一律當成沒在等 —— 誤判成「在等你」等於幫它找藉口。"""
        self.assertTrue(Y.looks_awaiting("這樣可以嗎？"))
        self.assertTrue(Y.looks_awaiting("兩條路你選，我不再自己決定"))
        self.assertFalse(Y.looks_awaiting("做完了，461 個測試全過。"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
