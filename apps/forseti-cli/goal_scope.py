#!/usr/bin/env python3
"""Fail-closed Goal scope and Drift eligibility contracts.

The formal spec defines ``scope_match`` as a GAC factor, but does not define a
semantic classifier for free-form text.  This module therefore accepts only
owner-declared scope identifiers and independently evidenced action scope
identifiers.  Missing definitions remain UNKNOWN; they never become an
invented score.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import isfinite
from typing import Any


SCOPE_MATCH = "MATCH"
SCOPE_OUT = "OUT_OF_SCOPE"
UNKNOWN = "UNKNOWN"
GAC_VALID = "VALID"

NO_EXCLUSION = "NO_EXCLUSION"
OWNER_GOAL_CHANGE = "OWNER_GOAL_CHANGE"
EXPLORATORY_BRANCH = "EXPLORATORY_BRANCH"

GAC_SUSPECTED_MIN = 0.60
GAC_CONFIRMED_MIN = 0.80
GAR_CONFIRMED_MIN = 0.70


def _strings(values: Any) -> tuple[str, ...]:
    """Return deterministic, non-empty exact identifiers without guessing."""
    if not isinstance(values, (list, tuple, set, frozenset)):
        return ()
    return tuple(sorted({value.strip() for value in values
                         if isinstance(value, str) and value.strip()}))


def _unknown(why: str, **details: Any) -> dict[str, Any]:
    return {"status": UNKNOWN, "value": None, "why": why, **details}


def _strict_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _scope_observations(actions: Iterable[Mapping[str, Any]] | None,
                        anchor: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize one shared evidence set without deciding GAC or drift."""
    anchor = anchor or {}
    contract_ref = _strict_text(anchor.get("scope_contract_ref"))
    owner_ref = _strict_text(anchor.get("owner_provenance_ref"))
    accepted = _strings(anchor.get("accepted_scope"))
    rejected = _strings(anchor.get("rejected_scope"))

    base = {
        "contract_ref": contract_ref,
        "owner_provenance_ref": owner_ref,
        "accepted_scope": list(accepted),
        "rejected_scope": list(rejected),
    }
    if not contract_ref or not owner_ref:
        return {"ok": False,
                "error": "scope contract 缺 contract 或 owner provenance", **base}
    if not accepted and not rejected:
        return {"ok": False,
                "error": "owner 尚未定義 accepted_scope / rejected_scope", **base}

    overlap = sorted(set(accepted) & set(rejected))
    if overlap:
        return {"ok": False, "error": "同一 scope 同時被接受與拒絕",
                "overlap": overlap, **base}

    rows = list(actions or [])
    if not rows:
        return {"ok": False, "error": "沒有可判定的 action", **base}

    accepted_hits: set[str] = set()
    rejected_hits: set[str] = set()
    unresolved: list[str] = []
    evidence_refs: set[str] = set()
    for index, action in enumerate(rows):
        if not isinstance(action, Mapping):
            unresolved.append(f"action:{index}")
            continue
        raw_action_id = action.get("action_id")
        action_id = (_strict_text(raw_action_id) or f"action:{index}")
        scopes = _strings(action.get("scope_refs"))
        evidence = _strings(action.get("evidence_refs"))
        if not scopes or not evidence:
            unresolved.append(action_id)
            continue
        evidence_refs.update(evidence)
        accepted_hits.update(set(scopes) & set(accepted))
        rejected_hits.update(set(scopes) & set(rejected))
        if any(scope not in accepted and scope not in rejected for scope in scopes):
            unresolved.append(action_id)

    return {
        "ok": True,
        **base,
        "accepted_hits": sorted(accepted_hits),
        "rejected_hits": sorted(rejected_hits),
        "unresolved_action_ids": sorted(set(unresolved)),
        "evidence_refs": sorted(evidence_refs),
    }


