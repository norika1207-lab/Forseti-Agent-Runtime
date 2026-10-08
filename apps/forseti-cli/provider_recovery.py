"""Recover pre-compaction context from native Claude or Codex event streams."""

from __future__ import annotations

import json
from pathlib import Path

from rehydration import ORIGINAL, PACKET_LIMIT, recover_original_interval
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
    """Return an inspectable packet with untruncated text and source line ranges.

    The native transcript or its byte-identical archive is read-only. No
    recovered text is injected into an AI without a separate owner action.
    """
    def unknown(reason: str) -> dict:
        return {"status": "UNKNOWN", "reason": reason, "packet": None,
                "auto_inject": False}

    if provider not in {"claude", "codex"}:
        return unknown("unknown_provider")
    if type(compaction_ordinal) is not int or compaction_ordinal < 1:
        return unknown("invalid_compaction_ordinal")
    if not isinstance(source_path, str) or not source_path.strip():
        return unknown("missing_source")
    path = Path(source_path)
    if not path.is_file():
        return unknown("missing_source")

    # Tracker intentionally tolerates corrupt unrelated lines for the live UI.
    # Recovery cannot claim a complete source interval if the source is corrupt.
    try:
        with path.open("rb") as source:
            for raw in source:
                if not raw.endswith(b"\n"):
                    return unknown("incomplete_source_line")
                if not isinstance(json.loads(raw), dict):
                    return unknown("invalid_source_row")
    except (OSError, UnicodeError, ValueError):
        return unknown("unreadable_source")

    parser = CodexTracker(path) if provider == "codex" else Tracker(path)
    parser.poll()
    if parser.offset != path.stat().st_size:
        return unknown("incomplete_source_line")
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
    prefix = CodexTracker(path) if provider == "codex" else Tracker(path)
    messages = {}
    try:
        with path.open("rb") as source:
            for line_no, raw in enumerate(source, 1):
                if line_no >= cutoff:
                    break
                rec = json.loads(raw)
                message = _native_message(rec, provider)
                if message is not None:
                    messages[line_no] = message
                prefix._handle(rec, line_no)
    except (OSError, UnicodeError, ValueError):
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
            "source_ref": f"{path.resolve()}:{strand.owner_line}-{end_line}",
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
        result["compaction_source_ref"] = f"{path.resolve()}:{cutoff}"
    return result
