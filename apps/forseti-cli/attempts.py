#!/usr/bin/env python3
"""失敗嘗試登記簿。§39.1 的 `failed_attempts` 那一欄。

規格原文（AI-First 工程書 v1.0 第 975 行，逐字）:

    failed_attempts:
    - attempt + observed result + why not repeat

三個東西，不是一個。只寫「試過 X 沒用」的那種記錄，
下一個 session 讀完仍然會再試一次 X，因為它不知道當時看到什麼，
也不知道為什麼不該再試。

────────────────────────────────────────────────────

## 為什麼這一支沒有自動掃描

這個 repo 的失敗嘗試全部寫在 `.forseti/AUTO_CONTINUE_LOG.md` 與
`.forseti/ROADMAP.md` 的散文裡。`contract.py` 先前就是這樣標的:
「那是散文不是可查詢的狀態，沒有欄位也沒有 id」。

看起來最省事的做法是寫一支掃描器去抓「試了……沒好」這類句型。
不做，理由跟 `pollution.py` 同一條: BLOCKERS 的 B-05 擋住任何單獨靠
文字判斷「這句話有沒有在宣稱某件事」的做法。抓到的會是符合句型的
句子，不是真的失敗嘗試，而漏掉的那些會長得跟「沒有失敗嘗試」一樣。

登錄一律是明確呼叫 `record()`。

## 出處與記錄者為什麼是必填

規格只列三欄。這裡多要兩個:

- `source`: 一筆查不回出處的失敗記錄，本身就是一個沒有證據的宣稱。
  下一個人要能自己去看當時的原始輸出，而不是相信這一筆。
- `verifier`: 不知道是誰觀察到的，這筆的可信度就沒有上限也沒有下限。

兩條都照 `pollution.py` 已經付過代價的先例，不是這裡新發明的要求。

## retry_condition 為什麼不是選填到底

「why not repeat」在這個專案有兩種完全不同的實情:

  一種是條件沒變所以不要重試（認證過期、碟沒掛、額度用完）。
  條件變了就該重試，而且那一刻這筆記錄反而會擋路。

  另一種是這條路本身走不通（做法錯了、前提錯了）。
  那種沒有重試條件，條件怎麼變都一樣。

**不發明枚舉去分這兩種。** 規格沒有定義它們，照 §8.3 的禁止捷徑，
這裡不編一個分類器。改成照 `pollution.py` 的 `propagation_radius`
與 `radius_basis` 那個已經存在的形狀: 沒給 `retry_condition`
就要講 `no_retry_basis`（為什麼這一筆沒有重試條件）。

空的 `retry_condition` 讀起來是「試過了，永遠不要再試」，
跟「有條件但沒人寫下來」是兩件事，而後者常常才是實情。

## 只增不改

跟事件帳本、粉紅點、污染登記簿同一條。一筆寫下去當下就是證據，
事後改掉就不是了。條件成立可以重試的時候，追加一筆 `release`，
不回頭改原來那一筆。

零依賴，跟這條線上其他模組一樣。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

VERSION = "attempts@1.0"

REPO = Path(__file__).resolve().parents[2]
LOG = REPO / ".forseti" / "attempts.jsonl"

#: 規格第 975-977 行逐字的三欄。沒有第四個是規格要的。
SPEC_FIELDS = ("attempt", "observed_result", "why_not_repeat")

#: 這一支額外要求的兩欄，理由在模組說明。
EVIDENCE_FIELDS = ("source", "verifier")

#: 兩種 kind。`RELEASE` 是追加一筆說某一筆的條件成立了，
#: 不是把原來那筆改掉。
KINDS = ("ATTEMPT", "RELEASE")


def _id(attempt: str, observed: str) -> str:
    h = hashlib.sha256((attempt + "\x00" + observed).encode("utf-8"))
    return "att-" + h.hexdigest()[:10]


def record(*, attempt: str, observed_result: str, why_not_repeat: str,
           source: list[str], verifier: str,
           retry_condition: str = "", no_retry_basis: str = "",
           at: float | None = None, path: Path | None = None) -> dict:
    """登錄一筆失敗嘗試。回寫進去的那一筆，或拒絕的理由。

    五個必填一個都不能空。少了「observed result」這一筆就退化成
    一句沒有證據的抱怨；少了「why not repeat」下一個人照樣會再試一次。
    """
    at_ = (attempt or "").strip()
    ob = (observed_result or "").strip()
    wh = (why_not_repeat or "").strip()
    src = [s for s in (source or []) if str(s).strip()]
    vf = (verifier or "").strip()
    rc = (retry_condition or "").strip()
    nb = (no_retry_basis or "").strip()

    if not at_:
        return {"ok": False,
                "why": "attempt 是空的。沒有「試了什麼」就沒有東西可以登錄"}
    if not ob:
        return {"ok": False,
                "why": "observed_result 是空的。規格第 976 行要的是"
                       "「觀察到的結果」，不是「我覺得它不行」。"
                       "沒有這一欄，下一個人分不出是真的失敗還是當時看錯"}
    if not wh:
        return {"ok": False,
                "why": "why_not_repeat 是空的。只寫試過沒用的話，"
                       "下一個 session 讀完仍然會再試一次同一件事，"
                       "而那正是這一欄存在的理由"}
    if not src:
        return {"ok": False,
                "why": "source 是空的。一筆查不回出處的失敗記錄"
                       "本身就是一個沒有證據的宣稱"}
    if not vf:
        return {"ok": False,
                "why": "verifier 是空的。不知道是誰觀察到的，"
                       "這筆的可信度就沒有上限也沒有下限"}
    if not rc and not nb:
        return {"ok": False,
                "why": "retry_condition 沒給就要講 no_retry_basis"
                       "（為什麼這一筆沒有重試條件）。空的重試條件讀起來是"
                       "「永遠不要再試」，跟「有條件但沒人寫下來」是兩件事，"
                       "而後者常常才是實情"}

    row = {
        "id": _id(at_, ob),
        "attempt": at_,
        "observed_result": ob,
        "why_not_repeat": wh,
        "source": src,
        "verifier": vf,
        "retry_condition": rc,
        "no_retry_basis": nb,
        "recorded_at": at or time.time(),
        "kind": "ATTEMPT",
    }
    _append(row, path)
    return {"ok": True, "record": row}


def release(aid: str, *, why: str, verifier: str,
            at: float | None = None, path: Path | None = None) -> dict:
    """追加一筆說某一筆的重試條件成立了。**不改原來那一筆。**

    只有帶著 `retry_condition` 的那些放得掉。沒有重試條件的那些
    （`no_retry_basis` 講的就是這件事）放不掉，因為它們當初登記的
    實情就是條件怎麼變都一樣。要推翻那種判斷走的是 §40 的污染登記簿,
    那裡存的是「當初為什麼會這樣判」，這裡存不了。
    """
    cur = get(aid, path=path)
    if cur is None:
        return {"ok": False, "why": f"找不到 {aid}"}
    if not (why or "").strip():
        return {"ok": False,
                "why": "why 是空的。放掉一筆失敗記錄要講出哪個條件成立了，"
                       "不然下一個人看到的是一筆被撤銷而沒有理由的記錄"}
    if not (verifier or "").strip():
        return {"ok": False,
                "why": "verifier 是空的。誰確認條件成立的要留下來"}
    if not cur.get("retry_condition"):
        return {"ok": False,
                "why": f"{aid} 當初登記的時候沒有重試條件，理由是"
                       f"「{cur.get('no_retry_basis', '')}」。"
                       f"那種放不掉。要推翻當初那個判斷走 §40 污染登記簿"}
    if cur.get("released"):
        return {"ok": False, "why": f"{aid} 已經放掉了"}

    row = {
        "id": aid,
        "kind": "RELEASE",
        "why": (why or "").strip(),
        "verifier": (verifier or "").strip(),
        "released_at": at or time.time(),
    }
    _append(row, path)
    return {"ok": True, "record": row}


def _append(row: dict, path: Path | None) -> None:
    p = path or LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load(*, path: Path | None = None) -> list[dict]:
    """原始的每一行，順序照寫入。壞掉的行跳過不當成資料。"""
    p = path or LOG
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("id") and r.get("kind") in KINDS:
            out.append(r)
    return out


def records(*, path: Path | None = None) -> list[dict]:
    """把 `RELEASE` 折進它所屬的那一筆，回目前的狀態。

    折的時候原始那一筆不動，加的是 `released` 這個 dict。
    要看原始序列用 `load()`。
    """
    base: dict[str, dict] = {}
    order: list[str] = []
    rel: dict[str, dict] = {}
    for r in load(path=path):
        rid = r["id"]
        if r["kind"] == "ATTEMPT":
            if rid not in base:
                base[rid] = dict(r)
                order.append(rid)
        else:
            rel[rid] = r
    out = []
    for rid in order:
        row = dict(base[rid])
        if rid in rel:
            row["released"] = {k: v for k, v in rel[rid].items()
                               if k not in ("id", "kind")}
        out.append(row)
    return out


def get(aid: str, *, path: Path | None = None) -> dict | None:
    for r in records(path=path):
        if r["id"] == aid:
            return r
    return None


def active(*, path: Path | None = None) -> list[dict]:
    """還在擋路的那些。放掉的不算。"""
    return [r for r in records(path=path) if not r.get("released")]


def summary(*, path: Path | None = None) -> dict:
    """§39.1 那一欄要的形狀。

    **總數與還在擋路的數兩個都報。** 只報還在擋路的話，
    一筆放掉的記錄會從畫面上消失，而「這件事以前試過，後來條件變了」
    正是下一個人需要知道的東西。

    `with_retry_condition` 分開數，因為那些是會過期的:
    條件成立了卻沒有人去放，跟真的還在擋路長得一模一樣。
    """
    rs = records(path=path)
    act = [r for r in rs if not r.get("released")]
    return {
        "total": len(rs),
        "active": len(act),
        "released": len(rs) - len(act),
        "with_retry_condition": len([r for r in act if r.get("retry_condition")]),
        "no_retry": len([r for r in act if not r.get("retry_condition")]),
        "items": [
            {
                "id": r["id"],
                "attempt": r["attempt"],
                "observed_result": r["observed_result"],
                "why_not_repeat": r["why_not_repeat"],
                "retry_condition": r.get("retry_condition", ""),
                "no_retry_basis": r.get("no_retry_basis", ""),
                "source": r.get("source", []),
                "verifier": r.get("verifier", ""),
            }
            for r in act
        ],
        "version": VERSION,
    }


# ── CLI ────────────────────────────────────────────────────────────

def _arg(argv: list, name: str) -> str | None:
    for i, a in enumerate(argv):
        if a == name and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith(name + "="):
            return a.split("=", 1)[1]
    return None


def _print_record(r: dict) -> None:
    print()
    print(f"  {r['id']}　{'（已放掉）' if r.get('released') else ''}")
    print()
    print(f"  試了什麼　　　{r['attempt']}")
    print(f"  看到什麼　　　{r['observed_result']}")
    print(f"  為什麼不重試　{r['why_not_repeat']}")
    if r.get("retry_condition"):
        print(f"  什麼條件成立可以再試　{r['retry_condition']}")
    else:
        print(f"  沒有重試條件，理由　{r.get('no_retry_basis', '')}")
    print(f"  出處　　　　　{'、'.join(r.get('source', []))}")
    print(f"  誰觀察到的　　{r.get('verifier', '')}")
    if r.get("released"):
        rel = r["released"]
        print(f"  放掉的理由　　{rel.get('why', '')}（{rel.get('verifier', '')}）")
    print()


def main(argv: list) -> int:
    """`forseti attempt <list|show|template|record|release>`

    §39.1 failed_attempts。`record` 收的是一份 JSON 檔或旗標兩種都行,
    因為這一份只有五個必填欄位，用旗標填不會逼人為了讓指令跑得動而亂填
    （`forseti metric` 那一支有 25 欄，所以那裡只收檔案）。
    """
    sub = argv[0] if argv else "list"
    rest = argv[1:]
    p = Path(_arg(rest, "--path")) if _arg(rest, "--path") else None

    if sub == "template":
        print(json.dumps({
            "attempt": "<試了什麼　一定要填>",
            "observed_result": "<觀察到什麼　原始輸出、狀態碼、錯誤訊息>",
            "why_not_repeat": "<為什麼不要再試一次>",
            "source": ["<查得回去的出處，檔案:行 或 指令>"],
            "verifier": "<誰觀察到的>",
            "retry_condition": "<什麼條件成立之後可以再試；沒有就留空>",
            "no_retry_basis": "<留空 retry_condition 的話，這裡講為什麼沒有>",
        }, ensure_ascii=False, indent=2))
        print()
        print("# 五個必填：attempt、observed_result、why_not_repeat、"
              "source、verifier")
        print("# retry_condition 與 no_retry_basis 至少要有一個")
        print("# 填完：forseti attempt record --from <檔案>")
        return 0

    if sub == "record":
        src_file = _arg(rest, "--from")
        if src_file:
            try:
                data = json.loads(Path(src_file).read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"讀不到 {src_file}：{type(exc).__name__}: {exc}")
                return 2
        else:
            data = {
                "attempt": _arg(rest, "--attempt") or "",
                "observed_result": _arg(rest, "--observed") or "",
                "why_not_repeat": _arg(rest, "--why") or "",
                "source": [s for s in (_arg(rest, "--source") or "").split(",")
                           if s.strip()],
                "verifier": _arg(rest, "--verifier") or "",
                "retry_condition": _arg(rest, "--retry-condition") or "",
                "no_retry_basis": _arg(rest, "--no-retry-basis") or "",
            }
        r = record(path=p, **{k: data.get(k, "") for k in
                              ("attempt", "observed_result", "why_not_repeat",
                               "retry_condition", "no_retry_basis", "verifier")},
                   source=list(data.get("source") or []))
        if not r["ok"]:
            print(f"沒有登錄：{r['why']}")
            return 2
        print(f"登錄了 {r['record']['id']}")
        return 0

    if sub == "release":
        aid = rest[0] if rest and not rest[0].startswith("-") else ""
        r = release(aid, why=_arg(rest, "--why") or "",
                    verifier=_arg(rest, "--verifier") or "", path=p)
        if not r["ok"]:
            print(f"沒有放掉：{r['why']}")
            return 2
        print(f"放掉了 {aid}")
        return 0

    if sub == "show":
        aid = rest[0] if rest and not rest[0].startswith("-") else ""
        r = get(aid, path=p)
        if r is None:
            print(f"找不到 {aid}")
            return 2
        _print_record(r)
        return 0

    s = summary(path=p)
    print()
    print(f"  失敗嘗試登記簿　共 {s['total']} 筆，"
          f"還在擋路 {s['active']}，放掉了 {s['released']}")
    if s["active"]:
        print(f"  其中 {s['with_retry_condition']} 筆有重試條件"
              f"（條件成立了要有人來放），{s['no_retry']} 筆沒有")
    print()
    if not s["total"]:
        print("  此刻 0 筆。這一支不自動登記任何東西，理由在模組說明。")
        print("  要登一筆：forseti attempt template")
        print()
        return 0
    for r in records(path=p):
        _print_record(r)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
