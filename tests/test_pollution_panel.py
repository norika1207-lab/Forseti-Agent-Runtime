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


class Wiring(unittest.TestCase):
    def test_snap帶得出這一欄而且是在strands裡面(self):
        # 用原始碼位置釘住接線，跟 test_handoff.py 那次同一條。
        # 只驗函式算得出來是不夠的:`pollution_panel()` 自己會過，
        # 而畫面永遠拿不到 —— 這正是這一輪要補的那個缺口本身。
        import inspect
        body = inspect.getsource(D.strands)
        self.assertIn('snap["pollution"] = _safe(', body)
        # fallback 不准是空清單。這一條跟 test_讀不到的時候不回空清單
        # 各守一半:那條守函式，這條守接線處寫死的那個預設值。
        self.assertIn('"has": False', body.split('snap["pollution"]')[1][:400])

    def test_分母跟只靠人記得的那幾筆接到畫面上(self):
        """**後端改對而畫面沒接，是靜默的。**

        `pollution_panel()` 現在回得出分母與那幾個 id，而畫面照樣
        可以只印一個沒有分母的數字 —— 那個狀態跑測試會全綠，
        因為後端那幾條都過了。所以這一條在畫面這一側釘住。

        跟 `test_snap帶得出這一欄` 是同一條原則的兩端：
        那條守後端到 snap，這條守 snap 到畫面。
        """
        self.assertIn("p.guard_denominator", APP)
        self.assertIn("p.unguarded_ids", APP)
        # 有那幾筆的時候才印。`p.unguarded` 是 0 的時候印一句
        # 「剩下 0 筆只靠人記得」是噪音，不是資訊。
        self.assertIn("p.unguarded\n      ? ", APP)

    def test_畫面上分母那一句不准只印數字(self):
        """數字旁邊沒有分母，讀的人只能拿旁邊最近的那個數字去配。

        這一格旁邊最近的是 `p.open`，而 2026-09-18 之前那個數字
        接的是 `summary()['guarded']`（分母是 total）—— 配起來剛好
        對得上，所以錯的狀態看起來是對的。
        """
        seg = APP.split("p.guarded_note")[1][:400]
        self.assertIn("分母是", seg)
        # 舊那一欄不准被接回去。它一句話講完兩堆，接回去就是
        # `test_那兩行不准重複講同一句` 記的那個症狀。
        # 用 regex 是因為 `p.guarded_note` 也含 `p.guard` 這個前綴，
        # 單純的子字串比對分不開這兩個名字。
        self.assertIsNone(re.search(r"p\.guard_note\b", APP),
                          "畫面接回了 guard_note，那一句含著第二行整句")

    def test_那兩行不准重複講同一句(self):
        """**2026-09-18 實測撞到的，不是預防性假設。**

        第一行原本接的是 `guard_note`，而那一句是一句話講完兩堆
        （「⋯攔著的筆數。其餘那些現在只靠人記得」）。第二行接上去
        之後，畫面長成：

            ⋯其餘那些現在只靠人記得：19 筆，分母是⋯
            剩下 2 筆現在只靠人記得：pol-⋯

        兩行都說了同一句，而後面那一行才是有資訊的那一行。
        所以說明拆成 `guarded_note` 與 `unguarded_note` 各管一行。
        """
        pn = D.pollution_panel()
        一 = pn["guarded_note"]
        二 = pn["unguarded_note"]
        self.assertTrue(一.strip())
        self.assertTrue(二.strip())
        self.assertNotIn(二, 一, "第一行的說明裡含著第二行整句，會重複")
        self.assertNotIn(一, 二)
        # `basis` 是回答「憑什麼這樣分」的，不是畫面文案 ——
        # 它含著兩堆是對的，所以它不准被接到任何一行上。
        self.assertNotIn("p.guard_basis", APP)

    def test_那幾個id後面的話要接得成句(self):
        """caveat 分開一欄，因為 id 要夾在中間。

        併成一句的話排版會變成「⋯只靠人記得。重驗過不等於機制被
        擋住了：pol-xxx」—— 句號後面接冒號。**排版歸畫面，句子歸後端**，
        所以後端那兩欄各自都不准自帶標點。
        """
        pn = D.pollution_panel()
        for k in ("guarded_note", "unguarded_note", "unguarded_caveat"):
            v = pn[k]
            self.assertTrue(v.strip(), k)
            for 標點 in ("。", "：", ":"):
                self.assertNotIn(標點, v, f"{k} 自帶標點，排版要歸畫面")
        self.assertIn("p.unguarded_caveat", APP)

    def test_畫面函式有定義而且被呼叫(self):
        self.assertIn("function renderPollution(d) {", APP)
        # 定義一次、呼叫兩次(輪詢那條與展開那條)。少接一邊的症狀是
        # 「展開的時候是空的，兩秒後才出現」或反過來，都不會報錯。
        self.assertEqual(len(re.findall(r"renderPollution\(", APP)), 3)

    def test_跟八維度共用同一個展開開關(self):
        self.assertIn(".dims.open ~ .pollution{display:block}", CSS)

    def test_畫面上不准把null印成0(self):
        # 這一條釘的是那一行判斷本身。改成 `r.radius || 0` 之類的寫法，
        # 畫面會靜默地把「算不出來」變成「沒有擴散」。
        self.assertIn("r.radius == null", APP)
        self.assertIn("擴散半徑算不出來", APP)

    def test_捲動位置在重畫之後要放回去(self):
        """**這一格捲得動，而它每 1 到 3 秒整塊換 innerHTML。**

        實測過:捲到底 450px，6.5 秒後 scrollTop 回到 0，而且節點已經
        不是同一個。症狀是第 3、4 筆永遠看不到，程式沒有任何錯誤 ——
        跟搜尋框吃掉使用者的字是同一個根因。
        """
        self.assertIn("keepScroll", APP, "重畫前沒有記下捲動位置")
        self.assertIn("list.scrollTop = Math.min(keepScroll", APP,
                      "放回去的時候沒有夾住上限，筆數變少會停在空白處")

    def test_捲得動這件事要看得見而且是量出來的(self):
        """內容塞得下的時候印一句「往下捲」是假的，所以那兩個判斷要量。

        **這一條第一版是假的守備**:它只檢查 `scrollHeight - clientHeight`
        有沒有出現在檔案裡，而那個算式在還原捲動位置那一行也有，
        所以把判斷寫死成 `true` 照樣會過。反向驗證第 4 次抓到。
        現在釘的是那兩個判斷本身。
        """
        # 2026-09-16 21:x 這一行本來釘死整個參數列。§12.2 那一格接進來
        # 之後，這支函式多收一個選擇器參數（兩格共用同一套捲動修正，
        # 不長第二份會分歧的實作），所以這裡只釘函式在不在 ——
        # 真正的守備是下面那三條判斷，它們沒有變。
        self.assertIn("function syncPlCut(list", APP)
        # 漸層要跟著捲動位置變。只看內容有沒有超出的版本，捲到底
        # 還是會把最後一筆的出處淡掉 —— 一個永遠亮著的「還有更多」
        # 跟沒有提示一樣沒用，而且它會蓋掉真的內容。截圖抓到的。
        self.assertIn("list.scrollHeight - list.clientHeight - list.scrollTop",
                      APP, "漸層沒有算捲動位置，到底了還會繼續切")
        self.assertIn('list.classList.toggle("cut", rest > 1)', APP)
        self.assertIn("plMore", APP)
        self.assertIn(".plMore", CSS)
        self.assertIn(".plList.cut", CSS, "被切一半要讀得出是「下面還有」")

    def test_捲動事件委派在只建立一次的容器上(self):
        """`.plList` 每次重畫都是新節點，逐次綁會累積成孤兒 listener。

        跟 `.blQ` 那次同一條。scroll 不冒泡，所以要走捕獲階段 ——
        少了那個 true，漸層就不會跟著捲動變，而且不會有錯誤訊息。
        """
        self.assertNotIn('.plList").addEventListener', APP)
        self.assertIn('box.addEventListener("scroll"', APP)
        self.assertIn("}, true);", APP, "scroll 不冒泡，沒有捕獲階段收不到")
        self.assertIn("box.dataset.scrollBound", APP, "沒有防重複綁定")

    def test_用到的class都有樣式(self):
        # 2026-09-14 的 --accent-dark 事件同一類:JS 用了、CSS 沒有，
        # 不報錯，只是那一塊變成沒有樣式的裸文字。
        used = set(re.findall(r'class="(pl[A-Za-z]+)"', APP))
        used |= set(re.findall(r'class="(pl[A-Za-z]+) ', APP))
        self.assertTrue(used)
        for c in used:
            self.assertIn(f".{c}", CSS, f"{c} 沒有樣式")


if __name__ == "__main__":
    unittest.main()
