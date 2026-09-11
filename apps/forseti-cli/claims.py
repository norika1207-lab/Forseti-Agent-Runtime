#!/usr/bin/env python3
"""Claim 與 Reality。階段 2 的核心。

規格來源：v5.0 §7（Reality Engine and Claim Lifecycle），主 session
2026-09-11 逐行讀過，只有 24 行。階段定義在 `docs/build-plan.md:332`。

────────────────────────────────────────────────────

## 這個模組不做什麼，比它做什麼重要

`docs/build-plan.md:350` 寫死了：

    不做語意判斷。抽取用結構規則（引號、路徑、數字、過去式動詞），
    抽不出來就標 UNEXTRACTABLE，不猜。

所以這裡沒有「理解句子」這種東西。它只認得住址、數字、以及一小張
過去式動詞表。一句話裡沒有可以被查核的具體物，它就標 UNEXTRACTABLE
然後走開 —— 那不是失敗，那是誠實。

**猜一個 claim 出來的代價，比漏掉一個高。** 漏掉的那個本來就沒有
具體物可驗，而猜出來的會帶著一個假的驗證狀態進入下游。

## 兩句規格原文，它們是機制不是描述

§7.1：

    A claim never becomes canonical merely because multiple agents
    repeat it. Repetition increases social consensus, not evidence strength.

所以這個模組的 `promote()` 不看有幾個人說過。說一百次的 E0 還是 E0。
`repeat()` 會把次數記下來，但它動不到 strength —— 那是刻意的，
把「記錄重複」與「強度」放在兩個改不到彼此的地方。

§7.3：

    Actions that create claims must declare how those claims can be verified.

宣稱要自己聲明怎麼驗。不聲明的話它永遠停在 EVIDENCE_REQUIRED，
不會變成 UNKNOWN —— 那兩個不一樣：UNKNOWN 是「驗過了但答不出來」，
沒有契約是「根本還沒開始驗」。

## E0-E4 跟 evidence.js 的四級是兩個軸，別混

| | 量什麼 | 值 |
|---|---|---|
| 本模組的 E0-E4（v5.0 §7.2） | 強度 | E0 模型自述 → E4 owner 確認 |
| `src/evidence.js` 四級 | 來源類型 | OBSERVED / DECLARED / INFERRED / MISSING |

一份 DECLARED 的證據強度是 E0，一份 OBSERVED 的可以是 E2 或 E3，
取決於是不是新鮮的確定性檢查、有沒有獨立佐證。**兩個軸垂直，
不是同一張表的兩種寫法。** 這條寫在這裡是因為 `docs/glossary.md`
已經有一條在講證據分級四套並存，不要再加第五套。

零依賴（ADR-009）。
"""

from __future__ import annotations

import hashlib
import importlib
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path


def _event_ledger_mod():
    """延遲載入 event_ledger,避免兩個模組互相 import。"""
    try:
        return importlib.import_module("event_ledger")
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        return importlib.import_module("event_ledger")

# ---------------------------------------------------------------------------
# v5.0 §7.1 的生命週期
# ---------------------------------------------------------------------------

STATES = ("PROPOSED", "EVIDENCE_REQUIRED", "VERIFIED", "REFUTED",
          "UNKNOWN", "CANONICAL")

# 規格的圖：
#     PROPOSED → EVIDENCE_REQUIRED → VERIFIED / REFUTED / UNKNOWN
#                              ↓
#                      CANONICAL (only by authority/policy)
#
# CANONICAL 的入口刻意只有一條，而且不在這張表裡由狀態決定 ——
# 見 promote()。表裡不放是為了讓「誰能升級」這個問題沒辦法靠
# 改一個狀態轉移表來繞過。
ALLOWED: dict[str, tuple[str, ...]] = {
    "PROPOSED": ("EVIDENCE_REQUIRED",),
    "EVIDENCE_REQUIRED": ("VERIFIED", "REFUTED", "UNKNOWN"),
    # 驗過的可以被新證據推翻。REFUTED 也可以回去重驗 ——
    # 一個被判失敗的宣稱，後來拿到證據應該能翻案，
    # 不然這張表就變成單向的定罪。
    "VERIFIED": ("REFUTED", "UNKNOWN"),
    "REFUTED": ("EVIDENCE_REQUIRED",),
    "UNKNOWN": ("EVIDENCE_REQUIRED", "VERIFIED", "REFUTED"),
    "CANONICAL": (),
}

# ---------------------------------------------------------------------------
# v5.0 §7.2 的證據強度
# ---------------------------------------------------------------------------

STRENGTH = ("E0", "E1", "E2", "E3", "E4")

