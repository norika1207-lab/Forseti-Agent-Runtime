#!/usr/bin/env python3
"""Forseti CLI.

階段 0 的交付。它存在的理由很具體：2026-09-08 那個 session 花了兩小時
讀文件拼湊現況，然後走偏。如果當時有這個指令，第一輪就會知道要讀九份
不是一份、工程書指定 Python、照妖鏡在 Code Duo。

設計約束（階段 0 明令）：

  只讀檔案，不做判斷。這裡沒有 detector，沒有分數，沒有語意分析。
  它報告的每一個字都能在 .forseti/ 底下找到出處。

  零依賴。標準庫而已。**這條 2026-09-10 由 ADR-009 定案成長期政策，
  不再是「階段 1 再裝」的暫緩。** 最重的理由是 doctor 必須一定跑得起來：
  接手的人通常是在別人卡住之後才來的，那個時候不該卡在 pip install。

  拿不到就說拿不到。缺一份控制檔就報缺，不用預設值填補，
  因為填補會讓一個沒設定好的專案看起來完全正常。

用法：
    python3 apps/forseti-cli/forseti.py doctor
    python3 apps/forseti-cli/forseti.py status
    python3 apps/forseti-cli/forseti.py gate takeover
    python3 apps/forseti-cli/forseti.py antianchor open
    python3 apps/forseti-cli/forseti.py metric [list|show|template|register]
    python3 apps/forseti-cli/forseti.py attempt [list|show|template|record|release]
    python3 apps/forseti-cli/forseti.py evidence [list|levels|template|register|show]
    python3 apps/forseti-cli/forseti.py pollution [list|show|template|register|advance]
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
    python3 apps/forseti-cli/forseti.py handoff --no-shell ...   worker 只能寫檔案
    python3 apps/forseti-cli/forseti.py watch

事件帳本（階段 1，Event Ledger，跟上面的 tasks 是兩本不同的帳）：
    python3 apps/forseti-cli/forseti.py events
    python3 apps/forseti-cli/forseti.py replay [session]
    python3 apps/forseti-cli/forseti.py reindex

ADR-008 定案兩本分開。Task Ledger 記「誰接了什麼、還欠什麼」,
Event Ledger 記「AI 與 runtime 實際發生了什麼」。兩邊都有 events,
講的時候一律說是哪一本的。

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
    # 不是給人從頭讀的,是查的。列在這裡的理由是它被刪掉要有人知道 ——
    # 十條同名不同義,每一條接錯都不會報錯,只會安靜地顯示錯的東西。
    "docs/glossary.md": "同一個詞在哪份文件裡是什麼意思（B-11）",
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
    # 放在 `# 已解除` 底下、本文卻還寫著擋住什麼的那幾條。
    # **不併進 `blockers`**,那樣等於替 owner 挑了一邊。
    # `None` 是「數不出來」,空 list 是「真的沒有」,兩件事。
    misfiled: list[str] | None = None
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


def extract_misfiled(text: str) -> list[str] | None:
    """抓「被上面那一支切掉，本文卻還寫著擋住什麼」的那幾條。

    `extract_blockers` 在 `# 已解除` 那一行把檔案切掉,所以放在那底下的
    不進阻塞數。多數時候那是對的 —— 解除的本來就不該算。可是一條被搬到
    已解除區、本文還寫著它擋住某個具體交付的,在這裡直接消失,
    在 `desktop_api._blockers` 那裡卻是一條乾淨的未解除。
    2026-09-17 實測 doctor 8 條、desktop 11 條,差的是 B-17、B-14、B-13,
    **而兩邊都不報異常**。

    這一支只讓 doctor 講得出自己少算了哪幾條。
    **不改上面那個數字,也不挑邊** —— 挑哪一邊是 owner 的決定,
    B-17 的本文自己就寫著在等她三選一。

    判準不自己定,借 `desktop_api._blockers` 的 `misfiled`。理由是再寫一次
    區段與「擋住：」欄的解析,等於造出第三個會跟前兩個對不上的數字,
    而對不上正是這一支要講出來的那件事。

    借不到的時候回 `None` 不回 `[]`。「數不出來」跟「沒有」是兩件事,
    讓它們長成同一個樣子是這個專案抓過很多次的形狀（見 `_safe` 的檔頭）。
    """
    try:
        return list(_sibling("desktop_api")._blockers(text).get("misfiled") or [])
    except Exception:                           # noqa: BLE001
        return None


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
            rep.misfiled = extract_misfiled(text)
            if rep.misfiled is None:
                rep.add(
                    "WARN",
                    "放錯區段的阻塞數不出來",
                    "借不到 `desktop_api._blockers`，所以講不出上面那個數字"
                    "少算了哪幾條。這不等於 0 條。",
                )
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



def _reading_conformance() -> None:
    """跑 tools/reading-conformance.py 的檢查,把結果印進 doctor。

    整段包在 try 裡:一個檢查器自己壞掉,不該讓 doctor 跟著不能用。
    壞掉的時候要說出來,不是靜靜略過 —— 靜靜略過會讓人以為檢查過了。
    """
    try:
        import importlib.util
        here = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "reading_conformance", here / "tools" / "reading-conformance.py")
        if spec is None or spec.loader is None:
            return
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        r = mod.check()
    except Exception as e:                       # noqa: BLE001
        print(f"  規格閱讀合規　檢查器自己出錯：{type(e).__name__}")
        print()
        return

    if r.get("status") == "CANNOT_CHECK":
        print(f"  規格閱讀合規　無法檢查：{r.get('why', '')}")
        print()
        return

    bad = r.get("bad", 0)
    n = r.get("checked", 0)
    if not bad:
        print(f"  規格閱讀合規　{n} 份全部對得上")
        print("    （驗的是檔案沒變與補讀表有記錄。驗不到「讀了幾行」,")
        print("      那要段落層級的 coverage,見 coverage_gap()）")
    else:
        print(f"  規格閱讀合規　！{bad} / {n} 份不合格")
        for row in r.get("rows") or []:
            if row.get("verdict") != "OK":
                print(f"    · {row.get('id')}　{row.get('verdict')}"
                      f"　{row.get('why', '')}")
        print("    政策原文：" + r.get("policy", ""))
    print()

def _artifact_drift() -> None:
    """交接檔記下的產出雜湊,現在還對不對得上。印進 doctor。

    掛在 doctor 的理由跟 `_reading_conformance()` 同一條:接手的人一定會
    跑 doctor,不一定會想到去跑一支他不知道存在的工具。而這一項正是
    接手的第一秒要知道的 —— `NEXT.md` 上那幾行如果已經過期,
    後面每一個判斷都建在過期的地基上。

    整段包在 try 裡,壞掉要說出來不是靜靜略過。靜靜略過會讓人以為對過了。
    """
    try:
        CT = _sibling("contract")
        d = CT.artifact_drift()
        lines = CT.drift_lines(d)
    except Exception as e:                       # noqa: BLE001
        print(f"  交接檔的產出雜湊　對帳自己出錯：{type(e).__name__}")
        print()
        return
    if not lines:
        return
    print("  交接檔的產出雜湊")
    for ln in lines:
        print(ln)
    print()


def _lineage() -> None:
    """§6.3 的 lineage 邊，此刻有幾條、十條型別裡幾條的兩端指得到。

    掛在 doctor 的理由跟 `_artifact_drift()` 同一條：接手的人會跑
    doctor，不會跑一支他不知道存在的模組。而這一項答的是
    「這個系統追不追得回一個結論是怎麼來的」—— 北極星四個軸
    裡「可驗證」那一軸的地基。

    **0 條邊要印出來，不是不印。** 不印的話這一節在「還沒有邊」
    跟「有邊而且都好」兩種情況下長得一樣。
    """
    try:
        LN = _sibling("lineage")
        lines = LN.lines()
    except Exception as e:                       # noqa: BLE001
        print(f"  lineage 邊　自己出錯：{type(e).__name__}")
        print()
        return
    if not lines:
        return
    print("  lineage 邊（v5.0 §6.3）")
    for ln in lines:
        print(ln)
    print()


def _evidence() -> None:
    """§5 的 Evidence 實體，此刻磁碟上有幾筆、§33.3 的獨立支撐幾個。

    緊接在 `_lineage()` 後面印，理由是它答的是上一節那三條連不起來的邊
    （DERIVED_FROM / VERIFIES / REFUTES）缺的到底是什麼。
    兩節分開讀的話，「evidence 擋住三條」會看起來像一個沒有下一步的狀態。

    **0 筆要印出來。** 實體與儲存在了但沒有人登，跟模組不存在，
    在畫面上長得一樣的話，下一個人會去寫一個已經有的模組 ——
    那正是 2026-09-18 `pol-ce2f84f5b5` 那一筆的機制。
    """
    try:
        EV = _sibling("evidence")
        lines = EV.lines()
    except Exception as e:                       # noqa: BLE001
        print(f"  證據　自己出錯：{type(e).__name__}")
        print()
        return
    if not lines:
        return
    print("  證據（v5.0 §5 Evidence）")
    for ln in lines:
        print(ln)
    print()


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

    # 上面那個數字少算了誰。**不併進去**,也不挑邊 ——
    # 挑哪一邊是 owner 的決定（B-17 的本文自己寫著在等她三選一）。
    if rep.misfiled:
        print(f"  這個數字少算了 {len(rep.misfiled)} 條"
              f"　{'、'.join(rep.misfiled)}")
        print("    它們放在 `# 已解除` 底下，本文卻還寫著擋住什麼。")
        print("    上面那一行在那個標題就把檔案切掉，所以數不到；")
        print("    桌面版那一支不看區段，逐條判本文，所以數得到。")
        print("    同一個檔案同一個問題，兩支程式回不同的數字。")
        print("    要搬回去還是要把本文改成真的解除,是 owner 的決定。")
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

    # 規格閱讀合規。spec_manifest.json 那條 reading_policy 寫著
    # 「full-file required; sampled/title-only reading is non-conformant」,
    # 而在 2026-09-11 之前沒有任何程式在檢查它。
    #
    # 掛在 doctor 而不是獨立跑,理由是接手的人一定會跑 doctor,
    # 不一定會想到去跑一支他不知道存在的工具。
    # 交接檔那幾行雜湊還對不對得上。**接手的第一秒就該知道** ——
    # `NEXT.md` 已經過期的話,後面每個判斷都建在過期的地基上。
    # 先前這件事靠人記得多重產一次交接檔（2026-09-18 那一輪的
    # 「還缺什麼」第一條寫著「沒有東西擋」）,這裡就是那個東西。
    _artifact_drift()
    _lineage()
    _evidence()

    _reading_conformance()

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
    line = (f"  阻塞 {len(rep.blockers)}　文件未讀完 {len(rep.unread)}"
            f"　門檻未達標 {len(rep.gates)}　缺檔 {len(rep.missing)}")
    # 少算的掛在阻塞那個數字旁邊,不另起一行 —— 它講的是同一個數字。
    if rep.misfiled:
        line += f"（阻塞另有 {len(rep.misfiled)} 條放錯區段沒算進去）"
    elif rep.misfiled is None and rep.blockers:
        line += "（放錯區段的數不出來，不是 0）"
    print(line)
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


def _suff():
    return _sibling("sufficiency")


def current_session() -> str:
    """這條線的識別。環境變數優先，否則用最近被寫的那份 transcript。

    權限綁在這個值上，所以它取錯的後果是「別人考過的算到我頭上」。
    環境變數 `FORSETI_SESSION` 是給測試與非 Claude 環境用的逃生口。
    """
    import os
    v = (os.environ.get("FORSETI_SESSION") or "").strip()
    if v:
        return v
    try:
        f = _sibling("tracker").latest_session()
        return f.stem if f else ""
    except Exception:                                        # noqa: BLE001
        return ""


def cmd_gate_takeover(rep: Report) -> int:
    """接管閘門。**這一版真的驗答案。**

    B-08 記的是「閘門攔不住寫程式的人，只列題目不驗答案」。
    `sufficiency.py` 把 v5.0 §17.3 的五個維度接成一份會批改的考卷，
    題目從原文抽，答案不寫進考卷（§39 第 2 步）。

    下面那六題是另一回事:它們來自她實際糾正過的地方，是開放題，
    **系統驗不了**，所以印出來的時候要說清楚哪一半會驗哪一半不會。
    混在一起講就變成另一個「看起來有在把關」。
    """
    S = _suff()
    root = rep.root if hasattr(rep, "root") else Path(__file__).resolve().parents[2]
    sess = current_session()

    print()
    print("  接管測試")
    print()
    print("  這不是考試，是攔截。2026-09-08 有一個 session 讀了九份文件")
    print("  裡的一份就開始寫程式，走偏兩小時。這個閘門就是為了那件事存在。")
    print()

    if rep.missing:
        print(f"  ✗ 缺 {len(rep.missing)} 份控制檔，這個閘門現在無效。")
        print()
        return 1

    st = S.state(root, session=sess)
    print(f"  這條線　{sess or '（認不出來）'}")
    print(f"  現在的權限　{'可以寫' if st['write'] else '唯讀'}　{st['why']}")
    print(f"  強制擋人　{'開' if st['enforced'] else '關（只記錄不擋）'}")
    print()

    exam = S.open_exam(root, session=sess)
    print(f"  考卷　{exam['id']}　{len(exam['questions'])} 題，"
          f"門檻 {exam['threshold']:.0%}，逐維度算")
    print()
    for key, en, zh, _d in S.DIMENSIONS:
        d = exam["dims"].get(key, {})
        state = d.get("state", "")
        if state == "OK":
            print(f"  ● {zh}（{en}）　來源 {d.get('source', '')}")
        else:
            print(f"  ○ {zh}（{en}）　{state}：{d.get('why', '')}")
    print()
    for q in exam["questions"]:
        print(f"  [{q['qid']}] {q['q']}")
    print()
    print("  答案不在這份考卷裡。v5.0 §39 第 2 步:先看到答案再推導，")
    print("  推導出來的就是那個答案。要找依據去讀題目標的那一行原文。")
    print()
    print("  交卷：")
    print(f"    echo '{{\"{exam['questions'][0]['qid'] if exam['questions'] else 'xxx-1'}\": \"...\"}}' | \\")
    print(f"      python3 apps/forseti-cli/forseti.py gate submit {exam['id']}")
    print()
    print("  ── 以下六題系統驗不了，是開放題 ──")
    print()
    for i, (q, where) in enumerate(TAKEOVER_QUESTIONS, 1):
        print(f"  {i}. {q}")
        print(f"     依據在：{where}")
        print()
    return 0


def cmd_gate_submit(rep: Report, args: list[str]) -> int:
    """交卷。答案從 stdin 讀 JSON:`{"qid": "作答", ...}`。"""
    S = _suff()
    root = rep.root if hasattr(rep, "root") else Path(__file__).resolve().parents[2]
    if not args:
        print("要交哪一份考卷？　forseti gate submit <exam_id>", file=sys.stderr)
        return 2
    raw = sys.stdin.read()
    try:
        answers = json.loads(raw) if raw.strip() else {}
    except ValueError as e:                                  # noqa: BLE001
        print(f"讀不懂答案，要是 JSON：{e}", file=sys.stderr)
        return 2
    if not isinstance(answers, dict):
        print("答案要是一個物件：{\"qid\": \"作答\"}", file=sys.stderr)
        return 2

    res = S.submit(root, exam_id=args[0], answers=answers,
                   session=current_session())
    if not res.get("ok"):
        print(f"  ✗ {res.get('why')}")
        return 2

    print()
    print(f"  判決　{res['verdict']}　{res['why']}")
    print(f"  答對　{res['right']} / {res['asked']}　"
          f"（{res['rate']:.0%}，門檻 {res['threshold']:.0%}）")
    print()
    for dim, v in res["per_dim"].items():
        mark = "✓" if v["pass"] else "✗"
        print(f"  {mark} {dim}　{v['right']}/{v['asked']}")
    if res["missing_dims"]:
        print()
        print("  沒有來源可考的維度：" + "、".join(res["missing_dims"]))
    print()
    return 0 if res["verdict"] in ("PASS", "PASS_PARTIAL") else 1


def cmd_gate_status(rep: Report) -> int:
    S = _suff()
    root = rep.root if hasattr(rep, "root") else Path(__file__).resolve().parents[2]
    st = S.state(root, session=current_session())
    print()
    print(f"  這條線　{st['session'] or '（認不出來）'}")
    print(f"  權限　{'可以寫' if st['write'] else '唯讀'}")
    print(f"  理由　{st['why']}")
    print(f"  考過幾次　{st['attempts']}")
    print(f"  強制擋人　{'開' if st['enforced'] else '關（只記錄不擋）'}")
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
            # 先撿收件匣。只有 Write 權限的 worker 的話都在那裡，
            # 不撿就等於它從來沒說過。
            got = led.collect_inbox(s["step_id"])
            a = led.check_liveness(s["step_id"])
            mark = "！" if a.suspect else "　"
            who = s["worker"] or "沒有負責人"
            cap = {"full": "", "write_only": "　只能寫檔",
                   "unknown": "　回報能力未宣告"}[s["can_report"]]
            print(f"  {mark} {s['local_id']:<10}{s['state']:<12}"
                  f"{_fmt_age(s['idle_sec']):>8} 沒動靜　{who}{cap}")
            print(f"      {s['objective'][:56]}")
            if got:
                print(f"      收到回報 {len(got)} 則　{'、'.join(got)}")
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


INBOX_README = """# 這是一個收件匣

