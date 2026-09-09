#!/usr/bin/env python3
"""執行連續性。實作 F06-EXC-001。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F06-EXC-001  sha256 e2c0dfb0f965

F06 §2 把失效機制寫得很精確：

    explanation completed → model turn feels complete
    → execution obligation silently disappears

解釋完成了，模型的一輪感覺完整，於是執行義務靜默消失。關鍵是
「感覺」跟「靜默」這兩個詞：沒有人決定要停，也沒有任何東西壞掉，
義務就是不見了，而且不見的那一刻沒有任何訊號。

這個模組做的事很小：把「停止」變成一個需要理由的動作，而且理由
必須來自一張固定的清單。清單之外的一律記成違規。

2026-09-09 這一場的實測數字是 HumanContinueBurden = 9。九次都是
同一個形狀：做完一件事、寫一份完整的報告、停下來，等使用者說繼續。
每一次我都覺得那一輪是完整的，因為報告確實完整。F06 §4 的判定是
「I explained it」不是合法的停止理由，我看到那句的時候正在做第九次。

零依賴。
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# F06 §4 的停止理由分類
# ---------------------------------------------------------------------------

STOP_REASONS = (
    "WAITING_EXTERNAL",       # 在等外部系統，等的對象要講得出來
    "BLOCKED_VERIFIED",       # 真的被擋住，而且擋住的事實驗證過
    "NEEDS_HUMAN_DECISION",   # 需要擁有者做一個只有他能做的決定
    "RETRY_BACKOFF",          # 退避中，會自己回來
    "RESOURCE_LIMIT",         # 資源上限
    "POLICY_BOUNDARY",        # 政策或安全邊界
    "WORKER_FAILURE",         # worker 失敗
    "UNKNOWN_STOP",           # 不知道為什麼停了。合法但它是一個告警
)

# 這些不是「不夠好的理由」，是規格明文說的無效理由。
# 分開列出來是為了讓錯誤訊息講得出你踩到哪一條，而不是只說「不合法」。
INVALID_STOP_PATTERNS = (
    (re.compile(r"turn\s*end|回合結束|這一輪結束", re.I),
     "「turn ended」不是停止理由（F06 §4）。對話的一輪結束不等於任務結束"),
    (re.compile(r"explain|解釋|說明完|報告完|講完", re.I),
     "「I explained it」不是停止理由（F06 §4）。解釋不是交付"),
    (re.compile(r"等(你|妳|使用者|owner)(說|下)?(繼續|指示|命令)|wait.*instruction", re.I),
     "等人說繼續不是停止理由。下一步已授權的話就該自己走（F01 §6）"),
    (re.compile(r"^(完成|做完|好了|done)[了。!！]*$", re.I),
     "「做完了」不是停止理由。完成要靠 verifier 判定，而且完成之後還有下一步"),
)


class ContinuityViolation(Exception):
    """停止的理由不合法。

    刻意用例外而不是回傳 False：停止是一個顯性的動作,用錯理由
    應該讓呼叫端當場知道,而不是回一個可以被忽略的值。
    F06 §3 說得很直接:otherwise stopping is EXECUTION_CONTINUITY_VIOLATION。
    """


def classify_stop(reason: str, detail: str = "") -> str:
    """檢查一個停止理由。合法回傳它自己，不合法丟例外。

    UNKNOWN_STOP 是合法的,因為「不知道為什麼停了」是一個誠實的答案,
    比硬掰一個理由好。但它本身就是一個告警,呼叫端應該把它當成
    需要調查的訊號而不是正常出口。
    """
    if reason in STOP_REASONS:
        return reason
    text = f"{reason} {detail}"
    for pat, why in INVALID_STOP_PATTERNS:
        if pat.search(text):
            raise ContinuityViolation(why)
    raise ContinuityViolation(
        f"不是 F06 §4 定義的停止理由：{reason!r}。"
        f"合法的是 {'/'.join(STOP_REASONS)}。"
        f"真的不知道為什麼停就用 UNKNOWN_STOP，那是誠實的，硬掰一個不是")


def requires_named_target(reason: str) -> bool:
    """這幾種理由必須講得出對象，不然它們跟「我先停一下」沒有差別。"""
    return reason in ("WAITING_EXTERNAL", "BLOCKED_VERIFIED", "NEEDS_HUMAN_DECISION")


# ---------------------------------------------------------------------------
# F06 §5 的兩個指標
# ---------------------------------------------------------------------------

def continuity_score(auto_continued: int, expected_continuation: int) -> float:
    """ExecutionContinuityScore = AutoContinued / max(ExpectedContinuation, 1)。

    分母用 max(x, 1) 是規格寫的。意思是沒有任何應該繼續的場合時,
    分數是 0/1 = 0 而不是除以零 —— 也就是「沒機會證明自己會繼續」
    不算滿分。這個選擇是對的:預設不信任比預設信任安全。
    """
    return round(auto_continued / max(expected_continuation, 1), 3)


def burden_verdict(burden: int) -> str:
    """HumanContinueBurden 的解讀。門檻是我定的，規格只說應趨近於零。"""
    if burden == 0:
        return "沒有人需要說繼續"
    if burden <= 2:
        return f"{burden} 次，還在可接受範圍"
    return f"{burden} 次，使用者被當成心跳器用了"
