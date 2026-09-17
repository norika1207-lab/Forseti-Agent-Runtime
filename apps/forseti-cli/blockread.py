"""區塊閱讀。讀一塊、記一塊、最後把疑問交給 owner。§41

owner 2026-09-14：

    而且 FORSETI 應該要協助 AI 在讀文件時用區塊方式去讀完，
    然後讀完一個區塊就記錄下來，最後再跟開發者做確認
    這些規格有沒有問題才對

這解的是 `REQUIRED_READING.md` 第 22 行那句話的後半段。那份文件說
「還沒讀完這件事要是檔案裡的狀態，不是靠誰記得」，但它只做到記
「讀了幾行」。讀了幾行證明不了讀進去什麼 —— 一個 session 可以把
整份檔案 cat 出來然後什麼都沒看。

所以這裡記的不是行數，是每一塊的「我讀到了什麼」跟「我沒看懂什麼」。
沒看懂的那些會累積成一張清單交給 owner 裁，那就是 F08 §5 的
level 6 `VERIFIED_UNDERSTANDING`:完整讀取之後有人考過我。
`REQUIRED_READING.md` 第 59 行寫著那一級「現在沒有實作」。

**為什麼照標題切不照行數切。** 一份文件的段落邊界是作者放的，
死切 80 行會把一張表切成兩半，而表格被切斷之後兩半都讀不懂。
`REQUIRED_READING.md` 第 119 行講 docx 轉檔時說過同一件事:
結構本身就是資訊。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

LOG_NAME = "reading_blocks.jsonl"

# markdown 標題。fence 裡面的 # 不是標題，要先剔掉。
_H = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Block:
    """一個讀取單位。行號都是 1-based，兩端都含。"""

    index: int
    title: str
    level: int
    lo: int
    hi: int

    @property
    def lines(self) -> int:
        return self.hi - self.lo + 1

    def to_dict(self) -> dict:
        return {"index": self.index, "title": self.title, "level": self.level,
                "lo": self.lo, "hi": self.hi, "lines": self.lines}


def split(path: Path, *, max_lines: int = 160, min_lines: int = 12) -> list[Block]:
    """照標題切塊。太長的塊再對半切，太短的塊併進前一塊。

    max_lines 不是規定一次要讀多少，是避免一個沒有子標題的長段落
    變成一塊三百行的東西 —— 那跟沒切一樣。
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    if not lines:
        return []

    heads: list[tuple[int, int, str]] = []          # (行號, 階, 標題)
    in_fence = False
    for i, ln in enumerate(lines, 1):
        if _FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _H.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))

    spans: list[tuple[int, int, str, int]] = []
    if not heads or heads[0][0] > 1:
        end = heads[0][0] - 1 if heads else len(lines)
        if end >= 1:
            spans.append((1, end, path.name, 0))
    for n, (lo, lv, title) in enumerate(heads):
        hi = heads[n + 1][0] - 1 if n + 1 < len(heads) else len(lines)
        spans.append((lo, hi, title, lv))

    # 太短的併進前一塊。一個只有標題沒內容的段落單獨成塊沒有意義。
    merged: list[list] = []
    for lo, hi, title, lv in spans:
        if merged and (hi - lo + 1) < min_lines and \
                (merged[-1][1] - merged[-1][0] + 1) + (hi - lo + 1) <= max_lines:
            merged[-1][1] = hi
            merged[-1][2] = merged[-1][2] + " + " + title
        else:
            merged.append([lo, hi, title, lv])

    out: list[Block] = []
    for lo, hi, title, lv in merged:
        n = hi - lo + 1
        if n <= max_lines:
            out.append(Block(len(out) + 1, title, lv, lo, hi))
            continue
        # 對半再對半，直到每塊都在上限內。
        parts = (n + max_lines - 1) // max_lines
        step = (n + parts - 1) // parts
        for k in range(parts):
            a = lo + k * step
            b = min(hi, a + step - 1)
            if a > hi:
                break
            suffix = f"（{k + 1}/{parts}）" if parts > 1 else ""
            out.append(Block(len(out) + 1, title + suffix, lv, a, b))
    return out


def text_of(path: Path, block: Block) -> str:
    """這一塊的原文。讀的人拿到的東西。"""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[block.lo - 1:block.hi])


@dataclass
class Note:
    """讀完一塊之後留下的東西。

    summary 是「我讀到了什麼」。question 是「我沒看懂或這裡有問題」，
    空字串代表沒有疑問 —— 那也是一種狀態，不是沒填。
    """

    path: str
    index: int
    title: str
    lo: int
    hi: int
    summary: str
    question: str = ""
    at: float = field(default_factory=time.time)
    session: str = ""

    def to_dict(self) -> dict:
        return {"path": self.path, "index": self.index, "title": self.title,
                "lo": self.lo, "hi": self.hi, "summary": self.summary,
                "question": self.question, "at": self.at,
                "session": self.session}


