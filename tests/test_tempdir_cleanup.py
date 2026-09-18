"""借了臨時目錄的，有沒有還。

**2026-09-17 加這一組，起因是上一輪自己寫下的缺口。** 上一輪在
`AUTO_CONTINUE_LOG.md` 留的原話是：

    `snapshot()` 零寫入只驗了 `.forseti/` 這個目錄底下。
    它會不會寫 repo 其他地方、或家目錄底下的東西，這一輪沒有量。

這一輪把攔截網的判定範圍從 `.forseti/` 放到整個檔案系統，量出來
`snapshot()` 連跑三次都是 **0 次寫入**，所以上一輪那句話成立。
**但同一次量測看到 `strands()` 每一輪都在 `.forseti/` 外面寫**，
一次四個檔、兩個臨時目錄：

    $TMPDIR/forseti-js-*/run.mjs   payload.json    jsbridge.py:186
    $TMPDIR/forseti-gac-*/run.mjs  payload.json    goalgate.py:233

那兩支都有 `finally: shutil.rmtree`（`jsbridge.py:202`、
`goalgate.py:249`），所以寫完就收掉。**而 `blast.py` 的兩支沒有。**
2026-09-17 07:2x 在 `$TMPDIR` 底下實際數到：

    forseti-blast-*     2732 個
    forseti-blast-d-*   2981 個
    合計 5713 個目錄，全部是 {run.mjs, payload.json}
    （逐個比對過內容形狀，異常 0 個）。**兩個大小數字都是真的，
    量的不是同一件事**：檔案內容加起來 57.2MB，`du -shc` 報 84MB，
    差額是 5713 個目錄本身的配置區塊。清掉的時候實際釋出 57.2MB。

同一個 `$TMPDIR` 當時有 57575 個項目。這不是「暫存檔沒清乾淨」這種
整潔問題 —— `vectors()` 每次指紋變了就走一次，而指紋每一輪都可能變，
所以它是隨開發時間線性成長的。

**這一組守的是「還」這個動作，不是「借」。** 借臨時目錄是對的，
四支都該借；漏的是其中兩支沒有 `finally`。
"""

from __future__ import annotations

import ast
import glob
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "apps" / "forseti-cli"
TOOLS = ROOT / "tools"
sys.path.insert(0, str(CLI))

def _count(prefix: str) -> int:
    """數**當下**那個暫存區底下的同前綴目錄。

    不快取成模組層常數，因為 `box` fixture 會把 `tempfile.tempdir`
    導到一個隔離目錄，而這一支必須跟著走 —— 數的地方跟被測程式借的
    地方要是同一個，否則 before 與 after 量的不是同一件事。
    """
    return len(glob.glob(str(Path(tempfile.gettempdir()) / (prefix + "*"))))


def _fake_repo() -> Path:
    """一個夠 `blast` 走完 node 那條路的最小 repo。

    `src` 用符號連結指回真的那份，**不複製**：真的 `src/` 有 15MB，
    而這一組要驗的是收尾不是解析，複製一次只是讓測試變慢。
    符號連結對 `src.is_dir()` 是 True，`pathlib` 的 `rglob`
    預設不跟著目錄連結遞迴，所以掃描不會走進去。

    每一次都開一個新的 box，所以 `_cache_get()` 必定落空 ——
    落空才會走到 `mkdtemp`。快取命中那條路提早 return，
    根本不借臨時目錄，那樣這一組會變成永遠綠的裝飾品。
    """
    box = Path(tempfile.mkdtemp(prefix="forseti-cleanup-test-"))
    (box / "src").symlink_to(ROOT / "src")
    return box


