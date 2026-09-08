/**
 * Forseti：過早交還發言權
 *
 * 這個形狀是擁有者指出來的,不是工具發現的,而且它在自我審計表上
 * 缺席了十七輪。她的原話裡出現最多次的一句是「繼續」。
 *
 * ── 為什麼 followthrough.js 抓不到 ────────────────────
 *
 * followthrough 抓的是「說了要做,然後沒做」。用它掃寫出 Forseti 的
 * 那個 session,兌現率 91%,只有三筆未兌現 —— 而同一個 session 裡,
 * 擁有者至少十次叫我繼續。
 *
 * 兩個數字不衝突,因為它們量的是不同的東西。過早交還發言權的典型樣子是:
 * 宣告全部兌現了,這一輪也真的有產出,然後停下來 —— 而工作還沒完。
 * 每一筆帳都結清了,只是提早收工。從宣告的角度看,那是滿分。
 *
 * ── 跟「該停下來問人」的分界 ──────────────────────────
 *
 * 有些停是對的:問了問題等答案、遇到只有人能決定的取捨、被明確叫停。
 * 分不開這兩者的偵測器只會製造一種壓力,就是「不做完不准停」,
 * 而那正是 2026-09-08 從 Stop hook 拿掉的東西(見 hooks/README.md)。
 *
 * 所以「有沒有在等」是輸入,不是猜測。宿主判斷,這裡只收布林值,
 * 跟 followthrough 的 awaiting 同一個設計。
 *
 * ── 誠實條款 ─────────────────────────────────────────
 *
 * 拿不到完成的定義就回 CANNOT_DETERMINE,不是 LEGITIMATE。
 * 不知道還有什麼沒做,不等於已經做完了。這條跟 drift.js 的
 * GoalState 閘門同源:沒有錨點就不准說人飄移。
 *
 * 零依賴。這裡不讀文字,不做語意判斷。
 */

export const VERSION = 'yield@0.1';

export const VERDICTS = Object.freeze([
  'PREMATURE',          // 還有未達成的條件,沒有在等人,這一輪也有產出
  'LEGITIMATE',         // 完成的條件都達成了
  'AWAITING',           // 在等對方回應。問了問題就停下來是協作,不是提早收工。
  'BLOCKED',            // 這一輪零產出,那是卡住,不是提早收工。兩者的處方相反。
  'CANNOT_DETERMINE',   // 拿不到完成的定義
]);

/**
 * 這次交還發言權是不是過早。
 *
 * @param {object} p
 * @param {string[]|null} p.doneWhen     完成的定義。拿不到就傳 null,不要傳空陣列 ——
 *                                       空陣列的意思是「定義了,而且是零條」。
 * @param {string[]} p.unmet             上面那些條件裡還沒達成的。宿主判斷。
 * @param {boolean} p.awaiting           有沒有在等對方回應。宿主判斷,這裡不猜。
 * @param {number} p.producedThisTurn    這一輪的產出數(檔案、指令、任何可驗的動作)。
 */
export function judgeYield({
  doneWhen = null, unmet = [], awaiting = false, producedThisTurn = 0,
} = {}) {
  const base = { version: VERSION };

  if (doneWhen === null || doneWhen === undefined) {
    return Object.freeze({
      ...base,
      verdict: 'CANNOT_DETERMINE',
      reason: 'No definition of done is available. Not knowing what is left '
        + 'is not the same as nothing being left.',
    });
  }

  if (awaiting) {
    return Object.freeze({
      ...base,
      verdict: 'AWAITING',
      reason: 'Waiting on the other party. Asking and stopping is collaboration, '
        + 'not stopping early.',
    });
  }

  const outstanding = [...unmet];

  if (producedThisTurn === 0) {
    return Object.freeze({
      ...base,
      verdict: 'BLOCKED',
      outstanding: Object.freeze(outstanding),
      reason: 'Nothing was produced this turn. That is being stuck, not stopping '
        + 'early, and the two need opposite responses.',
    });
  }

  if (!outstanding.length) {
    return Object.freeze({ ...base, verdict: 'LEGITIMATE', outstanding: Object.freeze([]) });
  }

  return Object.freeze({
    ...base,
    verdict: 'PREMATURE',
    outstanding: Object.freeze(outstanding),
    /**
     * 措辭刻意不是命令。這個偵測器不擋任何東西,它只是把「還有這些沒做」
     * 講出來,因為交還發言權的那一刻,正是當事人最不會去看那張清單的時候。
     */
    reason: `${outstanding.length} of ${doneWhen.length} conditions are still unmet, `
      + 'nothing is being waited on, and this turn did produce work. '
      + 'Handing the turn back here means someone else has to notice.',
  });
}

/**
 * 一段對話裡有多少次是過早交還。
 *
 * 分母排除 AWAITING、BLOCKED 與 CANNOT_DETERMINE:前兩者不是提早收工,
 * 第三者是沒有資料。分母為零時回 null,不是 0 —— 沒有可判的回合
 * 不等於一次都沒發生。
 */
export function prematureRate(judgements) {
  const list = judgements ?? [];
  const judged = list.filter((j) => j.verdict === 'PREMATURE' || j.verdict === 'LEGITIMATE');
  const byVerdict = {};
  for (const j of list) byVerdict[j.verdict] = (byVerdict[j.verdict] ?? 0) + 1;
  const undetermined = byVerdict.CANNOT_DETERMINE ?? 0;
  return Object.freeze({
    rate: judged.length ? judged.filter((j) => j.verdict === 'PREMATURE').length / judged.length : null,
    judged: judged.length,
    premature: judged.filter((j) => j.verdict === 'PREMATURE').length,
    by_verdict: Object.freeze(byVerdict),
    /** 判不了的比例太高時,這個率沒有代表性。 */
    undetermined_ratio: list.length ? undetermined / list.length : null,
    note: list.length === 0
      ? 'No turns judged. This is not a clean record; it is no record.'
      : (undetermined / list.length > 0.5
        ? 'More than half the turns had no definition of done available, so this rate covers a minority of them.'
        : null),
  });
}
