#!/usr/bin/env python3
"""空輸出與結果保全。實作 F07-OUT-001。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F07-OUT-001  sha256 c721da66a062

這一份對應使用者 CLAUDE.md 裡那條最重的規則：「絕對不准吐空白」。
她的原文寫了根因：把回應文字綁在工具呼叫的同一則訊息，工具回顯掛掉，
整則就變空白。她付了 token 卻收到空白。

F07 §5 給的解法很小但很準：每個 tool-heavy 步驟在自然語言合成之前，
先落一份 durable ResultReceipt。這樣就算最後那句話沒送出去，工作成果
還在，恢復的時候只要重做合成，不用重跑昂貴的部分。

── §3 劃的界線，這個模組必須遵守 ──────────────────────

Forseti can observe tool calls, final-output absence, process/log/artifact
changes, result existence, foreground running state, and recurrence.
It cannot directly prove hidden reasoning was swallowed; root cause must
separate OBSERVED from INFERRED.

所以每一個診斷都帶 basis 欄位，標明它是看到的還是推論的。這不是
文件上的分類，是資料結構裡的欄位 —— 寫在註解裡的界線會被忽略，
寫在欄位裡的不會。

── 一處我沒看懂，照 CT 的線索實作並標明 ───────────────

§2 的 STALE_WATCHER 規格沒有定義。CT-F07-04 寫「ESC reveals
completion → STALE_WATCHER evidence」，我據此推測它指的是：工作其實
已經完成，但觀測端還顯示在跑，按 ESC 之後才看到完成。

所以我實作成「有 ResultReceipt 但沒有最終輸出，而且處於前景執行狀態」。
這是推測不是理解，已記在 REQUIRED_READING。

零依賴。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------------------
# F07 §2 的可觀測失效類別
# ---------------------------------------------------------------------------

FAILURE_CLASSES = (
    "OUTPUT_STARVATION",     # 有工具結果，沒有最終輸出
    "BLANK_OUTPUT_SEQUENCE", # 連續多次空輸出
    "STALE_WATCHER",         # 結果已在，觀測端還顯示在跑（見檔頭，這是推測）
    "PROCESS_STALL",         # 既沒有工具結果也沒有輸出
    "LONG_VALID_TASK",       # 久，但有健康的進度。這是「沒事」的類別
)

# 連續幾次空輸出算 sequence。這個數字是我定的，規格沒給。
BLANK_SEQUENCE_AT = 2

# 診斷的依據。§3 要求根因必須分開這兩者。
OBSERVED = "OBSERVED"
INFERRED = "INFERRED"


@dataclass
class ResultReceipt:
    """工作成果的收據。在自然語言合成之前就落地。

    這份東西的價值全在時序上:它必須早於合成。晚一步落地就等於沒有,
    因為吐白正是發生在合成那一刻。
    """

    step_id: str
    tool: str
    outcome: str                       # 工具本身的結果:成功、失敗、exit code
    at: float = field(default_factory=time.time)
    artifacts: list[str] = field(default_factory=list)
    raw_refs: list[str] = field(default_factory=list)
    digest: str = ""
    synthesized: bool = False          # 有沒有被轉成給人看的文字

    def __post_init__(self):
        if not self.digest:
            payload = json.dumps(
                {"step": self.step_id, "tool": self.tool, "outcome": self.outcome,
                 "artifacts": sorted(self.artifacts)}, ensure_ascii=False)
            self.digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Diagnosis:
    """一次診斷。basis 欄位是 §3 的界線在資料結構裡的形式。"""

    failure_class: str
    basis: str            # OBSERVED 或 INFERRED
    detail: str
    recoverable_without_rerun: bool = False
    recurrence: int = 1

    @property
    def is_healthy(self) -> bool:
        return self.failure_class == "LONG_VALID_TASK"


def diagnose(*, has_receipts: bool, has_final_output: bool,
             tool_calls: int, progress_healthy: bool,
             blank_run: int = 0, foreground_running: bool = False) -> Diagnosis:
    """從可觀測的事實分類。

    刻意不接受任何「模型說它怎麼了」的輸入。§3 說 Forseti 無法直接證明
    隱藏推理被吞掉,所以這裡只吃看得到的東西:有沒有收據、有沒有最終輸出、
    工具呼叫幾次、進度健不健康、連續空幾次、是不是前景執行中。
    """
    if blank_run >= BLANK_SEQUENCE_AT:
        return Diagnosis(
            "BLANK_OUTPUT_SEQUENCE", OBSERVED,
            f"連續 {blank_run} 次沒有最終輸出。重複本身就是證據，"
            f"單次可能是意外，連續不是",
            recoverable_without_rerun=has_receipts, recurrence=blank_run)

    if has_receipts and not has_final_output:
        if foreground_running:
            return Diagnosis(
                "STALE_WATCHER", INFERRED,
                "結果收據已存在但沒有最終輸出，而且還顯示在前景執行。"
                "推測是觀測端落後於實際狀態（見模組檔頭：這是推測不是理解）",
                recoverable_without_rerun=True)
        return Diagnosis(
            "OUTPUT_STARVATION", OBSERVED,
            "工具結果已經產出，最終輸出缺席。工作沒有白做，只是沒有被說出來",
            recoverable_without_rerun=True)

    if tool_calls == 0 and not has_final_output:
        return Diagnosis(
            "PROCESS_STALL", OBSERVED,
            "沒有工具呼叫也沒有輸出。沒有東西被做出來，所以沒有東西可以保全",
            recoverable_without_rerun=False)

    if progress_healthy:
        return Diagnosis(
            "LONG_VALID_TASK", OBSERVED,
            "有健康的進度。久不等於壞掉，這一類存在的目的就是不要誤判長工作")

    return Diagnosis(
        "PROCESS_STALL", INFERRED,
        "沒有明確的失效訊號，也沒有健康訊號。"
        "無法從可觀測的事實判定根因，不猜")


# ---------------------------------------------------------------------------
# F07 §4 的恢復
# ---------------------------------------------------------------------------

RECOVERY_STEPS = (
    "PRESERVE_RESULTS",     # 先保住已經產出的東西
    "MARK_AVAILABILITY",    # 標記哪些結果還在
    "SYNTHESIS_ONLY",       # 只重做合成
    "AVOID_RERUN",          # 不重跑昂貴的部分
    "CLEAN_RESPONSE_WORKER",# 合成一直失敗才換一個乾淨的來講
)


def recovery_plan(d: Diagnosis) -> list[str]:
    """依診斷給恢復步驟。

    §4 的順序有一個明確主張:重跑排在很後面。已經花掉的建置時間、
    已經呼叫過的 API,那些成本是真的,不該因為一句話沒說出來就再付一次。
    """
    if d.is_healthy:
        return []
    if not d.recoverable_without_rerun:
        return ["PRESERVE_RESULTS", "MARK_AVAILABILITY"]
    plan = ["PRESERVE_RESULTS", "MARK_AVAILABILITY", "SYNTHESIS_ONLY", "AVOID_RERUN"]
    if d.recurrence >= BLANK_SEQUENCE_AT:
        plan.append("CLEAN_RESPONSE_WORKER")
    return plan
