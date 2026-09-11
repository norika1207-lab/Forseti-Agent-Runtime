#!/usr/bin/env python3
"""拿真實 transcript 全量跑 owner 分類器與沉默地圖。階段 3 的校準。

`tools/claims-audit.py` 的同一個方法，換一個對象。那支跑完之後
REFUTED 從 30.8% 降到 1.9%，而降下來的那些全部是真實語料才暴露得出來的
形狀 —— 單元測試用的句子是我自己想得出來的，而我想得出來的剛好就是
我寫規則時預期的那些。那是循環。

────────────────────────────────────────────────────

## 這裡的「定罪」是 CORRECTION

claims 那邊是 REFUTED（「你講了假話」），這邊是 CORRECTION
（「你做錯了」）。兩個都是把一件事記到 AI 頭上。

而 CORRECTION 的誤判有一個 claims 沒有的後果：**它會把她行使擁有者
的權力記成 AI 的失誤。** `owner.py` 的模組註解寫過同一件事 ——
「不用跑測試了」是改變想法不是糾正，把它算成糾正，等於說她犯了錯。

所以 CORRECTION 與 MIND_CHANGE 兩類全印。前者是定罪，
後者會變成 `OWNER_GOAL_CHANGE` 事件進帳本、影響北極星該不該換版。

## 它一樣不判斷對錯

印出來的東西要人看。一則訊息到底是糾正還是改變想法，
要知道上一則講了什麼，而這個分類器是無狀態的（一次只看一則）。

## UNKNOWN 高不是壞事

`owner.py` 註解記過：105 則裡 53 則是 UNKNOWN。
**那個比例看起來很糟，但它是誠實的** —— 猜出來的分類會讓所有下游
統計都帶著看不見的誤差。這支工具會把 UNKNOWN 的原句也印出來
（`--all`），好讓人判斷那些到底是該分類的還是真的分不出來。

用法：

    python3 tools/owner-audit.py                  # 定罪那兩類 + 沉默統計
    python3 tools/owner-audit.py --all            # 五類全印
    python3 tools/owner-audit.py --limit 20
    python3 tools/owner-audit.py --silence        # 只看沉默地圖
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import owner as O  # noqa: E402
import northstar as N  # noqa: E402

DEFAULT_DIR = Path.home() / ".claude" / "projects" / "-Users-norikaoda"
SNIP = 150

# 這兩類是「記到 AI 頭上」與「改變北極星」的入口，全印。
LOUD = ("CORRECTION", "MIND_CHANGE")


def snippet(text: str) -> str:
    flat = " ".join(text.split())
    return flat[:SNIP] + ("…" if len(flat) > SNIP else "")


def main(argv: list[str]) -> int:
    show_all = "--all" in argv
    silence_only = "--silence" in argv
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

    kinds: Counter[str] = Counter()
    matched: Counter[str] = Counter()
    buckets: dict[str, list[tuple[str, str]]] = {}
    sil_total: Counter[str] = Counter()
    sessions = 0
    mv_total = mv_unknown = 0

    for f in files:
        try:
            msgs = O.from_transcript(f)
        except OSError:
            continue
        if not msgs:
            continue
        sessions += 1
        for _, text in msgs:
            m = O.classify(text)
            kinds[m.kind] += 1
            if m.matched:
                matched[f"{m.kind}：{m.matched}"] += 1
            buckets.setdefault(m.kind, []).append((m.why, snippet(text)))
        try:
            for s in O.silence_map(f):
                sil_total[s.kind] += 1
                if s.kind == "MOVED_ON":
                    mv_total += 1
                    if s.owner_kind == "UNKNOWN":
                        mv_unknown += 1
        except OSError:
            pass

    total = sum(kinds.values())
    print()
    print(f"  語料　{sessions} 個 session，{total:,} 則 owner 訊息")
    print()
    for k, n in kinds.most_common():
        pct = 100.0 * n / total if total else 0
        print(f"    {k:<18} {n:>6,}　{pct:5.1f}%")
    print()

    st = sum(sil_total.values())
    print(f"  沉默地圖　{st:,} 輪")
    for k in O.SILENCE:
        n = sil_total.get(k, 0)
        pct = 100.0 * n / st if st else 0
        print(f"    {k:<18} {n:>6,}　{pct:5.1f}%")
    print()
    print("    MOVED_ON 不等於同意。要當成同意只有一條路：她自己說出口")
    if mv_total:
        share = 100.0 * mv_unknown / mv_total
        print(f"    其中 {mv_unknown:,} 輪（{share:.0f}%）底下是分類器的 UNKNOWN —— "
              "那部分量的是「分不出她在說什麼」不是「她跳過了」")
    print()

    # 落差：她改了幾次方向，北極星換了幾版。
    #
    # **這裡的北極星版本數是這支工具自己造的，不是真實狀態。**
    # `.forseti/NORTH_STAR.md` 現在沒有版本鏈（它是一份只增不改的文件），
    # 所以這個落差只證明一件事：這條路是通的。它不是一個發現。
    #
    # 會特別寫這段，是因為一個看起來像數據的數字最容易被下一個人
    # 當成結論帶走。標清楚它從哪來，比印得漂亮重要。
    chain = N.Chain()
    chain.adopt("讓 AI 的工作狀態變成可觀測、可驗證、可控制、可復原",
                authority="owner", why="soul.md 第二節，只增不改")
    gap = O.goal_change_gap(kinds.get("MIND_CHANGE", 0), len(chain.versions))
    print(f"  方向改變 {gap['goal_changes']} 次，"
          f"北極星換版 {gap['north_star_bumps']} 次，落差 {gap['gap']}")
    print("    ！這個落差不是發現。北極星版本數是這支工具現場造的單版鏈，")
    print("      真實的 .forseti/NORTH_STAR.md 沒有版本鏈。這裡只證明路是通的")
    print()

    if silence_only:
        return 0

    print("  最常命中的判準（看有沒有哪一條在暴衝）")
    for k, n in matched.most_common(12):
        print(f"    {n:>5,}　{k}")
    print()

    want = list(buckets) if show_all else LOUD
    for kind in want:
        rows = buckets.get(kind) or []
        if not rows:
            continue
        print()
        print(f"  ── {kind}　{len(rows)} 則 " + "─" * 40)
        print()
        for why, snip in rows:
            print(f"    {snip}")
            print(f"      判定　{why}")
            print()

    if not show_all:
        print(f"  只印了 {'、'.join(LOUD)}。要看五類全部加 --all")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
