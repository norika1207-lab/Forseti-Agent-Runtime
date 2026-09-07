/**
 * Forseti M5：Session 覆蓋範圍物件
 *
 * 回答一個五年前不存在的問題：一個活著的 session 現在「知道」哪些檔案、
 * 知道到什麼程度。這個量一旦存在，可以餵四件事：
 *   派工   誰的 context 已經熱在這塊程式碼上，就派給誰，不必重新載入
 *   去重   兩條線覆蓋範圍高度重疊 = 正在付兩次錢讀同一批檔案
 *   交接   A 交給 B 時該轉述哪些檔案 = Coverage(A) − Coverage(B)
 *   保命   哪些髒活最會吃掉主 session 的覆蓋，事前算得出來
 *
 * 零依賴。不 import Moirai 任何東西，不接 ctx，不讀 duo_state.json。
 *
 * 誠實條款（文件 7.7 雷一）：coverage 是「上界」不是精確集合。
 * session 內部的壓縮會讓它實際「記得」的比「讀過」的少，本模組無從得知。
 * 因此每個 SessionCoverage 都帶 is_upper_bound = true，不可關閉。
 *
 * 資料來源限制（文件 7.7 雷二）：只用 provider 公開事件流推得出來的東西。
 * 不讀 provider 內部狀態，不猜它記得什麼。
 */

/** 知道的深淺。順序有意義：後面的涵蓋前面的。 */
export const COVERAGE_DEPTHS = Object.freeze(['MENTIONED', 'READ_PARTIAL', 'READ_FULL', 'EDITED']);

/** 深度強弱，用於同一檔案多次事件時取最強者。 */
const DEPTH_RANK = Object.freeze({ MENTIONED: 1, READ_PARTIAL: 2, READ_FULL: 3, EDITED: 4 });

/**
 * 交接差集的預設策略：深度低於此門檻的檔案不算「已知」，
 * 因為只是被提到過不代表下游能省下讀它的成本。
 */
export const DEFAULT_CONFIG = Object.freeze({
  /** 去重警示門檻：重疊率超過此值視為重複付費 */
  duplicateThreshold: 0.6,
  /** 算交接差集時，接收方要達到這個深度才算「已經知道」 */
  knownDepth: 'READ_PARTIAL',
  /** 派工挑人時，候選必須至少覆蓋任務檔案的這個比例才算有效熱度 */
  minHotRatio: 0,
});

/** compact_risk 拿不到 provider 用量時的標記（文件 7.5 三：拿不到就不做，不要估） */
export const COMPACT_RISK_UNKNOWN = null;

function assertDepth(depth) {
  if (!DEPTH_RANK[depth]) {
    throw new TypeError(`不認得的 CoverageDepth: ${String(depth)}。合法值: ${COVERAGE_DEPTHS.join(' / ')}`);
  }
  return depth;
}

function strongerDepth(a, b) {
  if (!a) return b;
  if (!b) return a;
  return DEPTH_RANK[a] >= DEPTH_RANK[b] ? a : b;
}

/**
 * 建立一個 SessionCoverage。
 *
 * @param {object} p
 * @param {string} p.session_id
 * @param {string} p.agent_id
 * @param {object} [p.files]        { [file_path]: CoverageDepth }
 * @param {string} [p.updated_at]   ISO 時間字串；不給就是 null，不自己編時間
 * @param {number|null} [p.compact_risk]
 *        0..1。拿不到 provider 的 context 用量時必須傳 null（預設），
 *        不可以用啟發式估算。文件 7.5 三。
 */
export function createCoverage({ session_id, agent_id, files = {}, updated_at = null, compact_risk = COMPACT_RISK_UNKNOWN } = {}) {
  if (!session_id) throw new TypeError('session_id 必填');
  if (!agent_id) throw new TypeError('agent_id 必填');
  if (compact_risk !== null && !(typeof compact_risk === 'number' && compact_risk >= 0 && compact_risk <= 1)) {
    throw new TypeError('compact_risk 必須是 0..1 或 null（拿不到就 null，不要估）');
  }
  const norm = {};
  for (const [path, depth] of Object.entries(files)) norm[path] = assertDepth(depth);
  return Object.freeze({
    session_id,
    agent_id,
    files: Object.freeze(norm),
    updated_at,
    compact_risk,
    /** coverage 是上界：session 壓縮後實際記得的只會更少，不會更多。不可關閉。 */
    is_upper_bound: true,
  });
}

