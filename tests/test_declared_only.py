#!/usr/bin/env python3
"""模組級常數裡誰從來沒有人讀，這件事有沒有人守。

`test_js_symbols.py` 守 JS 的「叫了但沒定義」，`test_ui_contract.py`
守 JS 的「定義了但沒人叫」。Python 這一側，直到 2026-09-17 為止
一條都沒有 —— 而 §40 污染登記簿第一筆講的正是 Python 的常數
（`event_ledger.py:122` 的 `LINEAGE_EDGES`）。

做法在 `tools/declared-only-check.py`，連同它五個盲點。

## 這一組分兩半，理由不一樣

**合成目錄那一半**（`class 掃描器`）在 `tmp` 造幾個小檔跑完整流程。
它驗的是掃描器本身的行為，跟這個 repo 現在長什麼樣子無關，
所以它不會隨開發腐爛。

**真 repo 那一半**（`class 這個repo現在的狀態`）驗登記簿沒有過期、
守門現在是綠的。它會隨開發變動 —— 那正是它存在的目的：
新長出一個沒人讀的常數就該紅。

## 一條不能省的：這一支自己會污染自己

`tools/` 在 `READ_DIRS` 底下，所以掃描器自己的模組級名字會被自己
掃到。第一版它有一個常數叫 `KINDS`，結果 `lanes.py:48` 真正沒人讀的
那個 `KINDS` 被判成「有弱引用」，安靜地從紅名單消失。
`test_這一支自己的名字不可以跟被掃的常數撞名` 守這個方向。
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TOOL = REPO / "tools" / "declared-only-check.py"


def _load():
    """檔名有連字號，`import` 進不來，所以用檔案路徑載。

    放進 `sys.modules` 的理由跟 `test_ui_render.py` 同一條：
    Python 3.9 解析 dataclass 的型別註記時要找得到自己的模組。
    """
    spec = importlib.util.spec_from_file_location("forseti_declared_only",
                                                  TOOL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forseti_declared_only"] = mod
    spec.loader.exec_module(mod)
    return mod


DO = _load()


def _mk(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        (root / name).write_text(body, encoding="utf-8")


class 掃描器(unittest.TestCase):
    """合成目錄。跟這個 repo 現在長什麼樣子無關。"""

    def _scan(self, defs: dict[str, str], extra: dict[str, str] | None = None):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        d = root / "src"
        d.mkdir()
        _mk(d, defs)
        roots = [d]
        if extra:
            e = root / "other"
            e.mkdir()
            _mk(e, extra)
            roots.append(e)
        self.addCleanup(self.tmp.cleanup)
        return DO.scan(def_dir=d, roots=tuple(roots))

    def test_沒有人讀的常數會被抓到(self):
        r = self._scan({"a.py": "USED = 1\nUNUSED = 2\n\ndef f():\n    return USED\n"})
        names = {c.name for c in r.unread}
        self.assertIn("UNUSED", names)
        self.assertNotIn("USED", names)

    def test_同名常數不會互相掩蓋(self):
        """精確歸屬的核心價值。

        這個 repo 有 24 組同名常數（`STATES` 在六個檔裡）。純比名字的話
        只要有一個檔的 `STATES` 被讀，六個都算被讀 —— 往綠的方向壞。
        """
        r = self._scan({
            "a.py": "STATES = ('x',)\n\ndef f():\n    return STATES\n",
            "b.py": "STATES = ('y',)\n",
        })
        unread = {(c.module, c.name) for c in r.unread}
        self.assertIn(("b", "STATES"), unread)
        self.assertNotIn(("a", "STATES"), unread)

    def test_跨檔的module點常數算被讀(self):
        r = self._scan(
            {"a.py": "WANTED = 1\n"},
            {"caller.py": "import a\n\ndef f():\n    return a.WANTED\n"})
        self.assertNotIn("WANTED", {c.name for c in r.unread})

    def test_from_import算被讀(self):
        r = self._scan(
            {"a.py": "WANTED = 1\n"},
            {"caller.py": "from a import WANTED\n"})
        self.assertNotIn("WANTED", {c.name for c in r.unread})

    def test_底線開頭的不算模組級常數(self):
        """`_CACHE_VERSION` 這種是私有實作細節，它沒有對外宣稱任何東西。"""
        r = self._scan({"a.py": "_PRIVATE = 1\n__DUNDER__ = 2\nPUBLIC = 3\n"})
        self.assertEqual({c.name for c in r.unread}, {"PUBLIC"})

    def test_函式裡面的大寫名字不算(self):
        r = self._scan({"a.py": "def f():\n    INSIDE = 1\n    return 2\n"})
        self.assertEqual(r.unread, [])
        self.assertEqual(r.total, 0)

    def test_AppleDouble檔不會讓掃描炸掉(self):
        """工作碟是 exFAT，macOS 會在旁邊放 `._x.py`，它不是 UTF-8。

        寫這一支的第一次執行就是這樣死的（`UnicodeDecodeError`，
        `ast.parse` 還沒開始）。所以排除規則要有人守，不是靠記得。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name) / "src"
        d.mkdir()
        _mk(d, {"a.py": "LONELY = 1\n"})
        (d / "._a.py").write_bytes(b"\x00\xb0\xff not utf-8 \xfe")
        r = DO.scan(def_dir=d, roots=(d,))
        self.assertEqual({c.name for c in r.unread}, {"LONELY"})

    def test_弱引用不判紅但要數得出來(self):
        """歸屬不到的同名引用，列出來但不紅。

        誤報會讓守門被關掉，那比漏報更糟 —— 代價寫在工具檔頭盲點第三條。
        """
        r = self._scan(
            {"a.py": "AMBIG = 1\n"},
            {"caller.py": "def f(x):\n    return x.AMBIG\n"})
        self.assertEqual(r.unread, [])
        self.assertEqual([c.name for c in r.weak_only], ["AMBIG"])

    def test_星號import會講一句不會安靜當作沒事(self):
        r = self._scan(
            {"a.py": "THING = 1\n"},
            {"caller.py": "from a import *\n"})
        self.assertEqual(r.star_imports, ["a"])


