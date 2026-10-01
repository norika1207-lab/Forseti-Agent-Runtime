"""Security and outcome contracts for the desktop required-reading backend."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import desktop_api as D  # noqa: E402


class RequiredReadingContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        (self.repo / ".forseti").mkdir()
        (self.repo / "docs").mkdir()
        self.old_repo = D.REPO
        D.REPO = self.repo

    def tearDown(self):
        D.REPO = self.old_repo
        self.tmp.cleanup()

    def row(self, name: str) -> dict:
        return next(row for row in D.spec_reading()["rows"]
                    if row["name"] == name)

    def write_control(self, name: str, content: str = "hello\n") -> Path:
        path = self.repo / ".forseti" / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_rows_use_stable_opaque_ids_without_raw_paths(self):
        self.write_control("ALLOWED.md")
        first = D.spec_reading()["rows"]
        second = D.spec_reading()["rows"]
        self.assertEqual(
            [(r["document_id"], r["name"]) for r in first],
            [(r["document_id"], r["name"]) for r in second],
        )
        for row in first:
            self.assertTrue(row["document_id"].startswith("doc_"))
            self.assertNotIn("path", row)
            self.assertNotIn(str(self.repo), json.dumps(row))
            self.assertIn("source_category", row)

    def test_allowed_fetch_is_inspection_only_and_returns_hash(self):
        path = self.write_control("ALLOWED.md")
        row = self.row("ALLOWED.md")
        result = D.read_required_document(row["document_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["code"], "OK")
        self.assertEqual(result["content"], "hello\n")
        self.assertEqual(result["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(result["size"], len(path.read_bytes()))
        self.assertEqual(result["reading_state"], "沒有閱讀紀錄")
        self.assertFalse((self.repo / ".forseti" / "reading_coverage.jsonl").exists())
        self.assertFalse(result["evidence_contract"]["records_on_fetch"])
        self.assertEqual(result["evidence_contract"]["actor_scope"],
                         "AI_WORKER_SESSION_ONLY")
        self.assertFalse(result["evidence_contract"]["human_fetch_records"])
        self.assertEqual(result["evidence_contract"]["dispatch"]["action"],
                         "AI_READ_REQUIRED_DOCUMENT")
        self.assertFalse(Path(result["canonical_display_path"]).is_absolute())

    def test_unknown_and_traversal_ids_are_rejected(self):
        for document_id, code in (
            ("doc_unknown", "UNKNOWN_DOCUMENT_ID"),
            ("../doc_unknown", "PATH_TRAVERSAL_REJECTED"),
            ("/etc/passwd", "PATH_TRAVERSAL_REJECTED"),
            ("~/.ssh/id_rsa", "PATH_TRAVERSAL_REJECTED"),
            ("doc_x/y", "PATH_TRAVERSAL_REJECTED"),
        ):
            with self.subTest(document_id=document_id):
                self.assertEqual(D.read_required_document(document_id)["code"], code)

    def test_symlink_missing_oversized_non_utf8_and_non_regular_rejected(self):
        outside = Path(self.tmp.name).parent / (Path(self.tmp.name).name + "-outside")
        outside.mkdir()
        try:
            outside_file = outside / "secret.md"
            outside_file.write_text("secret", encoding="utf-8")
            link = self.repo / ".forseti" / "ESCAPE.md"
            link.symlink_to(outside_file)
            self.assertEqual(
                D.read_required_document(self.row("ESCAPE.md")["document_id"])["code"],
                "SYMLINK_ESCAPE",
            )

            missing = self.row("spec-v2.0.md")
            self.assertEqual(
                D.read_required_document(missing["document_id"])["code"],
                "MISSING_FILE",
            )

            huge = self.write_control("HUGE.md", "12345")
            old_limit = D.REQUIRED_DOCUMENT_MAX_BYTES
            D.REQUIRED_DOCUMENT_MAX_BYTES = 2
            try:
                self.assertEqual(
                    D.read_required_document(self.row("HUGE.md")["document_id"])["code"],
                    "OVERSIZED_FILE",
                )
            finally:
                D.REQUIRED_DOCUMENT_MAX_BYTES = old_limit
            self.assertTrue(huge.exists())

            binary = self.repo / ".forseti" / "BINARY.md"
            binary.write_bytes(b"\xff")
            self.assertEqual(
                D.read_required_document(self.row("BINARY.md")["document_id"])["code"],
                "NON_UTF8_FILE",
            )

            directory = self.repo / ".forseti" / "DIR.md"
            directory.mkdir()
            self.assertEqual(
                D.read_required_document(self.row("DIR.md")["document_id"])["code"],
                "NON_REGULAR_FILE",
            )
        finally:
            outside_file = outside / "secret.md"
            if outside_file.exists():
                outside_file.unlink()
            outside.rmdir()

    def test_stale_hash_exposes_reason_without_promoting_read(self):
        path = self.write_control("STALE.md")
        log = self.repo / ".forseti" / "reading_coverage.jsonl"
        log.write_text(json.dumps({
            "path": str(path), "ratio": 1.0, "level": "FULL_READ",
            "content_hash": "deadbeefdead", "at": 1, "session": "worker-session",
        }) + "\n", encoding="utf-8")
        result = D.read_required_document(self.row("STALE.md")["document_id"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["reading_state"], "讀過但檔案已經變了")
        self.assertEqual(result["evidence"]["coverage_state"], "STALE")
        self.assertEqual(result["evidence"]["stale_reason"], "content_hash_mismatch")
        self.assertEqual(result["evidence"]["owner_type"], "UNKNOWN")
        self.assertEqual(result["evidence"]["block_hashes_status"], "NOT_RECORDED")
        self.assertEqual(log.read_text(encoding="utf-8").count("deadbeefdead"), 1)

    def test_only_explicit_ai_worker_record_can_be_valid_evidence(self):
        path = self.write_control("WORKER.md")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        log = self.repo / ".forseti" / "reading_coverage.jsonl"
        log.write_text(json.dumps({
            "path": str(path), "ratio": 1.0, "level": "FULL_READ",
            "content_hash": digest, "at": 2, "session": "worker-session",
            "actor_type": "AI_WORKER", "worker_identity": "worker-7",
            "covered": [[1, 2]], "gaps": [],
        }) + "\n", encoding="utf-8")
        result = D.read_required_document(self.row("WORKER.md")["document_id"])
        self.assertEqual(result["reading_state"], "讀完")
        self.assertEqual(result["evidence"]["owner_type"], "AI_WORKER")
        self.assertEqual(result["evidence"]["evidence_eligibility"],
                         "AI_WORKER_CONFIRMED")
        self.assertEqual(result["evidence"]["coverage_state"], "VALID")
        self.assertEqual(result["evidence"]["worker_identity"], "worker-7")

    def test_duplicate_fetch_is_idempotent_and_does_not_write_evidence(self):
        self.write_control("IDEMPOTENT.md")
        document_id = self.row("IDEMPOTENT.md")["document_id"]
        first = D.read_required_document(document_id)
        second = D.read_required_document(document_id)
        self.assertEqual(first, second)
        self.assertFalse((self.repo / ".forseti" / "reading_coverage.jsonl").exists())

    def test_reading_outcomes_separate_availability(self):
        spec = D.spec_reading()
        self.assertTrue(spec["available"])
        self.assertEqual(spec["outcome"], "INCOMPLETE")
        self.assertEqual(spec["full"], 0)
        block = D.block_reading()
        self.assertTrue(block["available"])
        self.assertEqual(block["outcome"], "INCOMPLETE")
        self.assertEqual(block["done"], 0)

    def test_feature_outcome_does_not_turn_detector_liveness_into_completion(self):
        fake_items = [{"name": name, "alive": True, "live": "synthetic"}
                      for name, _key, _what, _spec in D.FEATURES]
        old_selftest, old_scale = D.selftest, D.scale_now
        try:
            D.selftest = lambda: {"items": fake_items}
            D.scale_now = lambda: {"tests": 0}
            feature = D.features()
        finally:
            D.selftest, D.scale_now = old_selftest, old_scale
        self.assertEqual(feature["detector_availability"]["available"],
                         feature["detector_availability"]["total"])
        self.assertEqual(feature["detector_availability"]["label"],
                         "detector availability")
        self.assertEqual(feature["outcome"], "INCOMPLETE")
        self.assertTrue(feature["available"])
        self.assertEqual(feature["test_count"], 0)
        self.assertEqual(feature["test_status"], "UNKNOWN")
        self.assertIn("scale_now.tests", feature["test_provenance"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
