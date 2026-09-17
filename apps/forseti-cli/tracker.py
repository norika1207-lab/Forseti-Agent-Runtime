#!/usr/bin/env python3
"""把一份正在寫入的 transcript 變成一條會長的線。Widget 的資料層。

規格：`.forseti/WIDGET_SPEC.md` §3（線）、§4（點）。

────────────────────────────────────────────────────

## 這支跟 timeline.py 差在哪

`tools/timeline.py` 是事後分析：讀完整份、每一輪跑 `claims.verify()`、
163 輪要數分鐘。那是回顧工具。

這一支是即時：只讀新增的位元組、不做任何需要跑子程序的判斷、
一次呼叫要在毫秒級回來。**因為它每 1 到 3 秒就會被叫一次。**

WIDGET_SPEC §13：owner 明說不需要 0 毫秒延遲，1 到 3 秒可以，
AI thinking 的時候本來就有餘裕。但「有餘裕」不等於「可以慢」——
它要在 AI 還在講話的時候就把線畫出來。

## 線的定義（§3.1）

一條線 = 一個來回。起點是使用者發話那一刻，終點是 AI 回完那一刻。

**線有長度，等於那一輪花了多久。** 所以 `started_at` 與 `ended_at`
都要留，不能只留一個時間戳。

**AI 還在跑的時候線一直長不會停** —— 那一條的 `ended_at` 是 None，
呼叫端要把它畫成「還在生長」。畫面最底下永遠有一條正在長的線。

## 點的定義（§3.2、§4）

每一次工具呼叫釘一個點。尺寸與顏色照 §4：

    6x6 黑   對話壓縮
    4x4      一輪的起訖
    2x2      輪內的工具動作
    2x2 紅   工具失敗

**工具失敗怎麼判**：`tool_result` 帶 `is_error`，或內容裡有
exit code 非零的跡象。這裡只認前者 —— 後者要讀內容猜語意，
而 `build-plan.md:350` 禁止。**認不出來就不標紅，
寧可漏掉也不要冤枉一個成功的呼叫。**

## 這支不做的事

不判斷飄移、不算健康度、不碰北極星。那些在 §14：
第一版只做兩件事 —— 線即時長、工具點釘上去。

零依賴（ADR-009）。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

# 讀（不改變世界）與寫（會改變世界）。§3.6
#
# 一條線上全是讀點 = 它在找東西還沒動手。突然出現一串寫點 = 它開始改了。
# 那個轉折點是最該看的地方:如果它在還沒找清楚之前就開始寫,
# 那通常就是出事的起點。
READ_TOOLS = frozenset({
    "Read", "Grep", "Glob", "NotebookRead", "WebFetch", "WebSearch",
    "ListAgents", "TaskOutput", "ToolSearch",
})
WRITE_TOOLS = frozenset({
    "Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "BashOutput",
    "Artifact", "SendMessage", "SendUserFile",
})

KIND_READ, KIND_WRITE, KIND_OTHER = "read", "write", "other"


def tool_kind(name: str) -> str:
    if name in READ_TOOLS:
        return KIND_READ
    if name in WRITE_TOOLS:
        return KIND_WRITE
    return KIND_OTHER


@dataclass
class Dot:
    """線上的一個點。§3.2、§4"""

    at: float
    label: str
    kind: str = KIND_OTHER
    failed: bool = False
    detail: str = ""
    count: int = 1              # 同一種連續重複時合併，§3.4
    line_no: int = 0
    size_override: int = 0      # 壓縮那顆是 6x6

    @property
    def size(self) -> int:
        """§4 的尺寸表。輪內動作 2x2，壓縮 6x6。

        黑點最大的理由:它的影響範圍最大 ——
        它不是一個事件,它是一條分界線。
        """
        return self.size_override or 2

    def to_dict(self) -> dict:
        return {
            "at": self.at, "label": self.label, "kind": self.kind,
            "failed": self.failed, "detail": self.detail[:200],
            "count": self.count, "size": self.size, "line": self.line_no,
        }


@dataclass
class Strand:
    """一條線。一個來回。§3.1"""

    n: int
    started_at: float
    owner_text: str
    owner_line: int
    ended_at: float | None = None
    ai_text: str = ""
    dots: list[Dot] = field(default_factory=list)
    compaction: bool = False     # 這一輪裡發生過壓縮，§6
    compaction_meta: dict = field(default_factory=dict)

    @property
    def growing(self) -> bool:
        """還在長。呼叫端要把它畫成沒有終點的線。"""
        return self.ended_at is None

    @property
    def duration(self) -> float:
        """線的長度。還在長的話算到現在。"""
        import time
        end = self.ended_at if self.ended_at is not None else time.time()
        return max(0.0, end - self.started_at)

    @property
    def failed_dots(self) -> int:
        return sum(1 for d in self.dots if d.failed)

    @property
    def tint(self) -> float:
        """紅點密度。0 是純綠，1 是純紅。§4.1

        **這不是健康度分數。** 它只回答一件事:這條線上有多少比例的
        動作失敗了。橘代表 AI 開始騙人(說有執行但沒執行),
        不是飄移。
        """
        if not self.dots:
            return 0.0
        return self.failed_dots / len(self.dots)

    def gaps(self, min_seconds: float = 20.0) -> list[tuple[float, float]]:
        """沒有任何動作的時間區段。§3.5

        實線是有動作的時間，淡的是什麼都沒發生的時間。
        一眼看得到「它卡在這裡三分鐘沒動」。

        那就是 F05 的 STALL_RISK，但不用算分數，用畫的。
        """
        import time
        end = self.ended_at if self.ended_at is not None else time.time()
        marks = [self.started_at] + [d.at for d in self.dots] + [end]
        out = []
        for a, b in zip(marks, marks[1:]):
            if b - a >= min_seconds:
                out.append((a, b))
        return out

    def to_dict(self) -> dict:
        return {
            "n": self.n,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "growing": self.growing,
            "duration": round(self.duration, 2),
            "owner_text": self.owner_text[:600],
            "owner_line": self.owner_line,
            "ai_text": self.ai_text[:900],
            "dots": [d.to_dict() for d in self.dots],
            "read": sum(1 for d in self.dots if d.kind == KIND_READ),
            "write": sum(1 for d in self.dots if d.kind == KIND_WRITE),
            "failed": self.failed_dots,
            "tint": round(self.tint, 3),
            "gaps": [[round(a, 2), round(b, 2)] for a, b in self.gaps()],
            "compaction": self.compaction,
            "compaction_meta": self.compaction_meta,
        }


def _ts(rec: dict) -> float:
    """ISO 字串轉 epoch。拿不到回 0，不猜。"""
    t = rec.get("timestamp")
    if not t:
        return 0.0
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(t).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _is_owner(text: str) -> bool:
    """真的是人講的話。

    `owner.is_owner_text()` 那份 NOT_OWNER 清單是實測出來的:
    2026-09-09 掃 800 個 session 發現 Codex 的 user_message 有 33.6%
    是它自己塞回去的歷史。不過濾的話會把系統注入的文字當成她說的話。
    """
    try:
        import owner as O
        return O.is_owner_text(text)
    except Exception:                        # noqa: BLE001
        return bool(text and text.strip())


class Tracker:
    """跟著一份 transcript 長。

    保留讀取位置，下一次只讀新增的位元組。
    **不重讀整份** —— 那份 jsonl 是 24 MB 而且一直在長。
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.offset = 0
        self.line_no = 0
        self.strands: list[Strand] = []
        self._pending_tools: dict[str, Dot] = {}   # tool_use_id -> Dot

    # -- 內部 ---------------------------------------------------------

    def _current(self) -> Strand | None:
        return self.strands[-1] if self.strands else None

    def _close_current(self, at: float) -> None:
        cur = self._current()
        if cur is not None and cur.ended_at is None:
            cur.ended_at = at

    def _add_dot(self, dot: Dot) -> None:
        cur = self._current()
        if cur is None:
            return
        # §3.4 同一種連續重複就併。不同種的不併 —— 那會讓漢堡清單失真。
        if (cur.dots and cur.dots[-1].label == dot.label
                and cur.dots[-1].failed == dot.failed
                and not dot.detail):
            cur.dots[-1].count += 1
            cur.dots[-1].at = dot.at
            return
        cur.dots.append(dot)

    def _handle(self, rec: dict, line_no: int) -> None:
        t = rec.get("type")
        at = _ts(rec)
        msg = rec.get("message") or {}
        content = msg.get("content")

        # 壓縮排在最前面。§6
        #
        # 【順序不能反】壓縮那一筆的 type 也是 "user",所以如果先走
        # user 分支,它會被當成一則新的使用者訊息開一條新線,
        # 而那條線是假的 —— 沒有人講那句話。
        # 2026-09-14 第一版就是這樣寫的,測試抓到。
        if rec.get("isCompactSummary") or rec.get("compactMetadata"):
            self._mark_compaction(rec, at, line_no)
            return

        if t == "user":
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                # tool_result 也是 user 型別。先處理它，那不是人講話。
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_result":
                        self._close_tool(b, at)
                text = "\n".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text")
            else:
                return
            if text.strip() and _is_owner(text):
                # 新的一輪。前一條線收尾。§3.1
                self._close_current(at)
                self.strands.append(Strand(
                    n=len(self.strands) + 1, started_at=at,
                    owner_text=text, owner_line=line_no))
            return

        if t == "assistant" and isinstance(content, list):
            cur = self._current()
            if cur is None:
                return
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    txt = b.get("text") or ""
                    if txt.strip():
                        cur.ai_text = (cur.ai_text + "\n\n" + txt).strip()
                elif b.get("type") == "tool_use":
                    name = b.get("name") or "?"
                    dot = Dot(at=at, label=name, kind=tool_kind(name),
                              detail=_tool_detail(b), line_no=line_no)
                    self._add_dot(dot)
                    tid = b.get("id")
                    if tid:
                        self._pending_tools[tid] = dot
            # AI 講完這一塊就先當這一輪的暫時終點。
            # 下一塊來了會往後推 —— 線就是這樣長的。
            cur.ended_at = at
            return

    def _mark_compaction(self, rec: dict, at: float, line_no: int) -> None:
        """壓縮的黑點。§6

        **它是一個錨,不只是警告記號。**

        `compactMetadata` 帶著真實的量化證據。2026-09-14 在這個
        session 的 transcript 裡實測到:

            {'trigger': 'auto', 'preTokens': 997325, 'postTokens': 17472}

        壓縮前 99.7 萬 token,壓縮後 1.7 萬 —— 掉了 98%。
        **那個數字就該寫在黑點旁邊**,因為它回答了「這次吃掉多少」,
        而那是使用者唯一需要知道的規模感。

        `line_no` 是錨的座標:黑點知道自己在全量紀錄的第幾行,
        往前推就得到被吃掉的範圍。
        """
        # 【一次壓縮橫跨兩行】2026-09-14 實測:
        #
        #   第 2218 行  type=system  帶 compactMetadata(有 token 數)
        #   第 2219 行  type=user    帶 isCompactSummary(沒有數字)
        #
        # 第一版對這兩行各標一顆黑點,而且第二顆把第一顆的數字蓋掉了。
        # 一次壓縮只該有一顆點,所以這裡要合併:
        # 已經標過的就只補資料,不再開新點。
        meta = rec.get("compactMetadata") or {}
        pre = meta.get("preTokens")
        post = meta.get("postTokens")
        detail = "AI 的記憶從這裡開始不完整"
        if isinstance(pre, int) and isinstance(post, int) and pre > 0:
            kept = post / pre
            detail = (f"壓縮前 {pre:,} token，壓縮後 {post:,}，"
                      f"留下 {kept:.1%}。觸發：{meta.get('trigger', '未知')}")
        cur = self._current()
        if cur is None:
            # 壓縮可能發生在任何一條線還沒開始的時候(例如 session 一開頭
            # 就是續接的摘要)。開一條只有黑點的線,不要把它丟掉 ——
            # 丟掉的話那個錨就不存在了。
            self.strands.append(Strand(
                n=len(self.strands) + 1, started_at=at,
                owner_text="(對話壓縮)", owner_line=line_no,
                ended_at=at, compaction=True))
            cur = self.strands[-1]
        cur.compaction = True

        # 已經有一顆黑點的話,只補上這一行帶來的資料,不再開新點。
        existing = next((d for d in cur.dots if d.label == "對話壓縮"), None)
        if existing is not None:
            if pre and post:
                existing.detail = detail
                cur.compaction_meta.update(
                    {"pre_tokens": pre, "post_tokens": post,
                     "trigger": meta.get("trigger")})
            # 錨的座標取第一次看到的那一行,不覆蓋 ——
            # 那一行才是壓縮真正發生的位置。
            cur.compaction_meta.setdefault("line", line_no)
            return

        cur.compaction_meta = {"pre_tokens": pre, "post_tokens": post,
                               "trigger": meta.get("trigger"),
                               "line": line_no}
        self._add_dot(Dot(at=at, label="對話壓縮", kind=KIND_OTHER,
                          detail=detail, line_no=line_no, size_override=6))

    def _close_tool(self, block: dict, at: float) -> None:
        """tool_result 回來了。失敗的話把對應的點標紅。§4.1

        只認 `is_error`。讀內容猜 exit code 是語意判斷,
        `build-plan.md:350` 禁止。認不出來就不標紅 ——
        寧可漏掉也不要冤枉一個成功的呼叫。
        """
        tid = block.get("tool_use_id")
        dot = self._pending_tools.pop(tid, None) if tid else None
        if dot is None:
            return
        if block.get("is_error") is True:
            dot.failed = True

    # -- 對外 ---------------------------------------------------------

    def poll(self) -> int:
        """讀新增的部分。回傳這次讀進幾行。

        檔案被截斷或換掉的話重來一次 —— 那通常代表換了 session。
        """
        try:
            size = self.path.stat().st_size
        except OSError:
            return 0
        if size < self.offset:
            self.offset = 0
            self.line_no = 0
            self.strands = []
            self._pending_tools = {}
        if size == self.offset:
            return 0

        read = 0
        with self.path.open("rb") as fh:
            fh.seek(self.offset)
            data = fh.read()
            # 最後一行可能寫到一半。留到下次。
            cut = data.rfind(b"\n")
            if cut < 0:
                return 0
            chunk = data[:cut + 1]
            self.offset += len(chunk)
            for raw in chunk.decode("utf-8", errors="replace").splitlines():
                self.line_no += 1
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                self._handle(rec, self.line_no)
                read += 1
        return read

    def snapshot(self, tail: int = 200) -> dict:
        """給 Widget 畫的資料。

        只回最後 `tail` 條 —— 一條 24 MB 的 transcript 有上百輪,
        全部送過去會讓前端每次重畫整棵樹。
        """
        rows = self.strands[-tail:]
        total_dots = sum(len(s.dots) for s in self.strands)
        total_failed = sum(s.failed_dots for s in self.strands)
        return {
            "path": str(self.path),
            "lines_read": self.line_no,
            "strands": len(self.strands),
            "shown": len(rows),
            "total_dots": total_dots,
            "total_failed": total_failed,
            "rows": [s.to_dict() for s in rows],
        }


