"""證據的人工登記入口。v5.0 §7.2

這個檔存在的理由：2026-09-18 的幾輪把 `Evidence` 這個實體、它的落地
（`record()` / `load()` / `get()`）、以及 claim 那一端的
`attach_evidence()` 都做好了，而 `.forseti/evidence.jsonl` 仍然 0 筆。
缺的不是資料也不是程式碼，是**人沒有地方登**。

所以這裡守的不是「證據對不對」（那是 `test_evidence.py`），
是「登記這個動作有沒有被做成一條會擋人的路」：

- 模板原樣送回去要被退，不然會登記成一筆每一欄都有值、
  `Evidence.__post_init__` 全部放行、畫面上跟真的一模一樣的假證據
- `--path` 不准被當成子指令，不然會去讀正本而回報 0 筆 ——
  而正本此刻真的是 0 筆，所以錯的答案跟對的答案長得一樣
- 空的時候不准自己登一筆讓那一格好看
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import evidence as E  # noqa: E402


def _good() -> dict:
    return {
        "about": "這一筆是測試用的觀察",
        "sources": ["tests/test_evidence_cli.py"],
        "strength": "E2",
        "captured_by": "pytest",
        "content_hash": "",
        "upstream": [],
        "independence_basis": "",
        "authority": "",
    }


class _Box(unittest.TestCase):
    """每一條各自一個暫存目錄，而且**絕不碰正本**。

    `--path` 一律傳。少傳一次就會寫進 `.forseti/evidence.jsonl`，
    而 `tests/conftest.py` 的寫入監控會抓到 —— 那條防線在這裡是
    最後一道，不是第一道。
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.log = self.tmp / "e.jsonl"

    def tearDown(self):
        self._td.cleanup()

    def write(self, obj, name: str = "in.json") -> str:
        p = self.tmp / name
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return str(p)

    def run_cli(self, argv: list) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            rc = E.main(argv)
        return rc, buf.getvalue()


class Template(_Box):
    """模板本身的形狀。"""

    def test_每一個必填欄位都是空格子不是預設值(self):
        tpl = E.template()
        for k in E._MUST_FILL:
            v = tpl[k]
            if isinstance(v, list):
                self.assertTrue(v and all(E.is_placeholder(x) for x in v), k)
            else:
                self.assertTrue(E.is_placeholder(v), k)

    def test_模板刻意不預填觀察時刻(self):
        """`observed_at` 進 id 的雜湊（`_make_eid()`），預填的話那個時間
        會變成產模板的時刻，而人拿模板去登的常常是更早發生的觀察。"""
        self.assertNotIn("observed_at", E.template())

    def test_選填的那幾欄是空字串不是空格子(self):
        """空字串送回去要能過，空格子送回去要被退。兩種不可以混。"""
        tpl = E.template()
        self.assertEqual(tpl["content_hash"], "")
        self.assertEqual(tpl["authority"], "")
        self.assertEqual(tpl["upstream"], [])


