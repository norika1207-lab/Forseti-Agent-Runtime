"""那些整段只有 `pass` 或不帶值 `return` 的 `except OSError`，各自吞掉什麼。

**2026-09-17 加這一組，補的是連續兩輪被寫下來、連續兩輪沒動的那一件。**
原話在 `AUTO_CONTINUE_LOG.md`（5ag 與 5ah 兩輪都寫過）：

    全 repo 的 `except OSError` 語法樹數出 70 個，其中 9 個整段只有
    `pass` 或不帶值的 `return`（`contract` 2、`coverage` 2、
    `context_meter` 1、`desktop_api` 1、`forseti` 1、`identity` 1、
    `ledger` 1），各自吞掉什麼仍然沒有量。

跟 5ag 修掉的 `blast._cache_put` 是同一種洞，只是散在七個模組裡。

## 問的是哪一題

不是「這裡該不該吞」。政策是既有的，每一個站點自己的註解都寫著
「寫失敗不算錯誤」那類理由，那是設計決定。

問的是：**吞掉的那一刻，呼叫端看得到什麼。**
看不到的話，錯誤的答案跟正確的答案長得一模一樣，
而分不出來這件事本身就是那個洞 —— 不是那幾十毫秒。

## 量出來的結果（2026-09-17 實測，九支全部）

手法一律是把那一個作業換成丟 `OSError`，再跟「正常」與
「本來就沒東西」兩種對照比。

| 站點 | 吞掉什麼 | 呼叫端分得出來嗎 |
|---|---|---|
| `context_meter.report_all:350` | 那個檔的大小不計入 `total_bytes` | 分不出來。3.5MB 的檔，報告從「共 3 MB」變「共 0 MB」，其餘每一行逐字元相同，沒有任何一行提到算不到 |
| `contract._hcache_save:545` | 雜湊快取沒寫進去 | 回傳分不出來（成功與失敗都是 `None`），要自己去 stat 那個檔 |
| `contract._rc_cache_save:763` | 同上 | 同上 |
| `coverage.header_lines_of:245` | 讀不到 → 回空集合 | 跟「這份文件真的沒有標題」分不出來，兩邊都是 `set()` |
| `coverage.read_all:310` | 讀不到 → 回 `[]` | 跟「一筆紀錄都沒有」分不出來，兩邊都是 `[]` |
| `desktop_api.spec_reading:815` | manifest 派生的必讀文件全部不進 `must` | 分不出來。實測 `total` 從 30 掉到 21，九份模組化規格整批消失，回傳字典沒有任何一個鍵提到它 |
| `forseti._ensure_inbox:1069` | 收件匣目錄與 README 沒建成 | 分不出來。成功與失敗都回一個 `Path`，形狀一樣 |
| `identity._cache_write:290` | 快取沒寫進去 | 回傳分不出來（都是 `None`） |
| `ledger.collect_inbox:858` | 處理完的檔沒搬進 `done/` | 分得出來，但要去看檔案系統：檔案留在原地，下一次收件會再撿一次 |

九個裡有八個從回傳值分不出來。唯一分得出來的那個（`ledger`）
分得出來的方式是「去看檔案還在不在」，不是呼叫端拿得到的東西。

## `tools/` 那三個（2026-09-17 補量，先前只普查）

連續三輪被寫進 `AUTO_CONTINUE_LOG.md` 的「下一輪最明確的一件」，
連續三輪沒動。這一輪量了，手法跟上面九個一樣。

| 站點 | 吞掉什麼 | 呼叫端分得出來嗎 |
|---|---|---|
| `claims-audit.assistant_texts:121` | 那一份 transcript 從出錯那一行開始的所有 assistant 文字 | 分不出來，而且**這一個是截斷不是全無**：讀到第 3 行才壞的話，前 2 段照樣 yield 出去，跟一份本來就只有 2 段的檔**逐元素相同** |
| `owner-audit.main:124` | 那一個 session 的整張沉默地圖 | 分不出來。報告印「沉默地圖 0 輪」，跟一份真的沒有任何 AI 輪的語料**逐字元相同**；而同一份報告上面四行還印著「4 則 owner 訊息」 |

`reading-conformance.declared` 原本也在這張表上（第三列），
**2026-09-17 修掉了，所以它離開這一組**，見下面那一段。

### 修掉的那一個，以及上一輪被推翻的那句話

`AUTO_CONTINUE_LOG.md` 5ai 那一輪寫：「`reading-conformance.py` 判的是
讀取符合度，吞掉讀取失敗會讓不合格看起來像合格」。

**方向是反的。** 實測 `check()` 在補讀表讀不到的時候回
`NON_CONFORMANT`、`bad` 等於全部、exit code 1 —— 它變得過嚴，不是過鬆。

真正的洞不在寬嚴，在**理由是假的**：它印「補讀表裡沒有這一份的記錄」，
而補讀表根本沒被讀到。照那句理由去修的人會去補表，
而表可能一直是對的，錯的是讀不到。

**這一個修掉了。** `declared()` 現在丟 `ReadingTableUnreadable`，
`check()` 接住之後回 `CANNOT_CHECK` —— 那是模組檔頭 exit code
那一段本來就寫著的第 2 種，先前只寫在文件裡沒有實作。
守它的那五條在 `tests/test_reading_conformance.py`
的 `TestReadingTableUnreadable`，包含「空表仍然是 NON_CONFORMANT」
（防的是修的時候順手把空表一起放寬）。

所以這一組現在是 **9 + 2**：產品側九個，`tools/` 兩個。

機制：從「吞掉錯誤 → 檢查失效 → 檢查失效通常代表放行」推下去，
中間那一步沒有去讀 `declared()` 回空之後 `check()` 怎麼用它。
回空在這裡是「沒人宣稱讀過」，而沒人宣稱讀過在這支工具裡是不合格。
**吞掉錯誤會讓檢查往哪一邊偏，取決於那個空值在下游代表什麼，
不能從「錯誤被吞掉了」本身推出來。**

## 量的時候踩到兩個假陰性，寫在這裡

一，`context_meter` 第一次量餵的 jsonl 放在 root 底下一層，
    而 `find_sessions` 要的是 `*/*.jsonl`（`context_meter.py:195`），
    於是 `report_all` 走的是「底下沒有 jsonl」那條早退路徑。
    正常與失敗兩份輸出都是同一句話，看起來像「分不出來」——
    **早退的相同，跟吞掉造成的相同長得一樣。**

二，改好目錄結構之後，餵的檔只有 40 位元組，
    `total_bytes / 1e6` 兩邊都印「0 MB」。**還是相同，還是假的。**
    要餵到 3.5MB 才量得出 3 MB 與 0 MB 的差。

兩個都是同一個形狀：拿到「兩邊一樣」就收手，沒有先問
「這個一樣是我要的那個一樣嗎」。所以下面每一條會分得出來的，
都另外釘住對照組本身不是退化的（例如 `mb_normal` 必須不是 0 MB）。

## 這一組紅了不一定是壞事

把其中一個站點改成會回報（像 5ag 對 `blast._cache_put` 做的那樣），
下面對應那一條會紅 —— 那是對的，因為這一組釘的是「此刻吞掉什麼」。
修好一個就同時改這裡那一條，順便把上面那張表改掉。

**不要為了讓它綠而把站點改回去。**
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

CLI = ROOT / "apps" / "forseti-cli"
TOOLS = ROOT / "tools"

#: 產品側那九個。**key 是（模組名，包住它的函式名）**，不是行號 ——
#: 行號會因為上面加一行註解就整批位移，那種紅是雜訊不是訊號。
EXPECTED_CLI = (
    ("context_meter", "report_all"),
    ("contract", "_hcache_save"),
    ("contract", "_rc_cache_save"),
    ("coverage", "header_lines_of"),
    ("coverage", "read_all"),
    ("desktop_api", "spec_reading"),
    ("forseti", "_ensure_inbox"),
    ("identity", "_cache_write"),
    ("ledger", "collect_inbox"),
)

#: `tools/` 底下還有三個，**5ag 那一輪數的 70 個沒有含這裡**
#: （那次只掃 `apps/`）。它們是開發側腳本不是產品程式碼，
#: 先前只做普查 —— 但漏數過一次，就不該再漏數第二次。
#: **2026-09-17 起三個都有行為量測**，見檔頭第二張表。
EXPECTED_TOOLS = (
    ("claims-audit.py", "assistant_texts"),
    ("owner-audit.py", "main"),
)


def _silent_sites(files) -> list[tuple[str, str, int]]:
    """語法樹掃出「整段只有 pass 或不帶值 return」的 `except OSError`。

    **不用 grep。** 5ag 那一輪用 grep 數 `except OSError` 數出 48 個，
    語法樹重數是 70 個 —— grep 抓不到跨行與 tuple 寫法。

    回 (檔案識別, 包住它的最內層函式名, 行號)。
    """
    out: list[tuple[str, str, int]] = []
    for f in sorted(files):
        if f.name.startswith("._"):          # exFAT 的 AppleDouble
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        funcs = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for n in ast.walk(tree):
            if not isinstance(n, ast.ExceptHandler):
                continue
            t = n.type
            names: list[str] = []
            if isinstance(t, ast.Name):
                names = [t.id]
            elif isinstance(t, ast.Tuple):
                names = [e.id for e in t.elts if isinstance(e, ast.Name)]
            if "OSError" not in names:
                continue
            if not all(isinstance(s, ast.Pass)
                       or (isinstance(s, ast.Return) and s.value is None)
                       for s in n.body):
                continue
            encl = [fn for fn in funcs
                    if fn.lineno <= n.lineno <= (fn.end_lineno or 0)]
            encl.sort(key=lambda fn: (fn.end_lineno or 0) - fn.lineno)
            ident = f.stem if f.parent == CLI else f.name
            out.append((ident, encl[0].name if encl else "<module>", n.lineno))
    return out


# ── 普查：名單本身有人守 ────────────────────────────────────────


def test_產品側靜默吞掉的就是這九個():
    """新增一個靜默的 `except OSError`，或修好其中一個，這一條會紅。

    兩種紅都是要的。新增的那種要補量測，修好的那種要改上面那張表。
    """
    got = tuple(sorted((m, fn) for m, fn, _ in _silent_sites(CLI.glob("*.py"))))
    assert got == tuple(sorted(EXPECTED_CLI))


def test_tools側靜默吞掉的就是這兩個():
    got = tuple(sorted((m, fn) for m, fn, _ in _silent_sites(TOOLS.rglob("*.py"))))
    assert got == tuple(sorted(EXPECTED_TOOLS))


def test_每一個站點都在下面有一條自己的行為量測():
    """普查表跟量測表對不起來就紅。

    防的是「名單上加一筆、但沒有人去量它吞掉什麼」——
    那樣普查會綠，而這一組存在的理由整個落空。
    """
    measured = {
        ("context_meter", "report_all"),
        ("contract", "_hcache_save"),
        ("contract", "_rc_cache_save"),
        ("coverage", "header_lines_of"),
        ("coverage", "read_all"),
        ("desktop_api", "spec_reading"),
        ("forseti", "_ensure_inbox"),
        ("identity", "_cache_write"),
        ("ledger", "collect_inbox"),
    }
    assert measured == set(EXPECTED_CLI)


# ── 逐站點：吞掉的那一刻呼叫端看到什麼 ──────────────────────────


def test_context_meter報告會少算而且不說(monkeypatch, tmp_path):
    """3.5MB 的檔 stat 不到，報告印「共 0 MB」，其餘逐行相同。"""
    import context_meter

    root = tmp_path / "projects"
    sub = root / "p"
    sub.mkdir(parents=True)
    line = json.dumps({"type": "assistant",
                       "message": {"usage": {"input_tokens": 100,
                                             "output_tokens": 5}}}) + "\n"
    (sub / "s.jsonl").write_text(line * 40000, encoding="utf-8")

    def run() -> str:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            context_meter.report_all(root)
        return buf.getvalue()

    normal = run()
    orig_stat = Path.stat

    def bad_stat(self, *a, **k):
        if self.suffix == ".jsonl":
            raise OSError(5, "boom")
        return orig_stat(self, *a, **k)

    monkeypatch.setattr(Path, "stat", bad_stat)
    failed = run()
    monkeypatch.undo()

    mb_normal = [l.strip() for l in normal.splitlines() if "MB" in l]
    mb_failed = [l.strip() for l in failed.splitlines() if "MB" in l]

    # 對照組本身不能是退化的：量到的假陰性兩次都是這裡塌掉。
    assert mb_normal, "正常那份連 MB 那一行都沒有，對照組是壞的"
    assert "共 0 MB" not in mb_normal[0], "餵的檔太小，兩邊本來就都是 0 MB"

    assert mb_failed == ["session 檔案　1 份，共 0 MB"]
    assert mb_normal != mb_failed

    # 少算了，而且整份報告沒有一個字提到少算。
    assert not any(w in failed for w in ("讀不到", "算不到", "stat"))

    def _rest(text: str) -> list[str]:
        """拿掉 MB 那一行，再把「掃描耗時」那一行的秒數歸一。

        **那一行本來就每次都不一樣。** 2026-09-17 全套實測撞到
        正常那次印 `掃描耗時　0.2s`、失敗那次印 `0.3s`，
        於是這一條紅了 —— 紅的是機器負載，不是被測行為。
        歸一而不是整行丟掉：那一行消失了也該紅，
        那代表報告的形狀真的變了。
        """
        import re
        return [re.sub(r"耗時.*", "耗時　（秒數不比）", l)
                for l in text.splitlines() if "MB" not in l]

    assert _rest(normal) == _rest(failed), \
        "除了那個數字以外應該逐行相同，不同代表這條測的不是同一件事"


@pytest.mark.parametrize("fname", ["_hcache_save", "_rc_cache_save"])
def test_contract兩個快取寫失敗回傳跟成功一樣(monkeypatch, tmp_path, fname):
    import contract

    base = tmp_path / "base"
    (base / ".forseti" / "cache").mkdir(parents=True)
    save = getattr(contract, fname)
    where = getattr(contract, "_hcache_file" if fname == "_hcache_save"
                    else "_rc_cache_file")(base)

    ret_ok = save(base, {"x": 1})
    assert where.is_file(), "正常那次沒寫成，這條測不到東西"
    where.unlink()

    orig_wt = Path.write_text

    def bad_wt(self, *a, **k):
        if "cache" in str(self):
            raise OSError(28, "no space")
        return orig_wt(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", bad_wt)
    ret_bad = save(base, {"x": 1})
    monkeypatch.undo()

    assert not where.is_file()
    assert ret_ok is None and ret_bad is None, \
        "成功與失敗回傳不同了，站點改過，上面那張表要跟著改"


def test_coverage讀不到的檔看起來像沒有標題(monkeypatch, tmp_path):
    import coverage as cov

    with_h = tmp_path / "with.md"
    with_h.write_text("# A\ntext\n## B\n", encoding="utf-8")
    without_h = tmp_path / "without.md"
    without_h.write_text("text only\n", encoding="utf-8")

    got_with = cov.header_lines_of(with_h)
    got_without = cov.header_lines_of(without_h)
    assert got_with == {1, 3}, "對照組壞了，有標題的那份應該抓得到"
    assert got_without == set()

    orig_rt = Path.read_text

    def bad_rt(self, *a, **k):
        if self.name == "with.md":
            raise OSError(5, "io error")
        return orig_rt(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", bad_rt)
    got_failed = cov.header_lines_of(with_h)
    monkeypatch.undo()

    assert got_failed == got_without == set(), \
        "讀不到跟真的沒標題現在分得出來了，站點改過"


def test_coverage讀不到的紀錄看起來像一筆都沒有(monkeypatch, tmp_path):
    import coverage as cov

    logp = tmp_path / "cov.jsonl"
    log = cov.CoverageLog(logp)
    when_missing = log.read_all()

    logp.write_text('{"path":"p","total":3}\n', encoding="utf-8")
    when_present = log.read_all()
    assert when_present == [{"path": "p", "total": 3}], "對照組壞了"

    orig_rt = Path.read_text

    def bad_rt(self, *a, **k):
        if self.name == "cov.jsonl":
            raise OSError(13, "denied")
        return orig_rt(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", bad_rt)
    when_denied = log.read_all()
    monkeypatch.undo()

    assert when_denied == when_missing == [], \
        "讀不到跟檔案不存在現在分得出來了，站點改過"


def test_spec_reading的manifest讀不到會整批少算必讀(monkeypatch):
    """實測九份模組化規格整批從分母消失，而回傳字典不提這件事。

    這一條問的不是「比例變高還是變低」——那取決於掉出去的那幾份
    當下讀完了沒有。問的是**掉出去這件事沒有人講**。
    分母是 `spec_reading` 自己算 `ok` 的依據（`bad == 0` 掃的是 `must`），
    所以不在 `must` 裡的文件不論讀沒讀都不再被問。
    """
    import desktop_api

    normal = desktop_api.spec_reading()
    if not normal.get("has"):
        pytest.skip("這台機器上讀不到閱讀紀錄，對照組立不起來")

    orig_rt = Path.read_text

    def bad_rt(self, *a, **k):
        if self.name == "spec_manifest.json":
            raise OSError(13, "denied")
        return orig_rt(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", bad_rt)
    broken = desktop_api.spec_reading()
    monkeypatch.undo()

    dropped = ({r["name"] for r in normal["rows"]}
               - {r["name"] for r in broken["rows"]})
    assert dropped, "manifest 壞掉之後沒有任何文件掉出去，對照組是壞的"
    assert broken["total"] < normal["total"]
    assert len(dropped) == normal["total"] - broken["total"]

    # 掉出去的都是 manifest 派生的那一組（架構書 + F 開頭那幾份）。
    assert all(n.startswith("00_") or n.startswith("F0") for n in dropped), \
        f"掉出去的不只 manifest 那一組：{sorted(dropped)}"

    # 沒有任何一個鍵講到它掉了東西。
    assert set(broken) == set(normal), "回傳的鍵變了，站點改過"
    assert not any("manifest" in str(v).lower() for v in broken.values()
                   if isinstance(v, str))


def test_ensure_inbox建不出來也回一個Path(monkeypatch, tmp_path):
    import forseti as fcli

    class FakeLed:
        def __init__(self, d: Path) -> None:
            self.d = d

        def inbox_dir(self, step_id: str) -> Path:
            return self.d / step_id

    led = FakeLed(tmp_path / "inbox")
    ok = fcli._ensure_inbox(led, "S-1")
    assert ok.is_dir() and (ok / "README.md").is_file(), "對照組壞了"

    def bad_mkdir(self, *a, **k):
        raise OSError(30, "read-only fs")

    monkeypatch.setattr(Path, "mkdir", bad_mkdir)
    bad = fcli._ensure_inbox(led, "S-2")
    monkeypatch.undo()

    assert not bad.exists()
    assert isinstance(bad, Path) and isinstance(ok, Path), \
        "回傳形狀不一樣了，站點改過"


def test_identity快取寫失敗回傳跟成功一樣(monkeypatch, tmp_path):
    """`_cache_file()` 寫死指向正本，所以量之前先把它導開。

    5ah 那一輪的植入驗證真的往正本 `.forseti/gate.jsonl` 寫了一行。
    這一條不重蹈：最後一句斷言正本沒被碰過。
    """
    import identity

    real = identity._cache_file()
    real_before = real.read_bytes() if real.is_file() else None

    tmp_cache = tmp_path / "cache" / "identity.json"
    monkeypatch.setattr(identity, "_cache_file", lambda: tmp_cache)

    ret_ok = identity._cache_write({"probe": {"n": 1}})
    assert tmp_cache.is_file(), "正常那次沒寫成，這條測不到東西"
    tmp_cache.unlink()

    orig_wt = Path.write_text

    def bad_wt(self, *a, **k):
        if self.name.endswith(".json.tmp"):
            raise OSError(28, "no space")
        return orig_wt(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", bad_wt)
    ret_bad = identity._cache_write({"probe": {"n": 1}})
    monkeypatch.undo()

    assert not tmp_cache.is_file()
    assert ret_ok is None and ret_bad is None, \
        "成功與失敗回傳不同了，站點改過"

    after = real.read_bytes() if real.is_file() else None
    assert after == real_before, "正本被碰到了"


def test_collect_inbox搬不走的檔會留在原地(tmp_path, monkeypatch):
    """`ledger.py:858` 吞掉的是 `rename`，代價是同一個檔會被收第二次。

    `Ledger(db=..., cwd=...)` 兩個都導到臨時目錄，所以 sqlite 帳本與
    收件匣都不落在家目錄，也不落在正本 —— 5ah 那一輪的植入驗證
    真的往正本寫過一行，這裡不重蹈。
    """
    import ledger as L

    led = L.Ledger(db=tmp_path / "ledger.db", cwd=tmp_path)
    step = "S-inbox"
    d = led.inbox_dir(step)
    d.mkdir(parents=True, exist_ok=True)

    # 對照組：搬得動的時候，檔案會進 .done/。
    (d / "a.txt").write_text("WORKER_ACK\n收到了\n", encoding="utf-8")
    got_ok = led.collect_inbox(step)
    assert got_ok, "對照組壞了，正常收件應該收到東西"
    assert not (d / "a.txt").exists()
    assert (d / ".done" / "a.txt").is_file()

    # 同一步再收一次，應該沒有東西可收。
    assert led.collect_inbox(step) == []

    # 植入：rename 丟 OSError。
    (d / "b.txt").write_text("WORKER_ACK\n第二封\n", encoding="utf-8")
    orig_rename = Path.rename

    def bad_rename(self, *a, **k):
        if self.parent == d:
            raise OSError(18, "cross-device link")
        return orig_rename(self, *a, **k)

    monkeypatch.setattr(Path, "rename", bad_rename)
    got_bad = led.collect_inbox(step)
    monkeypatch.undo()

    assert got_bad, "事件照樣記了，只有搬檔失敗"
    assert (d / "b.txt").exists(), "搬不走的檔應該留在原地"
    assert not (d / ".done" / "b.txt").exists()

    # 這才是代價：下一次收件會再撿同一個檔。
    again = led.collect_inbox(step)
    assert again == got_bad, \
        f"同一個檔應該被收第二次，第一次 {got_bad} 第二次 {again}"


# ── tools/ 三個站點：載入器 ────────────────────────────────────


def _load_tool(modname: str, filename: str):
    """`tools/` 底下的檔名有連字號，`import` 進不來，只能走 importlib。

    **先放進 `sys.modules` 再 `exec`。** 順序反過來的話，被載入的模組
    裡任何 dataclass 都會在 `sys.modules` 找不到宣告它的模組而炸
    —— `reading-conformance.py:127` 的註解記過同一件事，那是實際撞過的。
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(modname, TOOLS / filename)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def test_每一個tools站點都在下面有一條自己的行為量測():
    """普查表跟量測表對不起來就紅。跟產品側那一條同一個理由。

    2026-09-17 之前這三個只有普查，於是「名單守住了」跟
    「有人量過它吞掉什麼」長得一樣 —— 而那正是這一整組在抓的形狀。
    """
    measured = {
        ("claims-audit.py", "assistant_texts"),
        ("owner-audit.py", "main"),
    }
    assert measured == set(EXPECTED_TOOLS)


