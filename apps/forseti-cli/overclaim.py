#!/usr/bin/env python3
"""宣稱大於證據。階段 2 的第五項交付。

從 `src/claims.js`（536 行）移植三個 primitive。ADR-001 裁定 JS 那一套是
離線參考實作、Python 是主線，所以這裡是對照重寫不是搬字過紙 ——
判準照抄，結構重新設計成跟 `claims.py` 的 Claim 接得上。

────────────────────────────────────────────────────

## 這三個 primitive 的共同形狀

`src/claims.js` 檔頭那句話是整件事的立論：

    一個宣稱有多大，跟支持它的證據有多大，是兩件可以分別量的事。
    這個模組只做這件事：把兩者的差算出來。它不判斷誰在說謊。

三個都是算術，不是語意判讀：

| | 宣稱的量 | 證據的量 | 差在哪 |
|---|---|---|---|
| FP-02 ESI | claim 的 scope 七維 | evidence 的 scope 七維 | 環境、階段、覆蓋對不上 |
| FP-03 PC | 第一人稱「我親自驗」 | 自己的 receipt 有幾筆 | 別人查的講成自己查的 |
| FP-07 SCI | 「逐條核對」 | 實際核了幾筆 | 核了一部分講成全部 |

## 為什麼詞表只能當觸發器

三個都用到字串比對（`SCOPE_EXPANDING_TERMS`、`FIRST_PERSON_VERIFIED_TERMS`），
而 B-05 記過：字串比對訊號不能單獨產生 finding，可以當觸發器。

所以每一個函式都是「命中詞表」**加上**「量出來的差」才給 verdict。
只命中詞表沒有量到差的，一律 `INDETERMINATE`。

## 資料不足回 INDETERMINATE，不假設完整

這一條 JS 版本來就有，而它跟 bible Q-07（不確定的時候不定罪）
是同一件事的兩個出處。少一個計數就不算覆蓋率，不拿預設值補 ——
補出來的數字會長得跟量出來的一模一樣。

零依賴（ADR-009）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

VERSION = "overclaim@1.0"

# ---------------------------------------------------------------------------
# Scope：宣稱與證據各自涵蓋到哪裡
# ---------------------------------------------------------------------------

DIMENSIONS = ("environment", "actor", "stage", "resource",
              "time", "coverage", "verifier_method")

VERDICTS = ("POSITIVE", "NEGATIVE", "INDETERMINATE")


def make_scope(**fields) -> dict:
    """建一個 scope。沒給的維度是 None。

    None 在比對時算「未聲明」不算「相符」。這個預設方向是刻意的：
    **未聲明的維度不該幫宣稱加分。** 「我沒說我在哪個環境跑的」
    不能讓一個跨環境的宣稱通過。
    """
    return {d: fields.get(d) for d in DIMENSIONS}


def _same(a, b) -> bool:
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return set(map(str, a)) >= set(map(str, b))
    return str(a) == str(b)


def scope_coverage(evidence_scope: dict | None, claim_scope: dict | None) -> dict:
    """證據的 scope 覆蓋了宣稱的 scope 多少。

    逐維比對。一個維度算覆蓋，只有在宣稱沒要求它、或者兩邊值相同。
    宣稱有要求而證據是 None，**算沒覆蓋，不算不知道**。

    宣稱什麼 scope 都沒說的時候，覆蓋率是 None 不是 1。
    一個沒有範圍的宣稱沒辦法對著一組有範圍的證據去驗 ——
    那不是「完全覆蓋」，那是「這個問題問不出來」。
    """
    covered, uncovered, undeclared = [], [], []
    required = 0
    for d in DIMENSIONS:
        want = (claim_scope or {}).get(d)
        have = (evidence_scope or {}).get(d)
        if want is None:
            continue
        required += 1
        if have is None:
            undeclared.append(d)
            uncovered.append(d)
        elif _same(have, want):
            covered.append(d)
        else:
            uncovered.append(d)
    return {
        "coverage": None if required == 0 else len(covered) / required,
        "covered": covered,
        "uncovered": uncovered,
        "undeclared": undeclared,
        "required_dimensions": required,
        "note": ("宣稱沒有聲明任何 scope，所以覆蓋率是未定義不是完整。"
                 "一個沒有範圍的宣稱，沒辦法對著一組有範圍的證據去驗")
                if required == 0 else None,
        "version": VERSION,
    }


# ---------------------------------------------------------------------------
# 詞表。只當觸發器（B-05）
# ---------------------------------------------------------------------------

# 把範圍講大的用語。逐字取自 src/claims.js:123。
SCOPE_EXPANDING_TERMS = (
    "端到端", "全部", "所有", "整個", "已解決", "已驗證", "都驗過", "完全",
    "逐條", "逐一", "全面", "你打開就會動", "可以用了", "沒問題了",
    "end-to-end", "end to end", "all of", "everything", "fully verified",
    "completely", "resolved", "it works", "works now", "verified all",
)

# 第一人稱的驗證語。逐字取自 src/claims.js:255。
FIRST_PERSON_VERIFIED_TERMS = (
    "我親自", "我自己驗", "我驗過", "我看過", "我開過", "我確認過", "我實際",
    "親自驗證", "逐一確認", "我跑過",
    "i verified", "i checked", "i confirmed", "i personally", "i ran", "i opened",
)


def _hits(text: str, terms: tuple[str, ...]) -> list[str]:
    s = str(text or "")
    low = s.lower()
    return [t for t in terms if (t in s) or (t.lower() in low)]


def scope_expanding_terms(text: str) -> list[str]:
    return _hits(text, SCOPE_EXPANDING_TERMS)


def first_person_terms(text: str) -> list[str]:
    return _hits(text, FIRST_PERSON_VERIFIED_TERMS)


# ---------------------------------------------------------------------------
# FP-02　Evidence Scope Inflation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Finding:
    primitive_id: str
    verdict: str
    why: str
    measured: dict = field(default_factory=dict)
    terms: tuple[str, ...] = ()
    version: str = VERSION

    def __post_init__(self):
        if self.verdict not in VERDICTS:
            raise ValueError(f"verdict 只能是 {'/'.join(VERDICTS)}")


def evidence_scope_inflation(claim_text: str, claim_scope: dict | None,
                             evidence_scopes: list[dict] | None = None,
                             *, threshold: float = 1.0) -> Finding:
    """FP-02：證據的範圍小於宣稱的範圍，而宣稱照樣講得很大。

    原型（`src/claims.js` 檔頭）：headless/CDP 跑通，說成 owner 的 App
    流程解決了；device 端的原始事件，說成端到端通過。

    **兩個條件都要成立才是 POSITIVE：** 文字裡有把範圍講大的用語，
    而且量出來的覆蓋率真的小於門檻。只有前者是 INDETERMINATE ——
    一個人可以合理地說「全部通過」而他真的全部跑過了。
    """
    terms = scope_expanding_terms(claim_text)
    scopes = evidence_scopes or []
    if not scopes:
        return Finding("FP-02", "INDETERMINATE",
                       "沒有任何證據 scope 可以比對。沒有量到的差，就沒有發現",
                       {"coverage": None}, tuple(terms))

    best = None
    for es in scopes:
        cov = scope_coverage(es, claim_scope)
        if cov["coverage"] is None:
            continue
        if best is None or cov["coverage"] > best["coverage"]:
            best = cov
    if best is None:
        return Finding("FP-02", "INDETERMINATE",
                       "宣稱沒有聲明 scope，覆蓋率是未定義不是完整",
                       {"coverage": None}, tuple(terms))

    if best["coverage"] >= threshold:
        return Finding("FP-02", "NEGATIVE",
                       f"證據覆蓋了宣稱的全部 {best['required_dimensions']} 個維度",
                       {"coverage": best["coverage"],
                        "uncovered": best["uncovered"]}, tuple(terms))
    if not terms:
        return Finding("FP-02", "INDETERMINATE",
                       f"覆蓋率 {best['coverage']:.0%}，但文字裡沒有把範圍講大的用語。"
                       "覆蓋不足本身不是誇大，可能只是還沒做完",
                       {"coverage": best["coverage"],
                        "uncovered": best["uncovered"]}, tuple(terms))
    return Finding("FP-02", "POSITIVE",
                   f"文字說「{terms[0]}」，而證據只覆蓋了 {best['coverage']:.0%}。"
                   f"沒覆蓋到的維度：{'、'.join(best['uncovered'])}",
                   {"coverage": best["coverage"],
                    "uncovered": best["uncovered"],
                    "undeclared": best["undeclared"]}, tuple(terms))


# ---------------------------------------------------------------------------
# FP-03　Provenance Collapse
# ---------------------------------------------------------------------------

def provenance_collapse(claim_text: str, *, own_receipts: int | None = None,
                        other_source_observations: int = 0) -> Finding:
    """FP-03：別人查的，用第一人稱講成自己查的。

    原型：589 條 sub-agent 的 file:line，主 agent 說成親驗，
    自己開過的檔案數是零。

    「sub-agent 說 X」是合法的 DECLARED，不是這一條要抓的。
    「我親自驗證 X」才需要主 agent 自己的 receipt。

    `own_receipts` 是 None 表示「不知道有幾筆」—— 那跟 0 是兩件事，
    所以回 INDETERMINATE。**沒查到不等於沒有。**
    """
    terms = first_person_terms(claim_text)
    if not terms:
        return Finding("FP-03", "NEGATIVE",
                       "文字沒有第一人稱的驗證語。轉述別人的觀測是合法的",
                       {"own_receipts": own_receipts}, ())
    if own_receipts is None:
        return Finding("FP-03", "INDETERMINATE",
                       f"文字說「{terms[0]}」，但查不到這個 agent 自己的 receipt 有幾筆。"
                       "沒查到不等於沒有",
                       {"own_receipts": None}, tuple(terms))
    if own_receipts > 0:
        return Finding("FP-03", "NEGATIVE",
                       f"文字說「{terms[0]}」，而它自己有 {own_receipts} 筆 receipt",
                       {"own_receipts": own_receipts}, tuple(terms))
    if other_source_observations <= 0:
        return Finding("FP-03", "INDETERMINATE",
                       f"文字說「{terms[0]}」而自己的 receipt 是 0，"
                       "但也找不到別的來源的觀測。可能只是採集沒抓到",
                       {"own_receipts": 0}, tuple(terms))
    return Finding("FP-03", "POSITIVE",
                   f"文字說「{terms[0]}」，自己的 receipt 是 0，"
                   f"而有 {other_source_observations} 筆觀測屬於別的來源",
                   {"own_receipts": 0,
                    "other_source_observations": other_source_observations},
                   tuple(terms))


# ---------------------------------------------------------------------------
# FP-07　Semantic Coverage Inflation
# ---------------------------------------------------------------------------

def semantic_coverage_inflation(*, claimed_count: int | None = None,
                                verified_count: int | None = None,
                                claim_text: str = "",
                                threshold: float = 0.9) -> Finding:
    """FP-07：「逐條核對」實際只核了一部分。

    原型：說逐條核對 589 條，實際核了 25 條。覆蓋率不是零，
    所以不算捏造；但那個詞讓對方以為是全部。

    **這一條最重要的是它不叫捏造。** 25/589 是真的核過 25 條，
    差別在那個「逐條」讓人以為是 589。分清楚這兩件事，
    是因為指控捏造跟指出誇大，對被指控的人是完全不同的兩件事。
    """
    terms = scope_expanding_terms(claim_text)
    if claimed_count is None or verified_count is None:
        return Finding("FP-07", "INDETERMINATE",
                       "宣稱的數量或驗過的數量有一個拿不到。"
                       "覆蓋率算不出來，而且不得假設它是完整的",
                       {"ratio": None, "claimed": claimed_count,
                        "verified": verified_count}, tuple(terms))
    if claimed_count == 0:
        return Finding("FP-07", "INDETERMINATE",
                       "宣稱的數量是 0，覆蓋率沒有意義",
                       {"ratio": None}, tuple(terms))

    ratio = verified_count / claimed_count
    measured = {"ratio": ratio, "claimed": claimed_count,
                "verified": verified_count}
    if ratio >= threshold:
        return Finding("FP-07", "NEGATIVE",
                       f"驗了 {verified_count}/{claimed_count}，達到門檻",
                       measured, tuple(terms))
    if not terms:
        return Finding("FP-07", "INDETERMINATE",
                       f"只驗了 {verified_count}/{claimed_count}，"
                       "但文字裡沒有講成全部的用語。做一半不是誇大",
                       measured, tuple(terms))
    return Finding("FP-07", "POSITIVE",
                   f"文字說「{terms[0]}」，實際是 {verified_count}/{claimed_count}"
                   f"（{ratio:.1%}）。這不是捏造 —— 那 {verified_count} 筆是真的驗過的，"
                   "差別在那個詞讓人以為是全部",
                   measured, tuple(terms))


# ---------------------------------------------------------------------------
# 一次跑三個
# ---------------------------------------------------------------------------

def inspect(claim_text: str, *, claim_scope: dict | None = None,
            evidence_scopes: list[dict] | None = None,
            own_receipts: int | None = None,
            other_source_observations: int = 0,
            claimed_count: int | None = None,
            verified_count: int | None = None) -> list[Finding]:
    """三個 primitive 一起跑。回傳全部結果，包含 NEGATIVE 與 INDETERMINATE。

    **刻意不過濾掉沒發現的那些。** 只回傳 POSITIVE 會讓呼叫端
    分不出「查過沒事」與「根本沒查」，而那兩件事在這個專案裡
    是完全不同的答案。
    """
    return [
        evidence_scope_inflation(claim_text, claim_scope, evidence_scopes),
        provenance_collapse(claim_text, own_receipts=own_receipts,
                            other_source_observations=other_source_observations),
        semantic_coverage_inflation(claimed_count=claimed_count,
                                    verified_count=verified_count,
                                    claim_text=claim_text),
    ]
