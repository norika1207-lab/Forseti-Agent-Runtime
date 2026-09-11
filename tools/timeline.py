#!/usr/bin/env python3
"""把一段對話切成一條有顏色的線。UI 的第一塊資料。

owner 2026-09-11 講的形狀：

    一個節點 = 一輪對話。沿時序排下來，顏色從綠走到紅。
    看到紅的那一節，點進去知道當時講了什麼、為什麼判紅，
    然後從紅色之前那一節 fork，任務接著跑。

這支只做前半 —— 把線算出來。fork 是另一件事，而且還沒確認做不做得到。

────────────────────────────────────────────────────

## 顏色是結構訊號，不是體溫

工程書 Phase 8 的預設畫面是 `Forseti 37.2 C WATCH`。那個數字的問題是
**它精確到小數點，看起來像量出來的，但它量的是什麼沒有人說得清楚**。
Phase 8 自己的停止條件第三條寫「把推論當成確定事實就停」，
而一個沒有單位的體溫正是那種東西。

所以這裡的顏色只用三個結構事實，每一個都指得出 transcript 的哪一行：

    她下一句是什麼        owner.classify()，結構規則，不讀語意
    這一輪有沒有驗不過     claims.verify()，stat / hash 的確定性檢查
    這一輪有多長          工具呼叫數與文字塊數，純計數

**沒有加權、沒有分數、沒有溫度。** 一個節點的顏色可以用一句話講完它
憑什麼是那個顏色，講不出來就不該有顏色。

## 為什麼不是清單而是線

清單回答「哪裡有問題」，線回答「從哪裡開始有問題」。
要 fork 就得知道退到哪一步，而那是清單給不了的。

## 顏色會事後改變，這是刻意的

一輪當下看起來沒事，可能三輪之後才被糾正 —— 那時候才知道問題出在那裡。
所以顏色不是即時算一次就定死，它是重算出來的。
帳本 append-only 加上 `replay()` 就是為了讓這件事做得到。

用法：

    python3 tools/timeline.py <session-uuid 或 .jsonl 路徑> [--out <json>]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import claims as C  # noqa: E402
import owner as O  # noqa: E402

PROJECTS = Path.home() / ".claude" / "projects"

# 一個節點的顏色。**四級，不是連續光譜。**
#
# 連續的數字會誘人去比較 37.2 跟 37.4，而那兩個之間沒有意義上的差別。
# 四級逼人說出每一級是什麼意思。
LEVELS = ("OK", "WATCH", "CORRECTED", "BROKEN")

LEVEL_MEANING = {
    "OK": "她往下走了 —— 確認，或直接講下一件事",
    "WATCH": "她要我澄清。沒有人做錯，但我沒講清楚",
    "CORRECTED": "她糾正了我",
    "BROKEN": "她糾正了我，而且那一輪有驗不過的宣稱",
}


def resolve(arg: str) -> Path:
    p = Path(arg).expanduser()
    if p.is_file():
        return p
    hits = sorted(PROJECTS.glob(f"*/{arg}*.jsonl"))
    if not hits:
        raise SystemExit(f"  找不到 transcript：{arg}")
    return hits[0]


def rounds(path: Path) -> list[dict]:
    """切成輪。跟 owner.silence_map 同一套定義：兩則 owner 訊息之間算一輪。

    這裡自己走一遍而不是呼叫 silence_map，是因為要的東西多得多 ——
    每一輪的工具呼叫、文字內容、時間戳。silence_map 只回反應類型。
    """
    owner_turns: list[tuple[int, str, str]] = []
    ai_blocks: list[tuple[int, str, str]] = []
    tool_calls: dict[int, list[str]] = {}

    with path.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            try:
                d = json.loads(line)
            except (ValueError, TypeError):
                continue
            t = d.get("type")
            ts = d.get("timestamp") or ""
            c = (d.get("message") or {}).get("content")
            if t == "assistant" and isinstance(c, list):
                text = "\n".join(b.get("text", "") for b in c
                                 if isinstance(b, dict) and b.get("type") == "text")
                names = [b.get("name", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "tool_use"]
                if names:
                    tool_calls.setdefault(i, []).extend(names)
                if text.strip():
                    ai_blocks.append((i, text, ts))
            elif t == "user":
                if isinstance(c, str):
                    text = c
                elif isinstance(c, list):
                    text = "\n".join(b.get("text", "") for b in c
                                     if isinstance(b, dict)
                                     and b.get("type") == "text")
                else:
                    continue
                if O.is_owner_text(text):
                    owner_turns.append((i, text, ts))

    # 以兩則 owner 訊息為界切輪。
    out: list[dict] = []
    for idx, (oline, otext, ots) in enumerate(owner_turns):
        nxt = owner_turns[idx + 1][0] if idx + 1 < len(owner_turns) else 10 ** 12
        blocks = [(ln, tx) for ln, tx, _ in ai_blocks if oline < ln < nxt]
        tools: list[str] = []
        for ln, names in tool_calls.items():
            if oline < ln < nxt:
                tools.extend(names)
        out.append({
            "n": idx + 1,
            "owner_line": oline,
            "owner_text": otext,
            "at": ots,
            "ai_lines": [ln for ln, _ in blocks],
            "ai_text": "\n\n".join(tx for _, tx in blocks),
            "tools": tools,
        })
    return out


def score(rs: list[dict]) -> None:
    """算每一輪的顏色。就地改 rs。

    **顏色由「她下一句是什麼」決定，不是由我這一輪說了什麼決定。**
    那是刻意的：一輪回應好不好，看的人才知道，不是講的人自己說了算。
    """
    for i, r in enumerate(rs):
        nxt = rs[i + 1] if i + 1 < len(rs) else None
        reaction = O.classify(nxt["owner_text"]).kind if nxt else "UNOBSERVED"

        # 驗不過的宣稱。cwd 用這個 session 的實際工作目錄。
        refuted: list[str] = []
        for raw in C.extract(r["ai_text"]):
            if raw["kind"] != "file":
                continue
            cl = C.Claim(text=r["ai_text"], kind="file", subject=raw["subject"])
            try:
                C.verify(cl, cwd=Path.home())
            except C.ClaimError:
                continue
            if cl.state == "REFUTED":
                refuted.append(f"{cl.subject}：{cl.why_state}")

        if reaction == "CORRECTION":
            level = "BROKEN" if refuted else "CORRECTED"
        elif reaction == "CLARIFICATION":
            level = "WATCH"
        else:
            level = "OK"

        r["reaction"] = reaction
        r["refuted"] = refuted[:4]
        r["level"] = level
        r["why"] = _why(level, reaction, refuted, nxt)


def _why(level, reaction, refuted, nxt) -> str:
    """一句話講清楚憑什麼是這個顏色。**講不出來就不該有顏色。**"""
    if level == "BROKEN":
        return (f"下一句是糾正（{O.classify(nxt['owner_text']).why}），"
                f"而且這一輪有 {len(refuted)} 個宣稱驗不過")
    if level == "CORRECTED":
        return f"下一句是糾正：{O.classify(nxt['owner_text']).why}"
    if level == "WATCH":
        return f"下一句要我澄清：{O.classify(nxt['owner_text']).why}"
    if reaction == "UNOBSERVED":
        return "後面沒有她的訊息了 —— 還沒看到，不是沒問題"
    return LEVEL_MEANING["OK"]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__.strip().split("用法：")[-1])
        return 2
    path = resolve(argv[1])
    out = None
    if "--out" in argv:
        i = argv.index("--out")
        if i + 1 < len(argv):
            out = Path(argv[i + 1])

    rs = rounds(path)
    score(rs)

    tally = {}
    for r in rs:
        tally[r["level"]] = tally.get(r["level"], 0) + 1

    print()
    print(f"  {path.name}")
    print(f"  {len(rs)} 輪")
    print()
    for lv in LEVELS:
        if tally.get(lv):
            print(f"    {lv:<12} {tally[lv]:>4}　{LEVEL_MEANING[lv]}")
    print()

    bad = [r for r in rs if r["level"] in ("CORRECTED", "BROKEN")]
    if bad:
        print("  變紅的地方")
        print()
        for r in bad:
            head = " ".join(r["owner_text"].split())[:70]
            print(f"    第 {r['n']} 輪　{r['level']}")
            print(f"      我：{' '.join(r['ai_text'].split())[:80]}")
            print(f"      她：{head}")
            print(f"      因為：{r['why']}")
            for x in r["refuted"]:
                print(f"        · {x[:100]}")
            print()

    if out:
        out.write_text(json.dumps(
            {"session": path.stem, "rounds": rs,
             "levels": LEVELS, "meaning": LEVEL_MEANING},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  寫進 {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
