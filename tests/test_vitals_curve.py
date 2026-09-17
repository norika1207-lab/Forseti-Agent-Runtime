"""Health Curve。§16.1 八視圖之一。

**這組測試防的是一條好看但說謊的線。**

逐輪重算體溫的時候，八個維度裡有兩個(脈絡、連續性)的來源是
`snap` 那一刻的快照，不是那一輪的歷史。如果照樣算進去，
整條線會被同一個常數平移，看起來像歷史其實不是。

所以這裡每一條測試問的都是同一個問題：
**這條線上的每一點，是不是真的只用那一輪為止的證據算出來的。**
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import vitals as V  # noqa: E402


def row(n, *, failed=0, acts=2, corrected=False, betrayals=0,
        overclaims=0, stall=False, owner=""):
    dots = [{"kind": "run", "failed": i < failed} for i in range(acts)]
    return {"n": n, "dots": dots, "owner_text": owner,
            "corrected_by_owner": corrected, "nudge_by_owner": False,
            "betrayals": [{"x": 1}] * betrayals,
            "overclaims": [{"x": 1}] * overclaims,
            "stall": stall, "duration": 60.0}


SNAP = {"context": {"used_pct": 40, "compactions": 1},
        "ledger": {"age_hours": 2.0}}


def build(rows):
    gs = V.goal_support(rows)
    for r, g in zip(rows, gs):
        r["goal"] = g
    return rows, gs


# ── 算不出來就說算不出來 ────────────────────────────

def test_輪數不足不畫線也不補點():
    rows, gs = build([row(i) for i in range(V.CURVE_MIN - 1)])
    c = V.curve(rows, SNAP, gs)
    assert c["has"] is False
    assert c["points"] == []
    assert str(V.CURVE_MIN) in c["why"]


def test_剛好到最小輪數就有點():
    rows, gs = build([row(i) for i in range(V.CURVE_MIN)])
    c = V.curve(rows, SNAP, gs)
    assert c["has"] is True
    assert len(c["points"]) >= 1


# ── 兩個快照維度不准混進歷史 ──────────────────────────

def test_脈絡與連續性被排除在曲線之外():
    rows, gs = build([row(i) for i in range(40)])
    c = V.curve(rows, SNAP, gs)
    assert set(c["excluded"]) == {"context", "continuity"}


def test_曲線覆蓋率低於當前溫度而且不裝作一樣():
    """排掉兩維之後 coverage 一定比全維度低。這不是缺陷，是誠實。"""
    rows, gs = build([row(i) for i in range(40)])
    dims = V.dimensions(rows, SNAP, gs)
    now = V.temperature(dims)
    c = V.curve(rows, SNAP, gs)
    assert now["coverage"] > 0
    assert c["last"]["coverage"] < now["coverage"]


def test_換掉快照裡的脈絡與帳本曲線一點都不動():
    """如果曲線真的沒用到那兩維，改 snap 不該影響任何一點。

    這條是排除清單真正的驗收：不是看欄位寫了什麼，是看數字動不動。
    """
    rows, gs = build([row(i) for i in range(40)])
    a = V.curve(rows, SNAP, gs)
    other = {"context": {"used_pct": 99, "compactions": 9},
             "ledger": {"age_hours": 240.0}}
    b = V.curve(rows, other, gs)
    assert [p["t"] for p in a["points"]] == [p["t"] for p in b["points"]]


# ── 線要真的隨輪次動 ──────────────────────────────

def test_前面健康後面出事線要往上走():
    good = [row(i) for i in range(30)]
    bad = [row(30 + i, failed=2, corrected=True, betrayals=1,
               overclaims=1, stall=True, owner="你又漏掉了")
           for i in range(30)]
    rows, gs = build(good + bad)
    c = V.curve(rows, SNAP, gs)
    assert c["has"] is True
    assert c["last"]["t"] > c["first"]["t"], c
    assert c["delta"] > 0


def test_每一點只看到那一輪為止的證據():
    """把災難放在最後面，第一個點不該先知道。

    等價的做法是拿前綴單獨算一次，兩邊必須完全一樣。
    """
    good = [row(i) for i in range(30)]
    bad = [row(30 + i, failed=2, corrected=True, betrayals=2)
           for i in range(30)]
    rows, gs = build(good + bad)
    c = V.curve(rows, SNAP, gs)
    p = c["points"][0]
    head, head_gs = build([row(i) for i in range(p["i"] + 1)])
    dims = V.dimensions(head, SNAP, head_gs)
    for k in V.CURVE_EXCLUDED:
        dims[k] = {"score": None, "coverage": 0.0, "evidence": ""}
    assert V.temperature(dims)["c"] == p["t"]


# ── 取樣 ────────────────────────────────────

def test_點數有上限而且最後一輪一定在線上():
    rows, gs = build([row(i) for i in range(300)])
    c = V.curve(rows, SNAP, gs, max_points=20)
    assert len(c["points"]) <= 20
    assert c["points"][-1]["i"] == 299
    assert c["last"]["n"] == 299


def test_取樣切點不重複且遞增():
    idx = V._curve_idx(327, 60)
    assert idx == sorted(set(idx))
    assert idx[-1] == 326


# ── 退化起點 ────────────────────────────────

def test_一路下降就沒有退化起點():
    bad = [row(i, failed=2, corrected=True, betrayals=2) for i in range(30)]
    good = [row(30 + i) for i in range(30)]
    rows, gs = build(bad + good)
    c = V.curve(rows, SNAP, gs)
    assert c["last"]["t"] < c["first"]["t"]
    assert c["rising_since"] is None


def test_退化起點指得回一個真的輪號():
    good = [row(i) for i in range(30)]
    bad = [row(30 + i, failed=2, corrected=True, betrayals=1, stall=True)
           for i in range(30)]
    rows, gs = build(good + bad)
    c = V.curve(rows, SNAP, gs)
    rs = c["rising_since"]
    assert rs is not None
    assert rs["rise"] > 0
    assert rs["from"]["n"] in [p["n"] for p in c["points"]]
    assert rs["from"]["t"] <= c["last"]["t"]


def test_退化起點的定義照著點的順序走得回去():
    """不相信回傳值，自己照定義再走一次。"""
    good = [row(i) for i in range(20)]
    bad = [row(20 + i, failed=2, corrected=True, overclaims=1)
           for i in range(40)]
    rows, gs = build(good + bad)
    pts = V.curve(rows, SNAP, gs)["points"]
    j = len(pts) - 1
    while j > 0 and pts[j - 1]["t"] <= pts[j]["t"]:
        j -= 1
    rs = V._rising_since(pts)
    if j == len(pts) - 1:
        assert rs is None
    else:
        assert rs["from"]["i"] == pts[j]["i"]
        assert rs["points"] == len(pts) - j


# ── 最高溫 ──────────────────────────────────

def test_最高溫那一點真的是最高的():
    import random
    random.seed(7)
    rows = [row(i, failed=random.randint(0, 2), corrected=random.random() < .3,
                betrayals=random.randint(0, 1)) for i in range(80)]
    rows, gs = build(rows)
    c = V.curve(rows, SNAP, gs)
    assert c["hottest"]["t"] == max(p["t"] for p in c["points"])
