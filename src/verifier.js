/**
 * Forseti v2.0 — P4 Verifier Registry
 *
 * 規格來源:`docs/spec-v2.0.md` §22.4(FP-04 VMI)、§23.4、§28.2。
 *
 * ── 這個模組要防的那件事 ─────────────────────────────
 *
 * CASE-E 裡有一段:用 grep 找一個字串,沒找到,就宣告「hex bytes 不存在」,
 * 據此推翻了一份正確的證據。grep 對字串是有效的驗證器,對 hex 表示法
 * 沒有 coverage —— 而它照樣會回一個乾淨的「0 hit」。
 *
 * 錯的不是 grep,是拿一個不覆蓋該表示法的方法去下結論。所以 v2 要求
 * 每個 verifier 自己聲明它檢查什麼、不檢查什麼,而 FS-DET-VMI-001 講得
 * 更狠:Forseti 的驗證器本身也要被驗證,`VERIFIER_UNKNOWN_COVERAGE`
 * 必須比一個錯誤的 pass/fail 更優先。
 *
 * 一個會給錯誤答案的驗證器,比沒有驗證器更危險,因為它會讓人停止查。
 *
 * 零依賴。
 */

export const VERSION = 'verifier@2.0';

/** 驗證結果。UNKNOWN_COVERAGE 是這個模組存在的理由,不是邊角案例。 */
export const OUTCOMES = Object.freeze([
  'PASS',
  'FAIL',
  'UNKNOWN_COVERAGE',      // 這個方法對這種表示法/語意沒有 coverage
  'PRECONDITION_UNMET',    // 方法本身要求的前提沒滿足
]);

/**
 * §22.4 的 VerifierContract,欄位照規格書原文。
 *
 * `semantics_not_checked` 是最重要的一欄,也是最容易被留白的一欄。
 * 留白的話,這個契約就退化成「我什麼都檢查」,而那正是 grep 那次的形狀。
 * 所以建構時它是必填,空陣列要自己明講。
 */
export function createContract({
  methodId,
  targetTypes = [],
  supportedRepresentations = [],
  semanticsChecked = [],
  semanticsNotChecked = null,
  falseNegativeKnownCases = [],
  requiredPreconditions = [],
} = {}) {
  if (!methodId) throw new TypeError('methodId is required - an anonymous verifier cannot be audited.');
  if (semanticsNotChecked === null) {
    throw new TypeError(
      `Verifier ${methodId} must declare semantics_not_checked explicitly (use [] to assert `
      + 'it checks everything in scope). A contract that omits it silently claims total '
      + 'coverage, which is the grep-vs-hex failure in CASE-E (FP-04).',
    );
  }
  return Object.freeze({
    method_id: methodId,
    target_types: Object.freeze([...targetTypes]),
    supported_representations: Object.freeze([...supportedRepresentations]),
    semantics_checked: Object.freeze([...semanticsChecked]),
    semantics_not_checked: Object.freeze([...semanticsNotChecked]),
    false_negative_known_cases: Object.freeze([...falseNegativeKnownCases]),
    required_preconditions: Object.freeze([...requiredPreconditions]),
    version: VERSION,
  });
}

/**
 * 這個 verifier 有沒有資格對這個 claim 說話。
 *
 * 回傳的不是 true/false,是「哪些部分它覆蓋得到、哪些覆蓋不到」。
 * 呼叫端需要看得到未覆蓋的那一半,不然就會重演 CASE-E:
 * 拿一個部分覆蓋的方法,產出一個看起來完整的結論。
 */
export function coverageOf(contract, {
  targetType = null,
  representation = null,
  semanticsRequired = [],
  preconditionsMet = [],
} = {}) {
  const typeOk = targetType === null || contract.target_types.includes(targetType);
  const reprOk = representation === null
    || contract.supported_representations.includes(representation);

  const checked = semanticsRequired.filter((s) => contract.semantics_checked.includes(s));
  const uncovered = semanticsRequired.filter((s) => !contract.semantics_checked.includes(s));
  const missingPreconditions = contract.required_preconditions
    .filter((p) => !preconditionsMet.includes(p));

  const ratio = semanticsRequired.length === 0
    ? (typeOk && reprOk ? 1 : 0)
    : checked.length / semanticsRequired.length;

  return Object.freeze({
    method_id: contract.method_id,
    target_type_supported: typeOk,
    representation_supported: reprOk,
    semantics_covered: Object.freeze(checked),
    semantics_uncovered: Object.freeze(uncovered),
    missing_preconditions: Object.freeze(missingPreconditions),
    contract_coverage: ratio,
    /** 完全覆蓋才算數。部分覆蓋不是「大致可以」,是不能下全稱結論。 */
    fully_covers: typeOk && reprOk && uncovered.length === 0 && missingPreconditions.length === 0,
    version: VERSION,
  });
}

