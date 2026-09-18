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

二，**這支看得到的是「載入完」加漢堡那一下。** `--dump-dom`
本身是載入完成之後照一張，沒有點擊。`clicks=` 往那份暫存頁面
尾巴加一段 `document.querySelector(sel).click()`，
Chrome 照相之前先按下去。

**為什麼這樣算是使用者真的走的那條路。** 按的是真的那個元素，
事件走的是掛在它身上的 listener，由它自己去做該做的事 ——
**這支沒有直接呼叫任何一個 render 函式**。
直接呼叫的話驗到的是函式，不是那一下按了會發生什麼。

**它跟真人按下去差在哪，寫出來免得被讀成「按鍵全驗過了」：**
`isTrusted` 是 false（`app.js` 一處都沒有讀它，實測 grep 0 筆，
所以這一刻沒有差別，但哪天有人讀了就有）；沒有 hover、focus-visible
這些只有真的指標裝置才會有的狀態；而且只按得到「按一下就有反應」
這種一步的東西，要先輸入再按的流程不在射程內。

【2026-09-18 砍到剩三個,這一段是縮小的紀錄不是待辦】
先前這支還驗展開那四格(Blast、Identity、Workflow、Probe)、
五個分頁的表頭與列數、任務卡動作鈕的第一下,以及三圈量快取行為的
(坐著不動重抓幾次 / 切走再切回來 / 連按同一頁)。那些畫面整批退場,
檢查跟著退場 —— 2,335 行砍到 865 行。

**留下來的射程要照實講,不要照舊印象講**:預設那一頁(沒有炸掉、
console 乾淨、佔位字換掉了、樹真的畫出節點、頁腳數字對、
退不回去的時候不猜輪號),加上漢堡按下去面板真的打開。

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

    # 借的人是誰，在借之前就要決定。`outdir` 是呼叫端給的，那一份
    # 不是我借的，不准收；沒給的時候才是我自己去借的。
    #
    # 2026-09-18 加這一段。在這之前，底下五條 raise 路徑
    #（harness 產不出頁面、沒寫出 index.html、Chrome 逾時、
    # Chrome 非零回傳、空 DOM）每走一條就留一個目錄在暫存區：
    # 呼叫端收的方式是 `shutil.rmtree(r.outdir)`，而那些路徑上
    # `r` 根本不存在，所以那幾條上沒有任何人收得到。
    # 當天實測暫存區有 188 個 `forseti-render-*`，130MB。
    mine = outdir is None
    # 成功回傳 = 所有權交給呼叫端（它自己 rmtree `r.outdir`），
    # 那一條路上不能收，收了呼叫端拿到的是一個空目錄。
    handed = False
    out = outdir or Path(tempfile.mkdtemp(prefix="forseti-render-"))
    try:
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
        handed = True
        return Render(dom=r.stdout, console=console, fixture=fixture, outdir=out)
    finally:
        if mine and not handed:
            shutil.rmtree(out, ignore_errors=True)


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


#: 漢堡打開之後該有幾顆分頁按鈕。
#:
#: **寫死,不從 `index.html` 數。** 從 HTML 數的話,少一顆的同時
#: 期望值也跟著少一顆,這條檢查會永遠綠 —— 那正是它要防的那件事。
#:
#: 【2026-09-18 砍到剩三個】原本是 `len(TABS) + 1` 等於七顆
#: (六個分頁加 tree)。在做什麼 / 讀文件 / 這台機器 / 功能 /
#: 自我審計那五頁退場,剩對話與需要注意兩顆。
VIEW_BUTTONS = 2


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
            symptom="找不到那個面板，分頁跟 session 清單全部沒有入口",
            expected="DOM 裡有 #picker", actual="沒有")]
    if "hidden" in m.group(1):
        return [Finding(
            where="漢堡",
            symptom="按了左上角那顆漢堡，選單沒有打開 —— "
                    "分頁跟 session 清單在畫面上按不到",
            expected="#picker 的 hidden 拿掉",
            actual="還是 hidden")]
    n = _count_class(_id_html(dom, "picker") or "", "vw")
    if n != VIEW_BUTTONS:
        return [Finding(
            where="漢堡",
            symptom="選單打開了，但裡面的分頁數量不對",
            expected=f"{VIEW_BUTTONS} 顆 .vw", actual=f"{n} 顆")]
    return []


# ------------------------------------------------- 輪詢那一條路（誰畫的）

# ------------------------------------------ 另外五頁：誰畫的（同一個問題）

# ------------------------------------------------ 第二次切進同一頁

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


CHECKS = (
    check_no_fatal_banner,
    check_no_console_errors,
    check_no_placeholder_left,
    check_tree_drew_nodes,
    check_footer_counts,
    check_rescue_never_guesses,
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

    # 第二次：漢堡一下，看面板開不開。
    #
    # **單獨開一次瀏覽器,不在上面那張快照上再看一次。**
    # 按下去是一次狀態轉換,同一張 DOM 上沒有「按之前」跟
    # 「按之後」兩種樣子。
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

    if not findings:
        print("畫出來的東西跟資料對得上。")
        # 【2026-09-18 砍到剩三個】這句話涵蓋的範圍縮小了很多,
        # 寫在這裡是因為「對得上」這三個字本身不會變,
        # 而它背後驗過的東西變了 —— 照著舊印象讀它就是讀成
        # 一句比實際強的話,那正是這支工具存在要防的事。
        print("注意這句話的範圍：預設那一頁,加上漢堡按下去那一下。"
              "展開那四格、五個分頁、任務卡動作鈕、"
              "以及那三圈量快取行為的,連同它們驗的畫面一起退場了。"
              "DOM 層、Tauri 是假的、看的是 DOM 不是像素。")
        return 0
    print(f"\n對不上 {len(findings)} 條：\n")
    for f in findings:
        print(f)
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
