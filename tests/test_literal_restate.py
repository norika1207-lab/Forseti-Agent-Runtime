#!/usr/bin/env python3
"""列舉常數的值被手打一次而打錯了，這件事有沒有人守。

`tools/declared-only-check.py` 那一輪收尾時寫下一個缺口：十六條
`REFERENCE` 的值在別處以字面字串重打，**拼錯不會紅**。這一組守的
就是那個缺口。做法與三個判紅條件在 `tools/literal-restate-check.py`，
連同它六個盲點。

## 這一組分兩半，理由不一樣

**合成目錄那一半**（`class 掃描器`）在 `tmp` 造幾個小檔跑完整流程。
它驗的是掃描器本身的行為，跟這個 repo 現在長什麼樣子無關，
所以它不會隨開發腐爛。

**真 repo 那一半**（`class 這個repo現在的狀態`）驗守門現在是綠的、
豁免登記簿沒有過期。它會隨開發變動 —— 那正是它存在的目的。

## 三條不能省的

一，**條件 2（全 repo 唯一）不能拿掉。** 拿掉之後
`owner.py:326` 的 `provenance="OBSERVED"` 會被判成 `SILENCE` 裡
`"UNOBSERVED"` 的拼錯，而它是合法值（`event_ledger.py:236` 的欄位
預設值、`starvation.py:61` 的常數值）。那是第一版唯一的一條命中，
而它是誤報。`test_repo唯一這個條件拿掉就會誤報` 拿真 repo 的
`OBSERVED` 當回歸測試。

二，**距離 0 不算拼錯。** 那是重打，真 repo 有 289 次，
把它們判紅只會讓這支守門被關掉。

三，**這一支自己不可以參與計數。** `tools/` 在 `COUNT_DIRS` 底下，
所以這個檔寫下的任何 ALL_CAPS 字面字串會把 repo 計數加一 ——
一個真的打錯的字串只要碰巧被寫進那支的說明或白名單，條件 2
就不成立，它會安靜地從紅名單消失。往綠的方向壞。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "literal-restate-check.py"


def _load():
    """檔名有連字號，`import` 進不來，所以用檔案路徑載。

    放進 `sys.modules` 的理由跟 `test_declared_only.py` 同一條：
    Python 3.9 解析 dataclass 的型別註記時要找得到自己的模組。
    """
    spec = importlib.util.spec_from_file_location("forseti_literal_restate",
                                                  TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forseti_literal_restate"] = mod
    spec.loader.exec_module(mod)
    return mod


LR = _load()


class 掃描器(unittest.TestCase):
    """合成目錄。跟這個 repo 現在長什麼樣子無關。"""

    def _scan(self, defs: dict[str, str], extra: dict[str, str] | None = None,
              js: dict[str, str] | None = None):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        d = root / "src"
        d.mkdir()
        for name, body in defs.items():
            (d / name).write_text(body, encoding="utf-8")
        if extra:
            o = root / "other"
            o.mkdir()
            for name, body in extra.items():
                (o / name).write_text(body, encoding="utf-8")
        if js:
            j = root / "web"
            j.mkdir()
            for name, body in js.items():
                (j / name).write_text(body, encoding="utf-8")
        return LR.scan(def_dir=d, repo=root,
                       count_dirs=("src", "other"), js_dirs=("web",))

    # ── 判紅的那一條路走得通 ──────────────────────────────

    def test_打錯一個字元會紅(self):
        rep = self._scan({"a.py": (
            'STEPS = ("PRESERVE_RESULTS", "SYNTHESIS_ONLY")\n'
            'def plan():\n'
            '    return ["PRESERVE_RESULTS", "SYNTHESIS_OLNY"]\n'
        )})
        self.assertEqual([s.literal for s in rep.suspects], ["SYNTHESIS_OLNY"])
        self.assertEqual(rep.suspects[0].member, "SYNTHESIS_ONLY")
        self.assertEqual(rep.suspects[0].dist, 2)
        self.assertEqual(rep.suspects[0].const, "STEPS")

    def test_打錯的位置指得回行號(self):
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            '\n'
            'def f():\n'
            '    return "ALPHA_ONF"\n'
        )})
        self.assertEqual(rep.suspects[0].lineno, 4)
        self.assertEqual(rep.suspects[0].where, "a.py:4")

    # ── 三個條件，每一個拿掉都會出事 ──────────────────────

    def test_距離0是重打不是拼錯(self):
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            'def f():\n'
            '    return "ALPHA_ONE"\n'
        )})
        self.assertEqual(rep.suspects, [])
        self.assertEqual([(r.member, r.count) for r in rep.restated],
                         [("ALPHA_ONE", 1)])

    def test_距離3不算(self):
        """守的是現在這個閾值的行為。

        **不是「3 一定會出事」** —— 2026-09-17 實測把 `MAX_DISTANCE`
        放寬到 3，真 repo 一樣 0 命中 0 誤報。理由見那支的
        `MAX_DISTANCE` 說明。
        """
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            'def f():\n'
            '    return "ALPHA_XYZ"\n'
        )})
        self.assertEqual(rep.suspects, [])

    def test_repo裡出現第二次就不算拼錯(self):
        """條件 2。它在別處也存在，所以它是一個合法的值。"""
        rep = self._scan(
            {"a.py": 'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
                     'def f():\n'
                     '    return "ALPHA_ONF"\n'},
            extra={"b.py": 'X = f("ALPHA_ONF")\n'})
        self.assertEqual(rep.suspects, [])

    def test_JS側出現過就不算拼錯(self):
        rep = self._scan(
            {"a.py": 'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
                     'def f():\n'
                     '    return "ALPHA_ONF"\n'},
            js={"app.js": 'const k = "ALPHA_ONF";\n'})
        self.assertEqual(rep.suspects, [])

    def test_不像識別字的字串不看(self):
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            'def f():\n'
            '    return "alpha one"\n'
        )})
        self.assertEqual(rep.suspects, [])

    def test_太短的字串不看(self):
        rep = self._scan({"a.py": (
            'STEPS = ("AB", "CD")\n'
            'def f():\n'
            '    return "AC"\n'
        )})
        self.assertEqual(rep.enums, 0)
        self.assertEqual(rep.suspects, [])

    def test_只有一個成員不算列舉(self):
        """單值常數沒有對照組，構不成「同一組名字裡打錯一個」。"""
        rep = self._scan({"a.py": (
            'ONE = "ALPHA_ONE"\n'
            'def f():\n'
            '    return "ALPHA_ONF"\n'
        )})
        self.assertEqual(rep.enums, 0)
        self.assertEqual(rep.suspects, [])

    # ── 定義自己不算重打，也不算拼錯 ──────────────────────

    def test_定義自己不算重打(self):
        rep = self._scan({"a.py": 'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'})
        self.assertEqual(rep.restated, [])
        self.assertEqual(rep.suspects, [])

    def test_兩個常數列同一個值不會互相判成拼錯(self):
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            'MEANING = {"ALPHA_ONE": "x", "BETA_TWO": "y"}\n'
        )})
        self.assertEqual(rep.suspects, [])
        self.assertEqual(rep.restated, [])

    def test_多行定義後面緊接的程式碼不會被吃掉(self):
        """跳過用的是節點 id 不是行號區間，理由寫在 `enums_of` 裡。"""
        rep = self._scan({"a.py": (
            'STEPS = (\n'
            '    "ALPHA_ONE",\n'
            '    "BETA_TWO",\n'
            ')\n'
            'def f():\n'
            '    return "ALPHA_ONF"\n'
        )})
        self.assertEqual([s.literal for s in rep.suspects], ["ALPHA_ONF"])

    # ── 手打統計：報數字，不判紅 ──────────────────────────

    def test_手打次數與行號都算得出來(self):
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            'def f():\n'
            '    return ["ALPHA_ONE", "BETA_TWO"]\n'
            'def g():\n'
            '    return "ALPHA_ONE"\n'
        )})
        by = {r.member: r for r in rep.restated}
        self.assertEqual(by["ALPHA_ONE"].count, 2)
        self.assertEqual(by["ALPHA_ONE"].lines, (3, 5))
        self.assertEqual(by["BETA_TWO"].count, 1)
        self.assertEqual(rep.restated_total, 3)

    def test_手打歸屬得回哪幾個常數(self):
        """真 repo 裡一個成員常常同時屬於 `TYPES` 與 `TYPE_MEANING`。

        `MEANING` 要有兩個 key 才算列舉（`MIN_ENUM_MEMBERS`），
        所以這裡兩個都列 —— 只有一個 key 的版本由
        `test_只有一個成員不算列舉` 守。
        """
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            'MEANING = {"ALPHA_ONE": "x", "BETA_TWO": "y"}\n'
            'def f():\n'
            '    return "ALPHA_ONE"\n'
        )})
        by = {r.member: r for r in rep.restated}
        self.assertEqual(by["ALPHA_ONE"].consts, ("MEANING", "STEPS"))

    def test_手打再多也不判紅(self):
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            'def f():\n'
            '    return ["ALPHA_ONE"] * 3 + ["BETA_TWO"]\n'
        )})
        self.assertEqual(rep.suspects, [])
        self.assertGreater(rep.restated_total, 0)

    # ── 豁免登記簿兩個方向都釘住 ──────────────────────────

    def test_登記豁免之後不再判紅(self):
        rep = self._scan({"a.py": (
            'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'
            'def f():\n'
            '    return "ALPHA_ONF"\n'
        )})
        self.assertEqual(len(rep.unexempted), 1)
        key = rep.suspects[0].key
        LR.EXEMPT[key] = "測試用"
        self.addCleanup(LR.EXEMPT.pop, key, None)
        self.assertEqual(rep.unexempted, [])

    def test_登記的豁免不再命中就算過期(self):
        rep = self._scan({"a.py": 'STEPS = ("ALPHA_ONE", "BETA_TWO")\n'})
        key = ("a", "NOT_THERE", "ALPHA_ONE")
        LR.EXEMPT[key] = "測試用"
        self.addCleanup(LR.EXEMPT.pop, key, None)
        self.assertEqual([k for k, _ in rep.stale_exempt], [key])

    # ── 環境性的兩條 ──────────────────────────────────────

    def test_AppleDouble檔不會讓掃描炸掉(self):
        """工作碟是 exFAT，macOS 會放 `._a.py`，它不是 UTF-8。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        d = root / "src"
        d.mkdir()
        (d / "a.py").write_text('STEPS = ("ALPHA_ONE", "BETA_TWO")\n',
                                encoding="utf-8")
        (d / "._a.py").write_bytes(b"\x00\x05\x16\x07\xff\xfe not utf-8")
        rep = LR.scan(def_dir=d, repo=root, count_dirs=("src",), js_dirs=())
        self.assertEqual(rep.enums, 1)

    def test_語法壞掉的檔跳過而不是炸掉(self):
        rep = self._scan({"a.py": 'STEPS = ("ALPHA_ONE", "BETA_TWO")\n',
                          "b.py": 'def ( oops\n'})
        self.assertEqual(rep.enums, 1)


