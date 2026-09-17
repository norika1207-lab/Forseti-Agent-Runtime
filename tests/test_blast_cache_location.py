"""`blast.py` 的快取檔到底寫在哪裡。

**2026-09-17 加這一組，是為了回答上一輪自己留下的那一句。**
上一輪在 `AUTO_CONTINUE_LOG.md` 的原話：

    `blast.py` 的 `_cache_file()` 寫在哪裡，這一輪沒有量。
    臨時 repo 那邊它寫在 repo 底下（測完跟著 box 一起刪），
    真的 repo 那邊寫 `.forseti/cache/`（白名單內）。
    **沒有第三種情況被驗過。**

量了。**第三種情況存在，而且是活的。**

## 量出來的三件事

一，`collect()` 在 `base != REPO` 的時候一個位元組都不寫。
    閘在 `blast.py:458`：`fp = _fingerprint(...) if base == REPO else None`，
    `fp` 是 None 就不進 `_cache_put()`。

二，**`vectors()` 與 `detail()` 沒有那道閘。** `blast.py:615` 與
    `blast.py:838` 是同一行形狀：

        fp = g.get("fp") or _fingerprint(base, python_files(base), g["js_files"]) or ""

    `g["fp"]` 在臨時 repo 是 None，於是走 `or` 那一邊自己補算一個
    **真的**指紋，接著 `_cache_put(base, ...)`（`:750`、`:935`）就把
    `<base>/.forseti/cache/blast.json` 寫出來。

三，**那個快取是活的不是死碼。** 同一個 box 連呼叫兩次，
    第二次 `cached` 是 True，答案從檔案裡撈回來。

## 所以「第三種情況」是什麼

`_cache_file()` 寫的位置**完全由呼叫端的 `root` 決定**，
`vectors()` / `detail()` 收到什麼就寫進什麼底下。
測試裡它剛好是 `tmp_path`，所以跟著 box 一起被清掉，看起來沒事 ——
**「剛好會被清掉」不是「不會寫出去」**，而先前只有前者被觀察到。

## 這一組不改行為，只把行為釘住

`blast.py:613` 與 `:836` 的註解寫著「臨時 repo 那邊 `collect()`
不算指紋，所以這裡自己補一次」—— **這是刻意的，不是疏漏**，
為的是讓臨時 repo 也吃得到快取（`test_blast.py` 幾十條都靠它跑得快）。
所以這裡不加閘、不改政策，只把「三支公開函式對同一件事有兩套做法」
這個事實變成會紅的東西。改政策是設計決定，不是這一輪該自己做的。

## 一個順帶的發現，寫在這裡不是補充是前提

`test_blast.py` 的 `test_不是正本就不寫快取檔` 這個名字比它驗的事**大**：
它只呼叫 `collect()`，而同一個臨時 repo 上 `vectors()` 與 `detail()`
寫的正是它斷言不存在的那個檔。那條測試沒有錯，是名字收不住 ——
**這一組刻意不去改它**，因為改名字會讓 `git log` 上看起來像修了 bug。
下面 `test_不是正本這件事三支函式的答案不一樣` 就是拿來擋這個誤讀的。
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import blast as B  # noqa: E402

BLAST_SRC = ROOT / "apps" / "forseti-cli" / "blast.py"


def _box(tmp_path: Path) -> Path:
    """最小的可跑 repo。

    `src` 用符號連結指回真的那份，**不複製** —— 照
    `tests/test_tempdir_cleanup.py` 既有的做法，不自創一套。
    少了 `src/` 的話 `vectors()` 會在 `blast.py:606` 提早 return
    （`找不到 src/，cost.js 不在`），根本走不到寫快取那一步，
    於是「沒有寫」會被誤讀成「不會寫」。第一次量測就是這樣錯過去的。
    """
    d = tmp_path / "box"
    (d / "apps" / "forseti-cli").mkdir(parents=True)
    (d / "apps" / "forseti-cli" / "a.py").write_text("import b\n", encoding="utf-8")
    (d / "apps" / "forseti-cli" / "b.py").write_text("x = 1\n", encoding="utf-8")
    (d / "src").symlink_to(ROOT / "src")
    return d


def _cache(box: Path) -> Path:
    return box / ".forseti" / "cache" / "blast.json"


def test_不是正本這件事三支函式的答案不一樣(tmp_path):
    """同一個臨時 repo，`collect()` 不寫，另外兩支寫。

    **這一條是這個檔存在的理由。** 只讀 `collect()` 那道
    `base == REPO` 閘，會得到「這個模組不對非正本寫快取」這個結論，
    而那個結論是錯的 —— 2026-09-17 就是這樣錯了一次，
    是實測把它推翻的，不是再讀一次讀出來的。
    """
    box = _box(tmp_path)
    cf = _cache(box)

    g = B.collect(box)
    assert g["fp"] is None, "collect() 對非正本應該算不出指紋（blast.py:458 那道閘）"
    assert not cf.exists(), "collect() 不該對非正本寫快取檔"

    v = B.vectors(root=box)
    assert v.get("has") is True, f"vectors() 沒跑成，後面驗不到東西：{v.get('why')}"
    assert cf.exists(), (
        "vectors() 對非正本**會**寫快取檔，這一條紅代表行為變了。"
        "變成不寫是一個政策改動（blast.py:615 那個 `or _fingerprint` 退路），"
        "要改的話連 blast.py:613 的註解一起改，不是把這條測試刪掉。"
    )
    assert list(json.loads(cf.read_text(encoding="utf-8"))) == ["vectors|8|ALL"]

    B.detail("apps/forseti-cli/b.py", root=box)
    assert sorted(json.loads(cf.read_text(encoding="utf-8"))) == [
        "detail|apps/forseti-cli/b.py", "vectors|8|ALL"]


def test_那個快取是活的不是寫完沒人讀(tmp_path):
    """寫出去的檔第二次真的被撈回來。

    **分「有寫」跟「有用」這兩件事。** 一個寫完沒人讀的檔案是整潔問題，
    一個會被讀回來的檔案是行為 —— 而只有後者說得上「快取的位置
    由呼叫端決定」這句話有後果。
    """
    box = _box(tmp_path)
    assert B.vectors(root=box).get("cached") is False
    assert B.vectors(root=box).get("cached") is True, "第二次沒吃到快取"

    tgt = "apps/forseti-cli/b.py"
    assert B.detail(tgt, root=box).get("cached") is False
    assert B.detail(tgt, root=box).get("cached") is True, "detail 第二次沒吃到快取"


def test_寫非正本的時候不會順手動到正本的快取(tmp_path):
    """`root` 指到哪就寫哪，**不會兩邊都寫**。

    這一條擋的是一個很像樣的改法：有人覺得「快取本來就該集中在正本」，
    把 `_cache_file(base)` 改成 `_cache_file(REPO)`。改完功能全部照跑，
    測試全部照綠 —— 而測試用的臨時 repo 會開始把自己的答案寫進
    真正的 `.forseti/cache/`，然後被下一次真的呼叫吃回去。
    **那是一個安靜的錯誤答案，不是一個當場爆掉的錯誤。**
    """
    real = ROOT / ".forseti" / "cache" / "blast.json"
    before = real.read_bytes() if real.exists() else None

    box = _box(tmp_path)
    B.vectors(root=box)
    B.detail("apps/forseti-cli/b.py", root=box)

    after = real.read_bytes() if real.exists() else None
    assert after == before, (
        "對臨時 repo 呼叫 vectors()/detail() 動到了正本的快取檔。"
        "`_cache_file()` 要從 `base` 長出來，不是從模組層的 REPO 常數。"
    )


def test_cache_file只認參數不認模組層的REPO():
    """原始碼層級，擋掉上一條擋不到的那一半。

    上一條是行為測試，它要 `vectors()` 真的跑得起來（要有 node、
    要有 `src/cost.js`）。**node 不在的機器上它會因為提早 return
    而無聲通過** —— `blast.py:606` 那條路連快取都走不到。
    這一條不跑任何東西，只讀 `_cache_file()` 的語法樹，
    所以它在任何機器上都有效。
    """
    tree = ast.parse(BLAST_SRC.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_cache_file"), None)
    assert fn is not None, "`_cache_file` 不見了，改名的話這一組要跟著改"

    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "base" in names, "`_cache_file` 沒有用到它的 `base` 參數"
    assert "REPO" not in names, (
        "`_cache_file` 裡出現了模組層的 REPO 常數。"
        "它一旦不從 `base` 長出來，臨時 repo 的答案就會寫進正本的快取。"
    )
