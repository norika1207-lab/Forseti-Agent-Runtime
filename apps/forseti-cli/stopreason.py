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

from dataclasses import dataclass

# F06 §4 逐字，順序照原文。
STOP_REASONS = (
    "WAITING_EXTERNAL",
    "BLOCKED_VERIFIED",
    "NEEDS_HUMAN_DECISION",
    "RETRY_BACKOFF",
    "RESOURCE_LIMIT",
    "POLICY_BOUNDARY",
    "WORKER_FAILURE",
    "UNKNOWN_STOP",
)

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

# F06 §4 最後一句點名的兩個。
#
# 「Turn ended」與「I explained it」不是停止理由，它們是停止本身的描述。
# 拿描述當理由，等於沒有理由 —— 而那正是這一整份規格要擋的東西
# （§2 的 completion illusion：解釋完成了，執行義務就靜靜消失）。
INVALID_REASONS = ("turn ended", "i explained it", "turn_end",
                   "回合結束", "我解釋過了", "我講完了", "報告完了")

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

    low = r.lower()
    for bad in INVALID_REASONS:
        if bad in low:
            return StopAssessment(
                "INVALID_REASON", "UNKNOWN_STOP",
                f"「{r}」是停止本身的描述，不是理由（F06 §4 點名）", at)

    if r not in STOP_REASONS:
        return StopAssessment(
            "INVALID_REASON", "UNKNOWN_STOP",
            f"「{r}」不在 F06 §4 的八種裡。不在清單裡的一律不收，"
            "因為理由可以隨便取名等於沒有分類法", at)

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
