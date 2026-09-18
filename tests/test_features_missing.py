#!/usr/bin/env python3
"""功能盤點的「還沒做」那一半。owner 2026-09-17 要的。

原話:「現在盤點給我看，到底有做哪些，沒做那些，全部列出清單來，
我要有功能說明，列在畫面上」。

## 為什麼這一組存在

`features()` 先前只列做好的,而且 `total` 跟 `alive` 都是 21。
**一張 21/21 全綠的表,看起來像做完了。** 而實際上八個 X-Ray 視圖
只有三個、紫點下不了判決、換模型會不會變差一次都沒量過。

一張只列成功的表,跟一張造假的表,在讀的人眼裡是一樣的東西。
這一組守的就是「兩份一定要一起出」。

## 四種擋法為什麼要分開

`NO_CODE`(一行都沒有)、`JS_ONLY`(有實作沒接上)、
`NO_DATA`(等資料長出來)、`OWNER`(等你決定)。

混成一句「還沒做」會讓人以為它們可以用同一種方式推進。
實際上第一種要從頭寫、第二種要先決定接了會不會得到一排
NOT_APPLICABLE、第三種做了只會輸出噪音、第四種工程上動不了。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import desktop_api as D  # noqa: E402

APP_JS = ROOT / "desktop" / "ui" / "app.js"
APP_CSS = ROOT / "desktop" / "ui" / "app.css"


class 兩份一定要一起出(unittest.TestCase):

    def setUp(self):
        self.f = D.features()

    def test_回傳裡兩份都在(self):
        self.assertIn("items", self.f)
        self.assertIn("missing", self.f)
        self.assertGreater(len(self.f["missing"]), 0,
                           "還沒做的那一份是空的。八個 X-Ray 視圖只有三個，"
                           "這個數字不可能是零")

    def test_做好的那份不准把還沒做的算進分母(self):
        """`total` 是「證明得了它是活的」那幾項，不含還沒做的。

        混進去的話通過率會變難看，但那不是重點 ——
        重點是兩種東西的驗收方式不同:一個要跑得出真實數字，
        一個只要說得出被什麼擋住。
        """
        self.assertEqual(self.f["total"], len(self.f["items"]))
        names = {i["name"] for i in self.f["items"]}
        miss = {m["name"] for m in self.f["missing"]}
        self.assertEqual(names & miss, set(), "同一項同時出現在兩份裡")


class 每一筆都說得出被什麼擋住(unittest.TestCase):

    def setUp(self):
        self.miss = D.features()["missing"]

    def test_四個欄位一個都不能少(self):
        for m in self.miss:
            with self.subTest(name=m.get("name")):
                for k in ("name", "what", "spec", "barrier", "blocked"):
                    self.assertTrue(m.get(k), f"{m.get('name')} 缺 {k}")

    def test_功能說明不是一句話帶過(self):
        """owner 要的是功能說明，不是標題。"""
        for m in self.miss:
            with self.subTest(name=m["name"]):
                self.assertGreater(len(m["what"]), 25,
                                   "說明太短，看不出它是什麼")

    def test_擋住的理由要具體(self):
        """「還沒排到」不算理由。"""
        for m in self.miss:
            with self.subTest(name=m["name"]):
                self.assertGreater(len(m["blocked"]), 15)
                for lazy in ("還沒排到", "之後再說", "有空再"):
                    self.assertNotIn(lazy, m["blocked"])

    def test_每一筆都指得回條文(self):
        for m in self.miss:
            with self.subTest(name=m["name"]):
                self.assertTrue(
                    any(t in m["spec"] for t in ("§", "Vol", "F0")),
                    f"{m['name']} 的 spec {m['spec']!r} 指不回任何條文")

    def test_四種擋法都是認得的那四種(self):
        for m in self.miss:
            with self.subTest(name=m["name"]):
                self.assertIn(m["barrier"], D.BARRIER_LABEL)

    def test_四種都有東西不然分類是裝飾(self):
        """只剩一種的時候，分類就沒有意義了。"""
        kinds = {m["barrier"] for m in self.miss}
        self.assertGreaterEqual(len(kinds), 3,
                                f"只用到 {kinds}，分類等於裝飾")


if __name__ == "__main__":
    unittest.main()
