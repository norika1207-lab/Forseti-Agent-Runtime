#!/usr/bin/env python3
"""畫出來的東西對不對，不是有沒有人叫它。

## 這支補的是哪一個洞

`tests/test_js_symbols.py` 守「被呼叫但沒定義」。
`tests/test_ui_contract.py` 守「定義了但沒人呼叫」。
兩邊守的都是接線，而接線對了之後還有一整類症狀沒有人守：

**叫了，跑完了，畫面上那一格是空的、是佔位字、或是數字不是資料裡那個。**

2026-09-16 整天補的十一支渲染函式接線斷言全部是靜態比對，
那一輪自己寫下來的結論是「守不到叫了之後畫出來的東西對不對」。
這支就是那一句的實作。

做法：用 `tools/ui-harness.py` 已經有的 `build()` 產出一份可跑的頁面，
丟進 headless Chrome，把**跑完 JS 之後的 DOM** 撈回來，
拿 DOM 裡的字跟 fixture 裡的值對。

## 繼承來的盲點，寫在最前面因為它咬過一次

一，**這支看不到「前端連不連得上後端」。** harness 會 stub 掉
`window.__TAURI__`，那是 `ui-harness.py` 自己寫在檔頭的盲點，
這支原封不動繼承。補那一層的是 `test_ui_contract.py` 的 `TauriWiring`。

二，**這支看得到的是「載入完」加「按得到的那幾下」。** `--dump-dom`
本身是載入完成之後照一張，沒有點擊。2026-09-17 補上 `clicks=`：
往那份暫存頁面尾巴加一段 `document.getElementById(id).click()`，
Chrome 照相之前先按下去，於是展開之後才畫的那四格
（Blast、Identity、Workflow、Probe）也照得到。

**為什麼這樣算是使用者真的走的那條路。** 按的是真的那個元素，
事件走的是 `app.js:3057` 那個掛在 `#vWhy` 上的 listener，
接著由它自己去呼叫九個 render —— **這支沒有直接呼叫任何一個
render 函式**。直接呼叫的話驗到的是函式，不是那一下按了會發生什麼。

**它跟真人按下去差在哪，寫出來免得被讀成「按鍵全驗過了」：**
`isTrusted` 是 false（`app.js` 一處都沒有讀它，實測 grep 0 筆，
所以這一刻沒有差別，但哪天有人讀了就有）；沒有 hover、focus-visible
這些只有真的指標裝置才會有的狀態；而且只按得到「按一下就展開」
這種一步的東西，要先輸入再按的流程不在射程內。

2026-09-17 再補分頁那一條路：`clicks` 改收 CSS 選擇器（那七顆
`.vw` 一個 id 都沒有），一次按兩下 —— 先 `#burgerBtn` 再
`.vw[data-view=…]`，因為七顆全部住在 `#picker` 裡而它帶著 `hidden`。
六個分頁各開一次瀏覽器，驗表頭數字與列數（`TABS`）。
`tree` 不在裡面，它是預設那一頁，`check_tree_drew_nodes` 已經驗過。

**漢堡那一下對結果沒有影響，這是實測不是推論。** `HTMLElement.click()`
對 `hidden` 底下的元素照樣派送事件 —— 不按漢堡直接按 `.vw` 照樣全綠，
把 `openPicker` 換成空函式（`app.js:2946`）也照樣全綠。所以分頁那一組
**證明不了漢堡是通的**，而漢堡是畫面上唯一的入口。補那個洞的是
`check_burger_opens_picker`，它單獨按一次漢堡，問的是不同的問題。

分頁裡面第二層的東西（`.fi` 展開、`.wk` 上那三顆動作鈕）
仍然不在射程內：那要按兩層以上。

二之二，**這支驗得到「那一格畫出來了而且數字對」，驗不到
「是那一下按的造成的」。** 2026-09-17 實測：那四格有兩條路會畫它們 ——
`#vWhy` 的 listener（`app.js:3057`）與輪詢迴圈裡 `.dims.open` 那個分支
（`app.js:3010`）。把 listener 裡的 `renderBlast` 拿掉，這支照樣全綠，
因為按完之後那一格是輪詢畫的；只把輪詢那一行拿掉也全綠；
**兩邊都拿掉才紅**。所以這一組的斷言只到「按完之後畫面上是對的」，
到不了「是誰畫的」。要分得開得量時間，而 `--dump-dom` 只照一張。

三，**這支看的是 DOM，不是像素。** CSS 把一塊蓋掉、推出畫面、
或者 `color` 跟背景同色，DOM 裡照樣有字。版面正不正確不在這支的射程內。

三件都是真的限制，不是待補。寫下來是因為一個「畫面全驗過了」的
說法，比沒有驗過更貴 —— 2026-09-14 就是這樣騙到自己的。

## 回傳

    0  都對
    1  有對不上的，症狀印在 stdout
    2  跑不起來（沒有 Chrome、harness 產不出頁面）

**2 不是通過。** 它跟 0 分開，是因為「驗不了」被當成「驗過了」
正是這個專案在防的那一類事。

用法：

    python3 tools/ui-render-check.py
    python3 tools/ui-render-check.py --session <path>
    python3 tools/ui-render-check.py --keep      # 留下暫存目錄自己看

零依賴，標準庫加一個 Chrome 執行檔（ADR-009）。
"""

from __future__ import annotations

import html as _html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Chrome 在哪。找不到就回 2，不猜、不裝成通過。
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]

# Chrome 自己的雜訊。這幾類跟頁面無關，是 headless 在 macOS 上
# 抓不到顯示器與 GPU 造成的，每一次都會出現。
# 白名單用「出處檔名」比對，不是用字面訊息 ——
# 訊息會隨 Chrome 版本改寫，出處不會。
CHROME_NOISE = (
    "cv_display_link_mac.mm",
    "shared_image_manager.cc",
    "gpu_channel_manager.cc",
    "sandbox_mac.mm",
    "device_event_log_impl.cc",
    "bluetooth_adapter_mac.mm",
)


class CannotRun(Exception):
    """跑不起來。跟「沒通過」是兩件事，所以是不同的例外。"""


@dataclass
class Finding:
    """一條對不上。

    `symptom` 寫的是使用者會看到什麼，不是測試的抓法。
    理由跟 5c 那一輪一樣：一個講抓法的錯誤訊息，
    看的人還要自己翻譯回症狀，而翻譯的那一步常常翻錯。
    """

    where: str
    symptom: str
    expected: str
    actual: str

    def __str__(self) -> str:
        return (f"  {self.where}\n"
                f"    症狀　{self.symptom}\n"
                f"    資料裡是　{self.expected}\n"
                f"    畫面上是　{self.actual}")


@dataclass
class Render:
    dom: str
    console: list[str]
    fixture: dict
    outdir: Path


def find_chrome() -> str:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    found = shutil.which("chromium") or shutil.which("google-chrome")
    if found:
        return found
    raise CannotRun(
        "找不到 Chrome。試過：" + "、".join(CHROME_CANDIDATES) +
        "，以及 PATH 上的 chromium / google-chrome")


