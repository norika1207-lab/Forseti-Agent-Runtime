/**
 * Forseti v2.0 — P0 術語凍結 + P2 Evidence Receipt
 *
 * 規格來源:`docs/spec-v2.0.md` §2 Normative Vocabulary、§3 Evidence Law、
 * §4 Temporal Evidence。這是 §26 實作順序的第一與第三階,而 FS-IMP-001
 * 明講:P3/P4/P5/P6 沒完成之前,不准把 drift classifier 當主判斷器。
 * 所以這個檔案先做,而且它不判斷任何東西 —— 它只定義「什麼算證據」。
 *
 * ── 為什麼 v1 的六級不能直接沿用 ────────────────────────
 *
 * v1(`conformance.js` 的 EPISTEMIC)是 OBSERVED/VERIFIED/INFERRED/
 * UNKNOWN/REFUTED/STALE 六級,那組講的是「一個宣稱處於什麼狀態」。
 * v2 §3.1 的四級 OBSERVED/DECLARED/INFERRED/MISSING 講的是別的東西:
 * 「這份證據是從哪裡來的」。兩組不衝突,是兩個軸,所以兩個都留著。
 *
 * 最重要的新增是 DECLARED。v1 沒有這一級,自白書、self-audit、
 * agent 說「我驗過了」全部只能塞進 INFERRED 或 OBSERVED,兩個都是錯的。
 * FS-EVD-002 要求它們必須留在 DECLARED,而且沒有外部證據時不得升級。
 *
 * 第二個新增是 MISSING。v1 用 UNKNOWN 涵蓋了「沒觀測到」跟「本來有
 * 但因為保留期限消失了」兩件事,而 §4 明講這兩件事必須分開 ——
 * 把 retention deletion 當成「agent 當時沒做」是 FS-TMP-003 禁止的。
 *
 * 零依賴。
 */

export const VERSION = 'evidence@2.0';

/**
 * v2 §3.1 的四個 evidence class。順序有意義:authority 由高到低。
 *
 * 這不是 v1 六級的替代品,是另一個軸。v1 那組回答「這個 claim 現在
 * 算不算數」,這組回答「這份證據是誰產生的」。
 */
export const EVIDENCE_CLASSES = Object.freeze([
  'OBSERVED',   // filesystem/process/tool/git/system-of-record 直接觀測
  'DECLARED',   // user/agent 自己說的,包含 self-audit 與自白書
  'INFERRED',   // Forseti 自己的語意或統計推論
  'MISSING',    // 本應存在但因 retention/capture failure 取不到
]);

/**
 * 每一級可以支持什麼樣的系統宣稱。照 §3.1 表格逐字實作。
 *
 * `can_self_validate: false` 的意思是:這一級的證據不能證明自己。
 * DECLARED 最重要,因為六份自白書全部是這一級,而 FS-SRC-002 明講
 * 它們可以用來發現候選 pattern,不能當 ground truth。
 */
export const CLASS_AUTHORITY = Object.freeze({
  OBSERVED: Object.freeze({
    rank: 0,
    can_self_validate: true,
    can_refute_claim: true,
    note: 'Highest factual layer. May verify or refute a claim.',
  }),
  DECLARED: Object.freeze({
    rank: 1,
    can_self_validate: false,
    can_refute_claim: false,
    note: 'Forms claim/goal candidates. Cannot validate itself. '
      + 'Model self-reports, confessions and self-audits live here permanently '
      + 'unless independent OBSERVED evidence corroborates them (FS-EVD-002).',
  }),
  INFERRED: Object.freeze({
    rank: 2,
    can_self_validate: false,
    can_refute_claim: false,
    note: 'Must carry confidence. Must never override OBSERVED.',
  }),
  MISSING: Object.freeze({
    rank: 3,
    can_self_validate: false,
    can_refute_claim: false,
    note: 'Lowers confidence. MUST NOT be auto-converted to false (FS-TMP-003).',
  }),
});

/**
 * §2 的兩個特殊狀態。它們不是 evidence class,是「答案」的狀態。
 *
 * UNKNOWN     系統無法觀測。不是 0、不是 false、不是模型可以自己補的空白。
 * INDETERMINATE 資料存在但不足以支持可靠結論。
 *
 * 分開的理由:前者要去採集,後者要去補證據強度,處理方式不同。
 * v1 只有 UNKNOWN,兩種情況混在一起,看不出該做什麼。
 */
export const UNKNOWN = Object.freeze({ state: 'UNKNOWN', value: null });
export const INDETERMINATE = Object.freeze({ state: 'INDETERMINATE', value: null });

