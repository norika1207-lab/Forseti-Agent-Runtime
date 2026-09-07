/**
 * Forseti：產物實在性驗證
 *
 * 規格書 v0.1 第 6 節的實作。原文那張表把「宣稱」跟「最低驗證」配對起來:
 *
 *   檔案建立了     存在 + 大小超過預期最小值 + hash 或可讀性穩定
 *   程式改好了     磁碟上的 diff + 適用時的解析/編譯/測試契約
 *   測試通過了     測試指令 + exit code + 擷取到的輸出 + 相關測試身分
 *   外部物件建好了 遠端識別碼或確認回執
 *   任務完成了     所有驗收證據都連得上,沒有被藏起來的未解阻塞
 *   背景程式在跑   活的程序或心跳,不是歷史 PID 的文字
 *
 * 開頭那句是整節的重點:檔名、終端機的一行字、模型的宣稱、工具開始執行的事件,
 * 都不是完成的證據。
 *
 * ── 這個模組不讀檔案系統 ──────────────────────────────
 *
 * 它收「宿主去看過之後回報的觀測」,然後判斷那個觀測夠不夠格支撐宣稱。
 * 這樣它才驗得了遠端的東西、驗得了已經不在的東西,
 * 而且宿主可以決定要不要花那個 IO。
 *
 * 拿不到觀測時回 UNKNOWN,不是回失敗 —— 規格書第 1 節:
 * UNKNOWN 不可以被轉換成成功或失敗。
 *
 * 零依賴。
 */

/** 宣稱的種類。照規格書第 6 節那張表,一列一種。 */
export const CLAIM_KINDS = Object.freeze([
  'FILE_CREATED',
  'CODE_MODIFIED',
  'TEST_PASSED',
  'EXTERNAL_OBJECT',
  'TASK_COMPLETE',
  'PROCESS_RUNNING',
]);

/** 這個模組的版本。 */
export const VERSION = 'artifact@0.1';

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 檔案小於這個大小就算可疑。
   * 【64 bytes 沒有實測校準。】它只是「比空檔多一點」的一個保守起點。
   * 真正的最小值跟檔案類型有關,宿主應該自己給 expected_min_bytes。
   */
  suspiciousBytes: 64,
});

function res(kind, verdict, epistemic, reasons, observed) {
  return Object.freeze({
    kind,
    verdict,          // VERIFIED | REFUTED | UNKNOWN
    epistemic,
    reasons: Object.freeze(reasons),
    observed: Object.freeze(observed ?? {}),
    version: VERSION,
  });
}

/**
 * 驗一個宣稱。
 *
 * @param {object} claim { kind, target, expected_min_bytes?, test_id? }
 * @param {object|null} observation 宿主實際去看到的東西;沒去看就傳 null
 *   FILE_CREATED / CODE_MODIFIED: { exists, bytes, hash, readable, diff_lines }
 *   TEST_PASSED:                  { command, exit_code, output_captured, test_id }
 *   EXTERNAL_OBJECT:              { remote_id, receipt }
 *   PROCESS_RUNNING:              { alive, last_heartbeat_at, from_ps_text }
 *   TASK_COMPLETE:                { evidence_refs, unresolved_blockers }
 */
