#!/usr/bin/env python3
"""Deterministic offline recovery/continuity E2E harness.

The harness models turns and two provider-session identities but never starts or
drives a real provider session. Its output is a contract receipt, not a claim
that native or live recovery has been exercised.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

import successor_contract as SC


def run(*, ledger_path: Path, source_session_id: str,
        successor_session_id: str, truth: dict, healthy_context: list[dict],
        first_action_receipt: dict | None, caller_session_id: str,
        verifier_registry: SC.VerifierRegistry | None, evidence_resolver=None,
        packet_limit: int = SC.PACKET_LIMIT) -> dict:
    ledger = SC.TruthLedger(ledger_path)
    evidence: list[dict] = []

    evidence.append(ledger.record(
        session_id=source_session_id, turn_id="source-turn-1",
        truth=truth, event="TASK_ACCEPTED"))
    evidence.append(ledger.record(
        session_id=source_session_id, turn_id="source-turn-2",
        truth=truth, event="TURN_ENDED_TASK_CONTINUES"))

    packet = SC.build_packet(
        truth=truth, source_session_id=source_session_id,
        successor_session_id=successor_session_id,
        healthy_context=healthy_context, limit=packet_limit)
    accepted = SC.receive_packet(packet, successor_session_id=caller_session_id)
    if not accepted.get("accepted"):
        return {
            "ok": False, "claim_success": False, "state": "PACKET_REJECTED",
            "reason": accepted["reason"], "packet": packet, "events": evidence,
        }

    evidence.append(ledger.record(
        session_id=caller_session_id, turn_id="successor-turn-1",
        truth=truth, event="PACKET_ACCEPTED_READ_ONLY"))
    gate = SC.verify_first_action(
        packet=packet, receipt=first_action_receipt,
        caller_session_id=caller_session_id,
        verifier_registry=verifier_registry,
        evidence_resolver=evidence_resolver)
    if not gate.get("resumed"):
        return {
            "ok": False,
            "claim_success": False,
            "state": gate["state"],
            "mode": gate["mode"],
            "reason": gate["reason"],
            "packet": packet,
            "events": evidence,
            "truth_preserved": _truth_preserved(evidence, truth),
        }

    evidence.append(ledger.record(
        session_id=caller_session_id, turn_id="successor-turn-1",
        truth=truth, event="FIRST_ACTION_REVERIFIED"))
    return {
        "ok": True,
        "claim_success": True,
        "state": gate["state"],
        "mode": gate["mode"],
        "reason": gate["reason"],
        "packet": packet,
        "receipt_id": gate["receipt_id"],
        "events": evidence,
        "truth_preserved": _truth_preserved(evidence, truth),
    }


def _truth_preserved(events: list[dict], truth: dict) -> bool:
    digests = {
        event.get("event", {}).get("truth_digest")
        for event in events
        if event.get("event")
    }
    return digests == {truth.get("truth_digest")}


def fixture_inputs(*, packet_limit: int = SC.PACKET_LIMIT) -> dict:
    """Return deterministic unsigned inputs; an independent verifier must sign."""
    truth = SC.task_truth(
        task_id="task-recovery-001",
        goal="Preserve verified task truth across a successor takeover",
        current_task="Verify the first resumed action before normal mode",
        next_action="read receipt-bound artifact metadata",
        decisions=[SC.statement(
            "use canonical truth rather than the latest narrative", "fixture:decision:1")],
        corrections=[SC.statement(
            "do not call a packet alone a successful recovery", "fixture:correction:1")],
        unknowns=[SC.statement(
            "live provider delivery remains outside this harness", "fixture:unknown:1")],
        verified_work=[{"artifact": "artifact.bin", "receipt": "artifact-r1"}],
        evidence_receipts=[{"id": "artifact-r1", "status": "VERIFIED"}],
        invalidated_ancestry=[{"ref": "polluted-plan-v3", "reason": "owner correction"}],
        prohibited_retries=[{"action": "failed write strategy", "reason": "invalidated"}],
    )
    context = [
        {"text": "Owner-approved goal and current acceptance boundary.",
         "provenance": "fixture:healthy:1", "why": "active Goal",
         "invalidated": False},
        {"text": "Latest narrative says the failed strategy was successful.",
         "provenance": "fixture:polluted:2", "why": "forensic only",
         "invalidated": True},
    ]
    packet = SC.build_packet(
        truth=truth, source_session_id="source-session",
        successor_session_id="successor-session",
        healthy_context=context, limit=packet_limit)
    return {"truth": truth, "healthy_context": context, "packet": packet,
            "source_session_id": "source-session",
            "successor_session_id": "successor-session"}


def verify_replacement_ancestry(*, repo: Path, candidate: str, baseline: str,
                                forbidden_ancestor: str | None = None) -> dict:
    """Require the replacement's direct parent to be the shared baseline."""
    parent = subprocess.run(
        ["git", "-C", str(repo), "show", "-s", "--format=%P", candidate],
        text=True, capture_output=True)
    if parent.returncode != 0:
        return {"ok": False, "reason": "CANDIDATE_NOT_FOUND"}
    parents = parent.stdout.strip().split()
    if parents != [baseline]:
        return {"ok": False, "reason": "DIRECT_PARENT_MISMATCH",
                "parents": parents}
    if forbidden_ancestor:
        check = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor",
             forbidden_ancestor, candidate])
        if check.returncode == 0:
            return {"ok": False, "reason": "FORBIDDEN_ANCESTRY"}
        if check.returncode not in (0, 1):
            return {"ok": False, "reason": "ANCESTRY_CHECK_FAILED"}
    return {"ok": True, "parent": baseline}
