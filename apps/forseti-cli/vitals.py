"""生命徵象。溫度、八個維度、目標距離。

這支取代先前那個把失敗率壓成一個 0 到 1 再染色的做法。

**為什麼不合成單一分數。** Five Mechanisms §6.8 雷一:所有批判都反對
合成單一風險分數，理由是合成會把可行動的維度壓平成不可行動的一個數字。
工程書 §22.2 講同一件事:單一溫度是 UX 摘要，內部每個維度要能分開查詢，
因為 context 壓力的解法跟證據過期、工具死結、協作反轉、計畫失效完全不同。

**為什麼溫度是體溫不是百分比。** bible.md Q-03 引 owner 原話:
Context 用到 950K/1M 但污染 5%、Truth 99%、Goal 對齊 100%，那是健康的;
Context 只有 300K 但污染 65%、Truth 72%、Goal 漂移 41%，那要立刻 Fork。
所以溫度量的是 Cognitive/Runtime degradation，不是 Context fullness。
公式出自工程書 §11.3，原文明寫這個映射是 calibration hypothesis 不是科學事實。

**為什麼目標距離用糾正算，不用工具失敗率算。** Vol1 憲法第 6 條:
活動不是進度，Task Progress 與 Goal Progress 必須分開。
Formal Spec §22.7 給了公式，而 FS-DET-FSD-001 明寫「東西真的做了」
不能讓這個分數下降 —— 執行成功與目標對齊是兩條獨立軸。
工具有沒有失敗是執行軸;有沒有偏離目標要看 owner 有沒有把我拉回來。
"""

from __future__ import annotations

import math
import re

# ── 糾正偵測 ──────────────────────────────────
# FS-MET-CB-001 與 FS-HQA-001 都明文禁止用語氣或髒話判定。
# 量的是 corrective labor:她有沒有必須指出遺漏、指出錯誤、強迫我去驗證。
#
# 這裡的詞表只收「指向我的行為」的句式,不收情緒詞。
# 「幹」「操」這種字一個都不在表裡,因為 owner 罵髒話的時候
# 工作可能是健康的(CT-027),而她語氣平靜的時候我可能正在闖禍。
_CORRECTION = re.compile(
    r"你(?:又|還|根本|從來|到底|怎麼)"
    r"|又來了|我(?:說過|講過|早就|不是說)"
    r"|(?:沒有|不是|不要|別)(?:做|讀|接|寫|給我)"
    r"|漏(?:掉|了)|錯了|不對|搞錯|重(?:做|寫|改)"
    r"|擅自|自作主張|誰叫你|我要的是"
    r"|為什麼(?:不|沒|要)")
# 她只是叫我往下走,不是在糾正。F06 §5 的 HumanContinueBurden 算這個。
_NUDGE = re.compile(r"^\s*(繼續|continue|go|下一步|嗯|好|ok|okay)\s*[。.!！]?\s*$", re.I)


#: 她按下打斷的那一刻。**這是 OBSERVED，不是我猜的** ——
#: 字串由系統寫進 transcript，不經過任何判斷。
_INTERRUPT = re.compile(r"^\s*\[Request interrupted by user")

#: 她在替我跑指令:貼終端機的提示字元與輸出回來。
#: 這不是糾正，是更重的東西 —— **她變成我的手。**
#: 2026-09-16 實測:第 286、287、288 輪連續三輪都是她貼 shell 輸出，
#: 而糾正偵測全部判 False，於是那一整段被算成「AI 自己回到中軸」。
_OPERATOR = re.compile(
    r"^\s*\w[\w.\-]*@[\w.\-]+\s+\S*\s*[%$#]\s"      # user@host ~ %
    r"|^\s*(?:zsh|bash):\s"
    r"|^\s*(?:Traceback \(most recent call last\)|command not found)")


def is_interrupt(text: str) -> bool:
    """她按了打斷。OBSERVED 級，100% 是她出手。"""
    return bool(_INTERRUPT.match((text or "").strip()))


def is_operator(text: str) -> bool:
    """她在替我操作。貼回來的終端輸出就是證據。

    **這比糾正更嚴重。** 糾正是她動口，這是她動手 ——
    `continuity` 的 human_continue_burden 量的是前者，
    這個量的是後者，而後者才是「我變成你的工人」的字面意思。
    """
    return bool(_OPERATOR.search((text or "").strip()))


