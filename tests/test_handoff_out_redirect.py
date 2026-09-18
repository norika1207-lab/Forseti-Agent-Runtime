"""跑測試的時候，交接檔寫到哪裡去。

**2026-09-18 加這一支，修的是上一輪自己寫下的那個缺口。**
原話在 `AUTO_CONTINUE_LOG.md`：

    正本 `.forseti/NEXT.md` 這一輪被測試用合成資料覆蓋過。收尾的
    時候讀到裡面寫「工作區跟 HEAD 不一致的：0 個」與「checkpoint
    2 個」，而實測工作區有二十幾個檔案有改動、這條 session 的
    checkpoint 是 0 個。⋯⋯這一輪的處置只是等節流窗過去之後重寫
    一次，**沒有修根因**。

## 這跟「測試會動到 mtime」不是同一題

`tests/conftest.py` 的模組說明早就記著「測試會寫正本 NEXT.md」，
但記的是 **mtime 會動**。mtime 動是雜訊 —— 接手的人看到的內容
還是真的，只是時間戳不好看。

內容被合成資料取代是另一回事：交接檔對接手的人**說假話**，
而它是停機之後唯一有人看的東西。同一個現象兩種嚴重程度，
上一輪記下的是輕的那一種，於是重的那一種沒有人去修。

## 守的是機制，不是「這一輪正本有沒有被動」

「正本這一輪一次都沒被動」這句話守不住 —— 桌面 App 跟 Stop hook
都寫得到正本，而它們在不在跑不是這一組測試決定的。拿那句話當
斷言會紅在跟測試無關的地方（`conftest` 的模組說明裡「它分不出
寫入者」那一段就是這個形狀咬過一次）。

所以這一支守的是**這條路徑自己**：
`handoff.OUT` 這一刻指到哪、`write()` 不帶 path 的時候落在哪、
以及重導失效的時候有沒有人會發現。每一條都自足，
不依賴這一輪有沒有別的測試走到寫入，也不依賴外面有誰在跑。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import handoff as HO  # noqa: E402

CANONICAL = ROOT / ".forseti" / "NEXT.md"


def _state() -> dict:
    """一份形狀正確的假交接狀態。

    `write()` 會擋形狀不對的東西（那是它存在的理由之一），
    所以這裡得給滿 `REQUIRED_KEYS`，不然量到的會是「被形狀檢查擋下」
    而不是「寫到哪裡去」—— 兩者的回傳都是 `ok: False`。
    """
    s: dict = {k: [] for k in HO.REQUIRED_KEYS}
    s.update({"at": time.time(), "goal": "這一條測試用的假狀態", "n": 1})
    return s


# ── resolve_out() 自己 ────────────────────────────────────────────

def test_沒設環境變數的時候回正本():
    """拿不準就回正本。導錯地方的後果是交接檔沒人在寫而且沒人會發現。"""
    assert HO.resolve_out({}) == HO.DEFAULT_OUT
    assert HO.DEFAULT_OUT == CANONICAL


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_設成空的等於沒設(raw):
    """空字串不是一個路徑。`Path("")` 是 `.`，寫下去會變成寫目錄。"""
    assert HO.resolve_out({HO.OUT_ENV: raw}) == HO.DEFAULT_OUT


def test_設了就用設的(tmp_path):
    want = tmp_path / "x" / "NEXT.md"
    assert HO.resolve_out({HO.OUT_ENV: str(want)}) == want


def test_波浪號會展開():
    got = HO.resolve_out({HO.OUT_ENV: "~/forseti-handoff-test/NEXT.md"})
    assert not str(got).startswith("~"), f"沒展開：{got}"
    assert got.is_absolute()


# ── 這一輪實際生效了沒有 ──────────────────────────────────────────

def test_跑測試的時候OUT不是正本():
    """**這一條紅掉代表重導沒生效，而不是重導壞了。**

    最可能的成因有兩個：`conftest.py` 那一段沒跑到（import 順序變了），
    或者有人在外面把 `FORSETI_HANDOFF_OUT` 設成正本。後者是合法的
    （`setdefault` 刻意讓得出去），所以失敗訊息要把實際值印出來，
    讓讀的人分得出是哪一種。
    """
    assert HO.OUT != CANONICAL, (
        f"交接檔的寫入目標此刻就是正本：{HO.OUT}　"
        f"環境變數 {HO.OUT_ENV} 的值是 "
        f"{__import__('os').environ.get(HO.OUT_ENV)!r}"
    )


def test_不帶path的write落在重導目標而不是正本():
    """**這是根因那條路徑的直接重現。**

    `desktop_api._write_handoff()` 呼叫 `should_write()` 與 `write()`
    兩邊都不帶 path（2026-09-18 實測攔截，兩次都是 `<default>`），
    所以它寫到哪裡完全由這個模組全域決定。這一條走的就是那個形狀。

    正本用 (mtime_ns, 大小) 前後比對。**比對不到不等於沒人動過** ——
    別的程序同時在寫的話這裡也會紅，那種紅是真的有東西寫了正本，
    只是寫的人不是我。訊息裡不預設是哪一種。

    ## 寫之前先擋，不是寫下去才發現

    **2026-09-18 這一條自己咬了我一次。** 第一版是直接呼叫
    `HO.write(..., force=True)` 然後才比對正本 —— 於是在反向驗證
    （故意拿掉 conftest 那一段）的時候，`HO.OUT` 回到正本，
    這一條就**真的把正本覆蓋成一份 goal 寫著「這一條測試用的假狀態」
    的殘缺交接檔**（實測 1315 位元組，正常九千上下）。斷言確實紅了，
    可是檔案已經寫下去了 —— 紅的是「我發現我剛做了那件事」。

    一條在驗「不准寫到正本」的測試，自己不准有寫到正本的路徑。
    所以前置條件擋在 `write()` 之前：目標是正本就直接失敗，不寫。
    `force=True` 讓這件事更嚴重 —— 它連節流那層保護都繞過去。
    """
    assert HO.OUT != CANONICAL, (
        "前置條件不成立：寫入目標此刻就是正本，這一條不會往下寫。"
        f"　OUT={HO.OUT}"
    )

    before = CANONICAL.stat() if CANONICAL.exists() else None

    res = HO.write(_state(), force=True)

    assert res.get("ok") is True, f"沒寫成：{res}"
    assert Path(res["path"]) == HO.OUT
    assert Path(res["path"]) != CANONICAL
    assert HO.OUT.exists() and HO.OUT.stat().st_size > 0, "重導目標沒有東西"

    after = CANONICAL.stat() if CANONICAL.exists() else None
    if before is None:
        assert after is None, "正本本來不存在，現在有了"
    else:
        assert after is not None, "正本不見了"
        assert (before.st_mtime_ns, before.st_size) == \
               (after.st_mtime_ns, after.st_size), (
            "正本在這一條測試期間變了。要嘛重導沒接住，"
            "要嘛同時有別的程序在寫正本"
        )


def test_上游那兩個呼叫點不帶path():
    """釘住 `desktop_api` 那一端。

    上面那一條證明的是「不帶 path 會落在重導目標」，前提是上游真的
    不帶 path。哪天有人在 `_write_handoff()` 補上 `path=handoff.OUT`
    之類的東西，上面那一條照樣綠，而重導會從那一刻開始失效 ——
    因為那個表達式在 import 之後才求值，跟這裡守的不是同一個時刻。
    """
    src = (ROOT / "apps" / "forseti-cli" / "desktop_api.py").read_text(
        encoding="utf-8")
    assert "HO.should_write()" in src, "呼叫點不再是不帶 path 的那個形狀"
    i = src.index("def _write_handoff(")
    body = src[i:]
    assert "HO.write(" in body, "找不到 write 的呼叫點"

    # **括號配對切到呼叫結束，不是切固定長度。** 第一版切 400 個字元，
    # 而那個呼叫傳的 dict 本身就七百多字元 —— 切點落在 dict 中間，
    # 於是加在最後面的 `path=` 剛好在守不到的位置。一個看起來在守、
    # 實際上守不到要防的那一種寫法的斷言。
    start = body.index("HO.write(") + len("HO.write(")
    depth, end = 1, start
    while depth and end < len(body):
        depth += {"(": 1, ")": -1}.get(body[end], 0)
        end += 1
    assert depth == 0, "括號沒配對完，切不出完整的呼叫"
    call = body[start:end]

    # dict 裡的鍵是 `"path":` 不是 `path=`，所以這個字串比對分得開
    # 「傳了 path 參數」跟「dict 裡有 path 這個鍵」。
    assert "path=" not in call, (
        f"寫入點帶了 path，重導會從那一刻起失效：⋯{call[-160:]}")


def test_conftest那一段用的是setdefault():
    """外面設了就聽外面的。

    想量「測試到底會不會寫正本」的人，把 `FORSETI_HANDOFF_OUT` 設成
    正本路徑就量得回原本的行為。寫死成指派的話那條路就沒了，
    而這一組守門本身也會變成不可否證的。
    """
    src = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'os.environ.setdefault("FORSETI_HANDOFF_OUT"' in src
