#!/usr/bin/env python3
"""RuntimeNode。v5.0 §5 那張表的一列，位置在 §12.1 的拓樸裡。

回答的是 §39.1 Reality 那一組的第二欄：**現在跑在哪台機器**。

在這一支之前那一欄是 `NO_SOURCE`，理由寫著「`events` 表有
`runtime_node_id` 欄位，但 hooks 一律寫空字串，§12.1 的 RuntimeNode
沒有實作」。那句話當時是真的 —— `grep -rn runtime_node apps src` 只命中
`event_ledger.py` 的 schema 與 `contract.py` 自己那句理由。

這一欄空著的後果不是抽象的：`.forseti/NEXT.md` 的「已經發生過的決定」
第一條就是「換機器：舊機器硬碟不穩，工作移往新電腦」。
**一份記錄過換機器的交接檔，答不出現在這一份是在哪台機器上寫的。**

────────────────────────────────────────────────────

## 規格六欄，這一支填得出三欄

§5 那張表寫 `node_id, host, process, service, version, health`。
量得到的只有前三欄，後三欄**回 None 並且說得出為什麼**，
不投影、不借別的東西頂替。逐欄的理由在 `_UNFILLED` 那張表裡。

最重要的是 `health`。§12.2 寫得很清楚，服務健康狀態的來源是
「程序管理器加健康端點加 socket/listener」，這條線一個都沒接。
所以這一欄不是「健康」也不是「未知但看起來還好」，是 None。
理由借 `sot.py` 檔頭那一句：**一個沒有被檢查過的綠燈比沒有燈更糟，
因為它會讓人不去看。**

`version` 那一欄是刻意留空的，不是漏掉。§5 只寫 `version`，
沒說是誰的版本。這台機器的作業系統版本量得到（在 `measure()` 的
`host.os_version`），但把它接到這一欄等於重演 `contract.py` 已經
記過一次的那個形狀：「jsonl 的 `version` 是 CLI 版本不是模型版本」。
**名字對上不等於東西對上。** 所以量到的放 `measured`，
規格那一欄留 None，讓讀的人自己決定它們是不是同一個。

## node_id 怎麼來的，以及它到底有多穩

§10 那張 Stage 表第 3 條要的是「Agent/session/process identity
remains coherent across restart」，所以 node_id 不能是每次開機就變的
隨機值，也不能是 pid。

取的順序：

    1. IOPlatformUUID（macOS，`ioreg`，不需要 sudo）
    2. 取不到就退回 hostname

**兩者的穩定度不一樣，所以 `basis` 那一欄一定要帶著走。**
退回 hostname 的那個 node_id 會在改機器名字的那天變掉，
而那件事在畫面上跟「換了一台機器」長得一模一樣。
不寫下 basis 的話，沒有人分得出來。

存的是 sha256 前 16 碼，不是原值。理由是原值是硬體序號等級的東西，
而這一欄會被寫進 git 追蹤的檔案。雜湊在這裡不損失任何東西 ——
這一欄只需要「同一台機器算出同一個值」與「不同機器算出不同值」。

**跨重開機這件事這一輪沒有驗過**，驗過的是跨行程：兩個獨立的
python 行程算出同一個值（`tests/test_runtimenode.py`）。
跨重開機的穩定性靠的是 IOPlatformUUID 自己的性質，不是我量到的。
這兩件事不一樣，寫在這裡免得下一個人把後者讀成前者。

## 這一支一個字都不寫

沒有登記簿、沒有 jsonl、沒有 `register()`。全部是當下量出來的。

所以 `service` 永遠是 None —— 「這個節點提供什麼服務」是人登記的事實，
不是程式看得出來的。**不從行程名稱的長相推斷**，那是 B-05 擋住的做法：
靠文字判斷某件事有沒有成立，抓到的是符合句型的東西，
而漏掉的那些會長得跟「沒有」一模一樣。

要讓 `service` 有值，得先有一個人工登記簿（形狀照 `identity.py`）。
這一輪沒做，因為沒有人在等那一欄，硬接一個沒人用的寫入點
只會多一個要守的東西。

零依賴，只用標準庫。
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 規格 §5 那張表的六欄，逐字，順序不改。
SPEC_FIELDS = ("node_id", "host", "process", "service", "version", "health")

#: 每一欄的值是從哪裡來的。
#: `MEASURED` = 這一輪真的量到的；`NONE` = 沒有來源，`why` 說得出原因。
#: **沒有 `INFERRED`**，那正是不做的那一種。
ORIGIN_MEASURED = "MEASURED"
ORIGIN_NONE = "NONE"

#: 填不出來的那三欄，各自的理由。**這張表是這一支的主要產出之一** ——
#: 一個說得出自己為什麼是空的欄位，跟一個單純的空欄位不是同一件事。
_UNFILLED = {
    "service": (
        "「這個節點提供什麼服務」是人登記的事實，不是量得出來的。"
        "這一支沒有登記簿，而從行程名稱的長相推斷是 B-05 擋住的做法"
    ),
    "version": (
        "§5 那張表只寫 version，沒說是誰的版本。"
        "作業系統版本量到了，在 measure()['host']['os_version']，"
        "但接到這一欄等於重演「jsonl 的 version 是 CLI 版本不是模型版本」"
        "那個形狀 —— 名字對上不等於東西對上"
    ),
    "health": (
        "§12.2 寫的來源是「程序管理器加健康端點加 socket/listener」，"
        "這條線一個都沒接。沒探測就不給燈：一個沒有被檢查過的綠燈"
        "比沒有燈更糟，因為它會讓人不去看"
    ),
}

#: `ioreg` 取硬體 UUID 的查法。macOS 專用，不需要 sudo。
_IOREG = ("ioreg", "-rd1", "-c", "IOPlatformExpertDevice")

#: node_id 前綴。帶前綴是為了讓這個字串在帳本裡一眼看得出是什麼，
#: 不會跟 session id、incident id 混在一起。
_PREFIX = "node-"

#: `basis` 那一欄的兩個值。**取了名字是為了讓別人問得出「這個 id 穩不穩」
#: 而不必去比對字面字串。** 比對字面字串的那一種寫法，在這裡改一個字
#: 就會靜默地永遠成立或永遠不成立，而症狀是畫面上少了一句警告 ——
#: 少一句警告不會紅，所以沒有人會發現。
BASIS_UUID = "IOPlatformUUID"
BASIS_HOSTNAME = "hostname"


def _platform_uuid() -> str | None:
    """macOS 的 IOPlatformUUID。取不到就回 None，不丟例外。

    取不到有好幾種成因（不是 macOS、`ioreg` 不在、輸出格式變了），
    而它們的後果一樣：要退回 hostname。所以這裡不分辨，
    分辨的責任在 `basis` 那一欄 —— 它記的是「最後用了哪一個」。
    """
    if platform.system() != "Darwin":
        return None
    try:
        r = subprocess.run(_IOREG, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    for ln in r.stdout.splitlines():
        if "IOPlatformUUID" not in ln:
            continue
        parts = ln.split('"')
        # 形狀是 `"IOPlatformUUID" = "40366DB7-..."`，所以要的是最後一段引號。
        if len(parts) >= 4 and parts[-2].strip():
            return parts[-2].strip()
    return None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def measure(*, uuid: object = False, host: str | None = None) -> dict:
    """量這台機器。**只放真的量到的東西。**

    `uuid` 與 `host` 是給測試用的注入點:`uuid=False` 代表「照常去問」，
    `uuid=None` 代表「問不到」，給字串代表「問到這個」。
    不用 `None` 當預設值的理由是 `None` 在這一支裡有意義
    （問不到），拿它當「沒傳」的話兩件事會混在一起。
    """
    hn = host if host is not None else socket.gethostname()
    pu = _platform_uuid() if uuid is False else uuid
    if pu:
        basis, seed = BASIS_UUID, pu
    else:
        basis, seed = BASIS_HOSTNAME, hn
    return {
        "node_id": _PREFIX + _digest(seed),
        "basis": basis,
        "host": {
            "hostname": hn,
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            # 作業系統版本。**不是 SPEC_FIELDS 的 version**，理由見 `_UNFILLED`。
            "os_version": platform.mac_ver()[0] or platform.release(),
        },
        "process": {
            "pid": os.getpid(),
            "executable": sys.executable,
            "python": platform.python_version(),
            "cwd": os.getcwd(),
        },
    }


def node_id(*, uuid: object = False, host: str | None = None) -> str:
    """這台機器的穩定識別碼。同一台算出同一個。

    穩定度看 `measure()['basis']` —— 退回 hostname 的那一種
    會在改機器名字的那天變掉。
    """
    return measure(uuid=uuid, host=host)["node_id"]


def fields(*, uuid: object = False, host: str | None = None) -> dict:
    """§5 那六欄，逐欄帶 value / origin / why。

    填不出來的回 `value=None` 加一句 `why`，**不省略那一欄** ——
    省略掉的欄位跟從來沒有這個欄位長得一模一樣。
    """
    m = measure(uuid=uuid, host=host)
    out = {
        "node_id": {"value": m["node_id"], "origin": ORIGIN_MEASURED,
                    "why": f"從 {m['basis']} 算的 sha256 前 16 碼"},
        "host": {"value": m["host"]["hostname"], "origin": ORIGIN_MEASURED,
                 "why": "socket.gethostname()"},
        "process": {"value": f"pid {m['process']['pid']}"
                             f"　{m['process']['executable']}",
                    "origin": ORIGIN_MEASURED,
                    "why": "當下這個行程。**下一輪就不是同一個 pid**"},
    }
    for k, why in _UNFILLED.items():
        out[k] = {"value": None, "origin": ORIGIN_NONE, "why": why}
    # 順序照規格那張表，不照字典序。
    return {k: out[k] for k in SPEC_FIELDS}


def describe(*, uuid: object = False, host: str | None = None) -> dict:
    """給下游用的完整描述:六欄、量到的原始值、哪幾欄是空的。

    `unfilled` 單獨列出來不是重複 —— 下游要問的是
    「這個節點的描述完不完整」，那一題不該逼每個呼叫端自己再掃一次六欄。
    """
    f = fields(uuid=uuid, host=host)
    m = measure(uuid=uuid, host=host)
    return {
        "spec": "v5.0 §5 RuntimeNode / §12.1 Runtime topology",
        "fields": f,
        "measured": m,
        "filled": [k for k in SPEC_FIELDS if f[k]["value"] is not None],
        "unfilled": [k for k in SPEC_FIELDS if f[k]["value"] is None],
    }


def reference(*, uuid: object = False, host: str | None = None) -> dict:
    """§39.1 Reality 那一欄要的東西:指得出是哪一台。

    只有三個 key。**不是 `describe()` 的縮寫版**，是另一個問題的答案:
    §39.1 問「active machine/runtime node」，問的是這一份工作現在
    跑在哪，不是這個節點的完整實體。完整實體在 `describe()`。
    """
    m = measure(uuid=uuid, host=host)
    return {"node_id": m["node_id"],
            "host": m["host"]["hostname"],
            "basis": m["basis"]}


def summary_lines(d: dict | None = None) -> list[str]:
    d = d or describe()
    out = [f"node_id　{d['fields']['node_id']['value']}"
           f"　（{d['measured']['basis']}）",
           f"host　　 {d['fields']['host']['value']}"
           f"　{d['measured']['host']['system']}"
           f" {d['measured']['host']['os_version']}"
           f" {d['measured']['host']['machine']}",
           f"process　{d['fields']['process']['value']}",
           ""]
    out.append(f"六欄裡填得出 {len(d['filled'])} 欄，空的 {len(d['unfilled'])} 欄：")
    for k in d["unfilled"]:
        out.append(f"  {k}　{d['fields'][k]['why']}")
    return out


def main(argv: list[str]) -> int:
    d = describe()
    if "--json" in argv:
        print(json.dumps(d, ensure_ascii=False, indent=2))
        return 0
    for ln in summary_lines(d):
        print(ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
