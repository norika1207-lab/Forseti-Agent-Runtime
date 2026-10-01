#!/usr/bin/env python3
"""Repeatable, privacy-preserving validation of Forseti's live session follower."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

import desktop_api as desktop
import owner as owner_classifier


SCHEMA_VERSION = "forseti-session-follow-validation@1"


def _normal(value: object) -> str:
    return " ".join(str(value or "").split())


def _hash_text(value: object) -> str:
    return hashlib.sha256(_normal(value).encode("utf-8")).hexdigest()[:20]


def _assistant_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return " ".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") == "text"
    )


def raw_tail_fingerprints(path: Path) -> dict:
    """Read the source independently and retain hashes, never transcript text."""
    owner = ""
    assistant = ""
    valid_records = 0
    malformed_records = 0
    excluded_system_user_records = 0
    session_ids: set[str] = set()
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except (TypeError, ValueError, UnicodeError):
                malformed_records += 1
                continue
            if not isinstance(row, dict):
                malformed_records += 1
                continue
            valid_records += 1
            sid = row.get("sessionId")
            if isinstance(sid, str) and sid:
                session_ids.add(sid)
            message = row.get("message")
            message = message if isinstance(message, dict) else {}
            content = message.get("content")
            if row.get("type") == "user" and isinstance(content, str) \
                    and not row.get("isMeta"):
                if owner_classifier.is_owner_text(content):
                    owner = content
                else:
                    excluded_system_user_records += 1
            elif row.get("type") == "assistant":
                assistant = _assistant_text(content)
    stat = path.stat()
    return {
        "path_hash": hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:20],
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "valid_records": valid_records,
        "malformed_records": malformed_records,
        "excluded_system_user_records": excluded_system_user_records,
        "session_ids": sorted(session_ids),
        "owner_hash": _hash_text(owner),
        "assistant_hash": _hash_text(assistant),
    }


def _source_path(session_id: str, base: Path) -> Path | None:
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    filename = session_id.strip() + ".jsonl"
    hits = sorted(path for path in base.rglob("*.jsonl")
                  if path.name == filename)
    return hits[0] if len(hits) == 1 else None


def _semantic_summary(rows: list[dict]) -> dict:
    states = Counter()
    epistemics = Counter()
    missing_contract = 0
    correction_proxy_misses = 0
    deterministic_deviations = 0
    inferred_deviations = 0
    for row in rows:
        semantic = row.get("path_semantics")
        if not isinstance(semantic, dict):
            missing_contract += 1
            continue
        state = str(semantic.get("state") or "missing")
        states[state] += 1
        epistemics[str(semantic.get("epistemic") or "missing")] += 1
        predicted = state in {"suspected", "confirmed"}
        if state == "confirmed":
            deterministic_deviations += 1
        elif state == "suspected":
            inferred_deviations += 1
        if row.get("corrected_by_owner") and not predicted:
            correction_proxy_misses += 1
    return {
        "rows": len(rows),
        "states": dict(sorted(states.items())),
        "epistemics": dict(sorted(epistemics.items())),
        "missing_contract": missing_contract,
        "deterministic_deviations": deterministic_deviations,
        "inferred_deviations": inferred_deviations,
        "owner_correction_missed_by_path_state_proxy": correction_proxy_misses,
        "ground_truth_status": "PARTIAL_PROXY_ONLY",
        "ground_truth_note": (
            "owner correction is only a locator, not automatic proof of drift; "
            "suspected is inference and confirmed requires structured contradiction"
        ),
    }


def validate_once(base: Path, raw_cache: dict) -> dict:
    started = time.perf_counter()
    # _meta_rows is intentionally not used as a second source of truth: the
    # public follower contract is the desktop API's focused_session result.
    # This also keeps the check on the same metadata path used by strands().
    expected = desktop.focused_session()
    snapshot = desktop.strands(persist=False)
    actual = str(snapshot.get("session") or "")
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    source = _source_path(actual, base) if actual else None
    errors = []
    if not expected:
        errors.append("NO_FOCUSED_SESSION")
    if actual != expected:
        errors.append("FOLLOWED_SESSION_MISMATCH")
    if snapshot.get("picked_by") != "跟著你":
        errors.append("NOT_PICKED_BY_FOCUS")
    if source is None:
        errors.append("SOURCE_NOT_UNIQUE_OR_MISSING")
    if not rows:
        errors.append("NO_RENDER_ROWS")

    raw = {}
    if source is not None:
        stat = source.stat()
        cache_key = (str(source), stat.st_size, stat.st_mtime_ns)
        raw = raw_cache.get(cache_key)
        if raw is None:
            raw = raw_tail_fingerprints(source)
            raw_cache.clear()
            raw_cache[cache_key] = raw
        if raw["malformed_records"]:
            errors.append("MALFORMED_SOURCE_RECORD")
        if raw["session_ids"] and actual not in raw["session_ids"]:
            errors.append("SOURCE_SESSION_ID_MISMATCH")
        last = rows[-1] if rows else {}
        if raw["owner_hash"] != _hash_text(last.get("owner_text")):
            errors.append("OWNER_TAIL_MISMATCH")
        if raw["assistant_hash"] != _hash_text(last.get("ai_text")):
            errors.append("ASSISTANT_TAIL_MISMATCH")

    semantic = _semantic_summary(rows)
    if semantic["missing_contract"]:
        errors.append("MISSING_PATH_SEMANTICS")
    public_raw = {
        key: value for key, value in raw.items() if key != "session_ids"
    }
    if raw:
        public_raw["session_id_count"] = len(raw.get("session_ids") or [])
    return {
        "status": "PASS" if not errors else "FAIL",
        "expected_session_hash": _hash_text(expected),
        "actual_session_hash": _hash_text(actual),
        "picked_by": snapshot.get("picked_by"),
        "source": public_raw,
        "semantic": semantic,
        "divergence": snapshot.get("divergence") or {"has": False},
        "errors": errors,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }


def run(iterations: int, delay_ms: int, base: Path) -> tuple[dict, int]:
    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if delay_ms < 0:
        raise ValueError("delay_ms must be >= 0")
    started = time.perf_counter()
    rounds = []
    raw_cache: dict = {}
    for index in range(iterations):
        row = validate_once(base, raw_cache)
        row["iteration"] = index + 1
        rounds.append(row)
        if delay_ms and index + 1 < iterations:
            time.sleep(delay_ms / 1000)

    failures = [row for row in rounds if row["status"] != "PASS"]
    sessions = Counter(row["actual_session_hash"] for row in rounds)
    semantic_signatures = Counter(
        json.dumps(row["semantic"], ensure_ascii=True, sort_keys=True)
        for row in rounds
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "validated_scope": "CLAUDE_FOCUSED_SESSION",
        "cross_provider_follow_status": "NOT_IMPLEMENTED",
        "cross_provider_note": (
            "the live follower reads Claude lastFocusedAt metadata only; "
            "it cannot claim to follow the current Codex task"
        ),
        "iterations_requested": iterations,
        "iterations_completed": len(rounds),
        "sessions_followed": dict(sorted(sessions.items())),
        "focus_changes_observed": max(0, len(sessions) - 1),
        "semantic_snapshots_distinct": len(semantic_signatures),
        "semantic_latest": rounds[-1]["semantic"] if rounds else {},
        "divergence_latest": rounds[-1]["divergence"] if rounds else {},
        "failure_count": len(failures),
        "error_types": dict(sorted(Counter(
            error for row in failures for error in row["errors"]
        ).items())),
        "rounds": rounds,
        "duration_ms": round((time.perf_counter() - started) * 1000, 3),
    }
    return report, 0 if report["status"] == "PASS" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--delay-ms", type=int, default=50)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--projects", type=Path,
                        default=Path.home() / ".claude" / "projects")
    args = parser.parse_args(argv)
    if args.iterations < 1 or args.delay_ms < 0:
        parser.error("iterations must be >= 1 and delay-ms must be >= 0")
    report, code = run(args.iterations, args.delay_ms, args.projects)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.json_output.with_suffix(args.json_output.suffix + ".tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True,
                              indent=2) + "\n", encoding="utf-8")
    tmp.replace(args.json_output)
    print(json.dumps({
        "status": report["status"],
        "iterations_completed": report["iterations_completed"],
        "failure_count": report["failure_count"],
        "sessions_followed": report["sessions_followed"],
        "semantic_latest": report["semantic_latest"],
        "duration_ms": report["duration_ms"],
    }, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())


# This module is deliberately importable by offline test runners; it does not
# start a provider, poll a GUI, or mutate a session source.
