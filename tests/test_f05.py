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


class TestSweepFindsForgottenWorkers(F05Case):
    """B-09 的回歸測試：controller 忘記 worker 存在。

    2026-09-08 一個 worker 死了十七小時沒人知道。watchdog 那時已經
    寫好也測過，但它要有人記得對那個特定的 step 呼叫 check_liveness()，
    而「記得」正是會失敗的東西。

    所以這一組測的不是「watchdog 判斷得準不準」（那是上面那些），
    是「不必記得也找得到」。
    """

    def test_active_steps_finds_it_without_knowing_the_id(self):
        """不給 step_id，也要找得到進行中的步驟。"""
        found = self.led.active_steps()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["worker"], "worker-a")
        self.assertEqual(found[0]["local_id"], "s1")

    def test_terminal_steps_are_not_swept(self):
        """已經結束的步驟不該一直出現在巡檢裡。"""
        (self.tmp / "build.log").write_text("done", encoding="utf-8")
        self.led.verify_step(self.s1)
        self.assertEqual(self.led.active_steps(), [])

    def test_steps_of_a_terminated_task_drop_out_of_the_sweep(self):
        """任務結束了，它的步驟就不該還被當成「有人在做」。

        2026-09-09 實測撞到：兩個任務轉成 SUPERSEDED 之後，巡檢仍然
        每次都列出它們的步驟，因為步驟自己還停在 RUNNING。一個永遠
        清不掉的待辦會讓整張巡檢表失去意義 —— 看久了就會開始忽略它，
        而那正是它存在的反面。
        """
        self.assertEqual(len(self.led.active_steps()), 1)
        self.led.transition(self.t, "SUPERSEDED", "換一個做法", actor="owner")
        self.assertEqual(self.led.active_steps(), [],
                         "任務被取代之後，它的步驟不該還在巡檢表上")

    def test_the_longest_silent_one_comes_first(self):
        """最久沒動靜的排最前面，因為那是最可能已經死掉的。"""
        self.led.con.execute(
            "INSERT INTO steps (step_id,task_id,seq,objective,dependencies,state,"
            "started_at,last_progress_at,expected_outputs,verifier,evidence_refs,"
            "retry_count,next_action,requires_human,assigned_worker)"
            " VALUES (?,?,?,?,'[]','RUNNING',?,?,'[]','[]','[]',0,'',0,?)",
            (f"{self.t}/s2", self.t, 2, "剛派出去的", time.time(), time.time(),
             "worker-b"))
        self.led.con.commit()
        self.age_step(7200)

        found = self.led.active_steps()
        self.assertEqual([f["local_id"] for f in found], ["s1", "s2"])
        self.assertGreater(found[0]["idle_sec"], 7000)

    def test_sweeping_repeatedly_does_not_bloat_the_event_log(self):
        """重複巡檢不該讓事件表以巡檢頻率膨脹。

        watch 是可以掛進排程每分鐘跑的東西。每次都寫一筆「取樣了但
        什麼都沒變」，一天就是上千筆零資訊的紀錄，而真正的事件會被
        淹沒在裡面。只在有變化時才記。
        """
        def probes():
            return sum(1 for e in self.led.events_of(self.t)
                       if e["kind"] == "PROGRESS_PROBE")

        for _ in range(5):
            self.led.check_liveness(self.s1)
        self.assertEqual(probes(), 1, "五次巡檢什麼都沒變，只該留一筆基準")

        (self.tmp / "build.log").write_text("進度", encoding="utf-8")
        self.led.check_liveness(self.s1)
        self.assertEqual(probes(), 2, "產物真的變了才記第二筆")

    def test_a_worker_that_never_reported_is_still_visible(self):
        """派出去之後一個事件都沒回報，仍然看得見。

        這正是十七小時那次的形狀：worker 收到訊息、沒有接、或接了就死。
        帳本裡沒有它的任何 worker 事件，但派工那一刻已經留下了 step，
        所以巡檢找得到它。派工登記進帳本是整條防線的第一塊。
        """
        events = [e for e in self.led.events_of(self.t)
                  if e["kind"].startswith("WORKER_")]
        self.assertEqual(events, [], "這個 worker 從來沒有回報過任何事")

        self.age_step(7200)
        a = self.led.check_liveness(self.s1)
        self.assertTrue(a.suspect, "兩小時沒有產物也沒有事件，該被標出來")
        found = self.led.active_steps()
        self.assertEqual(found[0]["worker"], "worker-a")