def scope_match(actions: Iterable[Mapping[str, Any]] | None,
                anchor: Mapping[str, Any] | None) -> dict[str, Any]:
    """Evaluate whether the Goal Anchor contract covers the action scope.

    ``anchor`` must identify both its contract and owner provenance.  Every
    action must identify its normalized ``scope_refs`` and independent
    ``evidence_refs``.  Objective text, filenames and keyword mentions are not
    classified here because the owner has not defined such a classifier.

    This is the GAC ``scopeMatch`` factor.  A known rejected action is still
    covered by the anchor contract, so it returns 1.0 here.  Whether that
    action violates the Goal is decided separately by
    :func:`action_scope_verdict`.
    """
    observed = _scope_observations(actions, anchor)
    if not observed.get("ok"):
        return _unknown(observed.pop("error"), **observed)
    if observed["unresolved_action_ids"]:
        return _unknown("至少一個 action 缺 scope/evidence 或不在 anchor contract",
                        **observed)
    if observed["accepted_hits"] or observed["rejected_hits"]:
        return {"status": SCOPE_MATCH, "value": 1.0,
                "why": "所有 action scope 均由 anchor contract 明確涵蓋",
                **observed}
    return _unknown("沒有 action 命中 anchor contract", **observed)


def action_scope_verdict(actions: Iterable[Mapping[str, Any]] | None,
                         anchor: Mapping[str, Any] | None) -> dict[str, Any]:
    """Decide action alignment without changing anchor confidence."""
    observed = _scope_observations(actions, anchor)
    if not observed.get("ok"):
        return _unknown(observed.pop("error"), **observed)
    if observed["rejected_hits"]:
        return {"status": SCOPE_OUT, "value": 0.0,
                "why": "action 命中 owner 明示的 rejected_scope", **observed}
    if observed["unresolved_action_ids"]:
        return _unknown("至少一個 action 缺 scope/evidence 或 scope 未由 owner 定義",
                        **observed)
    if observed["accepted_hits"]:
        return {"status": SCOPE_MATCH, "value": 1.0,
                "why": "所有 action 均命中 owner 明示的 accepted_scope",
                **observed}
    return _unknown("沒有 action 命中 owner 定義的 scope", **observed)


