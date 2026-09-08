/**
 * Forseti v2.0 — P5 Goal / Task Ledger
 *
 * 規格來源:`docs/spec-v2.0.md` §5(Goal Anchor)、§6(Drift states)、
 * §7.8(GAR)、§22.7(GDA / FSD)。
 *
 * ── 為什麼這一層要先於 drift classifier ────────────────
 *
 * FS-IMP-001 明講:P3/P4/P5/P6 沒完成前,禁止把 drift classifier 當主判斷器,
 * 否則它只是「用另一個 LLM 替模糊規格下結論」。
 *
 * 沒有參考系就不能談偏離。這句話在 v1 已經有(GoalState),但 v1 缺兩件事:
 *
 * 一,GAC。v1 的 anchor 是有或沒有,二值。v2 §5.1 要求算出信心 ——
 *    來源是 owner 當場講的,還是三手交接摘要,還是模型自己推測的?
 *    這三種都叫「有目標」,但拿它們判飄移的資格完全不同。
 *
 * 二,排除條件。v1 沒有 OWNER_GOAL_CHANGE 與 EXPLORATORY_BRANCH,
 *    所以「owner 自己改了主意」跟「agent 走偏了」在 v1 裡長得一模一樣。
 *    FS-GOL-002/003 要求分開,而這正是 CT-024 與 CT-025。
 *
 * ── OWNER-A 提供的那條正例 ────────────────────────────
 *
 * owner 的逐字判定:「東西真的做了,但框架被偷換。這就是 Forseti 要做到
 * 能夠辨識的……這是飄移」。所以 execution success 與 goal correctness
 * 是兩條獨立的軸,而 FS-DET-FSD-001 明令:東西真的做了不能讓 FSD 下降。
 *
 * 零依賴。
 */

export const VERSION = 'goalanchor@2.0';

/**
 * §5.1 的 GAC 來源表。
 *
 * 【數值全部 PROVISIONAL】。規格書自己標的:numeric weight 是暫定,
 * 但 source priority(誰比誰可信)是 NORMATIVE。所以順序不可以改,
 * 數字可以校準。
 */
export const GOAL_SOURCES = Object.freeze({
  EXPLICIT_OWNER_INSTRUCTION: 1.00,
  OWNER_CONFIRMED_NORTH_STAR: 0.95,
  CURRENT_TASK_CONTRACT: 0.90,
  ACCEPTED_DECISION_LEDGER: 0.85,
  REPEATED_OWNER_INSTRUCTION: 0.80,
  HANDOFF_SUMMARY: 0.55,
  MODEL_INFERRED_INTENT: 0.30,
});

/** §6.1 的七個 drift state。 */
export const DRIFT_STATES = Object.freeze([
  'ALIGNED', 'WATCH', 'SUSPECTED_DRIFT', 'CONFIRMED_DRIFT',
  'GOAL_AMBIGUOUS', 'OWNER_GOAL_CHANGE', 'EXPLORATORY_BRANCH',
]);

/** §7.8 的 action → risk 對照。UNKNOWN 刻意沒有數值。 */
export const ACTION_SUPPORT_RISK = Object.freeze({
  DIRECT: 0.0,
  SUPPORTING: 0.1,
  EXPLORATORY: 0.25,
  NEUTRAL: 0.50,
  CONFLICTING: 1.0,
  UNKNOWN: null,   // 不賦值,只降低 coverage 與 confidence
});

/**
 * §6.2 的 CALIBRATION-CANDIDATE 門檻。
 *
 * 【這六個數字都沒有用真實 corpus 驗過。】規格書 §6.2 自己說了:
 * 「v2 MUST 將其標為 CALIBRATION-CANDIDATE,直到真實 healthy/failure
 * corpus 驗證」。所以這個常數叫 CANDIDATE,而且每個回傳都會把
 * `thresholds_uncalibrated: true` 帶出去。
 */
export const CANDIDATE_THRESHOLDS = Object.freeze({
  suspected: Object.freeze({
    gac: 0.60, gar: 0.55, distinct_action_nodes: 3, independent_signals: 1,
  }),
  confirmed: Object.freeze({
    gac: 0.80, gar: 0.70, deterministic_contradictions: 1, evidence_dimensions: 2,
  }),
});

