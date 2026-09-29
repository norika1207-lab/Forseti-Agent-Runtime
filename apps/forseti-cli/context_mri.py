#!/usr/bin/env python3
"""Deterministic Context MRI projection.

The contract links decisions only to explicit fragment/provenance references.
Compression token counts do not reveal which ideas were lost, so numeric-only
compaction data produces ``UNKNOWN_EDGE`` instead of an invented dependency.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass

CONTRACT_VERSION = "context-mri@1"
UNKNOWN_EDGE = "UNKNOWN_EDGE"
CONTEXT_CLASSES = ("CHAT_HISTORY", "CANONICAL_PROJECT_STATE",
                   "HEALTHY_COLLABORATION_CONTEXT")


def _dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    return {}


def _list(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    text = str(value or "").strip()
    return [text] if text else []


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _edge_key(edge: dict) -> tuple:
    return (str(edge.get("from") or ""), str(edge.get("to") or ""),
            str(edge.get("relation") or edge.get("type") or ""),
            str(edge.get("state") or ""))


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    unique: dict[tuple, dict] = {}
    for edge in edges:
        key = (_edge_key(edge), str(edge.get("basis") or ""),
               str(edge.get("why") or ""))
        unique.setdefault(key, edge)
    return sorted(unique.values(), key=_edge_key)


def _unknown(source: str | None, target: str | None, why: str,
             relation: str) -> dict:
    return {"type": UNKNOWN_EDGE, "relation": relation, "from": source,
            "to": target, "state": "UNKNOWN", "why": why}


def build(*, decisions: list[dict] | None = None,
          fragments: list[dict] | None = None,
          compactions: list[dict] | None = None) -> dict:
    fragment_nodes: dict[str, dict] = {}
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    fragment_rows = [_dict(value) for value in (fragments or [])]
    fragment_rows.sort(key=lambda row: (str(row.get("id") or
                                             row.get("provenance") or ""),
                                        json.dumps(row, ensure_ascii=False,
                                                   sort_keys=True, default=str)))
    unknown_context_classes = 0
    for index, row in enumerate(fragment_rows):
        source_id = str(row.get("id") or row.get("provenance") or "").strip()
        if not source_id:
            source_id = f"unknown-fragment:{index}"
            state = "UNKNOWN"
        else:
            state = "OBSERVED"
        context_class = str(row.get("context_class") or "UNKNOWN").strip()
        if context_class not in CONTEXT_CLASSES:
            context_class = "UNKNOWN"
        if context_class == "UNKNOWN":
            unknown_context_classes += 1
        node = {"id": source_id, "kind": "fragment", "state": state,
                "source_type": str(row.get("source") or "UNKNOWN"),
                "context_class": context_class,
                "provenance": str(row.get("provenance") or ""),
                "why_included": str(row.get("why") or "")}
        fragment_nodes[source_id] = node
        provenance = node["provenance"]
        if provenance:
            fragment_nodes.setdefault(provenance, node)
        nodes[source_id] = node

    decision_rows = sorted((_dict(value) for value in (decisions or [])),
                           key=lambda row: str(row.get("id") or ""))
    for index, row in enumerate(decision_rows):
        decision_id = str(row.get("id") or "").strip()
        if not decision_id:
            decision_id = f"unknown-decision:{index}"
            state = "UNKNOWN"
        else:
            state = str(row.get("state") or "OBSERVED")
        nodes[decision_id] = {"id": decision_id, "kind": "decision",
                              "state": state,
                              "source": str(row.get("source") or "")}
        refs = _list(row.get("fragment_refs") or row.get("provenance_refs"))
        if not refs:
            edges.append(_unknown(
                decision_id, None,
                "decision has no explicit fragment or provenance references",
                "DEPENDS_ON"))
            continue
        for ref in refs:
            fragment = fragment_nodes.get(ref)
            if not fragment or fragment.get("state") == "UNKNOWN":
                edges.append(_unknown(
                    decision_id, ref,
                    "decision references a fragment without an observed stable identity",
                    "DEPENDS_ON"))
                continue
            edges.append({"type": "DEPENDS_ON", "relation": "DEPENDS_ON",
                          "from": decision_id, "to": fragment["id"],
                          "state": "KNOWN", "basis": "explicit decision reference"})

    compaction_rows = sorted((_dict(value) for value in (compactions or [])),
                             key=lambda row: (str(row.get("at") or row.get("ts") or ""),
                                              str(row.get("id") or "")))
    loss_records: list[dict] = []
    for index, row in enumerate(compaction_rows):
        compaction_id = str(row.get("id") or row.get("anchor_uuid") or
                            row.get("head_uuid") or f"compaction:{index}").strip()
        nodes[compaction_id] = {"id": compaction_id, "kind": "compaction",
                                "state": "OBSERVED",
                                "dropped_tokens": _int(row.get("dropped") or
                                                       row.get("dropped_tokens"))}
        dropped = _list(row.get("dropped_fragment_ids"))
        if dropped:
            for ref in dropped:
                fragment = fragment_nodes.get(ref)
                if fragment and fragment.get("state") != "UNKNOWN":
                    edges.append({"type": "DROPPED_BY", "relation": "DROPPED_BY",
                                  "from": fragment["id"], "to": compaction_id,
                                  "state": "KNOWN",
                                  "basis": "explicit compaction dropped_fragment_ids"})
                else:
                    edges.append(_unknown(
                        ref, compaction_id,
                        "compaction names a dropped fragment absent from the supplied corpus",
                        "DROPPED_BY"))
            loss_records.append({"compaction_id": compaction_id,
                                 "state": "KNOWN", "fragment_ids": dropped})
        elif nodes[compaction_id]["dropped_tokens"] > 0:
            edges.append(_unknown(
                None, compaction_id,
                "token loss is observed, but the dropped fragment identities are unavailable",
                "DROPPED_BY"))
            loss_records.append({"compaction_id": compaction_id,
                                 "state": "UNKNOWN", "fragment_ids": []})
        else:
            loss_records.append({"compaction_id": compaction_id,
                                 "state": "NONE_OBSERVED", "fragment_ids": []})

    edges = _dedupe_edges(edges)
    unknown_n = sum(edge.get("type") == UNKNOWN_EDGE for edge in edges)
    known_dependencies = sum(edge.get("type") == "DEPENDS_ON" and
                             edge.get("state") == "KNOWN" for edge in edges)
    status = "UNKNOWN" if not decision_rows else (
        "PARTIAL" if unknown_n or unknown_context_classes else "COMPLETE")
    why = ("no decisions were supplied" if not decision_rows else
           "at least one decision dependency or compression loss is unknown"
           if unknown_n else
           "at least one fragment cannot be assigned to a distinct context class"
           if unknown_context_classes else
           "all returned decision dependencies and compression losses are explicit")
    return {"version": CONTRACT_VERSION, "status": status, "why": why,
            "context_classes": list(CONTEXT_CLASSES),
            "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
            "edges": edges, "unknown_edges": unknown_n,
            "unknown_context_classes": unknown_context_classes,
            "known_decision_dependencies": known_dependencies,
            "compression_loss": loss_records}
