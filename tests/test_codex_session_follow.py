import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import desktop_api  # noqa: E402
import session_surface  # noqa: E402
import tracker  # noqa: E402


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
    assert data["semantic_surface"]["unknown_is_not_aligned"] is True


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


def test_primary_ui_renders_owner_and_ai_with_attributed_verdict():
    js = (ROOT / "desktop" / "ui" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "desktop" / "ui" / "index.html").read_text(encoding="utf-8")
    assert "flat(s.owner_text)" in js
    assert "flat(s.ai_text)" in js
    assert "責任：${semantic.actor}" in js
    assert 'id="nodeAI"' in html
    assert 'id="nodeVerdict"' in html
