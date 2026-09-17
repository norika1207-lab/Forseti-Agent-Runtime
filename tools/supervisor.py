#!/usr/bin/env python3
"""開發監督。停著就自動喚醒接續工作。

owner 2026-09-16：

    給我現在立刻寫一隻自動工具開發監督腳本，
    只要停著就會自動喚醒接續工作，我不准你再把我當奴力

事故背景:2026-09-15 17:02 停機、09-16 09:11 恢復，中間 16 小時，
她在那段時間發的指令沒有人接。`continuity score 0.0 / burden 15`
量的就是這件事:十五次「繼續」全部是她推的。

## 這支會花錢，所以有四道閘

一，**停止開關。** `.forseti/SUPERVISOR_OFF` 存在就完全不跑。
    要停不必改設定、不必記指令，建一個空檔案就停。

二，**每天上限。** 預設 12 次。超過就停到隔天，
    不管停滯多久都不再喚醒。

三，**冷卻。** 兩次喚醒之間至少隔 `COOLDOWN_MIN` 分鐘。
    沒有冷卻的話一次卡住會變成連環喚醒。

四，**要有事做才喚醒。** `.forseti/NEXT.md` 裡沒有「下一步」也沒有
    「卡在哪」的時候不喚醒 —— 沒事還把人叫起來，就是製造噪音，
    而 v5.0 §18 寫著:噪音多的守護者自己會變成另一個故障源。

## 它不判斷「該做什麼」

喚醒時送出的提示只有一句:去讀 `.forseti/NEXT.md` 然後接續。
**要做什麼是那份檔案說了算，不是這支腳本說了算。**
理由跟 `handoff.py` 一樣:兩個地方都能決定下一步，
它們遲早會不一致，而不一致的時候沒有人知道該信哪個。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NEXT = REPO / ".forseti" / "NEXT.md"
LOG = REPO / ".forseti" / "supervisor.jsonl"
OFF = REPO / ".forseti" / "SUPERVISOR_OFF"

#: 停滯多久算停著。**owner 2026-09-16 指定 7 分鐘。**
#:
#: 這三個數字是綁在一起的，改一個要看另外兩個：
#: 排程每 7 分鐘檢查一次，門檻也是 7 分鐘 —— 所以停下來之後
#: 最快 7 分鐘、最慢 14 分鐘會被接手。
IDLE_MIN = 7
#: 兩次喚醒之間的冷卻。比門檻稍長,讓被喚醒的那一輪有時間真的做事;
#: 冷卻比門檻短的話，前一次還在跑就會被再叫一次。
COOLDOWN_MIN = 10
#: 每天最多喚醒幾次。門檻從 25 降到 7 之後觸發會變密，
#: 上限跟著放寬，不然一個上午就用完然後整天不再接手。
MAX_PER_DAY = 40
#: 喚醒之後最多讓它跑幾輪。沒有上限的話一次喚醒可能跑很久。
MAX_TURNS = 40

#: 喚醒之後等幾秒，看它是不是起來就死了。
#: 正常的喚醒要跑很久（最多 MAX_TURNS 輪），不會在這個時間內退出；
#: **OAuth 過期那種失敗 2.7 秒就退了（2026-09-17 實測）。**
EARLY_EXIT_S = 6

#: 子行程的 stderr 寫這裡。原本丟 DEVNULL，於是
#: 「Failed to authenticate: OAuth session expired」這種訊息
#: 沒有任何人看得到，而 supervisor 照樣記一筆「喚醒成功」。
WAKE_LOG = REPO / ".forseti" / "supervisor_wake.log"

PROMPT = (
    "你在一個自動監督的迴圈裡被喚醒，因為這條線停了超過 "
    f"{IDLE_MIN} 分鐘而工作還沒做完。\n\n"
    "先讀 `.forseti/NEXT.md`，那裡面寫著現在卡在哪、還沒解決什麼。\n"
    "再讀 `.forseti/TODO_AUDIT_2026-09-16.md` 找還沒做完的項目。\n\n"
    "然後接續做下去，不要問使用者要做什麼 —— "
    "她已經說過『沒有完成的，全部給我一個一個完成，不用我來說』。\n"
    "做完一項就更新 NEXT.md，停下來之前也要更新。\n"
    "需要她決定的事情寫進 NEXT.md 的『還沒解決的』，不要停下來等。"
)


#: 算停滯的時候看哪些東西。**程式碼，不是對話紀錄。**
#:
#: 【2026-09-16 這裡本來是錯的，而且錯得很徹底】
#: 原本用「~/.claude/projects 底下最新的 transcript 有多久沒動」判停滯。
#: owner 同時開十幾個 session，實測五個 session 全部在 0.4 分鐘內有活動，
#: 所以那個指標在她身上永遠是 0，永遠判不出停滯。
#:
#: 更糟的是排程任務自己也是一個 session:它一跑起來，自己的 transcript
#: 就成了最新的，於是它看到 idle=0，判定沒停，然後結束什麼都不做。
#: **它在偵測自己。** 實測跑了三次，每次活 20 到 45 秒就退出。
#:
#: 要偵測的不是「有沒有人在講話」，是「Forseti 的程式碼有沒有在被改」。
WATCH_DIRS = ("apps", "tests", "tools", "src", "desktop/ui", "desktop/src-tauri/src")
WATCH_EXT = (".py", ".js", ".css", ".html", ".rs", ".sh")

#: `.forseti/` 整個排除。帳本、日誌、NEXT.md 都會自動更新 ——
#: 包括這支自己寫的 supervisor.jsonl。把它算進去又是一次自我否定。


def watched() -> list[Path]:
    """算停滯要看的檔案。只看原始碼。"""
    out = []
    for d in WATCH_DIRS:
        base = REPO / d
        if not base.is_dir():
            continue
        for f in base.rglob("*"):
            if not f.is_file() or f.name.startswith("._"):
                continue
            if f.suffix in WATCH_EXT:
                out.append(f)
    return out


def newest() -> Path | None:
    fs = watched()
    return max(fs, key=lambda p: p.stat().st_mtime) if fs else None


def idle_minutes(p: Path | None = None) -> float | None:
    """程式碼多久沒被改。碟沒掛就回 None，不要假裝停滯很久。"""
    if not REPO.is_dir():
        return None
    p = p or newest()
    if not p:
        return None
    return (time.time() - p.stat().st_mtime) / 60.0


def has_work() -> tuple[bool, str]:
    """NEXT.md 裡還有沒有事。沒有就不喚醒。"""
    if not NEXT.exists():
        return False, "沒有 NEXT.md，不知道要接什麼"
    t = NEXT.read_text(encoding="utf-8", errors="replace")
    if "## 卡在哪" in t or "## 還沒解決的" in t:
        return True, "NEXT.md 裡還有卡住的或沒解決的"
    if "沒有算得出來的下一步" in t and "## 卡在哪" not in t:
        return False, "NEXT.md 說沒有下一步，也沒有卡住的"
    return True, "NEXT.md 有內容"


def history() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def today_count(rows: list[dict] | None = None) -> int:
    rows = rows if rows is not None else history()
    day = time.strftime("%Y-%m-%d")
    return sum(1 for r in rows
               if time.strftime("%Y-%m-%d", time.localtime(r.get("at", 0))) == day
               and r.get("did") == "wake")


def last_wake(rows: list[dict] | None = None) -> float:
    rows = rows if rows is not None else history()
    ws = [r.get("at", 0) for r in rows if r.get("did") == "wake"]
    return max(ws) if ws else 0.0


def record(did: str, why: str, extra: dict | None = None) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {"at": time.time(), "did": did, "why": why}
    if extra:
        row.update(extra)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def decide() -> dict:
    """要不要喚醒。四道閘，任何一道擋住都不喚醒，而且說出是哪一道。"""
    if OFF.exists():
        return {"wake": False, "gate": "OFF",
                "why": f"停止開關存在：{OFF}"}

    rows = history()
    n = today_count(rows)
    if n >= MAX_PER_DAY:
        return {"wake": False, "gate": "DAILY_CAP",
                "why": f"今天已經喚醒 {n} 次，上限 {MAX_PER_DAY}"}

    since = (time.time() - last_wake(rows)) / 60.0
    if since < COOLDOWN_MIN:
        return {"wake": False, "gate": "COOLDOWN",
                "why": f"距上次喚醒 {since:.0f} 分鐘，冷卻 {COOLDOWN_MIN} 分鐘"}

    idle = idle_minutes()
    if idle is None:
        return {"wake": False, "gate": "NO_REPO",
                "why": "看不到專案原始碼，碟可能沒掛"}
    if idle < IDLE_MIN:
        return {"wake": False, "gate": "NOT_IDLE",
                "why": f"才停了 {idle:.0f} 分鐘，門檻 {IDLE_MIN}"}

    ok, why = has_work()
    if not ok:
        return {"wake": False, "gate": "NO_WORK", "why": why}

    return {"wake": True, "gate": "", "why": why,
            "idle_min": round(idle, 1), "today": n}


def wake(dry: bool = False) -> dict:
    """真的把它叫起來。"""
    # 不再帶 --resume。原本是接續「最新的 transcript」，而那個常常是
    # 別條線 —— owner 同時開十幾個 session。接錯線比開新線更糟。
    sid = ""
    cmd = ["claude", "-p", PROMPT,
           "--dangerously-skip-permissions",
           "--max-turns", str(MAX_TURNS)]
    if dry:
        return {"ok": True, "dry": True, "cmd": cmd[:2] + ["<prompt>"] + cmd[3:]}
    WAKE_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        err = WAKE_LOG.open("a", encoding="utf-8")
        err.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} 喚醒 ===\n")
        err.flush()
        p = subprocess.Popen(cmd, cwd=str(REPO),
                             stdout=subprocess.DEVNULL,
                             stderr=err,
                             start_new_session=True)
    except OSError as e:
        record("error", f"叫不動 claude：{e}")
        return {"ok": False, "why": str(e)}

    # 【起得來不等於做得了事】
    # 先前這裡只看 Popen 有沒有丟 OSError，而 OSError 只在
    # 「執行檔不存在、權限不足」這類情況出現。認證過期的時候
    # claude 起得來、幾秒後以非 0 退出，於是每一次失敗
    # 都被記成「喚醒成功」，帳本上看起來運作正常。
    #
    # 這跟 deploy.sh 只驗視窗數是同一個形狀:
    # 量到的是「動作發生了」，不是「事情做成了」。
    time.sleep(EARLY_EXIT_S)
    rc = p.poll()
    if rc is not None and rc != 0:
        tail = wake_log_tail()
        record("error", f"喚醒起來就退了 rc={rc}",
               {"pid": p.pid, "rc": rc, "stderr": tail})
        return {"ok": False, "why": f"claude 立刻以 rc={rc} 退出",
                "rc": rc, "stderr": tail}

    record("wake", "自動喚醒", {"pid": p.pid, "session": sid})
    return {"ok": True, "pid": p.pid, "session": sid}


def wake_log_tail(n: int = 6) -> str:
    """最近一次喚醒的 stderr 尾巴。抽不到就說抽不到，不回空字串。

    回空字串的話，「沒有錯誤」跟「讀不到錯誤」在紀錄裡長得一樣。
    """
    try:
        lines = WAKE_LOG.read_text(encoding="utf-8").splitlines()
    except OSError as e:
        return f"<讀不到 {WAKE_LOG.name}: {e}>"
    tail = [x for x in lines[-n:] if x.strip()]
    return " / ".join(tail) if tail else "<log 是空的>"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="停著就自動喚醒接續工作")
    ap.add_argument("--dry-run", action="store_true", help="只判斷不喚醒")
    ap.add_argument("--status", action="store_true", help="看現在的狀態")
    ap.add_argument("--off", action="store_true", help="建立停止開關")
    ap.add_argument("--on", action="store_true", help="移除停止開關")
    a = ap.parse_args(argv[1:])

    if a.off:
        OFF.parent.mkdir(parents=True, exist_ok=True)
        OFF.write_text(f"停於 {time.strftime('%Y-%m-%d %H:%M')}\n", encoding="utf-8")
        print(f"已停。刪掉 {OFF} 就會恢復")
        return 0
    if a.on:
        OFF.unlink(missing_ok=True)
        print("已恢復")
        return 0

    d = decide()
    if a.status or a.dry_run:
        idle = idle_minutes()
        print(json.dumps({
            "會不會喚醒": d["wake"],
            "擋住的閘": d.get("gate") or "（沒有）",
            "原因": d["why"],
            "停了幾分鐘": round(idle, 1) if idle is not None else None,
            "今天喚醒次數": today_count(),
            "上限": MAX_PER_DAY,
            "停止開關": OFF.exists(),
        }, ensure_ascii=False, indent=2))
        if a.dry_run and d["wake"]:
            print(json.dumps(wake(dry=True), ensure_ascii=False, indent=2))
        return 0

    if not d["wake"]:
        record("skip", d["why"], {"gate": d.get("gate", "")})
        return 0
    r = wake()
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
