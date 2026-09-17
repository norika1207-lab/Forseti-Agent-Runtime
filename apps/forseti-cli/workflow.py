#!/usr/bin/env python3
"""Workflow / WorkflowStep。v5.0 §5(第 156、157 行)與 §17.1 Workflow
Reconstruction(第 471 行)。

ROADMAP P2 第 6 項的完成定義是:

    「一件跨 session 的工作,程序死掉之後接得回來,
     而不是靠模型記得。」

同一項寫著現在缺什麼:「`ledger.py` 有 task/step,但沒有 v5.0 §5 定義的
`Workflow` 實體與 `commit_boundary`。」

────────────────────────────────────────────────────

## 這一支要回答的窄問題

    「程序剛死掉,我現在接哪一步?憑什麼是那一步?
     還有哪幾步被擋住,各自在等什麼?」

**不是「幫我建一個 workflow 引擎」。** 這條線上已經有耐久的
task/step(`ledger.py` 的 sqlite),再建一套平行的存放區,
兩套遲早會分歧,而分歧那天不會有錯誤訊息。所以這一支
**不新增任何一張表**,只做兩件現在沒有的事:

一,`resume()` —— §17.1 那一行要的「Resumable durable workflow」。
   它只讀磁碟,不碰任何 module-level 狀態,所以另起一個程序跑
   答案要逐欄一致(`test_另一個程序重跑答案一樣` 釘住這件事)。

二,把規格那兩行的十個欄位跟現況逐欄比對,**缺的要講得出為什麼缺**。

## 三種來源狀態,NO_SOURCE 不准投影成好消息

- `PRESENT`    ledger 有這一欄,而且性質就是規格要的那個
- `DEGRADED`   有值,但不是規格要的性質(機械比得出來的才算,
               語意判斷不算 —— 分不出來就不分)
- `NO_SOURCE`  這個 repo 沒有資料來源,所以不給值

`external_refs` 是第三種。steps 表十五個欄位裡沒有任何一欄放外部物件 ID
(`sqlite3 ... 'pragma table_info(steps)'` 自己查),所以它回 `None`
**不回 `[]`**。空清單在畫面上讀起來是「這一步沒有外部效果」,
那是一句沒有根據的話,而這個專案已經為同一件事付過四次代價
(blast 的 live_conflicts、uncovered_d1、blast.detail 的任務依賴、
pollution 的 propagation_radius)。

## commit_boundary 為什麼是人工登記的

規格 §5 說 Workflow 有 commit_boundary 這一欄,`authority.py` 也已經有
一張 `COMMIT_BOUNDARY` 動作表(send / deploy / spend / delete / publish /
push)。看起來最省事的做法是拿 step 的 objective 文字去比對那張表。

**不做**,理由是 BLOCKERS B-05:靠文字判斷「這句話有沒有在宣稱某件事」
抓到的是符合句型的字串。這裡的代價比別處高 —— 一個被漏判的
commit boundary,意思是「這一步不可逆而沒有人在守」,
而它在畫面上會長得跟「這一步很安全」一模一樣。

所以沒宣告就是 `UNDECLARED`,那是一個**要人來回答的問題**,
不是一個「沒有跨邊界」的結論。登記在
`.forseti/workflow_boundary.jsonl`,只增不改,跟
`pollution.py` / `identity.py` / `sot.py` 同一條。

## 規格 §6.2 那四種事件,實測一筆都沒有

§6.2 第 194 行給 Workflow 類定了四種事件:STEP_START、STEP_COMMIT、
STEP_ROLLBACK、APPROVAL_REQUESTED。`spec_events()` 回去數,
2026-09-16 實測**四種各 0 筆**,帳本裡實際用的是 STEP_STATE(86 筆)
這種自己的命名。

這件事要報出來,不能靜默把 STEP_STATE 當成 STEP_START —— 那是
把「我們沒照規格記」翻譯成「我們照規格記了」。兩者的差別在復原的時候
才會顯現:STEP_STATE 記的是狀態轉換,STEP_COMMIT 記的是**那一步的
效果已經對外生效了**,後者是 rollback 要看的那一筆。

零依賴,只在需要時才 import `ledger`。
"""

from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 規格原文的位置。`verify_spec()` 會回去逐行比對。
SPEC = ("docs/sources/"
        "Forseti_Agent_Runtime_System_Architecture_Engineering_Spec_v5.0_"
        "2026-09-04.md")

