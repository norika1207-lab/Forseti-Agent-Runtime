"""反錨定接手協議的中間四步。v5.0 §39

這組守六件事：

一，**沒交推導不准揭曉。** §39 的順序是第 4 步在第 5 步之前。
    允許先看再推導的話，前面四步做得再完整都只是流程表演，
    所以這一條是整組最重要的一條。

二，**推導只能交一次。** 揭曉之後還能改答案，等於看完答案再抄。

三，**兩邊都空不算一致。** 正典空、受測者交白卷，字串比對會說
    「一樣」，於是一場什麼都沒驗到的接手考試看起來滿分。
    這是這一支最容易造假的地方。

四，**四類不自動判。** §39 第 6 步的四種解釋沒有一種算得出來，
    所以 `classify()` 的 `by` 必填，而且不收四類以外的字串。
    分不出來就讓它留在未分類，和解就不會完成。

五，**`priority_order` 沒有正典。** §41 的 triage 引擎沒有實作，
    這一欄要誠實回 `NO_SOURCE`，不准拿 ROADMAP 的章節順序頂替。

六，**正典借現成的判斷，不自己再算一次。** 改掉 `contract` 那兩支，
    `canonical()` 要跟著變 —— 不變就代表這裡藏了第二份實作。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import antianchor as AA  # noqa: E402
import contract as CT  # noqa: E402


def _mkroot(tmp_path, cfg=None):
    (tmp_path / ".forseti").mkdir(parents=True, exist_ok=True)
    if cfg is not None:
        (tmp_path / ".forseti" / "config.json").write_text(
            json.dumps(cfg), encoding="utf-8")
    return tmp_path


#: 一份有東西可以答的 work：一個被擋住的步驟、一件有下一步的任務。
WORK = {
    "blocked": ["S-01 等憑證"],
    "tasks": [{"id": "T-1", "next_step": {"objective": "把畫面接上去"}}],
}
SNAP = {"verified": ["必讀文件 20/30 讀完"]}


class TestCanonical:

    def test_四欄都在_順序照規格原文(self, tmp_path):
        can = AA.canonical(SNAP, WORK, _mkroot(tmp_path))
        assert [k for k, _e, _z in AA.FIELDS] == [
            "state", "priority_order", "blockers", "next_action"]
        assert set(can["fields"]) == {k for k, _e, _z in AA.FIELDS}

    def test_priority_order沒有正典而且說得出為什麼(self, tmp_path):
        f = AA.canonical(SNAP, WORK, _mkroot(tmp_path))["fields"]["priority_order"]
        assert f["state"] == AA.NO_SOURCE
        assert f["value"] is None
        # 不准悄悄拿 ROADMAP 頂替：理由裡要點名這件事
        assert "41" in f["why"] and "ROADMAP" in f["why"]

    def test_state空的時候是EMPTY不是NO_SOURCE(self, tmp_path):
        """兩種空不一樣：一個是來源在此刻沒值，一個是這系統沒有來源。"""
        f = AA.canonical({}, WORK, _mkroot(tmp_path))["fields"]["state"]
        assert f["state"] == AA.EMPTY
        assert f["why"]

    def test_blockers與next_action借contract而不是自己算(self, tmp_path, monkeypatch):
        """改掉 `contract` 那兩支，這裡要跟著變。

        不變就代表 `canonical()` 藏了第二份實作，而兩份會分歧的判斷
        遲早會分歧，分歧那天不會有錯誤訊息。
        """
        monkeypatch.setattr(CT, "_blockers_field", lambda w: ["換掉的擋住"])
        monkeypatch.setattr(CT, "_next_step", lambda w: ["換掉的下一步"])
        f = AA.canonical(SNAP, WORK, _mkroot(tmp_path))["fields"]
        assert f["blockers"]["value"] == ["換掉的擋住"]
        assert f["next_action"]["value"] == ["換掉的下一步"]
        assert f["blockers"]["source"] == "contract._blockers_field"

    def test_contract那一支不見了就回NO_SOURCE而不是當成空的(self, tmp_path, monkeypatch):
        monkeypatch.delattr(CT, "_next_step")
        f = AA.canonical(SNAP, WORK, _mkroot(tmp_path))["fields"]["next_action"]
        assert f["state"] == AA.NO_SOURCE
        assert "_next_step" in f["why"]

    def test_內容一樣sha就一樣_內容變了sha就變(self, tmp_path):
        r = _mkroot(tmp_path)
        a = AA.canonical(SNAP, WORK, r)["sha"]
        b = AA.canonical(SNAP, WORK, r)["sha"]
        c = AA.canonical(SNAP, {**WORK, "blocked": ["別的"]}, r)["sha"]
        assert a == b and a != c


class TestCompareOne:

    def test_兩邊都空是NOT_COMPARABLE不是SAME(self):
        """整組最容易造假的一條。什麼都沒驗到不准算成一致。"""
        r = AA.compare_one(None, {"state": AA.EMPTY, "value": None})
        assert r["result"] == AA.NOT_COMPARABLE
        assert r.get("same") is not True

    def test_受測者答了但沒有正典_不算對也不算錯(self):
        r = AA.compare_one(["我的推導"], {"state": AA.NO_SOURCE, "value": None})
        assert r["result"] == AA.CANONICAL_MISSING
        assert r.get("same") is not True

    def test_有正典而受測者沒答是差異(self):
        r = AA.compare_one(None, {"state": AA.HAS_VALUE, "value": ["甲"]})
        assert r["result"] == AA.DIFFERENT
        assert r["only_canonical"] == ["甲"]

    def test_清單比集合不比順序(self):
        """來源本身沒有定義順序，拿會變的東西當差異會製造假差異。"""
        r = AA.compare_one(["乙", "甲"], {"state": AA.HAS_VALUE, "value": ["甲", "乙"]})
        assert r["result"] == AA.SAME

    def test_空白不算差異但用字不同就算(self):
        c = {"state": AA.HAS_VALUE, "value": ["把畫面 接上去"]}
        assert AA.compare_one(["把畫面接上去"], c)["result"] == AA.SAME
        assert AA.compare_one(["把畫面接起來"], c)["result"] == AA.DIFFERENT


class TestOrder:
    """§39 七步的順序，這一段是整組的重點。"""

    def test_沒交推導不准揭曉(self, tmp_path):
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        out = AA.reveal(r, derivation_id=op["id"], snap=SNAP, work=WORK)
        assert out["ok"] is False
        assert "第 4 步" in out["why"] or "還沒交" in out["why"]

    def test_開卷本身不含任何答案(self, tmp_path):
        """§39 第 2 步：不要先把正典答案攤開。"""
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        blob = json.dumps(op, ensure_ascii=False)
        assert "必讀文件 20/30 讀完" not in blob
        assert "把畫面接上去" not in blob
        assert "S-01" not in blob
        # 帳本裡那一行也不能有
        assert "把畫面接上去" not in (r / ".forseti" / AA.LOG_NAME).read_text(
            encoding="utf-8")

    def test_推導只能交一次(self, tmp_path):
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        assert AA.submit(r, derivation_id=op["id"], answer={"state": ["x"]})["ok"]
        again = AA.submit(r, derivation_id=op["id"], answer={"state": ["對的答案"]})
        assert again["ok"] is False

    def test_揭曉只能一次(self, tmp_path):
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        AA.submit(r, derivation_id=op["id"], answer={"state": ["x"]})
        assert AA.reveal(r, derivation_id=op["id"], snap=SNAP, work=WORK)["ok"]
        assert AA.reveal(r, derivation_id=op["id"], snap=SNAP, work=WORK)["ok"] is False

    def test_沒揭曉不能分類(self, tmp_path):
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        AA.submit(r, derivation_id=op["id"], answer={"state": ["x"]})
        out = AA.classify(r, derivation_id=op["id"], field="state",
                          kind="STALE_CANONICAL", by="norika")
        assert out["ok"] is False

    def test_找不到的推導每一支都擋得住(self, tmp_path):
        r = _mkroot(tmp_path)
        assert AA.submit(r, derivation_id="沒有這個", answer={})["ok"] is False
        assert AA.reveal(r, derivation_id="沒有這個")["ok"] is False
        assert AA.reconciliation(r, derivation_id="沒有這個")["reconciled"] is False


class TestClassify:

    def _到揭曉(self, tmp_path):
        """兩欄故意推錯，一欄推對。

        推對的那一欄的答案**從 `canonical()` 取**，不在測試裡抄一份
        正典的措辭 —— 抄的那一份哪天 `contract` 改了行文就會假紅，
        而假紅的測試最後都會被關掉。
        """
        r = _mkroot(tmp_path)
        right = AA.canonical(SNAP, WORK, r)["fields"]["next_action"]["value"]
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        AA.submit(r, derivation_id=op["id"],
                  answer={"state": ["我推的不一樣"], "blockers": ["也不一樣"],
                          "next_action": list(right)})
        rev = AA.reveal(r, derivation_id=op["id"], snap=SNAP, work=WORK)
        return r, op["id"], rev

    def test_答對的那一欄不用分類_答錯的要(self, tmp_path):
        _r, _did, rev = self._到揭曉(tmp_path)
        assert "next_action" in rev["verified_fields"]
        assert set(rev["needs_classification"]) == {"state", "blockers"}
        # priority_order 沒有正典，不能算進驗到的那一堆
        assert "priority_order" in rev["nothing_verified"]
        assert "priority_order" not in rev["verified_fields"]

    def test_四類以外的字串不收(self, tmp_path):
        r, did, _rev = self._到揭曉(tmp_path)
        out = AA.classify(r, derivation_id=did, field="state",
                          kind="大概是環境問題", by="norika")
        assert out["ok"] is False

    def test_by必填_因為這四類沒有一類算得出來(self, tmp_path):
        r, did, _rev = self._到揭曉(tmp_path)
        out = AA.classify(r, derivation_id=did, field="state",
                          kind="CHANGED_REALITY", by="   ")
        assert out["ok"] is False
        assert "by" in out["why"]

    def test_不需要分類的欄位不准硬塞一筆(self, tmp_path):
        r, did, _rev = self._到揭曉(tmp_path)
        out = AA.classify(r, derivation_id=did, field="next_action",
                          kind="DEFECTIVE_RULE", by="norika")
        assert out["ok"] is False


class TestReconciliation:

    def test_分類完才算和解(self, tmp_path):
        r = _mkroot(tmp_path)
        right = AA.canonical(SNAP, WORK, r)["fields"]["next_action"]["value"]
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        did = op["id"]
        AA.submit(r, derivation_id=did,
                  answer={"state": ["不一樣"], "blockers": ["不一樣"],
                          "next_action": list(right)})
        AA.reveal(r, derivation_id=did, snap=SNAP, work=WORK)

        assert AA.reconciliation(r, derivation_id=did)["reconciled"] is False
        AA.classify(r, derivation_id=did, field="state",
                    kind="SUCCESSOR_REASONING_ERROR", by="norika")
        rec = AA.reconciliation(r, derivation_id=did)
        assert rec["reconciled"] is False
        assert rec["unclassified"] == ["blockers"]

        AA.classify(r, derivation_id=did, field="blockers",
                    kind="STALE_CANONICAL", by="norika", reason="那條早就解了")
        rec = AA.reconciliation(r, derivation_id=did)
        assert rec["reconciled"] is True
        assert rec["classified"] == ["blockers", "state"]

    def test_一欄都沒驗到的和解要自己講出來(self, tmp_path):
        """四欄都沒有正典的時候，`reconciled` 是 True 而證據是空的。

        布林值上它跟四欄都答對一樣，而它們不是同一件事。
        """
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap={}, work={})
        AA.submit(r, derivation_id=op["id"], answer={})
        AA.reveal(r, derivation_id=op["id"], snap={}, work={})
        rec = AA.reconciliation(r, derivation_id=op["id"])
        assert rec["reconciled"] is True
        assert rec["verified_fields"] == []
        assert "一欄都沒有驗到" in rec["why"]

    def test_還沒揭曉的時候說得出停在哪一步(self, tmp_path):
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        rec = AA.reconciliation(r, derivation_id=op["id"])
        assert rec["reconciled"] is False
        assert "還沒交推導" in rec["stage"]
        AA.submit(r, derivation_id=op["id"], answer={"state": ["x"]})
        rec = AA.reconciliation(r, derivation_id=op["id"])
        assert "還沒揭曉" in rec["stage"]

    def test_正典在推導期間變了會被記下來(self, tmp_path):
        """記的是事實不是判定：它可能是「現實變了」，也可能是有人改了來源。"""
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        AA.submit(r, derivation_id=op["id"], answer={"state": ["x"]})
        rev = AA.reveal(r, derivation_id=op["id"], snap=SNAP,
                        work={**WORK, "blocked": ["中途換掉的"]})
        assert rev["canonical_changed"] is True
        assert AA.reconciliation(r, derivation_id=op["id"])["canonical_changed"]

    def test_正典沒變就不要亂報(self, tmp_path):
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap=SNAP, work=WORK)
        AA.submit(r, derivation_id=op["id"], answer={"state": ["x"]})
        rev = AA.reveal(r, derivation_id=op["id"], snap=SNAP, work=WORK)
        assert rev["canonical_changed"] is False


class TestState:

    def test_沒走過的線說得出自己沒走過(self, tmp_path):
        st = AA.state(_mkroot(tmp_path), session="沒來過")
        assert st["reconciled"] is False
        assert st["derivation"] == ""

    def test_權限綁session不綁時間(self, tmp_path):
        """別條線和解過的不算這條線的。§39 講的是 successor。"""
        r = _mkroot(tmp_path)
        op = AA.open_derivation(r, session="s1", snap={}, work={})
        AA.submit(r, derivation_id=op["id"], answer={})
        AA.reveal(r, derivation_id=op["id"], snap={}, work={})
        assert AA.state(r, session="s1")["reconciled"] is True
        assert AA.state(r, session="s2")["reconciled"] is False

    def test_預設不強制_開了才擋(self, tmp_path):
        r = _mkroot(tmp_path)
        assert AA.enforced(r) is False
        assert AA.can_write(r, session="沒走過") is True

        r2 = _mkroot(tmp_path / "b", cfg={"antianchor_enforce": True})
        assert AA.enforced(r2) is True
        assert AA.can_write(r2, session="沒走過") is False
        op = AA.open_derivation(r2, session="s1", snap={}, work={})
        AA.submit(r2, derivation_id=op["id"], answer={})
        AA.reveal(r2, derivation_id=op["id"], snap={}, work={})
        assert AA.can_write(r2, session="s1") is True

    def test_沒開強制的時候state照樣說實話(self, tmp_path):
        """`can_write` 回 True 不代表這條線走過 —— 兩個問題不能合成一個。"""
        r = _mkroot(tmp_path)
        assert AA.can_write(r, session="沒走過") is True
        assert AA.state(r, session="沒走過")["reconciled"] is False
