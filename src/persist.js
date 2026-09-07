/**
 * Forseti M6：持久化
 *
 * 前面六個模組全部無狀態。程序一重啟，M2 累積的自動化率歸零、
 * M3 記得誰佔著哪些檔案的紀錄消失、M5 每個 session 知道什麼全部忘光。
 * 那些量之所以有用，正是因為它們是累積的，重啟就歸零等於沒有。
 *
 * 這個模組不寫檔案、不碰檔案系統。它只做四件事：
 * 打包、序列化、還原、以及還原之後的復甦處理。
 * 真正的 I/O 是宿主的事，它只要能存一個字串、讀回一個字串就夠了。
 *
 * ── 兩個會靜默吃掉資料的坑，這個模組存在的主要理由 ──────────
 *
 * 一，Set 過不了 JSON。
 *     admission.js 的 scope.actual 是 Set。JSON.stringify 一個 Set
 *     得到的是 {}，不是空陣列也不是錯誤，就是一個空物件，而且完全不會報錯。
 *     重啟之後每個 agent 都變成「什麼都沒寫過」，越界偵測整個失效，
 *     畫面上卻一切正常。這種錯不會有人發現，除非有天出事回頭查。
 *     所以序列化一律走這裡的 encode/decode，不准直接 JSON.stringify。
 *
 * 二，重啟之後所有 ACTIVE 的佔用範圍都是可疑的。
 *     紀錄上寫著「A 正在寫這批檔案」，但 A 的程序在重啟時就死了。
 *     照單全收的話，整個專案會被已經不存在的 agent 幽靈鎖死，
 *     而且 M3 會一直擋新任務，理由是一個永遠不會結束的佔用。
 *     所以 restore() 一律把它們標成 stale 交給宿主確認，
 *     不自作主張當成還活著，也不自作主張全部釋放 ——
 *     後者會在真的還活著的情況下放兩個 agent 進同一個檔案。
 */

/** 快照格式版本。改欄位就要進版，並在 migrate() 補上升級路徑。 */
export const SCHEMA_VERSION = 1;

/** 快照裡的區塊。逐塊還原，一塊壞掉不連累其他塊。 */
export const SECTIONS = Object.freeze([
  'capsules', 'budget', 'scopes', 'locks', 'coverages', 'stats', 'edges',
  // 北極星與訊號。忘了目標,飄移就永遠量不出來,所以它必須跨重啟活著。
  'goal', 'signals',
]);

// ---------------------------------------------------------------------------
// 完整性檢查
// ---------------------------------------------------------------------------

/**
 * FNV-1a 32 位元雜湊。純 JS，零依賴。
 *
 * 【這是完整性檢查，不是安全檢查。】它擋得住檔案被截斷、被編輯器改壞、
 * 半路寫入失敗，擋不住任何有意的竄改 —— 想改的人重算一次就好。
 * 不要拿它當簽章用，這裡沒有任何密碼學保證。
 */
export function checksum(text) {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
}

// ---------------------------------------------------------------------------
// 打包與序列化
// ---------------------------------------------------------------------------

/** Set 與 Map 轉成可序列化的形狀。排序讓同樣的狀態產生同樣的字串。 */
function encodeValue(v) {
  if (v instanceof Set) return { __set: [...v].sort() };
  if (v instanceof Map) return { __map: [...v.entries()].sort((a, b) => String(a[0]).localeCompare(String(b[0]))) };
  if (Array.isArray(v)) return v.map(encodeValue);
  if (v && typeof v === 'object') {
    const out = {};
    for (const [k, val] of Object.entries(v)) out[k] = encodeValue(val);
    return out;
  }
  return v;
}

function decodeValue(v) {
  if (Array.isArray(v)) return v.map(decodeValue);
  if (v && typeof v === 'object') {
    if (Array.isArray(v.__set)) return new Set(v.__set.map(decodeValue));
    if (Array.isArray(v.__map)) return new Map(v.__map.map(([k, val]) => [k, decodeValue(val)]));
    const out = {};
    for (const [k, val] of Object.entries(v)) out[k] = decodeValue(val);
    return out;
  }
  return v;
}

/**
 * 打包目前狀態。缺的區塊留空，不編造預設值。
 *
 * @param {object} p 各模組的目前狀態
 * @param {number} p.at 打包時間，毫秒。restore 要靠它判斷過了多久。
 */