def _load_harness():
    """`ui-harness.py` 檔名有連字號，import 不進來，所以用檔案路徑載。

    **不重寫一份 build()。** 這個專案在 2026-09-16 一天之內
    重複實作過三次同一個東西，重寫一份會多出第二個「fixture 該長怎樣」
    的定義，而兩份定義一定會分岔。
    """
    p = REPO / "tools" / "ui-harness.py"
    if not p.exists():
        raise CannotRun(f"harness 不在：{p}")
    sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))
    spec = importlib.util.spec_from_file_location("_forseti_ui_harness", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# 展開那一格要按的是哪一個。
#
# **一個選擇器，不是一串。** `#vWhy` 那個 listener（`app.js:3057`）
# 自己會去呼叫九個 render，所以按一下就夠。列成常數是為了讓
# 「這支按了什麼」可以被讀到，不用去翻程式碼。
# （分頁那條路要兩下，見 `tab_clicks`。）
EXPANDED_CLICKS = ("#vWhy",)

# 按下去之前要等多久（毫秒，虛擬時間）。
#
# 太早按，`lastSnap` 還是 null，九個 render 收到的是 `{}`，
# 畫出來的是「沒有資料」那一版 —— 而那一版跟真的沒資料長得一模一樣。
# 這個數字要小於 `--virtual-time-budget`，不然照相的時候還沒按。
CLICK_AFTER_MS = 2500

# 兩下之間隔多久（毫秒，虛擬時間）。
#
# 分頁那條路是「先開漢堡、再按分頁」，第一下會讓 `#picker`
# 的 `hidden` 變 false，第二下才按得到那顆按鈕。間隔為 0 的話
# 兩下在同一個 task 裡跑完，等於沒有給中間任何非同步的機會 ——
# 而 `renderWork` 這幾支是 async，它們要等 invoke 回來。
# 這個數字加上 `CLICK_AFTER_MS` 仍然要小於 `--virtual-time-budget`。
CLICK_GAP_MS = 400


# 傾印觀察器結果要比最後一下再晚多久（毫秒，虛擬時間）。
#
# 太早倒，`wireActs` 那個 handler 是 async，第一下的同步那一段
# （改文字、加 armed）雖然立刻跑完，但要留餘裕給後面接上來的
# 任何非同步工作 —— 不留的話，一個「第一下其實有發 act」的 bug
# 會因為倒得太早而看起來乾淨。
SPY_DUMP_EXTRA_MS = 600

# 觀察器把結果寫進 DOM 的哪個 id。
SPY_ID = "rcSpy"


def _inject_invoke_spy(page: Path) -> None:
    """記下 app.js 透過 Tauri 發了哪些指令，寫進 DOM 讓 `--dump-dom` 照得到。

    **為什麼要插在 `<script src="app.js">` 之前。** `app.js:6` 是
    `const invoke = window.__TAURI__?.core?.invoke;` —— 它在載入那一刻
    就把函式抓走了。插在 `</body>` 之前（`_inject_clicks` 的位置）
    再去包 `window.__TAURI__.core.invoke`，app.js 手上那份仍然是原版，
    觀察器會一筆都收不到，而那看起來跟「真的一筆都沒發」一模一樣。
    這一句是讀 `app.js:6` 得到的，不是試出來的。

    **包的是 harness 的假 Tauri，不是真的那個。** 所以這支能回答的是
    「app.js 有沒有發出這個指令」，回答不了「後端收到之後做了什麼」。
    那一層仍然是 `ui-harness.py` 檔頭寫的同一個盲點。

    **不改 app.js 的路徑。** 包裝版把參數原封不動轉給原函式，
    回的是同一個 Promise。app.js 看到的行為跟沒有觀察器時一樣。

    裝不上的時候往 console 喊，不安靜跳過 —— 底下那條檢查遇到
    「記錄是空的」會報錯而不是放行，理由寫在 `check_act_did_not_invoke`。
    """
    h = page.read_text(encoding="utf-8")
    tag = '<script src="app.js"></script>'
    if tag not in h:
        raise CannotRun(
            "暫存頁面裡找不到 app.js 那個 script 標籤，觀察器插不進去")
    spy = (
        "<script>\n"
        "window.__RC_INVOKES = [];\n"
        "(function(){\n"
        "  var c = window.__TAURI__ && window.__TAURI__.core;\n"
        "  if (!c || typeof c.invoke !== 'function') {\n"
        "    console.error('[render-check] 裝不上 invoke 觀察器："
        "stub 還沒定義');\n"
        "    return;\n"
        "  }\n"
        "  var orig = c.invoke;\n"
        "  c.invoke = function(cmd){\n"
        "    window.__RC_INVOKES.push(String(cmd));\n"
        "    return orig.apply(this, arguments);\n"
        "  };\n"
        "})();\n"
        "</script>\n")
    page.write_text(h.replace(tag, spy + tag, 1), encoding="utf-8")


def _inject_spy_dump(page: Path, at_ms: int) -> None:
    """照相之前，把觀察器收到的指令清單寫成一個隱藏的 div。

    `--dump-dom` 照的是 DOM，讀不到 JS 變數，所以要把結果放進 DOM。
    放 `hidden` 的 div 是因為它不該影響任何一條看畫面的檢查 ——
    而 `strip_fixture` 只拿掉 fixture 那一塊，這一塊留著給人看。
    """
    h = page.read_text(encoding="utf-8")
    js = (
        "<script>\nsetTimeout(function(){\n"
        "  var d = document.createElement('div');\n"
        "  d.id = %s; d.hidden = true;\n"
        "  d.textContent = JSON.stringify(window.__RC_INVOKES || null);\n"
        "  document.body.appendChild(d);\n"
        "}, %d);\n</script>\n" % (json.dumps(SPY_ID), at_ms))
    if "</body>" in h:
        h = h.replace("</body>", js + "</body>", 1)
    else:
        h = h + js
    page.write_text(h, encoding="utf-8")


def _inject_clicks(page: Path, sels: tuple[str, ...], after_ms: int) -> None:
    """往暫存頁面尾巴加一段，照相之前把那幾個元素依序按下去。

    **改的是暫存目錄裡那一份，不是 `desktop/ui/index.html`，
    也不是 `ui-harness.py`。** 出貨的那份頁面一個字都不動 ——
    一個只有測試路徑才有的 `<script>` 留在正本裡，遲早會有人
    以為那是產品的一部分。

    **按的是元素自己的 `.click()`，不是去呼叫 render 函式。**
    `HTMLElement.click()` 派送的是一個真的、會冒泡的 MouseEvent，
    走的是 `app.js` 自己註冊的那個 listener，接下來發生什麼
    由 app.js 決定，不由這支決定。差別寫在檔頭盲點二。

    收的是 **CSS 選擇器**不是 id（2026-09-17 改）。七個分頁那排
    `.vw` 按鈕一個 id 都沒有（`index.html:113-119` 實測），
    只認 id 的話那一整排永遠按不到。`#vWhy` 這種寫法照樣成立。

    **依序按，不是同時按。** 分頁那條路要先開漢堡再按分頁，
    兩下之間有先後。全部塞進同一個 `setTimeout` 的話順序仍在，
    但中間沒有讓出執行緒 —— 所以這裡每一下自己一個 timer，
    間隔 `CLICK_GAP_MS`，讓上一下引發的非同步工作有機會跑完。
    """
    if not sels:
        return
    h = page.read_text(encoding="utf-8")
    parts = []
    for n, sel in enumerate(sels):
        # 找不到元素要往 console 喊。安靜跳過的話，按鈕改了選擇器之後
        # 這支會照出一張「沒切過去」的 DOM，而底下每一條檢查遇到
        # 找不到的元素都是放行的 —— 那一天整組會全綠。
        # （`check_tab_switched` 是同一件事的第二道。）
        parts.append(
            'setTimeout(function(){\n'
            '  var el = document.querySelector(%s);\n'
            '  if (el) { el.click(); } else { console.error(%s); }\n'
            '}, %d);' % (json.dumps(sel),
                         # 訊息也要 json 編碼。選擇器本身含雙引號
                         # （`.vw[data-view="work"]`），直接拼進 JS
                         # 字串會把字串提前關掉 —— 2026-09-17 實測，
                         # 症狀是 "Uncaught SyntaxError: missing )"
                         # 而且那一下完全沒按到，畫面停在預設分頁。
                         json.dumps("[render-check] 找不到要按的元素 " + sel),
                         after_ms + n * CLICK_GAP_MS))
    inject = "<script>\n" + "\n".join(parts) + "\n</script>\n"
    if "</body>" in h:
        h = h.replace("</body>", inject + "</body>", 1)
    else:
        h = h + inject
    page.write_text(h, encoding="utf-8")


def render(session: str = "", fake: bool = False,
           outdir: Path | None = None, timeout: int = 120,
           clicks: tuple[str, ...] = (), spy: bool = False,
           budget_ms: int = 8000, spy_at_ms: int | None = None) -> Render:
    """產頁面、丟進 Chrome、把跑完 JS 的 DOM 撈回來。

    `clicks` 給的是 CSS 選擇器，照相之前依序按下去。
    空的就是原本那條路。

    `spy` 打開的話，額外記下 app.js 透過 Tauri 發了哪些指令，
    結果寫進 DOM 的 `#rcSpy`。預設關著 —— 它多插兩段 script，
    而多數檢查不需要它，能少一層就少一層。

    `budget_ms` 是照相的時刻（虛擬時間）。**它是一個斷言的一部分，
    不是一個效能旋鈕** —— 動作鈕那一組要的正是「按下之後跨過
    一次輪詢再照」，理由寫在 `ACT_BUDGET_MS`。

    `spy_at_ms` 是觀察器傾印的時刻。不給的話跟著最後一下走
    （那是動作鈕那一組要的：按完就看）。**輪詢那一組要的相反** ——
    它要的是「按完之後再坐過好幾輪」，看那幾輪各自發了什麼，
    所以那一組自己指定一個晚得多的時刻。傾印早於照相是必要的，
    早多少由呼叫的人決定，因為那個差距本身就是被觀察的區間。
    """
    chrome = find_chrome()
    harness = _load_harness()

    out = outdir or Path(tempfile.mkdtemp(prefix="forseti-render-"))
    try:
        harness.build(out, fake, session)
    except Exception as e:
        raise CannotRun(f"harness 產不出頁面：{type(e).__name__}: {e}") from e

    page = out / "index.html"
    if not page.exists():
        raise CannotRun(f"harness 沒有寫出 index.html：{out}")
    if spy:
        # 順序有意義：觀察器要在 app.js 之前，傾印要在最後一下之後。
        _inject_invoke_spy(page)
    _inject_clicks(page, clicks, CLICK_AFTER_MS)
    if spy:
        _inject_spy_dump(
            page,
            spy_at_ms if spy_at_ms is not None else
            CLICK_AFTER_MS + max(0, len(clicks) - 1) * CLICK_GAP_MS
            + SPY_DUMP_EXTRA_MS)

    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
        # fixture 內嵌在 HTML 裡，但 app.js / app.css 是同目錄的檔案。
        "--allow-file-access-from-files",
        # console 走 stderr。沒有這兩個旗標，JS 的 Uncaught 完全看不到，
        # 而「整塊不出現」最常見的原因正是一個沒人接的例外。
        "--enable-logging=stderr", "--log-level=0",
        # 讓計時器與 fetch 的微任務跑完再照相。app.js 的渲染是在
        # DOMContentLoaded 之後才動，不等的話照到的是還沒畫的那一刻。
        "--virtual-time-budget=%d" % budget_ms,
        "--dump-dom", page.resolve().as_uri(),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise CannotRun(f"Chrome 超過 {timeout} 秒沒有回來") from e
    if r.returncode != 0:
        raise CannotRun(f"Chrome 回 {r.returncode}：{r.stderr[-600:]}")
    if not r.stdout.strip():
        raise CannotRun("Chrome 回了空的 DOM")

    console = [ln for ln in r.stderr.splitlines()
               if "CONSOLE" in ln or "Uncaught" in ln]
    fixture = json.loads((out / "fixture.json").read_text(encoding="utf-8"))
    return Render(dom=r.stdout, console=console, fixture=fixture, outdir=out)


# ---------------------------------------------------------------- DOM 取值

def strip_fixture(dom: str) -> str:
    """把內嵌的 fixture JSON 拿掉。

    不拿掉的話，任何「畫面上有沒有這個數字」的檢查都會命中
    fixture 自己 —— 那是資料，不是畫出來的東西。
    一條永遠綠的斷言比沒有斷言糟。
    """
    return re.sub(r'<script type="application/json" id="fx">.*?</script>',
                  "", dom, flags=re.S)


def _tag_text(dom: str, eid: str) -> str | None:
    """抓 id=eid 那個元素的文字內容。

    自己配對標籤而不是用 regex 抓 `>(.*?)<`，因為那些格子裡
    本來就有巢狀的 `<b>` 與 `<span>`，抓到第一個 `<` 就停會只拿到開頭。
    """
    m = re.search(r'<(\w+)([^>]*\bid="%s"[^>]*)>' % re.escape(eid), dom)
    if not m:
        return None
    tag = m.group(1)
    i = m.end()
    depth = 1
    pat = re.compile(r'</?%s\b[^>]*>' % re.escape(tag))
    while depth:
        n = pat.search(dom, i)
        if not n:
            return None
        depth += -1 if n.group(0).startswith("</") else 1
        if depth == 0:
            inner = dom[m.end():n.start()]
            break
        i = n.end()
    txt = re.sub(r"<[^>]+>", "", inner)
    return _html.unescape(txt).replace("　", " ").strip()


def _nums(s: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", s or "")


def _box_html(dom: str, cls: str) -> str | None:
    """抓 `<div class="cls">` 那一整塊的內容。

    自己配對 `<div>` 而不是用非貪婪 regex 抓到第一個 `</div>`，
    因為這幾格裡面本來就有巢狀的 div（`.blRow`、`.idnRow`…），
    抓到第一個就停只會拿到開頭那一行。
    跟 `_tag_text` 同一個理由，只是這裡是用 class 找不是用 id。
    """
    m = re.search(r'<div[^>]*\bclass="[^"]*\b%s\b[^"]*"[^>]*>'
                  % re.escape(cls), dom)
    if not m:
        return None
    i = m.end()
    depth = 1
    pat = re.compile(r"</?div\b[^>]*>")
    while depth:
        n = pat.search(dom, i)
        if not n:
            return None
        depth += -1 if n.group(0).startswith("</div") else 1
        if depth == 0:
            return dom[m.end():n.start()]
        i = n.end()
    return None


def _count_class(frag: str, cls: str) -> int:
    """數這一塊裡面有幾個帶這個 class 的元素。

    比對的是 class 屬性裡的完整單字，不是字串包含 ——
    `blRow` 用字串比會連 `blRowHead` 這種一起數進去。
    """
    return len(re.findall(r'\bclass="[^"]*\b%s\b[^"]*"' % re.escape(cls),
                          frag or ""))


def _id_html(dom: str, eid: str) -> str | None:
    """抓 `id=eid` 那個 div 裡面那一整塊。

    跟 `_box_html` 同一套配對邏輯，只是用 id 找不是用 class。
    七個分頁全部畫進 `#lane`（`app.js` 六支 render 的第一行都是
    `const lane = $("lane")`，實測），所以分頁那一組的每一條
    都先取這一塊再往裡面找 —— **不在整份 DOM 上找**。

    理由是實測出來的：`#picker` 裡那份 session 清單有 81 個
    `.pk*`，`.ct` 這種 class 在 picker、machine、list 三處都有。
    不縮範圍的話，數出來的是整頁的量，而那個數字跟分頁畫了什麼無關，
    卻會剛好在某些分頁上對上 —— 一條有時候對的斷言比沒有斷言糟。
    """
    m = re.search(r'<div[^>]*\bid="%s"[^>]*>' % re.escape(eid), dom)
    if not m:
        return None
    i = m.end()
    depth = 1
    pat = re.compile(r"</?div\b[^>]*>")
    while depth:
        n = pat.search(dom, i)
        if not n:
            return None
        depth += -1 if n.group(0).startswith("</div") else 1
        if depth == 0:
            return dom[m.end():n.start()]
        i = n.end()
    return None


def _cls_text(frag: str, cls: str) -> str | None:
    """抓這一塊裡第一個帶這個 class 的元素的文字。

    自己配對標籤，理由跟 `_tag_text` 一樣：這些格子裡有巢狀的
    `<b>` 與 `<span>`，用 `>(.*?)<` 抓到第一個 `<` 就停，
    拿到的是開頭那幾個字 —— 而那幾個字常常剛好包含要驗的數字，
    於是斷言看起來會過。
    """
    m = re.search(r'<(\w+)([^>]*\bclass="[^"]*\b%s\b[^"]*")' % re.escape(cls),
                  frag or "")
    if not m:
        return None
    tag = m.group(1)
    e = (frag or "").find(">", m.end())
    if e < 0:
        return None
    i = e + 1
    depth = 1
    pat = re.compile(r"</?%s\b[^>]*>" % re.escape(tag))
    while depth:
        n = pat.search(frag, i)
        if not n:
            return None
        depth += -1 if n.group(0).startswith("</") else 1
        if depth == 0:
            inner = frag[e + 1:n.start()]
            break
        i = n.end()
    txt = re.sub(r"<[^>]+>", " ", inner)
    return _html.unescape(txt).replace("\u3000", " ").strip()


# 展開那一格底下四塊，各自的：資料在 fixture 的哪個鍵、
# 這一塊在 DOM 的 class、一列是什麼 class、畫面上叫什麼。
#
# 做成一張表而不是四支各寫一遍，是因為這四塊的檢查邏輯
# **完全一樣**：資料說有幾列，畫面上就該有幾列。
# 寫成四份一定會分岔，而分岔的那一份通常是最少被看的那一份。
#
# 【2026-09-17 實測】第四欄一開始把 blast 寫成 `rows`，而它真正的
# 鍵是 `top`。後果不是紅燈，是**那一格被安靜跳過**，整組照樣全綠 ——
# 合成那一組才抓到。所以底下那支遇到「`has` 是 true 但這一鍵不是清單」
# 不再 `continue`，直接報一條。
EXPANDED_BOXES = (
    ("blast", "blast", "blHit", "top", "波及範圍"),
    ("identity", "idn", "idnRow", "rows", "身份跟什麼分得開"),
    ("workflow", "wfl", "wflRow", "resumable", "接哪一步"),
    ("probe", "prb", "prbRow", "rows", "哪一類退化了"),
)


# ---------------------------------------------------------------- 檢查

def check_no_fatal_banner(r: Render) -> list[Finding]:
    """渲染迴圈有沒有整段炸掉。

    **這一條要在 console 那一條之前看，因為 console 看不到它。**
    `app.js:3024` 起那個 `catch` 把整個 `tick()` 包起來，
    例外進了 `fatal()`（`app.js:2962`），於是它變成畫面上的一張卡，
    完全不經過 console。實測過：在 `renderTree` 裡丟一個
    `ReferenceError`，console 一行都沒有。

    少了這一條的話，一次渲染迴圈崩潰只會讓別的檢查報出
    「頁腳數字對不上」這種下游症狀，而真正的原因是整段沒跑完。
    報錯的症狀跟真正的原因差一層，查的人就會往錯的方向走。
    """
    dom = strip_fixture(r.dom)
    if "black-note fatal" not in dom:
        return []
    title = _tag_text(dom, "stat") or ""
    why = _tag_text(dom, "adviceWhy") or ""
    return [Finding(
        where="#lane 的 fatal 卡",
        symptom=("整個渲染迴圈中途丟出例外，被 app.js 的 catch 接走了。"
                 "例外之後的渲染一行都沒跑，畫面上是半張圖"),
        expected="渲染跑完，不出現 fatal 卡",
        actual=f"{title}：{why[:160]}")]


def check_no_console_errors(r: Render) -> list[Finding]:
    """console 上有沒有留東西。

    **射程要講清楚，不然這條綠燈會被讀成「JS 沒問題」。**
    `tick()` 裡的例外走 `catch` 進 `fatal()`，不經過 console，
    所以那一類這一條看不到 —— 那是上面 `check_no_fatal_banner` 的事。
    這一條看得到的是**那個 try 以外**的：模組頂層、事件處理器、
    非同步回呼裡沒人接的例外。實測兩種都抓得到。

    Chrome 的 `INFO:CONSOLE` 不分 log 與 error，所以這裡不假裝分得出來。
    帶 `Uncaught` 的當成壞掉，其餘的當成「不該留在成品裡的雜訊」，
    兩者的症狀分開寫。
    """
    bad = [ln for ln in r.console
           if not any(n in ln for n in CHROME_NOISE)]
    if not bad:
        return []
    def msg(x):
        return x.split("] ", 1)[-1][:160]
    crashed = [x for x in bad if "Uncaught" in x]
    noisy = [x for x in bad if "Uncaught" not in x]
    out = []
    if crashed:
        out.append(Finding(
            where="瀏覽器 console",
            symptom=("渲染迴圈以外有沒人接的例外。它後面同一段的程式不會跑，"
                     "而畫面上只是那一塊沒出現，跟本來就沒東西長得一樣"),
            expected="沒有 Uncaught",
            actual=" / ".join(msg(x) for x in crashed[:3])))
    if noisy:
        out.append(Finding(
            where="瀏覽器 console",
            symptom="成品裡留著 console 輸出。它本身不一定是壞掉，但它會蓋掉真的壞掉那一行",
            expected="console 乾淨",
            actual=" / ".join(msg(x) for x in noisy[:3])))
    return out


def check_no_placeholder_left(r: Render) -> list[Finding]:
    """HTML 裡寫死的佔位字，渲染之後還在不在。

    `index.html` 給了幾個初始值（溫度 `--`、`讀取中`），
    它們的用途是「還沒算好時不要空白」。渲染跑完之後還留著，
    代表那一格根本沒有被寫進去。
    """
    dom = strip_fixture(r.dom)
    out = []
    t = _tag_text(dom, "vTemp")
    if t == "--":
        out.append(Finding(
            where="#vTemp",
            symptom="溫度那一格一直是兩條槓，看起來像系統還在算",
            expected=f"temp.c = {(r.fixture['strands'].get('temp') or {}).get('c')}",
            actual="--"))
    for eid in ("pickList", "adviceText"):
        v = _tag_text(dom, eid)
        if v == "讀取中":
            out.append(Finding(
                where=f"#{eid}",
                symptom="這一格永遠停在「讀取中」，看起來像在載入，其實沒有人去填它",
                expected="渲染之後應該被換掉",
                actual="讀取中"))
    return out


def check_temperature(r: Render) -> list[Finding]:
    """溫度與證據覆蓋率，畫面上那個數字是不是資料裡那個。

    症狀：渲染函式跑了，可是拿到的是別的物件，於是畫出一個
    看起來很合理、但跟資料無關的數字。這一類靜態接線測試碰不到。
    """
    dom = strip_fixture(r.dom)
    temp = (r.fixture["strands"].get("temp") or {})
    out = []
    c = temp.get("c")
    got = _tag_text(dom, "vTemp")
    if c is None:
        if got != "--":
            out.append(Finding(
                where="#vTemp",
                symptom="資料算不出溫度，畫面上卻給了一個數字",
                expected="temp.c 是 null，畫面該顯示 --", actual=str(got)))
    else:
        want = f"{float(c):.1f}"
        if got != want:
            out.append(Finding(
                where="#vTemp", symptom="畫面上的溫度不是資料裡那個溫度",
                expected=want, actual=str(got)))
        cov = temp.get("coverage")
        if cov is not None:
            band = _tag_text(dom, "vBand") or ""
            want_cov = f"證據 {round(float(cov) * 100)}%"
            if want_cov not in band:
                out.append(Finding(
                    where="#vBand",
                    symptom=("證據覆蓋率沒有跟著溫度走。FS-RSK-001 的重點是"
                             "低覆蓋率的高分不能裝作確定，少了這個數字，"
                             "一個沒把握的溫度看起來跟有把握的一樣"),
                    expected=want_cov, actual=band or "（空的）"))
    return out


def check_progress_三軸(r: Render) -> list[Finding]:
    """活動 / 寫入 / 目標三個數字，畫面上是不是資料裡那三個。

    FS-DET-FPR-001 要求這三件永遠分開。分開之後還有第二件事：
    每一個都要是真的那個值。

    **目標那一格今天是綠的，可是它綠得不是因為接對了。**
    `app.js:291` 把「目標 未知」寫死在字串裡，從來沒有讀過
    `progress.goal`。今天 `progress.goal` 剛好永遠是 null，
    所以兩邊看起來一致 —— 那是巧合不是機制。
    這一條留著，是為了在後端哪天算得出目標進度的那一刻變紅。
    """
    dom = strip_fixture(r.dom)
    pr = (r.fixture["strands"].get("progress") or {})
    line = _tag_text(dom, "vProg") or ""
    out = []
    for key, label in (("activity", "活動"), ("task", "寫入")):
        want = pr.get(key)
        if want is None:
            continue
        m = re.search(re.escape(label) + r"\s*(\d+)", line)
        if not m or int(m.group(1)) != int(want):
            out.append(Finding(
                where="#vProg " + label,
                symptom=f"畫面上的「{label}」不是資料裡那個數字",
                expected=str(want),
                actual=(m.group(1) if m else "找不到這一格")))
    goal = pr.get("goal")
    if goal is None:
        if "目標 未知" not in line:
            out.append(Finding(
                where="#vProg 目標",
                symptom=("目標進度算不出來的時候畫面該說未知。填零會被讀成"
                         "「做了但沒進度」，那是另一件事"),
                expected="目標 未知", actual=line or "（空的）"))
    else:
        m = re.search(r"目標\s*(\d+)", line)
        if not m or int(m.group(1)) != int(goal):
            out.append(Finding(
                where="#vProg 目標",
                symptom=("後端算得出目標進度了，畫面還是寫死「未知」。"
                         "`app.js` 的 renderVitals 從來沒有讀過 progress.goal"),
                expected=str(goal),
                actual=(m.group(1) if m else "未知（寫死的）")))
    return out


def check_tree_drew_nodes(r: Render) -> list[Finding]:
    """樹到底有沒有畫出點。

    症狀：軌道那一塊是空的。空的軌道跟「這條 session 很乾淨」
    在畫面上長得一樣，而後者是好消息 —— 方向又是看起來比實際好。
    """
    dom = strip_fixture(r.dom)
    m = re.search(r'<div[^>]*\bid="lane"[^>]*>(.*)', dom, flags=re.S)
    lane = m.group(1) if m else ""
    drew = lane.count('class="st"') + lane.count("class='st'")
    rows = len(r.fixture["strands"].get("rows") or [])
    if rows and drew == 0:
        return [Finding(
            where="#lane",
            symptom="資料裡有輪次，軌道上一個都沒畫出來，看起來像這條線很乾淨",
            expected=f"{rows} 輪", actual="0 個節點")]
    return []


def check_footer_counts(r: Render) -> list[Finding]:
    """頁腳那一行「N 線 · M 點」。

    這一行是整個畫面上唯一一處把總量講出來的地方。
    它錯了的話，畫面上少畫了一半也看不出來。
    """
    dom = strip_fixture(r.dom)
    txt = _tag_text(dom, "stat") or ""
    want_lines = r.fixture["strands"].get("strands")
    want_dots = r.fixture["strands"].get("total_dots")
    out = []
    got = _nums(txt)
    if want_lines is not None:
        m = re.search(r"(\d+)\s*線", txt)
        if not m or int(m.group(1)) != int(want_lines):
            out.append(Finding(
                where="#stat 線數", symptom="頁腳的線數跟資料對不上",
                expected=str(want_lines),
                actual=(m.group(1) if m else txt or "（空的）")))
    if want_dots is not None:
        m = re.search(r"(\d+)\s*點", txt)
        if not m or int(m.group(1)) != int(want_dots):
            out.append(Finding(
                where="#stat 點數", symptom="頁腳的點數跟資料對不上",
                expected=str(want_dots),
                actual=(m.group(1) if m else txt or "（空的）")))
    del got
    return out


def check_rescue_never_guesses(r: Render) -> list[Finding]:
    """退不回去的時候，畫面要講缺什麼，不准給輪號。

    這一條守的是規格那句「算不出來不猜一個出來」：猜一個輪號
    會把還好的工作一起丟掉，而且丟了不會有人發現。
    """
    dom = strip_fixture(r.dom)
    resc = (r.fixture["strands"].get("rescue") or
            r.fixture["snapshot"].get("rescue") or None)
    back = _tag_text(dom, "rBack")
    cost = _tag_text(dom, "rCost") or ""
    if back is None:
        return []
    out = []
    if resc and resc.get("can"):
        want = str(resc.get("back_to"))
        if want not in (back or ""):
            out.append(Finding(
                where="#rBack", symptom="救得回去，可是畫面上的輪號不是資料裡那個",
                expected=f"第 {want} 輪", actual=back or "（空的）"))
    else:
        if re.search(r"第\s*\d+\s*輪", back or ""):
            out.append(Finding(
                where="#rBack",
                symptom=("算不出可以退到哪一輪，畫面上卻給了一個輪號。"
                         "照著退會把還好的工作一起丟掉，而且不會有人發現"),
                expected="說明缺什麼，不給輪號", actual=back))
        elif not cost.strip():
            out.append(Finding(
                where="#rCost",
                symptom="說了退不回去，卻沒有講缺什麼，看的人不知道下一步要做什麼",
                expected="一句說明缺什麼", actual="（空的）"))
    return out


# ------------------------------------------------ 展開之後那四格

# ---------------------------------------------------------- 七個分頁

# 一格探針：在 `#lane` 裡面找什麼、要等於 fixture 算出來的什麼。
#
# `cls` 收的是**一串候選 class，第一個找到的算數**。理由不是為了
# 寬鬆，是 `app.js` 真的會換 class：`renderWork` 的表頭寫
# `d.total ? "aBig" : "fBig"`（`app.js:2316`），`renderSpec` 同一招
# （`:2405`）—— 數字是 0 的時候那一格換一個 class。只認一個的話，
# 一個真的沒有待辦的乾淨狀態會被判成「找不到表頭」。
Probe = namedtuple("Probe", "kind cls want zh")

# `kind` 三種，各自問的是不同的問題：
#   count  這一塊裡有幾列（畫面上那幾列 == 資料裡那幾筆）
#   nums   這一格文字裡的數字（畫面上那個數字 == 資料裡那個數字）
#   text   這一格的文字本身（畫面上那個字 == 資料裡那個字）
# `want` 是一個吃 fixture 回期望值的函式，**不是寫死的常數** ——
# 寫死的話換一條 session 整組就紅了，而那不是畫面壞掉。


def _fam_count(fx: dict, fam: str) -> int:
    """三格嚴重度裡，屬於這一家的發現有幾筆。

    `renderList` 是從 `strands.rows` 自己數出來的（`app.js:2044`），
    不是後端算好一個數字送過來。所以這裡也要從同一份原始資料數，
    不能去讀某個現成的總數欄位 —— 讀現成的那個驗到的是
    「兩個欄位一不一致」，不是「畫面上那個數字對不對」。
    """
    n = 0
    for row in ((fx.get("strands") or {}).get("rows") or []):
        for it in (row.get("betrayals") or []) + (row.get("overclaims") or []):
            if (it.get("family") or "") == fam:
                n += 1
    return n


# 一個分頁：哪個 view、畫面上叫什麼、按哪一顆、驗哪幾格。
Tab = namedtuple("Tab", "view zh probes")

# **入口是漢堡，不是分頁列。** 七顆 `.vw` 全部住在 `#picker` 裡面，
# 而 `#picker` 在 `index.html:106` 帶著 `hidden`。真人要先按左上角
# 那顆漢堡（`#burgerBtn`，`app.js:2946` 掛 `openPicker`）才看得到它們。
# 所以這一組每一次是**兩下**。
#
# 【這條路有一個實測出來的盲點，寫在下面 TABS 底下】
def tab_clicks(view: str) -> tuple[str, ...]:
    return ("#burgerBtn", '.vw[data-view="%s"]' % view)


TABS = (
    Tab("work", "在做什麼", (
        Probe("nums", ("aBig", "fBig"),
              lambda f: [str(f["work"]["total"])], "還沒做完幾件"),
        Probe("nums", ("aSub",),
              lambda f: [str(f["work"]["active"])], "進行中幾件"),
        # 帳本裡還有「進行中」那一區的話，`renderWork` 會再多畫一張
        # `.wk`（`app.js:2361`）。那一張不是任務，是清單，
        # 所以這裡要加回去 —— 不加的話真實資料一旦有進行中就紅，
        # 而那不是畫面壞掉。
        Probe("count", ("wk",),
              lambda f: len(f["work"].get("tasks") or []) +
              (1 if (f["work"].get("active_rows") or []) else 0), "任務卡"),
    )),
    Tab("feat", "功能", (
        Probe("nums", ("fBig", "aBig"),
              lambda f: [str(f["features"]["alive"]),
                         str(f["features"]["total"])], "活的／全部"),
        # 2026-09-17: 這一頁現在畫兩份 —— 做好的（items）與還沒做的
        # （missing）。只數 items 的話，加了第二份之後這一條會紅，
        # 而紅的原因不是畫錯，是它不知道有第二份。
        Probe("count", ("fi",),
              lambda f: (len(f["features"].get("items") or [])
                         + len(f["features"].get("missing") or [])),
              "功能列（做好的加還沒做的）"),
    )),
    Tab("spec", "讀文件", (
        Probe("nums", ("aBig", "fBig"),
              lambda f: [str(f["spec_reading"]["full"]),
                         str(f["spec_reading"]["total"])], "讀完／全部"),
        # 必讀清單那一塊是 lane 裡第一個 `.fam`（`app.js:2413`），
        # 底下區塊閱讀跟問題那兩塊也是 `.fam`，所以這裡數的是
        # **第一塊裡面的 `.ct`**，不是整個 lane 的。
        # 不縮的話數出來是 74，而清單只有 30。
        Probe("count", ("__fam1:ct",),
              lambda f: len(f["spec_reading"].get("rows") or []), "必讀清單列"),
    )),
    Tab("audit", "自我審計", (
        Probe("nums", ("aBig", "fBig"),
              lambda f: [str(f["audit"]["count"])], "這一輪的損害筆數"),
        Probe("nums", ("aSub",),
              lambda f: [str(f["audit"]["events"]),
                         str(f["audit"]["burden"])], "帳本事件數與你說了幾次繼續"),
        Probe("count", ("af",),
              lambda f: len(f["audit"].get("faults") or []), "事故卡"),
    )),
    Tab("machine", "這台機器", (
        Probe("text", ("machHost",), lambda f: f["machine"]["host"], "主機名"),
        Probe("text", ("machModel",), lambda f: f["machine"]["model"], "機型"),
        Probe("count", ("mi",),
              lambda f: len(f["machine"].get("items") or []), "掃到的東西"),
    )),
    Tab("list", "需要注意", (
        Probe("nums", ("sevC",), lambda f: [str(_fam_count(f, "C"))], "編造"),
        Probe("nums", ("sevB",), lambda f: [str(_fam_count(f, "B"))], "沒做卻說做了"),
        Probe("nums", ("sevA",), lambda f: [str(_fam_count(f, "A"))], "講太滿"),
    )),
)

# **`tree` 不在這張表裡**，因為它是預設那一頁，`check_tree_drew_nodes`
# 已經在第一張快照上驗過了。放進來會變成同一件事驗兩次，
# 而多開一次瀏覽器十秒。

# 這一組驗不到什麼，寫出來免得被讀成「七個分頁全驗過了」：
#
# 一，**驗不到「是那一下按的造成的」。** 跟展開那一組同一個盲點，
#     只是這裡更嚴重一點：`syncView()`（`app.js:3035`）跟輪詢迴圈
#     （`app.js:3010`）兩條路都會畫這幾頁。`--dump-dom` 只照一張，
#     分不開誰畫的。要分得開得量時間。
#
# 二，**漢堡那一下對結果沒有影響（2026-09-17 實測）。**
#     `HTMLElement.click()` 對 `hidden` 底下的元素照樣派送事件，
#     所以不按漢堡直接按 `.vw` 也會切過去。這一組照樣按漢堡，
#     因為那是真人走的路；但**它證明不了漢堡是通的** ——
#     漢堡哪天壞掉，這一組仍然全綠。守那件事的是
#     `check_burger_opens_picker`，它問的是不同的問題。
#
# 三，**只按得到一步就到的分頁。** 分頁裡面還有第二層的東西
#     （`.fi` 展開、`.wk` 上那三顆動作鈕）全部不在射程內。


def _lane(r: Render) -> str | None:
    return _id_html(strip_fixture(r.dom), "lane")


def _first(frag: str, cands: tuple[str, ...]):
    """候選 class 裡第一個找得到的，回 (class, 那一塊的文字)。"""
    for c in cands:
        t = _cls_text(frag, c)
        if t is not None:
            return c, t
    return None, None


def check_tab_switched(r: Render, tab: Tab) -> list[Finding]:
    """那一下真的切過去了，而且 lane 裡有東西。

    這一條存在的理由跟 `check_expanded_opened` 一樣：底下每一條
    探針遇到「找不到那一格」都會報一條，但**如果整個 lane 是空的
    或還停在「讀任務帳本」那個佔位字**，報出來的會是一堆
    「找不到 xxx」，而真正的症狀是「那一下沒按到」。
    症狀跟原因差一層的話，看的人要自己翻譯回去。
    """
    dom = strip_fixture(r.dom)
    out: list[Finding] = []
    m = re.search(r'data-view="%s"[^>]*aria-pressed="(\w+)"' % tab.view, dom)
    if not m:
        out.append(Finding(
            where=f"分頁 {tab.zh}（{tab.view}）",
            symptom="那一排分頁按鈕裡找不到這一顆",
            expected=f'index.html 有 .vw[data-view="{tab.view}"]',
            actual="DOM 裡沒有"))
        return out
    if m.group(1) != "true":
        out.append(Finding(
            where=f"分頁 {tab.zh}（{tab.view}）",
            symptom="按了之後這一顆沒有變成選中的那一顆，畫面還停在別頁",
            expected='aria-pressed="true"',
            actual=f'aria-pressed="{m.group(1)}"'))
    lane = _id_html(dom, "lane")
    if not lane or not lane.strip():
        out.append(Finding(
            where=f"分頁 {tab.zh}（{tab.view}）",
            symptom="切過去了，但畫面主區是空的",
            expected="#lane 裡有畫出來的東西",
            actual="空的" if lane is not None else "找不到 #lane"))
        return out
    # 佔位字是「還在讀」，不是「讀完了沒東西」。停在佔位字
    # 代表那一支 async render 沒有跑完就照相了 —— 這一條要是
    # 沒有，那些數字探針會報成「找不到表頭」，方向完全不同。
    for ph in ("讀任務帳本", "逐項驗證中", "算必讀清單", "讀帳本", "掃描中"):
        if ("<div class=\"none\">%s</div>" % ph) in lane:
            out.append(Finding(
                where=f"分頁 {tab.zh}（{tab.view}）",
                symptom=f"畫面停在佔位字「{ph}」，那一頁還沒讀完就照相了",
                expected="render 跑完之後的內容",
                actual=f"佔位字「{ph}」"))
    return out


def check_tab_values(r: Render, tab: Tab) -> list[Finding]:
    """那一頁畫出來的數字與列數，等於 fixture 裡那些。"""
    lane = _lane(r)
    if lane is None:
        return [Finding(
            where=f"分頁 {tab.zh}（{tab.view}）",
            symptom="找不到畫面主區，整頁沒有東西可以驗",
            expected="#lane 在 DOM 裡",
            actual="找不到")]
    out: list[Finding] = []
    for pr in tab.probes:
        try:
            want = pr.want(r.fixture)
        except (KeyError, TypeError) as e:
            # fixture 少一把鑰匙不准安靜跳過。2026-09-17 展開那一組
            # 就是「安靜跳過」害整組假綠的。
            out.append(Finding(
                where=f"分頁 {tab.zh} ／ {pr.zh}",
                symptom="這一格的期望值算不出來，這是這支自己的表寫錯了",
                expected="fixture 裡有這個鍵",
                actual=f"{type(e).__name__}: {e}"))
            continue

        if pr.kind == "count":
            cls = pr.cls[0]
            if cls.startswith("__fam1:"):
                # 只數 lane 裡第一個 `.fam` 那一塊。
                frag = _box_html(lane, "fam")
                cls = cls.split(":", 1)[1]
                if frag is None:
                    out.append(Finding(
                        where=f"分頁 {tab.zh} ／ {pr.zh}",
                        symptom="找不到清單那一塊",
                        expected=f"lane 裡有 .fam，裡面 {want} 列",
                        actual="沒有 .fam"))
                    continue
            else:
                frag = lane
            got = _count_class(frag, cls)
            if got != want:
                out.append(Finding(
                    where=f"分頁 {tab.zh} ／ {pr.zh}",
                    symptom="畫出來的列數跟資料裡的筆數對不上",
                    expected=f"{want} 列", actual=f"{got} 列（.{cls}）"))
            continue

        cls, txt = _first(lane, pr.cls)
        if txt is None:
            out.append(Finding(
                where=f"分頁 {tab.zh} ／ {pr.zh}",
                symptom="畫面上找不到這一格",
                expected="、".join(f".{c}" for c in pr.cls) + " 其中一個",
                actual="都沒有"))
            continue
        if pr.kind == "nums":
            got = _nums(txt)[:len(want)]
            if got != list(want):
                out.append(Finding(
                    where=f"分頁 {tab.zh} ／ {pr.zh}",
                    symptom="畫面上那個數字不是資料裡那個",
                    expected="、".join(want),
                    actual=("、".join(got) if got else "那一格一個數字都沒有")
                    + f"（.{cls}：{txt[:60]}）"))
        elif pr.kind == "text":
            if want not in txt:
                out.append(Finding(
                    where=f"分頁 {tab.zh} ／ {pr.zh}",
                    symptom="畫面上那個字不是資料裡那個",
                    expected=str(want), actual=f"{txt[:80]}（.{cls}）"))
    return out


def check_burger_opens_picker(r: Render) -> list[Finding]:
    """只按漢堡，那個面板要真的打開。

    **這一條跟上面兩條問的不是同一件事。** 上面兩條按的是
    漢堡加分頁兩下，而 `HTMLElement.click()` 對 `hidden` 底下的
    元素照樣派送事件（2026-09-17 實測），所以漢堡壞掉的話
    上面兩條**仍然全綠**，畫面上卻沒有任何辦法切分頁。
    這一條就是補那個洞：只按漢堡，看 `#picker` 的 `hidden` 掉了沒。
    """
    dom = strip_fixture(r.dom)
    m = re.search(r'<div class="picker" id="picker"([^>]*)>', dom)
    if not m:
        return [Finding(
            where="漢堡",
            symptom="找不到那個面板，七個分頁全部沒有入口",
            expected="DOM 裡有 #picker", actual="沒有")]
    if "hidden" in m.group(1):
        return [Finding(
            where="漢堡",
            symptom="按了左上角那顆漢堡，選單沒有打開 —— "
                    "七個分頁在畫面上按不到",
            expected="#picker 的 hidden 拿掉",
            actual="還是 hidden")]
    n = _count_class(_id_html(dom, "picker") or "", "vw")
    if n != len(TABS) + 1:  # 七顆：六個分頁加 tree
        return [Finding(
            where="漢堡",
            symptom="選單打開了，但裡面的分頁數量不對",
            expected=f"{len(TABS) + 1} 顆 .vw", actual=f"{n} 顆")]
    return []


# 「在做什麼」那一頁，任務卡上第一顆動作鈕要按到哪裡。
#
# **三下：漢堡、分頁、那顆鈕。** 前兩下跟 `tab_clicks("work")` 一樣，
# 第三下才是這一組真正要問的東西。
#
# **只按第一下，不按第二下，而這是這一組的全部重點。**
# `wireActs`（`app.js:2254`）是兩段式的：第一下只把按鈕改成
# 「再按一次確定」加上 `armed`，**一個指令都不發**；第二下才
# `invoke("act")`。所以按第一下驗得到那道閘還在，而且驗的過程
# 不會往正本寫任何東西。
#
# 按第二下會怎樣：harness 的 fixture 裡沒有 `act` 這把鑰匙，
# stub 會回 `{}`，所以就算按下去也碰不到真的帳本。**但這一組
# 不靠那件事** —— 靠 stub 的形狀來保證安全，等於哪天有人往
# fixture 加一個 `act` 就默默變成會執行，而沒有人會發現。
# 不按第二下是這支自己的決定，不是環境剛好擋住。
ACT_CLICKS = ("#burgerBtn", '.vw[data-view="work"]',
              '.acts .ac[data-kind="finish"]')

# 第一下之後那顆鈕該長什麼樣（`app.js` 的 `wireActs`）。
ARMED_LABEL = "再按一次確定"

# 動作鈕那一組照相的時刻（虛擬時間毫秒）。
#
# **這個數字自己就是一條斷言。** 它要落在一個窗裡：
#
#   按下那一刻            3300（CLICK_AFTER_MS + 2 * CLICK_GAP_MS）
#   ＋2000 以上           跨過至少一次輪詢（`setInterval(tick, 2000)`）
#   ＋5000 以下           確認窗自己的計時器還沒把 armed 還原
#
# 也就是 (5300, 8300)。取 7000，兩邊各留一千多毫秒。
#
# 為什麼一定要跨過輪詞：2026-09-17 抓到的那個 bug 正是
# 「輪詢重畫把 armed 沖掉」，照相時機若落在第一次輪詢之前，
# 那個 bug 會照出一張乾淨的畫面。預設的 8000 只比 8300 早 300，
# 窄到一次時序抖動就會翻面 —— 而翻面之後是**綠的**，
# 也就是往「看起來沒事」的方向壞。
ACT_BUDGET_MS = 7000


def _acts_box(r: Render) -> str | None:
    lane = _lane(r)
    if lane is None:
        return None
    return _box_html(lane, "acts")


def check_act_arms_not_fires(r: Render) -> list[Finding]:
    """按第一下，那顆鈕要進入待確認，而且不該有執行結果。

    這一條守的是**兩段式確認本身**。哪天有人把 `armed` 那一段
    拿掉，三顆鈕會變成按一下就寫帳本 —— 畫面不會壞、別的測試
    不會紅，而使用者滑一下滑鼠就改掉了正本。
    """
    out: list[Finding] = []
    box = _acts_box(r)
    if box is None:
        return [Finding(
            where="在做什麼 ／ 任務卡動作鈕",
            symptom="切到那一頁之後找不到動作鈕那一排",
            expected="lane 裡有 .acts（app.js:2352）",
            actual="沒有 .acts")]

    m = re.search(r'<button[^>]*\bclass="([^"]*)"[^>]*\bdata-kind="finish"'
                  r'|<button[^>]*\bdata-kind="finish"[^>]*\bclass="([^"]*)"',
                  box)
    if not m:
        out.append(Finding(
            where="在做什麼 ／ 收尾鈕",
            symptom="那一排裡找不到「收尾」這一顆",
            expected='button[data-kind="finish"]',
            actual="沒有"))
        return out
    cls = m.group(1) or m.group(2) or ""
    if "armed" not in cls.split():
        out.append(Finding(
            where="在做什麼 ／ 收尾鈕",
            symptom="按了第一下，那顆鈕沒有進入待確認 —— "
                    "兩段式確認可能被拿掉了，那會讓一下就寫進帳本",
            expected='class 裡有 armed（app.js:2264）',
            actual=f'class="{cls}"'))

    n = _count_class(box, "armed")
    if n > 1:
        out.append(Finding(
            where="在做什麼 ／ 動作鈕",
            symptom="按一顆卻有多顆進入待確認，按錯的那一顆也會被確認掉",
            expected="1 顆 armed", actual=f"{n} 顆"))

    label = _cls_text(box, "armed")
    if label is not None and ARMED_LABEL not in label:
        out.append(Finding(
            where="在做什麼 ／ 收尾鈕",
            symptom="進入待確認了，但鈕上的字沒有講出「還要再按一次」，"
                    "使用者會以為剛剛那一下沒反應",
            expected=ARMED_LABEL, actual=label[:40]))

    res = _cls_text(box, "acOut")
    if res:
        out.append(Finding(
            where="在做什麼 ／ 動作結果",
            symptom="只按了第一下，畫面上卻已經有執行結果",
            expected="那一格是空的（第一下不執行）", actual=res[:60]))
    return out


def check_act_did_not_invoke(r: Render) -> list[Finding]:
    """按第一下之後，`act` 這個指令一次都沒有被發出去。

    上面那條看的是畫面，這條看的是**有沒有真的發出指令** ——
    兩件事。畫面上沒有結果，可能是指令發了而回傳被吃掉。

    **記錄整個是空的要報錯，不准放行。** 頁面一載入 app.js 就會
    發 `strands`、`snapshot` 這些，所以觀察器只要裝上了，
    記錄一定不是空的。空的只有一種解釋：觀察器沒裝上 ——
    而那一刻「一次都沒發 act」是真的，卻毫無意義。
    這是 5o 那一輪「安靜跳過害整組假綠」的同一種病，
    所以這裡把它報成驗不了，不是報成通過。
    """
    raw = _tag_text(r.dom, SPY_ID)
    if raw is None:
        return [Finding(
            where="在做什麼 ／ 指令觀察器",
            symptom="觀察器沒有把結果寫進畫面，這一條驗不了（不是通過）",
            expected=f"DOM 裡有 #{SPY_ID}", actual="沒有")]
    try:
        cmds = json.loads(raw)
    except ValueError:
        return [Finding(
            where="在做什麼 ／ 指令觀察器",
            symptom="觀察器寫出來的東西不是清單，這一條驗不了（不是通過）",
            expected="一個 JSON 陣列", actual=raw[:80])]
    if not isinstance(cmds, list) or not cmds:
        return [Finding(
            where="在做什麼 ／ 指令觀察器",
            symptom="一個指令都沒收到，代表觀察器沒裝上 —— "
                    "頁面一載入就會發 strands，不可能是空的",
            expected="至少收到載入時那幾個指令",
            actual=repr(cmds)[:80])]
    if "act" in cmds:
        return [Finding(
            where="在做什麼 ／ 收尾鈕",
            symptom="只按了第一下，指令就已經發出去了 —— "
                    "兩段式確認沒有擋住，正本會被改掉",
            expected="act 不在這一次的指令清單裡",
            actual="發了 " + "、".join(cmds))]
    return []


def check_expanded_opened(r: Render) -> list[Finding]:
    """展開那一下真的發生了。

    **這一條守的是它底下那四條本身。** 下面每一條遇到
    「找不到這一塊」都是直接放行的（那個設計是對的：元素在不在
    歸 `test_ui_contract.py` 管），而那有一個副作用 ——
    哪天那一下沒按到（按鈕改 id、listener 被拆掉、時機太早），
    四條會一起變成綠的，而且畫面上其實什麼都沒展開。

    跟 `test_確實讀到了東西而不是一片空白` 是同一件事的第二個位置。
    """
    dom = strip_fixture(r.dom)
    out = []
    if not re.search(r'class="[^"]*\bdims\b[^"]*\bopen\b', dom) and \
       not re.search(r'class="[^"]*\bopen\b[^"]*\bdims\b', dom):
        out.append(Finding(
            where=".dims",
            symptom="按了展開，可是那一區沒有打開。底下那四格根本沒有被畫",
            expected="`.dims` 帶著 open",
            actual="沒有 open"))
    for key, cls, _row, _lk, zh in EXPANDED_BOXES:
        if _box_html(dom, cls) is None:
            out.append(Finding(
                where=f".{cls}",
                symptom=f"展開之後「{zh}」那一格整塊不在畫面上",
                expected=f"一個 .{cls}", actual="找不到"))
    return out


def _expanded_data(r: Render, key: str) -> dict | None:
    d = r.fixture.get("strands") or {}
    v = d.get(key)
    if not isinstance(v, dict):
        v = (r.fixture.get("snapshot") or {}).get(key)
    return v if isinstance(v, dict) else None


def check_expanded_row_counts(r: Render) -> list[Finding]:
    """資料裡有幾列，畫面上就要有幾列。

    這四格先前只有靜態接線在守 —— 「`renderBlast` 有定義、
    有人呼叫」跟「按下去之後那八行真的畫出來了」是兩件事，
    而 2026-09-14 那次整頁是死的，靜態那兩組全綠。

    **`has` 是 false 的時候不當作錯。** 那是資料端說算不出來，
    畫面照著印「沒有資料」是對的行為。這裡只抓一種：
    **資料說有，畫面上卻是那句「沒有資料」**。
    """
    dom = strip_fixture(r.dom)
    out = []
    for key, cls, row_cls, list_key, zh in EXPANDED_BOXES:
        frag = _box_html(dom, cls)
        if frag is None:
            continue          # 整塊不在 → 上面那條負責
        data = _expanded_data(r, key)
        if data is None:
            continue          # fixture 沒有這一鍵 → 不是畫面的問題
        if not data.get("has"):
            continue
        rows = data.get(list_key)
        if not isinstance(rows, list):
            # 這是這支自己的表寫錯了，不是畫面壞了。
            # 安靜跳過的話這一格從此不驗，而且沒有人會發現。
            out.append(Finding(
                where=f"EXPANDED_BOXES[{key!r}]",
                symptom=(f"「{zh}」這一格沒有被驗到 —— 這支拿的鍵"
                         f"`{list_key}` 在資料裡不是一個清單，"
                         "是這支自己的表寫錯了"),
                expected=f"{key}.{list_key} 是 list",
                actual=type(rows).__name__))
            continue
        if _count_class(frag, "none"):
            out.append(Finding(
                where=f".{cls}",
                symptom=(f"資料算得出「{zh}」，畫面上印的卻是"
                         "「沒有資料」那一版"),
                expected=f"{len(rows)} 列",
                actual="沒有資料"))
            continue
        got = _count_class(frag, row_cls)
        if got != len(rows):
            out.append(Finding(
                where=f".{cls} .{row_cls}",
                symptom=f"「{zh}」畫出來的列數跟資料裡的不一樣",
                expected=f"{len(rows)} 列", actual=f"{got} 列"))
    return out


def check_blast_header_counts(r: Render) -> list[Finding]:
    """波及範圍那一行的檔數與邊數，是資料裡那兩個。

    列數對不代表數字對 —— 那一行是整張圖的規模，
    而它是唯一一個會讓人以為「這張圖掃過全部」的數字。
    """
    dom = strip_fixture(r.dom)
    frag = _box_html(dom, "blast")
    b = _expanded_data(r, "blast")
    if frag is None or not b or not b.get("has"):
        return []
    m = re.search(r'<span class="sub">(.*?)</span>', frag, flags=re.S)
    if not m:
        return []
    txt = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1)))
    got = _nums(txt)
    want = [str(b.get("files")), str(b.get("edges"))]
    if got[:2] != want:
        return [Finding(
            where=".blast .sub",
            symptom="波及範圍那一行的檔數或邊數，不是資料裡那兩個",
            expected=f"{want[0]} 個檔案　{want[1]} 條依賴邊",
            actual=txt.strip() or "（空的）")]
    return []


