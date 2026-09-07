/**
 * Forseti：可疑窗口選取
 *
 * 規格書 v0.1 第 5 節。原文的立場很明確:
 * 把整個 session 餵給語意分析是例外,不是預設。
 * 預設的流程是事件先收窄,再針對性語意檢視。
 *
 *   一,把所有事件建索引
 *   二,算滾動的原子訊號
 *   三,找峰值、變點、重複母題
 *   四,選出前 K 個可疑窗口
 *   五,依設定往前後各擴一段脈絡
 *   六,只把那些窗口加上已驗證的專案錨點送去語意分析
 *   七,語意結果存成 INFERRED,除非另外驗證過
 *
 * ── 為什麼不全部送 ─────────────────────────────────
 *
 * 一個真實的長 session 有幾十萬行。全部送出去有三個代價,
 * 而且第三個最容易被忽略:
 *
 *   花錢    這個明顯
 *   慢      這個也明顯
 *   稀釋    幾十萬行裡的一個異常,對語意模型來說跟雜訊沒有差別。
 *           收窄之後送三千行,那個異常佔的比重大了兩個數量級。
 *
 * 第三個是這個模組真正的理由。省錢只是副作用。
 *
 * ── 這個模組不呼叫任何模型 ──────────────────────────
 *
 * 它只回答「該送哪幾段」。送不送、送去哪、怎麼問,是宿主的事。
 * 而且回傳一定帶 epistemic: 'INFERRED' 的提醒:
 * 語意分析的結果不會因為它讀了原文就變成 VERIFIED。
 *
 * 零依賴。
 */

export const VERSION = 'windows@0.1';

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 【以下全部沒有實測校準。】規格書第 15 節把窗口大小列為必須校準的第一項,
   * 並且明確問「一個可疑窗口周圍需要多少語意脈絡才夠」。這些是起點,不是答案。
   */
  bucketMs: 5 * 60 * 1000,   // 滾動桶的大小
  topK: 5,                   // 選幾個窗口
  contextBefore: 1,          // 往前擴幾個桶
  contextAfter: 1,           // 往後擴幾個桶
  minPeakZ: 1.5,             // 高於平均幾個標準差才算峰值
  motifMinRepeats: 3,        // 重複幾次才算母題
});

/**
 * 把事件依時間切成固定大小的桶。
 *
 * 用固定時間而不是固定事件數,因為要找的是「某一段時間裡不對勁」,
 * 而活動密度本身就是訊號之一。用事件數切會把密集期壓縮掉。
 */
export function bucketize(events, { bucketMs = DEFAULT_CONFIG.bucketMs, from = null, to = null } = {}) {
  const list = (events ?? []).filter((e) => typeof e.at === 'number').sort((a, b) => a.at - b.at);
  if (!list.length) return Object.freeze([]);
  const start = from ?? list[0].at;
  const end = to ?? list.at(-1).at;
  const n = Math.max(1, Math.ceil((end - start + 1) / bucketMs));
  const buckets = Array.from({ length: n }, (_, i) => ({
    index: i,
    from: start + i * bucketMs,
    to: start + (i + 1) * bucketMs,
    events: [],
  }));
  for (const e of list) {
    const i = Math.min(n - 1, Math.floor((e.at - start) / bucketMs));
    buckets[i].events.push(e);
  }
  return Object.freeze(buckets.map((b) => Object.freeze({ ...b, events: Object.freeze(b.events), count: b.events.length })));
}

/**
 * 找峰值:某個桶的分數顯著高於整體平均。
 *
 * 用 z 分數而不是絕對門檻,因為每個 session 的活動水準差很多,
 * 一個絕對門檻在忙的 session 裡到處都是峰值,在安靜的 session 裡一個都沒有。
 *
 * 標準差為零時回空陣列 —— 每個桶都一樣就沒有峰值可言,
 * 那不是「沒有異常」,是「這個方法在這裡看不出東西」。
 */
export function findPeaks(scores, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const vals = (scores ?? []).map((s) => s.value).filter((v) => typeof v === 'number');
  if (vals.length < 3) return Object.freeze([]);
  const mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  const sd = Math.sqrt(vals.reduce((a, b) => a + (b - mean) ** 2, 0) / vals.length);
  if (sd === 0) return Object.freeze([]);
  return Object.freeze(scores
    .filter((s) => typeof s.value === 'number' && (s.value - mean) / sd >= c.minPeakZ)
    .map((s) => Object.freeze({ ...s, z: (s.value - mean) / sd, kind: 'PEAK' })));
}

/**
 * 找變點:相鄰兩桶之間的落差顯著大於一般落差。
 *
 * 峰值找的是「這裡特別高」,變點找的是「這裡開始不一樣了」。
 * 兩者要分開,因為一個平緩爬升到高點的過程沒有變點但有峰值,
 * 而一個從高掉到低的轉折有變點但沒有峰值。
 */
