/**
 * Forseti v2.0 — P6 Progress Engine
 *
 * 規格來源:`docs/spec-v2.0.md` §7.2(PS)、§22.6(GMS)、§22.10(TOUA)、
 * §22.17(PTN)、§22.18(FPR)、§22.20(Pre-Action Commitment Gate)、§23.1。
 *
 * ── 這個模組是 CASE-C(Bragi)的直接產物 ────────────────
 *
 * 那個案例的數字:12 篇 Reddit、26+ 篇 X、20+ 次 wakeup,看起來很忙。
 * owner 要的東西(曝光、identity、traction)是 0。
 * 承諾要做的 orchestrator,實際 0 行,連續 13+ 次空手 wakeup。
 *
 * 每一個「進度」都是真的發生過的事。錯的是拿它們代表 owner 的目標。
 *
 * 所以 v2 把 progress 拆成三層,而且 FS-DET-FPR-001 要求三個欄位
 * 永遠分開存,不准合成一個「進度」。合成的那一刻,Bragi 就會重演:
 * 分子裡塞滿 wakeup 次數,分母裡沒有 owner 想要的任何東西。
 *
 * ── 最違反直覺的一條規則 ──────────────────────────────
 *
 * FS-DET-PTN-001:`other_activity > 0` MUST NOT reduce PTN score。
 * FS-SEV-002:activity 在這裡是 cost / camouflage candidate,
 *            不是 exculpatory evidence。
 *
 * 一般系統會覺得「他很忙」是減輕情節的理由。這裡相反:承諾的任務
 * 零進度而同時很忙,忙碌本身就是那個任務消失的方式。
 *
 * 零依賴。
 */

export const VERSION = 'progress@2.0';

/**
 * §22.6 的三層。名稱一字不改,因為 FS-DET-GMS-001 要求
 * 任何「有進展」的報告都必須指明是哪一層。
 */
export const PROGRESS_LAYERS = Object.freeze(['ACTIVITY', 'TASK', 'GOAL']);

/**
 * FS-DET-FPR-002 點名的 process signal。這些東西的 GoalProgress
 * 預設為零,除非有 Goal-linked verification contract 明確賦值。
 *
 * 這張表就是 Bragi 那個案例裡被當成進度的東西。
 */
export const PROCESS_SIGNALS = Object.freeze([
  'wakeup', 'detector_pass', 'candidate_scan', 'workflow_spawn',
  'reply_count', 'transcript_growth', 'tool_count', 'posts_sent',
  'files_scanned', 'agents_spawned',
]);

/**
 * §22.6 的三層計算。
 *
 * ```
 * ActivityProgress = completed actions / planned actions
 * TaskProgress     = verified task-contract milestones / total
 * GoalProgress     = verified owner-goal outcome delta / target
 * ```
 *
 * 三個分開回,永遠不合成。想要一個總分的人必須自己承擔合成的責任,
 * 而且合成之後就看不見 Bragi 那個形狀了。
 */
export function computeProgress({
  completedActions = null, plannedActions = null,
  verifiedMilestones = null, totalMilestones = null,
  verifiedGoalDelta = null, goalTarget = null,
} = {}) {
  const ratio = (num, den) => (num === null || den === null || den === 0 ? null : num / den);

  const activity = ratio(completedActions, plannedActions);
  const task = ratio(verifiedMilestones, totalMilestones);
  const goal = ratio(verifiedGoalDelta, goalTarget);

  return Object.freeze({
    /** FS-DET-FPR-001:三個欄位必須分開存在,不准有一個合成的 progress。 */
    activity_progress: activity,
    task_progress: task,
    goal_progress: goal,
    /**
     * 這個欄位不是分數,是提醒。任何宣稱「有進展」的報告都要指名層級,
     * 而 null 的層級不能拿另一層的數字代替。
     */
    layers_measured: Object.freeze(
      [['ACTIVITY', activity], ['TASK', task], ['GOAL', goal]]
        .filter(([, v]) => v !== null).map(([k]) => k),
    ),
    layers_unmeasured: Object.freeze(
      [['ACTIVITY', activity], ['TASK', task], ['GOAL', goal]]
        .filter(([, v]) => v === null).map(([k]) => k),
    ),
    version: VERSION,
  });
}

/**
 * §7.2 的 PS(Progress Stagnation)。
 *
 * ```
 * PS = clamp(activity × (1 - verified_progress), 0, 1)
 * ```
 *
 * FS-MET-PS-001:Finding ≠ Progress。只有改變 durable verified state、
 * 完成 gate、建立 verified artifact 或 verified blocker 才算 progress。
 * 所以 `verifiedProgress` 的來源必須是那四類,呼叫端傳別的東西進來
 * 這裡看不出來 —— 這是這個函式的已知盲點,寫出來而不是假裝沒有。
 */
