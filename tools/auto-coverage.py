#!/usr/bin/env python3
"""從 transcript 自動補上閱讀涵蓋記錄。把「靠自律」那一塊拿掉。

`.forseti/HANDOVER_FAILURE_2026-09-11.md` §19.7 記著一個沒做完的東西：

    `from_full_read()` 要人主動呼叫。也就是說涵蓋記錄目前靠自律，
    而這整份文件講的就是自律不可靠。

    要讓它不靠自律，讀取端每次讀檔都得自動記錄，
    那會動到工作流程本身，不是一個模組能解決的。

那句話當時是對的，但前提變了。`apps/forseti-cli/tracker.py` 做出來之後，
**每一次 Read 都已經被記在 transcript 裡了** —— 工具名、檔案路徑、
時間，全部都有。所以不需要改工作流程，只要回頭讀那份紀錄。

────────────────────────────────────────────────────

## 它怎麼判斷「讀了幾行」

`Read` 工具的 input 帶 `file_path`，有時候帶 `offset` 與 `limit`。

    有 offset/limit  →  涵蓋 (offset, offset+limit-1)
    兩個都沒有       →  涵蓋整份

第二條是這支工具唯一的推論，而且它是**保守方向錯的**：
`Read` 沒給範圍時確實會讀整份，但如果檔案超過工具上限，
它會被截斷，而截斷這件事 transcript 裡看不到。

所以這支會**高估**涵蓋率。高估的方向跟這整套東西的原則相反
（`claims.py` 的 `can_refute()`、`coverage.py` 的 THRESHOLDS 都是
寧可低估），所以每一筆自動補的記錄都帶
`inferred: true`，跟人工 `from_full_read()` 的分開。

**一個自動推出來的涵蓋率，不該跟親眼讀完的算同一級。**

## 它不做的事

不碰 `Grep`。grep 命中三行不等於讀了那三行的脈絡，
把它算成涵蓋會讓一個只掃過關鍵字的人看起來讀過了。

用法：

    python3 tools/auto-coverage.py                 # 最近的 session
    python3 tools/auto-coverage.py <session-uuid>
    python3 tools/auto-coverage.py --dry-run
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import coverage as C      # noqa: E402
import tracker as TK      # noqa: E402

# 只認這一個。理由見模組 docstring。
READ_TOOL = "Read"


def harvest(path: Path) -> list[dict]:
    """從 transcript 撈出所有 Read 呼叫。"""
    out: list[dict] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") != "assistant":
                continue
            content = (rec.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for b in content:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                if b.get("name") != READ_TOOL:
                    continue
                inp = b.get("input") or {}
                fp = inp.get("file_path")
                if not isinstance(fp, str) or not fp.strip():
                    continue
                out.append({
                    "path": fp,
                    "offset": inp.get("offset"),
                    "limit": inp.get("limit"),
                    "line": i,
                })
    return out


def apply(reads: list[dict], *, dry_run: bool = False) -> dict:
    """把撈到的 Read 變成涵蓋記錄。

    同一個檔案的多次 Read 會累積 —— `CoverageLog.merged_for()` 本來
    就會按 content_hash 分組再併，所以分段讀完的檔案合起來算讀完。
    """
    log = C.CoverageLog(root=REPO)
    added, skipped, missing = 0, 0, 0
    seen: set[tuple] = set()

    for r in reads:
        p = Path(r["path"]).expanduser()
        if not p.is_file():
            missing += 1
            continue
        try:
            full = C.from_full_read(p)
        except (OSError, ValueError):
            missing += 1
            continue
        total = full.total_lines
        if not total:
            skipped += 1
            continue

        off, lim = r.get("offset"), r.get("limit")
        if isinstance(off, int) and isinstance(lim, int) and off >= 1:
            lo, hi = off, min(total, off + lim - 1)
        else:
            lo, hi = 1, total

        key = (str(p), full.content_hash, lo, hi)
        if key in seen:
            continue
        seen.add(key)

        rec = C.ReadRecord(str(p), total, full.content_hash)
        try:
            rec.add(lo, hi)
        except C.CoverageError:
            skipped += 1
            continue
        if not dry_run:
            log.append(rec, session="auto",
                       note=f"自動補：transcript 第 {r['line']} 行的 Read"
                            f"（inferred，可能高估）")
        added += 1

    return {"reads": len(reads), "added": added,
            "skipped": skipped, "missing": missing, "dry_run": dry_run}


def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    if args:
        hits = sorted((Path.home() / ".claude" / "projects").glob(
            f"*/{args[0]}*.jsonl"))
        target = hits[0] if hits else None
    else:
        target = TK.latest_session()
    if target is None or not target.is_file():
        print("  找不到 transcript")
        return 2

    reads = harvest(target)
    r = apply(reads, dry_run=dry)

    print()
    print(f"  {target.name}")
    print(f"  抓到 {r['reads']} 次 Read")
    print(f"  寫入 {r['added']} 筆涵蓋記錄"
          + ("（--dry-run，沒有真的寫）" if dry else ""))
    if r["missing"]:
        print(f"  {r['missing']} 個檔案現在不存在或讀不到，跳過")
    if r["skipped"]:
        print(f"  {r['skipped']} 筆區間不合法或檔案是空的，跳過")
    print()
    print("  自動補的記錄帶 inferred 標記。Read 沒給範圍時會被當成讀整份，")
    print("  而超過工具上限的檔案實際上會被截斷 —— 這支會高估，")
    print("  所以它跟人工 from_full_read() 的記錄要分開看。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
