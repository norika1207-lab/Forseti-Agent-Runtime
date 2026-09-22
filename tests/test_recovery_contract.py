import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "forseti-cli"))

import recovery_contract as RC


def test_dead_worker_preserves_results_and_never_auto_reruns():
    result = RC.assess(step_id="s1", worker_alive=False, has_receipts=True,
                       has_final_output=False, tool_calls=2)
    assert result["liveness"]["state"] == "DEAD_OR_UNKNOWN"
    assert result["output"]["failure_class"] == "OUTPUT_STARVATION"
    assert result["auto_rerun"] is False
    assert result["actions"][:3] == ["PRESERVE_RESULTS", "MARK_AVAILABILITY", "CHECKPOINT"]


def test_healthy_long_worker_does_not_trigger_recovery():
    result = RC.assess(step_id="s2", worker_alive=True, has_final_output=False,
                       tool_calls=1, progress_healthy=True)
    assert result["output"]["failure_class"] == "LONG_VALID_TASK"
    assert result["actions"] == []


def test_repeated_blank_output_can_be_recovered_without_rerun():
    result = RC.assess(step_id="s3", worker_alive=True, blank_run=2,
                       has_receipts=True, has_final_output=False, tool_calls=3)
    assert result["output"]["failure_class"] == "BLANK_OUTPUT_SEQUENCE"
    assert result["output"]["recoverable_without_rerun"] is True
    assert "SYNTHESIS_ONLY" in result["actions"]
