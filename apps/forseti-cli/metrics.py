#!/usr/bin/env python3
"""Metric Provenance Contract。v5.0 §33.1

規格原文（`docs/sources/..._v5.0_2026-09-04.md:844` 起）給了一個
25 欄的 `MetricRecord`，最後附一句對畫面的硬要求：

    Forseti UI and reports must not display an unqualified percentage
    as a release claim. At minimum the user must be able to inspect the
    metric's 'ruler, material, layer, denominator' plus environment and
    lineage.

## 這一支要回答的窄問題

    「這個系統報出去的某一個數字，說得出它的尺、材料、層、分母、
     環境與血緣嗎？說不出來的是哪幾樣？」

不是「幫我做一個指標系統」。這個專案每天在報數字（`NEXT.md` 印
42%、ROADMAP 印 1684 綠），而 `contract.py` 的 `metrics_by_distribution`
那一欄到 2026-09-17 為止寫著「Metric Provenance Contract 沒有實作，
有數字不等於有出處契約」。那句話是對的，這一支補的就是它。

## 缺席分兩種，而且兩種都要附理由

規格 25 欄裡有好幾欄在這個專案結構上不存在（沒有 dataset 就沒有
`dataset_manifest_hash`），也有好幾欄是概念在、此刻取不到（jsonl
沒有給 `seed`）。**這兩種不能塞成同一個 None。**

| 缺席 | 意思 | 下一步不一樣在哪 |
|---|---|---|
| `NOT_APPLICABLE` | 這個專案結構上沒有這個東西 | 沒有下一步，它本來就不該有 |
| `UNKNOWN` | 概念適用，此刻取不到 | 有下一步：去要提供端給 |

這跟 `contract.py` 分 NO_SOURCE 與 EMPTY 是同一條原則：一個說得出
理由的缺席指得出下一步，一個 None 指不出任何東西。

**沒有第三種「先放著」。** 一個欄位沒給、也沒宣告缺席，`build()`
直接拒絕。理由跟 `contract.py` 那句一樣：一個沒有人說明為什麼不見
的欄位，比一個說得出理由的缺席更糟。

## 為什麼不自動登記任何東西

這一支**不掃描、不推斷、不自己產生記錄**。要有一筆記錄，得有人
明確登記，把尺與材料寫下來。

自動登記的話唯一辦得到的方式是拿現成的數字（測試通過數之類）
配上一組猜出來的欄位，而那正是 §8.3 禁止的填空：一筆欄位齊全、
材料類別是編的記錄，在畫面上跟一筆真的記錄長得一模一樣，
而後者才是這個契約存在的理由。

實例就在眼前：這個專案最常報的數字是「全套 1684 綠」，而它照
§33.1 **登記不了**。`material_class` 規格只收六種，pytest 那一套
混著人工構造的輸入與拿真實 jsonl 跑的案例，硬歸成其中一種就是編。
要登記得先照分佈拆開，而拆開要靠人去讀每一條測試用的是什麼材料
—— 那是語意判斷，B-05 擋住自動做。**所以它現在登記不了，
這是正確的結果，不是這一支的缺陷。**

## 合格與否是算出來的，不是宣告的

`qualification()` 把規格最後那句話變成六項檢查（尺、材料、層、
分母、環境、血緣）。任何一項缺，`releasable` 就是 False。

在這個專案裡幾乎每一筆都會是 False，因為 `model_hash`、`config_hash`、
`seed`、`target_environment` 全部 UNKNOWN。**那是量出來的實情，
不是門檻訂太嚴。** 把門檻放寬到讓它們通過，等於回到「有數字就敢報」
的狀態，而這個契約整個存在的理由就是那件事害過人。

零依賴（ADR-009）。專案內借兩支，都是**函式內延後 import 加可注入**：
`contract.git_head` 與 `contract.model_from_transcript`。自己再寫一次
會變成兩份會分歧的實作 —— 同 `contract.py` 借 `claims._disk()` 那一條。
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
import time
from pathlib import Path

VERSION = "metrics@1.0"

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "metrics.jsonl"

# ---------------------------------------------------------------------------
# §33.1 那 25 欄，逐字，順序照規格
# ---------------------------------------------------------------------------
#
# 名字一個字都不改。中文是說明不是翻譯權威，對不上以英文為準。

FIELDS: tuple = (
    ("metric_id", "這一筆的 id"),
    ("metric_name", "這個數字叫什麼"),
    ("semantic_definition", "什麼才算成功（尺）"),
    ("numerator", "分子"),
    ("denominator", "分母"),
    ("sample_count_N", "樣本數"),
    ("material_class", "材料類別"),
    ("dataset_manifest_hash", "資料清單雜湊"),
    ("split_hash", "切分雜湊"),
    ("overlap_score", "跟設計／規則／訓練材料的重疊"),
    ("system_layer", "量的是哪一層"),
    ("execution_environment", "在哪裡跑的"),
    ("target_environment", "要落到哪裡"),
    ("model_id", "哪個模型"),
    ("model_hash", "模型權重雜湊"),
    ("config_hash", "設定雜湊"),
    ("code_commit", "哪一版程式碼"),
    ("seed", "亂數種子"),
    ("cache_state", "快取狀態"),
    ("raw_metric_artifact", "原始輸出在哪"),
    ("confidence_interval", "信賴區間"),
    ("measured_at", "什麼時候量的"),
    ("measured_by", "誰量的"),
    ("verification_method", "怎麼驗的"),
    ("applicability_scope", "這個數字適用到哪裡"),
)

FIELD_NAMES: tuple = tuple(k for k, _ in FIELDS)

#: 規格列的枚舉，逐字。**不加「其他」這一項** —— 加了之後每一筆
#: 歸不了類的都會落進去，而那正是這個契約要擋的事。
MATERIAL_CLASSES = ("real", "synthetic", "public", "consented", "blind",
                    "red-team")
SYSTEM_LAYERS = ("model", "wrapper", "router", "verifier", "end-to-end")
CACHE_STATES = ("cold", "warm", "hit", "miss")

NOT_APPLICABLE = "NOT_APPLICABLE"
UNKNOWN = "UNKNOWN"
ABSENT_KINDS = (NOT_APPLICABLE, UNKNOWN)

#: 呼叫者一定要自己給的。這幾欄沒有任何辦法從環境推出來，
#: 而推出來的那一刻它就不是量測了。
REQUIRED_FROM_CALLER: tuple = (
    "metric_name", "semantic_definition", "numerator", "denominator",
    "sample_count_N", "material_class", "system_layer",
    "measured_by", "verification_method", "applicability_scope",
)

#: 這個專案結構上就沒有的那幾欄，理由逐字對齊 `contract.py` 的
#: `dataset_manifest` / `source_classes` / `leakage_result` 三欄 ——
#: 兩邊講同一件事而措辭不同的話，讀的人會以為是兩件事。
STRUCTURAL_ABSENCE: dict = {
    "dataset_manifest_hash": (NOT_APPLICABLE,
                              "這個專案不是訓練任務，沒有 dataset manifest 這個物件"),
    "split_hash": (NOT_APPLICABLE, "同上，沒有切分就沒有切分雜湊"),
    "overlap_score": (NOT_APPLICABLE,
                      "同上，沒有訓練材料就算不出重疊分數"),
}


#: 概念適用、這個專案此刻取不到的那幾欄。理由不是這裡新編的，
#: 是 `contract.py` 已經查過並寫下來的實情，措辭對齊那邊。
#: `seed` 那一條 2026-09-17 親自再驗一次:最近一份 transcript jsonl
#: 的欄位表只有 `effort` 與 `perTurnEffort`，沒有 seed、沒有
#: temperature、沒有 top_p。
ENV_ABSENCE: dict = {
    "target_environment": (
        UNKNOWN,
        "沒有任何地方記錄目標環境。`runtimenode.py` 答的是「現在跑在哪」，"
        "不是「要落到哪裡」——兩件事。Project → RuntimeNode 的綁定仍然沒有"),
    "seed": (
        UNKNOWN,
        "這條線的 transcript jsonl 沒有 seed 這一欄（2026-09-17 實測欄位表"
        "只有 effort 與 perTurnEffort），提供端沒有給"),
}


def absent(kind: str, why: str) -> dict:
    """把一個缺席寫成資料。`why` 是強制的，空的會被 `build()` 擋下。"""
    return {"absent": kind, "why": str(why or "")}


def is_absent(v: object) -> bool:
    return isinstance(v, dict) and v.get("absent") in ABSENT_KINDS


def degraded(value: object, why: str) -> dict:
    """有值，但那個值不滿足規格要求它的性質。形狀對齊 `contract.Degraded`。

    **這裡用 dict 不用 class。** 一筆記錄要能寫進 jsonl 再讀回來，
    而讀回來的 class 實例會變成一個普通的 dict —— 那一刻降級的理由
    就不見了，於是一個「HEAD 指不到現在跑的程式碼」的記錄，
    重讀之後會看起來像一個乾淨的 commit。
    """
    return {"value": value, "degraded": str(why or "")}


def json_safe(v: object) -> object:
    """把 `contract` 那幾個 class 轉成寫得進 jsonl 的形狀。

    `Degraded` 轉成 `degraded()`，`NoSource` 轉成 `absent(UNKNOWN, ...)`
    —— 後者是**降級的**:NoSource 在 `contract.py` 的意思是「整個系統
    沒有地方算得出它」，而這裡只表示得出 UNKNOWN。理由原樣帶過來，
    所以資訊沒有掉，掉的是狀態碼的粒度。
    """
    if v is None or isinstance(v, (str, int, float, bool, dict, list)):
        return v
    why = getattr(v, "why", None)
    if isinstance(why, str):
        if hasattr(v, "value"):
            return degraded(v.value, why)
        return absent(UNKNOWN, why)
    return str(v)


# ---------------------------------------------------------------------------
# 環境那幾欄：真的量得到的就量，量不到的宣告 UNKNOWN
# ---------------------------------------------------------------------------


def execution_environment(*, node: dict | None = None) -> dict:
    """現在在哪裡跑的。這一欄量得到，所以不准是 UNKNOWN。

    借 `runtimenode`（2026-09-17 那一輪做的）拿機器身份。拿不到的
    時候**不退回空字串** —— 那會讓「量不到機器」跟「機器叫空字串」
    長得一樣。拿不到就只帶 python 與平台，並且在 `node_error` 說為什麼。
    """
    out = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
    if node is not None:
        out.update(node)
        return out
    try:
        import runtimenode as RN  # 延後 import：測試不必有它
        m = RN.measure()
        out["node_id"] = m["node_id"]
        out["host"] = m["host"]["hostname"]
        # `basis` 帶著走。退回 hostname 的 node_id 會在改機器名字那天
        # 變掉，而那在畫面上跟「換了一台機器」長得一模一樣 ——
        # 這件事 `runtimenode.summary_lines()` 已經釘過一次。
        out["basis"] = m["basis"]
    except Exception as exc:                      # pragma: no cover - 防禦
        out["node_error"] = f"{type(exc).__name__}: {exc}"
    return out


def code_commit(*, git: object = None) -> object:
    """哪一版程式碼。借 `contract.git_head`，不自己跑 git。

    回傳的可能是一個 `Degraded`（HEAD 拿得到但工作區跟它不一致）。
    **那個形狀原樣留著**，這裡不把它壓成字串：壓成字串之後
    「這個 hash 指得到現在跑的程式碼」這件事就看不出來了，
    而那正是 §33.1 要 `code_commit` 的理由。
    """
    if git is not None:
        return json_safe(git)
    try:
        import contract as CT                     # 延後 import
        return json_safe(CT.git_head())
    except Exception as exc:                      # pragma: no cover - 防禦
        return absent(UNKNOWN, f"拿不到 git HEAD：{type(exc).__name__}: {exc}")


def model_fields(*, transcript: str | Path | None = None,
                 model: dict | None = None) -> dict:
    """`model_id` / `model_hash` / `config_hash` 三欄。

    只有第一欄拿得到。後兩欄的理由**不是這裡新寫的**，是
    `contract.py` 的 `model_revision` 與 `model_config` 已經查過的實情：
    jsonl 裡只有 `effort`，沒有 temperature / top_p / system prompt 版本，
    也沒有模型權重的 revision。2026-09-17 再驗一次那份 jsonl 的欄位表，
    仍然只有 `effort` 與 `perTurnEffort`。
    """
    mi = model if model is not None else {}
    if model is None and transcript:
        try:
            import contract as CT                 # 延後 import
            mi = CT.model_from_transcript(transcript)
        except Exception:                         # pragma: no cover - 防禦
            mi = {}
    return {
        "model_id": mi.get("model") or absent(
            UNKNOWN, "這一條 session 的 jsonl 讀不到 model 欄位"),
        "model_hash": absent(
            UNKNOWN, "模型權重的 revision/hash 提供端沒有給。"
                     "jsonl 的 `version` 是 CLI 版本不是模型版本"),
        "config_hash": absent(
            UNKNOWN,
            "jsonl 只有 effort" + (f"（{mi['effort']}）" if mi.get("effort") else "")
            + "，沒有 temperature / top_p / system prompt 版本這些"
              "真正決定輸出的設定，所以算不出一個代表得了設定的雜湊"),
    }


def _mid(row: dict) -> str:
    raw = "|".join(str(row.get(k, "")) for k in
                   ("metric_name", "semantic_definition", "numerator",
                    "denominator", "sample_count_N", "measured_at",
                    "measured_by"))
    return "m-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def build(**kw) -> dict:
    """組一筆 `MetricRecord`，組不起來就說為什麼，不硬組。

    回 `{"ok": True, "record": {...}}` 或 `{"ok": False, "why": [...]}`。
    `why` 是一串話不是一句，因為缺三欄的時候修一欄再被擋一次
    是三次來回，而三次來回之後人會開始亂填。
    """
    problems: list = []

    for k in REQUIRED_FROM_CALLER:
        if k not in kw or kw[k] is None or kw[k] == "":
            problems.append(f"`{k}` 一定要給，這一欄推不出來")

    mc = kw.get("material_class")
    if mc is not None and mc not in MATERIAL_CLASSES and not is_absent(mc):
        problems.append(
            f"`material_class` 只收規格列的六種（{'、'.join(MATERIAL_CLASSES)}），"
            f"拿到的是 {mc!r}。歸不了類的數字照 §33.1 不能登記，"
            "要登記得先照分佈拆開")
    sl = kw.get("system_layer")
    if sl is not None and sl not in SYSTEM_LAYERS and not is_absent(sl):
        problems.append(
            f"`system_layer` 只收規格列的五種（{'、'.join(SYSTEM_LAYERS)}），"
            f"拿到的是 {sl!r}")
    cs = kw.get("cache_state")
    if cs is not None and cs not in CACHE_STATES and not is_absent(cs):
        problems.append(
            f"`cache_state` 只收規格列的四種（{'、'.join(CACHE_STATES)}），"
            f"拿到的是 {cs!r}")

    den = kw.get("denominator")
    if isinstance(den, (int, float)) and den == 0:
        problems.append("`denominator` 是 0，那樣算出來的不是一個比率")

    row: dict = {}
    for k in FIELD_NAMES:
        if k == "metric_id":
            continue
        if k in kw:
            row[k] = kw[k]
        elif k in STRUCTURAL_ABSENCE:
            kind, why = STRUCTURAL_ABSENCE[k]
            row[k] = absent(kind, why)
        elif k == "measured_at":
            row[k] = time.time()
        else:
            problems.append(
                f"`{k}` 既沒有值也沒有宣告缺席。"
                "一個沒有人說明為什麼不見的欄位，比一個說得出理由的缺席更糟")

    for k, v in row.items():
        if is_absent(v) and not (v.get("why") or "").strip():
            problems.append(f"`{k}` 宣告了缺席但沒寫理由")

    if problems:
        return {"ok": False, "why": problems}

    row["metric_id"] = _mid(row)
    return {"ok": True, "record": {k: row[k] for k in FIELD_NAMES}}


# ---------------------------------------------------------------------------
# 規格最後那句話，變成六項可以跑的檢查
# ---------------------------------------------------------------------------
#
#     the user must be able to inspect the metric's
#     'ruler, material, layer, denominator' plus environment and lineage

ASPECTS: tuple = (
    ("ruler", "尺", ("semantic_definition",)),
    ("material", "材料", ("material_class",)),
    ("layer", "層", ("system_layer",)),
    ("denominator", "分母", ("denominator",)),
    ("environment", "環境", ("execution_environment", "target_environment")),
    ("lineage", "血緣", ("model_id", "model_hash", "config_hash",
                        "code_commit", "seed")),
)


def _degraded_why(v: object) -> str | None:
    """降級的理由。拿不到就回 None。

    認兩種形狀:`degraded()` 出來的 dict，與 `contract.Degraded` 實例。
    **不 import `contract` 去做 isinstance** —— 那會讓這一支在沒有
    `contract` 的環境裡爆掉，而它其餘部分本來不需要它。

    dict 那一種一定要認，因為寫進 jsonl 再讀回來的記錄只有 dict。
    只認實例的話，登記當下判得出降級、重讀之後判不出來，
    而那個差異不會有任何錯誤訊息。
    """
    if isinstance(v, dict):
        d = v.get("degraded")
        return d if isinstance(d, str) and d else None
    why = getattr(v, "why", None)
    return why if isinstance(why, str) and why else None


def qualification(record: dict) -> dict:
    """這一筆夠不夠格被當成 release claim。

    六項全齊才 `releasable`。一項裡面只要有一欄缺席，那一項就不齊 ——
    **不算「大部分有」**：血緣缺 `model_hash` 的意思是換一組權重
    重跑會得到另一個數字而沒有人分得出來，那不是一個程度問題。
    """
    aspects = []
    for key, zh, fields in ASPECTS:
        missing = []
        for f in fields:
            v = record.get(f)
            if v is None or v == "":
                missing.append({"field": f, "kind": UNKNOWN,
                                "why": "這一欄整個不在這筆記錄裡"})
            elif is_absent(v):
                missing.append({"field": f, "kind": v["absent"],
                                "why": v.get("why", "")})
            else:
                dw = _degraded_why(v)
                if dw:
                    missing.append({"field": f, "kind": "DEGRADED", "why": dw})
        aspects.append({"key": key, "zh": zh, "fields": list(fields),
                        "ok": not missing, "missing": missing})
    ok = [a for a in aspects if a["ok"]]
    return {
        "metric_id": record.get("metric_id", ""),
        "metric_name": record.get("metric_name", ""),
        "aspects": aspects,
        "satisfied": len(ok),
        "total": len(ASPECTS),
        "releasable": len(ok) == len(ASPECTS),
        "why_not": [f"{a['zh']}缺 " + "、".join(m["field"] for m in a["missing"])
                    for a in aspects if not a["ok"]],
    }


# ---------------------------------------------------------------------------
# 登記簿
# ---------------------------------------------------------------------------


def register(record: dict, *, path: Path | None = None) -> dict:
    """把一筆組好的記錄寫進登記簿。**不在這裡重新驗一次值。**

    驗在 `build()`，這裡只擋「不是 `build()` 出來的東西」——
    兩個地方各驗一次會分歧，而分歧那天不會有錯誤訊息。
    """
    missing = [k for k in FIELD_NAMES if k not in record]
    if missing:
        return {"ok": False,
                "why": f"這不是 build() 出來的記錄，缺：{'、'.join(missing)}"}
    p = path or LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "metric_id": record["metric_id"]}


def load(*, path: Path | None = None) -> list[dict]:
    p = path or LOG
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("metric_id"):
            out.append(r)
    return out


def by_distribution(*, path: Path | None = None) -> dict:
    """§39.1 Metrics 那一欄要的形狀：**按分佈分開報**，不是一個總數。

    分佈這裡用 `material_class` 分組。規格 §33.1 把材料類別列成
    枚舉，而一個混了兩種材料的總數正是 `by distribution` 這三個字
    要擋的東西 —— 混起來之後，「在真實材料上多少」這個問題
    從畫面上問不出來。
    """
    rows = load(path=path)
    groups: dict = {}
    for r in rows:
        mc = r.get("material_class")
        key = mc if isinstance(mc, str) else "（材料類別缺席）"
        groups.setdefault(key, []).append(r)
    out = []
    for key in sorted(groups):
        items = []
        for r in groups[key]:
            q = qualification(r)
            items.append({
                "metric_id": r["metric_id"],
                "metric_name": r.get("metric_name", ""),
                "numerator": r.get("numerator"),
                "denominator": r.get("denominator"),
                "sample_count_N": r.get("sample_count_N"),
                "system_layer": r.get("system_layer"),
                "releasable": q["releasable"],
                "satisfied": q["satisfied"],
                "total": q["total"],
                "why_not": q["why_not"],
            })
        out.append({"material_class": key, "n": len(items), "metrics": items})
    return {
        # 契約版本跟著這一份答案走。讀的人拿到的是一組按分佈分好的
        # 數字，而「照哪一版契約分的」不在任何一筆記錄裡
        # （記錄那 25 欄是規格的，多塞一欄就不是那張表了）。
        "version": VERSION,
        "total": len(rows),
        "distributions": out,
        "releasable": sum(1 for r in rows if qualification(r)["releasable"]),
        "why_empty": (None if rows else
                      "登記簿是空的。這一支不自動登記任何東西 —— "
                      "要有值得有人把尺與材料寫下來登記一筆"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _arg(argv: list, name: str) -> str | None:
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _num(s: str | None):
    """數字就當數字，不是就原樣留著。

    **不硬轉。** 轉失敗丟例外的話，一個寫錯的分母會變成堆疊追蹤；
    原樣留著的話它會走到 `build()` 的型別檢查，那裡講得出人話。
    """
    if s is None:
        return None
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _print_record(r: dict) -> None:
    q = qualification(r)
    print()
    print(f"  {r.get('metric_name', '')}　{r.get('metric_id', '')}")
    print()
    for k, zh in FIELDS:
        v = r.get(k)
        if is_absent(v):
            print(f"  ○ {k}　{zh}")
            print(f"      {v['absent']}：{v.get('why', '')}")
        else:
            print(f"  ● {k}　{zh}　{v}")
    print()
    print(f"  夠不夠格當 release claim：{'夠' if q['releasable'] else '不夠'}"
          f"（{q['satisfied']}/{q['total']}）")
    for w in q["why_not"]:
        print(f"    缺　{w}")
    print()


def main(argv: list) -> int:
    """`forseti metric <list|show|template|register>`

    §33.1。`register` 收的是一份 JSON 檔，不是一長串旗標 ——
    這份記錄有 25 欄而且每一欄的缺席都要附理由，用旗標填的話
    人會為了讓指令跑得動而亂填，那正是這個契約要擋的事。
    """
    sub = argv[0] if argv else "list"
    rest = argv[1:]
    p = Path(_arg(rest, "--path")) if _arg(rest, "--path") else None

    if sub == "template":
        tpl = {}
        for k, zh in FIELDS:
            if k == "metric_id":
                continue
            if k in STRUCTURAL_ABSENCE:
                kind, why = STRUCTURAL_ABSENCE[k]
                tpl[k] = {"absent": kind, "why": why}
            elif k in ENV_ABSENCE:
                kind, why = ENV_ABSENCE[k]
                tpl[k] = {"absent": kind, "why": why}
            elif k in REQUIRED_FROM_CALLER:
                tpl[k] = f"<{zh}　一定要填>"
            else:
                tpl[k] = {"absent": UNKNOWN, "why": f"<{zh}　為什麼此刻取不到>"}
        # 這三欄不留空格給人自己編一句理由 —— 它們的實情
        # `contract.py` 已經查過，而人現場補的那一句會跟那邊分歧。
        tpl.update(model_fields(transcript=_arg(rest, "--transcript")))
        tpl["code_commit"] = code_commit()
        tpl["execution_environment"] = execution_environment()
        tpl["measured_at"] = time.time()
        print(json.dumps(tpl, ensure_ascii=False, indent=2))
        print()
        print(f"# material_class 只收：{'、'.join(MATERIAL_CLASSES)}",
              file=sys.stderr)
        print(f"# system_layer   只收：{'、'.join(SYSTEM_LAYERS)}",
              file=sys.stderr)
        return 0

    if sub == "register":
        src = _arg(rest, "--from")
        if not src:
            print("要一份 JSON：`forseti metric register --from <檔案>`。"
                  "空白模板：`forseti metric template`")
            return 2
        try:
            kw = json.loads(Path(src).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"讀不到或解不開：{exc}")
            return 2
        built = build(**kw)
        if not built["ok"]:
            print()
            print("  這一筆登記不了：")
            for w in built["why"]:
                print(f"    - {w}")
            print()
            return 1
        res = register(built["record"], path=p)
        if not res["ok"]:
            print(res["why"])
            return 1
        _print_record(built["record"])
        return 0

    if sub == "show":
        mid = _arg(rest, "--id") or (rest[0] if rest and not rest[0].startswith("-")
                                     else None)
        rows = [r for r in load(path=p) if not mid or r["metric_id"] == mid]
        if not rows:
            print("沒有這一筆" if mid else "登記簿是空的")
            return 1
        for r in rows:
            _print_record(r)
        return 0

    d = by_distribution(path=p)
    print()
    print(f"  §33.1 登記簿　{d['total']} 筆，"
          f"其中夠格當 release claim 的 {d['releasable']} 筆")
    if d["why_empty"]:
        print()
        print(f"  {d['why_empty']}")
    for g in d["distributions"]:
        print()
        print(f"  材料 {g['material_class']}　{g['n']} 筆")
        for m in g["metrics"]:
            print(f"    {m['metric_id']}　{m['metric_name']}　"
                  f"{m['numerator']}/{m['denominator']}　"
                  f"{'夠格' if m['releasable'] else '不夠格'}"
                  f"（{m['satisfied']}/{m['total']}）")
            for w in m["why_not"]:
                print(f"      缺　{w}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
