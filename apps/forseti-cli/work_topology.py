#!/usr/bin/env python3
"""Canonical work topology from durable Commander/Codex records.

This module deliberately reads the local Codex thread index/history database,
not a desktop surface or a live-process list.  A missing connector is an
unknown state, never an empty task list.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

THREAD_TITLE = re.compile(r"^Forseti\s+(Worker|Verifier)\b", re.IGNORECASE)
SHA = re.compile(r"(?<![0-9a-f])([0-9a-f]{7,40})(?![0-9a-f])", re.IGNORECASE)
WORK_ORDER = re.compile(r"\b(FOR-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b")

TERMINAL_THREAD_STATUSES = {"completed", "complete", "success", "succeeded"}
FAILED_THREAD_STATUSES = {"failed", "error", "cancelled", "canceled"}


def _epoch(value: object) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _iso(epoch: float) -> str | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _read_index(path: Path) -> tuple[list[dict], str | None]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [], f"session index unavailable: {exc}"
    rows: dict[str, dict] = {}
    nonempty = False
    valid_json = 0
    for line in lines:
        if line.strip():
            nonempty = True
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        valid_json += 1
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        title = row.get("thread_name")
        if not isinstance(title, str) or not THREAD_TITLE.search(title.strip()):
            continue
        sid = row["id"].strip()
        if not sid:
            continue
        # The index is append-only in practice.  Last occurrence is the
        # authoritative title/update pair for one thread, and this makes
        # duplicate index events idempotent.
        rows[sid] = {
            "thread_id": sid,
            "title": title.strip(),
            "updated_at": row.get("updated_at"),
            "updated_epoch": _epoch(row.get("updated_at")),
        }
    if nonempty and not valid_json:
        return [], "session index unavailable: no valid JSON records"
    return list(rows.values()), None


def _open_history(path: Path):
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = {row[0] for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"thread_turns", "thread_items"}
        if not required <= tables:
            con.close()
            return None, "thread history unavailable: required tables missing"
        return con, None
    except (OSError, sqlite3.Error) as exc:
        return None, f"thread history unavailable: {exc}"


def _thread_rows(con: sqlite3.Connection, thread_id: str) -> list[dict]:
    try:
        rows = con.execute(
            "SELECT turn_id,status,started_at,completed_at,rollout_ordinal "
            "FROM thread_turns WHERE thread_id=? ORDER BY rollout_ordinal",
            (thread_id,),
        ).fetchall()
    except sqlite3.Error:
        return []
    return [{
        "turn_id": row[0],
        "status": str(row[1] or ""),
        "started_at": float(row[2] or 0),
        "completed_at": float(row[3] or 0),
        "rollout_ordinal": row[4] or 0,
    } for row in rows]


def _thread_text(con: sqlite3.Connection, thread_id: str) -> str:
    try:
        rows = con.execute(
            "SELECT item_json FROM thread_items WHERE thread_id=? "
            "ORDER BY rollout_ordinal,created_at_ms",
            (thread_id,),
        ).fetchall()
    except sqlite3.Error:
        return ""
    pieces: list[str] = []
    for (raw,) in rows:
        try:
            item = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str):
            pieces.append(text)
        # commandExecution records are useful provenance for an explicitly
        # printed HEAD/candidate/verifier receipt, but never make a state.
        command = item.get("command")
        if isinstance(command, str):
            pieces.append(command)
    return "\n".join(pieces)


def _role(title: str) -> str:
    match = THREAD_TITLE.search(title or "")
    if not match:
        return "UNKNOWN"
    return "verifier" if match.group(1).lower() == "verifier" else "worker"


def _candidate_commit(text: str) -> tuple[str | None, str]:
    if not text:
        return None, "thread history contains no commit receipt"
    lines = text.splitlines()
    # Prefer explicit delivery/candidate fields over arbitrary hashes in logs.
    preferred = re.compile(r"(?:candidate|commit|verified_commit|head)\s*[:=]\s*[`'\"]?([0-9a-f]{7,40})",
                           re.IGNORECASE)
    for line in reversed(lines):
        match = preferred.search(line)
        if match:
            return match.group(1), "explicit commit receipt in thread history"
    return None, "no explicit candidate commit receipt"


def _verdict(text: str, role: str) -> tuple[str | None, str]:
    if role != "verifier":
        return None, "not a verifier thread"
    if not text:
        return None, "verifier thread has no durable message text"
    for line in reversed(text.splitlines()):
        upper = line.upper()
        if re.search(r"\b(VERIFICATION_FAILED|FAIL(?:ED)?|BLOCKED)\b", upper):
            return "FAIL", "explicit verifier result in thread history"
        if re.search(r"\b(PASS(?:ED)?|VERIFIED(?:_COMPLETE)?)\b", upper):
            return "PASS", "explicit verifier result in thread history"
    return None, "no explicit verifier verdict receipt"


def _work_order_id(text: str) -> str | None:
    matches = WORK_ORDER.findall(text or "")
    return matches[-1] if matches else None


def _normalize_state(role: str, status: str) -> tuple[str, str]:
    lowered = status.strip().lower()
    if lowered in TERMINAL_THREAD_STATUSES:
        return "COMPLETED", "thread_turns.status"
    if lowered in FAILED_THREAD_STATUSES:
        return "FAILED", "thread_turns.status"
    if lowered in {"blocked", "waiting", "waiting_dependency"}:
        return "BLOCKED", "thread_turns.status"
    if lowered in {"inprogress", "in_progress", "running", "started"}:
        return ("VERIFYING" if role == "verifier" else "ACTIVE"), "thread_turns.status"
    return "UNKNOWN", "unrecognized thread_turns.status"


def _item(index_row: dict, turns: list[dict], text: str, *, now: float,
          stale_after_sec: float) -> dict:
    role = _role(index_row["title"])
    latest = turns[-1] if turns else None
    raw_status = latest["status"] if latest else ""
    state, state_source = _normalize_state(role, raw_status)
    observed_epoch = max(
        index_row.get("updated_epoch", 0.0),
        (latest or {}).get("completed_at", 0.0),
        (latest or {}).get("started_at", 0.0),
    )
    stale = bool(state in {"ACTIVE", "VERIFYING"} and observed_epoch
                 and now - observed_epoch > stale_after_sec)
    if stale:
        state = "UNKNOWN"
        state_source = "stale thread record"
    commit, commit_basis = _candidate_commit(text)
    verdict, verdict_basis = _verdict(text, role)
    return {
        "work_order_id": _work_order_id(text),
        "work_order_title": index_row["title"],
        "thread_id": index_row["thread_id"],
        "role": role,
        "state": state,
        "state_reason": ("thread record is older than stale threshold"
                         if stale else raw_status or "missing thread turn"),
        "candidate_commit": commit,
        "candidate_commit_reason": commit_basis,
        "verifier_verdict": verdict,
        "verifier_verdict_reason": verdict_basis,
        "updated_at": index_row.get("updated_at") or _iso(observed_epoch),
        "updated_epoch": observed_epoch or None,
        "stale": stale,
        "source": {
            "type": "codex_thread_history",
            "index": "~/.codex/session_index.jsonl",
            "history": "~/.codex/thread_history_1.sqlite",
            "state_field": state_source,
        },
    }


def build_topology(*, index_path: Path | None = None,
                   history_path: Path | None = None, now: float | None = None,
                   stale_after_sec: float = 24 * 60 * 60) -> dict:
    """Return canonical worker/verifier records or explicit unavailable state."""
    index_path = index_path or (Path.home() / ".codex" / "session_index.jsonl")
    history_path = history_path or (Path.home() / ".codex" / "thread_history_1.sqlite")
    index_rows, index_error = _read_index(index_path)
    if index_error:
        return _unavailable(index_error, index_path, history_path)
    con, history_error = _open_history(history_path)
    if history_error:
        return _unavailable(history_error, index_path, history_path)
    now = now if now is not None else datetime.now(tz=timezone.utc).timestamp()
    try:
        items = []
        for row in index_rows:
            turns = _thread_rows(con, row["thread_id"])
            text = _thread_text(con, row["thread_id"])
            items.append(_item(row, turns, text, now=now,
                               stale_after_sec=stale_after_sec))
    finally:
        con.close()
    # Stable identity is the Codex thread id.  Index duplicates have already
    # collapsed; sorting keeps output deterministic for UI and tests.
    items.sort(key=lambda item: (item["updated_epoch"] or 0, item["thread_id"]),
               reverse=True)
    counts = {"total": len(items), "active": 0, "verifying": 0,
              "completed": 0, "failed": 0, "blocked": 0, "unknown": 0}
    for item in items:
        key = item["state"].lower()
        counts[key] = counts.get(key, 0) + 1
    return {
        "available": True,
        "state": "AVAILABLE",
        "reason": "authoritative Codex thread index and history loaded",
        "authoritative_empty": not items,
        "items": items,
        "counts": counts,
        "source": {
            "type": "codex_thread_history",
            "index": str(index_path),
            "history": str(history_path),
        },
    }


def _unavailable(reason: str, index_path: Path, history_path: Path) -> dict:
    return {
        "available": False,
        "state": "UNKNOWN",
        "reason": reason,
        "authoritative_empty": False,
        "items": [],
        "counts": {"total": None, "active": None, "verifying": None,
                   "completed": None, "failed": None, "blocked": None,
                   "unknown": None},
        "source": {"type": "codex_thread_history",
                   "index": str(index_path), "history": str(history_path)},
    }


def topology(*, index_path: Path | None = None,
             history_path: Path | None = None, now: float | None = None,
             stale_after_sec: float = 24 * 60 * 60) -> dict:
    """Public alias kept short for desktop_api and offline callers."""
    return build_topology(index_path=index_path, history_path=history_path,
                          now=now, stale_after_sec=stale_after_sec)
