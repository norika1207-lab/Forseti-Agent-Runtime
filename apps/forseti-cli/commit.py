#!/usr/bin/env python3
"""Two-Phase Agent Commit。準備跟提交是兩個權限等級。v5.0 §9.3

    DRAFT → PREPARING → PREPARED → AWAITING_APPROVAL → COMMITTED
                ↘                        ↘
                 CANCELLED                ROLLED_BACK

規格給的四個例子:

    email     draft = PREPARE；send = COMMIT
    ads       create PAUSED = PREPARE；enable spend = COMMIT
    deploy    build/stage = PREPARE；production switch = COMMIT
    database  generate migration = PREPARE；execute migration = COMMIT

## 為什麼這一層必須存在

§26 第 5 條是「不准倒退」的十條之一:
**絕不把準備與不可逆提交合併成單一權限位元。**

合併之後會發生的事是這樣:一個有權限「做這件事」的東西，
自動就有權限「做完這件事」。而真實世界裡這兩者的風險差了幾個數量級 ——
把信寫好跟把信寄出去，差別在於後者收不回來。

`authority.decide()` 已經會對跨邊界的動作回 PREPARE，
但它只回答「該不該」。這一支回答「做到哪了」——
一個停在 PREPARED 的東西，跟一個沒開始的東西，
在畫面上必須看得出差別，不然人會以為它沒做。

## 外部效果的 id 要留著

`external_ref` 是準備階段在外部系統建立的東西（草稿 id、
PAUSED 的廣告 id、staging 的 build id）。**沒有它就沒辦法 rollback** ——
你知道自己做了某件事，但找不到那個東西在哪。
FB-ADS-Automatic 的教訓:所有物件先建成 PAUSED，
人來按下去才開始花錢（v5.0 §28 對照表）。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "commits.jsonl"

STATES = ("DRAFT", "PREPARING", "PREPARED", "AWAITING_APPROVAL",
          "COMMITTED", "CANCELLED", "ROLLED_BACK")

TERMINAL = ("COMMITTED", "CANCELLED", "ROLLED_BACK")

#: 誰可以轉到哪。**COMMITTED 只能從 AWAITING_APPROVAL 來** ——
#: 那一格就是人按下去的那一刻，跳過它等於把兩個權限等級合成一個。
ALLOWED: dict[str, tuple[str, ...]] = {
    "DRAFT": ("PREPARING", "CANCELLED"),
    "PREPARING": ("PREPARED", "CANCELLED"),
    "PREPARED": ("AWAITING_APPROVAL", "CANCELLED"),
    "AWAITING_APPROVAL": ("COMMITTED", "CANCELLED"),
    "COMMITTED": ("ROLLED_BACK",),
    "CANCELLED": (),
    "ROLLED_BACK": (),
}

#: 只有這個 principal 能把東西推過 commit 邊界。
COMMIT_PRINCIPAL = "OWNER"


class CommitError(Exception):
    """不合法的轉換。**拒絕而不是修正** —— 自動修正會把錯誤藏起來。"""


def _cid(kind: str, subject: str, at: float) -> str:
    raw = f"{kind}|{subject}|{at}"
    return "tx-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def _append(row: dict, path: Path | None = None) -> None:
    p = path or LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load(path: Path | None = None) -> list[dict]:
    p = path or LOG
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def state_of(tx_id: str, path: Path | None = None) -> str:
    """現在在哪一格。append-only，所以看最後一筆。"""
    st = ""
    for r in load(path):
        if r.get("tx") == tx_id:
            st = r.get("to", st)
    return st


def open_tx(*, kind: str, subject: str, actor: str = "agent",
            at: float | None = None, path: Path | None = None) -> dict:
    """開一筆。一律從 DRAFT 開始，沒有捷徑。"""
    now = at or time.time()
    tx = _cid(kind, subject, now)
    _append({"at": now, "tx": tx, "kind": kind, "subject": subject,
             "from": "", "to": "DRAFT", "actor": actor,
             "cause": "開啟"}, path)
    return {"ok": True, "tx": tx, "state": "DRAFT"}


def advance(tx_id: str, to_state: str, *, actor: str = "agent",
            cause: str = "", external_ref: str = "",
            at: float | None = None, path: Path | None = None) -> dict:
    """往下一格。

    三條硬規則：

    一，**沒有 cause 不准轉。** 跟 `ledger.transition` 同一條
        （F02 §5）。一個說不出為什麼的狀態轉換，事後沒有人查得出來。

    二，**COMMITTED 只有 OWNER 能按。** 這是整個模組存在的理由。

    三，**要提交就得有 external_ref。** 準備階段在外部系統建了東西，
        沒有把 id 留下來的話，之後想 rollback 會找不到那個東西在哪。
    """
    cur = state_of(tx_id, path)
    if not cur:
        raise CommitError(f"沒有這一筆：{tx_id}")
    if to_state not in STATES:
        raise CommitError(f"不認得的狀態：{to_state}")
    if to_state not in ALLOWED.get(cur, ()):
        raise CommitError(
            f"{cur} 不能直接到 {to_state}。"
            f"允許的只有：{'、'.join(ALLOWED.get(cur, ())) or '（終局，不能再轉）'}")
    if not cause.strip():
        raise CommitError("沒有 cause 不准轉。說不出為什麼的轉換事後查不出來")
    if to_state == "COMMITTED":
        if actor != COMMIT_PRINCIPAL:
            raise CommitError(
                f"只有 {COMMIT_PRINCIPAL} 能跨過 commit 邊界。"
                "§26 第 5 條：準備與不可逆提交不能合成單一權限位元")
        prev = [r for r in load(path) if r.get("tx") == tx_id]
        if not any(r.get("external_ref") for r in prev) and not external_ref:
            raise CommitError(
                "要提交就得有 external_ref。沒有它就沒辦法 rollback ——"
                "你知道自己做了某件事，但找不到那個東西在哪")

    now = at or time.time()
    row = {"at": now, "tx": tx_id, "from": cur, "to": to_state,
           "actor": actor, "cause": cause}
    if external_ref:
        row["external_ref"] = external_ref
    _append(row, path)
    return {"ok": True, "tx": tx_id, "from": cur, "state": to_state}


def pending(path: Path | None = None) -> list[dict]:
    """停在半路的。**這一份是給人看的重點。**

    一個停在 PREPARED 的東西，跟一個沒開始的東西，
    在畫面上必須看得出差別，不然人會以為它沒做。
    """
    seen: dict = {}
    for r in load(path):
        tx = r.get("tx")
        if not tx:
            continue
        e = seen.setdefault(tx, {"tx": tx, "kind": r.get("kind", ""),
                                 "subject": r.get("subject", ""),
                                 "opened_at": r.get("at")})
        e["state"] = r.get("to", "")
        e["at"] = r.get("at")
        if r.get("external_ref"):
            e["external_ref"] = r["external_ref"]
        if r.get("kind"):
            e["kind"] = r["kind"]
        if r.get("subject"):
            e["subject"] = r["subject"]
    out = [e for e in seen.values() if e.get("state") not in TERMINAL]
    out.sort(key=lambda e: e.get("opened_at") or 0)
    for e in out:
        e["waiting_for"] = ("你按下去" if e["state"] == "AWAITING_APPROVAL"
                            else "還在準備")
    return out


def summary(path: Path | None = None) -> dict:
    rows = load(path)
    pend = pending(path)
    done = {r["tx"] for r in rows if r.get("to") == "COMMITTED"}
    return {
        "total": len({r.get("tx") for r in rows if r.get("tx")}),
        "pending": pend,
        "awaiting_owner": [e for e in pend if e["state"] == "AWAITING_APPROVAL"],
        "committed": len(done),
        "states": list(STATES),
        "note": "準備跟提交是兩個權限等級（§9.1）。"
                "停在 PREPARED 不等於沒做，它是做到最後一步為止在等人按",
    }
