"""Durable Commander/Codex work-topology contracts."""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import work_topology as WT  # noqa: E402
import desktop_api as D  # noqa: E402


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _make_source(tmp_path: Path, rows: list[dict], turns: list[dict],
                 items: list[dict]):
    index = tmp_path / "session_index.jsonl"
    index.write_text("\n".join(json.dumps(row) for row in rows) + "\n",
                     encoding="utf-8")
    history = tmp_path / "thread_history.sqlite"
    con = sqlite3.connect(history)
    con.executescript("""
      CREATE TABLE thread_turns (
        thread_id TEXT, turn_id TEXT, rollout_ordinal INTEGER,
        status TEXT, started_at INTEGER, completed_at INTEGER
      );
      CREATE TABLE thread_items (
        thread_id TEXT, turn_id TEXT, item_id TEXT, rollout_ordinal INTEGER,
        created_at_ms INTEGER, item_json TEXT
      );
    """)
    con.executemany(
        "INSERT INTO thread_turns VALUES (?,?,?,?,?,?)",
        [(x["thread_id"], x["turn_id"], x["ordinal"], x["status"],
          x.get("started_at", 100), x.get("completed_at")) for x in turns],
    )
    con.executemany(
        "INSERT INTO thread_items VALUES (?,?,?,?,?,?)",
        [(x["thread_id"], x["turn_id"], x["item_id"], x["ordinal"],
          x.get("created_at_ms", x["ordinal"]), json.dumps(x["item"]))
         for x in items],
    )
    con.commit()
    con.close()
    return index, history


def test_active_completed_and_verifier_states_are_mapped(tmp_path):
    rows = [
        {"id": "worker-active", "thread_name": "Forseti Worker R3: active",
         "updated_at": _iso(1000)},
        {"id": "worker-done", "thread_name": "Forseti Worker R3: done",
         "updated_at": _iso(1000)},
        {"id": "verifier-running", "thread_name": "Forseti Verifier R3: running",
         "updated_at": _iso(1000)},
        {"id": "verifier-pass", "thread_name": "Forseti Verifier R3: pass",
         "updated_at": _iso(1000)},
    ]
    turns = [
        {"thread_id": "worker-active", "turn_id": "t1", "ordinal": 1,
         "status": "inProgress"},
        {"thread_id": "worker-done", "turn_id": "t2", "ordinal": 1,
         "status": "completed", "completed_at": 1000},
        {"thread_id": "verifier-running", "turn_id": "t3", "ordinal": 1,
         "status": "inProgress"},
        {"thread_id": "verifier-pass", "turn_id": "t4", "ordinal": 1,
         "status": "completed", "completed_at": 1000},
    ]
    items = [
        {"thread_id": "worker-active", "turn_id": "t1", "item_id": "i1",
         "ordinal": 1, "item": {"text": "FOR-R3-A\nCommit: `abcdef1`"}},
        {"thread_id": "verifier-pass", "turn_id": "t4", "item_id": "i2",
         "ordinal": 1, "item": {
             "type": "agentMessage", "phase": "final_answer",
             "delivery": {"candidate_commit": "abcdef1", "verdict": "PASS"},
             "text": "Candidate receipt delivered",
         }},
    ]
    index, history = _make_source(tmp_path, rows, turns, items)

    result = WT.topology(index_path=index, history_path=history, now=1000)
    assert result["available"] is True
    assert result["counts"] == {
        "total": 4, "active": 1, "verifying": 1, "completed": 2,
        "failed": 0, "blocked": 0, "unknown": 0,
    }
    by_id = {row["thread_id"]: row for row in result["items"]}
    assert by_id["worker-active"]["state"] == "ACTIVE"
    assert by_id["worker-active"]["candidate_commit"] == "abcdef1"
    assert by_id["worker-active"]["work_order_id"] == "FOR-R3-A"
    assert by_id["worker-done"]["state"] == "COMPLETED"
    assert by_id["verifier-running"]["state"] == "VERIFYING"
    assert by_id["verifier-pass"]["state"] == "COMPLETED"
    assert by_id["verifier-pass"]["verifier_verdict"] == "PASS"


