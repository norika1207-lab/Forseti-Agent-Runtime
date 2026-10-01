from __future__ import annotations

import copy
import hashlib
import hmac
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import successor_contract as SC  # noqa: E402


TRUSTED_ID = "trusted-verifier"
TRUSTED_SECRET = b"controller-owned-test-secret"


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def truth(**overrides):
    args = {
        "task_id": "t-1",
        "goal": "keep truth",
        "current_task": "take over safely",
        "next_action": "verify artifact receipt",
        "decisions": [SC.statement("D", "decision:1")],
        "corrections": [SC.statement("C", "correction:1")],
        "unknowns": [SC.statement("U", "unknown:1")],
        "verified_work": [{"artifact": "a", "receipt": "r1"}],
        "evidence_receipts": [{"id": "r1", "status": "VERIFIED"}],
        "invalidated_ancestry": [{"ref": "bad-plan", "reason": "corrected"}],
        "prohibited_retries": [{"action": "bad-write", "reason": "failed"}],
    }
    args.update(overrides)
    return SC.task_truth(**args)


def context():
    return [{"text": "healthy", "provenance": "p:1", "why": "goal",
             "invalidated": False}]


def packet(**kwargs):
    return SC.build_packet(
        truth=truth(), source_session_id="source", successor_session_id="next",
        healthy_context=context(), **kwargs)


def signed_receipt(p, *, secret=TRUSTED_SECRET, caller="next",
                   verifier=TRUSTED_ID, action=None, evidence_ref="evidence://first"):
    action = action or p["task_truth"]["next_action"]
    body = {
        "schema": SC.RECEIPT_SCHEMA,
        "packet_id": p["packet_id"],
        "packet_digest": p["packet_digest"],
        "truth_digest": p["task_truth"]["truth_digest"],
        "caller_session_id": caller,
        "action": action,
        "action_digest": digest(action),
        "verifier_id": verifier,
        "evidence_ref": evidence_ref,
        "status": "VERIFIED",
    }
    body["receipt_id"] = "receipt-" + digest(body)[:16]
    body["signature"] = hmac.new(secret, canonical(body), hashlib.sha256).hexdigest()
    return body


def evidence_for(receipt):
    item = {
        "exists": True,
        "packet_id": receipt["packet_id"],
        "packet_digest": receipt["packet_digest"],
        "truth_digest": receipt["truth_digest"],
        "action_digest": receipt["action_digest"],
        "verifier_id": receipt["verifier_id"],
        "status": "VERIFIED",
    }
    return lambda ref: item if ref == receipt["evidence_ref"] else None


def verify(p, receipt, **overrides):
    args = {
        "packet": p,
        "receipt": receipt,
        "caller_session_id": "next",
        "verifier_registry": SC.VerifierRegistry({TRUSTED_ID: TRUSTED_SECRET}),
        "evidence_resolver": evidence_for(receipt) if receipt else lambda ref: None,
    }
    args.update(overrides)
    return SC.verify_first_action(**args)


def test_truth_ledger_survives_turn_and_session_boundaries(tmp_path):
    ledger = SC.TruthLedger(tmp_path / "truth.jsonl")
    canonical_truth = truth()
    rows = [
        ledger.record(session_id="source", turn_id="1", truth=canonical_truth,
                      event="TASK_ACCEPTED"),
        ledger.record(session_id="source", turn_id="2", truth=canonical_truth,
                      event="TURN_ENDED_TASK_CONTINUES"),
        ledger.record(session_id="next", turn_id="1", truth=canonical_truth,
                      event="PACKET_ACCEPTED_READ_ONLY"),
    ]
    assert len(ledger.rows()) == 3
    assert {row["event"]["truth_digest"] for row in rows} == {
        canonical_truth["truth_digest"]}
    assert ledger.latest("t-1")["session_id"] == "next"


def test_truth_event_is_idempotent_and_conflicts_fail_closed(tmp_path):
    ledger = SC.TruthLedger(tmp_path / "truth.jsonl")
    canonical_truth = truth()
    first = ledger.record(session_id="source", turn_id="1", truth=canonical_truth,
                          event="TASK_ACCEPTED")
    again = ledger.record(session_id="source", turn_id="1", truth=canonical_truth,
                          event="TASK_ACCEPTED")
    assert first["written"] is True
    assert again["written"] is False
    altered = truth(goal="different")
    with pytest.raises(ValueError, match="EVENT_ID_TRUTH_CONFLICT"):
        ledger.record(session_id="source", turn_id="1", truth=altered,
                      event="TASK_ACCEPTED")