你在這個目錄底下建一個 `.txt`，就等於在任務帳本裡發了一則回報。

    第一行   事件種類
    第二行起 說明

檔名隨便取。一個檔案一筆，不用去改舊的檔案。
控制端巡檢的時候會來撿，撿走的會移到 `.done/`。

合法的事件種類只有這八種：

    WORKER_ACCEPTED     我接下了
    WORKER_PROGRESS     做到哪裡了
    WORKER_COMPLETION   我認為做完了（這不等於驗證通過）
    WORKER_BLOCKED      被什麼擋住
    WORKER_FAILED       失敗了
    WORKER_CANCELLED    取消
    EVIDENCE_AVAILABLE  證據可以看了
    ARTIFACT_CHANGED    產物變了

寫別的種類不會被丟掉，會被記成「不認得的種類」，
因為讓你的話無聲消失比記錯更糟。

一件要講清楚的事：在這裡寫 `WORKER_COMPLETION` 不會讓任何東西
變成已驗證。驗證是控制端真的去跑 verifier、真的去看磁碟。
這個收件匣降低的是回報的門檻，不是驗證的門檻。
"""


def _ensure_inbox(led, step_id: str):
    """派工時就把收件匣建好，附一份格式說明。

    不要求 worker 自己建目錄：那是一個它可能做不到、而且做不到的時候
    完全不會有人知道的動作。這條通道存在的意義是把回報的門檻降到最低，
    那就不該在門檻前面再放一道門檻。

    說明檔用 .md，因為 collect_inbox 只撿 .txt，不會把它當成一則回報。
    """
    d = led.inbox_dir(step_id)
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "README.md").write_text(INBOX_README, encoding="utf-8")
    except OSError:
        pass
    return d


def _report_by_writing(led, step_id: str) -> list[str]:
    """只需要 Write 權限的回報方式（B-10）。

    一個檔案一筆事件，不用 append。read-modify-write 對一個只有 Write
    的 worker 是額外的失敗機會，而這條通道存在的意義就是把回報的門檻
    降到跟寫產物一樣低。
    """
    d = _ensure_inbox(led, step_id)
    return [
        "你可能沒有執行指令的權限。那不影響回報：寫一個檔案就是回報。",
        "",
        f"收件匣　{d}",
        "",
        "在那個目錄底下建一個 .txt，第一行寫事件種類，第二行起寫說明。",
        "檔名隨便取，一個檔案一筆，不用去改舊的檔案。",
        "",
        "  例如　accepted.txt",
        "      WORKER_ACCEPTED",
        "      接下了，正在讀 ledger.py",
        "",
        "  例如　p1.txt",
        "      WORKER_PROGRESS",
        "      骨架寫完了，還差 exit code 的處理",
        "",
        "  卡住也要寫，沉默跟卡住在帳本裡長得一模一樣：",
        "      WORKER_BLOCKED",
        "      找不到 schema 定義在哪",
        "",
        "控制端巡檢的時候會去撿，撿到就變成帳本裡真正的事件。",
        "寫了就等於說了，不必等它撿。",
    ]


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
    ]

    cap = led.can_report(step_id)
    if cap in ("full", "unknown"):
        lines += [
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
    if cap in ("write_only", "unknown"):
        if cap == "unknown":
            lines += ["", "── 如果上面那些指令跑不起來 ──", ""]
        lines += _report_by_writing(led, step_id)
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
    # B-10：worker 能不能執行指令,是派工方本來就知道的事。
    # 沒宣告就是 unknown,那不是「大概可以」,是「沒問過」。
    cap = "unknown"
    if "--no-shell" in args:
        cap = "write_only"
        args = [a for a in args if a != "--no-shell"]
    elif "--shell" in args:
        cap = "full"
        args = [a for a in args if a != "--shell"]
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

        led.dispatch(step_id, worker, f"跨 session 派給 {worker}",
                     can_report=cap)

        print()
        print(f"  已登記　{step_id}")
        print(f"  負責人　{worker}")
        note = {"full": "能執行指令，直接寫帳本",
                "write_only": "只能寫檔案，回報走收件匣",
                "unknown": "沒有宣告，訊息裡兩種方式都給了"}[cap]
        print(f"  回報能力　{cap}　（{note}）")
        if cap == "write_only":
            # 2026-09-09 實測:兩個 worker 同時卡住,因為我把要讀的源檔
            # 放在 Dropbox。它們的沙盒只准存取 repo,連讀都不行。
            # B-10 學到「worker 只能寫 repo」,當時沒推廣到「也只能讀 repo」。
            print("  ⚠ 這種 worker 通常只存取得到 repo 內的檔案，讀也一樣。")
            print("    它要用的資料先複製進 repo，不要只給外部路徑。")
        if cap == "unknown":
            print("  下次可以用 --shell 或 --no-shell 講清楚，")
            print("  巡檢就不必把「它不回話」跟「它回不了話」混在一起。")
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


def cmd_events(args: list[str]) -> int:
    """Event Ledger 的現況。跟 tasks 是兩本不同的帳（ADR-008）。"""
    el = _sibling("event_ledger")
    led = el.EventLedger()
    try:
        recs = led.read_all()
        print()
        print(f"  正本　{led.jsonl}")
        print(f"  索引　{led.index_path}")
        print()
        if not recs:
            print("  還沒有事件。")
            print("  這本記的是 provider 行為事件（AI 與 runtime 實際做了什麼），")
            print("  不是派工協調 —— 那本是 `forseti tasks`。")
            print()
            return 0
        by_cat: dict[str, int] = {}
        for r in recs:
            n = r.get("norm")
            if n:
                c = el.TYPE_TO_CATEGORY.get(n.get("type"), "?")
                by_cat[c] = by_cat.get(c, 0) + 1
        print(f"  {len(recs)} 筆　指紋 {led.digest()[:16]}")
        print()
        for c in el.CATEGORIES:
            if by_cat.get(c):
                print(f"    {c:<12}{by_cat[c]}")
        no_norm = sum(1 for r in recs if not r.get("norm"))
        if no_norm:
            print(f"    （另有 {no_norm} 筆只有 raw 沒有 normalized）")
        n_test = sum(1 for r in recs if el.is_test_event(r))
        if n_test:
            print()
            print(f"  其中 {n_test} 筆是測試產生的（session 在 KNOWN_TEST_SESSIONS 裡）")
            print("  不刪，因為正本是 append-only。分析時排除，取證時不當它沒發生。")
        print()
        return 0
    finally:
        led.close()


def cmd_replay(args: list[str]) -> int:
    """重播帳本。出口條件：同一份帳本重播兩次，結果逐位元組相同。

    給 session id 就只重播那一個。不給就全部。
    """
    el = _sibling("event_ledger")
    led = el.EventLedger()
    try:
        recs = led.read_all()
        if args:
            want = args[0]
            recs = [r for r in recs
                    if (r.get("norm") or {}).get("session_id") == want]
            if not recs:
                print(f"  沒有 session {want} 的事件。")
                return 1
        for r in recs:
            print(el.canonical_json(r))
        return 0
    finally:
        led.close()


def cmd_reindex(args: list[str]) -> int:
    """從正本重建索引。整個砍掉重來，正本一個位元組都不動。"""
    el = _sibling("event_ledger")
    led = el.EventLedger()
    try:
        stat = led.reindex()
        print()
        print(f"  重建完成　raw {stat['raw']} 筆　normalized {stat['normalized']} 筆")
        print(f"  {stat['index']}")
        print()
        return 0
    finally:
        led.close()


def no_extra_args(args: list[str], cmd: str) -> str:
    """不吃任何參數的那四支。回「哪裡不對」，沒問題回空字串。

    2026-09-18 實測，這四支收到多餘參數的後果一模一樣:

    | 寫法 | exit | 後果 |
    |---|---|---|
    | `doctor --yes` | 0 | 旗標被吞掉，印出一份正常的報告 |
    | `status --limit 5` | 0 | 同上 |
    | `gate status --yes` | 0 | 同上 |
    | `gate takeover --bogus x` | 0 | 同上，**而且照樣寫一筆考卷進正本** |

    最後那一支是這四支裡唯一會改變狀態的。量它的方式是攔
    `sufficiency.open_exam`，三種寫法都走到寫入點（次數各 1），
    所以「參數被吞掉」在那裡不是顯示問題，是寫進去的那一筆
    不知道使用者其實下錯了指令。

    **這裡不分旗標與位置參數的對錯，兩種都是錯的** —— 這一支
    不吃任何參數，所以 exit code 一律 2（用法錯）。長相只拿來挑
    措辭:`-` 開頭的人以為這支有這個旗標，不是的人多半是子指令
    打錯或多打了一個字。長相不決定 exit code，就沒有 `transcript_path`
    那裡「拿長相定罪」的風險，誤判是 0。
    """
    if not args:
        return ""
    flags = [a for a in args if str(a).startswith("-")]
    rest = [a for a in args if not str(a).startswith("-")]
    if flags:
        what = f"這一支沒有這些旗標：{'、'.join(flags)}"
    else:
        what = f"這一支不吃參數，拿到的是：{'、'.join(str(r) for r in rest)}"
    return (f"{what}\n"
            f"用法：forseti.py {cmd}\n"
            "不擋的話這裡會印出一份正常的報告，exit 0，"
            "而你下錯的那個字不會有任何人提起。")


NO_ARG_COMMANDS: tuple[str, ...] = ("tasks", "events", "watch", "reindex")
"""帳本那一邊不吃任何參數的四支。**名單是量出來的，不是讀出來的。**

