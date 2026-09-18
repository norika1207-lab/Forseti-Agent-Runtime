#!/usr/bin/env python3
"""前端跟樣式之間的契約。守的是一整類靜默失敗。

2026-09-14 實際發生：改配色時刪掉了 `--accent-dark` 這個 CSS 變數，
而 `app.js` 還在用它當色點的背景。結果不是報錯，是那幾個點
**變成透明的** —— 畫面看起來正常，只是少了東西。

這跟 Forseti 整個專案在防的東西是同一類：
看起來像成功，實際上沒有發生。

這一組只做靜態比對，不需要瀏覽器。
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "desktop" / "ui"
JS = (UI / "app.js").read_text(encoding="utf-8")
CSS = (UI / "app.css").read_text(encoding="utf-8")
HTML = (UI / "index.html").read_text(encoding="utf-8")

DECLARED = set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", CSS))

# 只抓「沒有後備值」的引用。
#
# `var(--x)` 找不到 --x 就整條宣告作廢，靜默變透明。
# `var(--x, red)` 找不到就用 red，那是刻意的 —— JS 會在執行時
# 用 setProperty 塞進去（`--linkcol` 就是），沒塞成也有退路。
#
# 第一版沒分這兩種，當場把 `--linkcol` 報成錯。
# 一個會誤報的檢查，下場是被習慣性忽略，那比沒有檢查更糟。
NO_FALLBACK = re.compile(r"var\(\s*(--[a-zA-Z0-9-]+)\s*\)")



# header 底下每一個佔版面的直屬子元素，都必須讓滑鼠事件穿透，
# 否則視窗上會有一條推不動的帶子。
# header 底下的直屬子元素分兩類，每一個都必須落在其中一類:
#
#   PASSTHROUGH  純顯示，讓滑鼠事件穿透到 header 去拖視窗
#   INTERACTIVE  刻意收回事件，因為它要被點（代價是那一塊不能拖）
#
# 兩邊都沒有的，就是一條會讓視窗推不動、而且誰也沒注意到的帶子。
HEADER_KIDS_NEEDING_PASSTHROUGH = (".bar{", ".subs{", ".adviceBox{",
                                   ".ctx{", ".vitals{", ".cards{", ".panel{")
HEADER_KIDS_INTERACTIVE = ()


def _header_children() -> set:
    """<header> 底下第一層元素的 class 或 id。

    只看第一層 —— 巢狀在裡面的（.tag、.help）由它們的父層決定。
    """
    import html.parser

    class P(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = 0
            self.inside = False
            self.found: set = set()

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag == "header":
                self.inside, self.depth = True, 0
                return
            if not self.inside:
                return
            if self.depth == 0:
                key = a.get("class") or a.get("id")
                if key:
                    self.found.add(key.split()[0])
            if tag not in ("br", "img", "input", "meta", "link", "hr"):
                self.depth += 1

        def handle_endtag(self, tag):
            if tag == "header":
                self.inside = False
            elif self.inside:
                self.depth -= 1

    p = P()
    p.feed(HTML)
    return p.found


class CssVariablesResolve(unittest.TestCase):
    def test_every_var_used_in_js_is_declared(self):
        missing = sorted(set(NO_FALLBACK.findall(JS)) - DECLARED)
        self.assertEqual(missing, [], f"app.js 用了 app.css 沒有定義的變數：{missing}")

    def test_every_var_used_in_css_is_declared(self):
        missing = sorted(set(NO_FALLBACK.findall(CSS)) - DECLARED)
        self.assertEqual(missing, [], f"app.css 用了自己沒有定義的變數：{missing}")

    def test_the_check_actually_catches_a_missing_one(self):
        """反向驗證。一個永遠回空的檢查跟一個壞掉的檢查長得一樣。"""
        self.assertEqual(
            sorted(set(NO_FALLBACK.findall("a{color:var(--nope)}")) - DECLARED),
            ["--nope"])
        self.assertEqual(
            set(NO_FALLBACK.findall("a{color:var(--nope, red)}")), set())


class DomContract(unittest.TestCase):
    """JS 拿 id 拿元素，HTML 沒有那個 id 就是 null，
    然後在第一次用到它的地方才炸 —— 而那可能是幾分鐘後。"""

    def test_every_getElementById_exists_in_html(self):
        ids = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', JS))
        have = set(re.findall(r'id="([A-Za-z0-9_-]+)"', HTML))
        missing = sorted(ids - have)
        self.assertEqual(missing, [], f"app.js 找的 id 不在 index.html 裡：{missing}")


class TauriWiring(unittest.TestCase):
    """前端連不連得上後端。

    2026-09-14 實際發生，而且是這一輪最嚴重的一個：
    `.app` 編譯成功、5.1 MB、開得起來，畫面卻是空的 ——
    Tauri 2 預設不注入 `window.__TAURI__`，前端一個指令都呼叫不到。

    我當時用瀏覽器 harness 驗 UI，而那個 harness 自己 stub 掉
    `window.__TAURI__`。**我測的正好繞過了會壞的那一層。**
    UI 每個細節都驗過，唯獨「它到底連不連得上」從來沒被測到。

    這一組是靜態檢查，攔不到全部，但攔得住那一個具體的坑。
    """

    CONF = json.loads(
        (UI.parent / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    RS = (UI.parent / "src-tauri" / "src" / "main.rs").read_text(encoding="utf-8")

    def test_global_tauri_is_on(self):
        """app.js 用的是 window.__TAURI__，那就必須開這個。"""
        self.assertIn("window.__TAURI__", JS)
        self.assertIs(self.CONF["app"].get("withGlobalTauri"), True)

    def test_every_invoked_command_is_registered(self):
        """前端 invoke 的名字，Rust 那邊要真的有註冊。

        名字打錯不會編譯失敗，會在執行時回一個錯誤字串，
        然後畫面上少一塊東西。
        """
        called = set(re.findall(r'invoke\(\s*"([A-Za-z_][A-Za-z0-9_]*)"', JS))
        m = re.search(r"generate_handler!\[([^\]]*)\]", self.RS, re.S)
        self.assertIsNotNone(m, "main.rs 找不到 generate_handler!")
        registered = {x.strip() for x in m.group(1).split(",") if x.strip()}
        missing = sorted(called - registered)
        self.assertEqual(missing, [],
                         f"app.js 呼叫了 main.rs 沒註冊的指令：{missing}")

    def test_every_invoked_command_is_in_the_harness_fixture(self):
        """瀏覽器版的 fixture 也要有，不然那個功能在 harness 裡是死的。

        `tools/ui-harness.py` 自己的註解記過這個坑：2026-09-14 加了
        `spec_reading` 跟 `block_reading` 之後忘了補 fixture，
        瀏覽器版點「讀文件」什麼都沒有。**死的跟壞的長得一樣**，
        所以在 harness 裡查 UI 的人會去查一個沒有壞的地方。
        """
        root = Path(__file__).resolve().parents[1]
        harness = (root / "tools" / "ui-harness.py").read_text(encoding="utf-8")
        called = set(re.findall(r'invoke\(\s*"([A-Za-z_][A-Za-z0-9_]*)"', JS))
        # fixture 那個 dict 裡的鍵。
        m = re.search(r"fixture = \{(.*?)\}\n", harness, re.S)
        self.assertIsNotNone(m, "ui-harness.py 找不到 fixture")
        keys = set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)":', m.group(1)))
        # 這幾個是前端只在特定互動才叫的，harness 不模擬。
        skip = {"repo_path", "open_session", "fork", "act", "note_add",
                "timeline"}
        missing = sorted(called - keys - skip)
        self.assertEqual(missing, [],
                         f"app.js 呼叫了 harness fixture 沒有的指令：{missing}")

    def test_capabilities_are_inline_not_a_directory(self):
        """capability 不准放獨立檔案。

        NewDrive 是 exFAT，macOS 會寫 `._` sidecar，
        而 Tauri 的 build script 會把 `._default.json` 當成真的設定去讀，
        炸在「stream did not contain valid UTF-8」。
        同一個坑咬過兩次（先前是 permissions/._default.toml）。
        """
        caps = self.CONF["app"].get("security", {}).get("capabilities")
        self.assertTrue(caps, "capability 要內嵌在 tauri.conf.json")
        self.assertFalse((UI.parent / "src-tauri" / "capabilities").exists(),
                         "capabilities 目錄在 exFAT 上會被 ._ sidecar 咬")

    def test_window_has_a_drag_region(self):
        """沒有拖曳區的無邊框視窗，是一個推不動的視窗。

        2026-09-14 實際發生：header 掛了屬性，但 Tauri 2 看的是
        **事件目標那個元素**，不往上找父層，而 header 的子元素
        整片蓋在上面，所以拖曳區等於不存在。
        """
        self.assertIn("data-tauri-drag-region", HTML)
        # 蓋在拖曳區上的純顯示元素必須讓事件穿透，否則屬性是白掛的。
        for sel in HEADER_KIDS_NEEDING_PASSTHROUGH:
            block = CSS.split(sel, 1)[1].split("}", 1)[0] if sel in CSS else ""
            self.assertIn("pointer-events:none", block,
                          f"{sel} 蓋住拖曳區卻會吃掉滑鼠事件")
        # 刻意可互動的那些，要明講自己收回了事件，不是忘了寫。
        for sel in HEADER_KIDS_INTERACTIVE:
            block = CSS.split(sel, 1)[1].split("}", 1)[0] if sel in CSS else ""
            self.assertIn("pointer-events:auto", block,
                          f"{sel} 要被點就要明講 pointer-events:auto")

    def test_the_passthrough_list_covers_every_header_child(self):
        """上面那條檢查列的清單，要真的涵蓋 header 的每一個直屬子元素。

        2026-09-14 這條抓到兩次真的疏漏：canvas 包進 `.pool` 之後
        檢查還指著 `#temp`；後來整個頂部改成資訊中心，多了 `.bar`
        跟兩個 `<p>`，清單又落後了。**清單自己會過時**，
        所以要有一條檢查盯著清單。
        """
        kids = _header_children()
        checked = {x.strip(".#{") for x in
                   HEADER_KIDS_NEEDING_PASSTHROUGH + HEADER_KIDS_INTERACTIVE}
        missing = sorted(kids - checked)
        self.assertEqual(missing, [],
                         f"header 多了沒被拖曳檢查涵蓋的區塊：{missing}")


class HiddenActuallyHides(unittest.TestCase):
    """用 [hidden] 開關的元素，要自己把 display:none 寫回來。

    2026-09-14：`.sheet{display:flex}` 的優先級蓋過瀏覽器對 hidden 的
    預設樣式，圖例面板永遠開著。這種 bug 不會報錯，
    只會讓一個開關看起來壞掉。
    """

    def test_every_hidden_toggled_element_has_a_rule(self):
        ids = set(re.findall(r'id="([A-Za-z0-9_-]+)"[^>]*\shidden', HTML))
        for el in ids:
            cls = re.search(rf'class="([a-z-]+)"[^>]*id="{el}"', HTML) \
                or re.search(rf'id="{el}"[^>]*class="([a-z-]+)"', HTML)
            sel = f'.{cls.group(1).split()[0]}' if cls else f"#{el}"
            block = CSS.split(sel + "{", 1)
            if len(block) < 2:
                continue          # 沒有自己的 display 規則，瀏覽器預設就夠
            if "display:" not in block[1].split("}", 1)[0]:
                continue
            self.assertIn(f"{sel}[hidden]", CSS,
                          f"{sel} 設了 display 卻沒有 [hidden] 規則，"
                          f"那個開關會壞掉")


class DraggableAreaStaysBigEnough(unittest.TestCase):
    """頂部不准被可互動元素吃光。

    2026-09-14 同一天發生兩次:
    第一次是 canvas 跟數字區蓋住 header，視窗完全推不動；
    第二次是建議那塊改成可點、分項那幾格為了 tooltip 收走事件，
    加起來又把頂部吃掉。

    兩次都是加了可互動的東西之後，沒回頭看還剩多少地方能拖。
    """

    def test_full_width_header_children_do_not_take_pointer_events(self):
        # 佔滿整條寬度的那些子元素，一律要讓事件穿透。
        # 要被點的話，只能在它裡面的小元件上收回（像漢堡跟問號）。
        for sel in (".bar{", ".subs{", ".adviceBox{", ".ctx{"):
            block = CSS.split(sel, 1)[1].split("}", 1)[0] if sel in CSS else ""
            self.assertIn("pointer-events:none", block,
                          f"{sel} 佔滿整條寬度，不能收走滑鼠事件")

    def test_sub_cells_do_not_take_pointer_events(self):
        """分項那幾格是 flex:1，一格就吃掉整條。"""
        block = CSS.split(".sub{", 1)[1].split("}", 1)[0]
        self.assertIn("pointer-events:none", block)


class NoShadowedDefinitions(unittest.TestCase):
    """同一個模組裡不准有兩個同名的頂層定義。

    2026-09-14：改寫 `focused_session()` 的時候留下了舊的那一份在檔案後面。
    Python 不報錯，只是靜默用了後面那個 —— 也就是被我淘汰掉的實作。
    症狀是「我明明改好了，跑起來卻還是舊行為」。
    """

    def test_no_duplicate_top_level_defs(self):
        import ast
        root = Path(__file__).resolve().parents[1]
        # 跳過 `._` 開頭的。
        #
        # NewDrive 是 exFAT，macOS 會為帶 xattr 的檔案寫一個 AppleDouble
        # sidecar，檔名就是原檔加 `._` 前綴，內容是二進位。
        # **同一個坑在這個專案咬過三次**：Tauri 的 permissions 目錄、
        # capabilities 目錄，現在是這條檢查自己。
        # 任何在這個 repo 裡 glob 檔案的程式碼都要記得這件事。
        files = [f for f in sorted((root / "apps" / "forseti-cli").glob("*.py"))
                 if not f.name.startswith("._")]
        self.assertTrue(files, "掃不到任何 .py，檢查等於沒跑")
        for py in files:
            tree = ast.parse(py.read_text(encoding="utf-8"))
            names = [n.name for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                       ast.ClassDef))]
            dup = sorted({x for x in names if names.count(x) > 1})
            self.assertEqual(dup, [], f"{py.name} 有重複的頂層定義：{dup}")


class NoDuplicateJsDefs(unittest.TestCase):
    """app.js 裡不准有兩個同名的頂層定義。

    2026-09-16 差點出事：接管閘門那一塊新增了一個 `renderGate`，
    而第 326 行早就有一個 `renderGate`（目標錨點閘門，FS-GOL-001）。
    JavaScript 不會報錯，**後面那個直接蓋掉前面那個** ——
    畫面上目標錨點那一格會靜默變成另一個東西。

    Python 端早就有同型的檢查（`test_no_duplicate_top_level_defs`），
    JS 端先前沒有。這一條就是把那個缺口補上。
    """

    #: 行首沒有縮排的定義才算頂層。
    DEF = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(",
                     re.MULTILINE)
    LET = re.compile(r"^(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=",
                     re.MULTILINE)

    def _names(self):
        return self.DEF.findall(JS) + self.LET.findall(JS)

    def test_no_duplicate_top_level_defs_in_app_js(self):
        names = self._names()
        self.assertTrue(names, "一個頂層定義都抓不到，這條檢查等於沒跑")
        dup = sorted({x for x in names if names.count(x) > 1})
        self.assertEqual(dup, [], f"app.js 有重複的頂層定義：{dup}")

    def test_the_check_actually_catches_a_duplicate(self):
        """檢查自己要抓得到問題，不然它只是一行綠燈。"""
        fake = "function a() {}\nfunction a() {}\nconst b = 1;\n"
        names = self.DEF.findall(fake) + self.LET.findall(fake)
        self.assertEqual(sorted({x for x in names if names.count(x) > 1}), ["a"])


class RenderersAreActuallyCalled(unittest.TestCase):
    """寫了一個 render 函式卻沒有人叫它，畫面上就什麼都不會多出來。

    ROADMAP 明寫的禁區之一：「不為了盤點數字接輔助函式。接上去畫面
    不會變的東西，接了就是白工。」一個定義了但沒被呼叫的渲染函式，
    在檔案裡看起來跟做完了一模一樣。

    **2026-09-16 23:4x 這一組整個改嚴，因為舊版守不住。**

    舊版對每個名字要求全檔至少出現兩次（定義算一次）。**有兩條呼叫
    路徑的那些因此守不住** —— 拿掉其中一條之後全檔仍然是兩次以上。
    實測（2026-09-16 23:4x）：拿掉輪詢那一條之後 `renderDims` 剩 2 次、
    `renderGate` 剩 2 次、`renderVitals` 剩 2 次、`renderCards` 剩 3 次，
    舊判準四個全部不會紅。同一個弱點 `renderProbe` 那一組在
    2026-09-16 22:1x 反向驗證時實測沒抓到，當時只改了
    identity / workflow / probe 三格。

    只有一條路徑的那些（`renderSubs`、`renderRescue`）舊判準抓得到，
    因為拿掉之後只剩定義那一次。所以舊版不是全盤失效，是漏掉
    「有備援路徑所以看起來還在」的那一類 —— 而那一類正是多數。

    展開區另外六格當時沒有一起改，而其中四格
    （`renderDims`、`renderHealthCurve`、`renderBlast`、`renderGate`）
    在整套測試裡**一條接線斷言都沒有** —— 把輪詢那一段裡任何一個
    整行刪掉，1119 條測試全綠，畫面上那一格打開之後就凍住。

    兩條路徑各自會壞，症狀不一樣：拿掉輪詢那一條，這一格打開之後
    不再更新；拿掉展開那一條，要等下一次輪詢才會出現。所以分開釘。
    """

    #: `.dims` 那個開關底下的九格，兩條路徑都要有人叫。
    #:
    #: **這份清單是寫死的，不從程式碼推導。** 從程式碼推導的話，
    #: 刪掉一行的同時清單也跟著縮小，那條檢查會永遠綠。
    DIMS_PANELS = ("renderDims", "renderHealthCurve", "renderBlast",
                   "renderGate", "renderPollution", "renderSot",
                   "renderIdentity", "renderWorkflow", "renderProbe")

    #: 面板收起的時候也要跑的那幾個，在主輪詢裡。
    MAIN = ("renderSubs", "renderVitals", "renderCards", "renderRescue")

    #: 溫度卡開合的時候補畫的那兩個。`renderRescue` 不在這裡，
    #: 它只走主輪詢一條路 —— 照實際程式碼寫，不補一個它沒有的要求。
    TOGGLE = ("renderVitals", "renderCards")

    def _block(self, pattern, what):
        m = re.search(pattern, JS, re.S)
        self.assertIsNotNone(m, f"找不到{what}，這條檢查等於沒跑")
        return m.group(1)

    def _poll(self):
        return self._block(
            r'if \(document\.querySelector\("\.dims\.open"\)\) \{'
            r'(.*?)\n    \}', "輪詢那一段")

    def _expand(self):
        return self._block(
            r'\$\("vWhy"\)\?\.addEventListener\((.*?)\n\}\);',
            "展開按鈕那一段")

    def _main(self):
        return self._block(
            r'\n    setAdvice\(d\);(.*?)\n    if \(document\.querySelector'
            r'\("\.dims\.open"\)\)', "主輪詢那一段")

    def _toggle(self):
        return self._block(r'function togglePanel\(force\) \{(.*?)\n\}',
                           "溫度卡開合那一段")

    def test_每一個渲染函式都真的有定義(self):
        for name in self.DIMS_PANELS + self.MAIN:
            self.assertIn(f"function {name}(", JS, f"{name} 沒有定義")

    def test_展開區九格在輪詢那一段都有人叫(self):
        poll = self._poll()
        for name in self.DIMS_PANELS:
            self.assertIn(f"{name}(d)", poll,
                          f"輪詢那一段沒有叫 {name}，這一格打開之後會凍住")

    def test_展開區九格在展開按鈕那一段都有人叫(self):
        exp = self._expand()
        for name in self.DIMS_PANELS:
            self.assertIn(f"{name}(lastSnap", exp,
                          f"展開按鈕那一段沒有叫 {name}，要等下一次輪詢才出現")

    def test_輪詢那一段沒有清單以外的格(self):
        """新增一格卻忘了加進清單，這一條會紅。

        上面兩條守的是「清單裡的有沒有被叫」，守不住「程式碼裡多了
        一格而清單不知道」—— 那一格就回到沒有任何接線斷言的狀態。
        """
        found = set(re.findall(r"\b(render[A-Za-z]+)\(", self._poll()))
        self.assertEqual(found, set(self.DIMS_PANELS),
                         "輪詢那一段的格數跟 DIMS_PANELS 對不起來")

    def test_展開那一段沒有清單以外的格(self):
        found = set(re.findall(r"\b(render[A-Za-z]+)\(", self._expand()))
        self.assertEqual(found, set(self.DIMS_PANELS),
                         "展開那一段的格數跟 DIMS_PANELS 對不起來")

    def test_主輪詢那幾個都有人叫(self):
        main = self._main()
        for name in self.MAIN:
            self.assertIn(f"{name}(d)", main,
                          f"主輪詢那一段沒有叫 {name}，面板收起時那一塊不會更新")

    def test_溫度卡開合的時候補畫那兩個(self):
        tog = self._toggle()
        for name in self.TOGGLE:
            self.assertIn(f"{name}(lastSnap", tog,
                          f"溫度卡打開的時候沒有叫 {name}，要等下一次輪詢才出現")

    def test_這一組的區間抓法自己要抓得到問題(self):
        """四個區間任何一個抓不到，上面那幾條會安靜地跳過。

        `_block` 抓不到就 assert 失敗，這一條確認那個失敗真的會發生，
        不是靠 `re.search` 回 None 之後默默往下走。
        """
        for fn, what in ((self._poll, "輪詢"), (self._expand, "展開"),
                         (self._main, "主輪詢"), (self._toggle, "溫度卡")):
            self.assertTrue(fn().strip(), f"{what}那一段抓出來是空的")


class ViewRenderersAreActuallyCalled(unittest.TestCase):
    """七個分頁的渲染函式，兩條分派路徑都要有人叫。

    `RenderersAreActuallyCalled` 守的是 `.dims` 開關底下那九格，
    走的是完全不同的一段程式碼。分頁這一批走 `view === "..."` 的
    if-else 鏈，在整套測試裡**一條接線斷言都沒有** ——
    `renderTree`、`renderWork`、`renderMachine`、`renderFeat`、
    `renderAudit`、`renderSpec`、`renderList` 七個，`tests/` 裡
    grep 得到的只有 `test_js_symbols.py` 提到 `renderTree` 的那句註解。

    **這件事是實測的，不是推論。** 2026-09-17：把輪詢分派裡
    `else if (view === "work") renderWork();` 整行刪掉，
    `python3 -m pytest tests/ -q` 1126 條全綠。

    兩條路徑各自會壞，症狀不一樣，所以分開釘：

      一，輪詢那一條被刪 → 切進那一頁看得到內容（`syncView` 畫過
          一次），之後永遠不再更新。畫面上跟「這一頁沒有新資料」
          長得一模一樣
      二，`syncView` 那一條被刪 → 按下分頁按鈕畫面不換，停在前一頁，
          要等下一次輪詢才換過去

    `test_js_symbols.py` 守不到這一類，它守的是反方向（被呼叫但
    沒定義）。整行刪掉之後函式還在、沒有人叫它，那條不會紅。
    """

    #: 七個分頁各自的渲染函式。**這份清單是寫死的，不從程式碼推導。**
    #: 從程式碼推導的話，刪掉一行的同時清單也跟著縮小，
    #: 那條檢查會永遠綠（`RenderersAreActuallyCalled` 付過這個代價）。
    #:
    #: `renderList` 是 else 那一支，對應 `index.html` 的
    #: `data-view="list"`（需要注意）。
    VIEW_RENDERERS = ("renderTree", "renderWork", "renderMachine",
                      "renderFeat", "renderAudit", "renderSpec",
                      "renderList")

    #: `index.html` 底下那排按鈕的 `data-view`。用來確認分派鏈
    #: 沒有漏掉任何一個按鈕得到的頁 —— 漏掉的那一頁按下去會掉進
    #: else，畫出來的是別頁的內容，而且不會有錯誤訊息。
    VIEW_NAMES = ("tree", "work", "machine", "feat", "audit", "spec")

    #: 切分頁的時候要清掉的那五個模組層快取。`tree` 與 `list`
    #: 不在這裡，它們沒有快取變數 —— 照實際程式碼寫，
    #: 不補一個它們沒有的要求。
    CACHES = ("workCache", "machCache", "featCache", "auditCache",
              "specCache")

    def _block(self, pattern, what):
        m = re.search(pattern, JS, re.S)
        self.assertIsNotNone(m, f"找不到{what}，這條檢查等於沒跑")
        return m.group(1)

    def _poll_dispatch(self):
        """輪詢尾段那條分派。

        右界是後面那句 `if (follow && view === "tree")`，因為
        `syncView` 裡有一段長得幾乎一樣，只抓前綴會抓錯段。

        **左界刻意不綁 `renderTree` 那一行。** 第一版綁了，結果
        刪掉那一行的時候報的是「找不到輪詢分派那一段，這條檢查等於
        沒跑」—— 那句話把人指向測試的區間抓法，而真正發生的事是
        那一頁不再更新。**一個指錯方向的訊息比沒有訊息糟**，
        所以改成從 `.dims` 區塊的收尾往下吃連續的 if/else 行，
        少了哪一行就由下面那幾條各自指名。
        """
        return self._block(
            r'\n    \}\n((?:    (?:if|else)[^\n]*\n)+)'
            r'    if \(follow && view === "tree"\)', "輪詢分派那一段")

    def _sync_dispatch(self):
        return self._block(r'function syncView\(\) \{(.*?)\n\}',
                           "切分頁那一段")

    def test_七個分頁的渲染函式都真的有定義(self):
        for name in self.VIEW_RENDERERS:
            self.assertRegex(
                JS, rf"(?:async\s+)?function {name}\(",
                f"{name} 沒有定義，那一頁按下去是 ReferenceError")

    def test_輪詢那一段每一頁都有人叫(self):
        seg = self._poll_dispatch()
        for name in self.VIEW_RENDERERS:
            self.assertIn(f"{name}()", seg,
                          f"輪詢分派沒有叫 {name}，那一頁切進去之後不再更新")

    def test_切分頁那一段每一頁都有人叫(self):
        seg = self._sync_dispatch()
        for name in self.VIEW_RENDERERS:
            self.assertIn(f"{name}()", seg,
                          f"syncView 沒有叫 {name}，按下那個分頁畫面不會換")

    def test_輪詢分派沒有清單以外的頁(self):
        """新增一頁卻忘了加進清單，這一條會紅。

        上面兩條守的是「清單裡的有沒有被叫」，守不住「程式碼裡多了
        一頁而清單不知道」—— 那一頁就回到沒有任何接線斷言的狀態。
        """
        seg = self._poll_dispatch()
        found = set(re.findall(r"\b(render[A-Za-z]+)\(", seg))
        self.assertEqual(found, set(self.VIEW_RENDERERS),
                         "輪詢分派的頁數跟 VIEW_RENDERERS 對不起來")

    def test_切分頁分派沒有清單以外的頁(self):
        found = set(re.findall(r"\b(render[A-Za-z]+)\(",
                               self._sync_dispatch()))
        self.assertEqual(found, set(self.VIEW_RENDERERS),
                         "syncView 的頁數跟 VIEW_RENDERERS 對不起來")

    def test_兩條分派認得的頁一樣(self):
        """一條認得六個 view 值、另一條只認得五個，多的那一頁會掉進
        else，於是它在其中一條路徑上畫出來的是「需要注意」那一頁的
        內容。兩邊都是合法的 JS，不會有任何錯誤訊息。
        """
        poll = set(re.findall(r'view === "([a-z]+)"', self._poll_dispatch()))
        sync = set(re.findall(r'view === "([a-z]+)"', self._sync_dispatch()))
        self.assertEqual(poll, sync, "兩條分派認得的 view 值不一樣")
        self.assertEqual(poll, set(self.VIEW_NAMES),
                         "分派認得的 view 值跟 VIEW_NAMES 對不起來")

    def test_分派認得的頁跟按鈕對得起來(self):
        """按鈕在 HTML 裡，分派在 JS 裡，兩份各自改得動。

        按鈕多一個而分派不知道，那一頁按下去掉進 else，
        畫出來的是別頁的內容 —— 不是空白，所以不像壞掉。
        """
        buttons = set(re.findall(r'data-view="([a-z]+)"', HTML))
        self.assertEqual(buttons - {"list"}, set(self.VIEW_NAMES),
                         "HTML 的分頁按鈕跟 JS 的分派對不起來")
        self.assertIn("list", buttons,
                      "else 那一支對應的 data-view=\"list\" 不見了")

    def test_切分頁的時候那五個快取有被清掉(self):
        """快取不清的症狀是「畫面上是上一次切進來時的資料」，
        而它跟一份剛抓的資料長得一模一樣。

        `renderWork` 那幾支都是 `if (!xCache)` 才去 invoke，
        所以少了這一行就等於那一頁永遠是第一次的內容。
        """
        seg = self._sync_dispatch()
        for name in self.CACHES:
            self.assertIn(f"{name} = null", seg,
                          f"切分頁時沒有清掉 {name}，那一頁會停在舊資料")

    def test_那五個快取變數真的存在而且真的在擋(self):
        """上面那條比對的是字串。變數名改掉而 syncView 沒跟著改，
        會變成宣告一個新的全域，`if (!xCache)` 那一支照樣永遠是舊值。
        """
        for name in self.CACHES:
            self.assertIn(f"let {name} = null;", JS, f"{name} 沒有宣告")
            self.assertIn(f"if (!{name})", JS,
                          f"{name} 沒有被拿來擋重抓，清它沒有意義")

    def test_這一組的區間抓法自己要抓得到問題(self):
        """兩個區間任何一個抓不到，上面那幾條會安靜地跳過。"""
        for fn, what in ((self._poll_dispatch, "輪詢分派"),
                         (self._sync_dispatch, "切分頁")):
            self.assertTrue(fn().strip(), f"{what}那一段抓出來是空的")

    def test_兩個區間不是同一段(self):
        """`syncView` 裡那段跟輪詢那段長得幾乎一樣。抓錯的話兩組
        斷言會同時比對同一段程式碼，於是其中一條路徑等於沒有人守。
        """
        self.assertNotIn("function syncView", self._poll_dispatch(),
                         "輪詢分派抓過頭，抓進 syncView 了")
        self.assertNotIn("follow && view", self._sync_dispatch(),
                         "切分頁那一段抓過頭，抓進輪詢那一段了")


class IdentityPanelIsWiredEndToEnd(unittest.TestCase):
    """§11.1 那一格，三段接線任何一段斷掉都不會報錯，只會少東西。

    這一類 bug 2026-09-14 發生過一次（`--accent-dark` 被刪，色點變透明，
    畫面看起來正常）。這裡守的是同一件事，只是換一格:

      一，渲染函式寫了但沒有人叫它 → 畫面上什麼都不會多出來
      二，JS 用了一個 CSS 沒定義的 class → 那一塊沒有樣式，
          在深色底上可能等於看不見
      三，後端沒有把 `identity` 放進 snapshot → 永遠走到 has=False 那一支，
          而那一支印的是「算不出來」，讀起來像這一格壞了
    """

    #: 這一格用到的 class。JS 裡寫死的字串，CSS 裡必須找得到。
    CLASSES = ("idn", "idnList", "idnMore", "idnRow", "idnHead", "idnSt",
               "idnTy", "idnQ", "idnLive", "idnEv", "idnStale", "idnNote",
               "idnCache")

    def test_渲染函式在兩條路徑上都有人叫(self):
        """**只數次數的版本守不住這件事，實測過。**

        `renderIdentity` 全檔出現三次：一次定義、輪詢那一段一次、
        展開按鈕那一段一次。舊版要求「至少兩次」，所以拿掉其中
        一條呼叫路徑之後仍然是兩次，測試不會紅。同樣的寫法在
        `renderProbe` 那一組反向驗證時實測沒抓到（2026-09-16 22:1x），
        這兩組當時沒有一起改，2026-09-16 22:4x 補上。

        兩條路徑各自會壞，症狀也不一樣：拿掉輪詢那一條，這一格
        打開之後就凍住不再更新；拿掉展開那一條，要等下一次輪詢
        才會出現。所以分開釘。
        """
        self.assertIn("function renderIdentity(", JS)
        m = re.search(r'if \(document\.querySelector\("\.dims\.open"\)\) \{'
                      r'(.*?)\n    \}', JS, re.S)
        self.assertIsNotNone(m, "找不到輪詢那一段")
        self.assertIn("renderIdentity(d)", m.group(1),
                      "輪詢那一段沒有叫 renderIdentity，這一格打開之後會凍住")
        m2 = re.search(r'\$\("vWhy"\)\?\.addEventListener\((.*?)\n\}\);',
                       JS, re.S)
        self.assertIsNotNone(m2, "找不到展開按鈕那一段")
        self.assertIn("renderIdentity(lastSnap", m2.group(1),
                      "展開按鈕那一段沒有叫 renderIdentity，要等下一次輪詢才出現")

    def test_每一個class在css裡都定義得到(self):
        for c in self.CLASSES:
            self.assertRegex(CSS, rf"\.{c}[\s,.:{{]",
                             f".{c} 在 JS 裡用了，CSS 沒有定義")

    def test_跟八維度共用同一個展開開關(self):
        # 長第二套展開狀態的話，兩套會分歧，而分歧那天沒有人會發現。
        self.assertIn(".dims.open ~ .idn", CSS)

    def test_快取命中那句話三段都接上(self):
        """2026-09-16 21:5x 加的磁碟快取要看得見。

        一個用上一次結果算出來的數字，跟一個剛剛量出來的，
        在畫面上長得一模一樣。三段任何一段斷掉都不會報錯:
        後端不組那句話、JS 不印、CSS 沒有那個 class。
        """
        api = (Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
               / "desktop_api.py").read_text(encoding="utf-8")
        self.assertIn("cache_note", JS, "JS 沒有用 cache_note")
        self.assertIn('"cache_note"', api,
                      "後端 identity_panel 沒有把 cache_note 放進去")
        # 0 條命中的時候不准印出一句空話。
        self.assertRegex(JS, r"t\.cache_note\s*\n?\s*\?")

    def test_後端有把identity放進snapshot(self):
        api = (Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
               / "desktop_api.py").read_text(encoding="utf-8")
        self.assertIn('snap["identity"]', api)
        self.assertIn("def identity_panel(", api)

    def test_算不出來的時候不回空清單(self):
        # 空清單在畫面上讀起來是「五個軸都沒事」，那是一句沒有根據的話。
        api = (Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
               / "desktop_api.py").read_text(encoding="utf-8")
        m = re.search(r'snap\["identity"\][^\n]*\n(?:[^\n]*\n){0,3}', api)
        self.assertIsNotNone(m)
        self.assertIn("不是身份沒問題", m.group(0))


class WorkflowPanelIsWiredEndToEnd(unittest.TestCase):
    """§5 / §17.1 那一格，三段接線任何一段斷掉都不會報錯，只會少東西。

    跟 `IdentityPanelIsWiredEndToEnd` 守的是同一件事，換一格。
    多守一條:捲動位置沒留住的話，使用者捲到第 3 件，兩秒後自己彈回
    頂端，而且沒有任何錯誤訊息（這個專案已經為同一件事修過三次:
    blast 搜尋框、pollution 捲動、identity 捲動）。
    """

    #: 這一格用到的 class。JS 裡寫死的字串，CSS 裡必須找得到。
    CLASSES = ("wfl", "wflList", "wflMore", "wflRow", "wflHead", "wflSt",
               "wflId", "wflObj", "wflCnt", "wflReady", "wflBlocked",
               "wflBad", "wflBd", "wflMiss", "wflMs", "wflNote")

    def test_渲染函式在兩條路徑上都有人叫(self):
        """**只數次數的版本守不住這件事，實測過。**

        `renderWorkflow` 全檔出現三次：一次定義、輪詢那一段一次、
        展開按鈕那一段一次。舊版要求「至少兩次」，所以拿掉其中
        一條呼叫路徑之後仍然是兩次，測試不會紅。同樣的寫法在
        `renderProbe` 那一組反向驗證時實測沒抓到（2026-09-16 22:1x），
        這兩組當時沒有一起改，2026-09-16 22:4x 補上。

        兩條路徑各自會壞，症狀也不一樣：拿掉輪詢那一條，這一格
        打開之後就凍住不再更新；拿掉展開那一條，要等下一次輪詢
        才會出現。所以分開釘。
        """
        self.assertIn("function renderWorkflow(", JS)
        m = re.search(r'if \(document\.querySelector\("\.dims\.open"\)\) \{'
                      r'(.*?)\n    \}', JS, re.S)
        self.assertIsNotNone(m, "找不到輪詢那一段")
        self.assertIn("renderWorkflow(d)", m.group(1),
                      "輪詢那一段沒有叫 renderWorkflow，這一格打開之後會凍住")
        m2 = re.search(r'\$\("vWhy"\)\?\.addEventListener\((.*?)\n\}\);',
                       JS, re.S)
        self.assertIsNotNone(m2, "找不到展開按鈕那一段")
        self.assertIn("renderWorkflow(lastSnap", m2.group(1),
                      "展開按鈕那一段沒有叫 renderWorkflow，要等下一次輪詢才出現")

    def test_每一個class在css裡都定義得到(self):
        for c in self.CLASSES:
            self.assertRegex(CSS, rf"\.{c}[\s,.:{{]",
                             f".{c} 在 JS 裡用了，CSS 沒有定義")

    def test_跟八維度共用同一個展開開關(self):
        self.assertIn(".dims.open ~ .wfl", CSS)

    def test_後端有把workflow放進snapshot(self):
        api = (Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
               / "desktop_api.py").read_text(encoding="utf-8")
        self.assertIn('snap["workflow"]', api)
        self.assertIn("def workflow_panel(", api)

    def test_算不出來的時候不回空清單(self):
        # 空清單在畫面上讀起來是「沒有待續的工作」，那是一句沒有根據的話。
        api = (Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
               / "desktop_api.py").read_text(encoding="utf-8")
        m = re.search(r'snap\["workflow"\][^\n]*\n(?:[^\n]*\n){0,3}', api)
        self.assertIsNotNone(m)
        self.assertIn("不是沒有待續的", m.group(0))

    def test_捲動位置在重畫之後要放回去(self):
        # 不放回去的症狀是「後面那幾件永遠看不到」，而且不會報錯。
        self.assertIn("wflList", JS)
        m = re.search(r"function renderWorkflow\(d\) \{(.*?)\n\}\n",
                      JS, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("keepScroll", body)
        self.assertIn("scrollTop = Math.min(keepScroll", body)

    def test_沒有人登記過不准畫成不跨邊界(self):
        # UNDECLARED 是「沒有人回答過」，NONE 是「有人看過而且說不跨」。
        # 這兩件事的下一步不一樣，畫面上不准混成一句。
        self.assertIn("WF_BD_ZH", JS)
        self.assertIn("沒有人登記過", JS)
        m = re.search(r"const WF_BD_ZH = \{(.*?)\};", JS, re.S)
        self.assertIsNotNone(m)
        self.assertIn("UNDECLARED", m.group(1))
        self.assertIn("NONE", m.group(1))
        self.assertNotIn("不跨邊界", m.group(1).split("NONE")[0])


class ProbePanelIsWiredEndToEnd(unittest.TestCase):
    """§15 那一格。跟前兩格守的是同一類靜默失敗，多守三條這一格特有的。

    這一格如果畫錯，錯的方向會是「看起來比實際好」：
    十類裡只有九類量得到，而沒有東西可量的那一類如果跟通過畫成同一個
    樣子，一張全綠的表會讓人以為十類都驗過了。
    """

    #: 這一格用到的 class。JS 裡寫死的字串，CSS 裡必須找得到。
    CLASSES = ("prb", "prbList", "prbMore", "prbRow", "prbHead", "prbSt",
               "prbId", "prbDm", "prbWhy", "prbChg", "prbNv", "prbWarn",
               "prbNote")

    def test_渲染函式在兩條路徑上都有人叫(self):
        """**只數次數的版本守不住這件事，實測過。**

        `renderProbe` 全檔出現三次：一次定義、輪詢那一段一次、
        展開按鈕那一段一次。所以「至少兩次」在拿掉其中一條呼叫路徑
        之後仍然成立 —— 反向驗證第 1 次沒抓到，就是這個原因。

        兩條路徑各自會壞，症狀也不一樣：拿掉輪詢那一條，這一格
        打開之後就凍住不再更新；拿掉展開那一條，要等下一次輪詢
        才會出現。所以分開釘。

        註：`renderIdentity` 與 `renderWorkflow` 那兩組測試原本有同一個
        弱點，2026-09-16 22:4x 已經照這一組的寫法改嚴，四條路徑
        各自反向驗證過。
        """
        self.assertIn("function renderProbe(", JS)
        m = re.search(r'if \(document\.querySelector\("\.dims\.open"\)\) \{'
                      r'(.*?)\n    \}', JS, re.S)
        self.assertIsNotNone(m, "找不到輪詢那一段")
        self.assertIn("renderProbe(d)", m.group(1),
                      "輪詢那一段沒有叫 renderProbe，這一格打開之後會凍住")
        m2 = re.search(r'\$\("vWhy"\)\?\.addEventListener\((.*?)\n\}\);',
                       JS, re.S)
        self.assertIsNotNone(m2, "找不到展開按鈕那一段")
        self.assertIn("renderProbe(lastSnap", m2.group(1),
                      "展開按鈕那一段沒有叫 renderProbe，要等下一次輪詢才出現")

    def test_每一個class在css裡都定義得到(self):
        for c in self.CLASSES:
            self.assertRegex(CSS, rf"\.{c}[\s,.:{{]",
                             f".{c} 在 JS 裡用了，CSS 沒有定義")

    def test_跟八維度共用同一個展開開關(self):
        self.assertIn(".dims.open ~ .prb", CSS)

    def test_後端有把probe放進snapshot(self):
        api = (Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
               / "desktop_api.py").read_text(encoding="utf-8")
        self.assertIn('snap["probe"]', api)
        self.assertIn("def probe_panel(", api)

    def test_算不出來的時候不回空清單(self):
        # 空清單讀起來是「沒有哪一類退化」，那是一句沒有根據的話。
        api = (Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
               / "desktop_api.py").read_text(encoding="utf-8")
        m = re.search(r'snap\["probe"\][^\n]*\n(?:[^\n]*\n){0,3}', api)
        self.assertIsNotNone(m)
        # **兩處都要。** `_safe` 的預設值與後面那個 `or` 是兩個各自
        # 會被改掉的地方，只檢查一次的版本在反向驗證第 4 次沒抓到。
        self.assertEqual(m.group(0).count("不是沒有哪一類退化"), 2,
                         "_safe 的預設值與 or 後面那個要各有一份")

    def test_捲動位置在重畫之後要放回去(self):
        self.assertIn("prbList", JS)
        m = re.search(r"function renderProbe\(d\) \{(.*?)\n\}\n", JS, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("keepScroll", body)
        self.assertIn("scrollTop = Math.min(keepScroll", body)

    def test_沒有東西可量不准跟通過畫成同一個樣子(self):
        """這一格存在的理由就是這一條。

        `NO_VERIFIER` 跟 `PASS` 如果同色同字，十類裡只有九類量得到
        這件事在畫面上就消失了，而消失的方向是「看起來比實際好」。
        """
        m = re.search(r"const PRB_ZH = \{(.*?)\};", JS, re.S)
        self.assertIsNotNone(m, "PRB_ZH 不見了")
        body = m.group(1)
        self.assertIn("NO_VERIFIER", body)
        self.assertNotIn("通過", body.split("NO_VERIFIER")[1])
        # 顏色也要分開，不是只有字不一樣。
        self.assertRegex(CSS, r"\.prbSt\.NO_VERIFIER\s*\{")
        # 而且它不進通過率的分母 —— 那句話要在畫面上，不是只在註解裡。
        self.assertIn("不算進通過率的分母", JS)

    def test_通過率的分母用的是可量的那個數(self):
        # 用 10 當分母的話，9 個 PASS 會變成 90%，而實情是 9/9。
        m = re.search(r"function renderProbe\(d\) \{(.*?)\n\}\n", JS, re.S)
        self.assertIsNotNone(m)
        self.assertIn("t.measurable", m.group(1))

    def test_沒有基準線要自己講不能讓人從NEW去推(self):
        m = re.search(r"function renderProbe\(d\) \{(.*?)\n\}\n", JS, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("t.has_baseline", body)
        self.assertIn("還沒有基準線", body)

    def test_基準線多舊要印出來(self):
        """一條三個月前的基準線跟一條剛剛錄的，在「跟基準線一致」
        這句話裡分量差很多。兩段任何一段斷掉都不會報錯。"""
        api = (Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"
               / "desktop_api.py").read_text(encoding="utf-8")
        self.assertIn('"baseline_at"', api,
                      "後端 probe_panel 沒有把 baseline_at 帶出來")
        self.assertIn("t.baseline_at", JS, "JS 沒有用 baseline_at")

    def test_跨不了的那兩軸畫面上要看得到(self):
        m = re.search(r"function renderProbe\(d\) \{(.*?)\n\}\n", JS, re.S)
        self.assertIsNotNone(m)
        body = m.group(1)
        self.assertIn("axes_missing", body)
        self.assertIn("axes_why", body)


class TypingSurvivesRepaint(unittest.TestCase):
    """**每 1 到 3 秒重畫一次的面板上放一個輸入框，預設會吃掉使用者的字。**

    `renderBlast` 整塊換 `innerHTML`，所以搜尋框每次輪詢都是一個全新的
    節點：value 回到空的、焦點跑掉、游標位置不見。使用者看到的是
    「打到一半字自己消失」，而程式沒有任何錯誤。這是這個專案在防的
    那一類：看起來像成功，實際上沒有發生。

    這三條釘住三個各自獨立會壞的點。
    """

    def test_搜尋框的字在重畫之後要被放回去(self):
        self.assertIn("inp.value = blastQuery", JS,
                      "重畫後沒有把 blastQuery 寫回輸入框，字會每隔幾秒消失")

    def test_焦點與游標位置也要放回去(self):
        self.assertIn("setSelectionRange", JS,
                      "只還原 value 不還原游標，游標會每次跳到開頭")
        self.assertIn("document.activeElement", JS,
                      "沒有判斷原本有沒有焦點，會在使用者沒在打字時亂搶焦點")

    def test_輸入事件委派在容器上不是綁在輸入框自己身上(self):
        """`.blQ` 每次重畫都是新節點，綁在它身上的 listener 會隨重畫累積。"""
        self.assertNotIn(".blQ\").addEventListener", JS)
        self.assertIn('box.addEventListener("input"', JS,
                      "輸入事件要委派在只建立一次的容器上")

    def test_搜尋結果有被畫出來(self):
        """定義了 renderBlastHits 卻沒人叫它，搜尋框打字就完全沒反應。"""
        self.assertIn("function renderBlastHits(", JS)
        self.assertGreaterEqual(
            len(re.findall(r"\brenderBlastHits\(", JS)), 3,
            "renderBlastHits 要在重畫與輸入事件兩邊都被呼叫")


class CacheIsVisible(unittest.TestCase):
    """**快取回來的數字跟剛算出來的數字，在畫面上長得一模一樣。**

    波及範圍那一格算一次要三秒，而畫面每 2 秒問一次，所以絕大多數時候
    看到的是快取。不標的話，使用者會以為畫面上的依賴圖反映的是此刻的
    原始碼 —— 那正是這個專案整份文件在防的那一類：
    讓人以為系統知道一件它其實不知道的事。
    """

    def test_快取要標在畫面上(self):
        self.assertIn("b.cached", JS,
                      "沒有讀 cached 旗標，畫面無從分辨數字是不是剛算的")
        self.assertIn("blStale", JS, "沒有把快取狀態畫出來")
        self.assertIn(".blStale", CSS, "畫出來了但沒有樣式")

    def test_快取標示不做成警告色(self):
        """它不是錯誤，是一個要看得到的事實。紅的會讓人以為有東西壞了。"""
        m = re.search(r"\.blast \.hd \.blStale\{[^}]*\}", CSS, re.S)
        self.assertIsNotNone(m, "找不到 .blStale 的樣式")
        self.assertNotIn("--red", m.group(0))


class BlastGraphHasBothHalves(unittest.TestCase):
    """.py 走 ast，.js 走正則。兩半邊的可靠度不一樣。

    2026-09-16 接上 JS 半邊之前，這張圖只有 .py，所以 `src/cost.js`
    （算這張圖的那份演算法本身）搜尋不到也點不開。接上之後如果不標明
    兩邊解析方法不同，畫面看起來就像整張圖是同一種品質。
    """

    def test_兩半邊的組成要看得到(self):
        for f in ("b.py_files", "b.js_files", "b.py_edges", "b.js_edges"):
            self.assertIn(f, JS, f"{f} 沒有畫出來，兩半邊的組成看不到")

    def test_解析方法的差異要講明(self):
        self.assertIn("parser_why", JS,
                      "沒有把「兩半邊解析方法不同」這句話畫出來")

    def test_讀不到的js檔不准靜靜消失(self):
        """讀不到的檔它的邊不在圖裡，而那不是「它沒有依賴」。"""
        self.assertIn("js_unreadable", JS)


class BlindSpotsAreVisible(unittest.TestCase):
    """**`is_lower_bound` 先前只是畫面上一句話，沒有數字。**

    「這個數字永遠是下界」讀起來像一句免責聲明：它不告訴任何人
    下界差多少。而兩份解析器其實都算得出「我看到了但解不出來」
    的筆數 —— JS 那半邊的 `dynamic_opaque` 從第一天就在算，
    Python 這半邊 2026-09-16 補上。

    這一組釘的是：那兩個數字真的畫在畫面上，而且沒有資料的時候
    不准印成 0。
    """

    def test_兩半邊的盲點數字都要畫出來(self):
        for f in ("py_dynamic_opaque", "js_dynamic_opaque"):
            self.assertIn(f, JS, f"{f} 沒有畫出來，這張圖的盲點看不到")

    def test_沒有資料時不准印成0(self):
        """跟 `live_conflicts` 的 0 同一條誠實條款。

        JS 半邊沒算成的時候 `js_dynamic_opaque` 是 None，
        而 `${undefined}` 或 `|| 0` 都會在畫面上變成一個數字。
        """
        m = re.search(r"js_dynamic_opaque\s*==\s*null", JS)
        self.assertIsNotNone(
            m, "沒有分辨 None 與 0，畫面會把「沒有資料」印成一個數字")
        self.assertNotIn("js_dynamic_opaque || 0", JS,
                         "`|| 0` 會把沒有資料變成沒有盲點")

    def test_盲點的位置也要畫出來不只是數量(self):
        """一個總數是免責聲明，位置才查得下去。

        差別跟「這份報告可能有錯」與「第 190 行這一句是錯的」一樣大。
        """
        for f in ("py_dynamic_where", "js_dynamic_where"):
            self.assertIn(f, JS, f"{f} 沒有畫出來，只看得到數量看不到位置")

    def test_位置沒有資料時不准當成沒有盲點(self):
        """`js_dynamic_where` 是 None 代表 JS 半邊沒算成。

        直接 for 一個 null 會炸，而 `|| []` 會安靜地變成
        「那半邊沒有盲點」—— 後者比炸掉糟，因為它不會有錯誤訊息。
        """
        self.assertIsNotNone(
            re.search(r"js_dynamic_where\s*!=\s*null", JS),
            "沒有分辨 None 與空清單，畫面會把「沒有資料」印成「沒有盲點」")
        self.assertNotIn("js_dynamic_where || []", JS,
                         "`|| []` 會把沒有資料變成沒有盲點")

    def test_補回來的延後邊要看得到(self):
        """這個專案用 importlib 打破循環依賴，那些邊先前不在圖上。
        補回來之後要講出來，不然數字自己變大沒有人知道為什麼。"""
        self.assertIn("py_deferred_edges", JS)


class StuckKindOnScreen(unittest.TestCase):
    """做完沒收尾不准被畫成「派不動」加警示色。

    2026-09-16 19:0x 加。在這之前畫面上寫著
    「派不動　7 個步驟都不在可動狀態」，而那 7 個步驟**全部**是
    VERIFIED_COMPLETE。一句假話配一個琥珀色，讀的人會去找哪裡壞了，
    而實情是沒有壞，是有一件事在等她按收尾。

    這一組守的是**畫面有沒有分辨 kind**，不是文案長怎樣。
    """

    def test_畫面要看得懂ALL_VERIFIED(self):
        self.assertIn("ALL_VERIFIED", JS,
                      "畫面沒有分辨 kind，做完跟卡住就會印成同一句")

    def test_做完那一行不准用stuck的警示樣式(self):
        m = re.search(r'ALL_VERIFIED[^\n]*\n\s*\?\s*`<p class="nx ([a-z]+)"',
                      JS)
        self.assertIsNotNone(m, "找不到 ALL_VERIFIED 那一支的樣式類別")
        self.assertNotEqual(m.group(1), "stuck",
                            "做完等收尾不是警示，不該跟卡住共用琥珀色")

    def test_那個樣式類別在css裡真的有定義(self):
        """2026-09-14 踩過：JS 用一個 CSS 裡不存在的類別，
        結果不是報錯，是那段文字變成沒有顏色 —— 看起來正常。"""
        m = re.search(r'ALL_VERIFIED[^\n]*\n\s*\?\s*`<p class="nx ([a-z]+)"',
                      JS)
        self.assertIsNotNone(m)
        self.assertIn(f".nx.{m.group(1)}{{", CSS.replace(" ", ""),
                      "JS 用了一個 CSS 沒定義的類別，那段字會變成沒有顏色")


class SheetRenderersAreActuallyCalled(unittest.TestCase):
    """抽屜與面板裡那幾支渲染函式，有沒有人真的叫它。

    2026-09-17 實測：整行刪掉 `renderNotes(s);`、`renderPicker();`、
    `$("pickQuery").addEventListener("input", renderPicker);`、
    `await renderTakeoverGate(lane);` 這四行的任何一行，
    `python3 -m pytest tests/ -q` 1137 條全部綠。一條都沒有人守。

    這四支跟上一組（`ViewRenderersAreActuallyCalled`）守的那七支不一樣：
    那七支掛在 `view === "..."` 的分頁分派上，這四支是各自頁面內部的
    呼叫，區間長得不一樣，所以上一組的抓法碰不到它們。

    `test_js_symbols.py` 也守不到，它守的是反方向（被呼叫但沒定義）。
    刪掉呼叫之後函式還在，那條不會紅。

    四個症狀都是「畫面看起來正常，只是少了東西」：

      renderNotes       換一輪之後粉紅點清單還停在上一輪，而且上一次
                        沒送出的草稿也還在輸入框裡。看到的是 A 輪的
                        注記，按下去寫進的是 B 輪（`saveNote` 用的是
                        已經更新過的 `nodeN`）
      renderPicker      側邊那份 session 清單永遠停在「讀取中」
      pickQuery 那條     搜尋框打字完全沒反應，清單不跟著過濾
      renderTakeoverGate 接管閘門整塊不出現。那一塊寫的是「沒考過
                        就是唯讀」，少了它，畫面上跟「這裡沒有限制」
                        長得一模一樣，方向是看起來比實際好
    """

    def test_打開某一輪時有叫renderNotes(self):
        self.assertIn("function renderNotes(s)", JS)
        m = re.search(r"\nfunction openNode\(s\) \{(.*?)\n\}\n", JS, re.S)
        self.assertIsNotNone(m, "找不到 openNode 的函式本體")
        self.assertIn("renderNotes(s)", m.group(1),
                      "openNode 沒有叫 renderNotes，換一輪之後粉紅點清單"
                      "還停在上一輪，寫下去會寫到錯的那一輪")

    def test_renderNotes每次都把上一輪的草稿清掉(self):
        """只重畫清單不夠。

        `noteText` 沒清掉的話，上一輪打到一半沒送出的字會留在
        輸入框裡，而抽屜的標題已經換成新的那一輪。這一條跟上一條
        是同一個症狀鏈的兩半，分開釘是因為它們會各自被改掉。
        """
        m = re.search(r"\nfunction renderNotes\(s\) \{(.*?)\n\}\n", JS, re.S)
        self.assertIsNotNone(m, "找不到 renderNotes 的函式本體")
        body = m.group(1)
        self.assertIn('$("noteText").value = ""', body,
                      "renderNotes 沒有清掉輸入框，上一輪沒送出的草稿"
                      "會留到下一輪")
        self.assertIn("out.textContent", body,
                      "renderNotes 沒有清掉上一次的結果字樣，"
                      "下一次打開還會看到「寫下了」")

    def test_打開側邊清單時有叫renderPicker(self):
        self.assertIn("function renderPicker(", JS)
        m = re.search(r"\nasync function openPicker\(\) \{(.*?)\n\}\n",
                      JS, re.S)
        self.assertIsNotNone(m, "找不到 openPicker 的函式本體")
        self.assertIn("renderPicker()", m.group(1),
                      "openPicker 沒有叫 renderPicker，那份清單會永遠"
                      "停在「讀取中」")
        # 上面那句症狀成立的前提：openPicker 自己先寫了「讀取中」。
        # 哪天這句話改掉，錯誤訊息就會指錯方向。
        self.assertIn("讀取中", m.group(1),
                      "openPicker 不再寫「讀取中」了，上面那條的錯誤"
                      "訊息要跟著改")

    def test_搜尋框打字有接上renderPicker(self):
        self.assertRegex(
            JS, r'\$\("pickQuery"\)\.addEventListener\("input", renderPicker\)',
            "搜尋框沒有接上 renderPicker，打字完全沒反應，"
            "清單不會跟著過濾")

    def test_規格那一頁有叫renderTakeoverGate(self):
        self.assertIn("async function renderTakeoverGate(", JS)
        m = re.search(r"\nasync function renderSpec\(\) \{(.*?)\n\}\n",
                      JS, re.S)
        self.assertIsNotNone(m, "找不到 renderSpec 的函式本體")
        self.assertIn("renderTakeoverGate(lane)", m.group(1),
                      "renderSpec 沒有叫 renderTakeoverGate，接管閘門"
                      "整塊不會出現，畫面上跟「這裡沒有限制」一樣")

    def test_blast搜尋結果兩條路徑分開釘住(self):
        """既有那條數的是全檔出現三次。

        三次是「定義一次、重畫一次、輸入事件一次」，拿掉其中一條
        會變兩次，所以那條會紅，這一點跟 `renderIdentity` 那組當初
        的弱點不一樣。要補的是**它紅了之後講不出是哪一條壞掉**：
        兩條路徑的症狀差很多，一條是重畫之後結果整塊消失，
        另一條是打字沒反應。
        """
        mi = re.search(r'box\.addEventListener\("input", \(e\) => \{'
                       r"(.*?)\n    \}\);", JS, re.S)
        self.assertIsNotNone(mi, "找不到 blast 那一格的輸入事件委派")
        self.assertIn("renderBlastHits(box)", mi.group(1),
                      "輸入事件裡沒有叫 renderBlastHits，"
                      "搜尋框打字沒反應")
        mr = re.search(r'const inp = box\.querySelector\("\.blQ"\);'
                       r"(.*?)\n\}", JS, re.S)
        self.assertIsNotNone(mr, "找不到 renderBlast 重畫的尾段")
        self.assertIn("renderBlastHits(box)", mr.group(1),
                      "重畫那一條沒有叫 renderBlastHits，"
                      "每次重畫之後搜尋結果整塊消失，"
                      "而輸入框裡的字還在")

class NoNetworkFonts(unittest.TestCase):
    """離線是這個 app 的常態。
    去網路抓字體的那一刻，抓不到就整個介面的質感垮掉。"""

    def test_no_remote_stylesheet_or_font(self):
        self.assertNotIn("fonts.googleapis.com", HTML)
        self.assertNotIn("http://", HTML.replace("http://127.0.0.1", ""))
        self.assertNotIn("@import", CSS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
