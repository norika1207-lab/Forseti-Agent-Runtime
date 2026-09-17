#!/usr/bin/env python3
"""把這個 repo 裡已經白紙黑字寫過的更正，登錄進 §40 污染登記簿。

為什麼要有這支，而不是直接手動塞 jsonl:資料要查得回來怎麼進去的。
可以重跑,同一筆不會變成兩筆(id 是 original_claim 加 failure_mechanism
的 hash)。

## 每一筆的來源都是「當初那一輪自己寫下的更正」,不是我判讀出來的

所以 `verifier` 分兩段:發現的人是當初那一輪,登錄的人是這一輪。
這個差別要看得見 —— 把登錄者寫成發現者會讓這份登記簿看起來
比實際上更可靠。

## 為什麼不做自動掃描

`.forseti/AUTO_CONTINUE_LOG.md` 裡「先前……不準」這種句型有幾十處,
但靠句型抓到的是符合句型的句子,不是真的污染(BLOCKERS 的 B-05)。
這裡只收我逐行開檔驗過出處的那幾筆。

## propagation_radius 一律 None

規格沒定義單位。這四筆都沒有量過下游到底影響幾個結論,
所以一個都不填數字,每一筆帶 radius_basis 說為什麼。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import pollution  # noqa: E402

FOUND_BY = "發現者：2026-09-16 當輪自己更正"
SEEDED_BY = "登錄者：2026-09-16 19:2x 自動接續（逐行開檔驗過出處）"

SEEDS = [
    dict(
        original_claim="事件帳本裡有 lineage 邊，從事件節點往下游走得通",
        corrected_claim=(
            "`event_ledger.py:122` 的 LINEAGE_EDGES 只定義未實作，"
            "同檔 SPEC_DEVIATIONS 自己寫著「等 claim 與 decision 存在」，"
            "所以現在沒有邊可以走"),
        failure_mechanism=(
            "看到常數名稱就當成功能存在。那個常數旁邊五行就寫著它沒實作，"
            "但判斷在讀到說明之前就已經下完了"),
        source_events=[
            ".forseti/ROADMAP.md:121",
            "apps/forseti-cli/event_ledger.py:122",
            "apps/forseti-cli/event_ledger.py:132",
        ],
        affected_decisions=["Blast Radius 的做法（§16.1）"],
        radius_basis="沒有量過這個誤判往下游帶出幾個結論，規格也沒定義單位",
    ),
    dict(
        original_claim="Blast Radius 缺的是查詢與畫面",
        corrected_claim=(
            "反向可達 BFS 與 CostVector 早就完整實作在 `src/cost.js`"
            "（`reverseReachable` 在第 62 行，`computeCostVector` 在第 107 行），"
            "真正缺的是餵給它的真實 import 邊"),
        failure_mechanism=(
            "從「畫面上看不到」推論「後端沒有」。看得見的那一層缺，"
            "不代表底下那一層缺，而這個推論方向從來沒有被檢查過"),
        source_events=[".forseti/ROADMAP.md:126", "src/cost.js:62", "src/cost.js:107"],
        affected_decisions=["差點在 Python 重寫一套已經存在的演算法"],
        radius_basis="沒有量過。這一筆被抓到得早，下游結論還沒長出來",
        preventive_rule=(
            "動手寫新模組之前先 `grep -rl` 找概念，不只看檔名。"
            "已寫進排程任務說明的「動手寫任何新模組之前，先確認它不存在」"),
    ),
    dict(
        original_claim="`vitals.dimensions()` 已經逐輪算八個維度",
        corrected_claim=(
            "它只算當下一次，內部取最後 20 輪"
            "（`vitals.py:589` 的註解寫著原因）。"
            "健康曲線是靠反覆餵前綴做出來的，不是讀現成的逐輪結果"),
        failure_mechanism=(
            "把函式回傳的東西的形狀，當成它內部算過的東西的形狀。"
            "回傳八個維度不等於逐輪算過八個維度"),
        source_events=[".forseti/ROADMAP.md:108", "apps/forseti-cli/vitals.py:589"],
        affected_decisions=["Health Curve 的實作方式（§16.1）"],
        radius_basis="沒有量過",
    ),
    dict(
        original_claim=(
            "那兩條紅燈跟那一輪無關，兩個測試檔的 mtime 是 "
            "09-16 13:11 與 09-08 10:14"),
        corrected_claim=(
            "測試檔是 09-11 13:00 與 09-08 10:14；"
            "09-16 13:11 是 `hooks/forseti-stop-hook.mjs` 自己，也就是被測對象。"
            "這兩條紅燈正是 09-16 那次改 hook 造成的"),
        failure_mechanism=(
            "把被測檔的時間當成測試檔的時間，於是因果整個反過來，"
            "把自己剛造成的問題判成無主的舊帳"),
        source_events=[".forseti/ROADMAP.md:502", ".forseti/BLOCKERS.md"],
        affected_decisions=["B-15 要不要現在處理"],
        radius_basis="沒有量過。這個誤判只存在一輪就被實測推翻",
    ),
]


def main() -> int:
    existing = {r["id"] for r in pollution.records()}
    added = skipped = 0
    for s in SEEDS:
        kw = dict(s)
        kw["verifier"] = f"{FOUND_BY}；{SEEDED_BY}"
        pid = pollution._id(kw["original_claim"], kw["failure_mechanism"])
        if pid in existing:
            print(f"已經有了，跳過　{pid}")
            skipped += 1
            continue
        r = pollution.record(**kw)
        if not r["ok"]:
            print(f"退回　{r['why']}")
            return 1
        print(f"登錄　{r['record']['id']}　{r['record']['original_claim'][:34]}")
        added += 1
    print(f"\n新增 {added} 筆，跳過 {skipped} 筆")
    s = pollution.summary()
    print(f"登記簿現在 {s['total']} 筆，未解決 {s['open']} 筆，"
          f"半徑沒量到 {s['radius_unknown']} 筆")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
