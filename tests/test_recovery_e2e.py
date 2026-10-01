from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import recovery_e2e as E2E  # noqa: E402
import successor_contract as SC  # noqa: E402


VERIFIER = "independent-verifier"
SECRET = b"independent-verifier-secret"


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def signed_receipt(packet, *, secret=SECRET, caller="successor-session"):
    body = {
        "schema": SC.RECEIPT_SCHEMA,
        "packet_id": packet["packet_id"],
        "packet_digest": packet["packet_digest"],
        "truth_digest": packet["task_truth"]["truth_digest"],
        "caller_session_id": caller,
        "action": packet["task_truth"]["next_action"],
        "action_digest": digest(packet["task_truth"]["next_action"]),
        "verifier_id": VERIFIER,
        "evidence_ref": "fixture://first-action",
        "status": "VERIFIED",
    }
    body["receipt_id"] = "receipt-" + digest(body)[:16]
    body["signature"] = hmac.new(secret, canonical(body), hashlib.sha256).hexdigest()
    return body


def evidence_resolver(receipt):
    evidence = {
        "exists": True,
        "packet_id": receipt["packet_id"],
        "packet_digest": receipt["packet_digest"],
        "truth_digest": receipt["truth_digest"],
        "action_digest": receipt["action_digest"],
        "verifier_id": receipt["verifier_id"],
        "status": "VERIFIED",
    }
    return lambda ref: evidence if ref == receipt["evidence_ref"] else None


def run_fixture(tmp_path, *, receipt="valid", caller="successor-session"):
    inputs = E2E.fixture_inputs()
    signed = None
    if receipt == "valid":
        signed = signed_receipt(inputs["packet"])
    elif receipt == "forged":
        signed = signed_receipt(inputs["packet"], secret=b"attacker")
    return E2E.run(
        ledger_path=tmp_path / "truth.jsonl",
        source_session_id=inputs["source_session_id"],
        successor_session_id=inputs["successor_session_id"],
        caller_session_id=caller,
        truth=inputs["truth"], healthy_context=inputs["healthy_context"],
        first_action_receipt=signed,
        verifier_registry=SC.VerifierRegistry({VERIFIER: SECRET}),
        evidence_resolver=(evidence_resolver(signed) if signed else lambda ref: None))


def test_offline_e2e_preserves_truth_and_reverifies_first_action(tmp_path):
    result = run_fixture(tmp_path)
    assert result["ok"] is True
    assert result["claim_success"] is True
    assert result["state"] == "RESUMED"
    assert result["truth_preserved"] is True
    assert result["receipt_id"].startswith("receipt-")
    sessions = {item["event"]["session_id"] for item in result["events"]}
    assert sessions == {"source-session", "successor-session"}
    assert len(SC.TruthLedger(tmp_path / "truth.jsonl").rows()) == 4


def test_no_receipt_means_recovery_cannot_be_claimed(tmp_path):
    result = run_fixture(tmp_path, receipt=None)
    assert result["ok"] is False
    assert result["claim_success"] is False
    assert result["state"] == "TAKEOVER_GATE"
    assert result["mode"] == "READ_ONLY"
    assert result["reason"] == "MISSING_FIRST_ACTION_RECEIPT"


def test_forged_receipt_never_produces_success_claim(tmp_path):
    result = run_fixture(tmp_path, receipt="forged")
    assert result["ok"] is False
    assert result["claim_success"] is False
    assert result["reason"] == "UNTRUSTED_OR_INVALID_VERIFIER"


def test_wrong_runtime_caller_never_reaches_takeover(tmp_path):
    result = run_fixture(tmp_path, caller="other-session")
    assert result["ok"] is False
    assert result["claim_success"] is False
    assert result["state"] == "PACKET_REJECTED"
    assert result["reason"] == "SUCCESSOR_TARGET_MISMATCH"


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], text=True, capture_output=True,
        check=True).stdout.strip()


def commit(repo, name):
    (repo / "state.txt").write_text(name, encoding="utf-8")
    git(repo, "add", "state.txt")
    git(repo, "commit", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def test_ancestry_isolation_rejects_xray_parent_counterexample(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "verifier@example.invalid")
    git(repo, "config", "user.name", "Independent Verifier")
    baseline = commit(repo, "baseline")
    git(repo, "checkout", "-b", "xray")
    xray = commit(repo, "xray")
    bad = commit(repo, "bad-recovery-on-xray")
    git(repo, "checkout", "-b", "replacement", baseline)
    good = commit(repo, "good-recovery-on-baseline")

    assert E2E.verify_replacement_ancestry(
        repo=repo, candidate=good, baseline=baseline,
        forbidden_ancestor=xray) == {"ok": True, "parent": baseline}
    rejected = E2E.verify_replacement_ancestry(
        repo=repo, candidate=bad, baseline=baseline,
        forbidden_ancestor=xray)
    assert rejected["ok"] is False
    assert rejected["reason"] == "DIRECT_PARENT_MISMATCH"
