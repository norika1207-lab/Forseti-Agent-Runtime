#!/usr/bin/env python3
"""Event Ledger：provider 行為事件的正本。階段 1 的核心交付。

規格來源：v5.0 §6（Event Ledger and Lineage Ledger）與 §20（Storage
Architecture），主 session 2026-09-10 逐行讀過；工程書 Phase 1。
對照筆記在 `docs/reading/v5-06-20.md`。

**這不是 Task Ledger。** ADR-008 定案兩本帳本分開：

    Task Ledger（ledger.py）  誰接了什麼、還欠什麼、驗過沒
    Event Ledger（本檔）      AI 與 runtime 實際發生了什麼

兩邊都有 `events`，但在不同的儲存體。講的時候一律說「Task Ledger 的
events」或「Event Ledger 的 events」，不准只講「events 表」。
八條同名不同義記在 `docs/glossary.md`。

────────────────────────────────────────────────────

## 為什麼 JSONL 是正本，SQLite 只是索引

v5.0 §20.3 要的是「SQLite WAL 為主，append-only JSONL 為可攜匯出」。
本專案把主從反過來，理由有兩層。

表層理由是環境：這個 repo 在 exFAT 外接碟上，而 exFAT 沒有 sqlite 要的
POSIX advisory lock（`ledger.py` 的 `default_db()` 記了實測經過）。
JSONL 是普通檔案，寫得進去。

真正的理由是出口條件。`docs/build-plan.md:327` 要求：

    殺掉程序再開，事件不掉。同一份帳本重播兩次，結果逐位元組相同。

append-only 的文字檔天生滿足這兩條 —— 每筆寫完就 flush，行的順序就是
發生的順序。換成「SQLite 為主」的話，這兩條都要另外設計交易邊界去保證。

**索引壞掉刪掉重建就好，正本一個位元組都不動。** 這跟 `recall.py`
的做法是同一個哲學，它的檔頭第 16 行寫得更直接：
「只讀 jsonl，一個位元組都不動。索引是另一個檔案，錯了刪掉重建。」

代價是與 §20.3 字面不符，已記在下面的 SPEC_DEVIATIONS。

零依賴，只用標準庫（ADR-009）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field, asdict
from pathlib import Path

# ---------------------------------------------------------------------------
# v5.0 §6.2 的 canonical event types
# ---------------------------------------------------------------------------

# 八大類是封閉的白名單。類別可以隨便取名的話就等於沒有分類 ——
# 下游沒辦法對著一組不固定的名字寫邏輯，那是 ledger.py 的 WORKER_EVENTS
# 已經踩過的原則。
CATEGORIES = (
    "Cognitive", "Tool", "Artifact", "Runtime",
    "Workflow", "Governance", "Recovery", "Health",
)

# 每一類底下的 type。這份清單逐字取自 v5.0 §6.2（190-197 行），
# 沒有自己加任何一個。
#
# 規格把它叫 "Examples"，所以它不是窮舉。但先當成封閉白名單用，
# 理由跟 ledger.py 的 ALIASES 一樣：要加就要有實測的出處，
# 而不是先想像可能需要什麼。接 hook 的時候如果發現缺，
# 那時候加，並在旁邊註明是哪一個真實事件要求的。
TYPES: dict[str, tuple[str, ...]] = {
    "Cognitive": ("USER_INSTRUCTION", "MODEL_OUTPUT", "ASSUMPTION",
                  "HYPOTHESIS", "DECISION_PROPOSAL", "CORRECTION"),
    "Tool": ("TOOL_CALL", "TOOL_RESULT", "NORMALIZATION", "RETRY", "TOOL_ERROR"),
    "Artifact": ("FILE_READ", "FILE_WRITE", "FILE_DIFF", "DB_WRITE",
                 "API_OBJECT_CREATED"),
    "Runtime": ("PROCESS_START", "PROCESS_EXIT", "SERVICE_RESTART",
                "NODE_HEARTBEAT", "SESSION_RESUME"),
    "Workflow": ("STEP_START", "STEP_COMMIT", "STEP_ROLLBACK",
                 "APPROVAL_REQUESTED"),
    "Governance": ("POLICY_ALLOW", "POLICY_BLOCK", "AUTHORITY_COLLISION",
                   "WRITE_BARRIER"),
    "Recovery": ("CHECKPOINT", "INCIDENT_OPEN", "RECONSTRUCT",
                 "CLEAN_FORK", "TAKEOVER"),
    "Health": ("CONTEXT_SAMPLE", "QUEUE_DEPTH", "FRESHNESS",
               "THRASHING", "TOOL_LOOP"),
}

TYPE_TO_CATEGORY = {t: c for c, ts in TYPES.items() for t in ts}

# v5.0 §6.3 的十種 lineage 邊。這裡先定義不實作 ——
# 邊要有兩端才畫得出來，而現在只有事件還沒有 claim 與 decision。
# 定義先放著是為了讓做的人不用回頭翻規格，也避免又長出第二套
# （`src/topology.js:40` 已經有一套九種的，只有三個名字重疊，
# 那是 glossary 第四條）。
LINEAGE_EDGES = (
    "DERIVED_FROM", "TRIGGERED_BY", "VERIFIES", "REFUTES", "SUPERSEDES",
    "CONSUMES", "PRODUCES", "PROMOTES", "PROPAGATES_TO", "RECONSTRUCTED_FROM",
)

# 已知與規格的偏離。寫在程式碼裡而不是只寫在文件裡，因為改這個檔的人
# 不一定會去讀文件。
SPEC_DEVIATIONS = (
    "v5.0 §20.3 要 SQLite 為主、JSONL 為輔；本專案反過來（見檔頭）。",
    "v5.0 §20.2 列 29 張表；本階段只做 raw_events 與 events 兩張。",
    "v5.0 §6.3 的 lineage_edges 只定義未實作，等 claim 與 decision 存在。",
)


# 2026-09-10 之前寫進正本的測試假料,用 session_id 認。
#
# **它們不會被刪掉。** 正本是 append-only,而那個性質存在的意義就是
# 沒有人能刪它 —— 包括發現自己寫錯的人。所以改成讓它們可被識別。
#
# 要講清楚的是它們不是「髒資料」:hook 真的執行了、事件真的發生了,
# 假的是 input(test/hooks.e2e.test.mjs 餵的 file_path 指向 src/drift.js,
# 而那個檔案從頭到尾沒被改過)。所以它們是「測試產生的真實事件」,
# 分析的時候該排除,取證的時候不該假裝沒發生過。
#
# 來源已經修掉:hook 現在尊重 FORSETI_EVENT_LEDGER_DIR,測試導向沙箱。
KNOWN_TEST_SESSIONS = ("insider", "perf", "probe-1", "b", "s")


def is_test_event(rec: dict) -> bool:
    """這一筆是不是測試產生的。"""
    n = rec.get("norm") or {}
    return (n.get("session_id") or n.get("agent_id") or "") in KNOWN_TEST_SESSIONS


class LedgerError(Exception):
    """事件不合規格。拒收而不是修正 —— 一個被默默改過的事件比被拒絕的危險。"""


# ---------------------------------------------------------------------------
# v5.0 §6.1 的雙表示
# ---------------------------------------------------------------------------

def canonical_json(obj) -> str:
    """決定性的 JSON。

    同樣的內容一定產生同樣的位元組，這是出口條件「重播兩次逐位元組相同」
    的地基。sort_keys 讓欄位順序固定，separators 去掉多餘空白，
    ensure_ascii=False 讓中文保持原樣（不然 hash 會跟著跳脫序列走）。
    """
    return json.dumps(obj, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def payload_hash(payload) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RawEvent:
    """provider 原生事件，一個位元組都不改。

    v5.0 §6.1 第 175 行：Every provider-native event is stored twice:
    raw and normalized. Normalization is never allowed to destroy the
    original evidence.

    frozen=True 是那句話的機制形式：正規化那一端拿到的是不可變物件，
    改不動它。
    """

    provider: str
    provider_event_type: str
    timestamp: float
    payload: dict
    id: str = ""

    def __post_init__(self):
        if not self.provider or not self.provider_event_type:
            raise LedgerError("RawEvent 必須有 provider 與 provider_event_type。"
                              "那兩個欄位正是它跟 Task Ledger 事件的分野")
        if not self.id:
            # id 由內容決定，不用 uuid。理由是重播要決定性：
            # 同一份輸入重跑要產生同一個 id，uuid 每次都不同。
            h = payload_hash(self.payload)
            object.__setattr__(self, "id", f"{self.timestamp:.6f}-{h[:12]}")

    @property
    def hash(self) -> str:
        return payload_hash(self.payload)


@dataclass
class NormalizedEvent:
    """正規化之後的事件。欄位照 v5.0 §6.1（181-184 行）。

    `raw_event_id` 是回頭路。任何時候都能從這裡回到原始證據，
    那是「正規化不得摧毀原始證據」的可查核形式 —— 不是承諾不摧毀，
    是留一條回去的路。
    """

    raw_event_id: str
    type: str
    session_id: str = ""
    project_id: str = ""
    agent_id: str = ""
    runtime_node_id: str = ""
    action: str = ""
    subject: str = ""
    object: str = ""
    result: str = ""
    provenance: str = "OBSERVED"
    risk: str = ""
    metadata: dict = field(default_factory=dict)
    id: str = ""

    def __post_init__(self):
        if self.type not in TYPE_TO_CATEGORY:
            raise LedgerError(
                f"不是 v5.0 §6.2 的 canonical type：{self.type}。"
                f"合法的有 {len(TYPE_TO_CATEGORY)} 種，分屬 {len(CATEGORIES)} 類。"
                f"要加新的請附實際遇到的事件當出處")
        if not self.id:
            object.__setattr__(self, "id", f"n-{self.raw_event_id}")

    @property
    def category(self) -> str:
        return TYPE_TO_CATEGORY[self.type]


# ---------------------------------------------------------------------------
# 正本：append-only JSONL
# ---------------------------------------------------------------------------

def default_jsonl(root: Path | None = None) -> Path:
    """正本放 repo 裡的 `.forseti/event_ledger.jsonl`。

    位置照 v5.0 §20.1（541 行）。它可以放這裡而 Task Ledger 不行，
    差別是普通檔案與 sqlite —— exFAT 沒有 advisory lock，但寫文字檔沒問題。
    這個區分是 2026-09-09 那個 worker 指出來的，我原本判斷得太粗，
    以為整個儲存體系都得搬去 home。
    """
    base = (root or Path(__file__).resolve().parents[2]).resolve()
    return base / ".forseti" / "event_ledger.jsonl"


def default_index(root: Path | None = None) -> Path:
    """索引放 home。壞了刪掉重建，正本不動。"""
    base = (root or Path(__file__).resolve().parents[2]).resolve()
    key = hashlib.sha256(str(base).encode("utf-8")).hexdigest()[:12]
    return Path.home() / ".forseti" / "events" / f"{base.name}-{key}.db"


INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_events (
  id TEXT PRIMARY KEY, provider TEXT, provider_event_type TEXT,
  timestamp REAL, payload_hash TEXT, payload TEXT, line_no INTEGER
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, raw_event_id TEXT,
  project_id TEXT, agent_id TEXT, session_id TEXT, runtime_node_id TEXT,
  type TEXT, category TEXT, action TEXT, subject TEXT, object TEXT,
  result TEXT, provenance TEXT, risk TEXT, metadata TEXT, line_no INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ev_session ON events(session_id, line_no);
CREATE INDEX IF NOT EXISTS idx_ev_type ON events(type);
CREATE INDEX IF NOT EXISTS idx_raw_ts ON raw_events(timestamp);
"""

