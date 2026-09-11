#!/usr/bin/env python3
"""階段 2：Claim 與 Reality。

出口條件（`docs/build-plan.md:345`）：

    拿今天這個 session 的 transcript 跑，能列出所有 claim 及其驗證狀態，
    而且「檔案已建立」這種宣稱能被 stat + size + hash 自動驗證。
    0 bytes 的檔案不得判 VERIFIED（CT-001）。

**這一組測試最重要的不是功能會動，是三條禁令守不守得住：**

一，不做語意判斷（`build-plan:350`）。抽不出來標 UNEXTRACTABLE，不猜。
二，重複不增加證據強度（v5.0 §7.1 原文）。
三，0 bytes 不得 VERIFIED（CT-001）。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import claims as C  # noqa: E402
import event_ledger as E  # noqa: E402


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def file(self, name: str, content: str = "x") -> Path:
        p = self.tmp / name
        p.write_text(content, encoding="utf-8")
        return p


class TestCT001(Case):
    """0 bytes 的檔案不得判 VERIFIED。這一條單獨開一個 class。"""

    def test_empty_file_is_refuted_not_verified(self):
        p = self.tmp / "empty.py"
        p.write_text("", encoding="utf-8")
        c = C.Claim(text="我建立了 empty.py", kind="file", subject=str(p))
        C.verify(c)
        self.assertEqual(c.state, "REFUTED")
        self.assertIn("0 bytes", c.why_state)

    def test_a_file_with_content_verifies(self):
        p = self.file("real.py", "print(1)")
        c = C.Claim(text="我建立了 real.py", kind="file", subject=str(p))
        C.verify(c)
        self.assertEqual(c.state, "VERIFIED")

    def test_the_reason_says_why_not_just_that_it_failed(self):
        """判 REFUTED 要講得出為什麼，不然沒辦法反駁它。"""
        p = self.tmp / "e.py"
        p.write_text("", encoding="utf-8")
        c = C.Claim(text="建立了", kind="file", subject=str(p))
        C.verify(c)
        self.assertIn("跟沒建立對使用者是一樣的", c.why_state)


class TestRepetitionDoesNotStrengthen(Case):
    """v5.0 §7.1：Repetition increases social consensus, not evidence strength."""

    def test_saying_it_a_hundred_times_keeps_it_at_E0(self):
        c = C.Claim(text="改好了", kind="file", subject="a.py")
        for i in range(100):
            c.repeat(by=f"agent-{i}")
        self.assertEqual(c.repeats, 100)
        self.assertEqual(len(c.said_by), 100)
        self.assertEqual(c.strength, "E0", "一百個人說過，強度一樣是 E0")

    def test_repeat_cannot_reach_canonical(self):
        c = C.Claim(text="改好了", kind="file", subject="a.py")
        for _ in range(50):
            c.repeat(by="someone")
        with self.assertRaises(C.ClaimError) as ctx:
            c.promote(authority="owner", policy_ref="ADR-001")
        self.assertIn("E4", str(ctx.exception))
        self.assertIn("social consensus", str(ctx.exception))

    def test_repeat_has_no_path_to_strength(self):
        """機制層面的檢查：repeat() 不碰 strength 這件事要看得見。

        測行為不夠 —— 有人之後在 repeat() 裡加一行提升強度，
        上面兩條仍然會過（只要他讓一百次才升一級）。
        這一條直接驗那個欄位在 repeat 前後完全沒動。
        """
        c = C.Claim(text="x", kind="file", subject="a.py")
        c.raise_strength("E2", "stat")
        before = c.strength
        for _ in range(10):
            c.repeat()
        self.assertEqual(c.strength, before)


class TestNoSemanticGuessing(Case):
    """`build-plan:350`：抽不出來標 UNEXTRACTABLE，不猜。"""

    def test_intent_is_not_a_claim(self):
        """「我要去改 a.py」是意圖不是宣稱。

        把意圖當宣稱去驗會永遠判 REFUTED —— 那個檔案當然還沒改，
        因為他說的是等一下要做。這一條是 classify-turns.mjs 的
        INTENT 類踩出來的。
        """
        self.assertEqual(C.extract("我要去改 apps/a.py"), [])
        self.assertEqual(C.extract("接下來會建立 b.py"), [])

    def test_past_tense_without_anything_checkable_is_unextractable(self):
        got = C.extract("我改好了，應該沒問題了")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["kind"], "unextractable")
        self.assertIn("找不到可查核的具體物", got[0]["why"])

    def test_a_path_is_extracted(self):
        got = C.extract("我建立了 apps/forseti-cli/claims.py")
        self.assertEqual(got[0]["kind"], "file")
        self.assertEqual(got[0]["subject"], "apps/forseti-cli/claims.py")

    def test_file_wins_over_number_in_the_same_sentence(self):
        """一句話裡同時有檔案跟數字，抽檔案。

        數字單獨存在幾乎驗不了，而那句話真正的具體物是那個檔案。
        """
        got = C.extract("跑過了 tests/test_claims.py，19 條全過")
        self.assertEqual(got[0]["kind"], "file")

    def test_empty_and_whitespace_give_nothing(self):
        for s in ("", "   ", "\n\n"):
            self.assertEqual(C.extract(s), [])


class TestLifecycle(Case):
    """v5.0 §7.1 的狀態機。"""

    def test_canonical_has_exactly_one_entrance(self):
        c = C.Claim(text="x", kind="file", subject="a.py")
        with self.assertRaises(C.ClaimError) as ctx:
            c.to("CANONICAL", "我說了算")
        self.assertIn("promote()", str(ctx.exception))

    def test_promote_needs_authority_policy_and_E4(self):
        c = C.Claim(text="x", kind="file", subject="a.py")
        c.raise_strength("E4", "owner 親自確認")
        for kwargs in ({"authority": "", "policy_ref": "p"},
                       {"authority": "owner", "policy_ref": ""}):
            with self.assertRaises(C.ClaimError):
                c.promote(**kwargs)
        c.promote(authority="owner", policy_ref="ADR-001")
        self.assertEqual(c.state, "CANONICAL")

    def test_a_claim_without_a_contract_cannot_wait_for_evidence(self):
        """沒有契約的宣稱停在 PROPOSED，不會進 EVIDENCE_REQUIRED。

        UNKNOWN 的意思是「驗過了但答不出來」，沒有契約是「根本還沒開始」。
        讓它進 EVIDENCE_REQUIRED 會讓後者看起來像前者。
        """
        c = C.Claim(text="x", kind="unextractable", subject="")
        self.assertIsNone(c.contract)
        with self.assertRaises(C.ClaimError):
            c.require_evidence()
        self.assertEqual(c.state, "PROPOSED")

    def test_every_transition_needs_a_reason(self):
        c = C.Claim(text="x", kind="file", subject="a.py")
        with self.assertRaises(C.ClaimError):
            c.to("EVIDENCE_REQUIRED", "   ")

    def test_refuted_can_be_reopened(self):
        """被判失敗的宣稱，拿到證據要能翻案。

        不能翻的話這張表就變成單向的定罪。
        """
        c = C.Claim(text="x", kind="file", subject="a.py")
        c.require_evidence()
        c.to("REFUTED", "當時不存在")
        c.to("EVIDENCE_REQUIRED", "後來找到證據，重驗")
        self.assertEqual(c.state, "EVIDENCE_REQUIRED")

    def test_contract_is_frozen(self):
        """契約在宣稱成立那一刻固定。事後改契約是搬球門。"""
        with self.assertRaises(Exception):
            C.FILE_CREATED.checks = ("path_exists",)


class TestUnknownIsNotRefuted(Case):
    """量不到跟不存在是兩件事。混在一起會冤枉人。"""

    def test_permission_denied_is_unknown_not_refuted(self):
        """讀不到跟不存在，靠例外型別分，不靠猜。

        2026-09-11 這條測試自己錯過一次：原本用 `/proc/xxx` 當「讀不到」
        的例子，但那個路徑在 macOS 上是**真的不存在**，所以它一直在測
        FileNotFoundError 而不是 PermissionError。兩種都被程式碼併成
        UNKNOWN 的時候它會過，而那正是判準過寬的樣子。

        現在用一個 chmod 000 的目錄，那會真的產生 PermissionError。
        """
        locked = self.tmp / "locked"
        locked.mkdir()
        inner = locked / "secret.txt"
        inner.write_text("x", encoding="utf-8")
        locked.chmod(0o000)
        try:
            got = C._disk(str(inner))
            if got["existence"] is False:
                self.skipTest("這個環境下讀得到（可能是 root），測不到權限那條路")
            self.assertEqual(got["existence"], "unknown")
            c = C.Claim(text="x", kind="file", subject=str(inner))
            C.verify(c)
            self.assertEqual(c.state, "UNKNOWN")
            self.assertIn("不是不存在", c.why_state)
        finally:
            locked.chmod(0o755)

    def test_a_path_that_really_does_not_exist_is_refuted(self):
        """真的不存在就是 REFUTED，那是一個確定的答案不是「量不到」。"""
        c = C.Claim(text="x", kind="file", subject=str(self.tmp / "never"))
        C.verify(c)
        self.assertEqual(c.state, "REFUTED")

    def test_unsupported_kind_is_unknown_not_refuted(self):
        c = C.Claim(text="19 條全過", kind="number", subject="19")
        C.verify(c)
        self.assertEqual(c.state, "UNKNOWN")
        self.assertIn("不是驗不過", c.why_state)


class TestEvidenceFromLedger(Case):
    """階段 1 的成果直接用上：帳本裡當時的證據。"""

    def setUp(self):
        super().setUp()
        self.led = E.EventLedger(jsonl=self.tmp / "el.jsonl",
                                 index=self.tmp / "idx.db")

    def tearDown(self):
        self.led.close()

    def write_event(self, path: str, size: int, h: str = "abc123"):
        r = E.RawEvent(provider="claude-code", provider_event_type="PostToolUse",
                       timestamp=1700000000.0, payload={"file_path": path})
        self.led.append(r, E.NormalizedEvent(
            raw_event_id=r.id, type="FILE_WRITE", subject=path,
            result=f"{size} bytes",
            metadata={"evidence": {"existence": True, "byteSize": size,
                                   "contentHash": h}}))

    def test_two_independent_sources_reach_E3(self):
        """帳本當時的證據 + 現在的 stat = 兩個獨立來源，§7.2 的 E3。"""
        p = self.file("both.py", "content")
        self.write_event(str(p), 7)
        c = C.Claim(text="建立了 both.py", kind="file", subject=str(p))
        C.verify(c, led=self.led)
        self.assertEqual(c.state, "VERIFIED")
        self.assertEqual(c.strength, "E3")

    def test_disk_only_is_E2(self):
        p = self.file("only.py", "content")
        c = C.Claim(text="建立了 only.py", kind="file", subject=str(p))
        C.verify(c, led=self.led)
        self.assertEqual(c.strength, "E2")

    def test_ledger_evidence_wins_when_the_file_changed_later(self):
        """檔案後來被改了，帳本裡當時的證據仍然算數。

        這是階段 1 存在的理由之一：現在量到的 hash 跟宣稱當時不同，
        不代表那個宣稱是假的。
        """
        p = self.file("changed.py", "original")
        self.write_event(str(p), 8, h="original-hash")
        p.write_text("something completely different", encoding="utf-8")
        c = C.Claim(text="建立了 changed.py", kind="file", subject=str(p))
        C.verify(c, led=self.led)
        self.assertEqual(c.state, "VERIFIED",
                         "檔案後來變了，不代表當初沒建立")

    def test_a_missing_ledger_is_not_a_refutation(self):
        """帳本裡找不到，不是 REFUTED，只是少一條證據來源。"""
        p = self.file("nolog.py", "content")
        c = C.Claim(text="建立了 nolog.py", kind="file", subject=str(p))
        C.verify(c, led=self.led)
        self.assertEqual(c.state, "VERIFIED")



class TestDirectoriesAreNotMissingFiles(Case):
    """2026-09-11 實測抓到的誤判。

    出口條件第一次跑真實 transcript 的時候，`docs/sources` 與
    `~/.forseti/ledgers` 兩個真的存在的目錄被判 REFUTED，
    因為原本的程式碼把「不是檔案」一律當成「不存在」。

    **冤枉是最糟的一類錯。** 一個被判成假的真宣稱，會讓人不信任
    整套判定，而那比漏掉幾個假宣稱傷得更重。
    """

    def test_an_existing_directory_verifies(self):
        d = self.tmp / "somedir"
        d.mkdir()
        c = C.Claim(text="建立了 somedir", kind="file", subject=str(d))
        C.verify(c)
        self.assertEqual(c.state, "VERIFIED")
        self.assertIn("目錄", c.why_state)

    def test_an_empty_directory_still_verifies(self):
        """空目錄跟空檔案不一樣。

        CT-001 規的是「建立了一個空檔案等於沒建立」，
        而一個空目錄是真的被建立了 —— 它可以被 cd 進去、可以放東西。
        """
        d = self.tmp / "emptydir"
        d.mkdir()
        c = C.Claim(text="建立了 emptydir", kind="file", subject=str(d))
        C.verify(c)
        self.assertEqual(c.state, "VERIFIED")

    def test_a_real_missing_path_is_still_refuted(self):
        """修完之後，真的不存在的東西還是要被抓到。

        修誤判最容易犯的錯是把判準放寬到什麼都過。
        """
        c = C.Claim(text="建立了 nope.py",
                    kind="file", subject=str(self.tmp / "nope.py"))
        C.verify(c)
        self.assertEqual(c.state, "REFUTED")


class TestUncertaintyFallsToUnknownNotRefuted(Case):
    """結構規則必然有誤判。**誤判要往 UNKNOWN 倒，不要往 REFUTED 倒。**

    這條原則是 2026-09-11 跑出口條件跑出來的。修了三輪，每一輪都發現
    新的誤判，而且每一輪都是同一個方向：把不確定的東西判成假的。

    抽取器看不懂一段文字的時候，正確的答案是「我不知道」，
    不是「他在說謊」。不確定的時候不定罪。
    """

    def test_slash_separated_enumerations_are_not_paths(self):
        """「VERIFIED/REFUTED/UNKNOWN」是列舉不是路徑。"""
        for enum in ("OBSERVED/DECLARED/INFERRED/MISSING",
                     "VERIFIED/REFUTED/UNKNOWN", "E0/E1/E2"):
            self.assertTrue(C.looks_like_enumeration(enum), enum)
            c = C.Claim(text="x", kind="file", subject=enum)
            C.verify(c)
            self.assertEqual(c.state, "UNKNOWN", f"{enum} 不該被定罪")
            self.assertIn("列舉", c.why_state)

    def test_real_paths_are_not_mistaken_for_enumerations(self):
        """修誤判不能把真路徑一起殺掉。"""
        for real in ("src/evidence.js", "apps/forseti-cli/ledger.py",
                     "docs/README.md", "a/b/c.txt"):
            self.assertFalse(C.looks_like_enumeration(real), real)

    def test_an_ambiguous_bare_name_is_unknown(self):
        """裸檔名對到多個，不猜是哪一個。

        猜一個去驗的話，驗出來的結果跟宣稱可能根本無關 ——
        那比不驗更糟，因為它看起來像是驗過了。
        """
        (self.tmp / "a").mkdir()
        (self.tmp / "b").mkdir()
        (self.tmp / "a" / "dup.py").write_text("x", encoding="utf-8")
        (self.tmp / "b" / "dup.py").write_text("y", encoding="utf-8")
        got, why = C.resolve_subject("dup.py", cwd=self.tmp)
        self.assertIsNone(got)
        self.assertIn("多個", why)

    def test_a_unique_bare_name_resolves(self):
        (self.tmp / "only-one.py").write_text("x", encoding="utf-8")
        got, why = C.resolve_subject("only-one.py", cwd=self.tmp)
        self.assertIsNotNone(got)
        self.assertIn("唯一", why)

    def test_refutation_says_where_it_looked(self):
        """判 REFUTED 的時候要講清楚是在哪裡找不到。

        驗證器只看得到一個 repo，而宣稱可能在講別的專案。
        寫「不存在」太絕對，那不是這個驗證器真正知道的。
        """
        c = C.Claim(text="x", kind="file",
                    subject=str(self.tmp / "sub" / "gone.py"))
        C.verify(c)
        self.assertEqual(c.state, "REFUTED")
        self.assertIn("在這個 repo 裡找不到", c.why_state)

if __name__ == "__main__":
    unittest.main(verbosity=2)