class TestInboxReportingChannel(F05Case):
    """B-10：只有 Write 權限的 worker 也要能回報。

    實測發現的事：一個用 `--permission-mode acceptEdits` 開的 worker，
    Write 允許、Bash 被擋，於是它交得出合格的產物，卻連一句「我接下了」
    都送不出去，因為送出的方式是跑一行 python。

    能做事跟能回話是兩種不同的權限。收件匣把後者的門檻降到跟前者一樣。
    """

    def write_inbox(self, name: str, kind: str, body: str = "") -> None:
        d = self.led.inbox_dir(self.s1)
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(f"{kind}\n{body}", encoding="utf-8")

    def test_a_file_becomes_a_real_event(self):
        self.write_inbox("a.txt", "WORKER_ACCEPTED", "接下了")
        got = self.led.collect_inbox(self.s1)
        self.assertEqual(got, ["WORKER_ACCEPTED"])
        kinds = [e["kind"] for e in self.led.events_of(self.t)]
        self.assertIn("WORKER_ACCEPTED", kinds)

    def test_collecting_twice_does_not_duplicate(self):
        """撿過的不再撿。冪等靠 idem_key，不靠記得移走檔案。"""
        self.write_inbox("a.txt", "WORKER_PROGRESS", "一半了")
        self.led.collect_inbox(self.s1)
        # 就算檔案又被放回來，也不該再算一次
        self.write_inbox("a.txt", "WORKER_PROGRESS", "一半了")
        self.led.collect_inbox(self.s1)
        n = sum(1 for e in self.led.events_of(self.t)
                if e["kind"] == "WORKER_PROGRESS")
        self.assertEqual(n, 1)

    def test_appledouble_sidecars_are_not_counted_as_reports(self):
        """`._` 開頭的附屬檔不算回報。

        這個 repo 在 exFAT 外接碟上，macOS 會為每個檔案寫一個 `._` 附屬檔。
        不濾掉的話一則回報會被算成兩則，第二則的內容還是二進位垃圾。
        tools/orphans.mjs 因為同一個原因假警報過兩次。
        """
        self.write_inbox("a.txt", "WORKER_PROGRESS", "真的回報")
        d = self.led.inbox_dir(self.s1)
        (d / "._a.txt").write_bytes(b"\x00\x05\x16\x07AppleDouble")
        self.led.collect_inbox(self.s1)
        n = sum(1 for e in self.led.events_of(self.t)
                if e["kind"] == "WORKER_PROGRESS")
        self.assertEqual(n, 1, "附屬檔不該被當成第二則回報")

    def test_unknown_kind_is_recorded_not_discarded(self):
        """不認得的種類不丟掉。

        丟掉會讓 worker 的話消失得無聲無息，而那正是這條通道要解決的
        問題。記成 INBOX_UNKNOWN_KIND，讓它至少看得見。
        """
        self.write_inbox("x.txt", "差不多好了", "嗨")
        self.led.collect_inbox(self.s1)
        kinds = [e["kind"] for e in self.led.events_of(self.t)]
        self.assertIn("INBOX_UNKNOWN_KIND", kinds)

    def test_unknown_kind_keeps_the_body_too(self):
        """種類不認得的時候，說明本身更要留住。

        第一版只記了檔名與第一行，於是 worker 寫了什麼還是消失了一半。
        那等於沒有做到「不讓它的話無聲消失」這句話宣稱的事。
        """
        self.write_inbox("x.txt", "差不多好了", "報告寫在 docs/x.md，有四個發現")
        self.led.collect_inbox(self.s1)
        ev = next(e for e in self.led.events_of(self.t)
                  if e["kind"] == "INBOX_UNKNOWN_KIND")
        self.assertIn("四個發現", ev["cause"] + ev["payload"].get("body", ""))

    def test_a_predictable_misspelling_is_absorbed_not_punished(self):
        """WORKER_DONE 這種寫法要收。

        2026-09-09 實測：訊息裡列了八種，worker 仍然寫了 WORKER_DONE。
        那不是它不小心，是那個名字比 COMPLETION 更像人會講的話。
        可預期的寫法失誤由設計吸收，不是靠要求對方更小心。

        別名表只收實測發生過的，每條附出處，否則它會長成一張什麼都收
        的表，那等於沒有協定。
        """
        self.write_inbox("d.txt", "WORKER_DONE", "做完了")
        self.led.collect_inbox(self.s1)
        kinds = [e["kind"] for e in self.led.events_of(self.t)]
        self.assertIn("WORKER_COMPLETION", kinds)
        self.assertNotIn("INBOX_UNKNOWN_KIND", kinds)

    def test_kind_and_text_on_the_same_line_still_parses(self):
        """種類跟說明寫在同一行也要讀得懂。

        合法的種類都沒有空白，所以取第一個 token 是安全的，
        而且省掉一種可預期的寫法失誤。
        """
        d = self.led.inbox_dir(self.s1)
        d.mkdir(parents=True, exist_ok=True)
        (d / "one.txt").write_text("WORKER_PROGRESS 讀到一半", encoding="utf-8")
        self.led.collect_inbox(self.s1)
        ev = next(e for e in self.led.events_of(self.t)
                  if e["kind"] == "WORKER_PROGRESS")
        self.assertIn("讀到一半", ev["cause"])

    def test_claiming_completion_in_a_file_does_not_verify_anything(self):
        """worker 寫檔案說自己完成了，步驟不會因此變成已驗證。

        這條是整個收件匣最重要的邊界。降低回報的門檻不等於降低驗證的
        門檻 —— 一個檔案裡的「我做完了」跟嘴巴說的「我做完了」是同一
        種東西，都是 claim。
        """
        self.write_inbox("done.txt", "WORKER_COMPLETION", "全部做完了")
        self.led.collect_inbox(self.s1)
        state = self.led.steps_of(self.t)[0]["state"]
        self.assertNotEqual(state, "VERIFIED_COMPLETE")
        self.assertIn(state, L.ACTIVE)

    def test_writing_a_file_rescues_a_worker_from_being_called_stalled(self):
        """寫一個檔案就足以證明自己還活著。

        這是這條通道存在的理由。沒有它，一個只能寫檔的 worker 在還沒
        產出第一個檔案之前，四個因子會是「久 × 沒產物 × 沒事件 × 該有產物」，
        於是活得好好的它會被判定成停滯。
        """
        self.age_step(7200)
        a = self.led.check_liveness(self.s1)
        self.assertTrue(a.suspect, "沒有任何訊號時確實該被標出來")

        self.age_step(7200)
        self.write_inbox("alive.txt", "WORKER_PROGRESS", "還在讀規格，慢但沒死")
        a2 = self.led.check_liveness(self.s1)
        self.assertFalse(a2.suspect, "它說話了，就不該再被當成停滯")

    def test_the_ladder_skips_asking_a_worker_that_cannot_answer(self):
        """回不了話的 worker，不要浪費三階去問它。

        階梯的前三階都是「問它」。問一個只有 Write 權限的 worker 三次，
        它不會因此變得能回答，只是把真正有用的動作往後推三輪。
        """
        full = WD.next_rung(None, can_report="full")
        self.assertEqual(full, "SUSPECT")
        self.assertEqual(WD.next_rung("SUSPECT", can_report="full"), "SOFT_PING")

        # 只能寫檔的，跳過問話，直接去看它留下了什麼
        self.assertEqual(WD.next_rung("SUSPECT", can_report="write_only"),
                         "CHECKPOINT")

    def test_recover_uses_the_workers_declared_capability(self):
        """帳本裡宣告的能力要真的影響決定，不是只存著好看。"""
        self.led.dispatch(self.s1, "worker-a", "重派", can_report="write_only")
        self.assertEqual(self.led.recover(self.s1, current_rung="SUSPECT"),
                         "CHECKPOINT")

    def test_dispatch_records_whether_the_worker_can_report(self):
        """派工方宣告的能力要留在帳本裡。

        不宣告就是 unknown，那不是「大概可以」，是「沒問過」。
        把它記成 full 會讓一個沒有答案的問題看起來已經有答案。
        """
        self.assertEqual(self.led.can_report(self.s1), "unknown")
        self.led.dispatch(self.s1, "worker-b", "重派", can_report="write_only")
        self.assertEqual(self.led.can_report(self.s1), "write_only")
        with self.assertRaises(ValueError):
            self.led.dispatch(self.s1, "worker-b", "亂填", can_report="maybe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