def owner_stepped_in(row: dict) -> str:
    """她這一輪有沒有出手，以及用哪一種方式。

    **不用詞表猜，用可觀測的事實判。** 三種都是 OBSERVED:
    打斷是系統寫的、貼終端輸出是她真的貼了、糾正句式是她真的打了那些字。

    回空字串代表沒出手。
    """
    t = row.get("owner_text") or ""
    if is_interrupt(t):
        return "INTERRUPTED"
    if is_operator(t):
        return "OPERATED"
    if row.get("corrected_by_owner") or is_correction(t):
        return "CORRECTED"
    return ""


def is_correction(text: str) -> bool:
    """這一則是不是糾正。只看句式,不看情緒。"""
    t = (text or "").strip()
    if not t or _NUDGE.match(t):
        return False
    return bool(_CORRECTION.search(t))


def is_nudge(text: str) -> bool:
    return bool(_NUDGE.match((text or "").strip()))


# ── 目標支持度 ────────────────────────────────
# Formal Spec §7.8 的六級,原文的風險貢獻值照抄。
SUPPORT_RISK = {
    "DIRECT": 0.0,
    "SUPPORTING": 0.1,
    "EXPLORATORY": 0.25,
    "NEUTRAL": 0.50,
    "CONFLICTING": 1.0,
}


def classify_turn(row: dict, corrected: bool) -> str:
    """把一輪分類成六級之一。

    **這是 INFERRED 不是 OBSERVED。** Formal Spec §3.1 規定推論級證據
    必須附 confidence 且不得覆蓋 OBSERVED。這裡唯一屬於 OBSERVED 的
    輸入是「owner 在下一輪糾正了」這件事 —— 那是她真的打出來的字。

    UNKNOWN 不賦值,只降低覆蓋率(§7.8 原文)。
    """
    if corrected:
        return "CONFLICTING"
    if row.get("betrayals"):
        return "CONFLICTING"
    if row.get("overclaims"):
        return "CONFLICTING"
    dots = row.get("dots") or []
    if not dots:
        return "UNKNOWN"
    # 有讀有寫的輪子預設算支持。這是保守的方向:
    # bible Q-07 的原則是不確定的時候往 UNKNOWN 倒,不往定罪倒。
    return "SUPPORTING"


def goal_support(rows: list, window: int = 12) -> list:
    """逐輪算目標支持率與目標距離。§22.7

    GoalSupportRatio_t = weighted(DIRECT + SUPPORTING) / observable_action_weight
    GoalDistanceTrend  = slope(1 - GoalSupportRatio_t)

    回傳每一輪的 {n, support, distance, coverage, klass}。
    distance 就是線要往外移多遠:0 貼著中軸,1 推到最外面。
    """
    out: list = []
    klasses: list = []
    for i, r in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        corrected = bool(nxt and nxt.get("corrected_by_owner"))
        klasses.append(classify_turn(r, corrected))

    for i, r in enumerate(rows):
        lo = max(0, i - window + 1)
        seg = klasses[lo:i + 1]
        known = [k for k in seg if k != "UNKNOWN"]
        if not known:
            out.append({"n": r.get("n", i), "support": None, "distance": 0.0,
                        "coverage": 0.0, "klass": klasses[i]})
            continue
        good = sum(1 for k in known if k in ("DIRECT", "SUPPORTING"))
        support = good / len(known)
        out.append({
            "n": r.get("n", i),
            "support": round(support, 3),
            "distance": round(1.0 - support, 3),
            "coverage": round(len(known) / len(seg), 3),
            "klass": klasses[i],
        })
    return out


def distance_trend(points: list, k: int = 8) -> float:
    """目標距離的斜率。正值代表正在往外飄。§22.7"""
    vals = [p["distance"] for p in points[-k:] if p.get("support") is not None]
    if len(vals) < 3:
        return 0.0
    n = len(vals)
    mx = (n - 1) / 2
    my = sum(vals) / n
    num = sum((i - mx) * (v - my) for i, v in enumerate(vals))
    den = sum((i - mx) ** 2 for i in range(n))
    return round(num / den, 4) if den else 0.0


