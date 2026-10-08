"""Bounded raw-source archive tests; failures never print transcript content."""

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "forseti-cli"))
import source_archive as A  # noqa: E402


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

    def sync(self):
        return A.sync_source(**self.kwargs)

    def chunks(self, result):
        manifest = json.loads(Path(result["manifest_path"]).read_text())
        folder = Path(result["archive_path"])
        return manifest, b"".join((folder / c["name"]).read_bytes()
                                  for c in manifest["chunks"])

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
        self.assertEqual(first["archived_bytes"], len(record(1)))
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

    def test_incomplete_final_record_waits_then_resumes(self):
        full = record(1) + record(2)
        self.source.write_bytes(record(1) + record(2)[:-2])
        first = self.sync()
        self.assertEqual(first["status"], "IN_PROGRESS")
        self.assertEqual(first["archived_bytes"], len(record(1)))
        self.assertEqual(self.sync()["reason"], "awaiting_complete_record")
        with self.source.open("ab") as output:
            output.write(full[len(record(1) + record(2)[:-2]):])
        self.assertEqual(self.sync()["status"], "IN_PROGRESS")

    def test_finalized_source_with_incomplete_jsonl_is_unknown(self):
        self.source.write_bytes(record(1) + b'{"n":')
        self.kwargs["source_finalized"] = True
        self.assertEqual(self.sync()["status"], "IN_PROGRESS")
        bad = self.sync()
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertEqual(bad["reason"], "corrupt_source_jsonl")
        self.assertIsNone(bad["archive_path"])

    def test_finalized_empty_source_is_unknown(self):
        self.source.write_bytes(b"")
        self.kwargs["source_finalized"] = True
        self.assertEqual(self.sync()["reason"], "empty_source")

    def test_missing_and_corrupt_source_fail_closed(self):
        self.assertEqual(self.sync()["reason"], "missing_source")
        self.source.write_bytes(b"not-json\n")
        bad = self.sync()
        self.assertEqual(bad["status"], "UNKNOWN")
        self.assertEqual(bad["reason"], "corrupt_source_jsonl")
        self.assertIsNone(bad["archive_path"])

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

    def test_truncated_unarchived_tail_is_unknown(self):
        prefix = record(1)
        self.source.write_bytes(prefix + b'{"n": 2')
        first = self.sync()
        self.assertEqual(first["archived_bytes"], len(prefix))
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
        part.write_bytes(record(9))
        self.assertEqual(self.sync()["status"], "UNKNOWN")
        part.write_bytes(record(1))
        Path(result["manifest_path"]).write_text("broken", encoding="utf-8")
        self.assertEqual(self.sync()["reason"], "corrupt_manifest")

    def test_manifest_missing_required_field_fails_closed(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        manifest_path = Path(first["manifest_path"])
        data = json.loads(manifest_path.read_text())
        del data["source_size_seen"]
        manifest_path.write_text(json.dumps(data), encoding="utf-8")
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
        self.assertEqual(result["status"], "IN_PROGRESS")
        self.assertEqual(result["archived_bytes"], len(initial + oversized_for_old_default))
        ready = A.sync_source(
            source_path=self.source, archive_root=self.root,
            provider="codex", session_id="session-123")
        self.assertEqual(ready["status"], "READY")
        _, archived = self.chunks(ready)
        self.assertTrue(archived == initial + oversized_for_old_default)

    def test_record_above_hard_cap_fails_closed(self):
        self.source.write_bytes(large_record(A.MAX_CALL_BYTES + 1))
        result = A.sync_source(
            source_path=self.source, archive_root=self.root,
            provider="codex", session_id="session-123")
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "record_exceeds_budget")
        self.assertFalse(result["auto_inject"])

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
        pending = Path(result["archive_path"]) / f"{len(first):016x}.jsonl"
        pending.write_bytes(record(2))
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
        for directory in (self.root, self.root / "codex", Path(result["archive_path"])):
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode) & 0o077, 0)
        for path in (Path(result["manifest_path"]),
                     Path(result["archive_path"]) / "archive.lock",
                     Path(result["archive_path"]) / manifest["chunks"][0]["name"]):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)
        self.assertTrue(Path(result["archive_path"]).resolve().is_relative_to(
            self.root.resolve()))

    def test_symlinked_session_path_cannot_escape_archive_root(self):
        self.source.write_bytes(record(1))
        (self.root / "codex").mkdir(parents=True, mode=0o700)
        outside = Path(self.temp.name) / "outside"
        outside.mkdir(mode=0o700)
        (self.root / "codex" / "session-123").symlink_to(outside,
                                                           target_is_directory=True)
        result = self.sync()
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "archive_path_escape")
        self.assertEqual(list(outside.iterdir()), [])

    def test_hash_chain_records_chunk_identity_without_raw_text(self):
        self.source.write_bytes(record(1))
        result = self.sync()
        manifest, archived = self.chunks(result)
        self.assertEqual(manifest["chunks"][0]["sha256"],
                         hashlib.sha256(archived).hexdigest())
        self.assertNotIn("private transcript content", str(result))

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
        self.assertTrue(b"".join(Path(p).read_bytes() for p in read["chunk_paths"])
                        == original)
        self.assertNotIn("private transcript content", str(read))

    def test_verified_chunks_reject_incomplete_archive_without_source(self):
        self.source.write_bytes(record(1) + record(2))
        first = self.sync()
        self.source.unlink()
        read = A.verified_chunks(first["manifest_path"])
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["reason"], "archive_incomplete")
        self.assertEqual(read["chunk_paths"], [])

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
        self.assertEqual(read["chunk_paths"], [])

    def test_verified_chunks_reject_hash_chain_tamper(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        self.source.unlink()
        path = Path(first["manifest_path"])
        manifest = json.loads(path.read_text())
        manifest["chain_sha256"] = "0" * 64
        path.write_text(json.dumps(manifest), encoding="utf-8")
        read = A.verified_chunks(path)
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["chunk_paths"], [])

    def test_verified_chunks_reject_manifest_symlink(self):
        self.source.write_bytes(record(1))
        first = self.sync()
        self.assertEqual(self.sync()["status"], "READY")
        alias = Path(first["archive_path"]) / "alias"
        alias.symlink_to(Path(first["manifest_path"]))
        read = A.verified_chunks(alias)
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["chunk_paths"], [])

    def test_verified_chunks_reject_path_outside_newdrive(self):
        read = A.verified_chunks("/tmp/not-an-archive/manifest.json")
        self.assertEqual(read["status"], "UNKNOWN")
        self.assertEqual(read["chunk_paths"], [])


if __name__ == "__main__":
    unittest.main()
