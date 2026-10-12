"""Bounded encrypted-source archive tests; failures never print transcript content."""

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "forseti-cli"))
import source_archive as A  # noqa: E402
import archive_reconcile as R  # noqa: E402


def record(n):
    return json.dumps({"n": n, "text": "private transcript content"}).encode() + b"\n"


def large_record(size):
    prefix, suffix = b'{"payload":"', b'"}\n'
    return prefix + b"x" * (size - len(prefix) - len(suffix)) + suffix


class SourceArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/Volumes/NewDrive")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / "source.jsonl"
        self.root = base / ".forseti" / "session_archive"
        self.kwargs = {"source_path": self.source, "archive_root": self.root,
                       "provider": "codex", "session_id": "session-123",
                       "max_bytes": len(record(1)) + 2}
        self.addCleanup(self.cleanup_anchor)

    def cleanup_anchor(self):
        try:
            for provider in ("codex", "grok"):
                anchor = A._anchor_path(A._key(), self.root.resolve(), provider,
                                        "session-123")
                anchor.unlink(missing_ok=True)
                folder = A._archive_folder(self.root.resolve(), A._key(),
                                           provider, "session-123")
                for kind in ("archive", "worker"):
                    A._local_lock_path(folder, kind).unlink(missing_ok=True)
        except A.ArchiveReadError:
            pass

    def sync(self):
        return A.sync_source(**self.kwargs)

    def chunks(self, result):
        path = Path(result["manifest_path"])
        manifest = A._read_manifest(path, None, "codex", "session-123",
                                    A._key(), None)
        folder = Path(result["archive_path"])
        key = A._key()
        return manifest, b"".join(A._decrypt(
            key, (folder / c["name"]).read_bytes(), "codex", "session-123",
            c["offset"]) for c in manifest["chunks"])

    def test_bounded_first_poll_and_eventual_ready_byte_exact(self):
        original = record(1) + record(2) + record(3)
        self.source.write_bytes(original)
        first = self.sync()
        self.assertEqual(first["status"], "IN_PROGRESS")
        self.assertFalse(first["auto_inject"])
        self.assertLessEqual(first["archived_bytes"], self.kwargs["max_bytes"])
        results = [first]
        for _ in range(8):
            results.append(self.sync())
            if results[-1]["status"] == "READY":
                break
        self.assertEqual(results[-1]["status"], "READY")
        manifest, archived = self.chunks(results[-1])
        self.assertTrue(archived == original)
        self.assertEqual(manifest["archived_bytes"], len(original))
        self.assertEqual(manifest["audit_index"], len(manifest["chunks"]))
        self.assertEqual(self.sync()["status"], "READY")

    def test_first_poll_does_not_scan_or_copy_entire_large_source(self):
        self.source.write_bytes(record(1) * 5000)
        first = self.sync()
        self.assertEqual(first["status"], "IN_PROGRESS")
        self.assertEqual(first["archived_bytes"], self.kwargs["max_bytes"])
        self.assertGreater(first["source_bytes"], first["archived_bytes"])

    def test_growing_source_resumes_without_truncation(self):
        initial = record(1)
        self.source.write_bytes(initial)
        self.assertEqual(self.sync()["status"], "IN_PROGRESS")
        with self.source.open("ab") as output:
            output.write(record(2))
        outcome = self.sync()
        self.assertEqual(outcome["status"], "IN_PROGRESS")
        _, archived = self.chunks(outcome)
        self.assertTrue(archived == initial + record(2))

    def test_partial_final_record_is_preserved_and_resumes(self):
        full = record(1) + record(2)
        self.source.write_bytes(record(1) + record(2)[:-2])
        first = self.sync()
        self.assertEqual(first["status"], "IN_PROGRESS")
        self.assertEqual(first["archived_bytes"], self.kwargs["max_bytes"])
        self.sync()
        with self.source.open("ab") as output:
            output.write(full[len(record(1) + record(2)[:-2]):])
        self.assertEqual(self.sync()["status"], "IN_PROGRESS")
        for _ in range(8):
            result = self.sync()
            if result["status"] == "READY":
                break
        self.assertEqual(result["status"], "READY")
        self.assertEqual(self.chunks(result)[1], full)

    def test_finalized_source_with_incomplete_jsonl_is_backed_up_raw(self):
        self.source.write_bytes(record(1) + b'{"n":')
        self.kwargs["source_finalized"] = True
        self.assertEqual(self.sync()["status"], "IN_PROGRESS")
        for _ in range(8):
            result = self.sync()
            if result["status"] == "READY":
                break
        self.assertEqual(result["status"], "READY")
        self.assertEqual(self.chunks(result)[1], record(1) + b'{"n":')

    def test_finalized_empty_source_is_unknown(self):
        self.source.write_bytes(b"")
        self.kwargs["source_finalized"] = True
        self.assertEqual(self.sync()["reason"], "empty_source")

    def test_missing_source_fails_but_malformed_row_is_preserved_byte_exact(self):
        self.assertEqual(self.sync()["reason"], "missing_source")
        self.source.write_bytes(b"not-json\n")
        first = self.sync()
        self.assertEqual(first["status"], "IN_PROGRESS")
        self.assertEqual(self.sync()["status"], "READY")
        _, archived = self.chunks(first)
        self.assertEqual(archived, b"not-json\n")
        self.assertEqual(A.verified_chunks(first["manifest_path"])["status"], "READY")

    def test_changed_prefix_detected_by_bounded_audit(self):
        initial = record(1) + record(2)
        self.source.write_bytes(initial)
        self.sync()
        self.sync()
        self.source.write_bytes(record(9) + record(2))
        bad = self.sync()
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertIn(bad["reason"], ("source_modified", "source_identity_changed",
                                     "archive_source_prefix_mismatch"))

    def test_same_bytes_new_mtime_are_reaudited(self):
        original = record(1) + record(2)
        local = tempfile.TemporaryDirectory()
        self.addCleanup(local.cleanup)
        self.source = Path(local.name) / "source.jsonl"
        self.kwargs["source_path"] = self.source
        self.kwargs["max_bytes"] = len(original)
        self.source.write_bytes(original)
        self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        stat_before = self.source.stat()
        os.utime(self.source, ns=(stat_before.st_atime_ns,
                                  stat_before.st_mtime_ns + 1_000_000_000))
        result = self.sync()
        for _ in range(8):
            if result["status"] == "READY":
                break
            result = self.sync()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(self.chunks(result)[1], original)

    def test_same_size_changed_bytes_still_fail_reaudit(self):
        original = record(1) + record(2)
        local = tempfile.TemporaryDirectory()
        self.addCleanup(local.cleanup)
        self.source = Path(local.name) / "source.jsonl"
        self.kwargs["source_path"] = self.source
        self.kwargs["max_bytes"] = len(original)
        self.source.write_bytes(original)
        self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        stat_before = self.source.stat()
        self.source.write_bytes(record(9) + record(2))
        os.utime(self.source, ns=(stat_before.st_atime_ns,
                                  stat_before.st_mtime_ns + 1_000_000_000))
        result = self.sync()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "archive_source_prefix_mismatch")

    def test_truncated_unarchived_tail_is_unknown(self):
        prefix = record(1)
        self.source.write_bytes(prefix + b'{"n": 2')
        first = self.sync()
        self.assertEqual(first["archived_bytes"], self.kwargs["max_bytes"])
        with self.source.open("r+b") as source:
            source.truncate(len(prefix))
        bad = self.sync()
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertEqual(bad["reason"], "source_truncated")

    def test_corrupt_chunk_or_manifest_is_unknown(self):
        self.source.write_bytes(record(1))
        result = self.sync()
        manifest, _ = self.chunks(result)
        part = Path(result["archive_path"]) / manifest["chunks"][0]["name"]
        original = part.read_bytes()
        part.write_bytes(record(9))
        self.assertEqual(self.sync()["status"], "UNKNOWN")
        part.write_bytes(original)
        Path(result["manifest_path"]).write_text("broken", encoding="utf-8")
        self.assertEqual(self.sync()["reason"], "corrupt_manifest")

    def test_manifest_missing_required_field_fails_closed(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        manifest_path = Path(first["manifest_path"])
        data = A._decrypt_manifest(A._key(), manifest_path,
                                   manifest_path.read_bytes())
        del data["source_size_seen"]
        manifest_path.write_bytes(A._encrypt_manifest(A._key(), manifest_path, data))
        self.assertEqual(self.sync()["reason"], "corrupt_manifest")

    def test_lower_budget_than_existing_chunk_is_explicit_failure(self):
        self.source.write_bytes(record(1))
        self.sync()
        self.kwargs["max_bytes"] = len(record(1)) - 1
        self.assertEqual(self.sync()["reason"], "chunk_exceeds_budget")

    def test_default_resumes_legacy_budget_before_13455941_byte_record(self):
        initial = record(1)
        self.source.write_bytes(initial)
        self.assertEqual(self.sync()["status"], "IN_PROGRESS")
        oversized_for_old_default = large_record(13_455_941)
        with self.source.open("ab") as output:
            output.write(oversized_for_old_default)
        result = A.sync_source(
            source_path=self.source, archive_root=self.root,
            provider="codex", session_id="session-123")
        self.assertEqual(A.DEFAULT_MAX_BYTES, A.MAX_CALL_BYTES)
        self.assertEqual(result["status"], "IN_PROGRESS", result["reason"])
        self.assertEqual(result["archived_bytes"], len(initial + oversized_for_old_default))
        ready = A.sync_source(
            source_path=self.source, archive_root=self.root,
            provider="codex", session_id="session-123")
        self.assertEqual(ready["status"], "READY")
        _, archived = self.chunks(ready)
        self.assertTrue(archived == initial + oversized_for_old_default)

    def test_record_above_hard_cap_is_split_and_preserved(self):
        self.source.write_bytes(large_record(A.MAX_CALL_BYTES + 1))
        result = A.sync_source(
            source_path=self.source, archive_root=self.root,
            provider="codex", session_id="session-123")
        self.assertEqual(result["status"], "IN_PROGRESS")
        for _ in range(5):
            result = A.sync_source(
                source_path=self.source, archive_root=self.root,
                provider="codex", session_id="session-123")
            if result["status"] == "READY":
                break
        self.assertEqual(result["status"], "READY")
        self.assertEqual(self.chunks(result)[1], self.source.read_bytes())

    def test_tamper_after_ready_revokes_status(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        manifest, _ = self.chunks(first)
        part = Path(first["archive_path"]) / manifest["chunks"][0]["name"]
        part.write_bytes(record(9))
        info = part.stat()
        os.utime(part, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))
        bad = self.sync()
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertEqual(bad["reason"], "archive_chunk_changed")

    def test_adopts_committed_chunk_after_manifest_interruption(self):
        first = record(1)
        self.source.write_bytes(first)
        result = self.sync()
        with self.source.open("ab") as output:
            output.write(record(2))
        folder = Path(result["archive_path"])
        pending = folder / A._chunk_name(A._key(), folder, len(first))
        pending.write_bytes(A._encrypt(A._key(), record(2), "codex",
                                       "session-123", len(first)))
        adopted = self.sync()
        self.assertEqual(adopted["status"], "IN_PROGRESS")
        self.assertEqual(adopted["reason"], "recovered_pending_chunk")
        _, archived = self.chunks(adopted)
        self.assertTrue(archived == first + record(2))

    def test_path_containment_and_permissions(self):
        self.source.write_bytes(record(1))
        self.kwargs["session_id"] = "../../escape"
        self.assertEqual(self.sync()["reason"], "invalid_identity")
        self.kwargs["session_id"] = "session-123"
        self.kwargs["archive_root"] = "/tmp/forbidden-session-archive"
        self.assertEqual(self.sync()["reason"], "archive_root_not_on_newdrive")
        self.kwargs["archive_root"] = "relative/archive"
        self.assertEqual(self.sync()["reason"], "invalid_archive_root")
        self.kwargs["archive_root"] = self.root
        result = self.sync()
        manifest, _ = self.chunks(result)
        for directory in (self.root, Path(result["archive_path"])):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode) & 0o077, 0)
        for path in (Path(result["manifest_path"]),
                     A._local_lock_path(Path(result["archive_path"]), "archive"),
                     Path(result["archive_path"]) / manifest["chunks"][0]["name"]):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
        anchor = A._anchor_path(A._key(), self.root.resolve(), "codex",
                                "session-123")
        self.assertEqual(stat.S_IMODE(A._KEY_PATH.stat().st_mode) & 0o077, 0)
        self.assertEqual(stat.S_IMODE(anchor.stat().st_mode) & 0o077, 0)
        self.assertEqual(A._KEY_PATH.stat().st_dev,
                         Path("/System/Volumes/Data").stat().st_dev)
        self.assertEqual(anchor.stat().st_dev,
                         Path("/System/Volumes/Data").stat().st_dev)
        self.assertTrue(Path(result["archive_path"]).resolve().is_relative_to(
            self.root.resolve()))

    def test_symlinked_session_path_cannot_escape_archive_root(self):
        self.source.write_bytes(record(1))
        self.root.mkdir(parents=True, mode=0o700)
        folder = A._archive_folder(self.root.resolve(), A._key(create=True),
                                   "codex", "session-123")
        outside = Path(self.temp.name) / "outside"
        outside.mkdir(mode=0o700)
        folder.symlink_to(outside, target_is_directory=True)
        result = self.sync()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "archive_path_escape")
        self.assertEqual(list(outside.iterdir()), [])

    def test_hash_chain_records_chunk_identity_without_raw_text(self):
        self.source.write_bytes(record(1))
        result = self.sync()
        manifest, _ = self.chunks(result)
        encrypted = (Path(result["archive_path"]) /
                     manifest["chunks"][0]["name"]).read_bytes()
        self.assertEqual(manifest["chunks"][0]["sha256"],
                         hashlib.sha256(encrypted).hexdigest())
        self.assertNotIn(b"private transcript content", encrypted)
        sealed = Path(result["manifest_path"]).read_bytes()
        self.assertNotIn(b"private transcript content", sealed)
        self.assertNotIn(str(self.source).encode(), sealed)
        self.assertNotIn(b"session-123", sealed)
        self.assertNotIn(b"codex", sealed)
        self.assertNotIn("session-123", Path(result["archive_path"]).name)
        self.assertEqual(len(Path(result["archive_path"]).name), 64)
        self.assertIn(len(encrypted) - A._CIPHER_OVERHEAD, A._CHUNK_BUCKETS)
        self.assertNotEqual(len(encrypted), len(record(1)) + A._CIPHER_OVERHEAD)
        self.assertNotIn("private transcript content", str(result))
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"private transcript content", path.read_bytes())
        self.assertEqual(list(self.root.rglob("*.jsonl")), [])

    def test_first_use_key_ignores_benign_fs_files_but_not_archive_evidence(self):
        self.root.mkdir(parents=True)
        (self.root / ".DS_Store").write_bytes(b"metadata")
        with tempfile.TemporaryDirectory() as local:
            anchor_dir = Path(local) / "anchors"
            with mock.patch.object(A, "_ANCHOR_DIR", anchor_dir), \
                    mock.patch.object(A, "_KEY_PATH", Path(local) / "missing-key"):
                with mock.patch.object(A, "_key", return_value=b"k" * 32) as key:
                    A._archive_key(self.root)
                    self.assertTrue(key.call_args.kwargs["create"])
                    (self.root / ("a" * 64)).mkdir()
                    A._archive_key(self.root)
                    self.assertFalse(key.call_args.kwargs["create"])
                    (self.root / ("a" * 64)).rmdir()
                    anchor_dir.mkdir()
                    (anchor_dir / "old-anchor").write_bytes(b"evidence")
                    A._archive_key(self.root)
                    self.assertFalse(key.call_args.kwargs["create"])

    def test_existing_key_does_not_rescan_archive_root(self):
        with tempfile.TemporaryDirectory() as local:
            key_path = Path(local) / "archive-key"
            key_path.write_bytes(b"k" * 32)
            with mock.patch.object(A, "_KEY_PATH", key_path), \
                    mock.patch.object(A, "_key", return_value=b"k" * 32) as key, \
                    mock.patch.object(Path, "iterdir", side_effect=AssertionError("rescan")):
                self.assertEqual(A._archive_key(self.root), b"k" * 32)
                key.assert_called_once_with(create=False)

    def test_old_manifest_is_rejected_after_anchor_advances(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        manifest_path = Path(first["manifest_path"])
        old_manifest = manifest_path.read_bytes()
        with self.source.open("ab") as output:
            output.write(record(2))
        self.assertEqual(self.sync()["status"], "IN_PROGRESS")
        manifest_path.write_bytes(old_manifest)
        bad = self.sync()
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertEqual(bad["reason"], "archive_rollback_or_anchor_mismatch")

    def test_crash_after_manifest_write_recovers_one_signed_generation(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        old_manifest = Path(first["manifest_path"]).read_bytes()
        with self.source.open("ab") as output:
            output.write(record(2))
        original_write = A._atomic_bytes
        failed = False

        def fail_one_anchor(path, payload):
            nonlocal failed
            if path.parent == A._ANCHOR_DIR and not failed:
                failed = True
                raise OSError("simulated power loss")
            return original_write(path, payload)

        with mock.patch.object(A, "_atomic_bytes", side_effect=fail_one_anchor):
            interrupted = self.sync()
        self.assertTrue(failed, interrupted["reason"])
        self.assertEqual(interrupted["status"], "UNKNOWN")
        self.assertEqual(interrupted["reason"], "archive_io_error")
        for _ in range(4):
            recovered = self.sync()
            if recovered["status"] == "READY":
                break
        self.assertEqual(recovered["status"], "READY")
        self.assertTrue(b"".join(A.iter_plaintext_chunks(recovered["manifest_path"]))
                        == record(1) + record(2))
        Path(first["manifest_path"]).write_bytes(old_manifest)
        self.assertEqual(self.sync()["reason"],
                         "archive_rollback_or_anchor_mismatch")

    def test_missing_local_key_and_crypto_fail_closed(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        with tempfile.TemporaryDirectory() as local:
            missing = Path(local) / "archive-key"
            with mock.patch.object(A, "_KEY_PATH", missing):
                self.assertEqual(A.verified_chunks(first["manifest_path"])["reason"],
                                 "missing_archive_key")
                self.assertEqual(self.sync()["reason"], "missing_archive_key")
                self.assertFalse(missing.exists())
        with mock.patch.object(A, "AESGCM", None):
            self.assertEqual(A.verified_chunks(first["manifest_path"])["reason"],
                             "crypto_unavailable")

    def test_exfat_or_world_readable_key_is_rejected(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        with mock.patch.object(A, "_KEY_PATH", self.root / "bad-key"):
            self.assertEqual(A.verified_chunks(first["manifest_path"])["reason"],
                             "local_apfs_required")
        with tempfile.TemporaryDirectory() as local:
            exposed = Path(local) / "archive-key"
            exposed.write_bytes(b"k" * 32)
            exposed.chmod(0o644)
            with mock.patch.object(A, "_KEY_PATH", exposed):
                self.assertEqual(A.verified_chunks(first["manifest_path"])["reason"],
                                 "insecure_archive_permissions")

    def test_legacy_unencrypted_manifest_is_not_migrated_or_read(self):
        self.source.write_bytes(record(1))
        A._key(create=True)
        folder = self.root / "codex" / "session-123"
        folder.mkdir(parents=True, mode=0o700)
        manifest = folder / "manifest.json"
        manifest.write_text('{"format_version":1}', encoding="utf-8")
        self.assertEqual(self.sync()["reason"], "legacy_metadata_archive_present")
        self.assertEqual(A.verified_chunks(manifest)["reason"],
                         "invalid_manifest_path")
        self.assertEqual(list(folder.glob("*.enc")), [])

    def test_anchor_tampering_fails_closed(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        anchor = A._anchor_path(A._key(), self.root.resolve(), "codex",
                                "session-123")
        data = json.loads(anchor.read_text())
        data["manifest_sha256"] = "0" * 64
        anchor.write_text(json.dumps(data))
        bad = A.verified_chunks(first["manifest_path"])
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertEqual(bad["reason"], "corrupt_local_anchor")

    def test_plaintext_reader_raises_public_fixed_reason_on_tamper(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        manifest, _ = self.chunks(first)
        part = Path(first["archive_path"]) / manifest["chunks"][0]["name"]
        corrupted = bytearray(part.read_bytes())
        corrupted[-1] ^= 1
        part.write_bytes(corrupted)
        with self.assertRaises(A.ArchiveReadError) as caught:
            list(A.iter_plaintext_chunks(first["manifest_path"]))
        self.assertIn(caught.exception.reason,
                      ("archive_chunk_changed", "corrupt_archive_chunk"))
        self.assertNotIn("private transcript content", str(caught.exception))

    def test_plaintext_reader_is_chunk_bounded_and_later_failure_is_explicit(self):
        self.source.write_bytes(record(1) + record(2))
        self.sync()
        second = self.sync()
        for _ in range(4):
            outcome = self.sync()
            if outcome["status"] == "READY":
                break
        self.assertEqual(outcome["status"], "READY")
        manifest, _ = self.chunks(second)
        self.assertEqual(len(manifest["chunks"]), 2)
        part = Path(second["archive_path"]) / manifest["chunks"][1]["name"]
        reader = A.iter_plaintext_chunks(second["manifest_path"])
        try:
            self.assertTrue(next(reader) == (record(1) + record(2))[:
                self.kwargs["max_bytes"]])
            corrupted = bytearray(part.read_bytes())
            corrupted[-1] ^= 1
            part.write_bytes(corrupted)
            with self.assertRaises(A.ArchiveReadError):
                next(reader)
        finally:
            reader.close()

    def test_verified_chunks_survive_source_deletion(self):
        original = record(1) + record(2)
        self.source.write_bytes(original)
        result = self.sync()
        for _ in range(5):
            if result["status"] == "READY":
                break
            result = self.sync()
        self.assertEqual(result["status"], "READY")
        self.source.unlink()
        read = A.verified_chunks(result["manifest_path"])
        self.assertEqual(read["status"], "READY")
        self.assertFalse(read["auto_inject"])
        self.assertEqual(read["provider"], "codex")
        self.assertEqual(read["session_id"], "session-123")
        self.assertEqual(read["archived_bytes"], len(original))
        self.assertTrue(b"".join(A.iter_plaintext_chunks(result["manifest_path"]))
                        == original)
        self.assertNotIn("chunk_paths", read)
        self.assertNotIn("private transcript content", str(read))

    def test_grok_raw_session_is_encrypted_and_restorable(self):
        original = record(1) + record(2)
        self.source.write_bytes(original)
        self.kwargs["provider"] = "grok"
        result = self.sync()
        for _ in range(5):
            if result["status"] == "READY":
                break
            result = self.sync()
        self.assertEqual(result["status"], "READY")
        self.source.unlink()
        verified = A.verified_chunks(result["manifest_path"])
        self.assertEqual(verified["status"], "READY")
        self.assertEqual(verified["provider"], "grok")
        self.assertEqual(b"".join(A.iter_plaintext_chunks(result["manifest_path"])), original)

    def test_reconciler_rejects_corrupted_ciphertext(self):
        self.source.write_bytes(record(1) + record(2))
        result = self.sync()
        for _ in range(5):
            if result["status"] == "READY":
                break
            result = self.sync()
        self.assertEqual(result["status"], "READY")
        info = self.source.stat()
        version = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns]
        key = A._archive_key(self.root.resolve())
        self.assertTrue(R._verify_done_archive(self.root.resolve(), key,
                                                "codex", "session-123", version))
        part = next(path for path in Path(result["archive_path"]).glob("*.enc")
                    if path.name != "manifest.enc" and not path.name.startswith("._"))
        damaged = bytearray(part.read_bytes())
        damaged[-1] ^= 1
        part.write_bytes(damaged)
        self.assertFalse(R._verify_done_archive(self.root.resolve(), key,
                                                 "codex", "session-123", version))

    def test_verified_chunks_reject_incomplete_archive_without_source(self):
        self.source.write_bytes(record(1) + record(2))
        first = self.sync()
        self.source.unlink()
        read = A.verified_chunks(first["manifest_path"])
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["reason"], "archive_incomplete")
        self.assertEqual(read["encrypted_chunk_paths"], [])

    def test_verified_chunks_detect_tampering_without_source(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        self.source.unlink()
        manifest, _ = self.chunks(first)
        part = Path(first["archive_path"]) / manifest["chunks"][0]["name"]
        part.write_bytes(record(9))
        read = A.verified_chunks(first["manifest_path"])
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["encrypted_chunk_paths"], [])

    def test_verified_chunks_reject_hash_chain_tamper(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        self.source.unlink()
        path = Path(first["manifest_path"])
        manifest = A._decrypt_manifest(A._key(), path, path.read_bytes())
        manifest["chain_sha256"] = "0" * 64
        path.write_bytes(A._encrypt_manifest(A._key(), path, manifest))
        read = A.verified_chunks(path)
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["encrypted_chunk_paths"], [])

    def test_verified_chunks_reject_manifest_symlink(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        alias = Path(first["archive_path"]) / "alias"
        alias.symlink_to(Path(first["manifest_path"]))
        read = A.verified_chunks(alias)
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["encrypted_chunk_paths"], [])

    def test_verified_chunks_reject_path_outside_newdrive(self):
        read = A.verified_chunks("/tmp/not-an-archive/manifest.json")
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["encrypted_chunk_paths"], [])


if __name__ == "__main__":
    unittest.main()
