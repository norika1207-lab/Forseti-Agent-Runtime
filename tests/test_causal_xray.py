from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import causal_xray as X


def row(n, *, distance=0.0, failed=0, corrected=False, incident_id=""):
    return {"n": n, "goal": {"distance": distance}, "failed": failed,
            "corrected_by_owner": corrected, "incident_id": incident_id}


def test_empty_input_is_unknown_not_healthy_story():
    result = X.build([])
    assert result["version"] == "causal-xray@1"
    assert result["status"] == "UNKNOWN"
    assert result["nodes"] == []


def test_divergence_without_incident_preserves_unknown_edge():
    result = X.build([row(1), row(2, distance=0.5, failed=1)])
    assert result["status"] == "PARTIAL"
    assert result["unknown_edges"] >= 1
    assert any(edge["type"] == "UNKNOWN_EDGE" and
               edge["relation"] == "PROPAGATES_TO" for edge in result["edges"])


def test_explicit_incident_traces_transitive_downstream_impact():
    rows = [row(1), row(2, distance=0.5, failed=1,
                       corrected=True, incident_id="inc-1")]
    lineage = [
        {"type": "PROPAGATES_TO", "from_id": "inc-1", "to_id": "file:a.py",
         "to_kind": "artifact", "basis": "write receipt"},
        {"type": "PROPAGATES_TO", "from_id": "file:a.py", "to_id": "task:ship",
         "to_kind": "node", "basis": "task dependency"},
    ]
    result = X.build(rows, lineage_edges=lineage)
    known = [edge for edge in result["edges"]
             if edge["type"] == "PROPAGATES_TO"]
    assert [(edge["from"], edge["to"]) for edge in known] == [
        ("file:a.py", "task:ship"), ("inc-1", "file:a.py")]
    assert result["unknown_edges"] == 0
    assert result["status"] == "COMPLETE"


def test_temporal_adjacency_does_not_become_causality():
    result = X.build([row(1), row(2, distance=0.5, failed=1), row(3)])
    assert not any(edge.get("from") == "2" and edge.get("to") == "3"
                   for edge in result["edges"])


def test_missing_propagation_basis_stays_unknown():
    rows = [row(1, distance=0.5, failed=1, incident_id="inc-1")]
    result = X.build(rows, lineage_edges=[
        {"type": "PROPAGATES_TO", "from_id": "inc-1", "to_id": "file:a.py"}
    ])
    assert any(edge["type"] == "UNKNOWN_EDGE" and
               "basis" in edge["why"] for edge in result["edges"])


def test_missing_confirmed_and_consequential_anchors_keep_contract_partial():
    result = X.build([row(1, distance=0.5, incident_id="inc-1")],
                     lineage_edges=[{"type": "PROPAGATES_TO", "from_id": "inc-1",
                                     "to_id": "x", "basis": "receipt"}])
    assert result["unknown_anchors"] == 2
    assert result["status"] == "PARTIAL"


def test_json_contract_is_stable_for_reordered_input():
    rows = [row(2, distance=0.5, failed=1, incident_id="inc-1"), row(1)]
    edges = [{"type": "PROPAGATES_TO", "from_id": "inc-1", "to_id": "x",
              "basis": "receipt"}]
    left = X.build(rows, lineage_edges=edges)
    right = X.build(list(reversed(rows)), lineage_edges=list(reversed(edges)))
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def test_edge_sort_uses_basis_and_full_canonical_tie_break():
    rows = [row(1, distance=0.5, failed=1, corrected=True,
                incident_id="inc-1")]
    edges = [
        {"type": "PROPAGATES_TO", "from_id": "inc-1", "to_id": "x",
         "basis": "z-basis", "to_kind": "node", "id": "b"},
        {"type": "PROPAGATES_TO", "from_id": "inc-1", "to_id": "x",
         "basis": "a-basis", "to_kind": "artifact", "id": "a"},
    ]
    left = X.build(rows, lineage_edges=edges)
    right = X.build(rows, lineage_edges=list(reversed(edges)))
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
    known = [edge for edge in left["edges"]
             if edge["type"] == "PROPAGATES_TO"]
    assert [edge["basis"] for edge in known] == ["a-basis", "z-basis"]


def test_incident_without_propagation_is_explicit_unknown():
    result = X.build([row(1, distance=0.5, failed=1, corrected=True,
                          incident_id="inc-1")])
    assert result["status"] == "PARTIAL"
    assert any(edge["type"] == "UNKNOWN_EDGE" and edge["from"] == "inc-1" and
               "downstream impact is unknown" in edge["why"]
               for edge in result["edges"])
