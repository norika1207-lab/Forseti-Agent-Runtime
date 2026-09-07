/**
 * Forseti：效益與負擔
 *
 * 規格書 §15 最後一項:怎麼估生產力效益,對比 Forseti 自己的額外負擔。
 *
 * 這一項比其他九項難,難在效益沒有直接的量測 —— 一次沒有發生的互蓋,
 * 不會在任何地方留下紀錄。所以這裡不假裝算得出淨效益,
 * 它只把兩邊各自能量到的東西並排,並且明說哪一邊是估的。
 *
 * ── 負擔可以量,效益只能估 ────────────────────────────
 *
 * 負擔:每次 hook 的毫秒數乘上次數。這個是真的,量得到。
 * 效益:攔下的撞車次數乘上「一次互蓋要花多久修」。後者是估的,
 *      而且只能由使用者自己給 —— 修一次互蓋要多久,跟專案、跟人有關。
 *
 * 所以這個模組要求呼叫端給那個估值,不內建一個。內建一個數字然後
 * 拿它算出「淨效益為正」,是拿自己編的參數證明自己有用。
 *
 * 零依賴。
 */

export const VERSION = 'overhead@0.1';

/**
 * 算負擔。這一邊是實測的。
 *
 * @param {object} p
 * @param {number} p.perCallMs     每次 hook 的毫秒數(實測值)
 * @param {number} p.calls          總共跑了幾次
 * @param {number} p.processStartMs 其中有多少是程序啟動,不是這個工具的邏輯
 */
export function cost({ perCallMs, calls, processStartMs = null } = {}) {
  if (typeof perCallMs !== 'number' || typeof calls !== 'number') {
    return Object.freeze({ total_ms: null, note: 'No measurement supplied.', version: VERSION });
  }
  const total = perCallMs * calls;
  return Object.freeze({
    total_ms: total,
    per_call_ms: perCallMs,
    calls,
    /**
     * 程序啟動的部分不是這個工具的邏輯造成的,任何 hook 都會付。
     * 分開報是為了讓「換一個更快的工具」跟「不裝 hook」變成兩個不同的選項。
     */
    process_start_ms: processStartMs,
    own_logic_ms: processStartMs == null ? null : (perCallMs - processStartMs) * calls,
    version: VERSION,
  });
}

/**
 * 估效益。這一邊是估的,而且估值必須由呼叫端給。
 *
 * @param {object} p
 * @param {number} p.collisionsBlocked  攔下幾次撞車
 * @param {number|null} p.minutesPerCollision  修一次互蓋要多久。呼叫端給,這裡不內建。
 */
export function benefit({ collisionsBlocked = 0, minutesPerCollision = null } = {}) {
  if (minutesPerCollision == null) {
    return Object.freeze({
      saved_ms: null,
      collisions_blocked: collisionsBlocked,
      /**
       * 不內建這個數字,因為內建一個然後拿它算出「淨效益為正」,
       * 等於拿自己編的參數證明自己有用。
       */
      note: 'No estimate supplied for the cost of one overwrite. This module will not invent one - '
        + 'inventing it and then computing a positive net benefit is proving usefulness with a made-up parameter.',
      version: VERSION,
    });
  }
  return Object.freeze({
    saved_ms: collisionsBlocked * minutesPerCollision * 60_000,
    collisions_blocked: collisionsBlocked,
    minutes_per_collision: minutesPerCollision,
    /** 這一邊是估的。跟量到的負擔並排時,這個標記不可被拿掉。 */
    is_estimate: true,
    version: VERSION,
  });
}

/**
 * 兩邊並排。刻意不給一個「淨效益」的單一數字。
 *
 * 一個把實測的負擔跟估出來的效益相減得到的數字,看起來像實測值,
 * 而它的精度完全由那個估值決定。並排讓看的人自己判斷那個估值合不合理。
 */
export function ledger(costResult, benefitResult) {
  const c = costResult?.total_ms ?? null;
  const b = benefitResult?.saved_ms ?? null;
  return Object.freeze({
    cost_ms: c,
    cost_measured: c !== null,
    benefit_ms: b,
    benefit_estimated: benefitResult?.is_estimate === true,
    /**
     * 兩邊都有值時才給比值,而且明講它一半是估的。
     * 沒有淨效益欄位:那個數字會被當成實測值使用,而它不是。
     */
    ratio: (c && b) ? b / c : null,
    note: b === null
      ? 'Benefit cannot be estimated without a value for what one overwrite costs. '
        + 'The burden side is measured; the benefit side is not, and they must not be subtracted.'
      : 'The cost is measured. The benefit rests entirely on the supplied estimate. '
        + 'No net figure is given, because a net figure would look measured and is not.',
    version: VERSION,
  });
}

/**
 * 一次沒發生的互蓋不會留下紀錄,這是這一節最根本的困難。
 *
 * 唯一誠實的近似:量「被攔下之後,使用者選擇繼續還是取消」。
 * 選擇取消代表那次攔截確實攔到了東西;選擇繼續代表那次是誤攔或必要的覆寫。
 * 這個比例是可以真的量到的,而且它比任何時間估值都硬。
 */
export function interceptOutcomes(records) {
  const list = records ?? [];
  if (!list.length) {
    return Object.freeze({
      rate: null, total: 0,
      note: 'No interceptions recorded. Not evidence of a clean record - evidence of no record.',
      version: VERSION,
    });
  }
  const cancelled = list.filter((r) => r.outcome === 'CANCELLED').length;
  const proceeded = list.filter((r) => r.outcome === 'PROCEEDED').length;
  const undecided = list.length - cancelled - proceeded;
  return Object.freeze({
    total: list.length,
    cancelled,
    proceeded,
    undecided,
    /**
     * 取消率。這是唯一不靠估值的效益指標:
     * 使用者看到警告之後選擇不寫,代表那次攔截攔到了東西。
     */
    rate: (cancelled + proceeded) > 0 ? cancelled / (cancelled + proceeded) : null,
    /** 繼續的那些是誤攔或必要覆寫。誤攔率太高的話這個機制在製造噪音。 */
    false_positive_burden: (cancelled + proceeded) > 0 ? proceeded / (cancelled + proceeded) : null,
    version: VERSION,
  });
}