#: §5 那兩行的原文,一個字都沒有改。
SPEC_WORKFLOW_LINE = 156
SPEC_WORKFLOW_TEXT = ("| Workflow | Durable multi-step unit of work. | "
                      "workflow_id, objective, state, commit_boundary, owner |")
SPEC_STEP_LINE = 157
SPEC_STEP_TEXT = ("| WorkflowStep | Resumable execution step. | "
                  "step_id, status, inputs, outputs, external_refs |")

#: §17.1 那一行。這一行是 `resume()` 的出處。
SPEC_RECON_LINE = 471
SPEC_RECON_TEXT = ("| Workflow Reconstruction | external object IDs, "
                   "step state, retries, approvals. | "
                   "Resumable durable workflow. |")

#: §6.2 Workflow 類的四種事件。
SPEC_EVENTS_LINE = 194
SPEC_EVENTS_TEXT = ("| Workflow | STEP_START, STEP_COMMIT, STEP_ROLLBACK, "
                    "APPROVAL_REQUESTED |")
SPEC_EVENTS = ("STEP_START", "STEP_COMMIT", "STEP_ROLLBACK",
               "APPROVAL_REQUESTED")

#: 三種來源狀態。**沒有第四種叫「看起來沒問題」。**
SOURCE_STATES = ("PRESENT", "DEGRADED", "NO_SOURCE")

#: commit_boundary 的四種答案。`UNDECLARED` 是預設,而它是一個問題
#: 不是一個結論 —— 見檔頭。
BOUNDARY_STATES = ("UNDECLARED", "NONE", "CROSSES", "CROSSED")

# ---------------------------------------------------------------------------
# 一,規格那十個欄位跟現況的逐欄對照
# ---------------------------------------------------------------------------

#: §5 Workflow 五欄。`ledger` 那一欄寫的是 tasks 表的欄位名,
#: `None` 表示那一欄在 tasks 表裡不存在。
#: 下面幾條 `why` 是**印到畫面上的字串**，所以裡面不放 markdown 標記 ——
#: 星號與反引號會原樣顯示。sot.py 與 identity.py 前兩輪各犯過一次。
WORKFLOW_FIELDS: tuple[dict, ...] = (
    {
        "field": "workflow_id",
        "ledger": "tasks.task_id",
        "state": "PRESENT",
        "why": "主鍵,格式 T-<hash>,跨 session 不變",
        "how": "sqlite3 <db> 'select task_id from tasks limit 3'",
    },
    {
        "field": "objective",
        "ledger": "tasks.objective",
        "state": "PRESENT",
        "why": "同名同義",
        "how": "sqlite3 <db> 'select objective from tasks limit 3'",
    },
    {
        "field": "state",
        "ledger": "tasks.current_state",
        "state": "PRESENT",
        "why": "ledger.STATES 九個狀態,終態四個,有狀態機守著轉換",
        "how": "sqlite3 <db> 'select distinct current_state from tasks'",
    },
    {
        "field": "commit_boundary",
        "ledger": None,
        "state": "NO_SOURCE",
        "why": "tasks 表沒有這一欄。不從 objective 文字猜(B-05),"
               "所以改成人工登記 .forseti/workflow_boundary.jsonl,"
               "沒登記就是 UNDECLARED 不是 NONE",
        "how": "sqlite3 <db> 'pragma table_info(tasks)' | grep -i commit",
    },
    {
        "field": "owner",
        "ledger": "tasks.current_owner",
        "state": "DEGRADED",
        "why": "有值,但值是 session alias(norikaoda-03 這種),"
               "換 session 就換。§11.1 要的持久身份不存在 —— "
               "identity.py 量過,持久身份登記 0 條、帳本裡 31 個 alias",
        "how": "python3 apps/forseti-cli/identity.py",
    },
)

