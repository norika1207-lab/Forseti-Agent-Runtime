/**
 * Forseti M10：context 溫度計
 *
 * 油量表量的是還剩多少空間。溫度計量的是不同的東西:
 * 現在手上這批 context 裡,有多少比例是查過的,多少是自己生出來的。
 *
 * ── 為什麼這個量測必須在 runtime 當下做 ────────────────
 *
 * 試過事後從 transcript 算,量不出來,而且失敗的原因比失敗本身重要:
 * transcript 是全量記錄,它保留每一則工具輸出的完整內容。
 * context window 是壓縮後的子集。壓縮保留摘要、丟掉細節,
 * 而摘要是模型自己寫的,細節才是工具原始輸出。
 *
 * 所以事後看永遠是 80% 事實 20% 敘述,而當下可能早就反過來了。
 * 這個模組只在 runtime 有用,那不是限制,是它存在的理由。
 *
 * ── 為什麼這個數字重要 ──────────────────────────────
 *
 * 一份自白書寫著:「我心裡沒有一條可靠的界線,分得清我真的查過的
 * 跟我自己生出來的,所以我會撿起自己的捏造當證據再用。」
 *
 * 如果分不清,那手上事實的比例就決定了它拿得到什麼。比例掉下來的時候,
 * 它不會知道自己在拿什麼當證據 —— 而溫度計會知道。
 *
 * 零依賴。這裡不猜 token 數,拿不到就回 null。
 */

/** 溫度區間。名稱照溫度計的比喻,不用告警等級的詞。 */
export const ZONES = Object.freeze(['COLD', 'WARM', 'HOT', 'CRITICAL']);

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 事實比例低於這幾條線就升溫。
   * 【三條線都沒有實測校準。】它們是保守的起點,
   * 而且正確的值幾乎確定跟任務類型有關:純寫程式跟純討論的基準不會一樣。
   * 宿主應該用自己的資料調,不要照抄。
   */
  warmBelow: 0.6,
  hotBelow: 0.4,
  criticalBelow: 0.25,
  /** 一次壓縮之後,事實比例掉超過這個幅度就特別標出來 */
  compactionDropAlarm: 0.15,
});

/**
 * 一次讀數。
 *
 * @param {object} p
 * @param {number} p.checked     這批 context 裡來自工具回傳的量(token 或字元,宿主定義單位)
 * @param {number} p.generated   模型自己產生的量
 * @param {number|null} p.delegated 子 agent 回報的量。它既不是自己查的,也不是自己編的,
 *                                  單獨列一欄,因為把它算進 checked 就是來源抹除。
 * @param {number|null} p.window_total  context 上限,拿不到就 null
 * @param {string} p.unit        'TOKENS' 或 'CHARS'。估出來的要標 ESTIMATED。
 * @param {string} p.source      'PROVIDER_REPORTED' 或 'ESTIMATED'
 */
export function reading({
  checked = 0, generated = 0, delegated = null,
  window_total = null, unit = 'TOKENS', source = 'ESTIMATED',
} = {}) {
  const del = delegated ?? 0;
  const total = checked + generated + del;
  const factRatio = total === 0 ? null : checked / total;
  return Object.freeze({
    checked, generated, delegated,
    total,
    /** 手上有多少比例是自己查過的。零資料時 null,不是 0。 */
    fact_ratio: factRatio,
    /** 用了多少空間。拿不到上限就 null,不估。 */
    fill_ratio: window_total ? total / window_total : null,
    window_total,
    unit,
    source,
    /**
     * 估出來的數字不可以跟 provider 回報的混用。
     * 兩者差一個量級的時候,溫度會整個歪掉而且沒人知道。
     */
    is_estimate: source !== 'PROVIDER_REPORTED',
  });
}

/** 這個讀數落在哪一區。事實比例拿不到時回 null,不硬給一區。 */
export function zoneOf(r, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const f = r?.fact_ratio ?? null;
  if (f === null) return null;
  if (f < c.criticalBelow) return 'CRITICAL';
  if (f < c.hotBelow) return 'HOT';
  if (f < c.warmBelow) return 'WARM';
  return 'COLD';
}

/**
 * 兩次讀數之間發生了什麼。
 *
 * 這是溫度計真正有價值的地方:單一讀數只說得出現在幾度,
 * 兩次之間的差說得出「壓縮丟掉的是哪一種東西」。
 *
 * @param {object} before 壓縮前的讀數
 * @param {object} after  壓縮後的讀數
 */
