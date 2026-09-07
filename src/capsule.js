// Forseti M1「Context 收銀台」核心模組。
// 依據:Forseti_Five_Mechanisms_Handoff_v1.0_2026-09-07.md 第 3 節。
// 邊界:不 import Moirai 任何東西、不接 ctx、不讀 duo_state.json、不做 UI、不做 HTTP。
// 純函數風格:不呼叫時鐘,produced_at / measured_at 一律由呼叫端傳入;
// 所有狀態轉移回傳新物件,回傳物件一律凍結。

export const CAPSULE_STATES = Object.freeze({
  PENDING: 'PENDING',
  PREVIEWED: 'PREVIEWED',
  ACCEPTED: 'ACCEPTED',
  REJECTED: 'REJECTED',
  SUMMARIZED_AGAIN: 'SUMMARIZED_AGAIN',
});

// 誠實條款(文件 3.8 雷一):token 計數來源必須標明,
// provider 回報的真值與自己估的不准混為一談。
export const TOKEN_SOURCES = Object.freeze({
  PROVIDER_REPORTED: 'PROVIDER_REPORTED',
  ESTIMATED: 'ESTIMATED',
});

// 狀態機,照文件 3.4 節的圖,一條不多一條不少。
// PENDING → ACCEPTED 這條邊只在自動放行條件成立時合法(acceptCapsule 裡把關)。
export const LEGAL_TRANSITIONS = Object.freeze({
  PENDING: Object.freeze(['PREVIEWED', 'ACCEPTED']),
  PREVIEWED: Object.freeze(['ACCEPTED', 'SUMMARIZED_AGAIN', 'REJECTED']),
  SUMMARIZED_AGAIN: Object.freeze(['PENDING']),
  ACCEPTED: Object.freeze([]),
  REJECTED: Object.freeze([]),
});

export function assertLegalTransition(fromState, toState) {
  const allowed = LEGAL_TRANSITIONS[fromState];
  if (!allowed) throw new Error(`Unknown state: ${String(fromState)}`);
  if (!allowed.includes(toState)) {
    throw new Error(`Illegal state transition: ${fromState} -> ${toState}`);
  }
}

// 預設設定。閾值不寫死,呼叫端可覆寫(文件 3.8 雷二:閾值應該可調,預設偏寬鬆)。
// auto_accept_ratio 0.02 = 文件 3.4 節建議的 token_cost <= 2% of window_total。
// compact_threshold 0.2 = exploded 批判「低於 20% 變色」的同一條線,
// 剩餘比例掉到它以下就視為會觸發壓縮。文件 3.5 只給欄位名,未給數值,此預設可調。
export const DEFAULT_CONFIG = Object.freeze({
  auto_accept_ratio: 0.02,
  compact_threshold: 0.2,
});

function intField(value, name) {
  if (!Number.isInteger(value) || value < 0) {
    throw new TypeError(`${name} must be a non-negative integer, got: ${String(value)}`);
  }
  return value;
}

function strField(value, name) {
  if (typeof value !== 'string' || value.length === 0) {
    throw new TypeError(`${name} must be a non-empty string`);
  }
  return value;
}

/** 建立 Capsule。欄位名照文件 3.3 節,一字不改。state 一律從 PENDING 開始。 */
export function createCapsule(fields) {
  const f = fields ?? {};
  return Object.freeze({
    capsule_id: strField(f.capsule_id, 'capsule_id'),
    produced_by: strField(f.produced_by, 'produced_by'),
    produced_at: intField(f.produced_at, 'produced_at'),
    task_ref: strField(f.task_ref, 'task_ref'),
    payload_ref: strField(f.payload_ref, 'payload_ref'),
    summary: strField(f.summary, 'summary'),
    token_cost: intField(f.token_cost, 'token_cost'),
    raw_token_size: intField(f.raw_token_size, 'raw_token_size'),
    destination: f.destination ?? null,
    state: CAPSULE_STATES.PENDING,
    contract_ref: strField(f.contract_ref, 'contract_ref'),
  });
}

/**
 * 建立 ContextBudget。欄位名照文件 3.3 節,一字不改。
 * source 必填且只能是 PROVIDER_REPORTED 或 ESTIMATED:
 * 拿不到真值就標 ESTIMATED,不准不標、不准假裝是真值(3.8 雷一)。
 */
