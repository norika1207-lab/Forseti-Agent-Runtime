// Forseti M3「寫入准入控制」核心模組。
// 依據:Forseti_Five_Mechanisms_Handoff_v1.0_2026-09-07.md 第 5 節。
// 邊界:唯一 import 是同目錄的 ./cost.js(只用於 NARROW 建議範圍),
// 不 import Moirai 任何東西、不接 ctx、不讀 duo_state.json、
// 不做 UI、不做 HTTP、不做真的檔案鎖。純函數:時間一律由呼叫端傳入。

import { reverseReachable } from './cost.js';

export const SCOPE_STATES = Object.freeze({ ACTIVE: 'ACTIVE', RELEASED: 'RELEASED' });

export const DECISIONS = Object.freeze({
  ALLOW: 'ALLOW',
  NARROW: 'NARROW',
  SERIALIZE: 'SERIALIZE',
  BLOCK: 'BLOCK',
});

// 樞紐判定的資料來源標註。沒有 import 次數資料時是 NONE:
// 此時不估算、不假裝有樞紐,一律當成真衝突(保守側,寧可誤攔不可誤放)。
export const HUB_SOURCES = Object.freeze({ IMPORT_COUNTS: 'IMPORT_COUNTS', NONE: 'NONE' });

/**
 * 預設參數。全部可由呼叫端覆寫,沒有一個是寫死的。
 *
 * hub_percentile: 樞紐檔案判定用的百分位,文件 5.4 建議 N=2(被 import 次數前 2%)。
 *
 * conflict_window_seconds: 15。
 *   【此預設值未經實測校準】文件 5.7 雷二明白寫著,15 秒這個數字來自 silicon 批判的建議值,
 *   不是實測值,本模組不假裝它被驗證過。接手者應以實際資料校準並記錄校準過程。
 *
 * default_ttl_seconds: AdvisoryLock 的預設存活秒數,文件未給數值,此處取 300 為保守預設,
 *   同樣未經實測校準。TTL 的存在理由是 agent 崩潰不得造成永久死鎖(文件 5.6 驗收四)。
 */
export const DEFAULT_CONFIG = Object.freeze({
  hub_percentile: 2,
  conflict_window_seconds: 15,
  default_ttl_seconds: 300,
});

function strField(value, name) {
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`${name} 必須是非空字串`);
  }
  return value;
}

function intField(value, name) {
  if (!Number.isInteger(value) || value < 0) {
    throw new TypeError(`${name} 必須是非負整數,拿到:${String(value)}`);
  }
  return value;
}

// ---------------------------------------------------------------------------
// 最小 glob 比對。文件只寫 declared 是 [glob],未規定 glob 語法,
// 這裡實作最小可用子集:** 跨目錄、* 單層、? 單字元,其餘字元照字面比。
// 不引入任何第三方 glob 套件(零依賴要求)。
// ---------------------------------------------------------------------------
export function matchGlob(pattern, filePath) {
  let re = '';
  for (let i = 0; i < pattern.length; i += 1) {
    const ch = pattern[i];
    if (ch === '*') {
      if (pattern[i + 1] === '*') {
        re += '.*';
        i += 1;
        if (pattern[i + 1] === '/') i += 1; // ** / 也吃掉斜線,讓 src/** 能對到 src/a.js
      } else {
        re += '[^/]*';
      }
    } else if (ch === '?') {
      re += '[^/]';
    } else {
      re += ch.replace(/[.+^${}()|[\]\\]/g, '\\$&');
    }
  }
  return new RegExp(`^${re}$`).test(filePath);
}

/** 不含萬用字元的樣式。這種樣式不必展開就能確定比對結果。 */
export function literalPaths(globs) {
  return (globs ?? []).filter((g) => !/[*?]/.test(g));
}

/**
 * 兩邊都是萬用字元、又沒有候選檔案清單時,無法確定它們有沒有交集。
 *
 * 這種情況必須跟「確定沒有交集」分開回報。把無法判定當成放行,
 * 是本模組最容易犯、也最難查的一種錯:畫面上一片綠,衝突照撞。
 *
 * @returns {Array<{request_glob, scope_glob, holder_agent}>}
 */
