#!/usr/bin/env python3
"""把 src/ 那 13,190 行 JavaScript 接到畫面上。§38

owner 2026-09-14：

    我就是靠這個提案得到這份工作
    所有功能你不能找理由，即使要程式重新寫，你都要給我做到

在這之前 `src/` 的 40 支 JavaScript 一行都沒接。我先前的說法是
「那些 detector 吃結構化事件，Widget 只有 transcript，中間缺一層」。
那個說法沒錯，但它是理由不是結論 —— 缺的那一層本來就該補。

## 怎麼接

那些模組是標準 ES module，node 直接 import 就能跑。
Python 這邊起一個 node 子行程，把要判的東西用 JSON 餵進去，
拿回 Finding。判斷邏輯留在 JavaScript 那一份，不重寫 ——
**重寫就會變成兩份會分歧的實作，而分歧的那天沒有人會發現。**

## 缺的那一層長什麼樣

detector 要的是 `unknownRef`、`resolvingClaim`、`evidenceBetween`
這種欄位，而 transcript 只有「誰說了什麼、叫了哪些工具」。
`_shape()` 就是那一層:從一輪對話推出這些欄位。

推得出來的才送進去判。**推不出來的不送** ——
餵半套資料給一個嚴謹的 detector，只會得到一堆
NOT_APPLICABLE，那比不接還糟，因為它看起來像有在跑。

零依賴（ADR-009）。node 不在就回空，不當機。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "src"

# 跑一次 node 的上限。超過就放棄 ——
# 一個會讓畫面卡住的偵測器，使用者會關掉它，那等於沒做。
TIMEOUT = 12


def node_bin() -> str | None:
    for c in ("node", "/opt/homebrew/bin/node", "/usr/local/bin/node"):
        p = shutil.which(c) or (c if Path(c).exists() else None)
        if p:
            return p
    # nvm 裝的
    nvm = Path.home() / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        vs = sorted(nvm.iterdir(), reverse=True)
        for v in vs:
            b = v / "bin" / "node"
            if b.exists():
                return str(b)
    return None


def available() -> dict:
    """這條橋通不通。通不通都要說清楚，不要靜默回空。"""
    n = node_bin()
    return {
        "ok": bool(n) and SRC.is_dir(),
        "node": n or "",
        "src": str(SRC).replace(str(REPO), "."),
        "modules": len([f for f in SRC.glob("*.js")
                        if not f.name.startswith("._")]) if SRC.is_dir() else 0,
        "why": "" if n else "找不到 node，JavaScript 那層跑不起來",
    }


_RUNNER = r"""
import { readFileSync } from 'node:fs';
const [,, srcDir, payloadFile] = process.argv;
const payload = JSON.parse(readFileSync(payloadFile, 'utf8'));
const out = { findings: [], errors: [] };

async function run() {
  const prim = await import(`${srcDir}/primitives.js`);
  out.registry = (prim.REGISTRY || []).length;

  for (const item of payload.rounds) {
    // FP-10 發現被升成成果
    try {
      if (prim.findingAsProgress) {
        const f = prim.findingAsProgress({
          claimText: item.text,
          artifactsProduced: item.writes,
          findingsOnly: item.writes === 0 && item.tools > 0,
        });
        if (f && f.verdict === 'POSITIVE')
          out.findings.push({ n: item.n, ...pick(f) });
      }
    } catch (e) { out.errors.push(`FP-10 ${e.message}`); }

    // FP-11 寫好了被升成可用了
    try {
      if (prim.statePromotionWithoutGate) {
        const f = prim.statePromotionWithoutGate({
          claimText: item.text,
          fromState: 'written',
          toState: 'verified',
          gatePassed: item.verified,
        });
        if (f && f.verdict === 'POSITIVE')
          out.findings.push({ n: item.n, ...pick(f) });
      }
    } catch (e) { out.errors.push(`FP-11 ${e.message}`); }

    // FP-19 樣本被升成母體
    try {
      if (prim.samplePopulationInference) {
        const f = prim.samplePopulationInference({
          claimText: item.text,
          sampleSize: item.tools,
          populationSize: null,
        });
        if (f && f.verdict === 'POSITIVE')
          out.findings.push({ n: item.n, ...pick(f) });
      }
    } catch (e) { out.errors.push(`FP-19 ${e.message}`); }
  }
}

