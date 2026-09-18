#!/usr/bin/env python3
"""從對話中間某一輪 fork 出一個新 session。

【2026-09-14 從 tools/fork-session.py 搬過來】
Widget 也要用、CLI 也要用，而判斷邏輯只能有一份。
跨目錄 import 在這個專案已經害過一次（`desktop_api` 去 import
住在 `tools/` 的 `timeline`，失敗被吞掉，畫面顯示「建議算不出來」）。

`tools/fork-session.py` 現在是這支的薄殼。

────────────────────────────────────────────────────
owner 2026-09-11 要的形狀：看到紅的那一節，從紅色之前那一節 fork，
任務接著跑。她補過兩個定義：一個節點等於一輪對話，
fork 是從那個節點 resume。

`clean fork` 在三份規格都出現而實作完全沒有：
`F05-WDG-001` §5 recovery ladder 倒數第二階、`F08-CTX-001` §4
rehydration 鏈的終點、`spec-v2.0` §17 Rescue 流程的
`CLEAN FORK / NEW SESSION / RESUME`。

────────────────────────────────────────────────────

## 為什麼內建的 --fork-session 不夠

`claude --resume <id> --fork-session` 存在，說明寫著
「When resuming, create a new session ID instead of reusing the original」。

但它是從 session 的結尾分岔。owner 要的是從中間某一輪 ——
而中間那一輪之後發生的事，正是要丟掉的那部分。

## 這支怎麼做到

transcript 的儲存格式本身就是一棵樹。每一行帶 `uuid` 與 `parentUuid`，
從任何一個節點沿著 `parentUuid` 往回走，就是那一刻的完整祖先鏈。

所以 fork 不需要改動宿主，只要：

    沿鏈收集到目標節點為止
    換一個 sessionId
    寫成新的 jsonl 放進同一個 projects 目錄

之後 `claude --resume <新 id>` 就從那個點接下去。

**原檔一個位元組都不動。** fork 是建立，不是修改 —— 一個會改到
原始對話的 fork，等於把「回頭看當時發生什麼」這件事毀掉，
而那正是 Source Tree 存在的理由。

## 它不做的事

不判斷該不該 fork。哪一節值得退回是人的判斷，
`tools/timeline.py` 只把候選標出來。

用法：

    python3 tools/fork-session.py <session-uuid> --at-line <行號>
    python3 tools/fork-session.py <session-uuid> --at-line 8818 --dry-run
"""

from __future__ import annotations

import json
import sys
import time
import uuid as _uuid
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"

#: 桌面版自己記的 session 清單。2026-09-18 跟著 `fork_at` 從
#: `desktop_api` 搬過來 —— 那支是畫面的資料來源,而 fork 是
#: `rescue` 也要用的東西,把 fork 放在畫面層等於任何要 fork 的人
#: 都得把整個畫面層拖進來。
SESSIONS_META = (Path.home() / "Library" / "Application Support" / "Claude"
                 / "claude-code-sessions")


def resolve(arg: str) -> Path:
    p = Path(arg).expanduser()
    if p.is_file():
        return p
    hits = sorted(PROJECTS.glob(f"*/{arg}*.jsonl"))
    if not hits:
        raise SystemExit(f"  找不到 transcript：{arg}")
    return hits[0]


def load(path: Path) -> list[tuple[int, dict | None, str]]:
    """(行號, 解析後的 dict 或 None, 原始行)。

    解析不了的行原樣留著。**丟掉一行看不懂的紀錄，
    等於在一份要當證據的檔案裡開一個洞。**
    """
    out = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            raw = line.rstrip("\n")
            if not raw.strip():
                continue
            try:
                out.append((i, json.loads(raw), raw))
            except ValueError:
                out.append((i, None, raw))
    return out


def ancestors(rows, target_uuid: str) -> set[str]:
    """從目標節點沿 parentUuid 往回走，收集整條祖先鏈。"""
    by_uuid = {}
    for _, d, _raw in rows:
        if d and d.get("uuid"):
            by_uuid[d["uuid"]] = d
    chain: set[str] = set()
    cur = target_uuid
    seen = 0
    while cur and cur in by_uuid and cur not in chain:
        chain.add(cur)
        cur = by_uuid[cur].get("parentUuid")
        seen += 1
        if seen > 200000:                # 壞掉的鏈不該讓程式轉不出來
            break
    return chain