class 距離函式(unittest.TestCase):
    def test_相同是0(self):
        self.assertEqual(LR.distance("ABC", "ABC"), 0)

    def test_換一個字元是1(self):
        self.assertEqual(LR.distance("ABC", "ABD"), 1)

    def test_換兩個字元是2(self):
        self.assertEqual(LR.distance("ABCD", "ABXY"), 2)

    def test_長度差太多直接剪枝(self):
        self.assertGreater(LR.distance("A", "ABCDEFG"), LR.MAX_DISTANCE)

    def test_調換相鄰兩個字元是2(self):
        """`SYNTHESIS_ONLY` 打成 `SYNTHESIS_OLNY` 就是這個形狀。"""
        self.assertEqual(LR.distance("ONLY", "OLNY"), 2)


class 這個repo現在的狀態(unittest.TestCase):
    """會隨開發變動。那正是它存在的目的。"""

    @classmethod
    def setUpClass(cls):
        cls.rep = LR.scan()

    def test_沒有疑似打錯的字面值(self):
        bad = [f'{s.where} "{s.literal}" 像 "{s.member}"'
               for s in self.rep.unexempted]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_豁免登記簿沒有過期條目(self):
        self.assertEqual(self.rep.stale_exempt, [])

    def test_真的掃到東西了(self):
        """全部回 0 也會讓上面兩條綠，所以要有下界。"""
        self.assertGreater(self.rep.enums, 20)
        self.assertGreater(self.rep.members, 100)

    def test_手打是真的存在的現象(self):
        """`--restated` 那個數字不是 0，所以它值得被量。"""
        self.assertGreater(self.rep.restated_total, 50)

    def test_starvation的RECOVERY_STEPS就是那個例子(self):
        """檔頭舉的例子必須是真的，不然說明會腐爛。"""
        hit = [r for r in self.rep.restated
               if r.module == "starvation" and "RECOVERY_STEPS" in r.consts]
        self.assertTrue(hit, "RECOVERY_STEPS 的成員不再被手打了，檔頭要改")
        self.assertIn("SYNTHESIS_ONLY", {r.member for r in hit})

    def test_repo唯一這個條件拿掉就會誤報(self):
        """條件 2 的回歸測試，拿真 repo 的 `OBSERVED` 當實例。

        `owner.py:326` 的 `provenance="OBSERVED"` 跟 `SILENCE`
        （`owner.py:457`）裡的 `"UNOBSERVED"` 距離 2，而它完全合法。
        擋住它的是「全 repo 只出現這一次」—— 這一條驗那個前提還在：
        `OBSERVED` 真的在 repo 裡出現不只一次。
        """
        counts = LR.repo_literal_counts()
        self.assertGreater(counts["OBSERVED"], 1)
        self.assertEqual(LR.distance("OBSERVED", "UNOBSERVED"), 2)

    def test_這一組自己不可以參與計數(self):
        """往綠的方向壞的那個方向，而且它真的發生過。

        `tools/` 與 `tests/` 都在 `COUNT_DIRS` 底下。這一組自己寫下的
        ALL_CAPS 字面字串如果被算進去，一個真的打錯的字串只要碰巧
        出現在說明、豁免登記簿、或測試的負例裡，條件 2 就不成立，
        它會安靜地從紅名單消失。

        **2026-09-17 第一次反向驗證就是被這件事擋下來的**，見下面
        `test_把真檔打錯一個字會紅` 的說明。
        """
        for f, root in ((TOOL, REPO / "tools"),
                        (Path(__file__), REPO / "tests")):
            got = [q.resolve() for q in LR.py_files(root)]
            self.assertNotIn(f.resolve(), got, f"{f.name} 沒有被排除")
            allf = [q.resolve() for q in LR.py_files(root, skip_self=False)]
            self.assertIn(f.resolve(), allf)

    def test_排除清單裡的檔案必須真的存在(self):
        """排除用的是硬寫的路徑，檔案改名之後排除會安靜失效。

        失效的方向是往綠的 —— 測試檔的負例又開始參與計數，
        而不會有任何東西紅。所以路徑本身要有人守。
        """
        for f in LR._SELF_FILES:
            self.assertTrue(f.exists(), f"{f} 不在了，排除已經失效")
        self.assertIn(Path(__file__).resolve(), LR._SELF_FILES)

    def test_把真檔打錯一個字會紅(self):
        """反向驗證做成常設測試，不是只做一次。

        在記憶體裡改，不動磁碟：讀 `starvation.py`，把
        `recovery_plan()` 手打的 `"SYNTHESIS_ONLY"` 換成
        `"SYNTHESIS_OLNY"`，寫進一個合成目錄再掃。

        **`"SYNTHESIS_OLNY"` 這個字串只出現在這個檔裡**，
        而這個檔在 `_SELF_FILES` 裡不參與計數，所以條件 2
        仍然成立 —— 那正是上面兩條守的東西。
        """
        src = (REPO / "apps" / "forseti-cli" / "starvation.py").read_text(
            encoding="utf-8")
        typo = "SYNTHESIS_" + "OLNY"
        bad = src.replace('"SYNTHESIS_ONLY", "AVOID_RERUN"',
                          f'"{typo}", "AVOID_RERUN"')
        self.assertNotEqual(bad, src, "starvation.py 的那一行變了，這條要改")
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            d = root / "src"
            d.mkdir()
            (d / "starvation.py").write_text(bad, encoding="utf-8")
            rep = LR.scan(def_dir=d, repo=root, count_dirs=("src",), js_dirs=())
        self.assertEqual([s.literal for s in rep.unexempted], [typo])
        self.assertEqual(rep.unexempted[0].member, "SYNTHESIS_ONLY")
        self.assertEqual(rep.unexempted[0].const, "RECOVERY_STEPS")


