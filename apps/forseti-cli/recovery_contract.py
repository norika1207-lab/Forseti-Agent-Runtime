#!/usr/bin/env python3
"""R06 recovery decision boundary for workers and blank output.

Liveness, correctness, and output starvation remain separate observations.
The contract recommends the next safe action but never silently re-runs a
side-effecting worker.
"""
from __future__ import annotations

import hashlib


TERMINAL_TASK_STATES = {
    "VERIFIED_COMPLETE", "CANCELLED_BY_OWNER", "FAILED_TERMINAL", "SUPERSEDED",
}


def assess(*, step_id: str, worker_alive: bool | None, blank_run: int = 0,
           has_receipts: bool = False, has_final_output: bool = False,
           tool_calls: int = 0, progress_healthy: bool = False,
           foreground_running: bool = False) -> dict:
    import starvation
    output = starvation.diagnose(
        has_receipts=has_receipts, has_final_output=has_final_output,
        tool_calls=tool_calls, progress_healthy=progress_healthy,
        blank_run=blank_run, foreground_running=foreground_running)
    liveness = {"state": ("ALIVE" if worker_alive is True else
                           "DEAD_OR_UNKNOWN" if worker_alive is False else "UNKNOWN"),
                "basis": "OBSERVED" if worker_alive is not None else "UNKNOWN",
                "why": ("worker process 可觀測存在" if worker_alive is True else
                        "worker process 不可觀測，不能假設仍在執行" if worker_alive is False else
                        "此 transcript 沒有 process liveness receipt")}
    actions = starvation.recovery_plan(output)
    if worker_alive is False:
        actions = ["PRESERVE_RESULTS", "MARK_AVAILABILITY", "CHECKPOINT",
                   "RESTART_OR_REASSIGN"]
    return {"step_id": step_id, "liveness": liveness,
            "output": output.__dict__, "actions": actions,
            "auto_rerun": False,
            "why": "副作用 worker 不自動重跑；先保全 receipt/checkpoint，再由 controller 決定重派"}


def continuation_key(task_id: str, step_id: str, authorized_input: str) -> str:
    """Stable idempotency key for one authorized continuation packet."""
    raw = "\x1f".join((task_id, step_id, authorized_input)).encode("utf-8")
    return "continue-" + hashlib.sha256(raw).hexdigest()[:16]


def continue_decision(*, task_id: str, step_id: str, task_state: str,
                      authorized_input: str, command_running: bool,
                      activity_observed: bool, stall_suspect: bool,
                      has_receipts: bool, has_final_output: bool,
                      blank_run: int = 0) -> dict:
    """Decide whether the controller may re-send an existing work packet.

    This is deliberately a decision, not a transport.  The caller must write
    the returned `event_key` durably before handing `original_input` to a
    worker, so a repeated observation cannot create duplicate execution.
    """
    text = str(authorized_input or "").strip()
    output = assess(step_id=step_id, worker_alive=None, blank_run=blank_run,
                    has_receipts=has_receipts, has_final_output=has_final_output,
                    progress_healthy=activity_observed,
                    foreground_running=command_running)["output"]
    if command_running or activity_observed:
        return {"action": "WAIT_FOR_ACTIVITY", "output": output,
                "why": "命令或可觀測進度仍在，不能插入續作輸入"}
    if has_receipts and not has_final_output:
        return {"action": "SYNTHESIS_ONLY", "output": output,
                "why": "已有 ResultReceipt；只補結果綜述，不能重跑原工作"}
    if task_state in TERMINAL_TASK_STATES:
        return {"action": "NOOP_TERMINAL", "output": output,
                "why": f"task 已在終態 {task_state}"}
    if not stall_suspect:
        return {"action": "WAIT_FOR_LIVENESS", "output": output,
                "why": "尚無停滯證據，不能因為畫面暫時安靜就重送"}
    if not text:
        return {"action": "UNKNOWN", "output": output,
                "why": "沒有保存的原始授權輸入，不能自行改寫工作內容"}
    return {"action": "RESEND_ORIGINAL_INPUT", "output": output,
            "original_input": text,
            "event_key": continuation_key(task_id, step_id, text),
            "why": "任務非終態、已停滯且沒有活動；重送原始授權輸入"}