class 登記簿(unittest.TestCase):
    """清單不准變成垃圾桶，也不准腐爛。"""

    def test_每一條都有kind而且是三種之一(self):
        for key, v in DO.REGISTRY.items():
            self.assertIn(v["kind"], DO.REG_KINDS, key)

    #: 理由裡要有一個「可以拿去查的東西」。
    #:
    #: 用正則不用關鍵字表，因為關鍵字表要嘛太鬆（「行」會被「不行」中）
    #: 要嘛擋掉正當的寫法 —— 第一版就擋掉了 `pollution.REQUIRES` 那條
    #: 指到 `_missing_for()` 第 180 行的理由，而那是整張表裡最具體的
    #: 一條。判準改成「指得出位置」，不是「用了哪幾個詞」。
    CITES = (
        r"§\s*\d",                 # 規格節號
        r"\.(py|js|mjs|md|jsonl)",  # 檔名
        r"第\s*\d+\s*(與\s*\d+\s*)?行",  # 行號
        r":\d+",                    # path:line
        r"`[^`]+\(\)`",              # 函式
        r"[「『][^」』]{4,}[」』]",   # 引的原文
        r"\d+\s*次",                # 實測次數
    )

    def test_每一條的理由都指得回原文(self):
        """`why` 不准是「不用」「沒差」這種。

        一條沒有依據的理由跟沒有理由一樣，而它比沒有理由更糟：
        它讓清單看起來已經想過了。
        """
        import re
        for key, v in DO.REGISTRY.items():
            why = v["why"]
            self.assertGreaterEqual(len(why), 20, f"{key} 的理由太短")
            self.assertTrue(
                any(re.search(pat, why) for pat in self.CITES),
                f"{key} 的理由沒有指回任何查得到的位置：{why}")

    def test_這條判準真的擋得住空話(self):
        """反向驗證寫成測試，不是只在紀錄裡說「我試過了」。"""
        import re
        for junk in ("這個不用，沒差", "保留著以後可能會用到",
                     "歷史因素", "暫時放著" * 6):
            self.assertFalse(
                len(junk) >= 20 and any(re.search(p, junk) for p in self.CITES),
                f"這種理由應該要被擋下來：{junk}")

    def test_空殼那幾條要講得出缺什麼(self):
        for key, v in DO.REGISTRY.items():
            if v["kind"] != "DECLARED_ONLY":
                continue
            self.assertTrue(
                any(t in v["why"] for t in ("沒有實作", "沒有任何地方",
                                            "一條都沒有")),
                f"{key} 登記成空殼，但沒有寫出缺什麼")