class BlockLog:
    """append-only。寫進去就改不掉，跟帳本同一個原則。"""

    def __init__(self, root: Path):
        self.path = Path(root) / ".forseti" / LOG_NAME

    def append(self, note: Note) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(note.to_dict(), ensure_ascii=False) + "\n")

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

    def done_for(self, path: str) -> set[int]:
        return {r.get("index") for r in self.all() if r.get("path") == path}

    def questions(self) -> list[dict]:
        """待 owner 裁的清單。§41

        只收有寫 question 的。沒有疑問的塊不佔她的時間。
        """
        return [r for r in self.all() if (r.get("question") or "").strip()]


def status(root: Path, path: Path) -> dict:
    """這份文件讀到哪了。"""
    blocks = split(path)
    log = BlockLog(root)
    done = log.done_for(str(path))
    rows = []
    for b in blocks:
        d = b.to_dict()
        d["done"] = b.index in done
        rows.append(d)
    return {"path": str(path), "name": path.name,
            "blocks": len(blocks), "done": len([r for r in rows if r["done"]]),
            "rows": rows}


# ── 反過來考 AI ──────────────────────────────────
# owner 2026-09-14：
#
#     如果 FORSETI 一開始沒有讓 AI 知道有這個能力，
#     就像我跟你說的 grillme 的 skill 一樣，反過頭來問 AI
#
#     這樣有文件的開發者，至少是安心地按照文件跟北極星在做，
#     而不是碰運氣賭 AI 只讀 18%
#
# 題目跟答案都從原文抽，不是生成的。這一條是整個機制能不能算數的
# 關鍵:如果題目是讀的人自己出的，那它只會考自己記得的部分，
# 而記得的部分正是不需要考的部分。

# 含數字的規定句。數字是最好挖的洞:它有唯一解，錯了就是錯了。
_NUM = re.compile(r"(?<![\w.])(\d{1,6})(?![\w.])")
# 明文禁止。這種句子被漏讀的代價最高。
_FORBID = re.compile(r"(不准|不可以|禁止|絕對不|一律不|不得|必須先|一定要)")
# 表格列。| a | b | c |
_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
# 日期形狀。年月日被挖空考的是記性不是理解。
_DATEY = re.compile(r"\d{4}-\d{2}-\d{2}|\d{4}/\d{1,2}/\d{1,2}|\d{1,2} 月 \d{1,2} 日")


# 這句是不是在規定一件事。不是的話它的數字不值得考。
_RULEY = re.compile(
    r"必須|應該|應|要求|規定|上限|下限|至少|最多|最少|不得超過|門檻|"
    r"趨近|等於|定義為|共有|一共|分成|七級|六條|條規|第\s*\d+\s*條")


# 識別碼裡的數字。`B-08`、`F01`、`AT-HOOK-R3` 的那一段數字
# 是這條阻塞、這份規格的名字，不是它規定的值。
# 挖掉它考的是「你記不記得那條叫幾號」，跟 `_DATEY` 排除日期同一條理由。
_IDPREFIX = re.compile(r"[A-Za-z]-?$")


def _is_year(n: str) -> bool:
    return len(n) == 4 and n.startswith(("19", "20"))


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _quoted(s: str, pos: int) -> bool:
    """這個位置是不是在引號裡面。

    【2026-09-14】soul.md 第 76 行寫的是「誤讀成『不准碰情緒』」。
    原文白紙黑字標著那是誤讀,是錯誤理解的版本,而出題器把它抓成
    明文限制拿來考人。**引號裡的句子是被引述的說法,不是規定。**
    分不出這兩者的題庫,考出來的答案是反的。
    """
    for lq, rq in (("「", "」"), ("『", "』"), ("\u201c", "\u201d"), ('"', '"')):
        depth = 0
        for i, ch in enumerate(s):
            if ch == lq:
                depth += 1
            elif ch == rq and depth:
                depth -= 1
            if i == pos and depth:
                return True
    return False


