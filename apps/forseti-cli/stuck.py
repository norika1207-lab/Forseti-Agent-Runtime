#!/usr/bin/env python3
"""派不動的時候，講出到底是哪一種派不動。

2026-09-16 19:0x 加。起因是畫面與 `.forseti/NEXT.md` 上同時有一句話：

    T-7da5ef2183：7 個步驟都不在可動狀態

那句話是假的。實測 `steps_of()` 回來的 7 個步驟**全部**是
VERIFIED_COMPLETE，另一件 T-b95303aaa2 的 2 個也是。兩件任務都不是
卡住，是**做完了沒收尾**。任務自己停在 VERIFYING，所以
`ledger.next_step()` 走到迴圈底回 None，而呼叫端把「回 None」
一律翻譯成「步驟不在可動狀態」。

這兩件事要人做的動作完全相反：
一個是去把擋住的依賴解開，另一個是按收尾。
把它們印成同一句話，等於把讀的人推去做一件不存在的事。

── 這一支不做什麼 ────────────────────────────────

不改 `next_step()` 的判準。它回哪一步是對的，錯的是「回 None」
之後那句解釋。改判準的範圍比這一輪大，而且會動到 `auto_dispatch`
的四個條件（F04 §5）。

不自己定義新的步驟狀態。分類全部從 `ledger.TERMINAL` 與現有的
`dependencies` 欄位算出來，沒有一個是編的。

── 五條誠實條款，每一條都有對應的測試 ──────────────

一，**「永遠等不到」跟「正在等」不合併。** 一個依賴指到已經
    FAILED_TERMINAL 的步驟，跟一個依賴指到正在 RUNNING 的步驟，
    在「這一步現在不能動」上長得一模一樣，可是前者不會自己解開。
    合併成一句「等依賴」會讓人一直等一件不會發生的事。

二，**回名單不回數字。** 「2 個依賴沒滿足」說不出該去看哪裡。
    這條是這個專案第三次踩到同一件事（blast radius 的明細、
    JS 盲點的位置），所以直接寫成結構要求。

三，**依賴指到不存在的 step_id，回 `missing` 並指名。**
    不當成「還沒好」。一個打錯的依賴跟一個還沒做完的依賴，
    在「不在 done 集合裡」上完全一樣，而前者要改資料，後者要等。

四，**算不出來的時候回 UNKNOWN 並說少了什麼，不編一個原因。**
    v5.0 §8.3 的禁止捷徑。

五，**沒卡住就說沒卡住。** 呼叫端在 `next_step()` 有值的時候
    不該問這一支，但真的問了要回 NOT_STUCK，不是硬湊一個卡住的理由。

零依賴，ledger 由呼叫端傳進來（只用到 state_of / steps_of）。
"""

from __future__ import annotations

# 跟 ledger.TERMINAL 同一組，但這裡只需要「哪一個終局算成功」。
# 不 import ledger：這一支被 desktop_api 與測試各自載入，
# 多一條 import 邊就多一個循環的機會，而 ledger 已經是圖上代價最高的檔。
DONE = "VERIFIED_COMPLETE"
TERMINAL = ("VERIFIED_COMPLETE", "CANCELLED_BY_OWNER", "FAILED_TERMINAL",
            "SUPERSEDED")

KINDS = (
    "NOT_STUCK",           # 算得出下一步，呼叫端不該問
    "TASK_TERMINAL",       # 任務本身已經是終局
    "NO_STEPS",            # 還沒拆成步驟
    "ALL_VERIFIED",        # 步驟全部驗證完成，等的是收尾
    "ENDED_NOT_COMPLETE",  # 步驟都結束了，但有結得不好的
    "DEPS_UNMET",          # 有未完成步驟，依賴沒滿足
    "UNKNOWN",             # 算不出來，並且說得出少了什麼
)


def _blocking(step: dict, by_id: dict, done: set) -> list[dict]:
    """這一步被哪些依賴擋住，每一筆標明是哪一種擋法。"""
    out = []
    for dep in step.get("dependencies") or []:
        if dep in done:
            continue
        target = by_id.get(dep)
        if target is None:
            # 條款三：指到不存在的步驟。這不是「還沒好」，是資料壞了。
            out.append({"dep": dep, "why": "missing", "state": None,
                        "permanent": True,
                        "say": "這個依賴指到一個不存在的步驟"})
        elif target["state"] in TERMINAL:
            # 已經終局而且不是 VERIFIED_COMPLETE，所以它永遠不會進 done。
            out.append({"dep": dep, "why": "dead", "state": target["state"],
                        "permanent": True,
                        "say": f"這個依賴已經結束在 {target['state']}，"
                               "不會再變成驗證完成"})
        else:
            out.append({"dep": dep, "why": "pending", "state": target["state"],
                        "permanent": False,
                        "say": f"這個依賴還在 {target['state']}"})
    return out


