/**
 * Forseti M7：目標飄移
 *
 * 前面的機制防的都是「說了沒做」:宣稱改了某個檔案,磁碟上沒動靜。
 * 那種欺騙有破綻,查得到。
 *
 * 這個模組防的是另一種,而且是更難發現、代價更高的那種:
 * 東西真的做了、檔案真的寫了、數字真的跑出來了,
 * 但那已經不是原本要做的事了。北極星變成南極星,而且沒有任何一刻
 * 有人說過「我們改方向了」。
 *
 * ── 為什麼「跟上一步比」抓不到飄移 ────────────────────
 *
 * 第一版寫錯了,拿相鄰時間段的重疊率找斷崖。跑真實資料才知道方向反了。
 *
 * 飄移的定義特徵就是沒有斷崖。每一步都只偏一點,每一步看起來都合理,
 * 走一百步之後完全反了。實測一條橫跨三個月的對話:
 * 相鄰段的平均重疊只有 16%(每一步都是小移動),
 * 但跟起點的重疊從 100% 一路掉到 0%,中間沒有任何一段像轉向。
 *
 * 所以量的是「跟錨點的距離」,不是「跟前一步的距離」。
 * 這是整個模組唯一重要的設計決定。
 *
 * ── 飄移本身不是錯 ──────────────────────────────
 *
 * 人本來就會改主意,改主意是對的。危險的是沒有人注意到方向變了,
 * 尤其是「做不到就換一個」這種:遇到失敗,提出一個聽起來更好的新方向,
 * 工作重心轉過去,舊的目標從此再也沒被碰過,而且沒有人宣告過放棄它。
 *
 * 所以這裡把兩件事分開:
 *   有宣告的轉向    正常,不告警
 *   沒宣告的飄移    告警,附上從哪裡飄到哪裡
 * 並且對每個被放棄的目標,列出放棄的那一刻附近有沒有失敗訊號。
 * 有失敗又立刻換方向,那是逃逸,不是決策。
 *
 * 零依賴。這裡只讀事件,不判斷任何人的動機。
 */

export const ALERT_LEVELS = Object.freeze(['ON_COURSE', 'DRIFTING', 'OFF_COURSE', 'LOST']);

export const DEFAULT_CONFIG = Object.freeze({
  /** 跟錨點的重疊低於此值 = 開始飄 */
  driftingBelow: 0.5,
  /** 低於此值 = 已經偏離 */
  offCourseBelow: 0.2,
  /** 完全零重疊 = 走丟了 */
  lostAt: 0,
  /** 一個主題至少要有這麼多事件,才算「密集做過」 */
  minEventsForTopic: 25,
  /**
   * 超過這麼久沒碰,算被放棄。
   * 【七天不是實測值。】它是一個保守的起點,宿主應該依專案節奏調整:
   * 週更的專案七天太短,日更的專案七天太長。
   */
  abandonedAfterMs: 7 * 24 * 60 * 60 * 1000,
  /** 放棄點前後多久內的失敗訊號算相關 */
  signalWindowMs: 2 * 60 * 60 * 1000,
});

/**
 * 把路徑收斂成一個「主題」。
 *
 * 單一檔案太細:同一件事會碰十幾個檔案,檔案層級的重疊率抖動太大。
 * 取前幾層路徑當語意單位,比較貼近「在做哪件事」。
 *
 * @param {string} filePath
 * @param {number} [depth=3] 取路徑前幾層
 */
export function topicOf(filePath, depth = 3) {
  return String(filePath ?? '').split('/').filter(Boolean).slice(0, depth).join('/');
}

/**
 * 把事件流切成等長的段。用事件數切而不是時間切,
 * 因為活動密度差異極大:同樣一小時,可能有兩百個動作也可能有兩個。
 */
export function segment(events, { size = 50, depth = 3 } = {}) {
  const out = [];
  const list = events ?? [];
  for (let i = 0; i < list.length; i += size) {
    const chunk = list.slice(i, i + size);
    if (chunk.length < size / 2) break;      // 尾巴不足半段就不算
    const topics = new Map();
    for (const e of chunk) {
      const t = topicOf(e.file_path, depth);
      if (!t) continue;
      topics.set(t, (topics.get(t) ?? 0) + 1);
    }
    out.push(Object.freeze({
      from: chunk[0].at,
      to: chunk.at(-1).at,
      count: chunk.length,
      topics,
    }));
  }
  return Object.freeze(out);
}

/**
 * 釘北極星。
 *
 * 兩種來源,優先用第一種:
 *   declared  宿主明確告訴我們目標是什麼(最可靠)
 *   前 N 段   從實際行為推,適用於沒人宣告過目標的情況
 *
 * 推出來的錨點會標 inferred: true,不冒充成宣告過的目標。
 */
