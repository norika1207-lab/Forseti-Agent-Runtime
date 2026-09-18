#!/usr/bin/env python3
"""Blast Radius（§16.1 八視圖之一）。

§16.1 原文那一句：

    Blast Radius | What files/workflows/sessions/external effects
                   depend on this node?

精確定義在 `Forseti_Five_Mechanisms_Handoff_v1.0_2026-09-07.md` 第 6 節
（M4 代價定義），五維 `CostVector` 加四條誠實條款。

## 這個檔不做什麼

**不重寫演算法。** 反向可達 BFS 與 CostVector 已經完整實作在
`src/cost.js`（167 行，`test/cost.test.mjs` 有測試）。這裡照
`jsbridge.py` 與 `goalgate.py` 的做法用 node 跑那一份。

`jsbridge.py` 檔頭那句話是理由：

    重寫就會變成兩份會分歧的實作，而分歧的那天沒有人會發現。

## 那這個檔做什麼

做 `src/cost.js` 沒有的那一半：**真實的 import 邊從哪裡來。**
`buildGraph()` 要一個 `{from, to, specifier}` 的陣列，而產生那個陣列
需要讀真的原始碼。這裡用 `ast` 解析，不是正規表示式猜的。

## ROADMAP 那一句不準確

ROADMAP P1 第 5 項寫「事件帳本裡有 lineage 邊，`event_ledger.py`
有相關實作」。2026-09-16 查證：`LINEAGE_EDGES` 當時是**只定義未實作**，
所以「從事件節點往下游走」這條路沒有邊可以走。
這裡走的是**檔案依賴**那條，也就是 M4 精確定義的那一條。

**2026-09-18 更新。** `lineage.py` 補上了存放層與 §6.3 的兩端約束，
`lineage.walk()` 走得動。但**磁碟上此刻 0 條邊**，所以上面那句
「沒有邊可以走」對結果仍然成立，變的是原因：先前是沒有存放層，
現在是沒有人產生邊。同一輪也量翻了當時記下的理由 ——
擋住的不是「還沒有 claim 與 decision」（decision 指得到、claim 有
實作），是 evidence 沒有實體。這一段留著不刪，因為它是那句
ROADMAP 原話的更正紀錄。

## 誠實條款（第 6.4 節，不可協商）

一，永遠是下界。`is_lower_bound` 由 `cost.js` 釘死 true。
二，未解析的 import 可查，不靜默吞掉 → `unresolved`。
三，跨語言邊界標成斷點，不假裝連得起來 → `cross_language`。
四，沒有覆蓋報告時 `uncovered_d1` 回 None、`coverage_source` 為
    NONE，不用啟發式估算 → 本檔不傳 coverage，由 cost.js 回 None。

**再加一條本檔自己的。** `live_conflicts` 是第 6.3 節優先序最高的
指標，資料來源是 M3 的 WriteScope。Python 這條線沒有執行中的
WriteScope，所以送進去的是空集合，而 `cost.js` 對空集合回 0。
**0 在畫面上看起來像「沒有衝突」，但真相是「沒有資料來源」。**
所以輸出另外帶 `live_conflicts_source`，NONE 時畫面不准顯示 0。
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"

#: 掃哪些目錄的 Python 原始碼。tests/ 納進來是因為「測試 import 生產
#: 模組」是真實的依賴事實。**但它不可以拿來推覆蓋率** —— 有 import
#: 不等於有覆蓋，那是誠實條款四禁止的啟發式估算。
SCAN_DIRS = ("apps/forseti-cli", "tools", "tests")

#: 掃哪些目錄的 JS 原始碼。這張清單涵蓋 repo 裡**全部**非 node_modules
#: 的 .js/.mjs/.cjs，跟 SCAN_DIRS 對 .py 的涵蓋範圍是同一個意思
#: （那三個目錄剛好就是全部的 .py），不是我挑出來的一個子集。
#:
#: `adapters/` 與 `hooks/` 一定要在裡面：少了它們，
#: `test/adapter-claude-code.test.mjs` 與 `test/event-ledger.test.mjs`
#: 的 import 會變成 NOT_FOUND，而那不是「目標不存在」，
#: 是「我沒有掃到它」—— 兩者在 to=None 上長得一模一樣。
JS_SCAN_DIRS = ("src", "test", "hooks", "adapters", "tools",
                "desktop/ui", "example", "ui/source-tree")

#: node_modules 底下的不是這個專案的原始碼。
JS_EXCLUDE = ("node_modules",)

#: cost.js 的預設模組歸屬是「路徑第一段目錄」。本檔不改它，
#: 因為真正的子系統劃分規格沒有定義，自己編一個就是 §8.3 的填空。
MODULE_RULE = "路徑第一段目錄（cost.js 的預設，不是這個專案的子系統劃分）"

def _stdlib_names() -> frozenset:
    """標準庫模組名。**直譯器自己給的事實，不是我維護的一張清單。**

    手維護的清單會過期，而過期的那天沒有人會發現 —— 一個舊模組被
    當成第三方，解析率就悄悄少一格。

    `sys.stdlib_module_names` 是 3.10 才有的，這台是 3.9.6，
    所以退回去讀 `sysconfig` 的 stdlib 目錄，一樣是問直譯器。
    """
    names = set(getattr(sys, "stdlib_module_names", ()) or ())
    if not names:
        import os
        import sysconfig
        names |= set(sys.builtin_module_names)
        for key in ("stdlib", "platstdlib"):
            d = sysconfig.get_paths().get(key)
            if not d or not os.path.isdir(d):
                continue
            for e in os.listdir(d):
                if e.startswith("_") and not e.startswith("__"):
                    names.add(e.split(".")[0])
                elif e.endswith(".py"):
                    names.add(e[:-3])
                elif os.path.isdir(os.path.join(d, e)):
                    names.add(e)
        ld = os.path.join(sysconfig.get_paths().get("stdlib", ""), "lib-dynload")
        if os.path.isdir(ld):
            for e in os.listdir(ld):
                names.add(e.split(".")[0])
    return frozenset(names) | {"__future__"}


STDLIB = _stdlib_names()

#: 看起來像 JS 檔案路徑的 token。白名單而不是「用空白切開看結尾」——
#: 後者會把中文說明文字一起吃進來，也會被 `lstrip` 逐字元剝掉檔名開頭
#: （`cost.js` 被啃成 `ost.js`，`intervention.js` 被啃成 `ntervention.js`）。
_JS_REF = re.compile(r"[A-Za-z0-9_${}/.-]*[A-Za-z0-9_-]\.js\b")

#: 跑一次 node 的上限，跟 jsbridge.TIMEOUT 同一個理由。
TIMEOUT = 20


def _rel(p: Path, base: Path | None = None) -> str:
    """相對 repo 根的路徑。

    `base` 不能省略成常數 REPO：測試要能在 tmp 目錄上建一個假 repo，
    寫死 REPO 會讓 `relative_to` 直接丟 ValueError。
    第一版就是寫死的，`test_假repo_也能跑` 當場抓到。
    """
    return str(p.relative_to(base or REPO))


def python_files(root: Path | None = None) -> list[Path]:
    """要掃的 .py。跳過 macOS 在 exFAT 上留的 `._` 伴生檔。"""
    base = root or REPO
    out: list[Path] = []
    for d in SCAN_DIRS:
        dd = base / d
        if not dd.is_dir():
            continue
        for f in sorted(dd.rglob("*.py")):
            if f.name.startswith("._"):
                continue
            out.append(f)
    return out


def js_files(root: Path | None = None) -> list[str]:
    """要掃的 JS。回的是**repo 相對路徑字串**，不是 Path。

    格式必須跟 Python 那半邊的 `_rel()` 一致（`src/cost.js` 這種），
    因為兩批邊最後要進同一張 `cost.js` 的圖。
    `imports.js` 的 `resolve()` 也是拿這個字串做 `dirOf` 拼接，
    所以 `src/topology.js` 裡的 `./cost.js` 才解得出 `src/cost.js`。

    跳過 macOS 在 exFAT 上留的 `._` 伴生檔，理由跟 `python_files()`
    同一條 —— `imports.js` 自己的 `NOT_SOURCE` 也在防同一件事，
    這裡先濾一次是為了不讓它們進到「掃到幾個檔」那個數字裡。
    """
    base = root or REPO
    out: list[str] = []
    for d in JS_SCAN_DIRS:
        dd = base / d
        if not dd.is_dir():
            continue
        for pat in ("*.js", "*.mjs", "*.cjs"):
            for f in sorted(dd.rglob(pat)):
                if f.name.startswith("._"):
                    continue
                rel = _rel(f, base)
                if any(x in rel.split("/") for x in JS_EXCLUDE):
                    continue
                out.append(rel)
    return sorted(set(out))


def _flat_targets(files: list[Path], base: Path | None = None) -> dict[str, str]:
    """模組名 → 檔案路徑。

    `apps/forseti-cli/` 那批是平面 import（`import vitals as VT`），
    不是 package，所以查表用的是**檔名去掉副檔名**。
    """
    table: dict[str, str] = {}
    for f in files:
        table.setdefault(f.stem, _rel(f, base))
    return table


def imports_of(path: Path, table: dict[str, str], root: Path | None = None
               ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """解析一個檔的 import。回傳（邊, 外部 import, 跨語言斷點, 動態 import）。

    **三類要分開，第一版沒分，當場得到一個假的壞消息。**

    第一版把標準庫（`json`、`time`、`pathlib`）也算成「未解析」，
    於是解析率變成 0.184。那個數字看起來像「這張圖有八成漏抓」，
    但真相是那八成根本不該進圖 —— 專案內依賴圖裡沒有 `json` 這個節點。

    誠實條款二的「未解析」問的是**我漏抓了多少應該有的邊**，
    所以三類必須分開：

        一，解析到專案內的檔案      → 進圖，成為邊
        二，標準庫或第三方          → 不進圖，記進 `external` 可查
        三，真的解析不出來（相對 import、動態）→ 進圖但 to=None

    標準庫用 `sys.stdlib_module_names` 判定，那是直譯器自己給的事實，
    不是我維護的一張清單。這個專案零依賴（ADR-009），
    所以第二類幾乎等於標準庫。

    ## 第四類：延後 import（2026-09-16 補）

    `ast.Import` 與 `ast.ImportFrom` 只看得到**模組頂層與函式內的
    import 語句**，看不到 `importlib.import_module("worker")`。
    而這個專案大量使用後者來打破循環依賴 —— `ledger.py` 就是靠
    它依賴 worker / starvation / continuity / watchdog 四個模組。

    **那四條是真的依賴，只是先前整張圖上不存在。** 所以
    `ledger.py` 的 blast radius 先前是低報的，而低報的方向
    比高報更危險：它讀起來像「改這個檔影響範圍比較小」。

    兩種要分開，理由跟上面三類分開是同一條：

        四之一，參數是字面字串 → **解得出來，進圖**，kind=DEFERRED
        四之二，參數是變數或 f-string → 解不出來，**只計數不猜**

    第二種就是 `src/imports.js` 檔頭講的 `dynamic_opaque`，
    JS 那半邊從第一天就在算，Python 這半邊先前沒有對應的數字，
    所以畫面上「這張圖看不到的東西」只講得出一半。
    """
    base = root or REPO
    rel = str(path.relative_to(base))
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError, OSError):
        # **三個值，不是兩個。** 先前這裡回兩個，而三個呼叫端全部寫
        # `e, x, b = imports_of(...)`，所以 repo 裡只要有一個語法錯誤的
        # .py（測試 fixture 最容易出現），整張圖會以 ValueError 整個炸掉，
        # 而錯誤訊息完全不會提到是哪個檔造成的。
        # `test_語法錯誤的檔不會讓整張圖炸掉` 釘住這一條。
        # 2026-09-16 元數從三變四（多了動態 import），這一行跟著改。
        return [], [], [], []

    # 模組、函數、類別的第一個字串運算式就是 docstring。
    docstrings: set = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            b = getattr(n, "body", None)
            if b and isinstance(b[0], ast.Expr) and \
                    isinstance(b[0].value, ast.Constant) and \
                    isinstance(b[0].value.value, str):
                docstrings.add(id(b[0].value))

    edges: list[dict] = []
    external: list[dict] = []
    dynamic: list[dict] = []
    seen: set[str] = set()

    def add(spec: str, kind: str = "STATIC") -> None:
        head = spec.split(".")[0]
        if head in seen:
            return
        seen.add(head)
        to = table.get(head)
        if to is not None:
            # 自己 import 自己不算邊（BFS 會跳過，但別讓它進圖製造噪音）
            if to != rel:
                edges.append({"from": rel, "to": to, "specifier": spec,
                              "kind": kind})
            return
        # 第二類：標準庫或第三方。不進圖，但要可查。
        external.append({"from": rel, "specifier": spec,
                         "stdlib": head in STDLIB, "kind": kind})

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # 第三類：相對 import。這個專案是平面的，出現就是
                # package 形式，解析規則不一樣，不猜 → 真的未解析。
                edges.append({"from": rel, "to": None,
                              "specifier": "." * node.level + (node.module or ""),
                              "kind": "RELATIVE"})
                continue
            if node.module:
                add(node.module)

    # 第四類：延後 import。**這一輪之前整張圖上完全不存在。**
    #
    # `ledger.py` 靠 `importlib.import_module("worker")` 打破循環依賴，
    # 所以它依賴 worker / starvation / continuity / watchdog 這四條邊
    # 先前一條都沒有進圖 —— 那不是「它沒有依賴」，是「我沒有看到」。
    #
    # **字面的進圖，非字面的只計數。** 猜一個 f-string 可能指到哪裡
    # 就是 §8.3 的填空衝動，這裡不做。
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        name = (f.attr if isinstance(f, ast.Attribute)
                else f.id if isinstance(f, ast.Name) else None)
        if name not in ("import_module", "__import__"):
            continue
        arg = n.args[0] if n.args else None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            add(arg.value, "DEFERRED")
        else:
            # 看到了，但解不出來。記一筆，不猜它指到哪裡。
            dynamic.append({"from": rel, "line": getattr(n, "lineno", None),
                            "call": name})

    # 跨語言邊界（誠實條款三）。Python 呼叫 src/*.js 走的是 subprocess，
    # 靜態 import 分析抓不到，所以**標成斷點，不連邊**。
    #
    # **docstring 要跳過。** 第一版沒跳，於是這個檔自己的說明文字
    # 「路徑第一段目錄（cost.js 的預設」被算成一個跨語言斷點，
    # 正本因此虛報成 28 個。一個虛報的斷點數跟一個虛報的
    # blast radius 是同一種病 —— 它讓人以為系統知道一件它不知道的事。
    breaks: list[dict] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            if id(n) in docstrings:
                continue
            v = n.value
            if ".js" not in v or len(v) >= 400:
                continue
            for m in _JS_REF.finditer(v):
                name = m.group(0).rsplit("/", 1)[-1]
                if name != ".js":
                    breaks.append({"from": rel, "js": name})
    return edges, external, breaks, dynamic


# ── 磁碟快取 ────────────────────────────────────────────────────
#
# **記憶體快取在這裡沒有用。** 畫面每 2 秒呼叫一次 `strands`，
# 而每一次都是 Rust `Command::new(python3)` 起的**全新程序**
# （`desktop/src-tauri/src/main.rs` 的 `run_api()`），
# 所以 module-level 的 dict 每次都是空的。跨程序只能靠磁碟。
#
# 實測（2026-09-16，外接碟 exFAT）：`strands` 4.53 秒，輪詢間隔 2 秒。
# 後端跟不上前端，而且**這件事在接 JS 之前就已經成立**
# （當時約 2.9 秒），接 JS 只是把它從一倍變成兩倍。
#
# 失效靠指紋不靠時間：檔案集合 + 每個檔的 mtime_ns + size。
# 用時間當有效期會有一個很難查的症狀 —— 改完程式碼畫面不動，
# 而且不會有任何錯誤訊息。
# 2026-09-16 16:5x：4 到 5，因為 `js_dynamic_where` 是新欄位。
# 不跳版的症狀跟上一次一樣難查：畫面少一格，而且不會有任何錯誤訊息。
_CACHE_VERSION = 5


def _fingerprint(base: Path, py: list[Path], js: list[str]) -> str | None:
    """檔案集合的指紋。算不出來回 None，**不是回一個假的指紋**。

    回 None 時呼叫端要當成「不能用快取」，直接重算。
    一個編出來的指紋會讓快取永遠命中，那比沒有快取糟得多。
    """
    h = hashlib.sha256()
    h.update(f"v{_CACHE_VERSION}\n".encode())
    try:
        for f in py:
            st = f.stat()
            h.update(f"{_rel(f, base)}|{st.st_mtime_ns}|{st.st_size}\n".encode())
        for r in js:
            st = (base / r).stat()
            h.update(f"{r}|{st.st_mtime_ns}|{st.st_size}\n".encode())
    except OSError:
        return None
    return h.hexdigest()


def _cache_file(base: Path) -> Path:
    return base / ".forseti" / "cache" / "blast.json"


def _cache_get(base: Path, key: str, fp: str) -> dict | None:
    """讀快取。壞掉、過期、讀不到一律回 None 重算，不猜。"""
    if not fp:
        return None
    try:
        raw = json.loads(_cache_file(base).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ent = (raw or {}).get(key)
    if not isinstance(ent, dict) or ent.get("fp") != fp:
        return None
    val = ent.get("val")
    return val if isinstance(val, dict) else None


#: `_cache_put()` 回傳的三種狀態。**不是布林**，因為「沒寫」有兩種，
#: 而這兩種的後果相反：`SKIPPED` 是本來就不該寫（非正本、沒有指紋），
#: `FAILED` 是該寫但寫不進去 —— 後者代表之後每一次呼叫都會重算。
CACHE_OK = "ok"
CACHE_SKIPPED = "skipped"
CACHE_NOT_ATTEMPTED = "not_attempted"


def _cache_write_why(status: str) -> str:
    """把狀態翻成一句給人看的話。**四種狀態四句，不共用一句。**"""
    if status == CACHE_OK:
        return "快取寫成功了，檔案沒變的話下一次會命中"
    if status == CACHE_SKIPPED:
        return ("沒有指紋所以本來就不寫（非正本 repo，"
                "或者檔案在算指紋的時候讀不到）")
    if status == CACHE_NOT_ATTEMPTED:
        return "這一次是快取命中，沒有寫入動作"
    return ("快取寫不進去（" + status.split(":", 1)[-1] + "），"
            "所以之後每一次呼叫都會整個重算，而且 cached 會永遠是 False。"
            "**這不等於答案是錯的** —— 答案一樣，代價是每次重算")


def _cache_put(base: Path, key: str, fp: str, val: dict) -> str:
    """寫快取。**寫失敗不算錯誤**，功能本身不依賴它 —— 但它會說出來。

    回傳 `CACHE_OK` / `CACHE_SKIPPED` / `"failed:<例外類別>"`。

    **先前這裡是 `except OSError: return`，什麼都不說。** 2026-09-17 實測
    （快取目錄 chmod 0o500）：`vectors()` 兩次都回 `cached: False`、
    兩次答案逐欄位相同、回傳的 36 個鍵一個都沒變 —— 於是
    「這次剛算，下次會命中」跟「永遠寫不進去，每次都重算」
    在呼叫端長得一模一樣。**分不出來的那兩件事後果相反。**

    這一支不改政策：寫不進去仍然不丟例外、仍然照常回答。
    改的只是它說不說。
    """
    if not fp:
        return CACHE_SKIPPED
    f = _cache_file(base)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = {}
        except (OSError, json.JSONDecodeError):
            raw = {}
        # 指紋一變，舊的整批都沒用了，留著只會讓檔案無限長大。
        raw = {k: v for k, v in raw.items()
               if isinstance(v, dict) and v.get("fp") == fp}
        raw[key] = {"fp": fp, "val": val}
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)
    except OSError as e:
        # **不吞掉，回報。** 例外類別帶出去，訊息不帶 ——
        # 訊息裡會有絕對路徑，那會跑到畫面上去。
        return "failed:" + type(e).__name__
    return CACHE_OK


#: `collect()` 在快取檔裡的 key。跟 `vectors|...` / `summary|...`
#: 同一個檔、同一個指紋，所以指紋一變三個一起失效。
_COLLECT_KEY = "collect"


def collect(root: Path | None = None) -> dict:
    """掃出圖上的節點與 Python 那半邊的邊。這一步全部是事實，沒有判斷。

    **`imports` 只有 .py 的邊。** JS 的 import 邊由 `src/imports.js`
    在 node 那端解析（見 `_JS_PRELUDE`），這裡只負責決定哪些 .js
    在範圍內（`js_files`）。分這樣是因為那份解析器從第一天就寫好了，
    缺的是宿主不是演算法，在 Python 再寫一份正則解析會變成
    兩份會分歧的實作。

    **這一支自己有磁碟快取，而且是 2026-09-16 21:5x 才加的。**
    先前 `vectors()` 與 `summary()` 的快取都在 `g = collect(root)`
    那一行**之後**才問，所以這一段從來沒有被快取過。第 5a 節寫的
    「4.53 秒 → 1.29 秒」不含這 1.89 秒，那個數字量的是 node 那一段。
    成本不對稱：讀 120 個檔加 AST 剖析實測 1.89 秒，而指紋只要
    兩次目錄掃描加 stat，實測 0.25 秒。

    **臨時 repo 不走快取（`base != REPO`）。** exFAT 的 mtime 解析度
    是 10 毫秒，一個在 10 毫秒內被改回同樣大小的檔，指紋分不出來。
    測試正是在這個時間尺度上建檔改檔，而臨時 repo 只用一次，
    快取在那裡沒有價值只有風險。快取命中時 `cached` 是 True，
    跟 `vectors()` 同一條理由：一個舊數字看起來跟新的一模一樣。
    """
    base = root or REPO
    files = python_files(base)
    js = js_files(base)
    fp = _fingerprint(base, files, js) if base == REPO else None
    if fp:
        hit = _cache_get(base, _COLLECT_KEY, fp)
        if hit is not None:
            return {**hit, "fp": fp, "cached": True,
                    "cache_write": CACHE_NOT_ATTEMPTED,
                    "cache_write_why": _cache_write_why(CACHE_NOT_ATTEMPTED)}
    table = _flat_targets(files, base)
    edges: list[dict] = []
    external: list[dict] = []
    breaks: list[dict] = []
    dynamic: list[dict] = []
    for f in files:
        e, x, b, d = imports_of(f, table, base)
        edges.extend(e)
        external.extend(x)
        breaks.extend(b)
        dynamic.extend(d)
    # 斷點去重
    uniq = {(b["from"], b["js"]): b for b in breaks}
    res = {
        "files": [_rel(f, base) for f in files],
        "imports": edges,
        "external": external,
        "cross_language": sorted(uniq.values(), key=lambda b: (b["from"], b["js"])),
        # 看得到但解不出來的動態 import。**這是圖的盲點，不是零。**
        # 跟 `src/imports.js` 的 `dynamic_opaque` 是同一個意思，
        # 先前只有 JS 那半邊算得出來。
        "dynamic_opaque": sorted(dynamic, key=lambda d: (d["from"], d["line"] or 0)),
        # **JS 那半邊只有清單，沒有邊。** 邊是 node 那端用
        # `src/imports.js` 算的（`_JS_PRELUDE`），因為那份解析器
        # 本來就在，不在 Python 重寫。所以這一支回的 `imports`
        # 是 Python 半邊，完整的圖要看 `vectors()` / `detail()`。
        "js_files": js,
        # 算過的指紋帶出來給 `vectors()` / `summary()` 用。
        # 不帶的話那兩支要自己再掃一次兩個目錄樹（實測 0.24 秒），
        # 而那次掃描算出來的一定是同一個值。
        "fp": fp,
        "cached": False,
    }
    # **賦值在 `_cache_put()` 之後**，所以存進檔案的那一份不帶這兩欄。
    # 帶的話等於把某一次的寫入狀態凍進快取，下一次命中會讀回來，
    # 於是一個舊狀態看起來會像此刻的狀態。
    st = _cache_put(base, _COLLECT_KEY, fp, res) if fp else CACHE_SKIPPED
    res["cache_write"] = st
    res["cache_write_why"] = _cache_write_why(st)
    return res


#: node 端的共用片段。**兩個 runner 用同一份，不是各寫一次。**
#:
#: 這裡只做「餵資料 + 分類」，解析演算法完全在 `src/imports.js`（M11）。
#: 那個模組從第一天就寫好了，它的檔頭自己寫著「它不讀檔案系統，
#: 宿主把檔名 → 原始碼文字餵進來」—— 缺的一直是這個宿主，
#: 不是演算法。所以這裡不在 Python 也不在這段 JS 裡重寫任何解析。
#:
#: **EXTERNAL 不進圖，這是這段程式碼唯一的判斷，而它有代價。**
#: 實測：把 EXTERNAL 一起餵進 `buildGraph()`，`cost.js` 的
#: `resolutionRate()` 從 0.971 掉到 0.541，因為它把 to=null 一律
#: 算成未解析。那個 0.54 會被讀成「這張圖漏抓了四成六」，
#: 而真相是那四成六是 `node:fs` 這類內建模組，本來就不該是圖上的節點。
#: 跟 `imports_of()` 檔頭記載的 Python 第一版 0.184 事件是**同一種病**。
_JS_PRELUDE = r"""
import { readFileSync } from 'node:fs';
import { builtinModules } from 'node:module';

