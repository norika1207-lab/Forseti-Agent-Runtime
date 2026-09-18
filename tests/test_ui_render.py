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


def _one_int(pat: str, why: str) -> int | None:
    """從 `app.js` 抽一個數字出來。抽不到、或抽到不只一處，回 None。

    **不在這個檔案裡抄一份。** 抄的話 `app.js` 改了之後這一組
    仍然全綠，而它守的那個關係已經不成立了 —— 那正是這個
    專案裡「過期的狀態檔」那一類問題。

    **不只一處也要回 None，這是實測踩到的。** 2026-09-17 寫
    `workBusy()` 的註解時，把 `setInterval(tick, 2000)` 原樣寫進
    註解裡，於是這裡抓到的是**註解裡那個**，不是真正在跑的那一行
    —— 而 `re.search` 只回第一個，完全不會告訴你有第二個。
    哪天有人改了真的那行卻沒改註解，這裡會安靜地拿到舊值，
    而底下每一條比大小的斷言照樣綠。
    """
    ms = re.findall(pat, APP_JS.read_text(encoding="utf-8"), re.S)
    return int(ms[0]) if len(ms) == 1 else None


# 輪詢多久重畫一次。
POLL_MS = _one_int(r"setInterval\(tick, (\d+)\)", "輪詢間隔")

# 按了第一下之後，待確認狀態自己撐多久（`wireActs` 的還原計時器）。
ARM_WINDOW_MS = _one_int(
    r"armed = false; b\.textContent = label;.*?\}, (\d+)\);", "確認窗")

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


# 展開之後那一張，跟上面那一張是**兩次瀏覽器**。
#
# 展開是一次狀態轉換，同一張快照上沒有「展開前」跟「展開後」
# 兩種樣子，所以不能共用。代價是整組多開一次瀏覽器（十秒上下）。
_SHOT_X = {"r": None, "err": None}


def _shot_x():
    if _SHOT_X["r"] is None and _SHOT_X["err"] is None:
        try:
            _SHOT_X["r"] = RC.render(clicks=RC.EXPANDED_CLICKS)
        except RC.CannotRun as e:
            _SHOT_X["err"] = str(e)
    if _SHOT_X["err"]:
        raise unittest.SkipTest(f"驗不了，不是通過：{_SHOT_X['err']}")
    return _SHOT_X["r"]


def tearDownModule():
    for box in (_SHOT, _SHOT_X):
        r = box.get("r")
        if r is not None:
            shutil.rmtree(r.outdir, ignore_errors=True)
    # 分頁那幾次的暫存目錄（定義在這個檔案後半）。不清的話
    # 每跑一次留下七個目錄，一個十幾 MB。
    _cleanup_tabs()


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

    def test_溫度與證據覆蓋率是資料裡那個(self):
        self._assert(RC.check_temperature)

    def test_活動寫入目標三個數字是資料裡那三個(self):
        self._assert(RC.check_progress_三軸)

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
        for eid in ("vTemp", "vBand", "vProg", "stat"):
            with self.subTest(eid=eid):
                v = RC._tag_text(dom, eid)
                self.assertIsNotNone(v, f"#{eid} 在渲染後的 DOM 裡找不到")
                self.assertTrue(v.strip(), f"#{eid} 是空的")


class ExpandedPagesMatchData(unittest.TestCase):
    """按一下展開之後那四格，畫出來的東西對不對。

    這四格（Blast、Identity、Workflow、Probe）先前**只有靜態接線
    在守** —— `test_js_symbols.py` 守「叫了但沒定義」、
    `test_ui_contract.py` 守「定義了但沒人叫」，兩組都停在接線那層，
    而 2026-09-14 那次整頁是死的，這兩組全綠。

    按的是真的那個元素（`#vWhy`），事件走 `app.js` 自己註冊的
    listener。**這一組沒有直接呼叫任何 render 函式** ——
    直接呼叫驗到的是函式，不是那一下按了會發生什麼。
    差別與限制寫在 `tools/ui-render-check.py` 檔頭盲點二。

    **這一組驗得到的是「按完之後畫面上是對的」，不是「是那一下
    按的造成的」。** 實測（2026-09-17）：那四格有兩條路會畫它們，
    拿掉任何一條都還是綠的，兩條都拿掉才紅。盲點二之二寫著原因。
    """

    def _assert(self, fn):
        found = fn(_shot_x())
        if found:
            self.fail("\n" + "\n".join(str(f) for f in found))

    def test_展開那一下真的發生了(self):
        self._assert(RC.check_expanded_opened)

    def test_四格畫出來的列數是資料裡那個(self):
        self._assert(RC.check_expanded_row_counts)

    def test_波及範圍的檔數邊數是資料裡那兩個(self):
        self._assert(RC.check_blast_header_counts)

    def test_展開之後渲染迴圈沒有炸掉(self):
        self._assert(RC.check_no_fatal_banner)

    def test_展開之後_console_乾淨(self):
        self._assert(RC.check_no_console_errors)

    def test_沒按的時候這四格本來就不在(self):
        """守的是上面那幾條的前提。

        如果這四格**沒按也在**，那上面那幾條綠了也證明不了
        「按下去有用」—— 它們驗到的會是本來就畫好的東西。
        這一條拿沒按的那張快照（`_shot()`）反過來釘住這件事。
        """
        dom = RC.strip_fixture(_shot().dom)
        for _k, cls, _r, _lk, zh in RC.EXPANDED_BOXES:
            with self.subTest(cls=cls):
                self.assertIsNone(
                    RC._box_html(dom, cls),
                    f"沒按就看得到「{zh}」，那上面那幾條驗的不是按出來的東西")

    def test_四格真的有列而不是空殼(self):
        """守的是 `check_expanded_row_counts` 本身。

        那一條比的是「資料幾列、畫面幾列」，而資料是 0 列的時候
        畫面 0 列也相等 —— 兩邊一起是空的會通過。
        真實資料上這四格都有東西，所以這裡直接釘住有列。
        哪天真的變成 0，這條會紅，然後由人去看是資料沒了還是畫面死了。
        """
        dom = RC.strip_fixture(_shot_x().dom)
        for _k, cls, row_cls, _lk, zh in RC.EXPANDED_BOXES:
            with self.subTest(cls=cls):
                frag = RC._box_html(dom, cls)
                self.assertIsNotNone(frag, f"「{zh}」那一格不在")
                self.assertGreater(
                    RC._count_class(frag, row_cls), 0,
                    f"「{zh}」那一格在，可是一列都沒有")