export function createSnapshot({
  capsules = [], budget = null, scopes = [], locks = [],
  coverages = [], stats = null, edges = [], goal = null, signals = null, at = null,
} = {}) {
  if (typeof at !== 'number' || !Number.isFinite(at)) {
    throw new TypeError('at is required and must be a millisecond timestamp. Without a pack time, lock expiry cannot be judged.');
  }
  return Object.freeze({
    schema_version: SCHEMA_VERSION,
    at,
    capsules, budget, scopes, locks, coverages, stats, edges, goal, signals,
  });
}

/**
 * 轉成可以存起來的字串。
 * 最外層帶 checksum，讀回來時能發現檔案被截斷或改壞。
 */
export function serialize(snapshot) {
  const body = JSON.stringify(encodeValue({
    schema_version: snapshot.schema_version ?? SCHEMA_VERSION,
    at: snapshot.at,
    ...Object.fromEntries(SECTIONS.map((s) => [s, snapshot[s] ?? null])),
  }));
  return JSON.stringify({ checksum: checksum(body), body });
}

/**
 * 讀回來。整份壞掉跟一塊壞掉是兩件事，這裡分得開。
 *
 * 一塊壞掉時不整份丟掉：其他塊照樣還原，壞掉的那塊記進 errors。
 * M5 的覆蓋資料壞了不該連帶讓 M2 累積半年的自動化率一起歸零。
 *
 * @returns {{snapshot:object|null, errors:Array, checksum_ok:boolean|null}}
 */
export function deserialize(text) {
  const errors = [];
  let outer;
  try {
    outer = JSON.parse(text);
  } catch (e) {
    return Object.freeze({
      snapshot: null,
      errors: Object.freeze([Object.freeze({ section: null, message: 'Whole snapshot failed to parse: ' + e.message })]),
      checksum_ok: null,
    });
  }

  let checksum_ok = null;
  let bodyText = null;
  if (typeof outer?.body === 'string') {
    bodyText = outer.body;
    checksum_ok = typeof outer.checksum === 'string' ? checksum(bodyText) === outer.checksum : null;
    if (checksum_ok === false) {
      errors.push(Object.freeze({ section: null, message: 'checksum mismatch - the content may be truncated or modified' }));
    }
  } else {
    // 沒有外層信封,當成裸的快照。舊格式或手寫的都走這條。
    bodyText = text;
  }

  let raw;
  try {
    raw = JSON.parse(bodyText);
  } catch (e) {
    return Object.freeze({
      snapshot: null,
      errors: Object.freeze([...errors, Object.freeze({ section: null, message: 'Body failed to parse: ' + e.message })]),
      checksum_ok,
    });
  }

  const out = {
    schema_version: raw.schema_version ?? 0,
    at: typeof raw.at === 'number' ? raw.at : null,
  };
  for (const s of SECTIONS) {
    try {
      out[s] = raw[s] === undefined ? null : decodeValue(raw[s]);
    } catch (e) {
      out[s] = null;
      errors.push(Object.freeze({ section: s, message: e.message }));
    }
  }

  return Object.freeze({
    snapshot: Object.freeze(migrate(out)),
    errors: Object.freeze(errors),
    checksum_ok,
  });
}

/**
 * 舊版快照升到目前版本。
 *
 * 現在只有一個版本，所以這裡只做一件事：把沒有版本號的舊資料標成 0，
 * 讓呼叫端知道它來自一個沒有版本概念的年代，而不是假裝它是第 1 版。
 * 之後改欄位時，升級路徑寫在這裡，一步一步升，不要跳版。
 */
export function migrate(raw) {
  const v = raw.schema_version ?? 0;
  if (v > SCHEMA_VERSION) {
    // 比我認得的還新。不猜它多了什麼，原樣回傳並標明。
    return { ...raw, migrated_from: v, unknown_future_version: true };
  }
  if (v === SCHEMA_VERSION) return raw;
  return { ...raw, schema_version: SCHEMA_VERSION, migrated_from: v };
}

// ---------------------------------------------------------------------------
// 復甦
// ---------------------------------------------------------------------------

/** 判斷一個鎖有沒有過期。跟 admission.js 的規則一致，但這裡不 import 它。 */
function lockExpired(lock, now) {
  const ttl = lock?.ttl_seconds;
  if (typeof ttl !== 'number' || typeof lock?.acquired_at !== 'number') return false;
  return now - lock.acquired_at > ttl * 1000;
}

