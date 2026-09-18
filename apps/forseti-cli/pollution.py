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
import sys
import time
from pathlib import Path

# 三支指令列判準只有一份,在 `cliargs.py`。那個檔的 docstring 記著
# 為什麼它存在（另外五個檔各有一份,而 `_arg` 有四種寫法）,以及
# 為什麼那五支沒有一起搬。
#
# 這裡跟 `forseti._sibling()` 同一個防守:從別的 cwd 進來的時候
# 這個目錄不一定在 sys.path 上,而 `import pollution` 成功不代表
# 它底下的 `import cliargs` 也成功 —— 兩個 import 走的是同一條路徑
# 清單,所以失敗的那一次會是 ImportError 而不是靜默拿到別的東西。
try:
    from cliargs import arg as _arg
    from cliargs import flag_without_value as _flag_without_value
    from cliargs import unknown_flags as _unknown_flags
except ImportError:  # pragma: no cover  只有換 cwd 才走得到
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cliargs import arg as _arg
    from cliargs import flag_without_value as _flag_without_value
    from cliargs import unknown_flags as _unknown_flags

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


def has_guard(r: dict) -> bool:
    """這一筆有沒有東西攔著它。**「有守門」的唯一定義,只寫在這裡。**

    §40.2 認的是 preventive_rule 或 regression_probe,兩個有一個就算。

    ## 為什麼一定要唯一

    2026-09-18 這一支被抽出來,起因是 `guard_split()` 把同一個判斷式
    照抄了兩次,於是 `r.get("regression_probe")` 在這個檔裡出現三次 ——
    而 `tools/literal-restate-check.py` 的條件 2 是「全 repo 出現
    超過一次就當成真的鍵名」(那一支的第 1212 行)。

    所以那三次**讓打錯鍵名的偵測器失效了**:把其中一個打成
    `regression_prope` 本來會被抓,重複之後就被當成真的鍵名放過。
    `tests/test_literal_restate.py` 的反向驗證當場變成 0 命中。

    判斷式重複不只是難維護,它會關掉一個偵測器。這是實測到的,
    不是風格意見。

    ## 為什麼沒有底線(2026-09-18 第二次)

    這一支原本叫 `_has_guard`,而 `desktop_api.pollution_panel()`
    第 2041 行當時自己另外抄了一份(還多了 `.strip()`,所以兩份
    語意其實不完全一樣)。底線名稱會讓下一個人覺得「那是私有的,
    我自己再寫一份」—— **而那正是這一支存在要杜絕的機制。**

    現在它有跨模組使用者,所以名字不帶底線。
    """
    return bool(r.get("preventive_rule") or r.get("regression_probe"))


def summary(path: Path | None = None) -> dict:
    rows = records(path)
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r.get("status", "OPEN")] = counts.get(r.get("status", "OPEN"), 0) + 1
    no_radius = [r["id"] for r in rows if r.get("propagation_radius") is None]
    guarded = [r["id"] for r in rows if has_guard(r)]
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


