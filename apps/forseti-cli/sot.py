#!/usr/bin/env python3
"""Source-of-Truth Registry。v5.0 §12.2。

規格那張表逐字在 `PRECEDENCE` 裡。它回答的是一個很窄但很常搞錯的問題:

    「這一類狀態，該信哪個來源？」

ROADMAP P2 第 7 項的完成定義寫得很精確:
問「服務健康狀態該信誰」，它要回「程序管理器加健康端點」而不是「git」。

────────────────────────────────────────────────────

## 表是七行不是五行

2026-09-16 21:0x 寫這一支的時候，先前一次讀規格只讀到第 375 行就停了，
於是「§12.2 有五行」這句話差點被寫進程式碼。實際是第 371 到 377 行，
**七行**。多出來的兩行(Agent session state、Model training run)
正好是這個 repo 最缺的那兩塊。

這件事本身就是 §12.2 的示範:讀到一半的視窗跟完整的來源長得一模一樣，
而前者不會報錯。所以這一支的每一行都帶 `spec_line`，
`verify_spec()` 拿那一行原文回去比對，改一個字就會紅。

## 為什麼不做自動推斷「這個 repo 現在信誰」

看起來最聰明的做法是掃原始碼，猜每一類狀態現在從哪裡讀。
不做，理由跟 `pollution.py` 不做自動掃描同一條(BLOCKERS B-05):
靠文字判斷「這段程式在宣稱什麼」，抓到的是符合句型的段落，
不是真的來源，而漏掉的那些會長得跟「沒有來源」一模一樣。

所以 `BINDINGS` 是**人工登記**的，每一條都要附 file 加一段原文。
防腐爛的機制不是相信登記的人，是 `verify_bindings()`:
拿那段原文回檔案裡找，找不到就是 STALE，找到但行號變了就是 DRIFTED。
行號會漂是正常的，**原文消失不是**。

## 算不出來就是 None

跟這條線上其他模組同一條。`assess()` 只對真的量過的那一格給結論:

- 檔案內容那一行量得出來(工作區跟 HEAD 比對，`contract.py` 現成的)
- 其他幾行給的是「登記了什麼、登記的東西還在不在」，不是即時探測

沒探測就說沒探測，不投影成「健康」。一個沒有被檢查過的綠燈
比沒有燈更糟，因為它會讓人不去看。

零依賴，只在 `assess()` 需要時才 import `contract`。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: 規格原文的位置。`verify_spec()` 會回去比對。
SPEC = ("docs/sources/"
        "Forseti_Agent_Runtime_System_Architecture_Engineering_Spec_v5.0_"
        "2026-09-04.md")

#: §12.2 的表，逐字。英文欄位一個字都沒有改 ——
#: 中文那一欄標明是翻譯，不是規格原文(見 `preferred_zh` 的說明)。
PRECEDENCE: tuple[dict, ...] = (
    {
        "key": "current_file_content",
        "state_type": "Current file content",
        "preferred": "Live filesystem + hash; "
                     "Git only if deployed from same revision",
        "preferred_zh": "活的檔案系統加雜湊；只有在部署自同一個 revision 時才信 git",
        "spec_line": 371,
        "aliases": ("current file content", "檔案內容", "現在的檔案內容",
                    "檔案現在長什麼樣"),
    },
    {
        "key": "service_health",
        "state_type": "Service health",
        "preferred": "Process manager + health endpoint + socket/listener",
        "preferred_zh": "程序管理器加健康端點加 socket/listener",
        "spec_line": 372,
        "aliases": ("service health", "服務健康狀態", "服務健康",
                    "服務還活著嗎"),
    },
    {
        "key": "workflow_progress",
        "state_type": "Workflow progress",
        "preferred": "Durable workflow store, not session prose",
        "preferred_zh": "耐久的工作流程存放區，不是 session 散文",
        "spec_line": 373,
        "aliases": ("workflow progress", "工作進度", "流程進度",
                    "這件事做到哪了"),
    },
    {
        "key": "external_api_object",
        "state_type": "External API object",
        "preferred": "Fresh GET from external system",
        "preferred_zh": "直接跟外部系統要一次新的",
        "spec_line": 374,
        "aliases": ("external api object", "外部 api 物件", "外部系統的東西"),
    },
    {
        "key": "owner_decision",
        "state_type": "Owner decision",
        "preferred": "Decision ledger / signed policy",
        "preferred_zh": "決策帳本或簽署過的政策",
        "spec_line": 375,
        "aliases": ("owner decision", "owner 的決定", "她決定了什麼",
                    "決策"),
    },
    {
        "key": "agent_session_state",
        "state_type": "Agent session state",
        "preferred": "Provider-native session metadata + Forseti registry",
        "preferred_zh": "提供端原生的 session metadata 加 Forseti 自己的登記簿",
        "spec_line": 376,
        "aliases": ("agent session state", "session 狀態", "agent 狀態"),
    },
    {
        "key": "model_training_run",
        "state_type": "Model training run",
        "preferred": "Run ledger + checkpoints + metrics + "
                     "configuration snapshot",
        "preferred_zh": "訓練帳本加 checkpoint 加指標加設定快照",
        "spec_line": 377,
        "aliases": ("model training run", "訓練", "訓練跑了什麼"),
    },
)

#: 明確不是來源的東西。回答「不該信誰」跟「該信誰」一樣重要 ——
#: §12.2 那一行的重點正是「Git only if」，也就是預設不信 git。
NOT_SOURCE: dict[str, tuple[str, ...]] = {
    "current_file_content": ("git HEAD（除非部署自同一個 revision）",),
    "service_health": ("git", "上一次看到它活著的記憶"),
    "workflow_progress": ("session 散文", "對話歷史"),
    "external_api_object": ("本地快取", "上一次的回應"),
    "owner_decision": ("我事後整理的心得", "沒有出處的設定檔"),
    "agent_session_state": ("模型自己說它是誰",),
    "model_training_run": ("最後一次印出來的數字",),
}

#: 這個 repo 現在實際上從哪裡讀。**人工登記，不是掃出來的。**
#:
#: `evidence` 的每一項是 (相對路徑, 期待的行號, 那一行要出現的原文)。
#: 行號是提示，原文才是憑據 —— `verify_bindings()` 找的是原文。
#:
#: `state` 四種:
#:   BOUND        照規格的來源接上了
#:   PARTIAL      接上一半，另一半沒有來源
#:   NO_SOURCE    規格要的來源這個 repo 沒有
#:   NOT_APPLICABLE  這個 repo 沒有這一類狀態(要附可查核的依據)
BINDINGS: tuple[dict, ...] = (
    {
        "key": "current_file_content",
        "state": "BOUND",
        "uses": "工作區逐檔雜湊，git HEAD 只拿來當對照不當權威",
        "evidence": (
            ("apps/forseti-cli/contract.py", 549, "def _fingerprint"),
            ("apps/forseti-cli/contract.py", 1027, "def worktree_paths"),
            ("apps/forseti-cli/contract.py", 958, "def git_head"),
        ),
        "note": "這一行是七行裡唯一量得出即時答案的，見 assess()",
    },
    {
        "key": "service_health",
        "state": "NO_SOURCE",
        "uses": "",
        "evidence": (
            ("apps/forseti-cli/contract.py", 1338, '"process_status": NoSource'),
        ),
        "note": "watchdog.py 算的是 heartbeat 停滯，那是「有沒有在動」，"
                "不是「服務健康」。程序管理器與健康端點兩條線都沒有接，"
                "所以這一格不給燈號",
    },
    {
        "key": "workflow_progress",
        "state": "PARTIAL",
        "uses": "ledger.db 的 tasks / steps / events 三張表（sqlite，耐久）",
        "evidence": (
            ("apps/forseti-cli/ledger.py", 148,
             "CREATE TABLE IF NOT EXISTS tasks"),
            ("apps/forseti-cli/ledger.py", 157,
             "CREATE TABLE IF NOT EXISTS steps"),
            ("apps/forseti-cli/attempts.py", 93, "def record("),
        ),
        "note": "耐久存放區有了。「試過而且失敗的做法」這一類進度"
                "2026-09-17 22:xx 之前只活在 AUTO_CONTINUE_LOG 的散文裡，"
                "現在 attempts.py 是它的來源（contract.py 那一欄從 "
                "NO_SOURCE 變成 EMPTY）。仍然是接了一半，因為登記簿"
                "此刻 0 筆 —— 缺的是有人去登記，不是缺一個系統",
    },
    {
        "key": "external_api_object",
        "state": "NOT_APPLICABLE",
        "uses": "",
        "evidence": (
            ("apps/forseti-cli/migrate.py", 156, "socket.gethostname()"),
        ),
        "note": "2026-09-16 21:0x 查過 apps/forseti-cli、src、hooks 三個執行期目錄，"
                "沒有任何對外請求（migrate.py 那一處是取主機名，不是連線；"
                "tools/check-page-readable.py 是獨立工具，不在執行期路徑上）。"
                "沒有外部物件就沒有這一類狀態 —— 這是「不適用」，不是「還沒接」",
    },
    {
        "key": "owner_decision",
        "state": "PARTIAL",
        "uses": "帳本裡真的發生過的狀態轉換（TASK_STATE / HANDOFF / STOP）",
        "evidence": (
            ("apps/forseti-cli/desktop_api.py", 1133,
             "決策用帳本裡真的發生過的狀態轉換"),
            ("apps/forseti-cli/contract.py", 1387, '"claims_allowed": NoSource'),
        ),
        "note": "帳本這一半在。簽署過的政策物件不存在 ——"
                ".forseti/config.json 的開關是 owner 開的，"
                "但那個檔沒有簽章、沒有時間、沒有出處，"
                "所以它是設定不是決策帳本",
    },
    {
        "key": "agent_session_state",
        "state": "PARTIAL",
        "uses": "提供端原生的 session id 與 transcript jsonl",
        "evidence": (
            ("apps/forseti-cli/identity.py", 459, "def registry"),
            ("apps/forseti-cli/contract.py", 337, "def _logical_agent_id"),
        ),
        # 2026-09-16 22:5x 更正。先前這一句寫「§11.1 的 AgentIdentity
        # 沒有實作」，而 `identity.py` 在同一天 21:0x 就做好了。
        # 那句話是在寫下來之後才變成假的 —— 跟 `contract.py` 那一欄
        # 同一次腐爛，是 `verify_bindings()` 報 STALE 才查出來的。
        "note": "提供端那一半在。登記簿也在了（`identity.registry()`），"
                "但此刻 0 條登記，而帳本裡有 31 個 alias 沒有人認領，"
                "所以「換 session 不換的那個身份」現在仍然查不到值。"
                "缺的是有人去登記，不是缺一個系統",
    },
    {
        "key": "model_training_run",
        "state": "NOT_APPLICABLE",
        "uses": "",
        "evidence": (
            ("apps/forseti-cli/contract.py", 1331,
             '"dataset_manifest": NoSource'),
        ),
        "note": "這個專案不是訓練任務，沒有 run 也沒有 dataset。"
                "同樣是「不適用」不是「還沒接」",
    },
)

STATES = ("BOUND", "PARTIAL", "NO_SOURCE", "NOT_APPLICABLE")


# ---------------------------------------------------------------------------
# 查表
# ---------------------------------------------------------------------------

def keys() -> tuple[str, ...]:
    return tuple(r["key"] for r in PRECEDENCE)


def preferred(key: str) -> dict | None:
    """照 key 拿一整行。找不到回 None。"""
    for r in PRECEDENCE:
        if r["key"] == key:
            return dict(r)
    return None


#: 問句尾巴，**一張固定的字面清單**，不是句型推斷。
#: 剝掉它們是為了讓 ROADMAP 完成定義那一句原文
#: 「服務健康狀態該信誰」查得到，而不是讓比對變鬆。
#: 每加一個都要是有人真的這樣問過的字串。
SUFFIXES = ("該信誰", "要信誰", "該相信誰", "信誰", "該信哪個", "該看哪裡")


def _norm(text: str) -> str:
    t = (text or "").strip().lower().rstrip("？?。.").strip()
    for suf in SUFFIXES:
        if t.endswith(suf):
            t = t[: -len(suf)].strip()
            break
    return t


def lookup(text: str) -> dict:
    """拿一句話去問該信誰。

    **只認完全相符的別名**，不做模糊比對。理由是 B-05:
    模糊比對會給出一個看起來有回答的答案，而它符合的是字面不是意思。
    對不上就把合法的 key 全部列出來，讓問的人自己挑。

    唯一的放寬是 `SUFFIXES` 那張固定清單:剝掉問句尾巴之後仍然要
    **完全相符**。「含有某個別名」不算 —— 一句
    「服務健康狀態跟檔案內容哪個重要」含有兩個別名，
    而它問的不是這兩類的任何一類。
    """
    t = _norm(text)
    if not t:
        return {"ok": False, "why": "問句是空的", "valid": list(keys())}
    for r in PRECEDENCE:
        cands = [r["key"], r["state_type"].lower()] + [a.lower()
                                                       for a in r["aliases"]]
        if t in cands:
            return {"ok": True, "row": dict(r),
                    "answer": r["preferred"],
                    "answer_zh": r["preferred_zh"],
                    "not_source": list(NOT_SOURCE.get(r["key"], ())),
                    "spec": f"{SPEC}:{r['spec_line']}"}
    return {"ok": False,
            "why": f"對不上任何一類狀態:{text!r}。"
                   "這裡不做模糊比對(B-05)，所以寧可不回答",
            "valid": list(keys())}


def binding(key: str) -> dict | None:
    for b in BINDINGS:
        if b["key"] == key:
            return dict(b)
    return None


# ---------------------------------------------------------------------------
# 防腐爛
# ---------------------------------------------------------------------------

def verify_spec(repo: Path | None = None) -> dict:
    """七行的 state_type 與 preferred 是不是還跟規格原文一致。

    比對的是**那一行的原文**，不是有沒有這個字串在檔案某處出現 ——
    後者在一份四千行的規格裡幾乎一定會過，那種測試等於沒有。
    """
    base = Path(repo or REPO)
    f = base / SPEC
    if not f.exists():
        return {"ok": False, "why": f"規格檔不在:{SPEC}", "rows": []}
    lines = f.read_text(encoding="utf-8").splitlines()
    rows = []
    for r in PRECEDENCE:
        n = r["spec_line"]
        raw = lines[n - 1] if 0 < n <= len(lines) else ""
        hit = (r["state_type"] in raw) and (r["preferred"] in raw)
        rows.append({"key": r["key"], "line": n, "ok": hit,
                     "raw": raw.strip()})
    return {"ok": all(x["ok"] for x in rows), "rows": rows,
            "spec": SPEC, "checked": len(rows)}


def verify_bindings(repo: Path | None = None) -> dict:
    """每一條登記的憑據還在不在。

    三種結果:
      OK        原文在，行號也對
      DRIFTED   原文在，行號變了(正常，程式碼會動)
      STALE     原文找不到了 —— 這條登記不能再信
    """
    base = Path(repo or REPO)
    out = []
    for b in BINDINGS:
        items = []
        for path, line, needle in b["evidence"]:
            f = base / path
            if not f.exists():
                items.append({"path": path, "line": line, "needle": needle,
                              "state": "STALE", "why": "檔案不存在"})
                continue
            lines = f.read_text(encoding="utf-8").splitlines()
            found = [i + 1 for i, s in enumerate(lines) if needle in s]
            if not found:
                items.append({"path": path, "line": line, "needle": needle,
                              "state": "STALE", "why": "原文找不到了"})
            elif line in found:
                items.append({"path": path, "line": line, "needle": needle,
                              "state": "OK", "at": line})
            else:
                items.append({"path": path, "line": line, "needle": needle,
                              "state": "DRIFTED", "at": found[0],
                              "why": f"原文在，但在第 {found[0]} 行不是第 {line} 行"})
        out.append({"key": b["key"], "state": b["state"], "items": items,
                    "stale": sum(1 for x in items if x["state"] == "STALE"),
                    "drifted": sum(1 for x in items if x["state"] == "DRIFTED")})
    return {"ok": all(r["stale"] == 0 for r in out),
            "rows": out,
            "stale": sum(r["stale"] for r in out),
            "drifted": sum(r["drifted"] for r in out)}


# ---------------------------------------------------------------------------
# 現況
# ---------------------------------------------------------------------------

def _file_content_live(repo: Path | None = None) -> dict:
    """唯一量得出即時答案的那一行。

    §12.2 說 git 只有在「部署自同一個 revision」時才算來源。
    這裡量的就是那個條件成不成立:工作區跟 HEAD 有沒有差。
    量不到就回 None 加原因，不回 0 ——
    0 讀起來是「量過了，沒有差」，那是另一件事。
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import contract as C  # noqa: PLC0415
        w = C.worktree_paths(Path(repo) if repo else None)
    except Exception as e:                                  # noqa: BLE001
        return {"measured": False, "why": f"量不到:{e}",
                "git_authoritative": None}
    # `worktree_paths` 的回傳是 entries 加 problem,不是 ok 加 paths。
    # 空清單加 problem 是「沒量到」,空清單沒 problem 是「量過了,乾淨」——
    # 那支的 docstring 自己寫著這兩件事必須分得出來,這裡照它分。
    if w.get("problem"):
        return {"measured": False, "why": w["problem"],
                "git_authoritative": None}
    ents = w.get("entries") or []
    n = len(ents)
    tracked = sum(1 for e in ents if e.get("vcs") != "從來沒進版控")
    return {
        "measured": True,
        "divergent": n,
        "tracked_modified": tracked,
        "untracked": n - tracked,
        "git_authoritative": n == 0,
        "why": (f"工作區有 {n} 個檔跟 HEAD 不一致,"
                "所以 HEAD 指不到現在跑的程式碼,git 不是這一類狀態的來源"
                if n else "工作區跟 HEAD 一致,這一刻 git 也指得到"),
    }


