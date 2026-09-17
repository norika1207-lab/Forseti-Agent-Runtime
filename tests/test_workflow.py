#!/usr/bin/env python3
"""§5 Workflow / WorkflowStep 與 §17.1 Workflow Reconstruction。

這一組要抓的是五類會靜默說謊的事:

  一，`resume()` 其實靠了程序內的狀態，於是「程序死掉接得回來」
      在單一程序裡測起來永遠是綠的
  二，NO_SOURCE 被投影成好消息(`external_refs` 回 `[]` 讀起來是
      「這一步沒有外部效果」)
  三，`UNDECLARED` 被當成 `NONE`(沒有人回答過，被讀成「不跨邊界」)
  四，STEP_STATE 被當成規格的 STEP_START，於是「我們沒照規格記」
      變成「我們照規格記了」
  五，依賴指到不存在的 step 被併進 blocked，於是資料壞了看起來像
      在等人

自己造 sqlite，不拿真實帳本當輸入 —— 那會讓這組測試隨著今天誰派了
什麼工而變色。只有兩條刻意打真實正本(規格原文比對)，因為那兩條要抓的
正是「規格被改了而程式碼沒跟上」。
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "apps" / "forseti-cli"
sys.path.insert(0, str(CLI))

import workflow as W  # noqa: E402


def _mkdb(path: Path, tasks: list[dict], steps: list[dict],
          events: list[tuple[str, int]] | None = None) -> None:
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE tasks (
      task_id TEXT PRIMARY KEY, owner_goal_ref TEXT, objective TEXT,
      accepted_at REAL, accepted_by TEXT,
      deliverables TEXT, definition_of_done TEXT, stop_conditions TEXT,
      evidence_contract TEXT,
      current_state TEXT, current_owner TEXT, next_required_action TEXT,
      terminal_reason TEXT);
    CREATE TABLE steps (
      step_id TEXT PRIMARY KEY, task_id TEXT, seq INTEGER,
      objective TEXT, dependencies TEXT, assigned_worker TEXT,
      state TEXT, started_at REAL, last_progress_at REAL,
      expected_outputs TEXT, verifier TEXT, evidence_refs TEXT,
      retry_count INTEGER DEFAULT 0, next_action TEXT,
      requires_human INTEGER DEFAULT 0,
      worker_can_report TEXT DEFAULT 'unknown');
    CREATE TABLE events (
      event_id INTEGER PRIMARY KEY AUTOINCREMENT,
      at REAL, task_id TEXT, step_id TEXT,
      kind TEXT, from_state TEXT, to_state TEXT,
      cause TEXT, actor TEXT, payload TEXT);
    """)
    for t in tasks:
        con.execute(
            "INSERT INTO tasks (task_id, objective, accepted_at, accepted_by,"
            " stop_conditions, current_state, current_owner,"
            " next_required_action) VALUES (?,?,?,?,?,?,?,?)",
            (t["task_id"], t.get("objective", ""), t.get("accepted_at", 1.0),
             t.get("accepted_by", "alias-1"),
             json.dumps(t.get("stop_conditions", []), ensure_ascii=False),
             t.get("current_state", "RUNNING"),
             t.get("current_owner", "alias-1"),
             t.get("next_required_action", "")))
    for s in steps:
        con.execute(
            "INSERT INTO steps (step_id, task_id, seq, objective,"
            " dependencies, assigned_worker, state, expected_outputs,"
            " retry_count, next_action, requires_human)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (s["step_id"], s["task_id"], s.get("seq", 0),
             s.get("objective", ""),
             json.dumps(s.get("dependencies", []), ensure_ascii=False),
             s.get("assigned_worker"), s.get("state", "RUNNING"),
             json.dumps(s.get("expected_outputs", []), ensure_ascii=False),
             s.get("retry_count", 0), s.get("next_action", ""),
             1 if s.get("requires_human") else 0))
    for kind, n in (events or []):
        for _ in range(n):
            con.execute("INSERT INTO events (at, kind) VALUES (?,?)",
                        (1.0, kind))
    con.commit()
    con.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wf-test-"))
        self.db = self.tmp / "ledger.db"
        self.repo = self.tmp / "repo"
        (self.repo / ".forseti").mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 規格原文