STRENGTH_MEANING = {
    "E0": "模型自述，沒有支持。非權威",
    "E1": "工具輸出、未驗證的路徑、快取狀態。弱",
    "E2": "新鮮的確定性檢查：stat / hash / git diff / API GET / process state。強",
    "E3": "多個確定性來源獨立佐證。很強",
    "E4": "owner 確認、簽署的政策、外部的真實系統。canonical 候選",
}

# 只有 E4 夠格被提名為 canonical（§7.2 最後一欄）。
CANONICAL_CANDIDATE = "E4"


class ClaimError(Exception):
    """宣稱不合規格。拒絕而不是修正。"""


# ---------------------------------------------------------------------------
# 抽取：只認結構，不讀語意
# ---------------------------------------------------------------------------

# 過去式動詞表。**這張表刻意很短。**
#
# 它是這個模組唯一需要字串比對的地方，而字串比對的判斷力有上限
# （B-05 記過：字串比對訊號不能單獨判斷，可以當觸發器）。
# 所以它只當觸發器：命中之後還是要找到具體物，找不到就 UNEXTRACTABLE。
#
# 每加一個詞都要有實際遇到的句子當出處，不然這張表會長成一個
# 沒有人知道邊界在哪的語意判斷器。
PAST_TENSE = (
    "建立了", "改好了", "改完了", "寫好了", "寫完了", "修好了", "加上了",
    "跑過了", "跑完了", "驗過了", "測過了", "確認了", "刪掉了", "部署了",
    "created", "updated", "fixed", "added", "removed", "deployed",
    "verified", "tested", "ran", "wrote",
)

# 路徑：至少一個斜線或一個副檔名，而且不是句子裡的一般文字。
#
# 開頭的 `/` 要吃進來。2026-09-11 拿真實 transcript 跑才發現漏了：
# 「/Users/norikaoda」被抽成「Users/norikaoda」，相對於 repo 當然找不到，
# 然後被判 REFUTED。一個真的存在的目錄被判成假的，只因為少吃一個字元。
_PATH = re.compile(r"\$?/?(?:[$\w.~-]+/)+[\w.-]+|\b[\w-]+\.(?:py|js|mjs|ts|md|json|"
                   r"jsonl|html|css|txt|yml|yaml|toml|sh|db|sql)\b")
# 數字：整數、小數、百分比、含千分位。
_NUMBER = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?%?\b")
# 通過與否。
_PASSFAIL = re.compile(r"\b(?:pass(?:ed|ing)?|fail(?:ed|ing)?|ok|error|"
                       r"exit\s*code\s*\d+)\b|通過|沒過|失敗|成功", re.I)

KINDS = ("file", "number", "passfail", "unextractable")


def extract(text: str) -> list[dict]:
    """從一段文字抽出可驗證的宣稱。抽不出來回 UNEXTRACTABLE。

    順序刻意是路徑 → 通過與否 → 數字。一句「tests/a.py 通過」
    裡的具體物是那個檔案，數字是附屬的；反過來的話會抽出一個
    只有數字的 claim，而數字單獨存在幾乎驗不了。

    **沒有過去式動詞就不抽。** 「我要去改 a.py」不是宣稱，是意圖，
    把它當成宣稱去驗會永遠判 REFUTED。這一條是 `tools/classify-turns.mjs`
    的 INTENT 類踩出來的，它的判準排在所有規則最前面。
    """
    if not text or not text.strip():
        return []
    low = text.lower()
    if not any(v in text or v in low for v in PAST_TENSE):
        return []

    out: list[dict] = []
    for m in _PATH.finditer(text):
        out.append({"kind": "file", "subject": m.group(0), "span": m.span()})
    if not out:
        for m in _PASSFAIL.finditer(text):
            out.append({"kind": "passfail", "subject": m.group(0), "span": m.span()})
    if not out:
        for m in _NUMBER.finditer(text):
            out.append({"kind": "number", "subject": m.group(0), "span": m.span()})
    if not out:
        # 有過去式動詞但沒有任何具體物。**這不是失敗，是誠實。**
        # 猜一個出來的代價比漏掉高：漏掉的本來就沒東西可驗，
        # 猜出來的會帶著一個假的驗證狀態進入下游。
        return [{"kind": "unextractable", "subject": "",
                 "why": "有過去式動詞但找不到可查核的具體物（路徑、通過與否、數字）"}]
    return out


# ---------------------------------------------------------------------------
# §7.3 的驗證契約
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Contract:
    """一個宣稱怎麼驗。**建立 claim 的動作必須聲明這個（§7.3）。**

    frozen 是因為契約在宣稱成立的那一刻就固定了。事後改契約等於
    搬球門 —— 而那正是 2026-09-10 部署那次我自己做過的事
    （改了 s3 的 verifier），當時留了痕跡，這裡直接讓它做不到。
    """

    kind: str
    checks: tuple[str, ...]

    def __post_init__(self):
        if not self.checks:
            raise ClaimError("契約不能是空的。沒有 checks 的契約等於沒有契約，"
                             "而那會讓宣稱看起來已經有驗證方式了")


