#!/usr/bin/env python3
"""這個專案做了什麼，有多少真的接到使用者面前。

owner 2026-09-14：

    你等一下給我總盤點所有你做的，有多少東西根本沒有接近去到這介面上，
    那些東西沒有進去等於帶做工了

她說得對，而且這種盤點不能憑記憶 —— 憑記憶的盤點會偏向
「我覺得我做了很多」。所以這支從 Widget 的進入點
（`apps/forseti-cli/desktop_api.py`）往外追 import，
追得到的才算接上了。

## 三類，不是兩類

把「沒接進 Widget」全部算成白做工是不對的，那會把
測試跟 hook 也算進去。所以分三類：

    接到畫面      從 desktop_api 追得到
    別的入口用    CLI、hook、測試在用，只是不在 Widget 上
    沒有人用      沒有任何進入點追得到 —— 這一類才是白做工

用法：

    python3 tools/inventory.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 幾個進入點。從這些往外追，追得到的就是有人在用。
ENTRIES = {
    "Widget": REPO / "apps" / "forseti-cli" / "desktop_api.py",
    "CLI": REPO / "apps" / "forseti-cli" / "forseti.py",
}


def _py(d: Path) -> list[Path]:
    """跳過 `._` 開頭的。exFAT 的 AppleDouble sidecar 是二進位，
    讀進來會炸 UTF-8。同一個坑在這個專案咬過三次。"""
    return sorted(f for f in d.glob("*.py") if not f.name.startswith("._"))


def imports_of(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module.split(".")[0])
    return out


def reachable(start: Path, universe: dict[str, Path]) -> set[str]:
    """從 start 沿 import 追出去，看得到誰。"""
    seen, queue = set(), [start]
    while queue:
        cur = queue.pop()
        for name in imports_of(cur):
            if name in universe and name not in seen:
                seen.add(name)
                queue.append(universe[name])
    return seen


def main() -> int:
    app = REPO / "apps" / "forseti-cli"
    universe = {f.stem: f for f in _py(app)}

    reach = {k: reachable(v, universe) for k, v in ENTRIES.items()}
    for k, v in ENTRIES.items():
        reach[k].add(v.stem)

    # tools/ 與 tests/ 也會 import 那些模組
    used_by_tools: dict[str, set[str]] = {}
    for d, label in ((REPO / "tools", "tools"), (REPO / "tests", "tests")):
        if not d.is_dir():
            continue
        for f in _py(d):
            for name in imports_of(f):
                if name in universe:
                    used_by_tools.setdefault(name, set()).add(f"{label}/{f.name}")

    hooks = _hook_targets()

    rows = []
    for name, path in sorted(universe.items()):
        lines = len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        in_widget = name in reach["Widget"]
        in_cli = name in reach["CLI"]
        others = sorted(used_by_tools.get(name, set()))
        in_hook = any(name in h for h in hooks)
        if in_widget:
            kind = "接到畫面"
        elif in_cli or in_hook or any(o.startswith("tools/") for o in others):
            kind = "別的入口用"
        elif others:
            kind = "只有測試碰"
        else:
            kind = "沒有人用"
        rows.append((kind, name, lines, in_widget, in_cli, others))

    order = {"接到畫面": 0, "別的入口用": 1, "只有測試碰": 2, "沒有人用": 3}
    rows.sort(key=lambda r: (order[r[0]], -r[2]))

    print()
    print(f"  apps/forseti-cli 共 {len(rows)} 個模組，"
          f"{sum(r[2] for r in rows):,} 行")
    print()
    cur = None
    for kind, name, lines, w, c, others in rows:
        if kind != cur:
            cur = kind
            n = sum(1 for r in rows if r[0] == kind)
            ln = sum(r[2] for r in rows if r[0] == kind)
            print(f"  【{kind}】{n} 個，{ln:,} 行")
        tail = ""
        if not w and others:
            tail = "  ← " + ", ".join(others[:2])
        print(f"    {name:<16} {lines:>5} 行{tail}")
    print()

    for label, d in (("tools", REPO / "tools"), ("tests", REPO / "tests")):
        if d.is_dir():
            fs = _py(d)
            print(f"  {label}/  {len(fs)} 支，"
                  f"{sum(len(f.read_text(encoding='utf-8', errors='replace').splitlines()) for f in fs):,} 行")

    js = REPO / "src"
    if js.is_dir():
        fs = sorted(f for f in js.glob("*.js") if not f.name.startswith("._"))
        total = sum(len(f.read_text(encoding="utf-8", errors="replace").splitlines())
                    for f in fs)
        print(f"  src/    {len(fs)} 支 js，{total:,} 行"
              f"（{'接到畫面' if _js_in_widget() else '沒接到畫面'}）")

    if hooks:
        print(f"  hook    {len(hooks)} 個註冊在 .claude/settings.json")
    return 0


def _hook_targets() -> list[str]:
    f = REPO / ".claude" / "settings.json"
    if not f.is_file():
        return []
    try:
        import json
        d = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for group in (d.get("hooks") or {}).values():
        for item in group if isinstance(group, list) else []:
            for h in item.get("hooks", []):
                cmd = h.get("command", "")
                if cmd:
                    out.append(cmd)
    return out


def _js_in_widget() -> bool:
    ui = REPO / "desktop" / "ui" / "app.js"
    api = REPO / "apps" / "forseti-cli" / "desktop_api.py"
    for f in (ui, api):
        if f.is_file() and "primitives" in f.read_text(encoding="utf-8"):
            return True
    return False


if __name__ == "__main__":
    sys.exit(main())
