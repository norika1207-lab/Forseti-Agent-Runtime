/**
 * Forseti M0：採集層
 *
 * 前面五個機制都是純函數，都在等同一件事：有人餵資料給它們。
 * 這個模組就是那個餵食口，但它不去讀檔案、不監聽任何東西。
 * 宿主把自己環境裡的原始事件丟進來，這裡負責轉成中性格式再分流出去。
 *
 * 為什麼要有中性格式：coverage.js 吃的是 { name, input, at }，
 * admission.js 的 windowConflicts 吃的是 { file_path, agent_id, at }。
 * 兩個形狀不一樣，而且宿主的原始形狀又是第三種。
 * 沒有這一層，每個宿主都得自己寫五份轉換，寫錯了還沒人知道。
 *
 * 零依賴。不碰檔案系統、不碰網路、不認識任何 agent runtime。
 *
 * ── 兩條實測教訓，寫死在這個模組裡 ──────────────────────────
 *
 * 一，agent 自己報的身分一律不採信。
 *     實跑環境裡試過三種認人的方式，三種都失效：
 *     alias 會漂移，自報的身分會被 fork 出來的子程序整份繼承，
 *     而看起來最可靠的 UUID 標的是「記錄流」不是「執行者」。
 *     靠自報身分找人，找錯了四次，還把訊息送進兩個完全無關的 session。
 *     唯一可靠的是宿主蓋在事件上的標記：某個時間點、某個工具呼叫、
 *     動了哪個檔案。所以這裡只收 attributed_agent（宿主蓋的），
 *     raw 裡自稱的欄位一律忽略，宿主沒蓋章就是 null，整條進 skipped。
 *
 * 二，穩定識別碼與顯示名必須分開存。
 *     實跑環境裡規則存的是內部代號、面板顯示的是使用者取的名字。
 *     使用者改了名字之後兩邊脫鉤，規則照舊送去舊代號，
 *     而且兩個視窗剛好同名時連人也分不出來送到哪去了，這就是「亂送」的根因。
 *     所以中性事件同時帶 agent_id（穩定，路由只准用它）
 *     跟 agent_label（顯示用，隨時可變，路由絕不可用）。
 *     這不是潔癖，是燒過錢才知道要分開。
 */

/** 中性事件裡認得的動作類別。 */
export const ACTIONS = Object.freeze(['READ', 'WRITE', 'SEARCH', 'OTHER']);

/** 事件被跳過的原因。一律可查，不靜默丟棄。 */
export const SKIP_REASONS = Object.freeze([
  'NOT_AN_OBJECT',      // 根本不是物件
  'NO_ATTRIBUTION',     // 宿主沒蓋章說這是誰做的（教訓一）
  'NO_TIMESTAMP',       // 沒有時間戳，衝突視窗算不出來
  'NO_FILE',            // 沒動到任何檔案，五個機制都用不上
  'UNKNOWN_TOOL',       // adapter 認不得這個工具
]);

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 一輪的邊界怎麼判：同一個 agent 的兩個事件間隔超過這個毫秒數，
   * 視為前一輪已經結束。
   *
   * 【這個值沒有實測校準過。】30 秒是從「一次工具呼叫到下一次通常不會隔這麼久」
   * 推出來的，不是量出來的。宿主如果拿得到明確的回合結束訊號，
   * 應該直接用 markTurnEnd() 而不是靠這個推。
   */
  // 【已校準】230 秒 = 真實工具間隔的 p90(130 份 transcript,n=53054)。
  // 原本 30 秒,而真實 p50 就有 21.8 秒 —— 那會把大量同一輪的動作切成不同輪。
  // 一個人的資料,不是通用常數。別的團隊請跑 tools/calibrate.mjs 用自己的分佈。
  turn_gap_ms: 230_000,
});

// ---------------------------------------------------------------------------
// 中性事件
// ---------------------------------------------------------------------------

/**
 * 建一個中性事件。所有欄位都必須是宿主給的，這裡不推測任何一個。
 *
 * @param {object} p
 * @param {number} p.at              毫秒 timestamp
 * @param {string} p.agent_id        穩定識別碼。路由只准用這個。
 * @param {string|null} p.agent_label 顯示名。會變。路由絕不可用。
 * @param {string|null} p.session_id
 * @param {string} p.tool            原始工具名，保留不改寫，方便對回宿主的紀錄
 * @param {string} p.action          READ | WRITE | SEARCH | OTHER
 * @param {string} p.file_path
 * @param {boolean} p.partial        讀取是否只讀了一部分
 */