@pytest.fixture()
def box():
    """假 repo，外加**把暫存區隔離掉**。

    2026-09-18 加隔離，起因是這兩條 behavioral 測試原本數的是全域
    `$TMPDIR`。那個目錄是整台機器共用的：桌面版每一輪 `strands()` 都會
    走到 `blast.summary()`（`desktop_api.py:3345`），而它借的正是
    `forseti-blast-*` 這個前綴。於是只要在 before 與 after 中間有另一個
    程序借了還沒還，這兩條就紅，而且紅的訊息是
    「借了臨時目錄沒還」—— 一句指著 `blast.py` 的**假指控**。

    決定性復現在 2026-09-18 做過：外掛包住 `vectors()` 與 `detail()`，
    在回傳之後於真系統 `$TMPDIR` 建一個同前綴目錄（模擬外部程序），
    兩條立刻紅，訊息就是那句假指控。隔離之後同一個注入不再讓它紅。

    **隔離不會讓它變成裝飾品。** blast 真的不還的話，目錄會留在這個
    隔離目錄裡，`after > before` 照樣紅；隔離擋掉的只有「別人的目錄」。

    `tempfile.tempdir` 是 `tempfile` 官方的覆寫點，`mkdtemp()` 不帶
    `dir=` 時就看它。`blast.py:667` 與 `:893` 兩處都不帶 `dir=`
    （這一輪查過），所以導得到。還原放在 `finally`，因為它是行程全域的。
    """
    b = _fake_repo()
    iso = b / "tmp"
    iso.mkdir()
    old = tempfile.tempdir
    tempfile.tempdir = str(iso)
    try:
        yield b
    finally:
        tempfile.tempdir = old
        shutil.rmtree(b, ignore_errors=True)


@pytest.fixture()
def iso_tmp():
    """**只隔離暫存區**，不造假 repo。

    `jsbridge` 與 `goalgate` 跟 `blast` 不一樣：它們的 `SRC` 是模組層
    的 `REPO / "src"`（`jsbridge.py:42`、`goalgate.py` 同一套），
    吃的是真的那一份，不接受 `root=`。所以那兩支要的只有隔離。

    隔離的理由跟 `box` 同一條，寫在那裡不重複。
    """
    d = Path(tempfile.mkdtemp(prefix="forseti-iso-test-"))
    old = tempfile.tempdir
    tempfile.tempdir = str(d)
    try:
        yield d
    finally:
        tempfile.tempdir = old
        shutil.rmtree(d, ignore_errors=True)


class _Strand:
    """一輪對話，剛好餵得進 `jsbridge._shape()`。

    三個欄位都是照 `jsbridge.py:155-170` 讀出來的：`ai_text` 要非空
    而且要打到 `_WORTH`（「全部」「所有的」「檢查過」那組字），
    否則 `_shape()` 過濾掉它，`scan()` 在 `mkdtemp` 之前就 return ——
    那樣這一條會綠，而綠的理由是根本沒走到要驗的那一段。
    """

    n = 1
    ai_text = "我全部檢查過了，所有的檔案都沒問題"
    dots: list = []


def test_執行層偵測器不留臨時目錄(iso_tmp):
    """`jsbridge.scan()` 借的 `forseti-js-*`，回來的時候要不見了。

    **2026-09-18 補這一條，理由是上一輪自己寫下的缺口。** 上一輪
    在 `AUTO_CONTINUE_LOG.md` 的原話：「這一輪只查了 `forseti-blast-`
    這兩個前綴。`jsbridge.py:186` 的 `forseti-js-*` 與
    `goalgate.py:233` 的 `forseti-gac-*` 有沒有測試在數全域計數，沒查」。

    查完的答案是**沒有任何 behavioral 測試在驗那兩支**，只有原始碼層
    那一條在看結構 —— 而結構看得到的東西有限：同一輪就抓到
    `jsbridge` 借完之後先做兩個 `write_text` 才進 `try`，
    而舊版那條原始碼守門對它是綠的。

    `checked` 那個斷言是防呆，理由同 `vectors()` 那條的 `cached`：
    `_shape()` 濾掉所有輪的時候 `scan()` 提早 return，
    沒有它這一條會在沒走到 `mkdtemp` 的情況下變成永遠綠。
    """
    import jsbridge as JB

    if not JB.available().get("ok"):
        pytest.skip("這台沒有 node 或找不到 src/，走不到 mkdtemp 那條路")

    before = _count("forseti-js-")
    out = JB.scan([_Strand()])
    after = _count("forseti-js-")

    assert out.get("ok") is True, f"node 那條路沒走通：{out.get('why')}"
    assert out.get("checked"), "沒有一輪送進去，這一條驗不到東西"
    assert after == before, (
        f"scan() 借了臨時目錄沒還，{before} → {after}。"
        "收的地方是 jsbridge.py 的 finally。"
    )


