/**
 * Forseti：自適應健康基線
 *
 * 規格書 §15 第二項:健康基線要用全域預設,還是每個使用者、每個工具自適應。
 *
 * 答案是自適應,而且理由是實測出來的:輸出長度的全域預設原本是 400 字,
 * 而真實資料的中位數是 126 字。用全域值的話,一半的正常回覆會被判成
 * 「輸出壓縮」。那不是門檻設錯,是「一個數字適用所有人」這個假設錯了。
 *
 * ── 基線本身會被污染 ─────────────────────────────────
 *
 * 這是自適應方案最大的坑:如果一個 session 從頭到尾都不健康,
 * 拿它自己的歷史當基線,等於把不健康定義成正常,然後永遠不會告警。
 *
 * 所以基線有三條防線:
 *   一,只用「有已驗證產出」的窗口當樣本。做出過東西的時段才有資格定義正常。
 *   二,樣本不足時回 null,不回一個勉強算出來的數字。
 *   三,基線本身帶著樣本數與時間範圍,呼叫端看得到它有多可信。
 *
 * 零依賴。
 */

export const VERSION = 'baseline@0.1';

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 至少要幾個樣本才算得出基線。
   * 【二十個沒有實測校準。】太少會被幾筆極端值帶走,太多則新使用者永遠等不到基線。
   */
  minSamples: 20,
  /** 用哪個分位當基線。中位數對極端值穩健。 */
  quantile: 0.5,
  /** 偏離基線多少算異常。以基線的倍數計。 */
  deviationFactor: 0.5,
});

const q = (arr, p) => {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(s.length * p))];
};

/**
 * 從樣本算一條基線。
 *
 * @param {number[]} samples
 * @param {object} p
 * @param {number} p.from  樣本的時間範圍起點
 * @param {number} p.to
 * @param {boolean} p.healthyOnly  這些樣本是不是只取自「有已驗證產出」的時段。
 *   false 的話基線會被標成可能污染 —— 一個從頭壞到尾的 session
 *   拿自己當基線,等於把壞定義成正常。
 */
export function fit(samples, { from = null, to = null, healthyOnly = false, config = DEFAULT_CONFIG } = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const list = (samples ?? []).filter((x) => typeof x === 'number' && Number.isFinite(x));
  if (list.length < c.minSamples) {
    return Object.freeze({
      value: null,
      samples: list.length,
      /** 樣本不足時回 null,不回一個勉強算出來的數字。 */
      note: `Only ${list.length} sample(s); need ${c.minSamples}. No baseline - not a default one.`,
      version: VERSION,
    });
  }
  return Object.freeze({
    value: q(list, c.quantile),
    p10: q(list, 0.1),
    p90: q(list, 0.9),
    samples: list.length,
    from, to,
    healthy_only: healthyOnly,
    /**
     * 沒有限定在健康時段的基線可能被污染。這個旗標要跟著基線走,
     * 不然一個學會了不健康的基線,看起來會跟一條正常的基線一模一樣。
     */
    possibly_contaminated: !healthyOnly,
    note: healthyOnly ? null
      : 'Fitted over all windows, including unhealthy ones. A session that was never healthy '
        + 'will teach this baseline that its own dysfunction is normal.',
    version: VERSION,
  });
}

/**
 * 一個值相對於基線偏離多少。
 *
 * 沒有基線時回 null,不拿全域預設頂替 —— 那正是這個模組要取代的東西。
 */
export function deviation(value, baseline, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  if (baseline?.value == null || typeof value !== 'number') {
    return Object.freeze({
      ratio: null, abnormal: false,
      note: 'No baseline for this measure. A global default would defeat the purpose of fitting one.',
      version: VERSION,
    });
  }
  const ratio = value / baseline.value;
  const abnormal = ratio < (1 - c.deviationFactor) || ratio > (1 + c.deviationFactor);
  return Object.freeze({
    ratio,
    abnormal,
    direction: ratio < 1 ? 'BELOW' : (ratio > 1 ? 'ABOVE' : 'AT'),
    baseline: baseline.value,
    /** 基線可能被污染時,任何基於它的判斷都要帶著那個警告。 */
    baseline_contaminated: baseline.possibly_contaminated === true,
    note: baseline.possibly_contaminated
      ? 'This comparison rests on a baseline that may have been fitted over unhealthy windows.'
      : null,
    version: VERSION,
  });
}

/**
 * 每個工具各自的基線。
 *
 * 規格書問的是「全域 vs 每使用者/每工具」。答案是兩者都要:
 * Bash 跟 Read 的耗時本來就差一個量級,用同一條基線判它們,
 * 會讓慢工具永遠告警、快工具永遠不告警。
 *
 * @param {Array} samples [{ key, value }]
 */
export function fitPerKey(samples, opts = {}) {
  const byKey = new Map();
  for (const s of (samples ?? [])) {
    if (!s?.key || typeof s.value !== 'number') continue;
    if (!byKey.has(s.key)) byKey.set(s.key, []);
    byKey.get(s.key).push(s.value);
  }
  const out = new Map();
  const insufficient = [];
  for (const [k, vals] of byKey) {
    const b = fit(vals, opts);
    out.set(k, b);
    if (b.value === null) insufficient.push(k);
  }
  return Object.freeze({
    baselines: out,
    keys: Object.freeze([...out.keys()].sort()),
    /** 樣本不足的那些要列出來,不然呼叫端會以為它們是正常的。 */
    insufficient: Object.freeze(insufficient.sort()),
    version: VERSION,
  });
}
