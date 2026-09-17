"""app.js 裡不准有「被呼叫但沒定義」的自訂函式。

這個 bug 2026-09-15 到 09-16 之間發生兩次，兩次都讓整個畫面變成
一行紅字的錯誤訊息，而 `node --check` 完全抓不到（語法是合法的）：

一，`renderWork()` 在兩個地方被呼叫，但整個專案沒有這個函式的定義。
    功能表上有「在做什麼」這一頁，點下去直接 ReferenceError。

二，重寫 `drawDrift` 時用「從 A 到 B 整段替換」，把夾在中間的
    `loadOffsets` 跟 `OFFSET_BY_N` 一起刪掉，而 `renderTree` 還在用它們。

**兩次都是部署之後才發現，而 deploy.sh 只驗視窗數。**
視窗開得出來但整頁是錯誤訊息，它照樣回報「部署完成」。
所以防線要往前移到測試。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "desktop" / "ui" / "app.js"

#: 只檢查專案自己命名的函式。瀏覽器內建與第三方不在管轄範圍，
#: 把它們列進來只會製造噪音，而噪音會讓人關掉這個檢查。
OURS = ("render", "draw", "load", "toggle", "pack", "open", "close", "sync")

_DEF = re.compile(
    r"^(?:async\s+)?(?:function|const|let|var)\s+([A-Za-z_$][\w$]*)", re.M)
_ASSIGN = re.compile(r"^\s*([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function|\()", re.M)
#: 前面有點號的是方法呼叫（el.closest()、classList.toggle()），
#: 那些歸 DOM 管不歸我們管。不排除的話這個檢查會充滿噪音，
#: 而充滿噪音的檢查最後一定會被關掉。
_CALL = re.compile(r"(?<![.\w$])([a-z][A-Za-z0-9_$]*)\s*\(")


def _source() -> str:
    return APP.read_text(encoding="utf-8")


#: 函式的參數也是「已定義」。漏掉的話，一個叫 `render` 的參數
#: 會被誤報成未定義的全域函式 —— 而誤報會讓人關掉這個檢查。
_PARAMS = re.compile(r"(?:function\s*[\w$]*\s*|\()\s*([^()]*?)\s*\)\s*(?:=>|\{)")


def _defined(src: str) -> set:
    out = set(_DEF.findall(src)) | set(_ASSIGN.findall(src))
    for group in _PARAMS.findall(src):
        for raw in group.split(","):
            name = raw.strip().split("=")[0].strip().lstrip(".")
            if re.fullmatch(r"[A-Za-z_$][\w$]*", name or ""):
                out.add(name)
    return out


def _ours(name: str) -> bool:
    return any(name.startswith(p) for p in OURS)


@pytest.mark.skipif(not APP.exists(), reason="找不到 app.js")
def test_沒有被呼叫但沒定義的自訂函式():
    src = _source()
    defined = _defined(src)
    missing = sorted({n for n in _CALL.findall(src)
                      if _ours(n) and n not in defined})
    assert missing == [], (
        f"這些函式被呼叫但沒有定義，畫面會整頁變成 ReferenceError：{missing}")


@pytest.mark.skipif(not APP.exists(), reason="找不到 app.js")
def test_這個檢查本身要抓得到問題():
    """一個永遠回 OK 的檢查等於沒有檢查（HANDOVER_FAILURE §17.4）。

    餵一段刻意壞掉的程式碼進去，抓不到就是這個測試死了。
    """
    bad = "function a(){ renderNotExist(); }"
    missing = sorted({n for n in _CALL.findall(bad)
                      if _ours(n) and n not in _defined(bad)})
    assert missing == ["renderNotExist"]


@pytest.mark.skipif(not APP.exists(), reason="找不到 app.js")
def test_每個檢視都要有對應的渲染函式():
    """`syncView` 會照 view 分派。分派得出去而函式不存在，就是那個 bug。"""
    src = _source()
    defined = _defined(src)
    views = set(re.findall(r'view === "(\w+)"', src))
    assert views, "找不到任何 view 分派，這個測試的前提壞了"
    for v in sorted(views):
        fn = "render" + v[0].upper() + v[1:]
        if fn in src:
            assert fn in defined, f"{v} 這一頁呼叫 {fn}，但它沒有定義"