#: §5 WorkflowStep 五欄。
STEP_FIELDS: tuple[dict, ...] = (
    {
        "field": "step_id",
        "ledger": "steps.step_id",
        "state": "PRESENT",
        "why": "主鍵,格式 <task_id>/<name>",
        "how": "sqlite3 <db> 'select step_id from steps limit 3'",
    },
    {
        "field": "status",
        "ledger": "steps.state",
        "state": "PRESENT",
        "why": "同一組 ledger.STATES,終態判定用 ledger.is_terminal",
        "how": "sqlite3 <db> 'select distinct state from steps'",
    },
    {
        "field": "inputs",
        "ledger": "steps.dependencies",
        "state": "DEGRADED",
        "why": "dependencies 是「要等哪幾個 step 先完成」,"
               "那是順序不是輸入。真正的輸入(檔案、參數、前一步的"
               "產出)沒有欄位放。兩者機械上分得出來:dependencies 裡"
               "每一筆都是 step_id,不是路徑也不是值",
        "how": "sqlite3 <db> 'select dependencies from steps limit 5'",
    },
    {
        "field": "outputs",
        "ledger": "steps.expected_outputs",
        "state": "DEGRADED",
        "why": "是預期輸出不是實際輸出。這一欄在 step 開始前就寫好了,"
               "沒有任何地方回來記「實際產出了什麼」。"
               "欄位名保留 expected_ 這個字,不准在這一支改叫 outputs",
        "how": "sqlite3 <db> 'select state, expected_outputs from steps"
               " where state != \"VERIFIED_COMPLETE\"'",
    },
    {
        "field": "external_refs",
        "ledger": None,
        "state": "NO_SOURCE",
        "why": "steps 表沒有任何一欄放外部物件 ID。evidence_refs 放的是"
               "證據參照(cmd: / file: 開頭),那是「怎麼驗證」不是"
               "「在外部系統建立了哪個物件」。回 None 不回空清單",
        "how": "sqlite3 <db> 'pragma table_info(steps)'",
    },
)


def fields() -> dict:
    """十個欄位的對照表,加上兩個分開報的覆蓋率。

    **兩個覆蓋率不合成一個。** Workflow 五欄與 WorkflowStep 五欄
    答的是不同的問題,合起來的那個數字沒有人看得懂它在說什麼。
    """
    def _cov(rows):
        n = sum(1 for r in rows if r["state"] == "PRESENT")
        return {"present": n, "total": len(rows),
                "ratio": round(n / len(rows), 3) if rows else None}

    return {
        "workflow": {"fields": [dict(f) for f in WORKFLOW_FIELDS],
                     "coverage": _cov(WORKFLOW_FIELDS)},
        "step": {"fields": [dict(f) for f in STEP_FIELDS],
                 "coverage": _cov(STEP_FIELDS)},
        "note": "兩個覆蓋率不合成一個,它們答的不是同一個問題",
        "source": "v5.0 §5 第 156、157 行",
    }


# ---------------------------------------------------------------------------
# 二,規格原文比對
# ---------------------------------------------------------------------------

def verify_spec(repo: Path | None = None) -> dict:
    """那四行原文還在不在,而且逐字一樣。

    比對整行,不是「這份檔案裡有沒有出現過 Workflow 這個字」——
    那個字在四千行的規格裡出現十幾次,那種比對等於沒有比對。
    """
    base = Path(repo or REPO)
    f = base / SPEC
    if not f.exists():
        return {"ok": False, "why": f"規格檔不在:{SPEC}", "rows": []}
    lines = f.read_text(encoding="utf-8").splitlines()

    def _raw(n: int) -> str:
        return lines[n - 1] if 0 < n <= len(lines) else ""

    want = (
        ("workflow", SPEC_WORKFLOW_LINE, SPEC_WORKFLOW_TEXT),
        ("step", SPEC_STEP_LINE, SPEC_STEP_TEXT),
        ("reconstruction", SPEC_RECON_LINE, SPEC_RECON_TEXT),
        ("events", SPEC_EVENTS_LINE, SPEC_EVENTS_TEXT),
    )
    rows = []
    for key, n, text in want:
        raw = _raw(n)
        rows.append({"key": key, "line": n, "ok": raw.strip() == text,
                     "raw": raw.strip()})
    return {"ok": all(r["ok"] for r in rows), "rows": rows,
            "spec": SPEC, "checked": len(rows)}


# ---------------------------------------------------------------------------
# 三,commit boundary 登記簿（人工，不猜）
# ---------------------------------------------------------------------------

def boundary_path(repo: Path | None = None) -> Path:
    return Path(repo or REPO) / ".forseti" / "workflow_boundary.jsonl"


