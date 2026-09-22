import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

from desktop_adapter import DesktopAdapter  # noqa: E402
import ledger as L  # noqa: E402


def _adapter(tmp_path):
    led = L.Ledger(db=tmp_path / "ledger.db", cwd=tmp_path)
    task = led.accept("host continuation", [L.Step(
        "s1", "original work", next_action="run original action")])
    led.transition(task, "RUNNING", "authorized")
    step = led.sid(task, "s1")
    led.dispatch(step, "worker-a")
    led.close()
    return DesktopAdapter(db=tmp_path / "ledger.db", cwd=tmp_path,
                          step_id=step, target="exact-thread"), step


def test_adapter_requires_exact_permission_target_state_and_observation(tmp_path):
    adapter, _ = _adapter(tmp_path)
    try:
        cases = [
            ({"target": "exact-thread", "state": "ACTIVE", "observation_id": "a"}, "NO_ACCESSIBILITY"),
            ({"accessibility": True, "target": "wrong", "state": "ACTIVE", "observation_id": "a"}, "TARGET_MISMATCH"),
            ({"accessibility": True, "target": "exact-thread", "state": "WAITING", "observation_id": "a"}, "UNKNOWN_AX_STATE"),
            ({"accessibility": True, "target": "exact-thread", "state": "ACTIVE"}, "MISSING_OBSERVATION_ID"),
        ]
        for event, reason in cases:
            got = adapter.observe(event)
            assert got == {"action": "FAIL_CLOSED", "reason": reason}
    finally:
        adapter.close()


def test_adapter_never_invents_delivery_text_or_duplicates_packet(tmp_path):
    adapter, _ = _adapter(tmp_path)
    try:
        assert adapter.observe({"accessibility": True, "target": "exact-thread",
                                "state": "ACTIVE", "observation_id": "a1"})["action"] == "OBSERVED_ACTIVE"
        first = adapter.observe({"accessibility": True, "target": "exact-thread",
                                 "state": "IDLE", "observation_id": "i1"})
        assert first["action"] == "RESEND_ORIGINAL_INPUT"
        assert first["original_input"] == "run original action"
        assert "continue" not in first["original_input"].lower()
        assert adapter.observe({"accessibility": True, "target": "exact-thread",
                                "state": "IDLE", "observation_id": "i2"})["action"] == "FAIL_CLOSED"
    finally:
        adapter.close()


def test_controller_rejects_legacy_polling_flags_without_ui_access():
    proc = subprocess.run(
        [str(ROOT / "tools" / "codex-desktop-controller.sh"), "--interval", "10"],
        text=True, capture_output=True,
    )
    assert proc.returncode == 64
    assert "refusing legacy polling controller option: --interval" in proc.stderr


def test_controller_source_has_no_foreground_or_timer_delivery_code():
    source = (ROOT / "tools" / "codex-desktop-controller.sh").read_text(encoding="utf-8")
    forbidden = ("frontmost", "osascript", "cliclick", "setInterval", "sleep 10")
    assert not any(token in source for token in forbidden)
    assert 'exec python3 "$ROOT/apps/forseti-cli/desktop_adapter.py" "$@"' in source
