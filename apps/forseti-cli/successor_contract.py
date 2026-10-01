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
import hmac
import json
from pathlib import Path
from typing import Any


SCHEMA = "forseti.successor-contract.v1"
PACKET_LIMIT = 8_000
TERMINAL_TASK_STATES = {
    "VERIFIED_COMPLETE", "CANCELLED_BY_OWNER", "FAILED_TERMINAL", "SUPERSEDED",
}
RECEIPT_SCHEMA = "forseti.first-action-receipt.v1"
RECEIPT_FIELDS = {
    "schema", "packet_id", "packet_digest", "truth_digest", "caller_session_id", "action",
    "action_digest", "verifier_id", "evidence_ref", "status", "receipt_id",
    "signature",
}
PACKET_FIELDS = {
    "schema", "source_session_id", "successor_session_id", "task_truth",
    "healthy_context", "dropped_for_budget", "limit_bytes", "takeover_state",
    "packet_id", "packet_digest", "size_bytes",
}
TRUTH_FIELDS = {
    "task_id", "goal", "current_task", "next_action", "task_state",
    "decisions", "corrections", "unknowns", "verified_work",
    "evidence_receipts", "invalidated_ancestry", "prohibited_retries",
}


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _strict_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _statement_list(name: str, value: Any) -> tuple[bool, str]:
    if not isinstance(value, list):
        return False, f"{name.upper()}_NOT_LIST"
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            return False, f"MALFORMED_{name.upper()}_{index}"
        if set(item) != {"text", "provenance", "invalidated"}:
            return False, f"MALFORMED_{name.upper()}_{index}"
        if not isinstance(item["invalidated"], bool):
            return False, f"MALFORMED_{name.upper()}_{index}"
        if item["invalidated"]:
            return False, f"INVALIDATED_{name.upper()}_{index}"
        if not _strict_text(item["text"]) or not _strict_text(item["provenance"]):
            return False, f"MALFORMED_{name.upper()}_{index}"
    return True, "VERIFIED"


def _object_list(name: str, value: Any, required: set[str]) -> tuple[bool, str]:
    if not isinstance(value, list):
        return False, f"{name.upper()}_NOT_LIST"
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != required:
            return False, f"MALFORMED_{name.upper()}_{index}"
        if any(not _strict_text(item[key]) for key in required):
            return False, f"MALFORMED_{name.upper()}_{index}"
    return True, "VERIFIED"


def _validate_truth_body(body: dict) -> tuple[bool, str]:
    if set(body) != TRUTH_FIELDS:
        return False, "TASK_TRUTH_SCHEMA_MISMATCH"
    required_scalars = ("task_id", "goal", "current_task", "next_action", "task_state")
    if any(not _strict_text(body.get(key)) for key in required_scalars):
        return False, "TASK_TRUTH_INCOMPLETE"
    if body.get("task_state") in TERMINAL_TASK_STATES:
        return False, "TASK_ALREADY_TERMINAL"
    for name in ("decisions", "corrections", "unknowns"):
        ok, reason = _statement_list(name, body.get(name))
        if not ok:
            return False, reason
    schemas = (
        ("verified_work", {"artifact", "receipt"}),
        ("evidence_receipts", {"id", "status"}),
        ("invalidated_ancestry", {"ref", "reason"}),
        ("prohibited_retries", {"action", "reason"}),
    )
    for name, fields in schemas:
        ok, reason = _object_list(name, body.get(name), fields)
        if not ok:
            return False, reason
    return True, "VERIFIED"


def statement(text: str, provenance: str, *, invalidated: bool = False) -> dict:
    """Construct one provenance-bearing canonical truth statement."""
    normalized_text = _strict_text(text)
    normalized_provenance = _strict_text(provenance)
    if not normalized_text or not normalized_provenance:
        raise ValueError("statement text and provenance must be non-empty strings")
    return {"text": normalized_text, "provenance": normalized_provenance,
            "invalidated": invalidated}