def drift_exclusion(*, goal_change: Mapping[str, Any] | None = None,
                    exploration: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Check FS-GOL-002/003 exclusions without inferring owner intent."""
    change = goal_change or {}
    if change:
        refs = _strings(change.get("evidence_refs"))
        from_version = change.get("from_version")
        to_version = change.get("to_version")
        complete = (
            change.get("kind") == OWNER_GOAL_CHANGE
            and change.get("owner_confirmed") is True
            and type(from_version) is int and from_version > 0
            and type(to_version) is int and to_version > from_version
            and bool(refs)
        )
        if complete:
            return {"status": OWNER_GOAL_CHANGE, "excludes_drift": True,
                    "evidence_refs": list(refs),
                    "why": "owner-confirmed goal supersession 排除舊目標 drift"}
        return {"status": UNKNOWN, "excludes_drift": None,
                "evidence_refs": list(refs),
                "why": "goal change 資料不足，不能猜是不是 owner goal change"}

    branch = exploration or {}
    if branch:
        refs = _strings(branch.get("evidence_refs"))
        marked = branch.get("branch") == "EXPERIMENTAL"
        complete = (
            marked
            and branch.get("isolated_canonical_state") is True
            and _strict_text(branch.get("stop_condition")) is not None
            and _strict_text(branch.get("return_condition")) is not None
            and bool(refs)
        )
        if complete:
            return {"status": EXPLORATORY_BRANCH, "excludes_drift": True,
                    "evidence_refs": list(refs),
                    "why": "有界且隔離 canonical state 的探索排除 drift"}
        if marked:
            return {"status": UNKNOWN, "excludes_drift": None,
                    "evidence_refs": list(refs),
                    "why": "探索缺 isolation、stop/return condition 或 evidence"}

    return {"status": NO_EXCLUSION, "excludes_drift": False,
            "evidence_refs": [], "why": "未提供可適用的 exclusion"}


def _score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if isfinite(value) and 0.0 <= value <= 1.0 else None


def _gac_record(gac: Any) -> tuple[float | None, list[str]]:
    """Validate GAC status/value/provenance as one inseparable contract."""
    if not isinstance(gac, Mapping):
        return None, ["gac_contract"]
    status = gac.get("status")
    value = gac.get("value")
    anchor_ref = _strict_text(gac.get("anchor_ref"))
    provenance = _strings(gac.get("provenance_refs"))
    if status == UNKNOWN and value is None:
        return None, ["valid_gac"]
    score = _score(value)
    if status != GAC_VALID or score is None or not anchor_ref or not provenance:
        return None, ["gac_contract"]
    return score, []


def _scope_record(scope: Any) -> tuple[str, list[str]]:
    if not isinstance(scope, Mapping):
        return UNKNOWN, ["scope_contract"]
    status = scope.get("status")
    value = scope.get("value")
    contract_ref = _strict_text(scope.get("contract_ref"))
    owner_ref = _strict_text(scope.get("owner_provenance_ref"))
    evidence = _strings(scope.get("evidence_refs"))
    if status == UNKNOWN and value is None:
        return UNKNOWN, ["scope_match"]
    expected = {SCOPE_MATCH: 1.0, SCOPE_OUT: 0.0}.get(status)
    if (expected is None or _score(value) != expected or not contract_ref
            or not owner_ref or not evidence):
        return UNKNOWN, ["scope_contract"]
    return status, []


def _exclusion_record(exclusion: Any) -> tuple[str, bool | None, list[str]]:
    if not isinstance(exclusion, Mapping):
        return UNKNOWN, None, ["exclusion_contract"]
    status = exclusion.get("status")
    excluded = exclusion.get("excludes_drift")
    refs = _strings(exclusion.get("evidence_refs"))
    if status == UNKNOWN and excluded is None:
        return UNKNOWN, None, ["exclusion_resolution"]
    if status == NO_EXCLUSION and excluded is False and not refs:
        return status, False, []
    if (status in (OWNER_GOAL_CHANGE, EXPLORATORY_BRANCH)
            and excluded is True and refs):
        return status, True, []
    return UNKNOWN, None, ["exclusion_contract"]


def confirmed_drift_gate(*, gac: Mapping[str, Any], scope: Mapping[str, Any],
                         exclusion: Mapping[str, Any],
                         confirmation: Mapping[str, Any] | None = None
                         ) -> dict[str, Any]:
    """Apply the complete §6.2 confirmation gate.

    Passing GAC and scope only makes a case eligible for the remaining checks;
    it does not itself produce CONFIRMED_DRIFT.
    """
    missing: list[str] = []
    gac_value, gac_missing = _gac_record(gac)
    scope_state, scope_missing = _scope_record(scope)
    exclusion_state, excluded, exclusion_missing = _exclusion_record(exclusion)
    missing.extend(gac_missing + scope_missing + exclusion_missing)

    if excluded is True:
        return {"state": exclusion_state, "confirmed_drift": False,
                "eligible_for_confirmation": False, "missing": [],
                "why": "FS-GOL exclusion applies"}
    if gac_value is None:
        if not gac_missing:
            missing.append("valid_gac")
    elif gac_value < GAC_CONFIRMED_MIN:
        missing.append("gac_at_least_0.80")
    if scope_state not in (UNKNOWN, SCOPE_OUT):
        missing.append("goal_scope_conflict")

    if missing:
        state = ("NO_VALID_GOAL_ANCHOR" if gac_value is None
                 else "GOAL_AMBIGUOUS" if gac_value < GAC_SUSPECTED_MIN
                 else "SUSPECTED_DRIFT")
        return {"state": state, "confirmed_drift": False,
                "eligible_for_confirmation": False,
                "missing": sorted(set(missing)),
                "why": "GAC/scope/exclusion gate 不完整，不得 confirmed"}

    evidence = confirmation or {}
    gar = _score(evidence.get("gar"))
    if gar is None or gar < GAR_CONFIRMED_MIN:
        missing.append("gar_at_least_0.70")
    if evidence.get("deterministic_or_owner_confirmed_contradiction") is not True:
        missing.append("deterministic_or_owner_confirmed_contradiction")
    if evidence.get("persisted_after_correction_or_high_impact") is not True:
        missing.append("persistence_or_high_impact")
    dimensions = _strings(evidence.get("independent_evidence_dimensions"))
    if len(dimensions) < 2:
        missing.append("two_independent_evidence_dimensions")

    if missing:
        return {"state": "SUSPECTED_DRIFT", "confirmed_drift": False,
                "eligible_for_confirmation": True,
                "missing": sorted(set(missing)),
                "why": "GAC gate 已過，但 §6.2 confirmation evidence 未齊"}
    return {"state": "CONFIRMED_DRIFT", "confirmed_drift": True,
            "eligible_for_confirmation": True, "missing": [],
            "why": "GAC、scope、exclusion 與 §6.2 evidence 均通過"}
