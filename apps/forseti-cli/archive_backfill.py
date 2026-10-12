#!/usr/bin/env python3
"""Bounded, resumable import of native session transcripts into the raw archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from pathlib import Path

import source_archive


_UUID = re.compile(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl\Z")
DEFAULT_ROOT = Path("/Volumes/NewDrive/AI Project/Forseti/.forseti/session_archive")


def sources(home: Path) -> list[tuple[str, str, Path]]:
    found = []
    for provider, root in (("codex", home / ".codex/sessions"),
                           ("claude", home / ".claude/projects")):
        if not root.is_dir():
            continue
        for path in root.rglob("*.jsonl"):
            match = _UUID.search(path.name)
            if path.is_symlink() or not path.is_file():
                continue
            session_id = match.group(1) if match else "file-" + hashlib.sha256(
                (provider + ":" + str(path.relative_to(root))).encode()).hexdigest()
            found.append((provider, session_id, path))
    found.sort(key=lambda row: (row[0], str(row[2])))
    seen = set()
    unique = []
    for provider, session_id, path in found:
        if (provider, session_id) in seen:
            root = home / (".codex/sessions" if provider == "codex"
                           else ".claude/projects")
            session_id = "file-" + hashlib.sha256(
                (provider + ":" + str(path.relative_to(root))).encode()).hexdigest()
        seen.add((provider, session_id))
        unique.append((provider, session_id, path))
    return unique


def import_batch(*, home: Path, archive_root: Path, start: int,
                 limit: int, seconds: float,
                 inventory: list[tuple[str, str, Path]] | None = None) -> dict:
    if inventory is None:
        inventory = sources(home)
    begun = time.monotonic()
    next_index = start
    counts = {"READY": 0, "UNKNOWN": 0, "IN_PROGRESS": 0}
    reasons: dict[str, int] = {}
    unknown_items = []
    while next_index < len(inventory) and next_index - start < limit:
        if time.monotonic() - begun >= seconds:
            break
        provider, session_id, path = inventory[next_index]
        while True:
            result = source_archive.sync_source(
                source_path=path, archive_root=archive_root,
                provider=provider, session_id=session_id,
                source_finalized=True)
            if result["status"] != "IN_PROGRESS":
                break
            if time.monotonic() - begun >= seconds:
                break
        status = result["status"]
        counts[status] += 1
        if status == "UNKNOWN":
            reason = result["reason"]
            reasons[reason] = reasons.get(reason, 0) + 1
            unknown_items.append({"index": next_index, "provider": provider,
                                  "session_id": session_id, "reason": reason})
        if status == "IN_PROGRESS":
            break
        next_index += 1
    return {"inventory": len(inventory), "start": start,
            "next_index": next_index, "counts": counts,
            "unknown_reasons": reasons, "unknown_items": unknown_items,
            "scan_complete": next_index == len(inventory),
            "batch_all_ready": counts["UNKNOWN"] == 0
            and counts["IN_PROGRESS"] == 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--seconds", type=float, default=120)
    args = parser.parse_args()
    if args.start < 0 or args.limit < 1 or args.seconds <= 0:
        parser.error("start, limit, or seconds out of range")
    print(json.dumps(import_batch(home=args.home, archive_root=args.archive_root,
                                  start=args.start, limit=args.limit,
                                  seconds=args.seconds), sort_keys=True))


if __name__ == "__main__":
    main()
