#!/usr/bin/env python3
"""列舉常數的值被手打一次，而那一次打錯了。

## 為什麼有這一支

`tools/declared-only-check.py` 收尾時，十六條 `REFERENCE` 共同留下
一個缺口，寫在那一輪的紀錄裡：

    那些列舉的值在別處以字面字串重打（`starvation.py` 的
    `RECOVERY_STEPS` 定義五個名字，十行後的 `recovery_plan()` 手打
    同樣五個），**拼錯不會紅**。

`RECOVERY_STEPS`（`starvation.py:157`）列五個步驟名，
`recovery_plan()`（同檔 175、176、178 行）把其中四個再打一次，
用的是字面字串不是那個常數。把 `"SYNTHESIS_ONLY"` 打成
`"SYNTHESIS_OLNY"`，Python 不會抱怨，測試也不一定會，
而下游拿那個字串去比對的地方會安靜地永遠不成立。

**那一支答的是「這個常數有沒有人讀」，這一支答的是
「重打的那一次有沒有打對」。** 兩個不同的問題。

## 它回答哪一個問題，不回答哪一個

回答：**這個檔裡有一個識別字風格的字面字串，它不是本檔任何
列舉常數的成員，全 repo 只出現過這一次，而且跟本檔某個成員
只差一兩個字元。** 那高度可疑是打錯的那一次。

**兩種風格，各自的閾值。** `UPPER` 看 `"SYNTHESIS_ONLY"` 這種
ALL_CAPS 常數值，`LOWER` 看 `"tool_use"` 這種小寫鍵名。
小寫那一半是 2026-09-17 補的，它不是把 `IDENT_RE` 放寬 ——
距離上界收到 1，而且多一層屬性存取白名單，理由在
`LOWER_MAX_DISTANCE` 與 `attr_names()` 各自的說明裡，
兩個都是量出來的不是想出來的。

不回答：

- **重打本身該不該改。** `if state == "RUNNING"` 在 Python 裡到處都是。
  真 repo 實測 141 組、289 次，把它們全部判紅只會讓這支守門被關掉。
  所以重打只出現在 `--restated` 的數字裡，**不判紅**。
- **用了合法但錯的成員。** `"VERIFYING"` 該寫 `"VERIFIED"` 的那種，
  兩個都在清單裡，這一支看不出來。那要語意，不是拼寫。

## 三個條件缺一不可，每一個都是為了壓誤報

判紅要同時滿足：

1. **形狀像這個風格的識別字**（`UPPER` 是
   `^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$`，`LOWER` 是
   `^[a-z][a-z0-9]*(_[a-z0-9]+)*$`，都要長度 >= 3）。
   中文說明、句子、路徑一概不看，兩種風格彼此也不互看。
2. **全 repo 只出現這一次。** 合法的值會在別處也出現；打錯的那一次
   只有那一處。**小寫側這一條不夠**，因為小寫鍵名的下游讀者
   常常是 `obj.key` 而不是引號字串 —— 所以小寫再加一層屬性存取
   白名單，那一層是被真 repo 的一次誤報逼出來的（見 `attr_names()`）。這一條是壓誤報的主力 —— 沒有它，`owner.py:326` 的
   `provenance="OBSERVED"` 會被判成 `SILENCE` 裡 `"UNOBSERVED"`
   的拼錯（距離 2），而 `"OBSERVED"` 是 `event_ledger.py:236` 的
   欄位預設值、`starvation.py:61` 的常數值，出現四次，完全合法。
   **那正是第一版唯一的一條命中，而它是誤報。**
3. **跟本檔某個列舉成員距離在 1 到這個風格的上界之間。**
   距離 0 是重打不是拼錯。ALL_CAPS 側上界 2，小寫側上界 1
   （小寫側那個是量出來的，見 `LOWER_MAX_DISTANCE`）。
   ALL_CAPS 側的 2 是一個**選擇，不是量出來的最佳值** —— 2026-09-17
   實測把它放寬到 3，真 repo 一樣 0 命中 0 誤報，所以此刻沒有證據
   說 2 比 3 好。選 2 的理由是距離越大「這是拼錯」這個推論越弱，
   而這一支沒有證據支持更大的距離。**閾值改大不會立刻出事，
   但也不會是因為量過。**

真 repo 上這三條同時成立的：**兩種風格都是 0 個**。
那不是「這支沒用」，那是「此刻沒有拼錯」—— 而從今以後打錯會紅。
2026-09-17 的量：ALL_CAPS 側 70 個列舉常數、266 個成員、
141 組手打共 289 次；小寫側 35 個列舉常數、231 個成員、
123 組手打共 326 次。

## 這一支自己的盲點，寫在這裡不是只寫在紀錄裡

- **兩處打錯成同一個樣子，抓不到。** 條件 2 會把它當成合法值。
  複製貼上剛好就是這個形狀，所以這是真的會發生的漏報。
- **距離 3 以上抓不到。** 閾值是選的（見上面條件 3），
  不是量出來的。三個字元以上的錯字這一支綠。
- **小寫側的屬性白名單很大，代價是漏報，而代價量出來了。**
  真 repo 1527 個名字。2026-09-17 把每個成員的每一個距離 1 變異
  都試過一次（`--shadow --shadow-kinds sub,del,ins`）：
  162309 個變異裡，只有屬性白名單擋住的是 **23 個，落在 21 個
  成員上**。「84 個成員也在白名單裡」不是這個數字，
  那一句講的是另一件事（見 `attr_names()`）。
- **那個量測仍然是下界，只是比先前緊。** 相鄰對調（`ONLY` 打成
  `OLNY`）的距離是 2，三種變異都不包含它，小寫側上界 1
  本來也抓不到。**預設只量替換**（`DEFAULT_MUTATION_KINDS`），
  要三種一起得自己指定，理由是要讓先前量到的 11 還原得回來。
- **駝峰命名（`toolUse`）兩種風格都不看，而 2026-09-17 量過之後
  知道那不是缺口。** Python 定義側 0 個駝峰列舉 0 個成員，JS 側 1 個
  像列舉的區塊 2 個成員，而那 2 個查過是函式名字不是列舉值。
  **所以不加第三個 Profile 不是欠一個判準，是沒有東西可守** ——
  加了會是一個永遠 0 命中的風格。這句話自己會腐爛，所以
  Python 側一長出駝峰列舉就有測試變紅（`camel_census()`、`--camel`）。
- **JS 那一側才是真的缺口，而它有數字了。** `JS_DIRS` 底下 54 個
  ALL_CAPS 區塊 258 個成員、19 個小寫區塊 149 個成員，此刻無人守
  （見下一條：JS 只當白名單）。**下一步是這一條，不是駝峰。**
- **定義側只掃 `apps/forseti-cli/*.py`。** JS 那側的字面值只拿來
  當白名單（壓誤報），不當成拼錯的來源。
- **只看形狀不看用途。** 一個 ALL_CAPS 字串放錯欄位，形狀全對，
  這一支綠。
- **弱在「列舉」的認定。** 一個常數要有兩個以上的 ALL_CAPS 成員
  才算列舉；單值常數（`OBSERVED = "OBSERVED"`）不構成對照組。
- **底線開頭的常數不是定義側的一員，而這件事此刻不造成漏報。**
  `_const_targets()` 排除它們，所以 `_MARK`、`_LABEL`、`_OWNER_EXIT`
  這 3 個私有列舉（共 10 個成員）不當對照組。**但曝險是 0** ——
  那 10 個全部同時也是同檔公開列舉的成員，對照組還在。
  這一條是 2026-09-17 反向驗證駝峰守門時撞出來的：第一次植入的探針
  叫 `_CAMEL_PROBE`，測試沒有紅。機制與曝險是兩個數字，不要合併
  （`private_exposure()`，`test_私有常數的曝險此刻是0` 在曝險
  不再是 0 的時候會紅）。

## 這一組也會污染自己，而且第一次反向驗證就被它擋下來

`tools/` 與 `tests/` 都在 `COUNT_DIRS` 底下，所以這一組自己寫下的
任何 ALL_CAPS 字面字串會把 repo 計數加一 —— 一個真的打錯的字串
只要碰巧出現在這裡的說明、豁免登記簿、或測試的負例裡，條件 2
就不成立，它會安靜地從紅名單消失。**往綠的方向壞。**

**這不是預防性的假設，它真的發生了。** 2026-09-17 第一次反向驗證：
把 `starvation.py:176` 的 `"SYNTHESIS_ONLY"` 打成 `"SYNTHESIS_OLNY"`，
應該紅，結果綠 —— 因為 `tests/test_literal_restate.py` 有一條
測試拿同一個錯字串當負例，`"SYNTHESIS_OLNY"` 在 repo 裡於是有兩次。
**守門被自己的測試關掉了。**

治法是 `_SELF_FILES` 把工具與測試兩個檔一起排除，
不是去改測試裡那個字串（那只治那一次）。
`test_這一組自己不可以參與計數` 與
`test_排除清單裡的檔案必須真的存在` 兩個方向都釘住 ——
第二條是因為排除用的是硬寫的路徑，檔案改名之後排除會安靜失效。

## 為什麼要排除 `._` 開頭的檔

工作碟是 exFAT，macOS 會在旁邊放 AppleDouble 檔（`._owner.py`）。
它不是 UTF-8，`ast.parse` 之前就炸。跟 `declared-only-check.py`
同一條理由，同樣有測試釘著。
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import string
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: 列舉常數的定義從哪裡找。跟 `declared-only-check.py` 同一個目錄。
DEF_DIR = REPO / "apps" / "forseti-cli"

#: 「全 repo 出現幾次」從哪些目錄數。Python 側。
COUNT_DIRS = ("apps/forseti-cli", "tools", "tests", "src")

#: JS 側只當白名單用：一個字串在 JS 裡出現過就不算「repo 唯一」。
JS_DIRS = ("src", "desktop/ui", "tools")

#: 識別字風格。全字串匹配，所以句子、路徑、小寫鍵名不會進來。
IDENT_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$")

#: 低於這個長度不看。兩個字元的距離 1 幾乎一定是兩個不同的名字。
MIN_LEN = 3

#: 判成可疑拼錯的編輯距離上界（下界固定是 1，0 是重打不是拼錯）。
#:
#: **這是一個選擇不是一個量測。** 2026-09-17 實測放寬到 3，
#: 真 repo 一樣 0 命中 0 誤報。`test_距離3不算` 釘住的是
#: 現在這個值的行為，不是「3 一定會出事」。
MAX_DISTANCE = 2

#: 一個常數要有幾個成員才算列舉。兩種風格共用。
MIN_ENUM_MEMBERS = 2

#: 小寫鍵名風格。`"tool_use"`、`"session_id"` 這一種。
#:
#: 這一半是 2026-09-17 補的，理由寫在上一輪的紀錄裡：這個 repo 的
#: dict key 大量是小寫，同一個拼錯風險原本完全沒有人守。
LOWER_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

#: 小寫側的編輯距離上界。**這一個跟 ALL_CAPS 那一個不一樣，
#: 而且是量出來的不是選的。**
#:
#: 2026-09-17 實測（`COUNT_DIRS` 與 JS 字串白名單，還沒有屬性白名單）：
#: 距離 2 在真 repo 命中兩條，其中 `migrate.py:255` 的 `"save"`
#: 對到 `ITEMS` 的 `"name"`（距離 2）是誤報 —— 兩個都是四個字母的
#: 常用詞，語意上毫無關係。距離 1 同一次量測沒有這一條。
#:
#: **小寫短字彼此距離 2 的碰撞率遠高於 ALL_CAPS**，因為它們是
#: 自然語言的詞。所以這一側收到 1。
#:
#: 誠實的界線：加上屬性白名單之後，距離 2 在真 repo 也回到 0 命中。
#: 所以量到的是「白名單較弱時 2 會誤報而 1 不會」，
#: **不是**「有了白名單之後 2 仍然會誤報」。
LOWER_MAX_DISTANCE = 1


@dataclass(frozen=True)
class Profile:
    """一種字面值風格，以及它自己的三個閾值。

    兩種風格共用同一個掃描核心，差別只在這裡：形狀、最短長度、
    距離上界，以及要不要查屬性存取白名單。
    """
    key: str
    zh: str
    ident_re: "re.Pattern[str]"
    min_len: int
    max_distance: int
    use_attr: bool


UPPER = Profile("upper", "ALL_CAPS 常數值", IDENT_RE, MIN_LEN,
                MAX_DISTANCE, use_attr=False)

#: 小寫側多查一層屬性存取白名單，理由見 `attr_names()`。
LOWER = Profile("lower", "小寫鍵名", LOWER_RE, MIN_LEN,
                LOWER_MAX_DISTANCE, use_attr=True)

PROFILES = (UPPER, LOWER)

#: 這一組自己的兩個檔，必須一起排除在計數之外。
#:
#: **兩個都要，不是只有工具那一個。** 2026-09-17 的反向驗證就是被
#: 這件事擋下來的：把 `starvation.py` 的 `"SYNTHESIS_ONLY"` 打成
#: `"SYNTHESIS_OLNY"`，應該紅，結果綠 —— 因為
#: `tests/test_literal_restate.py` 裡有一條測試拿同一個錯字串當負例，
#: 於是「全 repo 只出現這一次」不成立。
#:
#: **測試檔裡刻意寫的錯字串，會讓真實的同一個錯字串不判紅。**
#: 往綠的方向壞，而且完全沒有聲音。改測試裡的字串只治那一次，
#: 排除這一組自己才治以後每一次 —— 跟
#: `declared-only-check.py` 的 `KINDS` 撞名同一個形狀。
#:
#: 排除是安全的：這兩個檔都不定義任何被掃的列舉常數，
#: 它們只讀檔案。
_SELF = Path(__file__).resolve()
_SELF_TEST = (REPO / "tests" / "test_literal_restate.py").resolve()
_SELF_FILES = frozenset({_SELF, _SELF_TEST})


def py_files(root: Path, *, skip_self: bool = True) -> list[Path]:
    """底下的 .py，排除 AppleDouble、`__pycache__` 與這一組自己。"""
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.py")
                  if not p.name.startswith("._")
                  and "__pycache__" not in p.parts
                  and not (skip_self and p.resolve() in _SELF_FILES))


def _parse(p: Path) -> ast.Module | None:
    try:
        return ast.parse(p.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def distance(a: str, b: str, cap: int = MAX_DISTANCE) -> int:
    """Levenshtein 距離，超過 `cap` 就不算了，回傳一個大數。

    長度差本身就是距離下界，所以先用它剪枝。
    """
    if abs(len(a) - len(b)) > cap:
        return cap + 99
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def is_ident(s: str, prof: Profile | None = None) -> bool:
    """這個字串長得像某個風格的識別字嗎。

    預設 `UPPER`，所以既有呼叫端的行為一個字都沒變。
    """
    p = prof or UPPER
    return len(s) >= p.min_len and bool(p.ident_re.match(s))


# ---------------------------------------------------------------------------
# 掃描
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Enum:
    """一個模組級列舉常數：名字，以及它列出來的那些值。"""
    module: str
    name: str
    lineno: int
    members: frozenset[str]

    @property
    def where(self) -> str:
        return f"{self.module}.py:{self.lineno}"


@dataclass(frozen=True)
class Suspect:
    """一個疑似打錯的字面字串。"""
    module: str
    lineno: int
    literal: str
    const: str
    member: str
    dist: int

    @property
    def where(self) -> str:
        return f"{self.module}.py:{self.lineno}"

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.module, self.literal, self.member)


@dataclass(frozen=True)
class Restated:
    """一個列舉成員在同檔被手打的次數（只報數字，不判紅）。"""
    module: str
    consts: tuple[str, ...]
    member: str
    lines: tuple[int, ...]

    @property
    def count(self) -> int:
        return len(self.lines)


def _const_targets(node: ast.stmt) -> list[str]:
    """這個模組級語句定義了哪些 ALL_CAPS 常數名。"""
    tg: list[ast.Name] = []
    if isinstance(node, ast.Assign):
        tg = [t for t in node.targets if isinstance(t, ast.Name)]
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        tg = [node.target]
    return [t.id for t in tg
            if t.id.isupper() and len(t.id) > 1 and not t.id.startswith("_")]


def enums_of(path: Path, tree: ast.Module,
             prof: Profile | None = None) -> tuple[list[Enum], set[int]]:
    """本檔的列舉常數，以及它們定義子樹裡所有節點的 id。

    回傳第二項是給呼叫端跳過用的：**定義自己不算重打。**
    用節點 id 而不是行號區間，因為多行的 tuple 字面值跟後面的
    程式碼在行號上會相鄰，用區間判會把邊界上的東西吃掉。
    """
    out: list[Enum] = []
    skip: set[int] = set()
    for node in tree.body:
        names = _const_targets(node)
        if not names:
            continue
        for sub in ast.walk(node):
            skip.add(id(sub))
        members = {s.value for s in ast.walk(node)
                   if isinstance(s, ast.Constant) and isinstance(s.value, str)
                   and is_ident(s.value, prof)}
        if len(members) >= MIN_ENUM_MEMBERS:
            for n in names:
                out.append(Enum(path.stem, n, node.lineno, frozenset(members)))
    return out, skip


def repo_literal_counts(*, count_dirs: tuple[str, ...] | None = None,
                        repo: Path | None = None,
                        prof: Profile | None = None) -> Counter:
    """全 repo 的 Python 側，每個識別字風格字面字串出現幾次。

    **包含定義側自己那一次。** 所以一個列舉成員至少是 1，
    一個只被打過一次的可疑字串也是 1 —— 條件 2 判的是「> 1」，
    而可疑字串本來就不在任何定義裡，所以它的 1 就是那唯一一次。
    """
    repo = repo or REPO
    count_dirs = count_dirs or COUNT_DIRS
    c: Counter = Counter()
    for d in count_dirs:
        for p in py_files(repo / d):
            tree = _parse(p)
            if tree is None:
                continue
            for s in ast.walk(tree):
                if isinstance(s, ast.Constant) and isinstance(s.value, str) \
                        and is_ident(s.value, prof):
                    c[s.value] += 1
    return c


def js_literals(*, js_dirs: tuple[str, ...] | None = None,
                repo: Path | None = None,
                prof: Profile | None = None) -> set[str]:
    """JS 側出現過的識別字風格字面字串。

    **只當白名單，不當來源。** 用正則不用 parser：這裡要的是
    「這個字串在 JS 那邊也存在」，多抓一點只會讓判紅更保守。
    """
    repo = repo or REPO
    js_dirs = js_dirs or JS_DIRS
    pf = prof or UPPER
    out: set[str] = set()
    body = pf.ident_re.pattern.strip("^$")
    pat = re.compile(r"""['"`](""" + body + r""")['"`]""")
    for d in js_dirs:
        root = repo / d
        if not root.exists():
            continue
        for ext in ("*.js", "*.mjs"):
            for p in sorted(root.rglob(ext)):
                if p.name.startswith("._"):
                    continue
                try:
                    txt = p.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                out.update(m for m in pat.findall(txt)
                           if len(m) >= pf.min_len)
    return out