def _ai_line(text: str) -> str:
    return json.dumps({"type": "assistant", "cwd": "/x",
                       "message": {"content": [{"type": "text",
                                                "text": text}]}},
                      ensure_ascii=False)


def _user_line(text: str) -> str:
    return json.dumps({"type": "user", "message": {"content": text}},
                      ensure_ascii=False)


class _TruncatingHandle:
    """讀到第 k 行之後丟 `OSError`，模擬讀到一半的 I/O 錯誤。

    **開不開得了跟讀不讀得完是兩件事。** 只植入 `open` 失敗的話，
    量到的是「全無」，而 `assistant_texts` 的 `try` 包住整個迴圈，
    所以它真正的行為是**截斷**。截斷才是分不出來的那一種。
    """

    def __init__(self, real, k: int) -> None:
        self.real, self.k, self.n = real, k, 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.real.close()
        return False

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if self.n >= self.k:
            raise OSError(5, "input/output error")
        self.n += 1
        return next(self.real)


def test_claims_audit讀到一半壞掉跟檔案本來就短一模一樣(monkeypatch, tmp_path):
    """`assistant_texts` 是 generator，吞掉的代價是**默默少掃**。

    三個對照擺在一起才看得出形狀：
    全開不了回 0 段、讀到第 2 行壞掉回 2 段、
    而一份本來就只有 2 段的檔也回 2 段 —— 後兩者逐元素相同。
    """
    ca = _load_tool("forseti_probe_claims_audit", "claims-audit.py")

    five = tmp_path / "five.jsonl"
    five.write_text("\n".join(_ai_line(f"第 {i} 段") for i in range(5)) + "\n",
                    encoding="utf-8")
    two = tmp_path / "two.jsonl"
    two.write_text("\n".join(_ai_line(f"第 {i} 段") for i in range(2)) + "\n",
                   encoding="utf-8")

    normal = list(ca.assistant_texts(five))
    really_short = list(ca.assistant_texts(two))
    assert len(normal) == 5, "對照組壞了，正常那份應該撈得到五段"
    assert len(really_short) == 2, "對照組壞了"

    orig_open = Path.open

    def denied_open(self, *a, **k):
        if self.name == "five.jsonl":
            raise OSError(13, "denied")
        return orig_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", denied_open)
    none_at_all = list(ca.assistant_texts(five))
    monkeypatch.undo()
    assert none_at_all == [], "開不了的時候應該一段都沒有"

    def truncating_open(self, *a, **k):
        if self.name == "five.jsonl":
            return _TruncatingHandle(orig_open(self, *a, **k), 2)
        return orig_open(self, *a, **k)

    monkeypatch.setattr(Path, "open", truncating_open)
    truncated = list(ca.assistant_texts(five))
    monkeypatch.undo()

    assert truncated == really_short, (
        "截斷之後跟一份本來就只有兩段的檔現在分得出來了，站點改過，"
        "檔頭那張表要跟著改")
    assert truncated != normal


