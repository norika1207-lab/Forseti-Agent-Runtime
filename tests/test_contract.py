"""最小交接契約。v5.0 §39.1

這一組守的是一件事：**這張表不准自己變小，缺席不准自己變成沒事。**

先前這個專案被過期狀態檔咬過一次（`PHASE_STATUS.md` 說五階沒開始，
實際三階已完成，於是有人重做一遍）。那不是文件寫錯，是沒有人在檢查
交接帶了什麼。所以這裡每一條都對著同一個方向：

一，**沒有資料來源，不准退化成空清單。** 空清單在畫面上讀起來是
    「沒有這種東西」，那是一句沒有根據的話。這條跟 `blast.py` 的
    `live_conflicts` 是同一條誠實條款。

二，**沒有理由的缺席要被抓出來。** 給 None 或整個不給那一欄，
    除了算成沒有來源，還要另外記成 undeclared。

三，**兩個覆蓋率不准合成一個。** 一個數字會被當分數，
    然後有人為了讓分數好看去改 NO_SOURCE。

四，**分母是 0 的時候回 None 不回 0。** 算不出來的比率不是 0。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import contract as C  # noqa: E402

# 注入用：一個量過了而且乾淨的工作區。
# `{"entries": [], "problem": None}` 跟 `{"entries": [], "problem": "..."}`
# 是兩件事，前者是乾淨，後者是沒量到 —— 測試裡也不准把兩者混用。
_CLEAN = {"entries": [], "problem": None}



# ---------------------------------------------------------------------------
# 表本身
# ---------------------------------------------------------------------------

def test_十一個欄位群一個都不能少():
    """§39.1 的表是 11 列。少一列就是悄悄放寬了交接標準。"""
    names = [g[0] for g in C.GROUPS]
    assert names == ["Identity", "Reality", "Model", "Data", "Execution",
                     "Metrics", "Artifacts", "Limits", "Next", "Claims",
                     "Recovery"], names


def test_欄位總數釘住():
    assert C.TOTAL_FIELDS == 31
    assert sum(len(g[2]) for g in C.GROUPS) == C.TOTAL_FIELDS


def test_欄位鍵不重複():
    keys = [f[0] for g in C.GROUPS for f in g[2]]
    assert len(keys) == len(set(keys)), "有重複的鍵，ctx 會互相蓋掉"


def test_每一欄都帶得出規格原文():
    for _, _, fields in C.GROUPS:
        for key, spec, note in fields:
            assert spec.strip(), key
            assert note.strip(), key


# ---------------------------------------------------------------------------
# 五種狀態分得開
# ---------------------------------------------------------------------------

def test_有值算PRESENT():
    assert C.classify("x")["status"] == C.STATUS_PRESENT
    assert C.classify(["a"])["status"] == C.STATUS_PRESENT
    assert C.classify(0)["status"] == C.STATUS_PRESENT, "0 是一個值，不是空的"
    assert C.classify(False)["status"] == C.STATUS_PRESENT


def test_空的跟沒有來源分得開():
    """這是整組測試裡最重要的一條。

    一個真的還沒有 checkpoint（空的），跟一個這個系統根本算不出來的
    欄位（沒有來源），在「畫面上是空白」這件事上長得一模一樣。
    合成一種，接手的人就會把後者讀成「沒有這種東西」。
    """
    empty = C.classify([])
    nosrc = C.classify(C.NoSource("因為 X 沒有實作"))
    assert empty["status"] == C.STATUS_EMPTY
    assert nosrc["status"] == C.STATUS_NO_SOURCE
    assert empty["status"] != nosrc["status"]
    assert "X 沒有實作" in nosrc["why"]


def test_算得出來沒帶跟做不到分得開():
    """NOT_CARRIED 是一條線的距離，NO_SOURCE 要先有一個物件存在。

    合成一種的後果是：今天就補得掉的那些，會被排到「等條件成熟」。
    """
    nc = C.classify(C.NotCarried("`claims._disk()` 已經會算"))
    ns = C.classify(C.NoSource("沒有實作"))
    assert nc["status"] == C.STATUS_NOT_CARRIED
    assert ns["status"] == C.STATUS_NO_SOURCE
    assert "claims._disk()" in nc["why"]


def test_有值但不合規格算DEGRADED而且值要看得到():
    c = C.classify(C.Degraded("abc123", "工作區有 84 個檔案沒進版控"))
    assert c["status"] == C.STATUS_DEGRADED
    assert "abc123" in c["shown"], "看不到值的話沒辦法判斷它壞在哪"
    assert "沒進版控" in c["why"]


def test_沒有理由的缺席要被記成undeclared():
    """給 None 而不說為什麼，本身就是一個缺陷。"""
    c = C.classify(None)
    assert c["status"] == C.STATUS_NO_SOURCE
    assert c["undeclared"] is True
    assert c["why"], "連預設理由都沒有的話，這條就沒有意義"
    assert C.classify(C.NoSource("有講理由"))["undeclared"] is False


def test_整個沒給那一欄跟給None一樣():
    """漏掉一欄跟宣告一欄沒來源，後果一樣，所以待遇要一樣。"""
    r = C.check({})
    assert r["totals"]["no_source"] == C.TOTAL_FIELDS
    assert r["totals"]["undeclared"] == C.TOTAL_FIELDS


# ---------------------------------------------------------------------------
# 覆蓋率
# ---------------------------------------------------------------------------

def test_兩個覆蓋率分開報而且分母帶得出來():
    ctx = {"project_id": "P", "objective": "O"}
    for _, _, fields in C.GROUPS:
        for key, _, _ in fields:
            ctx.setdefault(key, C.NoSource("沒有"))
    r = C.check(ctx)
    assert r["totals"]["present"] == 2
    assert r["possible"] == 2
    assert abs(r["coverage"] - 2 / C.TOTAL_FIELDS) < 1e-9
    assert abs(r["coverage_of_possible"] - 1.0) < 1e-9, (
        "扣掉沒有來源的之後，該帶的都帶了")


def test_分母是零的時候回None不回零():
    """全部都是沒有來源的時候，可能的覆蓋率算不出來。

    回 0 讀起來是「一個都沒做到」，那是一句假話。
    """
    ctx = {k: C.NoSource("沒有")
           for g in C.GROUPS for k, _, _ in g[2]}
    r = C.check(ctx)
    assert r["possible"] == 0
    assert r["coverage_of_possible"] is None
    assert r["coverage"] == 0.0


def test_沒有資料來源不算進可能的分母():
    """反過來釘：如果哪天有人把 NO_SOURCE 當成分母的一部分，這條會紅。"""
    ctx = {k: C.NoSource("沒有") for g in C.GROUPS for k, _, _ in g[2]}
    ctx["project_id"] = "P"
    r = C.check(ctx)
    assert r["possible"] == 1
    assert r["coverage_of_possible"] == 1.0


# ---------------------------------------------------------------------------
# 缺口排序
# ---------------------------------------------------------------------------

def test_今天補得掉的排在前面():
    """NOT_CARRIED 要排在 NO_SOURCE 前面。

    排錯的後果不是不好看，是一條線就補得掉的事被排到最後。
    """
    ctx = {k: C.NoSource("沒有") for g in C.GROUPS for k, _, _ in g[2]}
    ctx["stop_condition"] = C.NotCarried("欄位在 ledger 裡")
    ctx["code_commit"] = C.Degraded("abc", "工作區不乾淨")
    ctx["blockers"] = []
    r = C.check(ctx)
    order = [g["status"] for g in r["gaps"]]
    assert order[0] == C.STATUS_NOT_CARRIED
    assert order[1] == C.STATUS_DEGRADED
    assert order[2] == C.STATUS_EMPTY
    assert order[3] == C.STATUS_NO_SOURCE


def test_PRESENT不出現在缺口裡():
    ctx = {k: "v" for g in C.GROUPS for k, _, _ in g[2]}
    r = C.check(ctx)
    assert r["gaps"] == []
    assert r["totals"]["present"] == C.TOTAL_FIELDS


# ---------------------------------------------------------------------------
# 給人看的那幾行
# ---------------------------------------------------------------------------

def test_摘要要講出連理由都沒人寫的有幾個():
    r = C.check({})
    txt = "\n".join(C.summary_lines(r))
    assert "連理由都沒人寫" in txt
    assert str(C.TOTAL_FIELDS) in txt


def test_摘要不准出現英文狀態碼():
    """英文狀態碼是給程式看的。給人看的那幾行出現它就是漏了翻譯。"""
    r = C.check({"project_id": "P", "stop_condition": C.NotCarried("在 ledger")})
    txt = "\n".join(C.summary_lines(r))
    for code in (C.STATUS_NOT_CARRIED, C.STATUS_NO_SOURCE, C.STATUS_DEGRADED):
        assert code not in txt, code


def test_摘要截斷的時候要講還有幾個沒列():
    r = C.check({})
    txt = "\n".join(C.summary_lines(r, limit=3))
    assert "還有" in txt and "沒列出來" in txt


# ---------------------------------------------------------------------------
# collect：從真實狀態組 ctx
# ---------------------------------------------------------------------------

def test_collect每一欄都有人宣告():
    """collect 出來的 ctx 不准有沒人宣告的欄位。

    這條是這一支存在的理由：可以缺，但要說得出為什麼缺。
    """
    ctx = C.collect({}, {}, git=C.NoSource("測試不跑 git"), model={})
    r = C.check(ctx)
    assert r["totals"]["undeclared"] == 0, [
        g["key"] for g in r["gaps"] if g["undeclared"]]


def test_collect不會把沒有來源寫成空清單():
    """2026-09-16 19:2x：`invalidated_conclusions` 從這張清單移出去了。

    移出去的理由不是為了讓這條變綠，是 §40 的 PollutionRegistry
    實作了（`apps/forseti-cli/pollution.py`），那一欄現在有來源。
    它移到下面 `test_有來源的欄位不准再標成沒有來源` 繼續被釘住。

    2026-09-16 22:5x：`logical_agent_id` 同樣移出去了，**同樣不是
    為了變綠**。`identity.py` 實作了，那一欄的來源在
    `identity.registry()`，所以它現在是 EMPTY 不是 NO_SOURCE。
    這條變紅正是它該做的事 —— 它守的是「有來源了還寫沒有來源」，
    而那一刻它抓到的就是這件事。釘在
    `test_登記簿空的時候是來源在此刻空的_不是沒有來源`
    與下面那條真實 collect 的斷言。

    2026-09-17 20:4x：`runtime_node` 移出去了，**第三次同樣不是為了
    變綠**。`runtimenode.py` 實作了 §12.1 的 RuntimeNode，那一欄現在
    答得出是哪一台機器（`runtimenode.reference()`）。
    這條紅的時候訊息裡印的是 `{'basis': 'IOPlatformUUID', ...}` ——
    **它抓到的正是「有來源了還寫沒有來源」**，跟前兩次一模一樣。
    釘在下面 `test_runtime_node有來源之後不准再標成沒有來源`。

    2026-09-17：`metrics_by_distribution` 移出去了，**第四次同樣不是為了
    變綠**。`metrics.py` 實作了 §33.1 的 Metric Provenance Contract，
    那一欄現在讀得到登記簿。這條紅的時候訊息裡印的是一整段
    `Empty(why=...)` —— 跟前三次一模一樣，抓到的是「有來源了還寫
    沒有來源」。釘在下面 `test_metrics有來源之後不准再標成沒有來源`。

    四次都是同一個方向：這張清單只會變短，不會變長。
    哪天有一欄從這裡消失而它其實還是沒有來源，那條紅不會出現 ——
    所以移出去的每一欄都要在別處被釘住，不是只是刪掉。
    """
    ctx = C.collect({}, {}, git=C.NoSource("測試不跑 git"), model={})
    for key in ("claims_allowed",):
        assert isinstance(ctx[key], C.NoSource), key
    # 移出去的那一欄不准退化成一個沒有理由的空值。
    got = ctx["logical_agent_id"]
    assert not isinstance(got, C.NoSource), "來源在了，不准再寫沒有來源"
    assert isinstance(got, (C.Empty, str)) and got != "", \
        "空字串讀起來像「查過了，這個 agent 沒有 id」，那是一句沒有根據的話"


def test_runtime_node有來源之後不准再標成沒有來源():
    """§39.1 Reality 第二欄：現在跑在哪台機器。

    這一欄從 NO_SOURCE 移出來的那一刻起，守它的就是這一條。
    問的是三件事，缺一件那個移出去的動作就沒有被接住：

    一，不是 `NoSource` —— 來源在了。
    二，答得出是哪一台（帶得出 `node_id`）。
    三，**不是空字串也不是空 dict** —— 空的讀起來像
        「查過了，這台機器沒有識別碼」，那是一句沒有根據的話。

    不斷言 node_id 的值，那是這台機器的事實，換一台就不一樣。
    """
    ctx = C.collect({}, {}, git=C.NoSource("測試不跑 git"), model={})
    got = ctx["runtime_node"]
    assert not isinstance(got, C.NoSource), "來源在了，不准再寫沒有來源"
    assert isinstance(got, dict) and got.get("node_id"), got
    assert C.classify(got)["status"] == C.STATUS_PRESENT


def test_metrics有來源之後不准再標成沒有來源(tmp_path):
    """§39.1 Metrics 那一欄：現在的數字，附出處契約。

    這一欄從 NO_SOURCE 移出來的那一刻起，守它的就是這一條。
    問的是三件事：

    一，不是 `NoSource` —— `metrics.py` 在了。
    二，登記簿空的時候是 `Empty`，而那句理由要指得出誰去做什麼
        它才會有值。空的 `Empty` 跟一個死路長得一模一樣。
    三，**不准自動登記**。這一欄最容易的作弊是拿現成的數字配一組
        猜出來的欄位登記上去，讓 0 變 1。讀一次不准長出檔案。

    用 tmp_path 當登記簿路徑，不讀正本 —— 正本的筆數會變，
    這條規則不會。
    """
    empty = tmp_path / "沒有這個檔.jsonl"
    got = C._metrics_field(path=empty)
    assert not isinstance(got, C.NoSource), "來源在了，不准再寫沒有來源"
    assert isinstance(got, C.Empty)
    assert "metric template" in got.why, "空的時候要指得出下一步是什麼"
    assert not empty.exists(), "讀一次不准長出登記簿"


def test_有來源的欄位不准再標成沒有來源(tmp_path):
    """§40 登記簿存在，所以這一欄永遠不是 NoSource。

    空的登記簿回空清單，而空清單在 `check()` 那邊是 EMPTY —— 
    「來源在，此刻沒有未解決的污染」跟「這個系統沒有污染登記簿」
    是兩件事，讀起來卻很像，所以要分開釘。

    用 tmp_path 當 repo，不讀正本 —— 正本的筆數會變，這條規則不會。
    """
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={}, repo=tmp_path)
    got = ctx["invalidated_conclusions"]
    assert not isinstance(got, C.NoSource)
    assert got == []


def test_未解決的污染會出現在交接契約裡(tmp_path):
    """真的登一筆進去，那句話要帶得到交接檔這一欄。"""
    import sys
    sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))
    import pollution
    log = tmp_path / ".forseti" / "pollution.jsonl"
    r = pollution.record(
        original_claim="某個結論",
        corrected_claim="其實是另一回事",
        failure_mechanism="從畫面缺推論後端缺",
        source_events=["某檔:1"],
        verifier="測試",
        radius_basis="沒量",
        path=log)
    assert r["ok"] is True
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={}, repo=tmp_path)
    got = ctx["invalidated_conclusions"]
    assert len(got) == 1
    assert "某個結論" in got[0]
    assert "從畫面缺推論後端缺" in got[0]


def test_collect帶得出實際跑過的指令():
    snap = {"rows": [{"dots": [
        {"label": "Bash", "detail": "pytest -q"},
        {"label": "Read", "detail": "a.py"},
    ]}]}
    ctx = C.collect(snap, {}, git=C.NoSource("x"), model={})
    assert ctx["commands_run"] == ["pytest -q"]


def test_collect的時間戳不會是空的():
    """這一欄問的是「這份交接什麼時候寫的」，答案永遠算得出來。"""
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={})
    assert C.classify(ctx["timestamp"])["status"] == C.STATUS_PRESENT


def test_有effort就標成不合規格不標成有():
    """只有 effort 不等於有模型設定。

    標成 PRESENT 會讓人以為交接帶得出「這個輸出是怎麼產生的」，
    而 temperature 這類真正決定輸出的東西一個都沒有。
    """
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={"effort": "high"})
    c = C.classify(ctx["model_config"])
    assert c["status"] == C.STATUS_DEGRADED
    assert "temperature" in c["why"]


def test_沒有模型資訊的時候是空的不是編一個():
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={})
    assert C.classify(ctx["model_identity"])["status"] == C.STATUS_EMPTY


def test_git乾淨才算數():
    """HEAD 單獨拿出來會說謊：它指到的可能不是現在跑的程式碼。"""
    ctx = C.collect({}, {}, git="abc123def456", model={})
    assert C.classify(ctx["code_commit"])["status"] == C.STATUS_PRESENT
    ctx2 = C.collect({}, {}, git=C.Degraded("abc123", "工作區有 84 個檔案沒進版控"),
                     model={})
    assert C.classify(ctx2["code_commit"])["status"] == C.STATUS_DEGRADED


def test_git_head對非repo回沒有來源不回空字串(tmp_path):
    v = C.git_head(tmp_path)
    assert isinstance(v, (C.NoSource, C.Degraded)), v
    if isinstance(v, C.NoSource):
        assert v.why


def test_git_head對這個repo回得出東西():
    """實際跑一次。回什麼都可以，但不准是沒有理由的 None。"""
    v = C.git_head()
    assert v is not None
    assert C.classify(v)["status"] in (
        C.STATUS_PRESENT, C.STATUS_DEGRADED, C.STATUS_NO_SOURCE)
    assert C.classify(v)["undeclared"] is False


def test_model_from_transcript讀不到檔不會炸(tmp_path):
    assert C.model_from_transcript(None) == {}
    assert C.model_from_transcript(tmp_path / "不存在.jsonl") == {}


def test_model_from_transcript讀得出模型(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"type":"user","message":{"content":"hi"}}\n'
                 '不是 json 的一行\n'
                 '{"type":"assistant","message":{"model":"claude-opus-5"}}\n',
                 encoding="utf-8")
    assert C.model_from_transcript(p)["model"] == "claude-opus-5"


def test_report是collect加check():
    r = C.report({}, {}, git=C.NoSource("x"), model={})
    assert r["totals"]["total"] == C.TOTAL_FIELDS
    assert r["spec"].startswith("v5.0 §39.1")


# ---------------------------------------------------------------------------
# 產出的內容雜湊（2026-09-16 17:5x 從 NOT_CARRIED 接上）
#
# 這一組守的是一件事：**這一欄不准看起來比它實際上強。**
# 一個雜湊值讀起來像「這份交接證明了產出是什麼」，而它證明的只有
# 「此刻磁碟上是什麼」。中間被誰改過，這裡看不出來。
# ---------------------------------------------------------------------------

def test_借的是claims那一支():
    """不自己再寫一次 sha256。兩份會分歧，而分歧那天沒有錯誤訊息。

    這條釘住被借的那一支還在、還回得出 contentHash。
    哪天它改名或改掉回傳欄位，這裡紅，
    而不是每一筆產出靜默地變成「算不出雜湊」。
    """
    d = C._claims_disk()
    assert callable(d)
    import inspect
    assert inspect.getmodule(d).__name__ == "claims"


def test_雜湊跟hashlib自己算的一致(tmp_path):
    import hashlib
    f = tmp_path / "a.txt"
    f.write_bytes(b"forseti")
    got = C.artifact_hashes([str(f)])
    assert len(got) == 1
    assert got[0]["state"] == "ok"
    assert got[0]["hash"] == hashlib.sha256(b"forseti").hexdigest()[:16]
    assert got[0]["bytes"] == 7


def test_不存在的檔是missing不是unmeasured(tmp_path):
    """兩種原因不准併成一種。

    一個已經被刪掉的產出，意思是「這份交接指向不存在的東西」；
    一個讀不到的產出不是。併成一個 None 之後這兩句話長得一模一樣。
    """
    got = C.artifact_hashes([str(tmp_path / "沒有這個檔")])
    assert got[0]["state"] == "missing"
    assert got[0]["hash"] is None


def test_量不到的不准被記成不存在():
    """權限不足讀不到，不等於它不在那裡。跟 `claims._disk()` 同一條理由。"""
    def fake(path, cwd=None):
        return {"existence": "unknown", "byteSize": None, "contentHash": None}
    got = C.artifact_hashes(["x"], disk=fake)
    assert got[0]["state"] == "unmeasured"


def test_存在但讀不出內容算量不到():
    """`_disk()` 的 OSError 分支：existence True、contentHash None。"""
    def fake(path, cwd=None):
        return {"existence": True, "byteSize": 12, "contentHash": None}
    got = C.artifact_hashes(["x"], disk=fake)
    assert got[0]["state"] == "unmeasured"
    assert got[0]["bytes"] == 12


def test_目錄存在但沒有內容雜湊(tmp_path):
    got = C.artifact_hashes([str(tmp_path)])
    assert got[0]["state"] == "dir"
    assert got[0]["hash"] is None


def test_空清單就是空清單_不補任何東西():
    assert C.artifact_hashes([]) == []
    assert C.artifact_hashes(None) == []


def test_雜湊不宣稱自己是產出當下的():
    """欄位名不准寫成這個系統證明不了的話。"""
    def fake(path, cwd=None):
        return {"existence": True, "byteSize": 1, "contentHash": "aa"}
    row = C.artifact_hashes(["x"], disk=fake)[0]
    assert "hashed_at" in row and isinstance(row["hashed_at"], float)
    assert not any("produced" in k or "written" in k for k in row)


def test_artifact_hashes接上之後不再是算得出來沒帶(tmp_path):
    """先前這一欄是 NOT_CARRIED，理由是沒有人對產出清單跑 `_disk()`。"""
    f = tmp_path / "b.txt"
    f.write_bytes(b"x")
    snap = {"rows": [{"dots": [{"label": "Write", "detail": str(f)}]}]}
    ctx = C.collect(snap, {}, git=C.NoSource("x"), model={}, worktree=_CLEAN)
    assert C.classify(ctx["artifact_hashes"])["status"] == C.STATUS_PRESENT
    assert ctx["artifact_hashes"][0]["state"] == "ok"


def test_沒有產出路徑的時候是空的不是沒有來源():
    """空是對的狀態，不是失敗。EMPTY 跟 NO_SOURCE 是兩件事。

    這裡要注入一個乾淨的工作區。不注入的話 `collect()` 會去跑真的
    `git status`，於是這條測試的結果變成「此刻這個 repo 有沒有改動」，
    那不是它要測的東西。
    """
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={}, worktree=_CLEAN)
    assert ctx["artifact_paths"] == []
    assert C.classify(ctx["artifact_hashes"])["status"] == C.STATUS_EMPTY


# ---------------------------------------------------------------------------
# 停止條件（同一輪從 NOT_CARRIED 接上）
# ---------------------------------------------------------------------------

def test_stop_condition從work帶進來():
    work = {"tasks": [{"id": "T-1", "stop_conditions": ["owner 說停", "出現矛盾"]}]}
    ctx = C.collect({}, work, git=C.NoSource("x"), model={})
    assert C.classify(ctx["stop_condition"])["status"] == C.STATUS_PRESENT
    assert "owner 說停；出現矛盾" in ctx["stop_condition"][0]
    assert ctx["stop_condition"][0].startswith("T-1")


def test_沒有停止條件的任務不補一個預設值():
    """編出來的停止條件比沒有危險，它看起來像有人想過。"""
    work = {"tasks": [{"id": "T-1", "objective": "做事"},
                      {"id": "T-2", "stop_conditions": []},
                      {"id": "T-3", "stop_conditions": ["  ", ""]}]}
    ctx = C.collect({}, work, git=C.NoSource("x"), model={})
    assert ctx["stop_condition"] == []
    assert C.classify(ctx["stop_condition"])["status"] == C.STATUS_EMPTY


def test_兩欄接上之後表裡沒有算得出來沒帶的了():
    """這一輪的出口條件：NOT_CARRIED 歸零。

    歸零不代表交接完整 —— 另外兩種缺席（沒有資料來源、有來源此刻空的）
    照樣在，而且不准被這一條掩蓋。所以下面那兩個斷言一起釘。
    """
    work = {"tasks": [{"id": "T-1", "stop_conditions": ["owner 說停"]}]}
    snap = {"rows": [{"dots": [{"label": "Write", "detail": __file__}]}]}
    rep = C.report(snap, work, git=C.NoSource("x"), model={}, worktree=_CLEAN)
    assert rep["totals"]["not_carried"] == 0
    assert rep["totals"]["no_source"] > 0
    assert rep["totals"]["undeclared"] == 0


def test_工具點那一半看不到Bash改的檔_而且不准去猜():
    """釘住一個**已知的漏**，不是釘住一個功能。

    工具點那一半只認得 Write / Edit / NotebookEdit。2026-09-16 那一輪
    全程用 Bash 改檔，所以它改了五個檔案而這一欄是空的，
    空在畫面上讀起來像「這一輪沒有產出」，那是一句錯的話。

    **2026-09-16 18:2x 補的是工作區那一半，不是這一半。** 用 Bash 改的
    檔案現在看得到了，看得到的理由是 `git status` 量出來的，
    不是從指令字串裡認出來的 —— 那個差別就是這條測試守的東西。

    哪天有人要從 Bash 指令裡抽路徑，這條會紅，
    而那個人會先讀到上面這段話，然後才決定要不要猜。
    """
    snap = {"rows": [{"dots": [
        {"label": "Bash", "detail": "cat > apps/forseti-cli/新檔.py <<EOF"},
        {"label": "Write", "detail": "真的用 Write 寫的.md"},
    ]}]}
    ctx = C.collect(snap, {}, git=C.NoSource("x"), model={}, worktree=_CLEAN)
    assert [e["path"] for e in ctx["artifact_paths"]] == ["真的用 Write 寫的.md"]
    assert "新檔.py" not in str(ctx["artifact_paths"])
    # Bash 那一筆照樣進得了 commands_run，所以它不是完全看不見，
    # 只是沒有人從那句指令裡認出「這是一個產出」。
    assert any("新檔.py" in c for c in ctx["commands_run"])


def test_髒工作區把兩種情形分開報(tmp_path):
    """「有改動沒 commit」跟「從來沒進版控」的下一步不一樣。

    前者 commit 就好；後者要先決定那些檔該不該進版控。
    一個把兩者併起來的數字指不出那個差別，
    而這個 repo 實際上同時有這兩種（實測 26 對 62）。
    """
    import subprocess

    def g(*a):
        return subprocess.run(["git", "-C", str(tmp_path), *a],
                              capture_output=True, text=True)

    if g("init", "-q").returncode != 0:
        import pytest
        pytest.skip("這台機器沒有 git")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (tmp_path / "a.txt").write_text("1", encoding="utf-8")
    g("add", "a.txt")
    g("commit", "-qm", "first")
    (tmp_path / "a.txt").write_text("2", encoding="utf-8")      # 已追蹤有改動
    (tmp_path / "b.txt").write_text("x", encoding="utf-8")      # 從來沒進版控
    (tmp_path / "c.txt").write_text("y", encoding="utf-8")

    v = C.git_head(tmp_path)
    assert isinstance(v, C.Degraded), v
    assert "1 個已追蹤但有改動" in v.why, v.why
    assert "2 個從來沒進版控" in v.why, v.why


# ---------------------------------------------------------------------------
# 工作區那一半（2026-09-16 18:2x）
#
# 先前 `artifact_paths` 只有工具點一個來源，而那個來源看不到用 Bash
# 改的檔案。這一組釘住新來源的三件事：量出來的不是猜出來的、
# 兩個來源分得出來、量不到不准長得像乾淨。
# ---------------------------------------------------------------------------

def _git(tmp_path, *files, commit=True):
    """建一個真的 git repo。假造 porcelain 字串測不到 `-z` 那件事。"""
    import subprocess
    r = tmp_path / "repo"
    r.mkdir()
    def run(*a):
        return subprocess.run(["git", "-C", str(r), *a],
                              capture_output=True, text=True)
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (r / "seed.txt").write_text("seed", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "seed")
    for f in files:
        (r / f).parent.mkdir(parents=True, exist_ok=True)
        (r / f).write_text("x", encoding="utf-8")
    return r, run


def test_worktree把已追蹤有改動跟從來沒進版控分開(tmp_path):
    """兩種的下一步不一樣：前者 commit 就好，後者要先決定該不該進版控。"""
    r, run = _git(tmp_path, "新的.py")
    (r / "seed.txt").write_text("改過了", encoding="utf-8")
    got = C.worktree_paths(r)
    assert got["problem"] is None
    byp = {e["path"]: e["vcs"] for e in got["entries"]}
    assert byp["seed.txt"] == "已追蹤但有改動"
    assert byp["新的.py"] == "從來沒進版控"


def test_非ASCII路徑要拿得到真的路徑不是跳脫字串(tmp_path):
    """**這條是 `-z` 存在的理由，不是風格偏好。**

    不用 `-z` 的時候 git 會把非 ASCII 路徑包成 C 風格跳脫
    （實測正本有一筆 `"\\351\\226\\213..."`）。那個字串當成路徑去開
    永遠是 missing，於是交接檔指向一個沒有人寫過的檔案 ——
    那正是這一欄最該避免的事。
    """
    r, _ = _git(tmp_path, "開啟Forseti.command")
    got = C.worktree_paths(r)
    paths = [e["path"] for e in got["entries"]]
    assert "開啟Forseti.command" in paths
    assert not any("\\3" in p for p in paths)
    # 而且它真的開得到 —— 這才是「路徑對」的意思
    assert (r / "開啟Forseti.command").is_file()


def test_改名那一筆的來源路徑不會被當成另一個變更(tmp_path):
    """`-z` 的 R 條目後面接的是來源路徑，不是下一個檔案。

    多算一筆的症狀是：交接檔多出一個已經不存在的路徑，
    而它會被算成 missing —— 讀起來像「產出不見了」。
    """
    import subprocess
    r, run = _git(tmp_path)
    run("mv", "seed.txt", "改名後.txt")
    got = C.worktree_paths(r)
    paths = [e["path"] for e in got["entries"]]
    assert "改名後.txt" in paths
    assert "seed.txt" not in paths
    assert len(got["entries"]) == 1


def test_量不到跟乾淨不是同一件事(tmp_path):
    """空清單加 problem 是「沒量到」，空清單沒有 problem 是「乾淨」。

    併成一種的話，git 壞掉的時候畫面上會寫「工作區乾淨」，
    那是一句這個系統證明不了的話。跟 `live_conflicts` 的 0 與 None 同一條。
    """
    notrepo = tmp_path / "空的"
    notrepo.mkdir()
    bad = C.worktree_paths(notrepo)
    assert bad["entries"] == []
    assert bad["problem"]

    r, _ = _git(tmp_path)
    ok = C.worktree_paths(r)
    assert ok["entries"] == []
    assert ok["problem"] is None


def test_量不到的時候這一欄是DEGRADED不是EMPTY():
    """EMPTY 讀起來是「量過了沒有產出」，而實情是「有一半沒量到」。"""
    bad = {"entries": [], "problem": "git status 失敗：x"}
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={}, worktree=bad)
    assert C.classify(ctx["artifact_paths"])["status"] == C.STATUS_DEGRADED
    lines = "\n".join(C.artifact_lines(ctx))
    assert "沒量到" in lines
    assert "乾淨" in lines          # 明講「沒量到不等於乾淨」


def test_兩個來源不合成一個數字():
    """工具點答「這一輪寫了什麼」，工作區答「這裡有什麼還沒進版控」。"""
    snap = {"rows": [{"dots": [{"label": "Write", "detail": "剛寫的.md"}]}]}
    wt = {"entries": [{"path": "別人改的.py", "source": "worktree",
                       "vcs": "已追蹤但有改動"}], "problem": None}
    ctx = C.collect(snap, {}, git=C.NoSource("x"), model={}, worktree=wt)
    srcs = {e["path"]: e["source"] for e in ctx["artifact_paths"]}
    assert srcs == {"剛寫的.md": "tool_point", "別人改的.py": "worktree"}
    lines = "\n".join(C.artifact_lines(ctx))
    assert "1 個" in lines
    assert "這一輪寫的" in lines


def test_同一個檔兩邊都有的時候工具點那一筆留下來():
    """工具點更精確：它知道這是這一輪寫的，工作區只知道它跟 HEAD 不一樣。"""
    snap = {"rows": [{"dots": [{"label": "Write", "detail": "同一個.py"}]}]}
    wt = {"entries": [{"path": "同一個.py", "source": "worktree",
                       "vcs": "從來沒進版控"}], "problem": None}
    ctx = C.collect(snap, {}, git=C.NoSource("x"), model={}, worktree=wt)
    assert len(ctx["artifact_paths"]) == 1
    assert ctx["artifact_paths"][0]["source"] == "tool_point"


def test_認不出來的git狀態碼不替它翻譯():
    """猜一個好聽的狀態會讓交接檔宣稱一件 git 沒講過的事。§8.3"""
    assert C._vcs_label("??") == "從來沒進版控"
    assert "不替它翻譯" in C._vcs_label("ZZ")


def test_artifact_lines印得出路徑本身_不只是數字():
    """缺口清單只印缺的。一個從缺口清單上消失的欄位，
    跟一個真的說得出產出在哪的交接，不是同一件事。"""
    wt = {"entries": [{"path": f"檔{i}.py", "source": "worktree",
                       "vcs": "從來沒進版控"} for i in range(15)],
          "problem": None}
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={}, worktree=wt,
                    disk=lambda p, cwd=None: {"existence": True,
                                              "contentHash": "a" * 64,
                                              "byteSize": 1})
    lines = "\n".join(C.artifact_lines(ctx, limit=10))
    assert "`檔0.py`" in lines
    assert "`檔9.py`" in lines
    assert "還有 5 個沒列出來" in lines


def test_雜湊快取命中的時候時間戳不跟著跳(tmp_path):
    """把它改成此刻等於宣稱剛剛量過，那是這支函式證明不了的話。"""
    import time
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    first = C.artifact_hashes([str(f)], cwd=tmp_path, cache=tmp_path)
    assert first[0]["cached"] is False
    time.sleep(0.02)
    second = C.artifact_hashes([str(f)], cwd=tmp_path, cache=tmp_path)
    assert second[0]["cached"] is True
    assert second[0]["hash"] == first[0]["hash"]
    assert second[0]["hashed_at"] == first[0]["hashed_at"]


def test_檔案變了指紋就不命中(tmp_path):
    """用時間當有效期會有一個很難查的症狀：改完檔案畫面不動，而且不報錯。"""
    f = tmp_path / "a.txt"
    f.write_bytes(b"hello")
    first = C.artifact_hashes([str(f)], cwd=tmp_path, cache=tmp_path)
    f.write_bytes(b"hello world")
    second = C.artifact_hashes([str(f)], cwd=tmp_path, cache=tmp_path)
    assert second[0]["cached"] is False
    assert second[0]["hash"] != first[0]["hash"]


def test_注入disk的時候不碰快取(tmp_path):
    """快取一個假的磁碟狀態會污染下一次真的量測。"""
    C.artifact_hashes([{"path": "x.txt"}], cwd=tmp_path, cache=tmp_path,
                      disk=lambda p, cwd=None: {"existence": True,
                                                "contentHash": "b" * 64,
                                                "byteSize": 1})
    assert not (tmp_path / ".forseti" / "cache" / "artifact_hashes.json").exists()


def test_清單裡是dict的時候雜湊要認得path那一欄(tmp_path):
    """認錯的代價不是例外，是靜默：`str({...})` 是一個永遠不存在的路徑，
    於是每一筆都回 missing，而 missing 讀起來是「交接指向不存在的東西」。"""
    f = tmp_path / "a.txt"
    f.write_bytes(b"hi")
    got = C.artifact_hashes([{"path": str(f), "source": "worktree", "vcs": ""}],
                            cwd=tmp_path)
    assert got[0]["state"] == "ok"
    assert got[0]["path"] == str(f)


def test_report把ctx一起帶回去():
    """畫面那一節要印欄位裡面的東西，重跑一次 collect 會變成第二個事實來源。"""
    rep = C.report({}, {}, git=C.NoSource("x"), model={}, worktree=_CLEAN)
    assert isinstance(rep.get("ctx"), dict)
    assert "artifact_paths" in rep["ctx"]


def test_內容變了但大小一樣的時候也不准命中(tmp_path):
    """**這條是反向驗證補出來的，不是想出來的。**

    把指紋改成只看 size，上面那條「檔案變了指紋就不命中」照樣是綠的，
    因為它的前後內容長度不一樣。一條在壞掉的實作下仍然通過的測試，
    比沒有測試糟 —— 它讓人以為那條路有人守。
    """
    f = tmp_path / "a.txt"
    f.write_bytes(b"AAAA")
    first = C.artifact_hashes([str(f)], cwd=tmp_path, cache=tmp_path)
    f.write_bytes(b"BBBB")                       # 一樣 4 bytes
    second = C.artifact_hashes([str(f)], cwd=tmp_path, cache=tmp_path)
    assert second[0]["cached"] is False
    assert second[0]["hash"] != first[0]["hash"]


def test_工作區那一半照修改時間排_新的在前(tmp_path):
    """git 給的是路徑字典序，於是前十筆永遠是每四分鐘被自動重寫的
    那幾個控制檔，而剛做出來的東西排在看不到的地方。"""
    import os
    for name, age in (("舊.py", 9000), ("新.py", 1), ("中.py", 500)):
        f = tmp_path / name
        f.write_text("x", encoding="utf-8")
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime - age))
    wt = {"entries": [{"path": n, "source": "worktree", "vcs": "從來沒進版控"}
                      for n in ("舊.py", "中.py", "新.py")], "problem": None}
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={}, worktree=wt,
                    repo=tmp_path, disk=lambda p, cwd=None: {})
    assert [e["path"] for e in ctx["artifact_paths"]] == ["新.py", "中.py", "舊.py"]


def test_量不到mtime的排最後不是排最前(tmp_path):
    """用此刻當預設會讓一個讀不到的檔案看起來像剛剛才動過。"""
    f = tmp_path / "在的.py"
    f.write_text("x", encoding="utf-8")
    wt = {"entries": [{"path": "不在的.py", "source": "worktree", "vcs": "已刪除"},
                      {"path": "在的.py", "source": "worktree", "vcs": "從來沒進版控"}],
          "problem": None}
    ctx = C.collect({}, {}, git=C.NoSource("x"), model={}, worktree=wt,
                    repo=tmp_path, disk=lambda p, cwd=None: {})
    assert [e["path"] for e in ctx["artifact_paths"]] == ["在的.py", "不在的.py"]


def test_CLI真的會印清單_用原始碼釘住():
    """交接檔那一節寫著「`python3 apps/forseti-cli/contract.py` 全部印得出來」。

    **那句話 2026-09-16 18:2x 之前是假的** —— 這一支只印缺口清單，
    一個路徑都不印。一句叫人去跑而跑了沒有東西的指示，比不寫更糟，
    它讓人以為自己查過了。

    這裡釘原始碼不是真的去跑它：跑它會呼叫 `desktop_api.strands()`，
    而那一支會寫 `.forseti/NEXT.md` —— 一條會改動正本狀態的測試，
    比這條測試守住的東西危險。作法跟 `test_handoff.py` 釘 last_good 同一條。
    """
    src = (Path(C.__file__).read_text(encoding="utf-8")
           .split('if __name__ == "__main__"')[-1])
    assert "artifact_lines" in src, "CLI 不印清單了，交接檔那句指示會變成假的"


# ── 2026-09-16 19:2x：§40 那一節的行文算在 contract，不在 handoff ──

def test_被推翻的行文空的時候整節不出現():
    """不印「目前沒有被推翻的結論」，理由見 invalidated_lines 的 docstring。"""
    assert C.invalidated_lines({"invalidated_conclusions": []}) == []
    assert C.invalidated_lines({}) == []
    assert C.invalidated_lines(None) == []


def test_被推翻的行文要講得出機制不只講數字():
    out = "\n".join(C.invalidated_lines({"invalidated_conclusions": ["甲 → 乙"]}))
    assert "甲 → 乙" in out
    assert "§40" in out
    assert "機制" in out, "§40 存的是機制不是更正後的數字，這一節要講出來"
    assert "pollution.jsonl" in out, "要給得出自己查的方法"


def test_被推翻的行文不准把交接撐大():
    rows = [f"第 {i} 句被推翻的話" for i in range(40)]
    out = C.invalidated_lines({"invalidated_conclusions": rows}, limit=6)
    body = [l for l in out if l.startswith("- ")]
    assert len(body) == 7, "6 筆加一行「還有幾筆沒列出來」"
    assert "還有 34 筆" in body[-1]


# ── 2026-09-16 22:5x：理由自己會腐爛，所以理由也要被複查 ──
#
# 這一組守的是一件先前沒有人守的事：**一句「這一欄沒有資料來源」的理由，
# 是在某一刻查過才寫下來的，而它可以在寫下來之後變成假的。**
#
# 真實事件：`logical_agent_id` 的理由寫著「§11.1 的 AgentIdentity 沒有實作
# （grep 零命中）」，而 `identity.py` 在同一天更早就做好了。跟 2026-09-16
# 早上那個 `PHASE_STATUS.md` 事故同一種病，只是腐爛的東西從階段狀態
# 換成了缺席的理由。

def test_recheck抓得到當初那次腐爛():
    """**這條是回歸測試，不是示範。**

    用當初那條被推翻的宣告，在真正的 repo 上跑一次。抓不到就代表
    這個機制對它存在的理由無效 —— 那比沒有這個機制糟，因為畫面上
    會多一節看起來有人在守的東西。
    """
    ctx = {"logical_agent_id": C.NoSource("§11.1 的 AgentIdentity 沒有實作",
                                          recheck=C._RC_AGENT_IDENTITY)}
    rows = C.recheck_all(ctx, cache=False)
    assert len(rows) == 1
    assert rows[0]["stale"] is True, "當初那個查法現在對不上了，要報出來"
    assert rows[0]["actual"] >= 1
    assert rows[0]["where"], "只說「對不上」沒有用，要指得出去看哪裡"


def test_宣告理由的那個檔自己一定要排除():
    """不排除的話每一條都會自己觸發自己 —— 那句話就寫在 contract.py 裡。"""
    def fake(base, pattern, paths):
        return [{"file": "apps/forseti-cli/contract.py", "line": 1},
                {"file": "apps/forseti-cli/other.py", "line": 2}]
    ctx = {"k": C.NoSource("理由", recheck=C.Recheck("X"))}
    rows = C.recheck_all(ctx, runner=fake, cache=False)
    assert rows[0]["files"] == ["apps/forseti-cli/other.py"]
    assert rows[0]["actual"] == 1


def test_查不成的時候不算通過也不算失敗():
    """`hits` 是 None 的時候 `stale` 不准是 True 也不准假裝查過了。

    一個沒查成的複查說成「沒有過期」，正是這一整組要防的那種假消息。
    """
    ctx = {"k": C.NoSource("理由", recheck=C.Recheck("X"))}
    rows = C.recheck_all(ctx, runner=lambda *a: None, cache=False)
    assert rows[0]["stale"] is False
    assert rows[0]["actual"] is None, "查不成要回 None 不回 0"
    assert rows[0]["files"] is None, "空清單讀起來是「查過了沒命中」"


def test_沒掛recheck的理由不會被算進來():
    """只有附了查法的才複查。沒附的不准假裝查過。"""
    ctx = {"a": C.NoSource("沒附查法"), "b": "有值",
           "c": C.NoSource("有附", recheck=C.Recheck("X"))}
    rows = C.recheck_all(ctx, runner=lambda *a: [], cache=False)
    assert [r["key"] for r in rows] == ["c"]


def test_recheck行文在沒事的時候整節不出現():
    """不印「0 條過期」。那種行會被讀成有人在守，而它只代表這一刻沒觸發。"""
    assert C.recheck_lines([]) == []
    assert C.recheck_lines(None) == []
    assert C.recheck_lines([{"key": "a", "stale": False, "actual": 0}]) == []


def test_recheck行文要講明它只是觸發器():
    """B-05：文字比對不准單獨產生結論。這句話要在畫面上，不是在註解裡。"""
    out = "\n".join(C.recheck_lines([{
        "key": "logical_agent_id", "stale": True, "actual": 2, "expect": 0,
        "pattern": "AgentIdentity", "where": ["a.py:1", "b.py:2"]}]))
    assert "不是說那句理由錯了" in out
    assert "a.py:1" in out, "要指得出去看哪裡"
    assert "AgentIdentity" in out


def test_查不成的那幾條要單獨講_不併進過期():
    out = "\n".join(C.recheck_lines([{
        "key": "k", "stale": False, "actual": None, "expect": 0,
        "pattern": "X", "where": []}]))
    assert "沒跑成" in out
    assert "既沒有被推翻也沒有被證實" in out


def test_pycache動了指紋不准跟著動(tmp_path):
    """**釘的是行為不是字串。**

    第一版這條只檢查原始碼裡有沒有 `_RC_SKIP_DIRS` 與 `--exclude-dir=`，
    反向驗證當場抓到它是假守備：把 `_rc_fingerprint` 裡那一行呼叫拿掉，
    常數與 grep 那一邊都還在，於是它照樣綠。一條永遠綠的測試比沒有
    測試糟，它讓人以為那條路有人守。

    症狀在畫面上看不見：`__pycache__` 算進指紋的話，每跑一次 python
    都可能重寫 .pyc，於是快取永遠不命中，只有 `strands` 白白慢兩秒，
    而且沒有任何錯誤訊息。2026-09-16 實測到的就是這個（cached 恆 False）。
    """
    d = tmp_path / "pkg"
    (d / "__pycache__").mkdir(parents=True)
    (d / "a.py").write_text("x = 1", encoding="utf-8")
    pyc = d / "__pycache__" / "a.cpython-313.pyc"
    pyc.write_bytes(b"\x00" * 16)
    before = C._rc_fingerprint(tmp_path, ("pkg",))
    assert before is not None
    pyc.write_bytes(b"\x01" * 64)          # 大小與 mtime 都變了
    assert C._rc_fingerprint(tmp_path, ("pkg",)) == before, \
        "pyc 變動不准讓指紋失效，否則快取永遠不命中"
    (d / "a.py").write_text("x = 2", encoding="utf-8")
    assert C._rc_fingerprint(tmp_path, ("pkg",)) != before, \
        "真的原始碼變了，指紋一定要跟著變"


def test_grep那一邊也跳過同一批目錄():
    """指紋跳過而 grep 不跳過的話，兩邊答的就不是同一個範圍。"""
    src = Path(C.__file__).read_text(encoding="utf-8")
    assert "--exclude-dir=" in src
    assert "_RC_SKIP_DIRS" in src.split("def _grep(")[-1], \
        "grep 要用同一個常數，不准自己再列一張表"


# ── logical_agent_id 這一欄從 NO_SOURCE 改成 EMPTY，那是一次更正 ──

def test_登記簿空的時候是來源在此刻空的_不是沒有來源():
    """兩者的下一步完全不同：一個是找人去登記，一個是蓋一整個系統。"""
    v = C._logical_agent_id(C.REPO, {"session": "s1"}, reg=[])
    assert isinstance(v, C.Empty)
    c = C.classify(v)
    assert c["status"] == C.STATUS_EMPTY
    assert c["why"], "EMPTY 也要說得出怎麼樣才會有值"
    assert "identity.register" in c["why"], "要指得出下一步是誰去做什麼"


def test_問不到登記簿的時候才是沒有來源():
    """`identity.registry()` 拿不到，跟它回空清單，是兩件事。"""
    v = C._logical_agent_id(C.REPO, {"session": "s1"}, reg=None)
    # 真實 repo 裡 identity 在，所以這裡用一個一定問不到的根目錄
    v2 = C._logical_agent_id(Path("/nonexistent-xyz"), {"session": "s1"},
                             reg=None)
    assert isinstance(v, (C.Empty, str)), "真實 repo 問得到"
    assert isinstance(v2, (C.Empty, C.NoSource))


def test_登記了就查得到而且要完全相符():
    reg = [{"agent_id": "A1", "aliases": ["norikaoda-56"]}]
    assert C._logical_agent_id(C.REPO, {"session": "norikaoda-56"},
                               reg=reg) == "A1"
    # 前綴一樣不算。B-05：不靠命名相似度配對身份。
    v = C._logical_agent_id(C.REPO, {"session": "norikaoda-5"}, reg=reg)
    assert isinstance(v, C.Empty)
    assert "完全相符" in v.why


def test_這一欄不准退回寫死的沒有資料來源():
    """釘住那句已經被推翻的理由不會再回來。

    §40 的作法：被推翻的結論要留得住，不是刪掉就算。
    """
    src = Path(C.__file__).read_text(encoding="utf-8")
    body = src.split("def collect(")[-1]
    assert '"logical_agent_id": _logical_agent_id(' in body
    assert "AgentIdentity 沒有實作" not in body.split("return {")[-1], \
        "那句理由已經被推翻，不准留在 collect 的回傳裡"


def test_Empty型別沒有把狀態變成六種():
    """五種狀態不准因為多一個型別就變六種。"""
    assert C.classify(C.Empty("理由"))["status"] == C.STATUS_EMPTY
    assert set(C.STATUS_ZH) == {C.STATUS_PRESENT, C.STATUS_EMPTY,
                                C.STATUS_NOT_CARRIED, C.STATUS_NO_SOURCE,
                                C.STATUS_DEGRADED}


def test_report帶著複查結果():
    rep = C.report({}, {}, worktree=_CLEAN, git="abc", model={})
    assert "recheck" in rep
    assert isinstance(rep["recheck_stale"], int)


# ── 另外四個 EMPTY 欄位的理由（2026-09-16 23:3x）──
#
# 這四欄先前是**唯一一批連理由都沒有的空欄位**：畫面上只印
# 「來源在，此刻空的」，指不出誰去做什麼它就會有值。


def _tasks(*stucks):
    return {"tasks": [{"id": f"T-{i}", "stuck": {"kind": k}}
                      for i, k in enumerate(stucks)]}


def test_四欄空的時候都說得出下一步():
    """一個空欄位跟一個說得出下一步的空欄位，先前在畫面上長得一樣。"""
    ctx = C.collect({}, {}, worktree=_CLEAN, git="x", model={})
    for f in ("blockers", "next_step", "recovery_status", "last_good_pointer"):
        c = C.classify(ctx[f])
        assert c["status"] == C.STATUS_EMPTY, f
        assert c["why"].strip(), f"{f} 是空的卻說不出為什麼"


def test_有值的時候不包成Empty():
    """理由只在空的時候出現，有值的路徑一個字都不准變。"""
    w = {"tasks": [{"id": "T-1", "next_step": {"objective": "做 X"}}],
         "blocked": ["某步驟"]}
    snap = {"checkpoints": {"total": 3, "last_good": {"id": "cp-1"}}}
    ctx = C.collect(snap, w, worktree=_CLEAN, git="x", model={})
    assert ctx["next_step"] == ["T-1　做 X"]
    assert ctx["blockers"] == ["被擋住：某步驟"]
    assert ctx["recovery_status"] == "checkpoint 3 個"
    assert ctx["last_good_pointer"] == {"id": "cp-1"}
    for f in ("next_step", "blockers", "recovery_status", "last_good_pointer"):
        assert C.classify(ctx[f])["status"] == C.STATUS_PRESENT, f


def test_沒有下一步不准一律說成等收尾():
    """`handoff.py` 付過這個代價：一句猜錯方向的指示比沒有指示糟。

    先前它對所有沒有下一步的情況都寫「可能是任務還沒拆成步驟」，
    而對正本那兩件任務那句是假的（步驟全部驗證完成了，等的是收尾）。
    """
    fin = C._next_step(_tasks("ALL_VERIFIED", "ALL_VERIFIED"))
    nos = C._next_step(_tasks("NO_STEPS"))
    assert isinstance(fin, C.Empty) and isinstance(nos, C.Empty)
    assert "收尾" in fin.why and "收尾" not in nos.why
    assert "拆" in nos.why and "拆" not in fin.why


def test_卡住的原因不只一種就不給一句總結():
    """混在一起的時候給逐件判定，不挑一個講。"""
    v = C._next_step(_tasks("ALL_VERIFIED", "NO_STEPS", "DEPS_UNMET"))
    assert isinstance(v, C.Empty)
    for k in ("ALL_VERIFIED", "NO_STEPS", "DEPS_UNMET"):
        assert k in v.why, f"{k} 沒有出現在逐件判定裡"
    assert "不只一種" in v.why


def test_認不得的kind原樣帶出來不編解釋():
    """`stuck.py` 的 kind 是一張會長的表。編一句聽起來合理的話是 §8.3 的填空。"""
    v = C._next_step(_tasks("SOME_FUTURE_KIND"))
    assert isinstance(v, C.Empty)
    assert "SOME_FUTURE_KIND" in v.why


def test_一件任務都沒有跟派不動不是同一句話():
    """下一步不一樣：一個是去建任務，一個是去看那些任務卡在哪。"""
    v = C._next_step({"tasks": []})
    assert isinstance(v, C.Empty)
    assert "沒有任務" in v.why
    assert v.why != C._next_step(_tasks("ALL_VERIFIED")).why


def test_blockers那一欄要講清楚跟BLOCKERS檔不是同一件事():
    """不講的話，這一欄的空值會跟 NEXT.md 上那一節讀起來打架。"""
    v = C._blockers_field({"blocked": []})
    assert isinstance(v, C.Empty)
    assert "BLOCKERS.md" in v.why and "known_limits" in v.why


def test_一個都沒有跟沒人標記是兩種缺法():
    """0 個的時候「去標一個」指錯方向 —— 先得有一個。"""
    none = C._last_good_pointer({"checkpoints": {"total": 0}})
    some = C._last_good_pointer({"checkpoints": {
        "total": 4, "why_no_last_good": "系統不自己挑"}})
    assert isinstance(none, C.Empty) and isinstance(some, C.Empty)
    assert "先落一個" in none.why, "0 個的下一步是先落一個"
    assert "標記" in some.why, "有 checkpoint 沒人標的下一步才是去標記"
    assert "先落一個" not in some.why, "有了還叫人先落一個就指錯方向"


def test_那句理由是借checkpoint的不是自己寫的():
    """複製一份的話，哪天那邊改了措辭兩句話會不一樣而且沒人發現。"""
    v = C._last_good_pointer({"checkpoints": {
        "total": 2, "why_no_last_good": "這一句是 checkpoint 那邊給的"}})
    assert "這一句是 checkpoint 那邊給的" in v.why
    src = Path(C.__file__).read_text(encoding="utf-8")
    body = src.split("def _last_good_pointer(")[-1].split("\ndef ")[0]
    assert "最近的那一個常常正是出事的那一個" not in body.split('"""')[-1], \
        "那句話是 checkpoint.py 的，不准在這裡再寫一份"