#: 屬性存取形式要掃哪些目錄。比 `JS_DIRS` 廣，因為這一層是白名單，
#: 掃得越廣只會讓判紅越保守。
ATTR_DIRS = ("apps/forseti-cli", "src", "desktop/ui", "tools", "tests",
             "hooks", "adapters")

#: 屬性存取的形狀：`obj.some_key`。
_ATTR_RE = re.compile(r"\.([a-z][a-z0-9]*(?:_[a-z0-9]+)*)\b")


def attr_names(*, attr_dirs: tuple[str, ...] | None = None,
               repo: Path | None = None,
               prof: Profile | None = None) -> set[str]:
    """以 `obj.key` 形式出現過的名字。**小寫側的白名單主力。**

    ## 為什麼小寫側需要這一層而 ALL_CAPS 側不需要

    2026-09-17 量測逼出來的，不是先想好的。第一版小寫掃描在真 repo
    命中 `desktop_api.py:2091` 的 `"stale_total"`，說它像 `FEATURES`
    的 `"stall_total"`（距離 1）。

    **去查了才知道是誤報，而且兩個都是活的。** `"stale_total"`
    是身份那一頁回傳字典的鍵（陳舊 alias 有幾個），它的下游讀者是
    `desktop/ui/app.js:942` 的 `t.stale_total`；`"stall_total"`
    是停滯風險那一格的鍵，`desktop_api.py:3072` 寫它。兩個不同的東西。

    條件 2（全 repo 唯一）沒有擋住它，因為**小寫鍵名的消費端通常是
    屬性存取而不是字串字面值** —— `t.stale_total` 不是引號包起來的，
    所以字串計數看不到它。ALL_CAPS 那一側沒有這個問題，因為那些值
    幾乎只會以字串出現。

    ## 代價量出來了，而且比這一段原本寫的小很多

    這個白名單在真 repo 有 1527 個名字，而 214 個小寫列舉成員裡
    有 84 個也在裡面。**這一段原本停在這裡，而停在這裡會被讀成
    「84 個成員打錯了不會紅」。那是錯的。**

    判紅看的是**打錯之後**的那個字串在不在白名單裡，不是原成員在不在。
    成員自己在白名單裡完全不影響判紅。這兩個是不同的集合，
    而前一句很容易被讀成後一句。

    2026-09-17 量出來的（`audit_shadow()`，`--shadow` 印得出來）。
    **先量了替換，後來把少打與多打也納入，下界跟著收緊：**

    | 量了哪幾種 | 變異總數 | 只有屬性白名單擋住 | 落在幾個成員 |
    |---|---|---|---|
    | 只有替換 | 75921 | 11 | 10 |
    | 替換＋少打＋多打 | 162309 | 23 | 21 |

    只有替換那 11 個全部是短的常用英文詞（`src` 打成 `sec`、
    `git` 打成 `get`、`how` 打成 `now`），因為短詞的距離 1 鄰居
    容易也是常用詞，而常用詞容易是某個屬性名。

    **少打與多打補進來的那 12 個是另一個形狀，而且更像真的打錯。**
    十二個裡有九個是「長的那個以短的那個開頭」，也就是差在字尾
    一個字元；那九個裡有七個是真的單複數或時態（`created` 打成
    `create`、`outputs` 打成 `output`、`name` 打成 `names`、
    `transcripts` 打成 `transcript`、`actor` 打成 `actors`、
    `number` 打成 `numbers`、`resolved` 打成 `resolve`）。
    **兩個數字不一樣，不要合併** —— 另外兩個字尾形狀的
    （`insider` 打成 `inside`、`ran` 打成 `rank`）不是詞形變化，
    只是剛好也差在字尾。測試釘的是九那一個（字尾形狀），
    因為「是不是詞形變化」沒有辦法用程式判準地判。

    詞形變化那一類的兩個形式通常**都**有人以 `obj.key` 用過，
    所以白名單整類吃掉。只量替換完全看不到這個形狀 ——
    這是把下界收緊之後才長出來的資訊，不只是同一種東西變多。

    其中一條剛好是這一層白名單當初的來由反過來：
    `desktop_api.py` 的 `"stall_total"` 打成 `"stale_total"` 不會紅，
    因為 `"stale_total"` 是一個真的存在的鍵。

    代價是真的，方向往綠，跟條件 2 同一種取捨 —— 只是它的大小
    現在是一個查得到的數字，不是一句聽起來很嚴重的話。
    """
    repo = repo or REPO
    attr_dirs = attr_dirs or ATTR_DIRS
    p = prof or LOWER
    out: set[str] = set()
    for d in attr_dirs:
        root = repo / d
        if not root.exists():
            continue
        for ext in ("*.py", "*.js", "*.mjs"):
            for q in sorted(root.rglob(ext)):
                if q.name.startswith("._") or "__pycache__" in q.parts:
                    continue
                if q.resolve() in _SELF_FILES:
                    continue
                try:
                    txt = q.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                out.update(m for m in _ATTR_RE.findall(txt)
                           if len(m) >= p.min_len)
    return out


