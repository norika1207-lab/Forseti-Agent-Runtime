#!/usr/bin/env python3
"""粉紅點。使用者自己在某一輪上寫下的注記。§5.5

owner 2026-09-14 口述（WIDGET_SPEC §5.5）：

    或許我不會常用，但是當我用的時候，
    肯定是有個想法我覺得很重要我要加上去

**價值不在頻率，在那幾次的密度。**

## 為什麼這一支跟其他偵測器不是同一類

白點、金點、紫點都是系統算給她看的，粉紅點是唯一她給系統的。
所以它的證據等級不一樣:那是人在當下親手寫的，不是事後回憶，
也不是系統推斷。`HUMAN_ADJUDICATION` 是這套系統裡最高的一級，
高過任何 deterministic check ——
因為那些檢查驗的是「事情有沒有發生」，她寫的是「這件事重不重要」，
後者沒有任何演算法算得出來。

## 沒有它，金點永遠出不來

§5.3 的金點要判「你這次的決策跟過去不同」，那需要知道過去哪些決策
是重要的。系統自己標不出來 —— 它只看得到她說了什麼，看不到她
當時在想什麼。粉紅點就是那個標記，是金點唯一的訓練資料來源。

## 只增不改

跟事件帳本同一個原則。寫下去的當下就是證據，事後改掉就不是了。
要更正就再寫一則，舊的留著。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "notes.jsonl"

#: 一則注記的上限。不設限的話它會變成另一個貼全文的地方，
#: 而那正是 handoff 失效的原因（bible H-01）。
MAX_CHARS = 1200

PROVENANCE = "HUMAN_ADJUDICATION"


def add(text: str, *, session: str, n: int,
        at: float | None = None, path: Path | None = None) -> dict:
    """寫一則。回寫進去的那一筆，或拒絕的理由。"""
    t = (text or "").strip()
    if not t:
        return {"ok": False, "why": "空的注記不寫。沒有內容的標記等於雜訊"}
    if len(t) > MAX_CHARS:
        return {"ok": False,
                "why": f"超過 {MAX_CHARS} 字。注記是標記不是文件，"
                       "太長的東西應該寫成檔案再從這裡指過去"}
    row = {
        "at": at or time.time(),
        "session": str(session or ""),
        "n": int(n),
        "text": t,
        "provenance": PROVENANCE,
    }
    p = path or LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "note": row}


def load(*, session: str | None = None, path: Path | None = None) -> list[dict]:
    """讀。給了 session 就只回那一條線的。"""
    p = path or LOG
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if session is not None and r.get("session", "") != session:
            continue
        out.append(r)
    return out


def by_turn(session: str, path: Path | None = None) -> dict:
    """輪號 → 那一輪的所有注記。畫面直接吃這個。"""
    out: dict = {}
    for r in load(session=session, path=path):
        out.setdefault(int(r.get("n") or 0), []).append(r)
    return out


def summary(session: str, path: Path | None = None) -> dict:
    rows = load(session=session, path=path)
    turns = sorted({int(r.get("n") or 0) for r in rows})
    return {
        "total": len(rows),
        "turns": turns,
        "provenance": PROVENANCE,
        "note": "這是唯一由使用者寫入的證據。系統算出來的東西都不能"
                "覆蓋它，也不能拿它去推論她沒說的事",
    }
