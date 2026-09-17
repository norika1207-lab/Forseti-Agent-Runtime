"""阻塞項怎麼被讀、怎麼被交接出去。

2026-09-16 18:5x 加。在這之前有兩件事同時成立：

一，`.forseti/NEXT.md` 一個 blocker 都看不到。那份檔案的
    「還沒解決的」來源是 blocked steps 與未讀文件，不是 `BLOCKERS.md`。
    所以「B-15 在等 owner 一句話」這件事，只讀交接檔的人不會知道 ——
    而交接檔正是停機之後唯一有人看的東西。

二，未解除的判定只看標題四個字。B-04 的標題從 09-16 就寫著「結案」，
    而那張表裡沒有那個詞，於是一條已經結案的阻塞繼續被算進未解除數。

這一組守的是分類規則本身，不是「此刻剛好有幾條」。
數字會變，規則不會 —— 把當時的資料狀態寫成結構要求，
是 `test_forseti_cli.py` 2026-09-10 真的踩過的坑。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import desktop_api as D  # noqa: E402
import handoff as H  # noqa: E402


FIX = """# BLOCKERS

規則：一條阻塞要寫清楚「擋住哪個具體交付」。

---

## B-91　還在擋的

**擋住：** 階段 7 的出口條件。

**原因：** 隨便。

## B-92　兩邊都說結束了（已解除）

**擋住：** 無。2026-01-01 實測解除。

## B-93　標題說結案，擋住欄還寫著東西（2026-01-02 結案）

**擋住：** 階段 1 與階段 4。

## B-94　擋住欄說擋不住，標題沒說

**擋住：** 目前擋不住任何東西。標準庫就夠。

## B-95　根本沒寫擋住什麼

**原因：** 有人忘了寫。

## B-96　擋住寫了兩行

**擋住：** 第一行講的東西，
第二行接著講完。

**原因：** 排版折行。
"""


def _by_id(rep: dict) -> dict:
    return {it["id"]: it for it in rep["open_items"]}


def test_每一節都抽得到編號跟擋住什麼():
    secs = D._blocker_sections(FIX)
    ids = [s["id"] for s in secs]
    assert ids == ["B-91", "B-92", "B-93", "B-94", "B-95", "B-96"]
    assert secs[0]["blocks"] == "階段 7 的出口條件。"


def test_擋住欄折行要接起來():
    """折行是排版，不是內容。接不起來的話後半句會靜靜消失。"""
    secs = D._blocker_sections(FIX)
    b96 = [s for s in secs if s["id"] == "B-96"][0]
    assert "第一行講的東西" in b96["blocks"]
    assert "第二行接著講完" in b96["blocks"]


def test_沒寫擋住什麼的回None不是空字串():
    """「沒有寫」跟「寫了無」是兩件事，後者才是宣告解除。

    併成一個的話，一條忘了填的阻塞會被當成已經解除。
    """
    secs = D._blocker_sections(FIX)
    b95 = [s for s in secs if s["id"] == "B-95"][0]
    assert b95["blocks"] is None


def test_兩個訊號都說結束才算結束():
    rep = D._blockers(FIX)
    assert "B-92" not in _by_id(rep), "標題與擋住欄都說結束，這條不該還算數"
    assert rep["closed"] == 1


def test_只有一邊說結束的不自動降級():
    """挑哪一邊是 owner 的決定，不是我的。

    B-93 標題寫結案、擋住欄還寫著階段 1 與階段 4；
    B-94 反過來。兩條都照樣算未解除，另外被記成打架。
    """
    rep = D._blockers(FIX)
    ids = _by_id(rep)
    assert "B-93" in ids and "B-94" in ids
    conf = {x["id"] for x in rep["conflicting"]}
    assert conf == {"B-93", "B-94"}
    assert ids["B-93"]["said_closed_by"] == "標題"
    assert ids["B-94"]["said_closed_by"] == "擋住欄"


def test_打架的數字不跟未解除數相減():
    """兩個數字回答的不是同一個問題，合成一個就沒得查了。"""
    rep = D._blockers(FIX)
    assert rep["open"] == 5
    assert len(rep["conflicting"]) == 2
    assert rep["open"] + rep["closed"] == rep["total"]


def test_沒寫擋住什麼的另外記下來():
    rep = D._blockers(FIX)
    assert rep["undeclared"] == ["B-95"]
    assert "B-95" in _by_id(rep), "沒有寫不等於沒有擋，不准自動降級"


def test_每一行都講得出擋住什麼():
    """一條說不出自己擋住什麼的阻塞就是待辦。BLOCKERS.md 第一條規則。"""
    rep = D._blockers(FIX)
    lines = D._blocker_lines(rep)
    got = [x for x in lines if x.startswith("- B-")]
    assert got, "有未解除的就要印得出來"
    for ln in got:
        assert "擋住：" in ln, f"這一行沒說擋住什麼：{ln}"


def test_沒寫擋住什麼的那一行要說它沒寫():
    lines = D._blocker_lines(D._blockers(FIX))
    hit = [x for x in lines if x.startswith("- B-95")]
    assert hit and "沒寫擋住什麼" in hit[0]


def test_還有幾條的分母是未解除總數不是被截短的清單():
    """用被截短的清單算，「還有幾條」永遠是 0，而那是一句假話。"""
    lines = D._blocker_lines(D._blockers(FIX), limit=2)
    tail = [x for x in lines if x.startswith("- 還有")]
    assert tail == ["- 還有 3 條沒列出來"]


def test_全部解除的時候不印空殼():
    """空的一節讀起來像「這裡沒東西」，其實是「這裡什麼都沒算」。"""
    rep = D._blockers("# BLOCKERS\n\n## B-99　好了（已解除）\n\n**擋住：** 無。\n")
    assert rep["open"] == 0
    assert D._blocker_lines(rep) == []


def test_交接檔有擋住的那一節():
    t = H.render({"goal": "G", "n": 1,
                  "blocker_lines": ["- B-15　擋住：部署守門納不進 JS 測試"]})
    assert "## 擋住的" in t
    assert "B-15" in t
    assert "BLOCKERS.md" in t


def test_沒有阻塞行的時候交接檔不長出那一節():
    t = H.render({"goal": "G", "n": 1})
    assert "## 擋住的" not in t


def test_真實檔案解析得動():
    """只驗結構，不驗此刻有幾條 —— 數字會變，規則不會。"""
    rep = D._blockers()
    assert rep["total"] > 0
    assert rep["open"] + rep["closed"] == rep["total"]
    for it in rep["open_items"]:
        assert it["id"].startswith("B-")
        assert it["title"]


def test_截斷要看得出來是截斷():
    """實測第一版把 B-15 切在「要把 `npm tes」，讀起來像檔案壞了。

    一個沒有標記的截斷跟一個壞掉的字串長得一模一樣。
    """
    long = "甲" * 300
    rep = D._blockers(f"# B\n\n## B-97　長的\n\n**擋住：** {long}\n")
    ln = [x for x in D._blocker_lines(rep) if x.startswith("- B-97")][0]
    assert "…" in ln and "BLOCKERS.md" in ln
    assert len(ln) < 200, "截斷還是要真的有截"