class ChecksThemselvesCatchThings(unittest.TestCase):
    """檢查本身抓不抓得到東西。不需要瀏覽器，用合成的 DOM。

    存在的理由：上面那一組全綠有兩種可能，一種是畫面對，
    一種是檢查根本不會紅。這一組把第二種排除掉。
    """

    def _fake(self, dom: str, fixture: dict):
        return RC.Render(dom=dom, console=[], fixture=fixture,
                         outdir=Path("/nonexistent"))

    def test_溫度對不上會紅(self):
        r = self._fake('<span id="vTemp">99.9</span><span id="vBand">安靜 證據 92%</span>',
                       {"strands": {"temp": {"c": 36.9, "coverage": 0.92}},
                        "snapshot": {}})
        self.assertTrue(RC.check_temperature(r))

    def test_溫度對得上不會紅(self):
        r = self._fake('<span id="vTemp">36.9</span><span id="vBand">安靜　證據 92%</span>',
                       {"strands": {"temp": {"c": 36.9, "coverage": 0.92}},
                        "snapshot": {}})
        self.assertEqual(RC.check_temperature(r), [])

    def test_算不出溫度卻給了數字會紅(self):
        r = self._fake('<span id="vTemp">36.9</span><span id="vBand"></span>',
                       {"strands": {"temp": {"c": None}}, "snapshot": {}})
        self.assertTrue(RC.check_temperature(r))

    def test_後端算得出目標進度而畫面寫死未知會紅(self):
        """這一條今天在真畫面上是綠的，而且綠得不是因為接對了。

        `app.js` 的 `renderVitals` 把「目標 未知」寫死在字串裡，
        從來沒有讀過 `progress.goal`。今天 `progress.goal`
        永遠是 null，所以兩邊剛好一致 —— 那是巧合不是機制。

        真畫面驗不到這件事（資料永遠是 null），所以在這裡用
        合成資料釘住：哪天後端算得出目標進度，這一條會紅。
        """
        r = self._fake('<p id="vProg">已驗證進度　活動 120　寫入 70　目標 未知</p>',
                       {"strands": {"progress": {"activity": 120, "task": 70,
                                                 "goal": 42}},
                        "snapshot": {}})
        found = RC.check_progress_三軸(r)
        self.assertTrue(found)
        self.assertIn("目標", found[0].where)

    def test_退不回去卻給輪號會紅(self):
        r = self._fake('<span id="rBack">退回去的話：<b>第 206 輪</b></span>'
                       '<p id="rCost">x</p>',
                       {"strands": {"rescue": {"can": False}}, "snapshot": {}})
        self.assertTrue(RC.check_rescue_never_guesses(r))

    # ---------------------------------------- 展開那四格的檢查本身

    def _expanded(self, blast_rows=2, extra="", opened=True, files=239,
                  edges=353, data_rows=2):
        """拼一份展開之後的合成 DOM 加對應的 fixture。"""
        rows = "".join('<div class="blRow blHit" data-blast="x">'
                       '<span class="blF">a</span></div>'
                       for _ in range(blast_rows))
        dims = 'class="dims open"' if opened else 'class="dims"'
        dom = (f'<div {dims}></div>'
               f'<div class="blast"><p class="hd">波及範圍'
               f'<span class="sub">{files} 個檔案　{edges} 條依賴邊</span></p>'
               f'{rows}{extra}</div>')
        fx = {"strands": {"blast": {
            "has": True, "files": 239, "edges": 353,
            "top": [{"target": f"t{i}"} for i in range(data_rows)]}},
            "snapshot": {}}
        return self._fake(dom, fx)

    def test_列數對不上會紅(self):
        r = self._expanded(blast_rows=1, data_rows=2)
        self.assertTrue(RC.check_expanded_row_counts(r))

    def test_列數對得上不會紅(self):
        r = self._expanded(blast_rows=2, data_rows=2)
        self.assertFalse(RC.check_expanded_row_counts(r))

    def test_資料說有畫面印沒有資料會紅(self):
        """最重要的一條：資料算得出來，畫面卻走了 fallback 那一版。

        這是整組最容易發生又最難用眼睛看出來的症狀 ——
        「沒有資料」那一版本來就是合法畫面，看的人分不出
        它是資料真的沒有，還是前端讀錯了鍵。
        """
        r = self._fake(
            '<div class="dims open"></div>'
            '<div class="blast"><p class="hd">波及範圍'
            '<span class="none">沒有資料，不是沒問題</span></p></div>',
            {"strands": {"blast": {"has": True, "files": 1, "edges": 1,
                                   "top": [{"target": "a"}]}},
             "snapshot": {}})
        self.assertTrue(RC.check_expanded_row_counts(r))

    def test_資料說沒有畫面印沒有資料不會紅(self):
        """`has` 是 false 的時候，印「沒有資料」是對的行為，不准判紅。"""
        r = self._fake(
            '<div class="dims open"></div>'
            '<div class="blast"><p class="hd">波及範圍'
            '<span class="none">算不出來</span></p></div>',
            {"strands": {"blast": {"has": False, "why": "算不出來"}},
             "snapshot": {}})
        self.assertFalse(RC.check_expanded_row_counts(r))

    def test_沒展開會紅(self):
        r = self._expanded(opened=False)
        found = RC.check_expanded_opened(r)
        self.assertTrue(found)
        self.assertIn("沒有打開", "".join(str(f) for f in found))

    def test_整塊不在會紅而不是安靜放行(self):
        """這一條守的是「四條一起變綠」那個方向。

        `check_expanded_row_counts` 遇到找不到的那一塊是放行的，
        所以整塊消失必須由 `check_expanded_opened` 喊出來，
        不然那一天整組全綠而畫面上什麼都沒有。
        """
        r = self._fake('<div class="dims open"></div>',
                       {"strands": {}, "snapshot": {}})
        found = RC.check_expanded_opened(r)
        self.assertEqual(len(found), len(RC.EXPANDED_BOXES))

    def test_檔數邊數對不上會紅(self):
        r = self._expanded(files=104, edges=130)
        found = RC.check_blast_header_counts(r)
        self.assertTrue(found)

    def test_檔數邊數對得上不會紅(self):
        self.assertFalse(RC.check_blast_header_counts(self._expanded()))

    def test_數列數不會把別的_class_數進去(self):
        """`blRow` 用字串包含比會連 `blRowHead` 一起數進去。

        這種多數一列的錯，症狀是「畫面多畫了一行」，
        而實際上是測試自己算錯 —— 假警報比漏抓更快讓人不看這組測試。
        """
        frag = ('<div class="blRow blHead"></div>'
                '<div class="blRow blHit"></div>'
                '<div class="blRowHead"></div>')
        self.assertEqual(RC._count_class(frag, "blHit"), 1)
        self.assertEqual(RC._count_class(frag, "blHead"), 1)

    def test_巢狀的_div_不會讓那一塊提早結束(self):
        """`_box_html` 要自己配對 div。

        抓到第一個 `</div>` 就停的話，每一格都只會拿到開頭那一行，
        於是「列數」永遠是 0 —— 那會變成一條永遠紅的斷言，
        比永遠綠的更快被人關掉。
        """
        dom = ('<div class="blast"><div class="blRow blHit">'
               '<span>a</span></div><div class="blRow blHit"></div></div>'
               '<div class="idn"></div>')
        frag = RC._box_html(dom, "blast")
        self.assertEqual(RC._count_class(frag, "blHit"), 2)
        self.assertNotIn("idn", frag)

    def test_fixture_那一段不會被當成畫面(self):
        """內嵌的 fixture JSON 要先拿掉。

        不拿掉的話「畫面上有沒有這個數字」永遠命中 fixture 自己，
        於是那幾條斷言永遠綠 —— 一條永遠綠的斷言比沒有斷言糟。
        """
        dom = ('<script type="application/json" id="fx">{"strands":'
               '{"temp":{"c":36.9}}}</script><span id="vTemp">--</span>')
        self.assertNotIn("36.9", RC.strip_fixture(dom))


if __name__ == "__main__":
    unittest.main()


# ===================================================== 七個分頁

# 一頁一次瀏覽器，用到才開。
#
# 換分頁是一次狀態轉換，同一張快照上沒有七頁的樣子
# （`syncView()` 每次都把 `#lane` 整個清掉），所以**不能共用**。
# 代價是這一組最多開六次瀏覽器，一次十秒上下。
_TABS: dict = {}


def _tab_shot(view: str):
    box = _TABS.setdefault(view, {"r": None, "err": None})
    if box["r"] is None and box["err"] is None:
        try:
            box["r"] = RC.render(clicks=RC.tab_clicks(view))
        except RC.CannotRun as e:
            box["err"] = str(e)
    if box["err"]:
        raise unittest.SkipTest(f"驗不了，不是通過：{box['err']}")
    return box["r"]


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


# 動作鈕那一次：切到「在做什麼」，按任務卡第一顆鈕的**第一下**。
#
# **第二下不按。** 第一下只是把鈕改成待確認，一個指令都不發
# （`app.js` 的 `wireActs`）；第二下才 `invoke("act")`，而那一下
# 在真的 App 裡會往帳本寫東西。harness 的 fixture 剛好沒有 `act`
# 這把鑰匙，但這一組**不靠那件事** —— 靠 stub 的形狀來保證安全的話，
# 哪天有人往 fixture 補一個 `act`，這組測試就默默變成會執行。
#
# `budget_ms` 用 `ACT_BUDGET_MS` 不是預設值，理由在那個常數上面：
# 照相的時刻必須跨過一次輪詢，否則抓不到「輪詢把待確認沖掉」那個 bug。
_ACT = {"r": None, "err": None}


def _act_shot():
    if _ACT["r"] is None and _ACT["err"] is None:
        try:
            _ACT["r"] = RC.render(clicks=RC.ACT_CLICKS, spy=True,
                                  budget_ms=RC.ACT_BUDGET_MS)
        except RC.CannotRun as e:
            _ACT["err"] = str(e)
    if _ACT["err"]:
        raise unittest.SkipTest(f"驗不了，不是通過：{_ACT['err']}")
    return _ACT["r"]


def _cleanup_tabs():
    for box in list(_TABS.values()) + [_BURGER, _ACT, _POLL]:
        r = box.get("r")
        if r is not None:
            shutil.rmtree(r.outdir, ignore_errors=True)


class TabsMatchData(unittest.TestCase):
    """底下那幾個分頁，畫出來的數字與列數等於資料裡那些。

    這一組補的是 5o 那一輪自己寫下的那一句：展開那四格驗過了，
    **底下七個分頁仍然沒有驗**，因為它們是 `.vw` 換 `view` 變數
    再重畫，跟展開不同一條路。

    入口是漢堡不是分頁列：七顆 `.vw` 住在 `#picker` 裡，
    而 `#picker` 在 `index.html:106` 帶著 `hidden`。所以這一組
    每一次按兩下（`RC.tab_clicks`）。

    **這一組驗不到漢堡是不是通的。** `HTMLElement.click()` 對
    `hidden` 底下的元素照樣派送事件 —— 2026-09-17 實測：不按漢堡
    直接按 `.vw` 照樣全綠，把漢堡的 listener 換成空函式照樣全綠。
    守那件事的是底下 `BurgerIsTheOnlyDoor`，問的是不同的問題。
    """

    def _one(self, view: str):
        tab = {t.view: t for t in RC.TABS}[view]
        r = _tab_shot(view)
        return r, tab

    def _assert_clean(self, view: str):
        r, tab = self._one(view)
        for fn in (RC.check_no_fatal_banner, RC.check_no_console_errors):
            self.assertEqual(fn(r), [], "\n".join(str(x) for x in fn(r)))
        f = RC.check_tab_switched(r, tab)
        self.assertEqual(f, [], "\n".join(str(x) for x in f))
        f = RC.check_tab_values(r, tab)
        self.assertEqual(f, [], "\n".join(str(x) for x in f))

    def test_在做什麼那一頁(self):
        self._assert_clean("work")

    def test_功能那一頁(self):
        self._assert_clean("feat")

    def test_讀文件那一頁(self):
        self._assert_clean("spec")

    def test_自我審計那一頁(self):
        self._assert_clean("audit")

    def test_這台機器那一頁(self):
        self._assert_clean("machine")

    def test_需要注意那一頁(self):
        self._assert_clean("list")

    def test_每一頁都真的畫了東西而不是空的(self):
        """列數對得上有一種假的過法：兩邊都是 0。

        `check_tab_values` 比的是「畫面幾列 == 資料幾筆」，
        資料是空的時候畫面空的也算對 —— 那是對的行為，
        但整組要是每一頁都這樣，這一組等於什麼都沒驗。
        所以這裡單獨釘住：真實資料上，每一頁的 lane 有內容。
        """
        for tab in RC.TABS:
            r = _tab_shot(tab.view)
            lane = RC._id_html(RC.strip_fixture(r.dom), "lane")
            self.assertIsNotNone(lane, tab.view)
            self.assertGreater(len(lane.strip()), 200,
                               f"{tab.zh} 那一頁 lane 幾乎是空的")

    def test_切過去之後別頁不會同時亮著(self):
        """`syncView` 把每一顆的 aria-pressed 重算（`app.js:3039`）。

        只驗「目標那一顆是 true」的話，一個永遠不清除舊狀態的
        實作也會過，而畫面上會有兩顆同時看起來被選中。
        """
        for tab in RC.TABS:
            dom = RC.strip_fixture(_tab_shot(tab.view).dom)
            on = re.findall(r'data-view="([a-z]+)"[^>]*aria-pressed="true"',
                            dom)
            self.assertEqual(on, [tab.view], f"{tab.zh}：亮著的是 {on}")


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


