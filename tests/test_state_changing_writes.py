"""會改變狀態的那三個指令，寫出去的是不是只有該寫的那幾筆。

**2026-09-17 加這一組，補的是上一輪自己寫下的缺口。** 原話在
`AUTO_CONTINUE_LOG.md`：

    `STATE_CHANGING_CMDS` 那三個仍然沒有任何寫入守門。
    它們本來就該寫，所以白名單那套問法不適用 ——
    要守的是「寫的是不是只有該寫的那幾筆」，那是另一種測試，
    這一輪沒做。

`tests/test_forseti_dir_writes.py` 守的是十七個唯讀指令，問法是
「有沒有寫出白名單以外的東西」，而且容許零次寫入 —— 因為唯讀指令
本來就可能一個字都不寫。**這一組問的是相反的那一題**：這三個一定會寫，
所以零次寫入反而是壞掉，要驗的是位置對不對、有沒有順手多寫別的。

## 三個怎麼在不改變 owner 狀態的前提下真的跑

一，`note_add`（粉紅點）與 `act checkpoint`：把模組層級那個常數
    （`notes.LOG`、`checkpoint.LOG`）改到臨時目錄。兩支都吃
    `path=` 參數，但 `desktop_api` 從來不傳，所以搬常數是唯一
    攔得住的地方。**搬走之後真實檔案一個字都不會多**，
    而每一條都另外釘住「那個常數本來指到哪裡」——
    不釘的話，哪天有人把它搬出 `.forseti/`，這一組會繼續全綠。

二，`fork`：不走 `desktop_api.fork_at()`，走它底下真正寫檔的
    `forkline.fork()`，餵一個臨時目錄裡自己造的 session 檔。
    理由是 `fork_at` 只認 `~/.claude/projects/` 底下的東西
    （`desktop_api.py:1702` 的 glob），在那裡造檔會讓一條假 session
    出現在她的側邊欄。

## 這一組自己的弱點，寫在這裡不是補充是前提

它靠 `test_forseti_dir_writes._WriteSpy` 那張網。網瞎掉的時候
「沒寫別的」會無聲通過。守那張網的是那個檔案裡的三條自我測試
（`test_攔截網蓋得到handoff實際用的那種寫法`、
`test_攔截網蓋得到PathOpen這種寫法`、
`test_用builtins_open攔不到PathOpen這件事本身`）。
**那三條刪掉的話，這一整個檔案就變成裝飾品。**

刻意不自己複製一份網：複製出來的兩份會分歧，而分歧的那天
兩邊都還是綠的。
"""

from __future__ import annotations

import ast
import json
import sys
import uuid as _uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

from test_forseti_dir_writes import (            # noqa: E402
    ALLOWED_TOP, FORSETI, STATE_CHANGING_CMDS, _WriteSpy,
)


# --------------------------------------------------------------- 覆蓋率
#
# 分派表新增一個會改變狀態的指令，下面這條會紅。沒有它的話，
# 新增的那個只要被分類進 `STATE_CHANGING_CMDS` 就完全沒有人看 ——
# 而那正是它被放進那一組的理由（唯讀那條 parametrize 不跑它們）。

#: 這個檔案實際守到的指令。**跟 `STATE_CHANGING_CMDS` 必須一模一樣。**
GUARDED_HERE = frozenset({"note_add", "act", "fork"})


def test_每一個會改變狀態的指令在這裡都有人守():
    """`STATE_CHANGING_CMDS` 多一個，這裡就要多一組測試。

    唯讀那十七個有 parametrize 逐個問過，這三個沒有 ——
    它們被排除在那條 parametrize 之外的理由是「一條測試不該替她按」，
    而那個理由**只擋得住『照原樣跑一次』，擋不住『完全不看』**。
    這一條把那個差別變成會紅的東西。
    """
    missing = STATE_CHANGING_CMDS - GUARDED_HERE
    stale = GUARDED_HERE - STATE_CHANGING_CMDS
    assert not missing, (
        f"{sorted(missing)} 被分類成會改變狀態，但這個檔案沒有守它。"
        "會改變狀態代表它一定會寫東西 —— 沒有人看的話，"
        "它哪天多寫一個檔不會有任何地方紅。"
    )
    assert not stale, (
        f"{sorted(stale)} 在這裡守著，但它已經不在 STATE_CHANGING_CMDS 裡了。"
        "指令被刪掉、改名、或改成唯讀了，兩邊要一起改。"
    )


