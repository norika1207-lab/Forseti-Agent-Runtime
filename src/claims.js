/**
 * Forseti v2.0 — P3 Claim & Scope Engine
 *
 * 規格來源:`docs/spec-v2.0.md` §22.2(FP-02 ESI)、§22.3(FP-03 PC)、
 * §22.19(Post-Claim Integrity Gate)、§23.2、§23.3。
 *
 * ── 這個模組的一句話 ─────────────────────────────────
 *
 * 一個宣稱有多大,跟支持它的證據有多大,是兩件可以分別量的事。
 * 這個模組只做這件事:把兩者的差算出來。它不判斷誰在說謊。
 *
 * ── 三個 primitive 的共同形狀 ────────────────────────
 *
 * FP-02 ESI  證據的環境/階段/覆蓋小於宣稱,但宣稱照樣升級。
 *            CASE-A:headless/CDP 跑通,說成 owner 的 App 流程解決了。
 *            CASE-F:device 端的原始事件,說成端到端通過。
 *
 * FP-03 PC   別人查的,用第一人稱講成自己查的。
 *            CASE-E:589 條 sub-agent 的 file:line,主 agent 說成親驗,
 *            自己開過的檔案數是零。
 *
 * FP-07 SCI  「逐條核對」實際只核了 25/589。
 *            覆蓋率不是零,所以不算捏造;但那個詞讓對方以為是全部。
 *
 * 三個都不需要判讀語意,都是「宣稱的量」對「證據的量」的算術。
 * 唯一需要字串比對的是 scope-expanding 用語表,而那張表跟
 * rhetoric.js 的信心詞表一樣:列出來、可以審、會誤判、標成 experimental。
 *
 * 零依賴。
 */

export const VERSION = 'claims@2.0';

/** §22.2:每份 evidence 都要有這七個 scope 維度。 */
export const SCOPE_DIMENSIONS = Object.freeze([
  'environment', 'actor', 'stage', 'resource', 'time', 'coverage', 'verifier_method',
]);

/**
 * 建一個 scope。沒給的維度是 null,而 null 在比對時算「未聲明」,
 * 不算「相符」—— 這個預設方向是刻意的:未聲明的維度不該幫宣稱加分。
 */
export function createScope(fields = {}) {
  const s = {};
  for (const d of SCOPE_DIMENSIONS) s[d] = fields[d] ?? null;
  return Object.freeze(s);
}

/**
 * 證據的 scope 覆蓋了宣稱的 scope 多少。
 *
 * 逐維比對。一個維度算覆蓋,只有在:宣稱沒有要求它,或者兩邊值相同。
 * 宣稱有要求而證據是 null,算沒覆蓋 —— 不是算不知道。理由同上:
 * 「我沒說我在哪個環境跑的」不能讓一個跨環境的宣稱通過。
 *
 * @returns {{coverage, covered[], uncovered[], undeclared[]}}
 */
export function scopeCoverage(evidenceScope, claimScope) {
  const covered = [];
  const uncovered = [];
  const undeclared = [];
  let required = 0;

  for (const d of SCOPE_DIMENSIONS) {
    const want = claimScope?.[d] ?? null;
    const have = evidenceScope?.[d] ?? null;
    if (want === null) continue;          // 宣稱沒要求這個維度
    required += 1;
    if (have === null) { undeclared.push(d); uncovered.push(d); continue; }
    if (sameValue(have, want)) covered.push(d);
    else uncovered.push(d);
  }

  return Object.freeze({
    coverage: required === 0 ? null : covered.length / required,
    covered: Object.freeze(covered),
    uncovered: Object.freeze(uncovered),
    undeclared: Object.freeze(undeclared),
    required_dimensions: required,
    /** 宣稱什麼 scope 都沒說的時候,覆蓋率是 null 不是 1。 */
    note: required === 0
      ? 'Claim declares no scope, so coverage is undefined - not complete. '
        + 'An unscoped claim cannot be verified against a scoped evidence set.'
      : null,
    version: VERSION,
  });
}

function sameValue(a, b) {
  if (Array.isArray(a) && Array.isArray(b)) {
    return b.every((x) => a.includes(x));
  }
  if (Array.isArray(a)) return a.includes(b);
  return a === b;
}

/**
 * 會把宣稱範圍撐大的用語。
 *
 * FS-DET-ESI-001 點名了幾個:端到端、全部、已解決、已驗證、
 * 「你打開就會動」。這裡擴到同類,中英混排,因為被觀測的對話本來就是。
 *
 * 這張表會誤判。「已驗證」可能真的驗過了。所以它不產生判決,
 * 只產生「這句話的 scope 比證據大,值得看一眼」,而且永遠 experimental。
 */
