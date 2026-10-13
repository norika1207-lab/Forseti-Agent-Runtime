import json
import os
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import session_surface  # noqa: E402


def test_claude_focus_only_reads_recent_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
    root.mkdir(parents=True)
    for index in range(300):
        path = root / f"local_{index:03}.json"
        path.write_text(json.dumps({
            "cliSessionId": f"session-{index}",
            "title": f"Session {index}",
            "lastFocusedAt": 1000 if index != 299 else 2000,
        }), encoding="utf-8")
        os.utime(path, (index + 1, index + 1))
    monkeypatch.setattr(session_surface, "_CLAUDE_FOCUS_CACHE", (-1e9, ("", 0.0)))

    assert session_surface.latest_claude_focused_session()[0] == "session-299"
    assert session_surface.claude_session_title("session-299") == "Session 299"
    assert len(session_surface._CLAUDE_TITLE_CACHE) == 256


def test_auto_follow_skips_unavailable_claude_and_pin_overrides_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    claude = "9aa8c99e-b2a4-42b2-b99f-916a97e51113"
    missing = "77f5fa15-b2a4-42b2-b99f-916a97e51113"
    codex = "88f5fa15-b2a4-42b2-b99f-916a97e51113"
    transcript = tmp_path / ".claude" / "projects" / "demo" / f"{claude}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n", encoding="utf-8")
    codex_path = tmp_path / ".codex" / "sessions" / f"{codex}.jsonl"
    codex_path.parent.mkdir(parents=True)
    codex_path.write_text("{}\n", encoding="utf-8")
    metadata = tmp_path / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
    metadata.mkdir(parents=True)
    for name, sid, focus in (("stale", missing, 3000), ("current", claude, 2000)):
        (metadata / f"local_{name}.json").write_text(json.dumps({
            "cliSessionId": sid, "sessionId": sid, "title": name,
            "lastFocusedAt": focus * 1000,
        }), encoding="utf-8")
    logs = tmp_path / "codex-logs"
    logs.mkdir()
    (logs / "main.log").write_text(
        "2026-10-13T08:00:00Z thread_stream_view_activity_changed "
        f"active=true conversationId={codex} rendererWindowAppearance=primary "
        "rendererWindowFocused=true rendererWindowVisible=true\n", encoding="utf-8")
    monkeypatch.setattr(session_surface, "_CLAUDE_FOCUS_CACHE", (-1e9, ("", 0.0)))

    assert session_surface.resolve_requested("", logs_root=logs, provider_hint="codex") == codex_path
    assert session_surface.resolve_requested("", logs_root=logs, provider_hint="claude") == transcript
    assert session_surface.resolve_requested(codex, logs_root=logs, provider_hint="claude") == codex_path
    assert session_surface.resolve_requested(claude, logs_root=logs, provider_hint="codex") == transcript
    assert session_surface.resolve_requested("", logs_root=logs, provider_hint="codex") == codex_path