export function createEvent({
  at, agent_id, agent_label = null, session_id = null,
  tool, action, file_path, partial = false,
} = {}) {
  if (!ACTIONS.includes(action)) {
    throw new TypeError(`Unrecognised action: ${String(action)}. Valid values: ${ACTIONS.join(' / ')}`);
  }
  if (!agent_id) throw new TypeError('agent_id is required. Without a stable id an event should not be created at all - see lesson one.');
  if (typeof at !== 'number' || !Number.isFinite(at)) {
    throw new TypeError('at must be a millisecond timestamp. Events without one belong in skipped, not filled in with a fake.');
  }
  return Object.freeze({
    at, agent_id, agent_label, session_id, tool, action, file_path, partial,
  });
}

// ---------------------------------------------------------------------------
// Adapter：宿主原始事件 → 中性事件
// ---------------------------------------------------------------------------

const WRITE_TOOLS = /^(Edit|MultiEdit|Write|NotebookEdit|str_replace|str_replace_editor|create_file|apply_patch|edit_file)$/i;
const READ_TOOLS = /^(Read|read_file|view|open_file|cat)$/i;
const SEARCH_TOOLS = /^(Grep|Glob|search|list_dir|ls|find|rg)$/i;

/**
 * 通吃型 adapter，涵蓋 Claude Code 與 Codex 常見的工具呼叫形狀。
 *
 * 認得的原始形狀（擇一即可）：
 *   { name, input: { file_path } }        Claude Code tool_use
 *   { tool_name, tool_input: { path } }   部分 hook 的形狀
 *   { type, params: { file } }            其他
 *
 * 身分只從宿主蓋章的欄位拿：attributed_agent / agent_id。
 * raw 裡如果有 self_reported_agent 之類的欄位，一律不看（教訓一）。
 *
 * @returns {object|{skip:string}} 中性事件的欄位，或帶 skip 原因的物件
 */
export function defaultAdapter(raw) {
  if (!raw || typeof raw !== 'object') return { skip: 'NOT_AN_OBJECT' };

  const agent_id = raw.attributed_agent ?? raw.agent_id ?? null;
  if (!agent_id) return { skip: 'NO_ATTRIBUTION' };

  const at = typeof raw.at === 'number' ? raw.at
    : typeof raw.timestamp === 'number' ? raw.timestamp
    : null;
  if (at == null) return { skip: 'NO_TIMESTAMP' };

  const tool = String(raw.name ?? raw.tool_name ?? raw.type ?? '');
  const input = raw.input ?? raw.tool_input ?? raw.params ?? {};
  const file_path = raw.file_path ?? input.file_path ?? input.path
    ?? input.notebook_path ?? input.file ?? null;
  // 真實資料裡有工具把 file_path 傳成陣列或物件。非字串一律當成沒有檔案,
  // 不然它會一路流到下游,直到某個 .split() 才炸,而且是在別人的機器上。
  if (typeof file_path !== 'string' || !file_path) return { skip: 'NO_FILE' };

  let action;
  if (WRITE_TOOLS.test(tool)) action = 'WRITE';
  else if (READ_TOOLS.test(tool)) action = 'READ';
  else if (SEARCH_TOOLS.test(tool)) action = 'SEARCH';
  else if (!tool) return { skip: 'UNKNOWN_TOOL' };
  else action = 'OTHER';

  return {
    at,
    agent_id,
    agent_label: raw.agent_label ?? raw.display_name ?? null,
    session_id: raw.session_id ?? null,
    tool,
    action,
    file_path,
    partial: action === 'READ' && (input.offset != null || input.limit != null),
  };
}

/**
 * 把一整串原始事件轉成中性事件。
 *
 * 被跳過的事件一律計數並附原因，不靜默丟棄。
 * 採集層靜默丟事件是最難查的一種故障：五個機制全部照跑、
 * 每個都給得出答案、每個答案都少算了一塊，而且沒有任何地方會紅。
 *
 * @returns {{events:Array, skipped:number, skipped_by_reason:object, total:number}}
 */
