#!/usr/bin/env python3
"""Deterministic live-event projection for execution identity topology.

This adapter is deliberately narrower than ``src/topology.js``.  It projects
only identity relationships that are explicit in normalized events: agent,
process, runtime node, session, and worldview version.  It never reads transcript prose to
invent a runtime edge.  Missing endpoint data remains an UNKNOWN edge or a
diagnostic, per Formal P8 / FS-TOP-001.

The module has no I/O and no third-party dependencies.  Callers may pass plain
dicts, ``NormalizedEvent`` objects, or persisted Event Ledger rows containing
``{"norm": ...}``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

VERSION = "execution-topology@1"

NODE_KINDS = (
    "AGENT", "PROCESS", "RUNTIME_NODE", "SESSION", "WORLDVIEW_VERSION"
)
EDGE_TYPES = (
    "AGENT_IN_SESSION",
    "PROCESS_IN_SESSION",
    "AGENT_OPERATES_PROCESS",
    "PROCESS_ON_RUNTIME_NODE",
    "SESSION_USES_WORLDVIEW",
    # These names are the Formal P8 / src/topology.js contract.  Do not prefix
    # them with endpoint kinds; callers need one topology vocabulary.
    "SPAWNS",
    "DELEGATES_TO",
    "SUPERSEDES",
    "UNKNOWN_EDGE",
)

_ID_FIELDS = {
    "AGENT": ("agent_id",),
    "PROCESS": ("process_id",),
    "SESSION": ("session_id",),
    # A generic ``version`` may be a CLI/model/provider version.  It is not a
    # worldview version unless the producer names that meaning explicitly.
    "WORLDVIEW_VERSION": (
        "worldview_version",
        "goal_version",
        "north_star_version",
    ),
}

_EXPLICIT_PARENT_FIELDS = {
    "parent_agent_id": ("AGENT", "AGENT", "DELEGATES_TO"),
    "parent_process_id": ("PROCESS", "PROCESS", "SPAWNS"),
    "supersedes_worldview_version": (
        "WORLDVIEW_VERSION", "WORLDVIEW_VERSION", "SUPERSEDES"
    ),
}


class TopologyContractError(ValueError):
    """The producer supplied a malformed explicit topology declaration."""


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        row = dict(value)
    elif is_dataclass(value):
        row = asdict(value)
    elif hasattr(value, "__dict__"):
        row = dict(vars(value))
    else:
        raise TopologyContractError("event must be a mapping or structured object")
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
    """Return an explicit value and its field path; never inspect prose."""
    meta = _metadata(row)
    for name in names:
        value = _clean(row.get(name))
        if value:
            return value, name
        value = _clean(meta.get(name))
        if value:
            return value, f"metadata.{name}"
    return "", ""


def _node_id(kind: str, source_id: str) -> str:
    if kind not in NODE_KINDS or not _clean(source_id):
        raise TopologyContractError("node kind and source id must be explicit")
    digest = hashlib.sha256(f"{kind}:{source_id}".encode("utf-8")).hexdigest()[:16]
    return f"{kind.lower()}-{digest}"


def _edge_id(edge_type: str, from_id: str, to_id: str) -> str:
    raw = json.dumps([edge_type, from_id, to_id], separators=(",", ":"))
    return f"edge-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _event_id(row: Mapping[str, Any], index: int) -> str:
    return _clean(row.get("id") or row.get("raw_event_id")) or f"input:{index}"


def project(events: Iterable[Any] | None) -> dict[str, Any]:
    """Project explicit normalized events into a deterministic topology.

    Co-occurrence of explicit identity fields in one structured event is the
    evidence basis for the three execution-context edges.  Parent/delegation
    and worldview-supersession edges require their dedicated fields.  Textual
    mentions never become nodes or edges.
    """
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    unknown_edges: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    seen = 0
    with_identity = 0

    def add_node(kind: str, source_id: str, source_event_id: str) -> dict[str, Any]:
        nid = _node_id(kind, source_id)
        existing = nodes.get(nid)
        if existing is None:
            existing = {
                "id": nid,
                "kind": kind,
                "source_id": source_id,
                "state": "OBSERVED",
                "source_event_ids": [],
            }
            nodes[nid] = existing
        if source_event_id not in existing["source_event_ids"]:
            existing["source_event_ids"].append(source_event_id)
        return existing

    def add_edge(
        edge_type: str,
        from_node: dict[str, Any],
        to_node: dict[str, Any],
        *,
        event_id: str,
        basis: list[str],
    ) -> None:
        if edge_type not in EDGE_TYPES:
            raise TopologyContractError(f"unknown execution edge type: {edge_type}")
        key = (edge_type, from_node["id"], to_node["id"])
        existing = edges.get(key)
        if existing is None:
            existing = {
                "id": _edge_id(*key),
                "type": edge_type,
                "from": from_node["id"],
                "to": to_node["id"],
                "state": "KNOWN",
                "basis_fields": sorted(set(basis)),
                "source_event_ids": [],
            }
            edges[key] = existing
        if event_id not in existing["source_event_ids"]:
            existing["source_event_ids"].append(event_id)

    def add_unknown_edge(
        intended_type: str,
        *,
        from_id: str | None,
        to_id: str | None,
        event_id: str,
        reason: str,
        basis: list[str],
    ) -> None:
        if intended_type not in EDGE_TYPES or intended_type == "UNKNOWN_EDGE":
            raise TopologyContractError(
                f"unknown intended execution edge type: {intended_type}"
            )
        if not _clean(reason):
            raise TopologyContractError(
                "UNKNOWN_EDGE requires unobservable_reason (FS-TOP-001)"
            )
        unknown_edges.append({
            "id": _edge_id(
                f"UNKNOWN_EDGE:{intended_type}",
                from_id or "UNKNOWN_FROM",
                to_id or "UNKNOWN_TO",
            ),
            "type": "UNKNOWN_EDGE",
            "intended_type": intended_type,
            "from": from_id,
            "to": to_id,
            "state": "UNKNOWN",
            "source_event_id": event_id,
            "basis_fields": sorted(set(basis)),
            "unobservable_reason": reason,
        })

    for index, raw in enumerate(events or []):
        seen += 1
        try:
            row = _mapping(raw)
        except TopologyContractError as exc:
            diagnostics.append({
                "input_index": index,
                "state": "UNKNOWN",
                "why": str(exc),
            })
            continue

        eid = _event_id(row, index)
        found: dict[str, tuple[str, str, dict[str, Any]]] = {}
        for kind, fields in _ID_FIELDS.items():
            value, field = _explicit(row, *fields)
            if value:
                found[kind] = (value, field, add_node(kind, value, eid))

        # ``runtime_node_id`` is a canonical NormalizedEvent field.  A value in
        # metadata is not equivalent and must not silently become topology.
        runtime_node_id = _clean(row.get("runtime_node_id"))
        metadata_runtime_node_id = _clean(_metadata(row).get("runtime_node_id"))
        if runtime_node_id:
            found["RUNTIME_NODE"] = (
                runtime_node_id,
                "runtime_node_id",
                add_node("RUNTIME_NODE", runtime_node_id, eid),
            )
        elif metadata_runtime_node_id:
            diagnostics.append({
                "source_event_id": eid,
                "field": "runtime_node_id",
                "state": "UNKNOWN",
                "why": (
                    "metadata.runtime_node_id is not the canonical NormalizedEvent "
                    "runtime_node_id field"
                ),
            })

        parent_values = {
            field: _explicit(row, field)
            for field in _EXPLICIT_PARENT_FIELDS
        }

        if found:
            with_identity += 1
        elif not any(value for value, _ in parent_values.values()):
            diagnostics.append({
                "source_event_id": eid,
                "state": "SKIPPED",
                "why": "no explicit execution identity fields; transcript text was not parsed",
            })
            continue

        pairs = (
            ("AGENT_IN_SESSION", "AGENT", "SESSION"),
            ("PROCESS_IN_SESSION", "PROCESS", "SESSION"),
            ("AGENT_OPERATES_PROCESS", "AGENT", "PROCESS"),
            ("PROCESS_ON_RUNTIME_NODE", "PROCESS", "RUNTIME_NODE"),
            ("SESSION_USES_WORLDVIEW", "SESSION", "WORLDVIEW_VERSION"),
        )
        for edge_type, from_kind, to_kind in pairs:
            if from_kind in found and to_kind in found:
                add_edge(
                    edge_type,
                    found[from_kind][2],
                    found[to_kind][2],
                    event_id=eid,
                    basis=[found[from_kind][1], found[to_kind][1]],
                )

        if "PROCESS" in found and "RUNTIME_NODE" not in found:
            add_unknown_edge(
                "PROCESS_ON_RUNTIME_NODE",
                from_id=found["PROCESS"][2]["id"],
                to_id=None,
                event_id=eid,
                reason="canonical runtime_node_id is missing from the normalized event",
                basis=[found["PROCESS"][1]],
            )
            diagnostics.append({
                "source_event_id": eid,
                "field": "runtime_node_id",
                "state": "UNKNOWN",
                "why": "canonical runtime_node_id is missing; process placement is unknown",
            })
        elif "RUNTIME_NODE" in found and "PROCESS" not in found:
            add_unknown_edge(
                "PROCESS_ON_RUNTIME_NODE",
                from_id=None,
                to_id=found["RUNTIME_NODE"][2]["id"],
                event_id=eid,
                reason="runtime_node_id is explicit but the process endpoint is missing",
                basis=[found["RUNTIME_NODE"][1]],
            )

        for field, (parent_kind, child_kind, edge_type) in _EXPLICIT_PARENT_FIELDS.items():
            parent_value, parent_path = parent_values[field]
            if not parent_value:
                continue
            child = found.get(child_kind)
            if child is None:
                add_unknown_edge(
                    edge_type,
                    from_id=_node_id(parent_kind, parent_value),
                    to_id=None,
                    event_id=eid,
                    reason=(
                        f"{parent_path} is explicit but the child endpoint is missing"
                    ),
                    basis=[parent_path],
                )
                continue
            parent = add_node(parent_kind, parent_value, eid)
            add_edge(
                edge_type,
                parent,
                child[2],
                event_id=eid,
                basis=[parent_path, child[1]],
            )

    node_rows = sorted(nodes.values(), key=lambda n: (n["kind"], n["source_id"]))
    edge_rows = sorted(edges.values(), key=lambda e: (e["type"], e["from"], e["to"]))
    unknown_edges.sort(
        key=lambda e: (e["source_event_id"], e["intended_type"], e["id"])
    )
    all_edges = sorted(
        [*edge_rows, *unknown_edges],
        key=lambda e: (e["type"], e.get("intended_type", ""), e["id"]),
    )
    diagnostics.sort(key=lambda d: (d.get("source_event_id", ""), d.get("input_index", -1)))
    return {
        "version": VERSION,
        "nodes": node_rows,
        # Formal P8 exposes one edge collection including UNKNOWN_EDGE.  The
        # split views remain available so runtime callers do not have to infer
        # known/unknown from counts or nullable endpoints.
        "edges": all_edges,
        "known_edges": edge_rows,
        "unknown_edges": unknown_edges,
        "coverage": {
            "events_seen": seen,
            "events_with_explicit_identity": with_identity,
            "events_skipped": seen - with_identity,
            "known_edges": len(edge_rows),
            "unknown_edges": len(unknown_edges),
        },
        "diagnostics": diagnostics,
        "unknown_policy": (
            "Only explicit structured identity fields create runtime edges; "
            "transcript prose and generic version fields remain unprojected."
        ),
    }


def from_events(events: Iterable[Any] | None) -> dict[str, Any]:
    """Named adapter entry point for live Event Ledger callers."""
    return project(events)


build_topology = from_events
