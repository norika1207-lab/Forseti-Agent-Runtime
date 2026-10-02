import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import desktop_api  # noqa: E402
import session_surface  # noqa: E402
import tracker  # noqa: E402
import vitals  # noqa: E402


def _write(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def test_codex_tracker_reads_owner_assistant_and_tool(tmp_path):
    transcript = tmp_path / ".codex" / "sessions" / "2026" / "09" / "x.jsonl"
    _write(transcript, [
        {"timestamp": "2026-09-29T05:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text": "請修好拖曳"}]}},
        {"timestamp": "2026-09-29T05:00:01Z", "type": "response_item",
         "payload": {"type": "custom_tool_call", "id": "t1", "call_id": "c1",
                     "name": "exec", "input": "ignored"}},
        {"timestamp": "2026-09-29T05:00:02Z", "type": "response_item",
         "payload": {"type": "custom_tool_call_output", "id": "o1",
                     "call_id": "c1", "output": []}},
        {"timestamp": "2026-09-29T05:00:03Z", "type": "response_item",
         "payload": {"type": "message", "id": "a1", "role": "assistant",
                     "content": [{"type": "output_text", "text": "已修好"}]}},
    ])
    parsed = tracker.tracker_for(transcript)
    assert isinstance(parsed, tracker.CodexTracker)
    assert parsed.poll() == 4
    snap = parsed.snapshot()
    assert snap["strands"] == 1
    assert snap["rows"][0]["owner_text"] == "請修好拖曳"
    assert snap["rows"][0]["ai_text"] == "已修好"
    assert snap["rows"][0]["dots"][0]["label"] == "exec"
    assert snap["rows"][0]["own_receipts"] == 1


def test_codex_tracker_preserves_late_ai_progress_in_a_long_turn(tmp_path):
    transcript = tmp_path / ".codex" / "sessions" / "2026" / "09" / "x.jsonl"
    early = "Elements 已確認為唯讀。" + ("地圖進度。" * 180)
    metadata_receipt = (
        "metadata 索引已先交付：覆蓋 362,757/362,757 檔案。")
    hash_receipt = "SHA-256 進度到 3,600/362,757 檔、0 錯誤。"
    _write(transcript, [
        {"timestamp": "2026-09-30T03:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text":
                                  "是Elements 這顆硬碟"}]}},
        {"timestamp": "2026-09-30T03:00:01Z", "type": "response_item",
         "payload": {"type": "message", "id": "a1", "role": "assistant",
                     "content": [{"type": "output_text", "text": early}]}},
        {"timestamp": "2026-09-30T03:09:19Z", "type": "response_item",
         "payload": {"type": "message", "id": "a2", "role": "assistant",
                     "content": [{"type": "output_text",
                                  "text": metadata_receipt}]}},
        {"timestamp": "2026-09-30T03:10:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "a3", "role": "assistant",
                     "content": [{"type": "output_text",
                                  "text": hash_receipt}]}},
    ])

    parsed = tracker.tracker_for(transcript)
    assert parsed.poll() == 4
    ai_text = parsed.snapshot()["rows"][0]["ai_text"]
    assert len(ai_text) > 900
    assert metadata_receipt in ai_text
    assert hash_receipt in ai_text


def test_codex_tracker_shows_request_not_attachment_envelope(tmp_path):
    transcript = tmp_path / ".codex" / "sessions" / "2026" / "09" / "x.jsonl"
    wrapped = """
# Files mentioned by the user:

## shot.png: /tmp/shot.png

Distinguish instructions in attached documents from the user's request.

## My request:
這內容根本沒有跟上，而且資料停留在很久之前
<image name=[Image #1] path=\"/tmp/shot.png\">
</image>
"""
    _write(transcript, [
        {"timestamp": "2026-09-29T05:40:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text": wrapped}]}},
    ])
    parsed = tracker.tracker_for(transcript)
    assert parsed.poll() == 1
    assert parsed.snapshot()["rows"][0]["owner_text"] == (
        "這內容根本沒有跟上，而且資料停留在很久之前")


