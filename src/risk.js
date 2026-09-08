/**
 * Forseti v2.0 — P10:Composite Runtime Reliability Risk 與 Trend
 *
 * 規格來源:`docs/spec-v2.0.md` §8(Composite R)、§8.1(bands)、§9(Trend)。
 * 對應 CT-037。
 *
 * ── 這個模組跟 v1 thermometer.js 的分工 ─────────────────
 *
 * v1 的 thermometer.js 量的是 context 裡有多少是事實(§7.2 的那個溫度計)。
 * 這裡量的是 §8 的 Composite Runtime Reliability Risk,輸入是 11 個
 * atomic metric,不是 context 佔比。兩個都叫溫度計,但量的不是同一件事,
 * 所以不合併 —— 合併的話,兩個都會變得不知道自己在講什麼。
 *
 * ── 這個模組最重要的一個欄位 ────────────────────────────
 *
 * EvidenceCoverage。FS-RSK-001:Composite R 必須同時顯示它,
 * 低 coverage 的高分不能裝作確定。
 *
 * 一個 0.55,如果是從 22% 的訊號算出來的,跟同一個 0.55 從全部訊號算出來,
 * 是完全不同的兩件事。介面不准讓它們長得一樣(CT-037)。
 *
 * ── 為什麼 trend 比當下的分數重要 ───────────────────────
 *
 * §9 是 owner 明確要求補的:「若 0→1 的數值連續上升,應可預料失衡
 * 正在發生」。單看現在幾度沒有用,一個健康的 session 也會有 spike;
 * 一路往上爬的才是問題。所以 FS-TRD-001 直接禁止用單次 spike 判 degradation。
 *
 * 零依賴。
 */

export const VERSION = 'risk@2.0';

/** §7 的十一個 atomic metric。名稱照規格書表格。 */
export const METRICS = Object.freeze([
  'CED', 'PS', 'TOS', 'RL', 'CB', 'OD', 'SM', 'GAR', 'PAR', 'RB', 'HCD',
]);

/**
 * §8.1 的五個 band。
 *
 * 【全部是 CALIBRATION-CANDIDATE。】規格書原文:「真實 corpus 必須證明
 * false-positive/false-negative 可接受後才能 STABLE」。目前沒有那份 corpus。
 */
export const BANDS = Object.freeze([
  Object.freeze({ max: 0.19, state: 'NORMAL', behavior: 'quiet observe' }),
  Object.freeze({ max: 0.39, state: 'WATCH', behavior: 'increase sampling; passive indicator' }),
  Object.freeze({ max: 0.59, state: 'UNSTABLE', behavior: 'explain top signals; optional challenge' }),
  Object.freeze({ max: 0.79, state: 'DEGRADED', behavior: 'recommend recovery/replan; targeted guard' }),
  Object.freeze({ max: 1.00, state: 'CRITICAL', behavior: 'preserve state; freeze affected strategy where policy permits; rescue' }),
]);

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 【α、k、watch_threshold 全部是 TBD-CALIBRATION。】
   * §9 結尾原文:「v2 不應假裝在沒有 corpus 的情況下已知道最優值」。
   */
  alpha: 0.3,
  k: 5,
  watchThreshold: 0.20,
  /** coverage 低於這個值時,不准給一個看起來確定的 R。 */
  minCoverageForConfidentRisk: 0.5,
});

/**
 * §8 的 composite。
 *
 * ```
 * R = Σ(w_i × s_i × c_i) / Σ(w_i × c_i)
 * EvidenceCoverage = Σ(w_i × c_i) / Σ(w_i)
 * ```
 *
 * 注意分母是 Σ(w_i × c_i) 而不是 Σ(w_i):沒有證據的 metric 不進分母,
 * 所以它不會把分數稀釋成「看起來還好」。這是刻意的 ——
 * 一個什麼都沒量到的系統,R 應該是 null,不是 0。
 *
 * @param {Array} metrics [{ id, score, confidence, weight }]
 */
