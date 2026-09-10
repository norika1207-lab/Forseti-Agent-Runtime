#!/usr/bin/env python3
"""Context 隔離、壓縮邊界與 Rehydration。實作 F08-CTX-001。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F08-CTX-001  sha256 b80b985fdfc0
    另參 Vol3 §4.1 的 RehydrationPacket schema

F08 §2 那句是整個模組的理由：

    A summary may lose why decisions were accepted, rejected alternatives,
    interaction contract, owner corrections, evidence strength and
    nuanced Goal evolution.

摘要會丟掉「為什麼」。結論留著、依據沒了，於是結論變成教條 —— 講得出來，
但不知道什麼時候不適用，也不知道遇到反例該推翻它。

所以 rehydration 不是把摘要塞回去，是回去拿原文。而且是有界的：
不是把八九十萬字倒回來，是照當前任務的依賴，只取需要的那幾段。

── 兩條硬規則 ────────────────────────────────────────

原文勝過摘要（§2、CT-F08-02）。衝突的時候不投票、不折衷、不「綜合
兩者」，原文直接贏。摘要是索引不是原件，這是 Vol1 第一條憲法。

每一段都要說得出為什麼被放進來（Vol3 §4.1 的 why_each_fragment_is_included）。
沒有這一欄的話，rehydration 會變成另一種塞：塞的是有關但不必要的東西，
而「有關」是一個永遠成立的理由。

零依賴。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

# ---------------------------------------------------------------------------
# F08 §5 的 Context Coverage（與 Vol2 §4 同一張表）
# ---------------------------------------------------------------------------

COVERAGE = ("NONE", "TITLE_ONLY", "HEADER_SCAN", "SAMPLED",
            "STRUCTURAL", "FULL_READ", "VERIFIED_UNDERSTANDING")

# 「我知道這份文件」但 coverage 只有 SAMPLED，不是完整理解（§5 原文）。
FULL_ENOUGH = ("FULL_READ", "VERIFIED_UNDERSTANDING")


def coverage_report(*, read_ranges: list[tuple[int, int]], total_lines: int,
                    challenged_ok: bool = False) -> dict:
    """coverage 加上「這是上界」這個標記。標記不可關閉。

    這個做法 2026-09-10 從隔壁 Moirai 的 `src/forseti/coverage.js` 學的。
    它的 SessionCoverage 每一筆都帶 `is_upper_bound = true`，沒有參數
    可以關掉，檔頭寫的理由是：

        session 內部的壓縮會讓它實際「記得」的比「讀過」的少，
        本模組無從得知。

    那句話對這個檔案一樣成立，而我原本沒有寫。`coverage_of()` 算的是
    read_ranges，也就是「讀過的範圍」；一個被壓縮過的 session 記得的
    比那個少，而從外面量不出來少了多少。

    這不是理論問題。2026-09-10 這一場對話本身就被壓縮過一次，
    而我在那之後說過「v5.0 §6 與 §20 我逐行讀過」—— 那句話是真的，
    但它是上界，不是「我現在還記得每一行」。

    刻意讓標記待在回傳值裡而不是只寫在註解：註解會被忽略，
    欄位會一路跟著資料走。
    """
    level = coverage_of(read_ranges=read_ranges, total_lines=total_lines,
                        challenged_ok=challenged_ok)
    covered = sum(max(0, b - a + 1) for a, b in read_ranges)
    return {
        "level": level,
        # 不可關閉。沒有任何參數能把它變成 False。
        "is_upper_bound": True,
        "why_upper_bound": "read_ranges 記的是讀過的範圍。被壓縮過的 session "
                           "記得的比讀過的少，那個差從外面量不出來",
        "lines_read": covered,
        "total_lines": total_lines,
        "challenged": bool(challenged_ok),
    }


def coverage_of(*, read_ranges: list[tuple[int, int]], total_lines: int,
                challenged_ok: bool = False) -> str:
    """從實際讀過的範圍算 coverage，不從宣稱算。

    這是整張表的重點:level 是量出來的不是報上來的。
    read_ranges 空的時候是 NONE,不管誰說他讀過。

    VERIFIED_UNDERSTANDING 需要 challenged_ok,也就是有人考過。
    自己說自己懂最多只能到 FULL_READ —— 這正是 level 5 與 6 的差別,
    也是 gate takeover 現在做不到 6 的原因(B-08)。

    【回傳的 level 是上界】要讓那個事實跟著資料走的話用
    `coverage_report()`,它的 is_upper_bound 關不掉。
    """
    if not read_ranges or total_lines <= 0:
        return "NONE"
    covered = sum(max(0, b - a + 1) for a, b in read_ranges)
    ratio = min(1.0, covered / total_lines)
    if ratio >= 0.98:
        return "VERIFIED_UNDERSTANDING" if challenged_ok else "FULL_READ"
    if ratio >= 0.6:
        return "STRUCTURAL"
    if ratio > 0.0:
        return "SAMPLED"
    return "NONE"


def is_full_understanding(level: str) -> bool:
    return level in FULL_ENOUGH


# ---------------------------------------------------------------------------
# 片段與衝突解決
# ---------------------------------------------------------------------------

ORIGINAL = "ORIGINAL"
SUMMARY = "SUMMARY"


@dataclass
class Fragment:
    """一段被放回去的內容。

    why 不是註解,是必填欄位。說不出為什麼要放這一段,就不該放。
    """

    text: str
    source: str            # ORIGINAL 或 SUMMARY
    provenance: str        # 從哪來:檔案:行號,或 jsonl 位置
    why: str

    def __post_init__(self):
        if not self.why.strip():
            raise ValueError("每一段都要說得出為什麼被放進來（Vol3 §4.1）")
        if self.source not in (ORIGINAL, SUMMARY):
            raise ValueError(f"source 只能是 {ORIGINAL} 或 {SUMMARY}")


def resolve(fragments: list[Fragment]) -> list[Fragment]:
    """原文勝過摘要。

    CT-F08-02:summary conflicts with original → original wins。
    判定「衝突」用同一個 provenance:同一個出處同時有原文與摘要時,
    摘要被丟掉。不折衷、不併陳 —— 併陳等於把矛盾轉嫁給讀的人,
    而讀的人正是那個已經沒有脈絡的。
    """
    originals = {f.provenance for f in fragments if f.source == ORIGINAL}
    return [f for f in fragments
            if f.source == ORIGINAL or f.provenance not in originals]


# ---------------------------------------------------------------------------
# RehydrationPacket（Vol3 §4.1、F08 §4）
# ---------------------------------------------------------------------------

# packet 的字元上限。有界是規格要求(CT-F08-01:bounded)。
# 這個數字是我定的,沒有實測依據 —— 合理的值應該從「Main 讀完之後
# 還剩多少判斷力」量出來,而那還沒有辦法量。
PACKET_LIMIT = 8000


@dataclass
class RehydrationPacket:
    current_goal: str
    current_task: str
    original_fragments: list[Fragment] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    unresolved_unknowns: list[str] = field(default_factory=list)
    provenance_refs: list[str] = field(default_factory=list)
    at: float = field(default_factory=time.time)
    dropped_for_budget: int = 0

    @property
    def size(self) -> int:
        return (len(self.current_goal) + len(self.current_task)
                + sum(len(f.text) + len(f.why) for f in self.original_fragments)
                + sum(len(x) for x in self.key_decisions + self.constraints
                      + self.unresolved_unknowns))

    def why_table(self) -> list[tuple[str, str]]:
        """每一段與它被放進來的理由。這張表是 packet 能不能被信任的依據。"""
        return [(f.provenance, f.why) for f in self.original_fragments]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["size"] = self.size
        return d


def build(*, goal: str, task: str, fragments: list[Fragment],
          decisions: list[str] | None = None, constraints: list[str] | None = None,
          unknowns: list[str] | None = None, limit: int = PACKET_LIMIT
          ) -> RehydrationPacket:
    """組一份有界的 packet。

    §4 的順序:current task → dependency graph → exact original fragments
    → owner corrections → decisions/evidence → healthy fragments → bounded packet。

    超出預算時砍片段,不砍 decisions、constraints、unknowns。
    理由是那三樣是結論性的、體積小、而且丟掉會讓 packet 失去骨架;
    片段是可以再查的,因為 provenance 還在。
    """
    p = RehydrationPacket(
        current_goal=goal, current_task=task,
        key_decisions=list(decisions or []),
        constraints=list(constraints or []),
        unresolved_unknowns=list(unknowns or []),
    )
    kept: list[Fragment] = []
    for f in resolve(fragments):
        p.original_fragments = kept + [f]
        if p.size > limit:
            p.original_fragments = kept
            p.dropped_for_budget += 1
            continue
        kept.append(f)
    p.original_fragments = kept
    p.provenance_refs = [f.provenance for f in kept]
    return p


# ---------------------------------------------------------------------------
# 壓縮邊界（F08 §3）
# ---------------------------------------------------------------------------

GOAL_RECALL_QUESTIONS = (
    "北極星是什麼？不是 scope 定義，是北極星。",
    "當前任務的 definition of done 有哪幾條？",
    "有哪些 constraint 是不准違反的？",
    "上一個被擁有者糾正的決定是什麼，糾正的理由是什麼？",
)


@dataclass
class CompressionBoundary:
    """壓縮是 first-class event（§3）。

    記下來的目的不是統計,是讓「壓縮之後」變成一個可以檢查的時刻。
    §3 要求比較壓縮前後的 Goal recall、constraints、current task、
    decision provenance 與 Context Coverage。
    """

    at: float
    pre_tokens: int
    post_tokens: int
    dropped_tokens: int
    task_state_before: str
    task_state_after: str

    @property
    def task_state_intact(self) -> bool:
        """CT-F08-04 的前半：壓縮不得改變任務狀態。

        會變的話代表任務真相跟著 context 走,那整個帳本就白做了。
        """
        return self.task_state_before == self.task_state_after

    def challenge(self) -> tuple[str, ...]:
        """CT-F08-04 的後半：壓縮之後要考 Goal recall。

        不是問「你還記得嗎」——那個問題的答案永遠是「記得」。
        是問具體的內容,答不出來就是不記得。
        """
        return GOAL_RECALL_QUESTIONS