def test_算GAC不留臨時目錄(iso_tmp):
    """`goalgate.gac()` 借的 `forseti-gac-*`，回來的時候要不見了。

    這一支**不要求 `ok` 是 True**，跟上面那條不一樣。GAC 算得出來
    要 `scope_match`，而那一欄規格沒有定義、owner 還沒定
    （`NEXT.md`「還沒解決的」那一條），所以 `gac()` 回 ok=False 是
    現在的正常狀態。這一條驗的是**借了有沒有還**，不是算不算得出來。

    分辨「走到 mkdtemp」與「提早 return」靠 `why`：找不到 node 或
    找不到 `src/` 的時候它在 `mkdtemp` 之前就 return，那兩種在上面
    被 skip 掉了。
    """
    import goalgate as GG

    if not GG.node_bin() or not GG.SRC.is_dir():
        pytest.skip("這台沒有 node 或找不到 src/，走不到 mkdtemp 那條路")

    before = _count("forseti-gac-")
    out = GG.gac([{"text": "北極星", "kind": "goal"}])
    after = _count("forseti-gac-")

    assert isinstance(out, dict) and "gac" in out, f"回的形狀不對：{out}"
    assert after == before, (
        f"gac() 借了臨時目錄沒還，{before} → {after}。"
        "收的地方是 goalgate.py 的 finally。"
    )


def test_算代價向量不留臨時目錄(box):
    """`blast.vectors()` 借的那個目錄，回來的時候要不見了。

    **`cached is False` 這個斷言是這一條的防呆。** 沒有它的話，
    快取命中時函式在 `mkdtemp` 之前就 return，臨時目錄數當然沒變，
    而這一條會綠 —— 綠的理由卻是「根本沒走到要驗的那段」。
    """
    import blast as B

    if not B._node_bin():
        pytest.skip("這台沒有 node，走不到 mkdtemp 那條路")

    before = _count("forseti-blast-")
    out = B.vectors(root=box)
    after = _count("forseti-blast-")

    assert out.get("has") is True, f"node 那條路沒走通：{out.get('why')}"
    assert out.get("cached") is False, "吃到快取就沒有借目錄，這一條驗不到東西"
    assert after == before, (
        f"vectors() 借了臨時目錄沒還，{before} → {after}。"
        "這一支每輪指紋變了就走一次，不收的話是隨時間線性成長的 —— "
        "2026-09-17 實測累積 5713 個。收的地方是 blast.py 的 finally。"
    )


def test_算單點細節不留臨時目錄(box):
    """`blast.detail()` 是同一個形狀的另一半，前綴不同要分開數。

    target 從 `vectors()` 的結果裡拿真的節點名，不自己編一個：
    圖裡沒有那個節點的話 `detail()` 在 `mkdtemp` 之前就 return。
    """
    import blast as B

    if not B._node_bin():
        pytest.skip("這台沒有 node，走不到 mkdtemp 那條路")

    v = B.vectors(root=box)
    assert v.get("has") is True, f"前置的 vectors() 就沒過：{v.get('why')}"
    node = (v.get("top") or [{}])[0].get("target")
    assert node, f"拿不到真的節點名，vectors() 回的是 {list(v)}"

    before = _count("forseti-blast-d-")
    out = B.detail(node, root=box)
    after = _count("forseti-blast-d-")

    assert out.get("has") is True, f"node 那條路沒走通：{out.get('why')}"
    assert after == before, (
        f"detail() 借了臨時目錄沒還，{before} → {after}。"
    )


def _protecting_try(node: ast.AST) -> bool:
    """這個 `Try` 的 `finally` 裡有沒有 `rmtree`。"""
    return isinstance(node, ast.Try) and any(
        isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr == "rmtree"
        for stmt in node.finalbody
        for c in ast.walk(stmt)
    )


