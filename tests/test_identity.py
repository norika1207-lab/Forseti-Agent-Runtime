#!/usr/bin/env python3
"""§11.1 Persistent Agent Identity。

這一組要抓的是四類會靜默說謊的事:

  一，五個軸跟規格原文分岔了而沒有人發現
  二，`<synthetic>` 被算成一個模型，於是「換過模型」的條數被灌大
  三，NO_SOURCE 被投影成好消息(沒有來源長得像沒有問題)
  四，靠命名相似度把兩個 alias 認成同一個身份

不重測 `context_meter.read_session`，那是它自己的測試的事。
這裡自己造 jsonl，因為拿真實 `~/.claude/projects` 當輸入的測試
會隨著使用者今天用了什麼模型而變色。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import identity as I  # noqa: E402


def _write_session(d: Path, name: str, lines: list[dict]) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    with p.open("w", encoding="utf-8") as fh:
        for x in lines:
            fh.write(json.dumps(x, ensure_ascii=False) + "\n")
    return p


def _turn(sid: str, model: str | None = None, **extra) -> dict:
    d = {"sessionId": sid, "timestamp": "2026-09-16T10:00:00Z",
         "cwd": "/x", "gitBranch": "main", "version": "1.0"}
    if model:
        d["message"] = {"model": model}
    d.update(extra)
    return d


class 五個軸要跟規格一致(unittest.TestCase):
    def test_五個軸不是四個也不是六個(self):
        self.assertEqual(len(I.AXES), 5)

    def test_每一個軸都回得去規格那一行原文(self):
        r = I.verify_spec()
        self.assertTrue(r["ok"], r)
        self.assertTrue(r["anchor_ok"], r)
        self.assertEqual(r["checked"], 5)
        for row in r["rows"]:
            self.assertTrue(row["ok"], row)
            # 比對的是那一行本身,所以每一行都要以 ≠ 開頭。
            self.assertTrue(row["raw"].startswith("≠"), row)

    def test_規格原文改一個字就會紅(self):
        orig = I.AXES[3]["axis"]
        try:
            I.AXES[3]["axis"] = "Execution Slots"
            self.assertFalse(I.verify_spec()["ok"])
        finally:
            I.AXES[3]["axis"] = orig
        self.assertTrue(I.verify_spec()["ok"])

    def test_指錯行號也會紅(self):
        orig = I.AXES[0]["spec_line"]
        try:
            I.AXES[0]["spec_line"] = 326   # 那是 Session 那一行
            self.assertFalse(I.verify_spec()["ok"])
        finally:
            I.AXES[0]["spec_line"] = orig
        self.assertTrue(I.verify_spec()["ok"])

    def test_錨點那一行搬走了也要紅(self):
        # 只比對五個軸的話,整節被搬去別的地方而行號剛好對上,會全綠。
        orig = I.SPEC_ANCHOR_LINE
        try:
            I.SPEC_ANCHOR_LINE = 323   # 空行
            r = I.verify_spec()
            self.assertFalse(r["anchor_ok"])
            self.assertFalse(r["ok"])
        finally:
            I.SPEC_ANCHOR_LINE = orig
        self.assertTrue(I.verify_spec()["anchor_ok"])


class 觀察一份真實形狀的jsonl(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "projects"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_抽得出session與model(self):
        p = _write_session(self.root / "a", "s1.jsonl", [
            _turn("sid-1", "claude-opus-5"),
            _turn("sid-1", "claude-sonnet-5"),
        ])
        o = I.observe_session(p)
        self.assertEqual(o["session_ids"], ["sid-1"])
        self.assertEqual(o["models"], ["claude-opus-5", "claude-sonnet-5"])
        self.assertEqual(o["lines"], 2)

    def test_壞行不會炸掉整份而且要計數(self):
        d = self.root / "a"
        d.mkdir(parents=True)
        p = d / "s2.jsonl"
        p.write_text('{"sessionId":"s"}\n{壞掉\n[1,2]\n', encoding="utf-8")
        o = I.observe_session(p)
        self.assertEqual(o["lines"], 1)
        self.assertEqual(o["bad_lines"], 2)

    def test_一個檔裡有兩個sessionId要看得出來(self):
        # 真實資料裡出現過(fork/resume)。「一個檔等於一條 session」是錯的。
        p = _write_session(self.root / "a", "s3.jsonl", [
            _turn("sid-1", "claude-opus-5"),
            _turn("sid-2", "claude-opus-5"),
        ])
        o = I.observe_session(p)
        self.assertEqual(len(o["session_ids"]), 2)

    def test_沒有pid欄位要回False而不是不知道(self):
        p = _write_session(self.root / "a", "s4.jsonl",
                           [_turn("sid-1", "claude-opus-5")])
        self.assertFalse(I.observe_session(p)["has_pid_field"])

    def test_有pid欄位的話要抓得到(self):
        # 反向:哪天 runtime 真的開始寫 pid,這一軸就不該再是 NO_SOURCE。
        p = _write_session(self.root / "a", "s5.jsonl",
                           [_turn("sid-1", "claude-opus-5", pid=123)])
        self.assertTrue(I.observe_session(p)["has_pid_field"])

    def test_讀不到的檔回空的不丟例外(self):
        o = I.observe_session(self.root / "不存在.jsonl")
        self.assertEqual(o["lines"], 0)
        self.assertEqual(o["models"], [])


class synthetic不是模型(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "projects"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_synthetic不算換過模型(self):
        # 2026-09-16 第一版把 19 寫進檔頭,就是這裡算錯。
        _write_session(self.root / "a", "s1.jsonl", [
            _turn("sid-1", "claude-opus-5"),
            _turn("sid-1", "<synthetic>"),
        ])
        s = I.survey(limit=10, root=self.root)
        self.assertEqual(s["multi_model_count"], 0, s["multi_model_sessions"])

    def test_synthetic有被看到要數出來不是默默丟掉(self):
        p = _write_session(self.root / "a", "s2.jsonl", [
            _turn("sid-1", "<synthetic>"),
        ])
        self.assertEqual(I.observe_session(p)["synthetic_seen"], 1)
        self.assertEqual(I.observe_session(p)["models"], [])

    def test_兩個真模型才算換過(self):
        _write_session(self.root / "a", "s3.jsonl", [
            _turn("sid-1", "claude-opus-5"),
            _turn("sid-1", "claude-haiku-4-5-20251001"),
        ])
        s = I.survey(limit=10, root=self.root)
        self.assertEqual(s["multi_model_count"], 1)


class 抽樣的分母要說出來(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "projects"
        for i in range(5):
            _write_session(self.root / "a", f"s{i}.jsonl",
                           [_turn(f"sid-{i}", "claude-opus-5")])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_掃幾條跟磁碟上有幾條是兩個數字(self):
        s = I.survey(limit=2, root=self.root)
        self.assertEqual(s["scanned"], 2)
        self.assertEqual(s["total_sessions_on_disk"], 5)
        self.assertTrue(s["sampled"])

    def test_全掃的時候sampled要是False(self):
        s = I.survey(limit=99, root=self.root)
        self.assertEqual(s["scanned"], 5)
        self.assertFalse(s["sampled"])

    def test_目錄不存在不丟例外(self):
        s = I.survey(limit=5, root=self.root.parent / "沒有這個目錄")
        self.assertEqual(s["scanned"], 0)
        self.assertEqual(s["total_sessions_on_disk"], 0)


def _fake_ledger(p: Path, workers=(), actors_=(), accepted=()) -> Path:
    c = sqlite3.connect(p)
    with c:
        c.execute("CREATE TABLE steps (step_id TEXT, assigned_worker TEXT)")
        c.execute("CREATE TABLE events (event_id INTEGER, actor TEXT)")
        c.execute("CREATE TABLE tasks (task_id TEXT, accepted_by TEXT)")
        for i, w in enumerate(workers):
            c.execute("INSERT INTO steps VALUES (?,?)", (f"st{i}", w))
        for i, a in enumerate(actors_):
            c.execute("INSERT INTO events VALUES (?,?)", (i, a))
        for i, a in enumerate(accepted):
            c.execute("INSERT INTO tasks VALUES (?,?)", (f"t{i}", a))
    c.close()
    return p


class 帳本裡誰被當成身份(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = _fake_ledger(self.tmp / "l.db",
                               workers=("w-1", "w-2"),
                               actors_=("w-1", "controller"),
                               accepted=("controller",))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_三個欄位分開數(self):
        a = I.actors(self.db)
        self.assertTrue(a["available"])
        self.assertEqual({x["name"] for x in a["assigned_worker"]},
                         {"w-1", "w-2"})
        self.assertEqual({x["name"] for x in a["actor"]},
                         {"w-1", "controller"})
        self.assertEqual({x["name"] for x in a["accepted_by"]},
                         {"controller"})
        self.assertEqual(set(a["all"]), {"w-1", "w-2", "controller"})

    def test_帳本不存在要說不可得而不是回空集合(self):
        a = I.actors(self.tmp / "沒有這個檔.db")
        self.assertFalse(a["available"])
        self.assertTrue(a["why"])
        # 空清單跟「沒有量」在畫面上長得一樣,所以 available 要分得開。
        self.assertEqual(a["all"], [])

    def test_連預設帳本都沒有的時候也要說不可得(self):
        # 上面那條打的是「給了路徑但開不起來」,這條打的是「根本沒有帳本」。
        # 2026-09-16 反向驗證第 5 次發現這兩條是不同分支,而只有一條有測。
        orig = I._ledger_db
        try:
            I._ledger_db = lambda: None
            a = I.actors(None)
            self.assertFalse(a["available"])
            self.assertTrue(a["why"])
            self.assertEqual(a["all"], [])
        finally:
            I._ledger_db = orig


class 登記簿是人工的(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".forseti").mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_沒有檔就是零條不是錯誤(self):
        self.assertEqual(I.registry(self.tmp), [])

    def test_登記得進去也讀得回來(self):
        r = I.register("ag-1", ["w-1", "w-2"], "測試", repo=self.tmp)
        self.assertTrue(r["ok"], r)
        got = I.registry(self.tmp)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["aliases"], ["w-1", "w-2"])

    def test_同一個id不准登記兩次(self):
        I.register("ag-1", ["w-1"], repo=self.tmp)
        r = I.register("ag-1", ["w-9"], repo=self.tmp)
        self.assertFalse(r["ok"])
        self.assertEqual(len(I.registry(self.tmp)), 1)

    def test_空的id擋掉(self):
        self.assertFalse(I.register("  ", ["w"], repo=self.tmp)["ok"])

    def test_壞行跳過不炸掉(self):
        p = self.tmp / I.REGISTRY_NAME
        p.write_text('{壞\n{"agent_id":"ag-2","aliases":["x"]}\n{"no_id":1}\n',
                     encoding="utf-8")
        got = I.registry(self.tmp)
        self.assertEqual([x["agent_id"] for x in got], ["ag-2"])


class 身份漂移兩個方向(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".forseti").mkdir()
        self.db = _fake_ledger(self.tmp / "l.db",
                               workers=("w-1", "w-2"),
                               actors_=("w-3",))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_沒人認領的alias要列出來(self):
        d = I.drift(self.tmp, self.db)
        self.assertEqual(d["registered"], 0)
        self.assertEqual(set(d["unregistered"]), {"w-1", "w-2", "w-3"})

    def test_登記了帳本卻沒出現過算過期(self):
        I.register("ag-1", ["w-1", "w-鬼"], repo=self.tmp)
        d = I.drift(self.tmp, self.db)
        self.assertEqual(d["stale"], ["w-鬼"])
        self.assertEqual(d["matched"], ["w-1"])
        self.assertEqual(set(d["unregistered"]), {"w-2", "w-3"})

    def test_不靠命名相似度配對(self):
        # `w-1` 登記過,`w-2` 沒有。前綴一樣,但不准因此認成同一個身份。
        I.register("ag-1", ["w-1"], repo=self.tmp)
        d = I.drift(self.tmp, self.db)
        self.assertIn("w-2", d["unregistered"])
        self.assertNotIn("w-2", d["matched"])


class 五軸判定(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".forseti").mkdir()
        self.root = self.tmp / "projects"
        self.db = _fake_ledger(self.tmp / "l.db", workers=("w-1",))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _assess(self):
        # verify_spec 要的是真的規格檔,所以 repo 用真的 ROOT;
        # 登記簿與 session 用暫存的。
        return I.assess(repo=self.tmp, limit=99, root=self.root, db=self.db)

    def test_同一條線換過模型就判分得開(self):
        _write_session(self.root / "a", "s.jsonl", [
            _turn("sid-1", "claude-opus-5"),
            _turn("sid-1", "claude-sonnet-5"),
        ])
        row = {r["key"]: r for r in self._assess()["rows"]}["model"]
        self.assertEqual(row["state"], "SEPARABLE")
        self.assertIn("1 條", row["evidence"])

    def test_沒遇到換模型不准判成分不開(self):
        # 「沒遇到」與「分不開」是兩件事,這一條釘住不准混。
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        row = {r["key"]: r for r in self._assess()["rows"]}["model"]
        self.assertEqual(row["state"], "NO_SOURCE")
        self.assertIn("沒遇到", row["evidence"])

    def test_有alias沒登記就判混在一起(self):
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        row = {r["key"]: r for r in self._assess()["rows"]}["session"]
        self.assertEqual(row["state"], "CONFLATED")

    def test_全部alias都被登記才判分得開(self):
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        I.register("ag-1", ["w-1"], repo=self.tmp)
        row = {r["key"]: r for r in self._assess()["rows"]}["session"]
        self.assertEqual(row["state"], "SEPARABLE")

    def test_三軸沒有來源(self):
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        rows = {r["key"]: r for r in self._assess()["rows"]}
        for k in ("process", "execution_slot", "role"):
            self.assertEqual(rows[k]["state"], "NO_SOURCE", k)
            self.assertTrue(rows[k]["evidence"], k)

    def test_沒有第四種狀態(self):
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        for r in self._assess()["rows"]:
            self.assertIn(r["state"], I.STATES, r)

    def test_每一軸都講得出依據(self):
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        for r in self._assess()["rows"]:
            self.assertTrue(r["evidence"].strip(), r)
            self.assertIn(":", r["spec"])

    def test_誠實條款三條都要在回傳值裡(self):
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        a = self._assess()
        for k in ("sampled_note", "no_source_note", "no_fuzzy_note"):
            self.assertTrue(a[k].strip(), k)

    def test_有pid欄位的話process那一軸的live要跟著動(self):
        # 現在是 0。哪天 runtime 開始寫 pid,這個數字要自己變,
        # 不是等人回來改一個寫死的 0。
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5", pid=7)])
        row = {r["key"]: r for r in self._assess()["rows"]}["process"]
        self.assertEqual(row["live"]["value"], 1)

    def test_summary跟assess講同一件事(self):
        _write_session(self.root / "a", "s.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        a = self._assess()
        s = I.summary(repo=self.tmp, limit=99)
        self.assertEqual(s["total"], a["total"])
        self.assertEqual(sum(s["by_state"].values()), 5)


class 畫面不准把沒有來源畫成好消息(unittest.TestCase):
    def test_no_source不是零問題(self):
        # 這一條守的是文案,不是數字。三軸 NO_SOURCE 的時候,
        # 回傳值裡必須有一句話講明那不是「沒問題」。
        a = I.assess()
        self.assertIn("不是", a["no_source_note"])
        self.assertGreaterEqual(a["by_state"]["NO_SOURCE"], 1)


class 逐檔快取不可以改變答案(unittest.TestCase):
    """survey 的磁碟快取（2026-09-16 21:5x）。

    這一組防的是快取最會出的兩種事:

      一，快取回的東西跟現算的不一樣（那會讓畫面停在一個舊答案，
          而且不會有任何錯誤訊息）
      二，檔案動過了快取還在命中（同上，但更難查，因為它只在
          「剛好動到的那一條」上出錯）

    **mtime 一律用 `os.utime` 明確設定，不靠寫入的先後。**
    exFAT 的 mtime 解析度不保證分得開毫秒級的兩次寫入，
    靠時間差的測試會在快的機器上隨機變綠。
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "projects"
        self._repo = I.REPO
        self._proj = I.PROJECTS_DIR
        # 正本的快取檔不可以被測試寫到，所以把兩個常數都搬進 tmp。
        I.REPO = self.tmp
        I.PROJECTS_DIR = self.root

    def tearDown(self):
        I.REPO = self._repo
        I.PROJECTS_DIR = self._proj
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch(self, p: Path, mtime: float):
        import os
        os.utime(p, (mtime, mtime))

    def test_第二次全部命中而且答案一模一樣(self):
        _write_session(self.root / "a", "s1.jsonl", [
            _turn("sid-1", "claude-opus-5"),
            _turn("sid-1", "claude-sonnet-5"),
        ])
        _write_session(self.root / "a", "s2.jsonl",
                       [_turn("sid-2", "claude-opus-5")])
        first = I.survey(limit=10)
        second = I.survey(limit=10)
        self.assertEqual(first["cache_hits"], 0)
        self.assertEqual(second["cache_hits"], 2)
        for k in first:
            if k == "cache_hits":
                continue
            self.assertEqual(first[k], second[k], f"{k} 冷熱不一致")

    def test_動過的那一條要重讀(self):
        p = _write_session(self.root / "a", "s1.jsonl",
                           [_turn("sid-1", "claude-opus-5")])
        self._touch(p, 1_000_000)
        I.survey(limit=10)
        _write_session(self.root / "a", "s1.jsonl", [
            _turn("sid-1", "claude-opus-5"),
            _turn("sid-1", "claude-sonnet-5"),
        ])
        self._touch(p, 2_000_000)
        s = I.survey(limit=10)
        self.assertEqual(s["cache_hits"], 0, "mtime 變了還命中")
        self.assertEqual(s["multi_model_count"], 1,
                         "重讀之後要看得到新加的那個模型")

    def test_給了root就不碰快取(self):
        _write_session(self.root / "a", "s1.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        s = I.survey(limit=10, root=self.root)
        self.assertFalse(s["cache_used"])
        self.assertEqual(s["cache_hits"], 0)
        self.assertFalse(I._cache_file().exists(),
                         "臨時目錄不該留下快取檔")

    def test_stat不到的檔不給key也不寫進快取(self):
        # `_obs_key` 回 None 的那條路。編一個 key 出來的話，
        # 快取會永遠命中同一筆。
        self.assertIsNone(I._obs_key(self.root / "沒有這個檔.jsonl"))

    def test_命中之後就算有人改了結果也不會被寫回磁碟(self):
        """2026-09-16 21:5x 實際踩到的那件事。

        反向驗證在命中之後改了一個欄位，那個值被寫回快取檔，
        於是程式碼還原之後錯的答案還留在磁碟上。**症狀是一個
        看起來完全合理的數字**，不是錯誤訊息。
        """
        _write_session(self.root / "a", "s1.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        I.survey(limit=10)
        before = json.loads(I._cache_file().read_text(encoding="utf-8"))
        real = I.observe_session
        try:
            # 命中那條路不會呼叫 observe_session，所以這裡只要確認
            # 第二次跑完磁碟上的內容沒有被動過。
            I.observe_session = lambda p: (_ for _ in ()).throw(
                AssertionError("命中的時候不該再讀檔"))
            I.survey(limit=10)
        finally:
            I.observe_session = real
        after = json.loads(I._cache_file().read_text(encoding="utf-8"))
        self.assertEqual(before, after, "命中之後快取檔被改寫了")

    def test_快取檔壞掉就重算不丟例外(self):
        _write_session(self.root / "a", "s1.jsonl",
                       [_turn("sid-1", "claude-opus-5")])
        I.survey(limit=10)
        f = I._cache_file()
        f.write_text("{壞掉的 json", encoding="utf-8")
        s = I.survey(limit=10)
        self.assertEqual(s["cache_hits"], 0)
        self.assertEqual(s["scanned"], 1)


if __name__ == "__main__":
    unittest.main()
