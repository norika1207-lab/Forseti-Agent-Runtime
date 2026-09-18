"""四支 CLI 的第一個參數：旗標不准被當成子指令。

這個檔存在的理由：2026-09-18 08:2x 在 `evidence.py` 撞到這個形狀，
修完當下就記下「`metrics.py:573` 有同一個寫法」。那一輪沒有改它，
理由寫的是「它的 `--path` 有哪些呼叫端還沒查」。

這一輪查了：`metrics.main` / `attempts.main` / `antianchor.main` /
`probemodel.main` 在 repo 裡**只有一個非測試呼叫端**，
就是 `forseti.py` 的 dispatch，而那裡是原樣轉發 `argv[2:]`。
所以那個「還沒查」的理由不成立了。

量出來的後果分成兩種，不是一種 ——
這件事比「四個檔都有同一個 bug」重要：

| 檔 | 有沒有未知子指令守門 | 旗標當第一參數的後果 |
|---|---|---|
| `metrics.py` | 沒有 | 靜默掉進 list，**讀正本而不是讀 `--path`**，exit=0 |
| `attempts.py` | 沒有 | 同上，而且正本此刻有資料，所以拿到的是別人的答案 |
| `antianchor.py` | 有 | 印 usage，exit=2 |
| `probemodel.py` | 有 | 印 usage，exit=2 |

前兩支是**錯的答案長得跟對的一樣**，後兩支是明著退回。
兩種都要修，但修的不是同一件事：前兩支修的是「答案是錯的」，
後兩支修的是「省略預設子指令用不了」。

所以這個檔分兩組守：`FlagFirst` 守四支都認得旗標，
`SilentFallthrough` 只守前兩支不准再靜默 —— 那一組如果哪天
被人「順手統一」成四支一樣，會少掉一半的意思。
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import antianchor as AA  # noqa: E402
import attempts as AT  # noqa: E402
import evidence as EV  # noqa: E402
import metrics as MT  # noqa: E402
import probemodel as PM  # noqa: E402


def _run(mod, argv: list) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        rc = mod.main(list(argv))
    return rc, buf.getvalue()


class _Box(unittest.TestCase):
    """一律傳 `--path` / `--root` 指到暫存目錄，**絕不碰正本**。

    這個檔守的正是「`--path` 有沒有真的被看見」，所以它自己少傳一次
    就會去讀正本 —— 那是這個檔最容易自食其果的地方。
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def jsonl(self, rows: list, name: str) -> Path:
        p = self.tmp / name
        p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                             for r in rows), encoding="utf-8")
        return p


class FlagFirst(_Box):
    """第一個參數是旗標的時候，四支都要把它當旗標。"""

    def test_metric_旗標當第一參數的時候讀的是指定路徑(self):
        """這一條是整個檔的起點。錯的時候讀的是正本，而正本此刻
        不存在所以回 0 筆 —— 「0 筆」跟「登記簿是空的」那句正常
        輸出長得一模一樣，不會報錯。所以斷言要盯著**筆數**，
        不是盯著有沒有例外。"""
        p = self.jsonl([{"metric_id": "m-FLAGTEST01", "name": "旗標測試"}],
                       "m.jsonl")
        rc, out = _run(MT, ["--path", str(p)])
        self.assertEqual(rc, 0)
        self.assertIn("1 筆", out)
        self.assertIn("m-FLAGTEST01", out)

    def test_attempt_旗標當第一參數的時候讀的是指定路徑(self):
        """這一支比 metric 更要緊：它的正本有資料，所以錯的時候
        拿到的不是「0 筆」而是一份完整的別人的答案。"""
        p = self.jsonl([], "a.jsonl")
        rc, out = _run(AT, ["--path", str(p)])
        self.assertEqual(rc, 0)
        self.assertIn("共 0 筆", out)
        self.assertNotIn("att-", out)

    def test_antianchor_旗標當第一參數的時候當成預設子指令(self):
        (self.tmp / ".forseti").mkdir(parents=True, exist_ok=True)
        rc, out = _run(AA, ["--root", str(self.tmp)])
        self.assertEqual(rc, 0)
        self.assertNotIn("forseti antianchor <status", out)

    def test_probemodel_旗標當第一參數的時候當成預設子指令(self):
        """`status` 的回傳值看認證狀態（0 或 1），所以這裡不能斷言
        exit code —— 斷言的是**它沒有掉到最後那條 usage**（那條回 2）。"""
        rc, out = _run(PM, ["--check-auth"])
        self.assertIn(rc, (0, 1))
        self.assertNotIn("forseti probe-model <status", out)

    def test_四支的算法一致而且不是各寫一份(self):
        """同一個 bug 出現在四個檔，是因為這兩行被複製過。這一條
        盯的是它們沒有在修的時候又漂開 —— 例如有人只在其中一支
        改成 `argv[0][0] != '-'`，那對空字串會 IndexError。"""
        for mod in (MT, AT, AA, PM):
            with self.subTest(mod=mod.__name__):
                rc, _ = _run(mod, [""])
                self.assertIsInstance(rc, int)


class SilentFallthrough(_Box):
    """只有 metric 與 attempt 這兩支先前會靜默掉進 list。

    另外兩支本來就有守門，所以不在這一組 —— 把四支放進同一組
    會讓「這兩支先前是靜默的」這件事消失。
    """

    def test_metric_打錯子指令不當成list(self):
        rc, out = _run(MT, ["registr", "--from", "x"])
        self.assertEqual(rc, 2)
        self.assertIn("不認得", out)
        self.assertNotIn("登記簿　", out)

    def test_attempt_打錯子指令不當成list(self):
        rc, out = _run(AT, ["lst", "--path", str(self.jsonl([], "a.jsonl"))])
        self.assertEqual(rc, 2)
        self.assertIn("不認得", out)

    def test_打錯的時候要印得出有哪些可以用(self):
        """少了這一段，使用者看到「不認得」之後的下一步是再猜一次。"""
        for mod, want in ((MT, "register"), (AT, "release")):
            with self.subTest(mod=mod.__name__):
                _, out = _run(mod, ["nope"])
                self.assertIn(want, out)

    def test_常數列的就是main真的認得的那幾個(self):
        """`SUBCOMMANDS` 跟底下那幾條 `sub == "..."` 各寫一份，
        漂開的話會出現「守門說認得、main 裡沒有分支」的子指令 ——
        那種會靜默掉進預設，正是這個檔要擋的東西。"""
        import re
        for mod, dflt in ((MT, "list"), (AT, "list")):
            with self.subTest(mod=mod.__name__):
                src = Path(mod.__file__).read_text(encoding="utf-8")
                body = src[src.index("def main("):]
                branches = set(re.findall(r'sub == "([a-z_]+)"', body))
                self.assertEqual(set(mod.SUBCOMMANDS), branches | {dflt})


