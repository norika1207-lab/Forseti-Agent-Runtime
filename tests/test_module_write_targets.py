"""那十三個 `Path.open` 寫入點，各自實際寫到哪裡。

**2026-09-17 加這一組，補的是連續三輪被寫下來、連續三輪沒動的那一件。**
原話在 `AUTO_CONTINUE_LOG.md`（5af 與 5ag 兩輪都寫過）：

    那 13 個 `Path.open` 寫入點只走過 3 個，另外十支
    （`advicetrack`、`blockread`、`commit`、`coverage`、`event_ledger`、
    `gate`、`identity`、`pollution`、`sufficiency`、`workflow`）
    實際寫到哪裡沒有量。

走過的那三個是 `notes.py:67`、`checkpoint.py:79`、`forkline.py:178`，
守在 `tests/test_state_changing_writes.py`。它們會被守到，是因為
`desktop_api` 的三個會改變狀態的指令剛好會呼叫它們 ——
**其餘十支沒有任何指令會走到，所以那條路上的測試永遠看不到它們。**
這一組不從指令那一端進去，直接對模組的公開寫入 API 問同一題。

## 問的是哪一題

「餵它一個臨時目錄之後，整個檔案系統上被動到的是不是只有該動的那一個。」

不是「它有沒有寫」（那個一看就知道），是**有沒有順手寫別的**：
寫進 repo 的 `.forseti/`、寫進家目錄、寫進當前工作目錄。
這三種洩漏共同的性質是：在開發機上看起來一切正常，
因為那些位置本來就有東西，多一個檔沒有人會發現。

## 量出來的結果（2026-09-17 實測，十支全部）

十支各呼叫一次公開寫入 API，`_WriteSpy(scope=None)` 攔全檔案系統：
每一支都只攔到 **1 次**，落在餵進去的臨時目錄底下，零外洩。
所以這一組現在全綠 —— **它的價值不在今天，在有人改壞它的那天。**

## 量的時候踩到一個假陰性，寫在這裡

第一次量 `pollution.record()` 得到 **0 次寫入**，看起來像「它不寫檔」。
實際是漏傳 `radius_basis`，於是在 `pollution.py:150` 就 `return` 了。
跟 5af 那一輪 `fork_at` 的 0 次同一個形狀：
**提早 return 的零，跟「它不寫」的零長得一樣。**
所以下面每一條都另外斷言「至少寫了一次」——
零次在這一組裡一律是壞掉，不是通過。

## 這一組自己的兩個弱點，是前提不是補充

一，它靠 `test_forseti_dir_writes._WriteSpy` 那張網。網瞎掉的時候
    「沒寫別的」會無聲通過。守那張網的是那個檔案裡的三條自我測試。

二，**那張網攔不到 sqlite3 的寫入。** 2026-09-17 實測：
    `EventLedger.reindex()` 在家目錄建出 4096 位元組的 db 檔，
    而 spy 攔到的路徑裡沒有它（sqlite3 在 C 層開檔，
    不經過 `builtins.open` 也不經過 `Path.open`）。
    下面 `test_攔截網攔不到sqlite這件事本身` 把這個前提釘住，
    免得有人把這裡的「零外洩」讀成「連索引都沒外洩」。
"""

from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

from test_forseti_dir_writes import FORSETI, _WriteSpy   # noqa: E402

CLI = ROOT / "apps" / "forseti-cli"

#: 這一組守的十一支。**名字是模組名，不是檔名。**
#:
#: `antianchor` 是 2026-09-17 新增的第十四個寫入點，由上面那條
#: 覆蓋率測試點名進來的 —— 它紅了一次，這一行才長出來。
#: **那條紅是這個檔案唯一的用處**：其餘每一條都只看自己那一支，
#: 新增的模組在它們眼裡不存在。
GUARDED_HERE = frozenset({
    "advicetrack", "antianchor", "attempts", "blockread", "claims", "commit",
    "coverage", "event_ledger", "evidence", "gate", "identity", "lineage",
    "metrics", "pollution", "sufficiency", "workflow",
})

