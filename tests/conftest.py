"""跑測試的時候，正本 `.forseti/` 被哪一條測試動到。

**2026-09-17 加這一支，補的是上一輪（5ai）自己寫下的那個缺口。**
原話在 `AUTO_CONTINUE_LOG.md`：

    跑全套測試會寫到正本的 `.forseti/NEXT.md`（實測 mtime 從
    09:33:20 跳到 09:49:50，那段時間只有 pytest 在跑）。
    這是既有行為不是這一輪造成的，但它讓「測試不碰正本」這個前提
    有一個缺口，沒有量是哪一條測試寫的。

「測試不碰正本」是 `tests/test_forseti_dir_writes.py` 與
`tests/test_module_write_targets.py` 兩組共同的**前提**。
前提沒人守跟沒有前提一樣 —— 而上一輪量到的那個 mtime 跳動，
證明這個前提此刻並不成立，只是不知道是誰。

## 量的方式，以及為什麼不用 `_WriteSpy`

`test_forseti_dir_writes._WriteSpy` 攔的是 `builtins.open` 與
`Path` 上那幾支寫入方法。它在單一函式的範圍內好用，但拿來罩整個
測試流程有兩個問題：一，它攔不到 sqlite3 與子行程（那兩個洞
`test_module_write_targets.py` 的 docstring 已經釘住）；二，全套裡
本來就有好幾條自己在 patch `builtins.open`，兩層 patch 疊起來
量到的不會是真實行為。

所以這一支不攔任何東西，改成**每一條測試前後各掃一次目錄**，
比對 `(相對路徑, mtime_ns, 大小)`。掃的是結果不是動作，
所以 sqlite、`shutil`、子行程、C 層寫入一律看得到。

## 這個量法看不到什麼（是前提不是補充）

**一條測試裡面先建檔再刪掉，前後兩次掃出來一樣，這一支看不到。**
它量的是「這條測試結束之後，目錄跟開始前有沒有不同」，
不是「這條測試期間發生過幾次寫入」。要量後者得攔動作，
那是 `_WriteSpy` 的範圍。兩個問的不是同一題，所以兩個都要留著。

**它分不出寫入者。** 這一條比上一條嚴重，而且 2026-09-17 真的
咬了一次。掃描量的是時間窗前後的差，所以那段時間裡**任何人**的
寫入都會被記在當時在跑的那一條測試頭上 —— 包含外部程序。
實測:`test_ui_render.py` 那一條跑 71 秒，期間別的 session 結束了
一次回合，Claude Code 的 Stop hook（`.claude/settings.json` →
`hooks/forseti-stop-hook.mjs:112`）往 `.forseti/event_ledger.jsonl`
接了一筆，於是那一筆被判成「這條測試動了正本」。
單獨重跑，一模一樣的 +669 位元組再現。

**測試跑得越久，被誤記的機會越大** —— 也就是說這個誤差不是隨機的，
它偏向最慢的那幾條。

補的辦法是 `_APPENDED`:內容自己帶著來源，所以讀內容分得出來，
看時間分不出來。判斷在 `test_zz_forseti_write_attribution.py` 的
`_written_by_external_hook()`，不在這一支 —— 這一支只負責讀回來。

`tests/test_zz_forseti_write_attribution.py` 那一組守這裡量出來的東西。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORSETI_DIR = (ROOT / ".forseti").resolve()

# nodeid -> 這條測試結束後，跟開始前不一樣的相對路徑（排序過）
_RECORD: dict[str, list[str]] = {}
# nodeid -> {相對路徑: 這條測試期間被接在檔尾的那一段原文}
#
# **這一份存在的理由是實測出來的。** 2026-09-17：
# `test_ui_render.py::TabsMatchData::test_切過去之後別頁不會同時亮著`
# 被記成動了 `event_ledger.jsonl`，而那一段內容讀出來是
# `{"provider":"claude-code","provider_event_type":"Stop",...}` ——
# Claude Code 的 Stop hook 寫的（`hooks/forseti-stop-hook.mjs:112`）。
# 那一條測試跑 71 秒，窗口夠長剛好罩到一次外部回合結束。
#
# 上面那張 `_RECORD` 量的是「這段時間這個檔變了」，
# 它**永遠分不出是誰寫的** —— 時間窗裡的每一次寫入都會被記在
# 當時在跑的那一條頭上，不管寫的人是不是它。
# 要分得出來，唯一的路是讀寫進去的內容，因為內容自己帶著來源。
_APPENDED: dict[str, dict[str, str]] = {}
# 掃描期間 stat 不到的路徑，不靜默吞掉（§5ai 那一輪的教訓）
_SCAN_ERRORS: list[str] = []
# 這一輪從什麼時候開始跑。守門那一組要拿它算「節流窗開過幾次」。
_T0: float | None = None


#: exFAT 的 AppleDouble sidecar。NewDrive 是 exFAT，macOS 會替檔案
#: 自動建這種 `._` 開頭的檔，**不是任何程式寫的**。把它算成一次寫入
#: 等於把檔案系統的行為記在某一條測試頭上。
#:
#: **這裡只排除這一種。** 「哪些路徑算動到正本」是判斷，不是觀測，
#: 那個判斷在 `test_zz_forseti_write_attribution._allowed()`。
#: 兩邊各寫一份會分歧，而分歧的那天沒有人會發現。
SKIP_PREFIX = "._"


def _skip(rel: str) -> bool:
    """這個路徑是不是檔案系統自己長出來的東西。"""
    return any(part.startswith(SKIP_PREFIX) for part in Path(rel).parts)


def _snapshot(root: Path = FORSETI_DIR) -> dict[str, tuple[int, int]]:
    """把目錄底下每個檔案的 (mtime_ns, 大小) 掃成一張表。

    掃不到的不當成不存在，記進 `_SCAN_ERRORS`，
    因為「掃不到」跟「沒有這個檔」在比對的時候長得一樣。

    **2026-09-17：sidecar 不算。** 其餘一律照實記，
    包含 `cache/` 底下的東西 —— 那些要不要算成「動到正本」
    是判斷，判斷在 `_allowed()` 那裡，不在這支。
    """
    out: dict[str, tuple[int, int]] = {}
    if not root.exists():
        return out
    for p in root.rglob("*"):
        try:
            st = p.stat()
        except OSError as exc:
            _SCAN_ERRORS.append(f"{p}: {exc}")
            continue
        if not p.is_file():
            continue
        rel = str(p.relative_to(root))
        if _skip(rel):
            continue
        out[rel] = (st.st_mtime_ns, st.st_size)
    return out


def _diff(
    before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]
) -> list[str]:
    """兩張表之間不一樣的相對路徑：新增、刪除、內容或時間變過的都算。"""
    changed = set()
    for k, v in after.items():
        if before.get(k) != v:
            changed.add(k)
    for k in before:
        if k not in after:
            changed.add(k)
    return sorted(changed)


#: 讀回來的新增段最多留這麼多位元組。超過就整段不留 ——
#: 留一半會讓判斷層讀到切斷的 JSON，而切斷的 JSON 跟「格式不對」
#: 長得一模一樣，於是一個量得到的東西會被誤判成量不到。
APPEND_CAPTURE_LIMIT = 256 * 1024


def _appended(rel: str, before_size: int, after_size: int,
              root: Path = FORSETI_DIR) -> str | None:
    """檔案變大的時候，把多出來的那一段位元組讀回來。

    **只讀尾巴，不驗前面那一段有沒有被改過。** 驗前綴要在每一條
    測試前後對整個目錄多跑一次雜湊，那個成本會讓這支量測本身
    變成拖慢全套的原因。

    代價由判斷層吸收，方向是安全的：前面被改過的話，從
    `before_size` 讀起會切在某一行中間，解不出 JSON ——
    而判斷層的規則是**解不出來就不放行**。所以這個省略
    只會多紅，不會少紅。

    讀不到、太大、或者不是文字，一律回 `None`（= 沒有量到），
    不回空字串 —— 空字串在判斷層跟「量到了而且是空的」同形。
    """
    n = after_size - before_size
    if n <= 0 or n > APPEND_CAPTURE_LIMIT:
        return None
    try:
        with (root / rel).open("rb") as f:
            f.seek(before_size)
            blob = f.read(n)
    except OSError as exc:
        _SCAN_ERRORS.append(f"{rel}: 讀新增段失敗 {exc}")
        return None
    try:
        return blob.decode("utf-8")
    except UnicodeDecodeError:
        return None


def append_record() -> dict[str, dict[str, str]]:
    """給判斷層讀的。回傳複本，讀的人改不到正本。"""
    return {k: dict(v) for k, v in _APPENDED.items() if v}


def write_record() -> dict[str, list[str]]:
    """給守門那一組讀的。回傳的是複本，讀的人改不到正本。"""
    return {k: list(v) for k, v in _RECORD.items() if v}


def scan_errors() -> list[str]:
    return list(_SCAN_ERRORS)


def session_elapsed_s() -> float:
    """這一輪到目前為止跑了幾秒。

    **不是統計用的，是守門算得出上界用的。** `handoff.MIN_GAP_S`
    那個節流是對時間的，所以「一輪最多寫得成幾次」取決於這一輪
    有多長 —— 一輪比節流窗短的時候是 1 次，比它長就不是。
    2026-09-17 實測全套從 217 秒漲到 301 秒，跨過 240 秒那條線，
    於是寫入者變成 2 條，而那是節流在正常運作，不是失效。

    沒有掛上 `pytest_configure` 的時候回 0.0，
    讓守門那一條退回最嚴的界，而不是靜默放寬。
    """
    return 0.0 if _T0 is None else time.monotonic() - _T0


def pytest_configure(config):
    """把這支模組本身掛到 config 上。

    守門那一組要拿到的是 **pytest 載入的這一份**。它如果自己
    `import conftest`，在某些 import 模式下會拿到另一份新載入的模組，
    那一份的 `_RECORD` 永遠是空的 —— 而空的記錄表看起來跟
    「沒有人動正本」一模一樣。這是這個專案踩過很多次的形狀。
    """
    global _T0
    _T0 = time.monotonic()
    config._forseti_recorder = sys.modules[__name__]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """罩住 setup / call / teardown 整段，不是只罩 call。

    fixture 的 teardown 也會寫檔，只罩 call 會把那些算在下一條頭上。
    """
    before = _snapshot()
    yield
    after = _snapshot()
    changed = _diff(before, after)
    _RECORD[item.nodeid] = changed

    # 變動的檔裡面，純粹長大的那些，把長出來的那一段留下來。
    # 判斷層要拿它分辨「這條測試寫的」跟「別人在這段時間寫的」。
    caps: dict[str, str] = {}
    for rel in changed:
        b, a = before.get(rel), after.get(rel)
        if b is None or a is None:
            continue
        blob = _appended(rel, b[1], a[1])
        if blob is not None:
            caps[rel] = blob
    if caps:
        _APPENDED[item.nodeid] = caps


def pytest_sessionfinish(session, exitstatus):
    """設了環境變數才把量到的東西倒出來，預設什麼都不寫。"""
    out = os.environ.get("FORSETI_WRITE_ATTRIBUTION_OUT")
    if not out:
        return
    payload = {
        "writers": write_record(),
        "appended": append_record(),
        "scan_errors": scan_errors(),
        "total_tests": len(_RECORD),
    }
    Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