# 「created file X」要 path existence + non-zero size + optional hash（§7.3 原文）。
#
# non-zero size 那一條是 CT-001 的來源：0 bytes 的檔案不得判 VERIFIED。
# 那不是吹毛求疵 —— 一個建立了但沒寫東西的檔案，跟沒建立的差別，
# 對使用者來說是零。
FILE_CREATED = Contract("file", ("path_exists", "size_gt_zero", "hash_recorded"))
PASSFAIL_CLAIMED = Contract("passfail", ("exit_code_recorded",))
NUMBER_CLAIMED = Contract("number", ("source_command_recorded", "output_recorded"))

DEFAULT_CONTRACTS = {
    "file": FILE_CREATED,
    "passfail": PASSFAIL_CLAIMED,
    "number": NUMBER_CLAIMED,
}


# ---------------------------------------------------------------------------
# Claim
# ---------------------------------------------------------------------------

@dataclass
class Claim:
    """一個可以被查核的宣稱。

    `repeats` 跟 `strength` 是兩個欄位，而且沒有任何一條程式碼把前者
    餵給後者。那是 §7.1 那句話的機制形式：

        Repetition increases social consensus, not evidence strength.

    分成兩個欄位而不是「不記錄重複」，是因為重複本身有資訊 ——
    它告訴你這件事被講過幾次、被幾個人講過。那是社會事實，
    跟它是不是真的無關，所以它可以被記錄但不能被計入。
    """

    text: str
    kind: str
    subject: str
    state: str = "PROPOSED"
    strength: str = "E0"
    contract: Contract | None = None
    evidence_refs: list[str] = field(default_factory=list)
    repeats: int = 0
    said_by: list[str] = field(default_factory=list)
    at: float = field(default_factory=time.time)
    why_state: str = "剛抽出來，還沒要求證據"

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ClaimError(f"不是合法的 kind：{self.kind}")
        if self.state not in STATES:
            raise ClaimError(f"不是合法的 state：{self.state}")
        if self.strength not in STRENGTH:
            raise ClaimError(f"不是合法的強度：{self.strength}。"
                             f"合法的是 {'/'.join(STRENGTH)}（v5.0 §7.2）")
        if self.contract is None and self.kind in DEFAULT_CONTRACTS:
            self.contract = DEFAULT_CONTRACTS[self.kind]

    # -- 生命週期 ---------------------------------------------------------

    def to(self, state: str, why: str) -> None:
        """換狀態。每一次都要有理由，理由空白跟狀態不合法是同一類錯誤。"""
        if state not in STATES:
            raise ClaimError(f"不是合法的 state：{state}")
        if state == "CANONICAL":
            raise ClaimError("CANONICAL 不能用 to() 進去，只能用 promote()。"
                             "那是 §7.1『only by authority/policy』的入口")
        if state not in ALLOWED.get(self.state, ()):
            raise ClaimError(f"不允許的轉換：{self.state} → {state}")
        if not why.strip():
            raise ClaimError("換狀態要有理由")
        self.state = state
        self.why_state = why

    def require_evidence(self) -> None:
        """進入等證據的狀態。

        沒有契約的話拒絕前進。那不是刁難：沒有契約就不知道要拿什麼
        當證據，而在那種狀態下判 UNKNOWN 會騙人 —— UNKNOWN 的意思是
        「驗過了但答不出來」，不是「根本沒開始驗」。
        """
        if self.contract is None:
            raise ClaimError(
                f"這個宣稱沒有驗證契約（§7.3）。kind={self.kind} 沒有預設契約，"
                "要自己給一個。不給的話它會停在 PROPOSED，而那是對的 —— "
                "一個不知道怎麼驗的宣稱，不該看起來像是在等證據")
        self.to("EVIDENCE_REQUIRED", f"契約已定：{'、'.join(self.contract.checks)}")

    def repeat(self, by: str = "") -> None:
        """有人又說了一次。

        **這個方法碰不到 strength，那是刻意的。** 它跟 strength 之間
        沒有任何一條路徑，所以「說很多次就變強」這件事不是靠紀律避免的，
        是靠沒有那個入口。
        """
        self.repeats += 1
        if by and by not in self.said_by:
            self.said_by.append(by)

    def promote(self, *, authority: str, policy_ref: str) -> None:
        """升成 CANONICAL。§7.1 的唯一入口。

        三個條件缺一不可：要有具名的 authority、要有政策依據、
        而且強度必須是 E4。前兩個是「誰說的、憑什麼」，第三個是
        §7.2 那張表 —— 只有 E4 被列為 canonical candidate。

        重複次數在這裡完全沒有出現，那是這個方法最重要的地方。
        """
        if not authority.strip():
            raise ClaimError("CANONICAL 必須有具名的 authority（§7.1）")
        if not policy_ref.strip():
            raise ClaimError("CANONICAL 必須有政策依據。沒有依據的權威"
                             "就只是另一個說話大聲的人")
        if self.strength != CANONICAL_CANDIDATE:
            raise ClaimError(
                f"強度是 {self.strength}，只有 {CANONICAL_CANDIDATE} 夠格"
                f"（§7.2）。被重複了 {self.repeats} 次不影響這一條 —— "
                "repetition increases social consensus, not evidence strength")
        self.state = "CANONICAL"
        self.why_state = f"{authority} 依 {policy_ref} 認定"

    def raise_strength(self, level: str, why: str) -> None:
        """升強度。只能升不能降著用，而且要說出憑據。

        降強度要用 lower_strength()，分開兩個方法是為了讓「降級」
        在程式碼裡看得見 —— 一個宣稱的證據變弱了是大事，
        不該跟升級用同一個呼叫。
        """
        if level not in STRENGTH:
            raise ClaimError(f"不是合法的強度：{level}")
        if STRENGTH.index(level) < STRENGTH.index(self.strength):
            raise ClaimError(f"{self.strength} → {level} 是降級，用 lower_strength()")
        if not why.strip():
            raise ClaimError("升強度要說出憑據")
        self.strength = level
        self.evidence_refs.append(why)

    def lower_strength(self, level: str, why: str) -> None:
        if level not in STRENGTH:
            raise ClaimError(f"不是合法的強度：{level}")
        if not why.strip():
            raise ClaimError("降強度要說出理由")
        self.strength = level
        self.evidence_refs.append(f"降級：{why}")