# ── 八個維度 ──────────────────────────────────
# 工程書 §22.1 的八個,名字與意義照原文。
DIMENSIONS = (
    ("context", "脈絡"),
    ("runtime", "工具與執行"),
    ("progress", "進度"),
    ("collab", "協作"),
    ("evidence", "證據"),
    ("strategy", "策略"),
    ("resource", "資源"),
    ("continuity", "連續性"),
)


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def dimensions(rows: list, snap: dict, gs: list) -> dict:
    """八個維度各自的分數與證據。每一個都要能單獨查。

    沒有資料的維度回 None 並標 coverage 0,不猜。
    Bragi 架構原則 P-01:對沒檢查過的東西保持安靜,
    使用者會把安靜讀成背書。所以這裡不存在「沒有標記」的維度。
    """
    n = len(rows) or 1
    recent = rows[-20:] if len(rows) > 20 else rows

    dots = [d for r in recent for d in (r.get("dots") or [])]
    failed = sum(1 for d in dots if d.get("failed"))
    corrections = sum(1 for r in recent if r.get("corrected_by_owner"))
    nudges = sum(1 for r in recent if r.get("nudge_by_owner"))
    betrayals = sum(len(r.get("betrayals") or []) for r in recent)
    overclaims = sum(len(r.get("overclaims") or []) for r in recent)
    stalls = sum(1 for r in recent if r.get("stall"))
    wrote = sum(1 for d in dots if d.get("kind") == "write")

    out: dict = {}

    def put(key, score, evidence, coverage=1.0):
        out[key] = {"score": None if score is None else round(_clamp(score), 3),
                    "evidence": evidence, "coverage": coverage}

    ctx = snap.get("context") or {}
    used = ctx.get("used_pct")
    # §10 明寫單一 token 百分比解釋不了任何事,所以它只是脈絡維度的
    # 其中一個訊號,而且單獨列出來,不參與溫度加權。
    put("context", (used / 100.0 * 0.4) if isinstance(used, (int, float)) else None,
        f"壓縮 {ctx.get('compactions', 0)} 次" if ctx else "沒有脈絡樣本",
        1.0 if ctx else 0.0)

    put("runtime", failed / max(len(dots), 1),
        f"{len(dots)} 個動作，{failed} 個失敗")

    put("progress", 1.0 - min(1.0, wrote / max(len(recent), 1)),
        f"最近 {len(recent)} 輪有 {wrote} 次寫入")

    put("collab", (corrections + nudges) / max(len(recent), 1),
        f"糾正 {corrections} 次，催促 {nudges} 次")

    put("evidence", (betrayals + overclaims) / max(len(recent), 1),
        f"白點 {betrayals}，說了沒做 {overclaims}")

    d = gs[-1] if gs else None
    put("strategy", d["distance"] if d and d.get("support") is not None else None,
        f"目標支持率 {d['support']:.0%}" if d and d.get("support") is not None
        else "還算不出目標支持率",
        d["coverage"] if d else 0.0)

    put("resource", stalls / max(len(recent), 1),
        f"{stalls} 輪沒有動作")

    led = snap.get("ledger") or {}
    age = led.get("age_hours")
    put("continuity", min(1.0, age / 24.0) if isinstance(age, (int, float)) else None,
        f"帳本 {age:.1f} 小時前更新" if isinstance(age, (int, float)) else "讀不到帳本",
        1.0 if isinstance(age, (int, float)) else 0.0)
    return out


