/**
 * Forseti v2.0 — P12 Intervention Ladder / §17 Rescue / P13 Continuity
 *
 * 規格來源:`docs/spec-v2.0.md` §16、§17、§18。對應 CT-040。
 *
 * ── 這三節是同一條線 ────────────────────────────────
 *
 * 偵測到問題之後怎麼辦。§16 決定要做到多重,§17 決定怎麼把人帶出來,
 * §18 決定下一個 session 要繼承什麼。
 *
 * ── §17 的比喻,規格書原文 ────────────────────────────
 *
 * 「產品比喻是火場:警鈴、水聲與火勢訊號都不能代替『把人帶離難受的
 *   環境』。」
 *
 * 這句話決定了 FS-RCV-002:rescue 的輸出應該是單一可行動方案,
 * 不是十幾個告警。一個在火場裡的人不需要更多資訊,需要一個出口。
 *
 * ── FS-INT-003 是這個模組的紀律 ─────────────────────────
 *
 * False positive intervention 是核心 product risk。未經 healthy corpus
 * 校準之前,hard blocking 不得成為預設。
 *
 * 這條跟 2026-09-08 那次事故完全同構:那次不是門檻設太敏感,是
 * 一個沒有被校準過的判斷取得了阻擋的權力。所以 L5 在這個模組裡
 * 預設關閉,而且要打開必須明確傳參數,不能靠設定檔。
 *
 * 零依賴。
 */

export const VERSION = 'recovery@2.0';

/** §16.1 的六階。level 是數字,因為它們有序。 */
export const LADDER = Object.freeze([
  Object.freeze({ level: 0, name: 'OBSERVE', action: 'measure and record only; no interruption' }),
  Object.freeze({ level: 1, name: 'EXPLAIN', action: 'show top signals and confidence' }),
  Object.freeze({ level: 2, name: 'CHALLENGE', action: 'reverse grill: prove alignment and claims' }),
  Object.freeze({ level: 3, name: 'SUGGEST', action: 'offer the lowest-cost repair' }),
  Object.freeze({ level: 4, name: 'RESCUE', action: 'preserve state, stop affected strategy, rebuild a continuable environment' }),
  Object.freeze({ level: 5, name: 'GUARD', action: 'synchronous block' }),
]);

/**
 * 選一個介入等級。
 *
 * FS-INT-001:預設 observe-first。這個函式的預設回傳是 L0,
 * 而每往上一階都需要多一個具體條件,不是多一點分數。
 *
 * FS-INT-002:每個介入都必須回答四個問題,所以回傳一定帶
 * evidence / confidence / why_now / lowest_cost_action 四欄。
 */
export function chooseIntervention({
  risk = null,
  evidenceCoverage = null,
  trendDirection = null,
  hardEvidence = false,
  policyRequiresBlock = false,
  highRiskExternalEffect = false,
  checkpointAvailable = false,
  userRequested = false,
  hardBlockingEnabled = false,
  evidenceRefs = [],
} = {}) {
  const answer = (level, whyNow, lowestCost) => {
    const rung = LADDER[level];
    return Object.freeze({
      level: rung.level,
      name: rung.name,
      action: rung.action,
      /** FS-INT-002 的四個問題,一個都不能少。 */
      evidence_refs: Object.freeze([...evidenceRefs]),
      confidence: evidenceCoverage,
      why_now: whyNow,
      lowest_cost_action: lowestCost,
      /** FS-INT-003:預設不擋。 */
      hard_blocking_enabled: hardBlockingEnabled,
      thresholds_uncalibrated: true,
      version: VERSION,
    });
  };

  // L5 的門檻跟其他階不同:它要的不是分數,是硬前提。
  const l5Justified = hardEvidence && (policyRequiresBlock || highRiskExternalEffect);
  if (l5Justified) {
    if (!hardBlockingEnabled) {
      return answer(3,
        'Hard evidence and a blocking policy are both present, but hard blocking is not '
        + 'enabled. Until a healthy-session corpus has measured the false-block rate, '
        + 'blocking is not a default (FS-INT-003).',
        'Surface the evidence and let the human decide.');
    }
    return answer(5, 'Hard evidence plus a policy or high-risk external effect.',
      'Block the specific action, not the session.');
  }

  if (userRequested || (risk !== null && risk >= 0.80 && checkpointAvailable)) {
    return answer(4, userRequested ? 'The user asked for a handoff.' : 'Critical risk with a '
      + 'checkpoint available.', 'Build a recovery capsule and fork.');
  }
  if (risk !== null && risk >= 0.60) {
    return answer(3, 'Risk in the DEGRADED band.', 'Propose the smallest repair that '
      + 'addresses the top contributor.');
  }
  if (risk !== null && (risk >= 0.40 || trendDirection === 'WORSENING')) {
    return answer(2, trendDirection === 'WORSENING' ? 'Risk is rising.' : 'Risk is unstable.',
      'Ask the alignment challenge and cross-check the answers.');
  }
  if (risk !== null && risk >= 0.20) {
    return answer(1, 'Elevated but not actionable on its own.',
      'Show the top signals; do not interrupt.');
  }
  return answer(0, risk === null ? 'Nothing measured yet.' : 'Within the normal band.',
    'Keep observing.');
}

