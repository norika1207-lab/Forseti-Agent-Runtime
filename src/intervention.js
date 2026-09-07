/**
 * Forseti：觀測面與介入面
 *
 * 規格書 v0.1 第 9、10、11 節。三節講的是同一件事的三面:
 * 什麼時候可以動手,動手前要問什麼,以及動手本身會怎麼污染觀測。
 *
 * ── 觀測者效應是這裡最硬的一條 ────────────────────────
 *
 * 規格書 9.1:不可以持續盤問被觀測的模型,因為那會改變正在被量測的東西。
 *
 * 這不是禮貌問題,是量測問題。每問一次「你還在跟著目標嗎」,
 * 那個問題本身就進了 context,而接下來的行為是「被問過之後的行為」,
 * 不是「原本的行為」。問十次之後,你量到的是你自己造成的東西。
 *
 * 所以每一次注入都必須被記成 intervention event,
 * 後續分析才分得出「介入前」跟「介入後」。這條沒有例外。
 *
 * ── 高溫不是動手的理由 ───────────────────────────────
 *
 * 規格書第 11 節:硬介入必須有比高溫更多的東西。
 * 溫度只是「值得看一眼」,不是「可以出手」。
 * 每一種動作各自有前置條件,而且都比溫度嚴格。
 *
 * 零依賴。這個模組不執行任何介入,它只回答「可不可以」與「該問什麼」。
 */

export const VERSION = 'intervention@0.1';

/** 兩個面。規格書第 9 節。 */
export const PLANES = Object.freeze({
  OBSERVATION: 'OBSERVATION',   // 預設開著
  INTERVENTION: 'INTERVENTION', // 預設關著,除非被觸發
});

/** 介入動作。規格書第 11 節那張表,一列一個。 */
export const ACTIONS = Object.freeze([
  'QUIET_ANNOTATION',   // 安靜標註
  'SUGGEST_RECOVERY',   // 建議復原
  'FREEZE_RETRY',       // 凍結重複重試
  'REPLAN',             // 重新規劃
  'BLOCK_HIGH_RISK',    // 擋下高風險動作
  'CREATE_SUCCESSOR',   // 建立接班 session
]);

/**
 * 診斷探針的欄位。規格書第 10 節,一字不改。
 *
 * 這個探針刻意不問「你是不是飄移了」。那個問題只會拿到一個
 * 流利的否認,而流利本身不是證據。它問的是連結與證據:
 * 你以為目標是什麼、現在這一步為什麼推進那個目標、
 * 什麼證據會推翻你現在的策略。
 *
 * 最後兩欄是重點:一個講不出「什麼會推翻我」的策略,
 * 沒有辦法被證偽,也就沒有辦法被檢驗。
 */
export const PROBE_FIELDS = Object.freeze([
  'current_goal_as_understood',
  'current_step',
  'why_this_step_advances_goal',
  'required_constraints',
  'evidence_of_progress',
  'what_would_falsify_current_strategy',
  'next_step_if_falsified',
]);

/**
 * 產生一個診斷探針。
 *
 * 回傳的東西本身就是一次介入 —— 它會進到被觀測者的 context。
 * 所以它帶著 must_log_as_intervention: true,提醒宿主一定要記錄,
 * 不然後續分析會把「被問過之後的行為」當成「原本的行為」。
 */
export function buildProbe({ reason = null, windowRef = null } = {}) {
  return Object.freeze({
    fields: PROBE_FIELDS,
    reason,
    window_ref: windowRef,
    /** 這個探針不問「你是不是飄移了」。問了只會拿到流利的否認。 */
    forbidden_phrasings: Object.freeze([
      'Are you drifting?',
      'Are you still following the goal?',
      'Is everything on track?',
    ]),
    must_log_as_intervention: true,
    /** 回答本身是 DECLARED,對照到可觀測的現實之前不會升級。 */
    answer_epistemic_ceiling: 'INFERRED',
    version: VERSION,
  });
}

/**
 * 評估一份探針回答。
 *
 * 規格書第 10 節最後一句是這個函式的全部依據:
 * 答不出來會提高不確定性,但它本身不證明欺騙。
 *
 * 所以這裡只回報「哪幾欄沒答」與「哪幾欄跟可觀測的現實對不上」,
 * 不下任何關於意圖的結論。
 */
