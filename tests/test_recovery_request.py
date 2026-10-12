"""The desktop recovery entrypoint only reads bounded native originals."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

from recovery_request import recover_request


def _codex(path: Path, owner: str, answer: str) -> None:
    records = [
        {"type": "response_item", "payload": {"type": "message", "role": "user",
         "content": [{"type": "input_text", "text": owner}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
         "content": [{"type": "output_text", "text": answer}]}},
        {"type": "compacted", "payload": {"window_number": 2}},
    ]
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records),
                    encoding="utf-8")


def test_native_compaction_restores_exact_text_and_line_refs(tmp_path):
    source = tmp_path / ".codex/sessions/one.jsonl"
    source.parent.mkdir(parents=True)
    owner = "原文末段不可被卡片截斷" + "甲" * 400
    answer = "AI 原文末段" + "乙" * 400
    _codex(source, owner, answer)
    result = recover_request(home=tmp_path, source_path=str(source),
                             provider="codex", ordinal=1, round_number=1,
                             expected_line=3)
    assert result["status"] == "READY"
    assert result["auto_inject"] is False
    fragments = result["packet"]["original_fragments"]
    assert [fragment["text"] for fragment in fragments] == [owner, answer]
    assert all(f"{source}:1-2" in item["provenance"] for item in fragments)


def test_rejects_external_file_and_symlink(tmp_path):
    root = tmp_path / ".codex/sessions"
    root.mkdir(parents=True)
    external = tmp_path / "secret.jsonl"
    _codex(external, "user", "AI")
    link = root / "link.jsonl"
    link.symlink_to(external)
    for source in (external, link):
        result = recover_request(home=tmp_path, source_path=str(source),
                                 provider="codex", ordinal=1, round_number=1,
                                 expected_line=3)
        assert result["status"] == "UNKNOWN"
        assert result["packet"] is None


def test_rejects_invalid_provider_and_round(tmp_path):
    for provider, ordinal, round_number in (("grok", 1, 1), ("codex", 0, 1),
                                             ("codex", 1, 0)):
        result = recover_request(home=tmp_path, source_path="/tmp/a.jsonl",
                                 provider=provider, ordinal=ordinal,
                                 round_number=round_number, expected_line=3)
        assert result["status"] == "UNKNOWN"


def test_refuses_mismatched_compaction_marker(tmp_path):
    source = tmp_path / ".codex/sessions/one.jsonl"
    source.parent.mkdir(parents=True)
    _codex(source, "owner", "answer")
    result = recover_request(home=tmp_path, source_path=str(source),
                             provider="codex", ordinal=1, round_number=1,
                             expected_line=99)
    assert result["status"] == "UNKNOWN"
    assert result["reason"] == "compaction_anchor_changed"


def test_refuses_mismatched_round_for_correct_anchor(tmp_path):
    source = tmp_path / ".codex/sessions/one.jsonl"
    source.parent.mkdir(parents=True)
    _codex(source, "owner", "answer")
    result = recover_request(home=tmp_path, source_path=str(source),
                             provider="codex", ordinal=1, round_number=2,
                             expected_line=3)
    assert result["status"] == "UNKNOWN"
    assert result["packet"] is None
