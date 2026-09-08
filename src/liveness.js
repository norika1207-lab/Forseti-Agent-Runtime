/**
 * Forseti v2.0 — P7:Runtime Detector Pack(liveness 那一半)
 *
 * 規格來源:`docs/spec-v2.0.md` §14(Tool / Running Task Failure)、
 * §22.11(FP-13 Phantom Verification)、§22.15(FP-20 Silent Liveness Failure)、
 * §7.3(TOS)、§7.4(RL)。對應 CT-019、CT-021、CT-029、CT-030、CT-043。
 *
 * ── 這一組全部要在看不到 Thinking 的前提下運作 ──────────
 *
 * §14 的開頭講清楚了:使用者描述的可重複 pattern 是回答字數下降、
 * 工具呼叫增加、Running Task 長達 10-30 分鐘、畫面沒有答案,
 * 手動 ESC 之後 agent 才承認 task 其實早就完成了。
 *
 * 這些全部要靠外部行為診斷。這個模組不讀任何思考內容,
 * 只看時間、log 成長、artifact 成長、heartbeat、exit code。
 *
 * ── 最容易寫錯的一條 ────────────────────────────────
 *
 * FS-TOOL-001:Duration alone MUST NOT 判 stall。
 *
 * 「跑很久」是最好取得的訊號,也是最沒有資訊量的訊號。一個編譯跑
 * 二十分鐘完全正常,一個空迴圈跑二十分鐘完全不正常,而兩者的
 * duration 一模一樣。分辨它們的是「有沒有東西在長大」,不是時間。
 *
 * 所以這個模組的每一個判定都要求至少一個 growth 訊號,
 * 拿不到 growth 訊號的時候回 UNKNOWN_TOOL_FAILURE,不猜。
 *
 * 零依賴。
 */

export const VERSION = 'liveness@2.0';

/** §14 的六個 class,名稱一字不改。 */
export const TASK_CLASSES = Object.freeze([
  'LONG_VALID_TASK',
  'TOOL_LOOP',
  'OUTPUT_STARVATION',
  'STALE_WATCHER',
  'PROCESS_STALL',
  'UNKNOWN_TOOL_FAILURE',
]);

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 【這三個門檻都沒有實測校準。】
   * §14 提到使用者觀察到的 Running Task 是 10-30 分鐘,所以 10 分鐘
   * 是那個區間的下緣,不是量出來的最佳值。重跑校準見 tools/calibrate.mjs。
   */
  longRunningMs: 10 * 60 * 1000,
  heartbeatStaleMs: 2 * 60 * 1000,
  /** 等價嘗試幾次以上算迴圈。§7.4 的公式用 (n-1)/4,這裡沿用。 */
  retryDivisor: 4,
});

/**
 * 一個長時間工作到底是哪一種。
 *
 * 判定順序是刻意的:先問有沒有在長大,再問時間。反過來的話,
 * duration 會先進到判斷裡,而 FS-TOOL-001 禁止那件事。
 *
 * @param {object} p
 * @param {number} p.durationMs
 * @param {boolean|null} p.logGrowing
 * @param {boolean|null} p.artifactGrowing
 * @param {boolean|null} p.stateGrowing
 * @param {number|null} p.lastHeartbeatAgeMs
 * @param {boolean|null} p.taskAlreadyCompleted 事後才發現其實早就跑完了
 * @param {number|null} p.visibleOutputRate 使用者看得到的實質輸出速率
 */
