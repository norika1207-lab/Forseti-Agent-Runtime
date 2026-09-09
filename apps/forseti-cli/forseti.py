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
    python3 apps/forseti-cli/forseti.py context [--all|<path.jsonl>]
    python3 apps/forseti-cli/forseti.py index [--rebuild]
    python3 apps/forseti-cli/forseti.py recall "為何會有點名板"
    python3 apps/forseti-cli/forseti.py tasks

執行連續性（F03-F06）：
    python3 apps/forseti-cli/forseti.py dispatch <step> <worker> [理由]
    python3 apps/forseti-cli/forseti.py auto <task> <worker> [理由]
    python3 apps/forseti-cli/forseti.py drain <task> <worker>
    python3 apps/forseti-cli/forseti.py event <kind> <step> <理由> [worker]
    python3 apps/forseti-cli/forseti.py verify <step>
    python3 apps/forseti-cli/forseti.py continuity <task>

跨 session 派工（B-09）：
    python3 apps/forseti-cli/forseti.py handoff <task> <local_id> <worker>
    python3 apps/forseti-cli/forseti.py handoff --new <worker> "目標" [verifier]
    python3 apps/forseti-cli/forseti.py watch

handoff 先把步驟登記進帳本再產出要送的訊息，watch 一次掃完所有
進行中的步驟。原本的做法是直接送 SendMessage，那條路徑在帳本外面，
於是 worker 對 watchdog 而言不存在，死了十七小時沒有人知道。
watch 有可疑項時回傳 1，可以直接掛進排程。

