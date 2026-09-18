#!/usr/bin/env python3
"""救回一次。把 divergence、checkpoint、fork 串成一條走得完的流程。

ROADMAP P0 第 1 項，也是 Vol4 Stage 4 的出口條件：

    至少一個真實專案從失敗分支救回來

**零件早就齊了，缺的是沒有人真的走過一次。** `divergence.find()`
算得出該回到哪一輪之前，`checkpoint.create()` 存得住那一刻，
`forkline.fork()` 開得出新線。三個各自有測試，各自都綠，
但它們之間沒有一條路，所以那個出口條件到今天是零次。

這支就是那條路。

## 為什麼流程本身要是一個模組，而不是寫在畫面裡

救援是會留下痕跡的動作：它建立新的 session 檔案，而且它宣稱
「這一段之後的工作被排除了」。那個宣稱如果只存在於按鈕的
onclick 裡，三個月後沒有人查得出當初是憑什麼排除的。

所以這裡的每一步都往 Event Ledger 寫一筆，用的是 v5.0 §6.2
Recovery 類底下本來就有的三個 type：

    INCIDENT_OPEN   出事了，這是事故的起點
    CHECKPOINT      救援動手之前先存一個點
    CLEAN_FORK      真的開了新線，中間那段被排除

三筆事件共用同一個 `incident` id，所以事後查得出它們是同一次救援。

## 回到哪一輪，只有兩個合法來源

**一，有人標過的 last_good checkpoint。** 人的判斷優先。

**二，`divergence.fork_before`。** 第一個真的造成後果的區段之前。

沒有第三個。特別是不准拿「最近的那一個 checkpoint」當退路，
`checkpoint.py` 的檔頭已經寫過理由：最近的那一個常常正是出事的那一個。

兩個來源都沒有的時候回 `can: False` 並說明缺什麼，**不猜一個輪號**。
一個猜出來的 fork 點會把還好的工作一起丟掉，而丟掉的那部分
不會有人發現，因為新線看起來很正常。

## 排除的那一段怎麼算可查核

fork 的機制本身就排除了切點之後的一切（`forkline.fork` 沿
parentUuid 收祖先鏈，切點之後的節點不會進新檔）。所以「排除」
不需要另一個動作，需要的是**把排除了什麼寫下來**：

    quarantined   被排除的輪號範圍
    dropped       實際沒帶過去的節點數，forkline 回報的真實數字

`dropped` 是 forkline 數出來的，不是這裡算的。自己算一次等於
發明第二個真相，而兩個真相不一致的那天沒有人會知道該信哪個。

## 這支不做的事

**不判斷該不該救。** 那是人的決定。這支只回答「如果要救，
回到哪一輪、憑什麼、會丟掉什麼」，然後在被要求的時候執行。

**不自動執行。** `run()` 預設 `dry_run=True`。建立新 session 檔案
是不可逆的（檔案會留在 `~/.claude/projects/`），預設不做。
"""

from __future__ import annotations

import hashlib
import time

#: 回去的點只有這兩個合法來源。沒有第三個，見模組說明。
SOURCES = ("OWNER_MARKED_CHECKPOINT", "FIRST_CONSEQUENTIAL_DIVERGENCE")

#: 救援過程往 Event Ledger 寫的三種事件。全部在 v5.0 §6.2 Recovery 類裡。
EVENT_TYPES = ("INCIDENT_OPEN", "CHECKPOINT", "CLEAN_FORK")