export function classifyLongTask({
  durationMs = null,
  logGrowing = null,
  artifactGrowing = null,
  stateGrowing = null,
  lastHeartbeatAgeMs = null,
  taskAlreadyCompleted = null,
  visibleOutputRate = null,
  config = DEFAULT_CONFIG,
} = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const growthSignals = [logGrowing, artifactGrowing, stateGrowing];
  const measured = growthSignals.filter((g) => g !== null);

  // 沒有任何 growth 訊號 = 不能判。這是 FS-TOOL-001 的直接後果。
  if (!measured.length) {
    return Object.freeze({
      class: 'UNKNOWN_TOOL_FAILURE',
      duration_ms: durationMs,
      /** 這句話是這個模組存在的理由之一。 */
      note: 'No growth signal was observable (log, artifact or state). Duration alone '
        + 'MUST NOT be used to call a stall (FS-TOOL-001). External evidence is '
        + 'insufficient, and inventing an internal cause is forbidden.',
      confidence: null,
      duration_alone_was_not_used: true,
      version: VERSION,
    });
  }

  const growing = measured.some((g) => g === true);

  // CT-030:task 其實早就完成了,但前景還在等。
  if (taskAlreadyCompleted === true) {
    return Object.freeze({
      class: 'STALE_WATCHER',
      duration_ms: durationMs,
      note: 'The task had already completed while the foreground kept waiting. '
        + 'The wasted time is the watcher\'s, not the task\'s.',
      confidence: 1,
      duration_alone_was_not_used: true,
      version: VERSION,
    });
  }

  // CT-029:有東西在長大 = 長但正常。
  if (growing) {
    const starved = visibleOutputRate !== null && visibleOutputRate <= 0;
    return Object.freeze({
      class: starved ? 'OUTPUT_STARVATION' : 'LONG_VALID_TASK',
      duration_ms: durationMs,
      growth: Object.freeze({ log: logGrowing, artifact: artifactGrowing, state: stateGrowing }),
      note: starved
        ? 'Work is progressing but the user can see none of it. The process is healthy; '
          + 'the human is blind.'
        : 'Long duration with observable growth is not a failure (FS-TOOL-001).',
      confidence: 1,
      duration_alone_was_not_used: true,
      version: VERSION,
    });
  }

  // 沒有在長大。這時候 heartbeat 才有意義。
  const heartbeatStale = lastHeartbeatAgeMs !== null
    && lastHeartbeatAgeMs > c.heartbeatStaleMs;

  return Object.freeze({
    class: heartbeatStale ? 'PROCESS_STALL' : 'OUTPUT_STARVATION',
    duration_ms: durationMs,
    growth: Object.freeze({ log: logGrowing, artifact: artifactGrowing, state: stateGrowing }),
    last_heartbeat_age_ms: lastHeartbeatAgeMs,
    note: heartbeatStale
      ? 'Nothing is growing and the heartbeat has gone quiet.'
      : 'Nothing is growing but the process still reports in. It is alive and not working.',
    confidence: measured.length === 3 ? 1 : 0.6,
    unmeasured_growth_signals: Object.freeze(
      [['log', logGrowing], ['artifact', artifactGrowing], ['state', stateGrowing]]
        .filter(([, v]) => v === null).map(([k]) => k),
    ),
    duration_alone_was_not_used: true,
    thresholds_uncalibrated: true,
    version: VERSION,
  });
}

/**
 * §7.4 的 RL(Retry Loop)。
 *
 * ```
 * equivalent_attempt = same intent class + same target layer/resource
 *                    + materially same strategy
 * RL = min(1, max(0,(equivalent_attempt_count-1)/4)) × I[no_state_change]
 * ```
 *
 * FS-MET-RL-001:有新證據或真的換了策略之後的 retry,不算同一個迴圈。
 */
export function retryLoop(attempts = [], { config = DEFAULT_CONFIG } = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  if (!attempts.length) {
    return Object.freeze({
      rl: null, groups: Object.freeze([]),
      note: 'No attempts recorded. RL is unknown, not zero.',
      version: VERSION,
    });
  }

  const groups = new Map();
  for (const a of attempts) {
    // 換了策略或拿到新證據的,自己開一組,不跟前面的算在一起。
    const key = [a.intent_class, a.target, a.strategy].join('|');
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(a);
  }

  const scored = [...groups.entries()].map(([key, list]) => {
    const stateChanged = list.some((a) => a.state_changed === true);
    const newEvidence = list.some((a) => a.new_evidence === true);
    const n = list.length;
    const raw = Math.min(1, Math.max(0, (n - 1) / c.retryDivisor));
    return Object.freeze({
      key,
      attempts: n,
      state_changed: stateChanged,
      new_evidence: newEvidence,
      /** FS-MET-RL-001:狀態變了或有新證據,就不是空轉。 */
      rl: (stateChanged || newEvidence) ? 0 : raw,
    });
  });

  const worst = scored.reduce((a, b) => (b.rl > a.rl ? b : a));
  return Object.freeze({
    rl: worst.rl,
    worst_group: worst,
    groups: Object.freeze(scored),
    class: worst.rl > 0 ? 'TOOL_LOOP' : 'OK',
    thresholds_uncalibrated: true,
    version: VERSION,
  });
}