def test_owner_audit沉默地圖吞掉之後跟沒有AI輪的語料逐字元相同(
        monkeypatch, tmp_path, capsys):
    """吞掉的是**整個 session** 的沉默地圖，而報告照樣說它掃過了。

    最刺的一句在報告裡自己打自己：同一份輸出上面印「1 個 session，
    4 則 owner 訊息」，下面印「沉默地圖 0 輪」。
    四行之內自相矛盾，而沒有任何一行說它失敗了。
    """
    oa = _load_tool("forseti_probe_owner_audit", "owner-audit.py")
    import owner as O

    # 有 AI 輪也有 owner 回話的正常語料。
    normal_dir = tmp_path / "normal"
    normal_dir.mkdir()
    rows: list[str] = []
    for i in range(4):
        rows.append(_ai_line(f"我做完了第 {i} 件"))
        rows.append(_user_line("好，繼續" if i % 2 == 0 else "你把那個弄錯了"))
    (normal_dir / "a.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")

    # 對照：同樣那些 owner 訊息，但一個 AI 輪都沒有。
    empty_dir = tmp_path / "no_ai"
    empty_dir.mkdir()
    (empty_dir / "a.jsonl").write_text(
        "\n".join(r for r in rows if '"user"' in r) + "\n", encoding="utf-8")

    def run(d: Path) -> str:
        capsys.readouterr()
        oa.main(["--dir", str(d)])
        return capsys.readouterr().out

    normal = run(normal_dir)
    no_ai_turns = run(empty_dir)
    assert "沉默地圖　4 輪" in normal, "對照組壞了，正常那份應該有四輪"
    assert "沉默地圖　0 輪" in no_ai_turns, "對照組壞了"

    def boom(*a, **k):
        raise OSError(5, "input/output error")

    monkeypatch.setattr(O, "silence_map", boom)
    swallowed = run(normal_dir)
    monkeypatch.undo()

    assert swallowed == no_ai_turns, (
        "吞掉之後跟「真的沒有 AI 輪」現在分得出來了，站點改過")
    assert swallowed != normal

    # 同一份輸出裡兩個數字互相矛盾，而沒有一個字說它失敗。
    assert "1 個 session，4 則 owner 訊息" in swallowed
    assert "沉默地圖　0 輪" in swallowed
    assert not any(w in swallowed for w in ("讀不到", "失敗", "OSError", "算不到"))

# `reading-conformance.declared` 那一條行為量測**移走了，不是刪掉**。
#
# 那個站點 2026-09-17 修好了：讀不到補讀表現在回 `CANNOT_CHECK`，
# 不再假裝「表裡沒有這一份的記錄」。守它的五條在
# `tests/test_reading_conformance.py::TestReadingTableUnreadable`，
# 其中一條專門釘住「空表仍然是 NON_CONFORMANT」——
# 修這種假理由最容易順手把空表一起放寬。
#
# 這一組釘的是「此刻吞掉什麼」，所以站點修好之後留在這裡的量測
# 反而會變成一句過期的斷言。檔頭那兩張表已經跟著改。