export function undecidablePairs(request, { scopes = [], candidateFiles = null } = {}) {
  if (candidateFiles) return [];
  const out = [];
  const reqGlobs = (request.declared ?? []).filter((g) => /[*?]/.test(g));
  for (const scope of scopes) {
    if (scope.state !== SCOPE_STATES.ACTIVE) continue;
    if (scope.agent_id === request.agent_id) continue;
    for (const sg of scope.declared) {
      if (!/[*?]/.test(sg)) continue;
      for (const rg of reqGlobs) {
        out.push(Object.freeze({ request_glob: rg, scope_glob: sg, holder_agent: scope.agent_id }));
      }
    }
  }
  return Object.freeze(out);
}

export function matchesAny(globs, filePath) {
  for (const g of globs) if (matchGlob(g, filePath)) return true;
  return false;
}

/** 把 glob 集合對候選檔案清單展開成實際檔案集合。 */
export function expandGlobs(globs, candidateFiles) {
  const out = new Set();
  for (const f of candidateFiles) if (matchesAny(globs, f)) out.add(f);
  return out;
}

// ---------------------------------------------------------------------------
// 資料結構,欄位名照文件 5.3 節,一字不改。
// ---------------------------------------------------------------------------

export function createWriteScope(fields) {
  const f = fields ?? {};
  return Object.freeze({
    agent_id: strField(f.agent_id, 'agent_id'),
    task_id: strField(f.task_id, 'task_id'),
    declared: Object.freeze([...(f.declared ?? [])]),
    actual: Object.freeze(new Set(f.actual ?? [])),
    declared_at: intField(f.declared_at, 'declared_at'),
    state: f.state ?? SCOPE_STATES.ACTIVE,
  });
}

/** 記錄 agent 實際碰到的檔案(actual 會成長)。回傳新的 WriteScope。 */
export function recordActualWrite(scope, filePath) {
  const actual = new Set(scope.actual);
  actual.add(filePath);
  return Object.freeze({ ...scope, actual: Object.freeze(actual) });
}

export function releaseScope(scope) {
  return Object.freeze({ ...scope, state: SCOPE_STATES.RELEASED });
}

/**
 * 越界偵測(文件 5.5 步驟三):agent 實際碰到的檔案落在 declared 之外就是越界。
 * 本模組只回報,暫停寫入與等批准是呼叫端的事。
 */
export function outOfScopeWrites(scope) {
  const out = [];
  for (const f of scope.actual) if (!matchesAny(scope.declared, f)) out.push(f);
  return out.sort();
}

export function createAdvisoryLock(fields, config = DEFAULT_CONFIG) {
  const f = fields ?? {};
  const ttl = f.ttl_seconds ?? config.default_ttl_seconds ?? DEFAULT_CONFIG.default_ttl_seconds;
  return Object.freeze({
    file_path: strField(f.file_path, 'file_path'),
    holder: strField(f.holder, 'holder'),
    acquired_at: intField(f.acquired_at, 'acquired_at'),
    ttl_seconds: intField(ttl, 'ttl_seconds'),
  });
}

/**
 * 鎖是否已逾時。時間單位:acquired_at 與 now 都是毫秒 timestamp,ttl_seconds 是秒。
 * TTL 到期即視為釋放,agent 崩潰不會造成永久死鎖(文件 5.6 驗收四)。
 */
export function isLockExpired(lock, now) {
  return now - lock.acquired_at >= lock.ttl_seconds * 1000;
}

/** 過濾出仍然有效的鎖。 */
export function liveLocks(locks, now) {
  return locks.filter((l) => !isLockExpired(l, now));
}

// ---------------------------------------------------------------------------
// 樞紐檔案(文件 5.4)
// ---------------------------------------------------------------------------

/**
 * 樞紐檔案 = 被 import 次數位於全專案前 N 百分位的檔案,N 預設 2,可設定。
 * 不排除的話 barrel 檔案會讓交集永遠非空,機制會永遠在誤報(文件 5.7 雷一 / library 批判)。
 *
 * 沒有 import 次數資料時回傳 null,不估算、不猜。呼叫端看到 null 就知道
 * 這一輪判定沒有樞紐豁免,而不是「這個專案沒有樞紐」。
 *
 * 文件只寫「前 N 百分位」,未指定百分位演算法,以下為本模組的實作選擇:
 * 取 k = ceil(N/100 × 總檔案數),樞紐 = 被 import 次數嚴格大於「第 k+1 名」次數的檔案。
 * 用嚴格大於而不是大於等於,是為了處理長尾並列:一份真實專案裡大量檔案的 import 次數同為 1,
 * 若用大於等於當門檻,那些檔案會整批被誤判成樞紐,樞紐豁免就會反過來把真衝突全部放行。
 * 檔案總數不足 k+1 時,全部視為樞紐。
 */
