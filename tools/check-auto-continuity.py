#!/usr/bin/env python3
"""真實帳本裡有沒有自動接上的派工。

存在的理由：F04 的 auto_dispatch() 從 2026-09-09 就寫好也測過了，
但一直到當天晚上，真實帳本裡的 8 筆 DISPATCH 全部是手動的，
continuity 分數是 0。機制通過自己的單元測試，卻從來沒有被真正的
工作呼叫過一次。

單元測試證明的是「它會動」。這支腳本問的是另一個問題：
「它有沒有真的被用過」。兩者不能互相取代 —— 一個只在測試裡動過的
機制，對使用者而言等於不存在。

回傳 0 代表帳本裡至少有一筆自動派工，非 0 代表沒有。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "forseti-cli"))

import ledger as L  # noqa: E402


def main() -> int:
    db = L.default_db()
    if not db.exists() or db.stat().st_size == 0:
        print(f"沒有帳本：{db}")
        return 2

    led = L.Ledger()
    try:
        rows = led.con.execute(
            "SELECT task_id, cause, payload FROM events WHERE kind='DISPATCH'"
        ).fetchall()
    finally:
        led.close()

    auto, manual = [], []
    for task_id, cause, payload in rows:
        try:
            p = json.loads(payload) if payload else {}
        except (ValueError, TypeError):
            p = {}
        (auto if p.get("auto") is True else manual).append((task_id, cause))

    print(f"派工事件　{len(rows)} 筆")
    print(f"  自動接上　{len(auto)}")
    print(f"  有人推的　{len(manual)}")

    if not auto:
        print()
        print("一筆自動派工都沒有。auto_dispatch() 可能寫好了、測過了，")
        print("但沒有被真實的工作呼叫過。單元測試不會發現這件事。")
        return 1

    print()
    for task_id, cause in auto[:10]:
        print(f"  {task_id}　{cause}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
