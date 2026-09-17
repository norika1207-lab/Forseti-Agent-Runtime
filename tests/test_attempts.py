"""§39.1 failed_attempts 登記簿。

規格原文只有一行（AI-First 工程書 v1.0 第 975-977 行）:

    failed_attempts:
    - attempt + observed result + why not repeat

這一組守的是五件事，每一件都對著一個具體的退化路徑:

1. 三欄逐字對得上規格，而且缺任何一欄登不進去
2. 出處與記錄者是必填。一筆查不回去的失敗記錄是沒有證據的宣稱
3. `retry_condition` 沒給就要講為什麼沒有。空的重試條件讀起來是
   「永遠不要再試」，跟「有條件但沒人寫下來」是兩件事
4. 只增不改。放掉一筆是追加一筆，不是回頭改原來那一筆
5. **沒有重試條件的那些放不掉。** 那種當初登記的實情就是
   條件怎麼變都一樣，要推翻走的是 §40 的污染登記簿

第 5 條是這一組最容易被寫壞的。`release()` 如果什麼都放得掉，
這個登記簿就變成一個可以隨手清空的待辦清單，
而它存在的理由正是「下一個 session 不要再試一次」。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import attempts as AT  # noqa: E402


def _ok(**over):
    """一組能過的最小輸入。每一欄都是測試自己給的，不從環境撈。"""
    d = {
        "attempt": "跑 claude -p 去執行 §15 的 models 那一軸",
        "observed_result": "rc=1，stderr 是 OAuth session expired",
        "why_not_repeat": "認證過期，重試一定同樣失敗",
        "source": [".forseti/ROADMAP.md:3259"],
        "verifier": "自動接續 2026-09-17",
        "retry_condition": "owner 重新登入 claude CLI 之後",
    }
    d.update(over)
    return d


# ── 規格那三欄 ──────────────────────────────────────────────────

def test_規格那三欄的名字逐字對得上():
    """對的是規格原文，不是我自己在別處寫的另一個常數。

    比對自己寫的常數的話，兩邊一起寫錯會一起通過。
    """
    book = (ROOT / "docs" / "sources" /
            "Forseti_AI_First_Development_Engineering_Book_v1.0_2026-09-07.md")
    if not book.exists():
        pytest.skip(f"規格原文不在：{book}")
    txt = book.read_text(encoding="utf-8", errors="replace")
    assert "failed_attempts:" in txt, "規格裡找不到這一欄，那這一組在守什麼"
    assert "attempt + observed result + why not repeat" in txt, (
        "規格那一行的內容變了，這一組的前提要重看")
    assert AT.SPEC_FIELDS == ("attempt", "observed_result", "why_not_repeat")


@pytest.mark.parametrize("miss", ["attempt", "observed_result",
                                  "why_not_repeat"])
def test_規格三欄缺任何一欄都登不進去(miss, tmp_path):
    p = tmp_path / "a.jsonl"
    r = AT.record(path=p, **_ok(**{miss: ""}))
    assert not r["ok"], f"少了 {miss} 還登得進去"
    assert miss in r["why"], f"拒絕的理由要點名是哪一欄：{r['why']}"
    assert not p.exists(), "被拒絕的那一筆不准留在檔案裡"


@pytest.mark.parametrize("miss", ["source", "verifier"])
def test_出處與記錄者也是必填(miss, tmp_path):
    """規格沒列這兩欄，這裡多要。理由在模組說明，照 pollution.py 的先例。"""
    p = tmp_path / "a.jsonl"
    r = AT.record(path=p, **_ok(**{miss: [] if miss == "source" else ""}))
    assert not r["ok"]
    assert miss in r["why"]


def test_source只有空白字串等於沒給(tmp_path):
    r = AT.record(path=tmp_path / "a.jsonl", **_ok(source=["", "   "]))
    assert not r["ok"], "一串空白不算出處"


# ── retry_condition 那一對 ─────────────────────────────────────

def test_沒有重試條件就要講為什麼沒有(tmp_path):
    p = tmp_path / "a.jsonl"
    r = AT.record(path=p, **_ok(retry_condition=""))
    assert not r["ok"], "兩個都空還登得進去"
    assert "no_retry_basis" in r["why"]
    assert not p.exists()


def test_講了為什麼沒有就登得進去(tmp_path):
    r = AT.record(path=tmp_path / "a.jsonl",
                  **_ok(retry_condition="",
                        no_retry_basis="這個做法本身錯了，條件怎麼變都一樣"))
    assert r["ok"], r.get("why")
    assert r["record"]["retry_condition"] == ""
    assert r["record"]["no_retry_basis"]


def test_有重試條件就不必講為什麼沒有(tmp_path):
    r = AT.record(path=tmp_path / "a.jsonl", **_ok(no_retry_basis=""))
    assert r["ok"], r.get("why")


# ── 只增不改 ────────────────────────────────────────────────────

def test_寫進去的那一筆讀回來欄位一個不少(tmp_path):
    p = tmp_path / "a.jsonl"
    r = AT.record(path=p, **_ok())
    assert r["ok"]
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    for k in AT.SPEC_FIELDS + AT.EVIDENCE_FIELDS:
        assert rows[0][k], f"{k} 讀回來是空的"
    assert rows[0]["kind"] == "ATTEMPT"
    assert rows[0]["id"].startswith("att-")


def test_同樣的試法與同樣的結果算同一筆(tmp_path):
    p = tmp_path / "a.jsonl"
    a = AT.record(path=p, **_ok())
    b = AT.record(path=p, **_ok(why_not_repeat="換一句話講"))
    assert a["record"]["id"] == b["record"]["id"], (
        "id 由「試了什麼」加「看到什麼」決定，換一句理由不該變成另一筆")
    assert len(AT.records(path=p)) == 1, "折起來之後是一筆"
    assert len(AT.load(path=p)) == 2, "原始序列還是兩行，沒有改掉舊的"


def test_放掉是追加一筆不是改原來那筆(tmp_path):
    p = tmp_path / "a.jsonl"
    a = AT.record(path=p, **_ok())
    aid = a["record"]["id"]
    raw_before = p.read_text(encoding="utf-8")

    r = AT.release(aid, why="owner 09-17 重新登入了", verifier="測試", path=p)
    assert r["ok"], r.get("why")

    raw_after = p.read_text(encoding="utf-8")
    assert raw_after.startswith(raw_before), (
        "原來那一行被動過了。只增不改的意思是原文逐位元組留著")
    got = AT.get(aid, path=p)
    assert got["released"]["why"] == "owner 09-17 重新登入了"
    assert got["attempt"] == a["record"]["attempt"], "原始欄位不准被蓋掉"


def test_放掉之後不算還在擋路(tmp_path):
    p = tmp_path / "a.jsonl"
    aid = AT.record(path=p, **_ok())["record"]["id"]
    assert AT.summary(path=p)["active"] == 1
    AT.release(aid, why="條件成立了", verifier="測試", path=p)
    s = AT.summary(path=p)
    assert s["active"] == 0
    assert s["released"] == 1
    assert s["total"] == 1, "放掉的不從總數裡消失"


# ── 放不掉的那些 ────────────────────────────────────────────────

def test_沒有重試條件的那些放不掉(tmp_path):
    """這一組最重要的一條。

    什麼都放得掉的話，這個登記簿就是一個可以隨手清空的待辦清單。
    """
    p = tmp_path / "a.jsonl"
    aid = AT.record(path=p, **_ok(retry_condition="",
                                  no_retry_basis="做法本身錯了"))["record"]["id"]
    r = AT.release(aid, why="我覺得可以再試一次", verifier="測試", path=p)
    assert not r["ok"], "沒有重試條件的也放掉了"
    assert "污染登記簿" in r["why"], "要指得出正確的那條路：§40"
    assert AT.summary(path=p)["active"] == 1


def test_放掉要講理由與是誰確認的(tmp_path):
    p = tmp_path / "a.jsonl"
    aid = AT.record(path=p, **_ok())["record"]["id"]
    assert not AT.release(aid, why="", verifier="測試", path=p)["ok"]
    assert not AT.release(aid, why="條件成立", verifier="", path=p)["ok"]
    assert AT.summary(path=p)["active"] == 1


def test_找不到的放不掉(tmp_path):
    r = AT.release("att-不存在", why="x", verifier="y", path=tmp_path / "a.jsonl")
    assert not r["ok"]


def test_放過的不准再放一次(tmp_path):
    p = tmp_path / "a.jsonl"
    aid = AT.record(path=p, **_ok())["record"]["id"]
    AT.release(aid, why="條件成立", verifier="測試", path=p)
    r = AT.release(aid, why="再放一次", verifier="測試", path=p)
    assert not r["ok"]


# ── summary 的形狀 ──────────────────────────────────────────────

def test_active只回還在擋路的那些(tmp_path):
    """反向驗證抓到的缺口（2026-09-17）。

    `summary()` 自己算了一次還在擋路的數，所以把 `active()` 改成
    「全部都回」的時候，上面那條 `test_放掉之後不算還在擋路` 是綠的。
    兩支各算各的，就要各守各的。
    """
    p = tmp_path / "a.jsonl"
    keep = AT.record(path=p, **_ok(attempt="這件還在擋路"))["record"]["id"]
    gone = AT.record(path=p, **_ok(attempt="這件放掉了"))["record"]["id"]
    AT.release(gone, why="條件成立", verifier="測試", path=p)

    ids = [r["id"] for r in AT.active(path=p)]
    assert ids == [keep], f"放掉的那筆還在擋路清單裡：{ids}"
    assert len(AT.records(path=p)) == 2, "放掉的不從完整清單裡消失"


def test_summary把有重試條件的分開數(tmp_path):
    """那些是會過期的：條件成立了卻沒人去放，跟真的還在擋路長得一樣。"""
    p = tmp_path / "a.jsonl"
    AT.record(path=p, **_ok())
    AT.record(path=p, **_ok(attempt="另一件", retry_condition="",
                            no_retry_basis="做法錯了"))
    s = AT.summary(path=p)
    assert s["total"] == 2
    assert s["with_retry_condition"] == 1
    assert s["no_retry"] == 1


def test_空的時候不假裝有東西(tmp_path):
    s = AT.summary(path=tmp_path / "沒有這個檔.jsonl")
    assert s == {"total": 0, "active": 0, "released": 0,
                 "with_retry_condition": 0, "no_retry": 0,
                 "items": [], "version": AT.VERSION}


def test_壞掉的行跳過不當成資料(tmp_path):
    p = tmp_path / "a.jsonl"
    AT.record(path=p, **_ok())
    with p.open("a", encoding="utf-8") as f:
        f.write("這不是 json\n")
        f.write(json.dumps({"kind": "ATTEMPT"}, ensure_ascii=False) + "\n")
        f.write(json.dumps({"id": "x", "kind": "沒這種"}) + "\n")
    assert len(AT.load(path=p)) == 1, "壞行與沒有 id 的行不算資料"


# ── 不自動萃取 ──────────────────────────────────────────────────

def test_讀一次不准長出登記簿(tmp_path):
    """守的是模組說明那句「不自動登記」。

    讀完之後檔案還是不存在，才叫不自動萃取。
    """
    p = tmp_path / "a.jsonl"
    AT.summary(path=p)
    AT.records(path=p)
    AT.active(path=p)
    assert not p.exists(), "只是讀就把檔案建出來了"


def test_這一支沒有掃描散文的入口():
    """B-05 擋住靠句型判斷宣稱。這裡連那個函式都不該有。"""
    src = (ROOT / "apps" / "forseti-cli" / "attempts.py").read_text(
        encoding="utf-8")
    body = src.split('"""', 2)[-1]          # 跳過模組說明，那裡會提到這件事
    for bad in ("AUTO_CONTINUE_LOG", "ROADMAP.md", "re.compile", "import re"):
        assert bad not in body, (
            f"程式碼裡出現 {bad}，這一支開始自己去讀散文了")


# ── 接上 §39.1 ──────────────────────────────────────────────────

def test_有來源之後不准再標成沒有來源(tmp_path):
    import contract as C
    v = C._failed_attempts_field(path=tmp_path / "空的.jsonl")
    assert isinstance(v, C.Empty), f"空登記簿要是 EMPTY 不是 NO_SOURCE：{v!r}"
    why = str(getattr(v, "why", ""))
    assert "attempts.py" in why, "理由要指得出來源在哪"
    assert "forseti attempt" in why, "理由要指得出下一步做什麼"


def test_登了一筆之後那一欄有值(tmp_path):
    import contract as C
    p = tmp_path / "a.jsonl"
    AT.record(path=p, **_ok())
    v = C._failed_attempts_field(path=p)
    assert isinstance(v, dict), f"有資料還回 Empty/NoSource：{v!r}"
    assert v["total"] == 1
    assert v["items"][0]["why_not_repeat"], "帶出去的那一筆要有規格那三欄"
