"""污染登記簿（v5.0 §40）。

2026-09-16 19:2x 加。起因是 `contract.py:847` 自己寫著這一句：

    "invalidated_conclusions": NoSource(
        "§40 的 PollutionRegistry 沒有實作"
        "（`grep -rn PollutionRecord apps/ src/` 零命中）"),

這一組守的是「規格的四個狀態與兩條進入條件」，不是「此刻登了幾筆」。
每一條都寫到臨時檔，不碰正本 `.forseti/pollution.jsonl` ——
正本的內容會變，規則不會。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import pollution  # noqa: E402


@pytest.fixture
def log(tmp_path):
    return tmp_path / "pollution.jsonl"


def 一筆(log, **kw):
    base = dict(
        original_claim="事件帳本裡有 lineage 邊",
        corrected_claim="LINEAGE_EDGES 只定義未實作",
        failure_mechanism="看到常數名稱就當成功能存在，沒有讀同檔的說明",
        source_events=["apps/forseti-cli/event_ledger.py:117"],
        verifier="auto-continue 2026-09-16",
        radius_basis="規格沒定義單位",
        path=log,
    )
    base.update(kw)
    return pollution.record(**base)


class Test必填:
    def test_沒有機制就不准登(self, log):
        r = 一筆(log, failure_mechanism="  ")
        assert r["ok"] is False
        assert "機制" in r["why"]

    def test_沒有出處就不准登(self, log):
        r = 一筆(log, source_events=[])
        assert r["ok"] is False
        assert "source_events" in r["why"]

    def test_空字串的出處不算出處(self, log):
        r = 一筆(log, source_events=["", "   "])
        assert r["ok"] is False

    def test_沒有驗證者就不准登(self, log):
        r = 一筆(log, verifier="")
        assert r["ok"] is False
        assert "verifier" in r["why"]

    def test_沒有更正後的說法就不准登(self, log):
        r = 一筆(log, corrected_claim="")
        assert r["ok"] is False

    def test_四個都有就寫得進去(self, log):
        r = 一筆(log)
        assert r["ok"] is True
        assert r["record"]["id"].startswith("pol-")
        assert log.exists()


class Test半徑:
    """規格沒定義單位，所以沒量到是 None 不是 0。"""

    def test_沒給半徑又不說為什麼就退回(self, log):
        r = 一筆(log, radius_basis="")
        assert r["ok"] is False
        assert "radius_basis" in r["why"]

    def test_沒量到是_None_不是_0(self, log):
        一筆(log)
        rec = pollution.records(log)[0]
        assert rec["propagation_radius"] is None
        assert rec["propagation_radius"] != 0

    def test_量得到就照實存(self, log):
        一筆(log, propagation_radius=3, radius_basis="下游三個結論")
        assert pollution.records(log)[0]["propagation_radius"] == 3

    def test_摘要把沒量到的筆數講出來(self, log):
        一筆(log)
        s = pollution.summary(log)
        assert s["radius_unknown"] == 1
        assert "None 不是 0" in s["radius_note"]


class Test狀態:
    def test_只認規格那四個(self, log):
        assert pollution.STATUSES == ("OPEN", "PARTIAL", "REVERIFIED", "RESOLVED")
        r = 一筆(log, status="CLOSED")
        assert r["ok"] is False

    def test_重驗要有驗證者(self, log):
        pid = 一筆(log)["record"]["id"]
        r = pollution.advance(pid, "REVERIFIED", path=log)
        assert r["ok"] is False
        assert "verifier" in r["why"]

    def test_有驗證者才過得去(self, log):
        pid = 一筆(log)["record"]["id"]
        r = pollution.advance(pid, "REVERIFIED", verifier="人", path=log)
        assert r["ok"] is True
        assert pollution.get(pid, log)["status"] == "REVERIFIED"

    def test_解決要有預防規則或回歸探針(self, log):
        pid = 一筆(log)["record"]["id"]
        pollution.advance(pid, "REVERIFIED", verifier="人", path=log)
        r = pollution.advance(pid, "RESOLVED", path=log)
        assert r["ok"] is False
        assert "§40.2" in r["why"]

    def test_有回歸探針就過得去(self, log):
        pid = 一筆(log)["record"]["id"]
        pollution.advance(pid, "REVERIFIED", verifier="人", path=log)
        r = pollution.advance(pid, "RESOLVED",
                              regression_probe="tests/test_x.py::test_y",
                              path=log)
        assert r["ok"] is True

    def test_不准從OPEN直接跳到RESOLVED(self, log):
        pid = 一筆(log)["record"]["id"]
        r = pollution.advance(pid, "RESOLVED",
                              regression_probe="tests/test_x.py", path=log)
        assert r["ok"] is False
        assert "不能直接到" in r["why"]

    def test_可以往回走(self, log):
        """重驗之後又發現沒好，要走得回去。"""
        pid = 一筆(log)["record"]["id"]
        pollution.advance(pid, "REVERIFIED", verifier="人", path=log)
        r = pollution.advance(pid, "OPEN", path=log)
        assert r["ok"] is True
        assert pollution.get(pid, log)["status"] == "OPEN"

    def test_轉到不存在的那一筆會講清楚(self, log):
        r = pollution.advance("pol-nope", "PARTIAL", path=log)
        assert r["ok"] is False
        assert "沒有這一筆" in r["why"]


class Test只增不改:
    def test_狀態轉換是追加不是改寫(self, log):
        pid = 一筆(log)["record"]["id"]
        pollution.advance(pid, "PARTIAL", path=log)
        raw = pollution.load(log)
        assert len(raw) == 2
        assert raw[0]["kind"] == "RECORD"
        assert raw[0]["status"] == "OPEN"   # 第一筆原封不動
        assert raw[1]["kind"] == "STATUS"

    def test_原始說法不會被後來的轉換蓋掉(self, log):
        pid = 一筆(log)["record"]["id"]
        pollution.advance(pid, "PARTIAL", note="改了一半", path=log)
        rec = pollution.get(pid, log)
        assert rec["original_claim"] == "事件帳本裡有 lineage 邊"
        assert rec["failure_mechanism"].startswith("看到常數名稱")

    def test_歷史留得住(self, log):
        pid = 一筆(log)["record"]["id"]
        pollution.advance(pid, "PARTIAL", path=log)
        pollution.advance(pid, "REVERIFIED", verifier="人", path=log)
        assert len(pollution.get(pid, log)["history"]) == 2

    def test_壞掉的行跳過不炸(self, log):
        一筆(log)
        with log.open("a", encoding="utf-8") as f:
            f.write("{ 這不是 json\n")
        assert len(pollution.records(log)) == 1


class Test交接欄位:
    def test_沒有檔案回空清單不炸(self, tmp_path):
        assert pollution.invalidated_conclusions(tmp_path / "無") == []

    def test_未解決的會帶進交接(self, log):
        一筆(log)
        out = pollution.invalidated_conclusions(log)
        assert len(out) == 1
        assert "事件帳本裡有 lineage 邊" in out[0]
        assert "機制" in out[0]

    def test_解決了就不再帶(self, log):
        pid = 一筆(log)["record"]["id"]
        pollution.advance(pid, "REVERIFIED", verifier="人", path=log)
        pollution.advance(pid, "RESOLVED", regression_probe="t.py", path=log)
        assert pollution.invalidated_conclusions(log) == []

    def test_重驗過但沒人攔它的還是要帶(self, log):
        """重驗不等於機制被擋住了。"""
        pid = 一筆(log)["record"]["id"]
        pollution.advance(pid, "REVERIFIED", verifier="人", path=log)
        assert len(pollution.invalidated_conclusions(log)) == 1


class Test識別:
    def test_同一個錯配同一個機制是同一筆(self, log):
        a = 一筆(log)["record"]["id"]
        b = 一筆(log)["record"]["id"]
        assert a == b

    def test_機制不同就是不同筆(self, log):
        a = 一筆(log)["record"]["id"]
        b = 一筆(log, failure_mechanism="另一個原因")["record"]["id"]
        assert a != b