export function createBudget(fields) {
  const f = fields ?? {};
  if (f.source !== TOKEN_SOURCES.PROVIDER_REPORTED && f.source !== TOKEN_SOURCES.ESTIMATED) {
    throw new TypeError(
      `ContextBudget.source must state PROVIDER_REPORTED or ESTIMATED explicitly, got: ${String(f.source)}`,
    );
  }
  return Object.freeze({
    session_id: strField(f.session_id, 'session_id'),
    window_total: intField(f.window_total, 'window_total'),
    consumed: intField(f.consumed ?? 0, 'consumed'),
    reserved: intField(f.reserved ?? 0, 'reserved'),
    measured_at: intField(f.measured_at, 'measured_at'),
    source: f.source,
  });
}

/** 建立 TaskContract。欄位名照文件 3.3 節,一字不改。 */
export function createContract(fields) {
  const f = fields ?? {};
  const inputs = f.inputs ?? {};
  const outputs = f.outputs ?? {};
  return Object.freeze({
    contract_id: strField(f.contract_id, 'contract_id'),
    inputs: Object.freeze({
      file_globs: Object.freeze([...(inputs.file_globs ?? [])]),
      upstream_artifacts: Object.freeze([...(inputs.upstream_artifacts ?? [])]),
    }),
    outputs: Object.freeze({
      artifact_ids: Object.freeze([...(outputs.artifact_ids ?? [])]),
    }),
    return_shape: f.return_shape ?? null,
    max_return_tokens: intField(f.max_return_tokens, 'max_return_tokens'),
  });
}

/** 剩餘可用 token:window_total − consumed − reserved。 */
export function remainingBudget(budget) {
  return budget.window_total - budget.consumed - budget.reserved;
}

/**
 * 驗證膠囊是否符合契約的 return_shape 與 max_return_tokens。
 * 文件對 ReturnShape 只有欄位名沒有內部規格,這裡實作最小驗證:
 *   一,token_cost 不得超過 max_return_tokens(3.3:硬上限,超過必須先摘要)。
 *   二,return_shape.kind === 'json' 時 summary 必須是合法 JSON;
 *      return_shape.required_fields 有列的欄位必須都在。
 * 呼叫端可用 config.validate_shape 換成自己的驗證器。
 * 回傳 { ok: bool, reasons: string[] },不靜默吞理由。
 */
export function validateReturnShape(capsule, contract) {
  const reasons = [];
  if (capsule.token_cost > contract.max_return_tokens) {
    reasons.push(`token_cost ${capsule.token_cost} exceeds max_return_tokens ${contract.max_return_tokens}`);
  }
  const shape = contract.return_shape;
  if (shape && shape.kind === 'json') {
    let parsed = null;
    try {
      parsed = JSON.parse(capsule.summary);
    } catch {
      reasons.push('return_shape requires JSON but summary is not valid JSON');
    }
    if (parsed && Array.isArray(shape.required_fields)) {
      for (const key of shape.required_fields) {
        if (!(key in parsed)) reasons.push(`summary is missing a field required by return_shape: ${key}`);
      }
    }
  }
  return { ok: reasons.length === 0, reasons };
}

function shapeCheck(capsule, contract, config) {
  const validator = config.validate_shape ?? validateReturnShape;
  return validator(capsule, contract);
}

/**
 * 自動放行判定,照文件 3.4 節:
 * token_cost <= auto_accept_ratio × window_total 且 return_shape 驗證通過。
 * 閾值走 config,不寫死。
 */
export function shouldAutoAccept(capsule, budget, contract, config = DEFAULT_CONFIG) {
  const ratio = config.auto_accept_ratio ?? DEFAULT_CONFIG.auto_accept_ratio;
  if (capsule.token_cost > ratio * budget.window_total) return false;
  return shapeCheck(capsule, contract, config).ok;
}

/** 報價,對應 3.5 節 preview 的輸出欄位。純計算,不改任何狀態。 */
export function quoteCapsule(capsule, budget, config = DEFAULT_CONFIG) {
  const threshold = config.compact_threshold ?? DEFAULT_CONFIG.compact_threshold;
  const before = remainingBudget(budget);
  const after = before - capsule.token_cost;
  return Object.freeze({
    token_cost: capsule.token_cost,
    raw_token_size: capsule.raw_token_size,
    budget_before: before,
    budget_after: after,
    would_trigger_compact: after / budget.window_total < threshold,
  });
}

function withState(capsule, nextState) {
  assertLegalTransition(capsule.state, nextState);
  return Object.freeze({ ...capsule, state: nextState });
}

/** PENDING → PREVIEWED:擁有者查看報價。回傳 { capsule, quote }。 */
export function previewCapsule(capsule, budget, config = DEFAULT_CONFIG) {
  const next = withState(capsule, CAPSULE_STATES.PREVIEWED);
  return { capsule: next, quote: quoteCapsule(capsule, budget, config) };
}