def task_truth(*, task_id: str, goal: str, current_task: str,
               next_action: str, task_state: str = "RUNNING",
               decisions: list[dict] | None = None,
               corrections: list[dict] | None = None,
               unknowns: list[dict] | None = None,
               verified_work: list[dict] | None = None,
               evidence_receipts: list[dict] | None = None,
               invalidated_ancestry: list[dict] | None = None,
               prohibited_retries: list[dict] | None = None) -> dict:
    """Create the canonical truth that must survive turn/session boundaries."""
    required = {
        "task_id": task_id, "goal": goal, "current_task": current_task,
        "next_action": next_action, "task_state": task_state,
    }
    missing = [name for name, value in required.items() if not _strict_text(value)]
    if missing:
        raise ValueError("task truth missing: " + ", ".join(missing))
    if task_state in TERMINAL_TASK_STATES:
        raise ValueError("terminal task cannot be handed to a successor")
    truth = {
        "task_id": task_id.strip(),
        "goal": goal.strip(),
        "current_task": current_task.strip(),
        "next_action": next_action.strip(),
        "task_state": task_state.strip(),
        "decisions": list(decisions or []),
        "corrections": list(corrections or []),
        "unknowns": list(unknowns or []),
        "verified_work": list(verified_work or []),
        "evidence_receipts": list(evidence_receipts or []),
        "invalidated_ancestry": list(invalidated_ancestry or []),
        "prohibited_retries": list(prohibited_retries or []),
    }
    ok, reason = _validate_truth_body(truth)
    if not ok:
        raise ValueError(reason)
    truth["truth_digest"] = _digest(truth)
    return truth


def verify_truth(truth: dict) -> tuple[bool, str]:
    if not isinstance(truth, dict):
        return False, "TASK_TRUTH_NOT_OBJECT"
    supplied = str(truth.get("truth_digest") or "")
    body = {key: value for key, value in truth.items() if key != "truth_digest"}
    ok, reason = _validate_truth_body(body)
    if not ok:
        return False, reason
    if supplied != _digest(body):
        return False, "TASK_TRUTH_DIGEST_MISMATCH"
    return True, "VERIFIED"


