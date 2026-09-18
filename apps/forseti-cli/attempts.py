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


def _flag_without_value(argv: list, name: str) -> bool:
    """旗標出現了，可是後面沒有值。

    這跟「旗標沒出現」要分得開。`_arg` 兩種都回 None，而呼叫端拿
    None 當「沒指定，讀正本」——於是 `--path`（手滑漏掉路徑）會去
    讀正本並回報一份看起來正常的報告。2026-09-18 實測
    `forseti attempt list --path` 回的是正本那筆 att-2bb74c352d，
    五個欄位完整印出來。**那個人以為他看到的是自己指定的檔。**

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


SUBCOMMANDS: tuple[str, ...] = ("list", "show", "template", "record", "release")


#: `main()` 認得的全部旗標。跟底下那幾個 `_arg(rest, "--x")` 各寫
#: 一份，`tests/test_cli_flag_dispatch.py` 有一條盯著不漂開 ——
#: 漂開的話會出現「守門說認得、`main()` 裡沒人讀」的旗標，那種
#: 打對了也沒用，跟打錯字一樣靜默。整支共用一份不是每個子指令一份。
KNOWN_FLAGS: tuple[str, ...] = (
    "--path", "--from", "--id",
    "--attempt", "--observed", "--why", "--source", "--verifier",
    "--retry-condition", "--no-retry-basis")


def main(argv: list) -> int:
    """`forseti attempt <list|show|template|record|release>`

    §39.1 failed_attempts。`record` 收的是一份 JSON 檔或旗標兩種都行,
    因為這一份只有五個必填欄位，用旗標填不會逼人為了讓指令跑得動而亂填
    （`forseti metric` 那一支有 25 欄，所以那裡只收檔案）。
    """
    # 第一個參數以 `-` 開頭的時候它是旗標不是子指令。少了這一行，
    # `forseti attempt --path X` 會把 `--path` 放進 `sub`，於是 `rest`
    # 只剩下 X，`_arg(rest, "--path")` 找不到，結果是**讀正本而不是
    # 讀 X**。2026-09-18 實測：指定一個空檔，回的是正本那 1 筆
    # att-2bb74c352d，完整印出來跟正常查詢長得一模一樣，不會報錯。
    _flag_first = bool(argv) and str(argv[0]).startswith("-")
    sub = argv[0] if (argv and not _flag_first) else "list"
    rest = list(argv) if _flag_first else argv[1:]
    # `--path` 寫了可是後面沒有值 -> 明著退回，不准掉回正本。
    # 少了這一段，手滑漏掉路徑的人會拿到正本的內容並以為那是他指定的
    # 檔（2026-09-18 實測，原始輸出在那一輪的接續紀錄裡）。
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
    # 底下這七個是**內容欄位**，跟上面那兩個不同級。上面那兩個至少會報錯
    # （只是怪錯對象），這七個一句話都不說：2026-09-18 實測七個全部
    # exit=0、印「登錄了 att-xxxxxxxxxx」、磁碟落地把下一個旗標名寫成內容。
    # 撈出來確認過的四筆:
    #   `--attempt --observed "看到 X"`  -> attempt='--observed'
    #   `--source --verifier me`         -> source=['--verifier']
    #   `--verifier --no-retry-basis X`  -> verifier='--no-retry-basis'
    #   release `--why --verifier me`    -> RELEASE 那一筆 why='--verifier'
    # 最後一個是這一組裡最重的：release 存的就是「哪個條件成立了所以
    # 可以重試」，而那一欄變成旗標名等於這筆放掉沒有理由 —— 正是
    # `release()` 內部第 166 行明著擋空字串要防的那件事，只是空的擋得住，
    # 被下一個旗標填滿的擋不住。§39.1 五個必填欄位同理:填著旗標名的
    # 那一筆在 `list` 與 `show` 裡跟填對的長得一樣。
    for _flag, _what in (("--attempt", "試了什麼"),
                         ("--observed", "觀察到什麼"),
                         ("--why", "為什麼不要再試"),
                         ("--source", "出處"),
                         ("--verifier", "誰觀察到的"),
                         ("--retry-condition", "什麼條件成立可以再試"),
                         ("--no-retry-basis", "為什麼沒有重試條件")):
        if _flag_without_value(rest, _flag):
            print(f"  `{_flag}` 後面要接{_what}。沒接的話下一個旗標會被")
            print("  當成內容寫進登記簿，而且會印「登錄了」跟成功一樣 ——")
            print("  所以這裡退回。")
            return 2
    # 旗標名打錯字 -> 明著退回。這一支的打錯字後果分兩種，
    # 2026-09-18 逐個量的：**必填**那幾欄打錯會被 `record()` 內部擋住
    # （`--attemptt` 回「attempt 是空的」exit=2，怪錯對象但至少沒落地）；
    # **選填**那幾欄打錯是靜默的 —— `--retry-conditionn 等登入` exit=0、
    # 印「登錄了 att-xxxxxxxxxx」、磁碟上 `retry_condition` 是 `''`。
    # 那一欄存的就是「什麼條件成立可以再試」，空的跟「本來就沒有
    # 重試條件」在 `list` 與 `show` 裡長得一模一樣。
    _unknown = _unknown_flags(rest, KNOWN_FLAGS)
    if _unknown:
        print()
        print(f"  不認得這個旗標：{'、'.join(_unknown)}")
        print(f"  有的是：{'、'.join(KNOWN_FLAGS)}")
        print("  打錯字不會報錯，那個旗標會被當成沒寫 —— 選填那幾欄")
        print("  會靜默留空，而畫面照樣印「登錄了」。所以這裡退回。")
        print()
        return 2
    p = Path(_arg(rest, "--path")) if _arg(rest, "--path") else None

    # 打錯子指令不准靜默掉進 list。這一支比 `metric` 更要緊：它的正本
    # 此刻有資料，所以打錯字拿到的不是「0 筆」而是一份看起來完整的
    # 別人的答案。
    if sub not in SUBCOMMANDS:
        print()
        print(f"  不認得這個子指令：{sub}")
        print(f"  有的是：{'、'.join(SUBCOMMANDS)}")
        print()
        return 2

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