class ArgValue(_Box):
    """`--path` 後面接什麼，三支的答案要一樣。

    2026-09-18 實測，同一個旗標在三個檔有三種解析器，兩種靜默錯：

    | 檔 | 等號寫法 `--path=X` | 缺值 `--path` |
    |---|---|---|
    | `metrics.py` | 收 | 靜默讀正本，exit=0 |
    | `attempts.py` | 收 | 靜默讀正本（正本有資料），exit=0 |
    | `evidence.py` | **靜默丟掉，讀正本** | 靜默讀正本，exit=0 |

    兩種都是「錯的答案跟對的答案長得一樣」——
    `evidence` 那一格回「0 筆」，而正本此刻真的是 0 筆。

    `antianchor.py` 的 `--root` 是同一個形狀。上面那一輪寫著
    「量不出後果」，**2026-09-18 下一輪量出來了，所以那句話不算數**。
    量不出來的原因不在它身上，在量的方法：先前沒有帶 `--session`，
    而 `state()` 照 session 濾，兩個 root 都答「這條線還沒走過」，
    於是兩邊印出來的字當然一樣。帶對 session 之後三種寫法三種答案 ——
    `--root=X` 靜默丟掉、去讀正本、印出正本那一筆推導。

    它的 `--session` 比 `--root` 重：`_session()` 自己那句註解寫著
    權限綁在那個值上，而等號寫法先前會靜默掉回 `current_session()`，
    **他問的是別條線，拿到的是自己這條線的答案**。
    """

    def test_等號寫法三支都要收(self):
        """先前只有 evidence 不收。它回的是正本的 0 筆，
        跟「登記簿是空的」那句正常輸出一模一樣。"""
        for mod, rows, name, want in (
                (MT, [{"metric_id": "m-EQ01"}], "m.jsonl", "m-EQ01"),
                (AT, [], "a.jsonl", "共 0 筆"),
                (EV, [{"id": "ev-EQ01", "strength": "E5", "about": "x",
                       "sources": [], "observed_at": 0}], "e.jsonl", "ev-EQ01")):
            with self.subTest(mod=mod.__name__):
                p = self.jsonl(rows, name)
                rc, out = _run(mod, ["list", f"--path={p}"])
                self.assertEqual(rc, 0)
                self.assertIn(want, out)

    def test_等號寫法跟空格寫法讀到的是同一個檔(self):
        """只斷言「收了等號」還不夠 —— 收了但解錯一樣是錯的答案。
        兩種寫法的輸出要逐字相同。"""
        p = self.jsonl([{"metric_id": "m-SAME01"}], "m.jsonl")
        _, a = _run(MT, ["list", "--path", str(p)])
        _, b = _run(MT, ["list", f"--path={p}"])
        self.assertEqual(a, b)

    def test_缺值的時候明著退回不准掉回正本(self):
        """手滑漏掉路徑的人先前拿到的是正本的內容。attempt 那一支
        實測回的是 att-2bb74c352d 五欄完整 —— **那個人以為他看到的
        是自己指定的檔**。"""
        for mod in (MT, AT, EV):
            with self.subTest(mod=mod.__name__):
                rc, out = _run(mod, ["list", "--path"])
                self.assertEqual(rc, 2)
                self.assertIn("--path", out)

    def test_缺值守門不准把有值的也擋掉(self):
        """退回得太寬的話，這個守門會把正常用法也擋住，
        而那種壞法比原本的靜默錯更明顯 —— 明顯不等於不用守。"""
        p = self.jsonl([], "a.jsonl")
        for argv in (["list", "--path", str(p)], ["list", f"--path={p}"]):
            with self.subTest(argv=argv):
                rc, _ = _run(AT, argv)
                self.assertEqual(rc, 0)

    def test_重複出現的時候取第一個而且三支一樣(self):
        """先前沒有人量過。三支的 `_arg` 都是「掃到第一個就回」，
        這一條把那個行為釘住 —— 不是因為第一個比較對，
        是因為三支給不同答案的話，同一條指令的意思會隨著
        它打到哪一支而變。"""
        first = self.jsonl([{"metric_id": "m-FIRST"}], "first.jsonl")
        second = self.jsonl([{"metric_id": "m-SECOND"}], "second.jsonl")
        rc, out = _run(MT, ["list", "--path", str(first),
                            "--path", str(second)])
        self.assertEqual(rc, 0)
        self.assertIn("m-FIRST", out)
        self.assertNotIn("m-SECOND", out)

    # --- antianchor：上面那段 docstring 說明為什麼它先前不在這一組 ---

    def aa_root(self, name: str, session: str) -> Path:
        """造一個 antianchor 看得懂的根目錄，裡面有一筆 OPEN。

        **不呼叫 `open_derivation()` 去造**：那一支會去讀
        `desktop_api`，於是這個檔會變成在測別的東西。
        """
        root = self.tmp / name
        (root / ".forseti").mkdir(parents=True, exist_ok=True)
        (root / ".forseti" / "antianchor.jsonl").write_text(
            json.dumps({"kind": "OPEN", "id": name, "at": 0,
                        "session": session, "canonical_sha": "x",
                        "answerable": [], "unanswerable": [], "asks": []},
                       ensure_ascii=False) + "\n", encoding="utf-8")
        return root

    def test_antianchor_等號寫法讀的是指定的那個root(self):
        """先前靜默丟掉，掉回正本 —— 而正本此刻真的有兩筆推導，
        所以那個人看到的是一份看起來正常的狀態。"""
        sess = "S-EQ01"
        a = self.aa_root("aa111111", sess)
        rc, out = _run(AA, ["status", f"--root={a}", "--session", sess])
        self.assertEqual(rc, 0)
        self.assertIn("aa111111", out)

    def test_antianchor_等號跟空格印出來的字要一樣(self):
        """收了等號還不夠，解錯一樣是錯的答案。"""
        sess = "S-EQ02"
        a = self.aa_root("aa222222", sess)
        _, x = _run(AA, ["status", "--root", str(a), "--session", sess])
        _, y = _run(AA, ["status", f"--root={a}", "--session", sess])
        self.assertEqual(x, y)

    def test_antianchor_root缺值明著退回不准掉回正本(self):
        rc, out = _run(AA, ["status", "--root"])
        self.assertEqual(rc, 2)
        self.assertIn("--root", out)
        self.assertNotIn("和解完成", out)

    def test_antianchor_session缺值明著退回(self):
        """這一條守的後果比 `--root` 重。`_session()` 缺值的時候
        掉回 `forseti.current_session()`，也就是**問別人、答自己**，
        而權限就綁在那個值上。"""
        a = self.aa_root("aa333333", "S-EQ03")
        rc, out = _run(AA, ["status", "--root", str(a), "--session"])
        self.assertEqual(rc, 2)
        self.assertIn("--session", out)

    def test_antianchor_session等號寫法讀的是指定的那條線(self):
        """`_session()` 是另一份解析器，不吃 `_arg`。
        兩份都要收等號，只修一份的話 `--session=X` 照樣靜默掉回。"""
        sess = "S-EQ04"
        a = self.aa_root("aa444444", sess)
        rc, out = _run(AA, ["status", "--root", str(a), f"--session={sess}"])
        self.assertEqual(rc, 0)
        self.assertIn(sess, out)
        self.assertIn("aa444444", out)

    def test_antianchor_缺值守門不准把有值的也擋掉(self):
        sess = "S-EQ05"
        a = self.aa_root("aa555555", sess)
        for argv in (["status", "--root", str(a), "--session", sess],
                     ["status", f"--root={a}", f"--session={sess}"]):
            with self.subTest(argv=argv):
                rc, _ = _run(AA, argv)
                self.assertEqual(rc, 0)

    def test_antianchor_重複出現取第一個跟另外三支一樣(self):
        """三支已經釘住「取第一個」，這一條把第四支接上去 ——
        不是因為第一個比較對，是因為四支給不同答案的話，
        同一條指令的意思會隨著它打到哪一支而變。"""
        sess = "S-EQ06"
        first = self.aa_root("aa666666", sess)
        second = self.aa_root("aa777777", sess)
        rc, out = _run(AA, ["status", "--root", str(first),
                            "--root", str(second), "--session", sess])
        self.assertEqual(rc, 0)
        self.assertIn("aa666666", out)
        self.assertNotIn("aa777777", out)

    def test_四支的缺值判準一模一樣(self):
        """`_flag_without_value` 現在是五份複製品（2026-09-18 加上
        `probemodel`）。抽共用是設計決定，
        這一條不做那個決定，只盯它們沒有漂開 —— 先前
        `test_四支的算法一致而且不是各寫一份` 盯的是 `_flag_first`，
        同一個理由。

        五支各自的旗標名不同（三支 `--path`、`antianchor` `--root`、
        `probemodel` `--only`），
        所以比的是函式本身在同一組輸入上的答案，不是原始碼字串。
        """
        cases = [([], False), (["--f"], True), (["--f", "v"], False),
                 (["--f="], False), (["--f=v"], False),
                 (["x", "--f"], True),
                 # 這一條 2026-09-18 從 False 換邊成 True。原本的 False
                 # 是在「守 `--path` 缺值」那個題目底下寫的，而那時候
                 # 沒有人量過「值是另一個旗標」會怎樣。量了之後是
                 # `antianchor classify --by --reason X` 落地成
                 # `by='--reason'`、exit=0、畫面印「記下了」，
                 # 所以原本那條斷言釘住的是一個錯的行為。
                 # 換邊不是放寬：`--f=--g` 那一條仍然是 False，
                 # 也就是明著用等號傳減號開頭的值照樣收。
                 (["--f", "--g"], True), (["--f", "--g=v"], True),
                 (["--f=--g"], False), (["--f", "-1"], False),
                 # 下面這兩條是 2026-09-18 反向注入補的。拿掉判準裡
                 # `startswith(name + "=")` 那一半，上面七條**全部照樣綠**
                 # —— 因為第一個 `any` 要的是 `a == name` 逐字相等，
                 # 而單獨一個 `--f=v` 根本進不到第二個 `any`。
                 # 那一半只有在旗標出現兩次（一次裸的、一次帶等號）
                 # 的時候才走得到。五份複製品從以前就都是這樣。
                 (["--f=v", "--f"], False), (["--f", "--f=v"], False)]
        for argv, want in cases:
            with self.subTest(argv=argv):
                got = {m.__name__: m._flag_without_value(argv, "--f")
                       for m in (MT, AT, EV, AA, PM)}
                self.assertEqual(set(got.values()), {want}, got)

    def test_evidence也吃旗標當第一參數(self):
        """`evidence.py` 的守門是 08:2x 那一輪加的，形狀跟另外四支
        一樣，可是守它的測試在 `test_evidence_cli.py::Args`。
        同一個判準兩個檔各守一半，改判準的人只會看到其中一個。"""
        p = self.jsonl([{"id": "ev-FLAG01", "strength": "E5", "about": "x",
                         "sources": [], "observed_at": 0}], "e.jsonl")
        rc, out = _run(EV, ["--path", str(p)])
        self.assertEqual(rc, 0)
        self.assertIn("ev-FLAG01", out)


