#!/usr/bin/env python3
"""Lineage 邊。v5.0 §6.3

## 這一支為什麼現在才長出來

`event_ledger.py` 的 `LINEAGE_EDGES` 從寫下的那天起就是十個名字，
同檔 `SPEC_DEVIATIONS` 給的理由是「等 claim 與 decision 存在」。
2026-09-18 逐一查證，**那個理由兩半都不成立**：

- decision 存在而且指得到：`.forseti/DECISION_LEDGER.md` 的
  `## ADR-001` 到 `## ADR-010`，十條，標題行是穩定的 id。
- claim 存在：`claims.py` 有 §7.1 的六個狀態、§7.2 的 E0-E4、
  `verify()` 與 `promote()`。它缺的不是「存在」，是 `Claim`
  這個 dataclass 沒有 `id` 欄位、也沒有落地的儲存，所以指不到。

兩件事差很多。「還沒有」會讓下一個人去寫一個 claim 模組（已經有了），
「有但指不到」會讓他去加 id 與儲存（那才是缺的）。一個錯的理由
比沒有理由貴，因為它會把後面每一次判斷都導向錯的地方。

## 這一支做什麼

一，把 §6.3 那十條邊變成**會執行的約束**，不是十個名字。
`add()` 拒收不在 `LINEAGE_EDGES` 裡的型別，也拒收兩端型別
跟 §6.3 對不上的邊。拒收不修正 —— 跟 `event_ledger.LedgerError`
同一條理由：一個被默默改過的邊比被拒絕的危險。

二，`readiness()` 回答「這十條邊，此刻哪一條的兩端真的指得到」。
這個答案是**量出來的**：去讀那些檔、數那些列、看那些 dataclass
有沒有 id 欄位，不是我在註解裡宣告的。

## 這一支刻意不做什麼

**不自動產生任何一條邊。** 現在磁碟上零條，`readiness()` 講得出
為什麼零條：兩端都指得到的邊有幾條、缺的那一步是什麼。

最接近可以產的是 `PRODUCES`：workflow step 有 `step_id`，
而且帶著 `expected_outputs` 的檔案路徑。**但 expected 不等於
produced** —— 把一個 VERIFIED_COMPLETE 的步驟的「預期產出」
當成「實際產出」是一次判斷，不是一次讀取。§8.3 的 forbidden
shortcut 指的正是這種：規格沒有定義的地方自己補一個看起來合理的。
所以這裡把它列成「差一個判斷」，把那個判斷留給人，不自己做掉。

零依賴（ADR-009）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "lineage.jsonl"
_HERE = Path(__file__).resolve().parent


def _sibling(name: str):
    if str(_HERE) not in sys.path:
        sys.path.insert(0, str(_HERE))
    return importlib.import_module(name)


# ---------------------------------------------------------------------------
# §6.3 的兩端型別
# ---------------------------------------------------------------------------
#
# 規格那十行用了兩種箭頭：`decision <- evidence` 與 `evidence -> claim`。
# 兩種寫法讀起來都是「邊的名字從左邊念到右邊」——
# 「decision DERIVED_FROM evidence」、「evidence VERIFIES claim」。
# 所以這裡一律正規化成 (主詞, 受詞)，也就是邊實際指的方向。
#
# **這是一次正規化，不是規格原文。** 規格沒有明寫方向要怎麼統一，
# 寫在這裡是為了讓下一個人知道這一步是誰做的、根據是什麼。
EDGE_ENDPOINTS: dict[str, tuple[str, str]] = {
    "DERIVED_FROM":       ("decision", "evidence"),
    "TRIGGERED_BY":       ("tool_call", "decision"),
    "VERIFIES":           ("evidence", "claim"),
    "REFUTES":            ("evidence", "claim"),
    "SUPERSEDES":         ("decision", "decision"),
    "CONSUMES":           ("workflow_step", "artifact"),
    "PRODUCES":           ("workflow_step", "artifact"),
    "PROMOTES":           ("authority", "hypothesis_or_fact"),
    "PROPAGATES_TO":      ("incident", "node"),
    "RECONSTRUCTED_FROM": ("checkpoint", "raw_event"),
}

#: 規格原文那一行長什麼樣。留著是為了讓上面的正規化可以被對照。
SPEC_TEXT: dict[str, str] = {
    "DERIVED_FROM":       "decision <- evidence",
    "TRIGGERED_BY":       "tool_call <- decision",
    "VERIFIES":           "evidence -> claim",
    "REFUTES":            "evidence -> claim",
    "SUPERSEDES":         "decision -> decision",
    "CONSUMES":           "workflow_step -> artifact",
    "PRODUCES":           "workflow_step -> artifact",
    "PROMOTES":           "authority -> hypothesis/fact",
    "PROPAGATES_TO":      "incident -> downstream node",
    "RECONSTRUCTED_FROM": "checkpoint -> raw events",
}

#: 四種可定址狀態。**`NOT_ADDRESSABLE` 跟 `NO_SOURCE` 不能合併** ——
#: 前者要加 id 與儲存，後者要從零寫一個實體，處置完全不一樣。
READINESS = ("ADDRESSABLE", "NOT_ADDRESSABLE", "NO_INSTANCES", "NO_SOURCE")


class LineageError(Exception):
    """邊不合 §6.3。拒收而不是修正。"""


def edge_types() -> tuple[str, ...]:
    """合法的邊型別。**唯一來源是 `event_ledger.LINEAGE_EDGES`** ——
    不在這裡再抄一份，抄一份就會有兩份會分歧的規格。
    """
    return tuple(_sibling("event_ledger").LINEAGE_EDGES)


def spec_alignment() -> dict:
    """`EDGE_ENDPOINTS` 有沒有跟 `LINEAGE_EDGES` 對齊。

    兩張表分在兩個檔，所以它們會分開腐爛。這一支把那件事變成
    答得出來的，而不是等哪天有人發現少一條。
    """
    names = set(edge_types())
    mine = set(EDGE_ENDPOINTS)
    return {
        "ok": names == mine == set(SPEC_TEXT),
        "only_in_ledger": sorted(names - mine),
        "only_here": sorted(mine - names),
        "missing_spec_text": sorted(mine - set(SPEC_TEXT)),
    }


# ---------------------------------------------------------------------------
# 端點解析。每一支只回「量到什麼」，量不到就說量不到。
# ---------------------------------------------------------------------------

_ADR = re.compile(r"^##\s+(ADR-\d+)", re.MULTILINE)
_INC = re.compile(r"\binc-[0-9a-f]{6,}\b")


def _r(status: str, *, n: int | None, why: str, source: str = "",
       example: str = "") -> dict:
    assert status in READINESS, status
    return {"status": status, "n": n, "why": why,
            "source": source, "example": example}


def _kind_decision(repo: Path) -> dict:
    p = repo / ".forseti" / "DECISION_LEDGER.md"
    if not p.exists():
        return _r("NO_SOURCE", n=None, why="DECISION_LEDGER.md 不在",
                  source=str(p))
    ids = _ADR.findall(p.read_text(encoding="utf-8", errors="replace"))
    uniq = sorted(set(ids))
    if not uniq:
        return _r("NO_INSTANCES", n=0,
                  why="檔在，但沒有 `## ADR-NNN` 這種標題行",
                  source=".forseti/DECISION_LEDGER.md")
    return _r("ADDRESSABLE", n=len(uniq),
              why="標題行 `## ADR-NNN` 就是穩定的 id",
              source=".forseti/DECISION_LEDGER.md", example=uniq[0])


def _kind_claim(repo: Path) -> dict:
    try:
        cl = _sibling("claims")
    except Exception as e:                            # noqa: BLE001
        return _r("NO_SOURCE", n=None,
                  why=f"claims 模組載不進來：{type(e).__name__}")
    klass = getattr(cl, "Claim", None)
    if klass is None or not dataclasses.is_dataclass(klass):
        return _r("NO_SOURCE", n=None, why="claims 裡沒有 Claim 這個 dataclass")
    fields = {f.name for f in dataclasses.fields(klass)}
    store = repo / ".forseti" / "claims.jsonl"
    if "id" in fields:
        n = _count_lines(store)
        if n:
            return _r("ADDRESSABLE", n=n,
                      why="Claim 有 id 欄位，claims.jsonl 上有得指",
                      source=str(store))
        # 跟 evidence 那一支同一條理由：不寫清楚的話，「沒有模組」跟
        # 「有模組但沒有人登」在畫面上長得一樣，而那正是
        # `pol-ce2f84f5b5` 那一筆的機制。**下一步差的是一筆真的宣稱，
        # 不是一個模組。**
        return _r("NO_INSTANCES", n=0,
                  why=("Claim 有 id（`claims.make_cid()`）與 claims.jsonl "
                       "的落地（2026-09-18），磁碟上一筆都還沒有人登。"
                       "**這跟 NOT_ADDRESSABLE 不一樣** —— 缺的是一筆"
                       "真的被寫下來的宣稱，不是一個 id 欄位"),
                  source=str(store))
    return _r("NOT_ADDRESSABLE", n=None,
              why=("claims.py 有 §7.1 生命週期與 §7.2 強度，"
                   "但 Claim 這個 dataclass 沒有 id 欄位，"
                   f"也沒有 {store.name}。指不到就連不了邊"),
              source="apps/forseti-cli/claims.py")


def _kind_evidence(repo: Path) -> dict:
    try:
        ev = _sibling("evidence")
    except Exception as e:                            # noqa: BLE001
        return _r("NO_SOURCE", n=None,
                  why=f"evidence 模組載不進來：{type(e).__name__}")
    klass = getattr(ev, "Evidence", None)
    if klass is None or not dataclasses.is_dataclass(klass):
        return _r("NO_SOURCE", n=None,
                  why=("evidence.py 只有分級與鏈結檢查的函式（level_index / "
                       "can_support / check_chain），沒有 Evidence 這個實體，"
                       "也沒有任何一筆證據帶得出 id"),
                  source="apps/forseti-cli/evidence.py")
    fields = {f.name for f in dataclasses.fields(klass)}
    if "id" not in fields:
        return _r("NOT_ADDRESSABLE", n=None,
                  why="evidence 有 Evidence 這個 dataclass，但它沒有 id 欄位",
                  source="apps/forseti-cli/evidence.py")
    store = getattr(ev, "log_path", None)
    if store is None:
        return _r("NOT_ADDRESSABLE", n=None,
                  why="Evidence 有 id，但 evidence.py 沒有 log_path()，"
                      "所以一筆證據落不了地，換一條 session 就指不到",
                  source="apps/forseti-cli/evidence.py")
    p = Path(store(repo))
    n = _count_lines(p)
    if not n:
        return _r("NO_INSTANCES", n=0,
                  why=("Evidence 實體與 evidence.jsonl 的落地都在了（2026-09-18），"
                       "磁碟上一筆都還沒有人登。**這跟 NO_SOURCE 不一樣** ——"
                       "缺的是一筆真的觀察，不是一個模組。"
                       "登記的入口同日做好了：`forseti evidence template` 產模板，"
                       "填完 `forseti evidence register --from <檔案>`。"
                       "**那一支不自動登記**，拿現成的東西配一組猜出來的欄位"
                       "就是 §8.3 的填空"),
                  source=str(p))
    ids = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ids.append(json.loads(line).get("id"))
        except ValueError:
            continue
    ids = [i for i in ids if i]
    if not ids:
        return _r("NO_INSTANCES", n=0, why="檔在，但沒有帶 id 的證據",
                  source=str(p))
    return _r("ADDRESSABLE", n=len(ids),
              why="evidence.record() 給的 `ev-` id（§5 evidence_id）",
              source=str(p), example=str(ids[0]))


def _norm_rows(repo: Path) -> list[dict]:
    p = repo / ".forseti" / "event_ledger.jsonl"
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _kind_tool_call(repo: Path) -> dict:
    rows = _norm_rows(repo)
    ids = [(r.get("norm") or {}).get("id") for r in rows
           if (r.get("norm") or {}).get("type") == "TOOL_CALL"]
    ids = [i for i in ids if i]
    if not rows:
        return _r("NO_SOURCE", n=None, why="event_ledger.jsonl 不在或讀不到")
    if not ids:
        return _r("NO_INSTANCES", n=0,
                  why="帳本在，但沒有帶 id 的 TOOL_CALL",
                  source=".forseti/event_ledger.jsonl")
    return _r("ADDRESSABLE", n=len(ids),
              why="正規化事件的 id（§6.1 NormalizedEvent.id）",
              source=".forseti/event_ledger.jsonl", example=str(ids[0]))


def _kind_raw_event(repo: Path) -> dict:
    rows = _norm_rows(repo)
    ids = [(r.get("raw") or {}).get("id") for r in rows]
    ids = [i for i in ids if i]
    if not rows:
        return _r("NO_SOURCE", n=None, why="event_ledger.jsonl 不在或讀不到")
    if not ids:
        return _r("NO_INSTANCES", n=0, why="帳本在，但沒有帶 id 的 raw",
                  source=".forseti/event_ledger.jsonl")
    return _r("ADDRESSABLE", n=len(ids),
              why="原始事件的 id（§6.1 RawEvent.id）",
              source=".forseti/event_ledger.jsonl", example=str(ids[0]))


def _kind_incident(repo: Path) -> dict:
    rows = _norm_rows(repo)
    found: set[str] = set()
    for r in rows:
        found.update(_INC.findall(json.dumps(r, ensure_ascii=False)))
    if not rows:
        return _r("NO_SOURCE", n=None, why="event_ledger.jsonl 不在或讀不到")
    if not found:
        return _r("NO_INSTANCES", n=0,
                  why="帳本在，但沒有任何 `inc-` 事故 id",
                  source=".forseti/event_ledger.jsonl")
    return _r("ADDRESSABLE", n=len(found),
              why="rescue.py 開事故時寫進帳本的 `inc-` id",
              source=".forseti/event_ledger.jsonl",
              example=sorted(found)[0])


def _count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for ln in p.read_text(encoding="utf-8",
                                       errors="replace").splitlines()
               if ln.strip())


def _kind_checkpoint(repo: Path) -> dict:
    p = repo / ".forseti" / "checkpoints.jsonl"
    if not p.exists():
        return _r("NO_INSTANCES", n=0,
                  why="checkpoint.py 在，但磁碟上一筆都沒有",
                  source=str(p))
    ids = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ids.append(json.loads(line).get("id"))
        except ValueError:
            continue
    ids = [i for i in ids if i]
    if not ids:
        return _r("NO_INSTANCES", n=0, why="檔在，但沒有帶 id 的 checkpoint",
                  source=".forseti/checkpoints.jsonl")
    return _r("ADDRESSABLE", n=len(ids), why="checkpoint.create() 給的 `cp-` id",
              source=".forseti/checkpoints.jsonl", example=str(ids[0]))


def _kind_workflow_step(repo: Path) -> dict:
    try:
        wf = _sibling("workflow")
        got = wf.workflows()
    except Exception as e:                            # noqa: BLE001
        return _r("NO_SOURCE", n=None,
                  why=f"workflow 查不動：{type(e).__name__}")
    if not got.get("available"):
        return _r("NO_SOURCE", n=None,
                  why=got.get("note") or "workflow 說它現在查不到")
    n, example = 0, ""
    for w in got.get("workflows") or []:
        r = wf.resume(w.get("workflow_id", ""))
        for bucket in ("ready", "blocked", "done"):
            for s in r.get(bucket) or []:
                sid = s.get("step_id")
                if sid:
                    n += 1
                    example = example or str(sid)
    if not n:
        return _r("NO_INSTANCES", n=0, why="有 workflow，但沒有帶 step_id 的步驟")
    return _r("ADDRESSABLE", n=n, why="WorkflowStep 的 step_id",
              source="Task Ledger（workflow.resume）", example=example)


def _kind_artifact(repo: Path) -> dict:
    """產出的 id 是它的 repo 相對路徑。

    **這裡不算雜湊。** 邊要的是「指得到哪一個產出」，路徑就指得到；
    雜湊回答的是另一個問題（內容這一刻有沒有變），那是
    `contract.artifact_drift()` 的事。兩件事併在一起的話，
    一個檔案被改過就會變成「另一個產出」，而它不是。

    數量拿 `git ls-files` 當母體，理由是：**這一欄要答的是
    「有多少產出指得到」，不是「有多少產出這一輪動過」**。
    用 `contract.worktree_paths()` 會把母體縮成後者，
    然後這個數字會隨著有沒有人 commit 上下跳，而可定址性不會。
    """
    try:
        res = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                             capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        return _r("NOT_ADDRESSABLE", n=None,
                  why=f"數不到產出母體，跑 git 失敗：{type(e).__name__}。"
                      "路徑本身仍然是穩定的 id，但這裡不給一個量不到的數字",
                  source="git ls-files")
    if res.returncode != 0:
        why = " ".join((res.stderr or b"").decode("utf-8", "replace").split())[:80]
        return _r("NOT_ADDRESSABLE", n=None,
                  why=f"數不到產出母體：git ls-files 失敗（{why}）",
                  source="git ls-files")
    paths = [f.decode("utf-8", "replace")
             for f in res.stdout.split(b"\0") if f]
    if not paths:
        return _r("NO_INSTANCES", n=0, why="git 說這個 repo 沒有追蹤中的檔案",
                  source="git ls-files")
    return _r("ADDRESSABLE", n=len(paths),
              why="產出的 id 就是它的 repo 相對路徑",
              source="git ls-files", example=paths[0])


def _kind_authority(repo: Path) -> dict:
    try:
        au = _sibling("authority")
    except Exception as e:                            # noqa: BLE001
        return _r("NO_SOURCE", n=None,
                  why=f"authority 模組載不進來：{type(e).__name__}")
    trust = getattr(au, "TRUST", None)
    if not trust:
        return _r("NO_SOURCE", n=None, why="authority 裡沒有 TRUST 這張信任階層")
    names = list(trust)
    return _r("ADDRESSABLE", n=len(names),
              why="§9 信任階層裡的 principal 名字就是 id",
              source="apps/forseti-cli/authority.py", example=str(names[0]))


def _kind_node(repo: Path) -> dict:
    try:
        bl = _sibling("blast")
        got = bl.collect(repo)
    except Exception as e:                            # noqa: BLE001
        return _r("NO_SOURCE", n=None, why=f"blast 查不動：{type(e).__name__}")
    nodes = got.get("nodes") or got.get("files") or []
    n = len(nodes)
    if not n:
        return _r("NO_INSTANCES", n=0, why="import 圖建得起來，但一個節點都沒有")
    ex = nodes[0] if isinstance(nodes[0], str) else str(nodes[0])
    return _r("ADDRESSABLE", n=n,
              why="依賴圖的節點就是原始檔的相對路徑",
              source="apps/forseti-cli/blast.py", example=ex)


def _kind_hypothesis_or_fact(repo: Path) -> dict:
    return _r("NO_SOURCE", n=None,
              why=("§6.3 的 PROMOTES 指向 hypothesis/fact，"
                   "而這個 repo 沒有這兩個實體。`claims.py` 的 CANONICAL "
                   "是同一件事的另一種說法（§7.1），但它是 Claim 的一個"
                   "**狀態**不是一個物件，所以指不到。要不要把兩者對應起來"
                   "是規格層的決定，不在這裡自己接"),
              source="apps/forseti-cli/claims.py")


RESOLVERS = {
    "decision": _kind_decision,
    "evidence": _kind_evidence,
    "claim": _kind_claim,
    "tool_call": _kind_tool_call,
    "raw_event": _kind_raw_event,
    "incident": _kind_incident,
    "checkpoint": _kind_checkpoint,
    "workflow_step": _kind_workflow_step,
    "artifact": _kind_artifact,
    "authority": _kind_authority,
    "node": _kind_node,
    "hypothesis_or_fact": _kind_hypothesis_or_fact,
}


def kinds(repo: Path | None = None) -> dict:
    """每一種端點型別此刻指不指得到。量出來的，不是宣告的。"""
    base = Path(repo or REPO)
    return {k: fn(base) for k, fn in RESOLVERS.items()}


def readiness(repo: Path | None = None) -> dict:
    """十條邊，此刻哪一條的兩端都指得到。

    `ready` 的意思是**兩端指得到**，不是「有邊」。磁碟上有幾條邊
    是另一個數字（`count`），兩個分開放是刻意的 —— 合成一個的話，
    「機制在那裡」跟「真的走過」會長得一樣，而那正是
    `probemodel.AXES_COVERED` 那一條守著的事。
    """
    base = Path(repo or REPO)
    ks = kinds(base)
    out, ready = {}, []
    for name in edge_types():
        ends = EDGE_ENDPOINTS.get(name)
        if ends is None:
            out[name] = {"ready": False,
                         "why": "這條邊在 LINEAGE_EDGES 裡，但 EDGE_ENDPOINTS "
                                "沒有它的兩端型別。兩張表分開腐爛了",
                         "endpoints": None}
            continue
        a, b = ends
        ea, eb = ks[a], ks[b]
        ok = ea["status"] == "ADDRESSABLE" and eb["status"] == "ADDRESSABLE"
        if ok:
            ready.append(name)
        out[name] = {"ready": ok, "spec": SPEC_TEXT.get(name, ""),
                     "endpoints": {a: ea, b: eb},
                     "blocked_by": [k for k, e in ((a, ea), (b, eb))
                                    if e["status"] != "ADDRESSABLE"]}
    return {"edges": out, "ready": sorted(ready), "ready_n": len(ready),
            "total": len(out), "count": len(load(path=log_path(base))),
            "kinds": ks, "alignment": spec_alignment()}


# ---------------------------------------------------------------------------
# 邊本身
# ---------------------------------------------------------------------------

def log_path(repo: Path | None = None) -> Path:
    """邊落在哪。公開，因為守門要問得到「不傳參數的時候它去哪」
    （`tests/test_module_write_targets.py` 的 `_default_of`）。"""
    return Path(repo or REPO) / ".forseti" / "lineage.jsonl"


def _eid(row: dict) -> str:
    raw = f"{row['type']}|{row['from_kind']}:{row['from_id']}|" \
          f"{row['to_kind']}:{row['to_id']}"
    return "ln-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def add(*, type: str, from_id: str, to_id: str,
        from_kind: str = "", to_kind: str = "", basis: str = "",
        at: float | None = None, path: Path | None = None) -> dict:
    """加一條邊。不合 §6.3 就拒收，不修正。

    `basis` 必填：這條邊是根據什麼連的。空的就退回 —— 一條講不出
    根據的 lineage 邊，在需要它的時候（追一個結論是怎麼來的）
    正好是最沒有用的那一種。
    """
    t = (type or "").strip()
    if t not in edge_types():
        return {"ok": False,
                "why": f"{t!r} 不是 §6.3 的邊。合法的是："
                       f"{'、'.join(edge_types())}"}
    want_a, want_b = EDGE_ENDPOINTS[t]
    fk = (from_kind or want_a).strip()
    tk = (to_kind or want_b).strip()
    if (fk, tk) != (want_a, want_b):
        return {"ok": False,
                "why": f"{t} 的兩端照 §6.3 是 {want_a} -> {want_b}"
                       f"（原文 `{SPEC_TEXT[t]}`），收到的是 {fk} -> {tk}"}
    if not str(from_id).strip() or not str(to_id).strip():
        return {"ok": False, "why": "兩端的 id 都不能是空的"}
    if not (basis or "").strip():
        return {"ok": False,
                "why": "basis 是空的。一條講不出根據的邊，"
                       "在需要追來源的時候正好沒有用"}
    row = {"type": t, "from_kind": fk, "from_id": str(from_id),
           "to_kind": tk, "to_id": str(to_id),
           "basis": basis.strip(), "at": at or time.time()}
    row["id"] = _eid(row)
    p = path or log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return {"ok": True, "edge": row}


def load(path: Path | None = None) -> list[dict]:
    p = path or log_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def walk(node_id: str, *, direction: str = "down", depth: int = 3,
         path: Path | None = None) -> dict:
    """從一個節點走。`down` 是順著邊走，`up` 是逆著走。

    回傳帶 `edges_total`，因為「走不到」有兩種：沒有邊可走，
    以及有邊但都不接這個節點。兩種的處置不一樣。
    """
    if direction not in ("down", "up"):
        return {"ok": False, "why": "direction 只能是 down 或 up"}
    edges = load(path)
    seen, frontier, hops = {str(node_id)}, [str(node_id)], []
    for _ in range(max(0, int(depth))):
        nxt = []
        for e in edges:
            a, b = (e["from_id"], e["to_id"]) if direction == "down" \
                else (e["to_id"], e["from_id"])
            if a in frontier and b not in seen:
                seen.add(b)
                nxt.append(b)
                hops.append(e)
        if not nxt:
            break
        frontier = nxt
    return {"ok": True, "start": str(node_id), "direction": direction,
            "reached": sorted(seen - {str(node_id)}), "edges": hops,
            "edges_total": len(edges)}


def summary(repo: Path | None = None) -> dict:
    r = readiness(repo)
    return {"count": r["count"], "ready_n": r["ready_n"],
            "total": r["total"], "ready": r["ready"]}


def lines(r: dict | None = None, repo: Path | None = None) -> list[str]:
    """印進 doctor 的幾行。**先講最壞的消息** —— 磁碟上有幾條邊。"""
    r = r or readiness(repo)
    out = [f"    磁碟上的 lineage 邊　{r['count']} 條"
           f"（十條邊型別裡 {r['ready_n']} 條的兩端此刻指得到）"]
    if not r["alignment"]["ok"]:
        out.append("    ！EDGE_ENDPOINTS 跟 LINEAGE_EDGES 對不齊："
                   f"{r['alignment']}")
    if r["ready"]:
        out.append("      兩端都指得到：" + "、".join(r["ready"]))
    blocked: dict[str, list[str]] = {}
    for name, e in r["edges"].items():
        for k in e.get("blocked_by") or []:
            blocked.setdefault(k, []).append(name)
    for kind, names in sorted(blocked.items(), key=lambda kv: -len(kv[1])):
        st = r["kinds"][kind]
        out.append(f"      {kind}　{st['status']}　擋住 {len(names)} 條"
                   f"（{'、'.join(names)}）")
        out.append(f"        {st['why']}")
    return out


def _main(argv: list[str]) -> int:
    for ln in lines():
        print(ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