# 改了 INDEX_SCHEMA 就把這個加一。舊索引會被丟掉重建 —— 那是安全的,
# 因為索引不是真相,正本才是。這一行跟 recall.py:264 是同一個做法。
INDEX_VERSION = 1


class EventLedger:
    """正本是檔案，這個類別是它的門。

    刻意不提供任何「改一筆」或「刪一筆」的方法。append-only 不是靠
    紀律維持的，是靠沒有那個入口。
    """

    def __init__(self, jsonl: Path | None = None, index: Path | None = None,
                 root: Path | None = None):
        self.jsonl = jsonl or default_jsonl(root)
        self.index_path = index or default_index(root)
        self.jsonl.parent.mkdir(parents=True, exist_ok=True)
        self._con: sqlite3.Connection | None = None

    # -- 寫 ---------------------------------------------------------------

    def append(self, raw: RawEvent, norm: NormalizedEvent | None = None) -> str:
        """寫一筆。回傳 raw event id。

        raw 與 normalized 寫在同一行，因為它們是同一個事件的兩個表示，
        分兩行會讓「其中一半寫成功」變成可能的狀態。v5.0 §6.1 說
        stored twice，沒說要分兩個地方。

        flush 之後不 fsync。出口條件是「殺掉程序再開，事件不掉」——
        SIGKILL 之後 OS buffer 仍在，flush 就夠；fsync 是為了斷電，
        代價是每筆多幾毫秒，而熱路徑預算只有 p95 < 50ms。
        真的需要抗斷電時把 fsync 打開，那是一行的事。
        """
        if norm is not None and norm.raw_event_id != raw.id:
            raise LedgerError(
                f"normalized 的 raw_event_id（{norm.raw_event_id}）"
                f"對不上 raw 的 id（{raw.id}）。回頭路斷了就等於摧毀原始證據")
        rec = {"raw": asdict(raw), "norm": asdict(norm) if norm else None}
        line = canonical_json(rec)
        with self.jsonl.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
        return raw.id

    # -- 讀 ---------------------------------------------------------------

    def read_all(self) -> list[dict]:
        """整份讀出來，順序就是寫入順序。

        壞掉的行不跳過也不猜，直接報位置。一個安靜被略過的事件，
        效果跟從來沒發生過一樣，而那正是這本帳要防的東西。
        """
        if not self.jsonl.exists():
            return []
        out = []
        with self.jsonl.open(encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError as e:
                    raise LedgerError(f"第 {i} 行不是合法 JSON：{e}") from e
        return out

    def replay(self) -> str:
        """把整份帳本重播成一份決定性的輸出。

        出口條件（`docs/build-plan.md:327`）：同一份帳本重播兩次，
        結果逐位元組相同。

        這裡不做任何取捨或格式化 —— 每一行都用 canonical_json 重新
        序列化，所以連原本寫入時的欄位順序差異都會被抹平。
        兩次重播不同的唯一可能是正本被改過。
        """
        return "\n".join(canonical_json(r) for r in self.read_all())

    def digest(self) -> str:
        """整份帳本的指紋。重播結果的 sha256。"""
        return hashlib.sha256(self.replay().encode("utf-8")).hexdigest()

    # -- 索引 -------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._con is None:
            self.index_path.parent.mkdir(parents=True, exist_ok=True)
            con = sqlite3.connect(self.index_path)
            try:
                con.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError:
                pass
            have = con.execute("PRAGMA user_version").fetchone()[0]
            if have and have != INDEX_VERSION:
                # 版本不合就整個丟掉重建。索引不是真相,正本才是,
                # 所以這裡可以 DROP —— 跟 ledger.py 的「只能 ALTER 不能 DROP」
                # 剛好相反,差別在於誰是唯一真相。
                con.execute("DROP TABLE IF EXISTS raw_events")
                con.execute("DROP TABLE IF EXISTS events")
            con.executescript(INDEX_SCHEMA)
            con.execute(f"PRAGMA user_version = {INDEX_VERSION}")
            con.commit()
            self._con = con
        return self._con

    def reindex(self) -> dict:
        """從正本重建索引。整個砍掉重來，不做增量。

        增量索引要處理「上次讀到哪」，而那個狀態自己會壞。
        全量重建三十秒的事，換掉一整類 bug。
        """
        con = self._connect()
        con.execute("DELETE FROM raw_events")
        con.execute("DELETE FROM events")
        n_raw = n_norm = 0
        for line_no, rec in enumerate(self.read_all(), 1):
            r = rec.get("raw") or {}
            con.execute(
                "INSERT OR REPLACE INTO raw_events"
                " (id,provider,provider_event_type,timestamp,payload_hash,payload,line_no)"
                " VALUES (?,?,?,?,?,?,?)",
                (r.get("id"), r.get("provider"), r.get("provider_event_type"),
                 r.get("timestamp"), payload_hash(r.get("payload") or {}),
                 canonical_json(r.get("payload") or {}), line_no))
            n_raw += 1
            n = rec.get("norm")
            if not n:
                continue
            con.execute(
                "INSERT OR REPLACE INTO events"
                " (id,raw_event_id,project_id,agent_id,session_id,runtime_node_id,"
                "  type,category,action,subject,object,result,provenance,risk,"
                "  metadata,line_no) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (n.get("id"), n.get("raw_event_id"), n.get("project_id"),
                 n.get("agent_id"), n.get("session_id"), n.get("runtime_node_id"),
                 n.get("type"), TYPE_TO_CATEGORY.get(n.get("type"), ""),
                 n.get("action"), n.get("subject"), n.get("object"),
                 n.get("result"), n.get("provenance"), n.get("risk"),
                 canonical_json(n.get("metadata") or {}), line_no))
            n_norm += 1
        con.commit()
        return {"raw": n_raw, "normalized": n_norm, "index": str(self.index_path)}

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None
