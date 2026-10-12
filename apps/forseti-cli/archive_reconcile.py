#!/usr/bin/env python3
"""Periodic, bounded reconciliation of native session files into the archive."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path

import archive_backfill
import source_archive


RECEIPT = source_archive._ANCHOR_DIR / "backfill-status.json"
LOCK = source_archive._ANCHOR_DIR / "backfill.lock"
MAX_SECONDS = 300
MAX_SOURCES = 500


def _check_archive_access(root: Path) -> None:
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    os.close(fd)


def _write_receipt(path: Path, result: dict) -> None:
    source_archive._secure_local_dir(path.parent)
    temp = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(json.dumps(result, sort_keys=True).encode() + b"\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temp.unlink(missing_ok=True)


def _inventory_digest(inventory: list[tuple[str, str, Path]]) -> str:
    digest = hashlib.sha256()
    for provider, session_id, path in inventory:
        for value in (provider, session_id, str(path)):
            digest.update(value.encode())
            digest.update(b"\0")
    return digest.hexdigest()


def _resume(receipt: Path, digest: str,
            inventory: list[tuple[str, str, Path]]) -> tuple[int, dict, dict, int]:
    empty = {"READY": 0, "UNKNOWN": 0, "IN_PROGRESS": 0}
    try:
        if receipt.is_symlink() or receipt.stat().st_size > 65536:
            return 0, empty, {}, int(time.time())
        previous = json.loads(receipt.read_text())
        cursor = previous.get("cursor")
        counts = previous.get("counts")
        reasons = previous.get("unknown_reasons")
        if (type(cursor) is not int or not 0 <= cursor < len(inventory)
                or (previous.get("inventory_sha256") != digest
                    and previous.get("prefix_sha256") != _inventory_digest(inventory[:cursor]))
                or not isinstance(counts, dict) or not isinstance(reasons, dict)
                or any(type(counts.get(status)) is not int or counts[status] < 0
                       for status in empty)
                or counts["READY"] + counts["UNKNOWN"] != cursor
                or any(type(value) is not int or value < 0 for value in reasons.values())):
            return 0, empty, {}, int(time.time())
        return cursor, {**counts, "IN_PROGRESS": 0}, reasons, previous.get("started_at", int(time.time()))
    except (OSError, ValueError, TypeError):
        return 0, empty, {}, int(time.time())


def run_once(*, home: Path = Path.home(),
             archive_root: Path = archive_backfill.DEFAULT_ROOT,
             receipt: Path = RECEIPT, seconds: float = MAX_SECONDS,
             limit: int = MAX_SOURCES, lock: Path = LOCK) -> int:
    source_archive._local_apfs()
    source_archive._secure_local_dir(lock.parent)
    lock_fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 3
        stage = receipt.with_name("reconcile-stage.json")
        try:
            _write_receipt(stage, {"phase": "check_access", "at": int(time.time())})
            _check_archive_access(archive_root)
            _write_receipt(stage, {"phase": "inventory", "at": int(time.time())})
            inventory = archive_backfill.sources(home)
            digest = _inventory_digest(inventory)
            _write_receipt(stage, {"phase": "resume", "at": int(time.time())})
            cursor, counts, reasons, started_at = _resume(receipt, digest, inventory)
            summary = {"status": "RUNNING", "at": int(time.time()),
                       "started_at": started_at, "inventory": len(inventory),
                       "inventory_sha256": digest, "cursor": cursor,
                       "prefix_sha256": _inventory_digest(inventory[:cursor]),
                       "scanned": cursor, "counts": counts,
                       "unknown_reasons": reasons}
            _write_receipt(receipt, summary)
            _write_receipt(stage, {"phase": "batch", "at": int(time.time()),
                                   "cursor": cursor, "inventory": len(inventory)})
            result = archive_backfill.import_batch(
                home=home, archive_root=archive_root, start=cursor, limit=limit,
                seconds=seconds, inventory=inventory)
            counts = {"READY": counts["READY"] + result["counts"]["READY"],
                      "UNKNOWN": counts["UNKNOWN"] + result["counts"]["UNKNOWN"],
                      "IN_PROGRESS": result["counts"]["IN_PROGRESS"]}
            for reason, count in result["unknown_reasons"].items():
                reasons[reason] = reasons.get(reason, 0) + count
            cursor = result["next_index"]
            ready = result["scan_complete"] and counts["UNKNOWN"] == 0 and counts["IN_PROGRESS"] == 0
            summary.update(status="READY" if ready else "UNKNOWN" if result["scan_complete"] else "IN_PROGRESS",
                           at=int(time.time()), cursor=cursor, scanned=cursor,
                           prefix_sha256=_inventory_digest(inventory[:cursor]),
                           counts=counts, unknown_reasons=reasons)
            _write_receipt(stage, {"phase": "done", "at": int(time.time()),
                                   "cursor": cursor, "inventory": len(inventory)})
        except Exception as exc:
            ready = False
            summary = {"status": "UNKNOWN", "at": int(time.time()),
                       "reason": ("newdrive_permission_denied" if isinstance(exc, PermissionError)
                                  else "reconcile_" + type(exc).__name__.lower())}
        _write_receipt(receipt, summary)
        return 0 if ready else 2
    finally:
        os.close(lock_fd)


if __name__ == "__main__":
    sys.exit(run_once())