/**
 * 放行。PREVIEWED → ACCEPTED 無條件合法;
 * PENDING → ACCEPTED 只有自動放行條件成立才合法,否則拋錯,不靜默允許。
 * token 進入 reserved(已接受但尚未計入,照 3.3 的欄位語意),
 * 實際計入 consumed 是 provider 回報之後的事,不在這裡假裝發生。
 */
export function acceptCapsule(capsule, budget, contract, config = DEFAULT_CONFIG) {
  if (capsule.state === CAPSULE_STATES.PENDING) {
    if (!shouldAutoAccept(capsule, budget, contract, config)) {
      const { reasons } = shapeCheck(capsule, contract, config);
      throw new Error(
        `Illegal transition: PENDING -> ACCEPTED is only allowed for auto-clear, and this capsule does not qualify` +
          (reasons.length ? `(${reasons.join(';')})` : ' (token_cost exceeds the auto-clear threshold)'),
      );
    }
  }
  const next = withState(capsule, CAPSULE_STATES.ACCEPTED);
  const newBudget = Object.freeze({
    ...budget,
    reserved: budget.reserved + capsule.token_cost,
  });
  return { capsule: next, budget: newBudget };
}

/** PREVIEWED → REJECTED:否決。原始輸出留在外面(payload_ref 不動),預算不變。 */
export function rejectCapsule(capsule) {
  return withState(capsule, CAPSULE_STATES.REJECTED);
}

/** PREVIEWED → SUMMARIZED_AGAIN:要求先壓縮再送。 */
export function requestResummarize(capsule) {
  return withState(capsule, CAPSULE_STATES.SUMMARIZED_AGAIN);
}

/**
 * SUMMARIZED_AGAIN → PENDING:壓縮完成,帶新 summary 與新報價回到佇列重新報價。
 * 產出一顆新膠囊(新 capsule_id、新 token_cost),舊膠囊不可變。
 */
export function requoteCapsule(capsule, { capsule_id, summary, token_cost, produced_at }) {
  assertLegalTransition(capsule.state, CAPSULE_STATES.PENDING);
  return Object.freeze({
    ...capsule,
    capsule_id: strField(capsule_id, 'capsule_id'),
    summary: strField(summary, 'summary'),
    token_cost: intField(token_cost, 'token_cost'),
    produced_at: intField(produced_at, 'produced_at'),
    state: CAPSULE_STATES.PENDING,
  });
}

/**
 * 對應 3.8 雷二的量測函式:給定一批歷史膠囊,算出照目前閾值有幾成需要人工放行。
 * 讓 auto_accept_ratio 可以被量測而不是憑感覺調。
 *
 * @param {Array<object>} capsules
 * @param {object} deps { budget, contractsById: Map|object(contract_ref → contract), config }
 * @returns { total, auto, manual, manual_rate, missing_contract }
 *   查不到契約的膠囊視為需要人工放行(無法驗 return_shape 就不准自動放),
 *   並在 missing_contract 如實計數,不靜默吞掉。
 */
export function manualReviewRate(capsules, { budget, contractsById, config = DEFAULT_CONFIG }) {
  const lookup =
    contractsById instanceof Map ? (ref) => contractsById.get(ref) : (ref) => contractsById?.[ref];
  let auto = 0;
  let missing = 0;
  for (const capsule of capsules) {
    const contract = lookup(capsule.contract_ref);
    if (!contract) {
      missing += 1;
      continue;
    }
    if (shouldAutoAccept(capsule, budget, contract, config)) auto += 1;
  }
  const total = capsules.length;
  const manual = total - auto;
  return Object.freeze({
    total,
    auto,
    manual,
    manual_rate: total === 0 ? 0 : manual / total,
    missing_contract: missing,
  });
}

/**
 * 累計「擋掉了多少原始 token」(3.7 驗收四的核心計算;日期切分由呼叫端用 produced_at 過濾)。
 * ACCEPTED:擋掉 raw_token_size − token_cost(只有摘要進去)。
 * REJECTED:擋掉整個 raw_token_size。
 * 其他狀態還沒定案,不計。
 */
export function blockedRawTokens(capsules) {
  let blocked = 0;
  for (const c of capsules) {
    if (c.state === CAPSULE_STATES.ACCEPTED) blocked += c.raw_token_size - c.token_cost;
    else if (c.state === CAPSULE_STATES.REJECTED) blocked += c.raw_token_size;
  }
  return blocked;
}