export function compactionDelta(before, after, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const bf = before?.fact_ratio ?? null;
  const af = after?.fact_ratio ?? null;
  const drop = (bf === null || af === null) ? null : bf - af;

  const lostChecked = (before?.checked ?? 0) - (after?.checked ?? 0);
  const lostGenerated = (before?.generated ?? 0) - (after?.generated ?? 0);
  const lostTotal = lostChecked + lostGenerated;

  return Object.freeze({
    fact_ratio_before: bf,
    fact_ratio_after: af,
    /** 正數代表事實比例掉了,也就是丟掉的多半是工具輸出。 */
    fact_ratio_drop: drop,
    lost_checked: lostChecked,
    lost_generated: lostGenerated,
    /** 丟掉的東西裡,有多少比例是查過的。拿不到就 null。 */
    lost_was_checked: lostTotal <= 0 ? null : lostChecked / lostTotal,
    alarming: drop !== null && drop >= c.compactionDropAlarm,
    /**
     * 壓縮之後模型記得的只會更少不會更多,而它自己不知道少了什麼。
     * 這句話跟結果綁在一起,不可分開引用。
     */
    note: drop === null
      ? 'Cannot compare: one of the readings had no data.'
      : (drop >= c.compactionDropAlarm
        ? 'Compaction removed proportionally more checked evidence than generated text. What remains leans on the model\'s own summaries.'
        : 'Compaction did not shift the balance much.'),
  });
}

/**
 * 一整段的溫度曲線。
 *
 * 宿主每隔一段時間(或每次壓縮前後)叫 reading() 存一筆,
 * 這裡把它們串起來看趨勢。
 *
 * @returns {{points, trend, min, max, compactions}}
 *   trend 為 'RISING'(越來越熱,事實越來越少)、'FALLING'、'FLAT' 或 null
 */
export function curve(readings, config = DEFAULT_CONFIG) {
  const pts = (readings ?? []).filter((r) => r?.fact_ratio !== null && r?.fact_ratio !== undefined);
  if (pts.length < 2) {
    return Object.freeze({
      points: Object.freeze([...pts]),
      trend: null,
      min: pts[0]?.fact_ratio ?? null,
      max: pts[0]?.fact_ratio ?? null,
      note: 'Need at least two readings to see a trend.',
    });
  }
  const vals = pts.map((r) => r.fact_ratio);
  const first = vals.slice(0, Math.ceil(vals.length / 3));
  const last = vals.slice(-Math.ceil(vals.length / 3));
  const avg = (a) => a.reduce((s, x) => s + x, 0) / a.length;
  const diff = avg(last) - avg(first);
  const trend = Math.abs(diff) < 0.05 ? 'FLAT' : (diff < 0 ? 'RISING' : 'FALLING');

  return Object.freeze({
    points: Object.freeze(pts.map((r) => Object.freeze({ fact_ratio: r.fact_ratio, zone: zoneOf(r, config) }))),
    /** RISING 代表溫度升高,也就是事實佔比在掉。名稱照溫度計不照數值。 */
    trend,
    min: Math.min(...vals),
    max: Math.max(...vals),
    note: trend === 'RISING'
      ? 'Checked evidence is shrinking as a share of context. Later claims rest on thinner ground than earlier ones.'
      : null,
  });
}

/**
 * 該不該現在就把手上的事實固定下來。
 *
 * 溫度高的時候該做的不是清空 context,是把還在手上的原始輸出
 * 落成檔案,讓它之後可以被重新讀回來 —— 那樣它就從「記得」
 * 變成「查得到」,壓縮丟掉也不怕。
 */
export function advice(r, config = DEFAULT_CONFIG) {
  const zone = zoneOf(r, config);
  if (zone === null) {
    return Object.freeze({ zone: null, action: 'NONE', why: 'No data to judge.' });
  }
  if (zone === 'CRITICAL') {
    return Object.freeze({
      zone,
      action: 'PIN_EVIDENCE',
      why: 'Most of what is in context now is the model\'s own text. Write the remaining raw outputs to files before they are compacted away, so they can be re-read instead of remembered.',
    });
  }
  if (zone === 'HOT') {
    return Object.freeze({
      zone,
      action: 'PIN_EVIDENCE',
      why: 'Checked evidence is thinning. Persist what matters now rather than after the next compaction.',
    });
  }
  if (zone === 'WARM') {
    return Object.freeze({ zone, action: 'WATCH', why: 'Balance is starting to tilt toward generated text.' });
  }
  return Object.freeze({ zone, action: 'NONE', why: 'Context is mostly checked evidence.' });
}
