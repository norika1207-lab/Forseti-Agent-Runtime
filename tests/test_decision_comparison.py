"""Gold owner-decision markers require actual prior decision evidence."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

from source_tree_schema import annotate_rows


def test_real_owner_change_gets_prior_decision_and_source_lines():
    rows = [
        {"n": 1, "owner_line": 10, "owner_text": "先做讀取原文的功能",
         "owner_message_kind": "NEW_REQUEST"},
        {"n": 2, "owner_line": 20, "owner_text": "好",
         "owner_message_kind": "ACKNOWLEDGEMENT"},
        {"n": 3, "owner_line": 30, "owner_text": "新的方向是先做完整封存",
         "owner_message_kind": "MIND_CHANGE"},
    ]
    annotate_rows(rows)
    comparison = rows[2]["decision_comparison"]
    assert comparison["state"] == "POSSIBLE_DIFFERENCE"
    assert comparison["epistemic"] == "INFERRED"
    assert comparison["baseline_n"] == 1
    assert comparison["baseline_source_ref"] == "line:10"
    assert comparison["evidence_source_ref"] == "line:30"
    assert "先做讀取原文" in comparison["baseline"]
    assert "新的方向" in comparison["evidence"]
    assert "decision_comparison" not in rows[0]
    assert "decision_comparison" not in rows[1]


def test_correction_does_not_masquerade_as_owner_direction_change():
    rows = [
        {"n": 1, "owner_text": "先做封存", "owner_message_kind": "NEW_REQUEST"},
        {"n": 2, "owner_text": "你根本沒做封存", "owner_message_kind": "CORRECTION",
         "owner_goal_change_candidate": True},
    ]
    annotate_rows(rows)
    assert "decision_comparison" not in rows[1]


def test_candidate_without_baseline_stays_unknown():
    rows = [{"n": 1, "owner_text": "新的方向是封存原文",
             "owner_goal_change_candidate": True}]
    annotate_rows(rows)
    assert "decision_comparison" not in rows[0]