def check_blast_cache_badge(r: Render) -> list[Finding]:
    """那一格右上角的快取標記，跟資料裡的 `cache_write` 對得上。

    **這一格先前只有兩種狀態畫得出來，資料裡有四種。**
    `b.cached` 是 true 就標「快取」，否則什麼都不標，
    於是「這一次剛算」跟「快取寫不進去、每一次都會重算」
    在畫面上一模一樣。2026-09-17 實測（快取目錄 chmod 0o500）：
    `vectors()` 回傳的 36 個鍵一個都沒少，`cached` 兩次都是 False，
    答案逐欄位相同，所以肉眼與這支工具都分不出來。

    **這支跑得到的是 ok 與 not_attempted 兩種。** failed 那一種要
    快取目錄寫不進去才會出現，harness 用的是真的那份 snapshot，
    所以它在這裡走不到，寫出來免得被讀成「三種都驗過了」。
    走得到它的是 `tests/test_blast_cache_write_status.py`（Python 側）。
    """
    dom = strip_fixture(r.dom)
    frag = _box_html(dom, "blast")
    b = _expanded_data(r, "blast")
    if frag is None or not b or not b.get("has"):
        return []
    m = re.search(r'<span class="blStale([^"]*)"[^>]*>(.*?)</span>', frag, flags=re.S)
    got = (m.group(2).strip(), "bad" in m.group(1)) if m else (None, False)
    cw = str(b.get("cache_write") or "")
    if b.get("cached"):
        want = ("快取", False)
    elif cw.startswith("failed:"):
        want = ("快取寫不進去", True)
    else:
        want = (None, False)
    if got != want:
        return [Finding(
            where=".blast .hd .blStale",
            symptom=("快取標記跟資料對不上。"
                     f"資料說 cached={b.get('cached')!r}、cache_write={cw!r}"),
            expected=("沒有標記" if want[0] is None
                      else f"標「{want[0]}」" + ("（警告色）" if want[1] else "")),
            actual=("沒有標記" if got[0] is None
                    else f"標「{got[0]}」" + ("（警告色）" if got[1] else "")))]
    return []


