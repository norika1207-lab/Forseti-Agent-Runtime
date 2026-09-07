/**
 * Forseti：原子訊號 S1–S10
 *
 * 規格書 v0.1 第 3.1 節。每個訊號正規化到 0..1,1 代表最不健康。
 *
 * ── 三條貫穿全部十個的規則 ────────────────────────────
 *
 * 一,拿不到資料就回 null,不回 0。
 *   0 的意思是「量過了,沒事」。null 的意思是「沒量到」。
 *   把後者當成前者,會讓一個什麼都沒接的系統看起來完全健康。
 *
 * 二,每個訊號都附帶它自己的但書。
 *   規格書在 S1 就寫了:高佔用如果伴隨已驗證的進展,是良性的。
 *   一個訊號單獨看幾乎都會誤判,所以每個都回 caveat,
 *   而複合分數必須把貢獻最大的幾個列出來(第 3.2 節:
 *   單一純量沒有解釋就是不合格)。
 *
 * 三,窗口大小與衰減常數全部沒有校準。
 *   規格書第 15 節把它們列為「必須校準,不准用猜的」的第一項。
 *   這裡的預設值是為了讓程式跑得起來,不是為了拿來用。
 *
 * 零依賴。
 */

/** 十個訊號的代號與名稱。照規格書第 3.1 節,一字不改。 */
export const SIGNALS = Object.freeze([
  ['S1', 'Tool Occupancy'],
  ['S2', 'Silent Execution'],
  ['S3', 'Output Compression'],
  ['S4', 'Retry Repetition'],
  ['S5', 'Artifact Nullity'],
  ['S6', 'Correction Load'],
  ['S7', 'Verified Progress Stagnation'],
  ['S8', 'Claim-Evidence Gap'],
  ['S9', 'Cancellation Pressure'],
  ['S10', 'Strategy Persistence'],
]);

export const VERSION = 'signals@0.1';

/**
 * 【以下全部沒有實測校準。】規格書第 15 節第一條就是這些值必須校準。
 * 這裡的數字只是為了讓程式能跑,任何拿它們當結論的行為都是誤用。
 */
export const DEFAULT_CONFIG = Object.freeze({
  windowMs: 10 * 60 * 1000,      // 滾動窗口
  silentToleranceMs: 60 * 1000,  // 多久沒有使用者看得見的動靜算沉默
  stagnationFullMs: 30 * 60 * 1000, // 停滯多久算滿分
  retrySimilarity: 0.8,          // 動作相似度門檻
  // 【已校準】126 = 真實每則輸出字數的 p50(130 份 transcript,n=43246)。
  // 原本 400,而 p50 只有 126 —— 那會讓一半的正常回覆被判成「輸出壓縮」。
  // 一個人的資料,不是通用常數。別的團隊請跑 tools/calibrate.mjs 用自己的分佈。
  healthyOutputChars: 126,
});

const clamp01 = (x) => (x < 0 ? 0 : (x > 1 ? 1 : x));

function sig(id, value, caveat, inputs) {
  return Object.freeze({
    id,
    name: SIGNALS.find(([s]) => s === id)?.[1] ?? id,
    value,                       // 0..1 或 null
    /** null 代表沒量到,不是沒事。 */
    measured: value !== null,
    caveat,
    inputs: Object.freeze(inputs ?? {}),
    version: VERSION,
  });
}

/** S1 工具佔用:工具在跑的時間佔窗口的比例。 */
export function s1ToolOccupancy({ toolActiveMs, windowMs } = {}) {
  if (toolActiveMs == null || !windowMs) {
    return sig('S1', null, 'No tool timing data.', {});
  }
  return sig('S1', clamp01(toolActiveMs / windowMs),
    'High occupancy is benign if verified progress is also rising. Never read this one alone.',
    { toolActiveMs, windowMs });
}

/** S2 沉默執行:沒有使用者看得見的動靜的時間,佔實際執行時間的比例。 */
export function s2SilentExecution({ silentMs, activeMs } = {}) {
  if (silentMs == null || !activeMs) {
    return sig('S2', null, 'No liveness data. Cannot tell alive-but-quiet from hung.', {});
  }
  return sig('S2', clamp01(silentMs / activeMs),
    'Measures visible-liveness failure, not correctness. A quiet correct run scores high here.',
    { silentMs, activeMs });
}