def test_借的是checkpoint那一支真的有在算這句話():
    """釘住來源真的存在。它改名或不再帶這個欄位的時候這條要紅。"""
    import checkpoint as CP
    s = CP.summary("一條不存在的-session")
    assert "why_no_last_good" in s, "來源沒了，`_last_good_pointer` 會靜默退成備用那句"


def test_summary沒帶那個欄位的時候不自己補一句():
    v = C._last_good_pointer({"checkpoints": {"total": 2}})
    assert isinstance(v, C.Empty)
    assert "沒有帶" in v.why and "不自己補" in v.why


def test_這四欄不准退回一個沒有理由的空值():
    """釘住這一輪的更正不會被改回去。§40 的作法。"""
    src = Path(C.__file__).read_text(encoding="utf-8")
    body = src.split("def collect(")[-1]
    for call in ("_blockers_field(work)", "_next_step(work)",
                 "_recovery_status(snap)", "_last_good_pointer(snap)"):
        assert call in body, f"{call} 沒有接上，那一欄會退回沒有理由的空值"


# ---------------------------------------------------------------------------
# 「這一份是在哪裡寫的」那一節。v5.0 §39.1 Identity + Reality
# ---------------------------------------------------------------------------
#
# 2026-09-17 21:xx 加。守的是這個檔案的一種慣性:
# **缺口清單只印缺的，所以一欄從 NO_SOURCE 變成有值之後，
# 讀的人在 `NEXT.md` 上看到的差別是「少了一行缺口」，不是「多了一個答案」。**
#
# 同一個形狀先前撞過一次（`artifact_lines`，2026-09-16 18:2x:
# artifact_paths 早就 PRESENT，而交接檔上一個路徑都看不到）。
# 這一次是 `runtime_node`:同一份檔案的「已經發生過的決定」第一條寫著
# 換機器，而它答不出現在是哪一台。

