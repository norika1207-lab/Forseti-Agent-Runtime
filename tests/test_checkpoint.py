"""Checkpoint。v5.0 §17、§25、階段 5

**Python 端先前完全沒有這個東西**，而 `PHASE_STATUS.md` 把階段 5 叫
「Checkpoint 與 Fork」。只有 fork，checkpoint 一行都沒有。

這組守三件事：

一，**存的是 §25 那四樣。** 目標、已接受的決策、未解決的未知、
    最後已知良好狀態。少一樣，後繼者就答不出那一題。

二，**不存對話全文。** §3.2 的非目標明寫不把完整歷史對話倒進後繼
    session，而且全文本來就在 jsonl 裡。

三，**last_good 沒有就是沒有。** 不准退而求其次拿最近的那一個 ——
    最近的那一個常常正是出事的那一個。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import checkpoint as C  # noqa: E402


@pytest.fixture()
def log(tmp_path):
    return tmp_path / "cp.jsonl"


def test_理由只收白名單(log):
    r = C.create(session="s", n=1, reason="隨便填", path=log)
    assert r["ok"] is False
    assert "TASK_FINISHED" in r["why"]


def test_存的是規格要的四樣(log):
    r = C.create(session="s", n=3, reason="OWNER_MARK",
                 goal="G", decisions=["D"], unknowns=["U"], verified=["V"],
                 path=log)
    cp = r["checkpoint"]
    for k in ("goal", "decisions", "unknowns", "verified"):
        assert k in cp, f"§25 要求的 {k} 不見了"


def test_不存對話全文(log):
    """有人把 transcript 塞進來就是把 §3.2 的非目標推翻了。"""
    r = C.create(session="s", n=1, reason="OWNER_MARK", path=log)
    cp = r["checkpoint"]
    for bad in ("transcript", "rows", "messages", "text", "full"):
        assert bad not in cp, f"checkpoint 不該存 {bad}"


def test_沒有標記就沒有last_good(log):
    C.create(session="s", n=1, reason="OWNER_MARK", path=log)
    C.create(session="s", n=2, reason="TASK_FINISHED", path=log)
    assert C.last_good("s", log) is None, "系統不准自己挑最近的那一個"


def test_只回被明確標記的(log):
    C.create(session="s", n=1, reason="OWNER_MARK", last_good=True, path=log)
    C.create(session="s", n=9, reason="TASK_FINISHED", path=log)
    lg = C.last_good("s", log)
    assert lg is not None and lg["n"] == 1, "第 9 輪沒被標，不能拿它冒充"


def test_多個標記取最後一個(log):
    C.create(session="s", n=1, reason="OWNER_MARK", last_good=True, at=100, path=log)
    C.create(session="s", n=5, reason="OWNER_MARK", last_good=True, at=200, path=log)
    assert C.last_good("s", log)["n"] == 5


def test_session_隔離(log):
    C.create(session="a", n=1, reason="OWNER_MARK", last_good=True, path=log)
    assert C.last_good("b", log) is None


def test_摘要要說明為什麼沒有last_good(log):
    C.create(session="s", n=1, reason="OWNER_MARK", path=log)
    s = C.summary("s", log)
    assert s["last_good"] is None
    assert "最近的那一個常常正是出事的那一個" in s["why_no_last_good"]


def test_id_穩定而且不同筆不撞(log):
    a = C.create(session="s", n=1, reason="OWNER_MARK", at=1.0, path=log)["checkpoint"]
    b = C.create(session="s", n=2, reason="OWNER_MARK", at=2.0, path=log)["checkpoint"]
    assert a["id"] != b["id"]
    assert a["id"].startswith("cp-")


# ── 碟上別條 session 的那些（2026-09-17）──────────────────────────
#
# 起因是實測:`.forseti/checkpoints.jsonl` 有 3 筆、全部被人標成
# last_good、分屬兩條舊 session，而當下這條 session 是 0 筆。於是
# `summary()` 回的兩句話（total=0、「沒有任何 checkpoint 被標成
# last_good」）各自都對，合起來讀卻是「這台機器上完全沒有可以回去
# 的點」。這一組守的是**主詞要講出來**，以及**講事實不等於替人決定**。


def test_別條session的不併進total(log):
    C.create(session="舊", n=1, reason="OWNER_MARK", last_good=True, path=log)
    C.create(session="新", n=2, reason="HANDOFF", path=log)
    s = C.summary("新", log)
    assert s["total"] == 1, "total 只算這條線上的"
    assert s["elsewhere"]["total"] == 1
    assert s["elsewhere"]["last_good"] == 1
    assert s["elsewhere"]["sessions"] == 1


def test_沒有last_good那句話要有主詞(log):
    C.create(session="舊", n=1, reason="OWNER_MARK", last_good=True, path=log)
    s = C.summary("新", log)
    why = s["why_no_last_good"]
    assert "這條 session" in why, "沒有主詞的全稱否定正是那個誤導"
    assert "最近的那一個常常正是出事的那一個" in why, "原本的理由不准掉"
    assert "碟上另有 1 個" in why, "碟上有被標記的，事實要講出來"


def test_碟上沒有別的就不多講一句(log):
    C.create(session="新", n=1, reason="HANDOFF", path=log)
    s = C.summary("新", log)
    assert s["elsewhere"]["total"] == 0
    assert "碟上另有" not in s["why_no_last_good"], "沒有的東西不准提"


def test_講事實不等於跨session挑一個(log):
    C.create(session="舊", n=1, reason="OWNER_MARK", last_good=True, path=log)
    s = C.summary("新", log)
    # 這一條是政策，不是措辭：`last_good()` 絕不跨 session。
    assert C.last_good("新", log) is None
    assert s["last_good"] is None, "elsewhere 有值也不准補進 last_good"
