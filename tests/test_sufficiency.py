"""Context Sufficiency Gate。v5.0 §17.3 / §19.2 / §39

這組守五件事：

一，**預設唯讀。** §19.2 寫 `Read-only default for newly attached
    agents on high-risk projects`。一條沒考過的線，狀態必須是不能寫。

二，**考卷裡沒有答案明文。** §39 第 2 步
    `Do not expose the canonical current-answer artifact yet`。
    測試直接去考卷的 JSON 裡找原文那段字，找得到就是壞了。

三，**題目來自原文，而且不只來自開頭。** 她的原話是
    「只挑標題重點看，掃描前幾排字後面就略過」。一份只考前面的考卷，
    考的正是那個壞習慣做得到的範圍。

四，**沒有來源的維度不編題。** `last_good` 沒有人標記的時候，
    要記成 `NO_SOURCE`，不准生一題出來讓數字好看。

五，**答錯就是 FAIL。** 這一條是整件事的理由：B-08 記的正是
    「閘門只列題目不驗答案」，所以驗不出錯的閘門等於沒有閘門。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import sufficiency as S  # noqa: E402


DOC = """# 規格

## 第一節

不准把沒有驗證過的數字直接寫進正式的交付文件裡面。
每一個結論至少要有三份互相獨立的證據才算數。

## 第二節

這一段是中間的內容，用來把文件撐長一點好驗證取樣有沒有跨區塊。
一行一行填滿，確保切塊器切得出不只一塊來。
再多寫一行，讓這一塊有足夠的行數不會被併進前一塊裡面去。
再一行。
再一行。
再一行。

## 第三節