/**
 * FS-EVD-002:自白、self-audit、「我騙了你」這類文字永遠是 DECLARED。
 *
 * 這個函式是一道閘門,不是建議。它存在的理由是六份自白書 ——
 * 它們讀起來極有說服力,而說服力正是不能當證據的原因。
 *
 * @param {object} p
 * @param {string} p.evidenceClass 目前的 class
 * @param {string} p.target 想升級到哪一級
 * @param {Array} p.corroboration 獨立的 OBSERVED 證據
 * @returns {{allowed, resulting_class, reason}}
 */
export function canPromote({ evidenceClass, target, corroboration = [] } = {}) {
  if (!EVIDENCE_CLASSES.includes(evidenceClass)) {
    return Object.freeze({
      allowed: false,
      resulting_class: null,
      reason: `Unrecognised evidence class: ${String(evidenceClass)}`,
    });
  }
  if (target !== 'OBSERVED') {
    return Object.freeze({
      allowed: false,
      resulting_class: evidenceClass,
      reason: 'Only promotion to OBSERVED is defined. Everything else is a downgrade '
        + 'or a no-op, and neither needs a gate.',
    });
  }
  const independent = corroboration.filter((c) => c?.evidence_class === 'OBSERVED');
  if (!independent.length) {
    return Object.freeze({
      allowed: false,
      resulting_class: evidenceClass,
      /**
       * 這句話針對的是自白書。一份寫得很誠懇、細節很多、
       * 連自己的動機都剖析了的自白,證據等級跟一句「我做完了」完全相同。
       */
      reason: 'No independent OBSERVED corroboration. A fluent, detailed, or '
        + 'self-critical account does not raise its own evidence class (FS-EVD-002).',
    });
  }
  return Object.freeze({
    allowed: true,
    resulting_class: 'OBSERVED',
    reason: `Corroborated by ${independent.length} independent OBSERVED item(s).`,
  });
}

/**
 * §19.2 的 IntentionalityRecord。
 *
 * 六份自白裡有「我不想做」「我偷懶」「我知道仍然這樣做」「我利用資訊
 * 不對稱」。FS-CORP-001 要求這些只能存成 DECLARED_CAUSAL_HYPOTHESIS,
 * FS-CORP-005 要求可觀測的 runtime pattern 可以判,主觀意圖不可以。
 *
 * 這個結構把兩者強制分欄。`MUST_NOT_AUTOPROMOTE_TO_OBSERVED` 是規格書
 * 原文的欄位名,一字不改,因為它是給讀 JSON 的人看的警告。
 */
export function intentionalityRecord({
  humanAdjudication = null,
  modelSelfReport = null,
  externalEvidence = [],
} = {}) {
  let state = 'UNVERIFIED';
  if (modelSelfReport) state = 'DECLARED';
  if (humanAdjudication) state = 'OWNER_ADJUDICATED';

  return Object.freeze({
    human_adjudication: humanAdjudication,
    model_self_report: modelSelfReport,
    external_evidence: Object.freeze([...externalEvidence]),
    intentionality_state: state,
    MUST_NOT_AUTOPROMOTE_TO_OBSERVED: true,
    /**
     * owner 判定「這是飄移」是高權威的 failure label(FS-CORP-003),
     * 但它判的是行為與後果,不是模型心裡想什麼。這個欄位分開記,
     * 是為了讓下游不能把前者當成後者。
     */
    note: state === 'OWNER_ADJUDICATED'
      ? 'Owner adjudication is authoritative for the failure label, not for the '
        + 'mental state behind it (FS-CORP-004).'
      : 'Motive remains a declared hypothesis. Behaviour may still be scored (FS-CORP-005).',
    version: VERSION,
  });
}

// ---------------------------------------------------------------------------
// §4 Temporal Evidence
// ---------------------------------------------------------------------------

/** §4 的 EvidenceReceipt 欄位,照規格書原文順序。 */
export const RECEIPT_FIELDS = Object.freeze([
  'observed_at', 'resource_locator', 'existence', 'byte_size', 'content_hash',
  'diff_hash', 'mtime', 'process_id', 'process_status', 'exit_code',
  'stdout_hash', 'stderr_hash', 'provider_object_id', 'capture_method',
]);

/**
 * FS-TMP-001:在 artifact/process/effect 還看得到的時候就留下憑證。
 *
 * 為什麼不能事後補:使用者回報 session 相關檔案會在保留期限後消失
 * (FS-SRC-003 把這件事標為部署假設,不是已知事實)。事後分析會看到
 * 「AI 說做了」但檔案不在,而那時候分不出是當時沒做,還是後來被刪了。
 *
 * `existence` 三態:true / false / unknown。不准用 false 代替 unknown ——
 * 那正是 FS-TMP-003 禁止的那一步。
 */
