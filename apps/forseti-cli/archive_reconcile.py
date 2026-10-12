#!/usr/bin/env python3
"""Periodic, bounded reconciliation of native session files into the archive."""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
from pathlib import Path

import archive_backfill
import source_archive


RECEIPT = source_archive._ANCHOR_DIR / "backfill-status.json"
MAX_SECONDS = 360
MAX_SOURCES = 1000000


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


def run_once(*, home: Path = Path.home(),
             archive_root: Path = archive_backfill.DEFAULT_ROOT,
             receipt: Path = RECEIPT, seconds: float = MAX_SECONDS,
             limit: int = MAX_SOURCES) -> int:
    source_archive._local_apfs()
    try:
        result = archive_backfill.import_batch(
            home=home, archive_root=archive_root, start=0, limit=limit,
            seconds=seconds)
        ready = result["scan_complete"] and result["batch_all_ready"]
        summary = {"status": "READY" if ready else "UNKNOWN",
                   "at": int(time.time()), "inventory": result["inventory"],
                   "scanned": result["next_index"],
                   "counts": result["counts"],
                   "unknown_reasons": result["unknown_reasons"]}
    except Exception as exc:
        ready = False
        summary = {"status": "UNKNOWN", "at": int(time.time()),
                   "reason": "reconcile_" + type(exc).__name__.lower()}
    _write_receipt(receipt, summary)
    return 0 if ready else 2


if __name__ == "__main__":
    sys.exit(run_once())