def declare_boundary(workflow_id: str, state: str, *, declared_by: str,
                     actions: list[str] | None = None, why: str = "",
                     repo: Path | None = None) -> dict:
    """登記一件 workflow 有沒有跨 commit 邊界。

    只增不改,跟事件帳本同一條。`declared_by` 是必填而且不准是空字串 ——
    一筆沒有人認領的宣告,跟沒有宣告的差別只在畫面上比較好看。
    """
    if state not in BOUNDARY_STATES:
        raise ValueError(f"state 只能是 {BOUNDARY_STATES},拿到 {state!r}")
    if state == "UNDECLARED":
        raise ValueError("UNDECLARED 是「沒有人登記」的意思,不能拿來登記")
    if not declared_by or not declared_by.strip():
        raise ValueError("declared_by 必填:一筆沒有人認領的宣告不算宣告")
    if state in ("CROSSES", "CROSSED") and not actions:
        raise ValueError("說它跨邊界就要講跨的是哪個動作,"
                         f"合法的看 authority.COMMIT_BOUNDARY")
    rec = {
        "workflow_id": workflow_id,
        "state": state,
        "actions": list(actions or []),
        "why": why,
        "declared_by": declared_by,
        "declared_at": time.time(),
    }
    p = boundary_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def boundaries(repo: Path | None = None) -> dict:
    """讀登記簿。同一個 workflow 多筆時,**最後一筆有效**(只增不改)。

    壞掉的行不靜默跳過,計數回報 —— 一個被跳過的行跟一行不存在,
    在結果上長得一模一樣。
    """
    p = boundary_path(repo)
    latest: dict[str, dict] = {}
    total = bad = 0
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                rec = json.loads(line)
                wid = rec["workflow_id"]
            except Exception:
                bad += 1
                continue
            latest[wid] = rec
    return {"records": latest, "lines": total, "unreadable": bad,
            "path": str(p), "exists": p.exists()}


def boundary_of(workflow_id: str, repo: Path | None = None) -> dict:
    """單一 workflow 的 commit boundary。

    沒登記回 `UNDECLARED`,而且 `declared` 是 False。
    **UNDECLARED 不是 NONE** —— 前者是「沒有人回答過這個問題」,
    後者是「有人看過而且說不跨」,復原的時候這兩件事的下一步不一樣。
    """
    rec = boundaries(repo)["records"].get(workflow_id)
    if rec is None:
        return {"workflow_id": workflow_id, "state": "UNDECLARED",
                "declared": False, "actions": [],
                "why": "沒有人登記過。不從 objective 文字猜(B-05),"
                       "所以這是一個待回答的問題,不是「不跨邊界」",
                "how": "workflow.declare_boundary(wid, 'NONE'|'CROSSES'|"
                       "'CROSSED', declared_by=...)"}
    return {"workflow_id": workflow_id, "state": rec["state"],
            "declared": True, "actions": rec.get("actions", []),
            "why": rec.get("why", ""), "declared_by": rec.get("declared_by"),
            "declared_at": rec.get("declared_at")}


# ---------------------------------------------------------------------------
# 四,從耐久存放區重組
# ---------------------------------------------------------------------------

def _db(db: Path | None = None) -> Path:
    if db is not None:
        return Path(db)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ledger  # noqa: PLC0415
    return ledger.default_db()


def _terminal() -> tuple[str, ...]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ledger  # noqa: PLC0415
    return tuple(ledger.TERMINAL)


def _jsonlist(raw) -> list:
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except Exception:
        return []
    return v if isinstance(v, list) else []


def workflows(db: Path | None = None, repo: Path | None = None) -> dict:
    """把 tasks 讀成 §5 的 Workflow 形狀。

    **不新增表**,這是同一份 sqlite 的另一種讀法。
    `commit_boundary` 從登記簿來,不是從這張表來(那裡沒有這一欄)。
    """
    path = _db(db)
    if not path.exists():
        return {"available": False,
                "why": f"任務帳本不存在:{path}",
                "workflows": [], "count": 0, "db": str(path)}
    con = sqlite3.connect(path)
    try:
        rows = con.execute(
            "SELECT task_id, objective, current_state, current_owner,"
            " accepted_by, accepted_at, next_required_action"
            " FROM tasks ORDER BY accepted_at").fetchall()
        counts = dict(con.execute(
            "SELECT task_id, count(*) FROM steps GROUP BY 1").fetchall())
    finally:
        con.close()

    term = _terminal()
    out = []
    for (wid, obj, state, owner, acc_by, acc_at, nxt) in rows:
        out.append({
            "workflow_id": wid,
            "objective": obj,
            "state": state,
            "terminal": state in term,
            "owner": owner or acc_by,
            "owner_kind": "session_alias",
            "commit_boundary": boundary_of(wid, repo),
            "steps": counts.get(wid, 0),
            "accepted_at": acc_at,
            "next_required_action": nxt or "",
        })
    return {"available": True, "workflows": out, "count": len(out),
            "db": str(path),
            "note": "owner 是 session alias 不是持久身份,見 identity.py"}


