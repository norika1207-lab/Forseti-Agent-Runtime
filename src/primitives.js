/**
 * Forseti v2.0 — Failure Primitive Registry 與其餘 detector
 *
 * 規格來源:`docs/spec-v2.0.md` §21(registry)、§22.1、§22.5、§22.8、
 * §22.9、§22.12、§22.13、§22.14。
 * 對應 CT-005、CT-006、CT-010、CT-012、CT-013、CT-014、CT-015、CT-018、
 * CT-023、CT-038、CT-039。
 *
 * ── 這個檔案裡的十一個 detector 有一個共同形狀 ───────────
 *
 * 全部都是「某個東西被升到它沒有資格待的位置」:
 *
 *   FP-01 UCWE    UNKNOWN 被升成事實
 *   FP-05 EIC     相依的證據被升成獨立佐證
 *   FP-10 FAP     發現被升成成果
 *   FP-11 SPWG    寫好了被升成可用了
 *   FP-14 UCC     症狀被升成根因
 *   FP-15 UCE     一條限制被升成一整類限制
 *   FP-16 PCLOSE  一次失敗被升成不可行
 *   FP-18 MAS     別人的成果被升成自己的
 *   FP-19 SPI     樣本被升成母體
 *   FP-21 CAF     被更正過的東西還在驅動後續
 *   FP-22 INP     失效的計畫骨架還在主導策略
 *
 * §31 的控制律把這件事講成一句話:只要任何一條關係從 UNKNOWN 被無證據
 * 補成確定、從局部被升成整體、從 delegated 被洗成親驗、從 finding 被升成
 * achievement、從 activity 被升成 goal progress,都要留下可重播的證據。
 *
 * 所以這些 detector 全部是「比對兩個位置」,不是「判斷有沒有惡意」。
 *
 * 零依賴。
 */

export const VERSION = 'primitives@2.0';

/**
 * §21 的完整 registry。二十五個,一個不少。
 *
 * `implemented_in` 指向真正做這件事的模組。這一欄存在的理由跟
 * provenance.js 的 HANDLED_ELSEWHERE 一樣:「這裡沒有」跟
 * 「全系統都沒有」是兩件事,混在一起講就是這個系統自己要抓的東西。
 */
