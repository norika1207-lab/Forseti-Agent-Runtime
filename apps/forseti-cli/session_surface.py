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
from pathlib import Path

import owner as owner_classifier
import betrayal
import lanes
import source_tree_schema
import vitals
from tracker import tracker_for


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
_CODEX_OWNER_ROUTE_RE = re.compile(
    r"^(\S+).*IAB_LIFECYCLE received browser sidebar owner sync "
    r".*ownerRoutePath=/local/"
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:\s|$)"
)
_SESSION_ID_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)


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
            match = (_CODEX_FOCUS_RE.search(line)
                     or _CODEX_OWNER_ROUTE_RE.search(line))
            if match and (best is None or match.group(1) > best[0]):
                best = (match.group(1), match.group(2))
    return best[1] if best else ""


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

    focused = latest_codex_focused_session(logs_root)
    if focused:
        target = _find_session(focused, roots)
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
    # The primary transcript is an evidence surface.  A fixed tail silently
    # omitted early turns in long sessions (195 real turns became 180), which
    # made the visible conversation impossible to audit end to end.
    snap = parser.snapshot(tail=len(parser.strands))
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
    # Keep the fast foreground-follow path visually equivalent to the full
    # surface.  The SVG renderer can only draw branch tracks when this contract
    # is present; omitting it reduced every session to a straight main line.
    snap["lanes"] = lanes.summary(rows)
    source_tree_schema.annotate_rows(rows)

    # Node details are part of the primary evidence surface.  The fast follow
    # path used to omit these fields, leaving clickable nodes with no record of
    # why a path diverged, when it recovered, or what the owner had marked.
    try:
        import goalgate
        last_correction = next(
            (i for i in range(len(rows) - 1, -1, -1)
             if rows[i].get("corrected_by_owner")), None)
        since = (len(rows) - 1 - last_correction
                 if last_correction is not None else None)
        actions: list[str] = []
        for row in rows[-12:]:
            if row.get("ai_text"):
                actions.append(str(row["ai_text"]))
            actions.extend(str(dot.get("detail")) for dot in row.get("dots", [])
                           if dot.get("detail"))
        gate = goalgate.gate(actions=actions, turns_since_owner=since)
        alerts = vitals.drift_alerts(rows, gate)
        by_n = {item["n"]: item for item in alerts}
        for row in rows:
            alert = by_n.get(row.get("n"))
            if alert:
                row["drift_alert"] = dict(
                    alert, prompt=vitals.drift_prompt(alert))
        snap["goal_gate"] = gate
        snap["drift_alerts"] = len(alerts)
    except Exception as exc:
        snap["goal_gate"] = {"ok": False, "note": str(exc)[:160]}
        snap["drift_alerts"] = 0

    try:
        import divergence
        snap["divergence"] = divergence.summary(rows)
    except Exception as exc:
        snap["divergence"] = {"has": False, "why": str(exc)[:160]}
    try:
        import latency
        snap["latency"] = latency.summary(rows)
    except Exception as exc:
        snap["latency"] = {"has": False, "why": str(exc)[:160]}

    session_for_records = (_SESSION_ID_RE.search(target.name).group(1)
                           if _SESSION_ID_RE.search(target.name)
                           else target.stem)
    try:
        import notes
        notes_by_turn = notes.by_turn(session_for_records)
        for row in rows:
            found = notes_by_turn.get(int(row.get("n") or 0))
            if found:
                row["notes"] = [{"text": item.get("text", ""),
                                 "at": item.get("at")} for item in found]
        snap["notes"] = notes.summary(session_for_records)
    except Exception as exc:
        snap["notes"] = {"total": 0, "turns": [], "why": str(exc)[:160]}
    try:
        import checkpoint
        saved = checkpoint.load(session=session_for_records)
        by_turn: dict[int, list[dict]] = {}
        for item in saved:
            by_turn.setdefault(int(item.get("n") or 0), []).append(item)
        for row in rows:
            found = by_turn.get(int(row.get("n") or 0))
            if found:
                row["checkpoint"] = {
                    "n": len(found),
                    "last_good": any(item.get("last_good") for item in found),
                    "reason": found[-1].get("reason", ""),
                }
        snap["checkpoints"] = checkpoint.summary(session_for_records)
    except Exception as exc:
        snap["checkpoints"] = {"total": 0, "rows": [], "why": str(exc)[:160]}
    provider = "codex" if ".codex" in target.parts else "claude"
    id_match = _SESSION_ID_RE.search(target.name)
    session = id_match.group(1) if id_match else target.stem
    followed = latest_codex_focused_session()
    session_title = ""
    if provider == "codex":
        from codex_session_inventory import title_for
        session_title = title_for(
            session, Path.home() / ".codex" / "session_index.jsonl")
    picked_by = ("跟著 Codex 前景" if followed == session
                 else f"鎖定 {provider.title()} Session")
    snap.update({
        "provider": provider,
        "session": session,
        "session_title": session_title,
        "ui_id": session,
        "picked_by": picked_by,
        "advice": {
            "text": "正在跟隨目前 Session",
            "why": f"直接讀取 {provider} transcript；未以重複讀取充當驗證",
            "tone": "info",
            "n": 0,
        },
        "temp": {"c": None, "band": "UNKNOWN", "coverage": 0,
                 "why": "首屏只讀 Session；深度語意分析尚未完成"},
        "progress": {"activity": 0, "task": 0},
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
