#!/usr/bin/env python3
"""污染登記簿。v5.0 §40。

規格原文那一句是整支的立論（§40 開頭）:

    Forseti should preserve the mechanism of a misleading conclusion,
    not only the corrected number. Numbers change; failure mechanisms recur.

所以這裡存的重點不是「正確答案是多少」，是「當初為什麼會錯」。
數字改掉就沒事了，機制不改掉會再犯一次。

────────────────────────────────────────────────────

## 為什麼這一支沒有「自動掃描」

這個 repo 的更正全部寫在 `.forseti/AUTO_CONTINUE_LOG.md` 與
`.forseti/ROADMAP.md` 的散文裡（`contract.py:844` 的 failed_attempts
就是這樣標的:「那是散文不是可查詢的狀態」）。

看起來最省事的做法是寫一支掃描器去抓「先前……不準」這類句型。
不做，理由是 BLOCKERS 的 B-05:任何單獨靠文字判斷「這句話有沒有在
宣稱某件事」的做法都擋住。抓到的會是符合句型的句子，不是真的污染，
而漏掉的那些會長得跟「沒有污染」一模一樣。

登錄一律是明確呼叫 `record()`,每一筆自己帶得出 `source_events`。

## propagation_radius 算不出來就是 None,不是 0

§40.1 列了這個欄位,但規格沒有定義它的單位 ——
是幾個下游結論、幾個檔案、還是幾輪。沒有定義就沒有算法,
照 §8.3 的禁止捷徑,這裡不編一個。

沒給就 None,並且要求呼叫端講出 `radius_basis`(為什麼算不出來)。
「0」讀起來是「量過了,沒有傳播」,跟「沒量」是兩件事,
而後者才是實情。這個專案已經為同一件事付過三次代價
(blast 的 live_conflicts、uncovered_d1、blast.detail 的任務依賴)。

## 只增不改

跟事件帳本與粉紅點同一條。狀態轉換是追加一筆,不是改舊的那筆。
一筆寫下去當下就是證據,事後改掉就不是了。

## 狀態不准自己往上跳

§40.2 明寫規則要存「造成它的事故、用來強制的偵測器、可以退役的條件」。
所以:

- REVERIFIED 要有 verifier,不能自己宣告重驗過了
- RESOLVED 要有 preventive_rule 或 regression_probe,
  否則「解決」只是把話講完,機制還在

零依賴,跟這條線上其他模組一樣。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "pollution.jsonl"

#: §40.1 逐字的四個狀態。沒有第五個。
STATUSES = ("OPEN", "PARTIAL", "REVERIFIED", "RESOLVED")

#: 合法轉換。往回走是允許的(重驗之後又發現沒好),
#: 往前跳過中間狀態不允許。
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "OPEN": ("PARTIAL", "REVERIFIED"),
    "PARTIAL": ("REVERIFIED", "OPEN"),
    "REVERIFIED": ("RESOLVED", "PARTIAL", "OPEN"),
    "RESOLVED": ("OPEN",),
}

#: 進這個狀態要附什麼。空 tuple 表示沒有額外要求。
REQUIRES: dict[str, tuple[str, ...]] = {
    "OPEN": (),
    "PARTIAL": (),
    "REVERIFIED": ("verifier",),
    "RESOLVED": ("preventive_rule|regression_probe",),
}

#: §40.1 的欄位,逐字照抄。後面兩個規格標了問號(選填)。
FIELDS = (
    "id", "original_claim", "corrected_claim", "failure_mechanism",
    "source_events", "affected_metrics", "affected_decisions",
    "propagation_radius", "status", "discovered_at", "verifier",
    "preventive_rule", "regression_probe",
)
OPTIONAL = ("preventive_rule", "regression_probe")


def _id(original: str, mechanism: str) -> str:
    h = hashlib.sha256((original + "\x00" + mechanism).encode("utf-8"))
    return "pol-" + h.hexdigest()[:10]


def record(*, original_claim: str, corrected_claim: str,
           failure_mechanism: str, source_events: list[str],
           verifier: str,
           affected_metrics: list[str] | None = None,
           affected_decisions: list[str] | None = None,
           propagation_radius: int | None = None,
           radius_basis: str = "",
           status: str = "OPEN",
           preventive_rule: str = "", regression_probe: str = "",
           at: float | None = None, path: Path | None = None) -> dict:
    """登錄一筆污染。回寫進去的那一筆,或拒絕的理由。

    四個必填一個都不能空:錯的那句、對的那句、為什麼會錯、出處。
    少了「為什麼會錯」這一筆就退化成一次更正,而 §40 存在的理由
    正是更正本身留不住機制。
    """
    oc = (original_claim or "").strip()
    cc = (corrected_claim or "").strip()
    fm = (failure_mechanism or "").strip()
    src = [s for s in (source_events or []) if str(s).strip()]
    vf = (verifier or "").strip()

    if not oc:
        return {"ok": False, "why": "original_claim 是空的。"
                                    "沒有錯的那句話就沒有東西可以登錄"}
    if not cc:
        return {"ok": False, "why": "corrected_claim 是空的。"
                                    "只知道錯不知道對的是什麼,下游沒辦法改"}
    if not fm:
        return {"ok": False,
                "why": "failure_mechanism 是空的。§40 開頭那句"
                       "(preserve the mechanism, not only the corrected number)"
                       "就是在擋這種寫法 —— 只改數字不寫機制,機制會再犯"}
    if not src:
        return {"ok": False,
                "why": "source_events 是空的。一筆查不回出處的污染記錄"
                       "本身就是一個沒有證據的宣稱"}
    if not vf:
        return {"ok": False,
                "why": "verifier 是空的。不知道是誰查出來的,"
                       "這筆的可信度就沒有上限也沒有下限"}
    if status not in STATUSES:
        return {"ok": False, "why": f"status 只能是 {'/'.join(STATUSES)},"
                                    f"收到的是 {status!r}"}

    bad = _missing_for(status, verifier=vf, preventive_rule=preventive_rule,
                       regression_probe=regression_probe)
    if bad:
        return {"ok": False, "why": bad}

    if propagation_radius is None and not radius_basis.strip():
        return {"ok": False,
                "why": "propagation_radius 沒給就要講 radius_basis"
                       "(為什麼算不出來)。規格沒有定義這個欄位的單位,"
                       "所以這裡不替它編一個,但也不准留一個沒有說明的空值"}

    row = {
        "id": _id(oc, fm),
        "original_claim": oc,
        "corrected_claim": cc,
        "failure_mechanism": fm,
        "source_events": src,
        "affected_metrics": list(affected_metrics or []),
        "affected_decisions": list(affected_decisions or []),
        "propagation_radius": propagation_radius,
        "radius_basis": radius_basis.strip(),
        "status": status,
        "discovered_at": at or time.time(),
        "verifier": vf,
        "preventive_rule": (preventive_rule or "").strip(),
        "regression_probe": (regression_probe or "").strip(),
        "kind": "RECORD",
    }
    _append(row, path)
    return {"ok": True, "record": row}


def _missing_for(status: str, *, verifier: str = "",
                 preventive_rule: str = "", regression_probe: str = "") -> str:
    """進某個狀態少了什麼。回空字串表示沒少。"""
    if status == "REVERIFIED" and not (verifier or "").strip():
        return ("REVERIFIED 要有 verifier。"
                "一筆污染不能自己宣告重驗過了 —— 那正是它當初出現的方式")
    if status == "RESOLVED" and not ((preventive_rule or "").strip()
                                     or (regression_probe or "").strip()):
        return ("RESOLVED 要有 preventive_rule 或 regression_probe。"
                "§40.2 明寫規則要存造成它的事故、強制它的偵測器、"
                "以及退役條件。沒有任何一個攔它的東西,"
                "「已解決」講的是這次,不是下次")
    return ""


def _append(row: dict, path: Path | None) -> None:
    p = path or LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def advance(pid: str, to: str, *, verifier: str = "",
            preventive_rule: str = "", regression_probe: str = "",
            note: str = "", at: float | None = None,
            path: Path | None = None) -> dict:
    """狀態轉換。追加一筆,不改原來那一筆。"""
    cur = get(pid, path=path)
    if cur is None:
        return {"ok": False, "why": f"沒有這一筆:{pid}"}
    if to not in STATUSES:
        return {"ok": False, "why": f"status 只能是 {'/'.join(STATUSES)}"}
    frm = cur["status"]
    if to == frm:
        return {"ok": False, "why": f"已經是 {to} 了,不用轉"}
    if to not in TRANSITIONS.get(frm, ()):
        return {"ok": False,
                "why": f"{frm} 不能直接到 {to}。"
                       f"{frm} 允許的下一站是 "
                       f"{'/'.join(TRANSITIONS.get(frm, ())) or '（沒有）'}"}
    bad = _missing_for(to, verifier=verifier, preventive_rule=preventive_rule,
                       regression_probe=regression_probe)
    if bad:
        return {"ok": False, "why": bad}

    row = {
        "kind": "STATUS",
        "id": pid,
        "from": frm,
        "status": to,
        "verifier": (verifier or "").strip(),
        "preventive_rule": (preventive_rule or "").strip(),
        "regression_probe": (regression_probe or "").strip(),
        "note": (note or "").strip(),
        "at": at or time.time(),
    }
    _append(row, path)
    return {"ok": True, "change": row, "status": to}


def load(path: Path | None = None) -> list[dict]:
    """原始的每一行,照寫入順序。"""
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


def records(path: Path | None = None) -> list[dict]:
    """把 RECORD 與後續的 STATUS 疊起來,回現在的樣子。

    疊的時候只動 status 與那次轉換帶進來的欄位,
    原始的 original_claim / failure_mechanism 永遠是第一筆寫的那個。
    """
    by: dict[str, dict] = {}
    order: list[str] = []
    for r in load(path):
        pid = r.get("id") or ""
        if not pid:
            continue
        if r.get("kind") == "RECORD":
            if pid not in by:
                order.append(pid)
            by[pid] = dict(r)
            by[pid]["history"] = []
        elif r.get("kind") == "STATUS" and pid in by:
            cur = by[pid]
            cur["status"] = r.get("status") or cur["status"]
            for k in ("verifier", "preventive_rule", "regression_probe"):
                if (r.get(k) or "").strip():
                    cur[k] = r[k].strip()
            cur["history"].append(r)
    return [by[p] for p in order]


def get(pid: str, path: Path | None = None) -> dict | None:
    for r in records(path):
        if r["id"] == pid:
            return r
    return None


def open_records(path: Path | None = None) -> list[dict]:
    """還沒收乾淨的。RESOLVED 以外全算。

    REVERIFIED 也算在內:重驗過不等於機制被擋住了,
    §40.2 要的是偵測器不是一次查核。
    """
    return [r for r in records(path) if r.get("status") != "RESOLVED"]


def invalidated_conclusions(path: Path | None = None) -> list[str]:
    """給 §39.1 交接契約的 Limits 用。

    回的是「這些話已經被推翻了,不要再帶下去」。
    只列還沒 RESOLVED 的 —— RESOLVED 表示已經有東西在攔它,
    帶下去的價值比噪音低。
    """
    out = []
    for r in open_records(path):
        out.append(f"{r['original_claim']}　→　實際是:{r['corrected_claim']}"
                   f"（{r['status']}，機制:{r['failure_mechanism']}）")
    return out


def summary(path: Path | None = None) -> dict:
    rows = records(path)
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r.get("status", "OPEN")] = counts.get(r.get("status", "OPEN"), 0) + 1
    no_radius = [r["id"] for r in rows if r.get("propagation_radius") is None]
    guarded = [r["id"] for r in rows
               if (r.get("preventive_rule") or r.get("regression_probe"))]
    return {
        "total": len(rows),
        "by_status": counts,
        "open": len(open_records(path)),
        # 這兩個數字是誠實條款,不是統計。
        "radius_unknown": len(no_radius),
        "radius_note": ("規格沒有定義 propagation_radius 的單位,"
                        "所以沒量到的是 None 不是 0" if no_radius else ""),
        "guarded": len(guarded),
        "guard_note": ("有偵測器或預防規則攔著的筆數。"
                       "其餘那些現在只靠人記得"),
        "source": "v5.0 §40 PollutionRegistry",
    }
