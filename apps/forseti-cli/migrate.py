#!/usr/bin/env python3
"""換機器。把「搬遷」變成一件會被記錄、能被驗證的事。§31

owner 2026-09-14，把舊電腦搬到新電腦那一整晚之後：

    一個舊電腦搬到新電腦這麼簡單的事情，Forseti 說什麼可以看到我們
    做了什麼，但沒有一個功能幫的到我。

她說得對。那一晚實際發生的事:

  ．一個 session 宣稱「全部搬完」，實際少了 workspace 綁定，
    142 個 local_*.json 沒過去，於是新電腦所有對話都開不了工作目錄
  ．沒有任何東西比對過兩邊的數字，所以「少了什麼」是靠人一個個發現的
  ．搬完之後沒有紀錄，隔天問「到底搬了什麼」誰也答不出來

這三件都是 Forseti 本來就該接住的:宣稱要對得上證據、
未完成的事要被自動暴露、做過的事要留在帳本裡。

## 它做什麼

    inventory()   掃這台機器，列出每一項該搬的東西與它的實際數字
    compare()     拿另一台的清單比，指出缺什麼、多什麼
    register()    把這次搬遷登記進 Forseti 帳本

## 它不做什麼

**不自己複製檔案。** 跨機器複製要走 AirDrop、外接碟或網路，
那是人的動作，而且是不可逆的。這支只負責:搬之前告訴你要搬什麼，
搬之後告訴你到底到了沒。

零依賴（ADR-009）。
"""

from __future__ import annotations

import hashlib
import json
import platform
import socket
import subprocess
import sys
import time
from pathlib import Path

H = Path.home()

# 每一項都指到實際路徑，而且附一句「丟了會怎樣」。
#
# 沒有那句話的清單，看的人不知道哪一項可以放棄 ——
# 而換機器的當下人是急的，急的時候需要的是取捨依據不是條目。
ITEMS = [
    {
        "key": "rules",
        "name": "Claude 規則與 memory",
        "paths": [H / ".claude" / "CLAUDE.md",
                  H / ".claude" / "COWORK.md",
                  H / ".claude" / "ISEEU_START_HERE.md"],
        "count_glob": (H / ".claude" / "projects", "*/memory/*.md"),
        "lose": "每一條都是付過代價才寫下的。丟了要重新犯一次同樣的錯",
    },
    {
        "key": "transcripts",
        "name": "對話紀錄",
        "count_glob": (H / ".claude" / "projects", "*/*.jsonl"),
        "lose": "所有專案的工作紀錄。Widget 畫的那條線就是它",
    },
    {
        "key": "workspace",
        "name": "session 的工作目錄綁定",
        "count_glob": (H / "Library" / "Application Support" / "Claude"
                       / "claude-code-sessions", "*/*/local_*.json"),
        "lose": "沒有它，新機器看得到對話標題卻開不了工作目錄，"
                "只能走遠端連回舊機。**2026-09-14 就是漏了這一項**",
    },
    {
        "key": "ledger",
        "name": "Forseti 任務帳本",
        "paths": [H / ".forseti" / "ledgers", H / ".forseti" / "events"],
        "sqlite": (H / ".forseti" / "ledgers", ("tasks", "steps", "events")),
        "lose": "append-only 的正本。義務只活在模型記憶裡的話，回合結束就散了",
    },
    {
        "key": "mem",
        "name": "claude-mem 記憶庫",
        "paths": [H / ".claude-mem" / "claude-mem.db"],
        "lose": "跨 session 的長期記憶",
    },
    {
        "key": "codex",
        "name": "Codex session",
        "count_glob": (H / ".codex" / "sessions", "**/*"),
        "lose": "Codex 那條線的完整工作紀錄",
    },
    {
        "key": "ssh",
        "name": "SSH 金鑰與 shell 設定",
        "count_glob": (H / ".ssh", "*"),
        "lose": "所有機器的連線能力。重建要一台一台重新授權",
    },
]


def _count(base: Path, pattern: str) -> int:
    if not base.exists():
        return 0
    try:
        return sum(1 for p in base.glob(pattern) if p.is_file())
    except OSError:
        return 0


def _sqlite_rows(folder: Path, tables: tuple) -> dict:
    """帳本不看檔案大小，看裡面幾筆。

    一個 0 筆的資料庫跟一個 293 筆的，檔案大小可能一樣。
    """
    import sqlite3
    out = {}
    if not folder.is_dir():
        return out
    for db in folder.glob("*.db"):
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for t in tables:
                out[t] = c.execute(f"select count(*) from {t}").fetchone()[0]
            c.close()
        except Exception:                                  # noqa: BLE001
            continue
    return out


