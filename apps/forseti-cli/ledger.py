#!/usr/bin/env python3
"""Task Ledger：外部任務真相。實作 F01-PEC-001 與 F02-TSM-001。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    ARCH-EXEC-001  sha256 4ca6689973e5
    F01-PEC-001    sha256 fe86cb2a1ab7
    F02-TSM-001    sha256 99ec01294dde

為什麼要有這個東西，用一個實測數字講：

    F06 第 5 節定義 HumanContinueBurden = 每個任務裡人類必須說「繼續」
    的次數，應趨近於零。2026-09-09 這一場實測 8 次。

    原因不是我懶。原因是義務只存在於模型的記憶裡，而回合結束記憶就散了。
    F01 的核心不變量說得很準：TURN_END MUST NOT imply TASK_END。
    要讓這句話成立，義務必須活在模型外面。這個檔案就是那個外面。

三個設計決定，每個都對應規格條文：

  狀態機以 F02 §2 的 canonical states 為準。F01 §3 另外提到 REPORTING、
  NEEDS_REVIEW、NO_OUTPUT 三個非終止狀態，F02 的狀態機沒有它們。
  兩份規格不一致，不自己補，記在 REQUIRED_READING 待澄清。

  verifier 要真的跑。CT-F02-01 要求「宣稱 done 但缺測試收據就維持
  VERIFYING」。如果 verifier 只是一個讓人填「已驗證」的欄位，這條測試
  就是假的，而假的驗證比沒有驗證更危險。

  report 不改變狀態（CT-F01-05、CT-F04-04）。報告是觀察通道不是流程關卡。
  這一條是那 8 次的直接修正。

零依賴。sqlite3 是標準庫。
"""

from __future__ import annotations

import hashlib
import json
import shlex
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 狀態機（F02 §2）
# ---------------------------------------------------------------------------

# PROPOSED → ACCEPTED → RUNNING ↔ WAITING_DEPENDENCY ↔ BLOCKED
#            ↔ NEEDS_HUMAN ↔ VERIFYING → VERIFIED_COMPLETE
ACTIVE = ("RUNNING", "WAITING_DEPENDENCY", "BLOCKED", "NEEDS_HUMAN", "VERIFYING")

# F01 §3：只有這四個是終止。其餘一律非終止,包含「我報告完了」。
TERMINAL = ("VERIFIED_COMPLETE", "CANCELLED_BY_OWNER", "FAILED_TERMINAL", "SUPERSEDED")

STATES = ("PROPOSED", "ACCEPTED", *ACTIVE, *TERMINAL)

# 任何狀態都能被取消或取代,那是擁有者的權力,不受狀態機限制。
_OWNER_EXIT = ("CANCELLED_BY_OWNER", "SUPERSEDED")

ALLOWED: dict[str, tuple[str, ...]] = {
    "PROPOSED": ("ACCEPTED", *_OWNER_EXIT),
    "ACCEPTED": ("RUNNING", "WAITING_DEPENDENCY", "NEEDS_HUMAN", *_OWNER_EXIT),
    # F02 §2 的 ↔ 鏈:這五個之間可以互轉
    "RUNNING": (*ACTIVE, "FAILED_TERMINAL", *_OWNER_EXIT),
    "WAITING_DEPENDENCY": (*ACTIVE, "FAILED_TERMINAL", *_OWNER_EXIT),
    "BLOCKED": (*ACTIVE, "FAILED_TERMINAL", *_OWNER_EXIT),
    "NEEDS_HUMAN": (*ACTIVE, "FAILED_TERMINAL", *_OWNER_EXIT),
    # 驗證沒過要回去做,不是直接失敗
    "VERIFYING": (*ACTIVE, "VERIFIED_COMPLETE", "FAILED_TERMINAL", *_OWNER_EXIT),
    "VERIFIED_COMPLETE": (),
    "CANCELLED_BY_OWNER": (),
    "FAILED_TERMINAL": (),
    "SUPERSEDED": (),
}


class TransitionError(Exception):
    """不合法的狀態轉換,或缺少事件因。

    F02 §5：Every transition MUST have an event cause.
    所以「沒給理由」跟「狀態不合法」是同一類錯誤,都不准過。
    """


def is_terminal(state: str) -> bool:
    return state in TERMINAL


# ---------------------------------------------------------------------------
# Verifier（F02 §4 的 verifier[]）
# ---------------------------------------------------------------------------

@dataclass
class VerifyResult:
    ok: bool
    spec: str
    detail: str


def run_verifier(spec: str, cwd: Path | None = None, timeout: int = 120) -> VerifyResult:
    """跑一條 verifier。

    支援兩種,都是真的去看,不是問誰。

        file:<path>   檔案存在且非空
        cmd:<command> 指令 exit code 0

    刻意不支援 "manual" 或 "asserted" 這種由人或模型宣告通過的形式。
    那種東西就是 claim,而這整個專案存在的理由就是不信 claim。
    """
    if spec.startswith("file:"):
        p = Path(spec[5:]).expanduser()
        if not p.is_absolute() and cwd:
            p = cwd / p
        if not p.exists():
            return VerifyResult(False, spec, f"不存在：{p}")
        try:
            size = p.stat().st_size
        except OSError as e:
            return VerifyResult(False, spec, f"讀不到：{e}")
        if size == 0:
            return VerifyResult(False, spec, f"空檔案：{p}")
        return VerifyResult(True, spec, f"{size:,} bytes")

    if spec.startswith("cmd:"):
        cmd = spec[4:]
        try:
            r = subprocess.run(shlex.split(cmd), cwd=str(cwd) if cwd else None,
                               capture_output=True, timeout=timeout, text=True)
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            return VerifyResult(False, spec, f"跑不起來：{e}")
        tail = (r.stderr or r.stdout or "").strip().splitlines()
        return VerifyResult(r.returncode == 0, spec,
                            f"exit {r.returncode}" + (f"　{tail[-1][:80]}" if tail else ""))

    return VerifyResult(False, spec, "不認得的 verifier 形式（只支援 file: 與 cmd:）")


