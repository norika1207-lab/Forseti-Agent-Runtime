from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import context_mri as M


def fragment(fid, *, provenance="", context_class="HEALTHY_COLLABORATION_CONTEXT"):
    return {"id": fid, "provenance": provenance, "source": "ORIGINAL",
            "why": "decision dependency", "context_class": context_class}


def test_no_decisions_is_unknown():
    result = M.build(fragments=[fragment("f1")])
    assert result["version"] == "context-mri@1"
    assert result["status"] == "UNKNOWN"


def test_decision_explicitly_depends_on_original_fragment():
    result = M.build(decisions=[{"id": "d1", "fragment_refs": ["f1"]}],
                     fragments=[fragment("f1", provenance="session:turn-4")])
    assert result["status"] == "COMPLETE"
    assert result["known_decision_dependencies"] == 1
    assert any(edge["from"] == "d1" and edge["to"] == "f1" and
               edge["type"] == "DEPENDS_ON" for edge in result["edges"])


def test_provenance_reference_resolves_same_fragment():
    result = M.build(decisions=[{"id": "d1", "provenance_refs": ["session:turn-4"]}],
                     fragments=[fragment("f1", provenance="session:turn-4")])
    assert result["known_decision_dependencies"] == 1


def test_missing_decision_reference_is_unknown_edge():
    result = M.build(decisions=[{"id": "d1"}], fragments=[fragment("f1")])
    assert result["status"] == "PARTIAL"
    assert any(edge["type"] == "UNKNOWN_EDGE" and
               edge["relation"] == "DEPENDS_ON" for edge in result["edges"])


def test_numeric_compaction_loss_does_not_invent_lost_fragment():
    result = M.build(decisions=[{"id": "d1", "fragment_refs": ["f1"]}],
                     fragments=[fragment("f1")],
                     compactions=[{"id": "c1", "dropped_tokens": 500}])
    loss = result["compression_loss"][0]
    assert loss["state"] == "UNKNOWN"
    assert loss["fragment_ids"] == []
    assert any(edge["type"] == "UNKNOWN_EDGE" and
               edge["relation"] == "DROPPED_BY" for edge in result["edges"])


def test_explicit_compaction_difference_is_traceable():
    result = M.build(decisions=[{"id": "d1", "fragment_refs": ["f1"]}],
                     fragments=[fragment("f1"), fragment("f2")],
                     compactions=[{"id": "c1", "dropped_tokens": 20,
                                   "dropped_fragment_ids": ["f2"]}])
    assert any(edge["type"] == "DROPPED_BY" and edge["from"] == "f2" and
               edge["to"] == "c1" for edge in result["edges"])


def test_context_classes_remain_separate_and_unknown_is_not_coerced():
    result = M.build(decisions=[{"id": "d1", "fragment_refs": ["f1", "f2"]}],
                     fragments=[fragment("f1", context_class="CHAT_HISTORY"),
                                fragment("f2", context_class="not-a-class")])
    by_id = {node["id"]: node for node in result["nodes"]}
    assert by_id["f1"]["context_class"] == "CHAT_HISTORY"
    assert by_id["f2"]["context_class"] == "UNKNOWN"
    assert result["status"] == "PARTIAL"
    assert result["unknown_context_classes"] == 1


def test_fragment_without_stable_identity_cannot_be_known_dependency():
    result = M.build(decisions=[{"id": "d1",
                                 "fragment_refs": ["unknown-fragment:0"]}],
                     fragments=[{"text": "orphan", "source": "ORIGINAL",
                                 "context_class": "CHAT_HISTORY"}])
    assert result["known_decision_dependencies"] == 0
    assert any(edge["type"] == "UNKNOWN_EDGE" and
               edge["relation"] == "DEPENDS_ON" for edge in result["edges"])


def test_output_is_deterministic():
    decisions = [{"id": "d2", "fragment_refs": ["f2"]},
                 {"id": "d1", "fragment_refs": ["f1"]}]
    fragments = [fragment("f2"), fragment("f1")]
    left = M.build(decisions=decisions, fragments=fragments)
    right = M.build(decisions=list(reversed(decisions)),
                    fragments=list(reversed(fragments)))
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def test_replayed_decision_reference_does_not_duplicate_edge():
    result = M.build(decisions=[{"id": "d1", "fragment_refs": ["f1"]},
                                {"id": "d1", "fragment_refs": ["f1"]}],
                     fragments=[fragment("f1")])
    deps = [edge for edge in result["edges"] if edge["type"] == "DEPENDS_ON"]
    assert len(deps) == 1


def test_conflicting_duplicate_decision_id_is_unknown_and_order_independent():
    decisions = [{"id": "d1", "fragment_refs": ["f1"], "source": "a"},
                 {"id": "d1", "fragment_refs": ["f2"], "source": "b"}]
    fragments = [fragment("f1"), fragment("f2")]
    left = M.build(decisions=decisions, fragments=fragments)
    right = M.build(decisions=list(reversed(decisions)),
                    fragments=list(reversed(fragments)))
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
    decision = next(node for node in left["nodes"] if node["id"] == "d1")
    assert decision["state"] == "UNKNOWN"
    assert decision["collision"] is True
    assert left["known_decision_dependencies"] == 0
    assert any(item["kind"] == "decision_id" for item in left["collisions"])


def test_shared_provenance_is_ambiguous_not_last_write_wins():
    fragments = [fragment("f1", provenance="session:4"),
                 fragment("f2", provenance="session:4")]
    left = M.build(decisions=[{"id": "d1", "provenance_refs": ["session:4"]}],
                   fragments=fragments)
    right = M.build(decisions=[{"id": "d1", "provenance_refs": ["session:4"]}],
                    fragments=list(reversed(fragments)))
    assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)
    assert {node["id"] for node in left["nodes"]} >= {"f1", "f2"}
    assert left["known_decision_dependencies"] == 0
    assert left["provenance_collisions"] == [{
        "kind": "provenance", "key": "session:4",
        "candidates": ["f1", "f2"], "state": "UNKNOWN"}]


def test_invalid_dropped_tokens_is_unknown_not_zero_or_none_observed():
    result = M.build(decisions=[{"id": "d1", "fragment_refs": ["f1"]}],
                     fragments=[fragment("f1")],
                     compactions=[{"id": "c1", "dropped_tokens": "many"}])
    node = next(node for node in result["nodes"] if node["id"] == "c1")
    loss = result["compression_loss"][0]
    assert node["dropped_tokens"] is None
    assert node["dropped_tokens_state"] == "UNKNOWN"
    assert loss["state"] == "UNKNOWN"
    assert loss["state"] != "NONE_OBSERVED"
    assert any(edge["relation"] == "DROPPED_TOKEN_COUNT" and
               edge["state"] == "UNKNOWN" for edge in result["edges"])
