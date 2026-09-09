#!/usr/bin/env python3
"""F01-PEC-001 與 F02-TSM-001 的 conformance tests。

測試名稱直接用規格的 CT 編號，這樣哪一條規格沒過一眼看得到，
而不是「有 27 條測試通過」這種對不上任何要求的數字。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F01-PEC-001  sha256 fe86cb2a1ab7  §7 有五條 CT
    F02-TSM-001  sha256 99ec01294dde  §7 有五條 CT

用臨時 db，不碰 repo 的 .forseti/ledger.db。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import ledger as L  # noqa: E402


def _steps(n: int, with_verifier: bool = False, chain: bool = True) -> list[L.Step]:
    """n 個步驟。chain=True 時每一步依賴前一步。"""
    out = []
    for i in range(1, n + 1):
        out.append(L.Step(
            step_id=f"s{i}",
            objective=f"第 {i} 步",
            verifier=[f"file:out{i}.txt"] if with_verifier else [],
            dependencies=[f"s{i-1}"] if (chain and i > 1) else [],
        ))
    return out


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)

    def tearDown(self):
        self.led.close()

    def sid(self, task_id: str, local: str) -> str:
        return L.qualify(task_id, local)

    def reopen(self) -> L.Ledger:
        """關掉再開，模擬 session 換人：記憶沒了，帳本還在。"""
        self.led.close()
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)
        return self.led


# ---------------------------------------------------------------------------
# F01 — Persistent Execution Contract
# ---------------------------------------------------------------------------

class TestF01(LedgerCase):

    def test_CT_F01_01_report_after_step2_keeps_running_and_schedules_step3(self):
        """五步任務在第二步後回報；任務維持 RUNNING，第三步自動排上。"""
        t = self.led.accept("五步任務", _steps(5))
        self.led.transition(t, "RUNNING", "開始執行")
        for local in ("s1", "s2"):
            sid = self.sid(t, local)
            self.led.step_transition(sid, "RUNNING", "開工")
            self.led.step_transition(sid, "VERIFYING", "做完了")
            self.led.step_transition(sid, "VERIFIED_COMPLETE", "驗過")

        self.led.report(t, "做完前兩步，摘要如下……")

        self.assertEqual(self.led.state_of(t), "RUNNING", "回報不該讓任務離開 RUNNING")
        nxt = self.led.next_step(t)
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt["local_id"], "s3", "第三步應該自動成為下一個可動的步驟")

    def test_CT_F01_02_not_finished_must_continue_or_be_blocked_with_reason(self):
        """說「還沒做完」之後，必須繼續、或進 BLOCKED/NEEDS_HUMAN 並附理由。

        帳本這一端的保證是：說沒做完不會讓任務終止，而且要進 BLOCKED
        一定得帶 cause，帶不出來就轉不了。
        """
        t = self.led.accept("任務", _steps(3))
        self.led.transition(t, "RUNNING", "開始")
        self.led.report(t, "還沒做完")

        self.assertFalse(L.is_terminal(self.led.state_of(t)))
        self.assertIsNotNone(self.led.next_step(t), "還沒做完就要有下一步")

        with self.assertRaises(L.TransitionError):
            self.led.transition(t, "BLOCKED", "")  # 沒有理由不准擋
        self.led.transition(t, "BLOCKED", "等外部 API 金鑰")
        self.assertEqual(self.led.state_of(t), "BLOCKED")

    def test_CT_F01_03_successor_resumes_from_task_truth(self):
        """第三步之後 session 結束；接手者從帳本接第四步，不靠任何記憶。"""
        t = self.led.accept("五步任務", _steps(5))
        self.led.transition(t, "RUNNING", "開始")
        for local in ("s1", "s2", "s3"):
            sid = self.sid(t, local)
            self.led.step_transition(sid, "RUNNING", "開工")
            self.led.step_transition(sid, "VERIFYING", "做完")
            self.led.step_transition(sid, "VERIFIED_COMPLETE", "驗過")

        led2 = self.reopen()  # 全新的 Ledger 物件，等於全新的 session
        self.assertEqual(led2.state_of(t), "RUNNING")
        self.assertEqual(led2.next_step(t)["local_id"], "s4")

    def test_CT_F01_04_cancel_stops_dispatch(self):
        """使用者取消後不再派工。"""
        t = self.led.accept("任務", _steps(4))
        self.led.transition(t, "RUNNING", "開始")
        self.led.transition(t, "CANCELLED_BY_OWNER", "owner 說停",
                            actor="owner", terminal_reason="owner 說停")
        self.assertIsNone(self.led.next_step(t), "取消後不該再有下一步")
        with self.assertRaises(L.TransitionError):
            self.led.transition(t, "RUNNING", "想偷偷繼續")

    def test_CT_F01_05_progress_report_is_not_completion(self):
        """進度報告不算完成。

        這一條是 2026-09-09 那 8 次「繼續」的直接修正：
        report() 刻意沒有任何可以順手改狀態的參數。
        """
        t = self.led.accept("任務", _steps(2))
        self.led.transition(t, "RUNNING", "開始")
        before = self.led.state_of(t)
        after = self.led.report(t, "全部做完了，總結如下：一二三四五")
        self.assertEqual(before, after)
        self.assertEqual(after, "RUNNING")
        self.assertFalse(L.is_terminal(after))
        kinds = [e["kind"] for e in self.led.events_of(t)]
        self.assertIn("PROGRESS_REPORT", kinds)
        self.assertNotIn("VERIFIED_COMPLETE", [e["to"] for e in self.led.events_of(t)])


# ---------------------------------------------------------------------------
# F02 — Task State Machine & External Task Truth
# ---------------------------------------------------------------------------

class TestF02(LedgerCase):

    def test_CT_F02_01_done_without_receipt_stays_non_terminal(self):
        """宣稱 done 但缺收據，維持非終止。

        verifier 是真的去看檔案，不是誰說了算。這一條如果讓 verifier
        可以由人宣告通過，整條測試就是假的。
        """
        t = self.led.accept("任務", _steps(1, with_verifier=True))
        self.led.transition(t, "RUNNING", "開始")
        self.led.step_transition(self.sid(t, "s1"), "RUNNING", "開工")

        ok, results = self.led.verify_step(self.sid(t, "s1"))
        self.assertFalse(ok)
        self.assertEqual(self.led.steps_of(t)[0]["state"], "RUNNING")
        self.assertIn("不存在", results[0].detail)

        (self.tmp / "out1.txt").write_text("real output", encoding="utf-8")
        ok, _ = self.led.verify_step(self.sid(t, "s1"))
        self.assertTrue(ok)
        self.assertEqual(self.led.steps_of(t)[0]["state"], "VERIFIED_COMPLETE")

    def test_CT_F02_01b_empty_file_is_not_evidence(self):
        """空檔案不算證據。產物存在但是空的，是最常見的假完成。"""
        t = self.led.accept("任務", _steps(1, with_verifier=True))
        self.led.transition(t, "RUNNING", "開始")
        self.led.step_transition(self.sid(t, "s1"), "RUNNING", "開工")
        (self.tmp / "out1.txt").write_text("", encoding="utf-8")
        ok, results = self.led.verify_step(self.sid(t, "s1"))
        self.assertFalse(ok)
        self.assertIn("空檔案", results[0].detail)

    def test_verify_before_start_is_a_clear_failure_not_an_exception(self):
        """驗證一個還沒開工的步驟，要得到明確的不通過，不是例外。"""
        t = self.led.accept("任務", _steps(1, with_verifier=True))
        self.led.transition(t, "RUNNING", "開始")
        ok, results = self.led.verify_step(self.sid(t, "s1"))
        self.assertFalse(ok)
        self.assertIn("還沒開工", results[0].detail)

    def test_CT_F02_02_fourteen_unfinished_exposed_without_interrogation(self):
        """十四個未完成項目要被自動暴露，不需要使用者盤問。

        對應使用者 2026-09-08 那個八小時事故：她必須自己開口問
        「還有多少東西要做」才拿得到答案。
        """
        t = self.led.accept("大任務", _steps(14, chain=False))
        self.led.transition(t, "RUNNING", "開始")
        o = self.led.obligations()
        self.assertEqual(len(o["unfinished_steps"]), 14)
        self.assertEqual(len(o["unfinished_tasks"]), 1)
        self.assertEqual(self.led.total_unfinished(), 15)

    def test_CT_F02_03_compression_does_not_change_state(self):
        """壓縮讓模型忘記，帳本狀態不變。

        壓縮在這裡模擬成：丟掉所有 in-memory 物件，重新從 db 讀。
        那正是壓縮對模型做的事。
        """
        t = self.led.accept("任務", _steps(3))
        self.led.transition(t, "RUNNING", "開始")
        self.led.step_transition(self.sid(t, "s1"), "RUNNING", "開工")
        snapshot = (self.led.state_of(t), [s["state"] for s in self.led.steps_of(t)])

        led2 = self.reopen()
        self.assertEqual((led2.state_of(t), [s["state"] for s in led2.steps_of(t)]), snapshot)

    def test_CT_F02_04_model_switch_does_not_change_state(self):
        """換模型，狀態不變。帳本不知道也不在乎誰在跑。"""
        t = self.led.accept("任務", _steps(2))
        self.led.transition(t, "RUNNING", "opus 開始")
        led2 = self.reopen()
        led2.report(t, "換成另一個模型接手")
        self.assertEqual(led2.state_of(t), "RUNNING")
        self.assertEqual(led2.next_step(t)["local_id"], "s1")

    def test_CT_F02_05_restart_is_deterministic(self):
        """重啟後確定性重載：所有欄位與順序一致。"""
        t = self.led.accept("任務", _steps(5), definition_of_done=["全部驗過"])
        self.led.transition(t, "RUNNING", "開始")
        self.led.step_transition(self.sid(t, "s1"), "RUNNING", "開工")
        first = self.led.steps_of(t)
        led2 = self.reopen()
        self.assertEqual(led2.steps_of(t), first)
        self.assertEqual([s["seq"] for s in led2.steps_of(t)], [0, 1, 2, 3, 4])


# ---------------------------------------------------------------------------
# 狀態機本身
# ---------------------------------------------------------------------------

class TestStateMachine(LedgerCase):

    def test_only_four_terminal_states(self):
        """F01 §3：只有四個終止狀態。REPORTING 不在其中。"""
        self.assertEqual(set(L.TERMINAL), {
            "VERIFIED_COMPLETE", "CANCELLED_BY_OWNER", "FAILED_TERMINAL", "SUPERSEDED"})
        for s in ("RUNNING", "BLOCKED", "NEEDS_HUMAN", "WAITING_DEPENDENCY", "VERIFYING"):
            self.assertFalse(L.is_terminal(s), f"{s} 不該是終止狀態")

    def test_every_transition_needs_a_cause(self):
        """F02 §5：每一次轉換都必須有事件因。"""
        t = self.led.accept("任務", _steps(1))
        for bad in ("", "   "):
            with self.assertRaises(L.TransitionError):
                self.led.transition(t, "RUNNING", bad)

    def test_terminal_states_are_dead_ends(self):
        for terminal, cause in (("VERIFIED_COMPLETE", None), ("FAILED_TERMINAL", "壞了")):
            t = self.led.accept("任務", _steps(1))
            self.led.transition(t, "RUNNING", "開始")
            if terminal == "VERIFIED_COMPLETE":
                self.led.transition(t, "VERIFYING", "驗證中")
            self.led.transition(t, terminal, cause or "驗過")
            with self.assertRaises(L.TransitionError):
                self.led.transition(t, "RUNNING", "想復活")

    def test_task_without_steps_is_refused(self):
        """沒有步驟的任務無法追蹤未完成項，所以不准接受。"""
        with self.assertRaises(ValueError):
            self.led.accept("空任務", [])

    def test_step_without_verifier_cannot_self_declare_complete(self):
        """沒有 verifier 的步驟不准自己宣稱完成。

        「沒有驗證方式」跟「驗證過了」在帳本裡必須看得出差別。
        """
        t = self.led.accept("任務", _steps(1, with_verifier=False))
        self.led.transition(t, "RUNNING", "開始")
        ok, results = self.led.verify_step(self.sid(t, "s1"))
        self.assertFalse(ok)
        self.assertEqual(results, [])
        self.assertNotEqual(self.led.steps_of(t)[0]["state"], "VERIFIED_COMPLETE")

    def test_manual_verifier_form_is_rejected(self):
        """由人或模型宣告通過的 verifier 形式不被接受。那就是 claim。"""
        r = L.run_verifier("manual:我確認過了")
        self.assertFalse(r.ok)
        self.assertIn("不認得", r.detail)

    def test_cmd_verifier_actually_runs(self):
        self.assertTrue(L.run_verifier("cmd:true").ok)
        self.assertFalse(L.run_verifier("cmd:false").ok)


if __name__ == "__main__":
    unittest.main(verbosity=2)
