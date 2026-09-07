/**
 * Forseti：偵測器一致性契約
 *
 * 規格書 v0.1 第 16 節的實作。原文的要求是硬的:
 *
 *   任何輸出 drift、deception、failure 或 safe 的偵測器,
 *   若沒有暴露以下七項,就是實驗性的,而且 MUST 標成實驗性:
 *   (1) 輸入事件 (2) 計算方式與版本 (3) 門檻 (4) 排除條件
 *   (5) 信心與知識論狀態 (6) 使用者看得懂的解釋 (7) 連結的復原行為
 *
 * 這個模組不判斷任何事情,它只檢查「一個判斷有沒有資格被當成判斷」。
 *
 * ── 為什麼是七項而不是三項 ─────────────────────────────
 *
 * 少掉任何一項,結論就會被當成比它實際更硬的東西:
 *
 *   沒有版本   → 兩次結果不一樣時,分不出是資料變了還是演算法變了
 *   沒有門檻   → 使用者不知道它為什麼在這裡叫、那裡不叫
 *   沒有排除   → 分不出「檢查過沒事」跟「這個情況根本不在檢查範圍內」
 *   沒有知識論 → 推測會被當成觀測
 *   沒有解釋   → 只能選擇相信或不信,沒有第三條路
 *   沒有復原   → 講了問題卻沒有下一步,那是製造焦慮不是產品
 *
 * 零依賴。
 */

/**
 * 知識論分級。規格書第 1 節,一字不改。
 * 順序有意義:VERIFIED 最強,REFUTED 表示曾經的主張已被更強的證據推翻。
 */
export const EPISTEMIC = Object.freeze([
  'OBSERVED',   // 直接捕捉到的事件或產物事實
  'VERIFIED',   // 觀測到的事實,經獨立驗證契約檢查過
  'INFERRED',   // 從訊號推導,未經直接證明
  'UNKNOWN',    // 需要的證據不存在或已過期
  'REFUTED',    // 先前的假設被更強的證據推翻
  'STALE',      // 曾經有效,但對當前主張已經不夠新
]);

/** 七項必要欄位。規格書第 16 節。 */
export const REQUIRED_FIELDS = Object.freeze([
  'inputs',       // 用了哪些事件
  'version',      // 計算方式與版本
  'thresholds',   // 門檻
  'exclusions',   // 排除條件:什麼情況下這個偵測器不作數
  'epistemic',    // 知識論狀態
  'explanation',  // 使用者看得懂的一句話
  'recovery',     // 連結的復原行為;沒有可做的事就明確寫 null 並說明
]);

/** 需要這份契約的字眼。規格書第 16 節列的四個。 */
export const GOVERNED_VERDICTS = Object.freeze(['drift', 'deception', 'failure', 'safe']);

function assertEpistemic(state) {
  if (!EPISTEMIC.includes(state)) {
    throw new TypeError(`Unrecognised epistemic state: ${String(state)}. Valid: ${EPISTEMIC.join(' / ')}`);
  }
  return state;
}

/**
 * 包一個偵測結果,並檢查它有沒有資格被當成判斷。
 *
 * 缺欄位不會拋錯 —— 拋錯會讓開發者傾向於填一個假的值進去。
 * 缺欄位會讓 conformant 變成 false,而且 missing 會列出來,
 * 那比一個填滿了空話的完整結構誠實。
 *
 * @param {object} p
 * @param {string} p.detector    偵測器名稱
 * @param {string} p.version     計算方式的版本。改演算法就要進版。
 * @param {*} p.verdict          結論本身
 * @param {string} p.epistemic   見 EPISTEMIC
 * @param {object} p.inputs      用了哪些事件,以及多少筆
 * @param {object} p.thresholds  這次判斷用到的門檻值
 * @param {string[]} p.exclusions 什麼情況下這個結論不作數
 * @param {string} p.explanation 一句話,寫給人看的
 * @param {object|null} p.recovery 可做的下一步;沒有就 null 並在 explanation 說明
 */
export function detectorResult(p = {}) {
  const missing = REQUIRED_FIELDS.filter((f) => p[f] === undefined);
  const epistemic = p.epistemic === undefined ? 'UNKNOWN' : assertEpistemic(p.epistemic);

  return Object.freeze({
    detector: p.detector ?? 'UNNAMED',
    verdict: p.verdict ?? null,
    epistemic,
    inputs: Object.freeze(p.inputs ?? {}),
    version: p.version ?? null,
    thresholds: Object.freeze(p.thresholds ?? {}),
    exclusions: Object.freeze([...(p.exclusions ?? [])]),
    explanation: p.explanation ?? null,
    recovery: p.recovery ?? null,
    /** 七項齊全才算數。 */
    conformant: missing.length === 0,
    missing_fields: Object.freeze(missing),
    /**
     * 不齊全的偵測器必須被標成實驗性,而且這個標記要跟結論一起傳下去,
     * 不可以在中途被拿掉。規格書第 16 節。
     */
    experimental: missing.length > 0,
  });
}

/**
 * 這個結論可以被當成事實講嗎。
 *
 * 只有 OBSERVED 與 VERIFIED 可以。其他一律要標成推測、未知或已被推翻。
 * 規格書第 1 節:模型流利的自我解釋永遠不足以把 INFERRED 升成 VERIFIED。
 */
export function statableAsFact(result) {
  return result.epistemic === 'OBSERVED' || result.epistemic === 'VERIFIED';
}

/**
 * 一組偵測結果裡,有幾個夠格、幾個是實驗性的。
 *
 * 這個數字要跟報告一起出現。一份全部由實驗性偵測器組成的報告,
 * 看起來會跟一份全部經過驗證的報告一模一樣,那正是要防的事。
 */
export function conformanceSummary(results) {
  const list = results ?? [];
  const experimental = list.filter((r) => r.experimental);
  const byState = {};
  for (const r of list) byState[r.epistemic] = (byState[r.epistemic] ?? 0) + 1;
  return Object.freeze({
    total: list.length,
    conformant: list.length - experimental.length,
    experimental: experimental.length,
    experimental_detectors: Object.freeze([...new Set(experimental.map((r) => r.detector))].sort()),
    by_epistemic: Object.freeze(byState),
    /** 全部都是實驗性時,整份報告就是實驗性的,不可以只在個別項目上標。 */
    report_is_experimental: list.length > 0 && experimental.length === list.length,
  });
}

/**
 * 沒有可靠目標時的標準回覆。
 *
 * 規格書第 4.1 節:GoalState 為 MISSING 時,
 * UI MUST 說「goal alignment cannot be determined」,
 * MUST NOT 說「agent drifted」。這個函式讓那句話只有一個寫法。
 */
export function cannotDetermine(detector, reason, { version = null, inputs = {} } = {}) {
  return detectorResult({
    detector,
    verdict: null,
    epistemic: 'UNKNOWN',
    inputs,
    version,
    thresholds: {},
    exclusions: [reason],
    explanation: 'Goal alignment cannot be determined: ' + reason,
    recovery: null,
  });
}
