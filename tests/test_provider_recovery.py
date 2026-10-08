"""Native transcript recovery must preserve text and physical line provenance."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

from provider_recovery import recover_archived_interval, recover_provider_interval
from source_archive import sync_source


def _write(path, records):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                            for r in records), encoding="utf-8")


def test_codex_original_text_survives_snapshot_limits(tmp_path):
    source = tmp_path / "codex.jsonl"
    ending = "不得刪除原始資料"
    owner = "新的方向是：" + "保留完整資料。" * 110 + ending
    reply = "我會把這段保留下來。" * 100 + "最後一段 AI 回覆也在"
    _write(source, [
        {"type": "response_item", "timestamp": "2026-10-08T10:00:00Z",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": owner}]}},
        {"type": "response_item", "timestamp": "2026-10-08T10:00:01Z",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": reply}]}},
        {"type": "compacted", "timestamp": "2026-10-08T10:00:02Z",
         "payload": {"window_number": 2}},
    ])
    result = recover_provider_interval(
        source_path=str(source), provider="codex", start_round=1,
        compaction_ordinal=1, goal="保留", task="回取")
    assert result["status"] == "READY"
    assert result["auto_inject"] is False
    serialized = json.dumps(result["packet"], ensure_ascii=False)
    assert owner in serialized and ending in serialized
    assert reply in serialized and "最後一段 AI 回覆也在" in serialized
    assert f"{source.resolve()}:1-2" in serialized
    assert result["compaction_source_ref"] == f"{source.resolve()}:3"


def test_claude_original_text_and_line_range(tmp_path):
    source = tmp_path / "claude.jsonl"
    _write(source, [
        {"type": "user", "timestamp": "2026-10-08T10:00:00Z",
         "message": {"content": "保留原始指令"}},
        {"type": "assistant", "timestamp": "2026-10-08T10:00:01Z",
         "message": {"content": [{"type": "text", "text": "會保留"}]}},
        {"type": "user", "timestamp": "2026-10-08T10:00:02Z",
         "message": {"content": "第二輪"}},
        {"type": "system", "timestamp": "2026-10-08T10:00:03Z",
         "compactMetadata": {"preTokens": 100, "postTokens": 10}},
    ])
    result = recover_provider_interval(
        source_path=str(source), provider="claude", start_round=1,
        compaction_ordinal=1, goal="保留", task="回取")
    assert result["status"] == "READY"
    serialized = json.dumps(result["packet"], ensure_ascii=False)
    assert "保留原始指令" in serialized and "會保留" in serialized
    assert f"{source.resolve()}:1-2" in serialized


def test_corrupt_native_line_fails_closed(tmp_path):
    source = tmp_path / "codex.jsonl"
    source.write_text('{"type":"response_item"}\n{broken}\n', encoding="utf-8")
    result = recover_provider_interval(
        source_path=str(source), provider="codex", start_round=1,
        compaction_ordinal=1, goal="g", task="t")
    assert result["status"] == "UNKNOWN"
    assert result["packet"] is None


def test_assistant_after_compaction_is_not_in_pre_compaction_packet(tmp_path):
    source = tmp_path / "codex.jsonl"
    _write(source, [
        {"type": "response_item", "timestamp": "2026-10-08T10:00:00Z",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "保留原始指令"}]}},
        {"type": "response_item", "timestamp": "2026-10-08T10:00:01Z",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "壓縮前回覆"}]}},
        {"type": "compacted", "timestamp": "2026-10-08T10:00:02Z",
         "payload": {"window_number": 2}},
        {"type": "response_item", "timestamp": "2026-10-08T10:00:03Z",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "壓縮後回覆不得混入"}]}},
    ])
    result = recover_provider_interval(
        source_path=str(source), provider="codex", start_round=1,
        compaction_ordinal=1, goal="保留", task="回取")
    assert result["status"] == "READY"
    text = json.dumps(result["packet"], ensure_ascii=False)
    assert "壓縮前回覆" in text
    assert "壓縮後回覆不得混入" not in text


def test_codex_owner_envelope_and_whitespace_are_preserved(tmp_path):
    source = tmp_path / "codex.jsonl"
    original = "  <context>must remain</context>\n## My request:\n  保留原文  "
    _write(source, [
        {"type": "response_item", "timestamp": "2026-10-08T10:00:00Z",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": original}]}},
        {"type": "compacted", "timestamp": "2026-10-08T10:00:01Z",
         "payload": {"window_number": 2}},
    ])
    result = recover_provider_interval(
        source_path=str(source), provider="codex", start_round=1,
        compaction_ordinal=1, goal="保留", task="回取")
    assert result["status"] == "READY"
    assert original in [fragment["text"] for fragment in
                        result["packet"]["original_fragments"]]
    assert result["scope"] == "owner_and_ai_text_not_tool_payloads"


def test_malformed_assistant_content_fails_closed(tmp_path):
    source = tmp_path / "codex.jsonl"
    _write(source, [
        {"type": "response_item", "timestamp": "2026-10-08T10:00:00Z",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "保留原文"}]}},
        {"type": "response_item", "timestamp": "2026-10-08T10:00:01Z",
         "payload": {"type": "message", "role": "assistant", "content": 42}},
        {"type": "compacted", "timestamp": "2026-10-08T10:00:02Z",
         "payload": {"window_number": 2}},
    ])
    result = recover_provider_interval(
        source_path=str(source), provider="codex", start_round=1,
        compaction_ordinal=1, goal="保留", task="回取")
    assert result["status"] == "UNKNOWN"
    assert result["packet"] is None


def test_recover_from_verified_archive_after_original_is_removed(tmp_path, monkeypatch):
    import source_archive
    monkeypatch.setattr(source_archive, "_KEY_PATH", tmp_path / "archive-key")
    monkeypatch.setattr(source_archive, "_ANCHOR_DIR", tmp_path / "archive-anchors")
    with tempfile.TemporaryDirectory(dir="/Volumes/NewDrive") as folder:
        base = Path(folder)
        source = base / "codex.jsonl"
        _write(source, [
            {"type": "response_item", "timestamp": "2026-10-08T10:00:00Z",
             "payload": {"type": "message", "role": "user",
                         "content": [{"type": "input_text", "text": "完整保留這段原文"}]}},
            {"type": "response_item", "timestamp": "2026-10-08T10:00:01Z",
             "payload": {"type": "message", "role": "assistant",
                         "content": [{"type": "output_text", "text": "原文仍可回取"}]}},
            {"type": "compacted", "timestamp": "2026-10-08T10:00:02Z",
             "payload": {"window_number": 2}},
        ])
        kwargs = {"source_path": source,
                  "archive_root": base / ".forseti" / "session_archive",
                  "provider": "codex", "session_id": "source-deletion-test",
                  "max_bytes": max(map(len, source.read_bytes().splitlines(keepends=True)))}
        archive = None
        for _ in range(12):
            archive = sync_source(**kwargs)
            if archive["status"] == "READY":
                break
        assert archive["status"] == "READY"
        archive_dir = Path(archive["archive_path"])
        assert len(list(archive_dir.glob("*.enc"))) >= 2
        assert not list(archive_dir.glob("*.jsonl"))
        for encrypted in archive_dir.glob("*.enc"):
            assert "完整保留這段原文".encode() not in encrypted.read_bytes()
        assert str(source) not in Path(archive["manifest_path"]).read_text()
        assert source_archive._KEY_PATH.is_file()
        assert not source_archive._KEY_PATH.is_relative_to(base)
        source.unlink()
        recovered = recover_archived_interval(
            manifest_path=archive["manifest_path"], start_round=1,
            compaction_ordinal=1, goal="保留", task="回取")
        assert recovered["status"] == "READY"
        assert recovered["auto_inject"] is False
        assert "完整保留這段原文" in json.dumps(recovered["packet"], ensure_ascii=False)
        assert archive["manifest_path"] in recovered["compaction_source_ref"]
        assert f'{archive["manifest_path"]}:1-2' in json.dumps(recovered["packet"], ensure_ascii=False)
        assert recovered["compaction_source_ref"] == f'{archive["manifest_path"]}:3'
