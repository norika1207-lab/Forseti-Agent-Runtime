/**
 * Forseti：目標範圍與離題累積
 *
 * 飄移偵測看的是趨勢,它要幾十段事件才說得出話。這個模組看的是單一動作:
 * 現在要碰的這個檔案,在不在宣告過的目標範圍裡。
 *
 * ── 為什麼不是碰到範圍外就叫 ──────────────────────────
 *
 * 因為那會一直叫。做一件事的過程本來就會碰到很多周邊:讀設定、看別人的
 * 實作、翻文件、跑測試。每一次都提醒等於沒有提醒,而且會被關掉。
 *
 * 所以判準是累積:連續幾次都在範圍外,才算真的走開了。
 * 中間只要碰回範圍內一次,計數就歸零 —— 那代表人還在主線上,
 * 剛才那幾次是繞路不是離開。
 *
 * ── 範圍是宣告出來的,不是推出來的 ────────────────────
 *
 * 沒有宣告過範圍就不作用,而且會明說。推一個範圍出來然後拿它擋人,
 * 是把工具自己的猜測強加到使用者身上,那比不擋更糟。
 *
 * 零依賴。
 */

export const VERSION = 'scope@0.1';

export const DEFAULT_CONFIG = Object.freeze({
  /**
   * 連續幾次在範圍外才提醒。
   * 【五次沒有實測校準。】一次就叫必然變成噪音;太多次則等於沒有防線。
   * 五是保守的起點,宿主應該依自己被打擾的容忍度調。
   */
  streakBeforeNotice: 5,
});

/**
 * 建一個目標範圍。
 *
 * @param {object} p
 * @param {string} p.northStar  一句話的目標,給人看的
 * @param {string[]} p.paths    範圍內的路徑前綴。空的話這個模組不作用。
 */
export function createScope({ northStar = null, paths = [] } = {}) {
  return Object.freeze({
    north_star: northStar,
    paths: Object.freeze([...paths]),
    /** 沒有宣告路徑就不作用。這個模組不推測範圍。 */
    active: paths.length > 0,
    version: VERSION,
  });
}

/** 這個路徑在不在範圍內。邊界卡在斜線上,src/a 不會誤匹配 src/auth。 */
export function inScope(filePath, scope) {
  if (!scope?.active) return true;   // 沒宣告範圍時一律算在內,不擋任何東西
  const p = String(filePath ?? '');
  for (const base of scope.paths) {
    if (p === base || p.startsWith(base.endsWith('/') ? base : base + '/')) return true;
    // 也接受相對於範圍的寫法
    if (p.includes('/' + base + '/') || p.endsWith('/' + base)) return true;
  }
  return false;
}

/** 空的離題計數。宿主要存下來,不然「連續」永遠數不到。 */
export function createStreak() {
  return Object.freeze({ off: 0, last_off_paths: Object.freeze([]), total_off: 0, total_checked: 0 });
}

/**
 * 檢查一次動作,並更新累積。
 *
 * @returns {{streak, notice}}
 *   notice 為 null 表示不用說話。這是最常見的情況,而且應該是。
 */
export function check(filePath, scope, streak, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  if (!scope?.active) {
    return Object.freeze({
      streak: streak ?? createStreak(),
      notice: null,
      /** 沒宣告範圍時明說,不要讓「沒叫」看起來像「檢查過沒事」。 */
      inactive_reason: 'No goal scope declared; this check does nothing until one exists.',
    });
  }

  const s = streak ?? createStreak();
  const ok = inScope(filePath, scope);
  const next = ok
    ? Object.freeze({ off: 0, last_off_paths: Object.freeze([]), total_off: s.total_off, total_checked: s.total_checked + 1 })
    : Object.freeze({
      off: s.off + 1,
      last_off_paths: Object.freeze([...s.last_off_paths, filePath].slice(-10)),
      total_off: s.total_off + 1,
      total_checked: s.total_checked + 1,
    });

  if (ok || next.off < c.streakBeforeNotice) {
    return Object.freeze({ streak: next, notice: null });
  }

  return Object.freeze({
    streak: next,
    notice: Object.freeze({
      streak: next.off,
      north_star: scope.north_star,
      recent: Object.freeze([...next.last_off_paths]),
      /**
       * 這是提醒不是阻止。人可能正在做一件必要的繞路,
       * 而工具沒有資格判斷那個繞路值不值得。
       */
      text: `${next.off} consecutive writes outside the declared goal scope. `
        + (scope.north_star ? `North star: ${scope.north_star}. ` : '')
        + 'This may be a necessary detour - the tool cannot tell. '
        + 'If the direction genuinely changed, declare it so the drift reading stays meaningful.',
    }),
  });
}

/** 離題比例。回顧用,不是即時判斷用。分母為零時回 null。 */
export function offScopeRate(streak) {
  const s = streak ?? createStreak();
  return Object.freeze({
    rate: s.total_checked ? s.total_off / s.total_checked : null,
    off: s.total_off,
    checked: s.total_checked,
    current_streak: s.off,
  });
}
