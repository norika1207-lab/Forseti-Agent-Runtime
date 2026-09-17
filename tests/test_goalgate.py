"""GAC 閘門。§28.6 / FS-GOL-001

這組測試守的是三件會無聲出錯的事：

一，缺因子不准當成 1。`goalanchor.js` 明令少一個因子就算不出來，
    把缺的當 1 會讓 GAC 憑空變高，而 GAC 高就更敢出 CONFIRMED。

二，算不出來不等於低。NO_VALID_GOAL_ANCHOR 跟「GAC 0.3」是兩件事，
    前者是沒有參考系，後者是有參考系但很弱。

三，**過了 GAC 這一關不准直接升級成 CONFIRMED。** §6.2 的 CONFIRMED
    還有四條，一條都沒實作。一個「過一關就放行」的閘門比沒有閘門危險。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import goalgate as G  # noqa: E402
import vitals as VT  # noqa: E402


def test_非目標清單從檔案讀不是寫死的():
    ng = G.non_goals()
    assert len(ng) >= 5
    assert any("Claude Code" in g for g in ng)


def test_非目標檔案不存在時回空不當機():
    assert G.non_goals(Path("/tmp/絕不存在的北極星.md")) == []


def test_scope_match一律回None因為規格沒定義():
    """2026-09-15 兩種判法都誤判，所以退回不給值。

    守的是最重要的一條:**不准再憑空給這一項一個數字。**
    給了之後它會長得跟量出來的一模一樣，而且會直接影響 GAC。
    """
    for acts in ([], ["讀檔案，寫測試"], ["我要做一個取代 Claude Code 的東西"]):
        assert G.scope_match(acts)["value"] is None


def test_提到非目標只算弱訊號不進分母():
    """「提到」跟「在做」是兩件事。

    誤判現場:當天在讀 GitNexus 的 README，滿篇 Claude Code，
    舊版判成「在做取代 Claude Code 的事」，GAC 從 0.83 掉到 0.69。
    """
    r = G.scope_match(["我要做一個取代 Claude Code、Codex 的東西"])
    assert r["mentions"], "字眼還是要抓得到"
    assert r["value"] is None, "但不准因此給分"


def test_兩次誤判要留在程式碼裡():
    """記錄失敗過的判法，下一個人才不會再寫一次同樣的東西。"""
    assert len(G.scope_match([])["tried"]) >= 2


def test_開頭虛詞不准貪婪吃掉實詞():
    """`^不\\w{0,2}` 會把「不把完整」切成「整」，切壞就比不到。

    這條守的是 mentions 的抓取，不是 scope_match 的分數。
    """
    r = G.scope_match(["把完整歷史對話倒進每個後繼 session"])
    assert r["mentions"], "切壞 key 會漏抓弱訊號"


def test_provenance有已知缺口就扣分且列得出來():
    r = G.provenance_integrity()
    assert r["value"] is not None and r["value"] < 1.0
    assert len(r["gaps"]) >= 1


def test_owner拍板之後缺口要真的少一個():
    """2026-09-15 owner 拍板單向，那條就不再是未決分歧。

    守的是反向:不准有人把已經拍板的事情又加回未決清單，
    那會讓 GAC 無聲地降下來。
    """
    gaps = " ".join(G.provenance_integrity()["gaps"])
    assert "雙向" not in gaps, "單向已由 owner 2026-09-15 拍板"


def test_freshness不用時間衰減且指得出是誰決定的():
    """owner 2026-09-15:「freshness 不用時間衰減」。

    **1.0 一定要帶 decided_by。** 一個寫死 1.0 而說不出為什麼的因子，
    跟「把缺的因子當成 1」在資料上長得一模一樣，而後者是
    goalanchor.js 明令禁止的。
    """
    r = G.freshness(10)
    assert r["value"] == 1.0
    assert r["decided_by"]
    assert r["mode"] == "NO_TIME_DECAY"


def test_freshness不隨輪數下降():
    assert G.freshness(1)["value"] == G.freshness(500)["value"] == 1.0


def test_freshness候選曲線要明說未校準():
    r = G.freshness(0, enable_candidate=True)
    assert r["value"] == 1.0
    assert r.get("candidate") is True


def test_候選曲線關閉時turns仍要帶出去():
    """算不出值不代表沒資訊。距上次指令幾輪本身是可查證的事實。"""
    assert G.freshness(7)["turns_since"] == 7


# ── drift_alerts 的閘門行為 ──────────────────────────────

def _run(gate):
    """造一段符合三條件的偏離：連續多輪沒糾正、距離超標且上升。"""
    rows = []
    for i in range(8):
        rows.append({
            "n": i,
            "corrected_by_owner": False,
            "goal": {"distance": 0.20 + i * 0.05, "coverage": 0.8},
        })
    return VT.drift_alerts(rows, gate)


def test_沒接gate時照實說沒接():
    a = _run(None)
    assert a, "這段資料應該要觸發 SUSPECTED"
    assert any("沒有接上" in e for e in a[-1]["excluded"])


def test_gac算不出來時要指名缺哪個因子():
    gate = {"ok": True, "gac": None, "may_confirm_drift": False,
            "missing_factors": [{"factor": "freshness", "why": ""}],
            "thresholds_uncalibrated": True}
    a = _run(gate)
    assert any("freshness" in e for e in a[-1]["excluded"])


def test_gac未達門檻時要寫出實際數值():
    gate = {"ok": True, "gac": 0.42, "may_confirm_drift": False,
            "missing_factors": [], "thresholds_uncalibrated": True}
    a = _run(gate)
    assert any("0.42" in e for e in a[-1]["excluded"])


def test_gac過門檻也不准出CONFIRMED():
    """最重要的一條。§6.2 另外四條沒實作，過一關不等於放行。"""
    gate = {"ok": True, "gac": 0.95, "may_confirm_drift": True,
            "missing_factors": [], "thresholds_uncalibrated": True}
    a = _run(gate)
    assert a[-1]["state"] == "SUSPECTED_DRIFT"
    assert any("仍不出 CONFIRMED" in e for e in a[-1]["excluded"])


def test_每筆都要帶goal_anchor_ref():
    """FS-DRF-001 要求 drift classifier 一定要輸出 goal_anchor_ref。"""
    gate = {"ok": True, "gac": None, "may_confirm_drift": False,
            "goal_state": "NO_VALID_GOAL_ANCHOR", "missing_factors": [],
            "thresholds_uncalibrated": True}
    a = _run(gate)
    assert a[-1]["goal_anchor_ref"] == "NO_VALID_GOAL_ANCHOR"


def test_gate跑不起來時不准靜默當成通過():
    gate = {"ok": False, "gac": None, "may_confirm_drift": False,
            "note": "找不到 node"}
    a = _run(gate)
    assert a[-1]["state"] == "SUSPECTED_DRIFT"
    assert any("跑不起來" in e for e in a[-1]["excluded"])


def test_門檻未校準要講出來():
    gate = {"ok": True, "gac": 0.9, "may_confirm_drift": True,
            "missing_factors": [], "thresholds_uncalibrated": True}
    a = _run(gate)
    assert any("未經真實語料校準" in e for e in a[-1]["excluded"])


# ── 真的去跑 goalanchor.js ───────────────────────────────

@pytest.mark.skipif(G.node_bin() is None, reason="這台沒有 node")
def test_缺因子時js端回算不出來而不是低分():
    r = G.gac([{"source": "OWNER_CONFIRMED_NORTH_STAR",
                "freshness": None, "scopeMatch": 1.0,
                "provenanceIntegrity": 1.0}])
    assert r["ok"] is True
    assert r["gac"] is None
    assert r["goal_state"] == "NO_VALID_GOAL_ANCHOR"
    assert r["may_confirm_drift"] is False


@pytest.mark.skipif(G.node_bin() is None, reason="這台沒有 node")
def test_兩份弱來源不會疊成一份強來源():
    """GAC 取 max 不是加總。這是 js 那份的規則，這裡守住它別被改掉。"""
    weak = {"source": "HANDOFF_SUMMARY", "freshness": 1.0,
            "scopeMatch": 1.0, "provenanceIntegrity": 1.0}
    r = G.gac([dict(weak), dict(weak)])
    assert r["gac"] == pytest.approx(0.55, abs=0.001)


@pytest.mark.skipif(G.node_bin() is None, reason="這台沒有 node")
def test_門檻由js那份決定confirmed要080():
    r = G.gac([{"source": "EXPLICIT_OWNER_INSTRUCTION", "freshness": 1.0,
                "scopeMatch": 1.0, "provenanceIntegrity": 1.0}])
    assert r["gac"] == pytest.approx(1.0)
    assert r["may_confirm_drift"] is True
    r2 = G.gac([{"source": "HANDOFF_SUMMARY", "freshness": 1.0,
                 "scopeMatch": 1.0, "provenanceIntegrity": 1.0}])
    assert r2["may_confirm_drift"] is False      # 0.55 < 0.80
    assert r2["may_suspect_drift"] is False      # 0.55 < 0.60
