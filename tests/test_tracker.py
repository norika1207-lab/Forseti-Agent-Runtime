#!/usr/bin/env python3
"""即時追蹤器。守的是「線會長、點釘得對、失敗不冤枉」。

規格 `.forseti/WIDGET_SPEC.md` §3 與 §4。

這一組的重點不在「有幾條線」,在三件事:
線還在長的時候長什麼樣、點併得對不對、失敗判得準不準。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import tracker as T  # noqa: E402


def iso(offset=0.0):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(time.time() + offset, timezone.utc).isoformat()


class Case(unittest.TestCase):

    def setUp(self):
        self.box = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.box, ignore_errors=True))
        self.f = self.box / "t.jsonl"
        self.f.write_text("", encoding="utf-8")
        self.tk = T.Tracker(self.f)
        self.t0 = time.time()

    def write(self, *rows):
        with self.f.open("a", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def owner(self, text, dt=0.0):
        return {"type": "user", "timestamp": iso(dt),
                "message": {"content": text}}

    def ai_text(self, text, dt=0.0):
        return {"type": "assistant", "timestamp": iso(dt),
                "message": {"content": [{"type": "text", "text": text}]}}

    def ai_tool(self, name, tid="t1", dt=0.0, **inp):
        return {"type": "assistant", "timestamp": iso(dt),
                "message": {"content": [
                    {"type": "tool_use", "id": tid, "name": name, "input": inp}]}}

    def result(self, tid="t1", err=False, dt=0.0):
        return {"type": "user", "timestamp": iso(dt),
                "message": {"content": [
                    {"type": "tool_result", "tool_use_id": tid,
                     "is_error": err, "content": "x"}]}}


class TestStrandGrows(Case):
    """§3.1 線有長度,而且還在跑的時候不會停。"""

    def test_a_new_owner_message_starts_a_strand(self):
        self.write(self.owner("做這件事"))
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 1)
        self.assertEqual(self.tk.strands[0].owner_text, "做這件事")

    def test_an_unfinished_strand_is_growing(self):
        """AI 還沒回,那一條的 ended_at 是 None。

        畫面最底下永遠有一條正在長的線,那個視覺很重要。
        """
        self.write(self.owner("做"))
        self.tk.poll()
        s = self.tk.strands[0]
        self.assertTrue(s.growing)
        self.assertIsNone(s.ended_at)

    def test_duration_of_a_growing_strand_counts_to_now(self):
        """還在長的線,長度算到現在,不是 0。"""
        self.write(self.owner("做", dt=-30))
        self.tk.poll()
        self.assertGreater(self.tk.strands[0].duration, 25)

    def test_ai_reply_extends_the_end(self):
        """AI 每講一塊就把終點往後推。線就是這樣長的。"""
        self.write(self.owner("做", dt=-60), self.ai_text("在做", dt=-40))
        self.tk.poll()
        first = self.tk.strands[0].ended_at
        self.write(self.ai_text("做完了", dt=-10))
        self.tk.poll()
        self.assertGreater(self.tk.strands[0].ended_at, first)

    def test_next_owner_message_closes_the_previous(self):
        self.write(self.owner("一", dt=-60), self.ai_text("好", dt=-50),
                   self.owner("二", dt=-10))
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 2)
        self.assertFalse(self.tk.strands[0].growing)
        self.assertTrue(self.tk.strands[1].growing)


class TestDots(Case):
    """§3.2、§3.4 點釘在線上,同一種連續的要併。"""

    def test_a_tool_call_pins_a_dot(self):
        self.write(self.owner("做"), self.ai_tool("Read", file_path="/a.py"))
        self.tk.poll()
        d = self.tk.strands[0].dots[0]
        self.assertEqual(d.label, "Read")
        self.assertEqual(d.detail, "/a.py")

    def test_consecutive_same_tool_merges(self):
        """§3.4 五次 Read 併成一個點寫 Read x5。"""
        rows = [self.owner("做")]
        for i in range(5):
            rows.append(self.ai_tool("Read", tid=f"t{i}"))
        self.write(*rows)
        self.tk.poll()
        dots = self.tk.strands[0].dots
        self.assertEqual(len(dots), 1)
        self.assertEqual(dots[0].count, 5)

    def test_different_tools_do_not_merge(self):
        """不同種的不併 —— 併了漢堡清單會失真。"""
        self.write(self.owner("做"),
                   self.ai_tool("Read", tid="a"),
                   self.ai_tool("Bash", tid="b"),
                   self.ai_tool("Read", tid="c"))
        self.tk.poll()
        self.assertEqual(len(self.tk.strands[0].dots), 3)

    def test_read_and_write_are_separated(self):
        """§3.6 讀不改變世界,寫會。"""
        self.write(self.owner("做"),
                   self.ai_tool("Read", tid="a"),
                   self.ai_tool("Write", tid="b"))
        self.tk.poll()
        s = self.tk.strands[0].to_dict()
        self.assertEqual(s["read"], 1)
        self.assertEqual(s["write"], 1)

    def test_dot_size_is_two(self):
        """§4 輪內動作一律 2x2。"""
        self.write(self.owner("做"), self.ai_tool("Read"))
        self.tk.poll()
        self.assertEqual(self.tk.strands[0].dots[0].size, 2)


class TestFailureIsNotGuessed(Case):
    """§4.1 失敗要判得準。寧可漏掉也不要冤枉一個成功的呼叫。"""

    def test_is_error_marks_the_dot_red(self):
        self.write(self.owner("做"), self.ai_tool("Bash", tid="x"),
                   self.result(tid="x", err=True))
        self.tk.poll()
        self.assertTrue(self.tk.strands[0].dots[0].failed)

    def test_a_successful_result_leaves_it_green(self):
        self.write(self.owner("做"), self.ai_tool("Bash", tid="x"),
                   self.result(tid="x", err=False))
        self.tk.poll()
        self.assertFalse(self.tk.strands[0].dots[0].failed)

    def test_exit_code_in_text_is_not_guessed(self):
        """內容裡寫著 exit 1 也不標紅。

        讀內容猜 exit code 是語意判斷,build-plan.md:350 禁止。
        認不出來就不標紅。
        """
        self.write(self.owner("做"), self.ai_tool("Bash", tid="x"))
        self.write({"type": "user", "timestamp": iso(),
                    "message": {"content": [
                        {"type": "tool_result", "tool_use_id": "x",
                         "content": "command failed with exit code 1"}]}})
        self.tk.poll()
        self.assertFalse(self.tk.strands[0].dots[0].failed)

    def test_tint_is_the_failure_ratio_not_a_score(self):
        """§4.1 tint 只回答「多少比例的動作失敗了」。

        它不是健康度分數。橘代表 AI 開始騙人,不是飄移。
        """
        self.write(self.owner("做"),
                   self.ai_tool("Bash", tid="a"), self.result("a", err=True),
                   self.ai_tool("Write", tid="b"), self.result("b", err=False))
        self.tk.poll()
        self.assertAlmostEqual(self.tk.strands[0].tint, 0.5)

    def test_no_dots_means_no_tint(self):
        self.write(self.owner("做"))
        self.tk.poll()
        self.assertEqual(self.tk.strands[0].tint, 0.0)


class TestGaps(Case):
    """§3.5 空轉要看得出來。實線是有動作,淡的是什麼都沒發生。"""

    def test_a_long_silence_becomes_a_gap(self):
        self.write(self.owner("做", dt=-300), self.ai_tool("Read", dt=-10))
        self.tk.poll()
        gaps = self.tk.strands[0].gaps(min_seconds=20)
        self.assertTrue(gaps)
        self.assertGreater(gaps[0][1] - gaps[0][0], 200)

    def test_dense_activity_has_no_gap(self):
        rows = [self.owner("做", dt=-10)]
        for i in range(5):
            rows.append(self.ai_tool("Read", tid=f"t{i}", dt=-9 + i))
        self.write(*rows)
        self.tk.poll()
        self.assertEqual(self.tk.strands[0].gaps(min_seconds=20), [])


class TestIncremental(Case):
    """只讀新增的部分。那份 jsonl 是 24 MB 而且一直在長。"""

    def test_second_poll_reads_only_new_lines(self):
        self.write(self.owner("一"))
        n1 = self.tk.poll()
        self.assertEqual(n1, 1)
        self.assertEqual(self.tk.poll(), 0)
        self.write(self.owner("二"))
        self.assertEqual(self.tk.poll(), 1)

    def test_a_half_written_line_waits(self):
        """最後一行寫到一半就留到下次。

        這支每 1 到 3 秒跑一次,一定會讀到寫到一半的行。
        """
        self.write(self.owner("一"))
        self.tk.poll()
        with self.f.open("a", encoding="utf-8") as fh:
            fh.write('{"type":"user","message":{"content":"還沒寫完')
        self.assertEqual(self.tk.poll(), 0)
        self.assertEqual(len(self.tk.strands), 1)

    def test_truncation_resets(self):
        """檔案被截斷或換掉就重來 —— 那通常代表換了 session。"""
        self.write(self.owner("一"), self.owner("二"))
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 2)
        self.f.write_text("", encoding="utf-8")
        self.write(self.owner("新的"))
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 1)


class TestCompaction(Case):
    """§6 壓縮是 6x6 的黑點,而且它是一個錨。"""

    def test_one_compaction_spanning_two_lines_is_one_dot(self):
        """一次壓縮橫跨兩行,只該有一顆黑點。

        2026-09-14 實測真實 transcript:
            type=system 那行帶 compactMetadata(有 token 數)
            type=user   那行帶 isCompactSummary(沒有數字)

        第一版對兩行各標一顆,而且第二顆把第一顆的數字蓋掉了。
        """
        self.write(self.owner("做"),
                   {"type": "system", "timestamp": iso(),
                    "compactMetadata": {"trigger": "auto",
                                        "preTokens": 997325,
                                        "postTokens": 17472}},
                   {"type": "user", "timestamp": iso(),
                    "isCompactSummary": True,
                    "message": {"content": "摘要"}})
        self.tk.poll()
        s = self.tk.strands[0]
        black = [d for d in s.dots if d.label == "對話壓縮"]
        self.assertEqual(len(black), 1)
        self.assertEqual(black[0].size, 6)
        self.assertIn("997,325", black[0].detail)
        self.assertEqual(s.compaction_meta["pre_tokens"], 997325)

    def test_the_compaction_dot_carries_the_anchor_line(self):
        """§6.1 黑點知道自己在全量紀錄的第幾行,那是錨的座標。"""
        self.write(self.owner("做"),
                   {"type": "system", "timestamp": iso(),
                    "compactMetadata": {"preTokens": 100, "postTokens": 2}})
        self.tk.poll()
        self.assertEqual(self.tk.strands[0].compaction_meta["line"], 2)

    def test_compaction_without_a_strand_still_anchors(self):
        """session 一開頭就是續接摘要的情況。

        丟掉的話那個錨就不存在了。
        """
        self.write({"type": "system", "timestamp": iso(),
                    "compactMetadata": {"preTokens": 500, "postTokens": 10}})
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 1)
        self.assertTrue(self.tk.strands[0].compaction)

    def test_a_compaction_record_is_marked(self):
        self.write(self.owner("做"),
                   {"type": "user", "timestamp": iso(),
                    "isCompactSummary": True,
                    "message": {"content": "摘要"}})
        self.tk.poll()
        s = self.tk.strands[0]
        self.assertTrue(s.compaction)
        self.assertTrue(any(d.label == "對話壓縮" for d in s.dots))


class TestSnapshotIsBounded(Case):

    def test_only_the_tail_is_sent(self):
        """一條 24 MB 的 transcript 有上百輪,全部送過去前端會重畫整棵樹。"""
        rows = []
        for i in range(30):
            rows.append(self.owner(f"第 {i} 則"))
        self.write(*rows)
        self.tk.poll()
        snap = self.tk.snapshot(tail=10)
        self.assertEqual(snap["strands"], 30)
        self.assertEqual(snap["shown"], 10)
        self.assertEqual(len(snap["rows"]), 10)


if __name__ == "__main__":
    unittest.main(verbosity=2)