# ---------------------------------------------------------------------------
# Reality：真的去看
# ---------------------------------------------------------------------------


# 不要走進去找的目錄。走進去的成本高,而且找到的東西多半不是宣稱在講的。
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".forseti", "docs/sources"}


# 裸檔名的搜尋結果快取。
#
# **快取的是「哪個路徑」不是「存不存在」。** 那個區別重要:
# 路徑解析在一次執行裡是穩定的(同一個 root 找同一個名字),
# 而檔案存不存在隨時會變 —— 把後者快取起來會讓驗證器看到過期的現實。
#
# 沒有這個快取的話,批次跑幾千個宣稱會讓每一個都重掃一次目錄樹,
# 2026-09-11 實測跑超過十分鐘沒跑完。
_RESOLVE_CACHE: dict[tuple[str, str], tuple] = {}


def _remember(key, path, why):
    _RESOLVE_CACHE[key] = (path, why)
    return path, why


# 走幾個目錄之後放棄。挑這個數字沒有理論依據,它只要滿足兩件事:
# 大到足以走完一個正常的專案目錄,小到不會讓人以為程式當掉了。
_WALK_BUDGET = 3000

# 全大寫、用斜線分隔的東西幾乎都是列舉不是路徑。
# 2026-09-11 實測抓到:「OBSERVED/DECLARED/INFERRED/MISSING」與
# 「VERIFIED/REFUTED/UNKNOWN」都被路徑正則抓成路徑,然後判 REFUTED。
# 真實路徑極少每一段都全大寫,所以這條規則不太會誤殺。
_ENUM_LIKE = re.compile(r"^[A-Z][A-Z_0-9]*(?:/[A-Z][A-Z_0-9]*)+$")


def looks_like_enumeration(subject: str) -> bool:
    return bool(_ENUM_LIKE.match(subject))