/**
 * 把一個檔案存取事件併進 coverage。同一檔案多次事件取最強深度。
 * 回傳新的凍結物件，不改動原物件。
 */
export function recordAccess(coverage, file_path, depth, at = null) {
  assertDepth(depth);
  if (!file_path) throw new TypeError('file_path 必填');
  const next = { ...coverage.files };
  next[file_path] = strongerDepth(next[file_path], depth);
  return createCoverage({
    session_id: coverage.session_id,
    agent_id: coverage.agent_id,
    files: next,
    updated_at: at ?? coverage.updated_at,
    compact_risk: coverage.compact_risk,
  });
}

/**
 * 從 provider 的事件流建 coverage。
 *
 * 只認公開事件流裡看得到的東西（文件 7.7 雷二）。每個事件形如
 *   { type: 'tool_use' | 'mention', name?: string, input?: object, file_path?: string, at?: string }
 * 對應關係由 toolDepth 決定，呼叫端可覆寫，因為不同 provider 的工具名不同。
 *
 * 預設對應（Claude Code / Codex 常見工具名）：
 *   Read / read_file            → READ_FULL（有 offset/limit 則 READ_PARTIAL）
 *   Edit / Write / str_replace  → EDITED
 *   Grep / Glob / search        → MENTIONED（只知道它存在，沒讀內容）
 *   其餘含 file_path 的工具     → MENTIONED
 */
export function coverageFromEvents({ session_id, agent_id, events = [], toolDepth = defaultToolDepth } = {}) {
  let cov = createCoverage({ session_id, agent_id });
  let last = null;
  for (const ev of events) {
    if (!ev || typeof ev !== 'object') continue;
    const resolved = toolDepth(ev);
    if (!resolved) continue;                       // 認不得的事件直接跳過，不猜
    const { file_path, depth } = resolved;
    if (!file_path) continue;
    cov = recordAccess(cov, file_path, depth, ev.at ?? last);
    last = ev.at ?? last;
  }
  return cov;
}

/** 預設的工具名到深度對應。認不得的回 null，呼叫端可覆寫。 */
export function defaultToolDepth(ev) {
  const name = String(ev.name ?? ev.type ?? '');
  const input = ev.input ?? {};
  const file = ev.file_path ?? input.file_path ?? input.path ?? input.notebook_path ?? null;
  if (!file) return null;
  if (/^(Edit|Write|NotebookEdit|str_replace|create_file|apply_patch)$/i.test(name)) {
    return { file_path: file, depth: 'EDITED' };
  }
  if (/^(Read|read_file|view)$/i.test(name)) {
    const partial = input.offset != null || input.limit != null;
    return { file_path: file, depth: partial ? 'READ_PARTIAL' : 'READ_FULL' };
  }
  if (/^(Grep|Glob|search|list_dir|ls)$/i.test(name)) {
    return { file_path: file, depth: 'MENTIONED' };
  }
  return { file_path: file, depth: 'MENTIONED' };
}

/** 這個 session 知道哪些檔案，依深度由強到弱排序（驗收 7.6 一）。 */
export function knownFiles(coverage, { minDepth = 'MENTIONED' } = {}) {
  assertDepth(minDepth);
  const floor = DEPTH_RANK[minDepth];
  return Object.entries(coverage.files)
    .filter(([, d]) => DEPTH_RANK[d] >= floor)
    .sort((a, b) => DEPTH_RANK[b[1]] - DEPTH_RANK[a[1]] || a[0].localeCompare(b[0]))
    .map(([file_path, depth]) => Object.freeze({ file_path, depth }));
}

/** 交集的檔案路徑集合。 */
export function intersect(a, b) {
  const bf = b.files;
  return Object.keys(a.files).filter((f) => f in bf).sort();
}

/**
 * 重疊率（驗收 7.6 二）。分母用較小的那一邊，
 * 這樣「小集合完全被大集合包住」會得到 1，那正是重複付費最嚴重的形狀。
 * 任一邊為空時回 null，不是 0：沒有資料不等於沒有重疊。
 */
