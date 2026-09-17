"""`.forseti/` 這個控制目錄，這一輪到底被誰寫過。

**2026-09-17 加這一組，是為了補掉上一輪自己寫下的缺口。**
上一輪在 `AUTO_CONTINUE_LOG.md` 留的原話是：

    攔截只攔 `handoff` 這一個模組，所以
    「`snapshot()` 完全不寫任何檔案」這句話**沒有被驗過**，
    這一輪也沒有寫成結論。

`tests/test_handoff.py` 的 `test_snapshot不寫交接檔寫的只有strands`
攔的是 `handoff.should_write` 與 `handoff.write` 兩個名字。
它證得了「`snapshot()` 不發交接指令」，**證不了**「`snapshot()`
不寫 `.forseti/` 底下的東西」—— 中間差的是別的模組。
這一組把攔截點從模組名往下搬到寫入動作本身。

搬下來之後第一次就看到 `handoff` 以外的寫入者。2026-09-17 06:5x
實測一次 `strands('')`，`.forseti/` 底下被寫 4 次、3 個相異位置：

    NEXT.md                      write_text
    cache/artifact_hashes.json   write_text
    cache/identity.json.tmp      write_text
    cache/identity.json          replace

`cache/` 底下一共有三個模組在寫，讀原始碼數出來的：
`identity.py:253`、`blast.py:385`、`contract.py:523` 與
`contract.py` 的 `recheck.json`。`identity` 那一支走的是
`tmp.write_text()` 加 `tmp.replace(f)`（`identity.py:286` 與 `:290`），
`blast.py:420` 是同一個形狀。**所以「`.forseti/` 底下只有交接檔
會被動」這句話是錯的**，而攔模組名的那條測試永遠看不到這件事。

守兩件：

一，`snapshot()` 在這個目錄底下一個位元組都不寫。這是
    §40 `pol-5fd00d9bc0` 那一筆歸因的**檔案系統層級版本**。
    哪天有人把任何一種寫入搬進 `snapshot()`，它每兩秒被輪詢一次，
    這個目錄就會變成每兩秒被改寫一次 —— 而那正是
    `MIN_GAP_S` 當初要擋的事。

二，`strands()` 寫的東西全部在白名單內。新增一個寫入者要先改這裡，
    改這裡的時候才會被問一句「這個檔為什麼要放在控制目錄底下」。

**這一組會真的讓寫入發生，不攔下來。** 攔下來量到的就不是真實行為了。
被寫到的是 `.forseti/NEXT.md` 與 `.forseti/cache/`，兩個都是
系統平常每一輪本來就在寫的東西，所以跑這一組等同跑一次輪詢，
不製造額外的狀態變更。
"""

from __future__ import annotations

import ast
import builtins
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

FORSETI = (ROOT / ".forseti").resolve()

#: `strands()` 准許寫在 `.forseti/` 底下的東西，用相對路徑的第一段比對。
#: `NEXT.md` 是交接檔（`handoff.py:270`），`cache` 底下是
#: `identity`、`blast`、`contract` 三支的快取。**這份清單是白名單
#: 不是紀錄**：
#: 多出來的東西要讓測試紅，不是讓測試跟著長。
#:
#: **`.forseti/probe_baseline.json` 刻意不在裡面。** 它就躺在同一層，
#: 而 `strands()` 確實會走到 `probe_panel`（`desktop_api.py:3189`）——
#: 但 `probe_panel` 只讀不寫，`record_baseline()`（`probe.py:584`）
#: 在 `desktop_api.py` 裡一個呼叫點都沒有（2185 行那個是註解裡提到）。
#: 所以它進不了這條路。哪天有人把它接上來，這條測試會紅，
#: 那時候要回答的是「基準線該不該每一輪被改寫」，不是把它加進白名單。
ALLOWED_TOP = {"NEXT.md", "cache"}