#: 底線開頭的模組級常數。`_const_targets()` 把它們排除在定義側之外。
_PRIV_RE = re.compile(r"^_+[A-Z][A-Z0-9_]*$")


def private_exposure(*, def_dir: Path | None = None,
                     prof: Profile | None = None) -> tuple[int, int, set[str]]:
    """私有列舉常數有多少成員**只**活在私有常數裡。

    ## 這一條是反向驗證撞出來的，不是想出來的

    2026-09-17 為了確認駝峰那條守門真的會紅，先植入了一個
    `_CAMEL_PROBE = ("toolUse", "sessionId")`，**結果測試沒有紅**。
    原因是 `_const_targets()` 第 3 個條件
    （`not t.id.startswith("_")`）把底線開頭的常數整批排除，
    所以私有常數從來不是定義側的一員 —— 三種風格都一樣。

    **一條恆綠的測試跟一條沒有守備的測試，在畫面上長得一模一樣。**
    這一支就是把那個差別變成數字。

    ## 機制是真的，此刻的曝險是 0，兩件事都要講

    回傳 `(常數個數, 成員總數, 只在私有常數裡出現的成員)`。
    真 repo 2026-09-17 的量：`UPPER` 3 個常數 10 個成員
    （`identity.py:696` 的 `_MARK`、`lanes.py:50` 的 `_LABEL`、
    `ledger.py:62` 的 `_OWNER_EXIT`），`LOWER` 0 個。

    **而那 10 個的曝險是 0**，因為每一個同時也是同檔某個公開列舉的
    成員（`_MARK` 的鍵對 `STATES`、`_LABEL` 的鍵對 `KINDS`、
    `_OWNER_EXIT` 的值對 `ALLOWED`）。對照組還在，所以那些成員
    打錯了照樣會紅。

    **不要把「3 個常數沒被當成定義側」講成「10 個成員沒人守」。**
    那是兩個數字，而前一句很容易被讀成後一句 —— 跟 `attr_names()`
    裡那個「84 個成員」的更正是同一個形狀的錯誤。

    ## 為什麼不順手把私有常數也納入定義側

    納入會改變判紅行為（多一批對照組，可能多出誤報），
    那要它自己的誤報量測。**此刻曝險是 0，所以改了不會多守到任何
    一個成員，只會多承擔一批沒量過的誤報風險。**
    曝險一旦不是 0，那個取捨才值得重算 —— 那時候
    `test_私有常數的曝險此刻是0` 會先紅。
    """
    def_dir = def_dir or DEF_DIR
    prof = prof or UPPER
    n_consts = 0
    total = 0
    only: set[str] = set()
    for p in sorted(q for q in def_dir.glob("*.py")
                    if not q.name.startswith("._")):
        tree = _parse(p)
        if tree is None:
            continue
        pub, _ = enums_of(p, tree, prof)
        pubmem: set[str] = set()
        for e in pub:
            pubmem |= set(e.members)
        for node in tree.body:
            names = []
            if isinstance(node, ast.Assign):
                names = [t.id for t in node.targets
                         if isinstance(t, ast.Name) and _PRIV_RE.match(t.id)]
            elif isinstance(node, ast.AnnAssign) \
                    and isinstance(node.target, ast.Name) \
                    and _PRIV_RE.match(node.target.id):
                names = [node.target.id]
            if not names:
                continue
            vals = {s.value for s in ast.walk(node)
                    if isinstance(s, ast.Constant)
                    and isinstance(s.value, str) and is_ident(s.value, prof)}
            if len(vals) >= MIN_ENUM_MEMBERS:
                n_consts += len(names)
                total += len(vals)
                only |= (vals - pubmem)
    return n_consts, total, only