export const REGISTRY = Object.freeze([
  Object.freeze({ id: 'FP-01', code: 'UCWE', axis: 'Evidence', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-02', code: 'ESI', axis: 'Evidence', family: 'A', implemented_in: 'claims.js' }),
  Object.freeze({ id: 'FP-03', code: 'PC', axis: 'Evidence', family: 'B', implemented_in: 'claims.js' }),
  Object.freeze({ id: 'FP-04', code: 'VMI', axis: 'Verification', family: 'A', implemented_in: 'verifier.js' }),
  Object.freeze({ id: 'FP-05', code: 'EIC', axis: 'Evidence', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-06', code: 'SEF', axis: 'Integrity/Evidence', family: 'C', implemented_in: 'sef.js' }),
  Object.freeze({ id: 'FP-07', code: 'SCI', axis: 'Evidence', family: 'B', implemented_in: 'claims.js' }),
  Object.freeze({ id: 'FP-08', code: 'GMS', axis: 'Goal/Progress', family: 'B', implemented_in: 'progress.js' }),
  Object.freeze({ id: 'FP-09', code: 'GDA', axis: 'Goal', family: 'A', implemented_in: 'goalanchor.js' }),
  Object.freeze({ id: 'FP-10', code: 'FAP', axis: 'Progress', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-11', code: 'SPWG', axis: 'State', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-12', code: 'TOUA', axis: 'Progress', family: 'B', implemented_in: 'progress.js' }),
  Object.freeze({ id: 'FP-13', code: 'PV', axis: 'Verification', family: 'B', implemented_in: 'liveness.js' }),
  Object.freeze({ id: 'FP-14', code: 'UCC', axis: 'Evidence/Causal', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-15', code: 'UCE', axis: 'Goal/Authority', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-16', code: 'PCLOSE', axis: 'Planning', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-17', code: 'FSD', axis: 'Goal', family: 'A', implemented_in: 'goalanchor.js' }),
  Object.freeze({ id: 'FP-18', code: 'MAS', axis: 'Causal/Progress', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-19', code: 'SPI', axis: 'Measurement', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-20', code: 'SLF', axis: 'Runtime', family: 'B', implemented_in: 'liveness.js' }),
  Object.freeze({ id: 'FP-21', code: 'CAF', axis: 'Governance', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-22', code: 'INP', axis: 'Governance', family: 'A', implemented_in: 'primitives.js' }),
  Object.freeze({ id: 'FP-23', code: 'WSGO', axis: 'Product/Governance', family: 'A', implemented_in: 'incident.js' }),
  Object.freeze({ id: 'FP-24', code: 'PTN', axis: 'Commitment/Progress', family: 'B', implemented_in: 'progress.js' }),
  Object.freeze({ id: 'FP-25', code: 'FPR', axis: 'Integrity/Progress', family: 'B', implemented_in: 'progress.js' }),
]);

/**
 * FS-FP-001:每個 primitive detector 的回傳必須有這六個欄位。
 * 不得只回一句自然語言警告。
 */
export const REQUIRED_FIELDS = Object.freeze([
  'primitive_id', 'evidence_refs', 'confidence', 'scope', 'exclusions_checked',
  'root_incident_key',
]);

/**
 * 把一個 detector 的結果包成符合 FS-FP-001 的形狀。
 *
 * 這個函式存在的理由是:六個欄位很容易漏掉一兩個,而漏掉的通常是
 * exclusions_checked —— 也就是「我有沒有想過我可能錯了」那一欄。
 */
export function finding({
  primitiveId, verdict, evidenceRefs = [], confidence = null,
  scope = null, exclusionsChecked = [], rootIncidentKey = null, ...rest
} = {}) {
  if (!REGISTRY.some((p) => p.id === primitiveId)) {
    throw new TypeError(`Unknown primitive: ${String(primitiveId)}. See REGISTRY.`);
  }
  const meta = REGISTRY.find((p) => p.id === primitiveId);
  return Object.freeze({
    primitive_id: primitiveId,
    code: meta.code,
    verdict,
    evidence_refs: Object.freeze([...evidenceRefs]),
    confidence,
    scope,
    exclusions_checked: Object.freeze([...exclusionsChecked]),
    root_incident_key: rootIncidentKey,
    severity_family: meta.family,
    axis: meta.axis,
    ...rest,
    version: VERSION,
  });
}

// ---------------------------------------------------------------------------
// FP-01 UCWE — Uncertainty Collapse Without Evidence(§22.1)
// ---------------------------------------------------------------------------

/**
 * 一個 UNKNOWN 在沒有新證據的情況下,被一個後來的宣稱補成了確定值。
 *
 * CASE-B 的原案:transcript 沒有 speaker label,模型自行指派了說話者
 * (CT-005);一個 metadata 欄位被推成「大多數需要授權」(CT-006)。
 *
 * 排除條件照 §22.1 原文:owner 給了那個值;工具或 system-of-record
 * 給了那個值;agent 明講「推測/可能」而下游沒有把它升成事實。
 */
export function ucwe({
  unknownRef = null,
  unknownState = null,
  resolvingClaim = null,
  evidenceBetween = [],
  claimLabelledAsInference = false,
  downstreamPromotedToFact = true,
  suppliedByOwner = false,
  suppliedByTool = false,
} = {}) {
  const base = {
    primitiveId: 'FP-01',
    evidenceRefs: evidenceBetween.map((e) => e.id ?? null).filter(Boolean),
    scope: unknownRef,
    exclusionsChecked: ['owner_supplied', 'tool_supplied', 'labelled_as_inference'],
    rootIncidentKey: unknownRef ? `${unknownRef}:ucwe` : null,
  };

  if (suppliedByOwner || suppliedByTool) {
    return finding({
      ...base, verdict: 'RESOLVED_BY_SOURCE', confidence: 1, is_ucwe: false,
      note: suppliedByOwner
        ? 'The owner supplied the value. That is not a collapse, that is an answer.'
        : 'A tool or system-of-record supplied the value.',
    });
  }
  if (claimLabelledAsInference && !downstreamPromotedToFact) {
    return finding({
      ...base, verdict: 'LABELLED_INFERENCE', confidence: 1, is_ucwe: false,
      /** 明講是推測、下游也沒當成事實,這是正確行為,不是失效。 */
      note: 'The claim was explicitly labelled as inference and downstream state did not '
        + 'promote it to fact. Saying "probably" and being treated as "probably" is the '
        + 'system working.',
    });
  }
  if (!['UNKNOWN', 'AMBIGUOUS', 'MISSING'].includes(unknownState)) {
    return finding({
      ...base, verdict: 'NOT_APPLICABLE', confidence: null, is_ucwe: false,
      note: 'The prior state was not UNKNOWN/AMBIGUOUS/MISSING, so nothing collapsed.',
    });
  }

  // evidence_gain:這段期間有沒有取得足以支持那個結論的新證據。
  const relevant = evidenceBetween.filter((e) => e.supports === unknownRef);
  const evidenceGain = relevant.length;
  const isUcwe = evidenceGain === 0 && resolvingClaim !== null;

  return finding({
    ...base,
    verdict: isUcwe ? 'UNCERTAINTY_COLLAPSE_WITHOUT_EVIDENCE' : 'OK',
    confidence: isUcwe ? 1 : null,
    is_ucwe: isUcwe,
    ucwe_score: isUcwe ? 1 : 0,
    unknown_ref: unknownRef,
    resolving_claim_ref: resolvingClaim?.id ?? null,
    evidence_gain: evidenceGain,
    note: isUcwe
      ? 'An unknown became a stated fact with no new supporting evidence in between. '
        + 'The gap was filled from somewhere other than observation.'
      : null,
  });
}

// ---------------------------------------------------------------------------
// FP-05 EIC — Evidence Independence Collapse(§22.5)
// ---------------------------------------------------------------------------

/**
 * 兩份證據共用同一個決定性的上游來源或假設,卻被當成互相印證。
 *
 * FS-DET-EIC-001:「兩個 agent 都這樣說」不等於兩份獨立證據;
 * 如果 agent B 只讀 agent A 的輸出,independence 接近 0。
 *
 * CT-018 的原案就是這個。
 */
export function independence(e1, e2) {
  const up1 = new Set(e1?.upstream ?? []);
  const up2 = new Set(e2?.upstream ?? []);
  if (!up1.size || !up2.size) return null;      // 不知道上游就不能算獨立性

  const shared = [...up1].filter((u) => up2.has(u));
  const decisiveShared = shared.filter((u) =>
    (e1.decisive_upstream ?? []).includes(u) || (e2.decisive_upstream ?? []).includes(u));

  if (decisiveShared.length) return 0;
  if (!shared.length) return 1;
  return 1 - (shared.length / Math.max(up1.size, up2.size));
}

export function evidenceIndependenceCollapse({
  evidences = [],
  claimedAsCorroboration = false,
} = {}) {
  const base = {
    primitiveId: 'FP-05',
    evidenceRefs: evidences.map((e) => e.id ?? null).filter(Boolean),
    exclusionsChecked: ['upstream_declared', 'claimed_as_corroboration'],
  };
  if (evidences.length < 2) {
    return finding({ ...base, verdict: 'NOT_APPLICABLE', confidence: null, is_eic: false });
  }

  const pairs = [];
  for (let i = 0; i < evidences.length; i++) {
    for (let j = i + 1; j < evidences.length; j++) {
      pairs.push({
        a: evidences[i].id ?? i, b: evidences[j].id ?? j,
        independence: independence(evidences[i], evidences[j]),
      });
    }
  }
  const unknown = pairs.filter((p) => p.independence === null);
  const collapsed = pairs.filter((p) => p.independence === 0);

  if (unknown.length === pairs.length) {
    return finding({
      ...base, verdict: 'UPSTREAM_UNKNOWN', confidence: null, is_eic: false,
      pairs: Object.freeze(pairs),
      note: 'No upstream lineage declared for any evidence, so independence cannot be '
        + 'computed. Undeclared independence MUST NOT be assumed (FS-DET-EIC-001).',
    });
  }

  const isEic = collapsed.length > 0 && claimedAsCorroboration;
  return finding({
    ...base,
    verdict: isEic ? 'EVIDENCE_INDEPENDENCE_COLLAPSE' : 'OK',
    confidence: isEic ? 1 : null,
    is_eic: isEic,
    pairs: Object.freeze(pairs),
    collapsed_pairs: Object.freeze(collapsed),
    note: isEic
      ? 'Two pieces of evidence share a decisive upstream source and were presented as '
        + 'independent corroboration. Two agents reading the same thing is one observation, '
        + 'counted twice (FS-DET-EIC-001).'
      : null,
  });
}

// ---------------------------------------------------------------------------
// FP-10 FAP — Finding-to-Achievement Promotion(§22.8)
// ---------------------------------------------------------------------------

/** §22.8 的成果階梯。順序有意義,不可以跳級。 */
export const OUTCOME_STATES = Object.freeze([
  'OBSERVATION', 'FINDING', 'IMPLEMENTED_ARTIFACT', 'EXECUTED', 'VERIFIED_EFFECT', 'GOAL_OUTCOME',
]);

/**
 * FS-DET-FAP-001:找到 correlation/dim/pattern 只能停在 FINDING。
 * 沒有 intervention + effect measurement,不得升級為 product achievement。
 *
 * CASE-D 的原案:11 個 dims 的發現從未 prune 或 benchmark,卻被算成
 * Mercury 的進度(CT-012)。
 */
export function findingToAchievement({
  actualState = null,
  claimedState = null,
  hasIntervention = false,
  hasEffectMeasurement = false,
} = {}) {
  const base = {
    primitiveId: 'FP-10',
    exclusionsChecked: ['intervention_present', 'effect_measured'],
    scope: claimedState,
  };
  const ai = OUTCOME_STATES.indexOf(actualState);
  const ci = OUTCOME_STATES.indexOf(claimedState);
  if (ai < 0 || ci < 0) {
    return finding({
      ...base, verdict: 'INDETERMINATE', confidence: null, is_fap: false,
      note: 'Outcome state not on the ladder; cannot compare positions.',
    });
  }

  // 有介入且量了效果的話,可以往上走到 VERIFIED_EFFECT。
  const ceiling = (hasIntervention && hasEffectMeasurement)
    ? OUTCOME_STATES.indexOf('VERIFIED_EFFECT')
    : hasIntervention ? OUTCOME_STATES.indexOf('EXECUTED')
      : OUTCOME_STATES.indexOf('FINDING');

  const isFap = ci > Math.max(ai, ceiling);
  return finding({
    ...base,
    verdict: isFap ? 'FINDING_TO_ACHIEVEMENT_PROMOTION' : 'OK',
    confidence: isFap ? 1 : null,
    is_fap: isFap,
    actual_state: actualState,
    claimed_state: claimedState,
    highest_defensible_state: OUTCOME_STATES[Math.max(ai, Math.min(ceiling, ai))] ?? actualState,
    note: isFap
      ? `Claimed ${claimedState} while the evidence supports ${actualState}. A pattern found `
        + 'is not a problem solved: without an intervention and a measured effect, it stops '
        + 'at FINDING (FS-DET-FAP-001).'
      : null,
  });
}

// ---------------------------------------------------------------------------
// FP-11 SPWG — State Promotion Without Gate(§22.9)
// ---------------------------------------------------------------------------

/** §22.9 的狀態鏈。每一條 transition 都要有 gate receipt。 */
export const BUILD_STATES = Object.freeze([
  'PLANNED', 'WRITTEN', 'BUILT', 'TESTED', 'DEPLOYED', 'VERIFIED', 'RELEASABLE',
]);

/**
 * CASE-D 的原案:Tier-B patch `written, not built`,卻被當成進行中的
 * 可用功能(CT-013)。
 */
export function statePromotionWithoutGate({
  actualState = null,
  claimedState = null,
  gateReceipts = [],
} = {}) {
  const base = {
    primitiveId: 'FP-11',
    evidenceRefs: gateReceipts.map((g) => g.id ?? null).filter(Boolean),
    exclusionsChecked: ['gate_receipts_present'],
  };
  const ai = BUILD_STATES.indexOf(actualState);
  const ci = BUILD_STATES.indexOf(claimedState);
  if (ai < 0 || ci < 0) {
    return finding({
      ...base, verdict: 'INDETERMINATE', confidence: null, is_spwg: false,
    });
  }
  if (ci <= ai) {
    return finding({ ...base, verdict: 'OK', confidence: null, is_spwg: false });
  }

  // 從 actual 走到 claimed,中間每一步都要有對應的 gate receipt。
  const needed = BUILD_STATES.slice(ai + 1, ci + 1);
  const have = new Set(gateReceipts.map((g) => g.reaches));
  const missing = needed.filter((s) => !have.has(s));

  return finding({
    ...base,
    verdict: missing.length ? 'STATE_PROMOTION_WITHOUT_GATE' : 'OK',
    confidence: missing.length ? 1 : null,
    is_spwg: missing.length > 0,
    actual_state: actualState,
    claimed_state: claimedState,
    missing_gates: Object.freeze(missing),
    /** CT-013:沒有 build gate 的話,狀態必須明確標成 WRITTEN_NOT_BUILT。 */
    required_label: missing.length ? `${actualState}_NOT_${missing[0]}` : null,
    note: missing.length
      ? `Claimed ${claimedState} without gate receipts for ${missing.join(', ')}.`
      : null,
  });
}

// ---------------------------------------------------------------------------
// FP-14 UCC — Unsupported Causal Completion(§22.12)
// ---------------------------------------------------------------------------

/**
 * 從症狀 A 直接跳到原因 C,中間的 causal edge 沒有 verifier。
 *
 * CASE-B 的原案:quick_check 自己鎖了 DB,卻被補成「DB 毀了」。
 * §22.12 特別點名:「DB 被毀」「系統壞了」「另一台機器」這類 root-cause
 * claim 必須有對應的 system-of-record 證據。
 */
export function unsupportedCausalCompletion({
  symptom = null,
  claimedCause = null,
  causalChain = [],
  labelledAsHypothesis = false,
} = {}) {
  const base = {
    primitiveId: 'FP-14',
    evidenceRefs: causalChain.map((c) => c.verifier_ref ?? null).filter(Boolean),
    exclusionsChecked: ['labelled_as_hypothesis', 'verifier_present_on_each_edge'],
    scope: claimedCause,
  };
  if (labelledAsHypothesis) {
    return finding({
      ...base, verdict: 'LABELLED_HYPOTHESIS', confidence: 1, is_ucc: false,
      note: 'Stated as a hypothesis. That is the correct state for an unverified cause.',
    });
  }
  if (!claimedCause) {
    return finding({ ...base, verdict: 'NOT_APPLICABLE', confidence: null, is_ucc: false });
  }

  const unverifiedEdges = causalChain.filter((e) => !e.verifier_ref);
  const isUcc = causalChain.length === 0 || unverifiedEdges.length > 0;

  return finding({
    ...base,
    verdict: isUcc ? 'UNSUPPORTED_CAUSAL_COMPLETION' : 'OK',
    confidence: isUcc ? 1 : null,
    is_ucc: isUcc,
    symptom,
    claimed_cause: claimedCause,
    unverified_edges: Object.freeze(unverifiedEdges.map((e) => e.from + '->' + e.to)),
    /** 沒有 verifier 的話,C 只能是 HYPOTHESIS。 */
    highest_allowed_state: isUcc ? 'HYPOTHESIS' : 'CONFIRMED_CAUSE',
    note: isUcc
      ? (causalChain.length === 0
        ? 'A cause was stated with no causal chain at all between symptom and conclusion.'
        : `${unverifiedEdges.length} causal edge(s) have no verifier. Without one, the cause `
          + 'can only be a hypothesis (§22.12).')
      : null,
  });
}

// ---------------------------------------------------------------------------
// FP-15 UCE — Unauthorized Constraint Expansion(§22.13)
// ---------------------------------------------------------------------------

/**
 * owner 的限制被擴張成更廣的禁止,改變了解法空間。
 *
 * §22.13 的原例,逐字:
 *   Owner constraint: "do not use Claude API"
 *   Invalid expansion: "therefore no image generation of any kind"
 *
 * CT-010。這一條的實務代價很具體:被擴張的限制會讓一整類做得到的事
 * 從選項裡消失,而 owner 從來沒有禁止過那些。
 */
export function unauthorizedConstraintExpansion({
  ownerConstraints = [],
  appliedConstraint = null,
} = {}) {
  const base = {
    primitiveId: 'FP-15',
    exclusionsChecked: ['owner_provenance_present'],
    scope: appliedConstraint?.id ?? null,
  };
  if (!appliedConstraint) {
    return finding({ ...base, verdict: 'NOT_APPLICABLE', confidence: null, is_uce: false });
  }

  const source = ownerConstraints.find((c) => c.id === appliedConstraint.derived_from);
  if (!appliedConstraint.derived_from) {
    return finding({
      ...base, verdict: 'MODEL_DERIVED_CONSTRAINT', confidence: 1, is_uce: true,
      applied_constraint: appliedConstraint.text ?? null,
      /** 沒有 owner provenance 又縮小了解法空間,標成模型自訂,不得當硬限制。 */
      may_hard_authorize_plan: false,
      note: 'This constraint has no owner provenance. It may be recorded as '
        + 'MODEL_DERIVED_CONSTRAINT but MUST NOT hard-authorize a plan (§22.13).',
    });
  }
  if (!source) {
    return finding({
      ...base, verdict: 'SOURCE_NOT_FOUND', confidence: null, is_uce: false,
      note: 'The claimed source constraint is not in the owner constraint list.',
    });
  }

  const ownerScope = new Set(source.scope ?? []);
  const appliedScope = appliedConstraint.scope ?? [];
  const expanded = appliedScope.filter((s) => !ownerScope.has(s));

  return finding({
    ...base,
    verdict: expanded.length ? 'UNAUTHORIZED_CONSTRAINT_EXPANSION' : 'OK',
    confidence: expanded.length ? 1 : null,
    is_uce: expanded.length > 0,
    owner_constraint: source.text ?? null,
    applied_constraint: appliedConstraint.text ?? null,
    expanded_scope: Object.freeze(expanded),
    may_hard_authorize_plan: expanded.length === 0,
    note: expanded.length
      ? `The owner constrained ${[...ownerScope].join(', ')}; this was applied to `
        + `${expanded.join(', ')} as well. The extra scope removes options the owner never `
        + 'ruled out.'
      : null,
  });
}

// ---------------------------------------------------------------------------
// FP-16 PCLOSE — Premature Closure
// ---------------------------------------------------------------------------

/**
 * 一次失敗或弱證據被推成「不可行/壞掉/沒有路」。
 *
 * CASE-D 的原案:ssh key 一次失敗就宣告 GX10 不通。
 */
export function prematureClosure({
  attempts = [],
  conclusion = null,
  conclusionScope = 'GLOBAL',
  alternativesConsidered = [],
} = {}) {
  const base = {
    primitiveId: 'FP-16',
    evidenceRefs: attempts.map((a) => a.id ?? null).filter(Boolean),
    exclusionsChecked: ['alternatives_considered', 'conclusion_scope_local'],
    scope: conclusionScope,
  };
  if (!conclusion) {
    return finding({ ...base, verdict: 'NOT_APPLICABLE', confidence: null, is_pclose: false });
  }

  const distinctApproaches = new Set(attempts.map((a) => a.approach ?? 'unknown')).size;
  const isPclose = conclusionScope === 'GLOBAL'
    && distinctApproaches <= 1
    && alternativesConsidered.length === 0;

  return finding({
    ...base,
    verdict: isPclose ? 'PREMATURE_CLOSURE' : 'OK',
    confidence: isPclose ? 1 : null,
    is_pclose: isPclose,
    attempt_count: attempts.length,
    distinct_approaches: distinctApproaches,
    conclusion,
    note: isPclose
      ? `A global conclusion ("${conclusion}") was drawn from ${attempts.length} attempt(s) `
        + `using ${distinctApproaches} approach, with no alternatives considered. One failed `
        + 'attempt is not impossibility (§29).'
      : null,
  });
}

// ---------------------------------------------------------------------------
// FP-18 MAS — Mechanism Attribution Substitution
// ---------------------------------------------------------------------------

/**
 * 別的機制、別的軟體、快取或 orchestrator 的成果,被敘述成
 * model/project 本身的成果。
 *
 * CASE-D 的原案:Mercury 1.15x 失敗之後,改用 Ollama 的 GPU 速度
 * 銜接敘述(CT-015)。
 */
export function mechanismAttributionSubstitution({
  claimedMechanism = null,
  actualMechanism = null,
  metricRef = null,
} = {}) {
  const base = {
    primitiveId: 'FP-18',
    evidenceRefs: metricRef ? [metricRef] : [],
    exclusionsChecked: ['actual_mechanism_declared'],
    scope: metricRef,
  };
  if (actualMechanism === null) {
    return finding({
      ...base, verdict: 'MECHANISM_UNKNOWN', confidence: null, is_mas: false,
      note: 'The mechanism behind the number was not recorded, so attribution cannot be '
        + 'checked. Record it at measurement time, not afterwards.',
    });
  }
  const isMas = claimedMechanism !== null && claimedMechanism !== actualMechanism;
  return finding({
    ...base,
    verdict: isMas ? 'MECHANISM_ATTRIBUTION_SUBSTITUTION' : 'OK',
    confidence: isMas ? 1 : null,
    is_mas: isMas,
    claimed_mechanism: claimedMechanism,
    actual_mechanism: actualMechanism,
    note: isMas
      ? `The result came from ${actualMechanism} but was narrated as ${claimedMechanism}. `
        + 'Another system\'s performance is not this project\'s progress.'
      : null,
  });
}

// ---------------------------------------------------------------------------
// FP-19 SPI — Sampling-to-Population Inflation(§22.14)
// ---------------------------------------------------------------------------

/**
 * §22.14:任何 population claim 必須連 sampling contract ——
 * sample frame、method、n、selection rule。極端樣本只能講
 * 「worst-case examples」,不能推「大部分」。
 *
 * CASE-F 的原案:挑最糟的三個樣本推整體(CT-023)。
 */
export const POPULATION_TERMS = Object.freeze([
  '大部分', '多數', '大多', '普遍', '整體', '幾乎都', '通常',
  'most', 'majority', 'generally', 'typically', 'overall', 'in general',
]);

export function samplingToPopulationInflation({
  claimText = '',
  samplingContract = null,
} = {}) {
  const base = {
    primitiveId: 'FP-19',
    exclusionsChecked: ['sampling_contract_present', 'selection_rule_random'],
  };
  const populationTerms = POPULATION_TERMS.filter((term) => {
    const re = new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    return re.test(String(claimText));
  });
  if (!populationTerms.length) {
    return finding({ ...base, verdict: 'OK', confidence: null, is_spi: false });
  }

  if (!samplingContract) {
    return finding({
      ...base, verdict: 'SAMPLING_TO_POPULATION_INFLATION', confidence: 1, is_spi: true,
      population_terms: Object.freeze(populationTerms),
      /** 沒有抽樣契約的母體宣稱,不得成立。 */
      population_claim_allowed: false,
      note: 'A population claim was made with no sampling contract (frame, method, n, '
        + 'selection rule). Without it the claim cannot be evaluated at all (§22.14).',
    });
  }

  const missing = ['frame', 'method', 'n', 'selection_rule']
    .filter((f) => samplingContract[f] === undefined || samplingContract[f] === null);
  const extremeSelection = /extreme|worst|top|最糟|最差|最高/i
    .test(String(samplingContract.selection_rule ?? ''));

  const isSpi = missing.length > 0 || extremeSelection;
  return finding({
    ...base,
    verdict: isSpi ? 'SAMPLING_TO_POPULATION_INFLATION' : 'OK',
    confidence: isSpi ? 1 : null,
    is_spi: isSpi,
    population_terms: Object.freeze(populationTerms),
    missing_contract_fields: Object.freeze(missing),
    extreme_selection: extremeSelection,
    population_claim_allowed: !isSpi,
    /** 極端樣本可以講的話只有一句:這些是最糟的例子。 */
    allowed_phrasing: extremeSelection ? 'worst-case examples' : null,
    note: extremeSelection
      ? 'The sample was selected for extremes. It supports "worst-case examples" and '
        + 'nothing about the majority (§22.14).'
      : missing.length ? `Sampling contract missing: ${missing.join(', ')}.` : null,
  });
}

// ---------------------------------------------------------------------------
// FP-21 CAF / FP-22 INP — Governance
// ---------------------------------------------------------------------------

/**
 * FP-21 Correction Absorption Failure。
 *
 * owner 已經更正過了,而後續的 action/plan 仍然沿用被更正掉的狀態。
 * CT-038。
 */
export function correctionAbsorptionFailure({
  corrections = [],
  subsequentActions = [],
} = {}) {
  const base = {
    primitiveId: 'FP-21',
    evidenceRefs: corrections.map((c) => c.id ?? null).filter(Boolean),
    exclusionsChecked: ['action_predates_correction', 'correction_acknowledged'],
  };
  const violations = [];
  for (const corr of corrections) {
    for (const act of subsequentActions) {
      if ((act.at ?? 0) <= (corr.at ?? 0)) continue;       // 更正之前的動作不算
      if ((act.depends_on ?? []).includes(corr.invalidates)) {
        violations.push({ correction: corr.id ?? null, action: act.id ?? null, stale: corr.invalidates });
      }
    }
  }
  return finding({
    ...base,
    verdict: violations.length ? 'CORRECTION_ABSORPTION_FAILURE' : 'OK',
    confidence: violations.length ? 1 : null,
    is_caf: violations.length > 0,
    violations: Object.freeze(violations.map((v) => Object.freeze(v))),
    note: violations.length
      ? `${violations.length} action(s) after a correction still depend on what the `
        + 'correction invalidated. The correction was received but not absorbed.'
      : null,
  });
}

/**
 * FP-22 Invalidated Narrative Persistence。
 *
 * 核心 prerequisite 或 hypothesis 失效之後,舊的 plan skeleton 仍然
 * 主導後續策略。CT-039。
 *
 * 跟 FP-21 的差別:FP-21 是「某個動作用了過期的東西」,
 * FP-22 是「整個計畫骨架已經失效,而大家還在補丁它」。
 */
export function invalidatedNarrativePersistence({
  planNodes = [],
  invalidatedPrerequisites = [],
  patchesAfterInvalidation = 0,
} = {}) {
  const base = {
    primitiveId: 'FP-22',
    exclusionsChecked: ['plan_replanned_after_invalidation'],
  };
  const dependent = planNodes.filter((n) =>
    (n.depends_on ?? []).some((d) => invalidatedPrerequisites.includes(d)));
  const stillActive = dependent.filter((n) => n.status === 'ACTIVE');

  const isInp = stillActive.length > 0;
  return finding({
    ...base,
    verdict: isInp ? 'INVALIDATED_NARRATIVE_PERSISTENCE' : 'OK',
    confidence: isInp ? 1 : null,
    is_inp: isInp,
    invalidated_prerequisites: Object.freeze([...invalidatedPrerequisites]),
    still_active_dependent_nodes: Object.freeze(stillActive.map((n) => n.id ?? null)),
    patches_after_invalidation: patchesAfterInvalidation,
    /** FS-MET-PA-001:核心前提失效時,依賴它的計畫節點必須失去 active authority。 */
    must_lose_authority: Object.freeze(stillActive.map((n) => n.id ?? null)),
    note: isInp
      ? `${stillActive.length} plan node(s) still hold active authority while the `
        + 'prerequisite they depend on is invalidated'
        + (patchesAfterInvalidation > 0
          ? `, and the skeleton has been patched ${patchesAfterInvalidation} time(s) since.`
          : '.')
      : null,
  });
}