def guard_split(path: Path | None = None) -> dict:
    """還沒收乾淨的那幾筆裡,有守門的與只靠人記得的各幾筆。

    ## 為什麼這一支不是 `summary()['guarded']`

    **分母不一樣。** `summary()` 的 `guarded` 是對 `records()` 算的,
    分母是全部登記過的筆數；而交接檔「已經被推翻的」那一節
    講的是 `open_records()`(RESOLVED 以外)。

    2026-09-18 這一刻 RESOLVED 是 0,所以兩個分母剛好相等 ——
    **那是巧合,不是設計。** 一旦有一筆推到 RESOLVED,
    `summary()['guarded']` 就會把它算進來,而那一節的 21 筆裡沒有它。
    拿那個數字去配這一節的分母,兩個數字就會在同一頁上打架,
    而這個專案已經為「兩邊回答的不是同一個問題」付過代價
    (`NEXT.md` 的產出那一節就是為此分成兩半)。

    所以這一支自己對 open 組算,並且把分母寫在回傳值裡。

    ## 為什麼要分這兩堆

    §40.2 要的是偵測器,不是一次查核。一筆污染只要沒有
    `preventive_rule` 也沒有 `regression_probe`,那個機制下一次
    還是會犯 —— 現在唯一擋著它的是有人記得。

    `open` 那個總數看不出這件事:19 筆有守門跟 2 筆只靠人記得
    在那個數字裡長得一模一樣,而**後面那 2 筆才是風險所在**。

    `unguarded_ids` 照登記順序,不排序 —— 順序本身是資訊
    (先登記的那一筆卡得比較久)。
    """
    rows = open_records(path)
    guarded = [r["id"] for r in rows if has_guard(r)]
    unguarded = [r["id"] for r in rows if not has_guard(r)]
    return {
        "open": len(rows),
        "guarded": len(guarded),
        "unguarded": len(unguarded),
        "unguarded_ids": unguarded,
        "denominator": "open_records()（RESOLVED 以外）",
        "basis": ("有 preventive_rule 或 regression_probe 的算有守門。"
                  "其餘那些現在只靠人記得"),
        # **`basis` 一句話講完兩堆，而畫面是兩行各講一堆。**
        # 直接拿 `basis` 去當第一行的說明，它的後半（「其餘那些現在
        # 只靠人記得」）會跟第二行整句重複 —— 實測畫面上長成
        # 「⋯其餘那些現在只靠人記得：19 筆⋯／剩下 2 筆現在只靠人記得⋯」。
        # 所以這裡拆成兩句，各對應畫面的一行。`basis` 不動，
        # 它是回答「憑什麼這樣分」的那一句，不是畫面文案。
        "guarded_note": "有偵測器或預防規則攔著的筆數",
        "unguarded_note": "現在只靠人記得",
        # caveat 分開一欄，因為畫面上那幾個 id 要接在 note 後面，
        # caveat 要接在 id 後面 —— 併成一句的話，排版會變成
        # 「⋯只靠人記得。重驗過不等於機制被擋住了：pol-xxx」，
        # 句號後面接冒號，斷句是壞的。**排版歸畫面，句子歸這裡。**
        "unguarded_caveat": "重驗過不等於機制被擋住了",
        "source": "v5.0 §40.2",
    }


# ── CLI ──────────────────────────────────────────────────────────────
#
# 2026-09-18 自動接續補的。**缺的不是資料也不是判準,是入口。**
# 這個模組的 `record()` / `advance()` / `summary()` 在 09-16 就寫好了,
# 桌面端（`desktop_api.pollution_panel()`）與交接契約（`contract.py`）
# 都在讀它,而**登一筆進去只能寫 `python3 -c "import pollution; ..."`**
# —— `NEXT.md` 自己印的那一行「自己查」就是那個寫法,
# `tools/seed_pollution.py` 也是為此存在的一次性腳本。
#
# §40 要的是「每一次推翻都留下機制」,而一個要手寫 import 的登記方式
# 會讓人在趕的時候跳過去。這跟 `evidence.py` 2026-09-18 那一輪
# 「實體與儲存在了,磁碟上仍然 0 筆,因為人沒有地方登」是同一個形狀。

SUBCOMMANDS: tuple[str, ...] = ("list", "show", "template",
                                "register", "advance")

KNOWN_FLAGS: tuple[str, ...] = (
    "--path", "--from", "--id", "--to", "--verifier",
    "--preventive-rule", "--regression-probe", "--note",
)


def _kwargs_of(fn) -> tuple[str, ...]:
    """某一支收哪幾個關鍵字。**去問它,不抄一份。**

    抄一份的症狀跟 `MEMBER_SLOTS` docstring 寫的那種一樣:
    `record()` 哪天多一個欄位,這邊不會跟著動,而畫面上看起來
    只是「不認得的欄位」一句拒絕,沒有人會發現兩邊已經不一致。

    `path` 與 `at` 不在裡面:那兩個是呼叫端的事（寫到哪、什麼時候),
    不是這一筆記錄的內容。
    """
    import inspect  # noqa: PLC0415  只有 CLI 這一段用得到
    return tuple(p for p in inspect.signature(fn).parameters
                 if p not in ("path", "at"))


def template() -> dict:
    """空白模板。尖括號那幾格一定要自己填。

    `propagation_radius` 預設 None 配一句 `radius_basis`,
    因為 `record()` 兩個都空的時候會退回 —— 規格沒有定義這個欄位的
    單位,所以這裡不替它編一個,但也不准留一個沒有說明的空值。
    """
    return {
        "original_claim": "<錯的那句話，逐字抄，不要改寫成比較好看的版本>",
        "corrected_claim": "<實際是什麼>",
        "failure_mechanism": "<為什麼會錯。不是錯在哪，是什麼機制讓它錯的>",
        "source_events": ["<查得回去的出處，檔名加行號或事件 id>"],
        "verifier": "<誰查出來的>",
        "affected_metrics": [],
        "affected_decisions": [],
        "propagation_radius": None,
        "radius_basis": "<沒有給 propagation_radius 就要寫為什麼算不出來>",
        "status": "OPEN",
        "preventive_rule": "",
        "regression_probe": "",
    }


