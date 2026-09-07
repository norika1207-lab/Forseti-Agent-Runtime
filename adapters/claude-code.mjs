/**
 * Adapter：Claude Code 的 session jsonl → Forseti 中性事件
 *
 * 這是第一個接到真實宿主的 adapter，也是這份東西第一次吃到不是自己造的資料。
 * 它示範一個 adapter 該負責什麼：把宿主的格式翻譯過來，
 * 以及在身分歸屬不確定時誠實標明，而不是挑一個看起來最像的欄位填進去。
 *
 * ── 真實格式（實際讀 jsonl 對出來的，不是憑印象）─────────────
 *
 * 每行一個 JSON 物件，跟工具呼叫有關的長這樣：
 *   {
 *     type: 'assistant',
 *     sessionId: '...',              整個檔共用一個
 *     timestamp: '2026-09-07T...Z',  ISO 字串
 *     uuid, parentUuid,              串起對話樹
 *     isSidechain: false,            true = 這是 subagent 的分支
 *     cwd, gitBranch,
 *     message: { content: [ { type:'tool_use', name, input, id, caller } ] }
 *   }
 *
 * ── 身分歸屬:這裡正是教訓一的真實場景 ────────────────────
 *
 * sessionId 標的是「這個記錄檔」,不是「做這件事的人」。
 * isSidechain 為 true 的那些事件是 subagent 做的,卻共用同一個 sessionId。
 * 直接拿 sessionId 當 agent_id,會把主線跟所有 subagent 的動作
 * 全部算成同一個人:覆蓋範圍被灌得很大、衝突偵測失效
 * (同一個人不會跟自己衝突)、派工挑人永遠挑到同一個。
 *
 * 所以這裡把 sidechain 的事件另外標一個 agent_id,
 * 並在結果裡明講:sidechain 的真正執行者身分,從這個檔案裡看不出來。
 * 那是宿主要補的資訊,不是這裡該猜的。
 *
 * ── resume:同一條對話會有兩個 sessionId ──────────────────
 *
 * 跑 130 個真實記錄檔時抓到的。使用者 resume 一條對話,系統開一個新檔、
 * 給一個新的 sessionId,並把舊檔的歷史整段複製進去。結果是:
 * 同一批事件在兩個檔各出現一次,時間戳一模一樣,sessionId 不同。
 *
 * 拿 sessionId 當執行者身分的話,同一個人被算成兩個人,
 * 同一筆寫入被算成兩次,時間差 0.0 秒,直接判成「兩個 agent 撞車」。
 * 實測跑出四次撞車,其中三次是這樣來的。
 *
 * 可靠的識別碼是每行的 uuid:它標的是事件本身,resume 複製過去也不變。
 * 所以 parseTranscripts() 用 uuid 去重,並把共用大量 uuid 的 session
 * 合併成同一個執行者。這又是同一條教訓的另一個面向 ——
 * 檔案層級的識別碼標的是記錄流,不是做事的人。
 */

/** sidechain 事件的 agent_id 後綴。宿主拿得到真實 subagent id 時應覆寫。 */
export const SIDECHAIN_SUFFIX = ':sidechain';

/**
 * 一行 jsonl → 零到多個 Forseti 原始事件。
 *
 * 一行可能含多個 tool_use block，所以回傳陣列。
 * 跟工具呼叫無關的行回空陣列。
 */
export function lineToRawEvents(obj, { sessionLabel = null } = {}) {
  if (!obj || typeof obj !== 'object') return [];
  const content = obj.message?.content;
  if (!Array.isArray(content)) return [];

  const at = Date.parse(obj.timestamp);
  if (!Number.isFinite(at)) return [];      // 沒有可用的時間戳就跳過，不補

  const sid = obj.sessionId;
  if (!sid) return [];

  // 教訓一:sessionId 是記錄流不是執行者。sidechain 另外標,不混進主線。
  const agent = obj.isSidechain ? sid + SIDECHAIN_SUFFIX : sid;

  const out = [];
  for (const b of content) {
    if (!b || b.type !== 'tool_use') continue;
    out.push({
      attributed_agent: agent,
      agent_label: sessionLabel,
      session_id: sid,
      name: b.name,
      input: b.input ?? {},
      at,
      /** 事件本身的識別碼。resume 複製到新檔也不變,是跨檔去重的依據。 */
      event_uuid: obj.uuid ? `${obj.uuid}#${out.length}` : null,
    });
  }
  return out;
}

/**
 * 多份記錄檔一起處理:跨檔去重,並把 resume 出來的 session 併回同一個執行者。
 *
 * 單獨用 parseTranscript() 逐檔處理再合併,會把 resume 的重複事件算兩次
 * 並判成撞車。要正確,去重與合併必須在看得到全部檔案的地方做。
 *
 * @param {Array<{name:string, text:string}>} inputs
 * @param {object} [opts]
 * @param {number} [opts.mergeRatio=0.5] 兩個 session 共用 uuid 的比例超過此值就視為同一條對話
 * @returns {{events, sessions, resume_groups, duplicates_removed, lines, parse_failures, sidechain_events, notes}}
 */
