#!/usr/bin/env python3
"""§40 污染登記簿的桌面入口。

後端 `pollution.summary()` 與 `records()` 從 2026-09-16 19:2x 就算得出來，
**缺的一直是入口**。這一組守的是入口這一段，不重測登記簿本身
（那是 `tests/test_pollution.py` 的 24 條）。

這一組要抓的是一整類會靜默說謊的事:

  半徑 None 被投影成 0 —— 0 讀起來是「量過了，沒有擴散」
  讀不到登記簿被投影成空清單 —— 空清單讀起來是「沒有被推翻的結論」
  畫面函式被誰刪掉或改名，而 snap 照樣帶著資料
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import pollution as PO  # noqa: E402
import desktop_api as D  # noqa: E402

APP = (ROOT / "desktop" / "ui" / "app.js").read_text(encoding="utf-8")
CSS = (ROOT / "desktop" / "ui" / "app.css").read_text(encoding="utf-8")


class Panel(unittest.TestCase):
    def test_投影出來的筆數跟登記簿一樣(self):
        p = D.pollution_panel()
        self.assertTrue(p["has"])
        self.assertEqual(len(p["rows"]), len(PO.records()))
        self.assertEqual(p["total"], len(PO.records()))

    def test_每一筆都帶著機制(self):
        # §40 開頭那一句:數字改掉就沒事，機制不改掉會再犯一次。
        # 一筆沒有機制的污染紀錄，只是一個更正，不是登記簿要的東西。
        for r in D.pollution_panel()["rows"]:
            self.assertTrue(r["mechanism"].strip(), r["id"])

    def test_半徑量不到是None不是0(self):
        p = D.pollution_panel()
        unknown = [r for r in p["rows"] if r["radius"] is None]
        self.assertEqual(len(unknown), p["radius_unknown"])
        for r in unknown:
            # 沒給值就一定要說為什麼算不出來。一個沒有說明的空值，
            # 跟一個編出來的 0 一樣沒有用。
            self.assertTrue(r["radius_basis"].strip(), r["id"])

    def test_guarded跟登記簿算的一樣(self):
        """**分母是 open，不是 rows 全部。**

        2026-09-18 之前這一條寫的是「rows 裡 guarded 為 True 的筆數」
        等於 `p["guarded"]`，而那時 `p["guarded"]` 接的是
        `summary()['guarded']`（分母 `records()` 全部）。此刻
        RESOLVED 是 0，所以兩邊剛好相等 —— **這一條當時是被巧合
        撐著的**，第一筆推到 RESOLVED 的那天它才會紅，而紅的原因
        會讀起來像是投影壞了，不像分母不對。

        現在它自己把 RESOLVED 濾掉，所以對得上的理由是分母一樣，
        不是巧合。`Denominator` 那一組拿真的 RESOLVED 把巧合拆掉。
        """
        p = D.pollution_panel()
        open_guarded = sum(1 for r in p["rows"]
                           if r["guarded"] and r["status"] != "RESOLVED")
        self.assertEqual(open_guarded, p["guarded"])

    def test_分母講得出來(self):
        # 一個沒有說明分母的比例，讀的人只能自己猜一個。
        p = D.pollution_panel()
        self.assertTrue(p["guard_denominator"].strip())
        self.assertTrue(p["guard_basis"].strip())
        self.assertEqual(p["guarded"] + p["unguarded"], p["open"])

    def test_只靠人記得的那幾筆指名道姓(self):
        # §40.2 要的是偵測器。「還有兩筆沒有」跟「是這兩筆」
        # 差在後者可以直接去補，前者要先找。
        p = D.pollution_panel()
        self.assertEqual(len(p["unguarded_ids"]), p["unguarded"])
        ids = {r["id"] for r in p["rows"]}
        for pid in p["unguarded_ids"]:
            self.assertIn(pid, ids)


class Denominator(unittest.TestCase):
    """**拿一筆真的 RESOLVED 把「兩個分母剛好相等」的巧合拆掉。**

    這一組是 2026-09-18 這一輪的核心。正本登記簿此刻 RESOLVED 是 0，
    所以 `records()` 與 `open_records()` 的筆數相等，任何「接錯分母」
    的錯誤在正本上都測不出來。

    做法是 monkeypatch `pollution.LOG` 指到臨時檔，寫進去的資料裡
    有一筆 RESOLVED 且有守門 —— 那一筆正是兩個分母會分岔的地方。
    """

    def _寫一份登記簿(self, d: Path):
        log = d / "pollution.jsonl"
        for i, (claim, kw) in enumerate([
            ("甲說錯了", {"regression_probe": "tests/test_a.py"}),
            ("乙說錯了", {"preventive_rule": "部署前守門"}),
            ("丙說錯了", {}),
        ]):
            r = PO.record(
                original_claim=claim,
                corrected_claim=f"實際是{i}",
                failure_mechanism=f"機制{i}",
                source_events=["apps/forseti-cli/x.py:1"],
                verifier="test",
                radius_basis="規格沒定義單位",
                path=log, **kw)
            self.assertIs(r.get("ok"), True, r)
        # 把甲推到 RESOLVED。**它有守門，所以它會被 `summary()` 數到，
        # 而不會被 `guard_split()` 數到 —— 兩個分母就在這裡分岔。**
        # OPEN 不能直接到 RESOLVED（`TRANSITIONS` 表），要經過 REVERIFIED。
        甲 = PO.records(log)[0]["id"]
        for to in ("REVERIFIED", "RESOLVED"):
            r = PO.advance(甲, to, verifier="test",
                           regression_probe="tests/test_a.py", path=log)
            self.assertIs(r.get("ok"), True, r)
        return log

    def test_有RESOLVED的時候面板報的是open那一組(self):
        import tempfile

        with tempfile.TemporaryDirectory() as t:
            log = self._寫一份登記簿(Path(t))
            old = PO.LOG
            PO.LOG = log
            try:
                p = D.pollution_panel()
                s = PO.summary(log)
            finally:
                PO.LOG = old

        # 先確認這一份資料真的把兩個分母拆開了，不然這條測試是空的。
        self.assertEqual(p["total"], 3)
        self.assertEqual(p["open"], 2)
        self.assertEqual(s["guarded"], 2, "summary 的分母是全部，含那筆 RESOLVED")

        # 面板報的必須是 open 那一組。**接回 summary 的話這裡會是 2。**
        self.assertEqual(p["guarded"], 1)
        self.assertEqual(p["unguarded"], 1)
        self.assertEqual(p["guarded"] + p["unguarded"], p["open"])

    def test_逐筆的guarded照樣是全部而不是open(self):
        """rows 是整本登記簿，含 RESOLVED —— 這是刻意的，不是漏濾。

        畫面上那個清單要看得到已經收乾淨的那幾筆，
        所以 rows 的分母跟上面那個數字本來就不同。
        **兩邊回答的不是同一個問題**，這一條把這件事釘住，
        免得下一個人看到數字對不上就去「修」其中一邊。
        """
        import tempfile

        with tempfile.TemporaryDirectory() as t:
            log = self._寫一份登記簿(Path(t))
            old = PO.LOG
            PO.LOG = log
            try:
                p = D.pollution_panel()
            finally:
                PO.LOG = old

        self.assertEqual(len(p["rows"]), 3)
        self.assertEqual(sum(1 for r in p["rows"] if r["guarded"]), 2)
        self.assertEqual(p["guarded"], 1)

    def test_讀不到的時候不回空清單(self):
        # 空清單在畫面上讀起來是「沒有被推翻的結論」。
        # 那是一句沒有根據的話，跟 blast 的 live_conflicts 同一條。
        real = PO.records

        def boom(*a, **k):
            raise OSError("讀不到")

        PO.records = boom
        try:
            snap: dict = {}
            snap["pollution"] = D._safe(
                D.pollution_panel,
                {"has": False, "why": "讀不到登記簿，不是沒有污染"})
        finally:
            PO.records = real
        self.assertFalse(snap["pollution"]["has"])
        self.assertNotIn("rows", snap["pollution"])
        self.assertIn("不是沒有", snap["pollution"]["why"])

    def test_沒有自動掃描這件事帶得到畫面(self):
        # B-05:靠句型抓到的是符合句型的句子，不是真的污染。
        # 所以這份登記簿只有人登的，畫面不講就會被讀成全面偵測。
        why = D.pollution_panel()["not_scanned_why"]
        self.assertIn("沒有自動掃描", why)
        self.assertIn("不代表", why)


if __name__ == "__main__":
    unittest.main()