class TabChecksThemselvesCatchThings(unittest.TestCase):
    """分頁那幾條檢查本身抓不抓得到東西。不開瀏覽器。

    跟上面 `ChecksThemselvesCatchThings` 同一個理由：真畫面全綠
    有兩種可能，一種是畫面對，一種是檢查根本不會紅。
    """

    WORK = {t.view: t for t in RC.TABS}["work"]
    SPEC = {t.view: t for t in RC.TABS}["spec"]

    def _fake(self, dom: str, fixture: dict):
        return RC.Render(dom=dom, console=[], fixture=fixture,
                         outdir=Path("/nonexistent"))

    def _work(self, rows=2, total=2, active=0, data_rows=2,
              pressed="true", lane_extra=""):
        cards = "".join('<div class="wk"><div class="wkTop">x</div></div>'
                        for _ in range(rows))
        dom = (f'<button class="vw" data-view="work" aria-pressed="{pressed}">'
               f'</button>'
               f'<div class="lane" id="lane">'
               f'<div class="aHead"><span class="aBig">{total}</span>'
               f'<span class="aSub">件還沒做完 進行中 {active}</span></div>'
               f'{cards}{lane_extra}</div>')
        fx = {"work": {"total": 2, "active": 0,
                       "tasks": [{"id": f"T{i}"} for i in range(data_rows)],
                       "active_rows": []}}
        return self._fake(dom, fx)

    def test_列數對不上會紅(self):
        f = RC.check_tab_values(self._work(rows=1), self.WORK)
        self.assertTrue(f)
        self.assertIn("列數", f[0].symptom)

    def test_列數對得上不會紅(self):
        self.assertEqual(RC.check_tab_values(self._work(), self.WORK), [])

    def test_表頭數字對不上會紅(self):
        f = RC.check_tab_values(self._work(total=9), self.WORK)
        self.assertTrue(f)
        self.assertIn("數字", f[0].symptom)

    def test_進行中那個數字也驗(self):
        """表頭有兩個數字，只驗第一個的話第二個永遠是自由的。"""
        f = RC.check_tab_values(self._work(active=7), self.WORK)
        self.assertTrue(f)
        self.assertIn("進行中", f[0].where)

    def test_進行中有資料的時候多那一張卡不算多畫(self):
        """`renderWork` 在有進行中的時候會多畫一張 `.wk`
        （`app.js:2361`），那一張不是任務是清單。

        沒有這一條的話，真實資料一旦有進行中就紅，
        而那不是畫面壞掉 —— 是這支自己的表沒有算進去。
        """
        r = self._work(rows=3, data_rows=2)
        r.fixture["work"]["active_rows"] = [{"state": "x"}]
        self.assertEqual(RC.check_tab_values(r, self.WORK), [])

    def test_沒切過去會紅(self):
        f = RC.check_tab_switched(self._work(pressed="false"), self.WORK)
        self.assertTrue(f)
        self.assertIn("停在別頁", f[0].symptom)

    def test_切過去了不會紅(self):
        self.assertEqual(RC.check_tab_switched(self._work(), self.WORK), [])

    def test_那一顆按鈕整個不在會紅而不是安靜放行(self):
        r = self._fake('<div class="lane" id="lane">x</div>', {})
        f = RC.check_tab_switched(r, self.WORK)
        self.assertTrue(f)
        self.assertIn("找不到", f[0].symptom)

    def test_主區是空的會紅(self):
        r = self._fake('<button class="vw" data-view="work" '
                       'aria-pressed="true"></button>'
                       '<div class="lane" id="lane"></div>', {})
        f = RC.check_tab_switched(r, self.WORK)
        self.assertTrue(f)
        self.assertIn("空的", f[0].symptom)

    def test_停在佔位字會紅(self):
        """佔位字是「還在讀」，不是「讀完了沒東西」。

        沒有這一條，那一頁 async 還沒跑完就照相的時候，
        報出來的會是一堆「找不到表頭」—— 症狀跟原因差一層。
        """
        r = self._fake('<button class="vw" data-view="work" '
                       'aria-pressed="true"></button>'
                       '<div class="lane" id="lane">'
                       '<div class="fam plain"><div class="none">讀任務帳本'
                       '</div></div></div>', {})
        f = RC.check_tab_switched(r, self.WORK)
        self.assertTrue(f)
        self.assertIn("佔位字", f[0].symptom)

    def test_表頭那一格換了_class_照樣找得到(self):
        """`renderWork` 的表頭在 total 是 0 的時候換成 `.fBig`
        （`app.js:2316`）。只認 `.aBig` 的話，一個真的沒有待辦的
        乾淨狀態會被判成「找不到表頭」。
        """
        dom = ('<button class="vw" data-view="work" aria-pressed="true">'
               '</button><div class="lane" id="lane">'
               '<div class="aHead"><span class="fBig">0</span>'
               '<span class="aSub">件還沒做完 進行中 0</span></div></div>')
        r = self._fake(dom, {"work": {"total": 0, "active": 0,
                                      "tasks": [], "active_rows": []}})
        self.assertEqual(RC.check_tab_values(r, self.WORK), [])

    def test_fixture_少一把鑰匙會紅而不是安靜跳過(self):
        """2026-09-17 展開那一組就是「安靜跳過」害整組假綠的。

        這支自己的表寫錯鍵的時候，要指名是表寫錯了，
        不是報成畫面壞掉，也不是什麼都不報。
        """
        r = self._work()
        del r.fixture["work"]["total"]
        f = RC.check_tab_values(r, self.WORK)
        self.assertTrue(f)
        self.assertIn("這支自己的表", f[0].symptom)

    def test_必讀清單只數第一塊不把底下那兩塊數進去(self):
        """`renderSpec` 在 lane 裡放三塊 `.fam`（清單、區塊閱讀、
        要你裁的問題），三塊裡面都有 `.ct`。

        不縮到第一塊的話，真實資料上數出來是 74 而清單只有 30。
        """
        rows = "".join('<li><span class="ct">讀完</span></li>'
                       for _ in range(30))
        other = "".join('<li><span class="ct">x</span></li>'
                        for _ in range(44))
        dom = ('<button class="vw" data-view="spec" aria-pressed="true">'
               '</button><div class="lane" id="lane">'
               '<div class="aHead"><span class="aBig">20 / 30</span></div>'
               f'<div class="fam">{rows}</div>'
               f'<div class="fam"><div class="famT">區塊閱讀</div>{other}</div>'
               '</div>')
        r = self._fake(dom, {"spec_reading": {
            "full": 20, "total": 30,
            "rows": [{"name": f"d{i}"} for i in range(30)]}})
        self.assertEqual(RC.check_tab_values(r, self.SPEC), [])

    def test_必讀清單那一塊少一列還是會紅(self):
        rows = "".join('<li><span class="ct">讀完</span></li>'
                       for _ in range(29))
        dom = ('<button class="vw" data-view="spec" aria-pressed="true">'
               '</button><div class="lane" id="lane">'
               '<div class="aHead"><span class="aBig">20 / 30</span></div>'
               f'<div class="fam">{rows}</div></div>')
        r = self._fake(dom, {"spec_reading": {
            "full": 20, "total": 30,
            "rows": [{"name": f"d{i}"} for i in range(30)]}})
        f = RC.check_tab_values(r, self.SPEC)
        self.assertTrue(f)
        self.assertIn("列數", f[0].symptom)

    def test_三格嚴重度的數字從原始資料數不是讀現成總數(self):
        """`renderList` 是自己從 `strands.rows` 數出來的
        （`app.js:2044`），betrayals 跟 overclaims 都要算。

        讀某個現成的總數欄位的話，驗到的是「兩個欄位一不一致」，
        不是「畫面上那個數字對不對」。
        """
        fx = {"strands": {"rows": [
            {"betrayals": [{"family": "C"}, {"family": "A"}],
             "overclaims": [{"family": "A"}]},
            {"overclaims": [{"family": "A"}]},
        ]}}
        self.assertEqual(RC._fam_count(fx, "C"), 1)
        self.assertEqual(RC._fam_count(fx, "A"), 3)
        self.assertEqual(RC._fam_count(fx, "B"), 0)

    def test_嚴重度那一格數字對不上會紅(self):
        tab = {t.view: t for t in RC.TABS}["list"]
        dom = ('<button class="vw" data-view="list" aria-pressed="true">'
               '</button><div class="lane" id="lane">'
               '<div class="fam sev sevC"><h3>編造<em>0</em></h3></div>'
               '<div class="fam sev sevB"><h3>沒做卻說做了<em>0</em></h3></div>'
               '<div class="fam sev sevA"><h3>講太滿<em>0</em></h3></div>'
               '</div>')
        fx = {"strands": {"rows": [{"betrayals": [{"family": "C"}]}]}}
        f = RC.check_tab_values(self._fake(dom, fx), tab)
        self.assertTrue(f)
        self.assertIn("編造", f[0].where)

    # ---------------------------------------- 漢堡那一條

    def test_面板還是關的會紅(self):
        r = self._fake('<div class="picker" id="picker" hidden>'
                       '<button class="vw"></button></div>', {})
        f = RC.check_burger_opens_picker(r)
        self.assertTrue(f)
        self.assertIn("按不到", f[0].symptom)

    def test_面板打開了不會紅(self):
        vws = "".join('<button class="vw"></button>'
                      for _ in range(len(RC.TABS) + 1))
        r = self._fake(f'<div class="picker" id="picker">{vws}</div>', {})
        self.assertEqual(RC.check_burger_opens_picker(r), [])

    def test_面板打開了但分頁少一顆會紅(self):
        """開了不等於裡面的東西還在。少一顆的話有一頁按不到，
        而那一頁的檢查在別的地方是綠的（它按的是選擇器不是畫面）。
        """
        vws = "".join('<button class="vw"></button>' for _ in range(len(RC.TABS)))
        r = self._fake(f'<div class="picker" id="picker">{vws}</div>', {})
        f = RC.check_burger_opens_picker(r)
        self.assertTrue(f)
        self.assertIn("數量不對", f[0].symptom)

    # ---------------------------------------- 取值那兩支

    def test_巢狀的_div_不會讓_lane_提早結束(self):
        inner = '<div class="wk"><div class="wkTop"><div>x</div></div></div>'
        dom = f'<div id="lane">{inner}</div><div class="wk">外面那個</div>'
        got = RC._id_html(dom, "lane")
        self.assertEqual(RC._count_class(got, "wk"), 1)

    def test_取文字不會抓到第一個角括號就停(self):
        """這些格子裡本來就有巢狀的 `<b>` 與 `<span>`，
        抓到第一個 `<` 就停會只拿到開頭那幾個字 ——
        而那幾個字常常剛好含要驗的數字，於是斷言看起來會過。
        """
        frag = '<span class="aSub">帳本共 <b>310</b> 筆，繼續 <b>15</b> 次</span>'
        self.assertEqual(RC._nums(RC._cls_text(frag, "aSub")), ["310", "15"])

    def test_取文字找不到回_None_不回空字串(self):
        """回空字串的話，`_nums` 會回空清單，而空清單跟
        「那一格有但是沒有數字」長得一樣 —— 兩種症狀差很遠。
        """
        self.assertIsNone(RC._cls_text('<span class="x">a</span>', "y"))

    def test_class_比對的是完整單字(self):
        frag = '<div class="af"></div><div class="afT"></div>'
        self.assertEqual(RC._count_class(frag, "af"), 1)

    def test_帶別的_class_的那一個照樣算進去(self):
        """`renderAudit` 有幾張 `.af` 帶第二個 class。
        只認 `class="af"` 的話那幾張會被漏掉，而畫面上它們是在的。
        """
        frag = '<div class="af"></div><div class="af hot"></div>'
        self.assertEqual(RC._count_class(frag, "af"), 2)


