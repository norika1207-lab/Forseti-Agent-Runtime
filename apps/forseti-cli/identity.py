#!/usr/bin/env python3
"""Persistent Agent Identity。v5.0 §11.1。

規格那一段只有六行，短到很容易被當成一句口號讀過去:

    Persistent Agent Identity
      ≠ Model
      ≠ Session
      ≠ Process
      ≠ Execution Slot
      ≠ Role

ROADMAP P2 第 8 項的完成定義是「agent 的身份跟 session、model、process
分開，換 session 不換身份」。

────────────────────────────────────────────────────

## 這一支要回答的窄問題

    「這個 repo 現在分得開身份與那五樣東西嗎？分不開的是哪幾樣，
     憑什麼這樣講？」

不是「幫我建一個身份系統」。建一個沒有人用的身份系統，跟現在沒有身份
系統，在畫面上長得一模一樣(都會出現一排看起來很整齊的欄位)，
而後者至少不會讓人以為問題解決了。

## 每一軸只有三種答案，而且 NO_SOURCE 不准投影成好消息

- `SEPARABLE`    真實資料裡量得到「同一個東西跨過這一軸還是同一個」
- `CONFLATED`    真實資料裡量得到「這個 repo 現在把兩者當成同一件事」
- `NO_SOURCE`    這一軸在這個 repo 沒有資料來源，所以不給結論

第三種最重要。`Process` 這一軸不是「沒問題」，是**這條線上的 jsonl
沒有 pid 欄位**，所以任何關於它的結論都是編的。這件事寫在回傳值裡
(`live` 是 None，`why` 講得出為什麼)，不藏在註解。

## 為什麼不從 alias 的長相推斷身份

`norikaoda-03` 與 `norikaoda-84` 前綴一樣，看起來像同一個人的兩條線。
**不做這個推斷**，理由跟 `sot.py` 不掃原始碼猜來源、`pollution.py`
不自動掃描同一條(BLOCKERS B-05): 靠文字相似度判斷「這兩個是不是同一個
身份」，抓到的是符合命名慣例的字串，而真的同一個身份但改過命名的那些，
會長得跟「兩個不同身份」一模一樣。

所以 `.forseti/identity.jsonl` 是**人工登記**的。空的時候它就是空的，
`assess()` 會照實說「登記 0 條」，不會拿命名相似度補一個數字上去。

## 真實資料實跑(2026-09-16 21:5x，`survey()` 掃最近 80 條)

- 10 條 session 在同一條線裡用過不只一個 model。所以 identity ≠ Model
  在這條線上不是理論，是量得到的事實。
  **這個數字第一版寫成 19，是錯的。** 19 那一次把 `<synthetic>` 算成
  一個模型，於是「這條線用過 opus-5 與 synthetic」被算成換過模型。
  排除之後是 10。跟 `blast.py` 那次 resolutionRate 從 0.971 掉到 0.541
  是同一種病:把一個不該是節點的東西放進分子，數字就開始說謊。
  `test_synthetic不算換過模型` 兩個方向都釘住。
- 1 個 jsonl 檔裡有 2 個 sessionId。所以「一個檔 = 一條 session」
  這個直覺也是錯的。
- Task Ledger 裡被當成身份用的字串(`assigned_worker` / `actor` /
  `accepted_by`)全部是 session alias。alias 換 session 就換，
  所以這個 repo 現在的「身份」其實是 Session 這一軸，不是 §11.1 的
  Persistent Agent Identity。這是 `CONFLATED` 的依據。

## `<synthetic>` 不是模型

jsonl 裡會出現 `model: "<synthetic>"`，那是 runtime 自己合成的訊息，
不是一個模型。算進「這條線用過幾個模型」會把 19 灌成更大的數字。
`SYNTHETIC_MODELS` 把它排除，而且排除這件事印在回傳值裡。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 規格原文的位置。`verify_spec()` 會回去比對。
SPEC = ("docs/sources/"
        "Forseti_Agent_Runtime_System_Architecture_Engineering_Spec_v5.0_"
        "2026-09-04.md")

#: §11.1 那一段的錨點行。324 是 `Persistent Agent Identity`。
SPEC_ANCHOR_LINE = 324
SPEC_ANCHOR_TEXT = "Persistent Agent Identity"

#: 五個軸，逐字。`axis` 是規格那一行 `≠` 後面的字，一個字都沒有改。
AXES: list[dict] = [
    {
        "key": "model",
        "axis": "Model",
        "axis_zh": "模型",
        "spec_line": 325,
        "question": "換模型還是不是同一個 agent",
    },
    {
        "key": "session",
        "axis": "Session",
        "axis_zh": "對話線",
        "spec_line": 326,
        "question": "換 session 還是不是同一個 agent",
    },
    {
        "key": "process",
        "axis": "Process",
        "axis_zh": "程序",
        "spec_line": 327,
        "question": "程序死掉重開還是不是同一個 agent",
    },
    {
        "key": "execution_slot",
        "axis": "Execution Slot",
        "axis_zh": "執行槽",
        "spec_line": 328,
        "question": "換一個執行槽還是不是同一個 agent",
    },
    {
        "key": "role",
        "axis": "Role",
        "axis_zh": "角色",
        "spec_line": 329,
        "question": "換角色還是不是同一個 agent",
    },
]

STATES = ("SEPARABLE", "CONFLATED", "NO_SOURCE")

#: 不是模型的 model 值。理由見檔頭。
SYNTHETIC_MODELS = ("<synthetic>",)

#: session 紀錄在哪。跟 `context_meter.PROJECTS_DIR` 同一個來源。
PROJECTS_DIR = Path.home() / ".claude" / "projects"

#: 人工登記的持久身份。沒有這個檔就是 0 條，不是錯誤。
REGISTRY_NAME = ".forseti/identity.jsonl"


# ---------------------------------------------------------------------------
# 一，觀察真實 session
# ---------------------------------------------------------------------------

def observe_session(path: Path) -> dict:
    """從一份 jsonl 抽出身份相關的事實。只抽檔案裡真的有的欄位。

    壞行跳過並計數,不讓一行壞資料炸掉整份(跟 `context_meter.read_session`
    同一條)。回傳裡沒有任何推斷,只有出現過什麼。
    """
    out = {
        "path": str(path),
        "name": path.name,
        "session_ids": [],
        "models": [],
        "synthetic_seen": 0,
        "cwds": [],
        "branches": [],
        "versions": [],
        "entrypoints": [],
        "lines": 0,
        "bad_lines": 0,
        "has_pid_field": False,
        "has_role_field": False,
        "first_ts": None,
        "last_ts": None,
    }
    sids: set[str] = set()
    models: set[str] = set()
    cwds: set[str] = set()
    branches: set[str] = set()
    versions: set[str] = set()
    entries: set[str] = set()

    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return out

    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except (ValueError, TypeError):
                out["bad_lines"] += 1
                continue
            if not isinstance(d, dict):
                out["bad_lines"] += 1
                continue
            out["lines"] += 1

            if d.get("sessionId"):
                sids.add(str(d["sessionId"]))
            if d.get("cwd"):
                cwds.add(str(d["cwd"]))
            if d.get("gitBranch"):
                branches.add(str(d["gitBranch"]))
            if d.get("version"):
                versions.add(str(d["version"]))
            if d.get("entrypoint"):
                entries.add(str(d["entrypoint"]))
            # 這兩個是「有沒有這個欄位」的觀察,不是有沒有值。
            # NO_SOURCE 的依據要是「掃過而且沒有」,不是「我記得沒有」。
            if "pid" in d:
                out["has_pid_field"] = True
            if "role" in d:
                out["has_role_field"] = True

            ts = d.get("timestamp")
            if isinstance(ts, str) and ts:
                if out["first_ts"] is None or ts < out["first_ts"]:
                    out["first_ts"] = ts
                if out["last_ts"] is None or ts > out["last_ts"]:
                    out["last_ts"] = ts

            msg = d.get("message")
            if isinstance(msg, dict):
                m = msg.get("model")
                if isinstance(m, str) and m:
                    if m in SYNTHETIC_MODELS:
                        out["synthetic_seen"] += 1
                    else:
                        models.add(m)

    out["session_ids"] = sorted(sids)
    out["models"] = sorted(models)
    out["cwds"] = sorted(cwds)
    out["branches"] = sorted(branches)
    out["versions"] = sorted(versions)
    out["entrypoints"] = sorted(entries)
    return out


# ── 逐檔磁碟快取 ──────────────────────────────────────────────
#
# **記憶體快取在這裡沒有用**，理由跟 `blast.py` 同一條：畫面每 2 秒
# 呼叫一次 `strands`，每一次都是 Rust `Command::new(python3)` 起的
# 全新程序，module-level 的 dict 每次都是空的。
#
# **但這裡不能用 blast 那種「整批一個指紋」。** session 檔是活的，
# 當前這一條每講一句話就長大一次，所以整批指紋幾乎每次都不一樣，
# 快取會永遠不命中。改成逐檔：key 是路徑加 mtime_ns 加 size，
# 動過的那一條自己重讀，其餘 79 條直接用上一次的結果。
#
# 實測（2026-09-16 21:5x，80 條 session）：`survey()` 1.79 秒，
# 其中 137201 次 `json.loads`。
_CACHE_VERSION = 1


def _cache_file() -> Path:
    return REPO / ".forseti" / "cache" / "identity.json"


def _obs_key(p: Path) -> str | None:
    """一條 session 的快取 key。stat 不到回 None，**不編一個**。

    編出來的 key 會讓快取永遠命中同一筆，那比沒有快取糟得多
    （`blast._fingerprint` 的檔頭記著同一條）。
    """
    try:
        st = p.stat()
    except OSError:
        return None
    return f"v{_CACHE_VERSION}|{p}|{st.st_mtime_ns}|{st.st_size}"


def _cache_read() -> dict:
    """讀快取。壞掉、讀不到一律回空的重算，不猜。"""
    try:
        raw = json.loads(_cache_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _cache_write(entries: dict) -> None:
    """寫快取。**寫失敗不算錯誤**，功能本身不依賴它。

    只留這一次掃到的那些 key，所以檔案不會隨 session 累積而無限長大。
    """
    f = _cache_file()
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entries, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(f)
    except OSError:
        return


def find_sessions(root: Path | None = None) -> list[Path]:
    """最近改過的排前面。跟 `context_meter.find_sessions` 同一個排序。"""
    r = Path(root or PROJECTS_DIR)
    if not r.is_dir():
        return []

    def _m(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    return sorted(r.glob("*/*.jsonl"), key=_m, reverse=True)


def survey(limit: int = 80, root: Path | None = None) -> dict:
    """掃最近 `limit` 條 session，量兩件事。

    **這是抽樣不是全體。** 掃了幾條、總共有幾條，兩個數字都在回傳值裡,
    因為「19 條用過多個 model」在分母是 80 跟分母是 354 底下，
    讀起來完全不是同一件事。
    """
    files = find_sessions(root)
    picked = files[:max(0, int(limit))]
    multi_model = []
    multi_session = []
    models_count: dict[str, int] = {}
    pid_field = 0
    role_field = 0
    scanned = 0

    # **快取只給正本開（`root is None`）。** 測試給的是 tmp 目錄裡
    # 現場建出來的假 session，那些檔在毫秒尺度上被建立與改寫，
    # 而 mtime 的解析度不保證分得開；臨時目錄本來就只用一次，
    # 快取在那裡沒有價值只有風險。跟 `blast.collect()` 同一條。
    use_cache = root is None
    cache = _cache_read() if use_cache else {}
    fresh: dict = {}
    cache_hits = 0

    for f in picked:
        k = _obs_key(f) if use_cache else None
        hit = cache.get(k) if k else None
        if isinstance(hit, dict):
            cache_hits += 1
            o = hit
        else:
            # **快取存的就是 `observe_session()` 的輸出，沒有第二份實作。**
            # 在這裡重算一次判斷，兩份遲早會分歧，而分歧那天不會有錯誤訊息。
            hit = None
            o = observe_session(f)
        if k:
            # **命中的那一筆寫回去的是快取裡的原件，不是 `o`。**
            # 2026-09-16 21:5x 實際踩到:反向驗證在命中之後改了 `o` 的
            # 一個欄位，那個改過的值被寫回磁碟，於是程式碼還原之後
            # 錯的答案還留在快取裡（`multi_model_count` 從 10 變 0，
            # 而畫面上那句依據讀起來完全合理）。
            # 命中路徑上任何一個 bug 都會這樣被固化，所以這裡切斷那條路。
            fresh[k] = hit if hit is not None else o
        if o["lines"] == 0:
            continue
        scanned += 1
        for m in o["models"]:
            models_count[m] = models_count.get(m, 0) + 1
        if len(o["models"]) > 1:
            multi_model.append({"name": o["name"], "models": o["models"]})
        if len(o["session_ids"]) > 1:
            multi_session.append({"name": o["name"],
                                  "session_ids": o["session_ids"]})
        if o["has_pid_field"]:
            pid_field += 1
        if o["has_role_field"]:
            role_field += 1

    if use_cache and fresh != cache:
        _cache_write(fresh)

    return {
        "total_sessions_on_disk": len(files),
        "scanned": scanned,
        # 命中幾條要看得見。一個用上一次結果算出來的數字，
        # 跟一個剛剛量出來的數字，在畫面上長得一模一樣。
        # 跟 `blast.vectors()` 的 `cached` 同一條理由。
        "cache_hits": cache_hits,
        "cache_used": use_cache,
        "limit": int(limit),
        "sampled": scanned < len(files),
        "multi_model_sessions": multi_model,
        "multi_model_count": len(multi_model),
        "multi_session_files": multi_session,
        "multi_session_count": len(multi_session),
        "models_seen": sorted(models_count.items(), key=lambda x: -x[1]),
        "pid_field_sessions": pid_field,
        "role_field_sessions": role_field,
        "synthetic_excluded": list(SYNTHETIC_MODELS),
        # 這句會原樣印在畫面上，所以不放反引號。
        # 上一輪截圖抓到同一個瑕疵(註記裡的反引號印在畫面上)。
        "synthetic_note": ("synthetic 那個值是 runtime 合成的訊息不是模型，"
                           "算進去會把「用過幾個模型」灌大"),
        "root": str(root or PROJECTS_DIR),
    }


# ---------------------------------------------------------------------------
# 二，這個 repo 現在把什麼當成身份
# ---------------------------------------------------------------------------

def _ledger_db() -> Path | None:
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import ledger  # noqa: WPS433
        db = ledger.default_db()
        return db if db.exists() and db.stat().st_size > 0 else None
    except Exception:
        return None


def actors(db: Path | None = None) -> dict:
    """Task Ledger 裡被當成「誰做的」的那些字串。

    三個欄位分開數,因為它們的失效方式不同:`assigned_worker` 是派工時
    寫下的,`actor` 是事件發生時寫下的,`accepted_by` 是接任務時寫下的。
    合成一個集合會讓「哪一種欄位在用 alias」這個問題消失。
    """
    p = db or _ledger_db()
    if p is None:
        return {"available": False,
                "why": "Task Ledger 不存在或是空的，所以這一格沒有量",
                "assigned_worker": [], "actor": [], "accepted_by": [],
                "all": []}
    out = {"available": True, "why": "", "db": str(p)}
    try:
        c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except sqlite3.Error as e:
        return {"available": False, "why": f"開不起來:{e}",
                "assigned_worker": [], "actor": [], "accepted_by": [],
                "all": []}
    with c:
        for col, tbl in (("assigned_worker", "steps"),
                         ("actor", "events"),
                         ("accepted_by", "tasks")):
            try:
                rows = list(c.execute(
                    f"select {col}, count(*) from {tbl} "
                    f"where {col} is not null and {col} != '' group by 1"))
            except sqlite3.Error:
                rows = []
            out[col] = sorted(({"name": r[0], "n": r[1]} for r in rows),
                              key=lambda x: -x["n"])
    names: set[str] = set()
    for col in ("assigned_worker", "actor", "accepted_by"):
        for r in out.get(col, ()):
            names.add(r["name"])
    out["all"] = sorted(names)
    return out


# ---------------------------------------------------------------------------
# 三，人工登記的持久身份
# ---------------------------------------------------------------------------

def registry_path(repo: Path | None = None) -> Path:
    return Path(repo or REPO) / REGISTRY_NAME


def registry(repo: Path | None = None) -> list[dict]:
    """讀登記簿。沒有檔案就是 0 條，不是錯誤。"""
    p = registry_path(repo)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(d, dict) and d.get("agent_id"):
            d.setdefault("aliases", [])
            d.setdefault("note", "")
            out.append(d)
    return out


def register(agent_id: str, aliases: list[str], note: str = "",
             repo: Path | None = None) -> dict:
    """登記一個持久身份。**只有人能呼叫這一支。**

    不從資料推斷,理由見檔頭。這裡唯一做的檢查是同一個 agent_id 不重複
    登記,因為兩筆同 id 不同 aliases 會讓「這個身份有哪些 alias」
    變成看誰先被讀到。
    """
    aid = (agent_id or "").strip()
    if not aid:
        return {"ok": False, "why": "agent_id 不能是空的"}
    cur = registry(repo)
    if any(r["agent_id"] == aid for r in cur):
        return {"ok": False, "why": f"{aid} 已經登記過了"}
    rec = {"agent_id": aid,
           "aliases": [a.strip() for a in aliases if a and a.strip()],
           "note": note}
    p = registry_path(repo)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "record": rec, "path": str(p)}


def drift(repo: Path | None = None, db: Path | None = None) -> dict:
    """Agent Identity Drift(§18 那張表的第一條)。

    兩個方向都要查,因為它們是不同的病:

    - `unregistered` 帳本裡出現過、但沒有任何登記認領的 alias。
      這一類愈多,代表「身份」這件事愈是靠 alias 在撐。
    - `stale` 登記裡宣稱的 alias,帳本裡一次都沒出現過。
      那條登記不能再當證據用。

    **不做命名相似度配對**,理由見檔頭(B-05 同一條)。
    """
    reg = registry(repo)
    act = actors(db)
    known: set[str] = set()
    for r in reg:
        known.update(r.get("aliases", ()))
    seen = set(act.get("all", ()))
    return {
        "registered": len(reg),
        "aliases_registered": len(known),
        "actors_seen": len(seen),
        "ledger_available": act.get("available", False),
        "unregistered": sorted(seen - known),
        "stale": sorted(known - seen),
        "matched": sorted(known & seen),
        "why_no_fuzzy": ("不用命名相似度配對 alias。"
                         "前綴一樣不代表同一個身份，"
                         "而改過命名的同一個身份會長得像兩個"),
    }


# ---------------------------------------------------------------------------
# 四，規格對照
# ---------------------------------------------------------------------------

def verify_spec(repo: Path | None = None) -> dict:
    """五個軸是不是還跟規格那五行原文一致。

    比對的是**那一行的原文**,不是整份檔案裡有沒有出現過這個字。
    `Model` 這種字在四千行的規格裡到處都是,那種比對等於沒有比對。
    """
    base = Path(repo or REPO)
    f = base / SPEC
    if not f.exists():
        return {"ok": False, "why": f"規格檔不在:{SPEC}", "rows": [],
                "anchor_ok": False}
    lines = f.read_text(encoding="utf-8").splitlines()

    def _raw(n: int) -> str:
        return lines[n - 1] if 0 < n <= len(lines) else ""

    anchor = _raw(SPEC_ANCHOR_LINE).strip() == SPEC_ANCHOR_TEXT
    rows = []
    for a in AXES:
        raw = _raw(a["spec_line"])
        # 規格那五行的形狀是兩個空格加 `≠ `，逐字比對整行。
        hit = raw.strip() == f"≠ {a['axis']}"
        rows.append({"key": a["key"], "line": a["spec_line"],
                     "ok": hit, "raw": raw.strip()})
    return {"ok": anchor and all(r["ok"] for r in rows),
            "anchor_ok": anchor,
            "anchor_line": SPEC_ANCHOR_LINE,
            "rows": rows, "spec": SPEC, "checked": len(rows)}


# ---------------------------------------------------------------------------
# 五，逐軸判定
# ---------------------------------------------------------------------------

def assess(repo: Path | None = None, limit: int = 80,
           root: Path | None = None, db: Path | None = None) -> dict:
    """五個軸各自的現況。

    每一軸的 `state` 都要講得出依據(`evidence`),講不出來的一律
    `NO_SOURCE`。**沒有第四種狀態叫「看起來沒問題」。**
    """
    sv = survey(limit=limit, root=root)
    dr = drift(repo, db)
    act = actors(db)

    rows = []
    for a in AXES:
        state = "NO_SOURCE"
        ev = ""
        live = None

        if a["key"] == "model":
            n = sv["multi_model_count"]
            live = {"measured": True,
                    "value": n,
                    "of": sv["scanned"]}
            if sv["scanned"] == 0:
                state, ev = "NO_SOURCE", "一條 session 都沒掃到"
            elif n > 0:
                state = "SEPARABLE"
                ev = (f"掃過的 {sv['scanned']} 條裡有 {n} 條在同一條線內"
                      f"用過不只一個模型，所以這條線的身份不等於模型")
            else:
                state = "NO_SOURCE"
                ev = (f"掃過的 {sv['scanned']} 條每一條都只用過一個模型。"
                      "那是「沒遇到」不是「分不開」，所以不給結論")

        elif a["key"] == "session":
            live = {"measured": True,
                    "value": dr["registered"],
                    "of": dr["actors_seen"]}
            if not act.get("available"):
                state, ev = "NO_SOURCE", act.get("why", "帳本沒有量")
            elif dr["registered"] == 0 and dr["actors_seen"] > 0:
                state = "CONFLATED"
                ev = (f"帳本裡有 {dr['actors_seen']} 個字串被當成「誰做的」"
                      f"，而持久身份登記 0 條。"
                      "那些字串是 session alias，換 session 就換，"
                      "所以這個 repo 現在的「身份」就是 Session 這一軸")
            elif dr["unregistered"]:
                state = "CONFLATED"
                ev = (f"有 {len(dr['unregistered'])} 個 alias 沒有任何"
                      "持久身份認領，所以它們只代表那一條 session")
            else:
                state = "SEPARABLE"
                ev = (f"帳本裡出現的 {dr['actors_seen']} 個 alias "
                      f"全部由 {dr['registered']} 個登記身份認領")

        elif a["key"] == "process":
            # 這一格的依據是「掃過而且沒有這個欄位」,不是「我記得沒有」。
            live = {"measured": True,
                    "value": sv["pid_field_sessions"],
                    "of": sv["scanned"]}
            state = "NO_SOURCE"
            ev = (f"掃過的 {sv['scanned']} 條 session 裡，"
                  f"有 pid 欄位的是 {sv['pid_field_sessions']} 條。"
                  "沒有程序識別就量不出「程序死了身份還在不在」")

        elif a["key"] == "role":
            live = {"measured": True,
                    "value": sv["role_field_sessions"],
                    "of": sv["scanned"]}
            state = "NO_SOURCE"
            ev = ("帳本的 worker 名稱看起來像角色(book-reader、"
                  "claude-p-worker)，但那是 alias 不是角色定義:"
                  "沒有任何地方寫著這個角色能做什麼、不能做什麼。"
                  f"session 那邊有 role 欄位的是 {sv['role_field_sessions']} 條")

        else:  # execution_slot
            live = None
            state = "NO_SOURCE"
            ev = ("這條線沒有執行槽這個概念:沒有排程器、沒有 worker pool、"
                  "jsonl 與帳本都沒有對應欄位。"
                  "這一格不給燈號，因為一個沒被檢查過的綠燈比沒有燈更糟")

        rows.append({
            "key": a["key"], "axis": a["axis"], "axis_zh": a["axis_zh"],
            "question": a["question"],
            "spec": f"{SPEC}:{a['spec_line']}",
            "state": state, "evidence": ev, "live": live,
        })

    counts = {s: sum(1 for r in rows if r["state"] == s) for s in STATES}
    return {
        "rows": rows,
        "by_state": counts,
        "total": len(rows),
        "survey": sv,
        "drift": dr,
        "registered": dr["registered"],
        # 誠實條款,三條,都要看得見:
        "sampled_note": (f"model 那一軸的分母是抽樣的 {sv['scanned']} 條，"
                         f"磁碟上總共 {sv['total_sessions_on_disk']} 條"),
        "no_source_note": ("NO_SOURCE 是「這個 repo 沒有資料來源」，"
                           "不是「這一軸沒問題」。三軸沒有來源"
                           "就是三軸答不出來"),
        "no_fuzzy_note": dr["why_no_fuzzy"],
        "source": "v5.0 §11.1 Agent and session are not the same thing",
    }


def summary(repo: Path | None = None, limit: int = 80) -> dict:
    a = assess(repo, limit=limit)
    return {
        "total": a["total"],
        "by_state": a["by_state"],
        "registered": a["registered"],
        "unregistered": len(a["drift"]["unregistered"]),
        "stale": len(a["drift"]["stale"]),
        "scanned": a["survey"]["scanned"],
        "sampled_note": a["sampled_note"],
        "no_source_note": a["no_source_note"],
        "source": a["source"],
    }


_MARK = {"SEPARABLE": "分得開", "CONFLATED": "混在一起",
         "NO_SOURCE": "沒有來源"}


def main(argv: list[str]) -> int:
    arg = argv[1] if len(argv) > 1 else ""
    if arg == "--json":
        print(json.dumps(assess(), ensure_ascii=False, indent=2))
        return 0
    if arg == "--verify":
        print(json.dumps(verify_spec(), ensure_ascii=False, indent=2))
        return 0
    if arg == "--drift":
        print(json.dumps(drift(), ensure_ascii=False, indent=2))
        return 0
    a = assess()
    print(f"§11.1 持久身份　{a['total']} 個軸")
    print(f"　{a['no_source_note']}")
    print(f"　{a['sampled_note']}")
    print()
    for r in a["rows"]:
        print(f"[{_MARK[r['state']]}] 身份 ≠ {r['axis']}（{r['axis_zh']}）")
        print(f"　  問的是:{r['question']}")
        print(f"　  依據:{r['evidence']}")
        print(f"　  出處:{r['spec']}")
        print()
    d = a["drift"]
    print(f"　登記身份 {d['registered']} 個，"
          f"帳本出現 {d['actors_seen']} 個 alias，"
          f"沒人認領 {len(d['unregistered'])} 個")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