export function normalizeStream(rawEvents, adapter = defaultAdapter) {
  const events = [];
  const bucket = {};
  let skipped = 0;

  for (const raw of (rawEvents ?? [])) {
    const out = adapter(raw);
    if (!out || out.skip) {
      const reason = out?.skip ?? 'UNKNOWN_TOOL';
      bucket[reason] = (bucket[reason] ?? 0) + 1;
      skipped += 1;
      continue;
    }
    events.push(createEvent(out));
  }

  events.sort((a, b) => a.at - b.at);
  return Object.freeze({
    events: Object.freeze(events),
    skipped,
    skipped_by_reason: Object.freeze(bucket),
    total: (rawEvents ?? []).length,
  });
}

// ---------------------------------------------------------------------------
// 分流：中性事件 → 各機制吃得下的形狀
// ---------------------------------------------------------------------------

/**
 * 餵給 M5 coverage.js 的形狀。
 * coverage 自己有 defaultToolDepth，但那個是猜工具名；
 * 這裡已經判過 action 了，直接給它確定的深度，不必再猜一次。
 */
export function toCoverageEvents(events) {
  return Object.freeze((events ?? []).map((e) => Object.freeze({
    name: e.tool,
    file_path: e.file_path,
    at: e.at,
    input: Object.freeze(e.partial ? { file_path: e.file_path, offset: 0 } : { file_path: e.file_path }),
  })));
}

/**
 * 直接給 M5 用的深度對應，取代它的 defaultToolDepth。
 * 傳給 coverageFromEvents 的 toolDepth 參數即可。
 */
export function coverageDepthOf(ev) {
  const map = { WRITE: 'EDITED', READ: null, SEARCH: 'MENTIONED', OTHER: 'MENTIONED' };
  const action = ev.action ?? null;
  if (!action || !ev.file_path) return null;
  if (action === 'READ') {
    return { file_path: ev.file_path, depth: ev.partial ? 'READ_PARTIAL' : 'READ_FULL' };
  }
  return { file_path: ev.file_path, depth: map[action] ?? 'MENTIONED' };
}

/**
 * 餵給 M3 admission.js 的 windowConflicts 的形狀。
 * 只有寫入事件算數：兩個 agent 同時讀同一個檔案不是衝突。
 */
export function toWriteEvents(events) {
  return Object.freeze((events ?? [])
    .filter((e) => e.action === 'WRITE')
    .map((e) => Object.freeze({ file_path: e.file_path, agent_id: e.agent_id, at: e.at })));
}

/**
 * 某個 agent 這一段實際寫過哪些檔案。
 * 拿來跟它宣告的寫入範圍比對，就知道有沒有寫出界。
 */
export function actualWrites(events, agent_id) {
  const seen = new Set();
  for (const e of (events ?? [])) {
    if (e.action === 'WRITE' && e.agent_id === agent_id) seen.add(e.file_path);
  }
  return Object.freeze([...seen].sort());
}

/** 依 agent_id 分堆。路由用穩定識別碼，不用顯示名（教訓二）。 */
export function groupByAgent(events) {
  const out = new Map();
  for (const e of (events ?? [])) {
    if (!out.has(e.agent_id)) out.set(e.agent_id, []);
    out.get(e.agent_id).push(e);
  }
  for (const [k, v] of out) out.set(k, Object.freeze(v));
  return out;
}

/**
 * 同一個穩定識別碼在這段期間用過哪些顯示名。
 *
 * 回傳超過一個名字，代表使用者中途改過名。這正是實跑環境裡
 * 「規則照舊送去舊代號、面板顯示新名字」脫鉤的那一刻，
 * 宿主應該在這時候重整 UI，而不是等使用者發現送錯了。
 */
export function labelDrift(events) {
  const byAgent = new Map();
  for (const e of (events ?? [])) {
    if (!e.agent_label) continue;
    if (!byAgent.has(e.agent_id)) byAgent.set(e.agent_id, new Set());
    byAgent.get(e.agent_id).add(e.agent_label);
  }
  const drifted = [];
  for (const [agent_id, labels] of byAgent) {
    if (labels.size > 1) drifted.push(Object.freeze({ agent_id, labels: Object.freeze([...labels]) }));
  }
  return Object.freeze(drifted);
}

