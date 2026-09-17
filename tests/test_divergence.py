"""第一個分歧點。v5.0 §16.4、§6.3、FS-DRF-004

§6.3 的標題就是這組測試的主軸：**不可假裝只有一個精確點。**

實測（2026-09-16，180 輪真實資料）：三種分歧點散在第 195 到 207 輪，
差 12 輪。只報一個的話，回答的是哪一題就變成看運氣。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import divergence as D  # noqa: E402


def row(n, *, dist=0.0, failed=0, betrayals=None, overclaims=None,
        corrected=False, compaction=False, write=0):
    return {"n": n, "goal": {"distance": dist}, "failed": failed,
            "betrayals": betrayals or [], "overclaims": overclaims or [],
            "corrected_by_owner": corrected, "compaction": compaction,
            "write": write}


def test_沒有資料就說沒有():
    assert D.find([])["has"] is False


def test_乾淨的一段沒有分歧點():
    rows = [row(i) for i in range(1, 6)]
    assert D.find(rows)["has"] is False


def test_三種都回範圍不回單點():
    """FS-DRF-004：證據不足以定位單一 turn 就要回範圍。"""
    rows = [row(1), row(2, dist=0.5, failed=1, corrected=True), row(3)]
    f = D.find(rows)
    for k in ("earliest_suspicious", "earliest_confirmed", "first_consequential"):
        v = f[k]
        assert isinstance(v, tuple) and len(v) == 2, f"{k} 應該是範圍"


def test_確認需要兩個獨立維度():
    """§6.2：至少兩個獨立證據維度。單一種類只算可疑不算確認。"""
    only_drift = [row(1), row(2, dist=0.5), row(3)]
    f = D.find(only_drift)
    assert f["earliest_suspicious"] is not None
    assert f["earliest_confirmed"] is None, "只有一種問題不該算確認"

    two = [row(1), row(2, dist=0.5, failed=1), row(3)]
    assert D.find(two)["earliest_confirmed"] is not None


def test_距離變大不算後果():
    """距離是徵狀不是後果。把徵狀算成後果，
    First Consequential 會一路往前跑到最早那一輪。"""
    rows = [row(1), row(2, dist=0.9), row(3, dist=0.9)]
    f = D.find(rows)
    assert f["earliest_suspicious"] is not None
    assert f["first_consequential"] is None, "只有距離大不算造成後果"


def test_她出手糾正算後果():
    rows = [row(1), row(2, dist=0.2, corrected=True)]
    f = D.find(rows)
    assert f["first_consequential"] is not None
    assert "糾正" in f["consequential_why"]


def test_白點後面有寫入才算後果():
    """白點本身是宣稱錯了，後面真的寫下去才是代價。"""
    no_write = [row(1), row(2, betrayals=[{"x": 1}]), row(3)]
    assert D.find(no_write)["first_consequential"] is None

    with_write = [row(1), row(2, betrayals=[{"x": 1}]), row(3, write=2)]
    f = D.find(with_write)
    assert f["first_consequential"] is not None
    assert "寫入" in f["consequential_why"]


def test_fork基準用造成後果的不用最早警訊():
    """最早的警訊常常是誤報。回太早會把好的工作一起丟掉。"""
    rows = [row(1), row(2, dist=0.5), row(3), row(4),
            row(5, dist=0.5, corrected=True)]
    f = D.find(rows)
    assert f["earliest_suspicious"][0] == 2
    assert f["fork_before"] == 5, "要回到造成後果那一段之前，不是第一個警訊"


def test_沒有後果就沒有要回去的點():
    rows = [row(1), row(2, dist=0.5)]
    f = D.find(rows)
    assert f["fork_before"] is None
    assert "沒有需要回去的點" in f["fork_why"]


def test_範圍要往前擴到連續異常的開頭():
    """第一個被偵測到的輪，跟事情開始的輪，常常不是同一輪。"""
    rows = [row(1), row(2, dist=0.5), row(3, dist=0.5, failed=1), row(4)]
    f = D.find(rows)
    assert f["earliest_confirmed"][0] == 2, "要往前擴到異常開始那一輪"
    assert f["earliest_confirmed"][1] == 3


def test_三種落在不同輪時要講出差距():
    rows = [row(1), row(2, dist=0.5), row(3), row(4), row(5),
            row(6, dist=0.5, failed=1, corrected=True)]
    f = D.find(rows)
    assert "spread" in f
    assert "看運氣" in f["spread_note"]