# ---------------------------------------------------------------------------
# 儲存
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  task_id TEXT PRIMARY KEY,
  owner_goal_ref TEXT, objective TEXT,
  accepted_at REAL, accepted_by TEXT,
  deliverables TEXT, definition_of_done TEXT, stop_conditions TEXT,
  evidence_contract TEXT,
  current_state TEXT, current_owner TEXT, next_required_action TEXT,
  terminal_reason TEXT
);
CREATE TABLE IF NOT EXISTS steps (
  step_id TEXT PRIMARY KEY, task_id TEXT, seq INTEGER,
  objective TEXT, dependencies TEXT, assigned_worker TEXT,
  state TEXT, started_at REAL, last_progress_at REAL,
  expected_outputs TEXT, verifier TEXT, evidence_refs TEXT,
  retry_count INTEGER DEFAULT 0, next_action TEXT,
  worker_can_report TEXT DEFAULT 'unknown'
);
CREATE TABLE IF NOT EXISTS events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  at REAL, task_id TEXT, step_id TEXT,
  kind TEXT, from_state TEXT, to_state TEXT,
  cause TEXT, actor TEXT, payload TEXT
);
CREATE INDEX IF NOT EXISTS idx_steps_task ON steps(task_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id, at);
"""

SCHEMA_VERSION = 3

# F04 §3 要求的 worker 事件。這八種是 worker 那一端會發出的,
# 其餘(TASK_STATE、DISPATCH、REASSIGN…)是控制端自己的紀錄。
WORKER_EVENTS = (
    "WORKER_ACCEPTED", "WORKER_PROGRESS", "WORKER_COMPLETION", "WORKER_BLOCKED",
    "WORKER_FAILED", "WORKER_CANCELLED", "EVIDENCE_AVAILABLE", "ARTIFACT_CHANGED",
)

# B-10：worker 能不能回話,是派工方本來就知道的事。
#   full        能執行指令,所以能直接寫帳本
#   write_only  只能寫檔案,要靠收件匣
#   unknown     沒有人宣告過。這不是「大概可以」,是「沒問過」,
#               所以判斷時要把它當成一個已知的未知,不是預設值。
CAN_REPORT = ("full", "write_only", "unknown")

# 收件匣的別名。這張表只收「實測真的發生過的誤用」,不預先想像。
#
# 每一條都要附出處,不然它會慢慢長成一張什麼都收的表,那等於沒有協定 ——
# 協定的價值在於下游能對著固定的名字寫邏輯。
#
#   WORKER_DONE  2026-09-09 claude-p-worker-3。訊息裡列了八種,它仍然
#                寫了這個。那不是它不小心,是這個名字比 COMPLETION 更
#                像人會講的話。可預期的寫法失誤要由設計吸收,不是靠
#                要求對方更小心。
ALIASES = {
    "WORKER_DONE": "WORKER_COMPLETION",
}


def _migrate(con: sqlite3.Connection) -> None:
    """schema 演進。只加欄位,絕不 drop。

    這裡跟 recall.py 的做法剛好相反,差別值得寫下來:

      索引是純函數的產物,原始 jsonl 沒動過,所以 schema 一改就整個
      刪掉重建,重跑三十秒的事。

      帳本是唯一真相。它記的是「誰接了什麼、還欠什麼」,那些東西
      不存在於任何別的地方,刪掉就沒了。所以只能 ALTER 不能 DROP,
      而且加欄位一定要有預設值,舊資料才不會變成半殘。
    """
    have = con.execute("PRAGMA user_version").fetchone()[0]
    if have >= SCHEMA_VERSION:
        return
    cols = {r[1] for r in con.execute("PRAGMA table_info(events)")}
    if "idem_key" not in cols:
        con.execute("ALTER TABLE events ADD COLUMN idem_key TEXT")
    scols = {r[1] for r in con.execute("PRAGMA table_info(steps)")}
    if "requires_human" not in scols:
        con.execute("ALTER TABLE steps ADD COLUMN requires_human INTEGER DEFAULT 0")
    if "worker_can_report" not in scols:
        # B-10：worker 能不能回報,是派工方本來就知道的事,不該由控制端
        # 從沉默去猜。舊資料一律 unknown,因為它們確實不知道 —— 填
        # 'full' 會把一個沒問過的問題偽裝成已經有答案。
        con.execute("ALTER TABLE steps ADD COLUMN worker_can_report TEXT"
                    " DEFAULT 'unknown'")
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_events_idem"
                " ON events(idem_key) WHERE idem_key IS NOT NULL")
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()


def default_db(root: Path | None = None) -> Path:
    """每個專案一本帳,但檔案不能放在專案目錄裡。

    第一版放在 `<repo>/.forseti/ledger.db`,理由是任務屬於專案不屬於機器。
    實測失敗:這個 repo 在 exFAT 外接碟上,而 exFAT 不支援 sqlite 需要的
    POSIX advisory lock。症狀是普通檔案寫得進去,sqlite 一寫就
    「attempt to write a readonly database」,錯誤訊息完全沒有提到鎖。

    所以帳本放在 home 的 APFS,用專案路徑的 hash 區分,一個專案一本。
    這不是把它變成全機的東西,它仍然綁定那個專案路徑。

    代價要講清楚:帳本不跟著 repo 走,換機器就沒了。要跨機器就得匯出。
    這是檔案系統逼出來的取捨,不是設計偏好。
    """
    base = (root or Path(__file__).resolve().parents[2]).resolve()
    key = hashlib.sha256(str(base).encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".forseti" / "ledgers" / f"{base.name}-{key}.db"


def connect(db: Path | None = None) -> sqlite3.Connection:
    path = db or default_db()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrate(con)
    con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()
    return con


def _worker_mod():
    """延遲載入 worker,避免兩個模組互相 import。"""
    import importlib
    import sys as _sys
    try:
        return importlib.import_module("worker")
    except ImportError:
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        return importlib.import_module("worker")


def _starvation_mod():
    import importlib
    import sys as _sys
    try:
        return importlib.import_module("starvation")
    except ImportError:
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        return importlib.import_module("starvation")


def _continuity_mod():
    import importlib
    import sys as _sys
    try:
        return importlib.import_module("continuity")
    except ImportError:
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        return importlib.import_module("continuity")


def _watchdog_mod():
    import importlib
    import sys as _sys
    try:
        return importlib.import_module("watchdog")
    except ImportError:
        _sys.path.insert(0, str(Path(__file__).resolve().parent))
        return importlib.import_module("watchdog")


def _j(v) -> str:
    return json.dumps(v or [], ensure_ascii=False)


def _u(s: str | None):
    try:
        return json.loads(s) if s else []
    except (ValueError, TypeError):
        return []


# ---------------------------------------------------------------------------
# 契約
# ---------------------------------------------------------------------------

def qualify(task_id: str, local_id: str) -> str:
    """F02 §4 的 TaskStep 同時有 step_id 與 task_id,代表 step_id 只在任務內唯一。

    資料庫需要全域唯一的鍵,所以存的是 task_id/step_id。
    第一版把 step_id 當全域唯一,兩個任務都用 s1 就撞主鍵。
    """
    return local_id if "/" in local_id else f"{task_id}/{local_id}"


@dataclass
class Step:
    step_id: str
    objective: str
    expected_outputs: list[str] = field(default_factory=list)
    verifier: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    state: str = "PROPOSED"
    seq: int = 0
    assigned_worker: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    retry_count: int = 0
    next_action: str = ""
    # F04 §5:自動派工的四個條件之一是「不需要人的決定」。
    # 這個旗標讓那個條件變成資料,不是靠誰記得。
    requires_human: bool = False


class Ledger:
    """F01 的 PersistentExecutionContract 與 F02 的狀態機。"""

    def __init__(self, db: Path | None = None, cwd: Path | None = None):
        self.db_path = db or default_db()
        self.con = connect(db)
        self.cwd = cwd or Path(__file__).resolve().parents[2]

    # -- 事件 ------------------------------------------------------------

    def _event(self, kind: str, cause: str, actor: str = "system",
               task_id: str = "", step_id: str = "",
               from_state: str = "", to_state: str = "", payload=None,
               idem_key: str | None = None) -> bool:
        """記一筆事件。回傳 False 代表這個 idem_key 已經記過,這次是重複。

        F04 §4：Events are durable and idempotent. Duplicate completion
        MUST NOT execute the next step twice。冪等靠資料庫的 unique index,
        不靠呼叫端記得檢查 —— 呼叫端會忘記,索引不會。
        """
        try:
            self.con.execute(
                "INSERT INTO events (at,task_id,step_id,kind,from_state,to_state,"
                "cause,actor,payload,idem_key) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (time.time(), task_id, step_id, kind, from_state, to_state, cause, actor,
                 json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                 idem_key))
        except sqlite3.IntegrityError:
            return False
        self.con.commit()
        return True

    # -- 接受任務（F01 §5）------------------------------------------------

    def accept(self, objective: str, steps: list[Step], *,
               definition_of_done: list[str] | None = None,
               deliverables: list[str] | None = None,
               stop_conditions: list[str] | None = None,
               owner_goal_ref: str = "", accepted_by: str = "main") -> str:
        """接受一件工作,義務從這一刻起活在模型外面。

        F01 §5：使用者要求執行(不是要求建議)時,說出「我來做」等同建立
        執行承諾。所以呼叫這個函式就是那句話的落地形式。
        """
        if not steps:
            raise ValueError("一個沒有步驟的任務無法追蹤未完成項,拒絕接受")
        task_id = "T-" + uuid.uuid4().hex[:10]
        self.con.execute(
            "INSERT INTO tasks (task_id,owner_goal_ref,objective,accepted_at,accepted_by,"
            "deliverables,definition_of_done,stop_conditions,evidence_contract,"
            "current_state,current_owner,next_required_action,terminal_reason)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
            (task_id, owner_goal_ref, objective, time.time(), accepted_by,
             _j(deliverables), _j(definition_of_done), _j(stop_conditions),
             _j([v for s in steps for v in s.verifier]),
             "ACCEPTED", accepted_by, steps[0].objective))
        for i, s in enumerate(steps):
            # 步驟建立時就是 ACCEPTED:任務被擁有者接受的那一刻,步驟一起被接受了。
            # 讓步驟停在 PROPOSED 會需要第二次接受動作,而規格裡沒有那個動作。
            self.con.execute(
                "INSERT INTO steps (step_id,task_id,seq,objective,dependencies,assigned_worker,"
                "state,started_at,last_progress_at,expected_outputs,verifier,evidence_refs,"
                "retry_count,next_action) VALUES (?,?,?,?,?,?,?,NULL,NULL,?,?,?,0,?)",
                (qualify(task_id, s.step_id), task_id, i, s.objective,
                 _j([qualify(task_id, d) for d in s.dependencies]), s.assigned_worker,
                 "ACCEPTED", _j(s.expected_outputs), _j(s.verifier), _j(s.evidence_refs),
                 s.next_action))
            if s.requires_human:
                self.con.execute("UPDATE steps SET requires_human=1 WHERE step_id=?",
                                 (qualify(task_id, s.step_id),))
        self.con.commit()
        self._event("TASK_ACCEPTED", "owner requested execution", accepted_by,
                    task_id=task_id, to_state="ACCEPTED",
                    payload={"steps": [qualify(task_id, s.step_id) for s in steps]})
        return task_id

    def sid(self, task_id: str, local_id: str) -> str:
        """任務內的短 id 組成全域引用。"""
        return qualify(task_id, local_id)

    # -- 狀態轉換（F02 §5）------------------------------------------------

    def transition(self, task_id: str, to_state: str, cause: str,
                   actor: str = "system", terminal_reason: str | None = None) -> None:
        """轉換任務狀態。沒有 cause 不准轉,這是 F02 §5 的硬要求。"""
        if not cause or not cause.strip():
            raise TransitionError("F02 §5：每一次轉換都必須有事件因，不接受空的 cause")
        row = self.con.execute(
            "SELECT current_state FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise TransitionError(f"沒有這個任務：{task_id}")
        cur = row[0]
        if to_state not in STATES:
            raise TransitionError(f"不是合法狀態：{to_state}")
        if to_state not in ALLOWED.get(cur, ()):
            raise TransitionError(f"不允許的轉換：{cur} → {to_state}")
        self.con.execute(
            "UPDATE tasks SET current_state=?, terminal_reason=? WHERE task_id=?",
            (to_state, terminal_reason, task_id))
        self.con.commit()
        self._event("TASK_STATE", cause, actor, task_id=task_id,
                    from_state=cur, to_state=to_state)

    def step_transition(self, step_id: str, to_state: str, cause: str,
                        actor: str = "system") -> None:
        if not cause or not cause.strip():
            raise TransitionError("F02 §5：每一次轉換都必須有事件因")
        row = self.con.execute(
            "SELECT task_id,state FROM steps WHERE step_id=?", (step_id,)).fetchone()
        if row is None:
            raise TransitionError(f"沒有這個步驟：{step_id}")
        task_id, cur = row
        if to_state not in ALLOWED.get(cur, ()):
            raise TransitionError(f"不允許的轉換：{cur} → {to_state}")
        now = time.time()
        if to_state == "RUNNING" and cur in ("PROPOSED", "ACCEPTED"):
            self.con.execute("UPDATE steps SET state=?, started_at=?, last_progress_at=?"
                             " WHERE step_id=?", (to_state, now, now, step_id))
        else:
            self.con.execute("UPDATE steps SET state=?, last_progress_at=? WHERE step_id=?",
                             (to_state, now, step_id))
        self.con.commit()
        self._event("STEP_STATE", cause, actor, task_id=task_id, step_id=step_id,
                    from_state=cur, to_state=to_state)

    # -- 報告（CT-F01-05、CT-F04-04）--------------------------------------

    def report(self, task_id: str, text: str, actor: str = "main") -> str:
        """記錄一則進度報告。刻意不改變任何狀態。

        這個函式沒有回傳狀態、沒有參數可以順便改狀態,是故意的。
        報告是觀察通道不是流程關卡(F04 §6)。今天那 8 次「繼續」,
        每一次前面都是一則看起來很完整的報告。
        """
        self._event("PROGRESS_REPORT", "report only, no state change", actor,
                    task_id=task_id, payload={"text": text[:4000]})
        return self.state_of(task_id)

    # -- 查詢 ------------------------------------------------------------

    def state_of(self, task_id: str) -> str:
        r = self.con.execute("SELECT current_state FROM tasks WHERE task_id=?",
                             (task_id,)).fetchone()
        return r[0] if r else ""

    def steps_of(self, task_id: str) -> list[dict]:
        rows = self.con.execute(
            "SELECT step_id,seq,objective,dependencies,state,expected_outputs,verifier,"
            "evidence_refs,retry_count,next_action,assigned_worker,requires_human"
            " FROM steps WHERE task_id=? ORDER BY seq", (task_id,)).fetchall()
        return [{
            "step_id": r[0], "local_id": r[0].split("/")[-1],
            "requires_human": bool(r[11]),
            "seq": r[1], "objective": r[2], "dependencies": _u(r[3]),
            "state": r[4], "expected_outputs": _u(r[5]), "verifier": _u(r[6]),
            "evidence_refs": _u(r[7]), "retry_count": r[8], "next_action": r[9],
            "assigned_worker": r[10],
        } for r in rows]

    def next_step(self, task_id: str) -> dict | None:
        """下一個可以動的步驟。

        F04 §5：前一步驗證過、依賴允許、下一步已授權、不需要人的決定,
        就自動派工。這個函式回答「哪一步」,派不派是呼叫端的事。
        """
        if is_terminal(self.state_of(task_id)):
            return None
        steps = self.steps_of(task_id)
        done = {s["step_id"] for s in steps if s["state"] == "VERIFIED_COMPLETE"}
        for s in steps:
            if s["state"] in TERMINAL:
                continue
            if all(d in done for d in s["dependencies"]):
                return s
        return None

    # -- 驗證（CT-F02-01）------------------------------------------------

    def verify_step(self, step_id: str, actor: str = "system") -> tuple[bool, list[VerifyResult]]:
        """跑這一步的 verifier。全過才進 VERIFIED_COMPLETE。

        CT-F02-01：宣稱 done 但缺測試收據,狀態維持 VERIFYING/RUNNING。
        這裡的實作是:沒過就轉回 RUNNING 並累加 retry_count,
        而不是留在 VERIFYING 假裝還在驗。
        """
        row = self.con.execute(
            "SELECT task_id,state,verifier,evidence_refs,retry_count FROM steps WHERE step_id=?",
            (step_id,)).fetchone()
        if row is None:
            raise TransitionError(f"沒有這個步驟：{step_id}")
        task_id, cur, vspec, erefs, retry = row
        specs = _u(vspec)

        if not specs:
            # 沒有 verifier 的步驟不准自己宣稱完成。這不是嚴格,
            # 是因為「沒有驗證方式」跟「驗證過了」在帳本裡必須看得出差別。
            self._event("VERIFY_SKIPPED", "step has no verifier", actor,
                        task_id=task_id, step_id=step_id)
            return False, []

        if cur not in (*ACTIVE, "VERIFYING"):
            # 驗證一個還沒開工的步驟不是例外,是一個明確的「不通過」。
            # 讓它爆 TransitionError 會讓呼叫端以為是程式錯,
            # 實際上這是驗證結果:沒做怎麼會過。
            self._event("VERIFY_REFUSED", f"step is {cur}, not started", actor,
                        task_id=task_id, step_id=step_id)
            return False, [VerifyResult(False, "", f"步驟還沒開工（{cur}），沒有東西可驗")]

        results = [run_verifier(s, cwd=self.cwd) for s in specs]
        ok = all(r.ok for r in results)

        if cur != "VERIFYING":
            self.step_transition(step_id, "VERIFYING", "verification started", actor)

        if ok:
            refs = _u(erefs) + [f"{r.spec} → {r.detail}" for r in results]
            self.con.execute("UPDATE steps SET evidence_refs=? WHERE step_id=?",
                             (_j(refs), step_id))
            self.con.commit()
            self.step_transition(step_id, "VERIFIED_COMPLETE",
                                 f"{len(results)} verifier 全過", actor)
        else:
            failed = [r for r in results if not r.ok]
            self.con.execute("UPDATE steps SET retry_count=? WHERE step_id=?",
                             (retry + 1, step_id))
            self.con.commit()
            self.step_transition(step_id, "RUNNING",
                                 f"驗證未過：{failed[0].spec}　{failed[0].detail}", actor)
        return ok, results

    # -- 派工與收件（F03-CSI-001、F04 §3）---------------------------------

    def dispatch(self, step_id: str, worker: str, cause: str = "", *,
                 auto: bool = False, can_report: str = "") -> None:
        """把一個步驟派給 worker。

        auto=True 代表這一次是系統自己接上的，沒有人開口叫它繼續。
        這個旗標寫進事件 payload，不從 cause 的字面推。先前 continuity()
        的做法是掃 cause 裡有沒有「自動」兩個字，於是呼叫端只要自己給了
        cause（例如「owner 已決定」），那一次真的自動派工就會從指標裡
        消失。一個會漏算自己的指標，比沒有指標更糟，因為它看起來有數字。
        """
        row = self.con.execute("SELECT task_id,state FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        if row is None:
            raise TransitionError(f"沒有這個步驟：{step_id}")
        task_id, cur = row
        if can_report:
            if can_report not in CAN_REPORT:
                raise ValueError(f"worker_can_report 只能是 {'/'.join(CAN_REPORT)}，"
                                 f"收到 {can_report}")
            self.con.execute(
                "UPDATE steps SET assigned_worker=?, worker_can_report=?"
                " WHERE step_id=?", (worker, can_report, step_id))
        else:
            self.con.execute("UPDATE steps SET assigned_worker=? WHERE step_id=?",
                             (worker, step_id))
        self.con.commit()
        if cur != "RUNNING":
            self.step_transition(step_id, "RUNNING", cause or f"派給 {worker}", actor=worker)
        self._event("DISPATCH", cause or f"派給 {worker}", actor="controller",
                    task_id=task_id, step_id=step_id,
                    payload={"worker": worker, "auto": bool(auto)})

    def stash(self, step_id: str, text: str, label: str = "log") -> str:
        """把原始輸出落檔，回傳 packet 用的引用。細節見 worker.stash_raw。"""
        w = _worker_mod()
        row = self.con.execute("SELECT task_id FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        return w.stash_raw(text, task_id=row[0] if row else "", step_id=step_id,
                           store=w.default_store(self.db_path), label=label)

    def submit_result(self, packet, *, strict: bool = True):
        """worker 交回結果。回傳 worker.Receipt。

        關鍵一條：worker 說 COMPLETED 只讓步驟進 VERIFYING，不是
        VERIFIED_COMPLETE。F02 §3 說得很清楚，模型說 done 而要求未滿足時
        任務維持非終止。要進 VERIFIED_COMPLETE 得跑 verify_step()，
        而那是真的去看磁碟。

        這是整條交接鏈裡最容易抄近路的地方：讓 submit 直接標完成會讓
        流程順很多，也會讓整套驗證失去意義。
        """
        w = _worker_mod()
        row = self.con.execute(
            "SELECT task_id,state,expected_outputs FROM steps WHERE step_id=?",
            (packet.step_id,)).fetchone()
        if row is None:
            raise TransitionError(f"沒有這個步驟：{packet.step_id}")
        task_id, cur, expected = row

        if cur not in (*ACTIVE, "VERIFYING"):
            # 收到一個沒被派工的步驟的結果,代表流程有洞(F04 §2 的順序是
            # DISPATCH 先於 COMPLETION)。這是明確的拒收,不是例外:
            # 例外會讓呼叫端以為程式壞了,實際上壞的是流程。
            receipt = w.Receipt(accepted=False, packet=packet,
                                violations=[f"步驟狀態是 {cur}，還沒有被派工。"
                                            f"先 dispatch() 再收結果"])
            self._event("WORKER_RESULT_REFUSED", f"step is {cur}, never dispatched",
                        actor="controller", task_id=task_id, step_id=packet.step_id)
            return receipt

        receipt = w.receive(packet, expected_outputs=_u(expected), strict=strict)

        self._event("WORKER_RESULT",
                    receipt.brief() if receipt.accepted else "packet 被拒收",
                    actor=packet.step_id, task_id=task_id, step_id=packet.step_id,
                    payload={"accepted": receipt.accepted,
                             "violations": receipt.violations,
                             "status": packet.status,
                             "unknowns": packet.unresolved_unknowns,
                             "out_of_scope": packet.out_of_scope})

        if not receipt.accepted:
            return receipt

        if packet.evidence_refs or packet.raw_log_refs:
            cur_refs = _u(self.con.execute(
                "SELECT evidence_refs FROM steps WHERE step_id=?",
                (packet.step_id,)).fetchone()[0])
            self.con.execute("UPDATE steps SET evidence_refs=? WHERE step_id=?",
                             (_j(cur_refs + packet.evidence_refs + packet.raw_log_refs),
                              packet.step_id))
            self.con.commit()

        if packet.status == "COMPLETED":
            self.step_transition(packet.step_id, "VERIFYING",
                                 "worker 宣稱完成，等驗證", actor="controller")
        elif packet.status == "BLOCKED":
            self.step_transition(packet.step_id, "BLOCKED",
                                 "；".join(packet.blockers)[:200] or "worker 回報卡住",
                                 actor="controller")
        elif packet.status == "FAILED":
            self.con.execute(
                "UPDATE steps SET retry_count=retry_count+1 WHERE step_id=?",
                (packet.step_id,))
            self.con.commit()
            if cur != "RUNNING":
                self.step_transition(packet.step_id, "RUNNING",
                                     "worker 回報失敗，等重試或重派", actor="controller")
        return receipt

    def reassign(self, step_id: str, new_worker: str, cause: str) -> None:
        """換一個 worker。任務不動，因為連續性不在 worker 身上。

        CT-F03-04：worker 死掉，任務保留並可重派。這個方法刻意不碰
        步驟狀態 —— 換人不是進度。
        """
        row = self.con.execute("SELECT task_id,assigned_worker FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        if row is None:
            raise TransitionError(f"沒有這個步驟：{step_id}")
        task_id, old = row
        self.con.execute("UPDATE steps SET assigned_worker=?, retry_count=retry_count+1"
                         " WHERE step_id=?", (new_worker, step_id))
        self.con.commit()
        self._event("REASSIGN", cause, actor="controller", task_id=task_id, step_id=step_id,
                    payload={"from": old, "to": new_worker})

    # -- 事件驅動（F04-EVT-001）-------------------------------------------

    def worker_event(self, kind: str, step_id: str, cause: str, *,
                     worker: str = "", payload=None, idem_key: str | None = None) -> bool:
        """記一筆 worker 事件。回傳 False 代表是重複事件（已被冪等擋下）。

        F04 §3 列了八種 worker 事件,這裡只收那八種。不在清單裡的一律
        拒絕,因為「事件種類可以隨便取名」等於沒有事件協定 ——
        下游沒辦法對著一組不固定的名字寫邏輯。
        """
        if kind not in WORKER_EVENTS:
            raise ValueError(f"不是 F04 §3 定義的 worker 事件：{kind}。"
                             f"合法的是 {'/'.join(WORKER_EVENTS)}")
        row = self.con.execute("SELECT task_id FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        if row is None:
            raise TransitionError(f"沒有這個步驟：{step_id}")
        fresh = self._event(kind, cause, actor=worker or "worker", task_id=row[0],
                            step_id=step_id, payload=payload, idem_key=idem_key)
        if fresh and kind == "WORKER_PROGRESS":
            # 進度訊號要留時間戳,F05 的停滯偵測靠它分辨「久」與「卡住」。
            self.con.execute("UPDATE steps SET last_progress_at=? WHERE step_id=?",
                             (time.time(), step_id))
            self.con.commit()
        return fresh

    # -- 不需要執行權限的回報通道（B-10）---------------------------------

    def inbox_dir(self, step_id: str) -> Path:
        """這一步的收件匣。worker 只要能寫檔案就能回報。

        B-10：回報通道原本假設 worker 能執行 shell，因為送出一筆事件的
        方式是跑一行 python。實測發現那個假設不成立：一個用
        `--permission-mode acceptEdits` 開的 worker，Write 允許、Bash 被擋，
        於是它交得出 5,952 bytes 的合格產物，卻連一句「我接下了」都送不出去。

        能做事跟能回話是兩種不同的權限。這個收件匣把後者的門檻降到跟
        前者一樣：寫一個檔案。

        放在 home 不放 repo，跟帳本同一個理由（exFAT 跑不了 sqlite，
        而且回報不該污染工作目錄）。
        """
        safe = step_id.replace("/", "__").replace("..", "_")
        # 放在 repo 裡，不放 home。這一條是被實測推翻之後改的。
        #
        # 第一版放 ~/.forseti/inbox/，理由是「回報不該污染工作目錄」。
        # 實測結果：那個 worker 三條路全被擋（Write 工具、Bash 重導向、
        # 單指令重導向），因為它的沙盒白名單只有 repo 目錄，home 在外面。
        # 它自己的診斷比我的假設精確：沉默不是因為死掉，是因為寫不進去，
        # 而那兩件事在帳本裡長得一模一樣。
        #
        # 污染工作目錄的成本，遠低於通道整條斷掉。而且放 repo 還有一個
        # 更重要的性質：worker 本來就有 repo 的寫入權限，因為它要寫產物。
        # 於是「能做事」就蘊含「能回話」，不必再另外要一份權限。
        #
        # 帳本仍然留在 home，那是另一回事：exFAT 跑不了 sqlite 的鎖，
        # 而收件匣只是普通檔案，沒有那個限制。
        return self.cwd / ".forseti" / "inbox" / safe

    def collect_inbox(self, step_id: str) -> list[str]:
        """把收件匣裡的檔案轉成真的事件。回傳收到的事件種類。

        檔案格式刻意做到最簡單：第一行是事件種類，其餘是說明。
        一個檔案一筆事件，不用 append，因為 read-modify-write 對一個
        只有 Write 的 worker 是額外的失敗機會。

        守住的邊界：只收 F04 §3 那八種，而且它們全部是宣稱型。
        worker 寫一個檔案說自己完成了，不會讓步驟變成 VERIFIED_COMPLETE ——
        那仍然只有 verifier 說了算。收件匣降低的是回報的門檻，
        不是驗證的門檻。
        """
        d = self.inbox_dir(step_id)
        if not d.is_dir():
            return []
        done = d / ".done"
        got = []
        # `._` 開頭的是 macOS 在 exFAT 上寫的 AppleDouble 附屬檔，
        # 每個真檔案都會多出一個。不濾掉的話一則回報會被算成兩則，
        # 而且第二則的內容是二進位垃圾。tools/orphans.mjs 因為同一個
        # 原因假警報過兩次，那個教訓寫在 tools/README.md。
        for f in sorted(d.glob("*.txt")):
            if f.name.startswith("._"):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                continue
            head, _, body = text.partition("\n")
            # 第一行可能整行都是種類,也可能是「種類 說明」寫在同一行。
            # 合法的種類都沒有空白,所以取第一個 token 是安全的,
            # 而且省掉一種可預期的寫法失誤。
            first = head.strip().split()
            kind = ALIASES.get(first[0].upper(), first[0].upper()) if first else ""
            body = (" ".join(first[1:]) + "\n" + body).strip()
            if kind not in WORKER_EVENTS:
                # 不認得的種類不丟掉也不當成事件。丟掉會讓 worker 的話
                # 消失得無聲無息,那正是這個通道要解決的問題。
                # body 一定要一起留:2026-09-09 第一版只記了檔名與第一行,
                # 於是 worker 寫了什麼還是消失了一半,那等於沒有做到
                # 上面那句話宣稱的事。
                self._event("INBOX_UNKNOWN_KIND",
                            f"{f.name}：{head.strip()[:40]}　{body[:160]}",
                            actor="controller", step_id=step_id,
                            task_id=self._task_of_step(step_id),
                            payload={"raw_kind": head.strip()[:60], "body": body[:2000]})
                got.append(f"（不認得的種類 {kind[:24]}）")
            else:
                self.worker_event(kind, step_id, body.strip()[:200] or kind,
                                  worker="inbox",
                                  idem_key=f"inbox:{step_id}:{f.name}")
                got.append(kind)
            try:
                done.mkdir(parents=True, exist_ok=True)
                f.rename(done / f.name)
            except OSError:
                pass
        return got

    def _task_of_step(self, step_id: str) -> str:
        row = self.con.execute("SELECT task_id FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        return row[0] if row else ""

    def can_report(self, step_id: str) -> str:
        row = self.con.execute(
            "SELECT worker_can_report FROM steps WHERE step_id=?",
            (step_id,)).fetchone()
        return (row[0] if row and row[0] else "unknown")

    def auto_dispatch(self, task_id: str, worker: str, cause: str = "") -> dict | None:
        """F04 §5 的自動派工。四個條件都滿足才派。

        回傳被派出去的步驟，或 None。None 有三種意思，呼叫端要能分辨，
        所以需要人的決定時任務會被轉成 NEEDS_HUMAN，那是看得見的狀態，
        不是一個安靜的 None。

        這個方法是「不要叫人說繼續」的具體形式：條件滿足就自己走，
        不滿足就明確講出卡在哪一個條件。
        """
        if is_terminal(self.state_of(task_id)):
            return None
        nxt = self.next_step(task_id)
        if nxt is None:
            return None
        if nxt["requires_human"]:
            if self.state_of(task_id) != "NEEDS_HUMAN":
                self.transition(task_id, "NEEDS_HUMAN",
                                f"{nxt['local_id']} 需要 owner 決定：{nxt['objective']}",
                                actor="controller")
            return None
        if self.state_of(task_id) in ("NEEDS_HUMAN", "BLOCKED", "WAITING_DEPENDENCY"):
            self.transition(task_id, "RUNNING", cause or "阻礙解除，恢復執行",
                            actor="controller")
        self.dispatch(nxt["step_id"], worker,
                      cause or "前一步已驗證，自動派下一步", auto=True)
        return nxt

    def drain(self, task_id: str, worker: str, max_steps: int = 50) -> list[dict]:
        """一直派到派不動為止。

        F04 §2 的鏈是 DISPATCH → … → VERIFY → NEXT_STEP_DISPATCH。
        這個方法把那條鏈跑完,不需要有人在旁邊每一輪說一次「繼續」。
        max_steps 是防呆,不是設計上限。
        """
        out = []
        for _ in range(max_steps):
            step = self.auto_dispatch(task_id, worker)
            if step is None:
                break
            out.append(step)
            ok, _res = self.verify_step(step["step_id"])
            if not ok:
                break
        return out

    # -- Watchdog（F05-WDG-001）------------------------------------------

    def active_steps(self) -> list[dict]:
        """全部進行中的步驟，不分任務，最久沒動靜的排前面。

        B-09 的機制缺口就在這裡：`check_liveness()` 要有人記得對某一個
        特定的 step 呼叫它，而「記得」正是會失敗的東西。2026-09-08
        那個 worker 死了十七小時沒人知道，不是因為 watchdog 不會動，
        是因為沒有人想到要對它問一次。

        所以巡檢的入口不能是「看某一個」，必須是「看全部」。
        """
        now = time.time()
        rows = self.con.execute(
            "SELECT s.step_id,s.task_id,s.objective,s.state,s.assigned_worker,"
            "s.started_at,s.last_progress_at,s.retry_count,t.objective,"
            "s.worker_can_report"
            " FROM steps s JOIN tasks t ON t.task_id=s.task_id"
            f" WHERE s.state IN ({','.join('?' * len(ACTIVE))})"
            # 任務結束了,它底下的步驟就不該還被當成「有人在做」。
            # 2026-09-09 實測撞到:兩個任務轉成 SUPERSEDED 之後,
            # 巡檢仍然每次都列出它們的步驟,因為步驟自己還停在 RUNNING。
            # 一個永遠清不掉的待辦會讓整張巡檢表失去意義 —— 看久了
            # 就會開始忽略它,而那正是它存在的反面。
            f" AND t.current_state NOT IN ({','.join('?' * len(TERMINAL))})",
            (*ACTIVE, *TERMINAL)).fetchall()
        out = []
        for r in rows:
            since = r[6] or r[5] or now
            out.append({
                "step_id": r[0], "task_id": r[1], "local_id": r[0].split("/")[-1],
                "objective": r[2], "state": r[3], "worker": r[4] or "",
                "idle_sec": max(now - since, 0.0), "retry_count": r[7],
                "task_objective": r[8],
                "can_report": r[9] or "unknown",
            })
        out.sort(key=lambda d: d["idle_sec"], reverse=True)
        return out

    def check_liveness(self, step_id: str, *, expected_to_progress: bool = True,
                       config: dict | None = None):
        """這一步還活著嗎。只回答活不活著，不回答做得對不對。

        F05 §6：A worker can be alive and wrong。所以這個方法絕不碰
        verifier，也絕不改變步驟狀態。它只產生一個判斷。
        """
        w = _watchdog_mod()
        row = self.con.execute(
            "SELECT task_id,state,started_at,last_progress_at,expected_outputs"
            " FROM steps WHERE step_id=?", (step_id,)).fetchone()
        if row is None:
            raise TransitionError(f"沒有這個步驟：{step_id}")
        task_id, state, started, last_prog, expected = row
        if state not in ACTIVE:
            return w.assess(age_sec=0.0, progress_changed=True, events_since=1,
                            expected_to_progress=False, config=config)

        # B-10：先去收件匣撿。一個只有 Write 權限的 worker 的話都在那裡，
        # 不撿就等於它從來沒說過。撿要在算 age 之前，因為撿到
        # WORKER_PROGRESS 會更新 last_progress_at，那正是它想告訴我們的。
        self.collect_inbox(step_id)
        last_prog = self.con.execute(
            "SELECT last_progress_at FROM steps WHERE step_id=?",
            (step_id,)).fetchone()[0]

        since = last_prog or started or time.time()
        age = time.time() - since

        probe = w.ProgressProbe.take(_u(expected), self.cwd)
        prev = self._last_probe(step_id)
        changed = probe.changed_from(prev)
        # 只在有新資訊時才落一筆。巡檢是可以每分鐘跑的東西，每次都寫
        # 一筆「取樣了但什麼都沒變」會讓事件表以巡檢頻率膨脹，而那些
        # 筆數一個字的資訊都沒有。沒寫也不影響判斷：changed_from 比的
        # 是內容，基準留在上一筆有變化的地方仍然對得出來。
        if prev is None or changed:
            self._save_probe(step_id, probe)

        events = self.con.execute(
            "SELECT COUNT(*) FROM events WHERE step_id=? AND at>? AND kind IN"
            " ('WORKER_PROGRESS','EVIDENCE_AVAILABLE','ARTIFACT_CHANGED')",
            (step_id, since - 0.001)).fetchone()[0]

        a = w.assess(age_sec=age, progress_changed=changed, events_since=events,
                     expected_to_progress=expected_to_progress, config=config)
        if a.suspect:
            self._event("STALL_SUSPECT", a.why, actor="watchdog",
                        task_id=task_id, step_id=step_id,
                        payload={"risk": a.risk, "factors": a.factors})
        return a

    def _last_probe(self, step_id: str):
        """上一次取樣。存在 events 裡，不另開表：取樣本身就是一種觀測事件。"""
        w = _watchdog_mod()
        row = self.con.execute(
            "SELECT payload,at FROM events WHERE step_id=? AND kind='PROGRESS_PROBE'"
            " ORDER BY event_id DESC LIMIT 1", (step_id,)).fetchone()
        if not row or not row[0]:
            return None
        try:
            data = json.loads(row[0])
        except (ValueError, TypeError):
            return None
        return w.ProgressProbe(at=row[1], files={k: tuple(v) for k, v in data.items()})

    def _save_probe(self, step_id: str, probe) -> None:
        row = self.con.execute("SELECT task_id FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        self._event("PROGRESS_PROBE", "watchdog 取樣", actor="watchdog",
                    task_id=row[0] if row else "", step_id=step_id,
                    payload={k: list(v) for k, v in probe.files.items()})

    def recover(self, step_id: str, *, unresponsive_count: int = 0,
                current_rung: str | None = None, config: dict | None = None) -> str:
        """復原階梯的下一階。人排在最後（F05 §5）。

        叫人是最貴的一步，不是最方便的一步。
        """
        w = _watchdog_mod()
        rung = w.next_rung(current_rung, unresponsive_count=unresponsive_count,
                           can_report=self.can_report(step_id), config=config)
        row = self.con.execute("SELECT task_id FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        self._event("RECOVERY_RUNG", rung, actor="watchdog",
                    task_id=row[0] if row else "", step_id=step_id,
                    payload={"from": current_rung, "unresponsive": unresponsive_count})
        return rung

    # -- 執行連續性（F06-EXC-001）-----------------------------------------

    def stop(self, task_id: str, reason: str, detail: str = "",
             actor: str = "controller") -> str:
        """記錄一次停止。理由必須是 F06 §4 的八種之一。

        不合法的理由會丟 ContinuityViolation，而且違規本身會先被記進
        帳本再丟 —— 因為一次違規的嘗試本身就是資料，不該因為它失敗了
        就消失。

        這個方法是那 9 次的機制形式：把停止變成一個需要理由的動作。
        """
        c = _continuity_mod()
        try:
            ok = c.classify_stop(reason, detail)
        except c.ContinuityViolation as e:
            self._event("EXECUTION_CONTINUITY_VIOLATION", str(e), actor=actor,
                        task_id=task_id, payload={"attempted_reason": reason,
                                                  "detail": detail})
            raise
        if c.requires_named_target(ok) and not detail.strip():
            self._event("EXECUTION_CONTINUITY_VIOLATION",
                        f"{ok} 必須講出對象，不然跟「我先停一下」沒有差別",
                        actor=actor, task_id=task_id)
            raise c.ContinuityViolation(
                f"{ok} 必須在 detail 裡講出等什麼、被什麼擋住、或要誰決定")
        self._event("EXECUTION_STOP", f"{ok}：{detail}" if detail else ok,
                    actor=actor, task_id=task_id, payload={"reason": ok})
        return ok

    def human_continue(self, task_id: str, prompt: str = "") -> None:
        """記錄一次「使用者必須開口說繼續」。

        這個方法存在的唯一目的是讓 HumanContinueBurden 算得出來。
        每呼叫一次,就是系統失敗了一次 —— 那一次本來應該自己走。
        """
        self._event("HUMAN_CONTINUE", prompt[:200] or "使用者要求繼續",
                    actor="owner", task_id=task_id)

    def continuity(self, task_id: str) -> dict:
        """F06 §5 的兩個指標，從事件算，不是從印象算。

        【分母是我的詮釋，規格沒有定義】F06 §5 只給了公式
        `ExecutionContinuityScore = AutoContinued / max(ExpectedContinuation,1)`，
        沒有說 ExpectedContinuation 數的是什麼。下面的定義是我定的，
        換一個定義分數就會變，所以它跟 F05 的 STALL_RISK 四因子一樣，
        是待校準的東西，不是從規格推出來的事實。

        ExpectedContinuation 數兩種時刻：

          一，一個步驟驗證通過，而且任務還有下一步。這是最典型的
              「本來就該自己往下走」，也是 drain 走的路。

          二，一次進度報告。CT-F06-02 明寫 60% status report →
              workflow continues，報告不該變成流程關卡。

        刻意不算 WORKER_RESULT：worker 交回結果之後的那次繼續，
        已經被「驗證通過就派下一步」涵蓋，兩邊都算會讓同一次交接
        被數兩次，分母虛胖、分數虛低。

        AutoContinued 不算任務的第一次派工。那一次是起步不是接續，
        前面沒有東西可以接。把它算進去的話，一個只有一步的任務會
        看起來「完美自動」，而它其實從沒接續過任何東西。

        這兩條都是 2026-09-09 第一次真的拿它跑一件真實任務才發現的。
        在那之前分母是 PROGRESS_REPORT + WORKER_RESULT，而 drain
        兩種都不產生，於是三步全自動走完的任務算出 3/0 = 3.0 分。
        一個沒有人用過的指標，會安靜地算出離譜的數字。
        """
        c = _continuity_mod()
        ev = self.events_of(task_id)
        kinds = [e["kind"] for e in ev]

        dispatches = [e for e in ev if e["kind"] == "DISPATCH"]
        auto = sum(1 for e in dispatches[1:]
                   if (e.get("payload") or {}).get("auto") is True)

        n_steps = len(self.steps_of(task_id))
        verified = sum(1 for e in ev
                       if e["kind"] == "STEP_STATE" and e["to"] == "VERIFIED_COMPLETE")
        # 最後一步驗證通過之後沒有下一步可派,那不算「該接而沒接」。
        expected = min(verified, max(n_steps - 1, 0)) + kinds.count("PROGRESS_REPORT")
        burden = kinds.count("HUMAN_CONTINUE")
        violations = kinds.count("EXECUTION_CONTINUITY_VIOLATION")
        return {
            "auto_continued": auto,
            "expected_continuation": expected,
            "score": c.continuity_score(auto, expected),
            "human_continue_burden": burden,
            "burden_verdict": c.burden_verdict(burden),
            "violations": violations,
        }

    # -- 結果保全（F07-OUT-001）-------------------------------------------

    def receipt(self, step_id: str, tool: str, outcome: str, *,
                artifacts: list[str] | None = None,
                raw_refs: list[str] | None = None):
        """落一份 ResultReceipt。必須在自然語言合成之前呼叫。

        F07 §5。這份東西的價值全在時序上:晚一步落地就等於沒有,
        因為吐白正是發生在合成那一刻。
        """
        st = _starvation_mod()
        r = st.ResultReceipt(step_id=step_id, tool=tool, outcome=outcome,
                             artifacts=artifacts or [], raw_refs=raw_refs or [])
        row = self.con.execute("SELECT task_id FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        self._event("RESULT_RECEIPT", f"{tool}：{outcome}", actor="worker",
                    task_id=row[0] if row else "", step_id=step_id,
                    payload=r.to_dict(), idem_key=f"receipt:{step_id}:{r.digest}")
        return r

    def receipts_of(self, step_id: str) -> list[dict]:
        rows = self.con.execute(
            "SELECT payload FROM events WHERE step_id=? AND kind='RESULT_RECEIPT'"
            " ORDER BY event_id", (step_id,)).fetchall()
        out = []
        for (p,) in rows:
            try:
                out.append(json.loads(p))
            except (ValueError, TypeError):
                continue
        return out

    def mark_synthesized(self, step_id: str, digest: str) -> None:
        """標記某份收據已經被轉成給人看的文字。"""
        row = self.con.execute("SELECT task_id FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        self._event("SYNTHESIZED", digest, actor="main",
                    task_id=row[0] if row else "", step_id=step_id)

    def diagnose_output(self, step_id: str, *, blank_run: int = 0,
                        foreground_running: bool = False,
                        progress_healthy: bool = False):
        """診斷這一步的輸出狀況。只吃看得到的事實。

        不接受任何「模型說它怎麼了」的輸入(§3)。回傳的 Diagnosis 帶
        basis 欄位,標明是 OBSERVED 還是 INFERRED。
        """
        st = _starvation_mod()
        receipts = self.receipts_of(step_id)
        synthesized = self.con.execute(
            "SELECT COUNT(*) FROM events WHERE step_id=? AND kind='SYNTHESIZED'",
            (step_id,)).fetchone()[0]
        tool_calls = self.con.execute(
            "SELECT COUNT(*) FROM events WHERE step_id=? AND kind IN"
            " ('RESULT_RECEIPT','WORKER_PROGRESS','ARTIFACT_CHANGED')",
            (step_id,)).fetchone()[0]
        d = st.diagnose(has_receipts=bool(receipts),
                        has_final_output=bool(synthesized),
                        tool_calls=tool_calls,
                        progress_healthy=progress_healthy,
                        blank_run=blank_run,
                        foreground_running=foreground_running)
        row = self.con.execute("SELECT task_id FROM steps WHERE step_id=?",
                               (step_id,)).fetchone()
        self._event("OUTPUT_DIAGNOSIS", f"{d.failure_class}（{d.basis}）：{d.detail}",
                    actor="watchdog", task_id=row[0] if row else "", step_id=step_id,
                    payload={"class": d.failure_class, "basis": d.basis,
                             "plan": st.recovery_plan(d)})
        return d

    # -- 義務帳本（F02 §6）-----------------------------------------------

    def obligations(self) -> dict:
        """五種未完成。F02 §6 要求 Forseti 必須持續知道這些。

        CT-F02-02：十四個未完成項目要被自動暴露,不需要使用者盤問。
        這正是使用者 2026-09-08 那個八小時事故的反面。
        """
        q = self.con.execute
        unfinished_tasks = q(
            "SELECT task_id,objective,current_state,next_required_action FROM tasks"
            " WHERE current_state NOT IN (?,?,?,?)", TERMINAL).fetchall()
        unfinished_steps = q(
            "SELECT s.step_id,s.objective,s.state,t.task_id FROM steps s"
            " JOIN tasks t ON t.task_id=s.task_id"
            " WHERE s.state NOT IN (?,?,?,?) AND t.current_state NOT IN (?,?,?,?)",
            (*TERMINAL, *TERMINAL)).fetchall()
        blocked = q(
            "SELECT task_id,objective FROM tasks WHERE current_state IN"
            " ('BLOCKED','NEEDS_HUMAN','WAITING_DEPENDENCY')").fetchall()
        # 宣稱完成但沒有證據:進了 VERIFYING 卻沒有 evidence_refs
        unverified = q(
            "SELECT step_id,objective FROM steps"
            " WHERE state='VERIFYING' AND (evidence_refs IS NULL OR evidence_refs IN ('','[]'))"
        ).fetchall()
        orphan = q(
            "SELECT task_id,objective FROM tasks"
            " WHERE (current_owner IS NULL OR current_owner='')"
            " AND current_state NOT IN (?,?,?,?)", TERMINAL).fetchall()
        # next 動態算,不讀 tasks.next_required_action。
        # 靜態欄位要記得更新才會對,而「記得更新」正是這整個帳本
        # 想要消滅的那種依賴。
        def _next(tid: str) -> str:
            n = self.next_step(tid)
            return f"{n['local_id']}　{n['objective']}" if n else "（沒有可動的步驟）"

        return {
            "unfinished_tasks": [dict(zip(("task_id", "objective", "state", "next"),
                                          (r[0], r[1], r[2], _next(r[0]))))
                                 for r in unfinished_tasks],
            "unfinished_steps": [dict(zip(("step_id", "objective", "state", "task_id"), r))
                                 for r in unfinished_steps],
            "blocked": [dict(zip(("task_id", "objective"), r)) for r in blocked],
            "unverified_claims": [dict(zip(("step_id", "objective"), r)) for r in unverified],
            "orphans": [dict(zip(("task_id", "objective"), r)) for r in orphan],
        }

    def total_unfinished(self) -> int:
        o = self.obligations()
        return len(o["unfinished_tasks"]) + len(o["unfinished_steps"])

    def events_of(self, task_id: str) -> list[dict]:
        """一件任務的全部事件，按發生順序。

        payload 一起帶出來，解析成 dict。先前這個查詢漏掉 payload，
        於是 continuity() 想知道一次派工是不是自動的，只能去掃 cause
        裡有沒有「自動」兩個字。指標讀不到自己要的欄位時，就會退化成
        猜字串，而猜字串的指標會安靜地算錯。
        """
        rows = self.con.execute(
            "SELECT at,kind,step_id,from_state,to_state,cause,actor,payload FROM events"
            " WHERE task_id=? ORDER BY event_id", (task_id,)).fetchall()
        out = []
        for r in rows:
            d = dict(zip(("at", "kind", "step_id", "from", "to", "cause", "actor"), r[:7]))
            try:
                d["payload"] = json.loads(r[7]) if r[7] else {}
            except (ValueError, TypeError):
                # 壞掉的 payload 不該讓整份事件史讀不出來。
                d["payload"] = {}
            out.append(d)
        return out

    def close(self) -> None:
        self.con.close()