def resolve_subject(subject: str, cwd: Path | None = None) -> tuple[Path | None, str]:
    """把宣稱裡的 subject 對到磁碟上的一個路徑。

    回傳 (路徑, 說明)。對不到回 (None, 為什麼對不到)。

    **這個函式存在的理由是 2026-09-11 的第二次誤判。** 出口條件跑真實
    transcript 的時候,「ledger.py」「PHASE_STATUS.md」這種裸檔名
    全部被判 REFUTED —— 而它們都存在,只是我在文字裡寫的是簡稱不是路徑。

    有斜線的當路徑用。沒有斜線的是簡稱,要去找;找到剛好一個就用它,
    找到零個或多個都回 None。**多個的時候不猜**:兩個同名檔案裡挑一個去驗,
    驗出來的結果跟宣稱可能根本無關。
    """
    if looks_like_enumeration(subject):
        return None, f"「{subject}」看起來是用斜線分隔的列舉，不是路徑"
    if "/" in subject or subject.startswith("~"):
        try:
            p = Path(subject).expanduser()
        except (RuntimeError, OSError) as e:
            # `~someone/x` 展不開的時候 expanduser() 會丟 RuntimeError。
            # 2026-09-11 拿真實 transcript 跑的第一秒就撞到,而且它不是誤判,
            # 是整個 verify() 炸掉 —— 一個驗證器自己爆炸,比它判錯更嚴重,
            # 因為批次跑的時候後面的宣稱全部沒被驗到,而且沒人會知道。
            return None, f"「{subject}」的 ~ 展不開（{e}），沒辦法對到路徑"
        return ((cwd / p) if (cwd and not p.is_absolute()) else p), "路徑"

    root = cwd or Path.cwd()
    key = (str(root), subject)
    if key in _RESOLVE_CACHE:
        return _RESOLVE_CACHE[key]

    # 自己走目錄樹，不用 rglob。
    #
    # **2026-09-11 我在這裡連錯兩次，兩次都是同一個形狀：
    # 以為自己設了上限，其實沒有。**
    #
    # 第一次：`for f in root.rglob(subject)` 外面包一個計數器。
    # 但 rglob 吐出來的只有「匹配的項目」—— 一個不存在的檔名在家目錄底下
    # 會走完整棵樹然後吐出零個，計數器永遠是 0，上限永遠不會觸發。
    # 限制了產出，沒有限制工作量。
    #
    # 第二次：加快取。快取擋得住重複的 key，擋不住第一次那幾千個不同的 key。
    #
    # 真正要限制的是遍歷本身，所以這裡自己走。
    hits: list[Path] = []
    walked = 0
    try:
        stack = [root]
        while stack:
            d = stack.pop()
            walked += 1
            if walked > _WALK_BUDGET:
                return _remember(key, None,
                                 f"在 {root} 底下找「{subject}」走過 "
                                 f"{_WALK_BUDGET:,} 個目錄還沒定案，範圍太大，停手。"
                                 "這句話是關於我自己的，不是關於那個檔案")
            try:
                with os.scandir(d) as it:
                    for e in it:
                        name = e.name
                        if name.startswith(".") or name in _SKIP_DIRS:
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif name == subject:
                            hits.append(Path(e.path))
                            if len(hits) > 1:
                                stack.clear()
                                break
            except OSError:
                continue
    except OSError:
        return _remember(key, None, "搜尋失敗")

    if len(hits) == 1:
        return _remember(key, hits[0],
                         f"裸檔名，在搜尋範圍裡找到唯一一個：{hits[0]}")
    if not hits:
        return _remember(key, None,
                         f"裸檔名「{subject}」在搜尋範圍裡找不到，"
                         "但也不知道它本來指哪裡")
    return _remember(key, None, f"裸檔名「{subject}」對到多個檔案，不猜是哪一個")


def _disk(path: str, cwd: Path | None = None) -> dict:
    """現在的磁碟狀態。量不到回 existence='unknown'，不是 False。

    三態不是講究，是防冤枉：一個因為權限讀不到的檔案，
    如果被記成「不存在」，那個宣稱會被判 REFUTED，
    而事實可能是它好好地在那裡。
    """
    p = Path(path).expanduser()
    if not p.is_absolute() and cwd:
        p = cwd / p
    try:
        st = p.stat()
    except FileNotFoundError:
        # 真的不存在。這是一個確定的答案,不是「量不到」。
        return {"existence": False, "byteSize": None, "contentHash": None}
    except OSError:
        # 權限不足、路徑太長、檔案系統掛了。這些是「量不到」。
        #
        # 2026-09-11 我在修目錄誤判的時候把這兩種併成 unknown,
        # 於是一個真的不存在的檔案也變成 UNKNOWN —— 那正是我在那條
        # 測試的註解裡寫的「修誤判最容易犯的錯是把判準放寬到什麼都過」,
        # 寫完不到五分鐘自己犯了。分開靠例外型別,不靠判斷。
        return {"existence": "unknown", "byteSize": None, "contentHash": None}
    if p.is_dir():
        # 目錄存在就是存在。2026-09-11 實測抓到的誤判:原本這裡把
        # 「不是檔案」一律當成「不存在」,於是 docs/sources 與
        # ~/.forseti/ledgers 這兩個真的存在的目錄被判 REFUTED。
        #
        # **冤枉是最糟的一類錯**:一個被判成假的真宣稱,會讓人不信任
        # 整套判定,而那比漏掉幾個假宣稱傷得更重。
        #
        # 目錄沒有 size 的概念,所以 CT-001 那條(0 bytes 不得 VERIFIED)
        # 對它不適用 —— 那條規的是「建立了一個空檔案等於沒建立」,
        # 而一個空目錄是真的被建立了。
        return {"existence": True, "byteSize": None, "contentHash": None,
                "is_dir": True}
    if not p.is_file():
        # 不是檔案也不是目錄:socket、device、broken symlink。
        # 這種東西量得到它存在,但驗不了內容,所以不說它不存在。
        return {"existence": "unknown", "byteSize": None, "contentHash": None}
    try:
        data = p.read_bytes()
    except OSError:
        return {"existence": True, "byteSize": st.st_size, "contentHash": None}
    return {"existence": True, "byteSize": len(data),
            "contentHash": hashlib.sha256(data).hexdigest()[:16]}


