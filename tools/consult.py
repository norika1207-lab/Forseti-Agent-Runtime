#!/usr/bin/env python3
"""術前診斷器（consult）。醫生 mentor 階段一的第一個可跑產物。

這支跟 tools/risky.py、src/claims.js 是相反方向的東西,寫清楚免得下一個人以為重複:

    claims / risky   事後。拿已經發生的 transcript,抽出過去式宣稱去驗,
                     抓「說了沒做」跟「說了沒把握而人沒回應」的縫。
    consult          事前。拿一段還沒送出去的 prompt 意圖,在它變成
                     指令之前,看它送進去會不會讓 AI 飄移、會不會踩到
                     不可逆操作、範圍夠不夠明確,然後給醫囑。

claims.py 自己那條「沒有過去式動詞就不抽,意圖不是宣稱」正好界定了這個分工:
意圖不歸 claims 管,歸這裡管。兩者不撞。

## 一條硬性設計,取自 bible Q-07（不確定往寬鬆倒,誤判不對稱）

這支的預設是安靜放行。只有真的偵測到東西才出聲。理由:一個每句話都
囉嗦兩行的醫生,使用者三天就關掉他（工程書 RSK-4）。所以:
    verdict 預設 PASS。
    偵測到模糊或飄移風險,升到 ADVISE（建議,不擋）。
    偵測到明確的不可逆操作,升到 CAUTION（提醒使用者確認,仍不強制擋）。
    這支不會 BLOCK。擋不擋是使用者的權利,醫生只負責把代價攤開。

## 這支現在還不接 Mercury

工程書說醫囑品質等於器材解析度,要靠 Mercury 造影指到專案裡具體某一行。
Mercury 2026-09-11 正在搬家,所以這一版只用文字層的規則判斷,不接造影。
造影接口留成 scan() 這個佔位,搬完再接,路徑不寫死。這是階段一可控版本
（工程書 7.3 節）:先做出能跑的門診,做了才知道醫囑好不好。

用法:
    python3 tools/consult.py "幫我把那個檔案優化一下"
    echo "把舊資料全部清掉重來" | python3 tools/consult.py
    python3 tools/consult.py --json "..."      只輸出 json
"""

from __future__ import annotations

import json
import re
import sys

# ── 判準詞表。每一組都附它為什麼在這裡,不是憑感覺列的 ──────────────

# 模糊指稱:使用者用了代名詞或含糊動詞,但沒指明對象。送進去 AI 會自己猜對象,
# 猜錯就做錯。這對應工程書決策樹 Q1。
VAGUE_REFERENCE = [
    "那個", "這個", "那些", "這些", "它", "上面那個", "剛剛那個", "之前那個",
    "幫我弄", "幫我用", "幫我搞", "處理一下", "弄一下", "看著辦", "隨便",
]

# 會讓 AI 自由發揮的詞:範圍無界或授權太寬。AI 會擴張解讀,做超出使用者本意的事。
# 這對應工程書決策樹 Q2,也對應 Asclepius 那條「保留頭尾只動中段」的反面:
# 沒界定範圍等於叫它動全部。
OPEN_SCOPE = [
    "全部", "所有", "整個", "每一個", "統統", "一律", "都",
    "優化", "改善", "重構", "整理", "清理", "美化", "完善",
    "自動", "盡量", "順便", "一併", "連帶",
]

# 不可逆操作:錯了不能回滾。這對應設計原則約束一(預設不可逆)與工程書 Q3。
# 命中這一組要把代價攤開,提醒使用者確認。
IRREVERSIBLE = [
    "刪除", "刪掉", "清掉", "清空", "移除", "砍掉", "重來", "重置", "還原到",
    "覆蓋", "蓋掉", "取代掉", "格式化",
    "rm ", "rm-", "drop table", "truncate", "delete from", "force push",
    "reset --hard", "--force", "-f ", "format", "wipe",
    "遷移", "migration", "改 schema", "改資料庫",
]

# 缺範圍的訊號:整句沒有出現任何具體標的(檔名、路徑、函式名、明確名詞)。
# 有這個訊號 + OPEN_SCOPE,飄移風險最高。
CONCRETE_HINT = re.compile(
    r"[\w.-]+\.(?:py|js|mjs|ts|tsx|md|json|html|css|sh|yml|yaml|sql|txt|go|rs|java|c|cpp)"
    r"|/[\w./-]+"                       # 路徑
    r"|`[^`]+`"                         # 反引號括起來的具體東西
    r"|\bdef \w+|\bclass \w+|\bfunction \w+"
)


def _find(text: str, words: list[str]) -> list[str]:
    """回傳 text 裡命中的詞。大小寫不敏感,中文照原樣。誤判往寬鬆:
    只回命中的詞,不推斷意圖,由呼叫端決定要不要出聲。"""
    low = text.lower()
    hit = []
    for w in words:
        if w.lower() in low:
            hit.append(w.strip())
    return hit


