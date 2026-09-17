#!/usr/bin/env python3
"""修正延遲畫在時間軸左緣。工程規格書 §13.3 的 TC-LT-01 到 TC-LT-03。

這一項先前的狀態在兩份文件裡不一樣，兩份都沒說錯，說的不是同一件事:

* `ROADMAP.md` P1.3 寫「已完成」,指的是 `latency.py` 算得出來、
  已經接進 `snap["latency"]`、`app.js` 在自我審計那一頁列得出來。
* 工程規格書 §13.3 把它排 P0,寫的是「只出現在自我審計那一頁的清單,
  要做的是把它畫在時間軸上」。

實測 2026-09-17:`grep -c data-lt desktop/ui/app.js` 回 0,
`latency` 在 `app.js` 只出現在 2615 行起那一段 `renderAudit`。
所以畫在線上那一半是真的沒做,這一組守的是那一半。

為什麼要畫在線上而不是留在清單裡,理由是 WIDGET_SPEC §5.1:
清單要人自己把「第幾段偏離」對回「那是什麼時候的事」,
壓在線上就沒有那個對照動作,看到的位置就是它發生的位置。

## 測法:從正本抽,不做第二份

`ltMarkFor()` 跟 `LT_KIND` 從 `desktop/ui/app.js` 抽出來丟進 node 跑。
抽不是複製:抽出來的是這個檔案當下的內容,那一段改了這裡就跟著動。
在 Python 裡重寫一份等價邏輯會多出第二個實作,而分歧的那天沒有人會發現
(`jsbridge.py` 檔頭記的就是這件事)。

## 這一組抓到的一個真 bug(2026-09-17)

`end` 原本判的是 `ep.recovery !== "STILL_OPEN"`,而 `kind` 判的是
`LT_KIND[ep.recovery] || "open"`。一個認不得的 `recovery` 會同時是
「還開著」(kind) 跟「已經收尾」(end),兩個標記互相矛盾,
而畫面上只看得到後者。改成 `end` 吃 `kind`,兩個永遠一致。

## 真實資料上畫出來看過(2026-09-17)

`tools/ui-render-check.py` 對 session `a280762a`(「Forseti 開發 V1」,
180 輪)渲染,數字逐一對得起來:

| 段 | 輪號 | 收尾方式 | 畫面內輪數 |
|---|---|---|---|
| 1 | 217-229 | SELF_RECOVERED | 13 |
| 2 | 239-287 | OWNER_CORRECTION | 49 |
| 3 | 308-337 | OWNER_CORRECTION | 30 |
| 4 | 362-386 | STILL_OPEN | 25 |

DOM 裡 `data-lt` 共 117 個 = 13+49+30+25,分佈
`owner` 79(49+30)、`self` 13、`open` 25。`.ltm` 元素同樣 117 個。
收尾端點 3 個,還開著那一段沒有,正是 TC-LT-02。console 零錯誤。

**TC-LT-03 的情況在真實資料上真的存在。** 同一份 DOM 裡,
第 368 輪同時帶 `data-cp="good"` 與 `data-lt="open"`,
兩個標記各自有載體(checkpoint 用 `::before`,偏離用 `.ltm` 元素),
並存不互相蓋。另外 11 輪同時帶分歧點的 inset 陰影與偏離標記。
184 輪裡 116 輪只有偏離標記、1 輪兩者都有,合計 117,
跟上面那張表的 13+49+30+25 對得起來。

## 反向驗證(2026-09-17 實跑,基準 15 passed)

1. `end` 拿掉 `kind !== "open"` 那一半 → 2 failed(還開著的被畫上收尾)
2. 區間判斷 `<`/`>` 改成 `<=`/`>=`(把端點排除) → 2 failed(每段頭尾漏標)
3. CSS 加一條 `.st[data-lt]::before` → 1 failed(搶了 .st 的偽元素)
4. 拿掉 `.st[data-lt="open"] .ltm` → 1 failed(JS 設得出而畫面隱形)

四次還原後 `app.js` sha256 都是 `c212cd76f1af2488`、
`app.css` 都是 `0a2c4ece12153c41`,跟改動前逐字元相同。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP_JS = REPO / "desktop" / "ui" / "app.js"
APP_CSS = REPO / "desktop" / "ui" / "app.css"


def _extract(src: str, start: str, end: str) -> str:
    """從 app.js 抽出一段。抓不到就炸,不回空字串。

    回空字串的話,底下每一條都會在「函式不存在」的情況下
    以某種方式通過或跳過,而那跟驗過了長得一樣。
    """
    i = src.find(start)
    if i < 0:
        raise AssertionError(f"app.js 裡找不到 {start!r}")
    j = src.find(end, i)
    if j < 0:
        raise AssertionError(f"app.js 裡 {start!r} 之後找不到結尾 {end!r}")
    return src[i:j + len(end)]


def _run_cases(cases: list[dict]) -> list:
    """把抽出來的那兩段丟進 node,對每個 case 跑一次 ltMarkFor。"""
    src = APP_JS.read_text(encoding="utf-8")
    kind = _extract(src, "const LT_KIND = {", "\n};")
    fn = _extract(src, "function ltMarkFor(", "\n}")
    script = (
        f"{kind}\n{fn}\n"
        f"const cases = {json.dumps(cases, ensure_ascii=False)};\n"
        "console.log(JSON.stringify("
        "cases.map((c) => ltMarkFor(c.n, c.eps))));"
    )
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("這台機器沒有 node,抽出來的那一段跑不了")
    r = subprocess.run([node, "-e", script], capture_output=True,
                       text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(f"node 跑不起來: {r.stderr.strip()}")
    return json.loads(r.stdout)


OWNER_EP = {"from_n": 10, "to_n": 14, "recovery": "OWNER_CORRECTION"}
SELF_EP = {"from_n": 20, "to_n": 22, "recovery": "SELF_RECOVERED"}
OPEN_EP = {"from_n": 30, "to_n": 40, "recovery": "STILL_OPEN"}


class TCLT01區間內每一輪都標得到(unittest.TestCase):
    """TC-LT-01:一段 OWNER_CORRECTION,該區間每一輪都有 data-lt="owner"。"""

    def test_區間內每一輪都是_owner(self):
        eps = [OWNER_EP]
        got = _run_cases([{"n": n, "eps": eps} for n in range(10, 15)])
        self.assertEqual(len(got), 5)
        for n, mark in zip(range(10, 15), got):
            with self.subTest(n=n):
                self.assertIsNotNone(mark, f"第 {n} 輪在區間內卻沒標")
                self.assertEqual(mark["kind"], "owner")

    def test_區間外不標(self):
        eps = [OWNER_EP]
        got = _run_cases([{"n": 9, "eps": eps}, {"n": 15, "eps": eps}])
        self.assertEqual(got, [None, None],
                         "區間外被標了,那會讓沒出事的輪看起來有事")

    def test_端點那兩輪算在區間內(self):
        """`>=` 跟 `<=` 寫成 `>` `<` 的話,每一段的頭尾會漏掉。

        漏的方向是把偏離顯示得比實際短,也就是「看起來比較不嚴重」。
        """
        eps = [OWNER_EP]
        got = _run_cases([{"n": 10, "eps": eps}, {"n": 14, "eps": eps}])
        self.assertTrue(all(m is not None for m in got),
                        "起點或終點那一輪漏標")

    def test_三種收尾各自對到自己的顏色(self):
        eps = [OWNER_EP, SELF_EP, OPEN_EP]
        got = _run_cases([{"n": 11, "eps": eps}, {"n": 21, "eps": eps},
                          {"n": 35, "eps": eps}])
        self.assertEqual([m["kind"] for m in got], ["owner", "self", "open"])


class TCLT02還開著的不畫收尾端點(unittest.TestCase):
    """TC-LT-02:一段 STILL_OPEN 延伸到最後,不畫收尾端點。

    畫了等於說「這裡結束了」,而那一段其實還開著。
    這個方向的錯是「看起來比實際好」,跟 probe 那一格同一類。
    """

    def test_still_open_的最後一輪沒有收尾端點(self):
        got = _run_cases([{"n": 40, "eps": [OPEN_EP]}])
        self.assertEqual(got[0]["kind"], "open")
        self.assertFalse(got[0]["end"],
                         "還開著的那一段被畫上收尾端點了")

    def test_收得回來的那兩種在最後一輪有收尾端點(self):
        got = _run_cases([{"n": 14, "eps": [OWNER_EP]},
                          {"n": 22, "eps": [SELF_EP]}])
        self.assertTrue(all(m["end"] for m in got),
                        "收得回來的那一段沒有畫出收尾")

    def test_區間中間不畫收尾端點(self):
        got = _run_cases([{"n": 12, "eps": [OWNER_EP]}])
        self.assertFalse(got[0]["end"])

    def test_認不得的收尾方式當成還開著(self):
        """認不得的值畫成「已經收尾」會讓人以為那段結束了。"""
        odd = {"from_n": 1, "to_n": 3, "recovery": "SOMETHING_NEW"}
        got = _run_cases([{"n": 3, "eps": [odd]}])
        self.assertEqual(got[0]["kind"], "open")
        self.assertFalse(got[0]["end"])

    def test_缺輪號的段落整段跳過(self):
        """`from_n` 或 `to_n` 是 null 的時候不能猜一個位置畫上去。"""
        bad = {"from_n": None, "to_n": 5, "recovery": "OWNER_CORRECTION"}
        got = _run_cases([{"n": 3, "eps": [bad]}])
        self.assertIsNone(got[0])


class TCLT03不跟既有標記搶偽元素(unittest.TestCase):
    """TC-LT-03:同一輪既是 checkpoint 又在偏離段內,兩個標記不互相覆蓋。

    `.st` 上的位置已經滿了:`::after` 是粉紅點的角標、
    `::before` 是 checkpoint、左緣的 inset 陰影是分歧點。
    再共用任何一個,後寫的會蓋掉前面的,而同時中獎的那一輪
    剛好是最該看清楚的那一輪。
    """

    def setUp(self):
        self.css = APP_CSS.read_text(encoding="utf-8")
        self.js = APP_JS.read_text(encoding="utf-8")

    def test_latency_用真實元素不用_st_的偽元素(self):
        import re
        # `]` 後面要直接接 `::` 才算搶 `.st` 的偽元素。
        # `.st[data-lt-end] .ltm::after` 中間隔著 `.ltm`,
        # 那是掛在自己身上的,不算。
        bad = re.findall(r"\.st\[data-lt[^\]]*\]::(?:before|after)", self.css)
        self.assertEqual(bad, [],
                         f"latency 搶了 .st 的偽元素: {bad}")

    def test_ltm_是真的建出來的元素(self):
        self.assertIn('ltm.className = "ltm"', self.js,
                      "app.js 沒有真的建 .ltm 元素")
        self.assertIn(".st .ltm{", self.css,
                      "app.css 沒有 .ltm 的規則")

    def test_checkpoint_跟粉紅點的偽元素沒被動到(self):
        """這兩條是既有行為。這一項不該把它們擠掉。"""
        self.assertIn(".st[data-cp]::before{", self.css,
                      "checkpoint 的 ::before 不見了")
        self.assertIn(".st[data-notes]::after{", self.css,
                      "粉紅點的 ::after 不見了")

    def test_三個值在_css_裡都有對應規則(self):
        """JS 設得出來而 CSS 沒有規則的話,那一段在畫面上是隱形的。"""
        for kind in ("owner", "self", "open"):
            with self.subTest(kind=kind):
                self.assertIn(f'[data-lt="{kind}"] .ltm{{', self.css,
                              f"data-lt={kind} 沒有對應的 CSS")

    def test_收尾端點掛在_ltm_自己身上(self):
        self.assertIn("[data-lt-end] .ltm::after{", self.css,
                      "收尾端點沒有掛在 .ltm 自己的偽元素上")

    def test_不擋點擊(self):
        """左緣那一條蓋在 .st 上,吃到點擊的話那一輪就打不開。"""
        block = self.css[self.css.index(".st .ltm{"):]
        block = block[:block.index("}")]
        self.assertIn("pointer-events:none", block,
                      ".ltm 會吃掉點擊,那一輪的面板就打不開了")


if __name__ == "__main__":
    unittest.main()