禁止在沒有取得擁有者同意的情況下刪除任何既有的紀錄檔案。
另外規定重試的次數最多只能有五次，超過就要停下來回報。
"""


def _mkroot(tmp_path, *, with_last_good=True, cfg=None):
    """造一個最小的專案。五個維度的來源檔各給一份。"""
    fs = tmp_path / ".forseti"
    fs.mkdir(parents=True, exist_ok=True)
    for name in ("NORTH_STAR.md", "DECISION_LEDGER.md", "BLOCKERS.md"):
        (fs / name).write_text(DOC, encoding="utf-8")
    (tmp_path / "bible.md").write_text(DOC, encoding="utf-8")
    if with_last_good:
        (fs / "checkpoints.jsonl").write_text(json.dumps({
            "at": 1.0, "id": "cp-test", "n": 42, "last_good": True,
            "goal": "讓 AI 的工作狀態變成可觀測可驗證可控制可復原",
            "decisions": ["原檔一個位元組都不動，fork 是建立不是修改"],
            "unknowns": [], "verified": [],
        }, ensure_ascii=False) + "\n", encoding="utf-8")
    (fs / "config.json").write_text(
        json.dumps(cfg or {}, ensure_ascii=False), encoding="utf-8")
    return tmp_path


# ── 一　預設唯讀 ──────────────────────────────────

def test_沒考過的線預設不能寫(tmp_path):
    root = _mkroot(tmp_path)
    st = S.state(root, session="新來的")
    assert st["write"] is False
    assert st["attempts"] == 0
    assert "§19.2" in st["why"]


def test_沒開強制的時候不擋人但狀態照樣說實話(tmp_path):
    root = _mkroot(tmp_path)
    assert S.can_write(root, session="新來的") is True
    assert S.state(root, session="新來的")["write"] is False


def test_開了強制而且沒考過就擋住(tmp_path):
    root = _mkroot(tmp_path, cfg={"sufficiency_enforce": True})
    assert S.can_write(root, session="新來的") is False


# ── 二　考卷裡不可以有答案 ─────────────────────────

def test_考卷裡找不到答案明文(tmp_path):
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1")
    blob = json.dumps(exam, ensure_ascii=False)
    # 原文那幾段明確的答案，一個都不准出現在考卷裡。
    for secret in ("把沒有驗證過的數字直接寫進正式的交付文件",
                   "在沒有取得擁有者同意的情況下刪除",
                   "讓 AI 的工作狀態變成可觀測可驗證可控制可復原"):
        assert S._norm(secret) not in S._norm(blob)
    assert all("key" not in q for q in exam["questions"])
    assert all(q["key_sha"] and q["key_len"] for q in exam["questions"])


def test_帳本檔裡也找不到答案明文(tmp_path):
    root = _mkroot(tmp_path)
    S.open_exam(root, session="s1")
    raw = (root / ".forseti" / S.LOG_NAME).read_text(encoding="utf-8")
    assert S._norm("在沒有取得擁有者同意的情況下刪除") not in S._norm(raw)


# ── 三　題目來自原文，而且跨得出開頭 ───────────────

def test_題目跨得出第一塊(tmp_path):
    """整份文件都要考得到。只考開頭等於獎勵掃描前幾排字。"""
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1", per_dim=3)
    lines = [q["line"] for q in exam["questions"] if q["dim"] == "effects"]
    assert lines, "bible.md 這一維要出得了題"
    assert max(lines) > 10, f"題目全擠在開頭：{lines}"


def test_同一份文件出的卷不會每次都不一樣(tmp_path):
    """重考不是轉盤。每次抽不同的題，多考幾次就會過。"""
    root = _mkroot(tmp_path)
    a = S.compose(root)
    b = S.compose(root)
    assert [q["key_sha"] for q in a["questions"]] == \
           [q["key_sha"] for q in b["questions"]]


def test_答案太短的題不出(tmp_path):
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1", per_dim=4)
    assert all(q["key_len"] >= S.MIN_KEY_LEN for q in exam["questions"])


# ── 四　沒有來源就說沒有，不編 ─────────────────────

def test_沒有人標過last_good就記成沒有來源(tmp_path):
    root = _mkroot(tmp_path, with_last_good=False)
    paper = S.compose(root)
    assert paper["dims"]["last_good"]["state"] == "NO_SOURCE"
    assert not [q for q in paper["questions"] if q["dim"] == "last_good"]


def test_缺維度時全對只拿得到部分通過(tmp_path):
    root = _mkroot(tmp_path, with_last_good=False)
    exam = S.open_exam(root, session="s1")
    ans = _all_right(root, exam)
    res = S.submit(root, exam_id=exam["id"], answers=ans, session="s1")
    assert res["verdict"] == "PASS_PARTIAL"
    assert "last_good" in res["missing_dims"]
    assert S.state(root, session="s1")["write"] is True


# ── 五　答錯就是 FAIL ─────────────────────────────

def _all_right(root, exam):
    """照原文作答。測試自己要拿得到答案，所以從來源檔重算一次。

    這也順便證明了一件事：**這道門防的是錨定，不是作弊。**
    讀得到來源檔的人本來就答得出來，規格 §39 要的是別把答案
    直接端到受測者面前，不是假裝擋得住一個決心作弊的 session。
    """
    import blockread as BR
    out = {}
    for q in exam["questions"]:
        found = None
        srcs = [root / ".forseti" / "NORTH_STAR.md",
                root / ".forseti" / "DECISION_LEDGER.md",
                root / ".forseti" / "BLOCKERS.md",
                root / "bible.md"]
        for p in srcs:
            if not p.is_file():
                continue
            for b in BR.split(p):
                for cand in BR.quiz(p, b, limit=4):
                    if S._sha(S._norm(cand.get("key") or "")) == q["key_sha"]:
                        found = cand["key"]
                        break
                if found:
                    break
            if found:
                break
        if found is None:
            # last_good 那幾題的答案在 checkpoint 裡。
            cp = S._last_good(root) or {}
            for cand in [cp.get("goal", "")] + list(cp.get("decisions") or []):
                for cut in (40, 30):
                    if S._sha(S._norm(cand[:cut])) == q["key_sha"]:
                        found = cand[:cut]
                        break
                if found:
                    break
        out[q["qid"]] = found or ""
    return out


def test_全對而且五維齊全就通過(tmp_path):
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1")
    res = S.submit(root, exam_id=exam["id"],
                   answers=_all_right(root, exam), session="s1")
    assert res["verdict"] == "PASS", res
    assert res["rate"] == 1.0
    assert S.state(root, session="s1")["write"] is True


def test_全部答錯就是FAIL而且拿不到寫入權限(tmp_path):
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1")
    ans = {q["qid"]: "我不知道" for q in exam["questions"]}
    res = S.submit(root, exam_id=exam["id"], answers=ans, session="s1")
    assert res["verdict"] == "FAIL"
    assert res["rate"] == 0.0
    assert S.state(root, session="s1")["write"] is False


def test_一維答錯就整份不過(tmp_path):
    """門檻是逐維度算的，不是總分。

    總分制會讓一個完全沒讀某一份文件的人靠其他四維補回來，
    而 §17.3 列那五樣是因為少一樣就接不下去。
    """
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1")
    ans = _all_right(root, exam)
    for q in exam["questions"]:
        if q["dim"] == "effects":
            ans[q["qid"]] = "亂answer"
    res = S.submit(root, exam_id=exam["id"], answers=ans, session="s1")
    assert res["verdict"] == "FAIL"
    assert "effects" in res["why"]
    assert res["rate"] > 0.5, "其他維度是對的，總分仍然很高，但照樣不過"


def test_空白作答不會因為hash比對而誤判成對(tmp_path):
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1")
    res = S.submit(root, exam_id=exam["id"],
                   answers={q["qid"]: "" for q in exam["questions"]},
                   session="s1")
    assert res["right"] == 0


# ── 帳本本身 ─────────────────────────────────────

def test_交卷兩次兩筆都留著(tmp_path):
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1")
    S.submit(root, exam_id=exam["id"],
             answers={q["qid"]: "錯" for q in exam["questions"]}, session="s1")
    S.submit(root, exam_id=exam["id"],
             answers=_all_right(root, exam), session="s1")
    rs = S.Log(root).results("s1")
    assert len(rs) == 2
    assert rs[0]["verdict"] == "FAIL" and rs[1]["verdict"] == "PASS"
    assert S.state(root, session="s1")["attempts"] == 2


def test_別條線考過的不算這條線的(tmp_path):
    """§39 講的是 successor。換一條線就是換一個受測者。"""
    root = _mkroot(tmp_path)
    exam = S.open_exam(root, session="s1")
    S.submit(root, exam_id=exam["id"],
             answers=_all_right(root, exam), session="s1")
    assert S.state(root, session="s1")["write"] is True
    assert S.state(root, session="s2")["write"] is False


def test_交一份不存在的考卷會被擋掉(tmp_path):
    root = _mkroot(tmp_path)
    r = S.submit(root, exam_id="不存在", answers={}, session="s1")
    assert r["ok"] is False


# ── 門檻是設定值 ─────────────────────────────────

def test_門檻讀得到設定也擋得掉亂填的值(tmp_path):
    assert S.threshold(_mkroot(tmp_path, cfg={"sufficiency_threshold": 0.5})) == 0.5
    assert S.threshold(_mkroot(tmp_path / "b", cfg={"sufficiency_threshold": 9})) \
        == S.DEFAULT_THRESHOLD


def test_五個維度就是規格那一句列的五樣(tmp_path):
    """順序與內容都照 §17.3 原文，不增不減。"""
    assert [d[0] for d in S.DIMENSIONS] == [
        "objective", "decisions", "unknowns", "last_good", "effects"]
    assert [d[1] for d in S.DIMENSIONS] == [
        "current objective", "accepted decisions", "unresolved unknowns",
        "last-good state", "external-effect boundaries"]