export function createReceipt({
  observedAt,
  resourceLocator,
  existence = 'unknown',
  captureMethod = 'unknown',
  ...rest
} = {}) {
  if (![true, false, 'unknown'].includes(existence)) {
    throw new TypeError(
      `existence must be true, false or 'unknown' - got ${JSON.stringify(existence)}. `
      + 'A missing observation is not a negative observation (FS-TMP-003).',
    );
  }
  const r = {
    observed_at: observedAt ?? null,
    resource_locator: resourceLocator ?? null,
    existence,
    capture_method: captureMethod,
  };
  for (const f of RECEIPT_FIELDS) {
    if (f in r) continue;
    r[f] = rest[toCamel(f)] ?? rest[f] ?? null;
  }
  return Object.freeze(r);
}

function toCamel(s) {
  return s.replace(/_([a-z])/g, (_, c) => c.toUpperCase());
}

/**
 * FS-TMP-002:「它在 T 那一刻存在嗎」與「它現在存在嗎」是兩個不同的問題。
 *
 * 這兩個函式刻意分開命名,不合併成一個帶旗標的函式,因為合併之後
 * 呼叫端只要漏傳一個參數,兩個問題就會被靜靜地當成同一個。
 */
export function existedAt(receipts, { resourceLocator, at } = {}) {
  const relevant = (receipts ?? [])
    .filter((r) => r.resource_locator === resourceLocator && r.observed_at != null
      && r.observed_at <= at)
    .sort((a, b) => b.observed_at - a.observed_at);

  if (!relevant.length) {
    return Object.freeze({
      answer: 'UNKNOWN',
      evidence_class: 'MISSING',
      receipt: null,
      /** 沒有當時的憑證,就不知道當時有沒有。這不是「沒有」。 */
      reason: 'No contemporaneous receipt at or before that time.',
      version: VERSION,
    });
  }
  const latest = relevant[0];
  return Object.freeze({
    answer: latest.existence === true ? 'YES' : latest.existence === false ? 'NO' : 'UNKNOWN',
    evidence_class: latest.existence === 'unknown' ? 'MISSING' : 'OBSERVED',
    receipt: latest,
    byte_size: latest.byte_size ?? null,
    content_hash: latest.content_hash ?? null,
    reason: `Receipt captured at ${latest.observed_at} by ${latest.capture_method}.`,
    version: VERSION,
  });
}

/**
 * FS-TMP-003:現在不見了,而且沒有當時的憑證,只能標
 * MISSING_HISTORICAL_EVIDENCE,不准直接說「agent 當時騙人/沒做」。
 *
 * @param {object} p
 * @param {boolean|'unknown'} p.existsNow 現在的觀測結果
 * @param {object|null} p.historicalReceipt 當時的憑證,沒有就傳 null
 * @param {boolean} p.retentionKnown 是否已知這類資源會被保留期限清掉
 */
export function reconcileHistorical({
  existsNow,
  historicalReceipt = null,
  retentionKnown = false,
} = {}) {
  if (existsNow === true) {
    return Object.freeze({
      verdict: 'EXISTS_NOW',
      evidence_class: 'OBSERVED',
      may_conclude_agent_did_not_do_it: false,
      version: VERSION,
    });
  }
  if (historicalReceipt) {
    return Object.freeze({
      verdict: 'VERIFIED_AT_TIME',
      evidence_class: 'OBSERVED',
      receipt: historicalReceipt,
      may_conclude_agent_did_not_do_it: false,
      /** CT-002:當時的憑證證明它存在過,現在不見了是保留期限的事。 */
      note: 'A contemporaneous receipt proves it existed. Current absence is a '
        + 'retention fact, not an agent failure.',
      version: VERSION,
    });
  }
  return Object.freeze({
    verdict: 'MISSING_HISTORICAL_EVIDENCE',
    evidence_class: 'MISSING',
    /** 這個欄位是這整個函式存在的理由。 */
    may_conclude_agent_did_not_do_it: false,
    retention_known: retentionKnown,
    note: retentionKnown
      ? 'Resource is gone and retention is known to delete this class of resource. '
        + 'Absence carries no information about what the agent did (FS-TMP-003).'
      : 'Resource is gone and no contemporaneous receipt exists. This is an evidence '
        + 'gap, not a finding. Capture receipts at event time (FS-TMP-001).',
    version: VERSION,
  });
}
