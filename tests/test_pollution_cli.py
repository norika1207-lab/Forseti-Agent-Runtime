"""污染登記簿的人工登記入口。v5.0 §40

這個檔存在的理由跟 `test_evidence_cli.py` 同一個形狀：`pollution.py`
的 `record()` / `advance()` / `summary()` 2026-09-16 就寫好了，
桌面端（`desktop_api.pollution_panel()`）與交接契約（`contract.py`）
都在讀它，而**登一筆進去只能手寫 `python3 -c "import pollution; ..."`**
—— `NEXT.md` 自己印的那一行「自己查」就是那個寫法。缺的不是資料也不是
判準，是入口。

所以這裡守的不是「污染記錄對不對」（那是 `test_pollution.py`），
是「登記這個動作有沒有被做成一條會擋人的路」：

- 模板原樣送回去要被退。**這一條是被自己的量測逼出來的** ——
  第一版的 `template` 在 stderr 印著「原樣送回去會被退」，而實測
  原樣送回去 exit=0 登進去了一筆五欄全是尖括號的污染，在 `list` 裡
  跟填對的長得一模一樣。`record()` 的四條必填擋的是空的，而佔位符
  不是空的。**寫得出警告不等於有人在守。**
- 判準比對的對象是 `template()` 自己，不是抄一份佔位字串
- `--path` 不准被當成子指令，不然會去讀正本
- 打錯子指令不准掉進 `list` 回 0
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import pollution as P  # noqa: E402

POLL_SRC = (ROOT / "apps" / "forseti-cli" / "pollution.py").read_text(encoding="utf-8")


def _good() -> dict:
    return {
        "original_claim": "這一句當初是這樣寫的",
        "corrected_claim": "實際上是另一回事",
        "failure_mechanism": "把常數名當成功能存在",
        "source_events": ["tests/test_pollution_cli.py:1"],
        "verifier": "pytest",
        "radius_basis": "測試不量傳播半徑",
        "status": "OPEN",
    }


class _Box(unittest.TestCase):
    """每一條各自一個暫存目錄，而且**絕不碰正本**。

    `--path` 一律傳。少傳一次就會寫進 `.forseti/pollution.jsonl`，
    而那是這條線每一輪都在讀的正本。
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.log = self.tmp / "p.jsonl"

    def tearDown(self):
        self._td.cleanup()

    def write(self, obj, name: str = "in.json") -> str:
        p = self.tmp / name
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def run_cli(self, argv: list) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = P.main(argv)
        return rc, buf.getvalue()

    def seed(self, **over) -> str:
        """先登一筆真的進去，回它的 id。"""
        kw = dict(_good(), **over)
        rc, out = self.run_cli(["register", "--from", self.write(kw),
                                "--path", str(self.log)])
        self.assertEqual(rc, 0, out)
        return json.loads(self.log.read_text(encoding="utf-8").splitlines()[0])["id"]