def fork(path: Path, at_line: int, *, dry_run: bool = False) -> dict:
    rows = load(path)
    target = None
    for i, d, _raw in rows:
        if i == at_line and d and d.get("uuid"):
            target = d
            break
    if target is None:
        # 那一行可能不是對話行（工具結果、header）。往前找最近的一個。
        for i, d, _raw in reversed([r for r in rows if r[0] <= at_line]):
            if d and d.get("uuid"):
                target = d
                at_line = i
                break
    if target is None:
        raise SystemExit(f"  第 {at_line} 行附近找不到帶 uuid 的節點")

    keep = ancestors(rows, target["uuid"])
    new_sid = str(_uuid.uuid4())

    kept_lines, header_lines = [], []
    for i, d, raw in rows:
        if d is None:
            continue
        u = d.get("uuid")
        if u is None:
            # 「header 也要跟著行號截斷。」
            #
            # 沒有 uuid 的行不是無害的中繼資料,它們帶著 session 狀態:
            # last-prompt 是最後一次的 prompt、queue-operation 是待辦佇列、
            # custom-title 是標題。全部帶過去,等於把切點之後的狀態
            # 塞進一個宣稱停在切點的 session —— 那個 fork 會從一開始
            # 就說謊。
            if i <= at_line:
                header_lines.append((i, d))
        elif u in keep:
            kept_lines.append((i, d))

    out_rows = []
    for _, d in header_lines + sorted(kept_lines, key=lambda x: x[0]):
        row = dict(d)
        if row.get("sessionId"):
            row["sessionId"] = new_sid
        if row.get("bridgeSessionId"):
            row["bridgeSessionId"] = new_sid
        out_rows.append(row)

    dest = path.parent / f"{new_sid}.jsonl"
    info = {
        "source": str(path),
        "at_line": at_line,
        "target_uuid": target.get("uuid"),
        "target_type": target.get("type"),
        "kept": len(kept_lines),
        "headers": len(header_lines),
        "dropped": sum(1 for _, d, _r in rows if d and d.get("uuid")
                       and d["uuid"] not in keep),
        "new_session_id": new_sid,
        "dest": str(dest),
        "dry_run": dry_run,
    }
    if not dry_run:
        with dest.open("w", encoding="utf-8") as fh:
            for row in out_rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return info


def fork_at(session: str, n: int, dry_run: bool = True) -> dict:
    """從第 n 輪 fork 出一個新 session。§27

    owner 2026-09-11 要的形狀:看到紅的那一節，從紅色之前那一節 fork，
    任務接著跑。2026-09-14:「這樣才能 Fork 啊，不然都是單向的
    還要自己慢慢往前面翻。」

    切點是那一輪的**起點**（她發話那一行），因為那一輪之後發生的事
    正是要丟掉的部分。

    **原檔一個位元組都不動。** fork 是建立，不是修改 ——
    一個會改到原始對話的 fork，等於把「回頭看當時發生什麼」毀掉，
    而那正是這整個 Widget 存在的理由。

    【2026-09-14 實測到的限制，不要拿掉這段註解】
    fork 出來的 jsonl 桌面版看不到，因為它的側邊欄清單在記憶體裡，
    不會即時重掃目錄。在 `claude-code-sessions/` 補一份 metadata
    可以讓它重啟後出現，但 deep link 當下開不了它（測過，焦點沒變）。

    所以回傳裡給兩條真的走得通的路，不假裝可以當場開:
      重啟 Claude 之後它在側邊欄
      或者現在就 `claude --resume <新 id>`
    """
    import tracker as TK

    base = Path.home() / ".claude" / "projects"
    hits = sorted(base.glob(f"*/{session}*.jsonl"))
    if not hits:
        return {"error": f"找不到 {session}"}
    path = hits[0]

    tk = TK.Tracker(path)
    tk.poll()
    row = next((x for x in tk.strands if x.n == n), None)
    if row is None:
        return {"error": f"這條線裡沒有第 {n} 輪"}

    try:
        info = fork(path, row.owner_line, dry_run=dry_run)
    except SystemExit as e:
        return {"error": str(e)}
    except OSError as e:
        return {"error": f"寫不出來：{e}"}

    info["n"] = n
    info["owner_text"] = " ".join((row.owner_text or "").split())[:60]
    if not dry_run:
        # metadata 寫不出來不該讓 fork 算失敗 —— jsonl 已經寫好了,
        # `claude --resume` 那條路走得通,少的只是側邊欄會不會出現它。
        try:
            info["meta"] = _write_fork_meta(path.stem, info["new_session_id"], n)
        except (OSError, ValueError):
            info["meta"] = ""
        info["resume"] = f"claude --resume {info['new_session_id']}"
    return info


def _write_fork_meta(src_cli: str, new_cli: str, n: int) -> str:
    """給 fork 出來的分支補一份桌面版 metadata。

    從原 session 那份複製，只改該改的欄位 ——
    自己憑空編一份等於猜它的格式，而猜錯的那天沒有人會知道。

    **要重啟 Claude 才看得到。** 桌面版不重掃目錄。
    """
    import uuid as _uuid

    src = None
    for f in SESSIONS_META.rglob("local_*.json"):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if o.get("cliSessionId") == src_cli:
            src = (f, o)
            break
    if src is None:
        return ""
    f_src, o = src
    new_ui = "local_" + str(_uuid.uuid4())
    now = int(time.time() * 1000)
    o = dict(o)
    o.update({
        "sessionId": new_ui,
        "cliSessionId": new_cli,
        "title": f"{o.get('title', '')} · 從第 {n} 輪".strip(" ·"),
        "titleSource": "user",
        "createdAt": now,
        "lastActivityAt": now,
        "lastFocusedAt": 0,
        "completedTurns": n,
    })
    dest = f_src.parent / f"{new_ui}.json"
    dest.write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")
    return new_ui
