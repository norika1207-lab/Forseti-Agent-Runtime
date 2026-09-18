#!/usr/bin/env python3
"""Claim 的 id 與落地。§5 那一行的 `claim_id`，§6.3 的 VERIFIES / REFUTES
需要的那一端。

這一組守的不是「寫得進檔案」，是三個會被下一輪改掉的設計決定：

一，id 只拿 text / kind / subject 算，不拿會變的欄位，也不拿 `at`。
二，`get()` 回最後一列不是第一列（append-only 加上會變的狀態）。
三，§5 那一行的 `confidence` **刻意沒有對應欄位**，不是漏掉。

每一條都附著它擋的是什麼。擋不到東西的測試不算守備。
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import claims as C  # noqa: E402
import lineage as L  # noqa: E402


def _c(text="我建立了 a.py", kind="file", subject="a.py"):
    return C.Claim(text=text, kind=kind, subject=subject)


class Id(unittest.TestCase):

    def test_同一句話同一個主詞算出同一個id(self):
        self.assertEqual(_c().id, _c().id)

    def test_id前綴是cl(self):
        """跟 `ev-` 分得開。混在一起的話，一條邊的兩端指到哪一個
        登記簿要靠猜。"""
        self.assertTrue(_c().id.startswith("cl-"), _c().id)

    def test_換了主詞就是另一個宣稱(self):
        self.assertNotEqual(_c(subject="a.py").id, _c(subject="b.py").id)

    def test_換了句子就是另一個宣稱(self):
        self.assertNotEqual(_c(text="建立了").id, _c(text="刪掉了").id)

    def test_狀態變了id不變(self):
        """擋的是：把 state 放進雜湊。那樣的話 §6.3 的 VERIFIES 邊
        在宣稱被驗過的那一刻就指到一個不存在的 id。"""
        c = _c()
        before = c.id
        c.require_evidence()
        c.to("VERIFIED", "測試")
        self.assertEqual(c.id, before)
        self.assertNotEqual(c.state, "PROPOSED")

    def test_強度變了id不變(self):
        c = _c()
        before = c.id
        c.raise_strength("E2", "測試")
        self.assertEqual(c.id, before)

    def test_重複次數變了id不變(self):
        c = _c()
        before = c.id
        c.repeat(by="某人")
        self.assertEqual(c.id, before)

    def test_同一句話在兩個時刻說是同一個宣稱(self):
        """擋的是：把 `at` 放進雜湊。

        這個模組已經有 `repeat()` 在處理「同一句話又被說了一次」
        （§7.1 repetition increases social consensus）。`at` 進雜湊的話
        每說一次就多一個 id，跟那支方法的語意直接打架。"""
        a = C.Claim(text="x", kind="file", subject="a.py", at=1000.0)
        b = C.Claim(text="x", kind="file", subject="a.py", at=9999.0)
        self.assertEqual(a.id, b.id)

    def test_傳進來的id不被覆蓋(self):
        """讀回來的那一列要造得回原本那個物件。自動算會蓋掉它。"""
        c = C.Claim(text="x", kind="file", subject="a.py", id="cl-手動指定")
        self.assertEqual(c.id, "cl-手動指定")

    def test_verify走完一輪之後id不變(self):
        """整條生命週期走過一次，不是只在建構那一刻對。"""
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "real.py"
            f.write_text("x = 1\n", encoding="utf-8")
            c = C.Claim(text="我建立了 real.py", kind="file", subject=str(f))
            before = c.id
            C.verify(c, cwd=Path(d))
            self.assertEqual(c.state, "VERIFIED")
            self.assertEqual(c.id, before)


class NotInvented(unittest.TestCase):

    def test_confidence刻意沒有變成欄位(self):
        """§5 第 160 行那一列寫著 `claim_id, statement, subject,
        confidence, status`。四個有對應（id / text / subject / state），
        `confidence` 沒有，而且是刻意的：

        同一份規格第 705 行寫著 `Never use model self-confidence as
        authority or evidence strength`，而全份規格沒有別的地方定義
        claim 的 confidence 要怎麼算。**沒有定義就自己編一個算法填上去
        正是 §8.3 的填空。** 這一條測試的用處是讓下一個看到那一列的人，
        在加欄位之前先撞到這段話。

        `strength`（E0-E4）不是它 —— 那是證據強度，§7.2。"""
        names = {f.name for f in dataclasses.fields(C.Claim)}
        self.assertNotIn("confidence", names)
        self.assertIn("strength", names)

    def test_規格那一列的另外四欄都指得到(self):
        names = {f.name for f in dataclasses.fields(C.Claim)}
        for want in ("id", "text", "subject", "state"):
            self.assertIn(want, names)


class Row(unittest.TestCase):

    def test_契約存的是checks不是物件(self):
        row = _c().to_row()
        self.assertEqual(row["contract"], list(C.FILE_CREATED.checks))
        self.assertEqual(row["contract_kind"], "file")

    def test_沒有契約的宣稱那兩欄是None不是空list(self):
        """空 list 跟「沒有契約」長得一樣，而 §7.3 的整個機制建立在
        這兩件事要分得開（`require_evidence()` 靠它決定擋不擋）。"""
        row = C.Claim(text="x", kind="unextractable", subject="").to_row()
        self.assertIsNone(row["contract"])
        self.assertIsNone(row["contract_kind"])

    def test_整列進得了json(self):
        json.dumps(_c().to_row(), ensure_ascii=False)


class Store(unittest.TestCase):

    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.p = Path(self.d.name) / "claims.jsonl"

    def tearDown(self):
        self.d.cleanup()

    def test_寫得進去也讀得回來(self):
        c = _c()
        r = C.record(c, path=self.p)
        self.assertTrue(r["ok"])
        rows = C.load(self.p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], c.id)
        self.assertEqual(rows[0]["text"], c.text)

    def test_不是Claim就退回不丟例外(self):
        r = C.record({"text": "x"}, path=self.p)
        self.assertFalse(r["ok"])
        self.assertIn("dict", r["why"])
        self.assertFalse(self.p.exists())

    def test_檔案不存在的時候load回空的(self):
        self.assertEqual(C.load(Path(self.d.name) / "沒這個檔.jsonl"), [])

    def test_壞掉的那一行跳過不讓整個檔讀不出來(self):
        self.p.write_text('{"id": "cl-1"}\n這不是 json\n{"id": "cl-2"}\n',
                          encoding="utf-8")
        self.assertEqual([r["id"] for r in C.load(self.p)], ["cl-1", "cl-2"])

    def test_history照順序回同一個id的每一列(self):
        c = _c()
        C.record(c, path=self.p)
        c.require_evidence()
        C.record(c, path=self.p)
        h = C.history(c.id, path=self.p)
        self.assertEqual([r["state"] for r in h],
                         ["PROPOSED", "EVIDENCE_REQUIRED"])

    def test_get回最後一列不是第一列(self):
        """擋的是：回第一列。那樣的話一個已經被 REFUTED 的宣稱
        會永遠回報 PROPOSED —— 一個看起來還在等證據的假。"""
        c = _c()
        C.record(c, path=self.p)
        c.require_evidence()
        c.to("REFUTED", "測試")
        C.record(c, path=self.p)
        self.assertEqual(C.get(c.id, path=self.p)["state"], "REFUTED")

    def test_get對不存在的id回None(self):
        self.assertIsNone(C.get("cl-沒有這個", path=self.p))

    def test_別人的id不會被history撈進來(self):
        a, b = _c(subject="a.py"), _c(subject="b.py")
        C.record(a, path=self.p)
        C.record(b, path=self.p)
        self.assertEqual(len(C.history(a.id, path=self.p)), 1)

    def test_同一個宣稱改兩次只算一個宣稱但三列(self):
        """列數與宣稱數是兩個數字。合成一個的話，「三個宣稱」跟
        「一個宣稱被改了三次」在畫面上長得一樣。"""
        c = _c()
        for _ in range(3):
            C.record(c, path=self.p)
        rows = C.load(self.p)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len({r["id"] for r in rows}), 1)


class Summary(unittest.TestCase):

    def test_列數與宣稱數分開算而且照最後那一列算狀態(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / ".forseti").mkdir()
            p = C.log_path(repo)
            a = _c(subject="a.py")
            C.record(a, path=p)
            a.require_evidence()
            a.to("REFUTED", "測試")
            C.record(a, path=p)
            C.record(_c(subject="b.py"), path=p)
            s = C.store_summary(repo)
            self.assertEqual(s["rows"], 3)
            self.assertEqual(s["claims"], 2)
            self.assertEqual(s["by_state"], {"REFUTED": 1, "PROPOSED": 1})

    def test_空的時候不是錯是零(self):
        with tempfile.TemporaryDirectory() as d:
            s = C.store_summary(Path(d))
            self.assertEqual((s["rows"], s["claims"]), (0, 0))

    def test_預設落在控制目錄底下(self):
        self.assertEqual(C.log_path().parent.name, ".forseti")
        self.assertEqual(C.log_path().name, "claims.jsonl")


class LineageEnd(unittest.TestCase):
    """§6.3 那一端。這一組是這一輪存在的理由 —— 上面那些都是手段。"""

    def test_有列的時候claim那一端指得到(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / ".forseti").mkdir()
            C.record(_c(), path=C.log_path(repo))
            r = L._kind_claim(repo)
            self.assertEqual(r["status"], "ADDRESSABLE")
            self.assertEqual(r["n"], 1)

    def test_沒有列的時候是NO_INSTANCES不是NOT_ADDRESSABLE(self):
        """兩者差的是下一個人要做什麼：一個去寫模組，一個去登一筆。

        2026-09-18 之前這裡回的是 NOT_ADDRESSABLE，理由是
        「Claim 這個 dataclass 沒有 id 欄位」。那句話現在是假的。"""
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / ".forseti").mkdir()
            r = L._kind_claim(repo)
            self.assertEqual(r["status"], "NO_INSTANCES")
            self.assertEqual(r["n"], 0)
            self.assertNotIn("沒有 id 欄位", r["why"])

    def test_VERIFIES與REFUTES兩端指的是evidence與claim(self):
        """釘住這一輪做的是哪一端。§6.3 原文 `evidence -> claim`。"""
        self.assertEqual(L.EDGE_ENDPOINTS["VERIFIES"], ("evidence", "claim"))
        self.assertEqual(L.EDGE_ENDPOINTS["REFUTES"], ("evidence", "claim"))


if __name__ == "__main__":
    unittest.main()