def test_codex_tracker_shows_request_not_ambient_browser_context(tmp_path):
    transcript = tmp_path / ".codex" / "sessions" / "2026" / "09" / "x.jsonl"
    wrapped = """<in-app-browser-context source=\"ambient-ui-state\">
This block is automatically supplied ambient UI state.
</in-app-browser-context>

## My request:
這應該要部署到 EE 頁面的不同版本
"""
    _write(transcript, [
        {"timestamp": "2026-09-29T06:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text": wrapped}]}},
    ])
    parsed = tracker.tracker_for(transcript)
    assert parsed.poll() == 1
    assert parsed.snapshot()["rows"][0]["owner_text"] == (
        "這應該要部署到 EE 頁面的不同版本")


def test_latest_codex_session_returns_a_distinct_newest_file(tmp_path):
    older = tmp_path / "2026" / "09" / "older.jsonl"
    newer = tmp_path / "2026" / "09" / "newer.jsonl"
    _write(older, [{"type": "response_item", "payload": {}}])
    _write(newer, [{"type": "response_item", "payload": {}}])
    older.touch()
    newer.touch()
    older_mtime = older.stat().st_mtime - 10
    import os
    os.utime(older, (older_mtime, older_mtime))
    assert desktop_api._latest_codex_session(tmp_path) == newer


def test_native_watcher_includes_both_session_providers():
    source = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text()
    assert 'home.join(".claude/projects")' in source
    assert 'home.join(".codex/sessions")' in source
    assert 'home.join("Library/Logs/com.openai.codex")' in source
    assert "spawn_codex_focus_watcher(app.handle().clone())" in source
    assert "thread_stream_view_activity_changed active=true" in source


def test_codex_foreground_switch_beats_stale_deploy_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    stale = "01a0c213-35e3-7053-95fc-36a449c5d676"
    focused = "01a0d313-019d-7413-be90-99e70e8e2906"
    for sid in (stale, focused):
        _write(tmp_path / ".codex" / "sessions" / "2026" / "09"
               / f"rollout-2026-09-29T00-00-00-{sid}.jsonl",
               [{"type": "response_item", "payload": {}}])
    hint = tmp_path / ".forseti" / "current-session-id"
    hint.parent.mkdir(parents=True)
    hint.write_text(stale, encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "codex.log").write_text(
        "2026-09-29T01:00:00.000Z info [electron-message-handler] "
        "thread_stream_view_activity_changed active=true "
        f"conversationId={stale} rendererWebContentsId=1 "
        "rendererWindowAppearance=primary rendererWindowFocused=true "
        "rendererWindowId=1 rendererWindowVisible=true\n"
        "2026-09-29T02:00:00.000Z info [electron-message-handler] "
        "thread_stream_view_activity_changed active=true "
        f"conversationId={focused} rendererWebContentsId=1 "
        "rendererWindowAppearance=primary rendererWindowFocused=true "
        "rendererWindowId=1 rendererWindowVisible=true\n",
        encoding="utf-8")

    assert session_surface.latest_codex_focused_session(logs) == focused
    assert focused in session_surface.resolve_requested("", logs_root=logs).name


def test_codex_sidebar_owner_sync_beats_previous_activity_event(tmp_path):
    previous = "01a0f665-8995-7dd1-bebf-eb1ec7c58137"
    selected = "01a0c213-35e3-7053-95fc-36a449c5d676"
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "codex.log").write_text(
        "2026-10-01T07:37:24.830Z info [electron-message-handler] "
        "thread_stream_view_activity_changed active=true "
        f"conversationId={previous} rendererWebContentsId=1 "
        "rendererWindowAppearance=primary rendererWindowFocused=true "
        "rendererWindowId=1 rendererWindowVisible=true\n"
        "2026-10-01T07:37:53.105Z info [electron-message-handler] "
        "IAB_LIFECYCLE received browser sidebar owner sync browserTabId=null "
        f"conversationId={selected} originWebContentsId=1 "
        f"ownerRoutePath=/local/{selected} windowId=1\n",
        encoding="utf-8")

    assert session_surface.latest_codex_focused_session(logs) == selected