#: 另外三支守在 `tests/test_state_changing_writes.py`，那裡是從
#: `desktop_api` 的指令那一端進去的。這裡列出來只為了讓下面那條
#: 覆蓋率測試算得完 —— 不是在這裡守它們。
GUARDED_ELSEWHERE = frozenset({"notes", "checkpoint", "forkline"})

#: `desktop_api.py` 自己的寫入點不在這一組的範圍內。它是分派層不是
#: 儲存層，而它寫出去的東西已經被 `test_forseti_dir_writes.py` 的
#: 十七條 parametrize 逐個問過（問法是白名單）。
#: `context_meter` / `forseti` / `recall` / `tracker` 用的是讀模式或
#: `write_text`，不在這一組數的那十三個裡。
OUT_OF_SCOPE = frozenset({"desktop_api"})


def _write_mode_open_sites() -> dict[str, list[int]]:
    """語法樹掃出所有寫模式的 `X.open(...)`，回 模組名 -> 行號。

    **不用 grep。** 5ag 那一輪用 grep 數 `except OSError` 數出 48 個，
    實際是 70 個 —— grep 只抓得到單行寫法。這裡同一個理由。

    跳過 `._*`：exFAT 上的 AppleDouble 資源分叉，不是原始碼。
    """
    out: dict[str, list[int]] = {}
    for f in sorted(CLI.glob("*.py")):
        if f.name.startswith("._"):
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "open"):
                continue
            mode = ""
            if n.args and isinstance(n.args[0], ast.Constant):
                mode = str(n.args[0].value)
            for kw in n.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            if any(c in mode for c in "wax+"):
                out.setdefault(f.stem, []).append(n.lineno)
    return out


def test_每一個寫模式的PathOpen在某處都有人守():
    """新增一個 `p.open("a")` 的模組，這一條會紅。

    **這是這個檔案裡唯一一條會隨著程式碼長大的測試。** 其餘每一條
    都只看它自己那一支，所以新增第十四個寫入點時，
    其餘每一條都會繼續全綠 —— 那正是這十支先前三輪沒有人管的原因：
    沒有任何東西在數「總共有幾個」。
    """
    sites = _write_mode_open_sites()
    known = GUARDED_HERE | GUARDED_ELSEWHERE | OUT_OF_SCOPE
    new = set(sites) - known
    assert not new, (
        f"{sorted(new)} 有寫模式的 .open() 但沒有任何地方守它："
        + "；".join(f"{m}:{sites[m]}" for m in sorted(new))
        + "。要嘛在這個檔案加一條，要嘛寫下它為什麼不需要。"
    )
    gone = GUARDED_HERE - set(sites)
    assert not gone, (
        f"{sorted(gone)} 在這裡守著，但它已經沒有寫模式的 .open() 了。"
        "改寫法（例如改用 write_text）之後這裡要跟著改，"
        "不然守的是一個不存在的東西。"
    )


# --------------------------------------------------------------- 十支怎麼跑
#
# 每一支回傳「它應該寫到的那一個絕對路徑」。**回傳而不是寫死在斷言裡**，
# 是因為路徑的組法在各支模組裡不一樣（有的吃 path=、有的吃 root=、
# 有的吃 repo=），寫死會讓這一組看起來像在驗路徑組法，而它驗的是洩漏。

def _w_advicetrack(tmp: Path) -> Path:
    import advicetrack
    p = tmp / ".forseti" / "advice_ledger.jsonl"
    advicetrack.record([{"title": "守門測試", "severity": "info"}],
                       n=1, session="s", path=p)
    return p


def _w_blockread(tmp: Path) -> Path:
    import blockread
    lg = blockread.BlockLog(tmp)
    lg.append(blockread.Note(path="x.md", index=0, title="t",
                             lo=1, hi=2, summary="s"))
    return lg.path


def _w_claims(tmp: Path) -> Path:
    import claims
    p = tmp / ".forseti" / "claims.jsonl"
    claims.record(claims.Claim(text="守門測試", kind="file", subject="x.py"),
                  path=p)
    return p


def _w_commit(tmp: Path) -> Path:
    import commit
    p = tmp / ".forseti" / "commits.jsonl"
    commit.open_tx(kind="k", subject="守門測試", path=p)
    return p


