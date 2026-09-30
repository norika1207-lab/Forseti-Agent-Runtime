"""Source Tree 的視覺語法正本。

這裡只描述語意與既有 UI class 的對應，不在 Python 重新判定 drift。
`desktop_api.strands()` 把它送給前端，讓圖例、主線與問題軌道讀同一份
契約；新增狀態時若沒有 class，契約測試會先紅，而不是靜默畫成預設橘色。
"""

from __future__ import annotations

from copy import deepcopy


_SCHEMA = {
    "version": 1,
    "lines": {
        "aligned": {
            "class_name": "main path-aligned",
            "css_var": "--green",
            "label": "綠色實線",
            "meaning": "目前實際路徑對 active North Star 有足夠支持。",
        },
        "suspected": {
            "class_name": "main path-suspected",
            "css_var": "--amber",
            "label": "橘色分支",
            "meaning": "可能偏離或目標尚未確認；不是錯誤判決。",
        },
        "new_direction": {
            "class_name": "main path-new-direction",
            "css_var": "--violet",
            "label": "紫色實線",
            "meaning": "owner 已確認新的 North Star；這是方向換版，不是 AI 偏離。",
        },
        "direction_candidate": {
            "class_name": "main path-direction-candidate",
            "css_var": "--violet",
            "label": "紫色虛線",
            "meaning": "owner 的文字像是在改方向，但尚未確認為新的 North Star。",
        },
        "exploratory": {
            "class_name": "main path-exploratory",
            "css_var": "--amber",
            "label": "橘色虛線",
            "meaning": "owner 明確保留的探索旁支；不改主線，也不算 AI drift。",
        },
        "confirmed": {
            "class_name": "main path-confirmed",
            "css_var": "--red",
            "label": "紅色分支",
            "meaning": "已有 deterministic 或 owner-confirmed contradiction。",
        },
        "neutral": {
            "class_name": "main path-neutral",
            "css_var": "--ink-3",
            "label": "中性色分支",
            "meaning": "未知、壓縮或資料覆蓋不足；不歸責。",
        },
        "tool_fail": {
            "class_name": "main path-tool-fail",
            "css_var": "--blue",
            "label": "藍色分支",
            "meaning": "工具或 runtime 失敗；是誠實失敗，不等於 drift。",
        },
        "northstar_reference": {
            "class_name": "reference northstar-reference",
            "css_var": "--green",
            "label": "綠色虛線參照",
            "meaning": "偏離後仍保留的舊北極星路徑；不是 self-recovery latency。",
        },
    },
    "lanes": {
        "COMPACT": {"class_name": "lane lc", "meaning": "對話壓縮，記憶不完整。"},
        "BETRAYAL": {"class_name": "lane lb", "meaning": "說了沒做，還沒落地。"},
        "DRIFT": {"class_name": "lane ld", "meaning": "偏離目標。"},
        "TOOL_FAIL": {"class_name": "lane lf", "meaning": "工具連續失敗。"},
        "BLIND_WRITE": {"class_name": "lane lw", "meaning": "一直在找，還沒動手。"},
    },
    "markers": {
        "owner": {"data_value": "owner", "class_name": "ltm", "meaning": "使用者出手。"},
        "self": {"data_value": "self", "class_name": "ltm", "meaning": "未偵測到使用者出手。"},
        "open": {"data_value": "open", "class_name": "ltm", "meaning": "問題仍未收回。"},
        "checkpoint": {"data_value": "good", "class_name": "st data-cp", "meaning": "可回復的 checkpoint。"},
        "note": {"data_value": "notes", "class_name": "st data-notes", "meaning": "使用者給系統的註記。"},
    },
    "cards": {
        "proposal": {"class_name": "card2", "meaning": "可忽略的建議，不代表 owner 已採納。"},
        "betrayal": {"class_name": "card warn", "meaning": "可查證的說了沒做提示。"},
        "compaction": {"class_name": "card black-note", "meaning": "記憶覆蓋缺口與 recovery anchor。"},
        "drift": {"class_name": "driftBox", "meaning": "SUSPECTED drift 的低干擾介入。"},
    },
}


