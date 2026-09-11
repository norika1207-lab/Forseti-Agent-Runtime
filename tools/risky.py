#!/usr/bin/env python3
"""把四個模組接起來，產出這套系統真正要給人看的東西。

    在哪幾個地方，AI 說了沒把握的話，而她沒有回應。

────────────────────────────────────────────────────

## 為什麼是這個組合

`owner.Silence.risky` 的定義是兩個條件的交集：

    flagged     那一輪 AI 輸出裡有未解的東西
    MOVED_ON    她沒有針對那一輪說話，直接講下一件事

單看任何一邊都沒有用。只看 flagged 會得到一長串「AI 說過沒把握的話」，
但她可能已經看到並處理了；只看 MOVED_ON 會得到 78% 的輪次，
因為人本來就不會每一段都回應。

**交集才是那個真正的縫：那裡有問題，而且沒有人看過。**

## flagged 只用 REFUTED，不用 UNKNOWN

這是這支工具最重要的一個取捨，寫清楚理由：

`claims` 在真實語料上有 82% 是 UNKNOWN。把 UNKNOWN 算成 flagged 的話
幾乎每一輪都會中，risky 就變成「所有輪次」的同義詞。

而且 UNKNOWN 大部分不是 AI 的問題，是**驗證器沒有能力驗**
（不在這個 repo、沒有副檔名、這一版沒有那種驗證器）。
拿系統自己的無知去標記人，方向完全錯了。

`overclaim` 的三個 primitive 也接進來了，但實測它們在 transcript 上
產生不了 POSITIVE —— FP-02 與 FP-07 要結構化的 scope 與計數，
FP-03 要 Event Ledger 裡這個 session 的 receipt 數，而 hook 對主 session
不生效（B-13）。**接著但沒有貢獻，這件事本身要講出來**，
不然下一個人會以為它有在工作。

## 這支工具會不會有用，跑之前不知道

如果 risky 出來幾百筆，它就是噪音，這一層不算成立。
如果少到可以人工看完，這一層才有價值。

用法：

    python3 tools/risky.py [--limit N] [--dir <path>]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import claims as C  # noqa: E402
import overclaim as OC  # noqa: E402
import owner as O  # noqa: E402

# 語料目錄 = 被觀測的那個專案。**理由與踩過的坑寫在
# `tools/claims-audit.py` 的同一個常數上面**，那是 2026-09-11 的取樣錯誤。
DEFAULT_DIR = (Path.home() / ".claude" / "projects"
               / "-Volumes-NewDrive-AI-Project-Forseti")


def assistant_blocks(path: Path) -> list[tuple[int, str, str]]:
    """(行號, 文字, cwd)。行號要跟 owner.silence_map 算的是同一套。

    **cwd 是 2026-09-11 接線時才發現非拿不可的。**

    先前 `tools/claims-audit.py` 硬拿 Forseti repo 當所有宣稱的基準，
    而實測六個 session 的 cwd 沒有一個是這個 repo ——
    全部在 `/Users/norikaoda` 或 `code-matrix-rebuild` 底下工作。

    拿 A 目錄當基準去驗 B 目錄裡講的相對路徑，判出來的「找不到」
    講的是我自己的座標錯了，不是那個人說了假話。
    """
    import json
    out: list[tuple[int, str, str]] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, 1):
                try:
                    d = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if d.get("type") != "assistant":
                    continue
                c = (d.get("message") or {}).get("content")
                if not isinstance(c, list):
                    continue
                text = "\n".join(b.get("text", "") for b in c
                                 if isinstance(b, dict) and b.get("type") == "text")
                if text.strip():
                    out.append((i, text, d.get("cwd") or ""))
    except OSError:
        return []
    return out


def flag_lines(path: Path, led=None) -> tuple[set[int], dict[int, list[str]],
                                              Counter]:
    """哪幾行有未解的東西，以及為什麼。"""
    flagged: set[int] = set()
    reasons: dict[int, list[str]] = {}
    tally: Counter[str] = Counter()

    for line_no, text, cwd in assistant_blocks(path):
        base = Path(cwd) if cwd else REPO
        for raw in C.extract(text):
            if raw["kind"] == "unextractable":
                tally["UNEXTRACTABLE"] += 1
                continue
            cl = C.Claim(text=text, kind=raw["kind"], subject=raw["subject"])
            try:
                C.verify(cl, cwd=base, led=led)
            except C.ClaimError:
                continue
            tally[cl.state] += 1
            if cl.state == "REFUTED":
                flagged.add(line_no)
                reasons.setdefault(line_no, []).append(
                    f"驗不過：{cl.subject}　{cl.why_state}")

        # overclaim 也接上。它目前產生不了 POSITIVE，但要接著 ——
        # 沒接的話下一個人不知道這條線存不存在；接了而沒貢獻，
        # 統計會把那件事說出來。
        for f in OC.inspect(text):
            tally[f"OC:{f.verdict}"] += 1
            if f.verdict == "POSITIVE":
                flagged.add(line_no)
                reasons.setdefault(line_no, []).append(f"誇大：{f.why}")

    return flagged, reasons, tally


def main(argv: list[str]) -> int:
    limit = None
    if "--limit" in argv:
        i = argv.index("--limit")
        if i + 1 < len(argv):
            limit = int(argv[i + 1])
    src = DEFAULT_DIR
    if "--dir" in argv:
        i = argv.index("--dir")
        if i + 1 < len(argv):
            src = Path(argv[i + 1]).expanduser()

    if not src.is_dir():
        print(f"  找不到語料目錄：{src}")
        return 2
    files = sorted(src.glob("*.jsonl"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    if limit:
        files = files[:limit]

    led = None
    try:
        import event_ledger as EL
        led = EL.EventLedger()
    except Exception:
        pass

    total_rounds = 0
    total_flagged_rounds = 0
    sil = Counter()
    tally = Counter()
    risky_rows: list[tuple[str, int, str, list[str], str]] = []

    try:
        for f in files:
            flagged, reasons, t = flag_lines(f, led=led)
            tally.update(t)
            try:
                items = O.silence_map(f, flagged)
            except OSError:
                continue
            total_rounds += len(items)
            for s in items:
                sil[s.kind] += 1
                if s.flagged:
                    total_flagged_rounds += 1
                if s.risky:
                    # 只取這一輪涵蓋的行。攤平整個 session 的話，
                    # 每一筆的理由會長得一模一樣，清單就廢了。
                    why = []
                    for ln in sorted(s.lines & set(reasons)):
                        why.extend(reasons[ln])
                    risky_rows.append((f.stem[:8], s.ai_line, s.ai_excerpt,
                                       why, s.kind))
    finally:
        if led is not None:
            led.close()

    print()
    print(f"  {len(files)} 個 session，{total_rounds:,} 輪")
    print()
    print("  宣稱判定")
    for k in ("VERIFIED", "REFUTED", "UNKNOWN", "UNEXTRACTABLE"):
        if tally.get(k):
            print(f"    {k:<16} {tally[k]:>6,}")
    print()
    print("  誇大判定（三個 primitive 一起）")
    for k in ("OC:POSITIVE", "OC:NEGATIVE", "OC:INDETERMINATE"):
        if tally.get(k):
            print(f"    {k:<16} {tally[k]:>6,}")
    if not tally.get("OC:POSITIVE"):
        print("    POSITIVE 0 —— 接上了但沒有貢獻。FP-02 與 FP-07 要結構化的")
        print("    scope 與計數，FP-03 要這個 session 的 receipt 數（B-13）")
    print()
    print(f"  被標記的輪次　{total_flagged_rounds:,} / {total_rounds:,}"
          f"　（{100.0 * total_flagged_rounds / total_rounds:.1f}%）"
          if total_rounds else "  沒有輪次")
    print()
    print("  她接下來做了什麼")
    for k in O.SILENCE:
        if sil.get(k):
            print(f"    {k:<16} {sil[k]:>6,}")
    print()
    print("  ── 風險清單：有問題，而且她沒有回應 " + "─" * 26)
    print()
    if not risky_rows:
        print("    空的。")
        print("    **空不等於沒事** —— 也可能是 flagged 的判準太嚴，")
        print("    或者驗不過的那幾輪剛好她都回應了。兩者要分開看。")
    else:
        for sid, line, excerpt, why, kind in risky_rows:
            print(f"    {sid}　第 {line} 行　{kind}")
            print(f"      {' '.join(excerpt.split())[:100]}")
            for w in why:
                print(f"      · {w[:110]}")
            print()
        print(f"    共 {len(risky_rows)} 筆。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