class OnlyFlag(_Box):
    """`probemodel run --only` ——  五支裡最後一支，而且後果不同級。

    另外四支的缺值／等號寫法掉回去讀正本，是**答案錯**。
    這一支掉回去的是 `only=None`，而 `run()` 拿 None 當「不過濾」，
    於是它跑滿 `len(PACK) × models × modes` 次真的模型呼叫。
    2026-09-18 實測那是 36 次，指定一題是 4 次 —— **是花錢**。

    這一組一次都不呼叫模型：攔 `PM.run` 只記下 `only` 收到什麼。
    攔的位置是 `main()` 的下游，所以量到的正是解析結果本身。
    """

    def setUp(self):
        super().setUp()
        self._real_run = PM.run
        self.seen: list = []

        def _spy(**kw):
            self.seen.append(kw.get("only"))
            return {"rows": [], "by_state": {}, "judged": 0,
                    "passed": 0, "rate": None}

        PM.run = _spy

    def tearDown(self):
        PM.run = self._real_run
        super().tearDown()

    def test_等號寫法讀得到而且不再靜默跑滿(self):
        rc, _ = _run(PM, ["run", "--yes", "--only=goal_persistence"])
        self.assertEqual(self.seen, ["goal_persistence"],
                         "等號寫法被丟掉的話 only 是 None，"
                         "run() 會跑滿 36 次而不是 4 次")
        self.assertEqual(rc, 1)   # 沒有 row 所以 rate 不是 1.0

    def test_等號跟空格讀到的是同一題(self):
        _run(PM, ["run", "--yes", "--only", "goal_persistence"])
        _run(PM, ["run", "--yes", "--only=goal_persistence"])
        self.assertEqual(self.seen, ["goal_persistence"] * 2)

    def test_缺值明著退回而且沒有進run(self):
        rc, out = _run(PM, ["run", "--yes", "--only"])
        self.assertEqual(rc, 2)
        self.assertEqual(self.seen, [],
                         "缺值卻還是進了 run()，那一趟會跑滿")
        self.assertIn("--only", out)

    def test_缺值守門排在yes之前(self):
        """打錯的人要在乾跑那一刻就知道，不是等他決定花錢之後。

        沒有 `--yes` 的乾跑本來就回 2，所以這一條靠的不是 exit code，
        是印出來的字：擋下來的是缺值，不是「你還沒加 --yes」。
        """
        rc, out = _run(PM, ["run", "--only"])
        self.assertEqual(rc, 2)
        self.assertIn("--only", out)
        self.assertNotIn("確定的話加 --yes", out)

    def test_守門不准把有值的擋掉(self):
        rc, _ = _run(PM, ["run", "--yes", "--only", "goal_persistence"])
        self.assertEqual(self.seen, ["goal_persistence"])
        self.assertNotEqual(rc, 2)

    def test_不給only的時候照樣跑全部(self):
        """守門只擋「寫了旗標卻沒給值」，不擋「根本沒寫」。
        跑全部是這一支的正當用法，擋掉它等於把功能拿走。"""
        rc, _ = _run(PM, ["run", "--yes"])
        self.assertEqual(self.seen, [None])
        self.assertNotEqual(rc, 2)

    def test_重複出現取第一個跟另外四支一樣(self):
        """先前這一支取的是**最後一個**（迴圈沒有 break）。
        改成第一個不是因為第一個比較對，是因為五支給不同答案的話，
        同一條指令的意思會隨著它打到哪一支而變。

        2026-09-18 換材料：原本用的是 `A` 與 `B` 兩個假題名，而同一輪
        新加的「題名不在 PACK 裡就退回」會在走到 `run()` 之前擋掉它們，
        於是這一條量到的是新守門而不是取值順序。**題目沒有變**，
        變的是材料 —— 換成兩個真的題名，取第一個這件事照樣釘得住。"""
        _run(PM, ["run", "--yes",
                  "--only", "goal_persistence", "--only", "stale_cache"])
        self.assertEqual(self.seen, ["goal_persistence"])

    def test_五支的取值算法一模一樣(self):
        """比的是同一組輸入的答案，不是原始碼字串 —— 跟
        `test_四支的缺值判準一模一樣` 同一個理由。

        `antianchor._arg` 的簽章不同（多一個 `default`，沒找到回 `""`
        而不是 `None`），所以它不能放進同一個嚴格比較。
        那個差別是真的，不是可以「順手統一」掉的東西，
        這裡把它單獨比並且明著把 None 對到 ""。
        """
        cases = [([], None), (["--f", "v"], "v"), (["--f=v"], "v"),
                 (["--f"], None), (["--f="], ""),
                 (["--f", "a", "--f", "b"], "a"),
                 (["x", "--f", "v"], "v")]
        for argv, want in cases:
            with self.subTest(argv=argv):
                got = {m.__name__: m._arg(argv, "--f")
                       for m in (MT, AT, EV, PM)}
                self.assertEqual(set(got.values()), {want}, got)
                self.assertEqual(AA._arg(argv, "--f"), want or "",
                                 "antianchar 那一份漂開了")


if __name__ == "__main__":
    unittest.main()


