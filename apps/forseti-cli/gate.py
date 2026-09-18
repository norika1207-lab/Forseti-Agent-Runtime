#!/usr/bin/env python3
"""接手閘門。沒證明讀懂之前，高風險工作只准讀不准寫。v5.0 §17.3

    A successor may be read-only until it demonstrates understanding of
    the current objective, accepted decisions, unresolved unknowns,
    last-good state, and external-effect boundaries.

## 為什麼這一條可以硬擋，而「說了沒做」不行

`intervene.can_intervene` 的階梯裡，`BLOCK_HIGH_RISK` 要的是
「權限、授權或安全的硬前提不明或被推翻」。

**「接手的人沒有證明自己讀懂規格」正是硬前提不明。**
它跟「說了沒做」不同 —— 後者是行為問題，人有正當理由停下來;
前者是狀態問題，沒讀懂就動手，做出來的每一步都建立在可能錯的前提上。

2026-09-11 的 B-14 就是這樣發生的:一個 session 讀錯規格，
重做了已經完成的階段。2026-09-16 早上又發生一次同型事故，
16 小時斷線之後接手的 session 花了一個上午重讀昨晚已經讀完並記錄過的文件。

## 出題不是我出的

題目來自 `blockread.quiz()`，答案是原文裡的字。
`grade()` 比對的是原文的 key，**不做語意相似度** ——
差不多對在規格這種東西上就是錯。

這條很重要:一個 AI 自己出題自己改的閘門，等於沒有閘門。

## 通過會過期

文件改了就要重考。`content_hash` 對不上就作廢 ——
讀的是舊版而拿著舊版的通行證，比沒讀過更危險，
因為它看起來像已經讀過了。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "gate.jsonl"

#: 高風險工作動手之前一定要讀完的。少而精 ——
#: 清單太長會讓閘門變成儀式，而儀式會被繞過。
REQUIRED = (
    ".forseti/NORTH_STAR.md",
    ".forseti/NEXT.md",
    "bible.md",
)

#: 出幾題、要對幾題。**不是全對。**
#: 全對的門檻會讓一次抽到刁鑽題目的人卡死，而卡死的閘門會被拔掉。
ASK = 3
NEED = 2

#: 通行證有效期。超過就重考 —— 狀態會變，讀過不等於現在還知道。
TTL_HOURS = 12


def _hash(p: Path) -> str:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def required_files() -> list[dict]:
    """必讀清單與它們現在的指紋。檔案不在就標出來，不要靜默跳過。"""
    out = []
    for rel in REQUIRED:
        p = REPO / rel
        out.append({"path": rel, "exists": p.is_file(), "hash": _hash(p)})
    return out


def fingerprint() -> str:
    """必讀文件整體的指紋。任何一份改了，通行證就作廢。"""
    parts = [f"{f['path']}:{f['hash']}" for f in required_files()]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _load(path: Path | None = None) -> list[dict]:
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


def _append(row: dict, path: Path | None = None) -> None:
    p = path or LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def challenge(*, limit: int = ASK, path: Path | None = None) -> dict:
    """出題。題目來自原文，不是我編的。"""
    import blockread as BR

    qs: list[dict] = []
    for f in required_files():
        if not f["exists"] or len(qs) >= limit:
            continue
        p = REPO / f["path"]
        try:
            blocks = BR.split(p)
        except Exception:                                   # noqa: BLE001
            continue
        for b in blocks:
            if len(qs) >= limit:
                break
            for q in BR.quiz(p, b, limit=1):
                q["file"] = f["path"]
                qs.append(q)
                break
    if not qs:
        return {"ok": False, "why": "出不了題。必讀文件讀不到或抽不出可考的內容",
                "questions": []}
    return {
        "ok": True,
        "questions": [{"file": q["file"], "line": q["line"],
                       "kind": q["kind"], "q": q["q"], "_key": q["key"]}
                      for q in qs],
        "need": NEED,
        "of": len(qs),
        "fingerprint": fingerprint(),
        "note": "答案是原文裡的字。比對不做語意相似度 —— "
                "差不多對在規格這種東西上就是錯",
    }


def judge(questions: list, answers: list, *, session: str = "",
          path: Path | None = None) -> dict:
    """改考卷。對到 NEED 題就發通行證。"""
    import blockread as BR

    results = []
    right = 0
    for q, a in zip(questions, answers or []):
        r = BR.grade({"key": q.get("_key") or q.get("key"), "line": q.get("line"),
                      "kind": q.get("kind")}, a)
        results.append({"line": r["line"], "kind": r["kind"], "ok": r["ok"],
                        "expected_contains": r["key"]})
        right += 1 if r["ok"] else 0

    passed = right >= NEED
    row = {
        "at": time.time(),
        "session": session,
        "right": right,
        "of": len(questions),
        "need": NEED,
        "passed": passed,
        "fingerprint": fingerprint(),
    }
    _append(row, path)
    return {
        "passed": passed,
        "right": right,
        "of": len(questions),
        "need": NEED,
        "results": results,
        "why": ("通過，寫入權限開啟" if passed else
                f"只對 {right} 題，要 {NEED} 題。在那之前只准讀不准寫"),
    }


def status(session: str = "", *, path: Path | None = None,
           now: float | None = None) -> dict:
    """這條線現在是唯讀還是可寫。

    三種情況會回唯讀：從來沒考過、考過但沒通過、通過但文件改了或過期。
    """
    fp = fingerprint()
    t = now or time.time()
    rows = [r for r in _load(path)
            if (not session or r.get("session") == session) and r.get("passed")]
    if not rows:
        return {"writable": False, "reason": "NEVER_PASSED",
                "why": "這條線還沒通過接手閘門。§17.3：先唯讀，"
                       "證明讀懂了才拿到寫入權限",
                "fingerprint": fp}

    last = max(rows, key=lambda r: r.get("at", 0))
    if last.get("fingerprint") != fp:
        return {"writable": False, "reason": "DOCS_CHANGED",
                "why": "通過之後必讀文件改過了。拿著舊版的通行證比沒讀過更危險，"
                       "因為它看起來像已經讀過了",
                "passed_at": last.get("at"), "fingerprint": fp}

    age_h = (t - last.get("at", 0)) / 3600.0
    if age_h > TTL_HOURS:
        return {"writable": False, "reason": "EXPIRED",
                "why": f"通行證超過 {TTL_HOURS} 小時（已 {age_h:.1f} 小時）。"
                       "狀態會變，讀過不等於現在還知道",
                "passed_at": last.get("at"), "fingerprint": fp}

    return {"writable": True, "reason": "PASSED",
            "why": f"{age_h:.1f} 小時前通過，{last.get('right')}/{last.get('of')} 題",
            "passed_at": last.get("at"), "fingerprint": fp}
