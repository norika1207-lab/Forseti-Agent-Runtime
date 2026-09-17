"""粉紅點。§5.5 唯一由使用者寫進系統的證據。

守三件事：

一，**只增不改。** 寫下去的當下就是證據，事後改掉就不是了。
    所以這個模組沒有 update 也沒有 delete，測試守住它不要被加上去。

二，**等級不准被降。** `HUMAN_ADJUDICATION` 高過任何 deterministic
    check —— 那些驗的是「事情有沒有發生」，她寫的是「這件事重不重要」，
    後者沒有演算法算得出來。

三，**session 要隔離。** 輪號是每條線各自從 1 數的，
    混在一起會把別人的注記掛到這條線上。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import notes as N  # noqa: E402


@pytest.fixture()
def log(tmp_path):
    return tmp_path / "notes.jsonl"


def test_空的不寫(log):
    r = N.add("   ", session="s", n=1, path=log)
    assert r["ok"] is False
    assert not log.exists() or log.read_text(encoding="utf-8") == ""


def test_太長的不寫(log):
    r = N.add("x" * (N.MAX_CHARS + 1), session="s", n=1, path=log)
    assert r["ok"] is False
    assert str(N.MAX_CHARS) in r["why"]


def test_寫進去的等級是人類裁決(log):
    r = N.add("這一輪的判斷很重要", session="s", n=7, path=log)
    assert r["ok"] is True
    assert r["note"]["provenance"] == "HUMAN_ADJUDICATION"


def test_只增不改沒有刪除也沒有修改():
    """有人加了 update/delete 就是把證據變成可竄改的東西。"""
    for forbidden in ("update", "delete", "edit", "remove"):
        assert not hasattr(N, forbidden), f"notes 不該有 {forbidden}"


def test_session_隔離(log):
    N.add("A 線的", session="a", n=1, path=log)
    N.add("B 線的", session="b", n=1, path=log)
    assert len(N.load(session="a", path=log)) == 1
    assert N.load(session="a", path=log)[0]["text"] == "A 線的"


def test_by_turn_掛在對的輪上(log):
    N.add("第三輪", session="s", n=3, path=log)
    N.add("第三輪再一則", session="s", n=3, path=log)
    N.add("第九輪", session="s", n=9, path=log)
    by = N.by_turn("s", log)
    assert sorted(by) == [3, 9]
    assert len(by[3]) == 2


def test_壞掉的行不會炸掉整份(log):
    N.add("好的", session="s", n=1, path=log)
    with log.open("a", encoding="utf-8") as f:
        f.write("這行不是 json\n")
    assert len(N.load(session="s", path=log)) == 1


def test_摘要要講清楚它不能被拿去推論(log):
    N.add("重要", session="s", n=2, path=log)
    s = N.summary("s", log)
    assert s["total"] == 1
    assert s["provenance"] == "HUMAN_ADJUDICATION"
    assert "不能拿它去推論她沒說的事" in s["note"]
