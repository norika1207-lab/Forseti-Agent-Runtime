#!/usr/bin/env python3
"""Reliability Probe Packs。固定情境，重跑比對，抓結構性退化。v5.0 §15

規格原文（v5.0 §15，`docs/sources/` 那份第 410 行起）:

    Borrowing the controlled-measurement pattern from AEO/GEO, Forseti
    uses fixed probe packs to detect structural regressions across
    models, versions and contexts.

§15.1 給了 schema 的十一個欄位，§15.2 列了十個必測類別。
`ProbeScenario` 的欄位名照原文一字不改，`REQUIRED_CLASSES` 的十條
照原文順序，沒有增減。這兩件事有回歸測試釘住。

## 這一支跟 `desktop_api.selftest()` 不是同一件事

`selftest()` 問的是「這個功能現在是不是活的」，答案是 alive / dead，
每次跑都從零判一次，沒有記憶。

Probe Pack 問的是「跟上一次量的比，有沒有退化」。它要有基準線，
要能重跑，要看得出「這一次跟上一次不一樣」。一個功能可以是活的，
同時判準已經悄悄變寬，那種退化 `selftest()` 看不見。

## 最重要的一條誠實條款: 這一版只跨得了三軸裡的一軸

§15 原文要跨的是 models、versions、contexts 三軸。

這一版的 `model_matrix` 每個情境都只有一格 `code@REPO`，
因為這裡的 verifier 跑的是「這個 repo 的偵測器程式碼」，
不呼叫任何模型。所以它抓得到的是「程式碼改動造成的判準退化」,
也就是 versions 那一軸。

換模型或改路由之後會不會退化，這一版答不出來，
而且不會裝作答得出來: `AXES_COVERED` 與 `AXES_MISSING` 是兩個
常數，`run()` 的輸出每一次都帶著它們。要補那兩軸，缺的是一個
會呼叫模型的執行器，不是這裡多寫幾個情境。

## 沒有 verifier 的類別回 NO_VERIFIER，不回 PASS

十類裡有一類（`fastpath_routing`）在這個 repo 完全沒有資料來源:
`grep -rliE "fastpath|routing" apps/forseti-cli/ src/ | grep -v probe.py`
是空的（排除這個檔自己，因為它寫著這兩個字）。

一個沒有東西可量的情境，跟一個量過而且通過的情境，
在一張綠色的表上長得一模一樣。所以它的狀態是 `NO_VERIFIER`，
而且 `run()` 的摘要把它跟 PASS 分開數。

## 基準線不自己更新

`.forseti/probe_baseline.json` 只有明確呼叫 `record_baseline()` 才寫。

自動更新的基準線等於沒有基準線: 每一次退化都會在下一次變成新常態，
而曲線永遠是平的。這跟 `checkpoint.py` 的 last_good 不自己挑同一條理由。
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "apps" / "forseti-cli"
if str(CLI) not in sys.path:
    sys.path.insert(0, str(CLI))

BASELINE_PATH = REPO / ".forseti" / "probe_baseline.json"

# §15 原文要跨的三軸。這一版只跨得了中間那一軸。
AXES_COVERED = ("versions",)
AXES_MISSING = ("models", "contexts")
AXES_WHY = ("這一版的 verifier 跑的是這個 repo 的偵測器程式碼，不呼叫模型。"
            "所以它量得到程式碼改動造成的判準退化，"
            "量不到換模型或改路由造成的退化")

# §15.2 的十個必測類別，順序照原文。
REQUIRED_CLASSES: tuple[tuple[str, str], ...] = (
    ("goal_persistence", "Goal persistence across session replacement."),
    ("claim_evidence_honesty",
     "Claim-evidence honesty after file/process/API actions."),
    ("handoff_sufficiency", "Handoff sufficiency under context truncation."),
    ("fastpath_routing", "Wrong fastpath / routing collision."),
    ("stale_cache", "Stale cache and evidence freshness."),
    ("tool_loop_blank_output", "Tool loop and blank-output recovery."),
    ("authority_commit",
     "Authority collision and commit-boundary enforcement."),
    ("reconstruction",
     "Reconstruction from incomplete session artifacts."),
    ("multi_agent_consensus",
     "Multi-agent disagreement and unsupported consensus."),
    ("topology_sot",
     "Runtime topology drift and source-of-truth mismatch."),
)

STATES = ("PASS", "REGRESSED", "NEW", "NO_VERIFIER")


class ProbeError(Exception):
    pass


@dataclass(frozen=True)
class ProbeScenario:
    """§15.1 的 schema。十一個欄位，名字照原文。

    `verifier` 存的是名字不是函式，因為這張表要能寫進 json 再讀回來。
    函式在 `VERIFIERS` 裡查。
    """

    id: str
    domain: str
    risk_class: str
    setup: str
    prompt: str
    expected_contract: str
    verifier: str | None
    prohibited_shortcuts: tuple[str, ...]
    model_matrix: tuple[str, ...]
    baseline: str
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# verifier。每一個都用合成的 setup 跑真實模組，不碰真實狀態。
#
# 合成而不是讀現況，理由跟 selftest 的 _spec() 修正同一條:
# 一個依賴真實狀態的檢查，會在狀態變好之後失效，
# 那跟永遠回 OK 是同一種壞掉。
#
# 回傳固定三個鍵:
#   ok        契約有沒有被滿足
#   observed  可以跨次比對的觀測值，不含時間戳與路徑
#   why       講給人看的一句話
# ---------------------------------------------------------------------------

def _v_goal_persistence() -> dict:
    """換版之後，舊的北極星還查得回來，而且被標成不是現行的。"""
    import northstar as NS

    ch = NS.Chain()
    v1 = ch.adopt("把 A 做完", authority="owner", why="起點")
    v2 = ch.adopt("改成把 B 做完", authority="owner", why="方向換了")
    back = ch.at_version(v1.version)
    observed = {
        "old_recoverable": back is not None,
        "old_objective_intact": bool(back and back.objective == "把 A 做完"),
        "old_is_stale": ch.is_stale(v1.version),
        "new_is_current": not ch.is_stale(v2.version),
        "supersedes": v2.supersedes,
        "versions_kept": len(ch.versions),
    }
    ok = (observed["old_recoverable"] and observed["old_objective_intact"]
          and observed["old_is_stale"] and observed["new_is_current"]
          and observed["supersedes"] == v1.version
          and observed["versions_kept"] == 2)
    return {"ok": ok, "observed": observed,
            "why": "換版後舊目標查得回來且被標為過期" if ok
                   else "換版之後舊目標的狀態不對"}


def _v_claim_evidence_honesty() -> dict:
    """弱證據撐不起強宣稱，而且沒有證據不能升格成正典。"""
    import evidence as EV
    import claims as CL

    weak = EV.can_support(claim_level="E4", evidence_level="E0")
    strong = EV.can_support(claim_level="E1", evidence_level="E3")

    c = CL.Claim(text="測試全過", kind="passfail",
                 subject="probe", strength="E1")
    promoted_without_evidence = True
    try:
        c.promote(authority="owner", policy_ref="§7.1")
    except CL.ClaimError:
        promoted_without_evidence = False

    observed = {
        "weak_rejected": weak["ok"] is False,
        "weak_gap": weak["gap"],
        "strong_accepted": strong["ok"] is True,
        "promote_without_e4_blocked": promoted_without_evidence is False,
    }
    ok = all([observed["weak_rejected"], observed["strong_accepted"],
              observed["promote_without_e4_blocked"],
              observed["weak_gap"] == 4])
    return {"ok": ok, "observed": observed,
            "why": "弱證據被擋，非 E4 不能升正典" if ok
                   else "證據等級的守備鬆了"}


def _v_handoff_sufficiency() -> dict:
    """截斷之後任務狀態不得改變，而且要考得出 goal recall 的題目。"""
    import rehydration as RH

    intact = RH.CompressionBoundary(
        at=0.0, pre_tokens=100_000, post_tokens=20_000,
        dropped_tokens=80_000,
        task_state_before="IN_PROGRESS", task_state_after="IN_PROGRESS")
    broken = RH.CompressionBoundary(
        at=0.0, pre_tokens=100_000, post_tokens=20_000,
        dropped_tokens=80_000,
        task_state_before="IN_PROGRESS", task_state_after="DONE")

    # 讀了 50 行就說讀完，量出來只能是 SAMPLED。
    # level 是量出來的不是報上來的，這是 §17.3 那道門能不能算數的前提。
    cov = RH.coverage_report(read_ranges=[(1, 50)], total_lines=500)
    observed = {
        "intact_passes": intact.task_state_intact is True,
        "mutation_caught": broken.task_state_intact is False,
        "challenge_questions": len(intact.challenge()),
        "partial_read_level": cov["level"],
        "upper_bound_flag_cannot_be_turned_off": cov["is_upper_bound"] is True,
    }
    ok = (observed["intact_passes"] and observed["mutation_caught"]
          and observed["challenge_questions"] > 0
          and observed["partial_read_level"] == "SAMPLED"
          and observed["upper_bound_flag_cannot_be_turned_off"])
    return {"ok": ok, "observed": observed,
            "why": "截斷改了任務狀態會被抓到，讀取深度也是量的不是報的" if ok
                   else "截斷邊界的守備有缺口"}


def _v_stale_cache() -> dict:
    """過期的北極星不准拿來當偏離判定的依據，而 freshness 說得出誰決定的。"""
    import northstar as NS
    import goalgate as GG

    ch = NS.Chain()
    v1 = ch.adopt("舊方向", authority="owner", why="起點")
    ch.adopt("新方向", authority="owner", why="換了")

    fr = GG.freshness(40)
    observed = {
        "stale_version_flagged": ch.is_stale(v1.version) is True,
        "freshness_value": fr.get("value"),
        "freshness_has_decider": bool(fr.get("decided_by")),
        "freshness_mode": fr.get("mode"),
    }
    ok = (observed["stale_version_flagged"]
          and observed["freshness_has_decider"]
          and observed["freshness_value"] is not None)
    return {"ok": ok, "observed": observed,
            "why": "過期版本標得出來，freshness 說得出是誰決定的" if ok
                   else "過期判定或 freshness 的來源說不清楚"}


def _v_tool_loop_blank_output() -> dict:
    """空輸出判成卡住不是收工，而長時間本身不足以判定停滯。"""
    import yieldcheck as YC
    import watchdog as WD

    blank = YC.judge(done_when=["交付 X"], unmet=["交付 X"],
                     produced_this_turn=0)
    premature = YC.judge(done_when=["交付 X", "交付 Y"], unmet=["交付 Y"],
                         produced_this_turn=3)
    unknown = YC.judge(done_when=None)

    stalled = WD.assess(age_sec=3600.0, progress_changed=False,
                        events_since=0)
    waiting = WD.assess(age_sec=3600.0, progress_changed=False,
                        events_since=0, expected_to_progress=False)

    observed = {
        "blank_is_blocked": blank["verdict"] == "BLOCKED",
        "premature_caught": premature["verdict"] == "PREMATURE",
        "no_dod_is_unknown": unknown["verdict"] == "CANNOT_DETERMINE",
        "stall_risk_high": round(float(stalled.risk), 3),
        "not_expected_lowers_risk": float(waiting.risk) < float(stalled.risk),
    }
    ok = (observed["blank_is_blocked"] and observed["premature_caught"]
          and observed["no_dod_is_unknown"]
          and observed["not_expected_lowers_risk"])
    return {"ok": ok, "observed": observed,
            "why": "空輸出判成卡住，不該有產出時久了也不算停滯" if ok
                   else "停止判定或停滯判定的守備鬆了"}


def _v_authority_commit() -> dict:
    """同一個資源兩個權威要抓得到，而 COMMITTED 只有 OWNER 按得下去。"""
    import tempfile
    import authority as AU
    import commit as CM

    col = AU.collisions([
        {"resource": "config.json", "principal": "agent", "at": 1.0},
        {"resource": "config.json", "principal": "owner", "at": 2.0},
        {"resource": "other.json", "principal": "agent", "at": 3.0},
        {"resource": "other.json", "principal": "agent", "at": 4.0},
    ])

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "commit.jsonl"
        tx = CM.open_tx(kind="publish", subject="probe", path=p)["tx"]
        # 狀態機沒有捷徑，DRAFT 到 COMMITTED 要一格一格走。
        CM.advance(tx, "PREPARING", cause="開始準備", path=p)
        CM.advance(tx, "PREPARED", cause="準備好了",
                   external_ref="ext-1", path=p)
        CM.advance(tx, "AWAITING_APPROVAL", cause="等 owner 按", path=p)
        agent_blocked = False
        try:
            CM.advance(tx, "COMMITTED", actor="agent", cause="提交", path=p)
        except CM.CommitError:
            agent_blocked = True
        owner_ok = CM.advance(tx, "COMMITTED",
                              actor=CM.COMMIT_PRINCIPAL,
                              cause="owner 按的", path=p)["state"]

    observed = {
        "collisions_found": len(col),
        "collision_resource": col[0]["resource"] if col else None,
        "same_principal_not_a_collision": all(
            c["resource"] != "other.json" for c in col),
        "agent_cannot_commit": agent_blocked,
        "owner_can_commit": owner_ok == "COMMITTED",
    }
    ok = (observed["collisions_found"] == 1
          and observed["same_principal_not_a_collision"]
          and observed["agent_cannot_commit"]
          and observed["owner_can_commit"])
    return {"ok": ok, "observed": observed,
            "why": "兩個權威抓得到，commit 邊界擋得住 agent" if ok
                   else "權威衝突或 commit 邊界的守備有缺口"}


def _v_reconstruction() -> dict:
    """殘缺的 session 產物重建時，缺的部分要看得出來是缺的。"""
    import rehydration as RH

    # 殘缺的產物重建出來的涵蓋度，跟完整的要分得開；
    # 而「自己說自己懂」最高只能到 FULL_READ，第 6 級要有人考過。
    partial = RH.coverage_of(read_ranges=[(1, 100), (400, 500)],
                             total_lines=1000)
    full = RH.coverage_of(read_ranges=[(1, 1000)], total_lines=1000)
    challenged = RH.coverage_of(read_ranges=[(1, 1000)], total_lines=1000,
                                challenged_ok=True)
    empty = RH.coverage_of(read_ranges=[], total_lines=1000)
    observed = {
        "partial_level": partial,
        "full_level": full,
        "challenged_level": challenged,
        "empty_level": empty,
        "self_claim_cannot_reach_level6": full != "VERIFIED_UNDERSTANDING",
    }
    ok = (partial == "SAMPLED" and full == "FULL_READ"
          and challenged == "VERIFIED_UNDERSTANDING" and empty == "NONE"
          and observed["self_claim_cannot_reach_level6"])
    return {"ok": ok, "observed": observed,
            "why": "殘缺與完整分得開，第 6 級一定要有人考過" if ok
                   else "重建涵蓋度的判定不可信"}


def _v_multi_agent_consensus() -> dict:
    """重複不增加證據強度。這一條是靠沒有那個入口，不是靠紀律。"""
    import claims as CL

    c = CL.Claim(text="這個數字是 42", kind="number",
                 subject="probe", strength="E1")
    before = c.strength
    for who in ("agent-a", "agent-b", "agent-c", "agent-a"):
        c.repeat(by=who)

    observed = {
        "repeats": c.repeats,
        "distinct_speakers": len(c.said_by),
        "strength_unchanged": c.strength == before,
        "strength": c.strength,
        "repeat_touches_strength": "strength" in (
            CL.Claim.repeat.__code__.co_names),
    }
    ok = (observed["repeats"] == 4 and observed["distinct_speakers"] == 3
          and observed["strength_unchanged"]
          and observed["repeat_touches_strength"] is False)
    return {"ok": ok, "observed": observed,
            "why": "講四次強度沒動，而且程式碼裡沒有那條路徑" if ok
                   else "重複跟強度之間出現了路徑"}


def _v_topology_sot() -> dict:
    """登記的憑據還在不在。原文找不到的那條登記不能再信。"""
    import sot as ST

    b = ST.verify_bindings()
    observed = {
        "rows": len(b.get("rows") or []),
        "stale": b.get("stale"),
        "drifted_is_counted": "drifted" in b,
        "ok_means_no_stale": b.get("ok") == (b.get("stale") == 0),
    }
    ok = (observed["rows"] > 0 and observed["stale"] == 0
          and observed["drifted_is_counted"]
          and observed["ok_means_no_stale"])
    return {"ok": ok, "observed": observed,
            "why": f"{observed['rows']} 條登記的憑據都還在" if ok
                   else f"有 {observed['stale']} 條登記的原文找不到了"}


VERIFIERS = {
    "goal_persistence": _v_goal_persistence,
    "claim_evidence_honesty": _v_claim_evidence_honesty,
    "handoff_sufficiency": _v_handoff_sufficiency,
    "fastpath_routing": None,
    "stale_cache": _v_stale_cache,
    "tool_loop_blank_output": _v_tool_loop_blank_output,
    "authority_commit": _v_authority_commit,
    "reconstruction": _v_reconstruction,
    "multi_agent_consensus": _v_multi_agent_consensus,
    "topology_sot": _v_topology_sot,
}

# fastpath_routing 為什麼沒有 verifier，寫在這裡而不是註解裡，
# 因為它要出現在畫面上。一句「沒有資料來源」比一格綠燈誠實。
NO_VERIFIER_WHY = {
    "fastpath_routing":
        "這個 repo 沒有路由層。grep -rliE 那兩個關鍵字（排除 probe.py 自己）"
        "命中 0 個檔，所以沒有東西可以量。要補這一類，缺的是一個會做"
        "路由決策的元件，不是這裡多寫一個情境",
}


# ---------------------------------------------------------------------------
# PACK。§15.2 十類各一個情境。
#
# `prompt` 這個欄位在 §15.1 的 schema 裡，而這一版的 verifier 不呼叫
# 模型，所以它填的是「這個情境問的是什麼」，不是要餵給模型的字串。
# 那是缺 models 那一軸的直接後果，不是欄位填錯。
# ---------------------------------------------------------------------------

def _sc(cid, domain, risk, setup, prompt, contract, shortcuts, tags):
    return ProbeScenario(
        id=cid, domain=domain, risk_class=risk, setup=setup, prompt=prompt,
        expected_contract=contract, verifier=cid,
        prohibited_shortcuts=tuple(shortcuts),
        model_matrix=("code@REPO",),
        baseline=f"file:{BASELINE_PATH.name}#{cid}",
        tags=tuple(tags))


PACK: tuple[ProbeScenario, ...] = (
    _sc("goal_persistence", "goal", "HIGH",
        "一條北極星鏈，adopt 兩次，第二次取代第一次",
        "換過一版之後，上一版的目標還查得回來嗎，而且知道它已經不是現行的嗎",
        "舊版 objective 原文不變、is_stale 為真、supersedes 指回舊版、"
        "兩版都留著",
        ["把舊版刪掉再說『沒有過期的版本』",
         "用 current 回答『當時對著哪一個』"],
        ["§8.1", "northstar"]),

    _sc("claim_evidence_honesty", "evidence", "HIGH",
        "一個 E0 證據配 E4 宣稱，一個 E1 強度的宣稱要升正典",
        "弱證據撐得起強宣稱嗎，沒有 E4 能不能升成正典",
        "can_support 對 E4/E0 回 ok False 且 gap 4，promote 在非 E4 時丟錯",
        ["把 gap 改成只看正負不看大小",
         "讓 promote 在強度不足時只警告不擋"],
        ["§7.1", "§7.2", "claims", "evidence"]),

    _sc("handoff_sufficiency", "handoff", "HIGH",
        "兩個壓縮邊界，一個任務狀態不變一個被改掉；再量一次 50/500 行的涵蓋度",
        "截斷之後任務狀態被改掉看得出來嗎，讀取深度是量的還是報的",
        "改掉狀態的那個 task_state_intact 為 False、challenge 出得了題、"
        "50/500 行量出來是 SAMPLED、is_upper_bound 關不掉",
        ["拿宣稱的 level 當答案",
         "把 is_upper_bound 做成可以關的參數"],
        ["§3", "§17.3", "rehydration"]),

    _sc("fastpath_routing", "routing", "HIGH",
        "（沒有 setup，這個 repo 沒有路由層）",
        "走錯快路或路由撞號的時候，看得出來嗎",
        "（無法表述。沒有路由決策元件就沒有可以違反的契約）",
        ["編一個路由模型出來測它自己"],
        ["§15.2", "NO_SOURCE"]),

    _sc("stale_cache", "freshness", "MEDIUM",
        "一條換過版的北極星，加上一次 freshness 查詢",
        "過期的東西拿來當判斷依據的時候，攔得住嗎，而那個新鮮度是誰決定的",
        "舊版 is_stale 為真、freshness 帶得出 decided_by、值不是 None",
        ["把缺的因子當成 1.0 帶過去",
         "回一個沒有出處的新鮮度分數"],
        ["§5.1", "goalgate", "northstar"]),

    _sc("tool_loop_blank_output", "liveness", "HIGH",
        "三次交還發言權的判定，加上兩次停滯評估（預期有產物與不預期）",
        "這一輪什麼都沒產出，是收工還是卡住，而久沒動就一定是停滯嗎",
        "空輸出判 BLOCKED、還有未完成判 PREMATURE、沒有完成定義判 "
        "CANNOT_DETERMINE、不預期有產物時 risk 低於預期有產物時",
        ["把 BLOCKED 併進 PREMATURE（兩者的處方相反）",
         "只用時間長短判停滯"],
        ["F06", "F05", "yieldcheck", "watchdog"]),

    _sc("authority_commit", "authority", "CRITICAL",
        "四筆權威宣告（兩筆同資源不同人、兩筆同資源同人），"
        "加上一筆走到 COMMITTED 的交易",
        "同一個資源上兩個權威抓得到嗎，agent 按得下不可逆提交嗎",
        "只回一筆衝突（同人重複不算）、agent 提交丟 CommitError、"
        "OWNER 提交成功",
        ["把同一個 principal 重複宣告也算成衝突（會淹掉真的衝突）",
         "把準備與提交合成單一權限位元"],
        ["§9.1", "§9.3", "§26", "authority", "commit"]),

    _sc("reconstruction", "reconstruction", "MEDIUM",
        "四種讀取範圍：兩成、全部、全部且被考過、完全沒讀",
        "從殘缺的產物重建之後，它自己知道缺了多少嗎",
        "兩成是 SAMPLED、全部是 FULL_READ、被考過才是 "
        "VERIFIED_UNDERSTANDING、沒讀是 NONE",
        ["自己說自己懂就給第 6 級",
         "沒讀的時候回一個中間值而不是 NONE"],
        ["Vol2 §4", "rehydration"]),

    _sc("multi_agent_consensus", "consensus", "HIGH",
        "同一個宣稱被三個 agent 講四次",
        "講的人多了、講的次數多了，這件事有變得比較可信嗎",
        "repeats 到 4、說話者 3 人、strength 完全沒動，"
        "而且 repeat 的位元組碼裡不出現 strength",
        ["把 repeats 餵進信心分數",
         "用『多個 agent 都這樣說』當升格理由"],
        ["§7.1", "claims"]),

    _sc("topology_sot", "sot", "MEDIUM",
        "真實 repo 的 source-of-truth 登記簿",
        "登記的那些憑據，原文現在還在不在",
        "每一條登記都查得到原文（stale 為 0），行號漂移分開計數",
        ["行號對不上就當成原文不見了（程式碼會動，那是正常的）",
         "原文不見了還繼續拿那條登記當根據"],
        ["§12.2", "sot"]),
)


def scenarios() -> tuple[ProbeScenario, ...]:
    return PACK


def _check_pack_covers_spec() -> dict:
    """PACK 有沒有蓋滿 §15.2 那十類。少一類就是這張表在說謊。"""
    want = [k for k, _ in REQUIRED_CLASSES]
    got = [s.id for s in PACK]
    return {"ok": want == got, "required": want, "present": got,
            "missing": [k for k in want if k not in got],
            "extra": [k for k in got if k not in want]}


# ---------------------------------------------------------------------------
# 基準線
# ---------------------------------------------------------------------------

def load_baseline(path: Path | None = None) -> dict:
    p = Path(path or BASELINE_PATH)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def record_baseline(results: list[dict] | None = None,
                    path: Path | None = None, *, by: str = "") -> dict:
    """把這一次的觀測值存成基準線。

    只有明確呼叫才寫。`run()` 不會順手更新它。

    `by` 是誰按的。一條沒有人負責的基準線，事後沒有人能回答
    「當時為什麼覺得這個數字是對的」。
    """
    if not by.strip():
        raise ProbeError("要記基準線就要留下是誰按的。"
                         "沒有人負責的基準線，事後沒有人答得出當時為什麼")
    rs = results if results is not None else run(compare=False)["results"]
    payload = {
        "at": time.time(),
        "by": by,
        "axes_covered": list(AXES_COVERED),
        "axes_missing": list(AXES_MISSING),
        "scenarios": {
            r["id"]: {"ok": r["ok"], "observed": r["observed"],
                      "state": r["state"]}
            for r in rs if r["state"] != "NO_VERIFIER"
        },
    }
    p = Path(path or BASELINE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
    return {"ok": True, "path": str(p), "count": len(payload["scenarios"])}


def _diff(base: dict, now: dict) -> list[str]:
    """哪幾個觀測欄位變了。回欄位名，不回值。"""
    keys = sorted(set(base) | set(now))
    return [k for k in keys if base.get(k) != now.get(k)]


# ---------------------------------------------------------------------------
# 執行
# ---------------------------------------------------------------------------

def run(*, only: str | None = None, compare: bool = True,
        baseline_path: Path | None = None) -> dict:
    """跑整包，跟基準線比對。

    四種狀態:
        PASS         契約滿足，而且觀測值跟基準線一致
        REGRESSED    契約沒滿足，或觀測值跟基準線不一樣
        NEW          沒有基準線可比
        NO_VERIFIER  這一類在這個 repo 沒有東西可以量

    NO_VERIFIER 跟 PASS 分開數。摘要裡兩個數字永遠是分開的，
    因為把它們加在一起就會得到一個比實際好看的通過率。
    """
    base = load_baseline(baseline_path) if compare else {}
    base_sc = (base.get("scenarios") or {}) if isinstance(base, dict) else {}

    results = []
    for sc in PACK:
        if only and sc.id != only:
            continue
        fn = VERIFIERS.get(sc.id)
        if fn is None:
            results.append({
                "id": sc.id, "domain": sc.domain,
                "risk_class": sc.risk_class,
                "state": "NO_VERIFIER", "ok": None, "observed": None,
                "why": NO_VERIFIER_WHY.get(sc.id, "沒有資料來源"),
                "changed": [],
            })
            continue

        started = time.time()
        try:
            out = fn()
            ok = bool(out.get("ok"))
            observed = out.get("observed")
            why = out.get("why", "")
            err = None
        except Exception as e:                       # noqa: BLE001
            ok, observed, err = False, None, f"{type(e).__name__}: {e}"
            why = "verifier 自己炸了。一個跑不起來的檢查等於沒有檢查"

        prev = base_sc.get(sc.id) if compare else None
        changed: list[str] = []
        if prev is not None and isinstance(observed, dict) \
                and isinstance(prev.get("observed"), dict):
            changed = _diff(prev["observed"], observed)

        if not ok:
            state = "REGRESSED"
        elif prev is None:
            state = "NEW" if compare else "PASS"
        elif changed:
            state = "REGRESSED"
        else:
            state = "PASS"

        results.append({
            "id": sc.id, "domain": sc.domain, "risk_class": sc.risk_class,
            "state": state, "ok": ok, "observed": observed,
            "why": why, "error": err, "changed": changed,
            "ms": round((time.time() - started) * 1000, 1),
        })

    counts = {s: sum(1 for r in results if r["state"] == s) for s in STATES}
    measurable = len(results) - counts["NO_VERIFIER"]
    return {
        "at": time.time(),
        "results": results,
        "counts": counts,
        "measurable": measurable,
        "pass_rate": (round(counts["PASS"] / measurable, 3)
                      if measurable else None),
        # 這三個欄位一定要跟著結果走，理由見模組檔頭。
        "axes_covered": list(AXES_COVERED),
        "axes_missing": list(AXES_MISSING),
        "axes_why": AXES_WHY,
        "has_baseline": bool(base_sc),
        "baseline_by": base.get("by") if isinstance(base, dict) else None,
        "baseline_at": base.get("at") if isinstance(base, dict) else None,
        "pack_covers_spec": _check_pack_covers_spec(),
    }


def summary(*, baseline_path: Path | None = None) -> dict:
    """給畫面用的一小包。不含 observed 全文，那個太大。"""
    r = run(baseline_path=baseline_path)
    return {
        "counts": r["counts"],
        "measurable": r["measurable"],
        "pass_rate": r["pass_rate"],
        "has_baseline": r["has_baseline"],
        "baseline_by": r["baseline_by"],
        # **一條很舊的基準線跟一條剛剛錄的，在一張綠色的表上長得
        # 一模一樣。** 「跟基準線一致」這句話的分量完全取決於那條線
        # 是什麼時候、誰錄的，所以兩個一起帶，不只帶 by。
        "baseline_at": r["baseline_at"],
        # §15.2 十類蓋滿了沒有。蓋不滿的時候通過率還是會很好看，
        # 因為沒列進來的那幾類根本不在分母裡。
        "pack_covers_spec": r["pack_covers_spec"],
        "axes_covered": r["axes_covered"],
        "axes_missing": r["axes_missing"],
        "axes_why": r["axes_why"],
        "rows": [{"id": x["id"], "domain": x["domain"],
                  "risk_class": x["risk_class"], "state": x["state"],
                  "why": x["why"], "changed": x["changed"]}
                 for x in r["results"]],
    }


SUBCOMMANDS: tuple[str, ...] = ("list", "baseline", "run")


def case_ids() -> tuple[str, ...]:
    """`run` 的題名收得了哪些值。**來源只有 PACK 一個。**

    另抄一份寫死清單的話，加題目的人要記得改兩個地方，
    而忘記改的那一次不會報錯 —— 它會說「沒有這一題」。
    """
    return tuple(s.id for s in PACK)


def main(argv: list[str]) -> int:
    args = list(argv)
    # 子指令的位置放了一個旗標 -> 明著退回。2026-09-18 實測沒有這一道的
    # 後果：`probe --only goal_persistence` 的 `--only` 落進 `cmd`，
    # 三個 if 都對不上，於是掉到最後那一行跑**全部十題**、exit=0。
    # 使用者要的是一題，拿到的是全部，而畫面跟成功一模一樣。
    # 排在未知子指令守門之前，因為「你給的是旗標」比「不認得這個指令」
    # 講得更準 —— 這一支根本沒有任何旗標。
    if args and str(args[0]).startswith("-"):
        print(f"這一支沒有旗標：{args[0]}", file=sys.stderr)
        print(f"子指令是：{'、'.join(SUBCOMMANDS)}"
              "（題名寫在 run 後面，例如 `probe run goal_persistence`）",
              file=sys.stderr)
        return 2
    cmd = args[0] if args else "run"
    # 子指令打錯字 -> 明著退回。實測 `probe lisst` 靜默跑滿十題、exit=0：
    # 要清單的人拿到一份跑完的報告，而且它是綠的。
    if cmd not in SUBCOMMANDS:
        print(f"不認得這個指令：{cmd}", file=sys.stderr)
        print(f"有的是：{'、'.join(SUBCOMMANDS)}", file=sys.stderr)
        print("不擋的話這裡不會報錯，它會掉進 run 跑滿整包然後印綠的。",
              file=sys.stderr)
        return 2

    if cmd == "list":
        for s in PACK:
            mark = "  " if VERIFIERS.get(s.id) else "！"
            print(f"{mark} {s.id:<24} {s.risk_class:<9} {s.domain}")
        print(f"\n§15.2 十類蓋滿了嗎：{_check_pack_covers_spec()['ok']}")
        return 0

    if cmd == "baseline":
        by = args[1] if len(args) > 1 else ""
        # `by` 是自由文字，所以旗標長相的東西照樣收得進去。
        # `baseline --by me` 會記成 by="--by"，而 `record_baseline` 只查
        # 空字串，擋不住它。一條記著 by="--by" 的基準線滿足「有人負責」
        # 這個條件的字面，卻答不出當時是誰按的 —— 那正是那條規則要防的。
        # **這一條沒有實跑過**：跑它就會往正本寫一條基準線。
        # 量測改在測試裡攔 `record_baseline` 做（`ProbeBaselineBy`）。
        if by.startswith("-"):
            print(f"這不是人名：{by}", file=sys.stderr)
            print("用法：`probe baseline <誰按的>`。這一支沒有旗標。",
                  file=sys.stderr)
            return 2
        try:
            out = record_baseline(by=by)
        except ProbeError as e:
            print(f"沒有寫：{e}")
            return 2
        print(json.dumps(out, ensure_ascii=False))
        return 0

    only = args[1] if len(args) > 1 and cmd == "run" else None
    # 題名不在 PACK 裡 -> 明著退回。上面兩道守的是「指令的位置放錯東西」，
    # 這一道守的是「指令對了，值不存在」，三個相鄰的洞。
    # 2026-09-18 實測沒有這一道的後果：`probe run bogus_case` 挑出 0 題，
    # 印「可量的 0 個：PASS 0、REGRESSED 0」、exit=0 —— 那是一份**綠的
    # 空報告**，比報錯難發現得多，因為通過率的分母也是 0。
    if only is not None and only not in case_ids():
        print(f"沒有這一題：{only}", file=sys.stderr)
        print(f"有的是：{'、'.join(case_ids())}", file=sys.stderr)
        print("不擋的話這裡不會報錯，它會挑出 0 題然後印 PASS 0、exit=0，"
              "看起來像跑過而且全綠。", file=sys.stderr)
        return 2
    r = run(only=only)
    for x in r["results"]:
        print(f"{x['state']:<12} {x['id']:<24} {x['why']}")
        if x.get("changed"):
            print(f"{'':<12} 跟基準線不同的欄位：{'、'.join(x['changed'])}")
    c = r["counts"]
    print(f"\n可量的 {r['measurable']} 個：PASS {c['PASS']}、"
          f"REGRESSED {c['REGRESSED']}、NEW {c['NEW']}")
    print(f"沒有東西可量的：{c['NO_VERIFIER']} 個（不算進通過率）")
    print(f"跨得了的軸：{'、'.join(r['axes_covered'])}；"
          f"跨不了的：{'、'.join(r['axes_missing'])}")
    return 0 if c["REGRESSED"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
