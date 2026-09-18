#!/usr/bin/env python3
"""畫出來的東西對不對。這一組要開瀏覽器。

`test_js_symbols.py` 守「叫了但沒定義」，`test_ui_contract.py`
守「定義了但沒人叫」。兩組都是靜態比對，兩組都停在接線那一層。

接線對了之後還有一整類：**叫了、跑完了，畫面上那一格是空的、
是佔位字、或者數字不是資料裡那一個。** 這一組守那一類。

做法在 `tools/ui-render-check.py`，連同它三個繼承來的盲點
（Tauri 是假的、只看得到預設那一頁、看的是 DOM 不是像素）。

## 沒有 Chrome 的時候

`skipTest`，理由印出來。**不當成通過** —— 跳過跟通過在
pytest 的輸出裡是兩種字，而這個專案在防的正是
「驗不了被當成驗過了」。

這一組沒有進 `desktop/deploy.sh` 的守門。守門加一個要開瀏覽器
的相依，是部署策略的改動，不是實作規格，那要 owner 決定（B-15 同一類）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "ui-render-check.py"


def _load():
    """檔名有連字號，`import` 進不來，所以用檔案路徑載。

    載進來的模組要放進 `sys.modules`，不然它裡面的 dataclass
    在 Python 3.9 解析型別註記時找不到自己的模組，直接炸。
    （這一行是實測換來的，不是預防性寫法。）
    """
    spec = importlib.util.spec_from_file_location("forseti_ui_render_check",
                                                  TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forseti_ui_render_check"] = mod
    spec.loader.exec_module(mod)
    return mod


RC = _load()

APP_JS = REPO / "desktop" / "ui" / "app.js"


# 開一次瀏覽器十秒上下，所以整組共用同一次渲染。
# 共用的代價是每一條測試看的是同一張快照 —— 這裡可以接受，
# 因為這一組問的全都是「那一張快照上對不對」。
_SHOT = {"r": None, "err": None}


def _shot():
    if _SHOT["r"] is None and _SHOT["err"] is None:
        try:
            _SHOT["r"] = RC.render()
        except RC.CannotRun as e:
            _SHOT["err"] = str(e)
    if _SHOT["err"]:
        raise unittest.SkipTest(
            f"驗不了，不是通過：{_SHOT['err']}")
    return _SHOT["r"]


def tearDownModule():
    # 【2026-09-18】原本要清七八個暫存目錄(展開、五個分頁、動作鈕、
    # 輪詢)。那幾組連同它們驗的畫面一起退場,現在只剩兩張快照。
    for box in (_SHOT, _BURGER):
        r = box.get("r")
        if r is not None:
            shutil.rmtree(r.outdir, ignore_errors=True)


class RenderedOutputMatchesData(unittest.TestCase):
    """每一條對應 `ui-render-check.py` 裡的一組檢查。

    分成一條一條而不是一次跑 `run_all`，是為了紅的時候
    直接看得出壞在哪一類，不用去讀 findings 清單。
    """

    def _assert(self, fn):
        found = fn(_shot())
        if found:
            self.fail("\n" + "\n".join(str(f) for f in found))

    def test_渲染迴圈沒有整段炸掉(self):
        self._assert(RC.check_no_fatal_banner)

    def test_console_乾淨(self):
        self._assert(RC.check_no_console_errors)

    def test_佔位字都被換掉了(self):
        self._assert(RC.check_no_placeholder_left)

    def test_樹真的畫出了節點(self):
        self._assert(RC.check_tree_drew_nodes)

    def test_頁腳的線數點數是資料裡那個(self):
        self._assert(RC.check_footer_counts)

    def test_退不回去的時候不猜輪號(self):
        self._assert(RC.check_rescue_never_guesses)

    def test_確實讀到了東西而不是一片空白(self):
        """這一條守的是上面那八條本身。

        `_tag_text` 找不到元素會回 None，而好幾條檢查遇到 None
        是直接放行的 —— 那個設計是對的（找不到元素是接線問題，
        歸 `test_ui_contract.py` 管），但它有一個副作用：
        **哪天渲染整個沒發生，上面八條會一起變成綠的。**

        所以這裡直接釘住「有讀到值」。沒有這一條，
        整組測試會在最該紅的那一天全綠。
        """
        dom = RC.strip_fixture(_shot().dom)
        # 【2026-09-18】原本釘的是 vTemp / vBand / vProg / stat。
        # 前三個是溫度卡的,那一塊砍掉了。換成兩個一定要有東西的:
        # 頁腳的線數點數,跟頂上那行「在看哪一個 session」。
        for eid in ("stat", "sessName"):
            with self.subTest(eid=eid):
                v = RC._tag_text(dom, eid)
                self.assertIsNotNone(v, f"#{eid} 在渲染後的 DOM 裡找不到")
                self.assertTrue(v.strip(), f"#{eid} 是空的")


class ChecksThemselvesCatchThings(unittest.TestCase):
    """檢查本身抓不抓得到東西。不需要瀏覽器，用合成的 DOM。

    存在的理由：上面那一組全綠有兩種可能，一種是畫面對，
    一種是檢查根本不會紅。這一組把第二種排除掉。
    """

    def _fake(self, dom: str, fixture: dict):
        return RC.Render(dom=dom, console=[], fixture=fixture,
                         outdir=Path("/nonexistent"))

    def test_退不回去卻給輪號會紅(self):
        r = self._fake('<span id="rBack">退回去的話：<b>第 206 輪</b></span>'
                       '<p id="rCost">x</p>',
                       {"strands": {"rescue": {"can": False}}, "snapshot": {}})
        self.assertTrue(RC.check_rescue_never_guesses(r))

    # ---------------------------------------- 展開那四格的檢查本身

if __name__ == "__main__":
    unittest.main()


# ===================================================== 七個分頁

_BURGER = {"r": None, "err": None}


def _burger_shot():
    if _BURGER["r"] is None and _BURGER["err"] is None:
        try:
            _BURGER["r"] = RC.render(clicks=("#burgerBtn",))
        except RC.CannotRun as e:
            _BURGER["err"] = str(e)
    if _BURGER["err"]:
        raise unittest.SkipTest(f"驗不了，不是通過：{_BURGER['err']}")
    return _BURGER["r"]


class BurgerIsTheOnlyDoor(unittest.TestCase):
    """左上角那顆漢堡按下去，那個面板要真的打開。

    存在的理由是實測出來的，不是設計上的對稱：上面那一組按兩下，
    而第二下對 `hidden` 底下的元素照樣有效，所以**漢堡壞掉的話
    上面那一組仍然全綠**，畫面上卻沒有任何辦法切分頁。
    2026-09-17 實測把 `openPicker` 換成空函式，上面那一組全綠、
    這一條紅。
    """

    def test_按了漢堡面板就打開(self):
        f = RC.check_burger_opens_picker(_burger_shot())
        self.assertEqual(f, [], "\n".join(str(x) for x in f))

    def test_沒按的時候面板本來就是關的(self):
        """沒有這一條，上面那一條綠了也證明不了按下去有用。"""
        dom = RC.strip_fixture(_shot().dom)
        m = re.search(r'<div class="picker" id="picker"([^>]*)>', dom)
        self.assertIsNotNone(m)
        self.assertIn("hidden", m.group(1))


# ------------------------------------------ 另外五頁：誰畫的（同一個問題）
#
# `POLL_CHECKS` 那一組只問「在做什麼」那一頁。另外五頁 2026-09-17
# 各量過一次寫進 B-16，但沒有進常態檢查 —— 量過一次跟守著它
# 是兩件事，前者是一個會過期的數字，後者才是「這個行為不會再安靜地變」。
#
# **這一類不在這裡開五次瀏覽器。** `tools/ui-render-check.py` 自己
# 跑的時候會開（一頁一次，共五次，約 55 秒）。這一層守的是那張表
# 本身站不站得住、以及那支檢查抓不抓得到東西 —— 兩件用合成資料
# 就驗得到的事。把五次瀏覽器搬進 pytest 會讓每一次跑測試都多一分鐘，
# 而多出來的東西跟這一層要守的不是同一件事。


# ----------------------------------------- 第二次切進同一頁那一組

# 這一層跟上面那一層同一個分工：這裡守表與檢查函式，開瀏覽器那五次
# 在 `tools/ui-render-check.py` 的主流程裡（一頁一次，約 40 秒）。


# ------------------------------------- 連按同一頁那一組（中間沒切走）

# 這一層守表與檢查函式，開瀏覽器那五次在主流程裡。
#
# **這一組存在的理由不是多守一個功能，是守一句話的有效期限。**
# 上面那一組寫著「驗不到切走過」，理由是 `syncView()` 不比對 `view`。
# 那個理由哪天不成立，上面那一組的射程就變了 —— 在這一組出現之前，
# 沒有任何東西會在那一天紅。


