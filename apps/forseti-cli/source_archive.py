#!/usr/bin/env python3
"""Bounded, authenticated Codex/Claude JSONL archive on NewDrive.

This storage primitive does not map provider records into rehydration rows,
select a foreground session, or inject content into an AI. Ordered immutable
encrypted chunk files decrypt to the source bytes. Each poll reads at most
``max_bytes`` of new source data and at most ``max_bytes`` for audit. READY is
returned only after all current bytes and every chunk pass a bounded audit.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import plistlib
import re
import secrets
import stat
import subprocess
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.exceptions import InvalidTag
except ImportError:
    AESGCM = None
    InvalidTag = Exception


_NEWDRIVE = Path("/Volumes/NewDrive")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_EMPTY_SHA = hashlib.sha256(b"").hexdigest()
MAX_CALL_BYTES = 16 * 1024 * 1024
DEFAULT_MAX_BYTES = MAX_CALL_BYTES
_KEY_PATH = Path.home() / ".forseti" / "archive-key"
_ANCHOR_DIR = Path.home() / ".forseti" / "archive-anchors"
_DATA_VOLUME = Path("/System/Volumes/Data")
_MAGIC = b"FSA2"
_NONCE_BYTES = 12
_CIPHER_OVERHEAD = len(_MAGIC) + _NONCE_BYTES + 16
_MAX_MANIFEST_BYTES = 32 * 1024 * 1024


class ArchiveReadError(Exception):
    """Fixed-code archive read failure; never contains transcript bytes."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class _Failure(ArchiveReadError):
    pass


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


@lru_cache(maxsize=1)
def _apfs_data_device() -> int:
    try:
        info = plistlib.loads(subprocess.check_output(
            ["/usr/sbin/diskutil", "info", "-plist", str(_DATA_VOLUME)],
            stderr=subprocess.DEVNULL, timeout=5))
        if (info.get("FilesystemType") != "apfs"
                or info.get("GlobalPermissionsEnabled") is not True):
            raise _Failure("local_apfs_required")
        return _DATA_VOLUME.stat().st_dev
    except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
        raise _Failure("local_apfs_required") from exc


def _local_apfs() -> None:
    device = _apfs_data_device()
    if (Path.home().stat().st_dev != device
            or _DATA_VOLUME.stat().st_dev != device
            or (_KEY_PATH.parent if _KEY_PATH.parent.exists() else Path.home()).stat().st_dev
            != device
            or (_ANCHOR_DIR.parent if _ANCHOR_DIR.parent.exists() else Path.home()).stat().st_dev
            != device):
        raise _Failure("local_apfs_required")


def _secure_local_dir(path: Path) -> None:
    if path.is_symlink():
        raise _Failure("local_apfs_required")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if (info.st_dev != _DATA_VOLUME.stat().st_dev or info.st_uid != os.getuid()
            or not stat.S_ISDIR(info.st_mode)):
        raise _Failure("local_apfs_required")
    if stat.S_IMODE(info.st_mode) & 0o077:
        os.chmod(path, 0o700)
    _check_dir(path)


