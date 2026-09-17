#!/usr/bin/env python3
"""第一個分歧點。v5.0 §16.4、§6.3

## 為什麼不是一個點

§6.3 的標題就是答案:**不可假裝只有一個精確點。**
規格要三種，因為它們回答三個不同的問題：

| 種類 | 問題 | 用途 |
|---|---|---|
| Earliest Suspicious | 第一個離開健康基線的區段 | 最早的警訊，可能是誤報 |
| Earliest Confirmed | 第一個有足夠證據可分類的區段 | 可以下結論的起點 |
| First Consequential | 第一個真的造成代價的區段 | **fork 要回到這裡之前** |

三者常常不同輪。只報一個的話,回答的是哪一題就變成看運氣。

## FS-DRF-004:不准製造假精確

    如果 evidence 不足以定位單一 turn，MUST 回傳 event/turn range，
    而不是製造 false precision。

所以每一種都回 `(from_n, to_n)` 而不是一個數字。範圍只有一輪寬的時候，
它自然就是一個點 —— 但那是資料說的，不是我們硬指的。

## 代價怎麼算

`First Consequential` 要的是「真的造成 cost / artifact / plan /
human workload 後果」。這裡用可觀測的三種：

    她出手糾正         人力代價，OBSERVED 級
    工具失敗           執行代價
    白點後面跟著寫入    那次寫入是建立在錯的宣稱上

**不用「距離變大」當代價。** 距離是徵狀不是後果，
把徵狀算成後果會讓 First Consequential 一路往前跑到最早那一輪。
"""

from __future__ import annotations

#: 目標距離超過這個值算離開健康基線。跟 vitals / lanes 一致。
BASELINE = 0.08

#: 幾種問題同時出現才算「足夠證據可分類」。§6.2 要至少兩個獨立證據維度。
CONFIRM_DIMENSIONS = 2


def _n(r: dict) -> int:
    return int(r.get("n") or 0)


def _dims(r: dict) -> set:
    """這一輪出現了哪幾種問題。用種類不用次數 —— §6.2 要的是維度。"""
    out = set()
    if (r.get("betrayals") or []):
        out.add("BETRAYAL")
    if (r.get("overclaims") or []):
        out.add("OVERCLAIM")
    if (r.get("failed") or 0) > 0:
        out.add("TOOL_FAIL")
    if ((r.get("goal") or {}).get("distance") or 0) > BASELINE:
        out.add("DRIFT")
    if r.get("compaction"):
        out.add("COMPACT")
    return out


def _consequence(rows: list, i: int) -> str:
    """這一輪有沒有造成真的後果。回原因，沒有就回空字串。"""
    r = rows[i]
    if r.get("corrected_by_owner"):
        return "她出手糾正了（人力代價，OBSERVED 級）"
    if (r.get("failed") or 0) > 0:
        return f"{r['failed']} 次工具失敗"
    if (r.get("betrayals") or []):
        for later in rows[i + 1:i + 4]:
            if (later.get("write") or 0) > 0:
                return f"白點之後第 {_n(later)} 輪有寫入，那次寫入建立在錯的宣稱上"
    return ""


def _range(rows: list, i: int) -> tuple:
    """把一個索引擴成範圍。FS-DRF-004 不准製造假精確。

    往前找到同一段連續異常的開頭 —— 因為「第一個被偵測到的輪」
    跟「事情開始的輪」常常不是同一輪。
    """
    start = i
    while start > 0 and _dims(rows[start - 1]):
        start -= 1
    return (_n(rows[start]), _n(rows[i]))


def find(rows: list) -> dict:
    """算三種分歧點。每一種都回範圍，不回單點。"""
    if not rows:
        return {"has": False, "why": "沒有資料"}

    suspicious = confirmed = consequential = None
    conf_why = cons_why = ""

    for i, r in enumerate(rows):
        d = _dims(r)
        if d and suspicious is None:
            suspicious = _range(rows, i)
        if len(d) >= CONFIRM_DIMENSIONS and confirmed is None:
            confirmed = _range(rows, i)
            conf_why = f"同一輪出現 {len(d)} 種：{'、'.join(sorted(d))}"
        if consequential is None:
            c = _consequence(rows, i)
            if c:
                consequential = _range(rows, i)
                cons_why = c

    out = {
        "has": bool(suspicious or confirmed or consequential),
        "earliest_suspicious": suspicious,
        "earliest_confirmed": confirmed,
        "first_consequential": consequential,
        "confirmed_why": conf_why,
        "consequential_why": cons_why,
        "baseline": BASELINE,
        "confirm_dimensions": CONFIRM_DIMENSIONS,
    }

    # fork 要回到「造成後果之前」，不是回到「第一個警訊之前」。
    # 第一個警訊常常是誤報，回太早等於把好的工作一起丟掉。
    if consequential:
        out["fork_before"] = consequential[0]
        out["fork_why"] = ("回到第一個真的造成後果的區段之前。"
                           "不用最早的警訊當基準 —— 那常常是誤報，"
                           "回太早會把好的工作一起丟掉")
    else:
        out["fork_before"] = None
        out["fork_why"] = "沒有任何一輪造成可觀測的後果，沒有需要回去的點"

    # 三種落在不同輪的時候，那個差距本身是資訊。
    pts = [p for p in (suspicious, confirmed, consequential) if p]
    if len(pts) >= 2:
        lo = min(p[0] for p in pts)
        hi = max(p[1] for p in pts)
        out["spread"] = (lo, hi)
        out["spread_note"] = (f"三種分歧點散在第 {lo} 到 {hi} 輪之間。"
                              "只報一個的話，回答的是哪一題就變成看運氣")
    return out


def summary(rows: list) -> dict:
    f = find(rows)
    if not f.get("has"):
        return dict(f, note="這段還沒有任何離開基線的地方")
    return dict(f, note="§6.3 不可假裝只有一個精確點。三種回答三個不同的問題，"
                        "而且都回範圍不回單點（FS-DRF-004）")