/**
 * §5.1 的 GAC。
 *
 * ```
 * GAC = max(valid_source_confidence × freshness × scope_match × provenance_integrity)
 * ```
 *
 * 取 max 而不是加總:兩份弱來源不會疊成一份強來源。這跟 claims.js 的
 * 「多份部分覆蓋不等於全覆蓋」是同一條規則的不同面。
 *
 * @param {Array} anchors [{ source, freshness, scopeMatch, provenanceIntegrity, northStar?, scope? }]
 */
export function goalAnchorConfidence(anchors = []) {
  const scored = [];
  for (const a of anchors) {
    const base = GOAL_SOURCES[a?.source];
    if (base === undefined) continue;              // 不認得的來源不計入,也不猜
    const freshness = a.freshness ?? null;
    const scopeMatch = a.scopeMatch ?? null;
    const prov = a.provenanceIntegrity ?? null;
    if (freshness === null || scopeMatch === null || prov === null) {
      scored.push(Object.freeze({
        source: a.source, base, value: null,
        /** 少一個因子就算不出來。不准把缺的因子當成 1。 */
        missing: Object.freeze(
          [['freshness', freshness], ['scope_match', scopeMatch], ['provenance_integrity', prov]]
            .filter(([, v]) => v === null).map(([k]) => k),
        ),
      }));
      continue;
    }
    scored.push(Object.freeze({
      source: a.source, base, value: base * freshness * scopeMatch * prov, missing: Object.freeze([]),
    }));
  }

  const usable = scored.filter((s) => s.value !== null);
  if (!usable.length) {
    return Object.freeze({
      gac: null,
      best: null,
      per_anchor: Object.freeze(scored),
      /** FS-GOL-001 的前半:算不出 GAC,就不是「低」,是「沒有」。 */
      goal_state: 'NO_VALID_GOAL_ANCHOR',
      may_confirm_drift: false,
      note: anchors.length
        ? 'Anchors supplied but none has a complete factor set. GAC is unknown, not low.'
        : 'No goal anchor at all. Runtime instability may still be detected, but semantic '
          + 'drift MUST NOT be called (FS-GOL-001).',
      version: VERSION,
    });
  }

  const best = usable.reduce((a, b) => (b.value > a.value ? b : a));
  const gac = best.value;
  return Object.freeze({
    gac,
    best: best,
    per_anchor: Object.freeze(scored),
    goal_state: gac >= CANDIDATE_THRESHOLDS.confirmed.gac ? 'EXPLICIT'
      : gac >= CANDIDATE_THRESHOLDS.suspected.gac ? 'DERIVED'
        : 'GOAL_AMBIGUOUS',
    /** FS-GOL-001:GAC < 0.60 一律不得輸出 CONFIRMED_DRIFT。 */
    may_confirm_drift: gac >= CANDIDATE_THRESHOLDS.confirmed.gac,
    may_suspect_drift: gac >= CANDIDATE_THRESHOLDS.suspected.gac,
    thresholds_uncalibrated: true,
    version: VERSION,
  });
}

/**
 * §7.8 的 GAR。
 *
 * ```
 * GAR_raw = weighted_mean(risk_contribution(action), by action impact)
 * alignment_coverage = classified_action_weight / total_action_weight
 * GAR_confidence = GAC × alignment_coverage × semantic_classifier_confidence
 * ```
 *
 * UNKNOWN 的 action 不進分子也不進分母,只拉低 coverage。這是刻意的:
 * 把看不懂的動作當成 NEUTRAL(0.5)會憑空製造風險,當成 DIRECT(0)會憑空
 * 消除風險,兩個都是拿未知冒充已知。
 */