class _WriteSpy:
    """攔四種寫入動作，記下落在 `.forseti/` 底下的那些。

    四種是數出來的不是猜的：`apps/forseti-cli/*.py` 底下
    `write_text` 20 處、`open()` 寫模式 13 處、`write_bytes` 0 處、
    `os.replace` / `os.rename` 0 處，而 `Path.replace`
    有（`identity.py:290`、`blast.py:422`）。`write_bytes` 現在沒有人用，
    仍然攔著，因為新增一個用它的模組不該是無聲的。

    **第五種 `Path.open` 是 2026-09-17 補的，補之前這張網瞎掉一半。**
    `p.open("a")` 走的是 `Path.open`，**不經過 `builtins.open`** ——
    Python 3.9.6 實測：換掉 `builtins.open` 之後 `p.open("a")` 一次都
    攔不到，而檔案照樣寫出去。這個 repo 底下用這種寫法的有 13 處：
    `advicetrack.py:102`、`blockread.py:165`、`checkpoint.py:79`、
    `commit.py:81`、`coverage.py:294`、`event_ledger.py:351`、
    `forkline.py:178`、`gate.py:101`、`identity.py:499`、`notes.py:67`、
    `pollution.py:195`、`sufficiency.py:313`、`workflow.py:307`。
    **粉紅點、checkpoint、事件帳本、fork 的寫檔全部在這張名單上**，
    所以補這一種之前，上面那些「零寫入」的斷言證到的比它們宣稱的少。

    補進來之後 `Path.write_text` 會被記兩次（它內部呼叫 `self.open`），
    這是刻意留著的：`tops()` 與 `paths()` 都回集合，多記一次不影響判定，
    而把它去掉要靠猜哪一次是內層，猜錯就漏掉真的那一次。

    **`shutil` 不攔**：全檔只有 `which` 兩處與 `rmtree(tmp)` 四處
    （`goalgate.py`、`jsbridge.py`、`blast.py` 兩支 —— `blast.py`
    那兩處是 2026-09-17 補的，先前它借了臨時目錄不還，
    見 `tests/test_tempdir_cleanup.py`），沒有一處寫進這個目錄。
    這是讀過之後的決定，不是遺漏 —— 哪天有人用 `shutil.copy`
    寫進來，這個攔截網會看不到，所以寫在這裡。
    """

    def __init__(self, scope: Path | None = FORSETI) -> None:
        #: 只記落在 `scope` 底下的寫入。**`None` 代表整個檔案系統** ——
        #: 2026-09-17 加的，因為上一輪自己寫下「零寫入只驗了 `.forseti/`
        #: 底下，它會不會寫 repo 其他地方或家目錄沒有量」。
        #: 判定範圍是這一層的事，攔截網本身攔的是動作不是路徑，
        #: 所以放寬範圍不需要動下面任何一個 hook。
        self.scope = scope
        self.hits: list[tuple[str, str]] = []
        self.on = False
        self._orig: dict = {}

    def _under(self, p) -> bool:
        if self.scope is None:
            return True
        try:
            return str(Path(p).resolve()).startswith(str(self.scope))
        except Exception:
            return False

    def _note(self, kind: str, p) -> None:
        if self.on and self._under(p):
            try:
                self.hits.append((kind, str(Path(p).resolve())))
            except Exception:
                self.hits.append((kind, repr(p)))

    def __enter__(self) -> "_WriteSpy":
        self._orig = {
            "open": builtins.open,
            "write_text": Path.write_text,
            "write_bytes": Path.write_bytes,
            "replace": Path.replace,
            "path_open": Path.open,
        }
        o, wt, wb, rp, po = (self._orig[k] for k in
                             ("open", "write_text", "write_bytes",
                              "replace", "path_open"))
        spy = self

        def _open(file, mode="r", *a, **k):
            if any(c in mode for c in "wax+"):
                spy._note("open:" + mode, file)
            return o(file, mode, *a, **k)

        def _wt(self_, *a, **k):
            spy._note("write_text", self_)
            return wt(self_, *a, **k)

        def _wb(self_, *a, **k):
            spy._note("write_bytes", self_)
            return wb(self_, *a, **k)

        def _rp(self_, target):
            spy._note("replace", target)
            return rp(self_, target)

        def _po(self_, mode="r", *a, **k):
            if any(c in mode for c in "wax+"):
                spy._note("Path.open:" + mode, self_)
            return po(self_, mode, *a, **k)

        builtins.open = _open
        Path.write_text, Path.write_bytes, Path.replace = _wt, _wb, _rp
        Path.open = _po
        self.on = True
        return self

    def __exit__(self, *exc) -> None:
        self.on = False
        builtins.open = self._orig["open"]
        Path.write_text = self._orig["write_text"]
        Path.write_bytes = self._orig["write_bytes"]
        Path.replace = self._orig["replace"]
        Path.open = self._orig["path_open"]

    def paths(self) -> set[str]:
        """被寫到的相異絕對路徑。**用集合不是次數** ——
        `write_text` 一次會被記兩下（它內部呼叫 `self.open`），
        所以次數不是可以拿來斷言的東西，位置才是。
        """
        return {p for _, p in self.hits}

    def tops(self) -> set[str]:
        """被寫到的路徑，相對 `.forseti/` 的第一段。"""
        out = set()
        for _, p in self.hits:
            rel = Path(p).relative_to(FORSETI)
            out.add(rel.parts[0] if rel.parts else str(rel))
        return out


