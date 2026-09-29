from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import successor_contract as SC  # noqa: E402


def truth():
    return SC.task_truth(
        task_id="t-1", goal="keep truth", current_task="take over safely",
        next_action="verify artifact receipt", decisions=["D"],
        corrections=["C"], unknowns=["U"],
        verified_work=[{"artifact": "a", "receipt": "r1"}],
        evidence_receipts=[{"id": "r1", "status": "VERIFIED"}],
        invalidated_ancestry=["bad-plan"], prohibited_retries=["bad-write"],
    )


def packet(**kwargs):
    return SC.build_packet(
        truth=truth(), source_session_id="source", successor_session_id="next",
        healthy_context=[{"text": "healthy", "provenance": "p:1", "why": "goal"}],
        **kwargs,
    )


def test_truth_ledger_survives_turn_and_session_boundaries(tmp_path):
    ledger = SC.TruthLedger(tmp_path / "truth.jsonl")
    canonical = truth()
    a = ledger.record(session_id="source", turn_id="1", truth=canonical,
                      event="TASK_ACCEPTED")
    b = ledger.record(session_id="source", turn_id="2", truth=canonical,
                      event="TURN_ENDED_TASK_CONTINUES")
    c = ledger.record(session_id="next", turn_id="1", truth=canonical,
                      event="PACKET_ACCEPTED_READ_ONLY")
    assert len(ledger.rows()) == 3
    assert {x["event"]["truth_digest"] for x in (a, b, c)} == {
        canonical["truth_digest"]}
    assert ledger.latest("t-1")["session_id"] == "next"


def test_truth_event_is_idempotent_and_conflicts_fail_closed(tmp_path):
    ledger = SC.TruthLedger(tmp_path / "truth.jsonl")
    canonical = truth()
    first = ledger.record(session_id="source", turn_id="1", truth=canonical,
                          event="TASK_ACCEPTED")
    again = ledger.record(session_id="source", turn_id="1", truth=canonical,
                          event="TASK_ACCEPTED")
    assert first["written"] is True
    assert again["written"] is False
    altered = SC.task_truth(
        task_id="t-1", goal="different", current_task="take over safely",
        next_action="verify artifact receipt")
    with pytest.raises(ValueError, match="EVENT_ID_TRUTH_CONFLICT"):
        ledger.record(session_id="source", turn_id="1", truth=altered,
                      event="TASK_ACCEPTED")


def test_packet_is_bounded_and_drops_invalidated_narrative():
    fragments = [
        {"text": "x" * 400, "provenance": f"p:{i}", "why": "healthy"}
        for i in range(20)
    ]
    fragments.insert(0, {"text": "polluted", "provenance": "bad:1",
                         "why": "forensic", "invalidated": True})
    p = SC.build_packet(
        truth=truth(), source_session_id="source", successor_session_id="next",
        healthy_context=fragments, limit=3_500)
    assert p["size_bytes"] <= p["limit_bytes"] == 3_500
    assert p["dropped_for_budget"] > 0
    assert all(not f.get("invalidated") for f in p["healthy_context"])
    assert p["task_truth"]["invalidated_ancestry"] == ["bad-plan"]
    assert p["task_truth"]["prohibited_retries"] == ["bad-write"]


def test_packet_tampering_and_wrong_successor_are_rejected():
    p = packet()
    assert SC.receive_packet(p, successor_session_id="wrong")["reason"] == \
        "SUCCESSOR_TARGET_MISMATCH"
    changed = copy.deepcopy(p)
    changed["task_truth"]["goal"] = "tampered"
    assert SC.receive_packet(changed, successor_session_id="next")["reason"] == \
        "PACKET_DIGEST_MISMATCH"


def test_receive_is_read_only_until_first_action_receipt_passes():
    p = packet()
    accepted = SC.receive_packet(p, successor_session_id="next")
    assert accepted["accepted"] is True
    assert accepted["state"] == "TAKEOVER_GATE"
    assert accepted["write_authority"] is False
    assert SC.verify_first_action(packet=p, receipt=None) == {
        "resumed": False, "state": "TAKEOVER_GATE", "mode": "READ_ONLY",
        "reason": "MISSING_FIRST_ACTION_RECEIPT",
    }


def test_only_exact_receipt_promotes_successor_to_resumed():
    p = packet()
    wrong = SC.make_first_action_receipt(
        packet=p, action="repeat failed strategy", verifier_id="v",
        evidence_ref="fixture://wrong")
    assert SC.verify_first_action(packet=p, receipt=wrong)["reason"] == \
        "FIRST_ACTION_MISMATCH"
    good = SC.make_first_action_receipt(
        packet=p, action=p["task_truth"]["next_action"], verifier_id="v",
        evidence_ref="fixture://ok")
    result = SC.verify_first_action(packet=p, receipt=good)
    assert result["resumed"] is True
    assert result["state"] == "RESUMED"
    assert result["reason"] == "FIRST_ACTION_REVERIFIED"


def test_valid_receipt_cannot_promote_a_tampered_packet():
    p = packet()
    receipt = SC.make_first_action_receipt(
        packet=p, action=p["task_truth"]["next_action"], verifier_id="v",
        evidence_ref="fixture://ok")
    p["task_truth"]["goal"] = "tampered after receipt"
    result = SC.verify_first_action(packet=p, receipt=receipt)
    assert result["resumed"] is False
    assert result["mode"] == "READ_ONLY"
    assert result["reason"] == "INVALID_PACKET:PACKET_DIGEST_MISMATCH"
