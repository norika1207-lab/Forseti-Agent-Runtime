"""交接檔記下的那幾個雜湊,現在還對不對得上。

2026-09-18 自動接續那一輪加。起因是上一輪自己的「還缺什麼」第一條,
原話:

    收尾的順序是「重產 `NEXT.md` → 寫這一節」,而 `NEXT.md` 的
    「產出在哪裡」那一節裡有這個檔的 hash。所以寫完這一節,
    `NEXT.md` 當場就過期了。現在靠人記得多重產一次,**沒有東西擋**。

這一組守的是那個「東西」:

1. 交出去的那份 `NEXT.md` 上面那幾行讀得回來（而且只讀那一節）。
2. 對不上的時候,「交接寫完之後才改的」跟「檔案沒被動過卻對不上」
   **分開回**。前者是追尾,重產一次就對了;後者是那句記錄在寫下的
   當下就不成立 —— 那才是真正要抓的。量不到的是第三類,不歸進前兩類。
3. 全部對得上的時候照樣印一行,而且那一行講得出它管到哪裡為止。
   一個乾淨時什麼都不印的檢查,分不出「乾淨」跟「根本沒跑」。
4. doctor 真的接上去了。後端算對而畫面沒接,跑後端測試會全綠。

全部寫在 tmp_path,不碰正本 `.forseti/`。
"""

from __future__ import annotations

import os
import sys
import textwrap
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import contract as CT  # noqa: E402


def 寫檔(base: Path, rel: str, body: str) -> None:
    f = base / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")


def 交接檔(base: Path, paths: list[str], *, mtime: float | None = None,
         limit: int = 10 ** 6) -> Path:
    """用真的 `artifact_lines()` 產那一節,不自己拼字串。

    自己拼會讓這一組永遠通過 —— 它測到的是我對格式的記憶,
    不是那一支實際印出來的東西。
    """
    ctx = {"artifact_paths": [{"path": p, "source": "worktree",
                               "vcs": "已追蹤但有改動"} for p in paths],
           "artifact_hashes": CT.artifact_hashes(
               [{"path": p} for p in paths], cwd=base)}
    body = ["# 接下來要做什麼", "", CT.ARTIFACT_HEADING, ""]
    body += CT.artifact_lines(ctx, limit=limit)
    out = base / ".forseti" / "NEXT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(body), encoding="utf-8")
    if mtime is not None:
        os.utime(out, (mtime, mtime))
    return out


# ---------------------------------------------------------------- 讀得回來

def test_那個標題在排版側已經不是第二份字面值():
    """`handoff.py` 不准再自己寫一次那個標題,它要用同一份常數。

    **這一條跟它取代掉的那一條方向相反。** 舊的那一條掃的是
    「那個字面值在不在 `handoff.py` 裡」,前提是兩邊各寫一次、
    只能靠測試去比對。2026-09-18 那一輪量過那個前提留下的逃生路:
    把字面值搬進註解、印出去的那一行改掉,這個檔 35 條全綠 ——
    因為它掃的是整份原始碼,不是實際印出去的那一行。

    現在排版側改成讀 `contract.ARTIFACT_HEADING`,那條路構造上
    走不出來了。所以這裡守的變成「不准再長回第二份」。
    """
    src = (ROOT / "apps" / "forseti-cli" / "handoff.py").read_text(encoding="utf-8")
    码 = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    码 = "\n".join(码)
    assert f'"{CT.ARTIFACT_HEADING}"' not in 码, (
        "排版側又自己寫了一次那個標題,它跟 contract 那一份會各自漂走")
    assert "contract.ARTIFACT_HEADING" in 码, (
        "排版側沒有在用那一份常數,那這一節的標題是從哪裡來的")


def _最小狀態(art_lines: list[str]) -> dict:
    """`render()` 要的十五個鍵,除了這一節以外全部給空的。

    **不用 `dict.fromkeys`**,因為 `missing_keys()` 看的是鍵在不在,
    而這裡要的是「其他每一節都不長出來」,值得是空的容器。
    """
    import handoff as HO
    st = {k: [] for k in HO.REQUIRED_KEYS}
    st["at"] = 1758124800.0   # render() 要的是 epoch,不是排好版的字串
    st["goal"] = "測試用"
    st["n"] = 1
    st["artifact_lines"] = list(art_lines)
    assert not HO.missing_keys(st), HO.missing_keys(st)
    return st


def test_真的走過一次排版再讀回來(tmp_path):
    """從 `handoff.render()` 印出去,再用 `recorded_artifacts()` 讀回來。

    **這一條是這個檔裡唯一一條真的走過產出者的。** 其他每一條
    （含 `交接檔()` 這個 helper）都只呼叫 `artifact_lines()` 產內容,
    標題那一行是自己拼 `CT.ARTIFACT_HEADING` 拼出來的 —— 所以
    排版側實際印什麼,這一組從來沒有看過。

    那正是舊 `test_那個標題兩邊是同一個` 補不到的縫:它掃原始碼,
    這一條走輸出。
    """
    寫檔(tmp_path, "a.py", "print(1)\n")
    路徑 = "a.py"
    ctx = {"artifact_paths": [{"path": 路徑, "source": "worktree",
                               "vcs": "已追蹤但有改動"}],
           "artifact_hashes": CT.artifact_hashes([{"path": 路徑}], cwd=tmp_path)}
    import handoff as HO
    text = HO.render(_最小狀態(CT.artifact_lines(ctx, limit=10 ** 6)))

    rows = CT.recorded_artifacts(text)
    assert [r["path"] for r in rows] == [路徑], (
        f"排版側印出去的那一節讀不回來,切到 {len(rows)} 行")
    assert rows[0]["hash"] and len(rows[0]["hash"]) == 16


