#!/usr/bin/env python3
"""最小交接契約。v5.0 §39.1

`handoff.py` 已經在寫 `.forseti/NEXT.md`，而 ROADMAP 對它的描述是
「交接檔 C4 的**一半**」。這一支回答那句話裡沒講的另一半是什麼：
**照規格，一份交接該帶哪些欄位，這一份實際帶了哪些。**

## 為什麼這件事值得做

2026-09-16 這個專案被過期狀態檔咬過一次：`PHASE_STATUS.md` 寫五階
沒開始，實際三階已完成，於是有人重做了一遍。那不是文件寫錯，
是**沒有人在檢查交接帶了什麼**。一份缺一半欄位的交接，
跟一份完整的交接，在畫面上長得一模一樣。

所以這一支不產生任何新事實，它只做一件事：把 §39.1 那張表變成
可以逐欄位比對的物件，然後說出每一欄的狀態與出處。

## 五種狀態，不是兩種

「有」跟「沒有」兩格不夠用，而且會說謊。一個欄位可能是：

| 狀態 | 意思 | 為什麼要跟別的分開 |
|---|---|---|
| PRESENT | 有值，帶得出出處 | — |
| EMPTY | 有資料來源，此刻是空的 | 空的可能是對的（真的還沒有 checkpoint） |
| NOT_CARRIED | 算得出來，這份交接沒有帶 | **這是一條線的距離**，跟做不到完全不同 |
| NO_SOURCE | 整個系統沒有地方算得出它 | 要先有某個物件存在才談得上 |
| DEGRADED | 有值，但那個值不滿足規格要求它的性質 | 最危險的一種，因為它看起來是有的 |

DEGRADED 只用在**機械比得出來**的情況（例如某個 id 的值等於另一個
id、git HEAD 配上一個非空的工作區），不用在語意判斷。
這是 §8.3 的禁止捷徑：分不出來就不要分。

## 沒有說明理由的缺席，自己就是一個缺陷

`ctx` 裡給 `None` 或整個沒給那一欄，一律算成 NO_SOURCE，而且另外
記成 `undeclared`。**一個沒有人說明為什麼不見的欄位，比一個說得出
理由的缺席更糟** —— 前者讀起來像沒人想過，後者至少指得出下一步。
這一條讓「補一句理由」變成寫程式的人繞不過去的事。

## 兩個覆蓋率，不是一個

一個數字會被拿去當分數，然後 NO_SOURCE 那些會被算成「我們的錯」，
接著就有人想把它們改成空清單讓數字好看。所以這裡給兩個：
`coverage` 是對整張表的，`coverage_of_possible` 把 NO_SOURCE 扣掉。
兩個都附分母，而且分母是 0 的時候回 None 不回 0 ——
一個算不出來的比率不是 0。

零依賴（ADR-009，那條規的是第三方套件）。專案內只借一支：
`claims._disk()` 用來算產出的內容雜湊，而且是**函式內延後 import
加可注入**，所以測試不必有它也跑得起來。自己再寫一次 sha256 會變成
兩份會分歧的實作，而分歧那天不會有錯誤訊息，只會有兩個都長得像
真雜湊的值 —— 這跟 `blast.py` 借 `cost.js` 是同一條原則。
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

VERSION = "contract@1.0"

REPO = Path(__file__).resolve().parents[2]

STATUS_PRESENT = "PRESENT"
STATUS_EMPTY = "EMPTY"
STATUS_NOT_CARRIED = "NOT_CARRIED"
STATUS_NO_SOURCE = "NO_SOURCE"
STATUS_DEGRADED = "DEGRADED"

#: 畫面與文字輸出共用的短名。英文狀態碼不給人看。
STATUS_ZH = {
    STATUS_PRESENT: "有",
    STATUS_EMPTY: "來源在，此刻空的",
    STATUS_NOT_CARRIED: "算得出來，沒帶",
    STATUS_NO_SOURCE: "沒有資料來源",
    STATUS_DEGRADED: "有值但不合規格",
}


@dataclass(frozen=True)
class Recheck:
    """一條 NO_SOURCE 理由背後那個查法，寫成可以真的跑一次的東西。

    ## 為什麼要有這個

    2026-09-16 22:5x 實測抓到：`logical_agent_id` 的理由寫著
    「§11.1 的 AgentIdentity 沒有實作（`grep -rn AgentIdentity apps/ src/`
    零命中）」，而 `identity.py` 在同一天 21:0x 就做好了。
    那句理由當初是查過的，**它是在寫下來之後才變成假的**。

    這正是這個專案付過代價的病（`PHASE_STATUS.md` 說五階沒開始、
    實際三階已完成，於是有人重做一遍）。差別只在那一次腐爛的是
    階段狀態，這一次腐爛的是「為什麼這一欄沒有來源」的理由。

    ## 它產生的是觸發器，不是結論

    B-05 擋住「任何單獨靠文字判斷某件事有沒有發生」的做法，
    但明文不擋「拿它當觸發器、再用證據驗證」。這一支是後者：
    命中數對不上的時候回報 `stale=True` 加上命中的位置，
    意思是**去看一眼**，不是「這條理由錯了」。

    實例就在眼前，而且它自己就示範了為什麼不能自動判：排除宣告檔之後
    `AgentIdentity` 仍然命中 `sot.py:223`，而那一處是一句**記錄這次更正
    的註解**（在那之前是一句「說它沒實作」的散文）。純比對分不出實作、
    散文、與一句講這件事的註解，所以這裡只給位置，判斷留給人。

    ## declared_in 一定要排除，不排除的話每一條都會自己觸發自己

    理由的文字本身含著那個 pattern（那句話就寫在 `contract.py` 裡），
    所以不排除宣告它的那個檔，`expect=0` 這種查法永遠不可能成立。
    """
    pattern: str
    paths: tuple = ("apps/forseti-cli", "src")
    expect: int = 0
    declared_in: tuple = ("apps/forseti-cli/contract.py",)


@dataclass(frozen=True)
class NoSource:
    """這個系統沒有地方算得出這一欄。`why` 是強制的。

    `recheck` 是選用的：理由裡如果附了一個查法，把它也寫成資料，
    這樣那個查法會真的被跑，而不是留在散文裡等人去跑。
    **不從 `why` 的文字剖析查法** —— 那又是一次文字判斷（B-05）。
    """
    why: str
    recheck: object = None


@dataclass(frozen=True)
class Empty:
    """有資料來源，此刻是空的，而且說得出要怎麼樣才會有值。

    2026-09-16 22:5x 加。先前 EMPTY 只能靠「值剛好是空的」判出來，
    於是它在缺口清單上是唯一一種**連理由都沒有**的狀態 ——
    一個空欄位跟一個說得出下一步的空欄位，在畫面上長得一模一樣，
    而後者才指得出「誰去做什麼它就會有值」。

    狀態仍然是五種，沒有變成六種。這只是讓 EMPTY 也帶得動一句話。
    """
    why: str


@dataclass(frozen=True)
class NotCarried:
    """算得出來，但這份交接沒有帶。`where` 指出它在哪裡算得出來。"""
    where: str


@dataclass(frozen=True)
class Degraded:
    """有值，但那個值不滿足規格要求它的性質。"""
    value: object
    why: str


# ---------------------------------------------------------------------------
# §39.1 那張表，逐字
# ---------------------------------------------------------------------------
#
# 右欄的英文是規格原文（`docs/sources/..._v5.0_2026-09-04.md:1227-1239`），
# 一個字都不改。中文是說明，不是翻譯權威 —— 對不上的時候以英文為準。

GROUPS: tuple = (
    ("Identity", "身份", (
        ("project_id", "job/project id", "這件工作屬於哪個專案"),
        ("objective", "objective", "要達成什麼"),
        ("owner", "owner", "誰是主人"),
        ("timestamp", "timestamp", "這份交接是什麼時候寫的"),
        ("logical_agent_id", "logical agent id", "換 session 不換的那個身份"),
        ("session_id", "session id", "這一條 session 的 id"),
    )),
    ("Reality", "現實座標", (
        ("canonical_root", "canonical root", "正本在哪裡"),
        ("runtime_node", "active machine/runtime node", "現在跑在哪台機器"),
        ("target_environment", "target environment", "目標環境是哪一個"),
    )),
    ("Model", "模型", (
        ("model_identity", "model identity", "用的是哪個模型"),
        ("model_config", "config", "什麼設定"),
        ("model_revision", "revision/hash", "哪一版"),
    )),
    ("Data", "資料", (
        ("dataset_manifest", "dataset manifest", "用了哪些資料"),
        ("source_classes", "source classes", "資料的來源類別"),
        ("leakage_result", "split/group leakage result", "切分有沒有洩漏"),
    )),
    ("Execution", "執行", (
        ("commands_run", "commands actually run", "實際跑過哪些指令"),
        ("code_commit", "tool/code commit", "跑的是哪一版程式碼"),
        ("process_status", "process status", "程序現在是什麼狀態"),
    )),
    ("Metrics", "指標", (
        ("metrics_by_distribution", "current metrics by distribution "
         "with Metric Provenance Contract", "現在的數字，附出處契約"),
    )),
    ("Artifacts", "產出", (
        ("artifact_paths", "paths/IDs", "產出在哪裡"),
        ("artifact_hashes", "hashes", "產出的內容雜湊"),
    )),
    ("Limits", "限制", (
        ("blockers", "blockers", "被什麼擋住"),
        ("known_limits", "known limits", "已知做不到什麼"),
        ("failed_attempts", "failed attempts", "試過而且失敗的做法"),
        ("invalidated_conclusions", "invalidated conclusions", "已經作廢的結論"),
    )),
    ("Next", "下一步", (
        ("next_step", "exact next executable step", "下一個真的可執行的步驟"),
        ("stop_condition", "stop condition", "做到什麼程度停"),
    )),
    ("Claims", "可以對外講什麼", (
        ("claims_allowed", "public/operational claims allowed", "允許講的"),
        ("claims_prohibited", "claims explicitly prohibited", "明文禁止講的"),
    )),
    ("Recovery", "復原", (
        ("recovery_status", "backup/checkpoint/cleanup status", "備份與檢查點狀態"),
        ("last_good_pointer", "last-known-good pointer", "最後一個已知良好的點"),
    )),
)

#: 全部欄位數。測試釘住它，欄位被偷偷拿掉的時候會紅。
TOTAL_FIELDS = sum(len(g[2]) for g in GROUPS)

_UNDECLARED_WHY = (
    "沒有人說明為什麼沒有資料來源。"
    "一個沒有理由的缺席指不出下一步，比說得出理由的缺席更糟"
)


# ---------------------------------------------------------------------------
# 判狀態
# ---------------------------------------------------------------------------

def _is_empty(v: object) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, tuple, dict, set)):
        return len(v) == 0
    return False


def _shown(v: object, limit: int = 160) -> str:
    """給人看的一行。不是序列化，不要拿它回推原值。"""
    if isinstance(v, str):
        s = " ".join(v.split())
    elif isinstance(v, (list, tuple)):
        s = f"{len(v)} 筆：" + "；".join(_shown(x, 40) for x in list(v)[:3])
    elif isinstance(v, dict):
        s = "；".join(f"{k}={_shown(x, 40)}" for k, x in list(v.items())[:4])
    else:
        s = str(v)
    return s[:limit]


def classify(v: object) -> dict:
    """一個 ctx 值 → 狀態。純函式，沒有副作用。"""
    if isinstance(v, NoSource):
        return {"status": STATUS_NO_SOURCE, "why": v.why,
                "shown": "", "undeclared": False}
    if isinstance(v, NotCarried):
        return {"status": STATUS_NOT_CARRIED, "why": v.where,
                "shown": "", "undeclared": False}
    if isinstance(v, Degraded):
        return {"status": STATUS_DEGRADED, "why": v.why,
                "shown": _shown(v.value), "undeclared": False}
    if isinstance(v, Empty):
        return {"status": STATUS_EMPTY, "why": v.why,
                "shown": "", "undeclared": False}
    if v is None:
        return {"status": STATUS_NO_SOURCE, "why": _UNDECLARED_WHY,
                "shown": "", "undeclared": True}
    if _is_empty(v):
        return {"status": STATUS_EMPTY, "why": "", "shown": "",
                "undeclared": False}
    return {"status": STATUS_PRESENT, "why": "", "shown": _shown(v),
            "undeclared": False}


# ---------------------------------------------------------------------------
# 產出的內容雜湊（§39.1 Artifacts 的第二欄）
# ---------------------------------------------------------------------------

def _claims_disk():
    """借 `claims._disk()`，不自己算。見檔頭那一段的理由。

    它是私有名字，所以 `test_借的是claims那一支` 釘住這件事：
    哪天它改名或改掉回傳欄位，那條會紅，
    而不是這裡靜默地每一筆都回不出雜湊。
    """
    import claims                    # noqa: PLC0415  故意延後，見檔頭
    return claims._disk


def _invalidated(base=None) -> list[str]:
    """借 `pollution.invalidated_conclusions()`，不自己判讀散文。

    §40 的登記簿是唯一的來源。這裡不去掃 AUTO_CONTINUE_LOG 的句型 ——
    那是 B-05 擋住的做法（字串比對不能單獨產生 finding）。

    登記簿不存在就回空清單，而空清單在 `check()` 那邊是 EMPTY 不是
    NO_SOURCE：來源在了，只是此刻沒有未解決的。
    """
    import pollution                 # noqa: PLC0415  故意延後，同 _claims_disk
    p = None
    if base is not None:
        p = Path(base) / ".forseti" / "pollution.jsonl"
    return pollution.invalidated_conclusions(p)


def _identity_registry(base):
    """借 `identity.registry()`，不自己讀那個 jsonl。

    延後 import 加上讀不到就回 None，理由跟 `_claims_disk()` 同一條：
    自己再解析一次 `.forseti/identity.jsonl` 會變成兩份會分歧的實作。
    **拿不到的時候回 None 不回 `[]`** —— 空清單讀起來是
    「登記簿在，裡面沒有人」，而實情是「連登記簿這個東西都問不到」。
    """
    try:
        import identity            # noqa: PLC0415  故意延後，見 _claims_disk
        return identity.registry(base)
    except Exception:              # noqa: BLE001  模組不在、檔案壞掉都算問不到
        return None


#: `logical_agent_id` 那條理由當初的查法。2026-09-16 22:5x 起它是假的，
#: 留在這裡是為了讓 `recheck_all()` 有東西可以對照 —— 一條被推翻的查法
#: 刪掉就沒有人知道它曾經被推翻過（§40 同一條）。
_RC_AGENT_IDENTITY = Recheck("AgentIdentity")


def _logical_agent_id(base, snap: dict | None, reg: object = None) -> object:
    """§39.1 Identity 的第五欄：換 session 不換的那個身份。

    ## 這一欄 2026-09-16 22:5x 從 NO_SOURCE 改成 EMPTY，而那是一次更正

    先前的理由寫著「§11.1 的 AgentIdentity 沒有實作
    （`grep -rn AgentIdentity apps/ src/` 零命中）」。
    **那句話在寫下來的時候是真的，現在不是了** —— `identity.py`
    在同一天 21:0x 做好，`registry()` 就是這一欄的來源。

    差別不是措辭：NO_SOURCE 的意思是「要先有某個東西存在才談得上」，
    而現在的實情是「東西在了，沒有人去登記」。後者是一條線的距離，
    前者讀起來像還要蓋一整個系統。

    ## 不做模糊比對

    `sid` 要**完全相符**才算認領。不比前綴、不比相似度，理由跟
    `identity.py` 檔頭那一段同一條（B-05）：`norikaoda-03` 與
    `norikaoda-84` 前綴一樣但不保證同一個身份，而改過命名的同一個
    身份會長得像兩個。查不到就說查不到。
    """
    rows = _identity_registry(base) if reg is None else reg
    if rows is None:
        return NoSource(
            "問不到 `identity.registry()`（模組不在或登記簿讀不出來）。"
            "這一欄的來源在 `apps/forseti-cli/identity.py`",
            recheck=_RC_AGENT_IDENTITY)
    sid = ((snap or {}).get("session") or "").strip()
    for r in rows:
        if sid and sid in (r.get("aliases") or ()):
            return r.get("agent_id") or ""
    if not rows:
        return Empty(
            "`identity.py`（§11.1 五軸）就是這一欄的來源，而"
            "`.forseti/identity.jsonl` 此刻 0 條登記。"
            "帳本裡被當成身份用的那些字串是 session alias，換 session 就換，"
            "所以要有值得有人去登記：`identity.register(agent_id, aliases)`。"
            "**不從 alias 的長相推斷**，那是 B-05 擋住的做法")
    return Empty(
        f"登記簿有 {len(rows)} 條，但這一條 session 的識別字串"
        f"（`{sid or '空的'}`）不在任何一條的 alias 裡。"
        "完全相符才算認領，不比前綴也不比相似度（B-05）")

# ---------------------------------------------------------------------------
# 另外四個 EMPTY 欄位的理由（2026-09-16 23:3x）
# ---------------------------------------------------------------------------
#
# `Empty(why)` 在 22:5x 那一輪加進來，但只有 `logical_agent_id` 用它。
# 另外四欄（blockers / next_step / last_good_pointer / recovery_status）
# 此刻都是空的，而且**是唯一一批連理由都沒有的空欄位** ——
# 在缺口清單上它們印出來只有一句「來源在，此刻空的」，
# 指不出「誰去做什麼它就會有值」。
#
# 四支都**借現成的判斷**，不自己再判一次：
# `next_step` 借 `stuck.py` 的 kind、`last_good_pointer` 借
# `checkpoint.summary()` 已經算好的 `why_no_last_good`。
# 兩份會分歧的判斷遲早會分歧，而分歧那天不會有錯誤訊息。


def _next_step(work: dict | None) -> object:
    """§39.1 Next 的第一欄：下一個真的可執行的步驟。

    ## 為什麼不能把「沒有下一步」一律說成同一件事

    `handoff.py` 付過這個代價：先前它對所有沒有下一步的情況都寫
    「可能是任務還沒拆成步驟」，而對正本那兩件任務那句是**假的**
    （步驟全部驗證完成了，等的是收尾）。一句猜錯方向的指示比沒有
    指示糟，它讓人去找一件不存在的事。

    所以這裡照 `stuck.py` 算出來的 kind 分開講，而且**不自己判**：
    同一件事有兩個地方各判一次的話，遲早會分歧。

    ## 認不得的 kind 不編解釋

    `stuck.py` 的 kind 是一張會長的表。認不得的時候原樣把 kind 與
    headline 帶出來，不套一句聽起來合理的話 —— 那是 §8.3 的填空。
    """
    w = work or {}
    tasks = w.get("tasks") or []
    rows = [f"{t.get('id', '')}　{(t.get('next_step') or {}).get('objective', '')}"
            for t in tasks if t.get("next_step")]
    if rows:
        return rows
    if not tasks:
        return Empty(
            "帳本裡此刻沒有任務，所以沒有步驟可以派。"
            "要有值得先有一件任務被拆成步驟（`ledger` 的 tasks/steps 兩張表）")

    kinds: dict = {}
    for t in tasks:
        k = ((t.get("stuck") or {}).get("kind") or "").strip() or "（沒有判定）"
        kinds.setdefault(k, []).append(str(t.get("id") or ""))

    if set(kinds) == {"ALL_VERIFIED"}:
        ids = "、".join(kinds["ALL_VERIFIED"])
        return Empty(
            f"{len(kinds['ALL_VERIFIED'])} 件任務（{ids}）的步驟"
            "**全部驗證完成**了，所以沒有東西可以派 —— 這不是卡住。"
            "等的是收尾，而系統不自己收尾：那是一次狀態轉換，要留給人按。"
            "畫面上那一格的動作是「收尾」")
    if set(kinds) == {"NO_STEPS"}:
        ids = "、".join(kinds["NO_STEPS"])
        return Empty(
            f"{len(kinds['NO_STEPS'])} 件任務（{ids}）還沒有被拆成步驟。"
            "要有值得有人把任務拆開，拆之前這一欄算不出下一步")
    # 混合或認不得的，把 kind 原樣列出來，判斷留給人。
    parts = [f"{k}：{len(v)} 件（{'、'.join(v)}）" for k, v in sorted(kinds.items())]
    return Empty(
        "沒有任何一件任務有可派的步驟，而它們卡住的原因**不只一種**，"
        "所以這裡不給一句總結。逐件的判定（`stuck.py` 算的）是："
        + "；".join(parts))


def _blockers_field(work: dict | None) -> object:
    """§39.1 Limits 的第一欄：被什麼擋住。

    ## 這一欄跟 `.forseti/BLOCKERS.md` 不是同一件事

    這一欄的來源是**帳本裡被標成 blocked 的步驟**，是執行中真的卡住
    的東西。`BLOCKERS.md` 那幾條（B-01 … B-15）在 `known_limits` 那一欄，
    是寫下來的阻塞清單。

    不講清楚的話這一欄的空值會跟 `NEXT.md` 上那一節打架：那裡列著
    好幾條擋住的，這裡卻是空的，讀起來像其中一邊壞了。
    兩邊回答的不是同一個問題。
    """
    rows = [f"被擋住：{b}" for b in ((work or {}).get("blocked") or [])]
    if rows:
        return rows
    return Empty(
        "這一欄的來源是帳本裡被標成 blocked 的步驟，此刻 0 筆。"
        "**`.forseti/BLOCKERS.md` 那幾條不在這一欄**，它們在 `known_limits`："
        "一個是執行中被卡住的步驟，一個是寫下來的阻塞清單，兩件事。"
        "要有值得有某個步驟真的被標成 blocked")


def _recovery_status(snap: dict | None) -> object:
    """§39.1 Recovery 的第一欄：備份與檢查點狀態。"""
    cps = (snap or {}).get("checkpoints") or {}
    total = cps.get("total") or 0
    if total:
        return f"checkpoint {total} 個"
    # 【2026-09-17 加】碟上別條 session 的那些要講出來。
    #
    # 先前這一欄在 0 個的時候只寫「這條線上沒有可以回去的那一刻」，
    # 那句話對，但接手的人讀完會以為這台機器上什麼都沒有。實測
    # `.forseti/checkpoints.jsonl` 有 3 筆、全部被人標成 last_good、
    # 分屬兩條舊 session。**判定不變**（這條線上仍然是 EMPTY），
    # 變的是理由裡有沒有把碟上的事實一起講。
    els = cps.get("elsewhere") or {}
    extra = ""
    if els.get("total"):
        extra = (f"。碟上另有 {els['total']} 個 checkpoint（其中 "
                 f"{els.get('last_good', 0)} 個被標成 last_good），"
                 f"分屬 {els.get('sessions', 0)} 條別的 session。"
                 "**它們不算這條線上的點** —— 要不要接過來是 owner 的決定")
    return Empty(
        "`checkpoint.py`（§17）就是這一欄的來源，而這一條 session 此刻"
        "**0 個 checkpoint**。要有值得落一個："
        "`checkpoint.create(session=..., n=..., reason=...)`，"
        "或走畫面上那個按鈕。"
        "**0 個不等於沒有備份** —— 它只說這條線上沒有可以回去的那一刻"
        + extra)


def _last_good_pointer(snap: dict | None) -> object:
    """§39.1 Recovery 的第二欄：最後一個已知良好的點。

    ## 那句理由借 `checkpoint.summary()` 的，不在這裡再寫一次

    `checkpoint.py:121` 的 `why_no_last_good` 已經說得出「系統不自己挑
    —— 最近的那一個常常正是出事的那一個」。在這裡複製一份，
    哪天那邊改了措辭或改了政策，兩句話會不一樣而且沒有人會發現。

    ## 一個 checkpoint 都沒有的時候，那句話技術上對但指錯方向

    `why_no_last_good` 說的是「沒有任何 checkpoint 被標成 last_good」，
    在 0 個的情況下它讀起來像「去標一個」，而實情是**先得有一個**。
    兩種情況的下一步不一樣，所以分開講。
    """
    cps = (snap or {}).get("checkpoints") or {}
    lg = cps.get("last_good")
    if lg:
        return lg
    if not (cps.get("total") or 0):
        # 【2026-09-17 加】同 `_recovery_status`：0 個的時候要順帶說
        # 碟上有沒有別條 session 的。不講的話這一句讀起來是全稱否定。
        els = cps.get("elsewhere") or {}
        extra = ""
        if els.get("last_good"):
            extra = (f"。碟上另有 {els['last_good']} 個被標成 last_good 的"
                     f" checkpoint，分屬 {els.get('sessions', 0)} 條別的"
                     " session。**這裡不替 owner 決定它們算不算數** —— "
                     "跨 session 挑一個回去是一次狀態轉換，"
                     "跟 `last_good()` 不自己挑最近的那一個是同一條政策")
        return Empty(
            "這一條 session 一個 checkpoint 都沒有，所以談不上哪一個是"
            "已知良好的點。**下一步是先落一個**，不是去標記"
            "（`recovery_status` 那一欄是同一個來源）" + extra)
    why = (cps.get("why_no_last_good") or "").strip()
    if why:
        return Empty(
            why + "。要有值：打開任一輪，按「標記這裡是好的」")
    return Empty(
        f"有 {cps.get('total')} 個 checkpoint，沒有一個被標成 last_good，"
        "而 `checkpoint.summary()` 這一次沒有帶 `why_no_last_good`。"
        "**這裡不自己補一句理由** —— 那會變成第二個說法")



def _metrics_field(*, path: Path | None = None) -> object:
    """§39.1 Metrics 那一欄。來源是 `metrics.py` 的 §33.1 登記簿。

    ## 空的時候是 EMPTY 不是 NO_SOURCE，而且那不是壞消息

    登記簿空的意思是「有地方可以登記，此刻沒有人登記」，
    跟「這個系統沒有出處契約這個東西」差一整條實作。
    `Empty` 帶著的那句話要指得出誰去做什麼它才會有值，
    不然一個空欄位跟一個死路長得一模一樣。

    ## 為什麼不在這裡自動登記一筆

    這一欄最容易的作弊方式是拿手邊現成的數字（測試通過數）
    配一組猜出來的欄位登記上去，數字立刻從 0 變 1。
    `metrics.py` 的模組說明寫了為什麼不做：材料類別歸不了類的數字
    照 §33.1 本來就登記不了，硬歸一類就是 §8.3 的填空。

    ## 只算 releasable 的那些嗎？不

    **總數與夠格數兩個都報。** 只報夠格數的話，一筆登記了但血緣
    不齊的記錄會從畫面上消失，而那一筆正是要有人去補提供端的那一筆。
    """
    try:
        import metrics as MT                      # 延後 import，同 claims
        d = MT.by_distribution(path=path)
    except Exception as exc:                      # pragma: no cover - 防禦
        return NoSource(f"讀不到 §33.1 登記簿：{type(exc).__name__}: {exc}")
    if not d.get("total"):
        return Empty(
            "`metrics.py`（§33.1 Metric Provenance Contract）就是這一欄的"
            "來源，而 `.forseti/metrics.jsonl` 此刻 0 筆。"
            "要有值得有人把尺與材料寫下來登記一筆："
            "`forseti metric template` 產模板，填完 "
            "`forseti metric register --from <檔案>`。"
            "**這一支不自動登記** —— 拿現成數字配一組猜出來的欄位"
            "就是 §8.3 的填空")
    return d


def _failed_attempts_field(*, path: Path | None = None) -> object:
    """§39.1 failed_attempts 那一欄。來源是 `attempts.py` 的登記簿。

    ## 空的時候是 EMPTY 不是 NO_SOURCE

    跟 `_metrics_field()` 同一條。登記簿空的意思是「有地方可以登記，
    此刻沒有人登記」，跟「這個系統沒有失敗嘗試這個物件」差一整條實作。

    ## 為什麼不在這裡自動萃取

    這一欄最容易的作弊方式是去掃 `AUTO_CONTINUE_LOG.md` 的散文，
    抓「試了……沒好」那類句型湊出幾筆，數字立刻從 0 變好幾。
    `attempts.py` 的模組說明寫了為什麼不做（B-05）:
    抓到的會是符合句型的句子，不是真的失敗嘗試。

    ## 報的是還在擋路的那些，總數也一起報

    放掉的那些不從畫面上消失。「這件事以前試過，後來條件變了」
    正是下一個人需要知道的東西，只報還在擋路的話那件事會不見。
    """
    try:
        import attempts as AT                     # 延後 import，同 metrics
        s = AT.summary(path=path)
    except Exception as exc:                      # pragma: no cover - 防禦
        return NoSource(f"讀不到失敗嘗試登記簿：{type(exc).__name__}: {exc}")
    if not s.get("total"):
        return Empty(
            "`attempts.py`（§39.1 failed_attempts）就是這一欄的來源，"
            "而 `.forseti/attempts.jsonl` 此刻 0 筆。"
            "要有值得有人把一次失敗的嘗試寫下來："
            "`forseti attempt template` 產模板，填完 "
            "`forseti attempt record --from <檔案>`。"
            "規格要的是三件事（試了什麼、看到什麼、為什麼不重試），"
            "**這一支不自動萃取散文** —— 抓句型抓到的是符合句型的句子，"
            "不是真的失敗嘗試（B-05）")
    return s


def _runtime_node() -> object:
    """§39.1 Reality 的第二欄：現在跑在哪台機器。

    ## 這一欄先前是 NO_SOURCE，理由已經不成立了

    那句理由寫著「§12.1 的 RuntimeNode 沒有實作」，
    2026-09-17 `apps/forseti-cli/runtimenode.py` 之後不再是真的。
    **一句當初查過、後來才變假的理由**，正是 `Recheck` 那個 class
    整個存在的原因，所以這一欄不留著那句話等人來複查，直接接上來源。

    ## 接的是 `reference()` 不是 `describe()`

    §39.1 那一欄問的是「active machine/runtime node」 ——
    指得出是哪一台就答完了，不是要那個實體的六個欄位。
    `runtimenode.describe()` 回的是完整實體（六欄裡三欄是空的，
    各自帶著為什麼），那是另一個問題的答案。
    **在這裡接 `describe()` 會讓這一欄變成 DEGRADED，
    而那個降級的理由來自另一張表** —— §5 的實體完整度，不是 §39.1
    的這一欄有沒有答出來。兩張表混在一起，讀的人會以為
    「不知道跑在哪台機器」，實情是知道。

    ## `basis` 一起帶著走

    退回 hostname 算出來的 node_id 會在改機器名字的那天變掉，
    而那件事在畫面上跟「換了一台機器」長得一模一樣。
    只帶 node_id 不帶 basis 的話，沒有人分得出來。
    """
    try:
        import runtimenode                   # noqa: PLC0415  故意延後
        return runtimenode.reference()
    except Exception as e:                   # noqa: BLE001
        # 量不到就說量不到。**不退回 hostname 假裝量到了** ——
        # 這一支自己失敗跟這台機器沒有識別碼是兩件事。
        return NoSource(
            f"`runtimenode.reference()` 這一次沒跑成：{type(e).__name__}: {e}")


def _hcache_file(base: Path) -> Path:
    return Path(base) / ".forseti" / "cache" / "artifact_hashes.json"


def _hcache_load(base) -> dict:
    """讀不到、壞掉一律回空的重算，不猜。"""
    if base is None:
        return {}
    try:
        raw = json.loads(_hcache_file(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _hcache_save(base, data: dict) -> None:
    """**寫失敗不算錯誤**，功能本身不依賴它。"""
    if base is None:
        return
    f = _hcache_file(base)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _fingerprint(path: Path) -> str:
    """mtime_ns 加 size。跟 `blast.py` 同一條，理由也同一條。

    **不用時間當有效期。** 那會有一個很難查的症狀：改完檔案畫面不動，
    而且不會有任何錯誤訊息。量不到就回空字串，空指紋一律不命中 ——
    一個編出來的指紋會讓快取永遠命中，那比沒有快取糟得多。
    """
    try:
        st = path.stat()
    except OSError:
        return ""
    return f"{st.st_mtime_ns}-{st.st_size}"


def artifact_hashes(paths, cwd=None, disk=None, cache=None) -> list:
    """對交接裡的產出清單逐個算內容雜湊。

    **三條誠實條款，因為這一欄最容易被讀成它不是的東西。**

    一，這是**此刻磁碟上**的內容，不是寫入當下的內容。中間被誰改過
        這裡看不出來，所以欄位叫 `hashed_at` 而不是「產出時的雜湊」
        —— 後者是一句這個系統證明不了的話。

    二，**算不出來的三種原因不併成一種。** 檔案不在了（missing）、
        量不到（unmeasured，權限或檔案系統）、它是目錄（dir，沒有
        內容雜湊這個概念）。併成一個 None 的話，一個已經被刪掉的
        產出跟一個讀不到的產出在畫面上長得一模一樣，
        而前者是「這份交接指向不存在的東西」，後者不是。

    三，**空清單就是空清單**，不補任何東西。沒有產出路徑的時候
        這一欄是 EMPTY，那是對的狀態，不是失敗。

    四，**命中快取的那一筆，`hashed_at` 是上次量的時間不是此刻。**
        2026-09-16 18:2x 加快取時實測：這個 repo 的工作區有 88 個檔，
        逐個 `read_bytes` 要 1.008 秒（外接碟，每檔約 12 毫秒的開檔成本），
        而 `stat` 只要 0.005 秒。1 秒會讓 `strands` 從 1.29 秒變成 2.3 秒，
        超過畫面 2 秒的輪詢間隔 —— 那正是上一輪剛修掉的那個問題。
        所以指紋（mtime_ns 加 size）沒變就不重讀，**而時間戳不跟著跳**：
        把它改成此刻等於宣稱剛剛量過，那是一句這支函式證明不了的話。
        `cache` 沒給就整個不快取，測試注入 `disk` 的時候一律不快取。
    """
    d = disk or _claims_disk()
    base = Path(cwd) if cwd else None
    at = time.time()
    cbase = cache if (cache is not None and disk is None) else None
    cmap = _hcache_load(cbase)
    fresh = {}
    out = []
    for p in (paths or []):
        # 清單裡可以是純路徑字串，也可以是 `collect()` 組的
        # `{"path", "source", "vcs"}`。**認錯的代價不是例外，是靜默**：
        # `str({...})` 是一個永遠不存在的路徑，於是每一筆都回 missing，
        # 而 missing 讀起來是「這份交接指向不存在的東西」。
        key = p.get("path") if isinstance(p, dict) else str(p)
        key = str(key)
        if cbase is not None:
            fp = _fingerprint((base / key) if (base and not Path(key).is_absolute())
                              else Path(key))
            hit = cmap.get(key)
            if fp and isinstance(hit, dict) and hit.get("fp") == fp:
                out.append({"path": key, "state": hit.get("state"),
                            "hash": hit.get("hash"), "bytes": hit.get("bytes"),
                            "hashed_at": hit.get("at"), "cached": True})
                fresh[key] = hit
                continue
        r = d(str(key), cwd=base) or {}
        ex = r.get("existence")
        if r.get("is_dir"):
            state, h = "dir", None
        elif ex is False:
            state, h = "missing", None
        elif r.get("contentHash"):
            state, h = "ok", r["contentHash"]
        else:
            # existence 是 unknown，或存在但讀不出 bytes。
            # 兩種都是「量不到」，不是「不存在」。
            state, h = "unmeasured", None
        out.append({"path": key, "state": state, "hash": h,
                    "bytes": r.get("byteSize"), "hashed_at": at,
                    "cached": False})
        if cbase is not None and fp:
            fresh[key] = {"fp": fp, "state": state, "hash": h,
                          "bytes": r.get("byteSize"), "at": at}
    if cbase is not None:
        # 只留這一次用到的，不累積 —— 一個永遠長大的快取檔
        # 會讓每次讀取變慢，而那個變慢沒有任何錯誤訊息。
        _hcache_save(cbase, fresh)
    return out


_MISSING = object()


def check(ctx: dict | None) -> dict:
    """照 §39.1 逐欄位比對。

    `ctx` 沒有給到的欄位跟給 `None` 是同一件事 —— 都算成沒有理由的缺席。
    這是刻意的：漏掉一欄跟宣告一欄沒有來源，在後果上一樣，
    而後者至少留下一句話。
    """
    ctx = ctx or {}
    groups, tot = [], {STATUS_PRESENT: 0, STATUS_EMPTY: 0,
                       STATUS_NOT_CARRIED: 0, STATUS_NO_SOURCE: 0,
                       STATUS_DEGRADED: 0}
    undeclared = 0
    for name, zh, fields in GROUPS:
        out = []
        for key, spec_text, note in fields:
            raw = ctx.get(key, _MISSING)
            c = classify(None if raw is _MISSING else raw)
            tot[c["status"]] += 1
            undeclared += 1 if c["undeclared"] else 0
            out.append({"key": key, "spec": spec_text, "note": note,
                        "status": c["status"], "zh": STATUS_ZH[c["status"]],
                        "why": c["why"], "shown": c["shown"],
                        "undeclared": c["undeclared"]})
        groups.append({
            "group": name, "zh": zh, "fields": out,
            "present": sum(1 for f in out if f["status"] == STATUS_PRESENT),
            "total": len(out),
        })

    total = sum(tot.values())
    possible = total - tot[STATUS_NO_SOURCE]
    return {
        "version": VERSION,
        "spec": "v5.0 §39.1 Minimum Handoff Contract",
        "groups": groups,
        "totals": {
            "present": tot[STATUS_PRESENT],
            "empty": tot[STATUS_EMPTY],
            "not_carried": tot[STATUS_NOT_CARRIED],
            "no_source": tot[STATUS_NO_SOURCE],
            "degraded": tot[STATUS_DEGRADED],
            "undeclared": undeclared,
            "total": total,
        },
        # 分母是 0 的時候回 None。一個算不出來的比率不是 0。
        "coverage": (tot[STATUS_PRESENT] / total) if total else None,
        "coverage_of_possible": (
            (tot[STATUS_PRESENT] / possible) if possible else None),
        "possible": possible,
        "note": (
            "coverage 是對整張表；coverage_of_possible 把「沒有資料來源」"
            "那些扣掉。兩個都不是分數 —— NO_SOURCE 不等於做錯，"
            "NOT_CARRIED 才是一條線的距離"
        ),
        "gaps": gaps(groups),
    }


# ---------------------------------------------------------------------------
# 複查那些理由（§39.1 沒有要求這件事，是這個 repo 自己的傷）
# ---------------------------------------------------------------------------

def _rc_cache_file(base: Path) -> Path:
    return Path(base) / ".forseti" / "cache" / "recheck.json"


#: 指紋與 grep 都要跳過的目錄。**兩邊一定要一致**，不一致的症狀很難查：
#: 指紋把 `__pycache__` 算進去的話，每跑一次 python 都可能重寫 .pyc，
#: 於是指紋每次都不一樣、快取永遠不命中，而畫面上沒有任何異狀，
#: 只有 `strands` 慢兩秒。2026-09-16 22:5x 實測就是這樣（cached 恆為 False）。
_RC_SKIP_DIRS = ("__pycache__", ".git", "node_modules")


def _rc_skip(f: Path) -> bool:
    return any(part in _RC_SKIP_DIRS for part in f.parts)


def _rc_fingerprint(base: Path, paths: tuple) -> str | None:
    """掃描範圍的檔案集合加每個檔的 mtime_ns 與 size。

    照 `blast.py` 5a 那一套：失效靠指紋不靠時間。用時間當有效期會有一個
    很難查的症狀 —— 改完程式碼那條理由還是舊答案，而且不會有錯誤訊息。

    算不出來的時候回 None 而不是一個編出來的值。一個編出來的指紋會讓
    快取永遠命中，那比沒有快取糟得多。
    """
    import hashlib                   # noqa: PLC0415  只有這一支用得到
    h = hashlib.sha256()
    try:
        for rel in sorted(paths):
            d = Path(base) / rel
            if not d.exists():
                h.update(f"{rel}\x00MISSING\n".encode())
                continue
            for f in sorted(d.rglob("*")):
                if not f.is_file() or _rc_skip(f):
                    continue
                st = f.stat()
                h.update(f"{f}\x00{st.st_mtime_ns}\x00{st.st_size}\n".encode())
    except OSError:
        return None
    return h.hexdigest()[:16]


def _rc_cache_load(base) -> dict:
    if base is None:
        return {}
    try:
        raw = json.loads(_rc_cache_file(base).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _rc_cache_save(base, data: dict) -> None:
    if base is None:
        return
    try:
        f = _rc_cache_file(base)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass                         # 快取寫不進去不是錯誤，下次重算就好


def _grep(base: Path, pattern: str, paths: tuple) -> object:
    """跑一次 `grep -rn`，回命中的 (檔案相對路徑, 行號)。

    **用 grep 不自己逐檔讀**，理由跟 `blast.py` 借 `cost.js`、
    `contract.py` 借 `claims._disk()` 同一條：理由裡寫的查法就是 grep，
    自己再寫一次比對規則會變成兩份會分歧的實作，
    而分歧那天下一個人手動跑 grep 得到的答案跟畫面上不一樣。

    跑不起來的時候回 None，**不回空清單** —— 空清單讀起來是
    「查過了，沒有命中」，而實情是「沒查成」。
    """
    have = [str(Path(base) / x) for x in paths if (Path(base) / x).exists()]
    if not have:
        return None
    try:
        excl = [f"--exclude-dir={d}" for d in _RC_SKIP_DIRS]
        r = subprocess.run(["grep", "-rn", *excl, pattern, *have],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode not in (0, 1):   # 2 以上是 grep 自己出錯
        return None
    out = []
    for line in r.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 2:
            continue
        try:
            rel = str(Path(parts[0]).resolve().relative_to(Path(base).resolve()))
        except (ValueError, OSError):
            rel = parts[0]
        out.append({"file": rel, "line": int(parts[1])
                    if parts[1].isdigit() else 0})
    return out


def recheck_all(ctx: dict | None, *, repo: Path | None = None,
                runner: object = None, cache: bool = True) -> list:
    """把 ctx 裡每一條帶 `Recheck` 的理由真的跑一次。

    回的每一筆帶 `stale`：命中數跟當初宣告的 `expect` 對不上就是 True。

    **`stale` 是一個觸發器不是一個結論**（B-05）。命中的位置一起回，
    因為純比對分不出「實作了」與「一句說它沒實作的散文」——
    這個 repo 此刻正好兩種都有。

    查不成的時候 `hits` 是 None 而且 `stale` 是 False：
    一個沒查成的複查不是一個通過的複查，也不是一個失敗的複查。
    """
    ctx = ctx or {}
    r = Path(repo or REPO)
    g = runner or _grep
    cached = _rc_cache_load(r if cache else None)
    fresh, out, dirty = {}, [], False

    for key, v in ctx.items():
        rc = getattr(v, "recheck", None) if isinstance(v, NoSource) else None
        if not isinstance(rc, Recheck):
            continue
        ck = f"{rc.pattern}\x00{','.join(rc.paths)}\x00{','.join(rc.declared_in)}"
        fp = _rc_fingerprint(r, rc.paths) if cache else None
        hit = None
        prev = cached.get(ck)
        if fp is not None and isinstance(prev, dict) and prev.get("fp") == fp:
            hit = prev.get("hits")
            cached_hit = True
        else:
            raw = g(r, rc.pattern, rc.paths)
            cached_hit = False
            if raw is None:
                hit = None
            else:
                # 宣告這條理由的檔案自己一定要排除，見 Recheck 的 docstring。
                hit = [h for h in raw if h["file"] not in rc.declared_in]
            if fp is not None:
                fresh[ck] = {"fp": fp, "hits": hit}
                dirty = True
        if fp is not None and cached_hit:
            fresh[ck] = prev
        files = sorted({h["file"] for h in hit}) if hit is not None else None
        out.append({
            "key": key,
            "pattern": rc.pattern,
            "paths": list(rc.paths),
            "expect": rc.expect,
            "actual": len(files) if files is not None else None,
            "where": [f"{h['file']}:{h['line']}" for h in (hit or [])][:6],
            "files": files,
            "cached": cached_hit,
            "stale": (files is not None and len(files) != rc.expect),
            "why": v.why,
        })

    if cache and dirty:
        merged = dict(cached)
        merged.update(fresh)
        _rc_cache_save(r, merged)
    out.sort(key=lambda x: (not x["stale"], x["key"]))
    return out


def recheck_lines(rows: list, limit: int = 4) -> list:
    """給 `NEXT.md` 用。只在真的有東西要看的時候才出現。"""
    rows = rows or []
    bad = [x for x in rows if x.get("stale")]
    unk = [x for x in rows if x.get("actual") is None]
    if not bad and not unk:
        return []
    lines = []
    if bad:
        lines += [
            f"這幾條「沒有資料來源」的理由，當初附的查法現在對不上了"
            f"（{len(bad)} 條）。",
            "",
            "**這是要去看一眼，不是說那句理由錯了。** 字串比對分不出"
            "「已經實作」與「一句說它沒實作的散文」，判斷留給人。",
            "",
        ]
        for x in bad[:limit]:
            where = "、".join(x["where"][:3]) or "（拿不到位置）"
            lines.append(
                f"- `{x['key']}`：查法 `{x['pattern']}` 當初是 "
                f"{x['expect']} 個檔，現在 {x['actual']} 個 —— {where}")
        if len(bad) > limit:
            lines.append(f"- 還有 {len(bad) - limit} 條沒列出來")
        lines.append("")
    if unk:
        lines.append(
            f"另外 {len(unk)} 條的複查沒跑成，所以那幾條的理由"
            "這一刻既沒有被推翻也沒有被證實。")
        lines.append("")
    return lines


def gaps(groups: list) -> list:
    """只列不是 PRESENT 的，按「離補上有多近」排。

    NOT_CARRIED 排最前面，因為那是今天就補得掉的。
    """
    order = {STATUS_NOT_CARRIED: 0, STATUS_DEGRADED: 1,
             STATUS_EMPTY: 2, STATUS_NO_SOURCE: 3}
    out = []
    for g in groups:
        for f in g["fields"]:
            if f["status"] == STATUS_PRESENT:
                continue
            out.append({"group": g["group"], "key": f["key"],
                        "spec": f["spec"], "status": f["status"],
                        "zh": f["zh"], "why": f["why"],
                        "undeclared": f["undeclared"]})
    out.sort(key=lambda x: (order.get(x["status"], 9), x["group"], x["key"]))
    return out


def summary_lines(report: dict, limit: int = 12) -> list:
    """給 `NEXT.md` 用的幾行。接手的人第一眼要看到的是缺什麼。"""
    t = report.get("totals") or {}
    cov = report.get("coverage")
    lines = [
        f"照 v5.0 §39.1 的最小交接契約，{t.get('total', 0)} 個欄位裡"
        f"帶得出值的有 {t.get('present', 0)} 個"
        + (f"（{cov:.0%}）" if isinstance(cov, float) else "") + "。",
        "",
        f"- 算得出來但這份沒帶：{t.get('not_carried', 0)}",
        f"- 有來源此刻是空的：{t.get('empty', 0)}",
        f"- 有值但不滿足規格要求：{t.get('degraded', 0)}",
        f"- 這個系統沒有資料來源：{t.get('no_source', 0)}"
        + (f"，其中 {t['undeclared']} 個連理由都沒人寫"
           if t.get("undeclared") else ""),
        "",
    ]
    gs = report.get("gaps") or []
    if gs:
        lines.append("缺的是這些，排在前面的是今天就補得掉的：")
        lines.append("")
        for g in gs[:limit]:
            why = f" —— {g['why']}" if g.get("why") else ""
            lines.append(f"- `{g['key']}`（{g['spec']}）{g['zh']}{why}")
        if len(gs) > limit:
            lines.append(f"- 還有 {len(gs) - limit} 個沒列出來")
        lines.append("")
    return lines


# ---------------------------------------------------------------------------
# 從真實狀態組出 ctx
# ---------------------------------------------------------------------------
#
# 下面每一句 NoSource 的理由都是實際查過的，不是推測的。查法寫在理由裡，
# 下一個人可以自己重跑一次去推翻它。**推翻得了才算是證據。**

def git_head(repo: Path | None = None) -> object:
    """HEAD 加上工作區乾不乾淨。

    HEAD 單獨拿出來會說謊：這個 repo 2026-09-16 有一批檔案從來沒有
    `git add` 過，所以 HEAD 指到的程式碼不是現在跑的程式碼。
    那不是「沒有 commit」，是「有一個看起來可信的 commit」，更難查。
    """
    r = Path(repo or REPO)
    def _run(*a):
        return subprocess.run(["git", "-C", str(r), *a], capture_output=True,
                              text=True, timeout=10)
    try:
        h = _run("rev-parse", "HEAD")
        if h.returncode != 0:
            return NoSource("這個目錄不是 git repo，或還沒有任何 commit："
                            + " ".join((h.stderr or "").split())[:80])
        head = h.stdout.strip()[:12]
        st = _run("status", "--porcelain")
        if st.returncode != 0:
            return Degraded(head, "拿得到 HEAD 但 git status 失敗，"
                                  "所以不知道工作區跟它差多少")
        dirty = [x for x in st.stdout.splitlines() if x.strip()]
        if dirty:
            # 2026-09-16 17:5x 更正：先前這句話寫成「N 個檔案沒有進版控」，
            # 而 N 是 porcelain 的總行數，裡面混著兩種完全不同的情形。
            # 實測那一刻的 88 是 26 個已追蹤但有改動、62 個從來沒 git add。
            # 兩種都讓 hash 指不到現在跑的程式碼，但下一步不一樣：
            # 前者 commit 就好，後者要先決定那些檔該不該進版控。
            # 一個把兩者併起來的數字，指不出那個差別。
            untracked = [x for x in dirty if x.startswith("??")]
            return Degraded(
                head,
                f"工作區有 {len(dirty)} 個檔案跟這個 hash 不一致"
                f"（{len(dirty) - len(untracked)} 個已追蹤但有改動、"
                f"{len(untracked)} 個從來沒進版控），"
                f"所以這個 hash 指不到現在跑的程式碼")
        return head
    except (OSError, subprocess.SubprocessError) as e:
        return NoSource(f"跑 git 失敗：{type(e).__name__}")


# XY 兩個字元 → 一句人看得懂的版控狀態。
# **認不出來的碼不猜**，原樣留著 —— 猜一個好聽的狀態會讓交接檔
# 宣稱一件 git 沒有講過的事，那是 §8.3 的填空。
_VCS = {
    "??": "從來沒進版控",
    "!!": "被 gitignore 排除",
}


def _vcs_label(xy: str) -> str:
    if xy in _VCS:
        return _VCS[xy]
    x, y = (xy + "  ")[0], (xy + "  ")[1]
    if "D" in (x, y):
        return "已刪除"
    if x == "R":
        return "改名"
    if x == "C":
        return "複製"
    if x == "A":
        return "新增已暫存"
    if x == "U" or y == "U":
        return "合併衝突"
    if "M" in (x, y):
        return "已追蹤但有改動"
    return f"git 狀態碼 {xy.strip() or '空白'}（這裡不替它翻譯）"


def worktree_paths(repo: Path | None = None) -> dict:
    """工作區裡跟 HEAD 不一致的檔案，逐個帶上版控狀態。

    **這一支回答的不是「這一輪寫了什麼」。** 它回答的是「這個工作區
    有哪些東西跟 HEAD 不一樣」。兩件事在交接上都要，但併成一個清單
    就沒有人分得出哪些是剛做出來的，所以每一筆都帶 `source`，
    而且兩邊的數字在畫面上分開報，不合成一個。

    **用 `-z` 不是為了快，是因為不用 `-z` 會給出不存在的路徑。**
    git 預設把非 ASCII 路徑包成 C 風格跳脫（實測這個 repo 有一筆
    `"\351\226\213..."`），那個字串當成路徑去開會是 missing ——
    一份指向沒有人寫過的檔案的交接，正是這一欄最該避免的東西。

    量不到的時候 `problem` 是那句理由，`entries` 是空的。
    **空清單加沒有 problem，意思是「量過了，工作區乾淨」；
    空清單加有 problem，意思是「沒量到」。** 兩件事在畫面上必須
    分得出來 —— 跟 `live_conflicts` 的 0 與 None 同一條誠實條款。
    """
    r = Path(repo or REPO)
    try:
        res = subprocess.run(["git", "-C", str(r), "status", "--porcelain", "-z"],
                             capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        return {"entries": [], "problem": f"跑 git 失敗：{type(e).__name__}"}
    if res.returncode != 0:
        why = " ".join((res.stderr or b"").decode("utf-8", "replace").split())[:100]
        return {"entries": [], "problem": f"git status 失敗：{why}"}

    fields = res.stdout.split(b"\0")
    entries, i = [], 0
    while i < len(fields):
        f = fields[i]
        i += 1
        if len(f) < 4:
            continue
        xy = f[:2].decode("utf-8", "replace")
        path = f[3:].decode("utf-8", "replace")
        if xy[:1] in ("R", "C"):
            i += 1            # 下一格是來源路徑，不是另一個變更
        entries.append({"path": path, "source": "worktree",
                        "vcs": _vcs_label(xy)})
    return {"entries": entries, "problem": None}


def _by_mtime(entries: list, base: Path) -> list:
    """照修改時間排，新的在前；量不到的排最後。

    量不到的時候用 -inf 不用 0 或此刻：用此刻會讓一個讀不到的檔案
    排到最前面，看起來像剛剛才動過，那是一句這裡證明不了的話。
    """
    def key(e):
        try:
            return -Path(base, e.get("path", "")).stat().st_mtime
        except OSError:
            return float("inf")
    return sorted(entries, key=key)


def _guard_lines(guard: dict | None, n_rows: int) -> list:
    """「其中幾筆有守門」那幾行。`invalidated_lines()` 的一部分，拆出來是為了測得動。

    `guard` 是 `pollution.guard_split()` 的回傳值。給 None 就自己去問；
    問不到（登記簿不存在、模組 import 不起來）**整段不印**，
    不印「守門狀態未知」那種行文 —— 那句話對讀的人沒有作用，
    而且會讓這一節看起來比實際上知道得更多。
    """
    if guard is None:
        try:
            import pollution                # noqa: PLC0415  故意延後，同 _invalidated
            guard = pollution.guard_split()
        except Exception:                   # noqa: BLE001
            return []
    if not isinstance(guard, dict):
        return []
    try:
        g = int(guard["guarded"])
        u = int(guard["unguarded"])
        n_open = int(guard["open"])
    except (KeyError, TypeError, ValueError):
        return []

    ids = [str(x) for x in (guard.get("unguarded_ids") or [])]
    out = []
    if u == 0:
        out.append(f"這 {n_open} 筆**全部**有偵測器或預防規則攔著。")
    else:
        out.append(f"其中 **{g} 筆**有偵測器或預防規則攔著，"
                   f"**{u} 筆現在只靠人記得**。")
        if ids:
            named = "、".join(f"`{i}`" for i in ids[:6])
            more = f"（還有 {len(ids) - 6} 筆沒列）" if len(ids) > 6 else ""
            out.append("")
            out.append(f"只靠人記得的是 {named}{more}。**那幾筆才是風險所在** ——")
            out.append("§40.2 要的是偵測器，不是一次查核。重驗過不等於機制被擋住了。")
    if n_open != n_rows:
        out.append("")
        out.append(f"**這兩個數字對不起來**：上面那一行的 {n_rows} 筆是傳進來的清單，"
                   f"這一行的 {n_open} 筆是現在去讀登記簿算的。")
        out.append("不挑一個印，因為不一致本身就是要給人看的狀態。")
    out.append("")
    return out


def invalidated_lines(ctx: dict | None, limit: int = 6,
                      guard: dict | None = None) -> list:
    """交接檔「已經被推翻的」那一節的行文。算在這裡，`handoff.py` 只排版。

    理由跟 `artifact_lines` 同一條，而這一節的必要性更直接:
    §39.1 把 invalidated_conclusions 放在 Limits 那一組，
    它存在的理由就是「不要讓後繼者再帶著這句錯的話走」。

    一個只從缺口清單上消失、內容卻看不到的欄位，達不到那個目的 ——
    契約覆蓋率會變好看，而後繼者照樣會再犯一次同一個推論。

    空的時候回空清單，那一節整個不印。**不印「目前沒有被推翻的結論」** ——
    這個登記簿只收明確登錄的那幾筆，沒有東西不代表沒有污染，
    只代表沒有人登錄。這句話講出來反而會給一個沒有根據的保證。

    ## `guard` 那一行是 2026-09-18 加的

    先前這一節只印得出「有 N 筆還沒收乾淨」。而那個數字裡，
    **有偵測器攔著的那幾筆跟只靠人記得的那幾筆長得一模一樣** ——
    §40.2 要的是偵測器不是一次查核，所以後面那幾筆才是風險所在，
    而讀這一份的人看不出來是哪幾筆。

    `guard` 不給就自己去問 `pollution.guard_split()`（延後 import，
    理由跟 `_invalidated()` 同一條）。**問不到就整行不印** ——
    拿 `summary()['guarded']` 來湊是不行的，那一支的分母是
    `records()` 全部，而這一節的分母是 open，兩個此刻相等純屬巧合
    （RESOLVED 是 0）。細節寫在 `pollution.guard_split()` 的說明裡。

    兩邊的 open 數字不一致的時候**不挑一個印** ——
    `rows` 是呼叫者傳進來的（可能已經被 `Degraded` 降級過），
    `guard` 是這一支自己讀檔算的。不一致本身是要給人看的狀態，
    不是要被抹平的雜訊。
    """
    ctx = ctx or {}
    raw = ctx.get("invalidated_conclusions")
    if isinstance(raw, Degraded):
        raw = raw.value
    rows = raw if isinstance(raw, list) else []
    if not rows:
        return []

    lines = [
        f"§40 的污染登記簿裡有 **{len(rows)} 筆**還沒收乾淨。",
        "",
        "這幾句話**已經被推翻了**，不要再帶下去。",
        "每一筆存的重點是「當初為什麼會錯」，不是「正確答案是多少」——",
        "數字改掉就沒事了，機制不改掉會再犯一次（§40 開頭那一句）。",
        "",
    ]
    lines += _guard_lines(guard, len(rows))
    for r in rows[:limit]:
        lines.append(f"- {r}")
    if len(rows) > limit:
        lines.append(f"- 還有 {len(rows) - limit} 筆沒列出來")
    lines += [
        "",
        "出處 v5.0 §40 PollutionRegistry，資料在 `.forseti/pollution.jsonl`。",
        "自己查：`python3 -c \"import sys;sys.path.insert(0,'apps/forseti-cli');"
        "import pollution;print(pollution.summary())\"`",
        "",
    ]
    return lines


#: 「這一份是在哪裡寫的」那一節印哪幾欄。**這是白名單，不是「所有 PRESENT」。**
#: 產出、已推翻的結論、阻塞各自有自己那一節，全部 PRESENT 一起印會印兩次，
#: 然後兩個地方開始不一致。
#:
#: 這幾欄的共同點不是「比較重要」，是**其他每一節都要靠它們才解釋得了**:
#: 一條 `apps/forseti-cli/contract.py` 只有在某一台機器的某一個正本底下
#: 才指得到東西，而這份檔案會被另一台機器上的人讀到。
COORDINATE_FIELDS: tuple = (
    "project_id", "canonical_root", "runtime_node",
    "session_id", "logical_agent_id", "model_identity",
)


def coordinate_lines(report: dict | None) -> list:
    """交接檔「這一份是在哪裡寫的」那一節的行文。`handoff.py` 只排版。

    ## 為什麼要有這一節

    先前 `NEXT.md` 的契約那一節**只印缺口，填得出來的欄位一個字都不印**。
    所以 2026-09-17 那一輪把 `runtime_node` 從「沒有資料來源」接成有值
    之後，那份交接檔照樣答不出「這一份是在哪台機器上寫的」——
    值算出來了，讀的人看不到。

    **一個從缺口清單上消失的欄位，跟一份真的說得出座標的交接，
    不是同一件事。** 這句話是 `artifact_lines` 那一節先撞到的
    （2026-09-16 18:2x），這裡是同一個形狀第二次出現，
    所以它是這個檔案的一種慣性，不是一次意外。

    ## 只印 PRESENT，缺的不在這裡

    白名單裡不是 PRESENT 的那幾欄不在這一節出現 —— 它們已經在
    「這份交接照規格少了什麼」那一節裡，連理由一起。結尾那一句
    負責講清楚沒列出來的去哪裡找，不然讀的人會把「沒列」讀成「沒有」。

    ## `basis` 要跟著 node_id 走

    退回 hostname 算出來的 node_id 會在改機器名字的那天變掉，
    而那件事在畫面上跟「換了一台機器」長得一模一樣
    （`runtimenode` 檔頭）。所以 basis 不是硬體識別碼的時候，
    這一節多印一句，**不是把那個 id 藏起來**。

    值本身一律走 `check()` 算好的 `shown`，這一支不自己格式化任何值 ——
    自己格式化就會變成第二個渲染路徑，然後同一個值在兩個地方長得不一樣。
    """
    rep = report or {}
    bykey = {}
    for g in (rep.get("groups") or []):
        for f in (g.get("fields") or []):
            bykey[f.get("key")] = f

    rows = [(k, bykey[k]) for k in COORDINATE_FIELDS
            if bykey.get(k, {}).get("status") == STATUS_PRESENT
            and str(bykey[k].get("shown") or "").strip()]
    if not rows:
        # 一欄都答不出來的時候整節不印。**不印一句「座標不明」** ——
        # 那一行會被讀成系統查過了，實情是這一節沒有東西可講，
        # 而缺了哪幾欄、為什麼缺，缺口那一節講得比這裡準。
        return []

    lines = [
        "接手的人第一眼要確認的是**這一份講的東西跟你在的地方是不是同一個**。",
        "底下每一條路徑、每一個雜湊，都只有在這組座標底下才指得到東西。",
        "",
    ]
    for k, f in rows:
        lines.append(f"- {f.get('note') or k}（`{k}`）：{f.get('shown')}")
    lines.append("")

    ctx = rep.get("ctx") or {}
    rn = ctx.get("runtime_node")
    basis = rn.get("basis") if isinstance(rn, dict) else None
    if basis and basis != _basis_uuid_name():
        lines += [
            f"**`node_id` 這一次是從 {basis} 算出來的，不是硬體識別碼。**",
            "改機器名字的那天它會跟著變，而那在畫面上跟「換了一台機器」",
            "長得一模一樣。要分辨得看這一行，不是看 id 本身。",
            "",
        ]

    listed = {k for k, _ in rows}
    missing = [k for k in COORDINATE_FIELDS if k not in listed]
    if missing:
        lines += [
            "這一節沒列到的座標（"
            + "、".join(f"`{k}`" for k in missing)
            + "）**不是沒有這一欄**，是這一刻答不出來。",
            "為什麼答不出來，在下面「這份交接照規格少了什麼」那一節，連理由一起。",
            "",
        ]
    return lines


def _basis_uuid_name() -> str:
    """硬體識別碼那個 basis 叫什麼。**跟 `runtimenode` 拿，不寫死字面值。**

    寫死的話那邊改一個字，這裡的警告會靜默地永遠不成立 ——
    而少印一句警告不會讓任何測試變紅，所以沒有人會發現。
    拿不到就回空字串，那會讓警告永遠印出來:**多印一句警告是安全的方向**，
    少印那一句才會讓人把換機器誤判成沒換。
    """
    try:
        import runtimenode                   # noqa: PLC0415  故意延後
        return runtimenode.BASIS_UUID
    except Exception:                        # noqa: BLE001
        return ""


def artifact_lines(ctx: dict | None, limit: int = 10) -> list:
    """交接檔那一節的行文。**算在這裡，`handoff.py` 只排版。**

    理由跟 `summary_lines` 同一條：判斷放在排版那一支，就會變成
    第二個事實來源，然後兩個來源開始不一致。

    先前這一欄就算 PRESENT 了，接手的人在 `NEXT.md` 上照樣看不到
    任何一個路徑 —— 缺口清單只印缺的，不印有的。
    **一個從缺口清單上消失的欄位，跟一個真的說得出產出在哪的交接，
    不是同一件事。**
    """
    ctx = ctx or {}
    raw = ctx.get("artifact_paths")
    problem = ctx.get("_artifact_problem")
    if isinstance(raw, Degraded):
        raw = raw.value
    paths = raw if isinstance(raw, list) else []
    hashes = ctx.get("artifact_hashes")
    if isinstance(hashes, Degraded):
        hashes = hashes.value
    hmap = {h.get("path"): h for h in (hashes or []) if isinstance(h, dict)}

    tool = [p for p in paths if p.get("source") == "tool_point"]
    work = [p for p in paths if p.get("source") == "worktree"]
    tracked = [p for p in work if p["vcs"] != "從來沒進版控"]
    untracked = [p for p in work if p["vcs"] == "從來沒進版控"]

    lines = [
        f"工具點（Write / Edit / NotebookEdit）看得到的：**{len(tool)} 個**。",
        "",
    ]
    if problem:
        lines += [f"工作區那半邊**沒量到**：{problem}。",
                  "沒量到不等於工作區是乾淨的，這兩件事在這裡分得出來。", ""]
    else:
        lines += [f"工作區跟 HEAD 不一致的：**{len(work)} 個**"
                  f"（{len(tracked)} 個已追蹤有改動、{len(untracked)} 個從來沒進版控）。",
                  ""]
    lines += [
        "**兩邊回答的不是同一個問題。** 工具點答的是「這一輪寫了什麼」，",
        "工作區答的是「這裡有什麼還沒進版控」。用 Bash 改的檔案工具點看不到，",
        "工作區看得到 —— 所以兩個數字不合成一個。",
        "",
    ]
    if paths:
        for e in paths[:limit]:
            h = hmap.get(e["path"]) or {}
            st = h.get("state")
            mark = (h["hash"][:16] if st == "ok" and h.get("hash")
                    else {"missing": "檔案不在了", "dir": "這是目錄",
                          "unmeasured": "量不到"}.get(st, "沒有雜湊"))
            tag = "這一輪寫的" if e.get("source") == "tool_point" else e.get("vcs", "")
            lines.append(ART_ROW_FMT.format(path=e["path"], tag=tag, mark=mark))
        if len(paths) > limit:
            lines.append(ART_TRUNC_FMT.format(n=len(paths) - limit))
            # 數量那一行講不出是哪幾個,而「另外 16 個不在檢查範圍內」
            # 這句話拿不去查:讀的人不知道自己剛改的檔在不在那 16 個裡。
            # 代價量過了（多一行 493 字元），理由與四種排版的比較
            # 在 `ART_UNLISTED_FMT` 的說明裡。
            lines.append(ART_UNLISTED_FMT.format(
                paths=ART_UNLISTED_SEP.join(
                    ART_UNLISTED_ITEM_FMT.format(path=e["path"])
                    for e in paths[limit:])))
        lines.append("")
        lines.append("工作區那一半照**修改時間**排，新的在前。"
                     "那是「什麼時候被動過」，不是「誰動的」。")
        lines.append("")
    return lines


#: 交接檔那一節的標題。**跟 `handoff.py` 排版用的是同一個字面值**，
#: 而它在那邊是寫死的。兩邊各寫一次就會有一天只改一邊，而那一天
#: 這裡會靜默地掃不到任何一行 —— 零筆讀起來跟「全部對得上」一樣。
#: `test_那個標題兩邊是同一個` 釘住這件事。
ARTIFACT_HEADING = "## 產出在哪裡"

#: `artifact_lines()` 印出來的那一行長這樣:
#:     - `路徑` ── 標記，雜湊前 16 碼
#: 最後一欄不一定是雜湊（「檔案不在了」「這是目錄」「量不到」
#: 「沒有雜湊」都印在同一格），所以這裡**不假設它是**，
#: 判斷留給 `artifact_drift()`。
#:
#: **這是那一行唯一的定義。** 先前排版寫在 `artifact_lines()` 的
#: f-string 裡，讀回來的正則寫在這裡，兩邊各寫一次。2026-09-18
#: 實測過只改排版不改正則會怎樣:`tests/test_artifact_drift.py`
#: 當場 11 條紅，**所以那不是靜默失效**（上一輪的紀錄寫成靜默，
#: 那句話已經登進 §40）。會靜默的是另一半 —— Python 側的改動不經過
#: build 就對桌面版生效，而 `desktop/deploy.sh` 的守門只跑
#: `test_js_symbols.py` 與 `test_ui_contract.py`，這一組不在裡面。
#: 也就是說「有人跑全套測試」是唯一的關卡。單一來源化不是為了多一道
#: 守門，是為了讓那個不一致從「測試會擋」變成**構造上做不出來**。
ART_ROW_FMT = "- `{path}` ── {tag}，{mark}"

#: 每一欄允許長什麼樣。**用具名群組**，因為 `ART_ROW_FMT` 的欄位
#: 順序哪天換了，位置群組的編號會跟著換而讀的那一支不會知道。
#:
#: **這一份跟 `ART_ROW_FMT` 是一對，所以跟它一樣公開。** 第一版寫成
#: 底線開頭，`test_私有常數的曝險此刻是0` 當場紅了 —— 那一條守的是
#: 「成員只活在私有常數裡就沒有對照組」，而這三個鍵正是那種。
#: 它們真正的對照組是 `ART_ROW_FMT` 裡的 `{path}` `{tag}` `{mark}`，
#: 但那個守門掃的是列舉常數的成員，看不進 f-string 的欄位名。
#: 一個講格式、一個講每欄的樣式，沒有理由一個公開一個私有。
ART_FIELD_PAT = {
    "path": r"(?P<path>[^`]+)",
    "tag": r"(?P<tag>[^，]*)",
    "mark": r"(?P<mark>.*)",
}

#: 那一節被截斷的時候多印的那一行。**它是這個檢查的邊界宣告**:
#: `artifact_lines()` 預設只印前 10 個路徑（`desktop_api.py` 傳的就是 10），
#: 而 `artifact_drift()` 只對得到印出去的那幾行。被截掉的那些
#: **永遠不會被追尾抓到**,因為它們從來沒有被記下來過。
#:
#: 2026-09-18 實測:工作區 26 個路徑,交接檔那一節記了 10 筆,
#: 另外 16 個不在檢查範圍內。而 `drift_lines()` 印的是
#: 「10 個雜湊這一刻都對得上（那一節共 10 筆）」——
#: 那句話沒有一個字是假的,可是讀起來像是覆蓋了工作區。
#:
#: 所以這一行要讀得回來,理由跟 `ART_ROW_FMT` 同一條,
#: 而用途不同:那一份是為了對雜湊,這一份是為了**講出對不到哪裡為止**。
ART_TRUNC_FMT = ("- 還有 {n} 個沒列出來，"
                 "`python3 apps/forseti-cli/contract.py` 全部印得出來")

#: 只有一欄,而且它一定是數字。**不用 `.*`** —— 那會讓
#: 「還有 一些 個沒列出來」也匹配得上,然後 `int()` 在別的地方炸。
ART_TRUNC_PAT = {"n": r"(?P<n>\d+)"}

#: 被截掉的那幾個**是哪幾個**。上一行只講得出數量,而
#: 「另外 16 個不在這個檢查裡」這句話沒辦法拿去查 —— 讀的人
#: 不知道自己剛改的那個檔在不在那 16 個裡面,也就沒辦法判斷
#: 「全部對得上」這句話對他有沒有用。
#:
#: **只有路徑,刻意不帶雜湊。** 帶了雜湊就會被 `recorded_artifacts()`
#: 讀成記錄，於是它們變成追尾範圍的一部分 —— 而這一行的用途正好相反:
#: 它是在宣告這些東西**不**在範圍內。名單跟範圍是兩件事。
#:
#: 2026-09-18 實測四種排版的代價（工作區 26 個路徑,`limit=10`,
#: 四份都是真的產出來再數的,不是估的）:
#:
#:     A 現況,只有數量                 22 行　872 字元
#:     B 擠成一行,只有路徑             23 行　1402 字元　← 這一份
#:     C 每行一個,只有路徑             38 行　1380 字元
#:     D 乾脆全部印出來,含雜湊         37 行　1766 字元
#:
#: **C 沒有比 D 省行數**（38 比 37 還多一行,因為 D 的截斷行本身
#: 消失了）,它省的只有字元,而字元也只省 22%。也就是說「留路徑
#: 清單」這件事要划得來,唯一的排版是 B:多一行,換那句邊界宣告
#: 從「拿不去查」變成「查得動」。
#:
#: B 那一行很長（實測 530 字元）,這是刻意付的代價。
#:
#: **這一行自己不截斷。** 一個宣告別人被截斷了的行自己再截斷一次,
#: 就會需要第三行去講它截到哪裡，而那正是這一整節在解的問題。
ART_UNLISTED_FMT = ("- 沒列出來的是這幾個（只有路徑，"
                    "**沒有雜湊，所以它們不在追尾範圍內**）：{paths}")

#: 一整串,裡面每一個路徑各自用反引號包,中間用 `ART_UNLISTED_SEP` 隔開。
#: **不用 `.*`** 而用 `.+`:空字串代表沒有路徑,那種時候整行就不該印。
ART_UNLISTED_PAT = {"paths": r"(?P<paths>.+)"}

#: 分隔符。**單獨一個常數**,因為讀回來那一支要拿它切,
#: 而排版與切割用同一個字面值是這一整組的前提。
ART_UNLISTED_SEP = "、"

#: 那一行裡每一個路徑長什麼樣。**這一份存在是因為守門抓到了它** ——
#: 第一版把反引號直接寫在 `artifact_lines()` 的 f-string 裡,
#: `test_排版跟讀回來用的是同一份格式` 當場紅（它掃的是原始碼裡
#: 有沒有寫死的 `` `{ ``）,而讀回來那一支則自己 `strip("`")`。
#: 兩邊各有一份對反引號的知識,就是 `ART_ROW_FMT` 那一整段講的形狀。
#: 沒有把測試改綠,改的是這裡。
ART_UNLISTED_ITEM_FMT = "`{path}`"
ART_UNLISTED_ITEM_PAT = {"path": r"(?P<path>[^`]+)"}


def _fmt_to_re(fmt: str, pats: dict) -> re.Pattern:
    """把排版格式轉成讀得回來的正則。固定的部分一律 `re.escape`。

    **不接受 `pats` 沒定義的欄位。** 排版多加一欄而這裡忘了給樣式，
    正確的行為是當場 `KeyError`，不是生出一個少一欄照樣匹配得上的
    正則 —— 那會讓多出來的那一欄靜默地被併進隔壁欄。
    """
    out, i = [], 0
    for m in re.finditer(r"\{(\w+)\}", fmt):
        out.append(re.escape(fmt[i:m.start()]))
        out.append(pats[m.group(1)])
        i = m.end()
    out.append(re.escape(fmt[i:]))
    return re.compile("^" + "".join(out) + "$")


_ART_ROW = _fmt_to_re(ART_ROW_FMT, ART_FIELD_PAT)
_ART_TRUNC = _fmt_to_re(ART_TRUNC_FMT, ART_TRUNC_PAT)
_ART_UNLISTED = _fmt_to_re(ART_UNLISTED_FMT, ART_UNLISTED_PAT)
_ART_UNLISTED_ITEM = _fmt_to_re(ART_UNLISTED_ITEM_FMT, ART_UNLISTED_ITEM_PAT)

_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def _section(text: str, heading: str) -> list[str]:
    """切出某一節的內容。下一個 `## ` 就停。

    **先切範圍再比對，不是整份檔案 grep。** 別的節裡也有反引號包路徑
    的行，靠「只有這一節有 ──」去分等於依賴別節的排版永遠不變，
    而那是一個沒有人在守的假設。
    """
    lines = (text or "").splitlines()
    try:
        i = lines.index(heading)
    except ValueError:
        return []
    out = []
    for ln in lines[i + 1:]:
        if ln.startswith("## "):
            break
        out.append(ln)
    return out


def recorded_artifacts(text: str) -> list[dict]:
    """把已經寫出去的交接檔裡「產出在哪裡」那幾行讀回來。

    **讀的是交出去的那份文字，不是重算一次狀態。** 這是刻意的:
    這一支要答的是「接手的人看到的那幾行，現在還對不對得上」。
    重算一次只會答「現在是什麼」，而那題 `artifact_hashes()` 早就答過了，
    再答一次不會發現任何不一致。
    """
    rows = []
    for ln in _section(text, ARTIFACT_HEADING):
        m = _ART_ROW.match(ln)
        if not m:
            continue
        path = m.group("path")
        tag, mark = m.group("tag").strip(), m.group("mark").strip()
        rows.append({"path": path, "tag": tag, "mark": mark,
                     "hash": mark if _HEX16.match(mark) else None})
    return rows


def recorded_truncation(text: str) -> int | None:
    """那一節自己宣告「還有幾個沒列出來」。

    **`None` 跟 `0` 是兩件事。** `0` 是那一節有路徑行而沒有截斷行,
    也就是當初沒有被截斷,所以檢查範圍等於工作區。`None` 是連一行
    路徑都讀不回來 —— 那一節可能是空的,也可能是排版改了讀不到,
    這裡分不出來,所以不准回 `0` 冒充「沒有被截斷」。

    這一支跟 `recorded_artifacts()` 讀的是同一節,拆成兩支是因為
    兩題不一樣:那邊問「記了哪幾個」,這邊問「沒記的有幾個」。
    """
    body = _section(text, ARTIFACT_HEADING)
    seen_row = False
    for ln in body:
        m = _ART_TRUNC.match(ln)
        if m:
            return int(m.group("n"))
        if _ART_ROW.match(ln):
            seen_row = True
    return 0 if seen_row else None


def recorded_unlisted(text: str) -> list[str] | None:
    """那一節被截掉的**是哪幾個**。三態,跟 `recorded_truncation()` 不同構。

    `[]`   那一節沒有被截斷（有路徑行、沒有截斷行）。沒有名單要讀,
           而這不是缺陷。
    `list` 讀回來的路徑,順序照印出去那一行。
    `None` **答不出來**,兩種情況:一行路徑都讀不回來（跟
           `recorded_truncation()` 的 `None` 同一種）,或者有截斷行
           卻沒有名單行 —— 後者是舊格式的交接檔,它宣告了數量而
           沒有留下路徑。

    **`[]` 跟 `None` 在 `if not` 底下長得一樣,所以呼叫端一律用
    `is None` 判斷。** 這一支回的兩種空值分別是「不需要」跟「答不出來」,
    合成一個就會讓一份舊格式的交接檔讀起來像是沒有被截斷過。
    """
    body = _section(text, ARTIFACT_HEADING)
    seen_row = trunc = False
    for ln in body:
        m = _ART_UNLISTED.match(ln)
        if m:
            # 每一項也走同一份格式。**不 `strip("`")`** —— 那是第二份
            # 對反引號的知識,而且它會把一個根本沒被包起來的字串
            # 照樣收下來,於是排版壞掉那天這裡讀得回東西。
            got = []
            for x in m.group("paths").split(ART_UNLISTED_SEP):
                mi = _ART_UNLISTED_ITEM.match(x.strip())
                if mi:
                    got.append(mi.group("path"))
            return got
        if _ART_TRUNC.match(ln):
            trunc = True
        if _ART_ROW.match(ln):
            seen_row = True
    if trunc:
        return None
    return [] if seen_row else None


def _changed_after(base, rel: str, at: float | None) -> bool | None:
    """那個檔案是不是在交接檔寫出去之後才被動的。

    **拿不到就回 None 不回 False。** False 讀起來是「沒有在那之後被動過」，
    而那正是下面要標成可疑的那一類。拿一個量不到的東西去指控一筆記錄，
    是這個專案 §8.3 點名的填空。
    """
    if at is None:
        return None
    f = Path(rel)
    if not f.is_absolute() and base is not None:
        f = Path(base) / rel
    try:
        return f.stat().st_mtime > at
    except OSError:
        return None


def artifact_drift(text: str | None = None, cwd=None, out=None, disk=None) -> dict:
    """交接檔記下的那幾個雜湊，現在還對不對得上。

    ## 為什麼有這一支

    2026-09-18 自動接續那一輪撞到的，原話在 `AUTO_CONTINUE_LOG.md`:

        收尾的順序是「重產 `NEXT.md` → 寫這一節」，而 `NEXT.md` 的
        「產出在哪裡」那一節裡有這個檔的 hash。**所以寫完這一節，
        `NEXT.md` 當場就過期了。**

    那一輪的處置是多重產一次，而它自己的結尾寫著「現在靠人記得，
    **沒有東西擋**」。這一支就是那個東西。

    ## 對不上是一個觸發器，不是一個結論

    B-05 擋住的是「單靠文字比對直接產生 finding」。這裡同一條:
    雜湊對不上只代表那個檔案在交接寫出去之後被動過，而那在一個
    還在動的工作區裡是正常狀態。所以每一筆一起回 `changed_after`。

    **`True` 跟 `False` 是兩種東西，不准併成一個數字。**
    `True` 是交接寫完之後才改的，那是追尾，重產一次就對了。
    `False` 是檔案沒被動過而雜湊對不上 —— 那句記錄在寫下的當下
    就不成立，那才是這一支真正要抓的。`None` 是量不到，
    它既不是前者也不是後者。

    ## 它看不到什麼（是前提不是補充）

    交接檔寫出去之後被改過又改回來的檔案，這一支看不到 ——
    它比的是內容不是歷史。這跟 `conftest.py` 掃目錄那一支看不到
    「先建檔再刪掉」是同一個形狀:量結果的東西看不到過程。
    """
    p = Path(out) if out else None
    if p is None:
        try:
            import handoff                # noqa: PLC0415  故意延後，同 _claims_disk
            p = Path(handoff.OUT)
        except Exception:                 # noqa: BLE001
            p = None
    empty = {"source": str(p) if p else None, "at": None, "checked": 0,
             "matched": [], "stale": [], "gone": [], "unmeasured": [],
             "skipped": [], "uncovered": None, "uncovered_paths": None,
             "problem": None}
    if text is None:
        if p is None:
            return {**empty, "problem": "問不到交接檔在哪裡（`handoff.OUT` 拿不到）"}
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            return {**empty, "problem": f"交接檔讀不到:{type(e).__name__}: {e}"}
    at = None
    if p is not None:
        try:
            at = p.stat().st_mtime
        except OSError:
            at = None
    rows = recorded_artifacts(text)
    # 那一節自己宣告沒列出來的有幾個。**這一欄不是用來對雜湊的**,
    # 它講的是這一支對不到哪裡為止,見 `ART_TRUNC_FMT` 的說明。
    uncovered = recorded_truncation(text)
    # 是哪幾個。**跟上面那一欄分開讀**,因為一份舊格式的交接檔
    # 答得出數量而答不出名單,那兩件事要分得出來（見 `recorded_unlisted()`）。
    uncovered_paths = recorded_unlisted(text)
    base = Path(cwd) if cwd else REPO
    live = artifact_hashes([{"path": r["path"]} for r in rows], cwd=base, disk=disk)
    lmap = {h.get("path"): h for h in live if isinstance(h, dict)}

    matched, stale, gone, unmeasured, skipped = [], [], [], [], []
    for r in rows:
        if r["hash"] is None:
            # 當初就沒記到雜湊（目錄、量不到、檔案不在了）。
            # **這不算對得上也不算對不上** —— 沒有東西可以比。
            skipped.append({"path": r["path"], "mark": r["mark"]})
            continue
        h = lmap.get(r["path"]) or {}
        st = h.get("state")
        if st == "missing":
            gone.append({"path": r["path"], "was": r["hash"]})
        elif st == "ok" and h.get("hash"):
            now = h["hash"][:16]
            if now == r["hash"]:
                matched.append(r["path"])
            else:
                stale.append({"path": r["path"], "was": r["hash"], "now": now,
                              "changed_after": _changed_after(base, r["path"], at)})
        else:
            unmeasured.append({"path": r["path"], "state": st})
    return {"source": str(p) if p else None, "at": at,
            "checked": len(rows), "matched": matched, "stale": stale,
            "gone": gone, "unmeasured": unmeasured, "skipped": skipped,
            "uncovered": uncovered, "uncovered_paths": uncovered_paths,
            "problem": None}


def _uncovered_line(d: dict) -> list[str]:
    """這一支管到哪裡為止。**跟對不對得上是兩題。**

    `drift_lines()` 印的「N 個雜湊這一刻都對得上（那一節共 N 筆）」
    沒有一個字是假的,可是它讀起來像是覆蓋了工作區。
    `artifact_lines()` 預設只印前 10 個路徑,被截掉的那些
    從來沒有被記下來,所以**永遠不會被任何一次追尾抓到** ——
    不是對得上,是根本不在範圍內,而這兩件事在原本的行文裡長得一樣。

    走到這裡的時候 `uncovered` 一定是數字:`None` 只在
    「一行路徑都讀不回來」的時候出現,而那條路徑在上面
    `if not d.get("checked")` 就提早回了。
    `test_讀不回來那一種在這裡到不了` 釘住這個推論 ——
    哪天那個提早回被拿掉,這裡就要自己處理 `None`。
    """
    u = d.get("uncovered")
    if u is None:
        return ["    那一節有沒有被截斷**讀不回來**,所以管到哪裡為止答不出來。"]
    if not u:
        return []
    out = [f"    **另外 {u} 個工作區的檔案不在這個檢查裡。**",
           "    它們沒有被寫進那一節,所以不是對得上,是從來沒有被記下來過。"]
    # 是哪幾個。數量答不出「我剛改的那個檔在不在裡面」,而那正是
    # 讀這一行的人唯一想知道的事。**`[]` 跟 `None` 在這裡是兩種話**,
    # 所以用 `is None` 分,不用 `if not`。
    names = d.get("uncovered_paths")
    if names is None:
        out.append("    是哪幾個**讀不回來** —— 那一節只宣告了數量,"
                   "沒有留下路徑（舊格式的交接檔）。")
        return out
    # 數量跟名單各自讀回來,所以它們對不上是量得到的。對不上不去
    # 挑一邊當真 —— 兩個都印,讓讀的人知道那一節自己在打架。
    if len(names) != u:
        out.append(f"    **那一節自己打架**:數量寫 {u},名單只有 "
                   f"{len(names)} 個。名單照印,不替它挑一邊。")
    out.append("      " + ART_UNLISTED_SEP.join(names))
    return out


#: `drift_lines()` 每一類最多列幾筆。**它跟 `artifact_lines()` 的
#: `limit` 是兩個不同的截斷**:那一個決定「哪幾個檔進得了追尾範圍」,
#: 這一個只決定「對不上的那些印幾筆出來」。
#:
#: 2026-09-18 查過:這個上限**從來沒有被觸發過**（那一輪四類最多 2 筆）。
#: 沒被觸發過的截斷仍然要宣告 —— 一個安靜少印的分支,等到真的踩到
#: 那一天,讀的人看到的是一份看起來完整的清單。
DRIFT_ROW_LIMIT = 6


def _drift_rows(items: list, fmt) -> list[str]:
    """一類對不上的明細。**截到上限就講出還有幾筆。**

    這是這一輪那一整節（`ART_UNLISTED_FMT`）的同一個形狀:
    截斷本身不是問題,不宣告才是。四類共用這一支,所以
    「哪天多一類而忘了宣告」這條路走不出來。
    """
    out = [fmt(x) for x in items[:DRIFT_ROW_LIMIT]]
    if len(items) > DRIFT_ROW_LIMIT:
        out.append(f"      · 還有 {len(items) - DRIFT_ROW_LIMIT} 筆沒列出來")
    return out


def drift_lines(d: dict | None) -> list[str]:
    """把 `artifact_drift()` 的結果寫成給人看的行。

    **全部對得上的時候照樣印一行。** 這跟 `recheck_lines()` 的做法相反，
    理由不一樣:那邊不印「0 條過期」是因為那一行斷言的是缺席，
    而缺席沒有人量得到。這裡印的是「N 筆量過了，這一刻都對得上」，
    那是一個量出來的正面事實，而且它必須印 ——
    這一支存在的理由就是取代「靠人記得」，
    一個乾淨時什麼都不印的檢查，分不出「乾淨」跟「根本沒跑」。

    印的那一行一定連著講它管到哪裡為止。少了那半句，
    它就會被讀成「這幾個檔沒問題」，而它只說「這一刻內容沒變」。
    """
    if not d:
        return []
    if d.get("problem"):
        return [f"  交接檔的產出雜湊**沒對到**:{d['problem']}",
                "    對不到不等於對得上,這兩件事在這裡分得出來。"]
    if not d.get("checked"):
        return ["  交接檔的「產出在哪裡」那一節**一行雜湊都沒有**,所以沒有東西可以對。"]
    out = []
    stale = d.get("stale") or []
    after = [x for x in stale if x.get("changed_after") is True]
    before = [x for x in stale if x.get("changed_after") is False]
    unknown = [x for x in stale if x.get("changed_after") is None]
    gone = d.get("gone") or []
    n = d["checked"]
    if not (stale or gone):
        out.append(f"  交接檔記的 {len(d['matched'])} 個雜湊這一刻都對得上"
                   f"（那一節共 {n} 筆）。")
        out.append("    **這只說這一刻的內容一樣**,不說中間沒有被改過又改回來。")
        return out + _uncovered_line(d)
    out.append(f"  交接檔記的雜湊有 {len(stale) + len(gone)} 筆對不上（那一節共 {n} 筆）。")
    if after:
        out.append(f"    交接寫完之後才被改的　{len(after)} 筆　"
                   "這是追尾,重產一次交接檔就對了")
        out += _drift_rows(
            after, lambda x: f"      · {x['path']}　{x['was']} → {x['now']}")
    if before:
        out.append(f"    **檔案沒被動過,雜湊卻對不上　{len(before)} 筆**　"
                   "那句記錄在寫下的當下就不成立")
        out += _drift_rows(
            before, lambda x: f"      · {x['path']}　{x['was']} → {x['now']}")
    if unknown:
        out.append(f"    對不上但量不到它什麼時候被動的　{len(unknown)} 筆　"
                   "**不歸進上面任何一類**")
        out += _drift_rows(
            unknown, lambda x: f"      · {x['path']}　{x['was']} → {x['now']}")
    if gone:
        out.append(f"    交接指到的檔案不在了　{len(gone)} 筆")
        out += _drift_rows(gone, lambda x: f"      · {x['path']}")
    return out + _uncovered_line(d)


def model_from_transcript(path: str | Path | None, tail: int = 400) -> dict:
    """從 jsonl 讀模型身份與 effort。只讀最後幾行，那份檔案很大。

    回 `{"model": ..., "effort": ...}`，讀不到的那一項不放進去。
    """
    out: dict = {}
    if not path:
        return out
    p = Path(path)
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in reversed(lines[-tail:]):
        try:
            r = json.loads(line)
        except (ValueError, TypeError):
            continue
        m = r.get("message")
        if isinstance(m, dict) and m.get("model") and "model" not in out:
            out["model"] = m["model"]
        for k in ("effort", "perTurnEffort"):
            if r.get(k) and "effort" not in out:
                out["effort"] = r[k]
        if "model" in out and "effort" in out:
            break
    return out


def collect(snap: dict | None, work: dict | None = None, *,
            repo: Path | None = None,
            git: object = _MISSING,
            model: dict | None = None,
            disk: object = None,
            identity_reg: object = None,
            worktree: object = _MISSING) -> dict:
    """把此刻的狀態組成 §39.1 的 ctx。

    `git`、`model`、`disk` 可以注入，測試不必真的去跑 git、讀 jsonl，
    也不必有 `claims` 這支模組在旁邊。
    """
    snap = snap or {}
    work = work or {}
    r = Path(repo or REPO)
    rows = snap.get("rows") or []
    ns = snap.get("north_star") or {}

    cmds = []
    for row in rows[-6:]:
        for d in (row.get("dots") or []):
            if d.get("label") == "Bash" and d.get("detail"):
                cmds.append(d["detail"][:120])
    # **這一欄有兩個來源，而且刻意不合成一個。**
    #
    # 一，transcript 的工具點，只認得 Write / Edit / NotebookEdit。
    #     用 Bash（heredoc、sed、python 腳本）改出來的檔案這裡一個都
    #     看不到 —— 2026-09-16 17:5x 那一輪全程用 Bash 改檔，寫了五個
    #     檔案而這一欄是空的，空在畫面上讀起來像「這一輪沒有產出」。
    #
    # 二，2026-09-16 18:2x 接上工作區。`git status` 說得出哪些檔案跟
    #     HEAD 不一樣，**那是量出來的，不是從 Bash 指令裡猜出來的**。
    #     仍然不去猜指令字串裡哪一段是產出路徑：那是 §8.3 的填空，
    #     而猜錯的代價是交接檔指向一個沒有人寫過的檔案。
    #
    # 兩邊回答的不是同一個問題（這一輪寫了什麼 vs 這裡有什麼還沒進版控），
    # 所以每一筆帶 `source`，數字在畫面上分開報。
    paths, seen = [], set()
    for row in rows[-6:]:
        for d in (row.get("dots") or []):
            if d.get("label") in ("Write", "Edit", "NotebookEdit") and d.get("detail"):
                if d["detail"] not in seen:
                    seen.add(d["detail"])
                    paths.append({"path": d["detail"], "source": "tool_point",
                                  "vcs": ""})

    wt = worktree_paths(r) if worktree is _MISSING else (worktree or {})
    wt_problem = wt.get("problem")
    # **照修改時間排，新的在前。** git 給的是路徑字典序，於是清單前十筆
    # 永遠是 `.forseti/` 那幾個每四分鐘被自動重寫的檔，而剛做出來的東西
    # 排在看不到的地方 —— 一份交接的前十行應該是剛動過的那些。
    #
    # mtime 是量出來的不是猜的，但它回答的仍然是「這個檔案什麼時候被動過」，
    # 不是「這一輪動的」。所以只拿來排序，不拿來宣稱來源，
    # 來源照樣是 `source` 那一欄。量不到 mtime 的排最後，不假裝它很新。
    for e in _by_mtime(wt.get("entries") or [], r):
        if e["path"] in seen:
            continue                 # 工具點那一筆更精確，它知道是這一輪寫的
        seen.add(e["path"])
        paths.append(e)

    # §39.1 Next 的第二欄。條件寫在任務上，不是寫在人的記憶裡。
    # 沒有條件的任務不補一句預設值 —— 一個編出來的停止條件
    # 比沒有停止條件危險，因為它看起來像有人想過。
    stops = []
    for t in (work.get("tasks") or []):
        sc = [str(x).strip() for x in (t.get("stop_conditions") or []) if str(x).strip()]
        if sc:
            stops.append(f"{t.get('id', '')}　" + "；".join(sc))

    if git is _MISSING:
        git = git_head(r)
    mi = model if model is not None else model_from_transcript(snap.get("path"))

    blockers_file = r / ".forseti" / "BLOCKERS.md"

    return {
        # -- Identity
        "project_id": r.name,
        "objective": (ns.get("text") or ns.get("objective") or ""),
        "owner": NoSource(
            "`owner.py` 判斷的是「這句話是不是 owner 講的」，"
            "不是「owner 是誰」。`grep -rn 'owner_id\\|owner_name' apps/ src/` 零命中",
            recheck=Recheck("owner_id\\|owner_name")),
        # 這一欄問的是「這份交接是什麼時候寫的」，答案就是此刻。
        # 拿 snap 裡不存在的欄位去問，只會得到一個假的空白。
        "timestamp": snap.get("at") or time.time(),
        "logical_agent_id": _logical_agent_id(r, snap, reg=identity_reg),
        "session_id": snap.get("session") or "",
        # -- Reality
        "canonical_root": str(r),
        "runtime_node": _runtime_node(),
        "target_environment": NoSource(
            "沒有任何地方記錄目標環境。`runtimenode.py`（2026-09-17）"
            "答的是「現在跑在哪」，不是「要落到哪裡」——**兩件事**。"
            "§12.1 那一層現在有 RuntimeNode 這一端，"
            "Project → RuntimeNode 的綁定仍然沒有，"
            "所以「這份工作要落到哪裡」無處可讀"),
        # -- Model
        "model_identity": mi.get("model", ""),
        "model_config": (
            Degraded(mi["effort"],
                     "jsonl 只有 effort，沒有 temperature / top_p / "
                     "system prompt 版本這些真正決定輸出的設定")
            if mi.get("effort") else NoSource(
                "jsonl 裡沒有取樣設定，提供端沒有給")),
        "model_revision": NoSource(
            "jsonl 的 `version` 是 CLI 版本不是模型版本。"
            "模型權重的 revision/hash 提供端沒有給"),
        # -- Data
        "dataset_manifest": NoSource(
            "這個專案不是訓練任務，沒有 dataset manifest 這個物件"),
        "source_classes": NoSource("同上，沒有 dataset 就沒有來源類別"),
        "leakage_result": NoSource("同上，沒有切分就沒有洩漏檢定"),
        # -- Execution
        "commands_run": cmds,
        "code_commit": git,
        "process_status": NoSource(
            "`watchdog.py` 算的是 heartbeat 的停滯評估，不是程序清單。"
            "§12.2 要的「程序管理器加健康端點」這條線沒有接"),
        # -- Metrics
        # 2026-09-17 接上。先前是 NO_SOURCE，理由寫著「Metric Provenance
        # Contract 沒有實作（grep 零命中）」，而 `metrics.py` 之後
        # 那句話不再是真的 —— 又一次「當初查過、後來才變假」的理由，
        # 所以不留著等 `Recheck` 來複查，直接接上來源。
        "metrics_by_distribution": _metrics_field(),
        # -- Artifacts
        # git 量不到的時候這一欄是 DEGRADED，不是 EMPTY。
        # EMPTY 讀起來是「量過了，沒有產出」，而這裡的實情是
        # 「有一半沒量到」，兩件事不一樣。
        "artifact_paths": (Degraded(paths, f"工作區那半邊沒量到：{wt_problem}，"
                                           "所以這份清單只有工具點看得到的那些")
                           if wt_problem else paths),
        # 2026-09-16 17:5x 接上。先前是 NOT_CARRIED，理由寫著
        # 「`claims._disk()` 已經會算，只是沒有人對產出清單跑它」。
        # 現在跑了。空清單的時候這一欄是 EMPTY，那是對的狀態。
        "artifact_hashes": artifact_hashes(paths, cwd=r, disk=disk, cache=r),
        # 不在 §39.1 的 31 欄裡，所以 `check()` 不會碰它。
        # 它存在的理由是 `artifact_lines()` 要說得出「沒量到」跟「乾淨」
        # 的差別，而那個差別在 paths 本身看不出來（兩種都是空清單）。
        "_artifact_problem": wt_problem,
        # -- Limits
        # 2026-09-16 23:3x 接上理由。空的時候這一欄先前是一個沒有理由的
        # 空清單，而它的空值會跟 `NEXT.md` 上那一節打架（那裡列著好幾條
        # 擋住的）。兩邊回答的不是同一個問題，理由裡講清楚。
        "blockers": _blockers_field(work),
        "known_limits": (str(blockers_file) if blockers_file.exists()
                         else NoSource("`.forseti/BLOCKERS.md` 不存在")),
        # 2026-09-17 22:xx 接上。先前是 NO_SOURCE，理由寫著「只寫在
        # AUTO_CONTINUE_LOG 的敘述裡，那是散文不是可查詢的狀態」。
        # 現在 `attempts.py` 在了，所以那個理由不再為真 ——
        # 空的時候是 EMPTY（有地方登記，此刻沒人登記），不是 NO_SOURCE。
        "failed_attempts": _failed_attempts_field(),
        # 2026-09-16 19:2x 接上。先前是 NOT_CARRIED，理由寫著
        # 「§40 的 PollutionRegistry 沒有實作」。現在 `pollution.py` 在了。
        # 空清單的時候這一欄是 EMPTY 不是 NO_SOURCE ——
        # 來源存在而且此刻沒有未解決的污染，那是對的狀態。
        "invalidated_conclusions": _invalidated(r),
        # -- Next
        # 2026-09-16 23:3x 接上理由。**照 `stuck.py` 的 kind 分開講**，
        # 不把所有「沒有下一步」說成同一件事 —— `handoff.py` 付過那個代價。
        "next_step": _next_step(work),
        # 2026-09-16 17:5x 接上。`ledger.obligations()` 先前 SELECT 的
        # 第四欄是 `next_required_action`，而同一支函式的註解寫著它
        # 刻意不讀那一欄（next 動態算）。所以那個位置一直在撈一個
        # 撈回來就被丟掉的值，改撈 `stop_conditions`。
        "stop_condition": stops,
        # -- Claims
        "claims_allowed": NoSource(
            "§39.1 的 Claims 要一個「允許對外講什麼」的政策物件，"
            "這個系統沒有。`claims.py` 判的是單一宣稱有沒有證據，是另一件事"),
        "claims_prohibited": NoSource("同上，沒有政策物件就沒有禁止清單"),
        # -- Recovery
        # 2026-09-16 23:3x 接上理由。`last_good_pointer` 那句話是
        # **借 `checkpoint.summary()` 的 `why_no_last_good`**，不在這裡
        # 再寫一次：複製一份的話，哪天那邊改了政策兩句話會不一樣，
        # 而且沒有人會發現。
        "recovery_status": _recovery_status(snap),
        "last_good_pointer": _last_good_pointer(snap),
    }


def report(snap: dict | None = None, work: dict | None = None, **kw) -> dict:
    """collect 加 check。給呼叫端一支就好。

    `ctx` 一起帶回去。`check()` 只看 §39.1 的 31 欄，而畫面那一節
    要印的是欄位裡面的東西（哪些路徑、雜湊是什麼），
    重跑一次 `collect()` 就會變成第二個事實來源。
    """
    r = kw.get("repo")
    ctx = collect(snap, work, **kw)
    out = check(ctx)
    out["ctx"] = ctx
    # **複查那些理由。** 每一次都跑，因為它要抓的正是「當初查過、
    # 後來變了」，而只在某些時候跑就等於讓腐爛有地方躲。
    # 磁碟快取讓它在沒人改檔的時候幾乎不花時間（指紋失效，見 5a）。
    out["recheck"] = _safe_recheck(ctx, r)
    out["recheck_stale"] = sum(1 for x in out["recheck"] if x.get("stale"))
    return out


def _safe_recheck(ctx, repo) -> list:
    """複查跑不起來不准把整份報告拖垮。

    這一節是附加的診斷，而 §39.1 那 31 欄是主體。
    一個因為複查出錯而整份消失的交接檔，比一份沒有複查的交接檔糟。
    """
    try:
        return recheck_all(ctx, repo=repo)
    except Exception:              # noqa: BLE001
        return []


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import desktop_api as D
        rep = report(D.strands(), D.work())
    except Exception as e:  # noqa: BLE001
        print(f"讀不到當下狀態（{type(e).__name__}），改用空的 ctx 示範結構")
        rep = check({})
    print("\n".join(summary_lines(rep, limit=40)))
    # 複查那一節。沒有東西要看的時候 `recheck_lines()` 回空清單，
    # 所以這裡不會印出一個「0 條過期」的空殼 —— 那種行會被讀成
    # 「有人在守」，而它其實只代表這一刻沒有觸發。
    _rl = recheck_lines(rep.get("recheck"), limit=10 ** 6)
    if _rl:
        print("\n".join(_rl))
    # 交接檔那一節寫著「這一支全部印得出來」。**先前那句是假的**：
    # 這裡只印缺口清單，一個路徑都不印。一句叫人去跑而跑了沒有東西的
    # 指示，比不寫更糟 —— 它讓人以為自己查過了。
    print("\n".join(artifact_lines(rep.get("ctx"), limit=10 ** 6)))
    # 上面那一節是「這一刻工作區是什麼」。這一節問的是另一題:
    # **已經交出去的那份 `NEXT.md` 上面寫的那幾行,現在還對不對得上。**
    # 兩題的差就是交接檔過期沒有,而那件事先前只有人記得。
    _dl = drift_lines(artifact_drift())
    if _dl:
        print()
        print("\n".join(_dl))
