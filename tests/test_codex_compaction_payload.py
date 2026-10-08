"""Native Codex compaction events retain their anchor even with a payload."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

from tracker import CodexTracker


def test_native_compacted_event_with_payload_is_visible(tmp_path):
    transcript = tmp_path / "session.jsonl"
    records = [
        {"type": "response_item", "timestamp": "2026-10-08T10:00:00Z",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "Keep the goal"}]}},
        {"type": "compacted", "timestamp": "2026-10-08T10:01:00Z",
         "payload": {"window_number": 2, "message": ""}},
    ]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records),
                          encoding="utf-8")
    parser = CodexTracker(transcript)
    assert parser.poll() == 2
    assert parser.snapshot()["compaction_total"] == 1
    assert parser.strands[0].compaction_meta["line"] == 2


def test_each_native_compaction_has_its_own_source_anchor(tmp_path):
    transcript = tmp_path / "session.jsonl"
    records = [
        {"type": "response_item", "timestamp": "2026-10-08T10:00:00Z",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "Keep the goal"}]}},
        {"type": "compacted", "timestamp": "2026-10-08T10:01:00Z",
         "payload": {"window_number": 2}},
        {"type": "compacted", "timestamp": "2026-10-08T10:02:00Z",
         "payload": {"window_number": 3}},
    ]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records),
                          encoding="utf-8")
    parser = CodexTracker(transcript)
    assert parser.poll() == 3
    assert parser.snapshot()["compaction_total"] == 2
    assert len(parser.strands) == 1
    assert [e["line"] for e in parser.snapshot()["compaction_events"]] == [2, 3]
    assert [e["label"] for e in parser.snapshot()["compaction_events"]] == [
        "對話壓縮", "對話壓縮"]


def test_assistant_activity_after_compaction_stays_on_owner_turn(tmp_path):
    transcript = tmp_path / "session.jsonl"
    records = [
        {"type": "response_item", "timestamp": "2026-10-08T10:00:00Z",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "Keep the goal"}]}},
        {"type": "compacted", "timestamp": "2026-10-08T10:01:00Z",
         "payload": {"window_number": 2}},
        {"type": "response_item", "timestamp": "2026-10-08T10:02:00Z",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "Continuing the task"}]}},
    ]
    transcript.write_text("".join(json.dumps(r) + "\n" for r in records),
                          encoding="utf-8")
    parser = CodexTracker(transcript)
    parser.poll()
    owner = parser.strands[0]
    assert owner.ai_text == "Continuing the task"
    assert [item["kind"] for item in owner.activity] == ["answer"]
    assert parser.snapshot()["compaction_events"][0]["n"] == owner.n