def _borrow_sites(fn: ast.AST) -> list[tuple[int, bool]]:
    """函式裡每一個 `mkdtemp`，以及它借到的東西**有沒有被罩住**。

    罩住只有兩種形狀算數：

    一，`mkdtemp` 本身就在那個 `try` 的區塊裡面。
    二，`mkdtemp` 那一個敘述的**下一個敘述**就是那個 `try`。

    中間夾任何別的敘述都不算 —— 那正是 2026-09-18 抓到的漏法：
    `jsbridge.py` 借完之後先做兩個 `write_text` 才進 `try`，
    寫檔丟 OSError 的時候目錄留在那裡沒人收。
    """
    out: list[tuple[int, bool]] = []

    def walk_body(body: list, protected: bool) -> None:
        for i, stmt in enumerate(body):
            borrows = [
                n for n in ast.walk(stmt)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "mkdtemp"
            ]
            if borrows:
                nxt = body[i + 1] if i + 1 < len(body) else None
                ok = protected or _protecting_try(nxt)
                # `try` 自己那一個敘述裡有 mkdtemp 的話，底下遞迴會
                # 再數一次，所以這裡只算不是 Try 的那些。
                if not isinstance(stmt, ast.Try):
                    for b in borrows:
                        out.append((b.lineno, ok))
            for name in ("body", "orelse", "finalbody"):
                sub = getattr(stmt, name, None)
                if isinstance(sub, list) and sub and isinstance(sub[0], ast.stmt):
                    walk_body(
                        sub,
                        protected or (name == "body" and _protecting_try(stmt)),
                    )

    walk_body(list(getattr(fn, "body", [])), False)
    return out