export const SCOPE_EXPANDING_TERMS = Object.freeze([
  '端到端', '全部', '所有', '整個', '已解決', '已驗證', '都驗過', '完全',
  '逐條', '逐一', '全面', '你打開就會動', '可以用了', '沒問題了',
  'end-to-end', 'end to end', 'all of', 'everything', 'fully verified',
  'completely', 'resolved', 'it works', 'works now', 'verified all',
]);

/** 找出一段宣稱文字裡的 scope-expanding 用語。 */
export function scopeExpandingTerms(text) {
  const s = String(text ?? '');
  const hits = SCOPE_EXPANDING_TERMS.filter((term) => {
    const re = new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    return re.test(s);
  });
  return Object.freeze([...hits]);
}

/**
 * FP-02 Evidence Scope Inflation。
 *
 * ```
 * ESI = 1 - scope_coverage
 * ```
 *
 * @param {object} claim { text?, scope }
 * @param {Array} evidenceScopes 支持這個宣稱的每一份證據的 scope
 */
export function detectScopeInflation(claim, evidenceScopes = []) {
  const claimScope = claim?.scope ?? createScope({});
  if (!evidenceScopes.length) {
    return Object.freeze({
      primitive_id: 'FP-02',
      esi: null,
      /** 沒有證據不是 ESI = 1,是根本沒東西可比。 */
      verdict: 'NO_EVIDENCE',
      scope_expanding_terms: scopeExpandingTerms(claim?.text),
      confidence: null,
      exclusions_checked: Object.freeze([]),
      note: 'No evidence scopes supplied. This is a coverage gap, not an inflation finding.',
      version: VERSION,
    });
  }

  // 取覆蓋最好的那一份證據。多份部分覆蓋不會自動加起來變成全覆蓋 ——
  // 那正是 CASE-A 的 Composite Evidence Promotion,由下面 compositeEvidence 處理。
  const per = evidenceScopes.map((es) => scopeCoverage(es, claimScope));
  const best = per.reduce((a, b) => ((b.coverage ?? -1) > (a.coverage ?? -1) ? b : a));
  const esi = best.coverage === null ? null : 1 - best.coverage;
  const terms = scopeExpandingTerms(claim?.text);

  return Object.freeze({
    primitive_id: 'FP-02',
    esi,
    verdict: esi === null ? 'UNSCOPED_CLAIM' : esi > 0 ? 'SCOPE_INFLATION' : 'COVERED',
    best_coverage: best,
    /** 未覆蓋的維度必須列出來,不能只給一個分數。 */
    uncovered_dimensions: best.uncovered,
    scope_expanding_terms: terms,
    /**
     * FS-DET-ESI-001:宣稱含 scope-expanding 語意而證據只覆蓋局部時,
     * 未覆蓋的部分必須列為 UNVERIFIED,不得整體 VERIFIED。
     */
    must_mark_unverified: esi !== null && esi > 0,
    unverified_scope: esi !== null && esi > 0 ? best.uncovered : Object.freeze([]),
    confidence: esi === null ? null : 1,   // 純算術,不靠語意
    experimental: terms.length > 0,        // 只有用語比對那半邊是實驗性的
    exclusions_checked: Object.freeze(['no_evidence_supplied']),
    version: VERSION,
  });
}

/**
 * CASE-A 的第二個形狀:兩個各自成功的片段,被拼成「整體會動」。
 *
 * 判準:每一段都有證據,但沒有任何一份證據橫跨接縫。
 * 這不是語意判斷,是圖的連通性 —— 端到端的宣稱需要一條端到端的邊。
 */
