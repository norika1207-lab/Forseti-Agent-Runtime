#!/usr/bin/env python3
"""交接。新 session 不貼任何東西就能接上。C4

owner 2026-09-16：

    17小時的空白，你到底要我怎麼樣才會好好的做事

那次是 09-15 17:02 停機、09-16 09:11 恢復，中間 16 小時 9 分鐘。
她在那段時間發的指令，對面沒有人。**停機本身控制不了，
但停機的時候沒有在檔案裡留下「接下來要做什麼」，那是可以控制的。**

## 為什麼是檔案不是口頭

`bible.md` H-01 記著她的原話:handoff 是文字就會失效，要是可驗證狀態。
所以這份不是一段交接敘述，是一份指得回證據的狀態:
每一項都附出處（帳本 id、檔案路徑、輪號），接手的人可以自己去查。

## 為什麼不塞全文

v5.0 §3.2 的非目標明寫「不把完整歷史對話倒進每個後繼 session」。
全文在 jsonl 裡，這份給的是座標。

## 寫入時機

**不是每次都寫。** 每兩秒被輪詢一次就重寫的檔案，
mtime 會失去意義 —— 而「這份交接是什麼時候寫的」正是接手的人
第一個要問的問題。所以有最小間隔，而且每次寫都記下當時的輪號。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 正本交接檔。停機之後接手的人唯一看得到的那一份就是它。
DEFAULT_OUT = REPO / ".forseti" / "NEXT.md"

#: 把預設寫入目標換掉的環境變數。
#:
#: **2026-09-18 加這一個，修的是一個一直在對接手的人說假話的根因。**
#: 上一輪（`AUTO_CONTINUE_LOG.md` 那一節）的原話：
#:
#:     正本 `.forseti/NEXT.md` 這一輪被測試用合成資料覆蓋過。收尾的
#:     時候讀到裡面寫「工作區跟 HEAD 不一致的：0 個」與「checkpoint
#:     2 個」，而實測工作區有二十幾個檔案有改動、這條 session 的
#:     checkpoint 是 0 個。兩個數字都不是真的。
#:
#: 成因不是誰寫錯了，是路徑本身：`desktop_api.strands()` 尾段無條件
#: 走 `_write_handoff()`，而 `_write_handoff()` 呼叫 `should_write()`
#: 與 `write()` **都不帶 path**，於是兩邊都落在這個模組全域上。測試
#: 餵合成 transcript 呼叫 `strands()` 的時候，算出來的是合成狀態，
#: 寫的地方卻是正本。
#:
#: **這跟「測試會動到 mtime」不是同一件事。** mtime 動是雜訊，
#: 內容被合成資料取代是交接檔對接手的人說假話 —— 而它偏偏是
#: 停機之後唯一有人看的東西，所以它的失敗方向不准是「看起來像真的」。
#:
#: 為什麼用環境變數而不是在測試裡 monkeypatch 這個全域：
#: 子行程繼承得到環境變數，繼承不到 monkeypatch。這個專案的測試裡
#: 有跑 `pytest` 迷你 session 的（`test_zz_forseti_write_attribution`
#: 的 e2e 那一組），那一條走的是真的子行程。
#:
#: **這一支不判斷「現在是不是在跑測試」。** 判斷在設環境變數的那一端
#: （`tests/conftest.py`），因為只有那一端知道自己是測試。這裡若自己去
#: 猜（看 `sys.modules` 有沒有 pytest 之類），正式執行時只要環境裡剛好
#: 有那個字，交接檔就會被默默導走 —— 而那種失敗一樣是安靜的。
OUT_ENV = "FORSETI_HANDOFF_OUT"


def resolve_out(env: dict | None = None) -> Path:
    """這一次的預設寫入目標。

    沒設、設成空的、設成只有空白，一律回正本 —— **拿不準就回正本**，
    因為導錯地方的後果是交接檔沒人在寫而且沒有人會發現，
    比多寫一次正本嚴重。
    """
    raw = ((env if env is not None else os.environ).get(OUT_ENV) or "").strip()
    return Path(raw).expanduser() if raw else DEFAULT_OUT


#: **import 的時候算一次**，跟它原本是個模組常數一致。
#: 跑到一半改環境變數不會生效，那是刻意的：一輪裡面換目標的話，
#: 「這一輪寫到哪裡」就沒有單一答案了。
OUT = resolve_out()

#: 兩次寫入的最小間隔。mtime 要保有意義。
MIN_GAP_S = 240

#: 一份交接狀態該有的欄位。**唯一的產生者是 `desktop_api._write_handoff()`**，
#: 這一組就是它傳過來的那些鍵。
#:
#: 2026-09-17 加。在這之前 `write()` 收任何 dict 都寫得出檔案:
#:
#:     handoff.write(desktop_api.strands(''), force=True)
#:
#: 那一行寫出 1309 位元組的殘缺交接檔（正常九千上下），北極星變
#: 「還沒設」，blockers、污染登記簿、交接契約整段消失，**而且不報錯**。
#: `strands()` 的回傳值跟這裡要的是兩種不同形狀的東西，兩邊的鍵
#: 一個都不重疊（實測 15 個必要欄位命中 0 個），但少掉的那些在
#: `render()` 裡全都是「沒有就不印那一節」，所以缺光了也長得像一份正常的檔。
#:
#: **停機之後接手的人唯一看得到的就是這個檔**，所以它的失敗方向
#: 不准是「看起來比實際好」。
REQUIRED_KEYS = frozenset({
    "at", "goal", "n",
    "next_actions", "awaiting_finish", "stuck", "unknowns",
    "decisions", "verified", "last_good",
    "blocker_lines", "contract_lines", "artifact_lines",
    "invalidated_lines", "recheck_lines", "coordinate_lines",
})


def missing_keys(state: object) -> list[str]:
    """這份狀態少了哪些必要欄位。照 `REQUIRED_KEYS` 的順序回，方便比對。

    **看的是鍵在不在，不是值是不是空的。** 兩件事差很遠:
    `"blocker_lines": []` 是「算過了，這一刻沒有」，
    整個鍵不存在是「根本沒有人算」。後者才是這裡要擋的。
    """
    if not isinstance(state, dict):
        return sorted(REQUIRED_KEYS)
    return sorted(k for k in REQUIRED_KEYS if k not in state)


def should_write(path: Path | None = None, now: float | None = None) -> bool:
    p = path or OUT
    if not p.exists():
        return True
    return (now or time.time()) - p.stat().st_mtime >= MIN_GAP_S


def render(state: dict) -> str:
    """把當下狀態寫成接手的人讀得懂的樣子。

    `state` 的每個欄位都是別人算好的，這裡只負責排版與標出處 ——
    這一支不自己判斷任何事，不然它會變成第二個事實來源。
    """
    ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(state.get("at") or time.time()))
    goal = (state.get("goal") or "").strip() or "（北極星還沒設）"
    lines = [
        "# 接下來要做什麼",
        "",
        f"這份是 Forseti 自動寫的，最後更新 {ts}。",
        "**不是交接敘述，是可查核的狀態。** 每一項都指得回出處，",
        "接手的人可以自己去查，不必相信這份文件。",
        "",
        "---",
        "",
        "## 北極星",
        "",
        f"> {goal}",
        "",
        f"出處 `.forseti/NORTH_STAR.md`",
        "",
    ]

    # 這一節回答的是「這一份是在哪裡寫的」。v5.0 §39.1 Identity + Reality
    #
    # 2026-09-17 21:xx 加。在這之前這份檔案只印缺口，**填得出來的欄位
    # 一個字都不印** —— 所以同一天稍早把 `runtime_node` 接成有值之後，
    # 這份交接照樣答不出「現在是在哪台機器上寫的」，而它自己的
    # 「已經發生過的決定」第一條就是「換機器」。
    #
    # 排在北極星底下、其他所有節之前，因為它決定底下每一條路徑
    # 該不該被相信 —— 座標不同的話，下面那些路徑指到的是別的東西。
    #
    # 行文由 `contract.coordinate_lines()` 算好，這裡只排版，
    # 理由跟底下每一節同一條:判斷放在排版這一支就會變成第二個事實來源。
    coord = state.get("coordinate_lines") or []
    if coord:
        lines += ["## 這一份是在哪裡寫的", ""] + list(coord)

    nxt = state.get("next_actions") or []
    fin = state.get("awaiting_finish") or []
    lines += ["## 下一步", ""]
    if nxt:
        lines += [f"{i}. {x}" for i, x in enumerate(nxt, 1)]
    elif fin:
        # 【2026-09-16 19:0x】先前這裡一律寫「可能是任務還沒拆成步驟」。
        # 對正本的兩件任務那句是假的：步驟全部驗證完成了，等的是收尾。
        # 一句猜錯方向的指示比沒有指示糟，它讓人去找一件不存在的事。
        lines.append("沒有待派的步驟，因為該派的都派完了。")
        lines.append("有任務在等收尾，見下面「等你收尾」。")
    else:
        lines.append("沒有算得出來的下一步。**這不等於沒事做** ——")
        lines.append("可能是任務還沒拆成步驟，見下面的「卡在哪」。")
    lines.append("")

    if fin:
        lines += ["## 等你收尾", "",
                  "這幾件的步驟**全部驗證完成**了，不是卡住。",
                  "系統不自己收尾 —— 那是一次狀態轉換，要留給人按。", ""]
        lines += [f"- {x}" for x in fin] + [""]

    stuck = state.get("stuck") or []
    if stuck:
        lines += ["## 卡在哪", ""] + [f"- {x}" for x in stuck] + [""]

    unknown = state.get("unknowns") or []
    if unknown:
        lines += ["## 還沒解決的", ""] + [f"- {x}" for x in unknown] + [""]

    # 這一節回答的是「有什麼在等 owner」。
    #
    # 2026-09-16 18:5x 加。在這之前 `NEXT.md` 一個 blocker 都看不到 ——
    # 上面「還沒解決的」那一節的來源是 blocked steps 與未讀文件，
    # 不是 `BLOCKERS.md`。所以 B-15 在等她一句話這件事，
    # 只讀這份交接的人不會知道。
    #
    # 行文由 `desktop_api._blocker_lines()` 算好，這裡只排版 ——
    # 這一支自己解析 BLOCKERS.md 就會變成第二個事實來源。
    blk = state.get("blocker_lines") or []
    if blk:
        lines += ["## 擋住的", ""] + list(blk) + [
            "",
            "出處 `.forseti/BLOCKERS.md`。一條阻塞要講得出它擋住哪個具體交付，",
            "講不出來的那叫待辦。",
            "",
        ]

    # 這一節回答的是「哪幾句話已經不成立了」。v5.0 §39.1 Limits + §40
    #
    # 2026-09-16 19:2x 加。上面「還沒解決的」講的是沒答案的問題，
    # 這一節講的是「有過答案，而那個答案是錯的」—— 兩種要做的事相反:
    # 前者要去找答案，後者要把已經傳出去的話收回來。
    #
    # 行文由 `contract.invalidated_lines()` 算好，這裡只排版，
    # 理由跟下面 contract_lines 那一節同一條。
    inv = state.get("invalidated_lines") or []
    if inv:
        lines += ["## 已經被推翻的", ""] + list(inv)

    lg = state.get("last_good")
    lines += ["## 最後一個已知良好的點", ""]
    if lg:
        lines += [f"`{lg.get('id', '')}`　第 {lg.get('n', '?')} 輪", "",
                  "出事的話從這裡回去。"]
    else:
        lines += ["沒有。**系統不自己挑** —— 最近的那一個常常正是出事的那一個。",
                  "要標記：打開任一輪，按「標記這裡是好的」。"]
    lines.append("")

    dec = state.get("decisions") or []
    if dec:
        lines += ["## 已經發生過的決定", ""] + [f"- {x}" for x in dec] + [""]

    ver = state.get("verified") or []
    if ver:
        lines += ["## 已驗證的狀態", ""] + [f"- {x}" for x in ver] + [""]

    # 這一段回答的是「這一輪產出了什麼」。v5.0 §39.1 Artifacts
    #
    # **一份說不出自己產出了什麼的交接，正是 2026-09-16 早上那個事故
    # 的形狀** —— 過期的狀態檔讓人重做一遍已經做完的事。
    # 行文一樣由 `contract.py` 算好，這裡只排版，理由同下面那一節。
    art = state.get("artifact_lines") or []
    if art:
        # 標題用 `contract.ARTIFACT_HEADING`，不在這裡再寫一次字面值。
        #
        # `contract.recorded_artifacts()` 靠這個標題把這一節切出來。
        # 兩邊各寫一次的時候，只改一邊會讓那一支切到 0 行 ——
        # **而 0 行讀起來跟「全部對得上」一樣**，不會有東西變紅。
        # 2026-09-18 實測過那條逃生路：把字面值搬進註解、印出去的
        # 那一行改掉，`test_artifact_drift.py` 35 條全綠。
        # 這裡改成同一份常數，那條路構造上就走不出來了。
        #
        # 延後 import，理由**不是**「模組頂層會炸」。2026-09-18 實測過：
        # 把兩邊都搬到模組頂層造成真的環，`tests/test_artifact_drift.py`
        # 38 條照樣全綠，兩個載入順序都不炸。因為這一刻雙方在載入期間
        # 都沒有碰對方的名字。
        #
        # 留在函式裡的理由是那個「這一刻」：模組頂層互相 import 之後，
        # **哪一天任何一邊在載入期間用到對方一個名字，它就會炸**，
        # 而那一天量不到、也沒有測試守得住。放在函式裡是把那個未來拿掉。
        import contract  # noqa: PLC0415
        lines += [contract.ARTIFACT_HEADING, ""] + list(art)

    # 這一段回答的是「這份交接本身夠不夠」。v5.0 §39.1
    #
    # 上面每一節都在講「現在在哪」，而它們全都可能同時是空的，
    # 然後這份檔案看起來仍然很完整 —— 那正是 2026-09-16 被過期狀態檔
    # 咬到的形狀。所以這一節講的是這份檔案自己缺什麼。
    #
    # **行文由 `contract.py` 算好，這裡只排版。** 這一支自己判斷就會
    # 變成第二個事實來源，然後兩個來源開始不一致。
    # 這一段回答的是「這份交接裡的理由還算不算數」。
    #
    # 上一節講的是欄位缺什麼，這一節講的是**缺席的理由本身腐爛了沒有**。
    # 兩者差很遠：前者說「這一欄沒有值」，後者說「那句解釋為什麼沒有值
    # 的話，當初附的查法現在對不上了」。一句過期的理由比沒有理由危險，
    # 因為它指出的下一步是錯的。
    #
    # 行文由 `contract.recheck_lines()` 算好，這裡只排版，理由同下一節。
    rck = state.get("recheck_lines") or []
    if rck:
        lines += ["## 這份交接裡有理由過期了", ""] + list(rck)
        lines += ["自己查：`python3 apps/forseti-cli/contract.py`", ""]

    con = state.get("contract_lines") or []
    if con:
        lines += ["## 這份交接照規格少了什麼", ""] + list(con)
        lines += ["出處 v5.0 §39.1 Minimum Handoff Contract。",
                  "自己查：`python3 apps/forseti-cli/contract.py`", ""]

    lines += [
        "---",
        "",
        "## 給接手的人",
        "",
        "先讀 `.forseti/REQUIRED_READING.md`，再讀這一份。",
        "這份只講「現在在哪」，那份講「動手之前要先讀什麼」。",
        "",
        "**接下來按什麼順序做，看 `.forseti/ROADMAP.md`。**",
        "這一份的「下一步」只長得出已經被拆成步驟的任務，",
        "而還沒拆的那些不會出現在這裡 —— 看不到不等於沒有。",
        "每一輪實際做了什麼、驗證到哪裡，在 `.forseti/AUTO_CONTINUE_LOG.md`。",
        "",
        f"這條線的輪號到第 {state.get('n', '?')} 輪。全文在 "
        "`~/.claude/projects/` 底下的 jsonl，**這份不複製全文**，",
        "因為 v5.0 §3.2 明寫不把完整歷史對話倒進每個後繼 session。",
        "",
    ]
    return "\n".join(lines)


def write(state: dict, *, path: Path | None = None, force: bool = False) -> dict:
    """把狀態寫成交接檔。形狀不對就**拒絕寫，而且不動原本那個檔**。

    `force` 只蓋得過時間間隔，蓋不過形狀檢查 —— 那次事故的指令
    帶的正是 `force=True`，一個「我確定」的旗標不該讓錯的形狀通過。

    拒絕的時候原本那個檔留在原地。一份舊的完整交接，比一份新的
    殘缺交接有用:前者的 mtime 自己會講「這份是舊的」，
    後者看起來是最新狀態，而那是假的。
    """
    p = path or OUT
    miss = missing_keys(state)
    if miss:
        why = ("不是一份交接狀態，少了 " + "、".join(miss)
               + f"（共 {len(miss)}/{len(REQUIRED_KEYS)} 個）。"
                 "唯一的產生者是 desktop_api._write_handoff()")
        # 拒絕要看得見。這個檔案存在的理由就是停機之後有人接得上，
        # 所以「不寫」這件事本身不准也是安靜的 —— 那會換成另一種沉默。
        print(f"[handoff] 拒絕寫入 {p}：{why}", file=sys.stderr)
        return {"ok": False, "why": why, "missing": miss, "path": str(p)}
    if not force and not should_write(p):
        return {"ok": False, "why": f"距上次寫不到 {MIN_GAP_S} 秒",
                "path": str(p)}
    p.parent.mkdir(parents=True, exist_ok=True)
    text = render(state)
    p.write_text(text, encoding="utf-8")
    return {"ok": True, "path": str(p), "bytes": len(text.encode("utf-8"))}