def test_每一個mkdtemp都有人收():
    """原始碼層級：借了目錄的，同一支要有 `finally` 收。

    **2026-09-18 把掃描範圍從 `apps/forseti-cli` 放到也含 `tools/`。**
    上一輪把「要不要納入 tools/」寫成一個決定，理由是「那三支是開發
    工具不是執行路徑，判準可能不同」。這一輪去看了，三支修完之後
    **全部符合這裡本來那條判準**，所以那個決定不需要做：沒有新判準，
    就沒有要挑的東西。修之前它們確實不符合，而且在漏：
    `ui-render-check.py` 的 raise 路徑留了 188 個目錄 130MB，
    `ui-harness.py` 整支沒有 `rmtree` 留了 44 個 42MB。

    **behavioral 那幾條蓋不到新增的第五支。** 哪天有人在別的模組
    再借一個，那幾條不會紅（它們只數已知的四個前綴），而這一條會。

    要求 `rmtree` 在 `finally` 裡而不只是在函式內某處，是因為
    這四支全部都有提早 return 的路徑（`TimeoutExpired`、`OSError`、
    `returncode != 0`）。寫在 try 尾巴的收尾在那些路徑上不會執行 ——
    而 node 逾時正是最需要收的那一次。

    **2026-09-18 補強：從「函式裡有沒有那個 try」改成「這一次借有沒有
    被罩住」。** 舊版問的是 `any(Try in fn)`，所以只要函式裡某處有
    一個帶 rmtree 的 finally 就算過 —— 而 `jsbridge.scan()` 當時
    正是借完之後先做兩個 `write_text` 才進 `try`，舊版對它是綠的
    （2026-09-18 拿舊版原始碼實測，`1 passed`）。決定性復現是把
    `Path.write_text` 換成丟 OSError：舊版一次留一個 `forseti-js-*`，
    而且 OSError 逸出那一支。

    **這一條的非空斷言是必要的**：掃描壞掉時「每一個都有人收」
    會在零個站點上成立。所以下面釘死站點數不得少於已知的四個。
    """
    sites: list[tuple[str, int, bool]] = []

    # `._*.py` 是 exFAT 上的 AppleDouble 附屬檔，不是原始碼，
    # 讀下去會是 UnicodeDecodeError。整個 repo 一律這樣濾
    # （`desktop_api.py:2603`、`ledger.py:825`、`jsbridge.py:74`）。
    for f in sorted(x for d in (CLI, TOOLS) for x in d.glob("*.py")
                    if not x.name.startswith("._")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for lineno, ok in _borrow_sites(fn):
                sites.append((f"{f.relative_to(ROOT)}:{fn.name}", lineno, ok))

    assert len(sites) >= 7, (
        f"只掃到 {len(sites)} 個 mkdtemp，已知有七個"
        "（jsbridge、goalgate、blast 兩支，加上 tools/ 的 "
        "ui-render-check、ui-harness、probe-stress）。掃描壞掉的時候，"
        "「每一個都有人收」會在零個站點上無聲成立。"
    )
    missing = [f"{w}（第 {ln} 行）" for w, ln, ok in sites if not ok]
    assert not missing, (
        f"這幾支借了臨時目錄，借到進 try 之間沒有被罩住：{missing}。"
        "寫在 try 尾巴不算 —— 那幾支都有提早 return 的路徑，"
        "而 node 逾時正是最需要收的那一次。中間夾 write_text 也不算："
        "寫檔丟 OSError 的時候目錄就留在那裡了。"
    )


def test_借了之後叫不動node的時候回的理由不指控錯人():
    """OSError 的 `why` 要說出是**哪一段**失敗，不是一律講成 node。

    2026-09-18 之前三支都寫死「叫不動 node」／「起不了 node」，
    而同一個 `except OSError` 也接得到兩個 `write_text` 丟出來的東西。
    寫檔失敗回一句指著 node 的理由，就是上一輪
    （`test_tempdir_cleanup` 紅燈指控 `blast.py`）那個形狀再來一次。

    這一條不跑 node，改成注入寫檔失敗，看回的字串。
    """
    import blast as BL
    import goalgate as GG
    import jsbridge as JB

    if not JB.node_bin():
        pytest.skip("這台沒有 node，走不到 mkdtemp 那條路")

    class _S:
        n = 1
        ai_text = "我全部檢查過了，所有的檔案都沒問題"
        dots: list = []

    real = Path.write_text

    def boom(self, *a, **k):
        raise OSError("模擬寫檔失敗")

    cases = [
        ("jsbridge.scan", lambda: JB.scan([_S()])),
        ("goalgate.gac", lambda: GG.gac([{"text": "x"}])),
    ]
    for name, fn in cases:
        Path.write_text = boom
        try:
            out = fn()
        finally:
            Path.write_text = real
        why = str(out.get("why") or "")
        assert "寫暫存檔" in why, (
            f"{name} 在寫檔失敗的時候回的是「{why}」。"
            "那句話指著 node，而 node 根本還沒被叫起來 —— "
            "一句指控錯人的理由，讀起來像已經查過了。"
        )
    assert BL.vectors  # 這一支要真的 repo 才走得到，behavioral 那條驗它


# ---------------------------------------------------------------- tools/ 那三支

def _load_render_check():
    """`tools/ui-render-check.py` 的檔名有連字號，`import` 進不來。

    載法跟 `tests/test_ui_render.py:_load()` 同一套（放進 `sys.modules`
    是實測換來的，不然它裡面的 dataclass 解析型別註記時找不到自己）。
    """
    import importlib.util

    tool = ROOT / "tools" / "ui-render-check.py"
    spec = importlib.util.spec_from_file_location("forseti_ui_render_check_tmp",
                                                  tool)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["forseti_ui_render_check_tmp"] = mod
    spec.loader.exec_module(mod)
    return mod


class _StubHarness:
    """假的 harness，只負責決定 `build()` 怎麼結束。

    **真的那一支 `build()` 要 16 秒**（2026-09-18 實測，`--fake` 也一樣，
    它要組出 312KB 的 fixture）。這一組驗的是「借了有沒有還」，
    不是 harness 產得出不出頁面，所以換掉它，讓每一條都跑得完。
    """

    def __init__(self, mode: str):
        self.mode = mode

    def build(self, out, fake, session):
        if self.mode == "raise":
            raise RuntimeError("模擬 harness 產不出頁面")
        if self.mode == "empty":
            return  # 什麼都不寫，於是 index.html 不存在
        # 其餘模式要走到 Chrome 那一段，所以頁面得真的在。內容不重要：
        # `subprocess.run` 被換掉了，這份 HTML 不會有人去讀。
        (out / "index.html").write_text("<html></html>", encoding="utf-8")


def _stub_render(rc, mode: str):
    """把 `render()` 前面兩個外部相依換掉，只留下借目錄那一段。

    `find_chrome()` 也要換：這台有沒有 Chrome 跟這一條驗的事無關，
    而它在 `mkdtemp` 之前，找不到的話整條測試會變成 skip ——
    那樣「借了有沒有還」永遠驗不到。這兩條路都走不到 subprocess，
    所以換成一個假路徑不會真的去叫什麼東西起來。
    """
    rc.find_chrome = lambda: "/nonexistent/chrome-不會被叫到"
    rc._load_harness = lambda: _StubHarness(mode)


def test_畫面檢查器走失敗路徑的時候不留臨時目錄(iso_tmp):
    """`render()` 的 raise 路徑，借到的目錄要不見了。

    **2026-09-18 補這一組，起因是上一輪自己寫下的缺口。** 上一輪原話：
    「`tools/` 底下那三個 `mkdtemp` 沒有被守門掃到 [...] 這一輪沒有去看
    它們收不收」。去看的結果是**真的在漏**，而且量得到：當天暫存區
    188 個 `forseti-render-*`，130MB，時間從 09-17 00:33 到 22:56。

    成因不是忘了寫 `rmtree` —— 九個呼叫端每一個都寫了。是那九個收的
    方式都是 `shutil.rmtree(r.outdir)`，而 `render()` 有五條 raise 路徑
    （harness 產不出頁面、沒寫出 index.html、Chrome 逾時、Chrome 非零
    回傳、空 DOM），走那幾條的時候 `r` 根本不存在，呼叫端拿不到
    `outdir` 就無從收起。**「每個呼叫端都有 rmtree」跟「每條路徑都有人
    收」是兩件事**，而前者看起來很像後者。
    """
    rc = _load_render_check()
    for mode, why in (("raise", "harness 產不出頁面"),
                      ("empty", "harness 沒有寫出 index.html")):
        _stub_render(rc, mode)
        before = _count("forseti-render-")
        with pytest.raises(rc.CannotRun) as e:
            rc.render(fake=True)
        after = _count("forseti-render-")
        assert why in str(e.value), f"走的不是預期那條路：{e.value}"
        assert after == before, (
            f"render() 走「{why}」那條路借了臨時目錄沒還，{before} → {after}。"
            "收的地方是 ui-render-check.py 的 finally。"
        )


def test_呼叫端給的目錄不會被畫面檢查器刪掉(iso_tmp):
    """`outdir=` 給的那一份不是它借的，失敗了也不准收。

    這一條跟上面那條方向相反，**兩條要一起在**：只有上面那條的話，
    「失敗就 rmtree(out)」可以讓它變綠，而那個寫法會把呼叫端自己的
    目錄刪掉。`render()` 的 `out` 有兩個來源，收尾只能對其中一個。
    """
    rc = _load_render_check()
    _stub_render(rc, "raise")
    mine = iso_tmp / "呼叫端自己的目錄"
    mine.mkdir()
    (mine / "不准被刪掉.txt").write_text("x", encoding="utf-8")

    with pytest.raises(rc.CannotRun):
        rc.render(fake=True, outdir=mine)

    assert mine.is_dir() and (mine / "不准被刪掉.txt").exists(), (
        "呼叫端給的目錄被 render() 收掉了。它不是 render() 借的，"
        "所有權從頭到尾在呼叫端手上。"
    )


class _StubProc:
    """`subprocess` 的替身，只放 `render()` 真的會碰的那兩個名字。

    整個模組裡只有 `render()` 用到 `subprocess`（第 417、418 行，
    2026-09-18 查過），所以換掉整個名字比去 monkeypatch 真的那個模組
    安全 —— 真的那一個是行程全域的，`_load_render_check()` 每次給的
    模組物件則是新的，換在它身上不會外溢到別條測試。

    `TimeoutExpired` 指回真的那一個，因為 `except` 那一行要接得到
    我們丟出去的東西，兩邊必須是同一個類別。
    """

    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, mode: str):
        self.mode = mode

    def run(self, cmd, **kw):
        if self.mode == "timeout":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 0))
        if self.mode == "rc":
            return subprocess.CompletedProcess(cmd, 137, stdout="",
                                               stderr="模擬 Chrome 掛掉")
        # mode == "emptydom"：回來了，回的是空的
        return subprocess.CompletedProcess(cmd, 0, stdout="   \n", stderr="")