def temperature(dims: dict) -> dict:
    """體溫。工程書 §11.3。

    instability_score = weighted_normalized_features
    temperature = 36.3 + 5.0 * sigmoid((instability - center) / scale)

    **這個映射是 calibration hypothesis,不是科學事實**,原文如此。
    所以回傳一定帶 coverage:低覆蓋率的高溫不能裝作確定(FS-RSK-001)。
    """
    # 權重。目標與證據最重,因為那是「有沒有走偏」與「講的話算不算數」;
    # 脈絡容量最輕,理由見 bible Q-03。
    w = {"strategy": .22, "evidence": .20, "collab": .16, "progress": .14,
         "runtime": .12, "resource": .08, "continuity": .05, "context": .03}
    num = den = 0.0
    for k, weight in w.items():
        d = dims.get(k) or {}
        s, c = d.get("score"), d.get("coverage", 0.0)
        if s is None or not c:
            continue
        num += weight * s * c
        den += weight * c
    if not den:
        return {"c": None, "band": "UNKNOWN", "coverage": 0.0,
                "why": "沒有足夠的證據算溫度"}
    inst = num / den
    t = 36.3 + 5.0 / (1 + math.exp(-(inst - 0.35) / 0.18))
    band = ("NORMAL" if t < 37.0 else "WATCH" if t < 38.0
            else "DEGRADED" if t < 39.0 else "CRITICAL")
    top = max(((k, (dims.get(k) or {}).get("score") or 0) for k in w),
              key=lambda kv: kv[1] * w[kv[0]])
    return {"c": round(t, 1), "band": band,
            "coverage": round(den / sum(w.values()), 3),
            "why": dict(DIMENSIONS)[top[0]], "why_key": top[0]}


def progress_layers(rows: list) -> dict:
    """Activity / Task / Goal 三層,永遠分開。§22.6 FS-DET-FPR-001

    FS-DET-FPR-002:spawn 的 workflow、很大的 transcript、成功的 detector、
    排定的 wakeup,預設帶零 GoalProgress。
    """
    dots = [d for r in rows for d in (r.get("dots") or [])]
    wrote = sum(1 for d in dots if d.get("kind") == "write")
    return {
        "activity": len(dots),
        "activity_note": "工具呼叫與訊息。規格明寫這永遠不是進度的證據",
        "task": wrote,
        "task_note": "實際寫入檔案的次數。這是 durable state 的下界",
        "goal": None,
        "goal_note": "目標進度需要 owner 的驗收條件才算得出來，現在沒有，所以標未知不填零",
    }


# ── 三張卡片 ──────────────────────────────────
# bible.md I-04（事前消歧勝過事後糾正），owner 原話:
#
#     累積這些他跟 AI 的互動，長期積累可以反饋給用戶，
#     讓用戶在面對選擇的時候，能用選擇比方說三個小卡片，
#     選其中一張直接成為給 AI 的 Prompt。
#
# 為什麼是三張而不是一句:事前給三個選項不吵，事後跳警告才吵。
# 這同時解掉 I-01 的介入時機問題跟「會不會很吵」的問題。
#
# 每張卡片要能展開五件事,出自 Vol3 §12 Recommendation Protocol 原文:
# Why now? Which evidence? Similar historical cases? Confidence?
# What if ignored? 少一項就退回成「另一個不可信的 AI 意見」(白皮書 §17.2)。