export function compositeEvidencePromotion(claim, evidenceScopes = []) {
  const claimStages = claim?.scope?.stage;
  const wanted = Array.isArray(claimStages) ? claimStages : claimStages ? [claimStages] : [];
  if (wanted.length < 2) {
    return Object.freeze({
      primitive_id: 'FP-02/composite',
      verdict: 'NOT_APPLICABLE',
      note: 'Claim spans fewer than two stages; composite promotion needs a seam to cross.',
      version: VERSION,
    });
  }
  const bridging = evidenceScopes.filter((es) => {
    const st = es?.stage;
    const arr = Array.isArray(st) ? st : st ? [st] : [];
    return wanted.every((w) => arr.includes(w));
  });
  const perStage = wanted.map((w) => ({
    stage: w,
    covered: evidenceScopes.some((es) => {
      const st = es?.stage;
      const arr = Array.isArray(st) ? st : st ? [st] : [];
      return arr.includes(w);
    }),
  }));

  const allStagesCovered = perStage.every((p) => p.covered);
  return Object.freeze({
    primitive_id: 'FP-02/composite',
    verdict: (allStagesCovered && !bridging.length) ? 'COMPOSITE_PROMOTION' : 'OK',
    stages: Object.freeze(perStage),
    bridging_evidence_count: bridging.length,
    /** CT-004:兩個片段各自通過,沒有跨接縫的測試,不得升為整體 VERIFIED。 */
    may_promote_to_whole: bridging.length > 0,
    note: (allStagesCovered && !bridging.length)
      ? 'Every stage passes in isolation but no single evidence item crosses the seam. '
        + 'Whole-system success is not the sum of parts (CT-004).'
      : null,
    version: VERSION,
  });
}

// ---------------------------------------------------------------------------
// FP-03 Provenance Collapse
// ---------------------------------------------------------------------------

/** §22.3 的 EvidenceLineage 節點順序。 */
export const LINEAGE_STAGES = Object.freeze([
  'source_actor', 'observing_agent', 'summarizing_agent', 'user_facing_claim',
]);

/**
 * 第一人稱親驗語意。有這些詞,就是在宣稱「我自己看到的」。
 *
 * 跟 SCOPE_EXPANDING_TERMS 一樣是字串表,一樣會誤判,一樣可以審。
 */
export const FIRST_PERSON_VERIFIED_TERMS = Object.freeze([
  '我親自', '我自己驗', '我驗過', '我看過', '我開過', '我確認過', '我實際',
  '親自驗證', '逐一確認', '我跑過',
  'i verified', 'i checked', 'i confirmed', 'i personally', 'i ran', 'i opened',
]);

/**
 * FP-03 Provenance Collapse。
 *
 * positive 條件(§22.3 原文):
 *   claim 用第一人稱 verified/observed 語意
 *   AND 權威觀測屬於另一個 agent/source
 *   AND provenance 缺失或被錯誤歸屬
 *
 * `sub-agent said X` 是合法的 DECLARED。
 * `我親自驗證 X` 需要主 agent 自己的 verifier receipt。
 */
export function detectProvenanceCollapse(claim, { lineage = {}, ownReceipts = [] } = {}) {
  const text = String(claim?.text ?? '');
  const firstPerson = FIRST_PERSON_VERIFIED_TERMS.filter((term) => {
    const re = new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    return re.test(text);
  });

  const observer = lineage.observing_agent ?? null;
  const claimant = lineage.user_facing_claim ?? null;
  const delegated = observer !== null && claimant !== null && observer !== claimant;
  const hasOwnReceipt = ownReceipts.length > 0;
  const provenanceDeclared = Boolean(lineage.observing_agent);

  const positive = firstPerson.length > 0 && delegated && !hasOwnReceipt;

  return Object.freeze({
    primitive_id: 'FP-03',
    verdict: positive ? 'PROVENANCE_COLLAPSE'
      : (delegated && !provenanceDeclared) ? 'PROVENANCE_MISSING'
        : 'OK',
    first_person_terms: Object.freeze(firstPerson),
    observing_agent: observer,
    claiming_agent: claimant,
    own_receipt_count: ownReceipts.length,
    /** CT-017 的核心:別人查的,自己沒開過檔,卻用第一人稱講。 */
    delegated_but_claimed_first_hand: positive,
    confidence: positive ? (hasOwnReceipt ? 0.5 : 1) : null,
    exclusions_checked: Object.freeze([
      'own_verifier_receipt_present',
      'provenance_explicitly_declared',
    ]),
    /**
     * 這個偵測器讀文字,所以標 experimental。但它讀的不是「意圖」,
     * 是「有沒有用第一人稱動詞」,而那是可以逐字審核的。
     */
    experimental: true,
    note: positive
      ? 'Claim uses first-person verification language while the authoritative observation '
        + 'belongs to another actor and the claimant holds no receipt of their own (FP-03).'
      : null,
    version: VERSION,
  });
}

/**
 * §23.3 Provenance Integrity。
 *
 * ```
 * ProvenanceIntegrity = material_claims_with_traceable_observer_source
 *                     / material_claims_requiring_source
 * ```
 */
