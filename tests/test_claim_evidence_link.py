#!/usr/bin/env python3
"""`Claim.evidence_refs` 收的是 evidence id，不是句子。§6.3 的
VERIFIES / REFUTES 那條邊的 claim 端。

## 這一組擋的是什麼

2026-09-18 之前 `raise_strength()` 把它的 `why` 直接 append 進
`evidence_refs`，於是那一欄裡放的是「帳本裡 hook 當時量到的」這種句子。
**問題不是欄位髒。** 問題是那一欄的名字讓讀的人以為它指得回
`evidence.jsonl`，而它指不回去 —— §6.3 的邊因此永遠接不上，
而畫面上看不出來：一欄有東西的 `evidence_refs` 跟一欄真的有 id 的
長得一樣。

所以這一組守三件事：

一，`evidence_refs` 只收 `ev-` 那個形狀，拒收而不是默默接受。
二，升降強度的理由有自己的家（`strength_log`），沒有被丟掉。
三，形狀對不對跟磁碟上存不存在是兩個檢查，而且後者預設不做。

第三條是這一組最容易被下一輪改掉的。預設去碰磁碟會讓 `verify()`
那條路上每一個宣稱都多讀一次整份 jsonl，而那條路一輪跑幾百次。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import claims as C  # noqa: E402
import evidence as E  # noqa: E402


def _c():
    return C.Claim(text="我建立了 a.py", kind="file", subject="a.py")


def _ev(tmp: Path, about="a.py 存在", strength="E2"):
    r = E.record(about=about, sources=("cmd:stat a.py",), strength=strength,
                 captured_by="test", path=tmp / "evidence.jsonl")
    assert r["ok"], r
    return r["evidence"]["id"]


class IdShape(unittest.TestCase):

    def test_判準借evidence不自己寫正則(self):
        """擋的是：在 claims.py 複製一份 `ev-` 的正則。

        複製的話 `evidence._make_eid()` 改了這邊不會跟著改，
        症狀是合法的 id 被拒收，而兩邊各自看起來都對。
        """
        seen = {}
        real = E.is_evidence_id

        def spy(s):
            seen["called"] = True
            return real(s)

        E.is_evidence_id = spy
        try:
            C.Claim(text="x", kind="file", subject="y",
                    evidence_refs=["ev-0123456789"])
        finally:
            E.is_evidence_id = real
        self.assertTrue(seen.get("called"),
                        "claims 沒有問 evidence，那它一定是自己有一份判準")

    def test_真的產出來的id過得了這一關(self):
        """擋的是：正則寫太緊。兩邊都用 sha256 前十位，但這一條是唯一
        會在長度改掉的時候紅的地方。"""
        with tempfile.TemporaryDirectory() as d:
            eid = _ev(Path(d))
        self.assertTrue(E.is_evidence_id(eid), eid)

    def test_形狀判斷不碰磁碟(self):
        """一個沒登記過的合法形狀也算合法。存不存在是另一個問題，
        用 require_exists 問。"""
        self.assertTrue(E.is_evidence_id("ev-0000000000"))
        self.assertIsNone(E.get("ev-0000000000",
                                path=Path(tempfile.mkdtemp()) / "nope.jsonl"))


class Refs(unittest.TestCase):

    def test_建構的時候就拒收自由文字(self):
        with self.assertRaises(C.ClaimError) as cm:
            C.Claim(text="x", kind="file", subject="y",
                    evidence_refs=["帳本裡 hook 當時量到的"])
        self.assertIn("evidence id", str(cm.exception))

    def test_接得上真的id(self):
        with tempfile.TemporaryDirectory() as d:
            eid = _ev(Path(d))
            c = _c()
            c.attach_evidence(eid)
            self.assertEqual(c.evidence_refs, [eid])

    def test_接兩次不重複記(self):
        """§7.1：重複增加的是社會共識不是證據強度。同一筆證據支撐同一個
        宣稱兩次，跟支撐一次是同一件事。"""
        with tempfile.TemporaryDirectory() as d:
            eid = _ev(Path(d))
            c = _c()
            c.attach_evidence(eid)
            c.attach_evidence(eid)
            self.assertEqual(c.evidence_refs, [eid])

    def test_接不是id的東西丟例外(self):
        c = _c()
        with self.assertRaises(C.ClaimError):
            c.attach_evidence("stat 確定性檢查")

    def test_兩筆不同的證據都接得上(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            a = _ev(tmp, about="a.py 存在")
            b = _ev(tmp, about="a.py 的 hash 是這個")
            self.assertNotEqual(a, b)
            c = _c()
            c.attach_evidence(a)
            c.attach_evidence(b)
            self.assertEqual(c.evidence_refs, [a, b])


class Exists(unittest.TestCase):

    def test_預設不查磁碟(self):
        """擋的是：把存在性檢查變成預設。

        `verify()` 那條路一輪跑幾百個宣稱，每一次重讀整份 jsonl 會讓
        驗證從碰一次磁碟變成碰兩次。要嚴的那一邊自己開。
        """
        c = _c()
        c.attach_evidence("ev-0000000000")          # 磁碟上沒有這一筆
        self.assertEqual(c.evidence_refs, ["ev-0000000000"])

    def test_開了就會拒收指不到的id(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            _ev(tmp)
            c = _c()
            with self.assertRaises(C.ClaimError) as cm:
                c.attach_evidence("ev-0000000000", require_exists=True,
                                  path=tmp / "evidence.jsonl")
            self.assertIn("找不到", str(cm.exception))
            self.assertEqual(c.evidence_refs, [],
                             "拒收之後不該留下半條邊")

    def test_開了而且真的有那一筆就過(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            eid = _ev(tmp)
            c = _c()
            c.attach_evidence(eid, require_exists=True,
                              path=tmp / "evidence.jsonl")
            self.assertEqual(c.evidence_refs, [eid])


class StrengthLog(unittest.TestCase):

    def test_升強度的理由不進evidence_refs(self):
        c = _c()
        c.raise_strength("E2", "stat 確定性檢查")
        self.assertEqual(c.evidence_refs, [])

    def test_升強度的理由沒有被丟掉(self):
        """擋的是：為了讓 evidence_refs 乾淨而把理由刪掉。那會讓
        「強度為什麼是 E2」變成答不出來的問題。"""
        c = _c()
        c.raise_strength("E2", "stat 確定性檢查")
        self.assertEqual(len(c.strength_log), 1)
        row = c.strength_log[0]
        self.assertEqual((row["from"], row["to"]), ("E0", "E2"))
        self.assertEqual(row["why"], "stat 確定性檢查")
        self.assertEqual(row["evidence_id"], "")

    def test_降級在log裡看得出來是降級(self):
        c = _c()
        c.raise_strength("E3", "兩個獨立來源")
        c.lower_strength("E1", "其中一個來源其實是快取")
        self.assertEqual(c.strength, "E1")
        self.assertTrue(c.strength_log[-1]["why"].startswith("降級："))
        self.assertEqual(c.strength_log[-1]["from"], "E3")

    def test_給了evidence_id就同時接上邊(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            eid = _ev(tmp)
            c = _c()
            c.raise_strength("E2", "stat 確定性檢查", evidence_id=eid)
            self.assertEqual(c.evidence_refs, [eid])
            self.assertEqual(c.strength_log[-1]["evidence_id"], eid)

    def test_evidence_id不合法的時候強度不動(self):
        """擋的是：先改強度再驗 id。那樣的話一個被拒收的呼叫會留下
        一個升過強度但沒有證據的宣稱 —— 正好是 §8.3 的填空。"""
        c = _c()
        with self.assertRaises(C.ClaimError):
            c.raise_strength("E2", "理由", evidence_id="不是 id")
        self.assertEqual(c.strength, "E0")
        self.assertEqual(c.strength_log, [])

    def test_多次升強度每一次都留一列(self):
        c = _c()
        c.raise_strength("E1", "工具輸出")
        c.raise_strength("E2", "stat")
        self.assertEqual([r["to"] for r in c.strength_log], ["E1", "E2"])


class Row(unittest.TestCase):

    def test_strength_log進得了那一列(self):
        c = _c()
        c.raise_strength("E2", "stat")
        row = c.to_row()
        self.assertEqual(len(row["strength_log"]), 1)
        self.assertEqual(row["evidence_refs"], [])

    def test_那一列改不到claim自己(self):
        """`to_row()` 回的 dict 被改，不該影響原本的 claim。
        擋的是把同一個 list / dict 直接交出去。"""
        c = _c()
        c.raise_strength("E2", "stat")
        row = c.to_row()
        row["strength_log"][0]["why"] = "被改掉了"
        row["evidence_refs"].append("ev-0000000000")
        self.assertEqual(c.strength_log[0]["why"], "stat")
        self.assertEqual(c.evidence_refs, [])

    def test_落地讀回來兩欄都還在(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            eid = _ev(tmp)
            c = _c()
            c.raise_strength("E2", "stat", evidence_id=eid)
            C.record(c, path=tmp / "claims.jsonl")
            back = C.get(c.id, path=tmp / "claims.jsonl")
            self.assertEqual(back["evidence_refs"], [eid])
            self.assertEqual(back["strength_log"][0]["why"], "stat")


class VerifyPath(unittest.TestCase):
    """`verify()` 走完之後那一欄不會被塞句子。

    這一組不是重複上面那幾條：上面守的是方法，這裡守的是**既有呼叫端**
    走過之後的結果。claims.py 裡有九處 `raise_strength(...)`，
    它們全部只給理由不給 id，所以走完 `evidence_refs` 必須還是空的。
    """

    def test_驗一個不存在的檔走完refs是空的(self):
        with tempfile.TemporaryDirectory() as d:
            c = C.Claim(text="我把 絕對不存在的檔.py 寫好了。", kind="file",
                        subject="絕對不存在的檔.py")
            C.verify(c, cwd=Path(d))
            self.assertEqual(c.evidence_refs, [],
                             f"verify 把句子塞進去了：{c.evidence_refs}")

    def test_驗一個真的存在的檔走完refs也是空的(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "a.py").write_text("x = 1\n", encoding="utf-8")
            c = C.Claim(text="我建立了 a.py", kind="file", subject="a.py")
            C.verify(c, cwd=tmp)
            self.assertEqual(c.evidence_refs, [])

    def test_而且理由有被記下來(self):
        """擋的是：把上面兩條改成「verify 不留任何痕跡」。
        那樣兩條會變綠，而強度為什麼變了會答不出來。"""
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            (tmp / "a.py").write_text("x = 1\n", encoding="utf-8")
            c = C.Claim(text="我建立了 a.py", kind="file", subject="a.py")
            C.verify(c, cwd=tmp)
            self.assertNotEqual(c.strength, "E0")
            self.assertTrue(c.strength_log,
                            "強度動了但沒有留下憑據")


if __name__ == "__main__":
    unittest.main()
