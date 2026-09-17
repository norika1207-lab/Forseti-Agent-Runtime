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


# ---------------------------------------------------------------------------
# 第三個訊號：這一條被放在哪一個區段（2026-09-17 加）
#
# 起因是同一個檔案同一個問題，兩支程式回不同的數字而兩邊都不報異常：
# `forseti.extract_blockers` 在 `# 已解除` 那一行把檔案切掉，回 8 條；
# `desktop_api._blockers` 完全看不到區段，逐條判本文，回 11 條。
# 差的三條（B-17、B-14、B-13）放在已解除區底下，本文卻還寫著擋住什麼，
# 其中 B-17 的本文自己寫著「選哪一個是 owner 的決定」。
#
# 這一組守的是規則，不是「此刻剛好有幾條」。

FIX_SEC = """# BLOCKERS

---

## B-81　還在擋的

**擋住：** 階段 7 的出口條件。

# 已解除

放在這裡的不再是阻塞。

## B-82　兩邊都說結束了（已解除）

**擋住：** 無。實測解除。

## B-83　搬到下面去了，本文還寫著擋住什麼

**擋住：** 階段 3 的出口條件。
"""


def test_放在哪一個區段抽得出來_而且跟本文分得開():
    secs = D._blocker_sections(FIX_SEC)
    got = {s["id"]: s["in_resolved_section"] for s in secs}
    assert got == {"B-81": False, "B-82": True, "B-83": True}
    b83 = [s for s in secs if s["id"] == "B-83"][0]
    assert b83["blocks"] == "階段 3 的出口條件。", "區段不該吃掉本文"


def test_區段單獨不准關掉任何一條():
    """搬動是一次手動動作，本文一個字都不必改。

    讓區段有關閉權等於「搬過去就算解除」，那正是要抓的東西。
    """
    rep = D._blockers(FIX_SEC)
    ids = _by_id(rep)
    assert "B-83" in ids, "只有區段說結束，不准自動降級"
    assert "B-82" not in ids, "標題與擋住欄都說結束，這條照舊算解除"
    assert rep["open"] == 2 and rep["closed"] == 1
    assert rep["open"] + rep["closed"] == rep["total"]


def test_放錯區段的另外列出來_因為它的後果跟別的打架不一樣():
    """別的打架只是不一致，這一種會讓 `forseti doctor` 根本數不到。"""
    import forseti as F

    rep = D._blockers(FIX_SEC)
    assert rep["misfiled"] == ["B-83"]
    assert set(rep["misfiled"]) <= {x["id"] for x in rep["conflicting"]}, \
        "放錯區段的必須同時算打架，不然它只出現在一個地方"

    doctor = [x.split()[0] for x in F.extract_blockers(FIX_SEC)]
    assert "B-83" not in doctor, "這條測試的前提：doctor 那一支數不到它"
    assert len(doctor) != rep["open"], "兩支程式對同一個檔案給不同的數字"


def test_單一訊號的字串沒有變_多個訊號才串起來():
    """下游要知道打架的是哪幾邊才查得下去，所以不能只回一個布林。"""
    rep = D._blockers(FIX_SEC)
    assert _by_id(rep)["B-83"]["said_closed_by"] == "所在區段"

    old = D._blockers(FIX)                       # 沒有 `# 已解除` 的那份
    ids = _by_id(old)
    assert ids["B-93"]["said_closed_by"] == "標題"
    assert ids["B-94"]["said_closed_by"] == "擋住欄"

    both = D._blockers(
        "# B\n\n# 已解除\n\n## B-84　標題說結案（2026-01-01 結案）\n\n"
        "**擋住：** 階段 9。\n"
    )
    assert _by_id(both)["B-84"]["said_closed_by"] == "標題、所在區段"


def test_打架那句話不准寫死是兩個訊號():
    """訊號變三個之後「兩個訊號」會是錯的，而它錯得很安靜。"""
    rep = D._blockers(FIX_SEC)
    lines = D._blocker_lines(rep)
    joined = "\n".join(lines)
    assert "兩個訊號" not in joined
    assert "B-83" in joined and "已解除" in joined
    assert "doctor" in joined, "要講出後果，不然讀的人不知道去比哪兩個數字"


def test_沒有放錯區段的時候不長出那一行():
    """沒事也講一句的話，這一行會變成背景噪音。"""
    rep = D._blockers(FIX)
    assert rep["misfiled"] == []
    assert "已解除" not in "\n".join(D._blocker_lines(rep))


def test_真實檔案此刻確實有放錯區段的():
    """這一條會因為 owner 把那三條搬回去而變紅，那是好消息紅。

    所以它斷言的是「misfiled 這個欄位對真實檔案算得出東西」，
    不是「永遠有三條」。數字寫在訊息裡給下一個人看，不寫進斷言。
    """
    rep = D._blockers()
    assert isinstance(rep["misfiled"], list)
    for bid in rep["misfiled"]:
        assert bid in {x["id"] for x in rep["conflicting"]}, \
            f"{bid} 放錯區段卻沒算進打架"