def _rep_with(**fields):
    """組一份只有指定欄位有值的 report。其他欄位一律沒有來源。

    走真的 `check()`，不是自己編一個 groups —— 自己編的話，
    哪天狀態的判法改了，這一組測試會繼續綠而功能已經壞了。
    """
    r = C.check(dict(fields))
    r["ctx"] = dict(fields)
    return r


def test_有值的座標要印出來而且指得回欄位名():
    out = C.coordinate_lines(_rep_with(
        canonical_root="/x/y", project_id="Forseti",
        runtime_node={"node_id": "node-abc", "host": "h1",
                      "basis": "IOPlatformUUID"}))
    t = "\n".join(out)
    assert "node-abc" in t, "值算出來了就要看得到，這一節存在的唯一理由"
    assert "/x/y" in t and "Forseti" in t
    assert "`runtime_node`" in t, "要指得回 §39.1 的欄位名，不然查不回去"


def test_一欄都答不出來的時候整節不印():
    """不印一句「座標不明」。那一行讀起來像系統查過了。"""
    assert C.coordinate_lines(C.check({})) == []
    assert C.coordinate_lines(None) == []
    assert C.coordinate_lines({}) == []


def test_沒列到的座標要說得出去哪裡找():
    """「沒列」不准被讀成「沒有這一欄」。"""
    out = "\n".join(C.coordinate_lines(_rep_with(project_id="Forseti")))
    assert "`runtime_node`" in out, "答不出來的那幾欄要點名"
    assert "不是沒有這一欄" in out
    assert "少了什麼" in out, "要指去缺口那一節，理由在那邊"