def cards(snap: dict, advice: dict | None = None) -> list:
    """最多三張。每一張都是可以直接貼給 AI 的一句話。

    **語氣是 proposal 不是裁決**(Vol3 §12)。所以卡片的標題寫的是
    「你可以叫他做什麼」，不是「你必須」。
    """
    out: list = []
    dims = snap.get("dims") or {}
    rows = snap.get("rows") or []
    temp = snap.get("temp") or {}

    def card(key, title, say, why_now, evidence, confidence, if_ignored):
        out.append({"key": key, "title": title, "say": say,
                    "why_now": why_now, "evidence": evidence,
                    "confidence": confidence, "if_ignored": if_ignored})

    # 一、根基。必讀沒讀完的時候這張永遠排第一,
    #     因為照著沒讀完的規格做，做得再順也是錯的。
    sp = snap.get("spec") or {}
    if sp.get("has") and not sp.get("ok"):
        miss = [r["name"] for r in (sp.get("rows") or [])
                if r.get("state") != "讀完"][:3]
        card("spec",
             "先把沒讀完的文件讀完再往下做",
             "在繼續做之前，先把必讀文件一塊一塊讀完，讀完一塊就記一塊，"
             "有疑問的地方停下來問我，不要邊讀邊寫程式。",
             f"必讀 {sp.get('total')} 份只讀完 {sp.get('full')} 份",
             "、".join(miss) if miss else "",
             "高　這是檔案狀態，不是推論",
             "照著沒讀完的規格做，後面每一步都建立在可能錯的前提上")

    # 二、指向某一輪的觀察。這一類的價值在於它指得出「第幾輪」,
    #     owner 可以直接點過去看原文。§16.3 的正例就是這個形狀:
    #     不要說「AI 看起來不太健康」,要說「第 262 輪說執行了但沒有動作」。
    if advice and advice.get("say"):
        card("turn", advice.get("text") or "有一輪的宣稱跟證據對不上",
             advice["say"],
             advice.get("why") or "",
             f"第 {advice.get('n')} 輪" if advice.get("n") else "",
             "高　這是從事件流直接數出來的",
             "說了沒做的那一輪會被當成已完成，後面都建立在它上面")
        out[-1]["n"] = advice.get("n") or 0

    # 三、目標距離。這張要的是 owner 裁定「這是演化還是偏離」——
    #     Vol1 §2.1 明寫偏離舊 North Star 不等於錯，可能是有意識的演化，
    #     平台要提示而不是直接判 drift。
    g = (rows[-1].get("goal") if rows else None) or {}
    trend = snap.get("goal_trend") or 0
    if g.get("support") is not None and (g["support"] < 0.85 or trend > 0.005):
        card("goal",
             "問他現在做的事跟你的目標還有沒有交集",
             "停一下，用一句話說出你現在的目標是什麼、這一步怎麼推進它、"
             "以及有哪些我的糾正已經讓你原本的計畫失效了。",
             f"目標支持率 {g['support']:.0%}"
             + ("，而且趨勢在往外" if trend > 0.005 else ""),
             f"最近 {snap.get('corrections', 0)} 輪裡我糾正過你",
             f"中　覆蓋率 {g.get('coverage', 0):.0%}，這是推論不是直接觀察",
             "每一步都可辯護，但累積起來框架已經被換掉（FP-17）")

    # 四、溫度最高的那個維度。只給一張,不給八張 ——
    #     FS-ALR-001:一百個 detector hit 可以只對應一個 root incident。
    hot = None
    for k, d in dims.items():
        if d.get("score") is None:
            continue
        if hot is None or d["score"] > dims[hot]["score"]:
            hot = k
    SAY = {
        "evidence": "把你剛才說已經做好的每一件事，各附一條我可以自己跑的驗證指令。",
        "collab": "不要等我一句一句指出缺什麼。你自己先跑一次完整檢查，"
                  "把沒做完的列出來再給我。",
        "runtime": "先停掉現在這個做法。講清楚失敗的原因是什麼，"
                   "換一條路之前先說你為什麼認為新的那條會成功。",
        "progress": "這一輪除了文字之外，你留下了什麼可以被我打開來看的東西。",
        "resource": "你卡在哪裡。如果在等什麼，先確認那個東西還活著。",
        "strategy": "你現在的策略已經被哪些證據推翻了。推翻了就重新規劃，不要修補。",
        "continuity": "先把現在的狀態寫進檔案，不要只留在對話裡。",
        "context": "在被壓縮之前，先把還沒落地的決定寫成檔案。",
    }
    NM = {"context": "脈絡", "runtime": "工具", "progress": "進度",
          "collab": "協作", "evidence": "證據", "strategy": "策略",
          "resource": "資源", "continuity": "連續性"}
    if hot and dims[hot]["score"] >= 0.15 and len(out) < 3:
        card(hot, f"{NM[hot]}這一項現在最需要處理", SAY.get(hot, ""),
             f"{NM[hot]}是八個維度裡分數最高的",
             dims[hot].get("evidence", ""),
             f"中　這一項的證據覆蓋率 {dims[hot].get('coverage', 0):.0%}",
             "溫度會繼續往上，而且原因會被後面的事蓋掉")

    # 什麼都沒有的時候不編一張出來。
    # 白皮書 §17.2:建議必須引用觸發它的觀測模式，
    # 否則就是另一個不可信的 AI 意見。
    if not out and temp.get("c") is not None:
        # 措辭照 WIDGET_SPEC §19.2:最好的情況也只能說「沒有查到問題」。
        # 查不到不等於沒有，而一個講得太滿的綠燈正是這整個專案要防的東西。
        card("ok", "沒有查到需要你介入的事",
             "",
             f"體溫 {temp['c']}，八個維度都在基準內",
             f"證據覆蓋率只有 {temp.get('coverage', 0):.0%}，"
             "沒有覆蓋到的部分這裡答不出來",
             "中　這是「沒查到」不是「沒有」",
             "無法判斷。沒有查到不代表沒有發生")
    return out[:3]


