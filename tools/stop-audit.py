#!/usr/bin/env python3
"""量 F06 §5 的 HumanContinueBurden。拿這個 session 自己當樣本。

F06-EXC-001 §5 逐字：

    HumanContinueBurden = human "continue/do it/keep going" prompts per task

壓縮前的我在 2026-09-09 量過一次，8 次，時間戳記在
`.forseti/REQUIRED_READING.md`。這支把那次的量法變成可重跑的工具。

────────────────────────────────────────────────────

## 判準只用結構，不讀語氣

一則 owner 訊息算成「催促」，要同時滿足兩件：

    夠短（催促幾乎都短，長訊息通常帶著新資訊）
    整句就是一個祈使或方向詞，沒有帶新的具體標的

「讀 F05」算，因為它只是在指定序列裡的下一步，那個下一步本來就
確定。「把 risky 清單跑出來」不算，那是新工作。

**分不出來的一律不算。** 低估比高估好：這個數字要用來說「AI 讓人
變成心跳器」，而一個灌水的數字會讓那句話站不住。

用法：

    python3 tools/stop-audit.py [<session-uuid 或 .jsonl 路徑>]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "apps" / "forseti-cli"))

import owner as O          # noqa: E402
import stopreason as S     # noqa: E402

PROJECTS = Path.home() / ".claude" / "projects"
THIS_SESSION = "a280762a"

# 催促的形狀。短、祈使、沒有新標的。
_NUDGE = re.compile(
    r"^(?:繼續|接續|往下|再來|然後呢?|下一步|go|next|做|開始|動手)\s*[。!！,，]?$"
    r"|^讀\s*[A-Za-z0-9_.-]{1,20}\s*$"
    r"|^(?:去|快|趕快|你去)\s*\S{1,8}\s*$"
    r"|繼續做|繼續走|接著做|不要停|別停|你又停")

# 夠短的上限。超過這個長度的訊息通常帶著新資訊，不算純催促。
NUDGE_MAX_CHARS = 30


def is_nudge(text: str) -> bool:
    t = " ".join((text or "").split())
    if not t:
        return False
    if len(t) <= NUDGE_MAX_CHARS and _NUDGE.search(t):
        return True
    return bool(re.search(r"你又停|不要停|別停|還在等什麼", t))


def rounds(path: Path):
    """(owner 訊息, 下一則 owner 訊息)。每一對之間就是我停的那一次。"""
    msgs = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for i, line in enumerate(fh, 1):
            try:
                d = json.loads(line)
            except (ValueError, TypeError):
                continue
            if d.get("type") != "user":
                continue
            c = (d.get("message") or {}).get("content")
            if isinstance(c, str):
                t = c
            elif isinstance(c, list):
                t = "\n".join(b.get("text", "") for b in c
                              if isinstance(b, dict) and b.get("type") == "text")
            else:
                continue
            if O.is_owner_text(t) and t.strip():
                msgs.append((i, t))
    return msgs


def main(argv: list[str]) -> int:
    arg = argv[1] if len(argv) > 1 else THIS_SESSION
    p = Path(arg).expanduser()
    if not p.is_file():
        hits = sorted(PROJECTS.glob(f"*/{arg}*.jsonl"))
        if not hits:
            print(f"  找不到 transcript：{arg}")
            return 2
        p = hits[0]

    msgs = rounds(p)
    stops: list[S.StopAssessment] = []
    nudges = []
    for line_no, text in msgs:
        nudge = is_nudge(text)
        if nudge:
            nudges.append((line_no, " ".join(text.split())[:44]))
        # 每一則 owner 訊息之前，都有我的一次停止。
        # 如果那則訊息只是催促，代表當時有確定的下一步而我停了。
        stops.append(S.classify_stop(
            "UNKNOWN_STOP" if nudge else "WAITING_EXTERNAL",
            has_authorized_next_action=nudge))

    b = S.burden(stops)
    print()
    print(f"  {p.name}")
    print(f"  owner 訊息　{len(msgs)} 則")
    print()
    print(f"  HumanContinueBurden　{len(nudges)} 次")
    print("  （F06 §5 定義：human continue/do it/keep going prompts per task，")
    print("    規格說它應趨近於零）")
    print()
    print(f"  停止判定　{b['stops']} 次，其中 {b['violations']} 次是")
    print(f"  EXECUTION_CONTINUITY_VIOLATION（{b['violation_rate']:.0%}）")
    print()
    if nudges:
        print("  每一次她必須開口：")
        print()
        for ln, t in nudges:
            print(f"    第 {ln} 行　{t}")
        print()
    print("  判準只用結構不讀語氣，分不出來的一律不算。")
    print("  低估比高估好：灌水的數字會讓「AI 讓人變成心跳器」這句話站不住。")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
