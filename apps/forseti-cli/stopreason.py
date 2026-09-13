#!/usr/bin/env python3
"""停止理由分類法。F06 §4。

規格來源：`F06-EXC-001`（2026-09-09，sha256 前 12 `e2c0dfb0f965`）§3 與 §4。
逐字：

    After any non-terminal report: authorized deterministic next action
    → continue; real blocker → name it; owner decision → NEEDS_HUMAN;
    otherwise stopping is EXECUTION_CONTINUITY_VIOLATION.

    WAITING_EXTERNAL, BLOCKED_VERIFIED, NEEDS_HUMAN_DECISION, RETRY_BACKOFF,
    RESOURCE_LIMIT, POLICY_BOUNDARY, WORKER_FAILURE, UNKNOWN_STOP.
    "Turn ended" and "I explained it" are invalid stop reasons.

────────────────────────────────────────────────────

## 為什麼這一個特別重要

`ledger.py` 的狀態機已經有 `NEEDS_HUMAN`，也就是「我在等人」這個狀態
存在。但一次停止如果沒有被歸類，它就只是「沒有下一筆事件」——
而那跟「我在等人」、「我卡住了」、「我做完了」在帳本裡長得一模一樣。

2026-09-11 這一場，owner 必須一句一句下指令，每一輪我做完就停。
那些停止如果被歸類，絕大多數會落在 `INVALID`：既沒有真的 blocker，
也不需要 owner 決定，下一步是確定的。

**分類法的作用不是記錄停止，是讓「不該停的停止」現形。**

## 這個模組不做的事

不判斷「該不該繼續」，那是呼叫端的決定。這裡只回答
「這一次停止，照 F06 §3 算不算合規」。

把判斷跟執行分開，理由跟 ADR-003 一樣：判斷可以被推翻、被重算、
被拿去做統計，而執行不行。

零依賴（ADR-009）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import continuity as _C  # noqa: E402

# 「清單從 continuity.py 來，這裡不再自己定義一套。」
#
# 2026-09-11 我在這個檔案裡重新定義了 STOP_REASONS 與一組無效理由，
# 而 `continuity.py` 早就有了，做得還更細（它的
# `INVALID_STOP_PATTERNS` 有四條，包含「等人說繼續不是停止理由」，
# 而我那版只有字面比對）。
#
# 原因是我當時只掃了 `ledger` 模組的常數就下結論「八種全缺」。
# **一個不完整的檢查，比不檢查更危險：它會給出一個看起來查過的答案。**
#
# 兩個模組現在的分工：
#
#   continuity.py   F06 §4 的清單與 §5 的公式。規格的直譯
#   stopreason.py   在那之上加「這一次停止合不合規」的情境判定
#                   （有沒有已授權的下一步、blocker 有沒有證據）
STOP_REASONS = _C.STOP_REASONS

REASON_MEANING = {
    "WAITING_EXTERNAL": "在等外面的東西：別的程序、別的服務、別人的回覆",
    "BLOCKED_VERIFIED": "真的卡住了，而且卡住這件事本身有證據",
    "NEEDS_HUMAN_DECISION": "需要 owner 做決定，不是需要 owner 催",
    "RETRY_BACKOFF": "重試之間的等待",
    "RESOURCE_LIMIT": "額度、空間、速率打到上限",
    "POLICY_BOUNDARY": "政策或安全邊界要求先確認",
    "WORKER_FAILURE": "worker 掛了",
    "UNKNOWN_STOP": "停了，但說不出屬於上面哪一種",
}
assert set(REASON_MEANING) == set(STOP_REASONS)

VERDICTS = ("VALID", "EXECUTION_CONTINUITY_VIOLATION", "INVALID_REASON")


class StopReasonError(Exception):
    """停止理由不合規格。拒絕而不是修正。"""


@dataclass(frozen=True)
class StopAssessment:
    """一次停止的判定。

    `why` 是必填：一個說不出理由的判定沒辦法被反駁，
    而不能被反駁的判定在這個專案裡等於沒有判定。
    """

    verdict: str
    reason: str
    why: str
    at: float = 0.0

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise StopReasonError(f"不是合法的 verdict：{self.verdict}")
        if not self.why.strip():
            raise StopReasonError("判定要說得出理由")

    @property
    def ok(self) -> bool:
        return self.verdict == "VALID"


def classify_stop(reason: str, *,
                  has_authorized_next_action: bool = False,
                  needs_owner_decision: bool = False,
                  blocker_evidence: str = "",
                  at: float = 0.0) -> StopAssessment:
    """照 F06 §3 判一次停止。

    三個放行條件，缺一就是 violation：

        真的有 blocker（而且 blocker 這件事有證據）
        需要 owner 決定
        沒有已授權的確定性下一步

    **注意第三條是反過來的。** 有下一步而且已授權，就不該停。
    這一條是 owner 2026-09-11 那一整晚的形狀：每一輪我都有確定的
    下一步（讀下一份規格、跑下一個檢查），而我停下來等她開口。
    """
    r = (reason or "").strip()
    if not r:
        return StopAssessment("INVALID_REASON", "UNKNOWN_STOP",
                              "沒有給停止理由。停止一定要說得出為什麼", at)

    # 交給 continuity.py 判。它會對規格點名的無效理由丟例外，
    # 而且錯誤訊息講得出踩到哪一條，不是只說「不合法」。
    try:
        _C.classify_stop(r, reason if reason else "")
    except _C.ContinuityViolation as e:
        return StopAssessment("INVALID_REASON", "UNKNOWN_STOP", str(e), at)

    if r == "BLOCKED_VERIFIED" and not blocker_evidence.strip():
        return StopAssessment(
            "EXECUTION_CONTINUITY_VIOLATION", r,
            "宣稱 BLOCKED_VERIFIED 但沒有給 blocker 的證據。"
            "「我覺得卡住了」跟「卡住這件事有證據」是兩回事", at)

    if r == "NEEDS_HUMAN_DECISION" and not needs_owner_decision:
        return StopAssessment(
            "EXECUTION_CONTINUITY_VIOLATION", r,
            "宣稱需要 owner 決定，但呼叫端說不需要。"
            "需要 owner「決定」跟需要 owner「催」是兩回事", at)

    if has_authorized_next_action and r not in (
            "POLICY_BOUNDARY", "RESOURCE_LIMIT", "WORKER_FAILURE"):
        return StopAssessment(
            "EXECUTION_CONTINUITY_VIOLATION", r,
            f"有已授權的確定性下一步，理由卻是 {r}。F06 §3："
            "authorized deterministic next action → continue", at)

    return StopAssessment("VALID", r, REASON_MEANING[r], at)


def burden(assessments: list[StopAssessment]) -> dict:
    """一批停止的統計。F06 §5 的 `HumanContinueBurden` 那一半。

    **違規率單獨列出來，不併進總數。** 一個停了 20 次而 18 次合規的
    session，跟一個停了 20 次而 18 次違規的 session，
    在「停了幾次」這個數字上一模一樣。
    """
    total = len(assessments)
    bad = [a for a in assessments if not a.ok]
    by_reason: dict[str, int] = {}
    for a in assessments:
        by_reason[a.reason] = by_reason.get(a.reason, 0) + 1
    return {
        "stops": total,
        "violations": len(bad),
        "violation_rate": round(len(bad) / total, 3) if total else 0.0,
        "by_reason": by_reason,
        "note": ("違規率單獨列，不併進總數。停很多次而每次都合規，"
                 "跟停很多次而每次都不該停，是兩件完全不同的事"),
    }