def quiz(path: Path, block: Block, *, limit: int = 3) -> list[dict]:
    """從這一塊原文出題。答案是原文裡的字，不是我的話。

    三種題型，按照「漏讀的代價」排序:
    禁令 > 數字 > 表格值。禁令被漏掉會做出規格明文禁止的東西，
    那正是 CLI 那次發生的事。
    """
    body = text_of(path, block)
    if not body.strip():
        return []
    out: list[dict] = []
    lines = body.splitlines()

    for off, ln in enumerate(lines):
        s = _clean(ln)
        if not s or len(s) < 12 or len(s) > 160:
            continue
        # 標題行照出禁令題。bible.md 的規矩就寫在標題上
        # （「R-01 文件要整份讀完，不准 grep 找答案」），
        # 把標題跳過等於把最重要的那條漏掉。
        is_head = s.startswith("#")
        s = _H.sub(r"\2", s) if is_head else s
        lineno = block.lo + off

        m = _FORBID.search(s)
        if m and len(out) < limit * 3 and not _quoted(s, m.start()):
            # key 不能是「不准」這兩個字。
            #
            # 【2026-09-14 owner 當場考出來的】原本 key 抽的是禁令詞本身，
            # 於是這題變成「你會不會把『不准』兩個字打出來」，
            # 答對答錯都跟有沒有讀懂那條規定無關。
            # 改成抽禁令詞後面那段，也就是「禁止的內容」。
            tail = s[m.end():].strip(" 　、,，。「」『』：:")
            key = tail[:24] if len(tail) >= 4 else s
            out.append({
                "kind": "禁令",
                "q": f"第 {lineno} 行有一條明文限制，它禁止什麼？",
                "a": s,
                "key": key,
                "line": lineno,
            })
            continue

        # 日期不是規定。「事故：2026-09-08」考的是我記不記得那天
        # 出了什麼事，而不是規格要求什麼 —— 挖那種洞等於白考。
        if is_head or _DATEY.search(s) or s.startswith(("事故", "**事故")):
            continue
        # 數字只在句子本身是規定的時候才考。
        # 「工程書 166,680 字」是敘述，挖掉它考的是記性；
        # 「至少要 3 份」是規定，挖掉它考的是有沒有讀到那條規定。
        # 【2026-09-16 18:5x】識別碼裡的數字不出題。
        #
        # 真的踩到過：`.forseti/NEXT.md` 新增的阻塞那一節有一行
        # 「- B-08　擋住：階段 0 的其中一半」，`_RULEY` 命中「一半」前的
        # 規定詞、`_NUM` 抽到 `08`，於是閘門出了一題答案是「08」的填空，
        # 而 `大概是講08那件事` 這種含糊回答照樣算對
        # （`tests/test_gate.py::test_不做語意相似度` 當場變紅）。
        #
        # 這跟 owner 2026-09-14 考出來的「把『不准』打出來就算對」
        # 是同一種病的第三個變體。前兩個（禁令詞、單字元數字）已經擋掉。
        nums = [m.group(1) for m in _NUM.finditer(s)
                if not _is_year(m.group(1))
                and not _IDPREFIX.search(s[max(0, m.start() - 2):m.start()])]
        # 【2026-09-16】單字元的答案不出題。
        #
        # `grade()` 比的是「原文的 key 有沒有出現在答案裡」，所以一個
        # 只有一個字元的 key 幾乎在任何一句話裡都找得到 —— 這題答對
        # 答錯都跟有沒有讀懂那一行無關。**那跟 owner 2026-09-14 當場
        # 考出來的「把『不准』兩個字打出來就算對」是同一種病**，
        # 上面禁令那一支已經用 `len(tail) >= 4` 擋掉了，數字這一支沒有。
        #
        # 真的踩到過：`.forseti/NEXT.md` 有一行摘要是
        # 「有值但不滿足規格要求：2」，`_RULEY` 命中「要求」、
        # `_NUM` 抽到 `2`，於是接手閘門出了一題答案是「2」的填空。
        #
        # 這裡擋的是退化情形，不是一個校準過的門檻。
        # **2 個字元以上仍然會漏**（key 是 `2` 的時候 `12` 也含它），
        # 那個要改 `grade()` 的比對方式才解得掉，不是改長度解得掉。
        nums = [n for n in nums if len(n) >= 2]
        if nums and _RULEY.search(s) and len(out) < limit * 3:
            n = max(nums, key=len)
            out.append({
                "kind": "數字",
                "q": f"第 {lineno} 行：{s.replace(n, '＿＿', 1)}　填空",
                "a": n,
                "key": n,
                "line": lineno,
            })
            continue

        r = _ROW.match(ln)
        if r and len(out) < limit * 3:
            cells = [c.strip() for c in r.group(1).split("|")]
            cells = [c for c in cells if c and not set(c) <= {"-", ":"}]
            if len(cells) >= 2:
                out.append({
                    "kind": "表格",
                    "q": f"第 {lineno} 行那一列，第一欄是「{cells[0]}」，"
                         f"後面幾欄是什麼？",
                    "a": " ｜ ".join(cells[1:]),
                    "key": cells[1] if len(cells) > 1 else "",
                    "line": lineno,
                })

    order = {"禁令": 0, "數字": 1, "表格": 2}
    out.sort(key=lambda q: order.get(q["kind"], 9))
    return out[:limit]


def grade(question: dict, answer: str) -> dict:
    """對答案。比對的是原文的 key，不是語意相似度。

    **不做模糊比對。** 語意相似度會讓「差不多對」通過，
    而規格這種東西差不多對就是錯。
    """
    key = (question.get("key") or "").strip()
    said = _clean(answer or "")
    ok = bool(key) and key in said
    return {"ok": ok, "key": key, "said": said,
            "line": question.get("line"), "kind": question.get("kind")}