class FlagAsValue(_Box):
    """旗標後面接的是另一個旗標的時候，不准當成他給了值。

    這一組跟 `ArgValue`／`OnlyFlag` 守的不是同一個形狀。那兩組守的是
    「旗標出現了，後面什麼都沒有」（`--by` 在結尾）。這一組守的是
    「後面有東西，可是那個東西是下一個旗標」（`--by --reason X`），
    而先前的守門對這一種一律回 False —— 五份複製品都一樣。

    2026-09-18 實測，後果分三級，不是一級：

    | 呼叫點 | 打錯之後 | 級 |
    |---|---|---|
    | `antianchor classify --by --reason X` | exit=0、印「記下了」、磁碟落地 `by='--reason'` | 錯的答案長得跟對的一樣 |
    | `attempt record --from --path=X` | exit=2，訊息是「讀不到 --path=...」 | 看得到，可是怪錯對象 |
    | `evidence/metric show --id --path=X` | exit=1，「不在登記簿上」 | 診斷指錯：他會以為那筆不存在 |

    最上面那一級是這一組存在的理由。`classify()` 內部本來就擋空的
    `by`（§39 那四類沒有一類算得出來，所以必填），所以擋不住的不是
    空的，是**被下一個旗標填滿的**。那一筆是 append-only，
    寫進去就在那裡，而畫面上跟成功一模一樣。
    """

    def aa_ready(self, name: str, session: str = "S-FAV") -> Path:
        """造一個走到 REVEAL、還有一欄等著分類的根目錄。

        直接寫 jsonl 不呼叫 `reveal()`，理由同 `aa_root`：那一支會去讀
        `desktop_api`，於是這個檔會變成在測別的東西。
        """
        root = self.tmp / name
        (root / ".forseti").mkdir(parents=True, exist_ok=True)
        rows = [
            {"kind": "OPEN", "id": name, "at": 0, "session": session,
             "canonical_sha": "x", "answerable": [], "unanswerable": [],
             "asks": []},
            {"kind": "REVEAL", "id": name, "at": 0, "session": session,
             "needs_classification": ["blockers"], "verified_fields": [],
             "nothing_verified": [], "differences": []},
        ]
        (root / ".forseti" / "antianchor.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")
        return root

    def classify_rows(self, root: Path) -> list:
        lines = (root / ".forseti" / "antianchor.jsonl").read_text(
            encoding="utf-8").splitlines()
        return [json.loads(x) for x in lines if x.strip()
                and json.loads(x).get("kind") == "CLASSIFY"]

    def test_classify的by接到下一個旗標不准落地(self):
        """這一條是整組的起點，而斷言要盯著**磁碟**不是盯著回傳值。

        先前的行為是 exit=0 加一行「記下了」，也就是只看畫面看不出
        問題；真正的損害在 `antianchor.jsonl` 那一筆 `by='--reason'`。
        """
        r = self.aa_ready("aafav01")
        rc, out = _run(AA, ["classify", "aafav01", "blockers",
                            "CHANGED_REALITY", f"--root={r}",
                            "--by", "--reason", "環境變了"])
        self.assertEqual(rc, 2)
        self.assertIn("--by", out)
        self.assertEqual(self.classify_rows(r), [])

    def test_classify的by有值的時候照樣記得下來(self):
        """守門不准把對的擋掉。少了這一條，把守門寫成
        「`--by` 出現就退回」也會全綠。"""
        r = self.aa_ready("aafav02")
        rc, _out = _run(AA, ["classify", "aafav02", "blockers",
                             "CHANGED_REALITY", f"--root={r}",
                             "--by", "norika", "--reason", "環境變了"])
        self.assertEqual(rc, 0)
        rows = self.classify_rows(r)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["by"], "norika")
        self.assertEqual(rows[0]["reason"], "環境變了")

    def test_用等號明著傳減號開頭的值還是收(self):
        """這一條守的是「沒有失去表達能力」。判準只認兩個減號開頭的
        下一個詞，等號那條路照樣走得通 —— 所以擋掉的是手滑，
        不是擋掉一種寫法。"""
        r = self.aa_ready("aafav03")
        rc, _out = _run(AA, ["classify", "aafav03", "blockers",
                             "CHANGED_REALITY", f"--root={r}",
                             "--by=--reason"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.classify_rows(r)[0]["by"], "--reason")

    def test_classify的reason接到下一個旗標也擋(self):
        """`--reason` 是選填的，可是「寫了而且掉了值」跟「沒寫」
        不是同一件事：記成空的之後，跟從來沒給理由長得一樣。"""
        r = self.aa_ready("aafav04")
        rc, out = _run(AA, ["classify", "aafav04", "blockers",
                            "CHANGED_REALITY", f"--root={r}",
                            "--reason", "--by", "norika"])
        self.assertEqual(rc, 2)
        self.assertIn("--reason", out)
        self.assertEqual(self.classify_rows(r), [])

    def test_evidence的id接到旗標退回而不是說不在登記簿上(self):
        """斷言要包含「不准出現那句話」。先前 exit=1 加
        「`--path=...` 不在登記簿上」，那個人會去查那筆資料為什麼
        不見了，而真正的事是他的指令打錯了 —— 順帶被吞掉的
        `--path` 還讓它讀的是別的檔。"""
        p = self.jsonl([{"id": "ev-FAV00001", "strength": "E5", "about": "x",
                         "sources": [], "observed_at": 0}], "e.jsonl")
        rc, out = _run(EV, ["show", "--id", f"--path={p}"])
        self.assertEqual(rc, 2)
        self.assertNotIn("不在登記簿上", out)

    def test_evidence的id有值的時候照樣查得到(self):
        p = self.jsonl([{"id": "ev-FAV00002", "strength": "E5", "about": "x",
                         "sources": [], "observed_at": 0}], "e.jsonl")
        rc, out = _run(EV, ["show", "--id", "ev-FAV00002", f"--path={p}"])
        self.assertEqual(rc, 0)
        self.assertIn("ev-FAV00002", out)

    def test_metric的id接到旗標退回而不是說沒有這一筆(self):
        p = self.jsonl([{"metric_id": "m-FAV01", "name": "x"}], "m.jsonl")
        rc, out = _run(MT, ["show", "--id", f"--path={p}"])
        self.assertEqual(rc, 2)
        self.assertNotIn("沒有這一筆", out)

    def test_attempt的from接到旗標退回而不是怪檔案不存在(self):
        """先前的訊息是「讀不到 --path=...：FileNotFoundError」。
        那句話把原因指到檔案系統，而原因是值漏了。"""
        p = self.jsonl([], "a.jsonl")
        rc, out = _run(AT, ["record", "--from", f"--path={p}"])
        self.assertEqual(rc, 2)
        self.assertNotIn("讀不到", out)

    def test_減號數字仍然算一個值(self):
        """判準只認兩個減號。這一條守的是「沒有順手把 `-1` 這種值
        也擋掉」—— 目前沒有呼叫端傳負數，所以這一條守的是以後。"""
        for m in (MT, AT, EV, AA, PM):
            with self.subTest(mod=m.__name__):
                self.assertFalse(m._flag_without_value(["--f", "-1"], "--f"))
                self.assertFalse(m._flag_without_value(["--f", "-"], "--f"))


class ContentFlagAsValue(_Box):
    """`attempt` 那七個**內容欄位**的旗標，接到下一個旗標不准落地。

    這一組跟 `FlagAsValue` 守的形狀一樣，級數不一樣。`FlagAsValue`
    那四個呼叫點裡有三個會報錯（只是怪錯對象），這七個一句話都不說。

    2026-09-18 實測，七個全部 exit=0、印「登錄了 att-xxxxxxxxxx」、
    磁碟落地把下一個旗標名寫成內容。撈出來確認過的四筆：

        `--attempt --observed "看到 X"` -> attempt='--observed'
        `--source --verifier me`        -> source=['--verifier']
        `--verifier --no-retry-basis X` -> verifier='--no-retry-basis'
        release `--why --verifier me`   -> RELEASE 那筆 why='--verifier'

    最後一個最重：`release` 存的就是「哪個條件成立了所以可以重試」，
    那一欄變成旗標名等於這筆放掉沒有理由 —— 正是 `release()` 內部
    明著擋空字串要防的那件事，只是空的擋得住，被填滿的擋不住。

    所以這一組的斷言一律盯著**磁碟**：畫面上看不出問題才是它的形狀。
    """

    FULL = ("--attempt", "試了 X", "--observed", "看到 Y",
            "--why", "前提錯", "--source", "a.py:1",
            "--verifier", "me", "--no-retry-basis", "做法錯")

    def argv_with(self, p: Path, swap: str) -> list:
        """把 `swap` 那個旗標的值拿掉，讓它後面直接接下一個旗標。"""
        out: list = ["record", f"--path={p}"]
        skip = False
        for i, tok in enumerate(self.FULL):
            if skip:
                skip = False
                continue
            out.append(tok)
            if tok == swap:
                skip = True
        return out

    def rows(self, p: Path) -> list:
        if not p.exists():
            return []
        return [json.loads(x) for x in
                p.read_text(encoding="utf-8").splitlines() if x.strip()]

    def test_七個內容旗標接到下一個旗標全部擋住而且磁碟是空的(self):
        for flag in ("--attempt", "--observed", "--why", "--source",
                     "--verifier", "--no-retry-basis"):
            with self.subTest(flag=flag):
                p = self.tmp / f"att{flag.strip('-')}.jsonl"
                rc, out = _run(AT, self.argv_with(p, flag))
                self.assertEqual(rc, 2)
                self.assertIn(flag, out)
                # 標記要連 id 一起比。守門那句話自己引用了「登錄了」
                # 三個字（2026-09-18 第一版這裡就是這樣假紅的），
                # 而成功那一行一定是「登錄了 att-」加十個十六進位字元。
                self.assertNotIn("登錄了 att-", out)
                self.assertEqual(self.rows(p), [])

    def test_retry_condition接到下一個旗標也擋(self):
        """這一個不在 `FULL` 裡（`FULL` 走的是 `no_retry_basis` 那一邊），
        所以單獨一條。兩個是二選一的關係，而「寫了而且掉了值」
        會讓二選一那道檢查以為兩個都填了。"""
        p = self.tmp / "attrc.jsonl"
        rc, out = _run(AT, ["record", f"--path={p}",
                            "--attempt", "試了 X", "--observed", "看到 Y",
                            "--why", "前提錯", "--source", "a.py:1",
                            "--verifier", "me",
                            "--retry-condition", "--no-retry-basis", "做法錯"])
        self.assertEqual(rc, 2)
        self.assertIn("--retry-condition", out)
        self.assertEqual(self.rows(p), [])

    def test_七個旗標有值的時候照樣登得下來(self):
        """守門不准把對的擋掉。少了這一條，把守門寫成
        「這七個出現就退回」也會全綠。"""
        p = self.tmp / "attok.jsonl"
        rc, out = _run(AT, ["record", f"--path={p}", *self.FULL])
        self.assertEqual(rc, 0)
        self.assertIn("登錄了", out)
        rows = self.rows(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["attempt"], "試了 X")
        self.assertEqual(rows[0]["observed_result"], "看到 Y")
        self.assertEqual(rows[0]["source"], ["a.py:1"])
        self.assertEqual(rows[0]["verifier"], "me")

    def test_release的why接到旗標不准落地一筆沒有理由的放掉(self):
        """`release` 這一支要單獨守，因為它跟 `record` 走的是不同分支，
        而它的損害不是「少一欄」是「這筆放掉說不出哪個條件成立了」。"""
        p = self.jsonl([{"id": "att-CFAV0001", "kind": "ATTEMPT",
                         "attempt": "a", "observed_result": "b",
                         "why_not_repeat": "c", "source": ["d"],
                         "verifier": "e", "retry_condition": "等登入",
                         "no_retry_basis": "", "at": 0}], "rel.jsonl")
        rc, out = _run(AT, ["release", "att-CFAV0001", f"--path={p}",
                            "--why", "--verifier", "me"])
        self.assertEqual(rc, 2)
        self.assertNotIn("放掉了", out)
        self.assertEqual([r for r in self.rows(p)
                          if r.get("kind") == "RELEASE"], [])

    def test_release的why有值的時候照樣放得掉(self):
        p = self.jsonl([{"id": "att-CFAV0002", "kind": "ATTEMPT",
                         "attempt": "a", "observed_result": "b",
                         "why_not_repeat": "c", "source": ["d"],
                         "verifier": "e", "retry_condition": "等登入",
                         "no_retry_basis": "", "at": 0}], "rel2.jsonl")
        rc, _out = _run(AT, ["release", "att-CFAV0002", f"--path={p}",
                             "--why", "條件變了", "--verifier", "me"])
        self.assertEqual(rc, 0)
        rel = [r for r in self.rows(p) if r.get("kind") == "RELEASE"]
        self.assertEqual(len(rel), 1)
        self.assertEqual(rel[0]["why"], "條件變了")

    def test_用等號明著傳減號開頭的內容還是收(self):
        """守的是「沒有失去表達能力」。判準只認兩個減號開頭的下一個詞。"""
        p = self.tmp / "atteq.jsonl"
        rc, _out = _run(AT, ["record", f"--path={p}",
                             "--attempt=--observed", "--observed", "看到 Y",
                             "--why", "前提錯", "--source", "a.py:1",
                             "--verifier", "me", "--no-retry-basis", "做法錯"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.rows(p)[0]["attempt"], "--observed")


class UnknownFlag(_Box):
    """旗標名打錯字：五支先前沒有一支說得出「我不認得這個名字」。

    這一組是 2026-09-18 補的，連續四輪被順延的那一項。跟
    `MissingValue` 那一組不是同一件事 —— `_flag_without_value` 找的是
    **正確的那個名字**（`any(a == name ...)`），所以名字本身打錯的時候
    它一律不觸發。兩道守門守的是相鄰的兩個洞。

    2026-09-18 逐支實測的後果，分三級：

    | 寫法 | 舊 exit | 舊行為 |
    |---|---|---|
    | `probe-model run --yes --onlyy X` | 1 | 不過濾，**36 次呼叫真的發出去** |
    | `antianchor status --roott X` | 0 | 讀正本，畫面跟成功一樣 |
    | `attempt record --retry-conditionn X` | 0 | 印「登錄了」，那一欄落地是空的 |
    | `metric template --transcriptt X` | 0 | 模板照印，缺席理由指錯原因 |
    | `evidence show --idd X` | 2 | 報錯，可是怪「你沒給 id」 |

    最重的是第一列：它不是答案錯，是花錢。`--only` 的缺值守門那一段
    自己的註解寫著「排在 `--yes` 之前，不是之後」，理由是手滑的人要在
    決定花錢之前就知道 —— 而那個理由對打錯字這條路完全沒有生效過。
    """

    def test_五支的判準一模一樣(self):
        """`_unknown_flags` 是五份複製品，同 `_flag_without_value`。
        抽共用是設計決定，這一條不做那個決定，只盯它們沒有漂開。

        比的是函式在同一組輸入上的答案，不是原始碼字串 —— 五支的
        `KNOWN_FLAGS` 內容不同，所以測試自己傳一份假的進去。
        """
        known = ("--path", "--from")
        cases = [
            ([], []),
            (["--path", "x"], []),
            (["--path=x"], []),
            (["--pathh", "x"], ["--pathh"]),
            (["--path=x", "--fromm=y"], ["--fromm"]),
            # 明著用等號傳一個減號開頭的值：比的是等號前面那一段，
            # 所以 `--from` 已知，值不算旗標。這一條守的是
            # 「沒有失去表達能力」，跟 `_flag_without_value` 同一個取捨。
            (["--from=--path"], []),
            # 裸的 `--` 跳過。五支都沒有實作那個慣例標記，這道守門
            # 不替它作決定 —— 這一條釘住的是現況，不是主張它該被忽略。
            (["--"], []),
            # 位置參數與負數不受影響，判準只認兩個減號。
            (["att-1234", "-1", "blockers"], []),
            # 重複的只報一次，報的順序照出現順序。
            (["--zz", "--yy", "--zz"], ["--zz", "--yy"]),
        ]
        for argv, want in cases:
            with self.subTest(argv=argv):
                got = {m.__name__: m._unknown_flags(argv, known)
                       for m in (MT, AT, EV, AA, PM)}
                self.assertEqual({tuple(v) for v in got.values()},
                                 {tuple(want)}, got)

    def test_常數列的就是main真的讀的那幾個(self):
        """`KNOWN_FLAGS` 跟 `main()` 裡那些 `_arg(rest, "--x")` 各寫
        一份。漂開的方向有兩個，而且不同級：

        **宣告了沒人讀** —— 那個旗標打對了也沒用，跟打錯字一樣靜默，
        而守門會說它認得。這是這一條主要要擋的。

        **讀了沒宣告** —— 守門會把一個真的有用的旗標擋掉。那是
        安全失敗（明著退回 exit=2），用的人馬上看得到，所以比較輕。

        判準的限制寫在這裡，不吹：撈的是 `main()` 的 AST 字串常數
        （排掉 docstring），所以一個**只出現在錯誤訊息裡、沒有人真的
        讀**的旗標，這一條抓不到。要抓那一種得追 `_arg` 的實際呼叫，
        那是另一個題目。
        """
        import ast
        import re
        pat = re.compile(r"--[a-z][a-z0-9-]*")
        for mod in (MT, AT, EV, AA, PM):
            with self.subTest(mod=mod.__name__):
                src = Path(mod.__file__).read_text(encoding="utf-8")
                tree = ast.parse(src)
                main = next(f for f in tree.body
                            if isinstance(f, ast.FunctionDef)
                            and f.name == "main")
                doc = ast.get_docstring(main) or ""
                found = set()
                for node in ast.walk(main):
                    if (isinstance(node, ast.Constant)
                            and isinstance(node.value, str)
                            and node.value != doc):
                        found |= set(pat.findall(node.value))
                self.assertEqual(set(mod.KNOWN_FLAGS) - found, set(),
                                 "宣告認得可是 main 裡沒人讀")
                self.assertEqual(found - set(mod.KNOWN_FLAGS), set(),
                                 "main 裡讀了可是守門不認得，會被擋掉")

    def test_probemodel打錯字不准進run(self):
        """五支裡唯一會花錢的那一條路。2026-09-18 實測舊行為：
        `run --yes --onlyy goal_persistence` exit=1，而且 36 次呼叫
        真的發出去了（全部 CALL_FAILED 是因為 OAuth 過期，不是因為
        被擋下來）。所以這一條斷言的不是 exit，是 `run` 沒有被叫到。
        """
        called = []
        orig = PM.run
        PM.run = lambda **kw: called.append(kw) or {"rows": [], "rate": 1.0}
        try:
            rc, out = _run(PM, ["run", "--yes", "--onlyy", "goal_persistence"])
        finally:
            PM.run = orig
        self.assertEqual(called, [])
        self.assertEqual(rc, 2)
        self.assertIn("--onlyy", out)

    def test_probemodel打錯字不准被當成沒加yes而印乾跑(self):
        """乾跑那一條也 return 2，所以光看 exit 分不出來。
        分辨的是訊息：打錯字要講「不認得這個旗標」，
        不是講「這會真的呼叫模型 N 次」。"""
        rc, out = _run(PM, ["run", "--yess", "--only", "goal_persistence"])
        self.assertEqual(rc, 2)
        self.assertIn("不認得這個旗標", out)
        self.assertNotIn("確定的話加 --yes", out)

    def test_四支靜默或指錯的都明著退回(self):
        """四支各一條，用的是 2026-09-18 實測到後果的那個寫法。
        `--path` / `--root` 一律指到暫存目錄，這個檔絕不碰正本。"""
        p = self.tmp / "unk.jsonl"
        cases = [
            (AA, ["status", "--roott", str(self.tmp)], "--roott"),
            (MT, ["template", "--transcriptt", str(p)], "--transcriptt"),
            (EV, ["show", "--idd", "ev-xxxxxxxxxx"], "--idd"),
            (AT, ["record", f"--path={p}",
                  "--attempt", "a", "--observed", "b", "--why", "c",
                  "--source", "d", "--verifier", "e",
                  "--retry-conditionn", "等登入",
                  "--no-retry-basis", "沒有"], "--retry-conditionn"),
        ]
        for mod, argv, bad in cases:
            with self.subTest(mod=mod.__name__):
                rc, out = _run(mod, argv)
                self.assertEqual(rc, 2, out)
                self.assertIn("不認得這個旗標", out)
                self.assertIn(bad, out)
        # 那一筆不准落地。舊行為是 exit=0、印「登錄了」、
        # `retry_condition` 是空字串。
        self.assertFalse(p.exists(), "被擋下來的那一筆不准寫進磁碟")

    def test_打錯字的時候要印得出有哪些可以用(self):
        """只說「不認得」的話，那個人要自己去猜正確的名字是什麼。
        這一條跟 `test_打錯的時候要印得出有哪些可以用`（子指令那一組）
        同一個理由。"""
        for mod, argv in ((MT, ["template", "--zzz", "x"]),
                          (AT, ["list", "--zzz", "x"]),
                          (EV, ["list", "--zzz", "x"]),
                          (AA, ["status", "--zzz", "x"]),
                          (PM, ["status", "--zzz", "x"])):
            with self.subTest(mod=mod.__name__):
                _rc, out = _run(mod, argv)
                for f in mod.KNOWN_FLAGS:
                    self.assertIn(f, out)

    def test_正確的寫法不准被誤擋(self):
        """守門不准順手把合法用法一起擋掉。五支各一條最短的正常路徑。"""
        p = self.tmp / "ok.jsonl"
        for mod, argv in ((PM, ["plan"]),
                          (MT, ["template"]),
                          (EV, ["levels"]),
                          (AA, ["status", "--root", str(self.tmp)]),
                          (AT, ["list", f"--path={p}"])):
            with self.subTest(mod=mod.__name__):
                rc, out = _run(mod, argv)
                self.assertEqual(rc, 0, out)
                self.assertNotIn("不認得這個旗標", out)

    def test_等號傳減號開頭的值照樣收(self):
        """代價那一半。`--attempt=--observed` 是明著傳一個減號開頭的
        內容，判準比的是等號前面那一段，所以不算未知旗標 ——
        跟 `MissingValue` 那一組的
        `test_用等號明著傳減號開頭的內容還是收` 是同一個取捨，
        差別是那一條守的是缺值守門，這一條守的是未知旗標守門。"""
        p = self.tmp / "eq.jsonl"
        rc, out = _run(AT, ["record", f"--path={p}",
                            "--attempt=--observed", "--observed", "看到 Y",
                            "--why", "前提錯", "--source", "a.py:1",
                            "--verifier", "me", "--no-retry-basis", "做法錯"])
        self.assertEqual(rc, 0, out)
        self.assertNotIn("不認得這個旗標", out)


class DryRunCount(_Box):
    """乾跑預告的次數，要等於按下 `--yes` 之後真的發生的次數。

    2026-09-18 之前不等於。`main()` 的乾跑寫死 `plan(PACK)`，
    而 `run()` 照 `--only` 過濾，兩份判準。當輪實測：
    `run --only goal_persistence` 印 36 次、實際 4 次；
    `run --only <不存在的題名>` 印 36 次、實際 0 次。

    這一組**一次都不呼叫模型**：攔 `PM.ask`，只數它被叫幾次。
    數 `ask` 而不是拿 `plan()` 再算一次，理由是後者會用被測對象
    自己的公式去驗自己 —— `ask` 的呼叫次數才是「真的發生了幾次」。
    """

    def setUp(self):
        super().setUp()
        self._real_ask = PM.ask
        self.asked: list = []

        def _spy(case, *, model, mode, timeout=180):
            self.asked.append((case.cls, model, mode))
            return {"verdict": case.expect, "state": "PASS", "ms": 1,
                    "raw": "", "reason": "", "model": model, "mode": mode}

        PM.ask = _spy

    def tearDown(self):
        PM.ask = self._real_ask
        super().tearDown()

    @staticmethod
    def _advertised(out: str) -> int:
        import re
        m = re.search(r"這會真的呼叫模型 (\d+) 次", out)
        assert m, out
        return int(m.group(1))

    def test_指定一題的時候預告的次數就是真的會跑的次數(self):
        rc, out = _run(PM, ["run", "--only", "goal_persistence"])
        self.assertEqual(rc, 2)
        said = self._advertised(out)
        _run(PM, ["run", "--yes", "--only", "goal_persistence"])
        self.assertEqual(said, len(self.asked),
                         f"乾跑說 {said} 次，實際呼叫 {len(self.asked)} 次")
        self.assertEqual(said, 4, "九題裡的一題乘兩個模型乘兩種 context")

    def test_每一題都要對得上不是只有第一題(self):
        """逐題量。只驗一題的話，過濾寫成「永遠回第一題」也會綠。"""
        for cls in PM.case_classes():
            with self.subTest(cls=cls):
                self.asked.clear()
                _rc, out = _run(PM, ["run", "--only", cls])
                said = self._advertised(out)
                _run(PM, ["run", "--yes", "--only", cls])
                self.assertEqual(said, len(self.asked))
                self.assertEqual({c for c, _m, _o in self.asked}, {cls},
                                 "挑出來的不是被指定的那一題")

    def test_不帶only的時候還是整包沒有被順手過濾掉(self):
        """代價那一半：修過濾不准把「不指定就全跑」一起改掉。"""
        _rc, out = _run(PM, ["run"])
        said = self._advertised(out)
        _run(PM, ["run", "--yes"])
        self.assertEqual(said, len(self.asked))
        self.assertEqual(said, 36)

    def test_等號寫法的預告也跟著過濾(self):
        _rc, out = _run(PM, ["run", "--only=stale_cache"])
        self.assertEqual(self._advertised(out), 4)


class UnknownOnlyValue(_Box):
    """`--only` 的**值**不在 PACK 裡 —— 跟旗標**名**不存在是相鄰兩個洞。

    2026-09-18 實測沒有這一道的後果：`run --yes --only bogus` 挑出 0 題、
    0 次呼叫、elapsed 0.0s，然後印一份 `judged=0` 的結果狀 JSON、exit=1。
    看起來像「跑過而且失敗了」，不是「你的題名不存在」。
    """

    def setUp(self):
        super().setUp()
        self._real_run = PM.run
        self.called: list = []

        def _spy(**kw):
            self.called.append(kw)
            return {"rows": [], "by_state": {}, "judged": 0,
                    "passed": 0, "rate": None}

        PM.run = _spy

    def tearDown(self):
        PM.run = self._real_run
        super().tearDown()

    def test_題名不存在要明著退回(self):
        rc, out = _run(PM, ["run", "--only", "bogus_nonexistent"])
        self.assertEqual(rc, 2)
        self.assertIn("沒有這一題", out)
        self.assertEqual(self.called, [], "退回了就不准還是走到 run()")

    def test_帶著yes也要在呼叫run之前擋住(self):
        """帶著 `--yes` 的那條路上，退回要發生在 `run()` 之前。

        這一條守的**不是**守門排在 `--yes` 檢查的哪一邊 —— 名字原本
        寫成「擋在花錢之前而不是之後」，而 2026-09-18 實測把守門整段
        搬到 `--yes` 區塊後面，這一條照樣綠（帶 `--yes` 的路上它還是
        擋得到）。真正紅的是隔壁那條 `test_題名不存在要明著退回`：
        守門搬到後面之後，不帶 `--yes` 的乾跑會先印完才走到守門。
        名字改掉，因為一個名字比它守得住的東西大，下一個人會以為
        順序有人管。"""
        rc, out = _run(PM, ["run", "--yes", "--only", "bogus_nonexistent"])
        self.assertEqual(rc, 2)
        self.assertIn("沒有這一題", out)
        self.assertEqual(self.called, [])

    def test_要印得出有哪些題名可以用(self):
        _rc, out = _run(PM, ["run", "--only", "typo"])
        for cls in PM.case_classes():
            self.assertIn(cls, out)

    def test_合法題名不准被誤擋(self):
        for cls in PM.case_classes():
            with self.subTest(cls=cls):
                rc, out = _run(PM, ["run", "--only", cls])
                self.assertEqual(rc, 2, out)         # 乾跑本來就是 2
                self.assertNotIn("沒有這一題", out)

    def test_題名的來源只有PACK一個(self):
        """`case_classes()` 不准是另抄一份清單。加一題進 PACK，
        它要跟著多一個 —— 不然兩份會漂開，而漂開的那一天
        合法題名會被這道守門擋掉。"""
        self.assertEqual(PM.case_classes(), tuple(c.cls for c in PM.PACK))

    def test_過濾只有一份判準(self):
        """`run()` 與乾跑不准各過濾一次。兩份判準正是這一輪修的東西。

        判準只看 `run` 那一支。`probe-model plan` 餵整個 PACK 是對的
        （那一支沒有 `--only`，它的題目就是「整包有多大」），
        第一次寫這條的時候用 `main()` 全文比字串，把那一支一起判紅 ——
        **守門自己的判準太寬，會把正確的用法也告進去。**
        """
        import ast
        import inspect
        # 讀的是真的那一支，不是 setUp 裝上去的 spy。
        self.assertIn("select(only)", inspect.getsource(self._real_run))

        tree = ast.parse(inspect.getsource(PM.main).lstrip())
        branch = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            t = node.test
            if (isinstance(t, ast.Compare)
                    and isinstance(t.left, ast.Name) and t.left.id == "sub"
                    and isinstance(t.comparators[0], ast.Constant)
                    and t.comparators[0].value == "run"):
                branch = node
        self.assertIsNotNone(branch, "找不到 `if sub == \"run\"` 那一支")

        fed = []
        for node in ast.walk(branch):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "plan"):
                fed.append(node.args[0])
        self.assertEqual(len(fed), 1, "run 那一支只該乾跑一次")
        self.assertTrue(
            isinstance(fed[0], ast.Call)
            and isinstance(fed[0].func, ast.Name)
            and fed[0].func.id == "select",
            "乾跑餵的不是 select() 過濾過的清單，"
            "那就是預告數字說謊的成因")


# ---------------------------------------------------------------------------
# 2026-09-18 12:xx：`probe` / `claims` / `overclaim` —— 上一輪寫下的
# 「另外幾支 CLI 沒有量過」量完了。四支裡三支有洞，而且三種形狀不一樣。
#
# | CLI | 打錯 | exit | 實際發生的事 |
# |---|---|---|---|
# | `probe lisst` | 子指令 | 0 | 靜默掉進 run，跑滿整包，印綠的 |
# | `probe --only X` | 旗標當子指令 | 0 | 同上，使用者要一題拿到十題 |
# | `probe run bogus` | 題名 | 0 | 挑 0 題印「PASS 0」，**空報告是綠的** |
# | `claims <檔> --limitt N` | 旗標名 | 0 | 靜默算整份 |
# | `claims <檔> --limit` | 缺值 | 0 | 同上 |
# | `claims <檔> --limit abc` | 值 | 1 | `int()` 的 traceback |
# | `gate submit/takover` | ── | 2 | **沒有洞**，三種都明著退回 |
#
# `gate` 那一列寫下來是因為「四支都有同一個洞」是這一輪一開始的預設，
# 量完是錯的。沒有量就不宣稱，反過來也一樣：量到沒有也要寫下來。
# ---------------------------------------------------------------------------

import probe as PB  # noqa: E402
import forseti as FS  # noqa: E402


class ProbeSubcommand(_Box):
    """`probe` 的第一個參數放錯東西，不准靜默跑滿整包。

    這一支跟前面五支不一樣的地方：它**根本沒有旗標**，三個位置全是
    位置參數。所以守的不是「旗標名打錯」，是「這個位置收得了哪些值」。
    """

    def setUp(self):
        super().setUp()
        self._real = PB.run
        self.called: list = []

        def _spy(**kw):
            self.called.append(kw)
            return {"results": [], "counts": {"PASS": 0, "REGRESSED": 0,
                                              "NEW": 0, "NO_VERIFIER": 0},
                    "measurable": 0, "axes_covered": (), "axes_missing": ()}

        PB.run = _spy

    def tearDown(self):
        PB.run = self._real
        super().tearDown()

    def test_旗標放在子指令的位置要退回(self):
        rc, out = _run(PB, ["--only", "goal_persistence"])
        self.assertEqual(rc, 2)
        self.assertIn("這一支沒有旗標", out)
        self.assertEqual(self.called, [], "退回了就不准還是跑整包")

    def test_子指令打錯字要退回(self):
        rc, out = _run(PB, ["lisst"])
        self.assertEqual(rc, 2)
        self.assertIn("不認得這個指令", out)
        self.assertEqual(self.called, [])

    def test_題名不存在要退回而不是印一份綠的空報告(self):
        """這一條是這一組裡最重的。

        沒有守門的時候 `probe run bogus_case` 印的是
        「可量的 0 個：PASS 0、REGRESSED 0」、exit=0 —— 通過率的
        分母跟分子同時是 0，於是它看起來跟「全過」一模一樣。
        """
        rc, out = _run(PB, ["run", "bogus_case"])
        self.assertEqual(rc, 2)
        self.assertIn("沒有這一題", out)
        self.assertEqual(self.called, [])

    def test_要印得出有哪些題名可以用(self):
        _rc, out = _run(PB, ["run", "typo"])
        for cid in PB.case_ids():
            self.assertIn(cid, out)

    def test_題名的來源只有PACK(self):
        self.assertEqual(PB.case_ids(), tuple(s.id for s in PB.PACK))
        self.assertTrue(PB.case_ids())

    def test_對的用法照樣走得到run(self):
        """守門不准擋住正確的三種寫法。"""
        rc, _out = _run(PB, ["run", PB.PACK[0].id])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.called), 1)
        self.assertEqual(self.called[0]["only"], PB.PACK[0].id)

    def test_不帶參數預設跑整包(self):
        rc, _out = _run(PB, [])
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.called), 1)
        self.assertIsNone(self.called[0]["only"])


