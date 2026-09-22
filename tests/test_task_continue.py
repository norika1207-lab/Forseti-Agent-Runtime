import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "apps" / "forseti-cli"))

import ledger as L


def _running_step():
    tmp = Path(tempfile.mkdtemp())
    led = L.Ledger(db=tmp / "ledger.db", cwd=tmp)
    task_id = led.accept("restore stalled work", [
        L.Step("s1", "implement recovery", next_action="implement recovery now"),
    ])
    led.transition(task_id, "RUNNING", "authorized")
    step_id = led.sid(task_id, "s1")
    led.dispatch(step_id, "worker-a")
    return led, task_id, step_id


def test_active_command_is_never_interrupted():
    led, _task_id, step_id = _running_step()
    try:
        got = led.continue_if_stalled(
            step_id, command_running=True, activity_observed=False,
            stall_suspect=True)
        assert got["action"] == "WAIT_FOR_ACTIVITY"
        assert "CONTINUATION_REQUESTED" not in [e["kind"] for e in led.events_of(_task_id)]
    finally:
        led.close()


def test_stalled_authorized_step_emits_one_durable_original_input_request():
    led, task_id, step_id = _running_step()
    try:
        first = led.continue_if_stalled(
            step_id, command_running=False, activity_observed=False,
            stall_suspect=True)
        second = led.continue_if_stalled(
            step_id, command_running=False, activity_observed=False,
            stall_suspect=True)
        assert first["action"] == "RESEND_ORIGINAL_INPUT"
        assert first["original_input"] == "implement recovery now"
        assert second["action"] == "ALREADY_REQUESTED"
        events = [e for e in led.events_of(task_id) if e["kind"] == "CONTINUATION_REQUESTED"]
        assert len(events) == 1
        assert events[0]["payload"]["original_input"] == "implement recovery now"
    finally:
        led.close()


def test_delivery_packet_survives_ledger_reopen():
    led, task_id, step_id = _running_step()
    db = led.db_path
    try:
        first = led.continue_if_stalled(
            step_id, command_running=False, activity_observed=False,
            stall_suspect=True)
        event = [e for e in led.events_of(task_id)
                 if e["kind"] == "CONTINUATION_REQUESTED"][0]
        packet = event["payload"]
        assert packet["original_input"] == first["original_input"]
        assert packet["event_key"] == first["event_key"]
    finally:
        led.close()

    reopened = L.Ledger(db=db, cwd=db.parent)
    try:
        events = [e for e in reopened.events_of(task_id)
                  if e["kind"] == "CONTINUATION_REQUESTED"]
        assert len(events) == 1
        assert events[0]["payload"]["original_input"] == "implement recovery now"
    finally:
        reopened.close()


def test_blank_output_with_receipt_requests_synthesis_not_a_rerun():
    led, task_id, step_id = _running_step()
    try:
        led.receipt(step_id, "build", "exit 0")
        got = led.continue_if_stalled(
            step_id, command_running=False, activity_observed=False,
            stall_suspect=True, blank_run=1)
        assert got["action"] == "SYNTHESIS_ONLY"
        kinds = [e["kind"] for e in led.events_of(task_id)]
        assert "SYNTHESIS_REQUESTED" in kinds
        assert "CONTINUATION_REQUESTED" not in kinds
    finally:
        led.close()