def test_排版側印的標題就是切節用的那一個():
    """輸出裡真的有那一行,而且是一字不差的那一行。

    上一條測的是「讀得回來」,這一條測的是「讀回來靠的是它」。
    兩條都要:`recorded_artifacts()` 有可能因為別的理由切到東西,
    那時候第一條會綠而這一條會紅。
    """
    import handoff as HO
    text = HO.render(_最小狀態(["- `a.py` ── 已追蹤但有改動，0123456789abcdef"]))
    assert CT.ARTIFACT_HEADING in text.splitlines(), (
        "輸出裡沒有那一行,那上一條是切到別的東西")


def test_排版側載得進來而且沒有繞回去(tmp_path):
    """兩個載入順序各走一次,證明那個延後 import 不會轉成環。

    `contract.py` 在函式裡 `import handoff`,`handoff.py` 現在也在
    函式裡 `import contract`。這一條守的是**兩個載入順序都到得了
    `render()`**,不是「延後 import 有沒有必要」。

    後面那一句量過了,答案是沒必要:把兩邊都搬到模組頂層造成真的環,
    這個檔照樣 38 條全綠。**所以這一條不准被讀成「它證明了延後
    import 是對的」** —— 它證明的只有這兩條路現在都走得通。
    延後的真正理由寫在 `handoff.py` 那一處的註解裡,是未來式的。
    """
    import subprocess
    cli = str(ROOT / "apps" / "forseti-cli")
    for 先, 後 in (("contract", "handoff"), ("handoff", "contract")):
        码 = (f"import sys; sys.path.insert(0, {cli!r});"
              f" import {先}; import {後};"
              " import handoff, contract;"
              " st = {k: [] for k in handoff.REQUIRED_KEYS};"
              " st.update(at=1758124800.0, goal='y', n=1,"
              " artifact_lines=['- `a.py` ── 已追蹤但有改動，0123456789abcdef']);"
              " t = handoff.render(st);"
              " assert contract.ARTIFACT_HEADING in t.splitlines(), t;"
              " print('ok')")
        r = subprocess.run([sys.executable, "-c", 码], capture_output=True,
                           text=True, cwd=str(tmp_path))
        assert r.returncode == 0, f"先 import {先} 就壞了:{r.stderr}"
        assert "ok" in r.stdout


def test_讀得回自己印出去的那幾行(tmp_path):
    寫檔(tmp_path, "a.py", "print(1)\n")
    寫檔(tmp_path, "b/c.md", "# hi\n")
    交接檔(tmp_path, ["a.py", "b/c.md"])
    rows = CT.recorded_artifacts((tmp_path / ".forseti" / "NEXT.md").read_text("utf-8"))
    assert [r["path"] for r in rows] == ["a.py", "b/c.md"]
    assert all(r["hash"] and len(r["hash"]) == 16 for r in rows)


def test_只掃那一節不掃整份(tmp_path):
    """別的節裡有一模一樣格式的行,不准被算進來。"""
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    text = out.read_text("utf-8") + (
        "\n## 別的一節\n\n- `別人的檔.py` ── 已追蹤但有改動，0123456789abcdef\n")
    rows = CT.recorded_artifacts(text)
    assert [r["path"] for r in rows] == ["a.py"]


def test_當初就沒記雜湊的不算對得上(tmp_path):
    """那一格印的是「這是目錄」之類的字,不是雜湊。沒有東西可以比。"""
    (tmp_path / "d").mkdir()
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["d", "a.py"])
    d = CT.artifact_drift(out.read_text("utf-8"), cwd=tmp_path, out=out)
    assert [x["path"] for x in d["skipped"]] == ["d"]
    assert d["matched"] == ["a.py"]


# ---------------------------------------------------------------- 對不對得上

def test_內容沒變就對得上(tmp_path):
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    d = CT.artifact_drift(out.read_text("utf-8"), cwd=tmp_path, out=out)
    assert d["matched"] == ["a.py"] and not d["stale"]


def test_內容變了就對不上(tmp_path):
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    寫檔(tmp_path, "a.py", "print(2)\n")
    d = CT.artifact_drift(out.read_text("utf-8"), cwd=tmp_path, out=out)
    assert [x["path"] for x in d["stale"]] == ["a.py"]
    assert d["stale"][0]["was"] != d["stale"][0]["now"]


def test_檔案不在了不算內容變了(tmp_path):
    """已經被刪掉的產出,跟被改過的產出,不是同一件事。

    併成一類的話,「這份交接指向不存在的東西」會被讀成「有人改過檔案」。
    """
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    (tmp_path / "a.py").unlink()
    d = CT.artifact_drift(out.read_text("utf-8"), cwd=tmp_path, out=out)
    assert [x["path"] for x in d["gone"]] == ["a.py"]
    assert not d["stale"]


# ------------------------------------------------ 追尾 跟 當下就不成立 要分開

def test_交接寫完之後才改的標成追尾(tmp_path):
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"], mtime=time.time() - 60)
    寫檔(tmp_path, "a.py", "print(2)\n")          # 現在改,比交接新
    d = CT.artifact_drift(out.read_text("utf-8"), cwd=tmp_path, out=out)
    assert d["stale"][0]["changed_after"] is True


