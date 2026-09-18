#!/usr/bin/env python3
"""§6.3 的 lineage 邊。

這一組守三件事，每一件對應一種會再犯的錯。

一，**兩張表會分開腐爛。** 邊的名字在 `event_ledger.LINEAGE_EDGES`，
兩端的型別在 `lineage.EDGE_ENDPOINTS`，分在兩個檔。有人加一條邊
只改一邊的時候，要有東西紅。

二，**拒收要真的拒收。** `add()` 的價值全在它擋得住什麼。
一個收下錯誤型別的邊、或收下兩端對調的邊的存放層，
比沒有存放層糟 —— 它會讓下游以為每一條邊都合規格。

三，**`readiness()` 的答案要是量出來的。** 這一組不寫死
「六條 ready」那種會隨開發變動的數字，寫死的是**結構**：
每一種端點型別都答得出一個合法狀態、ready 的定義是兩端都
ADDRESSABLE、以及 `count`（磁碟上的邊）跟 `ready_n`（兩端指得到）
是兩個不會被合成一個的數字。

**為什麼不驗「claim 現在是 NOT_ADDRESSABLE」。** 那是此刻的狀態，
哪天有人給 Claim 加 id 它就該變，而那一天這一組不該紅。
驗的是那一支**真的去讀了 dataclass 的欄位**，不是回一個寫死的答案
（`test_claim那一支看的是真的欄位不是寫死的`）。
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import lineage as LN                                   # noqa: E402
import event_ledger as EL                              # noqa: E402


class 規格對齊(unittest.TestCase):

    def test_兩張表的邊名字一模一樣(self):
        self.assertEqual(set(EL.LINEAGE_EDGES), set(LN.EDGE_ENDPOINTS))
        self.assertEqual(set(EL.LINEAGE_EDGES), set(LN.SPEC_TEXT))

    def test_spec_alignment說得出自己對齊(self):
        a = LN.spec_alignment()
        self.assertTrue(a["ok"], a)
        self.assertEqual(a["only_in_ledger"], [])
        self.assertEqual(a["only_here"], [])

    def test_十條不多不少(self):
        """§6.3 就是十條。多一條少一條都代表有人改了規格照抄的部分。"""
        self.assertEqual(len(LN.EDGE_ENDPOINTS), 10)

    def test_每一條的原文都留著而且對得上正規化(self):
        """原文用兩種箭頭，正規化成一個方向。**正規化要可對照。**

        `A <- B` 與 `A -> B` 在原文裡都是「A 的邊名念向 B」，
        所以兩端的兩個名字，不論箭頭哪一邊，都要出現在原文那一行裡。
        """
        for name, (a, b) in LN.EDGE_ENDPOINTS.items():
            text = LN.SPEC_TEXT[name]
            for kind in (a, b):
                # `hypothesis_or_fact` 對到原文的 `hypothesis/fact`，
                # `node` 對到 `downstream node`，`raw_event` 對到 `raw events`。
                probe = {"hypothesis_or_fact": "hypothesis/fact",
                         "node": "node",
                         "raw_event": "raw event"}.get(kind, kind)
                self.assertIn(probe, text,
                              f"{name}：正規化出來的 {kind} 在原文 "
                              f"`{text}` 裡找不到對應")

    def test_edge_types只有一個來源(self):
        """`lineage` 不自己抄一份邊名字。抄一份就會有兩份會分歧的規格。"""
        src = (REPO / "apps" / "forseti-cli" / "lineage.py").read_text(
            encoding="utf-8")
        for name in EL.LINEAGE_EDGES:
            # 邊名字可以出現在 EDGE_ENDPOINTS / SPEC_TEXT 的鍵，
            # 但不可以出現在第三份清單裡。兩份是表，不是抄。
            self.assertLessEqual(src.count(f'"{name}"'), 2,
                                 f"{name} 在 lineage.py 出現超過兩次，"
                                 "很可能長出了第三份清單")


class 拒收(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "lineage.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_不是規格裡的邊型別一律退回(self):
        r = LN.add(type="CAUSES", from_id="a", to_id="b",
                   basis="測試", path=self.p)
        self.assertFalse(r["ok"])
        self.assertIn("不是 §6.3 的邊", r["why"])
        self.assertFalse(self.p.exists(), "退回的邊不可以寫進檔案")

    def test_兩端型別對調要退回(self):
        """`VERIFIES` 是 evidence -> claim。反過來是另一件事。"""
        r = LN.add(type="VERIFIES", from_kind="claim", to_kind="evidence",
                   from_id="c1", to_id="e1", basis="測試", path=self.p)
        self.assertFalse(r["ok"])
        self.assertIn("evidence -> claim", r["why"])

    def test_沒給兩端型別的時候用規格的預設(self):
        r = LN.add(type="SUPERSEDES", from_id="ADR-010", to_id="ADR-002",
                   basis="DECISION_LEDGER 標題行", path=self.p)
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["edge"]["from_kind"], "decision")
        self.assertEqual(r["edge"]["to_kind"], "decision")

    def test_空的id退回(self):
        for a, b in (("", "x"), ("x", ""), ("  ", "x")):
            r = LN.add(type="SUPERSEDES", from_id=a, to_id=b,
                       basis="測試", path=self.p)
            self.assertFalse(r["ok"], (a, b))

    def test_沒有根據的邊退回(self):
        """一條講不出根據的邊，在需要追來源的時候正好沒有用。"""
        r = LN.add(type="SUPERSEDES", from_id="ADR-010", to_id="ADR-002",
                   basis="   ", path=self.p)
        self.assertFalse(r["ok"])
        self.assertIn("basis", r["why"])

    def test_id是內容決定的同一條邊兩次是同一個id(self):
        a = LN.add(type="SUPERSEDES", from_id="ADR-010", to_id="ADR-002",
                   basis="一", path=self.p)
        b = LN.add(type="SUPERSEDES", from_id="ADR-010", to_id="ADR-002",
                   basis="二", path=self.p)
        self.assertEqual(a["edge"]["id"], b["edge"]["id"],
                         "id 只看型別與兩端，不看根據 —— "
                         "同一條邊換個說法不是另一條邊")

    def test_壞掉的行不會讓load整支炸掉(self):
        self.p.parent.mkdir(parents=True, exist_ok=True)
        self.p.write_text('{"broken\n{"type":"SUPERSEDES","from_id":"a",'
                          '"to_id":"b","from_kind":"decision",'
                          '"to_kind":"decision","id":"ln-x"}\n',
                          encoding="utf-8")
        self.assertEqual(len(LN.load(self.p)), 1)


class 走圖(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = Path(self.tmp.name) / "lineage.jsonl"
        for a, b in (("ADR-001", "ADR-002"), ("ADR-002", "ADR-003")):
            LN.add(type="SUPERSEDES", from_id=a, to_id=b,
                   basis="測試", path=self.p)

    def tearDown(self):
        self.tmp.cleanup()

    def test_順著走得到下游(self):
        r = LN.walk("ADR-001", direction="down", depth=3, path=self.p)
        self.assertEqual(r["reached"], ["ADR-002", "ADR-003"])

    def test_逆著走得到上游(self):
        r = LN.walk("ADR-003", direction="up", depth=3, path=self.p)
        self.assertEqual(r["reached"], ["ADR-001", "ADR-002"])

    def test_深度真的限制得住(self):
        r = LN.walk("ADR-001", direction="down", depth=1, path=self.p)
        self.assertEqual(r["reached"], ["ADR-002"])

    def test_走不到的兩種分得出來(self):
        """沒有邊可走，跟有邊但不接這個節點，處置不一樣。"""
        empty = Path(self.tmp.name) / "none.jsonl"
        a = LN.walk("ADR-001", path=empty)
        self.assertEqual(a["reached"], [])
        self.assertEqual(a["edges_total"], 0)
        b = LN.walk("誰都不認識", path=self.p)
        self.assertEqual(b["reached"], [])
        self.assertEqual(b["edges_total"], 2,
                         "有邊但不接這個節點，edges_total 要講出來")

    def test_方向只有兩個(self):
        self.assertFalse(LN.walk("x", direction="sideways", path=self.p)["ok"])


class 可定址性是量出來的(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.r = LN.readiness()

    def test_每一種端點都答得出一個合法狀態(self):
        ks = self.r["kinds"]
        self.assertEqual(set(ks), set(LN.RESOLVERS))
        for kind, v in ks.items():
            self.assertIn(v["status"], LN.READINESS, kind)
            self.assertTrue(v["why"].strip(), f"{kind} 沒有講理由")

    def test_ready的定義就是兩端都ADDRESSABLE(self):
        """不驗「幾條 ready」，驗那個數字是怎麼來的。

        寫死數字的話，哪天有人把 claim 接上去這一條會紅，
        而那一天是好消息。
        """
        ks = self.r["kinds"]
        for name, e in self.r["edges"].items():
            a, b = LN.EDGE_ENDPOINTS[name]
            want = (ks[a]["status"] == "ADDRESSABLE"
                    and ks[b]["status"] == "ADDRESSABLE")
            self.assertEqual(e["ready"], want, name)

    def test_blocked_by列的就是那些不是ADDRESSABLE的端(self):
        ks = self.r["kinds"]
        for name, e in self.r["edges"].items():
            a, b = LN.EDGE_ENDPOINTS[name]
            want = sorted({k for k in (a, b)
                           if ks[k]["status"] != "ADDRESSABLE"})
            self.assertEqual(sorted(set(e["blocked_by"])), want, name)

    def test_磁碟上的邊跟兩端指不指得到是兩個數字(self):
        """合成一個的話，「機制在那裡」跟「真的走過」會長得一樣。

        這正是 `probemodel.AXES_COVERED` 守著的那件事。
        """
        self.assertIn("count", self.r)
        self.assertIn("ready_n", self.r)
        self.assertIsNot(self.r["count"], self.r["ready_n"],
                         "兩個欄位不可以是同一個物件")

    def test_claim那一支看的是真的欄位不是寫死的(self):
        """驗的是它真的去讀 dataclass，不是回一個固定答案。

        **這一條的對照組 2026-09-18 反過來了，而反過來的過程要留著。**
        原本是換上一個「有 id」的假 Claim，看它會不會從 NOT_ADDRESSABLE
        改口 —— 那個寫法的前提是「真的 Claim 沒有 id」。那一天 `Claim`
        長出了 id 與 `claims.jsonl`，前提變假，收尾那一句
        `assertEqual(..., "NOT_ADDRESSABLE")` 就紅了。

        **紅的是前提不是行為。** 所以對照組換邊：現在換上一個「沒有 id」
        的假 Claim，它要說 NOT_ADDRESSABLE；還原之後要回到有 id 的答案。
        兩個方向都還在，這一條仍然抓得到「回一個固定答案」。
        """
        import claims
        real = claims.Claim
        try:
            @dataclasses.dataclass
            class FakeClaim:
                text: str = "x"
            claims.Claim = FakeClaim
            got = LN._kind_claim(REPO)
            self.assertEqual(got["status"], "NOT_ADDRESSABLE",
                             "沒有 id 的 Claim 指不到，這一支要說得出來，"
                             f"拿到的是 {got}")
        finally:
            claims.Claim = real
        self.assertIn(LN._kind_claim(REPO)["status"],
                      ("ADDRESSABLE", "NO_INSTANCES"),
                      "還原之後要回到真的 Claim 的答案 —— 它有 id 了")

    def test_decision那一支讀的是DECISION_LEDGER的標題行(self):
        """換一個沒有 ADR 標題的目錄，它要說 NO_INSTANCES 不是硬給一個數字。"""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            (base / ".forseti").mkdir()
            (base / ".forseti" / "DECISION_LEDGER.md").write_text(
                "# 沒有任何 ADR 標題\n", encoding="utf-8")
            got = LN._kind_decision(base)
            self.assertEqual(got["status"], "NO_INSTANCES")
            self.assertEqual(got["n"], 0)

    def test_檔案不在的時候是NO_SOURCE不是零(self):
        """0 跟「沒有來源」不一樣。這是 blast 那四條誠實條款同一條。"""
        with tempfile.TemporaryDirectory() as td:
            got = LN._kind_decision(Path(td))
            self.assertEqual(got["status"], "NO_SOURCE")
            self.assertIsNone(got["n"])

    def test_真的repo現在decision指得到(self):
        """這一條會隨開發變動，那正是它的目的。

        DECISION_LEDGER.md 被刪掉或標題格式被改掉的那天它要紅。
        """
        got = self.r["kinds"]["decision"]
        self.assertEqual(got["status"], "ADDRESSABLE")
        self.assertTrue(got["example"].startswith("ADR-"))

    def test_印出來的那幾行講得出磁碟上有幾條(self):
        lines = LN.lines(self.r)
        self.assertTrue(lines)
        self.assertIn("磁碟上的 lineage 邊", lines[0])
        self.assertIn(str(self.r["count"]), lines[0])


class 記錄下來的理由要跟量到的一致(unittest.TestCase):
    """2026-09-18 這一輪的主角。

    `event_ledger.SPEC_DEVIATIONS` 先前寫的理由是「等 claim 與
    decision 存在」。量完之後 decision 指得到、claim 也有實作，
    真正擋住的是 evidence 這個實體不存在。

    **一個錯的理由比沒有理由貴** —— 它會把下一個人導去寫一個
    已經存在的模組。所以這一條守的是「那句話跟量到的東西一致」。
    """

    def test_偏離清單不再說在等decision(self):
        line = [d for d in EL.SPEC_DEVIATIONS if "lineage" in d]
        self.assertEqual(len(line), 1, EL.SPEC_DEVIATIONS)
        self.assertNotIn("等 claim 與 decision 存在", line[0],
                         "decision 指得到（ADR-001..010），"
                         "claim 也有實作。這句話量完是錯的")

    def test_decision此刻真的不是擋住的那一個(self):
        r = LN.readiness()
        blocked = {k for e in r["edges"].values()
                   for k in (e.get("blocked_by") or [])}
        self.assertNotIn("decision", blocked,
                         "decision 現在指得到，它不在擋住的那一群裡")


if __name__ == "__main__":
    unittest.main()