def assess(repo: Path | None = None) -> dict:
    """七行各自的現況。

    **只有第一行有即時量測**，其餘六行給的是登記狀態加憑據新鮮度。
    這件事寫在回傳值裡(`live` 是 None 就是沒量)，不藏在註解。
    """
    vb = verify_bindings(repo)
    by_key = {r["key"]: r for r in vb["rows"]}
    rows = []
    for r in PRECEDENCE:
        b = binding(r["key"]) or {}
        v = by_key.get(r["key"], {})
        live = _file_content_live(repo) if r["key"] == "current_file_content" \
            else None
        rows.append({
            "key": r["key"],
            "state_type": r["state_type"],
            "preferred": r["preferred"],
            "preferred_zh": r["preferred_zh"],
            "not_source": list(NOT_SOURCE.get(r["key"], ())),
            "spec": f"{SPEC}:{r['spec_line']}",
            "state": b.get("state", "NO_SOURCE"),
            "uses": b.get("uses", ""),
            "note": b.get("note", ""),
            "evidence_ok": v.get("stale", 0) == 0,
            "evidence_drifted": v.get("drifted", 0),
            "live": live,
        })
    counts = {s: sum(1 for x in rows if x["state"] == s) for s in STATES}
    return {
        "rows": rows,
        "by_state": counts,
        "total": len(rows),
        "evidence_stale": vb["stale"],
        "evidence_drifted": vb["drifted"],
        # 誠實條款,兩條,都要看得見:
        "live_measured": 1,
        "live_note": ("七行裡只有「檔案內容」這一行有即時量測。"
                      "其餘六行的 live 是 None，那是「沒量」不是「健康」"),
        "not_applicable_note": ("NOT_APPLICABLE 是查證過的不適用，"
                                "不是還沒接。依據在每一行的 note 裡"),
        "source": "v5.0 §12.2 Source-of-truth precedence",
    }