class ProbeBaselineBy(_Box):
    """`probe baseline` 的「誰按的」收得了旗標長相的東西。

    這一條**沒有實跑過 CLI**：跑它會往正本寫一條基準線。
    量測改成攔 `record_baseline` 做 —— 攔得到就代表守門沒擋住，
    攔不到就代表擋住了。這比讀原始碼多一步，而那一步正是
    「它到底會不會走到寫入」。
    """

    def setUp(self):
        super().setUp()
        self._real = PB.record_baseline
        self.got: list = []

        def _spy(*a, **kw):
            self.got.append(kw.get("by"))
            return {"ok": True}

        PB.record_baseline = _spy

    def tearDown(self):
        PB.record_baseline = self._real
        super().tearDown()

    def test_旗標長相的名字不准落進基準線(self):
        rc, out = _run(PB, ["baseline", "--by"])
        self.assertEqual(rc, 2)
        self.assertIn("這不是人名", out)
        self.assertEqual(self.got, [],
                         "擋住了就不准還是走到 record_baseline")

    def test_真的人名照樣寫得進去(self):
        rc, _out = _run(PB, ["baseline", "norika"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.got, ["norika"])

    def test_空的名字還是由record_baseline自己擋(self):
        """守門不准把既有那條規則接管過來。

        `record_baseline` 自己第 567 行擋空字串，理由是
        「沒有人負責的基準線，事後沒有人答得出當時為什麼」。
        新守門只管旗標長相，空的照樣要走到它那裡去被擋。
        """
        PB.record_baseline = self._real
        rc, out = _run(PB, ["baseline"])
        self.assertEqual(rc, 2)
        self.assertIn("是誰按的", out)


class TranscriptLimit(unittest.TestCase):
    """`claims` 與 `overclaim` 的 `--limit`，三種錯各一句話。"""

    def test_旗標名打錯要退回(self):
        n, why = FS.transcript_limit(["t.jsonl", "--limitt", "2"])
        self.assertEqual(n, 0)
        self.assertIn("不認得這個旗標", why)
        self.assertIn("--limitt", why)

    def test_缺值要退回(self):
        n, why = FS.transcript_limit(["t.jsonl", "--limit"])
        self.assertEqual(n, 0)
        self.assertIn("後面沒有數字", why)

    def test_值不是整數要退回而不是丟traceback(self):
        n, why = FS.transcript_limit(["t.jsonl", "--limit", "abc"])
        self.assertEqual(n, 0)
        self.assertIn("要一個整數", why)

    def test_負數要退回(self):
        n, why = FS.transcript_limit(["t.jsonl", "--limit", "-3"])
        self.assertEqual(n, 0)
        self.assertIn("不能是負的", why)

    def test_對的用法收得到值(self):
        n, why = FS.transcript_limit(["t.jsonl", "--limit", "2"])
        self.assertEqual((n, why), (2, ""))

    def test_沒寫limit就是整份(self):
        self.assertEqual(FS.transcript_limit(["t.jsonl"]), (0, ""))

    def test_第一個參數是路徑不掃它(self):
        """路徑打成旗標長相的東西，由上面那道 `找不到：` 管。

        這裡也擋的話，使用者會拿到「不認得這個旗標」——
        而他的問題是路徑打錯，不是旗標打錯。指錯地方。
        """
        self.assertEqual(FS.transcript_limit(["--limit"]), (0, ""))

    def test_兩支共用同一份判準(self):
        """判準兩份的代價 2026-09-18 11:2x 在 `probemodel` 量過：
        乾跑預告 36 次、實際 4 次，而且沒有人會發現。
        所以這裡釘住 `cmd_claims` 與 `cmd_overclaim` 都只呼叫
        `transcript_limit`，各自不准再 `int()` 一次。"""
        import ast
        src = (ROOT / "apps" / "forseti-cli" / "forseti.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for name in ("cmd_claims", "cmd_overclaim"):
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == name)
            calls = [c.func.id for c in ast.walk(fn)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
            self.assertIn("transcript_limit", calls,
                          f"{name} 沒有走共用那一支")
            self.assertNotIn("int", calls,
                             f"{name} 自己又 int() 了一次，判準變兩份")


class TranscriptPath(unittest.TestCase):
    """`claims` 與 `overclaim` 的第一個參數：旗標放在路徑的位置。

    2026-09-18 12:3x 量到的：`claims --limit 2` 回
    `找不到：--limit`、exit=1。**那句話是真的**，檔案確實不存在，
    所以它不是靜默，也不是說謊 —— 它是指錯地方，而且 exit code
    把用法錯記成資料錯。

    這一組守兩件事，第二件比第一件難看見：
    退回那一條，以及**順序**（先查檔案在不在，再看它像不像旗標）。
    順序反過來的話，一個真的叫做 `--limit` 的檔案會被擋在外面，
    那是拿長相定罪。`test_真的叫做旗標名的檔案照樣收` 就是釘這一條，
    它在順序被換掉的時候會紅。
    """

    def test_旗標放在路徑的位置要講得出是位置錯(self):
        path, why, code = FS.transcript_path(["--limit", "2"], "claims")
        self.assertIsNone(path)
        self.assertIn("旗標", why)
        self.assertIn("--limit", why)

    def test_退回的是用法錯不是資料錯(self):
        """這一支的慣例是 2 = 用法錯、1 = 資料錯。
        改之前這一條走的是 1，因為它是從「檔案不存在」那條路出去的。"""
        self.assertEqual(FS.transcript_path(["--limit"], "claims")[2], 2)
        self.assertEqual(FS.transcript_path(["--limitt"], "overclaim")[2], 2)

    def test_檔案真的不存在還是回找不到(self):
        path, why, code = FS.transcript_path(["nosuch.jsonl"], "claims")
        self.assertIsNone(path)
        self.assertIn("找不到", why)
        self.assertEqual(code, 1)

    def test_真的叫做旗標名的檔案照樣收(self):
        """先查存在再看長相。這一條紅了就是順序被換掉了。

        **參數必須是相對路徑。** 第一版寫的是 `str(f)`，也就是
        `/var/.../--limit` 這種絕對路徑，而它不是 `-` 開頭 ——
        於是守門根本不會被走到，順序換掉這一條照樣綠。
        反向驗證當場量到「順序換掉紅 0 條」，測試的 docstring 卻寫著
        「這一條紅了就是順序被換掉了」。宣稱寫在上面不會讓下面照做，
        那是 2026-09-18 12:3x 同一個機制的第二次。
        """
        import os
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "--limit").write_text("{}\n", encoding="utf-8")
            cwd = os.getcwd()
            os.chdir(td)
            try:
                path, why, code = FS.transcript_path(["--limit"], "claims")
            finally:
                os.chdir(cwd)
            self.assertEqual((why, code), ("", 0))
            self.assertEqual(str(path), "--limit")

    def test_對的路徑收得到(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.jsonl"
            f.write_text("{}\n", encoding="utf-8")
            self.assertEqual(FS.transcript_path([str(f)], "claims"),
                             (f, "", 0))

    def test_用法那一行講的是被呼叫的那一支(self):
        """兩支共用一份判準，所以錯誤訊息要講得出是誰在報錯。
        寫死 `claims` 的話，`overclaim` 的使用者會照著抄錯的那一行。"""
        self.assertIn("overclaim",
                      FS.transcript_path(["--limit"], "overclaim")[1])
        self.assertNotIn("overclaim",
                         FS.transcript_path(["--limit"], "claims")[1])

    def test_兩支走同一份判準而且自己不再查一次(self):
        """判準兩份的代價 2026-09-18 11:2x 在 `probemodel` 量過。
        這裡釘住 `cmd_claims` 與 `cmd_overclaim` 都呼叫
        `transcript_path`，而且兩支自己不准再 `.exists()` 一次。"""
        import ast
        src = (ROOT / "apps" / "forseti-cli" / "forseti.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        for name in ("cmd_claims", "cmd_overclaim"):
            fn = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef) and n.name == name)
            named = [c.func.id for c in ast.walk(fn)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
            attrs = [c.func.attr for c in ast.walk(fn)
                     if isinstance(c, ast.Call)
                     and isinstance(c.func, ast.Attribute)]
            self.assertIn("transcript_path", named,
                          f"{name} 沒有走共用那一支")
            self.assertNotIn("exists", attrs,
                             f"{name} 自己又查了一次，判準變兩份")

    def test_端到端兩支都退回而且不印分析(self):
        for cmd in ("claims", "overclaim"):
            fn = getattr(FS, f"cmd_{cmd}")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), \
                    contextlib.redirect_stderr(buf):
                rc = fn(["--limit", "2"])
            out = buf.getvalue()
            self.assertEqual(rc, 2, f"{cmd} 沒有退回")
            self.assertIn("旗標", out)
            self.assertNotIn("UNEXTRACTABLE", out,
                             f"{cmd} 退回之後還是跑了分析")

    def test_真的路徑照樣跑得動(self):
        """守門加上去之後，對的用法不准跟著壞掉。"""
        line = json.dumps({"type": "assistant", "message": {"content": [
            {"type": "text", "text": "我建立了 soul.md 這個檔案。"}]}},
            ensure_ascii=False)
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "t.jsonl"
            f.write_text(line + "\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf), \
                    contextlib.redirect_stderr(buf):
                rc = FS.cmd_claims([str(f), "--limit", "1"])
            self.assertEqual(rc, 0)
            self.assertIn("soul.md", buf.getvalue())


class NoArgSubcommand(unittest.TestCase):
    """四支不吃參數的子指令：多餘參數不准被靜默吞掉。

    這一組守的是 2026-09-18 13:3x 量到的形狀。連續五輪的
    `AUTO_CONTINUE_LOG.md` 都寫著「旗標用錯子指令仍然沒人管」，
    而那句話本身指錯了對象 —— 它舉的例子是 `plan --yes`，
    可是 `plan` 根本不是子指令，那一條走的是 dispatch 末尾的
    `print(__doc__); return 2`，早就有人管。真正沒人管的是
    **合法子指令帶多餘參數**，也就是下面這四支。

    | 寫法 | 改之前 | 改之後 |
    |---|---|---|
    | `doctor --yes` | exit 0，印出一份正常的報告 | exit 2 |
    | `status --limit 5` | 同上 | exit 2 |
    | `gate status --yes` | 同上 | exit 2 |
    | `gate takeover --bogus x` | 同上，**而且寫一筆考卷進正本** | exit 2 |

    最後那一支是這四支裡唯一會改變狀態的，所以它有自己的兩條
    （`test_帶多餘參數不會走到寫入點` 與 `test_乾淨呼叫照樣走到寫入點`）。
    **兩條要一起在**：只有前面那一條的話，把整支擋死也會綠。
    """

    NO_ARG = (("doctor", "cmd_doctor"),
              ("status", "cmd_status"),
              ("gate takeover", "cmd_gate_takeover"),
              ("gate status", "cmd_gate_status"))

    @staticmethod
    def _dispatch(argv: list[str], spy_on: str):
        """跑 dispatch，攔掉真正那一支與 `build_report`，**不碰正本**。

        回 `(exit code, 那一支被呼叫幾次, 印出來的東西)`。
        攔 `build_report` 是因為守門在它後面，不攔的話每一條測試
        都要重讀一次正本。
        """
        import types
        calls = []
        orig_rep = FS.build_report
        orig_cmd = getattr(FS, spy_on)
        FS.build_report = lambda root: types.SimpleNamespace(root=ROOT)
        setattr(FS, spy_on, lambda *a, **k: (calls.append(1), 0)[1])
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf), \
                    contextlib.redirect_stderr(buf):
                rc = FS.main(["forseti"] + argv)
        finally:
            FS.build_report = orig_rep
            setattr(FS, spy_on, orig_cmd)
        return rc, len(calls), buf.getvalue()

    def test_乾淨呼叫四支都照樣走到那一支(self):
        """先釘這一條。只守退回的話，把四支擋死也會全綠。"""
        for cmd, spy in self.NO_ARG:
            with self.subTest(cmd=cmd):
                rc, n, _ = self._dispatch(cmd.split(), spy)
                self.assertEqual((rc, n), (0, 1))

    def test_多餘旗標四支都退回而且不走到那一支(self):
        for cmd, spy in self.NO_ARG:
            with self.subTest(cmd=cmd):
                rc, n, out = self._dispatch(cmd.split() + ["--yes"], spy)
                self.assertEqual((rc, n), (2, 0))
                self.assertIn("--yes", out)

    def test_多餘位置參數也退回(self):
        """位置參數跟旗標都是錯的，因為這一支不吃任何參數。
        只擋 `-` 開頭的話，`doctor foo` 照樣靜默。"""
        for cmd, spy in self.NO_ARG:
            with self.subTest(cmd=cmd):
                rc, n, out = self._dispatch(cmd.split() + ["foo"], spy)
                self.assertEqual((rc, n), (2, 0))
                self.assertIn("foo", out)

    def test_gate_takeover帶多餘參數不會走到寫入點(self):
        """這四支裡唯一會改變狀態的那一支。

        2026-09-18 13:3x 實測，改之前三種寫法都走到 `open_exam`
        （次數各 1），也就是使用者下錯指令照樣被記一筆考卷。
        攔 `open_exam` 而不是讀原始碼，是因為要量的是
        「會不會走到」，不是「看起來會不會走到」。
        """
        import sufficiency
        seen = []
        orig = sufficiency.open_exam
        sufficiency.open_exam = lambda *a, **k: seen.append(1)
        try:
            for extra in (["--yes"], ["--bogus", "x"], ["foo"]):
                with self.subTest(extra=extra):
                    seen.clear()
                    rc, _, _ = self._dispatch(
                        ["gate", "takeover"] + extra, "cmd_gate_status")
                    self.assertEqual((rc, len(seen)), (2, 0))
        finally:
            sufficiency.open_exam = orig

    def test_gate_takeover乾淨呼叫照樣走到寫入點(self):
        """上面那一條的另一半。這一條紅了代表整支被擋死，
        而那種擋法會讓上面那一條照樣綠 —— 兩條要一起看。

        這一條**不攔 `build_report`**，跟同組其他幾條不一樣：
        `cmd_gate_takeover` 在走到 `open_exam` 之前會讀 `rep.missing`，
        假的 rep 會在那裡就 AttributeError，於是永遠到不了寫入點 ——
        那樣這一條會因為錯的理由紅。讀正本是唯讀的。
        """
        import sufficiency
        seen = []
        orig = sufficiency.open_exam
        sufficiency.open_exam = lambda *a, **k: (seen.append(1),
                                                 (_ for _ in ()).throw(
                                                     SystemExit(0)))
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    FS.main(["forseti", "gate", "takeover"])
        finally:
            sufficiency.open_exam = orig
        self.assertEqual(len(seen), 1)

    def test_訊息講得出是哪一支(self):
        """四支共用一份判準，所以用法那一行要帶呼叫端的名字。
        寫死其中一支的話，另外三支的使用者會照著抄錯的那一行。"""
        for cmd, _ in self.NO_ARG:
            with self.subTest(cmd=cmd):
                why = FS.no_extra_args(["--yes"], cmd)
                self.assertIn(f"forseti.py {cmd}", why)

    def test_旗標與位置參數的措辭不同(self):
        """長相只拿來挑措辭，不決定 exit code。
        兩種都是 2，所以這裡沒有 `transcript_path` 那個
        「拿長相定罪」的風險。"""
        flag = FS.no_extra_args(["--yes"], "doctor")
        pos = FS.no_extra_args(["foo"], "doctor")
        self.assertIn("旗標", flag)
        self.assertIn("不吃參數", pos)
        self.assertNotEqual(flag, pos)

    def test_沒有參數的時候回空字串(self):
        for cmd, _ in self.NO_ARG:
            self.assertEqual(FS.no_extra_args([], cmd), "")

    def test_四個分支都走共用那一支而且自己不判斷(self):
        """判準一份給四支用。這一條釘的是「不准長出第二份」。

        定位分支的方式是**看它呼叫哪一支 `cmd_*`**，不是看 if 的
        條件怎麼寫 —— 條件的寫法會變（`gate` 那兩支是
        `cmd == "gate" and argv[2] == ...`），呼叫的那一支不會。
        """
        import ast
        src = (ROOT / "apps" / "forseti-cli" / "forseti.py").read_text(
            encoding="utf-8")
        tree = ast.parse(src)
        main = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        want = {spy for _, spy in self.NO_ARG}
        found = set()
        for node in ast.walk(main):
            if not isinstance(node, ast.If):
                continue
            named = [c.func.id for c in ast.walk(node)
                     if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
            hit = want & set(named)
            if not hit:
                continue
            found |= hit
            self.assertIn("no_extra_args", named,
                          f"{hit} 那一支沒有走共用判準")
            attrs = [c.func.attr for c in ast.walk(node)
                     if isinstance(c, ast.Call)
                     and isinstance(c.func, ast.Attribute)]
            self.assertNotIn("startswith", attrs,
                             f"{hit} 自己又判了一次，判準變兩份")
        self.assertEqual(found, want, "有分支沒被掃到")