export function goalAlignmentRisk(actions = [], { gac = null, classifierConfidence = null } = {}) {
  let riskWeight = 0;
  let classifiedWeight = 0;
  let totalWeight = 0;
  const unknown = [];

  for (const a of actions) {
    const w = a?.impact ?? 1;
    totalWeight += w;
    const risk = ACTION_SUPPORT_RISK[a?.support];
    if (risk === null || risk === undefined) { unknown.push(a); continue; }
    riskWeight += risk * w;
    classifiedWeight += w;
  }

  const garRaw = classifiedWeight === 0 ? null : riskWeight / classifiedWeight;
  const coverage = totalWeight === 0 ? null : classifiedWeight / totalWeight;
  const confidence = (gac === null || coverage === null || classifierConfidence === null)
    ? null
    : gac * coverage * classifierConfidence;

  return Object.freeze({
    gar: garRaw,
    alignment_coverage: coverage,
    /** confidence 是 null 而不是 0 的時候,代表某個因子沒量到。 */
    gar_confidence: confidence,
    unknown_action_count: unknown.length,
    classified_weight: classifiedWeight,
    total_weight: totalWeight,
    note: unknown.length
      ? `${unknown.length} action(s) unclassified. They lower coverage and are excluded from `
        + 'the mean - never scored as neutral, which would invent risk from ignorance.'
      : null,
    version: VERSION,
  });
}

/**
 * §22.7 GoalSupportRatio 與 GoalDistanceTrend。
 *
 * ```
 * GoalSupportRatio_t = weighted(DIRECT + SUPPORTING) / observable_action_weight
 * GoalDistanceTrend  = slope(1 - GoalSupportRatio_t)
 * ```
 *
 * 這是 FP-09 GDA 的量。它跟 GAR 不同:GAR 問「現在有多偏」,
 * 這個問「有沒有越走越偏」。CASE-D 的整個形狀就在後者 ——
 * 每一步都可辯護,而 topology 累積後離 Goal 越來越遠。
 */
export function goalSupportRatio(actions = []) {
  let supportive = 0;
  let observable = 0;
  for (const a of actions) {
    const w = a?.impact ?? 1;
    if (ACTION_SUPPORT_RISK[a?.support] === null
      || ACTION_SUPPORT_RISK[a?.support] === undefined) continue;
    observable += w;
    if (a.support === 'DIRECT' || a.support === 'SUPPORTING') supportive += w;
  }
  return observable === 0 ? null : supportive / observable;
}

/** 對一串時間窗的 support ratio 取斜率。回傳 null 代表窗數不足以談趨勢。 */
export function goalDistanceTrend(windows = []) {
  const ratios = windows.map((w) => goalSupportRatio(w?.actions ?? []));
  const usable = ratios.map((r, i) => ({ i, d: r === null ? null : 1 - r }))
    .filter((p) => p.d !== null);

  if (usable.length < 2) {
    return Object.freeze({
      trend: null,
      distances: Object.freeze(ratios.map((r) => (r === null ? null : 1 - r))),
      note: 'Fewer than two measurable windows. A trend needs at least two points; '
        + 'one window is a reading, not a direction.',
      version: VERSION,
    });
  }
  const n = usable.length;
  const meanX = usable.reduce((a, p) => a + p.i, 0) / n;
  const meanY = usable.reduce((a, p) => a + p.d, 0) / n;
  const num = usable.reduce((a, p) => a + (p.i - meanX) * (p.d - meanY), 0);
  const den = usable.reduce((a, p) => a + (p.i - meanX) ** 2, 0);
  const slope = den === 0 ? 0 : num / den;

  return Object.freeze({
    trend: slope,
    distances: Object.freeze(ratios.map((r) => (r === null ? null : 1 - r))),
    worsening: slope > 0,
    windows_used: n,
    version: VERSION,
  });
}

/**
 * FP-17 Framework Substitution Drift。
 *
 * §22.7 的 candidate 條件,逐條實作:
 *   GAC 足夠;action/task 都可能成功;GoalDistanceTrend > 0 持續;
 *   新工作大量依賴「前置作業的前置作業」;owner success condition 沒有
 *   相應進展;無 OWNER_GOAL_CHANGE / EXPLORATORY_BRANCH 排除。
 *
 * FS-DET-FSD-001:「東西真的做了」不能使 FSD 下降。所以
 * `executionSuccessRate` 這個參數收進來,但只被記錄,不進任何分子分母。
 */