export function createAnchor({ declared = null, segments = [], warmup = 3 } = {}) {
  if (declared && declared.length) {
    return Object.freeze({
      topics: Object.freeze(new Set(declared)),
      inferred: false,
      warmup_segments: 0,
    });
  }
  const acc = new Map();
  for (const s of segments.slice(0, warmup)) {
    for (const [k, v] of s.topics) acc.set(k, (acc.get(k) ?? 0) + v);
  }
  return Object.freeze({
    topics: Object.freeze(new Set(acc.keys())),
    inferred: true,
    warmup_segments: Math.min(warmup, segments.length),
  });
}

/**
 * 一個主題在不在錨點範圍內。
 *
 * 用路徑前綴而不是全等,因為宿主宣告目標的粒度不會剛好等於 topicOf 的粒度。
 * 宣告 src/auth、動的是 src/auth/token.js,那顯然在範圍內,判成走失是錯的。
 * 邊界卡在斜線上,所以 src/a 不會誤匹配 src/auth。
 */
function withinAnchor(topic, anchor) {
  if (anchor.topics.has(topic)) return true;
  for (const a of anchor.topics) {
    if (topic.startsWith(a + '/') || a.startsWith(topic + '/')) return true;
  }
  return false;
}

/** 一段跟錨點的重疊比例。分母是這一段自己,問的是「現在做的事有多少還在原本範圍內」。 */
export function alignment(segmentTopics, anchor) {
  const keys = segmentTopics instanceof Map ? [...segmentTopics.keys()] : [...(segmentTopics ?? [])];
  if (!keys.length) return null;              // 沒有東西可比,回 null 不是 0
  let hit = 0;
  for (const k of keys) if (withinAnchor(k, anchor)) hit += 1;
  return hit / keys.length;
}

/** 依 alignment 給警戒等級。 */
export function alertLevel(align, config = DEFAULT_CONFIG) {
  if (align === null) return null;
  const c = { ...DEFAULT_CONFIG, ...config };
  if (align <= c.lostAt) return 'LOST';
  if (align < c.offCourseBelow) return 'OFF_COURSE';
  if (align < c.driftingBelow) return 'DRIFTING';
  return 'ON_COURSE';
}

/**
 * 整條軌跡:每一段跟錨點的距離,以及跟前一段的距離。
 *
 * 兩個數字都要看,因為它們一起才說得出「這是飄移還是轉向」:
 *   跟錨點掉很多 + 每一步都很小  = 飄移(沒有任何一刻像轉向)
 *   跟錨點掉很多 + 某一步特別大  = 轉向(有一個明確的斷點)
 */
export function trajectory(segments, anchor, config = DEFAULT_CONFIG) {
  const rows = [];
  let prev = null;
  for (let i = 0; i < segments.length; i += 1) {
    const s = segments[i];
    const toAnchor = alignment(s.topics, anchor);
    let toPrev = null;
    if (prev) {
      const keys = [...s.topics.keys()];
      if (keys.length) {
        let hit = 0;
        for (const k of keys) if (prev.topics.has(k)) hit += 1;
        toPrev = hit / keys.length;
      }
    }
    rows.push(Object.freeze({
      index: i,
      from: s.from,
      to: s.to,
      alignment: toAnchor,
      step: toPrev,
      level: alertLevel(toAnchor, config),
      top_topic: [...s.topics.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? null,
    }));
    prev = s;
  }
  return Object.freeze(rows);
}

/**
 * 這整條軌跡是飄移還是轉向。
 *
 * @returns {{is_drift:boolean, mean_step:number|null, final_alignment:number|null,
 *            first_off_course:object|null, biggest_step_drop:object|null}}
 */
export function classify(rows, config = DEFAULT_CONFIG) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const steps = rows.map((r) => r.step).filter((x) => x !== null);
  const meanStep = steps.length ? steps.reduce((a, b) => a + b, 0) / steps.length : null;
  const final = rows.length ? rows.at(-1).alignment : null;
  const firstOff = rows.find((r) => r.level === 'OFF_COURSE' || r.level === 'LOST') ?? null;

  // 最大的單步跌落。如果有一步特別大,那比較像轉向而不是飄移。
  let biggest = null;
  for (const r of rows) {
    if (r.step === null) continue;
    if (!biggest || r.step < biggest.step) biggest = r;
  }

  // 飄移的判準:終點偏離了,而且沒有任何一步大到像轉向。
  const drifted = final !== null && final < c.offCourseBelow;
  const noSingleTurn = biggest === null || biggest.step > 0.05;

  return Object.freeze({
    is_drift: drifted && noSingleTurn,
    mean_step: meanStep,
    final_alignment: final,
    first_off_course: firstOff,
    biggest_step_drop: biggest,
    /** 判準的解釋,讓人看得懂結論怎麼來的,而不是相信一個布林值。 */
    reason: drifted
      ? (noSingleTurn
        ? 'End state is off course and no single step looks like a deliberate turn - the direction moved without anyone changing it.'
        : 'End state is off course, but one step is large enough to look like a deliberate turn.')
      : 'End state is still within the anchor.',
  });
}

