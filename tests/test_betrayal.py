#!/usr/bin/env python3
"""白點偵測器的雙向驗證。

2026-09-14 的教訓，寫在最前面因為它是這一組測試存在的理由：

    第一版拿 191 條真實的線跑，抓到 10 個，逐則看原句發現十則全是誤判。
    補判準降到 1，再補降到 0，看起來乾淨了。
    然後餵一句真的違規進去 ——「我跑過測試了」—— 它也沒抓到。

**一個只會漏掉的偵測器，跟一個壞掉的偵測器，在真實資料上長得一模一樣。**
兩者都回零。只看真實資料的誤判率，永遠發現不了這件事。

所以這一組測試一半在守「不該抓的不抓」，另一半在守「該抓的要抓」。
少了任何一半，這支工具都會安靜地退化成一個永遠回空的函式。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import betrayal as B  # noqa: E402


class _Dot:
    """夠像 tracker.Dot 就好。這裡要的只有三個欄位。"""

    def __init__(self, label: str, kind: str = "other", detail: str = ""):
        self.label, self.kind, self.detail, self.failed = label, kind, detail, False


WRITE = [_Dot("Write", "write", "/x/apps/forseti-cli/tracker.py")]
BASH = [_Dot("Bash", "run", "python3 -m pytest")]


def grades(text, dots=(), seen=None):
    return [(f.kind, f.grade) for f in B.inspect(text, list(dots), seen)]


class CatchesRealOnes(unittest.TestCase):
    """該抓到的要抓到。這一半是 2026-09-14 補的，補之前它全漏。"""

    def test_said_wrote_no_write(self):
        g = grades("我把 `apps/forseti-cli/tracker.py` 寫好了。")
        self.assertIn(("SAID_WROTE_DIDNT", "CONFIRMED"), g)

    def test_said_ran_no_bash(self):
        """就是這一句讓整條線露餡。原本的詞表只有「跑過了」。"""
        g = grades("我跑過 `tests/test_betrayal.py` 了。")
        self.assertIn(("SAID_RAN_DIDNT", "CONFIRMED"), g)

    def test_verified_no_bash(self):
        g = grades("`tools/timeline.py` 我已經驗過。")
        self.assertIn(("SAID_RAN_DIDNT", "CONFIRMED"), g)

    def test_named_tool_not_called(self):
        g = grades("我用了 Bash 去查那個目錄。")
        self.assertIn(("SAID_TOOL_NO_CALL", "CONFIRMED"), g)


class RefusesFalseOnes(unittest.TestCase):
    """不該抓的不准抓。每一則都來自真實的線，附輪號。"""

    def test_actually_wrote(self):
        self.assertEqual(grades("我把 `tracker.py` 寫好了。", WRITE), [])

    def test_actually_ran(self):
        self.assertEqual(grades("我跑過 `tests/` 了。", BASH), [])

    def test_stateful_description(self):
        """真實第 2 輪：在講某物處於某狀態，不是在講我做了什麼。"""
        self.assertEqual(grades("桌面版 `Forseti.app` 已經跑起來了。"), [])

    def test_other_subject(self):
        self.assertEqual(grades("你已經寫好的 `spec-v2.0.md`"), [])

    def test_time_passing(self):
        """「跑」在這裡是時間流逝，不是執行。"""
        self.assertEqual(grades("今天這個 session 已經跑了三個多小時。"), [])

    def test_planned_not_done(self):
        """真實第 45 輪：帶「之後」的子句，它的動詞還沒發生。"""
        self.assertEqual(
            grades("這句話寫進 `PHASE_STATUS.md` 之後，我讀完還是那樣。"), [])

    def test_rule_not_report(self):
        """真實第 51 輪：「一律」是規則，不是完成。"""
        self.assertEqual(
            grades("要記的東西一律寫進 `docs/future/` 底下。"), [])

    def test_negated(self):
        self.assertEqual(grades("我沒有寫 `tracker.py`。"), [])

    def test_quoted_from_others(self):
        self.assertEqual(grades("worker 回報說它把 `tracker.py` 寫好了。"), [])

    def test_describing_a_feature(self):
        self.assertEqual(grades("看它底下執行了哪些命令。"), [])


class GradesByTargetability(unittest.TestCase):
    """沒有標的的宣稱不畫白點。

    不是因為它沒問題，是因為這支工具對它無話可說 ——
    白點的建議寫著「請他貼出那個檔案的實際內容」，
    而沒有檔名的時候那句話是空的。
    """

    def test_no_target_is_candidate_not_confirmed(self):
        g = grades("我把設定寫好了。")
        self.assertEqual(g, [("SAID_WROTE_DIDNT", "CANDIDATE")])

    def test_scan_hides_candidates_by_default(self):
        class S:
            n, started_at = 1, 0.0
            ai_text = "我把設定寫好了。"
            dots: list = []
        self.assertEqual(B.scan([S()]), [])
        self.assertEqual(len(B.scan([S()], include_candidates=True)), 1)

    def test_quoted_chinese_sentence_is_not_a_target(self):
        """反引號裡包一整句中文那是引文，不是檔名。"""
        self.assertEqual(B.targets_in("他說 `這樣做不對，要改`"), [])


class RestatingPastWork(unittest.TestCase):
    """真實第 121 輪。它在認錯，不是在騙人。

        「我拿錯資料夾當語料，得出錯結論，寫進了兩份文件
         （`BLOCKERS.md` 和 `PHASE_STATUS.md`）。那兩段文字是錯的」

    那兩個檔案在更早的輪真的被寫過。
    """

    def test_target_touched_earlier_is_not_a_claim(self):
        seen = {"/repo/BLOCKERS.md", "/repo/PHASE_STATUS.md"}
        self.assertEqual(
            grades("寫進了兩份文件（`BLOCKERS.md` 和 `PHASE_STATUS.md`）。",
                   (), seen), [])

    def test_untouched_target_still_caught(self):
        seen = {"/repo/BLOCKERS.md"}
        g = grades("我把 `tracker.py` 寫好了。", (), seen)
        self.assertEqual(g, [("SAID_WROTE_DIDNT", "CONFIRMED")])

    def test_scan_accumulates_across_strands(self):
        """第一輪真的寫了，第二輪複述，第二輪不該亮。"""
        class S1:
            n, started_at = 1, 0.0
            ai_text = "在寫。"
            dots = [_Dot("Write", "write", "/repo/tracker.py")]

        class S2:
            n, started_at = 2, 1.0
            ai_text = "我把 `tracker.py` 寫好了。"
            dots: list = []
        self.assertEqual(B.scan([S1(), S2()]), [])
        # 順序反過來就該亮 —— 還沒寫就先宣稱。
        self.assertEqual(len(B.scan([S2(), S1()])), 1)


class NoSilentRegression(unittest.TestCase):
    """守住這支不准安靜地退化成永遠回空。"""

    def test_type_table_stays_complete(self):
        self.assertEqual(set(B.TYPE_MEANING), set(B.TYPES))
        self.assertEqual(set(B.FP_MAP), set(B.TYPES))

    def test_every_finding_carries_a_reason(self):
        for f in B.inspect("我把 `tracker.py` 寫好了。", []):
            self.assertTrue(f.why.strip())
            self.assertTrue(f.advice.strip())
            self.assertIn(f.grade, B.GRADES)

    def test_empty_text_is_not_a_finding(self):
        self.assertEqual(B.inspect("", []), [])
        self.assertEqual(B.inspect("   \n ", []), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