def test_答不出來的座標不准在這一節印值或理由():
    """兩個地方都印同一欄，兩邊就會開始不一致。

    這一節只負責印有值的，缺席的理由歸缺口那一節管。
    """
    out = "\n".join(C.coordinate_lines(_rep_with(
        project_id="Forseti",
        runtime_node=C.NoSource("這句理由只該出現在缺口那一節"))))
    assert "這句理由只該出現在缺口那一節" not in out


def test_白名單不收已經有自己那一節的欄位():
    """產出、已推翻的結論各自有一節，收進來會印兩次。"""
    for k in ("artifact_paths", "artifact_hashes",
              "invalidated_conclusions", "known_limits"):
        assert k not in C.COORDINATE_FIELDS, f"{k} 已經有自己那一節"


def test_值走shown不自己格式化():
    """這一支不准有第二條渲染路徑。

    自己格式化的話，同一個值在缺口那一節跟這一節會長得不一樣，
    而讀的人沒辦法知道哪一邊是真的。
    """
    rep = _rep_with(project_id="Forseti")
    for g in rep["groups"]:
        for f in g["fields"]:
            if f["key"] == "project_id":
                f["shown"] = "換掉的字串"
    assert "換掉的字串" in "\n".join(C.coordinate_lines(rep))


def test_退回hostname的時候要多印一句():
    """改機器名字跟換一台機器在畫面上長得一模一樣，要有東西分得出來。"""
    out = "\n".join(C.coordinate_lines(_rep_with(
        runtime_node={"node_id": "node-abc", "host": "h1",
                      "basis": "hostname"})))
    assert "不是硬體識別碼" in out
    assert "node-abc" in out, "警告不是把那個 id 藏起來"


