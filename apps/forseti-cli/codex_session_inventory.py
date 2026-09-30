#!/usr/bin/env python3
"""Read Codex's local session index for Forseti's session picker."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def _epoch(value: object) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return 0.0


def list_sessions(sessions_root: Path, index_path: Path) -> list[dict]:
    """Return on-disk Codex sessions with index titles and explicit provenance."""
    titles: dict[str, tuple[str, float]] = {}
    try:
        lines = index_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        sid = row["id"].strip()
        if not sid:
            continue
        title = row.get("thread_name")
        title = title.strip() if isinstance(title, str) else ""
        titles[sid] = (title, _epoch(row.get("updated_at")))

    out = []
    if not sessions_root.is_dir():
        return out
    for path in sessions_root.rglob("*.jsonl"):
        sid = next((key for key in titles if key in path.name), "")
        if not sid:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        title, indexed_at = titles[sid]
        out.append({
            "id": sid,
            "ui_id": sid,
            "title": title or sid[:8],
            "turns": 0,
            "focused_at": 0,
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "project": "codex",
            "group": "Codex",
            "named": bool(title),
            "provider": "codex",
            "title_source": "codex_session_index" if title else "UNKNOWN",
            "indexed_at": indexed_at,
        })
    out.sort(key=lambda row: (row["indexed_at"] or row["mtime"]), reverse=True)
    return out


def title_for(session_id: str, index_path: Path) -> str:
    """Return an exact indexed title for one Codex session, or empty UNKNOWN."""
    wanted = str(session_id or "").strip()
    if not wanted:
        return ""
    try:
        lines = index_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            continue
        if not isinstance(row, dict) or row.get("id") != wanted:
            continue
        title = row.get("thread_name")
        return title.strip() if isinstance(title, str) else ""
    return ""
