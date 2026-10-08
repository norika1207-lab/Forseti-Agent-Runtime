#!/usr/bin/env python3
"""Nonblocking, single-instance launcher for bounded raw-session archiving.

The public `launch` command never scans a transcript. A detached child owns a
per-session flock while it calls source_archive.sync_source with a finite byte
budget and watch deadline. Standard streams are discarded in the child; the
status receipt contains only fixed status codes and numeric progress.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from pathlib import Path

import source_archive


_NEWDRIVE = Path("/Volumes/NewDrive")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
DEFAULT_WATCH_SECONDS = 600.0
DEFAULT_INTERVAL_SECONDS = 0.5


class _WorkerFailure(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _reply(status: str, reason: str, pid: int | None = None) -> dict:
    return {"status": status, "reason": reason, "pid": pid,
            "auto_inject": False}


def _secure_dir(path: Path) -> None:
    if path.is_symlink():
        raise _WorkerFailure("archive_path_escape")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise _WorkerFailure("insecure_archive_permissions")


def _secure_file(path: Path) -> None:
    if path.is_symlink():
        raise _WorkerFailure("archive_path_escape")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise _WorkerFailure("insecure_archive_permissions")


def _validated_paths(source_path: str | Path, archive_root: str | Path,
                     provider: str, session_id: str) -> tuple[Path, Path, Path]:
    if provider not in ("codex", "claude") or not isinstance(session_id, str):
        raise _WorkerFailure("invalid_identity")
    if not _ID.fullmatch(session_id):
        raise _WorkerFailure("invalid_identity")
    if not _NEWDRIVE.is_dir() or not os.path.ismount(_NEWDRIVE):
        raise _WorkerFailure("newdrive_unavailable")
    if not Path(archive_root).is_absolute() or not Path(source_path).is_absolute():
        raise _WorkerFailure("path_must_be_absolute")
    root = Path(archive_root).resolve()
    if not root.is_relative_to(_NEWDRIVE.resolve()) or root == _NEWDRIVE.resolve():
        raise _WorkerFailure("archive_root_not_on_newdrive")
    source = Path(source_path).resolve(strict=True)
    if not source.is_file():
        raise _WorkerFailure("missing_source")
    folder = root / provider / session_id
    if not folder.resolve().is_relative_to(root):
        raise _WorkerFailure("archive_path_escape")
    if source.is_relative_to(folder):
        raise _WorkerFailure("source_is_archive")
    for path in (root, root / provider, folder):
        _secure_dir(path)
    return source, root, folder


def _validate_limits(max_bytes: int, watch_seconds: float,
                     interval_seconds: float, source_finalized: bool) -> None:
    if (type(max_bytes) is not int
            or not 1 <= max_bytes <= source_archive.MAX_CALL_BYTES):
        raise _WorkerFailure("invalid_budget")
    if (not isinstance(watch_seconds, (int, float))
            or not 0 < watch_seconds <= 3600):
        raise _WorkerFailure("invalid_watch_seconds")
    if (not isinstance(interval_seconds, (int, float))
            or not 0.05 <= interval_seconds <= 30):
        raise _WorkerFailure("invalid_interval_seconds")
    if type(source_finalized) is not bool:
        raise _WorkerFailure("invalid_finalized_flag")


def _write_status(folder: Path, *, status: str, reason: str,
                  archived_bytes: int | None = None) -> None:
    receipt = {"status": status, "reason": reason, "pid": os.getpid(),
               "archived_bytes": archived_bytes, "updated_at": time.time()}
    path = folder / "worker-status.json"
    temp = folder / f".worker-status.{secrets.token_hex(8)}.tmp"
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        with os.fdopen(fd, "wb") as output:
            output.write((json.dumps(receipt, sort_keys=True) + "\n").encode())
            output.flush()
            os.fsync(output.fileno())
        _secure_file(temp)
        os.replace(temp, path)
        directory = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temp.exists():
            temp.unlink()


def launch_worker(*, source_path: str | Path, archive_root: str | Path,
                  provider: str, session_id: str,
                  max_bytes: int = source_archive.DEFAULT_MAX_BYTES,
                  watch_seconds: float = DEFAULT_WATCH_SECONDS,
                  interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
                  source_finalized: bool = False) -> dict:
    """Return immediately; STARTED and ALREADY_RUNNING are successful launch results."""
    try:
        _validate_limits(max_bytes, watch_seconds, interval_seconds,
                         source_finalized)
        source, root, folder = _validated_paths(
            source_path, archive_root, provider, session_id)
        lock_path = folder / "worker.lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            _secure_file(lock_path)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return _reply("ALREADY_RUNNING", "session_worker_locked")
            args = [sys.executable, str(Path(__file__).resolve()), "_run",
                    "--source", str(source), "--archive-root", str(root),
                    "--provider", provider, "--session-id", session_id,
                    "--max-bytes", str(max_bytes),
                    "--watch-seconds", str(watch_seconds),
                    "--interval-seconds", str(interval_seconds),
                    "--lock-fd", str(fd)]
            if source_finalized:
                args.append("--source-finalized")
            child = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
                close_fds=True, pass_fds=(fd,))
            return _reply("STARTED", "worker_spawned", child.pid)
        finally:
            os.close(fd)
    except FileNotFoundError:
        return _reply("UNKNOWN", "missing_source")
    except _WorkerFailure as exc:
        return _reply("UNKNOWN", exc.reason)
    except (OSError, TypeError, ValueError):
        return _reply("UNKNOWN", "worker_launch_error")


def _run_worker(args) -> int:
    try:
        _validate_limits(args.max_bytes, args.watch_seconds,
                         args.interval_seconds, args.source_finalized)
        source, root, folder = _validated_paths(
            args.source, args.archive_root, args.provider, args.session_id)
        lock_path = folder / "worker.lock"
        _secure_file(lock_path)
        if os.fstat(args.lock_fd).st_ino != lock_path.stat().st_ino:
            raise _WorkerFailure("invalid_lock_fd")
        fcntl.flock(args.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        deadline = time.monotonic() + args.watch_seconds
        _write_status(folder, status="RUNNING", reason="bounded_sync")
        while True:
            result = source_archive.sync_source(
                source_path=source, archive_root=root, provider=args.provider,
                session_id=args.session_id, max_bytes=args.max_bytes,
                source_finalized=args.source_finalized)
            if result["status"] == "READY":
                _write_status(folder, status="READY", reason="caught_up",
                              archived_bytes=result["archived_bytes"])
                return 0
            if result["status"] == "UNKNOWN":
                _write_status(folder, status="UNKNOWN", reason=result["reason"])
                return 2
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _write_status(folder, status="TIMED_OUT", reason="watch_deadline",
                              archived_bytes=result["archived_bytes"])
                return 3
            time.sleep(min(args.interval_seconds, remaining))
    except Exception:
        try:
            _write_status(folder, status="UNKNOWN", reason="worker_error")
        except Exception:
            pass
        return 2
    finally:
        try:
            os.close(args.lock_fd)
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded Forseti raw-session archive worker")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("launch", "_run"):
        command = sub.add_parser(name)
        command.add_argument("--source", required=True)
        command.add_argument("--archive-root", required=True)
        command.add_argument("--provider", required=True, choices=("codex", "claude"))
        command.add_argument("--session-id", required=True)
        command.add_argument("--max-bytes", type=int,
                             default=source_archive.DEFAULT_MAX_BYTES,
                             help="maximum source bytes per sync call (default: 16 MiB)")
        command.add_argument("--watch-seconds", type=float,
                             default=DEFAULT_WATCH_SECONDS)
        command.add_argument("--interval-seconds", type=float,
                             default=DEFAULT_INTERVAL_SECONDS)
        command.add_argument("--source-finalized", action="store_true")
        if name == "_run":
            command.add_argument("--lock-fd", type=int, required=True)
    args = parser.parse_args(argv)
    if args.command == "_run":
        return _run_worker(args)
    result = launch_worker(
        source_path=args.source, archive_root=args.archive_root,
        provider=args.provider, session_id=args.session_id,
        max_bytes=args.max_bytes, watch_seconds=args.watch_seconds,
        interval_seconds=args.interval_seconds,
        source_finalized=args.source_finalized)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] != "UNKNOWN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
