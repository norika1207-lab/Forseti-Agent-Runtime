#!/usr/bin/env python3
"""Context Sufficiency Gate。沒證明理解之前只能讀。v5.0 §17.3 / §19.2 / §39

規格原文（v5.0 §17.3，`docs/sources/` 底下那份第 488 行起）：

    A successor may be read-only until it demonstrates understanding of
    the current objective, accepted decisions, unresolved unknowns,
    last-good state, and external-effect boundaries. High-risk workflows
    can require a configured comprehension threshold before write or
    commit privileges are granted.

那一句列了五樣東西，`DIMENSIONS` 就是那五樣，順序照原文，沒有增減。
§19.2 另外寫 `Read-only default for newly attached agents on high-risk
projects`，所以「預設不能寫」是規格立場，不是我加的嚴格。

## 這支解的是 B-08

`BLOCKERS.md` 的 B-08：`forseti gate takeover` 只列題目不驗答案。
而 `REQUIRED_READING.md` 第 59 行說得更直白：level 5 是我說我讀完了，
level 6 是有人考過我，**因為沒有人在驗答案，任何文件現在最高只能到 5**。

`blockread.py` 早就有 `quiz()` 跟 `grade()`，題目從原文抽。
缺的一直只是把它接成一道真的擋得住的門。

## §39 的反錨定，做到哪裡、做不到哪裡

§39 第 2 步：`Do not expose the canonical current-answer artifact yet`。
所以考卷裡**不存答案明文**，只存 `key_sha`（正規化後的 sha256）
與 `key_len`。批改用滑動視窗比 hash，比對語意跟 `blockread.grade`
一樣是「原文那段有沒有出現在作答裡」，只是不必把原文那段寫下來。

**做不到的部分要講清楚：這防的是錨定，不是作弊。** 一個讀得到
`.forseti/` 的 session 也讀得到出題的原檔，題目又標了行號，
它可以直接去翻那一行。要真的防作弊，答案必須存在受測者拿不到的
地方，那是另一層架構，現在沒有。**不假裝它擋得住。**

§39 完整的七步（獨立推導 → 存下推導 → 才揭曉正典 → 把差異分成
四類 → 和解之後才給權限）這一支只做了第 2 步跟第 7 步。
中間那幾步要有「正典答案」這個物件才談得上，那個物件還不存在。

## 題目從哪裡來

每個維度綁一份來源檔，題目用 `blockread.quiz()` 從那份原文抽。
**題目不是生成的**，這是整件事能不能算數的關鍵：自己出的題只會考
自己記得的部分，而記得的部分正是不用考的部分。

`last_good` 那一維不一樣，它的正典是 `checkpoints.jsonl` 裡被標成
last_good 的那一筆，不是一份文件。沒有人標過的時候它沒有題目可出，
**那時候就誠實記成 `NO_SOURCE`，不編一題填上去。**

## 為什麼缺維度不是直接擋死

五維度裡只要有一維沒有來源，這道門就永遠開不了 ——
而 §18 寫著 `A noisy Forseti becomes another failure source`，
預設姿態是 OBSERVE 99% / INTERRUPT 1%。所以判決分三種：

    PASS          五維都有題，而且答對率過門檻
    PASS_PARTIAL  有題的都過了，但有維度沒有來源（紀錄裡列出是哪幾維）
    FAIL          任何一個有題的維度沒過

`PASS_PARTIAL` 拿得到寫入權限，但它跟 `PASS` 在帳本裡是兩種東西，
查得出來這一次到底有幾維沒驗到。

## 門檻是設定值，不是我定的常數

§17.3 的原文是 `a configured comprehension threshold`，所以它必須
可設定。`config.json` 的 `sufficiency_threshold` 是那個設定。
**預設 0.8 是 CALIBRATION-CANDIDATE**，規格沒有給數字，
這個值沒有用真實語料校準過，不要當成規格要求。

## 這一版不強制

算得出狀態、看得到、CLI 考得了，但沒有任何地方會因為 FAIL 就擋住寫入。
要強制是 owner 的決定（她為 `enforce_declarations` 明確說過要擋，
那是她開的口）。`config.json` 的 `sufficiency_enforce` 預設 false。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LOG_NAME = "sufficiency.jsonl"

#: §17.3 那一句列的五樣，順序照原文。
#: (key, 原文的說法, 中文, 預設來源)
DIMENSIONS = (
    ("objective", "current objective", "現在的目標",
     ".forseti/NORTH_STAR.md"),
    ("decisions", "accepted decisions", "已接受的決策",
     ".forseti/DECISION_LEDGER.md"),
    ("unknowns", "unresolved unknowns", "未解決的未知",
     ".forseti/BLOCKERS.md"),
    ("last_good", "last-good state", "最後已知良好狀態",
     None),                      # 正典是 checkpoint，不是文件
    ("effects", "external-effect boundaries", "外部效果的邊界",
     "bible.md"),
)

#: 預設門檻。**CALIBRATION-CANDIDATE**，規格只說「configured」，沒給數字。
DEFAULT_THRESHOLD = 0.8
#: 每個維度抽幾題。同上，不是規格值。
DEFAULT_PER_DIM = 2
#: 答案短於這個長度的題目不收。**這是我定的，不是規格值。**
#:
#: 理由是這種題驗不出理解：答案只有一兩個字的時候，一段稍長的作答
#: 很容易剛好含到它，答對跟讀懂沒有關係。`blockread.grade` 的
#: 子字串比對有同樣的弱點，這裡不是修好它，是不出那種題。
MIN_KEY_LEN = 3

_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    """比對前的正規化。只去空白，不做同義詞、不做模糊比對。

    `blockread.grade` 的註解寫過理由：語意相似度會讓「差不多對」通過，
    而規格這種東西差不多對就是錯。這裡唯一放寬的是空白，
    因為換行與全形空格的差異不是理解的差異。
    """
    return _WS.sub("", s or "").replace("　", "")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _cfg(root: Path) -> dict:
    p = Path(root) / ".forseti" / "config.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def threshold(root: Path = REPO) -> float:
    v = _cfg(root).get("sufficiency_threshold", DEFAULT_THRESHOLD)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD
    return f if 0.0 < f <= 1.0 else DEFAULT_THRESHOLD


def enforced(root: Path = REPO) -> bool:
    """這道門現在會不會真的擋人。預設不會。"""
    return bool(_cfg(root).get("sufficiency_enforce", False))


def source_of(dim: str, root: Path = REPO) -> Path | None:
    """某個維度的來源檔。config 可以改，改了要自己負責對不對。"""
    over = (_cfg(root).get("sufficiency_sources") or {}).get(dim)
    if over:
        p = Path(root) / over
        return p if p.is_file() else None
    for key, _en, _zh, default in DIMENSIONS:
        if key == dim:
            if not default:
                return None
            p = Path(root) / default
            return p if p.is_file() else None
    return None


def _last_good(root: Path) -> dict | None:
    """被標成 last_good 的那一筆 checkpoint。沒有就是沒有。

    **判定借 `checkpoint.load()`，不自己讀檔。** 這個專案已經有五組
    「同名不同義」（`events`、`temperature`、`rescue`、lineage 邊型、
    心跳），全部來自兩份實作各自長大。什麼叫 last_good 只能有一份定義。

    **但範圍刻意不一樣：`checkpoint.last_good()` 只看同一條線的，
    這裡跨所有線取最新。** 理由是 §17.3 的受測者是 successor ——
    一條剛接手的線自己沒有任何 checkpoint，照 per-session 過濾
    它永遠拿不到 last-good state，而那正是它最需要知道的一樣。
    """
    import checkpoint as CP

    rows = [r for r in CP.load(path=Path(root) / ".forseti" / "checkpoints.jsonl")
            if r.get("last_good")]
    return max(rows, key=lambda r: r.get("at", 0)) if rows else None


def _q_from_checkpoint(cp: dict, limit: int) -> list[dict]:
    """從 last_good checkpoint 出題。答案是它存下來的字，不是我的話。

    checkpoint 存的四樣（goal / decisions / unknowns / verified）
    正好覆蓋 §17.3 前四樣裡的三樣，所以這裡只出 last-good 專屬的題：
    那一刻的目標是什麼、那一刻已接受了哪些決策。
    """
    out: list[dict] = []
    n = cp.get("n")
    goal = (cp.get("goal") or "").strip()
    if goal:
        out.append({
            "kind": "正典",
            "q": f"最後已知良好的那一刻（第 {n} 輪）記下的目標是什麼？",
            "key": goal[:40],
            "line": n,
        })
    for d in (cp.get("decisions") or [])[:limit]:
        d = (d or "").strip()
        if len(d) >= 4:
            out.append({
                "kind": "正典",
                "q": f"最後已知良好那一刻（第 {n} 輪）記下的一項已接受決策，"
                     f"開頭是「{d[:6]}」，整句是什麼？",
                "key": d[:30],
                "line": n,
            })
    return out[:limit]


def _spread(pool: list, k: int) -> list:
    """從整份文件的題庫裡等距取 k 題。

    等距不是隨機：同一份文件出的卷每次都一樣，重考才有意義 ——
    每次抽不同的題，考不過的人多考幾次就會過，那不是門是轉盤。
    """
    if len(pool) <= k:
        return list(pool)
    step = len(pool) / float(k)
    return [pool[min(len(pool) - 1, int(i * step))] for i in range(k)]


def compose(root: Path = REPO, *, per_dim: int | None = None) -> dict:
    """出一份考卷。題目不含答案明文（§39 第 2 步）。

    回的 `dims` 會說每一維是有題、沒來源、還是來源裡抽不出題。
    三種狀態不能混成一種，因為它們要做的事不一樣：沒來源是專案缺東西，
    抽不出題是出題器的能力邊界。
    """
    import blockread as BR

    root = Path(root)
    k = per_dim or int(_cfg(root).get("sufficiency_per_dim", DEFAULT_PER_DIM))
    questions: list[dict] = []
    dims: dict[str, dict] = {}

    for key, en, zh, _default in DIMENSIONS:
        raw: list[dict] = []
        src_label = ""
        if key == "last_good":
            cp = _last_good(root)
            if cp is None:
                dims[key] = {"en": en, "zh": zh, "state": "NO_SOURCE",
                             "source": "",
                             "why": "沒有任何 checkpoint 被標成 last_good。"
                                    "系統不自己挑，要有人按「標記這裡是好的」"}
                continue
            src_label = f"checkpoints.jsonl @ {cp.get('id') or cp.get('n')}"
            raw = _q_from_checkpoint(cp, k)
        else:
            p = source_of(key, root)
            if p is None:
                dims[key] = {"en": en, "zh": zh, "state": "NO_SOURCE",
                             "source": "",
                             "why": "找不到這一維的來源檔"}
                continue
            src_label = str(p.relative_to(root)) if str(p).startswith(str(root)) \
                else str(p)
            # 全部區塊都出題，再跨區塊等距取樣。
            #
            # **不可以抽滿就停。** 抽滿就停等於只考文件開頭那幾塊，
            # 而 `REQUIRED_READING.md` 記的她的原話正是
            # 「只挑標題重點看，掃描前幾排字後面就略過」——
            # 一份只考前面的考卷，考的正是那個壞習慣做得到的範圍。
            pool = [q for b in BR.split(p) for q in BR.quiz(p, b, limit=k)]
            raw = _spread(pool, k)

        raw = [q for q in raw
               if len(_norm(q.get("key") or "")) >= MIN_KEY_LEN][:k]
        if not raw:
            dims[key] = {"en": en, "zh": zh, "state": "NO_QUESTION",
                         "source": src_label,
                         "why": "來源在，但抽不出可考的題目"}
            continue

        for i, q in enumerate(raw, 1):
            nk = _norm(q.get("key") or "")
            if not nk:
                continue
            questions.append({
                "qid": f"{key}-{i}",
                "dim": key,
                "kind": q.get("kind", ""),
                "q": q.get("q", ""),
                "line": q.get("line"),
                "source": src_label,
                "key_sha": _sha(nk),
                "key_len": len(nk),
            })
        dims[key] = {"en": en, "zh": zh, "state": "OK",
                     "source": src_label,
                     "asked": len([x for x in questions if x["dim"] == key])}

    return {"questions": questions, "dims": dims,
            "threshold": threshold(root), "per_dim": k}


class Log:
    """append-only。跟事件帳本同一個原則：寫下去就是證據。"""

    def __init__(self, root: Path = REPO):
        self.path = Path(root) / ".forseti" / LOG_NAME

    def append(self, row: dict) -> dict:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row

    def all(self) -> list[dict]:
        if not self.path.is_file():
            return []
        out = []
        with self.path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
        return out

    def exam(self, exam_id: str) -> dict | None:
        for r in self.all():
            if r.get("kind") == "EXAM" and r.get("id") == exam_id:
                return r
        return None

    def results(self, session: str | None = None) -> list[dict]:
        rs = [r for r in self.all() if r.get("kind") == "RESULT"]
        if session:
            rs = [r for r in rs if r.get("session") == session]
        return rs


def open_exam(root: Path = REPO, *, session: str,
              per_dim: int | None = None, at: float | None = None) -> dict:
    """出卷並記進帳本。回的東西可以直接拿給受測者看，裡面沒有答案。"""
    paper = compose(root, per_dim=per_dim)
    ts = at or time.time()
    eid = _sha(f"{session}|{ts}|{len(paper['questions'])}")[:12]
    row = {"kind": "EXAM", "id": eid, "at": ts, "session": str(session or ""),
           "threshold": paper["threshold"], "dims": paper["dims"],
           "questions": paper["questions"]}
    Log(root).append(row)
    return row


def grade_one(q: dict, answer: str) -> dict:
    """一題。比 hash，不比字面，因為考卷裡沒有字面可以比。

    滑動視窗：把作答正規化之後，看有沒有任何一段長度對得上的子字串
    hash 等於 `key_sha`。等價於「原文那一段有沒有出現在作答裡」。
    """
    n = int(q.get("key_len") or 0)
    want = q.get("key_sha") or ""
    said = _norm(answer or "")
    ok = False
    if want and n and len(said) >= n:
        for i in range(len(said) - n + 1):
            if _sha(said[i:i + n]) == want:
                ok = True
                break
    return {"qid": q.get("qid"), "dim": q.get("dim"), "ok": ok,
            "line": q.get("line"), "kind": q.get("kind")}


def judge(exam: dict, answers: dict) -> dict:
    """批改一整份。判決的三種狀態在模組說明裡有理由。"""
    thr = float(exam.get("threshold") or DEFAULT_THRESHOLD)
    per: dict[str, dict] = {}
    marks = []
    for q in exam.get("questions") or []:
        m = grade_one(q, (answers or {}).get(q.get("qid"), ""))
        marks.append(m)
        d = per.setdefault(q["dim"], {"asked": 0, "right": 0})
        d["asked"] += 1
        d["right"] += 1 if m["ok"] else 0

    dims = exam.get("dims") or {}
    missing = [k for k, v in dims.items()
               if v.get("state") in ("NO_SOURCE", "NO_QUESTION")]
    for k, v in per.items():
        v["rate"] = v["right"] / v["asked"] if v["asked"] else 0.0
        v["pass"] = v["rate"] >= thr

    asked = sum(v["asked"] for v in per.values())
    right = sum(v["right"] for v in per.values())
    rate = right / asked if asked else 0.0

    weak = [k for k, v in per.items() if not v["pass"]]
    if not per:
        verdict = "FAIL"
        why = "一題都出不出來，這道門現在驗不了任何事"
    elif weak:
        verdict = "FAIL"
        why = "這幾維沒過：" + "、".join(weak)
    elif missing:
        verdict = "PASS_PARTIAL"
        why = "有題的都過了，但這幾維沒有來源可考：" + "、".join(missing)
    else:
        verdict = "PASS"
        why = "五個維度都考過了"

    return {"verdict": verdict, "why": why, "rate": rate,
            "asked": asked, "right": right, "threshold": thr,
            "per_dim": per, "missing_dims": missing, "marks": marks}


def submit(root: Path = REPO, *, exam_id: str, answers: dict,
           session: str, at: float | None = None) -> dict:
    """交卷。批改結果進帳本，之後查得到這個 session 憑什麼拿到權限。"""
    log = Log(root)
    exam = log.exam(exam_id)
    if exam is None:
        return {"ok": False, "why": f"找不到這份考卷：{exam_id}"}
    res = judge(exam, answers)
    row = {"kind": "RESULT", "exam": exam_id, "at": at or time.time(),
           "session": str(session or ""), **res}
    log.append(row)
    return {"ok": True, **row}


def state(root: Path = REPO, *, session: str) -> dict:
    """這條線現在能不能寫。

    權限綁 session，不綁時間。§39 講的是 successor ——
    換一條線就是換一個受測者，上一個考過的不算它的。
    **不設有效期**，因為規格沒有給，自己編一個 TTL 等於發明規則。
    """
    rs = [r for r in Log(root).results(session)]
    rs.sort(key=lambda r: r.get("at", 0))
    last = rs[-1] if rs else None
    ok = bool(last) and last.get("verdict") in ("PASS", "PASS_PARTIAL")
    return {
        "session": str(session or ""),
        "write": ok,
        "verdict": (last or {}).get("verdict", ""),
        "why": (last or {}).get("why", "這條線還沒考過，預設唯讀（§19.2）"),
        "rate": (last or {}).get("rate"),
        "missing_dims": (last or {}).get("missing_dims", []),
        "attempts": len(rs),
        "enforced": enforced(root),
        "at": (last or {}).get("at"),
    }


def can_write(root: Path = REPO, *, session: str) -> bool:
    """給閘門呼叫的那一個布林值。

    **沒開強制的時候一律回 True**，而 `state()` 照樣說實話。
    把「現在的狀態」跟「要不要因此擋人」分開，是因為混在一起之後
    就沒辦法在不擋人的情況下先觀察這道門會擋掉什麼。
    """
    if not enforced(root):
        return True
    return bool(state(root, session=session)["write"])
