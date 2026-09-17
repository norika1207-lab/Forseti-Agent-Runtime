"""Authority。v5.0 §9、§3.3、§7.1

四個連續性裡的第三個，先前 Python 端一行都沒有。

這組守的是四件會無聲出錯的事：

一，**信任階層的順序是 NORMATIVE。** 數字可以校準，誰比誰可信不行。
    順序被改掉的話，一個 agent 的推論可能排到擁有者前面。

二，**跨 commit 邊界的動作，即使是擁有者也只到 PREPARE。**
    準備跟提交是兩個權限等級（§9.1）。合成一個權限位元就是
    §26 第 5 條明令不准倒退的那一項。

三，**模型不能寫正典狀態。** §7.1：一個宣稱不會因為被重複就變成正典，
    重複增加的是社會共識，不是證據強度。

四，**這一層不擋一般動作。** §18 的預設姿態是 OBSERVE 99%。
    一個動不動就擋人的權限層，自己就是那個 1% 的濫用。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import authority as A  # noqa: E402


def test_信任階層的順序不可以改():
    order = [k for k, _, _ in A.TRUST]
    assert order[0] == "OWNER"
    assert order[-1] == "UNSUPPORTED"
    assert order.index("DETERMINISTIC_VERIFIER") < order.index("CANONICAL_STATE")
    assert order.index("CANONICAL_STATE") < order.index("TOOL_OUTPUT")
    assert order.index("TOOL_OUTPUT") < order.index("AGENT_INFERENCE")
    assert order.index("AGENT_INFERENCE") < order.index("HANDOFF_SUMMARY")
    assert order.index("HANDOFF_SUMMARY") < order.index("STALE_CACHE")


def test_不認得的來源排最後():
    assert A.rank("誰知道") == len(A.TRUST)
    assert A.weight("誰知道") == 0.0


def test_跨commit邊界即使擁有者也只到PREPARE():
    """準備跟提交是兩個權限等級。合成一個權限位元 = §26 第 5 條倒退。"""
    for act in A.COMMIT_BOUNDARY:
        d = A.decide(action=act, principal="OWNER")
        assert d["decision"] == "PREPARE", f"{act} 不該直接放行"
        assert d["can_execute"] is False
        assert d["required_confirmation"] == "OWNER"
        assert d["blocked_final_action"] == act


def test_擁有者可以寫正典狀態():
    for act in A.CANONICAL_WRITE:
        d = A.decide(action=act, principal="OWNER")
        assert d["decision"] == "ALLOW"
        assert d["can_execute"] is True


def test_模型不能寫正典狀態只能提議():
    for act in A.CANONICAL_WRITE:
        d = A.decide(action=act, principal="AGENT_INFERENCE")
        assert d["decision"] == "ASK"
        assert d["can_execute"] is False
        assert "提議" in d["reason"] or "擁有者" in d["reason"]


def test_一般動作不攔():
    d = A.decide(action="read", principal="AGENT_INFERENCE")
    assert d["decision"] == "ALLOW"
    assert d["risk"] == "ORDINARY"


def test_呼叫端說不可逆就要問():
    d = A.decide(action="whatever", principal="OWNER", reversible=False)
    assert d["decision"] == "ASK"
    assert d["can_execute"] is False


def test_PolicyDecision的欄位一個都不能少():
    """少一欄，呼叫端就會自己腦補那一欄的預設值。"""
    d = A.decide(action="finish", principal="OWNER")
    for k in ("intent", "risk", "decision", "can_execute",
              "allowed_preparation", "required_confirmation",
              "blocked_final_action", "reason", "source_policy_version"):
        assert k in d, f"§9.2 要求的 {k} 不見了"


def test_同一個來源重複宣告不算衝突():
    cs = A.collisions([
        {"resource": "X", "principal": "OWNER"},
        {"resource": "X", "principal": "OWNER"},
    ])
    assert cs == []


def test_不同來源競爭同一資源才是衝突():
    cs = A.collisions([
        {"resource": "X", "principal": "OWNER"},
        {"resource": "X", "principal": "AGENT_INFERENCE"},
    ])
    assert len(cs) == 1
    assert cs[0]["winner"] == "OWNER"
    assert cs[0]["losers"] == ["AGENT_INFERENCE"]


def test_衝突由信任階層裁不是由先後裁():
    """後寫的不會贏。先後順序不是權威。"""
    cs = A.collisions([
        {"resource": "X", "principal": "AGENT_INFERENCE", "at": 999},
        {"resource": "X", "principal": "CANONICAL_STATE", "at": 1},
    ])
    assert cs[0]["winner"] == "CANONICAL_STATE"


def test_升格正典只有前兩級有資格():
    assert A.may_promote("OWNER")["may_promote"] is True
    assert A.may_promote("DETERMINISTIC_VERIFIER")["may_promote"] is True
    for p in ("CANONICAL_STATE", "TOOL_OUTPUT", "AGENT_INFERENCE",
              "HANDOFF_SUMMARY", "STALE_CACHE", "UNSUPPORTED"):
        assert A.may_promote(p)["may_promote"] is False, f"{p} 不該能升格"


def test_重複不增加證據強度這句話要在輸出裡():
    """這是 §7.1 的核心，寫在註解裡會被改掉，寫在輸出裡改掉測試會紅。"""
    assert "社會共識" in A.may_promote("AGENT_INFERENCE")["note"]
