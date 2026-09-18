#!/usr/bin/env python3
"""模組級常數裡，哪幾個從來沒有人讀。

## 為什麼有這一支

§40 污染登記簿第一筆的機制寫著：

    看到常數名稱就當成功能存在。那個常數旁邊五行就寫著它沒實作，
    但判斷在讀到說明之前就已經下完了。

那一筆講的是 `event_ledger.py:122` 的 `LINEAGE_EDGES` —— 十個 lineage
邊的名字都在，讀的人以為邊可以走，實際上一條都沒有實作。

**登記一筆污染改掉的是那一次的結論，不是下一次的機制。** 同一個形狀
可以再長出來，而且沒有任何東西會紅。這一支就是那個會紅的東西：
一個常數的名字或註解宣稱了某件事，而整個 Python 側沒有任何人讀它，
這件事從此是一個每次都會重算的數字，不是誰記得。

## 它回答哪一個問題，不回答哪一個

回答：**這個常數從頭到尾沒有被任何 Python 程式碼讀過。**

不回答：這是不是一個 bug。那需要判斷，而判斷會飄。所以分類寫在
`REGISTRY` 裡由人填，每一條附得出原文依據；這支只負責「清單以外
的新增一律紅」，以及「清單自己不准腐爛」。

`REGISTRY` 的 `kind` 有三個值，它們是三種不同的帳，不是三種放行：

- `REFERENCE`　這個常數存在的目的就是給人讀，不是給程式讀。
　　規格照抄、已知偏差登記屬於這一類。處置：不用動。
- `DECLARED_ONLY`　名字或註解宣稱了一個行為，而那個行為沒有實作。
　　**進清單不是結案，是登記在案。** 收尾時會單獨再列一次。
　　處置：補實作，或把那句宣稱改成它真正的樣子。
- `LEFTOVER`　既沒有宣稱行為，也沒有人讀，看起來是搬動之後留下的。
　　處置：**這一支不替人決定要刪還是要接。** 一個沒人讀的名字
　　不等於一段沒有用的程式碼，那個判斷要有人看過上下文才做得了。

## 怎麼判定「被讀」

用 AST，而且盡量歸屬到模組，不是比對名字。理由是這個 repo 裡有 24 組
同名常數（`STATES` 在六個檔裡），純比名字的話只要有一個檔的 `STATES`
被讀，六個都算被讀 —— 那是往綠的方向壞。

歸屬得到的三種：

1. 同檔內裸名讀取（`ast.Name` Load，且本檔定義了它）
2. `import x` 之後 `x.NAME`（追 import 別名）
3. `from x import NAME`

歸屬不到的（別的模組來的 `something.NAME`、或裸名而本檔沒定義）算成
**弱引用**：列出來，但不判紅。誤報會讓守門被關掉，那比漏報更糟。

## 這一支自己的盲點，寫在這裡不是只寫在紀錄裡

- **字串取用抓不到。** `getattr(m, "FIELDS")` 或 `globals()["FIELDS"]`
  這種，AST 看到的是字串不是名字。往綠的方向壞。
- **只掃 Python。** 常數的值被 JS 或 shell 以字面字串重打一次的情形
  （`starvation.py` 的 `RECOVERY_STEPS` 就是，`recovery_plan()` 在下面
  十行手打同樣五個字串），這一支看不到，因為那不是「讀這個常數」。
- **弱引用算被讀。** 上面那個取捨的代價：一個真的沒人讀的常數，只要
  repo 裡別處有同名的 `x.NAME`，它就不會紅。
- **`from x import *` 之後無從歸屬。** 目前 repo 裡沒有，真的出現時
  掃描器會在報告裡講一句，不會安靜當作沒事。
- **數的是「有沒有人讀」，不是「讀了有沒有用對」。** 一個被讀進來
  然後丟掉的常數，這一支照樣綠。

## 為什麼要排除 `._` 開頭的檔

工作碟是 exFAT，macOS 會在旁邊放 AppleDouble 檔（`._advicetrack.py`）。
它不是 UTF-8，`ast.parse` 之前就炸。寫這一支的第一次執行就是這樣死的，
所以排除規則有測試釘著，不是靠下一個人記得。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: 常數定義從哪裡找。
DEF_DIR = REPO / "apps" / "forseti-cli"

#: 讀取從哪裡找。三個目錄都算，因為測試讀一個常數也是讀。
READ_DIRS = ("apps/forseti-cli", "tools", "tests")


#: 這一支自己的路徑。底線開頭，所以它不會被自己當成模組級常數收錄。
_SELF = Path(__file__).resolve()


def py_files(root: Path, recurse: bool = True, skip_self: bool = True):
    """底下的 .py，排除 AppleDouble 與這一支自己。

    兩條排除各有理由，各有測試釘著：

    一，**AppleDouble。** 工作碟是 exFAT，macOS 會放 `._x.py`，
    　　它不是 UTF-8，`ast.parse` 之前就炸（見檔頭最後一節）。

    二，**這一支自己。** `tools/` 在 `READ_DIRS` 底下，所以掃描器的
    　　模組級名字會被自己掃到，而一個撞名會讓被掃側那個真正沒人讀的
    　　常數變成「有弱引用」，安靜地從紅名單消失。第一版就發生過
    　　（`KINDS` 撞掉 `lanes.py:48`）。改名只治那一次，排除自己才治
    　　以後每一次 —— 而排除是安全的，因為這一支不讀任何
    　　`apps/forseti-cli` 的常數，它只讀檔案。
    """
    it = root.rglob("*.py") if recurse else root.glob("*.py")
    return sorted(p for p in it
                  if not p.name.startswith("._")
                  and "__pycache__" not in p.parts
                  and not (skip_self and p.resolve() == _SELF))


def _parse(p: Path) -> ast.Module | None:
    try:
        return ast.parse(p.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


@dataclass(frozen=True)
class Const:
    """一個模組級常數的位置。"""
    module: str
    name: str
    lineno: int

    @property
    def where(self) -> str:
        return f"{self.module}.py:{self.lineno}"


def module_consts(path: Path) -> list[Const]:
    """這個檔的模組級 ALL_CAPS 常數。

    只認 module level：函式或 class 裡面的不算，那些不是對外的名字。
    底線開頭的也不算（`_CACHE_VERSION` 這種是私有實作細節，
    它沒有在對外宣稱任何東西）。
    """
    tree = _parse(path)
    if tree is None:
        return []
    out = []
    for node in tree.body:
        targets: list[ast.Name] = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        for t in targets:
            n = t.id
            if n.isupper() and len(n) > 1 and not n.startswith("_"):
                out.append(Const(path.stem, n, node.lineno))
    return out


@dataclass
class Reads:
    """誰讀了什麼。

    `strong` 歸屬得到模組，`weak` 歸屬不到 —— 兩個分開存，因為
    只有 `strong` 可以拿來判紅（檔頭「怎麼判定被讀」那一節）。
    """
    strong: set[tuple[str, str]] = field(default_factory=set)
    weak: set[str] = field(default_factory=set)
    star_imports: set[str] = field(default_factory=set)


def _import_map(tree: ast.Module, known: set[str]) -> dict[str, str]:
    """本檔的 `import x as y` 對照表，只收 forseti-cli 自己的模組。"""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                stem = a.name.split(".")[-1]
                if stem in known:
                    out[a.asname or a.name] = stem
    return out


def scan_reads(known_modules: set[str], defined_here: dict[str, set[str]],
               *, def_dir: Path | None = None,
               roots: tuple[Path, ...] | None = None) -> Reads:
    """走一遍所有 Python，記下誰讀了哪個模組的哪個名字。

    `def_dir` 與 `roots` 可以換掉，測試才有辦法在一個合成的小目錄上
    跑完整流程。**對真 repo 斷言的測試會隨開發腐爛**，而腐爛的測試
    會被調鬆；合成目錄的那幾條不會。
    """
    def_dir = def_dir or DEF_DIR
    roots = roots or tuple(REPO / d for d in READ_DIRS)
    r = Reads()
    for root in roots:
        for p in py_files(root):
            tree = _parse(p)
            if tree is None:
                continue
            imap = _import_map(tree, known_modules)
            own = defined_here.get(p.stem, set()) if p.parent == def_dir else set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    stem = (node.module or "").split(".")[-1]
                    for a in node.names:
                        if a.name == "*":
                            if stem in known_modules:
                                r.star_imports.add(stem)
                        elif stem in known_modules:
                            r.strong.add((stem, a.name))
                elif isinstance(node, ast.Attribute):
                    base = node.value
                    if isinstance(base, ast.Name) and base.id in imap:
                        r.strong.add((imap[base.id], node.attr))
                    else:
                        r.weak.add(node.attr)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    if node.id in own:
                        r.strong.add((p.stem, node.id))
                    else:
                        r.weak.add(node.id)
    return r


def _def_line(c: Const) -> int:
    """定義自己那一行不算讀。

    `ast.Assign` 的 target 是 Store 不是 Load，所以其實抓不到 ——
    這個函式留著是為了讓「不算自己」這件事寫得出來，不是靠 ctx
    這個實作細節碰巧成立。
    """
    return c.lineno


# ---------------------------------------------------------------------------
# 登記簿
# ---------------------------------------------------------------------------

#: 已知從來沒有人讀的常數，以及為什麼。
#:
#: 每一條的 `why` 必須指得回原文（註解、檔頭、規格節號），不是推測。
#: 清單以外的新增一律紅 —— 這才是這一支的重點：下一個
#: 「只定義未實作」不能安靜地出現。
#:
#: **這張表不是免死金牌。** `DECLARED_ONLY` 那幾條是登記在案的空殼，
#: 每次執行都會被單獨再列一次。
REGISTRY: dict[tuple[str, str], dict] = {}


def _reg(module: str, name: str, kind: str, why: str) -> None:
    assert kind in REG_KINDS, kind
    REGISTRY[(module, name)] = {"kind": kind, "why": why}


# 以下每一條的依據都是 2026-09-17 實際打開那個檔讀到的原文。
# 「字面字串 N 次」那種數字是 grep 實測，不是估的。

#: 三種帳的名字。
#:
#: **前綴不是裝飾。** 這一支自己也在 `READ_DIRS` 底下，所以它的模組級
#: 名字會被自己掃到 —— 第一版這裡叫 `KINDS`，結果 `lanes.py:48` 真正
#: 沒人讀的那個 `KINDS` 被判成「有弱引用」，安靜地從紅名單消失。
#: 那是檔頭盲點第三條（弱引用算被讀）第一次真的發生，而且是這一支
#: 自己造成的。`test_這一支自己的名字不可以跟被掃的常數撞名` 釘住。
REG_KINDS = ("REFERENCE", "DECLARED_ONLY", "LEFTOVER")

# ── 空殼：名字宣稱了行為，行為不存在 ──────────────────────

# 【2026-09-18 移除】`event_ledger.LINEAGE_EDGES` 先前登記成 DECLARED_ONLY。
# `lineage.py` 把它接成 `add()` 的邊型別白名單之後，它不再是空殼:
# 不在這張表裡的型別會被拒收，而且有測試植入不合法的型別驗過退回
# （`tests/test_lineage.py` 的 `拒收` 那一組）。
#
# **移除的理由是行為，不是「現在有人讀」。** 只是被讀到就把登記拿掉
# 的話，等於為了讓偵測器變綠而插一個讀取 —— 那正是 B-15
# 「不要做的事」那一段講的形狀。
#
# 同一天 `event_ledger.SPEC_DEVIATIONS` 也從 REFERENCE 移除:
# 它先前的理由是「本來就是寫給人讀的」，而 2026-09-18 起
# `tests/test_lineage.py` 會驗它那一行講的理由跟量到的一致。
# 一個有人守著不會腐爛的常數，不需要一筆豁免。

_reg("worker", "RAW_INLINE_LIMIT", "DECLARED_ONLY",
     "2026-09-17 這一支第一次執行就找到的，先前沒有人知道。"
     "註解寫「超過這個大小的原始輸出一律落檔,不進 packet」，"
     "檔頭第 24 行也寫「raw log 一律落檔」，"
     "而全 repo 只有定義那一行加 `docs/PROGRESS_2026-09-09.md:243`"
     "把它列成一條已生效的規則（標「拍的」）。"
     "隔壁 `SUMMARY_LIMIT` 與 `LIST_LIMIT` 都在 `check()` 裡真的被執行，"
     "只有這一個沒有 —— 落檔的 `stash_raw()` 存在，但沒有任何地方"
     "拿這個門檻去判斷要不要叫它。**跟 LINEAGE_EDGES 同形狀，"
     "而且比它危險：那一個的註解誠實寫著沒實作，這一個用的是直述句。**"
     "怎麼處置是政策（超過就拒收，還是超過就自動落檔），留給 owner。")

# ── 規格照抄：存在目的是給人對照，值在別處以字面字串使用 ──────
#
# 這一類共同的代價寫在檔頭盲點第二條：字面字串拼錯不會紅，因為
# 沒有人拿這張表去驗。那是一個真實的缺口，但它不是「這個常數沒用」。

_reg("authority", "DECISIONS", "REFERENCE",
     "§9.2 的四種決定。`\"PREPARE\"` 在同檔以字面字串出現 2 次。")

_reg("betrayal", "GRADE_MEANING", "REFERENCE",
     "兩個等級的意思，給人讀的說明。隔壁 `GRADES` 有人讀，"
     "`\"CANDIDATE\"` 在同檔以字面字串出現 4 次。")

_reg("evidence", "EPISTEMIC", "REFERENCE",
     "§8.3 的九個認知狀態。`\"UNSUPPORTED_FILL\"` 在同檔以字面字串"
     "出現 2 次，隔壁 `LEGAL_FROM` 有人讀。")

_reg("goalgate", "SOURCE_OWNER_NOW", "REFERENCE",
     "註解自己寫著存在理由：「這裡不複製數值，只記名字；"
     "數值在 goalanchor.js」。值 `EXPLICIT_OWNER_INSTRUCTION` "
     "確實在 `src/goalanchor.js:41` 與 `tests/test_goalgate.py:210`。")

_reg("intervene", "PLANES", "REFERENCE",
     "兩個平面的名字。`\"INTERVENTION\"` 在同檔以字面字串出現 3 次。")

_reg("lanes", "KINDS", "REFERENCE",
     "五種軌道。下面五行的 `_LABEL` 用同樣五個字面字串當 key，"
     "`\"BLIND_WRITE\"` 在同檔出現 3 次。")

_reg("latency", "RECOVERY", "REFERENCE",
     "三種修正結局。`\"SELF_RECOVERED\"` 在同檔以字面字串出現 3 次。")

_reg("pollution", "REQUIRES", "REFERENCE",
     "2026-09-17 查出來的第二件，跟 `RAW_INLINE_LIMIT` 並列。"
     "這張表寫「REVERIFIED 要附 verifier、RESOLVED 要附 "
     "preventive_rule 或 regression_probe」，而**那兩條規則真的有被執行**"
     " —— 執行的是 `_missing_for()` 第 180 與 183 行手寫的 if，"
     "不是這張表。也就是同一條規則有兩份，改這張表不會改變任何行為。"
     "分類是 REFERENCE 因為行為在（不是空殼），但它比別的 REFERENCE "
     "危險：它看起來像規則的來源。")

_reg("pollution", "FIELDS", "REFERENCE",
     "註解寫「§40.1 的欄位,逐字照抄」。逐字照抄的表就是拿來對規格的。")

_reg("pollution", "OPTIONAL", "REFERENCE",
     "跟 `FIELDS` 同一段（`pollution.py:86` 起），標哪兩個是選填。"
     "依據是那一段的註解「§40.1 的欄位,逐字照抄。"
     "後面兩個規格標了問號(選填)」。")

_reg("rehydration", "COVERAGE", "REFERENCE",
     "F08 §5 的七級（跟 Vol2 §4 同一張表）。"
     "`\"VERIFIED_UNDERSTANDING\"` 在同檔以字面字串出現 3 次，"
     "隔壁 `FULL_ENOUGH` 有人讀。")

_reg("starvation", "FAILURE_CLASSES", "REFERENCE",
     "F07 §2 的五個可觀測失效類別。"
     "`\"OUTPUT_STARVATION\"` 在同檔以字面字串出現 2 次。")

_reg("starvation", "RECOVERY_STEPS", "REFERENCE",
     "F07 §4 的五個恢復步驟。下面十行的 `recovery_plan()` 手打同樣"
     "五個字面字串，`\"SYNTHESIS_ONLY\"` 在同檔出現 2 次。"
     "**這一條是檔頭盲點第二條最清楚的例子。**")

_reg("vitals", "SUPPORT_RISK", "REFERENCE",
     "註解寫「Formal Spec §7.8 的六級,原文的風險貢獻值照抄」。"
     "`\"CONFLICTING\"` 在同檔以字面字串出現 4 次。")

# ── 留下來的 ──────────────────────────────────────────────

_reg("blast", "SRC", "LEFTOVER",
     "`blast.py:64` 的 `REPO / \"src\"`。這個模組掃 JS 走的是"
     "`JS_SCAN_DIRS`（`blast.py:79`，第一項就是 \"src\"），"
     "掃 .py 走 `SCAN_DIRS`（`blast.py:69`），沒有任何地方讀這個路徑。"
     "**沒有替它決定要刪還是要接** —— 一個沒人讀的名字不等於"
     "一段沒有用的程式碼。")


# ---------------------------------------------------------------------------
# 掃描與報告
# ---------------------------------------------------------------------------

@dataclass
class Report:
    """一次掃描的結果。

    `unread` 是完全沒有強引用也沒有弱引用的；`weak_only` 是只有
    歸屬不到的同名引用。兩者分開，因為只有前者判得了紅。
    """
    total: int
    unread: list[Const]
    weak_only: list[Const]
    star_imports: list[str]

    @property
    def unregistered(self) -> list[Const]:
        return [c for c in self.unread if (c.module, c.name) not in REGISTRY]

    @property
    def declared_only(self) -> list[Const]:
        return [c for c in self.unread
                if REGISTRY.get((c.module, c.name), {}).get("kind") == "DECLARED_ONLY"]

    @property
    def stale_registry(self) -> list[tuple[str, str, str]]:
        """清單自己腐爛的兩種方式。

        一，登記的常數不存在了（改名或刪掉）。
        二，登記的常數現在有人讀了 —— 這是好消息，但清單要跟著改，
        　　不然它會一直宣稱一件已經不成立的事。
        """
        live = {(c.module, c.name) for c in self.unread}
        here = {(c.module, c.name) for c in self._all}
        out = []
        for key in REGISTRY:
            if key not in here:
                out.append((*key, "登記的常數已經不在了"))
            elif key not in live:
                out.append((*key, "登記說沒人讀，實際上現在有人讀"))
        return out

    _all: list[Const] = field(default_factory=list)


def scan(*, def_dir: Path | None = None,
         roots: tuple[Path, ...] | None = None) -> Report:
    def_dir = def_dir or DEF_DIR
    defs: list[Const] = []
    for p in py_files(def_dir, recurse=False):
        defs.extend(module_consts(p))
    known = {c.module for c in defs}
    defined_here: dict[str, set[str]] = {}
    for c in defs:
        defined_here.setdefault(c.module, set()).add(c.name)
    r = scan_reads(known, defined_here, def_dir=def_dir, roots=roots)
    unread, weak_only = [], []
    for c in defs:
        if (c.module, c.name) in r.strong:
            continue
        if c.name in r.weak:
            weak_only.append(c)
        else:
            unread.append(c)
    rep = Report(total=len(defs), unread=unread, weak_only=weak_only,
                 star_imports=sorted(r.star_imports))
    rep._all = defs
    return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    ap.add_argument("--list-weak", action="store_true",
                    help="連只有弱引用的也列出來（不判紅）")
    a = ap.parse_args(argv)

    rep = scan()

    if a.json:
        print(json.dumps({
            "total": rep.total,
            "unread": [{"where": c.where, "name": c.name,
                        "kind": REGISTRY.get((c.module, c.name), {}).get("kind")}
                       for c in rep.unread],
            "unregistered": [c.where + " " + c.name for c in rep.unregistered],
            "declared_only": [c.where + " " + c.name for c in rep.declared_only],
            "stale_registry": rep.stale_registry,
            "weak_only": len(rep.weak_only),
            "star_imports": rep.star_imports,
        }, ensure_ascii=False, indent=2))
        return 1 if (rep.unregistered or rep.stale_registry) else 0

    print(f"模組級常數 {rep.total} 個，"
          f"沒有任何人讀的 {len(rep.unread)} 個，"
          f"只有歸屬不到的同名引用 {len(rep.weak_only)} 個。")

    if rep.star_imports:
        print(f"\n⚠ 有 from x import * （{', '.join(rep.star_imports)}），"
              f"這幾個模組的歸屬不可信。")

    if rep.declared_only:
        print(f"\n── 登記在案的空殼 {len(rep.declared_only)} 個 ──")
        print("名字或註解宣稱了一個行為，而那個行為沒有實作。"
              "登記不是結案。")
        for c in rep.declared_only:
            print(f"  {c.where:<28} {c.name}")
            print(f"      {REGISTRY[(c.module, c.name)]['why']}")

    if a.list_weak:
        print(f"\n── 只有弱引用 {len(rep.weak_only)} 個（不判紅）──")
        for c in rep.weak_only:
            print(f"  {c.where:<28} {c.name}")

    bad = False
    if rep.unregistered:
        bad = True
        print(f"\n🔴 沒登記的 {len(rep.unregistered)} 個 ──")
        print("一個沒有人讀的常數出現了，而沒有人寫下它為什麼可以沒人讀。")
        print("要嘛它是空殼（那就登記成 DECLARED_ONLY 並說明缺什麼），")
        print("要嘛它本來就是給人讀的（那就登記成 REFERENCE 並附原文依據）。")
        for c in rep.unregistered:
            print(f"  {c.where:<28} {c.name}")

    if rep.stale_registry:
        bad = True
        print(f"\n🔴 登記簿自己過期了 {len(rep.stale_registry)} 條 ──")
        for m, n, why in rep.stale_registry:
            print(f"  {m}.{n}　{why}")

    if not bad:
        print("\n✅ 沒有人讀的常數全部登記在案，登記簿沒有過期的條目。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
