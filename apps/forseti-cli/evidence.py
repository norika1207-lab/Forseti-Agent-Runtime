#!/usr/bin/env python3
"""證據強度與填空衝動。v5.0 §7.2、§8.3

## 兩件事放在同一支，因為它們是同一條鏈的兩端

§7.2 的 E0 到 E4 回答「這個支撐有多強」。
§8.3 的填空衝動偵測回答「有沒有人把弱的當成強的用」。
分開放的話，第二個會拿不到第一個的判準，然後自己編一套。

## §8.3 的禁止捷徑

    UNKNOWN → UNSUPPORTED_FILL → ASSUMED_FACT → WRITE / COMMIT

正確的鏈是：

    UNKNOWN → ASK / SEARCH / VERIFY → HYPOTHESIS → EVIDENCE → DECISION

**2026-09-16 當天犯過兩次。** `goalgate.scope_match` 那個因子規格沒有
定義怎麼算，我先用關鍵字比對（讀文件提到 Claude Code 就判成在做取代
它的事），再用檔案路徑（URL 裡的路徑片段也被當成離開範圍）。
兩次都是同一條鏈:不知道怎麼算，想出一個貌似合理的算法，
當成可用的數字，拿去算 GAC。

那兩個數字的問題不是不準，是**它們長得跟量出來的一模一樣**。
`REQUIRED_READING.md` 第 145 行記著同一件事:分辨估的跟量的，
唯一辦法是回頭問「這個數字從哪裡來」，而那個問題平常沒有人會問。

所以這一支把「從哪裡來」變成一個必填欄位。
"""

from __future__ import annotations

#: §7.2 的證據強度。順序是 NORMATIVE，數值是 PROVISIONAL。
LEVELS: tuple[tuple[str, float, str], ...] = (
    ("E0", 0.00, "模型自己說的，沒有支撐"),
    ("E1", 0.30, "工具輸出、未驗證的路徑、快取狀態"),
    ("E2", 0.70, "新鮮的決定性檢查：stat / hash / git diff / API GET / 程序狀態"),
    ("E3", 0.85, "多個決定性來源獨立佐證"),
    ("E4", 1.00, "擁有者確認、簽署政策、外部系統的紀錄"),
)
_IDX = {k: i for i, (k, _, _) in enumerate(LEVELS)}
_W = {k: w for k, w, _ in LEVELS}

#: §8.3 的認知狀態。**UNSUPPORTED_FILL 是唯一不該存在的那一格。**
EPISTEMIC = ("UNKNOWN", "ASKED", "SEARCHED", "VERIFIED",
             "HYPOTHESIS", "EVIDENCE", "DECISION", "UNSUPPORTED_FILL",
             "ASSUMED_FACT")

#: 正確的鏈。每一格只能從這些來。
LEGAL_FROM: dict[str, tuple[str, ...]] = {
    "ASKED": ("UNKNOWN",),
    "SEARCHED": ("UNKNOWN", "ASKED"),
    "VERIFIED": ("SEARCHED", "HYPOTHESIS"),
    "HYPOTHESIS": ("UNKNOWN", "ASKED", "SEARCHED"),
    "EVIDENCE": ("VERIFIED", "HYPOTHESIS"),
    "DECISION": ("EVIDENCE",),
}

#: 禁止捷徑。出現任何一段就是 §8.3 的那條鏈。
FORBIDDEN_EDGES = (
    ("UNKNOWN", "ASSUMED_FACT"),
    ("UNKNOWN", "DECISION"),
    ("UNSUPPORTED_FILL", "ASSUMED_FACT"),
    ("ASSUMED_FACT", "DECISION"),
    ("HYPOTHESIS", "DECISION"),      # 少了 EVIDENCE 那一格
    ("UNKNOWN", "EVIDENCE"),
)


def level_index(level: str) -> int:
    return _IDX.get(level, -1)


def weight(level: str) -> float:
    return _W.get(level, 0.0)


def can_support(*, claim_level: str, evidence_level: str) -> dict:
    """這個等級的證據，撐不撐得起這個等級的宣稱。

    **弱的不准冒充強的。** 這是整套系統的底線:
    E0 的東西不能被當成 E2 用，不論它聽起來多合理。
    """
    ci, ei = level_index(claim_level), level_index(evidence_level)
    if ci < 0 or ei < 0:
        return {"ok": False, "why": "不認得的等級",
                "claim": claim_level, "evidence": evidence_level}
    ok = ei >= ci
    return {
        "ok": ok,
        "claim": claim_level,
        "evidence": evidence_level,
        "gap": max(0, ci - ei),
        "why": ("證據夠強" if ok else
                f"宣稱要 {claim_level}，證據只有 {evidence_level}。"
                "弱的不准冒充強的"),
    }


