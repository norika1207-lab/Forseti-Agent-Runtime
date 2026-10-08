"""Background archive launcher tests; never emit transcript contents."""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "forseti-cli"))
import archive_worker as W  # noqa: E402
import source_archive as A  # noqa: E402


def record(n):
    return json.dumps({"n": n, "text": "PRIVATE-SENTINEL-DO-NOT-LOG"}).encode() + b"\n"


class ArchiveWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/Volumes/NewDrive")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.source = base / "source.jsonl"
        self.root = base / ".forseti" / "session_archive"
        self.kwargs = {"source_path": self.source, "archive_root": self.root,
                       "provider": "codex", "session_id": "session-123",
                       "max_bytes": len(record(1)), "watch_seconds": 3,
                       "interval_seconds": 0.05}
        self.addCleanup(self.cleanup_anchor)

    def cleanup_anchor(self):
        try:
            anchor = A._anchor_path(A._key(), self.root.resolve(), "codex",
                                    "session-123")
            anchor.unlink(missing_ok=True)
        except A.ArchiveReadError:
            pass

    def wait_child(self, pid):
        process = W._SPAWNED_CHILDREN.pop(pid, None)
        if process is not None:
            return process.wait(timeout=8)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status)
            time.sleep(0.02)
        self.fail("archive worker did not terminate")

    def receipt(self):
        path = self.root / "codex" / "session-123" / "worker-status.json"
        return json.loads(path.read_text())

    def test_launch_is_nonblocking_and_archive_is_byte_exact(self):
        original = record(1) + record(2) + record(3)
        self.source.write_bytes(original)
        started = time.monotonic()
        result = W.launch_worker(**self.kwargs)
        self.assertEqual(result["status"], "STARTED")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(self.wait_child(result["pid"]), 0)
        self.assertEqual(self.receipt()["status"], "READY")
        verified = A.verified_chunks(self.root / "codex" / "session-123" / "manifest.json")
        self.assertEqual(verified["status"], "READY")
        self.assertTrue(b"".join(A.iter_plaintext_chunks(verified["manifest_path"]))
                        == original)
        self.assertNotIn("chunk_paths", verified)
        self.assertFalse(result["auto_inject"])

    def test_duplicate_launch_has_one_live_worker(self):
        self.source.write_bytes(record(1)[:-1])
        options = dict(self.kwargs, watch_seconds=0.4)
        first = W.launch_worker(**options)
        self.assertEqual(first["status"], "STARTED")
        second = W.launch_worker(**options)
        self.assertEqual(second["status"], "ALREADY_RUNNING")
        self.assertIsNone(second["pid"])
        self.assertEqual(self.wait_child(first["pid"]), 3)
        self.assertEqual(self.receipt()["status"], "TIMED_OUT")

    def test_cli_prints_only_status_metadata(self):
        self.source.write_bytes(record(1))
        args = ["launch", "--source", str(self.source),
                "--archive-root", str(self.root), "--provider", "codex",
                "--session-id", "session-123", "--max-bytes", str(len(record(1))),
                "--watch-seconds", "3", "--interval-seconds", "0.05"]
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = W.main(args)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "STARTED")
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(self.wait_child(payload["pid"]), 0)
        self.assertNotIn("PRIVATE-SENTINEL", stdout.getvalue())
        self.assertNotIn("PRIVATE-SENTINEL", json.dumps(self.receipt()))

    def test_missing_source_and_invalid_session_fail_closed(self):
        missing = W.launch_worker(**self.kwargs)
        self.assertEqual(missing["status"], "UNKNOWN")
        self.assertEqual(missing["reason"], "missing_source")
        self.source.write_bytes(record(1))
        invalid = W.launch_worker(**dict(self.kwargs, session_id="../escape"))
        self.assertEqual(invalid["status"], "UNKNOWN")
        self.assertEqual(invalid["reason"], "invalid_identity")
        self.assertFalse((self.root / "escape").exists())

    def test_missing_crypto_does_not_spawn_worker(self):
        self.source.write_bytes(record(1))
        with mock.patch.object(A, "AESGCM", None):
            result = W.launch_worker(**self.kwargs)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertEqual(result["reason"], "crypto_unavailable")
        self.assertIsNone(result["pid"])

    def test_owner_only_worker_files(self):
        self.source.write_bytes(record(1))
        result = W.launch_worker(**self.kwargs)
        self.assertEqual(result["status"], "STARTED")
        self.assertEqual(self.wait_child(result["pid"]), 0)
        folder = self.root / "codex" / "session-123"
        for path in (folder, folder / "worker.lock", folder / "worker-status.json"):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode) & 0o077, 0)

    def test_short_watch_remains_bounded_on_large_source(self):
        self.source.write_bytes(record(1) * 1000)
        options = dict(self.kwargs, watch_seconds=0.05)
        result = W.launch_worker(**options)
        self.assertEqual(result["status"], "STARTED")
        self.assertEqual(self.wait_child(result["pid"]), 3)
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "TIMED_OUT")
        self.assertGreater(receipt["archived_bytes"], 0)
        self.assertLess(receipt["archived_bytes"], self.source.stat().st_size)

    def test_corrupt_source_fails_without_exposing_content(self):
        self.source.write_bytes(b"PRIVATE-SENTINEL-DO-NOT-LOG\n")
        result = W.launch_worker(**dict(self.kwargs, source_finalized=True))
        self.assertEqual(result["status"], "STARTED")
        self.assertEqual(self.wait_child(result["pid"]), 2)
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "UNKNOWN")
        self.assertNotIn("PRIVATE-SENTINEL", json.dumps(receipt))

    def test_default_worker_budget_accepts_record_above_four_mib(self):
        prefix, suffix = b'{"payload":"', b'"}\n'
        size = 4 * 1024 * 1024 + 1
        self.source.write_bytes(prefix + b"x" * (size - len(prefix) - len(suffix))
                                + suffix)
        options = {key: value for key, value in self.kwargs.items()
                   if key != "max_bytes"}
        options["watch_seconds"] = 10
        result = W.launch_worker(**options)
        self.assertEqual(result["status"], "STARTED")
        self.assertEqual(self.wait_child(result["pid"]), 0)
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "READY")
        self.assertEqual(receipt["archived_bytes"], size)

    def test_default_worker_fails_closed_above_hard_cap(self):
        prefix, suffix = b'{"payload":"', b'"}\n'
        size = A.MAX_CALL_BYTES + 1
        self.source.write_bytes(prefix + b"x" * (size - len(prefix) - len(suffix))
                                + suffix)
        options = {key: value for key, value in self.kwargs.items()
                   if key != "max_bytes"}
        result = W.launch_worker(**options)
        self.assertEqual(result["status"], "STARTED")
        self.assertEqual(self.wait_child(result["pid"]), 2)
        receipt = self.receipt()
        self.assertEqual(receipt["status"], "UNKNOWN")
        self.assertEqual(receipt["reason"], "record_exceeds_budget")


if __name__ == "__main__":
    unittest.main()
