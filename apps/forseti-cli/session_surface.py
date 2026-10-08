#!/usr/bin/env python3
"""Fast desktop surface for the active Claude or Codex transcript.

This entry point intentionally reads no Forseti repository state.  The native
app is installed on APFS while the project lives on an external exFAT volume;
macOS can indefinitely block GUI-launched children that open that volume.
The primary window only needs the live transcript, so keep that path local and
leave repository audits to explicit background commands.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import owner as owner_classifier
import betrayal
import source_tree_schema
import vitals
from tracker import tracker_for

_CLAUDE_FOCUS_CACHE: tuple[float, tuple[str, float]] = (0.0, ("", 0.0))


def latest_under(root: Path) -> Path | None:
    best: tuple[float, Path] | None = None
    if not root.is_dir():
        return None
    for path in root.rglob("*.jsonl"):
        try:
            item = (path.stat().st_mtime, path)
        except OSError:
            continue
        if best is None or item[0] > best[0]:
            best = item
    return best[1] if best else None


_CODEX_FOCUS_RE = re.compile(
    r"^(\S+).*thread_stream_view_activity_changed "
    r"active=true conversationId=([0-9a-fA-F-]{20,})"
    r".*rendererWindowAppearance=primary "
    r"rendererWindowFocused=true.*rendererWindowVisible=true"
)
_SESSION_ID_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)
_ISO_LINE_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z)")


def latest_codex_focused_session(root: Path | None = None) -> str:
    """Return the last Session the owner actually brought to the foreground.

    Codex writes this event on a task switch even when that transcript receives
    no new message.  JSONL mtime therefore cannot substitute for this signal.
    Only a visible, focused primary window counts; background workers and browser
    webviews must not steal the Forseti surface.
    """
    logs = root or (Path.home() / "Library" / "Logs" / "com.openai.codex")
    if not logs.is_dir():
        return ""
    try:
        candidates = sorted(
            logs.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
        )[:12]
    except OSError:
        return ""
    best: tuple[str, str] | None = None
    for path in candidates:
        try:
            with path.open("rb") as fh:
                size = path.stat().st_size
                fh.seek(max(0, size - 4 * 1024 * 1024))
                text = fh.read().decode("utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            match = _CODEX_FOCUS_RE.search(line)
            if match and (best is None or match.group(1) > best[0]):
                best = (match.group(1), match.group(2))
    return best[1] if best else ""


def latest_claude_focused_session() -> tuple[str, float]:
    """Return Claude's last foreground session and its real focus timestamp."""
    global _CLAUDE_FOCUS_CACHE
    if time.monotonic() - _CLAUDE_FOCUS_CACHE[0] < 3.0:
        return _CLAUDE_FOCUS_CACHE[1]
    root = (Path.home() / "Library" / "Application Support" / "Claude" /
            "claude-code-sessions")
    best = ("", 0.0)
    if not root.is_dir():
        _CLAUDE_FOCUS_CACHE = (time.monotonic(), best)
        return best
    for path in root.rglob("local_*.json"):
        try:
            raw = path.read_bytes()
            item = json.loads(raw)
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if item.get("isArchived") or not item.get("cliSessionId"):
            continue
        focused = float(item.get("lastFocusedAt") or 0) / 1000.0
        if focused > best[1]:
            best = (str(item["cliSessionId"]), focused)
    _CLAUDE_FOCUS_CACHE = (time.monotonic(), best)
    return best


