#!/usr/bin/env python3
"""Watchdog、停滯偵測與復原階梯。實作 F05-WDG-001。

規格來源（2026-09-09 READ_COVERAGE=FULL）：
    F05-WDG-001  sha256 17ca3a6ee9c4

F05 §1 的定位一句話講完：heartbeat 是故障偵測器，不是讓 AI 記得要工作
的引擎。這個差別決定了整個模組怎麼寫 —— 如果 heartbeat 是延續的引擎，
那少一次心跳就少做一件事；如果它只是偵測器，那它壞掉只會讓我們少知道
一件事，工作照樣由 F04 的事件鏈推進。

── 一處規格沒定義，我自己補的，標記清楚 ──────────────────

F05 §3 給了公式：

    STALL_RISK = duration_anomaly × no_progress_growth
                 × no_event_activity × expected_progress_confidence

但沒有定義任何一個因子的值域與量法。我在 REQUIRED_READING 裡把這一條
記成「沒看懂」，這個檔案是我的詮釋，不是規格原意：

  四個因子各自正規化到 0..1，1 代表「越像停滯」。
  相乘之後仍是 0..1。相乘的意思是任何一個因子接近 0 就足以洗掉懷疑，
  這符合 §3 那句「長時間本身不足以判定」。

  duration_anomaly 需要一個「預期多久」。現在沒有歷史資料可以算基準，
  所以用一個可設定的門檻，預設值是拍的。有歷史之後應該換成分位數。

這些數字沒有經過任何實測校準。拿它們當真理之前先去量。

── §6 的分線，這是最重要的設計 ─────────────────────────

Heartbeat proves neither correctness nor Goal alignment.
A worker can be alive and wrong.

所以這個模組只回答「還活著嗎」，絕不回答「做得對嗎」。做得對不對是
verify_step() 的事，那是真的去看磁碟。兩條線分開，各自產生自己的
incident 類型，混在一起會出現最糟的情況：worker 心跳正常於是沒人看它
的產物，而它的產物是錯的。

零依賴。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 門檻。全部沒有實測校準,見檔頭。
# ---------------------------------------------------------------------------

DEFAULTS = {
    # 超過這個秒數才開始考慮停滯。低於它一律不算,這是 §3「長時間
    # 本身不足以判定」的下界版本:短時間更不足以判定。
    "min_age_sec": 300.0,
    # 這個秒數之後 duration_anomaly 飽和到 1.0
    "saturate_sec": 3600.0,
    # 判 STALL_SUSPECT 的門檻
    "suspect_at": 0.5,
    # 連續幾次無回應就重派（CT-F05-04）
    "unresponsive_limit": 3,
}

LADDER = (
    "SUSPECT", "SOFT_PING", "INSPECT_STATE", "STRUCTURED_STATUS",
    "CHECKPOINT", "RESTART_OR_REASSIGN", "CLEAN_FORK", "HUMAN",
)


# ---------------------------------------------------------------------------
# 進度訊號（F05 §4）
# ---------------------------------------------------------------------------

@dataclass
class ProgressProbe:
    """一次進度取樣。

    §4 列的訊號裡，可以直接觀測的是產物的變化。這裡量的是
    expected_outputs 的存在、大小與內容 hash —— 跟 Code-Duo 的照妖鏡
    同一個判準：不問 worker 做了什麼，去看磁碟變了沒。

    刻意不把「worker 說它有進度」當成進度訊號。那是 claim。
    WORKER_PROGRESS 事件另外算，而且它只證明 worker 還會說話，
    不證明有東西被做出來。
    """

    at: float
    files: dict[str, tuple[int, str]] = field(default_factory=dict)

    @classmethod
    def take(cls, paths: list[str], cwd: Path) -> "ProgressProbe":
        out: dict[str, tuple[int, str]] = {}
        for rel in paths:
            p = Path(rel)
            if not p.is_absolute():
                p = cwd / p
            try:
                data = p.read_bytes()
            except OSError:
                continue
            out[rel] = (len(data), hashlib.sha256(data).hexdigest()[:12])
        return cls(at=time.time(), files=out)

    def changed_from(self, other: "ProgressProbe | None") -> bool:
        if other is None:
            return bool(self.files)
        return self.files != other.files


# ---------------------------------------------------------------------------
# 停滯評估（F05 §3）
# ---------------------------------------------------------------------------

@dataclass
class StallAssessment:
    risk: float
    suspect: bool
    factors: dict[str, float]
    why: str

    @property
    def verdict(self) -> str:
        return "STALL_SUSPECT" if self.suspect else "ALIVE"


def assess(*, age_sec: float, progress_changed: bool, events_since: int,
           expected_to_progress: bool = True, config: dict | None = None
           ) -> StallAssessment:
    """算 STALL_RISK。四個因子各自 0..1，1 代表越像停滯。

    參數對應 §3 的四個因子：
        age_sec            → duration_anomaly
        progress_changed   → no_progress_growth（取反）
        events_since       → no_event_activity（取反）
        expected_to_progress → expected_progress_confidence

    最後一個是關鍵的煞車：如果這一步本來就不該有可見產物
    （例如在等外部依賴），那再久也不算停滯。§3 說長時間本身不足以
    判定，這個因子就是「不足以」的具體形式。
    """
    c = {**DEFAULTS, **(config or {})}
    lo, hi = c["min_age_sec"], c["saturate_sec"]

    if age_sec <= lo:
        duration = 0.0
    else:
        duration = min(1.0, (age_sec - lo) / max(1.0, hi - lo))

    no_growth = 0.0 if progress_changed else 1.0
    no_events = 0.0 if events_since > 0 else 1.0
    confidence = 1.0 if expected_to_progress else 0.0

    factors = {
        "duration_anomaly": round(duration, 3),
        "no_progress_growth": no_growth,
        "no_event_activity": no_events,
        "expected_progress_confidence": confidence,
    }
    risk = duration * no_growth * no_events * confidence

    if progress_changed:
        why = "產物有變動，正在做事"
    elif events_since > 0:
        why = f"沒有新產物，但有 {events_since} 筆事件，還在回話"
    elif not expected_to_progress:
        why = "這一步本來就不預期有可見產物"
    elif duration == 0.0:
        why = f"才過 {age_sec:.0f} 秒，太短，不判定"
    else:
        why = f"{age_sec:.0f} 秒沒有產物變動也沒有事件"

    return StallAssessment(risk=round(risk, 3),
                           suspect=risk >= c["suspect_at"],
                           factors=factors, why=why)


# ---------------------------------------------------------------------------
# 復原階梯（F05 §5）
# ---------------------------------------------------------------------------

def next_rung(current: str | None, *, unresponsive_count: int = 0,
              can_report: str = "full", config: dict | None = None) -> str:
    """下一階該做什麼。

    §5 的階梯是 SUSPECT → soft ping → inspect state → structured status
    → checkpoint → restart/reassign → clean fork → human，而且人排在
    最後，只在權限或歧義需要時才叫。

    這個順序本身就是設計主張：叫人是最貴的一步，不是最方便的一步。

    can_report 是 B-10 加的。前三階（SOFT_PING、INSPECT_STATE、
    STRUCTURED_STATUS）全部是「問它」，而問一個回不了話的 worker
    等於白等三輪，然後才做真正有用的事。一個只有 Write 權限的 worker
    不會因為被問三次就變得能回答。

    所以 write_only 的 worker 直接跳過問話那三階，從 CHECKPOINT 開始 ——
    去看它留下了什麼，那是它唯一能留下的東西。這不是對它比較嚴格，
    是不要浪費時間問一個問不到的問題。
    """
    c = {**DEFAULTS, **(config or {})}
    if unresponsive_count >= c["unresponsive_limit"]:
        return "RESTART_OR_REASSIGN"

    ladder = LADDER
    if can_report == "write_only":
        ladder = tuple(r for r in LADDER
                       if r not in ("SOFT_PING", "INSPECT_STATE",
                                    "STRUCTURED_STATUS"))
    if current is None:
        return ladder[0]
    try:
        i = ladder.index(current)
    except ValueError:
        # 目前這一階不在這個 worker 的階梯上（例如它剛從 full 改判成
        # write_only）。從頭開始，不要猜一個位置。
        return ladder[0]
    return ladder[min(i + 1, len(ladder) - 1)]


# ---------------------------------------------------------------------------
# liveness 與 correctness 的分線（F05 §6）
# ---------------------------------------------------------------------------

@dataclass
class Incident:
    kind: str          # LIVENESS 或 CORRECTNESS
    step_id: str
    detail: str
    at: float = field(default_factory=time.time)


def correctness_incident(step_id: str, failed_verifiers: list[str]) -> Incident:
    """產物驗不過。這跟 worker 活不活著完全無關。

    CT-F05-05：heartbeat healthy but evidence wrong → separate
    correctness incident。分開的理由不是分類整齊,是因為混在一起會出現
    最糟的情況:worker 心跳正常於是沒人去看它的產物,而產物是錯的。
    """
    return Incident("CORRECTNESS", step_id,
                    "驗證未過：" + "、".join(failed_verifiers[:5]))


def liveness_incident(step_id: str, assessment: StallAssessment) -> Incident:
    return Incident("LIVENESS", step_id,
                    f"STALL_RISK {assessment.risk}　{assessment.why}")