def unfilled(kw: dict) -> list[str]:
    """哪幾格還是模板給的那個字串。回空清單表示都填過了。

    ## 這一支是被自己的量測逼出來的（2026-09-18）

    `template` 的 stderr 印著「尖括號那幾格一定要自己填,原樣送回去
    會被退」。**實測原樣送回去沒有被退** —— `pollution register
    --from <原封不動的模板>` exit=0,登進去一筆 `pol-a01ab492fd`,
    五個欄位全是尖括號,而 `list` 裡它跟填對的那幾筆長得一模一樣。

    `record()` 的四條必填擋的是「空的」,而佔位符**不是空的**。
    它是看起來有內容的空,所以四條全部放行。那句警告當時是假的:
    照抄 `evidence.py` 的說明,而那一支有 `check_fillable()`,
    這一支沒有。**寫得出警告不等於有人在守。**

    比對的對象是 `template()` 自己,不抄一份佔位字串到這裡 ——
    模板哪天改一個字,抄的那一份不會跟著動,而症狀是「守門說填過了、
    畫面上還是尖括號」,沒有人會發現。

    只認「值跟模板一模一樣」,不認「裡面有尖括號」:真的要登一句
    帶尖括號的原話（例如引用一段 HTML）是合法的,判它沒填就錯了。
    """
    t = template()
    out = []
    for k, placeholder in t.items():
        if k not in kw:
            continue
        if isinstance(placeholder, str) and placeholder.startswith("<"):
            if kw[k] == placeholder:
                out.append(k)
        elif isinstance(placeholder, list) and placeholder:
            # `source_events` 的模板是一個單元素清單。整串一樣才算沒填,
            # 填了一個真的出處再留著那個佔位符是兩件事（後者留給人自己看）。
            if kw[k] == placeholder:
                out.append(k)
    return out


def _one_line(r: dict) -> str:
    mark = "守" if has_guard(r) else "人"
    oc = (r.get("original_claim") or "").replace("\n", " ")
    return f"  {mark}　{r['id']}　{r.get('status', ''):<10}　{oc[:42]}"


def _print_row(r: dict) -> None:
    print()
    print(f"  {r['id']}　{r.get('status', '')}")
    print()
    print(f"  當初那句話　　{r.get('original_claim', '')}")
    print(f"  實際是　　　　{r.get('corrected_claim', '')}")
    print(f"  機制　　　　　{r.get('failure_mechanism', '')}")
    print(f"  出處　　　　　{'、'.join(r.get('source_events') or [])}")
    print(f"  誰查的　　　　{r.get('verifier', '')}")
    rad = r.get("propagation_radius")
    print(f"  傳播半徑　　　{rad if rad is not None else '沒量到'}"
          f"{'　' + r['radius_basis'] if not rad and r.get('radius_basis') else ''}")
    # 鍵名從 `OPTIONAL` 拿,不在這裡寫字面量。
    # 寫字面量的後果不是難維護:`tools/literal-restate-check.py` 的
    # 條件 2 是「全 repo 出現超過一次就當成真的鍵名」,所以在這裡多寫
    # 一次 `"preventive_rule"` 會讓打錯成 `preventive_rulle` 的那一次
    # 被當成真鍵名放過。`test_pollution_guard_split.py::Test唯一定義`
    # 在 2026-09-18 這一輪當場抓到這件事 —— 第一版這兩行就是字面量。
    #
    # 標籤跟 `OPTIONAL` 的順序綁在一起,所以那個 tuple 的順序改了
    # 這裡要跟著改。守它的是下面那條 assert 不是註解。
    labels = ("預防規則", "回歸探針")
    assert len(labels) == len(OPTIONAL), "標籤數跟 OPTIONAL 對不上"
    for key, label in zip(OPTIONAL, labels):
        print(f"  {label}　　　{r.get(key) or '（沒有）'}")
    if not has_guard(r):
        print()
        print("  **現在只靠人記得。** §40.2 要的是偵測器，不是一次查核 ——")
        print("  沒有 preventive_rule 也沒有 regression_probe 的那幾筆，")
        print("  下一次同一個機制還是會犯。")
    for h in r.get("history") or []:
        print(f"    {h.get('from', '')} → {h.get('status', '')}"
              f"　{h.get('verifier', '')}　{h.get('note', '')}")
    print()