def _key(*, create: bool = False) -> bytes:
    if AESGCM is None:
        raise _Failure("crypto_unavailable")
    _local_apfs()
    _secure_local_dir(_KEY_PATH.parent)
    lock_path = _KEY_PATH.with_name("archive-key.lock")
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        _secure_file(lock_path)
        fcntl.flock(fd, fcntl.LOCK_EX)
        if not _KEY_PATH.exists() and not _KEY_PATH.is_symlink():
            if not create:
                raise _Failure("missing_archive_key")
            created = os.open(_KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                              | os.O_NOFOLLOW, 0o600)
            with os.fdopen(created, "wb") as output:
                output.write(secrets.token_bytes(32))
                output.flush()
                os.fsync(output.fileno())
            directory = os.open(_KEY_PATH.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        _secure_file(_KEY_PATH)
        material = _KEY_PATH.read_bytes()
        if len(material) != 32:
            raise _Failure("invalid_archive_key")
        return material
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _canonical(data: dict) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _read_json_file(path: Path, limit: int, reason: str):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        with os.fdopen(fd, "rb") as source:
            fd = -1
            payload = source.read(limit + 1)
        if len(payload) > limit:
            raise _Failure(reason)
        return json.loads(payload)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise _Failure(reason) from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _mac(key: bytes, domain: bytes, payload: bytes) -> str:
    return hmac.new(key, domain + payload, hashlib.sha256).hexdigest()


def _source_id(key: bytes, source: Path) -> str:
    return _mac(key, b"source-path-v2\0", str(source).encode("utf-8"))


def _anchor_path(key: bytes, root: Path, provider: str, session_id: str) -> Path:
    _local_apfs()
    _secure_local_dir(_ANCHOR_DIR)
    identity = _canonical({"root": str(root), "provider": provider,
                           "session_id": session_id})
    return _ANCHOR_DIR / (_mac(key, b"anchor-name-v2\0", identity) + ".json")


def _seal_manifest(data: dict, key: bytes) -> dict:
    unsigned = {name: value for name, value in data.items() if name != "hmac"}
    return {**unsigned, "hmac": _mac(key, b"manifest-v2\0", _canonical(unsigned))}


def _anchor_data(data: dict, key: bytes) -> dict:
    anchor = {"generation": data["generation"],
              "manifest_sha256": hashlib.sha256(_canonical(data)).hexdigest()}
    anchor["hmac"] = _mac(key, b"anchor-v2\0", _canonical(anchor))
    return anchor


def _check_anchor(path: Path, data: dict, key: bytes) -> bool:
    if not path.exists():
        raise _Failure("missing_local_anchor")
    _secure_file(path)
    anchor = _read_json_file(path, 4096, "corrupt_local_anchor")
    if not isinstance(anchor, dict) or type(anchor.get("generation")) is not int:
        raise _Failure("corrupt_local_anchor")
    unsigned = {name: value for name, value in anchor.items() if name != "hmac"}
    expected = _mac(key, b"anchor-v2\0", _canonical(unsigned))
    if not hmac.compare_digest(str(anchor.get("hmac", "")), expected):
        raise _Failure("corrupt_local_anchor")
    digest = hashlib.sha256(_canonical(data)).hexdigest()
    if (anchor["generation"] == data["generation"]
            and anchor.get("manifest_sha256") == digest):
        return False
    if (anchor["generation"] + 1 == data["generation"]
            and data.get("prev_manifest_sha256") == anchor.get("manifest_sha256")):
        return True
    raise _Failure("archive_rollback_or_anchor_mismatch")


def _encrypt(key: bytes, payload: bytes, provider: str, session_id: str,
             offset: int) -> bytes:
    nonce = secrets.token_bytes(_NONCE_BYTES)
    aad = _canonical({"provider": provider, "session_id": session_id,
                      "offset": offset, "format_version": 2})
    return _MAGIC + nonce + AESGCM(key).encrypt(nonce, payload, aad)


def _decrypt(key: bytes, payload: bytes, provider: str, session_id: str,
             offset: int) -> bytes:
    if len(payload) < _CIPHER_OVERHEAD or not payload.startswith(_MAGIC):
        raise _Failure("corrupt_archive_chunk")
    nonce = payload[len(_MAGIC):len(_MAGIC) + _NONCE_BYTES]
    aad = _canonical({"provider": provider, "session_id": session_id,
                      "offset": offset, "format_version": 2})
    try:
        return AESGCM(key).decrypt(nonce, payload[len(_MAGIC) + _NONCE_BYTES:], aad)
    except InvalidTag as exc:
        raise _Failure("corrupt_archive_chunk") from exc


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


def _save_manifest(path: Path, data: dict, key: bytes, anchor: Path) -> None:
    data["prev_manifest_sha256"] = data.pop("_sealed_digest", _EMPTY_SHA)
    data["generation"] += 1
    sealed = _seal_manifest(data, key)
    _atomic_bytes(path, _canonical(sealed) + b"\n")
    _atomic_bytes(anchor, _canonical(_anchor_data(sealed, key)) + b"\n")
    data["_sealed_digest"] = hashlib.sha256(_canonical(sealed)).hexdigest()


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
                   session_id: str, key: bytes, anchor: Path,
                   source_stat=None) -> dict | None:
    if not path.exists():
        return None
    _secure_file(path)
    data = _read_json_file(path, _MAX_MANIFEST_BYTES, "corrupt_manifest")
    if isinstance(data, dict) and data.get("format_version") == 1:
        raise _Failure("legacy_unencrypted_archive")
    if (not isinstance(data, dict) or data.get("format_version") != 2
            or data.get("provider") != provider
            or data.get("session_id") != session_id
            or not isinstance(data.get("source_id"), str)
            or (source is not None and data["source_id"] != _source_id(key, source))
            or type(data.get("generation")) is not int
            or data["generation"] < 1
            or not isinstance(data.get("prev_manifest_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", data["prev_manifest_sha256"])
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
            or not re.fullmatch(r"[0-9a-f]{64}", data["chain_sha256"])
            or not isinstance(data.get("hmac"), str)):
        raise _Failure("corrupt_manifest")
    unsigned = {name: value for name, value in data.items() if name != "hmac"}
    expected_mac = _mac(key, b"manifest-v2\0", _canonical(unsigned))
    if not hmac.compare_digest(data["hmac"], expected_mac):
        raise _Failure("corrupt_manifest_auth")
    advance_anchor = _check_anchor(anchor, data, key)
    sealed_digest = hashlib.sha256(_canonical(data)).hexdigest()
    del data["hmac"]
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
                or chunk.get("name") != f"{offset:016x}.enc"
                or chunk.get("cipher_size") != chunk["size"] + _CIPHER_OVERHEAD
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
        if (part_stat.st_size != chunk["cipher_size"]
                or part_stat.st_mtime_ns != chunk["mtime_ns"]
                or part_stat.st_ctime_ns != chunk["ctime_ns"]):
            raise _Failure("archive_chunk_changed")
        chain = _chain(chain, offset, chunk["size"], chunk["sha256"])
        offset += chunk["size"]
    if offset != data["archived_bytes"] or chain != data["chain_sha256"]:
        raise _Failure("corrupt_manifest")
    if advance_anchor:
        if data["chunks"]:
            _read_encrypted_part(path.parent, data["chunks"][-1], key,
                                 provider, session_id)
        sealed = _seal_manifest(data, key)
        _atomic_bytes(anchor, _canonical(_anchor_data(sealed, key)) + b"\n")
    data["_sealed_digest"] = sealed_digest
    return data


def _verify_part(path: Path, source, offset: int, expected: dict | None,
                 budget: int, key: bytes, provider: str, session_id: str) -> dict:
    _secure_file(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        cipher_size = before.st_size
        size = cipher_size - _CIPHER_OVERHEAD
        if size < 1 or size > budget:
            raise _Failure("chunk_exceeds_budget")
        with os.fdopen(fd, "rb") as archived:
            fd = -1
            ciphertext = archived.read(cipher_size + 1)
            after = os.fstat(archived.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    if (len(ciphertext) != cipher_size
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise _Failure("corrupt_archive_chunk")
    digest = hashlib.sha256(ciphertext).hexdigest()
    if expected and (expected["size"] != size or expected["sha256"] != digest):
        raise _Failure("corrupt_archive_chunk")
    payload = _decrypt(key, ciphertext, provider, session_id, offset)
    if len(payload) != size or not _valid_jsonl(payload):
        raise _Failure("corrupt_archive_chunk")
    source.seek(offset)
    if source.read(size) != payload:
        raise _Failure("archive_source_prefix_mismatch")
    return {"offset": offset, "size": size, "cipher_size": cipher_size,
            "sha256": digest,
            "name": path.name, "mtime_ns": after.st_mtime_ns,
            "ctime_ns": after.st_ctime_ns}


def sync_source(*, source_path: str | Path, archive_root: str | Path,
                provider: str, session_id: str,
                max_bytes: int = DEFAULT_MAX_BYTES,
                source_finalized: bool = False) -> dict:
    """Advance one raw-session archive by at most max_bytes; never truncate.

    Recommended root: repo/.forseti/session_archive on mounted NewDrive.
    Chunks on NewDrive are AES-GCM ciphertext. Use iter_plaintext_chunks for
    bounded authenticated reads; ciphertext files are never plaintext JSONL.
    Return READY only after
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
        if any(folder.glob("*.jsonl")):
            raise _Failure("legacy_unencrypted_archive")
        manifest_path = folder / "manifest.json"
        key = _key(create=not manifest_path.exists())
        anchor = _anchor_path(key, root, provider, session_id)
        lock_path = folder / "archive.lock"
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            _secure_file(lock_path)
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            with source_path.open("rb") as source:
                info = os.fstat(source.fileno())
                data = _read_manifest(manifest_path, source_path, provider,
                                      session_id, key, anchor, info)
                if data is None:
                    if any(folder.glob("*.enc")) or anchor.exists():
                        raise _Failure("missing_manifest")
                    data = {"format_version": 2, "generation": 0,
                            "provider": provider,
                            "session_id": session_id,
                            "source_id": _source_id(key, source_path),
                            "source_dev": info.st_dev, "source_ino": info.st_ino,
                            "source_size_seen": 0, "source_mtime_ns": 0,
                            "archived_bytes": 0, "chain_sha256": _EMPTY_SHA,
                            "chunks": [], "audit_index": 0,
                            "audit_mtime_ns": None}
                    _save_manifest(manifest_path, data, key, anchor)
                if info.st_size == 0 and source_finalized:
                    raise _Failure("empty_source")
                if info.st_size < data["source_size_seen"]:
                    raise _Failure("source_truncated")
                if (info.st_size == data["source_size_seen"]
                        and data["source_mtime_ns"] not in (0, info.st_mtime_ns)):
                    raise _Failure("source_modified")
                offset = data["archived_bytes"]
                part = folder / f"{offset:016x}.enc"
                if part.exists() or part.is_symlink():
                    adopted = _verify_part(part, source, offset, None, max_bytes,
                                           key, provider, session_id)
                    data["chunks"].append(adopted)
                    data["archived_bytes"] += adopted["size"]
                    data["chain_sha256"] = _chain(
                        data["chain_sha256"], offset, adopted["size"],
                        adopted["sha256"])
                    data["audit_index"] = 0
                    data["audit_mtime_ns"] = None
                    data["source_size_seen"] = info.st_size
                    data["source_mtime_ns"] = info.st_mtime_ns
                    _save_manifest(manifest_path, data, key, anchor)
                    return _result("IN_PROGRESS", "recovered_pending_chunk",
                                   manifest_path, data)
                if offset < info.st_size:
                    payload = _read_chunk(source, offset, info.st_size, max_bytes,
                                          source_finalized)
                    if payload:
                        ciphertext = _encrypt(key, payload, provider, session_id,
                                              offset)
                        digest = hashlib.sha256(ciphertext).hexdigest()
                        _atomic_bytes(part, ciphertext)
                        part_stat = part.stat()
                        data["chunks"].append({"offset": offset, "size": len(payload),
                                               "cipher_size": len(ciphertext),
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
                    _save_manifest(manifest_path, data, key, anchor)
                    return _result("IN_PROGRESS", "copying" if payload else
                                   "awaiting_complete_record", manifest_path, data)
                if data["audit_mtime_ns"] != info.st_mtime_ns:
                    before_audit = _canonical(data)
                    data["audit_index"] = 0
                    data["audit_mtime_ns"] = info.st_mtime_ns
                else:
                    before_audit = _canonical(data)
                spent = 0
                while data["audit_index"] < len(data["chunks"]):
                    chunk = data["chunks"][data["audit_index"]]
                    if chunk["size"] > max_bytes:
                        raise _Failure("chunk_exceeds_budget")
                    if spent + chunk["size"] > max_bytes:
                        break
                    _verify_part(folder / chunk["name"], source, chunk["offset"],
                                 chunk, max_bytes, key, provider, session_id)
                    spent += chunk["size"]
                    data["audit_index"] += 1
                data["source_size_seen"] = info.st_size
                data["source_mtime_ns"] = info.st_mtime_ns
                if _canonical(data) != before_audit:
                    _save_manifest(manifest_path, data, key, anchor)
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


@contextmanager
def _locked_archive(manifest_path: str | Path):
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
    provider, session_id = provider_dir.name, folder.name
    if (not root.is_relative_to(_NEWDRIVE.resolve())
            or root == _NEWDRIVE.resolve()
            or provider not in ("codex", "claude")
            or not _ID.fullmatch(session_id)):
        raise _Failure("invalid_manifest_path")
    for directory in (root, provider_dir, folder):
        _check_dir(directory)
    if any(folder.glob("*.jsonl")):
        raise _Failure("legacy_unencrypted_archive")
    _secure_file(path)
    lock = folder / "archive.lock"
    _secure_file(lock)
    key = _key()
    anchor = _anchor_path(key, root, provider, session_id)
    lock_fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        data = _read_manifest(path, None, provider, session_id, key, anchor)
        if data is None:
            raise _Failure("missing_manifest")
        if (not data["chunks"] or data["audit_index"] != len(data["chunks"])
                or data["archived_bytes"] != data["source_size_seen"]):
            raise _Failure("archive_incomplete")
        expected = {chunk["name"] for chunk in data["chunks"]}
        actual = {part.name for part in folder.glob("*.enc")
                  if not part.name.startswith("._")}
        if actual != expected:
            raise _Failure("uncommitted_archive_chunk")
        yield path, folder, provider, session_id, key, data
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def _read_encrypted_part(folder: Path, chunk: dict, key: bytes,
                         provider: str, session_id: str) -> bytes:
    part = folder / chunk["name"]
    fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        with os.fdopen(fd, "rb") as archived:
            fd = -1
            ciphertext = archived.read(chunk["cipher_size"] + 1)
            after = os.fstat(archived.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    if (len(ciphertext) != chunk["cipher_size"]
            or hashlib.sha256(ciphertext).hexdigest() != chunk["sha256"]
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
        raise _Failure("corrupt_archive_chunk")
    plaintext = _decrypt(key, ciphertext, provider, session_id, chunk["offset"])
    if len(plaintext) != chunk["size"] or not _valid_jsonl(plaintext):
        raise _Failure("corrupt_archive_chunk")
    return plaintext


def _scan_chunks(folder: Path, data: dict, key: bytes,
                 provider: str, session_id: str) -> list[str]:
    chain, total, paths = _EMPTY_SHA, 0, []
    for chunk in data["chunks"]:
        _read_encrypted_part(folder, chunk, key, provider, session_id)
        chain = _chain(chain, total, chunk["size"], chunk["sha256"])
        total += chunk["size"]
        paths.append(str(folder / chunk["name"]))
    if total != data["archived_bytes"] or chain != data["chain_sha256"]:
        raise _Failure("corrupt_archive_chain")
    return paths


def verified_chunks(manifest_path: str | Path) -> dict:
    """Authenticate a complete archive without its source; paths are ciphertext."""
    def unknown(reason: str) -> dict:
        return {"status": "UNKNOWN", "reason": reason, "auto_inject": False,
                "manifest_path": None, "encrypted_chunk_paths": [],
                "archived_bytes": None, "chain_sha256": None,
                "provider": None, "session_id": None}

    try:
        with _locked_archive(manifest_path) as (path, folder, provider,
                                               session_id, key, data):
            paths = _scan_chunks(folder, data, key, provider, session_id)
            return {"status": "READY", "reason": "archive_aead_verified",
                    "auto_inject": False, "manifest_path": str(path),
                    "encrypted_chunk_paths": paths,
                    "archived_bytes": data["archived_bytes"],
                    "chain_sha256": data["chain_sha256"],
                    "provider": provider, "session_id": session_id}
    except FileNotFoundError:
        return unknown("missing_archive")
    except _Failure as exc:
        return unknown(exc.reason)
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, KeyError):
        return unknown("archive_io_error")


def iter_plaintext_chunks(manifest_path: str | Path):
    """Yield authenticated plaintext bytes, one <=16 MiB chunk at a time.

    No source file or plaintext temp file is needed. The manifest and local
    rollback anchor are checked before the first yield; each ciphertext chunk
    is authenticated before that chunk is yielded. A later corrupt chunk may
    raise after earlier chunks were yielded: callers must discard partial data
    on any failure. The archive lock stays held while read. Close the iterator
    if stopping early. Raises ArchiveReadError with a fixed reason on failure.
    """
    try:
        with _locked_archive(manifest_path) as (_, folder, provider,
                                               session_id, key, data):
            for chunk in data["chunks"]:
                yield _read_encrypted_part(folder, chunk, key, provider,
                                           session_id)
    except _Failure:
        raise
    except (OSError, TypeError, ValueError, OverflowError, RecursionError, KeyError) as exc:
        raise ArchiveReadError("archive_io_error") from exc