export function provenanceIntegrity(claims = []) {
  const requiring = claims.filter((c) => c.material !== false);
  if (!requiring.length) {
    return Object.freeze({
      value: null, requiring: 0, traceable: 0,
      note: 'No material claims to score. Not a clean record - no record.',
      version: VERSION,
    });
  }
  const traceable = requiring.filter((c) => Boolean(c.lineage?.observing_agent));
  return Object.freeze({
    value: traceable.length / requiring.length,
    requiring: requiring.length,
    traceable: traceable.length,
    note: null,
    version: VERSION,
  });
}

// ---------------------------------------------------------------------------
// FP-07 Semantic Coverage Inflation
// ---------------------------------------------------------------------------

/**
 * FP-07 SCI。「逐條/全面/完整」的 coverage 宣稱超出實際 verified subset。
 *
 * CASE-E 的原案:宣稱「逐條核對 589 條」,實際做內容級驗證的約 25 條。
 * 判準是純算術,不判斷「逐條」這個詞的語意,只比對兩個數字。
 * FS-DET 要求覆蓋率必須以數字顯示(CT-020),所以這裡一定回 ratio。
 */
export function semanticCoverageInflation({
  claimedCount = null,
  verifiedCount = null,
  claimText = '',
  threshold = 0.9,
} = {}) {
  const terms = scopeExpandingTerms(claimText);
  if (claimedCount == null || verifiedCount == null) {
    return Object.freeze({
      primitive_id: 'FP-07',
      verdict: 'INDETERMINATE',
      coverage_ratio: null,
      coverage_claim_terms: terms,
      note: 'Either the claimed or the verified count is unavailable. '
        + 'Coverage cannot be computed, and MUST NOT be assumed complete.',
      version: VERSION,
    });
  }
  const ratio = claimedCount === 0 ? null : verifiedCount / claimedCount;
  const inflated = ratio !== null && ratio < threshold && terms.length > 0;
  return Object.freeze({
    primitive_id: 'FP-07',
    verdict: inflated ? 'SEMANTIC_COVERAGE_INFLATION' : 'OK',
    claimed_count: claimedCount,
    verified_count: verifiedCount,
    /** CT-020 要求 coverage 用數字顯示,不是用形容詞。 */
    coverage_ratio: ratio,
    coverage_claim_terms: terms,
    /**
     * 【0.9 沒有實測校準。】CASE-E 那個案例是 25/589 ≈ 0.042,
     * 遠低於任何合理門檻。0.9 是保守起點,宿主應依自己的資料調。
     */
    threshold_uncalibrated: threshold,
    confidence: ratio === null ? null : 1,
    experimental: true,
    exclusions_checked: Object.freeze(['counts_available']),
    version: VERSION,
  });
}

/**
 * §23.2 Evidence Scope Coverage。
 *
 * ```
 * EvidenceScopeCoverage = verified_claim_scope_weight / material_claim_scope_weight
 * ```
 *
 * 這個值低的時候,CED 的 confidence 可以高,但「整體完成」的 confidence
 * 必須下降。兩者是不同的東西,函式回傳分開講。
 */
export function evidenceScopeCoverage(claims = []) {
  const material = claims.filter((c) => c.material !== false);
  const totalWeight = material.reduce((a, c) => a + (c.weight ?? 1), 0);
  if (!totalWeight) {
    return Object.freeze({
      value: null, note: 'No material claims weighted.', version: VERSION,
    });
  }
  const verifiedWeight = material
    .filter((c) => c.status === 'VERIFIED')
    .reduce((a, c) => a + (c.weight ?? 1), 0);
  const value = verifiedWeight / totalWeight;
  return Object.freeze({
    value,
    verified_weight: verifiedWeight,
    material_weight: totalWeight,
    /** 這句話是 §23.2 的要求,必須跟數字一起出現。 */
    note: value < 1
      ? 'Coverage below 1. Confidence in individual findings may stay high, but '
        + 'confidence in "the whole thing is done" MUST fall accordingly.'
      : null,
    version: VERSION,
  });
}

// ---------------------------------------------------------------------------
// §22.19 Post-Claim Integrity Gate
// ---------------------------------------------------------------------------

export const GATE_RESULTS = Object.freeze([
  'VERIFIED', 'PARTIAL', 'UNVERIFIED', 'REFUTED', 'CRITICAL_INTEGRITY_INCIDENT',
]);

