"""接手閘門。v5.0 §17.3

    A successor may be read-only until it demonstrates understanding.

**為什麼這一條可以硬擋。** `intervene.can_intervene` 的 `BLOCK_HIGH_RISK`
要的是「硬前提不明或被推翻」，而「接手的人沒證明自己讀懂規格」正是那個。
它跟「說了沒做」不同：後者是行為問題，人有正當理由停下來；
前者是狀態問題，沒讀懂就動手，之後每一步都建立在可能錯的前提上。

事故：B-14（2026-09-11 讀錯規格重做已完成階段）、
2026-09-16 早上（16 小時斷線後接手的 session 花一個上午重讀昨晚已記錄過的文件）。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import gate as G  # noqa: E402


@pytest.fixture()
def log(tmp_path):
    return tmp_path / "gate.jsonl"


def _qs():
    c = G.challenge()
    assert c["ok"], "出不了題，這組測試的前提就壞了"
    return c["questions"]


def test_題目來自原文不是自己編的():
    """一個 AI 自己出題自己改的閘門，等於沒有閘門。"""
    for q in _qs():
        assert q["line"] > 0, "每一題都要指得回原文的行號"
        assert q["file"], "每一題都要說出自哪份文件"
        assert q["_key"], "每一題都要有原文裡的答案"


def test_沒考過就是唯讀(log):
    st = G.status("never", path=log)
    assert st["writable"] is False
    assert st["reason"] == "NEVER_PASSED"


def test_答錯不給過(log):
    qs = _qs()
    r = G.judge(qs, ["不知道"] * len(qs), session="wrong", path=log)
    assert r["passed"] is False
    assert G.status("wrong", path=log)["writable"] is False


def test_不做語意相似度(log):
    """差不多對在規格這種東西上就是錯。"""
    qs = _qs()
    near = [f"大概是講{q['_key'][:2]}那件事" for q in qs]
    r = G.judge(qs, near, session="near", path=log)
    assert r["passed"] is False, "意思接近不算對"


def test_答對就給寫入權限(log):
    qs = _qs()
    r = G.judge(qs, [q["_key"] for q in qs], session="right", path=log)
    assert r["passed"] is True
    assert G.status("right", path=log)["writable"] is True


def test_門檻不是全對():
    """全對會讓抽到刁鑽題目的人卡死，而卡死的閘門會被拔掉。"""
    assert G.NEED < G.ASK


def test_文件改了通行證作廢(log, tmp_path, monkeypatch):
    qs = _qs()
    G.judge(qs, [q["_key"] for q in qs], session="s", path=log)
    assert G.status("s", path=log)["writable"] is True
    monkeypatch.setattr(G, "fingerprint", lambda: "different")
    st = G.status("s", path=log)
    assert st["writable"] is False
    assert st["reason"] == "DOCS_CHANGED"


def test_過期作廢(log):
    qs = _qs()
    G.judge(qs, [q["_key"] for q in qs], session="s", path=log)
    future = time.time() + (G.TTL_HOURS + 1) * 3600
    st = G.status("s", path=log, now=future)
    assert st["writable"] is False
    assert st["reason"] == "EXPIRED"


def test_必讀清單要短():
    """清單太長會讓閘門變成儀式，而儀式會被繞過。"""
    assert len(G.REQUIRED) <= 5


def test_session之間不共用通行證(log):
    qs = _qs()
    G.judge(qs, [q["_key"] for q in qs], session="a", path=log)
    assert G.status("a", path=log)["writable"] is True
    assert G.status("b", path=log)["writable"] is False