# ── 偏離北極星的警示 ──────────────────────────
# WIDGET_SPEC §5.4。三個條件同時成立才跳:
#
#   一、使用者一路順著 AI 的回覆往下走
#   二、沒有給出不同的指令去影響方向
#   三、而 AI 偏離了北極星
#
# **第二條是關鍵。** 如果是使用者自己換了方向，那是斷點不是偏離。
# 這條同時是 FS-GOL-002 的要求:owner 明確改變需求時必須產生
# OWNER_GOAL_CHANGE，而不是把偏離舊目標算成 agent drift。
#
# 規格說按下確認會自動送出 prompt。**做不到，不假裝。**
# §26.3 實測過 deep link 只到 session 這一層，跳不到某一輪，
# 所以介面上給的是「複製這段給他」。

MIN_RUN = 5          # 連續幾輪沒有被糾正才算「她一路順著走」
MIN_DISTANCE = 0.30  # 期末目標距離要超過多少才算偏離


def _exclusions(gate: dict | None) -> list:
    """FS-DRF-001 的 exclusions_checked。每一條都要說得出根據。

    回的是字串陣列，因為畫面 `app.js` 用頓號把它串起來顯示。
    """
    out = ["OWNER_GOAL_CHANGE 未偵測到", "這段期間沒有糾正"]
    if gate is None:
        out.append("GAC 沒有接上，依 FS-GOL-001 不出 CONFIRMED")
        return out
    if not gate.get("ok"):
        out.append(f"GAC 跑不起來（{gate.get('note') or '原因不明'}），不出 CONFIRMED")
        return out
    g = gate.get("gac")
    if g is None:
        miss = "、".join(m.get("factor", "?") for m in gate.get("missing_factors") or [])
        out.append(f"GAC 算不出來，缺 {miss or '未知因子'}，依 FS-GOL-001 不出 CONFIRMED")
    elif not gate.get("may_confirm_drift"):
        out.append(f"GAC {g}，未達 §6.2 的 CONFIRMED 門檻 0.80，不出 CONFIRMED")
    else:
        # GAC 這一關過了，其餘四條還沒實作。不准因為過了一關就升級。
        out.append(f"GAC {g} 已達門檻，但 §6.2 另外四條（GAR、deterministic "
                   f"contradiction、correction 後仍持續、兩個獨立證據維度）"
                   f"尚未實作，仍不出 CONFIRMED")
    if gate.get("thresholds_uncalibrated"):
        out.append("門檻為 CALIBRATION-CANDIDATE，未經真實語料校準")
    return out


