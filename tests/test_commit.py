"""Two-Phase Agent Commit。v5.0 §9.3、§26 第 5 條

§26 那十條「不准倒退」裡的第 5 條是這個模組存在的唯一理由：

    絕不把準備與不可逆提交合併成單一權限位元。

合併之後會發生的事:一個有權限「做這件事」的東西，自動就有權限
「做完這件事」。而真實世界裡這兩者差了幾個數量級 ——
把信寫好跟把信寄出去，差別在於後者收不回來。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import commit as C  # noqa: E402


@pytest.fixture()
def log(tmp_path):
    return tmp_path / "commits.jsonl"


def _to_approval(log, kind="deploy", subject="x"):
    tx = C.open_tx(kind=kind, subject=subject, path=log)["tx"]
    C.advance(tx, "PREPARING", cause="開始", path=log)
    C.advance(tx, "PREPARED", cause="好了", external_ref="ref-1", path=log)
    C.advance(tx, "AWAITING_APPROVAL", cause="等人按", path=log)
    return tx


def test_一律從DRAFT開始沒有捷徑(log):
    assert C.open_tx(kind="send", subject="信", path=log)["state"] == "DRAFT"


def test_不准跳格(log):
    tx = C.open_tx(kind="send", subject="信", path=log)["tx"]
    with pytest.raises(C.CommitError) as e:
        C.advance(tx, "COMMITTED", actor="OWNER", cause="跳過", path=log)
    assert "不能直接到" in str(e.value)


def test_沒有cause不准轉(log):
    tx = C.open_tx(kind="send", subject="信", path=log)["tx"]
    with pytest.raises(C.CommitError) as e:
        C.advance(tx, "PREPARING", cause="   ", path=log)
    assert "cause" in str(e.value)


def test_只有OWNER能跨commit邊界(log):
    """這條紅了就是 §26 第 5 條倒退了。"""
    tx = _to_approval(log)
    for who in ("agent", "worker", "DETERMINISTIC_VERIFIER", "CANONICAL_STATE"):
        with pytest.raises(C.CommitError) as e:
            C.advance(tx, "COMMITTED", actor=who, cause="我來", path=log)
        assert "OWNER" in str(e.value)
    assert C.advance(tx, "COMMITTED", actor="OWNER",
                     cause="她按了", path=log)["state"] == "COMMITTED"


def test_COMMITTED只能從AWAITING_APPROVAL來(log):
    """那一格就是人按下去的那一刻。跳過它 = 兩個權限等級合成一個。"""
    assert C.ALLOWED["PREPARED"] == ("AWAITING_APPROVAL", "CANCELLED")
    assert "COMMITTED" not in C.ALLOWED["PREPARED"]
    assert C.ALLOWED["AWAITING_APPROVAL"] == ("COMMITTED", "CANCELLED")


def test_要提交就得有external_ref(log):
    """沒有它就找不到那個東西在哪，之後想 rollback 也沒得 rollback。"""
    tx = C.open_tx(kind="send", subject="信", path=log)["tx"]
    C.advance(tx, "PREPARING", cause="開始", path=log)
    C.advance(tx, "PREPARED", cause="草稿好了", path=log)   # 刻意不給 ref
    C.advance(tx, "AWAITING_APPROVAL", cause="等人按", path=log)
    with pytest.raises(C.CommitError) as e:
        C.advance(tx, "COMMITTED", actor="OWNER", cause="送", path=log)
    assert "external_ref" in str(e.value)


def test_終局狀態不能再轉(log):
    tx = C.open_tx(kind="send", subject="信", path=log)["tx"]
    C.advance(tx, "CANCELLED", cause="不做了", path=log)
    with pytest.raises(C.CommitError):
        C.advance(tx, "PREPARING", cause="又想做", path=log)


def test_已提交的可以rollback(log):
    tx = _to_approval(log)
    C.advance(tx, "COMMITTED", actor="OWNER", cause="按了", path=log)
    assert C.advance(tx, "ROLLED_BACK", actor="OWNER",
                     cause="出事了", path=log)["state"] == "ROLLED_BACK"


def test_停在半路的要看得出在等什麼(log):
    """一個停在 PREPARED 的東西跟一個沒開始的東西，畫面上必須有差別。"""
    _to_approval(log, kind="deploy", subject="A")
    tx2 = C.open_tx(kind="send", subject="B", path=log)["tx"]
    C.advance(tx2, "PREPARING", cause="寫草稿", path=log)
    p = {e["subject"]: e for e in C.pending(log)}
    assert p["A"]["waiting_for"] == "你按下去"
    assert p["B"]["waiting_for"] == "還在準備"


def test_提交完就不算停在半路(log):
    tx = _to_approval(log)
    C.advance(tx, "COMMITTED", actor="OWNER", cause="按了", path=log)
    assert C.pending(log) == []
    assert C.summary(log)["committed"] == 1


def test_狀態機沒有多餘的路():
    """每一格的出口都要是刻意的。多一條就是多一個繞過人的方法。"""
    for s, outs in C.ALLOWED.items():
        for o in outs:
            assert o in C.STATES, f"{s} 指向不存在的狀態 {o}"
    assert C.ALLOWED["CANCELLED"] == ()
    assert C.ALLOWED["ROLLED_BACK"] == ()
