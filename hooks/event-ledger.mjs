/**
 * Event Ledger 的寫入端。給 hook 用。
 *
 * 正本是 `.forseti/event_ledger.jsonl`，讀取與索引在
 * `apps/forseti-cli/event_ledger.py`。**寫入端刻意不經過 Python。**
 *
 * 理由是量出來的：2026-09-10 實測，起一個 Python 直譯器加 import 加
 * append，端到端 p95 是 140.8 ms，而階段 1 的熱路徑預算是 p95 < 50ms
 * （`docs/build-plan.md:330`）。大頭是直譯器啟動，不是寫檔 ——
 * append 本身只有 0.173 ms。
 *
 * node 這邊的啟動成本 hook 本來就付了，所以多寫一行檔案接近零成本。
 *
 * 這正是「正本是檔案不是資料庫」換來的東西：寫入端不必跟讀取端同語言。
 * 如果照 v5.0 §20.3 讓 SQLite 當正本，這裡就得帶一個 sqlite 綁定，
 * 或者每次去起 Python。
 *
 * ── 這個檔案絕不擋人 ────────────────────────────────────────────
 *
 * 2026-09-08 那次事故是 hook 直接 exit 2 擋掉擁有者九小時的工作。
 * 所以這裡的每一個函式都不 throw：拿不到就回 null，寫不進去就算了。
 * **記錄失敗絕不能變成工作失敗。** 一本少了幾筆的帳，比一個因為記帳
 * 而卡住的編輯器好太多。
 */

import { appendFileSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join, dirname } from 'node:path';

/**
 * 決定性的 JSON，與 Python 的 `event_ledger.canonical_json()` 逐位元組相同。
 *
 * 三件事要對齊，缺一個指紋就對不上：欄位排序、無多餘空白、
 * 非 ASCII 不跳脫。2026-09-10 用含中文、巢狀、null、浮點數、布林的
 * 樣本兩邊比對過，輸出完全一致。
 */
export function canonicalJson(o) {
  if (o === null || typeof o !== 'object') return JSON.stringify(o);
  if (Array.isArray(o)) return `[${o.map(canonicalJson).join(',')}]`;
  return `{${Object.keys(o).sort()
    .map((k) => `${JSON.stringify(k)}:${canonicalJson(o[k])}`)
    .join(',')}}`;
}

export function payloadHash(payload) {
  return createHash('sha256').update(canonicalJson(payload), 'utf8').digest('hex');
}

// v5.0 §6.2 的 canonical types，只列這個 hook 真的會產生的那幾種。
// 完整的 39 種在 apps/forseti-cli/event_ledger.py 的 TYPES。
// 兩邊不同步的話 Python 那端會拒收，那是刻意的 —— 寧可拒收也不要
// 讓一個沒人認得的 type 靜靜躺在正本裡。
export const TOOL_CALL = 'TOOL_CALL';
export const TOOL_RESULT = 'TOOL_RESULT';
export const FILE_READ = 'FILE_READ';
export const FILE_WRITE = 'FILE_WRITE';
export const MODEL_OUTPUT = 'MODEL_OUTPUT';

const WRITE_TOOLS = /^(Write|Edit|MultiEdit|NotebookEdit)$/;

/**
 * 從 Claude Code 的 hook input 決定 canonical type。
 *
 * Stop 映射到 MODEL_OUTPUT 是我的選擇不是規格明文：v5.0 §6.2 沒有
 * 「一輪回應結束」這種事件，而 Cognitive 那類裡 MODEL_OUTPUT 最接近。
 * 記在這裡是因為之後有人要對照規格時，會找不到 Stop 在哪一條。
 */
export function classify(input) {
  const ev = input?.hook_event_name;
  const tool = String(input?.tool_name || '');
  if (ev === 'PreToolUse') return TOOL_CALL;
  if (ev === 'Stop' || ev === 'SubagentStop') return MODEL_OUTPUT;
  if (ev === 'PostToolUse') {
    if (WRITE_TOOLS.test(tool)) return FILE_WRITE;
    if (tool === 'Read' || tool === 'NotebookRead') return FILE_READ;
    return TOOL_RESULT;
  }
  return null;
}

