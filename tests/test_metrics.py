"""§33.1 Metric Provenance Contract。

這一組守的是四件事，每一件都對著一個具體的作弊路徑：

1. 25 欄逐字對得上規格，而且缺一欄組不起來
2. 材料類別與層只收規格列的枚舉，歸不了類的**登記不了**
3. 缺席一定要附理由，沒理由的缺席擋下來
4. `releasable` 是算出來的，六項缺一項就不夠格

第 2 條是這一組最重要的。這個專案最常報的數字（全套幾綠）照 §33.1
登記不了，因為 pytest 那一套的材料歸不進規格六類。
**有一條測試釘住它登記不了** —— 不是釘住它登記得了。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "forseti-cli"))

import metrics as MT  # noqa: E402


def _ok_kwargs(**over):
    """一組能過的最小輸入。每一欄都是測試自己給的，不從環境撈。"""
    kw = dict(
        metric_name="接手閘門通過率",
        semantic_definition="十四題裡答對且附得出出處的題數 / 十四題",
        numerator=9,
        denominator=14,
        sample_count_N=14,
        material_class="synthetic",
        system_layer="end-to-end",
        measured_by="test",
        verification_method="逐題人工比對",
        applicability_scope="這一條 session",
        target_environment=MT.absent(MT.UNKNOWN, "沒有地方記錄目標環境"),
        model_id="claude-opus-5",
        model_hash=MT.absent(MT.UNKNOWN, "提供端沒有給"),
        config_hash=MT.absent(MT.UNKNOWN, "jsonl 只有 effort"),
        code_commit="abc123456789",
        seed=MT.absent(MT.UNKNOWN, "jsonl 沒有 seed 這一欄"),
        cache_state="cold",
        raw_metric_artifact=".forseti/antianchor.jsonl",
        confidence_interval=MT.absent(MT.UNKNOWN, "單次量測，沒有重複"),
        execution_environment={"python": "3.9.6"},
        measured_at=1_700_000_000.0,
    )
    kw.update(over)
    return kw


# ---- 規格那二十四欄 -----------------------------------------------------------
def test_規格那二十四欄_欄位名逐字對得上規格():
    # `docs/sources/..._v5.0_2026-09-04.md:846` 起那一段
    spec = (ROOT / "docs" / "sources" /
            "Forseti_Agent_Runtime_System_Architecture_Engineering_Spec"
            "_v5.0_2026-09-04.md").read_text(encoding="utf-8")
    body = spec.split("MetricRecord {", 1)[1].split("}", 1)[0]
    want = [ln.split("#")[0].strip() for ln in body.splitlines()]
    want = [w for w in want if w]
    # **25 欄不是 24。** 第一版這裡寫 24，是我自己數的，沒有數規格。
    # 規格那一段第一行就是 `metric_id`，它不是這一支生成的額外欄位。
    assert want == list(MT.FIELD_NAMES), (
        "規格那張表跟 FIELDS 對不上。**改的時候以規格為準** —— "
        "這裡對不上的話，下游每一個讀這份記錄的人讀到的是另一份契約")

def test_規格那二十四欄_枚舉照規格不加其他這一項():
    assert MT.MATERIAL_CLASSES == (
        "real", "synthetic", "public", "consented", "blind", "red-team")
    assert MT.SYSTEM_LAYERS == (
        "model", "wrapper", "router", "verifier", "end-to-end")
    assert "other" not in MT.MATERIAL_CLASSES
    assert "unknown" not in MT.MATERIAL_CLASSES

def test_規格那二十四欄_組得起來的記錄二十四欄都在():
    r = MT.build(**_ok_kwargs())
    assert r["ok"], r.get("why")
    assert list(r["record"]) == list(MT.FIELD_NAMES)
    assert r["record"]["metric_id"].startswith("m-")


# ---- 缺一欄就組不起來 ----------------------------------------------------------
@pytest.mark.parametrize("field", MT.REQUIRED_FROM_CALLER)
def test_缺一欄就組不起來_呼叫者必填的每一欄拿掉都會被擋(field):
    kw = _ok_kwargs()
    kw.pop(field)
    r = MT.build(**kw)
    assert not r["ok"]
    assert any(f"`{field}`" in w for w in r["why"]), r["why"]

def test_缺一欄就組不起來_沒宣告缺席的欄位跟宣告了缺席不一樣():
    kw = _ok_kwargs()
    kw.pop("cache_state")
    r = MT.build(**kw)
    assert not r["ok"]
    assert any("既沒有值也沒有宣告缺席" in w for w in r["why"])

    kw["cache_state"] = MT.absent(MT.UNKNOWN, "沒有量快取狀態")
    assert MT.build(**kw)["ok"]

def test_缺一欄就組不起來_缺席沒寫理由擋下來():
    kw = _ok_kwargs(cache_state={"absent": MT.UNKNOWN, "why": "  "})
    r = MT.build(**kw)
    assert not r["ok"]
    assert any("沒寫理由" in w for w in r["why"])

def test_缺一欄就組不起來_問題一次講完不是一次擋一條():
    kw = _ok_kwargs()
    for f in ("metric_name", "numerator", "system_layer"):
        kw.pop(f)
    r = MT.build(**kw)
    assert not r["ok"]
    assert len(r["why"]) >= 3, (
        "一次只講一條的話，人要來回三次，而三次之後會開始亂填")


# ---- 歸不了類的數字登記不了 -------------------------------------------------------
def test_歸不了類的數字登記不了_材料類別不在六種裡面就擋():
    r = MT.build(**_ok_kwargs(material_class="mixed"))
    assert not r["ok"]
    assert any("material_class" in w and "六種" in w for w in r["why"])

def test_歸不了類的數字登記不了_那句話要指出下一步是拆開不是換一個詞():
    r = MT.build(**_ok_kwargs(material_class="測試案例"))
    assert any("照分佈拆開" in w for w in r["why"]), (
        "只說「不收這個值」的話，下一個人會改成收得下的那個詞，"
        "而那正是這個契約要擋的事")

def test_歸不了類的數字登記不了_全套測試通過率照規格登記不了():
    """這個專案最常報的數字，釘住它**登記不了**。

    ROADMAP 到處寫「全套 1684 綠」。那一套混著人工構造的輸入
    與拿真實 jsonl 跑的案例，硬歸成 real 或 synthetic 其中一種
    就是編。所以這裡不是「還沒登記」，是照 §33.1 登記不了。
    """
    r = MT.build(**_ok_kwargs(
        metric_name="全套測試通過率",
        material_class="real+synthetic"))
    assert not r["ok"]

def test_歸不了類的數字登記不了_層不在五種裡面就擋():
    r = MT.build(**_ok_kwargs(system_layer="python"))
    assert not r["ok"]
    assert any("system_layer" in w for w in r["why"])

def test_歸不了類的數字登記不了_分母零不是一個比率():
    r = MT.build(**_ok_kwargs(denominator=0))
    assert not r["ok"]
    assert any("denominator" in w for w in r["why"])


# ---- 結構性缺席不用呼叫者自己寫 -----------------------------------------------------
def test_結構性缺席不用呼叫者自己寫_三欄自動帶入而且理由跟contract一致():
    kw = _ok_kwargs()
    for k in ("dataset_manifest_hash", "split_hash", "overlap_score"):
        assert k not in kw
    rec = MT.build(**kw)["record"]
    for k in ("dataset_manifest_hash", "split_hash", "overlap_score"):
        assert rec[k]["absent"] == MT.NOT_APPLICABLE
        assert rec[k]["why"]
    assert "不是訓練任務" in rec["dataset_manifest_hash"]["why"]

def test_結構性缺席不用呼叫者自己寫_NOT_APPLICABLE跟UNKNOWN是兩種():
    """下一步不一樣:一個沒有下一步，一個要去要提供端給。"""
    assert MT.NOT_APPLICABLE != MT.UNKNOWN
    rec = MT.build(**_ok_kwargs())["record"]
    assert rec["split_hash"]["absent"] == MT.NOT_APPLICABLE
    assert rec["seed"]["absent"] == MT.UNKNOWN


# ---- 夠不夠格是算出來的 ---------------------------------------------------------
def test_夠不夠格是算出來的_六項對得上規格那句話():
    keys = [k for k, _, _ in MT.ASPECTS]
    assert keys == ["ruler", "material", "layer", "denominator",
                    "environment", "lineage"]

def test_夠不夠格是算出來的_這個專案的記錄現在不夠格而且說得出缺哪一項():
    q = MT.qualification(MT.build(**_ok_kwargs())["record"])
    assert not q["releasable"]
    assert any("血緣" in w for w in q["why_not"])

def test_夠不夠格是算出來的_六項全齊才夠格():
    kw = _ok_kwargs(
        target_environment="zeus-gx10",
        model_hash="sha256:abcd",
        config_hash="sha256:efgh",
        seed=1234)
    q = MT.qualification(MT.build(**kw)["record"])
    assert q["releasable"], q["why_not"]
    assert q["satisfied"] == q["total"] == 6

def test_夠不夠格是算出來的_一項裡面缺一欄整項就不齊不算大部分有():
    kw = _ok_kwargs(
        target_environment="zeus-gx10",
        config_hash="sha256:efgh",
        seed=1234)          # model_hash 仍然缺
    q = MT.qualification(MT.build(**kw)["record"])
    assert not q["releasable"]
    lineage = [a for a in q["aspects"] if a["key"] == "lineage"][0]
    assert not lineage["ok"]
    assert [m["field"] for m in lineage["missing"]] == ["model_hash"]

def test_夠不夠格是算出來的_降級的值不算齊():
    """HEAD 拿得到但工作區跟它不一致，那個 hash 指不到跑的程式碼。"""
    kw = _ok_kwargs(
        target_environment="zeus-gx10",
        model_hash="sha256:abcd",
        config_hash="sha256:efgh",
        seed=1234,
        code_commit=MT.degraded("abc123456789", "工作區有 17 個檔案不一致"))
    q = MT.qualification(MT.build(**kw)["record"])
    assert not q["releasable"]
    lineage = [a for a in q["aspects"] if a["key"] == "lineage"][0]
    assert lineage["missing"][0]["kind"] == "DEGRADED"

def test_夠不夠格是算出來的_降級的理由寫進jsonl再讀回來仍然判得出(tmp_path):
    """登記當下判得出、重讀之後判不出來的話，不會有任何錯誤訊息。"""
    kw = _ok_kwargs(
        code_commit=MT.degraded("abc123456789", "工作區有檔案不一致"))
    rec = MT.build(**kw)["record"]
    p = tmp_path / "m.jsonl"
    MT.register(rec, path=p)
    back = MT.load(path=p)[0]
    q = MT.qualification(back)
    lineage = [a for a in q["aspects"] if a["key"] == "lineage"][0]
    assert any(m["kind"] == "DEGRADED" for m in lineage["missing"])


# ---- 登記簿 ---------------------------------------------------------------
def test_登記簿_不是build出來的東西登記不進去(tmp_path):
    p = tmp_path / "m.jsonl"
    res = MT.register({"metric_name": "隨便"}, path=p)
    assert not res["ok"]
    assert "build()" in res["why"]
    assert not p.exists()

def test_登記簿_寫得進去也讀得回來(tmp_path):
    p = tmp_path / "m.jsonl"
    rec = MT.build(**_ok_kwargs())["record"]
    assert MT.register(rec, path=p)["ok"]
    rows = MT.load(path=p)
    assert len(rows) == 1
    assert rows[0]["metric_id"] == rec["metric_id"]

def test_登記簿_按材料分組不是一個總數(tmp_path):
    p = tmp_path / "m.jsonl"
    MT.register(MT.build(**_ok_kwargs(material_class="synthetic"))["record"],
                path=p)
    MT.register(MT.build(**_ok_kwargs(material_class="real",
                                      metric_name="另一個"))["record"],
                path=p)
    d = MT.by_distribution(path=p)
    assert d["total"] == 2
    assert [g["material_class"] for g in d["distributions"]] == \
           ["real", "synthetic"]

def test_登記簿_空的時候說得出誰去做什麼才會有值(tmp_path):
    d = MT.by_distribution(path=tmp_path / "沒有這個檔.jsonl")
    assert d["total"] == 0
    assert "沒有人登記" in d["why_empty"] or "0 筆" in d["why_empty"] \
        or "登記一筆" in d["why_empty"]

def test_登記簿_這一支不自動登記任何東西(tmp_path):
    """讀一次不會長出記錄。自動登記唯一辦得到的方式是編欄位。"""
    p = tmp_path / "m.jsonl"
    MT.by_distribution(path=p)
    MT.load(path=p)
    assert not p.exists()


# ---- 接進交接契約 ------------------------------------------------------------
def test_接進交接契約_那一欄不再是沒有資料來源(tmp_path):
    import contract as CT
    v = CT._metrics_field(path=tmp_path / "沒有這個檔.jsonl")
    assert isinstance(v, CT.Empty), type(v)
    assert "metrics.py" in v.why
    assert "不自動登記" in v.why

def test_接進交接契約_有登記的時候帶得出值(tmp_path):
    import contract as CT
    p = tmp_path / "m.jsonl"
    MT.register(MT.build(**_ok_kwargs())["record"], path=p)
    v = CT._metrics_field(path=p)
    assert isinstance(v, dict)
    assert v["total"] == 1

def test_接進交接契約_總數與夠格數兩個都報(tmp_path):
    p = tmp_path / "m.jsonl"
    MT.register(MT.build(**_ok_kwargs())["record"], path=p)
    d = MT.by_distribution(path=p)
    assert d["total"] == 1
    assert d["releasable"] == 0, (
        "只報夠格數的話，一筆血緣不齊的記錄會從畫面上消失，"
        "而那一筆正是要有人去補提供端的那一筆")


# ---- CLI ---------------------------------------------------------------
def test_CLI_指令接在forseti底下():
    src = (ROOT / "apps" / "forseti-cli" / "forseti.py").read_text(
        encoding="utf-8")
    assert 'cmd == "metric"' in src, (
        "沒有入口的模組是缺口不是設計 —— antianchor 那一輪的教訓")
    assert "metric [list|show|template|register]" in src

def test_CLI_模板每一欄都在而且必填的看得出來(capsys):
    assert MT.main(["template"]) == 0
    out = capsys.readouterr().out
    tpl = json.loads(out)
    assert set(tpl) == set(MT.FIELD_NAMES) - {"metric_id"}
    assert "一定要填" in tpl["material_class"]

def test_CLI_模板那三欄帶的是查過的理由不是空格(capsys):
    """人現場補的那一句會跟 `contract.py` 分歧。"""
    MT.main(["template"])
    tpl = json.loads(capsys.readouterr().out)
    for k in ("model_hash", "config_hash", "seed", "target_environment"):
        why = tpl[k]["why"]
        assert "<" not in why, f"{k} 留了空格給人自己編一句"
        assert len(why) > 10

def test_CLI_register要一份json不是一長串旗標(capsys):
    assert MT.main(["register"]) == 2
    assert "template" in capsys.readouterr().out

def test_CLI_擋下來的時候把每一條都印出來(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"metric_name": "只有名字"}),
                   encoding="utf-8")
    assert MT.main(["register", "--from", str(bad)]) == 1
    out = capsys.readouterr().out
    assert "登記不了" in out
    assert out.count("    - ") >= 3

def test_CLI_走完整條路登記得成(tmp_path, capsys):
    f = tmp_path / "one.json"
    f.write_text(json.dumps(_ok_kwargs(), ensure_ascii=False),
                 encoding="utf-8")
    p = tmp_path / "m.jsonl"
    assert MT.main(["register", "--from", str(f), "--path", str(p)]) == 0
    out = capsys.readouterr().out
    assert "夠不夠格當 release claim：不夠" in out
    assert len(MT.load(path=p)) == 1