def test_failed_and_blocked_are_not_counted_as_active(tmp_path):
    rows = [
        {"id": "failed", "thread_name": "Forseti Worker R3: failed",
         "updated_at": _iso(1000)},
        {"id": "blocked", "thread_name": "Forseti Worker R3: blocked",
         "updated_at": _iso(1000)},
        {"id": "verifier-fail", "thread_name": "Forseti Verifier R3: fail",
         "updated_at": _iso(1000)},
    ]
    turns = [
        {"thread_id": "failed", "turn_id": "t1", "ordinal": 1,
         "status": "failed"},
        {"thread_id": "blocked", "turn_id": "t2", "ordinal": 1,
         "status": "blocked"},
        {"thread_id": "verifier-fail", "turn_id": "t3", "ordinal": 1,
         "status": "completed", "completed_at": 1000},
    ]
    index, history = _make_source(tmp_path, rows, turns, [
        {"thread_id": "verifier-fail", "turn_id": "t3", "item_id": "i3",
         "ordinal": 1, "item": {
             "type": "agentMessage", "phase": "final_answer",
             "delivery": {"candidate_commit": "abcdef1", "verdict": "FAIL"},
             "text": "Candidate receipt delivered",
         }},
    ])
    result = WT.topology(index_path=index, history_path=history, now=1000)
    assert result["counts"]["active"] == 0
    assert result["counts"]["failed"] == 1
    assert result["counts"]["blocked"] == 1
    assert result["counts"]["completed"] == 1
    failed_verifier = next(x for x in result["items"]
                           if x["thread_id"] == "verifier-fail")
    assert failed_verifier["verifier_verdict"] == "FAIL"


def test_stale_active_record_becomes_unknown_with_reason(tmp_path):
    rows = [{"id": "old", "thread_name": "Forseti Worker R3: old",
             "updated_at": _iso(100)}]
    turns = [{"thread_id": "old", "turn_id": "t1", "ordinal": 1,
              "status": "inProgress", "started_at": 100}]
    index, history = _make_source(tmp_path, rows, turns, [])
    result = WT.topology(index_path=index, history_path=history,
                         now=100 + 25 * 60 * 60)
    item = result["items"][0]
    assert item["state"] == "UNKNOWN"
    assert item["stale"] is True
    assert "stale" in item["state_reason"]
    assert result["counts"]["active"] == 0
    assert result["counts"]["unknown"] == 1


def test_missing_connector_is_unavailable_not_zero(tmp_path):
    result = WT.topology(index_path=tmp_path / "missing-index.jsonl",
                         history_path=tmp_path / "missing-history.sqlite")
    assert result["available"] is False
    assert result["state"] == "UNKNOWN"
    assert result["counts"]["total"] is None
    assert result["counts"]["active"] is None
    assert result["authoritative_empty"] is False
    assert "unavailable" in result["reason"]


def test_malformed_connector_is_unavailable_not_authoritative_zero(tmp_path):
    index = tmp_path / "session_index.jsonl"
    index.write_text(json.dumps({
        "id": "valid", "thread_name": "Forseti Worker R3: valid",
        "updated_at": _iso(1000),
    }) + "\nnot-json\n", encoding="utf-8")
    history = tmp_path / "thread_history.sqlite"
    result = WT.topology(index_path=index, history_path=history)
    assert result["available"] is False
    assert result["counts"]["total"] is None
    assert result["authoritative_empty"] is False
    assert "mixed malformed" in result["reason"]


def test_malformed_thread_item_is_unknown_not_silently_skipped(tmp_path):
    rows = [{"id": "worker", "thread_name": "Forseti Worker R3: worker",
             "updated_at": _iso(1000)}]
    index, history = _make_source(tmp_path, rows, [
        {"thread_id": "worker", "turn_id": "t1", "ordinal": 1,
         "status": "completed", "completed_at": 1000},
    ], [])
    con = sqlite3.connect(history)
    con.execute("INSERT INTO thread_items VALUES (?,?,?,?,?,?)",
                ("worker", "t1", "bad", 2, 2, "not-json"))
    con.commit()
    con.close()
    result = WT.topology(index_path=index, history_path=history, now=1000)
    assert result["available"] is False
    assert result["state"] == "UNKNOWN"
    assert "malformed" in result["reason"]