# ---------------------------------------------------------------------------

class SpecText(unittest.TestCase):
    def test_四行原文逐字對得上正本(self):
        r = W.verify_spec()
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["checked"], 4)
        self.assertEqual({x["key"] for x in r["rows"]},
                         {"workflow", "step", "reconstruction", "events"})

    def test_改一個字就會紅(self):
        tmp = Path(tempfile.mkdtemp(prefix="wf-spec-"))
        try:
            f = tmp / W.SPEC
            f.parent.mkdir(parents=True)
            lines = (ROOT / W.SPEC).read_text(encoding="utf-8").splitlines()
            lines[W.SPEC_WORKFLOW_LINE - 1] = lines[
                W.SPEC_WORKFLOW_LINE - 1].replace("Durable", "Durabl")
            f.write_text("\n".join(lines), encoding="utf-8")
            r = W.verify_spec(repo=tmp)
            self.assertFalse(r["ok"])
            bad = [x for x in r["rows"] if not x["ok"]]
            self.assertEqual([x["key"] for x in bad], ["workflow"])
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_規格檔不在的時候說不在而不是說對(self):
        r = W.verify_spec(repo=Path("/nonexistent-forseti-xyz"))
        self.assertFalse(r["ok"])
        self.assertIn("規格檔不在", r["why"])

    def test_十個欄位跟規格那兩行的欄位名一字不差(self):
        raw = W.SPEC_WORKFLOW_TEXT.split("|")[3].strip()
        want = [x.strip() for x in raw.split(",")]
        self.assertEqual([f["field"] for f in W.WORKFLOW_FIELDS], want)
        raw2 = W.SPEC_STEP_TEXT.split("|")[3].strip()
        want2 = [x.strip() for x in raw2.split(",")]
        self.assertEqual([f["field"] for f in W.STEP_FIELDS], want2)


# ---------------------------------------------------------------------------
# 欄位對照:NO_SOURCE 不准變成好消息
# ---------------------------------------------------------------------------

class Fields(unittest.TestCase):
    def test_兩個覆蓋率分開不合成一個(self):
        f = W.fields()
        self.assertIn("workflow", f)
        self.assertIn("step", f)
        self.assertNotIn("coverage", f)
        self.assertNotEqual(f["workflow"]["coverage"],
                            f["step"]["coverage"])

    def test_每一欄的狀態只能是那三種(self):
        for row in (*W.WORKFLOW_FIELDS, *W.STEP_FIELDS):
            self.assertIn(row["state"], W.SOURCE_STATES, row)

    def test_沒有來源的那兩欄講得出查法而且ledger欄位是None(self):
        gone = [r for r in (*W.WORKFLOW_FIELDS, *W.STEP_FIELDS)
                if r["state"] == "NO_SOURCE"]
        self.assertEqual({r["field"] for r in gone},
                         {"commit_boundary", "external_refs"})
        for r in gone:
            self.assertIsNone(r["ledger"])
            self.assertTrue(r["how"].strip())
            self.assertTrue(r["why"].strip())

    def test_outputs那一欄的欄位名保留expected(self):
        # 改叫 outputs 會讓「預期」與「實際」在畫面上分不出來
        row = [r for r in W.STEP_FIELDS if r["field"] == "outputs"][0]
        self.assertEqual(row["state"], "DEGRADED")
        self.assertIn("expected_outputs", row["ledger"])


# ---------------------------------------------------------------------------
# commit boundary:UNDECLARED 不是 NONE
# ---------------------------------------------------------------------------

