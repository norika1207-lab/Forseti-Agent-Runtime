#!/usr/bin/env python3
"""F05-WDG-001 的 conformance tests。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F05-WDG-001  sha256 17ca3a6ee9c4  §7 有五條 CT

一件事要先講：§3 的 STALL_RISK 公式沒有定義任何因子的值域與量法，
我在 REQUIRED_READING 記成「沒看懂」。下面測的是我的詮釋
（watchdog.py 檔頭寫明），不是規格原意。門檻數字沒有實測校準。
"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import ledger as L  # noqa: E402
import watchdog as WD  # noqa: E402


class F05Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.led = L.Ledger(db=self.tmp / "t.db", cwd=self.tmp)
        self.t = self.led.accept("任務", [
            L.Step("s1", "長時間的建置",
                   expected_outputs=["build.log"], verifier=["file:build.log"]),
        ])
        self.led.transition(self.t, "RUNNING", "開始")
        self.s1 = self.led.sid(self.t, "s1")
        self.led.dispatch(self.s1, "worker-a")

    def tearDown(self):
        self.led.close()

    def age_step(self, seconds: float):
        """把步驟的時間戳往前推，模擬它已經跑了很久。"""
        past = time.time() - seconds
        self.led.con.execute(
            "UPDATE steps SET started_at=?, last_progress_at=? WHERE step_id=?",
            (past, past, self.s1))
        self.led.con.commit()


class TestF05(F05Case):

    def test_CT_F05_01_long_build_with_growing_logs_is_not_stalled(self):
        """長時間的建置，但 log 一直在長 → 不算停滯。

        這是最重要的一條。把「久」當成「卡住」會讓所有長工作都被誤判，
        而長工作正是最不該被打斷的那種。
        """
        (self.tmp / "build.log").write_text("start\n", encoding="utf-8")
        self.led.check_liveness(self.s1)          # 第一次取樣
        self.age_step(7200)                        # 已經跑了兩小時
        (self.tmp / "build.log").write_text("start\ncompiling...\n", encoding="utf-8")

        a = self.led.check_liveness(self.s1)
        self.assertFalse(a.suspect, f"log 在長就不該判停滯：{a.why}")
        self.assertEqual(a.verdict, "ALIVE")
        self.assertEqual(a.factors["no_progress_growth"], 0.0)

    def test_CT_F05_02_long_worker_with_no_changes_is_suspect(self):
        """跑很久而且什麼都沒變 → STALL_SUSPECT。"""
        (self.tmp / "build.log").write_text("start\n", encoding="utf-8")
        self.led.check_liveness(self.s1)
        self.age_step(7200)

        a = self.led.check_liveness(self.s1)      # 檔案沒動
        self.assertTrue(a.suspect, f"{a.risk} {a.why}")
        self.assertEqual(a.verdict, "STALL_SUSPECT")
        self.assertIn("STALL_SUSPECT", [e["kind"] for e in self.led.events_of(self.t)])

    def test_CT_F05_03_ping_with_progress_proof_clears_suspicion(self):
        """ping 之後拿得出進度證據 → 解除懷疑。

        注意「證據」的定義：worker 說它在做事不算，產物變了才算。
        WORKER_PROGRESS 事件只證明它還會說話。
        """
        (self.tmp / "build.log").write_text("start\n", encoding="utf-8")
        self.led.check_liveness(self.s1)
        self.age_step(7200)
        self.assertTrue(self.led.check_liveness(self.s1).suspect)

        self.led.worker_event("WORKER_PROGRESS", self.s1, "還在跑，第 3 個模組",
                              worker="worker-a")
        a = self.led.check_liveness(self.s1)
        self.assertFalse(a.suspect, "有事件回應就不該還是 SUSPECT")
        self.assertEqual(a.factors["no_event_activity"], 0.0)

    def test_CT_F05_04_repeated_unresponsive_leads_to_reassign(self):
        """連續無回應 → 重派，不是先去叫人。"""
        rung = None
        for i in range(1, 4):
            rung = self.led.recover(self.s1, unresponsive_count=i, current_rung=rung)
        self.assertEqual(rung, "RESTART_OR_REASSIGN")

        self.led.reassign(self.s1, "worker-b", "連續三次無回應")
        self.assertEqual(self.led.steps_of(self.t)[0]["assigned_worker"], "worker-b")
        self.assertEqual(self.led.state_of(self.t), "RUNNING", "換人不影響任務")

    def test_CT_F05_05_alive_but_wrong_is_a_separate_incident(self):
        """心跳正常但產物是錯的 → 這是 correctness incident，不是 liveness。

        F05 §6：A worker can be alive and wrong。分開的理由不是分類整齊，
        是因為混在一起會出現最糟的情況：心跳正常於是沒人去看產物，
        而產物是錯的。
        """
        (self.tmp / "build.log").write_text("", encoding="utf-8")  # 空檔案 = 假產物
        a = self.led.check_liveness(self.s1)
        self.assertFalse(a.suspect, "檔案剛動過，liveness 應該是好的")

        ok, results = self.led.verify_step(self.s1)
        self.assertFalse(ok, "空檔案不該通過驗證")

        inc = WD.correctness_incident(self.s1, [r.spec for r in results if not r.ok])
        self.assertEqual(inc.kind, "CORRECTNESS")
        self.assertNotEqual(inc.kind, WD.liveness_incident(self.s1, a).kind)


class TestStallFormula(unittest.TestCase):
    """§3 的公式。這裡測的是我的詮釋，門檻沒有實測校準。"""

    def test_short_age_never_suspect(self):
        """時間太短一律不判定。長時間本身不足以判定，短時間更不足以。"""
        a = WD.assess(age_sec=10, progress_changed=False, events_since=0)
        self.assertEqual(a.factors["duration_anomaly"], 0.0)
        self.assertFalse(a.suspect)

    def test_any_zero_factor_clears_the_risk(self):
        """四個因子相乘，任何一個接近 0 就洗掉懷疑。

        這正是 §3 那句「長時間本身不足以判定」的機制形式。
        """
        base = dict(age_sec=7200, progress_changed=False, events_since=0)
        self.assertTrue(WD.assess(**base).suspect)
        self.assertFalse(WD.assess(**{**base, "progress_changed": True}).suspect)
        self.assertFalse(WD.assess(**{**base, "events_since": 1}).suspect)
        self.assertFalse(WD.assess(**{**base, "expected_to_progress": False}).suspect)

    def test_not_expected_to_progress_never_stalls(self):
        """本來就不預期有產物的步驟，再久也不算停滯。

        例如在等外部依賴。沒有這個煞車，所有等待都會被誤判成卡住。
        """
        a = WD.assess(age_sec=86400, progress_changed=False, events_since=0,
                      expected_to_progress=False)
        self.assertEqual(a.risk, 0.0)
        self.assertIn("不預期", a.why)

    def test_risk_is_bounded(self):
        for age in (0, 100, 3600, 86400, 10**7):
            a = WD.assess(age_sec=age, progress_changed=False, events_since=0)
            self.assertGreaterEqual(a.risk, 0.0)
            self.assertLessEqual(a.risk, 1.0)


class TestRecoveryLadder(unittest.TestCase):
    def test_human_is_the_last_rung_not_the_first(self):
        """人排在最後。叫人是最貴的一步，不是最方便的一步。"""
        self.assertEqual(WD.LADDER[0], "SUSPECT")
        self.assertEqual(WD.LADDER[-1], "HUMAN")
        rung = None
        seen = []
        for _ in range(len(WD.LADDER) + 3):
            rung = WD.next_rung(rung)
            seen.append(rung)
        self.assertEqual(seen[0], "SUSPECT")
        self.assertEqual(seen[-1], "HUMAN")
        self.assertLess(seen.index("RESTART_OR_REASSIGN"), seen.index("HUMAN"))

    def test_unknown_rung_restarts_the_ladder(self):
        self.assertEqual(WD.next_rung("不存在的階"), "SUSPECT")


class TestProgressProbe(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_probe_detects_content_change_not_just_size(self):
        """內容變了但大小一樣，也算有進度。只看大小會漏掉原地覆寫。"""
        f = self.tmp / "a.txt"
        f.write_text("aaaa", encoding="utf-8")
        p1 = WD.ProgressProbe.take(["a.txt"], self.tmp)
        f.write_text("bbbb", encoding="utf-8")
        p2 = WD.ProgressProbe.take(["a.txt"], self.tmp)
        self.assertTrue(p2.changed_from(p1))

    def test_missing_file_is_not_a_change(self):
        p1 = WD.ProgressProbe.take(["nope.txt"], self.tmp)
        p2 = WD.ProgressProbe.take(["nope.txt"], self.tmp)
        self.assertFalse(p2.changed_from(p1))


if __name__ == "__main__":
    unittest.main(verbosity=2)
