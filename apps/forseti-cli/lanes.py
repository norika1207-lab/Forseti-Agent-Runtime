#!/usr/bin/env python3
"""問題軌道。一個沒被解決的問題就是一條線，解決了才收回來。

owner 2026-09-15：

    fork 會到新的 session，而是 Forseti 本來建議可能怎麼做會比較好，
    用戶下的指令偏離了，於是越做越歪，
    每個決定都會跟 forseti 的建議做分岔

先前的做法是拿「還站著的建議」當軌道，但建議是用當下狀態算出來的，
它只知道「現在有這幾條」，不知道它們從第幾輪就存在。結果每條軌道都是
從第 N 輪到第 N 輪，畫出來是四截短線，不是圖。

**這一支改成從已經發生過的事實回溯。** 每一條軌道都要說得出
「第幾輪開始、第幾輪收回來、憑什麼算收回來」。收不回來的就一直
平行往下走 —— 那就是「越做越歪」在畫面上的樣子。

## 每一種軌道的起點與終點

| 種類 | 起點 | 收回來的條件 |
|---|---|---|
| TOOL_FAIL | 那一輪有工具失敗 | 下一輪沒有失敗 |
| DRIFT | 目標距離超過門檻 | 距離回到門檻以下 |
| BLIND_WRITE | 連續幾輪只讀不寫 | 出現寫入動作 |
| BETRAYAL | 那一輪判出白點 | 下一輪真的有寫入（宣稱終於落地） |
| COMPACT | 對話壓縮那一輪 | **沒有收回來的條件** |

COMPACT 刻意沒有終點:壓縮吃掉的東西不會自己回來。
它一路畫到底，是為了讓「那之後的每一輪都建立在殘缺的記憶上」
這件事在畫面上一直看得見。要收回來只能靠人把脈絡貼回去，
而那個動作現在沒有被記錄，所以這裡不假裝它會結束。

**不合成分數。** 每條軌道獨立存在，同時開著五條就是五條，
不會被壓成一個「健康度 62」。Five Mechanisms §6.8 雷一。
"""

from __future__ import annotations

#: 目標距離超過這個值才算飄出去。跟 vitals 的判準一致。
DRIFT_ON = 0.08

#: 只讀不寫連續幾輪才算一條軌道。一兩輪在找東西是正常的。
BLIND_MIN = 3

#: 一條軌道至少要跨幾輪才畫。單輪事件是點不是線。
MIN_SPAN = 1

KINDS = ("COMPACT", "BETRAYAL", "DRIFT", "TOOL_FAIL", "BLIND_WRITE")

_LABEL = {
    "COMPACT": "對話壓縮，記憶不完整",
    "BETRAYAL": "說了沒做，還沒落地",
    "DRIFT": "偏離目標",
    "TOOL_FAIL": "工具連續失敗",
    "BLIND_WRITE": "一直在找，還沒動手",
}


def _n(r: dict) -> int:
    return int(r.get("n") or 0)


def _runs(rows: list, pred, *, min_len: int = 1) -> list[tuple[int, int, bool]]:
    """連續滿足 pred 的區段。回 (起 n, 訖 n, 是否延伸到最後)。"""
    out: list[tuple[int, int, bool]] = []
    start = None
    for i, r in enumerate(rows):
        if pred(r):
            if start is None:
                start = i
        elif start is not None:
            if i - start >= min_len:
                out.append((_n(rows[start]), _n(rows[i - 1]), False))
            start = None
    if start is not None and len(rows) - start >= min_len:
        out.append((_n(rows[start]), _n(rows[-1]), True))
    return out


def lanes(rows: list) -> list[dict]:
    """把一條線上所有沒收回來的問題算成軌道。

    回傳按起點排序。每一筆都帶 `open`:True 代表到最後一輪都還沒收回來。
    """
    if not rows:
        return []
    out: list[dict] = []

    for a, b, openish in _runs(rows, lambda r: (r.get("failed") or 0) > 0):
        out.append({"kind": "TOOL_FAIL", "from_n": a, "to_n": b, "open": openish})

    for a, b, openish in _runs(
            rows, lambda r: ((r.get("goal") or {}).get("distance") or 0) > DRIFT_ON):
        out.append({"kind": "DRIFT", "from_n": a, "to_n": b, "open": openish})

    for a, b, openish in _runs(
            rows,
            lambda r: (r.get("read") or 0) > 0 and (r.get("write") or 0) == 0,
            min_len=BLIND_MIN):
        out.append({"kind": "BLIND_WRITE", "from_n": a, "to_n": b, "open": openish})

    # 白點:那一輪說了沒做。收回來的條件是後面真的有寫入動作 ——
    # 「宣稱終於落地」。找不到就是一路開著。
    for i, r in enumerate(rows):
        if not (r.get("betrayals") or []):
            continue
        end, closed = _n(rows[-1]), False
        for later in rows[i + 1:]:
            if (later.get("write") or 0) > 0:
                end, closed = _n(later), True
                break
        out.append({"kind": "BETRAYAL", "from_n": _n(r), "to_n": end,
                    "open": not closed})

    # 壓縮:沒有收回來的條件，一路畫到底。
    for r in rows:
        if r.get("compaction"):
            out.append({"kind": "COMPACT", "from_n": _n(r),
                        "to_n": _n(rows[-1]), "open": True})

    for x in out:
        x["turns"] = max(1, x["to_n"] - x["from_n"] + 1)
        x["label"] = _LABEL.get(x["kind"], x["kind"])
    out = [x for x in out if x["turns"] >= MIN_SPAN]
    out.sort(key=lambda x: (x["from_n"], x["kind"]))
    return out


def summary(rows: list) -> dict:
    ls = lanes(rows)
    still = [x for x in ls if x["open"]]
    return {
        "lanes": ls,
        "total": len(ls),
        "open": len(still),
        "worst": max((x["turns"] for x in still), default=0),
        "note": "一條軌道就是一個沒被解決的問題。收回來才消失，"
                "所以同時開著幾條就是幾條，不合成一個分數",
    }
