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


def _blockers() -> dict:
    p = REPO / ".forseti" / "BLOCKERS.md"
    text = p.read_text(encoding="utf-8", errors="replace")
    heads = [ln.strip() for ln in text.splitlines() if ln.startswith("## B-")]
    open_ = [h for h in heads if "解除" not in h and "已解" not in h
             and "找到並修好" not in h]
    return {
        "total": len(heads),
        "open": len(open_),
        "titles": [h.lstrip("# ").strip() for h in open_][:10],
        "source": ".forseti/BLOCKERS.md",
    }


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
        })
    e = snap.get("ledger") or {}
    if not e.get("exists") or (e.get("age_hours") or 0) > 24:
        out.append({
            "severity": "WATCH",
            "title": "事件帳本太久沒有新資料",
            "detail": "hook 註冊在 repo 的 .claude/settings.json，"
                      "只有 session 啟動時 cwd 在 repo 內才會載入（B-13）。",
            "action": 'cd "' + str(REPO) + '" && claude',
        })
    r = snap.get("reading") or {}
    if r.get("bad"):
        out.append({
            "severity": "ATTENTION",
            "title": f"{r['bad']} 份規格對不上",
            "detail": r.get("policy", ""),
            "action": "python3 tools/reading-conformance.py",
        })
    b = snap.get("blockers") or {}
    if not out and b.get("open"):
        out.append({
            "severity": "WATCH",
            "title": f"{b['open']} 條阻塞還沒解除",
            "detail": "；".join(b.get("titles", [])[:3]),
            "action": "python3 apps/forseti-cli/forseti.py doctor",
        })
    return out[:3]


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


def sessions() -> dict:
    """這台機器上的 session，最新在前。"""
    base = Path.home() / ".claude" / "projects"
    out = []
    if base.is_dir():
        for d in base.iterdir():
            if not d.is_dir():
                continue
            for f in d.glob("*.jsonl"):
                try:
                    st = f.stat()
                except OSError:
                    continue
                out.append({"id": f.stem, "project": d.name,
                            "mtime": st.st_mtime, "size": st.st_size})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return {"sessions": out[:60]}


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "snapshot"
    if cmd == "snapshot":
        print(json.dumps(snapshot(), ensure_ascii=False))
    elif cmd == "timeline":
        if len(argv) < 3:
            print(json.dumps({"error": "要給 session id"}, ensure_ascii=False))
            return 2
        print(json.dumps(timeline(argv[2]), ensure_ascii=False))
    elif cmd == "sessions":
        print(json.dumps(sessions(), ensure_ascii=False))
    else:
        print(json.dumps({"error": f"不認得的指令：{cmd}"}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
