"""`blast.py` 寫快取寫不進去的時候，外面看不看得出來。

**2026-09-17 補這一組，是為了結掉一個連續兩輪被順延的項目。**
`AUTO_CONTINUE_LOG.md` 上一輪的原話：

    `_cache_put()` 的 `except OSError: return` 仍然是靜默吞掉。
    上一輪就寫下來了，這一輪順延，理由是先補網比較急 ——
    網瞎著的時候量出來的任何數字都不能用。**連續兩輪順延，記在這裡。**

那個理由這一輪沒了（攔截網 5af 已經補寬），所以先量再做。

## 量出來的（動手改之前，`except OSError: return` 還在的時候）

臨時 repo 的 `.forseti/cache/` chmod 0o500，連呼叫 `vectors()` 兩次：

| | 正常 | 快取目錄唯讀 |
|---|---|---|
| 第一次 `cached` | False | False |
| 第二次 `cached` | **True** | **False** |
| 回傳的鍵數 | 36 | 36（一個都沒少） |
| 兩次答案 | 相同 | 相同 |
| 有沒有欄位講到寫失敗 | — | **沒有** |

**所以「這次剛算，下次會命中」跟「永遠寫不進去，每次都重算」
在呼叫端長得一模一樣。** 分不出來的那兩件事後果相反：
前者是一次成本，後者是每一次都付。

## 這一組不改政策，只改它說不說

寫不進去仍然**不丟例外**、仍然照常回答、答案仍然正確。
把 `except OSError: return` 改成回報之後，行為一個位元組都沒變 ——
變的是回傳的字典多兩欄，而畫面上那一格因此分得出那兩種 False。

改政策（例如寫不進去就報錯、或改寫到別的位置）是設計決定，
不是這一輪該自己做的。

## 刻意不斷言的一件

這一組**不要求 `failed:` 後面是哪一個例外類別**。實測 macOS 上
是 `PermissionError`，但那是平台行為不是這支模組的契約，
釘死它等於把別人的行為寫成自己的規格。只要求它以 `failed:` 開頭。
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import blast as B  # noqa: E402

BLAST_SRC = ROOT / "apps" / "forseti-cli" / "blast.py"


def _box(tmp_path: Path) -> Path:
    """最小的可跑 repo。做法照 `test_blast_cache_location.py`，不自創一套。

    `src` 用符號連結指回真的那份 —— 少了它 `vectors()` 會在
    `blast.py` 那個「找不到 src/」提早 return，連寫快取那一步都走不到，
    於是「沒有寫」會被誤讀成「不會寫」。
    """
    d = tmp_path / "box"
    (d / "apps" / "forseti-cli").mkdir(parents=True)
    (d / "apps" / "forseti-cli" / "a.py").write_text("import b\n", encoding="utf-8")
    (d / "apps" / "forseti-cli" / "b.py").write_text("x = 1\n", encoding="utf-8")
    (d / "src").symlink_to(ROOT / "src")
    return d


def _lock_cache_dir(box: Path) -> bool:
    """把快取目錄變成寫不進去。回傳「真的變成寫不進去了」。

    **root 跑測試的時候 chmod 擋不住任何東西**，那一種情況下
    這個檔案裡靠它的幾條會無聲通過 —— 所以這裡自己驗一次，
    驗不成就讓呼叫端 skip，不讓一條假綠留在報告裡。
    """
    d = box / ".forseti" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o500)
    try:
        (d / "_probe").write_text("x", encoding="utf-8")
    except OSError:
        return True
    (d / "_probe").unlink()
    return False


def test_寫成功回ok(tmp_path):
    box = _box(tmp_path)
    v = B.vectors(root=box)
    assert v.get("has") is True, f"vectors() 沒跑成，後面驗不到東西：{v.get('why')}"
    assert v["cache_write"] == B.CACHE_OK
    assert v["cached"] is False


def test_快取命中的時候是沒有寫入動作不是寫成功(tmp_path):
    """命中那一條路不寫檔，所以不能回 `ok`。

    回 `ok` 的話等於宣稱這一次寫成功了，而那是假的。
    """
    box = _box(tmp_path)
    B.vectors(root=box)
    second = B.vectors(root=box)
    assert second["cached"] is True
    assert second["cache_write"] == B.CACHE_NOT_ATTEMPTED


def test_非正本的collect回skipped而不是ok(tmp_path):
    """本來就不寫 ≠ 寫成功。兩種「沒寫」後果不同，所以不共用一個值。"""
    box = _box(tmp_path)
    c = B.collect(box)
    assert c["fp"] is None
    assert c["cache_write"] == B.CACHE_SKIPPED


def test_寫不進去的時候說得出來而且答案不變(tmp_path):
    """**這一條是這個檔存在的理由。**

    先拿到一份正常情況的答案，再讓快取寫不進去重跑一次，
    要求：一，狀態說得出是 failed；二，除了那幾欄以外**逐欄位相同**。
    第二半擋的是有人「順手」把寫失敗改成回一份殘缺的答案 ——
    那會把一個效能問題變成一個正確性問題。
    """
    (tmp_path / "a").mkdir(exist_ok=True)
    good_box = _box(tmp_path / "a")
    good = B.vectors(root=good_box)
    assert good.get("has") is True

    (tmp_path / "b").mkdir(exist_ok=True)
    bad_box = _box(tmp_path / "b")
    if not _lock_cache_dir(bad_box):
        pytest.skip("這台機器上 chmod 0o500 擋不住寫入（root？），這條驗不到東西")

    bad = B.vectors(root=bad_box)
    assert str(bad["cache_write"]).startswith("failed:"), (
        "快取寫不進去，但回傳的狀態不是 failed。"
        "`_cache_put()` 的 `except OSError` 又變回靜默吞掉了？"
    )
    assert bad["cached"] is False
    assert "重算" in bad["cache_write_why"], "失敗的那句話要講出後果，不是只講狀態"

    skip = {"cache_write", "cache_write_why", "cached"}
    assert {k: v for k, v in bad.items() if k not in skip} == \
           {k: v for k, v in good.items() if k not in skip}, (
        "寫不進去的時候答案跟正常情況不一樣了。"
        "這一支的政策是『寫失敗不算錯誤，照常回答』。")


def test_寫進快取檔的那一份不帶寫入狀態(tmp_path):
    """免得把某一次的寫入狀態凍進檔案，下一次命中讀回來當成此刻的狀態。

    **這一條只走得到 `vectors` 與 `detail` 兩支。** `collect()` 在
    非正本 repo 算不出指紋，根本不寫檔，所以它那一支的順序
    這一條驗不到 —— 驗它的是下面那條讀語法樹的。
    第一版只呼叫 `vectors()`，反向驗證的時候把 `collect()` 的
    賦值搬到寫入之前，這一條照樣綠，才發現它覆蓋不到。
    """
    box = _box(tmp_path)
    B.vectors(root=box)
    B.detail("apps/forseti-cli/b.py", root=box)
    raw = json.loads((box / ".forseti" / "cache" / "blast.json").read_text(encoding="utf-8"))
    assert len(raw) == 2, f"預期 vectors 與 detail 兩個 key，實際 {sorted(raw)}"
    for key, ent in raw.items():
        val = ent.get("val") or {}
        assert "cache_write" not in val, f"`{key}` 把寫入狀態存進快取檔了"
        assert "cache_write_why" not in val, f"`{key}` 把寫入狀態存進快取檔了"


def test_四句話各自講的是各自那件事(tmp_path):
    """**不是只驗四句不一樣。**

    第一版只驗 `len(set(...)) == 4`，而把 `ok` 那句改成失敗的措辭之後
    它照樣綠 —— 因為那句話裡插了狀態字串，四句仍然兩兩不同。
    **兩兩不同不等於各自正確。** 所以這一條改成驗每一句的內容。
    """
    ok = B._cache_write_why(B.CACHE_OK)
    skipped = B._cache_write_why(B.CACHE_SKIPPED)
    not_att = B._cache_write_why(B.CACHE_NOT_ATTEMPTED)
    failed = B._cache_write_why("failed:OSError")

    assert len({ok, skipped, not_att, failed}) == 4, "四種狀態講出同一句話"
    assert "寫成功" in ok and "寫不進去" not in ok
    assert "本來就不寫" in skipped
    assert "命中" in not_att and "沒有寫入" in not_att
    assert "寫不進去" in failed and "重算" in failed


def test_三支函式都是先寫快取才記狀態():
    """順序讀語法樹釘死，因為執行期那一條覆蓋不到 `collect()`。

    賦值跑在 `_cache_put()` 前面的話，那個字典會被連同狀態一起
    序列化進快取檔，下一次命中就讀回一個**上一次的**寫入狀態。
    """
    tree = ast.parse(BLAST_SRC.read_text(encoding="utf-8"))
    for name in ("collect", "vectors", "detail"):
        fn = _fn(name)
        puts = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name) and n.func.id == "_cache_put"]
        assert len(puts) == 1, f"`{name}()` 裡有 {len(puts)} 個 _cache_put，這條沒驗過"
        sets = [n.lineno for n in ast.walk(fn) if isinstance(n, ast.Subscript)
                and isinstance(n.slice, ast.Constant)
                and n.slice.value in ("cache_write", "cache_write_why")
                and isinstance(n.ctx, ast.Store)]
        assert sets, f"`{name}()` 裡沒有把狀態寫進回傳字典"
        assert min(sets) > puts[0], (
            f"`{name}()` 第 {min(sets)} 行在第 {puts[0]} 行的 _cache_put 之前"
            "就把狀態寫進字典了，那個狀態會被存進快取檔。")


# ---------------------------------------------------------------- 原始碼層級

def _fn(name: str) -> ast.FunctionDef:
    tree = ast.parse(BLAST_SRC.read_text(encoding="utf-8"))
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == name), None)
    assert fn is not None, f"`{name}` 不見了，改名的話這一組要跟著改"
    return fn


def test_cache_put沒有任何一條路是不帶值的return():
    """`return` 不帶值 = 又回到靜默吞掉。

    這一條不跑任何東西，所以 node 不在、chmod 擋不住的機器上一樣有效。
    """
    fn = _fn("_cache_put")
    bare = [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Return) and n.value is None]
    assert bare == [], (
        f"`_cache_put()` 第 {bare} 行有不帶值的 return。"
        "寫失敗不丟例外是對的，不說話不是 —— 那兩種 False 在呼叫端分不出來。")


def test_三個呼叫點都要把回傳值用掉():
    """**擋的是一個很像樣的改法**：保留回傳值，呼叫端照樣丟掉。

    那樣所有既有測試照綠、行為照跑，而畫面上分不出來的東西
    又變回分不出來 —— 一個安靜的退步，不是一個當場爆掉的錯誤。
    """
    tree = ast.parse(BLAST_SRC.read_text(encoding="utf-8"))
    dropped = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
               and isinstance(n.value.func, ast.Name)
               and n.value.func.id == "_cache_put"]
    assert dropped == [], (
        f"第 {dropped} 行呼叫 `_cache_put()` 但沒有用它的回傳值。")

    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_cache_put"]
    assert len(calls) == 3, (
        f"`_cache_put()` 的呼叫點從 3 個變成 {len(calls)} 個，"
        "新的那一個有沒有把狀態帶出去，這一組沒有驗。")


def test_三支公開函式的回傳都帶得出寫入狀態():
    """`collect` / `vectors` / `detail` 三支，每一支都要有賦值那一行。"""
    src = BLAST_SRC.read_text(encoding="utf-8")
    assert src.count('"cache_write"') >= 6, (
        "帶出 cache_write 的地方少於 6 處（3 支寫入路徑 + 3 條命中路徑）")