/**
 * 把還原出來的狀態變成可以直接用的狀態。
 *
 * 這一步不是形式主義。重啟之後有兩類東西不能照單全收：
 *
 *   過期的鎖    直接清掉。持有者早就死了，留著只會擋人。
 *   ACTIVE 佔用 標成 stale 交給宿主確認,不當成還活著,也不自動釋放。
 *
 * 為什麼不自動釋放:如果那個 agent 其實還活著(只有宿主重啟、
 * agent 在別的程序裡繼續跑),自動釋放等於放兩個人進同一個檔案,
 * 那正是 M3 存在要擋的事。所以這裡只標記,決定權留給宿主 ——
 * 它才知道那些 agent 現在還在不在。
 *
 * @returns {{state:object, stale_scopes:Array, expired_locks:Array, gap_ms:number|null, warnings:Array}}
 */
export function restore(snapshot, { now } = {}) {
  if (typeof now !== 'number' || !Number.isFinite(now)) {
    throw new TypeError('now is required. Without the current time, lock expiry cannot be judged.');
  }
  const warnings = [];
  const scopes = Array.isArray(snapshot?.scopes) ? snapshot.scopes : [];
  const locks = Array.isArray(snapshot?.locks) ? snapshot.locks : [];

  const liveLocks = [];
  const expired = [];
  for (const l of locks) {
    (lockExpired(l, now) ? expired : liveLocks).push(l);
  }

  const stale = scopes.filter((s) => s?.state === 'ACTIVE');
  if (stale.length) {
    warnings.push(
      `${stale.length} write scope(s) were ACTIVE before the restart. Their holders may no longer exist; ` +
      'confirm before releasing or keeping them. This module will not decide for you - both guesses cause damage.',
    );
  }

  const gap = typeof snapshot?.at === 'number' ? now - snapshot.at : null;
  if (gap === null) {
    warnings.push('Snapshot has no pack time; the length of the interruption cannot be determined.');
  }
  if (snapshot?.unknown_future_version) {
    warnings.push('Snapshot version is newer than this build understands; some fields may not have been read.');
  }

  return Object.freeze({
    state: Object.freeze({
      capsules: snapshot?.capsules ?? [],
      budget: snapshot?.budget ?? null,
      scopes: Object.freeze(scopes),
      locks: Object.freeze(liveLocks),
      coverages: snapshot?.coverages ?? [],
      stats: snapshot?.stats ?? null,
      edges: snapshot?.edges ?? [],
      goal: snapshot?.goal ?? null,
      signals: snapshot?.signals ?? null,
    }),
    stale_scopes: Object.freeze(stale),
    expired_locks: Object.freeze(expired),
    gap_ms: gap,
    warnings: Object.freeze(warnings),
  });
}

/**
 * 一次做完:讀字串、還原、復甦。宿主最常用的入口。
 * 讀不出來時 state 為 null,不回一個空狀態 ——
 * 「讀失敗」跟「這是一個全新的空專案」是兩件事,混在一起會靜默清掉舊資料。
 */
export function load(text, { now } = {}) {
  const parsed = deserialize(text);
  if (!parsed.snapshot) {
    return Object.freeze({
      state: null,
      errors: parsed.errors,
      checksum_ok: parsed.checksum_ok,
      stale_scopes: Object.freeze([]),
      expired_locks: Object.freeze([]),
      gap_ms: null,
      warnings: Object.freeze(['Snapshot could not be read. This is not the same as an empty project - do not overwrite with empty state.']),
    });
  }
  const r = restore(parsed.snapshot, { now });
  return Object.freeze({ ...r, errors: parsed.errors, checksum_ok: parsed.checksum_ok });
}

/**
 * 存檔前的自我檢查:這份快照存下去,重讀之後會不會不一樣。
 *
 * 靜默資料遺失只有一種可靠的抓法,就是存完立刻讀回來比對。
 * 這個函式就做這件事,回報哪些區塊過不了來回。
 *
 * @returns {{ok:boolean, lossy_sections:string[], byte_size:number}}
 */
export function roundTripCheck(snapshot) {
  const text = serialize(snapshot);
  const back = deserialize(text).snapshot;
  const lossy = [];
  for (const s of SECTIONS) {
    const before = JSON.stringify(encodeValue(snapshot[s] ?? null));
    const after = JSON.stringify(encodeValue(back?.[s] ?? null));
    if (before !== after) lossy.push(s);
  }
  return Object.freeze({
    ok: lossy.length === 0,
    lossy_sections: Object.freeze(lossy),
    byte_size: text.length,
  });
}