function pick(f) {
  return {
    fp: f.primitive_id || '', code: f.code || '',
    why: (f.why || '').slice(0, 180),
    confidence: f.confidence ?? null,
  };
}

run().then(() => {
  console.log(JSON.stringify(out));
}).catch((e) => {
  console.log(JSON.stringify({ findings: [], errors: [String(e.message)] }));
});
"""

# 「樣本被講成母體」「發現被講成成果」這類，文字上有跡可循。
# 推不出來的不送進 detector —— 餵半套資料只會得到一堆
# NOT_APPLICABLE，那比不接還糟，因為它看起來像有在跑。
_WORTH = re.compile(
    r"全部|都沒問題|所有的?|每一[個份條]|完整|徹底|一律|"
    r"確認過|檢查過|掃過|驗過|測過|跑過|核對過")


def _shape(strands: list, limit: int = 60) -> list[dict]:
    """從一輪對話推出 detector 要的欄位。"""
    rounds = []
    for st in list(strands)[-limit:]:
        text = (getattr(st, "ai_text", "") or "").strip()
        if not text or not _WORTH.search(text):
            continue
        dots = getattr(st, "dots", [])
        writes = sum(1 for d in dots if getattr(d, "kind", "") == "write")
        rounds.append({
            "n": getattr(st, "n", 0),
            "text": text[:2000],
            "tools": len(dots),
            "writes": writes,
            "verified": writes > 0,
        })
    return rounds


def scan(strands: list) -> dict:
    """把可判的輪送進 JavaScript 那層。跑不起來就說跑不起來。"""
    av = available()
    if not av["ok"]:
        return {"ok": False, "why": av["why"], "findings": []}

    rounds = _shape(strands)
    if not rounds:
        return {"ok": True, "findings": [], "checked": 0,
                "why": "這段對話裡沒有推得出結構化欄位的輪"}

    import tempfile
    stage = "寫暫存檔"
    tmp = Path(tempfile.mkdtemp(prefix="forseti-js-"))
    # **2026-09-18：這兩個 write_text 先前在 try 外面。** 借了目錄之後、
    # 進到有 finally 的那個區塊之前，中間夾著兩個會丟 OSError 的動作，
    # 所以磁碟滿或權限不對的時候目錄留下來沒人收。決定性復現：把
    # `Path.write_text` 換成丟 OSError，`scan()` 一次留一個
    # `forseti-js-*`，而且 OSError 直接逸出這一支 —— 兩個呼叫點
    # （`desktop_api.py:3078`、`:3292`）都是 `_safe(..., default)`，
    # 帶 default 就不走 `{"error": ...}` 那條，於是畫面拿到 0 筆而
    # 說不出理由。`goalgate.py:233` 與 `blast.py:667` 從一開始就是
    # 「mkdtemp 的下一個敘述就是那個 try」，漏的是這裡。
    try:
        runner = tmp / "run.mjs"
        runner.write_text(_RUNNER, encoding="utf-8")
        data = tmp / "payload.json"
        data.write_text(json.dumps({"rounds": rounds}, ensure_ascii=False),
                        encoding="utf-8")
        stage = "叫 node"
        r = subprocess.run(
            [av["node"], str(runner), str(SRC), str(data)],
            capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"ok": False, "why": f"node 超過 {TIMEOUT} 秒沒回",
                "findings": []}
    except OSError as e:
        # **`stage` 不是裝飾。** 把寫檔失敗講成「叫不動 node」是一句
        # 假指控，而這個專案 2026-09-18 上一輪才為了同一個形狀
        # （紅燈指著沒做錯事的 `blast.py`）花掉一輪。
        return {"ok": False, "why": f"{stage}失敗：{e}", "findings": []}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if r.returncode != 0:
        return {"ok": False, "why": (r.stderr or "")[:200], "findings": []}
    try:
        out = json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "why": "node 回的不是 JSON", "findings": []}
    out["ok"] = True
    out["checked"] = len(rounds)
    return out


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "check":
        print(json.dumps(available(), ensure_ascii=False))
        return 0
    sys.path.insert(0, str(Path(__file__).parent))
    import tracker as TK
    t = TK.latest_session()
    if not t:
        print(json.dumps({"ok": False, "why": "找不到 transcript"},
                         ensure_ascii=False))
        return 1
    tk = TK.Tracker(t)
    tk.poll()
    print(json.dumps(scan(tk.strands), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
