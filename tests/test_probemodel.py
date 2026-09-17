#!/usr/bin/env python3
"""Probe Packs 的模型軸。§15 的 `models` 與 `contexts`。

`probe.py` 蓋的是 `versions`（改了判準程式碼會不會退化），
這一支蓋另外兩軸（換模型、context 被塞滿）。

## 這一組一次都不呼叫模型

真的呼叫要花 owner 的訂閱額度，而測試會被跑很多次。
所以 `subprocess.run` 一律換掉，驗的是判定邏輯本身:
抽不抽得到 VERDICT、抽到之後怎麼判、失敗怎麼分類、分母怎麼算。

## 為什麼分母要挑過

`CALL_FAILED`（認證過期、CLI 不在）與 `NO_VERDICT`（格式壞掉）
**不是答錯**。混進分母的話，一次認證失敗會看起來像模型退化，
而那兩件事的處理方式完全不同。這一組有兩條釘住這件事。
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import probe as PB          # noqa: E402
import probemodel as PM     # noqa: E402


class _R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _fake_run(out="", rc=0, err=""):
    return lambda *a, **k: _R(rc, out, err)


CASE = PM.PACK[0]


class _Base(unittest.TestCase):
    """換掉 `subprocess.run` 之前先記著，跑完還原。

    **2026-09-17 事故:** 原本直接 `PM.subprocess.run = fake` 而不還原。
    `PM.subprocess` 就是 `subprocess` 模組本身，改它等於改掉整個
    Python 程序的 `subprocess.run`。字母序 `test_probemodel` 排在
    `test_ui_render` 前面，於是後面每一條要開子行程的測試全部被毒死 ——
    全套 46 紅，而每一個檔單獨跑都是綠的。

    這個形狀特別難查:症狀出現在別人身上，而兇手自己一切正常。
    """

    def setUp(self):
        self._real_run = PM.subprocess.run

    def tearDown(self):
        PM.subprocess.run = self._real_run


class 十類一個不漏也不多(_Base):
    """出題的加上明講不出題的，要正好等於 §15.2 那十類。

    少一類會讓通過率的分母偷偷變小；多一類代表有人自己發明了
    一個類別塞進來。兩個方向都要擋。
    """

    def test_出題加不出題等於規格的十類(self):
        spec = {cid for cid, _ in PB.REQUIRED_CLASSES}
        asked = {c.cls for c in PM.PACK}
        skipped = set(PM.NOT_ASKED)
        self.assertEqual(asked | skipped, spec,
                         f"多了 {(asked | skipped) - spec}，"
                         f"少了 {spec - (asked | skipped)}")

    def test_出題與不出題不重疊(self):
        self.assertEqual({c.cls for c in PM.PACK} & set(PM.NOT_ASKED), set())

    def test_不出題的每一類都講得出為什麼(self):
        for cid, why in PM.NOT_ASKED.items():
            with self.subTest(cid=cid):
                self.assertGreater(len(why), 20,
                                   "沒有理由的略過，跟藏起來一樣")

    def test_每一題的答案都在選項裡(self):
        for c in PM.PACK:
            with self.subTest(cls=c.cls):
                self.assertIn(c.expect, c.options)
                self.assertGreaterEqual(len(c.options), 2, "只有一個選項不算題目")

    def test_每一題都指得回條文(self):
        """沒有條文可指的題目，正確答案就是我自己判斷的。"""
        for c in PM.PACK:
            with self.subTest(cls=c.cls):
                self.assertTrue(
                    any(t.startswith(("§", "F")) for t in c.tags),
                    f"{c.cls} 的 tags {c.tags} 裡沒有條文")
                self.assertGreater(len(c.why_it_matters), 15)


class 判定只看那一行(_Base):

    def test_抽得到標準格式(self):
        PM.subprocess.run = _fake_run("VERDICT: UNCONFIRMED\n因為沒有證據。")
        r = PM.ask(PM.PACK[7], model="x")
        self.assertEqual(r["verdict"], "UNCONFIRMED")
        self.assertEqual(r["state"], "PASS")
        self.assertIn("因為", r["reason"])

    def test_全形冒號也算(self):
        PM.subprocess.run = _fake_run("VERDICT：UNCONFIRMED\n理由")
        self.assertEqual(PM.ask(PM.PACK[7], model="x")["verdict"],
                         "UNCONFIRMED")

    def test_答錯就是答錯(self):
        PM.subprocess.run = _fake_run("VERDICT: CONFIRMED\n三個都同意。")
        r = PM.ask(PM.PACK[7], model="x")
        self.assertEqual(r["state"], "WRONG")

    def test_抽不到判定不等於答錯(self):
        """格式壞掉跟判斷錯掉是兩件事。

        混在一起的話，一個壞掉的輸出格式會被記成模型退化。
        """
        PM.subprocess.run = _fake_run("我覺得這個沒有被證實喔。")
        r = PM.ask(PM.PACK[7], model="x")
        self.assertEqual(r["state"], "NO_VERDICT")
        self.assertIsNone(r["verdict"])
        self.assertTrue(r["raw"], "原文沒留下來就查不出它到底回了什麼")

    def test_答了選項以外的東西要自成一類(self):
        PM.subprocess.run = _fake_run("VERDICT: MAYBE\n不確定。")
        r = PM.ask(PM.PACK[7], model="x")
        self.assertEqual(r["state"], "OFF_MENU")
        self.assertEqual(r["verdict"], "MAYBE")

    def test_呼叫失敗要看得出是呼叫失敗(self):
        PM.subprocess.run = _fake_run(rc=1, err="OAuth session expired")
        r = PM.ask(PM.PACK[7], model="x")
        self.assertEqual(r["state"], "CALL_FAILED")
        self.assertIn("OAuth", r["raw"])

    def test_不認得的context模式直接擋(self):
        with self.assertRaises(PM.ProbeModelError):
            PM.ask(CASE, model="x", mode="半滿")


class 分母不准把失敗算成答錯(_Base):

    def test_呼叫失敗與沒判定都不進分母(self):
        seq = iter([
            _R(0, "VERDICT: UNCONFIRMED\nok"),   # PASS
            _R(0, "VERDICT: CONFIRMED\nno"),     # WRONG
            _R(1, "", "OAuth session expired"),  # CALL_FAILED
            _R(0, "我不知道"),                    # NO_VERDICT
        ])
        PM.subprocess.run = lambda *a, **k: next(seq)
        out = PM.run(models=("m1", "m2"), modes=("clean", "loaded"),
                     only="multi_agent_consensus")
        self.assertEqual(out["judged"], 2, "分母應該只有真的拿到判定的兩次")
        self.assertEqual(out["passed"], 1)
        self.assertEqual(out["rate"], 0.5)
        self.assertEqual(out["by_state"].get("CALL_FAILED"), 1)
        self.assertEqual(out["by_state"].get("NO_VERDICT"), 1)

    def test_一次都沒判定成功的時候不給比率(self):
        PM.subprocess.run = _fake_run(rc=1, err="OAuth session expired")
        out = PM.run(models=("m1",), modes=("clean",),
                     only="multi_agent_consensus")
        self.assertIsNone(out["rate"], "全部失敗卻算得出通過率")
        self.assertEqual(out["judged"], 0)


class 乾跑與填充(_Base):

    def test_乾跑一次都不呼叫(self):
        def boom(*a, **k):
            raise AssertionError("plan() 不准呼叫任何東西")
        PM.subprocess.run = boom
        p = PM.plan(PM.PACK, models=("a", "b"), modes=("clean", "loaded"))
        self.assertEqual(p["calls"], len(PM.PACK) * 2 * 2)

    def test_填充模式真的比較長(self):
        clean = len(CASE.prompt())
        loaded = len(PM._load_prefix() + CASE.prompt())
        self.assertGreater(loaded - clean, PM.LOAD_CHARS - 200)

    def test_填充內容沒有判斷成分(self):
        """有意義的填充會變成另一個變因。"""
        pre = PM._load_prefix(500)
        for w in ("VERDICT", "應該", "建議", "正確"):
            self.assertNotIn(w, pre)

    def test_狀態查詢預設不花錢(self):
        def boom(*a, **k):
            raise AssertionError("status() 預設不准呼叫模型")
        PM.subprocess.run = boom
        s = PM.status()
        self.assertEqual(s["auth"], "UNKNOWN")
        self.assertIn("沒有查認證", s["why"])


class 這一軸還沒真的跑過就不准說它蓋到了(_Base):
    """`probe.AXES_COVERED` 是「真的量得到」，不是「寫好了」。

    機制在那裡而一次都沒跑成，跟跑過而且通過，
    在一張表上不能長一樣 —— 那正是 `NO_VERIFIER` 存在的理由。
    """

    def test_probe那一支的軸沒有被順手改掉(self):
        self.assertEqual(PB.AXES_COVERED, ("versions",))
        self.assertEqual(set(PB.AXES_MISSING), {"models", "contexts"})


if __name__ == "__main__":
    unittest.main()


class 花錢的那條路要按兩次(_Base):
    """`run` 沒有 `--yes` 不准真的呼叫。

    理由跟 fork 的乾跑一樣:一個按下去就開始花錢的指令，
    遲早會在沒人打算花錢的時候被按到。
    """

    def test_沒有yes就不呼叫而且離開碼不是零(self):
        def boom(*a, **k):
            raise AssertionError("沒有 --yes 卻真的呼叫了")
        PM.subprocess.run = boom
        self.assertEqual(PM.main(["run"]), 2)

    def test_status預設不呼叫(self):
        def boom(*a, **k):
            raise AssertionError("status 預設不准呼叫")
        PM.subprocess.run = boom
        self.assertIn(PM.main(["status"]), (0, 1))

    def test_plan不呼叫(self):
        def boom(*a, **k):
            raise AssertionError("plan 不准呼叫")
        PM.subprocess.run = boom
        self.assertEqual(PM.main(["plan"]), 0)

    def test_cli有掛進forseti(self):
        """指令沒接上的話，上面那些閘門一個都碰不到。"""
        src = (ROOT / "apps" / "forseti-cli" / "forseti.py").read_text(
            encoding="utf-8")
        self.assertIn('cmd == "probe-model"', src)
        self.assertIn("import probemodel", src)


class 不准再毒死別的測試檔(_Base):
    """換掉全域的東西而不還原，症狀會出現在別人身上。

    2026-09-17 實測:這個檔直接改 `PM.subprocess.run` 而不還原，
    造成全套 46 紅，而每一個檔單獨跑都是綠的。兇手自己一切正常，
    這是最難查的一種。

    守法是靜態的:**每一個會動全域的類別都要繼承 `_Base`**，
    而 `_Base` 的 `tearDown` 負責還原。行為測試守不住這件事，
    因為 `tearDown` 跑完之後一切看起來都正常。
    """

    def test_每個測試類別都繼承會還原的基底(self):
        import re
        src = Path(__file__).read_text(encoding="utf-8")
        bad = [m for m in re.findall(r"^class (\w+)\(unittest\.TestCase\):",
                                     src, re.M) if m != "_Base"]
        self.assertEqual(bad, [],
                         f"這幾個類別沒繼承 _Base，換掉的東西不會還原：{bad}")

    def test_基底真的有還原那一步(self):
        """驗行為，不比對原始碼字串。

        先前這一條寫成 `assertIn("PM.subprocess.run = self._real_run", src)`，
        而那個字串就在那一行自己身上 —— 檢查找到的是它自己，
        所以把 `tearDown` 的內容整個換掉它也不會紅（2026-09-17 反向驗證
        當場抓到）。§28.9 記過同一個形狀:一個永遠回 OK 的檢查，
        跟一個壞掉的檢查是同一種壞掉。
        """
        class _Probe(_Base):
            def runTest(self):
                pass

        probe = _Probe()
        probe.setUp()
        sentinel = object()
        PM.subprocess.run = sentinel
        probe.tearDown()
        self.assertIsNot(PM.subprocess.run, sentinel,
                         "tearDown 沒有把換掉的東西放回去")

    def test_這個檔動到的是模組本身不是複本(self):
        """釘住「為什麼會毒死別人」這個前提。

        前提要是哪天不成立了（例如改成 patch 一個區域名字），
        上面那兩條就變成在守一件不存在的事。
        """
        import subprocess as real
        self.assertIs(PM.subprocess, real,
                      "probemodel 換成別的 subprocess 了，"
                      "上面兩條守的前提要重新想")
