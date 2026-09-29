#!/usr/bin/env python3
"""Deterministic Claim/Evidence lineage explorer contract.

Duplicate IDs are grouped before projection.  Identical records are replay
duplicates; conflicting records become UNKNOWN collisions.  Missing relation
types, evidence basis, endpoint entities, and UNKNOWN endpoint nodes can never
produce a KNOWN edge or a COMPLETE contract.
"""

from __future__ import annotations

import hashlib
import json

CONTRACT_VERSION = "lineage-view@1"
UNKNOWN_EDGE = "UNKNOWN_EDGE"


def _rows(values) -> list[dict]:
    return [dict(value) for value in (values or []) if isinstance(value, dict)]


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


def _unknown(source: str | None, target: str | None, why: str,
             relation: str) -> dict:
    return {"type": UNKNOWN_EDGE, "relation": relation, "from": source,
            "to": target, "state": "UNKNOWN", "why": why}


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


def _fallback_id(kind: str, row: dict) -> str:
    return f"unknown-{kind}:" + _fingerprint(row)


def _group(rows: list[dict], kind: str) -> dict[str, list[dict]]:
    grouped: dict[str, dict[str, dict]] = {}
    for row in rows:
        node_id = str(row.get("id") or "").strip() or _fallback_id(kind, row)
        grouped.setdefault(node_id, {}).setdefault(_canonical(row), row)
    return {node_id: [variants[key] for key in sorted(variants)]
            for node_id, variants in sorted(grouped.items())}


