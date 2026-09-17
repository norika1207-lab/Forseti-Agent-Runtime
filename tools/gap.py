#!/usr/bin/env python3
"""做好了但沒接到桌面 App 的功能，一個都不漏。

owner 2026-09-14：

    我現在要你盤點你本來就做好好的功能，然後你卻沒有接上到桌面APP，
    這些一個都不可以給我漏掉

`tools/inventory.py` 是模組層級，太粗 —— 一個模組被 import 了，
不代表它的十個函式都被用到。這支到**函式層級**。

判準：Widget 的進入點是 `desktop_api.py`。
一個公開函式要算「接到畫面」，必須在 desktop_api 或它直接呼叫的
那幾支裡真的被叫到。只是被 import 不算。

用法：

    python3 tools/gap.py
    python3 tools/gap.py --only-gaps
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
APP = REPO / "apps" / "forseti-cli"


def _py(d: Path) -> list[Path]:
    # `._` 是 exFAT 的 AppleDouble sidecar，二進位，讀了會炸。
    return sorted(f for f in d.glob("*.py") if not f.name.startswith("._"))


def called_names(text: str) -> set[str]:
    """這段程式碼呼叫了哪些名字（含 mod.fn 的 fn）。"""
    out = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name):
            out.add(f.id)
        elif isinstance(f, ast.Attribute):
            out.add(f.attr)
    # 屬性存取也算（拿 class 當型別用）
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Name):
            out.add(node.id)
    return out


def public_defs(path: Path) -> list[tuple[str, str]]:
    """(名字, 一行說明)。跳過底線開頭的。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    out = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            continue
        if node.name.startswith("_"):
            continue
        doc = (ast.get_docstring(node) or "").strip().splitlines()
        first = next((l.strip() for l in doc if l.strip()), "")
        out.append((node.name, first))
    return out


def widget_surface() -> set[str]:
    """Widget 這條路徑上真的被呼叫到的名字。

    從 desktop_api 出發，把它 import 到的模組也一起看 ——
    那些模組裡被它呼叫的函式，以及那些函式自己再呼叫的。
    只走兩層，夠了:再深就不是「介面用到」而是「實作細節」。
    """
    api = APP / "desktop_api.py"
    text = api.read_text(encoding="utf-8")
    names = called_names(text)
    mods = {f.stem for f in _py(APP)}
    reached = {m for m in mods if re.search(rf"\bimport {m}\b", text)}
    for m in list(reached):
        f = APP / f"{m}.py"
        if f.is_file():
            names |= called_names(f.read_text(encoding="utf-8"))
    return names


def main(argv: list[str]) -> int:
    only_gaps = "--only-gaps" in argv
    surface = widget_surface()

    total = used = 0
    blocks = []
    for f in _py(APP):
        if f.stem == "desktop_api":
            continue
        defs = public_defs(f)
        if not defs:
            continue
        rows = [(n, d, n in surface) for n, d in defs]
        total += len(rows)
        used += sum(1 for r in rows if r[2])
        blocks.append((f.stem, rows))

    print()
    print(f"  apps/forseti-cli 的公開函式 {total} 個，"
          f"Widget 用得到 {used} 個（{used * 100 // max(total, 1)}%）")
    print()
    for name, rows in blocks:
        gaps = [r for r in rows if not r[2]]
        if only_gaps and not gaps:
            continue
        hit = len(rows) - len(gaps)
        print(f"  {name}  {hit}/{len(rows)}")
        for n, d, ok in rows:
            if only_gaps and ok:
                continue
            mark = "用" if ok else "  "
            print(f"    {mark} {n:<28} {d[:44]}")
        print()

    print("  ── tools/ ──")
    for f in _py(REPO / "tools"):
        try:
            doc = ast.get_docstring(ast.parse(f.read_text(encoding="utf-8"))) or ""
        except (SyntaxError, UnicodeDecodeError):
            doc = ""
        first = next((l.strip() for l in doc.splitlines() if l.strip()), "")
        print(f"    {f.name:<26} {first[:48]}")

    print()
    print("  ── src/ (JavaScript) ──")
    js = REPO / "src"
    if js.is_dir():
        for f in sorted(x for x in js.glob("*.js") if not x.name.startswith("._")):
            head = f.read_text(encoding="utf-8", errors="replace")[:400]
            m = re.search(r"\*\s*(Forseti[^\n]*|[^\n*]{6,60})", head)
            first = (m.group(1).strip() if m else "").strip(" *")
            n = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
            print(f"    {f.name:<22} {n:>5} 行  {first[:40]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
