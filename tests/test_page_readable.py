#!/usr/bin/env python3
"""`tools/check-page-readable.py` 的測試。

它存在的理由是 bible Q-06：2026-09-10 部署頁面到 VPS，三條 verifier
全過（檔案在、HTTP 200、雜湊逐位元組一致），瀏覽器打開是整頁亂碼。

所以這一組測試的重點不是「好的頁面會過」，是**壞的頁面會不會被抓到**。
一個永遠回 0 的檢查器比沒有檢查器更糟。
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "check-page-readable.py"
sys.path.insert(0, str(TOOL.parent))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("cpr", TOOL)
cpr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cpr)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, name: str, text: str, encoding="utf-8") -> Path:
        p = self.tmp / name
        p.write_bytes(text.encode(encoding))
        return p


class TestCatchesTheRealBug(Case):
    """2026-09-10 那個實際發生過的形狀。"""

    def test_no_charset_declared_anywhere_fails(self):
        """兩邊都沒宣告編碼就是看不懂。

        這正是當初部署上去的那份：HTML 沒有 meta charset，
        nginx 送 text/html 不帶 charset，而 nosniff 讓瀏覽器不能猜。
        """
        p = self.write("a.html", "<title>標題</title><p>北極星</p>")
        code, notes = cpr.check(str(p))
        self.assertEqual(code, 1)
        self.assertTrue(any("沒有宣告編碼" in n for n in notes), notes)

    def test_meta_charset_makes_it_pass(self):
        """加上 meta charset 就過 —— 那正是實際的修法。"""
        p = self.write("b.html", '<meta charset="utf-8"><p>北極星</p>')
        code, _ = cpr.check(str(p))
        self.assertEqual(code, 0)

    def test_mojibake_is_caught_even_when_charset_is_declared(self):
        """宣告了編碼但內容已經是亂碼，也要抓到。

        這是更陰險的一種：header 說 utf-8、解得開、不報錯，
        但內容本身是被錯誤解碼過一輪再存回去的。
        檔案是好的、編碼是對的、人看到的是垃圾。
        """
        broken = "北極星，可觀測".encode("utf-8").decode("latin-1")
        p = self.write("c.html", f'<meta charset="utf-8"><p>{broken * 3}</p>')
        code, notes = cpr.check(str(p))
        self.assertEqual(code, 1)
        self.assertTrue(any("像亂碼" in n for n in notes), notes)


class TestExpectedStrings(Case):
    def test_missing_expected_string_fails(self):
        """指定的字串找不到就是沒送到。

        這一條比 charset 更通用：它驗的是「我要的那段內容真的在裡面」，
        而不只是「這份文件解得開」。部署一份舊版上去也會解得開。
        """
        p = self.write("d.html", '<meta charset="utf-8"><p>別的東西</p>')
        code, notes = cpr.check(str(p), expect=["北極星"])
        self.assertEqual(code, 1)
        self.assertTrue(any("找不到" in n for n in notes), notes)

    def test_present_expected_string_passes(self):
        p = self.write("e.html", '<meta charset="utf-8"><p>北極星在這</p>')
        self.assertEqual(cpr.check(str(p), expect=["北極星"])[0], 0)


class TestBrowserRules(Case):
    def test_meta_charset_too_late_in_the_file_does_not_count(self):
        """meta charset 放在 2048 位元組之後等於沒放。

        那是瀏覽器的實際行為：解析器早就用預設編碼開始了。
        照抄這條規則而不是自己定一個比較寬鬆的，
        因為要驗的是「瀏覽器怎麼看」不是「檔案裡有沒有那個字串」。
        """
        pad = "<!-- " + "x" * 2200 + " -->"
        p = self.write("f.html", pad + '<meta charset="utf-8"><p>北極星</p>')
        self.assertEqual(cpr.check(str(p))[0], 1)


class TestUnreachableIsNotTheSameAsUnreadable(Case):
    def test_missing_file_returns_2_not_1(self):
        """拿不到內容跟看不懂是兩件事，exit code 要分開。

        混在一起的話，一個連不上的網站會被當成「頁面壞了」，
        而真正的問題是根本沒到那裡。
        """
        code, _ = cpr.check(str(self.tmp / "沒有這個檔"))
        self.assertEqual(code, 2)

    def test_empty_content_returns_2(self):
        p = self.tmp / "empty.html"
        p.write_bytes(b"")
        self.assertEqual(cpr.check(str(p))[0], 2)


class TestUsableAsVerifier(Case):
    def test_exit_codes_work_from_the_command_line(self):
        """要能直接放進 verifier 的 cmd:，所以 exit code 必須是真的。"""
        good = self.write("g.html", '<meta charset="utf-8"><p>北極星</p>')
        bad = self.write("h.html", "<p>北極星</p>")
        r_good = subprocess.run([sys.executable, str(TOOL), str(good)],
                                capture_output=True)
        r_bad = subprocess.run([sys.executable, str(TOOL), str(bad)],
                               capture_output=True)
        self.assertEqual(r_good.returncode, 0)
        self.assertEqual(r_bad.returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
