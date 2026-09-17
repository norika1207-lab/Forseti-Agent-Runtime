"""修正延遲。白皮書 §5.4

**這組測試是為了一個差點上線的說謊指標寫的。**

2026-09-16：第一版用 `corrected_by_owner` 判「誰把偏離拉回來」，
而那個旗標走詞表。實測這條線上三段偏離，全部判成「AI 自己回到中軸」。

真相是：第 229 輪她說「我決定全部刪除掉了」、第 287 輪她在貼終端輸出
替我跑指令、第 337 輪前後都是 Request interrupted。

**一個說謊的指標比沒有指標更糟**，因為它會讓人停止懷疑 ——
而它說的謊剛好是「它自己會回到正軌，沒麻煩到人」。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import latency as L  # noqa: E402
import vitals as V  # noqa: E402


def row(n, *, dist=0.0, dur=60.0, owner="", corrected=False):
    return {"n": n, "goal": {"distance": dist}, "duration": dur,
            "owner_text": owner, "corrected_by_owner": corrected}


# ── 三種 OBSERVED 訊號 ────────────────────────────────

def test_打斷是系統寫的不是猜的():
    assert V.is_interrupt("[Request interrupted by user]")
    assert V.is_interrupt("[Request interrupted by user for tool use]")
    assert not V.is_interrupt("我要打斷你")


def test_貼終端輸出算她替我跑指令():
    assert V.is_operator("norikaoda@NorikadeMacBook-Pro ~ % ls ~/.forseti")
    assert V.is_operator("zsh: command not found: foo")
    assert not V.is_operator("你去跑那個指令")


def test_出手的三種方式各自分得出來():
    assert V.owner_stepped_in(row(1, owner="[Request interrupted by user]")) == "INTERRUPTED"
    assert V.owner_stepped_in(row(1, owner="a@b ~ % ls")) == "OPERATED"
    assert V.owner_stepped_in(row(1, owner="你又搞錯了")) == "CORRECTED"
    assert V.owner_stepped_in(row(1, owner="繼續")) == ""


# ── 偏離段落 ──────────────────────────────────────────

def test_沒偏離就沒有段落():
    assert L.summary([row(i) for i in range(1, 5)])["has"] is False


def test_一段偏離要有起訖():
    rows = [row(1), row(2, dist=0.5), row(3, dist=0.5), row(4)]
    e = L.episodes(rows)[0]
    assert e["from_n"] == 2 and e["to_n"] == 4
    assert e["turns"] == 3


def test_她替我跑指令要算成她出手():
    """第 287 輪的真實情況。舊版判 SELF_RECOVERED。"""
    rows = [row(1), row(2, dist=0.5),
            row(3, dist=0.5, owner="norikaoda@Mac ~ % ls"), row(4)]
    e = L.episodes(rows)[0]
    assert e["recovery"] == "OWNER_CORRECTION"
    assert e["recovered_by"] == "她替我跑指令"


def test_她按打斷要算成她出手():
    """第 337 輪的真實情況。舊版判 SELF_RECOVERED。"""
    rows = [row(1), row(2, dist=0.5),
            row(3, dist=0.5, owner="[Request interrupted by user]"), row(4)]
    assert L.episodes(rows)[0]["recovery"] == "OWNER_CORRECTION"


def test_往前看三輪因為出手常落在偏離尾巴():
    rows = [row(1), row(2, dist=0.5, owner="你又搞錯了"),
            row(3, dist=0.5), row(4, dist=0.5), row(5)]
    assert L.episodes(rows)[0]["recovery"] == "OWNER_CORRECTION"


def test_沒回來的要標還開著():
    rows = [row(1), row(2, dist=0.5), row(3, dist=0.5)]
    e = L.episodes(rows)[0]
    assert e["still_open"] is True
    assert e["recovery"] == "STILL_OPEN"


# ── 分布不是平均 ──────────────────────────────────────

def test_用中位數與最壞值不用平均():
    """平均會把一次 32 輪的災難跟七次一輪的小偏離抹平成同一個數字。"""
    s = L.summary([row(1), row(2, dist=0.5), row(3)])
    assert "median_turns" in s and "p90_turns" in s and "worst" in s
    assert "mean" not in s and "average" not in s


def test_兩把尺都要有():
    """只看輪數會把「五輪各三十秒」跟「五輪各二十分鐘」算成一樣。"""
    e = L.episodes([row(1), row(2, dist=0.5, dur=600.0), row(3)])[0]
    assert e["turns"] > 0 and e["minutes"] > 0


def test_不確定度要跟數字一起端出去():
    """漏抓的方向一律是把她的出手算成我自己回來的，那件事要講。"""
    s = L.summary([row(1), row(2, dist=0.5), row(3)])
    assert "上限不是事實" in s["caveat"]
