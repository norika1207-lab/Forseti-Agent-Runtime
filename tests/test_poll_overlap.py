#!/usr/bin/env python3
"""事件刷新不准重疊、遺失或退回 timer polling。

## 事故(2026-09-18，owner 開桌面版當場看到)

owner:「build 給我看桌面版」。開起來是視窗在、整片黑、
底部一個小字「啟動中」，而且一直維持那樣。

實測:

* `setInterval(tick, 2000)` 兩秒一輪
* `strands` 在真實資料上 17.6 秒(冷)／6.7 秒(熱)
* `ps` 顯示 App 跑了 5 分 50 秒，而它底下的 Python 子行程只有 8 秒大

也就是每一輪都在上一輪還沒回來的時候又起一個 Python，
八九個同時跑互相搶 CPU，於是每一個更慢、累積得更多。
**它不是慢，是永遠不會完成。**

## 為什麼這個症狀特別難判

`fatal()` 沒有被觸發，因為 invoke 既沒成功也沒拋錯，它還在跑。
所以畫面上沒有任何錯誤訊息，只有一片黑 ——
而那跟「資料還沒來」「渲染壞掉」「App 當掉」長得一模一樣。

## 這一組守什麼

守的是「有沒有防重疊」與「旗標會不會被放回去」。
守不到「strands 夠不夠快」—— 那是另一件事，
17.6 秒本身仍然違反工程規格書 §3.1 寫的「0.1 到 3 秒」。
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "desktop" / "ui" / "app.js"


class 事件刷新不准重疊(unittest.TestCase):

    def setUp(self):
        self.js = JS.read_text(encoding="utf-8")

    def test_有防重疊的旗標(self):
        self.assertIn("let inFlight", self.js, "沒有防重疊的旗標")

    def test_執行中事件只記一個待刷新(self):
        """事件到達時不能再起子行程，也不能安靜遺失。"""
        m = re.search(r"async function tick\(\)\s*\{(.{0,400})", self.js, re.S)
        self.assertIsNotNone(m, "找不到 tick()")
        head = m.group(1)
        self.assertIn("if (inFlight)", head,
                      "重疊檢查不在 tick 開頭，擋不住起子行程")
        self.assertIn("refreshPending = true", head,
                      "執行中的事件被丟掉，完成後不會補刷新")
        self.assertIn("return", head)

    def test_旗標一定放得回去(self):
        """放在 finally，不放在 try 的結尾。

        拋錯的時候旗標留在 true，之後每一輪都被跳過，
        畫面從此不再更新 —— 而那跟「一切正常沒有變化」長得一樣。
        """
        m = re.search(r"\}\s*finally\s*\{([^}]*)\}", self.js, re.S)
        self.assertIsNotNone(m, "tick() 沒有 finally")
        self.assertIn("inFlight = false", m.group(1),
                      "旗標不是在 finally 放回去的")

    def test_等太久用單次timer顯示不是polling(self):
        import re
        self.assertIn("slowSince", self.js, "沒有量它等了多久")
        self.assertRegex(self.js, r"slowTimer\s*=\s*setTimeout\(")
        self.assertIn("clearTimeout(slowTimer)", self.js)

    def test_訂閱既有rust事件而且先訂閱再首次刷新(self):
        self.assertIn('listen("forseti://changed", repositoryChanged)', self.js)
        body = re.search(r"async function startRefresh\(\)\s*\{(.*?)\n\}",
                         self.js, re.S)
        self.assertIsNotNone(body)
        code = body.group(1)
        self.assertLess(code.index('listen("forseti://changed"'),
                        code.index("requestRefresh({ refreshFoundation: true })"))

    def test_同一burst用microtask合併(self):
        self.assertIn("let refreshScheduled = false", self.js)
        self.assertIn("queueMicrotask", self.js)
        self.assertIn("if (inFlight || refreshScheduled) return", self.js)

    def test_完成後只補待處理刷新(self):
        m = re.search(r"\}\s*finally\s*\{(.*?)\n  \}", self.js, re.S)
        self.assertIsNotNone(m)
        self.assertIn("inFlight = false", m.group(1))
        self.assertIn("if (refreshPending) requestRefresh()", m.group(1))

    def test_產品碼沒有背景輪詢(self):
        self.assertNotRegex(self.js, r"setInterval\s*\(")


if __name__ == "__main__":
    unittest.main()