def test_硬體識別碼算出來的不印那一句():
    out = "\n".join(C.coordinate_lines(_rep_with(
        runtime_node={"node_id": "node-abc", "host": "h1",
                      "basis": "IOPlatformUUID"})))
    assert "不是硬體識別碼" not in out


def test_那個basis名字是跟runtimenode拿的不是寫死():
    """寫死的話那邊改一個字，這句警告會靜默地永遠不成立。

    少印一句警告不會讓任何測試變紅，所以要在這裡釘住來源。
    """
    import runtimenode as RN
    assert C._basis_uuid_name() == RN.BASIS_UUID
    src = Path(C.__file__).read_text(encoding="utf-8")
    body = src.split("def coordinate_lines(")[-1].split("\ndef ")[0]
    assert "IOPlatformUUID" not in body, "這一支裡不准出現那個字面值"


def test_拿不到名字的時候寧可多印那一句(monkeypatch):
    """多印一句警告是安全的方向，少印那一句才會讓人誤判成沒換機器。"""
    monkeypatch.setattr(C, "_basis_uuid_name", lambda: "")
    out = "\n".join(C.coordinate_lines(_rep_with(
        runtime_node={"node_id": "node-abc", "basis": "IOPlatformUUID"})))
    assert "不是硬體識別碼" in out