def test_snapshot在forseti底下一個檔案都不寫():
    """§40 `pol-5fd00d9bc0` 的檔案系統層級版本。

    那一筆登記的是一次錯掉的歸因：`snapshot()` 被說成
    「內部那一條路徑照樣寫成了」，讀完 `desktop_api.py:442`
    之後發現它整支十三行沒有一條路通到 `handoff`。
    那一輪的攔截只證得了「不通到 `handoff`」。
    這一條證的是更強的那句：**不通到這個目錄底下的任何檔案**。

    **這一條自己有一個弱點，寫在這裡不是補充是前提：**
    它斷言的是「沒攔到東西」，所以攔截網瞎掉的時候它會無聲通過。
    擋這件事的是同一個檔案裡的
    `test_攔截網蓋得到handoff實際用的那種寫法`，那一條自己造出
    三種寫法要求網攔得到。**那一條刪掉的話，這一條就變成一個
    永遠綠的裝飾品。**
    """
    import desktop_api as D

    with _WriteSpy() as spy:
        D.snapshot()

    assert spy.hits == [], (
        f"snapshot() 在 .forseti/ 底下寫了 {spy.hits}。"
        "它先前一個都不寫，而它每兩秒被輪詢一次 —— "
        "搬任何寫入進去之前要先重新決定節流，不是把這條測試調鬆。"
    )


def test_snapshot在整個檔案系統上一個檔案都不寫():
    """把判定範圍從 `.forseti/` 放到整個檔案系統。

    **上一輪自己標明的缺口，原話：** 「`snapshot()` 零寫入只驗了
    `.forseti/` 這個目錄底下。它會不會寫 repo 其他地方、或家目錄
    底下的東西，這一輪沒有量，也沒有寫成結論。」這一條把它量了。

    2026-09-17 在乾淨行程裡連跑三次，全檔案系統範圍都是 **0 次**。
    同一次量測下 `strands()` 每一次都寫四個檔，全部在 `$TMPDIR`：
    `forseti-js-*` 兩個（`jsbridge.py:186`）、`forseti-gac-*` 兩個
    （`goalgate.py:233`），所以這張網在放寬範圍之後確實看得到東西，
    不是「放寬了但什麼都攔不到」。

    **範圍放寬之後這一條比 `.forseti/` 那一條強，但沒有取代它。**
    那一條講的是控制目錄這個特定語意（`MIN_GAP_S` 當初要擋的事），
    這一條講的是「它根本不落地」。哪天有人讓 `snapshot()` 寫一個
    暫存檔到 `$TMPDIR`，`.forseti/` 那一條不會紅，這一條會。
    """
    import desktop_api as D

    with _WriteSpy(scope=None) as spy:
        D.snapshot()

    assert spy.hits == [], (
        f"snapshot() 寫了 {spy.hits}。它每兩秒被輪詢一次，"
        "所以任何一種落地都會變成每兩秒一次 —— "
        "`blast.py` 那 5713 個沒人收的臨時目錄就是這樣長出來的。"
    )


