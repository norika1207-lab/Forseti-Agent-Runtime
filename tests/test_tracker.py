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


class TestClaudeSupport(Case):
    def test_sidechain_is_exposed_as_child_record(self):
        project = self.f.parent / "subagents"
        project.mkdir()
        child = project / "agent-child.jsonl"
        child.write_text(json.dumps({
            "type": "user", "timestamp": iso(), "isSidechain": True,
            "message": {"content": "支援讀取工作佇列"}}, ensure_ascii=False) + "\n" +
            json.dumps({"type": "assistant", "timestamp": iso(),
                        "isSidechain": True,
                        "message": {"content": [{"type": "text",
                            "text": "支援已回報結果"}]}}, ensure_ascii=False) + "\n",
            encoding="utf-8")
        self.write(self.owner("主命令"))
        self.tk.poll()
        support = self.tk.snapshot()["rows"][0]["support"]
        self.assertEqual(len(support), 1)
        self.assertEqual(support[0]["request"], "支援讀取工作佇列")
        self.assertIn("支援已回報結果", support[0]["response"])


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


class TestOverclaimEvidenceContract(Case):
    """overclaim 需要的數字在 tracker 層形成，不由 UI 猜。"""

    def test_explicit_claimed_count_is_extracted_from_ai_text(self):
        self.write(self.owner("查"),
                   self.ai_text("抽查 25 項，並宣稱全部 589 條都核對過"))
        self.tk.poll()
        self.assertEqual(self.tk.strands[0].claimed_count, 589)

    def test_local_and_other_source_receipts_are_separate(self):
        self.write(self.owner("查"),
                   self.ai_tool("Read", tid="local", file_path="a.py"),
                   self.result("local"),
                   self.ai_tool("TaskOutput", tid="other"),
                   self.result("other"))
        self.tk.poll()
        s = self.tk.strands[0]
        self.assertEqual(s.own_receipts, 1)
        self.assertEqual(s.verified_count, 1)
        self.assertEqual(s.other_source_observations, 1)

    def test_failed_tool_is_not_a_receipt(self):
        self.write(self.owner("查"), self.ai_tool("Read", tid="bad"),
                   self.result("bad", err=True))
        self.tk.poll()
        self.assertEqual(self.tk.strands[0].own_receipts, 0)


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

    def test_the_rest_of_a_half_written_line_is_picked_up_next_time(self):
        """上面那一支只驗到「這一次不算」,沒有驗到「下一次讀得到」。

        兩者差很多:一行被跳過去,跟一行等著被補完,對這一次的 poll()
        都是 0。**分得出來的只有補完之後那一次。** 沒有這一條的話,
        把上面那支的寫入端換成 `jsonlio.append_line`(它會替半行補上
        結尾換行)測試照樣綠,而那一筆其實永久讀不到了 ——
        2026-09-19 兩組實測:裸 append 補完之後 poll()=1,
        走 append_line 補完之後 poll()=0,而兩組半行那一次都是 0。
        """
        self.write(self.owner("一"))
        self.tk.poll()
        with self.f.open("a", encoding="utf-8") as fh:
            fh.write('{"type":"user","message":{"content":"還沒寫完')
        self.assertEqual(self.tk.poll(), 0)
        with self.f.open("a", encoding="utf-8") as fh:
            fh.write('"},"timestamp":"%s"}\n' % iso(1))
        self.assertEqual(self.tk.poll(), 1, "補完的那一行要讀得到,不是被跳過")
        self.assertEqual(len(self.tk.strands), 2)

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