def _has_cycle(pending: list[dict], by_id: dict) -> list[str]:
    """未完成步驟之間的依賴環。回環上的 step_id，沒有環回空清單。

    環跟「等一件還沒做完的事」在單看一步的時候一模一樣，
    差別是環永遠不會自己解開。所以它歸到 permanent 那一邊。
    """
    ids = {s["step_id"] for s in pending}
    colour: dict[str, int] = {}
    cycle: list[str] = []

    def walk(node: str, path: list[str]) -> bool:
        colour[node] = 1
        for dep in (by_id.get(node, {}).get("dependencies") or []):
            if dep not in ids:
                continue
            if colour.get(dep) == 1:
                cycle.extend(path[path.index(dep):] + [dep] if dep in path
                             else [dep, node])
                return True
            if colour.get(dep, 0) == 0 and walk(dep, path + [dep]):
                return True
        colour[node] = 2
        return False

    for s in pending:
        if colour.get(s["step_id"], 0) == 0 and walk(s["step_id"],
                                                     [s["step_id"]]):
            break
    return cycle


def diagnose(led, task_id: str) -> dict:
    """`next_step()` 回 None 的時候，這是為什麼。

    led 只需要有 state_of(task_id) 與 steps_of(task_id)。
    """
    base = {"task_id": task_id, "kind": "UNKNOWN", "permanent": None,
            "headline": "", "waiting_on": [], "unreachable": [],
            "action": None, "missing": None}

    try:
        tstate = led.state_of(task_id)
        steps = led.steps_of(task_id) or []
    except Exception as e:  # noqa: BLE001 - 條款四：講出少了什麼
        base["headline"] = "算不出派不動的原因"
        base["missing"] = f"讀不到這件任務的步驟：{type(e).__name__}"
        return base

    if tstate in TERMINAL:
        return {**base, "kind": "TASK_TERMINAL", "permanent": True,
                "headline": f"這件任務已經結束在 {tstate}，本來就不該有下一步",
                "action": None}

    if not steps:
        return {**base, "kind": "NO_STEPS", "permanent": False,
                "headline": "這件任務還沒有拆成步驟，所以沒有下一步可以派",
                "action": "把它拆成步驟"}

    done = {s["step_id"] for s in steps if s["state"] == DONE}
    pending = [s for s in steps if s["state"] not in TERMINAL]
    by_id = {s["step_id"]: s for s in steps}

    if not pending:
        bad = [{"step": s["local_id"], "state": s["state"]}
               for s in steps if s["state"] != DONE]
        if not bad:
            # 條款一那個真實案例：全部做完，只差收尾。
            return {**base, "kind": "ALL_VERIFIED", "permanent": False,
                    "headline": f"{len(steps)} 個步驟全部驗證完成了，"
                                f"沒有東西可以派　這件任務等的是收尾",
                    "action": "收尾"}
        return {**base, "kind": "ENDED_NOT_COMPLETE", "permanent": True,
                "headline": f"{len(steps)} 個步驟都結束了，"
                            f"其中 {len(bad)} 個不是驗證完成",
                "unreachable": bad,
                "action": "看那幾個沒完成的步驟要重開還是放掉"}

    # 還有未完成步驟，卻算不出下一步 → 每一個都被依賴擋著。
    waiting, unreachable = [], []
    for s in pending:
        for b in _blocking(s, by_id, done):
            row = {"step": s["local_id"], "dep": b["dep"].split("/")[-1],
                   "why": b["why"], "state": b["state"], "say": b["say"]}
            (unreachable if b["permanent"] else waiting).append(row)

    cyc = _has_cycle(pending, by_id)
    if cyc:
        unreachable.append({"step": cyc[0].split("/")[-1], "dep": "",
                            "why": "cycle", "state": None,
                            "say": "這些步驟互相等對方：" +
                                   " → ".join(x.split("/")[-1] for x in cyc)})

    if not waiting and not unreachable:
        # 每一個 pending 的依賴都滿足了，那 next_step() 不該回 None。
        # 條款五：這時候不硬湊理由。
        return {**base, "kind": "NOT_STUCK", "permanent": False,
                "headline": f"有 {len(pending)} 個步驟的依賴都滿足了，"
                            "派得動",
                "action": "派下一步"}

    parts = []
    if unreachable:
        parts.append(f"{len(unreachable)} 個等不到（不會自己解開）")
    if waiting:
        parts.append(f"{len(waiting)} 個在等還沒做完的步驟")
    return {**base, "kind": "DEPS_UNMET",
            "permanent": bool(unreachable),
            "headline": f"{len(pending)} 個步驟還沒完成，" + "，".join(parts),
            "waiting_on": waiting, "unreachable": unreachable,
            "action": ("先處理等不到的那幾個" if unreachable else None)}


def line(d: dict) -> str:
    """給畫面與交接檔用的一行字。

    刻意不在這裡加「派不動」三個字：ALL_VERIFIED 的時候那三個字是
    真的但會誤導，讀的人會去找哪裡壞了，而實情是做完了。
    """
    s = d.get("headline") or "算不出原因"
    act = d.get("action")
    return f"{s}　→　{act}" if act else s