def test_strands寫的東西全部在白名單內():
    """`strands()` 會寫，但只准寫講得出理由的那幾個。

    **這一條刻意不斷言「至少寫了一次」，那個斷言是錯的。**
    第一版寫了，單獨跑綠、整套跑紅，紅的原因不是壞了是
    零次寫入本來就是合法狀態：`handoff.write()` 過不了
    `MIN_GAP_S = 240` 就不寫（`handoff.py:265`），
    三支快取的內容沒變就不寫。2026-09-17 同一個行程裡連跑三次實測：

        第 1 次 strands()：2 次 → identity.json.tmp、identity.json
        第 2 次 strands()：0 次
        第 3 次 strands()：0 次

    所以「零次」分不出「真的沒寫」跟「網瞎了」——
    **分這兩件事的是 `test_攔截網蓋得到handoff實際用的那種寫法`**，
    它自己造三種寫法出來，不依賴 `strands()` 這一輪心情如何。
    這一條只回答一個問題：寫出去的東西有沒有跑出白名單。
    """
    import desktop_api as D

    with _WriteSpy() as spy:
        D.strands("")

    extra = spy.tops() - ALLOWED_TOP
    assert not extra, (
        f"strands() 在 .forseti/ 底下寫了白名單以外的 {sorted(extra)}。"
        "這個目錄是控制檔的地方，多一個檔就多一個接手的人要判斷的東西 —— "
        "要加就改 ALLOWED_TOP，順便回答那個檔為什麼非得放這裡。"
    )


def test_攔截網蓋得到handoff實際用的那種寫法():
    """白名單測試靠這張網，所以網有沒有蓋到要單獨釘。

    `handoff.write()` 用的是 `p.write_text`（`handoff.py:270`），
    `identity._cache_write()` 用 `tmp.write_text` 加 `tmp.replace`
    （`identity.py:286`、`identity.py:290`）。**`Path.replace` 這一種
    是這一輪才補進網裡的** —— 第一版只攔 `builtins.open` 與
    `write_text`，漏掉 `Path.replace`，而 `os.replace` 全檔是 0 處，
    所以照著 `os.` 去 grep 會得到「沒有人用 replace」這個錯結論。
    """
    import handoff as HO

    spy = _WriteSpy()
    with spy:
        HO.write  # 名字存在就好，這裡不呼叫它，呼叫會動到真的交接檔
        p = FORSETI / "cache" / "_spy_selftest.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text("{}", encoding="utf-8")   # identity 用的第一步
        tmp.replace(p)                            # identity 用的第二步
        with open(p, "w", encoding="utf-8") as fh:  # open 的寫模式
            fh.write("{}")
    p.unlink(missing_ok=True)

    kinds = {k for k, _ in spy.hits}
    for need in ("write_text", "replace"):
        assert need in kinds, (
            f"這張網攔不到 {need}，而 identity._cache_write 就是用它寫的。"
            f"攔到的只有 {sorted(kinds)}。"
        )
    assert any(k.startswith("open:") for k in kinds), (
        f"這張網攔不到 open() 的寫模式，攔到的只有 {sorted(kinds)}。"
    )


def test_攔截網蓋得到PathOpen這種寫法():
    """`p.open("a")` 不經過 `builtins.open`，補這一種之前整張網瞎掉一半。

    **2026-09-17 實測（Python 3.9.6）：** 把 `builtins.open` 換掉之後
    執行 `p.open("a")`，攔到 0 次，而檔案確實寫出去了。所以
    「換掉 `builtins.open` 就看得到所有 `open`」這句話是錯的。

    **這一條不是補充是前提。** 這個檔案裡每一條「零寫入」的斷言，
    在 `Path.open` 沒被攔之前，證到的都比它們宣稱的少 ——
    而且少掉的正是最會寫東西的那一批：粉紅點（`notes.py:67`）、
    checkpoint（`checkpoint.py:79`）、事件帳本（`event_ledger.py:351`）、
    fork 寫新 session 檔（`forkline.py:178`），四個全部用這種寫法。

    這一條刪掉的話，下一個把 `Path.open` 從 `__enter__` 拿掉的人不會被擋。
    """
    spy = _WriteSpy(scope=None)
    with spy:
        p = FORSETI / "cache" / "_spy_pathopen_selftest.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:   # notes / checkpoint 用的那一種
            fh.write("{}\n")
    p.unlink(missing_ok=True)

    kinds = {k for k, _ in spy.hits}
    assert any(k.startswith("Path.open:") for k in kinds), (
        f"這張網攔不到 Path.open 的寫模式，攔到的只有 {sorted(kinds)}。"
        "notes.add、checkpoint.create、event_ledger、forkline 全部用它寫，"
        "攔不到的話這個檔案裡所有『零寫入』都是裝飾品。"
    )
    assert str(p) in spy.paths(), (
        f"攔到了但位置記錯，記到的是 {sorted(spy.paths())}"
    )


