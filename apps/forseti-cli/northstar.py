#!/usr/bin/env python3
"""北極星與它的版本鏈。階段 3 的第一塊。

規格來源：v5.0 §8.1（North Star state）與 §8.2（Branch types），
主 session 2026-09-11 逐行讀過。階段定義在 `docs/build-plan.md:353`。

────────────────────────────────────────────────────

## 這個模組存在的理由，是一句她講過但沒寫進文件的話

`.forseti/REQUIRED_READING.md` 的「她講過但沒寫進文件的事」裡有一條：

    人改變想法時拿舊北極星去警告他，那個北極星就變成強噪音

**那是這整個模組的立論。** 一個不會換版本的北極星，在她改變想法的
那一刻起，就從「錨」變成「噪音來源」—— 而且是最難關掉的那種噪音，
因為它每一次都言之成理。

所以版本鏈不是為了留歷史，是為了讓「現在該對著哪一個」有明確答案。

## supersedes 不是「舊的錯了」

v5.0 §8.1 的欄位叫 `supersedes`，不叫 `replaces` 也不叫 `fixes`。
那個詞選得很準：被取代的那一版，在它的時代是對的。

`docs/build-plan.md:355` 說的「把她的指令本來就模糊算成 AI 走掉」，
反過來也成立 —— 把她改變想法算成「原本那個目標失敗了」同樣是錯的。
**改變想法是擁有者的權力，不是需要被解釋的異常。**

所以這裡沒有任何一個欄位叫 `reason_for_failure`。有的是 `why`，
而它記的是「為什麼換」不是「哪裡錯」。

零依賴（ADR-009）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict

# v5.0 §8.2 的五種 branch。
BRANCHES = ("MAINLINE", "EXPERIMENTAL", "QUARANTINED", "HARVESTED", "CUT")

BRANCH_MEANING = {
    "MAINLINE": "現在被接受的目標與執行路徑。照政策正常讀寫",
    "EXPERIMENTAL": "刻意隔離的、可能有用的岔出。沙箱裡跑，沒複審不得升為正典",
    "QUARANTINED": "沒有支持的假設，或可疑的漂移。只准讀與驗，不准寫",
    "HARVESTED": "從漂移裡撿出來的有用想法。開一個獨立的實驗或任務",
    "CUT": "已知有害的岔出。停止傳播，從最後一個好的節點復原",
}


class NorthStarError(Exception):
    """北極星不合規格。"""


@dataclass
class NorthStar:
    """v5.0 §8.1 的十個欄位，一個都沒有加也沒有減。

    `version` 從 1 開始，`supersedes` 指向上一版的 version。
    第一版的 supersedes 是 None —— 那是鏈的起點，不是「沒有前一版的錯誤」。
    """

    objective: str
    version: int = 1
    supersedes: int | None = None
    non_goals: list[str] = field(default_factory=list)
    invariants: list[str] = field(default_factory=list)
    accepted_scope: list[str] = field(default_factory=list)
    rejected_scope: list[str] = field(default_factory=list)
    owner_constraints: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    authority: str = ""
    branch: str = "MAINLINE"
    at: float = field(default_factory=time.time)
    why: str = ""

    def __post_init__(self):
        if not self.objective.strip():
            raise NorthStarError("北極星不能沒有 objective。一個空的目標"
                                 "比沒有目標危險，因為它看起來像有目標")
        if self.branch not in BRANCHES:
            raise NorthStarError(f"不是 §8.2 的 branch：{self.branch}")
        if self.version < 1:
            raise NorthStarError("version 從 1 開始")
        if self.version == 1 and self.supersedes is not None:
            raise NorthStarError("第一版沒有前一版可以取代")
        if self.version > 1 and self.supersedes is None:
            raise NorthStarError(
                f"第 {self.version} 版必須說出它取代哪一版。"
                "斷掉的鏈沒辦法回答「當時對著的是哪一個」，"
                "而那正是回頭看一個舊決定時唯一要問的問題")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Chain:
    """一條北極星的版本鏈。

    **刻意不提供刪除。** 一個被取代的版本要留著，因為回頭看一個舊決定
    的時候，唯一要問的是「它當時對著哪一個北極星」。把舊版刪掉之後，
    所有舊決定都會被拿現在的標準去評，而那是最不公平的一種事後諸葛。
    """

    versions: list[NorthStar] = field(default_factory=list)

    @property
    def current(self) -> NorthStar | None:
        """現在生效的那一版。沒有就是 None，不回一個空的。"""
        live = [v for v in self.versions if v.branch != "CUT"]
        return max(live, key=lambda v: v.version) if live else None

    def adopt(self, objective: str, *, authority: str, why: str,
              **fields) -> NorthStar:
        """換一版北極星。

        `why` 是必填而且不能空白。理由是這個模組唯一的用途 ——
        之後有人問「為什麼那時候方向變了」，答案要在鏈上而不是在
        某個人的記憶裡。

        **這個方法不判斷新的比舊的好。** 它只記錄「從這一刻起，
        對著的是這一個」。
        """
        if not authority.strip():
            raise NorthStarError("換北極星要有具名的 authority。"
                                 "沒有名字的話，之後沒有人能回答是誰決定的")
        if not why.strip():
            raise NorthStarError("換北極星要說出為什麼換。"
                                 "空白的理由等於沒有鏈")
        prev = self.current
        ns = NorthStar(
            objective=objective,
            version=(prev.version + 1) if prev else 1,
            supersedes=prev.version if prev else None,
            authority=authority, why=why, **fields)
        self.versions.append(ns)
        return ns

    def at_version(self, version: int) -> NorthStar | None:
        """當時對著的是哪一個。回頭評一個舊決定時要用這個。"""
        for v in self.versions:
            if v.version == version:
                return v
        return None

    def is_stale(self, version: int) -> bool:
        """這一版還是現在生效的嗎。

        **拿一個 stale 的北極星去警告人，那個警告就是噪音。**
        任何偏離判定在開口之前都應該先問這一句。
        """
        cur = self.current
        return cur is None or version != cur.version

    def diff(self, a: int, b: int) -> dict:
        """兩版之間變了什麼。

        `build-plan.md:361` 要的「她改變想法時北極星要跟著更新版本，
        而不是拿舊的去警告她」，需要這個來回答「到底變了哪裡」。
        """
        va, vb = self.at_version(a), self.at_version(b)
        if va is None or vb is None:
            raise NorthStarError(f"版本不存在：{a if va is None else b}")
        out: dict = {"from": a, "to": b, "changed": {}, "why": vb.why}
        for key in ("objective", "non_goals", "invariants", "accepted_scope",
                    "rejected_scope", "owner_constraints", "success_criteria",
                    "branch"):
            x, y = getattr(va, key), getattr(vb, key)
            if x != y:
                out["changed"][key] = {"before": x, "after": y}
        return out