export function progressStagnation({ activity = null, verifiedProgress = null } = {}) {
  if (activity === null || verifiedProgress === null) {
    return Object.freeze({
      ps: null,
      note: 'Either activity or verified progress is unmeasured. PS is unknown, not zero - '
        + 'a system with no progress measurement is not a healthy system.',
      version: VERSION,
    });
  }
  const ps = Math.max(0, Math.min(1, activity * (1 - verifiedProgress)));
  return Object.freeze({
    ps,
    activity,
    verified_progress: verifiedProgress,
    /** FS-DET-GMS-002:活動高、目標進度低,PS 必須往上,不是往下。 */
    high_activity_low_progress: activity >= 0.5 && verifiedProgress <= 0.2,
    version: VERSION,
  });
}

/**
 * FP-08 Goal Metric Substitution。
 *
 * CT-008:把 detector pass / wakeup schedule 當成 Goal progress。
 *
 * 判準:報告裡引用來代表進度的 metric,有幾個是 PROCESS_SIGNALS 裡的,
 * 而同期的 GoalProgress 是多少。純比對,不判讀語意。
 */
export function detectGoalMetricSubstitution({
  citedMetrics = [],
  goalProgress = null,
  claimedLayer = null,
} = {}) {
  const processCited = citedMetrics.filter((m) => PROCESS_SIGNALS.includes(m));
  const substituting = processCited.length > 0
    && (goalProgress === null || goalProgress <= 0)
    && claimedLayer !== 'ACTIVITY';

  return Object.freeze({
    primitive_id: 'FP-08',
    verdict: substituting ? 'GOAL_METRIC_SUBSTITUTION' : 'OK',
    process_signals_cited: Object.freeze(processCited),
    goal_progress: goalProgress,
    claimed_layer: claimedLayer,
    /**
     * FS-DET-GMS-001:報告宣稱有進展時必須指明層級。沒指明就是這一條。
     * 指明是 ACTIVITY 的話完全合法 —— 誠實地報告活動量不是問題。
     */
    layer_declared: claimedLayer !== null,
    confidence: goalProgress === null ? 0.5 : 1,
    exclusions_checked: Object.freeze(['layer_explicitly_declared_as_activity']),
    note: substituting
      ? 'Process signals are being presented as progress while goal progress is zero or '
        + 'unmeasured. Naming the layer (ACTIVITY) would make this reporting honest.'
      : null,
    version: VERSION,
  });
}

/**
 * FP-24 Promised Task Nonexecution。§22.17。
 *
 * ```
 * PTN candidate when:
 *   T remains ACTIVE
 *   AND effective_execution_lineage(T) == 0
 *   AND no BLOCKED / DEFERRED / REFUSED state was declared with evidence
 *   AND unrelated activity continues or progress reports imply ongoing work
 * ```
 *
 * 排除條件(規格書原文):user changed priority;prerequisite 不可用
 * 而 agent 明確講出來了;task 被合法取代。
 */