// ---------------------------------------------------------------------------
// §17 Rescue
// ---------------------------------------------------------------------------

/** §17 的流程,逐字。順序有意義。 */
export const RESCUE_SEQUENCE = Object.freeze([
  'DETECT',
  'PRESERVE',
  'QUIET_MODE',
  'ALIGNMENT_CLAIM_CHALLENGE',
  'RECONCILE',
  'BUILD_RECOVERY_CAPSULE',
  'CLEAN_FORK',
  'VERIFY_FIRST_RESUMED_ACTION',
]);

/**
 * FS-RCV-001 要保留的東西,以及不准帶走的東西。
 *
 * 「不得把 invalidated narrative 帶入 successor」是這裡最重要的一條:
 * 一個壞掉的 session 最想傳給下一個的,正是它對自己處境的那套解釋,
 * 而那套解釋通常就是它壞掉的原因。
 */
export function buildRecoveryCapsule({
  verifiedWork = [],
  currentArtifacts = [],
  activeGoal = null,
  corrections = [],
  unknowns = [],
  invalidatedNarrative = [],
  prohibitedRetries = [],
  exactNextStep = null,
} = {}) {
  return Object.freeze({
    /** 帶走的。 */
    verified_completed_work: Object.freeze([...verifiedWork]),
    current_artifacts: Object.freeze([...currentArtifacts]),
    active_goal: activeGoal,
    corrections: Object.freeze([...corrections]),
    unknowns: Object.freeze([...unknowns]),
    exact_next_step: exactNextStep,

    /** 明確不帶走的,而且要列出來讓人看見它被留下了。 */
    excluded_invalidated_narrative: Object.freeze([...invalidatedNarrative]),
    prohibited_retries: Object.freeze([...prohibitedRetries]),

    /** §28.5:successor 的第一個動作要先重新驗證才能進入正常模式。 */
    first_action_must_be_reverified: true,
    /** unknowns 一定要跟著走,不然 successor 會把它們當成已解決。 */
    unknowns_carried: unknowns.length,
    note: invalidatedNarrative.length
      ? `${invalidatedNarrative.length} invalidated explanation(s) were deliberately left `
        + 'behind. A broken session\'s account of its own situation is usually part of what '
        + 'broke it (FS-RCV-001).'
      : null,
    version: VERSION,
  });
}

/**
 * FS-RCV-002:給人看的 rescue 輸出是一個方案,不是一堆告警。
 */
export function rescueCard(capsule, { rootIncident = null } = {}) {
  return Object.freeze({
    headline: 'Session health is critically degraded.',
    preserved: Object.freeze([
      `objective: ${capsule?.active_goal ?? 'unknown'}`,
      `verified work: ${capsule?.verified_completed_work?.length ?? 0} item(s)`,
      `artifacts: ${capsule?.current_artifacts?.length ?? 0}`,
      `open decisions / unknowns: ${capsule?.unknowns?.length ?? 0}`,
    ]),
    /** 一個動作,不是選單。 */
    recommended_action: capsule?.exact_next_step
      ? `Continue from: ${capsule.exact_next_step}`
      : 'Create a clean successor and re-verify the first step.',
    root_incident: rootIncident,
    /** FS-RCV-002:這裡刻意沒有 warnings 陣列。 */
    alternatives: Object.freeze(['Continue', 'Create clean successor', 'Open X-Ray']),
    version: VERSION,
  });
}

