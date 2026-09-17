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


def _why_no_lg(els: dict) -> str:
    """沒有 last_good 的時候那句話。**主詞要講出來。**

    先前寫的是「沒有任何 checkpoint 被標成 last_good」,沒有主詞,
    而它算的只有這條 session。碟上另有被標記的時候,那句話讀起來是
    一句全稱否定,對接手的人是誤導。
    """
    why = ("這條 session 沒有任何 checkpoint 被標成 last_good。"
           "系統不自己挑 —— 最近的那一個常常正是出事的那一個")
    if els.get("last_good"):
        why += (f"。碟上另有 {els['last_good']} 個被標成 last_good 的 "
                f"checkpoint,分屬 {els['sessions']} 條別的 session。"
                "**它們不在這條線上** —— 算不算數是 owner 的決定,"
                "這裡只把它們存在這件事講出來")
    return why


def elsewhere(session: str, path: Path | None = None) -> dict:
    """碟上**不屬於這條 session** 的 checkpoint 有哪些。只講事實。

    ## 為什麼要有這一支

    2026-09-17 實測:`.forseti/checkpoints.jsonl` 裡有 3 筆,全部
    `last_good=True`,分屬兩條舊 session。而這一條 session 是 0 筆,
    於是交接檔對接手的人說的是「一個 checkpoint 都沒有」「沒有任何
    checkpoint 被標成 last_good」。兩句話各自都對(主詞是這條 session),
    合起來讀卻是「完全沒有可以回去的點」—— 而碟上有三個,是人親手標的。

    ## 這一支不做判斷

    **不跨 session 挑 last_good。** `last_good()` 的政策沒有改,
    這裡回的是一組數字,讓上層把事實講出來,而「別條 session 的點
    算不算這條線上的點」仍然是 owner 的決定。這一條跟模組說明
    「系統自己挑會挑到最近的那一個」是同一個理由:講事實不代表可以
    替人做選擇。
    """
    rows = [r for r in load(path=path)
            if r.get("session", "") != session]
    marked = [r for r in rows if r.get("last_good")]
    return {
        "total": len(rows),
        "last_good": len(marked),
        "sessions": len({r.get("session", "") for r in rows}),
        "latest_at": max((r.get("at", 0) for r in rows), default=None),
    }


def summary(session: str, path: Path | None = None) -> dict:
    rows = load(session=session, path=path)
    lg = last_good(session, path)
    els = elsewhere(session, path)
    return {
        "total": len(rows),
        # 碟上別條 session 的那些。**不併進 total** —— 兩個回答的不是
        # 同一個問題(這條線上有沒有 ／ 這台機器上有沒有)。
        "elsewhere": els,
        "rows": [{"id": r["id"], "n": r["n"], "reason": r["reason"],
                  "at": r["at"], "last_good": r.get("last_good", False),
                  "goal": (r.get("goal") or "")[:80],
                  "unknowns": len(r.get("unknowns") or [])}
                 for r in rows[-12:]][::-1],
        "last_good": ({"id": lg["id"], "n": lg["n"], "at": lg["at"]} if lg else None),
        "why_no_last_good": (None if lg else _why_no_lg(els)),
        "reasons": list(REASONS),
    }