def test_檔案沒被動過卻對不上是另一類(tmp_path):
    """這一類才是真正要抓的:那句記錄在寫下的當下就不成立。

    造法是把交接檔的 mtime 推到未來,於是檔案「不是在交接之後改的」。
    """
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    寫檔(tmp_path, "a.py", "print(2)\n")
    future = time.time() + 600
    os.utime(out, (future, future))
    d = CT.artifact_drift(out.read_text("utf-8"), cwd=tmp_path, out=out)
    assert d["stale"][0]["changed_after"] is False


def test_量不到什麼時候被動的不歸進前兩類(tmp_path):
    """交接檔的 mtime 拿不到的時候回 None,不回 False。

    回 False 會把一筆量不到的東西指控成「寫下的當下就不成立」。
    """
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    text = out.read_text("utf-8")
    out.unlink()                                   # 交接檔本身不見了 → 沒有 at
    寫檔(tmp_path, "a.py", "print(2)\n")
    d = CT.artifact_drift(text, cwd=tmp_path, out=out)
    assert d["at"] is None
    assert d["stale"][0]["changed_after"] is None


# ---------------------------------------------------------------- 行文

def test_全部對得上照樣印一行(tmp_path):
    """乾淨時什麼都不印的檢查,分不出「乾淨」跟「根本沒跑」。"""
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    lines = CT.drift_lines(CT.artifact_drift(out.read_text("utf-8"),
                                             cwd=tmp_path, out=out))
    assert lines and "對得上" in lines[0]


def test_那一行講得出它管到哪裡為止(tmp_path):
    """少了那半句,它會被讀成「這幾個檔沒問題」,而它只說這一刻內容一樣。"""
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    body = "\n".join(CT.drift_lines(CT.artifact_drift(
        out.read_text("utf-8"), cwd=tmp_path, out=out)))
    assert "這一刻" in body and "改過又改回來" in body


def test_兩類對不上在行文上分得出來(tmp_path):
    """後端分好而行文併成一行,讀的人照樣分不出來。"""
    d = {"checked": 2, "matched": [], "gone": [], "unmeasured": [], "skipped": [],
         "problem": None, "at": 1.0, "source": "x",
         "stale": [{"path": "追尾.py", "was": "a" * 16, "now": "b" * 16,
                    "changed_after": True},
                   {"path": "當下.py", "was": "c" * 16, "now": "d" * 16,
                    "changed_after": False}]}
    body = "\n".join(CT.drift_lines(d))
    assert "追尾" in body
    assert "沒被動過" in body
    追尾行 = [l for l in body.splitlines() if "追尾.py" in l]
    當下行 = [l for l in body.splitlines() if "當下.py" in l]
    assert 追尾行 and 當下行 and 追尾行 != 當下行


def test_讀不到交接檔不准報成對得上(tmp_path):
    out = tmp_path / ".forseti" / "NEXT.md"
    d = CT.artifact_drift(cwd=tmp_path, out=out)
    assert d["problem"]
    assert not d["matched"]
    body = "\n".join(CT.drift_lines(d))
    assert "對不到不等於對得上" in body


def test_一行雜湊都沒有的時候講得出來(tmp_path):
    out = tmp_path / ".forseti" / "NEXT.md"
    out.parent.mkdir(parents=True)
    out.write_text("# 接下來要做什麼\n", encoding="utf-8")
    d = CT.artifact_drift(out.read_text("utf-8"), cwd=tmp_path, out=out)
    assert d["checked"] == 0
    assert "一行雜湊都沒有" in "\n".join(CT.drift_lines(d))


# ---------------------------------------------------------------- 接上去了沒

def test_doctor真的接上去了():
    """後端算對而畫面沒接,跑後端測試會全綠 —— 那是 2026-09-18 那一輪
    反向驗證 D 列的形狀,所以這一條單獨釘住接線。"""
    src = (ROOT / "apps" / "forseti-cli" / "forseti.py").read_text(encoding="utf-8")
    assert "def _artifact_drift(" in src
    assert "\n    _artifact_drift()\n" in src


def test_contract自己跑起來也印():
    src = (ROOT / "apps" / "forseti-cli" / "contract.py").read_text(encoding="utf-8")
    assert "drift_lines(artifact_drift())" in src


# ------------------------------------------------ 那一行的格式只有一份

def test_排版跟讀回來用的是同一份格式():
    """`artifact_lines()` 不准自己寫死那一行的長相。

    先前排版在 f-string、讀回來在正則,兩邊各寫一次。
    2026-09-18 實測過只改排版不改正則會怎樣:這個檔當場 11 條紅,
    **所以那不是靜默失效**,測試擋得住。這一條守的是更前面一步 ——
    讓那個不一致從「測試會擋」變成構造上做不出來。

    抓法是看原始碼有沒有走 `ART_ROW_FMT`,而不是比對輸出:
    比對輸出的測試在兩邊同時被改壞的那天照樣全綠。
    """
    import ast
    import inspect

    src = inspect.getsource(CT.artifact_lines)
    tree = ast.parse(textwrap.dedent(src))
    用到 = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "ART_ROW_FMT" in 用到, "artifact_lines() 沒走 ART_ROW_FMT"

    分隔符 = [t for t in ("──", "`{") if t in src]
    assert not 分隔符, f"artifact_lines() 裡還有寫死的排版:{分隔符}"


