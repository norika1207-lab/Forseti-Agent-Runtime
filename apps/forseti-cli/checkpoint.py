#!/usr/bin/env python3
"""Checkpoint。可以回去的那一刻。v5.0 §17、階段 5

**Python 端先前完全沒有這個東西。** `PHASE_STATUS.md` 把階段 5 叫
「Checkpoint 與 Fork」，而實際上只有 fork，checkpoint 一行都沒有。
真正的實作在 `src/recovery.js` 302 行，沒接。

## 存什麼

v5.0 §25 的驗收標準給了答案:殺掉一個 session，後繼者要能

    正確回答目標、已接受的決策、未解決的未知、最後已知良好狀態

所以這四樣就是 checkpoint 的內容。不多存，也不能少存。
**不存對話全文** —— §3.2 的非目標明寫「不把完整歷史對話倒進每個
後繼 session」，而且全文本來就在 jsonl 裡，這裡存的是座標與結論。

## 為什麼不自動存每一輪

v5.0 P0 第 5 項寫的是「meaningful state transition 才建立」。
每一輪都存會讓 checkpoint 變成另一份 transcript，
那時候「回到哪一個」本身就變成一個要花力氣回答的問題。

## last_good 是一個標記不是一個判斷

這裡不自己決定哪一個是「最後已知良好」。一個 checkpoint 要被標成
last_good，必須有人（或某個 deterministic 條件）明確說它是。
系統自己挑會挑到「最近的那一個」，而最近的那一個常常正是出事的那一個。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "checkpoints.jsonl"

REASONS = ("TASK_FINISHED", "BEFORE_RISKY", "OWNER_MARK",
           "COMPACTION_BOUNDARY", "HANDOFF")


def _cid(row: dict) -> str:
    raw = f"{row.get('at')}|{row.get('session')}|{row.get('n')}|{row.get('reason')}"
    return "cp-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def create(*, session: str, n: int, reason: str,
           goal: str = "", decisions: list | None = None,
           unknowns: list | None = None, verified: list | None = None,
           last_good: bool = False, at: float | None = None,
           path: Path | None = None) -> dict:
    """落一個 checkpoint。四樣缺一不可，但允許是空清單。

    `reason` 只收 `REASONS` 裡的。理由跟事件帳本一樣:
    一個什麼都能填的欄位，三個月後沒有人知道當初為什麼存這一筆。
    """
    if reason not in REASONS:
        return {"ok": False,
                "why": f"理由要是這幾種之一：{'、'.join(REASONS)}"}
    row = {
        "at": at or time.time(),
        "session": str(session or ""),
        "n": int(n),
        "reason": reason,
        # v5.0 §25 的四件事。
        "goal": goal,
        "decisions": list(decisions or []),
        "unknowns": list(unknowns or []),
        "verified": list(verified or []),
        # 這個標記只能由外面給，系統不自己挑 —— 見模組說明。
        "last_good": bool(last_good),
    }
    row["id"] = _cid(row)
    p = path or LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "checkpoint": row}


def load(*, session: str | None = None, path: Path | None = None) -> list[dict]:
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


def last_good(session: str, path: Path | None = None) -> dict | None:
    """最後一個被明確標成 last_good 的。沒有就回 None。

    **沒有就是沒有，不退而求其次拿最近的那一個。**
    最近的那一個常常正是出事的那一個。
    """
    marked = [r for r in load(session=session, path=path) if r.get("last_good")]
    return max(marked, key=lambda r: r.get("at", 0)) if marked else None


def summary(session: str, path: Path | None = None) -> dict:
    rows = load(session=session, path=path)
    lg = last_good(session, path)
    return {
        "total": len(rows),
        "rows": [{"id": r["id"], "n": r["n"], "reason": r["reason"],
                  "at": r["at"], "last_good": r.get("last_good", False),
                  "goal": (r.get("goal") or "")[:80],
                  "unknowns": len(r.get("unknowns") or [])}
                 for r in rows[-12:]][::-1],
        "last_good": ({"id": lg["id"], "n": lg["n"], "at": lg["at"]} if lg else None),
        "why_no_last_good": (None if lg else
                             "沒有任何 checkpoint 被標成 last_good。"
                             "系統不自己挑 —— 最近的那一個常常正是出事的那一個"),
        "reasons": list(REASONS),
    }
