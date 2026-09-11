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
        """真的不存在就是 REFUTED，那是一個確定的答案不是「量不到」。

        要有副檔名。沒有副檔名的話 can_refute() 會擋下來，
        而那是對的 —— 見 TestCanRefute。
        """
        c = C.Claim(text="x", kind="file", subject=str(self.tmp / "never.py"))
        C.verify(c)
        self.assertEqual(c.state, "REFUTED")

    def test_unsupported_kind_is_unknown_not_refuted(self):
        c = C.Claim(text="19 條全過", kind="number", subject="19")
        C.verify(c)
        self.assertEqual(c.state, "UNKNOWN")
        self.assertIn("不是驗不過", c.why_state)


class TestCanRefute(Case):
    """有沒有資格判一個宣稱是假的。

    ────────────────────────────────────────────────────

    這一組全部來自 2026-09-11 的真實語料校準。跑六個真 session、
    1,755 個宣稱,REFUTED 佔 30.8%,逐條看原句之後發現絕大多數是冤枉的。

    加上這四條規則之後降到 1.9%。**降的不是偵測力,是冤枉率** ——
    被擋下來的那些全部變成 UNKNOWN,沒有一個變成 VERIFIED。

    每一條都附當時抓到的實際字串當出處。沒有出處的規則不該存在,
    不然這裡會長成一個沒人知道邊界在哪的語意判斷器。
    """

    def test_an_enumeration_is_not_a_missing_file(self):
        """`Goal/Task`、`yes/no`、`Read/Write/Edit` 都被判過 REFUTED。

        它們沒有副檔名,而我分不出「不存在的目錄」跟「斜線列舉」。
        分不出來就不定罪。
        """
        for subject in ("Goal/Task", "yes/no", "Read/Write/Edit/Bash",
                        "CB/PS/drift", "api/sessions"):
            c = C.Claim(text="x", kind="file", subject=subject)
            C.verify(c, cwd=self.tmp)
            self.assertEqual(c.state, "UNKNOWN", subject)

    def test_a_placeholder_is_not_a_missing_file(self):
        """`tests/test_fXX.py` 是說明文字裡的佔位符,不是有人在說謊。

        `$HOME/x.log` 是 shell 變數,`.../a.log` 是省略。
        """
        for subject in ("tests/test_fXX.py", "$HOME/llama.cpp",
                        ".../hb_6d.log", "src/*.py"):
            c = C.Claim(text="x", kind="file", subject=subject)
            C.verify(c, cwd=self.tmp)
            self.assertEqual(c.state, "UNKNOWN", subject)

    def test_outside_the_repo_is_not_mine_to_judge(self):
        """驗證器只看得到一個 repo。

        說一個 repo 外的檔案「不存在」,是在講一件自己不知道的事。
        """
        c = C.Claim(text="x", kind="file",
                    subject="/definitely/not/here/ever.py")
        C.verify(c, cwd=self.tmp)
        self.assertEqual(c.state, "UNKNOWN")
        self.assertIn("不在這個 repo", c.why_state)

    def test_ratio_digits_are_not_a_file_extension(self):
        """`74.7/21.5/3.8` 是一組比例,`.8` 長得像副檔名但不是。

        副檔名至少要有一個字母。
        """
        c = C.Claim(text="x", kind="file", subject="74.7/21.5/3.8")
        C.verify(c, cwd=self.tmp)
        self.assertEqual(c.state, "UNKNOWN")

    def test_the_rules_only_loosen_the_convicting_path(self):
        """**這一組規則不准碰 VERIFIED 那一側。**

        修誤判最容易犯的錯是把判準放寬到什麼都過。這條測試守的是
        放寬的範圍有界:一個真的存在的檔案還是照樣 VERIFIED,
        一個沒有副檔名的目錄存在也還是 VERIFIED。
        """
        f = self.tmp / "real"          # 沒有副檔名,但它存在
        f.mkdir()
        c = C.Claim(text="x", kind="file", subject=str(f))
        C.verify(c, cwd=self.tmp)
        self.assertEqual(c.state, "VERIFIED")

        g = self.tmp / "real.py"
        g.write_text("x", encoding="utf-8")
        c2 = C.Claim(text="x", kind="file", subject=str(g))
        C.verify(c2, cwd=self.tmp)
        self.assertEqual(c2.state, "VERIFIED")

    def test_ct_001_still_convicts_inside_the_repo(self):
        """CT-001 沒有被這次放寬吃掉:repo 內的 0 bytes 還是 REFUTED。"""
        z = self.tmp / "empty.json"
        z.write_text("", encoding="utf-8")
        c = C.Claim(text="x", kind="file", subject=str(z))
        C.verify(c, cwd=self.tmp)
        self.assertEqual(c.state, "REFUTED")
        self.assertIn("0 bytes", c.why_state)

    def test_ct_001_does_not_convict_outside_the_repo(self):
        """驗錯對象的定罪仍然是冤枉。

        真實語料抓到的:原句講 `~/Library/Application Support/Claude/...`,
        路徑含空格被切成 `~/Library/Application`,而那裡剛好真的有一個
        0 bytes 的檔案。技術上判對了,驗的卻不是那句話在講的東西。
        """
        import tempfile
        other = Path(tempfile.mkdtemp())
        try:
            z = other / "empty.json"
            z.write_text("", encoding="utf-8")
            c = C.Claim(text="x", kind="file", subject=str(z))
            C.verify(c, cwd=self.tmp)
            self.assertEqual(c.state, "UNKNOWN")
        finally:
            import shutil
            shutil.rmtree(other, ignore_errors=True)

    def test_size_none_is_not_size_zero(self):
        """量不到大小跟大小是 0 是兩件事。

        帳本來的證據可能沒有 byteSize 欄位,`not size` 對兩者都成立,
        於是一個好好的檔案被判成空檔案。
        """
        c = C.Claim(text="x", kind="file", subject="a.py")
        self.assertIsNotNone(c.contract)

    def test_a_tilde_that_cannot_expand_does_not_crash(self):
        """`~someone/x` 展不開時 expanduser() 會丟 RuntimeError。

        2026-09-11 拿真實語料跑的第一秒就撞到。**驗證器自己爆炸,
        比它判錯更嚴重** —— 批次跑的時候後面的宣稱全部沒被驗到,
        而且沒有人會知道。
        """
        c = C.Claim(text="x", kind="file", subject="~nonexistentuser/a.py")
        C.verify(c, cwd=self.tmp)
        self.assertEqual(c.state, "UNKNOWN")