def test_格式多一欄而樣式沒跟上會當場炸():
    """`_fmt_to_re` 遇到沒定義樣式的欄位要 KeyError,不准生出

    一個少一欄照樣匹配得上的正則 —— 那會讓多出來的那一欄
    靜默地被併進隔壁欄,而併進去之後讀起來完全正常。
    """
    with pytest.raises(KeyError):
        CT._fmt_to_re("- `{path}` ── {tag}，{mark}，{誰改的}", CT.ART_FIELD_PAT)


def test_欄位順序換掉照樣讀得回正確的欄():
    """具名群組守的就是這個。位置群組在這裡會靜默錯位。"""
    rx = CT._fmt_to_re("- {tag}：`{path}` ── {mark}", CT.ART_FIELD_PAT)
    m = rx.match("- 已追蹤但有改動：`a/b.py` ── 0123456789abcdef")
    assert m.group("path") == "a/b.py"
    assert m.group("tag") == "已追蹤但有改動"
    assert m.group("mark") == "0123456789abcdef"


@pytest.mark.parametrize("source,vcs", [
    ("tool_point", ""),
    ("worktree", "已追蹤但有改動"),
    ("worktree", "從來沒進版控"),
])
@pytest.mark.parametrize("state,mark", [
    ("ok", "0123456789abcdef"),
    ("missing", "檔案不在了"),
    ("dir", "這是目錄"),
    ("unmeasured", "量不到"),
    ("其他", "沒有雜湊"),
])
def test_實際印得出來的每一種組合都讀得回來(source, vcs, state, mark):
    """`artifact_lines()` 的 tag 與 mark 各有一組值域,逐一走一次。

    **這一條抓的是欄位錯位。** `tag` 那一欄的樣式是 `[^，]*`,
    所以任何一個含全形逗號的 tag 或 vcs 都會讓正則切在錯的地方,
    而切錯之後那一行仍然匹配得上、仍然讀得回三欄 ——
    讀起來完全正常,只是 mark 變成了半個 tag。

    先前這裡只走過一種組合（worktree + 已追蹤但有改動 + 真雜湊）,
    所以另外十四種從來沒有人走過。
    """
    路徑 = "a/b.py"
    ctx = {"artifact_paths": [{"path": 路徑, "source": source, "vcs": vcs}],
           "artifact_hashes": [{"path": 路徑, "state": state,
                                "hash": "0123456789abcdef" * 4}]}
    text = "\n".join(["# x", "", CT.ARTIFACT_HEADING, ""]
                     + CT.artifact_lines(ctx))
    rows = CT.recorded_artifacts(text)
    assert len(rows) == 1, f"那一行讀不回來:{text!r}"
    assert rows[0]["path"] == 路徑
    assert rows[0]["mark"] == mark, "欄位錯位了"
    期望 = "這一輪寫的" if source == "tool_point" else vcs
    assert rows[0]["tag"] == 期望


# ------------------------------------------ 這一支管到哪裡為止（2026-09-18）

def test_被截掉的那幾個永遠不會被追尾抓到(tmp_path):
    """**這一組存在的理由,而且它是量出來的不是推論出來的。**

    `desktop_api.py:1911` 傳的是 `limit=10`,工作區 2026-09-18 實測
    26 個路徑,所以另外 16 個從來沒有被寫進那一節。沒有被寫進去的
    東西不會出現在 `recorded_artifacts()` 裡,於是 `artifact_drift()`
    對得到的範圍就只有 10 個。

    這一條改一個**被截掉的**檔案,然後確認這一支照樣說「全部對得上」——
    那句話沒有一個字是假的,而它漏掉的正是剛剛被改的那一個。
    """
    for rel in ("a.py", "b.py", "c.py"):
        寫檔(tmp_path, rel, "print(1)\n")
    out = 交接檔(tmp_path, ["a.py", "b.py", "c.py"], limit=1)

    寫檔(tmp_path, "c.py", "print(2)\n")          # 被截掉的那一個
    d = CT.artifact_drift(cwd=tmp_path, out=out)

    assert d["checked"] == 1, f"那一節記了 {d['checked']} 筆,預期 1"
    assert not d["stale"] and not d["gone"], "改的是沒被記下來的那一個,不該對不上"
    assert d["uncovered"] == 2, f"沒被記下來的有 2 個,讀回 {d['uncovered']}"

    行 = "\n".join(CT.drift_lines(d))
    assert "另外 2 個" in 行, f"全對得上那一條路徑沒有講邊界:{行!r}"


def test_沒被截斷的時候是0不是None(tmp_path):
    """`0` 是量出來的「沒有被截斷」,`None` 是讀不回來。不准混。"""
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    d = CT.artifact_drift(cwd=tmp_path, out=out)
    assert d["uncovered"] == 0
    assert "另外" not in "\n".join(CT.drift_lines(d)), (
        "沒有東西被截掉的時候不該印邊界那一句,那會變成雜訊")


def test_一行路徑都讀不回來的時候回None(tmp_path):
    """那一節在,可是一行都切不出來。**這種時候不准回 0** ——

    `0` 讀起來是「全部都記下來了」,而實際上這一刻是
    「不知道記了什麼」。這兩件事在這裡分得出來。
    """
    text = "\n".join(["# x", "", CT.ARTIFACT_HEADING, "", "（這一節是空的）", ""])
    assert CT.recorded_truncation(text) is None
    assert CT.recorded_truncation("# x\n\n## 別節\n") is None


