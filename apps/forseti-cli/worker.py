#!/usr/bin/env python3
"""Main / Sub-session 隔離與 Worker Result Packet。實作 F03-CSI-001。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    ARCH-EXEC-001  sha256 4ca6689973e5
    F01-PEC-001    sha256 fe86cb2a1ab7
    F02-TSM-001    sha256 99ec01294dde
    F03-CSI-001    sha256 792cd95009f0

F03 §5 那句是這個模組的核心，值得抄下來：Forseti does not eliminate
workers; it eliminates the need for workers to own continuity.

不是消滅 worker，是消滅「worker 必須擁有連續性」這件事。worker 可以死、
可以換、可以忘記，因為連續性在帳本裡不在它腦子裡。

── 這個模組實際在擋什麼 ─────────────────────────────────

F03 §3 的 context isolation rule：worker 收最小必要 context，
Main 預設不該收到 raw compiler log、巨大 JSON、整份 transcript
或每一個工具結果。

擋法不是請 worker 自律。worker 也是 AI，它會把它覺得重要的東西
全部貼回來，而它覺得重要的標準正是會飄的那個東西。所以擋法是
硬性的：summary 有字元上限，超過就拒收；raw log 一律落檔，
packet 只帶路徑。

零依賴。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Main Session pollution budget（F03 §3、F08 §6）
# ---------------------------------------------------------------------------

# summary 的字元上限。這個數字是可以調的,但它必須存在。
# 沒有上限的話,worker 會把整份 log 塞進 summary,然後這整層隔離
# 就變成一個資料夾結構,擋不住任何東西。
SUMMARY_LIMIT = 2000

# 單一欄位的清單長度上限。同理:沒有上限就會收到一百筆 artifacts。
LIST_LIMIT = 40

# 超過這個大小的原始輸出一律落檔,不進 packet。
RAW_INLINE_LIMIT = 4000

WORKER_STATUS = ("COMPLETED", "BLOCKED", "FAILED", "PARTIAL")


class PacketRejected(Exception):
    """packet 不符合 pollution budget 或契約，拒收。

    拒收不是懲罰 worker,是保護 Main。一個被截斷但看起來正常的 packet
    比一個被拒絕的 packet 危險,因為前者會讓人以為自己看到了全部。
    """


# ---------------------------------------------------------------------------
# Worker Result Packet（F03 §4）
# ---------------------------------------------------------------------------

@dataclass
class WorkerResult:
    """F03 §4 的 schema，欄位名照抄規格。

    unresolved_unknowns 是最重要的一欄，因為它是 Main 唯一無法自己
    驗證的東西。worker 說它做完了，Main 可以去看磁碟；worker 說它
    不知道什麼，Main 只能靠它講。所以這一欄空著要是一個刻意的宣告，
    不是預設值。
    """

    task_id: str
    step_id: str
    status: str
    summary: str
    artifacts: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    unresolved_unknowns: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    recommended_next_action: str = ""
    raw_log_refs: list[str] = field(default_factory=list)
    # 規格之外的一欄。理由見 check_scope()：worker 交回範圍外的產物
    # 必須看得見,不然 CT-F03-03 的「drift bounded by TaskStep」只是空話。
    out_of_scope: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def size(self) -> int:
        return len(json.dumps(self.to_dict(), ensure_ascii=False))


def _too_long(items: list[str], limit: int = LIST_LIMIT) -> bool:
    return len(items) > limit


def validate(packet: WorkerResult) -> list[str]:
    """回傳違規清單。空清單代表可以收。"""
    bad: list[str] = []
    if packet.status not in WORKER_STATUS:
        bad.append(f"status 不是合法值：{packet.status!r}（只接受 {'/'.join(WORKER_STATUS)}）")
    if not packet.summary.strip():
        bad.append("summary 是空的。做了什麼要用一句話講得出來")
    if len(packet.summary) > SUMMARY_LIMIT:
        bad.append(f"summary {len(packet.summary):,} 字元，超過上限 {SUMMARY_LIMIT:,}。"
                   f"細節寫進檔案，用 raw_log_refs 指過去")
    for name in ("artifacts", "evidence_refs", "tests", "raw_log_refs"):
        if _too_long(getattr(packet, name)):
            bad.append(f"{name} 超過 {LIST_LIMIT} 筆")
    if packet.status == "BLOCKED" and not packet.blockers:
        bad.append("狀態是 BLOCKED 但沒有說被什麼擋住")
    if packet.status == "COMPLETED" and not packet.evidence_refs and not packet.tests:
        bad.append("宣稱 COMPLETED 但沒有任何 evidence_refs 或 tests。"
                   "完成是一種需要證據的宣稱")
    return bad


# ---------------------------------------------------------------------------
# raw log 落檔（F03 §3）
# ---------------------------------------------------------------------------

def stash_raw(text: str, *, task_id: str, step_id: str,
              store: Path, label: str = "log") -> str:
    """把原始輸出落檔，回傳可放進 packet 的引用字串。

    落檔不是為了整齊,是為了讓 Main 有選擇。內容在檔案裡,Main 決定
    要不要讀、讀哪一段。塞進 packet 的話 Main 沒有選擇,它一定會進 context。
    """
    store.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    safe_step = step_id.replace("/", "_")
    path = store / f"{safe_step}-{label}-{digest}.txt"
    if not path.exists():
        path.write_text(text, encoding="utf-8")
    return f"{path}#{len(text)}chars"


def default_store(ledger_db: Path) -> Path:
    """raw log 跟帳本放在一起。

    帳本在 ~/.forseti/ledgers/ 是因為 exFAT 跑不了 sqlite（見 ledger.py），
    raw log 沒有那個限制，但放在一起比較好清理：刪掉一個專案的帳本時，
    它的 log 就在隔壁。
    """
    return ledger_db.parent / (ledger_db.stem + "-logs")


# ---------------------------------------------------------------------------
# 範圍界定（F03 §6、CT-F03-03）
# ---------------------------------------------------------------------------

def check_scope(packet: WorkerResult, expected_outputs: list[str]) -> list[str]:
    """worker 交回來的產物有哪些不在 TaskStep 說好的範圍裡。

    F03 §6 要防的五件事之一是 worker redefining Goal。worker 偏離不會
    公告,它會安靜地多做一些事然後一起交回來,而那些多出來的東西
    看起來都很合理。所以判準不是內容像不像,是「這個產物有沒有在
    TaskStep 的 expected_outputs 裡」。

    這是結構比對不是語意判斷。expected_outputs 空的時候回空清單,
    因為沒有範圍就談不上超出範圍 —— 那是 TaskStep 沒定義好,
    不是 worker 的錯,兩者不可以混為一談。
    """
    if not expected_outputs:
        return []
    allowed = {Path(p).name for p in expected_outputs} | set(expected_outputs)
    out = []
    for a in packet.artifacts:
        if a in allowed or Path(a).name in allowed:
            continue
        out.append(a)
    return out


# ---------------------------------------------------------------------------
# 收件（Main 這一端）
# ---------------------------------------------------------------------------

@dataclass
class Receipt:
    """Main 收下 packet 之後留下的東西。"""

    accepted: bool
    packet: WorkerResult
    violations: list[str] = field(default_factory=list)
    at: float = field(default_factory=time.time)

    def brief(self) -> str:
        """給 Main 看的一句話。這是 Main 預設應該收到的份量。"""
        p = self.packet
        bits = [f"{p.status}　{p.summary.splitlines()[0][:120] if p.summary else ''}"]
        if p.tests:
            bits.append(f"測試 {len(p.tests)} 項")
        if p.unresolved_unknowns:
            bits.append(f"未知 {len(p.unresolved_unknowns)} 項")
        if p.blockers:
            bits.append(f"卡住 {len(p.blockers)} 項")
        if p.out_of_scope:
            bits.append(f"範圍外產物 {len(p.out_of_scope)} 項")
        if p.raw_log_refs:
            bits.append(f"原始輸出 {len(p.raw_log_refs)} 份（在檔案裡）")
        return "　".join(bits)


def receive(packet: WorkerResult, *, expected_outputs: list[str] | None = None,
            strict: bool = True) -> Receipt:
    """Main 收 worker 的結果。

    strict=True 時違規就拒收。拒收比截斷安全:一個被截斷但看起來正常的
    packet 會讓 Main 以為自己看到了全部。
    """
    packet.out_of_scope = check_scope(packet, expected_outputs or [])
    violations = validate(packet)
    if packet.out_of_scope:
        violations.append(
            f"{len(packet.out_of_scope)} 個產物不在 TaskStep 的 expected_outputs 裡："
            + "、".join(packet.out_of_scope[:5]))
    accepted = not violations if strict else True
    return Receipt(accepted=accepted, packet=packet, violations=violations)