def test_用builtins_open攔不到PathOpen這件事本身():
    """釘住上面那條存在的理由，而不是只在註解裡寫「實測過」。

    **只攔 `builtins.open` 的那張網，對 `Path.open` 是全盲的。**
    哪天 Python 改成讓 `Path.open` 轉呼叫 `builtins.open`，這一條會紅 ——
    紅的時候要做的是刪掉這一條，不是把 `Path.open` 那個 hook 拿掉，
    因為現行版本上它仍然是唯一看得到那 13 個寫入點的東西。
    """
    seen: list = []
    orig = builtins.open

    def _o(f, mode="r", *a, **k):
        seen.append((str(f), mode))
        return orig(f, mode, *a, **k)

    target = FORSETI / "cache" / "_builtins_blindspot.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    builtins.open = _o
    try:
        with target.open("a", encoding="utf-8") as fh:
            fh.write("{}\n")
    finally:
        builtins.open = orig
    wrote = target.exists()
    target.unlink(missing_ok=True)

    assert wrote, "這一條自己壞了：檔案根本沒寫出去，所以證不了盲點"
    assert seen == [], (
        f"`builtins.open` 攔到了 {seen} —— 這個 Python 上 Path.open 會"
        "轉呼叫 builtins.open，那麼 `_WriteSpy` 的 Path.open hook 就不再是"
        "唯一來源。要刪的是這一條，不是那個 hook。"
    )


# ------------------------------------------- 另外那十五個入口（2026-09-17 加）
#
# 上面四條守的是 `snapshot()` 與 `strands()` 兩個入口。**畫面按得到的
# 不只這兩個** —— `desktop_api.main()` 的分派表有 20 個指令，
# `desktop/src-tauri/src/main.rs` 各有一個 `#[tauri::command]` 對應。
# 先前另外十八個沒有任何測試在看它們往 `.forseti/` 底下寫了什麼。
#
# 2026-09-17 逐個實測一次（乾淨行程，攔截範圍是整個檔案系統）：
#
#     snapshot 0、sessions 0、spec_reading 0、block_reading 0、
#     sufficiency 0、machine 0、work 0、pollution 0、workflow 0、
#     identity 0、sot 0、timeline 0
#     strands 8（4 個 $TMPDIR + cache/identity.json{,.tmp} + cache/
#                artifact_hashes.json + NEXT.md）
#     audit 8（全部在 $TMPDIR，forseti-js-* 與 forseti-gac-* 各兩組）
#     features 2、selftest 2（都在 $TMPDIR，走 TemporaryDirectory()
#                            上下文管理器，自己收）
#     blast_detail 冷快取 4（2 個 $TMPDIR + cache/blast.json{,.tmp}），
#                  熱快取 0
#
# **`blast_detail` 那兩個 `.forseti/cache/` 的寫入，先前一條測試都沒有
# 看過。** 它不在 `strands()` 那條路上，所以上面那條白名單測試碰不到它。

#: 不改變狀態的指令，值是怎麼呼叫它。**這不是一份紀錄是一份分類**：
#: 分派表多一個指令，下面那條覆蓋測試就會紅，紅的時候要回答的是
#: 「這個新指令會不會寫控制檔」，不是把名字補進來讓它變綠。
#:
#: `blast_detail` 的參數挑 `blast.py` 自己，因為它一定在圖裡 ——
#: 挑一個不在圖裡的路徑，`blast.detail()` 會回 `known: False` 而
#: 早在走到快取之前就 return，於是這一格會變成永遠零寫入的裝飾品。
READ_ONLY_CMDS: dict[str, str] = {
    "snapshot": "snapshot",
    "sessions": "sessions",
    "audit": "audit",
    "spec_reading": "spec_reading",
    "block_reading": "block_reading",
    "sufficiency": "sufficiency_state",
    "features": "features",
    "selftest": "selftest",
    "machine": "machine",
    "work": "work",
    "blast_detail": "blast_detail",
    "pollution": "pollution_panel",
    "workflow": "workflow_panel",
    "identity": "identity_panel",
    "sot": "sot_panel",
    "timeline": "timeline",
    "strands": "strands",
}

