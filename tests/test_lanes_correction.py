import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import lanes  # noqa: E402


def test_correction_proxy_does_not_open_goal_drift_rail():
    rows = [
        {"n": 1, "goal": {"distance": 0.5, "klass": "CONFLICTING"},
         "corrected_by_owner": False},
        {"n": 2, "goal": {"distance": 0.5, "klass": "SUPPORTING"},
         "corrected_by_owner": True},
    ]
    result = lanes.lanes(rows)
    assert not any(lane["kind"] == "DRIFT" for lane in result)
    correction = next(lane for lane in result if lane["kind"] == "CORRECTION")
    assert (correction["from_n"], correction["to_n"], correction["open"]) == (1, 2, False)
    assert correction["event_link"] is True


def test_correction_lane_carries_that_owner_message():
    rows = [{"n": 8, "ai_text": "只做了 A"},
            {"n": 9, "corrected_by_owner": True,
             "owner_text": "你做反了，這次要的是 B"}]
    correction = lanes.lanes(rows)[0]
    assert correction["kind"] == "CORRECTION"
    assert correction["evidence"] == "你做反了，這次要的是 B"


def test_confirmed_claim_conflict_still_has_its_own_rail():
    rows = [{"n": 1, "betrayals": [{"target": "tracker.py"}], "write": 0},
            {"n": 2, "write": 0}]
    assert lanes.lanes(rows)[0]["kind"] == "BETRAYAL"