def _w_coverage(tmp: Path) -> Path:
    import coverage
    lg = coverage.CoverageLog(root=tmp)
    lg.append(coverage.ReadRecord(path="x.md", total_lines=10, spans=[(1, 5)]))
    return lg.path


def _w_event_ledger(tmp: Path) -> Path:
    """只呼叫 `append()`，**刻意不碰 `reindex()`**。

    `reindex()` 會在家目錄建一個以臨時目錄命名的 db（外加 -shm 與 -wal），
    而臨時目錄消失之後那三個檔留在那裡沒有人會刪。
    2026-09-17 量測時真的製造過一次，事後手動清掉。
    索引放 home 是 `event_ledger.py:283` 的設計決定（「壞了刪掉重建」），
    不是這一組該改的事 —— 這一組只負責不要再製造殘留。
    """
    import event_ledger as EL
    led = EL.EventLedger(root=tmp)
    led.append(EL.RawEvent(provider="p", provider_event_type="t",
                           timestamp=time.time(), payload={"a": 1}))
    return led.jsonl


def _w_gate(tmp: Path) -> Path:
    import gate
    p = tmp / ".forseti" / "gate.jsonl"
    gate.judge([], [], session="守門測試", path=p)
    return p


def _w_identity(tmp: Path) -> Path:
    import identity
    r = identity.register("agent-守門測試", ["a1"], repo=tmp)
    assert r["ok"], f"登記被拒絕了，那這一條量到的零就不是零：{r}"
    return identity.registry_path(tmp)


def _w_pollution(tmp: Path) -> Path:
    """`radius_basis` 一定要給，理由見檔頭那個假陰性。"""
    import pollution
    p = tmp / ".forseti" / "pollution.jsonl"
    r = pollution.record(original_claim="a", corrected_claim="b",
                         failure_mechanism="c", source_events=["e1"],
                         verifier="守門測試", radius_basis="守門測試不算半徑",
                         path=p)
    assert r["ok"], f"登錄被拒絕了，那這一條量到的零就不是零：{r}"
    return p


def _w_antianchor(tmp: Path) -> Path:
    """走公開 API 不直接用 `Log`。

    `open_derivation()` 是這一支唯一會被外面呼叫的寫入入口，
    而它內部要先算一次 `canonical()` —— 那一支會去叫 `contract`。
    直接用 `Log.append` 的話這條路整段不會被走到，
    於是「有沒有順手寫別的」這一題就沒有問到真正會跑的那條路。
    """
    import antianchor
    row = antianchor.open_derivation(tmp, session="守門測試",
                                     snap={}, work={})
    assert row.get("id"), f"開卷沒有回 id，那這一條量到的零就不是零：{row}"
    return antianchor.Log(tmp).path


def _w_attempts(tmp: Path) -> Path:
    """走 `record()`，五個必填全部餵真的值。

    少餵任何一個，`record()` 會在寫檔之前就 return 一個
    `{"ok": False}` —— 那樣量到的零是提早 return 的零，
    跟「它不寫」長得一樣（檔頭那個假陰性）。
    """
    import attempts
    p = tmp / "attempts.jsonl"
    r = attempts.record(
        attempt="守門測試", observed_result="守門測試",
        why_not_repeat="守門測試", source=["守門測試"],
        verifier="守門測試", no_retry_basis="守門測試", path=p)
    assert r["ok"], f"登錄被拒絕了，那這一條量到的零就不是零：{r}"
    return p


