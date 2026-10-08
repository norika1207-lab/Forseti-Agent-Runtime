"""Native transcript recovery must preserve text and physical line provenance."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

from provider_recovery import recover_provider_interval


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