class Boundary(Base):
    def test_沒登記是UNDECLARED而且declared是False(self):
        b = W.boundary_of("T-x", repo=self.repo)
        self.assertEqual(b["state"], "UNDECLARED")
        self.assertFalse(b["declared"])
        self.assertNotEqual(b["state"], "NONE")
        self.assertTrue(b["why"].strip())

    def test_UNDECLARED不准拿來登記(self):
        with self.assertRaises(ValueError):
            W.declare_boundary("T-x", "UNDECLARED", declared_by="me",
                               repo=self.repo)

    def test_不合法的狀態不准登記(self):
        with self.assertRaises(ValueError):
            W.declare_boundary("T-x", "MAYBE", declared_by="me",
                               repo=self.repo)

    def test_沒有人認領的宣告不算宣告(self):
        for who in ("", "   "):
            with self.assertRaises(ValueError):
                W.declare_boundary("T-x", "NONE", declared_by=who,
                                   repo=self.repo)

    def test_說跨邊界就要講跨哪個動作(self):
        with self.assertRaises(ValueError):
            W.declare_boundary("T-x", "CROSSES", declared_by="me",
                               repo=self.repo)
        r = W.declare_boundary("T-x", "CROSSES", declared_by="me",
                               actions=["deploy"], repo=self.repo)
        self.assertEqual(r["actions"], ["deploy"])

    def test_只增不改最後一筆有效(self):
        W.declare_boundary("T-x", "NONE", declared_by="a", repo=self.repo)
        W.declare_boundary("T-x", "CROSSES", declared_by="b",
                           actions=["push"], repo=self.repo)
        b = W.boundary_of("T-x", repo=self.repo)
        self.assertEqual(b["state"], "CROSSES")
        self.assertEqual(b["declared_by"], "b")
        self.assertEqual(W.boundaries(repo=self.repo)["lines"], 2)

    def test_壞掉的行要計數不准靜默跳過(self):
        W.declare_boundary("T-x", "NONE", declared_by="a", repo=self.repo)
        p = W.boundary_path(self.repo)
        with p.open("a", encoding="utf-8") as fh:
            fh.write("{這不是 json\n")
        b = W.boundaries(repo=self.repo)
        self.assertEqual(b["unreadable"], 1)
        self.assertEqual(b["lines"], 2)
        self.assertEqual(len(b["records"]), 1)


# ---------------------------------------------------------------------------
# resume:§17.1 的那一行
# ---------------------------------------------------------------------------