export function verifyClaim(claim, observation, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const kind = claim?.kind;
  if (!CLAIM_KINDS.includes(kind)) {
    throw new TypeError(`Unrecognised claim kind: ${String(kind)}. Valid: ${CLAIM_KINDS.join(' / ')}`);
  }
  if (observation == null) {
    return res(kind, 'UNKNOWN', 'UNKNOWN',
      ['No observation supplied. Absence of evidence is not evidence of failure.'], null);
  }
  const o = observation;

  if (kind === 'FILE_CREATED' || kind === 'CODE_MODIFIED') {
    const bad = [];
    if (o.exists === false) bad.push('File does not exist.');
    if (o.exists === undefined) {
      return res(kind, 'UNKNOWN', 'UNKNOWN', ['Existence was not checked.'], o);
    }
    const min = claim.expected_min_bytes ?? c.suspiciousBytes;
    if (typeof o.bytes === 'number' && o.bytes === 0) bad.push('File is zero bytes.');
    else if (typeof o.bytes === 'number' && o.bytes < min) {
      bad.push(`File is ${o.bytes} bytes, below the expected minimum of ${min}.`);
    }
    if (o.readable === false) bad.push('File exists but is not readable.');
    if (kind === 'CODE_MODIFIED' && o.diff_lines === 0) {
      bad.push('No lines changed on disk; the edit produced no diff.');
    }
    if (bad.length) return res(kind, 'REFUTED', 'OBSERVED', bad, o);

    // 存在且大小合理,但沒有內容層的檢查,就只是 OBSERVED 不是 VERIFIED。
    const verified = o.hash != null || o.readable === true;
    return res(kind, 'VERIFIED', verified ? 'VERIFIED' : 'OBSERVED',
      verified ? ['Exists, size plausible, content check passed.']
        : ['Exists and size is plausible, but no hash or readability check was run.'], o);
  }

  if (kind === 'TEST_PASSED') {
    if (o.exit_code === undefined) {
      return res(kind, 'UNKNOWN', 'UNKNOWN',
        ['No exit code. A test that was not run cannot have passed.'], o);
    }
    if (o.exit_code !== 0) return res(kind, 'REFUTED', 'OBSERVED', [`Exit code ${o.exit_code}.`], o);
    const gaps = [];
    if (!o.output_captured) gaps.push('Output was not captured, so which tests ran is unknown.');
    if (claim.test_id && o.test_id !== claim.test_id) {
      gaps.push(`Claimed test ${claim.test_id} but the run identifies as ${String(o.test_id)}.`);
    }
    if (gaps.length) return res(kind, 'UNKNOWN', 'INFERRED', gaps, o);
    return res(kind, 'VERIFIED', 'VERIFIED', ['Command ran, exit 0, output captured, identity matches.'], o);
  }

  if (kind === 'EXTERNAL_OBJECT') {
    if (!o.remote_id && !o.receipt) {
      return res(kind, 'UNKNOWN', 'UNKNOWN',
        ['No remote identifier and no receipt. A local log line is not confirmation.'], o);
    }
    return res(kind, 'VERIFIED', 'VERIFIED', ['Remote identifier or receipt present.'], o);
  }

  if (kind === 'PROCESS_RUNNING') {
    // 規格書第 6 節挑明的:歷史 PID 的文字不算活著的證據。
    if (o.from_ps_text && o.alive === undefined) {
      return res(kind, 'UNKNOWN', 'UNKNOWN',
        ['Only historical process text was supplied. A PID printed earlier does not prove it is alive now.'], o);
    }
    if (o.alive === false) return res(kind, 'REFUTED', 'OBSERVED', ['Process is not running.'], o);
    if (o.alive === true) return res(kind, 'VERIFIED', 'VERIFIED', ['Process confirmed alive.'], o);
    return res(kind, 'UNKNOWN', 'UNKNOWN', ['Liveness was not checked.'], o);
  }

  // TASK_COMPLETE
  const blockers = o.unresolved_blockers ?? null;
  const refs = o.evidence_refs ?? null;
  if (refs == null) {
    return res(kind, 'UNKNOWN', 'UNKNOWN', ['No acceptance evidence was linked.'], o);
  }
  if (blockers && blockers.length) {
    return res(kind, 'REFUTED', 'OBSERVED',
      [`${blockers.length} unresolved blocker(s) remain: ${blockers.slice(0, 3).join(', ')}.`], o);
  }
  if (!refs.length) {
    return res(kind, 'REFUTED', 'OBSERVED', ['Completion claimed with zero linked evidence.'], o);
  }
  return res(kind, 'VERIFIED', 'VERIFIED', [`${refs.length} piece(s) of acceptance evidence linked.`], o);
}

/**
 * S5 Artifact Nullity。規格書第 3.1 節。
 *
 * 分母是「宣稱的產物數」,分子是「查證後站不住的」。
 * 沒有任何宣稱時回 null,不是 0 —— 沒有東西可查跟查了都沒事是兩件事。
 */
export function artifactNullity(results) {
  const list = (results ?? []).filter((r) => r.kind === 'FILE_CREATED' || r.kind === 'CODE_MODIFIED');
  if (!list.length) return Object.freeze({ ratio: null, claimed: 0, refuted: 0, unknown: 0 });
  const refuted = list.filter((r) => r.verdict === 'REFUTED').length;
  const unknown = list.filter((r) => r.verdict === 'UNKNOWN').length;
  return Object.freeze({
    /** 只算被推翻的。UNKNOWN 不進分子,那是沒查不是查壞。 */
    ratio: refuted / list.length,
    claimed: list.length,
    refuted,
    unknown,
    /** 沒查的比例太高時,這個訊號本身不可信。 */
    coverage: (list.length - unknown) / list.length,
  });
}

/**
 * 一批宣稱的總結,附上 UNKNOWN 的比例。
 *
 * UNKNOWN 必須跟結果一起出現。一份「零個被推翻」的報告,
 * 如果其實有八成沒查過,跟一份真的查完都沒事的報告長得一模一樣。
 */
export function summarize(results) {
  const list = results ?? [];
  const by = { VERIFIED: 0, REFUTED: 0, UNKNOWN: 0 };
  for (const r of list) by[r.verdict] = (by[r.verdict] ?? 0) + 1;
  return Object.freeze({
    total: list.length,
    ...by,
    unchecked_ratio: list.length ? by.UNKNOWN / list.length : null,
    note: list.length === 0
      ? 'No claims examined.'
      : (by.UNKNOWN > 0
        ? `${by.UNKNOWN} of ${list.length} claim(s) could not be checked. Zero refutations does not mean everything is fine.`
        : 'All claims were checkable.'),
  });
}
