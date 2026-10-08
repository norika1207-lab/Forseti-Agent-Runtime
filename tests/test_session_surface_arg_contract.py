import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import session_surface  # noqa: E402


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

    rust = (ROOT / "desktop" / "src-tauri" / "src" / "main.rs").read_text()
    assert "cmd.arg(session.unwrap_or_default());" in rust
    assert "cmd.arg(tail.unwrap_or(180).to_string());" in rust