#: 會改變狀態的指令，**故意不在上面那組跑**。
#: `act` 會收尾任務、`note_add` 會留粉紅點、`fork` 會開新 session 檔，
#: 三個都是 owner 按下去才該發生的狀態轉換（§30、§5.5、§17）。
#: 一條測試不該替她按。
STATE_CHANGING_CMDS = frozenset({"note_add", "act", "fork"})


def _dispatch_cmds() -> set[str]:
    """`desktop_api.main()` 分派表裡的指令名，從語法樹讀不是用 grep。

    用 grep 的話 `cmd == "x"` 這個字串出現在註解或別的函式裡也會算進來，
    而這條測試的整個意義是「分派表多一個就要紅」，多算或少算都讓它失效。
    """
    src = (ROOT / "apps" / "forseti-cli" / "desktop_api.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
    assert fn is not None, "`desktop_api.main()` 不見了"
    out: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "cmd"):
            continue
        for op, cmp_ in zip(node.ops, node.comparators):
            if isinstance(op, ast.Eq) and isinstance(cmp_, ast.Constant) \
                    and isinstance(cmp_.value, str):
                out.add(cmp_.value)
    return out


def test_分派表裡每一個指令都被分類過():
    """新增一個畫面指令，這一條會紅，逼人回答它會不會寫控制檔。

    **這一條是下面那條的前提。** 下面那條只跑
    `READ_ONLY_CMDS` 裡列的東西 —— 沒有這一條的話，
    新增一個會寫 `.forseti/` 的指令只要不加進那份清單，
    整組測試會繼續全綠，而那正是「白名單跟著長」的形狀。
    """
    found = _dispatch_cmds()
    assert found, "從語法樹一個指令都讀不到，這條測試自己壞了"
    classified = set(READ_ONLY_CMDS) | STATE_CHANGING_CMDS
    missing = found - classified
    stale = classified - found
    assert not missing, (
        f"分派表裡的 {sorted(missing)} 沒有被分類。"
        "會改變狀態就放 STATE_CHANGING_CMDS，不會就放 READ_ONLY_CMDS —— "
        "放進 READ_ONLY_CMDS 等於宣告它寫的東西全部在白名單內。"
    )
    assert not stale, (
        f"{sorted(stale)} 列在分類裡但分派表沒有。"
        "指令被刪掉或改名了，清單要跟著改。"
    )


@pytest.mark.parametrize("cmd", sorted(READ_ONLY_CMDS))
def test_每一個唯讀指令寫的東西都在白名單內(cmd):
    """十七個入口，每一個都問同一句：有沒有寫出白名單以外的東西。

    **這一條不斷言「至少寫了一次」**，理由跟上面那條
    `test_strands寫的東西全部在白名單內` 一模一樣：零次寫入是合法狀態
    （快取沒變就不寫、`MIN_GAP_S` 沒到就不寫），
    所以零次分不出「真的沒寫」跟「網瞎了」。
    分那兩件事的是 `test_攔截網蓋得到handoff實際用的那種寫法`。

    **這一組會真的讓寫入發生，不攔下來。** 十七個指令是畫面上每一輪
    本來就在跑的東西，跑一次等於使用者切過一輪分頁，
    不製造額外的狀態變更 —— 會改變狀態的三個在 `STATE_CHANGING_CMDS`，
    這裡一個都不碰。
    """
    import desktop_api as D
    import tracker as TK

    fn = getattr(D, READ_ONLY_CMDS[cmd])
    if cmd == "timeline":
        call = lambda: fn(TK.latest_session())          # noqa: E731
    elif cmd == "blast_detail":
        call = lambda: fn("apps/forseti-cli/blast.py")  # noqa: E731
    elif cmd in ("strands", "sufficiency"):
        call = lambda: fn("")                           # noqa: E731
    else:
        call = fn

    with _WriteSpy() as spy:
        call()

    extra = spy.tops() - ALLOWED_TOP
    assert not extra, (
        f"`{cmd}` 在 .forseti/ 底下寫了白名單以外的 {sorted(extra)}。"
        "這個目錄是控制檔的地方，多一個檔就多一個接手的人要判斷的東西 —— "
        "要加就改 ALLOWED_TOP，順便回答那個檔為什麼非得放這裡。"
    )