2026-09-18 15:0x 用攔截數寫入點的方式量過十四種寫法，四支收到多餘
參數的後果分成兩種，而分界不是「有沒有印東西」，是**有沒有走到寫入點**：

| 寫法 | exit | 走到寫入點 | 後果 |
|---|---|---|---|
| `tasks --bogus` | 0 | 沒有 | 旗標吞掉，印出一份正常的未完成清單 |
| `tasks x` | 0 | 沒有 | 同上 |
| `events --limit 5` | 0 | 沒有 | 同上，`--limit` 等於沒寫 |
| `watch --bogus` | 0 | **`Ledger.collect_inbox`** | 照樣巡檢，收信箱、判活著沒 |
| `reindex --dry-run` | 0 | **`EventLedger.reindex`** | 索引照樣整個砍掉重建 |

後兩支是這一組的理由。`reindex --dry-run` 那一行**看起來像在問**，
實際上跟乾淨呼叫走的是同一條路 —— 使用者打那個旗標的意思是
「先別動」，而它動了，畫面上還回一句「重建完成」。
`watch --bogus` 同一個形狀：它會 `collect_inbox` 與 `recover`，
那是會改狀態的巡檢，不是唯讀的看一眼。

`watch` 那一支第一輪量的時候**走不到寫入點**，因為當下 0 個進行中
的步驟。那個 0 不是證據，是沒有材料。第二輪把 `active_steps()` 換成
一個假的進行中步驟再量，才看到 `collect_inbox`。
**「這一次沒走到」跟「走不到」不是同一件事**，中間差的是有沒有材料。