def test_one_disappearing_claude_metadata_does_not_erase_all_candidates(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    root = tmp_path / "Library" / "Application Support" / "Claude" / "claude-code-sessions"
    root.mkdir(parents=True)
    good = root / "local_good.json"
    good.write_text(json.dumps({
        "cliSessionId": "good-session", "title": "Current",
        "lastFocusedAt": 2000,
    }), encoding="utf-8")
    gone = root / "local_gone.json"
    gone.write_text("{}", encoding="utf-8")
    stat = Path.stat

    def one_missing(path, *args, **kwargs):
        if path == gone:
            raise FileNotFoundError(path)
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", one_missing)
    monkeypatch.setattr(session_surface, "_CLAUDE_FOCUS_CACHE", (-1e9, ("", 0.0)))
    assert session_surface.latest_claude_focused_session()[0] == "good-session"


def test_codex_session_uses_saved_display_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    sid = "88f5fa15-b2a4-42b2-b99f-916a97e51113"
    transcript = tmp_path / ".codex" / "sessions" / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"type": "user", "message": {
        "role": "user", "content": "hello"}}) + "\n", encoding="utf-8")
    db = tmp_path / ".codex" / "state_5.sqlite"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, name TEXT)")
        conn.execute("INSERT INTO threads VALUES (?, ?, ?)",
                     (sid, "Initial Codex title", "Renamed Codex session"))

    assert session_surface.main(["session_surface.py", sid, "180", "codex"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["provider"] == "codex"
    assert data["session_title"] == "Renamed Codex session"

    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE threads SET name = ? WHERE id = ?", ("  ", sid))
    assert session_surface.codex_session_title(sid) == "Initial Codex title"


def test_codex_title_missing_database_or_session_is_unknown(tmp_path):
    target = "88f5fa15-b2a4-42b2-b99f-916a97e51113"
    root = tmp_path / ".codex"
    assert session_surface.codex_session_title(target, root) == ""
    root.mkdir()
    with sqlite3.connect(root / "state_5.sqlite") as conn:
        conn.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, title TEXT, name TEXT)")
        conn.execute("INSERT INTO threads VALUES (?, ?, ?)",
                     ("another-session", "Another title", "Another name"))
    assert session_surface.codex_session_title(target, root) == ""


def test_auto_session_with_tail_preserves_empty_session_slot(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "88f5fa15-b2a4-42b2-b99f-916a97e51113"
    transcript = tmp_path / ".claude" / "projects" / "demo" / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"type": "user", "message": {
        "role": "user", "content": "hello"}}) + "\n", encoding="utf-8")
    metadata = (tmp_path / "Library" / "Application Support" / "Claude" /
                "claude-code-sessions" / "local_demo.json")
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({
        "cliSessionId": sid,
        "title": "掃描公司IP中的aiserver遠端登入",
        "lastFocusedAt": 1791427788978,
    }), encoding="utf-8")
    monkeypatch.setattr(session_surface, "_CLAUDE_FOCUS_CACHE", (-1e9, ("", 0.0)))

    assert session_surface.main(["session_surface.py", "", "180", "claude"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["provider"] == "claude"
    assert data["session"] == sid
    assert data["session_title"] == "掃描公司IP中的aiserver遠端登入"
    assert data["window"]["tail"] == 180
    assert "lanes" in data and "lanes" in data["lanes"]

    rust = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text()
    assert "cmd.arg(session.unwrap_or_default());" in rust
    assert "cmd.arg(tail.unwrap_or(180).to_string());" in rust


def test_archive_metadata_is_internal_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "88f5fa15-b2a4-42b2-b99f-916a97e51113"
    transcript = tmp_path / ".claude" / "projects" / "demo" / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(json.dumps({"type": "user", "message": {
        "role": "user", "content": "hello"}}) + "\n", encoding="utf-8")

    assert session_surface.main(["session_surface.py", sid, "180", "claude"]) == 0
    public = json.loads(capsys.readouterr().out)
    assert "_archive_source_path" not in public

    assert session_surface.main([
        "session_surface.py", sid, "180", "claude", "archive-meta-v1",
    ]) == 0
    internal = json.loads(capsys.readouterr().out)
    assert internal["_archive_source_path"] == str(transcript)

    rust = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text()
    assert 'object.remove("_archive_source_path")' in rust
    assert 'cmd.arg("archive-meta-v1")' in rust
    assert 'schedule_raw_archive(&contents, &source, provider, session_id)' in rust


def test_owner_correction_reaches_session_issue_lane(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    sid = "88f5fa15-b2a4-42b2-b99f-916a97e51113"
    transcript = tmp_path / ".claude" / "projects" / "demo" / f"{sid}.jsonl"
    transcript.parent.mkdir(parents=True)
    records = [
        {"type": "user", "message": {"content": "先完成 A"}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "我完成了 B"}]}},
        {"type": "user", "message": {"content": "你做反了，這次要的是 B"}},
    ]
    transcript.write_text("\n".join(json.dumps(item, ensure_ascii=False)
                                    for item in records) + "\n", encoding="utf-8")

    assert session_surface.main(["session_surface.py", sid, "180", "claude"]) == 0
    data = json.loads(capsys.readouterr().out)
    correction = next(lane for lane in data["lanes"]["lanes"]
                      if lane["kind"] == "CORRECTION")
    assert correction["event_link"] is True
    assert correction["evidence"] == "你做反了，這次要的是 B"


def test_archive_metadata_rejects_unrelated_jsonl(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    transcript = tmp_path / "unrelated.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {
        "role": "user", "content": "private"}}) + "\n", encoding="utf-8")
    assert session_surface.main([
        "session_surface.py", str(transcript), "180", "claude", "archive-meta-v1",
    ]) == 0
    data = json.loads(capsys.readouterr().out)
    assert "_archive_source_path" not in data


def test_archive_launcher_keeps_session_metadata_out_of_process_argv():
    rust = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text()
    launcher = rust.split("fn schedule_raw_archive(", 1)[1].split("\nfn ", 1)[0]
    assert '.arg("launch-fd")' in launcher
    assert '.arg("--request-fd").arg("0")' in launcher
    assert '.stdin(Stdio::piped())' in launcher
    assert 'stdin.write_all(&payload)' in launcher
    for sensitive_flag in ('--source', '--session-id', '--archive-root', '--provider'):
        assert f'.arg("{sensitive_flag}")' not in launcher
