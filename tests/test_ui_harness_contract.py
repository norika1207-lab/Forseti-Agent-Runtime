import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _harness():
    path = ROOT / "tools" / "ui-harness.py"
    spec = importlib.util.spec_from_file_location("forseti_ui_harness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_render_fixture_adds_deterministic_rows_when_ledgers_are_empty():
    data = {"workflow": {"has": False, "resumable": []}}
    work = {"ok": True, "total": 0, "active": 0, "tasks": []}

    _harness()._stabilize_render_fixture(data, work)

    assert data["workflow"]["resumable"][0]["workflow_id"] == \
        "render-fixture-workflow"
    assert work["tasks"][0]["id"] == "render-fixture-task"
    assert work["tasks"][0]["next_step"]["objective"] == \
        "render the fixture"


def test_render_fixture_preserves_real_rows():
    real_workflow = {"workflow_id": "real-workflow"}
    real_task = {"id": "real-task"}
    data = {"workflow": {"has": True, "resumable": [real_workflow]}}
    work = {"ok": True, "total": 1, "active": 1, "tasks": [real_task]}

    _harness()._stabilize_render_fixture(data, work)

    assert data["workflow"]["resumable"] == [real_workflow]
    assert work["tasks"] == [real_task]
