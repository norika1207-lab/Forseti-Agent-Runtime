#!/usr/bin/env python3
"""索引層與查詢層。階段 C1。

存在的理由寫在 `docs/context-continuity.md` 第 5 節：全文檢索在這裡是死的，
因為人想不起來自己忘了什麼，AI 更不知道自己忘了什麼。遺忘不會留下一個空格
讓你發現，它是無縫的。

所以索引不是「更快的搜尋」，它做三件搜尋做不到的事：

  縮小範圍。被壓縮丟掉的段落優先，那些正是現在讀不到但可能還需要的。
  標出分界。使用者糾正過的位置是分界線，線之前的講法要當作可疑。
  攔下過時答案。一個很有自信的錯答案比不回答更糟。

設計約束：

  只讀 jsonl，一個位元組都不動。索引是另一個檔案，錯了刪掉重建。
  這是不變量一與不變量三。

  零依賴。sqlite3 是標準庫，FTS5 trigram 讓中文不必自己造分詞。

  啟發式的要標成啟發式。糾正偵測與作廢判定都是規則猜的，不是確定的，
  輸出裡一律標 candidate。把猜的講成確定的,就是這整個專案在防的事。

用法：
    python3 apps/forseti-cli/recall.py index [--rebuild] [--limit N]
    python3 apps/forseti-cli/recall.py "為何會有點名板"
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECTS_DIR = Path.home() / ".claude" / "projects"
DB_PATH = Path.home() / ".forseti" / "recall.db"

# ---------------------------------------------------------------------------
# 訊號詞表
# ---------------------------------------------------------------------------
#
# 這些詞表單獨用都會誤判,B-05 記著實測數字:每千則命中 242 次、40/40 全中,
# 而且有一類假陽性方向是反的。所以它們在這裡只當觸發器,後面一定接結構條件
# (訊息角色、長度、有沒有跟著行為改變)。用法跟 Code-Duo 的 check_honesty
# 一樣:詞表負責「要不要看」,結構負責「算不算數」。

_CORRECTION_HINTS = re.compile(
    r"(不對|錯了|不是這樣|你搞錯|沒有達到|根本沒|你真的|要不要去看|"
    r"等一下|停下來|不要再|我說過|講過了|你去|重來|回去看|再讀|你忘了|"
    r"幹你娘|不高興|我強調|我要的是|沒做完|你有沒有)",
)

_DECISION_HINTS = re.compile(
    r"(決定|改用|不做|採用|放棄|改成|定案|就這樣|方向是|原則是|一律)",
)

# 路徑:有副檔名或有斜線,且不含空白。跟 Code-Duo 的 _BACKTICK/_EXT 同一個判準。
_PATHLIKE = re.compile(r"[A-Za-z0-9_./~-]*[/][A-Za-z0-9_./~-]+|[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}\b")


def norm(s: str) -> str:
    """正規化後才進索引。

    她打字大量使用全形英數(ＩＳＥＥＵ、ＣＯＤＥＤＵＯ),跟半形在 FTS 裡
    是完全不同的字串,不正規化就永遠查不到。NFKC 把全形折成半形,
    再統一小寫,英文查詢就不必管大小寫。

    顯示一律用原文,正規化只用於比對。改動原文等於改動證據。
    """
    return unicodedata.normalize("NFKC", s or "").lower()


# ---------------------------------------------------------------------------
# 資料
# ---------------------------------------------------------------------------

@dataclass
class Segment:
    """一次交換：使用者說一句，AI 做了一串事，到下一句使用者訊息為止。

    用 user turn 當邊界，因為那是對話的自然關節。以 assistant turn 切
    會把一件事拆成好幾段，查出來全是碎片。
    """

    session_id: str
    file: str
    start_line: int
    end_line: int
    ts: str
    user_text: str = ""
    asst_text: str = ""
    paths: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    kind: str = "work"
    dropped: bool = False

    @property
    def text(self) -> str:
        return (self.user_text + "\n" + self.asst_text).strip()


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------

def _blocks_text(content) -> tuple[str, list[str]]:
    """從 message.content 取出文字與工具名。

    content 可能是字串，也可能是 block 清單。清單裡混著 text、tool_use、
    tool_result，只取 text 的文字部分，工具名另外收。
    """
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return "", []
    texts, tools = [], []
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text" and isinstance(b.get("text"), str):
            texts.append(b["text"])
        elif t == "tool_use":
            name = b.get("name")
            if isinstance(name, str):
                tools.append(name)
        elif t == "thinking" and isinstance(b.get("thinking"), str):
            # 思考不進索引。它是過程不是結論,而且量大會淹掉真正的內容。
            continue
    return "\n".join(texts), tools


def segment_session(path: Path) -> list[Segment]:
    """把一份 jsonl 切成段。行號從 1 起算，對得上編輯器。"""
    segs: list[Segment] = []
    cur: Segment | None = None
    session_id = ""
    compact_ts: list[str] = []

    try:
        fh = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return segs

    with fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(d, dict):
                continue

            session_id = session_id or (d.get("sessionId") or "")

            if d.get("subtype") == "compact_boundary":
                ts = d.get("timestamp") or ""
                if ts:
                    compact_ts.append(ts)
                continue

            typ = d.get("type")
            if typ not in ("user", "assistant"):
                continue
            msg = d.get("message")
            if not isinstance(msg, dict):
                continue

            text, tools = _blocks_text(msg.get("content"))
            ts = d.get("timestamp") or ""

            if typ == "user":
                # 壓縮摘要不是使用者說的話。它是系統塞進來的,
                # 當成使用者訊息會讓「她說過什麼」整個失真。
                if d.get("isCompactSummary"):
                    continue
                if cur is not None:
                    cur.end_line = lineno - 1
                    segs.append(cur)
                cur = Segment(
                    session_id=session_id,
                    file=str(path),
                    start_line=lineno,
                    end_line=lineno,
                    ts=ts,
                    user_text=text.strip(),
                )
            else:
                if cur is None:
                    cur = Segment(session_id=session_id, file=str(path),
                                  start_line=lineno, end_line=lineno, ts=ts)
                if text.strip():
                    cur.asst_text = (cur.asst_text + "\n" + text).strip()
                for t in tools:
                    if t not in cur.tools:
                        cur.tools.append(t)
                cur.end_line = lineno

    if cur is not None:
        segs.append(cur)

    first_compact = min(compact_ts) if compact_ts else None
    for s in segs:
        _classify(s)
        # 保守估計:壓縮之前的段落視為已被丟出 context。
        # preservedSegment 標了保留段的錨點,精確判定要跟 uuid 鏈,
        # 那是 C1 之後的事。標保守會多撈一些,不會漏。
        if first_compact and s.ts and s.ts < first_compact:
            s.dropped = True
    return segs


def _classify(s: Segment) -> None:
    """分類。全部是啟發式，所以名字裡帶 candidate。"""
    s.paths = sorted({m.group(0) for m in _PATHLIKE.finditer(s.text)})[:20]

    u = s.user_text
    # 糾正的結構條件:必須是使用者說的、必須短。長篇通常是在交代需求,
    # 不是在糾正。門檻 400 字是看真實資料抓的,不是理論值。
    if u and len(u) < 400 and _CORRECTION_HINTS.search(u):
        s.kind = "correction_candidate"
    elif _DECISION_HINTS.search(s.asst_text[:1500]):
        s.kind = "decision_candidate"
    elif s.tools:
        s.kind = "work"
    else:
        s.kind = "discussion"


# ---------------------------------------------------------------------------
# 索引
# ---------------------------------------------------------------------------

# external content 的 FTS5 表,欄位名必須跟來源表一致,rebuild 才讀得到。
# 用 body 這種來源表沒有的名字,建表會過,rebuild 會炸,而且錯誤訊息
# 只說 SQL logic error 不說哪裡錯。
SCHEMA = """
CREATE TABLE IF NOT EXISTS segments (
  id INTEGER PRIMARY KEY,
  session_id TEXT, file TEXT,
  start_line INTEGER, end_line INTEGER,
  ts TEXT, kind TEXT, dropped INTEGER,
  paths TEXT, tools TEXT,
  user_text TEXT, asst_text TEXT,
  norm_user TEXT, norm_asst TEXT
);
CREATE INDEX IF NOT EXISTS idx_ts ON segments(ts);
CREATE INDEX IF NOT EXISTS idx_kind ON segments(kind);
CREATE INDEX IF NOT EXISTS idx_file ON segments(file);
CREATE VIRTUAL TABLE IF NOT EXISTS seg_fts USING fts5(
  norm_user, norm_asst, content='segments', content_rowid='id', tokenize='trigram'
);
"""

# 改了 SCHEMA 就把這個加一。舊索引會被自動丟掉重建。
# 這樣做的底氣是不變量一:原始 jsonl 沒動過,索引是純函數的產物,
# 隨時可以從頭長出來。索引的結構因此可以大膽改。
SCHEMA_VERSION = 3


def connect(db: Path = DB_PATH) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    have = con.execute("PRAGMA user_version").fetchone()[0]
    if have and have != SCHEMA_VERSION:
        con.executescript("DROP TABLE IF EXISTS seg_fts; DROP TABLE IF EXISTS segments;")
        have = 0
    con.executescript(SCHEMA)
    if have != SCHEMA_VERSION:
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    con.commit()
    return con


def build_index(db: Path = DB_PATH, root: Path = PROJECTS_DIR,
                rebuild: bool = False, limit: int | None = None) -> dict:
    con = connect(db)
    if rebuild:
        # external content 的 FTS5 表沒有自己的欄位,DELETE 會找不到 body。
        # 清空要用它自己的命令。
        con.execute("INSERT INTO seg_fts(seg_fts) VALUES('delete-all')")
        con.execute("DELETE FROM segments")
        con.commit()

    done = {r[0] for r in con.execute("SELECT DISTINCT file FROM segments")}
    files = sorted(root.glob("*/*.jsonl"))
    if limit:
        files = files[:limit]

    t0 = time.time()
    n_files = n_segs = 0
    for p in files:
        if str(p) in done:
            continue
        segs = segment_session(p)
        if not segs:
            continue
        rows = [(s.session_id, s.file, s.start_line, s.end_line, s.ts, s.kind,
                 int(s.dropped), " ".join(s.paths), " ".join(s.tools),
                 s.user_text[:4000], s.asst_text[:8000],
                 norm(s.user_text[:4000]), norm(s.asst_text[:8000])) for s in segs]
        con.executemany(
            "INSERT INTO segments (session_id,file,start_line,end_line,ts,kind,"
            "dropped,paths,tools,user_text,asst_text,norm_user,norm_asst) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        n_files += 1
        n_segs += len(rows)

    # FTS 從 segments 重建。分開做而不是逐筆插,是因為 external content
    # 表這樣同步最不容易寫錯。
    con.execute("INSERT INTO seg_fts(seg_fts) VALUES('rebuild')")
    con.commit()
    return {"files": n_files, "segments": n_segs, "seconds": round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------
# 查詢
# ---------------------------------------------------------------------------

@dataclass
class Hit:
    seg_id: int
    ts: str
    kind: str
    dropped: bool
    file: str
    start_line: int
    end_line: int
    snippet: str
    score: float
    superseded_by: list[str] = field(default_factory=list)
    copies: int = 1


def _terms(q: str) -> list[str]:
    """把問題切成查詢詞。

    英文照空白切,中文切成三字窗,因為 FTS5 的 trigram 需要至少三個字元,
    兩個字的查詢詞永遠命中不了。這是實測出來的,不是猜的。
    """
    q = norm(q)
    out = []
    for tok in re.findall(r"[a-z0-9_.-]{2,}", q):
        out.append(tok)
    han = re.findall(r"[一-鿿]{2,}", q)
    for h in han:
        if len(h) >= 3:
            for i in range(len(h) - 2):
                out.append(h[i:i + 3])
        else:
            out.append(h)  # 兩字詞走 LIKE 分支
    return out


def search(q: str, db: Path = DB_PATH, limit: int = 8,
           exclude_file: str | None = None) -> list[Hit]:
    """查。exclude_file 預設排除當前正在跑的那個 session。

    不排除的話會出現自我引用污染:助理查「為何有點名板」,查到的第一名
    是主 session 五分鐘前打的那句「為何有點名板」。實測三題全中這個坑,
    因為問題的原文就在最新的 jsonl 裡。

    當前 session 的內容它本來就在 context 裡,不需要用查的。
    這個系統要找的是它「已經沒有」的東西。
    """
    con = connect(db)
    terms = _terms(q)
    if not terms:
        return []

    rows: dict[int, float] = {}
    hit_terms: dict[int, set[str]] = {}
    for t in terms:
        if len(t) >= 3:
            sql = ("SELECT s.id, bm25(seg_fts) FROM seg_fts "
                   "JOIN segments s ON s.id = seg_fts.rowid "
                   "WHERE seg_fts MATCH ? ORDER BY bm25(seg_fts) LIMIT 400")
            try:
                got = con.execute(sql, (f'"{t}"',)).fetchall()
            except sqlite3.OperationalError:
                got = []
            # 這裡試過加 IDF 式降權(命中越多筆的詞權重越低),三題全部變差,
            # 已回退。原因推測是罕見的三字窗常常是巧合,不是語意訊號。
            # 留這段註解是為了讓下一個人不要再試一次同樣的東西。
            for sid, bm in got:
                # bm25 越小越相關,轉成越大越好
                rows[sid] = rows.get(sid, 0.0) + max(0.0, 10.0 - float(bm))
                hit_terms.setdefault(sid, set()).add(t)
        else:
            # trigram 吃不下的短詞走 LIKE。慢,但只有兩字詞會走到。
            got = con.execute(
                "SELECT id FROM segments WHERE user_text LIKE ? OR asst_text LIKE ? LIMIT 200",
                (f"%{t}%", f"%{t}%")).fetchall()
            for (sid,) in got:
                rows[sid] = rows.get(sid, 0.0) + 1.0
                hit_terms.setdefault(sid, set()).add(t)

    if not rows:
        return []

    ids = sorted(rows, key=lambda i: rows[i], reverse=True)[:limit * 4]
    qmarks = ",".join("?" * len(ids))
    sql = (f"SELECT id,ts,kind,dropped,file,start_line,end_line,paths,user_text,asst_text "
           f"FROM segments WHERE id IN ({qmarks})")
    params = list(ids)
    if exclude_file:
        sql += " AND file != ?"
        params.append(exclude_file)
    recs = con.execute(sql, params).fetchall()

    hits: list[Hit] = []
    for (sid, ts, kind, dropped, f, sl, el, paths, ut, at) in recs:
        score = rows.get(sid, 0.0)
        # 命中越多個不同的查詢詞越相關。沒有這一項的話,一個高頻短詞
        # 命中很多次就能贏過真正切題的段落 —— 實測「ISEEU 開了幾個角色」
        # 第二名是一段講造假 pattern 的文字,它只是碰巧含「幾個」。
        cov = len(hit_terms.get(sid, ())) / max(1, len(set(terms)))
        score *= (0.25 + 0.75 * cov)
        # 被壓縮丟掉的加權。它們是這個系統存在的理由:現在讀不到,
        # 但可能還需要。沒有這一項的話,索引只是一個比較慢的 grep。
        if dropped:
            score *= 1.35
        if kind == "correction_candidate":
            score *= 1.25
        hits.append(Hit(sid, ts or "", kind, bool(dropped), f, sl, el,
                        _snippet(ut, at, q), score))

    hits.sort(key=lambda h: h.score, reverse=True)
    hits = _dedupe(hits)[:limit]
    _mark_superseded(con, hits)
    return hits


def _dedupe(hits: list[Hit]) -> list[Hit]:
    """同一段內容常常在多份 jsonl 裡各有一份（session 被複製過）。

    實測「如何協調 Code-Duo」時，前六名有三組是兩兩重複的，等於一半的
    版面在講同一件事。合併成一筆，把其他份數記在 copies 上，別讓重複
    把真正不同的答案擠掉。
    """
    out: list[Hit] = []
    seen: dict[tuple, Hit] = {}
    for h in hits:
        key = (h.snippet[:100], h.start_line, h.end_line)
        if key in seen:
            seen[key].copies += 1
            continue
        seen[key] = h
        out.append(h)
    return out


def _snippet(user_text: str, asst_text: str, q: str, width: int = 150) -> str:
    """優先取使用者說的那一句。她的原話比 AI 的複述可靠。"""
    base = user_text.strip() or asst_text.strip()
    base = re.sub(r"\s+", " ", base)
    for t in _terms(q):
        i = base.find(t)
        if i >= 0:
            a = max(0, i - width // 3)
            return ("…" if a else "") + base[a:a + width] + ("…" if a + width < len(base) else "")
    return base[:width] + ("…" if len(base) > width else "")


def _mark_superseded(con: sqlite3.Connection, hits: list[Hit]) -> None:
    """作廢關係。啟發式，所以只標 candidate 不下定論。

    規則：這一段之後如果有使用者的糾正，而且那次糾正碰的是同一批檔案路徑，
    那這一段的講法就可疑。不敢說它一定被推翻，只說後面有人動過這個話題。
    """
    for h in hits:
        row = con.execute("SELECT paths FROM segments WHERE id=?", (h.seg_id,)).fetchone()
        paths = (row[0] or "").split() if row else []
        if not paths or not h.ts:
            continue
        cond = " OR ".join(["paths LIKE ?"] * len(paths[:6]))
        args = [f"%{p}%" for p in paths[:6]]
        later = con.execute(
            f"SELECT ts,start_line,file FROM segments "
            f"WHERE ts > ? AND kind='correction_candidate' AND ({cond}) "
            f"ORDER BY ts LIMIT 3", [h.ts, *args]).fetchall()
        h.superseded_by = [f"{_local(ts)} {Path(f).name[:8]}…:{sl}" for ts, sl, f in later]


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------

def _local(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts[:16]


def cmd_index(args: list[str]) -> int:
    rebuild = "--rebuild" in args
    limit = None
    if "--limit" in args:
        try:
            limit = int(args[args.index("--limit") + 1])
        except (IndexError, ValueError):
            print("--limit 要跟一個數字", file=sys.stderr)
            return 2
    print()
    print("  建索引中…（只讀 jsonl，不修改任何原始檔）")
    st = build_index(rebuild=rebuild, limit=limit)
    con = connect()
    total = con.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    dropped = con.execute("SELECT COUNT(*) FROM segments WHERE dropped=1").fetchone()[0]
    corr = con.execute("SELECT COUNT(*) FROM segments WHERE kind='correction_candidate'").fetchone()[0]
    print(f"  新增 {st['files']} 份檔案、{st['segments']:,} 段，耗時 {st['seconds']}s")
    print()
    print(f"  索引現況　{total:,} 段")
    print(f"    被壓縮丟掉的　{dropped:,} 段　（查詢時加權，那是這個系統的重點）")
    print(f"    糾正候選　{corr:,} 段　（啟發式，是候選不是確定）")
    print(f"    資料庫　{DB_PATH}")
    print()
    return 0


def _current_session_file() -> str | None:
    """最近被寫入的 jsonl,幾乎一定是正在跑的這個 session。"""
    try:
        files = sorted(PROJECTS_DIR.glob("*/*.jsonl"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        return str(files[0]) if files else None
    except OSError:
        return None


def cmd_recall(q: str, include_current: bool = False) -> int:
    excl = None if include_current else _current_session_file()
    hits = search(q, exclude_file=excl)
    print()
    print(f"  問題　{q}")
    print()
    if not hits:
        print("  查不到。索引建過了嗎？`forseti index`")
        print("  或者換一個更長的詞，中文查詢詞少於三個字命中率很差。")
        print()
        return 1

    for i, h in enumerate(hits, 1):
        tags = []
        if h.dropped:
            tags.append("已被壓縮丟出 context")
        if h.kind == "correction_candidate":
            tags.append("糾正候選")
        elif h.kind == "decision_candidate":
            tags.append("決策候選")
        if h.copies > 1:
            tags.append(f"另有 {h.copies - 1} 份相同紀錄")
        tag = "　".join(tags)
        print(f"  {i}. {_local(h.ts)}　{tag}")
        print(f"     {h.snippet}")
        print(f"     {Path(h.file).name[:8]}…:{h.start_line}-{h.end_line}")
        if h.superseded_by:
            print(f"     ! 之後有人糾正過同一批檔案：{'、'.join(h.superseded_by)}")
            print(f"       這一段的講法可能已經不算數，讀之前先看那幾處。")
        print()

    print("  以上是位置，不是答案。要用的話去讀原文，只讀需要的那一段。")
    if not include_current:
        print("  （已排除當前 session。要含它加 --include-current）")
    print()
    return 0


def main(argv: list[str]) -> int:
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2
    if args[0] == "index":
        return cmd_index(args[1:])
    inc = "--include-current" in args
    args = [a for a in args if a != "--include-current"]
    return cmd_recall(" ".join(args), include_current=inc)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
