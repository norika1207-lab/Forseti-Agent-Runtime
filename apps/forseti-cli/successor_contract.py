#!/usr/bin/env python3
"""Offline successor takeover contract for P13 / Formal v2 section 28.5.

This module is deliberately transport-free. It does not open an App, address a
provider session, or perform an external effect. It gives an offline recovery
harness four fail-closed guarantees: canonical task truth lives outside either
session, successor packets are bounded and integrity-protected, the successor
is read-only until its first action is re-verified, and no matching evidence
receipt means no recovery-success claim.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "forseti.successor-contract.v1"
PACKET_LIMIT = 8_000
TERMINAL_TASK_STATES = {
    "VERIFIED_COMPLETE", "CANCELLED_BY_OWNER", "FAILED_TERMINAL", "SUPERSEDED",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def task_truth(*, task_id: str, goal: str, current_task: str,
               next_action: str, task_state: str = "RUNNING",
               decisions: list[str] | None = None,
               corrections: list[str] | None = None,
               unknowns: list[str] | None = None,
               verified_work: list[dict] | None = None,
               evidence_receipts: list[dict] | None = None,
               invalidated_ancestry: list[str] | None = None,
               prohibited_retries: list[str] | None = None) -> dict:
    """Create the canonical truth that must survive turn/session boundaries."""
    required = {
        "task_id": task_id, "goal": goal, "current_task": current_task,
        "next_action": next_action, "task_state": task_state,
    }
    missing = [name for name, value in required.items() if not str(value).strip()]
    if missing:
        raise ValueError("task truth missing: " + ", ".join(missing))
    if task_state in TERMINAL_TASK_STATES:
        raise ValueError("terminal task cannot be handed to a successor")
    truth = {
        "task_id": str(task_id),
        "goal": str(goal),
        "current_task": str(current_task),
        "next_action": str(next_action),
        "task_state": str(task_state),
        "decisions": list(decisions or []),
        "corrections": list(corrections or []),
        "unknowns": list(unknowns or []),
        "verified_work": list(verified_work or []),
        "evidence_receipts": list(evidence_receipts or []),
        "invalidated_ancestry": list(invalidated_ancestry or []),
        "prohibited_retries": list(prohibited_retries or []),
    }
    truth["truth_digest"] = _digest(truth)
    return truth


def verify_truth(truth: dict) -> tuple[bool, str]:
    if not isinstance(truth, dict):
        return False, "TASK_TRUTH_NOT_OBJECT"
    supplied = str(truth.get("truth_digest") or "")
    body = {key: value for key, value in truth.items() if key != "truth_digest"}
    required = ("task_id", "goal", "current_task", "next_action", "task_state")
    if any(not str(body.get(key) or "").strip() for key in required):
        return False, "TASK_TRUTH_INCOMPLETE"
    if body.get("task_state") in TERMINAL_TASK_STATES:
        return False, "TASK_ALREADY_TERMINAL"
    if supplied != _digest(body):
        return False, "TASK_TRUTH_DIGEST_MISMATCH"
    return True, "VERIFIED"


class TruthLedger:
    """Append-only, idempotent task-truth events for an offline E2E harness."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        for line in self.path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    def record(self, *, session_id: str, turn_id: str, truth: dict,
               event: str) -> dict:
        ok, reason = verify_truth(truth)
        if not ok:
            raise ValueError(reason)
        identity = {
            "schema": SCHEMA,
            "session_id": str(session_id),
            "turn_id": str(turn_id),
            "event": str(event),
            "task_id": truth["task_id"],
        }
        event_id = "truth-" + _digest(identity)[:16]
        existing = [row for row in self.rows() if row.get("event_id") == event_id]
        if existing:
            if existing[-1].get("truth_digest") != truth["truth_digest"]:
                raise ValueError("EVENT_ID_TRUTH_CONFLICT")
            return {"written": False, "event": existing[-1]}
        row = dict(identity, event_id=event_id,
                   truth_digest=truth["truth_digest"], truth=truth)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        return {"written": True, "event": row}

    def latest(self, task_id: str) -> dict | None:
        rows = [row for row in self.rows() if row.get("task_id") == task_id]
        return rows[-1] if rows else None