def test_讀不回來那一種在drift_lines裡到不了(tmp_path):
    """`_uncovered_line()` 的 docstring 寫著「走到這裡 uncovered 一定是數字」。

    **那是一個推論,所以要有人守。** 推論的依據是
    `if not d.get("checked")` 提早回,哪天那一行被拿掉,
    這一條會紅,而不是靜默地走進那個沒有人走過的分支。
    """
    d = CT.artifact_drift(text="# x\n\n" + CT.ARTIFACT_HEADING + "\n\n", cwd=tmp_path,
                          out=tmp_path / "無此檔.md")
    assert d["uncovered"] is None
    行 = CT.drift_lines(d)
    assert len(行) == 1 and "一行雜湊都沒有" in 行[0], (
        f"checked=0 不再提早回了,那 `_uncovered_line()` 要自己處理 None:{行!r}")


def test_截斷那一行的格式只有一份():
    """跟 `test_排版跟讀回來用的是同一份格式` 同一條理由,守的是另一行。

    抓法一樣是看原始碼走不走那個常數,不是比對輸出:
    比對輸出的測試在兩邊同時被改壞的那天照樣全綠。
    """
    import ast
    import inspect

    src = inspect.getsource(CT.artifact_lines)
    tree = ast.parse(textwrap.dedent(src))
    用到 = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "ART_TRUNC_FMT" in 用到, "artifact_lines() 沒走 ART_TRUNC_FMT"
    assert "沒列出來" not in src, "那一行的字面值又長回排版側了"


def test_截斷行那一欄不是數字就不准匹配():
    """`ART_TRUNC_PAT` 用 `\\d+` 不用 `.*`。

    `.*` 會讓「還有 一些 個沒列出來」也讀得回來,然後
    `int()` 在 `recorded_truncation()` 裡炸,而炸的位置
    離真正的原因很遠。
    """
    好 = CT.ART_TRUNC_FMT.format(n=7)
    壞 = CT.ART_TRUNC_FMT.format(n="一些")
    assert CT._ART_TRUNC.match(好)
    assert CT._ART_TRUNC.match(好).group("n") == "7"
    assert not CT._ART_TRUNC.match(壞), "非數字也匹配得上,int() 會在別的地方炸"


def test_截斷行跟路徑行讀的是同一節(tmp_path):
    """別節裡有一行長得一樣的,不准被讀進來。

    `_section()` 已經守著路徑行,這一條確認新的那一支走的是同一支,
    不是自己 grep 整份檔案。
    """
    寫檔(tmp_path, "a.py", "print(1)\n")
    ctx = {"artifact_paths": [{"path": "a.py", "source": "worktree",
                               "vcs": "已追蹤但有改動"}],
           "artifact_hashes": CT.artifact_hashes([{"path": "a.py"}], cwd=tmp_path)}
    body = ["# x", "", CT.ARTIFACT_HEADING, ""]
    body += CT.artifact_lines(ctx, limit=10 ** 6)
    body += ["## 別的一節", "", CT.ART_TRUNC_FMT.format(n=999), ""]
    assert CT.recorded_truncation("\n".join(body)) == 0, (
        "切到別節去了,那個 999 不是這一節的")


def test_對不上跟沒被記下來同時成立的時候兩句都印(tmp_path):
    """兩件事不是互斥的,所以不准只印一句。"""
    for rel in ("a.py", "b.py"):
        寫檔(tmp_path, rel, "print(1)\n")
    out = 交接檔(tmp_path, ["a.py", "b.py"], limit=1, mtime=time.time() - 5)
    寫檔(tmp_path, "a.py", "print(2)\n")        # 被記下來的那一個
    d = CT.artifact_drift(cwd=tmp_path, out=out)
    assert len(d["stale"]) == 1 and d["uncovered"] == 1
    行 = "\n".join(CT.drift_lines(d))
    assert "對不上" in 行 and "另外 1 個" in 行, 行


# ------------------------------- 是哪幾個,不只是幾個（2026-09-18 04:4x）

def test_被截掉的那幾個現在指名道姓(tmp_path):
    """數量答不出「我剛改的那個檔在不在裡面」,而那是唯一想知道的事。

    上一輪把邊界變成一個數字（「另外 16 個不在這個檢查裡」）。
    那句話沒辦法拿去查:讀的人手上有一個剛改過的路徑,他要知道的是
    那個路徑在不在被截掉的那一批,而數量回答不了。
    """
    for rel in ("a.py", "b.py", "c.py"):
        寫檔(tmp_path, rel, "print(1)\n")
    out = 交接檔(tmp_path, ["a.py", "b.py", "c.py"], limit=1)

    assert CT.recorded_unlisted(out.read_text("utf-8")) == ["b.py", "c.py"]
    d = CT.artifact_drift(cwd=tmp_path, out=out)
    assert d["uncovered_paths"] == ["b.py", "c.py"]
    行 = "\n".join(CT.drift_lines(d))
    assert "b.py" in 行 and "c.py" in 行, f"邊界那一句還是只講得出數量:{行!r}"


