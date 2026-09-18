#!/usr/bin/env python3
"""目標錨點閘門。算 GAC，決定紫點有沒有資格出 CONFIRMED_DRIFT。§28.6

owner 2026-09-15：「接 GAC 閘門」

在這之前 `vitals.drift_alerts` 一律輸出 SUSPECTED_DRIFT，`excluded`
欄位裡寫著一句「GAC 算不出來，所以不出 CONFIRMED」。那句話是對的，
但它是寫死的字串，沒有真的算過，也說不出到底缺什麼。
一個永遠回同一句話的檢查，跟一個永遠回 OK 的檢查是同一種壞掉
（`.forseti/HANDOVER_FAILURE_2026-09-11.md` §17.4）。

## 為什麼不在 Python 重寫 GAC

`src/goalanchor.js` 有完整實作 477 行。照 `jsbridge.py` 的做法用 node
跑那一份，判斷邏輯留在 JavaScript。重寫會變成兩份會分歧的實作，
而分歧的那天沒有人會發現 —— 2026-09-14 實測過一次，`betrayal.py` 手寫
的表說 FP-11 是家族 B，`primitives.js` 說 A，兩邊各自看起來都對。

## 三個因子規格沒有定義

`docs/spec-v2.0.md` §5.1 給了公式

    GAC = max(valid_source_confidence × freshness × scope_match × provenance_integrity)

跟七級來源表，但 freshness / scope_match / provenance_integrity 怎麼算，
規格一個字都沒寫。這三個是這支程式自己決定的，所以每一個都必須指得回
可查證的事實：

freshness
    規格沒給衰減曲線。**預設回 None，讓 GAC 照 goalanchor.js 的規則
    算不出來。** 不自己編曲線的理由在 `REQUIRED_READING.md` 第 145 行：
    估出來的數字跟量出來的長得一模一樣，分辨它們的唯一辦法是回頭問
    「這個數字從哪裡來」，而那個問題平常沒有人會問。
    附了一條 CANDIDATE 曲線，預設關閉，要 owner 拍板才啟用。

scope_match
    `NORTH_STAR.md` 有一節「非目標」，六條。踩到幾條是查得出來的。

provenance_integrity
    來源鏈完不完整。`NORTH_STAR.md` 的出處指向「她的 ChatGPT 對話
    第六十節」，而 `REQUIRED_READING.md` 記著那份對話不在資料夾裡、
    連結由她提供。來源鏈斷掉是事實不是判斷。另外那個「Vol1 的平台
    北極星是雙向，NORTH_STAR.md 寫的是單向」的未決分歧也扣在這一項。

零依賴。node 不在就照實說跑不起來，不當機。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"
NORTH_STAR = REPO / ".forseti" / "NORTH_STAR.md"
TIMEOUT = 12

#: §5.1 的來源表。這裡不複製數值，只記名字；數值在 goalanchor.js。
SOURCE_OWNER_NOW = "EXPLICIT_OWNER_INSTRUCTION"
SOURCE_NORTH_STAR = "OWNER_CONFIRMED_NORTH_STAR"

#: freshness 的處理方式。
#:
#: **owner 2026-09-15 拍板:「freshness 不用時間衰減」。**
#:
#: 所以 freshness 恆為 1.0。這個 1.0 跟「把缺的因子當成 1」不是同一件事:
#: 前者是 owner 決定這個維度不參與衰減,後者是拿未知冒充已知。
#: 差別在於這裡說得出是誰決定的、什麼時候決定的,而且回傳裡帶著這個出處。
FRESHNESS_MODE = "NO_TIME_DECAY"
FRESHNESS_DECIDED_BY = "owner 2026-09-15"

#: 舊的候選衰減曲線。owner 已決定不用，留著是為了讓「曾經考慮過什麼」
#: 有跡可循，不是留著給人打開。
FRESHNESS_CANDIDATE_HALFLIFE_TURNS = 40

#: 已知的未決分歧，扣 provenance_integrity。出處在
#: `.forseti/REQUIRED_READING.md`「一件待決的事，不要自己決定」。
#: 2026-09-15 少了一條:owner 拍板「單向就好」，所以
#: 「Vol1 是雙向、NORTH_STAR.md 是單向」不再是未決分歧，是已確認的選擇。
#: 決定記在 `.forseti/DECISION_LEDGER.md`。
#: 每條帶自己的權重。**缺口不是只有「有」跟「沒有」兩種狀態。**
#: 2026-09-15 那份 ChatGPT 對話補進資料夾了，但補進去的是從分享頁
#: 抽取重組的版本，不是 OpenAI 的官方匯出。來源鏈接上了，可是接點
#: 本身有損耗，所以是半扣不是歸零。
#: 一個「補了就當作完全沒問題」的規則，會讓來源品質永遠看不出差別。
KNOWN_PROVENANCE_GAPS = (
    ("origin_document_extracted_not_official", 0.125,
     "北極星出處那份 ChatGPT 對話已補進資料夾，但是抽取版不是官方匯出"),
)


def node_bin() -> str | None:
    """跟 jsbridge 同一套找法。找不到就回 None，不猜路徑。"""
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        import jsbridge
        return jsbridge.node_bin()
    except Exception:
        for c in ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"):
            p = shutil.which(c) or (c if Path(c).exists() else None)
            if p:
                return p
        return None


def non_goals(path: Path | None = None) -> list[str]:
    """從 NORTH_STAR.md 讀非目標清單。不在程式裡寫死一份。"""
    p = path or NORTH_STAR
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    out: list[str] = []
    inside = False
    for ln in lines:
        s = ln.strip()
        if s.startswith("## "):
            inside = s.replace("#", "").strip() == "非目標"
            continue
        if inside and s.startswith("- "):
            out.append(s[2:].strip())
    return out


def scope_match(actions: list[str], goals: list[str] | None = None) -> dict:
    """§5.1 的 scope_match。**現在判不準，所以回 None。**

    【2026-09-15 同一天內兩種判法都誤判，第三次動手前停手】

    一，關鍵字比對。拿 `NORTH_STAR.md` 的非目標清單比對動作文字，
        出現「Claude Code、」就算踩到「不取代 Claude Code」。當天在讀
        GitNexus 的 README，滿篇都是 Claude Code / Cursor / Codex，
        scope_match 掉到 0.833，GAC 從 0.83 掉到 0.69。
        **我們只是在讀文件提到它。** 那是 `FS-INT-003` 說的 false positive。

    二，路徑範圍。改判「寫出去的東西落在專案內還是專案外」，結果 31 個
        路徑全部被判成專案外 —— 正則會從 URL 裡抓出 `/share/...` 這種
        片段，而 scratchpad 與 Dropbox 的來源文件本來就在專案外，
        那是正常工作不是離開範圍。

    兩次方向相反，錯法一樣:**拿一個規格沒有定義的東西，硬湊出一個
    看起來像量出來的數字。** `REQUIRED_READING.md` 第 145 行記過同一件事,
    估的跟量的長得一模一樣，分辨的唯一辦法是回頭問這個數字從哪裡來。

    所以現在回 None，讓 GAC 誠實地算不出來，並把需要 owner 定義的東西
    寫在 `why` 裡。非目標的字眼仍然抓，但降級成 `mentions` 弱訊號，
    **不進分母**，因為「提到」跟「在做」是兩件事。

    要讓這一項能算，需要 owner 定義「什麼算離開範圍」。
    """
    import re as _re
    ng = goals if goals is not None else non_goals()
    blob = "\n".join(str(a) for a in actions or [])
    mentions = []
    for g in ng:
        key = _re.sub(r"^不(?:是|把|要求|取代|讓|准|會|該)?\s*", "", g).strip()[:12]
        if len(key) >= 4 and key in blob:
            mentions.append({"non_goal": g, "matched": key})
    return {
        "value": None,
        "mentions": mentions,
        "tried": ["關鍵字比對(誤判:讀文件提到就算踩到)",
                  "路徑範圍(誤判:URL 片段與正常的專案外來源都算離開)"],
        "why": "規格沒有定義什麼算離開範圍，兩種判法都誤判過，"
               "需要 owner 定義才准給值"
               + (f"；這一段提到 {len(mentions)} 條非目標的字眼，"
                  "那是弱訊號不進分母" if mentions else ""),
    }


def provenance_integrity() -> dict:
    """來源鏈完不完整。已知的缺口一條扣一格，扣到最低 0。"""
    gaps = [g for g in KNOWN_PROVENANCE_GAPS]
    if not NORTH_STAR.exists():
        return {"value": None, "gaps": ["NORTH_STAR.md 不存在"],
                "why": "沒有北極星檔案，來源鏈無從談起"}
    # 每條缺口照自己的權重扣。級距是 PROVISIONAL，跟門檻一樣沒校準過。
    total = sum(g[1] for g in gaps)
    value = max(0.0, 1.0 - total)
    return {"value": round(value, 3),
            "gaps": [g[2] for g in gaps],
            "deductions": [{"id": g[0], "weight": g[1]} for g in gaps],
            "provisional": True,
            "why": f"{len(gaps)} 個已知缺口，合計扣 {round(total, 3)}"}


def freshness(turns_since: int | None, *, enable_candidate: bool = False) -> dict:
    """§5.1 的 freshness。

    **owner 2026-09-15 拍板不用時間衰減**，所以恆為 1.0。
    回傳一定帶 `decided_by`,因為一個寫死 1.0 而說不出為什麼的因子，
    跟把缺的因子當成 1 在資料上長得一模一樣。
    """
    if not enable_candidate:
        return {"value": 1.0,
                "mode": FRESHNESS_MODE,
                "decided_by": FRESHNESS_DECIDED_BY,
                "turns_since": turns_since,
                "why": f"{FRESHNESS_DECIDED_BY} 決定不用時間衰減，"
                       f"所以這個因子恆為 1.0，不隨輪數下降"}
    if turns_since is None:
        return {"value": None, "turns_since": None,
                "why": "算不出距離上一次 owner 指令幾輪"}
    half = FRESHNESS_CANDIDATE_HALFLIFE_TURNS
    v = 0.5 ** (turns_since / half)
    return {"value": round(v, 3), "turns_since": turns_since,
            "candidate": True, "half_life_turns": half,
            "why": f"CANDIDATE 曲線，半衰期 {half} 輪。未經校準"}


_RUNNER = r"""
import { readFileSync } from 'node:fs';
const [,, srcDir, payloadFile] = process.argv;
const payload = JSON.parse(readFileSync(payloadFile, 'utf8'));
const mod = await import(`${srcDir}/goalanchor.js`);
const r = mod.goalAnchorConfidence(payload.anchors || []);
console.log(JSON.stringify(r));
"""


def gac(anchors: list[dict]) -> dict:
    """呼叫 src/goalanchor.js 算 GAC。判斷邏輯不在這裡。"""
    n = node_bin()
    if not n or not SRC.is_dir():
        return {"ok": False, "gac": None, "may_confirm_drift": False,
                "why": "找不到 node，GAC 算不了" if not n else "找不到 src/"}

    stage = "寫暫存檔"
    tmp = Path(tempfile.mkdtemp(prefix="forseti-gac-"))
    # 收尾的結構本來就對（mkdtemp 的下一個敘述就是這個 try）。
    # 2026-09-18 加的只有 `stage`：兩個 write_text 也會丟 OSError，
    # 而底下那一句先前一律講成「叫不動 node」—— 寫檔失敗的時候
    # 那是一句指著 node 的假指控。
    try:
        runner = tmp / "run.mjs"
        runner.write_text(_RUNNER, encoding="utf-8")
        data = tmp / "payload.json"
        data.write_text(json.dumps({"anchors": anchors}, ensure_ascii=False),
                        encoding="utf-8")
        stage = "叫 node"
        r = subprocess.run([n, str(runner), str(SRC), str(data)],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "gac": None, "may_confirm_drift": False,
                "why": f"node 超過 {TIMEOUT} 秒沒回"}
    except OSError as e:
        return {"ok": False, "gac": None, "may_confirm_drift": False,
                "why": f"{stage}失敗：{e}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if r.returncode != 0:
        return {"ok": False, "gac": None, "may_confirm_drift": False,
                "why": (r.stderr or "")[:200]}
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "gac": None, "may_confirm_drift": False,
                "why": "node 回的不是 JSON"}
    out["ok"] = True
    return out


def build_anchors(*, actions: list[str] | None = None,
                  turns_since_owner: int | None = None,
                  enable_freshness_candidate: bool = False) -> dict:
    """組出要送進 goalanchor.js 的 anchor，每個因子都附理由。"""
    sm = scope_match(actions or [])
    pi = provenance_integrity()
    fr = freshness(turns_since_owner, enable_candidate=enable_freshness_candidate)

    anchor = {
        "source": SOURCE_NORTH_STAR,
        "freshness": fr["value"],
        "scopeMatch": sm["value"],
        "provenanceIntegrity": pi["value"],
    }
    return {"anchors": [anchor],
            "factors": {"freshness": fr, "scope_match": sm,
                        "provenance_integrity": pi}}


def gate(*, actions: list[str] | None = None,
         turns_since_owner: int | None = None,
         enable_freshness_candidate: bool = False) -> dict:
    """紫點的閘門。回「能不能出 CONFIRMED」跟「不能的話缺什麼」。"""
    built = build_anchors(actions=actions,
                          turns_since_owner=turns_since_owner,
                          enable_freshness_candidate=enable_freshness_candidate)
    r = gac(built["anchors"])

    missing = []
    for k, f in built["factors"].items():
        if f.get("value") is None:
            missing.append({"factor": k, "why": f.get("why", "")})

    return {
        "ok": r.get("ok", False),
        "gac": r.get("gac"),
        "goal_state": r.get("goal_state"),
        "may_confirm_drift": bool(r.get("may_confirm_drift")),
        "may_suspect_drift": bool(r.get("may_suspect_drift")),
        "thresholds_uncalibrated": r.get("thresholds_uncalibrated", True),
        "missing_factors": missing,
        "factors": built["factors"],
        "per_anchor": r.get("per_anchor"),
        "note": r.get("note") or r.get("why", ""),
        "at": time.time(),
    }


def main(argv: list[str]) -> int:
    enable = "--freshness-candidate" in argv
    print(json.dumps(gate(actions=[], turns_since_owner=None,
                          enable_freshness_candidate=enable),
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