class 這個repo現在的狀態(unittest.TestCase):
    """會隨開發變動。那正是它存在的目的。"""

    def setUp(self):
        self.r = DO.scan()

    def test_守門現在是綠的(self):
        """新長出一個沒人讀的常數，這一條就會紅。

        紅的時候要做的不是把它加進清單了事，是先判斷它是三種帳的哪一種
        —— 工具檔頭「REGISTRY 的 kind」那一節寫了三種各自的處置。
        """
        self.assertEqual(self.r.unregistered, [],
                         "有沒人讀的常數沒有登記，"
                         "跑 python3 tools/declared-only-check.py 看細節")

    def test_登記簿沒有過期的條目(self):
        """兩種腐爛：登記的常數不在了，或者它現在有人讀了。

        後者是好消息，但清單要跟著改，不然它會一直宣稱一件
        已經不成立的事。
        """
        self.assertEqual(self.r.stale_registry, [])

    def test_LINEAGE_EDGES不再是空殼而且不是靠讀一下變綠的(self):
        """2026-09-18 這一條紅過，那是好消息紅，處置照它原本寫的做了。

        原本這一條驗的是「它仍然登記在案、仍然沒人讀」。
        `lineage.py` 把它接成 `add()` 的邊型別白名單之後，
        登記拿掉了，這一條跟著改成守新的事實。

        **兩件事都要驗，只驗前面那件會被騙。** 一個常數只要被誰
        `import` 一下就會從 unread 消失，而那不代表它管得住任何東西
        —— B-15「不要做的事」那一段講的正是這種變綠法。
        所以這裡第二段直接去打 `lineage.add()`，驗那張表真的在擋人。
        """
        self.assertNotIn(("event_ledger", "LINEAGE_EDGES"), DO.REGISTRY,
                         "它不再是空殼，登記要拿掉")
        self.assertNotIn(("event_ledger", "LINEAGE_EDGES"),
                         {(c.module, c.name) for c in self.r.unread})

        import importlib.util as _ilu
        _spec = _ilu.spec_from_file_location(
            "forseti_lineage_probe",
            REPO / "apps" / "forseti-cli" / "lineage.py")
        _ln = _ilu.module_from_spec(_spec)
        sys.modules["forseti_lineage_probe"] = _ln
        _spec.loader.exec_module(_ln)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "lineage.jsonl"
            bad = _ln.add(type="NOT_A_SPEC_EDGE", from_id="a", to_id="b",
                          basis="植入", path=out)
            self.assertFalse(bad["ok"], "不在表裡的型別要被擋下來")
            self.assertFalse(out.exists(), "被擋下來的不可以落檔")

    def test_RAW_INLINE_LIMIT那個門檻仍然沒有人執行(self):
        """這一條不看登記簿，直接看原始碼。

        看登記簿的話，等於拿我自己寫的分類去證明我自己的分類。
        `worker.py` 裡 `SUMMARY_LIMIT` 與 `LIST_LIMIT` 都在 `check()`
        裡真的被比較過，`RAW_INLINE_LIMIT` 沒有 —— 這一條驗的是
        那個不對稱還在。它被接上去的那一天會紅，那是好消息紅。
        """
        src = (REPO / "apps" / "forseti-cli" / "worker.py").read_text(
            encoding="utf-8")
        hits = [ln for ln in src.splitlines()
                if "RAW_INLINE_LIMIT" in ln]
        self.assertEqual(len(hits), 1,
                         "RAW_INLINE_LIMIT 不再只有定義那一行了，"
                         "去更新 REGISTRY 與 docs/PROGRESS_2026-09-09.md:243")
        self.assertTrue(hits[0].startswith("RAW_INLINE_LIMIT ="))

    def test_掃描器把自己排除在檔案清單外(self):
        """兩個方向都驗，不然「排除」可能只是碰巧沒掃到。"""
        self.assertNotIn(TOOL.resolve(), DO.py_files(REPO / "tools"))
        self.assertIn(TOOL.resolve(),
                      DO.py_files(REPO / "tools", skip_self=False))

    def test_撞名真的還在而且已經不會造成漏報(self):
        """排除自己是為了治這個，所以要驗撞名本身仍然存在。

        掃描器有 `REPO`，`apps/forseti-cli` 十七個檔也有 `REPO`。
        撞名沒有消失 —— 消失的是它的後果。哪天有人把 `skip_self`
        拿掉，這一條不會紅（它驗的是撞名還在），
        紅的是上面那一條跟下面那一條。
        """
        mine = {c.name for c in DO.module_consts(TOOL)}
        theirs = set()
        for p in DO.py_files(DO.DEF_DIR, recurse=False):
            theirs |= {c.name for c in DO.module_consts(p)}
        self.assertTrue(mine & theirs, "撞名不見了，這一條的前提沒了")

    def test_lanes的KINDS仍然在紅名單裡(self):
        """第一版被掃描器自己的 `KINDS` 掩蓋掉的那一個。

        它是撞名造成漏報的唯一一次實例，所以拿它當回歸測試。
        哪天 `lanes.KINDS` 真的有人讀了，這一條會紅 —— 那時候要做的
        是把它從 `REGISTRY` 移掉，不是把這一條刪掉。
        """
        self.assertIn(("lanes", "KINDS"),
                      {(c.module, c.name) for c in self.r.unread})

    def test_主程式回傳碼跟著紅綠走(self):
        self.assertEqual(DO.main([]), 0)


if __name__ == "__main__":
    unittest.main()