def main(argv: list) -> int:
    """`forseti pollution <list|show|template|register|advance>`

    v5.0 §40 污染登記簿。`register` 收的是一份 JSON 檔不是一串旗標,
    理由同 `forseti evidence register`:這一份的每一欄缺席都有後果
    （沒有 failure_mechanism 會被退、沒有 source_events 會被退),
    用旗標填的話人會為了讓指令跑得動而亂填,而那正是這個登記簿要擋的事。

    `advance` 相反,收旗標,因為一次狀態轉換只有四個值要帶,
    而且 `advance()` 自己會擋住不合法的轉換與缺的附帶條件。
    """
    # 第一個參數以 `-` 開頭的時候它是旗標不是子指令。少了這一行,
    # `forseti pollution --path X` 會把 `--path` 放進 `sub`,於是 `rest`
    # 只剩下 X,`_arg(rest, "--path")` 找不到,結果是**讀正本而不是讀 X**。
    # 同一個形狀在 `evidence.py` 與 `metrics.py` 先撞到過,兩支的註解
    # 都寫著「錯的答案跟對的答案長得一模一樣」。
    _flag_first = bool(argv) and str(argv[0]).startswith("-")
    sub = argv[0] if (argv and not _flag_first) else "list"
    rest = list(argv) if _flag_first else list(argv[1:])

    # 旗標寫了可是後面沒有值 -> 明著退回,不准掉回預設。
    # `--path` 掉回正本、`--id` 會回「沒有這一筆」（那個人以為資料不存在,
    # 而真正的事是指令打錯）、`--to` 會變成「status 只能是 ...」
    # （怪值不合法,不是怪值漏了）。
    for _flag, _why in (
            ("--path", "後面要接一份登記簿的路徑。沒接的話會讀正本，"
                       "而那份報告看起來跟你指定的檔一模一樣。"),
            ("--from", "後面要接一份 JSON 的路徑。"),
            ("--id", "後面要接一個 pol-xxxxxxxxxx。"),
            ("--to", f"後面要接一個狀態：{'、'.join(STATUSES)}。"),
            ("--verifier", "後面要接誰查的。沒接的話下一個旗標會被當成人名，"
                           "而 REVERIFIED 這一關要的就是指得回人。"),
            ("--preventive-rule", "後面要接規則。沒接的話下一個旗標名會被"
                                  "當成規則寫進去，而那一筆看起來就有守門了。"),
            ("--regression-probe", "後面要接探針。沒接的話同上。"),
            ("--note", "後面要接一句話。")):
        if _flag_without_value(rest, _flag):
            print()
            print(f"  `{_flag}` {_why}")
            print("  所以這裡退回，不猜。")
            print()
            return 2

    # 旗標名打錯字 -> 明著退回。不擋的話那個旗標會被當成沒寫:
    # `--pathh X` 讀的是正本、`--verifierr 我` 會讓 REVERIFIED 那一關
    # 回「要有 verifier」,而打字的人明明寫了。
    _unknown = _unknown_flags(rest, KNOWN_FLAGS)
    if _unknown:
        print()
        print(f"  不認得這個旗標：{'、'.join(_unknown)}")
        print(f"  有的是：{'、'.join(KNOWN_FLAGS)}")
        print("  打錯字不會報錯，那個旗標會被當成沒寫 —— `--path` 會掉回")
        print("  正本，`--verifier` 會讓那一關回「你沒給」。所以這裡退回。")
        print()
        return 2

    if sub not in SUBCOMMANDS:
        # 打錯子指令要看得出來。掉進 list 的話會回 0 而且印一份看起來
        # 正常的報告 —— `forseti pollution registr --from x` 會印出
        # 登記簿然後結束,而那個人以為自己登記過了。
        print()
        print(f"  不認得這個子指令：{sub}")
        print(f"  有的是：{'、'.join(SUBCOMMANDS)}")
        print()
        return 2

    raw = _arg(rest, "--path")
    p = Path(raw).expanduser() if raw else None

    if sub == "template":
        print(json.dumps(template(), ensure_ascii=False, indent=2))
        print()
        print("# 尖括號那幾格一定要自己填，原樣送回去會被退。", file=sys.stderr)
        print(f"# status 只收：{'、'.join(STATUSES)}", file=sys.stderr)
        print("# failure_mechanism 是這一份存在的理由（§40 開頭那句：",
              file=sys.stderr)
        print("# preserve the mechanism, not only the corrected number）。",
              file=sys.stderr)
        return 0

    if sub == "register":
        src = _arg(rest, "--from")
        if not src:
            print("要一份 JSON：`forseti pollution register --from <檔案>`。"
                  "空白模板：`forseti pollution template`")
            return 2
        try:
            kw = json.loads(Path(src).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"讀不到或解不開：{exc}")
            return 2
        if not isinstance(kw, dict):
            print(f"要一個 JSON 物件，收到 {type(kw).__name__}")
            return 2
        extra = sorted(set(kw) - set(_kwargs_of(record)))
        if extra:
            print()
            print(f"  不認得的欄位：{'、'.join(extra)}")
            print("  沒有默默丟掉，是因為丟掉的話填錯欄位名跟沒填長得一樣 ——")
            print("  少了 failure_mechanism 的那一筆會被 record() 退，")
            print("  而 failure_mechanizm 打錯字的那一筆會被丟掉之後，")
            print("  退回的理由變成「你沒寫機制」，指的不是真正發生的事。")
            print()
            return 1
        blank = unfilled(kw)
        if blank:
            print()
            print(f"  這幾格還是模板給的那句話：{'、'.join(blank)}")
            print("  原樣送回去不會被 record() 擋 —— 它擋的是空的，")
            print("  而佔位符不是空的，是看起來有內容的空。登進去之後")
            print("  在 `list` 裡跟填對的那幾筆長得一模一樣。")
            print()
            return 1
        res = record(path=p, **kw)
        if not res["ok"]:
            print()
            print(f"  這一筆登記不了：{res['why']}")
            print()
            return 1
        _print_row({**res["record"], "history": []})
        return 0

    if sub == "advance":
        pid = _arg(rest, "--id")
        to = _arg(rest, "--to")
        if not pid or not to:
            print("要 id 與目標狀態："
                  "`forseti pollution advance --id pol-xxxxxxxxxx --to RESOLVED`")
            return 2
        res = advance(pid, to, path=p,
                      verifier=_arg(rest, "--verifier") or "",
                      preventive_rule=_arg(rest, "--preventive-rule") or "",
                      regression_probe=_arg(rest, "--regression-probe") or "",
                      note=_arg(rest, "--note") or "")
        if not res["ok"]:
            print()
            print(f"  轉不過去：{res['why']}")
            print()
            return 1
        row = get(pid, path=p)
        _print_row(row or {})
        return 0

    if sub == "show":
        pid = _arg(rest, "--id") or (rest[0] if rest and
                                     not str(rest[0]).startswith("-") else None)
        if not pid:
            print("要一個 id：`forseti pollution show --id pol-xxxxxxxxxx`")
            return 2
        row = get(pid, path=p)
        if row is None:
            print(f"  {pid} 不在登記簿上")
            return 1
        _print_row(row)
        return 0

    rows = records(p)
    s = summary(p)
    g = guard_split(p)
    print()
    print(f"  §40 污染登記簿　{s['total']} 筆，還沒收乾淨 {s['open']} 筆")
    if not rows:
        print()
        print("  一筆都還沒有人登。實體與儲存在了，缺的是有人去登 ——")
        print("  `forseti pollution template` 產模板，填完")
        print("  `forseti pollution register --from <檔案>`。")
        print()
        print("  **這一支不自動登記。** 拿一句看起來像錯的話配一個猜出來的")
        print("  機制就是 §8.3 的填空，而那正是這個登記簿要擋的事。")
        print()
        return 0
    print(f"  其中 {g['guarded']} 筆有偵測器或預防規則攔著，"
          f"{g['unguarded']} 筆現在只靠人記得")
    print(f"  分母是 {g['denominator']}")
    print()
    print("  左邊那一格：守＝有東西攔它，人＝只靠人記得")
    print()
    for r in rows:
        print(_one_line(r))
    if g["unguarded_ids"]:
        print()
        print(f"  只靠人記得的：{'、'.join(g['unguarded_ids'])}")
        print(f"  {g['unguarded_caveat']}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