/** S3 輸出壓縮:輸出長度相對健康基線的下降。規格書標它是弱證據,不可單獨使用。 */
export function s3OutputCompression({ recentAvgChars, baselineChars } = {}, config = DEFAULT_CONFIG) {
  const base = baselineChars ?? config.healthyOutputChars;
  if (recentAvgChars == null || !base) {
    return sig('S3', null, 'No output baseline.', {});
  }
  const drop = (base - recentAvgChars) / base;
  return sig('S3', clamp01(drop),
    'Weak evidence only; the specification says never use it alone. Terse can mean efficient.',
    { recentAvgChars, baselineChars: base });
}

/**
 * S4 重試重複:窗口內相似的動作重複次數。
 *
 * 規格書要求「相同的未解目標」才算重試。這裡用 key 當作那個目標的代理,
 * 由呼叫端決定 key 怎麼組。不同目標的相同動作不算重試。
 */
export function s4RetryRepetition(actions, config = DEFAULT_CONFIG) {
  const list = actions ?? [];
  if (!list.length) return sig('S4', null, 'No actions in window.', {});
  const counts = new Map();
  for (const a of list) {
    const k = a.key ?? `${a.tool ?? ''}|${a.target ?? ''}`;
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  const most = Math.max(...counts.values());
  // 一次不算重試,兩次開始算。五次以上視為滿分。
  const value = clamp01((most - 1) / 4);
  return sig('S4', value,
    'Requires the same unresolved objective. Repeating an action after the goal changed is not a retry.',
    { distinct: counts.size, most_repeated: most, total: list.length });
}

/** S5 產物虛無:宣稱的產物中站不住的比例。直接吃 artifact.js 的 artifactNullity()。 */
export function s5ArtifactNullity(nullity) {
  if (!nullity || nullity.ratio == null) {
    return sig('S5', null, 'No artifact claims examined.', {});
  }
  return sig('S5', clamp01(nullity.ratio),
    nullity.coverage != null && nullity.coverage < 1
      ? `Only ${(nullity.coverage * 100).toFixed(0)}% of claims were actually checked; this value is a lower bound.`
      : 'Strong reality-mismatch signal.',
    { claimed: nullity.claimed, refuted: nullity.refuted, coverage: nullity.coverage });
}

/**
 * S6 校正負荷:使用者的糾正回合佔總回合的比例。
 *
 * 規格書要求區分「新需求」與「糾正」。這個模組不讀文字,
 * 所以那個區分必須由呼叫端做完再傳進來。分不出來的話這個訊號回 null。
 */
export function s6CorrectionLoad({ corrections, totalTurns, separated } = {}) {
  if (corrections == null || !totalTurns) {
    return sig('S6', null, 'No turn classification supplied.', {});
  }
  if (separated !== true) {
    return sig('S6', null,
      'Corrections were not separated from new requirements. The specification requires that distinction; guessing it here would produce a confident wrong number.',
      { corrections, totalTurns });
  }
  return sig('S6', clamp01(corrections / totalTurns),
    'A correction is not automatically a model failure; requirements legitimately change.',
    { corrections, totalTurns });
}

/** S7 已驗證進展停滯:距離上一次「經過驗證的」推進過了多久。 */
export function s7ProgressStagnation({ lastVerifiedAt, now } = {}, config = DEFAULT_CONFIG) {
  if (lastVerifiedAt == null || now == null) {
    return sig('S7', null,
      'No verified progress has ever been recorded, so stagnation cannot be measured. This is not the same as no stagnation.', {});
  }
  const full = config.stagnationFullMs ?? DEFAULT_CONFIG.stagnationFullMs;
  return sig('S7', clamp01((now - lastVerifiedAt) / full),
    'Core productivity signal. Long verified-progress gaps are normal during genuine investigation.',
    { elapsed_ms: now - lastVerifiedAt, full_scale_ms: full });
}

/** S8 宣稱與證據落差:沒有支撐的實質宣稱佔實質宣稱的比例。 */
export function s8ClaimEvidenceGap({ unsupported, material } = {}) {
  if (unsupported == null || !material) {
    return sig('S8', null, 'No claim inventory. Requires a definition of material claim.', {});
  }
  return sig('S8', clamp01(unsupported / material),
    'High value only where an evidence contract exists. Without one, every claim looks unsupported.',
    { unsupported, material });
}

/** S9 取消壓力:中斷與長時間沉默的次數。 */
export function s9CancellationPressure({ cancels, longSilences, turns } = {}) {
  if (cancels == null || !turns) return sig('S9', null, 'No interruption data.', {});
  return sig('S9', clamp01((cancels + (longSilences ?? 0)) / turns),
    'Measures unsafe-interrupt risk, not user mood.',
    { cancels, longSilences: longSilences ?? 0, turns });
}

/**
 * S10 策略固著:在反證出現之後仍然重複同一個策略。
 *
 * 規格書寫得很精確:證據要真的推翻了前提,這個訊號才強。
 * 所以呼叫端必須傳「反證發生的時間」與「之後仍然重複的次數」,
 * 不是只傳重複次數 —— 沒有反證的重複只是在做同一件事。
 */
export function s10StrategyPersistence({ repeatsAfterRefutation, repeatsTotal, refutedAt } = {}) {
  if (refutedAt == null) {
    return sig('S10', null,
      'No refutation event. Repetition without counter-evidence is just doing the same work, not persisting against evidence.', {});
  }
  if (repeatsAfterRefutation == null || !repeatsTotal) {
    return sig('S10', null, 'No repetition counts supplied.', {});
  }
  return sig('S10', clamp01(repeatsAfterRefutation / repeatsTotal),
    'Strong only when the evidence genuinely refutes the premise.',
    { repeatsAfterRefutation, repeatsTotal });
}

/** 規格書第 3.2 節的權重。標為 provisional,未經標註資料擬合。 */
export const WEIGHTS = Object.freeze({
  S1: 0.12, S2: 0.12, S3: 0.06, S4: 0.10, S5: 0.12,
  S6: 0.10, S7: 0.14, S8: 0.10, S9: 0.06, S10: 0.08,
});

/**
 * 複合溫度 T_runtime。規格書第 3.2 節。
 *
 * 兩條硬規則:
 *
 * 一,分數必須附帶貢獻最大的幾個訊號。規格書原文:
 *   單一純量而沒有解釋,就是不合格。
 *
 * 二,沒量到的訊號不當成 0。它們被排除在分子與分母之外,
 *   而且 measured_weight 會告訴你這個分數是用多少比重的資料算出來的。
 *   用 0 頂替沒量到的訊號,會讓一個什麼都沒接的系統得到滿分健康。
 */
export function composite(signals, config = {}) {
  const w = { ...WEIGHTS, ...(config.weights ?? {}) };
  const list = signals ?? [];
  let num = 0, den = 0;
  const contrib = [];
  for (const s of list) {
    if (s.value === null) continue;
    const weight = w[s.id] ?? 0;
    num += weight * s.value;
    den += weight;
    contrib.push({ id: s.id, name: s.name, value: s.value, contribution: weight * s.value, caveat: s.caveat });
  }
  const totalWeight = Object.values(w).reduce((a, b) => a + b, 0);
  if (den === 0) {
    return Object.freeze({
      temperature: null,
      state: null,
      measured_weight: 0,
      top_contributors: Object.freeze([]),
      unmeasured: Object.freeze(list.filter((s) => s.value === null).map((s) => s.id)),
      note: 'No signal could be measured. This is not a healthy reading; it is no reading.',
      version: VERSION,
    });
  }
  const t = clamp01(num / den);
  contrib.sort((a, b) => b.contribution - a.contribution);
  return Object.freeze({
    temperature: t,
    state: stateOf(t),
    /** 這個分數是用多少比重的資料算出來的。低就代表它不可信。 */
    measured_weight: den / totalWeight,
    top_contributors: Object.freeze(contrib.slice(0, 3).map(Object.freeze)),
    unmeasured: Object.freeze(list.filter((s) => s.value === null).map((s) => s.id)),
    note: den / totalWeight < 0.5
      ? 'Fewer than half the weighted signals were measurable; treat this number as indicative only.'
      : null,
    version: VERSION,
  });
}

/** 規格書第 3.2 節的區間。標明是工程預設值,不是驗證過的常數。 */
export const STATES = Object.freeze(['HEALTHY', 'WATCH', 'ELEVATED', 'HIGH', 'CRITICAL']);

export function stateOf(t) {
  if (t === null) return null;
  if (t < 0.30) return 'HEALTHY';
  if (t < 0.50) return 'WATCH';
  if (t < 0.70) return 'ELEVATED';
  if (t < 0.85) return 'HIGH';
  return 'CRITICAL';
}
