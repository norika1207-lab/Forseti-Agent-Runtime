#!/usr/bin/env python3
"""F08-CTX-001 的 conformance tests。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F08-CTX-001  sha256 b80b985fdfc0  §7 有五條 CT
    另參 Vol3 §4.1 的 RehydrationPacket schema

這一組原本叫 C2。改成對齊 F08 之後出口條件也換了：原本是我自己拍的
「context 增加小於 500 token」，那只管量；F08 管的是質，每一段都要
說得出為什麼被放進來。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import ledger as L  # noqa: E402
import rehydration as R  # noqa: E402


def frag(text, source=R.ORIGINAL, prov="a.jsonl:1-2", why="測試用"):
    return R.Fragment(text=text, source=source, provenance=prov, why=why)


class TestF08(unittest.TestCase):

    def test_CT_F08_01_huge_history_yields_bounded_packet(self):
        """八十萬字的歷史 → 有界的、只跟當前任務相關的 packet。

        不是把歷史倒回來，是照當前任務的需要只取幾段。
        """
        history = [frag("一段舊對話 " * 350, prov=f"h.jsonl:{i}", why=f"與第 {i} 個決策相關")
                   for i in range(400)]
        total = sum(len(f.text) for f in history)
        self.assertGreater(total, 800_000)

        p = R.build(goal="北極星", task="當前任務", fragments=history)

        self.assertLessEqual(p.size, R.PACKET_LIMIT, "packet 必須有界")
        self.assertGreater(p.dropped_for_budget, 0, "超出預算的要被記下來，不是靜靜消失")
        self.assertLess(p.size, total / 50)

    def test_CT_F08_02_original_wins_over_summary(self):
        """摘要與原文衝突 → 原文贏。不折衷、不併陳。

        併陳等於把矛盾轉嫁給讀的人，而讀的人正是那個已經沒有脈絡的。
        """
        same = "x.jsonl:10-20"
        frs = [
            frag("摘要版：決定用 A 方案", source=R.SUMMARY, prov=same, why="摘要"),
            frag("原文：先試 A，失敗後改用 B", source=R.ORIGINAL, prov=same, why="原文"),
            frag("另一段摘要", source=R.SUMMARY, prov="y.jsonl:1", why="沒有對應原文"),
        ]
        kept = R.resolve(frs)
        texts = [f.text for f in kept]
        self.assertIn("原文：先試 A，失敗後改用 B", texts)
        self.assertNotIn("摘要版：決定用 A 方案", texts)
        self.assertIn("另一段摘要", texts, "沒有對應原文的摘要要留著")

    def test_CT_F08_03_three_sampled_fragments_is_SAMPLED_not_FULL_READ(self):
        """讀了三段 → SAMPLED，不是 FULL_READ。

        §5 原文：「I know the document」with SAMPLED coverage is not
        full understanding。level 是量出來的不是報上來的。
        """
        lvl = R.coverage_of(read_ranges=[(1, 5), (40, 45), (900, 905)], total_lines=1000)
        self.assertEqual(lvl, "SAMPLED")
        self.assertFalse(R.is_full_understanding(lvl))

    def test_CT_F08_03b_full_read_still_is_not_verified_understanding(self):
        """全部讀完也只到 FULL_READ，除非有人考過。

        這是 level 5 與 6 的差別，也是 gate takeover 現在到不了 6 的原因。
        """
        ranges = [(1, 1000)]
        self.assertEqual(R.coverage_of(read_ranges=ranges, total_lines=1000), "FULL_READ")
        self.assertEqual(
            R.coverage_of(read_ranges=ranges, total_lines=1000, challenged_ok=True),
            "VERIFIED_UNDERSTANDING")

    def test_CT_F08_03c_claiming_to_have_read_without_ranges_is_NONE(self):
        """沒有實際讀過的範圍就是 NONE，不管誰說他讀過。"""
        self.assertEqual(R.coverage_of(read_ranges=[], total_lines=1000), "NONE")

    def test_CT_F08_04_compression_keeps_task_state_and_challenges_goal(self):
        """壓縮 → 任務狀態不變，而且要考 Goal recall。

        考的方式是問具體內容。問「你還記得嗎」沒有用，那個問題的答案
        永遠是「記得」—— 2026-09-09 這一場就實際發生過。
        """
        tmp = Path(tempfile.mkdtemp())
        led = L.Ledger(db=tmp / "t.db", cwd=tmp)
        t = led.accept("任務", [L.Step("s1", "第一步")])
        led.transition(t, "RUNNING", "開始")
        before = led.state_of(t)

        led.close()  # 壓縮 = 這一端的記憶全部丟掉
        led = L.Ledger(db=tmp / "t.db", cwd=tmp)
        after = led.state_of(t)

        b = R.CompressionBoundary(at=0, pre_tokens=997325, post_tokens=17472,
                                  dropped_tokens=979853,
                                  task_state_before=before, task_state_after=after)
        self.assertTrue(b.task_state_intact, "壓縮改變任務狀態的話，整個帳本就白做了")
        qs = b.challenge()
        self.assertTrue(any("北極星" in q for q in qs))
        self.assertFalse(any("你還記得嗎" in q for q in qs))
        led.close()

    def test_CT_F08_05_worker_tool_noise_stays_outside_main(self):
        """worker 的工具雜訊留在 Main 外面。

        packet 裡只有 provenance，沒有 raw log 的內容。
        """
        p = R.build(goal="北極星", task="任務",
                    fragments=[frag("一句決策", prov="ledger:step-1", why="這一步的依據")],
                    decisions=["用 sqlite 不用 JSON"],
                    constraints=["帳本只能 ALTER 不能 DROP"])
        blob = str(p.to_dict())
        self.assertNotIn("compiler warning", blob)
        self.assertIn("ledger:step-1", p.provenance_refs)
        self.assertLess(p.size, 500)


class TestWhyIsMandatory(unittest.TestCase):
    """Vol3 §4.1 的 why_each_fragment_is_included。"""

    def test_fragment_without_why_is_refused(self):
        """說不出為什麼要放這一段，就不該放。

        沒有這一欄的話，rehydration 會變成另一種塞：塞的是有關但不必要的
        東西，而「有關」是一個永遠成立的理由。
        """
        for bad in ("", "   "):
            with self.assertRaises(ValueError):
                R.Fragment(text="內容", source=R.ORIGINAL, provenance="x:1", why=bad)

    def test_why_table_covers_every_fragment(self):
        p = R.build(goal="g", task="t", fragments=[
            frag("A", prov="p1", why="因為 A"),
            frag("B", prov="p2", why="因為 B"),
        ])
        self.assertEqual(len(p.why_table()), 2)
        self.assertEqual(dict(p.why_table())["p2"], "因為 B")

    def test_unknown_source_is_refused(self):
        with self.assertRaises(ValueError):
            R.Fragment(text="x", source="大概是原文吧", provenance="p", why="理由")


class TestBudgetPriority(unittest.TestCase):
    def test_decisions_and_unknowns_survive_the_budget_cut(self):
        """超出預算時砍片段，不砍決策、約束、未知。

        那三樣是結論性的、體積小、丟掉會讓 packet 失去骨架；
        片段是可以再查的，因為 provenance 還在。
        """
        big = [frag("很長的一段 " * 300, prov=f"p{i}", why="測試") for i in range(20)]
        p = R.build(goal="g", task="t", fragments=big,
                    decisions=["決策一", "決策二"],
                    constraints=["約束一"],
                    unknowns=["還不知道的事"], limit=2000)
        self.assertLessEqual(p.size, 2000)
        self.assertEqual(p.key_decisions, ["決策一", "決策二"])
        self.assertEqual(p.unresolved_unknowns, ["還不知道的事"])
        self.assertGreater(p.dropped_for_budget, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
