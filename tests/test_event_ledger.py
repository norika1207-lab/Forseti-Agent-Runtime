#!/usr/bin/env python3
"""Event Ledger 的測試。階段 1。

**核心的三條是出口條件**（`docs/build-plan.md:327`）：

    殺掉程序再開，事件不掉。
    同一份帳本重播兩次，結果逐位元組相同。
    Claude Code 的 tool 事件、檔案事件、程序事件都進得來。

第一條用真的 SIGKILL 測，不是模擬。一個「假裝程序死了」的測試
證明不了資料真的落地了。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

APPS = Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
sys.path.insert(0, str(APPS))

import event_ledger as E  # noqa: E402


def raw(provider="claude-code", kind="PostToolUse", payload=None, ts=None):
    return E.RawEvent(provider=provider, provider_event_type=kind,
                      timestamp=ts if ts is not None else 1700000000.0,
                      payload=payload if payload is not None else {"a": 1})


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.led = E.EventLedger(jsonl=self.tmp / "el.jsonl",
                                 index=self.tmp / "idx.db")

    def tearDown(self):
        self.led.close()


class TestExitConditions(Case):
    """三條出口條件。"""

    def test_replaying_twice_is_byte_identical(self):
        """同一份帳本重播兩次，逐位元組相同。"""
        for i in range(5):
            r = raw(payload={"i": i, "z": "後面", "a": "前面"}, ts=1700000000.0 + i)
            self.led.append(r, E.NormalizedEvent(raw_event_id=r.id, type="TOOL_CALL"))

        a, b = self.led.replay(), self.led.replay()
        self.assertEqual(a, b)
        self.assertEqual(self.led.digest(), self.led.digest())

        # 換一個 EventLedger 實例讀同一個檔案，結果也要一樣 ——
        # 決定性不能依賴行程內的狀態。
        other = E.EventLedger(jsonl=self.led.jsonl, index=self.tmp / "idx2.db")
        self.assertEqual(other.replay(), a)
        other.close()

    def test_key_order_in_payload_does_not_change_the_digest(self):
        """同樣的內容、不同的寫入順序，指紋要一樣。

        這是「逐位元組相同」的實際威脅：dict 的欄位順序會隨建構方式變，
        沒有 canonical 化的話同一件事會產生兩個指紋。
        """
        l1 = E.EventLedger(jsonl=self.tmp / "a.jsonl", index=self.tmp / "a.db")
        l2 = E.EventLedger(jsonl=self.tmp / "b.jsonl", index=self.tmp / "b.db")
        l1.append(raw(payload={"x": 1, "y": 2}))
        l2.append(raw(payload={"y": 2, "x": 1}))
        self.assertEqual(l1.digest(), l2.digest())
        l1.close()
        l2.close()

    def test_events_survive_sigkill(self):
        """殺掉程序再開，事件不掉。真的 SIGKILL，不是模擬。

        子程序寫五筆之後把自己 SIGKILL 掉（不是 sys.exit，那會跑
        清理程序）。父程序再開同一個檔案，五筆都要在。
        """
        jsonl = self.tmp / "kill.jsonl"
        script = f"""
import sys, os, signal
sys.path.insert(0, {str(APPS)!r})
import event_ledger as E
from pathlib import Path
led = E.EventLedger(jsonl=Path({str(jsonl)!r}), index=Path({str(self.tmp / 'k.db')!r}))
for i in range(5):
    r = E.RawEvent(provider='claude-code', provider_event_type='PostToolUse',
                   timestamp=1700000000.0 + i, payload={{'i': i}})
    led.append(r, E.NormalizedEvent(raw_event_id=r.id, type='FILE_WRITE'))