def test_codex_sidebar_route_wins_when_conversation_id_is_temporary(tmp_path):
    previous = "01a0c213-35e3-7053-95fc-36a449c5d676"
    selected = "01a0c714-dc99-7a81-ac98-01be9468df50"
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "codex.log").write_text(
        "2026-10-01T07:50:21.169Z info [electron-message-handler] "
        "IAB_LIFECYCLE received browser sidebar owner sync browserTabId=null "
        f"conversationId={previous} originWebContentsId=1 "
        f"ownerRoutePath=/local/{previous} windowId=1\n"
        "2026-10-01T07:50:42.783Z info [electron-message-handler] "
        "IAB_LIFECYCLE received browser sidebar owner sync browserTabId=null "
        "conversationId=client-new-thread:66ef7b0f-388a-4344-a55e-144e059ab817 "
        f"originWebContentsId=1 ownerRoutePath=/local/{selected} windowId=1\n",
        encoding="utf-8")

    assert session_surface.latest_codex_focused_session(logs) == selected


def test_fast_surface_preserves_every_turn_and_full_owner_text(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "01a0-full-transcript"
    transcript = (tmp_path / ".codex" / "sessions" / "2026" / "10"
                  / f"rollout-{sid}.jsonl")
    long_text = "完整內容" * 250
    records = []
    for n in range(195):
        text = long_text if n == 0 else f"使用者訊息 {n}"
        records.append({
            "timestamp": f"2026-10-01T00:{n // 60:02d}:{n % 60:02d}Z",
            "type": "response_item",
            "payload": {"type": "message", "id": f"u{n}", "role": "user",
                        "content": [{"type": "input_text", "text": text}]},
        })
        records.append({
            "timestamp": f"2026-10-01T00:{n // 60:02d}:{n % 60:02d}Z",
            "type": "response_item",
            "payload": {"type": "message", "id": f"a{n}",
                        "role": "assistant",
                        "content": [{"type": "output_text",
                                     "text": f"AI 回覆 {n}"}]},
        })
    _write(transcript, records)

    assert session_surface.main(["session_surface.py", sid]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["strands"] == 195
    assert data["shown"] == data["strands"]
    assert len(data["rows"]) == 195
    assert data["rows"][0]["owner_text"] == long_text
    assert data["rows"][-1]["owner_text"] == "使用者訊息 194"


def test_fast_surface_keeps_problem_branch_lanes(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "01a0-branch-lanes"
    transcript = (tmp_path / ".codex" / "sessions" / "2026" / "10"
                  / f"rollout-{sid}.jsonl")
    records = []
    for n in range(3):
        records.extend([
            {"timestamp": f"2026-10-01T00:00:0{n}Z",
             "type": "response_item",
             "payload": {"type": "message", "id": f"u{n}", "role": "user",
                         "content": [{"type": "input_text",
                                      "text": f"請先檢查資料 {n}"}]}},
            {"timestamp": f"2026-10-01T00:00:0{n}Z",
             "type": "response_item",
             "payload": {"type": "custom_tool_call", "id": f"t{n}",
                         "call_id": f"t{n}", "name": "Read",
                         "input": {"path": f"file-{n}"}}},
        ])
    _write(transcript, records)

    assert session_surface.main(["session_surface.py", sid]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["lanes"]["total"] >= 1
    assert any(item["kind"] == "BLIND_WRITE"
               for item in data["lanes"]["lanes"])
    assert "goal_gate" in data
    assert "drift_alerts" in data
    assert "divergence" in data
    assert "latency" in data
    assert "notes" in data
    assert "checkpoints" in data
    drift_events = [e for lane in data["lanes"]["lanes"]
                    if lane["kind"] == "DRIFT"
                    for e in lane.get("events", [])]
    for event in drift_events:
        assert event.get("why")


def test_overlapping_same_kind_findings_share_one_visual_lane():
    rows = [
        {"n": 1, "betrayals": [{"why": "first"}], "write": 0},
        {"n": 2, "betrayals": [{"why": "second"}], "write": 0},
        {"n": 3, "betrayals": [], "write": 0},
    ]
    merged = session_surface.lanes.lanes(rows)
    betrayal_lanes = [x for x in merged if x["kind"] == "BETRAYAL"]
    assert len(betrayal_lanes) == 1
    assert betrayal_lanes[0]["from_n"] == 1
    assert betrayal_lanes[0]["to_n"] == 3
    assert betrayal_lanes[0]["issues"] == 2
    assert [e["why"] for e in betrayal_lanes[0]["events"]] == ["first", "second"]
    assert [e["n"] for e in betrayal_lanes[0]["events"]] == [1, 2]


def test_lane_issue_count_counts_findings_not_only_turns():
    rows = [
        {"n": 1, "betrayals": [{"why": "first"}, {"why": "second"}], "write": 0},
        {"n": 2, "betrayals": [], "write": 0},
    ]
    betrayal_lane = next(x for x in session_surface.lanes.lanes(rows)
                         if x["kind"] == "BETRAYAL")
    assert betrayal_lane["issues"] == 2
    assert len(betrayal_lane["events"]) == 2


def test_drift_lane_nodes_keep_each_turns_judgment_and_direction():
    rows = [
        {"n": 1, "goal": {"support": .8, "distance": .2, "coverage": .5},
         "path_semantics": {"label": "可能偏離", "why": "第一輪理由", "evidence": "第一輪證據"},
         "active_goal_version": 3, "active_goal_objective": "方向甲"},
        {"n": 2, "goal": {"support": .6, "distance": .4, "coverage": .9},
         "path_semantics": {"label": "確認偏離", "why": "第二輪理由", "evidence": "第二輪證據"},
         "active_goal_version": 4, "active_goal_objective": "方向乙"},
    ]
    drift_lane = next(x for x in session_surface.lanes.lanes(rows)
                      if x["kind"] == "DRIFT")
    assert [e["n"] for e in drift_lane["events"]] == [1, 2]
    assert [e["why"] for e in drift_lane["events"]] == ["第一輪理由", "第二輪理由"]
    assert [e["objective"] for e in drift_lane["events"]] == ["方向甲", "方向乙"]
    assert [e["distance"] for e in drift_lane["events"]] == [.2, .4]
    first, second = drift_lane["events"]
    assert first["chain"]["relation"] == "DEPARTS_BASELINE"
    assert first["chain"]["next_n"] == 2
    assert second["chain"]["previous_n"] == 1
    assert second["chain"]["relation"] == "DIRECTION_CHANGED"
    assert second["chain"]["epistemic"] == "OBSERVED_OWNER_DIRECTION"
    assert all(e["chain"]["current"] == e["why"] for e in (first, second))


def test_drift_chain_marks_temporal_continuation_as_inferred_not_proven_cause():
    rows = [
        {"n": 4, "goal": {"support": .8, "distance": .2, "coverage": .5},
         "path_semantics": {"why": "開始偏離"}, "active_goal_version": 2},
        {"n": 5, "goal": {"support": .7, "distance": .3, "coverage": .6},
         "path_semantics": {"why": "偏離擴大"}, "active_goal_version": 2,
         "corrected_by_owner": True},
    ]
    drift = next(x for x in session_surface.lanes.lanes(rows) if x["kind"] == "DRIFT")
    chain = drift["events"][1]["chain"]
    assert chain["relation"] == "CONTINUES_DRIFT"
    assert chain["epistemic"] == "INFERRED_SEQUENCE_NOT_CAUSAL_PROOF"
    assert "增加 10 個百分點" in chain["predecessor"]
    assert "使用者在本輪出手糾正" in chain["consequence"]


def test_non_drift_lane_nodes_keep_structured_per_turn_activity():
    rows = [
        {"n": 1, "read": 2, "write": 0, "failed": 1, "goal": {"distance": 0}},
        {"n": 2, "read": 4, "write": 0, "failed": 2, "goal": {"distance": 0}},
        {"n": 3, "read": 1, "write": 0, "failed": 0, "goal": {"distance": 0}},
    ]
    got = session_surface.lanes.lanes(rows)
    tool = next(x for x in got if x["kind"] == "TOOL_FAIL")
    blind = next(x for x in got if x["kind"] == "BLIND_WRITE")
    assert [(e["n"], e["failed"]) for e in tool["events"]] == [(1, 1), (2, 2)]
    assert [(e["n"], e["read"], e["write"]) for e in blind["events"]] == [
        (1, 2, 0), (2, 4, 0), (3, 1, 0)]


def test_fast_surface_pins_current_session_and_never_paints_unknown_as_aligned(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "01a0-current"
    transcript = (tmp_path / ".codex" / "sessions" / "2026" / "09"
                  / f"rollout-{sid}.jsonl")
    _write(transcript, [
        {"timestamp": "2026-09-29T05:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text": "改成新的方向"}]}},
    ])
    hint = tmp_path / ".forseti" / "current-session-id"
    hint.parent.mkdir(parents=True)
    hint.write_text(sid, encoding="utf-8")

    assert session_surface.main(["session_surface.py"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["session"].endswith(sid)
    assert data["picked_by"] == "鎖定 Codex Session"
    assert data["rows"][0]["path_semantics"]["state"] == "direction_candidate"
    assert data["rows"][0]["active_goal_version"] == 2
    assert data["rows"][0]["active_goal_objective"] == "改成新的方向"
    assert data["rows"][0]["active_goal_from_n"] == 1
    assert data["rows"][0]["direction_decision"]["epistemic"] == "OBSERVED_OWNER_TEXT"
    assert data["semantic_surface"]["unknown_is_not_aligned"] is True


def test_fast_surface_preserves_historical_owner_direction_per_turn(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "01a0-direction-history"
    transcript = (tmp_path / ".codex" / "sessions" / "2026" / "09"
                  / f"rollout-{sid}.jsonl")
    _write(transcript, [
        {"timestamp": "2026-09-29T05:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text": "先檢查資料"}]}},
        {"timestamp": "2026-09-29T05:00:01Z", "type": "response_item",
         "payload": {"type": "message", "id": "u2", "role": "user",
                     "content": [{"type": "input_text", "text": "改成先修復節點"}]}},
        {"timestamp": "2026-09-29T05:00:02Z", "type": "response_item",
         "payload": {"type": "message", "id": "u3", "role": "user",
                     "content": [{"type": "input_text", "text": "繼續驗證"}]}},
    ])
    hint = tmp_path / ".forseti" / "current-session-id"
    hint.parent.mkdir(parents=True)
    hint.write_text(sid, encoding="utf-8")

    assert session_surface.main(["session_surface.py"]) == 0
    data = json.loads(capsys.readouterr().out)
    before, changed, inherited = data["rows"]
    assert before["active_goal_version"] == 1
    assert before["active_goal_objective"] == ""
    assert changed["active_goal_version"] == 2
    assert changed["active_goal_objective"] == "改成先修復節點"
    assert changed["active_goal_from_n"] == changed["n"]
    assert changed["path_semantics"]["state"] == "new_direction"
    assert inherited["active_goal_version"] == 2
    assert inherited["active_goal_objective"] == "改成先修復節點"
    assert inherited["active_goal_from_n"] == changed["n"]


def test_fast_surface_evaluates_ai_output_and_attributes_drift_to_ai(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "01a0-ai-output"
    transcript = (tmp_path / ".codex" / "sessions" / "2026" / "09"
                  / f"rollout-{sid}.jsonl")
    _write(transcript, [
        {"timestamp": "2026-09-29T05:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text": "請建立 `missing.json`"}]}},
        {"timestamp": "2026-09-29T05:00:01Z", "type": "response_item",
         "payload": {"type": "message", "id": "a1", "role": "assistant",
                     "content": [{"type": "output_text", "text": "我已經寫好 `missing.json`。"}]}},
    ])
    hint = tmp_path / ".forseti" / "current-session-id"
    hint.parent.mkdir(parents=True)
    hint.write_text(sid, encoding="utf-8")

    assert session_surface.main(["session_surface.py"]) == 0
    data = json.loads(capsys.readouterr().out)
    row = data["rows"][0]
    assert row["ai_text"] == "我已經寫好 `missing.json`。"
    assert row["betrayals"][0]["kind"] == "SAID_WROTE_DIDNT"
    assert row["path_semantics"]["state"] == "confirmed"
    assert row["path_semantics"]["actor"] == "AI"


