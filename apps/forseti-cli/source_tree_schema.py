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
            "meaning": "有獨立證據確認本輪符合 active North Star。",
        },
        "suspected": {
            "class_name": "main path-suspected",
            "css_var": "--amber",
            "label": "橘色分支",
            "meaning": "使用者指出問題，或近期需要修正；不等於目標偏離。",
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
        "temporary": {
            "class_name": "main path-temporary",
            "css_var": "--amber",
            "label": "橘色暫時工作線",
            "meaning": "owner 明確說這是暫時插入的工作；原 North Star 不換版。",
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
        "DRIFT": {"class_name": "lane ld", "meaning": "須有獨立 North Star 比對證據的偏離。"},
        "CORRECTION": {"class_name": "lane lcr", "meaning": "本輪 AI 回答與下一輪使用者糾正的關係。"},
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
            "label": "宣稱與證據衝突",
            "meaning": "這一輪有可查證的宣稱衝突；不等於改變 North Star。",
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

    if row.get("temporary_work"):
        decision = row.get("direction_decision") \
            if isinstance(row.get("direction_decision"), dict) else {}
        return {
            "state": "temporary", "actor": "owner",
            "label": "暫時插入工作",
            "meaning": "使用者確認這只是暫時工作，原北極星保持不變。",
            "why": _short(decision.get("why")) or "owner 明確選擇暫時工作",
            "evidence": _short(row.get("owner_text")) or "owner 的 temporary 決策",
            "epistemic": "OBSERVED",
        }

    if row.get("owner_goal_change_candidate"):
        return {
            "state": "direction_candidate",
            "actor": "owner",
            "label": "可能是新的方向",
            "meaning": "owner 文字觸發改方向或插入工作候選，但尚未獲得換版確認。",
            "why": _short(row.get("owner_goal_change_state") or
                          "OWNER_GOAL_CHANGE candidate"),
            "evidence": owner_text or "owner 文字候選",
            "epistemic": "INFERRED",
        }

    alert = row.get("drift_alert") or {}
    if alert.get("state") == "SUSPECTED_DRIFT":
        return {
            "state": "suspected",
            "actor": "AI（待核對）",
            "label": "可能開始偏離北極星",
            "meaning": "目標距離持續增加，但還沒有滿足確認偏離的證據門檻。",
            "why": (f"第 {alert.get('from_n')} 至 {row.get('n')} 輪，"
                    f"距離 {alert.get('from_distance')} → {alert.get('distance')}"),
            "evidence": _short(row.get("ai_text")) or "目標距離趨勢",
            "epistemic": "INFERRED",
        }

    if row.get("owner_correction_text"):
        return {
            "state": "suspected",
            "actor": "AI",
            "label": "這一輪被糾正",
            "meaning": "使用者指出前一輪有問題；尚不能據此判成目標偏離。",
            "why": "下一輪使用者指出問題，需核對實際交付",
            "evidence": _short(row.get("owner_correction_text")) or
                        _short(row.get("ai_text")) or "使用者糾正紀錄",
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

    if row.get("northstar_alignment") != "ALIGNED":
        return {
            "state": "neutral",
            "actor": "未歸因",
            "label": "方向尚未核對",
            "meaning": "有活動紀錄，但尚未比對有效 North Star；不能宣稱對齊。",
            "why": "工具活動不等於目標進度",
            "evidence": _short(row.get("ai_text")) or "本輪工具紀錄",
            "epistemic": "UNKNOWN",
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
    import owner

    previous = None
    last_decision = None
    for i, row in enumerate(rows or []):
        if i + 1 < len(rows) and rows[i + 1].get("corrected_by_owner"):
            row["owner_correction_text"] = rows[i + 1].get("owner_text") or ""
        owner_text = (row.get("owner_text") or "").strip()
        owner_kind = row.get("owner_message_kind") or owner.classify(owner_text).kind
        direction_candidate = bool(row.get("owner_goal_change_candidate"))
        if (last_decision and owner_text and owner_kind != "CORRECTION"
                and (owner_kind == "MIND_CHANGE" or direction_candidate)
                and owner_text != last_decision["text"]):
            previous_line = last_decision.get("line")
            current_line = row.get("owner_line")
            row["decision_comparison"] = {
                "state": "POSSIBLE_DIFFERENCE",
                "epistemic": "INFERRED",
                "baseline_n": last_decision["n"],
                "current_n": row.get("n"),
                "baseline_source_ref": (f"line:{previous_line}"
                                        if previous_line else None),
                "evidence_source_ref": (f"line:{current_line}"
                                        if current_line else None),
                "baseline": (f"第 {last_decision['n']} 輪"
                             + (f"（原始第 {previous_line} 行）" if previous_line else "")
                             + f"：{_short(last_decision['text'])}"),
                "evidence": (f"第 {row.get('n')} 輪"
                             + (f"（原始第 {current_line} 行）" if current_line else "")
                             + f"：{_short(owner_text)}"),
                "why": "與先前的使用者決策不同，供你判斷是否換方向；尚未改動北極星。",
            }
        if owner_text and owner_kind in {"NEW_REQUEST", "MIND_CHANGE"}:
            last_decision = {"n": row.get("n"), "line": row.get("owner_line"),
                             "text": owner_text}
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