_DEEP_PATHS = (
    ("timeout", "沒有回來"),
    ("rc", "Chrome 回 137"),
    ("emptydom", "Chrome 回了空的 DOM"),
)


def test_畫面檢查器走Chrome那三條失敗路徑的時候不留臨時目錄(iso_tmp):
    """`render()` 剩下那三條 raise 路徑，借到的目錄也要不見了。

    **2026-09-18 補這一條，起因是上一輪自己寫下的缺口。** 上一輪原話：

        `render()` 另外三條 raise 路徑（Chrome 逾時、非零回傳、空 DOM）
        沒有 behavioral 測試。它們跟驗過的那兩條共用同一個 `finally`，
        所以推論上一起修好了 —— 但**推論不是量測**。

    共用同一個 `finally` 是真的（第 430 行只有一個），所以這一條
    現在必然是綠的。**它守的不是今天，是明天**：`handed = True`
    那一行在第 428 行，就壓在 `return` 上面；哪天有人為了別的理由
    把它往上搬到 `subprocess.run` 之前，前面兩條（harness 那兩條，
    根本走不到 subprocess）仍然全綠，而這三條會紅。
    兩組一起在，才蓋得住 `handed` 那一行的整個位移範圍。

    `137` 不是隨手挑的數字，是 SIGKILL 的那一個 —— Chrome 被系統
    砍掉正是這條路現實中最常發生的走法。
    """
    rc = _load_render_check()
    for mode, why in _DEEP_PATHS:
        _stub_render(rc, "ok")
        rc.subprocess = _StubProc(mode)
        before = _count("forseti-render-")
        with pytest.raises(rc.CannotRun) as e:
            rc.render(fake=True)
        after = _count("forseti-render-")
        assert why in str(e.value), f"走的不是預期那條路：{e.value}"
        assert after == before, (
            f"render() 走「{why}」那條路借了臨時目錄沒還，{before} → {after}。"
            "收的地方是 ui-render-check.py 的 finally。"
        )


