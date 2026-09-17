#!/usr/bin/env python3
"""頂部不准把主畫面擠出去。

## 事故(2026-09-17 owner 開瀏覽器當場看到)

owner:「我到現在連 UI 都沒有看到完整精緻正確版」。打開之後第一眼
就是整個畫面被一張卡片佔滿，捲軸停在 0，看起來像 Widget 卡住了。

實測那條鏈:

    .card2 .say   1204px   rehydration 那張卡的內文，沒有高度上限
    .card2        1289px
    .cards        1326px
    .panel        1567px
    .top          1627px   而視窗只有 900px

`#lane`（主畫面）從 1627px 開始，完全在視窗外。

## 為什麼這個 bug 特別難發現

症狀是「主要內容看不到」，而那看起來像渲染失敗或資料沒來，
不像高度問題。`test_ui_contract` 驗接線、`test_ui_render` 驗
「畫出來的東西對不對」，兩組都不會紅 —— 因為東西都畫對了，
只是被推到視窗外面。

## 這一組守什麼，以及守不到什麼

守的是「有沒有上限」這個靜態事實。
**守不到「上限夠不夠小」** —— 那要真的量，而量要開瀏覽器。
量到的數字寫在上面那張表裡，這一組只確保那兩個上限沒有被拿掉。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "desktop" / "ui" / "app.css"


def _rule(css: str, selector: str) -> str:
    """抓出一條規則的內容。抓不到就炸，不回空字串。

    回空字串的話，「沒有這條規則」跟「規則是空的」在斷言裡
    長得一樣，而底下每一條都會以某種方式通過。
    """
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
    if not m:
        raise AssertionError(f"app.css 裡找不到規則 {selector!r}")
    return m.group(1)


class 沒有上限的內容不准決定畫面高度(unittest.TestCase):

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def test_建議卡的內文有上限(self):
        """那段文字是按「用這句」複製走的，不是拿來讀的。§11.4"""
        r = _rule(self.css, ".card2 .say")
        self.assertIn("max-height", r, "內文沒有上限，一張卡就能撐爆整個頂部")
        self.assertIn("overflow-y", r, "有上限而不能捲，內容會被吃掉")

    def test_頂部整塊有硬上限(self):
        """上面那條修已經發生過的，這條擋下一個。

        任何一塊新內容都可能再撐爆一次，而症狀看起來不像高度問題。
        """
        r = _rule(self.css, ".top")
        self.assertIn("max-height", r, "頂部沒有硬上限")
        self.assertIn("overflow-y", r)

    def test_頂部的上限是相對視窗不是寫死像素(self):
        """寫死像素的話，換一個視窗高度它又會擠爆或留一大塊空白。"""
        r = _rule(self.css, ".top")
        m = re.search(r"max-height:\s*([\d.]+)(vh|px)", r)
        self.assertIsNotNone(m, "頂部的 max-height 讀不出來")
        self.assertEqual(m.group(2), "vh", "頂部的上限寫死成像素了")
        self.assertLessEqual(float(m.group(1)), 60,
                             "頂部吃掉超過六成視窗，主畫面就沒剩多少了")

    def test_捲動不會傳染到外層(self):
        """卡片內文捲到底之後再捲，不該把整個 Widget 一起帶走。"""
        for sel in (".card2 .say", ".top"):
            with self.subTest(sel=sel):
                self.assertIn("overscroll-behavior", _rule(self.css, sel))


if __name__ == "__main__":
    unittest.main()