def test_fast_surface_owner_correction_marks_the_previous_ai_turn_red(
        tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "01a0-owner-correction"
    transcript = (tmp_path / ".codex" / "sessions" / "2026" / "09"
                  / f"rollout-{sid}.jsonl")
    _write(transcript, [
        {"timestamp": "2026-09-29T05:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text": "檢查 AI 回答是否偏離"}]}},
        {"timestamp": "2026-09-29T05:00:01Z", "type": "response_item",
         "payload": {"type": "message", "id": "a1", "role": "assistant",
                     "content": [{"type": "output_text", "text": "我只顯示使用者輸入。"}]}},
        {"timestamp": "2026-09-29T05:00:02Z", "type": "response_item",
         "payload": {"type": "message", "id": "u2", "role": "user",
                     "content": [{"type": "input_text",
                                  "text": "你根本做反了，我要的是檢查 AI 回答"}]}},
    ])
    hint = tmp_path / ".forseti" / "current-session-id"
    hint.parent.mkdir(parents=True)
    hint.write_text(sid, encoding="utf-8")

    assert session_surface.main(["session_surface.py"]) == 0
    data = json.loads(capsys.readouterr().out)
    first, correction = data["rows"]
    assert first["path_semantics"]["state"] == "confirmed"
    assert first["path_semantics"]["actor"] == "AI"
    assert correction["corrected_by_owner"] is True
    assert correction["path_semantics"]["actor"] == "未歸因"
    assert correction.get("owner_goal_change_candidate") is not True