class TestCompactionReplay(Case):
    """壓縮之前，同一則訊息會被再寫一次到同一份檔案。

    2026-09-19 在 12 份真實 transcript 上量到的：重播區段的最後一行，
    下一行就是 `compact_boundary`（差 1，12/12）。357 組重複配對裡，
    tracker 會讀的五個欄位全部相同。

    不去重的後果不是「多畫一個點」而已 —— 重播裡若有 owner 訊息，
    畫面上會多出一條**她沒講過的**來回（`e88e0125` 第 96 輪就是）。
    """

    def replayable(self, rec, uid):
        rec = dict(rec)
        rec["uuid"] = uid
        return rec

    def test_the_same_message_written_twice_is_counted_once(self):
        # 同一個 dict 重寫，才是真的「同一則訊息」—— 每次現叫
        # `self.ai_tool()` 拿到的是當下時間，那是另一則訊息。
        one = self.replayable(self.owner("第一句"), "u-1")
        tool = self.replayable(self.ai_tool("Read"), "u-2")
        self.write(one, tool)
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 1)
        self.assertEqual(len(self.tk.strands[0].dots), 1)
        self.assertEqual(self.tk.strands[0].dots[0].count, 1)

        # 壓縮前的重播：一模一樣的兩筆又寫一次。
        self.write(one, tool)
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 1, "重播開出了一條她沒講過的線")
        self.assertEqual(len(self.tk.strands[0].dots), 1)
        # 【這一條是守備的重點】`_add_dot` 會把連續同名的點併成一顆並
        # 加 count，所以「點的個數沒變」擋不住重複計數 —— 第一版就是
        # 只斷言了個數，重播照樣把 count 推到 2 而測試全綠。
        self.assertEqual(self.tk.strands[0].dots[0].count, 1,
                         "重播的點被併進去多數了一次")
        self.assertEqual(self.tk.replayed, 2)

    def test_replayed_dots_do_not_drag_time_backwards(self):
        """重播那一批帶著舊時間戳，會讓點的時間往回跳。

        `fced45b5` 第 80 輪實測：9 顆點的時間比自己那條線的起點
        還早 4530 秒。`gaps()` 不排序 marks，所以那是負的區段。
        """
        # 那顆舊點第一次出現的時候是**合理的** —— 它在自己那條舊線上。
        # 不先鋪這一段的話，第一次寫入就已經是「點早於起點」，
        # 驗到的是造資料造錯，不是重播。
        old = self.replayable(self.ai_tool("Edit", tid="e1", dt=-4530.0), "u-old")
        self.write(self.replayable(self.owner("舊的一輪", dt=-4600.0), "u-s0"),
                   old)
        self.tk.poll()
        self.assertEqual(len(self.tk.strands[0].dots), 1)

        self.write(self.replayable(self.owner("下一輪", dt=10.0), "u-s2"),
                   old)                       # 重播那一顆舊點
        self.tk.poll()
        cur = self.tk.strands[-1]
        self.assertEqual([d.at for d in cur.dots], [],
                         "舊時間戳的重播點被釘到新的那條線上了")
        for s in self.tk.strands:
            for d in s.dots:
                self.assertGreaterEqual(
                    d.at, s.started_at, "點的時間早於自己那條線的起點")

    def test_the_same_uuid_with_different_content_is_not_swallowed(self):
        """指紋不同就不是重播。不認識的東西不准靜默吞掉。"""
        a = self.replayable(self.owner("原本這句"), "u-x")
        b = self.replayable(self.owner("換了內容"), "u-x")
        self.write(a, b)
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 2)
        self.assertEqual(self.tk.replayed, 0)

    def test_records_without_uuid_are_never_deduped(self):
        """`type=mode` 這種沒有 uuid 的記錄照常處理，兩筆就是兩筆。

        【2026-09-19 審讀修掉的恆真】第一版寫 `self.owner("一")` 與
        `self.owner("二")`，兩筆內容不同，任何實作都不會把它們當重播，
        把 `_replay_seen` 的 uuid 守門整段拿掉照樣綠。要驗的是
        「沒有 uuid 就不准去重」，所以要餵一模一樣的兩筆（同一個
        dict 寫兩次，不要現叫兩次 `owner()`，那會拿到兩個時間戳）：
        守門在的時候兩筆都算，守門被拿掉的時候第二筆會被
        `_seen[None]` 吞掉，這條才會紅。
        """
        same = self.owner("同一句")
        self.write(same, same)
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 2)
        self.assertEqual(self.tk.replayed, 0)


class TestLineSeparatorInsideAMessage(Case):
    """訊息內文裡的 U+2028 不是換行。

    2026-09-19 量到的：10 份真實 transcript 的訊息內文含 U+2028。
    `splitlines()` 認它，於是一筆合法 JSON 被切成兩半、兩半都解析失敗，
    整筆消失（合計 20 筆），而且後面每一行的 `line_no` 全部偏移
    （`fced45b5` 偏 460 行）。line_no 是錨的座標，偏掉就指不到東西。
    """

    def test_a_record_containing_u2028_survives(self):
        self.write(self.owner("上半\u2028下半"))
        self.tk.poll()
        self.assertEqual(len(self.tk.strands), 1, "含 U+2028 的那筆被丟掉了")
        self.assertIn("下半", self.tk.strands[0].owner_text)

    def test_line_numbers_stay_aligned_with_the_file(self):
        self.write(self.owner("一"),
                   self.owner("二\u2028還是同一行"),
                   self.owner("三"))
        self.tk.poll()
        real = self.f.read_bytes().count(b"\n")
        self.assertEqual(self.tk.line_no, real, "line_no 跟檔案行數對不上")
        self.assertEqual(self.tk.strands[-1].owner_line, 3)

    def test_polling_twice_does_not_count_an_extra_line(self):
        """chunk 一定以 \n 結尾，切行的最後一格是空的。

        留著它的話每次 poll 都會多數一行，而這條測試是為了那個
        `[:-1]` 存在的 —— 拿掉它，第二次 poll 之後 line_no 就多 1。
        """
        self.write(self.owner("一"))
        self.tk.poll()
        self.write(self.owner("二"))
        self.tk.poll()
        self.assertEqual(self.tk.line_no, self.f.read_bytes().count(b"\n"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