# ---------------------------------------------------------------------------
# 第三種風格：駝峰。**量它，不守它，而且說得出為什麼不守。**
# ---------------------------------------------------------------------------

#: 駝峰鍵名的形狀。`"toolUse"`、`"sessionId"` 這一種。
#:
#: **這個常數存在不代表有人守駝峰。** 它只給 `camel_census()` 用，
#: 刻意不進 `PROFILES` —— 理由是量出來的，見 `camel_census()`。
CAMEL_RE = re.compile(r"^[a-z][a-z0-9]*(?:[A-Z][a-z0-9]+)+$")

#: 駝峰側的最短長度。跟另外兩種同一個值，沒有理由不一樣。
CAMEL_MIN_LEN = MIN_LEN

#: 從 JS 抓「像列舉的 const 區塊」。`const NAME = ` 開頭那一種。
_JS_CONST_RE = re.compile(r"^(?:export\s+)?const\s+([A-Z][A-Z0-9_]*)\s*=", re.M)

#: 區塊裡的字串字面值。三種引號都算，不跨行。
_JS_STR_RE = re.compile(r"""['"`]([^'"`\n]{1,60})['"`]""")

#: 一個 const 區塊最多往下看幾行。括號收平就提早停，這是防呆上界。
_JS_BLOCK_MAX_LINES = 60


def js_enum_blocks(*, js_dirs: tuple[str, ...] | None = None,
                   repo: Path | None = None,
                   prof_re: "re.Pattern[str]" | None = None,
                   min_len: int = CAMEL_MIN_LEN,
                   min_members: int = MIN_ENUM_MEMBERS,
                   ) -> tuple[int, set[str]]:
    """JS 側有幾個「像列舉」的 const 區塊，以及它們的相異成員。

    **回傳的是下界，不是精確值。** 這裡用正則不用 JS parser，
    跟 `js_literals()` 同一條理由（那一支的說明裡寫著），
    只是方向相反：那一支多抓一點只會讓判紅更保守，
    **這一支多抓或少抓都只影響一個統計數字，不影響任何判紅**。

    區塊的界線靠括號收平判，最多往下看 `_JS_BLOCK_MAX_LINES` 行。
    巢狀物件會被整塊吃進來，所以「成員」這個詞在這裡比在 Python 側鬆：
    它是「這個區塊裡出現過的、形狀符合的字串」，
    不保證它真的是某個欄位的合法值之一。
    """
    repo = repo or REPO
    js_dirs = js_dirs or JS_DIRS
    rx = prof_re or CAMEL_RE
    n_blocks = 0
    members: set[str] = set()
    for d in js_dirs:
        root = repo / d
        if not root.exists():
            continue
        for ext in ("*.js", "*.mjs"):
            for p in sorted(root.rglob(ext)):
                if p.name.startswith("._"):
                    continue
                if p.resolve() in _SELF_FILES:
                    continue
                try:
                    txt = p.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                lines = txt.split("\n")
                for m in _JS_CONST_RE.finditer(txt):
                    start = txt[:m.start()].count("\n")
                    blk: list[str] = []
                    depth = 0
                    for ln in lines[start:start + _JS_BLOCK_MAX_LINES]:
                        blk.append(ln)
                        depth += ln.count("(") + ln.count("{") + ln.count("[")
                        depth -= ln.count(")") + ln.count("}") + ln.count("]")
                        if depth <= 0:
                            break
                    vals = {v for v in _JS_STR_RE.findall("\n".join(blk))
                            if len(v) >= min_len and rx.match(v)}
                    if len(vals) >= min_members:
                        n_blocks += 1
                        members |= vals
    return n_blocks, members


