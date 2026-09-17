#!/usr/bin/env python3
"""建議軌跡。Forseti 建議的那條路，跟實際走的那條路，差多遠。§11

owner 2026-09-15：

    fork 會到新的 session，而是 Forseti 本來建議可能怎麼做會比較好，
    用戶下的指令偏離了，於是越做越歪，
    每個決定都會跟 forseti 的建議做分岔

在這之前線是一直線，因為畫面上只有「實際走的那一條」。
建議那一條從來沒有被存下來 —— `_advice()` 每次 snapshot 即時算完就丟，
帳本裡一筆都沒有。**沒有「它當時建議什麼」，就無從比對有沒有照做，
分岔也就無從算起。**

## 判準:建議自己消失就是被處理了

判「使用者的指令有沒有照建議做」需要讀語意，那是 INFERRED，而且
`FS-DRF-002` 明令 drift 不得只由 semantic similarity 或 one-shot LLM
judgment 決定。

這裡用一個 OBSERVED 的訊號代替:**建議是根據當下狀態算出來的。**
下一輪它不再出現，代表觸發它的條件消失了。一輪一輪持續出現，
代表那個狀況一直都在。

    出現 → 消失      RESOLVED    分岔收回來
    出現 → 一直出現   STANDING    分岔越開

這個判準的邊界要講清楚:它量的是「狀況有沒有解除」，不是
「她有沒有聽我的」。狀況也可能因為別的原因解除。所以輸出一律標
`provenance: OBSERVED_STATE_CHANGE`，不寫成「她採納了建議」。

## 為什麼寬度用持續輪數不用建議則數

三條建議同時站著一輪，跟一條建議站著三輪，嚴重程度不一樣。
後者是同一個問題被放著不管，那才是「越做越歪」。所以寬度吃的是
每條建議各自的持續輪數，取最大的那一條當主導。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "advice_ledger.jsonl"

#: 一條建議站著幾輪之後開始算歪。1 輪還在正常來回的範圍內。
MIN_STANDING = 2

#: 分岔的最大橫向偏移，單位是格。線再歪也要留在畫面裡。
MAX_OFFSET = 6


def advice_id(a: dict) -> str:
    """建議的穩定識別。

    優先用 `key`（`vitals.cards` 給的 spec / turn / … 那種），因為 title
    裡帶著會變的數字（「必讀 26 份只讀完 25 份」讀完一份就變了）。
    用會變的東西當識別，同一個問題會被算成兩條建議，分岔就斷掉。
    """
    k = (a.get("key") or "").strip()
    if k:
        return "adv-" + k
    t = (a.get("title") or a.get("text") or "").strip()
    return "adv-" + hashlib.sha256(t.encode("utf-8")).hexdigest()[:10]


def record(advices: list, *, n: int, session: str = "",
           at: float | None = None,
           path: Path | None = None, dedupe: bool = True) -> list[dict]:
    """把這一輪的建議記下來。append-only。

    Widget 是輪詢的，同一輪會被掃很多次。沒有去重的話帳本會塞滿
    同一筆，而持續輪數是用「出現在幾個不同的 n」算的，重複記不會
    改變結果，但會讓檔案無限長大。
    """
    p = path or LOG
    seen = set()
    if dedupe and p.exists():
        for r in load(p):
            seen.add((r.get("session", ""), r.get("n"), r.get("id")))
    rows = []
    for a in advices or []:
        if dedupe and (session, n, advice_id(a)) in seen:
            continue
        rows.append({
            "at": at or time.time(),
            "n": n,
            # 【2026-09-16 補】輪號是每個 session 各自從 1 數的。
            # 不記 session 的話，兩條不同的線會共用同一組輪號，
            # 分岔就會算到別人的帳上。
            "session": session,
            "id": advice_id(a),
            "title": a.get("title") or a.get("text") or "",
            "severity": a.get("severity") or a.get("tone") or "",
            "say": a.get("say") or "",
        })
    if rows:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def load(path: Path | None = None, *, session: str | None = None) -> list[dict]:
    """讀帳本。給了 session 就只回那一條線的。

    輪號是 session 內部的序號，跨 session 混在一起算會把別人的
    輪數算進自己的分岔。
    """
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


def standing(history: list[dict], *, upto_n: int | None = None) -> dict:
    """每條建議目前站了幾輪。回 {id: {...}}。"""
    seen: dict = {}
    for r in history:
        n = r.get("n")
        if upto_n is not None and n is not None and n > upto_n:
            continue
        i = r.get("id")
        if not i:
            continue
        e = seen.setdefault(i, {"id": i, "title": r.get("title", ""),
                                "severity": r.get("severity", ""),
                                "first_n": n, "last_n": n, "turns": 0,
                                "ns": set()})
        e["last_n"] = n
        if n is not None:
            e["ns"].add(n)
    out = {}
    for i, e in seen.items():
        e["turns"] = len(e["ns"])
        e.pop("ns")
        out[i] = e
    return out


def outcome(history: list[dict], advice_ids_now: set) -> list[dict]:
    """哪些建議還站著、哪些已經不見了。

    不見了只代表狀況解除，**不代表她採納了建議**。
    """
    st = standing(history)
    out = []
    for i, e in st.items():
        gone = i not in advice_ids_now
        out.append(dict(
            e,
            state="RESOLVED" if gone else "STANDING",
            provenance="OBSERVED_STATE_CHANGE",
            note="狀況已解除，不等於她採納了建議" if gone
                 else f"連續出現 {e['turns']} 輪，狀況一直在",
        ))
    out.sort(key=lambda x: (-x["turns"], x["id"]))
    return out


def divergence(history: list[dict], *, max_n: int | None = None) -> list[dict]:
    """逐輪的分岔寬度。這是畫圖直接吃的東西。

    offset 0 代表實際路徑貼著建議路徑；數字越大代表岔得越開。
    """
    if not history:
        return []
    ns = sorted({r.get("n") for r in history if r.get("n") is not None})
    if not ns:
        return []
    hi = max_n if max_n is not None else ns[-1]

    # 每條建議出現在哪幾輪
    by_id: dict = {}
    for r in history:
        n = r.get("n")
        i = r.get("id")
        if n is None or not i:
            continue
        by_id.setdefault(i, {"ns": set(), "title": r.get("title", "")})
        by_id[i]["ns"].add(n)

    out = []
    for n in range(ns[0], hi + 1):
        live = []
        for i, e in by_id.items():
            if n not in e["ns"]:
                continue
            # 這一輪為止，這條建議連續站了幾輪
            run = 0
            k = n
            while k in e["ns"]:
                run += 1
                k -= 1
            live.append({"id": i, "title": e["title"], "run": run})
        if not live:
            out.append({"n": n, "offset": 0, "standing": [], "lead": None})
            continue
        lead = max(live, key=lambda x: x["run"])
        # 站滿 MIN_STANDING 輪才開始往外偏，一輪之內算正常來回。
        off = max(0, lead["run"] - MIN_STANDING + 1)
        out.append({
            "n": n,
            "offset": min(MAX_OFFSET, off),
            "standing": sorted(live, key=lambda x: -x["run"]),
            "lead": lead["title"],
        })
    return out


def summary(history: list[dict], advice_ids_now: set) -> dict:
    d = divergence(history)
    oc = outcome(history, advice_ids_now)
    worst = max((x["offset"] for x in d), default=0)
    now = d[-1]["offset"] if d else 0
    return {
        "has": bool(history),
        "turns_recorded": len({r.get("n") for r in history}),
        "offset_now": now,
        "offset_worst": worst,
        "standing": [o for o in oc if o["state"] == "STANDING"],
        "resolved": [o for o in oc if o["state"] == "RESOLVED"],
        "divergence": d,
        "note": "分岔量的是「建議指出的狀況有沒有解除」，"
                "不是「她有沒有聽建議」。狀況也可能因為別的原因解除。",
    }