def _packet_body(packet: dict) -> dict:
    return {key: value for key, value in packet.items()
            if key not in {"packet_digest", "size_bytes"}}


def _seal(packet: dict) -> None:
    packet["packet_digest"] = _digest(_packet_body(packet))
    # size_bytes is itself part of the serialized packet. Iterate to the tiny
    # fixed point where the recorded value equals the complete packet length.
    size = int(packet.get("size_bytes") or 0)
    for _ in range(8):
        packet["size_bytes"] = size
        actual = len(_canonical(packet))
        if actual == size:
            return
        size = actual
    raise ValueError("PACKET_SIZE_DID_NOT_STABILIZE")


def build_packet(*, truth: dict, source_session_id: str,
                 successor_session_id: str, healthy_context: list[dict] | None = None,
                 limit: int = PACKET_LIMIT) -> dict:
    """Build a bounded capsule, dropping context but never its control skeleton."""
    ok, reason = verify_truth(truth)
    if not ok:
        raise ValueError(reason)
    if not source_session_id or not successor_session_id:
        raise ValueError("source and successor session ids are required")
    if source_session_id == successor_session_id:
        raise ValueError("successor must be a distinct session")
    if limit <= 0:
        raise ValueError("packet limit must be positive")

    packet = {
        "schema": SCHEMA,
        "source_session_id": str(source_session_id),
        "successor_session_id": str(successor_session_id),
        "task_truth": truth,
        "healthy_context": [],
        "dropped_for_budget": 0,
        "limit_bytes": int(limit),
        "takeover_state": "SUCCESSOR_ASSIGNED",
    }
    for fragment in list(healthy_context or []):
        if not isinstance(fragment, dict):
            raise ValueError("healthy context fragment must be an object")
        if not all(str(fragment.get(key) or "").strip()
                   for key in ("text", "provenance", "why")):
            raise ValueError("healthy context requires text, provenance, and why")
        if fragment.get("invalidated"):
            packet["dropped_for_budget"] += 1
            continue
        candidate = dict(packet)
        candidate["healthy_context"] = packet["healthy_context"] + [dict(fragment)]
        if len(_canonical(candidate)) > limit:
            packet["dropped_for_budget"] += 1
            continue
        packet["healthy_context"].append(dict(fragment))

    if len(_canonical(packet)) > limit:
        raise ValueError("PACKET_SKELETON_EXCEEDS_LIMIT")
    packet_id_seed = {
        "truth_digest": truth["truth_digest"],
        "source_session_id": source_session_id,
        "successor_session_id": successor_session_id,
    }
    packet["packet_id"] = "packet-" + _digest(packet_id_seed)[:16]
    _seal(packet)
    while packet["healthy_context"] and packet["size_bytes"] > limit:
        packet["healthy_context"].pop()
        packet["dropped_for_budget"] += 1
        _seal(packet)
    if packet["size_bytes"] > limit:
        raise ValueError("PACKET_SKELETON_EXCEEDS_LIMIT")
    return packet