# 佔位符。真實路徑不長這樣,而文件與說明裡到處都是。
# `tests/test_fXX.py`、`<name>.json`、`src/*.py` —— 拿這些去 stat
# 當然找不到,然後判一個人在說謊。
# `$HOME/x` 是 shell 變數,`.../x` 是省略。兩種都在真實 transcript 裡
# 大量出現(貼指令、貼路徑摘要),而它們都不是可以去 stat 的東西。
_PLACEHOLDER = re.compile(r"[*?<>{}$]|\.\.\.|([A-Z])\1{1,}|\bXX+\b|\bNNN?\b")

# 最後一段有沒有副檔名。**點後面至少要有一個字母。**
# 「74.7/21.5/3.8」的 `.8` 長得像副檔名但不是 —— 那是一組比例數字,
# 2026-09-11 真實語料抓到它被判 REFUTED。
# 「Midjourney...」點後面是空的,不算;「9/8」沒有點,不算。
_HAS_EXT = re.compile(r"\.(?=[A-Za-z0-9]{1,8}$)[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*$")


def can_refute(subject: str, resolved: Path, cwd: Path | None) -> tuple[bool, str]:
    """這個宣稱,驗證器有沒有資格判它假。

    ────────────────────────────────────────────────────

    **REFUTED 是這套系統唯一的定罪輸出。** 它說的是「你講了一件假的事」。

    2026-09-11 拿六個真實 session 跑出來:1,755 個宣稱裡 541 個 REFUTED,
    30.8%。逐條看原句,絕大多數是冤枉的 —— `Goal/Task` 是列舉不是路徑,
    `github.com/...` 是網址,`9/8` 是日期,`/api/tokens` 是別的專案的端點。

    一個被冤枉的 REFUTED,傷害比十個漏掉的假宣稱大得多。人只要被冤枉
    一次就不會再信任整套判定,而那正好殺死北極星(不讓使用者變成 QA)。

    所以門檻改成這一句:**只有在驗證器真的有能力驗、而且真的驗了、
    答案是否定的時候,才給 REFUTED。其餘一律 UNKNOWN。**

    三條都是結構規則,不讀語意(`docs/build-plan.md:350`)。回傳
    (可不可以定罪, 為什麼不行)。

    ## 這裡最容易犯的錯

    修誤判的時候最容易犯的錯是把判準放寬到什麼都過。我 2026-09-11
    在 `_disk()` 的註解裡寫過這句話,寫完不到五分鐘自己犯了一次
    (把「真的不存在」也併進 unknown)。

    這三條刻意都不碰 VERIFIED 那一側:一個存在的檔案還是照驗、
    CT-001 的 0 bytes 還是照判 REFUTED。動到的只有定罪這條路徑,
    所以放寬的範圍是有界的。
    """
    if _PLACEHOLDER.search(subject):
        return False, f"「{subject}」看起來是佔位符不是真的路徑"

    if not _HAS_EXT.search(subject):
        # 沒有副檔名的時候,我分不出「不存在的目錄」跟「用斜線分隔的列舉」。
        # 分不出來就不定罪 —— 這是 bible Q-07 的形式。
        #
        # 代價是誠實的:一個人宣稱建立了 src/newdir 而沒建立,會變成
        # UNKNOWN 不是 REFUTED。但 UNKNOWN 不是放過,它是「還沒驗」,
        # 下游仍然看得到它。
        return False, (f"「{subject}」沒有副檔名，分不出是目錄路徑還是"
                       "用斜線分隔的列舉，不猜")

    if cwd is not None:
        try:
            resolved.resolve().relative_to(Path(cwd).resolve())
        except (ValueError, OSError):
            # 落在 repo 外面。驗證器只看得到一個 repo,說它「不存在」
            # 是在講一件自己不知道的事。
            return False, f"「{subject}」不在這個 repo 底下，不在能驗的範圍內"

    return True, ""


