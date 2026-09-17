"""派不動的原因怎麼分類。

2026-09-16 19:0x 加。起因是一句在畫面與 `.forseti/NEXT.md` 上
同時出現的假話：

    T-7da5ef2183：7 個步驟都不在可動狀態

實測那 7 個步驟全部是 VERIFIED_COMPLETE。任務不是卡住，是做完沒收尾。
`desktop_api` 把 `next_step()` 回 None 一律翻譯成「步驟不在可動狀態」，
於是兩種要人做相反動作的情況印成了同一句話。

這一組守的是**分類規則**，不是「此刻剛好有幾件」。
用假的步驟清單餵，不讀正本資料庫 —— 正本的狀態會變，規則不會。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import stuck  # noqa: E402


class FakeLed:
    """只實作 diagnose 用得到的兩個方法。"""

    def __init__(self, state, steps):
        self._state, self._steps = state, steps

    def state_of(self, task_id):
        return self._state

    def steps_of(self, task_id):
        return self._steps


def S(local, state, deps=(), task="T-x"):
    return {"step_id": f"{task}/{local}", "local_id": local,
            "state": state, "dependencies": list(deps)}


# ── 條款一：做完沒收尾，不准講成卡住 ────────────────────

def test_全部驗證完成報ALL_VERIFIED不是卡住():
    led = FakeLed("VERIFYING", [S("A", "VERIFIED_COMPLETE"),
                                S("B", "VERIFIED_COMPLETE", ["T-x/A"])])
    d = stuck.diagnose(led, "T-x")
    assert d["kind"] == "ALL_VERIFIED"
    assert d["action"] == "收尾"
    # 這一句是這整支模組存在的理由：不准出現「不在可動狀態」那種說法
    assert "不在可動狀態" not in d["headline"]
    assert "收尾" in d["headline"]


def test_ALL_VERIFIED不是永久卡住():
    # 它會解開，按一下收尾就解開。標成 permanent 會讓人以為要修什麼。
    led = FakeLed("VERIFYING", [S("A", "VERIFIED_COMPLETE")])
    assert stuck.diagnose(led, "T-x")["permanent"] is False


def test_line不加派不動三個字():
    led = FakeLed("VERIFYING", [S("A", "VERIFIED_COMPLETE")])
    assert "派不動" not in stuck.line(stuck.diagnose(led, "T-x"))


# ── 條款一的另一半：結束了但沒結好，跟結好了不一樣 ──────

def test_有步驟結在失敗要跟全部完成分開():
    led = FakeLed("VERIFYING", [S("A", "VERIFIED_COMPLETE"),
                                S("B", "FAILED_TERMINAL")])
    d = stuck.diagnose(led, "T-x")
    assert d["kind"] == "ENDED_NOT_COMPLETE"
    assert d["permanent"] is True
    assert d["unreachable"] == [{"step": "B", "state": "FAILED_TERMINAL"}]


# ── 條款一核心：永遠等不到 vs 正在等，不合併 ────────────

def test_依賴死在終局算等不到不算在等():
    led = FakeLed("VERIFYING", [S("A", "FAILED_TERMINAL"),
                                S("B", "RUNNING", ["T-x/A"])])
    d = stuck.diagnose(led, "T-x")
    assert d["kind"] == "DEPS_UNMET"
    assert d["permanent"] is True
    assert [r["why"] for r in d["unreachable"]] == ["dead"]
    assert d["waiting_on"] == []


def test_依賴還在跑算在等不算等不到():
    led = FakeLed("VERIFYING", [S("A", "RUNNING"),
                                S("B", "PROPOSED", ["T-x/A"])])
    d = stuck.diagnose(led, "T-x")
    assert d["kind"] == "DEPS_UNMET"
    assert d["permanent"] is False
    assert [r["why"] for r in d["waiting_on"]] == ["pending"]
    assert d["unreachable"] == []


def test_兩種同時存在時分開報():
    led = FakeLed("VERIFYING", [S("A", "FAILED_TERMINAL"),
                                S("B", "RUNNING"),
                                S("C", "PROPOSED", ["T-x/A", "T-x/B"])])
    d = stuck.diagnose(led, "T-x")
    assert len(d["unreachable"]) == 1 and len(d["waiting_on"]) == 1
    # 一句話裡兩個數字都要在，合成一個「2 個依賴沒滿足」就是這條在擋的
    assert "等不到" in d["headline"] and "還沒做完" in d["headline"]


# ── 條款二：回名單不回數字 ──────────────────────────

def test_回的是哪一步等哪一個不是幾個():
    led = FakeLed("VERIFYING", [S("A", "RUNNING"),
                                S("B", "PROPOSED", ["T-x/A"])])
    row = stuck.diagnose(led, "T-x")["waiting_on"][0]
    assert row["step"] == "B" and row["dep"] == "A"
    assert row["state"] == "RUNNING"


# ── 條款三：指到不存在的步驟，是資料壞了不是還沒好 ──────

def test_依賴指到不存在的步驟報missing且永久():
    led = FakeLed("VERIFYING", [S("B", "PROPOSED", ["T-x/打錯了"])])
    d = stuck.diagnose(led, "T-x")
    row = d["unreachable"][0]
    assert row["why"] == "missing"
    assert row["dep"] == "打錯了"
    assert d["permanent"] is True
    # 不准被歸到「在等」那一邊，那會讓人一直等一個不存在的東西
    assert d["waiting_on"] == []


# ── 環：互相等對方，永遠不會自己解開 ─────────────────

def test_互相依賴的環算等不到():
    led = FakeLed("VERIFYING", [S("A", "PROPOSED", ["T-x/B"]),
                                S("B", "PROPOSED", ["T-x/A"])])
    d = stuck.diagnose(led, "T-x")
    assert d["permanent"] is True
    assert any(r["why"] == "cycle" for r in d["unreachable"])


# ── 條款五：沒卡住就說沒卡住 ────────────────────────

def test_依賴都滿足時回NOT_STUCK不硬湊理由():
    led = FakeLed("VERIFYING", [S("A", "VERIFIED_COMPLETE"),
                                S("B", "PROPOSED", ["T-x/A"])])
    d = stuck.diagnose(led, "T-x")
    assert d["kind"] == "NOT_STUCK"
    assert d["unreachable"] == [] and d["waiting_on"] == []


# ── 其餘兩種基本情況 ───────────────────────────────

def test_沒有步驟時講的是還沒拆():
    d = stuck.diagnose(FakeLed("RUNNING", []), "T-x")
    assert d["kind"] == "NO_STEPS"
    assert "拆" in d["headline"]


def test_任務已終局不算卡住():
    led = FakeLed("VERIFIED_COMPLETE", [S("A", "PROPOSED")])
    d = stuck.diagnose(led, "T-x")
    assert d["kind"] == "TASK_TERMINAL"


# ── 條款四：算不出來要說少了什麼，不編一個原因 ──────────

class BrokenLed:
    def state_of(self, task_id):
        raise RuntimeError("資料庫鎖住")

    def steps_of(self, task_id):
        return []


def test_讀不到資料時回UNKNOWN並說少了什麼():
    d = stuck.diagnose(BrokenLed(), "T-x")
    assert d["kind"] == "UNKNOWN"
    assert d["missing"] and "RuntimeError" in d["missing"]
    # 不准編一個看起來合理的原因
    assert d["waiting_on"] == [] and d["unreachable"] == []


def test_每一種kind都在KINDS裡登記():
    # 回一個沒登記的 kind，畫面那邊就會靜靜地不認得它
    cases = [
        FakeLed("VERIFIED_COMPLETE", []),
        FakeLed("RUNNING", []),
        FakeLed("VERIFYING", [S("A", "VERIFIED_COMPLETE")]),
        FakeLed("VERIFYING", [S("A", "FAILED_TERMINAL")]),
        FakeLed("VERIFYING", [S("A", "RUNNING"), S("B", "PROPOSED", ["T-x/A"])]),
        FakeLed("VERIFYING", [S("A", "VERIFIED_COMPLETE"),
                              S("B", "PROPOSED", ["T-x/A"])]),
        BrokenLed(),
    ]
    for led in cases:
        assert stuck.diagnose(led, "T-x")["kind"] in stuck.KINDS