def _iid(session: str, at: float, n) -> str:
    raw = f"{session}|{at}|{n}"
    return "inc-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def plan(rows: list, *, session: str, checkpoints: list | None = None) -> dict:
    """算出這條線該怎麼救。不寫任何東西。

    `checkpoints` 是這條 session 的 checkpoint 清單（`checkpoint.load()`
    的回傳）。給 None 的時候當成一個都沒有，**不去自己讀檔** ，
    因為讀哪一份檔是呼叫端的事，這裡混進去會讓測試沙箱漏一半。
    """
    import divergence as DV

    if not rows:
        return {"can": False, "why": "這條線沒有任何一輪，沒有東西可以救"}

    d = DV.find(rows)
    last_n = int(rows[-1].get("n") or 0)

    # 來源一：有人親手標過的。人的判斷優先於演算法。
    #
    # **挑法必須跟 `checkpoint.last_good()` 完全一致：標記時間最晚的那一筆。**
    # 不是輪號最大的那一筆 —— 她後來改變主意往前標，那個改變要算數。
    # 這裡沒有直接呼叫 `checkpoint.last_good()`，因為那支只吃
    # session 加檔案路徑，而這支收清單是為了讓測試能在沙箱裡跑完整條路。
    # 兩套邏輯會漂開，所以 `test_rescue.py` 有一條測試拿同一份檔案
    # 比對兩邊挑出來的是不是同一筆。
    marked = [c for c in (checkpoints or []) if c.get("last_good")]
    if marked:
        best = max(marked, key=lambda c: c.get("at", 0))
        back_to = int(best.get("n") or 0)
        source = "OWNER_MARKED_CHECKPOINT"
        why = (f"回到有人標成 last_good 的第 {back_to} 輪。"
               f"人標的優先於算出來的")
        cp_id = best.get("id", "")
    else:
        back_to = d.get("fork_before")
        source = "FIRST_CONSEQUENTIAL_DIVERGENCE"
        why = d.get("fork_why", "")
        cp_id = ""

    if not back_to:
        return {
            "can": False,
            "why": ("沒有可以回去的點。沒有人標過 last_good checkpoint，"
                    "而且沒有任何一輪造成可觀測的後果，"
                    "所以 divergence 也算不出 fork_before"),
            "divergence": d,
            "hint": ("要救的話，先在確定還健康的那一輪按「標記這裡是好的」。"
                     "系統不自己挑 —— 最近的那一個常常正是出事的那一個"),
            "sources": list(SOURCES),
        }

    back_to = int(back_to)
    # 被排除的是切點那一輪以後的全部。切點本身留著 ——
    # fork 是「從那一輪的起點接下去」，那一輪還沒發生的事才是要丟的。
    quarantined = (back_to, last_n) if last_n >= back_to else None
    lost = max(0, last_n - back_to + 1)

    return {
        "can": True,
        "session": session,
        "back_to": back_to,
        "source": source,
        "why": why,
        "checkpoint_id": cp_id,
        "quarantined": quarantined,
        "turns_excluded": lost,
        "last_n": last_n,
        "divergence": d,
        "sources": list(SOURCES),
        "note": ("這是計畫不是結果。`run()` 才會真的建立新 session，"
                 "而且預設 dry_run"),
    }


def run(rows: list, *, session: str, checkpoints: list | None = None,
        reason: str = "", dry_run: bool = True,
        fork_fn=None, ledger=None, at: float | None = None,
        goal: str = "", unknowns: list | None = None) -> dict:
    """走完一次救援。三筆事件、一次 fork、一張收據。

    `fork_fn(session, n, dry_run)` 預設用 `forkline.fork_at`。
    可以換掉是為了測試能在沙箱裡跑完整條路，而不是只測到一半。

    `ledger` 預設用 `event_ledger.EventLedger()`（正本）。測試要傳沙箱的。
    """
    p = plan(rows, session=session, checkpoints=checkpoints)
    if not p.get("can"):
        return dict(p, ok=False)

    ts = at if at is not None else time.time()
    incident = _iid(session, ts, p["back_to"])

    el = _ledger(ledger)
    written: list[str] = []

    # 一，事故本身。先寫這一筆，因為後面兩筆都要掛在它底下 ——
    # 一個沒有事故的 CLEAN_FORK 查不出當初為什麼要 fork。
    written.append(_emit(
        el, ts, "INCIDENT_OPEN", session, incident,
        action="rescue", subject=f"第 {p['back_to']} 輪",
        result=(reason or p["why"])[:120],
        meta={"back_to": p["back_to"], "source": p["source"],
              "turns_excluded": p["turns_excluded"],
              "divergence": {k: p["divergence"].get(k) for k in
                             ("earliest_suspicious", "earliest_confirmed",
                              "first_consequential")}}))

    # 二，動手之前先存一個點。**救援本身也可能出錯。**
    # 沒有這一筆的話，一次救錯的救援就沒有回頭路了。
    cp = None
    if not dry_run:
        import checkpoint as CP
        r = CP.create(session=session, n=p["last_n"], reason="BEFORE_RISKY",
                      goal=goal, unknowns=list(unknowns or []),
                      decisions=[f"要從第 {p['back_to']} 輪 fork，事故 {incident}"],
                      at=ts)
        cp = r.get("checkpoint") if r.get("ok") else None
    written.append(_emit(
        el, ts, "CHECKPOINT", session, incident,
        action="before_rescue", subject=f"第 {p['last_n']} 輪",
        result=(cp or {}).get("id", "dry-run 沒有真的存"),
        meta={"reason": "BEFORE_RISKY", "dry_run": dry_run}))

    # 三，真的開線。
    fn = fork_fn or _default_fork
    info = fn(session, p["back_to"], dry_run)
    if info.get("error"):
        return {"ok": False, "why": f"fork 失敗：{info['error']}",
                "incident": incident, "plan": p, "events": written}

    written.append(_emit(
        el, ts, "CLEAN_FORK", session, incident,
        action="fork", subject=f"第 {p['back_to']} 輪",
        object=info.get("new_session_id", ""),
        result=("dry-run" if dry_run else "建立了新 session"),
        meta={"kept": info.get("kept"), "dropped": info.get("dropped"),
              "quarantined": p["quarantined"], "dry_run": dry_run,
              "at_line": info.get("at_line")}))

    return {
        "ok": True,
        "incident": incident,
        "plan": p,
        "fork": info,
        "checkpoint": cp,
        "events": written,
        "dry_run": dry_run,
        # dropped 是 forkline 數出來的真實數字，不是這裡算的。
        # 自己算一次等於發明第二個真相。
        "excluded_nodes": info.get("dropped"),
        "resume": info.get("resume", ""),
        "receipt": (f"事故 {incident}：從第 {p['back_to']} 輪 fork，"
                    f"排除第 {p['back_to']} 到 {p['last_n']} 輪，"
                    f"{info.get('dropped', '?')} 個節點沒有帶過去。"
                    f"憑據 {p['source']}"),
    }


