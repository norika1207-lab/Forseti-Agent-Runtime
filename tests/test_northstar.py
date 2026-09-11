#!/usr/bin/env python3
"""北極星版本鏈。階段 3 的第一塊。

這一組測試守的是一句她講過但沒寫進文件的話：

    人改變想法時拿舊北極星去警告他，那個北極星就變成強噪音

所以重點不是「版本號會加一」，是三件事：
舊版留著、鏈不能斷、以及任何警告開口前都問得出「這一版還算數嗎」。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import northstar as N  # noqa: E402


class TestChain(unittest.TestCase):

    def setUp(self):
        self.c = N.Chain()

    def test_first_version_has_no_predecessor(self):
        ns = self.c.adopt("讓 AI 的工作狀態可觀測", authority="owner", why="起點")
        self.assertEqual(ns.version, 1)
        self.assertIsNone(ns.supersedes)

    def test_the_chain_cannot_be_broken(self):
        """第二版以後一定要說出取代哪一版。

        斷掉的鏈沒辦法回答「當時對著的是哪一個」，
        而那正是回頭看一個舊決定時唯一要問的問題。
        """
        with self.assertRaises(N.NorthStarError):
            N.NorthStar(objective="x", version=2, supersedes=None)
        with self.assertRaises(N.NorthStarError):
            N.NorthStar(objective="x", version=1, supersedes=1)

    def test_adopting_keeps_the_old_one(self):
        """換版本不刪舊的。

        刪掉之後，所有舊決定都會被拿現在的標準去評 ——
        那是最不公平的一種事後諸葛。
        """
        self.c.adopt("原本的目標", authority="owner", why="起點")
        self.c.adopt("改過的目標", authority="owner", why="她改變想法")
        self.assertEqual(len(self.c.versions), 2)
        self.assertEqual(self.c.at_version(1).objective, "原本的目標")
        self.assertEqual(self.c.current.objective, "改過的目標")

    def test_there_is_no_delete(self):
        for forbidden in ("delete", "remove", "drop", "prune"):
            self.assertFalse(hasattr(self.c, forbidden),
                             f"Chain 不該有 {forbidden}()")

    def test_changing_your_mind_is_not_a_failure(self):
        """沒有任何一個欄位在問「哪裡錯了」。

        改變想法是擁有者的權力，不是需要被解釋的異常。
        """
        ns = self.c.adopt("新方向", authority="owner", why="想法變了")
        fields = set(ns.to_dict())
        for blame in ("reason_for_failure", "error", "mistake", "regression"):
            self.assertNotIn(blame, fields)
        self.assertIn("why", fields)


class TestStaleness(unittest.TestCase):
    """拿 stale 的北極星去警告人，那個警告就是噪音。"""

    def setUp(self):
        self.c = N.Chain()
        self.c.adopt("第一版", authority="owner", why="起點")

    def test_current_version_is_not_stale(self):
        self.assertFalse(self.c.is_stale(1))

    def test_superseded_version_is_stale(self):
        self.c.adopt("第二版", authority="owner", why="她改變想法")
        self.assertTrue(self.c.is_stale(1),
                        "對著第一版發出的警告，現在是噪音")
        self.assertFalse(self.c.is_stale(2))

    def test_an_empty_chain_makes_everything_stale(self):
        """沒有北極星的時候，任何偏離判定都不該開口。

        `.forseti/goal.json` 的註解記過同一件事：沒有錨點就不准說人飄移。
        """
        self.assertTrue(N.Chain().is_stale(1))
        self.assertIsNone(N.Chain().current)

    def test_a_cut_branch_is_not_current(self):
        """CUT 的版本不算生效中（v5.0 §8.2：停止傳播）。"""
        self.c.adopt("走錯的方向", authority="owner", why="試試看",
                     branch="CUT")
        self.assertEqual(self.c.current.version, 1,
                         "被 CUT 的那一版不該成為現在生效的")


class TestWhyIsMandatory(unittest.TestCase):

    def test_adopt_requires_authority_and_why(self):
        c = N.Chain()
        for kwargs in ({"authority": "", "why": "x"},
                       {"authority": "owner", "why": "  "}):
            with self.assertRaises(N.NorthStarError):
                c.adopt("目標", **kwargs)

    def test_empty_objective_is_refused(self):
        """空的目標比沒有目標危險，因為它看起來像有目標。"""
        with self.assertRaises(N.NorthStarError):
            N.NorthStar(objective="   ")


class TestDiff(unittest.TestCase):

    def test_diff_says_what_changed_and_why(self):
        c = N.Chain()
        c.adopt("做 A", authority="owner", why="起點",
                non_goals=["不做 B"])
        c.adopt("做 A 跟 C", authority="owner", why="她說 C 也要",
                non_goals=["不做 B"])
        d = c.diff(1, 2)
        self.assertIn("objective", d["changed"])
        self.assertNotIn("non_goals", d["changed"], "沒變的不該出現在 diff 裡")
        self.assertEqual(d["why"], "她說 C 也要")

    def test_diff_on_a_missing_version_raises(self):
        c = N.Chain()
        c.adopt("x", authority="owner", why="起點")
        with self.assertRaises(N.NorthStarError):
            c.diff(1, 99)


class TestBranches(unittest.TestCase):

    def test_five_branches_exactly(self):
        self.assertEqual(len(N.BRANCHES), 5)
        self.assertEqual(set(N.BRANCHES), set(N.BRANCH_MEANING))

    def test_unknown_branch_is_refused(self):
        with self.assertRaises(N.NorthStarError):
            N.NorthStar(objective="x", branch="差不多是主線")


if __name__ == "__main__":
    unittest.main(verbosity=2)