def consult(text: str) -> dict:
    """對一段還沒送出去的 prompt 意圖做術前診斷。回一個 Consult dict。

    這函式不改任何東西,不呼叫 AI,零依賴。純規則。可重跑,同輸入同輸出。
    """
    text = (text or "").strip()

    vague = _find(text, VAGUE_REFERENCE)
    open_scope = _find(text, OPEN_SCOPE)
    irrev = _find(text, IRREVERSIBLE)
    has_concrete = bool(CONCRETE_HINT.search(text))

    # bible Q-07 + RSK-4:誤判往寬鬆倒,範圍已清楚就別囉嗦。
    # 代名詞後面若緊跟具體名詞（這個詞、那個函式、這個檔案）,它就不是懸空的,
    # 不算模糊。用「代名詞 + 一到四個非空白字 + 名詞性結尾」粗略判定。
    # 這一條是 2026-09-11 拿真實 prompt 餵它、案例 3「這個詞」被誤判之後補的,
    # 而且它自己犯的正是它要防的 RSK-4。誤判方向:寧可漏報,不亂出聲。
    _ANCHORED = re.compile(
        "(?:" + "|".join(re.escape(w) for w in ["這個", "那個", "這些", "那些", "它"]) + ")"
        r"[一-鿿\w]{0,4}(?:詞|檔|檔案|函式|方法|欄位|參數|變數|常數|地方|行|段|模組|類|表|值|字|句)"
    )
    if _ANCHORED.search(text):
        vague = [w for w in vague if w not in ("這個", "那個", "這些", "那些", "它")]
    # 整句已經有明確標的時,單獨的代名詞不足以升 ADVISE（只是小提醒,不出聲）。
    if has_concrete:
        vague = [w for w in vague if w in ("看著辦", "隨便", "幫我弄", "幫我搞")]

    # scope_missing:用了開放範圍詞,又沒有任何具體標的。這是飄移最高風險。
    scope_missing = bool(open_scope) and not has_concrete

    findings = []
    if vague:
        findings.append({
            "kind": "vague_reference",
            "hit": vague,
            "why": "用了代名詞或含糊動詞但沒指明對象,AI 會自己猜,猜錯就做錯",
        })
    if scope_missing:
        findings.append({
            "kind": "open_scope",
            "hit": open_scope,
            "why": "範圍無界又沒指定具體標的,AI 會擴張解讀,可能動到你沒要動的東西",
        })
    if irrev:
        findings.append({
            "kind": "irreversible",
            "hit": irrev,
            "why": "這是不可逆操作,錯了不能回滾。動手前該先確認範圍與備份",
        })

    # verdict:預設 PASS。有 irreversible 升 CAUTION,其餘 findings 升 ADVISE。
    # 絕不 BLOCK（bible Q-07,擋不擋是使用者的權利）。
    if irrev:
        verdict = "CAUTION"
    elif findings:
        verdict = "ADVISE"
    else:
        verdict = "PASS"

    suggestion = _suggest(text, vague, open_scope, irrev, scope_missing)

    return {
        "verdict": verdict,
        "findings": findings,
        "suggestion": suggestion,
        "has_concrete_target": has_concrete,
        "raw_text": text,
    }


def _suggest(text, vague, open_scope, irrev, scope_missing) -> str:
    """給一句站在使用者立場的建議改寫。沒東西可建議就回空字串,不硬掰。"""
    parts = []
    if vague:
        parts.append("把「%s」換成具體的檔名或名稱,AI 就不用猜" % "、".join(vague[:2]))
    if scope_missing:
        parts.append("指定要動哪個檔案或哪個範圍,不然「%s」會被當成動全部"
                     % "、".join(open_scope[:2]))
    if irrev:
        parts.append("這一步不可逆,先講清楚動哪些、先備份、講好錯了怎麼回滾")
    return ";".join(parts)


def render(c: dict) -> str:
    """把 Consult 變成使用者看得懂的醫囑。工程書 5.5 節那三句結構:
    先承認(做得好),再引路(建議),站在使用者立場給理由。"""
    v = c["verdict"]
    if v == "PASS":
        return "醫囑:這句指令範圍清楚,可以送出。"
    head = "醫囑:不錯的開始," if c["raw_text"] else "醫囑:"
    lines = [head + "在送出之前有幾點會讓你的結果更精準有效。"]
    for f in c["findings"]:
        lines.append("  - %s。%s。" % ("、".join(f["hit"]), f["why"]))
    if c["suggestion"]:
        lines.append("建議:" + c["suggestion"] + "。")
    if v == "CAUTION":
        lines.append("這是不可逆的操作,決定權在你,我只把代價先攤開。")
    return "\n".join(lines)


def _read_input(argv) -> tuple[str, bool]:
    as_json = "--json" in argv
    args = [a for a in argv[1:] if a != "--json"]
    if args:
        return " ".join(args), as_json
    if not sys.stdin.isatty():
        return sys.stdin.read(), as_json
    return "", as_json


def main() -> int:
    text, as_json = _read_input(sys.argv)
    if not text.strip():
        sys.stderr.write("用法: python3 tools/consult.py \"你要下的指令\"\n")
        return 2
    c = consult(text)
    if as_json:
        print(json.dumps(c, ensure_ascii=False, indent=2))
    else:
        print(render(c))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