class VerifierRegistry:
    """Trust roots supplied by the controller, never by the successor packet."""

    def __init__(self, secrets: dict[str, bytes | str]):
        self._secrets = {}
        for verifier, secret in secrets.items():
            verifier_id = _strict_text(verifier)
            if not verifier_id or not isinstance(secret, (bytes, str)) or not secret:
                raise ValueError("verifier registry requires strict ids and secrets")
            self._secrets[verifier_id] = (
                secret.encode("utf-8") if isinstance(secret, str) else secret)

    def verify(self, receipt: dict) -> bool:
        verifier_id = _strict_text(receipt.get("verifier_id"))
        secret = self._secrets.get(verifier_id or "")
        if not secret:
            return False
        signed = {key: value for key, value in receipt.items() if key != "signature"}
        expected = hmac.new(secret, _canonical(signed), hashlib.sha256).hexdigest()
        return hmac.compare_digest(str(receipt.get("signature") or ""), expected)


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
            except ValueError as error:
                raise ValueError("MALFORMED_TRUTH_LEDGER") from error
            if not isinstance(row, dict):
                raise ValueError("MALFORMED_TRUTH_LEDGER")
            truth = row.get("truth")
            ok, reason = verify_truth(truth or {})
            if (not isinstance(truth, dict) or not ok
                    or row.get("truth_digest") != truth.get("truth_digest")):
                raise ValueError("INVALID_LEDGER_TRUTH:" + reason)
            out.append(row)
        return out

    def record(self, *, session_id: str, turn_id: str, truth: dict,
               event: str) -> dict:
        ok, reason = verify_truth(truth)
        if not ok:
            raise ValueError(reason)
        session_id = _strict_text(session_id)
        turn_id = _strict_text(turn_id)
        event = _strict_text(event)
        if not session_id or not turn_id or not event:
            raise ValueError("ledger identity fields must be non-empty strings")
        identity = {
            "schema": SCHEMA,
            "session_id": session_id,
            "turn_id": turn_id,
            "event": event,
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
    source_session_id = _strict_text(source_session_id)
    successor_session_id = _strict_text(successor_session_id)
    if not source_session_id or not successor_session_id:
        raise ValueError("source and successor session ids are required")
    if source_session_id == successor_session_id:
        raise ValueError("successor must be a distinct session")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("packet limit must be positive")

    packet = {
        "schema": SCHEMA,
        "source_session_id": source_session_id,
        "successor_session_id": successor_session_id,
        "task_truth": truth,
        "healthy_context": [],
        "dropped_for_budget": 0,
        "limit_bytes": int(limit),
        "takeover_state": "SUCCESSOR_ASSIGNED",
    }
    for fragment in list(healthy_context or []):
        if not isinstance(fragment, dict):
            raise ValueError("healthy context fragment must be an object")
        if set(fragment) != {"text", "provenance", "why", "invalidated"}:
            raise ValueError("healthy context has unknown or missing fields")
        if not isinstance(fragment["invalidated"], bool):
            raise ValueError("healthy context invalidated must be boolean")
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
    successor_session_id = _strict_text(successor_session_id)
    if not successor_session_id:
        return {"accepted": False, "reason": "INVALID_SUCCESSOR_IDENTITY"}
    if not isinstance(packet, dict) or packet.get("schema") != SCHEMA:
        return {"accepted": False, "reason": "UNKNOWN_PACKET_SCHEMA"}
    if set(packet) != PACKET_FIELDS:
        return {"accepted": False, "reason": "INVALID_PACKET_SCHEMA"}
    if packet.get("successor_session_id") != successor_session_id:
        return {"accepted": False, "reason": "SUCCESSOR_TARGET_MISMATCH"}
    source_session_id = _strict_text(packet.get("source_session_id"))
    if not source_session_id:
        return {"accepted": False, "reason": "INVALID_PACKET_SCHEMA"}
    if source_session_id == successor_session_id:
        return {"accepted": False, "reason": "INVALID_PACKET_SCHEMA"}
    if (not isinstance(packet.get("packet_id"), str)
            or not packet["packet_id"].strip()
            or not isinstance(packet.get("limit_bytes"), int)
            or isinstance(packet.get("limit_bytes"), bool)
            or packet["limit_bytes"] <= 0
            or not isinstance(packet.get("size_bytes"), int)
            or isinstance(packet.get("size_bytes"), bool)
            or not isinstance(packet.get("dropped_for_budget"), int)
            or isinstance(packet.get("dropped_for_budget"), bool)
            or packet["dropped_for_budget"] < 0
            or not isinstance(packet.get("healthy_context"), list)
            or packet.get("takeover_state") != "SUCCESSOR_ASSIGNED"):
        return {"accepted": False, "reason": "INVALID_PACKET_SCHEMA"}
    if packet.get("packet_digest") != _digest(_packet_body(packet)):
        return {"accepted": False, "reason": "PACKET_DIGEST_MISMATCH"}
    actual_size = len(_canonical(packet))
    if actual_size > packet["limit_bytes"]:
        return {"accepted": False, "reason": "PACKET_OVER_BUDGET"}
    if packet.get("size_bytes") != actual_size:
        return {"accepted": False, "reason": "PACKET_SIZE_MISMATCH"}
    ok, reason = verify_truth(packet.get("task_truth") or {})
    if not ok:
        return {"accepted": False, "reason": reason}
    expected_packet_id = "packet-" + _digest({
        "truth_digest": packet["task_truth"]["truth_digest"],
        "source_session_id": source_session_id,
        "successor_session_id": successor_session_id,
    })[:16]
    if packet["packet_id"] != expected_packet_id:
        return {"accepted": False, "reason": "PACKET_ID_MISMATCH"}
    return {
        "accepted": True,
        "state": "TAKEOVER_GATE",
        "mode": "READ_ONLY",
        "write_authority": False,
        "packet_id": packet["packet_id"],
        "truth_digest": packet["task_truth"]["truth_digest"],
        "required_first_action": packet["task_truth"]["next_action"],
    }


def _readonly(reason: str) -> dict:
    return {"resumed": False, "state": "TAKEOVER_GATE",
            "mode": "READ_ONLY", "write_authority": False, "reason": reason}


def _receipt_core(receipt: dict) -> dict:
    return {key: value for key, value in receipt.items()
            if key not in {"receipt_id", "signature"}}


def verify_first_action(*, packet: dict, receipt: dict | None,
                        caller_session_id: str,
                        verifier_registry: VerifierRegistry | None,
                        evidence_resolver=None) -> dict:
    """Promote to RESUMED only when the exact first action has valid evidence."""
    caller_session_id = _strict_text(caller_session_id)
    if not caller_session_id:
        return _readonly("INVALID_CALLER_IDENTITY")
    packet_check = receive_packet(packet, successor_session_id=caller_session_id)
    if not packet_check.get("accepted"):
        return _readonly("INVALID_PACKET:" + packet_check["reason"])
    if not receipt:
        return _readonly("MISSING_FIRST_ACTION_RECEIPT")
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        return _readonly("INVALID_RECEIPT_SCHEMA")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        return _readonly("INVALID_RECEIPT_SCHEMA")
    if any(not _strict_text(receipt.get(key)) for key in RECEIPT_FIELDS):
        return _readonly("INCOMPLETE_FIRST_ACTION_RECEIPT")
    expected_id = "receipt-" + _digest(_receipt_core(receipt))[:16]
    if receipt["receipt_id"] != expected_id:
        return _readonly("RECEIPT_ID_MISMATCH")
    if verifier_registry is None:
        return _readonly("MISSING_VERIFIER_REGISTRY")
    if not verifier_registry.verify(receipt):
        return _readonly("UNTRUSTED_OR_INVALID_VERIFIER")
    if evidence_resolver is None:
        return _readonly("MISSING_EVIDENCE_RESOLVER")
    truth = packet.get("task_truth") or {}
    checks = (
        (receipt["packet_id"] == packet.get("packet_id"), "RECEIPT_PACKET_MISMATCH"),
        (receipt["packet_digest"] == packet.get("packet_digest"),
         "RECEIPT_PACKET_DIGEST_MISMATCH"),
        (receipt["truth_digest"] == truth.get("truth_digest"), "RECEIPT_TRUTH_MISMATCH"),
        (receipt["caller_session_id"] == caller_session_id, "RECEIPT_CALLER_MISMATCH"),
        (receipt["action"] == truth.get("next_action"), "FIRST_ACTION_MISMATCH"),
        (receipt["action_digest"] == _digest(receipt["action"]), "ACTION_DIGEST_MISMATCH"),
        (receipt["status"] == "VERIFIED", "FIRST_ACTION_NOT_VERIFIED"),
    )
    for passed, reason in checks:
        if not passed:
            return _readonly(reason)
    try:
        evidence = evidence_resolver(receipt["evidence_ref"])
    except Exception:  # resolver is outside this trust boundary
        return _readonly("EVIDENCE_RESOLUTION_FAILED")
    if not isinstance(evidence, dict) or evidence.get("exists") is not True:
        return _readonly("EVIDENCE_NOT_FOUND")
    evidence_checks = (
        (evidence.get("packet_id") == packet.get("packet_id"), "EVIDENCE_PACKET_MISMATCH"),
        (evidence.get("packet_digest") == packet.get("packet_digest"),
         "EVIDENCE_PACKET_DIGEST_MISMATCH"),
        (evidence.get("truth_digest") == truth.get("truth_digest"), "EVIDENCE_TRUTH_MISMATCH"),
        (evidence.get("action_digest") == receipt["action_digest"], "EVIDENCE_ACTION_MISMATCH"),
        (evidence.get("verifier_id") == receipt["verifier_id"], "EVIDENCE_VERIFIER_MISMATCH"),
        (evidence.get("status") == "VERIFIED", "EVIDENCE_NOT_VERIFIED"),
    )
    for passed, reason in evidence_checks:
        if not passed:
            return _readonly(reason)
    return {
        "resumed": True,
        "state": "RESUMED",
        "mode": "NORMAL",
        "write_authority": True,
        "receipt_id": receipt["receipt_id"],
        "reason": "FIRST_ACTION_REVERIFIED",
    }
