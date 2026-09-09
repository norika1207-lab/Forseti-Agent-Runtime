#!/usr/bin/env python3
"""F04-EVT-001 的 conformance tests。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F04-EVT-001  sha256 91dfb59b5dfa  §7 有五條 CT

F04 §1 的目標寫得最白：Replace "wake up and ask what happened" with
event-driven execution continuity。也就是不要有人在旁邊每一輪問一次
「好了沒」。2026-09-09 這一場的 HumanContinueBurden 是 9，這組測試
就是要讓那個數字降下來。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import ledger as L  # noqa: E402
import worker as W  # noqa: E402


class F04Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)

    def tearDown(self):
        self.led.close()

    def make(self, n=3, human_at=None):
        """n 步的任務，每步的 verifier 是「檔案存在」。human_at 指定哪一步需要人決定。"""
        steps = []
        for i in range(1, n + 1):
            steps.append(L.Step(
                f"s{i}", f"第 {i} 步",
                expected_outputs=[f"out{i}.txt"],
                verifier=[f"file:out{i}.txt"],
                dependencies=[f"s{i-1}"] if i > 1 else [],
                requires_human=(human_at == i),
            ))
        t = self.led.accept("任務", steps)
        self.led.transition(t, "RUNNING", "開始")
        return t

    def produce(self, n):
        """把第 n 步的產物寫出來，模擬 worker 真的做了事。"""
        (self.tmp / f"out{n}.txt").write_text(f"output {n}", encoding="utf-8")


class TestF04(F04Case):

    def test_CT_F04_01_completion_then_verify_then_automatic_next_step(self):
        """完成 → 驗證 → 自動派下一步。中間沒有人說任何話。"""
        t = self.make(3)

        first = self.led.auto_dispatch(t, "worker-a")
        self.assertEqual(first["local_id"], "s1")

        self.produce(1)
        ok, _ = self.led.verify_step(self.led.sid(t, "s1"))
        self.assertTrue(ok)

        second = self.led.auto_dispatch(t, "worker-a")
        self.assertEqual(second["local_id"], "s2", "驗證過就該自己往下走")
        self.assertEqual(self.led.steps_of(t)[1]["state"], "RUNNING")

    def test_CT_F04_02_duplicate_completion_does_not_dispatch_twice(self):
        """重複的完成事件不得派工兩次。

        冪等靠資料庫的 unique index，不靠呼叫端記得檢查。
        呼叫端會忘記，索引不會。
        """
        t = self.make(2)
        s1 = self.led.sid(t, "s1")
        self.led.dispatch(s1, "worker-a")

        key = "evt-completion-001"
        first = self.led.worker_event("WORKER_COMPLETION", s1, "做完了",
                                      worker="worker-a", idem_key=key)
        again = self.led.worker_event("WORKER_COMPLETION", s1, "做完了",
                                      worker="worker-a", idem_key=key)
        self.assertTrue(first)
        self.assertFalse(again, "同一個 idem_key 的第二次要被擋下來")

        n = sum(1 for e in self.led.events_of(t) if e["kind"] == "WORKER_COMPLETION")
        self.assertEqual(n, 1, "帳本裡只該有一筆")

    def test_CT_F04_03_authorized_task_continues_while_user_is_away(self):
        """使用者離線八小時，已授權的任務照樣跑完。

        這條的本質不是時間，是「不需要人再出現」。所以測法是：
        建好任務之後，除了 worker 產出檔案，不做任何 human 動作，
        看它能不能自己走到底。
        """
        t = self.make(4)
        for i in range(1, 5):
            self.produce(i)

        done = self.led.drain(t, "worker-a")

        self.assertEqual([d["local_id"] for d in done], ["s1", "s2", "s3", "s4"])
        self.assertTrue(all(s["state"] == "VERIFIED_COMPLETE" for s in self.led.steps_of(t)))
        self.assertEqual(self.led.total_unfinished(), 1, "只剩任務本身待收尾")

    def test_CT_F04_04_progress_report_does_not_stop_execution(self):
        """進度報告之後，執行照樣繼續。報告是觀察通道不是流程關卡。"""
        t = self.make(3)
        self.led.auto_dispatch(t, "worker-a")
        self.produce(1)
        self.led.verify_step(self.led.sid(t, "s1"))

        self.led.report(t, "第一步做完了，以下是詳細說明……")

        nxt = self.led.auto_dispatch(t, "worker-a")
        self.assertIsNotNone(nxt, "報告完不該停下來")
        self.assertEqual(nxt["local_id"], "s2")

    def test_CT_F04_05_owner_decision_required_goes_to_needs_human(self):
        """需要 owner 決定的步驟，任務轉 NEEDS_HUMAN，不是安靜地停住。

        安靜的 None 跟「在等人」在呼叫端看起來一樣，但意思完全不同。
        一個是沒事做，一個是有人欠一個決定。
        """
        t = self.make(3, human_at=2)
        self.led.auto_dispatch(t, "worker-a")
        self.produce(1)
        self.led.verify_step(self.led.sid(t, "s1"))

        nxt = self.led.auto_dispatch(t, "worker-a")
        self.assertIsNone(nxt)
        self.assertEqual(self.led.state_of(t), "NEEDS_HUMAN")

        o = self.led.obligations()
        self.assertTrue(any(b["task_id"] == t for b in o["blocked"]),
                        "在等人的任務要出現在義務帳本裡")

    def test_CT_F04_05b_after_human_decides_execution_resumes(self):
        """人決定完之後，繼續自己走。"""
        t = self.make(3, human_at=2)
        self.led.auto_dispatch(t, "worker-a")
        self.produce(1)
        self.led.verify_step(self.led.sid(t, "s1"))
        self.led.auto_dispatch(t, "worker-a")
        self.assertEqual(self.led.state_of(t), "NEEDS_HUMAN")

        # owner 拍板：這一步不用人了
        self.led.con.execute("UPDATE steps SET requires_human=0 WHERE step_id=?",
                             (self.led.sid(t, "s2"),))
        self.led.con.commit()

        nxt = self.led.auto_dispatch(t, "worker-a", "owner 已決定")
        self.assertIsNotNone(nxt)
        self.assertEqual(nxt["local_id"], "s2")
        self.assertEqual(self.led.state_of(t), "RUNNING")


class TestEventContract(F04Case):
    """F04 §3 的事件協定。"""

    def test_only_the_eight_worker_events_are_accepted(self):
        """不在 F04 §3 清單裡的事件種類一律拒絕。

        事件種類可以隨便取名等於沒有協定，下游沒辦法對著一組不固定的
        名字寫邏輯。
        """
        t = self.make(1)
        s1 = self.led.sid(t, "s1")
        for kind in L.WORKER_EVENTS:
            self.assertTrue(self.led.worker_event(kind, s1, "測試", worker="w"))
        with self.assertRaises(ValueError):
            self.led.worker_event("差不多完成了", s1, "測試", worker="w")

    def test_progress_event_updates_last_progress_time(self):
        """WORKER_PROGRESS 要留下時間戳，F05 的停滯偵測靠它。"""
        t = self.make(1)
        s1 = self.led.sid(t, "s1")
        self.led.dispatch(s1, "worker-a")
        before = self.led.con.execute(
            "SELECT last_progress_at FROM steps WHERE step_id=?", (s1,)).fetchone()[0]
        self.led.worker_event("WORKER_PROGRESS", s1, "編譯到 40%", worker="worker-a")
        after = self.led.con.execute(
            "SELECT last_progress_at FROM steps WHERE step_id=?", (s1,)).fetchone()[0]
        self.assertGreaterEqual(after, before)

    def test_events_without_idem_key_are_not_deduplicated(self):
        """沒給 idem_key 的事件不去重。

        去重是呼叫端明確要求的行為，不是預設。預設去重會把兩次真實的
        進度回報吃掉一次。
        """
        t = self.make(1)
        s1 = self.led.sid(t, "s1")
        self.led.worker_event("WORKER_PROGRESS", s1, "10%", worker="w")
        self.led.worker_event("WORKER_PROGRESS", s1, "20%", worker="w")
        n = sum(1 for e in self.led.events_of(t) if e["kind"] == "WORKER_PROGRESS")
        self.assertEqual(n, 2)


class TestDrainSafety(F04Case):
    def test_drain_stops_when_verification_fails(self):
        """驗證沒過就停下來，不會硬著頭皮往下派。"""
        t = self.make(3)
        self.produce(1)  # 只產出第一步的東西
        done = self.led.drain(t, "worker-a")
        self.assertEqual([d["local_id"] for d in done], ["s1", "s2"])
        self.assertEqual(self.led.steps_of(t)[1]["state"], "RUNNING",
                         "第二步驗不過，留在 RUNNING 等重做")

    def test_drain_stops_on_terminal_task(self):
        t = self.make(2)
        self.led.transition(t, "CANCELLED_BY_OWNER", "owner 說停", actor="owner")
        self.assertEqual(self.led.drain(t, "worker-a"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
