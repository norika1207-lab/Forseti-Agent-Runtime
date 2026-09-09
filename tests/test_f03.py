#!/usr/bin/env python3
"""F03-CSI-001 的 conformance tests。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F03-CSI-001  sha256 792cd95009f0  §7 有五條 CT

測試名用規格的 CT 編號。用臨時 db 與臨時 log store，不碰真實帳本。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import ledger as L  # noqa: E402
import worker as W  # noqa: E402


class F03Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)
        self.t = self.led.accept("任務", [
            L.Step("s1", "第一步",
                   expected_outputs=["out.txt"],
                   verifier=["file:out.txt"]),
            L.Step("s2", "第二步", dependencies=["s1"]),
        ])
        self.led.transition(self.t, "RUNNING", "開始")
        self.s1 = self.led.sid(self.t, "s1")
        # F04 §2 的流程是 DISPATCH 先於 COMPLETION,所以每個案例都從派工開始
        self.led.dispatch(self.s1, "worker-a")

    def tearDown(self):
        self.led.close()

    def packet(self, **kw) -> W.WorkerResult:
        base = dict(task_id=self.t, step_id=self.s1, status="COMPLETED",
                    summary="做完第一步", artifacts=["out.txt"],
                    evidence_refs=["out.txt 存在"])
        base.update(kw)
        return W.WorkerResult(**base)


class TestF03(F03Case):

    def test_CT_F03_01_huge_log_becomes_compact_packet_plus_reference(self):
        """100KB 的 log，Main 收到的是精簡 packet 加一個引用。

        這一條是整個隔離層的重點。log 不是被摘要,是被落檔;
        Main 拿到路徑,要不要讀是它的選擇。摘要會失真,路徑不會。
        """
        huge = "compiler warning line\n" * 5000
        self.assertGreater(len(huge), 100_000)

        ref = self.led.stash(self.s1, huge, label="build")
        p = self.packet(summary="編譯過了，2 個警告", raw_log_refs=[ref])

        self.assertLess(p.size, 2_000, "進 Main 的 packet 要遠小於原始輸出")
        self.assertLess(p.size, len(huge) / 50)

        path = Path(ref.split("#")[0])
        self.assertTrue(path.is_file(), "原始輸出要真的落在檔案裡")
        self.assertEqual(path.read_text(encoding="utf-8"), huge, "落檔不得失真")

        r = self.led.submit_result(p)
        self.assertTrue(r.accepted)
        self.assertIn("原始輸出", r.brief())

    def test_CT_F03_02_worker_completion_reaches_controller_as_event(self):
        """worker 完成 → controller 收到事件。

        F03 §6 要防的其中一件事是 worker finishing without event:
        做完了但沒有人知道。所以完成必須留下事件,而不是只有一句話。
        """
        self.led.submit_result(self.packet())
        kinds = [e["kind"] for e in self.led.events_of(self.t)]
        self.assertIn("DISPATCH", kinds)
        self.assertIn("WORKER_RESULT", kinds)

    def test_CT_F03_02b_completed_claim_only_reaches_VERIFYING(self):
        """worker 說完成，只到 VERIFYING，不是 VERIFIED_COMPLETE。

        F02 §3：模型說 done 而要求未滿足時,任務維持非終止。
        這條是最容易被抄近路的地方,所以單獨測。
        """
        self.led.submit_result(self.packet())
        st = self.led.steps_of(self.t)[0]
        self.assertEqual(st["state"], "VERIFYING")
        self.assertNotEqual(st["state"], "VERIFIED_COMPLETE")

        # 要真的有產物才過得了
        ok, _ = self.led.verify_step(self.s1)
        self.assertFalse(ok, "檔案還不存在，不該通過")
        (self.tmp / "out.txt").write_text("real", encoding="utf-8")
        self.led.step_transition(self.s1, "RUNNING", "重試")
        ok, _ = self.led.verify_step(self.s1)
        self.assertTrue(ok)
        self.assertEqual(self.led.steps_of(self.t)[0]["state"], "VERIFIED_COMPLETE")

    def test_CT_F03_03_worker_drift_is_bounded_by_taskstep(self):
        """worker 偏離被 TaskStep 界定。

        偏離不會公告。worker 會安靜地多做幾件事一起交回來,而那些
        多出來的東西看起來都很合理。判準是結構的:產物在不在
        expected_outputs 裡。
        """
        p = self.packet(artifacts=["out.txt", "順手改的 config.yaml", "新開的 extra.py"])
        r = self.led.submit_result(p)
        self.assertFalse(r.accepted, "交回範圍外的產物要被擋下來")
        self.assertEqual(len(p.out_of_scope), 2)
        self.assertIn("config.yaml", " ".join(p.out_of_scope))

        st = self.led.steps_of(self.t)[0]
        self.assertNotEqual(st["state"], "VERIFYING", "被拒收的 packet 不得推進狀態")

    def test_result_from_undispatched_step_is_refused(self):
        """沒被派工的步驟交回結果，明確拒收。

        F04 §2 的順序是 DISPATCH 先於 COMPLETION。收到一個沒派工的結果
        代表流程有洞，那要看得見，不是靜靜地接受。
        """
        s2 = self.led.sid(self.t, "s2")
        p = W.WorkerResult(task_id=self.t, step_id=s2, status="COMPLETED",
                           summary="做完了", evidence_refs=["有"])
        r = self.led.submit_result(p)
        self.assertFalse(r.accepted)
        self.assertTrue(any("還沒有被派工" in v for v in r.violations))

    def test_CT_F03_03b_no_expected_outputs_means_no_scope_check(self):
        """TaskStep 沒定義 expected_outputs 時，不算 worker 超出範圍。

        沒有範圍就談不上超出範圍。那是 TaskStep 沒定義好，不是 worker
        的錯，兩者不可以混為一談 —— 混了就會開始責怪 worker 做對的事。
        """
        s2 = self.led.sid(self.t, "s2")
        p = W.WorkerResult(task_id=self.t, step_id=s2, status="COMPLETED",
                           summary="做完", artifacts=["anything.txt"],
                           evidence_refs=["有東西"])
        self.assertEqual(W.check_scope(p, []), [])

    def test_CT_F03_04_worker_dies_task_persists_and_reassigns(self):
        """worker 死掉，任務保留並可重派。

        F03 §5：Forseti 不消滅 worker,它消滅的是 worker 必須擁有
        連續性這件事。所以換人不影響任務,也不算進度。
        """
        before = self.led.steps_of(self.t)[0]["state"]

        self.led.reassign(self.s1, "worker-b", "worker-a 連續三次無回應")

        after = self.led.steps_of(self.t)
        self.assertEqual(after[0]["state"], before, "換人不是進度，狀態不該變")
        self.assertEqual(after[0]["assigned_worker"], "worker-b")
        self.assertEqual(self.led.state_of(self.t), "RUNNING", "任務要活著")
        self.assertIn("REASSIGN", [e["kind"] for e in self.led.events_of(self.t)])

    def test_CT_F03_05_main_model_switch_does_not_disturb_worker(self):
        """Main 換模型，worker 照常。帳本不知道也不在乎誰是 Main。"""
        snapshot = self.led.steps_of(self.t)

        self.led.close()  # Main 換人 = 這一端的物件全部丟掉
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)

        self.assertEqual(self.led.steps_of(self.t), snapshot)
        self.assertEqual(self.led.steps_of(self.t)[0]["assigned_worker"], "worker-a")


class TestPollutionBudget(F03Case):
    """F03 §3 的 context isolation rule。擋法是硬性的，不是請 worker 自律。"""

    def test_oversized_summary_is_rejected_not_truncated(self):
        """summary 超長要被拒收，不是截斷。

        一個被截斷但看起來正常的 packet 比一個被拒絕的 packet 危險,
        因為前者會讓 Main 以為自己看到了全部。
        """
        p = self.packet(summary="細節" * 2000)
        self.assertGreater(len(p.summary), W.SUMMARY_LIMIT)
        r = self.led.submit_result(p)
        self.assertFalse(r.accepted)
        self.assertTrue(any("超過上限" in v for v in r.violations))
        self.assertEqual(len(p.summary), 4000, "packet 不該被偷偷截斷")

    def test_completed_without_evidence_is_rejected(self):
        """宣稱 COMPLETED 但沒有任何證據，拒收。完成是需要證據的宣稱。"""
        p = self.packet(evidence_refs=[], tests=[])
        r = self.led.submit_result(p)
        self.assertFalse(r.accepted)
        self.assertTrue(any("evidence" in v for v in r.violations))

    def test_blocked_without_reason_is_rejected(self):
        p = self.packet(status="BLOCKED", blockers=[])
        r = self.led.submit_result(p)
        self.assertFalse(r.accepted)
        self.assertTrue(any("被什麼擋住" in v for v in r.violations))

    def test_blocked_with_reason_moves_step_to_blocked(self):
        p = self.packet(status="BLOCKED", blockers=["缺少上游 API 金鑰"])
        r = self.led.submit_result(p)
        self.assertTrue(r.accepted)
        self.assertEqual(self.led.steps_of(self.t)[0]["state"], "BLOCKED")

    def test_unknowns_survive_into_the_brief(self):
        """unresolved_unknowns 要出現在給 Main 的一句話裡。

        這一欄是 Main 唯一無法自己驗證的東西:worker 說做完了,Main 可以
        去看磁碟;worker 說它不知道什麼,Main 只能靠它講。所以它不能被
        摘要吃掉。
        """
        p = self.packet(unresolved_unknowns=["不確定這個 API 在舊版是否存在"])
        r = self.led.submit_result(p)
        self.assertTrue(r.accepted)
        self.assertIn("未知", r.brief())

    def test_status_must_be_a_known_value(self):
        p = self.packet(status="差不多好了")
        r = self.led.submit_result(p)
        self.assertFalse(r.accepted)
        self.assertTrue(any("status" in v for v in r.violations))


class TestStash(F03Case):
    def test_same_content_stashes_once(self):
        """同樣內容不重複落檔，用 hash 去重。"""
        a = self.led.stash(self.s1, "一樣的內容", label="x")
        b = self.led.stash(self.s1, "一樣的內容", label="x")
        self.assertEqual(a, b)

    def test_reference_carries_size(self):
        ref = self.led.stash(self.s1, "12345", label="x")
        self.assertTrue(ref.endswith("#5chars"), ref)


if __name__ == "__main__":
    unittest.main(verbosity=2)
