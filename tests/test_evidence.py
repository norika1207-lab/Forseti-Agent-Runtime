"""證據強度與填空衝動。v5.0 §7.2、§8.3

§8.3 的禁止捷徑：

    UNKNOWN → UNSUPPORTED_FILL → ASSUMED_FACT → WRITE / COMMIT

**2026-09-16 當天犯過兩次。** `goalgate.scope_match` 那個因子規格沒有
定義怎麼算，先用關鍵字比對，再用檔案路徑，兩次都誤判。兩次都是同一條鏈：
不知道怎麼算，想出一個貌似合理的算法，當成可用的數字，拿去算 GAC。

那兩個數字的問題不是不準，是它們長得跟量出來的一模一樣。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import evidence as E  # noqa: E402


def test_證據強度的順序不可以改():
    order = [k for k, _, _ in E.LEVELS]
    assert order == ["E0", "E1", "E2", "E3", "E4"]
    assert E.weight("E0") < E.weight("E1") < E.weight("E2") < E.weight("E4")


def test_弱的不准冒充強的():
    assert E.can_support(claim_level="E2", evidence_level="E0")["ok"] is False
    assert E.can_support(claim_level="E4", evidence_level="E2")["ok"] is False


def test_同級或更強可以():
    assert E.can_support(claim_level="E1", evidence_level="E1")["ok"] is True
    assert E.can_support(claim_level="E1", evidence_level="E4")["ok"] is True


def test_不認得的等級不准放行():
    """不認得就是不認得，不准當成最低或最高。"""
    assert E.can_support(claim_level="E9", evidence_level="E4")["ok"] is False


def test_禁止捷徑要被抓到():
    r = E.check_chain([{"state": "UNKNOWN"},
                       {"state": "ASSUMED_FACT"},
                       {"state": "DECISION"}])
    assert r["ok"] is False
    assert len(r["violations"]) >= 2


def test_正確的鏈要通過():
    r = E.check_chain([{"state": "UNKNOWN"}, {"state": "SEARCHED"},
                       {"state": "HYPOTHESIS"}, {"state": "EVIDENCE"},
                       {"state": "DECISION"}])
    assert r["ok"] is True


def test_假設直接跳到決定要被抓():
    """少了 EVIDENCE 那一格。這是最像正常流程的一種捷徑。"""
    r = E.check_chain([{"state": "HYPOTHESIS"}, {"state": "DECISION"}])
    assert r["ok"] is False


def test_說不出來源的數字一律判成填空():
    """不是因為它一定錯，是因為它跟量出來的長得一模一樣。"""
    r = E.gap_fill(0.833, source="")
    assert r["is_fill"] is True
    assert r["level"] == "E0"


def test_推估的可以用但不准假裝是量出來的():
    r = E.gap_fill(40, source="ESTIMATED", derivation="半衰期猜的")
    assert r["is_fill"] is True
    assert r["level"] == "E0"
    assert "不准當成量出來的" in r["why"]


def test_量出來的跟定義的不算填空():
    assert E.gap_fill(26, source="MEASURED")["is_fill"] is False
    assert E.gap_fill(1.0, source="DEFINED")["is_fill"] is False
    assert E.gap_fill(1.0, source="DEFINED")["level"] == "E4"


def test_今天那兩個誤判會被這一支擋下來():
    """回歸測試：關鍵字比對算出來的 0.833 說不出來源，判填空。"""
    keyword_based = E.gap_fill(0.833, source="")
    assert keyword_based["is_fill"] is True
    owner_decided = E.gap_fill(1.0, source="DEFINED",
                               derivation="owner 2026-09-15 拍板不用時間衰減")
    assert owner_decided["is_fill"] is False
