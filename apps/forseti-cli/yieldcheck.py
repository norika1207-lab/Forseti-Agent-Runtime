#!/usr/bin/env python3
"""過早交還發言權。§31

owner 2026-09-14 那一整晚的根因，而 Forseti 全程看著沒攔下來。

`src/yield.js` 的檔頭寫著這個形狀是她指出來的，在自我審計表上缺席了
十七輪，而她原話裡出現最多次的一句是「繼續」。那支寫好了，
到 2026-09-15 為止一行都沒接進任何地方。

## 為什麼 betrayal 抓不到

`betrayal` 抓的是「說了做了，而紀錄裡沒有那個動作」。
過早交還發言權的典型樣子相反：

    宣告全部兌現了，這一輪也真的有產出，然後停下來 —— 而工作還沒完。

每一筆帳都結清了，只是提早收工。**從宣告的角度看，那是滿分。**

## 判準照抄 src/yield.js

不自己改措辭也不自己加條件。兩邊分歧的那天沒有人會發現，
因為兩邊各自看起來都對。

零依賴（ADR-009）。
"""

from __future__ import annotations

import re

VERDICTS = ("PREMATURE", "LEGITIMATE", "AWAITING", "BLOCKED", "CANNOT_DETERMINE")

VERDICT_MEANING = {
    "PREMATURE": "還有沒做完的，沒有在等你，而且這一輪有產出",
    "LEGITIMATE": "完成的條件都達成了",
    "AWAITING": "在等你回應。問了問題就停下來是協作，不是提早收工",
    "BLOCKED": "這一輪零產出，那是卡住不是提早收工。兩者的處方相反",
    "CANNOT_DETERMINE": "拿不到完成的定義。不知道還剩什麼，不等於沒剩",
}

# 這一輪是不是在問你。問了就停是協作，不是提早收工。
#
# 刻意保守：只認明確的疑問句尾與請求。分不出來的一律當成沒在等 ——
# 把「提早收工」誤判成「在等你」，等於幫它找藉口。
_ASKING = re.compile(
    r"(?:要不要|好嗎|可以嗎|你說|你決定|等你|你選|哪一個|嗎？\s*$|"
    r"跟我說|告訴我|確認一下|你要我)")


def judge(*, done_when=None, unmet=None, awaiting=False,
          produced_this_turn=0) -> dict:
    """照 src/yield.js 的 judgeYield。

    `done_when` 是完成的定義（帳本裡的 definition_of_done）。
    拿不到就回 CANNOT_DETERMINE —— **不知道還剩什麼，不等於沒剩。**
    """
    if done_when is None:
        return {"verdict": "CANNOT_DETERMINE",
                "reason": "拿不到完成的定義。不知道還剩什麼，不等於沒剩"}
    if awaiting:
        return {"verdict": "AWAITING",
                "reason": "在等你回應。問了問題就停下來是協作，不是提早收工"}

    outstanding = list(unmet or [])

    if produced_this_turn == 0:
        return {"verdict": "BLOCKED", "outstanding": outstanding,
                "reason": "這一輪什麼都沒產出。那是卡住，不是提早收工，"
                          "而兩者的處方相反"}
    if not outstanding:
        return {"verdict": "LEGITIMATE", "outstanding": []}

    return {
        "verdict": "PREMATURE",
        "outstanding": outstanding,
        # 措辭刻意不是命令。這個偵測器不擋任何東西，它只是把
        # 「還有這些沒做」講出來 —— 因為交還發言權的那一刻，
        # 正是當事人最不會去看那張清單的時候。
        "reason": f"{len(outstanding)} 項還沒做完，沒有在等你，"
                  f"而這一輪確實有產出。在這裡把話還給你，"
                  f"等於要你自己記得還有什麼沒做",
    }


def looks_awaiting(text: str) -> bool:
    """這一輪結尾是不是在問人。"""
    tail = " ".join((text or "").split())[-120:]
    return bool(_ASKING.search(tail))


def open_next_actions() -> list[str]:
    """帳本上「已授權、可以自己做的下一步」。

    【2026-09-15 第一版餵錯，在進畫面前抓到】
    我先拿整個任務的 `definition_of_done` 當判準，結果 313 輪裡
    219 輪被判 PREMATURE —— 因為那三條完成定義在每一輪都還沒達成，
    所以每一輪都有「未達成項」。那量的是任務沒做完，
    不是這一輪提早收工。

    正確的判準是 `next_required_action`:帳本上有一句明確的、
    已授權的下一步，而我把發言權交回去了。F06 §3 講的就是這件事 ——
    有已授權的確定性下一步就該自己走。

    這跟昨天 `starvation` 那個錯是同一形狀:沒讀清楚欄位語意就餵。
    """
    import sqlite3
    from pathlib import Path as _P

    d = _P.home() / ".forseti" / "ledgers"
    dbs = sorted(d.glob("*.db")) if d.is_dir() else []
    if not dbs:
        return []
    try:
        c = sqlite3.connect(dbs[0])
        rows = c.execute(
            "select next_required_action from tasks"
            " where current_state not in ('DONE','CANCELLED')"
            "   and next_required_action is not null"
            "   and next_required_action != ''").fetchall()
    except Exception:                               # noqa: BLE001
        return []
    # VERIFIED_COMPLETE 的任務雖然還掛在帳上，它的下一步不是「現在該做的」。
    return [r[0] for r in rows if r[0]]


def scan(strands: list, done_when=None, unmet=None) -> list[dict]:
    """掃一整條線，找提早收工的那幾輪。

    `done_when` 與 `unmet` 從帳本來。拿不到的話每一輪都是
    CANNOT_DETERMINE，而那是誠實的結果，不是失敗。
    """
    out = []
    for s in strands:
        if getattr(s, "growing", False):
            continue
        text = (getattr(s, "ai_text", "") or "").strip()
        dots = getattr(s, "dots", [])
        r = judge(done_when=done_when, unmet=unmet,
                  awaiting=looks_awaiting(text),
                  produced_this_turn=len(dots) + (1 if text else 0))
        if r["verdict"] in ("PREMATURE", "BLOCKED"):
            r = dict(r)
            r["n"] = getattr(s, "n", 0)
            r["meaning"] = VERDICT_MEANING[r["verdict"]]
            out.append(r)
    return out


def confirmed(strands: list) -> list[dict]:
    """確認的提早收工：判為 PREMATURE，而且她下一句真的在催。§31

    【為什麼要兩個訊號】
    單看 PREMATURE 在這個 session 上是 219 輪 —— 因為帳本那兩條
    下一步從頭到尾掛著，所以每一輪都算「有事沒做」。那是噪音。

    加上「她下一句真的開口催了」之後落到 12 輪。**那 12 輪是確認的，
    不是推測。**

    這是白點那次學到的同一條:一個訊號只能當觸發器，要證據才算數。
    """
    import owner as O

    nxt = open_next_actions()
    prem = {h["n"] for h in scan(strands, done_when=nxt, unmet=nxt)
            if h["verdict"] == "PREMATURE"}
    out = []
    for i, s in enumerate(strands[:-1]):
        n = getattr(s, "n", 0)
        if n not in prem:
            continue
        nx = strands[i + 1]
        nudge = getattr(nx, "owner_text", "") or ""
        if not O.is_nudge(nudge):
            continue
        out.append({
            "n": n,
            "nudge": " ".join(nudge.split())[:40],
            "nudge_n": getattr(nx, "n", 0),
            "outstanding": nxt[:2],
        })
    return out
