#!/usr/bin/env python3
"""Deterministic Causal X-Ray projection.

This module projects existing divergence findings and explicit
``PROPAGATES_TO`` lineage edges.  It never turns temporal adjacency into a
causal edge.  When a divergence cannot be attached to an observed incident,
or a propagation endpoint is absent, the contract preserves ``UNKNOWN_EDGE``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import divergence

CONTRACT_VERSION = "causal-xray@1"
UNKNOWN_EDGE = "UNKNOWN_EDGE"
_ANCHORS = (
    ("earliest_suspicious", "SUSPICIOUS"),
    ("earliest_confirmed", "CONFIRMED"),
    ("first_consequential", "CONSEQUENTIAL"),
)


def _round(row: dict) -> int:
    try:
        return int(row.get("n") or 0)
    except (TypeError, ValueError):
        return 0


def _ids(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    text = str(value or "").strip()
    return [text] if text else []


def _root_ids(rows: list[dict], lo: int, hi: int,
              explicit: list[str] | None) -> list[str]:
    if explicit is not None:
        return _ids(explicit)
    found: set[str] = set()
    for row in rows:
        if lo <= _round(row) <= hi:
            found.update(_ids(row.get("incident_ids")))
            found.update(_ids(row.get("incident_id")))
    return sorted(found)


def _unknown(*, source: str | None, target: str | None, why: str,
             relation: str = "PROPAGATES_TO") -> dict:
    return {"type": UNKNOWN_EDGE, "relation": relation,
            "from": source, "to": target, "state": "UNKNOWN", "why": why}


def _edge_key(edge: dict) -> tuple:
    return (str(edge.get("from") or ""), str(edge.get("to") or ""),
            str(edge.get("relation") or edge.get("type") or ""),
            str(edge.get("state") or ""), str(edge.get("why") or ""))


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    """One observed relationship is one edge, even when anchors overlap."""
    unique: dict[tuple, dict] = {}
    for edge in edges:
        key = (_edge_key(edge), str(edge.get("basis") or ""))
        unique.setdefault(key, edge)
    return sorted(unique.values(), key=_edge_key)


def build(rows: list[dict] | None, *, lineage_edges: list[dict] | None = None,
          anchor_incidents: dict[str, list[str]] | None = None) -> dict:
    """Return a stable JSON-ready causal contract.

    ``anchor_incidents`` may explicitly bind one of the three divergence
    anchor names to incident IDs.  Without that binding, only incident IDs
    recorded inside rows in the anchor range are accepted.
    """
    ordered_rows = sorted((dict(row) for row in (rows or []) if isinstance(row, dict)),
                          key=lambda row: (_round(row), str(row.get("id") or "")))
    finding = divergence.find(ordered_rows)
    supplied = anchor_incidents or {}
    anchors: list[dict] = []
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    propagation = []
    for raw in lineage_edges or []:
        if not isinstance(raw, dict) or raw.get("type") != "PROPAGATES_TO":
            continue
        propagation.append(dict(raw))
    propagation.sort(key=lambda e: (str(e.get("from_id") or ""),
                                    str(e.get("to_id") or ""),
                                    str(e.get("id") or "")))

    for name, classification in _ANCHORS:
        point = finding.get(name)
        if not point:
            anchors.append({"name": name, "state": "UNKNOWN", "range": None,
                            "incident_ids": [],
                            "why": "divergence evidence did not establish this anchor"})
            continue
        lo, hi = int(point[0]), int(point[1])
        anchor_id = f"divergence:{name}:{lo}-{hi}"
        roots = _root_ids(ordered_rows, lo, hi,
                          supplied.get(name) if name in supplied else None)
        anchor = {"id": anchor_id, "name": name, "state": classification,
                  "range": [lo, hi], "incident_ids": roots}
        anchors.append(anchor)
        nodes[anchor_id] = {"id": anchor_id, "kind": "divergence_window",
                            "state": classification, "round_range": [lo, hi],
                            "source": "divergence.find"}
        if not roots:
            edges.append(_unknown(
                source=anchor_id, target=None,
                why="no explicit incident ID binds this divergence to downstream lineage"))
            continue

        for root in roots:
            nodes.setdefault(root, {"id": root, "kind": "incident",
                                    "state": "OBSERVED",
                                    "source": "explicit divergence incident binding"})
            edges.append({"type": "ANCHORS_AT", "relation": "ANCHORS_AT",
                          "from": anchor_id, "to": root, "state": "KNOWN",
                          "basis": "explicit incident ID in divergence range"})

        seen = set(roots)
        frontier = list(roots)
        while frontier:
            current = frontier.pop(0)
            outgoing = [edge for edge in propagation
                        if str(edge.get("from_id") or "") == current]
            for raw in outgoing:
                target = str(raw.get("to_id") or "").strip()
                basis = str(raw.get("basis") or "").strip()
                if not target or not basis:
                    edges.append(_unknown(
                        source=current, target=target or None,
                        why="PROPAGATES_TO is missing a target or evidence basis"))
                    continue
                nodes.setdefault(target, {
                    "id": target, "kind": str(raw.get("to_kind") or "node"),
                    "state": "OBSERVED", "source": "lineage.PROPAGATES_TO"})
                edges.append({"type": "PROPAGATES_TO", "relation": "PROPAGATES_TO",
                              "from": current, "to": target, "state": "KNOWN",
                              "basis": basis})
                if target not in seen:
                    seen.add(target)
                    frontier.append(target)

    edges = _dedupe_edges(edges)
    unknown_n = sum(edge.get("type") == UNKNOWN_EDGE for edge in edges)
    unknown_anchors = sum(anchor.get("state") == "UNKNOWN" for anchor in anchors)
    known_propagation = sum(edge.get("type") == "PROPAGATES_TO" and
                            edge.get("state") == "KNOWN" for edge in edges)
    if not finding.get("has"):
        status = "UNKNOWN"
        why = finding.get("why") or "no divergence evidence"
    elif unknown_n or unknown_anchors:
        status = "PARTIAL"
        why = ("divergence exists, but at least one anchor or downstream "
               "causal edge is unknown")
    elif known_propagation:
        status = "COMPLETE"
        why = "all returned propagation edges have explicit incident endpoints and basis"
    else:
        status = "PARTIAL"
        why = "divergence anchors exist, but no downstream propagation was observed"
    return {"version": CONTRACT_VERSION, "status": status, "why": why,
            "anchors": anchors,
            "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
            "edges": edges, "unknown_edges": unknown_n,
            "unknown_anchors": unknown_anchors,
            "known_propagation_edges": known_propagation,
            "divergence": finding}
