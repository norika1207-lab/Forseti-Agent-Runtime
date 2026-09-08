#!/usr/bin/env python3
"""context_meter 的測試。階段 C0。

一律用合成的 jsonl，不碰 ~/.claude/projects 底下的真實檔案。
兩個理由：真實檔案會變，測試就不可重現；而且那裡面是使用者的工作紀錄，
測試不該讀它。

每一條測試都對應一個實際踩過或差點踩到的坑，測試名字就寫那個坑。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import context_meter as cm  # noqa: E402


def _asst(ts: str, rid: str, inp: int, cache_read: int, cache_write: int, out: int = 10) -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "requestId": rid,
        "sessionId": "test-session",
        "cwd": "/tmp/x",
        "message": {
            "role": "assistant",
            "id": "msg_" + rid,
            "usage": {
                "input_tokens": inp,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
                "output_tokens": out,
            },
        },
    }


def _compact(ts: str, pre: int, post: int, dropped: int, ms: int) -> dict:
    return {
        "type": "system",
        "subtype": "compact_boundary",
        "timestamp": ts,
        "sessionId": "test-session",
        "content": "Conversation compacted",
        "compactMetadata": {
            "trigger": "auto",
            "preTokens": pre,
            "postTokens": post,
            "cumulativeDroppedTokens": dropped,
            "durationMs": ms,
            "preservedSegment": {"headUuid": "head-abc", "anchorUuid": "anchor-xyz"},
        },
    }


def _write(rows: list) -> Path:
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for r in rows:
        fh.write(json.dumps(r if isinstance(r, dict) else r) + "\n" if isinstance(r, dict) else r + "\n")
    fh.close()
    return Path(fh.name)


class TestOccupancy(unittest.TestCase):
    def test_three_fields_are_summed(self):
        """佔用是三個欄位相加，不是只看 input_tokens。

        本 session 實測 input=2、cache_read=129,584。只看 input 會少報六萬倍。
        """
        p = _write([_asst("2026-09-08T01:00:00.000Z", "r1", 2, 100_000, 3_000)])
        m = cm.read_session(p)
        self.assertEqual(m.current, 103_002)

    def test_peak_is_an_observation_not_a_limit(self):
        """peak 是觀察到的最高點，不是 context 上限。

        這條測的是語意：它必須等於實際出現過的最大值，不能是任何
        推估出來的上限。報一個推估的上限會讓人以為系統知道還剩多少。
        """
        p = _write([
            _asst("2026-09-08T01:00:00.000Z", "r1", 0, 50_000, 0),
            _asst("2026-09-08T01:01:00.000Z", "r2", 0, 90_000, 0),
            _asst("2026-09-08T01:02:00.000Z", "r3", 0, 70_000, 0),
        ])
        m = cm.read_session(p)
        self.assertEqual(m.peak, 90_000)
        self.assertEqual(m.current, 70_000)


class TestDeduplication(unittest.TestCase):
    def test_same_request_counted_once(self):
        """一次回應會拆成多行(apiBlockIndex)，usage 相同。

        不去重的話同一次請求被算好幾次，趨勢圖就是假的。
        """
        rows = [_asst("2026-09-08T01:00:00.000Z", "r1", 0, 10_000, 0) for _ in range(4)]
        rows.append(_asst("2026-09-08T01:00:05.000Z", "r2", 0, 12_000, 0))
        m = cm.read_session(_write(rows))
        self.assertEqual(len(m.turns), 2)


class TestOrdering(unittest.TestCase):
    def test_current_is_latest_by_time_not_last_line(self):
        """檔案行序不保證等於時間序，本 session 實測就不相等。

        「當前佔用」的定義是時間最新的那一次，不是檔案最後一行。
        """
        p = _write([
            _asst("2026-09-08T03:00:00.000Z", "r3", 0, 30_000, 0),
            _asst("2026-09-08T01:00:00.000Z", "r1", 0, 10_000, 0),
            _asst("2026-09-08T02:00:00.000Z", "r2", 0, 20_000, 0),
        ])
        m = cm.read_session(p)
        self.assertEqual(m.current, 30_000)
        self.assertEqual([t.occupancy for t in m.turns], [10_000, 20_000, 30_000])


class TestCompaction(unittest.TestCase):
    def setUp(self):
        self.p = _write([
            _asst("2026-09-08T01:00:00.000Z", "r1", 0, 900_000, 0),
            _compact("2026-09-08T02:00:00.000Z", 997_325, 17_472, 979_853, 178_851),
            _asst("2026-09-08T03:00:00.000Z", "r2", 0, 20_000, 0),
        ])
        self.m = cm.read_session(self.p)

    def test_numbers_come_from_metadata_not_inference(self):
        """壓縮有明確標記，數字直接讀，不靠佔用驟降推測。"""
        self.assertEqual(len(self.m.compactions), 1)
        c = self.m.compactions[0]
        self.assertEqual(c.pre, 997_325)
        self.assertEqual(c.post, 17_472)
        self.assertEqual(c.dropped, 979_853)
        self.assertEqual(c.trigger, "auto")

    def test_preserved_segment_is_captured(self):
        """保留段的錨點要留著，被丟掉的部分靠它定位。

        這是 C1 索引層的入口:知道保留了哪一段,才知道丟了哪一段。
        """
        self.assertEqual(self.m.compactions[0].anchor_uuid, "anchor-xyz")

    def test_compact_line_is_not_counted_as_a_turn(self):
        self.assertEqual(len(self.m.turns), 2)

    def test_spark_marks_the_compaction(self):
        self.assertIn("▼", cm._spark(self.m, 20))


class TestTimezone(unittest.TestCase):
    def test_utc_is_converted_to_local(self):
        """jsonl 存 UTC。直接印會差八小時。

        2026-09-08 寫這個模組時我自己被騙了一次:看到 13:52 以為是未來時間,
        去查了半天以為排序壞了,實際上那是 UTC,本地 21:52。
        """
        from datetime import datetime, timezone
        ts = "2026-09-08T13:52:31.890Z"
        expect = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
        self.assertEqual(cm._hhmm(ts), expect)

    def test_garbage_timestamp_does_not_raise(self):
        self.assertIsInstance(cm._hhmm("not-a-time"), str)
        self.assertIsInstance(cm._hhmm(""), str)


class TestRobustness(unittest.TestCase):
    def test_broken_lines_are_counted_not_fatal(self):
        """一行壞資料不該炸掉整份。使用者的紀錄裡什麼都有。"""
        fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        fh.write(json.dumps(_asst("2026-09-08T01:00:00.000Z", "r1", 0, 5_000, 0)) + "\n")
        fh.write("{ this is not json\n")
        fh.write("[1,2,3]\n")
        fh.write("\n")
        fh.write(json.dumps(_asst("2026-09-08T01:00:10.000Z", "r2", 0, 6_000, 0)) + "\n")
        fh.close()
        m = cm.read_session(Path(fh.name))
        self.assertEqual(len(m.turns), 2)
        self.assertEqual(m.bad_lines, 2)

    def test_missing_file_returns_empty_not_crash(self):
        m = cm.read_session(Path("/nonexistent/nope.jsonl"))
        self.assertEqual(m.turns, [])
        self.assertEqual(m.current, 0)

    def test_no_usage_messages_reports_zero(self):
        p = _write([{"type": "user", "timestamp": "2026-09-08T01:00:00.000Z", "message": {"role": "user"}}])
        m = cm.read_session(p)
        self.assertEqual(m.current, 0)
        self.assertEqual(m.peak, 0)


class TestOutput(unittest.TestCase):
    def test_report_says_it_cannot_report_percentage(self):
        """上限不在資料裡,所以不准報百分比。

        報一個推估的百分比會讓人以為系統知道上限,那是騙人。
        """
        import io
        from contextlib import redirect_stdout
        p = _write([_asst("2026-09-08T01:00:00.000Z", "r1", 0, 5_000, 0),
                    _asst("2026-09-08T01:00:10.000Z", "r2", 0, 6_000, 0)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            cm.report_one(cm.read_session(p))
        out = buf.getvalue()
        self.assertIn("不報百分比", out)
        self.assertNotIn("%", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