/**
 * 跑一次驗證,並且在方法沒有 coverage 的時候拒絕給 pass/fail。
 *
 * FS-DET-VMI-001 的實作。這裡的順序不能改:先問覆蓋,再看結果。
 * 反過來的話,`rawOutcome` 會先進到呼叫端腦裡,而人一旦看過一個
 * 乾淨的 0 hit,就很難再把它當成「這個方法答不了這題」。
 *
 * @param {object} contract VerifierContract
 * @param {object} p
 * @param {'PASS'|'FAIL'} p.rawOutcome 這個方法自己跑出來的結果
 * @param {object} p.scope 見 coverageOf
 */
export function verify(contract, { rawOutcome, ...scope } = {}) {
  const cov = coverageOf(contract, scope);

  if (cov.missing_preconditions.length) {
    return Object.freeze({
      outcome: 'PRECONDITION_UNMET',
      may_refute_claim: false,
      coverage: cov,
      reason: `Preconditions not met: ${cov.missing_preconditions.join(', ')}.`,
      version: VERSION,
    });
  }
  if (!cov.fully_covers) {
    return Object.freeze({
      outcome: 'UNKNOWN_COVERAGE',
      /**
       * 這一個 false 就是 CT-016。grep 找不到 hex bytes,回的必須是
       * 「我答不了」,不是「它不存在」。
       */
      may_refute_claim: false,
      coverage: cov,
      raw_outcome: rawOutcome ?? null,
      reason: 'Verifier does not fully cover this claim. '
        + (cov.representation_supported ? '' : 'Representation outside contract. ')
        + (cov.semantics_uncovered.length
          ? `Unchecked semantics: ${cov.semantics_uncovered.join(', ')}. ` : '')
        + 'A raw result from a non-covering method MUST NOT refute the claim '
        + '(FS-DET-VMI-001).',
      version: VERSION,
    });
  }
  if (!OUTCOMES.includes(rawOutcome) || rawOutcome === 'UNKNOWN_COVERAGE') {
    return Object.freeze({
      outcome: 'UNKNOWN_COVERAGE',
      may_refute_claim: false,
      coverage: cov,
      reason: `Verifier covered the claim but returned no usable outcome (${String(rawOutcome)}).`,
      version: VERSION,
    });
  }
  return Object.freeze({
    outcome: rawOutcome,
    may_refute_claim: rawOutcome === 'FAIL',
    coverage: cov,
    known_false_negatives: contract.false_negative_known_cases,
    version: VERSION,
  });
}

/**
 * §23.4:驗證結果的 confidence 不能高於驗證器本身的 validity confidence。
 *
 * ```
 * VerifierValidityConfidence = contract_coverage
 *                            × method_precondition_satisfaction
 *                            × verifier_test_quality
 * ```
 *
 * `verifierTestQuality` 拿不到就是 null,而 null 會讓整個結果變成 null,
 * 不是變成 1。沒有人測過的驗證器,不能因為沒被測過而得到滿分。
 */
export function validityConfidence(contract, {
  scope = {},
  verifierTestQuality = null,
} = {}) {
  const cov = coverageOf(contract, scope);
  const preconditionSatisfaction = contract.required_preconditions.length === 0
    ? 1
    : (contract.required_preconditions.length - cov.missing_preconditions.length)
      / contract.required_preconditions.length;

  if (verifierTestQuality === null) {
    return Object.freeze({
      value: null,
      contract_coverage: cov.contract_coverage,
      precondition_satisfaction: preconditionSatisfaction,
      verifier_test_quality: null,
      /** 【未校準】沒有人量過這個驗證器準不準,所以算不出總分。 */
      note: 'verifier_test_quality is unmeasured for this method, so validity confidence '
        + 'is null - not 1. An untested verifier does not earn a perfect score by '
        + 'never having been tested (§23.4).',
      version: VERSION,
    });
  }
  return Object.freeze({
    value: cov.contract_coverage * preconditionSatisfaction * verifierTestQuality,
    contract_coverage: cov.contract_coverage,
    precondition_satisfaction: preconditionSatisfaction,
    verifier_test_quality: verifierTestQuality,
    note: 'Claim verification confidence MUST be capped by this value (§28.2).',
    version: VERSION,
  });
}

