#!/usr/bin/env python3
"""docx 轉 markdown，保留結構。

為什麼不用「剝掉所有標籤」那個做法：它會把標題、清單、表格全部壓成
沒有層級的平行文字行。Vol1 的三層產品定位是一張表，剝完之後變成
十二行散落的字，讀的人要自己猜回它是表格。結構本身就是資訊。

為什麼用 ElementTree 不用正則：正則在自閉合標籤（<w:t/>）上會跨越邊界，
把中間的 XML 標籤吃進文字裡。2026-09-09 我用正則量 Vol1 的字數，
得到 16,859，以為原本的轉法漏了 83%，差點據此去重查所有讀過的文件。
真實字數是 2,876，正則那個數字裡大半是標籤。

零依賴，標準庫而已。
"""

from __future__ import annotations

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _text(el) -> str:
    """一個元素底下所有 <w:t> 的文字。<w:tab> 當空格，<w:br> 當換行。"""
    parts = []
    for node in el.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "tab":
            parts.append(" ")
        elif node.tag == W + "br":
            parts.append("\n")
    return "".join(parts)


def _style(p) -> str | None:
    pPr = p.find(W + "pPr")
    if pPr is None:
        return None
    st = pPr.find(W + "pStyle")
    return st.get(W + "val") if st is not None else None


def _para_md(p) -> str:
    txt = _text(p).strip()
    if not txt:
        return ""
    st = _style(p) or ""
    if st == "Title":
        return "# " + txt
    if st.startswith("Heading"):
        n = st[len("Heading"):]
        lvl = int(n) if n.isdigit() else 1
        return "#" * min(6, lvl + 1) + " " + txt
    if st in ("ListBullet", "ListParagraph"):
        return "- " + txt
    if st == "ListNumber":
        return "1. " + txt
    if st in ("Quote", "IntenseQuote"):
        return "> " + txt
    return txt


def _cell_md(tc) -> str:
    """表格格子。內部換行換成空格，並跳脫 markdown 的欄位分隔字元。"""
    lines = [_text(p).strip() for p in tc.findall(W + "p")]
    txt = " ".join(l for l in lines if l)
    return txt.replace("|", "\\|").replace("\n", " ")


def _table_md(tbl) -> list[str]:
    rows = []
    for tr in tbl.findall(W + "tr"):
        cells = [_cell_md(tc) for tc in tr.findall(W + "tc")]
        if cells:
            rows.append(cells)
    if not rows:
        return []
    # 只有一列一格的表格是 Word 的強調框,不是資料表。
    # 當成表格輸出會把標題跟內容擠進同一格,讀起來像壞掉的資料。
    if len(rows) == 1 and len(rows[0]) == 1:
        return ["> " + rows[0][0]]
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return out


def convert(path: Path) -> tuple[str, int]:
    """回傳 (markdown, 原始文字的非空白字元數)。後者用來驗證沒漏字。"""
    z = zipfile.ZipFile(path)
    root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(W + "body")
    if body is None:
        return "", 0

    raw_chars = sum(
        1
        for n in root.iter() if n.tag == W + "t"
        for c in (n.text or "") if not c.isspace()
    )

    blocks: list[str] = []
    for el in body:
        if el.tag == W + "p":
            md = _para_md(el)
            if md:
                blocks.append(md)
        elif el.tag == W + "tbl":
            t = _table_md(el)
            if t:
                blocks.append("\n".join(t))

    # 連續的清單項之間不要空行，其餘之間空一行
    out: list[str] = []
    for i, b in enumerate(blocks):
        out.append(b)
        if i + 1 < len(blocks):
            both_list = b.startswith(("- ", "1. ")) and blocks[i + 1].startswith(("- ", "1. "))
            if not both_list:
                out.append("")
    return "\n".join(out).replace("\n\n\n", "\n\n") + "\n", raw_chars


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    targets: list[Path] = []
    for a in argv[1:]:
        p = Path(a).expanduser()
        targets.extend(sorted(p.glob("*.docx")) if p.is_dir() else [p])

    for src in targets:
        if src.name.startswith("~$"):
            continue
        md, raw_ns = convert(src)
        dst = src.with_suffix(".md")
        dst.write_text(md, encoding="utf-8")
        # 驗證:markdown 的非空白字元數要 >= 原始文字的非空白字元數。
        # markdown 只會多出結構符號(# | -),不會少字。少了就是漏字。
        md_ns = sum(1 for c in md if not c.isspace())
        ok = "OK" if md_ns >= raw_ns else f"!! 少了 {raw_ns - md_ns:,} 字"
        print(f"  {src.name}")
        print(f"    → {dst.name}　原文 {raw_ns:,} 字　md {md_ns:,} 字　{ok}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