class Placeholder(_Box):
    """模板原樣送回去這條路。第一版沒有守，是量出來的。"""

    def test_原樣送回去被退而且每一個必填欄位都被點名(self):
        rc, out = self.run_cli(["register", "--from", self.write(P.template()),
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        for k in ("original_claim", "corrected_claim", "failure_mechanism",
                  "source_events", "verifier"):
            self.assertIn(k, out)

    def test_被退的時候一個字都沒有寫進去(self):
        self.run_cli(["register", "--from", self.write(P.template()),
                      "--path", str(self.log)])
        self.assertFalse(self.log.exists())

    def test_判準比對的是模板自己不是抄一份(self):
        """模板改一個字，判準要跟著動。

        抄一份佔位字串到 `unfilled()` 的話，症狀是「守門說填過了、
        畫面上還是尖括號」—— 沒有人會發現，因為兩邊都不報錯。
        """
        fake = dict(P.template(), original_claim="<換過的佔位字串>")
        with mock.patch.object(P, "template", lambda: fake):
            self.assertIn("original_claim",
                          P.unfilled({"original_claim": "<換過的佔位字串>"}))
            self.assertNotIn("original_claim",
                             P.unfilled({"original_claim":
                                         "<錯的那句話，逐字抄，"
                                         "不要改寫成比較好看的版本>"}))

    def test_帶尖括號的真原話不算沒填(self):
        """判「值跟模板一模一樣」，不判「裡面有尖括號」。

        判太寬的話，一筆要登記 `<div>` 這種原話的污染會被誤退，
        而那種話正是最需要逐字保留的。
        """
        self.assertEqual(P.unfilled({"original_claim": "<div> 那一行是空的"}), [])

    def test_選填那兩欄空字串不算沒填(self):
        """`preventive_rule` 與 `regression_probe` 的模板值是空字串，
        不是空格子。沒填是合法的（那一筆就是「只靠人記得」）。"""
        self.assertEqual(P.unfilled({"preventive_rule": "",
                                     "regression_probe": ""}), [])


class Register(_Box):
    """登記這條路本身。"""

    def test_填好的登得進去而且落地一筆(self):
        pid = self.seed()
        self.assertTrue(pid.startswith("pol-"))
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 1)

    def test_不認得的欄位被退而不是靜默丟掉(self):
        kw = dict(_good(), failure_mechanizm="打錯字的那一欄")
        rc, out = self.run_cli(["register", "--from", self.write(kw),
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertIn("failure_mechanizm", out)
        self.assertFalse(self.log.exists())

    def test_收哪幾個欄位是去問record不是抄一份(self):
        """`record()` 哪天多一個欄位，這邊要跟著動。

        抄一份的症狀是畫面上只有「不認得的欄位」一句拒絕，
        沒有人會發現兩邊已經不一致。
        """
        got = set(P._kwargs_of(P.record))
        want = {p for p in inspect.signature(P.record).parameters
                if p not in ("path", "at")}
        self.assertEqual(got, want)
        self.assertIn("failure_mechanism", got)
        self.assertNotIn("path", got)

    def test_沒有from的時候不准去登一筆空的(self):
        rc, _ = self.run_cli(["register", "--path", str(self.log)])
        self.assertEqual(rc, 2)
        self.assertFalse(self.log.exists())


class Advance(_Box):
    """狀態轉換。CLI 只轉發，判準在 `advance()`，這裡守的是轉發沒有漏。"""

    def test_跳過中間狀態被擋(self):
        pid = self.seed()
        rc, out = self.run_cli(["advance", "--id", pid, "--to", "RESOLVED",
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertIn("不能直接到", out)

    def test_重驗要有人(self):
        pid = self.seed()
        rc, out = self.run_cli(["advance", "--id", pid, "--to", "REVERIFIED",
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertIn("verifier", out)

    def test_解決要有攔它的東西(self):
        pid = self.seed()
        self.run_cli(["advance", "--id", pid, "--to", "REVERIFIED",
                      "--verifier", "我", "--path", str(self.log)])
        rc, out = self.run_cli(["advance", "--id", pid, "--to", "RESOLVED",
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertIn("§40.2", out)

    def test_走完之後看得到轉換歷史(self):
        pid = self.seed()
        self.run_cli(["advance", "--id", pid, "--to", "REVERIFIED",
                      "--verifier", "我", "--path", str(self.log)])
        self.run_cli(["advance", "--id", pid, "--to", "RESOLVED",
                      "--regression-probe", "tests/x.py::y",
                      "--path", str(self.log)])
        rc, out = self.run_cli(["show", "--id", pid, "--path", str(self.log)])
        self.assertEqual(rc, 0)
        self.assertIn("RESOLVED", out)
        self.assertIn("OPEN → REVERIFIED", out)

    def test_少了id或目標狀態不准猜(self):
        rc, _ = self.run_cli(["advance", "--path", str(self.log)])
        self.assertEqual(rc, 2)


class Args(_Box):
    """參數怎麼被讀。跟另外四支 CLI 同一組陷阱。"""

    def test_第一個參數是旗標的時候不准被當成子指令(self):
        """`forseti pollution --path X` 把 `--path` 當子指令的話，
        `rest` 只剩下 X，於是讀的是**正本**而不是 X。"""
        rc, out = self.run_cli(["--path", str(self.log)])
        self.assertEqual(rc, 0)
        self.assertIn("0 筆", out)

    def test_每一個旗標漏掉值都退回(self):
        for flag in P.KNOWN_FLAGS:
            with self.subTest(flag=flag):
                rc, out = self.run_cli(["list", flag])
                self.assertEqual(rc, 2, flag)
                self.assertIn(flag, out)

    def test_旗標名打錯字被點名(self):
        rc, out = self.run_cli(["list", "--pathh", str(self.log)])
        self.assertEqual(rc, 2)
        self.assertIn("--pathh", out)

    def test_子指令打錯字不准掉進list(self):
        """掉進 `list` 的話會回 0 而且印一份看起來正常的報告 ——
        `pollution registr --from x` 的那個人以為自己登記過了。"""
        rc, out = self.run_cli(["registr", "--from", "x"])
        self.assertEqual(rc, 2)
        self.assertIn("registr", out)
        self.assertIn("register", out)

    def test_等號寫法讀得到同一個值(self):
        self.seed()
        rc, out = self.run_cli([f"--path={self.log}"])
        self.assertEqual(rc, 0)
        self.assertIn("1 筆", out)


class Wiring(_Box):
    """名單與實際接線不准漂開。"""

    def test_每一個認得的旗標都真的有人讀(self):
        """守門說認得、`main()` 裡沒人讀的旗標，打對了也沒用，
        跟打錯字一樣靜默。"""
        read = set(re.findall(r'_arg\(rest,\s*"(--[a-z-]+)"\)', POLL_SRC))
        for flag in P.KNOWN_FLAGS:
            self.assertIn(flag, read, flag)

    def test_每一支子指令在main裡都有分支(self):
        for sub in P.SUBCOMMANDS:
            if sub == "list":
                continue  # list 是掉到最後那一段，沒有 `sub ==` 那一行
            self.assertIn(f'sub == "{sub}"', POLL_SRC, sub)

    def test_三支判準只有一份而且不在這個檔裡(self):
        """`cliargs.py` 是收斂的落點。這個檔自己再寫一份的話，
        就是第六份 —— 而那正是它存在要擋的事。"""
        for name in ("_arg", "_flag_without_value", "_unknown_flags"):
            self.assertNotIn(f"def {name}(", POLL_SRC, name)
        import cliargs  # noqa: PLC0415
        self.assertIs(P._arg, cliargs.arg)
        self.assertIs(P._flag_without_value, cliargs.flag_without_value)
        self.assertIs(P._unknown_flags, cliargs.unknown_flags)


class ListView(_Box):
    """空的時候與有東西的時候。"""

    def test_空的時候不准自己登一筆讓那一格好看(self):
        rc, out = self.run_cli(["list", "--path", str(self.log)])
        self.assertEqual(rc, 0)
        self.assertIn("不自動登記", out)
        self.assertFalse(self.log.exists())

    def test_守跟人兩堆的分母寫在畫面上(self):
        """`summary()['guarded']` 的分母是全部，這一節的分母是
        `open_records()`。兩個數字在同一頁上不講分母會打架。"""
        self.seed()
        rc, out = self.run_cli(["list", "--path", str(self.log)])
        self.assertEqual(rc, 0)
        self.assertIn("open_records()", out)
        self.assertIn("只靠人記得", out)

    def test_有守門的那一筆左邊那格不一樣(self):
        self.seed(regression_probe="tests/x.py::y")
        rc, out = self.run_cli(["list", "--path", str(self.log)])
        self.assertIn("守", out)
        self.assertIn("0 筆現在只靠人記得", out)


if __name__ == "__main__":
    unittest.main()