/**
 * FP-20 Silent Liveness Failure。§22.15。
 *
 * 原文:liveness 必須由 endpoint/process/heartbeat/output growth 組合,
 * 而不是「restart command 下過」或「第一秒 activating」。
 *
 * CASE-D 的原案:service 被改壞、restart 大量發生,23 小時沒有任何 alert。
 * 那 23 小時裡每一次 restart 指令都成功回傳了。
 */
export function silentLivenessFailure({
  restartIssued = null,
  processAlive = null,
  endpointHealthy = null,
  heartbeatFresh = null,
  outputGrowing = null,
  watchdogReportsHealthy = null,
} = {}) {
  /** restart 下過不算證據,所以它連進不進判斷都不進,只被記錄。 */
  const realSignals = { processAlive, endpointHealthy, heartbeatFresh, outputGrowing };
  const measured = Object.entries(realSignals).filter(([, v]) => v !== null);

  if (!measured.length) {
    return Object.freeze({
      primitive_id: 'FP-20',
      verdict: 'UNKNOWN',
      healthy: null,
      restart_issued_is_not_evidence: true,
      note: 'No real liveness signal was observable. A restart command returning 0 says '
        + 'nothing about whether the service works (§22.15).',
      version: VERSION,
    });
  }

  const bad = measured.filter(([, v]) => v === false).map(([k]) => k);
  const healthy = bad.length === 0;
  const mismatch = watchdogReportsHealthy === true && !healthy;

  return Object.freeze({
    primitive_id: 'FP-20',
    verdict: mismatch ? 'SILENT_LIVENESS_FAILURE' : healthy ? 'HEALTHY' : 'UNHEALTHY',
    healthy,
    failing_signals: Object.freeze(bad),
    /** 這一條是 FP-20 的核心:壞了,而且監控說沒事。 */
    watchdog_state_mismatch: mismatch,
    restart_issued: restartIssued,
    restart_issued_is_not_evidence: true,
    unmeasured_signals: Object.freeze(
      Object.entries(realSignals).filter(([, v]) => v === null).map(([k]) => k),
    ),
    severity_family: mismatch ? 'B' : null,
    note: mismatch
      ? 'The service is unhealthy while the watchdog reports healthy. This is a State '
        + 'Mismatch in the monitoring itself - the failure that hides failures.'
      : null,
    version: VERSION,
  });
}

/**
 * FP-13 Phantom Verification。§22.11。
 *
 * 必須整條走完才算數:
 * `STARTED → COMPLETED → OUTPUT_EXISTS → OUTPUT_READ/CONSUMED → RESULT_LINKED_TO_CLAIM`
 *
 * CASE-E 的原案:一個 workflow 跑了 8 個 agent、留下 1.4 MB transcript、
 * 從未完成、沒有輸出,而它被拿來當「交叉驗證」提高主報告的可信度。
 * 那句話在當下就發揮了作用,而作用是假的。
 */
export const VERIFICATION_STAGES = Object.freeze([
  'STARTED', 'COMPLETED', 'OUTPUT_EXISTS', 'OUTPUT_CONSUMED', 'RESULT_LINKED_TO_CLAIM',
]);