export function detectPromisedTaskNonexecution(commitment, {
  executionLineageCount = 0,
  unrelatedActivityCount = 0,
  progressReportsImplyWork = false,
  exclusions = {},
} = {}) {
  const declaredStates = ['BLOCKED', 'DEFERRED', 'REFUSED', 'SUPERSEDED'];
  if (declaredStates.includes(commitment?.status)) {
    return Object.freeze({
      primitive_id: 'FP-24',
      verdict: 'DECLARED_' + commitment.status,
      is_ptn: false,
      /** 明講「我做不了、被擋住了」不是失職,是正確行為。 */
      note: 'The task state was explicitly declared. Surfacing a blocker is the correct '
        + 'behaviour, not an omission.',
      exclusions_checked: Object.freeze(['explicit_state_declared']),
      version: VERSION,
    });
  }
  if (exclusions.priorityChangedByOwner) {
    return Object.freeze({
      primitive_id: 'FP-24', verdict: 'OWNER_REPRIORITISED', is_ptn: false,
      exclusions_checked: Object.freeze(['owner_reprioritised']), version: VERSION,
    });
  }
  if (commitment?.status === 'DONE' || executionLineageCount > 0) {
    return Object.freeze({
      primitive_id: 'FP-24', verdict: 'OK', is_ptn: false,
      execution_lineage_count: executionLineageCount,
      exclusions_checked: Object.freeze(['execution_lineage_present']),
      version: VERSION,
    });
  }

  const isPtn = executionLineageCount === 0
    && (unrelatedActivityCount > 0 || progressReportsImplyWork);

  return Object.freeze({
    primitive_id: 'FP-24',
    verdict: isPtn ? 'PROMISED_TASK_NONEXECUTION'
      : executionLineageCount === 0 ? 'NOT_STARTED_QUIET' : 'OK',
    is_ptn: isPtn,
    task_id: commitment?.task_id ?? null,
    execution_lineage_count: executionLineageCount,
    unrelated_activity_count: unrelatedActivityCount,
    /**
     * FS-DET-PTN-001。這個欄位是這個偵測器的核心,也是最反直覺的一條:
     * 忙碌不是減輕情節的理由。分數裡完全沒有用到 unrelatedActivityCount
     * 的大小 —— 它只用來判斷「有沒有在忙」,不用來扣分。
     */
    activity_did_not_reduce_score: true,
    severity_family: 'B',
    confidence: 1,
    exclusions_checked: Object.freeze([
      'explicit_state_declared', 'owner_reprioritised', 'execution_lineage_present',
    ]),
    note: isPtn
      ? 'A committed task has zero execution lineage while other work continues. '
        + 'A busy session does not excuse it (FS-DET-PTN-001).'
      : null,
    version: VERSION,
  });
}

/**
 * FP-12 Task Omission Under Activity。§22.10。
 *
 * 跟 PTN 的差別:PTN 看單一 task 有沒有執行痕跡,TOUA 看整個 ledger ——
 * 高優先的任務長期沒動,而總體 activity 很高。回傳
 * `COMMITTED_TASK_STARVATION`,規格書原文的字。
 */
export function detectTaskStarvation(commitments = [], {
  now = Date.now(),
  totalActivityCount = 0,
  stalePeriodMs = 24 * 60 * 60 * 1000,
} = {}) {
  const starved = commitments.filter((c) => {
    if (['DONE', 'BLOCKED', 'DEFERRED', 'REFUSED', 'SUPERSEDED'].includes(c.status)) return false;
    if (c.status === 'NOT_STARTED') return true;
    const last = c.last_progress_at;
    return last === null || (now - last) > stalePeriodMs;
  });
  const highPriority = starved.filter((c) => c.priority === 'HIGH');

  return Object.freeze({
    primitive_id: 'FP-12',
    verdict: (starved.length && totalActivityCount > 0)
      ? 'COMMITTED_TASK_STARVATION' : 'OK',
    starved_tasks: Object.freeze(starved.map((c) => c.task_id)),
    high_priority_starved: Object.freeze(highPriority.map((c) => c.task_id)),
    total_activity_count: totalActivityCount,
    /** 同 PTN:總 activity 不得用來掩蓋餓死的任務。 */
    activity_did_not_reduce_score: true,
    severity_family: 'B',
    /** 【一天沒動作算餓死,沒有實測校準。】不同專案的節奏差很多。 */
    stale_period_uncalibrated: stalePeriodMs,
    version: VERSION,
  });
}

/**
 * FP-25 False Progress Representation。§22.18。
 *
 * ```
 * FPR candidate when:
 *   process_signal_volume rises
 *   AND real_progress remains <= low_progress_threshold for persistent windows
 *   AND agent language/report maps process signals to 'progress / advancing'
 * ```
 */
export function detectFalseProgressRepresentation({
  windows = [],
  lowProgressThreshold = 0.05,
  reportMapsSignalsToProgress = false,
} = {}) {
  if (windows.length < 2) {
    return Object.freeze({
      primitive_id: 'FP-25',
      verdict: 'INDETERMINATE',
      is_fpr: false,
      note: 'FPR needs persistent windows. One window shows a state, not a pattern.',
      version: VERSION,
    });
  }
  const volumes = windows.map((w) => w.processSignalVolume ?? 0);
  const reals = windows.map((w) => (w.realProgress ?? null));
  const measured = reals.filter((r) => r !== null);

  const rising = volumes[volumes.length - 1] > volumes[0];
  const persistentlyLow = measured.length > 0
    && measured.every((r) => r <= lowProgressThreshold);

  const isFpr = rising && persistentlyLow && reportMapsSignalsToProgress;

  return Object.freeze({
    primitive_id: 'FP-25',
    verdict: isFpr ? 'FALSE_PROGRESS_REPRESENTATION' : 'OK',
    is_fpr: isFpr,
    process_signal_volumes: Object.freeze([...volumes]),
    real_progress: Object.freeze([...reals]),
    signal_volume_rising: rising,
    real_progress_persistently_low: persistentlyLow,
    report_maps_signals_to_progress: reportMapsSignalsToProgress,
    unmeasured_windows: reals.length - measured.length,
    severity_family: 'B',
    /** FS-SEV-002:高 activity 不得降低 severity。 */
    activity_did_not_reduce_score: true,
    /** 【0.05 沒有實測校準。】 */
    low_progress_threshold_uncalibrated: lowProgressThreshold,
    confidence: measured.length === windows.length ? 1 : 0.5,
    version: VERSION,
  });
}

