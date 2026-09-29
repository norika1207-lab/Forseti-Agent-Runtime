from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import lineage_view as V


def claim(cid, evidence_refs=()):
    return {"id": cid, "text": cid, "state": "VERIFIED",
            "evidence_refs": list(evidence_refs)}


def evidence(eid):
    return {"id": eid, "about": eid}


def test_no_claims_is_unknown():
    result = V.build(evidence=[evidence("ev-1")])
    assert result["version"] == "lineage-view@1"
    assert result["status"] == "UNKNOWN"


def test_claim_evidence_reference_is_traceable():
    result = V.build(claims=[claim("cl-1", ["ev-1"])],
                     evidence=[evidence("ev-1")])
    trace = result["traces"][0]
    assert trace["claim_id"] == "cl-1"
    assert trace["evidence_ids"] == ["ev-1"]
    assert any(edge["type"] == "REFERENCES_EVIDENCE" for edge in result["edges"])
    assert not any(edge["type"] == "VERIFIES" for edge in result["edges"])
    assert result["unknown_edges"] == 0


def test_missing_evidence_is_unknown_not_synthetic_node():
    result = V.build(claims=[claim("cl-1", ["ev-missing"])])
    assert "ev-missing" not in {node["id"] for node in result["nodes"]}
    assert any(edge["type"] == "UNKNOWN_EDGE" and
               edge["from"] == "ev-missing" for edge in result["edges"])


def test_explicit_lineage_requires_both_endpoints_and_basis():
    result = V.build(
        claims=[claim("cl-1")], evidence=[evidence("ev-1")],
        lineage_edges=[{"type": "VERIFIES", "from_id": "ev-1",
                        "to_id": "cl-1", "basis": "stat receipt"}])
    assert any(edge["type"] == "VERIFIES" and edge["state"] == "KNOWN"
               for edge in result["edges"])
    assert result["traces"][0]["evidence_ids"] == ["ev-1"]


def test_citation_and_rewrite_are_in_claim_trace():
    result = V.build(
        claims=[claim("cl-old", ["ev-1"]), claim("cl-new", ["ev-1"])],
        evidence=[evidence("ev-1")],
        citations=[{"claim_id": "cl-new", "source_id": "doc:4",
                    "basis": "explicit citation"}],
        rewrites=[{"from_claim_id": "cl-old", "to_claim_id": "cl-new",
                   "basis": "revision record"}])
    trace = next(item for item in result["traces"] if item["claim_id"] == "cl-new")
    assert trace["citation_source_ids"] == ["doc:4"]
    assert trace["rewritten_from_claim_ids"] == ["cl-old"]


def test_promotes_without_hypothesis_entity_stays_unknown():
    result = V.build(
        claims=[claim("cl-1")],
        entities=[{"id": "owner", "kind": "authority"}],
        lineage_edges=[{"type": "PROMOTES", "from_id": "owner",
                        "to_id": "hyp-1", "basis": "owner decision"}])
    assert any(edge["type"] == "UNKNOWN_EDGE" and
               edge["relation"] == "PROMOTES" for edge in result["edges"])


def test_claim_without_id_is_visible_but_unknown():
    result = V.build(claims=[{"text": "no address"}])
    assert result["status"] == "PARTIAL"
    assert any(node["kind"] == "claim" and node["state"] == "UNKNOWN"
               for node in result["nodes"])
    assert any(edge["type"] == "UNKNOWN_EDGE" and
               edge["relation"] == "IDENTITY" for edge in result["edges"])


def test_reordered_inputs_produce_same_json():
    claims = [claim("cl-2", ["ev-2"]), claim("cl-1", ["ev-1"])]
    evidence_rows = [evidence("ev-2"), evidence("ev-1")]
    left = V.build(claims=claims, evidence=evidence_rows)
    right = V.build(claims=list(reversed(claims)),
                    evidence=list(reversed(evidence_rows)))
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def test_replayed_citation_does_not_duplicate_edge():
    citation = {"claim_id": "cl-1", "source_id": "doc:4", "basis": "quote"}
    result = V.build(claims=[claim("cl-1", ["ev-1"])],
                     evidence=[evidence("ev-1")],
                     citations=[citation, dict(citation)])
    cited = [edge for edge in result["edges"] if edge["type"] == "CITES"]
    assert len(cited) == 1