def test_呼叫端給的目錄在Chrome那三條路上也不會被刪掉(iso_tmp):
    """所有權那一半也要蓋到深的那三條，不是只蓋到最淺的那一條。

    上面那一組（`test_呼叫端給的目錄不會被畫面檢查器刪掉`）走的是
    harness 就 raise 的那條，離 `finally` 只有幾行。這三條走完了
    注入、組指令、叫 Chrome 才失敗，中間多出來的每一段都是有人
    可能塞一句 `shutil.rmtree(out)` 的位置 —— 而塞在那裡的話，
    上面那一條不會紅，因為它根本走不到那幾行。
    """
    rc = _load_render_check()
    for mode, _why in _DEEP_PATHS:
        _stub_render(rc, "ok")
        rc.subprocess = _StubProc(mode)
        mine = iso_tmp / f"呼叫端自己的目錄-{mode}"
        mine.mkdir()
        (mine / "不准被刪掉.txt").write_text("x", encoding="utf-8")

        with pytest.raises(rc.CannotRun):
            rc.render(fake=True, outdir=mine)

        assert mine.is_dir() and (mine / "不准被刪掉.txt").exists(), (
            f"走「{mode}」那條路的時候，呼叫端給的目錄被 render() 收掉了。"
            "它不是 render() 借的，所有權從頭到尾在呼叫端手上。"
        )


# ---------------------------------------------------------------------------
# `TemporaryDirectory`：另一半，而且判準跟 `mkdtemp` 那一半不同
# ---------------------------------------------------------------------------