export function hubFiles(importCounts, config = DEFAULT_CONFIG) {
  if (importCounts == null) return null;
  const entries =
    importCounts instanceof Map ? [...importCounts.entries()] : Object.entries(importCounts);
  if (entries.length === 0) return new Set();
  const n = config.hub_percentile ?? DEFAULT_CONFIG.hub_percentile;
  const counts = entries.map(([, c]) => c).sort((a, b) => b - a);
  const k = Math.max(1, Math.ceil((n / 100) * counts.length));
  const hubs = new Set();
  if (k >= counts.length) {
    for (const [file] of entries) hubs.add(file);
    return hubs;
  }
  const cutoff = counts[k]; // 第 k+1 名的次數
  for (const [file, count] of entries) if (count > cutoff) hubs.add(file);
  return hubs;
}

// ---------------------------------------------------------------------------
// 15 秒窗口(文件 5.7 雷二,數值未經實測校準)
// ---------------------------------------------------------------------------

/**
 * 同一檔案在 conflict_window_seconds 內被兩個不同 agent 寫入即判定為衝突。
 * events: [{ file_path, agent_id, at }],at 為毫秒 timestamp。
 * 回傳 [{ file_path, agents: [a, b], gap_seconds }],依 file_path 排序。
 * 【窗口預設 15 秒,未經實測校準,見 DEFAULT_CONFIG 說明】
 */
export function windowConflicts(events, config = DEFAULT_CONFIG) {
  const windowMs = (config.conflict_window_seconds ?? DEFAULT_CONFIG.conflict_window_seconds) * 1000;
  const byFile = new Map();
  for (const e of events) {
    if (!byFile.has(e.file_path)) byFile.set(e.file_path, []);
    byFile.get(e.file_path).push(e);
  }
  const out = [];
  for (const [file, list] of byFile) {
    const sorted = [...list].sort((a, b) => a.at - b.at);
    for (let i = 0; i < sorted.length; i += 1) {
      for (let j = i + 1; j < sorted.length; j += 1) {
        if (sorted[j].at - sorted[i].at > windowMs) break;
        if (sorted[j].agent_id === sorted[i].agent_id) continue;
        out.push(
          Object.freeze({
            file_path: file,
            agents: Object.freeze([sorted[i].agent_id, sorted[j].agent_id]),
            gap_seconds: (sorted[j].at - sorted[i].at) / 1000,
          }),
        );
      }
    }
  }
  return out.sort((a, b) => a.file_path.localeCompare(b.file_path));
}

// ---------------------------------------------------------------------------
// 准入決策(文件 5.4)
// ---------------------------------------------------------------------------

/**
 * 找出請求範圍與現行佔用的交集。
 *
 * 文件 5.7 雷一:一律用「宣告的寫入集合」取交集,不用傳遞閉包,不碰依賴圖。
 * 依賴圖只在 suggestNarrowedScope 算 NARROW 建議時才用到。
 *
 * 交集來源三種,都以檔案路徑為單位:
 *   一,ACTIVE scope 的 actual 裡符合請求 globs 的檔案。
 *   二,請求展開後的檔案裡符合 ACTIVE scope declared 的(需要 candidateFiles 才做得到)。
 *   三,未逾時的 AdvisoryLock,其 file_path 符合請求 globs 且持有者不是請求者。
 */