/**
 * 上限規則本身。§28.2:VerifierValidityConfidence caps claim verification confidence。
 *
 * 分開成一個函式,是為了讓「有沒有套上限」這件事在呼叫端看得見,
 * 而不是藏在某個乘法裡。
 */
export function capConfidence(claimConfidence, validity) {
  if (validity?.value == null) {
    return Object.freeze({
      value: null,
      capped: true,
      reason: 'Verifier validity is unknown, so claim confidence cannot be asserted at all.',
      version: VERSION,
    });
  }
  const capped = Math.min(claimConfidence ?? 0, validity.value);
  return Object.freeze({
    value: capped,
    capped: capped < (claimConfidence ?? 0),
    reason: capped < (claimConfidence ?? 0)
      ? `Claim confidence ${claimConfidence} lowered to verifier validity ${validity.value}.`
      : 'Claim confidence already at or below verifier validity.',
    version: VERSION,
  });
}

/**
 * 內建的一組契約,對應規格書 §3.2 的 claim verification examples。
 *
 * 這些不是「Forseti 支援的全部」,是最低限度的示範:每一個都明講
 * 自己不檢查什麼。`grep_string` 那一條就是 CASE-E 的原型。
 */
export const BUILTIN_CONTRACTS = Object.freeze({
  file_exists_nonempty: createContract({
    methodId: 'file_exists_nonempty',
    targetTypes: ['file'],
    supportedRepresentations: ['filesystem'],
    semanticsChecked: ['existence', 'byte_size'],
    semanticsNotChecked: ['content_validity', 'semantic_correctness', 'parseability'],
    falseNegativeKnownCases: ['file written by an opaque shell command outside capture'],
    requiredPreconditions: ['path_resolvable'],
  }),
  content_hash_diff: createContract({
    methodId: 'content_hash_diff',
    targetTypes: ['file'],
    supportedRepresentations: ['filesystem'],
    semanticsChecked: ['content_changed'],
    semanticsNotChecked: ['change_is_correct', 'change_matches_intent'],
    falseNegativeKnownCases: ['mtime changed but content identical'],
    requiredPreconditions: ['before_hash_captured'],
  }),
  grep_string: createContract({
    methodId: 'grep_string',
    targetTypes: ['file', 'stream'],
    supportedRepresentations: ['utf8_text'],
    semanticsChecked: ['literal_substring_present'],
    /** CASE-E 的那一刀就寫在這裡。 */
    semanticsNotChecked: ['hex_byte_representation', 'encoded_forms', 'semantic_equivalence'],
    falseNegativeKnownCases: [
      'value present as hex bytes rather than utf8 text (CASE-E)',
      'value present but split across lines',
    ],
    requiredPreconditions: ['target_is_text'],
  }),
  process_liveness: createContract({
    methodId: 'process_liveness',
    targetTypes: ['process'],
    supportedRepresentations: ['pid', 'heartbeat', 'endpoint'],
    semanticsChecked: ['process_alive', 'heartbeat_recent'],
    semanticsNotChecked: ['service_healthy', 'work_progressing'],
    falseNegativeKnownCases: ['process alive but wedged with no output growth (FP-20)'],
    requiredPreconditions: ['observation_is_current'],
  }),
  http_status: createContract({
    methodId: 'http_status',
    targetTypes: ['url'],
    supportedRepresentations: ['http'],
    semanticsChecked: ['endpoint_reachable', 'status_code'],
    /** §29:HTTP 200 不等於 citation/content 正確。 */
    semanticsNotChecked: ['content_correctness', 'citation_title_match', 'semantic_relevance'],
    falseNegativeKnownCases: ['200 returned by a soft-404 page'],
    requiredPreconditions: [],
  }),
});