def check_chain(steps: list) -> dict:
    """走一遍認知鏈，找出禁止捷徑。§8.3

    `steps` 是 [{state, note}]，按時間順序。
    """
    seq = [str(s.get("state") or "") for s in (steps or [])]
    bad = []
    for i in range(len(seq) - 1):
        edge = (seq[i], seq[i + 1])
        if edge in FORBIDDEN_EDGES:
            bad.append({
                "at_step": i,
                "edge": f"{edge[0]} → {edge[1]}",
                "why": "§8.3 的禁止捷徑：沒有經過證據就下了結論",
            })
        legal = LEGAL_FROM.get(seq[i + 1])
        if legal and seq[i] not in legal and edge not in FORBIDDEN_EDGES:
            bad.append({
                "at_step": i,
                "edge": f"{edge[0]} → {edge[1]}",
                "why": f"{seq[i + 1]} 只能從 {'、'.join(legal)} 來",
            })
    return {
        "ok": not bad,
        "steps": len(seq),
        "violations": bad,
        "chain": " → ".join(seq),
        "legal_chain": "UNKNOWN → ASK/SEARCH/VERIFY → HYPOTHESIS → EVIDENCE → DECISION",
    }


def gap_fill(value, *, source: str, derivation: str = "") -> dict:
    """一個數字是量出來的還是編出來的。

    **`source` 是必填。** 說不出從哪裡來的數字，一律判成填空 ——
    不是因為它一定錯，是因為它跟量出來的長得一模一樣，
    而分辨它們的唯一辦法就是問這個問題。

    `source` 收三種：
      MEASURED   實際量到的（讀檔、跑指令、查 API）
      DEFINED    有人定義的（規格寫的、owner 拍板的）
      ESTIMATED  推估的

    ESTIMATED 不是不能用，是**不准假裝自己是另外兩種**。
    """
    ok_sources = ("MEASURED", "DEFINED", "ESTIMATED")
    src = (source or "").strip().upper()
    if src not in ok_sources:
        return {
            "is_fill": True,
            "value": value,
            "source": src or "(沒說)",
            "level": "E0",
            "why": f"說不出來源。來源要是 {'、'.join(ok_sources)} 之一。"
                   "說不出從哪裡來的數字，跟量出來的長得一模一樣",
        }
    level = {"MEASURED": "E2", "DEFINED": "E4", "ESTIMATED": "E0"}[src]
    return {
        "is_fill": src == "ESTIMATED",
        "value": value,
        "source": src,
        "level": level,
        "derivation": derivation,
        "why": ("量出來的" if src == "MEASURED" else
                "有人定義的" if src == "DEFINED" else
                "推估的。可以用，但不准當成量出來的"),
    }


def summary() -> dict:
    return {
        "levels": [{"level": k, "weight": w, "means": d} for k, w, d in LEVELS],
        "legal_chain": "UNKNOWN → ASK/SEARCH/VERIFY → HYPOTHESIS → EVIDENCE → DECISION",
        "forbidden": [f"{a} → {b}" for a, b in FORBIDDEN_EDGES],
        "note": "弱的不准冒充強的。一個說不出來源的數字，"
                "跟量出來的長得一模一樣 —— 而那正是它危險的地方",
    }


# ---------------------------------------------------------------------------
# Evidence 這個實體。v5.0 §5 的 key fields、§7.2 的強度、§33.3 的獨立性
# ---------------------------------------------------------------------------
#
# ## 這一段 2026-09-18 才長出來，理由要記下來
#
# 上面那幾支函式回答「這個支撐有多強」，但它們收的是字串參數，
# 算完就沒了。所以一筆證據帶不出 id，`lineage.py` 的 `readiness()`
# 把 evidence 判成 `NO_SOURCE`，而 §6.3 的三條邊
# （DERIVED_FROM、VERIFIES、REFUTES）因此連不起來。
#
# **缺的不是分級，是實體。** 2026-09-18 07:xx 那一輪查出來的時候，
# 四份文件都在講 claim 與 decision，沒有一份提到 evidence。
#
# ## 欄位的出處，每一個都指得回規格
#
# v5.0 §5 那張表寫的是：
#
#     Evidence | Observed support/refutation. |
#     evidence_id, source, strength, freshness, content_hash
#
# 所以 `id` / `sources` / `strength` / `content_hash` 是規格欄位。
# `freshness` 不存成欄位，因為 §10 定義它是「time since verification,
# resource version drift」，兩半都是**算出來的**不是記下來的：
# 存一個寫下當時的新鮮度，下一次讀到的會是一個過期的新鮮度。
# 所以存 `observed_at`，新鮮度由 `freshness()` 當場算。
#
# 三個欄位不在 §5 那一行裡，標明是誰加的與為什麼：
#
# - `about`：這筆證據在支撐或反駁什麼。不填的話一筆證據不知道
#   在講哪件事，而 §6.3 的 VERIFIES / REFUTES 正是要指向那件事。
# - `captured_by`：誰觀察到的。跟 `metrics.measured_by`、
#   `pollution.verifier`、`attempts.verifier` 同一個形狀。
# - `upstream`：這筆證據的上游前提、資料集、規則表、快取或衍生產物。
#   §33.3 要 Forseti 認得出「看起來獨立的證據共用上游」，
#   而那件事靠事後猜猜不出來，要登記的當下寫下來。
#
# ## 刻意不做的兩件
#
# 一，**不自動推斷 strength。** 規格沒有給「什麼樣的觀察算 E2」的
# 判定式，自己補一個貌似合理的就是 §8.3 的填空。所以 `strength`
# 必填，不在 E0-E4 裡就拒收。
#
# 二，**不自動產生任何一條 lineage 邊。** 這一段只讓 evidence 指得到，
# 邊要不要連是另一次判斷（`lineage.add()` 的 `basis` 必填就是那個判斷
# 的落點）。上一輪對 PRODUCES 做過同一個決定，理由一樣。