def summary(repo: Path | None = None) -> dict:
    a = assess(repo)
    return {
        "total": a["total"],
        "by_state": a["by_state"],
        "evidence_stale": a["evidence_stale"],
        "evidence_drifted": a["evidence_drifted"],
        "live_measured": a["live_measured"],
        "live_note": a["live_note"],
        "source": a["source"],
    }


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--json":
        print(json.dumps(assess(), ensure_ascii=False, indent=2))
    elif arg == "--verify":
        print(json.dumps({"spec": verify_spec(),
                          "bindings": verify_bindings()},
                         ensure_ascii=False, indent=2))
    elif arg:
        print(json.dumps(lookup(" ".join(sys.argv[1:])),
                         ensure_ascii=False, indent=2))
    else:
        a = assess()
        print(f"§12.2 來源優先序　{a['total']} 類狀態")
        print(f"　{a['live_note']}")
        print()
        for r in a["rows"]:
            mark = {"BOUND": "接上了", "PARTIAL": "接了一半",
                    "NO_SOURCE": "沒有來源",
                    "NOT_APPLICABLE": "不適用"}[r["state"]]
            print(f"[{mark}] {r['state_type']}")
            print(f"　  該信:{r['preferred_zh']}")
            if r["uses"]:
                print(f"　  現在用:{r['uses']}")
            if r["live"] and r["live"].get("measured"):
                print(f"　  量出來:{r['live']['why']}")
            if r["note"]:
                print(f"　  {r['note']}")
            if not r["evidence_ok"]:
                print("　  ⚠ 憑據找不到了，這一條不能再信")
            print()
        print(f"憑據:過期 {a['evidence_stale']} 條、行號漂移 "
              f"{a['evidence_drifted']} 條")
