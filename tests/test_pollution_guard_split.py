"""還沒收乾淨的那幾筆裡，哪幾筆只靠人記得。

2026-09-18 自動接續那一輪加。起因寫在前一輪的「還缺什麼」：

    `NEXT.md` 上「21 筆還沒收乾淨」看不出 19 有守門、
    2 只靠人記得的差別。而「只靠人記得」那兩筆才是真正的風險。

這一組守兩件事：

1. `pollution.guard_split()` 的分母是 **open**，不是 `records()` 全部。
   `summary()['guarded']` 的分母是全部 —— 此刻 RESOLVED 是 0 所以兩者
   相等，**那是巧合**。這一組拿一筆 RESOLVED 把巧合拆掉。
2. 交接檔那一節真的把這個分別印出來，而且指名是哪幾筆。

規則性質的斷言寫到臨時檔，不碰正本；只有第 4 類（真實登記簿）讀正本，
而那幾條刻意寫成不綁死數字，只綁「這個分別在正本上目前不是空話」。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import contract as CT  # noqa: E402
import pollution  # noqa: E402


@pytest.fixture
def log(tmp_path):
    return tmp_path / "pollution.jsonl"


def 一筆(log, original, **kw):
    base = dict(
        original_claim=original,
        corrected_claim="實際不是那樣",
        failure_mechanism="把 A 當成 B，中間那一步沒去讀",
        source_events=["apps/forseti-cli/x.py:1"],
        verifier="test",
        radius_basis="規格沒定義單位",
        path=log,
    )
    base.update(kw)
    r = pollution.record(**base)
    assert r.get("ok") is True, r
    return r["record"]


class Test分母:
    def test_有守門的與只靠人記得的分開算(self, log):
        一筆(log, "甲", regression_probe="tests/test_a.py")
        一筆(log, "乙", preventive_rule="部署前守門")
        一筆(log, "丙")                       # 兩個都沒有
        s = pollution.guard_split(log)
        assert s["open"] == 3
        assert s["guarded"] == 2
        assert s["unguarded"] == 1

    def test_只靠人記得的是那幾筆_指名得出來(self, log):
        a = 一筆(log, "甲", regression_probe="tests/test_a.py")
        c = 一筆(log, "丙")
        s = pollution.guard_split(log)
        assert s["unguarded_ids"] == [c["id"]]
        assert a["id"] not in s["unguarded_ids"]

    def test_分母是open不是records全部(self, log):
        """這一條是整組的核心。

        RESOLVED 那一筆帶著 regression_probe（§40.2 的進入條件要求），
        所以它一定算在 `summary()['guarded']` 裡。而它已經收乾淨了，
        不該算在「還沒收乾淨的那幾筆」的分母裡。

        兩個數字因此必須分岔 —— 分岔就是這一支存在的理由。
        """
        一筆(log, "甲", regression_probe="tests/test_a.py")
        一筆(log, "丙")
        done = 一筆(log, "丁")
        pollution.advance(done["id"], "REVERIFIED", verifier="test", path=log)
        r = pollution.advance(done["id"], "RESOLVED",
                              regression_probe="tests/test_d.py", path=log)
        assert r.get("ok") is not False, r

        s = pollution.guard_split(log)
        m = pollution.summary(log)
        assert m["total"] == 3
        assert m["guarded"] == 2          # 甲 + 丁（丁 RESOLVED 也帶 probe）
        assert s["open"] == 2             # 丁 不算
        assert s["guarded"] == 1          # 只有甲
        assert s["guarded"] != m["guarded"], "兩個分母沒分岔，這一支就白寫了"

    def test_分母寫在回傳值裡(self, log):
        一筆(log, "甲")
        s = pollution.guard_split(log)
        assert "open" in s["denominator"]
        assert "RESOLVED" in s["denominator"]

    def test_全部有守門的時候unguarded是空的(self, log):
        一筆(log, "甲", regression_probe="tests/test_a.py")
        s = pollution.guard_split(log)
        assert s["unguarded"] == 0
        assert s["unguarded_ids"] == []

    def test_登記簿不存在就回零而不是爆掉(self, tmp_path):
        s = pollution.guard_split(tmp_path / "沒有這個檔.jsonl")
        assert s["open"] == 0
        assert s["unguarded_ids"] == []


class Test行文:
    def test_印出幾筆有守門幾筆只靠人記得(self):
        ctx = {"invalidated_conclusions": ["甲 → 乙"]}
        guard = {"open": 1, "guarded": 0, "unguarded": 1,
                 "unguarded_ids": ["pol-aaaa"]}
        txt = "\n".join(CT.invalidated_lines(ctx, guard=guard))
        assert "只靠人記得" in txt
        assert "pol-aaaa" in txt

    def test_指名得出多筆(self):
        ctx = {"invalidated_conclusions": ["甲 → 乙"]}
        guard = {"open": 3, "guarded": 1, "unguarded": 2,
                 "unguarded_ids": ["pol-aaaa", "pol-bbbb"]}
        txt = "\n".join(CT.invalidated_lines(ctx, guard=guard))
        assert "pol-aaaa" in txt and "pol-bbbb" in txt
        assert "2 筆現在只靠人記得" in txt

    def test_超過六筆就說還有幾筆沒列(self):
        ids = [f"pol-{i:04d}" for i in range(9)]
        ctx = {"invalidated_conclusions": ["甲 → 乙"]}
        guard = {"open": 9, "guarded": 0, "unguarded": 9, "unguarded_ids": ids}
        txt = "\n".join(CT.invalidated_lines(ctx, guard=guard))
        assert "還有 3 筆沒列" in txt
        assert ids[8] not in txt

    def test_全部有守門就不印只靠人記得那句(self):
        ctx = {"invalidated_conclusions": ["甲 → 乙"]}
        guard = {"open": 4, "guarded": 4, "unguarded": 0, "unguarded_ids": []}
        txt = "\n".join(CT.invalidated_lines(ctx, guard=guard))
        assert "只靠人記得" not in txt
        assert "全部" in txt

    def test_兩邊open對不起來就講出來_不挑一個印(self):
        """`rows` 是傳進來的，`guard` 是讀檔算的，不一致要看得到。"""
        ctx = {"invalidated_conclusions": ["甲 → 乙", "丙 → 丁"]}   # 2 筆
        guard = {"open": 7, "guarded": 7, "unguarded": 0, "unguarded_ids": []}
        txt = "\n".join(CT.invalidated_lines(ctx, guard=guard))
        assert "對不起來" in txt
        assert "2" in txt and "7" in txt

    def test_一致的時候不印那段雜訊(self):
        ctx = {"invalidated_conclusions": ["甲 → 乙"]}
        guard = {"open": 1, "guarded": 1, "unguarded": 0, "unguarded_ids": []}
        txt = "\n".join(CT.invalidated_lines(ctx, guard=guard))
        assert "對不起來" not in txt

    def test_問不到守門狀態就整段不印_不印未知(self):
        """`_guard_lines` 拿不到值的時候回空清單。

        **不准印「守門狀態未知」**：那句話對讀的人沒有作用，
        而且會讓這一節看起來比實際上知道得更多（§8.3）。
        """
        assert CT._guard_lines({}, 3) == []
        assert CT._guard_lines({"open": "壞的"}, 3) == []
        assert CT._guard_lines("不是 dict", 3) == []
        txt = "\n".join(CT.invalidated_lines(
            {"invalidated_conclusions": ["甲 → 乙"]},
            guard={"guarded": 1}))          # 缺 open / unguarded
        assert "守門" not in txt
        assert "未知" not in txt

    def test_沒有被推翻的結論時整節不印(self):
        assert CT.invalidated_lines({"invalidated_conclusions": []}) == []
        assert CT.invalidated_lines(None) == []


class Test接到正本:
    """這幾條讀正本 `.forseti/pollution.jsonl`，刻意不綁死數字。"""

    def test_不給guard就自己去問_數字跟guard_split一致(self):
        ctx = {"invalidated_conclusions": pollution.invalidated_conclusions()}
        txt = "\n".join(CT.invalidated_lines(ctx))
        s = pollution.guard_split()
        if s["open"] == 0:
            pytest.skip("正本登記簿此刻是空的")
        assert f"{s['guarded']} 筆" in txt

    def test_正本此刻真的有只靠人記得的筆數(self):
        """非空斷言。

        沒有這一條，上面那幾條會在「正本剛好全部有守門」的時候
        無聲成立 —— 而那正是這一輪要讓人看見的東西。
        """
        s = pollution.guard_split()
        assert s["open"] > 0, "正本登記簿是空的，上面那幾條都無聲成立"
        assert s["unguarded"] > 0, (
            "正本此刻每一筆都有守門。那是好事，但這一輪加的那一行"
            "就變成永遠印『全部有守門』—— 要改這條測試之前先確認"
            "那是真的，不是 guard_split 壞了")
        for pid in s["unguarded_ids"]:
            assert pollution.get(pid) is not None

    def test_正本的行文指名得出那幾筆(self):
        s = pollution.guard_split()
        if s["unguarded"] == 0:
            pytest.skip("正本此刻全部有守門")
        ctx = {"invalidated_conclusions": pollution.invalidated_conclusions()}
        txt = "\n".join(CT.invalidated_lines(ctx))
        assert s["unguarded_ids"][0] in txt


class Test唯一定義:
    """「有守門」的判斷式在 `pollution.py` 只准有一處。

    這一組是 2026-09-18 撞出來的，不是預防性假設。經過是：
    `guard_split()` 第一版把 `summary()` 那個判斷式照抄了兩次，
    於是 `r.get("regression_probe")` 在那個檔裡出現三次，而
    `tools/literal-restate-check.py:1212` 的條件 2 是「全 repo 出現
    超過一次就當成真的鍵名」。

    結果 `tests/test_literal_restate.py` 那條反向驗證**當場 0 命中** ——
    把鍵名打成 `regression_prope` 本來會被抓，重複之後就不會了。

    所以判斷式重複不只是難維護，它會關掉一個偵測器。
    """

    # 掃哪幾個檔。**這張清單 2026-09-18 從一個檔擴成兩個。**
    #
    # 加 `desktop_api.py` 不是預防性假設，是它當時真的有第二份：
    # `pollution_panel()` 第 2041 行自己抄了一份，而且多了 `.strip()`
    # —— 兩份語意不完全一樣，只是現有 21 筆剛好都測不出差別。
    #
    # 前一輪的「還缺什麼」寫的是「等真的出現第二份再決定要不要擴大」。
    # 出現了，所以擴大了。
    掃描範圍 = (
        ("apps", "forseti-cli", "pollution.py"),
        ("apps", "forseti-cli", "desktop_api.py"),
    )

    @staticmethod
    def _判斷式所在的函式(src: str) -> list[str]:
        """用 AST 找，不用文字計數 —— 文字計數會被 docstring 干擾。

        實測過：docstring 裡的引用讓文字計數變 2 而 AST 是 1。
        """
        import ast

        tree = ast.parse(src)
        owners = []
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.FunctionDef):
                continue
            for sub in ast.walk(fn):
                if not isinstance(sub, ast.Call):
                    continue
                f = sub.func
                if not (isinstance(f, ast.Attribute) and f.attr == "get"):
                    continue
                if not sub.args:
                    continue
                a0 = sub.args[0]
                if isinstance(a0, ast.Constant) and a0.value in (
                        "preventive_rule", "regression_probe"):
                    owners.append(fn.name)
                    break
        return owners

    def test_有守門的判斷式只有一處(self):
        owners = []
        for parts in self.掃描範圍:
            src = ROOT.joinpath(*parts).read_text(encoding="utf-8")
            owners += self._判斷式所在的函式(src)

        assert sorted(set(owners)) == ["has_guard"], (
            f"「有守門」的判斷式出現在 {sorted(set(owners))}。"
            "只准在 `has_guard()` 裡 —— 多一處就會讓 "
            "literal-restate 的條件 2 把打錯的鍵名當成真鍵名放過")

    def test_掃描範圍裡的檔案都要存在(self):
        """路徑是硬寫的，改名之後掃描範圍會安靜縮小。

        **縮小的方向是往綠的**（少掃一個檔等於少一個機會抓到重複），
        所以它不會自己冒出來。
        """
        for parts in self.掃描範圍:
            f = ROOT.joinpath(*parts)
            assert f.is_file(), f"掃描範圍指到不存在的檔：{f}"

    def test_掃描範圍涵蓋所有會讀登記簿的模組(self):
        """**這一條防的是「第三份出現在沒被掃的檔裡」。**

        做法是反過來問：repo 裡還有哪個 .py 提到那兩個鍵名，
        而它不在掃描範圍裡。提到不等於判斷，所以命中的要嘛進
        掃描範圍，要嘛在這裡具名豁免並附理由。
        """
        掃到的 = {ROOT.joinpath(*p) for p in self.掃描範圍}
        豁免 = {
            # 產種子資料的，用的是關鍵字參數不是 `.get()`
            ROOT / "tools" / "seed_pollution.py",
            # 掃描器自己的說明文字裡引用了這兩個名字
            ROOT / "tools" / "declared-only-check.py",
        }
        漏掉的 = []
        for f in sorted(ROOT.rglob("*.py")):
            if f in 掃到的 or f in 豁免:
                continue
            if any(x in f.parts for x in ("tests", ".git", "node_modules")):
                continue
            src = f.read_text(encoding="utf-8", errors="replace")
            if "preventive_rule" not in src and "regression_probe" not in src:
                continue
            if self._判斷式所在的函式(src):
                漏掉的.append(str(f.relative_to(ROOT)))

        assert 漏掉的 == [], (
            f"這幾個檔裡有「有守門」的判斷式，而它們不在掃描範圍裡："
            f"{漏掉的}。要嘛改叫 `pollution.has_guard()`，"
            "要嘛加進 `掃描範圍` 讓上面那一條看得到")

    def test_真值表四種組合(self):
        assert pollution.has_guard({"regression_probe": "t.py"}) is True
        assert pollution.has_guard({"preventive_rule": "守門"}) is True
        assert pollution.has_guard({"preventive_rule": "守門",
                                     "regression_probe": "t.py"}) is True
        assert pollution.has_guard({}) is False
        assert pollution.has_guard({"preventive_rule": "",
                                     "regression_probe": ""}) is False

    def test_summary與guard_split共用同一個定義(self, log):
        """沒有 RESOLVED 的時候兩邊的 guarded 必須相等。

        相等不是因為分母一樣就好 —— 是因為判斷式是同一個。
        哪天有人在其中一邊加條件而另一邊沒加，這一條會紅。
        """
        一筆(log, "甲", regression_probe="tests/test_a.py")
        一筆(log, "乙", preventive_rule="部署前守門")
        一筆(log, "丙")
        assert pollution.summary(log)["guarded"] == \
            pollution.guard_split(log)["guarded"]
