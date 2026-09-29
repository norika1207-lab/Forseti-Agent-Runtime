from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import goal_scope as G  # noqa: E402
import northstar as N  # noqa: E402


ANCHOR = {
    "scope_contract_ref": "owner:contract:7",
    "owner_provenance_ref": "event:owner:7",
    "accepted_scope": ["forseti.goal"],
    "rejected_scope": ["production.deploy"],
}


def action(scope: str, *, action_id: str = "a1") -> dict:
    return {"action_id": action_id, "scope_refs": [scope],
            "evidence_refs": [f"tool:{action_id}"]}


def gac(value: float, **overrides) -> dict:
    record = {
        "status": G.GAC_VALID,
        "value": value,
        "anchor_ref": "north-star:v2",
        "provenance_refs": ["event:owner:7"],
    }
    record.update(overrides)
    return record


def test_scope_match_requires_owner_contract_and_never_reads_free_text():
    result = G.scope_match(
        [{"action_id": "a1", "text": "please deploy production"}],
        {"accepted_scope": ["forseti.goal"]},
    )
    assert result["status"] == G.UNKNOWN
    assert result["value"] is None


def test_exact_owner_scope_and_evidence_can_match():
    result = G.scope_match([action("forseti.goal")], ANCHOR)
    assert result["status"] == G.SCOPE_MATCH
    assert result["value"] == 1.0
    assert result["evidence_refs"] == ["tool:a1"]


def test_rejected_action_is_covered_by_anchor_but_out_of_scope_for_action():
    anchor_result = G.scope_match([action("production.deploy")], ANCHOR)
    action_result = G.action_scope_verdict(
        [action("production.deploy")], ANCHOR)
    assert anchor_result["status"] == G.SCOPE_MATCH
    assert anchor_result["value"] == 1.0
    assert action_result["status"] == G.SCOPE_OUT
    assert action_result["value"] == 0.0


def test_unclassified_or_unsupported_action_fails_closed():
    unknown_scope = G.scope_match([action("some.new.scope")], ANCHOR)
    no_evidence = G.scope_match(
        [{"action_id": "a2", "scope_refs": ["forseti.goal"]}], ANCHOR)
    assert unknown_scope["status"] == G.UNKNOWN
    assert no_evidence["status"] == G.UNKNOWN


def test_conflicting_owner_scope_definition_is_unknown():
    anchor = dict(ANCHOR, accepted_scope=["same"], rejected_scope=["same"])
    result = G.scope_match([action("same")], anchor)
    assert result["status"] == G.UNKNOWN
    assert result["overlap"] == ["same"]


def test_owner_goal_change_excludes_old_goal_drift():
    exclusion = G.drift_exclusion(goal_change={
        "kind": G.OWNER_GOAL_CHANGE,
        "owner_confirmed": True,
        "from_version": 1,
        "to_version": 2,
        "evidence_refs": ["event:owner:change"],
    })
    assert exclusion["status"] == G.OWNER_GOAL_CHANGE
    assert exclusion["excludes_drift"] is True


def test_cross_session_chain_feeds_owner_change_exclusion_contract():
    chain = N.Chain()
    chain.adopt_from_session(
        "v1", authority="owner", why="start", session_id="session-a",
        event_id="event-1", owner_confirmed=True, at=1.0,
    )
    chain.adopt_from_session(
        "v2", authority="owner", why="changed", session_id="session-b",
        event_id="event-2", owner_confirmed=True, at=2.0,
    )
    exclusion = G.drift_exclusion(
        goal_change=chain.goal_change_exclusion(1, 2))
    assert exclusion["status"] == G.OWNER_GOAL_CHANGE
    assert exclusion["excludes_drift"] is True
    assert exclusion["evidence_refs"] == ["event-2"]


def test_unproven_goal_change_is_unknown_not_an_exclusion():
    exclusion = G.drift_exclusion(goal_change={
        "kind": G.OWNER_GOAL_CHANGE,
        "owner_confirmed": False,
        "from_version": 1,
        "to_version": 2,
    })
    assert exclusion["status"] == G.UNKNOWN
    assert exclusion["excludes_drift"] is None


