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


# ---------------------------------------------------------------------------
# Evidence 這個實體。2026-09-18
#
# 上面那幾條守的是分級與鏈結檢查，它們收字串、算完就沒了。
# 下面這一組守的是**一筆證據指不指得到**：有沒有 id、落不落得了地、
# §7.2 那幾級的定義有沒有變成會執行的約束。
#
# 這一組存在的理由是 `lineage.readiness()` 把 evidence 判成 NO_SOURCE，
# 而 §6.3 的 DERIVED_FROM / VERIFIES / REFUTES 三條邊因此連不起來。
# ---------------------------------------------------------------------------

import json          # noqa: E402
import time          # noqa: E402

import pytest        # noqa: E402


def _ok(**kw):
    """一筆最小的合法證據。每一條測試只改它要驗的那一欄。"""
    base = dict(about="ledger.py 有 append()", sources=["grep -n append"],
                strength="E1", captured_by="測試")
    base.update(kw)
    return base


def test_強度只認E0到E4(tmp_path):
    r = E.record(**_ok(strength="E9"), path=tmp_path / "e.jsonl")
    assert r["ok"] is False
    assert "§7.2" in r["why"]
    assert not (tmp_path / "e.jsonl").exists(), "被拒收的東西不可以落地"


def test_不知道在支撐什麼的證據要被退回(tmp_path):
    r = E.record(**_ok(about="   "), path=tmp_path / "e.jsonl")
    assert r["ok"] is False
    assert "about" in r["why"]


def test_沒有來源的證據要被退回(tmp_path):
    r = E.record(**_ok(sources=[]), path=tmp_path / "e.jsonl")
    assert r["ok"] is False


def test_空字串的來源不算來源(tmp_path):
    """`["", "  "]` 不是一個來源，是兩個空白。"""
    r = E.record(**_ok(sources=["", "  "]), path=tmp_path / "e.jsonl")
    assert r["ok"] is False


def test_說不出是誰觀察到的要被退回(tmp_path):
    r = E.record(**_ok(captured_by=""), path=tmp_path / "e.jsonl")
    assert r["ok"] is False


def test_E3只有一個來源要被退回(tmp_path):
    """§7.2 原文：independent corroboration from multiple deterministic
    sources。一個來源的東西不是 E3，不論它多確定。"""
    r = E.record(**_ok(strength="E3", sources=["git diff"],
                       independence_basis="兩支獨立的指令"),
                 path=tmp_path / "e.jsonl")
    assert r["ok"] is False
    assert "多個決定性來源" in r["why"]


def test_E3說不出憑什麼算獨立要被退回(tmp_path):
    """§33.3：共用上游前提的兩個指標是同一個錯誤被數兩次。

    這一條是 `feedback_false_corroboration` 那件事的機制形式。
    """
    r = E.record(**_ok(strength="E3", sources=["a", "b"]),
                 path=tmp_path / "e.jsonl")
    assert r["ok"] is False
    assert "§33.3" in r["why"]


def test_E4沒有具名授權方要被退回(tmp_path):
    """§7.2 的 E4 是 owner 確認、簽署的政策、或外部的真實系統。
    三種都有一個具名的授權方。"""
    r = E.record(**_ok(strength="E4"), path=tmp_path / "e.jsonl")
    assert r["ok"] is False
    assert "authority" in r["why"]


def test_合法的E3與E4收得下來(tmp_path):
    p = tmp_path / "e.jsonl"
    assert E.record(**_ok(strength="E3", sources=["stat", "git diff"],
                          independence_basis="一個問檔案系統一個問 git"),
                    path=p)["ok"] is True
    assert E.record(**_ok(strength="E4", authority="owner 2026-09-18"),
                    path=p)["ok"] is True
    assert len(E.load(p)) == 2


def test_登記之後指得到(tmp_path):
    p = tmp_path / "e.jsonl"
    r = E.record(**_ok(), path=p)
    assert r["ok"] is True
    eid = r["evidence"]["id"]
    assert eid.startswith("ev-")
    got = E.get(eid, path=p)
    assert got is not None and got["about"] == "ledger.py 有 append()"
    assert E.get("ev-不存在", path=p) is None


def test_同一刻的同一個觀察是同一個id():
    a = E.Evidence(about="x", sources=("s",), strength="E1",
                   captured_by="t", observed_at=1000.0)
    b = E.Evidence(about="x", sources=("s",), strength="E1",
                   captured_by="t", observed_at=1000.0)
    assert a.id == b.id


def test_不同時刻看同一個東西是兩筆不是一筆():
    """§10 的 freshness 對它們的答案不一樣，所以它們不是同一筆。"""
    a = E.Evidence(about="x", sources=("s",), strength="E1",
                   captured_by="t", observed_at=1000.0)
    b = E.Evidence(about="x", sources=("s",), strength="E1",
                   captured_by="t", observed_at=2000.0)
    assert a.id != b.id


def test_登好的證據改不動():
    """事後改證據等於改歷史，而下游的邊會指向一個已經不是當初那筆的東西。"""
    ev = E.Evidence(about="x", sources=("s",), strength="E1", captured_by="t")
    with pytest.raises(Exception):
        ev.strength = "E4"


