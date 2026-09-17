"""反錨定接手協議的 CLI 入口。v5.0 §39 第 3 到第 6 步

`antianchor.py` 2026-09-17 寫好的那一輪自己記著「它現在是一個可呼叫
但沒有入口的模組。這是缺口，不是設計」，而 `forseti.py` 的模組說明
最後一句是「一個沒有入口的機制等於不存在」。這一組守的是那個入口。

守四件事，每一件都對著一種「入口看起來有，其實把整套廢掉」的失效：

一，**考卷上不准出現正典的值。** §39 第 2 步整條就是這一句。
    印出來的那一頁只要漏出任何一欄的答案，後面五步全部作廢，
    而那是印錯一行就會發生的事，所以這一條排第一。

二，**CLI 不准繞過順序。** 沒交推導 `reveal` 要擋、交過一次
    `submit` 要擋、沒 `--by` 的 `classify` 要擋。API 層擋住而
    CLI 層自己補一條路，等於沒擋。

三，**`forseti antianchor` 真的轉得到這一支。** 指令名打錯、
    dispatch 沒接上，症狀是印出 usage 然後回 2，不會有錯誤訊息。

四，**`state` 那一欄拿得到值。** 模組說明寫著它借 `snap["verified"]`，
    而 `strands()` 的 snap **沒有這個 key**（那個 key 只存在於
    `_write_handoff()` 的區域變數裡）。照說明去拿的人拿到的永遠是空的，
    於是四欄全部 unanswerable，一場什麼都沒驗到的考試。
    2026-09-17 抽出 `desktop_api.verified_lines()` 修掉，這一條釘住它。
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import antianchor as AA  # noqa: E402


#: 假的當下狀態。四欄裡兩欄有值，好讓「答案不准出現在考卷上」
#: 這一條有東西可以找 —— 四欄都空的話那條測試會永遠通過。
FAKE_SNAP = {"verified": ["必讀文件 20/30 讀完", "checkpoint 3 個"]}
FAKE_WORK = {
    "blocked": ["B-XX　這是正典裡的阻塞字串"],
    "tasks": [{"id": "T-cli", "next_step": {"objective": "這是正典裡的下一步"}}],
}


@pytest.fixture()
def live(monkeypatch):
    """把 `_live()` 換掉。

    真的那一支會去叫 `desktop_api.strands()`，那要 5 秒而且會重寫
    `.forseti/NEXT.md`。測試要的是 CLI 這一層的行為，不是 snap 怎麼算的。
    """
    monkeypatch.setattr(AA, "_live", lambda root: (FAKE_SNAP, FAKE_WORK))
    monkeypatch.setattr(AA, "_session", lambda rest: "cli-test")
    return None


def run(argv, root, stdin: str = "") -> tuple[int, str]:
    if stdin:
        sys.stdin = io.StringIO(stdin)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            code = AA.main([*argv, "--root", str(root)])
    finally:
        sys.stdin = sys.__stdin__
    return code, buf.getvalue()


def _open(root) -> tuple[str, str]:
    code, out = run(["open"], root)
    assert code == 0, out
    rows = AA.Log(root).all()
    did = [r for r in rows if r["kind"] == "OPEN"][-1]["id"]
    return did, out


# ---------------------------------------------------------------------------
# 一，考卷上不准出現正典的值
# ---------------------------------------------------------------------------

def test_考卷上不准出現任何一欄的正典值(live, tmp_path):
    """§39 第 2 步。這一條漏掉的話，後面五步全部是流程表演。

    找的是正典字串本身，不是欄位名稱 —— 欄位名稱本來就該印出來。
    """
    _did, out = _open(tmp_path)
    can = AA.canonical(FAKE_SNAP, FAKE_WORK, tmp_path)
    leaked = []
    for k, f in can["fields"].items():
        for v in (f.get("value") or []):
            if str(v) and str(v) in out:
                leaked.append((k, v))
    assert not leaked, f"考卷上漏出正典的值：{leaked}"


def test_考卷會說出哪幾欄沒有正典可以對(live, tmp_path):
    """兩邊都空不算答對，而受測者要在**交卷之前**就知道哪幾欄是那樣。

    事後才在揭曉那一頁說，等於讓人先白推導一輪。
    """
    _did, out = _open(tmp_path)
    assert "priority_order" in out
    assert "沒有正典可以揭曉" in out, out


def test_四欄一欄都對不了的時候考卷要自己講出來(monkeypatch, tmp_path):
    monkeypatch.setattr(AA, "_live", lambda root: ({}, {}))
    monkeypatch.setattr(AA, "_session", lambda rest: "cli-empty")
    _did, out = _open(tmp_path)
    assert "一欄都沒有正典可以對" in out, out


def test_空欄位的理由不准印在考卷上(monkeypatch, tmp_path):
    """**為什麼空，本身就是答案。**

    2026-09-17 對真正的 repo 跑 `open` 的時候抓到的：`next_action`
    那一欄的理由寫著「2 件任務的步驟全部驗證完成了，所以沒有東西可以派」，
    印在考卷上等於把第 3 步要人自己推的那一欄直接告訴他。

    上面那條「不准出現正典的值」抓不到這個 —— 空欄位的 `value` 是 None，
    比對字串永遠找不到東西，所以那條測試會一路綠著讓答案漏出去。
    這一條守的是**理由那一段**，不是值。

    `NO_SOURCE` 的理由照印：那一句講的是「§41 的 triage 引擎沒有實作」，
    是結構不是內容，而不講的話受測者會白推導一欄。
    """
    monkeypatch.setattr(AA, "_session", lambda rest: "cli-empty-why")
    # blockers 有來源而此刻空的（work 裡沒有 blocked），
    # priority_order 則是永遠 NO_SOURCE。
    monkeypatch.setattr(AA, "_live", lambda root: ({}, {}))
    _did, out = _open(tmp_path)

    can = AA.canonical({}, {}, tmp_path)
    for k, f in can["fields"].items():
        why = (f.get("why") or "").strip()
        if not why:
            continue
        if f["state"] == AA.EMPTY:
            assert why[:40] not in out, f"{k} 的「為什麼空」漏在考卷上"
        if f["state"] == AA.NO_SOURCE:
            assert why[:30] in out, f"{k} 的結構性理由該印而沒印"


def test_考卷要講出這道門擋不住什麼(live, tmp_path):
    """防不了偷看，而且 open 這個動作自己會重寫 NEXT.md。

    兩件都是事實，寫在模組說明裡而沒印在用的人眼前，等於沒寫。
    """
    _did, out = _open(tmp_path)
    assert "偷看" in out
    assert "NEXT.md" in out, out


# ---------------------------------------------------------------------------
# 二，CLI 不准繞過順序
# ---------------------------------------------------------------------------

def test_沒交推導CLI照樣不准揭曉(live, tmp_path):
    did, _ = _open(tmp_path)
    code, out = run(["reveal", did], tmp_path)
    assert code == 2
    assert "還沒交推導" in out, out


def test_推導交過一次CLI就不准再交(live, tmp_path):
    did, _ = _open(tmp_path)
    code, _ = run(["submit", did], tmp_path, stdin=json.dumps({"state": ["x"]}))
    assert code == 0
    code2, out2 = run(["submit", did], tmp_path,
                      stdin=json.dumps({"state": ["改一個"]}))
    assert code2 == 2
    assert "只能交一次" in out2, out2


def test_沒有by的分類CLI要擋(live, tmp_path):
    did, _ = _open(tmp_path)
    run(["submit", did], tmp_path, stdin=json.dumps({"state": ["推錯的答案"]}))
    run(["reveal", did], tmp_path)
    code, out = run(["classify", did, "state", "STALE_CANONICAL"], tmp_path)
    assert code == 2
    assert "必填" in out, out


def test_不是四類之一的字串CLI要擋(live, tmp_path):
    did, _ = _open(tmp_path)
    run(["submit", did], tmp_path, stdin=json.dumps({"state": ["推錯的答案"]}))
    run(["reveal", did], tmp_path)
    code, out = run(["classify", did, "state", "看起來像別人的問題",
                     "--by", "人"], tmp_path)
    assert code == 2


def test_讀不懂的推導不准當成白卷收下(live, tmp_path):
    """交一段壞掉的 JSON 而被當成空推導收下，是最難發現的一種：

    帳本上會留下一筆合法的 DERIVED，而受測者以為自己交出去的是別的東西。
    """
    did, _ = _open(tmp_path)
    code, _ = run(["submit", did], tmp_path, stdin="{這不是 JSON")
    assert code == 2
    assert AA.Log(tmp_path).latest(did, "DERIVED") is None


# ---------------------------------------------------------------------------
# 三，走得完一次完整的流程
# ---------------------------------------------------------------------------

def test_一次完整的流程走得完而且和解會完成(live, tmp_path):
    did, _ = _open(tmp_path)
    run(["submit", did], tmp_path,
        stdin=json.dumps({"state": ["我推出來的跟正典不一樣"]}))
    code, out = run(["reveal", did], tmp_path)
    assert code == 0
    assert "DIFFERENT" in out, out

    rec = AA.reconciliation(tmp_path, derivation_id=did)
    assert rec["reconciled"] is False, "有差異沒分類，不准算和解完成"

    # **沒答的欄也是差異。** 三欄有正典而受測者只答了一欄，
    # 另外兩欄是「有正典、受測者沒答」，那一樣要分類 ——
    # 不分類就算和解完成的話，交白卷是最快的過關法。
    need = rec["unclassified"]
    assert len(need) > 1, f"這組的前提是不只一欄要分類，實際 {need}"
    for i, f in enumerate(need):
        code, _ = run(["classify", did, f, "SUCCESSOR_REASONING_ERROR",
                       "--by", "測試", "--reason", "推錯了"], tmp_path)
        assert code == 0, f
        left = AA.reconciliation(tmp_path, derivation_id=did)["reconciled"]
        assert left is (i == len(need) - 1), \
            f"分到第 {i + 1} 欄就說和解完成了，剩下 {need[i + 1:]}"

    code, out = run(["show", did], tmp_path)
    assert code == 0
    assert "和解完成　是" in out, out


def test_status在還沒走過的時候說得出來(live, tmp_path):
    code, out = run(["status"], tmp_path)
    assert code == 0
    assert "還沒走過" in out, out


def test_沒帶推導編號的指令回2不是炸掉(live, tmp_path):
    for sub in ("submit", "reveal", "show"):
        code, _ = run([sub], tmp_path)
        assert code == 2, sub


# ---------------------------------------------------------------------------
# 四，dispatch 真的接上了
# ---------------------------------------------------------------------------

def test_forseti_antianchor轉得到這一支(monkeypatch):
    """dispatch 沒接上的症狀是印 usage 回 2，不會有錯誤訊息。"""
    import forseti

    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(AA, "main", fake_main)
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = forseti.main(["forseti", "antianchor", "status"])
    assert code == 0, buf.getvalue()
    assert seen.get("argv") == ["status"], seen


def test_用法那一段有這個指令():
    """`forseti.py` 打錯指令會印 `__doc__`，那一段是唯一的目錄。"""
    import forseti
    assert "antianchor" in (forseti.__doc__ or "")


# ---------------------------------------------------------------------------
# 五，state 那一欄拿得到值
# ---------------------------------------------------------------------------

def test_strands的snap沒有verified這個key():
    """釘住這個缺口的成因本身。

    哪天 `strands()` 自己回了 `verified`，這一條會紅，
    而那時候要做的是把 `_live()` 的補值拿掉，不是改這條測試 ——
    兩個來源同時存在，才是真的會分歧。
    """
    import desktop_api as D
    import inspect
    src = inspect.getsource(D.strands)
    assert '"verified"' not in src, (
        "strands() 開始回 verified 了，_live() 的補值要拿掉")


def test_verified_lines跟交接檔用的是同一支():
    """`_write_handoff()` 必須是**叫**這一支，不是自己再算一份。

    自己再算一份的話，交接檔上的「已驗證的狀態」跟考卷的正典
    會各自漂移，而漂移那天不會有錯誤訊息。
    """
    import desktop_api as D
    import inspect
    src = inspect.getsource(D._write_handoff)
    assert "verified_lines(snap)" in src, src[:400]


def test_verified_lines兩個來源都空就回空清單():
    import desktop_api as D
    assert D.verified_lines({}) == []
    assert D.verified_lines({"spec": {"has": False}, "checkpoints": {}}) == []


def test_verified_lines拿得出必讀進度與checkpoint():
    import desktop_api as D
    got = D.verified_lines({"spec": {"has": True, "full": 20, "total": 30},
                            "checkpoints": {"total": 3}})
    assert got == ["必讀文件 20/30 讀完", "checkpoint 3 個"]


def test_補上verified之後state那一欄才有正典():
    """這一條是上面那個缺口的終點：補值前 answerable 是空的。"""
    import desktop_api as D
    snap = {"spec": {"has": True, "full": 20, "total": 30}, "checkpoints": {}}
    before = AA.canonical(snap, {}, ROOT)
    assert "state" not in before["answerable"], "補值前不該有正典"
    after = AA.canonical({**snap, "verified": D.verified_lines(snap)}, {}, ROOT)
    assert "state" in after["answerable"], after["fields"]["state"]
