from pathlib import Path
from unittest.mock import patch

import archive_backfill


def test_sources_include_native_transcripts_and_non_uuid_agent_logs(tmp_path):
    codex = tmp_path / ".codex/sessions/2026/10/12"
    claude = tmp_path / ".claude/projects/project"
    codex.mkdir(parents=True)
    claude.mkdir(parents=True)
    codex_id = "01a0c213-35e3-7053-95fc-36a449c5d676"
    claude_id = "88f5fa15-b2a4-42b2-b99f-916a97e51113"
    (codex / f"rollout-2026-10-12T01-00-00-{codex_id}.jsonl").write_text("{}\n")
    (claude / f"{claude_id}.jsonl").write_text("{}\n")
    (claude / "audit.jsonl").write_text("{}\n")
    another = tmp_path / ".claude/projects/z-project"
    another.mkdir()
    (another / f"{claude_id}.jsonl").write_text("{}\n")
    rows = archive_backfill.sources(tmp_path)
    assert [(provider, session_id) for provider, session_id, _ in rows if
            session_id in {claude_id, codex_id}] == [
                ("claude", claude_id), ("codex", codex_id)]
    assert len(rows) == 4
    assert rows[1][1].startswith("file-")
    assert rows[2][1].startswith("file-")
    assert rows[1][1] != rows[2][1]


def test_batch_retries_same_source_after_time_budget():
    rows = [("claude", "88f5fa15-b2a4-42b2-b99f-916a97e51113",
             Path("/unused/source.jsonl"))]
    with patch.object(archive_backfill, "sources", return_value=rows), \
         patch.object(archive_backfill.source_archive, "sync_source",
                      return_value={"status": "IN_PROGRESS", "reason": "auditing"}), \
         patch.object(archive_backfill.time, "monotonic", side_effect=[0, 0, 0, 2]):
        result = archive_backfill.import_batch(
            home=Path("/unused"), archive_root=Path("/unused/archive"),
            start=0, limit=1, seconds=1)
    assert result["next_index"] == 0
    assert result["counts"]["IN_PROGRESS"] == 1


def test_batch_advances_after_ready_and_records_unknown():
    rows = [("claude", "88f5fa15-b2a4-42b2-b99f-916a97e51113", Path("/a")),
            ("codex", "01a0c213-35e3-7053-95fc-36a449c5d676", Path("/b"))]
    with patch.object(archive_backfill, "sources", return_value=rows), \
         patch.object(archive_backfill.source_archive, "sync_source",
                      side_effect=[{"status": "READY", "reason": "verified"},
                                   {"status": "UNKNOWN", "reason": "source_modified"}]):
        result = archive_backfill.import_batch(
            home=Path("/unused"), archive_root=Path("/unused/archive"),
            start=0, limit=2, seconds=10)
    assert result["scan_complete"] is True
    assert result["batch_all_ready"] is False
    assert result["counts"]["READY"] == 1
    assert result["unknown_reasons"] == {"source_modified": 1}
    assert result["unknown_items"] == [{
        "index": 1, "provider": "codex",
        "session_id": "01a0c213-35e3-7053-95fc-36a449c5d676",
        "reason": "source_modified"}]
