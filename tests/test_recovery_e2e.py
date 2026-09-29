from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import recovery_e2e as E2E  # noqa: E402
import successor_contract as SC  # noqa: E402


def test_offline_e2e_preserves_truth_and_reverifies_first_action(tmp_path):
    result = E2E.fixture(ledger_path=tmp_path / "truth.jsonl")
    assert result["ok"] is True
    assert result["claim_success"] is True
    assert result["state"] == "RESUMED"
    assert result["truth_preserved"] is True
    assert result["receipt_id"].startswith("receipt-")
    sessions = {item["event"]["session_id"] for item in result["events"]}
    assert sessions == {"source-session", "successor-session"}
    assert len(SC.TruthLedger(tmp_path / "truth.jsonl").rows()) == 4


def test_no_receipt_means_recovery_cannot_be_claimed(tmp_path):
    result = E2E.fixture(
        ledger_path=tmp_path / "truth.jsonl", with_receipt=False)
    assert result["ok"] is False
    assert result["claim_success"] is False
    assert result["state"] == "TAKEOVER_GATE"
    assert result["mode"] == "READ_ONLY"
    assert result["reason"] == "MISSING_FIRST_ACTION_RECEIPT"
    assert len(SC.TruthLedger(tmp_path / "truth.jsonl").rows()) == 3


def test_wrong_first_action_receipt_keeps_successor_read_only(tmp_path):
    truth = SC.task_truth(
        task_id="t", goal="G", current_task="T", next_action="safe action")
    context = [{"text": "healthy", "provenance": "p", "why": "goal"}]
    p = SC.build_packet(
        truth=truth, source_session_id="source", successor_session_id="next",
        healthy_context=context)
    receipt = SC.make_first_action_receipt(
        packet=p, action="unsafe action", verifier_id="v", evidence_ref="e")
    result = E2E.run(
        ledger_path=tmp_path / "truth.jsonl", source_session_id="source",
        successor_session_id="next", truth=truth, healthy_context=context,
        first_action_receipt=receipt)
    assert result["claim_success"] is False
    assert result["state"] == "TAKEOVER_GATE"
    assert result["reason"] == "FIRST_ACTION_MISMATCH"


def test_receipt_for_other_packet_is_rejected(tmp_path):
    truth = SC.task_truth(
        task_id="t", goal="G", current_task="T", next_action="safe action")
    context = [{"text": "healthy", "provenance": "p", "why": "goal"}]
    p = SC.build_packet(
        truth=truth, source_session_id="source", successor_session_id="other",
        healthy_context=context)
    receipt = SC.make_first_action_receipt(
        packet=p, action="safe action", verifier_id="v", evidence_ref="e")
    result = E2E.run(
        ledger_path=tmp_path / "truth.jsonl", source_session_id="source",
        successor_session_id="next", truth=truth, healthy_context=context,
        first_action_receipt=receipt)
    assert result["claim_success"] is False
    assert result["reason"] == "RECEIPT_PACKET_MISMATCH"


def test_tampered_receipt_is_rejected(tmp_path):
    truth = SC.task_truth(
        task_id="t", goal="G", current_task="T", next_action="safe action")
    context = [{"text": "healthy", "provenance": "p", "why": "goal"}]
    p = SC.build_packet(
        truth=truth, source_session_id="source", successor_session_id="next",
        healthy_context=context)
    receipt = SC.make_first_action_receipt(
        packet=p, action="safe action", verifier_id="v", evidence_ref="e")
    receipt = copy.deepcopy(receipt)
    receipt["evidence_ref"] = "tampered"
    result = E2E.run(
        ledger_path=tmp_path / "truth.jsonl", source_session_id="source",
        successor_session_id="next", truth=truth, healthy_context=context,
        first_action_receipt=receipt)
    assert result["claim_success"] is False
    assert result["reason"] == "RECEIPT_DIGEST_MISMATCH"