前兩支是唯讀的，所以它們是顯示問題不是狀態問題。**照樣擋** ——
理由跟 `no_extra_args` 原本那四支一樣：不擋的話那個打錯的字
不會有任何人提起。

名單裡沒有 `dispatch` / `auto` / `drain` / `verify` / `continuity` /
`event` / `handoff` / `replay` / `context` / `index` / `recall`，
因為那幾支**真的吃參數**，歸的是另一道判準（`operands` 那一種），
還沒接。同一輪量到的、還沒有人管的兩種形狀寫在
`AUTO_CONTINUE_LOG.md` 這一輪的「還缺什麼」。
"""


@dataclass(frozen=True)
class Shape:
    """一支子指令的位置參數長什麼樣。一份判準,多個呼叫端。

    `slots` 是固定位置,照順序,每一格 `(名字, 要不要擋旗標)`。

    **「要不要擋旗標」不是每一格都是 True。** `event` 的第三格是理由,
    自由文字,一個以 `-` 開頭的理由是合法的 —— 擋它就是拿長相定罪,
    而這裡沒有 filesystem 那種確定性的問法（`bible.md` Q-01 反過來用）。
    id 那幾格不一樣:它們要拿去查,查得到查不到是確定性的,
    所以旗標放在那裡一定是錯的。

    `required` 是前幾格必填,**只影響用法那一行框成 `<x>` 還是 `[x]`,
    不決定要不要退回**。帶太少歸各支自己那句話,它講得比通用措辭具體
    （`verify` 少參數印的是它自己那行用法),兩邊不重疊:
    這一支問「長相與數量對不對」,那一句問「到底要哪一個」。

    `tail` 是後面那一段自由文字的名字,空字串代表不收多的。
    有 tail 的那兩支（`dispatch` / `auto` 的理由）沒有上限,
    所以「多拿到的」對它們不成立 —— 這是三種形狀裡的第三種,
    2026-09-18 那一輪寫下「這三種要分清楚才動手」指的就是它。
    """

    slots: tuple[tuple[str, bool], ...]
    required: int
    tail: str = ""

    def usage(self, cmd: str) -> str:
        parts = [(f"<{n}>" if i < self.required else f"[{n}]")
                 for i, (n, _) in enumerate(self.slots)]
        if self.tail:
            parts.append(f"[{self.tail}]")
        return f"用法：forseti.py {cmd} " + " ".join(parts)


def operands(args: list[str], cmd: str, shape: Shape) -> str:
    """固定位置參數的那幾支。回「哪裡不對」,沒問題回空字串。

    `no_extra_args` 管不到這一種:這幾支**真的吃參數**,
    所以「有參數」本身是對的,錯的是長相與數量。

    2026-09-18 15:2x 攔寫入點量過,旗標放在位置參數的位置有**兩種**
    後果,而先前只量到第一種:

    | 寫法 | exit | 走到寫入點 | 收到什麼 |
    |---|---|---|---|
    | `verify --yes` | 1 | 沒有 | ── |
    | `continuity --yes` | 1 | 沒有 | ── |
    | `dispatch --yes w` | 1 | 沒有 | ── |
    | `auto --yes w` | 1 | 沒有 | ── |
    | `drain --yes w` | 1 | 沒有 | ── |
    | `event --yes s why` | 1 | 沒有 | ── |
    | `replay --limit` | 1 | 沒有 | ── |
    | `drain <真 task> --yes` | ── | **`Ledger.drain`** | `(task, '--yes')` |
    | `dispatch <真 step> --yes r` | ── | **`Ledger.dispatch`** | `(step, '--yes', 'r')` |
    | `auto <真 task> --yes r` | ── | **`Ledger.auto_dispatch`** | `(task, '--yes', 'r')` |
    | `event DONE <真 step> why --yes` | ── | **`Ledger.worker_event`** | `worker='--yes'` |

    **第一格與第二格不是同一件事。** 第一格是 id,查不到就停在
    「找不到…」,exit 1,沒有東西被寫進去 —— 那是訊息指錯地方
    加上 exit code 錯一級（用法錯應該是 2)。第二格是 worker,
    **沒有人去查它**,所以它一路走到寫入點,帳本裡那一筆的 worker
    就是那個旗標,而帳本是 append-only,收不回來。

    量的時候第一版的假帳本讓 `_resolve_step` 對任何字串都回得出步驟,
    於是 `verify --yes` 看起來走到了 `verify_step`。**那是自己造出來的
    材料,不是證據** —— 真的帳本查不到叫 `--yes` 的步驟。改成只有對得上
    才回得出東西之後,第一格那七種全部落在「沒有走到寫入點」。
    這跟前一輪 `watch` 那件事是同一個陷阱的反面:一邊是材料不夠把
    「走不到」讀成證據,一邊是材料太多把「走得到」讀成證據。

    **上面那張表的 `event` 那一列,例子本身是假材料（2026-09-18 15:5x 實測）。**
    `DONE` 不在 `ledger.WORKER_EVENTS` 裡,而假帳本的 `worker_event` 是
    計數用的 stub,不檢查 kind,所以任何字串都「走得到寫入點」。真帳本
    第一行就 raise,事件數不變。換成真 kind 之後結論才拿得到證據:
    `worker_event('WORKER_ACCEPTED', step, 'why', worker='--yes')` 實測
    寫進去了,`events.actor` 就是 `--yes` —— **結論成立,例子不成立**。
    修掉假帳本 `_resolve_step` 那一半的同一輪,漏掉了成員資格這一半。

    尾巴那幾個也量過,吞掉之後照樣寫:`drain <真 task> w extra --yes`
    走到 `drain` 收到 `(task, 'w')`,`verify <真 step> extra` 走到
    `verify_step`。所以「多拿到的」在這幾支不是顯示問題。
    """
    if not args:
        return ""
    usage = shape.usage(cmd)
    for i, (name, guard) in enumerate(shape.slots):
        if i >= len(args) or not guard:
            continue
        got = str(args[i])
        if got.startswith("-"):
            return (f"這個位置要的是 {name}，不是旗標，"
                    f"而拿到的是：{got}\n"
                    f"{usage}\n"
                    f"不擋的話 {got} 會被當成 {name} 用下去，"
                    f"而你真正錯的是旗標放在位置參數的位置，"
                    f"不是 {name} 打錯了。")
    if not shape.tail and len(args) > len(shape.slots):
        extra = "、".join(str(a) for a in args[len(shape.slots):])
        names = [n for n, _ in shape.slots]
        if len(names) == 1:
            what = f"這一支只吃一個 {names[0]}，多拿到的是：{extra}"
        else:
            what = (f"這一支只吃 {'、'.join(names)} 這 {len(names)} 個，"
                    f"多拿到的是：{extra}")
        return (f"{what}\n"
                f"{usage}\n"
                "不擋的話多的那幾個會被靜默吞掉，"
                "而這一支會照樣執行下去，"
                "那一次不知道你其實下錯了指令。")
    return ""


OPERAND_SHAPES: dict[str, Shape] = {
    "verify": Shape(slots=(("step", True),), required=1),
    "continuity": Shape(slots=(("task", True),), required=1),
    "replay": Shape(slots=(("session_id", True),), required=0),
    "drain": Shape(slots=(("task", True), ("worker", True)), required=2),
    "dispatch": Shape(slots=(("step", True), ("worker", True)),
                      required=2, tail="理由"),
    "auto": Shape(slots=(("task", True), ("worker", True)),
                  required=2, tail="理由"),
    "event": Shape(slots=(("kind", True), ("step", True),
                          ("理由", False), ("worker", True)),
                   required=3),
    "gate submit": Shape(slots=(("exam_id", True),), required=1),
}
"""真的吃位置參數的那八支。**每一格的形狀是量出來的,不是讀出來的。**

