#!/usr/bin/env python3
"""Project structured governance events into an Authority Map contract.

The map reuses ``authority.py`` as the sole trust-order source.  It displays
trust levels, explicit approval records, and competing authority claims.  An
unknown or absent principal is never upgraded from wording or event order: an
apparent ALLOW from such a source is retained as evidence but is effective
``BLOCKED_UNKNOWN_AUTHORITY`` (fail closed).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

try:
    import authority
except ImportError:  # pragma: no cover - supports package-style loading
    from . import authority  # type: ignore

VERSION = "authority-map@1"
GOVERNANCE_EVENTS = (
    "APPROVAL_REQUESTED",
    "POLICY_ALLOW",
    "POLICY_BLOCK",
    "AUTHORITY_COLLISION",
    "WRITE_BARRIER",
)


class AuthorityMapContractError(ValueError):
    """An explicit Authority Map input is malformed."""


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        row = dict(value)
    elif is_dataclass(value):
        row = asdict(value)
    elif hasattr(value, "__dict__"):
        row = dict(vars(value))
    else:
        raise AuthorityMapContractError("event must be a mapping or structured object")
    norm = row.get("norm")
    return dict(norm) if isinstance(norm, Mapping) else row


def _clean(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return dict(value) if isinstance(value, Mapping) else {}


def _explicit(row: Mapping[str, Any], *names: str) -> tuple[str, str]:
    meta = _metadata(row)
    for name in names:
        value = _clean(row.get(name))
        if value:
            return value, name
        value = _clean(meta.get(name))
        if value:
            return value, f"metadata.{name}"
    return "", ""


def _principal(raw: str) -> tuple[str, bool]:
    candidate = _clean(raw).upper()
    # UNSUPPORTED is the fail-closed floor of the hierarchy, not an authority.
    # Keeping it in TRUST makes the map complete; treating it as ``known``
    # would turn an explicit ``principal=UNSUPPORTED`` POLICY_ALLOW into an
    # approval, which defeats the purpose of that level.
    known = {name for name, _, _ in authority.TRUST if name != "UNSUPPORTED"}
    return (candidate, True) if candidate in known else ("UNSUPPORTED", False)


def _event_id(row: Mapping[str, Any], index: int) -> str:
    return _clean(row.get("id") or row.get("raw_event_id")) or f"input:{index}"


def _claim_row(resource: str, principal_raw: str, event_id: str, detail: str = "") -> dict:
    principal, known = _principal(principal_raw)
    return {
        "resource": resource,
        "principal": principal,
        "principal_raw": principal_raw,
        "principal_known": known,
        "trust_rank": authority.rank(principal),
        "trust_weight": authority.weight(principal),
        "source_event_id": event_id,
        "detail": detail,
    }


def project(
    events: Iterable[Any] | None,
    *,
    claims: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a deterministic Authority Map from explicit event fields.

    Recognized governance events are mapped from ``type`` plus explicit
    ``principal``/``authority``/``approved_by`` and ``resource`` fields.  Extra
    claims may be supplied by a canonical claim store.  Prose is never parsed
    to discover who approved what.
    """
    claim_rows: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    unknown_sources: list[dict[str, Any]] = []

    for index, raw in enumerate(events or []):
        try:
            row = _mapping(raw)
        except AuthorityMapContractError as exc:
            unknown_sources.append({
                "input_index": index,
                "state": "BLOCKED_UNKNOWN_AUTHORITY",
                "why": str(exc),
            })
            continue
        event_type = _clean(row.get("type")).upper()
        if event_type not in GOVERNANCE_EVENTS:
            continue
        eid = _event_id(row, index)
        principal_raw, principal_field = _explicit(
            row, "principal", "authority", "approved_by"
        )
        resource, resource_field = _explicit(row, "resource")
        if not resource:
            # subject/object are structured Event Ledger fields, not prose.
            resource, resource_field = _explicit(row, "subject", "object")
        action, _ = _explicit(row, "intent", "action")
        principal, known = _principal(principal_raw)

        state = {
            "APPROVAL_REQUESTED": "REQUESTED",
            "POLICY_ALLOW": "APPROVED",
            "POLICY_BLOCK": "BLOCKED",
            "AUTHORITY_COLLISION": "CONFLICT_REPORTED",
            "WRITE_BARRIER": "BLOCKED",
        }[event_type]
        effective_state = state
        if not known:
            effective_state = "BLOCKED_UNKNOWN_AUTHORITY"
            unknown_sources.append({
                "source_event_id": eid,
                "principal_raw": principal_raw,
                "state": effective_state,
                "why": "principal is missing or outside the normative trust hierarchy",
            })
        if not resource:
            effective_state = "BLOCKED_UNKNOWN_RESOURCE"
            unknown_sources.append({
                "source_event_id": eid,
                "state": effective_state,
                "why": "approval/conflict event has no explicit resource",
            })

        approvals.append({
            "source_event_id": eid,
            "event_type": event_type,
            "resource": resource,
            "principal": principal,
            "principal_raw": principal_raw,
            "principal_known": known,
            "action": action,
            "declared_state": state,
            "effective_state": effective_state,
            "can_rely_on": effective_state in ("APPROVED", "BLOCKED"),
            "basis_fields": [p for p in (principal_field, resource_field) if p],
        })
        if resource and principal_raw:
            claim_rows.append(_claim_row(resource, principal_raw, eid, event_type))

    for index, raw_claim in enumerate(claims or []):
        if not isinstance(raw_claim, Mapping):
            unknown_sources.append({
                "claim_index": index,
                "state": "BLOCKED_UNKNOWN_AUTHORITY",
                "why": "authority claim is not a structured mapping",
            })
            continue
        resource = _clean(raw_claim.get("resource"))
        principal_raw = _clean(raw_claim.get("principal"))
        event_id = _clean(raw_claim.get("source_event_id") or raw_claim.get("id"))
        event_id = event_id or f"claim:{index}"
        if not resource or not principal_raw:
            unknown_sources.append({
                "source_event_id": event_id,
                "state": "BLOCKED_UNKNOWN_AUTHORITY",
                "why": "authority claim requires explicit resource and principal",
            })
            continue
        claim = _claim_row(
            resource, principal_raw, event_id, _clean(raw_claim.get("detail"))
        )
        claim_rows.append(claim)
        if not claim["principal_known"]:
            unknown_sources.append({
                "source_event_id": event_id,
                "principal_raw": principal_raw,
                "state": "BLOCKED_UNKNOWN_AUTHORITY",
                "why": "claim principal is outside the normative trust hierarchy",
            })

    # ``authority.collisions`` remains the single implementation of the
    # normative winner order.  Preserve source rows around its summary.
    collision_input = [
        {
            "resource": row["resource"],
            "principal": row["principal"],
            "detail": row["detail"],
        }
        for row in claim_rows
    ]
    conflicts = authority.collisions(collision_input)
    for conflict in conflicts:
        supporting = [
            row["source_event_id"]
            for row in claim_rows
            if row["resource"] == conflict["resource"]
        ]
        conflict["source_event_ids"] = sorted(set(supporting))

    principals: dict[str, dict[str, Any]] = {}
    for row in claim_rows:
        name = row["principal"]
        principals[name] = {
            "principal": name,
            "known": row["principal_known"],
            "trust_rank": row["trust_rank"],
            "trust_weight": row["trust_weight"],
        }

    resources = sorted({row["resource"] for row in claim_rows if row["resource"]})
    claim_rows.sort(key=lambda row: (row["resource"], row["trust_rank"], row["source_event_id"]))
    approvals.sort(key=lambda row: (row["source_event_id"], row["event_type"]))
    unknown_sources.sort(
        key=lambda row: (row.get("source_event_id", ""), row.get("input_index", -1))
    )
    return {
        "version": VERSION,
        "trust_levels": [
            {
                "principal": name,
                "rank": index,
                "weight": weight,
                "means": means,
            }
            for index, (name, weight, means) in enumerate(authority.TRUST)
        ],
        "principals": sorted(principals.values(), key=lambda row: row["trust_rank"]),
        "resources": resources,
        "claims": claim_rows,
        "approvals": approvals,
        "conflicts": conflicts,
        "has_conflict": bool(conflicts),
        "unknown_sources": unknown_sources,
        "fail_closed": bool(unknown_sources),
        "unknown_policy": (
            "Unknown or missing authority cannot approve an action; wording and event order "
            "do not raise trust."
        ),
    }


def from_events(
    events: Iterable[Any] | None,
    *,
    claims: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    return project(events, claims=claims)


build_authority_map = from_events