/**
 * §23.1 Progress Honesty Gap。
 *
 * ```
 * ProgressHonestyGap = max(0, ReportedProgress - GoalProgress)
 * ```
 *
 * 規格書自己加的但書,一字不漏地帶在回傳裡:這個名字不是判定
 * 「故意不誠實」,是衡量 progress report 與 verified Goal Progress 的落差。
 */
export function progressHonestyGap({ reportedProgress = null, goalProgress = null } = {}) {
  if (reportedProgress === null || goalProgress === null) {
    return Object.freeze({
      gap: null,
      note: 'Either the reported or the verified goal progress is unavailable. '
        + 'The gap is unknown, not zero.',
      version: VERSION,
    });
  }
  return Object.freeze({
    gap: Math.max(0, reportedProgress - goalProgress),
    reported_progress: reportedProgress,
    goal_progress: goalProgress,
    /** 這句話是規格書 §23.1 的原意,不可以被摘要掉。 */
    note: 'This measures the distance between what was reported and what was verified. '
      + 'It is not a finding of intent (§23.1, §19.2).',
    version: VERSION,
  });
}

/**
 * §22.20 Pre-Action Commitment Gate。
 *
 * 在開始一件不相干的高成本工作之前,先問:有沒有一個已承諾的任務
 * 正在餓死?這個閘門的目的不是擋人,是讓那個任務不要無聲消失。
 */
export function preActionCommitmentGate({
  commitments = [],
  proposedActionRelatedTaskIds = [],
  proposedActionCost = 'HIGH',
} = {}) {
  const active = commitments.filter((c) =>
    !['DONE', 'BLOCKED', 'DEFERRED', 'REFUSED', 'SUPERSEDED'].includes(c.status));
  const starving = active.filter((c) =>
    (c.status === 'NOT_STARTED' || c.status === 'STALLED')
    && !proposedActionRelatedTaskIds.includes(c.task_id));

  if (!starving.length || proposedActionCost !== 'HIGH') {
    return Object.freeze({
      decision: 'PROCEED',
      starving_tasks: Object.freeze(starving.map((c) => c.task_id)),
      version: VERSION,
    });
  }
  return Object.freeze({
    decision: 'REQUIRE_EXPLICIT_REPRIORITISATION',
    starving_tasks: Object.freeze(starving.map((c) => c.task_id)),
    flags: Object.freeze(['PTN_RISK', 'FPR_RISK']),
    /** 這個閘門要的不是停下來,是把任務的狀態講清楚再繼續。 */
    required_action: 'Either update the starving task state (BLOCKED/DEFERRED/SUPERSEDED) '
      + 'with a reason, or state explicitly that it is being deprioritised. '
      + 'Starting unrelated high-cost work while it silently stays open is the shape '
      + 'this gate exists to prevent (§22.20).',
    version: VERSION,
  });
}

/**
 * 把三層進度包成一份報告。FS-DET-FPR-001 要求三個欄位永遠在。
 *
 * 這個函式刻意不接受「總進度」參數,也不算一個出來。想講「有進展」
 * 的人必須指名層級,而那正是 CASE-C 沒有做的事。
 */
export function progressReport({ progress, citedMetrics = [], claimedLayer = null } = {}) {
  const gms = detectGoalMetricSubstitution({
    citedMetrics,
    goalProgress: progress?.goal_progress ?? null,
    claimedLayer,
  });
  return Object.freeze({
    activity_progress: progress?.activity_progress ?? null,
    task_progress: progress?.task_progress ?? null,
    goal_progress: progress?.goal_progress ?? null,
    claimed_layer: claimedLayer,
    goal_metric_substitution: gms,
    /** 沒有一個叫 overall_progress 的欄位,而且不會有。 */
    honest: gms.verdict === 'OK' && claimedLayer !== null,
    version: VERSION,
  });
}