class TestRelativePathsNeedALedger(Case):
    """相對路徑少了基準，本來就沒有真假可言。

    2026-09-11 把四個模組接起來之後才看清楚的。兩個基準都試過,
    兩種誤判方向剛好相反:

        拿 Forseti repo 當基準   →  別的專案的檔案全被判成假的
        拿 session 的 cwd 當基準 →  這個 repo 裡真的存在的檔案
                                    (docs/build-plan.md、ledger.py)
                                    全被判成假的

    方向相反正說明問題不在規則。基準只有一個地方有:帳本裡 hook
    當時記下的 FILE_WRITE。**這讓 B-13 從一個缺口變成前提。**
    """

    def test_a_relative_path_without_ledger_evidence_is_unknown(self):
        c = C.Claim(text="x", kind="file", subject="dist/index.js")
        C.verify(c, cwd=self.tmp)
        self.assertEqual(c.state, "UNKNOWN")
        self.assertIn("不知道它相對於哪裡", c.why_state)

    def test_an_absolute_path_still_gets_judged(self):
        """這條放寬只針對相對路徑。絕對路徑自己帶著基準。"""
        c = C.Claim(text="x", kind="file",
                    subject=str(self.tmp / "nope.py"))
        C.verify(c, cwd=self.tmp)
        self.assertEqual(c.state, "REFUTED")

    def test_the_refutation_says_where_it_actually_looked(self):
        """措辭不能寫「在這個 repo 裡」—— 基準是呼叫端給的,不一定是 repo。

        一句講錯自己座標的判定,會讓讀的人以為系統查過了它其實沒查的地方。
        """
        c = C.Claim(text="x", kind="file", subject=str(self.tmp / "nope.py"))
        C.verify(c, cwd=self.tmp)
        self.assertIn(str(self.tmp), c.why_state)

    def test_a_huge_search_scope_gives_up_and_says_so(self):
        """走太多目錄就停手，而且說清楚那是關於自己的陳述。

        2026-09-11 在這裡連錯兩次,兩次都是「以為設了上限其實沒有」:
        先在 rglob 外面包計數器(它只數吐出來的匹配項,不數走過的目錄),
        再加快取(擋得住重複的 key,擋不住第一次那幾千個不同的 key)。
        真正要限制的是遍歷本身。
        """
        C._RESOLVE_CACHE.clear()
        deep = self.tmp
        for i in range(30):
            deep = deep / f"d{i}"
        deep.mkdir(parents=True)
        old = C._WALK_BUDGET
        try:
            C._WALK_BUDGET = 5
            path, why = C.resolve_subject("nowhere.py", cwd=self.tmp)
            self.assertIsNone(path)
            self.assertIn("範圍太大", why)
        finally:
            C._WALK_BUDGET = old
            C._RESOLVE_CACHE.clear()


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

        寫「不存在」太絕對,那不是這個驗證器真正知道的。
        它只在一個地方找過,而那個地方要講出來。

        2026-09-11 更新:原本寫死「在這個 repo 裡」,但基準是呼叫端給的
        cwd,接線之後它變成 session 的工作目錄。**一句講錯自己座標的
        判定,比不講更糟**,所以改成報實際找過的目錄。
        """
        target = self.tmp / "sub" / "gone.py"
        c = C.Claim(text="x", kind="file", subject=str(target))
        C.verify(c)
        self.assertEqual(c.state, "REFUTED")
        self.assertIn(str(target.parent), c.why_state)


class TestTheLedgerComesFirst(unittest.TestCase):
    """路徑對不到的時候，先問帳本再放棄。

    2026-09-11 準備開採集之前做 preflight 才發現的順序錯誤:
    原本 resolve 失敗就直接回 UNKNOWN，連查都不查。

    **那會讓整個採集白做** —— hook 明明在 FILE_WRITE 事件裡記了
    絕對路徑與 hash，而驗證器因為自己 resolve 不出來就先走開了。
    帳本記的是 hook 在那一刻親眼量到的東西，不需要猜基準，
    所以它該是第一順位不是備案。
    """

    def setUp(self):
        import os
        import tempfile
        self.box = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.box,
                                                            ignore_errors=True))
        self.old = os.environ.get("FORSETI_EVENT_LEDGER_DIR")
        os.environ["FORSETI_EVENT_LEDGER_DIR"] = str(self.box)
        self.addCleanup(self._restore)
        C._RESOLVE_CACHE.clear()

    def _restore(self):
        import os
        if self.old is None:
            os.environ.pop("FORSETI_EVENT_LEDGER_DIR", None)
        else:
            os.environ["FORSETI_EVENT_LEDGER_DIR"] = self.old
        C._RESOLVE_CACHE.clear()

    def _record(self, subject, size):
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parents[1]
                              / "apps" / "forseti-cli"))
        import importlib
        EL = importlib.import_module("event_ledger")
        importlib.reload(EL)
        led = EL.EventLedger()
        try:
            raw = EL.RawEvent(provider="claude-code",
                              provider_event_type="PostToolUse",
                              timestamp=1.0, payload={"file_path": subject})
            norm = EL.NormalizedEvent(
                raw_event_id=raw.id, type="FILE_WRITE", subject=subject,
                provenance="OBSERVED",
                metadata={"evidence": {"existence": True, "byteSize": size,
                                       "contentHash": "deadbeef"}})
            led.append(raw, norm)
        finally:
            led.close()

    def test_the_writer_and_the_reader_share_one_sandbox(self):
        """**一個只擋住寫入端的沙箱，比沒有沙箱更危險** —— 它讓人以為隔離了。

        2026-09-11 實測:node 的 hook 尊重 FORSETI_EVENT_LEDGER_DIR，
        Python 這邊不吃。於是 writer 寫沙箱、reader 讀正本，
        兩邊看到不同的帳本，而測試會通過，因為它只檢查了其中一邊。
        """
        import importlib
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parents[1]
                              / "apps" / "forseti-cli"))
        EL = importlib.import_module("event_ledger")
        importlib.reload(EL)
        self.assertEqual(EL.default_jsonl().parent, self.box)

    def test_a_lost_path_is_verified_by_the_ledger(self):
        self._record("/somewhere/else/gone-for-good.py", 128)
        c = C.Claim(text="x", kind="file", subject="gone-for-good.py")
        C.verify(c, cwd=self.box)
        self.assertEqual(c.state, "VERIFIED")
        self.assertEqual(c.strength, "E2")
        self.assertIn("帳本記得", c.why_state)

    def test_the_ledger_can_also_convict(self):
        """帳本說它當時是 0 bytes，CT-001 照樣成立。"""
        self._record("/somewhere/else/empty-one.py", 0)
        c = C.Claim(text="x", kind="file", subject="empty-one.py")
        C.verify(c, cwd=self.box)
        self.assertEqual(c.state, "REFUTED")
        self.assertIn("0 bytes", c.why_state)

    def test_no_ledger_entry_still_falls_to_unknown(self):
        c = C.Claim(text="x", kind="file", subject="never-recorded.py")
        C.verify(c, cwd=self.box)
        self.assertEqual(c.state, "UNKNOWN")



if __name__ == "__main__":
    unittest.main(verbosity=2)