def _w_metrics(tmp: Path) -> Path:
    """走 `build()` 再 `register()`，不直接餵一個手組的 dict。

    `register()` 擋下「不是 build() 出來的東西」，所以手組的 dict
    會在寫檔之前就 return —— 那樣量到的零是提早 return 的零，
    跟「它不寫」長得一樣（檔頭那個假陰性）。
    """
    import metrics
    built = metrics.build(
        metric_name="守門測試", semantic_definition="守門測試不算一把尺",
        numerator=1, denominator=2, sample_count_N=2,
        material_class="synthetic", system_layer="end-to-end",
        measured_by="守門測試", verification_method="守門測試",
        applicability_scope="守門測試",
        target_environment=metrics.absent(metrics.UNKNOWN, "守門測試"),
        model_id=metrics.absent(metrics.UNKNOWN, "守門測試"),
        model_hash=metrics.absent(metrics.UNKNOWN, "守門測試"),
        config_hash=metrics.absent(metrics.UNKNOWN, "守門測試"),
        code_commit=metrics.absent(metrics.UNKNOWN, "守門測試"),
        seed=metrics.absent(metrics.UNKNOWN, "守門測試"),
        cache_state=metrics.absent(metrics.UNKNOWN, "守門測試"),
        raw_metric_artifact=metrics.absent(metrics.UNKNOWN, "守門測試"),
        confidence_interval=metrics.absent(metrics.UNKNOWN, "守門測試"),
        execution_environment={"python": "守門測試"},
    )
    assert built["ok"], f"組不起來，那這一條量到的零就不是零：{built}"
    p = tmp / "metrics.jsonl"
    r = metrics.register(built["record"], path=p)
    assert r["ok"], f"登記被拒絕了，那這一條量到的零就不是零：{r}"
    return p


def _w_sufficiency(tmp: Path) -> Path:
    import sufficiency
    lg = sufficiency.Log(tmp)
    lg.append({"at": time.time(), "ok": True, "note": "守門測試"})
    return lg.path


def _w_lineage(tmp: Path) -> Path:
    """走 `add()`，五個必填全部餵真的值。

    2026-09-18 新增的第十五個寫入點，由上面那條覆蓋率測試點名進來的
    —— 它紅了一次，這一行才長出來。

    `basis` 不能空，空的話 `add()` 在寫檔之前就 return 一個
    `{"ok": False}`，那樣量到的零是提早 return 的零，
    跟「它不寫」長得一樣（檔頭那個假陰性）。
    """
    import lineage
    p = tmp / "lineage.jsonl"
    r = lineage.add(type="SUPERSEDES", from_id="ADR-010", to_id="ADR-002",
                    basis="守門測試", path=p)
    assert r["ok"], f"加邊被拒絕了，那這一條量到的零就不是零：{r}"
    return p


def _w_evidence(tmp: Path) -> Path:
    """走 `record()`，四個必填全部餵真的值。

    2026-09-18 新增的第十六個寫入點，由上面那條覆蓋率測試點名進來的
    —— 它紅了一次，這一行才長出來。

    `about` / `sources` / `strength` / `captured_by` 缺任何一個，
    `record()` 會在寫檔之前就 return 一個 `{"ok": False}`，
    那樣量到的零是提早 return 的零，跟「它不寫」長得一樣
    （檔頭那個假陰性）。
    """
    import evidence
    p = tmp / "evidence.jsonl"
    r = evidence.record(about="守門測試", sources=["守門測試"],
                        strength="E1", captured_by="守門測試", path=p)
    assert r["ok"], f"登記被拒絕了，那這一條量到的零就不是零：{r}"
    return p


def _w_workflow(tmp: Path) -> Path:
    import workflow
    workflow.declare_boundary("wf-守門測試", "NONE", declared_by="守門測試",
                              repo=tmp)
    return workflow.boundary_path(tmp)


WRITERS = {
    "advicetrack": _w_advicetrack,
    "antianchor": _w_antianchor,
    "attempts": _w_attempts,
    "blockread": _w_blockread,
    "claims": _w_claims,
    "commit": _w_commit,
    "coverage": _w_coverage,
    "event_ledger": _w_event_ledger,
    "evidence": _w_evidence,
    "gate": _w_gate,
    "identity": _w_identity,
    "lineage": _w_lineage,
    "metrics": _w_metrics,
    "pollution": _w_pollution,
    "sufficiency": _w_sufficiency,
    "workflow": _w_workflow,
}


def test_十支全部在這裡有對應的跑法():
    """`GUARDED_HERE` 跟 `WRITERS` 必須一模一樣。

    只改其中一邊的話，下面那條 parametrize 會少跑一支而且不會有人知道。
    """
    assert set(WRITERS) == set(GUARDED_HERE), (
        f"對不起來：只在 WRITERS 的 {sorted(set(WRITERS) - GUARDED_HERE)}、"
        f"只在 GUARDED_HERE 的 {sorted(GUARDED_HERE - set(WRITERS))}"
    )