def test_名單上的路徑不准變成被記下來的(tmp_path):
    """**這一條是那一行刻意不帶雜湊的理由。**

    帶了雜湊,`recorded_artifacts()` 就會把它們讀成記錄,於是這幾個
    路徑進了追尾範圍 —— 而這一行的用途正好相反:它宣告這些東西
    **不**在範圍內。名單跟範圍是兩件事,混成一件的話
    `uncovered` 會跟 `checked` 一起長大,邊界那一句就永遠印不出來。
    """
    for rel in ("a.py", "b.py", "c.py"):
        寫檔(tmp_path, rel, "print(1)\n")
    out = 交接檔(tmp_path, ["a.py", "b.py", "c.py"], limit=1)
    text = out.read_text("utf-8")

    記下的 = [r["path"] for r in CT.recorded_artifacts(text)]
    assert 記下的 == ["a.py"], f"名單那一行被讀成記錄了:{記下的}"
    d = CT.artifact_drift(text, cwd=tmp_path, out=out)
    assert d["checked"] == 1 and d["uncovered"] == 2

    寫檔(tmp_path, "c.py", "print(2)\n")          # 名單上的那一個
    d2 = CT.artifact_drift(text, cwd=tmp_path, out=out)
    assert not d2["stale"], "名單上的檔案被改了不該算對不上,它不在範圍內"


def test_舊格式的交接檔答得出數量答不出名單(tmp_path):
    """有截斷行、沒名單行。**這種時候回 `None` 不回 `[]`。**

    `[]` 讀起來是「沒有被截斷」,而實情是「被截斷了,但是不知道
    是哪幾個」。一份改版之前寫出去的交接檔就是這種,而它不該
    看起來像一份完整的。
    """
    body = ["# x", "", CT.ARTIFACT_HEADING, "",
            CT.ART_ROW_FMT.format(path="a.py", tag="已追蹤但有改動",
                                  mark="a" * 16),
            CT.ART_TRUNC_FMT.format(n=2), ""]
    text = "\n".join(body)
    assert CT.recorded_truncation(text) == 2, "數量這一欄照樣要讀得回來"
    assert CT.recorded_unlisted(text) is None, "沒有名單行不准回空清單"

    寫檔(tmp_path, "a.py", "print(1)\n")
    out = tmp_path / ".forseti" / "NEXT.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    行 = "\n".join(CT.drift_lines(CT.artifact_drift(text, cwd=tmp_path, out=out)))
    assert "另外 2 個" in 行
    assert "讀不回來" in 行, f"答不出名單這件事沒有印出來:{行!r}"


def test_沒被截斷的時候名單是空的不是讀不回來(tmp_path):
    """`[]` 是「不需要名單」,`None` 是「答不出來」。不准合成一個。"""
    寫檔(tmp_path, "a.py", "print(1)\n")
    out = 交接檔(tmp_path, ["a.py"])
    text = out.read_text("utf-8")
    assert CT.recorded_unlisted(text) == []
    assert CT.recorded_unlisted(text) is not None
    # 那一節整個讀不回來的那一種,仍然是 None
    assert CT.recorded_unlisted("# x\n\n## 別節\n") is None


def test_名單那一行的格式只有一份():
    """跟另外兩條同一條理由,守的是第三行。

    抓法是看原始碼走不走那幾個常數。**兩個常數都要檢查**:
    整行的格式與每一項的格式是分開的兩份,第一版就是只抽了前者,
    反引號留在 f-string 裡被 `test_排版跟讀回來用的是同一份格式` 抓到。
    """
    import ast
    import inspect

    src = inspect.getsource(CT.artifact_lines)
    tree = ast.parse(textwrap.dedent(src))
    用到 = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "ART_UNLISTED_FMT" in 用到, "artifact_lines() 沒走 ART_UNLISTED_FMT"
    assert "ART_UNLISTED_ITEM_FMT" in 用到, (
        "每一項的格式沒走常數,反引號又寫死在排版側了")
    assert "ART_UNLISTED_SEP" in 用到, "分隔符沒走常數,讀回來那一支會切錯"


def test_項目沒被包起來就不算讀得回來():
    """**不用 `strip("`")`。** 那會把沒被包起來的字串照樣收下來。

    排版壞掉的那天,`strip` 版本會讀回一串看起來正常的路徑,
    而正則版本讀回空的 —— 空的才是真話:那一行已經不是這個格式了。
    """
    好 = CT.ART_UNLISTED_FMT.format(paths=CT.ART_UNLISTED_SEP.join(
        CT.ART_UNLISTED_ITEM_FMT.format(path=p) for p in ("a.py", "b.py")))
    壞 = CT.ART_UNLISTED_FMT.format(paths="a.py、b.py")     # 沒有反引號
    text = f"# x\n\n{CT.ARTIFACT_HEADING}\n\n{好}\n"
    assert CT.recorded_unlisted(text) == ["a.py", "b.py"]
    assert CT.recorded_unlisted(f"# x\n\n{CT.ARTIFACT_HEADING}\n\n{壞}\n") == []


def test_數量跟名單打架的時候兩個都印():
    """兩欄各自讀回來,所以它們對不上是量得到的。**不替它挑一邊。**

    挑一邊當真就會在「那一節自己壞了」的時候印出一句看起來正常的話。
    """
    d = {"checked": 1, "matched": ["a.py"], "stale": [], "gone": [],
         "unmeasured": [], "skipped": [], "problem": None, "at": 1.0,
         "source": "x", "uncovered": 5, "uncovered_paths": ["b.py", "c.py"]}
    行 = "\n".join(CT.drift_lines(d))
    assert "另外 5 個" in 行
    assert "打架" in 行, f"數量 5 跟名單 2 對不上,行文沒有講:{行!r}"
    assert "b.py" in 行 and "c.py" in 行, "名單照印,不因為打架就不印"


# ----------------------------- 明細那一層的截斷也要宣告（2026-09-18 04:4x）

