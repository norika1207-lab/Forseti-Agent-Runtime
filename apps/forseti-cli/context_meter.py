#!/usr/bin/env python3
"""Context 佔用與壓縮事件的讀取層。階段 C0。

存在的理由：`.forseti/BLOCKERS.md` 的 B-01 原本寫「拿不到 Context」，
那句話把兩件事混成一句，結果把可解的那一半也擋掉了三輪。
切開之後是這樣：

    context 裡裝了什麼 —— 拿不到。hook 只給工具事件。
    context 有多滿     —— 拿得到。就在 jsonl 裡，不需要 hook。

設計約束，跟 forseti.py 同一套：

  只讀不判斷。這裡沒有溫度、沒有分數、沒有閾值。每一個數字都能
  在 jsonl 的某個欄位找到出處，加法是唯一的運算。
  溫度是後面階段的事，要等行為訊號齊了才做，現在做就是憑空捏一個公式。

  零依賴。標準庫而已。

  拿不到就說拿不到。context 上限這個檔案裡沒有，所以不報百分比。
  報一個推估的百分比會讓人以為系統知道上限，那是騙人。

用法：
    python3 apps/forseti-cli/context_meter.py            # 最近活動的 session
    python3 apps/forseti-cli/context_meter.py --all      # 掃全部，出總表
    python3 apps/forseti-cli/context_meter.py <path.jsonl>
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"


# ---------------------------------------------------------------------------
# 資料
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    """一次送進模型的請求。

    occupancy 是那一次真正送進去的 context 大小。三個欄位要全加：
    input 是這次新增的、cache_read 是快取命中的、cache_write 是這次寫進快取的，
    三者都佔位置。只看 input 會嚴重低估，這個 session 的 input 是 2，
    cache_read 是 129,584。
    """

    ts: str
    request_id: str
    occupancy: int
    output: int


@dataclass
class Compaction:
    """一次壓縮。數字全部來自 jsonl 的 compactMetadata，不是推算的。"""

    ts: str
    trigger: str
    pre: int
    post: int
    dropped: int
    duration_ms: int
    head_uuid: str | None = None
    anchor_uuid: str | None = None

    @property
    def kept_ratio(self) -> float:
        return self.post / self.pre if self.pre else 0.0


@dataclass
class SessionMeter:
    path: Path
    session_id: str | None = None
    cwd: str | None = None
    turns: list[Turn] = field(default_factory=list)
    compactions: list[Compaction] = field(default_factory=list)
    bad_lines: int = 0

    @property
    def current(self) -> int:
        return self.turns[-1].occupancy if self.turns else 0

    @property
    def peak(self) -> int:
        """觀察到的最大佔用。

        這不是 context 上限。上限在這個檔案裡沒有，不要拿這個數字當上限用。
        它只回答一件事：這個 session 曾經裝到多滿而沒有被壓縮。
        """
        return max((t.occupancy for t in self.turns), default=0)

    @property
    def total_dropped(self) -> int:
        return sum(c.dropped for c in self.compactions)

    def delta(self, n: int = 10) -> list[tuple[str, int, int]]:
        """最近 n 輪的佔用與增量。回傳 (時間, 佔用, 與前一輪的差)。"""
        tail = self.turns[-n:]
        out = []
        prev = None
        for t in tail:
            out.append((t.ts, t.occupancy, 0 if prev is None else t.occupancy - prev))
            prev = t.occupancy
        return out


# ---------------------------------------------------------------------------
# 讀取
# ---------------------------------------------------------------------------

def read_session(path: Path) -> SessionMeter:
    """讀一份 jsonl。壞行跳過並計數，不讓一行壞資料炸掉整份。"""
    m = SessionMeter(path=path)
    seen: set[str] = set()

    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return m

    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except (ValueError, TypeError):
                m.bad_lines += 1
                continue
            if not isinstance(d, dict):
                m.bad_lines += 1
                continue

            if m.session_id is None:
                m.session_id = d.get("sessionId")
            if m.cwd is None:
                m.cwd = d.get("cwd")

            # 壓縮事件。明確標記，不需要靠佔用驟降推測。
            if d.get("subtype") == "compact_boundary":
                meta = d.get("compactMetadata") or {}
                seg = meta.get("preservedSegment") or {}
                m.compactions.append(Compaction(
                    ts=d.get("timestamp") or "",
                    trigger=meta.get("trigger") or "unknown",
                    pre=int(meta.get("preTokens") or 0),
                    post=int(meta.get("postTokens") or 0),
                    dropped=int(meta.get("cumulativeDroppedTokens") or 0),
                    duration_ms=int(meta.get("durationMs") or 0),
                    head_uuid=seg.get("headUuid"),
                    anchor_uuid=seg.get("anchorUuid"),
                ))
                continue

            usage = ((d.get("message") or {}).get("usage")) if isinstance(d.get("message"), dict) else None
            if not isinstance(usage, dict):
                continue

            # 一次回應會拆成多行(apiBlockIndex)，usage 相同。
            # 不去重的話同一次請求會被算好幾次，趨勢圖就是假的。
            rid = d.get("requestId") or (d.get("message") or {}).get("id") or d.get("uuid")
            if rid in seen:
                continue
            if rid:
                seen.add(rid)

            m.turns.append(Turn(
                ts=d.get("timestamp") or "",
                request_id=str(rid),
                occupancy=(int(usage.get("input_tokens") or 0)
                           + int(usage.get("cache_read_input_tokens") or 0)
                           + int(usage.get("cache_creation_input_tokens") or 0)),
                output=int(usage.get("output_tokens") or 0),
            ))

    # 檔案行序不保證等於時間序（實測本 session 就不相等）。
    # 「當前佔用」的定義是時間最新的那一次，不是檔案最後一行。
    m.turns.sort(key=lambda t: t.ts)
    m.compactions.sort(key=lambda c: c.ts)
    return m


def find_sessions(root: Path = PROJECTS_DIR) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(root.glob("*/*.jsonl"), key=lambda p: _mtime(p), reverse=True)


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def latest_session(root: Path = PROJECTS_DIR) -> Path | None:
    files = find_sessions(root)
    return files[0] if files else None


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------

def _n(v: int) -> str:
    return f"{v:,}"


def _hhmm(ts: str) -> str:
    """jsonl 的 timestamp 是 UTC，直接印會差八小時。

    2026-09-08 寫這個模組的時候，我自己就被這件事騙了一次：看到 13:52
    以為是未來時間，去查了半天以為排序有 bug，實際上那是 UTC，本地 21:52。
    會誤導人的時間顯示就是壞的時間顯示，所以這裡一律轉成本地時間。
    """
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ts[11:19] if len(ts) >= 19 else ts


_LEVELS = "▁▂▃▄▅▆▇█"


def _spark(m: SessionMeter, width: int = 60) -> str:
    """整場的佔用走勢，壓縮處標 ▼。

    取樣而不是取平均：每一格取該區間的最大值。用平均的話壓縮前的尖峰
    會被旁邊的低點拉平，而尖峰正是要看的東西。
    """
    ts_list = [t.ts for t in m.turns]
    vals = [t.occupancy for t in m.turns]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1

    n = len(vals)
    out = []
    for i in range(width):
        a = i * n // width
        b = max(a + 1, (i + 1) * n // width)
        chunk = vals[a:b]
        peak = max(chunk)
        out.append(_LEVELS[min(len(_LEVELS) - 1, int((peak - lo) / span * (len(_LEVELS) - 1)))])

    # 把壓縮標到它發生的那一格
    for c in m.compactions:
        if not c.ts:
            continue
        idx = sum(1 for t in ts_list if t < c.ts)
        col = min(width - 1, idx * width // max(1, n))
        out[col] = "▼"

    return "".join(out)


def _dur(ms: int) -> str:
    s = ms / 1000
    if s < 60:
        return f"{s:.0f}s"
    return f"{int(s // 60)}m{int(s % 60):02d}s"


def report_one(m: SessionMeter) -> int:
    print()
    print(f"  session　{(m.session_id or '?')[:8]}")
    if m.cwd:
        print(f"  工作目錄　{m.cwd}")
    print("  時間一律顯示本地時區（jsonl 存的是 UTC）")
    print()

    if not m.turns:
        print("  這份 jsonl 裡沒有帶 usage 的訊息，量不到佔用。")
        print()
        return 1

    last = m.turns[-1]
    print("  當前 context 佔用")
    print(f"    {_n(last.occupancy)}　（{len(m.turns)} 次請求，最後一次 {_hhmm(last.ts)}）")
    print(f"    這個 session 觀察到的最高點　{_n(m.peak)}")
    print("    上限不在資料裡，所以這裡不報百分比。")
    print()

    if m.compactions:
        print(f"  壓縮事件　{len(m.compactions)} 次")
        for c in m.compactions:
            print(f"    {_hhmm(c.ts)}　{c.trigger}　"
                  f"{_n(c.pre)} → {_n(c.post)}　"
                  f"丟棄 {_n(c.dropped)}　歷時 {_dur(c.duration_ms)}")
            if c.anchor_uuid:
                print(f"              保留段錨點 {c.anchor_uuid[:8]}　"
                      f"被丟掉的部分仍在這份 jsonl 裡")
        print(f"    累計丟棄　{_n(m.total_dropped)}")
        print()
    else:
        print("  壓縮事件　尚未發生")
        print()

    if len(m.turns) > 2:
        # 全程走勢。只看最近幾筆是看不到壓縮的，那道斷崖在更前面，
        # 而斷崖才是這張圖存在的理由。
        print("  全程走勢")
        print(f"    {_spark(m, 60)}")
        print(f"    {_hhmm(m.turns[0].ts)}"
              + " " * 44 + f"{_hhmm(m.turns[-1].ts)}")
        print(f"    低 {_n(min(t.occupancy for t in m.turns))}"
              f"　高 {_n(m.peak)}"
              + ("　▼ 標示壓縮發生的位置" if m.compactions else ""))
        print()

    rows = m.delta(10)
    if len(rows) > 1:
        print("  最近 10 次請求")
        for ts, occ, dl in rows:
            sign = f"{dl:+,}" if dl else "—"
            print(f"    {_hhmm(ts)}  {occ:>9,}  {sign:>10}")
        print()

    if m.bad_lines:
        print(f"  ! 有 {m.bad_lines} 行解析不了，已跳過。")
        print()
    return 0


def report_all(root: Path = PROJECTS_DIR) -> int:
    t0 = time.time()
    files = find_sessions(root)
    if not files:
        print(f"\n  {root} 底下沒有 jsonl。\n")
        return 1

    total_bytes = 0
    total_turns = 0
    total_comp = 0
    total_dropped = 0
    hottest: list[tuple[int, SessionMeter]] = []

    for p in files:
        try:
            total_bytes += p.stat().st_size
        except OSError:
            pass
        m = read_session(p)
        total_turns += len(m.turns)
        total_comp += len(m.compactions)
        total_dropped += m.total_dropped
        if m.turns:
            hottest.append((m.peak, m))

    elapsed = time.time() - t0
    hottest.sort(key=lambda x: x[0], reverse=True)

    print()
    print("  全掃")
    print(f"    session 檔案　{_n(len(files))} 份，共 {total_bytes / 1e6:.0f} MB")
    print(f"    帶 usage 的請求　{_n(total_turns)} 次")
    print(f"    壓縮事件　{_n(total_comp)} 次，累計丟棄 {_n(total_dropped)} tokens")
    print(f"    掃描耗時　{elapsed:.1f}s")
    print()
    print("    這個耗時決定索引層可不可行。C1 的索引是增量建立的，")
    print("    全掃只在第一次做一遍。")
    print()

    print("  佔用最高的 5 個 session")
    for peak, m in hottest[:5]:
        tag = f"{len(m.compactions)} 次壓縮" if m.compactions else "未壓縮"
        print(f"    {_n(peak):>9}　{(m.session_id or '?')[:8]}　{tag}")
    print()
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]

    if args and args[0] == "--all":
        return report_all()

    if args:
        p = Path(args[0]).expanduser()
        if not p.is_file():
            print(f"讀不到 {p}", file=sys.stderr)
            return 2
        return report_one(read_session(p))

    p = latest_session()
    if p is None:
        print(f"{PROJECTS_DIR} 底下沒有 jsonl。", file=sys.stderr)
        return 2
    return report_one(read_session(p))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