def inventory() -> dict:
    """這台機器上，每一項該搬的東西現在是什麼數字。"""
    rows = []
    for it in ITEMS:
        row = {"key": it["key"], "name": it["name"], "lose": it["lose"]}
        n = 0
        if "count_glob" in it:
            base, pat = it["count_glob"]
            n = _count(base, pat)
            row["where"] = str(base).replace(str(H), "~")
        if "paths" in it:
            here = [p for p in it["paths"] if p.exists()]
            n = max(n, len(here))
            row["where"] = row.get("where") or str(
                it["paths"][0].parent).replace(str(H), "~")
            row["files"] = [p.name for p in here]
        if "sqlite" in it:
            folder, tables = it["sqlite"]
            row["rows"] = _sqlite_rows(folder, tables)
        row["count"] = n
        row["ok"] = n > 0
        rows.append(row)

    return {
        "host": socket.gethostname(),
        "model": _model(),
        "at": time.time(),
        "items": rows,
    }


def _model() -> str:
    try:
        return subprocess.run(["sysctl", "-n", "hw.model"],
                              capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except Exception:                                      # noqa: BLE001
        return platform.machine()


def compare(other: dict, mine: dict | None = None) -> dict:
    """拿另一台的清單比。**差在哪裡用數字講，不用形容詞。**"""
    mine = mine or inventory()
    a = {r["key"]: r for r in mine["items"]}
    b = {r["key"]: r for r in other.get("items", [])}
    gaps = []
    for k, want in b.items():
        got = a.get(k, {"count": 0, "name": want["name"], "lose": want["lose"]})
        if got["count"] < want["count"]:
            gaps.append({
                "key": k, "name": want["name"],
                "there": want["count"], "here": got["count"],
                "missing": want["count"] - got["count"],
                "lose": want["lose"],
            })
    return {
        "from": other.get("host", "?"),
        "to": mine["host"],
        "gaps": gaps,
        "complete": not gaps,
    }


def register(note: str = "", payload: dict | None = None) -> dict:
    """把這次搬遷登記進帳本。

    做過的事要留下來。隔天問「到底搬了什麼」，答案要在帳本裡不是在人的記憶裡。
    """
    import sqlite3
    folder = H / ".forseti" / "ledgers"
    dbs = sorted(folder.glob("*.db")) if folder.is_dir() else []
    if not dbs:
        return {"ok": False, "why": f"找不到帳本（{folder}）"}
    db = dbs[0]
    inv = inventory()
    body = {"note": note, "inventory": inv}
    if payload:
        body.update(payload)
    now = time.time()
    idem = hashlib.sha256(
        f"MIGRATE|{inv['host']}|{int(now)}".encode()).hexdigest()[:16]
    try:
        c = sqlite3.connect(db)
        tid = c.execute(
            "select task_id from tasks order by rowid desc limit 1").fetchone()
        c.execute(
            "insert into events (at, task_id, step_id, kind, from_state,"
            " to_state, cause, actor, payload, idem_key)"
            " values (?,?,?,?,?,?,?,?,?,?)",
            (str(now), tid[0] if tid else None, None, "MIGRATE", None, None,
             note or f"機器盤點：{inv['host']}", "owner",
             json.dumps(body, ensure_ascii=False), idem))
        c.commit()
        n = c.execute("select count(*) from events").fetchone()[0]
        c.close()
    except Exception as e:                                 # noqa: BLE001
        return {"ok": False, "why": f"寫不進帳本：{e}"}
    return {"ok": True, "events": n, "db": str(db)}


def _print(inv: dict) -> None:
    print()
    print(f"  {inv['host']}　{inv['model']}")
    print()
    for r in inv["items"]:
        mark = "有" if r["ok"] else "缺"
        extra = ""
        if r.get("rows"):
            extra = "　" + "、".join(f"{k} {v}" for k, v in r["rows"].items())
        print(f"  {mark}　{r['name']:<22}{r['count']:>6}{extra}")
        if not r["ok"]:
            print(f"        丟了會怎樣：{r['lose']}")
    print()


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "scan"
    if cmd == "scan":
        inv = inventory()
        if "--json" in argv:
            print(json.dumps(inv, ensure_ascii=False))
        else:
            _print(inv)
    elif cmd == "save":
        out = Path(argv[2]) if len(argv) > 2 else H / "forseti-inventory.json"
        out.write_text(json.dumps(inventory(), ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"  寫到 {out}")
        print("  把這個檔帶到另一台，跑：")
        print(f"    python3 {Path(__file__).name} compare {out.name}")
    elif cmd == "compare":
        if len(argv) < 3:
            print("  用法：compare <另一台存的 inventory.json>")
            return 2
        other = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        r = compare(other)
        print()
        print(f"  {r['from']}　→　{r['to']}")
        print()
        if r["complete"]:
            print("  沒有缺的。每一項的數字都不小於來源那台。")
        else:
            for g in r["gaps"]:
                print(f"  缺　{g['name']}　那台 {g['there']}，這台 {g['here']}"
                      f"　少 {g['missing']}")
                print(f"      {g['lose']}")
        print()
    elif cmd == "register":
        print(json.dumps(register(" ".join(argv[2:])), ensure_ascii=False))
    else:
        print(f"  不認得：{cmd}")
        print("  scan | save [檔名] | compare <檔名> | register [說明]")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