export function findChangePoints(scores, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const list = scores ?? [];
  if (list.length < 4) return Object.freeze([]);
  const deltas = [];
  for (let i = 1; i < list.length; i += 1) {
    const a = list[i - 1].value, b = list[i].value;
    if (typeof a !== 'number' || typeof b !== 'number') continue;
    deltas.push({ index: list[i].index, delta: Math.abs(b - a), at: list[i].from });
  }
  if (deltas.length < 3) return Object.freeze([]);
  const mean = deltas.reduce((a, d) => a + d.delta, 0) / deltas.length;
  const sd = Math.sqrt(deltas.reduce((a, d) => a + (d.delta - mean) ** 2, 0) / deltas.length);
  if (sd === 0) return Object.freeze([]);
  return Object.freeze(deltas
    .filter((d) => (d.delta - mean) / sd >= c.minPeakZ)
    .map((d) => Object.freeze({ index: d.index, from: d.at, value: d.delta, z: (d.delta - mean) / sd, kind: 'CHANGE_POINT' })));
}

/**
 * 找重複母題:同一個桶裡同一個動作重複多次。
 *
 * 這對應規格書第 3.1 節 S4 的「相同的未解目標」,
 * 所以 key 由呼叫端決定,不同目標的相同動作不算同一個母題。
 */
export function findMotifs(buckets, keyOf, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const out = [];
  for (const b of (buckets ?? [])) {
    const counts = new Map();
    for (const e of b.events) {
      const k = keyOf(e);
      if (k == null) continue;
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    for (const [k, n] of counts) {
      if (n >= c.motifMinRepeats) {
        out.push(Object.freeze({ index: b.index, from: b.from, value: n, motif: k, kind: 'MOTIF' }));
      }
    }
  }
  return Object.freeze(out.sort((a, b) => b.value - a.value));
}

/**
 * 選出前 K 個可疑窗口,並依設定擴充脈絡。
 *
 * 重疊的窗口會被合併 —— 送兩段重疊的脈絡給語意分析,
 * 等於為同一段內容付兩次錢,而且模型會看到重複的東西。
 *
 * @returns {{windows, considered, method, note}}
 */
export function selectWindows(candidates, buckets, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const list = [...(candidates ?? [])].sort((a, b) => (b.z ?? b.value ?? 0) - (a.z ?? a.value ?? 0));
  if (!list.length) {
    return Object.freeze({
      windows: Object.freeze([]),
      considered: 0,
      method: VERSION,
      /** 找不到可疑窗口不等於沒有問題,可能是這個方法在這份資料上看不出東西。 */
      note: 'No suspicious windows found. This does not mean nothing is wrong - it means these detectors found no peak, change point, or motif in this data.',
    });
  }

  const ranges = [];
  for (const cand of list.slice(0, c.topK)) {
    const lo = Math.max(0, cand.index - c.contextBefore);
    const hi = Math.min((buckets?.length ?? 1) - 1, cand.index + c.contextAfter);
    ranges.push({ lo, hi, reasons: [cand] });
  }
  ranges.sort((a, b) => a.lo - b.lo);

  // 合併重疊,不重複送同一段脈絡
  const merged = [];
  for (const r of ranges) {
    const last = merged.at(-1);
    if (last && r.lo <= last.hi + 1) {
      last.hi = Math.max(last.hi, r.hi);
      last.reasons.push(...r.reasons);
    } else {
      merged.push({ ...r, reasons: [...r.reasons] });
    }
  }

  const windows = merged.map((m) => {
    const bs = (buckets ?? []).slice(m.lo, m.hi + 1);
    const events = bs.flatMap((b) => b.events);
    return Object.freeze({
      from: bs[0]?.from ?? null,
      to: bs.at(-1)?.to ?? null,
      bucket_range: Object.freeze([m.lo, m.hi]),
      event_count: events.length,
      events: Object.freeze(events),
      reasons: Object.freeze(m.reasons.map((r) => Object.freeze({ kind: r.kind, value: r.value, z: r.z ?? null, motif: r.motif ?? null }))),
      /** 語意分析的結果存成 INFERRED,不會因為讀了原文就升級。規格書第 5 節第七步。 */
      result_epistemic_ceiling: 'INFERRED',
    });
  });

  const totalEvents = (buckets ?? []).reduce((a, b) => a + b.count, 0);
  const selected = windows.reduce((a, w) => a + w.event_count, 0);
  return Object.freeze({
    windows: Object.freeze(windows),
    considered: list.length,
    method: VERSION,
    /** 收窄到原本的幾分之幾。這是這個模組唯一的效益指標。 */
    reduction: totalEvents ? selected / totalEvents : null,
    note: null,
  });
}