// 超過這個大小的 payload 外存，正本只留參照。
// v5.0 §20.3：Large raw payloads and artifacts should be content-addressed
// on disk/object storage and referenced from the relational ledger.
//
// 64KB 是拍的，沒有實測校準。訂這個值的考量是一行 JSONL 應該還能用
// 一般文字工具打開來看 —— 一個必須寫程式才讀得動的「正本」，
// 在需要它的時候（通常是出事的時候）等於沒有。
const INLINE_LIMIT = 64 * 1024;

function stash(dir, value) {
  const text = canonicalJson(value);
  const h = createHash('sha256').update(text, 'utf8').digest('hex');
  try {
    const box = join(dir, 'raw_payloads');
    mkdirSync(box, { recursive: true });
    const f = join(box, `${h}.json`);
    if (!existsSync(f)) writeFileSync(f, text, 'utf8');
    return { _stashed: true, _sha256: h, _bytes: Buffer.byteLength(text, 'utf8') };
  } catch {
    // 外存失敗也要留下它存在過的證據。內容沒了，事實還在。
    return { _stashed: false, _sha256: h, _bytes: Buffer.byteLength(text, 'utf8') };
  }
}

/**
 * 大的欄位外存，其餘原樣保留。
 *
 * 只換超過門檻的那幾個欄位，不是整個 payload 一起丟掉 ——
 * `tool_input` 裡通常只有 content 那一欄大，file_path 與 tool_name
 * 是最有用的部分而且很小，把它們一起外存等於為了省空間丟掉可讀性。
 */
export function shrink(payload, forsetiDir) {
  if (!payload || typeof payload !== 'object') return payload;
  const out = Array.isArray(payload) ? [] : {};
  for (const [k, v] of Object.entries(payload)) {
    const size = Buffer.byteLength(canonicalJson(v ?? null), 'utf8');
    out[k] = size > INLINE_LIMIT ? stash(forsetiDir, v) : v;
  }
  return out;
}

/**
 * 寫一筆進正本。**任何失敗都回 null，絕不 throw。**
 *
 * @returns {string|null} raw event id，寫不進去就是 null
 */
export function appendEvent(forsetiDir, input, { sessionId, projectId } = {}) {
  try {
    const type = classify(input);
    if (!type) return null;

    const timestamp = Date.now() / 1000;
    const payload = shrink({
      hook_event_name: input.hook_event_name ?? null,
      tool_name: input.tool_name ?? null,
      tool_input: input.tool_input ?? null,
      tool_response: input.tool_response ?? null,
      cwd: input.cwd ?? null,
    }, forsetiDir);

    const h = payloadHash(payload);
    const rawId = `${timestamp.toFixed(6)}-${h.slice(0, 12)}`;

    const raw = {
      id: rawId,
      provider: 'claude-code',
      provider_event_type: String(input.hook_event_name || 'unknown'),
      timestamp,
      payload,
    };
    const norm = {
      id: `n-${rawId}`,
      raw_event_id: rawId,
      type,
      session_id: sessionId || input.session_id || '',
      project_id: projectId || '',
      agent_id: input.session_id || '',
      runtime_node_id: '',
      action: String(input.tool_name || input.hook_event_name || ''),
      subject: String(input.tool_input?.file_path || input.cwd || ''),
      object: '',
      result: '',
      provenance: 'OBSERVED',
      risk: '',
      metadata: {},
    };

    const line = canonicalJson({ raw, norm });
    const f = join(forsetiDir, 'event_ledger.jsonl');
    mkdirSync(dirname(f), { recursive: true });
    appendFileSync(f, `${line}\n`, 'utf8');
    return rawId;
  } catch {
    // 這裡刻意吞掉一切。記錄失敗不能變成工作失敗 ——
    // 2026-09-08 的事故就是 hook 把自己的問題變成使用者的問題。
    return null;
  }
}