class Placeholder(_Box):
    """模板原樣送回去這條路。"""

    def test_原樣送回去被退而且每一個必填欄位都被點名(self):
        rc, out = self.run_cli(["register", "--from", self.write(E.template()),
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        for k in E._MUST_FILL:
            self.assertIn(k, out)

    def test_被退的時候一個字都沒有寫進去(self):
        self.run_cli(["register", "--from", self.write(E.template()),
                      "--path", str(self.log)])
        self.assertFalse(self.log.exists())

    def test_空格子判準只認尖括號包住整個值(self):
        """「<」在句子中間不算。判太寬的話一句正常的話會被誤退。"""
        self.assertIs(E.is_placeholder("<誰看到的　一定要填>"), True)
        self.assertIs(E.is_placeholder("a < b 這個斷言"), False)
        self.assertIs(E.is_placeholder(""), False)
        self.assertIs(E.is_placeholder(3), False)

    def test_選填欄位留著空格子也要被退(self):
        """`_MUST_FILL` 以外的欄位沒填不是錯，但填著空格子是。"""
        kw = dict(_good(), authority="<E4 才要：具名的授權方>")
        rc, out = self.run_cli(["register", "--from", self.write(kw),
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertIn("authority", out)


class Args(_Box):
    """參數怎麼被讀。釘住 2026-09-18 實測撞到的那個靜默錯誤。"""

    def test_第一個參數是旗標的時候不准被當成子指令(self):
        """`forseti evidence --path X` 先前會把 `--path` 當成子指令名，
        於是 `rest` 只剩下 X，`_arg(rest, "--path")` 找不到，
        結果是讀正本而不是讀 X。正本此刻 0 筆，所以那個錯的答案
        跟對的答案長得一模一樣，不會有人發現。
        """
        rc, _ = self.run_cli(["register", "--from", self.write(_good()),
                              "--path", str(self.log)])
        self.assertEqual(rc, 0)
        rc, out = self.run_cli(["--path", str(self.log)])
        self.assertEqual(rc, 0)
        self.assertIn("1 筆", out)
        self.assertIn("這一筆是測試用的觀察", out)

    def test_有子指令的時候照樣讀得到路徑(self):
        self.run_cli(["register", "--from", self.write(_good()),
                      "--path", str(self.log)])
        rc, out = self.run_cli(["list", "--path", str(self.log)])
        self.assertEqual(rc, 0)
        self.assertIn("1 筆", out)

    def test_不帶路徑的時候預設去正本(self):
        """守門要問得到「不傳參數的時候它去哪」
        （`tests/test_module_write_targets.py` 的 `_default_of`）。"""
        self.assertEqual(E.log_path().name, "evidence.jsonl")
        self.assertEqual(E.log_path().parent.name, ".forseti")


class Register(_Box):
    """登記這條路上各種會被退的理由。"""

    def test_填好的能登而且讀得回來(self):
        rc, out = self.run_cli(["register", "--from", self.write(_good()),
                                "--path", str(self.log)])
        self.assertEqual(rc, 0)
        rows = E.load(self.log)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["about"], "這一筆是測試用的觀察")
        self.assertTrue(E.is_evidence_id(rows[0]["id"]))
        self.assertIn(rows[0]["id"], out)

    def test_欄位名打錯被點名而不是默默丟掉(self):
        kw = _good()
        kw["about_"] = kw.pop("about")
        rc, out = self.run_cli(["register", "--from", self.write(kw),
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertIn("about_", out)

    def test_欄位名打錯比沒有填先報(self):
        """兩個都會成立（`about` 不見了）。先報哪一個決定人去看哪裡，
        而打錯欄位名才是根因。"""
        kw = _good()
        kw["about_"] = kw.pop("about")
        _, out = self.run_cli(["register", "--from", self.write(kw),
                               "--path", str(self.log)])
        self.assertIn("不認得的欄位", out)
        self.assertNotIn("沒有填", out)

    def test_E3只給一個來源被退(self):
        kw = dict(_good(), strength="E3")
        rc, out = self.run_cli(["register", "--from", self.write(kw),
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertIn("獨立佐證", out)

    def test_E4沒有授權方被退(self):
        kw = dict(_good(), strength="E4")
        rc, out = self.run_cli(["register", "--from", self.write(kw),
                                "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertIn("authority", out)

    def test_不是一個物件被退(self):
        p = self.tmp / "arr.json"
        p.write_text("[1,2,3]", encoding="utf-8")
        rc, out = self.run_cli(["register", "--from", str(p),
                                "--path", str(self.log)])
        self.assertEqual(rc, 2)
        self.assertIn("JSON 物件", out)

    def test_檔案不存在被退而不是當成空的(self):
        rc, out = self.run_cli(["register", "--from", str(self.tmp / "沒有這個檔"),
                                "--path", str(self.log)])
        self.assertEqual(rc, 2)
        self.assertIn("讀不到", out)

    def test_沒給from的時候講得出模板怎麼產(self):
        rc, out = self.run_cli(["register"])
        self.assertEqual(rc, 2)
        self.assertIn("template", out)


class NoAutoRegister(_Box):
    """§8.3。這一支不准為了讓那一格好看而自己登。"""

    def test_空的時候印出來的是零筆而且沒有建檔(self):
        rc, out = self.run_cli(["list", "--path", str(self.log)])
        self.assertEqual(rc, 0)
        self.assertIn("0 筆", out)
        self.assertFalse(self.log.exists())

    def test_空的時候講得出為什麼是空的(self):
        _, out = self.run_cli(["list", "--path", str(self.log)])
        self.assertIn("不自動登記", out)
        self.assertIn("§8.3", out)

    def test_show找不到的時候回一而不是造一筆(self):
        rc, _ = self.run_cli(["show", "--id", "ev-0123456789",
                              "--path", str(self.log)])
        self.assertEqual(rc, 1)
        self.assertFalse(self.log.exists())


class Levels(_Box):
    def test_levels印得出五級而且照順序(self):
        rc, out = self.run_cli(["levels"])
        self.assertEqual(rc, 0)
        for k, _, _ in E.LEVELS:
            self.assertIn(k, out)
        self.assertLess(out.index("E0"), out.index("E4"))


class Dispatch(_Box):
    """接進 `forseti` 這條路。"""

    def test_forseti認得evidence這個指令(self):
        r = subprocess.run(
            [sys.executable, str(ROOT / "apps" / "forseti-cli" / "forseti.py"),
             "evidence", "levels"],
            capture_output=True, text=True, cwd=str(ROOT), timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("E0", r.stdout)
        self.assertIn("E4", r.stdout)

    def test_不認得的子指令不當成list(self):
        """打錯子指令要看得出來。掉進 list 的話會回 0 而且印一份
        看起來正常的報告，於是打錯字跟沒打錯長得一樣。"""
        rc, out = self.run_cli(["registr", "--path", str(self.log)])
        self.assertFalse(rc == 0 and "登記簿" in out,
                         "`registr` 掉進了預設那一條")


if __name__ == "__main__":
    unittest.main()