/**
 * 兩個不同的穩定識別碼共用同一個顯示名。
 *
 * 實跑環境裡兩個視窗同名時，光看畫面分不出訊息送去哪一個，
 * 使用者只看得到「亂送」。宿主應該在畫面上補上穩定識別碼消歧義。
 */
export function ambiguousLabels(events) {
  const byLabel = new Map();
  for (const e of (events ?? [])) {
    if (!e.agent_label) continue;
    if (!byLabel.has(e.agent_label)) byLabel.set(e.agent_label, new Set());
    byLabel.get(e.agent_label).add(e.agent_id);
  }
  const clashes = [];
  for (const [label, ids] of byLabel) {
    if (ids.size > 1) clashes.push(Object.freeze({ label, agent_ids: Object.freeze([...ids].sort()) }));
  }
  return Object.freeze(clashes.sort((a, b) => a.label.localeCompare(b.label)));
}

// ---------------------------------------------------------------------------
// 回合邊界：餵給 M2 的觸發點
// ---------------------------------------------------------------------------

/**
 * 推算每個 agent 的回合邊界，供 M2 決定何時觸發交接邊。
 *
 * 【這是推算，不是事實。】宿主如果拿得到明確的回合結束訊號，
 * 一律該用那個，不要用這裡的間隔推算。回傳的每一筆都帶 inferred: true，
 * 讓上層知道這個邊界是猜的，別把它當成 provider 給的保證。
 *
 * has_output 的判斷刻意保守：這一輪有沒有動到任何檔案。
 * 沒動任何檔案的一輪，M2 不該觸發任何邊 —— 這是實跑抓到的失敗模式，
 * 線路測試回一句「收到」也被自動交棒推給下游，兩邊白燒。
 *
 * @returns {Array<{agent_id, started_at, ended_at, event_count, files, has_output, inferred}>}
 */
export function inferTurns(events, config = DEFAULT_CONFIG) {
  const gap = config.turn_gap_ms ?? DEFAULT_CONFIG.turn_gap_ms;
  const turns = [];

  for (const [agent_id, list] of groupByAgent(events)) {
    let cur = null;
    for (const e of list) {
      if (cur && e.at - cur.last <= gap) {
        cur.last = e.at;
        cur.count += 1;
        cur.files.add(e.file_path);
        if (e.action === 'WRITE') cur.wrote = true;
        continue;
      }
      if (cur) turns.push(cur);
      cur = { agent_id, first: e.at, last: e.at, count: 1, files: new Set([e.file_path]), wrote: e.action === 'WRITE' };
    }
    if (cur) turns.push(cur);
  }

  return Object.freeze(turns
    .sort((a, b) => a.first - b.first)
    .map((t) => Object.freeze({
      agent_id: t.agent_id,
      started_at: t.first,
      ended_at: t.last,
      event_count: t.count,
      files: Object.freeze([...t.files].sort()),
      has_output: t.files.size > 0,
      wrote_files: t.wrote,
      inferred: true,
    })));
}

// ---------------------------------------------------------------------------
// 採集健康度
// ---------------------------------------------------------------------------

/**
 * 這批採集本身可不可信。
 *
 * 五個機制的答案品質上限就是這裡的品質，所以這個數字要看得到。
 * 完全沒有事件時回 null 不是 1：沒資料不等於採集完美。
 */
export function captureHealth(result) {
  const total = result?.total ?? 0;
  if (total === 0) {
    return Object.freeze({
      capture_rate: null,
      total: 0,
      skipped: 0,
      worst_reason: null,
      note: 'No events. This does not mean capture is healthy, only that there is nothing to judge.',
    });
  }
  const bucket = result.skipped_by_reason ?? {};
  let worst = null;
  for (const [reason, n] of Object.entries(bucket)) {
    if (!worst || n > worst.count) worst = { reason, count: n };
  }
  return Object.freeze({
    capture_rate: (total - result.skipped) / total,
    total,
    skipped: result.skipped,
    worst_reason: worst ? Object.freeze(worst) : null,
    note: null,
  });
}
