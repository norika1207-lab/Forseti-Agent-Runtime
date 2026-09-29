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

import json
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

CROSS_SESSION_SCHEMA_VERSION = 1


class NorthStarError(Exception):
    """北極星不合規格。"""


def _positive_int(value) -> bool:
    """Python bool is an int subclass; versions must reject it explicitly."""
    return type(value) is int and value > 0


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
        if not _positive_int(self.version):
            raise NorthStarError("version 從 1 開始")
        if self.supersedes is not None and not _positive_int(self.supersedes):
            raise NorthStarError("supersedes 必須是正整數版本號")
        if self.version == 1 and self.supersedes is not None:
            raise NorthStarError("第一版沒有前一版可以取代")
        if self.version > 1 and self.supersedes is None:
            raise NorthStarError(
                f"第 {self.version} 版必須說出它取代哪一版。"
                "斷掉的鏈沒辦法回答「當時對著的是哪一個」，"
                "而那正是回頭看一個舊決定時唯一要問的問題")
        if (self.supersedes is not None
                and self.supersedes >= self.version):
            raise NorthStarError("supersedes 必須指向更早的正整數版本")

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
    provenance: dict[int, dict] = field(default_factory=dict)

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
        # CUT is not current, but it remains part of the immutable version
        # chain.  Version allocation must therefore follow the latest record,
        # not the latest live record, or adopting after a CUT would duplicate a
        # version number.
        prev = max(self.versions, key=lambda v: v.version) if self.versions else None
        ns = NorthStar(
            objective=objective,
            version=(prev.version + 1) if prev else 1,
            supersedes=prev.version if prev else None,
            authority=authority, why=why, **fields)
        self.versions.append(ns)
        return ns

    def adopt_from_session(self, objective: str, *, authority: str, why: str,
                           session_id: str, event_id: str,
                           owner_confirmed: bool, **fields) -> NorthStar:
        """Adopt a version with explicit cross-session provenance.

        ``owner_confirmed`` is an observed provenance flag.  It is never
        inferred from the authority's display name.
        """
        if not isinstance(session_id, str) or not isinstance(event_id, str):
            raise NorthStarError("session_id 與 event_id 必須是字串，不能補值")
        session_id = session_id.strip()
        event_id = event_id.strip()
        if not session_id or not event_id:
            raise NorthStarError("跨 session 版本必須有 session_id 與 event_id")
        if not isinstance(owner_confirmed, bool):
            raise NorthStarError("owner_confirmed 必須是明確 boolean，不能猜")
        if any(meta.get("event_id") == event_id for meta in self.provenance.values()):
            raise NorthStarError(f"event_id 重複：{event_id}")
        ns = self.adopt(objective, authority=authority, why=why, **fields)
        self.provenance[ns.version] = {
            "session_id": session_id,
            "event_id": event_id,
            "owner_confirmed": owner_confirmed,
        }
        return ns

    def to_records(self) -> list[dict]:
        """Return version-sorted records suitable for deterministic replay."""
        records = []
        for ns in sorted(self.versions, key=lambda value: value.version):
            meta = self.provenance.get(ns.version)
            if not meta:
                raise NorthStarError(
                    f"第 {ns.version} 版缺 cross-session provenance，不能序列化")
            records.append({
                "schema_version": CROSS_SESSION_SCHEMA_VERSION,
                **meta,
                "north_star": ns.to_dict(),
            })
        return records

    def to_canonical_json(self) -> str:
        """Serialize with stable key and record ordering."""
        return json.dumps(self.to_records(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    @classmethod
    def from_records(cls, records: list[dict]) -> "Chain":
        """Replay records independent of provider/session arrival order."""
        parsed: list[tuple[NorthStar, dict]] = []
        event_ids: set[str] = set()
        for record in records:
            schema_version = record.get("schema_version")
            if (type(schema_version) is not int
                    or schema_version != CROSS_SESSION_SCHEMA_VERSION):
                raise NorthStarError("不支援的 cross-session schema_version")
            raw_session_id = record.get("session_id")
            raw_event_id = record.get("event_id")
            if not isinstance(raw_session_id, str) or not isinstance(raw_event_id, str):
                raise NorthStarError("session_id 與 event_id 必須是字串，不能補值")
            session_id = raw_session_id.strip()
            event_id = raw_event_id.strip()
            owner_confirmed = record.get("owner_confirmed")
            if not session_id or not event_id or not isinstance(owner_confirmed, bool):
                raise NorthStarError("record 缺 session/event/owner provenance")
            if event_id in event_ids:
                raise NorthStarError(f"event_id 重複：{event_id}")
            event_ids.add(event_id)
            payload = record.get("north_star")
            if not isinstance(payload, dict):
                raise NorthStarError("record 缺 north_star payload")
            try:
                ns = NorthStar(**payload)
            except (TypeError, ValueError) as exc:
                raise NorthStarError(f"north_star payload 不合法：{exc}") from exc
            parsed.append((ns, {
                "session_id": session_id,
                "event_id": event_id,
                "owner_confirmed": owner_confirmed,
            }))

        parsed.sort(key=lambda item: item[0].version)
        expected = 1
        previous = None
        for ns, _ in parsed:
            if ns.version != expected:
                raise NorthStarError(f"版本鏈不連續：預期 {expected}，得到 {ns.version}")
            if previous is not None and ns.supersedes != previous:
                raise NorthStarError(
                    f"第 {ns.version} 版應 supersede {previous}，得到 {ns.supersedes}")
            expected += 1
            previous = ns.version

        chain = cls()
        for ns, meta in parsed:
            chain.versions.append(ns)
            chain.provenance[ns.version] = meta
        return chain

    @classmethod
    def from_canonical_json(cls, raw: str) -> "Chain":
        try:
            records = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise NorthStarError(f"版本鏈不是合法 JSON：{exc}") from exc
        if not isinstance(records, list):
            raise NorthStarError("版本鏈 JSON 必須是 record list")
        return cls.from_records(records)

    def goal_change_exclusion(self, from_version: int,
                              to_version: int) -> dict:
        """Return an FS-GOL-002 exclusion only with explicit owner evidence."""
        if (not _positive_int(from_version) or not _positive_int(to_version)
                or to_version <= from_version):
            return {"kind": "UNKNOWN", "owner_confirmed": None,
                    "from_version": from_version, "to_version": to_version,
                    "evidence_refs": [],
                    "why": "版本必須是嚴格正整數且 to_version 單調增加"}
        old = self.at_version(from_version)
        new = self.at_version(to_version)
        meta = self.provenance.get(to_version)
        if old is None or new is None or new.supersedes != old.version:
            return {"kind": "UNKNOWN", "owner_confirmed": None,
                    "from_version": from_version, "to_version": to_version,
                    "evidence_refs": [],
                    "why": "版本不存在或不是直接 supersession"}
        if not meta or meta.get("owner_confirmed") is not True:
            return {"kind": "UNKNOWN", "owner_confirmed": None,
                    "from_version": from_version, "to_version": to_version,
                    "evidence_refs": ([meta["event_id"]] if meta else []),
                    "why": "缺 owner-confirmed provenance，不能猜 goal change"}
        return {"kind": "OWNER_GOAL_CHANGE", "owner_confirmed": True,
                "from_version": from_version, "to_version": to_version,
                "evidence_refs": [meta["event_id"]],
                "why": "新版本由 owner-confirmed event 直接 supersede 舊版本"}

    def at_version(self, version: int) -> NorthStar | None:
        """當時對著的是哪一個。回頭評一個舊決定時要用這個。"""
        if not _positive_int(version):
            return None
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
