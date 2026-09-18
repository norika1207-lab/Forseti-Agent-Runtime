"""pol-bdfd4735df 的回歸探針。§40.2 要的「用來強制的偵測器」。

## 這條探針守的是哪一筆

登記簿 `pol-bdfd4735df`：

    原本的結論　`vitals.dimensions()` 已經逐輪算八個維度
    更正之後　　它只算當下一次，內部取最後 20 輪
                健康曲線是靠反覆餵前綴做出來的，不是讀現成的逐輪結果
    失敗機制　　把函式回傳的東西的形狀，當成它內部算過的東西的形狀。
                回傳八個維度不等於逐輪算過八個維度

## 為什麼 `test_vitals_curve.py` 攔不住它

那一組守的是「曲線上每一點只用那一輪為止的證據」（前綴等價）。
**前綴等價跟「內部有沒有逐輪算」是兩件事** —— 一個內部真的逐輪算的
`dimensions()` 也會通過那一組。所以那個錯誤結論當初可以跟整組綠燈
並存，而它確實並存過。這裡守的是那一組留下的那個洞。

## 三條各自否證原結論的哪一半

1. 視窗：第 21 輪以前對結果零影響（`vitals.py:214` 的 `rows[-20:]`）
2. 形狀：回的是一次結果，不是每輪一組
3. 曲線：`curve()` 靠反覆呼叫 `dimensions()` 餵前綴，不是讀現成的逐輪結果

第 3 條是攔截力最強的那一條，因為原結論真正錯的地方在那裡。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import vitals as V  # noqa: E402

#: 這條探針釘住的登記簿編號。改動這個檔之前先去讀那一筆。
POLLUTION_ID = "pol-bdfd4735df"


def row(n, *, failed=0, acts=2, corrected=False, betrayals=0,
        overclaims=0, stall=False):
    dots = [{"kind": "run", "failed": i < failed} for i in range(acts)]
    return {"n": n, "dots": dots, "owner_text": "",
            "corrected_by_owner": corrected, "nudge_by_owner": False,
            "betrayals": [{"x": 1}] * betrayals,
            "overclaims": [{"x": 1}] * overclaims,
            "stall": stall, "duration": 60.0}


SNAP = {"context": {"used_pct": 40, "compactions": 1},
        "ledger": {"age_hours": 2.0}}


def _disaster(n):
    """一輪「什麼都出事」的資料。用它當前綴才驗得出視窗真的把它切掉。"""
    return row(n, failed=2, acts=2, corrected=True,
               betrayals=3, overclaims=3, stall=True)


# ── 1 視窗 ────────────────────────────────────

def test_第二十一輪以前的資料對dimensions零影響():
    """前 40 輪全是災難，後 20 輪全乾淨，結果必須等於只餵後 20 輪。

    這條紅了代表視窗變了（或消失了），那筆污染的更正文字就要跟著改，
    不是把這條測試改綠。
    """
    tail = [row(40 + i) for i in range(20)]
    head = [_disaster(i) for i in range(40)]
    gs = V.goal_support(head + tail)

    full = V.dimensions(head + tail, SNAP, gs)
    only_tail = V.dimensions(tail, SNAP, gs)

    assert full == only_tail, "前 40 輪影響到了結果，`rows[-20:]` 那個視窗不在了"


def test_那四十輪前綴本身不是空的():
    """非空斷言。上面那條在兩邊都算不出東西的時候會無聲成立。"""
    head = [_disaster(i) for i in range(40)]
    gs = V.goal_support(head)
    d = V.dimensions(head, SNAP, gs)
    assert d["runtime"]["score"] is not None
    assert d["runtime"]["score"] > 0, "災難前綴算出來是 0，這組資料驗不到東西"


# ── 2 形狀 ────────────────────────────────────

def test_dimensions回的是一次結果不是每輪一組():
    """原結論錯在這裡：回傳八個維度，被讀成逐輪算過八個維度。

    每個維度底下是一組 score／coverage／evidence，
    **不是一個長度等於輪數的序列**。
    """
    rows = [row(i) for i in range(30)]
    gs = V.goal_support(rows)
    d = V.dimensions(rows, SNAP, gs)

    assert isinstance(d, dict)
    for k, v in d.items():
        assert isinstance(v, dict), f"{k} 不是單一結果"
        assert set(v) >= {"score", "coverage", "evidence"}, f"{k} 少了欄位"
        assert not isinstance(v["score"], (list, tuple)), \
            f"{k} 的 score 是序列，那才叫逐輪算"


# ── 3 曲線 ────────────────────────────────────

def test_曲線是反覆餵前綴算出來的_不是讀現成的逐輪結果(monkeypatch):
    """攔截力最強的一條。直接量 `curve()` 怎麼拿到每一點。

    餵進去的 rows 長度必須嚴格遞增（那就是「前綴」），
    而且呼叫次數要等於點數 —— 一次呼叫換一個點。
    讀現成逐輪結果的實作只會呼叫一次，那時這條會紅。
    """
    seen: list = []
    real = V.dimensions

    def spy(rows, snap, gs):
        seen.append(len(rows))
        return real(rows, snap, gs)

    monkeypatch.setattr(V, "dimensions", spy)

    rows = [row(i) for i in range(60)]
    gs = V.goal_support(rows)
    c = V.curve(rows, SNAP, gs, max_points=10)

    assert c["has"] is True
    assert len(seen) == len(c["points"]), \
        f"呼叫 {len(seen)} 次卻產出 {len(c['points'])} 個點，不是一次換一個點"
    assert seen == sorted(seen) and len(set(seen)) == len(seen), \
        f"餵進去的長度不是嚴格遞增：{seen}"
    assert seen[-1] == len(rows), "最後一次沒有餵到「現在」這一輪"


def test_登記簿裡那一筆還在而且指得回這個檔():
    """探針跟登記簿要互相指得到。那一筆被刪掉的話這條會紅。"""
    sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))
    import pollution

    rec = pollution.get(POLLUTION_ID)
    assert rec is not None, f"{POLLUTION_ID} 不在登記簿裡了"
    assert "dimensions" in (rec.get("original_claim") or "")