@dataclass(frozen=True)
class CamelCensus:
    """駝峰這一種風格，兩側各有多少可守的東西。"""
    py_enums: int
    py_members: frozenset[str]
    js_blocks: int
    js_members: frozenset[str]

    @property
    def py_vacuous(self) -> bool:
        """Python 定義側一個駝峰列舉都沒有。

        **這一個才是「不守駝峰」這個決定的前提。** JS 那一側
        此刻不是定義來源（見檔頭盲點清單另一條），
        所以它的數字不參與這個判斷。
        """
        return self.py_enums == 0


def camel_census(*, def_dir: Path | None = None,
                 js_dirs: tuple[str, ...] | None = None,
                 repo: Path | None = None) -> CamelCensus:
    """駝峰側到底有多少東西可以守。**這是一個量測，不是一個守門。**

    ## 為什麼是量測而不是第三個 Profile

    「駝峰還沒有人守」這句話在 2026-09-17 的紀錄裡連續被推到下一輪
    三次，每一次的理由都是「判準要重想一次」。**那句話從來沒有被
    量過。** 這一輪量了，兩側的數字是：

    - **Python 定義側（`apps/forseti-cli/*.py`）：0 個駝峰列舉常數、
      0 個成員。** 掃描器的定義側只看這裡，所以加一個 `CAMEL` Profile
      進 `PROFILES`，它的 `enums` 與 `members` 會是 0 —— 一個永遠
      0 命中的風格，畫面上多一節看起來有人在守的東西，
      實際一個字都守不到。
    - **JS 側：1 個像列舉的 const 區塊、2 個成員**
      （`src/provenance.js:75` 與 `:76` 的 `'confidenceLoad'`、
      `'falseConfessions'`）。

    **而那 2 個進一步查過，不是列舉值。** 它們是 `rhetoric.js` 兩個
    函式的名字，以字串記在一張出處登記簿的 `fn:` 欄位裡
    （`src/rhetoric.js:74`、`:133` 是定義，`src/runtime.js:78`
    是 import）。一張「某個欄位的合法值有哪幾個」的清單才是這一支
    說的列舉，函式名字不是。**所以 JS 側真正的駝峰列舉材料也是 0。**

    結論：**不守駝峰不是欠一個判準，是沒有東西可守。**

    ## 這個結論自己會腐爛，所以它有守門

    跟 §40 那一批被推翻的結論同一個形狀：一句寫下來當時為真的話，
    條件變了之後沒有人會回來重跑。所以
    `test_駝峰在Python定義側必須仍然是空的` 拿這一支在真 repo 上跑，
    **Python 側一出現駝峰列舉就紅**，紅的時候該做的事是把
    `CAMEL` 加進 `PROFILES`，不是把這條測試調鬆。

    **JS 側刻意不設紅線。** JS 此刻不是定義來源，所以 JS 的駝峰長多少
    都不改變「這支工具要不要加第三個 Profile」；它改變的是另一件事
    （要不要把 JS 也變成定義側），而那一條是檔頭盲點清單裡
    獨立的一條，有它自己的數字：同一支 `js_enum_blocks()` 換上另外
    兩種形狀去量，`JS_DIRS` 底下有 **54 個 ALL_CAPS 區塊 258 個成員、
    19 個小寫區塊 149 個成員**，全部此刻無人守。
    那是駝峰的 0 的一百倍以上，**所以下一步該做的是 JS 定義側，
    不是駝峰**。（這兩組數字一樣是下界，理由同 `js_enum_blocks()`。）
    **兩件事不要合成一條紅線**，合起來會讓 JS 的任何改動去觸發一條
    它解釋不了的紅燈。
    """
    repo = repo or REPO
    def_dir = def_dir or DEF_DIR
    prof = Profile("camel", "駝峰鍵名", CAMEL_RE, CAMEL_MIN_LEN,
                   1, use_attr=True)
    n_enums = 0
    py_members: set[str] = set()
    for p in sorted(q for q in def_dir.glob("*.py")
                    if not q.name.startswith("._")):
        tree = _parse(p)
        if tree is None:
            continue
        enums, _ = enums_of(p, tree, prof)
        n_enums += len(enums)
        for e in enums:
            py_members |= set(e.members)
    js_blocks, js_members = js_enum_blocks(js_dirs=js_dirs, repo=repo)
    return CamelCensus(py_enums=n_enums, py_members=frozenset(py_members),
                       js_blocks=js_blocks,
                       js_members=frozenset(js_members))


def _report_camel(c: CamelCensus) -> None:
    print("\n── 駝峰鍵名（camel）：量它，不守它 ──")
    print(f"Python 定義側　列舉常數 {c.py_enums} 個，成員 "
          f"{len(c.py_members)} 個")
    print(f"JS 側　　　　　像列舉的 const 區塊 {c.js_blocks} 個，成員 "
          f"{len(c.js_members)} 個"
          + (f"（{'、'.join(sorted(c.js_members))}）"
             if c.js_members else ""))
    if c.py_vacuous:
        print("  ✅ Python 定義側沒有駝峰列舉，所以不加第三個 Profile，"
              "不是欠判準，是沒有東西可守。")
    else:
        print("  🔴 Python 定義側出現駝峰列舉了 ──"
              "「不守駝峰」這個決定的前提不再成立。")
        print("     該做的是把 CAMEL 加進 PROFILES，"
              "不是把那條測試調鬆。")
    print("  JS 側的數字不設紅線，理由見 `camel_census()`："
          "JS 此刻不是定義來源。")


# ---------------------------------------------------------------------------
# 白名單的代價：漏報量測
# ---------------------------------------------------------------------------

#: 變異用的字母表，依風格取。不含底線，理由見 `mutate()`。
_ALPHA = {
    "upper": string.ascii_uppercase + string.digits,
    "lower": string.ascii_lowercase + string.digits,
}

#: 三種距離 1 的打錯方式。**對調不在裡面**，理由見 `mutate()`。
MUTATION_KINDS = ("sub", "del", "ins")

#: 預設只做替換。**這是為了讓 5y 那一次量到的 11 還原得回來** ——
#: 換掉預設會讓那個數字無聲地變成另一個數字，而紀錄裡的
#: 11 就指不回任何可重跑的東西了。要更緊的下界用 `--shadow-kinds`。
DEFAULT_MUTATION_KINDS = ("sub",)

_KIND_ZH = {"sub": "替換一個字元", "del": "少打一個字元",
            "ins": "多打一個字元"}