def _tool_detail(block: dict) -> str:
    """滑過去看得到的那一行。§3.2

    只取最能識別的那個欄位,不是整包 input —— 整包會讓浮動視窗
    塞滿 JSON,而使用者要的是「它對哪個檔案做了什麼」。
    """
    inp = block.get("input") or {}
    if not isinstance(inp, dict):
        return ""
    for key in ("file_path", "path", "command", "pattern", "url",
                "description", "query", "prompt"):
        v = inp.get(key)
        if isinstance(v, str) and v.strip():
            return " ".join(v.split())[:200]
    return ""


def latest_session(projects: Path | None = None) -> Path | None:
    """最近被寫的那一份 jsonl。

    2026-09-14 實測:CLI 的 jsonl 是邊跑邊寫的(最後寫入距離當下 10 秒),
    而桌面版的 claude-code-sessions 索引近兩小時零更新。
    **所以資料源就是這份 jsonl,唯一的一份。**
    """
    base = projects or (Path.home() / ".claude" / "projects")
    best, best_m = None, -1.0
    if not base.is_dir():
        return None
    for d in base.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("*.jsonl"):
            try:
                m = f.stat().st_mtime
            except OSError:
                continue
            if m > best_m:
                best, best_m = f, m
    return best


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else latest_session()
    if target is None or not target.is_file():
        print(json.dumps({"error": "找不到 transcript"}, ensure_ascii=False))
        return 2
    tk = Tracker(target)
    tk.poll()
    print(json.dumps(tk.snapshot(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv))
