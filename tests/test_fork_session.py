#!/usr/bin/env python3
"""中途 fork。守的是「fork 出來的 session 不准從一開始就說謊」。

owner 2026-09-11 要的形狀：從紅色之前那一節 fork，任務接著跑。
`clean fork` 在三份規格都出現（F05 §5、F08 §4、spec-v2.0 §17）
而實作完全沒有，這是第一版。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
import uuid as _uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "fork_session", REPO / "tools" / "fork-session.py")
FK = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = FK
spec.loader.exec_module(FK)


class Case(unittest.TestCase):
    """造一份小 transcript：header + 六輪對話，uuid 串成一條鏈。"""

    def setUp(self):
        self.box = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.box, ignore_errors=True))
        self.src = self.box / "orig.jsonl"
        self.sid = "OLD-SESSION"
        rows = [
            {"type": "bridge-session", "sessionId": self.sid,
             "bridgeSessionId": self.sid},
        ]
        prev = None
        self.uuids = []
        for i in range(1, 7):
            u = f"u{i:02d}"
            self.uuids.append(u)
            rows.append({
                "type": "user" if i % 2 else "assistant",
                "uuid": u, "parentUuid": prev, "sessionId": self.sid,
                "message": {"content": f"第 {i} 則"},
            })
            prev = u
            # 每一則後面插一筆帶狀態的 header
            rows.append({"type": "last-prompt", "sessionId": self.sid,
                         "prompt": f"第 {i} 則當時的 prompt"})
        with self.src.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        self.rows = rows
        self.orig_hash = hashlib.sha256(self.src.read_bytes()).hexdigest()

    def line_of(self, u: str) -> int:
        for i, d, _raw in FK.load(self.src):
            if d and d.get("uuid") == u:
                return i
        raise AssertionError(u)

    def read(self, p: Path) -> list[dict]:
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


class TestItCutsAtTheRightPlace(Case):

    def test_the_last_conversation_row_is_the_cut_point(self):
        info = FK.fork(self.src, self.line_of("u04"))
        rows = self.read(Path(info["dest"]))
        convo = [r for r in rows if r.get("uuid")]
        self.assertEqual(convo[-1]["uuid"], "u04")

    def test_everything_after_the_cut_is_gone(self):
        info = FK.fork(self.src, self.line_of("u04"))
        got = {r["uuid"] for r in self.read(Path(info["dest"])) if r.get("uuid")}
        self.assertEqual(got, {"u01", "u02", "u03", "u04"})
        self.assertNotIn("u05", got)
        self.assertNotIn("u06", got)

    def test_the_whole_ancestor_chain_is_kept(self):
        """不是只留切點那一則，是留整條祖先鏈。

        少了祖先，那個 session resume 之後不知道前面發生過什麼。
        """
        info = FK.fork(self.src, self.line_of("u06"))
        got = {r["uuid"] for r in self.read(Path(info["dest"])) if r.get("uuid")}
        self.assertEqual(got, set(self.uuids))


class TestItDoesNotLieAboutState(Case):
    """這一組是這支工具最重要的部分。"""

    def test_headers_after_the_cut_are_dropped(self):
        """沒有 uuid 的行帶著 session 狀態，不是無害的中繼資料。

        last-prompt 是最後一次的 prompt。全部帶過去，等於把切點之後
        的狀態塞進一個宣稱停在切點的 session ——
        那個 fork 會從一開始就說謊。
        """
        info = FK.fork(self.src, self.line_of("u03"))
        prompts = [r.get("prompt") for r in self.read(Path(info["dest"]))
                   if r.get("type") == "last-prompt"]
        self.assertTrue(prompts)
        for p in prompts:
            self.assertNotIn("第 4 則", p)
            self.assertNotIn("第 5 則", p)
            self.assertNotIn("第 6 則", p)

    def test_every_session_id_is_rewritten(self):
        """殘留一個舊 sessionId，就會有兩份紀錄宣稱自己是同一場對話。"""
        info = FK.fork(self.src, self.line_of("u04"))
        rows = self.read(Path(info["dest"]))
        sids = {r.get("sessionId") for r in rows if r.get("sessionId")}
        self.assertEqual(sids, {info["new_session_id"]})
        self.assertNotIn(self.sid, sids)
        for r in rows:
            if r.get("bridgeSessionId"):
                self.assertEqual(r["bridgeSessionId"], info["new_session_id"])

    def test_the_new_session_id_is_a_real_uuid(self):
        info = FK.fork(self.src, self.line_of("u02"))
        _uuid.UUID(info["new_session_id"])


class TestItNeverTouchesTheOriginal(Case):
    """fork 是建立，不是修改。

    一個會改到原始對話的 fork，等於把「回頭看當時發生什麼」毀掉，
    而那正是 Source Tree 存在的理由。
    """

    def test_the_source_file_is_byte_identical_after(self):
        FK.fork(self.src, self.line_of("u03"))
        self.assertEqual(
            hashlib.sha256(self.src.read_bytes()).hexdigest(), self.orig_hash)

    def test_dry_run_writes_nothing(self):
        before = set(p.name for p in self.box.iterdir())
        info = FK.fork(self.src, self.line_of("u03"), dry_run=True)
        self.assertTrue(info["dry_run"])
        self.assertFalse(Path(info["dest"]).exists())
        self.assertEqual(set(p.name for p in self.box.iterdir()), before)

    def test_the_fork_lands_next_to_the_source(self):
        """Claude Code 靠目錄找 session，放錯地方 resume 就看不到。"""
        info = FK.fork(self.src, self.line_of("u03"))
        self.assertEqual(Path(info["dest"]).parent, self.src.parent)


class TestEdges(Case):

    def test_cutting_at_a_non_conversation_line_falls_back_to_the_previous(self):
        """切在 header 那一行時，往前找最近一個帶 uuid 的節點。

        使用者點的是視覺上的一節，不會知道那一行是不是對話行。
        """
        header_line = self.line_of("u03") + 1
        info = FK.fork(self.src, header_line, dry_run=True)
        self.assertEqual(info["target_uuid"], "u03")

    def test_a_line_before_any_conversation_is_refused(self):
        with self.assertRaises(SystemExit):
            FK.fork(self.src, 1, dry_run=True)

    def test_unparseable_lines_do_not_kill_the_fork(self):
        """丟掉一行看不懂的紀錄，等於在一份要當證據的檔案裡開一個洞。"""
        with self.src.open("a", encoding="utf-8") as fh:
            fh.write("{ 這行壞掉\n")
        info = FK.fork(self.src, self.line_of("u04"), dry_run=True)
        self.assertEqual(info["kept"], 4)

    def test_a_broken_parent_chain_terminates(self):
        """鏈斷掉的時候要停，不能轉不出來。"""
        p = self.box / "broken.jsonl"
        rows = [{"type": "user", "uuid": "a", "parentUuid": "b",
                 "sessionId": "s", "message": {"content": "x"}},
                {"type": "user", "uuid": "b", "parentUuid": "a",
                 "sessionId": "s", "message": {"content": "y"}}]
        with p.open("w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        info = FK.fork(p, 2, dry_run=True)
        self.assertEqual(info["kept"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