# ------------------------------------------------- 輪詢那一條路（誰畫的）

# 切到「在做什麼」之後，坐著不動，看那幾輪各自發了什麼。
POLL_CLICKS = ("#burgerBtn", '.vw[data-view="work"]')

# 這一組傾印與照相的時刻（虛擬時間毫秒）。
#
# **這兩個數字自己就是斷言的一部分**，跟 `ACT_BUDGET_MS` 同一個理由。
# 這一組問的是「按完之後坐過好幾輪，那幾輪做了什麼」，所以傾印的時刻
# 要離最後一下夠遠：
#
#   最後一下        2900（CLICK_AFTER_MS + CLICK_GAP_MS）
#   傾印           10500，也就是之後還有 7600 毫秒
#   輪詢間隔        2000（`setInterval(tick, 2000)`）
#   所以中間至少跨過 3 輪
#
# 倒得太早的話，輪詢還沒跑幾次，「重抓了幾次」這個問題會因為樣本
# 只有一輪而永遠答對 —— 往綠的方向壞。
POLL_SPY_AT_MS = 10500
POLL_BUDGET_MS = 11000

# 坐過那幾輪，`strands` 至少要被發幾次。
#
# 實測是 6（初次那一下加上五輪）。**寫 3 不寫 6**，因為這一條要
# 回答的是「輪詢在真的瀏覽器裡到底有沒有重跑」，不是「跑得剛好幾次」。
# 綁死 6 的話，虛擬時間的一次抖動就會紅，而紅的原因跟這條在問的事無關。
POLL_MIN_STRANDS = 3