def _tempdir_sites(tree: ast.AST) -> list[tuple[int, bool]]:
    """整檔每一個 `TemporaryDirectory()`，以及它**是不是 with 的頭**。

    判準只有一種形狀算數：這個 `Call` 本身就是某個 `with`（或
    `async with`）的 context expression。`with tempfile.TemporaryDirectory()
    as td:` 命中，`td = tempfile.TemporaryDirectory()` 不命中。

    **這條跟 `_borrow_sites` 問的不是同一件事，所以判準不一樣。**
    `mkdtemp` 回的是一個路徑字串，誰都不負責收，所以那邊要求
    `finally` 裡有人收。`TemporaryDirectory()` 回的是一個 context
    manager，收尾寫在它自己的 `__exit__` 裡 —— 只要進得了 `with`，
    離開區塊就收，中間 raise 也收。所以這邊要求的不是 `finally`，
    是**別把它從 `with` 上拆下來**。

    拆下來之後會怎樣：物件要等 GC 跑到它的 finalizer 才收，時機不定；
    存進 `self` 或模組層變數的話那個 finalizer 永遠不會跑，目錄就
    一直在。這不是理論 —— `tests/` 底下的 unittest fixture 正是
    `self.tmp = tempfile.TemporaryDirectory()` 這個形狀（配 `tearDown`
    手動收）。那個形狀在測試裡是刻意的，所以**這條守門不掃 `tests/`**，
    掃的是 `CLI` 與 `TOOLS`，跟 `_borrow_sites` 那條同一個範圍。

    **這條判準有一個已知的假陽性**：`with contextlib.ExitStack() as s:`
    配 `s.enter_context(tempfile.TemporaryDirectory())` 是安全的，
    而這裡會判它不合規。現在這個 repo 一處都沒有（2026-09-18 查過，
    `grep -rn 'enter_context' apps/forseti-cli tools` 零命中），
    所以不先為它開例外 —— 規格沒定義的形狀不預先編一條規則放行，
    真的出現的時候連同它的理由一起加。
    """
    holders: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.With, ast.AsyncWith)):
            for item in n.items:
                holders.add(id(item.context_expr))

    out: list[tuple[int, bool]] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        named = (isinstance(f, ast.Attribute) and f.attr == "TemporaryDirectory") \
            or (isinstance(f, ast.Name) and f.id == "TemporaryDirectory")
        if named:
            out.append((n.lineno, id(n) in holders))
    return out


def test_每一個TemporaryDirectory都是with形式():
    """原始碼層級：借目錄的另一半形狀，也要有人守。

    **2026-09-18 加這一條，起因是一個重複了三輪的查證。**
    `AUTO_CONTINUE_LOG.md` 連續三輪的「還缺什麼」都寫著
    `desktop_api.py:2873`、`:2895` 與 `probe.py:295` 的
    `TemporaryDirectory()`「仍然沒有量過」。這一輪去看了，
    三個位置全部是 `with tempfile.TemporaryDirectory() as td:`，
    也就是 context manager 本來就會收，**它們不是缺口**。

    那為什麼會連問三輪。因為既有那條守門
    （`test_每一個mkdtemp都有人收`）只認 `mkdtemp` 這一個名字，
    於是任何人 `grep TemporaryDirectory` 都會看到三個命中、
    再回頭發現守門測試裡一個字都沒提到它們 —— 然後只能自己去讀一次
    原始碼才知道沒事。**一個要靠重讀原始碼才回答得出來的問題，
    會被問到有人把它寫進測試為止。** 這一條就是把那個答案寫下來。

    所以這條守的**不是**今天：今天三個都合規。它守的是哪天有人
    把其中一個從 `with` 上拆下來（改成 `td = TemporaryDirectory()`
    再讀 `.name`），那一刻要紅。既有那條守門對那個改動是綠的，
    因為那個改動裡一個 `mkdtemp` 都沒有。

    **非空斷言是必要的**，理由跟既有那條同一句：掃描壞掉的時候，
    「每一個都是 with」會在零個站點上無聲成立。
    """
    sites: list[tuple[str, int, bool]] = []
    for f in sorted(x for d in (CLI, TOOLS) for x in d.glob("*.py")
                    if not x.name.startswith("._")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for lineno, ok in _tempdir_sites(tree):
            sites.append((str(f.relative_to(ROOT)), lineno, ok))

    assert len(sites) >= 3, (
        f"只掃到 {len(sites)} 個 TemporaryDirectory，已知有三個"
        "（desktop_api.py 兩個、probe.py 一個）。"
        "掃描壞掉的時候，「每一個都是 with」會在零個站點上無聲成立。"
    )
    loose = [f"{w}（第 {ln} 行）" for w, ln, ok in sites if not ok]
    assert not loose, (
        f"這幾個 TemporaryDirectory 沒有掛在 with 上：{loose}。"
        "從 with 上拆下來之後，收尾要等 GC 跑到 finalizer，時機不定；"
        "存進 self 或模組層變數的話那個 finalizer 永遠不跑。"
        "要嘛掛回 with，要嘛換成 mkdtemp 配 finally（那條走另一條守門）。"
    )