def evidence_from_ledger(subject: str, led=None) -> dict | None:
    """從 Event Ledger 找這個檔案被寫的那一刻的證據。

    **這比現在去量磁碟更有價值，而且那個差是階段 1 存在的理由。**

    現在量到的是「此刻」的狀態。一個宣稱說「我建立了 a.py」，
    如果之後有人改了 a.py，現在量到的 hash 跟當時不同 ——
    那不代表宣稱是假的。帳本裡存的是 hook 在那一刻量到的，
    那才是對得上宣稱的證據。

    找不到回 None。找不到不是 REFUTED —— 只是這條路沒有證據，
    還有磁碟那條路可以走。
    """
    try:
        if led is None:
            el = _event_ledger_mod()
            led = el.EventLedger()
            close = True
        else:
            close = False
        try:
            hit = None
            for rec in led.read_all():
                n = rec.get("norm") or {}
                if n.get("type") != "FILE_WRITE":
                    continue
                subj = n.get("subject") or ""
                if subj == subject or subj.endswith("/" + subject.lstrip("./")):
                    ev = (n.get("metadata") or {}).get("evidence")
                    if ev:
                        hit = ev      # 取最後一筆:同一個檔案可能被寫很多次
            return hit
        finally:
            if close:
                led.close()
    except Exception:
        # 帳本讀不到不該讓驗證整個掛掉。少一條證據來源而已。
        return None


