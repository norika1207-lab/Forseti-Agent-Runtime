#!/usr/bin/env python3
"""Deterministic Context MRI projection.

Decision and fragment identities are not last-write-wins maps.  Conflicting
records with the same ID, or multiple fragments sharing one provenance, stay
visible as collisions and produce UNKNOWN edges.  Compression counters are
also fail-closed: an invalid count is not silently converted to zero.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, is_dataclass

CONTRACT_VERSION = "context-mri@1"
UNKNOWN_EDGE = "UNKNOWN_EDGE"
CONTEXT_CLASSES = ("CHAT_HISTORY", "CANONICAL_PROJECT_STATE",
                   "HEALTHY_COLLABORATION_CONTEXT")
_NONNEGATIVE_INT = re.compile(r"^(0|[1-9][0-9]*)$")


def _dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    return {}


def _canonical(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def _fingerprint(row: dict) -> str:
    return hashlib.sha256(_canonical(row).encode("utf-8")).hexdigest()[:12]


def _list(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item).strip()})
    text = str(value or "").strip()
    return [text] if text else []


def _edge_key(edge: dict) -> tuple:
    return (str(edge.get("from") or ""), str(edge.get("to") or ""),
            str(edge.get("relation") or ""), str(edge.get("type") or ""),
            str(edge.get("state") or ""), str(edge.get("basis") or ""),
            str(edge.get("why") or ""), _canonical(edge))


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for edge in edges:
        unique.setdefault(_canonical(edge), edge)
    return sorted(unique.values(), key=_edge_key)


def _unknown(source: str | None, target: str | None, why: str,
             relation: str) -> dict:
    return {"type": UNKNOWN_EDGE, "relation": relation, "from": source,
            "to": target, "state": "UNKNOWN", "why": why}


def _parse_token_count(value) -> tuple[int | None, str]:
    if isinstance(value, bool):
        return None, "UNKNOWN"
    if isinstance(value, int):
        return (value, "KNOWN") if value >= 0 else (None, "UNKNOWN")
    if isinstance(value, str) and _NONNEGATIVE_INT.fullmatch(value.strip()):
        return int(value.strip()), "KNOWN"
    return None, "UNKNOWN"


def _token_value(row: dict):
    if "dropped" in row:
        return row.get("dropped")
    if "dropped_tokens" in row:
        return row.get("dropped_tokens")
    return None


def _group(rows: list[dict], identity) -> dict[str, list[dict]]:
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows:
        key = identity(row)
        grouped.setdefault(key, {}).setdefault(_canonical(row), row)
    return {key: [variants[name] for name in sorted(variants)]
            for key, variants in sorted(grouped.items())}


def build(*, decisions: list[dict] | None = None,
          fragments: list[dict] | None = None,
          compactions: list[dict] | None = None) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    collisions: list[dict] = []
    provenance_index: dict[str, set[str]] = {}

    fragment_rows = [_dict(value) for value in (fragments or [])]

    def fragment_identity(row: dict) -> str:
        explicit = str(row.get("id") or row.get("provenance") or "").strip()
        return explicit or f"unknown-fragment:{_fingerprint(row)}"

    fragment_groups = _group(fragment_rows, fragment_identity)
    fragment_nodes: dict[str, dict] = {}
    unknown_context_classes = 0
    for fragment_id, variants in fragment_groups.items():
        collision = len(variants) > 1
        classes = {str(row.get("context_class") or "UNKNOWN").strip()
                   for row in variants}
        context_class = next(iter(classes)) if len(classes) == 1 else "UNKNOWN"
        if context_class not in CONTEXT_CLASSES:
            context_class = "UNKNOWN"
        missing_identity = fragment_id.startswith("unknown-fragment:")
        state = "UNKNOWN" if collision or missing_identity else "OBSERVED"
        node = {
            "id": fragment_id, "kind": "fragment", "state": state,
            "source_type": (str(variants[0].get("source") or "UNKNOWN")
                            if len({str(row.get("source") or "UNKNOWN")
                                    for row in variants}) == 1 else "UNKNOWN"),
            "context_class": context_class,
            "provenance": (str(variants[0].get("provenance") or "")
                           if len({str(row.get("provenance") or "")
                                   for row in variants}) == 1 else ""),
            "why_included": (str(variants[0].get("why") or "")
                             if len({str(row.get("why") or "")
                                     for row in variants}) == 1 else ""),
            "collision": collision,
            "variant_fingerprints": [_fingerprint(row) for row in variants],
    }
        if context_class == "UNKNOWN":
            unknown_context_classes += 1
        if collision:
            collisions.append({"kind": "fragment_id", "key": fragment_id,
                               "candidates": node["variant_fingerprints"],
                               "state": "UNKNOWN"})
            edges.append(_unknown(fragment_id, None,
                                  "conflicting fragment records share one ID",
                                  "IDENTITY_COLLISION"))
        elif missing_identity:
            edges.append(_unknown(None, fragment_id,
                                  "fragment has no stable ID or provenance",
                                  "IDENTITY"))
        fragment_nodes[fragment_id] = node
        nodes[fragment_id] = node
        for row in variants:
            provenance = str(row.get("provenance") or "").strip()
            if provenance:
                provenance_index.setdefault(provenance, set()).add(fragment_id)

    provenance_collisions = []
    for provenance, candidates in sorted(provenance_index.items()):
        if len(candidates) > 1:
            record = {"kind": "provenance", "key": provenance,
                      "candidates": sorted(candidates), "state": "UNKNOWN"}
            provenance_collisions.append(record)
            collisions.append(record)
            edges.append(_unknown(provenance, None,
                                  "one provenance resolves to multiple fragments: " +
                                  ", ".join(sorted(candidates)),
                                  "PROVENANCE_RESOLVES_TO"))

    decision_rows = [_dict(value) for value in (decisions or [])]

    def decision_identity(row: dict) -> str:
        explicit = str(row.get("id") or "").strip()
        return explicit or f"unknown-decision:{_fingerprint(row)}"

    decision_groups = _group(decision_rows, decision_identity)
    for decision_id, variants in decision_groups.items():
        collision = len(variants) > 1
        missing_identity = decision_id.startswith("unknown-decision:")
        state_values = {str(row.get("state") or "OBSERVED") for row in variants}
        state = (next(iter(state_values)) if len(state_values) == 1 else "UNKNOWN")
        if collision or missing_identity:
            state = "UNKNOWN"
        node = {"id": decision_id, "kind": "decision", "state": state,
                "source": (str(variants[0].get("source") or "")
                           if len({str(row.get("source") or "")
                                   for row in variants}) == 1 else ""),
                "collision": collision,
                "variant_fingerprints": [_fingerprint(row) for row in variants]}
        nodes[decision_id] = node
        if collision:
            collisions.append({"kind": "decision_id", "key": decision_id,
                               "candidates": node["variant_fingerprints"],
                               "state": "UNKNOWN"})
            edges.append(_unknown(decision_id, None,
                                  "conflicting decision records share one ID",
                                  "IDENTITY_COLLISION"))
        elif missing_identity:
            edges.append(_unknown(None, decision_id,
                                  "decision has no stable source ID", "IDENTITY"))

        tagged_refs: set[tuple[str, str]] = set()
        for row in variants:
            tagged_refs.update(("fragment", ref)
                               for ref in _list(row.get("fragment_refs")))
            tagged_refs.update(("provenance", ref)
                               for ref in _list(row.get("provenance_refs")))
        if not tagged_refs:
            edges.append(_unknown(
                decision_id, None,
                "decision has no explicit fragment or provenance references",
                "DEPENDS_ON"))
            continue
        for ref_kind, ref in sorted(tagged_refs):
            if collision or missing_identity:
                edges.append(_unknown(
                    decision_id, ref,
                    "decision identity is ambiguous, so its dependency cannot be promoted",
                    "DEPENDS_ON"))
                continue
            if ref_kind == "fragment":
                candidates = [ref] if ref in fragment_nodes else []
            else:
                candidates = sorted(provenance_index.get(ref, set()))
            if len(candidates) != 1:
                reason = ("reference is absent from the supplied fragment corpus"
                          if not candidates else
                          "provenance resolves to multiple fragment candidates: " +
                          ", ".join(candidates))
                edges.append(_unknown(decision_id, ref, reason, "DEPENDS_ON"))
                continue
            fragment = fragment_nodes[candidates[0]]
            if fragment.get("state") == "UNKNOWN":
                edges.append(_unknown(
                    decision_id, fragment["id"],
                    "referenced fragment identity is UNKNOWN", "DEPENDS_ON"))
                continue
            edges.append({"type": "DEPENDS_ON", "relation": "DEPENDS_ON",
                          "from": decision_id, "to": fragment["id"],
                          "state": "KNOWN", "basis":
                          f"explicit decision {ref_kind} reference"})

    compaction_rows = [_dict(value) for value in (compactions or [])]
    compaction_rows.sort(key=lambda row: (
        str(row.get("at") or row.get("ts") or ""), str(row.get("id") or ""),
        _canonical(row)))
    loss_records: list[dict] = []
    for index, row in enumerate(compaction_rows):
        compaction_id = str(row.get("id") or row.get("anchor_uuid") or
                            row.get("head_uuid") or
                            f"compaction:{_fingerprint(row)}:{index}").strip()
        token_count, token_state = _parse_token_count(_token_value(row))
        nodes[compaction_id] = {"id": compaction_id, "kind": "compaction",
                                "state": "OBSERVED" if token_state == "KNOWN"
                                else "UNKNOWN",
                                "dropped_tokens": token_count,
                                "dropped_tokens_state": token_state}
        dropped = _list(row.get("dropped_fragment_ids"))
        known_dropped = []
        for ref in dropped:
            fragment = fragment_nodes.get(ref)
            if fragment and fragment.get("state") != "UNKNOWN":
                known_dropped.append(ref)
                edges.append({"type": "DROPPED_BY", "relation": "DROPPED_BY",
                              "from": fragment["id"], "to": compaction_id,
                              "state": "KNOWN",
                              "basis": "explicit compaction dropped_fragment_ids"})
            else:
                edges.append(_unknown(
                    ref, compaction_id,
                    "compaction names a dropped fragment with absent or ambiguous identity",
                    "DROPPED_BY"))
        if token_state == "UNKNOWN":
            edges.append(_unknown(
                None, compaction_id,
                "dropped token count is absent or not a non-negative integer",
                "DROPPED_TOKEN_COUNT"))
            loss_state = "UNKNOWN"
        elif dropped:
            loss_state = "KNOWN" if len(known_dropped) == len(dropped) else "UNKNOWN"
        elif token_count and token_count > 0:
            edges.append(_unknown(
                None, compaction_id,
                "token loss is observed, but dropped fragment identities are unavailable",
                "DROPPED_BY"))
            loss_state = "UNKNOWN"
        else:
            loss_state = "NONE_OBSERVED"
        loss_records.append({"compaction_id": compaction_id,
                             "state": loss_state,
                             "dropped_tokens": token_count,
                             "dropped_tokens_state": token_state,
                             "fragment_ids": dropped})

    edges = _dedupe_edges(edges)
    unknown_n = sum(edge.get("type") == UNKNOWN_EDGE for edge in edges)
    unknown_nodes = sum(node.get("state") == "UNKNOWN" for node in nodes.values())
    known_dependencies = sum(edge.get("type") == "DEPENDS_ON" and
                             edge.get("state") == "KNOWN" for edge in edges)
    status = "UNKNOWN" if not decision_rows else (
        "PARTIAL" if unknown_n or unknown_nodes or unknown_context_classes
        else "COMPLETE")
    why = ("no decisions were supplied" if not decision_rows else
           "at least one identity, dependency, context class, or compression field is unknown"
           if status == "PARTIAL" else
           "all returned decision dependencies and compression losses are explicit")
    return {"version": CONTRACT_VERSION, "status": status, "why": why,
            "context_classes": list(CONTEXT_CLASSES),
            "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
            "edges": edges, "unknown_edges": unknown_n,
            "unknown_nodes": unknown_nodes,
            "unknown_context_classes": unknown_context_classes,
            "known_decision_dependencies": known_dependencies,
            "collisions": sorted(collisions,
                                 key=lambda item: (item["kind"], item["key"])),
            "provenance_collisions": provenance_collisions,
            "compression_loss": loss_records}
