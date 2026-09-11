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

零依賴（ADR-009）。
"""

from __future__ import annotations

import re
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
    re.compile(r"重來|重做|再做一次|退回|改回去"),
    re.compile(r"你(?:又|還|怎麼).{0,6}(?:錯|沒|漏|忘)"),
    re.compile(r"不是這樣|搞錯|弄錯|寫錯|做錯"),
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
    re.compile(r"改成|換成|改用|改去|改做"),
    re.compile(r"我改變(?:主意|想法)|我想想|重新想|換個方向|換個做法"),
    re.compile(r"先做|先處理|優先|順序.{0,4}(?:換|改)"),
)

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
    t = (text or "").strip()
    if not t:
        return OwnerMessage("UNKNOWN", "空訊息", t)

    if len(t) <= ACK_MAX_CHARS and _ACK.match(t):
        return OwnerMessage("ACKNOWLEDGEMENT",
                            f"短（{len(t)} 字）而且整句都是正面回應", t, t)

    hit = _first_hit(t, _CORRECTION)
    if hit:
        return OwnerMessage("CORRECTION",
                            f"指向 AI 做了或沒做什麼：「{hit}」", t, hit)

    hit = _first_hit(t, _CLARIFY)
    if hit:
        return OwnerMessage("CLARIFICATION",
                            f"在補充或改寫自己的說法：「{hit}」", t, hit)

    hit = _first_hit(t, _MIND_CHANGE)
    if hit:
        return OwnerMessage("MIND_CHANGE",
                            f"方向變了而且沒有指向 AI 的失誤：「{hit}」", t, hit)

    m = _IMPERATIVE.search(t)
    if m:
        if _QUESTION.search(t):
            return OwnerMessage("CLARIFICATION",
                                "是問句，偏向釐清而不是指派新工作", t, m.group(0))
        return OwnerMessage("NEW_REQUEST",
                            f"祈使或要求的形狀：「{m.group(0)}」", t, m.group(0))

    if _QUESTION.search(t):
        return OwnerMessage("CLARIFICATION", "問句", t)

    # 結構規則分不出來。**不猜。**
    return OwnerMessage(
        "UNKNOWN",
        "沒有命中任何一條結構規則。分不出來比猜錯好 —— "
        "猜錯會把她行使擁有者的權力記成 AI 的失誤，或者相反", t)