def test_每一類超過上限就講出還有幾筆():
    """`drift_lines()` 每一類只印 `DRIFT_ROW_LIMIT` 筆。

    這個上限 2026-09-18 查過**從來沒有被觸發過**（那一輪四類最多 2 筆）。
    沒被觸發過的截斷仍然要宣告 —— 真的踩到那一天,讀的人看到的是
    一份看起來完整的清單,而這正是同一輪在 `ART_UNLISTED_FMT` 那一節
    解掉的形狀。
    """
    n = CT.DRIFT_ROW_LIMIT + 3
    stale = [{"path": f"f{i}.py", "was": "a" * 16, "now": "b" * 16,
              "changed_after": True} for i in range(n)]
    d = {"checked": n, "matched": [], "stale": stale, "gone": [],
         "unmeasured": [], "skipped": [], "problem": None, "at": 1.0,
         "source": "x", "uncovered": 0, "uncovered_paths": []}
    行 = CT.drift_lines(d)
    body = "\n".join(行)
    明細 = [l for l in 行 if "·" in l]
    assert len([l for l in 明細 if "→" in l]) == CT.DRIFT_ROW_LIMIT
    assert "還有 3 筆沒列出來" in body, f"截到上限而沒有宣告:{body!r}"


def test_剛好等於上限的時候不印那一句():
    """等於上限沒有東西被截掉。印了就是一句假話（「還有 0 筆」）。"""
    stale = [{"path": f"f{i}.py", "was": "a" * 16, "now": "b" * 16,
              "changed_after": True} for i in range(CT.DRIFT_ROW_LIMIT)]
    d = {"checked": CT.DRIFT_ROW_LIMIT, "matched": [], "stale": stale,
         "gone": [], "unmeasured": [], "skipped": [], "problem": None,
         "at": 1.0, "source": "x", "uncovered": 0, "uncovered_paths": []}
    assert "沒列出來" not in "\n".join(CT.drift_lines(d))


def test_四類都走同一支所以都會宣告():
    """哪天多一類而忘了宣告,這一條會紅。

    抓法是 AST:`drift_lines()` 裡不准再有自己切片的 `for` 迴圈。
    比對輸出抓不到「第五類忘了接」,因為那一類還不存在。
    """
    import ast
    import inspect

    src = inspect.getsource(CT.drift_lines)
    tree = ast.parse(textwrap.dedent(src))
    用到 = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "_drift_rows" in 用到, "drift_lines() 沒走那一支共用的明細排版"
    切片 = [n for n in ast.walk(tree) if isinstance(n, ast.Subscript)
            and isinstance(n.slice, ast.Slice)]
    assert not 切片, f"drift_lines() 裡還有自己切片的地方 {len(切片)} 處"


def test_名單答不出來的兩種來源不准講成同一句():
    """`recorded_unlisted()` 的 `None` 有兩種來源,而行文只講得出一種。

    上一輪（2026-09-18 04:5x）自己寫下這個缺口,原話:

        「一行路徑都讀不回來」與「有截斷行卻沒有名單行」都回 `None`,而
        `_uncovered_line()` 印的是後者那句（舊格式）。前者走不到那裡
        [...] **這一輪沒有為它補測試**

    上一條 `test_讀不回來那一種在drift_lines裡到不了` 守的是
    `uncovered` 那一欄,守的位置是 `drift_lines()` 的
    `if not d.get("checked")`。**這一條守的是第二道** ——
    就算那一道哪天被拿掉,`_uncovered_line()` 裡的 `u is None`
    仍然要先攔下來,因為「那一節整個讀不回來」的時候印
    「舊格式的交接檔」是一句假話:那一份根本沒有截斷行可以宣告數量。

    所以這裡**繞過 `drift_lines()` 直接餵 `_uncovered_line()`**。
    走 `drift_lines()` 進去的話 `checked` 會先攔住,測到的是上一條
    已經守著的那一道,而不是這一道。
    """
    甲 = CT._uncovered_line({"uncovered": None, "uncovered_paths": None})
    乙 = CT._uncovered_line({"uncovered": 2, "uncovered_paths": None})

    甲文, 乙文 = "\n".join(甲), "\n".join(乙)
    assert "舊格式" not in 甲文, (
        f"那一節整個讀不回來,卻被講成「舊格式的交接檔」:{甲文!r}　"
        "舊格式指的是有截斷行而沒名單行,這一種連截斷行都沒有")
    assert "有沒有被截斷" in 甲文, f"這一種該講的是連截斷都答不出來:{甲文!r}"
    assert "舊格式" in 乙文, f"有截斷行沒名單行那一種沒有被講出來:{乙文!r}"
    assert 甲文 != 乙文, "兩種來源印出同一句話,那讀的人分不出是哪一種"


def test_那兩種來源在讀回來那一層本來就分不出():
    """所以分得出來這件事,是 `uncovered` 那一欄給的,不是這一支給的。

    這一條釘住上面那一條的前提。哪天 `recorded_unlisted()` 自己
    改成分得出兩種（例如回一個 sentinel）,上面那一條的理由就換了,
    而這一條會先紅,提醒去改的人回頭看行文那一段還對不對。
    """
    整節讀不回來 = "# x\n\n" + CT.ARTIFACT_HEADING + "\n\n（這一節是空的）\n"
    舊格式 = "\n".join([
        "# x", "", CT.ARTIFACT_HEADING, "",
        CT.ART_ROW_FMT.format(path="a.py", tag="已追蹤但有改動", mark="a" * 16),
        CT.ART_TRUNC_FMT.format(n=2), ""])

    assert CT.recorded_unlisted(整節讀不回來) is None
    assert CT.recorded_unlisted(舊格式) is None
    # 分得出來的是這一欄:一個是 None,一個是數字。
    assert CT.recorded_truncation(整節讀不回來) is None
    assert CT.recorded_truncation(舊格式) == 2


