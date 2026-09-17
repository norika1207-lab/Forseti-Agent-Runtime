#!/usr/bin/env python3
"""把 spec_manifest.json 那條 reading_policy 變成真的會跑的檢查。

manifest 最後一行逐字：

    "reading_policy": "full-file required; sampled/title-only reading
     is non-conformant"

那條寫在機器可讀的 json 裡，不是寫在給人看的 md 裡。也就是說它本來
就設計成可以被程式檢查，不是靠 AI 自律。而在 2026-09-11 之前，
repo 裡沒有任何程式在檢查它。

────────────────────────────────────────────────────

## 為什麼需要這支，兩件當天發生的事

一，`.forseti/REQUIRED_READING.md` 第 176 到 223 行有一整段
壓縮前寫下的記錄（九份規格的 sha256、一條規格矛盾、一道禁令）。
那天早上我在七條回報裡說「補讀門檻全達標」，講的是同一個檔案
最底下那張表 —— 我打開了檔案，讀了表，沒有往上讀 60 行。

照 manifest 那條政策判，那次閱讀是 non-conformant。沒有人發現，
因為沒有東西在判。

二，那組規格的路徑被移動過（多了 `Forseti Agent Runtime` 一層），
`REQUIRED_READING.md` 裡記的還是舊路徑。照舊路徑去找就找不到，
而「找不到」跟「讀過了」在一張自己填的表上長得一模一樣。

## 這支驗得到什麼，驗不到什麼

驗得到：

    檔案還在不在那個路徑
    檔案的 sha256 跟宣稱讀過時記的一不一樣
    manifest 列的每一份，補讀表裡有沒有對應的記錄

驗不到，而且這一條要講清楚：

    「讀了幾行」

sha256 只證明「檔案自從被記錄之後沒有變」，不證明當時讀完了整份。
要真的擋住 sampled，得記錄每一次讀取涵蓋的行號範圍，
那是段落層級的 coverage（F08 §5 七級裡 SAMPLED 與 FULL_READ 的差別），
比 hash 比對大一圈，而且要改變讀取端的行為不是只加一個檢查。

`coverage_gap()` 是那件事的佔位，現在回 None 並說明為什麼，
不假裝有答案。

## exit code

    0   conformant
    1   non-conformant（有檔案變了、不見了、或沒有記錄）
    2   無法檢查（manifest 或補讀表找不到）

用法：

    python3 tools/reading-conformance.py
    python3 tools/reading-conformance.py --json
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 規格集的位置。2026-09-11 更正過：原本少了 `Forseti Agent Runtime` 那層。
SPEC_DIR = (Path.home() / "Dropbox" / "My project" / "Forseti Agent Runtime"
            / "forseti_20260909-2_Modular_Spec")
MANIFEST = SPEC_DIR / "spec_manifest.json"
READING = REPO / ".forseti" / "REQUIRED_READING.md"

# 補讀表裡那張 hash 表的列長這樣：
#   | F01-PEC-001 | `F01_...md` | 5 | `fe86cb2a1ab7` | 持久執行契約 |
_ROW = re.compile(
    r"^\|\s*([A-Z0-9-]+)\s*\|\s*`([^`]+)`\s*\|[^|]*\|\s*`([0-9a-f]{6,64})`")


def sha12(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:12]
    except OSError:
        return None


class ReadingTableUnreadable(Exception):
    """補讀表讀不到。

    **「讀不到」跟「表在、可是一列都沒有」是兩件事。**
    2026-09-17 之前這裡吞掉 `OSError` 回一個空 dict，於是 `check()`
    把每一份都判成 `NO_RECORD`，理由印「補讀表裡沒有這一份的記錄」
    —— 而補讀表根本沒有被讀到。實測兩種情形回傳的整個 dict 相同
    （`tests/test_silent_oserror.py` 當時量過）。

    那句理由是假的。照它去修的人會去補表，而表可能一直是對的，
    錯的是讀不到。

    丟例外不是為了讓它更嚴。`check()` 接住之後回 `CANNOT_CHECK`，
    也就是這個模組檔頭 exit code 那一段本來就寫著的
    「2　無法檢查（manifest 或補讀表找不到）」 —— 補讀表那一半
    先前只寫在文件裡，沒有實作。
    """


def declared() -> dict[str, tuple[str, str]]:
    """補讀表裡宣稱讀過的：id -> (檔名, hash 前 12)。

    讀不到就丟 `ReadingTableUnreadable`，不回空 dict。
    空 dict 在下游代表「沒有人宣稱讀過」，那是一個結論，
    而讀不到的時候還沒有資格下那個結論。
    """
    try:
        text = READING.read_text(encoding="utf-8")
    except OSError as e:
        raise ReadingTableUnreadable(
            f"補讀表讀不到 {READING}（{type(e).__name__}: {e}）") from e
    out: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        m = _ROW.match(line.strip())
        if m:
            out[m.group(1)] = (m.group(2), m.group(3))
    return out


def coverage_gap(doc_id: str, fname: str = "") -> dict | None:
    """這一份讀了哪幾行，沒讀哪幾行。

    「2026-09-11 之前這裡回 None 並說明為什麼。現在它真的答得出來了。」

    答案來自 `.forseti/reading_coverage.jsonl`（append-only），
    由 `apps/forseti-cli/coverage.py` 的 `CoverageLog` 維護。

    沒有記錄的時候仍然回 None，而且那是對的：**沒有涵蓋記錄
    不等於沒讀，也不等於讀了。** 跟 `claims.py` 的三態同一個原則。
    回一個 0% 會冤枉一個真的讀過但沒記錄的人。
    """
    if not fname:
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "forseti_coverage",
            REPO / "apps" / "forseti-cli" / "coverage.py")
        if spec is None or spec.loader is None:
            return None
        cov = importlib.util.module_from_spec(spec)
        # 「先放進 sys.modules 再 exec，順序不能反。」
        #
        # `dataclasses` 在處理類別時會去 `sys.modules` 找宣告它的模組，
        # 找不到就炸 `AttributeError: 'NoneType' object has no attribute
        # '__dict__'`。2026-09-11 實際撞到：coverage.py 有 dataclass，
        # 而動態載入沒有註冊，於是每一次查詢都丟例外。
        sys.modules[spec.name] = cov
        spec.loader.exec_module(cov)
        log = cov.CoverageLog(root=REPO)
        rec = log.merged_for(str(SPEC_DIR / fname))
    except Exception as e:                   # noqa: BLE001
        # 「不要把例外吞成 None。」
        #
        # 原本這裡是 `except Exception: return None`，於是上面那個
        # AttributeError 被顯示成「coverage 無記錄」——
        # 一個壞掉的查詢跟一個誠實的「沒有記錄」長得一模一樣，
        # 而前者才是要修的。這正是這個專案一直在抓的形狀。
        return {"error": f"{type(e).__name__}: {e}"}
    if rec is None:
        return None
    return {"level": rec.level(), "ratio": round(rec.ratio, 4),
            "gaps": [list(x) for x in rec.gaps()],
            "conformant": rec.conformant()}


def check() -> dict:
    if not MANIFEST.is_file():
        return {"status": "CANNOT_CHECK",
                "why": f"manifest 不在 {MANIFEST}"}
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return {"status": "CANNOT_CHECK", "why": f"manifest 讀不了：{e}"}

    policy = man.get("reading_policy", "")
    want: list[tuple[str, str]] = [(man.get("architecture", "ARCH-EXEC-001"),
                                    "00_Forseti_Execution_Foundation_Architecture.md")]
    for f in man.get("features") or []:
        want.append((f.get("id", ""), f.get("file", "")))

    try:
        have = declared()
    except ReadingTableUnreadable as e:
        return {"status": "CANNOT_CHECK", "why": str(e)}
    rows = []
    bad = 0
    for doc_id, fname in want:
        p = SPEC_DIR / fname
        actual = sha12(p)
        dec = have.get(doc_id)
        if actual is None:
            verdict, why = "MISSING_FILE", f"檔案不在 {p}"
        elif dec is None:
            verdict, why = "NO_RECORD", "補讀表裡沒有這一份的記錄"
        elif dec[1] != actual:
            verdict, why = "CHANGED", f"記的是 {dec[1]}，現在是 {actual}"
        else:
            verdict, why = "OK", ""
        if verdict != "OK":
            bad += 1
        rows.append({"id": doc_id, "file": fname, "verdict": verdict,
                     "why": why, "actual": actual,
                     "declared": dec[1] if dec else None,
                     "coverage_gap": coverage_gap(doc_id, fname)})

    return {"status": "NON_CONFORMANT" if bad else "CONFORMANT",
            "policy": policy, "checked": len(rows), "bad": bad, "rows": rows}


def main(argv: list[str]) -> int:
    r = check()
    if "--json" in argv:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print()
        if r["status"] == "CANNOT_CHECK":
            print(f"  無法檢查：{r['why']}")
            return 2
        print(f"  政策　{r['policy']}")
        print(f"  檢查　{r['checked']} 份，不合格 {r['bad']} 份")
        print()
        for row in r["rows"]:
            mark = "  " if row["verdict"] == "OK" else "！"
            cg = row.get("coverage_gap")
            cov = ""
            if cg and cg.get("error"):
                cov = f"　coverage 查詢出錯：{cg['error']}"
            elif cg:
                cov = f"　coverage {cg['level']} {cg['ratio']:.0%}"
                if not cg["conformant"]:
                    cov += f"　沒讀到 {cg['gaps']}"
            elif row["verdict"] == "OK":
                cov = "　coverage 無記錄（不等於沒讀，也不等於讀了）"
            print(f"  {mark}{row['id']:<16} {row['verdict']:<12}"
                  f"{row['why']}{cov}")
        print()
        print("  hash 那一層驗的是「檔案沒變」與「補讀表有記錄」。")
        print("  coverage 那一層驗的是「讀了哪幾行」，來自")
        print("  .forseti/reading_coverage.jsonl（append-only）。")
        print("  沒有涵蓋記錄時顯示「無記錄」而不是 0%：沒記錄不等於沒讀。")
        print()
    return 0 if r["status"] == "CONFORMANT" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