# 坐過那幾輪，「在做什麼」那一頁重抓幾次任務帳本。
#
# **這個 1 是量出來的，不是訂出來的。** 2026-09-17 實測：切過去之後
# 跨過至少三輪，`work` 這個指令總共只發了一次，也就是切進去那一次。
# 之後每一輪 `renderWork()` 都跑了，但 `app.js` 的 `if (!workCache)`
# 讓它從快取重畫，一次都沒有回頭去問後端。
#
# 寫成常數是為了讓這個事實有一個看得到的位置。它不是「應該如此」，
# 是「現在如此」，而現在如此代表使用者坐在那一頁上，帳本更新了
# 畫面也不會變，沒有錯誤訊息，跟「真的沒有新任務」長得一模一樣。
# 要不要改成會重抓，是快取政策，規格沒有定義，所以這裡不替 owner 決定，
# 只把它變成一條會說話的斷言（見 `.forseti/BLOCKERS.md` B-16）。
POLL_EXPECTED_WORK_FETCHES = 1


def _spy_cmds(r: Render, where: str):
    """把觀察器那一格讀成指令清單。讀不到就回一條「驗不了」。

    **空的報成驗不了，不報成通過。** 跟 `check_act_did_not_invoke`
    同一條理由：頁面一載入就會發 `strands`，空的只有一種解釋，
    就是觀察器沒裝上，而那一刻底下每一條「發了幾次」都會答對，
    整組假綠。
    """
    raw = _tag_text(r.dom, SPY_ID)
    if raw is None:
        return None, [Finding(
            where=where,
            symptom="觀察器沒有把結果寫進畫面，這一條驗不了（不是通過）",
            expected=f"DOM 裡有 #{SPY_ID}", actual="沒有")]
    try:
        cmds = json.loads(raw)
    except ValueError:
        return None, [Finding(
            where=where,
            symptom="觀察器寫出來的東西不是清單，這一條驗不了（不是通過）",
            expected="一個 JSON 陣列", actual=raw[:80])]
    if not isinstance(cmds, list) or not cmds:
        return None, [Finding(
            where=where,
            symptom="一個指令都沒收到，代表觀察器沒裝上，這一條驗不了"
                    "（不是通過）—— 頁面一載入就會發 strands，"
                    "不可能是空的",
            expected="至少收到載入時那幾個指令",
            actual=repr(cmds)[:80])]
    return [str(c) for c in cmds], []


