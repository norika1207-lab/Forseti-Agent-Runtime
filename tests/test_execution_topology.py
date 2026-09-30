from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import execution_topology as ET  # noqa: E402


def _node(graph, kind, source_id):
    return next(
        node for node in graph["nodes"]
        if node["kind"] == kind and node["source_id"] == source_id
    )


def _edge(graph, edge_type):
    return next(edge for edge in graph["edges"] if edge["type"] == edge_type)


def test_explicit_event_maps_agent_process_session_and_worldview():
    graph = ET.project([{
        "id": "evt-1",
        "type": "PROCESS_START",
        "agent_id": "agent-a",
        "session_id": "session-1",
        "runtime_node_id": "runtime-9",
        "metadata": {"process_id": "pid-44", "worldview_version": "goal-v3"},
    }])

    assert {node["kind"] for node in graph["nodes"]} == {
        "AGENT", "PROCESS", "RUNTIME_NODE", "SESSION", "WORLDVIEW_VERSION"
    }
    assert {edge["type"] for edge in graph["edges"]} == {
        "AGENT_IN_SESSION",
        "PROCESS_IN_SESSION",
        "AGENT_OPERATES_PROCESS",
        "PROCESS_ON_RUNTIME_NODE",
        "SESSION_USES_WORLDVIEW",
    }
    assert graph["coverage"] == {
        "events_seen": 1,
        "events_with_explicit_identity": 1,
        "events_skipped": 0,
        "known_edges": 5,
        "unknown_edges": 0,
    }


def test_persisted_ledger_norm_wrapper_and_object_are_supported():
    graph = ET.from_events([
        {"norm": {"id": "evt-norm", "session_id": "session-norm",
                  "metadata": {"goal_version": 2}}},
        SimpleNamespace(id="evt-object", agent_id="agent-a",
                        session_id="session-object"),
    ])
    assert _node(graph, "SESSION", "session-norm")
    assert _node(graph, "WORLDVIEW_VERSION", "2")
    assert _node(graph, "SESSION", "session-object")


def test_transcript_text_never_becomes_a_runtime_edge():
    graph = ET.project([{
        "id": "evt-text",
        "type": "MODEL_OUTPUT",
        "text": "agent-a spawned pid 42 in session-z using worldview 9",
        "action": "delegate agent-b to a new process",
        "subject": "agent-a",
        "object": "pid-42",
        "version": "9",
    }])
    assert graph["nodes"] == []
    assert graph["edges"] == []
    assert graph["coverage"]["events_skipped"] == 1
    assert "transcript text was not parsed" in graph["diagnostics"][0]["why"]


def test_generic_version_is_not_promoted_to_worldview():
    graph = ET.project([{
        "id": "evt-cli",
        "type": "SESSION_RESUME",
        "session_id": "session-1",
        "version": "claude-cli-3.2.1",
    }])
    assert {node["kind"] for node in graph["nodes"]} == {"SESSION"}
    assert graph["edges"] == []


def test_parent_relations_require_explicit_parent_fields():
    graph = ET.project([{
        "id": "evt-child",
        "agent_id": "child",
        "process_id": "pid-child",
        "metadata": {
            "parent_agent_id": "parent",
            "parent_process_id": "pid-parent",
        },
    }])
    delegated = _edge(graph, "DELEGATES_TO")
    spawned = _edge(graph, "SPAWNS")
    assert delegated["from"] == _node(graph, "AGENT", "parent")["id"]
    assert delegated["to"] == _node(graph, "AGENT", "child")["id"]
    assert spawned["from"] == _node(graph, "PROCESS", "pid-parent")["id"]
    assert spawned["to"] == _node(graph, "PROCESS", "pid-child")["id"]