名字與必填數對齊各支自己印的那行用法（`cmd_verify` 那幾支),
所以退回的時候畫面上那一行跟他打錯之前看到的是同一句。

`event` 的第三格 `理由` 是唯一一格 `guard=False`,因為它是自由文字。
第四格 `worker` 照擋:`event DONE <真 step> why --yes` 量過,
`--yes` 會以 `worker=` 走到 `Ledger.worker_event`。
（`DONE` 這個 kind 是假材料,真名單裡沒有它,見 `operands` docstring
結尾那一段。換成真 kind 之後結論照樣成立,寫進去的 actor 就是 `--yes`。）

`dispatch` 與 `auto` 有 `tail`,所以它們**沒有數量上限** ——
理由是自由文字,`dispatch s w 因為 A 所以 B` 是合法的。
這一點是它們跟 `drain` 的差別:`drain` 不收理由,第三個以後就是多的。

`gate submit` 在這張表裡,可是 `cmd` 永遠不會等於 `gate submit`
（那是兩段）,所以它由 `main()` 裡 gate 那一段自己查表呼叫。
兩個呼叫端讀的是同一份表,不是兩份。
"""


MEMBER_SLOTS: dict[str, tuple[int, str, str, str]] = {
    "event": (0, "kind", "ledger", "WORKER_EVENTS"),
}
"""哪一支的哪一格,值必須是某張名單裡的成員。

**這是第三種判準,跟前兩種不重疊。** `no_extra_args` 問「該不該有參數」,
`operands` 問「位置與長相對不對」,這一支問「這個值在不在名單裡」。
一個合法長相的字串可以完全不是合法的值:`event bogus <真 step> why`
四格數量對、沒有一格是旗標,三道裡前兩道都放行。