def history(ledger=None, session: str | None = None) -> dict:
    """查過去救過幾次，每一次回到哪裡。

    這是「全程留在帳本裡可回查」的可查核形式：不看這支的回傳值，
    直接從 Event Ledger 把三筆事件撈回來重組。
    """
    el = _ledger(ledger)
    try:
        recs = el.read_all()
    except Exception:                                        # noqa: BLE001
        return {"total": 0, "incidents": [], "why": "帳本讀不到"}

    by: dict = {}
    for rec in recs:
        n = rec.get("norm") or {}
        if n.get("type") not in EVENT_TYPES:
            continue
        meta = n.get("metadata") or {}
        iid = meta.get("incident") or ""
        if not iid:
            continue
        if session is not None and n.get("session_id") != session:
            continue
        slot = by.setdefault(iid, {"incident": iid, "session": n.get("session_id"),
                                   "steps": []})
        slot["steps"].append({"type": n["type"], "subject": n.get("subject"),
                              "result": n.get("result"), "meta": meta})

    out = []
    for iid, v in by.items():
        types = {s["type"] for s in v["steps"]}
        v["complete"] = set(EVENT_TYPES) <= types
        # 一次沒走完的救援要看得見。停在 INCIDENT_OPEN 的跟沒開始的
        # 在畫面上必須有差別，不然人會以為它沒做，然後再做一次。
        v["stopped_at"] = ("" if v["complete"] else
                           "、".join(t for t in EVENT_TYPES if t not in types))
        out.append(v)
    out.sort(key=lambda x: x["incident"])
    return {"total": len(out), "incidents": out,
            "complete": sum(1 for x in out if x["complete"])}


# ---------------------------------------------------------------------------
# 底下是接線，沒有判斷
# ---------------------------------------------------------------------------

def _ledger(given):
    if given is not None:
        return given
    import event_ledger as EL
    return EL.EventLedger()


def _default_fork(session: str, n: int, dry_run: bool) -> dict:
    # 2026-09-18 從 `desktop_api` 改接 `forkline`。行為一樣（那支就是
    # 從 `desktop_api` 搬過去的),差別在 rescue 不再為了一個 fork
    # 把整個畫面層(四千行、幾十個 import)拖進來。
    import forkline as FK
    return FK.fork_at(session, n, dry_run=dry_run)


def _emit(el, ts: float, etype: str, session: str, incident: str, *,
          action: str = "", subject: str = "", object: str = "",
          result: str = "", meta: dict | None = None) -> str:
    """寫一筆 Recovery 事件。raw 與 normalized 都給，回頭路不能斷。"""
    import event_ledger as EL
    m = dict(meta or {})
    m["incident"] = incident                 # 三筆靠這個串起來
    raw = EL.RawEvent(provider="forseti", provider_event_type="rescue",
                      timestamp=ts,
                      payload={"event": etype, "incident": incident,
                               "session": session, "action": action,
                               "subject": subject, "object": object,
                               "result": result, "metadata": m})
    norm = EL.NormalizedEvent(
        raw_event_id=raw.id, type=etype, session_id=session,
        action=action, subject=subject, object=object, result=result,
        provenance="OBSERVED", metadata=m)
    el.append(raw, norm)
    return raw.id