def mutate_kinds(member: str, prof: Profile,
                 kinds: tuple[str, ...] | None = None
                 ) -> list[tuple[str, str]]:
    """一個成員的所有距離 1 變異，附上它是哪一種打錯。

    ## 三種都是距離剛好 1，這是這個量測的前提

    替換（`test`→`best`）、刪除（`tests`→`test`）、插入
    （`test`→`tests`）三種的 Levenshtein 距離都保證是 1，
    所以「有沒有被擋掉」問的純粹是白名單，不會跟距離上界糾纏。

    **相鄰對調（`ONLY` 打成 `OLNY`）不在裡面**，它的距離是 2。
    小寫側上界 1 本來就抓不到對調，把它算進來會把
    「白名單擋掉的」跟「距離上界擋掉的」混成同一個數字。

    ## 為什麼三種要分開記

    2026-09-17 之前只有替換，量到的 11 是一個下界。分開記之後
    「下界收緊了多少、是被哪一種收緊的」才是查得到的，
    而不是三個數字加起來變成一個沒有結構的總數。

    ## 去重在種類之內，不跨種類

    刪除與插入會產生重複（`abb` 在三個位置插 `b` 都得到 `abbb`），
    同一個字串算兩次會把分母灌水。**跨種類不可能重複**，
    因為三種的長度分別是 n、n-1、n+1，三個集合不相交。

    ## 為什麼不動到底線

    底線會改變形狀（`a__b` 不合這兩個風格的樣式，`_abc` 也不合），
    於是量到的就不是白名單而是形狀。替換與插入的字母表都不含底線；
    刪除本來就只會拿掉既有的字元，而拿掉底線之後的字串
    （`a_b` 少掉底線變 `ab`）形狀仍然合法，那是真的打錯方式，
    所以刪除不特別排除底線。形狀不合的變異一律不計入分母，
    見 `audit_shadow()` 的說明。
    """
    alpha = _ALPHA[prof.key]
    ks = kinds or DEFAULT_MUTATION_KINDS
    bad = [k for k in ks if k not in MUTATION_KINDS]
    if bad:
        raise ValueError(f"不認得的變異種類：{bad}，只有 {MUTATION_KINDS}")
    out: list[tuple[str, str]] = []
    for kind in MUTATION_KINDS:
        if kind not in ks:
            continue
        seen: set[str] = set()
        if kind == "sub":
            cand = (member[:i] + c + member[i + 1:]
                    for i, orig in enumerate(member)
                    for c in alpha if c != orig)
        elif kind == "del":
            cand = (member[:i] + member[i + 1:] for i in range(len(member)))
        else:
            cand = (member[:i] + c + member[i:]
                    for i in range(len(member) + 1) for c in alpha)
        for v in cand:
            if v in seen or not is_ident(v, prof):
                continue
            seen.add(v)
            out.append((kind, v))
    return out


def mutate(member: str, prof: Profile,
           kinds: tuple[str, ...] | None = None) -> list[str]:
    """`mutate_kinds()` 的字串清單版本。預設仍然只有替換。"""
    return [v for _, v in mutate_kinds(member, prof, kinds)]


@dataclass(frozen=True)
class Shadow:
    """一個打錯的字，被某一條白名單擋掉了，所以它不會紅。

    `kind` 有預設值，因為它是 2026-09-17 後來補的一欄，
    而既有的位置參數建構（`Shadow("", "", "", k).zh`）不能跟著壞。
    """
    module: str
    member: str
    typo: str
    blocker: str
    kind: str = "sub"

    @property
    def zh(self) -> str:
        return {"member": "撞上同檔另一個合法成員",
                "repo": "這個字串 repo 裡別處也有",
                "js": "JS 側有這個字串",
                "attr": "有人以 obj.key 的形式用過這個名字"}[self.blocker]

    @property
    def kind_zh(self) -> str:
        return _KIND_ZH[self.kind]


@dataclass(frozen=True)
class KindTally:
    """一種打錯方式自己的帳。

    三種分開記，不然「下界收緊了多少、是被哪一種收緊的」
    就變成一個沒有結構的總數。
    """
    kind: str
    mutations: int
    caught: int
    blocked: int
    attr_only: int

    @property
    def zh(self) -> str:
        return _KIND_ZH[self.kind]


@dataclass(frozen=True)
class ShadowAudit:
    """一次漏報量測的結果。**不判紅**，它報的是一個數字。

    `kinds` 說的是這一次量了哪幾種打錯方式。**只量了替換的那一次，
    數字是一個下界不是全部** —— 少打與多打同樣是距離 1。
    """
    profile: str
    pairs: int
    unique_members: int
    members_in_attrs: int
    mutations: int
    caught: int
    blocked: tuple[Shadow, ...]
    attr_only: tuple[Shadow, ...]
    kinds: tuple[str, ...] = DEFAULT_MUTATION_KINDS
    #: 逐種的分母，量的時候記下來。`per_kind` 用得到，別處不用直接讀。
    mut_by_kind: tuple[tuple[str, int], ...] = ()

    @property
    def blocked_by(self) -> Counter:
        return Counter(s.blocker for s in self.blocked)

    @property
    def attr_only_members(self) -> int:
        return len({(s.module, s.member) for s in self.attr_only})

    @property
    def blocked_by_kind(self) -> Counter:
        return Counter(s.kind for s in self.blocked)

    @property
    def attr_only_by_kind(self) -> Counter:
        return Counter(s.kind for s in self.attr_only)

    @property
    def per_kind(self) -> tuple[KindTally, ...]:
        """每一種打錯方式各自的分母與結果。

        分母逐種算不回來（擋掉的數得出來，會紅的數不出來），
        所以 `mut_by_kind` 是量的時候記下來的，不是事後推的。
        """
        bk = self.blocked_by_kind
        ak = self.attr_only_by_kind
        by = dict(self.mut_by_kind)
        return tuple(KindTally(k, by.get(k, 0), by.get(k, 0) - bk.get(k, 0),
                               bk.get(k, 0), ak.get(k, 0))
                     for k in self.kinds)


def audit_shadow(*, def_dir: Path | None = None,
                 count_dirs: tuple[str, ...] | None = None,
                 js_dirs: tuple[str, ...] | None = None,
                 attr_dirs: tuple[str, ...] | None = None,
                 repo: Path | None = None,
                 prof: Profile | None = None,
                 kinds: tuple[str, ...] | None = None) -> ShadowAudit:
    """把每個成員各打錯一次，數有幾次不會紅，以及被哪一條擋掉。

    ## 這一支答的是白名單的代價，不是它該不該存在

    `attr_names()` 的說明裡有一句一直沒有數字撐著：

        這個白名單在真 repo 有一千五百多個名字，而 214 個小寫列舉
        成員裡有 84 個也在裡面。一個打錯的字只要剛好撞上某個屬性名
        就不會紅。

    「84 個成員在白名單裡」跟「84 個成員打錯之後不會紅」**是兩件事**，
    而前一句很容易被讀成後一句。成員自己在白名單裡完全不影響判紅，
    因為判紅看的是那個**打錯的字串**在不在白名單裡，不是原成員。
    這一支量的是後者。

    ## 分母是什麼，不是什麼

    分母是「形狀仍然合法的距離 1 變異」，種類由 `kinds` 決定
    （預設只有替換，理由見 `DEFAULT_MUTATION_KINDS`）。形狀不合的
    （第一個字元換成數字、刪到剩兩個字元）不計入，因為那種字串
    在 `scan()` 裡根本進不到白名單那一關，把它算進去只會把
    比例稀釋掉。

    **只量替換的那一次，得到的是下界不是全部。** 少打與多打
    同樣是距離 1；相鄰對調距離是 2，三種都不包含它，
    所以無論開幾種，這個數字永遠是下界。

    ## 歸因順序跟 `scan()` 一致，不然數字對不上

    `scan()` 的判斷是 `counts[v] > 1 or v in jsl or v in attrs`，
    短路，所以 `blocker` 記的是**第一個**擋住它的那一條。
    要問「屬性白名單自己造成多少漏報」得看 `attr_only`，
    那是只有它擋住、其他三條都不擋的那些。
    """
    repo = repo or REPO
    def_dir = def_dir or DEF_DIR
    prof = prof or LOWER
    ks = tuple(kinds or DEFAULT_MUTATION_KINDS)
    counts = repo_literal_counts(count_dirs=count_dirs, repo=repo, prof=prof)
    jsl = js_literals(js_dirs=js_dirs, repo=repo, prof=prof)
    attrs = (attr_names(attr_dirs=attr_dirs, repo=repo, prof=prof)
             if prof.use_attr else set())

    per_mod: dict[str, set[str]] = {}
    for p in sorted(q for q in def_dir.glob("*.py")
                    if not q.name.startswith("._")):
        tree = _parse(p)
        if tree is None:
            continue
        enums, _ = enums_of(p, tree, prof)
        if not enums:
            continue
        per_mod[p.stem] = set().union(*(e.members for e in enums))

    uniq: set[str] = set()
    for ms in per_mod.values():
        uniq |= ms

    pairs = 0
    mutations = 0
    caught = 0
    by_kind: Counter = Counter()
    blocked: list[Shadow] = []
    attr_only: list[Shadow] = []

    for mod, all_members in sorted(per_mod.items()):
        for mem in sorted(all_members):
            pairs += 1
            for kind, v in mutate_kinds(mem, prof, ks):
                mutations += 1
                by_kind[kind] += 1
                if v in all_members:
                    blocked.append(Shadow(mod, mem, v, "member", kind))
                    continue
                hit = {"repo": counts[v] > 1, "js": v in jsl,
                       "attr": v in attrs}
                first = next((k for k in ("repo", "js", "attr") if hit[k]), None)
                if first is None:
                    caught += 1
                    continue
                s = Shadow(mod, mem, v, first, kind)
                blocked.append(s)
                if hit["attr"] and not hit["repo"] and not hit["js"]:
                    attr_only.append(s)

    return ShadowAudit(profile=prof.key, pairs=pairs,
                       unique_members=len(uniq),
                       members_in_attrs=len(uniq & attrs),
                       mutations=mutations, caught=caught,
                       blocked=tuple(blocked), attr_only=tuple(attr_only),
                       kinds=ks,
                       mut_by_kind=tuple((k, by_kind.get(k, 0)) for k in ks))