def check_poll_loop_really_repeats(r: Render) -> list[Finding]:
    """輪詢在真的瀏覽器裡真的重跑，不是只有載入時那一次。

    **這一條跟原始碼層那一條不是同一件事。** `tests/test_ui_contract.py`
    守的是 `setInterval(tick, 2000)` 這一行還在、分派那幾行還在；
    這一條守的是那一行在瀏覽器裡真的有效果。中間隔著的東西
    （`loadFoundation()` 的 promise、tick 自己的 try/catch、
    每一輪都要成功回來的 `invoke`）任何一個壞掉，原始碼那一條仍然全綠。

    量的是 `strands` 的次數，因為 `tick` 的第一件事就是發它。
    發了幾次等於這條線真的跑了幾輪。
    """
    where = "整頁 ／ 兩秒一輪的輪詢"
    cmds, bad = _spy_cmds(r, where)
    if bad:
        return bad
    n = cmds.count("strands")
    if n < POLL_MIN_STRANDS:
        return [Finding(
            where=where,
            symptom="畫面停在載入時那一刻不再更新，而且沒有任何錯誤訊息，"
                    "看起來就像「沒有新資料」",
            expected=f"坐過 {POLL_SPY_AT_MS} 毫秒至少發 "
                     f"{POLL_MIN_STRANDS} 次 strands",
            actual=f"只發了 {n} 次（全部指令：{'、'.join(cmds)}）")]
    return []


def check_poll_repaints_from_cache(r: Render) -> list[Finding]:
    """切到「在做什麼」之後坐著不動，那幾輪重抓了幾次任務帳本。

    **這一條補的是「分不出那一格是誰畫的」那個盲點。** 在這之前，
    畫面上有內容只證明有人畫過，畫的是 `syncView`（切分頁那一下）
    還是輪詢（之後每兩秒），DOM 上分不出來，兩條路畫出來的
    HTML 一模一樣。指令清單分得出來：切分頁那一下會清快取所以會重抓，
    輪詢那幾輪不會。

    兩個方向都會紅，而兩邊的症狀不一樣：

    0 次，切過去根本沒抓，那一頁會停在「讀任務帳本」那一行。

    2 次以上，快取政策被改過了。那不一定是壞事，但這個數字是
    2026-09-17 量出來寫進 `POLL_EXPECTED_WORK_FETCHES` 的一個事實，
    改動它的人要一起改那個常數與 B-16，不能讓它安靜地變。
    """
    where = "在做什麼 ／ 輪詢重畫"
    cmds, bad = _spy_cmds(r, where)
    if bad:
        return bad
    n = cmds.count("work")
    if n == POLL_EXPECTED_WORK_FETCHES:
        return []
    if n == 0:
        return [Finding(
            where=where,
            symptom="切到「在做什麼」之後那一頁停在「讀任務帳本」，"
                    "永遠不會有內容",
            expected="切過去那一下要抓一次任務帳本",
            actual=f"一次都沒抓（全部指令：{'、'.join(cmds)}）")]
    return [Finding(
        where=where,
        symptom="輪詢重抓任務帳本的次數變了，快取政策被動過，"
                "而這個數字是量出來的事實，不是預設值",
        expected=f"跨過至少三輪只抓 {POLL_EXPECTED_WORK_FETCHES} 次"
                 "（之後每一輪都從 workCache 重畫）",
        actual=f"抓了 {n} 次。要改的話連 POLL_EXPECTED_WORK_FETCHES "
               "與 BLOCKERS.md 的 B-16 一起改")]


# ------------------------------------------ 另外五頁：誰畫的（同一個問題）

# 一頁「屬於它自己」的後端指令，全部列在這裡。
#
# **每一頁都對整份清單斷言，不是只對自己那一個。** 只數自己那一個
# 的話，「這一頁順手多發了別頁的指令」看不見；而更要命的是，那一下
# 根本沒切過去的時候，每一條「那個指令 0 次」都會答對 —— 往綠的
# 方向壞。所以沒列進 `expect` 的一律期望 0 次，缺席本身是斷言。
PAGE_CMDS = ("work", "features", "audit", "machine",
             "spec_reading", "block_reading", "sufficiency")

# 期望值的第二種：不是某個次數，是「每一輪都重抓」。
LIVE = "每輪"

# 「每輪重抓」至少要看到幾次。
#
# 寫 3 不寫實測的 5，跟 `POLL_MIN_STRANDS` 同一個理由：這一條問的是
# 「這一條路在瀏覽器裡到底有沒有每輪重跑」，不是「跑得剛好幾次」。
# 綁死實測值的話，虛擬時間抖一下就紅，而紅的原因跟這條在問的事無關。
POLL_MIN_LIVE = 3


# 一頁的輪詢行為：切過去之後坐著不動，那幾輪各發了什麼。
PollPage = namedtuple("PollPage", "view zh expect note")

# **`work` 不在這張表裡。** 它由 `check_poll_repaints_from_cache`
# 守著（2026-09-17 那一輪做的），而那一條被 `.forseti/BLOCKERS.md`
# B-16 指名。同一件事守兩處的話，改了一處另一處還綠，那比沒守更糟。
#
# 每一格的數字都是 2026-09-17 開瀏覽器量出來的，不是從程式碼推的，
# 也不是從上一輪的紀錄抄的（抄來的那一份正是這一輪推翻掉的東西）。
POLL_PAGES = (
    PollPage("feat", "功能",
             {"spec_reading": 1, "features": 1},
             "切進去抓一次，之後四輪都從 featCache 重畫"),
    PollPage("audit", "自我審計",
             {"spec_reading": 1, "audit": 1},
             "切進去抓一次，之後四輪都從 auditCache 重畫"),
    PollPage("machine", "這台機器",
             {"spec_reading": 1, "machine": 1},
             "切進去抓一次，之後四輪都從 machCache 重畫"),
    # **這一頁不是同一個形狀，而上一輪的紀錄說它是。**
    #
    # `spec_reading` 確實只抓兩次（載入那一次加切進去那一次，
    # `specCache` 守著）。但同一支 `renderSpec()` 裡還有兩個
    # 呼叫**沒有任何快取守門**：`block_reading`（`app.js:2458`）
    # 與 `renderTakeoverGate()` 裡的 `sufficiency`（`app.js:2497`）。
    # 它們跟著每一輪 `renderSpec()` 重發，所以這一頁的下半
    # （區塊閱讀、接管閘門）是即時的，上半（必讀清單）不是。
    #
    # 一頁兩種行為，而 B-16 的修法是按頁選的，所以這件事要有位置。
    PollPage("spec", "讀文件",
             {"spec_reading": 2, "block_reading": LIVE, "sufficiency": LIVE},
             "上半快取、下半每輪重抓，同一頁兩種行為"),
    # **這一頁一個專屬指令都不發**，連切進去那一次都沒有。
    # `syncView()` 的 `else renderList()`（`app.js:3076`）沒有
    # 對應的 `invoke`，`renderList` 讀的是 `tick` 已經抓回來的
    # `strands`。所以它是這六頁裡唯一真的即時的一頁 ——
    # 帳本更新，它下一輪就會變。這不是推論，是這張表量出來的。
    PollPage("list", "需要注意",
             {"spec_reading": 1},
             "沒有自己的指令，靠 strands 每輪重畫，唯一即時的一頁"),
)


def _tab_of(view: str) -> Tab | None:
    for t in TABS:
        if t.view == view:
            return t
    return None


def check_poll_page_fetches(r: Render, pg: PollPage) -> list[Finding]:
    """切到這一頁坐著不動，那幾輪各自回頭問了後端幾次。

    **這一條跟 `check_tab_values` 不是同一件事。** 那一條看的是
    一張靜止的 DOM 上「畫出來的數字對不對」，而一張 DOM 回答不了
    「這一格是切分頁那一下畫的，還是之後某一輪輪詢畫的」——
    兩條路呼叫的是同一支 render，畫出來的 HTML 一模一樣。
    指令清單分得出來。

    兩個方向都會紅，症狀不一樣：

    比期望少（尤其 0），切過去那一下根本沒抓，那一頁會停在佔位字。

    比期望多，快取政策被動過了。那不一定是壞事，但這張表裡每一個
    數字都是量出來的事實，改動它的人要一起改 `POLL_PAGES` 與
    `.forseti/BLOCKERS.md` 的 B-16，不能讓它安靜地變。

    **一個實測出來的盲點：`syncView()` 裡那幾行 `xxxCache = null`
    這一組驗不到。** 2026-09-17 反向驗證，把
    `else if (view === "feat") { featCache = null; renderFeat(); }`
    的清快取那一段拿掉，這一組**照樣全綠**。原因是那幾個快取變數
    初值就是 `null`（`app.js:2156` 等），所以首次切進去必然會抓一次，
    清不清都一樣。那幾行真正的效果在「切走再切回來要拿到新資料」，
    而這一組只按一下，按不到第二次切入。

    要驗到它得按三下（漢堡、A 頁、漢堡、B 頁、漢堡、A 頁），
    那是另一次瀏覽器與另一種時序，沒有做。寫在這裡是因為
    「這一組綠」不等於「那幾行有效」—— 兩者中間隔著這個盲點。
    """
    where = f"{pg.zh} ／ 坐著不動那幾輪"
    cmds, bad = _spy_cmds(r, where)
    if bad:
        return bad
    out: list[Finding] = []
    # 這張表自己寫錯的話，那一條期望會被**安靜跳過** —— 底下的迴圈
    # 只走 `PAGE_CMDS`，`expect` 裡一個拼錯的鍵不會有任何人去讀它。
    # 2026-09-17 的 `EXPANDED_BOXES` 第四欄就是這樣錯的（鍵寫成
    # `rows`，真正的鍵是 `top`），後果不是紅燈，是那一格被跳過。
    stray = sorted(set(pg.expect) - set(PAGE_CMDS))
    if stray:
        out.append(Finding(
            where=where,
            symptom="POLL_PAGES 裡有 PAGE_CMDS 沒列到的指令名，"
                    "那一條期望不會有人去讀 —— 是這支工具自己的表寫錯了",
            expected="expect 的每一個鍵都在 PAGE_CMDS 裡",
            actual="多出來的：" + "、".join(stray)))
    checked = 0
    for cmd in PAGE_CMDS:
        want = pg.expect.get(cmd, 0)
        n = cmds.count(cmd)
        checked += 1
        if want == LIVE:
            if n < POLL_MIN_LIVE:
                out.append(Finding(
                    where=where,
                    symptom=f"`{cmd}` 這條路本來每一輪都會重抓，現在沒有。"
                            "那一格會停在載入時那一刻，而且沒有錯誤訊息",
                    expected=f"坐過 {POLL_SPY_AT_MS} 毫秒至少 "
                             f"{POLL_MIN_LIVE} 次（{pg.note}）",
                    actual=f"只發了 {n} 次（全部指令：{'、'.join(cmds)}）"))
        elif n != want:
            out.append(Finding(
                where=where,
                symptom=f"`{cmd}` 發的次數跟量到的事實不一樣，"
                        "快取政策被動過而 POLL_PAGES 這張表沒跟著改"
                        if n > want else
                        f"`{cmd}` 發得比量到的少，那一頁可能沒有內容"
                        "（POLL_PAGES 裡這一格的數字是量出來的）",
                expected=f"{want} 次（{pg.note}）",
                actual=f"{n} 次（全部指令：{'、'.join(cmds)}）"))
    # 一條都沒比對過要報成驗不了，不能安靜回空。
    #
    # **回空跟通過在呼叫端長得一模一樣**，而這一支要是空轉，
    # 上面那五頁會一起變綠而其實什麼都沒驗。2026-09-17 反向驗證
    # 實測：把迴圈改成不跑，五頁全綠 —— 加這一條之前它抓不到。
    if not checked:
        out.append(Finding(
            where=where,
            symptom="這一頁一個指令都沒有比對過，整支空轉了，"
                    "回空跟通過在呼叫端分不出來（這不是通過）",
            expected="PAGE_CMDS 裡每一個都比對一次",
            actual="比對了 0 個"))
    return out


# ------------------------------------------------ 第二次切進同一頁

# 中間先繞去哪一頁。
#
# **挑「需要注意」是因為它一個專屬指令都不發**（`POLL_PAGES` 那張表
# 量出來的）。繞路那一頁自己會發指令的話，它的次數會混進這一組的
# 計數裡，而這一組要看的是 A 頁那一個指令發了幾次。
REVISIT_B_VIEW = "list"

# 這一組的傾印與照相時刻（虛擬時間毫秒）。
#
# 六下，最後一下落在 `CLICK_AFTER_MS + 5 * CLICK_GAP_MS` = 4500。
# 傾印 6000 是之後還有 1500，夠第三下引發的 invoke 回來。
#
# **這一組刻意不坐久。** `POLL_PAGES` 那一組坐 10500 是要看
# 「坐著不動那幾輪做了什麼」；這一組問的是「切回來那一下做了什麼」，
# 坐久了只會讓每輪重發的那幾個指令堆更多次，把要看的事實淹掉。
REVISIT_SPY_AT_MS = 6000
REVISIT_BUDGET_MS = 6500

# 這一組裡「每輪重抓」至少要看到幾次。
#
# **不是 `POLL_MIN_LIVE` 的 3。** 這一組的時窗只有 1500 毫秒，
# 跨不過三輪，拿那個門檻來套會因為時窗而紅，紅的原因跟這條在問的
# 事無關。寫 2 的意思是「兩次切入各至少一次」，也就是這一組真正
# 分得出來的東西。
#
# 代價寫在 `check_revisit_refetches` 的說明裡：**這一組分不出
# 「每輪重發」與「每次切入各發一次」**，那是 `POLL_PAGES` 的事。
REVISIT_MIN_LIVE = 2


