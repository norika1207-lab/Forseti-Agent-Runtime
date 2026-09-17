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