def test_verdict_text_without_structured_final_receipt_stays_unknown(tmp_path):
    rows = [{"id": "verifier", "thread_name": "Forseti Verifier R3: text",
             "updated_at": _iso(1000)}]
    turns = [{"thread_id": "verifier", "turn_id": "t1", "ordinal": 1,
              "status": "completed", "completed_at": 1000}]
    index, history = _make_source(tmp_path, rows, turns, [
        {"thread_id": "verifier", "turn_id": "t1", "item_id": "i1",
         "ordinal": 1, "item": {
             "type": "agentMessage", "phase": "final_answer",
             "text": "The instructions mention PASS and FAIL, but no receipt was emitted.",
             "delivery": None,
         }},
    ])
    result = WT.topology(index_path=index, history_path=history, now=1000)
    item = result["items"][0]
    assert item["verifier_verdict"] is None
    assert item["verifier_verdict_reason"] == "no structured final receipt"


def test_empty_index_is_ambiguous_not_authoritative_zero(tmp_path):
    index = tmp_path / "session_index.jsonl"
    index.write_text("\n", encoding="utf-8")
    history = tmp_path / "thread_history.sqlite"
    result = WT.topology(index_path=index, history_path=history)
    assert result["available"] is False
    assert result["state"] == "UNKNOWN"
    assert result["counts"]["total"] is None


def test_authoritative_empty_source_is_the_only_zero(tmp_path):
    index, history = _make_source(tmp_path, [{"authoritative_empty": True}], [], [])
    result = WT.topology(index_path=index, history_path=history)
    assert result["available"] is True
    assert result["authoritative_empty"] is True
    assert result["counts"]["total"] == 0
    assert result["counts"]["active"] == 0


def test_provenance_uses_actual_configured_paths(tmp_path):
    rows = [{"id": "same", "thread_name": "Forseti Worker R3: same",
             "updated_at": _iso(1000)}]
    turns = [{"thread_id": "same", "turn_id": "t1", "ordinal": 1,
              "status": "completed", "completed_at": 1000}]
    index, history = _make_source(tmp_path, rows, turns, [])
    result = WT.topology(index_path=index, history_path=history, now=1000)
    source = result["items"][0]["source"]
    assert source["index"] == str(index)
    assert source["history"] == str(history)
    assert "~/.codex" not in json.dumps(source)


def test_duplicate_index_events_are_idempotent(tmp_path):
    row = {"id": "same", "thread_name": "Forseti Worker R3: same",
           "updated_at": _iso(1000)}
    index, history = _make_source(tmp_path, [row, dict(row)], [
        {"thread_id": "same", "turn_id": "t1", "ordinal": 1,
         "status": "completed", "completed_at": 1000},
    ], [])
    result = WT.topology(index_path=index, history_path=history, now=1000)
    assert result["counts"]["total"] == 1
    assert [x["thread_id"] for x in result["items"]] == ["same"]


def test_desktop_work_uses_authoritative_topology_when_task_ledger_is_empty(tmp_path,
                                                                            monkeypatch):
    topology = {
        "available": True,
        "state": "AVAILABLE",
        "reason": "fixture",
        "items": [
            {"thread_id": "worker-1", "work_order_id": None,
             "state": "ACTIVE", "role": "worker"},
            {"thread_id": "verifier-1", "work_order_id": None,
             "state": "VERIFYING", "role": "verifier"},
        ],
        "counts": {"total": 2, "active": 1, "verifying": 1,
                   "completed": 0, "failed": 0, "blocked": 0, "unknown": 0},
    }
    monkeypatch.setattr("ledger.default_db", lambda: tmp_path / "missing.db")
    monkeypatch.setattr("work_topology.topology", lambda: topology)
    result = D.work()
    assert result["ok"] is True
    assert result["total"] == 2
    assert result["active"] == 2
    assert result["topology"]["items"] == topology["items"]
    assert result["task_ledger"]["state"] == "UNKNOWN"


def test_desktop_work_does_not_turn_missing_sources_into_zero(tmp_path, monkeypatch):
    monkeypatch.setattr("ledger.default_db", lambda: tmp_path / "missing.db")
    monkeypatch.setattr("work_topology.topology", lambda: {
        "available": False, "state": "UNKNOWN", "reason": "connector missing",
        "items": [], "counts": {k: None for k in
                                   ("total", "active", "verifying", "completed",
                                    "failed", "blocked", "unknown")},
    })
    result = D.work()
    assert result["ok"] is False
    assert result["total"] is None
    assert result["active"] is None
    assert "connector" in result["topology"]["reason"]