import hashlib
import json as _json
import re as _re
import sys
import time as _time
from dataclasses import dataclass as _dataclass, field as _field
from pathlib import Path as _Path

_REPO = _Path(__file__).resolve().parents[2]

#: §7.2 的五級。**唯一來源是上面的 `LEVELS`**，不在這裡再抄一份。
STRENGTHS: tuple[str, ...] = tuple(k for k, _, _ in LEVELS)


class EvidenceError(Exception):
    """這筆證據不合 §7.2 或 §5。拒收而不是修正。

    跟 `claims.ClaimError`、`lineage.LineageError` 同一條理由：
    一筆被默默補過欄位的證據，比一筆被退回的危險。
    """


@_dataclass(frozen=True)
class Evidence:
    """一筆觀察到的支撐或反駁。§5、§7.2

    `frozen` 是因為一筆證據記的是**某一刻觀察到什麼**。事後改它等於
    改歷史，而下游的 VERIFIES / REFUTES 邊會指向一個已經不是當初那筆
    的東西。要更新的話是登記新的一筆，舊的留著。
    """

    about: str
    sources: tuple[str, ...]
    strength: str
    captured_by: str
    content_hash: str = ""
    upstream: tuple[str, ...] = ()
    independence_basis: str = ""
    authority: str = ""
    observed_at: float = _field(default_factory=_time.time)
    id: str = ""

    def __post_init__(self):
        if self.strength not in STRENGTHS:
            raise EvidenceError(
                f"不是合法的強度：{self.strength!r}。"
                f"合法的是 {'/'.join(STRENGTHS)}（v5.0 §7.2）")
        if not str(self.about).strip():
            raise EvidenceError(
                "about 是空的。一筆不知道在支撐什麼的證據，"
                "在需要它的時候（§6.3 的 VERIFIES / REFUTES 要指過去）"
                "正好指不到東西")
        if not self.sources:
            raise EvidenceError("sources 是空的。§5 那一行的 source 是必填")
        if not str(self.captured_by).strip():
            raise EvidenceError("captured_by 是空的。說不出是誰觀察到的，"
                                "這筆證據就追不回去")
        # E3 的規格原文是 independent corroboration from multiple
        # deterministic sources。兩個條件都在這裡變成會執行的約束，
        # 而不是註解裡的一句話。
        if self.strength == "E3":
            if len(self.sources) < 2:
                raise EvidenceError(
                    f"E3 的定義是「多個決定性來源獨立佐證」（§7.2），"
                    f"收到 {len(self.sources)} 個來源。"
                    "一個來源的東西不是 E3，不論它多確定")
            if not str(self.independence_basis).strip():
                raise EvidenceError(
                    "E3 要說出這幾個來源憑什麼算獨立（§33.3）。"
                    "共用上游前提的兩個指標是同一個錯誤數兩次，"
                    "而那件事事後猜不出來，要登記的當下寫下來")
        # E4 的規格原文是 owner-confirmed / signed policy /
        # external system of record。三種都有一個具名的授權方。
        if self.strength == "E4" and not str(self.authority).strip():
            raise EvidenceError(
                "E4 要有具名的 authority（§7.2：owner 確認、簽署的政策、"
                "或外部的真實系統）。沒有授權方的 E4 就只是一句話")
        if not self.id:
            object.__setattr__(self, "id", _make_eid(self))

    def to_row(self) -> dict:
        return {
            "id": self.id, "about": self.about,
            "sources": list(self.sources), "strength": self.strength,
            "captured_by": self.captured_by,
            "content_hash": self.content_hash,
            "upstream": list(self.upstream),
            "independence_basis": self.independence_basis,
            "authority": self.authority,
            "observed_at": self.observed_at,
        }


def _make_eid(ev: "Evidence") -> str:
    """id 由內容決定，所以同一筆觀察登兩次會得到同一個 id。

    **`observed_at` 進雜湊。** 同一個檔案在兩個時刻各看一次是兩筆證據，
    不是一筆，因為 §10 的 freshness 對它們的答案不一樣。
    """
    raw = "|".join([ev.about, "\x1f".join(ev.sources), ev.strength,
                    ev.content_hash, f"{ev.observed_at:.6f}"])
    return "ev-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


#: 一個 evidence id 長什麼樣。`_make_eid()` 產的就是這個形狀，
#: 這一條存在是為了讓別的模組（`claims.evidence_refs`）判得出
#: 「這個字串是不是指得回這裡的一筆」，而不是各自寫一個正則。
_EID_RE = _re.compile(r"^ev-[0-9a-f]{10}$")