// node 自己給的內建模組清單，不是我維護的一張表。
// 跟 Python 那半邊用 `sys.stdlib_module_names` 是同一條原則。
const BUILTIN = new Set(builtinModules);
function isBuiltin(spec) {
  if (spec.startsWith('node:')) return true;
  return BUILTIN.has(spec.split('/')[0]);
}

// JS 那半邊的 import 邊。回傳格式刻意跟 Python 那半邊逐欄對齊
// （from / to / specifier），因為兩批邊要合併進同一張圖。
async function jsHalf(srcDir, repo, jsFiles) {
  const empty = { edges: [], external: [], unreadable: [], stats: null };
  if (!jsFiles || !jsFiles.length) return empty;
  let IM;
  try {
    IM = await import(`${srcDir}/imports.js`);
  } catch (e) {
    // imports.js 不在就整個 JS 半邊沒有，**不是零條邊**。
    return { ...empty, why: `載不進 imports.js：${e.message}` };
  }
  const sources = {};
  const unreadable = [];
  for (const f of jsFiles) {
    try {
      sources[f] = readFileSync(`${repo}/${f}`, 'utf8');
    } catch (e) {
      unreadable.push(f);
    }
  }
  const rec = IM.buildImportRecords(sources);
  const edges = [];
  const external = [];
  for (const r of rec.imports) {
    if (r.resolution === 'EXTERNAL') {
      external.push({ from: r.from, specifier: r.specifier,
                      stdlib: isBuiltin(r.specifier) });
      continue;
    }
    edges.push({ from: r.from, to: r.to, specifier: r.specifier,
                 kind: r.kind, resolution: r.resolution });
  }
  return { edges, external, unreadable, stats: rec.stats };
}
"""

_RUNNER = _JS_PRELUDE + r"""
const [,, srcDir, payloadFile] = process.argv;
const payload = JSON.parse(readFileSync(payloadFile, 'utf8'));
const mod = await import(`${srcDir}/cost.js`);
const js = await jsHalf(srcDir, payload.repo, payload.js_files);
// 兩批邊進同一張圖。Python 那批在前只是為了輸出穩定，
// buildGraph 對順序沒有意見。
const graph = mod.buildGraph([...(payload.imports || []), ...js.edges]);
const out = [];
for (const t of payload.targets || []) {
  out.push({ target: t, vector: mod.computeCostVector(graph, t, {}) });
}
out.sort((a, b) => mod.compareCostVectors(b.vector, a.vector));
console.log(JSON.stringify({
  resolution_rate: mod.resolutionRate(graph),
  unresolved: mod.unresolvedImports(graph),
  vectors: out,
  js: { edges: js.edges.length, external: js.external.length,
        unreadable: js.unreadable, stats: js.stats, why: js.why || null,
        third_party: [...new Set(js.external.filter(e => !e.stdlib)
                                           .map(e => e.specifier))].sort() },
}));
"""


def _node_bin() -> str | None:
    try:
        import jsbridge as JB
        return JB.node_bin()
    except Exception:
        return None


def vectors(targets: list[str] | None = None, root: Path | None = None,
            limit: int = 8) -> dict:
    """算 CostVector。演算法在 `src/cost.js`，這裡只餵資料。

    一次 node 呼叫算完所有 target，不是一個檔起一次進程。
    """
    g = collect(root)
    base = root or REPO
    src = (base / "src")
    n = _node_bin()
    if not n or not src.is_dir():
        return {"has": False, "why": "找不到 node，代價向量算不了" if not n
                else "找不到 src/，cost.js 不在", "files": len(g["files"])}

    all_nodes = sorted(set(g["files"]) | set(g["js_files"]))
    tg = targets if targets is not None else all_nodes

    # `collect()` 已經算過同一個指紋就直接用（`base == REPO` 時）。
    # 臨時 repo 那邊 `collect()` 不算指紋，所以這裡自己補一次。
    fp = g.get("fp") or _fingerprint(base, python_files(base), g["js_files"]) or ""
    ckey = f"vectors|{limit}|{'ALL' if targets is None else ','.join(tg)}"
    hit = _cache_get(base, ckey, fp)
    if hit is not None:
        # **標明這是快取。** 一個舊數字看起來跟一個新數字一模一樣，
        # 而這個專案整份的立場是不讓人以為系統知道它其實不知道的事。
        return {**hit, "cached": True,
                "cache_write": CACHE_NOT_ATTEMPTED,
                "cache_write_why": _cache_write_why(CACHE_NOT_ATTEMPTED)}
    stage = "寫暫存檔"
    tmp = Path(tempfile.mkdtemp(prefix="forseti-blast-"))
    # `stage` 是 2026-09-18 加的，理由跟 `goalgate.py` 那一支同一句：
    # 兩個 write_text 也會丟 OSError，而底下先前一律講成「起不了 node」。
    try:
        runner = tmp / "run.mjs"
        runner.write_text(_RUNNER, encoding="utf-8")
        data = tmp / "payload.json"
        data.write_text(json.dumps({"imports": g["imports"], "targets": tg,
                                    "js_files": g["js_files"],
                                    "repo": str(base)},
                                   ensure_ascii=False), encoding="utf-8")
        stage = "叫 node"
        r = subprocess.run([n, str(runner), str(src), str(data)],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"has": False, "why": f"node 超過 {TIMEOUT} 秒沒回"}
    except OSError as e:
        return {"has": False, "why": f"{stage}失敗：{e}"}
    finally:
        # **node 跑完就不需要這個目錄了。** 先前這裡沒有收，
        # 而這一支每一輪輪詢只要指紋變了就走一次 ——
        # 2026-09-17 實測 `$TMPDIR` 底下累積 5713 個沒人收的
        # `forseti-blast-*`：內容 57.2MB，`du` 報 84MB（差的是
        # 每個目錄的配置區塊，5713 個空目錄本身就要那個量）。
        # `jsbridge.py:202` 與
        # `goalgate.py:249` 從一開始就是這個形狀，漏的是這裡。
        shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        return {"has": False, "why": f"cost.js 跑失敗：{r.stderr.strip()[:200]}"}
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return {"has": False, "why": f"cost.js 的輸出不是 JSON：{e}"}

    top = out["vectors"][:limit]
    js = out.get("js") or {}
    res = {
        "has": True,
        "cached": False,
        "files": len(all_nodes),
        "py_files": len(g["files"]),
        "js_files": len(g["js_files"]),
        "edges": len([e for e in g["imports"] if e["to"]]) + int(js.get("edges") or 0),
        "py_edges": len([e for e in g["imports"] if e["to"]]),
        "js_edges": int(js.get("edges") or 0),
        "resolution_rate": round(out["resolution_rate"], 3),
        "unresolved_total": len(out["unresolved"]),
        "unresolved": out["unresolved"][:20],
        "external_total": len(g["external"]) + int(js.get("external") or 0),
        "third_party": sorted({x["specifier"] for x in g["external"]
                               if not x["stdlib"]}
                              | set(js.get("third_party") or [])),
        # 兩半邊的解析方法不一樣，可靠度不一樣，這件事不標明
        # 就等於讓人以為整張圖是同一種品質。
        "parser_py": "ast（直譯器自己的剖析器）",
        "parser_js": "正規表示式（src/imports.js，它的檔頭自己寫明"
                     "「不用 AST 解析器，因為那會引入依賴」）",
        "parser_why": "同一張圖的兩半邊解析方法不同：.py 走 ast，"
                      ".js 走正則。正則那半邊漏的會比較多，"
                      "所以整張圖的下界性質主要來自 JS 這半",
        "js_unreadable": js.get("unreadable") or [],
        "js_why": js.get("why"),
        "js_stats": js.get("stats"),
        # ── 這張圖的盲點。兩半邊各自算，不合併成一個數字 ──────────
        #
        # 「看得到但解不出來的動態 import」。這是 `is_lower_bound`
        # 那句話的**可查數字版本**：先前畫面只寫「這個數字是下界」，
        # 沒有講下界差多少，讀起來像一句免責聲明。
        #
        # Python 這半邊的 2 筆先前完全算不出來（`ast.Import` 看不到
        # `importlib.import_module(name)`），JS 那半邊的
        # `dynamic_opaque` 從第一天就在算但沒有接到畫面。
        "py_dynamic_opaque": len(g["dynamic_opaque"]),
        "py_dynamic_where": g["dynamic_opaque"][:20],
        # 字面參數的延後 import **解得出來，所以進圖**。
        # 這個數字是「先前漏掉、這一輪補回來的真實邊數」。
        "py_deferred_edges": len([e for e in g["imports"]
                                  if e.get("kind") == "DEFERRED" and e["to"]]),
        # **None 不是 0。** JS 半邊沒跑起來時（`js_why` 有值），
        # 這裡沒有資料，而 0 讀起來是「JS 那半邊沒有盲點」。
        "js_dynamic_opaque": (js.get("stats") or {}).get("dynamic_opaque")
                             if js.get("stats") else None,
        # **位置，不只是數量。** 一個總數說得出「JS 那半邊有 14 個
        # 看不到的地方」，說不出「所以我該去看哪個檔第幾行」。
        # Python 這半邊從一開始就帶 from 與 line，這裡補成同一個形狀。
        #
        # 一樣是 None 不是 []：JS 半邊沒跑起來時空清單讀起來是
        # 「JS 那邊沒有盲點」，跟 `js_dynamic_opaque` 同一條理由。
        #
        # `dynamic_where` 是 `src/imports.js` 的 `buildImportRecords`
        # 算的，**這裡沒有重寫任何解析**，跟這一整支對 cost.js 的
        # 做法同一條。
        "js_dynamic_where": (((js.get("stats") or {}).get("dynamic_where") or [])[:20]
                             if js.get("stats") else None),
        "blind_spot_why": "動態 import（路徑是變數或拼出來的）靜態分析"
                          "解不出來。看到了就記一筆，不猜它指到哪裡"
                          "（§8.3 禁止填空）。這個數字是這張圖「已知」"
                          "看不到的部分，不是全部看不到的部分",
        "deferred_why": "importlib.import_module(\"字面\") 這種延後 import "
                        "解得出來，所以進圖。這個專案用它打破循環依賴："
                        "ledger.py 對 worker / starvation / continuity / "
                        "watchdog 的依賴全部走這條，2026-09-16 之前"
                        "整張圖上不存在 —— 那不是它沒有依賴，是我沒看到",
        "cross_language": g["cross_language"],
        "top": top,
        # 排行榜只有前 `limit` 名，而明細對圖裡**任何**一個檔都算得出來。
        # 先前畫面上沒有入口走到前 8 名以外的檔，所以把完整節點清單
        # 帶出來讓前端做本地過濾 —— 這份清單 `collect()` 本來就算過，
        # 不是為了這個功能多掃一次。
        "all_files": all_nodes,
        "all_files_why": f"這份清單是這張圖的全部節點（{len(all_nodes)} 個："
                         f"{len(g['files'])} 個 .py 加 {len(g['js_files'])} 個 JS）。"
                         f".py 掃的是 {'、'.join(SCAN_DIRS)}，"
                         f"JS 掃的是 {'、'.join(JS_SCAN_DIRS)}，"
                         f"node_modules 除外。repo 裡其他檔"
                         f"（.md 文件、.rs、.html、.css）不在圖裡，"
                         f"搜尋也找不到，這不是它們不存在",
        "module_rule": MODULE_RULE,
        # 誠實條款四：這裡沒有傳 coverage，所以 cost.js 回 None/NONE。
        "coverage_source": "NONE",
        "coverage_why": "這個專案沒有 lcov 報告，所以 uncovered_d1 是 None。"
                        "不用啟發式估算填值（第 6.4 節條四）",
        # 本檔自己那一條：0 不是「沒有衝突」，是「沒有資料來源」。
        "live_conflicts_source": "NONE",
        "live_why": "live_conflicts 的來源是 M3 的 WriteScope，"
                    "Python 這條線沒有執行中的 WriteScope，"
                    "所以這個數字現在不是 0 個衝突，是沒有資料",
        "is_lower_bound": True,
        "lower_bound_why": "這個數字永遠是下界不是上界：動態 import、"
                           "反射、字串拼出來的路徑，靜態分析抓不到",
    }
    st = _cache_put(base, ckey, fp, res)
    res["cache_write"] = st
    res["cache_write_why"] = _cache_write_why(st)
    return res


_DETAIL_RUNNER = _JS_PRELUDE + r"""
const [,, srcDir, payloadFile] = process.argv;
const payload = JSON.parse(readFileSync(payloadFile, 'utf8'));
const mod = await import(`${srcDir}/cost.js`);
const js = await jsHalf(srcDir, payload.repo, payload.js_files);
// **跟 _RUNNER 建的必須是同一張圖。** 兩支各建一張會分歧，
// 而 `test_detail的數字跟vectors的數字一致` 正是釘這件事的那一條。
const graph = mod.buildGraph([...(payload.imports || []), ...js.edges]);
const target = payload.target;
const { d1, d2plus } = mod.reverseReachable(graph, target);
console.log(JSON.stringify({
  d1: [...d1].sort(),
  d2plus: [...d2plus].sort(),
  vector: mod.computeCostVector(graph, target, {}),
  resolution_rate: mod.resolutionRate(graph),
  // 這個目標自己往外的 import。方向相反，欄位名在 Python 那邊標明。
  // JS 目標的 external 只有 node 這邊知道，Python 的 g["external"]
  // 裡沒有它 —— 少了這一段，點開一個 .js 的「外部 import」會是空的，
  // 而空的讀起來是「它沒有用任何外部模組」。
  js_external: js.external.filter(e => e.from === target)
                          .map(e => ({ specifier: e.specifier, stdlib: e.stdlib })),
  js_edges: js.edges.length,
}));
"""


def detail(target: str, root: Path | None = None) -> dict:
    """點一個檔案，看**誰**依賴它。§16.1 那一句的前半。

    `vectors()` 回的是數字（d1_count 十個），這一支回的是**名單**
    （是哪十個）。差別不是好看：一個「改這個檔會波及 10 個」沒辦法
    行動，一個「會波及這十個，其中三個在 tests/」可以。

    ## 一樣不重寫演算法

    名單本來就在 `cost.js` 的 `reverseReachable()` 裡（它回的是兩個
    Set），只是 `computeCostVector()` 只把 size 帶出來。所以這裡走
    跟 `vectors()` 同一條路：node 跑同一份 `cost.js`，Python 只負責
    把真實 import 邊餵進去、把結果接出來。
    `test_detail的數字跟vectors的數字一致` 釘住兩邊不會分歧。

    ## 誠實條款怎麼落在這一支

    §16.1 問的是 files / workflows / sessions / external effects 四種，
    這一支只答得出 **files** 那一種，另外三種的處理不同：

    - **任務（workflow）**：`ledger.py` 的 `tasks` / `steps` 兩張表
      沒有任何檔案路徑欄位（schema 在 `ledger.py:148-164`），所以
      「哪些任務依賴這個檔」現在**沒有資料來源**。回 None 加一句
      為什麼，不回空清單 —— 空清單在畫面上讀起來是「沒有任務依賴
      它」，那是一句沒有根據的話。
    - **外部效果**：這個檔自己的標準庫與第三方 import 抓得到，
      照實列。但它是「這個檔用了什麼」不是「什麼依賴這個檔」，
      方向相反，所以欄位名與畫面上都要標明方向。
    - **跨語言**：這個檔提到的 `.js` 一律是斷點，不連邊。

    未知的檔名不當成「沒有人依賴它」：那會讓一個打錯的路徑
    看起來像一個安全的改動。`known` 為 False 時畫面不准畫成 0。
    """
    base = root or REPO
    g = collect(base)
    src = base / "src"
    n = _node_bin()
    if not n or not src.is_dir():
        return {"has": False, "target": target,
                "why": "找不到 node，代價向量算不了" if not n
                else "找不到 src/，cost.js 不在"}

    tgt = str(target or "").strip()
    if not tgt:
        return {"has": False, "target": tgt, "why": "沒有指定要看哪一個檔"}
    known_nodes = set(g["files"]) | set(g["js_files"])
    if tgt not in known_nodes:
        # **不回空名單。** 打錯的路徑跟一個沒有人依賴的檔，
        # 在「d1 是空的」這個結果上長得一模一樣。
        return {"has": False, "target": tgt, "known": False,
                "why": f"這張圖裡沒有 {tgt} 這個節點。"
                       f".py 掃的是 {'、'.join(SCAN_DIRS)}，"
                       f"JS 掃的是 {'、'.join(JS_SCAN_DIRS)}，"
                       f"共 {len(known_nodes)} 個檔",
                "files": len(known_nodes)}

    # `collect()` 已經算過同一個指紋就直接用（`base == REPO` 時）。
    # 臨時 repo 那邊 `collect()` 不算指紋，所以這裡自己補一次。
    fp = g.get("fp") or _fingerprint(base, python_files(base), g["js_files"]) or ""
    ckey = f"detail|{tgt}"
    hit = _cache_get(base, ckey, fp)
    if hit is not None:
        return {**hit, "cached": True,
                "cache_write": CACHE_NOT_ATTEMPTED,
                "cache_write_why": _cache_write_why(CACHE_NOT_ATTEMPTED)}

    stage = "寫暫存檔"          # 理由同 `vectors()`
    tmp = Path(tempfile.mkdtemp(prefix="forseti-blast-d-"))
    try:
        runner = tmp / "run.mjs"
        runner.write_text(_DETAIL_RUNNER, encoding="utf-8")
        data = tmp / "payload.json"
        data.write_text(json.dumps({"imports": g["imports"], "target": tgt,
                                    "js_files": g["js_files"],
                                    "repo": str(base)},
                                   ensure_ascii=False), encoding="utf-8")
        stage = "叫 node"
        r = subprocess.run([n, str(runner), str(src), str(data)],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"has": False, "target": tgt, "why": f"node 超過 {TIMEOUT} 秒沒回"}
    except OSError as e:
        return {"has": False, "target": tgt, "why": f"{stage}失敗：{e}"}
    finally:
        # 跟 `vectors()` 同一條理由，同一個事故的另一半：
        # 兩個前綴分別留下 2732 與 2981 個目錄。
        shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode != 0:
        return {"has": False, "target": tgt,
                "why": f"cost.js 跑失敗：{r.stderr.strip()[:200]}"}
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return {"has": False, "target": tgt,
                "why": f"cost.js 的輸出不是 JSON：{e}"}

    d1 = out["d1"]
    d2 = out["d2plus"]

    # 模組分佈。歸屬規則跟 cost.js 的 cross_modules 同一條
    # （路徑第一段目錄），不在這裡另定一套 —— 兩套會分歧。
    mods: dict[str, int] = {}
    for f in d1 + d2:
        mods[f.split("/")[0] if "/" in f else "(root)"] = \
            mods.get(f.split("/")[0] if "/" in f else "(root)", 0) + 1

    # 這個檔自己往外的 import。方向跟上面相反，欄位名標明。
    #
    # **JS 目標的 external 在 node 那邊，不在 `g["external"]` 裡。**
    # `g` 是 Python 半邊掃出來的，少了這一段，點開一個 .js 的
    # 「外部 import」永遠是空的，而空的讀起來是「它沒有用任何外部模組」。
    ext = [x for x in g["external"] if x["from"] == tgt]
    ext += [{"from": tgt, "specifier": e["specifier"], "stdlib": e["stdlib"]}
            for e in (out.get("js_external") or [])]
    breaks = [b for b in g["cross_language"] if b["from"] == tgt]
    # 這個檔依賴誰（下游）。列出來是因為看完「誰依賴我」之後
    # 下一個問題一定是「那我依賴誰」，而兩邊都在同一張圖裡。
    deps_out = sorted({e["to"] for e in g["imports"]
                       if e["from"] == tgt and e["to"]})

    res = {
        "has": True,
        "cached": False,
        "known": True,
        "target": tgt,
        "d1": d1,
        "d2plus": d2,
        "d1_count": len(d1),
        "d2_count": len(d2),
        "modules": sorted(mods.items(), key=lambda kv: (-kv[1], kv[0])),
        "module_rule": MODULE_RULE,
        "depends_on": deps_out,
        "depends_on_note": "這一欄的方向相反：是這個檔用了誰，"
                           "不是誰依賴這個檔",
        "external": sorted({x["specifier"] for x in ext}),
        "external_third_party": sorted({x["specifier"] for x in ext
                                        if not x["stdlib"]}),
        "cross_language": [b["js"] for b in breaks],
        "vector": out["vector"],
        "resolution_rate": round(out["resolution_rate"], 3),
        # 誠實條款。四種依賴裡只答得出檔案那一種，另外兩種講清楚為什麼。
        "tasks": None,
        "tasks_why": "ledger 的 tasks/steps 兩張表沒有檔案路徑欄位，"
                     "所以「哪些任務依賴這個檔」沒有資料來源。"
                     "這不是 0 個任務",
        "sessions": None,
        "sessions_why": "session 與檔案之間沒有記錄過的關聯，"
                        "同樣沒有資料來源，不是 0 條",
        "live_conflicts_source": "NONE",
        "live_why": "live_conflicts 的來源是 M3 的 WriteScope，"
                    "Python 這條線沒有執行中的 WriteScope，"
                    "所以這個數字現在不是 0 個衝突，是沒有資料",
        "coverage_source": "NONE",
        "coverage_why": "這個專案沒有 lcov 報告，所以 uncovered_d1 是 None。"
                        "不用啟發式估算填值（第 6.4 節條四）",
        "is_lower_bound": True,
        "lower_bound_why": "這份名單永遠是下界不是上界：動態 import、"
                           "反射、字串拼出來的路徑，靜態分析抓不到",
    }
    st = _cache_put(base, ckey, fp, res)
    res["cache_write"] = st
    res["cache_write_why"] = _cache_write_why(st)
    return res


def summary(root: Path | None = None) -> dict:
    """給畫面用的一格。"""
    return vectors(root=root)


if __name__ == "__main__":
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