def revisit_clicks(view: str) -> tuple[str, ...]:
    """漢堡、A 頁、漢堡、繞路那一頁、漢堡、A 頁。六下。"""
    return ("#burgerBtn", '.vw[data-view="%s"]' % view,
            "#burgerBtn", '.vw[data-view="%s"]' % REVISIT_B_VIEW,
            "#burgerBtn", '.vw[data-view="%s"]' % view)


# 第二次切進同一頁，那一下各發了什麼。
RevisitPage = namedtuple("RevisitPage", "view zh expect note")

# **這張表跟 `POLL_PAGES` 問的不是同一件事，所以 `work` 在這裡。**
# `POLL_PAGES` 把 `work` 排除，因為 `check_poll_repaints_from_cache`
# 已經守著它「坐著不動不重抓」。這一組守的是「切回來要重抓」——
# 反過來的方向，而 `workCache = null`（`app.js:3072`）這一行
# 在這之前沒有任何人守。
#
# 每一格的數字都是 2026-09-17 開瀏覽器量出來的。
REVISIT_PAGES = (
    RevisitPage("work", "在做什麼", {"spec_reading": 1, "work": 2},
                "兩次切入各抓一次（`workCache = null`）"),
    RevisitPage("feat", "功能", {"spec_reading": 1, "features": 2},
                "兩次切入各抓一次（`featCache = null`）"),
    RevisitPage("audit", "自我審計", {"spec_reading": 1, "audit": 2},
                "兩次切入各抓一次（`auditCache = null`）"),
    RevisitPage("machine", "這台機器", {"spec_reading": 1, "machine": 2},
                "兩次切入各抓一次（`machCache = null`）"),
    # 這一頁的 3 是載入那一次加兩次切入。下半那兩個本來就每輪重發
    # （`POLL_PAGES` 量到的），所以它們在這一組證明不了清快取的效力，
    # 列進來只是為了讓「缺席也是斷言」對整份 `PAGE_CMDS` 成立。
    RevisitPage("spec", "讀文件",
                {"spec_reading": 3, "block_reading": LIVE,
                 "sufficiency": LIVE},
                "載入一次加兩次切入（`specCache = null`）；"
                "下半那兩個本來就每輪重發"),
)


def _count_page_cmds(r: Render, where: str, expect: dict, note: str,
                     min_live: int, table: str,
                     less: str, more: str) -> list[Finding]:
    """照 `expect` 逐一數 `PAGE_CMDS`，回對不上的那幾條。

    **兩組共用這一支，不是各寫一份。** 各寫一份的話，哪天一邊改了
    邊界條件另一邊沒改，兩組會對同一個形狀給出不同答案，而那種分歧
    沒有任何人會紅。理由跟 `blast.py` 不在 Python 重寫 `cost.js`
    同一條。

    `less` ／ `more` 是次數少了、多了各自要講的話。**訊息不共用** ——
    兩組壞掉的時候使用者看到的東西不一樣，講成同一句就等於把
    「切回來看到舊資料」跟「快取政策被改過」混成一件事。
    兩個字串裡的 `{cmd}` 會被換成那個指令名。
    """
    cmds, bad = _spy_cmds(r, where)
    if bad:
        return bad
    out: list[Finding] = []
    # `expect` 裡拼錯一個鍵會被安靜跳過，因為底下的迴圈只走
    # `PAGE_CMDS`。安靜跳過的期望讀起來跟通過一模一樣。
    stray = sorted(set(expect) - set(PAGE_CMDS))
    if stray:
        out.append(Finding(
            where=where,
            symptom=f"{table} 裡有 PAGE_CMDS 沒列到的指令名，"
                    "那一條期望不會有人去讀 —— 是這支工具自己的表寫錯了",
            expected="expect 的每一個鍵都在 PAGE_CMDS 裡",
            actual="多出來的：" + "、".join(stray)))
    checked = 0
    for cmd in PAGE_CMDS:
        want = expect.get(cmd, 0)
        n = cmds.count(cmd)
        checked += 1
        if want == LIVE:
            if n < min_live:
                out.append(Finding(
                    where=where,
                    symptom=f"`{cmd}` 這條路本來每一輪都會重抓，現在沒有",
                    expected=f"至少 {min_live} 次（{note}）",
                    actual=f"只發了 {n} 次（全部指令：{'、'.join(cmds)}）"))
        elif n != want:
            out.append(Finding(
                where=where,
                symptom=(less if n < want else more).format(cmd=cmd),
                expected=f"{want} 次（{note}）",
                actual=f"{n} 次（全部指令：{'、'.join(cmds)}）"))
    # 一條都沒比對過要報成驗不了：回空跟通過在呼叫端分不出來。
    if not checked:
        out.append(Finding(
            where=where,
            symptom="這一頁一個指令都沒有比對過，整支空轉了，"
                    "回空跟通過在呼叫端分不出來（這不是通過）",
            expected="PAGE_CMDS 裡每一個都比對一次",
            actual="比對了 0 個"))
    return out


def check_revisit_refetches(r: Render, pg: RevisitPage) -> list[Finding]:
    """切走再切回來，那一下有沒有真的回頭問後端。

    **這一條補的是 2026-09-17 自己寫下的盲點。**
    `check_poll_page_fetches` 那一組只按一下，而
    `syncView()` 裡那幾行 `xxxCache = null`（`app.js:3072-3076`）
    在只按一下的時候不產生任何差別 —— 那幾個快取變數初值就是
    `null`（`app.js:2156` 等），首次切進去必然抓一次，清不清都一樣。
    當時實測把 `featCache = null` 拿掉，那一組照樣全綠。

    這一組按六下，所以那幾行有了效力：拿掉清快取，第二次切入
    就從快取重畫，次數從 2 掉到 1，這裡會紅。

    壞掉的話使用者看到什麼：切走做別的事再切回來，看到的是上一次
    的資料，而且沒有任何提示。跟「真的沒有變」長得一模一樣。

    **這一組驗不到的三件，寫出來免得被讀成驗過了：**

    一，**驗不到「切走過」。** `syncView()` 不管 `view` 有沒有變
        都照跑，所以這一組真正守的是「`syncView()` 第二次跑會
        重抓」，繞路那一頁在不在結果一樣。留著繞路是因為那是真人
        走的路，不是因為它被驗到了。

        **這句話本身現在有人守**：`check_samepage_refetches` 每一次
        都去量連按同一頁的次數，量到 3 就是這個盲點還在。哪天那裡
        掉到 1，代表 `syncView()` 開始比對 `view` 了，這一段與
        `SAME_PAGES` 要一起改。

    二，**驗不到漢堡。** 跟 `TABS` 那一組同一個盲點：
        `HTMLElement.click()` 對 `hidden` 底下的元素照樣派送事件，
        漢堡哪天壞掉這一組仍然全綠。守那件事的是
        `check_burger_opens_picker`。

    三，**分不出「每輪重發」與「每次切入各一次」。** 時窗只有
        1500 毫秒，`LIVE` 在這一組只斷言到 `REVISIT_MIN_LIVE`。
        那個區別是 `check_poll_page_fetches` 的射程。
    """
    return _count_page_cmds(
        r, f"{pg.zh} ／ 切走再切回來那一下", pg.expect, pg.note,
        REVISIT_MIN_LIVE, "REVISIT_PAGES",
        less="`{cmd}` 只在第一次切入發了，切回來那一下沒有 —— "
             "`syncView()` 的清快取那一行失效了，使用者"
             "切回來看到的是上一次的資料，而且沒有提示",
        more="`{cmd}` 發得比量到的多，快取政策被動過而"
             "REVISIT_PAGES 這張表沒跟著改")


# --------------------------------------------- 連按同一頁，中間沒切走

# 這一組跟上面那一組是同一個實驗的兩半，**唯一的差別是中間那一下
# 按哪一頁**：那一組按 A、B、A，這一組按 A、A、A。
#
# 為什麼要有這一半：上面那一組寫著一個盲點 ——「驗不到切走過」。
# 那句話 2026-09-17 是靠一次手動實測得來的，實測完就散掉了，
# 沒有任何東西守著它。**這一組把那句話變成每一次都會重量的數字。**
#
# 兩組合起來才分得出「切走過」這一維：
#
# | `syncView()` 看不看 `view` 有沒有變 | 切走再切回來 | 連按同一頁 |
# |---|---|---|
# | 不看（現況） | 2 | 3 |
# | 看（哪天有人加了 early return） | 2 | 1 |
#
# 所以這一組掉到 1 的那一天，**不是壞掉**，是上面那一組的射程
# 從「`syncView()` 第二次跑會重抓」變成「切走再切回來會重抓」。
# 那時候要一起改的是 `SAME_PAGES` 這張表與
# `check_revisit_refetches` 的盲點一。紅燈訊息裡直接寫著這件事。


def samepage_clicks(view: str) -> tuple[str, ...]:
    """漢堡、A、漢堡、A、漢堡、A。六下，全部同一頁。

    **下數、間隔、傾印時刻跟 `revisit_clicks()` 完全一樣**，
    差的只有中間那一下按的是哪一頁。控制變因只留一個，
    兩組的數字才能直接比 —— 下數不同的話，多出來的那幾百毫秒
    會讓每輪重發的那些指令堆得不一樣多，而那跟要問的事無關。
    """
    return ("#burgerBtn", '.vw[data-view="%s"]' % view) * 3


# 連按同一頁三次，那三下各發了什麼。
SamePage = namedtuple("SamePage", "view zh expect note")

# **這張表的每一格都是 2026-09-17 開瀏覽器量出來的**，不是從
# `REVISIT_PAGES` 推的。推的話，哪天推導的前提不成立，
# 這張表會跟著錯，而且錯得很像對的。
#
# 兩張表的關係由 `test_這張表跟切走再切回來那張表只差自己那一個指令`
# 釘住：同一頁比對下來只准差一個鍵、剛好差 1。哪天兩張表分歧，
# 那一條會紅 —— 這一組真正的價值在「跟那一組比」，比不了就沒有價值。
SAME_PAGES = (
    SamePage("work", "在做什麼", {"spec_reading": 1, "work": 3},
             "三次切入各抓一次（`syncView()` 不看 `view` 有沒有變）"),
    SamePage("feat", "功能", {"spec_reading": 1, "features": 3},
             "三次切入各抓一次（`syncView()` 不看 `view` 有沒有變）"),
    SamePage("audit", "自我審計", {"spec_reading": 1, "audit": 3},
             "三次切入各抓一次（`syncView()` 不看 `view` 有沒有變）"),
    SamePage("machine", "這台機器", {"spec_reading": 1, "machine": 3},
             "三次切入各抓一次（`syncView()` 不看 `view` 有沒有變）"),
    # 這一頁的 4 是載入那一次加三次切入。下半那兩個本來就每輪重發。
    SamePage("spec", "讀文件",
             {"spec_reading": 4, "block_reading": LIVE,
              "sufficiency": LIVE},
             "載入一次加三次切入（`syncView()` 不看 `view` 有沒有變）；"
             "下半那兩個本來就每輪重發"),
)


def check_samepage_refetches(r: Render, pg: SamePage) -> list[Finding]:
    """連按同一頁三次，那三下是不是每一下都回頭問後端。

    **這一條不是在守一個功能，是在守一句話的有效期限。**
    `check_revisit_refetches` 的盲點一說「那一組驗不到切走過」，
    理由是 `syncView()` 不比對 `view`。那個理由哪天不成立了，
    上面那一組的射程就變了，而在這一條出現之前，沒有任何東西
    會在那一天紅。

    量到的現況：三次切入各抓一次（`spec` 那一頁是載入加三次）。

    **這一組驗不到的兩件，跟上面那一組共用：**

    一，**驗不到漢堡**。`HTMLElement.click()` 對 `hidden` 底下的
        元素照樣派送事件，守那件事的是 `check_burger_opens_picker`。

    二，**分不出「每輪重發」與「每次切入各一次」**。時窗一樣只有
        1500 毫秒，`LIVE` 在這一組同樣只斷言到 `REVISIT_MIN_LIVE`。

    **還有一件是這一組自己的：它證明不了「使用者看得到新資料」。**
    它數的是發了幾次指令，不是畫面上那一格換了沒有。
    多發一次而畫面沒換，這一組照樣綠。
    """
    return _count_page_cmds(
        r, f"{pg.zh} ／ 連按同一頁三次", pg.expect, pg.note,
        REVISIT_MIN_LIVE, "SAME_PAGES",
        less="`{cmd}` 發得比量到的少 —— **這不一定是壞掉**。"
             "`syncView()` 如果開始比對 `view` 有沒有變，這裡本來"
             "就會掉到 1，而那代表『切走再切回來』那一組從此真的"
             "驗到了切走過。那一天要一起改的是 SAME_PAGES 這張表與"
             "`check_revisit_refetches` 的盲點一。"
             "`syncView()` 沒被動過的話，那就是清快取那一行失效了",
        more="`{cmd}` 發得比量到的多，快取政策被動過而"
             "SAME_PAGES 這張表沒跟著改")


POLL_CHECKS = (
    check_no_fatal_banner,
    check_no_console_errors,
    check_poll_loop_really_repeats,
    check_poll_repaints_from_cache,
)


CHECKS = (
    check_no_fatal_banner,
    check_no_console_errors,
    check_no_placeholder_left,
    check_temperature,
    check_progress_三軸,
    check_tree_drew_nodes,
    check_footer_counts,
    check_rescue_never_guesses,
)