@pytest.mark.parametrize("case", range(100))
def test_four_round_direction_attribution_matrix(case, tmp_path, monkeypatch, capsys):
    """100 four-round sessions must not blame an explicit owner direction change."""
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = f"01a0-four-round-{case:03d}"
    transcript = (tmp_path / ".codex" / "sessions" / "2026" / "10"
                  / f"rollout-{sid}.jsonl")
    items = []
    for turn in range(1, 5):
        owner_text = f"沿用原方向檢查資料，第 {turn} 輪"
        ai_text = f"已完成原方向第 {turn} 輪檢查"
        if turn == 4 and case < 25:
            owner_text = f"改成新的方向：只檢查建議卡資料路徑，案例 {case}"
            ai_text = "收到，改依新的方向檢查建議卡資料路徑"
        elif turn == 4 and case < 50:
            owner_text = "你上一輪做反了，我要的是檢查原方向，不是換方向"
            ai_text = "收到，這是對上一輪的糾正"
        elif turn == 4 and case < 75:
            owner_text = "繼續原方向並提供實際證據"
            ai_text = f"我已經寫好 `missing-{case}.json`。"
        elif turn == 4:
            owner_text = "先停一下，說明目前可以確認與不能確認的部分"
            ai_text = "目前證據不足，不能確認責任歸因"
        items.extend([
            {"timestamp": f"2026-10-02T06:00:{turn * 2:02d}Z",
             "type": "response_item", "payload": {"type": "message",
             "id": f"u{turn}", "role": "user",
             "content": [{"type": "input_text", "text": owner_text}]}},
            {"timestamp": f"2026-10-02T06:00:{turn * 2 + 1:02d}Z",
             "type": "response_item", "payload": {"type": "message",
             "id": f"a{turn}", "role": "assistant",
             "content": [{"type": "output_text", "text": ai_text}]}},
        ])
    _write(transcript, items)
    hint = tmp_path / ".forseti" / "current-session-id"
    hint.parent.mkdir(parents=True)
    hint.write_text(sid, encoding="utf-8")

    assert session_surface.main(["session_surface.py"]) == 0
    data = json.loads(capsys.readouterr().out)
    fourth = data["rows"][3]
    if case < 25:
        assert fourth["path_semantics"]["state"] == "new_direction"
        assert fourth["owner_goal_change_candidate"] is True
        assert fourth["path_semantics"]["actor"] != "AI"
        assert "新的方向" in data["cards"][0]["title"] or "方向" in data["cards"][0]["title"]
    elif case < 50:
        assert fourth["corrected_by_owner"] is True
        assert fourth.get("owner_goal_change_candidate") is not True
    elif case < 75:
        assert fourth["path_semantics"]["actor"] == "AI"
        assert fourth["betrayals"][0]["kind"] == "SAID_WROTE_DIDNT"
    else:
        assert fourth["path_semantics"]["actor"] != "AI"
        assert fourth.get("owner_goal_change_candidate") is not True


