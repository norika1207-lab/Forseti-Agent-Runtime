#!/usr/bin/env python3
"""Deterministic Claim/Evidence lineage explorer contract.

Persisted lineage, claim evidence references, citations, and rewrites are
projected only when their endpoints are present.  Missing evidence and absent
PROMOTES entities stay visible as ``UNKNOWN_EDGE``.
"""

from __future__ import annotations

import hashlib
import json

CONTRACT_VERSION = "lineage-view@1"
UNKNOWN_EDGE = "UNKNOWN_EDGE"


def _rows(values) -> list[dict]:
    return [dict(value) for value in (values or []) if isinstance(value, dict)]


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
            str(edge.get("relation") or edge.get("type") or ""),
            str(edge.get("state") or ""), str(edge.get("basis") or ""))


def _dedupe_edges(edges: list[dict]) -> list[dict]:
    unique: dict[tuple, dict] = {}
    for edge in edges:
        key = (_edge_key(edge), str(edge.get("why") or ""))
        unique.setdefault(key, edge)
    return sorted(unique.values(), key=_edge_key)


def _fallback_id(kind: str, row: dict) -> str:
    raw = json.dumps(row, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str)
    return f"unknown-{kind}:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def build(*, claims: list[dict] | None = None,
          evidence: list[dict] | None = None,
          lineage_edges: list[dict] | None = None,
          citations: list[dict] | None = None,
          rewrites: list[dict] | None = None,
          entities: list[dict] | None = None) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    claim_rows = sorted(_rows(claims), key=lambda row: str(row.get("id") or ""))
    evidence_rows = sorted(_rows(evidence), key=lambda row: str(row.get("id") or ""))

    for row in claim_rows:
        node_id = str(row.get("id") or "").strip()
        observed = bool(node_id)
        node_id = node_id or _fallback_id("claim", row)
        nodes[node_id] = {"id": node_id, "kind": "claim",
                          "state": (str(row.get("state") or "UNKNOWN")
                                    if observed else "UNKNOWN"),
                          "label": str(row.get("text") or ""),
                          "source": "claims"}
        if not observed:
            edges.append(_unknown(None, node_id,
                                  "claim has no stable source ID", "IDENTITY"))
    for row in evidence_rows:
        node_id = str(row.get("id") or "").strip()
        observed = bool(node_id)
        node_id = node_id or _fallback_id("evidence", row)
        nodes[node_id] = {"id": node_id, "kind": "evidence",
                          "state": "OBSERVED" if observed else "UNKNOWN",
                          "label": str(row.get("about") or ""),
                          "source": "evidence"}
        if not observed:
            edges.append(_unknown(None, node_id,
                                  "evidence has no stable source ID", "IDENTITY"))
    for row in _rows(entities):
        node_id = str(row.get("id") or "").strip()
        if node_id:
            nodes.setdefault(node_id, {"id": node_id,
                                       "kind": str(row.get("kind") or "node"),
                                       "state": str(row.get("state") or "OBSERVED"),
                                       "label": str(row.get("label") or ""),
                                       "source": str(row.get("source") or "entities")})

    explicit_pairs: set[tuple[str, str, str]] = set()
    for raw in sorted(_rows(lineage_edges),
                      key=lambda row: (str(row.get("type") or ""),
                                       str(row.get("from_id") or ""),
                                       str(row.get("to_id") or ""))):
        relation = str(raw.get("type") or "UNKNOWN").strip()
        source = str(raw.get("from_id") or "").strip()
        target = str(raw.get("to_id") or "").strip()
        basis = str(raw.get("basis") or "").strip()
        if source in nodes and target in nodes and basis:
            edges.append({"type": relation, "relation": relation,
                          "from": source, "to": target, "state": "KNOWN",
                          "basis": basis})
            explicit_pairs.add((relation, source, target))
        else:
            edges.append(_unknown(
                source or None, target or None,
                "lineage edge is missing an endpoint entity or evidence basis",
                relation))

    for claim in claim_rows:
        claim_id = str(claim.get("id") or "").strip()
        if not claim_id:
            continue
        refs = _list(claim.get("evidence_refs"))
        for evidence_id in refs:
            if ("VERIFIES", evidence_id, claim_id) in explicit_pairs or \
                    ("REFUTES", evidence_id, claim_id) in explicit_pairs:
                continue
            if evidence_id in nodes:
                edges.append({"type": "REFERENCES_EVIDENCE",
                              "relation": "REFERENCES_EVIDENCE",
                              "from": evidence_id, "to": claim_id,
                              "state": "KNOWN",
                              "basis": "claim.evidence_refs; polarity is not recorded"})
            else:
                edges.append(_unknown(
                    evidence_id, claim_id,
                    "claim references evidence absent from the supplied evidence store",
                    "REFERENCES_EVIDENCE"))

    for raw in sorted(_rows(citations),
                      key=lambda row: (str(row.get("claim_id") or ""),
                                       str(row.get("source_id") or ""))):
        claim_id = str(raw.get("claim_id") or "").strip()
        source_id = str(raw.get("source_id") or "").strip()
        basis = str(raw.get("basis") or "").strip()
        if source_id:
            nodes.setdefault(source_id, {"id": source_id, "kind": "source",
                                         "state": "OBSERVED", "label": "",
                                         "source": "citation record"})
        if claim_id in nodes and source_id and basis:
            edges.append({"type": "CITES", "relation": "CITES",
                          "from": claim_id, "to": source_id, "state": "KNOWN",
                          "basis": basis})
        else:
            edges.append(_unknown(
                claim_id or None, source_id or None,
                "citation is missing a claim endpoint, source endpoint, or basis",
                "CITES"))

    for raw in sorted(_rows(rewrites),
                      key=lambda row: (str(row.get("from_claim_id") or ""),
                                       str(row.get("to_claim_id") or ""))):
        source = str(raw.get("from_claim_id") or "").strip()
        target = str(raw.get("to_claim_id") or "").strip()
        basis = str(raw.get("basis") or "").strip()
        if source in nodes and target in nodes and basis:
            edges.append({"type": "REWRITES", "relation": "REWRITES",
                          "from": source, "to": target, "state": "KNOWN",
                          "basis": basis})
        else:
            edges.append(_unknown(
                source or None, target or None,
                "rewrite is missing a claim endpoint or basis",
                "REWRITES"))

    edges = _dedupe_edges(edges)
    traces = []
    for claim_id in sorted(node_id for node_id, node in nodes.items()
                           if node.get("kind") == "claim"):
        evidence_ids = sorted({edge["from"] for edge in edges
                               if edge.get("to") == claim_id and
                               edge.get("relation") in ("VERIFIES", "REFUTES",
                                                        "REFERENCES_EVIDENCE") and
                               edge.get("state") == "KNOWN"})
        citations_out = sorted({edge["to"] for edge in edges
                                if edge.get("from") == claim_id and
                                edge.get("relation") == "CITES" and
                                edge.get("state") == "KNOWN"})
        rewritten_from = sorted({edge["from"] for edge in edges
                                 if edge.get("to") == claim_id and
                                 edge.get("relation") == "REWRITES" and
                                 edge.get("state") == "KNOWN"})
        if not evidence_ids:
            edges.append(_unknown(
                None, claim_id,
                "claim has no observed evidence lineage",
                "VERIFIES_OR_REFUTES"))
        traces.append({"claim_id": claim_id, "evidence_ids": evidence_ids,
                       "citation_source_ids": citations_out,
                       "rewritten_from_claim_ids": rewritten_from})

    edges = _dedupe_edges(edges)
    unknown_n = sum(edge.get("type") == UNKNOWN_EDGE for edge in edges)
    status = "UNKNOWN" if not claim_rows else (
        "PARTIAL" if unknown_n else "COMPLETE")
    why = ("no claims were supplied" if not claim_rows else
           "at least one claim lineage endpoint remains unknown" if unknown_n else
           "all returned claim, evidence, citation, and rewrite links are explicit")
    return {"version": CONTRACT_VERSION, "status": status, "why": why,
            "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
            "edges": edges, "unknown_edges": unknown_n,
            "traces": traces}
