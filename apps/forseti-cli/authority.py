#!/usr/bin/env python3
"""Authority。誰有權把提議變成事實。v5.0 §9、§1.1、§3.3

四個連續性裡的第三個，先前 Python 端一行都沒有。

    Authority — 誰可以把假設升格為事實、批准不可逆動作、改目標、
    寫正典狀態、跨越 commit 邊界。
    失守的後果：兩個元件變成互相競爭的權威；
    或 AI 在沒有擁有者的情況下做出對外承諾。

## 這一層不是權限檢查器

它不擋人。它回答一個問題:**這個動作現在該由誰決定。**

`can_execute` 是 False 不代表「你不可以做」，而是「你可以做到準備為止，
最後那一下要人按」。v5.0 §9.1 明寫模型可以提議變更而不持有提交它的權限,
而 §18 的預設姿態是 OBSERVE 99% / INTERRUPT 1% ——
一個動不動就擋人的權限層,自己就是那個 1% 的濫用。

## 信任階層照抄 §3.3，順序不可以改

原文的順序本身就是規格。數字是暫定的（跟 GAC 的權重一樣），
但誰比誰可信是 NORMATIVE。

## 為什麼要偵測衝突

§9.1 最後一條:同一個 callback、state key、endpoint 或正典檔案上
有兩個競爭的權威，會被偵測為衝突。這種東西平常不會報錯 ——
兩邊各自都「成功」了，然後結果不一致，而且沒有人知道是什麼時候開始的。
Secretary_AGI 的雙重 state 格式就是這樣來的（v5.0 §28 對照表）。
"""

from __future__ import annotations

import time

#: §3.3 的信任階層，由高到低。**順序是 NORMATIVE，數字是 PROVISIONAL。**
TRUST: tuple[tuple[str, float, str], ...] = (
    ("OWNER", 1.00, "擁有者的明確決定"),
    ("DETERMINISTIC_VERIFIER", 0.90, "決定性驗證器、簽署政策、已驗執行證據"),
    ("CANONICAL_STATE", 0.80, "正典專案狀態與決策帳本"),
    ("TOOL_OUTPUT", 0.60, "帶來源的工具輸出"),
    ("AGENT_INFERENCE", 0.40, "當前 agent 的推論"),
    ("HANDOFF_SUMMARY", 0.30, "繼承來的交接摘要"),
    ("STALE_CACHE", 0.15, "過期記憶與快取"),
    ("UNSUPPORTED", 0.00, "沒有支撐的假設"),
)
_RANK = {k: i for i, (k, _, _) in enumerate(TRUST)}
_WEIGHT = {k: w for k, w, _ in TRUST}

#: §9.2 的決定。PREPARE 是這一層的重點 ——
#: 它讓「做到最後一步為止」變成一個合法狀態，而不是全有全無。
DECISIONS = ("ALLOW", "PREPARE", "ASK", "BLOCK")

#: 跨越 commit 邊界的動作。**這些做完就收不回來**，
#: 所以不論 principal 是誰，最後那一下都要 owner。
#: v5.0 §9.1：外部效果與不可逆動作需要明確的 commit-boundary policy。
COMMIT_BOUNDARY = {
    "send": "對外發送（信、訊息、貼文）",
    "deploy": "部署到正式環境",
    "spend": "花錢或改動用量",
    "delete": "永久刪除",
    "publish": "公開發佈",
    "push": "推到遠端版本庫",
    "migrate": "執行資料庫遷移",
}

#: 會改變正典狀態，但可以回復的。這些可以 ALLOW，但要記帳。
CANONICAL_WRITE = {
    "finish": "把任務標成完成",
    "transition": "轉換任務狀態",
    "checkpoint": "標記一個可以回去的點",
    "adopt_goal": "換一版北極星",
    "promote": "把宣稱升格為正典事實",
}


def rank(principal: str) -> int:
    """在信任階層裡排第幾。數字越小越可信。不認得的排最後。"""
    return _RANK.get(principal, len(TRUST))


def weight(principal: str) -> float:
    return _WEIGHT.get(principal, 0.0)