class 小寫鍵名(unittest.TestCase):
    """2026-09-17 補的那一半。合成目錄，跟這個 repo 現在長什麼樣無關。

    ## 為什麼小寫要自己一組而不是把 `IDENT_RE` 放寬

    三個閾值有兩個不一樣。距離上界小寫收到 1（量測理由見那支的
    `LOWER_MAX_DISTANCE`），而且小寫多一層屬性存取白名單
    —— 因為小寫鍵名的下游讀者常常是 `obj.key` 不是引號字串，
    字串計數看不到它。ALL_CAPS 沒有這個問題。

    把兩件事塞進同一組閾值，等於讓其中一邊承受另一邊的誤報率。
    """

    def _scan(self, defs: dict[str, str], extra: dict[str, str] | None = None,
              js: dict[str, str] | None = None,
              attr: dict[str, str] | None = None,
              prof=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        d = root / "src"
        d.mkdir()
        for name, body in defs.items():
            (d / name).write_text(body, encoding="utf-8")
        for sub, files in (("other", extra), ("web", js), ("attr", attr)):
            if not files:
                continue
            o = root / sub
            o.mkdir()
            for name, body in files.items():
                (o / name).write_text(body, encoding="utf-8")
        return LR.scan(def_dir=d, repo=root,
                       count_dirs=("src", "other"), js_dirs=("web",),
                       attr_dirs=("attr",), prof=prof or LR.LOWER)

    # ── 判紅那一條路 ─────────────────────────────────────

    def test_小寫鍵名打錯一個字會紅(self):
        rep = self._scan({"a.py": (
            'KEYS = ("session_id", "tool_use")\n'
            'def f(d):\n'
            '    return d["tool_usa"]\n'
        )})
        self.assertEqual([s.literal for s in rep.unexempted], ["tool_usa"])
        self.assertEqual(rep.unexempted[0].member, "tool_use")
        self.assertEqual(rep.unexempted[0].const, "KEYS")
        self.assertEqual(rep.unexempted[0].dist, 1)
        self.assertEqual(rep.profile, "lower")

    def test_小寫側距離2不算(self):
        """釘住 `LOWER_MAX_DISTANCE` 現在這個值的行為。

        **不是「距離 2 一定是誤報」**，是「小寫短字彼此距離 2 的
        碰撞率高到不值得判紅」—— 量測見那支的常數說明，
        真 repo 上 `"save"` 對到 `"name"` 就是這樣來的。
        """
        rep = self._scan({"a.py": (
            'KEYS = ("session_id", "tool_use")\n'
            'def f(d):\n'
            '    return d["tool_xsa"]\n'
        )})
        self.assertEqual(rep.suspects, [])

    def test_同一個距離2在ALL_CAPS側會紅(self):
        """兩側閾值真的不一樣，不是說明寫著不一樣而已。

        同樣的形狀、同樣的距離 2，換成 ALL_CAPS 就判紅。
        """
        rep = self._scan({"a.py": (
            'KEYS = ("SESSION_ID", "TOOL_USE")\n'
            'def f(d):\n'
            '    return d["TOOL_XSA"]\n'
        )}, prof=LR.UPPER)
        self.assertEqual([s.literal for s in rep.unexempted], ["TOOL_XSA"])
        self.assertEqual(rep.unexempted[0].dist, 2)

    # ── 屬性存取白名單 ───────────────────────────────────

    def test_以屬性形式出現過就不算拼錯(self):
        """這一條是被真 repo 的一次誤報逼出來的，不是預防性假設。

        `desktop_api.py:2091` 的 `"stale_total"` 被判成 `FEATURES`
        的 `"stall_total"` 的拼錯（距離 1），而它是活的鍵，
        讀它的是 `desktop/ui/app.js` 的 `t.stale_total`。
        """
        rep = self._scan({"a.py": (
            'KEYS = ("stall_total", "scanned")\n'
            'def f(d):\n'
            '    return d["stale_total"]\n'
        )}, attr={"app.js": "const n = t.stale_total ? 1 : 0;\n"})
        self.assertEqual(rep.suspects, [])

    def test_沒有那個屬性就會紅(self):
        """上一條的對照組。拿掉屬性來源，同一份定義就判紅。

        沒有這一條，上面那條綠掉的原因可能只是別的東西。
        """
        rep = self._scan({"a.py": (
            'KEYS = ("stall_total", "scanned")\n'
            'def f(d):\n'
            '    return d["stale_total"]\n'
        )})
        self.assertEqual([s.literal for s in rep.unexempted], ["stale_total"])

    def test_屬性白名單只在小寫側生效(self):
        """`UPPER.use_attr` 是 False，所以 ALL_CAPS 側不查這一層。"""
        self.assertFalse(LR.UPPER.use_attr)
        self.assertTrue(LR.LOWER.use_attr)

    def test_兩種風格的閾值真的不一樣(self):
        self.assertEqual(LR.UPPER.max_distance, LR.MAX_DISTANCE)
        self.assertEqual(LR.LOWER.max_distance, LR.LOWER_MAX_DISTANCE)
        self.assertLess(LR.LOWER.max_distance, LR.UPPER.max_distance)

    def test_形狀互不相容(self):
        """大寫的字串不會被小寫風格收，反之亦然。"""
        self.assertTrue(LR.is_ident("TOOL_USE", LR.UPPER))
        self.assertFalse(LR.is_ident("TOOL_USE", LR.LOWER))
        self.assertTrue(LR.is_ident("tool_use", LR.LOWER))
        self.assertFalse(LR.is_ident("tool_use", LR.UPPER))

    def test_預設風格仍然是ALL_CAPS(self):
        """既有呼叫端一個字都沒改，所以預設不能變。"""
        self.assertTrue(LR.is_ident("TOOL_USE"))
        self.assertFalse(LR.is_ident("tool_use"))


class 跨風格(unittest.TestCase):
    """兩個風格共用一張 `EXEMPT`，所以過期要一起算。"""

    def test_單獨一份報告會把另一個風格的豁免誤判成過期(self):
        """這是 `stale_across()` 存在的理由，寫成測試不是寫在註解裡。"""
        key = ("nowhere", "tool_usa", "tool_use")
        LR.EXEMPT[key] = "測試用"
        self.addCleanup(LR.EXEMPT.pop, key, None)
        upper = LR.scan(prof=LR.UPPER)
        self.assertIn(key, [k for k, _ in upper.stale_exempt])

    def test_跨風格算過期看的是兩邊命中的聯集(self):
        key = ("a", "tool_usa", "tool_use")
        LR.EXEMPT[key] = "測試用"
        self.addCleanup(LR.EXEMPT.pop, key, None)
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            d = root / "src"
            d.mkdir()
            (d / "a.py").write_text(
                'KEYS = ("session_id", "tool_use")\n'
                'def f(d):\n'
                '    return d["tool_usa"]\n', encoding="utf-8")
            reps = {p.key: LR.scan(def_dir=d, repo=root, count_dirs=("src",),
                                   js_dirs=(), attr_dirs=(), prof=p)
                    for p in LR.PROFILES}
        # 小寫那一份命中了它，所以跨風格看不算過期。
        self.assertEqual(LR.stale_across(reps), [])
        # 而單看 ALL_CAPS 那一份會說它過期 —— 那正是不能單看的原因。
        self.assertIn(key, [k for k, _ in reps["upper"].stale_exempt])


class 這個repo現在的小寫狀態(unittest.TestCase):
    """會隨開發變動，那正是它存在的目的。"""

    @classmethod
    def setUpClass(cls):
        cls.rep = LR.scan(prof=LR.LOWER)

    def test_小寫側現在沒有疑似打錯(self):
        self.assertEqual(
            [f'{s.where} "{s.literal}" ~ "{s.member}"'
             for s in self.rep.unexempted], [])

    def test_小寫側真的掃到東西(self):
        """0 個列舉的話上一條會空著全綠，那是假的綠。"""
        self.assertGreater(self.rep.enums, 10)
        self.assertGreater(self.rep.members, 100)

    def test_ALL_CAPS那一側的數字沒有被這次改動動到(self):
        """回歸。2026-09-17 加小寫之前量的是 70 個列舉、266 個成員。"""
        up = LR.scan(prof=LR.UPPER)
        # 2026-09-17: 70/266 → 72/290。`apps/forseti-cli/probemodel.py`
        # 帶進來的（§15 模型軸的九題與它的常數）。這個 class 的
        # docstring 寫著「會隨開發變動，那正是它存在的目的」，
        # 所以這裡更新數字，不是放寬判準。
        #
        # 2026-09-17 22:xx: 72/290 → 73/292。`apps/forseti-cli/attempts.py`
        # 的 `KINDS`（ATTEMPT / RELEASE）帶進來的，**只有它一個**。
        # 同一支的 `SPEC_FIELDS` 與 `EVIDENCE_FIELDS` 落在小寫那一側，
        # 不影響這個數字。查法是把那支暫時移開再掃一次：72/290 回來了。
        # 2026-09-17: 73/292 → 75/296。desktop_api.MISSING 與 KIND_LABEL
        # 帶進來的（功能盤點那一頁「還沒做的」那一區）。
        self.assertEqual((up.enums, up.members), (75, 296))
        self.assertEqual(up.unexempted, [])

    def test_stale_total與stall_total是兩個活的東西(self):
        """屬性白名單的回歸證據。**這一條會隨那兩個鍵改名而腐爛。**

        腐爛的時候該做的是去查它們還在不在，不是把這條刪掉 ——
        它記的是「屬性白名單不是預防性假設」這件事的出處。
        """
        api = (REPO / "apps" / "forseti-cli" / "desktop_api.py").read_text(
            encoding="utf-8")
        self.assertIn('"stale_total"', api)
        self.assertIn('"stall_total"', api)
        self.assertEqual(LR.distance("stale_total", "stall_total", cap=2), 1)
        # 讀它的是屬性存取，不是字串 —— 所以條件 2 看不到它。
        js = (REPO / "desktop" / "ui" / "app.js").read_text(encoding="utf-8")
        self.assertIn("stale_total", js)
        self.assertNotIn('"stale_total"', js)
        self.assertIn("stale_total", LR.attr_names())

    def test_把真檔的小寫鍵名打錯會紅(self):
        """反向驗證做成常設測試。在記憶體裡改，不動磁碟。"""
        src = (REPO / "apps" / "forseti-cli" / "pollution.py").read_text(
            encoding="utf-8")
        typo = "regression_" + "prope"
        bad = src.replace('r.get("regression_probe"))]',
                          f'r.get("{typo}"))]')
        self.assertNotEqual(bad, src, "pollution.py 那一行變了，這條要改")
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            d = root / "src"
            d.mkdir()
            (d / "pollution.py").write_text(bad, encoding="utf-8")
            rep = LR.scan(def_dir=d, repo=root, count_dirs=("src",),
                          js_dirs=(), attr_dirs=(), prof=LR.LOWER)
        self.assertEqual([s.literal for s in rep.unexempted], [typo])
        self.assertEqual(rep.unexempted[0].member, "regression_probe")

    def test_ATTR_DIRS裡的目錄必須真的存在(self):
        """路徑是硬寫的，改名之後白名單會安靜縮小。

        **縮小的方向是往紅的**（少白名單等於多誤報），
        跟 `_SELF_FILES` 失效的方向相反，但一樣是安靜的。
        """
        for d in LR.ATTR_DIRS:
            self.assertTrue((REPO / d).is_dir(), f"{d} 不在了")

    def test_屬性白名單不數這一組自己(self):
        """跟 `_SELF_FILES` 同一條理由，只是換成白名單這一層。

        這個檔裡寫了 `tool_usa`、`regression_prope` 這些刻意的錯字，
        它們前面沒有點所以不會被屬性正則收 —— 但檔案本身仍然
        必須排除，因為將來寫下的負例不一定是這個形狀。
        """
        names = LR.attr_names()
        self.assertNotIn("tool_usa", names)
        only_self = LR.attr_names(attr_dirs=("tests",))
        self.assertIsInstance(only_self, set)


class 白名單的代價(unittest.TestCase):
    """`audit_shadow()`：每個成員各打錯一次，有幾次不會紅。

    ## 這一組守的是一句沒有數字撐著的話

    `attr_names()` 的說明寫著「214 個小寫成員裡有 84 個也在白名單裡，
    一個打錯的字只要撞上某個屬性名就不會紅」。那句話混了兩件事：
    成員自己在不在白名單裡，跟成員**打錯之後**的那個字串在不在，
    是不同的兩個集合。判紅只看後者。

    ## 這一支不判紅，所以它需要自己的測試

    一個只印數字的東西壞掉是沒有聲音的。這一組釘的是三件事：
    分母是什麼、歸因照什麼順序、把白名單關掉數字要跟著動。
    """

    def _audit(self, defs: dict[str, str], extra: dict[str, str] | None = None,
               js: dict[str, str] | None = None,
               attr: dict[str, str] | None = None,
               prof=None, kinds=None):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        d = root / "src"
        d.mkdir()
        for name, body in defs.items():
            (d / name).write_text(body, encoding="utf-8")
        for sub, files in (("other", extra), ("web", js), ("attr", attr)):
            if not files:
                continue
            o = root / sub
            o.mkdir()
            for name, body in files.items():
                (o / name).write_text(body, encoding="utf-8")
        return LR.audit_shadow(def_dir=d, repo=root,
                               count_dirs=("src", "other"), js_dirs=("web",),
                               attr_dirs=("attr",), prof=prof or LR.LOWER,
                               kinds=kinds)

    # ── 分母 ─────────────────────────────────────────────

    def test_變異全部是距離1(self):
        """三種打錯方式都保證距離剛好 1，這是這個量測的前提。

        距離不是 1 的話，量到的就混進了距離上界，
        而這一支要問的只有白名單。
        """
        for kind, v in LR.mutate_kinds("session_id", LR.LOWER,
                                       LR.MUTATION_KINDS):
            self.assertEqual(LR.distance("session_id", v, cap=3), 1,
                             f"{kind} {v}")

    def test_預設只有替換(self):
        """**預設不准跟著變寬。**

        5y 那一輪量到的 11 是在只有替換的條件下量的。預設改成三種，
        那個數字會無聲地變成另一個數字，紀錄裡的 11 就指不回
        任何可重跑的東西。要更緊的下界得自己指定。
        """
        self.assertEqual(LR.DEFAULT_MUTATION_KINDS, ("sub",))
        by_kind = {k for k, _ in LR.mutate_kinds("session_id", LR.LOWER)}
        self.assertEqual(by_kind, {"sub"})
        a = self._audit({"a.py": 'KEYS = ("alpha", "bravo")\n'})
        self.assertEqual(a.kinds, ("sub",))

    def test_少打的變異短一個字元(self):
        got = [v for k, v in LR.mutate_kinds("alpha", LR.LOWER, ("del",))]
        self.assertTrue(got)
        for v in got:
            self.assertEqual(len(v), len("alpha") - 1, v)

    def test_多打的變異長一個字元(self):
        got = [v for k, v in LR.mutate_kinds("alpha", LR.LOWER, ("ins",))]
        self.assertTrue(got)
        for v in got:
            self.assertEqual(len(v), len("alpha") + 1, v)

    def test_三種變異彼此不會重複(self):
        """長度分別是 n、n-1、n+1，三個集合不相交。

        這一條釘住的是「去重只在種類之內」那個決定的前提。
        前提哪天不成立，跨種類的重複就會灌水分母。
        """
        got = LR.mutate_kinds("session_id", LR.LOWER, LR.MUTATION_KINDS)
        self.assertEqual(len(got), len({v for _, v in got}))

    def test_少打產生的重複只算一次(self):
        """`abbc` 拿掉第二或第三個字元都得到 `abc`。

        同一個字串算兩次會把分母灌水，而分母是這個量測的一半。
        """
        got = [v for _, v in LR.mutate_kinds("abbc", LR.LOWER, ("del",))]
        self.assertEqual(got.count("abc"), 1)
        self.assertEqual(len(got), len(set(got)))

    def test_多打產生的重複只算一次(self):
        """`abb` 在三個位置插 `b` 都得到 `abbb`。"""
        got = [v for _, v in LR.mutate_kinds("abb", LR.LOWER, ("ins",))]
        self.assertEqual(got.count("abbb"), 1)
        self.assertEqual(len(got), len(set(got)))

    def test_刪到太短的不計入分母(self):
        """`abc` 少一個字元只剩兩個，形狀那一關就過不了。

        跟「第一個字元換成數字」同一條理由：那種字串在 `scan()` 裡
        根本走不到白名單那一關。
        """
        self.assertEqual(LR.mutate("abc", LR.LOWER, ("del",)), [])
        self.assertTrue(LR.mutate("abcd", LR.LOWER, ("del",)))

    def test_少打一個底線算數(self):
        """**刪除不排除底線，替換與插入排除。**

        排除底線是為了不要量到形狀（`a__b`、`_abc` 都不合樣式）。
        少打一個底線得到的 `alphabeta` 形狀完全合法，
        而且那是真的會發生的打錯方式，所以它算。
        """
        got = LR.mutate("alpha_beta", LR.LOWER, ("del",))
        self.assertIn("alphabeta", got)

    def test_不認得的種類會炸不會安靜跳過(self):
        """打錯種類名字安靜地變成量了別的東西，那比炸掉糟。"""
        with self.assertRaises(ValueError):
            LR.mutate("alpha", LR.LOWER, ("swap",))

    def test_逐種的分母加起來等於總數(self):
        a = self._audit({"a.py": 'KEYS = ("alpha", "bravo")\n'},
                        kinds=LR.MUTATION_KINDS)
        self.assertEqual(sum(t.mutations for t in a.per_kind), a.mutations)
        self.assertEqual([t.kind for t in a.per_kind],
                         list(LR.MUTATION_KINDS))

    def test_逐種也守恆(self):
        """總量守恆過不代表逐種的歸因對。"""
        a = self._audit({"a.py": 'KEYS = ("alpha", "bravo")\n'},
                        kinds=LR.MUTATION_KINDS)
        for t in a.per_kind:
            self.assertEqual(t.caught + t.blocked, t.mutations, t.kind)
            self.assertGreater(t.mutations, 0, t.kind)

    def test_加了少打多打下界只會變緊(self):
        """**這一條是這一輪的核心。**

        只量替換得到的是下界。多量兩種之後那個下界只能往上，
        因為分母是疊加的，原本那些變異一個都沒有少。
        往下走代表歸因壞了。
        """
        defs = {"a.py": 'KEYS = ("alpha", "bravo")\n'}
        attr = {"u.js": "const x = obj.alpba;\nconst y = obj.alphas;\n"}
        narrow = self._audit(defs, attr=attr)
        wide = self._audit(defs, attr=attr, kinds=LR.MUTATION_KINDS)
        self.assertGreater(wide.mutations, narrow.mutations)
        self.assertGreaterEqual(len(wide.attr_only), len(narrow.attr_only))
        self.assertIn(("alpha", "alphas"),
                      [(s.member, s.typo) for s in wide.attr_only])
        self.assertNotIn(("alpha", "alphas"),
                         [(s.member, s.typo) for s in narrow.attr_only])

    def test_每一筆代價都記得住自己是哪一種打錯(self):
        """不記種類的話，「是被哪一種收緊的」就答不出來。"""
        a = self._audit(
            {"a.py": 'KEYS = ("alpha", "bravo")\n'},
            attr={"u.js": "const x = obj.alphas;\n"},
            kinds=LR.MUTATION_KINDS,
        )
        hit = [s for s in a.attr_only if s.typo == "alphas"]
        self.assertEqual([s.kind for s in hit], ["ins"])
        self.assertEqual(hit[0].kind_zh, "多打一個字元")

    def test_形狀不合的變異不計入分母(self):
        """第一個字元換成數字之後不是識別字，那種不算。

        算進去只會把比例稀釋掉，而且它在 `scan()` 裡
        根本走不到白名單那一關。
        """
        muts = LR.mutate("abc", LR.LOWER)
        self.assertNotIn("1bc", muts)
        self.assertIn("abd", muts)

    def test_不替換成底線(self):
        """底線會改變形狀，於是量到的是形狀不是白名單。"""
        self.assertFalse(any("_" in v for v in LR.mutate("abc", LR.LOWER)))

    def test_不插入底線(self):
        """**這一條是反向驗證補回來的，不是一開始就想到的。**

        2026-09-17 的第八次反向驗證：把底線加進插入用的字母表，
        88 條測試**全綠**。上面那一條只看替換（預設種類就是替換），
        所以插入那一側的同一個決定完全沒有人守 —— 而它是有後果的，
        `alpha` 插一個底線得到的 `a_lpha` 形狀完全合法，
        會進到分母裡，於是量到的就混進了形狀不再只有白名單。

        少打一個底線是另一回事，見 `test_少打一個底線算數`：
        拿掉既有的底線得到的字串形狀仍然合法，那是真的打錯方式。
        **兩邊不對稱是故意的，所以兩邊都要有人釘。**
        """
        got = LR.mutate("abc", LR.LOWER, ("ins",))
        self.assertTrue(got)
        self.assertFalse([v for v in got if "_" in v])

    def test_守恆_會紅的加不會紅的等於變異總數(self):
        """數字自己對不上就是壞了，這一條是總量守門。"""
        a = self._audit({"a.py": 'KEYS = ("alpha", "bravo")\n'})
        self.assertEqual(a.caught + len(a.blocked), a.mutations)
        self.assertGreater(a.mutations, 0)

    # ── 屬性白名單的代價 ────────────────────────────────

    def test_打錯的字撞上屬性名就不會紅(self):
        """這一條是整組的核心：白名單擋住的是打錯的那個字串。"""
        a = self._audit(
            {"a.py": 'KEYS = ("alpha", "bravo")\n'},
            attr={"u.js": "const x = obj.alpba;\n"},
        )
        got = [(s.member, s.typo) for s in a.attr_only]
        self.assertIn(("alpha", "alpba"), got)
        self.assertEqual([s.blocker for s in a.attr_only], ["attr"])

    def test_成員自己在白名單裡不算代價(self):
        """混掉的就是這一件事。

        `obj.alpha` 讓 `alpha` 進白名單，但判紅看的是打錯的字串，
        所以這不構成任何漏報。
        """
        a = self._audit(
            {"a.py": 'KEYS = ("alpha", "bravo")\n'},
            attr={"u.js": "const x = obj.alpha;\n"},
        )
        self.assertEqual(a.attr_only, ())
        self.assertEqual(a.members_in_attrs, 1)

    def test_關掉屬性白名單代價就歸零(self):
        """反向驗證。數字不跟著動，代表它不是在量這件事。"""
        defs = {"a.py": 'KEYS = ("alpha", "bravo")\n'}
        attr = {"u.js": "const x = obj.alpba;\n"}
        on = self._audit(defs, attr=attr)
        off = self._audit(defs, attr=attr,
                          prof=LR.Profile("lower", "小寫鍵名", LR.LOWER_RE,
                                          LR.MIN_LEN, LR.LOWER_MAX_DISTANCE,
                                          use_attr=False))
        self.assertEqual(len(on.attr_only), 1)
        self.assertEqual(off.attr_only, ())
        self.assertEqual(off.members_in_attrs, 0)
        self.assertGreater(off.caught, on.caught)

    # ── 歸因順序 ─────────────────────────────────────────

    def test_repo裡也有的時候歸給repo不歸給屬性(self):
        """`scan()` 是短路的，歸因不照同一個順序數字就對不上。

        而且這一條同時擋住一種假的代價：一個變異本來就被
        條件 2 擋掉了，把它算進屬性白名單的帳上會高估代價。
        """
        a = self._audit(
            {"a.py": 'KEYS = ("alpha", "bravo")\n'},
            extra={"b.py": 'X = "alpba"\nY = "alpba"\n'},
            attr={"u.js": "const x = obj.alpba;\n"},
        )
        hit = [s for s in a.blocked if s.typo == "alpba"]
        self.assertEqual([s.blocker for s in hit], ["repo"])
        self.assertEqual(a.attr_only, ())

    def test_撞上另一個合法成員歸給member(self):
        """那是「用了合法但錯的成員」，檔頭列的既有盲點之一，

        不是白名單造成的。混進白名單的帳上會高估代價。
        """
        a = self._audit({"a.py": 'KEYS = ("alpha", "alpba")\n'})
        hit = [s for s in a.blocked if s.typo == "alpba"]
        self.assertEqual([s.blocker for s in hit], ["member"])
        self.assertEqual(a.attr_only, ())

    def test_JS側也有的時候歸給js(self):
        a = self._audit(
            {"a.py": 'KEYS = ("alpha", "bravo")\n'},
            js={"u.js": 'const k = "alpba";\n'},
        )
        hit = [s for s in a.blocked if s.typo == "alpba"]
        self.assertEqual([s.blocker for s in hit], ["js"])
        self.assertEqual(a.attr_only, ())

    def test_ALL_CAPS側的屬性代價是0(self):
        """**這一條綠的原因不是 `use_attr`，反向驗證推翻過一次。**

        2026-09-17 把 `audit_shadow()` 裡 `if prof.use_attr else set()`
        拿掉（也就是 ALL_CAPS 側也去查屬性白名單），這一條**照樣綠**。
        真正的原因是 `_ATTR_RE` 只收小寫名字，所以大寫的變異
        永遠不可能落在那個集合裡，兩個字元集不相交。

        `use_attr` 在 ALL_CAPS 側省的是三秒鐘，不是一個結果。
        真正守住 `use_attr` 被遵守的是
        `test_關掉屬性白名單代價就歸零`（小寫側 on/off 對照）。
        """
        a = self._audit({"a.py": 'KEYS = ("ALPHA", "BRAVO")\n'},
                        attr={"u.js": "const x = obj.alpba;\n"},
                        prof=LR.UPPER)
        self.assertEqual(a.attr_only, ())
        self.assertEqual(a.members_in_attrs, 0)
        self.assertGreater(a.mutations, 0)

    def test_屬性白名單只收小寫名字(self):
        """上面那一條真正的理由，釘在這裡而不是只寫在註解裡。

        `_ATTR_RE` 哪天放寬到收大寫，這一條會紅 —— 那時
        ALL_CAPS 側的免疫就不再成立，`use_attr` 從省時間
        變成影響結果，上面那條的說明要跟著重寫。
        """
        self.assertIsNone(LR._ATTR_RE.search(".ALPHA_ONE"))
        self.assertIsNotNone(LR._ATTR_RE.search(".alpha_one"))
        names = LR.attr_names(prof=LR.UPPER)
        self.assertEqual([x for x in names if any(c.isupper() for c in x)], [])

    # ── 這一支不判紅 ─────────────────────────────────────

    def test_量測不影響回傳碼(self):
        """`--shadow` 印的是數字，紅不紅由 `scan()` 決定。

        量測開始判紅的那一天，守門就會因為一個既有的、
        已知的代價而永遠是紅的，然後被關掉。
        """
        self.assertEqual(LR.main(["--shadow", "--profile", "upper"]), 0)

    def test_指定種類也不影響回傳碼(self):
        self.assertEqual(LR.main(["--shadow", "--shadow-kinds", "del",
                                  "--profile", "upper"]), 0)

    def test_種類打錯了指令會停不會安靜量別的(self):
        """`--shadow-kinds sbu` 安靜地量成空集合，數字會變成 0，

        而 0 看起來像「沒有代價」。那是往綠的方向壞。
        """
        with self.assertRaises(SystemExit) as cm:
            LR.main(["--shadow", "--shadow-kinds", "sbu", "--profile", "upper"])
        self.assertEqual(cm.exception.code, 2)


class 這個repo的白名單代價(unittest.TestCase):
    """真 repo。會隨開發變動，那正是它存在的目的。"""

    @classmethod
    def setUpClass(cls):
        cls.up = LR.audit_shadow(prof=LR.UPPER)
        cls.lo = LR.audit_shadow(prof=LR.LOWER)
        cls.up_w = LR.audit_shadow(prof=LR.UPPER, kinds=LR.MUTATION_KINDS)
        cls.lo_w = LR.audit_shadow(prof=LR.LOWER, kinds=LR.MUTATION_KINDS)

    def test_真的量到東西了(self):
        """全部回 0 會讓底下每一條都綠，所以要有下界。"""
        self.assertGreater(self.lo.mutations, 10000)
        self.assertGreater(self.up.mutations, 10000)
        self.assertGreater(self.lo.pairs, 100)

    def test_真repo上ALL_CAPS側的屬性代價也是0(self):
        """兩層理由，而只有第二層守得住（合成那一組的說明有細節）。

        第一層是 `UPPER.use_attr` 為 False，第二層是
        `_ATTR_RE` 只收小寫。**第一層拿掉這一條照樣綠**，
        所以它守的其實是第二層。
        """
        self.assertEqual(self.up.attr_only, ())
        self.assertEqual(self.up.members_in_attrs, 0)

    def test_每一條代價都指得回一個查得到的位置(self):
        """報出來的東西要能自己去查，不然它只是一個數字。"""
        attrs = LR.attr_names()
        for s in self.lo.attr_only:
            self.assertIn(s.typo, attrs, f"{s.typo} 不在屬性白名單裡")
            self.assertEqual(LR.distance(s.member, s.typo, cap=3), 1)
            self.assertTrue((LR.DEF_DIR / f"{s.module}.py").is_file())

    def test_三種一起量下界確實收緊了(self):
        """**只量替換得到的是下界，這一條釘住它真的是下界。**

        2026-09-17 的量：只有替換是 11 個變異落在 10 個成員上，
        三種一起是 23 個落在 21 個成員上。數字會隨開發變動，
        所以這裡釘的是關係不是數字 —— 分母只能疊加，
        所以往下走代表歸因壞了。
        """
        self.assertGreater(self.lo_w.mutations, self.lo.mutations)
        self.assertGreater(len(self.lo_w.attr_only), len(self.lo.attr_only))
        self.assertGreater(self.lo_w.attr_only_members,
                           self.lo.attr_only_members)

    def test_少打與多打各自都真的貢獻了漏報(self):
        """兩種都是 0 的話，這一輪等於沒有收緊任何東西，

        而那件事會被上面那一條總量的測試蓋過去。
        """
        by = {t.kind: t for t in self.lo_w.per_kind}
        self.assertGreater(by["del"].attr_only, 0)
        self.assertGreater(by["ins"].attr_only, 0)

    def test_少打與多打抓到的主要是字尾差一個字元(self):
        """**這是這一輪量出來最有內容的一件事，所以它要有人守。**

        少打多打抓到的漏報，過半是同一個形狀：長的那個以短的那個
        開頭，也就是差在字尾一個字元（`created` 打成 `create`、
        `outputs` 打成 `output`、`name` 打成 `names`）。
        2026-09-17 是 12 個裡的 9 個。

        **這一條釘的是字尾形狀，不是「單複數」。** 那九個裡有七個
        是真的詞形變化，另外兩個（`insider` 打成 `inside`、
        `ran` 打成 `rank`）只是剛好也差在字尾。「是不是詞形變化」
        沒有辦法用程式判準地判，所以測試不宣稱那一件事 ——
        工具的說明裡兩個數字是分開寫的。

        為什麼這個形狀重要：詞形變化的兩個形式通常都有人以
        `obj.key` 用過，所以屬性白名單整類吃掉。只量替換
        完全看不到它。哪天這個比例掉下來，代表白名單或成員集合
        變了，那一段說明要跟著重寫。
        """
        pairs = [(s.member, s.typo) for s in self.lo_w.attr_only
                 if s.kind in ("del", "ins")]
        self.assertTrue(pairs)
        infl = [(m, t) for m, t in pairs
                if max(m, t, key=len).startswith(min(m, t, key=len))]
        self.assertGreaterEqual(len(infl), len(pairs) // 2,
                                f"字尾形狀 {len(infl)} / {len(pairs)}")
        # 判準自己不可以是恆真的。`send` 少打一個字元變 `end`
        # 也在這份漏報裡，而它不是字尾形狀 —— 這一句釘住
        # 上面那個 startswith 真的分得開兩類，不是全部都算進去。
        self.assertFalse(max("send", "end", key=len)
                         .startswith(min("send", "end", key=len)))

    def test_每一條代價都指得回一個查得到的位置_三種版本(self):
        """跟只有替換那一條同一件事，換成三種一起量。

        少打多打那些新出現的，一樣要查得到。
        """
        attrs = LR.attr_names()
        for s in self.lo_w.attr_only:
            self.assertIn(s.typo, attrs, f"{s.typo} 不在屬性白名單裡")
            self.assertEqual(LR.distance(s.member, s.typo, cap=3), 1)
            self.assertTrue((LR.DEF_DIR / f"{s.module}.py").is_file())
            self.assertIn(s.kind, LR.MUTATION_KINDS)

    def test_真repo上三種一起量ALL_CAPS側屬性代價仍然是0(self):
        """免疫的理由是字元集不相交，跟量幾種打錯方式無關。

        多打一個字元同樣只從大寫字母表取，所以變異永遠不會
        落在只收小寫的屬性白名單裡。少打更不可能改變大小寫。
        """
        self.assertEqual(self.up_w.attr_only, ())
        self.assertEqual(self.up_w.members_in_attrs, 0)
        self.assertGreater(self.up_w.mutations, self.up.mutations)

    def test_代價遠小於在白名單裡的成員數(self):
        """這一條釘住的是那句話的更正。

        84 個成員在白名單裡，而真正不會紅的只有個位數的成員。
        兩個數字如果變成同一個量級，代表歸因又混回去了。
        """
        self.assertGreater(self.lo.members_in_attrs, 50)
        self.assertLess(self.lo.attr_only_members,
                        self.lo.members_in_attrs // 4)


class 駝峰這一種(unittest.TestCase):
    """第三種風格。**這一組驗的是「不守它」這個決定還站不站得住。**

    「駝峰還沒有人守」這句話在 2026-09-17 的紀錄裡連續被推到下一輪
    三次，理由都是「判準要重想一次」，而它從來沒有被量過。量了之後
    知道 Python 定義側 0 個駝峰列舉 —— 所以那不是欠判準，
    是沒有東西可守。

    **這一組不驗「駝峰抓得到拼錯」**，因為駝峰沒有進 `PROFILES`，
    掃描器根本不走那條路。它驗的是那個決定的前提，
    以及前提不再成立的時候有人會知道。
    """

    @classmethod
    def setUpClass(cls):
        cls.c = LR.camel_census()

    def test_形狀只收駝峰(self):
        """三種形狀彼此不重疊，不然量出來的數字會互相灌水。"""
        for s in ("toolUse", "sessionId", "aB1c"):
            self.assertTrue(LR.CAMEL_RE.match(s), s)
        for s in ("tool_use", "TOOL_USE", "ToolUse", "tooluse", "toolU"):
            self.assertFalse(LR.CAMEL_RE.match(s), s)

    def test_駝峰不在PROFILES裡(self):
        """**刻意的，不是漏掉的。**

        加進去會是一個永遠 0 命中的風格：畫面上多一節看起來有人在守
        的東西，實際一個字都守不到。這一條釘住那個選擇，
        所以有人哪天加進去的時候，會先看到這條測試問他為什麼。
        """
        self.assertNotIn("camel", [p.key for p in LR.PROFILES])

    def test_駝峰在Python定義側必須仍然是空的(self):
        """**這是這一組唯一會隨開發變紅的一條，而它紅得對。**

        「不加第三個 Profile」這個決定的前提只有一條：掃描器的定義側
        （`apps/forseti-cli/*.py`）沒有駝峰列舉。前提一破，
        該做的是把 `CAMEL` 加進 `PROFILES`，**不是把這一條調鬆**。

        紅的時候看 `camel_census()` 的說明，那裡寫著該做什麼。
        """
        self.assertEqual(self.c.py_enums, 0,
                         "Python 定義側出現駝峰列舉了："
                         f"{sorted(self.c.py_members)} —— "
                         "「不守駝峰」的前提不再成立，"
                         "該把 CAMEL 加進 PROFILES")
        self.assertEqual(self.c.py_members, frozenset())
        self.assertTrue(self.c.py_vacuous)

    def test_前提破掉的時候真的會被抓到(self):
        """反向驗證：合成一個有駝峰列舉的定義側，`py_vacuous` 必須翻。

        上一條對真 repo 斷言，真 repo 現在是 0，所以它此刻恆綠 ——
        **一條恆綠的測試沒辦法自己證明它抓得到東西**。這一條補的就是
        那個方向，跟 5i 那次「假守備」同一個教訓。
        """
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "fake.py").write_text(
                'KINDS = ("toolUse", "sessionId")\n', encoding="utf-8")
            c2 = LR.camel_census(def_dir=p)
        self.assertEqual(c2.py_enums, 1)
        self.assertEqual(c2.py_members, frozenset({"toolUse", "sessionId"}))
        self.assertFalse(c2.py_vacuous)

    def test_JS側刻意不設紅線(self):
        """JS 的駝峰長多少都不該讓這一組變紅。

        JS 此刻不是定義來源，所以它的數字改變的是另一件事
        （要不要把 JS 也變成定義側），那一條有自己的位置。
        **兩件事合成一條紅線，會讓 JS 的任何改動觸發一條
        它解釋不了的紅燈。**

        這裡只斷言「量得到而且是合理範圍」，不釘死數字。
        """
        self.assertGreaterEqual(self.c.js_blocks, 0)
        self.assertEqual(len(self.c.js_members),
                         len(set(self.c.js_members)))
        for m in self.c.js_members:
            self.assertTrue(LR.CAMEL_RE.match(m), m)

    def test_JS側那兩個是函式名字不是列舉值(self):
        """**這一條釘住的是「JS 側也是 0」那個更正。**

        區塊抓取只看形狀，所以 `src/provenance.js` 的 `fn:` 欄位
        被算成兩個成員。去查才知道它們是 `rhetoric.js` 兩個函式的
        名字，不是某個欄位的合法值清單。**光看數字 2 會以為
        JS 側有駝峰列舉材料，實際沒有。**

        這一條會隨 repo 變動：那兩個函式改名或那張登記簿改寫，
        它就該紅，而紅的時候要重新去查一次 JS 側到底有沒有
        真的駝峰列舉，不是把斷言刪掉。
        """
        rh = (REPO / "src" / "rhetoric.js").read_text(encoding="utf-8")
        for name in self.c.js_members:
            self.assertIn(f"export function {name}(", rh,
                          f"{name} 不再是 rhetoric.js 的函式，"
                          "JS 側的駝峰材料要重新查一次")

    def test_區塊抓取回傳的是下界而且換形狀量得到另外兩種(self):
        """同一支換上另外兩種形狀，數字必須遠大於駝峰。

        那正是「下一步該做 JS 定義側不是駝峰」的依據。
        用大小關係不用精確數字，因為這一支是下界，
        而下界會隨 JS 開發漂。
        """
        cb, cm = LR.js_enum_blocks(prof_re=LR.CAMEL_RE)
        ub, um = LR.js_enum_blocks(prof_re=LR.IDENT_RE)
        lb, lm = LR.js_enum_blocks(prof_re=LR.LOWER_RE)
        self.assertGreater(ub, cb * 10)
        self.assertGreater(len(um), len(cm) * 10)
        self.assertGreater(lb, cb)
        self.assertGreater(len(lm), len(cm) * 10)

    def test_區塊抓取跳過自己這一組(self):
        """跟 `_SELF_FILES` 同一條理由。

        這個測試檔與工具檔都不是 JS，所以此刻不可能被掃到 ——
        釘住的是那個排除真的接在路徑上，不是靠副檔名剛好擋住。
        """
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "sub").mkdir()
            (p / "sub" / "x.js").write_text(
                "export const K = { a: 'fooBar', b: 'bazQux' };\n",
                encoding="utf-8")
            b, mem = LR.js_enum_blocks(js_dirs=("sub",), repo=p)
        self.assertEqual(b, 1)
        self.assertEqual(mem, {"fooBar", "bazQux"})

    def test_少於兩個成員的區塊不算列舉(self):
        """跟 Python 側 `MIN_ENUM_MEMBERS` 同一條：
        單值常數不構成對照組。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "sub").mkdir()
            (p / "sub" / "x.js").write_text(
                "export const K = { a: 'fooBar' };\n", encoding="utf-8")
            b, mem = LR.js_enum_blocks(js_dirs=("sub",), repo=p)
        self.assertEqual(b, 0)
        self.assertEqual(mem, set())


class 私有常數這個盲點(unittest.TestCase):
    """底線開頭的模組級常數不是定義側的一員，三種風格都一樣。

    **這一組是駝峰那一組的反向驗證撞出來的。** 為了確認守門真的會紅，
    第一次植入的是 `_CAMEL_PROBE`，**結果測試沒有紅** ——
    `_const_targets()` 把底線開頭的名字整批排除。換成不帶底線的
    名字才紅。那一次失敗本身就是這一組存在的理由。
    """

    def test_底線開頭的常數不算定義側(self):
        """釘住那個排除條件本身。

        它不是 bug 也不是要修的東西，是一個選擇；
        這一條只讓那個選擇有人看著。
        """
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "f.py").write_text(
                '_HIDDEN = ("ALPHA_ONE", "ALPHA_TWO")\n'
                'SHOWN = ("BETA_ONE", "BETA_TWO")\n', encoding="utf-8")
            tree = LR._parse(p / "f.py")
            enums, _ = LR.enums_of(p / "f.py", tree, LR.UPPER)
        self.assertEqual([e.name for e in enums], ["SHOWN"])

    def test_私有常數的曝險此刻是0(self):
        """**機制是真的，曝險是 0，兩件事都要講。**

        真 repo 有 3 個私有列舉常數共 10 個成員，而 10 個全部同時
        也是同檔某個公開列舉的成員，所以對照組還在、打錯照樣會紅。

        這一條是會隨開發變紅的那一條：一旦有成員**只**活在私有常數裡，
        它就沒有對照組了。紅的時候看 `private_exposure()` 的說明，
        那裡寫著為什麼此刻不順手把私有常數納入定義側。
        """
        for prof in (LR.UPPER, LR.LOWER):
            n, total, only = LR.private_exposure(prof=prof)
            self.assertEqual(only, set(),
                             f"{prof.key}：這些成員只活在私有常數裡，"
                             f"沒有對照組了 -> {sorted(only)}")
            self.assertGreaterEqual(total, n)

    def test_不要把常數個數讀成無人守的成員數(self):
        """`attr_names()` 那個「84 個成員」更正的同一個形狀。

        3 個常數沒被當成定義側，不等於 10 個成員沒人守。
        這一條釘住兩個數字不准被合成一個。
        """
        n, total, only = LR.private_exposure(prof=LR.UPPER)
        self.assertGreater(total, n)
        self.assertEqual(len(only), 0)
        self.assertNotEqual(total, len(only))

    def test_曝險真的算得出來(self):
        """合成一個只活在私有常數裡的成員，曝險必須不是 0。

        上一條對真 repo 斷言而真 repo 是 0，所以它此刻恆綠。
        這一條補那個方向。
        """
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "f.py").write_text(
                '_ONLY = ("GAMMA_ONE", "GAMMA_TWO")\n', encoding="utf-8")
            n, total, only = LR.private_exposure(def_dir=p, prof=LR.UPPER)
        self.assertEqual(n, 1)
        self.assertEqual(total, 2)
        self.assertEqual(only, {"GAMMA_ONE", "GAMMA_TWO"})

    def test_同檔公開列舉涵蓋到就不算曝險(self):
        """`_MARK` 對 `STATES` 那個形狀，用合成目錄釘住。"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "f.py").write_text(
                'STATES = ("DELTA_ONE", "DELTA_TWO")\n'
                '_LABEL = {"DELTA_ONE": "a", "DELTA_TWO": "b"}\n',
                encoding="utf-8")
            n, total, only = LR.private_exposure(def_dir=p, prof=LR.UPPER)
        self.assertEqual(n, 1)
        self.assertEqual(total, 2)
        self.assertEqual(only, set())


if __name__ == "__main__":
    unittest.main()