def resume(workflow_id: str, db: Path | None = None,
           repo: Path | None = None) -> dict:
    """§17.1 Workflow Reconstruction:程序死掉之後接哪一步。

    **只讀磁碟。** 沒有任何 module-level 快取、沒有任何跨呼叫的狀態,
    所以另起一個程序跑答案要一樣 —— 那正是「不是靠模型記得」的
    機械定義,`test_另一個程序重跑答案一樣` 釘住它。

    回的四類分得很開,因為它們的下一步不一樣:

    - `ready`     依賴都終態了而且自己還沒終態 —— **現在就能做的**
    - `blocked`   還在等依賴,每一筆講得出在等誰
    - `done`      已經終態
    - `dangling`  依賴指到一個不存在的 step_id。這一類**不併進 blocked**,
                  那是資料壞了不是在等人,兩者的處理方式相反

    `approvals` 照 §17.1 那一行的第四個輸入。這條線現在只有
    `requires_human` 這個布林,沒有「誰批准了、什麼時候」,
    所以回的是「要不要人」不是「批准了沒有」,欄位名寫明這件事。
    """
    path = _db(db)
    if not path.exists():
        return {"ok": False, "why": f"任務帳本不存在:{path}",
                "workflow_id": workflow_id}
    con = sqlite3.connect(path)
    try:
        head = con.execute(
            "SELECT objective, current_state, current_owner,"
            " next_required_action, stop_conditions"
            " FROM tasks WHERE task_id=?", (workflow_id,)).fetchone()
        if head is None:
            return {"ok": False, "why": f"沒有這件 workflow:{workflow_id}",
                    "workflow_id": workflow_id}
        srows = con.execute(
            "SELECT step_id, seq, objective, dependencies, state,"
            " retry_count, requires_human, expected_outputs, next_action,"
            " assigned_worker, last_progress_at"
            " FROM steps WHERE task_id=? ORDER BY seq", (workflow_id,)
        ).fetchall()
    finally:
        con.close()

    term = _terminal()
    steps = []
    for (sid, seq, obj, deps, st, retry, rh, exp, nxt, worker, prog) in srows:
        steps.append({
            "step_id": sid, "seq": seq, "objective": obj,
            "depends_on": _jsonlist(deps), "status": st,
            "terminal": st in term, "retries": retry or 0,
            "requires_human": bool(rh),
            "expected_outputs": _jsonlist(exp),
            "next_action": nxt or "", "assigned_worker": worker,
            "last_progress_at": prog,
        })
    known = {s["step_id"] for s in steps}
    finished = {s["step_id"] for s in steps if s["terminal"]}

    ready, blocked, done, dangling = [], [], [], []
    for s in steps:
        missing = [d for d in s["depends_on"] if d not in known]
        if missing:
            dangling.append(dict(s, unknown_dependencies=missing,
                                 why="依賴指到不存在的 step,這是資料壞了"
                                     "不是在等人"))
            continue
        if s["terminal"]:
            done.append(s)
            continue
        waiting = [d for d in s["depends_on"] if d not in finished]
        if waiting:
            blocked.append(dict(s, waiting_on=waiting))
        else:
            ready.append(s)

    return {
        "ok": True,
        "workflow_id": workflow_id,
        "objective": head[0],
        "state": head[1],
        "owner": head[2],
        "owner_kind": "session_alias",
        "stop_conditions": _jsonlist(head[4]),
        "commit_boundary": boundary_of(workflow_id, repo),
        "ready": ready,
        "blocked": blocked,
        "done": done,
        "dangling": dangling,
        "counts": {"ready": len(ready), "blocked": len(blocked),
                   "done": len(done), "dangling": len(dangling),
                   "total": len(steps)},
        "retries": sum(s["retries"] for s in steps),
        "approvals": {
            "needs_human": [s["step_id"] for s in steps
                            if s["requires_human"] and not s["terminal"]],
            "measures": "要不要人,不是批准了沒有",
            "why": "steps 表只有 requires_human 這個布林,"
                   "沒有批准者與批准時間的欄位。§17.1 要的 approvals "
                   "是後者,所以這一格是半套,標明而不補一個猜的值",
        },
        "next_required_action": head[3] or "",
        "source": "v5.0 §17.1 第 471 行 Workflow Reconstruction",
        "reconstructed_from": str(path),
    }