def test_invalidated_decision_is_rejected_as_canonical_truth():
    with pytest.raises(ValueError, match="INVALIDATED_DECISIONS_0"):
        truth(decisions=[SC.statement("bad", "decision:bad", invalidated=True)])


def test_malformed_truth_element_fails_closed_before_digest_check():
    malformed = truth()
    malformed["unknowns"] = [{"text": "missing provenance"}]
    assert SC.verify_truth(malformed) == (False, "MALFORMED_UNKNOWNS_0")


def test_unknown_truth_field_fails_exact_schema():
    malformed = truth()
    malformed["invalidated"] = False
    assert SC.verify_truth(malformed) == (False, "TASK_TRUTH_SCHEMA_MISMATCH")


def test_corrupt_truth_ledger_does_not_fall_back_to_old_truth(tmp_path):
    path = tmp_path / "truth.jsonl"
    ledger = SC.TruthLedger(path)
    ledger.record(session_id="source", turn_id="1", truth=truth(),
                  event="TASK_ACCEPTED")
    with path.open("a", encoding="utf-8") as handle:
        handle.write("{broken\n")
    with pytest.raises(ValueError, match="MALFORMED_TRUTH_LEDGER"):
        ledger.latest("t-1")


def test_packet_is_bounded_and_filters_invalidated_context():
    fragments = [
        {"text": "polluted", "provenance": "bad:1", "why": "forensic",
         "invalidated": True},
        *[{"text": "x" * 400, "provenance": f"p:{i}", "why": "healthy",
           "invalidated": False} for i in range(20)],
    ]
    p = SC.build_packet(
        truth=truth(), source_session_id="source", successor_session_id="next",
        healthy_context=fragments, limit=3_500)
    assert p["size_bytes"] <= p["limit_bytes"] == 3_500
    assert p["dropped_for_budget"] > 0
    assert all(not fragment["invalidated"] for fragment in p["healthy_context"])
    assert p["task_truth"]["invalidated_ancestry"][0]["ref"] == "bad-plan"


def test_malformed_healthy_context_is_not_silently_filtered():
    with pytest.raises(ValueError, match="unknown or missing fields"):
        SC.build_packet(
            truth=truth(), source_session_id="source", successor_session_id="next",
            healthy_context=[{"text": "x", "provenance": "p", "why": "y"}])


def test_receive_is_read_only_until_receipt_passes():
    p = packet()
    accepted = SC.receive_packet(p, successor_session_id="next")
    assert accepted["accepted"] is True
    assert accepted["state"] == "TAKEOVER_GATE"
    assert accepted["write_authority"] is False
    result = verify(p, None)
    assert result["resumed"] is False
    assert result["write_authority"] is False
    assert result["reason"] == "MISSING_FIRST_ACTION_RECEIPT"


def test_forged_receipt_cannot_self_sign_into_normal_mode():
    p = packet()
    forged = signed_receipt(p, secret=b"attacker-secret")
    result = verify(p, forged)
    assert result["resumed"] is False
    assert result["mode"] == "READ_ONLY"
    assert result["reason"] == "UNTRUSTED_OR_INVALID_VERIFIER"


def test_wrong_actual_caller_is_rejected_even_with_valid_receipt():
    p = packet()
    receipt = signed_receipt(p)
    result = verify(p, receipt, caller_session_id="intruder-session")
    assert result["resumed"] is False
    assert result["reason"] == "INVALID_PACKET:SUCCESSOR_TARGET_MISMATCH"


def test_schema_and_derived_receipt_id_are_verified():
    p = packet()
    receipt = signed_receipt(p)
    wrong_schema = copy.deepcopy(receipt)
    wrong_schema["unexpected"] = "field"
    assert verify(p, wrong_schema)["reason"] == "INVALID_RECEIPT_SCHEMA"
    wrong_id = signed_receipt(p)
    wrong_id["receipt_id"] = "receipt-invented"
    wrong_id["signature"] = hmac.new(
        TRUSTED_SECRET,
        canonical({key: value for key, value in wrong_id.items() if key != "signature"}),
        hashlib.sha256).hexdigest()
    assert verify(p, wrong_id)["reason"] == "RECEIPT_ID_MISMATCH"