def is_evidence_id(s) -> bool:
    """這個字串是不是這個模組產的 id。

    **只判形狀，不判存不存在。** 兩件事分開是因為它們的答案會在不同
    時刻改變：形狀不會變，而「磁碟上有沒有那一筆」隨時會變（jsonl 是
    append-only，但測試會換路徑）。合成一支的話，呼叫端要拒收一個
    亂寫的字串時會被迫先去碰磁碟。存不存在用 `get()` 問。
    """
    return bool(_EID_RE.match(str(s)))


def log_path(repo: _Path | None = None) -> _Path:
    """證據落在哪。公開，因為守門要問得到「不傳參數的時候它去哪」
    （`tests/test_module_write_targets.py` 的 `_default_of`）。"""
    return _Path(repo or _REPO) / ".forseti" / "evidence.jsonl"


def record(*, about: str, sources, strength: str, captured_by: str,
           content_hash: str = "", upstream=(), independence_basis: str = "",
           authority: str = "", observed_at: float | None = None,
           path: _Path | None = None) -> dict:
    """登記一筆證據。不合規格就退回，不補欄位。

    回 `{"ok": bool, ...}` 而不是丟例外，跟 `lineage.add()`、
    `pollution.record()` 同一個形狀：呼叫端大多是要把理由印出來，
    不是要中斷。
    """
    try:
        ev = Evidence(
            about=str(about),
            sources=tuple(str(s).strip() for s in (sources or ()) if str(s).strip()),
            strength=str(strength).strip(),
            captured_by=str(captured_by),
            content_hash=str(content_hash or ""),
            upstream=tuple(str(u).strip() for u in (upstream or ()) if str(u).strip()),
            independence_basis=str(independence_basis or ""),
            authority=str(authority or ""),
            observed_at=(_time.time() if observed_at is None
                         else float(observed_at)),
        )
    except EvidenceError as e:
        return {"ok": False, "why": str(e)}
    p = path or log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(ev.to_row(), ensure_ascii=False) + "\n")
    return {"ok": True, "evidence": ev.to_row()}


def load(path: _Path | None = None) -> list[dict]:
    p = path or log_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(_json.loads(line))
        except ValueError:
            continue
    return out


def get(evidence_id: str, *, path: _Path | None = None) -> dict | None:
    for row in load(path):
        if row.get("id") == evidence_id:
            return row
    return None


def freshness(row: dict, *, now: float | None = None,
              current_hash: str | None = None) -> dict:
    """§10 的 Evidence Freshness：離上一次驗證多久，資源版本有沒有飄。

    **兩半分開回。** 時間那一半永遠算得出來，版本飄移那一半要有
    兩個雜湊才算得出來。合成一個數字的話，「沒飄」跟「量不到有沒有飄」
    會長得一樣，而那兩件事的處置完全不同（一個可以用，一個要先去量）。
    """
    t = float(now if now is not None else _time.time())
    age = t - float(row.get("observed_at") or 0.0)
    stored = str(row.get("content_hash") or "")
    if not stored:
        drift, why = None, ("這筆沒有 content_hash，所以資源版本有沒有飄"
                            "量不到。不是沒飄")
    elif current_hash is None:
        drift, why = None, "沒有給現在的 content_hash，比不了"
    else:
        drift = stored != str(current_hash)
        why = "內容跟登記時不一樣了" if drift else "內容跟登記時一樣"
    return {"id": row.get("id"), "age_seconds": age, "drift": drift,
            "why": why, "strength": row.get("strength")}


