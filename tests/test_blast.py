"""Blast Radius（§16.1）。M4 精確定義見五機制文件第 6 節。

**這組測試防的是一個會說謊的 blast radius。** 五機制文件第 6.4 節原話：

    一個會說謊的 blast radius 比沒有 blast radius 危險得多。
    一旦它騙過她一次，整個介面就變裝飾品。

所以這裡每一條問的都是：**這個數字有沒有在假裝它知道它其實不知道的事。**

四個最容易說謊的地方，各有一條測試釘住：

    一，`uncovered_d1` 在沒有 lcov 時必須是 None，不是 0
    二，`live_conflicts` 的 0 必須標明是「沒有資料來源」而不是「沒有衝突」
    三，標準庫不可以被算成「未解析」（第一版就是這樣，解析率假摔到 0.184）
    四，`is_lower_bound` 恆為 true

還有一條防的是別的東西：**兩份實作漂移。** 演算法在 `src/cost.js`，
這裡只餵資料。`test_跟cost_js算出來的一致` 用同一組輸入兩邊各算一次，
比對五個維度。哪天有人在 Python 這邊「順手」重寫了演算法，那條會紅。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import blast as B  # noqa: E402


def mkrepo(tmp_path: Path, files: dict) -> Path:
    """建一個假 repo。key 是相對路徑，value 是檔案內容。"""
    for rel, body in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------- 圖的正確性

def test_專案內import成為邊(tmp_path):
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "import b\n",
        "apps/forseti-cli/b.py": "x = 1\n",
    })
    g = B.collect(r)
    edges = [e for e in g["imports"] if e["to"]]
    assert edges == [{"from": "apps/forseti-cli/a.py",
                      "to": "apps/forseti-cli/b.py", "specifier": "b",
                      "kind": "STATIC"}]


def test_標準庫不進圖也不算未解析(tmp_path):
    """第一版的 bug：`json` 被算成未解析，解析率假摔到 0.184。

    那個數字看起來像「這張圖有八成漏抓」，但專案內依賴圖裡
    根本沒有 `json` 這個節點。三類分開之後才問得出真正的問題：
    **我漏抓了多少應該有的邊。**
    """
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "import json\nimport time\nfrom pathlib import Path\n",
    })
    g = B.collect(r)
    assert [e for e in g["imports"] if e["to"] is None] == [], "標準庫不是未解析"
    assert [e for e in g["imports"] if e["to"]] == [], "標準庫不該進圖"
    specs = sorted(x["specifier"] for x in g["external"])
    assert specs == ["json", "pathlib", "time"]
    assert all(x["stdlib"] for x in g["external"]), "這三個都該被認出是標準庫"


def test_標準庫清單不是空的():
    """`_stdlib_names()` 壞掉會靜默把每個標準庫都當成第三方。

    這台是 3.9.6，`sys.stdlib_module_names` 不存在（3.10 才有），
    第一版就是直接讀它 AttributeError。退回 sysconfig 那條路
    要是哪天也壞了，沒有這條測試就只會看到「第三方套件突然變 200 個」。
    """
    assert len(B.STDLIB) > 50, f"標準庫只認出 {len(B.STDLIB)} 個，判定壞了"
    for m in ("json", "time", "pathlib", "subprocess", "ast", "__future__"):
        assert m in B.STDLIB, f"{m} 該是標準庫"


def test_相對import是真的未解析(tmp_path):
    """這一類才是誠實條款二要可查的東西。"""
    r = mkrepo(tmp_path, {"apps/forseti-cli/a.py": "from . import b\n"})
    g = B.collect(r)
    un = [e for e in g["imports"] if e["to"] is None]
    assert len(un) == 1 and un[0]["specifier"] == "."


def test_自己import自己不進圖(tmp_path):
    r = mkrepo(tmp_path, {"apps/forseti-cli/a.py": "import a\n"})
    assert [e for e in B.collect(r)["imports"] if e["to"]] == []


def test_跨語言斷點被記錄但不連邊(tmp_path):
    """誠實條款三：跨語言邊界標成斷點，不假裝連得起來。"""
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": 'RUN = "import(`${srcDir}/cost.js`)"\n',
    })
    g = B.collect(r)
    assert [e for e in g["imports"] if e["to"]] == [], "JS 不該變成 Python 的邊"
    assert any(b["js"] == "cost.js" for b in g["cross_language"])


def test_docstring裡提到js不算斷點(tmp_path):
    """第一版沒跳過 docstring，於是 `blast.py` 自己的說明文字
    「路徑第一段目錄（cost.js 的預設」被算成一個跨語言斷點。
    正本因此虛報 28 個，真實只有 13 個。

    **一個虛報的斷點數跟一個虛報的 blast radius 是同一種病** ——
    它讓人以為系統知道一件它其實不知道的事。
    """
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": '"""說明裡提到 cost.js 而已。"""\nx = 1\n',
        "apps/forseti-cli/b.py": 'RUN = "await import(`${d}/real.js`)"\n',
    })
    g = B.collect(r)
    names = {b["js"] for b in g["cross_language"]}
    assert names == {"real.js"}, f"docstring 不該進來，實際 {names}"


def test_檔名不會被啃掉開頭(tmp_path):
    """第一版用 `lstrip("${srcDir}/")`，那是逐字元剝除不是剝前綴，
    於是 `cost.js` 變成 `ost.js`、`intervention.js` 變成 `ntervention.js`。
    """
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py":
            'A = "`${srcDir}/cost.js`"\nB = "`${srcDir}/intervention.js`"\n',
    })
    names = {b["js"] for b in B.collect(r)["cross_language"]}
    assert names == {"cost.js", "intervention.js"}, names


def test_假repo也能跑(tmp_path):
    """`_rel()` 第一版寫死 REPO 常數，傳 root 會 ValueError。"""
    r = mkrepo(tmp_path, {"apps/forseti-cli/a.py": "x = 1\n"})
    assert B.collect(r)["files"] == ["apps/forseti-cli/a.py"]


# ------------------------------------------------------------ 誠實條款（6.4）

@pytest.fixture(scope="module")
def real():
    v = B.vectors()
    if not v.get("has"):
        pytest.skip(f"node 跑不起來：{v.get('why')}")
    return v


def test_沒有lcov時uncovered是None不是0(real):
    """誠實條款四。0 的意思是「查過，沒有未覆蓋的」，
    而真相是「根本沒查過」。這兩件事在畫面上長得一樣，所以要分開。"""
    assert real["coverage_source"] == "NONE"
    for t in real["top"]:
        assert t["vector"]["uncovered_d1"] is None
        assert t["vector"]["coverage_source"] == "NONE"


def test_live_conflicts的0要標明是沒有資料源(real):
    """優先序最高的指標，資料來源是 M3 的 WriteScope。

    Python 這條線沒有執行中的 WriteScope，`cost.js` 對空集合回 0。
    **0 在畫面上看起來像「沒有衝突」。** 所以必須另外帶一個來源欄位，
    不然這個介面第一次騙人就是在這裡。
    """
    assert real["live_conflicts_source"] == "NONE"
    assert "沒有資料" in real["live_why"]


def test_永遠是下界(real):
    """誠實條款一。動態 import、反射、字串拼路徑，靜態分析抓不到。"""
    assert real["is_lower_bound"] is True
    for t in real["top"]:
        assert t["vector"]["is_lower_bound"] is True


def test_不合成單一分數(real):
    """第 6.8 節雷一。合成會把可行動的維度壓平成不可行動的一個數字。"""
    for t in real["top"]:
        keys = set(t["vector"])
        assert "score" not in keys and "risk" not in keys
        assert {"d1_count", "d2_count", "uncovered_d1",
                "cross_modules", "live_conflicts"} <= keys


def test_模組劃分規則要標明(real):
    """`cross_modules` 用的是 cost.js 的預設（路徑第一段目錄），
    不是這個專案真正的子系統劃分。規格沒定義，所以不自己編，但要說。"""
    assert "cost.js" in real["module_rule"]


# ----------------------------------------------------------- 不要長出第二套

def test_跟cost_js算出來的一致(tmp_path):
    """**這條是防漂移的。**

    演算法在 `src/cost.js`，Python 這邊只負責餵資料。
    哪天有人在 Python 這邊「順手」重寫一份反向可達，
    兩份實作就會在某個邊界條件上分歧，而分歧的那天沒有人會發現。

    這裡拿同一組 import 直接呼叫 `cost.js`，跟 `B.vectors()` 比對。
    """
    files = {
        "apps/forseti-cli/hub.py": "x = 1\n",
        "apps/forseti-cli/a.py": "import hub\n",
        "apps/forseti-cli/b.py": "import hub\n",
        "tools/c.py": "import a\n",
    }
    r = mkrepo(tmp_path, files)
    (r / "src").mkdir(exist_ok=True)
    (r / "src" / "cost.js").write_text(
        (ROOT / "src" / "cost.js").read_text(encoding="utf-8"), encoding="utf-8")

    got = B.vectors(targets=["apps/forseti-cli/hub.py"], root=r)
    if not got.get("has"):
        pytest.skip(f"node 跑不起來：{got.get('why')}")
    mine = got["top"][0]["vector"]

    g = B.collect(r)
    runner = r / "direct.mjs"
    runner.write_text(
        "import { readFileSync } from 'node:fs';\n"
        "const p = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
        f"const m = await import('{(r / 'src' / 'cost.js').as_posix()}');\n"
        "const gr = m.buildGraph(p.imports);\n"
        "console.log(JSON.stringify(m.computeCostVector(gr, p.t, {})));\n",
        encoding="utf-8")
    import json as _j
    pay = r / "p.json"
    pay.write_text(_j.dumps({"imports": g["imports"],
                             "t": "apps/forseti-cli/hub.py"}), encoding="utf-8")
    n = B._node_bin()
    out = subprocess.run([n, str(runner), str(pay)],
                         capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    theirs = _j.loads(out.stdout)
    assert mine == theirs, "Python 那邊一定是重寫了演算法"


def test_反向可達分得出一階與二階(tmp_path):
    """hub 被 a、b 直接 import；c import a，所以 c 是二階。"""
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/hub.py": "x = 1\n",
        "apps/forseti-cli/a.py": "import hub\n",
        "apps/forseti-cli/b.py": "import hub\n",
        "tools/c.py": "import a\n",
    })
    (r / "src").mkdir(exist_ok=True)
    (r / "src" / "cost.js").write_text(
        (ROOT / "src" / "cost.js").read_text(encoding="utf-8"), encoding="utf-8")
    got = B.vectors(targets=["apps/forseti-cli/hub.py"], root=r)
    if not got.get("has"):
        pytest.skip(f"node 跑不起來：{got.get('why')}")
    v = got["top"][0]["vector"]
    assert v["d1_count"] == 2, "a 與 b 是一階"
    assert v["d2_count"] == 1, "c 經過 a 才到 hub，是二階"
    assert v["cross_modules"] == 2, "波及 apps 與 tools"


def test_node不在就說清楚不靜默回空(tmp_path, monkeypatch):
    """ADR-009 零依賴。node 不在要回 has=False 加理由，不是回一個空殼。"""
    r = mkrepo(tmp_path, {"apps/forseti-cli/a.py": "x = 1\n"})
    monkeypatch.setattr(B, "_node_bin", lambda: None)
    out = B.vectors(root=r)
    assert out["has"] is False and "node" in out["why"]


# ------------------------------------------------ detail()：誰依賴它，不只是幾個
#
# 排行榜回答「這個檔會波及 10 個」，detail() 回答「是哪 10 個」。
# 這一組防的東西跟上面同一個：**一份會說謊的名單。**
# 最容易說謊的三個地方各有一條：
#
#   一，打錯的路徑不可以看起來像「沒有人依賴它」（known=False，不是空清單）
#   二，任務與 session 兩種依賴沒有資料來源，要回 None 不是 []
#   三，名單的長度必須跟 vectors() 算出來的數字一致（兩邊不准分歧）


def _with_cost_js(r: Path) -> Path:
    """把真的 cost.js 複製進假 repo。演算法只有一份，測試也用同一份。"""
    (r / "src").mkdir(exist_ok=True)
    (r / "src" / "cost.js").write_text(
        (ROOT / "src" / "cost.js").read_text(encoding="utf-8"), encoding="utf-8")
    return r


def test_detail列出名單不只是數字(tmp_path):
    r = _with_cost_js(mkrepo(tmp_path, {
        "apps/forseti-cli/hub.py": "x = 1\n",
        "apps/forseti-cli/a.py": "import hub\n",
        "apps/forseti-cli/b.py": "import hub\n",
        "tools/c.py": "import a\n",
    }))
    d = B.detail("apps/forseti-cli/hub.py", root=r)
    if not d.get("has"):
        pytest.skip(f"node 跑不起來：{d.get('why')}")
    assert d["d1"] == ["apps/forseti-cli/a.py", "apps/forseti-cli/b.py"]
    assert d["d2plus"] == ["tools/c.py"]
    assert d["depends_on"] == [], "hub 自己沒有 import 專案內的東西"


def test_detail的數字跟vectors的數字一致(tmp_path):
    """兩條路徑算同一件事，不准分歧。

    `vectors()` 走 `computeCostVector`，`detail()` 走 `reverseReachable`，
    兩支都在 `cost.js` 裡。哪天有人只改一邊，這條會紅。
    """
    r = _with_cost_js(mkrepo(tmp_path, {
        "apps/forseti-cli/hub.py": "x = 1\n",
        "apps/forseti-cli/a.py": "import hub\n",
        "apps/forseti-cli/b.py": "import hub\n",
        "tools/c.py": "import a\n",
        "tests/test_z.py": "import b\n",
    }))
    tgt = "apps/forseti-cli/hub.py"
    v = B.vectors(targets=[tgt], root=r)
    d = B.detail(tgt, root=r)
    if not v.get("has") or not d.get("has"):
        pytest.skip("node 跑不起來")
    vec = v["top"][0]["vector"]
    assert len(d["d1"]) == vec["d1_count"] == d["d1_count"]
    assert len(d["d2plus"]) == vec["d2_count"] == d["d2_count"]
    assert sum(n for _, n in d["modules"]) == vec["d1_count"] + vec["d2_count"]
    assert len(d["modules"]) == vec["cross_modules"], "模組歸屬也不准有第二套"


def test_不在圖裡的路徑不會假裝成沒有人依賴它(tmp_path):
    """**打錯的路徑跟一個安全的改動，在「d1 是空的」上長得一模一樣。**

    所以未知的節點必須回 known=False 加一句為什麼，
    不可以回一份空名單讓人讀成「改它不會影響任何東西」。
    """
    r = _with_cost_js(mkrepo(tmp_path, {"apps/forseti-cli/a.py": "x = 1\n"}))
    d = B.detail("apps/forseti-cli/typo.py", root=r)
    assert d["has"] is False
    assert d["known"] is False
    assert "typo.py" in d["why"]
    assert "d1" not in d, "沒有名單就不要給一個空名單"


def test_任務與session依賴是None不是空清單(tmp_path):
    """誠實條款。§16.1 問四種依賴，這一支只答得出檔案那一種。

    `ledger.py` 的 tasks/steps 沒有檔案路徑欄位，所以「哪些任務
    依賴這個檔」**沒有資料來源**。空清單在畫面上讀起來是
    「沒有任務依賴它」，那是一句沒有根據的話。
    """
    r = _with_cost_js(mkrepo(tmp_path, {"apps/forseti-cli/a.py": "x = 1\n"}))
    d = B.detail("apps/forseti-cli/a.py", root=r)
    if not d.get("has"):
        pytest.skip("node 跑不起來")
    assert d["tasks"] is None and d["sessions"] is None
    assert d["tasks_why"] and d["sessions_why"]
    assert d["live_conflicts_source"] == "NONE"
    assert d["coverage_source"] == "NONE"
    assert d["vector"]["uncovered_d1"] is None
    assert d["is_lower_bound"] is True


def test_detail認得方向相反的那一欄(tmp_path):
    """`depends_on` 是「我用了誰」，跟 d1 的「誰用了我」方向相反。

    兩欄放在同一張畫面上，最容易被讀反，所以方向說明是必填的。
    """
    r = _with_cost_js(mkrepo(tmp_path, {
        "apps/forseti-cli/hub.py": "x = 1\n",
        "apps/forseti-cli/mid.py": "import hub\n",
        "apps/forseti-cli/top.py": "import mid\n",
    }))
    d = B.detail("apps/forseti-cli/mid.py", root=r)
    if not d.get("has"):
        pytest.skip("node 跑不起來")
    assert d["d1"] == ["apps/forseti-cli/top.py"], "誰用了 mid"
    assert d["depends_on"] == ["apps/forseti-cli/hub.py"], "mid 用了誰"
    assert d["depends_on_note"], "方向說明不可以是空的"


def test_detail的外部import分得出標準庫與第三方(tmp_path):
    r = _with_cost_js(mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "import json\nimport pytest\n",
    }))
    d = B.detail("apps/forseti-cli/a.py", root=r)
    if not d.get("has"):
        pytest.skip("node 跑不起來")
    assert "json" in d["external"] and "pytest" in d["external"]
    assert d["external_third_party"] == ["pytest"], "json 是標準庫不是第三方"


def test_detail的空目標不會變成掃全圖(tmp_path):
    r = _with_cost_js(mkrepo(tmp_path, {"apps/forseti-cli/a.py": "x = 1\n"}))
    for bad in ("", "   "):
        d = B.detail(bad, root=r)
        assert d["has"] is False and "沒有指定" in d["why"]


def test_語法錯誤的檔不會讓整張圖炸掉(tmp_path):
    """先前 `imports_of` 的例外分支只回兩個值，呼叫端要三個。

    所以 repo 裡只要有一個語法錯誤的 .py（測試 fixture 最容易出現），
    `collect()` 會以 ValueError 整個炸掉，而訊息完全不提是哪個檔造成的。

    2026-09-16 元數從三變四（多了動態 import），這條跟著改 ——
    **這條測的是元數一致，不是元數等於三**，所以改的是數字不是意圖。
    """
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/good.py": "import bad\n",
        "apps/forseti-cli/bad.py": "def (:\n",
    })
    e, x, b, dy = B.imports_of(r / "apps/forseti-cli/bad.py", {}, r)
    assert (e, x, b, dy) == ([], [], [], []), "四個值，不是三個"
    g = B.collect(r)  # 這一行先前會 ValueError
    assert "apps/forseti-cli/bad.py" in g["files"], "壞檔仍然是圖上的節點"


# ------------------------------------------------ 排行榜以外的那 96 個檔的入口

def test_完整節點清單有帶出來而且是全部不是前八(tmp_path):
    """**排行榜 limit=8，但 `detail()` 對圖裡任何一個節點都算得出來。**

    先前畫面上沒有入口走到前 8 名以外的檔，缺的是入口不是後端能力。
    前端要做本地搜尋，得先拿得到完整清單，所以 `vectors()` 必須把
    `collect()` 已經算出來的那份節點清單帶出來，而且是**全部**。
    """
    files = {f"apps/forseti-cli/m{i}.py": "x = 1\n" for i in range(12)}
    r = _with_cost_js(mkrepo(tmp_path, files))
    v = B.vectors(root=r, limit=3)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    assert len(v["top"]) == 3, "排行榜仍然只有 limit 名"
    # 13 不是 12：`_with_cost_js` 放進去的那個 `src/cost.js` **本身也是
    # 圖上的節點**。2026-09-16 接上 JS 半邊之前它不是，因為當時只掃 .py。
    # 這個 +1 是行為改變不是誤差，改成 13 的同時要能說出那多的是哪一個。
    assert len(v["all_files"]) == 13, "清單是全部的節點，不是排行榜那幾個"
    assert "src/cost.js" in v["all_files"], "多出來的那一個是 JS 半邊的節點"
    assert v["py_files"] == 12 and v["js_files"] == 1, "兩半邊各自報得出來"
    assert v["all_files"] == sorted(v["all_files"]), "排序過，畫面才穩定"
    assert len(v["all_files"]) == v["files"], "清單長度必須等於它自己報的檔案數"
    assert v["files"] == v["py_files"] + v["js_files"], "總數是兩半邊相加"


def test_節點清單要講清楚搜尋範圍到哪裡(tmp_path):
    """**搜尋框找不到 `src/cost.js`，那不是它不存在。**

    這張圖只掃 SCAN_DIRS 底下的 .py。如果畫面上不講，
    使用者搜尋 `.js` 一無所獲時會讀成「沒有東西依賴它」——
    跟 `detail()` 對未知路徑回 known=False 防的是同一件事。
    """
    r = _with_cost_js(mkrepo(tmp_path, {"apps/forseti-cli/a.py": "x = 1\n"}))
    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    why = v["all_files_why"]
    assert why, "清單不可以沒有範圍說明"
    for d in B.SCAN_DIRS:
        assert d in why, f"範圍說明要指名掃了哪些目錄，缺 {d}"


def test_節點清單裡的路徑真的送得進detail(tmp_path):
    """清單跟明細是同一套路徑格式，不然搜尋結果點下去會全部 known=False。

    這一條釘的是兩邊的**格式**一致，不只是兩邊都存在。
    """
    r = _with_cost_js(mkrepo(tmp_path, {
        "apps/forseti-cli/hub.py": "x = 1\n",
        "tools/c.py": "import hub\n",
    }))
    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    for f in v["all_files"]:
        d = B.detail(f, root=r)
        assert d.get("known") is True, f"清單給的 {f} 在 detail 裡卻是未知路徑"


# ------------------------------------------------- JS 半邊（2026-09-16 接上）
#
# 在這一天之前這張圖只有 .py，所以 `src/cost.js`（它自己就是算這張圖的
# 那份演算法）搜尋不到、點不開。缺的不是解析器 —— `src/imports.js`（M11）
# 從第一天就寫好了，它的檔頭自己寫著「不讀檔案系統，宿主把檔名 → 原始碼
# 餵進來」。缺的一直是那個宿主。下面這些釘住的就是那條線接上了沒有。


def _with_js_stack(r: Path) -> Path:
    """把 cost.js 跟 imports.js 兩份都複製進假 repo。

    `_with_cost_js` 只放 cost.js，那樣 `jsHalf()` 會走「載不進
    imports.js」那條分支，JS 邊永遠是 0 —— 對舊測試無所謂，
    對這一組就等於什麼都沒測到。
    """
    (r / "src").mkdir(exist_ok=True)
    for name in ("cost.js", "imports.js"):
        (r / "src" / name).write_text(
            (ROOT / "src" / name).read_text(encoding="utf-8"), encoding="utf-8")
    return r


def test_js的import變成真的邊(tmp_path):
    """最基本的一條：a.js import b.js，圖上要有那條邊。"""
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "import { x } from './b.js';\n",
        "src/b.js": "export const x = 1;\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    assert v["js_edges"] >= 1, "a.js → b.js 那條邊沒被解析出來"

    # **上面那一條不夠。** `js_edges` 報的是「解析出幾條邊」，
    # 不是「那些邊進了圖」。反向驗證當場抓到：把 `_RUNNER` 的
    # `...js.edges` 拿掉（邊解析得出來但不合併進圖），上面那條照樣綠。
    # 所以要斷言在**圖算出來的結果**上，而且兩個 runner 各打一次
    # —— 它們是兩份獨立的 node 程式碼，改一邊不會讓另一邊跟著錯。
    got = {t["target"]: t["vector"]["d1_count"] for t in v["top"]}
    assert got.get("src/b.js") == 1, \
        "_RUNNER 建的圖裡沒有那條邊（b.js 應該被 a.js 依賴）"

    d = B.detail("src/b.js", root=r)
    assert d["known"] is True, "JS 檔要在圖裡"
    assert "src/a.js" in d["d1"], "誰依賴 b.js 這個問題要答得出 a.js"
    assert d["d1_count"] == got["src/b.js"], \
        "_DETAIL_RUNNER 跟 _RUNNER 建的必須是同一張圖"


def test_打錯的js路徑不會被當成沒人依賴(tmp_path):
    """跟 .py 那邊同一條誠實條款，不因為換了副檔名就放寬。"""
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "export const x = 1;\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    d = B.detail("src/nope.js", root=r)
    assert d.get("known") is False, "不存在的節點不准回 known"
    assert "d1" not in d, "不准回一份空名單，那讀起來像改它很安全"
    assert "JS" in d["why"], "要講清楚 JS 的掃描範圍在哪"


def test_node內建模組不進圖也不算未解析(tmp_path):
    """**這一條釘的是一個會假摔的數字。**

    實測：把 EXTERNAL 一起餵進 `buildGraph()`，`cost.js` 的
    `resolutionRate()` 從 0.971 掉到 0.541，因為它把 to=null 一律算成
    未解析。那個 0.54 讀起來是「這張圖漏抓四成六」，而那四成六全是
    `node:fs` 這種內建模組，本來就不該是圖上的節點。

    跟 `imports_of()` 檔頭記載的 Python 第一版 0.184 事件是同一種病，
    所以兩邊要有各自的回歸測試。
    """
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "import { readFileSync } from 'node:fs';\n"
                    "import path from 'node:path';\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    assert v["resolution_rate"] == 1.0, \
        "內建模組被算成未解析了，解析率會假摔"
    assert v["js_edges"] == 0, "node:fs 不該變成圖上的一條邊"


def test_js目標的外部import不是空的(tmp_path):
    """點開一個 .js，它用了哪些外部模組要看得到。

    這一段只有 node 那端知道（`g["external"]` 是 Python 半邊掃的），
    漏接的話畫面上會是一片空白，而空白讀起來是「它沒有用任何外部模組」。
    """
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "import { readFileSync } from 'node:fs';\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    d = B.detail("src/a.js", root=r)
    if not d.get("has"):
        pytest.skip("node 跑不起來")
    assert "node:fs" in d["external"], "JS 目標的外部 import 沒接出來"


def test_兩半邊的解析方法要標明不一樣(tmp_path):
    """.py 走 ast，.js 走正則。不標等於讓人以為整張圖同一種品質。"""
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "export const x = 1;\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    assert "ast" in v["parser_py"], "Python 半邊用什麼解析要講"
    assert "正規表示式" in v["parser_js"], "JS 半邊用什麼解析要講"
    assert v["is_lower_bound"] is True


def test_節點清單的範圍說明要含JS(tmp_path):
    """先前那句寫著「src/ 的 .js 不在圖裡」。接上之後那句話是**假的**。"""
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "export const x = 1;\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    why = v["all_files_why"]
    assert "src" in why and "JS" in why, "範圍說明要講得出 JS 掃哪裡"
    assert "不在圖裡" not in why.split("repo 裡其他檔")[0], \
        "不准還留著「.js 不在圖裡」那句已經成假的話"


def test_node_modules不進圖(tmp_path):
    """它不是這個專案的原始碼。"""
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "export const x = 1;\n",
        "src/node_modules/dep/index.js": "module.exports = 1;\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    assert not any("node_modules" in f for f in B.js_files(r)), \
        "node_modules 底下的檔混進圖裡了"


# ------------------------------------------------------------------ 磁碟快取
#
# 記憶體快取在這裡沒有用：畫面每 2 秒呼叫 strands，而每一次都是
# Rust 起的**全新 python3 程序**，module-level 的 dict 每次都是空的。


def test_快取命中要標明自己是快取(tmp_path):
    """一個舊數字看起來跟一個新數字一模一樣。不標就是讓人以為它是剛算的。"""
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "export const x = 1;\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    first = B.vectors(root=r)
    if not first.get("has"):
        pytest.skip("node 跑不起來")
    assert first["cached"] is False, "第一次是真的算出來的"
    second = B.vectors(root=r)
    assert second["cached"] is True, "第二次該命中快取"
    assert second["files"] == first["files"], "數字不准因為走快取而不一樣"
    assert second["edges"] == first["edges"]


def test_改了檔案快取要自己失效(tmp_path):
    """**失效靠指紋不靠時間。**

    用時間當有效期會有一個很難查的症狀：改完程式碼畫面不動，
    而且不會有任何錯誤訊息。
    """
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "export const x = 1;\n",
        "src/b.js": "export const y = 1;\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    first = B.vectors(root=r)
    if not first.get("has"):
        pytest.skip("node 跑不起來")
    assert first["js_edges"] == 0
    # 加一條真的邊進去
    (r / "src" / "a.js").write_text("import './b.js';\nexport const x = 1;\n",
                                    encoding="utf-8")
    again = B.vectors(root=r)
    assert again["cached"] is False, "檔案改了還命中快取，那是最難查的那種 bug"
    assert again["js_edges"] == 1, "新的邊要算得出來"


def test_快取寫不進去也不能讓功能壞掉(tmp_path, monkeypatch):
    """快取是加速，不是依賴。寫失敗要照樣回得出結果。

    **第一版的這條測試是壞的。** 它 monkeypatch 掉 `_cache_put` 讓它
    拋錯，再斷言 `vectors()` 跟著拋錯 —— 那測的是 monkeypatch 有效，
    不是真實行為，而且它斷言的還是**錯的**行為。
    這一版打的是真的：把快取檔的位置換成一個建不出來的路徑
    （拿一個檔案當目錄用），走真正的 OSError 分支。
    """
    r = _with_js_stack(mkrepo(tmp_path, {
        "src/a.js": "export const x = 1;\n",
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    blocker = tmp_path / "blocker"
    blocker.write_text("我是檔案不是目錄", encoding="utf-8")
    monkeypatch.setattr(B, "_cache_file",
                        lambda base: blocker / "cache" / "blast.json")

    # 寫不進去不准拋出來
    B._cache_put(r, "k", "fp", {"x": 1})
    assert B._cache_get(r, "k", "fp") is None, "寫不進去就不該讀得到"

    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    assert v["has"] is True, "快取壞掉不准讓功能跟著壞"
    assert v["cached"] is False, "寫不進去就每次都是重算，不准謊報命中"


def test_指紋算不出來就不准用快取(tmp_path):
    """**回 None 不是回一個編出來的指紋。**

    一個編出來的指紋會讓快取永遠命中，那比沒有快取糟得多。
    """
    r = _with_js_stack(mkrepo(tmp_path, {
        "apps/forseti-cli/m.py": "x = 1\n",
    }))
    missing = [r / "apps" / "forseti-cli" / "沒有這個檔.py"]
    assert B._fingerprint(r, missing, []) is None, \
        "stat 不到的檔要讓指紋算不出來，不是跳過它"
    assert B._cache_get(r, "k", "") is None, "沒有指紋就不准命中"


# ------------------------------------------- 延後 import 與這張圖已知的盲點
#
# 2026-09-16 補。`ast.Import` / `ast.ImportFrom` 看不到
# `importlib.import_module("worker")`，而這個專案用它打破循環依賴，
# 所以那些邊先前**整張圖上一條都沒有**。
#
# 低報比高報危險：一個少算的 blast radius 讀起來像
# 「改這個檔影響範圍比較小」。


def test_延後import的字面參數要進圖(tmp_path):
    """`importlib.import_module("b")` 解得出來，所以它是一條真的邊。"""
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "import importlib\n"
                                 "def get():\n"
                                 "    return importlib.import_module('b')\n",
        "apps/forseti-cli/b.py": "x = 1\n",
    })
    edges = [e for e in B.collect(r)["imports"] if e["to"]]
    assert edges == [{"from": "apps/forseti-cli/a.py",
                      "to": "apps/forseti-cli/b.py", "specifier": "b",
                      "kind": "DEFERRED"}], \
        "延後 import 沒有變成邊，或是沒有標成 DEFERRED"


def test___import__也算延後import(tmp_path):
    """兩種寫法都要認得，不是只認 importlib 那一種。"""
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "def get():\n    return __import__('b')\n",
        "apps/forseti-cli/b.py": "x = 1\n",
    })
    kinds = {e["to"]: e["kind"] for e in B.collect(r)["imports"] if e["to"]}
    assert kinds == {"apps/forseti-cli/b.py": "DEFERRED"}


def test_非字面的動態import只計數不猜它指到哪(tmp_path):
    """§8.3 的禁止填空。**看到了要記一筆，但不准編一個目標出來。**"""
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "import importlib\n"
                                 "def get(name):\n"
                                 "    return importlib.import_module(name)\n",
        "apps/forseti-cli/b.py": "x = 1\n",
    })
    g = B.collect(r)
    assert [e for e in g["imports"] if e["to"]] == [], \
        "路徑是變數，不准猜出一條邊來"
    assert len(g["dynamic_opaque"]) == 1, "看到了就要記一筆，不准當作沒看到"
    assert g["dynamic_opaque"][0]["from"] == "apps/forseti-cli/a.py"
    assert g["dynamic_opaque"][0]["line"] == 3, "要指得回原始碼第幾行"


def test_延後import到標準庫不進圖但可查(tmp_path):
    """跟靜態 import 同一條規則，不因為它是延後的就放寬。"""
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "import importlib\n"
                                 "m = importlib.import_module('json')\n",
    })
    g = B.collect(r)
    assert [e for e in g["imports"] if e["to"]] == [], "標準庫不是圖上的節點"
    ext = [x for x in g["external"] if x["specifier"] == "json"]
    assert len(ext) == 1 and ext[0]["stdlib"] is True
    assert ext[0]["kind"] == "DEFERRED", "外部那筆也要標得出它是延後的"


def test_正本裡ledger對那四個模組的依賴真的在圖上():
    """**這一條釘的是真實的正本，不是一個假 repo。**

    `ledger.py` 靠 `importlib.import_module("worker")` 這種寫法
    依賴 worker / starvation / continuity / watchdog，
    而 2026-09-16 之前這四條邊整張圖上一條都沒有。

    哪天有人把延後 import 的解析拿掉，這一條會紅。
    """
    g = B.collect()
    got = {e["to"] for e in g["imports"]
           if e["from"] == "apps/forseti-cli/ledger.py" and e["to"]}
    for name in ("worker", "starvation", "continuity", "watchdog"):
        assert f"apps/forseti-cli/{name}.py" in got, \
            f"ledger.py 對 {name} 的延後依賴不在圖上"


def test_盲點數字兩半邊分開報(tmp_path):
    """**JS 半邊沒算成的時候要回 None，不是 0。**

    0 讀起來是「JS 那半邊沒有盲點」，而真相是「沒有資料」。
    這跟 `live_conflicts` 的 0 是同一條誠實條款。
    """
    # 只放 cost.js，不放 imports.js → `jsHalf()` 走「載不進」那條分支。
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "import importlib\n"
                                 "def g(n):\n"
                                 "    return importlib.import_module(n)\n",
    })
    (r / "src").mkdir(exist_ok=True)
    (r / "src" / "cost.js").write_text(
        (ROOT / "src" / "cost.js").read_text(encoding="utf-8"), encoding="utf-8")
    (r / "src" / "x.js").write_text("export const x = 1;\n", encoding="utf-8")
    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    assert v["js_dynamic_opaque"] is None, \
        "JS 半邊沒算成，這裡要是 None 不是 0"
    assert v["py_dynamic_opaque"] == 1, "Python 這半邊算得出來"


def test_js半邊的盲點帶得出是哪個檔第幾行():
    """**一個總數說得出有幾個盲點，說不出該去看哪裡。**

    Python 這半邊從一開始就帶 `from` 與 `line`，JS 那半邊
    先前只有一個總數。這一條釘的是兩半邊形狀一樣。
    """
    v = B.vectors()
    if not v.get("has"):
        pytest.skip(f"node 跑不起來：{v.get('why')}")
    w = v.get("js_dynamic_where")
    assert w is not None, "JS 半邊算成了，位置就不該是 None"
    assert w, "正本裡 hooks 那幾支用 await import(join(...))，不可能一筆都沒有"
    for x in w:
        assert set(x) == {"from", "line", "call"}, \
            f"形狀要跟 Python 那半邊一樣：{x}"
        assert isinstance(x["line"], int) and x["line"] >= 1, \
            f"行號要是 1 起算的正整數：{x}"
        assert x["call"] in ("import", "require")


def test_js盲點的行號真的指得到那一行():
    """**一個錯的行號比沒有行號糟。**

    沒有行號的人會自己去找；拿到錯行號的人會走到那一行，
    看到不相干的程式碼，然後認定這個工具在亂報。
    """
    v = B.vectors()
    if not v.get("has"):
        pytest.skip(f"node 跑不起來：{v.get('why')}")
    w = v.get("js_dynamic_where") or []
    assert w, "沒有樣本可驗"
    checked = 0
    for x in w:
        f = ROOT / x["from"]
        if not f.exists():
            continue
        lines = f.read_text(encoding="utf-8").splitlines()
        assert 1 <= x["line"] <= len(lines), f"行號超出檔案長度：{x}"
        src = lines[x["line"] - 1]
        assert re.search(rf"\b{x['call']}\s*\(", src), \
            f"{x['from']}:{x['line']} 那一行沒有 {x['call']}( ：{src!r}"
        checked += 1
    assert checked >= 3, "至少要驗到三筆真實位置"


def test_js半邊沒算成時位置是None不是空清單(tmp_path):
    """空清單讀起來是「JS 那邊沒有盲點」，跟 `js_dynamic_opaque`
    的 0 是同一種病。"""
    r = mkrepo(tmp_path, {
        "apps/forseti-cli/a.py": "import os\n",
    })
    (r / "src").mkdir(exist_ok=True)
    (r / "src" / "cost.js").write_text(
        (ROOT / "src" / "cost.js").read_text(encoding="utf-8"), encoding="utf-8")
    (r / "src" / "x.js").write_text("export const x = 1;\n", encoding="utf-8")
    v = B.vectors(root=r)
    if not v.get("has"):
        pytest.skip("node 跑不起來")
    assert v["js_dynamic_where"] is None, \
        "JS 半邊沒算成，位置要是 None 不是 []"


def test_js盲點位置的筆數跟總數對得起來():
    """畫面上會寫「另外 N 筆沒有列出來」，那個 N 是總數減列出來的筆數。
    位置被截斷到 20 筆，所以總數只能大於等於列出來的筆數。"""
    v = B.vectors()
    if not v.get("has"):
        pytest.skip(f"node 跑不起來：{v.get('why')}")
    w = v.get("js_dynamic_where") or []
    assert len(w) <= 20, "位置清單要截斷，不然一個大 repo 會把畫面灌爆"
    assert v["js_dynamic_opaque"] >= len(w), \
        "總數不可能小於列出來的筆數"


def test_正本的盲點數字跟兩份解析器各自算的一致():
    """畫面上那兩個數字要指得回來源，不是我在 `vectors()` 裡填的。"""
    v = B.vectors()
    if not v.get("has"):
        pytest.skip(f"node 跑不起來：{v.get('why')}")
    g = B.collect()
    assert v["py_dynamic_opaque"] == len(g["dynamic_opaque"]), \
        "Python 那個數字要等於 collect() 實際記到的筆數"
    stats = v.get("js_stats") or {}
    assert v["js_dynamic_opaque"] == stats.get("dynamic_opaque"), \
        "JS 那個數字要等於 src/imports.js 自己算的，不是另外一份"
    assert v["py_deferred_edges"] == len(
        [e for e in g["imports"] if e.get("kind") == "DEFERRED" and e["to"]])


# ------------------------------------------------- collect 的磁碟快取（21:5x）

def _repo_cache(monkeypatch, tmp_path: Path, files: dict) -> Path:
    """建一個假 repo 並把它當成正本，這樣 collect 才會走快取那條路。

    不搬 `B.REPO` 的話快取會寫到真正的 repo 裡，而且測試之間會互相污染。
    """
    r = mkrepo(tmp_path, files)
    monkeypatch.setattr(B, "REPO", r)
    return r


def test_正本的collect第二次是快取而且答案一模一樣(monkeypatch, tmp_path):
    r = _repo_cache(monkeypatch, tmp_path, {
        "apps/forseti-cli/a.py": "import b\n",
        "apps/forseti-cli/b.py": "x = 1\n",
    })
    first = B.collect(r)
    second = B.collect(r)
    assert first["cached"] is False
    assert second["cached"] is True
    # `cache_write` 冷熱本來就不一樣（冷的那次寫了檔，熱的那次沒寫），
    # 2026-09-17 加那一欄的時候這條紅過一次，紅得對。**不是放寬斷言**：
    # 下面緊接著把它該有的兩個值釘死，比先前只跳過 `cached` 嚴。
    skip = {"cached", "cache_write", "cache_write_why"}
    for k in first:
        if k in skip:
            continue
        assert first[k] == second[k], f"{k} 冷熱不一致"
    assert first["cache_write"] == B.CACHE_OK
    assert second["cache_write"] == B.CACHE_NOT_ATTEMPTED


def test_檔案動過快取就失效(monkeypatch, tmp_path):
    """**檔案集合刻意不變**，只有一個檔的內容與 mtime 變。

    第一版在這裡順手加了一個新檔，於是指紋因為「集合變了」而失效，
    這條測試就算把 mtime 與 size 從指紋裡拿掉照樣會綠 ——
    反向驗證第 1 次沒抓到，就是這個原因。
    一條永遠綠的測試比沒有測試糟，它讓人以為那條路有人守。
    """
    import os
    r = _repo_cache(monkeypatch, tmp_path, {
        "apps/forseti-cli/a.py": "x = 1\n",
        "apps/forseti-cli/b.py": "y = 2\n",
    })
    f = r / "apps" / "forseti-cli" / "a.py"
    os.utime(f, (1_000_000, 1_000_000))
    assert [e["to"] for e in B.collect(r)["imports"] if e["to"]] == []
    f.write_text("import b\n", encoding="utf-8")
    os.utime(f, (2_000_000, 2_000_000))
    g = B.collect(r)
    assert g["cached"] is False, "mtime 變了還命中"
    assert [e["to"] for e in g["imports"] if e["to"]] == ["apps/forseti-cli/b.py"]


def test_不是正本就不寫快取檔(tmp_path):
    # `B.REPO` 沒有被搬，所以這是「臨時 repo」那條路。
    r = mkrepo(tmp_path, {"apps/forseti-cli/a.py": "x = 1\n"})
    g = B.collect(r)
    assert g["fp"] is None
    assert g["cached"] is False
    assert not (r / ".forseti" / "cache" / "blast.json").exists()


def test_collect帶出來的指紋跟自己算的是同一個(monkeypatch, tmp_path):
    # `vectors()` / `summary()` 改用 `g["fp"]` 之後，這兩個值一分岔，
    # 快取就會在一個永遠不對的 key 上打轉而不會有錯誤訊息。
    r = _repo_cache(monkeypatch, tmp_path, {
        "apps/forseti-cli/a.py": "import b\n",
        "apps/forseti-cli/b.py": "x = 1\n",
    })
    g = B.collect(r)
    assert g["fp"] == B._fingerprint(r, B.python_files(r), g["js_files"])


def test_快取檔壞掉就重算不丟例外(monkeypatch, tmp_path):
    r = _repo_cache(monkeypatch, tmp_path, {"apps/forseti-cli/a.py": "x = 1\n"})
    B.collect(r)
    f = r / ".forseti" / "cache" / "blast.json"
    f.write_text("{壞掉的 json", encoding="utf-8")
    g = B.collect(r)
    assert g["cached"] is False
    assert g["files"] == ["apps/forseti-cli/a.py"]