# ---------------------------------------------------------------------------
# 五,§6.2 那四種事件實際有幾筆
# ---------------------------------------------------------------------------

def spec_events(db: Path | None = None) -> dict:
    """規格 §6.2 Workflow 類四種事件,帳本裡各幾筆。

    **不做同義詞對映。** 把 STEP_STATE 算成 STEP_START 等於把
    「我們沒照規格記」翻譯成「我們照規格記了」,而兩者的差別要到
    復原的時候才會顯現:STEP_STATE 記狀態轉換,STEP_COMMIT 記
    「這一步的效果已經對外生效」,後者才是 rollback 要找的那一筆。
    """
    path = _db(db)
    if not path.exists():
        return {"available": False, "why": f"任務帳本不存在:{path}",
                "spec_kinds": {}, "actual_top": []}
    con = sqlite3.connect(path)
    try:
        counts = {k: 0 for k in SPEC_EVENTS}
        for kind, n in con.execute(
                "SELECT kind, count(*) FROM events GROUP BY 1").fetchall():
            if kind in counts:
                counts[kind] = n
        top = con.execute(
            "SELECT kind, count(*) FROM events GROUP BY 1"
            " ORDER BY 2 DESC LIMIT 6").fetchall()
        total = con.execute("SELECT count(*) FROM events").fetchone()[0]
    finally:
        con.close()
    present = sum(1 for v in counts.values() if v)
    return {
        "available": True,
        "spec_kinds": counts,
        "spec_present": present,
        "spec_total": len(SPEC_EVENTS),
        "actual_top": [{"kind": k, "count": n} for k, n in top],
        "events_total": total,
        "note": ("帳本用自己的命名,沒有對映到規格那四種。"
                 "不做同義詞對映,理由見 spec_events 的說明"),
        "source": "v5.0 §6.2 第 194 行",
    }


# ---------------------------------------------------------------------------
# 六,總覽（畫面用）
# ---------------------------------------------------------------------------

def assess(db: Path | None = None, repo: Path | None = None) -> dict:
    """畫面要的形狀。**不在這裡重算任何東西**,只是挑。

    重算會變成兩份會分歧的實作,而分歧那天不會有錯誤訊息。
    """
    wf = workflows(db, repo)
    ev = spec_events(db)
    fl = fields()
    bd = boundaries(repo)

    live = [w for w in wf["workflows"] if not w["terminal"]]
    resumable = []
    for w in live:
        r = resume(w["workflow_id"], db, repo)
        if r.get("ok"):
            resumable.append({
                "workflow_id": w["workflow_id"],
                "objective": w["objective"],
                "state": w["state"],
                "counts": r["counts"],
                "ready_ids": [s["step_id"] for s in r["ready"]],
                "blocked_ids": [s["step_id"] for s in r["blocked"]],
                "boundary": r["commit_boundary"]["state"],
            })

    undeclared = [w["workflow_id"] for w in live
                  if w["commit_boundary"]["state"] == "UNDECLARED"]
    return {
        "available": wf["available"],
        "total": wf["count"],
        "live": len(live),
        "resumable": resumable,
        "fields": fl,
        "spec_events": ev,
        "boundary_registry": {"lines": bd["lines"],
                              "declared": len(bd["records"]),
                              "unreadable": bd["unreadable"],
                              "undeclared_live": undeclared},
        "honesty": [
            "external_refs 沒有資料來源,回 None 不回空清單",
            "commit_boundary 沒登記是 UNDECLARED,不是 NONE —— "
            "不從文字猜(B-05)",
            "owner 是 session alias 不是持久身份(identity.py 量過)",
            "outputs 是預期不是實際,欄位名保留 expected_",
            "規格 §6.2 那四種事件實測 "
            f"{ev.get('spec_present', 0)}/{len(SPEC_EVENTS)} 種有出現,"
            "不做同義詞對映",
        ],
        "source": "v5.0 §5 / §6.2 / §17.1",
    }


# ---------------------------------------------------------------------------

def _main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "--verify":
        print(json.dumps(verify_spec(), ensure_ascii=False, indent=2))
        return 0
    if len(argv) > 2 and argv[1] == "resume":
        print(json.dumps(resume(argv[2]), ensure_ascii=False, indent=2))
        return 0
    if len(argv) > 1 and argv[1] == "events":
        print(json.dumps(spec_events(), ensure_ascii=False, indent=2))
        return 0
    if len(argv) > 1 and argv[1] == "fields":
        print(json.dumps(fields(), ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(assess(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
