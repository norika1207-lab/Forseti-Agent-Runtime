from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import authority as A  # noqa: E402
import authority_map as AM  # noqa: E402


def test_map_reuses_normative_trust_hierarchy_without_reordering():
    result = AM.project([])
    assert [row["principal"] for row in result["trust_levels"]] == [
        name for name, _, _ in A.TRUST
    ]
    assert result["trust_levels"][0]["principal"] == "OWNER"
    assert result["trust_levels"][-1]["principal"] == "UNSUPPORTED"


def test_explicit_owner_allow_is_visible_and_reliable():
    result = AM.project([{
        "id": "approval-1",
        "type": "POLICY_ALLOW",
        "principal": "owner",
        "resource": "release:candidate-7",
        "action": "launch",
    }])
    approval = result["approvals"][0]
    assert approval["principal"] == "OWNER"
    assert approval["declared_state"] == "APPROVED"
    assert approval["effective_state"] == "APPROVED"
    assert approval["can_rely_on"] is True
    assert result["fail_closed"] is False


def test_unknown_principal_allow_fails_closed():
    result = AM.project([{
        "id": "approval-unknown",
        "type": "POLICY_ALLOW",
        "principal": "friendly-bot",
        "resource": "production",
    }])
    approval = result["approvals"][0]
    assert approval["principal"] == "UNSUPPORTED"
    assert approval["principal_raw"] == "friendly-bot"
    assert approval["effective_state"] == "BLOCKED_UNKNOWN_AUTHORITY"
    assert approval["can_rely_on"] is False
    assert result["fail_closed"] is True


def test_regression_literal_unsupported_principal_cannot_approve():
    result = AM.project([{
        "id": "counterexample-unsupported",
        "type": "POLICY_ALLOW",
        "principal": "UNSUPPORTED",
        "resource": "release:production",
    }])
    approval = result["approvals"][0]
    assert approval["principal"] == "UNSUPPORTED"
    assert approval["principal_known"] is False
    assert approval["effective_state"] == "BLOCKED_UNKNOWN_AUTHORITY"
    assert approval["can_rely_on"] is False
    assert result["fail_closed"] is True


def test_missing_principal_fails_closed_instead_of_guessing_from_text():
    result = AM.project([{
        "id": "approval-text",
        "type": "POLICY_ALLOW",
        "resource": "production",
        "text": "the owner approved this",
    }])
    assert result["approvals"][0]["effective_state"] == "BLOCKED_UNKNOWN_AUTHORITY"
    assert result["claims"] == []


def test_missing_resource_fails_closed():
    result = AM.project([{
        "id": "approval-no-resource",
        "type": "POLICY_ALLOW",
        "principal": "OWNER",
    }])
    assert result["approvals"][0]["effective_state"] == "BLOCKED_UNKNOWN_RESOURCE"
    assert result["approvals"][0]["can_rely_on"] is False


def test_structured_subject_is_accepted_as_resource_but_prose_is_not_parsed():
    result = AM.project([{
        "norm": {
            "id": "barrier-1",
            "type": "WRITE_BARRIER",
            "subject": "canonical:north-star",
            "metadata": {"principal": "CANONICAL_STATE"},
        }
    }])
    approval = result["approvals"][0]
    assert approval["resource"] == "canonical:north-star"
    assert approval["effective_state"] == "BLOCKED"
    assert set(approval["basis_fields"]) == {"metadata.principal", "subject"}


def test_conflict_winner_comes_from_authority_hierarchy_not_event_order():
    result = AM.project([], claims=[
        {"id": "c1", "resource": "goal", "principal": "AGENT_INFERENCE"},
        {"id": "c2", "resource": "goal", "principal": "CANONICAL_STATE"},
    ])
    assert result["has_conflict"] is True
    assert result["conflicts"][0]["winner"] == "CANONICAL_STATE"
    assert result["conflicts"][0]["losers"] == ["AGENT_INFERENCE"]
    assert result["conflicts"][0]["source_event_ids"] == ["c1", "c2"]


def test_same_principal_repeated_is_not_a_conflict():
    result = AM.project([], claims=[
        {"id": "c1", "resource": "goal", "principal": "OWNER"},
        {"id": "c2", "resource": "goal", "principal": "owner"},
    ])
    assert result["conflicts"] == []


def test_approval_requested_does_not_become_approval():
    result = AM.project([{
        "id": "request-1",
        "type": "APPROVAL_REQUESTED",
        "principal": "AGENT_INFERENCE",
        "resource": "deploy:prod",
    }])
    approval = result["approvals"][0]
    assert approval["declared_state"] == "REQUESTED"
    assert approval["effective_state"] == "REQUESTED"
    assert approval["can_rely_on"] is False


def test_non_governance_event_does_not_create_authority_claim():
    result = AM.project([{
        "id": "model-1",
        "type": "MODEL_OUTPUT",
        "principal": "OWNER",
        "resource": "goal",
        "text": "approved",
    }])
    assert result["approvals"] == []
    assert result["claims"] == []


def test_malformed_claim_is_retained_as_fail_closed_evidence():
    result = AM.project([], claims=[{"id": "bad", "principal": "OWNER"}])
    assert result["fail_closed"] is True
    assert result["unknown_sources"][0]["source_event_id"] == "bad"


def test_unknown_principal_in_external_claim_fails_closed():
    result = AM.project([], claims=[{
        "id": "claim-unknown", "resource": "goal", "principal": "mystery-agent"
    }])
    assert result["claims"][0]["principal"] == "UNSUPPORTED"
    assert result["fail_closed"] is True
    assert result["unknown_sources"][0]["state"] == "BLOCKED_UNKNOWN_AUTHORITY"


def test_projection_is_deterministic_for_same_input():
    events = [{
        "id": "approval-1", "type": "POLICY_ALLOW",
        "principal": "OWNER", "resource": "candidate",
    }]
    assert AM.build_authority_map(events) == AM.build_authority_map(events)
