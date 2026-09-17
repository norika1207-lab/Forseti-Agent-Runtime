#!/usr/bin/env python3
"""反錨定接手協議的中間四步。v5.0 §39

規格原文（v5.0 §39，`docs/sources/` 底下那份第 1213 行起）：

    A successor can be biased simply by reading the current answer before
    deriving it. Forseti's takeover protocol must separate rules/evidence
    from the expected answer when independent reconstruction is being tested.

    1. Load North Star, current canonical rules, source map, pollution
       registry and evidence ledger.
    2. Do not expose the canonical current-answer artifact yet.
    3. Successor independently derives current state, priority order,
       blockers, and next safe action.
    4. Persist the successor's derived answer.
    5. Reveal canonical answer and compare.
    6. Classify differences as successor reasoning error, stale canonical
       answer, changed reality, or defective rule.
    7. Only after reconciliation may the successor receive write/commit
       authority.

`sufficiency.py` 做的是第 2 步與第 7 步，它自己的模組說明寫著
「中間那幾步要有正典答案這個物件才談得上，那個物件還不存在」。
**這一支就是那個物件，加上第 3 到第 6 步。**

## 正典答案的四欄，一欄都不是我算的

第 3 步點名四樣：current state、priority order、blockers、next safe
action。這四欄各自借一支**已經存在**的判斷，不在這裡再判一次 ——
理由跟 `contract.py` 第 385 行那一段一樣：兩份會分歧的判斷遲早會分歧，
而分歧那天不會有錯誤訊息。

| 欄 | 借誰 |
|---|---|
| `state` | `snap["verified"]`，`desktop_api._write_handoff` 算的那一份 |
| `priority_order` | **沒有來源** |
| `blockers` | `contract._blockers_field(work)` |
| `next_action` | `contract._next_step(work)` |

`priority_order` 的正典是 v5.0 §41 的 triage 引擎，**那支沒有實作**
（2026-09-17 查過：`apps/forseti-cli/` 底下沒有任何檔提到 triage）。
所以它回 `NO_SOURCE`，不拿 ROADMAP 的章節順序頂替 ——
那是一份人寫的文件，不是系統算出來的正典，拿它當正典會讓這道門
考的是「有沒有讀過 ROADMAP」，不是「推導對不對」。

## 兩邊都空，不算答對

比對的結果有四種，`SAME` / `DIFFERENT` / `NOT_COMPARABLE` /
`CANONICAL_MISSING`，**兩邊都空是第三種不是第一種**。

這是這支最容易造假的地方：正典欄位空、受測者也交白卷，字串比對
會說「一致」，於是一場什麼都沒驗到的接手考試看起來滿分。
所以沒有正典可揭曉的欄位一律不算進通過率，而且在紀錄裡留著名字。

## 分類不自動判，這是刻意的

第 6 步的四類（推錯 / 正典過期 / 現實變了 / 規則有問題）**沒有一個
算得出來**。同一個「不一樣」，四種解釋都成立，要選哪一種靠的是
去查那個差異背後發生了什麼事。

自動判一個出來就是 v5.0 §8.3 的填空捷徑，而這個專案的污染登記簿
（§40）裡已經有九筆是這樣來的。所以 `classify()` 只收人標的，
`by` 是必填，標不出來就讓它留在未分類，**和解就不會完成**。

## 承諾 hash 防的是掉包，不是偷看

`open_derivation()` 記下當下正典的 sha256，`reveal()` 重新算一次比對。
不一樣的話紀錄裡標 `canonical_changed=True` ——
**那是事實不是判定**：正典在推導期間變了，它可能正是第 6 步的
「現實變了」，也可能是有人去改了來源，兩者這一支分不出來。

**這防不了偷看。** 一個讀得到 `.forseti/` 的 session 自己叫一次
`canonical()` 就看到全部答案了。`sufficiency.py` 對自己那道門說過
同一句話，這裡一樣不假裝它擋得住：要真的防，答案得存在受測者
拿不到的地方，那是另一層架構，現在沒有。

## 這一版不強制

跟 `sufficiency.py` 同一個立場。`reconciliation()` 算得出狀態、
說得出還缺哪幾欄沒分類，但沒有任何地方會因為沒和解就擋住寫入。
`config.json` 的 `antianchor_enforce` 預設 false。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG_NAME = "antianchor.jsonl"

#: §39 第 3 步點名的四樣，順序照原文，沒有增減。
#: (key, 原文的說法, 中文)
FIELDS = (
    ("state", "current state", "現在的狀態"),
    ("priority_order", "priority order", "優先順序"),
    ("blockers", "blockers", "被什麼擋住"),
    ("next_action", "next safe action", "下一個安全的動作"),
)

#: §39 第 6 步的四類，原文那一句的四個詞，沒有第五類。
CLASSES = (
    ("SUCCESSOR_REASONING_ERROR", "successor reasoning error", "接手的人推錯"),
    ("STALE_CANONICAL", "stale canonical answer", "正典過期了"),
    ("CHANGED_REALITY", "changed reality", "現實變了"),
    ("DEFECTIVE_RULE", "defective rule", "規則本身有問題"),
)

#: 欄位有沒有正典可以揭曉。三種，不混成一種。
HAS_VALUE = "HAS_VALUE"       # 有值
EMPTY = "EMPTY"               # 來源在，此刻空的，說得出要怎樣才會有值
NO_SOURCE = "NO_SOURCE"       # 這個系統沒有這一欄的資料來源

#: 一欄比對完的結果。四種。
SAME = "SAME"
DIFFERENT = "DIFFERENT"
NOT_COMPARABLE = "NOT_COMPARABLE"       # 兩邊都沒東西，什麼都沒驗到
CANONICAL_MISSING = "CANONICAL_MISSING"  # 受測者答了，但沒有正典可以對


def _norm_one(s: object) -> str:
    """一行的正規化。只去空白，不做同義詞、不做模糊比對。

    理由跟 `sufficiency._norm` 一樣：差不多對在規格這種東西上就是錯。
    """
    return "".join(str(s or "").split()).replace("　", "")


def _norm_value(v: object) -> tuple:
    """把一欄正規化成可比的東西。

    清單比的是**集合**不是順序 —— `blockers` 與 `next_action` 兩欄
    的來源本身就沒有定義順序（`contract._blockers_field` 照帳本掃描
    順序給，那個順序會因為 jsonl 追加而變）。拿會變的東西當差異，
    每一輪都會多出假差異要人去分類，而那正是 §18 說的 noisy Forseti。

    `priority_order` 是唯一順序有意義的一欄，但它現在沒有來源，
    所以這裡不為它預留分支 —— 等 §41 的 triage 存在再處理。
    **現在就寫一個順序敏感的分支，等於替一個不存在的資料結構
    先決定形狀。**
    """
    if v is None:
        return ()
    if isinstance(v, (list, tuple)):
        return tuple(sorted(_norm_one(x) for x in v if _norm_one(x)))
    s = _norm_one(v)
    return (s,) if s else ()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _cfg(root: Path) -> dict:
    p = Path(root) / ".forseti" / "config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def enforced(root: Path = REPO) -> bool:
    """沒和解會不會真的擋人。預設不會，理由在模組說明。"""
    return bool(_cfg(root).get("antianchor_enforce", False))


def _from_contract(fn_name: str, arg) -> dict:
    """借 `contract.py` 那兩支現成的判斷，把它的回傳翻成這裡的三態。

    `contract` 回的是 list（有值）或 `Empty`（來源在此刻空的，帶一句
    要怎樣才會有值）。**那句話原樣帶過來**，不在這裡重寫一次 ——
    重寫的那一份哪天跟那邊分歧了不會有人發現。
    """
    try:
        import contract as CT
    except ImportError as exc:
        return {"state": NO_SOURCE, "value": None,
                "why": f"`contract.py` 匯入不了：{exc}"}
    fn = getattr(CT, fn_name, None)
    if fn is None:
        return {"state": NO_SOURCE, "value": None,
                "why": f"`contract.{fn_name}` 不存在了，這一欄的來源斷了"}
    try:
        v = fn(arg)
    except Exception as exc:                     # noqa: BLE001
        return {"state": NO_SOURCE, "value": None,
                "why": f"`contract.{fn_name}` 算不出來：{exc!r}"}
    if isinstance(v, list) and v:
        return {"state": HAS_VALUE, "value": list(v),
                "why": "", "source": f"contract.{fn_name}"}
    why = getattr(v, "why", "") or "這一欄此刻是空的"
    return {"state": EMPTY, "value": None, "why": why,
            "source": f"contract.{fn_name}"}


def canonical(snap: dict | None = None, work: dict | None = None,
              root: Path = REPO) -> dict:
    """§39 第 5 步要揭曉的那份東西。四欄，每一欄說得出它借了誰。

    **這一支本身不做任何推導。** 它是一個轉接頭：把四個既有判斷的
    回傳整成同一個形狀，好讓第 5 步有東西可以比對。

    `snap` 與 `work` 照 `contract.py` 的介面收已經算好的字典，
    不在這裡去叫 `desktop_api.strands()` —— 那會讓一支用來考試的
    模組反過來驅動被考的系統。
    """
    fields: dict[str, dict] = {}

    ver = (snap or {}).get("verified") or []
    if ver:
        fields["state"] = {"state": HAS_VALUE, "value": list(ver), "why": "",
                           "source": "snap[\"verified\"]"}
    else:
        fields["state"] = {
            "state": EMPTY, "value": None, "source": "snap[\"verified\"]",
            "why": "這一欄的來源是交接檔的「已驗證的狀態」那一節"
                   "（`desktop_api._write_handoff` 算的 `verified`），此刻空的。"
                   "要有值得有某件事被驗證過並記進那一份"}

    fields["priority_order"] = {
        "state": NO_SOURCE, "value": None, "source": "",
        "why": "正典是 v5.0 §41 的 triage 引擎（rule-derived prioritization），"
               "**那支沒有實作**。`.forseti/ROADMAP.md` 的章節順序不是它的替代品："
               "那是一份人寫的文件，拿它當正典，考的會是「有沒有讀過 ROADMAP」，"
               "不是「推導對不對」"}

    fields["blockers"] = _from_contract("_blockers_field", work)
    fields["next_action"] = _from_contract("_next_step", work)

    payload = {k: list(_norm_value(v.get("value"))) for k, v in fields.items()}
    return {
        "fields": fields,
        "sha": _sha(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        "at": time.time(),
        "answerable": [k for k, v in fields.items() if v["state"] == HAS_VALUE],
        "unanswerable": [k for k, v in fields.items() if v["state"] != HAS_VALUE],
    }


class Log:
    """append-only。跟事件帳本同一個原則：寫下去就是證據。"""

    def __init__(self, root: Path = REPO):
        self.path = Path(root) / ".forseti" / LOG_NAME

    def append(self, row: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def all(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        with self.path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    def rows(self, did: str) -> list[dict]:
        """一次推導的全部紀錄，照寫入順序。"""
        return [r for r in self.all() if r.get("id") == did]

    def latest(self, did: str, kind: str) -> dict | None:
        rs = [r for r in self.rows(did) if r.get("kind") == kind]
        return rs[-1] if rs else None


def open_derivation(root: Path = REPO, *, session: str,
                    snap: dict | None = None, work: dict | None = None,
                    at: float | None = None) -> dict:
    """第 2 步與第 3 步的開始。出一張空卷，**不帶任何答案**。

    回的東西可以直接拿給受測者看：四個欄位的題目、每一欄有沒有正典
    可以揭曉，以及正典此刻的 sha256。**sha 不是答案**，它是承諾：
    揭曉的時候拿來證明那份跟現在這份是同一份。
    """
    can = canonical(snap, work, root)
    ts = at or time.time()
    did = _sha(f"{session}|{ts}|{can['sha']}")[:12]
    row = {
        "kind": "OPEN", "id": did, "at": ts, "session": str(session or ""),
        "canonical_sha": can["sha"],
        "answerable": can["answerable"],
        "unanswerable": can["unanswerable"],
        "asks": [{"field": k, "en": en, "zh": zh,
                  "canonical_state": can["fields"][k]["state"]}
                 for k, en, zh in FIELDS],
    }
    Log(root).append(row)
    return row


def submit(root: Path = REPO, *, derivation_id: str, answer: dict,
           at: float | None = None) -> dict:
    """第 4 步：存下受測者的推導。**存完才准揭曉。**

    重複交卷會被擋。第 5 步已經揭曉過之後還能改答案的話，
    這整套就退化成「看完答案再抄」，而那正是 §39 開頭那一句要防的。
    """
    log = Log(root)
    op = log.latest(derivation_id, "OPEN")
    if op is None:
        return {"ok": False, "why": f"找不到這份推導：{derivation_id}"}
    if log.latest(derivation_id, "DERIVED") is not None:
        return {"ok": False,
                "why": "這份已經交過了。**推導只能交一次** ——"
                       "揭曉之後還能改答案的話，這道門驗的就不是獨立推導"}
    keys = {k for k, _en, _zh in FIELDS}
    got = {k: (answer or {}).get(k) for k in keys}
    row = {"kind": "DERIVED", "id": derivation_id, "at": at or time.time(),
           "session": op.get("session", ""), "answer": got,
           "answered": sorted(k for k, v in got.items() if _norm_value(v))}
    log.append(row)
    return {"ok": True, **row}


def compare_one(mine: object, theirs: dict) -> dict:
    """一欄的比對。四種結果，兩邊都空**不算一致**。

    `theirs` 是 `canonical()['fields'][k]`。
    """
    a = _norm_value(mine)
    has_canonical = theirs.get("state") == HAS_VALUE
    b = _norm_value(theirs.get("value")) if has_canonical else ()

    if not has_canonical and not a:
        return {"result": NOT_COMPARABLE,
                "why": "沒有正典可以揭曉，受測者也沒有作答 —— "
                       "這一欄什麼都沒驗到，**不算一致**"}
    if not has_canonical:
        return {"result": CANONICAL_MISSING,
                "why": "受測者答了，但這個系統沒有正典可以對。"
                       "答案對不對這裡判不出來，不要當成對也不要當成錯"}
    if not a:
        return {"result": DIFFERENT, "same": False, "only_canonical": list(b),
                "only_mine": [],
                "why": "有正典，受測者沒答。這是差異，要分類"}
    if a == b:
        return {"result": SAME, "same": True, "only_mine": [], "only_canonical": []}
    return {"result": DIFFERENT, "same": False,
            "only_mine": [x for x in a if x not in b],
            "only_canonical": [x for x in b if x not in a],
            "why": "兩邊不一樣。**為什麼不一樣這裡算不出來**，第 6 步要人分類"}


def reveal(root: Path = REPO, *, derivation_id: str,
           snap: dict | None = None, work: dict | None = None,
           at: float | None = None) -> dict:
    """第 5 步：揭曉正典並比對。**沒交卷不准揭曉。**

    這一條拒絕就是整個 §39 的重點。允許先看再推導的話，前面四步
    做得再完整都只是流程表演。
    """
    log = Log(root)
    op = log.latest(derivation_id, "OPEN")
    if op is None:
        return {"ok": False, "why": f"找不到這份推導：{derivation_id}"}
    der = log.latest(derivation_id, "DERIVED")
    if der is None:
        return {"ok": False,
                "why": "還沒交推導，所以不揭曉（§39 第 4 步在第 5 步之前）。"
                       "先看答案再推導的話，這道門驗的是抄寫不是推導"}
    if log.latest(derivation_id, "REVEAL") is not None:
        return {"ok": False, "why": "這份已經揭曉過了，紀錄在帳本裡查得到"}

    can = canonical(snap, work, root)
    ans = der.get("answer") or {}
    diffs = []
    for k, _en, zh in FIELDS:
        c = compare_one(ans.get(k), can["fields"][k])
        diffs.append({"field": k, "zh": zh, **c})

    counts: dict[str, int] = {}
    for d in diffs:
        counts[d["result"]] = counts.get(d["result"], 0) + 1

    row = {
        "kind": "REVEAL", "id": derivation_id, "at": at or time.time(),
        "session": op.get("session", ""),
        "canonical_sha": can["sha"],
        "canonical_changed": can["sha"] != op.get("canonical_sha"),
        "diffs": diffs,
        "counts": counts,
        "needs_classification": [d["field"] for d in diffs
                                 if d["result"] == DIFFERENT],
        "verified_fields": [d["field"] for d in diffs if d["result"] == SAME],
        "nothing_verified": [d["field"] for d in diffs
                             if d["result"] in (NOT_COMPARABLE, CANONICAL_MISSING)],
    }
    Log(root).append(row)
    return {"ok": True, **row}


def classify(root: Path = REPO, *, derivation_id: str, field: str,
             kind: str, by: str, reason: str = "",
             at: float | None = None) -> dict:
    """第 6 步：把一個差異分成四類的其中一類。**只收人標的。**

    `by` 必填而且不准是空字串。四類沒有一類算得出來 ——
    同一個「不一樣」，四種解釋都成立，要選哪一種靠的是去查那個差異
    背後發生了什麼事。自動判一個出來是 §8.3 的填空捷徑。
    """
    log = Log(root)
    rev = log.latest(derivation_id, "REVEAL")
    if rev is None:
        return {"ok": False, "why": "還沒揭曉，沒有差異可以分類（§39 第 5 步在第 6 步之前）"}
    valid = {k for k, _en, _zh in CLASSES}
    if kind not in valid:
        return {"ok": False,
                "why": f"不是 §39 的四類之一：{kind}。四類是 " + "、".join(sorted(valid))}
    if not str(by or "").strip():
        return {"ok": False,
                "why": "`by` 必填。**這四類沒有一類算得出來**，"
                       "所以每一筆分類都要指得回是誰判的"}
    if field not in (rev.get("needs_classification") or []):
        return {"ok": False,
                "why": f"`{field}` 這一欄不需要分類。要分類的是："
                       + "、".join(rev.get("needs_classification") or ["（沒有）"])}
    row = {"kind": "CLASSIFY", "id": derivation_id, "at": at or time.time(),
           "session": rev.get("session", ""), "field": field,
           "class": kind, "by": str(by).strip(), "reason": str(reason or "")}
    log.append(row)
    return {"ok": True, **row}


def reconciliation(root: Path = REPO, *, derivation_id: str) -> dict:
    """第 7 步的前提：和解完成了沒有。

    完成的定義是**每一個 DIFFERENT 都被分類過**。
    沒有差異的時候也算完成，但回的東西會說「這一次驗到了幾欄」——
    四欄都 `NOT_COMPARABLE` 的一次和解在布林值上跟四欄都對一樣，
    而它們不是同一件事。
    """
    log = Log(root)
    rev = log.latest(derivation_id, "REVEAL")
    if rev is None:
        der = log.latest(derivation_id, "DERIVED")
        op = log.latest(derivation_id, "OPEN")
        if op is None:
            return {"ok": False, "reconciled": False,
                    "why": f"找不到這份推導：{derivation_id}"}
        stage = "已交推導，還沒揭曉" if der is not None else "已開卷，還沒交推導"
        return {"ok": True, "reconciled": False, "stage": stage,
                "unclassified": [], "verified_fields": [],
                "why": f"{stage}（§39 第 5 步還沒走）"}

    need = list(rev.get("needs_classification") or [])
    done = {r.get("field") for r in log.rows(derivation_id)
            if r.get("kind") == "CLASSIFY"}
    left = [f for f in need if f not in done]
    ver = list(rev.get("verified_fields") or [])
    none = list(rev.get("nothing_verified") or [])

    if left:
        why = "這幾欄的差異還沒分類：" + "、".join(left)
    elif need:
        why = f"{len(need)} 個差異都分類過了"
    elif ver:
        why = f"沒有差異要分類，{len(ver)} 欄比對一致"
    else:
        why = ("沒有差異要分類，**但一欄都沒有驗到** —— "
               + "、".join(none) + " 都沒有正典可以對。"
               "這一次和解在流程上完成，在證據上是空的")
    return {"ok": True, "reconciled": not left, "stage": "已揭曉",
            "unclassified": left, "classified": sorted(done),
            "verified_fields": ver, "nothing_verified": none,
            "canonical_changed": bool(rev.get("canonical_changed")),
            "why": why}


def state(root: Path = REPO, *, session: str) -> dict:
    """這條線走到 §39 的第幾步了。

    權限綁 session，跟 `sufficiency.state()` 同一個理由：
    §39 講的是 successor，換一條線就是換一個受測者。
    """
    ids = [r["id"] for r in Log(root).all()
           if r.get("kind") == "OPEN" and r.get("session") == str(session or "")]
    if not ids:
        return {"session": str(session or ""), "reconciled": False,
                "derivation": "", "enforced": enforced(root),
                "why": "這條線還沒走過反錨定接手（§39 第 3 步都還沒開始）"}
    did = ids[-1]
    rec = reconciliation(root, derivation_id=did)
    return {"session": str(session or ""), "derivation": did,
            "reconciled": bool(rec.get("reconciled")),
            "stage": rec.get("stage", ""),
            "unclassified": rec.get("unclassified", []),
            "verified_fields": rec.get("verified_fields", []),
            "nothing_verified": rec.get("nothing_verified", []),
            "enforced": enforced(root), "why": rec.get("why", "")}


def can_write(root: Path = REPO, *, session: str) -> bool:
    """§39 第 7 步那一個布林值。

    **沒開強制的時候一律回 True**，而 `state()` 照樣說實話。
    跟 `sufficiency.can_write` 同一個形狀，理由也一樣：
    一道預設就擋人的門，第一個被擋住的會是 owner 自己。
    """
    if not enforced(root):
        return True
    return bool(state(root, session=session).get("reconciled"))
