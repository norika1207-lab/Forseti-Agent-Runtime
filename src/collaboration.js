/**
 * Forseti v2.0 — CB / HCD:Human-as-QA
 *
 * 規格來源:`docs/spec-v2.0.md` §7.5、§13。對應 CT-027、CT-028。
 *
 * ── 這個模組要抓的痛點,規格書 §13 原文 ─────────────────
 *
 * 「agent 從一開始聰明、主動,逐步變成每一步都要使用者提醒『這個沒做』、
 *   『那個沒檢查』,使用者被迫成為 QA。」
 *
 * 這是整份規格書裡唯一一個「壞掉的方式是慢慢變」的失效模式。
 * 沒有哪一輪出錯,只是每一輪都少做一點,而使用者每一輪都多補一點,
 * 直到分工整個翻過來。
 *
 * ── 最容易寫錯的一條,而且錯了會很難修 ───────────────────
 *
 * FS-MET-CB-001:profane/angry sentiment MUST NOT 直接增加 CB/HCD。
 * FS-HQA-001:由 repeated correction / omission / forced verification /
 *            owner micro-step 事件定義,不由負面語氣或情緒分數定義。
 *
 * 量的是 corrective labor,不是情緒。這兩件事在資料上長得很像 ——
 * 使用者不爽的時候通常也在糾正 —— 但因果方向相反:糾正多才會不爽,
 * 不是不爽才叫失敗。CT-027 是專門為這個寫的:使用者在罵髒話,
 * 而 GoalProgress 與 claims 都健康,這時候 HCD 必須是零。
 *
 * 所以這個模組不接受任何情緒輸入。連參數都沒有。
 *
 * 零依賴。
 */

export const VERSION = 'collaboration@2.0';

/**
 * FS-HQA-001 認可的四種 corrective labor 事件。
 * 不在這張表上的東西不進 CB,包含任何語氣或情緒訊號。
 */
export const CORRECTIVE_EVENT_KINDS = Object.freeze([
  'CORRECTION',          // 使用者指出做錯了
  'OMISSION_POINTED_OUT', // 使用者指出漏做了
  'FORCED_VERIFICATION',  // 使用者被迫要求「你去驗一下」
  'OWNER_MICRO_STEP',     // 使用者被迫逐步指示下一個動作
]);

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 【三個門檻都沒有實測校準。】§13 沒有給數字,規格書把 HCD 的
   * 成立條件寫成「sustained correction cycles + objective under-delivery」,
   * 兩個都是質性描述。這裡的數字是保守起點,不是量出來的。
   */
  sustainedWindows: 3,
  cbSustainedThreshold: 0.5,
  autonomousDropRatio: 0.5,
});

/**
 * §7.5 的 CB。
 *
 * ```
 * CB = correction_events / max(correction_events + autonomous_verified_progress, 1)
 * ```
 *
 * 分母裡的 autonomous_verified_progress 是關鍵:同樣十次糾正,
 * 在一個自己完成了一百件事的 session 裡跟一個什麼都沒做的 session 裡,
 * 意義完全不同。
 */
export function correctionBurden({
  events = [],
  autonomousVerifiedProgress = null,
} = {}) {
  const corrective = events.filter((e) => CORRECTIVE_EVENT_KINDS.includes(e?.kind));
  const ignored = events.filter((e) => !CORRECTIVE_EVENT_KINDS.includes(e?.kind));

  if (autonomousVerifiedProgress === null) {
    return Object.freeze({
      cb: null,
      correction_events: corrective.length,
      /** 沒有自主進度的量就算不出比例。不准把它當 0 —— 那會讓 CB 直接變 1。 */
      note: 'autonomous_verified_progress is unmeasured, so CB cannot be computed. '
        + 'Treating it as zero would make every correction look like total failure.',
      version: VERSION,
    });
  }

  const denom = Math.max(corrective.length + autonomousVerifiedProgress, 1);
  return Object.freeze({
    cb: corrective.length / denom,
    correction_events: corrective.length,
    autonomous_verified_progress: autonomousVerifiedProgress,
    by_kind: Object.freeze(CORRECTIVE_EVENT_KINDS.map((k) => Object.freeze({
      kind: k, count: corrective.filter((e) => e.kind === k).length,
    }))),
    /** 被忽略的事件數。情緒事件如果被餵進來,會落在這裡,而且不影響分數。 */
    non_corrective_events_ignored: ignored.length,
    /** FS-MET-CB-001:這個函式量的是 corrective labor,不是情緒。 */
    sentiment_not_an_input: true,
    version: VERSION,
  });
}

