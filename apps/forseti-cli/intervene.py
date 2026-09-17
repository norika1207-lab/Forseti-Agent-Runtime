#!/usr/bin/env python3
"""什麼時候可以動手，動手前要問什麼。§32

`src/intervention.js` 規格書 v0.1 第 9、10、11 節。
寫好了，到 2026-09-15 一行都沒接進任何地方。

owner 2026-09-15：

    接 intervention.js，我又要變工人了嗎？你沒做完的不能自己全部做完？

那句話本身就是這個模組要防的東西：她必須開口，介面才動。

## 觀測者效應是這裡最硬的一條

規格 9.1：不可以持續盤問被觀測的模型，因為那會改變正在被量測的東西。

這不是禮貌問題，是量測問題。每問一次「你還在跟著目標嗎」，
那個問題本身就進了 context，接下來的行為是「被問過之後的行為」，
不是「原本的行為」。問十次之後，量到的是自己造成的東西。

**所以每一次介入都必須被記成 intervention event**，
後續分析才分得出「介入前」跟「介入後」。這條沒有例外。

## 高溫不是動手的理由

`canIntervene` 的每一個動作都要求溫度**加上**一個可驗證的事實：
進度停滯、證據對不上、重試預算用完、假設被推翻。
只有溫度高就動手，等於拿一個沒有單位的數字當授權。

## 判準照抄 src/intervention.js

不自己改門檻。兩邊分歧的那天沒有人會發現。

零依賴（ADR-009）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

PLANES = ("OBSERVATION", "INTERVENTION")

ACTIONS = ("QUIET_ANNOTATION", "SUGGEST_RECOVERY", "FREEZE_RETRY",
           "REPLAN", "BLOCK_HIGH_RISK", "CREATE_SUCCESSOR")

ACTION_MEANING = {
    "QUIET_ANNOTATION": "安靜標註。不打斷，只在線上留一個記號",
    "SUGGEST_RECOVERY": "建議復原。給一句可以直接用的話",
    "FREEZE_RETRY": "凍結重試。同一個錯法一直重複，再試也不會對",
    "REPLAN": "重新規劃。當前的假設被推翻了",
    "BLOCK_HIGH_RISK": "擋下高風險動作。前提條件不明",
    "CREATE_SUCCESSOR": "建立接班 session。這一個已經帶不動了",
}

# 這些問法一律不准用。問了只會拿到流利的否認。
FORBIDDEN = (
    "你是不是飄移了", "你還在跟著目標嗎", "一切都還好嗎",
    "Are you drifting?", "Are you still following the goal?",
)


def can_intervene(action: str, ctx: dict | None = None) -> dict:
    """照 src/intervention.js 的 canIntervene。

    **高溫不是動手的理由。** 每一個動作都要溫度加上一個可驗證的事實。
    """
    if action not in ACTIONS:
        raise ValueError(f"不認得的動作：{action}。可用：{' / '.join(ACTIONS)}")
    c = ctx or {}
    t = c.get("temperature")

    def hot(x: float) -> bool:
        return t is not None and t >= x

    if action == "QUIET_ANNOTATION":
        ok = hot(c.get("annotation_threshold", 0.5)) or c.get("verified_anomaly") is True
        need = "溫度到標註門檻，或者有一個查證過的異常"
    elif action == "SUGGEST_RECOVERY":
        ok = hot(0.7) and (c.get("progress_stagnation") is True
                           or c.get("evidence_mismatch") is True)
        need = "高溫，而且進度停滯或證據對不上"
    elif action == "FREEZE_RETRY":
        ok = (c.get("retry_budget_exceeded") is True
              and c.get("progress_stagnation") is True)
        need = "重試預算用完，而且沒有驗證過的進度"
    elif action == "REPLAN":
        ok = (c.get("hypothesis_refuted") is True
              or c.get("prerequisite_unknown") is True)
        need = "當前假設被推翻，或者一個硬前提失效"
    elif action == "BLOCK_HIGH_RISK":
        ok = c.get("prerequisite_unknown") is True
        need = "權限、授權或安全的硬前提不明或被推翻"
    else:                                    # CREATE_SUCCESSOR
        ok = (c.get("context_exhausted") is True
              or c.get("unrecoverable") is True)
        need = "context 用盡，或者這一條線已經救不回來"

    return {"action": action, "allowed": bool(ok), "need": need,
            "meaning": ACTION_MEANING[action]}


def build_probe(reason: str = "", window_ref: str = "") -> dict:
    """要問模型的時候，問可以被查核的東西。

    **這個探針不問「你是不是飄移了」。** 問了只會拿到流利的否認。
    回答本身是 DECLARED，對照到可觀測的現實之前不會升級。
    """
    return {
        "reason": reason,
        "window_ref": window_ref,
        "forbidden": list(FORBIDDEN),
        "must_log_as_intervention": True,
        # 回答的認知上限。沒有對照現實之前，它只是宣稱。
        "answer_epistemic_ceiling": "INFERRED",
    }


def decide(snap: dict) -> list[dict]:
    """從一份 strands 快照算出現在可以做哪些介入。§32

    每一個回傳都帶著「憑什麼」—— 一個說不出理由的介入沒辦法被反駁，
    而不能被反駁的介入等於沒有判斷。
    """
    total = snap.get("total_dots") or 0
    failed = snap.get("total_failed") or 0
    ctx_state = snap.get("context") or {}
    rows = snap.get("rows") or []

    # 溫度就是失敗比例。**不合成、不加權、沒有沒有單位的分數。**
    temperature = (failed / total) if total else 0.0

    # 進度停滯：最近五輪裡有一半以上是空輸出或沒動作。
    tail = rows[-5:]
    stalled = sum(1 for r in tail
                  if r.get("starving") or
                  any(g[1] - g[0] >= 300 for g in (r.get("gaps") or [])))
    stagnation = len(tail) >= 3 and stalled >= len(tail) / 2

    ctx = {
        "temperature": temperature,
        # 證據對不上 = 有確認過的白點。那是查證過的，不是推測。
        "evidence_mismatch": bool(snap.get("betrayal_total")),
        "verified_anomaly": bool(snap.get("betrayal_total")),
        "progress_stagnation": stagnation,
        # 同一個錯法重複 = 重試預算用完。
        "retry_budget_exceeded": failed >= 20,
        # context 用盡：離壓縮不到一成。
        "context_exhausted": (ctx_state.get("pct") or 0) >= 90,
    }

    out = []
    for a in ACTIONS:
        r = can_intervene(a, ctx)
        if r["allowed"]:
            r["why"] = _why(a, ctx, snap)
            out.append(r)
    return out


def _why(action: str, ctx: dict, snap: dict) -> str:
    """這個介入憑什麼現在可以做。指得出是從哪一筆資料算的。"""
    t = ctx["temperature"]
    if action == "QUIET_ANNOTATION":
        if ctx["verified_anomaly"]:
            return f"有 {snap.get('betrayal_total')} 個查證過的異常"
        return f"失敗比例 {t:.0%} 到了標註門檻"
    if action == "SUGGEST_RECOVERY":
        bits = []
        if ctx["progress_stagnation"]:
            bits.append("最近幾輪沒有進度")
        if ctx["evidence_mismatch"]:
            bits.append("有宣稱跟證據對不上")
        return f"失敗比例 {t:.0%}，而且" + "、".join(bits)
    if action == "FREEZE_RETRY":
        return f"{snap.get('total_failed')} 次工具失敗而且沒有進度"
    if action == "CREATE_SUCCESSOR":
        c = snap.get("context") or {}
        return f"記憶用了 {c.get('pct')}%，離壓縮只剩 {c.get('headroom', 0):,} token"
    return ctx.get("need", "")


def record(action: str, why: str, plane: str = "INTERVENTION") -> bool:
    """把這次介入寫進帳本。

    **這條沒有例外。** 介入會改變被觀測的東西，
    後續分析要分得出「介入前」跟「介入後」，就必須知道介入發生在哪一刻。
    寫不進去回 False，不假裝寫進去了。
    """
    d = Path.home() / ".forseti" / "ledgers"
    dbs = sorted(d.glob("*.db")) if d.is_dir() else []
    if not dbs:
        return False
    try:
        c = sqlite3.connect(dbs[0])
        now = time.time()
        payload = {"action": action, "why": why, "plane": plane,
                   "meaning": ACTION_MEANING.get(action, "")}
        idem = hashlib.sha256(f"{action}|{now}".encode()).hexdigest()[:16]
        c.execute(
            "insert into events (at, task_id, step_id, kind, from_state,"
            " to_state, cause, actor, payload, idem_key)"
            " values (?,?,?,?,?,?,?,?,?,?)",
            (str(now), None, None, "INTERVENTION", None, None, why,
             "forseti", json.dumps(payload, ensure_ascii=False), idem))
        c.commit()
        return True
    except Exception:                               # noqa: BLE001
        return False
