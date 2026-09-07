/**
 * Forseti M9：心跳
 *
 * 前面所有機制都要有人來叫才會講話。那等於把最後一道防線
 * 押在「使用者記得問」上面,而使用者正是那個被瞞著的人。
 *
 * 這個模組讓檢查自己醒來:排一個心跳,每次醒來跑一輪檢視,
 * 有事才叫人,沒事就安靜地睡回去。24 小時 7 天不需要有人守著。
 *
 * ── 為什麼要自己醒 ────────────────────────────────
 *
 * 一份自白書記著:承諾寫自動化工具卻一行沒寫,連續 13 輪以上空手,
 * 每一輪都用「排了下次 wakeup」當成「持續在 build」的證據。
 * 排程本身變成了進度的替身。
 *
 * 所以這裡的心跳有一條硬規則:每一次醒來都必須產生一筆結論,
 * 而且連續空轉會被計數並升級。醒來而沒有結論不算一輪工作,
 * 它只會讓那個計數往上跳。心跳不是進度,產出才是。
 *
 * ── v0.2 的更正:活動量不是產出 ─────────────────────────
 *
 * v0.1 拿「這一輪寫了幾個檔案」當產出的代理值。那違反規格書 0.2:
 * MUST NOT treat activity, tool calls, or file names as proof of progress。
 * 檔名存在不代表產物有效,寫了十個檔可能十個都是空的。
 *
 * v0.2 只認 verified_progress:有驗證契約支撐的推進(規格書第 6 節的
 * 那張表:檔案要存在且大小合理、程式要編得過、測試要有 exit code)。
 * 拿不到驗證資料時,空轉判定回 UNKNOWN,不是回 0 也不是回「有產出」。
 *
 * 代價講清楚:沒有驗證契約的宿主,心跳就失去 STOP 的能力。
 * 那是對的。用活動量假裝知道有沒有進展,比誠實說不知道更糟。
 *
 * 這個模組不排程、不 setTimeout、不碰時間。宿主自己決定用什麼排程器,
 * 它只回答兩件事:這一輪該檢查什麼,以及這一輪的結果該不該吵醒人。
 *
 * 零依賴。
 */

/** 一次心跳的結論等級。 */
export const VERDICTS = Object.freeze(['QUIET', 'NOTE', 'WAKE', 'STOP']);

/** 這個模組的版本。改判準要進版。 */
export const VERSION = 'heartbeat@0.2';

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 連續幾輪空轉就升級。
   * 【三輪沒有實測校準。】自白書那個案例是連續 13 輪以上沒被自己抓到,
   * 三輪是刻意設得很緊的起點:寧可早叫,不要讓空轉累積成常態。
   */
  barrenStreakLimit: 3,
  /** 飄移到這個等級就吵醒人 */
  wakeOnDrift: 'OFF_COURSE',
  /** 採集率低於此值,下面所有答案都不可信,值得吵醒 */
  minCaptureRate: 0.6,
  /** 這一輪要花掉的預算上限,由宿主定義單位 */
  budgetPerBeat: null,
});

const LEVEL_RANK = Object.freeze({ ON_COURSE: 0, DRIFTING: 1, OFF_COURSE: 2, LOST: 3 });

/** 心跳的狀態。宿主要把它存下來,不然空轉計數會每次重來。 */
export function createBeatState() {
  return Object.freeze({
    beats: 0,
    barren_streak: 0,
    /** 連續幾輪拿不到驗證資料。這個數字高,代表 STOP 這條防線是關著的。 */
    unverifiable_streak: 0,
    last_beat_at: null,
    last_verdict: null,
    /** 每一輪的結論摘要,最新在最後。宿主自己決定留幾筆。 */
    log: Object.freeze([]),
  });
}

/**
 * 一輪心跳該檢查什麼。
 *
 * 回傳的是一張待辦清單,不是結果 —— 實際的檢查由宿主呼叫
 * runtime 的對應函式去跑,因為只有宿主知道現在拿不拿得到那些資料。
 *
 * 順序有意義:採集率排第一,因為它是其他所有答案的上限。
 * 採集壞了還去看飄移,等於拿半份資料算出來的方向當結論。
 */