def receive_packet(packet: dict, *, successor_session_id: str) -> dict:
    """Validate a capsule and hold the successor at the takeover gate."""
    if not isinstance(packet, dict) or packet.get("schema") != SCHEMA:
        return {"accepted": False, "reason": "UNKNOWN_PACKET_SCHEMA"}
    if packet.get("successor_session_id") != successor_session_id:
        return {"accepted": False, "reason": "SUCCESSOR_TARGET_MISMATCH"}
    if packet.get("packet_digest") != _digest(_packet_body(packet)):
        return {"accepted": False, "reason": "PACKET_DIGEST_MISMATCH"}
    actual_size = len(_canonical(packet))
    if actual_size > int(packet.get("limit_bytes") or 0):
        return {"accepted": False, "reason": "PACKET_OVER_BUDGET"}
    if packet.get("size_bytes") != actual_size:
        return {"accepted": False, "reason": "PACKET_SIZE_MISMATCH"}
    ok, reason = verify_truth(packet.get("task_truth") or {})
    if not ok:
        return {"accepted": False, "reason": reason}
    return {
        "accepted": True,
        "state": "TAKEOVER_GATE",
        "mode": "READ_ONLY",
        "write_authority": False,
        "packet_id": packet["packet_id"],
        "truth_digest": packet["task_truth"]["truth_digest"],
        "required_first_action": packet["task_truth"]["next_action"],
    }


def make_first_action_receipt(*, packet: dict, action: str, verifier_id: str,
                              evidence_ref: str, status: str = "VERIFIED") -> dict:
    """Make deterministic fixture evidence; this function performs no action."""
    body = {
        "schema": "forseti.first-action-receipt.v1",
        "packet_id": packet.get("packet_id"),
        "truth_digest": (packet.get("task_truth") or {}).get("truth_digest"),
        "action": str(action),
        "action_digest": _digest(str(action)),
        "verifier_id": str(verifier_id),
        "evidence_ref": str(evidence_ref),
        "status": str(status),
    }
    body["receipt_id"] = "receipt-" + _digest(body)[:16]
    body["receipt_digest"] = _digest(body)
    return body


def verify_first_action(*, packet: dict, receipt: dict | None) -> dict:
    """Promote to RESUMED only when the exact first action has valid evidence."""
    packet_check = receive_packet(
        packet, successor_session_id=str(packet.get("successor_session_id") or ""))
    if not packet_check.get("accepted"):
        return {"resumed": False, "state": "TAKEOVER_GATE",
                "mode": "READ_ONLY",
                "reason": "INVALID_PACKET:" + packet_check["reason"]}
    if not receipt:
        return {"resumed": False, "state": "TAKEOVER_GATE",
                "mode": "READ_ONLY", "reason": "MISSING_FIRST_ACTION_RECEIPT"}
    supplied = str(receipt.get("receipt_digest") or "")
    body = {key: value for key, value in receipt.items() if key != "receipt_digest"}
    if supplied != _digest(body):
        return {"resumed": False, "state": "TAKEOVER_GATE",
                "mode": "READ_ONLY", "reason": "RECEIPT_DIGEST_MISMATCH"}
    required = ("receipt_id", "packet_id", "truth_digest", "action",
                "action_digest", "verifier_id", "evidence_ref", "status")
    if any(not str(receipt.get(key) or "").strip() for key in required):
        return {"resumed": False, "state": "TAKEOVER_GATE",
                "mode": "READ_ONLY", "reason": "INCOMPLETE_FIRST_ACTION_RECEIPT"}
    truth = packet.get("task_truth") or {}
    checks = (
        (receipt["packet_id"] == packet.get("packet_id"), "RECEIPT_PACKET_MISMATCH"),
        (receipt["truth_digest"] == truth.get("truth_digest"), "RECEIPT_TRUTH_MISMATCH"),
        (receipt["action"] == truth.get("next_action"), "FIRST_ACTION_MISMATCH"),
        (receipt["action_digest"] == _digest(receipt["action"]), "ACTION_DIGEST_MISMATCH"),
        (receipt["status"] == "VERIFIED", "FIRST_ACTION_NOT_VERIFIED"),
    )
    for passed, reason in checks:
        if not passed:
            return {"resumed": False, "state": "TAKEOVER_GATE",
                    "mode": "READ_ONLY", "reason": reason}
    return {
        "resumed": True,
        "state": "RESUMED",
        "mode": "NORMAL",
        "write_authority": True,
        "receipt_id": receipt["receipt_id"],
        "reason": "FIRST_ACTION_REVERIFIED",
    }