# ------------------------------------------------------- note_add 粉紅點

def test_粉紅點的預設位置就在控制目錄底下():
    """釘住下面那條搬走的是什麼。

    **這一條是下面那條的前提。** 下面那條把 `notes.LOG` 搬到臨時目錄
    才敢真的跑，而「搬走」只有在知道原本在哪的時候才是誠實的。
    哪天有人把粉紅點搬出 `.forseti/`，這一條會紅，
    那時候要回答的是「使用者親手寫的那唯一一種證據，
    為什麼不放在控制目錄裡」，不是把這條改掉。
    """
    import notes as NT

    assert NT.LOG.resolve() == (FORSETI / "notes.jsonl"), (
        f"粉紅點現在寫在 {NT.LOG}，不是 .forseti/notes.jsonl"
    )
    assert "notes.jsonl" not in ALLOWED_TOP, (
        "`notes.jsonl` 跑進唯讀指令的白名單了。粉紅點是 owner 按下去"
        "才該出現的東西 —— 它出現在唯讀路徑上代表有東西在替她寫。"
    )


def test_粉紅點只寫那一個檔案(tmp_path, monkeypatch):
    """`add_note()` 寫一則注記，整個檔案系統上只准動那一個檔。

    2026-09-17 實測：改掉 `notes.LOG` 之後跑一次，全檔案系統範圍
    攔到 **1 次**，`Path.open:a`，落在改過去的那個檔上。
    在 `Path.open` 補進攔截網之前這裡會量到 0 次 —— 那是假陰性，
    不是「它不寫」（`notes.py:67` 用的正是 `p.open("a")`）。
    """
    import desktop_api as D
    import notes as NT

    log = tmp_path / "notes.jsonl"
    monkeypatch.setattr(NT, "LOG", log)

    with _WriteSpy(scope=None) as spy:
        r = D.add_note("sess-for-test", 1, "守門測試寫的，不是 owner 按的")

    assert r.get("ok"), f"連寫都沒寫成功：{r}"
    assert spy.paths() == {str(log.resolve())}, (
        f"除了 {log.name} 以外還動了 {sorted(spy.paths() - {str(log.resolve())})}。"
        "粉紅點是只增不改的一行 jsonl，它沒有理由順手寫別的東西。"
    )
    lines = [x for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1, f"寫了 {len(lines)} 行，一則注記應該只有一行"
    assert json.loads(lines[0])["provenance"] == "HUMAN_ADJUDICATION"


# ---------------------------------------------------------- act checkpoint

def test_checkpoint的預設位置就在控制目錄底下():
    """跟粉紅點那一條同一個理由：先釘住搬走的是什麼。"""
    import checkpoint as CP

    assert CP.LOG.resolve() == (FORSETI / "checkpoints.jsonl"), (
        f"checkpoint 現在寫在 {CP.LOG}，不是 .forseti/checkpoints.jsonl"
    )
    assert "checkpoints.jsonl" not in ALLOWED_TOP, (
        "`checkpoints.jsonl` 跑進唯讀指令的白名單了。"
        "`last_good` 只能由人明確標記（`checkpoint.py` 模組說明），"
        "它出現在唯讀路徑上代表系統開始自己挑了。"
    )


def test_act標記checkpoint只落一筆而且不碰控制檔以外的東西(tmp_path, monkeypatch):
    """`act("checkpoint")` 是她按「標記這裡是好的」那一下。

    **這一條會真的跑完整條路。** `act` 走 `_checkpoint_now()`
    （`desktop_api.py:1869`），而它內部呼叫 `strands()` 拿座標 ——
    所以順帶會發生 `strands()` 平常每一輪本來就在做的寫入
    （`cache/` 底下三支快取、節流沒擋住的話還有 `NEXT.md`）。
    那些在 `ALLOWED_TOP` 裡，**不在裡面的一個都不准有**。

    2026-09-17 實測一次（`checkpoint.LOG` 改到臨時目錄）：
    `.forseti/` 底下被動的是 `cache/identity.json` 與它的 `.tmp`，
    那一次 `NEXT.md` 因為 `MIN_GAP_S` 沒到所以沒寫 ——
    **所以這一條不斷言 `NEXT.md` 一定被寫**，零次是合法狀態。

    另外釘一件事：**帳本不准被碰。** `act("checkpoint")` 在
    `desktop_api.py` 裡是在開帳本之前就 return 的那一支
    （`kind == "checkpoint"` 那個分支），所以 `~/.forseti/ledgers/`
    底下一個位元組都不該動。它要是動了，代表標記這個動作偷偷
    改了任務狀態，而那是 owner 沒有按的東西。
    """
    import checkpoint as CP
    import desktop_api as D
    import ledger as L

    log = tmp_path / "checkpoints.jsonl"
    monkeypatch.setattr(CP, "LOG", log)
    ledger_dir = str(L.default_db().parent.resolve())

    with _WriteSpy(scope=None) as spy:
        r = D.act("checkpoint")

    assert r.get("ok"), f"標記沒成功：{r}"

    assert str(log.resolve()) in spy.paths(), (
        "checkpoint 檔一次都沒被寫。`act('checkpoint')` 回 ok 卻沒落檔，"
        "代表回傳說謊 —— 或者常數搬錯地方，這一條量到的不是真的那一支。"
    )
    lines = [x for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(lines) == 1, (
        f"落了 {len(lines)} 筆 checkpoint。按一次只該有一筆 —— "
        "多的那幾筆會讓「回到哪一個」自己變成一個要花力氣回答的問題。"
    )
    row = json.loads(lines[0])
    assert row["reason"] == "OWNER_MARK" and row["last_good"] is True

    touched_ledger = [p for p in spy.paths() if p.startswith(ledger_dir)]
    assert not touched_ledger, (
        f"標記 checkpoint 動到了任務帳本 {touched_ledger}。"
        "這個動作在開帳本之前就 return，它碰帳本代表有別的東西"
        "搭著這個按鈕改任務狀態。"
    )

    under = {p for p in spy.paths() if p.startswith(str(FORSETI))}
    extra = {Path(p).relative_to(FORSETI).parts[0] for p in under} - ALLOWED_TOP
    assert not extra, (
        f"在 .forseti/ 底下寫了白名單以外的 {sorted(extra)}。"
        "要加就改 ALLOWED_TOP，順便回答那個檔為什麼非得放這裡。"
    )


# ------------------------------------------------------------------ fork

def _make_session(dirpath: Path) -> Path:
    """造一條最小的 session。四個對話節點加一行沒有 uuid 的 header。

    header 那一行是刻意的：`forkline.fork()` 對它有專門的處理
    （`forkline.py:145` 那段註解講的「header 也要跟著行號截斷」），
    沒有它的話這條測試走不到那段分支。
    """
    p = dirpath / f"{_uuid.uuid4()}.jsonl"
    rows = [
        {"type": "summary", "summary": "這一行沒有 uuid"},
        {"uuid": "u1", "parentUuid": None, "sessionId": "S", "type": "user"},
        {"uuid": "u2", "parentUuid": "u1", "sessionId": "S", "type": "assistant"},
        {"uuid": "u3", "parentUuid": "u2", "sessionId": "S", "type": "user"},
        {"uuid": "u4", "parentUuid": "u3", "sessionId": "S", "type": "assistant"},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_fork乾跑一個位元組都不寫(tmp_path):
    """乾跑就是不寫，這件事先前完全沒有人守。

    **`fork` 預設乾跑，而預設值是它唯一的防線。**
    `desktop_api.py:3713` 那行是 `dry_run="--go" not in argv`，
    也就是說沒有人按 `--go` 的時候，安全與否完全取決於
    `forkline.fork()` 真的不寫。那件事到這一輪為止沒有任何測試在看。

    2026-09-17 實測：乾跑全檔案系統範圍 **0 次寫入**，目錄裡仍然
    只有來源那一個檔。
    """
    import forkline as FK

    src = _make_session(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())

    with _WriteSpy(scope=None) as spy:
        info = FK.fork(src, 3, dry_run=True)

    assert info["dry_run"] is True
    assert info["new_session_id"], "連新 id 都沒算出來，代表它根本沒走到"
    assert spy.paths() == set(), (
        f"乾跑寫了 {sorted(spy.paths())}。乾跑會寫的話，"
        "那個預設值就不是防線是裝飾。"
    )
    assert sorted(p.name for p in tmp_path.iterdir()) == before, (
        "乾跑之後目錄內容變了"
    )


def test_fork真的寫的時候只寫新檔而且原檔一個位元組都不動(tmp_path):
    """`forkline.py` 檔頭那句「原檔一個位元組都不動」，現在有人驗。

    那句話的理由寫在原始碼裡：**一個會改到原始對話的 fork，
    等於把「回頭看當時發生什麼」毀掉**，而那正是整個 Widget
    存在的理由。先前它只是一句註解。

    2026-09-17 實測：真跑一次全檔案系統範圍 **1 個相異位置**，
    就是 `dest`，用 `Path.open:w` ——
    在 `Path.open` 補進攔截網之前，這裡會量到 0 次，
    於是這條測試會用一個假陰性宣告「它什麼都沒寫」。
    """
    import forkline as FK

    src = _make_session(tmp_path)
    src_bytes = src.read_bytes()

    with _WriteSpy(scope=None) as spy:
        info = FK.fork(src, 3, dry_run=False)

    dest = Path(info["dest"])
    assert spy.paths() == {str(dest.resolve())}, (
        f"除了新檔以外還動了 "
        f"{sorted(spy.paths() - {str(dest.resolve())})}"
    )
    assert src.read_bytes() == src_bytes, (
        "原檔被改了。fork 是建立不是修改 —— 改到原檔的話，"
        "出事之後就沒有東西可以回頭對照。"
    )
    assert dest.exists() and dest.parent == src.parent
    out = [json.loads(x) for x in
           dest.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(out) == info["kept"] + info["headers"]
    assert all(r.get("sessionId") in (None, info["new_session_id"])
               for r in out), "新檔裡還留著舊的 sessionId"


def test_畫面上的fork預設是乾跑():
    """從語法樹讀那個預設值，不是讀註解。

    **這一條跟上面兩條守的不是同一件事。** 上面兩條守
    `forkline.fork()` 的行為，這一條守分派表有沒有把
    `dry_run` 接對 —— 兩邊都對才安全。哪天有人把
    `dry_run="--go" not in argv` 寫成 `dry_run=False`，
    上面兩條仍然全綠，只有這一條會紅。
    """
    src = (ROOT / "apps" / "forseti-cli" / "desktop_api.py").read_text(
        encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "fork_at"]
    assert len(calls) == 1, f"`main()` 裡有 {len(calls)} 個 fork_at 呼叫"
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert "dry_run" in kw, (
        "分派表呼叫 `fork_at` 的時候沒有給 `dry_run`。"
        "函式簽章的預設是 True，但靠簽章等於靠另一個檔案的預設值 —— "
        "一個手滑就產生檔案的指令，那個值要在呼叫點看得到。"
    )
    assert "--go" in ast.dump(kw["dry_run"]), (
        f"`dry_run` 不是由 `--go` 決定的，而是 {ast.dump(kw['dry_run'])[:80]}。"
        "真的要寫檔必須明講 --go，不然遲早會在沒人打算 fork 的時候產生檔案。"
    )


@pytest.mark.parametrize("kind", ["finish", "verify", "dispatch", "drain"])
def test_act其餘四種動作沒有target一律拒絕而且不寫東西(kind):
    """拒絕的那條路上不准有寫入。

    **`act` 的五種裡有四種需要 target，而拒絕發生在開帳本之後。**
    （`desktop_api.py:2296` 先擋沒有 target，才走到 `L.Ledger()`。）
    這四種在這裡用空 target 跑，驗的是同一件事：
    被拒絕的動作不留下任何痕跡。

    一個「做不動」卻順手寫了東西的動作，是最難查的那種 ——
    畫面上她看到的是失敗，檔案系統上卻已經變了。
    """
    import desktop_api as D

    with _WriteSpy(scope=None) as spy:
        r = D.act(kind, "")

    assert r.get("ok") is False, f"空 target 竟然成功了：{r}"
    assert spy.paths() == set(), (
        f"`act({kind})` 被拒絕了卻寫了 {sorted(spy.paths())}。"
        "拒絕就要什麼都不留 —— 不然畫面說失敗、檔案說成功。"
    )


def test_標記那一下碰得到正本交接檔_所以它在冊(tmp_path, monkeypatch):
    """`act("checkpoint")` 會走到正本 `NEXT.md` 的寫入閘門。

    **這一條釘的是 `test_zz_forseti_write_attribution.py` 那張名單裡
    這個檔的登記理由**，不是行為本身。登記的話是「這個檔碰得到正本」，
    而一個沒有人守的登記理由，哪天路徑變了就會變成過期的說法。

    ## 為什麼這個檔以前不在冊，而這件事是怎麼查出來的

    2026-09-17 18:4x 到 18:5x 查那兩條間歇紅的成因時量出來的。
    那張名單有兩個來源，**兩個的盲區重疊在這個檔上**：

    一，觀測（跑一輪看誰動到正本）。`NEXT.md` 的節流是 240 秒，
        所以一輪裡最多一兩條寫得成，看得見的永遠是贏了競速的那一條。

    二，`_scan_strands_callers()`。它掃的是**直接**呼叫 `strands()` 的
        地方，而這一條隔著兩層：`act("checkpoint")`
        （`desktop_api.py:2308`）→ `_checkpoint_now:1892` → `:1901` 的
        `_safe(strands, {})`。那支掃描器自己的 docstring 就寫著
        看不到間接一層以上的呼叫，所以這不是它壞了，是它的範圍。

    兩邊都看不到的結果是：節流窗剛好開在這一條測試身上的那幾輪，
    `test_NEXT_md的寫入次數不超過節流窗開過的次數` 會紅在
    「寫了 NEXT.md 但不在冊」，其餘的輪次全綠。
    **2026-09-17 18:5x 讓窗開著重跑兩個檔，紅的正是那一條、
    理由正是那一句** —— 不是推論出來的形狀。

    ## 走到閘門的是三條路，不是一條

    第一次寫這條測試的時候，理由寫的是
    「`_checkpoint_now:1901` 的 `_safe(strands, {})`」，一條。
    **反向驗證當場推翻了它**：把那一行改成 `snap = {}`，
    這一條照樣全綠。印出堆疊之後才看到真正的形狀：

        _checkpoint_now:1901 → strands:3441 → _write_handoff:1807
        _checkpoint_now:1926 → audit:733 → strands:3441 → 同上
        _checkpoint_now:1926 → audit:739 → strands:3441 → 同上

    三條共用的出口是 `strands()` 尾段 `:3441` 的 `_write_handoff(snap)`。
    **所以這一條的反向驗證要斷在那裡**，斷任何一條上游都紅不起來 ——
    斷 `:3441` 實測只紅這一條，同檔另外 12 條全綠。

    記下來是因為這個形狀會再犯：一次觀測看到一條路，就把它寫成那條路。
    量到的是「走得到」，不是「怎麼走到的」。

    ## 這一條自己不寫正本

    `should_write` 被換成「記下目標、回 False」。回 False 是
    `write()` 那一層的擋法（`handoff.py:265`），所以整條路照樣走完，
    只是最後不落檔。**不改成攔 `write()`**：那樣就分不出
    「走到了閘門但被節流擋住」跟「根本沒走到」，而這一條要驗的正是前者。
    """
    import checkpoint as CP
    import desktop_api as D
    import handoff as HO

    monkeypatch.setattr(CP, "LOG", tmp_path / "checkpoints.jsonl")

    seen: list[str] = []
    orig = HO.should_write

    def spy(path=None, *a, **k):
        # **記的是「有沒有帶 path」，不是帶的值。** 原本這裡在 path 是
        # None 的時候記 `str(HO.OUT)`，然後下面拿 `str(HO.OUT)` 去比 ——
        # 同一個值跟自己比，那條斷言恆真，換句話說它守不到任何東西。
        # 2026-09-18 發現並改掉。
        seen.append("<default>" if path is None else str(path))
        return False

    monkeypatch.setattr(HO, "should_write", spy)
    try:
        D.act("checkpoint")
    finally:
        monkeypatch.setattr(HO, "should_write", orig)

    assert seen, (
        "`act('checkpoint')` 一次都沒走到交接檔的寫入閘門。"
        "路徑變了的話，`test_zz_forseti_write_attribution.py` 那張名單裡"
        "`tests/test_state_changing_writes.py` 那一筆的登記理由就過期了 —— "
        "回去改那裡的說明，不要改這一條讓它閉嘴"
    )
    assert "<default>" in seen, (
        f"走到閘門了，但帶了自己的路徑：{seen}　"
        "不帶 path 才落在 `handoff.OUT` 這個模組全域上 —— 那個全域"
        "正式執行時是正本、跑測試時被導到暫存"
        "（`tests/test_handoff_out_redirect.py`）。帶了自己的路徑的話"
        "它就不再碰那條路，那時候該做的是把它從"
        "`test_zz_forseti_write_attribution.py` 那張名單上拿掉，"
        "不是留著一筆不成立的登記"
    )