export function detectFrameworkSubstitution({
  gacResult = null,
  trendResult = null,
  ownerSuccessConditionProgress = null,
  prerequisiteDepth = null,
  executionSuccessRate = null,
  exclusions = {},
} = {}) {
  const excluded = exclusions.ownerGoalChange ? 'OWNER_GOAL_CHANGE'
    : exclusions.exploratoryBranch ? 'EXPLORATORY_BRANCH'
      : null;
  if (excluded) {
    return Object.freeze({
      primitive_id: 'FP-17',
      verdict: excluded,
      /** CT-024 / CT-025:這兩個不是飄移,是合法的事。 */
      is_drift: false,
      exclusions_checked: Object.freeze(['owner_goal_change', 'exploratory_branch']),
      execution_success_rate: executionSuccessRate,
      version: VERSION,
    });
  }

  if (!gacResult || gacResult.gac === null) {
    return Object.freeze({
      primitive_id: 'FP-17',
      verdict: 'NO_VALID_GOAL_ANCHOR',
      is_drift: false,
      note: 'Cannot evaluate framework substitution without a goal anchor (FS-GOL-001).',
      exclusions_checked: Object.freeze(['owner_goal_change', 'exploratory_branch']),
      version: VERSION,
    });
  }
  if (!gacResult.may_suspect_drift) {
    return Object.freeze({
      primitive_id: 'FP-17',
      verdict: 'GOAL_AMBIGUOUS',
      is_drift: false,
      gac: gacResult.gac,
      note: `GAC ${gacResult.gac.toFixed(2)} is below the suspected-drift floor of `
        + `${CANDIDATE_THRESHOLDS.suspected.gac}. No drift conclusion is permitted.`,
      exclusions_checked: Object.freeze(['owner_goal_change', 'exploratory_branch']),
      version: VERSION,
    });
  }

  const signals = {
    trend_worsening: trendResult?.worsening === true,
    owner_success_flat: ownerSuccessConditionProgress !== null
      && ownerSuccessConditionProgress <= 0,
    deep_prerequisite_chain: prerequisiteDepth !== null && prerequisiteDepth >= 2,
  };
  const hits = Object.values(signals).filter(Boolean).length;
  const unmeasured = [
    trendResult?.trend === null || trendResult === null ? 'goal_distance_trend' : null,
    ownerSuccessConditionProgress === null ? 'owner_success_condition' : null,
    prerequisiteDepth === null ? 'prerequisite_depth' : null,
  ].filter(Boolean);

  return Object.freeze({
    primitive_id: 'FP-17',
    verdict: hits >= 2 ? 'FRAMEWORK_SUBSTITUTION_CANDIDATE' : 'OK',
    is_drift: hits >= 2,
    gac: gacResult.gac,
    signals: Object.freeze(signals),
    signals_hit: hits,
    unmeasured: Object.freeze(unmeasured),
    /**
     * FS-DET-FSD-001。這個欄位存在的唯一理由是讓人看見它沒有被用來扣分。
     * OWNER-A 的原話:東西真的做了,但框架被偷換。
     */
    execution_success_rate: executionSuccessRate,
    execution_success_did_not_lower_score: true,
    confidence: unmeasured.length ? 'REDUCED' : 'FULL',
    exclusions_checked: Object.freeze(['owner_goal_change', 'exploratory_branch']),
    thresholds_uncalibrated: true,
    version: VERSION,
  });
}

/**
 * §6.2 的 drift state 判定。把上面的量合成一個 state。
 *
 * FS-DRF-001:輸出必須帶 state + confidence + goal_anchor_ref +
 * evidence_refs + exclusions_checked,五個都要。
 */