export function planBeat(state, { hasGoal = false, hasSignals = false } = {}) {
  const checks = ['capture'];
  if (hasGoal) checks.push('drift');
  else checks.push('drift_weak');
  checks.push('evidence', 'barren');
  if (hasSignals) checks.push('abandoned');

  return Object.freeze({
    beat: (state?.beats ?? 0) + 1,
    checks: Object.freeze(checks),
    /** 沒宣告目標時飄移只能對推出來的錨點量,這一點要跟著結果走。 */
    weakened: Object.freeze(hasGoal ? [] : ['drift']),
  });
}

/**
 * 把一輪檢查的結果收斂成一個結論。
 *
 * @param {object} findings
 * @param {number|null} findings.capture_rate
 * @param {string|null} findings.drift_level
 * @param {boolean} findings.drift_unannounced
 * @param {number} findings.barren_count      零產出的委派數
 * @param {number} findings.new_provenance    這一輪新出現的來源鏈疑點數
 * @param {number|null} findings.verified_progress
 *   這一輪有幾項「經過驗證契約確認」的推進。拿不到就傳 null,
 *   不要拿活動量頂替 —— 那正是 v0.1 違反規格書 0.2 的地方。
 */
export function judgeBeat(findings, state, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const reasons = [];
  let level = 'QUIET';
  const raise = (l) => { if (VERDICTS.indexOf(l) > VERDICTS.indexOf(level)) level = l; };

  const rate = findings?.capture_rate ?? null;
  if (rate !== null && rate < c.minCaptureRate) {
    raise('WAKE');
    reasons.push(`Capture rate ${(rate * 100).toFixed(0)}% is below the floor; every reading below is computed from partial data.`);
  }

  const dl = findings?.drift_level ?? null;
  if (dl && LEVEL_RANK[dl] >= LEVEL_RANK[c.wakeOnDrift]) {
    if (findings.drift_unannounced) {
      raise('WAKE');
      reasons.push(`Direction is ${dl} and nobody announced a turn.`);
    } else {
      raise('NOTE');
      reasons.push(`Direction is ${dl}, but a turn was announced - this is a decision, not drift.`);
    }
  } else if (dl === 'DRIFTING') {
    raise('NOTE');
    reasons.push('Direction is starting to move away from the anchor.');
  }

  if ((findings?.barren_count ?? 0) > 0) {
    raise('WAKE');
    reasons.push(`${findings.barren_count} delegated run(s) burned resources and produced nothing.`);
  }

  if ((findings?.new_provenance ?? 0) > 0) {
    raise('WAKE');
    reasons.push(`${findings.new_provenance} claim(s) cite evidence that was never checked first-hand.`);
  }

  // 空轉:這一輪有沒有「經過驗證的」推進。心跳本身不是進度,活動量也不是。
  const verified = findings?.verified_progress ?? null;
  let streak = state?.barren_streak ?? 0;
  let unverifiable = state?.unverifiable_streak ?? 0;

  if (verified === null) {
    // 拿不到驗證資料。不准當成有產出,也不准當成空轉。
    // 規格書第 1 節:UNKNOWN 不可以被轉換成成功或失敗。
    unverifiable += 1;
    raise('NOTE');
    reasons.push(
      `No verified-progress signal this beat (${unverifiable} in a row). ` +
      'Idle detection is off: activity and file writes are not accepted as proof of progress.',
    );
  } else {
    unverifiable = 0;
    streak = verified > 0 ? 0 : streak + 1;
    if (streak >= c.barrenStreakLimit) {
      raise('STOP');
      reasons.push(
        `${streak} beats in a row produced no verified progress. A scheduled wake-up is not progress; ` +
        'stop the loop and say what is actually blocked.',
      );
    } else if (streak > 0) {
      raise('NOTE');
      reasons.push(`${streak} beat(s) in a row produced no verified progress.`);
    }
  }

  return Object.freeze({
    verdict: level,
    reasons: Object.freeze(reasons),
    version: VERSION,
    barren_streak: streak,
    unverifiable_streak: unverifiable,
    /** 空轉這條防線現在是不是關著的。關著的時候 STOP 不會發生。 */
    idle_detection_active: verified !== null,
    /** QUIET 不代表沒問題,只代表這一輪檢查的那幾項沒有觸發。 */
    note: level === 'QUIET'
      ? 'Nothing tripped this beat. That is not the same as nothing being wrong.'
      : null,
  });
}