def drift_alerts(rows: list, gate: dict | None = None) -> list:
    """找出符合三條件的區段。回傳每段的起訖與證據。

    **這是 INFERRED。** Formal Spec FS-DRF-001 要求 drift classifier
    一定要輸出 state + confidence + evidence_refs + exclusions_checked，
    所以每一筆都帶 `excluded`(檢查過哪些排除條件)。

    FS-GOL-001 規定 GAC < 0.60 不得輸出 CONFIRMED_DRIFT。

    `gate` 是 `goalgate.gate()` 的回傳（2026-09-15 接上）。在這之前
    `excluded` 裡寫著一句寫死的「GAC 算不出來」，那句話沒有真的算過，
    也說不出缺什麼。接上之後 GAC 是實際跑 `src/goalanchor.js` 算的，
    算不出來時會指名缺哪個因子。

    **GAC 過了也不代表出 CONFIRMED。** §6.2 的 CONFIRMED 還要 GAR ≥0.70、
    至少一個 deterministic/owner-confirmed contradiction、correction 之後
    仍持續、至少兩個獨立證據維度。那四條目前都沒有實作，所以現在最高
    仍然是 SUSPECTED，差別在於理由是算出來的而不是寫死的。
    """
    out: list = []
    run_start = None
    for i, r in enumerate(rows):
        g = r.get("goal") or {}
        corrected = bool(r.get("corrected_by_owner"))
        changed = bool(r.get("owner_changed_goal"))   # 保留欄位，目前沒人填

        if corrected or changed:
            run_start = None          # 她出手了，這一段不算「她沒動」
            continue
        if run_start is None:
            run_start = i

        n = i - run_start + 1
        d = g.get("distance")
        if d is None or n < MIN_RUN or d < MIN_DISTANCE:
            continue

        # 這一段裡距離有沒有在上升。只有「越走越遠」才算偏離,
        # 一路持平的高距離可能只是這個任務本來就難分類。
        first = (rows[run_start].get("goal") or {}).get("distance")
        if first is None or d <= first + 0.05:
            continue

        # 同一段只報一次,報最尾端那一輪。FS-ALR-002 要求
        # 同一個 root incident 在狀態沒變時不得重複彈。
        if out and out[-1]["run_start"] == run_start:
            out[-1].update(n=r.get("n"), distance=d, turns=n)
            continue

        out.append({
            "n": r.get("n"),
            "run_start": run_start,
            "from_n": rows[run_start].get("n"),
            "turns": n,
            "distance": round(d, 3),
            "from_distance": round(first, 3),
            "state": "SUSPECTED_DRIFT",
            "confidence": round(min(0.75, (g.get("coverage") or 0) * 0.9), 2),
            "excluded": _exclusions(gate),
            # FS-DRF-001 要求 drift classifier 一定要輸出 goal_anchor_ref。
            "goal_anchor_ref": (gate or {}).get("goal_state"),
            "gac": (gate or {}).get("gac"),
        })
    return out


def drift_prompt(alert: dict, north_star: str = "") -> str:
    """紫點按下去要複製的那段話。§5.4

    規格要求四件:重新告訴 AI 北極星是什麼、偏離到哪裡、要它自我審計、
    放棄做錯的功能往對的方向重新開發。

    **「偏離到哪裡」必須具體。** §5.4 原文:如果送出去的是
    「你偏離了目標，請校正」，AI 會回一段很漂亮的自我檢討然後繼續做錯的事，
    那正是 FS-CHL-001 說的 yes/no self-report 不具驗證力。
    所以這段話帶上輪次區間與實際數字。
    """
    ns = north_star or "讓 AI 的工作狀態可觀測、可驗證、可控制、可復原"
    return (
        f"停一下。從第 {alert['from_n']} 輪到第 {alert['n']} 輪，"
        f"連續 {alert['turns']} 輪我沒有糾正你，而你跟目標的距離從 "
        f"{alert['from_distance']} 升到 {alert['distance']}。\n\n"
        f"北極星是：{ns}\n\n"
        "請做四件事，不要先解釋：\n"
        "一、用一句話說出你現在在做什麼，以及它怎麼推進上面那句北極星。\n"
        "二、列出這幾輪裡你做的事情當中，哪些跟北極星沒有交集。\n"
        "三、指出你的哪一個假設或計畫已經被推翻了卻還在驅動後續動作。\n"
        "四、把沒有交集的那部分停掉，說出下一步要做什麼，"
        "以及我怎麼驗證它真的推進了北極星。"
    )


# ── Health Curve ──────────────────────────────────
# §16.1 八視圖之一。完成的定義:可靠度從哪一輪開始退化,
# 一條隨時間的曲線,而不只是「現在幾度」。
#
# **這裡沒有新演算法。** 曲線上每一點都是同一個 `dimensions()` 加
# 同一個 `temperature()`,只是把輸入從「全部的輪」換成「到那一輪為止」。
# 之所以要強調,是因為 ROADMAP 那條「不自己編算法填空」的禁令
# (§8.3)正是這個模組最容易踩的:畫一條線太想要它平滑好看。

#: 曲線最少要有這麼多輪才算得出第一個點。
#: `dimensions()` 內部取最後 20 輪,樣本再少下去分母小到會亂跳。
#: **這是設定值不是規格值**,規格沒給起算輪數。
CURVE_MIN = 8

#: 一條線上最多幾個點。超過就等距抽樣。
CURVE_MAX_POINTS = 60