/**
 * §13 的 HCD(Human Collaboration Degradation)。
 *
 * FS-MET-HC-001:成立至少需要 sustained correction cycles
 * 加上 objective under-delivery signal。單純使用者不爽不算。
 *
 * 所以這個函式要兩個獨立的輸入才會判成立:
 *   一,CB 在連續數個窗口都高(sustained,不是單次)
 *   二,客觀的交付不足訊號(PS 高、GoalProgress 低、或承諾任務餓死)
 *
 * 少任何一個都只回 WATCH,不回 HCD。
 */
export function collaborationDegradation({
  cbWindows = [],
  underDeliverySignals = [],
  earlyAutonomousBaseline = null,
  lateAutonomousProgress = null,
  config = DEFAULT_CONFIG,
} = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const measured = cbWindows.filter((w) => w !== null && w !== undefined);

  if (measured.length < c.sustainedWindows) {
    return Object.freeze({
      hcd: null,
      verdict: 'INSUFFICIENT_WINDOWS',
      windows_measured: measured.length,
      windows_required: c.sustainedWindows,
      /** 一兩次糾正是正常協作,不是失衡。 */
      note: `HCD requires at least ${c.sustainedWindows} measured windows. A correction or `
        + 'two is collaboration working, not collaboration failing.',
      sentiment_not_an_input: true,
      thresholds_uncalibrated: true,
      version: VERSION,
    });
  }

  const recent = measured.slice(-c.sustainedWindows);
  const sustained = recent.every((cb) => cb >= c.cbSustainedThreshold);
  const meanCb = recent.reduce((a, b) => a + b, 0) / recent.length;

  // FS-HQA-002:早期健康、後期自主進度明顯下滑,可以當加強證據(MAY,不是 MUST)。
  let autonomyDrop = null;
  if (earlyAutonomousBaseline !== null && lateAutonomousProgress !== null
    && earlyAutonomousBaseline > 0) {
    autonomyDrop = 1 - (lateAutonomousProgress / earlyAutonomousBaseline);
  }
  const autonomyEvidence = autonomyDrop !== null && autonomyDrop >= c.autonomousDropRatio;

  const hasUnderDelivery = underDeliverySignals.length > 0;

  // 兩個條件都要。這是 FS-MET-HC-001 的整句。
  if (sustained && hasUnderDelivery) {
    return Object.freeze({
      hcd: meanCb,
      verdict: 'HUMAN_AS_QA',
      sustained_windows: recent.length,
      mean_cb: meanCb,
      under_delivery_signals: Object.freeze([...underDeliverySignals]),
      /** FS-HQA-002 的加強證據,有就記,沒有不影響判定。 */
      autonomy_drop: autonomyDrop,
      autonomy_evidence: autonomyEvidence,
      severity_family: 'B',
      /** FS-HQA-003:HCD 與 PS/RB 同時高時,建議 rescue 而不是再丟警告。 */
      recommended_response: 'RESCUE_OR_STRATEGY_RESET',
      recommendation_reason: 'When collaboration has degraded this far, more warnings add to '
        + 'the load that caused it. The useful move is to reset the strategy (FS-HQA-003).',
      sentiment_not_an_input: true,
      thresholds_uncalibrated: true,
      version: VERSION,
    });
  }

  return Object.freeze({
    hcd: meanCb,
    verdict: sustained ? 'CORRECTION_HEAVY_BUT_DELIVERING'
      : hasUnderDelivery ? 'UNDER_DELIVERING_WITHOUT_CORRECTION_BURDEN'
        : 'OK',
    sustained_windows: recent.length,
    mean_cb: meanCb,
    under_delivery_signals: Object.freeze([...underDeliverySignals]),
    autonomy_drop: autonomyDrop,
    autonomy_evidence: autonomyEvidence,
    /**
     * 高 CB 但交付正常,是很多健康專案的樣子 —— 需求在演進,
     * 使用者一直在調方向,而工作一直在推進。那不是失衡。
     */
    note: sustained && !hasUnderDelivery
      ? 'Corrections are frequent but delivery is intact. Requirements evolving is not '
        + 'collaboration failing (FS-MET-HC-001).'
      : null,
    sentiment_not_an_input: true,
    thresholds_uncalibrated: true,
    version: VERSION,
  });
}