export function compositeRisk(metrics = [], { config = DEFAULT_CONFIG } = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const known = metrics.filter((m) => m.score !== null && m.score !== undefined
    && m.confidence !== null && m.confidence !== undefined);

  const totalWeight = metrics.reduce((a, m) => a + (m.weight ?? 1), 0);
  const weightedConfidence = known.reduce((a, m) => a + (m.weight ?? 1) * m.confidence, 0);

  if (!known.length || weightedConfidence === 0) {
    return Object.freeze({
      r: null,
      evidence_coverage: totalWeight ? 0 : null,
      state: 'NO_DATA',
      contributors: Object.freeze([]),
      unmeasured: Object.freeze(metrics.filter((m) => m.score === null || m.score === undefined)
        .map((m) => m.id)),
      /** 沒量到任何東西的系統不是健康的系統,是沒接上的系統。 */
      note: 'No metric carries both a score and a confidence. R is null, not zero - '
        + 'an unwired system is not a healthy system.',
      thresholds_uncalibrated: true,
      version: VERSION,
    });
  }

  const numerator = known.reduce((a, m) => a + (m.weight ?? 1) * m.score * m.confidence, 0);
  const r = numerator / weightedConfidence;
  const coverage = totalWeight ? weightedConfidence / totalWeight : null;

  // FS-RSK-001 的實作:低 coverage 時不給一個看起來確定的判定。
  const lowCoverage = coverage !== null && coverage < c.minCoverageForConfidentRisk;

  const contributors = [...known]
    .map((m) => Object.freeze({
      id: m.id,
      contribution: (m.weight ?? 1) * m.score * m.confidence / weightedConfidence,
      score: m.score,
      confidence: m.confidence,
    }))
    .sort((a, b) => b.contribution - a.contribution)
    .slice(0, 3);

  return Object.freeze({
    r,
    /** FS-RSK-001:這兩個永遠一起出現,不可分開引用。 */
    evidence_coverage: coverage,
    state: lowCoverage ? 'LOW_EVIDENCE' : bandOf(r).state,
    band: bandOf(r),
    /** §8 原文:單一 scalar 沒有解釋就是不合格。 */
    top_contributors: Object.freeze(contributors),
    measured: Object.freeze(known.map((m) => m.id)),
    unmeasured: Object.freeze(metrics.filter((m) => m.score === null || m.score === undefined)
      .map((m) => m.id)),
    /** CT-037:高風險但證據覆蓋低 → 不得下確定的判斷、不得硬擋。 */
    may_block: !lowCoverage && r >= 0.80,
    note: lowCoverage
      ? `R computed from ${(coverage * 100).toFixed(0)}% of weighted signals. A confident-`
        + 'looking number from partial evidence is a different thing from the same number '
        + 'computed from all of it, and MUST NOT be presented as equivalent (CT-037).'
      : null,
    thresholds_uncalibrated: true,
    version: VERSION,
  });
}

export function bandOf(r) {
  if (r === null || r === undefined) return Object.freeze({ state: 'NO_DATA', behavior: null });
  for (const b of BANDS) if (r <= b.max) return b;
  return BANDS[BANDS.length - 1];
}

// ---------------------------------------------------------------------------
// §9 Trend
// ---------------------------------------------------------------------------

/**
 * ```
 * EWMA_t = α × score_t + (1-α) × EWMA_(t-1)
 * ```
 *
 * null 的分數會被跳過而不是當成 0。跳過會讓 EWMA 停在原地,
 * 當成 0 會讓它往下掉 —— 後者會把「沒量到」偽裝成「變好了」。
 */
export function ewma(scores = [], { alpha = DEFAULT_CONFIG.alpha } = {}) {
  let prev = null;
  const series = [];
  for (const s of scores) {
    if (s === null || s === undefined) { series.push(prev); continue; }
    prev = prev === null ? s : alpha * s + (1 - alpha) * prev;
    series.push(prev);
  }
  return Object.freeze(series);
}

/**
 * §9 的三個量一起算。
 *
 * FS-TRD-001:單次 spike 不得自動等於 degradation,除非那個事件本身
 * 是 deterministic high-impact contradiction(也就是 Family C)。
 * FS-TRD-003:trend confidence 不足時,「多久會壞」必須回 UNKNOWN。
 */
