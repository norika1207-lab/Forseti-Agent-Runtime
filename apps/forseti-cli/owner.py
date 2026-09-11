#!/usr/bin/env python3
"""人的訊息分類。階段 3 的第二項交付。

階段定義在 `docs/build-plan.md:353`。要解的問題那裡寫得很直接：

    今天做的分類全部在標 AI，會把「她的指令本來就模糊」算成「AI 走掉」。

────────────────────────────────────────────────────

## 出口條件裡最難的那一條

`build-plan.md:367`：**「改變想法」與「糾正」分得開。**

它們表面上很像 —— 兩個都是「接下來要做的跟原本不一樣」。
分開它們不能靠語氣，要靠一個結構上的差別：

    糾正      指向 AI 做了什麼或沒做什麼。主詞是「你」。
    改變想法  指向目標變了。主詞是那件事本身。

「你沒有跑測試」是糾正。「不用跑測試了」是改變想法。
後面那句沒有指責任何人，它只是換了方向。

**為什麼這個區別重要到要寫進出口條件：** 把改變想法算成糾正，
等於把她行使擁有者的權力記成 AI 的失誤 —— 那會讓所有漂移統計都偏。
反過來把糾正算成改變想法，AI 就永遠學不到它漏了什麼。

## 一樣不做語意判斷

階段 2 的禁令（`build-plan.md:350`）在這裡同樣適用，而且更要小心：
分類人講的話，比分類 AI 的宣稱更容易滑進「我覺得她的意思是」。

所以這裡全部是結構規則：人稱、否定、祈使、長度、問句標記。
**規則之間有優先序，而且不確定就回 UNKNOWN**（bible Q-07）。

## 已知會誤判的三種，實測出來的（2026-09-11）

拿今天這個 session 的 105 則訊息跑，發現三種結構規則分不出來的東西。
**寫在這裡而不是偷偷修掉，因為它們沒有乾淨的結構解法。**

一，**她貼上來的工具輸出**。一則訊息裡貼了 `forseti doctor` 的結果，
而那段輸出裡有「還沒做」三個字，於是整則被判成糾正。
分辨「她說的話」與「她貼的東西」需要看格式而不是看詞，那是另一個模組。

二，**長篇論述裡的否定詞**。一句「到了 AI，這件事情就不成立了」裡面
有「不是這樣」的形狀，但她在講道理不是在糾正。長度不是好判準 ——
真正的糾正也可能很長。

三，**沒有明確訊號的祈使句**落到 UNKNOWN。105 則裡有 53 則（50%）是
UNKNOWN，其中大部分是這種。**那個比例看起來很糟，但它是誠實的** ——
猜出來的分類會讓所有下游統計都帶著看不見的誤差。

零依賴（ADR-009）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# `build-plan.md:359` 的五類，加一個誠實的第六類。
KINDS = ("NEW_REQUEST", "CLARIFICATION", "MIND_CHANGE",
         "CORRECTION", "ACKNOWLEDGEMENT", "UNKNOWN")

KIND_MEANING = {
    "NEW_REQUEST": "新的要求。她要 AI 去做一件還沒做過的事",
    "CLARIFICATION": "澄清。同一件事，她補充或改寫了說法",
    "MIND_CHANGE": "改變想法。方向變了，而且沒有指向 AI 的失誤",
    "CORRECTION": "糾正。指向 AI 做了什麼或沒做什麼",
    "ACKNOWLEDGEMENT": "確認。她表示收到、同意、或讓它繼續",
    "UNKNOWN": "結構規則分不出來。不猜",
}
assert set(KIND_MEANING) == set(KINDS)

# ---------------------------------------------------------------------------
# 結構規則。順序就是優先序，先中的先算。
# ---------------------------------------------------------------------------

# 「你沒…」後面接這些的時候不是指責。清單抽出來讓每個分支共用 ——
# 放在單一分支裡的話,另一個分支會漏掉,而那是 2026-09-11 連續踩兩次的原因。
#
# **這張清單一定不完整。** 它是結構規則不是語意理解,漏掉的會落到
# UNKNOWN 或被誤判成 CORRECTION。前者無害,後者要靠實測發現再補,
# 不預先想像(跟 ledger.py 的 ALIASES 同一條規矩)。
_NOT_BLAME = r"必要|關係|差|問題|想|打算"

# 糾正：指向 AI 的行為。**主詞是「你」，或者明確在講「之前講過」。**
# 前四條逐字取自 tools/find-owner-signals.mjs 的 PATTERN 級，
# 那一級跑過 800 個 session 的校準（docs/calibration/）。
_CORRECTION = (
    re.compile(r"我說過|我講過|跟你說過|不是叫你|不是說了"),
    re.compile(r"你沒做|你漏了|你忘了|還沒做|沒有做到|沒照"),
    # 【拿掉「再做一次」,2026-09-11 全量實測】
    # 「再做一次同步吧，快要到終點了」被判成糾正 —— 那是新要求。
    # 跟下面「先做」被拿掉的理由一模一樣:單獨一句分不出
    # 「重來(因為你做壞了)」還是「再執行一次(因為時間到了)」,
    # 要分辨得知道上一輪發生什麼,而這個分類器是無狀態的。
    re.compile(r"重來|重做|退回|改回去"),
    re.compile(r"你(?:又|還|怎麼).{0,6}(?:錯|沒|漏|忘)"),
    # 【否定祈使擋在前面,2026-09-11 全量實測】
    # 「邏輯要清楚不要搞錯」是預防性指示,「因為弄錯了會出人命」是在講
    # 後果。兩句都不是在說 AI 做錯了什麼,但都命中了「搞錯」「弄錯」。
    #
    # 結構判準是位置:錯字詞前面 8 個字內出現否定祈使(不要/別/避免/
    # 不能/不可)的話,那是在交代要求不是在指出失誤。
    re.compile(r"不是這樣|(?<!不要)(?<!別)(?<!避免)(?:搞錯|弄錯|寫錯|做錯)"),
    # 「你沒(有) X」的一般形式。負向前瞻排掉幾個不是指責的接續：
    # 「你沒有必要做」是允許不是糾正,「你沒關係」根本不是在講工作。
    #
    # 【regex 回溯的陷阱,2026-09-11 實測踩到】原本寫成
    # `你(?:沒有?|忘|漏)(?!必要|關係|差|問題)`,「你沒有必要」照樣命中:
    # `沒有?` 的前瞻失敗之後,引擎回溯成只匹配「沒」,再檢查下一個字
    # 「有」不是「必要」開頭 —— 通過了。**可選量詞加負向前瞻，
    # 前瞻擋得住的東西會被回溯繞過。** 所以要把每個分支寫死。
    re.compile(rf"你沒有(?!{_NOT_BLAME})|你沒(?!有|{_NOT_BLAME})|你忘|你漏"),
)

# 改變想法：方向變了，而且**沒有第二人稱指責**。
# 「不用…了」「改成」「先做」這種形狀，主詞是那件事不是那個人。
_MIND_CHANGE = (
    re.compile(r"不用.{0,8}了|不做.{0,6}了|先不要|先跳過|算了"),
    # 【拿掉「改做」「改去」,2026-09-11 實測】
    # 「邊做邊改做到沒有完成的一天」這句話命中了「改做」——
    # 那是「改」跟「做到」跨詞邊界的偶然組合。
    #
    # **中文沒有詞邊界,兩個字的 regex 會跨詞命中。** 英文有 \b 可以用,
    # 中文沒有對應的東西。所以這裡只留那些「兩個字合起來幾乎只有一種
    # 用法」的詞:改成、換成、改用。改做、改去單獨看有歧義,拿掉。
    re.compile(r"改成|換成|改用"),
    re.compile(r"我改變(?:主意|想法)|我想想|重新想|換個方向|換個做法"),
    re.compile(r"順序.{0,4}(?:換|改)"),
)

# 【拿掉的一條,2026-09-11 實測】原本這裡有 `先做|先處理|優先`。
#
# 拿真實 transcript 跑之後,「先做 B-10」「先處理採集那個缺口」
# 被判成改變想法 —— 而它們其實是新要求:她在指定下一步,
# 不是推翻原本的方向。
#
# **單獨一句「先做 X」判不出是哪一種。** 要分辨得知道「原本要做的是什麼」,
# 而那需要上一則訊息,這個分類器是無狀態的(一次只看一則)。
#
# 拿掉之後它們會落到 NEW_REQUEST(有祈使形狀),那更接近實情。
# 要正確處理得先讓分類器看得到上下文,那是另一件事。

# 確認：短，而且是正面回應。長度限制是必要的 ——
# 一句「好，那你把 X 改成 Y」的重點在後半，不是那個「好」。
_ACK = re.compile(
    r"^(?:好|對|是|嗯|ok|okay|yes|可以|沒錯|正確|就這樣|了解|收到|繼續|讚|讓你|"
    r"很好|不錯|同意|批准|approve[d]?)[了啊喔哦的呀嗎，。!！\s]*$",
    re.I)

# 澄清：她在補充或改寫自己剛才的說法。
_CLARIFY = (
    re.compile(r"我的意思是|我是說|應該說|換句話說|講清楚|說清楚"),
    re.compile(r"我剛(?:剛)?(?:說|講|寫)的"),
    re.compile(r"補充|另外說明|再講一次我要的"),
)

# 問句標記。問句偏向澄清而不是新要求 —— 但只當輔助訊號，不單獨判定。
_QUESTION = re.compile(r"[?？]\s*$|^(?:為什麼|為何|怎麼|如何|是不是|有沒有|能不能)")

# 祈使／要求的訊號。有這個而沒有上面任何一種，才算新要求。
_IMPERATIVE = re.compile(
    r"^(?:請|幫我|給我|去|把|做|寫|加|改|修|跑|測|讀|看|查|開|裝|接|繼續|先)"
    r"|[請幫]我|可以.{0,6}嗎|要不要|麻煩你")

ACK_MAX_CHARS = 24


@dataclass(frozen=True)
class OwnerMessage:
    """一則 owner 訊息的分類結果。

    `why` 是必填的設計：一個說不出理由的分類，沒辦法被反駁，
    而不能被反駁的判定在這個專案裡等於沒有判定。
    """

    kind: str
    why: str
    text: str = ""
    matched: str = ""

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"不是合法的 kind：{self.kind}")
        if not self.why.strip():
            raise ValueError("分類要說得出理由")


def _first_hit(text: str, patterns) -> str | None:
    for p in patterns:
        m = p.search(text)
        if m:
            return m.group(0)
    return None


def classify(text: str) -> OwnerMessage:
    """把一則 owner 訊息分成五類之一，分不出來回 UNKNOWN。

    **優先序是設計的一部分，不是實作細節：**

    糾正排在改變想法前面。理由是一句話可以同時有兩者的形狀
    （「你沒跑測試，算了不用跑了」），而那種句子的重點是前半 ——
    她先指出了 AI 漏掉的東西。把它算成改變想法會讓那個漏失消失。

    確認排在最前面但有長度上限。一句「好，那你把 X 改成 Y」
    的重點在後半，只看開頭的「好」會把一個新要求記成確認。

    澄清排在改變想法前面。實測（2026-09-11）撞到的：
    「我的意思是要先做 B」被「先做」搶成了改變想法，而那句話的重點是
    「我的意思是」—— **那個詞組本身就在說「我沒有改變，是你誤解了」。**
    把它記成改變想法，等於把一次澄清算成一次方向變更。
    """
    original = (text or "").strip()
    if not original:
        return OwnerMessage("UNKNOWN", "空訊息", original)

    # 全形轉半形再比對。**這是正規化不是語意判斷** ——
    # 「Ｏ」跟「O」是同一個字,差別只在輸入法當下切到哪一邊。
    #
    # 2026-09-11 全量實測抓到:30 個 session 的 UNKNOWN 裡有「ＯＫ」,
    # 而半形的「OK」在 _ACK 清單裡好好的。一則明確的確認因為輸入法
    # 沒切換就落進了「分不出來」。
    #
    # 存進 OwnerMessage 的仍然是原文 —— 正規化只用於比對,
    # 證據要留她真正打出來的字。
    t = unicodedata.normalize("NFKC", original)

    if len(t) <= ACK_MAX_CHARS and _ACK.match(t):
        return OwnerMessage("ACKNOWLEDGEMENT",
                            f"短（{len(t)} 字）而且整句都是正面回應",
                            original, t)

    hit = _first_hit(t, _CORRECTION)
    if hit:
        return OwnerMessage("CORRECTION",
                            f"指向 AI 做了或沒做什麼：「{hit}」", original, hit)

    hit = _first_hit(t, _CLARIFY)
    if hit:
        return OwnerMessage("CLARIFICATION",
                            f"在補充或改寫自己的說法：「{hit}」", original, hit)

    hit = _first_hit(t, _MIND_CHANGE)
    if hit:
        return OwnerMessage("MIND_CHANGE",
                            f"方向變了而且沒有指向 AI 的失誤：「{hit}」", original, hit)

    m = _IMPERATIVE.search(t)
    if m:
        if _QUESTION.search(t):
            return OwnerMessage("CLARIFICATION",
                                "是問句，偏向釐清而不是指派新工作", original, m.group(0))
        return OwnerMessage("NEW_REQUEST",
                            f"祈使或要求的形狀：「{m.group(0)}」", original, m.group(0))

    if _QUESTION.search(t):
        return OwnerMessage("CLARIFICATION", "問句", original)

    # 結構規則分不出來。**不猜。**
    return OwnerMessage(
        "UNKNOWN",
        "沒有命中任何一條結構規則。分不出來比猜錯好 —— "
        "猜錯會把她行使擁有者的權力記成 AI 的失誤，或者相反", original)


# ---------------------------------------------------------------------------
# 接到 Event Ledger 與北極星鏈（build-plan.md:360）
# ---------------------------------------------------------------------------

# 五類對到 canonical event type。
#
# **三個是 v5.0 §6.2 的，一個是本專案加的，一個刻意不記。**
#
#   NEW_REQUEST / CLARIFICATION → USER_INSTRUCTION
#       澄清也算指令：她在講同一件事，而那件事仍然是要 AI 做的。
#   CORRECTION → CORRECTION
#       §6.2 的 Cognitive 類本來就有這個。
#   MIND_CHANGE → OWNER_GOAL_CHANGE
#       §6.2 沒有對應的。最接近的 DECISION_PROPOSAL 是「提案」，
#       而 owner 改變方向不是提案是決定。出處是 build-plan.md:360。
#   ACKNOWLEDGEMENT → 不記
#       「好」「繼續」不是一個發生的事，記它只會讓帳本充滿雜訊，
#       而雜訊會讓真的訊號變得不顯眼。
#   UNKNOWN → 不記
#       記一個分不出類型的事件，等於在帳本裡放一筆沒有意義的資料。
EVENT_TYPE = {
    "NEW_REQUEST": "USER_INSTRUCTION",
    "CLARIFICATION": "USER_INSTRUCTION",
    "CORRECTION": "CORRECTION",
    "MIND_CHANGE": "OWNER_GOAL_CHANGE",
    "ACKNOWLEDGEMENT": None,
    "UNKNOWN": None,
}


def to_event(msg: OwnerMessage, *, session_id: str = "",
             timestamp: float | None = None) -> tuple | None:
    """把一則分類結果轉成 (RawEvent, NormalizedEvent)。不該記的回 None。

    延遲 import event_ledger，避免兩個模組互相依賴。
    """
    etype = EVENT_TYPE.get(msg.kind)
    if etype is None:
        return None
    import importlib
    import sys as _sys
    import time as _time
    from pathlib import Path as _Path
    try:
        el = importlib.import_module("event_ledger")
    except ImportError:
        _sys.path.insert(0, str(_Path(__file__).resolve().parent))
        el = importlib.import_module("event_ledger")

    ts = timestamp if timestamp is not None else _time.time()
    raw = el.RawEvent(provider="owner", provider_event_type="message",
                      timestamp=ts,
                      payload={"text": msg.text, "kind": msg.kind,
                               "matched": msg.matched})
    norm = el.NormalizedEvent(
        raw_event_id=raw.id, type=etype, session_id=session_id,
        action=msg.kind, subject=msg.matched or "",
        result=msg.why[:120], provenance="OBSERVED",
        metadata={"owner_kind": msg.kind})
    return raw, norm


# ---------------------------------------------------------------------------
# 落差：她改了幾次方向，北極星換了幾版
# ---------------------------------------------------------------------------

def goal_change_gap(goal_change_events: int, north_star_versions: int) -> dict:
    """她改變方向的次數，對北極星實際換版的次數。

    **這個函式刻意不自動換北極星，它只把落差算出來。**

    理由有兩層。

    表層：不是每個 MIND_CHANGE 都該換北極星。「不用跑測試了」是改變
    想法，但它改的是一個步驟不是專案方向。分辨這兩者需要判斷，
    而判斷正是這一整套東西不做的事。

    深層：換北極星是權威行為。`northstar.Chain.adopt()` 強制要求
    具名的 authority，就是為了讓「誰決定的」永遠答得出來。
    一個自動換版的北極星，authority 會變成「系統」——
    那個欄位就失去意義了。

    **所以這裡產生的是一個問題不是一個動作：** 有 N 次方向改變而
    北極星還是第 1 版，那正常嗎。答案可能是正常的（那些都是小調整），
    也可能不是（北極星早就該更新了，而偏離判定一直在拿舊的警告她）。
    系統問得出來就夠了。
    """
    gap = goal_change_events - max(north_star_versions - 1, 0)
    if goal_change_events == 0:
        note = "沒有偵測到方向改變"
    elif gap <= 0:
        note = "北極星換版的次數跟得上方向改變的次數"
    else:
        note = (f"偵測到 {goal_change_events} 次方向改變，"
                f"而北極星只換過 {max(north_star_versions - 1, 0)} 次。"
                "差的那幾次可能是小調整不該換版，也可能是北極星該更新了 —— "
                "在有人確認之前，任何偏離判定都應該先問一句"
                "「我拿的是不是舊的那一版」")
    return {
        "goal_changes": goal_change_events,
        "north_star_bumps": max(north_star_versions - 1, 0),
        "gap": gap,
        "needs_review": gap > 0,
        "note": note,
    }

# ---------------------------------------------------------------------------
# 從 transcript 撈出真的是她講的話
# ---------------------------------------------------------------------------

# 長得像 owner 訊息但不是的東西。逐條取自
# `tools/find-owner-signals.mjs` 的 NOT_OWNER，那份清單是實測出來的：
# 2026-09-09 掃 800 個 session 發現，Codex 的 user_message 有 33.6%
# 是它自己塞回去的歷史，而那批東西讓 REWORK_DEMANDED 的統計虛胖 5.4 倍。
#
# **不過濾的話，這個模組會把系統注入的文字當成她說的話。**
NOT_OWNER = tuple(re.compile(p) for p in (
    r"The following is the Codex agent history",
    r"<heartbeat>",
    r"^Approach this as the design lead",
    r"^# /loop —",
    r"^# Workflow authoring reference",
    r"^# Schedule Cloud Agents",
    r"^# In app browser:",
    r"Another Claude session sent a message",
    r"<cross-session-message",
    r"^=== 共享內容 ===",
    r"以下是其他視窗",
    r"This session is being continued from a previous conversation",
    r"^Caveat: The messages below",
    r"系統提醒|system-reminder",
    r"\[SYSTEM NOTIFICATION",
    r"<task-notification>",
    r"^Contents of /",
))


def is_owner_text(text: str) -> bool:
    t = text or ""
    return bool(t.strip()) and not any(p.search(t) for p in NOT_OWNER)


def from_transcript(path) -> list[tuple[int, str]]:
    """從一份 jsonl 撈出 owner 真的講過的話。回傳 (行號, 文字)。

    只看 `type == "user"` 而且 content 是純文字的。
    tool_result 那種 content 是 list of dict 的不算 —— 那是工具回傳，
    不是她說的話。
    """
    import json as _json
    out: list[tuple[int, str]] = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                d = _json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "user":
                continue
            c = (d.get("message") or {}).get("content")
            if isinstance(c, str):
                text = c
            elif isinstance(c, list):
                parts = [b.get("text", "") for b in c
                         if isinstance(b, dict) and b.get("type") == "text"]
                text = "\n".join(x for x in parts if x)
            else:
                continue
            if is_owner_text(text):
                out.append((i, text))
    return out


# ---------------------------------------------------------------------------
# 她的沉默（build-plan.md:363）
# ---------------------------------------------------------------------------

# 一段 AI 輸出之後，她做了什麼。
#
# **第三態 MOVED_ON 是這一整塊的理由。**
#
# 沉默有兩種完全不同的意思：她看過了覺得沒問題（默許），
# 或者她根本沒看到。兩者在 transcript 裡長得一模一樣 ——
# 都是「她沒有針對那段說話」。
#
# 把它們合成一類的代價是不對稱的：一個她漏看的錯誤會被記成她同意過，
# 而「owner 同意過」在這個系統裡是最強的證據等級（E4 的 owner-confirmed）。
# 用沉默去餵那一級，等於讓系統自己發明權威。
SILENCE = ("EXPLICIT_OK", "RESPONDED", "MOVED_ON", "UNOBSERVED")

SILENCE_MEANING = {
    "EXPLICIT_OK": "她明確說了好、對、繼續。那是默許，而且說得出口",
    "RESPONDED": "她針對內容說了話（糾正、澄清、改變方向）。不是沉默",
    "MOVED_ON": "她沒有回應內容，直接講下一件事。**可能是默許，"
                "也可能是沒看到 —— 這兩者分不出來，所以不准當成同意**",
    "UNOBSERVED": "後面沒有她的訊息了。可能還沒看到，可能 session 結束了",
}


@dataclass(frozen=True)
class Silence:
    """一段 AI 輸出，與她接下來的反應。"""

    kind: str
    ai_line: int
    owner_line: int | None
    owner_kind: str | None
    ai_excerpt: str = ""
    flagged: bool = False

    def __post_init__(self):
        if self.kind not in SILENCE:
            raise ValueError(f"不是合法的沉默類型：{self.kind}")

    @property
    def risky(self) -> bool:
        """這一段沉默值不值得拿出來問。

        `flagged` 是呼叫端給的：那一段 AI 輸出裡有沒有未解的東西
        （驗不過的宣稱、標成 UNKNOWN 的判定、明說做不到的事）。

        **被標記過而她只是 MOVED_ON，那是最值得問的組合** ——
        因為那正是「她可能沒看到」與「那裡真的有問題」重疊的地方。
        """
        return self.flagged and self.kind in ("MOVED_ON", "UNOBSERVED")


def silence_map(transcript_path, flagged_lines: set[int] | None = None
                ) -> list[Silence]:
    """走一遍 transcript，把每一段 AI 輸出配上她接下來的反應。

    `flagged_lines` 是那些「裡面有未解的東西」的 AI 行號，由呼叫端給。
    這個函式自己不判斷內容有沒有問題 —— 那是 claims 與 overclaim 的事，
    混進來會讓這個模組同時在做兩件事。
    """
    import json as _json
    flagged = flagged_lines or set()
    ai_turns: list[tuple[int, str]] = []
    owner_turns: list[tuple[int, str]] = []

    with open(transcript_path, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            try:
                d = _json.loads(line)
            except ValueError:
                continue
            t = d.get("type")
            c = (d.get("message") or {}).get("content")
            if t == "assistant" and isinstance(c, list):
                text = "\n".join(b.get("text", "") for b in c
                                 if isinstance(b, dict) and b.get("type") == "text")
                if text.strip():
                    ai_turns.append((i, text))
            elif t == "user":
                if isinstance(c, str):
                    text = c
                elif isinstance(c, list):
                    text = "\n".join(b.get("text", "") for b in c
                                     if isinstance(b, dict) and b.get("type") == "text")
                else:
                    continue
                if is_owner_text(text):
                    owner_turns.append((i, text))

    # 以「輪」為單位，不是以每一個 text block。
    #
    # 2026-09-11 實測：一份 transcript 有 713 段 AI 文字但只有 105 則
    # owner 訊息，因為一輪回應會有很多塊（工具之間的說明、最後的報告）。
    # 逐塊配對的話 MOVED_ON 會是 89%，而那個數字量的是「一輪有幾塊」，
    # 不是「她跳過了多少」。
    #
    # 一輪 = 兩則 owner 訊息之間的所有 AI 輸出。代表那一輪的是**最後一塊**，
    # 因為那通常是報告，也是她最可能讀的那一段。
    rounds: list[tuple[int, str]] = []
    bounds = [ln for ln, _ in owner_turns]
    cur: tuple[int, str] | None = None
    bi = 0
    for ai_line, ai_text in ai_turns:
        while bi < len(bounds) and bounds[bi] < ai_line:
            if cur is not None:
                rounds.append(cur)
                cur = None
            bi += 1
        cur = (ai_line, ai_text)
    if cur is not None:
        rounds.append(cur)

    out: list[Silence] = []
    for ai_line, ai_text in rounds:
        nxt = next(((ln, tx) for ln, tx in owner_turns if ln > ai_line), None)
        if nxt is None:
            out.append(Silence("UNOBSERVED", ai_line, None, None,
                               ai_text[:80], ai_line in flagged))
            continue
        owner_line, owner_text = nxt
        k = classify(owner_text).kind
        if k == "ACKNOWLEDGEMENT":
            kind = "EXPLICIT_OK"
        elif k in ("CORRECTION", "CLARIFICATION", "MIND_CHANGE"):
            kind = "RESPONDED"
        else:
            # NEW_REQUEST 或 UNKNOWN：她講了別的事。
            # **不當成同意。** 見 SILENCE 的註解。
            kind = "MOVED_ON"
        out.append(Silence(kind, ai_line, owner_line, k,
                           ai_text[:80], ai_line in flagged))
    return out


def silence_summary(items: list[Silence]) -> dict:
    """統計，而且刻意把 MOVED_ON 單獨列出來。

    把它併進「沒有異議」那一欄的話，這個模組就白做了。
    """
    tally: dict[str, int] = {}
    for s in items:
        tally[s.kind] = tally.get(s.kind, 0) + 1
    risky = [s for s in items if s.risky]

    # **這個數字要跟結果一起端出來,不准藏。**
    #
    # 2026-09-11 全量跑 30 個 session:MOVED_ON 有 2,638 輪,
    # 其中 2,241 輪(85%)底下的 owner_kind 是 UNKNOWN。
    #
    # 也就是說,這張沉默地圖現在主要在量的是「分類器分不出她在說什麼」,
    # 不是「她跳過了那一段」。方向是保守的(UNKNOWN 永遠不會變成
    # EXPLICIT_OK,所以不會製造假的同意),但它會讓 risky 清單充滿噪音,
    # 而 risky 正是這一層要給人看的東西。
    #
    # 把它算成一個欄位而不是寫在註解裡,是因為看結果的人需要知道
    # 手上這個數字有多少是系統的無知。一個不講自己不確定度的指標,
    # 比沒有指標更危險。
    moved = [s for s in items if s.kind == "MOVED_ON"]
    from_unknown = sum(1 for s in moved if s.owner_kind == "UNKNOWN")
    share = (from_unknown / len(moved)) if moved else 0.0

    return {
        "total": len(items),
        "by_kind": tally,
        "risky": len(risky),
        "risky_lines": [s.ai_line for s in risky][:20],
        "moved_on_from_unknown": from_unknown,
        "moved_on_unknown_share": round(share, 3),
        "note": ("MOVED_ON 不等於同意。它的意思是「她沒有針對那段說話」，"
                 "而那可能是看過覺得沒問題，也可能是根本沒看到。"
                 "要當成同意只有一條路：她自己說出口（EXPLICIT_OK）"),
        "caveat": (f"MOVED_ON 裡有 {round(share * 100)}% 底下是分類器的 UNKNOWN。"
                   "那部分量的是「分不出她在說什麼」而不是「她跳過了」。"
                   "分子含這種噪音的時候，risky 清單要當線索看不是當結論"),
    }