export function findConflicts(request, { scopes = [], locks = [], now = 0, candidateFiles = null }) {
  const globs = request.declared ?? [];
  const found = new Map(); // file_path -> holder_agent
  const requested = candidateFiles ? expandGlobs(globs, candidateFiles) : null;

  for (const scope of scopes) {
    if (scope.state !== SCOPE_STATES.ACTIVE) continue;
    if (scope.agent_id === request.agent_id) continue;
    for (const f of scope.actual) {
      if (matchesAny(globs, f)) found.set(f, scope.agent_id);
    }
    // 宣告對宣告的直接比對。
    //
    // 端到端測試抓到的漏洞:原本只比對 scope.actual(已經寫下去的檔案)
    // 與展開後的 requested(需要 candidateFiles)。但派工當下 actual 必然是空的,
    // 而 candidateFiles 要掃整個 repo 才拿得到,宿主多半給不出來。
    // 兩人宣告同一個具體檔案、都還沒動手 —— 也就是最該攔的那一刻 —— 直接放行,
    // 要等有人真的寫下去才看得見衝突。那時 M3 已經退化成它想取代的那份 git diff。
    //
    // 字面路徑(不含萬用字元)不需要展開就能確定比對結果,所以這一段不引入猜測。
    for (const f of literalPaths(scope.declared)) {
      if (matchesAny(globs, f) && !found.has(f)) found.set(f, scope.agent_id);
    }
    for (const f of literalPaths(globs)) {
      if (matchesAny(scope.declared, f) && !found.has(f)) found.set(f, scope.agent_id);
    }
    if (requested) {
      for (const f of requested) {
        if (matchesAny(scope.declared, f) && !found.has(f)) found.set(f, scope.agent_id);
      }
    }
  }

  for (const lock of liveLocks(locks, now)) {
    if (lock.holder === request.agent_id) continue;
    if (matchesAny(globs, lock.file_path) && !found.has(lock.file_path)) {
      found.set(lock.file_path, lock.holder);
    }
  }

  return [...found.entries()]
    .map(([file_path, holder_agent]) => Object.freeze({ file_path, holder_agent }))
    .sort((a, b) => a.file_path.localeCompare(b.file_path));
}

/**
 * 算出避開衝突後的建議範圍。回傳 [glob] 或 null(無法建議)。
 *
 * 需要 candidateFiles 才能展開請求範圍;沒有清單就回 null,不猜。
 * 建議範圍以逐檔案字面路徑列出,不從路徑推目錄樣式,避免推出比請求更寬的範圍。
 *
 * 若另外提供依賴圖(graph,格式同 cost.js 的 buildGraph 回傳值),
 * 會額外排除「反向可達集碰到衝突檔案」的候選,也就是改了會波及持有者正在動的檔案的那些。
 * 這是本模組的實作選擇,文件 5.4 只寫「是否可以縮小 S_B 避開交集」,未規定判準。
 */
export function suggestNarrowedScope(request, conflicts, { candidateFiles = null, graph = null }) {
  if (!candidateFiles) return null;
  const conflictFiles = new Set(conflicts.map((c) => c.file_path));
  const kept = [];
  for (const f of expandGlobs(request.declared ?? [], candidateFiles)) {
    if (conflictFiles.has(f)) continue;
    if (graph) {
      const { d1, d2plus } = reverseReachable(graph, f);
      let touches = false;
      for (const d of d1) if (conflictFiles.has(d)) touches = true;
      for (const d of d2plus) if (conflictFiles.has(d)) touches = true;
      if (touches) continue;
    }
    kept.push(f);
  }
  return kept.length > 0 ? kept.sort() : null;
}

/**
 * 准入決策,照文件 5.4 的流程圖。
 *
 * @param {object} request { agent_id, task_id, declared: [glob], deferrable?: bool }
 *        deferrable 未宣告時預設可延後,走 SERIALIZE 排在持有者之後,不叫人。
 *        BLOCK 只保留給呼叫端明確宣告 deferrable === false 的情況。
 *        理由:BLOCK 是把成本轉嫁給使用者,預設就叫人會讓文件 5.6 驗收二的
 *        「誤攔率低於 10%」不可能達成,而一個頻繁叫人的機制會被直接關掉,
 *        關掉之後保護等於零。文件 5.4 有「任務允許延後?」這個判斷但未規定資料來源,
 *        此預設由 w1 於 2026-09-07 裁定。
 * @param {object} env { scopes, locks, now, importCounts, candidateFiles, graph, config }
 *        importCounts 為 null 時沒有樞紐豁免,所有交集都算真衝突(不估算)。
 * @returns 凍結的 AdmissionDecision,欄位恰為文件 5.3 的四個。
 */