/**
 * 被放棄的主題:密集做過,然後長期完全不再碰。
 *
 * 放棄不等於失敗,可能只是做完了。所以這裡不下判斷,
 * 只把事實列出來:做了多久、寫了多少、沉默了多久。
 * 判斷失敗與否要看 escapeSignals()。
 *
 * @param {Array} events 中性事件
 * @param {object} opts
 * @param {number} opts.now 現在時間,用來算沉默多久
 */
export function findAbandoned(events, { now, config = DEFAULT_CONFIG, depth = 3 } = {}) {
  if (typeof now !== 'number') throw new TypeError('now is required to measure how long a topic has been silent');
  const c = { ...DEFAULT_CONFIG, ...config };
  const spans = new Map();
  for (const e of (events ?? [])) {
    const t = topicOf(e.file_path, depth);
    if (!t) continue;
    if (!spans.has(t)) spans.set(t, { topic: t, events: 0, writes: 0, first: e.at, last: e.at });
    const s = spans.get(t);
    s.events += 1;
    if (e.at > s.last) s.last = e.at;
    if (e.at < s.first) s.first = e.at;
    if (e.action === 'WRITE') s.writes += 1;
  }
  const out = [];
  for (const s of spans.values()) {
    if (s.events < c.minEventsForTopic) continue;
    const silence = now - s.last;
    if (silence < c.abandonedAfterMs) continue;
    out.push(Object.freeze({
      topic: s.topic,
      events: s.events,
      writes: s.writes,
      first_touch: s.first,
      last_touch: s.last,
      active_ms: s.last - s.first,
      silent_ms: silence,
    }));
  }
  return Object.freeze(out.sort((a, b) => b.events - a.events));
}

/**
 * 放棄的那一刻附近,有沒有失敗訊號。
 *
 * 這是「做不到就換一個」與「做完了就換下一件」之間唯一可觀測的差別。
 *
 * 呼叫端負責提供訊號的時間點,本模組不解讀任何文字:
 *   failures  工具錯誤的時間戳
 *   friction  使用者表達不滿的時間戳(怎麼判定是宿主的事)
 *
 * 刻意不在這裡做關鍵詞比對。判斷一句話是不是不滿,是有文化與語境的,
 * 塞進一個零依賴模組只會做出一個誤判率很高又講得很篤定的東西。
 */
export function escapeSignals(abandoned, { failures = [], friction = [], config = DEFAULT_CONFIG } = {}) {
  const c = { ...DEFAULT_CONFIG, ...config };
  const w = c.signalWindowMs;
  return Object.freeze((abandoned ?? []).map((a) => {
    const f = failures.filter((t) => Math.abs(t - a.last_touch) <= w).length;
    const r = friction.filter((t) => Math.abs(t - a.last_touch) <= w).length;
    return Object.freeze({
      ...a,
      failures_near_abandonment: f,
      friction_near_abandonment: r,
      /** 有失敗又立刻不做了。這是逃逸的形狀,不是它的證明。 */
      looks_like_escape: (f > 0 || r > 0),
    });
  }));
}

/**
 * 即時告警:現在這一段偏離北極星多遠。
 *
 * 事後分析救不了任何人,要在飄的當下講得出來才有用。
 * 宿主應該每完成一段就呼叫一次。
 */
export function driftAlert({ recentTopics, anchor, declaredTurn = false, config = DEFAULT_CONFIG } = {}) {
  const align = alignment(recentTopics, anchor);
  const level = alertLevel(align, config);
  return Object.freeze({
    alignment: align,
    level,
    /** 有人宣告過轉向就不算飄移,只是換了方向。 */
    is_unannounced: !declaredTurn && (level === 'OFF_COURSE' || level === 'LOST'),
    anchor_was_inferred: anchor.inferred,
    /** 錨點是推出來的時,告警本身也比較弱。這一點必須讓呼叫端看得到。 */
    confidence: anchor.inferred ? 'INFERRED_ANCHOR' : 'DECLARED_ANCHOR',
  });
}