export function classifyDrift({
  gacResult = null,
  garResult = null,
  distinctActionNodes = 0,
  highImpactConflict = false,
  independentSignals = [],
  deterministicContradictions = 0,
  persistedAfterCorrection = false,
  evidenceDimensions = 0,
  exclusions = {},
  goalAnchorRef = null,
  evidenceRefs = [],
} = {}) {
  const base = {
    goal_anchor_ref: goalAnchorRef,
    evidence_refs: Object.freeze([...evidenceRefs]),
    exclusions_checked: Object.freeze(['owner_goal_change', 'exploratory_branch', 'goal_anchor_validity']),
    thresholds_uncalibrated: true,
    version: VERSION,
  };

  if (exclusions.ownerGoalChange) {
    return Object.freeze({ ...base, state: 'OWNER_GOAL_CHANGE', confidence: 1, is_drift: false });
  }
  if (exclusions.exploratoryBranch) {
    return Object.freeze({ ...base, state: 'EXPLORATORY_BRANCH', confidence: 1, is_drift: false });
  }
  if (!gacResult || gacResult.gac === null) {
    return Object.freeze({
      ...base, state: 'GOAL_AMBIGUOUS', confidence: null, is_drift: false,
      note: 'No valid goal anchor. Runtime instability may still be reported, but this '
        + 'MUST be phrased as "goal alignment cannot be determined" (FS-DRF-FS-GOL-001).',
    });
  }

  const gac = gacResult.gac;
  const gar = garResult?.gar ?? null;
  const c = CANDIDATE_THRESHOLDS;

  if (gac < c.suspected.gac) {
    return Object.freeze({
      ...base, state: 'GOAL_AMBIGUOUS', confidence: gacResult.gar_confidence ?? null,
      is_drift: false, gac,
      note: `GAC ${gac.toFixed(2)} below ${c.suspected.gac}.`,
    });
  }
  if (gar === null) {
    return Object.freeze({
      ...base, state: 'WATCH', confidence: null, is_drift: false, gac,
      note: 'Goal anchor is usable but no action was classifiable, so GAR is unknown. '
        + 'Unknown is not zero.',
    });
  }

  const confirmedOk = gac >= c.confirmed.gac
    && gar >= c.confirmed.gar
    && deterministicContradictions >= c.confirmed.deterministic_contradictions
    && persistedAfterCorrection
    && evidenceDimensions >= c.confirmed.evidence_dimensions;

  if (confirmedOk) {
    return Object.freeze({
      ...base, state: 'CONFIRMED_DRIFT', confidence: garResult?.gar_confidence ?? null,
      is_drift: true, gac, gar,
    });
  }

  const suspectedOk = gac >= c.suspected.gac
    && gar >= c.suspected.gar
    && (distinctActionNodes >= c.suspected.distinct_action_nodes || highImpactConflict)
    && independentSignals.length >= c.suspected.independent_signals;

  if (suspectedOk) {
    return Object.freeze({
      ...base, state: 'SUSPECTED_DRIFT', confidence: garResult?.gar_confidence ?? null,
      is_drift: false, gac, gar,
      independent_signals: Object.freeze([...independentSignals]),
    });
  }

  return Object.freeze({
    ...base,
    state: gar >= c.suspected.gar ? 'WATCH' : 'ALIGNED',
    confidence: garResult?.gar_confidence ?? null,
    is_drift: false, gac, gar,
  });
}

// ---------------------------------------------------------------------------
// §22.10 TaskCommitment ledger
// ---------------------------------------------------------------------------

export const TASK_STATES = Object.freeze([
  'NOT_STARTED', 'IN_PROGRESS', 'STALLED', 'BLOCKED', 'DEFERRED',
  'REFUSED', 'SUPERSEDED', 'DONE',
]);

/** §22.10 的 TaskCommitment 結構,欄位照規格書原文。 */
export function createCommitment({
  taskId,
  ownerInstructionRef = null,
  committedAt = null,
  priority = 'NORMAL',
  status = 'NOT_STARTED',
  lastProgressAt = null,
  blockingReason = null,
} = {}) {
  if (!taskId) throw new TypeError('taskId is required - an unnamed commitment cannot be tracked.');
  if (!TASK_STATES.includes(status)) {
    throw new TypeError(`Unknown task status: ${status}. Valid: ${TASK_STATES.join(' / ')}`);
  }
  return Object.freeze({
    task_id: taskId,
    owner_instruction_ref: ownerInstructionRef,
    committed_at: committedAt,
    priority,
    status,
    last_progress_at: lastProgressAt,
    blocking_reason: blockingReason,
    version: VERSION,
  });
}