def _report_shadow(a: ShadowAudit) -> None:
    prof = next(p for p in PROFILES if p.key == a.profile)
    kz = "、".join(_KIND_ZH[k] for k in a.kinds)
    print(f"\n── {prof.zh}（{prof.key}）白名單的代價 ──")
    print(f"成員 {a.pairs} 個（獨立字串 {a.unique_members} 個，"
          f"其中 {a.members_in_attrs} 個自己也在屬性白名單裡）。")
    print(f"距離 1 的變異 {a.mutations} 個（{kz}），"
          f"其中 {a.caught} 個會紅，{len(a.blocked)} 個不會。")
    if len(a.kinds) > 1:
        print("  逐種（分母／會紅／不會紅／只有屬性白名單擋住）：")
        for t in a.per_kind:
            print(f"    {t.kind:<4} {t.zh}　"
                  f"{t.mutations:>6} ／ {t.caught:>6} ／ "
                  f"{t.blocked:>4} ／ {t.attr_only:>3}")
    print("  對調（距離 2）任何一種都沒有量，所以這是下界。")
    if a.blocked:
        by = a.blocked_by
        print("  不會紅的，被哪一條擋掉（照 scan() 的短路順序）：")
        for k in ("member", "repo", "js", "attr"):
            if by.get(k):
                zh = Shadow("", "", "", k).zh
                print(f"    {k:<8} {by[k]:>5}　{zh}")
    if not prof.use_attr:
        print("  這個風格不查屬性白名單，所以它的代價是 0。")
        return
    print(f"  只有屬性白名單擋住的：{len(a.attr_only)} 個變異，"
          f"落在 {a.attr_only_members} 個成員上。")
    for s in a.attr_only:
        print(f'    {s.module}.py  "{s.member}" 打成 "{s.typo}" '
              f'不會紅（{s.kind_zh}）')


# ---------------------------------------------------------------------------
# 豁免登記簿
# ---------------------------------------------------------------------------

#: 已知合法、但三個條件都命中的字串，以及為什麼它不是拼錯。
#:
#: 跟 `declared-only-check.py` 的 `REGISTRY` 同一個約定：
#: **清單以外的新增一律紅，清單自己也不准腐爛**（登記的東西
#: 不再命中就要拿掉，不然它會一直宣稱一件已經不成立的事）。
#:
#: 2026-09-17 建立時真 repo 命中 0，所以這張表是空的。
#: 它空著是一個結果不是一個佔位 —— 第一條進來的時候，
#: `why` 要指得回一個查得到的位置，跟那一支同一條規則。
EXEMPT: dict[tuple[str, str, str], str] = {}


def _exempt(module: str, literal: str, member: str, why: str) -> None:
    EXEMPT[(module, literal, member)] = why


# ---------------------------------------------------------------------------
# 報告
# ---------------------------------------------------------------------------

@dataclass
class Report:
    enums: int
    members: int
    suspects: list[Suspect]
    restated: list[Restated]
    profile: str = UPPER.key
    _hit_keys: set[tuple[str, str, str]] = field(default_factory=set)

    @property
    def unexempted(self) -> list[Suspect]:
        return [s for s in self.suspects if s.key not in EXEMPT]

    @property
    def stale_exempt(self) -> list[tuple[tuple[str, str, str], str]]:
        """登記的豁免已經不命中了，清單該清。

        **這一份只看自己這個風格的命中。** 兩個風格共用一張
        `EXEMPT`，所以單獨拿一份 Report 問這件事，另一個風格登記的
        豁免會被誤判成過期。跨風格要問 `stale_across()`，
        `main()` 用的是那一個。
        """
        return [(k, "登記的豁免現在不再命中，清單該清")
                for k in EXEMPT if k not in self._hit_keys]

    @property
    def restated_total(self) -> int:
        return sum(r.count for r in self.restated)


def scan(*, def_dir: Path | None = None,
         count_dirs: tuple[str, ...] | None = None,
         js_dirs: tuple[str, ...] | None = None,
         attr_dirs: tuple[str, ...] | None = None,
         repo: Path | None = None,
         prof: Profile | None = None) -> Report:
    """跑一次完整掃描。

    每個目錄都可以換掉，測試才有辦法在合成的小目錄上跑完整流程。
    **對真 repo 斷言的測試會隨開發腐爛**，腐爛的測試會被調鬆。
    """
    repo = repo or REPO
    def_dir = def_dir or DEF_DIR
    prof = prof or UPPER
    counts = repo_literal_counts(count_dirs=count_dirs, repo=repo, prof=prof)
    jsl = js_literals(js_dirs=js_dirs, repo=repo, prof=prof)
    attrs = (attr_names(attr_dirs=attr_dirs, repo=repo, prof=prof)
             if prof.use_attr else set())

    n_enums = 0
    members: set[tuple[str, str]] = set()
    suspects: list[Suspect] = []
    restated: list[Restated] = []

    for p in sorted(q for q in def_dir.glob("*.py")
                    if not q.name.startswith("._")):
        tree = _parse(p)
        if tree is None:
            continue
        enums, skip = enums_of(p, tree, prof)
        if not enums:
            continue
        n_enums += len(enums)
        all_members = set().union(*(e.members for e in enums))
        members.update((p.stem, m) for m in all_members)
        owners: dict[str, list[str]] = {}
        for e in enums:
            for m in e.members:
                owners.setdefault(m, []).append(e.name)

        hits: dict[str, list[int]] = {}
        for sub in ast.walk(tree):
            if id(sub) in skip:
                continue
            if not (isinstance(sub, ast.Constant) and isinstance(sub.value, str)):
                continue
            v = sub.value
            if not is_ident(v, prof):
                continue
            if v in all_members:
                hits.setdefault(v, []).append(sub.lineno)
                continue
            # 條件 2：全 repo 唯一，JS 側也沒有，小寫側再加屬性存取。
            if counts[v] > 1 or v in jsl or v in attrs:
                continue
            # 條件 3：跟本檔某個成員距離在 1 到這個風格的上界之間。
            best: tuple[str, str, int] | None = None
            for e in enums:
                for m in e.members:
                    d = distance(v, m, cap=prof.max_distance)
                    if 1 <= d <= prof.max_distance \
                            and (best is None or d < best[2]):
                        best = (e.name, m, d)
            if best is not None:
                suspects.append(Suspect(p.stem, sub.lineno, v, *best))

        for v, lines in sorted(hits.items()):
            restated.append(Restated(p.stem, tuple(sorted(owners[v])), v,
                                     tuple(sorted(lines))))

    # 同一處可能對到多個成員，只留距離最小的那一條。
    dedup: dict[tuple[str, int, str], Suspect] = {}
    for s in suspects:
        k = (s.module, s.lineno, s.literal)
        if k not in dedup or s.dist < dedup[k].dist:
            dedup[k] = s
    suspects = sorted(dedup.values(), key=lambda s: (s.module, s.lineno))

    rep = Report(enums=n_enums, members=len(members),
                 suspects=suspects, restated=restated, profile=prof.key)
    rep._hit_keys = {s.key for s in suspects}
    return rep


