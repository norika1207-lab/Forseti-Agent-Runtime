"""Regression tests for the canonical-goal drift boundary."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import goal_scope as G  # noqa: E402
import vitals as V  # noqa: E402


def ready_gate() -> dict:
    return {
        "ok": True,
        "gac": 0.95,
        "missing_factors": [],
        "factors": {"scope_match": {"status": G.SCOPE_MATCH, "value": 1.0}},
    }


def change(kind: str, **overrides) -> dict:
    value = {
        "kind": kind,
        "incompatible": False,
        "incompatible_dimensions": [],
        "evidence_refs": [],
    }
    value.update(overrides)
    return value


def rising_rows(contract: dict | None) -> list[dict]:
    return [{
        "n": i,
        "corrected_by_owner": False,
        "drift_contract": contract,
        "goal": {"distance": 0.20 + i * 0.05, "coverage": 0.8},
    } for i in range(8)]


def test_execution_evolution_is_not_drift():
    for kind in G.EXECUTION_EVOLUTION_KINDS:
        result = G.drift_contract(change(kind))
        assert result["state"] == G.EXECUTION_EVOLUTION
        assert result["drift"] is False


def test_canonical_incompatibility_is_the_only_drift_candidate():
    result = G.drift_contract(change(
        "OWNER_GOAL_CHANGE", incompatible=True,
        incompatible_dimensions=["goal_outcome"],
        evidence_refs=["owner:event:42"],
    ))
    assert result["state"] == G.DRIFT
    assert result["drift"] is True


def test_missing_incompatibility_evidence_fails_closed():
    for candidate in (
        change("OWNER_GOAL_CHANGE"),
        change("OWNER_GOAL_CHANGE", incompatible=True,
               incompatible_dimensions=["goal_outcome"]),
        change("OWNER_GOAL_CHANGE", incompatible=True,
               incompatible_dimensions=["implementation_detail"],
               evidence_refs=["event:1"]),
    ):
        result = G.drift_contract(candidate)
        assert result["state"] == G.INSUFFICIENT_EVIDENCE
        assert result["drift"] is False


def test_missing_gac_or_scope_produces_no_alert():
    status = V.drift_contract_status(
        rising_rows(change("OWNER_GOAL_CHANGE", incompatible=True,
                           incompatible_dimensions=["goal_outcome"],
                           evidence_refs=["event:1"])),
        None,
    )
    assert status["state"] == G.INSUFFICIENT_EVIDENCE
    assert "gac" in status["missing"]
    assert V.drift_alerts(rising_rows(change(
        "OWNER_GOAL_CHANGE", incompatible=True,
        incompatible_dimensions=["goal_outcome"], evidence_refs=["event:1"])),
        None) == []


def test_execution_evolution_does_not_create_alert():
    rows = rising_rows(change("BUG_FIX"))
    status = V.drift_contract_status(rows, ready_gate())
    assert status["state"] == G.EXECUTION_EVOLUTION
    assert V.drift_alerts(rows, ready_gate()) == []


def test_evidenced_canonical_drift_can_create_suspected_alert_only():
    rows = rising_rows(change(
        "SCOPE_BOUNDARY_CHANGE", incompatible=True,
        incompatible_dimensions=["scope_boundary"], evidence_refs=["event:2"],
    ))
    status = V.drift_contract_status(rows, ready_gate())
    assert status["state"] == "DRIFT_CANDIDATE"
    alerts = V.drift_alerts(rows, ready_gate())
    assert alerts
    assert alerts[-1]["state"] == "SUSPECTED_DRIFT"


def test_missing_drift_contract_does_not_create_correction_card():
    snap = {
        "rows": [{"goal": {"support": 0.2}}],
        "goal_trend": 0.1,
        "drift_contract": {"state": G.INSUFFICIENT_EVIDENCE},
        "dims": {},
        "temp": {},
    }
    assert not any(card["key"] == "goal" for card in V.cards(snap))