class Resume(Base):
    def _fixture(self):
        _mkdb(self.db,
              tasks=[{"task_id": "T-1", "objective": "做一件事",
                      "current_state": "RUNNING",
                      "stop_conditions": ["owner 說停"],
                      "next_required_action": "跑 A"}],
              steps=[
                  {"step_id": "T-1/A", "task_id": "T-1", "seq": 0,
                   "state": "VERIFIED_COMPLETE"},
                  {"step_id": "T-1/B", "task_id": "T-1", "seq": 1,
                   "dependencies": ["T-1/A"], "state": "RUNNING",
                   "retry_count": 2},
                  {"step_id": "T-1/C", "task_id": "T-1", "seq": 2,
                   "dependencies": ["T-1/B"], "state": "WAITING_DEPENDENCY"},
                  {"step_id": "T-1/D", "task_id": "T-1", "seq": 3,
                   "dependencies": ["T-1/MISSING"], "state": "RUNNING"},
                  {"step_id": "T-1/E", "task_id": "T-1", "seq": 4,
                   "state": "NEEDS_HUMAN", "requires_human": True},
              ])

    def test_四類分得開(self):
        self._fixture()
        r = W.resume("T-1", db=self.db, repo=self.repo)
        self.assertTrue(r["ok"])
        self.assertEqual([s["step_id"] for s in r["ready"]],
                         ["T-1/B", "T-1/E"])
        self.assertEqual([s["step_id"] for s in r["blocked"]], ["T-1/C"])
        self.assertEqual([s["step_id"] for s in r["done"]], ["T-1/A"])
        self.assertEqual([s["step_id"] for s in r["dangling"]], ["T-1/D"])

    def test_壞掉的依賴不併進blocked(self):
        # 併進去的話「資料壞了」看起來像「在等人」，而這兩件事的
        # 下一步剛好相反:一個要去修資料，一個要去等。
        self._fixture()
        r = W.resume("T-1", db=self.db, repo=self.repo)
        ids = [s["step_id"] for s in r["blocked"]]
        self.assertNotIn("T-1/D", ids)
        d = r["dangling"][0]
        self.assertEqual(d["unknown_dependencies"], ["T-1/MISSING"])

    def test_blocked講得出在等誰(self):
        self._fixture()
        r = W.resume("T-1", db=self.db, repo=self.repo)
        self.assertEqual(r["blocked"][0]["waiting_on"], ["T-1/B"])

    def test_retries加總(self):
        self._fixture()
        r = W.resume("T-1", db=self.db, repo=self.repo)
        self.assertEqual(r["retries"], 2)

    def test_approvals回的是要不要人不是批准了沒有(self):
        self._fixture()
        r = W.resume("T-1", db=self.db, repo=self.repo)
        a = r["approvals"]
        self.assertEqual(a["needs_human"], ["T-1/E"])
        self.assertNotIn("approved_by", a)
        self.assertIn("要不要人", a["measures"])
        self.assertTrue(a["why"].strip())

    def test_沒有這件workflow的時候說沒有而不是回空的(self):
        self._fixture()
        r = W.resume("T-沒有這個", db=self.db, repo=self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("沒有這件", r["why"])
        self.assertNotIn("ready", r)

    def test_帳本不存在的時候說不存在(self):
        r = W.resume("T-1", db=self.tmp / "不存在.db", repo=self.repo)
        self.assertFalse(r["ok"])
        self.assertIn("不存在", r["why"])

    def test_全部完成的時候ready是空的而且done等於總數(self):
        _mkdb(self.db,
              tasks=[{"task_id": "T-2", "current_state": "VERIFYING"}],
              steps=[{"step_id": "T-2/A", "task_id": "T-2", "seq": 0,
                      "state": "VERIFIED_COMPLETE"},
                     {"step_id": "T-2/B", "task_id": "T-2", "seq": 1,
                      "dependencies": ["T-2/A"],
                      "state": "VERIFIED_COMPLETE"}])
        r = W.resume("T-2", db=self.db, repo=self.repo)
        self.assertEqual(r["counts"],
                         {"ready": 0, "blocked": 0, "done": 2,
                          "dangling": 0, "total": 2})

    def test_owner標明是session_alias不是持久身份(self):
        self._fixture()
        r = W.resume("T-1", db=self.db, repo=self.repo)
        self.assertEqual(r["owner_kind"], "session_alias")

    def test_另一個程序重跑答案一樣(self):
        """ROADMAP 第 6 項完成定義的機械化:「程序死掉之後接得回來」。

        同一個程序裡呼叫兩次永遠會一樣，就算答案其實藏在
        module-level 的變數裡。這一條另起一個 python 程序，
        所以任何跨呼叫的記憶體狀態都救不了它。
        """
        self._fixture()
        first = W.resume("T-1", db=self.db, repo=self.repo)
        code = (
            "import json,sys;"
            f"sys.path.insert(0,{str(CLI)!r});"
            "import workflow as W;"
            f"print(json.dumps(W.resume('T-1', db={str(self.db)!r},"
            f" repo={str(self.repo)!r}), ensure_ascii=False, sort_keys=True))"
        )
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        second = json.loads(out.stdout)
        self.assertEqual(json.dumps(first, sort_keys=True, ensure_ascii=False),
                         json.dumps(second, sort_keys=True,
                                    ensure_ascii=False))
        self.assertEqual(second["counts"]["ready"], 2)

    def test_reconstructed_from指得出是從哪裡重組的(self):
        self._fixture()
        r = W.resume("T-1", db=self.db, repo=self.repo)
        self.assertEqual(r["reconstructed_from"], str(self.db))
        self.assertIn("17.1", r["source"])


# ---------------------------------------------------------------------------
# §6.2 四種事件:不做同義詞對映
# ---------------------------------------------------------------------------

class SpecEvents(Base):
    def test_STEP_STATE不算成STEP_START(self):
        _mkdb(self.db, tasks=[{"task_id": "T-1"}], steps=[],
              events=[("STEP_STATE", 9), ("TASK_STATE", 3)])
        r = W.spec_events(db=self.db)
        self.assertEqual(r["spec_kinds"]["STEP_START"], 0)
        self.assertEqual(r["spec_present"], 0)
        self.assertEqual(r["events_total"], 12)
        self.assertEqual(r["actual_top"][0],
                         {"kind": "STEP_STATE", "count": 9})

    def test_真的有規格事件的時候數得到(self):
        _mkdb(self.db, tasks=[{"task_id": "T-1"}], steps=[],
              events=[("STEP_COMMIT", 4), ("STEP_STATE", 1)])
        r = W.spec_events(db=self.db)
        self.assertEqual(r["spec_kinds"]["STEP_COMMIT"], 4)
        self.assertEqual(r["spec_present"], 1)

    def test_四種都列出來就算是零(self):
        _mkdb(self.db, tasks=[], steps=[], events=[])
        r = W.spec_events(db=self.db)
        self.assertEqual(set(r["spec_kinds"]), set(W.SPEC_EVENTS))
        self.assertEqual(r["spec_total"], 4)

    def test_帳本不存在的時候說不可得而不是回零(self):
        r = W.spec_events(db=self.tmp / "不存在.db")
        self.assertFalse(r["available"])
        self.assertEqual(r["spec_kinds"], {})


# ---------------------------------------------------------------------------
# workflows / assess
# ---------------------------------------------------------------------------

class Overview(Base):
    def test_終態的不算live(self):
        _mkdb(self.db,
              tasks=[{"task_id": "T-1", "current_state": "RUNNING"},
                     {"task_id": "T-2", "current_state": "VERIFIED_COMPLETE"},
                     {"task_id": "T-3", "current_state": "SUPERSEDED"}],
              steps=[{"step_id": "T-1/A", "task_id": "T-1", "seq": 0,
                      "state": "RUNNING"}])
        a = W.assess(db=self.db, repo=self.repo)
        self.assertEqual(a["total"], 3)
        self.assertEqual(a["live"], 1)
        self.assertEqual([r["workflow_id"] for r in a["resumable"]], ["T-1"])

    def test_沒登記邊界的live會被列出來(self):
        _mkdb(self.db, tasks=[{"task_id": "T-1", "current_state": "RUNNING"}],
              steps=[])
        a = W.assess(db=self.db, repo=self.repo)
        self.assertEqual(a["boundary_registry"]["undeclared_live"], ["T-1"])
        W.declare_boundary("T-1", "NONE", declared_by="me", repo=self.repo)
        a2 = W.assess(db=self.db, repo=self.repo)
        self.assertEqual(a2["boundary_registry"]["undeclared_live"], [])
        self.assertEqual(a2["boundary_registry"]["declared"], 1)

    def test_誠實條款不是空的而且講得出那四種事件的現況(self):
        _mkdb(self.db, tasks=[], steps=[], events=[("STEP_STATE", 2)])
        a = W.assess(db=self.db, repo=self.repo)
        self.assertGreaterEqual(len(a["honesty"]), 5)
        self.assertTrue(any("0/4" in h for h in a["honesty"]), a["honesty"])

    def test_帳本不存在的時候available是False(self):
        a = W.assess(db=self.tmp / "不存在.db", repo=self.repo)
        self.assertFalse(a["available"])
        self.assertEqual(a["total"], 0)

    def test_assess不自己重算欄位表(self):
        # 重算會變成兩份會分歧的實作
        a = W.assess(db=self.tmp / "不存在.db", repo=self.repo)
        self.assertEqual(a["fields"], W.fields())


if __name__ == "__main__":
    unittest.main(verbosity=2)