export function decideAdmission(request, env = {}) {
  const {
    scopes = [],
    locks = [],
    now = 0,
    importCounts = null,
    candidateFiles = null,
    graph = null,
    config = DEFAULT_CONFIG,
  } = env;

  // 無法判定的 glob 對。ALLOW 時尤其重要:那代表「沒查到衝突」而不是「沒有衝突」。
  const undecidable = undecidablePairs(request, { scopes, candidateFiles });

  const decision = (d, conflicts, reason, suggested_scope = null) =>
    Object.freeze({
      decision: d,
      conflicts: Object.freeze(conflicts),
      reason,
      suggested_scope: suggested_scope ? Object.freeze(suggested_scope) : null,
      undecidable,
      is_complete: undecidable.length === 0,
    });

  const conflicts = findConflicts(request, { scopes, locks, now, candidateFiles });

  // Q1:沒有交集就放行
  if (conflicts.length === 0) {
    return decision(
      DECISIONS.ALLOW,
      [],
      undecidable.length === 0
        ? '與所有 ACTIVE 寫入範圍無交集'
        : `未查到交集,但有 ${undecidable.length} 組樣式無法判定(雙方都是萬用字元且未提供候選檔案清單)。` +
          '這是「沒查到」不是「沒有」,見 is_complete。',
    );
  }

  // Q2:交集是否只落在樞紐檔案上
  const hubs = hubFiles(importCounts, config);
  if (hubs === null) {
    // 沒有 import 次數資料,不估算,不給樞紐豁免。
  } else if (conflicts.every((c) => hubs.has(c.file_path))) {
    return decision(
      DECISIONS.ALLOW,
      conflicts,
      `交集只落在樞紐檔案上(前 ${config.hub_percentile ?? DEFAULT_CONFIG.hub_percentile} 百分位)` +
        `,不算真衝突,放行並標記警示。樞紐判定來源:${HUB_SOURCES.IMPORT_COUNTS}`,
    );
  }

  const realConflicts = hubs === null ? conflicts : conflicts.filter((c) => !hubs.has(c.file_path));
  const hubNote =
    hubs === null
      ? `樞紐判定來源:${HUB_SOURCES.NONE}(無 import 次數資料,未給樞紐豁免,未估算)`
      : `樞紐判定來源:${HUB_SOURCES.IMPORT_COUNTS}`;

  // Q3:能不能縮小範圍避開交集
  const narrowed = suggestNarrowedScope(request, realConflicts, { candidateFiles, graph });
  if (narrowed) {
    return decision(
      DECISIONS.NARROW,
      realConflicts,
      `可縮小寫入範圍避開 ${realConflicts.length} 個衝突檔案。${hubNote}`,
      narrowed,
    );
  }

  const narrowNote = candidateFiles
    ? '縮小後無檔案可寫'
    : '未提供候選檔案清單,無法評估能否縮小範圍(不猜)';

  // Q4:預設序列化,只有明確宣告不可延後才交給擁有者裁決
  if (request.deferrable === false) {
    return decision(
      DECISIONS.BLOCK,
      realConflicts,
      `${narrowNote};任務明確宣告不可延後,交給擁有者裁決。${hubNote}`,
    );
  }
  const deferNote = request.deferrable === true ? '任務可延後' : '任務未宣告可否延後,預設可延後';
  return decision(
    DECISIONS.SERIALIZE,
    realConflicts,
    `${narrowNote};${deferNote},排在持有者之後。${hubNote}`,
  );
}

/**
 * 誤攔率(文件 5.6 驗收二:被擋下但擁有者判定應該放行的比例,目標低於 10%)。
 *
 * records: [{ decision, owner_verdict }]
 *   owner_verdict 只認 'SHOULD_ALLOW' 與 'AGREE';null 或缺 = 擁有者尚未裁決。
 * 未裁決的不進分母,並在 unjudged 如實計數。分母為零時 rate 回傳 null,不回傳 0,
 * 因為「沒有資料」與「誤攔率為零」是兩件事,不可混為一談。
 */
export function falseBlockRate(records) {
  let judged = 0;
  let wrong = 0;
  let unjudged = 0;
  let intercepted = 0;
  for (const r of records) {
    if (r.decision !== DECISIONS.BLOCK && r.decision !== DECISIONS.SERIALIZE) continue;
    intercepted += 1;
    if (r.owner_verdict === 'SHOULD_ALLOW') {
      judged += 1;
      wrong += 1;
    } else if (r.owner_verdict === 'AGREE') {
      judged += 1;
    } else {
      unjudged += 1;
    }
  }
  return Object.freeze({
    intercepted,
    judged,
    wrongly_blocked: wrong,
    unjudged,
    rate: judged === 0 ? null : wrong / judged,
  });
}