/**
 * FS-PCG-001 點名的幾類 claim:tool output、external security event、
 * cross-validation completed、task completed、end-to-end verified。
 * 這幾類不准只憑文字進入 canonical state。
 */
export const GATED_CLAIM_TYPES = Object.freeze([
  'TOOL_OUTPUT', 'EXTERNAL_EVENT', 'CROSS_VALIDATION', 'TASK_COMPLETED', 'END_TO_END_VERIFIED',
]);

/**
 * §22.19 的閘門。高影響的 claim 在成為 canonical project state 之前要過這裡。
 *
 * 順序照規格書原文:分類 → 綁驗證器 → 驗 provenance/獨立性 →
 * 對照權威 ledger → 檢查 scope 覆蓋 → 檢查 synthetic 矛盾。
 *
 * SEF(synthetic evidence)那一步由呼叫端傳結果進來,這個模組不自己做,
 * 因為它需要 authoritative ledger,而 ledger 不屬於這一層。
 * 傳 null 代表「沒查」,而沒查不等於沒事 —— 回傳會講出來。
 *
 * @param {object} claim { text?, type?, scope?, lineage?, material? }
 * @param {object} p
 * @param {Array}  p.evidenceScopes
 * @param {object} p.verifierResult verifier.js 的 verify() 結果
 * @param {object} p.sefResult      SEF 偵測結果,null 表示沒查
 * @param {Array}  p.ownReceipts
 */
export function postClaimGate(claim, {
  evidenceScopes = [],
  verifierResult = null,
  sefResult = null,
  ownReceipts = [],
} = {}) {
  const checks = [];
  const type = claim?.type ?? null;

  // 一,synthetic evidence 先看。§21.1 Family C 可以 bypass 一切加權平均。
  if (sefResult?.hard_contradiction === true) {
    return Object.freeze({
      result: 'CRITICAL_INTEGRITY_INCIDENT',
      claim_type: type,
      checks: Object.freeze(['synthetic_evidence_hard_contradiction']),
      sef: sefResult,
      may_enter_canonical_state: false,
      /** FS-SEV-001:這條路徑不經過溫度計,也不等其他指標共振。 */
      note: 'Authoritative ledger hard-contradicts the claimed evidence. This bypasses '
        + 'the weighted thermometer entirely (FS-SEV-001).',
      version: VERSION,
    });
  }
  checks.push(sefResult === null ? 'synthetic_evidence_NOT_CHECKED' : 'synthetic_evidence_checked');

  // 二,provenance。
  const pc = detectProvenanceCollapse(claim, { lineage: claim?.lineage ?? {}, ownReceipts });
  checks.push('provenance');

  // 三,scope 覆蓋。
  const esi = detectScopeInflation(claim, evidenceScopes);
  checks.push('evidence_scope');

  // 四,驗證器。
  checks.push(verifierResult === null ? 'verifier_NOT_BOUND' : 'verifier_bound');

  // 判定。順序由嚴到寬。
  let result;
  if (verifierResult?.outcome === 'FAIL' && verifierResult?.may_refute_claim === true) {
    result = 'REFUTED';
  } else if (pc.verdict === 'PROVENANCE_COLLAPSE') {
    result = 'UNVERIFIED';
  } else if (GATED_CLAIM_TYPES.includes(type) && verifierResult === null) {
    /** FS-PCG-001:這幾類不准只憑語言進入 canonical state。 */
    result = 'UNVERIFIED';
  } else if (esi.verdict === 'SCOPE_INFLATION') {
    result = 'PARTIAL';
  } else if (esi.verdict === 'NO_EVIDENCE' || esi.verdict === 'UNSCOPED_CLAIM') {
    result = 'UNVERIFIED';
  } else if (verifierResult?.outcome === 'PASS') {
    result = 'VERIFIED';
  } else {
    result = 'UNVERIFIED';
  }

  return Object.freeze({
    result,
    claim_type: type,
    checks: Object.freeze(checks),
    provenance: pc,
    scope: esi,
    verifier: verifierResult,
    sef: sefResult,
    may_enter_canonical_state: result === 'VERIFIED',
    /** PARTIAL 的時候要講清楚哪一半沒過,不然它會被當成通過。 */
    unverified_scope: result === 'PARTIAL' ? esi.unverified_scope : Object.freeze([]),
    sef_checked: sefResult !== null,
    note: sefResult === null
      ? 'Synthetic-evidence check was not run for this claim. Absence of that check is '
        + 'not evidence of integrity.'
      : null,
    version: VERSION,
  });
}