def scan_all(**kw) -> dict[str, Report]:
    """兩種風格各掃一次，回傳以 `Profile.key` 為鍵的報告。"""
    return {p.key: scan(prof=p, **kw) for p in PROFILES}


def stale_across(reports: dict[str, Report]) -> list[tuple[tuple[str, str, str], str]]:
    """跨所有風格算過期的豁免。

    單獨一份 Report 只看得到自己那個風格的命中，
    所以「這條豁免還命中嗎」要把兩邊的命中聯集起來才問得準。
    """
    hit: set[tuple[str, str, str]] = set()
    for r in reports.values():
        hit |= r._hit_keys
    return [(k, "登記的豁免現在不再命中，清單該清")
            for k in EXEMPT if k not in hit]


def _report_one(rep: Report, show_restated: bool) -> bool:
    """印一個風格的結果，回傳這個風格有沒有紅。"""
    prof = next(p for p in PROFILES if p.key == rep.profile)
    print(f"\n── {prof.zh}（{prof.key}，距離上界 {prof.max_distance}"
          f"{'，含屬性白名單' if prof.use_attr else ''}）──")
    print(f"列舉常數 {rep.enums} 個，成員 {rep.members} 個，"
          f"同檔被手打的 {len(rep.restated)} 組共 {rep.restated_total} 次。")

    if show_restated:
        for r in sorted(rep.restated, key=lambda r: -r.count)[:40]:
            print(f"  {r.module}.py  {r.member:<26} x{r.count}  "
                  f"（{'/'.join(r.consts)}　行 "
                  f"{', '.join(str(n) for n in r.lines[:6])}）")

    if not rep.unexempted:
        print("  ✅ 沒有疑似打錯的字面值。")
        return False

    print(f"  🔴 疑似打錯 {len(rep.unexempted)} 處 ──")
    print("  這個字串全 repo 只出現這一次，而它跟同檔某個列舉成員"
          "只差一兩個字元。")
    for s in rep.unexempted:
        print(f'    {s.where:<28} "{s.literal}"')
        print(f'        像 {s.const} 的 "{s.member}"（距離 {s.dist}）')
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--restated", action="store_true",
                    help="列出被手打的成員與次數（不判紅）")
    ap.add_argument("--shadow", action="store_true",
                    help="量白名單的代價：每個成員各打錯一次，"
                         "有幾次不會紅（不判紅）")
    ap.add_argument("--shadow-kinds", default=",".join(DEFAULT_MUTATION_KINDS),
                    help="量哪幾種距離 1 的打錯，逗號分隔："
                         "sub 替換／del 少打／ins 多打。"
                         f"預設 {','.join(DEFAULT_MUTATION_KINDS)}")
    ap.add_argument("--camel", action="store_true",
                    help="量駝峰側有多少東西可守（不判紅，"
                         "理由見 camel_census）")
    ap.add_argument("--profile", choices=[p.key for p in PROFILES] + ["both"],
                    default="both",
                    help="只掃一種風格，預設兩種都掃")
    a = ap.parse_args(argv)

    want = [p for p in PROFILES if a.profile in (p.key, "both")]
    ks = tuple(x for x in a.shadow_kinds.split(",") if x)
    bad_ks = [k for k in ks if k not in MUTATION_KINDS]
    if bad_ks:
        ap.error(f"--shadow-kinds 不認得 {bad_ks}，只有 {MUTATION_KINDS}")
    reps = {p.key: scan(prof=p) for p in want}
    stale = stale_across(reps)
    shadows = ({p.key: audit_shadow(prof=p, kinds=ks) for p in want}
               if a.shadow else {})
    camel = camel_census() if a.camel else None

    if a.json:
        print(json.dumps({
            "profiles": {
                k: {
                    "enums": r.enums,
                    "members": r.members,
                    "suspects": [{"where": s.where, "literal": s.literal,
                                  "const": s.const, "member": s.member,
                                  "distance": s.dist} for s in r.suspects],
                    "unexempted": [s.where + " " + s.literal
                                   for s in r.unexempted],
                    "restated_groups": len(r.restated),
                    "restated_total": r.restated_total,
                } for k, r in reps.items()},
            "stale_exempt": [list(k) + [why] for k, why in stale],
            **({"camel": {
                "py_enums": camel.py_enums,
                "py_members": sorted(camel.py_members),
                "js_blocks": camel.js_blocks,
                "js_members": sorted(camel.js_members),
                "py_vacuous": camel.py_vacuous,
            }} if camel is not None else {}),
            **({"shadow": {
                k: {
                    "pairs": a.pairs,
                    "unique_members": a.unique_members,
                    "members_in_attrs": a.members_in_attrs,
                    "kinds": list(a.kinds),
                    "mutations": a.mutations,
                    "caught": a.caught,
                    "blocked": dict(a.blocked_by),
                    "blocked_by_kind": dict(a.blocked_by_kind),
                    "per_kind": [{"kind": t.kind, "mutations": t.mutations,
                                  "caught": t.caught, "blocked": t.blocked,
                                  "attr_only": t.attr_only}
                                 for t in a.per_kind],
                    "attr_only": [{"module": s2.module, "member": s2.member,
                                   "typo": s2.typo, "kind": s2.kind}
                                  for s2 in a.attr_only],
                    "attr_only_members": a.attr_only_members,
                } for k, a in shadows.items()}} if shadows else {}),
        }, ensure_ascii=False, indent=2))
        bad = any(r.unexempted for r in reps.values()) or bool(stale)
        return 1 if bad else 0

    print("手打本身不判紅（理由見檔頭「不回答哪一個」），"
          "判紅的只有疑似打錯的那一次。")

    bad = False
    for p in want:
        if _report_one(reps[p.key], a.restated):
            bad = True

    for p in want:
        if p.key in shadows:
            _report_shadow(shadows[p.key])

    if camel is not None:
        _report_camel(camel)

    if stale:
        bad = True
        print(f"\n🔴 豁免登記簿自己過期了 {len(stale)} 條 ──")
        for (m, lit, mem), why in stale:
            print(f'  {m}　"{lit}" ~ "{mem}"　{why}')
    elif not bad:
        print("\n✅ 兩種風格都沒有疑似打錯的字面值，"
              "豁免登記簿沒有過期的條目。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
