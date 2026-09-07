/**
 * Forseti：可見存活與安全中斷
 *
 * 規格書 v0.1 第 7 節。原文的要求:長時間執行的工作必須暴露可見的存活訊號,
 * 使用者不該被迫猜「它還活著、卡住了、還是安靜地失敗了」。
 *
 * ── 這一節解的是一個很具體的痛 ──────────────────────
 *
 * 使用者按下 ESC 的那一刻,通常不是因為她知道出事了,
 * 是因為她不知道有沒有出事,而不知道的成本比中斷還高。
 * 於是中斷發生在最糟的時間點:工作做到一半,沒有存檔,
 * 下一個 session 接手時什麼都不知道。
 *
 * 所以這個模組做兩件事:
 *   一,量「不可見的執行」有多少,讓沉默本身變成可見的數字
 *   二,在中斷之前產生一份可以接手的快照
 *
 * 第二件的規格很硬:快照必須包含 exact_next_step。
 * 一份說得出「現在在哪」卻說不出「下一步做什麼」的快照,
 * 接手的人還是要從頭讀一遍,那就沒有省到任何東西。
 *
 * 零依賴。這個模組不中斷任何東西,它只回答「現在中斷的話,要留下什麼」。
 */

export const VERSION = 'rescue@0.1';

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 【以下沒有實測校準。】規格書第 15 節把「最小心跳頻率」列為必須校準的項目,
   * 並且點出兩難:太密會變成雜訊,太疏就失去意義。60 秒是起點。
   */
  heartbeatIntervalMs: 60 * 1000,
  /** 超過這麼久沒有可見動靜,算一次沉默事件 */
  silenceEpisodeMs: 3 * 60 * 1000,
});

/** 快照的必要欄位。規格書第 7 節,一字不改。 */
export const SNAPSHOT_FIELDS = Object.freeze([
  'objective',
  'current_step',
  'last_verified_state',
  'active_hypothesis',
  'open_tool_calls',
  'artifact_refs',
  'unresolved_decisions',
  'exact_next_step',
  'timestamp',
]);

/**
 * 建一份復原快照。
 *
 * 缺欄位不拋錯,但會列在 missing 裡並且讓 usable 變成 false。
 * 理由跟 conformance.js 一樣:拋錯會逼人填一個看起來像樣的假值,
 * 而一份「說得出自己缺什麼」的快照,比一份填滿了空話的完整快照有用。
 *
 * exact_next_step 缺的時候特別標出來,因為那是這份快照唯一
 * 真正省到下一個人時間的欄位。其他欄位講的是「發生過什麼」,
 * 只有它講「接下來做什麼」。
 */
export function createSnapshot(fields = {}) {
  const missing = SNAPSHOT_FIELDS.filter((f) => fields[f] === undefined || fields[f] === null);
  const out = {};
  for (const f of SNAPSHOT_FIELDS) out[f] = fields[f] ?? null;
  return Object.freeze({
    ...out,
    open_tool_calls: Object.freeze([...(fields.open_tool_calls ?? [])]),
    artifact_refs: Object.freeze([...(fields.artifact_refs ?? [])]),
    unresolved_decisions: Object.freeze([...(fields.unresolved_decisions ?? [])]),
    version: VERSION,
    missing: Object.freeze(missing),
    /** 缺任何一項都不算完整,但缺 exact_next_step 是最貴的那一種。 */
    usable: missing.length === 0,
    lacks_next_step: fields.exact_next_step == null,
    note: fields.exact_next_step == null
      ? 'No exact next step recorded. Whoever picks this up will have to re-derive it, which is most of what a snapshot is supposed to save.'
      : null,
  });
}

/**
 * 沉默執行比:沒有可見動靜的時間,佔實際執行時間的比例。
 *
 * 規格書第 7 節的目標方向是 → 0。
 *
 * 要注意這個數字量的是「使用者看不看得到」,不是「有沒有在做事」。
 * 一個安靜但正確的長工作,這個數字會很高,而那不是錯誤 ——
 * 它說的是使用者現在必須用猜的,那本身就是要修的東西。
 */