def test_落地的是一行json(tmp_path):
    p = tmp_path / "e.jsonl"
    E.record(**_ok(), path=p)
    line = p.read_text(encoding="utf-8").strip()
    row = json.loads(line)
    assert set(row) >= {"id", "about", "sources", "strength", "captured_by",
                        "content_hash", "upstream", "observed_at"}


# ------------------------------------------------------------ §10 freshness

def test_沒有雜湊的時候飄移是量不到不是沒飄():
    """**這一條是這一組裡最重要的。** `None` 跟 `False` 合成一個的話，
    「沒飄」跟「不知道有沒有飄」會長得一樣，而處置完全不同。"""
    row = E.Evidence(about="x", sources=("s",), strength="E1",
                     captured_by="t", observed_at=100.0).to_row()
    f = E.freshness(row, now=160.0)
    assert f["drift"] is None
    assert "不是沒飄" in f["why"]
    assert f["age_seconds"] == pytest.approx(60.0)


def test_有雜湊而且對不上就是飄了():
    row = E.Evidence(about="x", sources=("s",), strength="E2",
                     captured_by="t", content_hash="aaa").to_row()
    assert E.freshness(row, current_hash="bbb")["drift"] is True
    assert E.freshness(row, current_hash="aaa")["drift"] is False


def test_有雜湊但沒給現在的值也是量不到():
    row = E.Evidence(about="x", sources=("s",), strength="E2",
                     captured_by="t", content_hash="aaa").to_row()
    assert E.freshness(row)["drift"] is None


# --------------------------------------------------------- §33.3 獨立性

def _row(eid_seed: float, upstream=()):
    return E.Evidence(about="x", sources=("s",), strength="E1",
                      captured_by="t", observed_at=eid_seed,
                      upstream=tuple(upstream)).to_row()


def test_共用上游的兩筆算一個獨立支撐():
    r = E.independence([_row(1.0, ["dataset-A"]), _row(2.0, ["dataset-A"])])
    assert r["raw_support_count"] == 2
    assert r["independent_support_count"] == 1
    assert r["shared_assumption"] == ["dataset-A"]
    assert r["confirmation_discount"] is True


def test_真的不同上游才算兩個獨立支撐():
    r = E.independence([_row(1.0, ["dataset-A"]), _row(2.0, ["dataset-B"])])
    assert r["independent_support_count"] == 2
    assert r["shared_assumption"] == []
    assert r["confirmation_discount"] is False


def test_沒登記上游的不准算成獨立():
    """把「不知道上游」當成「沒有共用上游」正是 §8.3 的填空，
    而它會讓獨立支撐數看起來比實際多。"""
    r = E.independence([_row(1.0), _row(2.0)])
    assert r["independent_support_count"] == 0
    assert len(r["unknown_ancestry"]) == 2
    assert r["confirmation_discount"] is True


def test_上游只重疊一半也算同一群():
    """A 跟 B 共用 P，B 跟 C 共用 Q，三筆是一群不是兩群。"""
    r = E.independence([_row(1.0, ["P"]), _row(2.0, ["P", "Q"]),
                        _row(3.0, ["Q"])])
    assert r["independent_support_count"] == 1
    assert set(r["shared_assumption"]) == {"P", "Q"}


# ------------------------------------------------------------ 磁碟與 doctor

def test_零筆的時候也印而且講得出擋住什麼(tmp_path):
    out = E.lines(tmp_path)
    assert any("0 筆" in ln for ln in out)
    assert any("VERIFIES" in ln for ln in out)


def test_有筆數之後印各強度(tmp_path):
    (tmp_path / ".forseti").mkdir()
    p = E.log_path(tmp_path)
    E.record(**_ok(strength="E1"), path=p)
    E.record(**_ok(strength="E2", observed_at=time.time() + 1), path=p)
    s = E.store_summary(tmp_path)
    assert s["count"] == 2 and s["addressable"] is True
    assert s["by_strength"] == {"E1": 1, "E2": 1}
    assert any("E1 1" in ln for ln in E.lines(tmp_path))


def test_預設位置在控制目錄底下():
    assert E.log_path().name == "evidence.jsonl"
    assert E.log_path().parent.name == ".forseti"


# ------------------------------------------------- 跟 lineage 的接縫

def test_lineage看得到實體但零筆不准說成指得到(tmp_path):
    """**這一條守的是這一輪最容易犯的錯。**

    實體與儲存做好了，`NO_SOURCE` 會消失 —— 但磁碟上零筆的時候
    那三條邊仍然連不起來。把「模組在了」讀成「證據在了」，
    就是 2026-09-18 07:xx 那一筆污染（`pol-ce2f84f5b5`）的同一個形狀。
    """
    import lineage

    (tmp_path / ".forseti").mkdir()
    k = lineage.kinds(tmp_path)["evidence"]
    assert k["status"] == "NO_INSTANCES", k
    assert k["n"] == 0

    E.record(**_ok(), path=E.log_path(tmp_path))
    k2 = lineage.kinds(tmp_path)["evidence"]
    assert k2["status"] == "ADDRESSABLE"
    assert k2["n"] == 1
    assert str(k2["example"]).startswith("ev-")