@pytest.mark.parametrize("name", sorted(WRITERS))
def test_只寫該寫的那一個檔案(name, tmp_path, monkeypatch):
    """餵臨時目錄，整個檔案系統上只准動它回報的那一個路徑。

    **範圍是整個檔案系統不是 `.forseti/`。** 只看 `.forseti/` 的話，
    寫進家目錄或工作目錄的那一種洩漏會完全看不到 —— 而那一種
    正是最難發現的，因為那些位置本來就有東西。

    兩個環境變數先清掉：`FORSETI_COVERAGE_LOG` 與
    `FORSETI_EVENT_LEDGER_DIR` 會把目標整個換掉（`coverage.py:294`
    與 `event_ledger.py:259`）。開發機上沒設，CI 上設了的話
    這一條會量到「寫到別的地方」而那不是模組的錯。
    """
    monkeypatch.delenv("FORSETI_COVERAGE_LOG", raising=False)
    monkeypatch.delenv("FORSETI_EVENT_LEDGER_DIR", raising=False)

    with _WriteSpy(scope=None) as spy:
        expected = WRITERS[name](tmp_path)

    assert spy.hits, (
        f"{name} 一次寫入都沒有攔到。**零在這一組裡一律是壞掉** ——"
        "要嘛提早 return 了（檔頭那個假陰性），要嘛攔截網瞎了。"
    )
    got = {p for _, p in spy.hits}
    want = {str(Path(expected).resolve())}
    assert got == want, (
        f"{name} 動到的不只它該動的那一個。"
        f"該動：{sorted(want)}；實際動到：{sorted(got)}"
    )
    stray = [p for p in got
             if not p.startswith(str(tmp_path.resolve()))]
    assert not stray, (
        f"{name} 寫到臨時目錄外面去了：{stray}。"
        "餵了 root/path 還往別處寫，代表那個參數沒有真的接上。"
    )


# ------------------------------------------------------------- 預設位置
#
# 上面那十條全部靠「傳參數」。傳了參數就只驗得到「參數有接上」，
# 驗不到「不傳的時候它去哪」—— 而系統平常跑的正是不傳的那條路。

def _default_of(name: str) -> Path:
    import advicetrack, antianchor, attempts                        # noqa: E401
    import blockread, claims, commit, coverage                     # noqa: E401
    import event_ledger, evidence                                  # noqa: E401
    import gate, identity, lineage, metrics, pollution            # noqa: E401
    import sufficiency, workflow                                   # noqa: E401
    import desktop_api                                             # noqa: E401
    return {
        "advicetrack": lambda: advicetrack.LOG,
        "antianchor": lambda: antianchor.Log().path,
        "attempts": lambda: attempts.LOG,
        # **`blockread` 沒有自己的預設。** `BlockLog.__init__` 的 `root`
        # 沒有預設值,位置整個由呼叫端決定,而全 repo 只有兩個呼叫端:
        # `desktop_api.py:921` 餵 `desktop_api.REPO`,`blockread.py:197`
        # 餵傳進來的 root。所以這一支問的是「那個呼叫端餵的是不是控制目錄」,
        # 跟其餘九支問的不是同一件事,寫在這裡免得被讀成一樣。
        "blockread": lambda: blockread.BlockLog(desktop_api.REPO).path,
        "claims": lambda: claims.log_path(),
        "commit": lambda: commit.LOG,
        "coverage": lambda: coverage.CoverageLog().path,
        "event_ledger": lambda: event_ledger.default_jsonl(),
        "evidence": lambda: evidence.log_path(),
        "gate": lambda: gate.LOG,
        "identity": lambda: identity.registry_path(),
        "lineage": lambda: lineage.log_path(),
        "metrics": lambda: metrics.LOG,
        "pollution": lambda: pollution.LOG,
        "sufficiency": lambda: sufficiency.Log().path,
        "workflow": lambda: workflow.boundary_path(),
    }[name]()


