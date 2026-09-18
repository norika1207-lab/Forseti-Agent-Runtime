#!/usr/bin/env python3
"""§12.2 Source-of-truth registry。

這一組要抓的是三類會靜默說謊的事:

  一，表跟規格原文分岔了而沒有人發現（七行被讀成五行就是這樣來的）
  二，登記的憑據被刪掉或改名，而那一條登記照樣印得出來
  三，「沒量」被投影成「健康」——沒有燈的地方長出一個綠燈

不重測 `contract.worktree_paths` 本身，那是 `test_contract.py` 的事。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import sot as S  # noqa: E402


class 表要跟規格一致(unittest.TestCase):
    def test_七行不是五行(self):
        # 2026-09-16 讀規格讀到第 375 行就停，於是「五行」差點寫進程式碼。
        # 實際是 371 到 377。這一條釘住行數本身。
        self.assertEqual(len(S.PRECEDENCE), 7)

    def test_每一行都回得去規格那一行原文(self):
        r = S.verify_spec()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checked"], 7)
        for row in r["rows"]:
            self.assertTrue(row["ok"], row)
            # 比對的是那一行，不是整份檔案裡有沒有出現過這個字串。
            self.assertTrue(row["raw"].startswith("|"), row)

    def test_規格原文改一個字就會紅(self):
        # 反向：把表裡的 preferred 動一個字，verify_spec 必須抓到。
        orig = S.PRECEDENCE[1]["preferred"]
        try:
            S.PRECEDENCE[1]["preferred"] = orig.replace("Process", "Prosess")
            self.assertFalse(S.verify_spec()["ok"])
        finally:
            S.PRECEDENCE[1]["preferred"] = orig
        self.assertTrue(S.verify_spec()["ok"])

    def test_指錯行號也會紅(self):
        orig = S.PRECEDENCE[0]["spec_line"]
        try:
            S.PRECEDENCE[0]["spec_line"] = 372   # 那是 Service health 那一行
            self.assertFalse(S.verify_spec()["ok"])
        finally:
            S.PRECEDENCE[0]["spec_line"] = orig


class 憑據不准腐爛(unittest.TestCase):
    def test_現在每一條登記的原文都還在(self):
        r = S.verify_bindings()
        self.assertEqual(r["stale"], 0, r)
        self.assertTrue(r["ok"])

    def test_每一行都有登記而且狀態合法(self):
        for row in S.PRECEDENCE:
            b = S.binding(row["key"])
            self.assertIsNotNone(b, row["key"])
            self.assertIn(b["state"], S.STATES)

    def test_原文不見了要是STALE不是靜靜地過(self):
        orig = S.BINDINGS[0]["evidence"]
        try:
            S.BINDINGS[0]["evidence"] = (
                ("apps/forseti-cli/contract.py", 282,
                 "def _這個函式不存在_"),)
            r = S.verify_bindings()
            self.assertEqual(r["stale"], 1)
            self.assertFalse(r["ok"])
        finally:
            S.BINDINGS[0]["evidence"] = orig
        self.assertTrue(S.verify_bindings()["ok"])

    def test_檔案不見了也要是STALE(self):
        orig = S.BINDINGS[0]["evidence"]
        try:
            S.BINDINGS[0]["evidence"] = (("apps/forseti-cli/沒有這個檔.py",
                                          1, "x"),)
            self.assertEqual(S.verify_bindings()["stale"], 1)
        finally:
            S.BINDINGS[0]["evidence"] = orig

    def test_行號漂移是DRIFTED不是STALE(self):
        # 程式碼會動，行號會漂。漂了要講，但不能當成憑據不見了 ——
        # 兩者的下一步不一樣：一個是更新行號，一個是這條登記不能再信。
        orig = S.BINDINGS[0]["evidence"]
        try:
            S.BINDINGS[0]["evidence"] = (
                ("apps/forseti-cli/contract.py", 1, "def _fingerprint"),)
            r = S.verify_bindings()
            self.assertEqual(r["stale"], 0)
            # **只數被動過的那一條，不數全域。** 2026-09-16 22:5x 這條
            # 因為別人改了 `contract.py` 的行數而變紅：全域 drifted 從
            # 1 變 6，而這個測試想驗的只是「漂移歸類成 DRIFTED」。
            # 一條會被無關改動弄紅的測試，久了會讓人習慣忽略它。
            row = next(x for x in r["rows"] if x["key"] == S.BINDINGS[0]["key"])
            self.assertEqual(row["drifted"], 1)
            self.assertEqual(row["stale"], 0)
            self.assertTrue(r["ok"])   # 漂移不擋
        finally:
            S.BINDINGS[0]["evidence"] = orig


class 查表(unittest.TestCase):
    def test_服務健康狀態回的是程序管理器不是git(self):
        # ROADMAP P2 第 7 項的完成定義，逐字。
        r = S.lookup("服務健康狀態")
        self.assertTrue(r["ok"])
        self.assertEqual(r["answer"],
                         "Process manager + health endpoint + socket/listener")
        self.assertIn("git", r["not_source"])
        self.assertNotIn("git", r["answer"].lower())

    def test_檔案內容那一行明說git要有條件(self):
        r = S.lookup("檔案內容")
        self.assertTrue(r["ok"])
        self.assertIn("Git only if deployed from same revision", r["answer"])

    def test_ROADMAP那句完整問句直接查得到(self):
        # 完成定義的原文是問「服務健康狀態該信誰」，不是問一個 key。
        r = S.lookup("服務健康狀態該信誰")
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["row"]["key"], "service_health")

    def test_對不上就不回答而且列出合法的key(self):
        # B-05：不做模糊比對。給一個看起來有回答的答案比不回答糟。
        r = S.lookup("這個東西該信誰")
        self.assertFalse(r["ok"])
        self.assertEqual(len(r["valid"]), 7)

    def test_句子裡含有別名不等於問那一類(self):
        # 第一版這條測試是假守備：它用的問句在模糊比對下也對不上，
        # 所以把 `t in cands` 改成 `any(t in c or c in t ...)` 照樣全綠。
        # 反向驗證抓到的。這一條用的是**會被模糊比對誤判**的句子：
        # 它含有兩個別名，而它問的不是這兩類的任何一類。
        for q in ("我想知道服務健康狀態跟檔案內容哪個重要",
                  "檔案內容以外的東西"):
            r = S.lookup(q)
            self.assertFalse(r["ok"], q)

    def test_剝掉的尾巴是固定清單不是句型推斷(self):
        # 清單以外的尾巴不剝 —— 剝了就是在猜語意。
        #
        # 第一版這條也是假守備：它用「服務健康狀態怎麼查」，
        # 而那句在「遇到『該』就砍」的通用切法下也對不上，
        # 所以把固定清單換成通用切法照樣全綠。反向驗證抓到的。
        # 這一條用的是**含有「該」但尾巴不在清單裡**的句子。
        self.assertTrue(S.lookup("服務健康狀態該信誰")["ok"])
        for q in ("服務健康狀態該去哪裡查", "服務健康狀態該怎麼辦",
                  "服務健康狀態怎麼查"):
            self.assertFalse(S.lookup(q)["ok"], q)

    def test_空字串不當成某一類(self):
        self.assertFalse(S.lookup("")["ok"])
        self.assertFalse(S.lookup("   ")["ok"])

    def test_英文原文跟key都查得到(self):
        self.assertTrue(S.lookup("Service health")["ok"])
        self.assertTrue(S.lookup("service_health")["ok"])

    def test_每一行都帶得出規格位置(self):
        for k in S.keys():
            r = S.lookup(k)
            self.assertTrue(r["ok"], k)
            self.assertIn(":", r["spec"])
            self.assertTrue(r["spec"].split(":")[-1].isdigit())


class 沒量到不准變成健康(unittest.TestCase):
    def test_只有一行有即時量測而且這件事寫在回傳值裡(self):
        a = S.assess()
        measured = [r for r in a["rows"] if r["live"] is not None]
        self.assertEqual(len(measured), 1)
        self.assertEqual(measured[0]["key"], "current_file_content")
        self.assertEqual(a["live_measured"], 1)
        # 沒量的那六行是 None，不是空字典也不是 False ——
        # 空字典在畫面上會被當成「查過了，沒事」。
        for r in a["rows"]:
            if r["key"] != "current_file_content":
                self.assertIsNone(r["live"])

    def test_工作區跟HEAD不一致的時候git不是權威(self):
        live = S._file_content_live()
        self.assertTrue(live["measured"], live)
        if live["divergent"]:
            self.assertIs(live["git_authoritative"], False)
        else:
            self.assertIs(live["git_authoritative"], True)

    def test_已追蹤有改動跟從沒進版控要分開數(self):
        # 兩種都讓 hash 指不到現在跑的程式碼，但下一步不一樣。
        live = S._file_content_live()
        self.assertEqual(live["tracked_modified"] + live["untracked"],
                         live["divergent"])

    def test_量不到的時候是None不是True也不是False(self):
        import contract as C
        orig = C.worktree_paths
        try:
            C.worktree_paths = lambda *a, **k: {"entries": [],
                                                "problem": "git 掛了"}
            live = S._file_content_live()
            self.assertFalse(live["measured"])
            self.assertIsNone(live["git_authoritative"])
            self.assertIn("git 掛了", live["why"])
        finally:
            C.worktree_paths = orig

    def test_空清單沒problem是乾淨不是沒量到(self):
        import contract as C
        orig = C.worktree_paths
        try:
            C.worktree_paths = lambda *a, **k: {"entries": [], "problem": None}
            live = S._file_content_live()
            self.assertTrue(live["measured"])
            self.assertIs(live["git_authoritative"], True)
        finally:
            C.worktree_paths = orig


class 不適用跟還沒接是兩件事(unittest.TestCase):
    def test_NOT_APPLICABLE的兩行都附得出依據(self):
        for b in S.BINDINGS:
            if b["state"] == "NOT_APPLICABLE":
                self.assertTrue(b["note"].strip(), b["key"])
                self.assertTrue(b["evidence"], b["key"])

    def test_NO_SOURCE不准假裝有在用(self):
        for b in S.BINDINGS:
            if b["state"] == "NO_SOURCE":
                self.assertEqual(b["uses"], "", b["key"])

    def test_BOUND跟PARTIAL一定講得出現在用什麼(self):
        for b in S.BINDINGS:
            if b["state"] in ("BOUND", "PARTIAL"):
                self.assertTrue(b["uses"].strip(), b["key"])

    def test_summary的分類數加起來等於七(self):
        s = S.summary()
        self.assertEqual(sum(s["by_state"].values()), 7)
        self.assertEqual(s["total"], 7)

    def test_每一行都講得出不該信誰(self):
        # 「該信誰」跟「不該信誰」一樣重要。§12.2 第一行的重點
        # 正是 Git only if —— 也就是預設不信。
        for k in S.keys():
            self.assertTrue(S.NOT_SOURCE.get(k), k)


if __name__ == "__main__":
    unittest.main()