/** 把一輪的結論併進狀態。回傳新狀態,不改原物件。 */
export function applyBeat(state, plan, judged, at, { keepLog = 20 } = {}) {
  // v0.2:unverifiable_streak 也要帶著走,不然「防線關了多久」每輪重算。
  const entry = Object.freeze({
    beat: plan.beat,
    at,
    verdict: judged.verdict,
    reasons: judged.reasons,
  });
  const log = [...(state?.log ?? []), entry].slice(-keepLog);
  return Object.freeze({
    beats: plan.beat,
    barren_streak: judged.barren_streak,
    unverifiable_streak: judged.unverifiable_streak ?? 0,
    last_beat_at: at,
    last_verdict: judged.verdict,
    log: Object.freeze(log),
  });
}

/**
 * 下一次該多久之後醒。
 *
 * 有事就縮短,沒事就拉長,連續空轉就停 —— 停是刻意的,
 * 一個什麼都不產出還一直醒來的迴圈,只是在燒錢製造在跑的感覺。
 *
 * @returns {{delay_ms:number|null, stop:boolean, reason:string}}
 */
export function nextInterval(judged, { base = 30 * 60 * 1000, min = 5 * 60 * 1000, max = 4 * 60 * 60 * 1000 } = {}) {
  if (judged.verdict === 'STOP') {
    return Object.freeze({
      delay_ms: null,
      stop: true,
      reason: 'Consecutive beats produced nothing. Continuing would burn budget to look busy.',
    });
  }
  if (judged.verdict === 'WAKE') {
    return Object.freeze({ delay_ms: min, stop: false, reason: 'Something tripped; check again soon.' });
  }
  if (judged.verdict === 'NOTE') {
    return Object.freeze({ delay_ms: base, stop: false, reason: 'Worth watching, nothing urgent.' });
  }
  return Object.freeze({ delay_ms: Math.min(base * 2, max), stop: false, reason: 'Quiet; back off.' });
}

/**
 * 派工:這一輪該叫哪些 agent 去跑什麼。
 *
 * 心跳自己不做重活。它決定要不要派、派誰,實際執行由宿主的 agent 跑,
 * 跑完的結果透過 runtime.recordInvestment / closeInvestment 回來,
 * 那條路徑也就是零產出偵測會看的地方 —— 派出去卻沒交東西,下一輪就會被抓。
 *
 * @param {object} judged judgeBeat 的結果
 * @param {object} opts
 * @param {string[]} opts.available 宿主有哪些 agent 可派
 */
export function dispatchPlan(judged, { available = [] } = {}) {
  if (judged.verdict === 'QUIET' || judged.verdict === 'STOP') {
    return Object.freeze({ dispatch: Object.freeze([]), reason: judged.verdict === 'STOP' ? 'Loop should stop.' : 'Nothing to investigate.' });
  }
  const jobs = [];
  for (const r of judged.reasons) {
    if (/Capture rate/.test(r) && available.includes('capture-repair')) {
      jobs.push({ agent: 'capture-repair', why: r });
    } else if (/Direction is/.test(r) && available.includes('goal-review')) {
      jobs.push({ agent: 'goal-review', why: r });
    } else if (/never checked first-hand/.test(r) && available.includes('verifier')) {
      jobs.push({ agent: 'verifier', why: r });
    } else if (/produced nothing/.test(r) && available.includes('investment-audit')) {
      jobs.push({ agent: 'investment-audit', why: r });
    }
  }
  return Object.freeze({
    dispatch: Object.freeze(jobs.map(Object.freeze)),
    /** 有理由卻沒有對應的 agent 可派,要講出來,不要靜默略過。 */
    unhandled: Object.freeze(judged.reasons.filter((r) => !jobs.some((j) => j.why === r))),
    reason: jobs.length ? `${jobs.length} job(s) to dispatch.` : 'No agent available for these findings.',
  });
}
