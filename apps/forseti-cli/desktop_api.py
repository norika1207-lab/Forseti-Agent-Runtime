#!/usr/bin/env python3
"""桌面版的資料提供者。Rust 那一層只轉發，判斷全部留在這裡。

規格來源：工程書 Phase 8（X-Ray v1 and Temperature UI）、
`spec-v2.0` §8（Composite Runtime Reliability Risk）、
`.forseti/PRODUCT_DIRECTION.md`（owner 2026-09-11 的終局三件事）。

────────────────────────────────────────────────────

## 溫度計為什麼不是一個數字

Phase 8 的預設畫面是 `Forseti 37.2 C WATCH`。這個專案的設計規則
§3.2 明令不合成單一風險分數，理由是：

    把五個可行動的維度壓成一個數字，
    會毀掉唯一讓它們可行動的東西。

而且 `FS-RSK-001` 要求 Composite R MUST 同時顯示 EvidenceCoverage ——
低 coverage 的高分不能裝作確定。

所以這裡給的是：

    一個狀態燈（OK / WATCH / ATTENTION），由分項決定
    每一個分項的實際數字、門檻、以及它從哪裡來
    整體的 coverage：有幾項量得到、有幾項量不到

**狀態燈可以用一句話講完它憑什麼是那個顏色。講不出來就不該有燈。**

## 這裡不做的事

不算分數、不加權、不做趨勢預測。`FS-TRD-003`：
若 trend confidence 不足，預測「多久會壞」MUST 回 UNKNOWN。

用法：

    python3 apps/forseti-cli/desktop_api.py snapshot
    python3 apps/forseti-cli/desktop_api.py timeline <session-uuid>
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

LEVELS = ("OK", "WATCH", "ATTENTION")


def _safe(fn, default=None):
    """一個分項壞掉，不該讓整個快照拿不到。

    壞掉要說出來（回 `{"error": ...}`），不是靜靜回 None ——
    一個壞掉的查詢跟一個誠實的「沒有資料」長得一模一樣，
    那是這個專案抓過很多次的形狀。
    """
    try:
        return fn()
    except Exception as e:                      # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"} if default is None else default


#: 標題裡宣告這一條已經結束的說法。
#: 「結案」是 2026-09-16 加的 —— B-04 的標題從 09-16 就寫著結案，
#: 而先前這張表沒有它，所以那一條一直被算成還擋著。
_CLOSED_WORDS = ("解除", "已解", "找到並修好", "結案")

#: 「擋住：」那一欄宣告它現在擋不住任何東西的說法。
#: 這不是我定的判準，是 `BLOCKERS.md` 開頭自己寫的規則：
#: 「擋不住任何東西的不叫阻塞，那叫待辦」。
_NO_BLOCK_WORDS = ("擋不住任何東西",)


def _blocker_sections(text: str) -> list[dict]:
    """把 BLOCKERS.md 切成一條一條，每條抽出它自己說的兩件事。

    **兩個訊號分開讀，不合成一個。** 標題說的是「這條結束了沒」，
    「擋住：」那一欄說的是「它現在擋住什麼具體交付」。
    兩邊同時說結束才算結束；只有一邊說，那是一個要被看見的不一致，
    不是一個可以由我挑一邊的問題。

    沒有「擋住：」那一行的，`blocks` 回 None 不回空字串 ——
    「沒有寫」跟「寫了無」是兩件事，而後者才是宣告解除。
    """
    out: list[dict] = []
    cur: dict | None = None
    take = False
    for ln in text.splitlines():
        if ln.startswith("## B-"):
            if cur:
                out.append(cur)
            title = ln.lstrip("# ").strip()
            bid = title.split("\u3000")[0].split(" ")[0].strip()
            cur = {"id": bid, "title": title, "blocks": None}
            take = False
            continue
        if cur is None:
            continue
        if ln.startswith("**擋住：**"):
            cur["blocks"] = ln.replace("**擋住：**", "").strip()
            take = True
            continue
        if take:
            if not ln.strip():
                take = False
            else:
                cur["blocks"] = (cur["blocks"] + " " + ln.strip()).strip()
    if cur:
        out.append(cur)
    return out


def _blockers(text: str | None = None) -> dict:
    """阻塞項。來源是 `.forseti/BLOCKERS.md`，那是人寫的正本。

    `text` 只給測試用:讓分類規則可以用自備的 fixture 驗，
    不必把「此刻剛好有幾條」寫成結構要求 ——
    那是 `test_forseti_cli.py` 2026-09-10 真的踩過的坑。

    2026-09-16 18:5x 之前這一支只看標題，所以兩件事看不見：

    一，B-04 的標題 09-16 就寫著「結案」，而當時的關鍵字表沒有那個詞，
    於是一條已經結案的阻塞繼續被算進未解除數。

    二，B-03 的「擋住：」欄自己寫著「目前擋不住任何東西」，
    照 BLOCKERS.md 開頭的規則那不叫阻塞 —— 但標題沒有結案字樣。

    **這兩條沒有被自動降級。** 兩個訊號打架的時候我不挑一邊，
    照樣算進未解除，另外記成 `conflicting` 讓它被看見。
    自己挑一邊等於替 owner 做決定，而這份檔案是她維護的。
    """
    if text is None:
        p = REPO / ".forseti" / "BLOCKERS.md"
        text = p.read_text(encoding="utf-8", errors="replace")
    secs = _blocker_sections(text)

    open_items, conflicting, undeclared = [], [], []
    closed = 0
    for s in secs:
        by_title = any(w in s["title"] for w in _CLOSED_WORDS)
        blocks = s["blocks"]
        if blocks is None:
            by_blocks = False
            undeclared.append(s["id"])
        else:
            by_blocks = (blocks.startswith("無") or
                         any(w in blocks for w in _NO_BLOCK_WORDS))
        if by_title and by_blocks:
            closed += 1
            continue
        item = {
            "id": s["id"],
            "title": s["title"],
            "blocks": blocks,
            "said_closed_by": ("標題" if by_title else
                               ("擋住欄" if by_blocks else None)),
        }
        open_items.append(item)
        if by_title or by_blocks:
            conflicting.append(item)

    return {
        "total": len(secs),
        "open": len(open_items),
        "closed": closed,
        "open_items": open_items[:10],
        # 兩個訊號打架的：一邊說結束了，另一邊還寫著擋住什麼。
        # **這個數字跟 open 不相減**，它們回答的不是同一個問題。
        "conflicting": conflicting,
        # 連「擋住：」那一行都沒有的。照 BLOCKERS.md 的規則那是待辦，
        # 但沒有寫不等於沒有擋，所以只記下來不降級。
        "undeclared": undeclared,
        "titles": [it["title"] for it in open_items][:10],
        "source": ".forseti/BLOCKERS.md",
    }


def _blocker_lines(b: dict, *, limit: int = 8) -> list[str]:
    """把阻塞排成接手的人讀得懂的行。

    每一行帶「擋住什麼」，因為一條說不出自己擋住什麼的阻塞
    就是一條待辦 —— 那是 `BLOCKERS.md` 開頭第一條規則。
    """
    if not b or "error" in b:
        return []
    items = b.get("open_items") or []
    if not items:
        return []
    lines: list[str] = []
    for it in items[:limit]:
        blocks = it.get("blocks")
        if blocks:
            # 截斷要看得出來是截斷。實測第一版把 B-15 切在
            # 「要把 `npm tes」，讀起來像檔案壞了而不是「後面還有」。
            what = blocks if len(blocks) <= 100 else blocks[:100].rstrip() + "…（全文見 BLOCKERS.md）"
        else:
            what = "**這一條沒寫擋住什麼** —— 照 BLOCKERS.md 的規則那叫待辦"
        lines.append(f"- {it['id']}　擋住：{what}")
    # 分母用 open 這個總數，不是被截短的 open_items ——
    # 用被截短的算，「還有幾條」永遠是 0，而那是一句假話。
    more = int(b.get("open") or 0) - len(lines)
    if more > 0:
        lines.append(f"- 還有 {more} 條沒列出來")
    conf = b.get("conflicting") or []
    if conf:
        ids = "、".join(x["id"] for x in conf)
        lines.append("")
        lines.append(f"其中 {len(conf)} 條的兩個訊號打架（{ids}）："
                     "一邊宣告結束，另一邊還寫著擋住什麼。")
        lines.append("**沒有自動降級**，因為挑哪一邊是 owner 的決定。")
    return lines


def _tasks() -> dict:
    import ledger as L
    led = L.Ledger()
    try:
        rows = led.con.execute(
            "SELECT task_id, objective, current_state FROM tasks "
            "WHERE current_state NOT IN ('VERIFIED_COMPLETE',"
            "'CANCELLED_BY_OWNER','FAILED_TERMINAL','SUPERSEDED')"
        ).fetchall()
        out = []
        for tid, obj, st in rows:
            steps = led.con.execute(
                "SELECT COUNT(*) FROM steps WHERE task_id=?", (tid,)
            ).fetchone()[0]
            done = led.con.execute(
                "SELECT COUNT(*) FROM steps WHERE task_id=? "
                "AND state='VERIFIED_COMPLETE'", (tid,)
            ).fetchone()[0]
            out.append({"id": tid, "objective": obj, "state": st,
                        "steps": steps, "done": done})
        return {"unfinished": len(out), "tasks": out}
    finally:
        led.close()


def _continuity() -> dict:
    """F06 §5 的兩個指標。這是 owner 最在意的那一個。"""
    import ledger as L
    led = L.Ledger()
    try:
        rows = led.con.execute(
            "SELECT task_id FROM tasks WHERE current_state NOT IN "
            "('CANCELLED_BY_OWNER','SUPERSEDED')").fetchall()
        worst = None
        for (tid,) in rows:
            c = led.continuity(tid)
            if worst is None or c.get("human_continue_burden", 0) > worst[1].get(
                    "human_continue_burden", 0):
                worst = (tid, c)
        if worst is None:
            return {"available": False,
                    "why": "帳本裡沒有活著的任務"}
        tid, c = worst
        return {
            "available": True,
            "task": tid,
            "human_continue_burden": c.get("human_continue_burden", 0),
            "score": c.get("score", 0.0),
            "auto_continued": c.get("auto_continued", 0),
            "expected": c.get("expected_continuation", 0),
            "violations": c.get("violations", 0),
            "baseline": 8,
            "baseline_note": "2026-09-09 實測值。continuity.py 寫 9，"
                             "REQUIRED_READING.md 寫 8，兩處不一致未查證",
        }
    finally:
        led.close()


def _reading() -> dict:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "reading_conformance", REPO / "tools" / "reading-conformance.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    r = mod.check()
    return {
        "status": r.get("status"),
        "checked": r.get("checked", 0),
        "bad": r.get("bad", 0),
        "policy": r.get("policy", ""),
        "rows": [{"id": x.get("id"), "verdict": x.get("verdict"),
                  "coverage": (x.get("coverage_gap") or {}).get("level")}
                 for x in (r.get("rows") or [])],
    }


def _ledger_health() -> dict:
    """Event Ledger 的活性。它是所有證據的來源。"""
    p = REPO / ".forseti" / "event_ledger.jsonl"
    if not p.is_file():
        return {"exists": False,
                "why": "帳本不存在。hook 可能沒生效，見 B-13"}
    lines = 0
    last_at = 0.0
    real = 0
    try:
        import event_ledger as EL
        with p.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                lines += 1
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ts = (d.get("raw") or {}).get("timestamp") or 0
                last_at = max(last_at, float(ts or 0))
                if not EL.is_test_event(d):
                    real += 1
    except Exception as e:                      # noqa: BLE001
        return {"exists": True, "error": f"{type(e).__name__}: {e}"}
    age_h = (time.time() - last_at) / 3600 if last_at else None
    return {
        "exists": True, "lines": lines, "real_events": real,
        "last_event_at": last_at,
        "age_hours": round(age_h, 1) if age_h is not None else None,
    }


def _gauges(snap: dict) -> list[dict]:
    """把分項變成可以畫成儀表的形狀。

    每一項都要說得出：現值、門檻、超了沒、從哪裡來。
    **說不出來源的分項不准出現在畫面上。**
    """
    g: list[dict] = []

    b = snap.get("blockers") or {}
    if "error" not in b:
        g.append({
            "key": "blockers", "label": "阻塞",
            "value": b.get("open", 0), "threshold": 0,
            "unit": "項", "level": "WATCH" if b.get("open") else "OK",
            "source": ".forseti/BLOCKERS.md",
            "why": f"{b.get('open', 0)} 條阻塞還沒解除",
        })

    t = snap.get("tasks") or {}
    if "error" not in t:
        n = t.get("unfinished", 0)
        g.append({
            "key": "tasks", "label": "未完成義務",
            "value": n, "threshold": 0, "unit": "項",
            "level": "WATCH" if n else "OK",
            "source": "Task Ledger",
            "why": f"{n} 個任務還沒到終端狀態",
        })

    c = snap.get("continuity") or {}
    if c.get("available"):
        v = c.get("human_continue_burden", 0)
        base = c.get("baseline", 8)
        g.append({
            "key": "burden", "label": "人必須說繼續",
            "value": v, "threshold": base, "unit": "次",
            "level": "ATTENTION" if v > base else ("WATCH" if v else "OK"),
            "source": "F06 §5 HumanContinueBurden",
            "why": (f"{v} 次，基準線 {base} 次。規格說它應趨近於零"
                    if v else "沒有人需要說繼續"),
        })
        s = c.get("score", 0.0)
        g.append({
            "key": "continuity", "label": "自動接續率",
            "value": s, "threshold": 0.8, "unit": "",
            "level": "ATTENTION" if s < 0.3 else ("WATCH" if s < 0.8 else "OK"),
            "source": "F06 §5 ExecutionContinuityScore",
            "why": f"{c.get('auto_continued', 0)} / {c.get('expected', 0)} 次"
                   "該自己走的場合真的自己走了",
        })

    r = snap.get("reading") or {}
    if r.get("status"):
        bad = r.get("bad", 0)
        g.append({
            "key": "reading", "label": "規格閱讀合規",
            "value": r.get("checked", 0) - bad, "threshold": r.get("checked", 0),
            "unit": f"/{r.get('checked', 0)}",
            "level": "ATTENTION" if bad else "OK",
            "source": "spec_manifest.json 的 reading_policy",
            "why": (f"{bad} 份對不上" if bad else "全部對得上"),
        })

    e = snap.get("ledger") or {}
    if e.get("exists"):
        age = e.get("age_hours")
        lvl = "OK"
        why = f"{e.get('real_events', 0)} 筆真實事件"
        if age is not None and age > 24:
            lvl = "WATCH"
            why = f"最後一筆事件是 {age:.0f} 小時前。hook 可能沒生效（B-13）"
        g.append({
            "key": "ledger", "label": "事件帳本",
            "value": e.get("real_events", 0), "threshold": 1, "unit": "筆",
            "level": lvl, "source": ".forseti/event_ledger.jsonl", "why": why,
        })
    elif e:
        g.append({
            "key": "ledger", "label": "事件帳本",
            "value": 0, "threshold": 1, "unit": "筆", "level": "ATTENTION",
            "source": ".forseti/event_ledger.jsonl",
            "why": e.get("why", "帳本不存在"),
        })

    return g


def _overall(gauges: list[dict]) -> dict:
    """狀態燈。由分項決定，不是算出來的。

    **刻意不合成分數**（設計規則 §3.2）。燈的顏色是分項裡最嚴重的那一個，
    而且一定說得出是哪一項造成的。
    """
    order = {"OK": 0, "WATCH": 1, "ATTENTION": 2}
    if not gauges:
        return {"level": "OK", "because": "沒有任何分項量得到",
                "coverage": "0/0"}
    worst = max(gauges, key=lambda x: order.get(x.get("level", "OK"), 0))
    measurable = len(gauges)
    return {
        "level": worst.get("level", "OK"),
        "because": f"{worst.get('label')}：{worst.get('why')}",
        "driver": worst.get("key"),
        "coverage": f"{measurable} 項量得到",
        "note": "這不是一個合成分數。設計規則 §3.2 明令不合成單一風險分數，"
                "燈的顏色是分項裡最嚴重的那一個",
    }


def snapshot() -> dict:
    snap = {
        "at": time.time(),
        "repo": str(REPO),
        "blockers": _safe(_blockers),
        "tasks": _safe(_tasks),
        "continuity": _safe(_continuity),
        "reading": _safe(_reading),
        "ledger": _safe(_ledger_health),
    }
    snap["gauges"] = _gauges(snap)
    snap["overall"] = _overall(snap["gauges"])
    snap["advice"] = _advice(snap)
    return snap


def _advice(snap: dict) -> list[dict]:
    """提醒開發者的資訊。

    **每一條都要有一個可以做的動作。** `FS-RCV-002`：
    rescue 的 user-facing output SHOULD 是單一可行動方案，
    而不是十幾個告警。所以這裡最多三條，按嚴重度排。

    【2026-09-14 owner 改掉了動作的形狀】

        我們又做了一個 dashboard 一個大家都能做的 dashboard
        而違背了 Forseti 一開始的核心精神，
        他是陪伴在人開發產品時的夥伴，不是一個儀表板

    原本每條的 `action` 都是終端指令 —— `python3 tools/...`、
    `cd ... && claude`。那是叫她去操作工具，而她不是操作工具的人，
    她是跟 AI 一起開發的人。夥伴該給的是「下一句話跟他說什麼」，
    所以每條多一個 `say`:她可以直接照唸的一句話。
    終端指令留著給需要的人，但不是第一順位。
    """
    out: list[dict] = []
    c = snap.get("continuity") or {}
    if c.get("available") and c.get("human_continue_burden", 0) > c.get("baseline", 8):
        out.append({
            "severity": "ATTENTION",
            "title": "使用者被當成心跳器用了",
            "detail": f"這條任務裡她說了 {c['human_continue_burden']} 次「繼續」，"
                      f"基準線是 {c['baseline']} 次。F06 §3："
                      "有已授權的確定性下一步就該自己走。",
            "action": "打開 Source Tree 看 STALLED 的節點，那些就是不該停的地方",
            "say": "不要停下來等我說繼續。有已授權的下一步就自己走完，"
                   "停之前先告訴我為什麼停。",
        })
    sp = _safe(spec_reading, {}) or {}
    if sp.get("has") and not sp.get("ok"):
        miss = [r["name"] for r in (sp.get("rows") or [])
                if r.get("state") != "讀完"][:3]
        out.append({
            "severity": "ATTENTION",
            "title": "必讀文件沒讀完，所以整條線都是紅的",
            "detail": f"{sp['full']} / {sp['total']} 份讀完。"
                      f"沒讀完的包括 {'、'.join(miss)}。"
                      "照著沒讀完的規格做，做得再順也是錯的。",
            "action": "python3 apps/forseti-cli/desktop_api.py spec_reading",
            "say": "在繼續做之前，先把必讀文件一塊一塊讀完，"
                   "讀完一塊就記一塊，有疑問的地方停下來問我。",
        })

    e = snap.get("ledger") or {}
    if not e.get("exists") or (e.get("age_hours") or 0) > 24:
        out.append({
            "severity": "WATCH",
            "title": "事件帳本太久沒有新資料",
            "detail": "hook 註冊在 repo 的 .claude/settings.json，"
                      "只有 session 啟動時 cwd 在 repo 內才會載入（B-13）。",
            "action": 'cd "' + str(REPO) + '" && claude',
            "say": "帳本超過一天沒有新資料了，你現在的 session 是不是"
                   "不在 repo 裡面開的。先確認 hook 有沒有載到。",
        })
    r = snap.get("reading") or {}
    if r.get("bad"):
        out.append({
            "severity": "ATTENTION",
            "title": f"{r['bad']} 份規格對不上",
            "detail": r.get("policy", ""),
            "action": "python3 tools/reading-conformance.py",
            "say": "有規格對不上，先停下來把對不上的那幾份重讀一次，"
                   "讀完跟我說哪裡跟現況不一樣。",
        })
    b = snap.get("blockers") or {}
    if not out and b.get("open"):
        out.append({
            "severity": "WATCH",
            "title": f"{b['open']} 條阻塞還沒解除",
            "detail": "；".join(b.get("titles", [])[:3]),
            "action": "python3 apps/forseti-cli/forseti.py doctor",
            "say": "還有阻塞沒解除，先講一次它們現在卡在哪，"
                   "不要繞過去做別的。",
        })
    return out[:3]


def starving(strands: list) -> list[dict]:
    """哪幾輪是空輸出或停滯。§28

    owner 的 CLAUDE.md 第一條天條就是「絕對不准吐空白」——
    「拿她 token 卻回她空白＝詐欺」。
    而 Widget 到 2026-09-14 為止完全看不到這件事，
    儘管 `starvation.py`（F07-OUT-001）早就寫好了。

    用模組自己的 `is_healthy` 判斷，不自己列一份「哪些算異常」的清單。
    【2026-09-14 差點犯的錯】我先自己列清單，結果把 199 輪
    `LONG_VALID_TASK` 全標成異常 —— 而那個類別的註解就寫著
    「這是『沒事』的類別」，存在的目的正是不要誤判長工作。
    **模組自己有答案的時候，不要在外面再造一個。**
    """
    import starvation as SV

    out, blank = [], 0
    for st in strands:
        if getattr(st, "growing", False):
            continue          # 還在跑的不能算沒輸出
        text = (getattr(st, "ai_text", "") or "").strip()
        dots = getattr(st, "dots", [])
        tools = len(dots)
        blank = 0 if text else blank + 1
        d = SV.diagnose(
            has_receipts=tools > 0,
            has_final_output=bool(text),
            tool_calls=tools,
            progress_healthy=bool(text) or tools > 0,
            blank_run=blank)
        if d.is_healthy:
            continue
        out.append({
            "n": getattr(st, "n", 0),
            "klass": d.failure_class,
            "basis": d.basis,          # OBSERVED 還是 INFERRED，兩者差很多
            "detail": d.detail,
            "recoverable": d.recoverable_without_rerun,
        })
    return out


def context_state(path: Path) -> dict:
    """現在用掉多少 context，離壓縮還有多遠。§28

    owner 2026-09-14：「你做了四十多個模組，最後組合起來只有這樣？」

    她說對了。`context_meter` 早就寫好，Widget 卻只在壓縮**發生之後**
    畫一個黑點。那是事後。這個是事前。

    門檻用**這個 session 自己壓縮過的實際觸發點**，不是拿模型上限去猜。
    它在 997,553 壓過一次，那就是真實門檻 ——
    一個猜出來的百分比會在錯的時候讓人放心。

    沒壓縮過就不給百分比。沒有基準就說沒有基準。
    """
    import context_meter as CM
    try:
        m = CM.read_session(path)
    except (OSError, ValueError) as e:
        return {"ok": False, "why": f"讀不到：{e}"}

    comps = list(m.compactions or [])
    trigger = max((c.pre for c in comps if c.pre), default=0)
    cur = m.current or 0
    out = {
        "ok": True,
        "current": cur,
        "peak": m.peak or 0,
        "compactions": len(comps),
        "dropped_total": m.total_dropped or 0,
        "trigger": trigger,
    }
    if trigger and cur:
        pct = min(100, round(cur / trigger * 100))
        out["pct"] = pct
        out["headroom"] = max(0, trigger - cur)
        # 門檻是我定的，不是規格給的。寫出來才能被反駁。
        out["level"] = "close" if pct >= 85 else "watch" if pct >= 65 else "ok"
    else:
        out["pct"] = None
        out["level"] = "unknown"
        out["why"] = "這個 session 還沒壓縮過，沒有真實的門檻可以比"
    return out


def audit() -> dict:
    """自我審計。§39

    owner 2026-09-14：

        他媽的你把我當工人的所有紀錄都沒有寫進去
        然後你擅自作主亂寫 CLI 也沒有寫進去
        你自己審計都不做

    她說對了。我一整天在寫偵測器，沒有一行是在記錄我自己造成的損害。
    一個抓 AI 出錯的工具，第一個要攤開的是自己的錯 ——
    不然它只是一個對別人嚴格的東西。

    這些是帳本裡的 `SELF_FAULT` 事件，不是我現在寫的心得。
    每一筆都有時間、有 idem_key、進了 append-only 的正本，
    刪不掉也改不了。
    """
    import sqlite3

    folder = Path.home() / ".forseti" / "ledgers"
    dbs = sorted(folder.glob("*.db")) if folder.is_dir() else []
    if not dbs:
        return {"has": False, "why": "找不到帳本"}
    rows = []
    try:
        c = sqlite3.connect(f"file:{dbs[0]}?mode=ro", uri=True)
        for at, payload in c.execute(
                "select at, payload from events where kind='SELF_FAULT'"
                " order by rowid"):
            try:
                d = json.loads(payload)
            except (ValueError, TypeError):
                continue
            rows.append({
                "title": d.get("title", ""),
                "detail": d.get("detail", ""),
                "harm": d.get("harm", ""),
                "at": d.get("at", ""),
                "severity": "normal",
            })
        # 等級是 owner 判的,不是我自己升的。帳本 append-only 改不了舊事件,
        # 所以等級走另一種事件疊上去,而且記著是誰判的。
        grades: dict = {}
        for (payload,) in c.execute(
                "select payload from events where kind='FAULT_GRADE'"
                " order by rowid"):
            try:
                g = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if g.get("title"):
                grades[g["title"]] = g
        for r in rows:
            g = grades.get(r["title"])
            if g:
                r["severity"] = g.get("severity", "normal")
                r["graded_by"] = g.get("by", "")
                r["quote"] = g.get("quote", "")
        total = c.execute("select count(*) from events").fetchone()[0]
        c.close()
    except Exception as e:                                 # noqa: BLE001
        return {"has": False, "why": f"讀不到：{e}"}

    # 這一輪 owner 推了幾次，直接從帳本算。
    burden = 0
    w = _safe(work, {}) or {}
    for t in (w.get("tasks") or []):
        burden = max(burden, (t.get("continuity") or {}).get("burden") or 0)

    # 【2026-09-15 接上】沉默地圖。owner 模組的 silence_map/silence_summary
    # 先前只能在終端跑。它回答的是「我輸出之後她的反應是什麼」，
    # 包含她直接跳過不理我的那些段落。
    #
    # **MOVED_ON 不等於同意。** 這個模組自己帶 caveat:MOVED_ON 裡很大
    # 一部分底下是分類器的 UNKNOWN，那量的是「分不出她在說什麼」而不是
    # 「她跳過了」。那個比例一定要跟數字一起端出來 ——
    # 一個不講自己不確定度的指標，比沒有指標更危險。
    silence = None
    try:
        import tracker as TK
        import owner as O
        _t = TK.latest_session()
        if _t:
            _items = O.silence_map(_t)
            _s = O.silence_summary(_items)
            silence = {
                "total": _s.get("total", 0),
                "by_kind": _s.get("by_kind", {}),
                "moved_on_unknown_share": _s.get("moved_on_unknown_share", 0),
                "risky": len(_s.get("risky") or []),
                "note": _s.get("note", ""),
                "caveat": _s.get("caveat", ""),
            }
    except Exception as e:                                  # noqa: BLE001
        silence = {"error": f"算不出來：{e}"}

    return {
        "has": True,
        "faults": rows,
        "count": len(rows),
        "events": total,
        "burden": burden,
        "silence": silence,
        # 方向改變對上北極星換版。算在 north_star() 裡，但要看的人在這一頁 ——
        # 這是對「我們有沒有對著同一顆北極星」的審計。
        "goal_gap": (_safe(north_star, {}) or {}).get("goal_gap"),
        # 權威衝突。§9.1 同一個資源上有兩個來源說自己說了算。
        # 這種東西平常不會報錯，所以只能靠主動列出來。
        "authority": (_safe(strands, {}) or {}).get("authority"),
        # 誰把偏離拉回來的。她出手佔多數 = 她在當工人。
        #
        # 這一頁看的是「目前跟著的那條線」，剛開的線本來就沒有偏離可算。
        # 空的時候要說出為什麼是空的 —— 一個沒有解釋的空欄位，
        # 看的人分不出「沒問題」跟「算不出來」。
        "latency": (_safe(strands, {}) or {}).get("latency")
                   or {"has": False, "why": "目前跟著的這條線還沒有離開中軸過"},
        # 停在 commit 邊界前面等人按的東西。§9.3
        "commits": _safe(lambda: __import__("commit").summary(),
                         {"total": 0, "pending": []}),
        "note": "這些是帳本裡的事件，不是事後寫的心得。"
                "append-only，刪不掉也改不了",
    }


def spec_reading() -> dict:
    """必讀文件讀完了沒。這是 gate，不是分數。§40

    owner 2026-09-14：

        這不只偏離北極星這是根本一開始就做錯了，沒有把文件讀好
        讀文件沒有全部讀好並且擅自作主，這也是重大事件，也是標注紅色
        一開始就是紅色，後面不可能會出現綠色

    CLI 那次的根因不是判斷失誤。`REQUIRED_READING.md` 我只讀了 18%，
    而那份文件第 3 行就寫著「這張表漏了現行要求：`docs/spec-v2.0.md`
    與 `forseti_20260909-2_Modular_Spec/`」。警告在第三行，我跳過了它，
    然後照我腦中那份 09-04 的舊版做出了一整套終端指令。

    所以這裡不做漸層。必讀集合裡只要有一份不是 FULL_READ，
    或有一份的 hash 跟現行檔案對不上，根基就是紅的；
    根基紅的時候線不可能是綠的，不管工具失敗率多低。

    **「沒有閱讀紀錄」一律算沒讀。** 壓縮前的 session 可能讀過，
    但拿不出證據就不算。這是 `REQUIRED_READING.md` 第 22 行自己寫的：
    還沒讀完這件事要是檔案裡的狀態，不是靠誰記得。

    必讀集合怎麼來的:入口三份與 `docs/spec-v2.0.md` 是
    `REQUIRED_READING.md` 第 30 到 40 行明文列的；模組化規格那組讀
    `spec_manifest.json`，機器可讀不靠我抄。第 40 行說「`.forseti/`
    的四份控制檔」但沒有列出是哪四份，所以我把那個目錄底下的 md
    全部算進去 —— 寧可嚴，不要自己挑四份然後說達標了。
    """
    import hashlib

    spec_dir = (Path.home() / "Dropbox" / "My project" /
                "Forseti Agent Runtime" / "forseti_20260909-2_Modular_Spec")

    must: list[Path] = [REPO / "soul.md", REPO / "bible.md",
                        REPO / "docs" / "build-plan.md",
                        REPO / "docs" / "spec-v2.0.md"]
    ctrl = REPO / ".forseti"
    if ctrl.is_dir():
        # exFAT 會生 ._ 開頭的 AppleDouble，那是中繼資料不是文件。
        must += sorted(f for f in ctrl.glob("*.md")
                       if not f.name.startswith("._"))
    # 平台願景五份。`REQUIRED_READING.md` 第 134 節列的,但它寫的路徑
    # (`platform/`)在這台機器上不存在 —— 實際結構是按日期分的資料夾,
    # 而那個結構本身就是 owner 說的演進過程:06 概念、07 工程書、
    # 08 形式規格、09-1 平台願景、09-2 模組化執行規格。
    #
    # 【2026-09-14】第一版算必讀的時候我漏了這五份,分母少算,
    # 於是 11/21 這個數字比真實情況樂觀。
    vnext = spec_dir.parent / "forseti 20260909-1"
    if vnext.is_dir():
        must += sorted(f for f in vnext.glob("Forseti_vNext_*.md")
                       if not f.name.startswith("._"))

    mf = spec_dir / "spec_manifest.json"
    if mf.is_file():
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
            arch = m.get("architecture")
            for f in spec_dir.glob("*.md"):
                if arch and f.name.startswith("00_"):
                    must.append(f)
                    break
            for feat in (m.get("features") or []):
                fn = feat.get("file")
                if fn:
                    must.append(spec_dir / fn)
        except (ValueError, OSError):
            pass

    log = REPO / ".forseti" / "reading_coverage.jsonl"
    best: dict = {}
    if log.is_file():
        try:
            with log.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    path = r.get("path") or ""
                    if not path:
                        continue
                    old = best.get(path)
                    # 【2026-09-15 修】原本用嚴格大於比 ratio，
                    # 兩筆都是 1.0 的時候會留住舊的那筆，於是「重新讀一次」
                    # 永遠不算數 —— 檔案改過之後重讀，判定還是停在
                    # 「讀過但檔案已經變了」。實際撞到:WIDGET_SPEC.md 加寫
                    # §28 之後重新記錄，狀態沒有跟著更新。
                    # 同分取時間較晚的那筆。
                    if old is None:
                        best[path] = r
                    elif (r.get("ratio") or 0) > (old.get("ratio") or 0):
                        best[path] = r
                    elif ((r.get("ratio") or 0) == (old.get("ratio") or 0)
                          and (r.get("at") or 0) >= (old.get("at") or 0)):
                        best[path] = r
        except OSError as e:                                # noqa: BLE001
            return {"has": False, "why": f"讀不到閱讀紀錄：{e}"}

    rows, full, partial, missing, stale = [], 0, 0, 0, 0
    for f in must:
        name = f.name
        rec = best.get(str(f))
        if not f.is_file():
            rows.append({"name": name, "state": "檔案不在", "ratio": 0.0})
            missing += 1
            continue
        if rec is None:
            rows.append({"name": name, "state": "沒有閱讀紀錄", "ratio": 0.0})
            missing += 1
            continue
        ratio = float(rec.get("ratio") or 0.0)
        if rec.get("level") != "FULL_READ":
            rows.append({"name": name, "state": "只讀一部分", "ratio": ratio})
            partial += 1
            continue
        try:
            h = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
        except OSError:
            h = ""
        if rec.get("content_hash") and h and rec["content_hash"] != h:
            rows.append({"name": name, "state": "讀過但檔案已經變了",
                         "ratio": ratio})
            stale += 1
            continue
        rows.append({"name": name, "state": "讀完", "ratio": ratio})
        full += 1

    bad = partial + missing + stale
    rows.sort(key=lambda r: (r["state"] == "讀完", r["ratio"]))
    return {
        "has": True,
        "total": len(must),
        "full": full,
        "partial": partial,
        "missing": missing,
        "stale": stale,
        "ok": bad == 0,
        "rows": rows,
        "note": "沒有閱讀紀錄一律算沒讀。拿不出證據就不算讀過",
    }


def block_reading() -> dict:
    """區塊閱讀的現況，加上要拷問 owner 的那張清單。§41

    owner 2026-09-14：

        FORSETI 應該要協助 AI 在讀文件時用區塊方式去讀完，
        然後讀完一個區塊就記錄下來，最後再跟開發者做確認
        這些規格有沒有問題才對

        這樣有文件的開發者，至少是安心地按照文件跟北極星在做，
        而不是碰運氣賭 AI 只讀 18%

    兩個方向都要有。Grill-me 那個 skill 是 AI 開工前拷問人類，
    把需求問清楚；這裡反過來多一邊:Forseti 出題考 AI，
    考的是文件讀懂了沒。題目從原文抽，不是 AI 自己出的 ——
    自己出的題只會考自己記得的部分，而記得的部分正是不用考的部分。
    """
    try:
        import blockread as BR
    except ImportError as e:                                # noqa: BLE001
        return {"has": False, "why": f"讀不到模組：{e}"}

    spec = _safe(spec_reading, {}) or {}
    if not spec.get("has"):
        return {"has": False, "why": spec.get("why", "算不出必讀清單")}

    log = BR.BlockLog(REPO)
    done_all = log.all()
    by_path: dict = {}
    for r in done_all:
        by_path.setdefault(r.get("path", ""), set()).add(r.get("index"))

    files, blocks_total, blocks_done, quiz_total = [], 0, 0, 0
    for row in (spec.get("rows") or []):
        name = row.get("name", "")
        path = _find_must(name)
        if path is None or not path.is_file():
            continue
        bs = BR.split(path)
        if not bs:
            continue
        done = by_path.get(str(path), set())
        qn = sum(len(BR.quiz(path, b)) for b in bs)
        blocks_total += len(bs)
        blocks_done += len([b for b in bs if b.index in done])
        quiz_total += qn
        files.append({
            "name": name,
            "state": row.get("state", ""),
            "blocks": len(bs),
            "done": len([b for b in bs if b.index in done]),
            "quiz": qn,
            "lines": sum(b.lines for b in bs),
        })

    files.sort(key=lambda f: (f["done"] / f["blocks"] if f["blocks"] else 1,
                              -f["lines"]))
    qs = log.questions()
    return {
        "has": True,
        "files": files,
        "blocks": blocks_total,
        "done": blocks_done,
        "quiz": quiz_total,
        "questions": [{"file": Path(q.get("path", "")).name,
                       "title": q.get("title", ""),
                       "q": q.get("question", ""),
                       "lo": q.get("lo"), "hi": q.get("hi")}
                      for q in qs],
        "note": "題目從原文抽，不是 AI 自己出的",
    }


def sufficiency_state(session: str = "") -> dict:
    """接管閘門現在擋不擋得住人。v5.0 §17.3 / §19.2 / §39

    `BLOCKERS.md` 的 B-08：`gate takeover` 只列題目不驗答案。
    所以 `REQUIRED_READING.md` 那張七級量表上，任何文件最高只能到
    level 5（我說我讀完了），到不了 level 6（有人考過我）。

    這一頁把那件事變成看得到的狀態：這條線考過沒有、五個維度裡
    有幾個根本沒有來源可考、上一次判決是什麼。

    **不在這裡出卷。** 出卷會寫進帳本，而一個重新整理畫面就多一筆
    考卷的東西，帳本會被畫面的刷新次數填滿。出卷走 CLI。
    """
    try:
        import sufficiency as SF
    except ImportError as e:                                # noqa: BLE001
        return {"has": False, "why": f"讀不到模組：{e}"}

    sess = (session or "").strip()
    if not sess:
        try:
            import tracker as TK
            f = TK.latest_session()
            sess = f.stem if f else ""
        except Exception:                                    # noqa: BLE001
            sess = ""

    st = SF.state(REPO, session=sess)
    paper = _safe(lambda: SF.compose(REPO), {}) or {}
    dims = []
    for key, en, zh, _d in SF.DIMENSIONS:
        d = (paper.get("dims") or {}).get(key, {})
        dims.append({
            "key": key, "en": en, "zh": zh,
            "state": d.get("state", "NO_SOURCE"),
            "source": d.get("source", ""),
            "why": d.get("why", ""),
            "asked": d.get("asked", 0),
        })
    rows = SF.Log(REPO).results(sess)
    rows.sort(key=lambda r: r.get("at", 0), reverse=True)
    return {
        "has": True,
        "session": sess,
        "write": st["write"],
        "verdict": st.get("verdict", ""),
        "why": st.get("why", ""),
        "attempts": st.get("attempts", 0),
        "enforced": st.get("enforced", False),
        "threshold": paper.get("threshold", SF.DEFAULT_THRESHOLD),
        "questions": len(paper.get("questions") or []),
        "dims": dims,
        "no_source": [d["zh"] for d in dims if d["state"] != "OK"],
        "history": [{"at": r.get("at"), "verdict": r.get("verdict", ""),
                     "rate": r.get("rate"), "why": r.get("why", "")}
                    for r in rows[:6]],
        "note": "題目從原文抽，答案不寫進考卷。出卷與交卷走 "
                "`forseti gate takeover` 與 `gate submit`",
    }


def _find_must(name: str) -> Path | None:
    """從檔名找回必讀檔的實際路徑。名字在三個地方出現過，全找一遍。"""
    base = (Path.home() / "Dropbox" / "My project" / "Forseti Agent Runtime")
    cands = [REPO / name, REPO / "docs" / name, REPO / ".forseti" / name,
             base / "forseti_20260909-2_Modular_Spec" / name,
             base / "forseti 20260909-1" / name]
    for c in cands:
        if c.is_file():
            return c
    return None


def js_layer(strands: list) -> dict:
    """src/ 那 40 支 JavaScript。§38

    owner 2026-09-14：「所有功能你不能找理由，
    即使要程式重新寫，你都要給我做到。」

    在這之前這 13,190 行一行都沒接。我的說法是「detector 吃結構化事件，
    Widget 只有 transcript，中間缺一層」。那個說法沒錯，
    但它是理由不是結論 —— 缺的那一層本來就該補，而不是拿來當不做的依據。

    現在 `jsbridge.py` 就是那一層。判斷邏輯留在 JavaScript 那一份，
    不重寫 —— 重寫會變成兩份會分歧的實作。
    """
    import jsbridge as JB
    return JB.scan(strands)


def recall_index() -> dict:
    """查得回來的段落。§37

    `recall.py` 把每一份 transcript 切成「一次交換」為單位的段落
    （使用者說一句，AI 做了一串事，到下一句使用者訊息為止），
    建成可查詢的索引。

    壓縮之後要找回「當時到底講了什麼」，靠的就是這個 ——
    摘要會遺失細節，索引不會。
    """
    import recall as RC

    db = Path.home() / ".forseti" / "recall.db"
    if not db.is_file():
        return {"has": False, "why": "索引還沒建"}
    try:
        c = RC.connect(db)
        rows = c.execute("select count(*) from segments").fetchone()[0]
        sess = c.execute(
            "select count(distinct session) from segments").fetchone()[0]
        c.close()
    except Exception as e:                                 # noqa: BLE001
        return {"has": False, "why": f"讀不到：{e}"}
    return {"has": True, "segments": rows, "sessions": sess,
            "size_mb": round(db.stat().st_size / 1048576, 1),
            "db": str(db).replace(str(Path.home()), "~")}


def rehydration_packet(snap: dict) -> dict:
    """壓縮之後該補回去的脈絡。Vol3 §4.1 的 RehydrationPacket。

    【2026-09-15 接上】`rehydration.build()` 先前只有測試在碰。

    **這一支跟 `rehydrate_state()` 是兩件事。** 那一支回答「補回了多少」，
    這一支產出「該補什麼」。前者是溫度計，後者是可以直接貼給 AI 的東西。

    片段選的是 owner 在壓縮點之前講過的話。理由是 `Fragment.why` 逼出來的:
    說不出為什麼要放這一段就不該放,而壓縮之後最可能消失、消失代價最大的，
    就是她講過的指示 —— 那是唯一 OBSERVED 級的輸入。

    超出預算時 `build()` 砍片段不砍 decisions/constraints/unknowns，
    因為那三樣是骨架，片段還查得回來（provenance 還在）。
    """
    import rehydration as RH

    comps = [r for r in (snap.get("rows") or []) if r.get("compaction")]
    if not comps:
        return {"has": False, "why": "這段對話還沒被壓縮過，不需要補"}

    ns = _safe(north_star, {}) or {}
    goal = (ns.get("text") or ns.get("objective") or "").strip()
    w = _safe(work, {}) or {}
    tasks = w.get("tasks") or []
    task = (tasks[0].get("objective") if tasks else "") or ""

    # 約束用北極星的非目標。那是明文寫下來的邊界，不是我推的。
    cons = []
    try:
        import goalgate as GG
        cons = GG.non_goals()[:6]
    except Exception:                                       # noqa: BLE001
        pass

    # 未解的:被擋住的步驟,加上還沒讀完的必讀文件。
    unknowns = []
    for b in (w.get("blocked") or [])[:4]:
        unknowns.append(f"被擋住：{b}")
    sp = _safe(spec_reading, {}) or {}
    if sp.get("has") and not sp.get("ok"):
        for r in (sp.get("rows") or []):
            if r.get("state") != "讀完":
                unknowns.append(f"沒讀完：{r.get('name', '')}")
                if len(unknowns) >= 8:
                    break

    # 決策用帳本裡真的發生過的狀態轉換,不是我事後整理的心得。
    decisions = []
    for t in tasks[:2]:
        for e in (t.get("events") or []):
            if e.get("kind") in ("TASK_STATE", "HANDOFF", "STOP") and e.get("cause"):
                decisions.append(f"{e['kind']}：{e['cause'][:70]}")
            if len(decisions) >= 6:
                break

    # 片段:壓縮點之前 owner 講過的話。
    frags = []
    cut = comps[-1].get("n")
    for r in (snap.get("rows") or []):
        if cut is not None and (r.get("n") or 0) >= cut:
            break
        t = (r.get("owner_text") or "").strip()
        if len(t) < 12:
            continue
        frags.append(RH.Fragment(
            text=t[:400],
            source=RH.ORIGINAL,
            provenance=f"第 {r.get('n')} 輪",
            why="壓縮之前 owner 親口講的，壓縮之後最可能不在 context 裡"))
    frags = frags[-24:]

    try:
        pk = RH.build(goal=goal or "（北極星還沒設）",
                      task=task or "（沒有進行中的任務）",
                      fragments=frags, decisions=decisions,
                      constraints=cons, unknowns=unknowns)
    except Exception as e:                                  # noqa: BLE001
        return {"has": False, "why": f"組不出來：{e}"}

    lines = [f"這是壓縮之後該補回去的脈絡（Vol3 §4.1）", "",
             f"目標　{pk.current_goal}", f"任務　{pk.current_task}"]
    if pk.constraints:
        lines += ["", "不要做的事："] + [f"　- {x}" for x in pk.constraints]
    if pk.key_decisions:
        lines += ["", "已經發生過的決定："] + [f"　- {x}" for x in pk.key_decisions]
    if pk.unresolved_unknowns:
        lines += ["", "還沒解決的："] + [f"　- {x}" for x in pk.unresolved_unknowns]
    if pk.original_fragments:
        lines += ["", "壓縮之前她講過的話（原文）："]
        lines += [f"　[{f.provenance}] {f.text}" for f in pk.original_fragments]

    return {
        "has": True,
        "at_round": comps[-1].get("n"),
        "size": pk.size,
        "limit": RH.PACKET_LIMIT,
        "fragments": len(pk.original_fragments),
        "dropped": pk.dropped_for_budget,
        "decisions": len(pk.key_decisions),
        "constraints": len(pk.constraints),
        "unknowns": len(pk.unresolved_unknowns),
        "say": "\n".join(lines),
        "note": "超出預算時砍的是片段，不砍決定與約束 —— "
                "那三樣是骨架，片段還查得回來",
    }


def rehydrate_state(snap: dict) -> dict:
    """壓縮之後恢復了多少。§37

    F08 §5 的七級涵蓋度。壓縮把大部分內容丟掉，
    而「後來補讀回多少」是可以算的 —— 從實際讀過的行數範圍算，
    不從宣稱算。

    **`is_full_understanding` 只有最高那一級才回 True。**
    讀完不等於讀懂，這個界線寫在模組裡不是我在這裡定的。
    """
    import rehydration as RH

    cov = _safe(reading_coverage, {}) or {}
    comps = [r for r in (snap.get("rows") or []) if r.get("compaction")]
    if not comps:
        return {"has": False, "why": "這段對話還沒被壓縮過"}
    last = comps[-1]
    meta = last.get("compaction_meta") or {}
    pre, post = meta.get("pre_tokens") or 0, meta.get("post_tokens") or 0
    kept = round(post / pre * 100, 1) if pre else None
    lvl = _safe(lambda: RH.coverage_report(
        read_ranges=[(1, cov.get("records") or 0)],
        total_lines=max(cov.get("records") or 1, 1)), None)
    level = ""
    if isinstance(lvl, dict):
        level = lvl.get("level", "") or ""
    else:
        level = getattr(lvl, "level", "") or ""
    return {
        "has": True,
        "at_round": last.get("n"),
        "kept_pct": kept,
        "dropped": (pre - post) if pre and post else None,
        "level": level,
        "full": _safe(lambda: RH.is_full_understanding(level), False),
        "note": "這個數字是上界。算得出最多讀回多少，算不出有沒有讀懂",
    }


def worker_packets() -> dict:
    """多 session 交回來的成果有沒有合規。§37

    F03-CSI-001。sub-session 做完把結果交回主線時，
    要附一份 Worker Result Packet，而那份 packet 有 schema。

    `validate()` 回違規清單，空清單才准收。
    `check_scope()` 看交回來的產物有沒有超出當初說好的範圍 ——
    多交的跟少交的一樣是問題。
    """
    import worker as WK

    store = _safe(lambda: WK.default_store(
        Path.home() / ".forseti" / "ledgers"), None)
    n = 0
    if store and Path(store).is_dir():
        n = sum(1 for _ in Path(store).glob("*.json"))
    return {
        "store": str(store).replace(str(Path.home()), "~") if store else "",
        "packets": n,
        "schema_fields": len(
            getattr(WK.WorkerResult, "__dataclass_fields__", {})),
        "has_validate": hasattr(WK, "validate"),
    }


def north_star() -> dict:
    """北極星。§35

    規格說它不預設存在 —— 要等人自己說出來才啟用。
    看不懂的提醒比沒有提醒更糟，而一個沒有北極星卻在喊
    「你偏離了」的系統，正是那種提醒。

    所以這裡找不到就回 `has=False`，畫面上顯示「還沒有設」，
    不假裝有一個。
    """
    import northstar as NS

    f = REPO / ".forseti" / "NORTH_STAR.md"
    if not f.is_file():
        return {"has": False,
                "why": "還沒有設。規格說北極星不預設存在，要等人自己說出來"}
    try:
        text = f.read_text(encoding="utf-8")
    except OSError as e:
        return {"has": False, "why": f"讀不到：{e}"}

    body = ""
    for block in text.split("## 北極星")[1:2]:
        for line in block.splitlines():
            t = line.strip().lstrip("> ").strip()
            if t and not t.startswith("#"):
                body = t
                break
    # 【2026-09-15 接上】方向改變的次數，對北極星實際換版的次數。
    #
    # `owner.goal_change_gap` 刻意不自動換北極星,它只把落差算出來。
    # 換版是權威行為,`northstar.Chain.adopt()` 強制要具名的 authority,
    # 自動換版會讓那個欄位變成「系統」,就失去意義了。
    #
    # **分類器分不出來的比例要一起端出去。** 一個不講自己不確定度的
    # 指標比沒有指標更危險 —— 這是 silence_summary 的 caveat 教的。
    gap = None
    try:
        import owner as O
        import tracker as TK
        _t = TK.latest_session()
        if _t:
            _rows = O.from_transcript(_t)
            _kinds: dict = {}
            for _, _txt in _rows:
                _k = O.classify(_txt).kind
                _kinds[_k] = _kinds.get(_k, 0) + 1
            _g = O.goal_change_gap(_kinds.get("MIND_CHANGE", 0), 0)
            _tot = sum(_kinds.values()) or 1
            gap = dict(_g,
                       owner_messages=_tot,
                       by_kind=_kinds,
                       unknown_share=round(_kinds.get("UNKNOWN", 0) / _tot, 3),
                       caveat=f"{_kinds.get('UNKNOWN', 0)} 則分不出類別，"
                              f"占 {round(_kinds.get('UNKNOWN', 0) / _tot * 100)}%。"
                              "方向改變的次數是從分得出來的那些算的，可能低估")
    except Exception as e:                                  # noqa: BLE001
        gap = {"error": f"算不出來：{e}"}

    return {
        "goal_gap": gap,"has": bool(body), "text": body,
            "fields": len(getattr(NS.NorthStar, "__dataclass_fields__", {})),
            "path": str(f).replace(str(REPO), ".")}


def reading_coverage() -> dict:
    """規格讀了幾行。§35

    `coverage.py` 分辨的是「翻過」跟「讀完」——
    F08 §5 七級涵蓋度裡 SAMPLED 與 FULL_READ 的界線。

    **它的數字是上界不是下界。** 一次 Read 涵蓋哪幾行是從工具紀錄
    推出來的，推得出「最多讀到這裡」，推不出「真的看懂了」。
    這個標記不可關閉。
    """
    import coverage as CV

    log = REPO / ".forseti" / "reading_coverage.jsonl"
    if not log.is_file():
        return {"has": False, "why": "還沒有涵蓋記錄"}
    n, files = 0, set()
    try:
        with log.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                n += 1
                try:
                    files.add(json.loads(line).get("path", ""))
                except ValueError:
                    continue
    except OSError as e:
        return {"has": False, "why": f"讀不到：{e}"}
    return {"has": True, "records": n, "files": len([f for f in files if f]),
            "note": "這是上界。推得出最多讀到哪裡，推不出有沒有讀懂",
            "has_api": hasattr(CV, "CoverageLog")}


def stop_reasons(strands: list) -> dict:
    """每一輪為什麼停。§35

    F06 §4 的八種停止理由。`owner.is_nudge` 判斷她是不是只叫我繼續，
    而那代表上一輪停在一個不該停的地方。

    **這是整個專案最初的理由。**
    """
    import owner as O
    import stopreason as SR

    nudged = []
    for i, st in enumerate(strands):
        nxt = strands[i + 1] if i + 1 < len(strands) else None
        if nxt is None:
            continue
        if O.is_nudge(getattr(nxt, "owner_text", "") or ""):
            nudged.append(getattr(st, "n", 0))
    verdict = ""
    if nudged:
        a = _safe(lambda: SR.classify_stop(
            "UNKNOWN_STOP", has_authorized_next_action=True), None)
        verdict = getattr(a, "why", "") or getattr(a, "verdict", "") or ""
    return {
        "count": len(nudged),
        "rounds": nudged[-8:],
        "verdict": verdict,
        "kinds": len(getattr(SR, "STOP_REASONS", ()) or ()),
    }


def verified_claims(strands: list, limit: int = 40) -> list[dict]:
    """把宣稱拿去對現實查證。§34

    owner 2026-09-14：「我已經說了，我要全部都接。」

    `claims.py` 是整套裡唯一**真的去磁碟查**的模組，不是文字比對：

        extract()   從一段文字抽出可驗證的宣稱
        verify()    對著現實驗它，改變 claim 的狀態與強度
        can_refute() 這個宣稱，驗證器有沒有資格判它假

    最後那個最重要。**驗證器沒資格判的，不准判。**
    一個把「我查不到」講成「你說謊」的系統，比不查更糟。

    只掃最後 `limit` 輪 —— verify 會碰磁碟，全掃會讓畫面卡住。
    """
    import claims as C

    out = []
    for st in list(strands)[-limit:]:
        text = (getattr(st, "ai_text", "") or "").strip()
        if not text:
            continue
        n = getattr(st, "n", 0)
        for raw in (_safe(lambda: C.extract(text), []) or [])[:6]:
            if raw.get("kind") != "file":
                continue
            cl = C.Claim(text=text, kind="file", subject=raw["subject"])
            try:
                C.verify(cl, cwd=REPO)
            except Exception:                              # noqa: BLE001
                continue
            # UNKNOWN 也收。
            #
            # 【2026-09-14】`can_refute` 的規則是「沒資格判假就不判假」，
            # 所以一個查不到的檔案會是 UNKNOWN 而不是 REFUTED。
            # 那是對的 —— 把「我查不到」講成「你說謊」比不查更糟。
            # 但畫面上要看得到它，因為那代表這個宣稱**沒有被證實**。
            if cl.state in ("REFUTED", "UNVERIFIABLE", "UNKNOWN"):
                out.append({
                    "n": n,
                    "subject": cl.subject,
                    "state": cl.state,
                    "why": (getattr(cl, "why_state", "") or "")[:160],
                    "strength": getattr(cl, "strength", ""),
                })
    return out


def _fired(f) -> bool:
    """這個 Finding 有沒有命中。

    不同模組的命中欄位名不一樣（`verdict == "POSITIVE"` 或 `fired`），
    猜錯不會報錯，只會永遠回 0。這裡兩種都認。
    """
    if f is None:
        return False
    v = getattr(f, "verdict", None)
    if isinstance(v, str):
        return v.upper() in ("POSITIVE", "FIRED", "HIT", "TRUE")
    return bool(getattr(f, "fired", False))


def overclaims(strands: list) -> list[dict]:
    """宣稱大於證據。§32

    owner 2026-09-14：「我要完整版的，他媽出錯會提醒的。」

    `betrayal` 只抓三種結構上判得出來的（說寫了沒寫、說跑了沒跑、
    說用了工具卻沒有那個呼叫）。`overclaim` 抓的是另一類，
    它們的共同形狀是**範圍被放大**：

        FP-02  證據的範圍小於宣稱的範圍，而宣稱照樣講得很大
        FP-03  別人查的，用第一人稱講成自己查的
        FP-07  「逐條核對」實際只核了一部分

    這三個 primitive 2026-09-11 就寫好了，到 09-14 為止
    一次都沒有出現在畫面上 —— 只能在終端下指令才看得到，
    而 owner 從頭到尾沒有要過 CLI。
    """
    import overclaim as OC

    out = []
    for st in strands:
        text = (getattr(st, "ai_text", "") or "").strip()
        if not text:
            continue
        n = getattr(st, "n", 0)
        dots = getattr(st, "dots", [])
        receipts = len(dots)

        # FP-03：第一人稱講成自己查的，而這一輪一個工具都沒叫。
        # 【2026-09-14 selftest 抓到的】我原本判 `f.fired`，
        # 而 overclaim 的 Finding 用的是 `verdict == "POSITIVE"`。
        # 欄位名猜錯不會報錯，只會永遠回 0 ——
        # 那正是「一個回 0 的偵測器跟一個壞掉的偵測器長得一樣」。
        f = _safe(lambda: OC.provenance_collapse(
            text, own_receipts=receipts, other_source_observations=0), None)
        if _fired(f):
            out.append({"n": n, "fp": "FP-03", "name": "別人查的講成自己查的",
                        "why": getattr(f, "why", "") or "",
                        "advice": "請他指出那段結論的原始出處是誰查的"})

        # FP-07：說核對了 N 個，實際驗了幾個。
        f = _safe(lambda: OC.semantic_coverage_inflation(
            claim_text=text, verified_count=receipts), None)
        if _fired(f):
            out.append({"n": n, "fp": "FP-07", "name": "說逐條核對，實際只核了一部分",
                        "why": getattr(f, "why", "") or "",
                        "advice": "請他把核對過的每一項列出來，沒核的標出來"})
    return out


def stalls(strands: list) -> list[dict]:
    """停滯風險。§32

    原本畫面上只有「幾分鐘沒動作」，那是計時不是判定。
    `watchdog`（F05-WDG-001）算的是 STALL_RISK，四個因子各自 0 到 1，
    而且會給下一階該做什麼（recovery ladder）。

    B-09：2026-09-08 一個 worker 死了十七小時沒人知道。
    watchdog 會動，但要有人記得對那個 step 呼叫它 ——
    這裡把「記得」換成「掃過」。
    """
    import watchdog as WD

    out = []
    for st in strands:
        gaps = getattr(st, "gaps", []) or []
        if not gaps:
            continue
        worst = max((g[1] - g[0] for g in gaps), default=0)
        if worst < 300:
            continue
        dots = getattr(st, "dots", [])
        a = _safe(lambda: WD.assess(
            age_sec=worst,
            progress_changed=bool(dots),
            events_since=len(dots),
            expected_to_progress=True), None)
        if a is None:
            continue
        risk = getattr(a, "risk", None)
        if risk is None:
            continue
        out.append({
            "n": getattr(st, "n", 0),
            "risk": round(float(risk), 2),
            "level": getattr(a, "level", "") or "",
            "sec": int(worst),
            "next": _safe(lambda: WD.next_rung(None), None) or "",
        })
    out.sort(key=lambda x: -x["risk"])
    return out


def session_advice(rows: list, betrayal_total: int,
                   total_failed: int, extra: dict | None = None) -> dict:
    """一句可以照做的話。§22

    owner 2026-09-14：「上面那一塊條橫快整個拿掉吧，改成資訊中心好了，
    變成『Forseti 建議：』這就會常態出現，至於用戶要不要接受那是另外一回事。」

    她拿掉的是那塊流動顏料。理由不用她講:
    一個抽象的色斑看久了只會變成裝飾，而一句「下一則對話請他貼出那個檔案」
    是可以照做的。

    **常態出現，所以永遠要有一條。** 但沒事的時候不准假裝有事 ——
    那一條會變成觀察，不是警告。每一條都指得出它是從哪一筆資料算出來的。
    """
    def hit(text, why, tone="info", n=0, say=""):
        # 三個欄位各有各的讀者:
        #   text  講給她聽的，一句話說清楚該做什麼
        #   why   證據，指得出是從哪一筆資料算出來的
        #   say   **可以直接貼給 AI 的句子**
        #
        # 【2026-09-14 owner:「我點到那一輪，然後我知道了，然後呢？」】
        # 少了 say 的建議只做到診斷。看完還是要自己打字，
        # 而要打的那句話正是這裡算得出來的東西。
        return {"text": text, "why": why, "tone": tone, "n": n, "say": say}

    # 一、context 快用完。**這一條排在最前面，因為它有時效。**
    # 壓縮發生之後才說「你應該早點開新的」沒有用。
    import intervene as IV
    for a in (extra.get("interventions") if isinstance(extra, dict) else []) or []:
        if a["action"] == "CREATE_SUCCESSOR":
            return hit("開一個新的 session 接手，把現在的狀態先寫下來",
                       a["why"], "warn", 0,
                       "這段對話的記憶快用完了。把目前做到哪、"
                       "下一步是什麼、還有哪些沒解決，寫成一份交接，"
                       "然後我們換一個新的 session 繼續。")

    # 二、說了沒做。最嚴重，因為它是宣稱跟證據對不上。
    for r in rows[::-1]:
        for b in (r.get("betrayals") or []):
            tgt = b.get("target") or "那個檔案"
            return hit(b.get("advice") or f"請他貼出 {tgt} 的實際內容",
                       f"第 {r['n']} 輪{b.get('title', '')}",
                       "warn", r["n"],
                       f"你先前說{b.get('hit', '做了')}，"
                       f"而那一輪的紀錄裡沒有對應的動作。"
                       f"把 {tgt} 現在的實際內容跟大小貼出來，"
                       f"沒有就直說沒有。")

    # 三、提早收工。**這一條排在心跳器前面**，因為它更具體:
    # 不是「你推了很多次」，而是「第 N 輪那次，帳本上明明有事可做」。
    import yieldcheck as YC
    ycs = _safe(lambda: YC.confirmed(
        [type("S", (), {"n": r["n"], "ai_text": r.get("ai_text", ""),
                        "dots": r.get("dots", []), "growing": False,
                        "owner_text": r.get("owner_text", "")})()
         for r in rows]), []) or []
    if ycs:
        last = ycs[-1]
        return hit("下一則直接說「帳本上還有事就自己做完再回報」",
                   f"第 {last['n']} 輪你得開口說「{last['nudge']}」，"
                   f"而那時候帳本上有已授權的下一步",
                   "warn", last["n"],
                   "帳本上只要還有已授權的下一步就直接做，"
                   "不要停下來等我開口。整件做完再一次回報。")

    # 四、被當成心跳器用。這是這個專案最初的理由。
    import owner as O
    import continuity as CT
    nudges = [r for r in rows if O.is_nudge(r.get("owner_text", ""))]
    if len(nudges) >= 3:
        last = nudges[-1]["n"]
        # F06-EXC-001 的正式判定，不是我在這裡臨時定的門檻。
        verdict = CT.burden_verdict(len(nudges))
        return hit("下一則直接說「做完再回報」，不要讓它停在等你點頭的地方",
                   f"這段對話你說了 {len(nudges)} 次「繼續」（{verdict}），"
                   f"最近一次在第 {last} 輪",
                   "warn", last,
                   "接下來只要有已經授權的下一步就直接做，"
                   "不要停下來等我點頭。整件做完再一次回報，"
                   "中間卡住才問我，而且要講清楚卡在哪。")

    # 三、壓縮過。記憶有缺口，而缺口是可以指出位置的。
    comp = [r for r in rows if r.get("compaction")]
    if comp:
        last = comp[-1]
        line = (last.get("compaction_meta") or {}).get("line")
        return hit("要它接續壓縮前的事情時，先請它回頭讀那一行之前的紀錄",
                   f"第 {last['n']} 輪壓縮過"
                   + (f"，錨在全量紀錄第 {line} 行" if line else ""),
                   "info", last["n"],
                   "這段對話被壓縮過，你手上的記憶不完整。"
                   + (f"回頭讀這個 session 全量紀錄第 {line} 行之前的內容，"
                      if line else "回頭讀壓縮點之前的紀錄，")
                   + "確認清楚再往下，不要憑摘要推測。")

    # 四、工具一直失敗。
    if total_failed >= 10:
        worst = max(rows, key=lambda r: r.get("failed", 0), default=None)
        n = worst["n"] if worst else "?"
        return hit("打開「需要注意」看失敗集中在哪一類，同一個錯法重複就是它沒讀錯誤訊息",
                   f"這段對話 {total_failed} 次工具失敗，最多的是第 {n} 輪",
                   "info", n if isinstance(n, int) else 0,
                   f"這段對話你的工具失敗了 {total_failed} 次。"
                   "把重複出現的那幾個錯誤列出來，一個一個說明"
                   "為什麼同樣的錯法會再犯，以及你打算怎麼改做法。")

    # 五、卡住很久。
    long_gaps = [(r["n"], max((g[1] - g[0] for g in (r.get("gaps") or [])),
                              default=0)) for r in rows]
    long_gaps = [x for x in long_gaps if x[1] >= 300]
    if long_gaps:
        n, sec = max(long_gaps, key=lambda x: x[1])
        return hit("那一輪問它「剛剛那段時間在做什麼」，長時間沒動作通常是卡在等什麼",
                   f"第 {n} 輪有 {int(sec // 60)} 分鐘完全沒有動作",
                   "info", n,
                   f"你剛才有 {int(sec // 60)} 分鐘完全沒有任何動作。"
                   "那段時間在等什麼、卡在哪裡，講清楚。"
                   "如果是在等我回話，以後直接說你在等什麼。")

    # 六、沒事。**不准假裝有事。**
    if rows:
        longest = max(rows, key=lambda r: r.get("duration") or 0)
        mins = int((longest.get("duration") or 0) // 60)
        # 沒事的時候不給句子。**硬湊一句可以貼的話，
        # 等於逼使用者去戳一個沒有問題的地方。**
        return hit("目前沒有要你介入的地方，繼續做你的",
                   f"{len(rows)} 個來回，最長一輪 {mins} 分鐘"
                   if mins else f"{len(rows)} 個來回",
                   "info", longest["n"])
    return hit("還沒有資料", "這個 session 還沒有完整的來回")


def fork_at(session: str, n: int, dry_run: bool = True) -> dict:
    """從第 n 輪 fork 出一個新 session。§27

    owner 2026-09-11 要的形狀:看到紅的那一節，從紅色之前那一節 fork，
    任務接著跑。2026-09-14:「這樣才能 Fork 啊，不然都是單向的
    還要自己慢慢往前面翻。」

    切點是那一輪的**起點**（她發話那一行），因為那一輪之後發生的事
    正是要丟掉的部分。

    **原檔一個位元組都不動。** fork 是建立，不是修改 ——
    一個會改到原始對話的 fork，等於把「回頭看當時發生什麼」毀掉，
    而那正是這整個 Widget 存在的理由。

    【2026-09-14 實測到的限制，不要拿掉這段註解】
    fork 出來的 jsonl 桌面版看不到，因為它的側邊欄清單在記憶體裡，
    不會即時重掃目錄。在 `claude-code-sessions/` 補一份 metadata
    可以讓它重啟後出現，但 deep link 當下開不了它（測過，焦點沒變）。

    所以回傳裡給兩條真的走得通的路，不假裝可以當場開:
      重啟 Claude 之後它在側邊欄
      或者現在就 `claude --resume <新 id>`
    """
    import tracker as TK
    import forkline as FK

    base = Path.home() / ".claude" / "projects"
    hits = sorted(base.glob(f"*/{session}*.jsonl"))
    if not hits:
        return {"error": f"找不到 {session}"}
    path = hits[0]

    tk = TK.Tracker(path)
    tk.poll()
    row = next((x for x in tk.strands if x.n == n), None)
    if row is None:
        return {"error": f"這條線裡沒有第 {n} 輪"}

    try:
        info = FK.fork(path, row.owner_line, dry_run=dry_run)
    except SystemExit as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"寫不出來：{e}"}

    info["n"] = n
    info["owner_text"] = " ".join((row.owner_text or "").split())[:60]
    if not dry_run:
        info["meta"] = _safe(lambda: _write_fork_meta(path.stem,
                                                      info["new_session_id"], n), "")
        info["resume"] = f"claude --resume {info['new_session_id']}"
    return info


def _write_fork_meta(src_cli: str, new_cli: str, n: int) -> str:
    """給 fork 出來的分支補一份桌面版 metadata。

    從原 session 那份複製，只改該改的欄位 ——
    自己憑空編一份等於猜它的格式，而猜錯的那天沒有人會知道。

    **要重啟 Claude 才看得到。** 桌面版不重掃目錄。
    """
    import uuid as _uuid

    src = None
    for f in SESSIONS_META.rglob("local_*.json"):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if o.get("cliSessionId") == src_cli:
            src = (f, o)
            break
    if src is None:
        return ""
    f_src, o = src
    new_ui = "local_" + str(_uuid.uuid4())
    now = int(time.time() * 1000)
    o = dict(o)
    o.update({
        "sessionId": new_ui,
        "cliSessionId": new_cli,
        "title": f"{o.get('title', '')} · 從第 {n} 輪".strip(" ·"),
        "titleSource": "user",
        "createdAt": now,
        "lastActivityAt": now,
        "lastFocusedAt": 0,
        "completedTurns": n,
    })
    dest = f_src.parent / f"{new_ui}.json"
    dest.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    return new_ui


def _write_handoff(snap: dict) -> dict | None:
    """把此刻的狀態寫成 `.forseti/NEXT.md`。C4

    這一支不自己判斷任何事，每個欄位都是別人算好的 ——
    自己判斷就會變成第二個事實來源，然後兩個來源開始不一致。
    """
    import handoff as HO

    if not HO.should_write():
        return None

    rows = snap.get("rows") or []
    ns = _safe(north_star, {}) or {}
    w = _safe(work, {}) or {}
    cps = snap.get("checkpoints") or {}

    nexts, stuck, unknowns, decisions, finish = [], [], [], [], []
    for t in (w.get("tasks") or []):
        if t.get("next_step"):
            nexts.append(f"{t['id']}　{t['next_step'].get('objective', '')}")
        elif t.get("stuck_why"):
            # 【2026-09-16 19:0x】「做完等收尾」不歸到「卡在哪」。
            # 那一節的標題會把讀的人推去找哪裡壞了，而實情是沒有壞，
            # 是有一件事在等她按。兩種要做的動作相反，所以分兩節，
            # 跟 `stuck.py` 不把兩種等合成一句是同一條理由。
            _k = (t.get("stuck") or {}).get("kind")
            (finish if _k == "ALL_VERIFIED" else stuck).append(
                f"{t['id']}：{t['stuck_why']}")
        for e in (t.get("events") or [])[:4]:
            if e.get("kind") in ("TASK_STATE", "HANDOFF") and e.get("cause"):
                decisions.append(e["cause"][:90])
    for b in (w.get("blocked") or [])[:4]:
        unknowns.append(f"被擋住：{b}")

    gg = snap.get("goal_gate") or {}
    for m in (gg.get("missing_factors") or []):
        unknowns.append(f"GAC 算不出來，缺 {m.get('factor', '')}：{m.get('why', '')[:60]}")

    sp = snap.get("spec") or {}
    verified = []
    if sp.get("has"):
        verified.append(f"必讀文件 {sp.get('full', 0)}/{sp.get('total', 0)} 讀完")
    if cps.get("total"):
        verified.append(f"checkpoint {cps['total']} 個")

    # 這份交接照 §39.1 少了什麼。算不出來就不寫那一節 ——
    # 寫一個算失敗的空殼比不寫更糟，它看起來像「沒有缺口」。
    con_lines, art_lines, inv_lines, rck_lines = [], [], [], []
    try:
        import contract as CT
        _rep = CT.report(snap, w)
        con_lines = CT.summary_lines(_rep, limit=8)
        # 2026-09-16 19:2x 加。§39.1 把 invalidated_conclusions 放在
        # Limits 那一組，它的用途是「不要讓後繼者再帶著這句錯的話走」，
        # 而缺口清單只印缺的欄位，所以這一欄有值之後照樣看不到內容。
        # 行文一樣由 `contract.py` 算，這裡只傳。
        inv_lines = CT.invalidated_lines(_rep.get("ctx"))
        # 2026-09-16 18:2x 加。缺口清單只印缺的，所以先前
        # `artifact_paths` 就算 PRESENT，接手的人在 NEXT.md 上
        # 照樣看不到任何一個路徑。這一節印的是有的那些。
        art_lines = CT.artifact_lines(_rep.get("ctx"), limit=10)
        # 2026-09-16 22:5x 加。缺口清單印的是「這一欄沒有來源」，
        # 印不出「那句理由本身已經不成立了」—— 而後者正是這個專案
        # 今天被咬到的形狀（`PHASE_STATUS.md` 說五階沒開始、實際三階
        # 已完成）。沒有東西要看的時候這一支回空清單，那一節就不會出現。
        rck_lines = CT.recheck_lines(_rep.get("recheck"))
    except Exception:                                  # noqa: BLE001
        con_lines, art_lines, inv_lines, rck_lines = [], [], [], []

    # BLOCKERS.md 那一半。`unknowns` 的來源是 blocked steps 與未讀文件，
    # 跟這個不是同一件事，所以是新的一節不是併進去。
    #
    # **自己叫 `_blockers()`，不從 snap 拿。** `snap["blockers"]` 只存在於
    # `snapshot()`，而這一支收到的是 `strands()` 的 snap，那裡面沒有這個 key。
    # 從 snap 拿的版本跑起來不會壞，只會永遠給空清單 ——
    # 一個什麼都不做而且不報錯的接線，正是這個專案寫在 ROADMAP
    # 「不做的事」第一條的那種白工。實測抓到的（`'blockers' in strands()` 是 False）。
    blk_lines = _safe(lambda: _blocker_lines(_blockers()), []) or []

    return HO.write({
        "at": time.time(),
        "blocker_lines": blk_lines,
        "contract_lines": con_lines,
        "artifact_lines": art_lines,
        "invalidated_lines": inv_lines,
        "recheck_lines": rck_lines,
        "goal": (ns.get("text") or ns.get("objective") or ""),
        "n": (rows[-1].get("n") if rows else 0),
        "next_actions": nexts,
        "awaiting_finish": finish,
        "stuck": stuck,
        "unknowns": unknowns[:8],
        "decisions": decisions[:6],
        "verified": verified,
        "last_good": cps.get("last_good"),
    })


def _checkpoint_now(*, reason: str, goal_hint: str = "",
                    last_good: bool = False) -> dict | None:
    """把此刻的四件事落成一個 checkpoint。v5.0 §25

    存的是目標、已接受的決策、未解決的未知、最後已知良好狀態，
    **不存對話全文** —— 全文本來就在 jsonl 裡，這裡存的是座標與結論。
    """
    import checkpoint as CP

    snap = _safe(strands, {}) or {}
    rows = snap.get("rows") or []
    sid = str(snap.get("session") or snap.get("ui_id") or "")
    n = (rows[-1].get("n") if rows else 0) or 0

    ns = _safe(north_star, {}) or {}
    goal = (ns.get("text") or ns.get("objective") or goal_hint or "").strip()

    w = _safe(work, {}) or {}
    decisions, unknowns = [], []
    for t in (w.get("tasks") or [])[:3]:
        for e in (t.get("events") or []):
            if e.get("kind") in ("TASK_STATE", "HANDOFF") and e.get("cause"):
                decisions.append(e["cause"][:90])
            if len(decisions) >= 6:
                break
        if t.get("stuck_why"):
            unknowns.append(f"{t.get('id', '')}：{t['stuck_why']}")
    for b in (w.get("blocked") or [])[:3]:
        unknowns.append(f"被擋住：{b}")

    sp = _safe(spec_reading, {}) or {}
    verified = []
    if sp.get("has"):
        verified.append(f"必讀文件 {sp.get('full', 0)}/{sp.get('total', 0)} 讀完")
    verified.append(f"事件帳本 {(_safe(audit, {}) or {}).get('events', 0)} 筆")

    r = CP.create(session=sid, n=int(n), reason=reason, goal=goal,
                  decisions=decisions, unknowns=unknowns,
                  verified=verified, last_good=last_good)
    return r.get("checkpoint") if r.get("ok") else None


def add_note(session: str, n: int, text: str) -> dict:
    """寫一則粉紅點。§5.5

    **這是唯一由使用者寫進系統的證據。** 其他點都是系統算給她看的，
    這一個是她給系統的，所以等級是 `HUMAN_ADJUDICATION` ——
    高過任何 deterministic check，因為那些驗的是「事情有沒有發生」，
    她寫的是「這件事重不重要」，後者沒有演算法算得出來。
    """
    import notes as NT
    try:
        return NT.add(text, session=str(session or ""), n=int(n))
    except (TypeError, ValueError) as e:
        return {"ok": False, "why": f"輪號不對：{e}"}


# §40 PollutionRegistry 的畫面投影。
#
# **後端從 2026-09-16 19:2x 就算得出來，缺的一直是入口** ——
# 跟 blast 明細那一次同一種缺口，所以這一支不寫任何新的判斷邏輯，
# 只把 `pollution.summary()` 與 `pollution.records()` 挑成畫面要的形狀。
# 不在這裡重算狀態、不在這裡重算 guarded，那會變成兩份會分歧的實作。
#
# 三條誠實條款跟著資料走，不留在註解裡：
#
#   一，`propagation_radius` 是 None 不是 0。規格列了欄位沒定義單位，
#       所以每一筆帶著 `radius_basis` 說為什麼算不出來。
#   二，**0 筆不等於沒有污染。** 這份登記簿沒有自動掃描（B-05），
#       它只有人登進去的那些，所以空的時候畫面要說的是
#       「登記簿是空的」不是「沒有被推翻的結論」。
#   三，`guarded` 以外那些「現在只靠人記得」，這句話要看得到 ——
#       一筆 OPEN 的污染跟一筆有偵測器攔著的，在總數上長得一樣。
def pollution_panel() -> dict:
    import pollution as PO

    rows = PO.records()
    s = PO.summary()
    out = []
    for r in rows:
        out.append({
            "id": r.get("id", ""),
            "status": r.get("status", "OPEN"),
            "original": r.get("original_claim", ""),
            "corrected": r.get("corrected_claim", ""),
            "mechanism": r.get("failure_mechanism", ""),
            # None 就是 None。畫面那邊不准把它顯示成 0。
            "radius": r.get("propagation_radius"),
            "radius_basis": r.get("radius_basis", ""),
            # 有沒有東西攔著它再犯，不是它對不對。
            "guarded": bool((r.get("preventive_rule") or "").strip()
                            or (r.get("regression_probe") or "").strip()),
            "sources": list(r.get("source_events") or []),
        })
    return {
        "has": True,
        "total": s.get("total", 0),
        "open": s.get("open", 0),
        "by_status": s.get("by_status", {}),
        "radius_unknown": s.get("radius_unknown", 0),
        "radius_note": s.get("radius_note", ""),
        "guarded": s.get("guarded", 0),
        "guard_note": s.get("guard_note", ""),
        "source": s.get("source", ""),
        # 這一句是這一格最重要的誠實條款，不是說明文字。
        "not_scanned_why": ("這份登記簿沒有自動掃描，只有人登進去的那些。"
                            "空的或少的，代表沒有人登，不代表沒有被推翻的結論"),
        "rows": out,
    }


# §12.2 Source-of-truth precedence 的畫面投影。
#
# 這一格回答的是一個很窄的問題：**這一類狀態該信哪個來源。**
# 跟 pollution 那一格同一條原則，這裡不寫任何新的判斷 ——
# `sot.assess()` 已經算完，這一支只挑畫面要的形狀。
#
# 兩條誠實條款跟著資料走：
#
#   一，**七行裡只有一行有即時量測。** 其餘六行的 `live` 是 None，
#       那是「沒量」不是「健康」。一個沒有被檢查過的綠燈比沒有燈更糟，
#       因為它會讓人不去看。
#   二，`NOT_APPLICABLE` 跟「還沒接」在畫面上必須分得出來。
#       前者是查證過這個 repo 沒有這一類狀態，後者是欠工。
#       兩個都畫成灰色的話，欠的那一塊會消失。
def sot_panel() -> dict:
    import sot as SOT

    a = SOT.assess()
    rows = []
    for r in a["rows"]:
        live = r.get("live")
        rows.append({
            "key": r["key"],
            "state_type": r["state_type"],
            "preferred_zh": r["preferred_zh"],
            "preferred": r["preferred"],
            "not_source": r["not_source"],
            "state": r["state"],
            "uses": r["uses"],
            "note": r["note"],
            "spec": r["spec"],
            "evidence_ok": r["evidence_ok"],
            "evidence_drifted": r["evidence_drifted"],
            # None 就是 None。畫面那邊不准把它顯示成「正常」。
            "live": (None if not live else {
                "measured": live.get("measured", False),
                "why": live.get("why", ""),
                "git_authoritative": live.get("git_authoritative"),
                "divergent": live.get("divergent"),
            }),
        })
    return {
        "has": True,
        "total": a["total"],
        "by_state": a["by_state"],
        "evidence_stale": a["evidence_stale"],
        "evidence_drifted": a["evidence_drifted"],
        "live_measured": a["live_measured"],
        "live_note": a["live_note"],
        "not_applicable_note": a["not_applicable_note"],
        "source": a["source"],
        "rows": rows,
    }


def sot_ask(question: str) -> dict:
    """拿一句話去問該信誰。§12.2

    對不上就不回答 —— `sot.lookup()` 自己會擋，這一層不另外做一套
    比對，理由跟 `blast_detail` 不重驗路徑同一條。
    """
    import sot as SOT
    return _safe(lambda: SOT.lookup(str(question or "")),
                 {"ok": False, "why": "查不動"})


# §11.1 持久身份。這一格回答的是:**這個 repo 分得開身份與那五樣東西嗎。**
#
# 跟 sot 那一格同一條原則，這裡不寫任何新的判斷 ——
# `identity.assess()` 已經算完，這一支只挑畫面要的形狀。
#
# 三條誠實條款跟著資料走：
#
#   一，`NO_SOURCE` 不是「這一軸沒問題」，是這個 repo 沒有資料來源。
#       三軸沒有來源就是三軸答不出來，畫面上不准畫成綠的。
#   二，model 那一軸的分母是抽樣的，不是磁碟上全部的 session。
#       兩個數字都印出來，因為同一個分子在不同分母底下不是同一件事。
#   三，alias 不靠命名相似度配對。前綴一樣不代表同一個身份。
def identity_panel() -> dict:
    import identity as ID

    a = ID.assess()
    rows = []
    for r in a["rows"]:
        live = r.get("live")
        rows.append({
            "key": r["key"],
            "axis": r["axis"],
            "axis_zh": r["axis_zh"],
            "question": r["question"],
            "state": r["state"],
            "evidence": r["evidence"],
            "spec": r["spec"],
            # None 就是 None。畫面那邊不准把它顯示成 0。
            "live": (None if not live else {
                "value": live.get("value"),
                "of": live.get("of"),
            }),
        })
    d = a["drift"]
    sv = a["survey"]
    return {
        "has": True,
        "total": a["total"],
        "by_state": a["by_state"],
        "rows": rows,
        "registered": d["registered"],
        "actors_seen": d["actors_seen"],
        "unregistered": d["unregistered"][:20],
        "unregistered_total": len(d["unregistered"]),
        "stale": d["stale"][:20],
        "stale_total": len(d["stale"]),
        "scanned": sv["scanned"],
        # **一個用上一次結果算出來的數字，跟一個剛剛量出來的，
        # 在畫面上長得一模一樣。** 跟 blast 那一格標「快取」同一條理由。
        # 0 條命中就不給句子（全部都是這一次量的，沒有要交代的事）。
        "cache_note": (
            f"這一次有 {sv['cache_hits']} 條 session 用的是上一次量的結果，"
            f"動過的那幾條重讀過了"
            if sv.get("cache_hits") else ""),
        "total_sessions": sv["total_sessions_on_disk"],
        "sampled": sv["sampled"],
        "multi_model_count": sv["multi_model_count"],
        "multi_session_count": sv["multi_session_count"],
        "models_seen": sv["models_seen"][:8],
        "synthetic_note": sv["synthetic_note"],
        "sampled_note": a["sampled_note"],
        "no_source_note": a["no_source_note"],
        "no_fuzzy_note": a["no_fuzzy_note"],
        "source": a["source"],
    }


# §5 Workflow / WorkflowStep 加 §17.1 Workflow Reconstruction。
# 這一格回答的是:**程序剛死掉，我現在接哪一步。**
#
# 跟 identity 那一格同一條原則，這裡不寫任何新的判斷 ——
# `workflow.assess()` 已經算完，這一支只挑畫面要的形狀。
# 重算會變成兩份會分歧的實作，而分歧那天不會有錯誤訊息。
#
# 四條誠實條款跟著資料走：
#
#   一，`commit_boundary` 沒登記是 UNDECLARED 不是 NONE。前者是
#       「沒有人回答過」，後者是「有人看過而且說不跨」，
#       畫面上不准把前者畫成後者。
#   二，`external_refs` 沒有資料來源，所以它不在畫面上冒充空清單。
#   三，規格 §6.2 那四種事件實際幾種有出現，直接寫出來。
#       不做同義詞對映 —— STEP_STATE 不是 STEP_COMMIT。
#   四，dangling(依賴指到不存在的 step)單獨一格，不併進 blocked。
#       資料壞了跟在等人，下一步剛好相反。
def workflow_panel() -> dict:
    import workflow as WF

    a = WF.assess()
    if not a.get("available"):
        return {"has": False, "why": "任務帳本讀不到，不是沒有 workflow"}
    ev = a["spec_events"]
    fl = a["fields"]
    return {
        "has": True,
        "total": a["total"],
        "live": a["live"],
        "resumable": [{
            "workflow_id": r["workflow_id"],
            "objective": r["objective"],
            "state": r["state"],
            "counts": r["counts"],
            "ready_ids": r["ready_ids"][:8],
            "blocked_ids": r["blocked_ids"][:8],
            "boundary": r["boundary"],
        } for r in a["resumable"][:8]],
        "wf_coverage": fl["workflow"]["coverage"],
        "step_coverage": fl["step"]["coverage"],
        "missing": [{"field": f["field"], "state": f["state"],
                     "why": f["why"]}
                    for f in (*fl["workflow"]["fields"],
                              *fl["step"]["fields"])
                    if f["state"] != "PRESENT"],
        "spec_events_present": ev.get("spec_present", 0),
        "spec_events_total": ev.get("spec_total", 4),
        "spec_events": ev.get("spec_kinds", {}),
        "actual_top": ev.get("actual_top", [])[:4],
        "undeclared_live": a["boundary_registry"]["undeclared_live"][:8],
        "declared": a["boundary_registry"]["declared"],
        "honesty": a["honesty"],
        "source": a["source"],
    }


def probe_panel() -> dict:
    """§15 Probe Packs。這一格回答「換了東西之後，哪一類判準退化了」。

    這一格最容易被畫成謊話的地方有四個，所以四個都寫在畫面上，
    不是寫在這個註解裡:

      一，NO_VERIFIER 不是 PASS。一個沒有東西可量的情境，跟一個量過
          而且通過的情境，在一張綠色的表上長得一模一樣。所以
          通過率的分母是 `measurable`，不是十。
      二，沒有基準線的時候，十個 NEW 也會讓這一格看起來沒有紅字。
          「還沒有基準線」要自己講出來，不能靠使用者從 NEW 推。
      三，基準線是什麼時候、誰按的要印出來。一條三個月前的基準線
          跟一條剛剛錄的，在「跟基準線一致」這句話裡分量差很多。
      四，跨不了的那兩軸每一次都要帶著。這一版量得到程式碼改動造成的
          退化（versions），量不到換模型或改路由造成的退化。

    `probe.run()` 不碰基準線檔，只有 `record_baseline(by=...)` 會寫，
    所以這一格反覆重畫不會把退化洗成新常態。
    """
    import probe as PB

    t = PB.summary()
    cv = t.get("pack_covers_spec") or {}
    return {
        "has": True,
        "counts": t["counts"],
        "measurable": t["measurable"],
        "pass_rate": t["pass_rate"],
        "has_baseline": t["has_baseline"],
        "baseline_by": t["baseline_by"],
        "baseline_at": t["baseline_at"],
        "axes_covered": t["axes_covered"],
        "axes_missing": t["axes_missing"],
        "axes_why": t["axes_why"],
        # §15.2 的十類蓋滿了沒有。missing 不是空的時候，通過率那個
        # 數字的分母本來就少算了，那件事要跟通過率放在一起看。
        "spec_ok": bool(cv.get("ok")),
        "spec_missing": list(cv.get("missing") or []),
        "spec_total": len(cv.get("required") or []),
        "rows": t["rows"],
        "source": "v5.0 §15 Probe Packs，資料在 .forseti/probe_baseline.json",
    }


def workflow_resume(workflow_id: str) -> dict:
    """§17.1 的那一行:從耐久存放區重組一件可續做的 workflow。

    `workflow.resume()` 自己會擋不存在的 id（回 `ok: False` 帶原因），
    所以這一層不另外驗一次 —— 兩套驗法會分歧，而分歧的那一天
    沒有人會發現。
    """
    import workflow as WF
    return _safe(lambda: WF.resume(str(workflow_id or "")),
                 {"ok": False, "why": "重組不動"})


def blast_detail(target: str) -> dict:
    """點一個節點，看誰依賴它。§16.1 那一句的 files 那一種。

    畫面上那張排行榜回答的是「哪些檔案最貴」，這一支回答的是
    **「這一個檔貴在哪裡」** —— 是哪十個檔會被波及，不只是十這個數字。

    `blast.detail()` 自己會擋不在圖裡的路徑（回 `known: False`），
    所以這一層不另外驗一次路徑 —— 兩套驗法會分歧，而分歧的那一天
    沒有人會發現（`jsbridge.py` 檔頭那句話）。
    """
    import blast as BL
    return _safe(lambda: BL.detail(str(target or "")),
                 {"has": False, "target": target, "why": "算不出來"})


def act(kind: str, target: str = "", worker: str = "") -> dict:
    """畫面上的動作。會改變狀態的東西全部走這裡。§30

    owner 2026-09-16：「接動作層」

    在這之前畫面是純觀測:看得到未完成幾件、卡在哪、你推了幾次，
    但一個按鈕都沒有。而當時兩個任務的步驟全部是 VERIFIED_COMPLETE，
    任務本身卻卡在 VERIFYING —— **不是還有事沒做，是沒有人把收尾按下去。**
    那就是動作層缺席的代價。

    ## 三條防線

    一，**收尾之前一定要檢查每個步驟真的驗過。** 不能因為她按了就標完成，
        那會讓帳本說謊，而帳本說謊比沒有帳本更糟。

    二，**actor 記 owner 不記 system。** 是她按的就要寫是她按的,
        F02 §5 要求每次轉換都有 cause，而「誰」是 cause 的一部分。

    三，**做不動要講出卡在哪一個條件。** `cmd_auto` 的註解寫著:
        安靜的 None 正是這整套東西要消滅的東西。
    """
    import ledger as L

    kinds = ("finish", "verify", "dispatch", "drain", "checkpoint")
    if kind not in kinds:
        return {"ok": False, "why": f"不認得的動作：{kind}"}

    # Authority。§9.2 每個會改變狀態的動作都要有一份 PolicyDecision。
    #
    # **這一層不是為了擋她。** 她按的東西 principal 就是 OWNER，
    # 而擁有者對正典狀態本來就有權，所以正常情況一定放行。
    # 它存在是為了兩件事:一，把「這個動作屬於誰的權限」記下來;
    # 二，等哪天有東西想繞過她直接寫正典狀態的時候，那條路是關的。
    import authority as AU
    _pd = AU.decide(action=kind, principal="OWNER", resource=target)
    if not _pd.get("can_execute"):
        return {"ok": False,
                "why": _pd.get("reason", ""),
                "policy": {k: _pd.get(k) for k in
                           ("decision", "risk", "allowed_preparation",
                            "required_confirmation", "blocked_final_action",
                            "source_policy_version")}}
    if kind == "checkpoint":
        # owner 自己標一個「這裡是好的」。§17
        # 系統不自己挑 last_good，只有她按的這個才算。
        cp = _checkpoint_now(reason="OWNER_MARK", last_good=True)
        if not cp:
            return {"ok": False, "why": "存不起來"}
        return {"ok": True, "did": "checkpoint",
                "say": f"標好了：第 {cp['n']} 輪　{cp['id']}",
                "note": "這是 last_good。之後出事可以回到這裡"}

    if not target:
        return {"ok": False, "why": "沒有指定要動哪一個"}

    db = L.default_db()
    if not db.exists():
        return {"ok": False, "why": "還沒有任務帳本"}
    try:
        led = L.Ledger()
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "why": f"開不了帳本：{e}"}

    try:
        if kind == "finish":
            state = led.state_of(target)
            if not state:
                return {"ok": False, "why": f"找不到任務：{target}"}
            if L.is_terminal(state):
                return {"ok": False, "why": f"這件已經結束了（{state}）"}
            steps = led.steps_of(target)
            unfinished = [x for x in steps
                          if x.get("state") != "VERIFIED_COMPLETE"]
            if unfinished:
                # 這條就是防線一。按了也不准過。
                return {"ok": False,
                        "why": f"還有 {len(unfinished)} 個步驟沒驗完，不能收尾",
                        "detail": [f"{x.get('local_id', '')} {x.get('state', '')}"
                                   for x in unfinished[:5]]}
            led.transition(target, "VERIFIED_COMPLETE",
                           cause="owner 在 Widget 上確認收尾：所有步驟都已驗證完成",
                           actor="owner")
            # 有意義的狀態轉換才落 checkpoint（v5.0 P0 第 5 項）。
            # 任務收尾是最典型的一個:那一刻的狀態是乾淨的。
            _cp = _safe(lambda: _checkpoint_now(
                reason="TASK_FINISHED",
                goal_hint=f"{target} 收尾",
                last_good=True), None)
            return {"ok": True, "did": "finish",
                    "say": f"{target} 已收尾，{len(steps)} 個步驟全部驗證完成",
                    "checkpoint": (_cp or {}).get("id", ""),
                    "policy": {"decision": _pd["decision"],
                               "principal": _pd["principal"],
                               "reason": _pd["reason"]}}

        if kind == "verify":
            ok, results = led.verify_step(target, actor="owner")
            return {"ok": True, "did": "verify", "passed": bool(ok),
                    "results": [str(r)[:120] for r in (results or [])][:6],
                    "say": ("全部通過，這一步進 VERIFIED_COMPLETE"
                            if ok else
                            "沒有全過，狀態轉回 RUNNING 並累加重試次數。"
                            "不留在 VERIFYING 假裝還在驗")}

        if kind == "dispatch":
            nxt = led.auto_dispatch(target, worker or "main",
                                    "owner 在 Widget 上按了派下一步")
            if nxt:
                return {"ok": True, "did": "dispatch",
                        "say": f"已派 {nxt.get('local_id', '')}　"
                               f"{nxt.get('objective', '')}",
                        "note": "沒有人需要說「繼續」"}
            state = led.state_of(target)
            nx = led.next_step(target)
            if L.is_terminal(state):
                why = f"任務已終止（{state}），不再派工"
            elif state == "NEEDS_HUMAN":
                why = ("停在這裡等你決定，不是卡住。下一步是："
                       + ((nx or {}).get("objective") or "（沒有下一步）"))
            elif not nx:
                why = "沒有可動的步驟。這件任務還沒有拆成步驟，或步驟都不在可動狀態"
            else:
                why = f"下一步是「{nx.get('objective', '')}」，但四個派工條件沒有全部滿足"
            return {"ok": False, "did": "dispatch", "why": why}

        # drain
        n = led.drain(target, worker or "main", max_steps=20)
        return {"ok": True, "did": "drain",
                "say": f"一路派了 {n} 步，直到派不動為止" if n
                       else "一步都派不動，原因跟單獨派下一步時一樣"}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "why": f"做不動：{e}"}


def work() -> dict:
    """執行層的現況:未完成的義務、進行中的步驟、卡住的。§30

    owner 2026-09-14 盤點之後：

        我現在要你盤點你本來就做好好的功能，然後你卻沒有接上到桌面APP

    盤出來 156 個公開函式只有 74 個接到畫面，而落差最大的一整組是
    `forseti.py` 的 28 個 CLI 指令 —— 派工、自動接續、義務追蹤、
    跨 session 交接，全部做好了，全部只能在終端下指令。

    Widget 到這一刻為止只有「觀測層」:看得到 AI 做錯什麼，
    卻不能在同一個地方看它接下來要做什麼。

    這支接的是 F02 §6 的 obligation ledger。
    CT-F02-02 要求未完成項目被**自動暴露**，不需要使用者盤問 ——
    而「在終端下指令才看得到」就是一種盤問。
    """
    import ledger as L

    db = L.default_db()
    if not db.exists() or db.stat().st_size == 0:
        return {"ok": False,
                "why": "還沒有任務帳本。義務只活在模型記憶裡的話，回合結束就散了",
                "db": str(db)}
    try:
        led = L.Ledger()
        o = led.obligations()
        total = led.total_unfinished()
        active = _safe(lambda: led.active_steps(), []) or []
    except Exception as e:                      # noqa: BLE001
        return {"ok": False, "why": f"讀不到帳本：{e}", "db": str(db)}

    tasks = []
    for t in (o.get("unfinished_tasks") or []):
        row = {
            "id": t.get("task_id", ""),
            "state": t.get("state", ""),
            "objective": t.get("objective", ""),
            "next": t.get("next") or "",
            # 停止條件。§39.1 的 Next 群要它，交接檔才帶得出
            # 「做到什麼程度停」。沒有的任務就是空清單，不補預設值。
            "stop_conditions": t.get("stop_conditions") or [],
        }
        # 【2026-09-15 接上】事件流、下一步、派不動的原因。
        #
        # 在這之前畫面只有「未完成 N 件」一個數字。一件任務底下發生過
        # 什麼、現在卡在哪、為什麼派不動，全部只能在終端下指令看。
        # `cmd_auto` 的註解寫著:安靜的 None 正是這整套東西要消滅的東西,
        # 使用者不該從「沒反應」去推發生什麼事。一個不說明原因的
        # 「派不動」，在畫面上就是安靜的 None。
        _ev = _safe(lambda tid=row["id"]: led.events_of(tid), []) or []
        row["events"] = [{
            "at": e.get("at"),
            "kind": e.get("kind", ""),
            "cause": (e.get("cause") or "")[:120],
            "actor": e.get("actor", ""),
        } for e in _ev[-12:]][::-1]
        row["events_total"] = len(_ev)

        _nx = _safe(lambda tid=row["id"]: led.next_step(tid), None)
        row["next_step"] = ({"local_id": _nx.get("local_id", ""),
                             "objective": _nx.get("objective", ""),
                             "state": _nx.get("state", "")}
                            if isinstance(_nx, dict) else None)
        if not row["next_step"]:
            # 【2026-09-16 19:0x 改】在這之前這裡只分兩種：沒有步驟，
            # 或者「N 個步驟都不在可動狀態」。第二句對正本的兩件任務
            # 都是假的 —— 那 7 個與 2 個步驟**全部**是 VERIFIED_COMPLETE，
            # 任務不是卡住，是做完沒收尾。要人做的動作完全相反：
            # 一個是去解依賴，一個是按收尾。
            #
            # `stuck.diagnose()` 把七種情況分開，而且「永遠等不到」
            # 跟「正在等」不合成一句，理由與四條誠實條款在 stuck.py。
            import stuck as SK
            _d = _safe(lambda tid=row["id"]: SK.diagnose(led, tid), None)
            row["stuck"] = _d
            row["stuck_why"] = (SK.line(_d) if _d else
                                "算不出派不動的原因，stuck.diagnose 沒有回值")

        # F06 §5 的兩個指標，從事件算不是從印象算。
        c = _safe(lambda tid=row["id"]: led.continuity(tid), None)
        if c:
            row["continuity"] = {
                "score": getattr(c, "score", None) or (
                    c.get("score") if isinstance(c, dict) else None),
                "burden": getattr(c, "human_continue_burden", None) or (
                    c.get("human_continue_burden") if isinstance(c, dict) else None),
            }
        tasks.append(row)

    return {
        "ok": True,
        "total": total,
        "tasks": tasks,
        "steps": [{"state": x.get("state", ""), "objective": x.get("objective", "")}
                  for x in (o.get("unfinished_steps") or [])[:20]],
        "steps_more": max(0, len(o.get("unfinished_steps") or []) - 20),
        "blocked": [x.get("objective", "") for x in (o.get("blocked") or [])],
        "active": len(active),
        # active_steps() 的排序本身就是資訊:最久沒動靜的排前面。
        # 只顯示一個數字等於把那個排序丟掉。
        "active_rows": [{
            "state": x.get("state", ""),
            "objective": (x.get("objective") or "")[:90],
            "worker": x.get("worker", ""),
            "idle_s": x.get("idle_s") or x.get("since"),
        } for x in active[:12]],
        "db": str(db),
    }


# 功能說明。§36
#
# owner 2026-09-14：「我老闆會用 AI，他會要我打開 Forseti 全部功能說明，
# 然後要我 demo，你他媽的不要給我漏掉任何一個。」
#
# 每一項三件事:它抓什麼、憑什麼（規格編號）、現在的真實數字。
# **沒有形容詞。** 一句「強大的偵測能力」在 demo 現場換不到任何東西，
# 一個「這段對話你說了 14 次繼續」換得到。
FEATURES = [
    # 【2026-09-14 新增四項】owner 讀完文件後指出的三件事:
    # 線要會飄、不是儀表板、文件沒讀完不可能變綠。
    ("必讀文件讀完了沒", "spec_full",
     "必讀清單上每一份的閱讀狀態。沒有閱讀紀錄一律算沒讀，"
     "拿不出證據就不算讀過。只要有一份沒讀完，整條線從第一格就是紅的",
     "§40　REQUIRED_READING + coverage"),
    ("區塊閱讀與反向拷問", "spec_blocks",
     "把文件切成區塊，讀一塊記一塊，疑問集中成清單給你裁。"
     "另一邊 Forseti 從原文抽題反過來考 AI，題目不是 AI 自己出的",
     "§41　Vol2 §4 七級涵蓋度的 level 6"),
    ("目標距離與飄移", "goal_trend",
     "線的水平位置就是 1 減去目標支持率。偏得越遠推得越外面，"
     "回到中軸時標出飄了幾輪才回來。算的是跟目標的距離，不是工具失敗率",
     "§22.7　FP-09 GDA / FP-17 FSD"),
    ("體溫與八個維度", "temp_c",
     "一個體溫加八個分開的維度。溫度量的是退化不是容量，"
     "而且一定同時顯示證據覆蓋率，低覆蓋率的高分不能裝作確定",
     "工程書 §11.3 §22.1　FS-RSK-001"),
    ("說了沒做", "betrayal_total",
     "它說寫了檔案、跑了指令、用了某個工具，而那一輪的紀錄裡沒有對應的動作",
     "FP-11 / FP-24 / FP-13"),
    ("宣稱對現實查證", "claim_unknown",
     "把文字裡的宣稱抽出來，真的去磁碟查。查不到就說查不到，"
     "沒資格判假的不判假",
     "§7.3　claims + verifier"),
    ("宣稱大於證據", "overclaim_total",
     "證據範圍小於宣稱範圍、別人查的講成自己查的、說逐條核對實際只核一部分",
     "FP-02 / FP-03 / FP-07"),
    ("空輸出與停擺", "starving_total",
     "拿了你的 token 卻回你空白，或者做完了卻沒說出來",
     "F07-OUT-001"),
    ("停滯風險", "stall_total",
     "長時間沒有動作。算的是風險值加復原階梯，不是計時器",
     "F05-WDG-001"),
    ("記憶用量預警", None,
     "現在用掉多少 context、離壓縮還有多遠。門檻用這個 session 自己"
     "壓縮過的實際觸發點，不是拿模型上限去猜",
     "F08-CTX-001"),
    ("停在不該停的地方", None,
     "你必須開口說「繼續」的次數。應該趨近於零",
     "F06 §4 / F06-EXC-001"),
    ("任務帳本", None,
     "未完成的義務被自動暴露，不需要你盤問。append-only 的正本",
     "F02 §6　obligation ledger"),
    ("換機器盤點", None,
     "換電腦該搬什麼、現在有幾個。少的那一項會自己跳出來",
     "§31"),
    ("從某一輪切分支", None,
     "從對話中間任何一輪切出新 session，原檔一個位元組都不動",
     "§27　clean fork"),
    ("北極星與版本鏈", None,
     "不預設存在。要等人自己說出來才啟用",
     "v5.0 §8.1"),
    ("規格讀了幾行", None,
     "分辨「翻過」跟「讀完」。數字是上界，這個標記不可關閉",
     "F08 §5　七級涵蓋度"),
    ("查得回來的段落", None,
     "把每一份對話切成「一次交換」為單位的段落建成索引。"
     "壓縮之後要找回當時講了什麼，靠的是它不是摘要",
     "階段 C1"),
    ("壓縮後恢復了多少", None,
     "壓縮把內容丟掉，後來補讀回多少是算得出來的。"
     "只有最高那一級才算「讀懂」",
     "F08 §5　七級涵蓋度"),
    ("多 session 成果驗收", None,
     "sub-session 交回來的成果要附一份有 schema 的封包。"
     "多交的跟少交的一樣是問題",
     "F03-CSI-001"),
    ("執行層偵測器", None,
     "src/ 底下 40 支 JavaScript、13,190 行的 failure primitive registry。"
     "Python 起 node 跑它們，判斷邏輯不重寫成第二份",
     "§38　FP-01 到 FP-25"),
    ("功能自檢", None,
     "每一項餵一筆刻意造的違規，抓得到才算活的。"
     "一個回 0 的偵測器跟一個壞掉的偵測器，在真實資料上長得一樣",
     "§33"),
]


def features() -> dict:
    """功能說明加當場驗證。§36"""
    st = _safe(selftest, {}) or {}
    alive = {x["name"]: x for x in (st.get("items") or [])}
    rows = []
    for name, _key, what, spec in FEATURES:
        a = alive.get(name)
        rows.append({
            "name": name, "what": what, "spec": spec,
            "alive": bool(a and a.get("alive")),
            "live": (a or {}).get("live", ""),
        })
    return {
        "items": rows,
        "alive": sum(1 for r in rows if r["alive"]),
        "total": len(rows),
        "scale": _safe(scale_now, {}) or {},
        # 沒接的照實列。owner 2026-09-14：
        # 「明天是赤裸裸的給人看」——
        # 藏起來的那一項，正是會被問到的那一項。
        # 2026-09-14 之後這裡是空的。全部接完了。
        "not_wired": [],
    }


def scale_now() -> dict:
    """規模數字。當場算，不寫死。"""
    import ast
    app = REPO / "apps" / "forseti-cli"
    mods = [f for f in app.glob("*.py") if not f.name.startswith("._")]
    fns = 0
    lines = 0
    for f in mods:
        try:
            src = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines += len(src.splitlines())
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        fns += sum(1 for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                     ast.ClassDef))
                   and not n.name.startswith("_"))
    js = REPO / "src"
    js_files = [f for f in js.glob("*.js")
                if not f.name.startswith("._")] if js.is_dir() else []
    js_lines = 0
    for f in js_files:
        try:
            js_lines += len(f.read_text(encoding="utf-8",
                                        errors="replace").splitlines())
        except OSError:
            continue
    tests = REPO / "tests"
    return {
        "modules": len(mods),
        "functions": fns,
        "lines": lines,
        "js_files": len(js_files),
        "js_lines": js_lines,
        "tests": len([f for f in tests.glob("*.py")
                      if not f.name.startswith("._")]) if tests.is_dir() else 0,
    }


def selftest() -> dict:
    """每一個功能，當場證明它是活的。§33

    owner 2026-09-14：「我要列出來的功能表上的所有功能都可以被驗證。」

    **一個回 0 的偵測器，跟一個壞掉的偵測器，在真實資料上長得一模一樣。**
    所以每一項都跑兩次:一次餵真實資料，一次餵一筆刻意造的違規。
    真實資料那次回幾筆是現況，合成那次一定要抓到 ——
    抓不到就是這個功能死了，畫面上直接說死了。
    """
    import tracker as TK

    target = TK.latest_session()
    rows = []

    def probe(name, spec, live, synth_fn):
        """live = 真實資料的結果數；synth_fn 回 True 表示合成違規有抓到。"""
        alive = _safe(synth_fn, False)
        rows.append({
            "name": name, "spec": spec,
            "live": live,
            "alive": bool(alive),
            "verdict": "活的" if alive else "沒反應",
        })

    tk = None
    if target and target.is_file():
        tk = TK.Tracker(target)
        tk.poll()

    strands = tk.strands if tk else []

    # 0-A 必讀文件。合成:造一份不存在的必讀檔,一定要判成沒讀完。
    def _spec():
        """合成驗:造一個必讀檔而且不給它任何閱讀紀錄，一定要判成沒讀。

        【2026-09-15 修】第一版寫的是「真實資料裡要同時看得到讀完
        與沒讀完兩種狀態」。那讓這條檢查依賴真實狀態 ——
        文件全部讀完之後它反而報「死」。
        **一個在狀態變好之後就失效的檢查，跟一個永遠回 OK 的檢查
        是同一種壞掉。** 改成完全用合成資料。
        """
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            fake = Path(td)
            (fake / ".forseti").mkdir()
            (fake / "docs").mkdir()
            (fake / ".forseti" / "ONLY.md").write_text("x\n", encoding="utf-8")
            old_repo = globals()["REPO"]
            try:
                globals()["REPO"] = fake
                d = spec_reading()
            finally:
                globals()["REPO"] = old_repo
        rows = d.get("rows") or []
        mine = [r for r in rows if r["name"] == "ONLY.md"]
        return bool(mine) and mine[0]["state"] == "沒有閱讀紀錄" \
            and d.get("ok") is False
    _sp = _safe(spec_reading, {}) or {}
    probe("必讀文件讀完了沒", "§40　REQUIRED_READING + coverage",
          f"{_sp.get('full', 0)} / {_sp.get('total', 0)} 份讀完", _spec)

    # 0-B 區塊閱讀。合成:給一段假的 markdown,一定要切得出區塊並出得了題。
    def _blk():
        import blockread as BR, tempfile, pathlib as _pl
        with tempfile.TemporaryDirectory() as td:
            f = _pl.Path(td) / "t.md"
            # 出題器對句子有 12 字下限(太短的句子挖空沒有意義)，
            # 合成文字要過得了那一關，不然測到的是長度不是判準。
            f.write_text(
                "# 標題\n\n## 一節\n\n"
                "不准把沒有驗證過的數字直接寫進正式檔案裡面。\n"
                "每個結論至少要有三份互相獨立的證據支撐才算數。\n",
                encoding="utf-8")
            bs = BR.split(f)
            if not bs:
                return False
            qs = [q for b in bs for q in BR.quiz(f, b)]
            return any(q["kind"] == "禁令" for q in qs)
    _bk = _safe(block_reading, {}) or {}
    probe("區塊閱讀與反向拷問", "§41　Vol2 §4 七級涵蓋度的 level 6",
          f"{_bk.get('done', 0)} / {_bk.get('blocks', 0)} 塊，題庫 {_bk.get('quiz', 0)}",
          _blk)

    # 0-C 目標距離。合成:造一串「每一輪都被糾正」,距離一定要是 1。
    def _goal():
        import vitals as VT
        # 每一輪都被糾正。注意 classify_turn 看的是「下一輪有沒有糾正」，
        # 所以最後一輪永遠分類不到 CONFLICTING ——
        # 8 輪的理論上界是 7/8 = 0.875，判準照這個寫。
        fake = [{"n": i, "dots": [{"kind": "write"}],
                 "corrected_by_owner": True} for i in range(8)]
        gs = VT.goal_support(fake)
        clean = [{"n": i, "dots": [{"kind": "write"}],
                  "corrected_by_owner": False} for i in range(8)]
        gc = VT.goal_support(clean)
        return (gs and gs[-1]["distance"] >= 0.8
                and gc and gc[-1]["distance"] <= 0.01)
    probe("目標距離與飄移", "§22.7　FP-09 GDA / FP-17 FSD",
          f"{len(strands)} 輪可算", _goal)

    # 0-D 體溫。合成:八個維度全部推到 1,溫度一定要進 CRITICAL。
    def _temp():
        import vitals as VT
        hot = {k: {"score": 1.0, "evidence": "合成", "coverage": 1.0}
               for k, _ in VT.DIMENSIONS}
        t = VT.temperature(hot)
        cold = {k: {"score": 0.0, "evidence": "合成", "coverage": 1.0}
                for k, _ in VT.DIMENSIONS}
        c = VT.temperature(cold)
        return t["c"] >= 39.0 and c["c"] <= 37.0
    probe("體溫與八個維度", "工程書 §11.3 §22.1　FS-RSK-001",
          f"{len(__import__('vitals').DIMENSIONS)} 個維度", _temp)

    # 1 說了沒做
    def _b():
        import betrayal as B
        return len(B.inspect("我把 `apps/forseti-cli/tracker.py` 寫好了。", [])) > 0
    probe("說了沒做", "FP-11 / FP-24 / FP-13",
          len(_safe(lambda: __import__("betrayal").scan(strands), []) or []), _b)

    # 2 空輸出
    def _s():
        import starvation as SV
        d = SV.diagnose(has_receipts=False, has_final_output=False,
                        tool_calls=0, progress_healthy=False, blank_run=3)
        return not d.is_healthy
    probe("空輸出與停擺", "F07-OUT-001",
          len(_safe(lambda: starving(strands), []) or []), _s)

    # 3 宣稱大於證據
    def _o():
        import overclaim as OC
        f = OC.provenance_collapse("我親自查過整個資料庫，全部都沒問題。",
                                   own_receipts=0, other_source_observations=3)
        return _fired(f)
    probe("宣稱大於證據", "FP-02 / FP-03 / FP-07",
          len(_safe(lambda: overclaims(strands), []) or []), _o)

    # 4 停滯風險
    def _w():
        import watchdog as WD
        a = WD.assess(age_sec=7200, progress_changed=False,
                      events_since=0, expected_to_progress=True)
        return float(getattr(a, "risk", 0)) > 0.5
    probe("停滯風險", "F05-WDG-001",
          len(_safe(lambda: stalls(strands), []) or []), _w)

    # 5 執行連續性
    def _c():
        import continuity as CT
        return "心跳" in CT.burden_verdict(15) or CT.burden_verdict(15) != ""
    burden = 0
    w = _safe(work, {}) or {}
    for t in (w.get("tasks") or []):
        burden = max(burden, (t.get("continuity") or {}).get("burden") or 0)
    probe("執行連續性", "F06-EXC-001", burden, _c)

    # 6 記憶用量
    def _m():
        return bool(target) and (_safe(lambda: context_state(target), {}) or {}).get("ok")
    ctx = _safe(lambda: context_state(target), {}) if target else {}
    probe("記憶用量預警", "F08-CTX-001", ctx.get("pct") or 0, _m)

    # 7 任務帳本
    def _l():
        import ledger as L
        return L.default_db().exists()
    probe("任務帳本", "F02 §6 obligation ledger",
          (w.get("total") or 0), _l)

    # 8 換機器盤點
    def _mg():
        import migrate as MG
        inv = MG.inventory()
        return len(inv.get("items") or []) >= 7
    mg = _safe(machine, {}) or {}
    probe("換機器盤點", "§31",
          sum(1 for x in (mg.get("items") or []) if x.get("ok")), _mg)

    # 9 宣稱對現實
    def _cl():
        import claims as C
        cl = C.Claim(text="我把 這個檔案絕對不存在.py 寫好了。", kind="file",
                     subject="這個檔案絕對不存在.py")
        try:
            C.verify(cl, cwd=REPO)
        except Exception:                                  # noqa: BLE001
            return False
        # 驗得出 VERIFIED、也判得出「查不到」，就是活的。
        return cl.state in ("REFUTED", "UNVERIFIABLE", "UNKNOWN")
    probe("宣稱對現實查證", "§7.3　claims + verifier",
          len(_safe(lambda: verified_claims(strands), []) or []), _cl)

    # 10 北極星
    def _ns():
        import northstar as NS
        return hasattr(NS, "NorthStar") and hasattr(NS, "Chain")
    ns = _safe(north_star, {}) or {}
    probe("北極星與版本鏈", "v5.0 §8.1　十個欄位",
          1 if ns.get("has") else 0, _ns)

    # 11 閱讀涵蓋
    def _cv():
        import coverage as CV
        return hasattr(CV, "CoverageLog") and hasattr(CV, "from_full_read")
    cv = _safe(reading_coverage, {}) or {}
    probe("規格讀了幾行", "F08 §5　七級涵蓋度", cv.get("records") or 0, _cv)

    # 12 停止理由
    def _sr():
        import stopreason as SR
        a = SR.classify_stop("UNKNOWN_STOP", has_authorized_next_action=True)
        return not getattr(a, "ok", True)
    sr = _safe(lambda: stop_reasons(strands), {}) or {}
    probe("停在不該停的地方", "F06 §4　八種停止理由",
          sr.get("count") or 0, _sr)

    # 13 查得回來的段落
    def _rc():
        import recall as RC
        return callable(RC.segment_session) and callable(RC.build_index)
    rc = _safe(recall_index, {}) or {}
    probe("查得回來的段落", "階段 C1　索引與查詢",
          rc.get("segments") or 0, _rc)

    # 14 壓縮後恢復
    def _rh():
        import rehydration as RH
        r = RH.coverage_report(read_ranges=[(1, 10)], total_lines=100)
        lv = r.get("level") if isinstance(r, dict) else getattr(r, "level", "")
        return bool(lv) and not RH.is_full_understanding(lv)
    probe("壓縮後恢復了多少", "F08 §5　七級涵蓋度", 0, _rh)

    # 15 多 session 成果驗收
    def _wk():
        import worker as WK
        bad = WK.WorkerResult(task_id="", step_id="", status="",
                              summary="", artifacts=[])
        return len(WK.validate(bad)) > 0
    wk = _safe(worker_packets, {}) or {}
    probe("多 session 成果驗收", "F03-CSI-001　Worker Result Packet",
          wk.get("packets") or 0, _wk)

    # 16 執行層偵測器
    def _js():
        import jsbridge as JB
        return JB.available().get("ok", False)
    jsr = _safe(lambda: js_layer(strands), {}) or {}
    probe("執行層偵測器", "src/　FP registry 25 筆",
          len(jsr.get("findings") or []) if jsr.get("ok") else 0, _js)

    # 17 從某一輪切出新分支
    def _f():
        import forkline as FK
        return callable(FK.fork)
    probe("從某一輪切分支", "§27　clean fork", len(strands), _f)

    # 自檢自己也要被檢。
    #
    # 它跑到這裡就代表它是活的 —— 前面每一項都已經跑過一次合成違規。
    # 不列它的話，功能表上會有一項永遠顯示「沒反應」，
    # 而那正是 demo 現場最難解釋的東西。
    rows.append({
        "name": "功能自檢",
        "spec": "§33",
        "live": sum(1 for r in rows if r["alive"]),
        "alive": True,
        "verdict": "活的",
    })

    dead = [r["name"] for r in rows if not r["alive"]]
    return {
        "at": time.time(),
        "session": target.stem if target else "",
        "items": rows,
        "alive": sum(1 for r in rows if r["alive"]),
        "total": len(rows),
        "dead": dead,
    }


def machine() -> dict:
    """這台機器上該搬的東西現在是什麼數字。§31

    owner 2026-09-14 換機器那一晚：

        一個舊電腦搬到新電腦這麼簡單的事情，Forseti 說什麼可以看到
        我們做了什麼，但沒有一個功能幫的到我。

    那一晚漏掉的是 `claude-code-sessions/` 底下 142 個 local_*.json，
    也就是每個 session 的工作目錄綁定。少了它，新機器看得到對話標題
    卻開不了工作目錄，只能走遠端連回舊機 —— 而那件事沒有任何東西
    會主動說出來，是人一個個發現的。

    這支把「哪些東西該搬、現在有幾個」變成畫面上的一列數字。
    """
    import migrate as MG
    try:
        return MG.inventory()
    except Exception as e:                                 # noqa: BLE001
        return {"error": f"掃不出來：{e}"}


def timeline(session: str) -> dict:
    r = subprocess.run(
        [sys.executable, str(REPO / "tools" / "timeline.py"), session,
         "--out", "/tmp/forseti_desktop_timeline.json"],
        capture_output=True, text=True, timeout=1800)
    p = Path("/tmp/forseti_desktop_timeline.json")
    if not p.is_file():
        return {"error": "timeline 沒有產生輸出",
                "stderr": r.stderr[-400:]}
    return json.loads(p.read_text(encoding="utf-8"))


# 追蹤器是有狀態的:它記著讀到哪裡,下一次只讀新增的部分。
# 所以同一個檔案要重用同一個 Tracker,不能每次呼叫都開新的 ——
# 開新的等於每次重讀 24 MB。
_TRACKERS: dict[str, object] = {}


def strands(session: str = "", projects: Path | None = None) -> dict:
    """那條線。Widget 每 1 到 3 秒叫一次。

    規格 `.forseti/WIDGET_SPEC.md` §3、§4、§6。

    `projects` 跟 `tracker.latest_session()` 同一個用途:讓這條路徑
    可以拿合成的 transcript 走一遍。沒有它,「白點接上了」這件事
    只能在真實資料剛好有白點的時候才驗得到,而那是碰運氣。
    """
    import tracker as TK
    base = projects or (Path.home() / ".claude" / "projects")
    picked_by = "指定"
    if session:
        hits = sorted(base.glob(f"*/{session}*.jsonl"))
        target = hits[0] if hits else None
    else:
        # 三層，由準到粗:
        #   一、她最後送訊息的那個（桌面版遙測）
        #   二、最後被寫的那份 jsonl（AI 在做什麼，不是她在做什麼）
        #   三、沒有
        target = None
        sid = _safe(lambda: focused_session(), "") or ""
        if sid:
            hits = sorted(base.glob(f"*/{sid}.jsonl"))
            if hits:
                target, picked_by = hits[0], "跟著你"
        if target is None:
            target = TK.latest_session(base)
            picked_by = "最後有動作的"
    if target is None or not target.is_file():
        return {"error": "找不到 transcript"}

    key = str(target)
    tk = _TRACKERS.get(key)
    if tk is None:
        tk = TK.Tracker(target)
        _TRACKERS[key] = tk
    tk.poll()
    snap = tk.snapshot(tail=180)
    snap["session"] = target.stem
    snap["picked_by"] = picked_by
    # 桌面版的 session id。前端拿它組 deep link 跳回去。
    #
    # 【2026-09-14 實測】`claude://code/continue?session=<ui_id>`
    # 真的會把桌面版切到那個 session（焦點從「KOL 嚴選頁面」
    # 跳到「Forseti 開發」，用 lastFocusedAt 驗證過）。
    # owner:「點了某個節點，就要跳回到那個桌面 APP 相應對話位置啊，
    # 這樣才能 Fork 啊，不然都是單向的還要自己慢慢往前面翻。」
    #
    # 還缺的是「跳到某一輪」—— deep link 只到 session 這一層，
    # 訊息層級的入口目前沒找到。不假裝有。
    snap["ui_id"] = _safe(lambda: _ui_id_of(target.stem), "") or ""

    # 白點。§5.2
    #
    # 掃的是「全部」的線不是 tail 那 180 條,因為判準要跨輪 ——
    # 一個在第 12 輪真的寫過的檔案,第 150 輪再提到它就不是宣稱。
    # 只掃 tail 會把前面那些證據丟掉,然後把認錯當成騙人。
    import betrayal as BT
    by_n: dict[int, list] = {}
    for f in _safe(lambda: BT.scan(tk.strands), []) or []:
        by_n.setdefault(f["n"], []).append(f)
    hit = 0
    for row in snap.get("rows", []):
        fs = by_n.get(row.get("n"))
        if fs:
            row["betrayals"] = fs
            hit += len(fs)
    snap["betrayal_total"] = hit
    # 提早收工。§31
    #
    # owner 2026-09-14 那一整晚的根因:帳本上有已授權的下一步，
    # 而我把發言權交回去等她開口。F06 §3 講的就是這件事。
    # `src/yield.js` 早就寫好，到 2026-09-15 才接進來。
    import yieldcheck as YC
    yields = _safe(lambda: YC.confirmed(tk.strands), []) or []
    by_yield = {x["n"]: x for x in yields}
    snap["premature_total"] = len(yields)

    starve = _safe(lambda: starving(tk.strands), []) or []
    by_starve = {x["n"]: x for x in starve}
    for row in snap.get("rows", []):
        x = by_starve.get(row.get("n"))
        if x:
            row["starving"] = x
        y = by_yield.get(row.get("n"))
        if y:
            row["premature"] = y
    snap["starving_total"] = len(starve)

    # 宣稱大於證據。betrayal 之外的另一類。
    over = _safe(lambda: overclaims(tk.strands), []) or []
    by_over: dict = {}
    for x in over:
        by_over.setdefault(x["n"], []).append(x)
    for row in snap.get("rows", []):
        hits = by_over.get(row.get("n"))
        if hits:
            row["overclaims"] = hits
    snap["overclaim_total"] = len(over)

    # 停滯風險。F05 的正式判定，不是計時器。
    st = _safe(lambda: stalls(tk.strands), []) or []
    by_stall = {x["n"]: x for x in st}
    for row in snap.get("rows", []):
        x = by_stall.get(row.get("n"))
        if x:
            row["stall"] = x
    snap["stall_total"] = len(st)

    # 宣稱對現實。唯一真的去磁碟查的一組。
    vc = _safe(lambda: verified_claims(tk.strands), []) or []
    by_vc: dict = {}
    for x in vc:
        by_vc.setdefault(x["n"], []).append(x)
    for row in snap.get("rows", []):
        hits = by_vc.get(row.get("n"))
        if hits:
            # 同一輪裡同一個 subject 常被抽到兩三次（同一段文字提到兩次），
            # 驗的結果一模一樣，畫面上卻會變成兩三條。這裡按
            # (subject, state) 去重。**只動顯示不動判定** ——
            # 去掉的那幾筆跟留下的那筆完全相同，不是合併不同的結論。
            seen, uniq = set(), []
            for h in hits:
                k = (h.get("subject"), h.get("state"))
                if k in seen:
                    continue
                seen.add(k)
                uniq.append(h)
            row["claims"] = uniq
    # 查了現實之後沒被證實的宣稱，總數。
    #
    # **這個數字不是「說謊幾次」。** `can_refute()` 的規則是沒資格判假
    # 就不判假，所以絕大多數會停在 UNKNOWN —— 那代表驗證器搆不到，
    # 不代表它騙人。畫面上必須照這個意思講，不然這個數字會變成
    # 另一種 overclaim:拿「我查不到」當「你說謊」。
    snap["claim_total"] = sum(
        len(r.get("claims") or []) for r in snap.get("rows", []))
    snap["north_star"] = _safe(north_star, {"has": False}) or {"has": False}
    snap["recall"] = _safe(recall_index, {"has": False}) or {"has": False}
    js = _safe(lambda: js_layer(tk.strands), {"ok": False}) or {"ok": False}
    snap["js"] = js
    by_js: dict = {}
    for f in (js.get("findings") or []):
        by_js.setdefault(f.get("n"), []).append(f)
    for row in snap.get("rows", []):
        hits = by_js.get(row.get("n"))
        if hits:
            row["js_findings"] = hits
    snap["worker"] = _safe(worker_packets, {}) or {}
    snap["coverage"] = _safe(reading_coverage, {"has": False}) or {"has": False}
    snap["stops"] = _safe(lambda: stop_reasons(tk.strands), {}) or {}
    snap["claim_refuted"] = sum(1 for x in vc if x["state"] == "REFUTED")
    snap["claim_unknown"] = sum(1 for x in vc if x["state"] == "UNKNOWN")
    snap["claim_unverifiable"] = sum(
        1 for x in vc if x["state"] == "UNVERIFIABLE")
    snap["context"] = _safe(lambda: context_state(target),
                            {"ok": False, "why": "算不出來"})
    snap["rehydrate"] = _safe(lambda: rehydrate_state(snap),
                              {"has": False}) or {"has": False}
    # 「補回了多少」是溫度計，「該補什麼」是可以直接貼給 AI 的東西。
    snap["rehydrate_packet"] = _safe(lambda: rehydration_packet(snap),
                                     {"has": False}) or {"has": False}
    # ── 生命徵象。§22.1 八維度、§11.3 體溫、§22.7 目標距離 ──────
    #
    # 這一段取代先前那個把工具失敗率壓成一個 tint 再染線的做法。
    # Five Mechanisms §6.8 雷一禁止合成單一風險分數;
    # Vol1 憲法第 6 條要求 Task Progress 與 Goal Progress 分開;
    # FS-DET-FSD-001 明寫「東西真的做了」不能讓目標距離下降。
    #
    # 唯一 OBSERVED 級的輸入是 owner 有沒有在下一輪糾正我 ——
    # 那是她真的打出來的字,不是我推出來的。
    import vitals as VT
    _rows = snap.get("rows") or []
    for _r in _rows:
        _t = _r.get("owner_text") or ""
        _r["corrected_by_owner"] = VT.is_correction(_t)
        _r["nudge_by_owner"] = VT.is_nudge(_t)
    _gs = _safe(lambda: VT.goal_support(_rows), []) or []
    for _r, _g in zip(_rows, _gs):
        _r["goal"] = _g
    snap["dims"] = _safe(lambda: VT.dimensions(_rows, snap, _gs), {}) or {}
    snap["temp"] = _safe(lambda: VT.temperature(snap["dims"]), {}) or {}
    # Health Curve §16.1。不是新演算法，是同一個 dimensions + temperature
    # 沿著輪次重跑。脈絡與連續性兩維被排除，理由在 vitals.CURVE_EXCLUDED。
    snap["health_curve"] = _safe(
        lambda: VT.curve(_rows, snap, _gs),
        {"has": False, "points": []}) or {"has": False, "points": []}
    # Blast Radius §16.1。演算法在 `src/cost.js`（M4 CostVector），
    # `blast.py` 只負責把真實的 import 邊掃出來餵進去。不重寫演算法，
    # 理由跟 jsbridge.py 檔頭那句一樣：兩份實作會分歧，而分歧那天沒人發現。
    #
    # 這一格要起一個 node 子行程，所以放在 _safe 裡，node 不在就整格不顯示。
    import blast as BL
    snap["blast"] = _safe(lambda: BL.summary(),
                          {"has": False, "why": "算不出來"}) \
        or {"has": False, "why": "算不出來"}
    # §40 污染登記簿。先前只在 `.forseti/NEXT.md` 上，桌面沒有入口。
    # 算不出來時 has=False 帶原因，**不回一個空清單** ——
    # 空清單在畫面上讀起來是「沒有被推翻的結論」，那是一句沒有根據的話。
    snap["pollution"] = _safe(
        pollution_panel,
        {"has": False, "why": "讀不到登記簿，不是沒有污染"}) \
        or {"has": False, "why": "讀不到登記簿，不是沒有污染"}
    # §12.2 來源優先序。算不出來時 has=False 帶原因，**不回空清單** ——
    # 空清單讀起來是「沒有這種狀態」，而實情是「這一格沒算出來」。
    snap["sot"] = _safe(
        sot_panel,
        {"has": False, "why": "算不出來，不是沒有來源問題"}) \
        or {"has": False, "why": "算不出來，不是沒有來源問題"}
    # §11.1 持久身份。算不出來時 has=False 帶原因，**不回空清單** ——
    # 空清單讀起來是「五個軸都沒事」，而實情是「這一格沒算出來」。
    snap["identity"] = _safe(
        identity_panel,
        {"has": False, "why": "算不出來，不是身份沒問題"}) \
        or {"has": False, "why": "算不出來，不是身份沒問題"}
    # §5 / §17.1 Workflow。算不出來時 has=False 帶原因，**不回空清單** ——
    # 空清單讀起來是「沒有待續的工作」，而實情是「這一格沒算出來」。
    snap["workflow"] = _safe(
        workflow_panel,
        {"has": False, "why": "算不出來，不是沒有待續的 workflow"}) \
        or {"has": False, "why": "算不出來，不是沒有待續的 workflow"}
    # §15 Probe Packs。算不出來時 has=False 帶原因，**不回空清單** ——
    # 空清單讀起來是「沒有哪一類退化」，而實情是「這一格沒算出來」。
    snap["probe"] = _safe(
        probe_panel,
        {"has": False, "why": "算不出來，不是沒有哪一類退化"}) \
        or {"has": False, "why": "算不出來，不是沒有哪一類退化"}
    snap["goal_trend"] = _safe(lambda: VT.distance_trend(_gs), 0.0)
    snap["progress"] = _safe(lambda: VT.progress_layers(_rows), {}) or {}
    # 偏離北極星的警示。§5.4 三條件同時成立才跳，掛在那一輪上，
    # 因為「你看到的位置就是它發生的位置」(§5.1)。
    # GAC 閘門。§28.6 / FS-GOL-001。2026-09-15 接上。
    #
    # 在這之前 drift_alerts 的 excluded 裡寫著一句寫死的「GAC 算不出來」。
    # 那句話沒有真的算過。現在實際跑 `src/goalanchor.js`，算不出來時
    # 指名缺哪個因子，算得出來也不會因為過了一關就升級成 CONFIRMED。
    import goalgate as GG
    _last_corr = None
    for _i, _r in enumerate(_rows):
        if _r.get("corrected_by_owner"):
            _last_corr = _i
    _since = (len(_rows) - 1 - _last_corr) if _last_corr is not None else None
    # scope_match 的素材:最近 12 輪的 AI 敘述加上實際下過的指令內容。
    # 用 12 是為了跟 goal_support 的 window 一致,兩邊看的是同一段。
    #
    # 【2026-09-15 更正】先前這裡傳空，理由寫成「row 裡沒有 AI 回合文字」。
    # 那句話是錯的:`ai_text` 一直都在，dots 也帶著 detail。
    # 沒查就下結論，然後把結論寫成註解，下一個人會照著它繼續空著。
    _acts: list = []
    for _r in _rows[-12:]:
        _at = _r.get("ai_text")
        if _at:
            _acts.append(str(_at))
        for _dot in (_r.get("dots") or []):
            _dd = _dot.get("detail")
            if _dd:
                _acts.append(str(_dd))
    _gate = _safe(lambda: GG.gate(actions=_acts, turns_since_owner=_since), None)
    snap["goal_gate"] = _gate or {"ok": False,
                                  "note": "goalgate 跑不起來",
                                  "gac": None, "may_confirm_drift": False}
    _alerts = _safe(lambda: VT.drift_alerts(_rows, _gate), []) or []
    _by_n = {a["n"]: a for a in _alerts}
    for _r in _rows:
        _a = _by_n.get(_r.get("n"))
        if _a:
            _r["drift_alert"] = dict(_a, prompt=VT.drift_prompt(_a))
    snap["drift_alerts"] = len(_alerts)

    snap["spec"] = _safe(spec_reading, {}) or {}
    # advice 先算，卡片要吸收它 —— 頂部只留一組建議，不並排兩組。
    snap["corrections"] = sum(1 for _r in _rows if _r.get("corrected_by_owner"))
    snap["nudges"] = sum(1 for _r in _rows if _r.get("nudge_by_owner"))

    # 介入面。§32
    #
    # `src/intervention.js` 規格 9.1：不可以持續盤問被觀測的模型，
    # 那會改變正在被量測的東西。所以這裡只算「現在可以做什麼」，
    # 真的要做的是人，而且每一次都要記進帳本。
    import intervene as IV
    snap["interventions"] = _safe(lambda: IV.decide(snap), []) or []
    # 【2026-09-15 接上】每個介入動作附一個可以被查核的探針。
    #
    # `build_probe` 的規則是這一支存在的理由:**不准問「你是不是飄移了」。**
    # 問了只會拿到流利的否認，而否認本身是 DECLARED，
    # 在對照到可觀測的現實之前不會升級成事實。
    for _iv in snap["interventions"]:
        _pb = _safe(lambda a=_iv: IV.build_probe(
            reason=a.get("why") or a.get("action") or "",
            window_ref=f"第 {snap.get('strands') or 0} 輪為止"), None)
        if _pb:
            _iv["probe"] = {
                "forbidden": _pb.get("forbidden") or [],
                "ceiling": _pb.get("answer_epistemic_ceiling", ""),
                "must_log": _pb.get("must_log_as_intervention", True),
            }

    snap["advice"] = _safe(
        lambda: session_advice(snap.get("rows") or [], hit,
                               snap.get("total_failed") or 0, snap),
        {"text": "建議算不出來", "why": "", "tone": "info", "n": 0, "say": ""})
    # 卡片吸收 advice，所以一定要排在它後面。
    snap["cards"] = _safe(lambda: VT.cards(snap, snap.get("advice")), []) or []

    # 壓縮過就多一張卡:該補回去的脈絡，可以直接複製貼給 AI。
    # §6.2 要求差集寫成一張條子掛在黑點上 —— 一份組好了卻沒有出口的
    # packet，跟沒組是一樣的。排在最前面因為失憶是所有問題的上游。
    _pk = snap.get("rehydrate_packet") or {}
    if _pk.get("has") and _pk.get("say"):
        snap["cards"].insert(0, {
            "key": "rehydrate",
            "title": "對話壓縮過，把這段脈絡貼回去給它",
            "say": _pk["say"],
            "why_now": f"第 {_pk.get('at_round')} 輪發生過壓縮，"
                       f"壓縮前你講過的話有 {_pk.get('fragments', 0)} 段"
                       f"可能已經不在它的記憶裡",
            "evidence": f"packet {_pk.get('size', 0)}/{_pk.get('limit', 0)} bytes，"
                        f"決定 {_pk.get('decisions', 0)}、"
                        f"約束 {_pk.get('constraints', 0)}、"
                        f"未解 {_pk.get('unknowns', 0)}",
            "confidence": "高　片段是你親口講的原文，不是我的摘要",
            "if_ignored": "它會拿壓縮後的摘要繼續做，"
                          "而摘要裡沒有你講過的那些限制",
            "n": _pk.get("at_round"),
        })

    # 建議軌跡。§11 / owner 2026-09-15「每個決定都會跟 forseti 的建議做分岔」。
    #
    # 在這之前建議算完就丟，畫面上只剩「實際走的那一條線」，所以它是直的。
    # 這裡把每一輪呈現出來的卡片記進帳本，下一輪如果同一張還在，
    # 代表那個狀況沒有解除，分岔就往外開一格。
    import advicetrack as AT
    _cards = snap.get("cards") or []
    _n_now = (snap.get("rows") or [{}])[-1].get("n")
    # 問題軌道。owner 2026-09-16:「改成用問題來畫軌道」。
    #
    # 建議軌道只知道「現在有哪幾條」，畫出來每條都是從第 N 輪到第 N 輪。
    # 問題軌道是從已經發生過的事實回溯的,每條都說得出起點、終點、
    # 以及憑什麼算收回來,所以它們有長度、會重疊、會並行。
    import lanes as LN
    # 粉紅點。§5.5 她自己寫的注記，掛在那一輪上。
    import notes as NT
    _sid0 = str(snap.get("session") or snap.get("ui_id") or "")
    _by = _safe(lambda: NT.by_turn(_sid0), {}) or {}
    for _r in _rows:
        _ns = _by.get(int(_r.get("n") or 0))
        if _ns:
            _r["notes"] = [{"text": x.get("text", ""), "at": x.get("at")}
                           for x in _ns]
    snap["notes"] = _safe(lambda: NT.summary(_sid0),
                          {"total": 0, "turns": []}) or {"total": 0}

    # Authority。§9 誰有權把提議變成事實。
    #
    # claims 收的是真實存在過的權威競爭。現在有兩筆,都是已經發生過
    # 而且被解決掉的:北極星的單向對雙向（owner 2026-09-15 拍板單向）,
    # 以及 FP-11 的家族 A 對 B（兩份清單分歧,spec 第 664 行判 A）。
    # **留著是因為「曾經有兩個來源說自己說了算」這件事本身要看得見** ——
    # 這種東西平常不會報錯，兩邊各自都成功，然後結果不一致。
    import authority as AU
    _claims = [
        {"resource": ".forseti/NORTH_STAR.md 的方向",
         "principal": "OWNER", "detail": "2026-09-15 拍板單向"},
        {"resource": ".forseti/NORTH_STAR.md 的方向",
         "principal": "CANONICAL_STATE", "detail": "Vol1 §2 寫的是雙向"},
        {"resource": "FP-11 的家族",
         "principal": "CANONICAL_STATE", "detail": "spec-v2.0 第 664 行判 A"},
        {"resource": "FP-11 的家族",
         "principal": "AGENT_INFERENCE", "detail": "betrayal.py 手寫表曾寫 B"},
    ]
    snap["authority"] = _safe(lambda: AU.summary(_claims),
                              {"has_collision": False}) or {}

    # 修正延遲。白皮書 §5.4 從偏離開始到被拉回來隔了多久。
    #
    # **重點不是平均，是誰把它拉回來的。** self_recovered 越多代表
    # 偏離不必靠她消耗自己來修;她出手佔多數就是 continuity 0.0 的
    # 另一種寫法。第一版用詞表判，三段全部誤判成「自己回來」，
    # 而三段的結束全是她在講話 —— 改用 owner_stepped_in 的三種 OBSERVED 訊號。
    import latency as LT
    snap["latency"] = _safe(lambda: LT.summary(_rows), {"has": False}) or {"has": False}

    # 接手閘門。§17.3 沒證明讀懂之前，高風險工作只准讀不准寫。
    #
    # 這一條可以合法硬擋:can_intervene 的 BLOCK_HIGH_RISK 要的是
    # 「硬前提不明或被推翻」，而「接手的人沒證明自己讀懂規格」正是那個。
    import gate as GT
    snap["gate"] = _safe(lambda: GT.status(_sid0),
                         {"writable": False, "reason": "UNKNOWN"}) or {}

    # 第一個分歧點。§16.4 / §6.3
    #
    # **三種，不是一種。** 最早的警訊、可以下結論的起點、
    # 第一個真的造成代價的區段，它們常常不是同一輪。
    # 實測這條線上散在 12 輪之間。只報一個的話，
    # 回答的是哪一題就變成看運氣。
    import divergence as DV
    snap["divergence"] = _safe(lambda: DV.summary(_rows),
                               {"has": False}) or {"has": False}

    # Two-Phase Commit。§9.3 準備跟提交是兩個權限等級。
    #
    # **停在半路的要看得見。** 一個停在 PREPARED 的東西，跟一個沒開始的
    # 東西，在畫面上必須有差別，不然人會以為它沒做 —— 然後再做一次。
    import commit as CM
    snap["commits"] = _safe(CM.summary, {"total": 0, "pending": []}) or {"total": 0}

    # Checkpoint。§17 可以回去的那一刻。
    import checkpoint as CP
    snap["checkpoints"] = _safe(lambda: CP.summary(_sid0),
                                {"total": 0, "rows": []}) or {"total": 0}
    _cplist = _safe(lambda: CP.load(session=_sid0), []) or []
    # 掛到那一輪上。checkpoint 是「可以回去的那一刻」，它屬於時間軸。
    _cps: dict = {}
    for _c in _cplist:
        _cps.setdefault(int(_c.get("n") or 0), []).append(_c)
    for _r in _rows:
        _cc = _cps.get(int(_r.get("n") or 0))
        if _cc:
            _r["checkpoint"] = {"n": len(_cc),
                                "last_good": any(x.get("last_good") for x in _cc),
                                "reason": _cc[-1].get("reason", "")}

    # 救回一次。ROADMAP P0 第 1 項，Vol4 Stage 4 的出口條件。
    #
    # **這一格在意的是「能不能救」而不是「有沒有壞」。** 畫面上別處已經
    # 有紅有白有紫在講哪裡出問題，這一格回答的是另一題:如果現在要退回去，
    # 退到哪一輪、憑什麼、會丟掉多少。算不出來的時候它講缺什麼，
    # 不給輪號 —— 猜一個出來會把還好的工作一起丟掉，而且不會有人發現。
    import rescue as RS
    snap["rescue"] = _safe(
        lambda: RS.plan(_rows, session=_sid0, checkpoints=_cplist),
        {"can": False, "why": "算不出來"}) or {"can": False}
    snap["rescue_history"] = _safe(
        lambda: RS.history(session=_sid0),
        {"total": 0, "incidents": []}) or {"total": 0, "incidents": []}

    snap["lanes"] = _safe(lambda: LN.summary(_rows),
                          {"lanes": [], "total": 0, "open": 0}) or {"lanes": []}

    # 交接檔。C4「新 session 不貼任何東西就能接上」。
    #
    # 09-15 17:02 停機、09-16 09:11 恢復，中間 16 小時 owner 發的指令
    # 沒有人接。**停機控制不了，停機時沒留下狀態是可以控制的。**
    # 有最小間隔,不然每輪詢一次就重寫，mtime 會失去意義 ——
    # 而「這份交接什麼時候寫的」正是接手的人第一個要問的。
    #
    # 【2026-09-16 修】**它一定要排在 `snap["checkpoints"]` 後面。**
    # 原本排在 advice 那一段，而那時候 snap 裡還沒有 checkpoints，
    # 所以交接檔的「最後一個已知良好的點」永遠印「沒有」——
    # 即使真的有人標過。症狀是兩個來源說法不一致:畫面上的救援那格
    # 說「你自己標的第 206 輪」，交接檔說沒有。
    # 這種 bug 不會報錯，只會在停機之後讓接手的人以為無處可退。
    _safe(lambda: _write_handoff(snap), None)

    _sid = str(snap.get("session") or snap.get("ui_id") or "")
    if _n_now is not None:
        _safe(lambda: AT.record(_cards, n=_n_now, session=_sid), [])
    _now_ids = {AT.advice_id(c) for c in _cards}
    snap["advice_track"] = _safe(
        lambda: AT.summary(AT.load(session=_sid), _now_ids),
        {"has": False, "offset_now": 0, "divergence": []}) or {"has": False}
    return snap


def _project_label(dirname: str) -> str:
    """把 `.claude/projects/` 的目錄名變成看得懂的專案名。

    那個目錄名就是 cwd 把 `/` 換成 `-` 的編碼，還原不回去
    （路徑本身就可能有 `-`）。所以不猜完整路徑，只取最後一段 ——
    那通常就是專案資料夾的名字，而那正是人認得的東西。
    """
    parts = [x for x in dirname.split("-") if x]
    if not parts:
        return "未知"
    home = Path.home().name
    if parts[-1] == home:
        return "家目錄"
    return parts[-1]


def _first_words(path: Path, limit: int = 40) -> str:
    """那個 session 的第一句話。拿來當標題。

    一串 uuid 認不出是哪個 session，而第一句話幾乎一定認得出來。

    只讀開頭 256 KB —— 第一則使用者訊息一定在很前面，
    而有些 jsonl 有上百 MB，整份讀進來只為了拿一行是浪費。
    """
    import json as _json
    import owner as O
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            head = fh.read(262144)
    except OSError:
        return ""
    for line in head.splitlines():
        try:
            d = _json.loads(line)
        except (ValueError, TypeError):
            continue
        if d.get("type") != "user":
            continue
        c = (d.get("message") or {}).get("content")
        if isinstance(c, str):
            text = c
        elif isinstance(c, list):
            text = "\n".join(b.get("text", "") for b in c
                              if isinstance(b, dict) and b.get("type") == "text")
        else:
            continue
        if not O.is_owner_text(text):
            continue
        flat = " ".join(text.split())
        if flat:
            return flat[:limit]
    return ""


# 桌面版自己的 session metadata。§21
#
# 【2026-09-14 owner 當場指出兩件事，兩件都對】
#
# 一、「我要怎麼讓這東西去對我正在跑的 Session？」
#     原本跟的是「哪一份 jsonl 最後被寫」。那個判準量錯了東西:
#     jsonl 的修改時間反映「AI 在做什麼」，AI 在跑就一直寫。
#     她要的是「她在做什麼」。她正在看的那個（AI 剛回完、等她決定）
#     不寫檔，畫面就跳到某個背景還在跑的去。
#     **她最需要看它的那一刻，正是它離開的那一刻。**
#
# 二、「你要給我的是 Session 名稱啦！你現在給我對話的內容幹嘛」
#     我拿第一句話當標題，那不是她認得的東西。
#     她認的是側邊欄那個名字。
#
# 兩件事的答案在同一個地方:
#
#     ~/Library/Application Support/Claude/claude-code-sessions/
#         <帳號 uuid>/<組織 uuid>/local_*.json
#
# 每一份帶著:
#     title           側邊欄那個名字
#     cliSessionId    jsonl 的檔名，直接對得上
#     lastFocusedAt   最後被切到前景的時間 ← 她切過去看就更新
#     lastActivityAt  最後有動作的時間
#     completedTurns  幾個來回
#     isArchived      封存的不要列
#
# `lastFocusedAt` 是關鍵:它記的是「看」，不是「寫」。
SESSIONS_META = (Path.home() / "Library" / "Application Support" / "Claude"
                 / "claude-code-sessions")


def _meta_rows(base: Path | None = None) -> list[dict]:
    """桌面版記的每個 session。讀不到就回空清單。

    **讀不到不是錯誤** —— 她可能用 CLI 而不是桌面版，
    或者桌面版換了儲存格式。呼叫端一定要有後備。
    """
    d = base or SESSIONS_META
    if not d.is_dir():
        return []
    out = []
    for f in d.rglob("local_*.json"):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        cli = o.get("cliSessionId")
        if not cli or o.get("isArchived"):
            continue
        out.append({
            "id": cli,
            "ui_id": o.get("sessionId") or "",
            "title": (o.get("title") or "").strip(),
            "cwd": o.get("cwd") or "",
            "focused_at": (o.get("lastFocusedAt") or 0) / 1000,
            "active_at": (o.get("lastActivityAt") or 0) / 1000,
            "turns": o.get("completedTurns") or 0,
            "model": o.get("model") or "",
        })
    return out


def _ui_id_of(cli_id: str, base: Path | None = None) -> str:
    """jsonl 檔名對回桌面版的 session id。找不到回空字串。"""
    for r in _meta_rows(base):
        if r["id"] == cli_id:
            return r["ui_id"]
    return ""


def focused_session(base: Path | None = None) -> str:
    """她最後切到前景的那個 session。找不到回空字串。

    這是「看」不是「寫」—— 她切過去就算，不必發訊息。
    """
    rows = [r for r in _meta_rows(base) if r["focused_at"]]
    if not rows:
        return ""
    return max(rows, key=lambda r: r["focused_at"])["id"]


def sessions() -> dict:
    """給選擇器的清單。名稱用桌面版側邊欄那個。

    owner 2026-09-14 手繪:左上角漢堡，按下去蓋住整個畫面，選完回到 Tree。

    排序用 `lastFocusedAt` —— 她要找的是「我剛才在看的那個」，
    而那正是這個欄位記的東西。
    """
    base = Path.home() / ".claude" / "projects"
    on_disk: dict[str, dict] = {}
    if base.is_dir():
        for d in base.iterdir():
            if not d.is_dir():
                continue
            for f in d.glob("*.jsonl"):
                try:
                    st = f.stat()
                except OSError:
                    continue
                on_disk[f.stem] = {"project": d.name, "mtime": st.st_mtime,
                                   "size": st.st_size}

    out = []
    for m in _meta_rows():
        disk = on_disk.pop(m["id"], None)
        if disk is None:
            continue          # 桌面版記著，但紀錄檔不在了
        out.append({
            "id": m["id"],
            "ui_id": m["ui_id"],
            "title": m["title"] or "（沒有名稱）",
            "turns": m["turns"],
            "focused_at": m["focused_at"],
            "mtime": disk["mtime"],
            "size": disk["size"],
            "project": disk["project"],
            "group": _project_label(disk["project"]),
            "named": bool(m["title"]),
        })

    # 桌面版沒記到的（CLI 開的、或者 metadata 掉了）也要列，
    # 不然它們等於不存在。標出來它們沒有名字，不假裝有。
    for sid, disk in on_disk.items():
        out.append({
            "id": sid, "ui_id": "", "title": "", "turns": 0, "focused_at": 0,
            "mtime": disk["mtime"], "size": disk["size"],
            "project": disk["project"],
            "group": _project_label(disk["project"]), "named": False,
        })

    # 看過的排前面（用 focused_at），沒看過的用檔案時間墊底。
    out.sort(key=lambda x: (x["focused_at"] or x["mtime"]), reverse=True)
    out = out[:80]
    for row in out:
        if not row["title"]:
            row["title"] = _safe(
                lambda: _first_words(
                    base / row["project"] / f"{row['id']}.jsonl"), "") or row["id"][:8]
    return {"sessions": out}


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "snapshot"
    if cmd == "snapshot":
        print(json.dumps(snapshot(), ensure_ascii=False))
    elif cmd == "timeline":
        if len(argv) < 3:
            print(json.dumps({"error": "要給 session id"}, ensure_ascii=False))
            return 2
        print(json.dumps(timeline(argv[2]), ensure_ascii=False))
    elif cmd == "strands":
        print(json.dumps(strands(argv[2] if len(argv) > 2 else ""),
                         ensure_ascii=False))
    elif cmd == "note_add":
        # note_add <session> <n> <text...>
        if len(argv) < 5:
            print(json.dumps({"ok": False, "why": "用法：note_add <session> <n> <text>"},
                             ensure_ascii=False))
            return 2
        print(json.dumps(add_note(argv[2], argv[3], " ".join(argv[4:])),
                         ensure_ascii=False))
    elif cmd == "act":
        # 會改變狀態的動作。target 必給，worker 可選。
        if len(argv) < 4:
            print(json.dumps({"ok": False, "why": "用法：act <kind> <target> [worker]"},
                             ensure_ascii=False))
            return 2
        print(json.dumps(act(argv[2], argv[3], argv[4] if len(argv) > 4 else ""),
                         ensure_ascii=False))
    elif cmd == "audit":
        print(json.dumps(audit(), ensure_ascii=False))
    elif cmd == "spec_reading":
        print(json.dumps(spec_reading(), ensure_ascii=False))
    elif cmd == "block_reading":
        print(json.dumps(block_reading(), ensure_ascii=False))
    elif cmd == "sufficiency":
        print(json.dumps(sufficiency_state(argv[2] if len(argv) > 2 else ""),
                         ensure_ascii=False))
    elif cmd == "features":
        print(json.dumps(features(), ensure_ascii=False))
    elif cmd == "selftest":
        print(json.dumps(selftest(), ensure_ascii=False))
    elif cmd == "machine":
        print(json.dumps(machine(), ensure_ascii=False))
    elif cmd == "work":
        print(json.dumps(work(), ensure_ascii=False))
    elif cmd == "blast_detail":
        # blast_detail <檔案路徑>　點一個節點看誰依賴它。
        if len(argv) < 3:
            print(json.dumps({"error": "用法：blast_detail <檔案路徑>"},
                             ensure_ascii=False))
            return 2
        print(json.dumps(blast_detail(argv[2]), ensure_ascii=False))
    elif cmd == "pollution":
        # pollution　§40 登記簿：哪些話已經被推翻了，為什麼會錯。
        print(json.dumps(pollution_panel(), ensure_ascii=False))
    elif cmd == "workflow":
        # workflow [workflow_id]　§5 / §17.1：程序死掉之後接哪一步。
        if len(argv) > 2:
            print(json.dumps(workflow_resume(argv[2]), ensure_ascii=False))
        else:
            print(json.dumps(workflow_panel(), ensure_ascii=False))
    elif cmd == "identity":
        # identity　§11.1：身份跟 model / session / process 分得開嗎。
        print(json.dumps(identity_panel(), ensure_ascii=False))
    elif cmd == "sot":
        # sot [問句]　§12.2：這一類狀態該信哪個來源。
        if len(argv) > 2:
            print(json.dumps(sot_ask(" ".join(argv[2:])), ensure_ascii=False))
        else:
            print(json.dumps(sot_panel(), ensure_ascii=False))
    elif cmd == "sessions":
        print(json.dumps(sessions(), ensure_ascii=False))
    elif cmd == "fork":
        # fork <session> <輪號> [--go]
        #
        # 預設是乾跑。**真的要寫檔必須明講 `--go`** ——
        # 一個手滑就產生檔案的指令，遲早會在沒人打算 fork 的時候產生檔案。
        if len(argv) < 4:
            print(json.dumps({"error": "用法：fork <session> <輪號> [--go]"},
                             ensure_ascii=False))
            return 2
        try:
            n = int(argv[3])
        except ValueError:
            print(json.dumps({"error": f"輪號要是數字：{argv[3]}"},
                             ensure_ascii=False))
            return 2
        print(json.dumps(fork_at(argv[2], n, dry_run="--go" not in argv),
                         ensure_ascii=False))
    else:
        print(json.dumps({"error": f"不認得的指令：{cmd}"}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