#: 不傳參數時，每一支該落在 `.forseti/` 底下的哪個名字。
#: **這是白名單不是紀錄**：改了位置要來這裡改，改的時候才會被問一句
#: 「這個檔為什麼要搬」。
DEFAULT_NAMES = {
    "advicetrack": "advice_ledger.jsonl",
    "antianchor": "antianchor.jsonl",
    "attempts": "attempts.jsonl",
    "blockread": "reading_blocks.jsonl",
    "claims": "claims.jsonl",
    "commit": "commits.jsonl",
    "coverage": "reading_coverage.jsonl",
    "event_ledger": "event_ledger.jsonl",
    "evidence": "evidence.jsonl",
    "gate": "gate.jsonl",
    "identity": "identity.jsonl",
    "lineage": "lineage.jsonl",
    "metrics": "metrics.jsonl",
    "pollution": "pollution.jsonl",
    "sufficiency": "sufficiency.jsonl",
    "workflow": "workflow_boundary.jsonl",
}


@pytest.mark.parametrize("name", sorted(DEFAULT_NAMES))
def test_不傳參數的時候寫在控制目錄底下(name, monkeypatch):
    """**只算路徑，不寫檔。** 真的寫下去會動到正本。

    `blockread`、`sufficiency` 與 `antianchor` 要建一個物件才問得到路徑，
    而那兩個建構子只組路徑不開檔（`blockread.py:158`、
    `sufficiency.py:311`）。`coverage.CoverageLog.__init__` 不一樣，
    它會 `mkdir(parents=True)` —— 目錄本來就存在，所以這裡不會多出東西，
    但這件事寫下來，免得有人以為這條完全沒有副作用。
    """
    monkeypatch.delenv("FORSETI_COVERAGE_LOG", raising=False)
    monkeypatch.delenv("FORSETI_EVENT_LEDGER_DIR", raising=False)

    got = Path(_default_of(name)).resolve()
    assert got == (FORSETI / DEFAULT_NAMES[name]), (
        f"{name} 的預設位置現在是 {got}，"
        f"不是 .forseti/{DEFAULT_NAMES[name]}"
    )


def test_覆蓋率記錄的環境變數會把目標整個換掉(tmp_path, monkeypatch):
    """`FORSETI_COVERAGE_LOG` 設了就寫那裡，連 `root=` 都蓋過去。

    **這不是 bug，是 `coverage.py:288` 那四行明寫的優先序。**
    釘住它的理由是：設了這個變數之後，寫入會落在 repo 外面，
    而上面那條「只寫該寫的那一個」在 CI 上就會紅得莫名其妙。
    紅的時候要看得到這一條，才知道紅的是環境不是模組。
    """
    import coverage

    outside = tmp_path / "somewhere_else" / "cov.jsonl"
    monkeypatch.setenv("FORSETI_COVERAGE_LOG", str(outside))
    lg = coverage.CoverageLog(root=tmp_path / "ignored")
    assert lg.path == outside, (
        f"環境變數沒有蓋過 root=，實際落在 {lg.path}"
    )


def test_攔截網攔不到sqlite這件事本身(tmp_path):
    """釘住這一組的第二個弱點：`_WriteSpy` 看不到 sqlite3 的寫入。

    **這一條跟 `test_用builtins_open攔不到PathOpen這件事本身` 是同一種：
    它釘的是前提不是功能。** Python 或 sqlite3 哪天改成走 Python 層的
    檔案物件，這一條會紅 —— 那時候該刪的是這一條，不是去修攔截網。

    2026-09-17 實測：`EventLedger.reindex()` 在家目錄建出 4096 位元組的
    db 檔，spy 攔到的路徑裡沒有它。這裡不跑 `reindex()`（會留殘留），
    改用最小的 `sqlite3.connect` 加一張表，目標在臨時目錄裡。
    """
    import sqlite3

    db = tmp_path / "probe.db"
    with _WriteSpy(scope=None) as spy:
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE t (a INTEGER)")
        con.commit()
        con.close()

    assert db.exists() and db.stat().st_size > 0, (
        "sqlite 沒有真的寫出檔案，那這一條證不了任何事"
    )
    assert not any(str(db) in p for _, p in spy.hits), (
        "攔截網現在看得到 sqlite3 的寫入了。這是好事 ——"
        "刪掉這一條，並且回頭看 `.forseti/` 那幾條「零寫入」的斷言，"
        "它們現在證到的比以前多。"
    )