def test_fast_surface_returns_recommendation_cards(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "01a0-card-contract"
    transcript = (tmp_path / ".codex" / "sessions" / "2026" / "10"
                  / f"rollout-{sid}.jsonl")
    _write(transcript, [
        {"timestamp": "2026-10-02T06:00:00Z", "type": "response_item",
         "payload": {"type": "message", "id": "u1", "role": "user",
                     "content": [{"type": "input_text", "text": "改成檢查三張建議卡"}]}},
        {"timestamp": "2026-10-02T06:00:01Z", "type": "response_item",
         "payload": {"type": "message", "id": "a1", "role": "assistant",
                     "content": [{"type": "output_text", "text": "收到新方向"}]}},
    ])
    hint = tmp_path / ".forseti" / "current-session-id"
    hint.parent.mkdir(parents=True)
    hint.write_text(sid, encoding="utf-8")

    assert session_surface.main(["session_surface.py"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["cards"]
    assert len(data["cards"]) == 3
    assert len({card["key"] for card in data["cards"]}) == 3
    card = data["cards"][0]
    assert all(card.get(key) for key in
               ("title", "say", "why_now", "evidence", "confidence", "if_ignored"))


@pytest.mark.parametrize("text", [
    "我不是要改成新目標，而是照原方向",
    "我並非要換方向，只是在糾正你",
    "不要換方向，繼續檢查原方向",
])
def test_negated_direction_language_does_not_change_north_star(text):
    assert vitals.owner_goal_change_candidates([
        {"n": 1, "owner_text": text},
    ]) == []


def test_primary_ui_renders_owner_and_ai_with_attributed_verdict():
    js = (ROOT / "desktop" / "ui" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "desktop" / "ui" / "index.html").read_text(encoding="utf-8")
    assert "flat(s.owner_text)" in js
    assert "flat(s.ai_text)" in js
    assert "責任：${semantic.actor}" in js
    assert 'id="nodeAI"' in html
    assert 'id="nodeVerdict"' in html
