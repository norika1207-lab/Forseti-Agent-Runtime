#!/usr/bin/env python3
"""帳本裡有沒有被派工之後就音訊全無的步驟。

存在的理由：B-09。2026-09-08 一個 worker 死了十七小時才被發現。
watchdog 不是不會動，是它量的是 last_progress_at，而一個從頭到尾
沒發過任何事件的 worker，連讓 watchdog 起疑的第一筆訊號都沒有。
派工發生了、欄位填了、然後就是安靜 —— 這種安靜跟「做得很順所以
沒空講話」在帳本裡長得一模一樣，而帳本分不出來的東西，人也分不出來。

這支腳本問的問題很窄：哪些步驟「有人接了」（有 DISPATCH 事件，
或 assigned_worker 有值），但事件史裡一筆 F04 §3 的 worker 事件
都沒有。八種 worker 事件直接引用 ledger.WORKER_EVENTS，不自己抄
一份清單 —— 抄的那份會在 ledger 改的時候安靜地過期。

兩類分開報，因為該做的事不一樣：

  進行中的孤兒 —— 現在就該去查那個 worker 是死是活，影響 exit code。
  剛派出去還在寬限期內的不算：派工到第一聲回報本來就有延遲，
  把延遲當失蹤會讓這支腳本天天狼來了，然後沒人再看它。

  已終止但從頭到尾沒回報過的 —— 事後紀錄，不影響 exit code。
  它說明那一步的「完成」全靠控制端自己跑 verifier，worker 的
  回報通道根本沒接上。結果是對的，過程是瞎的。

回傳 0 代表沒有超過寬限期的進行中孤兒，1 代表有，2 代表沒有帳本。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import ledger as L  # noqa: E402


def _age(sec: float | None) -> str:
    if sec is None:
        return "不知道多久（沒有任何時間戳）"
    if sec < 90:
        return f"{sec:.0f} 秒"
    if sec < 5400:
        return f"{sec / 60:.0f} 分鐘"
    return f"{sec / 3600:.1f} 小時"


def collect(led: L.Ledger, grace: float) -> dict:
    steps = led.con.execute(
        "SELECT step_id, task_id, objective, state, assigned_worker, started_at"
        " FROM steps").fetchall()
    marks = ",".join("?" * len(L.WORKER_EVENTS))
    reported = {r[0] for r in led.con.execute(
        f"SELECT DISTINCT step_id FROM events WHERE kind IN ({marks})",
        L.WORKER_EVENTS)}
    dispatched_at = dict(led.con.execute(
        "SELECT step_id, MAX(at) FROM events WHERE kind='DISPATCH' GROUP BY step_id"))

    now = time.time()
    active, waiting, historical = [], [], []
    for step_id, task_id, objective, state, worker, started in steps:
        was_dispatched = step_id in dispatched_at or bool(worker)
        if not was_dispatched or step_id in reported:
            continue
        since = dispatched_at.get(step_id) or started
        row = {
            "step_id": step_id, "task_id": task_id, "objective": objective,
            "state": state, "worker": worker or "（欄位是空的）",
            "silent_sec": (now - since) if since else None,
        }
        if L.is_terminal(state):
            historical.append(row)
        elif row["silent_sec"] is not None and row["silent_sec"] <= grace:
            waiting.append(row)
        else:
            # 沒有任何時間戳的進行中派工不進寬限期：連「派出去多久了」
            # 都答不出來的步驟，就是最需要有人去看一眼的那種。
            active.append(row)

    # 連安靜多久都答不出來的排最前面，其餘照安靜時間長到短。
    for bucket in (active, waiting, historical):
        bucket.sort(key=lambda r: (r["silent_sec"] is not None,
                                   -(r["silent_sec"] or 0.0)))
    return {"orphans": active, "in_grace": waiting, "historical": historical,
            "dispatched": sum(1 for s in steps
                              if s[0] in dispatched_at or bool(s[4])),
            "grace_sec": grace}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="找出被派工但從未回報任何 worker 事件的步驟")
    ap.add_argument("--grace", type=float, default=900.0,
                    help="派工後多少秒內的安靜不算失蹤（預設 900）")
    ap.add_argument("--db", type=Path, default=None,
                    help="指定帳本檔（預設用這個 repo 的帳本）")
    ap.add_argument("--json", action="store_true", help="輸出 JSON")
    args = ap.parse_args(argv)

    db = args.db or L.default_db()
    if not db.exists() or db.stat().st_size == 0:
        print(f"沒有帳本：{db}")
        return 2

    led = L.Ledger(db=db)
    try:
        r = collect(led, grace=args.grace)
    finally:
        led.close()

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 1 if r["orphans"] else 0

    print(f"被派工過的步驟　{r['dispatched']} 個")
    print(f"  進行中、超過寬限期還一聲不吭　{len(r['orphans'])}")
    print(f"  進行中、還在寬限期（{args.grace:.0f} 秒）內　{len(r['in_grace'])}")
    print(f"  已終止、但從頭到尾沒回報過　{len(r['historical'])}")

    if r["orphans"]:
        print()
        print("孤兒。派工發生了，然後就沒有然後了。去查這些 worker 是死是活：")
        for o in r["orphans"]:
            print(f"  {o['step_id']}　{o['state']}　worker={o['worker']}"
                  f"　安靜了 {_age(o['silent_sec'])}")
            print(f"    {o['objective']}")

    if r["historical"]:
        print()
        print("已終止但通道全程沒接上的（不影響 exit code，但值得知道）：")
        for o in r["historical"]:
            print(f"  {o['step_id']}　{o['state']}　worker={o['worker']}")

    if not r["orphans"]:
        print()
        print("沒有進行中的孤兒。")
    return 1 if r["orphans"] else 0


if __name__ == "__main__":
    sys.exit(main())
