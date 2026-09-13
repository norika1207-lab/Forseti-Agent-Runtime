#!/usr/bin/env python3
"""段落層級的閱讀涵蓋。F08 §5 那七級裡，分辨 SAMPLED 與 FULL_READ 的依據。

規格來源：`F08-CTX-001` §5（2026-09-09，sha256 前 12 碼 `b80b985fdfc0`），
以及 `spec_manifest.json` 的 `reading_policy`：

    full-file required; sampled/title-only reading is non-conformant

────────────────────────────────────────────────────

## 為什麼需要它

`tools/reading-conformance.py` 驗得到「檔案沒變」，驗不到「讀了幾行」。
sha256 只證明檔案自從被記錄之後沒有變 —— 一個只讀最後 20 行的人，
算出來的 hash 跟讀完整份的人一模一樣。

而「只讀了最後那張表」正是 2026-09-11 早上實際發生的事：
`.forseti/REQUIRED_READING.md` 第 176 到 223 行有一整段壓縮前寫下的
記錄（九份規格的 sha256、一條規格矛盾、一道禁令），而那天早上的
七條回報說「補讀門檻全達標」，講的是同一個檔案最底下那張表。

打開了檔案，讀了表，沒有往上讀 60 行。沒有人發現，因為沒有東西在量。

## 它量的是什麼，不是什麼

量的是「這次讀取涵蓋了哪些行」，一個純粹的區間集合。

不量「讀懂了沒有」。那是 F08 §5 最後一級 `VERIFIED_UNDERSTANDING`，
需要能被抽問、答得出原文，不是這個模組的事。把兩者混在一起，
會讓一個掃過全文的人拿到跟讀懂的人一樣的等級。

## 七級的判定只用行數，不讀內容

    NONE            沒讀
    TITLE_ONLY      只涵蓋第 1 行那一帶
    HEADER_SCAN     只涵蓋各節標題所在的行
    SAMPLED         零散片段，總涵蓋率低
    STRUCTURAL      涵蓋率高但有明顯缺口
    FULL_READ       每一行都涵蓋到
    VERIFIED_UNDERSTANDING   這個模組不發這一級，見上面

門檻是可辯駁的常數，寫在 `THRESHOLDS` 並標著未校準。
那組數字沒有實測依據，只有一個設計意圖：**寧可低估自己讀了多少。**
低估的代價是多讀一次，高估的代價是今天這場事故。

零依賴（ADR-009）。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

LEVELS = ("NONE", "TITLE_ONLY", "HEADER_SCAN", "SAMPLED",
          "STRUCTURAL", "FULL_READ", "VERIFIED_UNDERSTANDING")

LEVEL_MEANING = {
    "NONE": "沒讀",
    "TITLE_ONLY": "只涵蓋開頭那一帶",
    "HEADER_SCAN": "只涵蓋各節標題所在的行",
    "SAMPLED": "零散片段，總涵蓋率低",
    "STRUCTURAL": "涵蓋率高但有明顯缺口",
    "FULL_READ": "每一行都涵蓋到",
    "VERIFIED_UNDERSTANDING": "讀懂了，而且答得出原文。這個模組不發這一級",
}
assert set(LEVEL_MEANING) == set(LEVELS)

# 這個模組能發到哪一級。最後一級要靠抽問，不是靠行號。
MAX_MECHANICAL = "FULL_READ"

# 【未校準】沒有實測依據，只有一個設計意圖：寧可低估自己讀了多少。
THRESHOLDS = {
    "structural": 0.85,   # 涵蓋率到這裡才算 STRUCTURAL
    "sampled": 0.05,      # 低於這個而且不是標題帶，算 TITLE_ONLY
    "title_lines": 12,    # 前幾行算「開頭那一帶」
}
THRESHOLDS_UNCALIBRATED = True


class CoverageError(Exception):
    """涵蓋記錄不合法。拒絕而不是修正。"""


def _merge(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """把重疊或相鄰的區間併起來。

    相鄰也要併（`(1,10)` 與 `(11,20)` 併成 `(1,20)`），
    不然一份逐段讀完的檔案會因為區間破碎而看起來有缺口。
    """
    if not spans:
        return []
    out: list[tuple[int, int]] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


@dataclass
class ReadRecord:
    """某一份檔案，某一次或多次讀取，涵蓋了哪些行。

    `total_lines` 是讀取當下那個檔案的行數。它跟 `content_hash` 一起
    釘住「這份涵蓋記錄是對著哪一個版本的檔案算的」——
    檔案變了之後，舊的涵蓋率就不能再用（見 `is_stale_against()`）。
    """

    path: str
    total_lines: int
    content_hash: str = ""
    spans: list[tuple[int, int]] = field(default_factory=list)

    def __post_init__(self):
        if self.total_lines < 0:
            raise CoverageError("total_lines 不能是負的")
        for lo, hi in self.spans:
            if lo < 1 or hi < lo:
                raise CoverageError(f"不合法的區間：({lo}, {hi})")
            if hi > self.total_lines:
                raise CoverageError(
                    f"區間 ({lo}, {hi}) 超出檔案的 {self.total_lines} 行。"
                    "宣稱讀了不存在的行，比少讀更嚴重")

    def add(self, lo: int, hi: int) -> None:
        if lo < 1 or hi < lo:
            raise CoverageError(f"不合法的區間：({lo}, {hi})")
        if hi > self.total_lines:
            raise CoverageError(
                f"區間 ({lo}, {hi}) 超出檔案的 {self.total_lines} 行")
        self.spans.append((lo, hi))

    @property
    def covered(self) -> list[tuple[int, int]]:
        return _merge(self.spans)

    @property
    def covered_lines(self) -> int:
        return sum(hi - lo + 1 for lo, hi in self.covered)

    @property
    def ratio(self) -> float:
        if not self.total_lines:
            return 0.0
        return self.covered_lines / self.total_lines

    def gaps(self) -> list[tuple[int, int]]:
        """沒讀到的行。**這是這整個模組存在的理由。**

        `tools/reading-conformance.py` 只能說「檔案沒變」，
        這裡能說「第 176 到 223 行你沒讀進來」。
        """
        out: list[tuple[int, int]] = []
        cur = 1
        for lo, hi in self.covered:
            if lo > cur:
                out.append((cur, lo - 1))
            cur = max(cur, hi + 1)
        if cur <= self.total_lines:
            out.append((cur, self.total_lines))
        return out

    def is_stale_against(self, path: Path | None = None) -> bool | None:
        """這份涵蓋記錄還算不算數。

        回 None 代表量不到（檔案讀不到、或當初沒記 hash），
        不回 False。量不到不等於沒問題，跟 `claims.py` 的三態同一個原則。
        """
        if not self.content_hash:
            return None
        p = path or Path(self.path)
        try:
            now = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        except OSError:
            return None
        return now != self.content_hash[:12]

    def level(self, header_lines: set[int] | None = None) -> str:
        """七級判定。只用行數，不讀內容。"""
        if not self.covered_lines:
            return "NONE"
        if self.ratio >= 1.0:
            return "FULL_READ"
        if self.ratio >= THRESHOLDS["structural"]:
            return "STRUCTURAL"

        # 涵蓋的行如果剛好都落在標題上，那是 HEADER_SCAN 不是 SAMPLED。
        # 兩者的涵蓋率可能一樣，但意義差很多：掃標題的人知道有哪些節，
        # 零散抽樣的人連這個都不知道。
        if header_lines:
            read = {n for lo, hi in self.covered for n in range(lo, hi + 1)}
            if read and read <= set(header_lines):
                return "HEADER_SCAN"

        if (self.ratio < THRESHOLDS["sampled"]
                and all(hi <= THRESHOLDS["title_lines"]
                        for _, hi in self.covered)):
            return "TITLE_ONLY"
        return "SAMPLED"

    def conformant(self) -> bool:
        """照 `spec_manifest.json` 的 reading_policy 判。

        原文：full-file required; sampled/title-only reading is non-conformant
        """
        return self.level() == "FULL_READ"

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "total_lines": self.total_lines,
            "content_hash": self.content_hash,
            "covered": [list(x) for x in self.covered],
            "covered_lines": self.covered_lines,
            "ratio": round(self.ratio, 4),
            "gaps": [list(x) for x in self.gaps()],
            "level": self.level(),
            "conformant": self.conformant(),
            "thresholds_uncalibrated": THRESHOLDS_UNCALIBRATED,
        }


def from_full_read(path: Path) -> ReadRecord:
    """整份讀完的記錄。給「真的 cat 了整個檔案」那種讀取用。"""
    data = path.read_bytes()
    n = len(data.decode("utf-8", errors="replace").splitlines())
    r = ReadRecord(str(path), n,
                   hashlib.sha256(data).hexdigest()[:12])
    if n:
        r.add(1, n)
    return r


def header_lines_of(path: Path) -> set[int]:
    """markdown 標題所在的行。給 HEADER_SCAN 判定用。"""
    out: set[int] = set()
    try:
        for i, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace")
                .splitlines(), 1):
            if line.lstrip().startswith("#"):
                out.add(i)
    except OSError:
        pass
    return out


# ---------------------------------------------------------------------------
# 儲存：涵蓋記錄要落在磁碟上，不然壓縮之後就沒了
# ---------------------------------------------------------------------------

# 位置跟 Event Ledger 同一個目錄，理由一樣（v5.0 §20.1 那條的精神）：
# 它是這個 repo 的執行期證據，跟著 repo 走。
#
# append-only。一份涵蓋記錄被寫下來之後不准改 —— 改得掉的話，
# 「我讀到哪裡」就會變成一個可以事後調整的數字，而那正是這整套
# 東西要防的事。
DEFAULT_LOG = ".forseti/reading_coverage.jsonl"


class CoverageLog:
    """append-only 的涵蓋記錄。

    **為什麼要落地，而不是放在 session 的記憶裡：**

    2026-09-11 那場事故的根因是壓縮吃掉了「我該讀什麼」，
    而內容一直在磁碟上。一份只存在於 context 裡的涵蓋記錄，
    下一次壓縮就會消失，然後新的 session 又會從零開始高估自己。
    """

    def __init__(self, path=None, root=None):
        import os
        if path is not None:
            self.path = Path(path)
        else:
            env = os.environ.get("FORSETI_COVERAGE_LOG")
            if env:
                self.path = Path(env).expanduser()
            else:
                base = Path(root) if root else Path(__file__).resolve().parents[2]
                self.path = base / DEFAULT_LOG
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, rec: ReadRecord, *, session: str = "",
               note: str = "") -> None:
        import json
        import time
        row = rec.to_dict()
        row["at"] = time.time()
        row["session"] = session
        row["note"] = note
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False,
                                sort_keys=True, separators=(",", ":")) + "\n")

    def read_all(self) -> list[dict]:
        import json
        out: list[dict] = []
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue          # 壞掉的一行不該讓整份讀不出來
        except OSError:
            pass
        return out

    def best_for(self, path: str) -> dict | None:
        """某個檔案，涵蓋率最高的那一筆。

        **取最高而不是取最新**，因為多次讀取是累積的：
        先讀了前半再讀後半，兩筆各自不完整，但人確實讀完了。
        真正該擋的是「檔案變了之後的舊記錄」，那由 `stale` 處理。
        """
        want = str(path)
        rows = [r for r in self.read_all() if r.get("path") == want]
        if not rows:
            return None
        return max(rows, key=lambda r: r.get("ratio", 0))

    def merged_for(self, path: str) -> ReadRecord | None:
        """把同一個檔案、同一個 hash 的多筆記錄併成一筆。

        併之前先按 hash 分組：檔案改過之後的涵蓋記錄不能跟改之前的
        加在一起，不然一份被大改過的檔案會因為兩次半份的讀取
        而看起來讀完了。
        """
        want = str(path)
        rows = [r for r in self.read_all() if r.get("path") == want]
        if not rows:
            return None
        newest_hash = max(rows, key=lambda r: r.get("at", 0)).get("content_hash", "")
        same = [r for r in rows if r.get("content_hash", "") == newest_hash]
        if not same:
            return None
        total = max(r.get("total_lines", 0) for r in same)
        merged = ReadRecord(want, total, newest_hash)
        for r in same:
            for lo, hi in r.get("covered") or []:
                if 1 <= lo <= hi <= total:
                    merged.add(lo, hi)
        return merged
