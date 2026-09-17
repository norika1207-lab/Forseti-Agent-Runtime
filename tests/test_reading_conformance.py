#!/usr/bin/env python3
"""reading_policy 檢查器。守的是「這支會不會永遠回 OK」。

2026-09-11 實跑九份全部 OK。那是好消息，但它同時是一個危險的狀態：
一個永遠回 OK 的檢查等於沒有檢查，而當天稍早才踩過同一個坑
（`silence_map` 的行號對不上，讓 risky 清單恆為 0，
看起來像「沒事」）。

所以這一組測試全部在做同一件事：人為製造不合格，確認它真的會叫。
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "reading_conformance", REPO / "tools" / "reading-conformance.py")
RC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RC)

MANIFEST_JSON = """{
 "spec_set": "test",
 "version": "1.0",
 "architecture": "ARCH-EXEC-001",
 "features": [{"id": "F01-PEC-001", "file": "F01.md"}],
 "reading_policy": "full-file required; sampled/title-only reading is non-conformant"
}"""

ARCH_NAME = "00_Forseti_Execution_Foundation_Architecture.md"


class Case(unittest.TestCase):

    def setUp(self):
        self.box = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: shutil.rmtree(self.box, ignore_errors=True))
        self.spec_dir = self.box / "spec"
        self.spec_dir.mkdir()
        (self.spec_dir / "spec_manifest.json").write_text(
            MANIFEST_JSON, encoding="utf-8")
        (self.spec_dir / ARCH_NAME).write_text("arch 全文", encoding="utf-8")
        (self.spec_dir / "F01.md").write_text("F01 全文", encoding="utf-8")

        self.reading = self.box / "REQUIRED_READING.md"
        self._write_table(self._h(ARCH_NAME), self._h("F01.md"))

        self._old = (RC.SPEC_DIR, RC.MANIFEST, RC.READING)
        RC.SPEC_DIR = self.spec_dir
        RC.MANIFEST = self.spec_dir / "spec_manifest.json"
        RC.READING = self.reading
        self.addCleanup(self._restore)

    def _restore(self):
        RC.SPEC_DIR, RC.MANIFEST, RC.READING = self._old

    def _h(self, name: str) -> str:
        return hashlib.sha256(
            (self.spec_dir / name).read_bytes()).hexdigest()[:12]

    def _write_table(self, arch_hash, f01_hash, arch_id="ARCH-EXEC-001"):
        self.reading.write_text(
            "| ID | 檔案 | Level | sha256(前12) | 主題 |\n"
            "|---|---|---|---|---|\n"
            f"| {arch_id} | `{ARCH_NAME}` | 5 | `{arch_hash}` | 架構 |\n"
            f"| F01-PEC-001 | `F01.md` | 5 | `{f01_hash}` | 契約 |\n",
            encoding="utf-8")


class TestItActuallyCatchesThings(Case):
    """每一條都人為弄壞一樣東西，確認它會叫。"""

    def test_all_matching_is_conformant(self):
        r = RC.check()
        self.assertEqual(r["status"], "CONFORMANT")
        self.assertEqual(r["bad"], 0)
        self.assertEqual(r["checked"], 2)

    def test_a_changed_file_is_caught(self):
        """檔案被改過而補讀表沒更新。

        這是最常見的一種：規格換版了，而補讀表還記著舊 hash。
        """
        (self.spec_dir / "F01.md").write_text("改過了", encoding="utf-8")
        r = RC.check()
        self.assertEqual(r["status"], "NON_CONFORMANT")
        row = [x for x in r["rows"] if x["id"] == "F01-PEC-001"][0]
        self.assertEqual(row["verdict"], "CHANGED")
        self.assertIn("現在是", row["why"])

    def test_a_missing_file_is_caught(self):
        """檔案被移走。

        2026-09-11 真的發生過：整組規格被移進
        `Forseti Agent Runtime` 那一層，而補讀表記的是舊路徑。
        「找不到」跟「讀過了」在一張自己填的表上長得一模一樣。
        """
        (self.spec_dir / "F01.md").unlink()
        r = RC.check()
        self.assertEqual(r["status"], "NON_CONFORMANT")
        row = [x for x in r["rows"] if x["id"] == "F01-PEC-001"][0]
        self.assertEqual(row["verdict"], "MISSING_FILE")

    def test_an_unrecorded_spec_is_caught(self):
        """manifest 列了，補讀表沒有。

        新增一份規格而沒有人去讀它，就是這個形狀。
        """
        self._write_table(self._h(ARCH_NAME), self._h("F01.md"),
                          arch_id="SOMETHING-ELSE")
        r = RC.check()
        self.assertEqual(r["status"], "NON_CONFORMANT")
        row = [x for x in r["rows"] if x["id"] == "ARCH-EXEC-001"][0]
        self.assertEqual(row["verdict"], "NO_RECORD")

    def test_missing_manifest_is_cannot_check_not_ok(self):
        """manifest 不見的時候要說「檢查不了」，不能說「合格」。

        這一條跟 claims.py 的三態是同一個原則：
        量不到不等於沒問題。
        """
        RC.MANIFEST.unlink()
        r = RC.check()
        self.assertEqual(r["status"], "CANNOT_CHECK")
        self.assertEqual(RC.main(["x"]), 2)


class TestItAdmitsWhatItCannotDo(Case):
    """它驗不到的那一塊，要在程式碼裡看得見。"""

    def test_coverage_gap_returns_none_and_does_not_guess(self):
        """「讀了幾行」現在答不出來，那就回 None，不許填一個假的。

        sha256 只證明檔案自從被記錄之後沒有變，不證明當時讀完了整份。
        一個只讀最後 20 行的人，算出來的 hash 跟讀完整份的一模一樣。
        """
        self.assertIsNone(RC.coverage_gap("F01-PEC-001"))
        r = RC.check()
        for row in r["rows"]:
            self.assertIsNone(row["coverage_gap"])

    def test_the_policy_text_is_carried_through_verbatim(self):
        """政策原文要原封不動帶出來，不許改寫成自己的話。

        改寫過的政策會慢慢偏離，而讀報告的人不知道它偏了。
        """
        r = RC.check()
        self.assertEqual(
            r["policy"],
            "full-file required; sampled/title-only reading is non-conformant")


class TestReadingTableUnreadable(Case):
    """補讀表讀不到，跟補讀表是空的，不可以長得一樣。

    2026-09-17 之前 `declared()` 吞掉 `OSError` 回空 dict，於是兩種
    情形回傳的整個結果相同：每一份都 `NO_RECORD`，理由印
    「補讀表裡沒有這一份的記錄」—— 而補讀表根本沒被讀到。
    照那句理由去修的人會去補表，而表可能一直是對的。

    修法不是讓它更嚴：讀不到的時候回 `CANNOT_CHECK`，
    也就是模組檔頭 exit code 那段本來就寫著的第 2 種。
    """

    def _make_unreadable(self):
        """讓補讀表那一個檔 `read_text` 丟 `OSError`，其餘檔案照常。

        不用 `chmod` —— 這顆碟是 exFAT，不帶 Unix 權限，
        `chmod 000` 在上面不會讓讀取失敗（`files-on-adata` 那條記過）。
        """
        orig = Path.read_text
        target = self.reading

        def bad(self_, *a, **k):
            if self_ == target:
                raise OSError(13, "permission denied")
            return orig(self_, *a, **k)

        Path.read_text = bad
        self.addCleanup(lambda: setattr(Path, "read_text", orig))

    def test_unreadable_table_is_cannot_check_not_no_record(self):
        self._make_unreadable()
        r = RC.check()
        self.assertEqual(r["status"], "CANNOT_CHECK")
        self.assertIn("補讀表讀不到", r["why"])
        self.assertIn("permission denied", r["why"])
        self.assertNotIn("rows", r)

    def test_unreadable_table_exits_two(self):
        """exit 2 是「無法檢查」。1 會讓人以為判過了而且不合格。"""
        self._make_unreadable()
        self.assertEqual(RC.main(["x"]), 2)

    def test_declared_raises_instead_of_returning_empty(self):
        self._make_unreadable()
        with self.assertRaises(RC.ReadingTableUnreadable):
            RC.declared()

    def test_an_empty_but_readable_table_is_still_non_conformant(self):
        """表在、讀得到、可是一列都沒有 —— 那是「沒有人宣稱讀過」。

        這一條釘的是**沒有被順手放寬**：修掉上面那個假理由的時候，
        最容易犯的是把空表也一起改成 `CANNOT_CHECK`。
        """
        self.reading.write_text("（這張表現在一列都沒有）\n",
                                encoding="utf-8")
        r = RC.check()
        self.assertEqual(r["status"], "NON_CONFORMANT")
        self.assertEqual(r["bad"], 2)
        self.assertTrue(all(x["verdict"] == "NO_RECORD" for x in r["rows"]))
        self.assertEqual(RC.main(["x"]), 1)

    def test_the_two_cases_are_not_equal(self):
        """兩種情形的回傳值要分得出來。這是這一組存在的理由。"""
        self.reading.write_text("（這張表現在一列都沒有）\n",
                                encoding="utf-8")
        empty = RC.check()
        self._make_unreadable()
        unreadable = RC.check()
        self.assertNotEqual(empty, unreadable)
        self.assertNotEqual(empty["status"], unreadable["status"])


class TestExitCodes(Case):

    def test_conformant_exits_zero(self):
        self.assertEqual(RC.main(["x"]), 0)

    def test_non_conformant_exits_one(self):
        (self.spec_dir / "F01.md").write_text("變了", encoding="utf-8")
        self.assertEqual(RC.main(["x"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