def verify(claim: Claim, *, cwd: Path | None = None, led=None) -> Claim:
    """對著現實驗一個宣稱。改變 claim 的狀態與強度。

    **CT-001：0 bytes 的檔案不得判 VERIFIED。**（`docs/build-plan.md:348`）

    那不是吹毛求疵。「我建立了設定檔」而檔案是空的，對使用者來說
    跟沒建立沒有差別 —— 而且更糟，因為它看起來像是做完了。

    證據優先序：帳本裡當時的 > 現在量磁碟。理由寫在
    evidence_from_ledger()。兩邊都有的話升 E3（獨立佐證，§7.2）。
    """
    if claim.state == "CANONICAL":
        raise ClaimError("CANONICAL 的宣稱不重驗。要推翻它要走 authority")
    if claim.state == "PROPOSED":
        claim.require_evidence()

    if claim.kind != "file":
        # 非檔案類的宣稱這一版不驗。標 UNKNOWN 而不是 REFUTED ——
        # 「我沒辦法驗」跟「我驗了而它是假的」是兩件完全不同的事，
        # 混在一起會把一堆沒問題的宣稱打成假的。
        claim.to("UNKNOWN", f"kind={claim.kind} 這一版還沒有驗證器，不是驗不過")
        return claim

    resolved, how = resolve_subject(claim.subject, cwd=cwd)

    if resolved is None:
        # 路徑對不到,但帳本可能知道。**先問帳本再放棄。**
        #
        # ────────────────────────────────────────────
        # 2026-09-11 準備開採集之前做 preflight 才發現的順序錯誤。
        #
        # 原本這裡直接回 UNKNOWN,連查都不查。那會讓整個採集白做:
        # hook 明明在 FILE_WRITE 事件裡記了絕對路徑與 hash,
        # 而驗證器因為自己 resolve 不出來就先走開了。
        #
        # **帳本比現場的路徑解析可靠** —— 它記的是 hook 在那一刻
        # 親眼量到的東西,不需要猜基準。所以它該是第一順位不是備案。
        # ────────────────────────────────────────────
        from_ledger = evidence_from_ledger(claim.subject, led=led)
        if from_ledger is None:
            # 對不到路徑就是對不到。判 REFUTED 會冤枉一個可能存在的檔案,
            # 而 UNKNOWN 誠實得多:我不知道它指哪裡,所以我沒有驗。
            claim.to("UNKNOWN", how)
            return claim
        size = from_ledger.get("byteSize")
        if from_ledger.get("existence") is not True:
            claim.to("UNKNOWN", f"{how}；帳本裡那一筆也沒有量到它存在")
            return claim
        if not size:
            claim.to("REFUTED",
                     f"{claim.subject} 在帳本裡是 0 bytes。建立了一個空檔案，"
                     "跟沒建立對使用者是一樣的")
            claim.raise_strength("E2", "帳本裡 hook 當時量到的：size = 0")
            return claim
        claim.to("VERIFIED",
                 f"{claim.subject} 對不到現在的路徑，但帳本記得寫入的那一刻："
                 f"{size:,} bytes")
        claim.raise_strength("E2", "帳本裡 hook 當時量到的證據")
        return claim

    from_ledger = evidence_from_ledger(claim.subject, led=led)
    now = _disk(str(resolved), cwd=cwd)
    ev = from_ledger or now

    if ev.get("existence") == "unknown":
        claim.to("UNKNOWN", f"量不到 {claim.subject}（權限或路徑），不是不存在")
        return claim
    if not ev.get("existence"):
        # 相對路徑，而且帳本裡沒有它的證據 —— **我不知道基準在哪裡。**
        #
        # ────────────────────────────────────────────
        # 2026-09-11 把四個模組接起來之後才看清楚的一件事。
        #
        # 「dist/index.js」要相對於什麼才算數?我試過兩個答案,兩個都錯:
        #
        #   拿 Forseti repo 當基準   →  別的專案的檔案全被判成假的
        #   拿 session 的 cwd 當基準 →  這個 repo 裡真的存在的檔案
        #                               (docs/build-plan.md、ledger.py)
        #                               全被判成假的
        #
        # 兩種誤判的方向剛好相反,而那正說明問題不在規則:**一個相對路徑
        # 少了它的基準,本來就沒有真假可言。** cwd 也不是基準 ——
        # 這些 session 的 cwd 是家目錄,而它們開發的專案在外接碟上。
        #
        # 那個基準只有一個地方有:帳本裡 hook 當時記下的 FILE_WRITE。
        # 帳本沒有的話,誠實的答案是「我不知道」,不是「你說謊」。
        #
        # **這讓 B-13(hook 沒註冊、採集不到)從一個缺口變成前提。**
        # 沒有採集,這一層永遠只能回答 UNKNOWN。
        # ────────────────────────────────────────────
        if not claim.subject.startswith(("/", "~")) and from_ledger is None:
            claim.to("UNKNOWN",
                     f"「{claim.subject}」是相對路徑，而帳本裡沒有它的證據。"
                     "不知道它相對於哪裡，就沒有辦法說它不存在")
            return claim
        # 量到它不存在。但「量到不存在」跟「有資格說這個人在說謊」
        # 是兩件事 —— 見 can_refute()。
        ok, why_not = can_refute(claim.subject, resolved, cwd)
        if not ok:
            claim.to("UNKNOWN", why_not)
            return claim
        # 措辭要精確:驗證器只看得到一個 repo。一個宣稱可能在講別的
        # 專案(2026-09-11 實測抓到:`src/forseti` 是隔壁 Moirai 的目錄)。
        # 寫「不存在」太絕對,寫「在這裡找不到」才是這個驗證器真正知道的。
        # 措辭要精確到「在哪裡找不到」。寫「在這個 repo 裡」是錯的 ——
        # 基準是呼叫端給的 cwd,而它不一定是 repo(2026-09-11 接線之後
        # 它變成 session 的工作目錄)。一句講錯自己座標的判定,
        # 會讓讀的人以為系統查過了它其實沒查的地方。
        where = str(resolved.parent) if resolved.parent != resolved else str(cwd or "")
        claim.to("REFUTED", f"{claim.subject} 在 {where} 找不到")
        claim.raise_strength("E2", "stat 確定性檢查：檔案不存在")
        return claim

    if ev.get("is_dir"):
        claim.to("VERIFIED", f"{claim.subject} 存在，是一個目錄")
        claim.raise_strength("E2", "stat 確定性檢查：目錄存在")
        return claim

    size = ev.get("byteSize")
    if size is None:
        # 量得到它存在但量不到大小(讀不到內容、或帳本那筆證據沒有這個欄位)。
        # **None 不是 0。** 2026-09-11 真實語料抓到:帳本來的證據少那個欄位,
        # 於是 `not size` 成立,一個好好的檔案被判成空檔案。
        claim.to("UNKNOWN", f"{claim.subject} 存在，但量不到大小")
        return claim
    if not size:
        # CT-001。定罪之前一樣要問有沒有資格 ——
        #
        # 2026-09-11 真實語料抓到一個漂亮的例子:原句講的是
        # `~/Library/Application Support/Claude/...`,路徑含空格被正則切成
        # `~/Library/Application`,而那裡剛好真的有一個 0 bytes 的檔案
        # (某個程式被同樣的空格問題咬到留下的)。於是驗證器「正確地」
        # 判了一個 0 bytes,但它驗的根本不是那句話在講的東西。
        #
        # **一個技術上成立的定罪,驗錯了對象,仍然是冤枉。**
        ok, why_not = can_refute(claim.subject, resolved, cwd)
        if not ok:
            claim.to("UNKNOWN", why_not)
            return claim
        claim.to("REFUTED",
                 f"{claim.subject} 存在但是 0 bytes。建立了一個空檔案，"
                 "跟沒建立對使用者是一樣的")
        claim.raise_strength("E2", "stat 確定性檢查：size = 0")
        return claim

    claim.to("VERIFIED", f"{claim.subject} 存在且 {size:,} bytes")
    if from_ledger and now.get("existence") is True and now.get("byteSize"):
        # 兩個獨立來源：帳本裡當時量的，加上現在量的。§7.2 的 E3。
        claim.raise_strength("E3", "兩個獨立的確定性來源：帳本當時的證據 + 現在的 stat")
    else:
        claim.raise_strength("E2", "新鮮的確定性檢查：stat + hash")
    return claim
