#!/usr/bin/env python3
"""Periodic, bounded reconciliation of native session files into the archive."""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import time
from pathlib import Path

import archive_backfill
import source_archive


RECEIPT = source_archive._ANCHOR_DIR / "backfill-status.json"
LOCK = source_archive._ANCHOR_DIR / "backfill.lock"
MAX_SECONDS = 300
MAX_SOURCES = 500
PROGRESS_VERSION = 1


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


def _source_key(provider: str, session_id: str, path: Path) -> str:
    return hashlib.sha256((provider + "\0" + session_id + "\0" + str(path)).encode()).hexdigest()


def _source_version(path: Path) -> list[int]:
    info = path.stat()
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]


def _state_mac(done: dict[str, list[int]]) -> str:
    payload = json.dumps({"version": PROGRESS_VERSION, "done": done},
                         sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(source_archive._key(), b"reconcile-progress-v1\0" + payload,
                    hashlib.sha256).hexdigest()


def _load_progress(path: Path) -> dict[str, list[int]]:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size > 2000000:
            return {}
        data = json.loads(path.read_text())
        done = data.get("done")
        if (data.get("version") != PROGRESS_VERSION or not isinstance(done, dict)
                or len(done) > 100000
                or any(not isinstance(key, str) or len(key) != 64
                       or not isinstance(value, list) or len(value) != 4
                       or any(type(part) is not int or part < 0 for part in value)
                       for key, value in done.items())
                or not hmac.compare_digest(data.get("mac", ""), _state_mac(done))):
            return {}
        return done
    except (OSError, ValueError, TypeError):
        return {}


def _write_progress(path: Path, done: dict[str, list[int]]) -> None:
    _write_receipt(path, {"version": PROGRESS_VERSION, "done": done,
                          "mac": _state_mac(done)})


def _ready_count(inventory: list[tuple[str, str, Path]],
                 done: dict[str, list[int]]) -> int:
    count = 0
    for provider, session_id, path in inventory:
        try:
            count += done.get(_source_key(provider, session_id, path)) == _source_version(path)
        except OSError:
            pass
    return count


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
        progress = receipt.with_name("backfill-progress.json")
        try:
            _write_receipt(stage, {"phase": "check_access", "at": int(time.time())})
            _check_archive_access(archive_root)
            _write_receipt(stage, {"phase": "inventory", "at": int(time.time())})
            inventory = archive_backfill.sources(home)
            digest = _inventory_digest(inventory)
            _write_receipt(stage, {"phase": "resume", "at": int(time.time())})
            done = _load_progress(progress)
            keys = {_source_key(provider, session_id, path)
                    for provider, session_id, path in inventory}
            done = {key: version for key, version in done.items() if key in keys}
            ready_count = _ready_count(inventory, done)
            reasons: dict[str, int] = {}
            summary = {"status": "RUNNING", "at": int(time.time()),
                       "inventory": len(inventory), "inventory_sha256": digest,
                       "cursor": ready_count, "scanned": ready_count,
                       "remaining": len(inventory) - ready_count,
                       "counts": {"READY": ready_count, "UNKNOWN": 0, "IN_PROGRESS": 0},
                       "unknown_reasons": reasons}
            _write_receipt(receipt, summary)
            _write_receipt(stage, {"phase": "batch", "at": int(time.time()),
                                   "cursor": ready_count, "inventory": len(inventory)})
            begun = time.monotonic()
            attempted = 0
            incomplete = 0
            for provider, session_id, path in inventory:
                key = _source_key(provider, session_id, path)
                try:
                    version_before = _source_version(path)
                    if done.get(key) == version_before:
                        continue
                except OSError:
                    reasons["missing_source"] = reasons.get("missing_source", 0) + 1
                    continue
                if attempted >= limit or time.monotonic() - begun >= seconds:
                    break
                attempted += 1
                while True:
                    result = source_archive.sync_source(
                        source_path=path, archive_root=archive_root,
                        provider=provider, session_id=session_id,
                        source_finalized=True)
                    if result["status"] != "IN_PROGRESS" or time.monotonic() - begun >= seconds:
                        break
                if result["status"] == "READY":
                    try:
                        version = _source_version(path)
                        if version == version_before and version[2] == result["source_bytes"]:
                            done[key] = version
                            ready_count += 1
                        else:
                            incomplete += 1
                    except OSError:
                        incomplete += 1
                elif result["status"] == "UNKNOWN":
                    reason = result["reason"]
                    reasons[reason] = reasons.get(reason, 0) + 1
                else:
                    incomplete += 1
                if attempted % 100 == 0 or time.monotonic() - begun >= seconds:
                    _write_progress(progress, done)
                    summary.update(at=int(time.time()), cursor=ready_count,
                                   scanned=ready_count,
                                   remaining=len(inventory) - ready_count,
                                   counts={"READY": ready_count,
                                           "UNKNOWN": sum(reasons.values()),
                                           "IN_PROGRESS": incomplete},
                                   unknown_reasons=reasons)
                    _write_receipt(receipt, summary)
                if time.monotonic() - begun >= seconds:
                    break
            _write_progress(progress, done)
            ready_count = _ready_count(inventory, done)
            ready = ready_count == len(inventory) and not reasons and not incomplete
            summary.update(status="READY" if ready else "UNKNOWN" if reasons else "IN_PROGRESS",
                           at=int(time.time()), cursor=ready_count, scanned=ready_count,
                           remaining=len(inventory) - ready_count,
                           counts={"READY": ready_count, "UNKNOWN": sum(reasons.values()),
                                   "IN_PROGRESS": incomplete}, unknown_reasons=reasons)
            _write_receipt(stage, {"phase": "done", "at": int(time.time()),
                                   "cursor": ready_count, "inventory": len(inventory)})
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