這六個先前只存在於 Python API 裡，沒有 CLI 入口。結果是
auto_dispatch() 寫好也測過，卻從來沒有被真正的工作呼叫過一次，
continuity 分數長期是 0 —— 不是機制不會動，是沒有門可以進去。
一個沒有入口的機制等於不存在。
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
    """抓 BLOCKERS.md 裡每個 B-xx 標題與它擋住什麼。

    只算「已解除」那個一級標題之前的。BLOCKERS.md 開頭自己寫著
    「擋不住任何東西的不叫阻塞」,所以解除的不該還算進數字裡 ——
    doctor 報「9 項阻塞」而其中一項已經解除,那個數字是假的。

    解除的仍然留在檔案裡,因為「怎麼驗掉的」比「它曾經擋住什麼」有用。
    """
    text = re.split(r"^#\s*已解除\s*$", text, maxsplit=1, flags=re.M)[0]
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

    判準是 Level 欄（Vol2 §4 的七級量表）：level 5 逐段完整讀過的不算未讀，
    5 以下都算。level 6 要通過 challenge，現在的閘門做不到（B-08），
    所以任何文件目前最高只能到 5。

    2026-09-09 這裡壞過一次：REQUIRED_READING 的表加了 Level 欄，
    這個函式還在抓第三欄，於是把 level 5 讀完的也列成「沒讀完」，
    而且顯示的是一個孤零零的數字。16 條測試全過，因為它們檢查的是
    表格結構不是語意。修法是改抓 Level 欄，並加一條語意測試守著。
    """
    out: list[str] = []
    for cells in _table_rows(text, r"^##\s*源頭文件\s*$"):
        if len(cells) < 4:
            continue
        name, level, status = cells[0], cells[2].strip(), cells[3]
        if name.startswith("文件"):
            continue
        try:
            lv = int(re.sub(r"\D", "", level) or -1)
        except ValueError:
            continue
        if lv < 0 or lv >= 5:
            continue
        out.append(f"{name}：level {lv}，{status.replace('**', '')}")
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

    try:
        led_mod = _sibling("ledger")
        if led_mod.default_db().exists():
            led = led_mod.Ledger()
            n = led.total_unfinished()
            # 有人正在替這個專案做事的話，接手的人第一眼就該看到。
            # B-09 那次十七小時，失敗的不是偵測，是沒有人想到要問一次。
            # 所以這一段不等人問，doctor 一跑就講。
            active = led.active_steps()
            led.close()
            if n:
                print(f"  未完成的義務　{n} 項　（`forseti tasks` 看細節）")
                print()
            if active:
                print(f"  有人正在做事　{len(active)} 步")
                for s in active[:5]:
                    who = s["worker"] or "沒有負責人"
                    print(f"    · {who}　{_fmt_age(s['idle_sec'])}沒動靜"
                          f"　{s['objective'][:34]}")
                if len(active) > 5:
                    print(f"    …另外 {len(active) - 5} 步")
                print("    這些是別的 session 在跑的。`forseti watch` 會判斷它們還活著沒。")
                print()
    except Exception:
        # 帳本壞掉不該讓 doctor 整個掛掉。doctor 的價值在於它一定跑得起來。
        pass

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


# ---------------------------------------------------------------------------
# Context 佔用
# ---------------------------------------------------------------------------
#
# 實作在 context_meter.py，那邊有自己的約束說明。這裡只負責轉接。
# 分開的理由：forseti.py 的約束是「只讀控制檔」，而 context 讀的是
# ~/.claude/projects 底下的 jsonl，來源不同、失效方式也不同，混在一起
# 會讓「這個指令讀不到東西」變成兩種完全不同的意思。

def _sibling(name: str):
    """載入同目錄的模組。從別的 cwd 呼叫時 sys.path 不一定含得到這裡。"""
    import importlib
    try:
        return importlib.import_module(name)
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        return importlib.import_module(name)


def cmd_context(args: list[str]) -> int:
    return _sibling("context_meter").main(["context_meter", *args])


def cmd_index(args: list[str]) -> int:
    return _sibling("recall").main(["recall", "index", *args])


def cmd_recall(args: list[str]) -> int:
    if not args:
        print("要問什麼？　forseti recall \"為何會有點名板\"", file=sys.stderr)
        return 2
    return _sibling("recall").main(["recall", *args])


def cmd_tasks(args: list[str]) -> int:
    """未完成的義務。F02 §6 的 obligation ledger。

    CT-F02-02 要求十四個未完成項目要被自動暴露,不需要使用者盤問。
    這個指令就是「不需要盤問」的具體形式。
    """
    led_mod = _sibling("ledger")
    db = led_mod.default_db()
    if not db.exists() or db.stat().st_size == 0:
        print()
        print("  還沒有任務帳本。")
        print(f"  它會建在 {db}")
        print("  帳本存在的理由:義務只活在模型記憶裡的話,回合結束就散了。")
        print()
        return 0

    led = led_mod.Ledger()
    o = led.obligations()
    total = led.total_unfinished()
    print()
    if total == 0:
        print("  沒有未完成的義務。")
        print()
        return 0

    print(f"  未完成　{total} 項")
    print()
    for t in o["unfinished_tasks"]:
        print(f"  {t['task_id']}　{t['state']}　{t['objective']}")
        if t["next"]:
            print(f"      下一步　{t['next']}")
    if o["unfinished_steps"]:
        print()
        print(f"  未完成步驟　{len(o['unfinished_steps'])} 個")
        for st in o["unfinished_steps"][:20]:
            print(f"    {st['state']:<20}{st['objective']}")
        if len(o["unfinished_steps"]) > 20:
            print(f"    …另外 {len(o['unfinished_steps']) - 20} 個")
    if o["blocked"]:
        print()
        print(f"  卡住　{len(o['blocked'])} 項")
        for b in o["blocked"]:
            print(f"    {b['objective']}")
    if o["unverified_claims"]:
        print()
        print(f"  宣稱完成但沒有證據　{len(o['unverified_claims'])} 項")
        for u in o["unverified_claims"]:
            print(f"    {u['objective']}")
    if o["orphans"]:
        print()
        print(f"  沒有負責人　{len(o['orphans'])} 項")
        for x in o["orphans"]:
            print(f"    {x['objective']}")
    print()
    led.close()
    return 0


# ---------------------------------------------------------------------------
# 執行連續性（F03-F06）的 CLI 入口
# ---------------------------------------------------------------------------

def _open_ledger():
    """開帳本。沒有帳本就講清楚它會建在哪，不要噴 traceback。"""
    led_mod = _sibling("ledger")
    db = led_mod.default_db()
    if not db.exists() or db.stat().st_size == 0:
        print()
        print("  還沒有任務帳本。")
        print(f"  它會建在 {db}")
        print()
        return None, None
    return led_mod, led_mod.Ledger()


def _resolve_step(led, ref: str) -> str | None:
    """接受完整 step_id，也接受 `<task>/<local>`。找不到就回 None。"""
    row = led.con.execute("SELECT step_id FROM steps WHERE step_id=?", (ref,)).fetchone()
    if row:
        return row[0]
    rows = led.con.execute(
        "SELECT step_id FROM steps WHERE step_id LIKE ?", (f"%/{ref}",)).fetchall()
    if len(rows) == 1:
        return rows[0][0]
    if len(rows) > 1:
        print(f"  {ref} 對到 {len(rows)} 個步驟，請用完整 step_id：")
        for r in rows:
            print(f"    {r[0]}")
    return None


def cmd_dispatch(args: list[str]) -> int:
    """手動派工。這一次會被記成非自動，指標上算 owner 推了一把。"""
    if len(args) < 2:
        print("用法：forseti.py dispatch <step> <worker> [理由]", file=sys.stderr)
        return 2
    led_mod, led = _open_ledger()
    if led is None:
        return 1
    try:
        step = _resolve_step(led, args[0])
        if step is None:
            print(f"  找不到步驟：{args[0]}")
            return 1
        led.dispatch(step, args[1], " ".join(args[2:]))
        print(f"  已派　{step}　→　{args[1]}")
        print("  這一次記為手動。自動接上的請用 auto 或 drain。")
        return 0
    finally:
        led.close()


def cmd_auto(args: list[str]) -> int:
    """自動派下一步。派不動時要講出卡在哪一個條件。

    auto_dispatch() 回 None 有三種意思，這裡把三種分開講。安靜的 None
    正是這整套東西要消滅的東西：使用者不該從「沒反應」去推發生什麼事。
    """
    if len(args) < 2:
        print("用法：forseti.py auto <task> <worker> [理由]", file=sys.stderr)
        return 2
    led_mod, led = _open_ledger()
    if led is None:
        return 1
    task, worker = args[0], args[1]
    try:
        if not led.state_of(task):
            print(f"  找不到任務：{task}")
            return 1
        nxt = led.auto_dispatch(task, worker, " ".join(args[2:]))
        print()
        if nxt is not None:
            print(f"  已自動派　{nxt['local_id']}　{nxt['objective']}")
            print(f"  給　{worker}")
            print("  沒有人需要說「繼續」。")
            print()
            return 0

        state = led.state_of(task)
        if led_mod.is_terminal(state):
            print(f"  任務已終止（{state}），不再派工。")
        elif state == "NEEDS_HUMAN":
            nx = led.next_step(task)
            print("  停在這裡等你決定，不是卡住：")
            if nx:
                print(f"    {nx['local_id']}　{nx['objective']}")
            print("  這是 NEEDS_HUMAN，看得見的狀態，不是安靜的沒反應。")
        elif led.next_step(task) is None:
            print("  沒有可派的下一步。可能全部完成，或前面的步驟還沒驗證通過。")
            print("  用 tasks 看未完成的義務。")
        else:
            print(f"  沒有派工。任務目前是 {state}。")
        print()
        return 0
    finally:
        led.close()


def cmd_drain(args: list[str]) -> int:
    """一路派到派不動為止。F04 §2 那條鏈跑完，中間不需要有人說話。"""
    if len(args) < 2:
        print("用法：forseti.py drain <task> <worker>", file=sys.stderr)
        return 2
    led_mod, led = _open_ledger()
    if led is None:
        return 1
    try:
        if not led.state_of(args[0]):
            print(f"  找不到任務：{args[0]}")
            return 1
        done = led.drain(args[0], args[1])
        print()
        if not done:
            print("  一步都沒派出去。用 auto 看是卡在哪一個條件。")
        else:
            states = {s["step_id"]: s["state"] for s in led.steps_of(args[0])}
            print(f"  自動走了 {len(done)} 步：")
            for d in done:
                print(f"    {d['local_id']}　{d['objective']}　"
                      f"{states.get(d['step_id'], '')}")
        print()
        return 0
    finally:
        led.close()


def cmd_event(args: list[str]) -> int:
    """記一筆 worker 事件。只收 F04 §3 那八種。"""
    led_mod, led = _open_ledger()
    if led is None:
        return 1
    try:
        if len(args) < 3:
            print("用法：forseti.py event <kind> <step> <理由> [worker]", file=sys.stderr)
            print(f"合法的 kind：{'　'.join(led_mod.WORKER_EVENTS)}", file=sys.stderr)
            return 2
        step = _resolve_step(led, args[1])
        if step is None:
            print(f"  找不到步驟：{args[1]}")
            return 1
        try:
            fresh = led.worker_event(args[0], step, args[2],
                                     worker=args[3] if len(args) > 3 else "")
        except ValueError as e:
            print(f"  {e}")
            return 2
        print(f"  已記　{args[0]}" if fresh else f"  重複事件，已被冪等擋下　{args[0]}")
        return 0
    finally:
        led.close()


def cmd_verify(args: list[str]) -> int:
    """跑一個步驟的 verifier。真的去看磁碟，不看模型怎麼說。"""
    if not args:
        print("用法：forseti.py verify <step>", file=sys.stderr)
        return 2
    led_mod, led = _open_ledger()
    if led is None:
        return 1
    try:
        step = _resolve_step(led, args[0])
        if step is None:
            print(f"  找不到步驟：{args[0]}")
            return 1
        ok, results = led.verify_step(step)
        print()
        for r in results:
            print(f"  {'通過' if r.ok else '沒過'}　{r.spec}")
            if r.detail:
                print(f"        {r.detail}")
        if not results:
            print("  這一步沒有 verifier，所以沒有東西可以驗。")
        print()
        print("  驗過了。" if ok else "  沒有全過，步驟退回 RUNNING。")
        print()
        return 0 if ok else 1
    finally:
        led.close()


def cmd_continuity(args: list[str]) -> int:
    """F06 §5 的兩個指標。從事件算，不是從印象算。"""
    if not args:
        print("用法：forseti.py continuity <task>", file=sys.stderr)
        return 2
    led_mod, led = _open_ledger()
    if led is None:
        return 1
    try:
        if not led.state_of(args[0]):
            print(f"  找不到任務：{args[0]}")
            return 1
        c = led.continuity(args[0])
        print()
        print(f"  自動接上　{c['auto_continued']} / {c['expected_continuation']}")
        print(f"  連續性分數　{c['score']}")
        print(f"  人必須說繼續　{c['human_continue_burden']} 次　{c['burden_verdict']}")
        if c["violations"]:
            print(f"  不合法的停止　{c['violations']} 次")
        print()
        if c["expected_continuation"] and c["auto_continued"] == 0:
            print("  分數是 0 而且該接的地方有 "
                  f"{c['expected_continuation']} 處，代表每一次都是有人推的。")
            print()
        return 0
    finally:
        led.close()


def _fmt_age(sec: float) -> str:
    if sec < 90:
        return f"{int(sec)} 秒"
    if sec < 5400:
        return f"{sec / 60:.0f} 分"
    if sec < 172800:
        return f"{sec / 3600:.1f} 小時"
    return f"{sec / 86400:.1f} 天"


def cmd_watch(args: list[str]) -> int:
    """巡檢所有進行中的步驟。一個指令看全部，不是記得看某一個。

    B-09：2026-09-08 一個 worker 死了十七小時沒人知道。watchdog 會動，
    但要有人記得對那個 step 呼叫它。這個指令把「記得」換成「掃過」。

    回傳 1 代表有可疑的，這樣它可以直接掛進 cron 或 hook。
    """
    led_mod, led = _open_ledger()
    if led is None:
        return 1
    try:
        steps = led.active_steps()
        print()
        if not steps:
            print("  沒有進行中的步驟。")
            print()
            return 0

        print(f"  進行中　{len(steps)} 步")
        print()
        suspect = []
        for s in steps:
            a = led.check_liveness(s["step_id"])
            mark = "！" if a.suspect else "　"
            who = s["worker"] or "沒有負責人"
            print(f"  {mark} {s['local_id']:<10}{s['state']:<12}"
                  f"{_fmt_age(s['idle_sec']):>8} 沒動靜　{who}")
            print(f"      {s['objective'][:56]}")
            if a.suspect:
                suspect.append((s, a))
        print()

        if not suspect:
            print("  沒有可疑的。")
            print()
            return 0

        print(f"  可疑　{len(suspect)} 步")
        print()
        for s, a in suspect:
            rung = led.recover(s["step_id"], unresponsive_count=s["retry_count"])
            print(f"  {s['local_id']}　風險 {a.risk:.3f}")
            print(f"      {a.why}")
            print(f"      下一階　{rung}")
        print()
        print("  風險是四個因子相乘的結果，不是計時器。")
        print("  任何一個因子接近 0 就足以洗掉懷疑，所以被標出來的")
        print("  代表四個條件同時成立，不是「只是有點久」。")
        print()
        return 1
    finally:
        led.close()


def _handoff_message(led, step_id: str, task_id: str) -> str:
    """給 worker 的訊息。帶著它回報所需的一切。

    刻意寫成可以直接貼進 SendMessage 的形狀。CLI 送不了訊息（那是
    Claude 的工具，shell 呼叫不到），所以它只做登記與產文，不假裝
    自己能送。
    """
    st = next((x for x in led.steps_of(task_id) if x["step_id"] == step_id), None)
    row = led.con.execute("SELECT objective FROM tasks WHERE task_id=?",
                          (task_id,)).fetchone()
    cli = str(Path(__file__).resolve())
    repo = Path(__file__).resolve().parents[2]
    lines = [
        f"任務　{row[0] if row else task_id}",
        f"這一步　{st['objective'] if st else ''}",
        "",
        f"repo　{repo}",
        f"step_id　{step_id}",
        "",
        "這一步已經登記在帳本裡，所以你的狀態看得見，"
        "你不回話超過一段時間會被巡檢標出來。這對你有利：",
        "你死掉的話有人會知道，而不是等十七小時。",
        "",
        "開始做之前先回報一次，之後有進展就回報：",
        f'  python3 "{cli}" event WORKER_ACCEPTED {step_id} "接下了"',
        f'  python3 "{cli}" event WORKER_PROGRESS {step_id} "做到哪裡"',
        "",
        "卡住不要沉默，卡住也是一種要回報的狀態：",
        f'  python3 "{cli}" event WORKER_BLOCKED {step_id} "被什麼擋住"',
        "",
        "做完之後跑驗證。驗證是真的去看磁碟，不是你說了算：",
        f'  python3 "{cli}" verify {step_id}',
    ]
    if st and st["expected_outputs"]:
        lines += ["", "要產出的東西："] + [f"  {o}" for o in st["expected_outputs"]]
    if st and st["verifier"]:
        lines += ["", "會這樣驗你："] + [f"  {v}" for v in st["verifier"]]
    return "\n".join(lines)


def cmd_handoff(args: list[str]) -> int:
    """跨 session 派工。先登記帳本，再產出要送的訊息。

    B-09 的解法。原本的做法是直接送 SendMessage，那條路徑完全在帳本
    外面，於是 worker 對 watchdog 而言不存在。

    兩種用法：
        handoff <task> <local_id> <worker>              派一個已存在的步驟
        handoff --new <worker> "目標" [verifier ...]     開一個單步任務並派出去
    """
    led_mod, led = _open_ledger()
    if led is None:
        return 1
    try:
        if args and args[0] == "--new":
            if len(args) < 3:
                print('用法：forseti.py handoff --new <worker> "目標" [verifier ...]',
                      file=sys.stderr)
                print('verifier 形式：file:<路徑> 或 cmd:<指令>', file=sys.stderr)
                return 2
            worker, objective, verifiers = args[1], args[2], list(args[3:])
            step = led_mod.Step("s1", objective, verifier=verifiers,
                                expected_outputs=[v[5:] for v in verifiers
                                                  if v.startswith("file:")])
            task = led.accept(objective, [step],
                              definition_of_done=verifiers or ["（沒有給驗證條件）"],
                              accepted_by="controller")
            led.transition(task, "RUNNING", f"派給 {worker}", actor="controller")
            step_id = led.sid(task, "s1")
        else:
            if len(args) < 3:
                print("用法：forseti.py handoff <task> <local_id> <worker>",
                      file=sys.stderr)
                return 2
            task, local, worker = args[0], args[1], args[2]
            if not led.state_of(task):
                print(f"  找不到任務：{task}")
                return 1
            step_id = led.sid(task, local)
            if not led.con.execute("SELECT 1 FROM steps WHERE step_id=?",
                                   (step_id,)).fetchone():
                print(f"  找不到步驟：{local}")
                return 1

        led.dispatch(step_id, worker, f"跨 session 派給 {worker}")

        print()
        print(f"  已登記　{step_id}")
        print(f"  負責人　{worker}")
        print()
        print("  watchdog 現在看得到它了。忘記它也沒關係，")
        print("  用 watch 會把它掃出來。")
        print()
        print("  ── 以下貼給 worker ──")
        print()
        print(_handoff_message(led, step_id, task))
        print()
        return 0
    finally:
        led.close()


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
    if cmd == "context":
        return cmd_context(argv[2:])
    if cmd == "index":
        return cmd_index(argv[2:])
    if cmd == "recall":
        return cmd_recall(argv[2:])
    if cmd == "tasks":
        return cmd_tasks(argv[2:])
    if cmd == "dispatch":
        return cmd_dispatch(argv[2:])
    if cmd == "auto":
        return cmd_auto(argv[2:])
    if cmd == "drain":
        return cmd_drain(argv[2:])
    if cmd == "event":
        return cmd_event(argv[2:])
    if cmd == "verify":
        return cmd_verify(argv[2:])
    if cmd == "continuity":
        return cmd_continuity(argv[2:])
    if cmd == "watch":
        return cmd_watch(argv[2:])
    if cmd == "handoff":
        return cmd_handoff(argv[2:])

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
