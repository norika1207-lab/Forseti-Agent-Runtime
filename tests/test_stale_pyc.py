"""這一輪跑的，是不是磁碟上那一版程式碼。2026-09-17

## 為什麼要有這一組

NewDrive 是 exFAT，mtime 解析度 2 秒。Python 判斷 pyc 過期沒看的是
「原始碼的 mtime 與大小」，兩個都對得上就用快取。於是同一個 2 秒窗裡
「先 import 過、再改檔、而改完大小不變」會讓舊 bytecode 被判成有效。

**2026-09-17 實測真的發生。** 改完 `contract.py` 之後兩條測試紅，
而磁碟上的原始碼是對的 —— `_recovery_status.__code__.co_consts` 裡
沒有新加的那幾個常數。pyc header 記的 mtime 與 size 跟原始檔一模一樣。
刪掉那個 pyc 之後同樣兩條變綠，程式碼一個字都沒改。

這件事的嚴重性不在那兩條測試，在於**它讓「全套 N 綠」這句話失去
根據** —— 綠的可能是上一版。這個專案的 `deploy.sh` 守門、
ROADMAP 每一節結尾的測試數，全部站在那個前提上。

## 這一組守什麼

一，`_pyc_is_stale()` 抓得到那個組合（mtime 與 size 都一致而內容不同）。
二，一致的時候不准誤判成陳舊 —— 誤判的代價是每跑一次全套重編一次。
三，`conftest` 被 import 的當下就跑過一次，不是留一支沒人叫的函式。
"""

from __future__ import annotations

import importlib.util
import os
import py_compile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

import conftest as CF  # noqa: E402


def _make(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "假模組.py"
    p.write_text(body, encoding="utf-8")
    return p


def test_內容變了而mtime與size不變_抓得到(tmp_path):
    src = _make(tmp_path, "值 = 1\n")
    py_compile.compile(str(src), doraise=True)
    st = os.stat(src)

    # 改內容，長度一樣，然後把 mtime 設回去 —— exFAT 那個窗的等價物。
    src.write_text("值 = 2\n", encoding="utf-8")
    os.utime(src, (st.st_atime, st.st_mtime))
    assert os.stat(src).st_size == st.st_size, "這條測試的前提是大小不變"

    stale = CF._pyc_is_stale(src)
    assert stale is not None, "mtime 與 size 都一致，只有內容不同 —— 正是那個陷阱"
    assert Path(stale).name.startswith("假模組"), stale


def test_沒有變就不准說它舊了(tmp_path):
    src = _make(tmp_path, "值 = 1\n")
    py_compile.compile(str(src), doraise=True)
    assert CF._pyc_is_stale(src) is None, "誤判的代價是每次全套都重編"


def test_沒有pyc就不是舊的(tmp_path):
    src = _make(tmp_path, "值 = 1\n")
    cache = Path(importlib.util.cache_from_source(str(src)))
    if cache.exists():
        cache.unlink()
    assert CF._pyc_is_stale(src) is None


def test_刪掉之後真的不見了(tmp_path):
    src = _make(tmp_path, "值 = 1\n")
    py_compile.compile(str(src), doraise=True)
    st = os.stat(src)
    src.write_text("值 = 2\n", encoding="utf-8")
    os.utime(src, (st.st_atime, st.st_mtime))
    stale = Path(CF._pyc_is_stale(src))
    assert stale.is_file()
    stale.unlink()
    assert CF._pyc_is_stale(src) is None, "刪掉之後就沒有陳舊的那一份了"


def test_conftest載入時就跑過一次():
    """**不是留一支沒人叫的函式。**

    這一支要在任何測試 `import contract` 之前跑完，晚一步就來不及:
    模組一旦載入，刪 pyc 不會換掉記憶體裡那一份。
    """
    assert isinstance(CF.STALE_PYCS, list), "模組層沒有跑過"
    src = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "STALE_PYCS = _drop_stale_pycs()" in src, "模組層那一次呼叫不見了"
    at = src.index("STALE_PYCS = _drop_stale_pycs()")
    assert at < src.index("def pytest_configure"), \
        "要在 hook 之前，不是等 pytest 叫它"
