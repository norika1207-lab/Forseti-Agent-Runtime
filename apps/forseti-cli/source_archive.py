#!/usr/bin/env python3
"""Bounded, byte-exact raw Codex/Claude JSONL archive on NewDrive.

This storage primitive does not map provider records into rehydration rows,
select a foreground session, or inject content into an AI. Ordered immutable
chunk files concatenate to the source bytes. Each poll reads at most
``max_bytes`` of new source data and at most ``max_bytes`` for audit. READY is
returned only after all current bytes and every chunk pass a bounded audit.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path


_NEWDRIVE = Path("/Volumes/NewDrive")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_EMPTY_SHA = hashlib.sha256(b"").hexdigest()
DEFAULT_MAX_BYTES = 4 * 1024 * 1024
MAX_CALL_BYTES = 16 * 1024 * 1024


class _Failure(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _result(status: str, reason: str, manifest: Path | None = None,
            data: dict | None = None) -> dict:
    return {"status": status, "reason": reason, "auto_inject": False,
            "manifest_path": str(manifest) if manifest and status != "UNKNOWN" else None,
            "archive_path": str(manifest.parent) if manifest and status != "UNKNOWN" else None,
            "archived_bytes": data["archived_bytes"] if data and status != "UNKNOWN" else None,
            "source_bytes": data["source_size_seen"] if data and status != "UNKNOWN" else None,
            "chain_sha256": data["chain_sha256"] if data and status != "UNKNOWN" else None}


def _secure_dir(path: Path) -> None:
    if path.is_symlink():
        raise _Failure("archive_path_escape")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _check_dir(path)


def _check_dir(path: Path) -> None:
    if path.is_symlink():
        raise _Failure("archive_path_escape")
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise _Failure("insecure_archive_permissions")


def _secure_file(path: Path) -> None:
    if path.is_symlink():
        raise _Failure("archive_path_escape")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise _Failure("insecure_archive_permissions")


def _atomic_bytes(path: Path, payload: bytes) -> None:
    temp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        _secure_file(temp)
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp.exists():
            temp.unlink()


def _save_manifest(path: Path, data: dict) -> None:
    _atomic_bytes(path, (json.dumps(data, sort_keys=True) + "\n").encode("utf-8"))


def _chain(previous: str, offset: int, size: int, digest: str) -> str:
    material = (bytes.fromhex(previous) + offset.to_bytes(8, "big")
                + size.to_bytes(8, "big") + bytes.fromhex(digest))
    return hashlib.sha256(material).hexdigest()


def _valid_jsonl(payload: bytes) -> bool:
    if not payload or not payload.endswith(b"\n"):
        return False
    for line in payload.splitlines(keepends=True):
        try:
            if not isinstance(json.loads(line.decode("utf-8")), dict):
                return False
        except (UnicodeError, ValueError, RecursionError):
            return False
    return True


def _read_chunk(source, offset: int, source_size: int, budget: int,
                source_finalized: bool) -> bytes:
    source.seek(offset)
    payload = bytearray()
    while offset + len(payload) < source_size and len(payload) < budget:
        remaining = min(source_size - offset - len(payload), budget - len(payload))
        line = source.readline(remaining)
        if not line.endswith(b"\n"):
            if source_size - offset - len(payload) > remaining and not payload:
                raise _Failure("record_exceeds_budget")
            if source_finalized and source_size - offset - len(payload) <= remaining:
                raise _Failure("corrupt_source_jsonl")
            break
        try:
            if not isinstance(json.loads(line.decode("utf-8")), dict):
                raise _Failure("corrupt_source_jsonl")
        except (UnicodeError, ValueError, RecursionError) as exc:
            raise _Failure("corrupt_source_jsonl") from exc
        payload.extend(line)
    return bytes(payload)


def _read_manifest(path: Path, source: Path | None, provider: str,
                   session_id: str, source_stat=None) -> dict | None:
    if not path.exists():
        return None
    _secure_file(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise _Failure("corrupt_manifest") from exc
    if (not isinstance(data, dict) or data.get("format_version") != 1
            or data.get("provider") != provider
            or data.get("session_id") != session_id
            or not isinstance(data.get("source_path"), str)
            or not Path(data["source_path"]).is_absolute()
            or (source is not None and data["source_path"] != str(source))
            or type(data.get("source_dev")) is not int
            or type(data.get("source_ino")) is not int
            or type(data.get("archived_bytes")) is not int
            or type(data.get("audit_index")) is not int
            or type(data.get("source_size_seen")) is not int
            or type(data.get("source_mtime_ns")) is not int
            or (data.get("audit_mtime_ns") is not None
                and type(data.get("audit_mtime_ns")) is not int)
            or not isinstance(data.get("chunks"), list)
            or not isinstance(data.get("chain_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", data["chain_sha256"])):
        raise _Failure("corrupt_manifest")
    if (source_stat is not None
            and (data["source_dev"] != source_stat.st_dev
                 or data["source_ino"] != source_stat.st_ino)):
        raise _Failure("source_identity_changed")
    if (data["archived_bytes"] < 0 or data["source_size_seen"] < 0
            or data["source_size_seen"] < data["archived_bytes"]
            or not 0 <= data["audit_index"] <= len(data["chunks"])):
        raise _Failure("corrupt_manifest")
    offset = 0
    chain = _EMPTY_SHA
    for chunk in data["chunks"]:
        if (not isinstance(chunk, dict) or chunk.get("offset") != offset
                or type(chunk.get("size")) is not int
                or not 1 <= chunk["size"] <= MAX_CALL_BYTES
                or chunk.get("name") != f"{offset:016x}.jsonl"
                or type(chunk.get("mtime_ns")) is not int
                or type(chunk.get("ctime_ns")) is not int
                or not isinstance(chunk.get("sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", chunk["sha256"])):
            raise _Failure("corrupt_manifest")
        part = path.parent / chunk["name"]
        if not part.exists():
            raise _Failure("missing_archive_chunk")
        _secure_file(part)
        part_stat = part.stat()
        if (part_stat.st_size != chunk["size"]
                or part_stat.st_mtime_ns != chunk["mtime_ns"]
                or part_stat.st_ctime_ns != chunk["ctime_ns"]):
            raise _Failure("archive_chunk_changed")
        chain = _chain(chain, offset, chunk["size"], chunk["sha256"])
        offset += chunk["size"]
    if offset != data["archived_bytes"] or chain != data["chain_sha256"]:
        raise _Failure("corrupt_manifest")
    return data


def _verify_part(path: Path, source, offset: int, expected: dict | None,
                 budget: int) -> dict:
    _secure_file(path)
    before = path.stat()
    size = before.st_size
    if size < 1 or size > budget:
        raise _Failure("chunk_exceeds_budget")
    payload = path.read_bytes()
    if len(payload) != size or not _valid_jsonl(payload):
        raise _Failure("corrupt_archive_chunk")
    source.seek(offset)
    if source.read(size) != payload:
        raise _Failure("archive_source_prefix_mismatch")
    digest = hashlib.sha256(payload).hexdigest()
    if expected and (expected["size"] != size or expected["sha256"] != digest):
        raise _Failure("corrupt_archive_chunk")
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise _Failure("archive_chunk_changed")
    return {"offset": offset, "size": size, "sha256": digest,
            "name": path.name, "mtime_ns": after.st_mtime_ns,
            "ctime_ns": after.st_ctime_ns}


def sync_source(*, source_path: str | Path, archive_root: str | Path,
                provider: str, session_id: str,
                max_bytes: int = DEFAULT_MAX_BYTES,
                source_finalized: bool = False) -> dict:
    """Advance one raw-session archive by at most max_bytes; never truncate.

    Recommended root: repo/.forseti/session_archive on mounted NewDrive.
    ARCHIVE_PATH is a directory of ordered immutable JSONL chunks. Concatenate
    manifest.chunks in order for exact original bytes. Return READY only after
    all current source bytes have been copied and every chunk has been audited
    against the source within bounded calls. Other non-error calls return
    IN_PROGRESS; invalid/missing/corrupt data returns UNKNOWN. Results carry
    no transcript text and never authorize AI injection.
    """
    try:
        if (provider not in ("codex", "claude") or not isinstance(session_id, str)
                or not _ID.fullmatch(session_id)):
            raise _Failure("invalid_identity")
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_CALL_BYTES:
            raise _Failure("invalid_budget")
        if type(source_finalized) is not bool:
            raise _Failure("invalid_finalized_flag")
        if not _NEWDRIVE.is_dir() or not os.path.ismount(_NEWDRIVE):
            raise _Failure("newdrive_unavailable")
        if not Path(archive_root).is_absolute():
            raise _Failure("invalid_archive_root")
        if not Path(source_path).is_absolute():
            raise _Failure("invalid_source_path")
        root = Path(archive_root).resolve()
        if not root.is_relative_to(_NEWDRIVE.resolve()) or root == _NEWDRIVE.resolve():
            raise _Failure("archive_root_not_on_newdrive")
        source_path = Path(source_path).resolve(strict=True)
        if not source_path.is_file():
            raise _Failure("missing_source")
        folder = root / provider / session_id
        if not folder.resolve().is_relative_to(root):
            raise _Failure("archive_path_escape")
        if source_path.is_relative_to(folder):
            raise _Failure("source_is_archive")
        _secure_dir(root)
        _secure_dir(root / provider)
        _secure_dir(folder)
        manifest_path = folder / "manifest.json"
        lock_path = folder / "archive.lock"
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            _secure_file(lock_path)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            with source_path.open("rb") as source:
                info = os.fstat(source.fileno())
                data = _read_manifest(manifest_path, source_path, provider,
                                      session_id, info)
                if data is None:
                    if any(folder.glob("*.jsonl")):
                        raise _Failure("missing_manifest")
                    data = {"format_version": 1, "provider": provider,
                            "session_id": session_id,
                            "source_path": str(source_path),
                            "source_dev": info.st_dev, "source_ino": info.st_ino,
                            "source_size_seen": 0, "source_mtime_ns": 0,
                            "archived_bytes": 0, "chain_sha256": _EMPTY_SHA,
                            "chunks": [], "audit_index": 0,
                            "audit_mtime_ns": None}
                    _save_manifest(manifest_path, data)
                if info.st_size == 0 and source_finalized:
                    raise _Failure("empty_source")
                if info.st_size < data["source_size_seen"]:
                    raise _Failure("source_truncated")
                if (info.st_size == data["source_size_seen"]
                        and data["source_mtime_ns"] not in (0, info.st_mtime_ns)):
                    raise _Failure("source_modified")
                offset = data["archived_bytes"]
                part = folder / f"{offset:016x}.jsonl"
                if part.exists() or part.is_symlink():
                    adopted = _verify_part(part, source, offset, None, max_bytes)
                    data["chunks"].append(adopted)
                    data["archived_bytes"] += adopted["size"]
                    data["chain_sha256"] = _chain(
                        data["chain_sha256"], offset, adopted["size"],
                        adopted["sha256"])
                    data["audit_index"] = 0
                    data["audit_mtime_ns"] = None
                    data["source_size_seen"] = info.st_size
                    data["source_mtime_ns"] = info.st_mtime_ns
                    _save_manifest(manifest_path, data)
                    return _result("IN_PROGRESS", "recovered_pending_chunk",
                                   manifest_path, data)
                if offset < info.st_size:
                    payload = _read_chunk(source, offset, info.st_size, max_bytes,
                                          source_finalized)
                    if payload:
                        digest = hashlib.sha256(payload).hexdigest()
                        _atomic_bytes(part, payload)
                        part_stat = part.stat()
                        data["chunks"].append({"offset": offset, "size": len(payload),
                                               "sha256": digest, "name": part.name,
                                               "mtime_ns": part_stat.st_mtime_ns,
                                               "ctime_ns": part_stat.st_ctime_ns})
                        data["archived_bytes"] += len(payload)
                        data["chain_sha256"] = _chain(
                            data["chain_sha256"], offset, len(payload), digest)
                        data["audit_index"] = 0
                        data["audit_mtime_ns"] = None
                    data["source_size_seen"] = info.st_size
                    data["source_mtime_ns"] = info.st_mtime_ns
                    _save_manifest(manifest_path, data)
                    return _result("IN_PROGRESS", "copying" if payload else
                                   "awaiting_complete_record", manifest_path, data)
                if data["audit_mtime_ns"] != info.st_mtime_ns:
                    data["audit_index"] = 0
                    data["audit_mtime_ns"] = info.st_mtime_ns
                spent = 0
                while data["audit_index"] < len(data["chunks"]):
                    chunk = data["chunks"][data["audit_index"]]
                    if chunk["size"] > max_bytes:
                        raise _Failure("chunk_exceeds_budget")
                    if spent + chunk["size"] > max_bytes:
                        break
                    _verify_part(folder / chunk["name"], source, chunk["offset"],
                                 chunk, max_bytes)
                    spent += chunk["size"]
                    data["audit_index"] += 1
                data["source_size_seen"] = info.st_size
                data["source_mtime_ns"] = info.st_mtime_ns
                _save_manifest(manifest_path, data)
                after = os.fstat(source.fileno())
                current = source_path.stat()
                if (after.st_mtime_ns != info.st_mtime_ns
                        or after.st_size != info.st_size
                        or current.st_dev != info.st_dev
                        or current.st_ino != info.st_ino):
                    return _result("IN_PROGRESS", "source_grew_during_audit",
                                   manifest_path, data)
                if data["audit_index"] == len(data["chunks"]) and data["chunks"]:
                    return _result("READY", "byte_complete_hash_verified",
                                   manifest_path, data)
                return _result("IN_PROGRESS", "auditing", manifest_path, data)
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
    except FileNotFoundError:
        return _result("UNKNOWN", "missing_source")
    except _Failure as exc:
        return _result("UNKNOWN", exc.reason)
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, KeyError):
        return _result("UNKNOWN", "archive_io_error")


def verified_chunks(manifest_path: str | Path) -> dict:
    """Verify a completed archive without opening or requiring its source.

    This is an explicit, potentially long read operation, not a 1-3s poll
    operation. The result contains ordered chunk paths, never transcript text.
    Concatenating those paths in order reproduces the archived JSONL bytes.
    """
    def unknown(reason: str) -> dict:
        return {"status": "UNKNOWN", "reason": reason, "auto_inject": False,
                "manifest_path": None, "chunk_paths": [],
                "archived_bytes": None, "chain_sha256": None,
                "provider": None, "session_id": None}

    try:
        path = Path(manifest_path)
        if not path.is_absolute() or path.name != "manifest.json":
            raise _Failure("invalid_manifest_path")
        if not _NEWDRIVE.is_dir() or not os.path.ismount(_NEWDRIVE):
            raise _Failure("newdrive_unavailable")
        if path.resolve(strict=True) != path:
            raise _Failure("archive_path_escape")
        folder = path.parent
        provider_dir = folder.parent
        root = provider_dir.parent
        provider = provider_dir.name
        session_id = folder.name
        if (not root.is_relative_to(_NEWDRIVE.resolve())
                or root == _NEWDRIVE.resolve()
                or provider not in ("codex", "claude")
                or not _ID.fullmatch(session_id)):
            raise _Failure("invalid_manifest_path")
        for directory in (root, provider_dir, folder):
            _check_dir(directory)
        _secure_file(path)
        lock = folder / "archive.lock"
        _secure_file(lock)
        lock_fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)
            data = _read_manifest(path, None, provider, session_id)
            if data is None:
                raise _Failure("missing_manifest")
            if (not data["chunks"] or data["audit_index"] != len(data["chunks"])
                    or data["archived_bytes"] != data["source_size_seen"]):
                raise _Failure("archive_incomplete")
            expected = {chunk["name"] for chunk in data["chunks"]}
            actual = {part.name for part in folder.glob("*.jsonl")
                      if not part.name.startswith("._")}
            if actual != expected:
                raise _Failure("uncommitted_archive_chunk")
            chain = _EMPTY_SHA
            paths = []
            total = 0
            for chunk in data["chunks"]:
                part = folder / chunk["name"]
                fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    before = os.fstat(fd)
                    with os.fdopen(fd, "rb") as archived:
                        fd = -1
                        payload = archived.read(chunk["size"] + 1)
                        after = os.fstat(archived.fileno())
                finally:
                    if fd >= 0:
                        os.close(fd)
                if (len(payload) != chunk["size"] or not _valid_jsonl(payload)
                        or hashlib.sha256(payload).hexdigest() != chunk["sha256"]
                        or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                        != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                    raise _Failure("corrupt_archive_chunk")
                chain = _chain(chain, total, chunk["size"], chunk["sha256"])
                total += chunk["size"]
                paths.append(str(part))
            if total != data["archived_bytes"] or chain != data["chain_sha256"]:
                raise _Failure("corrupt_archive_chain")
            return {"status": "READY", "reason": "archive_hash_verified",
                    "auto_inject": False, "manifest_path": str(path),
                    "chunk_paths": paths, "archived_bytes": total,
                    "chain_sha256": chain, "provider": provider,
                    "session_id": session_id}
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
    except FileNotFoundError:
        return unknown("missing_archive")
    except _Failure as exc:
        return unknown(exc.reason)
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, KeyError):
        return unknown("archive_io_error")