def independence(rows: list[dict]) -> dict:
    """§33.3 的 Correlated Evidence Detector。

    幾筆看起來各自獨立的證據，共用上游前提的話，它們是同一個錯誤
    被數了很多次。規格要的四個值都在這裡回：`raw_support_count`、
    `independent_support_count`、`shared_assumption`、
    `confirmation_discount`。

    **判定靠登記的 `upstream`，不靠猜。** 沒有登記上游的那幾筆
    單獨列在 `unknown_ancestry`，**不計入獨立支撐數** ——
    把「不知道上游」當成「沒有共用上游」正是 §8.3 的填空，
    而它會讓獨立支撐數看起來比實際多。
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    known = [r for r in rows if (r.get("upstream") or [])]
    unknown = [r for r in rows if not (r.get("upstream") or [])]
    # 共用任何一個上游元素的幾筆算同一群。用聯集合併，不是只比第一個。
    groups: list[tuple[set, list[str]]] = []
    for r in known:
        ups = {str(u) for u in (r.get("upstream") or [])}
        hit = [g for g in groups if g[0] & ups]
        if not hit:
            groups.append((set(ups), [str(r.get("id") or "")]))
            continue
        merged_up: set = set(ups)
        merged_ids: list[str] = [str(r.get("id") or "")]
        for g in hit:
            merged_up |= g[0]
            merged_ids += g[1]
            groups.remove(g)
        groups.append((merged_up, merged_ids))
    shared = sorted({u for g in groups if len(g[1]) > 1 for u in g[0]})
    ind = len(groups)
    return {
        "raw_support_count": len(rows),
        "independent_support_count": ind,
        "unknown_ancestry": [str(r.get("id") or "") for r in unknown],
        "shared_assumption": shared,
        "confirmation_discount": bool(shared) or bool(unknown),
        "groups": [{"upstream": sorted(g[0]), "evidence": sorted(g[1])}
                   for g in groups],
        "why": ("有幾筆共用上游，照 §33.3 要打折" if shared else
                "有幾筆沒登記上游，獨立性量不到，所以照 §33.3 要打折"
                if unknown else "沒有共用的上游"),
    }


def store_summary(repo: _Path | None = None) -> dict:
    """磁碟上有幾筆、各強度幾筆。給 `forseti doctor` 用。"""
    p = log_path(repo)
    rows = load(p)
    by: dict[str, int] = {}
    for r in rows:
        by[str(r.get("strength") or "?")] = by.get(str(r.get("strength") or "?"), 0) + 1
    return {"count": len(rows), "path": str(p), "by_strength": by,
            "addressable": bool(rows),
            "independence": independence(rows) if rows else None}


def lines(repo: _Path | None = None) -> list[str]:
    """印進 doctor 的幾行。**零筆也印** ——
    不印的話「還沒有證據」跟「有證據而且都好」長得一樣。
    """
    s = store_summary(repo)
    out = [f"    磁碟上 {s['count']} 筆（§7.2 的強度分級在 evidence.py）"]
    if not s["count"]:
        out.append("      實體與儲存在了，一筆都還沒有人登。"
                   "§6.3 的 DERIVED_FROM / VERIFIES / REFUTES 因此仍然連不起來")
        return out
    out.append("      各強度：" + "、".join(
        f"{k} {v}" for k, v in sorted(s["by_strength"].items())))
    ind = s["independence"] or {}
    out.append(f"      §33.3 獨立支撐　{ind.get('independent_support_count')}"
               f" / 原始 {ind.get('raw_support_count')}")
    if ind.get("shared_assumption"):
        out.append("      共用上游：" + "、".join(ind["shared_assumption"]))
    if ind.get("unknown_ancestry"):
        out.append(f"      沒登記上游的 {len(ind['unknown_ancestry'])} 筆"
                   "不計入獨立支撐數")
    return out


# ---------------------------------------------------------------------------
# 人工登記入口。§7.2
# ---------------------------------------------------------------------------


#: 模板裡那些「你要自己填」的格子長什麼樣。`register` 看到這個形狀就拒收。
#:
#: 存在的理由不是排版。`template` 印出來的東西原樣送回 `register`
#: 的話，不擋的話會登記成一筆 `about` 是「<這筆證據在支撐什麼 一定要填>」
#: 的證據 —— 每一欄都有值、`Evidence.__post_init__` 全部放行、
#: 畫面上跟一筆真的證據長得一模一樣。那正是 §8.3 的
#: UNSUPPORTED_FILL：不知道填什麼的時候，填一個看起來像值的東西。
_PLACEHOLDER_RE = _re.compile(r"^\s*<.*>\s*$", _re.S)


def is_placeholder(v) -> bool:
    """這個值是不是模板留下的空格子，不是人填的東西。

    只判字串。list 裡的每一項各自判（`sources` 的模板是一個單元素 list）。
    """
    return bool(isinstance(v, str) and _PLACEHOLDER_RE.match(v))


#: `template` 印出來的欄位順序與說明。順序照 `Evidence` 的欄位宣告，
#: 不另外排 —— 兩邊漂開的話，讀模板的人看到的欄位順序會跟讀
#: `to_row()` 的人看到的不一樣，而那個差異沒有任何資訊。
TEMPLATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("about", "這筆證據在支撐或反駁什麼"),
    ("sources", "從哪裡看到的，一個或多個"),
    ("strength", "E0 到 E4，見 `forseti evidence levels`"),
    ("captured_by", "是誰觀察到的"),
    ("content_hash", "看到的那個東西的雜湊，沒有就留空字串"),
    ("upstream", "這筆證據自己站在哪幾筆上面，沒有就留空 list"),
    ("independence_basis", "E3 才要：這幾個來源憑什麼算獨立（§33.3）"),
    ("authority", "E4 才要：具名的授權方"),
)

#: 這幾欄一定要人自己填，模板給的是空格子不是預設值。
_MUST_FILL = ("about", "sources", "strength", "captured_by")

#: `main()` 認得的子指令。**不認得的不准掉進預設那一條** ——
#: 打錯字的人會拿到一份看起來正常的報告，然後以為自己登記過了。
SUBCOMMANDS: tuple[str, ...] = ("list", "levels", "template", "register", "show")


def template() -> dict:
    """一份空白的登記表。

    ## 為什麼不預填 `observed_at`

    `metrics.template()` 預填 `measured_at=time.time()`，這一支刻意不。
    兩邊問的不是同一件事：那一欄是「這個數字什麼時候量的」，而產模板
    跟量數字在同一輪；這一欄是「這件事什麼時候被看到的」，而人拿模板
    去登的常常是**更早**發生的觀察。預填的話那個時間會悄悄變成
    「產模板的時刻」，而 `observed_at` 進 id 的雜湊（`_make_eid()`），
    所以同一筆觀察在兩個時刻登會得到兩個 id。

    不填就是登記當下，那是 `record()` 的預設，寫在下面那行註記裡。
    """
    tpl: dict = {}
    for k, zh in TEMPLATE_FIELDS:
        if k == "sources":
            tpl[k] = [f"<{zh}　一定要填>"]
        elif k == "upstream":
            tpl[k] = []
        elif k in _MUST_FILL:
            tpl[k] = f"<{zh}　一定要填>"
        else:
            tpl[k] = ""
    return tpl


def check_fillable(kw: dict) -> list[str]:
    """登記之前先看有沒有沒填的格子。回一串理由，空的代表可以往下走。

    **這一支跟 `Evidence.__post_init__` 不重疊。** 那邊管的是
    「這個值合不合 §7.2」，這邊管的是「這個值是不是根本還沒填」。
    分開是因為第二種錯誤合法：一個佔位字串是合法的 `about`。
    """
    why: list[str] = []
    for k in _MUST_FILL:
        v = kw.get(k)
        if v is None or (isinstance(v, str) and not v.strip()):
            why.append(f"{k} 沒有填")
            continue
        if is_placeholder(v):
            why.append(f"{k} 還是模板留的空格子：{v}")
        if isinstance(v, (list, tuple)):
            if not [x for x in v if str(x).strip()]:
                why.append(f"{k} 是空的")
            for x in v:
                if is_placeholder(x):
                    why.append(f"{k} 裡還有模板留的空格子：{x}")
    for k in ("content_hash", "independence_basis", "authority"):
        if is_placeholder(kw.get(k)):
            why.append(f"{k} 還是模板留的空格子：{kw.get(k)}")
    return why


def _arg(argv: list, name: str) -> str | None:
    # `--path=X` 這種等號寫法先前被靜默丟掉：`name in argv` 對
    # `--path=X` 不成立，於是回 None，呼叫端就去讀正本。2026-09-18
    # 實測 `forseti evidence list --path=<裡面有 1 筆>` 回「0 筆」，
    # 而正本此刻真的是 0 筆 —— 錯的答案跟對的答案長得一模一樣。
    # 這跟 08:2x 那一輪修的「旗標被當成子指令」是同一個形狀換一個
    # 入口回來。`metrics.py` 與 `attempts.py` 的 `_arg` 本來就收
    # 等號，這裡是補齊，不是新增一種寫法。
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if str(a).startswith(name + "="):
            return str(a).split("=", 1)[1]
    return None


def _flag_without_value(argv: list, name: str) -> bool:
    """旗標出現了，可是後面沒有值。

    這跟「旗標沒出現」要分得開。`_arg` 兩種都回 None，而呼叫端拿
    None 當「沒指定，讀正本」——於是 `forseti evidence list --path`
    （手滑漏掉路徑）會去讀正本並回報一份看起來正常的報告。
    2026-09-18 實測 `forseti attempt list --path` 回的是正本那筆
    att-2bb74c352d，五個欄位完整印出來。**那個人以為他看到的是
    自己指定的檔。**

    等號寫法不算在內：`--path=` 是明確給了一個空字串，
    跟沒寫完不是同一件事，留給呼叫端自己判。
    """
    # 「後面那個東西是另一個旗標」也算沒給值。2026-09-18 實測的後果：
    # `antianchor classify <id> blockers CHANGED_REALITY --by --reason 環境變了`
    # 會 exit=0、印「記下了」、而磁碟上那一筆 CLASSIFY 的 `by` 是
    # `--reason`。§39 那四類沒有一類算得出來，所以每一筆分類都要指得回
    # 是誰判的 —— 指回一個旗標名等於指不回任何人，而畫面上跟成功一樣。
    # `classify()` 內部本來就擋空字串（`by` 必填），所以擋不住的不是空的，
    # 是被下一個旗標填滿的。三支 `show --id` 那一半則是診斷指錯：
    # 回「不在登記簿上」，那個人會以為那筆資料不存在。
    #
    # 代價講清楚：真的要傳一個以 `--` 開頭的值，等號那條路還在
    # （`--by=--reason` 照樣拿得到 `--reason`），所以沒有失去表達能力。
    # 只認兩個減號，`-1` 這種值不受影響。
    return any(a == name for a in argv) and not any(
        (a == name and i + 1 < len(argv)
         and not str(argv[i + 1]).startswith("--"))
        or str(a).startswith(name + "=")
        for i, a in enumerate(argv))



def _unknown_flags(argv: list, known: tuple) -> list:
    """認不得的旗標名。打錯字不准靜默走預設。

    2026-09-18 實測，五支的打錯字後果分三級，**沒有一支會說
    「我不認得這個旗標」**：

    | 寫法 | exit | 實際發生的事 |
    |---|---|---|
    | `probe-model run --yes --onlyy X` | 1 | 不過濾，跑滿 36 次真呼叫 |
    | `antianchor status --roott X` | 0 | 讀正本，畫面跟成功一樣 |
    | `attempt record --retry-conditionn X` | 0 | 印「登錄了」，那一欄落地是空的 |
    | `metric template --transcriptt X` | 0 | 模板照印，缺席理由指錯原因 |
    | `evidence show --idd X` | 2 | 報錯，可是怪「要一個 id」 |

    跟 `_flag_without_value` 不是同一件事：那一支問的是「這個旗標
    後面有沒有值」，前提是旗標名對得上。名字打錯的時候那一支
    一律不觸發 —— 它 `any(a == name ...)` 找的是正確的那個名字。

    判準只認兩個減號開頭的 token，取等號之前那一段比對，所以
    `--by=--reason` 這種明著傳減號開頭的值照樣收（比的是 `--by`）。
    裸的 `--` 跳過：這五支都沒有實作那個慣例標記，這道守門不替
    它作決定，維持現況的忽略。
    """
    out = []
    for a in argv:
        s = str(a)
        if not s.startswith("--") or s == "--":
            continue
        name = s.split("=", 1)[0]
        if name not in known and name not in out:
            out.append(name)
    return out

def _print_row(r: dict) -> None:
    print()
    print(f"  {r['id']}　{r['strength']}")
    print(f"    支撐什麼　{r['about']}")
    print(f"    來源　　　{'、'.join(r.get('sources') or []) or '（沒有）'}")
    print(f"    誰看到的　{r.get('captured_by') or '（沒有）'}")
    if r.get("content_hash"):
        print(f"    雜湊　　　{r['content_hash']}")
    if r.get("upstream"):
        print(f"    上游　　　{'、'.join(r['upstream'])}")
    if r.get("independence_basis"):
        print(f"    獨立憑據　{r['independence_basis']}")
    if r.get("authority"):
        print(f"    授權方　　{r['authority']}")
    print(f"    觀察時刻　{r.get('observed_at')}")


#: `main()` 認得的全部旗標。跟底下那幾個 `_arg(rest, "--x")` 各寫
#: 一份，`tests/test_cli_flag_dispatch.py` 有一條盯著不漂開 ——
#: 漂開的話會出現「守門說認得、`main()` 裡沒人讀」的旗標，那種
#: 打對了也沒用，跟打錯字一樣靜默。整支共用一份不是每個子指令一份。
KNOWN_FLAGS: tuple[str, ...] = ("--path", "--from", "--id")


def main(argv: list) -> int:
    """`forseti evidence <list|levels|template|register|show>`

    §7.2。這一支存在的理由是 `record()` 先前只有程式碼叫得到 ——
    2026-09-18 的幾輪把 Evidence 這個實體、它的落地、以及 claim 那一端
    的 `attach_evidence()` 都做好了，而磁碟上仍然 0 筆，因為**人沒有
    地方登**。缺的不是資料，是入口。

    `register` 收的是一份 JSON 檔不是一串旗標，同 `forseti metric
    register` 的理由：這份記錄的每一欄缺席都有後果（E3 沒有
    independence_basis 會被退、E4 沒有 authority 會被退），用旗標填
    的話人會為了讓指令跑得動而亂填。
    """
    # 第一個參數以 `-` 開頭的時候它是旗標不是子指令。少了這一行，
    # `forseti evidence --path X` 會把 `--path` 當成子指令名，掉進
    # 預設那一條，而 `--path` 留在 `sub` 裡於是 `rest` 只剩下 X ——
    # 結果是**讀正本而不是讀 X，回報 0 筆**。這個錯不會報錯：
    # 正本此刻真的是 0 筆，所以錯的答案跟對的答案長得一模一樣。
    # 2026-09-18 實測撞到，`tests/test_evidence_cli.py::Args` 釘住。
    sub = argv[0] if (argv and not str(argv[0]).startswith("-")) else "list"
    rest = argv[1:] if (argv and not str(argv[0]).startswith("-")) else list(argv)
    # `--path` 寫了可是後面沒有值 -> 明著退回，不准掉回正本。
    # 少了這一段，手滑漏掉路徑的人會拿到正本的內容並以為那是他指定的
    # 檔（2026-09-18 實測，原始輸出在 AUTO_CONTINUE_LOG 那一輪）。
    if _flag_without_value(rest, "--path"):
        print("  `--path` 後面要接一個檔案路徑。沒接的話會讀正本，")
        print("  而那份報告看起來跟你指定的檔一模一樣 —— 所以這裡退回。")
        return 2
    # `--from` 與 `--id` 是 2026-09-18 補的。兩者先前都不是靜默的，
    # 可是都指錯原因：`--from` 接到下一個旗標會回「讀不到 --path=...」
    # （怪檔案不存在，不是怪值漏了），`--id` 會回「不在登記簿上」
    # （那個人會以為那筆資料不存在，而真正的事是指令打錯，
    # 而且被吞掉的那個旗標讓它讀的還是別的檔）。
    for _flag, _why in (("--from", "後面要接一份 JSON 的路徑。"),
                        ("--id", "後面要接一個 id。")):
        if _flag_without_value(rest, _flag):
            print(f"  `{_flag}` {_why}沒接的話下一個旗標會被當成值，")
            print("  於是錯誤訊息會怪到別的東西頭上 —— 所以這裡退回。")
            return 2
    # 旗標名打錯字 -> 明著退回。這一支在五支裡後果最輕，可是不是
    # 沒有後果：2026-09-18 實測 `evidence show --idd ev-xxx` exit=2、
    # 回「要一個 id：`forseti evidence show --id ev-xxxxxxxxxx`」。
    # 那句話怪的是「你沒給 id」，而真正的事是「你給了，只是名字打錯」
    # —— 照著那句話做的人會再打一次同樣的錯字。
    _unknown = _unknown_flags(rest, KNOWN_FLAGS)
    if _unknown:
        print()
        print(f"  不認得這個旗標：{'、'.join(_unknown)}")
        print(f"  有的是：{'、'.join(KNOWN_FLAGS)}")
        print("  打錯字不會報錯，那個旗標會被當成沒寫，於是錯誤訊息")
        print("  怪的是「你沒給值」而不是「這個名字不存在」。")
        print()
        return 2
    p = _Path(_arg(rest, "--path")) if _arg(rest, "--path") else None

    if sub == "levels":
        print()
        print("  §7.2 證據強度。順序是 NORMATIVE，數值是 PROVISIONAL。")
        for k, w, zh in LEVELS:
            print(f"    {k}  {w:.2f}   {zh}")
        print()
        return 0

    if sub == "template":
        print(_json.dumps(template(), ensure_ascii=False, indent=2))
        print()
        print("# 尖括號那幾格一定要自己填，原樣送回去會被退。", file=sys.stderr)
        print(f"# strength 只收：{'、'.join(STRENGTHS)}", file=sys.stderr)
        print("# observed_at 刻意沒有預填 —— 不填就是登記當下。"
              "觀察發生在更早的話自己補一個 epoch 秒。", file=sys.stderr)
        return 0

    if sub == "register":
        src = _arg(rest, "--from")
        if not src:
            print("要一份 JSON：`forseti evidence register --from <檔案>`。"
                  "空白模板：`forseti evidence template`")
            return 2
        try:
            kw = _json.loads(_Path(src).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"讀不到或解不開：{exc}")
            return 2
        if not isinstance(kw, dict):
            print(f"要一個 JSON 物件，收到 {type(kw).__name__}")
            return 2
        allowed = {k for k, _ in TEMPLATE_FIELDS} | {"observed_at"}
        extra = sorted(set(kw) - allowed)
        if extra:
            print()
            print(f"  不認得的欄位：{'、'.join(extra)}")
            print("  沒有默默丟掉，是因為丟掉的話填錯欄位名跟沒填長得一樣。")
            print()
            return 1
        why = check_fillable(kw)
        if why:
            print()
            print("  這一筆登記不了：")
            for w in why:
                print(f"    - {w}")
            print()
            return 1
        res = record(path=p, **{k: kw[k] for k in kw})
        if not res["ok"]:
            print()
            print(f"  這一筆登記不了：{res['why']}")
            print()
            return 1
        _print_row(res["evidence"])
        return 0

    if sub == "show":
        eid = _arg(rest, "--id") or (rest[0] if rest and not rest[0].startswith("-")
                                     else None)
        if not eid:
            print("要一個 id：`forseti evidence show --id ev-xxxxxxxxxx`")
            return 2
        row = get(eid, path=p)
        if row is None:
            print(f"  {eid} 不在登記簿上")
            return 1
        _print_row(row)
        return 0

    if sub not in SUBCOMMANDS:
        # 打錯子指令要看得出來。掉進 list 的話會回 0 而且印一份看起來
        # 正常的報告 —— `forseti evidence registr --from x` 會回報
        # 「0 筆」然後結束，而那個人以為自己登記過了。
        print(f"  不認得的子指令：{sub}")
        print(f"  有的是：{'、'.join(SUBCOMMANDS)}")
        return 2

    rows = load(p)
    print()
    print(f"  §7.2 證據登記簿　{len(rows)} 筆")
    if not rows:
        print()
        print("  一筆都還沒有人登。實體與儲存在了，缺的是有人去登 —— ")
        print("  `forseti evidence template` 產模板，填完")
        print("  `forseti evidence register --from <檔案>`。")
        print()
        print("  **這一支不自動登記。** 拿現成的東西配一組猜出來的欄位")
        print("  就是 §8.3 的填空，而那正是這個模組存在要擋的事。")
        print()
        return 0
    for r in rows:
        _print_row(r)
    ind = independence(rows)
    print()
    print(f"  §33.3 獨立支撐　{ind['independent_support_count']}"
          f" / 原始 {ind['raw_support_count']}")
    print(f"  {ind['why']}")
    print()
    return 0