#: 逐輪重算時必須拿掉的兩個維度。
#:
#: `context` 來自 `snap["context"]`、`continuity` 來自 `snap["ledger"]`,
#: 兩個都是「現在這一刻」的快照,不隨輪次變。把它們留著,
#: 整條線會被同一個常數平移,看起來像歷史其實不是 ——
#: 那正是 FS-RSK-001 禁止的「把不確定的東西畫成確定」。
#:
#: `temperature()` 本來就會跳過 coverage 0 的維度,這裡不改它的算法,
#: 只是把這兩維的 coverage 設 0。所以曲線的覆蓋率一定低於當前溫度,
#: 每個點都帶著自己的 coverage,看得出來。
CURVE_EXCLUDED = ("context", "continuity")


def _curve_idx(n: int, k: int) -> list:
    """等距取樣的切點。一定包含最後一輪,因為那是「現在」。"""
    lo, hi = CURVE_MIN - 1, n - 1
    if hi <= lo:
        return [hi]
    span = hi - lo
    k = max(2, min(int(k), span + 1))
    return sorted({lo + round(span * j / (k - 1)) for j in range(k)})


def curve(rows: list, snap: dict, gs: list,
          max_points: int = CURVE_MAX_POINTS) -> dict:
    """體溫隨輪次的曲線。

    回傳每一點的 {n, t, band, coverage, why},外加這條線的形狀。
    **算不出來就說算不出來**,不補點、不內插、不平滑。
    """
    rows = rows or []
    gs = gs or []
    if len(rows) < CURVE_MIN:
        return {"has": False, "points": [],
                "excluded": list(CURVE_EXCLUDED),
                "why": f"只有 {len(rows)} 輪，不足 {CURVE_MIN} 輪算不出一個點"}

    pts: list = []
    for i in _curve_idx(len(rows), max_points):
        dims = dimensions(rows[:i + 1], snap, gs[:i + 1])
        for k in CURVE_EXCLUDED:
            if k in dims:
                dims[k] = {"score": None, "coverage": 0.0,
                           "evidence": "逐輪重算不出來，來源是當下的快照"}
        t = temperature(dims)
        if t.get("c") is None:
            continue
        pts.append({"i": i, "n": rows[i].get("n", i),
                    "t": t["c"], "band": t["band"],
                    "coverage": t["coverage"],
                    "why": t.get("why"), "why_key": t.get("why_key")})

    if not pts:
        return {"has": False, "points": [],
                "excluded": list(CURVE_EXCLUDED),
                "why": f"{len(rows)} 輪都算不出溫度，六個維度全部沒有覆蓋率"}

    hottest = max(pts, key=lambda p: p["t"])
    return {"has": True, "points": pts,
            "excluded": list(CURVE_EXCLUDED),
            "first": pts[0], "last": pts[-1],
            "delta": round(pts[-1]["t"] - pts[0]["t"], 1),
            "hottest": hottest,
            "rising_since": _rising_since(pts),
            "why": None}


def _rising_since(pts: list) -> dict | None:
    """最後這一段連續沒有下降的起點。**這是曲線的形狀，不是一個新指標。**

    定義只有一句:從最後一點往回走,只要前一點不比後一點高就繼續,
    停在走不動的地方。走不到兩點以上就回 None。

    **這個定義是我定的,規格沒給。** 規格 §16.1 只要求
    「可靠度從哪一輪開始退化」,沒有定義什麼叫開始。
    所以這裡刻意選一個一句話講得完、看著圖就能自己驗的定義,
    而不是斜率門檻或滑動迴歸 —— 那種東西會生出一個沒人能查的數字。
    """
    if len(pts) < 2:
        return None
    j = len(pts) - 1
    while j > 0 and pts[j - 1]["t"] <= pts[j]["t"]:
        j -= 1
    rise = round(pts[-1]["t"] - pts[j]["t"], 1)
    # **持平不是退化。** 第一版用 `<=` 往回走(持平不該打斷一段上升),
    # 但沒有檢查總量,於是一條末端完全平的線被回報成
    # 「從第 49 輪開始退化，升幅 0.0 度」。測試當場抓到。
    # 一個升幅 0 的退化起點就是在說謊,寧可回 None。
    if j == len(pts) - 1 or rise <= 0:
        return None
    return {"from": pts[j], "points": len(pts) - j, "rise": rise}
