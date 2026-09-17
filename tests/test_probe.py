"""Reliability Probe Packs（v5.0 §15）。

這組測試防的是一個「看起來有在量、其實什麼都沒量」的 probe pack。

一包全綠的 probe pack 是最有說服力的假證據，所以這裡每一條問的都是:
這張綠表底下有沒有真的東西。

五個最容易造假的地方，各有一條釘住:

    一，沒有 verifier 的類別不准算進通過率（一格綠燈比一句「沒資料」好看）
    二，verifier 自己炸掉要判 REGRESSED，不准判 PASS
    三，觀測值跟基準線不一樣就是退化，不管契約有沒有過
    四，run() 不准順手更新基準線（自動更新的基準線等於沒有基準線）
    五，跨不了的那兩軸要跟著每一次輸出走，不准只寫在註解裡

另外有一組反向驗證（`test_反向_*`）：把被測模組真的弄壞，
對應那一項一定要變成 REGRESSED。一條抓不到退化的回歸測試，
跟沒有那條測試是同一件事。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import probe as P  # noqa: E402


# --- schema 與涵蓋範圍 ------------------------------------------------------

def test_schema欄位照規格十一個一字不差():
    """§15.1 的 ProbeScenario 十一個欄位。多一個少一個都是改規格。"""
    want = ["id", "domain", "risk_class", "setup", "prompt",
            "expected_contract", "verifier", "prohibited_shortcuts",
            "model_matrix", "baseline", "tags"]
    got = list(P.ProbeScenario.__dataclass_fields__)
    assert got == want


def test_十個必測類別一個都沒少而且順序照原文():
    c = P._check_pack_covers_spec()
    assert c["ok"], f"缺 {c['missing']}，多 {c['extra']}"
    assert len(P.REQUIRED_CLASSES) == 10


def test_每個情境都講得出禁止的捷徑():
    """`prohibited_shortcuts` 是規格欄位，空的等於這個情境沒想清楚。"""
    for s in P.PACK:
        assert s.prohibited_shortcuts, f"{s.id} 沒寫禁止的捷徑"
        assert all(x.strip() for x in s.prohibited_shortcuts)


# --- 不准把沒量的算成量過的 ------------------------------------------------

def test_沒有verifier的不算進通過率():
    r = P.run(compare=False)
    assert r["counts"]["NO_VERIFIER"] >= 1
    assert r["measurable"] == len(r["results"]) - r["counts"]["NO_VERIFIER"]
    # 通過率的分母不含那一格
    assert r["pass_rate"] == round(
        r["counts"]["PASS"] / r["measurable"], 3)


def test_沒有verifier的狀態不是PASS而且說得出為什麼():
    r = P.run(compare=False)
    rows = [x for x in r["results"] if x["state"] == "NO_VERIFIER"]
    assert rows
    for x in rows:
        assert x["ok"] is None
        assert len(x["why"]) > 20, "要說出缺什麼，不是一句沒有"


def test_跨不了的那兩軸每一次輸出都帶著():
    r = P.run(compare=False)
    assert r["axes_missing"] == ["models", "contexts"]
    assert r["axes_covered"] == ["versions"]
    assert r["axes_why"]
    assert P.summary()["axes_missing"] == ["models", "contexts"]


def test_每個情境的model_matrix只有一格而且標明是程式碼():
    """填成多格就是在說它跨了模型，而它沒有。"""
    for s in P.PACK:
        assert s.model_matrix == ("code@REPO",)


# --- 基準線 ----------------------------------------------------------------

def test_基準線沒有留下是誰按的就不准寫(tmp_path):
    with pytest.raises(P.ProbeError):
        P.record_baseline([], path=tmp_path / "b.json", by="")
    assert not (tmp_path / "b.json").exists()


def test_run不會順手更新基準線(tmp_path):
    p = tmp_path / "b.json"
    P.run(baseline_path=p)
    assert not p.exists(), "run() 寫了基準線。自動更新的基準線等於沒有"


def test_基準線不存沒有verifier的那幾項(tmp_path):
    p = tmp_path / "b.json"
    P.record_baseline(path=p, by="測試")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "fastpath_routing" not in data["scenarios"]
    assert data["by"] == "測試"


def test_有基準線而且一致才算PASS(tmp_path):
    p = tmp_path / "b.json"
    first = P.run(compare=False)
    P.record_baseline(first["results"], path=p, by="測試")
    again = P.run(baseline_path=p)
    states = {x["id"]: x["state"] for x in again["results"]}
    assert states["multi_agent_consensus"] == "PASS"
    assert again["counts"]["NEW"] == 0
    assert again["has_baseline"] is True


def test_沒有基準線的時候是NEW不是PASS(tmp_path):
    r = P.run(baseline_path=tmp_path / "nope.json")
    assert r["counts"]["NEW"] == r["measurable"]
    assert r["counts"]["PASS"] == 0


def test_觀測值變了就算契約還過得去也判退化(tmp_path):
    """這是整包最重要的一條:判準悄悄變寬，契約照樣綠。"""
    p = tmp_path / "b.json"
    first = P.run(compare=False)
    fake = [dict(x) for x in first["results"]]
    for x in fake:
        if x["id"] == "topology_sot" and isinstance(x["observed"], dict):
            x["observed"] = {**x["observed"], "rows": x["observed"]["rows"] + 99}
    P.record_baseline(fake, path=p, by="測試")
    again = P.run(baseline_path=p)
    row = [x for x in again["results"] if x["id"] == "topology_sot"][0]
    assert row["ok"] is True, "契約本身還是過的"
    assert row["state"] == "REGRESSED"
    assert "rows" in row["changed"]


# --- verifier 本身 ---------------------------------------------------------

def test_每個有verifier的情境現在都滿足契約():
    r = P.run(compare=False)
    bad = [(x["id"], x["why"], x.get("error"))
           for x in r["results"]
           if x["state"] != "NO_VERIFIER" and not x["ok"]]
    assert not bad, f"這幾項沒過：{bad}"


def test_verifier炸掉判退化不判通過(monkeypatch):
    def boom():
        raise RuntimeError("故意的")
    monkeypatch.setitem(P.VERIFIERS, "topology_sot", boom)
    r = P.run(compare=False, only="topology_sot")
    row = r["results"][0]
    assert row["state"] == "REGRESSED"
    assert row["ok"] is False
    assert "RuntimeError" in (row["error"] or "")


def test_observed可以序列化(tmp_path):
    """存不進 json 的觀測值，下一次就比不了。"""
    r = P.run(compare=False)
    for x in r["results"]:
        json.dumps(x["observed"], ensure_ascii=False)


# --- 反向驗證。把被測的東西弄壞，對應那一項一定要紅 -------------------------

def test_反向_證據等級的守備放寬會被抓到(monkeypatch):
    import evidence as EV
    monkeypatch.setattr(EV, "can_support",
                        lambda **k: {"ok": True, "gap": 0,
                                     "claim": k.get("claim_level"),
                                     "evidence": k.get("evidence_level"),
                                     "why": "放行"})
    r = P.run(compare=False, only="claim_evidence_honesty")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_重複次數開始影響強度會被抓到(monkeypatch):
    import claims as CL

    def leaky(self, by=""):
        self.repeats += 1
        if by and by not in self.said_by:
            self.said_by.append(by)
        if self.repeats >= 3:          # 講三次就升一級
            self.strength = "E2"
    monkeypatch.setattr(CL.Claim, "repeat", leaky)
    r = P.run(compare=False, only="multi_agent_consensus")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_agent按得下不可逆提交會被抓到(monkeypatch):
    import commit as CM
    monkeypatch.setattr(CM, "COMMIT_PRINCIPAL", "agent")
    r = P.run(compare=False, only="authority_commit")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_同一個人重複宣告被算成衝突會被抓到(monkeypatch):
    """淹掉真衝突的那種壞法，跟漏掉衝突一樣嚴重。"""
    import authority as AU
    real = AU.collisions

    def noisy(claims):
        out = list(real(claims))
        out.append({"resource": "other.json", "principals": ["agent"],
                    "winner": "agent", "winner_reason": "", "losers": [],
                    "count": 2, "why_it_matters": ""})
        return out
    monkeypatch.setattr(AU, "collisions", noisy)
    r = P.run(compare=False, only="authority_commit")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_自己說自己懂就給第六級會被抓到(monkeypatch):
    import rehydration as RH
    monkeypatch.setattr(RH, "coverage_of",
                        lambda **k: "VERIFIED_UNDERSTANDING")
    r = P.run(compare=False, only="reconstruction")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_空輸出被併進提早收工會被抓到(monkeypatch):
    import yieldcheck as YC
    real = YC.judge

    def merged(**k):
        out = real(**k)
        if out["verdict"] == "BLOCKED":
            out = {**out, "verdict": "PREMATURE"}
        return out
    monkeypatch.setattr(YC, "judge", merged)
    r = P.run(compare=False, only="tool_loop_blank_output")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_只用時間長短判停滯會被抓到(monkeypatch):
    """把煞車拔掉:不預期有產物的時候也照樣算停滯。"""
    import watchdog as WD
    real = WD.assess
    monkeypatch.setattr(
        WD, "assess",
        lambda **k: real(**{**k, "expected_to_progress": True}))
    r = P.run(compare=False, only="tool_loop_blank_output")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_舊版北極星被刪掉會被抓到(monkeypatch):
    import northstar as NS
    monkeypatch.setattr(NS.Chain, "at_version",
                        lambda self, v: None)
    r = P.run(compare=False, only="goal_persistence")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_過期的北極星不再被標成過期會被抓到(monkeypatch):
    import northstar as NS
    monkeypatch.setattr(NS.Chain, "is_stale", lambda self, v: False)
    r = P.run(compare=False, only="stale_cache")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_freshness不說是誰決定的會被抓到(monkeypatch):
    import goalgate as GG
    monkeypatch.setattr(GG, "freshness",
                        lambda t, **k: {"value": 1.0, "mode": "x"})
    r = P.run(compare=False, only="stale_cache")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_壓縮改掉任務狀態不再被抓會被抓到(monkeypatch):
    import rehydration as RH
    monkeypatch.setattr(RH.CompressionBoundary, "task_state_intact",
                        property(lambda self: True))
    r = P.run(compare=False, only="handoff_sufficiency")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_上界標記變成可以關掉會被抓到(monkeypatch):
    import rehydration as RH
    real = RH.coverage_report

    def off(**k):
        return {**real(**k), "is_upper_bound": False}
    monkeypatch.setattr(RH, "coverage_report", off)
    r = P.run(compare=False, only="handoff_sufficiency")
    assert r["results"][0]["state"] == "REGRESSED"


def test_反向_登記的原文不見了會被抓到(monkeypatch):
    import sot as ST
    real = ST.verify_bindings
    monkeypatch.setattr(ST, "verify_bindings",
                        lambda repo=None: {**real(repo), "stale": 3})
    r = P.run(compare=False, only="topology_sot")
    assert r["results"][0]["state"] == "REGRESSED"
