import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import codex_session_inventory as inventory  # noqa: E402


def test_named_codex_session_is_available_to_picker(tmp_path):
    sid = "01a0f038-8b37-72f3-971e-21f870cef93c"
    transcript = (tmp_path / "sessions" / "2026" / "09" / "30"
                  / f"rollout-2026-09-30T10-50-32-{sid}.jsonl")
    transcript.parent.mkdir(parents=True)
    transcript.write_text("{}\n", encoding="utf-8")
    index = tmp_path / "session_index.jsonl"
    index.write_text(json.dumps({
        "id": sid,
        "thread_name": "建立硬碟檔案地圖與索引",
        "updated_at": "2026-09-30T02:50:38.093055Z",
    }, ensure_ascii=False) + "\n", encoding="utf-8")

    rows = inventory.list_sessions(tmp_path / "sessions", index)

    assert rows == [dict(rows[0], **{
        "id": sid,
        "ui_id": sid,
        "title": "建立硬碟檔案地圖與索引",
        "provider": "codex",
        "title_source": "codex_session_index",
        "named": True,
    })]


def test_malformed_or_missing_index_never_invents_a_title(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "rollout-unknown.jsonl").write_text("{}\n", encoding="utf-8")
    index = tmp_path / "session_index.jsonl"
    index.write_text("not-json\n", encoding="utf-8")

    assert inventory.list_sessions(sessions, index) == []


def test_title_for_returns_only_the_exact_indexed_session(tmp_path):
    index = tmp_path / "session_index.jsonl"
    index.write_text(
        json.dumps({"id": "other", "thread_name": "別的 Session"},
                   ensure_ascii=False) + "\n" +
        json.dumps({"id": "target", "thread_name": "建立硬碟檔案地圖與索引"},
                   ensure_ascii=False) + "\n",
        encoding="utf-8")

    assert inventory.title_for("target", index) == "建立硬碟檔案地圖與索引"
    assert inventory.title_for("missing", index) == ""


def test_primary_header_renders_session_title_and_id():
    js = (ROOT / "desktop" / "ui" / "app.js").read_text(encoding="utf-8")
    surface = (ROOT / "apps" / "forseti-cli" / "session_surface.py").read_text(
        encoding="utf-8")
    assert 'd.session_title || ""' in js
    assert '"session_title": session_title' in surface
