// Forseti M4「代價定義」純函數模組。
// 依據:Forseti_Five_Mechanisms_Handoff_v1.0_2026-09-07.md 第 6 節。
// 邊界:不 import Moirai 任何東西、不接 ctx、不讀 duo_state.json、不碰 server.js。
// 所有外部狀態(依賴圖、覆蓋資料、live scope)一律由呼叫端以參數傳入。

export const COVERAGE_LCOV = 'LCOV';
export const COVERAGE_NONE = 'NONE';

// 主指標優先順序,照文件 6.3 節。前兩者可直接轉成動作(通知誰、擋誰),
// 後兩者只是規模描述。禁止把這些維度合成單一風險分數(文件 6.8 雷一)。
export const PRIORITY_ORDER = Object.freeze([
  'live_conflicts',
  'cross_modules',
  'uncovered_d1',
  'd1_count',
  'd2_count',
]);

/**
 * 由 import 紀錄建圖。
 * imports: Array<{ from: string, to: string | null, specifier?: string }>
 *   from = 發出 import 的檔案;to = 被 import 的檔案(解析後路徑)。
 *   to 為 null(或缺)= 未解析的 import(動態 import、字串拼路徑、跨語言邊界斷點)。
 *   未解析的紀錄會完整保留,可用 unresolvedImports() 查詢,不靜默吞掉(文件 6.4 條二)。
 */
export function buildGraph(imports = []) {
  const reverse = new Map(); // to -> Set(from):誰依賴它
  const unresolved = [];
  let total = 0;
  for (const imp of imports) {
    if (!imp || typeof imp.from !== 'string') {
      throw new TypeError('import 紀錄缺少 from 欄位');
    }
    total += 1;
    if (imp.to == null) {
      unresolved.push({ from: imp.from, specifier: imp.specifier ?? null });
      continue;
    }
    if (!reverse.has(imp.to)) reverse.set(imp.to, new Set());
    reverse.get(imp.to).add(imp.from);
  }
  return { reverse, unresolved, totalImports: total };
}

/** 未解析 import 的完整清單(每筆含 from 與原始 specifier)。 */
export function unresolvedImports(graph) {
  return graph.unresolved.map((u) => ({ ...u }));
}

/** import 解析率。零筆 import 時定義為 1(沒有東西可以失敗)。 */
export function resolutionRate(graph) {
  if (graph.totalImports === 0) return 1;
  return (graph.totalImports - graph.unresolved.length) / graph.totalImports;
}

/**
 * 反向可達集:誰會被 target 的改動波及。
 * 在反向邊上做 BFS,回傳 { d1: Set, d2plus: Set }。
 * d1 = 一階(直接 import target 的檔案);d2plus = 二階以上。
 * target 自己不計入。visited 集合保證循環依賴會終止。
 */
export function reverseReachable(graph, target) {
  const d1 = new Set();
  const d2plus = new Set();
  const visited = new Set([target]);
  let frontier = [target];
  let depth = 0;
  while (frontier.length > 0) {
    depth += 1;
    const next = [];
    for (const node of frontier) {
      const dependents = graph.reverse.get(node);
      if (!dependents) continue;
      for (const dep of dependents) {
        if (visited.has(dep)) continue;
        visited.add(dep);
        (depth === 1 ? d1 : d2plus).add(dep);
        next.push(dep);
      }
    }
    frontier = next;
  }
  return { d1, d2plus };
}

// 預設模組歸屬:取路徑第一段目錄;沒有目錄的檔案歸 '(root)'。
function defaultModuleOf(filePath) {
  const idx = filePath.indexOf('/');
  return idx === -1 ? '(root)' : filePath.slice(0, idx);
}

/**
 * 計算 CostVector。五個維度 + 三個誠實欄位,欄位名照文件 6.3 節,一字不改。
 *
 * @param {object} graph      buildGraph() 的回傳值
 * @param {string} target     被改動的檔案
 * @param {object} [options]
 * @param {object|null} [options.coverage]  覆蓋資料。null = 沒有報告。
 *        有報告時形如 { source: 'LCOV', covered: Iterable<string> }(covered = 有測試覆蓋的檔案)。
 *        誠實條款(6.4 條四):沒有報告就 uncovered_d1 = null、coverage_source = 'NONE',
 *        不用啟發式估算填值。
 * @param {Array<{agent_id: string, files: Iterable<string>}>} [options.liveScopes]
 *        現在有 agent 正在動的檔案(M3 WriteScope 的內容,由呼叫端傳入,本模組不猜)。
 * @param {(filePath: string) => string} [options.moduleOf]  檔案→模組的歸屬函數
 * @returns 凍結的 CostVector
 */
export function computeCostVector(graph, target, options = {}) {
  const { coverage = null, liveScopes = [], moduleOf = defaultModuleOf } = options;
  const { d1, d2plus } = reverseReachable(graph, target);

  // 波及範圍 = d1 ∪ d2plus(不含 target 自己)
  const blast = new Set([...d1, ...d2plus]);

  const modules = new Set();
  for (const f of blast) modules.add(moduleOf(f));

  const liveFiles = new Set();
  for (const scope of liveScopes) {
    for (const f of scope.files ?? []) liveFiles.add(f);
  }
  let liveConflicts = 0;
  for (const f of blast) {
    if (liveFiles.has(f)) liveConflicts += 1;
  }

  let uncoveredD1 = null;
  let coverageSource = COVERAGE_NONE;
  if (coverage != null) {
    if (coverage.source !== COVERAGE_LCOV) {
      throw new TypeError(`不認得的 coverage_source: ${String(coverage.source)}`);
    }
    coverageSource = COVERAGE_LCOV;
    const covered = coverage.covered instanceof Set ? coverage.covered : new Set(coverage.covered ?? []);
    uncoveredD1 = 0;
    for (const f of d1) {
      if (!covered.has(f)) uncoveredD1 += 1;
    }
  }

  return Object.freeze({
    d1_count: d1.size,
    d2_count: d2plus.size,
    uncovered_d1: uncoveredD1,
    cross_modules: modules.size,
    live_conflicts: liveConflicts,
    coverage_source: coverageSource,
    resolution_rate: resolutionRate(graph),
    // 誠實條款(6.4 條一):靜態分析抓不到動態 import、反射、字串拼路徑,
    // 所以這個向量永遠是下界,不是上界。
    is_lower_bound: true,
  });
}

/**
 * 依文件 6.3 節優先順序比較兩個 CostVector 的代價高低。
 * 回傳負值 = a 代價較低;正值 = a 代價較高;0 = 五個維度全同。
 * uncovered_d1 為 null(無覆蓋資料)時,在比較上視為 -1:
 * 「不知道」不能拿來墊高代價,這是下界精神的延伸,不是估算。
 */
export function compareCostVectors(a, b) {
  for (const key of PRIORITY_ORDER) {
    const av = a[key] ?? -1;
    const bv = b[key] ?? -1;
    if (av !== bv) return av - bv;
  }
  return 0;
}
