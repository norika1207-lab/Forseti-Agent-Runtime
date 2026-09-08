#!/usr/bin/env python3
"""Forseti CLI.

階段 0 的交付。它存在的理由很具體：2026-09-08 那個 session 花了兩小時
讀文件拼湊現況，然後走偏。如果當時有這個指令，第一輪就會知道要讀九份
不是一份、工程書指定 Python、照妖鏡在 Code Duo。

設計約束（階段 0 明令）：

  只讀檔案，不做判斷。這裡沒有 detector，沒有分數，沒有語意分析。
  它報告的每一個字都能在 .forseti/ 底下找到出處。

  零依賴。標準庫而已。要 Pydantic 是階段 1 的事，那時再裝。

  拿不到就說拿不到。缺一份控制檔就報缺，不用預設值填補，
  因為填補會讓一個沒設定好的專案看起來完全正常。

用法：
    python3 apps/forseti-cli/forseti.py doctor
    python3 apps/forseti-cli/forseti.py status
    python3 apps/forseti-cli/forseti.py gate takeover
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 專案定位
# ---------------------------------------------------------------------------

def find_repo_root(start: Path) -> Path | None:
    """從自己的位置往上找 .forseti/，找到就是 repo 根。

    不用 cwd，因為 cwd 會隨呼叫者變。用檔案自己的位置往上找，
    這樣 repo 搬到哪它就跟到哪 —— 跟 hooks/forseti-hook.mjs 的
    insideRepo() 同一個做法，理由也一樣。
    """
    for parent in [start, *start.parents]:
        if (parent / ".forseti").is_dir():
            return parent
    return None


CONTROL_FILES = {
    "NORTH_STAR.md": "北極星、不變量、非目標",
    "PHASE_STATUS.md": "現在在哪一階、出口條件、已有與缺少的證據",
    "DECISION_LEDGER.md": "已接受的決策與被否決的替代方案",
    "BLOCKERS.md": "阻塞項與它們擋住什麼",
    "REQUIRED_READING.md": "必讀清單與讀取狀態",
}

ENTRY_DOCS = {
    "soul.md": "我是誰、北極星、她糾正過的七個時刻",
    "bible.md": "怎麼做事，每條附誕生的事故",
    "docs/build-plan.md": "現在做什麼、不做什麼、為什麼",
}


@dataclass
class Finding:
    """一條發現。level 只有三種，刻意不做更細的分級。"""

    level: str  # OK / MISSING / WARN
    what: str
    detail: str = ""


@dataclass
class Report:
    root: Path
    findings: list[Finding] = field(default_factory=list)
    north_star: str | None = None
    phase: str | None = None
    phase_state: str | None = None
    blockers: list[str] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    gates: list[str] = field(default_factory=list)

    def add(self, level: str, what: str, detail: str = "") -> None:
        self.findings.append(Finding(level, what, detail))

    @property
    def missing(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "MISSING"]


# ---------------------------------------------------------------------------
# 讀控制檔
# ---------------------------------------------------------------------------

def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def extract_north_star(text: str) -> str | None:
    """抓 NORTH_STAR.md 裡「## 北極星」底下第一段引文。

    用結構抓（標題 + 引文標記），不做語意判斷。抓不到就回 None，
    讓呼叫端報缺，不要猜一句話填進去。
    """
    m = re.search(r"^##\s*北極星\s*$(.*?)^##", text, re.M | re.S)
    section = m.group(1) if m else text
    quoted = [
        line.lstrip("> ").strip()
        for line in section.splitlines()
        if line.strip().startswith(">")
    ]
    if not quoted:
        return None
    # 引文可能跨行，接起來但保留句子邊界
    return " ".join(q for q in quoted if q)


def extract_phase(text: str) -> tuple[str | None, str | None]:
    """抓 PHASE_STATUS.md 的「現在在哪一階」。

    回傳 (階段名, 狀態)。抓不到回 (None, None)。
    """
    m = re.search(r"^##\s*現在在哪一階\s*$(.*?)(?:^##|\Z)", text, re.M | re.S)
    if not m:
        return None, None
    body = m.group(1).strip()
    if not body:
        return None, None
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    name = re.sub(r"[*`]", "", first)
    state = None
    sm = re.search(r"`([A-Z_]+)`", first)
    if sm:
        state = sm.group(1)
        name = name.replace(sm.group(1), "").strip()
    name = re.sub(r"\s*狀態\s*$", "", name).strip()
    return (name or None), state


def extract_blockers(text: str) -> list[str]:
    """抓 BLOCKERS.md 裡每個 B-xx 標題與它擋住什麼。"""
    out: list[str] = []
    for m in re.finditer(
        r"^##\s*(B-\d+)[　\s]+(.+?)\s*$(.*?)(?=^##|\Z)", text, re.M | re.S
    ):
        bid, title, body = m.group(1), m.group(2).strip(), m.group(3)
        blocks = re.search(r"\*\*擋住：\*\*\s*(.+?)(?:\n\n|\Z)", body, re.S)
        detail = " ".join(blocks.group(1).split()) if blocks else ""
        out.append(f"{bid} {title}" + (f" — 擋住 {detail}" if detail else ""))
    return out


def _table_rows(text: str, heading_pattern: str) -> list[list[str]]:
    """抓某個標題底下第一張表格的資料列。

    用標題界定範圍，因為 REQUIRED_READING.md 裡有兩張表：一張是文件的
    讀取狀態，一張是各階段的補讀門檻。混在一起會把「階段 1」當成一份文件。
    """
    m = re.search(heading_pattern + r"(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not m:
        return []
    rows: list[list[str]] = []
    for line in m.group(1).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3 or all(set(c) <= set("-: ") for c in cells):
            continue
        rows.append(cells)
    return rows


def extract_unread(text: str) -> list[str]:
    """從「## 源頭文件」那張表抓還沒讀完的文件。

    結構比對不是語意判斷：那張表格式固定，第三欄是讀取狀態。
    「完整」或空白算讀完，其餘算沒讀完。
    """
    out: list[str] = []
    for cells in _table_rows(text, r"^##\s*源頭文件\s*$"):
        name, status = cells[0], cells[2]
        if name.startswith("文件"):
            continue
        if "完整" in status or status in ("—", ""):
            continue
        out.append(f"{name}：{status.replace('**', '')}")
    return out


def extract_gates(text: str) -> list[str]:
    """從「補讀門檻」那張表抓還沒達標的階段。"""
    out: list[str] = []
    for cells in _table_rows(text, r"^##\s*.*補讀門檻\s*$"):
        stage, need, state = cells[0], cells[1], cells[2]
        if stage.startswith("要動哪一階"):
            continue
        if "未達標" in state or "未讀" in state:
            out.append(f"{stage}：需要 {need}（{state.replace('**', '')}）")
    return out


def build_report(root: Path) -> Report:
    rep = Report(root=root)
    fdir = root / ".forseti"

    for name, purpose in CONTROL_FILES.items():
        path = fdir / name
        text = read_text(path)
        if text is None:
            rep.add("MISSING", f".forseti/{name}", purpose)
            continue
        rep.add("OK", f".forseti/{name}")

        if name == "NORTH_STAR.md":
            rep.north_star = extract_north_star(text)
            if not rep.north_star:
                rep.add("WARN", "NORTH_STAR.md 裡找不到「## 北極星」底下的引文")
        elif name == "PHASE_STATUS.md":
            rep.phase, rep.phase_state = extract_phase(text)
            if not rep.phase:
                rep.add("WARN", "PHASE_STATUS.md 裡找不到「## 現在在哪一階」")
        elif name == "BLOCKERS.md":
            rep.blockers = extract_blockers(text)
        elif name == "REQUIRED_READING.md":
            rep.unread = extract_unread(text)
            rep.gates = extract_gates(text)

    for rel, purpose in ENTRY_DOCS.items():
        if not (root / rel).is_file():
            rep.add("MISSING", rel, purpose)
        else:
            rep.add("OK", rel)

    goal = fdir / "goal.json"
    if goal.is_file():
        try:
            data = json.loads(goal.read_text(encoding="utf-8"))
            ns = data.get("north_star")
            if ns and rep.north_star and ns not in rep.north_star:
                rep.add(
                    "WARN",
                    "goal.json 的 north_star 與 NORTH_STAR.md 不一致",
                    f"goal.json 寫的是「{ns}」。注意 goal.json 那句是 scope 定義，"
                    "不是北極星本身，兩者本來就可以不同 —— 但要知道自己在用哪一個。",
                )
        except (OSError, json.JSONDecodeError) as exc:
            rep.add("WARN", ".forseti/goal.json 讀不了", str(exc))

    return rep


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------

MARK = {"OK": "  ", "WARN": " ! ", "MISSING": " ✗ "}


def cmd_doctor(rep: Report) -> int:
    print()
    print(f"  專案根目錄　{rep.root}")
    print()

    print("  北極星")
    if rep.north_star:
        for line in re.split(r"(?<=。)", rep.north_star):
            if line.strip():
                print(f"    {line.strip()}")
    else:
        print("    讀不到。這代表接手的人不知道這個專案要幹嘛。")
    print()

    print("  當前階段")
    if rep.phase:
        print(f"    {rep.phase}" + (f"　{rep.phase_state}" if rep.phase_state else ""))
    else:
        print("    讀不到。")
    print()

    if rep.unread:
        print(f"  源頭文件沒讀完　{len(rep.unread)} 份")
        for u in rep.unread:
            print(f"    · {u}")
        print()

    if rep.gates:
        print(f"  補讀門檻未達標　{len(rep.gates)} 階")
        for g in rep.gates:
            print(f"    · {g}")
        print("    這幾階現在不准動，先補讀。")
        print()

    if rep.blockers:
        print(f"  阻塞　{len(rep.blockers)} 項")
        for b in rep.blockers:
            print(f"    · {b}")
        print()

    print("  檔案")
    for f in rep.findings:
        if f.level == "OK":
            continue
        print(f"  {MARK[f.level]}{f.what}")
        if f.detail:
            print(f"      {f.detail}")
    ok_count = sum(1 for f in rep.findings if f.level == "OK")
    print(f"      （另有 {ok_count} 項正常，未列出）")
    print()

    if rep.missing:
        print(f"  結論：缺 {len(rep.missing)} 份必要檔案，這個專案還不能接手。")
        print()
        return 1

    print("  結論：控制檔齊全。接手前請先讀 soul.md 與 bible.md，")
    print("  然後跑 `forseti gate takeover` 確認自己真的讀懂了。")
    print()
    return 0


def cmd_status(rep: Report) -> int:
    print()
    print(f"  {rep.phase or '階段未知'}" + (f"　{rep.phase_state}" if rep.phase_state else ""))
    print(f"  阻塞 {len(rep.blockers)}　文件未讀完 {len(rep.unread)}　門檻未達標 {len(rep.gates)}　缺檔 {len(rep.missing)}")
    print()
    return 0 if not rep.missing else 1


# ---------------------------------------------------------------------------
# 接管測試
# ---------------------------------------------------------------------------
#
# 題目必須來自她實際糾正過的地方，不能是我編的。編出來的題目就是校規，
# 讀完照答一樣空的。這六題全部對應 soul.md 第三節那七個時刻。

TAKEOVER_QUESTIONS = [
    (
        "北極星是什麼？",
        "goal.json 裡那句「聚焦完成 Forseti」不是北極星，那是 scope 定義。"
        "北極星在 .forseti/NORTH_STAR.md。",
    ),
    (
        "源頭文件有幾份？你讀完幾份？",
        "九份，在 ~/Dropbox/My project/Forseti Agent Runtime/。"
        "讀取狀態在 .forseti/REQUIRED_READING.md。"
        "不准 grep 找答案再說讀過了。",
    ),
    (
        "src/ 底下那 40 個模組是什麼性質？",
        "離線分析工具，事後拿 transcript 跑，不是 daemon。"
        "這是性質差異不是完成度差異。",
    ),
    (
        "哪一類訊號不得單獨產生 finding？為什麼？",
        "字串比對類。40 個 healthy session 實測每千則命中 242 次、40/40 全中，"
        "而且假陽性有一類方向是反的：誠實區分「驗過的」與「沒驗的」會命中更多次。",
    ),
    (
        "照妖鏡與 Context Token Monitor 在哪裡？",
        "在 Code Duo。要接不要重寫，見 DECISION_LEDGER 的 ADR-002。",
    ),
    (
        "動手寫程式之前要先做什麼？",
        "先講清楚四件事：知道了什麼、想改什麼、為何要改、核心原因是什麼。"
        "見 bible.md 的 T-01。",
    ),
]


def cmd_gate_takeover(rep: Report) -> int:
    print()
    print("  接管測試")
    print()
    print("  這六題不是考試，是攔截。2026-09-08 有一個 session 讀了九份文件")
    print("  裡的一份就開始寫程式，走偏兩小時。這個閘門就是為了那件事存在。")
    print()
    print("  答不出來的，去讀對應的檔案再回來。")
    print()
    for i, (q, where) in enumerate(TAKEOVER_QUESTIONS, 1):
        print(f"  {i}. {q}")
        print(f"     答案在：{where}")
        print()

    if rep.missing:
        print(f"  ✗ 缺 {len(rep.missing)} 份控制檔，這個閘門現在無效。")
        print()
        return 1

    print("  這個版本只列題目與出處，不驗證答案。")
    print("  驗證需要把答案存進帳本再比對，那是階段 1 之後的事。")
    print("  在那之前，這個閘門靠的是讀的人自己誠實。")
    print()
    return 0


def main(argv: list[str]) -> int:
    root = find_repo_root(Path(__file__).resolve().parent)
    if root is None:
        print("找不到 .forseti/，這裡不是 Forseti 專案。", file=sys.stderr)
        return 2

    rep = build_report(root)
    cmd = argv[1] if len(argv) > 1 else "doctor"

    if cmd == "doctor":
        return cmd_doctor(rep)
    if cmd == "status":
        return cmd_status(rep)
    if cmd == "gate" and len(argv) > 2 and argv[2] == "takeover":
        return cmd_gate_takeover(rep)

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