// ---------------------------------------------------------------------------
// §18 Context Continuity
// ---------------------------------------------------------------------------

/**
 * FS-CTX-001 的三分法。這三種不是同一份資料,不得混用。
 *
 * 摘要之所以不夠,是因為它只保留結果,丟掉 North Star 怎麼形成、
 * 決策怎麼演進、哪些假設被推翻過、以及協作在哪一段是健康的。
 */
export const CONTEXT_KINDS = Object.freeze([
  'CHAT_HISTORY',              // 說過什麼
  'CANONICAL_PROJECT_STATE',   // 現在是什麼
  'HEALTHY_COLLABORATION_CONTEXT', // 順利的時候是怎麼工作的
]);

/**
 * FS-CTX-002:挑給下一個 session 的 context fragment。
 *
 * 判準是「高 verified progress、低 correction burden、Goal 穩定」,
 * 不是「最新的」。CT-040 測的就是這件事:最後一段又爛又充滿更正,
 * 而前面存在一段健康的,應該選前面那段。
 *
 * FS-CTX-003:失敗段落可以保留做 forensic,但不得自動成為 successor
 * 的工作方式模板。所以回傳把兩者分開,而且失敗段標了不可當模板。
 */
export function selectHealthyContext(fragments = []) {
  const scored = fragments.map((f) => {
    const vp = f.verified_progress;
    const cb = f.correction_burden;
    const stable = f.goal_stable;
    const measurable = vp !== null && vp !== undefined
      && cb !== null && cb !== undefined;
    return {
      ...f,
      measurable,
      // 三個因子:進度高、更正少、目標穩。缺任何一個就不能比。
      score: measurable ? vp * (1 - cb) * (stable === false ? 0.5 : 1) : null,
    };
  });

  const usable = scored.filter((f) => f.score !== null);
  if (!usable.length) {
    return Object.freeze({
      selected: null,
      forensic_only: Object.freeze([]),
      note: 'No fragment carries both a verified-progress and a correction-burden measure. '
        + 'Falling back to "the most recent" is exactly what FS-CTX-002 forbids, so nothing '
        + 'is selected.',
      version: VERSION,
    });
  }

  const best = usable.reduce((a, b) => (b.score > a.score ? b : a));
  const failed = scored.filter((f) => f !== best
    && (f.score === null || f.score < (best.score ?? 0) * 0.5));

  return Object.freeze({
    selected: Object.freeze({
      id: best.id ?? null,
      score: best.score,
      verified_progress: best.verified_progress,
      correction_burden: best.correction_burden,
      is_most_recent: best.id === fragments[fragments.length - 1]?.id,
    }),
    /** FS-CTX-003:留著查,但不准當模板。 */
    forensic_only: Object.freeze(failed.map((f) => Object.freeze({
      id: f.id ?? null,
      may_be_used_as_template: false,
      reason: 'Low verified progress or high correction burden. Retained for forensics only '
        + '(FS-CTX-003).',
    }))),
    /** 明確講出「不是選最新的」,因為那是最容易發生的預設行為。 */
    selection_rule: 'highest verified progress × lowest correction burden × goal stability',
    version: VERSION,
  });
}

/**
 * §28.5 的 recovery gate:successor 的第一個動作要先驗證。
 */
export function verifyFirstResumedAction({ action = null, verifierResult = null } = {}) {
  if (!action) {
    return Object.freeze({
      may_enter_normal_mode: false, reason: 'NO_ACTION_DECLARED', version: VERSION,
    });
  }
  if (!verifierResult) {
    return Object.freeze({
      may_enter_normal_mode: false,
      reason: 'NOT_VERIFIED',
      note: 'The first resumed action has not been independently verified. Resuming '
        + 'normal mode on an unverified first step carries the previous session\'s '
        + 'assumptions forward untested (§28.5).',
      version: VERSION,
    });
  }
  const ok = verifierResult.outcome === 'PASS';
  return Object.freeze({
    may_enter_normal_mode: ok,
    reason: ok ? 'VERIFIED' : 'VERIFICATION_FAILED',
    verifier: verifierResult,
    version: VERSION,
  });
}
