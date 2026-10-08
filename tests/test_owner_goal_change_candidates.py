"""Owner direction changes are candidates, not automatic goal adoption."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import vitals


class OwnerGoalChangeCandidatesTests(unittest.TestCase):
    def test_explicit_new_direction_keeps_owner_evidence(self):
        rows = [{"n": 4, "owner_text": "新的方向是：先完成節點的因果鏈"}]
        self.assertEqual(vitals.owner_goal_change_candidates(rows), [{
            "n": 4,
            "kind": "OWNER_GOAL_CHANGE",
            "state": "CANDIDATE",
            "confidence": "HIGH",
            "evidence": rows[0]["owner_text"],
            "why": "owner used an explicit goal-change phrase",
        }])

    def test_exploratory_switch_does_not_adopt_goal(self):
        found = vitals.owner_goal_change_candidates([
            {"n": 5, "owner_text": "新的方向先試做這個旁支"},
            {"n": 6, "owner_text": "繼續"},
        ])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["kind"], "EXPLORATORY_BRANCH")
        self.assertEqual(found[0]["state"], "CANDIDATE")


if __name__ == "__main__":
    unittest.main()