# ---------------------------------------------------------------------------
# doctor 那一邊講不講得出自己少算了誰（2026-09-17 加）
#
# 上面那一組讓 `desktop_api._blockers` 說得出 misfiled，可是 `forseti doctor`
# 那一支還是安靜地回 8 —— 而跑 doctor 的人看不到桌面版，他不會知道
# 有三條在那個標題底下被切掉了。這一組守的是「doctor 講得出差在哪」，
# **不是「doctor 把它們算進去」**：算進去等於替 owner 挑了一邊。

def test_doctor_講得出自己少算了哪幾條():
    import forseti as F

    assert F.extract_misfiled(FIX_SEC) == ["B-83"]
    doctor = [x.split()[0] for x in F.extract_blockers(FIX_SEC)]
    assert "B-83" not in doctor, "這一條的前提：它本來就數不到 B-83"


def test_doctor_講出來但不准把它算進阻塞數(tmp_path):
    """自動降級等於替 owner 做決定，而這份檔案是她維護的。

    這一條走 `build_report`，不走 `extract_blockers`。寫這組測試的時候
    第一版斷言在 `extract_blockers` 上，而那個位置的反向驗證是綠的 ——
    因為那一支進門就 `re.split` 把 `# 已解除` 之後切掉，
    在它裡面怎麼接 misfiled 都接不到東西。**會發生自動降級的位置是
    兩個結果被組起來的那一層**，所以斷言要放在那裡。
    """
    import forseti as F

    fdir = tmp_path / ".forseti"
    fdir.mkdir()
    (fdir / "BLOCKERS.md").write_text(FIX_SEC, encoding="utf-8")
    rep = F.build_report(tmp_path)

    assert rep.misfiled == ["B-83"]
    assert len(rep.blockers) == 1, "少算的不准被併進阻塞數"
    assert not any("B-83" in b for b in rep.blockers)


def test_數不出來回_None_不回空list():
    """一個壞掉的查詢跟一個誠實的「沒有」不准長成同一個樣子。

    這是這個專案抓過很多次的形狀（`desktop_api._safe` 的檔頭寫著同一句）。
    """
    import forseti as F

    assert F.extract_misfiled(FIX) == [], "沒有已解除區的時候是真的沒有"

    real = F._sibling("desktop_api")

    def boom(_text=None):
        raise RuntimeError("借不到")

    orig = real._blockers
    real._blockers = boom
    try:
        assert F.extract_misfiled(FIX_SEC) is None, "借不到要回 None，不是 []"
    finally:
        real._blockers = orig
    assert F.extract_misfiled(FIX_SEC) == ["B-83"], "還原之後要恢復"


def test_doctor_不自己重寫一份解析():
    """再寫一次區段解析，就是造出第三個會跟前兩個對不上的數字。

    對不上正是這一支要講出來的那件事，所以它必須借，不准自己判。
    """
    import inspect

    import forseti as F

    src = inspect.getsource(F.extract_misfiled)
    assert "desktop_api" in src and "_blockers" in src, "要借，不要自己判"
    assert "已解除" not in src.split('"""')[-1], "函式本體不准自己認那個標題"


def test_status_那一行把少算的掛在阻塞旁邊(tmp_path, capsys):
    """少算的講的是同一個數字，另起一行會讓人以為是別的東西。

    第一版這條是 grep 原始碼找 `line +=`，反向驗證綠了 ——
    因為那個字串在同一支函式裡出現不只一次，把要守的那一處換掉，
    斷言照樣在別處成立。**在原始碼裡找字串，找到的可能不是你要的那一個。**
    改成跑一次拿真的輸出，斷言它們落在同一行。
    """
    import forseti as F

    fdir = tmp_path / ".forseti"
    fdir.mkdir()
    (fdir / "BLOCKERS.md").write_text(FIX_SEC, encoding="utf-8")
    F.cmd_status(F.build_report(tmp_path))

    out = capsys.readouterr().out
    same = [ln for ln in out.splitlines() if "阻塞" in ln and "放錯區段" in ln]
    assert same, f"少算的沒有掛在阻塞那一行上：\n{out}"
    assert "1" in same[0], "要講出少算幾條"


def test_doctor_的那幾行講得出後果與誰決定():
    """講「有三條沒算」而不講後果，讀的人不知道要去比哪兩個數字。"""
    import inspect

    import forseti as F

    src = inspect.getsource(F.cmd_doctor)
    assert "少算了" in src
    assert "owner 的決定" in src, "要講清楚這不是系統能自己選的"
    assert "兩支程式回不同的數字" in src, "要講出後果"
