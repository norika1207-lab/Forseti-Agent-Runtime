#!/usr/bin/env python3
"""F07-OUT-001 的 conformance tests。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F07-OUT-001  sha256 c721da66a062  §6 有五條 CT

這一份對應使用者 CLAUDE.md 裡那條最重的規則：絕對不准吐空白。
她付了 token 卻收到空白。§5 的解法是讓工作成果在合成之前就落地，
這樣就算最後那句話沒送出去，成果還在。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import ledger as L  # noqa: E402
import starvation as S  # noqa: E402


class F07Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)
        self.t = self.led.accept("任務", [
            L.Step("s1", "跑一個很貴的建置",
                   expected_outputs=["app.bin"], verifier=["file:app.bin"]),
        ])
        self.led.transition(self.t, "RUNNING", "開始")
        self.s1 = self.led.sid(self.t, "s1")
        self.led.dispatch(self.s1, "worker-a")

    def tearDown(self):
        self.led.close()


class TestF07(F07Case):

    def test_CT_F07_01_build_succeeds_final_blank_synthesize_without_rebuild(self):
        """建置成功但最終輸出空白 → 只重做合成，不重建。

        已經花掉的建置時間是真的成本，不該因為一句話沒說出來就再付一次。
        """
        (self.tmp / "app.bin").write_text("binary", encoding="utf-8")
        self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])

        d = self.led.diagnose_output(self.s1)

        self.assertEqual(d.failure_class, "OUTPUT_STARVATION")
        self.assertEqual(d.basis, S.OBSERVED)
        self.assertTrue(d.recoverable_without_rerun, "成果還在就不該重跑")

        plan = S.recovery_plan(d)
        self.assertIn("SYNTHESIS_ONLY", plan)
        self.assertIn("AVOID_RERUN", plan)
        self.assertLess(plan.index("SYNTHESIS_ONLY"), len(plan))

        # 成果真的還在，驗證照樣過，不需要重建
        ok, _ = self.led.verify_step(self.s1)
        self.assertTrue(ok)

    def test_CT_F07_02_repeated_blank_becomes_a_recurrent_incident(self):
        """連續空輸出 → 變成重複性事件。

        單次可能是意外，連續不是。重複本身就是證據。
        """
        self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])
        d = self.led.diagnose_output(self.s1, blank_run=3)
        self.assertEqual(d.failure_class, "BLANK_OUTPUT_SEQUENCE")
        self.assertEqual(d.recurrence, 3)
        self.assertIn("CLEAN_RESPONSE_WORKER", S.recovery_plan(d),
                      "一直合成失敗就該換一個乾淨的來講")

    def test_CT_F07_03_long_healthy_progress_is_LONG_VALID_TASK(self):
        """久但健康 → LONG_VALID_TASK，不是故障。

        這一類存在的目的就是不要誤判長工作。
        """
        self.led.worker_event("WORKER_PROGRESS", self.s1, "編到 60%", worker="w")
        self.led.mark_synthesized(self.s1, "digest-x")
        d = self.led.diagnose_output(self.s1, progress_healthy=True)
        self.assertEqual(d.failure_class, "LONG_VALID_TASK")
        self.assertTrue(d.is_healthy)
        self.assertEqual(S.recovery_plan(d), [], "健康的東西不需要恢復")

    def test_CT_F07_04_stale_watcher_is_marked_inferred_not_observed(self):
        """STALE_WATCHER 是推測，必須標成 INFERRED。

        規格沒有定義這個類別，我從 CT-F07-04「ESC reveals completion」
        推測它的意思。推測就要標成推測 —— 這正是 §3 要求分開
        OBSERVED 與 INFERRED 的理由。
        """
        self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])
        d = self.led.diagnose_output(self.s1, foreground_running=True)
        self.assertEqual(d.failure_class, "STALE_WATCHER")
        self.assertEqual(d.basis, S.INFERRED, "推測不得標成觀測")
        self.assertIn("推測", d.detail)

    def test_CT_F07_05_diagnosis_never_takes_the_models_word_for_it(self):
        """診斷只吃可觀測的事實，不吃模型的自述。

        §3：It cannot directly prove hidden reasoning was swallowed。
        所以 diagnose() 的參數裡沒有任何一個是「模型說它怎麼了」。
        """
        import inspect
        params = set(inspect.signature(S.diagnose).parameters)
        self.assertEqual(params, {
            "has_receipts", "has_final_output", "tool_calls",
            "progress_healthy", "blank_run", "foreground_running"})
        for p in params:
            self.assertNotIn("model", p)
            self.assertNotIn("claim", p)
            self.assertNotIn("said", p)

    def test_process_stall_has_nothing_to_preserve(self):
        """既沒有工具結果也沒有輸出 → 沒有東西可以保全，只能重跑。"""
        d = self.led.diagnose_output(self.s1)
        self.assertEqual(d.failure_class, "PROCESS_STALL")
        self.assertFalse(d.recoverable_without_rerun)
        self.assertNotIn("SYNTHESIS_ONLY", S.recovery_plan(d))


class TestResultReceipt(F07Case):

    def test_receipt_exists_before_synthesis(self):
        """收據必須早於合成。晚一步落地就等於沒有。"""
        r = self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])
        self.assertEqual(len(self.led.receipts_of(self.s1)), 1)
        self.assertFalse(r.synthesized)
        self.led.mark_synthesized(self.s1, r.digest)
        events = [e["kind"] for e in self.led.events_of(self.t)]
        self.assertLess(events.index("RESULT_RECEIPT"), events.index("SYNTHESIZED"))

    def test_identical_receipt_is_idempotent(self):
        """同樣的收據落兩次只留一份。重試不該讓帳本長出假的重複。"""
        self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])
        self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])
        self.assertEqual(len(self.led.receipts_of(self.s1)), 1)

    def test_different_outcome_makes_a_different_receipt(self):
        self.led.receipt(self.s1, "build", "exit 0")
        self.led.receipt(self.s1, "build", "exit 1")
        self.assertEqual(len(self.led.receipts_of(self.s1)), 2)

    def test_receipt_survives_session_boundary(self):
        """收據跨越 session 邊界。這正是它存在的理由。"""
        self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])
        self.led.close()
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)
        self.assertEqual(len(self.led.receipts_of(self.s1)), 1)


class TestDurableRecovery(F07Case):
    """F05/F07 的實際恢復路徑：觀測、保全、冪等重派。"""

    def test_long_active_work_is_not_interrupted(self):
        now = __import__("time").time()
        self.led.worker_event("WORKER_PROGRESS", self.s1, "仍在編譯", worker="worker-a")
        result = self.led.recover_stalled(
            self.s1, worker_running=True, activity_since=now - 1)
        self.assertEqual(result["action"], "HOLD_ACTIVE")
        self.assertEqual(
            self.led.con.execute(
                "SELECT COUNT(*) FROM events WHERE step_id=? AND kind='RECOVERY_DISPATCH'",
                (self.s1,)).fetchone()[0], 0)

    def test_blank_final_preserves_receipt_and_requests_synthesis_only(self):
        self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])
        result = self.led.recover_stalled(self.s1, blank_run=1)
        self.assertEqual(result["action"], "SYNTHESIS_ONLY")
        self.assertEqual(len(self.led.receipts_of(self.s1)), 1)
        self.assertEqual(
            self.led.con.execute(
                "SELECT COUNT(*) FROM events WHERE step_id=? AND kind='RECOVERY_DISPATCH'",
                (self.s1,)).fetchone()[0], 0)

    def test_running_worker_with_old_receipt_is_never_interrupted(self):
        """A receipt is not proof that the worker has stopped writing."""
        self.led.receipt(self.s1, "build", "exit 0", artifacts=["app.bin"])
        result = self.led.recover_stalled(
            self.s1, worker="worker-a", worker_running=True, blank_run=1)
        self.assertEqual(result["action"], "HOLD_RUNNING")
        kinds = [e["kind"] for e in self.led.events_of(self.t)]
        self.assertNotIn("RESULT_SYNTHESIS_REQUESTED", kinds)
        self.assertNotIn("RECOVERY_DISPATCH", kinds)

    def test_repeated_starvation_has_one_idempotent_redispatch(self):
        a = self.led.recover_stalled(self.s1, worker="worker-a", blank_run=2)
        b = self.led.recover_stalled(self.s1, worker="worker-a", blank_run=2)
        self.assertEqual(a["action"], "REDISPATCH")
        self.assertEqual(b["action"], "REDISPATCH")
        self.assertTrue(a["fresh"])
        self.assertFalse(b["fresh"])
        self.assertEqual(
            self.led.con.execute(
                "SELECT COUNT(*) FROM events WHERE step_id=? AND kind='RECOVERY_DISPATCH'",
                (self.s1,)).fetchone()[0], 1)
        self.assertEqual(
            self.led.con.execute(
                "SELECT COUNT(*) FROM events WHERE step_id=? AND kind='DISPATCH'",
                (self.s1,)).fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