class ActionButtonsNeedTwoPresses(unittest.TestCase):
    """任務卡上那三顆動作鈕，按第一下只進入待確認，不送出指令。

    這一組是這條線上第一次按到**第二層**。前面幾組按的都是
    一步就到的東西（展開、切分頁），這三顆鈕在分頁裡面，
    要三下才碰得到。

    **為什麼只按第一下。** 第二下會 `invoke("act")`，而那在真的
    App 裡是往帳本寫東西。一條會改正本的測試，跑的人要先猜它
    安不安全 —— 而「猜」正是這整個專案在消滅的東西。
    第一下驗得到的東西已經夠：那道閘還在，而且它撐得過一次輪詢。

    【2026-09-17 這一組抓到一個真的 bug，記在這裡免得修法被當成多餘】
    `setInterval(tick, 2000)` 每兩秒重畫一次 work 那一頁，而
    `renderWork()` 第一行把整塊清掉重建，所以待確認狀態撐不過
    一次輪詢。實測：兩下間隔 300 毫秒送得出 `act`，間隔 2500 毫秒
    **一個 act 都送不出去**，而畫面上沒有任何錯誤訊息。
    也就是那三顆鈕在真的 App 裡按不動，症狀是「按了沒反應」。
    修法是 `workBusy()`：使用者按到一半的時候，這一輪不重畫。
    """

    def test_按第一下那顆鈕進入待確認(self):
        fs = RC.check_act_arms_not_fires(_act_shot())
        self.assertEqual(fs, [], "\n" + "\n".join(str(f) for f in fs))

    def test_按第一下一個指令都沒送出去(self):
        fs = RC.check_act_did_not_invoke(_act_shot())
        self.assertEqual(fs, [], "\n" + "\n".join(str(f) for f in fs))

    def test_那一下沒有把畫面弄炸(self):
        r = _act_shot()
        fs = RC.check_no_fatal_banner(r) + RC.check_no_console_errors(r)
        self.assertEqual(fs, [], "\n" + "\n".join(str(f) for f in fs))

    def test_觀察器真的裝上了(self):
        """`check_act_did_not_invoke` 靠的是這份清單不是空的。

        分開寫一條，是因為上面那一條全綠有兩種可能：真的沒送 act，
        或者觀察器根本沒裝上。這一條問的是後面那種。
        """
        cmds = json.loads(RC._tag_text(_act_shot().dom, RC.SPY_ID))
        self.assertTrue(cmds, "觀察器一個指令都沒收到")
        self.assertIn("work", cmds, f"沒有看到切到那一頁時該發的指令：{cmds}")

    def test_照相的時刻有跨過一次輪詢(self):
        """這是一個對**常數**的斷言，因為那個常數自己就是斷言的一部分。

        照相若落在第一次輪詢之前，「輪詢把待確認沖掉」那個 bug
        會照出一張乾淨的畫面 —— 往看起來沒事的方向壞。
        另一邊也要守：超過確認窗的話，待確認被自己的計時器還原，
        那是正常行為卻會被判成 bug。
        """
        press = RC.CLICK_AFTER_MS + (len(RC.ACT_CLICKS) - 1) * RC.CLICK_GAP_MS
        self.assertGreater(RC.ACT_BUDGET_MS, press + POLL_MS,
                           "照相太早，跨不過輪詢")
        self.assertLess(RC.ACT_BUDGET_MS, press + ARM_WINDOW_MS,
                        "照相太晚，待確認已經被自己的計時器還原")

    def test_那三顆鈕都在(self):
        """少一顆的話上面幾條照樣綠：它們只看第一顆。"""
        box = RC._acts_box(_act_shot())
        self.assertIsNotNone(box, "找不到動作鈕那一排")
        for kind in ("finish", "dispatch", "drain"):
            self.assertIn('data-kind="%s"' % kind, box)