def test_only_bounded_isolated_exploration_is_excluded():
    bounded = G.drift_exclusion(exploration={
        "branch": "EXPERIMENTAL",
        "isolated_canonical_state": True,
        "stop_condition": "after 3 fixtures",
        "return_condition": "report only",
        "evidence_refs": ["work-order:exp-1"],
    })
    unbounded = G.drift_exclusion(exploration={
        "branch": "EXPERIMENTAL",
        "isolated_canonical_state": True,
    })
    assert bounded["status"] == G.EXPLORATORY_BRANCH
    assert bounded["excludes_drift"] is True
    assert unbounded["status"] == G.UNKNOWN
    assert unbounded["excludes_drift"] is None


def test_missing_or_low_gac_can_never_confirm_drift():
    scope = G.action_scope_verdict([action("production.deploy")], ANCHOR)
    exclusion = G.drift_exclusion()
    candidates = (
        {"status": G.UNKNOWN, "value": None},
        gac(0.59),
        gac(0.79),
    )
    for candidate in candidates:
        result = G.confirmed_drift_gate(
            gac=candidate, scope=scope, exclusion=exclusion,
            confirmation={
                "gar": 1.0,
                "deterministic_or_owner_confirmed_contradiction": True,
                "persisted_after_correction_or_high_impact": True,
                "independent_evidence_dimensions": ["tool", "owner"],
            },
        )
        assert result["confirmed_drift"] is False
        assert result["eligible_for_confirmation"] is False


def test_passing_gac_alone_is_still_only_suspected():
    result = G.confirmed_drift_gate(
        gac=gac(0.95),
        scope=G.action_scope_verdict([action("production.deploy")], ANCHOR),
        exclusion=G.drift_exclusion(),
    )
    assert result["state"] == "SUSPECTED_DRIFT"
    assert result["confirmed_drift"] is False
    assert "gar_at_least_0.70" in result["missing"]


def test_complete_confirmation_contract_can_confirm():
    result = G.confirmed_drift_gate(
        gac=gac(0.95),
        scope=G.action_scope_verdict([action("production.deploy")], ANCHOR),
        exclusion=G.drift_exclusion(),
        confirmation={
            "gar": 0.80,
            "deterministic_or_owner_confirmed_contradiction": True,
            "persisted_after_correction_or_high_impact": True,
            "independent_evidence_dimensions": ["tool", "owner"],
        },
    )
    assert result["state"] == "CONFIRMED_DRIFT"
    assert result["confirmed_drift"] is True


def test_verifier_counterexample_inconsistent_records_fail_closed():
    valid_scope = G.action_scope_verdict(
        [action("production.deploy")], ANCHOR)
    confirmation = {
        "gar": 1.0,
        "deterministic_or_owner_confirmed_contradiction": True,
        "persisted_after_correction_or_high_impact": True,
        "independent_evidence_dimensions": ["tool", "owner"],
    }
    malformed = (
        # A scalar score has no status or provenance.
        {"gac": 0.95, "scope": valid_scope},
        # OUT_OF_SCOPE cannot carry MATCH's value.
        {"gac": gac(0.95),
         "scope": dict(valid_scope, status=G.SCOPE_OUT, value=1.0)},
        # A non-UNKNOWN status cannot carry a null value.
        {"gac": gac(0.95), "scope": dict(valid_scope, value=None)},
        # Provenance is required even when status/value look consistent.
        {"gac": gac(0.95),
         "scope": dict(valid_scope, owner_provenance_ref=None)},
    )
    for case in malformed:
        result = G.confirmed_drift_gate(
            gac=case["gac"], scope=case["scope"],
            exclusion=G.drift_exclusion(), confirmation=confirmation)
        assert result["confirmed_drift"] is False
        assert result["eligible_for_confirmation"] is False