**名單存的是去哪裡拿,不是拿到的東西。** 第三、四格是模組名與常數名,
由 `membership()` 去 `_sibling()` 取。抄一份到這裡的話,
`ledger.WORKER_EVENTS` 哪天多一種,這裡不會跟著動,而兩邊不一致的
症狀是「CLI 說不合法,帳本說合法」—— 那種不一致沒有人會發現,
因為畫面上看起來就只是一句拒絕。
"""


def membership(args: list[str], cmd: str, spec: tuple[int, str, str, str]) -> str:
    """成員資格。回「哪裡不對」,沒問題回空字串。

    2026-09-18 15:5x 用臨時帳本量過現況（`Ledger(db=<暫存>)`,沒碰正本）。
    量出來的東西推翻了原本寫在「還缺什麼」裡的那句話,所以先記下來:

    | 寫法 | exit | 帳本事件數 | 畫面那句話 |
    |---|---|---|---|
    | `event WORKER_PROGRESS <真 step> why` | 0 | 1 → 2 | 已記　WORKER_PROGRESS |
    | `event bogus <真 step> why` | 2 | 2 → 2 | 不是 F04 §3 定義的 worker 事件 |
    | `event bogus <假 step> why` | **1** | 2 → 2 | **找不到步驟：假 step** |

    **第二列不是缺口。** `Ledger.worker_event` 第一行就擋,而且擋在任何
    寫入之前,所以 kind 打錯從來沒有污染過帳本 —— 原本那句「照樣一路走到
    `worker_event` 才 ValueError」聽起來像有東西被寫進去,量出來沒有。

    **缺口是第三列。** `cmd_event` 先 `_resolve_step` 再呼叫
    `worker_event`,所以兩格都打錯的時候,先撞到的是步驟那一關,
    畫面回「找不到步驟」exit 1。那句話是真的（那個步驟確實不存在）,
    可是它把人指向第二格,而第一格才是根本不合法的那一格。
    exit code 也錯一級:1 是資料錯,而 kind 打錯是用法錯,該是 2。

    所以這一支做的不是「新增一道攔截」,是**把成員資格搬到解析 id 之前**,
    讓「這個 kind 根本不存在」永遠比「那個 id 查不到」先講。

    **不做大小寫轉換,也不套 `ledger.ALIASES`。** 收件匣那一端兩件都做
    （`ledger.py:836` 的 `ALIASES.get(first[0].upper(), ...)`）,所以
    `WORKER_DONE` 與 `worker_completion` 走收件匣收得下,走 CLI 收不下。
    那個不一致是真的,實測確認過,可是收不收是協定適用範圍的決定
    （`ALIASES` 自己的註解寫著它是「收件匣的別名」,而且「只收實測真的
    發生過的誤用」）。**擴大一張有出處要求的名單不是我該自己決定的**,
    寫進「還缺什麼」等 owner。
    """
    slot, name, mod_name, const = spec
    if slot >= len(args):
        # 帶太少歸那一支自己那句話,跟 `operands` 同一個政策:
        # 這一支問「這個值合不合法」,那一句問「到底要哪幾個」。
        return ""
    allowed = tuple(getattr(_sibling(mod_name), const))
    got = str(args[slot])
    if got in allowed:
        return ""
    return (f"{got} 不是合法的 {name}。\n"
            f"合法的 {name}：{'　'.join(allowed)}\n"
            f"不擋的話,這一格的錯要等到 {mod_name} 那一層才會被提起,"
            f"而在那之前會先去查第二格 —— 第二格也打錯的時候,"
            f"畫面回的是「找不到步驟」,把「這個 {name} 不存在」"
            f"講成「那個東西不存在」,exit 也會是 1（資料錯）"
            f"而不是 2（用法錯）。")


GATE_SUBCOMMANDS: tuple[str, ...] = ("takeover", "submit", "status")


def gate_subcommand(args: list[str]) -> str:
    """`gate` 底下有哪幾支。回「哪裡不對」，沒問題回空字串。

    2026-09-18 實測，`gate` 與 `gate bogus` 兩種寫法的 exit code
    都已經是 2，所以這一支**不是新增一道守門**，改的是訊息指向:

    | 寫法 | 改之前印什麼 | 改之後 |
    |---|---|---|
    | `gate` | 整個 CLI 的 `__doc__` | gate 底下有哪幾支 |
    | `gate bogus` | 同上 | 同上，而且點名 bogus |

    走的是 dispatch 末尾那一行 `print(__doc__); return 2` ——
    那一行守的是「整個 CLI 沒有這個子指令」，而使用者打錯的是
    **gate 的子指令**。兩者都退回 2，可是講的不是同一件事:
    畫面要他去看整個 CLI 有哪些指令，而他要找的是 gate 有哪幾支。

    所以這裡不碰 exit code，只讓訊息指回他真正打錯的那一層。
    `no_extra_args` 那一支管的是另一件事（合法子指令帶多餘參數），
    兩支相鄰不重疊:這一支問「有沒有這一支」，那一支問
    「這一支收不收這些東西」。
    """
    if not args:
        what = "gate 要帶子指令，沒有預設的那一支。"
    elif args[0] in GATE_SUBCOMMANDS:
        return ""
    else:
        what = f"gate 底下沒有這一支：{args[0]}"
    return (f"{what}\n"
            f"有的是：{'、'.join(GATE_SUBCOMMANDS)}\n"
            f"用法：forseti.py gate <{'|'.join(GATE_SUBCOMMANDS)}>\n"
            "不擋的話這裡印的是整個 CLI 的用法，"
            "而你打錯的是 gate 的子指令，兩者講的不是同一件事。")


TRANSCRIPT_FLAGS: tuple[str, ...] = ("--limit",)


def transcript_path(args: list[str], cmd: str) -> tuple[Path | None, str, int]:
    """`claims` 與 `overclaim` 的第一個參數。回 `(路徑, 哪裡不對, exit code)`。

    2026-09-18 實測，旗標放在路徑的位置會拿到這個：

    | 寫法 | exit | 印出來的 |
    |---|---|---|
    | `claims --limit 2` | 1 | `找不到：--limit` |
    | `overclaim --limit 2` | 1 | 一模一樣 |

    那句話**是真的**，檔案確實不存在。它的問題是指錯地方：
    使用者的錯是把旗標放在路徑的位置，而畫面上講的是檔案不存在，
    於是他會去找那個檔案。比靜默好，比講得準差。

    exit code 也錯了一級。這一支的慣例是 2 = 用法錯、1 = 資料錯，
    而「旗標放錯位置」是用法錯。

    **先查檔案存不存在，再看它像不像旗標**，順序不能換。
    反過來寫的話，一個真的叫做 `--limit` 的檔案會被擋在外面 ——
    那是拿長相定罪，而這裡有 filesystem 可以直接問（`bible.md` Q-01
    能用確定性驗證就不要用機率性驗證）。順序這樣排，誤判是 0 不是少。
    """
    raw = str(args[0])
    p = Path(raw).expanduser()
    if p.exists():
        return p, "", 0
    if raw.startswith("-"):
        return None, (f"第一個參數要的是 transcript 的路徑，"
                      f"拿到的是一個旗標：{raw}\n"
                      f"用法：forseti.py {cmd} <transcript.jsonl> [--limit N]\n"
                      "旗標寫在路徑後面。不擋的話這裡會印"
                      f"「找不到：{raw}」，那句話是真的，"
                      "可是它講的是檔案不存在，不是你把旗標放錯位置。"), 2
    return None, f"  找不到：{p}", 1


def transcript_limit(args: list[str],
                     known: tuple[str, ...] = TRANSCRIPT_FLAGS
                     ) -> tuple[int, str]:
    """`claims` 與 `overclaim` 的 `--limit`。回 `(limit, 哪裡不對)`。

    **一份判準給兩支用，不在兩支各寫一次。** 各寫一次的代價是
    2026-09-18 11:2x 在 `probemodel` 量到的那一種：預告跟實際兩份判準，
    對不上而且沒有人會發現。

    2026-09-18 實測，這兩支打錯旗標的後果分三種，**沒有一種說得出
    哪裡不對**（材料是六則 assistant 文字）：

    | 寫法 | exit | 實際發生的事 |
    |---|---|---|
    | `claims <檔> --limitt 2` | 0 | 靜默跑滿六則，畫面跟成功一樣 |
    | `claims <檔> --limit` | 0 | 同上，`--limit` 等於沒寫 |
    | `claims <檔> --limit abc` | 1 | `int()` 的 ValueError traceback |
    | `overclaim <檔>` 三種 | 同上 | 三種後果完全一樣 |

    第三種看起來最兇，其實最輕 —— 它至少講了一件真的事。前兩種
    才是「錯的答案長得跟對的一樣」：使用者以為只看了最後兩則，
    實際看的是整份。

    第一個參數是路徑，**整支都不掃它**。路徑打成旗標長相的東西，
    上面那一道 `找不到：--limit` 已經擋得住，而且它講得比這裡準。

    「不掃第 0 個」這句話 2026-09-18 寫下來的時候只有前半段做到 ——
    未知旗標那一段跳過了第 0 個，缺值那一段沒有，於是同一支裡兩套
    判準。那正是這一支存在的理由（判準只准有一份），被它自己的
    測試 `test_第一個參數是路徑不掃它` 當場抓到。改成整支共用 `rest`。
    """
    rest = args[1:]
    for a in rest:
        if not str(a).startswith("--"):
            continue
        name = str(a).split("=", 1)[0]
        if name not in known:
            return 0, (f"不認得這個旗標：{name}\n"
                       f"有的是：{'、'.join(known)}\n"
                       "打錯字不會報錯，`--limit` 會變成沒寫，"
                       "於是整份都算進去。所以這裡退回。")
    if "--limit" not in rest:
        return 0, ""
    i = rest.index("--limit")
    if i + 1 >= len(rest):
        return 0, ("`--limit` 後面沒有數字。要全部就整個拿掉，"
                   "不然它會靜默算整份。")
    raw = rest[i + 1]
    try:
        n = int(raw)
    except ValueError:
        return 0, (f"`--limit` 要一個整數，拿到的是：{raw}\n"
                   "不擋的話這裡會丟一個 int() 的 traceback，"
                   "那看起來像程式壞了，不像你打錯字。")
    if n < 0:
        return 0, f"`--limit` 不能是負的：{n}"
    return n, ""


def cmd_claims(args: list[str]) -> int:
    """從一份 transcript 抽出宣稱，逐一對現實驗證。階段 2 的出口條件。

    只看 assistant 的 `text` block，不看 `thinking`。理由是 thinking
    不是對使用者說的話 —— 拿它當宣稱去驗，等於把思考過程當成承諾，
    而人在想的時候本來就會講出還沒確定的東西。
    """
    cl = _sibling("claims")
    if not args:
        print("用法：forseti.py claims <transcript.jsonl> [--limit N]",
              file=sys.stderr)
        return 2
    path, bad, code = transcript_path(args, "claims")
    if path is None:
        print(bad, file=sys.stderr if code == 2 else sys.stdout)
        return code
    limit, why = transcript_limit(args)
    if why:
        print(why, file=sys.stderr)
        return 2

    texts: list[str] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            c = (d.get("message") or {}).get("content")
            if not isinstance(c, list):
                continue
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = b.get("text") or ""
                    if t.strip():
                        texts.append(t)
    if limit:
        texts = texts[-limit:]

    root = find_repo_root(Path(__file__).resolve().parent)
    tally: dict[str, int] = {}
    strength: dict[str, int] = {}
    samples: list = []
    n_claims = 0
    for t in texts:
        for got in cl.extract(t):
            n_claims += 1
            c = cl.Claim(text=t[:160], kind=got["kind"],
                         subject=got.get("subject", ""))
            if got["kind"] == "unextractable":
                tally["UNEXTRACTABLE"] = tally.get("UNEXTRACTABLE", 0) + 1
                continue
            try:
                cl.verify(c, cwd=root)
            except Exception as e:  # noqa: BLE001
                tally["ERROR"] = tally.get("ERROR", 0) + 1
                continue
            tally[c.state] = tally.get(c.state, 0) + 1
            strength[c.strength] = strength.get(c.strength, 0) + 1
            if len(samples) < 8 and c.state in ("REFUTED", "VERIFIED"):
                samples.append(c)

    print()
    print(f"  {path.name}")
    print(f"  assistant 的 text block　{len(texts):,} 則")
    print(f"  抽出宣稱　{n_claims:,} 個")
    print()
    for st in ("VERIFIED", "REFUTED", "UNKNOWN", "UNEXTRACTABLE", "ERROR"):
        if tally.get(st):
            print(f"    {st:<16}{tally[st]:>6}")
    if strength:
        print()
        print("  證據強度（v5.0 §7.2）")
        for e in cl.STRENGTH:
            if strength.get(e):
                print(f"    {e}  {strength[e]:>6}   {cl.STRENGTH_MEANING[e][:34]}")
    if samples:
        print()
        print("  幾個例子")
        for c in samples:
            print(f"    {c.state:<10}{c.subject[:44]}")
            print(f"      {c.why_state[:70]}")
    print()
    print("  UNEXTRACTABLE 不是失敗。它是「有過去式動詞但找不到可查核的東西」，")
    print("  而猜一個出來的代價比漏掉高。")
    print()
    return 0


def cmd_overclaim(args: list[str]) -> int:
    """三個 overclaim primitive 跑一份 transcript。

    **FP-03 是這裡唯一算得出真答案的一個**，因為 Event Ledger 有 receipt：
    一句「我親自驗過了」對得上那個 session 在帳本裡到底留下幾筆觀測。

    FP-02 需要結構化的 scope、FP-07 需要宣稱數與驗證數，
    兩者 transcript 裡都沒有，所以會是 INDETERMINATE。
    **那不是失敗，那是這兩條判準的前提還沒備齊。**
    """
    oc = _sibling("overclaim")
    el = _sibling("event_ledger")
    if not args:
        print("用法：forseti.py overclaim <transcript.jsonl> [--limit N]",
              file=sys.stderr)
        return 2
    path, bad, code = transcript_path(args, "overclaim")
    if path is None:
        print(bad, file=sys.stderr if code == 2 else sys.stdout)
        return code
    limit, why = transcript_limit(args)
    if why:
        print(why, file=sys.stderr)
        return 2

    # 帳本裡每個 session 留下幾筆觀測。這就是「自己的 receipt」。
    receipts: dict[str, int] = {}
    try:
        led = el.EventLedger()
        try:
            for rec in led.read_all():
                n = rec.get("norm") or {}
                sid = n.get("session_id") or n.get("agent_id") or ""
                if sid:
                    receipts[sid] = receipts.get(sid, 0) + 1
        finally:
            led.close()
    except Exception:
        pass

    rows: list = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            c = (d.get("message") or {}).get("content")
            if not isinstance(c, list):
                continue
            sid = d.get("sessionId") or ""
            for b in c:
                if isinstance(b, dict) and b.get("type") == "text":
                    t = (b.get("text") or "").strip()
                    if t:
                        rows.append((sid, t))
    if limit:
        rows = rows[-limit:]

    tally: dict[str, dict[str, int]] = {}
    hits: list = []
    for sid, text in rows:
        own = receipts.get(sid)
        for f in oc.inspect(text, own_receipts=own):
            d = tally.setdefault(f.primitive_id, {})
            d[f.verdict] = d.get(f.verdict, 0) + 1
            if f.verdict == "POSITIVE" and len(hits) < 6:
                hits.append((text[:60], f))

    print()
    print(f"  {path.name}　{len(rows):,} 則 assistant 文字")
    print(f"  帳本裡有 receipt 的 session　{len(receipts)} 個")
    print()
    for pid in ("FP-02", "FP-03", "FP-07"):
        d = tally.get(pid, {})
        parts = "　".join(f"{v} {d.get(v, 0)}" for v in oc.VERDICTS)
        print(f"    {pid}　{parts}")
    if hits:
        print()
        print("  命中")
        for text, f in hits:
            print(f"    {f.primitive_id}　{text}…")
            print(f"      {f.why[:76]}")
    print()
    print("  INDETERMINATE 多是預期的：FP-02 要結構化的 scope、")
    print("  FP-07 要宣稱數與驗證數，transcript 裡兩者都沒有。")
    print("  那不是判準失效，是它的前提還沒備齊。")
    print()
    return 0


def main(argv: list[str]) -> int:
    root = find_repo_root(Path(__file__).resolve().parent)
    if root is None:
        print("找不到 .forseti/，這裡不是 Forseti 專案。", file=sys.stderr)
        return 2

    rep = build_report(root)
    cmd = argv[1] if len(argv) > 1 else "doctor"

    # 一份判準四個呼叫端，不是四份。名單在 NO_ARG_COMMANDS，
    # 那裡寫著它是怎麼量出來的，以及為什麼 reindex 與 watch 比另外兩支重。
    if cmd in NO_ARG_COMMANDS:
        bad = no_extra_args(argv[2:], cmd)
        if bad:
            print(bad, file=sys.stderr)
            return 2

    # 真的吃位置參數的那七支。形狀在 OPERAND_SHAPES，那裡寫著每一格
    # 是怎麼量出來的，以及為什麼第二格比第一格重（第二格會走到寫入點）。
    shape = OPERAND_SHAPES.get(cmd)
    if shape is not None:
        bad = operands(argv[2:], cmd, shape)
        if bad:
            print(bad, file=sys.stderr)
            return 2

    # 第三種判準：某一格的值必須在某張名單裡。排在 `operands` **後面**，
    # 因為旗標不在任何名單裡，兩道都會攔到 `event --yes s why` ——
    # 而那一次真正錯的是旗標放錯位置，不是「--yes 不是合法的 kind」。
    # 先講長相再講成員資格，訊息才指得到根本原因。
    member = MEMBER_SLOTS.get(cmd)
    if member is not None:
        bad = membership(argv[2:], cmd, member)
        if bad:
            print(bad, file=sys.stderr)
            return 2

    if cmd == "doctor":
        bad = no_extra_args(argv[2:], "doctor")
        if bad:
            print(bad, file=sys.stderr)
            return 2
        return cmd_doctor(rep)
    if cmd == "status":
        bad = no_extra_args(argv[2:], "status")
        if bad:
            print(bad, file=sys.stderr)
            return 2
        return cmd_status(rep)
    if cmd == "gate":
        bad = gate_subcommand(argv[2:])
        if bad:
            print(bad, file=sys.stderr)
            return 2
    if cmd == "gate" and len(argv) > 2 and argv[2] == "takeover":
        bad = no_extra_args(argv[3:], "gate takeover")
        if bad:
            print(bad, file=sys.stderr)
            return 2
        return cmd_gate_takeover(rep)
    if cmd == "gate" and len(argv) > 2 and argv[2] == "submit":
        bad = operands(argv[3:], "gate submit",
                       OPERAND_SHAPES["gate submit"])
        if bad:
            print(bad, file=sys.stderr)
            return 2
        return cmd_gate_submit(rep, argv[3:])
    if cmd == "gate" and len(argv) > 2 and argv[2] == "status":
        bad = no_extra_args(argv[3:], "gate status")
        if bad:
            print(bad, file=sys.stderr)
            return 2
        return cmd_gate_status(rep)
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
    if cmd == "events":
        return cmd_events(argv[2:])
    if cmd == "replay":
        return cmd_replay(argv[2:])
    if cmd == "reindex":
        return cmd_reindex(argv[2:])
    if cmd == "claims":
        return cmd_claims(argv[2:])
    if cmd == "overclaim":
        return cmd_overclaim(argv[2:])
    if cmd == "probe":
        import probe as PB
        return PB.main(argv[2:])
    if cmd == "probe-model":
        # §15 三軸裡的 models 與 contexts。另開一個指令不混進 `probe`，
        # 因為這一支會花掉訂閱額度，而 `probe` 是隨手跑得起來的。
        import probemodel as PM
        return PM.main(argv[2:])
    if cmd == "metric":
        # §33.1 Metric Provenance Contract。不併進 `claims`，因為那一支
        # 判的是「這句宣稱有沒有證據」，這一支問的是「這個數字說得出
        # 尺、材料、層、分母、環境、血緣嗎」—— 一個數字六欄齊全
        # 仍然可以被拿去講一句沒有證據的話，兩件事各守各的。
        import metrics as MT
        return MT.main(argv[2:])
    if cmd == "evidence":
        # §7.2。不併進 `claims`，因為那一支問的是「這句話有沒有被
        # 查核過」，這一支存的是「某一刻觀察到什麼」。一筆證據不屬於
        # 任何一個宣稱 —— §6.3 的 VERIFIES 是 evidence -> claim，
        # 方向是證據先在那裡，宣稱後來指過去。併進去的話登一筆證據會
        # 被迫先有一個宣稱，而那個順序是反的。
        import evidence as EV
        return EV.main(argv[2:])
    if cmd == "attempt":
        # §39.1 failed_attempts。不併進 `metric`，因為那一支問的是
        # 「這個數字說得出尺與材料嗎」，這一支存的是「這條路試過了，
        # 看到什麼，為什麼不要再試」。也不併進 `claims`：
        # 一次失敗的嘗試不是一句宣稱，它沒有真假只有發生過沒有。
        import attempts as AT
        return AT.main(argv[2:])
    if cmd == "pollution":
        # §40 污染登記簿。不併進 `claims`，因為那一支問的是「這句宣稱
        # 有沒有證據」，這一支存的是「這句話已經被推翻了，而且當初是
        # 什麼機制讓它錯的」。一筆污染不是一個待驗證的宣稱 —— 它的
        # 真假已經定了，留下來的價值在機制（§40 開頭那句：preserve the
        # mechanism, not only the corrected number）。
        #
        # 這個入口是 2026-09-18 補的。先前模組寫好了、桌面端與交接契約
        # 都在讀它，而**登一筆進去只能手寫 `python3 -c "import
        # pollution; ..."`**，`NEXT.md` 印的那一行「自己查」就是那個寫法。
        import pollution as PO
        return PO.main(argv[2:])
    if cmd == "antianchor":
        # §39 第 3 到第 6 步。不併進 `gate`，因為那一支做的是第 2 步與
        # 第 7 步（考讀懂沒有、給不給寫入權），這一支做的是中間那段
        # 獨立推導與和解。兩件事共用一個指令名會讓「考過了」變成兩種意思。
        import antianchor as AA
        return AA.main(argv[2:])

    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
