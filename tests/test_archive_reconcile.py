"""The scheduled archive receipt contains counts, never transcript content."""

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "apps", "forseti-cli"))
import archive_reconcile as R  # noqa: E402


class ArchiveReconcileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.receipt = Path(self.temp.name) / "receipt.json"

    def test_success_receipt_is_aggregate_only(self):
        result = {"inventory": 2, "next_index": 2,
                  "counts": {"READY": 2, "UNKNOWN": 0, "IN_PROGRESS": 0},
                  "unknown_reasons": {}, "unknown_items": [],
                  "scan_complete": True, "batch_all_ready": True}
        with mock.patch.object(R.archive_backfill, "import_batch", return_value=result):
            self.assertEqual(R.run_once(receipt=self.receipt), 0)
        payload = json.loads(self.receipt.read_text())
        self.assertEqual(payload["status"], "READY")
        self.assertEqual(payload["scanned"], 2)
        self.assertNotIn("unknown_items", payload)
        self.assertEqual(stat.S_IMODE(self.receipt.stat().st_mode), 0o600)

    def test_partial_run_exits_nonzero_without_source_identity(self):
        result = {"inventory": 2, "next_index": 1,
                  "counts": {"READY": 0, "UNKNOWN": 1, "IN_PROGRESS": 0},
                  "unknown_reasons": {"source_modified": 1},
                  "unknown_items": [{"session_id": "PRIVATE-ID"}],
                  "scan_complete": False, "batch_all_ready": False}
        with mock.patch.object(R.archive_backfill, "import_batch", return_value=result):
            self.assertEqual(R.run_once(receipt=self.receipt), 2)
        payload = self.receipt.read_text()
        self.assertNotIn("PRIVATE-ID", payload)
        self.assertEqual(json.loads(payload)["status"], "UNKNOWN")