class PollingMustNotWipeTheConfirm(unittest.TestCase):
    """輪詢重畫不准把使用者按到一半的狀態沖掉。

    這一組守的是上面那個 bug 的修法本身。修法只有一行
    （`app.js` 輪詢那一條路上的 `workBusy()` 守門），一行的東西
    最容易在下一次重構時被當成多餘拿掉。

    **兩條路要分開守。** 輪詢那一條要有守門，`syncView()`
    那一條不准有 —— 換分頁是使用者自己的動作，那時候本來就該
    整頁重畫。守錯邊的話，切走再切回來會看到上一頁的殘影。
    """

    def setUp(self):
        self.js = APP_JS.read_text(encoding="utf-8")

    def test_輪詢那一條路有守門(self):
        self.assertIn('else if (view === "work") { if (!workBusy()) renderWork(); }',
                      self.js,
                      "輪詢會無條件重畫 work，待確認撐不過兩秒")

    def test_換分頁那一條路沒有守門(self):
        self.assertIn('else if (view === "work") { workCache = null; renderWork(); }',
                      self.js,
                      "syncView 不該有守門，換分頁本來就該整頁重畫")

    def test_守門看的是待確認與送出中兩種(self):
        """只守 `armed` 的話，送出中那一段（`b.disabled = true`）
        仍然會被輪詢重畫沖掉 —— 而那一段正在等後端回話。
        """
        m = re.search(r"function workBusy\(\) \{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(m, "找不到 workBusy")
        body = m.group(1)
        self.assertIn(".ac.armed", body)
        self.assertIn(".ac:disabled", body)

    def test_確認窗比輪詢間隔長所以守門不可或缺(self):
        """這兩個數字的關係就是那個 bug 的成因。

        確認窗要是比輪詢間隔短，使用者根本碰不到這個問題，
        守門也就不需要。哪天有人把輪詢調慢或把窗調短，
        這一條會提醒他回來看這個修法還需不需要。
        """
        self.assertGreater(ARM_WINDOW_MS, POLL_MS,
                           "確認窗短於輪詢間隔的話，這個修法的前提沒了")

    def test_這兩個數字真的是從原始碼抽出來的(self):
        """抽不到的時候 `_one_int` 回 None，而 None 拿去比大小
        在 Python 3 會炸 —— 那是紅的，不是綠的。這一條把它變成
        一句看得懂的話，順便釘住抽取用的那兩個樣式還對得上。

        寫在這裡而不是靠上面那條的例外，是因為
        「這個修法的前提沒了」跟「這組測試量錯了東西」
        是兩種症狀，訊息不該混在一起。
        """
        self.assertIsNotNone(
            POLL_MS, "抽不到輪詢間隔，或者 app.js 裡有不只一處長這樣")
        self.assertIsNotNone(
            ARM_WINDOW_MS, "抽不到確認窗，或者 app.js 裡有不只一處長這樣")


# 輪詢那一次：切到「在做什麼」之後**坐著不動**，看接下來那幾輪做了什麼。
#
# 跟動作鈕那一次的差別只有一個：那一次問「按下去之後怎樣」，
# 這一次問「不按之後怎樣」。所以這一次要坐得久，久到跨過好幾輪，
# 而傾印的時刻要離最後一下夠遠（`POLL_SPY_AT_MS`）。
#
# **不能跟動作鈕那一次共用。** 那一次在 7000 毫秒照相，中間只跨過
# 一輪，樣本只有一輪的話「重抓了幾次」永遠答對 —— 往綠的方向壞。
_POLL = {"r": None, "err": None}


def _poll_shot():
    if _POLL["r"] is None and _POLL["err"] is None:
        try:
            _POLL["r"] = RC.render(clicks=RC.POLL_CLICKS, spy=True,
                                   budget_ms=RC.POLL_BUDGET_MS,
                                   spy_at_ms=RC.POLL_SPY_AT_MS)
        except RC.CannotRun as e:
            _POLL["err"] = str(e)
    if _POLL["err"]:
        raise unittest.SkipTest(f"驗不了，不是通過：{_POLL['err']}")
    return _POLL["r"]


class WhoPaintedThatCell(unittest.TestCase):
    """那一格是切分頁那一下畫的，還是之後某一輪輪詢畫的。

    **這一組補的是這條線一直寫在收尾那句話裡的盲點**：
    「分不出那一格是誰畫的」。5o、5p、5q 三輪都列著它。

    為什麼 DOM 分不出來：兩條路呼叫的是同一個 `renderWork()`，
    畫出來的 HTML 一模一樣。一張靜止的快照上，「有內容」只證明
    有人畫過，證明不了是誰。

    指令清單分得出來。`syncView()` 那一條會先把快取清掉所以會重抓，
    輪詢那一條不會 —— 兩條路在 Tauri 那一層的痕跡不同。

    **這一組跟 `tests/test_ui_contract.py` 那幾條不是同一件事。**
    那邊守的是原始碼裡那幾行還在（`setInterval(tick, 2000)`、
    七頁的分派、五個快取的清除）。這邊守的是那幾行在瀏覽器裡
    真的有效果。中間隔著 `loadFoundation()` 的 promise、`tick`
    自己的 try/catch、每一輪都要回來的 `invoke`，任何一個壞掉，
    原始碼那一邊仍然全綠。
    """

    def test_輪詢在瀏覽器裡真的重跑(self):
        fs = RC.check_poll_loop_really_repeats(_poll_shot())
        self.assertEqual(fs, [], "\n" + "\n".join(str(f) for f in fs))

    def test_那幾輪是從快取重畫沒有回頭抓帳本(self):
        fs = RC.check_poll_repaints_from_cache(_poll_shot())
        self.assertEqual(fs, [], "\n" + "\n".join(str(f) for f in fs))

    def test_那一下沒有把畫面弄炸(self):
        r = _poll_shot()
        fs = RC.check_no_fatal_banner(r) + RC.check_no_console_errors(r)
        self.assertEqual(fs, [], "\n" + "\n".join(str(f) for f in fs))

    def test_觀察器真的裝上了(self):
        """上面兩條全綠有兩種可能，這一條問的是另一種。

        跟動作鈕那一組同一個理由：觀察器沒裝上的時候，
        「發了幾次」每一條都會拿到空清單，而空清單什麼都對。
        """
        cmds = json.loads(RC._tag_text(_poll_shot().dom, RC.SPY_ID))
        self.assertTrue(cmds, "觀察器一個指令都沒收到")
        self.assertIn("work", cmds,
                      f"沒有看到切到那一頁時該發的指令：{cmds}")

    def test_傾印的時刻真的跨過好幾輪(self):
        """這是一個對**常數**的斷言，跟 `ACT_BUDGET_MS` 那條同源。

        倒得太早的話，輪詢還沒跑幾次，「重抓了幾次」這個問題
        因為樣本只有一輪而永遠答對。這一條把「至少跨過三輪」
        變成一個會紅的關係，而輪詢間隔是從 `app.js` 抽的，
        不是抄在這裡 —— 有人把輪詢調慢，這一條會紅。
        """
        self.assertIsNotNone(POLL_MS, "抽不到輪詢間隔")
        last = RC.CLICK_AFTER_MS + (len(RC.POLL_CLICKS) - 1) * RC.CLICK_GAP_MS
        self.assertGreaterEqual(
            RC.POLL_SPY_AT_MS - last, 3 * POLL_MS,
            "傾印太早，跨不過三輪，樣本不足以回答「重抓了幾次」")
        self.assertGreater(RC.POLL_BUDGET_MS, RC.POLL_SPY_AT_MS,
                           "照相早於傾印的話，DOM 裡不會有那一格")

    def test_最少幾次那個門檻不是隨便寫的(self):
        """門檻要落在「不可能自動達成」跟「不可能達成」中間。

        低於 2 的話，載入時那一次就滿足了，這條檢查等於沒跑。
        高於那個窗裝得下的輪數的話，它永遠紅，而紅的原因
        跟輪詢有沒有在跑無關。
        """
        self.assertGreaterEqual(RC.POLL_MIN_STRANDS, 2,
                                "載入時那一次就滿足了，等於沒跑")
        self.assertLessEqual(RC.POLL_MIN_STRANDS,
                             RC.POLL_SPY_AT_MS // POLL_MS,
                             "這個窗裝不下這麼多輪，這條會永遠紅")

    def test_按的是那一頁(self):
        """`POLL_CLICKS` 要真的走到「在做什麼」。

        寫死成別的選擇器的話，上面那條「重抓了幾次」會拿到 0，
        而 0 的訊息講的是別的事。
        """
        self.assertEqual(RC.POLL_CLICKS, RC.tab_clicks("work"))

    def test_這一組有被主流程跑到(self):
        """檢查函式寫好卻沒有人叫，是這個專案犯過的一類錯。

        看的是 `main()` 的原始碼，因為「跑過了」在這裡沒有別的痕跡。
        """
        src = (REPO / "tools" / "ui-render-check.py").read_text(
            encoding="utf-8")
        body = src[src.index("def main("):]
        self.assertIn("POLL_CHECKS", body, "main() 沒有跑輪詢那一組")
        self.assertIn("spy_at_ms=POLL_SPY_AT_MS", body,
                      "main() 沒有把傾印時刻傳進去，會用預設的那個早得多的值")


class PollChecksThemselvesCatchThings(unittest.TestCase):
    """上面那兩條檢查自己抓不抓得到東西。

    上面那一組全綠，可能是畫面對，也可能是檢查永遠回空清單。
    這一組餵合成的資料進去，逼它們紅。
    """

    def _r(self, cmds):
        """`cmds` 給 None 代表 DOM 裡根本沒有觀察器那一格。"""
        dom = "<html><body>"
        if cmds is not None:
            dom += '<div id="%s" hidden>%s</div>' % (
                RC.SPY_ID, json.dumps(cmds))
        dom += "</body></html>"
        return RC.Render(dom=dom, console=[], fixture={},
                         outdir=Path("/nonexistent"))

    def test_觀察器沒裝上要報驗不了不是通過(self):
        for bad in (None, []):
            with self.subTest(bad=bad):
                fs = RC.check_poll_loop_really_repeats(self._r(bad))
                self.assertTrue(fs, f"{bad!r} 被放行了")
                self.assertIn("驗不了", str(fs[0]))

    def test_輪詢沒重跑會紅(self):
        fs = RC.check_poll_loop_really_repeats(
            self._r(["spec_reading", "strands", "sessions", "work"]))
        self.assertTrue(fs, "只發了一次 strands 卻放行")
        self.assertIn("不再更新", str(fs[0]))

    def test_輪詢有重跑就過(self):
        self.assertEqual(
            RC.check_poll_loop_really_repeats(
                self._r(["strands"] * RC.POLL_MIN_STRANDS + ["work"])), [])

    def test_一次都沒抓帳本會紅而且講的是那一頁空著(self):
        fs = RC.check_poll_repaints_from_cache(self._r(["strands"] * 5))
        self.assertTrue(fs, "一次都沒抓卻放行")
        self.assertIn("讀任務帳本", str(fs[0]))

    def test_每輪都重抓會紅而且指得回那個常數(self):
        fs = RC.check_poll_repaints_from_cache(
            self._r(["strands", "work", "strands", "work", "strands", "work"]))
        self.assertTrue(fs, "抓了三次卻放行")
        self.assertIn("POLL_EXPECTED_WORK_FETCHES", str(fs[0]))

    def test_剛好那個次數才過(self):
        cmds = (["strands", "work"] +
                ["strands"] * RC.POLL_MIN_STRANDS)
        self.assertEqual(RC.check_poll_repaints_from_cache(self._r(cmds)), [])


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


class PollPagesTableItself(unittest.TestCase):
    """那張表本身站不站得住。"""

    def test_每一頁在TABS裡都找得到(self):
        for pg in RC.POLL_PAGES:
            with self.subTest(view=pg.view):
                self.assertIsNotNone(
                    RC._tab_of(pg.view),
                    f"POLL_PAGES 列了 {pg.view}，但 TABS 裡沒有這一頁")

    def test_expect的鍵全部在PAGE_CMDS裡(self):
        """表裡拼錯一個鍵，那一條期望不會有人去讀 —— 安靜跳過。

        這正是 2026-09-17 `EXPANDED_BOXES` 第四欄踩過的那一種
        （鍵寫成 `rows`，真正的鍵是 `top`），後果不是紅燈，
        是那一格被跳過。所以這裡守的是表，不是行為。
        """
        for pg in RC.POLL_PAGES:
            with self.subTest(view=pg.view):
                stray = sorted(set(pg.expect) - set(RC.PAGE_CMDS))
                self.assertEqual(stray, [], f"{pg.view} 的 expect 多出 {stray}")

    def test_work不在這張表裡免得同一件事守兩處(self):
        """`work` 由 `check_poll_repaints_from_cache` 守著。

        兩處守同一件事的話，改了一處另一處還綠，那比沒守更糟。
        """
        self.assertNotIn("work", [p.view for p in RC.POLL_PAGES])

    def test_六個分頁全部有人守誰畫的(self):
        """`TABS` 每一頁都要有人守，不能漏掉一頁還以為全守了。"""
        covered = {p.view for p in RC.POLL_PAGES} | {"work"}
        missing = sorted({t.view for t in RC.TABS} - covered)
        self.assertEqual(missing, [], f"這幾頁沒有人守誰畫的：{missing}")

    def test_每一頁至少斷言一個自己的指令(self):
        """`expect` 全空的話那一頁只剩「其餘都是 0」，形同沒驗。

        `list` 是例外而且是有意的：它一個專屬指令都不發，
        那正是它要守的事實，所以它 expect 裡放的是載入時
        那一次 `spec_reading`。
        """
        for pg in RC.POLL_PAGES:
            with self.subTest(view=pg.view):
                self.assertTrue(pg.expect, f"{pg.view} 的 expect 是空的")

    def test_每一頁都有寫下它為什麼是這個數字(self):
        for pg in RC.POLL_PAGES:
            with self.subTest(view=pg.view):
                self.assertTrue(pg.note.strip(), f"{pg.view} 沒有 note")

    def test_這一組有被主流程跑到(self):
        """表寫好了但 `main()` 沒跑，整組等於不存在。"""
        body = TOOL.read_text(encoding="utf-8")
        self.assertIn("for pg in POLL_PAGES:", body,
                      "main() 沒有走 POLL_PAGES 那一圈")
        self.assertIn("check_poll_page_fetches(rq, pg)", body,
                      "那一圈裡沒有真的呼叫這一支檢查")
        self.assertIn("check_tab_switched(rq, tb)", body,
                      "那一圈沒有先確認真的切過去了 —— 沒切過去的話"
                      "每一條「那個指令 0 次」都會答對")

    def test_每輪重抓那個門檻不是隨便寫的(self):
        """`POLL_MIN_LIVE` 要小於實際跨過的輪數，不然穩定紅。"""
        self.assertGreaterEqual(RC.POLL_MIN_LIVE, 2,
                                "門檻是 1 的話，只發一次也算每輪重抓")
        POLL_MS = _one_int(r"setInterval\(\s*tick\s*,\s*(\d+)\s*\)",
                           "輪詢間隔")
        self.assertIsNotNone(POLL_MS, "抽不到輪詢間隔")
        self.assertLessEqual(RC.POLL_MIN_LIVE, RC.POLL_SPY_AT_MS // POLL_MS,
                             "門檻比坐過的輪數還多，那是穩定紅不是斷言")


class PollPageCheckCatchesThings(unittest.TestCase):
    """那支檢查自己抓不抓得到東西。合成指令清單，逼它紅。"""

    def _r(self, cmds):
        dom = ('<html><body><div id="%s" hidden>%s</div></body></html>'
               % (RC.SPY_ID, json.dumps(cmds)))
        return RC.Render(dom=dom, console=[], fixture={},
                         outdir=Path("/nonexistent"))

    def _page(self, view):
        return [p for p in RC.POLL_PAGES if p.view == view][0]

    def _ok_feat(self):
        return ["spec_reading", "strands", "strands", "sessions",
                "features"] + ["strands"] * RC.POLL_MIN_STRANDS

    def test_量到的那個形狀會過(self):
        self.assertEqual(
            RC.check_poll_page_fetches(self._r(self._ok_feat()),
                                       self._page("feat")), [])

    def test_多抓一次會紅而且指得回那張表(self):
        fs = RC.check_poll_page_fetches(
            self._r(self._ok_feat() + ["features"]), self._page("feat"))
        self.assertTrue(fs, "抓了兩次卻放行")
        self.assertIn("POLL_PAGES", str(fs[0]))

    def test_一次都沒抓會紅(self):
        cmds = [c for c in self._ok_feat() if c != "features"]
        fs = RC.check_poll_page_fetches(self._r(cmds), self._page("feat"))
        self.assertTrue(fs, "一次都沒抓卻放行")

    def test_順手發了別頁的指令會紅(self):
        """沒列進 `expect` 的一律期望 0 次，缺席本身是斷言。"""
        fs = RC.check_poll_page_fetches(
            self._r(self._ok_feat() + ["machine"]), self._page("feat"))
        self.assertTrue(fs, "功能那一頁去抓 machine 卻放行")
        self.assertIn("machine", str(fs[0]))

    def test_讀文件那一頁的下半不再每輪重抓會紅(self):
        """`block_reading` 與 `sufficiency` 沒有快取守門，每輪重發。

        這一條守的是 2026-09-17 量到、而前一輪紀錄說相反的那件事：
        五頁**不是**同一個形狀，讀文件那一頁上半快取、下半即時。
        """
        cmds = ["spec_reading", "strands", "strands", "sessions",
                "spec_reading", "block_reading", "sufficiency"]
        cmds += ["strands"] * RC.POLL_MIN_STRANDS
        fs = RC.check_poll_page_fetches(self._r(cmds), self._page("spec"))
        self.assertTrue(fs, "下半只發一次卻放行")
        names = str(fs)
        self.assertIn("block_reading", names)
        self.assertIn("sufficiency", names)

    def test_讀文件那一頁正常的形狀會過(self):
        cmds = ["spec_reading", "strands", "strands", "sessions",
                "spec_reading"]
        for _ in range(RC.POLL_MIN_LIVE):
            cmds += ["block_reading", "sufficiency", "strands"]
        cmds += ["strands"] * RC.POLL_MIN_STRANDS
        self.assertEqual(
            RC.check_poll_page_fetches(self._r(cmds), self._page("spec")), [])

    def test_需要注意那一頁多發任何專屬指令都會紅(self):
        """它是六頁裡唯一一個專屬指令 0 次的，所以任何一個都算多。"""
        base = ["spec_reading"] + ["strands"] * RC.POLL_MIN_STRANDS
        for cmd in ("work", "features", "audit", "machine", "block_reading"):
            with self.subTest(cmd=cmd):
                fs = RC.check_poll_page_fetches(self._r(base + [cmd]),
                                                self._page("list"))
                self.assertTrue(fs, f"list 那一頁發了 {cmd} 卻放行")

    def test_觀察器沒裝上要報驗不了不是通過(self):
        for bad in (None, []):
            with self.subTest(bad=bad):
                dom = "<html><body>"
                if bad is not None:
                    dom += '<div id="%s" hidden>%s</div>' % (
                        RC.SPY_ID, json.dumps(bad))
                dom += "</body></html>"
                r = RC.Render(dom=dom, console=[], fixture={},
                              outdir=Path("/nonexistent"))
                fs = RC.check_poll_page_fetches(r, self._page("feat"))
                self.assertTrue(fs, f"{bad!r} 被放行了")
                self.assertIn("驗不了", str(fs[0]))

    def test_表裡拼錯一個鍵會被抓到不是安靜跳過(self):
        bad = RC.PollPage("feat", "功能", {"featurez": 1}, "測試用")
        fs = RC.check_poll_page_fetches(self._r(self._ok_feat()), bad)
        self.assertTrue(fs, "拼錯的鍵被安靜跳過了")
        self.assertIn("featurez", str(fs))

    def test_一條都沒比對過要報成驗不了(self):
        """整支空轉的話，回空跟通過在呼叫端分不出來。

        2026-09-17 反向驗證實測：把迴圈改成不跑，五頁全綠。
        """
        real = RC.PAGE_CMDS
        try:
            RC.PAGE_CMDS = ()
            fs = RC.check_poll_page_fetches(self._r(self._ok_feat()),
                                            self._page("feat"))
        finally:
            RC.PAGE_CMDS = real
        self.assertTrue(fs, "一條都沒比對卻放行")
        # `PAGE_CMDS` 清空之後 stray 那一條必然也會報（`expect` 裡
        # 每一個鍵都變成「不在清單裡」），所以看的是整份不是第一條。
        self.assertIn("空轉", str(fs))


# ----------------------------------------- 第二次切進同一頁那一組

# 這一層跟上面那一層同一個分工：這裡守表與檢查函式，開瀏覽器那五次
# 在 `tools/ui-render-check.py` 的主流程裡（一頁一次，約 40 秒）。


class RevisitPagesTableItself(unittest.TestCase):
    """那張表本身站不站得住。"""

    def test_每一頁在TABS裡都找得到(self):
        for pg in RC.REVISIT_PAGES:
            with self.subTest(view=pg.view):
                self.assertIsNotNone(
                    RC._tab_of(pg.view),
                    f"REVISIT_PAGES 列了 {pg.view}，但 TABS 裡沒有這一頁")

    def test_expect的鍵全部在PAGE_CMDS裡(self):
        for pg in RC.REVISIT_PAGES:
            with self.subTest(view=pg.view):
                stray = sorted(set(pg.expect) - set(RC.PAGE_CMDS))
                self.assertEqual(stray, [], f"{pg.view} 的 expect 多出 {stray}")

    def test_每一個有清快取的分頁都在這張表裡(self):
        """`syncView()` 裡每一行 `xxxCache = null` 都要有人守。

        漏掉一頁的話，那一頁的清快取哪天被拿掉不會有人紅，
        而使用者看到的是切回來還是舊資料、沒有任何提示。

        **這一條是從 `app.js` 抽出來比對的，不是照著表寫的。**
        照著表寫的話，表漏了一頁這一條也會跟著漏。
        """
        body = (REPO / "desktop" / "ui" / "app.js").read_text(
            encoding="utf-8")
        sync = body.split("function syncView()", 1)[1].split("\n}", 1)[0]
        cleared = set(re.findall(r'view === "(\w+)"\)\s*\{\s*\w+Cache = null',
                                 sync))
        self.assertTrue(cleared, "從 syncView() 抽不到任何清快取的分頁")
        missing = sorted(cleared - {p.view for p in RC.REVISIT_PAGES})
        self.assertEqual(missing, [],
                         f"這幾頁會清快取但沒有人守切回來那一下：{missing}")

    def test_繞路那一頁自己不發專屬指令(self):
        """繞路那一頁發指令的話，它的次數會混進這一組的計數。

        `list` 一個專屬指令都不發，那是 `POLL_PAGES` 量出來的事實，
        所以這一條盯著它 —— 哪天 `list` 長出自己的指令，
        這一組的每一個數字都要重量。
        """
        lst = [p for p in RC.POLL_PAGES if p.view == RC.REVISIT_B_VIEW]
        self.assertTrue(lst, f"{RC.REVISIT_B_VIEW} 不在 POLL_PAGES 裡，"
                             "它發不發指令沒有人量過")
        own = {c for c in lst[0].expect if c != "spec_reading"}
        self.assertEqual(own, set(),
                         f"繞路那一頁現在會發 {own}，這一組的數字要重量")

    def test_按六下而且最後一下回到A頁(self):
        cl = RC.revisit_clicks("feat")
        self.assertEqual(len(cl), 6, "不是六下的話它驗不到第二次切入")
        self.assertEqual(cl[-1], cl[1], "最後一下沒有回到 A 頁")
        self.assertIn(RC.REVISIT_B_VIEW, cl[3], "中間沒有繞去別頁")

    def test_傾印的時刻晚於最後一下(self):
        """倒得比最後一下早的話，第二次切入那一下根本還沒發生。"""
        last = RC.CLICK_AFTER_MS + (len(RC.revisit_clicks("feat")) - 1) \
            * RC.CLICK_GAP_MS
        self.assertGreater(RC.REVISIT_SPY_AT_MS, last,
                           "傾印早於最後一下，那一下的指令不會被數到")
        self.assertGreater(RC.REVISIT_BUDGET_MS, RC.REVISIT_SPY_AT_MS,
                           "照相早於傾印，#rcSpy 不會出現在 DOM 裡")

    def test_每一頁都有寫下它為什麼是這個數字(self):
        for pg in RC.REVISIT_PAGES:
            with self.subTest(view=pg.view):
                self.assertTrue(pg.note.strip(), f"{pg.view} 沒有 note")

    def test_這一組有被主流程跑到(self):
        body = TOOL.read_text(encoding="utf-8")
        self.assertIn("for pg in REVISIT_PAGES:", body,
                      "main() 沒有走 REVISIT_PAGES 那一圈")
        self.assertIn("check_revisit_refetches(rv, pg)", body,
                      "那一圈裡沒有真的呼叫這一支檢查")
        self.assertIn("check_tab_switched(rv, tb)", body,
                      "那一圈沒有先確認最後真的停在 A 頁")

    def test_這一組的門檻跟坐著不動那一組分開(self):
        """時窗不同，門檻不能共用。

        `POLL_MIN_LIVE` 是照 10500 毫秒訂的；這一組的時窗只有
        最後一下之後那一段，套過來會因為時窗而紅。
        """
        self.assertGreaterEqual(RC.REVISIT_MIN_LIVE, 2,
                                "門檻是 1 的話，只發一次也算兩次切入各一次")
        last = RC.CLICK_AFTER_MS + (len(RC.revisit_clicks("feat")) - 1) \
            * RC.CLICK_GAP_MS
        POLL_MS = _one_int(r"setInterval\(\s*tick\s*,\s*(\d+)\s*\)",
                           "輪詢間隔")
        self.assertIsNotNone(POLL_MS, "抽不到輪詢間隔")
        self.assertLessEqual(
            RC.REVISIT_MIN_LIVE,
            2 + (RC.REVISIT_SPY_AT_MS - last) // POLL_MS,
            "門檻比這個時窗裡可能發生的次數還多，那是穩定紅不是斷言")


class RevisitCheckCatchesThings(unittest.TestCase):
    """那支檢查自己抓不抓得到東西。合成指令清單，逼它紅。"""

    def _r(self, cmds):
        dom = ('<html><body><div id="%s" hidden>%s</div></body></html>'
               % (RC.SPY_ID, json.dumps(cmds)))
        return RC.Render(dom=dom, console=[], fixture={},
                         outdir=Path("/nonexistent"))

    def _page(self, view):
        return [p for p in RC.REVISIT_PAGES if p.view == view][0]

    def _ok_feat(self):
        # 2026-09-17 實測的序列。
        return ["spec_reading", "strands", "strands", "sessions",
                "features", "sessions", "strands", "sessions",
                "features", "strands"]

    def test_量到的那個形狀會過(self):
        self.assertEqual(
            RC.check_revisit_refetches(self._r(self._ok_feat()),
                                       self._page("feat")), [])

    def test_切回來沒重抓會紅而且說得出使用者看到什麼(self):
        """這正是 2026-09-17 反向驗證拿掉 `featCache = null` 的形狀。"""
        # 只剩第一次切入那一次。
        cmds = [c for c in self._ok_feat() if c != "features"]
        cmds.insert(4, "features")
        fs = RC.check_revisit_refetches(self._r(cmds), self._page("feat"))
        self.assertTrue(fs, "切回來沒重抓卻放行")
        self.assertIn("上一次的資料", str(fs[0]))

    def test_每一頁少掉第二次都會紅(self):
        """不是只有功能那一頁守得住。"""
        for pg in RC.REVISIT_PAGES:
            own = [c for c, n in pg.expect.items()
                   if n != RC.LIVE and c != "spec_reading"] or ["spec_reading"]
            cmd = own[0]
            cmds = []
            for c, n in pg.expect.items():
                cmds += [c] * (RC.REVISIT_MIN_LIVE if n == RC.LIVE else n)
            with self.subTest(view=pg.view):
                self.assertEqual(
                    RC.check_revisit_refetches(self._r(cmds), pg), [],
                    f"{pg.view} 照表組出來的形狀自己就紅了")
                cmds.remove(cmd)
                fs = RC.check_revisit_refetches(self._r(cmds), pg)
                self.assertTrue(fs, f"{pg.view} 少發一次 {cmd} 卻放行")

    def test_順手發了別頁的指令會紅(self):
        fs = RC.check_revisit_refetches(
            self._r(self._ok_feat() + ["machine"]), self._page("feat"))
        self.assertTrue(fs, "功能那一頁去抓 machine 卻放行")
        self.assertIn("machine", str(fs[0]))

    def test_觀察器沒裝上要報驗不了不是通過(self):
        for bad in (None, []):
            with self.subTest(bad=bad):
                dom = "<html><body>"
                if bad is not None:
                    dom += '<div id="%s" hidden>%s</div>' % (
                        RC.SPY_ID, json.dumps(bad))
                dom += "</body></html>"
                r = RC.Render(dom=dom, console=[], fixture={},
                              outdir=Path("/nonexistent"))
                fs = RC.check_revisit_refetches(r, self._page("feat"))
                self.assertTrue(fs, f"{bad!r} 被放行了")
                self.assertIn("驗不了", str(fs[0]))

    def test_表裡拼錯一個鍵會被抓到不是安靜跳過(self):
        bad = RC.RevisitPage("feat", "功能", {"featurez": 2}, "測試用")
        fs = RC.check_revisit_refetches(self._r(self._ok_feat()), bad)
        self.assertTrue(fs, "拼錯的鍵被安靜跳過了")
        self.assertIn("featurez", str(fs))

    def test_一條都沒比對過要報成驗不了(self):
        real = RC.PAGE_CMDS
        try:
            RC.PAGE_CMDS = ()
            fs = RC.check_revisit_refetches(self._r(self._ok_feat()),
                                            self._page("feat"))
        finally:
            RC.PAGE_CMDS = real
        self.assertTrue(fs, "一條都沒比對卻放行")
        self.assertIn("空轉", str(fs))


# ------------------------------------- 連按同一頁那一組（中間沒切走）

# 這一層守表與檢查函式，開瀏覽器那五次在主流程裡。
#
# **這一組存在的理由不是多守一個功能，是守一句話的有效期限。**
# 上面那一組寫著「驗不到切走過」，理由是 `syncView()` 不比對 `view`。
# 那個理由哪天不成立，上面那一組的射程就變了 —— 在這一組出現之前，
# 沒有任何東西會在那一天紅。


class SamePagesTableItself(unittest.TestCase):
    """那張表本身站不站得住。"""

    def test_每一頁在TABS裡都找得到(self):
        for pg in RC.SAME_PAGES:
            with self.subTest(view=pg.view):
                self.assertIsNotNone(
                    RC._tab_of(pg.view),
                    f"SAME_PAGES 列了 {pg.view}，但 TABS 裡沒有這一頁")

    def test_expect的鍵全部在PAGE_CMDS裡(self):
        for pg in RC.SAME_PAGES:
            with self.subTest(view=pg.view):
                stray = sorted(set(pg.expect) - set(RC.PAGE_CMDS))
                self.assertEqual(stray, [], f"{pg.view} 的 expect 多出 {stray}")

    def test_這張表跟切走再切回來那張表只差自己那一個指令(self):
        """兩張表比不了的話，這一組就沒有價值。

        這一組唯一的用途是**跟那一組比**：同樣六下、同樣的時刻，
        差的只有中間那一下按哪一頁。所以兩張表的期望值之間只准
        有一個鍵不一樣，而且剛好差 1（那一下多切入一次）。

        哪天有人只改一張表，這一條會紅 —— 兩張表各走各的之後，
        「切走過」那一維就再也算不出來了，而且不會有任何跡象。
        """
        rev = {p.view: p for p in RC.REVISIT_PAGES}
        same = {p.view: p for p in RC.SAME_PAGES}
        self.assertEqual(set(rev), set(same),
                         "兩張表守的頁面不一樣，逐頁比對無效")
        for view in sorted(rev):
            with self.subTest(view=view):
                a, b = rev[view].expect, same[view].expect
                self.assertEqual(set(a), set(b),
                                 f"{view} 兩張表的指令名單不同")
                diff = sorted(k for k in a if a[k] != b[k])
                self.assertEqual(
                    len(diff), 1,
                    f"{view} 兩張表差了 {diff or '零'} 個鍵，"
                    "只准差自己那一個指令")
                k = diff[0]
                self.assertNotEqual(a[k], RC.LIVE,
                                    f"{view} 差的那一個是每輪重抓的，"
                                    "那個差別證明不了切入次數")
                self.assertEqual(
                    b[k], a[k] + 1,
                    f"{view} 的 {k}：切走再切回來 {a[k]}、連按同一頁 "
                    f"{b[k]}，差的不是剛好一次切入")

    def test_按六下而且中間沒有切走別頁(self):
        cl = RC.samepage_clicks("feat")
        self.assertEqual(len(cl), 6, "不是六下的話它跟那一組比不了")
        self.assertEqual(len(set(cl)), 2, "中間切走了別頁，那就是那一組")
        self.assertNotIn(RC.REVISIT_B_VIEW, "".join(cl),
                         "序列裡出現了繞路那一頁")

    def test_跟切走再切回來那一組按一樣多下也用同一個傾印時刻(self):
        """控制變因只能留一個，不然兩組的數字比出來沒有意義。"""
        self.assertEqual(len(RC.samepage_clicks("feat")),
                         len(RC.revisit_clicks("feat")),
                         "兩組下數不同，多出來的時間會讓計數不可比")
        body = TOOL.read_text(encoding="utf-8")
        self.assertIn("clicks=samepage_clicks(pg.view),\n"
                      "                        spy=True, "
                      "budget_ms=REVISIT_BUDGET_MS,\n"
                      "                        spy_at_ms=REVISIT_SPY_AT_MS",
                      body, "這一組沒有跟那一組用同一個傾印與照相時刻")

    def test_每一頁都有寫下它為什麼是這個數字(self):
        for pg in RC.SAME_PAGES:
            with self.subTest(view=pg.view):
                self.assertTrue(pg.note.strip(), f"{pg.view} 沒有 note")

    def test_這一組有被主流程跑到(self):
        body = TOOL.read_text(encoding="utf-8")
        self.assertIn("for pg in SAME_PAGES:", body,
                      "main() 沒有走 SAME_PAGES 那一圈")
        self.assertIn("check_samepage_refetches(rs, pg)", body,
                      "那一圈裡沒有真的呼叫這一支檢查")
        self.assertIn("check_tab_switched(rs, tb)", body,
                      "那一圈沒有先確認最後真的停在那一頁")

    def test_syncView沒有提早返回所以同頁再按也會重抓(self):
        """這一組量到 3 的**原因**，釘在原始碼上。

        `syncView()` 現在不比對 `view` 有沒有變，所以連按同一頁
        每一下都重跑。哪天有人加了 early return，這裡的 3 會變 1 ——
        那不是壞掉，是上面那一組從此真的驗到了「切走過」。

        **這一條紅的時候要一起改三個地方**：`SAME_PAGES`、
        `check_revisit_refetches` 的盲點一、以及這一條自己。
        """
        body = APP_JS.read_text(encoding="utf-8")
        sync = body.split("function syncView()", 1)[1].split("\n}", 1)[0]
        self.assertNotIn("return", sync,
                         "syncView() 裡出現了 return —— 它沒有回傳值，"
                         "所以那是一條 early return。同頁再按可能"
                         "不再重抓了，SAME_PAGES 的數字要重量")


class SamePageCheckCatchesThings(unittest.TestCase):
    """那支檢查自己抓不抓得到東西。合成指令清單，逼它紅。"""

    def _r(self, cmds):
        dom = ('<html><body><div id="%s" hidden>%s</div></body></html>'
               % (RC.SPY_ID, json.dumps(cmds)))
        return RC.Render(dom=dom, console=[], fixture={},
                         outdir=Path("/nonexistent"))

    def _page(self, view):
        return [p for p in RC.SAME_PAGES if p.view == view][0]

    def _ok_feat(self):
        # 2026-09-17 實測的序列。
        return ["spec_reading", "strands", "strands", "sessions",
                "features", "sessions", "features", "strands",
                "sessions", "features", "strands"]

    def test_量到的那個形狀會過(self):
        self.assertEqual(
            RC.check_samepage_refetches(self._r(self._ok_feat()),
                                        self._page("feat")), [])

    def test_少一次會紅而且說得出這不一定是壞掉(self):
        cmds = self._ok_feat()
        cmds.remove("features")
        fs = RC.check_samepage_refetches(self._r(cmds), self._page("feat"))
        self.assertTrue(fs, "少一次卻放行")
        self.assertIn("不一定是壞掉", str(fs[0]))
        self.assertIn("切走過", str(fs[0]))

    def test_每一頁少掉一次都會紅(self):
        for pg in RC.SAME_PAGES:
            own = [c for c, n in pg.expect.items()
                   if n != RC.LIVE and c != "spec_reading"] or ["spec_reading"]
            cmd = own[0]
            cmds = []
            for c, n in pg.expect.items():
                cmds += [c] * (RC.REVISIT_MIN_LIVE if n == RC.LIVE else n)
            with self.subTest(view=pg.view):
                self.assertEqual(
                    RC.check_samepage_refetches(self._r(cmds), pg), [],
                    f"{pg.view} 照表組出來的形狀自己就紅了")
                cmds.remove(cmd)
                fs = RC.check_samepage_refetches(self._r(cmds), pg)
                self.assertTrue(fs, f"{pg.view} 少發一次 {cmd} 卻放行")

    def test_順手發了別頁的指令會紅(self):
        fs = RC.check_samepage_refetches(
            self._r(self._ok_feat() + ["machine"]), self._page("feat"))
        self.assertTrue(fs, "功能那一頁去抓 machine 卻放行")
        self.assertIn("machine", str(fs[0]))

    def test_多發一次會紅而且講的是表沒跟著改(self):
        fs = RC.check_samepage_refetches(
            self._r(self._ok_feat() + ["features"]), self._page("feat"))
        self.assertTrue(fs, "多發一次卻放行")
        self.assertIn("SAME_PAGES", str(fs[0]))

    def test_觀察器沒裝上要報驗不了不是通過(self):
        for bad in (None, []):
            with self.subTest(bad=bad):
                dom = "<html><body>"
                if bad is not None:
                    dom += '<div id="%s" hidden>%s</div>' % (
                        RC.SPY_ID, json.dumps(bad))
                dom += "</body></html>"
                r = RC.Render(dom=dom, console=[], fixture={},
                              outdir=Path("/nonexistent"))
                fs = RC.check_samepage_refetches(r, self._page("feat"))
                self.assertTrue(fs, f"{bad!r} 被放行了")
                self.assertIn("驗不了", str(fs[0]))

    def test_表裡拼錯一個鍵會被抓到不是安靜跳過(self):
        bad = RC.SamePage("feat", "功能", {"featurez": 3}, "測試用")
        fs = RC.check_samepage_refetches(self._r(self._ok_feat()), bad)
        self.assertTrue(fs, "拼錯的鍵被安靜跳過了")
        self.assertIn("featurez", str(fs))
        self.assertIn("SAME_PAGES", str(fs))

    def test_一條都沒比對過要報成驗不了(self):
        real = RC.PAGE_CMDS
        try:
            RC.PAGE_CMDS = ()
            fs = RC.check_samepage_refetches(self._r(self._ok_feat()),
                                             self._page("feat"))
        finally:
            RC.PAGE_CMDS = real
        self.assertTrue(fs, "一條都沒比對卻放行")
        self.assertIn("空轉", str(fs))

    def test_兩組的紅燈訊息沒有共用(self):
        """比對邏輯共用一支，訊息不共用。

        共用訊息的話，「切回來看到舊資料」跟「`syncView()` 的射程
        變了」會講成同一句話，而那兩件事要做的處置完全不同。
        """
        cmds = self._ok_feat()
        cmds.remove("features")
        same = str(RC.check_samepage_refetches(self._r(cmds),
                                               self._page("feat"))[0])
        rev = [p for p in RC.REVISIT_PAGES if p.view == "feat"][0]
        short = ["spec_reading", "features"]
        revf = str(RC.check_revisit_refetches(self._r(short), rev)[0])
        self.assertIn("上一次的資料", revf)
        self.assertNotIn("上一次的資料", same)
        self.assertIn("不一定是壞掉", same)
        self.assertNotIn("不一定是壞掉", revf)
