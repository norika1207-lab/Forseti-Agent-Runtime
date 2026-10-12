"""The periodic receipt is aggregate-only; progress is private and authenticated."""

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
import archive_reconcile as R  # noqa: E402


class ArchiveReconcileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.receipt = base / "receipt.json"
        self.lock = base / "backfill.lock"
        self.one = base / "one.jsonl"
        self.two = base / "two.jsonl"
        self.one.write_bytes(b"private one\n")
        self.two.write_bytes(b"private two\n")
        self.inventory = [("codex", "PRIVATE-ONE", self.one),
                          ("claude", "PRIVATE-TWO", self.two)]

    def sync_ready(self, **kwargs):
        return {"status": "READY", "reason": "caught_up",
                "source_bytes": Path(kwargs["source_path"]).stat().st_size}

    def run_with(self, *, limit=R.MAX_SOURCES):
        with (mock.patch.object(R, "_check_archive_access"),
              mock.patch.object(R.archive_backfill, "sources", return_value=self.inventory),
              mock.patch.object(R, "_verify_done_archive", return_value=True),
              mock.patch.object(R.source_archive, "sync_source", side_effect=self.sync_ready) as sync):
            code = R.run_once(receipt=self.receipt, lock=self.lock, limit=limit)
        return code, sync

    def test_full_receipt_and_authenticated_progress_hide_source_identity(self):
        code, sync = self.run_with()
        self.assertEqual(code, 0)
        self.assertEqual(sync.call_count, 2)
        summary = json.loads(self.receipt.read_text())
        self.assertEqual(summary["status"], "READY")
        self.assertEqual(summary["budget_type"], "cooperative")
        self.assertEqual(summary["counts"]["READY"], 2)
        self.assertEqual(summary["remaining"], 0)
        self.assertNotIn("PRIVATE", self.receipt.read_text())
        progress = self.receipt.with_name("backfill-progress.json")
        self.assertNotIn("PRIVATE", progress.read_text())
        self.assertEqual(stat.S_IMODE(progress.stat().st_mode), 0o600)

    def test_inserted_source_keeps_done_work(self):
        code, sync = self.run_with(limit=1)
        self.assertEqual(code, 2)
        self.assertEqual(Path(sync.call_args.kwargs["source_path"]), self.one)
        extra = Path(self.temp.name) / "new.jsonl"
        extra.write_bytes(b"private new\n")
        self.inventory.insert(0, ("claude", "PRIVATE-NEW", extra))
        code, sync = self.run_with(limit=1)
        self.assertEqual(code, 2)
        self.assertEqual(Path(sync.call_args.kwargs["source_path"]), extra)
        self.assertEqual(json.loads(self.receipt.read_text())["counts"]["READY"], 2)
        code, sync = self.run_with(limit=1)
        self.assertEqual(code, 0)
        self.assertEqual(Path(sync.call_args.kwargs["source_path"]), self.two)

    def test_changed_source_is_rechecked_without_rescanning_other(self):
        self.assertEqual(self.run_with()[0], 0)
        with self.one.open("ab") as output:
            output.write(b"next line\n")
        code, sync = self.run_with()
        self.assertEqual(code, 0)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(Path(sync.call_args.kwargs["source_path"]), self.one)

    def test_source_changed_during_sync_is_not_marked_ready(self):
        def change_source(**kwargs):
            result = self.sync_ready(**kwargs)
            if Path(kwargs["source_path"]) == self.one:
                self.one.write_bytes(b"changed one\n")
                before = self.one.stat()
                os.utime(self.one, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000))
            return result

        with (mock.patch.object(R, "_check_archive_access"),
              mock.patch.object(R.archive_backfill, "sources", return_value=self.inventory),
              mock.patch.object(R.source_archive, "sync_source", side_effect=change_source)):
            self.assertEqual(R.run_once(receipt=self.receipt, lock=self.lock), 2)
        summary = json.loads(self.receipt.read_text())
        self.assertEqual(summary["status"], "IN_PROGRESS")
        self.assertEqual(summary["counts"]["READY"], 1)
        self.assertEqual(summary["remaining"], 1)

    def test_long_active_source_does_not_starve_later_sources(self):
        def sync(**kwargs):
            if Path(kwargs["source_path"]) == self.one:
                time.sleep(0.003)
                return {"status": "IN_PROGRESS", "reason": "auditing"}
            return self.sync_ready(**kwargs)

        with (mock.patch.object(R, "_check_archive_access"),
              mock.patch.object(R, "MAX_SOURCE_SECONDS", 0.001),
              mock.patch.object(R.archive_backfill, "sources", return_value=self.inventory),
              mock.patch.object(R.source_archive, "sync_source", side_effect=sync) as called):
            self.assertEqual(R.run_once(receipt=self.receipt, lock=self.lock), 2)
        self.assertEqual([Path(call.kwargs["source_path"]) for call in called.call_args_list],
                         [self.one, self.two])
        summary = json.loads(self.receipt.read_text())
        self.assertEqual(summary["status"], "IN_PROGRESS")
        self.assertEqual(summary["counts"],
                         {"READY": 1, "UNKNOWN": 0, "IN_PROGRESS": 1})

    def test_tampered_progress_cannot_skip_sources(self):
        self.assertEqual(self.run_with()[0], 0)
        progress = self.receipt.with_name("backfill-progress.json")
        data = json.loads(progress.read_text())
        data["done"].clear()
        progress.write_text(json.dumps(data))
        code, sync = self.run_with()
        self.assertEqual(code, 0)
        self.assertEqual(sync.call_count, 2)

    def test_corrupt_archive_revokes_cached_ready(self):
        self.assertEqual(self.run_with()[0], 0)
        with (mock.patch.object(R, "_check_archive_access"),
              mock.patch.object(R.archive_backfill, "sources", return_value=self.inventory),
              mock.patch.object(R, "_verify_done_archive", return_value=False),
              mock.patch.object(R.source_archive, "sync_source") as sync):
            self.assertEqual(R.run_once(receipt=self.receipt, lock=self.lock), 2)
        sync.assert_not_called()
        summary = json.loads(self.receipt.read_text())
        self.assertEqual(summary["status"], "UNKNOWN")
        self.assertEqual(summary["counts"]["READY"], 0)
        self.assertEqual(summary["unknown_reasons"], {"archive_or_source_changed": 2})

    def test_large_authenticated_progress_remains_loadable(self):
        progress = self.receipt.with_name("backfill-progress.json")
        done = {f"{n:064x}": [1, 2, 3, 4] for n in range(30000)}
        R._write_progress(progress, done)
        self.assertGreater(progress.stat().st_size, 2000000)
        self.assertEqual(R._load_progress(progress), done)

    def test_inventory_time_counts_against_budget(self):
        def slow_inventory(_home):
            time.sleep(0.02)
            return self.inventory

        with (mock.patch.object(R, "_check_archive_access"),
              mock.patch.object(R.archive_backfill, "sources", side_effect=slow_inventory),
              mock.patch.object(R.source_archive, "sync_source") as sync):
            self.assertEqual(R.run_once(receipt=self.receipt, lock=self.lock,
                                        seconds=0.001), 2)
        sync.assert_not_called()
        self.assertEqual(json.loads(self.receipt.read_text())["status"], "IN_PROGRESS")

    def test_running_receipt_precedes_source_sync(self):
        def inspect(**kwargs):
            self.assertEqual(json.loads(self.receipt.read_text())["status"], "RUNNING")
            return self.sync_ready(**kwargs)

        with (mock.patch.object(R, "_check_archive_access"),
              mock.patch.object(R.archive_backfill, "sources", return_value=self.inventory),
              mock.patch.object(R, "_verify_done_archive", return_value=True),
              mock.patch.object(R.source_archive, "sync_source", side_effect=inspect)):
            self.assertEqual(R.run_once(receipt=self.receipt, lock=self.lock), 0)

    def test_newdrive_denial_fails_before_inventory(self):
        def check(_root):
            stage = self.receipt.with_name("reconcile-stage.json")
            self.assertEqual(json.loads(stage.read_text())["phase"], "check_access")
            raise PermissionError(1, "denied")

        with (mock.patch.object(R, "_check_archive_access", side_effect=check),
              mock.patch.object(R.archive_backfill, "sources") as sources):
            self.assertEqual(R.run_once(receipt=self.receipt, lock=self.lock), 2)
        sources.assert_not_called()
        self.assertEqual(json.loads(self.receipt.read_text())["reason"],
                         "newdrive_permission_denied")

    def test_second_reconciler_does_not_replace_receipt(self):
        self.receipt.write_text("older receipt")
        with (mock.patch.object(R.fcntl, "flock", side_effect=BlockingIOError),
              mock.patch.object(R.archive_backfill, "sources") as sources):
            self.assertEqual(R.run_once(receipt=self.receipt, lock=self.lock), 3)
        sources.assert_not_called()
        self.assertEqual(self.receipt.read_text(), "older receipt")