export function trend(scores = [], {
  config = DEFAULT_CONFIG,
  hasDeterministicContradiction = false,
} = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const measured = scores.filter((s) => s !== null && s !== undefined);

  if (measured.length < 2) {
    return Object.freeze({
      ewma: Object.freeze(ewma(scores, c)),
      velocity: null,
      persistence: null,
      direction: 'UNKNOWN',
      /** FS-TRD-003。 */
      time_to_failure: 'UNKNOWN',
      note: 'Fewer than two measured windows. A direction needs at least two points.',
      thresholds_uncalibrated: true,
      version: VERSION,
    });
  }

  const series = ewma(scores, c);
  const tail = series.slice(-c.k).filter((s) => s !== null);

  // velocity:對最近 k 個 EWMA 值取斜率。
  let velocity = null;
  if (tail.length >= 2) {
    const n = tail.length;
    const meanX = (n - 1) / 2;
    const meanY = tail.reduce((a, b) => a + b, 0) / n;
    const num = tail.reduce((a, y, i) => a + (i - meanX) * (y - meanY), 0);
    const den = tail.reduce((a, _, i) => a + (i - meanX) ** 2, 0);
    velocity = den === 0 ? 0 : num / den;
  }

  const recent = scores.slice(-c.k).filter((s) => s !== null && s !== undefined);
  const persistence = recent.length
    ? recent.filter((s) => s > c.watchThreshold).length / recent.length
    : null;

  const worsening = velocity !== null && velocity > 0;
  const singleSpike = measured.length >= 2
    && Math.max(...measured) > c.watchThreshold
    && persistence !== null && persistence <= 1 / Math.max(recent.length, 1);

  return Object.freeze({
    ewma: Object.freeze(series),
    velocity,
    persistence,
    direction: worsening ? 'WORSENING' : velocity !== null && velocity < 0 ? 'IMPROVING' : 'FLAT',
    /**
     * FS-TRD-001。這個欄位存在的理由:一個健康的 session 也會有 spike,
     * 而拿 spike 當 degradation 會讓這個系統變成 FP-23。
     */
    single_spike_only: singleSpike,
    counts_as_degradation: worsening && !singleSpike,
    /** 只有 Family C 那種確定性的硬矛盾,才可以憑單一事件升級。 */
    spike_escalation_allowed: hasDeterministicContradiction,
    /** FS-TRD-002:持續惡化要提高採樣與 challenge 的優先序,即使還沒到 confirmed。 */
    raise_sampling: worsening,
    raise_challenge_priority: worsening && (persistence ?? 0) > 0.5,
    /** FS-TRD-003:不做沒把握的預測。 */
    time_to_failure: 'UNKNOWN',
    time_to_failure_note: 'Predicting when this breaks requires a calibrated failure curve. '
      + 'None exists yet, so the answer is UNKNOWN rather than a number (FS-TRD-003).',
    windows_measured: measured.length,
    thresholds_uncalibrated: true,
    version: VERSION,
  });
}

/**
 * 把 composite 與 trend 合成一份可以直接給介面用的讀數。
 *
 * 刻意不叫 `score()`:回傳的不是一個數字,而是一個數字加上
 * 「這個數字有多少證據撐著」加上「它往哪裡走」。三個一起才有意義。
 */
export function reading(metrics = [], history = [], { config = DEFAULT_CONFIG, ...rest } = {}) {
  const composite = compositeRisk(metrics, { config });
  const t = trend([...history, composite.r], { config, ...rest });
  return Object.freeze({
    composite,
    trend: t,
    /** 介面要顯示的一句話。低證據時它會講證據,不會講風險。 */
    headline: composite.state === 'LOW_EVIDENCE'
      ? `Insufficient evidence (${((composite.evidence_coverage ?? 0) * 100).toFixed(0)}% coverage)`
      : composite.state === 'NO_DATA'
        ? 'Not measuring anything yet'
        : `${composite.state}${t.direction === 'WORSENING' ? ', worsening' : ''}`,
    version: VERSION,
  });
}
