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
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "apps" / "forseti-cli"
sys.path.insert(0, str(CLI))

TMP = Path(tempfile.gettempdir())


def _count(prefix: str) -> int:
    return len(glob.glob(str(TMP / (prefix + "*"))))


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
    b = _fake_repo()
    try:
        yield b
    finally:
        shutil.rmtree(b, ignore_errors=True)


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


def test_每一個mkdtemp都有人收():
    """原始碼層級：`apps/forseti-cli` 底下借了目錄的，同一支要有 `finally` 收。

    **behavioral 那兩條蓋不到新增的第五支。** 哪天有人在別的模組
    再借一個，那兩條不會紅（它們只數 `forseti-blast-` 這兩個前綴），
    而這一條會。

    要求 `rmtree` 在 `finally` 裡而不只是在函式內某處，是因為
    這四支全部都有提早 return 的路徑（`TimeoutExpired`、`OSError`、
    `returncode != 0`）。寫在 try 尾巴的收尾在那些路徑上不會執行 ——
    而 node 逾時正是最需要收的那一次。

    **這一條的非空斷言是必要的**：掃描壞掉時「每一個都有人收」
    會在零個站點上成立。所以下面釘死站點數不得少於已知的四個。
    """
    sites: list[tuple[str, int, bool]] = []

    # `._*.py` 是 exFAT 上的 AppleDouble 附屬檔，不是原始碼，
    # 讀下去會是 UnicodeDecodeError。整個 repo 一律這樣濾
    # （`desktop_api.py:2603`、`ledger.py:825`、`jsbridge.py:74`）。
    for f in sorted(x for x in CLI.glob("*.py")
                    if not x.name.startswith("._")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            borrows = [
                n for n in ast.walk(fn)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "mkdtemp"
            ]
            if not borrows:
                continue
            returns = any(
                isinstance(t, ast.Try)
                and any(
                    isinstance(c, ast.Call)
                    and isinstance(c.func, ast.Attribute)
                    and c.func.attr == "rmtree"
                    for stmt in t.finalbody
                    for c in ast.walk(stmt)
                )
                for t in ast.walk(fn)
            )
            for b in borrows:
                sites.append((f"{f.name}:{fn.name}", b.lineno, returns))

    assert len(sites) >= 4, (
        f"只掃到 {len(sites)} 個 mkdtemp，已知有四個"
        "（jsbridge、goalgate、blast 兩支）。掃描壞掉的時候，"
        "「每一個都有人收」會在零個站點上無聲成立。"
    )
    missing = [f"{w}（第 {ln} 行）" for w, ln, ok in sites if not ok]
    assert not missing, (
        f"這幾支借了臨時目錄，同一支裡沒有 finally 收：{missing}。"
        "寫在 try 尾巴不算 —— 那四支都有提早 return 的路徑，"
        "而 node 逾時正是最需要收的那一次。"
    )
