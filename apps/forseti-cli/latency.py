#!/usr/bin/env python3
"""修正延遲。從偏離開始到被拉回來，隔了多久。白皮書 §5.4

畫面上那句「飄了 N 輪才回來」是這個指標的雛形，但它只講最後一次。
**一次不是分布。** 一條線上偏離過八次，只看最後一次等於用一個樣本
去講一個趨勢，而趨勢正是這個指標唯一有用的地方:
它在變快還是變慢。

## 量什麼

每一段偏離有兩個座標:開始的那一輪、被拉回來的那一輪。
中間的距離用兩把尺量，因為它們回答不同的問題：

    輪數   我在錯的方向上做了幾件事
    時間   她被這件事卡了多久

**兩個都要。** 只看輪數會把「五輪但每輪三十秒」跟
「五輪但每輪二十分鐘」算成一樣;只看時間會把
「一輪耗時很久但方向正確」誤算進去。

## 誰把它拉回來的

    OWNER_CORRECTION   她開口糾正
    SELF_RECOVERED     沒有人講話，自己回到中軸
    STILL_OPEN         到最後一輪都還沒回來

這三種的意義差很多。**`SELF_RECOVERED` 越多代表這套東西越有價值**，
因為那表示偏離不必靠她消耗自己來修。反過來，`OWNER_CORRECTION`
佔多數就是 `continuity score 0.0 / burden 15` 的另一種寫法。

## 為什麼不合成一個分數

Five Mechanisms §6.8 雷一。這裡回的是每一段的清單加上分布，
不是一個「平均修正延遲 4.2 輪」。平均會把一次 32 輪的災難
跟七次一輪的小偏離抹平成同一個數字。
"""

from __future__ import annotations

#: 目標距離超過這個值算離開中軸。跟 vitals / lanes / divergence 一致。
DRIFT_ON = 0.08

RECOVERY = ("OWNER_CORRECTION", "SELF_RECOVERED", "STILL_OPEN")


def _n(r: dict) -> int:
    return int(r.get("n") or 0)


def _dist(r: dict) -> float:
    return float((r.get("goal") or {}).get("distance") or 0.0)


def _dur(r: dict) -> float:
    return float(r.get("duration") or 0.0)


def episodes(rows: list) -> list[dict]:
    """把每一段偏離抓出來，附上它怎麼結束的。"""
    out: list[dict] = []
    start = None
    for i, r in enumerate(rows):
        drifting = _dist(r) > DRIFT_ON
        if drifting and start is None:
            start = i
            continue
        if not drifting and start is not None:
            out.append(_close(rows, start, i, still_open=False))
            start = None
    if start is not None:
        out.append(_close(rows, start, len(rows) - 1, still_open=True))
    return out


def _close(rows: list, i0: int, i1: int, *, still_open: bool) -> dict:
    seg = rows[i0:i1 + 1]
    turns = len(seg)
    seconds = sum(_dur(r) for r in seg)

    if still_open:
        how = "STILL_OPEN"
        by = ""
    else:
        # 【2026-09-16 這裡本來在說謊】
        #
        # 原本只看 `corrected_by_owner`，而那個旗標走的是詞表。
        # 實測這條線上三段偏離，全部被判成「AI 自己回到中軸」，
        # 而真相是:第 229 輪她說「我決定全部刪除掉了」、
        # 第 287 輪她在貼終端輸出替我跑指令、
        # 第 337 輪前後都是 Request interrupted。
        #
        # **一個說謊的指標比沒有指標更糟**，因為它會讓人停止懷疑。
        # 改成問 `vitals.owner_stepped_in`，那裡面三種訊號都是 OBSERVED:
        # 打斷是系統寫的、貼終端輸出是她真的貼了、糾正是她真的打了那些字。
        #
        # 看回來那一輪往前三輪,因為她出手常常落在偏離的尾巴而不是
        # 回到中軸的那一刻。
        import vitals as _V
        hit = ""
        for r in rows[max(0, i1 - 3):i1 + 1]:
            hit = _V.owner_stepped_in(r)
            if hit:
                break
        how = "OWNER_CORRECTION" if hit else "SELF_RECOVERED"
        by = {"INTERRUPTED": "她按了打斷",
              "OPERATED": "她替我跑指令",
              "CORRECTED": "她開口糾正"}.get(hit, "自己回到中軸")

    return {
        "from_n": _n(rows[i0]),
        "to_n": _n(rows[i1]),
        "turns": turns,
        "seconds": round(seconds, 1),
        "minutes": round(seconds / 60.0, 1),
        "peak_distance": round(max(_dist(r) for r in seg), 3),
        "recovery": how,
        "recovered_by": by,
        "still_open": still_open,
    }


def summary(rows: list) -> dict:
    """分布，不是平均。

    平均會把一次 32 輪的災難跟七次一輪的小偏離抹平成同一個數字。
    """
    eps = episodes(rows)
    if not eps:
        return {"has": False, "episodes": [],
                "why": "這段沒有離開中軸過"}

    closed = [e for e in eps if not e["still_open"]]
    by_owner = [e for e in closed if e["recovery"] == "OWNER_CORRECTION"]
    self_rec = [e for e in closed if e["recovery"] == "SELF_RECOVERED"]
    still = [e for e in eps if e["still_open"]]

    turns = sorted(e["turns"] for e in closed)
    worst = max(eps, key=lambda e: e["turns"])

    def pick(frac: float) -> int:
        if not turns:
            return 0
        return turns[min(len(turns) - 1, int(len(turns) * frac))]

    return {
        "has": True,
        "episodes": eps,
        "count": len(eps),
        "closed": len(closed),
        "by_owner": len(by_owner),
        "self_recovered": len(self_rec),
        "still_open": len(still),
        # 分布用中位數與最壞值，不用平均。
        "median_turns": pick(0.5),
        "p90_turns": pick(0.9),
        "worst": {"from_n": worst["from_n"], "to_n": worst["to_n"],
                  "turns": worst["turns"], "minutes": worst["minutes"]},
        "owner_share": (round(len(by_owner) / len(closed), 3) if closed else None),
        "note": "self_recovered 越多代表偏離不必靠她消耗自己來修。"
                "owner_correction 佔多數，就是 continuity score 0.0 的另一種寫法",
        # 這一句要跟數字一起端出去。2026-09-16 實測:舊版判三段
        # 全部 SELF_RECOVERED，而三段的結束全是她在講話。
        "caveat": "SELF_RECOVERED 是上限不是事實。判斷靠三種 OBSERVED 訊號"
                  "（打斷、替我跑指令、糾正句式），句式那一項走詞表會漏抓 ——"
                  "漏抓的方向一律是把她的出手算成我自己回來的",
    }