export function evaluateProbe(answers, observations = {}) {
  const missing = PROBE_FIELDS.filter((f) => answers?.[f] == null || String(answers[f]).trim() === '');
  const contradictions = [];

  // 規格書 AT-PROBE-01:自述說對齊,但磁碟上的證據相反時,可觀測的證據勝出。
  if (answers?.evidence_of_progress && observations.verified_progress === 0) {
    contradictions.push('Claimed evidence of progress, but no verified progress exists in the observable record.');
  }
  if (answers?.current_step && observations.recent_files && observations.claimed_files) {
    const overlap = observations.claimed_files.filter((f) => observations.recent_files.includes(f));
    if (observations.claimed_files.length && overlap.length === 0) {
      contradictions.push('The files named in the answer do not appear in the recent observable record.');
    }
  }

  return Object.freeze({
    answered: PROBE_FIELDS.length - missing.length,
    missing: Object.freeze(missing),
    contradictions: Object.freeze(contradictions),
    /** 沒有講得出「什麼會推翻我」的策略,無法被檢驗。 */
    unfalsifiable: missing.includes('what_would_falsify_current_strategy'),
    /**
     * 這是提高不確定性,不是證明欺騙。規格書第 10 節。
     * 這句話跟結果綁在一起,不可分開引用。
     */
    note: 'Incoherent or missing answers raise uncertainty. They do not by themselves prove deception. '
      + 'Where the answer and the observable record disagree, the observable record wins.',
    version: VERSION,
  });
}

/**
 * 這個介入動作現在可不可以做。規格書第 11 節那張表。
 *
 * 每一種動作的前置條件都比「溫度高」嚴格。這是刻意的:
 * 一個只看溫度就出手的系統,會在第一次誤判之後被關掉,
 * 而被關掉的防線保護不了任何人。
 *
 * @param {string} action  見 ACTIONS
 * @param {object} ctx
 *   temperature            0..1 或 null
 *   verified_anomaly       是否有單一但強的已驗證異常
 *   progress_stagnation    是否停滯
 *   evidence_mismatch      是否有證據不符
 *   retry_budget_exceeded  重試預算是否用盡
 *   hypothesis_refuted     現行假設是否被推翻
 *   prerequisite_unknown   硬前提是否未知或被推翻
 *   checkpoint_available   有沒有可用的快照
 *   user_requested         使用者是否主動要求
 */
export function canIntervene(action, ctx = {}) {
  if (!ACTIONS.includes(action)) {
    throw new TypeError(`Unrecognised action: ${String(action)}. Valid: ${ACTIONS.join(' / ')}`);
  }
  const t = ctx.temperature ?? null;
  const hot = (x) => t !== null && t >= x;
  let ok = false;
  let need = '';

  switch (action) {
    case 'QUIET_ANNOTATION':
      ok = hot(ctx.annotationThreshold ?? 0.5) || ctx.verified_anomaly === true;
      need = 'temperature at or above the annotation threshold, or one strong verified anomaly';
      break;
    case 'SUGGEST_RECOVERY':
      ok = hot(0.7) && (ctx.progress_stagnation === true || ctx.evidence_mismatch === true);
      need = 'high temperature together with progress stagnation or an evidence mismatch';
      break;
    case 'FREEZE_RETRY':
      ok = ctx.retry_budget_exceeded === true && ctx.progress_stagnation === true;
      need = 'retry budget exceeded and no verified progress';
      break;
    case 'REPLAN':
      ok = ctx.hypothesis_refuted === true || ctx.prerequisite_unknown === true;
      need = 'the current hypothesis refuted, or a hard prerequisite invalidated';
      break;
    case 'BLOCK_HIGH_RISK':
      ok = ctx.prerequisite_unknown === true;
      need = 'a hard authority, licence or safety prerequisite that is unknown or refuted';
      break;
    case 'CREATE_SUCCESSOR':
      ok = (hot(0.85) && ctx.checkpoint_available === true) || ctx.user_requested === true;
      need = 'critical health with a checkpoint available, or an explicit user request';
      break;
    default:
      ok = false;
  }

  return Object.freeze({
    action,
    allowed: ok,
    requires: need,
    /** 高溫從來不是單獨的理由。這句話跟每個拒絕一起出現。 */
    note: ok ? null : 'A high temperature alone is never sufficient. ' + need + ' is required.',
    temperature: t,
    version: VERSION,
  });
}

/**
 * 介入紀錄。每一次注入都要進來,不然分不出介入前後。
 *
 * 規格書 9.1:任何注入的問題必須被記成 intervention event。
 */
export function recordIntervention(log, { at, action, reason = null, injected = false }) {
  return Object.freeze([...(log ?? []), Object.freeze({ at, action, reason, injected, version: VERSION })]);
}

/**
 * 實際的介入率與誤報負擔。
 *
 * 規格書第 9 節:OBSERVE 99% / INTERRUPT 1% 是哲學不是常數,
 * 實作必須量實際的中斷率與誤報負擔。所以這個函式存在。
 *
 * 分母為零時回 null。沒有回合就沒有比率,那不是零介入。
 */
export function interventionRate(log, totalTurns) {
  const list = log ?? [];
  const injected = list.filter((i) => i.injected).length;
  if (!totalTurns) {
    // 沒有回合數只讓「比率」算不出來,不代表沒有介入過。
    // 把 injected 寫死成 0 會讓污染觀測的注入從紀錄裡消失。
    return Object.freeze({ rate: null, interventions: list.length, injected, injection_rate: null });
  }
  return Object.freeze({
    rate: list.length / totalTurns,
    interventions: list.length,
    /** 有注入的那些才會污染觀測。純標註不會。 */
    injected,
    injection_rate: injected / totalTurns,
  });
}