def build(*, claims: list[dict] | None = None,
          evidence: list[dict] | None = None,
          lineage_edges: list[dict] | None = None,
          citations: list[dict] | None = None,
          rewrites: list[dict] | None = None,
          entities: list[dict] | None = None) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    collisions: list[dict] = []
    claim_groups = _group(_rows(claims), "claim")
    evidence_groups = _group(_rows(evidence), "evidence")

    for node_id, variants in claim_groups.items():
        collision = len(variants) > 1
        missing_identity = node_id.startswith("unknown-claim:")
        states = {str(row.get("state") or "UNKNOWN") for row in variants}
        state = next(iter(states)) if len(states) == 1 else "UNKNOWN"
        if collision or missing_identity:
            state = "UNKNOWN"
        nodes[node_id] = {"id": node_id, "kind": "claim", "state": state,
                          "label": (str(variants[0].get("text") or "")
                                    if len({str(row.get("text") or "")
                                            for row in variants}) == 1 else ""),
                          "source": "claims", "collision": collision,
                          "variant_fingerprints": [_fingerprint(row)
                                                   for row in variants]}
        if collision:
            collisions.append({"kind": "claim_id", "key": node_id,
                               "candidates": nodes[node_id]["variant_fingerprints"],
                               "state": "UNKNOWN"})
            edges.append(_unknown(node_id, None,
                                  "conflicting claim records share one ID",
                                  "IDENTITY_COLLISION"))
        elif missing_identity:
            edges.append(_unknown(None, node_id,
                                  "claim has no stable source ID", "IDENTITY"))

    for node_id, variants in evidence_groups.items():
        collision = len(variants) > 1
        missing_identity = node_id.startswith("unknown-evidence:")
        state = "UNKNOWN" if collision or missing_identity else "OBSERVED"
        nodes[node_id] = {"id": node_id, "kind": "evidence", "state": state,
                          "label": (str(variants[0].get("about") or "")
                                    if len({str(row.get("about") or "")
                                            for row in variants}) == 1 else ""),
                          "source": "evidence", "collision": collision,
                          "variant_fingerprints": [_fingerprint(row)
                                                   for row in variants]}
        if collision:
            collisions.append({"kind": "evidence_id", "key": node_id,
                               "candidates": nodes[node_id]["variant_fingerprints"],
                               "state": "UNKNOWN"})
            edges.append(_unknown(node_id, None,
                                  "conflicting evidence records share one ID",
                                  "IDENTITY_COLLISION"))
        elif missing_identity:
            edges.append(_unknown(None, node_id,
                                  "evidence has no stable source ID", "IDENTITY"))

    for node_id, variants in _group(_rows(entities), "entity").items():
        collision = len(variants) > 1
        states = {str(row.get("state") or "OBSERVED") for row in variants}
        state = next(iter(states)) if len(states) == 1 else "UNKNOWN"
        if collision or node_id.startswith("unknown-entity:"):
            state = "UNKNOWN"
        nodes.setdefault(node_id, {
            "id": node_id,
            "kind": (str(variants[0].get("kind") or "node")
                     if len({str(row.get("kind") or "node")
                             for row in variants}) == 1 else "node"),
            "state": state,
            "label": (str(variants[0].get("label") or "")
                      if len({str(row.get("label") or "")
                              for row in variants}) == 1 else ""),
            "source": (str(variants[0].get("source") or "entities")
                       if len({str(row.get("source") or "entities")
                               for row in variants}) == 1 else "entities"),
            "collision": collision,
            "variant_fingerprints": [_fingerprint(row) for row in variants]})
        if collision:
            collisions.append({"kind": "entity_id", "key": node_id,
                               "candidates": [_fingerprint(row) for row in variants],
                               "state": "UNKNOWN"})
            edges.append(_unknown(node_id, None,
                                  "conflicting entity records share one ID",
                                  "IDENTITY_COLLISION"))

    explicit_pairs: set[tuple[str, str, str]] = set()
    lineage_rows = sorted(_rows(lineage_edges), key=_canonical)
    for raw in lineage_rows:
        relation = str(raw.get("type") or raw.get("relation") or "").strip()
        source = str(raw.get("from_id") or raw.get("from") or "").strip()
        target = str(raw.get("to_id") or raw.get("to") or "").strip()
        basis = str(raw.get("basis") or "").strip()
        if not relation:
            edges.append(_unknown(
                source or None, target or None,
                "lineage edge has neither type nor relation",
                "UNKNOWN_RELATION"))
            continue
        source_node = nodes.get(source)
        target_node = nodes.get(target)
        if (source_node and target_node and basis and
                source_node.get("state") != "UNKNOWN" and
                target_node.get("state") != "UNKNOWN"):
            edges.append({"type": relation, "relation": relation,
                          "from": source, "to": target, "state": "KNOWN",
                          "basis": basis})
            explicit_pairs.add((relation, source, target))
        else:
            edges.append(_unknown(
                source or None, target or None,
                "lineage edge has an absent/UNKNOWN endpoint or no evidence basis",
                relation))

    for claim_id, variants in claim_groups.items():
        collision = len(variants) > 1 or nodes[claim_id].get("state") == "UNKNOWN"
        refs = sorted({ref for row in variants
                       for ref in _list(row.get("evidence_refs"))})
        for evidence_id in refs:
            if (("VERIFIES", evidence_id, claim_id) in explicit_pairs or
                    ("REFUTES", evidence_id, claim_id) in explicit_pairs):
                continue
            evidence_node = nodes.get(evidence_id)
            if collision or not evidence_node or evidence_node.get("state") == "UNKNOWN":
                edges.append(_unknown(
                    evidence_id, claim_id,
                    "claim or evidence identity is absent/ambiguous",
                    "REFERENCES_EVIDENCE"))
            else:
                edges.append({"type": "REFERENCES_EVIDENCE",
                              "relation": "REFERENCES_EVIDENCE",
                              "from": evidence_id, "to": claim_id,
                              "state": "KNOWN",
                              "basis": "claim.evidence_refs; polarity is not recorded"})

    for raw in sorted(_rows(citations), key=_canonical):
        claim_id = str(raw.get("claim_id") or "").strip()
        source_id = str(raw.get("source_id") or "").strip()
        basis = str(raw.get("basis") or "").strip()
        if source_id:
            nodes.setdefault(source_id, {"id": source_id, "kind": "source",
                                         "state": "OBSERVED", "label": "",
                                         "source": "citation record"})
        claim_node = nodes.get(claim_id)
        source_node = nodes.get(source_id)
        if (claim_node and claim_node.get("state") != "UNKNOWN" and
                source_node and source_node.get("state") != "UNKNOWN" and basis):
            edges.append({"type": "CITES", "relation": "CITES",
                          "from": claim_id, "to": source_id, "state": "KNOWN",
                          "basis": basis})
        else:
            edges.append(_unknown(
                claim_id or None, source_id or None,
                "citation has an absent/UNKNOWN claim, source, or basis", "CITES"))

    for raw in sorted(_rows(rewrites), key=_canonical):
        source = str(raw.get("from_claim_id") or "").strip()
        target = str(raw.get("to_claim_id") or "").strip()
        basis = str(raw.get("basis") or "").strip()
        source_node, target_node = nodes.get(source), nodes.get(target)
        if (source_node and target_node and basis and
                source_node.get("state") != "UNKNOWN" and
                target_node.get("state") != "UNKNOWN"):
            edges.append({"type": "REWRITES", "relation": "REWRITES",
                          "from": source, "to": target, "state": "KNOWN",
                          "basis": basis})
        else:
            edges.append(_unknown(
                source or None, target or None,
                "rewrite has an absent/UNKNOWN claim endpoint or no basis",
                "REWRITES"))

    edges = _dedupe_edges(edges)
    traces = []
    for claim_id in sorted(claim_groups):
        evidence_ids = sorted({edge["from"] for edge in edges
                               if edge.get("to") == claim_id and
                               edge.get("relation") in ("VERIFIES", "REFUTES",
                                                        "REFERENCES_EVIDENCE") and
                               edge.get("state") == "KNOWN"})
        citation_ids = sorted({edge["to"] for edge in edges
                               if edge.get("from") == claim_id and
                               edge.get("relation") == "CITES" and
                               edge.get("state") == "KNOWN"})
        rewritten_from = sorted({edge["from"] for edge in edges
                                 if edge.get("to") == claim_id and
                                 edge.get("relation") == "REWRITES" and
                                 edge.get("state") == "KNOWN"})
        if not evidence_ids:
            edges.append(_unknown(None, claim_id,
                                  "claim has no observed evidence lineage",
                                  "VERIFIES_OR_REFUTES"))
        traces.append({"claim_id": claim_id, "evidence_ids": evidence_ids,
                       "citation_source_ids": citation_ids,
                       "rewritten_from_claim_ids": rewritten_from})

    edges = _dedupe_edges(edges)
    unknown_n = sum(edge.get("type") == UNKNOWN_EDGE for edge in edges)
    unknown_nodes = sum(node.get("state") == "UNKNOWN" for node in nodes.values())
    claim_input_n = len(_rows(claims))
    status = "UNKNOWN" if not claim_input_n else (
        "PARTIAL" if unknown_n or unknown_nodes else "COMPLETE")
    why = ("no claims were supplied" if not claim_input_n else
           "at least one lineage endpoint, relation, or node remains unknown"
           if status == "PARTIAL" else
           "all returned claim, evidence, citation, and rewrite links are explicit")
    return {"version": CONTRACT_VERSION, "status": status, "why": why,
            "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
            "edges": edges, "unknown_edges": unknown_n,
            "unknown_nodes": unknown_nodes,
            "collisions": sorted(collisions,
                                 key=lambda item: (item["kind"], item["key"])),
            "traces": traces}