os.kill(os.getpid(), signal.SIGKILL)
"""
        p = subprocess.run([sys.executable, "-c", script], capture_output=True)
        self.assertEqual(p.returncode, -signal.SIGKILL,
                         f"子程序應該死於 SIGKILL，stderr={p.stderr[:300]}")

        after = E.EventLedger(jsonl=jsonl, index=self.tmp / "after.db")
        self.assertEqual(len(after.read_all()), 5, "被 SIGKILL 之後五筆都要還在")
        after.close()

    def test_the_three_kinds_of_claude_code_events_fit(self):
        """tool 事件、檔案事件、程序事件都進得來。

        用 Claude Code 真實會產生的形狀試：PreToolUse/PostToolUse 的
        工具呼叫、Write 造成的檔案變更、session 起訖。
        """
        cases = [
            ("PreToolUse", {"tool_name": "Bash", "command": "ls"}, "TOOL_CALL"),
            ("PostToolUse", {"tool_name": "Write", "path": "a.txt"}, "FILE_WRITE"),
            ("SessionStart", {"session_id": "abc"}, "PROCESS_START"),
        ]
        for kind, payload, ntype in cases:
            r = raw(kind=kind, payload=payload, ts=time.time())
            self.led.append(r, E.NormalizedEvent(
                raw_event_id=r.id, type=ntype, session_id="abc"))

        got = self.led.read_all()
        self.assertEqual(len(got), 3)
        cats = {E.TYPE_TO_CATEGORY[g["norm"]["type"]] for g in got}
        self.assertEqual(cats, {"Tool", "Artifact", "Runtime"})


class TestDualRepresentation(Case):
    """v5.0 §6.1：正規化不得摧毀原始證據。"""

    def test_raw_is_frozen(self):
        """raw 改不動。那句規格的機制形式，不是靠紀律。"""
        r = raw()
        with self.assertRaises(Exception):
            r.provider = "別人"

    def test_normalized_must_point_back_to_its_raw(self):
        """回頭路斷了就等於摧毀原始證據。"""
        r = raw()
        wrong = E.NormalizedEvent(raw_event_id="不存在的 id", type="TOOL_CALL")
        with self.assertRaises(E.LedgerError):
            self.led.append(r, wrong)

    def test_raw_without_provider_is_refused(self):
        """沒有 provider 的不是 provider 事件。

        那兩個欄位正是 Event Ledger 跟 Task Ledger 的分野（ADR-008）。
        """
        with self.assertRaises(E.LedgerError):
            E.RawEvent(provider="", provider_event_type="X",
                       timestamp=1.0, payload={})

    def test_same_payload_same_id(self):
        """id 由內容決定，不用 uuid。重播要決定性。"""
        self.assertEqual(raw().id, raw().id)
        self.assertNotEqual(raw(payload={"a": 1}).id, raw(payload={"a": 2}).id)


class TestCanonicalTypes(Case):
    """v5.0 §6.2 的八大類。"""

    def test_only_canonical_types_are_accepted(self):
        for t in ("TOOL_CALL", "FILE_WRITE", "CHECKPOINT", "POLICY_BLOCK"):
            E.NormalizedEvent(raw_event_id="x", type=t)
        with self.assertRaises(E.LedgerError):
            E.NormalizedEvent(raw_event_id="x", type="差不多是個工具呼叫")

    def test_every_type_belongs_to_exactly_one_category(self):
        """一個 type 落在兩類會讓分類失去意義。"""
        seen = {}
        for cat, types in E.TYPES.items():
            for t in types:
                self.assertNotIn(t, seen, f"{t} 同時屬於 {seen.get(t)} 與 {cat}")
                seen[t] = cat
        self.assertEqual(set(E.TYPES), set(E.CATEGORIES))


class TestIndexIsRebuildable(Case):
    """索引不是真相，正本才是。"""

    def test_reindex_from_scratch(self):
        for i in range(3):
            r = raw(payload={"i": i}, ts=1700000000.0 + i)
            self.led.append(r, E.NormalizedEvent(
                raw_event_id=r.id, type="TOOL_RESULT", session_id="s1"))
        stat = self.led.reindex()
        self.assertEqual(stat["raw"], 3)
        self.assertEqual(stat["normalized"], 3)

        con = self.led._connect()
        n = con.execute("SELECT COUNT(*) FROM events WHERE session_id='s1'").fetchone()[0]
        self.assertEqual(n, 3)
        cat = con.execute("SELECT DISTINCT category FROM events").fetchone()[0]
        self.assertEqual(cat, "Tool")

    def test_deleting_the_index_loses_nothing(self):
        """砍掉索引，正本還在，重建之後一模一樣。"""
        r = raw()
        self.led.append(r, E.NormalizedEvent(raw_event_id=r.id, type="TOOL_CALL"))
        before = self.led.digest()

        self.led.reindex()
        self.led.close()
        (self.tmp / "idx.db").unlink()

        again = E.EventLedger(jsonl=self.tmp / "el.jsonl", index=self.tmp / "idx.db")
        self.assertEqual(again.digest(), before)
        self.assertEqual(again.reindex()["raw"], 1)
        again.close()

    def test_reindex_is_idempotent(self):
        r = raw()
        self.led.append(r, E.NormalizedEvent(raw_event_id=r.id, type="TOOL_CALL"))
        self.led.reindex()
        self.led.reindex()
        con = self.led._connect()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM raw_events").fetchone()[0], 1)


class TestCorruptionIsLoud(Case):
    def test_a_broken_line_reports_its_position(self):
        """壞掉的行不安靜跳過。

        一個被略過的事件，效果跟從來沒發生過一樣 —— 那正是這本帳要防的。
        """
        self.led.append(raw())
        with self.led.jsonl.open("a", encoding="utf-8") as f:
            f.write("{這不是 JSON\n")
        with self.assertRaises(E.LedgerError) as ctx:
            self.led.read_all()
        self.assertIn("第 2 行", str(ctx.exception))

    def test_append_only_has_no_edit_or_delete_entry_point(self):
        """append-only 不是靠紀律，是靠沒有那個入口。"""
        for forbidden in ("update", "delete", "edit", "remove", "truncate"):
            self.assertFalse(
                hasattr(self.led, forbidden),
                f"EventLedger 不該有 {forbidden}()，append-only 要靠沒有入口")



class TestEvidenceTravelsWithItsEvent(Case):
    """Evidence Receipt 跟它所屬的事件在同一筆（build-plan:323）。

    為什麼不另開一種事件：evidence 不是一件「發生的事」，是某件事在
    那一刻的證據。拆成兩筆的話，它們之間的關聯要靠時間或 id 去拼，
    而拼接是會錯的 —— 尤其在併發寫入的時候。
    """

    def test_evidence_survives_a_round_trip_through_the_index(self):
        """寫進去、重建索引、再查出來，證據要還在。"""
        r = raw(payload={"tool_name": "Write", "path": "a.txt"})
        ev = {"byteSize": 42, "contentHash": "deadbeef", "existence": True,
              "captureMethod": "PostToolUse:Write", "exitCode": None}
        self.led.append(r, E.NormalizedEvent(
            raw_event_id=r.id, type="FILE_WRITE", session_id="s1",
            result="42 bytes", metadata={"evidence": ev}))
        self.led.reindex()

        con = self.led._connect()
        row = con.execute(
            "SELECT result, metadata FROM events WHERE session_id='s1'").fetchone()
        self.assertEqual(row[0], "42 bytes")
        got = json.loads(row[1])["evidence"]
        self.assertEqual(got["byteSize"], 42)
        self.assertEqual(got["contentHash"], "deadbeef")

    def test_unknown_existence_is_preserved_not_coerced(self):
        """'unknown' 不能在任何一層被轉成 False。

        量不到跟不存在是兩件事。混在一起的話，一個因為權限讀不到的檔案
        會被當成「AI 說做了但沒做」，而那是冤枉它。
        """
        r = raw(payload={"tool_name": "Write"})
        self.led.append(r, E.NormalizedEvent(
            raw_event_id=r.id, type="FILE_WRITE", session_id="s2",
            result="UNKNOWN",
            metadata={"evidence": {"existence": "unknown", "byteSize": None}}))
        self.led.reindex()
        con = self.led._connect()
        meta = json.loads(con.execute(
            "SELECT metadata FROM events WHERE session_id='s2'").fetchone()[0])
        self.assertEqual(meta["evidence"]["existence"], "unknown")
        self.assertIsNot(meta["evidence"]["existence"], False)

    def test_evidence_does_not_break_replay_determinism(self):
        """帶了證據的事件，重播兩次仍然逐位元組相同。

        evidence 是巢狀 dict，而巢狀是 canonical JSON 最容易出錯的地方。
        """
        for i in range(3):
            r = raw(payload={"i": i}, ts=1700000000.0 + i)
            self.led.append(r, E.NormalizedEvent(
                raw_event_id=r.id, type="FILE_WRITE",
                metadata={"evidence": {"z": 1, "a": {"y": None, "x": i}}}))
        self.assertEqual(self.led.replay(), self.led.replay())
        self.assertEqual(self.led.digest(), self.led.digest())

if __name__ == "__main__":
    unittest.main(verbosity=2)