# ── Recovery 那兩欄不准把碟上的事實吞掉（2026-09-17）─────────────
#
# 兩欄在「這條 session 0 個」的時候給的理由，先前只講這條線。
# 實測碟上有 3 個被人標成 last_good 的 checkpoint 分屬兩條舊 session，
# 於是那兩句話合起來讀成「完全沒有可以回去的點」。
#
# 這一組守兩件相反方向的事：事實要講出來，**而判定不准因此改變**。


def _snap_els(total_here=0, els_total=3, els_lg=3, els_sessions=2):
    return {"checkpoints": {
        "total": total_here,
        "elsewhere": {"total": els_total, "last_good": els_lg,
                      "sessions": els_sessions},
        "why_no_last_good": "這條 session 沒有任何 checkpoint 被標成 last_good",
    }}


def test_recovery_status_要講碟上還有什麼():
    v = C._recovery_status(_snap_els())
    assert isinstance(v, C.Empty), "判定不准變 —— 這條線上仍然是空的"
    assert "碟上另有 3 個" in v.why
    assert "2 條別的 session" in v.why
    assert "owner 的決定" in v.why, "不准自己替她接過來"


def test_last_good_pointer_要講碟上還有什麼():
    v = C._last_good_pointer(_snap_els())
    assert isinstance(v, C.Empty), "判定不准變"
    assert "碟上另有 3 個" in v.why
    assert "不替 owner 決定" in v.why


def test_碟上沒有別的就不多講():
    snap = _snap_els(els_total=0, els_lg=0, els_sessions=0)
    for v in (C._recovery_status(snap), C._last_good_pointer(snap)):
        assert isinstance(v, C.Empty)
        assert "碟上另有" not in v.why, "沒有的東西不准提"


def test_這條線上有checkpoint就不走那條理由():
    snap = _snap_els(total_here=2)
    assert C._recovery_status(snap) == "checkpoint 2 個", "有值就是有值"
