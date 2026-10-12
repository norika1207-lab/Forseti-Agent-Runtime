"""Recover pre-compaction context from native Claude or Codex event streams."""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from rehydration import ORIGINAL, PACKET_LIMIT, recover_original_interval
from source_archive import ArchiveReadError, iter_plaintext_chunks, verified_chunks
from tracker import CodexTracker, Tracker


def _native_message(rec: dict, provider: str) -> tuple[str, str] | None:
    if provider == "codex":
        if rec.get("type") != "response_item":
            return None
        payload = rec.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("invalid message payload")
        if payload.get("type") != "message" or payload.get("role") not in {
                "user", "assistant"}:
            return None
        role, content = payload["role"], payload.get("content")
        accepted = {"input_text", "output_text", "text"}
    else:
        if rec.get("type") not in {"user", "assistant"}:
            return None
        message = rec.get("message")
        if not isinstance(message, dict):
            raise ValueError("invalid message")
        role, content = rec["type"], message.get("content")
        accepted = {"text"}

    if isinstance(content, str):
        return role, content
    if not isinstance(content, list):
        raise ValueError("invalid message content")
    parts = []
    for block in content:
        if not isinstance(block, dict):
            raise ValueError("invalid content block")
        if block.get("type") in accepted:
            if not isinstance(block.get("text"), str):
                raise ValueError("invalid text block")
            parts.append(block["text"])
    return role, "\n".join(parts)


def recover_provider_interval(*, source_path: str, provider: str,
                              start_round: int, compaction_ordinal: int,
                              goal: str, task: str,
                              limit: int = PACKET_LIMIT) -> dict:
    """Recover from one native transcript without modifying or injecting it."""
    if not isinstance(source_path, str) or not source_path.strip():
        return _unknown("missing_source")
    path = Path(source_path)
    if not path.is_file():
        return _unknown("missing_source")
    return _recover_records(lambda: _raw_lines([path]), str(path.resolve()), provider,
                            start_round, compaction_ordinal, goal, task, limit)


def recover_archived_interval(*, manifest_path: str, start_round: int,
                              compaction_ordinal: int, goal: str, task: str,
                              limit: int = PACKET_LIMIT) -> dict:
    """Recover from verified ordered chunks after the original is gone."""
    verified = verified_chunks(manifest_path)
    if verified["status"] != "READY":
        return _unknown("archive_" + verified["reason"])
    result = _recover_records(
        lambda: _archived_lines(manifest_path),
        verified["manifest_path"], verified["provider"], start_round,
        compaction_ordinal, goal, task, limit)
    after = verified_chunks(manifest_path)
    if (after["status"] != "READY"
            or after["chain_sha256"] != verified["chain_sha256"]):
        return _unknown("archive_changed_during_recovery")
    return result


def _unknown(reason: str) -> dict:
    return {"status": "UNKNOWN", "reason": reason, "packet": None,
            "auto_inject": False}


def _raw_lines(paths: list[Path]):
    for path in paths:
        with path.open("rb") as source:
            yield from source


def _archived_lines(manifest_path: str):
    pending = b""
    for chunk in iter_plaintext_chunks(manifest_path):
        pieces = (pending + chunk).split(b"\n")
        for line in pieces[:-1]:
            yield line + b"\n"
        pending = pieces[-1]
    if pending:
        yield pending


def _recover_records(line_factory, source_ref: str, provider: str,
                     start_round: int, compaction_ordinal: int,
                     goal: str, task: str, limit: int) -> dict:
    """Use physical line numbers; never serialize display-truncated rows."""
    def unknown(reason: str) -> dict:
        return _unknown(reason)

    if provider not in {"claude", "codex"}:
        return unknown("unknown_provider")
    if type(compaction_ordinal) is not int or compaction_ordinal < 1:
        return unknown("invalid_compaction_ordinal")
    # Tracker intentionally tolerates corrupt unrelated lines for the live UI.
    # Recovery cannot claim a complete source interval if the source is corrupt.
    parser = CodexTracker(source_ref) if provider == "codex" else Tracker(source_ref)
    try:
        with closing(line_factory()) as lines:
            for line_no, raw in enumerate(lines, 1):
                if not raw.endswith(b"\n"):
                    return unknown("incomplete_source_line")
                rec = json.loads(raw)
                if not isinstance(rec, dict):
                    return unknown("invalid_source_row")
                parser._handle(rec, line_no)
    except (OSError, UnicodeError, ValueError, ArchiveReadError):
        return unknown("unreadable_source")
    if provider == "codex":
        boundaries = [event["line"] for event in parser.compaction_events]
    else:
        boundaries = [strand.compaction_meta["line"]
                      for strand in parser.strands if strand.compaction]
    if compaction_ordinal > len(boundaries):
        return unknown("missing_compaction_anchor")
    cutoff = boundaries[compaction_ordinal - 1]
    previous_cutoff = boundaries[compaction_ordinal - 2] \
        if compaction_ordinal > 1 else 0

    # Reparse only records physically before this anchor. A turn can continue
    # after compaction, so whole-turn ai_text would include future words.
    prefix = CodexTracker(source_ref) if provider == "codex" else Tracker(source_ref)
    messages = {}
    try:
        with closing(line_factory()) as lines:
            for line_no, raw in enumerate(lines, 1):
                if line_no >= cutoff:
                    break
                rec = json.loads(raw)
                message = _native_message(rec, provider)
                if message is not None:
                    messages[line_no] = message
                prefix._handle(rec, line_no)
    except (OSError, UnicodeError, ValueError, ArchiveReadError):
        return unknown("unreadable_source")

    rows = []
    for strand in prefix.strands:
        if strand.n < start_round:
            continue
        if strand.compaction or strand.owner_line <= previous_cutoff:
            return unknown("cross_compaction_boundary")
        owner_message = messages.get(strand.owner_line)
        if owner_message is None or owner_message[0] != "user":
            return unknown("missing_original_owner_message")
        answer_lines = [item.get("line") for item in strand.activity
                        if item.get("kind") == "answer"
                        and isinstance(item.get("line"), int)]
        if any(line not in messages or messages[line][0] != "assistant"
               for line in answer_lines):
            return unknown("missing_original_ai_message")
        end_line = max([strand.owner_line] + answer_lines)
        rows.append({
            "n": strand.n, "source_type": ORIGINAL,
            "source_ref": f"{source_ref}:{strand.owner_line}-{end_line}",
            "owner_text": owner_message[1],
            "ai_text": "\n\n".join(messages[line][1] for line in answer_lines),
        })
    if not rows:
        return unknown("missing_source_round")
    result = recover_original_interval(
        source_rows=rows, start_round=start_round,
        compaction_round=rows[-1]["n"] + 1,
        goal=goal, task=task, limit=limit)
    if result["status"] == "READY":
        result["reason"] = "conversation_text_complete_pre_anchor"
        result["scope"] = "owner_and_ai_text_not_tool_payloads"
        result["compaction_source_ref"] = f"{source_ref}:{cutoff}"
        result["recovered_end_round"] = rows[-1]["n"]
    return result
