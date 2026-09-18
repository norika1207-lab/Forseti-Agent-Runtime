#!/usr/bin/env python3
"""指令列參數的三支共用判準。

## 為什麼有這個檔（2026-09-18 自動接續）

`antianchor.py`、`attempts.py`、`evidence.py`、`metrics.py`、
`probemodel.py` 五個檔各自有一份 `_arg` / `_flag_without_value` /
`_unknown_flags`。**那不是五份一模一樣的東西,是量出來的:**

    | 函式 | 幾份 | body 雜湊 |
    |---|---|---|
    | `_unknown_flags` | 5 | 五份全同 |
    | `_flag_without_value` | 5 | 五份全同（型別註記兩種寫法） |
    | `_arg` | 5 | **四種 body** |

`_arg` 那四種的差別只有兩處:antianchor 回 `default`（預設空字串）
而不是 `None`,以及有沒有 `str()` 保護非字串元素。**語意一致,
寫法四種** —— 先前的紀錄寫的是「六份」,份數與同不同都沒有量過。

這個檔是收斂的落點,不是第六份複製。**現在只有 `pollution.py`
用它。** 另外五支的搬遷沒有做:那是五個檔的改動,每一支都有自己的
測試與註解（例如 `probemodel._arg` 的 docstring 記著「不收等號會
讓 `run` 跑滿 36 次真呼叫」那次實測),整批搬要各自的反向驗證,
跟「新增一個入口」不是同一件工作。

## 為什麼名字不帶底線

同 `pollution.has_guard` 的理由,逐字照那一支的 docstring:
底線名稱會讓下一個人覺得「那是私有的,我自己再寫一份」——
而那正是這個檔存在要杜絕的機制。

呼叫端可以 `from cliargs import arg as _arg`,讓那五支搬過來的時候
本地的讀法不用跟著改。
"""

from __future__ import annotations


def arg(argv: list, name: str) -> str | None:
    """`--flag X` 與 `--flag=X` 兩種寫法讀到同一個值,重複出現取第一個。

    等號那一半不是可有可無。`evidence.py` 的紀錄寫著實測:
    `--path=X` 先前被靜默丟掉,於是呼叫端讀正本,而正本那時真的是
    0 筆 —— **錯的答案跟對的答案長得一模一樣。**

    回 `None` 不是空字串:呼叫端要分得出「沒寫」與「寫了一個空的」。
    """
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if str(a).startswith(name + "="):
            return str(a).split("=", 1)[1]
    return None


def flag_without_value(argv: list, name: str) -> bool:
    """旗標出現了,可是後面沒有值。

    這跟「旗標沒出現」要分得開。`arg` 兩種都回 None,而呼叫端拿
    None 當「沒指定,讀正本」——於是 `forseti evidence list --path`
    （手滑漏掉路徑）會去讀正本並回報一份看起來正常的報告。
    2026-09-18 實測 `forseti attempt list --path` 回的是正本那筆
    att-2bb74c352d,五個欄位完整印出來。**那個人以為他看到的是
    自己指定的檔。**

    「後面那個東西是另一個旗標」也算沒給值:實測
    `--by --reason 環境變了` 會 exit=0、印「記下了」、
    而磁碟上那一筆的 `by` 是 `--reason`。

    等號寫法不算在內:`--path=` 是明確給了一個空字串,
    跟沒寫完不是同一件事,留給呼叫端自己判。真的要傳一個以 `--`
    開頭的值,等號那條路還在（`--by=--reason` 照樣拿得到）。
    只認兩個減號,`-1` 這種值不受影響。
    """
    return any(a == name for a in argv) and not any(
        (a == name and i + 1 < len(argv)
         and not str(argv[i + 1]).startswith("--"))
        or str(a).startswith(name + "=")
        for i, a in enumerate(argv))


def unknown_flags(argv: list, known: tuple) -> list:
    """認不得的旗標名。打錯字不准靜默走預設。

    跟 `flag_without_value` 不是同一件事:那一支問的是「這個旗標
    後面有沒有值」,前提是旗標名對得上。名字打錯的時候那一支
    一律不觸發 —— 它 `any(a == name ...)` 找的是正確的那個名字。

    判準只認兩個減號開頭的 token,取等號之前那一段比對,所以
    `--by=--reason` 這種明著傳減號開頭的值照樣收（比的是 `--by`）。
    裸的 `--` 跳過:沒有一支實作那個慣例標記,這道守門不替它作決定。
    """
    out = []
    for a in argv:
        s = str(a)
        if not s.startswith("--") or s == "--":
            continue
        name = s.split("=", 1)[0]
        if name not in known and name not in out:
            out.append(name)
    return out