export function silentExecutionRatio(beats, { activeFrom, activeTo, config = DEFAULT_CONFIG } = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  if (activeFrom == null || activeTo == null || activeTo <= activeFrom) {
    return Object.freeze({ ratio: null, episodes: 0, longest_ms: null, note: 'No active window supplied.' });
  }
  const marks = [activeFrom, ...(beats ?? []).filter((b) => b >= activeFrom && b <= activeTo).sort((a, b) => a - b), activeTo];
  let silent = 0;
  let episodes = 0;
  let longest = 0;
  for (let i = 1; i < marks.length; i += 1) {
    const gap = marks[i] - marks[i - 1];
    if (gap > c.heartbeatIntervalMs) silent += gap - c.heartbeatIntervalMs;
    if (gap >= c.silenceEpisodeMs) episodes += 1;
    if (gap > longest) longest = gap;
  }
  const total = activeTo - activeFrom;
  return Object.freeze({
    ratio: total > 0 ? Math.min(1, silent / total) : null,
    episodes,
    longest_ms: longest,
    note: (beats ?? []).length === 0
      ? 'No heartbeats at all. The user could not tell alive from hung for the entire window.'
      : null,
  });
}

/**
 * 不安全中斷率:中斷時沒有留下可用快照的比例。
 *
 * 規格書第 7 節的目標方向是 → 0。
 * 分母為零時回 null,不是 0 —— 沒有人中斷過,跟每次中斷都安全,是兩件事。
 */
export function unsafeInterruptRate(interruptions) {
  const list = interruptions ?? [];
  if (!list.length) return Object.freeze({ rate: null, total: 0, unsafe: 0 });
  const unsafe = list.filter((i) => !i.snapshot || i.snapshot.usable !== true).length;
  return Object.freeze({
    rate: unsafe / list.length,
    total: list.length,
    unsafe,
    /** 沒有 exact_next_step 的那些單獨數:它們技術上有快照,實際上省不到時間。 */
    without_next_step: list.filter((i) => i.snapshot && i.snapshot.lacks_next_step).length,
  });
}

/**
 * 現在中斷的話,安不安全。
 *
 * 這是給宿主在真的要中斷之前叫的。回傳 ready 為 false 時,
 * 宿主應該先把快照做出來再中斷 —— 規格書第 7 節:
 * 技術上可行時,中斷之前或之時必須建立復原快照。
 */
export function interruptReadiness({ snapshot = null, openToolCalls = [], lastVerifiedAt = null, now = null } = {}) {
  const blockers = [];
  if (!snapshot) blockers.push('No recovery snapshot exists.');
  else if (!snapshot.usable) blockers.push(`Snapshot is missing: ${snapshot.missing.join(', ')}.`);
  if (openToolCalls.length) {
    blockers.push(`${openToolCalls.length} tool call(s) still open; their results will be lost.`);
  }
  return Object.freeze({
    ready: blockers.length === 0,
    blockers: Object.freeze(blockers),
    /** 距離上一次已驗證的推進多久。中斷之後要從那裡接。 */
    last_verified_progress_age_ms: (lastVerifiedAt != null && now != null) ? now - lastVerifiedAt : null,
    version: VERSION,
  });
}

/**
 * 三個指標一起看。規格書第 7 節那張表。
 *
 * 三個都拿不到時明說,不要回一組零 —— 一個沒有接任何東西的系統,
 * 三個指標都是零,看起來會像一個完美的系統。
 */
export function livenessReport({ silent, unsafe, lastVerifiedAgeMs }) {
  const known = [silent?.ratio, unsafe?.rate, lastVerifiedAgeMs].filter((x) => x != null).length;
  return Object.freeze({
    silent_execution_ratio: silent?.ratio ?? null,
    unsafe_interrupt_rate: unsafe?.rate ?? null,
    last_verified_progress_age_ms: lastVerifiedAgeMs ?? null,
    measured: known,
    note: known === 0
      ? 'None of the three liveness metrics could be measured. Three nulls is not a healthy system; it is an unmeasured one.'
      : null,
    version: VERSION,
  });
}