def test_explicit_parent_without_child_stays_unknown():
    graph = ET.project([{
        "id": "evt-orphan",
        "session_id": "session-1",
        "metadata": {"parent_process_id": "pid-parent"},
    }])
    assert graph["known_edges"] == []
    assert graph["edges"] == graph["unknown_edges"]
    assert graph["unknown_edges"][0]["type"] == "UNKNOWN_EDGE"
    assert graph["unknown_edges"][0]["intended_type"] == "SPAWNS"
    assert graph["unknown_edges"][0]["to"] is None
    assert "child endpoint is missing" in graph["unknown_edges"][0]["unobservable_reason"]


def test_parent_only_event_is_unknown_not_silently_skipped():
    graph = ET.project([{
        "id": "evt-parent-only",
        "metadata": {"parent_agent_id": "agent-parent"},
    }])
    assert graph["nodes"] == []
    assert graph["edges"] == graph["unknown_edges"]
    assert graph["unknown_edges"][0]["type"] == "UNKNOWN_EDGE"
    assert graph["unknown_edges"][0]["intended_type"] == "DELEGATES_TO"
    assert graph["unknown_edges"][0]["to"] is None
    assert graph["diagnostics"] == []


def test_worldview_supersession_uses_dedicated_fields_only():
    graph = ET.project([{
        "id": "evt-goal-change",
        "session_id": "session-1",
        "metadata": {
            "north_star_version": "v4",
            "supersedes_worldview_version": "v3",
        },
    }])
    edge = _edge(graph, "SUPERSEDES")
    assert edge["from"] == _node(graph, "WORLDVIEW_VERSION", "v3")["id"]
    assert edge["to"] == _node(graph, "WORLDVIEW_VERSION", "v4")["id"]


def test_duplicate_observations_merge_without_duplicate_edges():
    graph = ET.project([
        {"id": "e1", "agent_id": "a", "session_id": "s"},
        {"id": "e2", "agent_id": "a", "session_id": "s"},
    ])
    assert len(graph["edges"]) == 1
    assert graph["edges"][0]["source_event_ids"] == ["e1", "e2"]
    assert _node(graph, "AGENT", "a")["source_event_ids"] == ["e1", "e2"]


def test_projection_is_deterministic_for_same_input():
    events = [{
        "id": "evt-1", "agent_id": "a", "session_id": "s",
        "metadata": {"process_id": "p", "worldview_version": "v1"},
    }]
    assert ET.build_topology(events) == ET.build_topology(events)


def test_malformed_event_is_recorded_unknown_not_crash():
    graph = ET.project(["not structured"])
    assert graph["coverage"]["events_seen"] == 1
    assert graph["nodes"] == []
    assert graph["diagnostics"][0]["state"] == "UNKNOWN"


def test_regression_unknown_runtime_edge_uses_p8_contract_exactly():
    graph = ET.project([{
        "id": "counterexample-p8",
        "metadata": {"parent_process_id": "process-parent"},
    }])
    edge = graph["unknown_edges"][0]
    assert edge["type"] == "UNKNOWN_EDGE"
    assert edge["intended_type"] == "SPAWNS"
    assert edge["unobservable_reason"]
    assert "why" not in edge


def test_regression_canonical_runtime_node_is_mapped_and_missing_is_unknown():
    graph = ET.project([
        {"id": "runtime-known", "process_id": "p1", "runtime_node_id": "node-a"},
        {"id": "runtime-missing", "process_id": "p2"},
        {"id": "runtime-wrong-place", "process_id": "p3",
         "metadata": {"runtime_node_id": "not-canonical"}},
    ])
    assert _node(graph, "RUNTIME_NODE", "node-a")
    assert any(edge["type"] == "PROCESS_ON_RUNTIME_NODE" for edge in graph["edges"])
    missing = [
        edge for edge in graph["unknown_edges"]
        if edge["intended_type"] == "PROCESS_ON_RUNTIME_NODE"
    ]
    assert len(missing) == 2
    assert all(edge["type"] == "UNKNOWN_EDGE" for edge in missing)
    assert all(edge["unobservable_reason"] for edge in missing)
    assert sum(d.get("field") == "runtime_node_id" for d in graph["diagnostics"]) == 3