export function phantomVerification(workflow = {}) {
  const reached = [];
  for (const stage of VERIFICATION_STAGES) {
    const key = stage.toLowerCase();
    if (workflow[key] === true) reached.push(stage);
    else break;                       // 階段是有序的,斷在哪裡就是哪裡
  }
  const complete = reached.length === VERIFICATION_STAGES.length;
  const usedAsConfidence = workflow.cited_as_verification === true;

  return Object.freeze({
    primitive_id: 'FP-13',
    verdict: (!complete && usedAsConfidence) ? 'PHANTOM_VERIFICATION'
      : complete ? 'VERIFIED' : 'INCOMPLETE',
    stages_reached: Object.freeze(reached),
    stopped_at: complete ? null : VERIFICATION_STAGES[reached.length],
    /** CT-019 / CT-043:沒走完就不准拿來提高信心。 */
    may_increase_confidence: complete,
    cited_as_verification: usedAsConfidence,
    agents_spawned: workflow.agents_spawned ?? null,
    transcript_bytes: workflow.transcript_bytes ?? null,
    severity_family: (!complete && usedAsConfidence) ? 'B' : null,
    /** 資源燒得越多越不能當證據,這一點跟直覺相反,所以寫出來。 */
    note: (!complete && usedAsConfidence)
      ? 'A validation workflow was cited as verification before reaching '
        + `${VERIFICATION_STAGES[reached.length]}. Spawning agents and growing a transcript `
        + 'is cost, not evidence - a large phantom is still a phantom (FP-13).'
      : null,
    version: VERSION,
  });
}

/**
 * §7.3 的 TOS(Tool Occupancy / Output Starvation)。
 *
 * ```
 * TOS = 0.40×tool_occupancy + 0.35×output_starvation + 0.25×stalled_task
 * ```
 *
 * 任何一項拿不到就回 null,而不是把它當 0 —— 那會讓一個什麼都沒接的
 * 系統看起來完全健康,是健康量測工具最危險的失敗模式。
 */
export function toolOccupancyStarvation({
  toolWallTime = null,
  activeSessionTime = null,
  substantiveOutputRate = null,
  stalledTask = null,
} = {}) {
  const occupancy = (toolWallTime === null || !activeSessionTime)
    ? null : toolWallTime / activeSessionTime;
  const starvation = substantiveOutputRate === null
    ? null : 1 - Math.max(0, Math.min(1, substantiveOutputRate));
  const stalled = stalledTask === null ? null : (stalledTask ? 1 : 0);

  const parts = [
    ['tool_occupancy', occupancy, 0.40],
    ['output_starvation', starvation, 0.35],
    ['stalled_task', stalled, 0.25],
  ];
  const missing = parts.filter(([, v]) => v === null).map(([k]) => k);

  if (missing.length) {
    return Object.freeze({
      tos: null,
      components: Object.freeze(Object.fromEntries(parts.map(([k, v]) => [k, v]))),
      missing_components: Object.freeze(missing),
      note: `Cannot compute TOS: ${missing.join(', ')} unmeasured. Treating an unmeasured `
        + 'component as zero would make an unwired system look perfectly healthy.',
      version: VERSION,
    });
  }
  return Object.freeze({
    tos: parts.reduce((a, [, v, w]) => a + v * w, 0),
    components: Object.freeze(Object.fromEntries(parts.map(([k, v]) => [k, v]))),
    missing_components: Object.freeze([]),
    version: VERSION,
  });
}

/**
 * FS-TOOL-002 [PROVISIONAL]:同一個 signature 在同一 session 第二次出現時,
 * SHOULD 提升 recurrence risk。
 *
 * 規格書自己標了這條需要 corpus 校準,所以回傳帶
 * `provisional: true`,而且不給一個看起來很確定的分數。
 */
export function recurrenceRisk(signatures = []) {
  const counts = new Map();
  for (const s of signatures) counts.set(s, (counts.get(s) ?? 0) + 1);
  const repeated = [...counts.entries()].filter(([, n]) => n >= 2);

  return Object.freeze({
    repeated_signatures: Object.freeze(repeated.map(([sig, n]) => Object.freeze({ sig, count: n }))),
    elevated: repeated.length > 0,
    /** 規格書 §14 自己標 PROVISIONAL,所以這裡不給數值分數。 */
    provisional: true,
    note: repeated.length
      ? 'The same failure signature has recurred in one session. This raises priority for '
        + 'inspection; the magnitude of the raise is not calibrated (FS-TOOL-002).'
      : null,
    version: VERSION,
  });
}