export function overlapRatio(a, b) {
  const sa = Object.keys(a.files).length;
  const sb = Object.keys(b.files).length;
  if (sa === 0 || sb === 0) return null;
  return intersect(a, b).length / Math.min(sa, sb);
}

/**
 * 去重偵測：兩條線是不是在付兩次錢讀同一批檔案。
 * 回傳 { duplicated: bool|null, ratio, shared, threshold }。
 * ratio 為 null 時 duplicated 也是 null，不擅自判定為「沒重複」。
 */
export function duplicateWork(a, b, config = DEFAULT_CONFIG) {
  const ratio = overlapRatio(a, b);
  const threshold = config.duplicateThreshold ?? DEFAULT_CONFIG.duplicateThreshold;
  return Object.freeze({
    duplicated: ratio === null ? null : ratio > threshold,
    ratio,
    shared: Object.freeze(intersect(a, b)),
    threshold,
  });
}

/**
 * 交接差集（驗收 7.6 三，也是 M5 回頭強化 M2 的地方）。
 *
 * 需轉述集合 = Coverage(from) − Coverage(to)，
 * 其中「to 已經知道」的判定門檻由 config.knownDepth 決定。
 * 只是被 grep 提到過（MENTIONED）不算知道，因為下游仍得自己讀一次。
 *
 * 回傳同時附上 saved_files：因為 to 已經知道而不必轉述的檔案數，
 * 那是這個機制省下來的東西，可以被量測（驗收要求「前後對照數據」）。
 */
export function handoffDelta(from, to, config = DEFAULT_CONFIG) {
  const knownDepth = config.knownDepth ?? DEFAULT_CONFIG.knownDepth;
  assertDepth(knownDepth);
  const floor = DEPTH_RANK[knownDepth];
  const need = [];
  const saved = [];
  for (const [file, depth] of Object.entries(from.files)) {
    const theirs = to.files[file];
    if (theirs && DEPTH_RANK[theirs] >= floor) saved.push(file);
    else need.push(Object.freeze({ file_path: file, depth }));
  }
  need.sort((x, y) => DEPTH_RANK[y.depth] - DEPTH_RANK[x.depth] || x.file_path.localeCompare(y.file_path));
  const total = Object.keys(from.files).length;
  return Object.freeze({
    need_briefing: Object.freeze(need),
    saved_files: Object.freeze(saved.sort()),
    total_from: total,
    /** 省下的比例。from 為空時 null，不是 0。 */
    saved_ratio: total === 0 ? null : saved.length / total,
    known_depth: knownDepth,
    is_upper_bound: true,
  });
}

/**
 * 派工挑人：誰的 context 已經最熱在這批檔案上。
 *
 * @param {string[]} taskFiles 這個任務會碰到的檔案
 * @param {SessionCoverage[]} candidates
 * @returns {object|null} { agent_id, session_id, hot_count, hot_ratio, matched }
 *          沒有任何候選達到 minHotRatio 時回 null，不硬挑一個。
 */
export function pickHottest(taskFiles, candidates, config = DEFAULT_CONFIG) {
  const want = new Set(taskFiles ?? []);
  if (want.size === 0 || !candidates?.length) return null;
  const minRatio = config.minHotRatio ?? DEFAULT_CONFIG.minHotRatio;
  let best = null;
  for (const c of candidates) {
    const matched = [...want].filter((f) => f in c.files).sort();
    const ratio = matched.length / want.size;
    if (ratio < minRatio) continue;
    if (!best || matched.length > best.hot_count) {
      best = { agent_id: c.agent_id, session_id: c.session_id, hot_count: matched.length, hot_ratio: ratio, matched };
    }
  }
  if (!best || best.hot_count === 0) return null;
  return Object.freeze({ ...best, matched: Object.freeze(best.matched) });
}

/**
 * 保命用：這批髒活會吃掉主 session 多少「新」覆蓋。
 * 已經在主 session 覆蓋裡的檔案不算新增成本。
 * 回傳新增檔案清單與數量，不換算 token —— 那是 M1 的職責，這裡不越界估算。
 */
export function newCoverageCost(mainCoverage, taskFiles) {
  const add = (taskFiles ?? []).filter((f) => !(f in mainCoverage.files)).sort();
  return Object.freeze({
    new_files: Object.freeze(add),
    new_count: add.length,
    already_known: (taskFiles ?? []).length - add.length,
  });
}