# 這一組要先按一下才照得到，所以跟上面那組分開跑（兩次 Chrome）。
#
# **不合成一組。** 合起來的話，展開那一下失敗會讓上面那八條
# 也一起變紅，而那八條跟展開沒有關係 —— 症狀跟原因差一層，
# 正是 `check_no_fatal_banner` 那一輪學到的同一件事。
EXPANDED_CHECKS = (
    check_no_fatal_banner,
    check_no_console_errors,
    check_expanded_opened,
    check_expanded_row_counts,
    check_blast_header_counts,
    check_blast_cache_badge,
)


def run_all(r: Render, checks=CHECKS) -> list[Finding]:
    out: list[Finding] = []
    for fn in checks:
        out.extend(fn(r))
    return out


def main(argv: list[str]) -> int:
    session = ""
    if "--session" in argv:
        session = argv[argv.index("--session") + 1]
    keep = "--keep" in argv
    try:
        r = render(session=session)
    except CannotRun as e:
        print(f"驗不了：{e}")
        print("這不是通過。回傳碼 2 跟 0 分開就是為了這件事。")
        return 2
    findings = run_all(r)
    print(f"DOM {len(r.dom)} 位元組，console {len(r.console)} 行，"
          f"檢查 {len(CHECKS)} 組")
    if keep:
        print(f"暫存目錄留著：{r.outdir}")
    else:
        shutil.rmtree(r.outdir, ignore_errors=True)

    # 第二次：按一下 `#vWhy`，照展開之後那四格。
    #
    # **開第二次瀏覽器，不是在同一張快照上再看一次。** 展開是一次
    # 狀態轉換，同一張 DOM 上沒有「展開前」跟「展開後」兩種樣子。
    exp_n = 0
    try:
        r2 = render(session=session, clicks=EXPANDED_CLICKS)
    except CannotRun as e:
        print(f"展開那一組驗不了：{e}")
        print("這不是通過。")
        return 2
    exp = run_all(r2, EXPANDED_CHECKS)
    exp_n = len(EXPANDED_CHECKS)
    print(f"展開後 DOM {len(r2.dom)} 位元組，console {len(r2.console)} 行，"
          f"檢查 {exp_n} 組（按了 {'、'.join(EXPANDED_CLICKS)}）")
    if keep:
        print(f"展開那一份留著：{r2.outdir}")
    else:
        shutil.rmtree(r2.outdir, ignore_errors=True)
    findings = findings + exp

    # 第三次起：漢堡一下，看面板開不開。
    #
    # **單獨一次，不跟分頁那幾次合。** 分頁那幾次按的是兩下，
    # 而第二下對 `hidden` 底下的元素照樣有效（實測），所以漢堡
    # 壞掉在那幾次裡是看不見的。這一次只按漢堡就是為了看見它。
    try:
        rb = render(session=session, clicks=("#burgerBtn",))
    except CannotRun as e:
        print(f"漢堡那一下驗不了：{e}")
        print("這不是通過。")
        return 2
    bg = check_no_fatal_banner(rb) + check_burger_opens_picker(rb)
    print(f"漢堡按下去　DOM {len(rb.dom)} 位元組，console {len(rb.console)} 行")
    if keep:
        print(f"漢堡那一份留著：{rb.outdir}")
    else:
        shutil.rmtree(rb.outdir, ignore_errors=True)
    findings = findings + bg

    # 再來每個分頁各一次瀏覽器。
    #
    # **一頁一次，不共用。** 換分頁是一次狀態轉換，同一張 DOM 上
    # 沒有七頁的樣子；而且 `syncView()` 每次都把上一頁整個清掉
    # （`app.js:2295` 那幾支第一行都是 `lane.textContent = ""`）。
    for tab in TABS:
        try:
            rt = render(session=session, clicks=tab_clicks(tab.view))
        except CannotRun as e:
            print(f"分頁 {tab.zh} 驗不了：{e}")
            print("這不是通過。")
            return 2
        got = (check_no_fatal_banner(rt) + check_no_console_errors(rt) +
               check_tab_switched(rt, tab) + check_tab_values(rt, tab))
        print(f"分頁 {tab.zh}（{tab.view}）　DOM {len(rt.dom)} 位元組，"
              f"console {len(rt.console)} 行，{len(tab.probes)} 格")
        if keep:
            print(f"  留著：{rt.outdir}")
        else:
            shutil.rmtree(rt.outdir, ignore_errors=True)
        findings = findings + got

    # 最後一次：切到「在做什麼」，按任務卡上第一顆動作鈕的第一下。
    #
    # **這一次要開觀察器。** 這一組問的是「第一下有沒有把指令發出去」，
    # 那是 JS 層的事實，DOM 上看不到 —— 畫面上沒有結果，也可能是
    # 指令發了而回傳被吃掉。
    #
    # 這是目前唯一按到第二層的一組。按第二下不在射程內，
    # 理由寫在 `ACT_CLICKS` 上面：那一下會寫帳本。
    try:
        ra = render(session=session, clicks=ACT_CLICKS, spy=True,
                    budget_ms=ACT_BUDGET_MS)
    except CannotRun as e:
        print(f"動作鈕那一下驗不了：{e}")
        print("這不是通過。")
        return 2
    ac = (check_no_fatal_banner(ra) + check_no_console_errors(ra) +
          check_act_arms_not_fires(ra) + check_act_did_not_invoke(ra))
    print(f"動作鈕按第一下　DOM {len(ra.dom)} 位元組，"
          f"console {len(ra.console)} 行，"
          f"指令 {_tag_text(ra.dom, SPY_ID) or '（觀察器沒回話）'}")
    if keep:
        print(f"動作鈕那一份留著：{ra.outdir}")
    else:
        shutil.rmtree(ra.outdir, ignore_errors=True)
    findings = findings + ac

    # 再一次：切到「在做什麼」之後坐著不動，看那幾輪各自做了什麼。
    #
    # **這一次問的不是畫面，是誰畫的。** 上面每一組照的都是一張
    # 靜止的 DOM，而一張 DOM 回答不了「這一格是切分頁那一下畫的，
    # 還是之後某一輪輪詢畫的」—— 兩條路畫出來的 HTML 一模一樣。
    # 指令清單分得出來，所以這一次開觀察器，而且坐得比別組久。
    try:
        rp = render(session=session, clicks=POLL_CLICKS, spy=True,
                    budget_ms=POLL_BUDGET_MS, spy_at_ms=POLL_SPY_AT_MS)
    except CannotRun as e:
        print(f"輪詢那一組驗不了：{e}")
        print("這不是通過。")
        return 2
    pl = run_all(rp, POLL_CHECKS)
    print(f"坐過 {POLL_SPY_AT_MS} 毫秒　DOM {len(rp.dom)} 位元組，"
          f"console {len(rp.console)} 行，"
          f"指令 {_tag_text(rp.dom, SPY_ID) or '（觀察器沒回話）'}")
    if keep:
        print(f"輪詢那一份留著：{rp.outdir}")
    else:
        shutil.rmtree(rp.outdir, ignore_errors=True)
    findings = findings + pl

    # 最後五次：另外五個分頁各自坐著不動，看那幾輪回頭問了後端幾次。
    #
    # **一頁一次瀏覽器，五次。** 不能在同一次裡依序切五頁：
    # `syncView()` 每次切都會清掉那一頁的快取（`app.js:3072`），
    # 而這一組問的正是「不切走的話會不會重抓」。切過去再切回來
    # 量到的是切分頁那條路，不是輪詢那條路。
    #
    # 這一組每次都跑 `check_tab_switched`，理由跟 `_spy_cmds` 空清單
    # 那一條一樣：那一下沒按到的話，畫面停在預設頁，而底下每一條
    # 「那個指令 0 次」都會答對 —— 整組假綠。
    for pg in POLL_PAGES:
        tb = _tab_of(pg.view)
        if tb is None:
            findings.append(Finding(
                where=f"{pg.zh}（{pg.view}）",
                symptom="POLL_PAGES 這張表列了一個 TABS 裡沒有的分頁，"
                        "是這支工具自己的表寫錯了",
                expected=f"TABS 裡有 view={pg.view}",
                actual="沒有"))
            continue
        try:
            rq = render(session=session, clicks=tab_clicks(pg.view), spy=True,
                        budget_ms=POLL_BUDGET_MS, spy_at_ms=POLL_SPY_AT_MS)
        except CannotRun as e:
            print(f"分頁 {pg.zh} 那幾輪驗不了：{e}")
            print("這不是通過。")
            return 2
        qf = (check_no_fatal_banner(rq) + check_no_console_errors(rq) +
              check_tab_switched(rq, tb) +
              check_poll_loop_really_repeats(rq) +
              check_poll_page_fetches(rq, pg))
        print(f"分頁 {pg.zh}（{pg.view}）坐過 {POLL_SPY_AT_MS} 毫秒　"
              f"指令 {_tag_text(rq.dom, SPY_ID) or '（觀察器沒回話）'}")
        if keep:
            print(f"  留著：{rq.outdir}")
        else:
            shutil.rmtree(rq.outdir, ignore_errors=True)
        findings = findings + qf

    # 再五次：每一頁切走再切回來，看第二次切入那一下有沒有重抓。
    #
    # **這一組跟上面那一組按的下數不同，所以不能合併。** 上面按兩下
    # （漢堡、分頁）然後坐著；這一組按六下（漢堡、A、漢堡、繞路、
    # 漢堡、A）然後看那一下。合在一起的話，第二次切入會把
    # 「坐著不動重抓幾次」那個計數推高，兩個問題互相污染。
    #
    # 這一組每次也跑 `check_tab_switched`，理由跟上面那一組一樣：
    # 最後一下沒按到的話畫面停在別頁，而底下每一條「那個指令 N 次」
    # 都可能因為別的原因答對。
    for pg in REVISIT_PAGES:
        tb = _tab_of(pg.view)
        if tb is None:
            findings.append(Finding(
                where=f"{pg.zh}（{pg.view}）",
                symptom="REVISIT_PAGES 這張表列了一個 TABS 裡沒有的分頁，"
                        "是這支工具自己的表寫錯了",
                expected=f"TABS 裡有 view={pg.view}",
                actual="沒有"))
            continue
        try:
            rv = render(session=session, clicks=revisit_clicks(pg.view),
                        spy=True, budget_ms=REVISIT_BUDGET_MS,
                        spy_at_ms=REVISIT_SPY_AT_MS)
        except CannotRun as e:
            print(f"分頁 {pg.zh} 切回來那一下驗不了：{e}")
            print("這不是通過。")
            return 2
        vf = (check_no_fatal_banner(rv) + check_no_console_errors(rv) +
              check_tab_switched(rv, tb) +
              check_revisit_refetches(rv, pg))
        print(f"分頁 {pg.zh}（{pg.view}）切走再切回來　"
              f"指令 {_tag_text(rv.dom, SPY_ID) or '（觀察器沒回話）'}")
        if keep:
            print(f"  留著：{rv.outdir}")
        else:
            shutil.rmtree(rv.outdir, ignore_errors=True)
        findings = findings + vf

    # 再五次：每一頁連按三次都不切走，看那三下是不是每一下都重抓。
    #
    # **這一圈跟上面那一圈按的下數一樣多，時刻也一樣**，差的只有
    # 中間那一下按哪一頁。兩圈的數字要能直接比，控制變因就只能留
    # 那一個。合併不了的理由跟上面那一段一樣：一次瀏覽器只走得了
    # 一條點擊路徑。
    for pg in SAME_PAGES:
        tb = _tab_of(pg.view)
        if tb is None:
            findings.append(Finding(
                where=f"{pg.zh}（{pg.view}）",
                symptom="SAME_PAGES 這張表列了一個 TABS 裡沒有的分頁，"
                        "是這支工具自己的表寫錯了",
                expected=f"TABS 裡有 view={pg.view}",
                actual="沒有"))
            continue
        try:
            rs = render(session=session, clicks=samepage_clicks(pg.view),
                        spy=True, budget_ms=REVISIT_BUDGET_MS,
                        spy_at_ms=REVISIT_SPY_AT_MS)
        except CannotRun as e:
            print(f"分頁 {pg.zh} 連按同一頁那三下驗不了：{e}")
            print("這不是通過。")
            return 2
        sf = (check_no_fatal_banner(rs) + check_no_console_errors(rs) +
              check_tab_switched(rs, tb) +
              check_samepage_refetches(rs, pg))
        print(f"分頁 {pg.zh}（{pg.view}）連按三次沒切走　"
              f"指令 {_tag_text(rs.dom, SPY_ID) or '（觀察器沒回話）'}")
        if keep:
            print(f"  留著：{rs.outdir}")
        else:
            shutil.rmtree(rs.outdir, ignore_errors=True)
        findings = findings + sf

    if not findings:
        print("畫出來的東西跟資料對得上。")
        print("注意這句話的範圍：預設那一頁、展開那四格、漢堡、"
              f"{len(TABS)} 個分頁的表頭與列數，"
              "任務卡動作鈕的第一下，"
              "輪詢那一條路在瀏覽器裡真的重跑，"
              f"以及 {len(TABS)} 個分頁坐著不動的時候，"
              "那幾輪各自回頭問了後端幾次（哪幾個指令從快取重畫、"
              "哪幾個每輪重抓，每一個都有數字）。"
              f"另外 {len(REVISIT_PAGES)} 頁切走再切回來，"
              "那一下有沒有真的回頭問後端（清快取那幾行的效力），"
              f"以及同樣 {len(SAME_PAGES)} 頁連按三次都不切走 —— "
              "兩組合起來才分得出「切走過」那一維，"
              "現在量到的是 `syncView()` 不看 `view` 有沒有變。"
              "DOM 層、Tauri 是假的、動作鈕的第二下沒驗（那一下會寫帳本）、"
              "看的是 DOM 不是像素。")
        return 0
    print(f"\n對不上 {len(findings)} 條：\n")
    for f in findings:
        print(f)
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