def latest_codex_focus_timestamp(root: Path | None = None) -> float:
    """Read the event timestamp, not log-file mtime (background writes lie)."""
    import datetime
    logs = root or (Path.home() / "Library" / "Logs" / "com.openai.codex")
    best = 0.0
    if not logs.is_dir():
        return best
    for path in logs.rglob("*.log"):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            if "thread_stream_view_activity_changed active=true" not in line:
                continue
            match = _ISO_LINE_RE.match(line)
            if match:
                try:
                    at = datetime.datetime.fromisoformat(
                        match.group(1).replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                best = max(best, at)
    return best


def _find_session(requested: str, roots: list[Path]) -> Path | None:
    direct = Path(requested).expanduser()
    if direct.is_file():
        return direct
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            if requested in path.name:
                return path
    return None


def resolve_requested(value: str, *, logs_root: Path | None = None) -> Path | None:
    requested = value.strip()
    roots = [Path.home() / ".codex" / "sessions",
             Path.home() / ".claude" / "projects"]
    if requested:
        return _find_session(requested, roots)

    # Compare both providers before choosing.  Previously this function
    # checked Codex first, so any Codex focus log could permanently mask Claude.
    claude_id, claude_at = latest_claude_focused_session()
    codex_id = latest_codex_focused_session(logs_root)
    codex_at = latest_codex_focus_timestamp(logs_root)
    if claude_id and claude_at >= codex_at:
        target = _find_session(claude_id, roots)
        if target is not None:
            return target
    if codex_id:
        target = _find_session(codex_id, roots)
        if target is not None:
            return target

    if not requested:
        hint = Path.home() / ".forseti" / "current-session-id"
        try:
            requested = hint.read_text(encoding="utf-8").strip()
        except OSError:
            requested = ""
    if requested:
        return _find_session(requested, roots)
    candidates = [p for p in (latest_under(root) for root in roots) if p]
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def main(argv: list[str]) -> int:
    target = resolve_requested(argv[1] if len(argv) > 1 else "")
    if target is None:
        print(json.dumps({"error": "找不到 Claude 或 Codex transcript"},
                         ensure_ascii=False))
        return 2

    parser = tracker_for(target)
    parser.poll()
    snap = parser.snapshot(tail=180)
    rows = snap.get("rows") or []
    betrayals_by_n: dict[int, list[dict]] = {}
    for finding in betrayal.scan(parser.strands):
        betrayals_by_n.setdefault(finding.get("n", 0), []).append(finding)
    for row in rows:
        classified = owner_classifier.classify(row.get("owner_text") or "")
        row["owner_message_kind"] = classified.kind
        row["owner_message_why"] = classified.why
        row["corrected_by_owner"] = vitals.is_correction(
            row.get("owner_text") or "")
        hits = betrayals_by_n.get(row.get("n"))
        if hits:
            row["betrayals"] = hits
    goal_changes = vitals.owner_goal_change_candidates(rows)
    goal_change_by_n = {item.get("n"): item for item in goal_changes}
    for row in rows:
        candidate = goal_change_by_n.get(row.get("n"))
        if candidate:
            row["owner_goal_change_candidate"] = True
            row["owner_goal_change_state"] = candidate.get("kind")
    for row, goal in zip(rows, vitals.goal_support(rows)):
        row["goal"] = goal
    goals = [row.get("goal") for row in rows]
    snap_dims = vitals.dimensions(rows, snap, goals)
    snap["dims"] = snap_dims
    snap["temp"] = vitals.temperature(snap_dims)
    snap["progress"] = vitals.progress_layers(rows)
    source_tree_schema.annotate_rows(rows)
    provider = "codex" if ".codex" in target.parts else "claude"
    id_match = _SESSION_ID_RE.search(target.name)
    session = id_match.group(1) if id_match else target.stem
    followed = latest_codex_focused_session()
    picked_by = ("跟著 Codex 前景" if followed == session
                 else f"鎖定 {provider.title()} Session")
    snap.update({
        "provider": provider,
        "session": session,
        "ui_id": session,
        "picked_by": picked_by,
        "advice": {
            "text": "正在跟隨目前 Session",
            "why": f"直接讀取 {provider} transcript；未以重複讀取充當驗證",
            "tone": "info",
            "n": 0,
        },
        "cards": [],
        "source_tree_schema": source_tree_schema.schema(),
        "semantic_surface": {
            "scope": "owner direction, AI answers, corrections, tool evidence, and explicit unknowns",
            "north_star_comparison": "TURN_LEVEL_OWNER_CORRECTION_AND_EVIDENCE",
            "unknown_is_not_aligned": True,
        },
    })
    print(json.dumps(snap, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
