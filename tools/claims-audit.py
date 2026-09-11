#!/usr/bin/env python3
"""拿真實 transcript 餵 claims.py，把每一類判定抽樣印出來給人看。

階段 2 的抽取器不能只靠單元測試校準。單元測試用的是我自己想得出來的
句子，而我想得出來的句子剛好就是我寫規則時預期的那些 —— 那是循環。

所以這支工具做的事很單純：拿真的講過的話進去，把結果攤開。

────────────────────────────────────────────────────

## 為什麼要看 REFUTED 而不是看 VERIFIED

REFUTED 是這套系統唯一會「定罪」的輸出。它說的是「你講了一件假的事」。

一個被冤枉的 REFUTED，傷害比十個漏掉的假宣稱大得多 —— 人只要被冤枉
一次就不會再信任整套判定，而那正好殺死這個專案的北極星（不讓使用者
變成 QA）。bible Q-07 記的是同一件事：不確定的時候不定罪，往 UNKNOWN 倒。

所以這支工具的預設輸出是「所有 REFUTED 的原句」。不抽樣，全印。
數量少到可以全部人工看過，那本身就是一個健康訊號。

## 這支工具不判斷對錯

它印出來的東西要人看。它不會說「這個是誤判」—— 它沒有那個能力，
判斷一個宣稱是不是真的需要知道當時的上下文，而那只有人有。

**它的價值在於讓人看得到，不在於它自己有結論。**

用法：

    python3 tools/claims-audit.py                    # 預設掃這個專案的 transcript
    python3 tools/claims-audit.py --all              # 連 VERIFIED / UNKNOWN 都印
    python3 tools/claims-audit.py --limit 20         # 只掃最近 20 個 session
    python3 tools/claims-audit.py --dir <path>       # 換語料
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import claims as C  # noqa: E402

# 語料目錄 = 被觀測的那個專案，不是使用者的家目錄。
#
# ────────────────────────────────────────────────────
# **2026-09-11 被 owner 抓到的一個取樣錯誤，值得完整寫下來。**
#
# 這裡原本寫死 `-Users-norikaoda`。那個目錄名就是 cwd 的編碼 ——
# 它底下只會有 cwd = /Users/norikaoda 的 session。
#
# 我從那裡抓六個 session，然後宣布「沒有任何 session 的 cwd 是
# Forseti repo」，還拿那個結論去推翻驗證基準、去把 B-13 升級成前提、
# 寫進 BLOCKERS.md 與 PHASE_STATUS.md。
#
# 那不是發現，是同義反覆:我在一個按 cwd 分類的抽屜裡找別的 cwd。
#
# 反證一直在我讀過的東西裡 —— 帳本中有
# `/Volumes/NewDrive/AI Project/Forseti/src/drift.js` 這類真實採集事件。
# 我印出來過，沒有把它跟結論對上。
#
# 實際上 `~/.claude/projects/-Volumes-NewDrive-AI-Project-Forseti`
# 有 21 個 session。那才是這套系統該看的資料:它們是在被觀測的專案裡
# 發生的，cwd 就是 repo，相對路徑有明確的基準。
#
# 教訓不是「換一個目錄」。是**取樣的範圍本身會決定結論，
# 而一個按條件分類的資料夾，不能拿來檢驗那個條件**。
# ────────────────────────────────────────────────────
DEFAULT_DIR = (Path.home() / ".claude" / "projects"
               / "-Volumes-NewDrive-AI-Project-Forseti")

# 一段話太長的話只印前後，中間省略。要看得到句子的形狀，
# 不是要看完整篇 —— 完整篇會讓人放棄看。
SNIP = 160


def snippet(text: str, subject: str) -> str:
    """把 subject 周圍的文字切出來。看不到上下文就沒辦法判斷是不是誤判。"""
    flat = " ".join(text.split())
    i = flat.find(subject) if subject else -1
    if i < 0:
        return flat[:SNIP] + ("…" if len(flat) > SNIP else "")
    lo = max(0, i - SNIP // 2)
    hi = min(len(flat), i + len(subject) + SNIP // 2)
    return ("…" if lo else "") + flat[lo:hi] + ("…" if hi < len(flat) else "")


def assistant_texts(path: Path):
    """從一個 transcript 撈出 (文字, cwd)。

    只撈 assistant 的。使用者講的話不是宣稱 —— 她說「你改好了嗎」
    不是在宣稱任何事，把它抽成 claim 然後判 REFUTED 是荒謬的。

    **cwd 要跟著每一行走。** 硬拿這個 repo 當所有宣稱的基準,
    等於假設每一句話都是在這裡講的。2026-09-11 在 risky.py 修過同一件事,
    當時沒回頭改這支。
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if rec.get("type") != "assistant":
                    continue
                msg = rec.get("message") or {}
                for block in msg.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text") or ""
                        if t.strip():
                            yield t, (rec.get("cwd") or "")
    except OSError:
        return


def main(argv: list[str]) -> int:
    show_all = "--all" in argv
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
    if not files:
        print(f"  {src} 底下沒有 .jsonl")
        return 2

    # 開一次帳本給所有 claim 共用。每個 claim 各開一次會把 I/O 放大幾百倍。
    led = None
    try:
        import event_ledger as EL
        led = EL.EventLedger()
    except Exception:
        pass

    states: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    buckets: dict[str, list[tuple[str, str, str]]] = {}
    turns = 0

    try:
        for f in files:
            for text, cwd in assistant_texts(f):
                turns += 1
                base = Path(cwd) if cwd else REPO
                for raw in C.extract(text):
                    kinds[raw["kind"]] += 1
                    if raw["kind"] == "unextractable":
                        states["UNEXTRACTABLE"] += 1
                        buckets.setdefault("UNEXTRACTABLE", []).append(
                            (raw.get("why", ""), "", snippet(text, "")))
                        continue
                    cl = C.Claim(text=text, kind=raw["kind"],
                                 subject=raw["subject"])
                    try:
                        C.verify(cl, cwd=base, led=led)
                    except C.ClaimError as e:
                        states["ERROR"] += 1
                        buckets.setdefault("ERROR", []).append(
                            (str(e), raw["subject"], snippet(text, raw["subject"])))
                        continue
                    states[cl.state] += 1
                    buckets.setdefault(cl.state, []).append(
                        (cl.why_state, cl.subject, snippet(text, cl.subject)))
    finally:
        if led is not None:
            led.close()

    total = sum(states.values())
    print()
    print(f"  語料　{len(files)} 個 session，{turns:,} 段 assistant 文字")
    print(f"  抽出　{total:,} 個宣稱")
    print()
    for s, n in states.most_common():
        pct = 100.0 * n / total if total else 0
        print(f"    {s:<16} {n:>6,}　{pct:5.1f}%")
    print()
    print("  kind　" + "　".join(f"{k}={v:,}" for k, v in kinds.most_common()))
    print()

    want = ["REFUTED", "ERROR"] if not show_all else list(buckets)
    for state in want:
        rows = buckets.get(state) or []
        if not rows:
            continue
        print()
        print(f"  ── {state}　{len(rows)} 筆 " + "─" * 40)
        print()
        seen: set[str] = set()
        for why, subject, snip in rows:
            key = f"{subject}|{why}"
            if key in seen:
                continue      # 同一個檔案被講很多次，看一次就夠
            seen.add(key)
            print(f"    {subject or '(無)'}")
            print(f"      判定　{why}")
            print(f"      原句　{snip}")
            print()

    if not show_all:
        print("  只印了 REFUTED 與 ERROR。要看全部加 --all")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