# ------------------------- 兩道攔截同時失效（2026-09-18 05:4x 自動接續）

def test_兩道攔截同時失效的時候那一句仍然印得出來():
    """上一輪（2026-09-18 05:2x）自己寫下的缺口,原話:

        `_uncovered_line()` 的兩道攔截,只有第二道被單獨餵過。[...]
        **沒有人守「兩道同時被拿掉」** —— 那要造一個 `checked > 0`
        而 `uncovered is None` 的 dict,而那個組合 `artifact_drift()`
        此刻產不出來 [...] 要先想清楚那個組合該印什麼才寫得出測試

    ## 那個組合該印什麼,想清楚了

    `checked > 0` 是「那一節有雜湊可以對」,`uncovered is None` 是
    「那一節有沒有被截斷答不出來」。**兩題各有各的答案,不互相吞掉** ——
    上半題答得出來就照答,下半題答不出來就說答不出來。

    所以該印的是三句:雜湊那一行、「只說這一刻」那一行、
    以及邊界答不出來那一行。現在的程式碼就是這樣做的
    （2026-09-18 05:4x 實測),這一條是把它釘住,不是去改它。

    ## 為什麼不從 `artifact_drift()` 進去

    進不去。`checked = len(recorded_artifacts(text))` 與
    `recorded_truncation()` 的 `seen_row` 走的是同一個 `_ART_ROW`,
    所以有雜湊行就一定不會回 `None`。下一條測試釘住這個推論的依據。
    **產不出來不等於將來產不出來**,所以這一條手造 dict 直接餵
    `drift_lines()`,守的是「哪天真的產出來了,行文不會吞掉任何一半」。
    """
    d = {"checked": 3, "matched": ["a.py", "b.py", "c.py"], "stale": [],
         "gone": [], "unmeasured": [], "skipped": [], "problem": None,
         "at": 1.0, "source": "x", "uncovered": None, "uncovered_paths": None}
    行 = CT.drift_lines(d)
    文 = "\n".join(行)

    # 下半題:答不出來要說答不出來,而且不准講成「舊格式」那一種。
    assert "有沒有被截斷" in 文, (
        f"兩道攔截都失效之後,邊界那一句被吞掉了:{行!r}")
    assert "舊格式" not in 文, (
        f"這一份連截斷行都沒有,不准講成「舊格式的交接檔」:{文!r}")
    # 上半題:答得出來的那一半不准被下半題拖掉。
    assert any("對得上" in l for l in 行), (
        f"下半題答不出來,把答得出來的上半題也吞掉了:{行!r}")
    assert any("改過又改回來" in l for l in 行), (
        f"「只說這一刻」那一句不見了:{行!r}")

    # 有對不上的那一條 return 也是同一件事。`drift_lines()` 有兩個
    # `return out + _uncovered_line(d)`,兩條都要帶上它。
    d2 = dict(d, matched=["a.py"],
              stale=[{"path": "b.py", "was": "1" * 16, "now": "2" * 16,
                      "changed_after": True}])
    文2 = "\n".join(CT.drift_lines(d2))
    assert "有沒有被截斷" in 文2, (
        f"有對不上那一條 return 沒有帶上邊界那一句:{文2!r}")


def test_那個組合產不出來靠的是兩支讀同一份判準():
    """上面那一條的前提。**「此刻產不出來」是一個推論,所以要有人守。**

    推論的依據是兩件事:`recorded_artifacts()`（`checked` 的來源）
    與 `recorded_truncation()`（`uncovered` 的來源）切的是同一節、
    用的是同一個路徑行判準。哪天有人給其中一支換一個更嚴的判準,
    `checked > 0` 而 `uncovered is None` 就產得出來了 ——
    而那一天這一條先紅,提醒回頭看上面那一條還是不是只是紙上作業。

    抓法是 AST 不是比對輸出:換掉判準之後兩支對現有的交接檔
    可能還是同一個答案,比對輸出那天會全綠。
    """
    import ast
    import inspect

    共用 = {}
    for name in ("recorded_artifacts", "recorded_truncation"):
        src = textwrap.dedent(inspect.getsource(getattr(CT, name)))
        用到 = {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
        共用[name] = 用到

    for name, 用到 in 共用.items():
        assert "_ART_ROW" in 用到, (
            f"`{name}()` 不再走 `_ART_ROW`,那兩支的路徑行判準分家了 —— "
            "`checked > 0` 而 `uncovered is None` 可能產得出來,"
            "回去看 `test_兩道攔截同時失效的時候那一句仍然印得出來`")
        assert "ARTIFACT_HEADING" in 用到, (
            f"`{name}()` 不再切 `ARTIFACT_HEADING` 那一節,兩支讀的不是同一節了")

    # 光是名字對得上還不夠:兩支要真的對同一段文字給出一致的答案。
    有路徑行 = "\n".join([
        "# x", "", CT.ARTIFACT_HEADING, "",
        CT.ART_ROW_FMT.format(path="a.py", tag="已追蹤但有改動", mark="a" * 16), ""])
    assert len(CT.recorded_artifacts(有路徑行)) == 1
    assert CT.recorded_truncation(有路徑行) == 0, (
        "有路徑行卻回 None,那個組合此刻就產得出來了")