export function parseTranscripts(inputs, { mergeRatio = 0.5 } = {}) {
  const perSession = new Map();   // agent_id -> { uuids:Set, events:[] }
  let lines = 0, parseFailures = 0, sidechain = 0;

  for (const { name, text } of inputs) {
    const r = parseTranscript(text, { sessionLabel: name });
    lines += r.lines; parseFailures += r.parse_failures; sidechain += r.sidechain_events;
    for (const e of r.events) {
      const id = e.attributed_agent;
      if (!perSession.has(id)) perSession.set(id, { uuids: new Set(), events: [] });
      const bucket = perSession.get(id);
      if (e.event_uuid) bucket.uuids.add(e.event_uuid);
      bucket.events.push(e);
    }
  }

  // 共用 uuid 比例高的 session 合併。用聯集尋找,一條 resume 鏈可以有很多段。
  const ids = [...perSession.keys()];
  const parent = new Map(ids.map((i) => [i, i]));
  const find = (x) => (parent.get(x) === x ? x : (parent.set(x, find(parent.get(x))), parent.get(x)));
  const union = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) parent.set(rb, ra); };

  for (let i = 0; i < ids.length; i += 1) {
    for (let j = i + 1; j < ids.length; j += 1) {
      const A = perSession.get(ids[i]).uuids;
      const B = perSession.get(ids[j]).uuids;
      if (!A.size || !B.size) continue;
      let shared = 0;
      const [small, big] = A.size <= B.size ? [A, B] : [B, A];
      for (const u of small) if (big.has(u)) shared += 1;
      if (shared / small.size >= mergeRatio) union(ids[i], ids[j]);
    }
  }

  // 去重並改用合併後的身分。同一個 uuid 只留最早的那筆。
  const seen = new Set();
  const events = [];
  let dropped = 0;
  for (const [id, bucket] of perSession) {
    const canonical = find(id);
    for (const e of bucket.events) {
      const key = e.event_uuid ? canonical + '|' + e.event_uuid : null;
      if (key && seen.has(key)) { dropped += 1; continue; }
      if (key) seen.add(key);
      events.push(canonical === id ? e : { ...e, attributed_agent: canonical });
    }
  }
  events.sort((a, b) => a.at - b.at);

  const groups = new Map();
  for (const id of ids) {
    const root = find(id);
    if (!groups.has(root)) groups.set(root, []);
    groups.get(root).push(id);
  }
  const resumeGroups = [...groups.values()].filter((g) => g.length > 1).map((g) => Object.freeze(g.sort()));

  const notes = [];
  if (resumeGroups.length) {
    notes.push(
      `${resumeGroups.length} conversation(s) were recorded under more than one session id, ` +
      'most likely resumed sessions. They are merged into one executor - counting them separately ' +
      'makes one person look like two and turns duplicated events into false conflicts.',
    );
  }
  if (dropped) notes.push(`${dropped} duplicate event(s) removed across transcripts.`);
  if (sidechain) {
    notes.push(
      `${sidechain} event(s) came from subagent sidechains; their real executor identity is not ` +
      'recoverable from the transcript.',
    );
  }
  if (parseFailures) notes.push(`${parseFailures} line(s) failed to parse.`);

  return Object.freeze({
    events,
    sessions: Object.freeze([...new Set(events.map((e) => e.attributed_agent))].sort()),
    resume_groups: Object.freeze(resumeGroups),
    duplicates_removed: dropped,
    lines,
    parse_failures: parseFailures,
    sidechain_events: sidechain,
    notes: Object.freeze(notes),
  });
}

/**
 * 整份 jsonl 文字 → 原始事件陣列。
 *
 * @returns {{events:Array, lines:number, parse_failures:number, sidechain_events:number,
 *            sessions:string[], notes:string[]}}
 */
export function parseTranscript(text, { sessionLabel = null } = {}) {
  const events = [];
  const sessions = new Set();
  let lines = 0;
  let parseFailures = 0;
  let sidechain = 0;

  for (const raw of text.split('\n')) {
    if (!raw.trim()) continue;
    lines += 1;
    let obj;
    try {
      obj = JSON.parse(raw);
    } catch {
      parseFailures += 1;      // 寫到一半的行。計數,不靜默忽略。
      continue;
    }
    const evs = lineToRawEvents(obj, { sessionLabel });
    for (const e of evs) {
      events.push(e);
      sessions.add(e.attributed_agent);
      if (e.attributed_agent.endsWith(SIDECHAIN_SUFFIX)) sidechain += 1;
    }
  }

  const notes = [];
  if (sidechain > 0) {
    notes.push(
      `${sidechain} event(s) came from subagent sidechains. Their real executor identity is not ` +
      'recoverable from the transcript, so they are attributed to a single synthetic id per session. ' +
      'A host that knows the actual subagent ids should override this.',
    );
  }
  if (parseFailures > 0) {
    notes.push(`${parseFailures} line(s) failed to parse (likely a partially written tail).`);
  }

  return Object.freeze({
    events,
    lines,
    parse_failures: parseFailures,
    sidechain_events: sidechain,
    sessions: Object.freeze([...sessions].sort()),
    notes: Object.freeze(notes),
  });
}
