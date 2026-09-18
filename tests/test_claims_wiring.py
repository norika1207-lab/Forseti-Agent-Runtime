#!/usr/bin/env python3
"""宣稱查現實的結果，有沒有真的走到畫面上。

## 為什麼要有這一組

`desktop_api.verified_claims()` 從 2026-09-14 就在跑，`claims.py` 真的去
stat 磁碟，結果寫進 `row["claims"]`。**而 `app.js` 一個字都沒讀它。**
後端算了整整兩天，畫面上零。

那是這個專案自己在抓的那種失敗：看起來像有在跑，實際上沒有到達。
所以這一組守的不是「函式會不會回值」，是「回的值有沒有人用」。

## 三件事分開測

靜態　畫面有沒有讀、class 有沒有定義、標籤有沒有講過頭
動態　`claim_total` 是不是真的從 rows 算出來的、去重有沒有生效

第三件是標籤。UNKNOWN 的意思是驗證器搆不到，不是它說謊
（`claims.can_refute()` 的規則）。把 UNKNOWN 寫成「說謊」，
等於用這個面板犯一次 §32 講太滿 —— 而那正是它在抓的東西。
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "desktop" / "ui"
JS = (UI / "app.js").read_text(encoding="utf-8")
CSS = (UI / "app.css").read_text(encoding="utf-8")
API = (ROOT / "apps" / "forseti-cli" / "desktop_api.py").read_text(encoding="utf-8")

#: 這段文字出現在使用者看得到的地方就是問題。
#: UNKNOWN 不是說謊，把它講成說謊比不顯示更糟。
OVERSTATED = ("說謊", "騙人", "造假", "撒謊")


class TestReachesScreen(unittest.TestCase):
    """後端算的那個東西，畫面有沒有讀。

    【2026-09-18 砍到剩三個】原本兩個。`claim_total` 那個總數住在
    頂部的統計列(`.subs`),那一塊連同溫度卡整批退場,所以
    「畫面有沒有讀 claim_total」不再是一個問題 —— 沒有地方讀它。
    後端還在寫,下面 `test_backend_still_writes_both` 照舊守著,
    畫面那一半的斷言拿掉。

    留下來的 `s.claims` 是時間軸上每一輪的宣稱,那個還在畫。
    """

    def test_row_claims_is_read_by_ui(self):
        self.assertIn("s.claims", JS,
                      "desktop_api 把結果寫進 row['claims']，app.js 沒讀它。"
                      "後端算了沒人用，等於沒做")

    def test_backend_still_writes_both(self):
        self.assertIn('row["claims"] = uniq', API,
                      "row['claims'] 不見了，或改了寫法，畫面那一塊會永遠空白")
        self.assertIn('snap["claim_total"]', API)


class TestStylesExist(unittest.TestCase):
    """JS 用到的 class，CSS 有沒有。

    少一條不會報錯，只會讓那塊變成沒有樣式的裸文字 ——
    跟 test_ui_contract 守的是同一類靜默失敗。
    """

    CLASSES = ("claimchk", "claimlist", "cst", "csub", "cev")

    def test_every_class_defined(self):
        for c in self.CLASSES:
            with self.subTest(cls=c):
                self.assertRegex(
                    CSS, r"\." + c + r"[\s,{:.]",
                    f"app.js 用了 .{c}，app.css 沒有定義它")

    def test_open_state_defined(self):
        self.assertIn(".claimlist.open", CSS,
                      "清單靠 .open 展開，沒有這條就永遠打不開")


class TestLabelDoesNotOverstate(unittest.TestCase):
    """標籤不准把「查不到」講成「說謊」。

    【2026-09-18】那句「查不到不等於它說謊」的說明住在統計列上,
    統計列退場它也跟著走。守那一句的斷言拿掉,
    守文案不准把 UNKNOWN 講成說謊的那條留著 ——
    它掃的是時間軸上還在畫的那些宣稱。
    """

    def test_no_overstated_words_near_claims(self):
        # 只看跟 claim 有關的那幾段，不掃全檔 ——
        # 別處講「誠實的失敗，不是騙人」是對的，不該被這條擋掉。
        block = "\n".join(
            ln for ln in JS.splitlines()
            if "claimHits" in ln or "claim_total" in ln or "宣稱" in ln)
        for w in OVERSTATED:
            with self.subTest(word=w):
                # 「不是騙人」這種否定句合法，肯定句不合法。
                for m in re.finditer(re.escape(w), block):
                    before = block[max(0, m.start() - 6):m.start()]
                    self.assertIn(
                        "不", before,
                        f"claim 相關文案出現肯定的「{w}」。"
                        "UNKNOWN 是驗證器搆不到，不是它說謊")

class TestRealSnapshot(unittest.TestCase):
    """真的跑一次，驗算出來的數字跟去重。

    沒有 session 資料的機器會 skip —— 一個在別人機器上永遠紅的
    測試，下場是被習慣性忽略，那比沒有測試更糟。
    """

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))
        try:
            import desktop_api
            cls.snap = desktop_api.strands("")
        except Exception as e:                            # noqa: BLE001
            raise unittest.SkipTest(f"跑不起來：{e}")
        if not cls.snap.get("rows"):
            raise unittest.SkipTest("這台機器沒有 session 資料")

    def test_total_matches_rows(self):
        want = sum(len(r.get("claims") or []) for r in self.snap["rows"])
        self.assertEqual(self.snap.get("claim_total"), want,
                         "claim_total 跟 rows 裡實際有的對不上。"
                         "一個自己算的總數，會跟明細各講各的")

    def test_no_duplicates_within_a_row(self):
        for r in self.snap["rows"]:
            hits = r.get("claims") or []
            keys = [(h.get("subject"), h.get("state")) for h in hits]
            with self.subTest(n=r.get("n")):
                self.assertEqual(len(keys), len(set(keys)),
                                 "同一輪出現重複的宣稱，去重沒生效")

    def test_strength_is_a_known_level(self):
        import claims as C
        for r in self.snap["rows"]:
            for h in (r.get("claims") or []):
                with self.subTest(subject=h.get("subject")):
                    self.assertIn(h.get("strength"), C.STRENGTH,
                                  "強度不是 §7.2 的 E0-E4，畫面會顯示看不懂的字")


if __name__ == "__main__":
    unittest.main()
