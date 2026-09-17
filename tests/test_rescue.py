"""救回一次。ROADMAP P0 第 1 項、Vol4 Stage 4 的出口條件。

那個出口條件到 2026-09-16 為止是**零次**：三個零件各自有測試、各自都綠，
但它們之間沒有一條路。這組測試守的是那條路本身。

最重要的三條：

一，**沒有可以回去的點的時候，拒絕並說明缺什麼。**
    猜一個輪號出來的話，會把還好的工作一起丟掉，
    而丟掉的那部分不會有人發現，因為新線看起來很正常。

二，**人標的 last_good 優先於算出來的。**

三，**三筆事件要共用同一個 incident。** 不然事後查不出它們是同一次救援，
    而「全程留在帳本裡可回查」就只是一句話。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import rescue as R  # noqa: E402
import event_ledger as EL  # noqa: E402


@pytest.fixture()
def led(tmp_path):
    return EL.EventLedger(jsonl=tmp_path / "ev.jsonl", index=tmp_path / "i.db")


def clean_rows(k=5):
    """完全健康的一條線。沒有任何一輪造成後果。"""
    return [{"n": i, "goal": {"distance": 0.0}} for i in range(1, k + 1)]


def hurt_rows():
    """第 4 輪她出手糾正了。那是 OBSERVED 級的人力代價。"""
    rows = clean_rows(6)
    rows[3]["corrected_by_owner"] = True
    return rows


def fake_fork(*, dropped=17, kept=40, err=""):
    def _f(session, n, dry_run):
        if err:
            return {"error": err}
        return {"new_session_id": "new-sid", "kept": kept, "dropped": dropped,
                "at_line": 123, "dry_run": dry_run,
                "resume": "claude --resume new-sid"}
    return _f


# ---------------------------------------------------------------------------
# 一，不准猜
# ---------------------------------------------------------------------------

def test_沒有可回去的點就拒絕():
    p = R.plan(clean_rows(), session="s")
    assert p["can"] is False
    assert "back_to" not in p, "拒絕的時候不准順手給一個輪號"
    assert "標" in p["hint"], "要講怎麼樣才救得了，不是只說不行"


def test_空的線也拒絕():
    assert R.plan([], session="s")["can"] is False


def test_run_遇到算不出來的就不動手(led):
    called = []

    def spy(*a, **k):
        called.append(a)
        return {}

    out = R.run(clean_rows(), session="s", fork_fn=spy, ledger=led)
    assert out["ok"] is False
    assert called == [], "算不出來還去 fork，等於猜一個點"
    assert led.read_all() == [], "沒動手就不該留下事件"


# ---------------------------------------------------------------------------
# 二，兩個合法來源，沒有第三個
# ---------------------------------------------------------------------------

def test_用第一個造成後果的區段():
    p = R.plan(hurt_rows(), session="s")
    assert p["can"] is True
    assert p["back_to"] == 4
    assert p["source"] == "FIRST_CONSEQUENTIAL_DIVERGENCE"


def test_人標的優先於算出來的():
    cps = [{"id": "cp-x", "n": 2, "at": 100, "last_good": True}]
    p = R.plan(hurt_rows(), session="s", checkpoints=cps)
    assert p["back_to"] == 2, "有人標過就該聽人的"
    assert p["source"] == "OWNER_MARKED_CHECKPOINT"
    assert p["checkpoint_id"] == "cp-x"


def test_沒標記的checkpoint不算數():
    """最近的那一個常常正是出事的那一個。"""
    cps = [{"id": "cp-y", "n": 5, "at": 999, "last_good": False}]
    p = R.plan(hurt_rows(), session="s", checkpoints=cps)
    assert p["back_to"] == 4, "沒標 last_good 的不准拿來當回去的點"
    assert p["source"] == "FIRST_CONSEQUENTIAL_DIVERGENCE"


def test_來源只有兩種():
    assert len(R.SOURCES) == 2


# ---------------------------------------------------------------------------
# 三，排除了什麼要寫得出來
# ---------------------------------------------------------------------------

def test_算得出排除的範圍():
    p = R.plan(hurt_rows(), session="s")
    assert p["quarantined"] == (4, 6)
    assert p["turns_excluded"] == 3


def test_丟掉幾個節點用forkline的數字不自己算(led):
    out = R.run(hurt_rows(), session="s", fork_fn=fake_fork(dropped=17),
                ledger=led)
    assert out["excluded_nodes"] == 17, "這個數字只能來自 forkline"


# ---------------------------------------------------------------------------
# 四，帳本
# ---------------------------------------------------------------------------

def test_寫三筆事件而且共用同一個incident(led):
    out = R.run(hurt_rows(), session="s", fork_fn=fake_fork(), ledger=led)
    assert out["ok"] is True
    recs = led.read_all()
    assert len(recs) == 3
    types = [r["norm"]["type"] for r in recs]
    assert types == ["INCIDENT_OPEN", "CHECKPOINT", "CLEAN_FORK"]
    iids = {r["norm"]["metadata"]["incident"] for r in recs}
    assert iids == {out["incident"]}, "三筆要串得起來，不然查不出是同一次救援"


def test_事件型別都是規格裡的():
    for t in R.EVENT_TYPES:
        assert t in EL.TYPE_TO_CATEGORY
        assert EL.TYPE_TO_CATEGORY[t] == "Recovery"
        assert EL.spec_source(t) == "v5.0 §6.2"


def test_fork失敗不算成功而且看得見走到哪(led):
    out = R.run(hurt_rows(), session="s", fork_fn=fake_fork(err="找不到"),
                ledger=led)
    assert out["ok"] is False
    assert "找不到" in out["why"]
    types = [r["norm"]["type"] for r in led.read_all()]
    assert "CLEAN_FORK" not in types, "沒 fork 成功就不准寫 CLEAN_FORK"
    assert types == ["INCIDENT_OPEN", "CHECKPOINT"]


def test_history從帳本重組得出來(led):
    out = R.run(hurt_rows(), session="s", fork_fn=fake_fork(), ledger=led)
    h = R.history(ledger=led)
    assert h["total"] == 1
    assert h["complete"] == 1
    inc = h["incidents"][0]
    assert inc["incident"] == out["incident"]
    assert len(inc["steps"]) == 3


def test_沒走完的救援看得見(led):
    R.run(hurt_rows(), session="s", fork_fn=fake_fork(err="炸了"), ledger=led)
    h = R.history(ledger=led)
    assert h["complete"] == 0
    assert "CLEAN_FORK" in h["incidents"][0]["stopped_at"]


def test_history認session(led):
    R.run(hurt_rows(), session="a", fork_fn=fake_fork(), ledger=led)
    assert R.history(ledger=led, session="b")["total"] == 0
    assert R.history(ledger=led, session="a")["total"] == 1


# ---------------------------------------------------------------------------
# 五，不可逆的動作預設不做
# ---------------------------------------------------------------------------

def test_預設是dry_run(led):
    seen = {}

    def spy(session, n, dry_run):
        seen["dry"] = dry_run
        return fake_fork()(session, n, dry_run)

    out = R.run(hurt_rows(), session="s", fork_fn=spy, ledger=led)
    assert seen["dry"] is True
    assert out["dry_run"] is True
    assert out["checkpoint"] is None, "dry-run 不該真的落 checkpoint"


def test_收據講得出憑據(led):
    out = R.run(hurt_rows(), session="s", fork_fn=fake_fork(), ledger=led)
    r = out["receipt"]
    assert "第 4 輪" in r
    assert "FIRST_CONSEQUENTIAL_DIVERGENCE" in r


def test_跟checkpoint模組挑的是同一筆(tmp_path):
    """兩邊各挑各的就會漂開，而漂開的那天沒有人會發現。"""
    import checkpoint as CP

    log = tmp_path / "cp.jsonl"
    CP.create(session="s", n=9, reason="OWNER_MARK", last_good=True,
              at=100, path=log)
    CP.create(session="s", n=2, reason="OWNER_MARK", last_good=True,
              at=200, path=log)
    cps = CP.load(session="s", path=log)

    p = R.plan(hurt_rows(), session="s", checkpoints=cps)
    assert p["checkpoint_id"] == CP.last_good("s", log)["id"]
    assert p["back_to"] == 2, "後標的那一筆贏，不是輪號大的那一筆贏"