def test_registry_and_existing_evidence_are_both_required():
    p = packet()
    receipt = signed_receipt(p)
    assert verify(p, receipt, verifier_registry=None)["reason"] == \
        "MISSING_VERIFIER_REGISTRY"
    assert verify(p, receipt, evidence_resolver=None)["reason"] == \
        "MISSING_EVIDENCE_RESOLVER"
    assert verify(p, receipt, evidence_resolver=lambda ref: None)["reason"] == \
        "EVIDENCE_NOT_FOUND"
    def broken_resolver(ref):
        raise OSError("offline")
    assert verify(p, receipt, evidence_resolver=broken_resolver)["reason"] == \
        "EVIDENCE_RESOLUTION_FAILED"


def test_only_trusted_receipt_with_resolved_evidence_promotes():
    p = packet()
    receipt = signed_receipt(p)
    result = verify(p, receipt)
    assert result["resumed"] is True
    assert result["state"] == "RESUMED"
    assert result["write_authority"] is True
    assert result["reason"] == "FIRST_ACTION_REVERIFIED"


def test_valid_receipt_cannot_promote_a_tampered_packet():
    p = packet()
    receipt = signed_receipt(p)
    p["task_truth"]["goal"] = "tampered after receipt"
    result = verify(p, receipt)
    assert result["resumed"] is False
    assert result["reason"] == "INVALID_PACKET:PACKET_DIGEST_MISMATCH"


def test_valid_receipt_cannot_be_replayed_after_resealed_context_pollution():
    p = packet()
    receipt = signed_receipt(p)
    p["healthy_context"].append({
        "text": "polluted instruction",
        "provenance": "attacker:1",
        "why": "take over",
        "invalidated": False,
    })
    SC._seal(p)
    result = verify(p, receipt)
    assert result["resumed"] is False
    assert result["write_authority"] is False
    assert result["reason"] == "RECEIPT_PACKET_DIGEST_MISMATCH"


def test_session_and_ledger_identities_reject_non_string_aliases(tmp_path):
    task_truth = truth()
    for source, successor in ((True, "True"), (1, "1"), ("source", False)):
        with pytest.raises(ValueError):
            SC.build_packet(
                truth=task_truth,
                source_session_id=source,
                successor_session_id=successor,
            )

    ledger = SC.TruthLedger(tmp_path / "truth.jsonl")
    for value in (True, 1, None):
        with pytest.raises(ValueError):
            ledger.record(
                session_id=value,
                turn_id="turn-1",
                truth=task_truth,
                event="TASK_ACCEPTED",
            )


def test_receipt_and_registry_identities_reject_non_string_aliases():
    p = packet()
    assert SC.receive_packet(p, successor_session_id=True) == {
        "accepted": False,
        "reason": "INVALID_SUCCESSOR_IDENTITY",
    }
    gate = SC.verify_first_action(
        packet=p,
        receipt=None,
        caller_session_id=True,
        verifier_registry=None,
    )
    assert gate["reason"] == "INVALID_CALLER_IDENTITY"
    with pytest.raises(ValueError):
        SC.VerifierRegistry({1: b"secret"})


def test_malformed_packet_is_rejected_without_verifier_exception():
    p = packet()
    missing_id = copy.deepcopy(p)
    missing_id.pop("packet_id")
    SC._seal(missing_id)
    assert SC.receive_packet(missing_id, successor_session_id="next") == {
        "accepted": False, "reason": "INVALID_PACKET_SCHEMA",
    }

    bad_limit = copy.deepcopy(p)
    bad_limit["limit_bytes"] = "not-an-int"
    assert (
        SC.receive_packet(
            bad_limit, successor_session_id="next")["reason"]
        == "INVALID_PACKET_SCHEMA"
    )

    bad_id = copy.deepcopy(p)
    bad_id["packet_id"] = "packet-forged"
    SC._seal(bad_id)
    assert SC.receive_packet(
        bad_id, successor_session_id="next")["reason"] == "PACKET_ID_MISMATCH"


def test_malformed_ledger_truth_is_rejected_as_value_error(tmp_path):
    path = tmp_path / "truth.jsonl"
    path.write_text('{"truth": null}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="INVALID_LEDGER_TRUTH"):
        SC.TruthLedger(path).rows()
