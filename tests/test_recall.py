#!/usr/bin/env python3
"""recall 的測試。階段 C1。

合成資料，不碰 ~/.claude/projects 底下的真實紀錄，理由同 test_context_meter。

每一條對應一個實際踩過的坑或一個會讓答案變假的失效。特別注意
TestCompactSummaryIsNotUser：把系統塞的摘要當成使用者說的話，
會讓「她說過什麼」這件事整個失真，而這正是本專案要防的事。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import recall  # noqa: E402


def _user(ts: str, text: str, compact_summary: bool = False) -> dict:
    d = {
        "type": "user", "timestamp": ts, "sessionId": "s1",
        "message": {"role": "user", "content": text},
    }
    if compact_summary:
        d["isCompactSummary"] = True
    return d


def _asst(ts: str, blocks: list) -> dict:
    return {
        "type": "assistant", "timestamp": ts, "sessionId": "s1",
        "message": {"role": "assistant", "content": blocks},
    }


def _compact(ts: str) -> dict:
    return {
        "type": "system", "subtype": "compact_boundary", "timestamp": ts,
        "sessionId": "s1",
        "compactMetadata": {"trigger": "auto", "preTokens": 900000,
                            "postTokens": 17000, "cumulativeDroppedTokens": 880000,
                            "durationMs": 1000,
                            "preservedSegment": {"headUuid": "h", "anchorUuid": "a"}},
    }


def _jsonl(rows: list) -> Path:
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    fh.close()
    return Path(fh.name)


class TestSegmentation(unittest.TestCase):
    def test_user_turn_is_the_boundary(self):
        """以 user turn 切段。用 assistant turn 切會把一件事拆成碎片。"""
        p = _jsonl([
            _user("2026-09-01T01:00:00Z", "做 A"),
            _asst("2026-09-01T01:00:10Z", [{"type": "text", "text": "好"}]),
            _asst("2026-09-01T01:00:20Z", [{"type": "text", "text": "做完了"}]),
            _user("2026-09-01T01:01:00Z", "做 B"),
            _asst("2026-09-01T01:01:10Z", [{"type": "text", "text": "好"}]),
        ])
        segs = recall.segment_session(p)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0].user_text, "做 A")
        self.assertIn("做完了", segs[0].asst_text)

    def test_tool_names_are_collected(self):
        p = _jsonl([
            _user("2026-09-01T01:00:00Z", "查一下"),
            _asst("2026-09-01T01:00:10Z", [
                {"type": "text", "text": "查"},
                {"type": "tool_use", "name": "Bash", "input": {}},
                {"type": "tool_use", "name": "Read", "input": {}},
            ]),
        ])
        segs = recall.segment_session(p)
        self.assertEqual(sorted(segs[0].tools), ["Bash", "Read"])

    def test_thinking_is_not_indexed(self):
        """思考是過程不是結論，量大會淹掉真正的內容。"""
        p = _jsonl([
            _user("2026-09-01T01:00:00Z", "問題"),
            _asst("2026-09-01T01:00:10Z", [
                {"type": "thinking", "thinking": "獨角獸魔法秘密關鍵字"},
                {"type": "text", "text": "答案"},
            ]),
        ])
        segs = recall.segment_session(p)
        self.assertIn("答案", segs[0].asst_text)
        self.assertNotIn("獨角獸", segs[0].text)


class TestCompactSummaryIsNotUser(unittest.TestCase):
    """壓縮摘要是系統塞的，不是使用者說的話。

    把它當成使用者訊息，「她說過什麼」就整個失真：查她的原話會查到
    AI 自己寫的摘要，而摘要正是可能已經飄掉的那份東西。
    """

    def test_compact_summary_does_not_become_a_user_segment(self):
        p = _jsonl([
            _user("2026-09-01T01:00:00Z", "真的使用者說的話"),
            _asst("2026-09-01T01:00:10Z", [{"type": "text", "text": "回應"}]),
            _compact("2026-09-01T02:00:00Z"),
            _user("2026-09-01T02:00:01Z", "這是壓縮摘要不是她說的", compact_summary=True),
            _asst("2026-09-01T02:00:10Z", [{"type": "text", "text": "續作"}]),
        ])
        segs = recall.segment_session(p)
        users = [s.user_text for s in segs if s.user_text]
        self.assertIn("真的使用者說的話", users)
        self.assertNotIn("這是壓縮摘要不是她說的", " ".join(users))


class TestClassification(unittest.TestCase):
    def test_correction_needs_user_role_and_short_length(self):
        """糾正必須是使用者說的、而且短。

        長篇通常是在交代需求不是糾正。詞表只當觸發器，
        結構條件才定生死 —— 跟 Code-Duo 的 check_honesty 同一個做法。
        """
        short = _jsonl([_user("2026-09-01T01:00:00Z", "不對，你搞錯了")])
        self.assertEqual(recall.segment_session(short)[0].kind, "correction_candidate")

        long_text = "你搞錯了。" + "然後我要你做的是一整套東西，" * 40
        self.assertGreater(len(long_text), 400)
        longer = _jsonl([_user("2026-09-01T01:00:00Z", long_text)])
        self.assertNotEqual(recall.segment_session(longer)[0].kind, "correction_candidate")

    def test_assistant_saying_correction_words_is_not_a_correction(self):
        """AI 自己說「不對」不算糾正。糾正只能由使用者發出。"""
        p = _jsonl([
            _user("2026-09-01T01:00:00Z", "跑一下"),
            _asst("2026-09-01T01:00:10Z", [{"type": "text", "text": "不對，錯了，我搞錯了"}]),
        ])
        self.assertNotEqual(recall.segment_session(p)[0].kind, "correction_candidate")

    def test_paths_are_extracted(self):
        p = _jsonl([
            _user("2026-09-01T01:00:00Z", "看 apps/forseti-cli/recall.py 跟 soul.md"),
        ])
        paths = recall.segment_session(p)[0].paths
        self.assertIn("apps/forseti-cli/recall.py", paths)
        self.assertIn("soul.md", paths)


class TestDropped(unittest.TestCase):
    def test_segments_before_compaction_are_marked_dropped(self):
        """壓縮之前的段落視為已被丟出 context。保守估計，寧可多撈不要漏。"""
        p = _jsonl([
            _user("2026-09-01T01:00:00Z", "壓縮前說的"),
            _compact("2026-09-01T02:00:00Z"),
            _user("2026-09-01T03:00:00Z", "壓縮後說的"),
        ])
        segs = recall.segment_session(p)
        by_text = {s.user_text: s for s in segs}
        self.assertTrue(by_text["壓縮前說的"].dropped)
        self.assertFalse(by_text["壓縮後說的"].dropped)

    def test_no_compaction_means_nothing_dropped(self):
        p = _jsonl([_user("2026-09-01T01:00:00Z", "沒被壓縮過")])
        self.assertFalse(recall.segment_session(p)[0].dropped)


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db = Path(self.tmpdir) / "t.db"
        root = Path(self.tmpdir) / "projects" / "proj"
        root.mkdir(parents=True)

        rows = [
            _user("2026-07-09T08:40:00Z", "我要你做切換四個視窗，因為開發程式需要四個各自分工"),
            _asst("2026-07-09T08:40:10Z", [{"type": "text", "text": "四個視窗分工做好了 app.py"}]),
            _compact("2026-08-01T00:00:00Z"),
            _user("2026-08-26T03:15:00Z", "不對，角色不要寫死四個，要可以自由命名 app.py"),
            _asst("2026-08-26T03:15:10Z", [{"type": "text", "text": "改成自由命名"}]),
            _user("2026-09-01T01:00:00Z", "點名板是為了解決 session ID 每次都變的問題"),
            _asst("2026-09-01T01:00:10Z", [{"type": "text", "text": "了解"}]),
        ]
        (root / "s1.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

        recall.build_index(db=self.db, root=Path(self.tmpdir) / "projects", rebuild=True)

    def test_chinese_query_hits(self):
        hits = recall.search("點名板", db=self.db)
        self.assertTrue(hits)
        self.assertIn("點名板", hits[0].snippet)

    def test_two_char_query_falls_back_to_like(self):
        """FTS5 trigram 需要至少三個字元，兩字詞永遠命中不了，要走 LIKE。

        這是實測出來的：查「都變」在 trigram 上回 0 筆。
        """
        hits = recall.search("視窗", db=self.db)
        self.assertTrue(hits, "兩字中文查詢應該仍然查得到")

    def test_dropped_segments_are_boosted(self):
        """被壓縮丟掉的要加權。沒有這一項，索引只是一個比較慢的 grep。"""
        hits = recall.search("四個視窗分工", db=self.db)
        self.assertTrue(hits)
        self.assertTrue(any(h.dropped for h in hits))

    def test_superseded_is_flagged_not_asserted(self):
        """作廢是啟發式的，只說「後面有人動過這個話題」，不說「這個一定錯」。

        七月「四個固定角色」被八月「自由命名」推翻，是真實發生過的事，
        索引要標得出來。
        """
        hits = recall.search("四個視窗分工", db=self.db)
        flagged = [h for h in hits if h.superseded_by]
        self.assertTrue(flagged, "應該標出後面有糾正")

    def test_empty_query_returns_nothing(self):
        self.assertEqual(recall.search("", db=self.db), [])

    def test_exclude_file_removes_self_reference(self):
        """排除當前 session,不然會自我引用污染。

        實測三題全中這個坑:查「為何有點名板」,第一名是主 session
        五分鐘前打的那句「為何有點名板」。當前 session 的內容本來就在
        context 裡,這個系統要找的是它已經沒有的東西。
        """
        target = str(Path(self.tmpdir) / "projects" / "proj" / "s1.jsonl")
        self.assertTrue(recall.search("點名板", db=self.db))
        self.assertEqual(recall.search("點名板", db=self.db, exclude_file=target), [])


class TestDedupe(unittest.TestCase):
    def test_identical_content_collapses_and_counts(self):
        """同一段常在多份 jsonl 各有一份（session 被複製過）。

        實測「如何協調 Code-Duo」時前六名有三組兩兩重複，
        等於一半版面在講同一件事。
        """
        h1 = recall.Hit(1, "t", "work", False, "a.jsonl", 1, 2, "一樣的內容", 5.0)
        h2 = recall.Hit(2, "t", "work", False, "b.jsonl", 1, 2, "一樣的內容", 4.0)
        h3 = recall.Hit(3, "t", "work", False, "c.jsonl", 9, 9, "不同的內容", 3.0)
        out = recall._dedupe([h1, h2, h3])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].copies, 2)


class TestSchemaVersion(unittest.TestCase):
    def test_version_bump_drops_old_index(self):
        """索引是純函數的產物，結構可以大膽改，改了自動重建。

        底氣來自不變量一：原始 jsonl 沒動過。
        """
        tmp = Path(tempfile.mkdtemp()) / "v.db"
        con = recall.connect(tmp)
        con.execute("INSERT INTO segments (session_id,file,ts) VALUES ('x','y','z')")
        con.commit()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM segments").fetchone()[0], 1)
        con.close()

        original = recall.SCHEMA_VERSION
        try:
            recall.SCHEMA_VERSION = original + 1
            con2 = recall.connect(tmp)
            self.assertEqual(con2.execute("SELECT COUNT(*) FROM segments").fetchone()[0], 0)
            con2.close()
        finally:
            recall.SCHEMA_VERSION = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
