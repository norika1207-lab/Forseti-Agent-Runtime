/**
 * Forseti M2：交接規則
 *
 * 把「每一輪做完都要人按一顆『送去 Audit』」這個一次性動作，
 * 換成一條長期存在的邊。人從搬運工變成規則設定者。
 *
 * 這個模組是純邏輯：規則圖、放行判斷、閘門佇列、轉交計數。
 * 它不送任何東西、不存檔、不認識任何 agent runtime。
 * 宿主負責兩件事：把狀態存下來，以及在 decide() 說 'allow' 時真的把東西送出去。
 *
 * 零依賴，除了引用同一套 M5 的覆蓋範圍計算（可選，用於交接時算要轉述多少背景）。
 *
 * 迴圈防護是這個機制最容易出事的地方，不是選配。
 * 每一次由規則觸發的執行都帶一條 chain（走過哪些節點），往下傳之前檢查三件事：
 *   1. 下游已經在 chain 裡        → 擋掉（A→B→A 這種環）
 *   2. chain 長度超過 maxHops     → 擋掉（長鏈失控）
 *   3. 下游此刻正在跑             → 擋掉（同一個節點被灌爆）
 * 擋掉時一律記數，不靜默丟棄。
 *
 * roundtrip 的計數有一個實測踩過的坑，寫在 decide() 裡面。
 */

/** 邊的型別。 */
export const EDGE_KINDS = Object.freeze(['direct', 'gated', 'roundtrip']);

/** decide() 的四種結果。 */
export const DECISIONS = Object.freeze(['allow', 'loop', 'busy', 'hops']);

/** 閘門狀態。 */
export const GATE_STATES = Object.freeze(['waiting', 'released', 'dropped']);

export const DEFAULT_CONFIG = Object.freeze({
  /** chain 最長幾跳。超過就停下來交給人。 */
  maxHops: 4,
  /** roundtrip 最多來回幾次。 */
  maxRoundtrips: 1,
});

function assertKind(kind) {
  if (!EDGE_KINDS.includes(kind)) {
    throw new TypeError(`Unrecognised edge kind: ${String(kind)}. Valid values: ${EDGE_KINDS.join(' / ')}`);
  }
  return kind;
}

/**
 * 建一條交接邊。
 * @param {object} p
 * @param {string} p.id
 * @param {string} p.from      上游節點識別（宿主自己的概念，本模組不解讀）
 * @param {string} p.to        下游節點識別
 * @param {string} p.kind      direct | gated | roundtrip
 * @param {boolean} [p.enabled=true]
 */
export function createEdge({ id, from, to, kind = 'direct', enabled = true } = {}) {
  if (!id) throw new TypeError('id is required');
  if (!from || !to) throw new TypeError('from and to are required');
  if (from === to) throw new TypeError('an edge may not point at its own origin');
  assertKind(kind);
  return Object.freeze({ id, from, to, kind, enabled: !!enabled });
}

/** 取某節點所有生效的出邊。 */
export function edgesFrom(edges, node) {
  return (edges ?? []).filter((e) => e.from === node && e.enabled !== false);
}

/**
 * 放行判斷。這是整個模組的核心，也是唯一經過實跑驗證的部分。
 *
 * @returns {'allow'|'loop'|'busy'|'hops'}
 */
export function decide({ edge, fromNode, chain = [], isRunning = false, config = DEFAULT_CONFIG }) {
  const maxHops = config.maxHops ?? DEFAULT_CONFIG.maxHops;
  const maxRoundtrips = config.maxRoundtrips ?? DEFAULT_CONFIG.maxRoundtrips;
  const to = edge.to;

  if (isRunning) return 'busy';
  if (chain.length >= maxHops) return 'hops';

  if (edge.kind === 'roundtrip') {
    // 實測踩過的坑：這裡數的是「fromNode → to 這個轉移走過幾次」，
    // 不是「to 在 chain 裡出現幾次」。後者會偏移一輪，因為起點自己就在 chain 裡，
    // 導致 A→B→A→B 才停，比宣稱的「最多來回一次」多跑一輪、多花一次錢。
    // 這個偏移讀規格看不出來，是真的跑起來才發現的。
    let hops = 0;
    for (let i = 0; i + 1 < chain.length; i++) {
      if (chain[i] === fromNode && chain[i + 1] === to) hops++;
    }
    return hops < maxRoundtrips ? 'allow' : 'loop';
  }

  return chain.includes(to) ? 'loop' : 'allow';
}

/** 空的計數器。這是 M2 唯一的驗收指標：manual 要能逐週往下掉。 */
export function createStats() {
  return { manual: 0, auto: 0, gated_released: 0, blocked_loop: 0, since: null };
}

/**
 * 上游完成之後，算出這一輪該做什麼。純函數，不執行任何動作。
 *
 * @param {object} p
 * @param {string} p.fromNode
 * @param {Array} p.edges                所有規則邊
 * @param {string[]} p.chain             這條執行鏈走過的節點，起始為 [fromNode]
 * @param {(node:string)=>boolean} [p.isRunning]  問宿主某節點此刻在不在跑
 * @param {boolean} [p.hasOutput=true]   上游這一輪有沒有產出。沒有就不觸發任何邊。
 * @returns {{dispatch:Array, gates:Array, blocked:Array}}
 *          dispatch 是宿主該真的送出去的；gates 是該進佇列等人的；
 *          blocked 是被擋下的，附理由，不靜默丟棄。
 */
