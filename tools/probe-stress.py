#!/usr/bin/env python3
"""ProgressProbe 抓不抓得到剛寫完的變化。B-12 的壓力測試。

B-12 記的是一個間歇性失敗：`tests/test_f05.py` 兩次回非零，
斷言是 `AssertionError: 1.0 != 0.0`，指向 `no_progress_growth` 因子 ——
也就是「預期產物有變動，實際判定成沒變」。

**推論是：這個 repo 在 exFAT 外接碟上，寫入還沒落地而 probe 立刻讀。**

那個推論如果成立，它就不只是測試不穩：`check_liveness()` 在真實情況下
同樣是「worker 剛寫完、巡檢立刻讀」，讀到舊內容會把一個正在做事的
worker 判成停滯。

────────────────────────────────────────────────────

## 這支腳本怎麼證明或推翻它

同一個測法跑兩個檔案系統，**對照組是關鍵**：

    exFAT   這個 repo 所在的外接碟
    APFS    /tmp（macOS 的系統碟）

如果只有 exFAT 抓不到，推論成立。
如果兩邊都抓不到，問題在 `ProgressProbe` 不在檔案系統。
如果兩邊都正常，推論被推翻，要往別的方向找。

**跑出來是零也是結果。** 那代表這個條件下重現不了，而不是問題不存在 ——
B-12 那兩次是真的發生過的。

用法：

    python3 tools/probe-stress.py [--rounds 300]

回傳 0 代表兩邊都沒有漏抓，1 代表有漏抓（那就是重現了）。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import watchdog as W  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# 大小要有變化。大檔案的寫入更可能還沒落地就被讀到，
# 所以不能只用一種大小測 —— 只測小檔案會得出「沒問題」的假結論。
SIZES = (64, 4096, 64 * 1024, 512 * 1024)


def one_round(box: Path, size: int, seq: int) -> bool:
    """寫兩次不同的內容，看 probe 抓不抓得到第二次。回傳 True 代表抓到了。"""
    name = f"p{seq}.bin"
    target = box / name

    target.write_text("A" * size, encoding="utf-8")
    first = W.ProgressProbe.take([name], box)

    # 刻意不 sleep、不 fsync。要測的正是「寫完立刻讀」這個真實情況。
    target.write_text("B" * size, encoding="utf-8")
    second = W.ProgressProbe.take([name], box)

    return second.changed_from(first)


def run(label: str, box: Path, rounds: int) -> dict:
    misses: list[tuple[int, int]] = []
    t0 = time.perf_counter()
    for i in range(rounds):
        size = SIZES[i % len(SIZES)]
        if not one_round(box, size, i):
            misses.append((i, size))
    elapsed = time.perf_counter() - t0
    return {"label": label, "rounds": rounds, "misses": misses,
            "elapsed": elapsed, "path": str(box)}


def report(r: dict) -> None:
    n = len(r["misses"])
    print(f"  {r['label']}")
    print(f"    {r['path']}")
    print(f"    {r['rounds']} 輪　{r['elapsed']:.1f} 秒　漏抓 {n}")
    if n:
        by_size: dict[int, int] = {}
        for _, size in r["misses"]:
            by_size[size] = by_size.get(size, 0) + 1
        for size, c in sorted(by_size.items()):
            print(f"      {size:>8,} bytes　漏 {c} 次")
    print()


def main(argv: list[str]) -> int:
    rounds = 300
    if "--rounds" in argv:
        i = argv.index("--rounds")
        if i + 1 < len(argv):
            rounds = int(argv[i + 1])

    exfat_box = REPO / ".forseti" / "probe-stress"
    apfs_box = Path(tempfile.mkdtemp(prefix="probe-stress-"))
    exfat_box.mkdir(parents=True, exist_ok=True)

    print()
    print(f"  每輪寫兩次不同內容，第二次寫完立刻 probe。大小輪流用 {SIZES}")
    print()
    try:
        results = [run("exFAT（這個 repo）", exfat_box, rounds),
                   run("APFS（/tmp，對照組）", apfs_box, rounds)]
        for r in results:
            report(r)

        bad = [r for r in results if r["misses"]]
        if not bad:
            print("  兩邊都沒有漏抓。")
            print("  **這不代表 B-12 的問題不存在** —— 那兩次失敗是真的發生過的。")
            print("  代表的是這個條件下重現不了，推論要往別的方向找：")
            print("    並行寫入？不同的 timing？還是 test_f05 裡別的斷言？")
            return 0

        only_exfat = len(bad) == 1 and bad[0]["label"].startswith("exFAT")
        if only_exfat:
            print("  ★ 只有 exFAT 漏抓。B-12 的推論成立。")
            print("  那不只是測試不穩：check_liveness() 在真實情況下也是")
            print("  「worker 剛寫完、巡檢立刻讀」，會把做事中的 worker 判成停滯。")
        else:
            print("  ★ 兩個檔案系統都漏抓。問題在 ProgressProbe 不在 exFAT。")
        return 1
    finally:
        shutil.rmtree(exfat_box, ignore_errors=True)
        shutil.rmtree(apfs_box, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
