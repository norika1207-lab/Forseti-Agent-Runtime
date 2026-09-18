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
#: 【2026-09-18 砍到剩三個】原本七個。`.subs`、`.adviceBox`、
#: `.vitals`、`.cards` 連同它們的畫面一起退場,剩三個。
#: 清單縮小不代表這條檢查變弱 —— 下面那條
#: `test_the_passthrough_list_covers_every_header_child`
#: 盯著它,漏掉 header 底下任何一個子元素都會紅。
HEADER_KIDS_NEEDING_PASSTHROUGH = (".bar{", ".ctx{", ".panel{")
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
        # 【2026-09-18】`.subs`(那排 Activity 數字)跟 `.adviceBox`
        # (建議列)連同它們的畫面一起退場,剩兩個。
        for sel in (".bar{", ".ctx{"):
            block = CSS.split(sel, 1)[1].split("}", 1)[0] if sel in CSS else ""
            self.assertIn("pointer-events:none", block,
                          f"{sel} 佔滿整條寬度，不能收走滑鼠事件")

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

    【2026-09-18 砍到剩三個】這一組原本守十三支:`.dims` 那個開關
    底下的九格(Dims / HealthCurve / Blast / Gate / Pollution / Sot /
    Identity / Workflow / Probe),加上主輪詢那四支(Subs / Vitals /
    Cards / Rescue)。九格連同開關整塊退場,主輪詢剩兩支。

    **守的東西一個字都沒變**:接了沒有人叫,以及程式碼裡多了一個而
    這份清單不知道。只是對象從十三支變成兩支 ——
    清單縮小不等於這條檢查變弱,它照樣會在有人偷加一支的時候紅。
    """

    #: 輪詢那一段該叫的。**這份清單是寫死的，不從程式碼推導。**
    #: 從程式碼推導的話，刪掉一行的同時清單也跟著縮小，
    #: 那條檢查會永遠綠。
    MAIN = ("setContext", "renderRescue")

    #: 同一段裡分派給分頁的那兩支,由 `ViewRenderersAreActuallyCalled`
    #: 釘。這裡只把它們排除,不重複守同一件事。
    DISPATCHED = ("renderTree", "renderList")

    def _block(self, pattern, what):
        m = re.search(pattern, JS, re.S)
        self.assertIsNotNone(m, f"找不到{what}，這條檢查等於沒跑")
        return m.group(1)

    def _main(self):
        return self._block(
            r'const raw = await invoke\("strands"(.*?)\n  \} catch \(e\) \{',
            "輪詢那一段")

    def test_每一個渲染函式都真的有定義(self):
        for name in self.MAIN:
            self.assertIn(f"function {name}(", JS, f"{name} 沒有定義")

    def test_輪詢那一段該叫的都有人叫(self):
        main = self._main()
        for name in self.MAIN:
            self.assertIn(f"{name}(d)", main,
                          f"輪詢那一段沒有叫 {name}，那一塊不會更新")

    def test_輪詢那一段沒有清單以外的(self):
        """新增一支卻忘了加進清單，這一條會紅。

        上面那條守的是「清單裡的有沒有被叫」，守不住「程式碼裡多了
        一支而清單不知道」—— 那一支就回到沒有任何接線斷言的狀態。
        """
        found = set(re.findall(r"\b(render[A-Za-z]+|setContext)\(",
                               self._main()))
        self.assertEqual(found, set(self.MAIN) | set(self.DISPATCHED),
                         "輪詢那一段叫到的東西跟 MAIN 對不起來")

    def test_這一組的區間抓法自己要抓得到問題(self):
        """區間抓不到，上面那幾條會安靜地跳過。

        `_block` 抓不到就 assert 失敗，這一條確認那個失敗真的會發生，
        不是靠 `re.search` 回 None 之後默默往下走。
        """
        self.assertTrue(self._main().strip(), "輪詢那一段抓出來是空的")


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

    #: 分頁各自的渲染函式。**這份清單是寫死的，不從程式碼推導。**
    #: 從程式碼推導的話，刪掉一行的同時清單也跟著縮小，
    #: 那條檢查會永遠綠（`RenderersAreActuallyCalled` 付過這個代價）。
    #:
    #: `renderList` 是 else 那一支，對應 `index.html` 的
    #: `data-view="list"`（需要注意）。
    #:
    #: 【2026-09-18】七支砍到兩支。在做什麼 / 讀文件 / 這台機器 /
    #: 功能 / 自我審計那五頁退場,連同它們那五個模組層快取
    #: (`workCache` 那一組)—— 所以先前那兩條守快取有沒有被清的檢查
    #: 一起拿掉,現在沒有任何一頁有快取,留著它們等於守一個空清單。
    VIEW_RENDERERS = ("renderTree", "renderList")

    #: `index.html` 底下那排按鈕的 `data-view`。用來確認分派鏈
    #: 沒有漏掉任何一個按鈕得到的頁 —— 漏掉的那一頁按下去會掉進
    #: else，畫出來的是別頁的內容，而且不會有錯誤訊息。
    VIEW_NAMES = ("tree",)

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
            r'\n    lastSnap = d;\n(?:[^\n]*\n)*?'
            r'((?:    (?:if|else)[^\n]*\n)+)'
            r'    if \(follow && view === "tree"\)', "輪詢分派那一段")

    def _sync_dispatch(self):
        return self._block(r'function syncView\(\) \{(.*?)\n\}',
                           "切分頁那一段")

    def test_每一頁的渲染函式都真的有定義(self):
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

    【2026-09-18 砍到剩三個】`renderTakeoverGate` 跟波及範圍那個
    搜尋框連同它們所在的頁一起退場,所以那兩條檢查拿掉了 ——
    守一個不存在的東西不會紅,只會讓這個檔看起來守得比實際多。
    剩下 `renderNotes`、`renderPicker`、`pickQuery` 三條,
    它們守的東西一個字都沒變。
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


class NoNetworkFonts(unittest.TestCase):
    """離線是這個 app 的常態。
    去網路抓字體的那一刻，抓不到就整個介面的質感垮掉。"""

    def test_no_remote_stylesheet_or_font(self):
        self.assertNotIn("fonts.googleapis.com", HTML)
        self.assertNotIn("http://", HTML.replace("http://127.0.0.1", ""))
        self.assertNotIn("@import", CSS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
