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
        p = D.pollution_panel()
        self.assertEqual(sum(1 for r in p["rows"] if r["guarded"]), p["guarded"])

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