def _short(value: object, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def path_semantics(row: dict, previous: dict | None = None) -> dict:
    """Explain one rendered path segment from structured semantic evidence.

    Colour is an output of this contract, never the input.  Owner decisions
    outrank inferred drift; missing coverage stays UNKNOWN instead of being
    painted as agreement or deviation.
    """
    previous = previous or {}
    goal = row.get("goal") if isinstance(row.get("goal"), dict) else {}
    current_version = row.get("active_goal_version")
    previous_version = previous.get("active_goal_version")
    owner_text = _short(row.get("owner_text"))

    # An observed AI contradiction belongs to the AI response in this turn.
    # It must not be hidden by an owner direction/exploration label that happens
    # to share the same turn.  Owner intent and AI conduct are separate facts;
    # the path colour answers whether the AI conduct is safe to trust.
    betrayals = row.get("betrayals") or []
    overclaims = row.get("overclaims") or []
    refuted = [claim for claim in (row.get("claims") or [])
               if claim.get("state") == "REFUTED"]
    contradictions = len(betrayals) + len(overclaims) + len(refuted)
    if contradictions:
        why_parts = []
        if betrayals:
            why_parts.append(f"{len(betrayals)} 個說了沒做")
        if overclaims:
            why_parts.append(f"{len(overclaims)} 個宣稱大於證據")
        if refuted:
            why_parts.append(f"{len(refuted)} 個檔案宣稱被現實反駁")
        evidence = _short(row.get("ai_text"))
        if betrayals and betrayals[0].get("why"):
            evidence = _short(betrayals[0]["why"])
        elif refuted and refuted[0].get("why"):
            evidence = _short(refuted[0]["why"])
        return {
            "state": "confirmed",
            "actor": "AI",
            "label": "AI 嚴重偏離",
            "meaning": "AI 的回答與當時有效的 North Star 或可驗證現實衝突。",
            "why": "、".join(why_parts) +
                   f"；共 {contradictions} 個可查證衝突",
            "evidence": evidence or "deterministic contradiction",
            "epistemic": "OBSERVED",
        }

    if (current_version is not None and previous_version is not None
            and current_version != previous_version):
        return {
            "state": "new_direction",
            "actor": "owner",
            "label": "新的方向",
            "meaning": "owner 已確認 North Star 換版，後續工作改用新目標解讀。",
            "why": f"active North Star 從 v{previous_version} 變成 v{current_version}",
            "evidence": owner_text or "northstar_chain 的 owner confirm 決策",
            "epistemic": "OBSERVED",
        }

    if row.get("exploratory_branch"):
        decision = row.get("direction_decision") \
            if isinstance(row.get("direction_decision"), dict) else {}
        return {
            "state": "exploratory",
            "actor": "owner",
            "label": "探索旁支",
            "meaning": "這段是 owner 明確記錄的探索，不取代目前 North Star。",
            "why": _short(decision.get("why")) or
                   "northstar_chain 記錄 action=explore",
            "evidence": _short(decision.get("objective")) or owner_text or
                        "owner 的 explore 決策",
            "epistemic": "OBSERVED",
        }

    if row.get("owner_goal_change_candidate"):
        return {
            "state": "direction_candidate",
            "actor": "owner",
            "label": "可能是新的方向",
            "meaning": "語意分析讀到 owner 改方向句式，但尚未獲得換版確認。",
            "why": _short(row.get("owner_goal_change_state") or
                          "OWNER_GOAL_CHANGE candidate"),
            "evidence": owner_text or "owner 文字候選",
            "epistemic": "INFERRED",
        }

    if goal.get("klass") == "CONFLICTING":
        return {
            "state": "confirmed",
            "actor": "AI",
            "label": "AI 嚴重偏離",
            "meaning": "AI 的回答與當時有效的 North Star 或可驗證現實衝突。",
            "why": "下一輪 owner 明確糾正 AI",
            "evidence": _short(row.get("ai_text")) or "goal_support=CONFLICTING",
            "epistemic": "OBSERVED+INFERRED",
        }

    failed = int(row.get("failed") or 0)
    if failed:
        return {
            "state": "tool_fail",
            "actor": "工具／runtime",
            "label": "工具失敗",
            "meaning": "執行工具失敗；這是 runtime 問題，不等於方向偏離。",
            "why": f"本輪觀測到 {failed} 次失敗",
            "evidence": "工具結果",
            "epistemic": "OBSERVED",
        }

    if goal.get("klass") == "UNKNOWN" or goal.get("support") is None:
        return {
            "state": "neutral",
            "actor": "未歸因",
            "label": "資料不足",
            "meaning": "目前資料不足，不能判成對齊、偏離或新方向。",
            "why": f"語意覆蓋率 {float(goal.get('coverage') or 0):.0%}",
            "evidence": "沒有足夠可觀測動作",
            "epistemic": "UNKNOWN",
        }

    distance = float(goal.get("distance") or 0)
    if distance > 0.08:
        return {
            "state": "suspected",
            "actor": "AI",
            "label": "可能偏離",
            "meaning": "語意支持度下降，但尚未有 owner 或 deterministic 證據確認偏離。",
            "why": f"目標支持率 {float(goal.get('support') or 0):.0%}，距離 {distance:.0%}",
            "evidence": _short(row.get("ai_text")) or "最近視窗的可觀測動作",
            "epistemic": "INFERRED",
        }

    version = f" v{current_version}" if current_version is not None else ""
    return {
        "state": "aligned",
        "actor": "AI",
        "label": "沿著目前方向",
        "meaning": f"可觀測動作支持目前有效的 North Star{version}。",
        "why": f"目標支持率 {float(goal.get('support') or 0):.0%}",
        "evidence": _short(row.get("ai_text")) or "最近視窗的可觀測動作",
        "epistemic": "INFERRED",
    }


def annotate_rows(rows: list[dict]) -> list[dict]:
    """Attach hover-ready semantics without rewriting source observations."""
    previous = None
    for row in rows or []:
        row["path_semantics"] = path_semantics(row, previous)
        previous = row
    return rows


def schema() -> dict:
    """回傳可安全放進 snapshot 的 immutable-by-convention 副本。"""
    return deepcopy(_SCHEMA)


def class_names() -> set[str]:
    """回傳 schema 宣告的 class token，供契約測試使用。"""
    out: set[str] = set()
    for group in ("lines", "lanes", "markers", "cards"):
        for item in _SCHEMA[group].values():
            out.update(item.get("class_name", "").split())
    return out