def decide(*, action: str, principal: str, resource: str = "",
           reversible: bool | None = None,
           policy_version: str = "spec-v2.0/§9") -> dict:
    """§9.2 的 PolicyDecision。

    回的欄位照規格原文，一個都不少 —— 少了哪一個，
    呼叫端就會自己腦補那一欄的預設值。
    """
    base = {
        "intent": action,
        "resource": resource,
        "principal": principal,
        "trust_rank": rank(principal),
        "source_policy_version": policy_version,
        "at": time.time(),
    }

    if action in COMMIT_BOUNDARY:
        return dict(base,
                    risk="IRREVERSIBLE",
                    decision="PREPARE",
                    can_execute=False,
                    allowed_preparation=f"可以準備到送出前一步：{COMMIT_BOUNDARY[action]}",
                    required_confirmation="OWNER",
                    blocked_final_action=action,
                    reason="§9.1 外部效果與不可逆動作要跨 commit 邊界，"
                           "準備跟提交是兩個權限等級")

    if action in CANONICAL_WRITE:
        if principal == "OWNER":
            return dict(base,
                        risk="CANONICAL",
                        decision="ALLOW",
                        can_execute=True,
                        allowed_preparation="",
                        required_confirmation="",
                        blocked_final_action="",
                        reason=f"擁有者對正典狀態有權：{CANONICAL_WRITE[action]}")
        return dict(base,
                    risk="CANONICAL",
                    decision="ASK",
                    can_execute=False,
                    allowed_preparation="可以算出結果並呈現，不要寫進去",
                    required_confirmation="OWNER",
                    blocked_final_action=action,
                    reason="§7.1 一個宣稱不會因為被重複就變成正典。"
                           "寫正典狀態要擁有者，模型可以提議")

    if reversible is False:
        return dict(base,
                    risk="IRREVERSIBLE",
                    decision="ASK",
                    can_execute=False,
                    allowed_preparation="可以準備，不要執行最後一步",
                    required_confirmation="OWNER",
                    blocked_final_action=action,
                    reason="呼叫端標明這個動作不可逆")

    return dict(base,
                risk="ORDINARY",
                decision="ALLOW",
                can_execute=True,
                allowed_preparation="",
                required_confirmation="",
                blocked_final_action="",
                reason="一般動作。§18 的預設姿態是 OBSERVE 99%，"
                       "不在紅線上的東西不攔")


def collisions(claims: list) -> list[dict]:
    """同一個資源上有兩個競爭的權威。§9.1

    `claims` 是 [{resource, principal, at, detail}]。

    **同一個 principal 重複宣告不算衝突**，那是正常的。
    衝突是「不同來源都說自己說了算」，而且平常不會報錯 ——
    兩邊各自都成功，然後結果不一致。
    """
    by_res: dict = {}
    for c in claims or []:
        res = (c.get("resource") or "").strip()
        if not res:
            continue
        by_res.setdefault(res, []).append(c)

    out = []
    for res, cs in by_res.items():
        who = {c.get("principal", "") for c in cs}
        if len(who) < 2:
            continue
        ranked = sorted(cs, key=lambda c: rank(c.get("principal", "")))
        top = ranked[0]
        out.append({
            "resource": res,
            "principals": sorted(who),
            "winner": top.get("principal", ""),
            "winner_reason": f"信任階層排第 {rank(top.get('principal', '')) + 1}",
            "losers": sorted(w for w in who if w != top.get("principal")),
            "count": len(cs),
            # 這一句是給人看的,不是給程式判的。
            "why_it_matters": "兩個來源都說自己說了算。平常不會報錯，"
                              "兩邊各自都成功，然後結果不一致，"
                              "而且沒有人知道是從什麼時候開始的",
        })
    out.sort(key=lambda x: -x["count"])
    return out


def may_promote(principal: str, *, evidence_strength: str = "") -> dict:
    """能不能把一個宣稱升格成正典事實。§7.1

    原文:一個宣稱不會因為多個 agent 重複它就變成正典，
    重複增加的是社會共識，不是證據強度。
    """
    ok = principal in ("OWNER", "DETERMINISTIC_VERIFIER")
    return {
        "may_promote": ok,
        "principal": principal,
        "trust_rank": rank(principal),
        "evidence_strength": evidence_strength,
        "reason": ("擁有者或決定性驗證器才有資格升格" if not ok else
                   "在信任階層的前兩級"),
        "note": "重複不會增加證據強度。多個 agent 都這樣說，"
                "增加的是社會共識不是證據",
    }


def summary(claims: list | None = None) -> dict:
    cols = collisions(claims or [])
    return {
        "trust_levels": [{"principal": k, "weight": w, "means": d}
                         for k, w, d in TRUST],
        "commit_boundary": sorted(COMMIT_BOUNDARY),
        "canonical_write": sorted(CANONICAL_WRITE),
        "collisions": cols,
        "has_collision": bool(cols),
        "note": "這一層不擋人，它回答「這個動作現在該由誰決定」。"
                "can_execute 是 False 通常代表「做到準備為止，最後那一下要人按」",
    }