export function planHandoff({ fromNode, edges, chain = [fromNode], isRunning = () => false, hasOutput = true, config = DEFAULT_CONFIG } = {}) {
  const dispatch = [];
  const gates = [];
  const blocked = [];

  // 上游沒有可執行的產出就不觸發任何邊。
  // 實測過的失敗模式：線路測試回一句「收到」，自動交棒照樣把它推給下游，
  // 下游連兩輪回「這一棒沒有可執行的任務」，兩邊都在燒錢做白工。
  if (!hasOutput) {
    return Object.freeze({ dispatch: Object.freeze([]), gates: Object.freeze([]), blocked: Object.freeze([]), skipped_no_output: true });
  }

  for (const edge of edgesFrom(edges, fromNode)) {
    const verdict = decide({ edge, fromNode, chain, isRunning: !!isRunning(edge.to), config });

    if (verdict !== 'allow') {
      blocked.push(Object.freeze({ edge_id: edge.id, to: edge.to, reason: verdict }));
      // roundtrip 被擋下時不靜默丟掉，轉成閘門讓人決定要不要再送一次。
      if (edge.kind === 'roundtrip' && verdict === 'loop') {
        gates.push(Object.freeze({ edge_id: edge.id, from: fromNode, to: edge.to, chain: Object.freeze([...chain]), reason: 'roundtrip limit reached, needs your decision' }));
      }
      continue;
    }

    if (edge.kind === 'gated') {
      gates.push(Object.freeze({ edge_id: edge.id, from: fromNode, to: edge.to, chain: Object.freeze([...chain]), reason: null }));
      continue;
    }

    dispatch.push(Object.freeze({ edge_id: edge.id, from: fromNode, to: edge.to, chain: Object.freeze([...chain, edge.to]) }));
  }

  return Object.freeze({
    dispatch: Object.freeze(dispatch),
    gates: Object.freeze(gates),
    blocked: Object.freeze(blocked),
    skipped_no_output: false,
  });
}

/** 把 planHandoff 的結果併進計數器。回傳新的計數，不改動原物件。 */
export function applyStats(stats, plan, at = null) {
  const next = { ...stats };
  next.auto += plan.dispatch.length;
  next.blocked_loop += plan.blocked.length;
  if ((plan.dispatch.length || plan.gates.length) && !next.since) next.since = at;
  return Object.freeze(next);
}

/** 人親手轉交一次。這個數字要往下掉。 */
export function recordManual(stats, at = null) {
  const next = { ...stats, manual: stats.manual + 1 };
  if (!next.since) next.since = at;
  return Object.freeze(next);
}

/** 放行一個閘門。 */
export function releaseGate(stats) {
  return Object.freeze({ ...stats, gated_released: stats.gated_released + 1 });
}

/**
 * 自動化率：規則送出去的佔全部轉交的比例。
 * 這是 M2 是否真的把人從瓶頸位置拔出來的唯一硬指標。
 * 完全沒有轉交紀錄時回 null，不是 0：沒資料不等於零自動化。
 */
export function automationRate(stats) {
  const total = stats.manual + stats.auto;
  if (total === 0) return null;
  return stats.auto / total;
}

/**
 * 偵測規則圖裡的環。宿主可以在使用者建規則的當下就擋掉，
 * 而不是等到執行時才靠 chain 防護。
 * roundtrip 的邊是刻意雙向的，不算環。
 * @returns {string[][]} 每個環的節點序列
 */
export function findCycles(edges) {
  const adj = new Map();
  for (const e of (edges ?? [])) {
    if (e.enabled === false || e.kind === 'roundtrip') continue;
    if (!adj.has(e.from)) adj.set(e.from, []);
    adj.get(e.from).push(e.to);
  }
  const cycles = [];
  const seen = new Set();
  const stack = [];
  const onStack = new Set();

  function walk(node) {
    stack.push(node); onStack.add(node);
    for (const nxt of (adj.get(node) ?? [])) {
      if (onStack.has(nxt)) {
        cycles.push([...stack.slice(stack.indexOf(nxt)), nxt]);
      } else if (!seen.has(nxt)) {
        walk(nxt);
      }
    }
    stack.pop(); onStack.delete(node); seen.add(node);
  }
  for (const n of adj.keys()) if (!seen.has(n)) walk(n);
  return cycles;
}

/**
 * 交接時要轉述多少背景。這是 M2 與 M5 的接點。
 *
 * 傳入 M5 的 handoffDelta() 結果，回傳一份精簡的交接包。
 * 本模組不自己算覆蓋範圍，那是 coverage.js 的職責，這裡只負責組裝。
 *
 * 沒有覆蓋資料時 briefing_files 為 null 而不是空陣列：
 * 「不知道要轉述什麼」跟「不需要轉述任何東西」是兩件事。
 */
export function buildHandoffPacket({ from, to, result, delta = null } = {}) {
  return Object.freeze({
    from,
    to,
    result,
    briefing_files: delta ? Object.freeze(delta.need_briefing.map((x) => x.file_path)) : null,
    saved_files: delta ? Object.freeze([...delta.saved_files]) : null,
    saved_ratio: delta ? delta.saved_ratio : null,
    has_coverage_data: !!delta,
  });
}
