/**
 * Forseti Runtime：把七個模組收成一個介面
 *
 * 前面每個模組都是獨立可用的純函數，但要真的接上來，
 * 得先讀完七份 API、自己想清楚呼叫順序、自己記住哪個結果該餵給哪個。
 * 這個模組把那些做掉，宿主只需要做四件事：
 *
 *   ingest()        把工具呼叫事件轉發進來
 *   requestWrite()  派工前問一句這個範圍能不能動
 *   completeTurn()  一輪做完通知一聲,拿回該送去哪裡
 *   save()          拿一個字串存起來
 *
 * ── 這裡只回答,不動作 ──────────────────────────────────
 *
 * completeTurn() 說「該送去 w2」,真的送出去是宿主的事。
 * requestWrite() 說「這個該擋」,擋不擋也是宿主的事。
 * 這條界線是刻意的:一旦這裡開始替宿主執行動作,它就從一組原語
 * 變成一個框架,而框架要求你照它的方式組織整個系統。
 * 那不是這份東西想成為的樣子。
 *
 * ── 這是唯一有狀態的模組 ────────────────────────────────
 *
 * 其他七個都是純函數。狀態集中在這裡而不是散在各處,
 * 是為了讓「哪裡有狀態」這件事看得見。內部狀態隨時可以 save() 出來檢查,
 * 沒有藏起來的東西。
 */

import {
  normalizeStream, coverageDepthOf, toWriteEvents, actualWrites,
  inferTurns, captureHealth, labelDrift, ambiguousLabels,
} from './capture.js';
import {
  coverageFromEvents, handoffDelta, pickHottest,
} from './coverage.js';
import {
  createWriteScope, recordActualWrite, releaseScope, outOfScopeWrites,
  decideAdmission, windowConflicts,
} from './admission.js';
import {
  planHandoff, createStats, applyStats, recordManual, releaseGate,
  automationRate, findCycles, buildHandoffPacket,
} from './handoff.js';
import {
  createSnapshot, serialize, load,
} from './persist.js';
import {
  segment, createAnchor, trajectory, classify, findAbandoned, escapeSignals, driftAlert,
} from './drift.js';
import {
  originMix, checkSourceErasure, checkScopeInflation, checkBarrenInvestment, audit,
  SHAPES, OUT_OF_SCOPE,
} from './provenance.js';

/**
 * 建一個 runtime。
 *
 * @param {object} p
 * @param {() => number} [p.now]  拿現在時間。預設用系統時鐘,測試時請注入。
 * @param {object} [p.config]     各模組的設定覆寫,依模組名分組
 */
export function createRuntime({ now = () => Date.now(), config = {} } = {}) {
  const state = {
    events: [],        // 中性事件,累積用
    coverages: new Map(),   // agent_id -> SessionCoverage
    scopes: [],
    locks: [],
    capsules: [],
    edges: [],
    stats: createStats(),
    capture: { total: 0, skipped: 0, skipped_by_reason: {} },
    /** 北極星。宿主宣告目標時釘下來,沒宣告就從前幾段推。 */
    anchor: null,
    /** 宿主宣告過轉向的時間點。有宣告的方向改變不算飄移。 */
    declaredTurns: [],
    /** 失敗訊號與摩擦訊號的時間點,由宿主提供。本模組不判讀文字。 */
    failures: [],
    friction: [],
    /** 這個 session 自己寫過的檔案。讀回它們是自產,不是第一手。 */
    selfWritten: new Set(),
    /** 委派出去的投入,用來追零產出。 */
    investments: [],
    /**
     * 工具呼叫的原始名稱與時間。
     *
     * 採集層只收動到檔案的事件,而派 agent 出去這件事本身沒有 file_path,
     * 整筆會被擋在 NO_FILE。但「這件事是誰查的」正是來源鏈要問的,
     * 所以這裡另外留一份,不經過採集層的檔案篩選。
     */
    toolCalls: [],
  };

  /** 重算某個 agent 的覆蓋範圍。事件進來之後才叫得動。 */
  function rebuildCoverage(agent_id) {
    const mine = state.events.filter((e) => e.agent_id === agent_id);
    if (!mine.length) return;
    state.coverages.set(agent_id, coverageFromEvents({
      session_id: mine[0].session_id ?? agent_id,
      agent_id,
      events: mine,
      toolDepth: coverageDepthOf,
    }));
  }

  return Object.freeze({
    /**
     * 餵事件進來。宿主每收到一批工具呼叫就丟過來。
     *
     * 回傳的東西全部是「你可能想知道的事」,沒有一項要求宿主做什麼。
     * conflicts 是已經發生的撞車(事後),不是攔截 —— 攔截在 requestWrite()。
     */
    ingest(rawEvents) {
      // 先留一份原始工具名。委派沒有檔案,過不了採集層,但來源鏈需要它。
      for (const raw of (rawEvents ?? [])) {
        const at = typeof raw?.at === 'number' ? raw.at : (typeof raw?.timestamp === 'number' ? raw.timestamp : null);
        const name = raw?.name ?? raw?.tool_name ?? raw?.type ?? null;
        if (at == null || !name) continue;
        const input = raw.input ?? raw.tool_input ?? raw.params ?? {};
        state.toolCalls.push({
          at, name,
          file_path: raw.file_path ?? input.file_path ?? input.path ?? null,
        });
      }
      state.toolCalls.sort((a, b) => a.at - b.at);

      const r = normalizeStream(rawEvents);
      state.events.push(...r.events);
      state.events.sort((a, b) => a.at - b.at);

      state.capture.total += r.total;
      state.capture.skipped += r.skipped;
      for (const [k, v] of Object.entries(r.skipped_by_reason)) {
        state.capture.skipped_by_reason[k] = (state.capture.skipped_by_reason[k] ?? 0) + v;
      }

      // 自己寫過的檔案要記下來。之後讀回它們,那是自產不是第一手證據。
      for (const e of r.events) {
        if (e.action === 'WRITE' && e.file_path) state.selfWritten.add(e.file_path);
      }

      const touched = new Set(r.events.map((e) => e.agent_id));
      for (const id of touched) rebuildCoverage(id);

      // 實際寫入的檔案回填到對應的佔用範圍,越界才看得出來
      for (const id of touched) {
        const files = actualWrites(state.events, id);
        state.scopes = state.scopes.map((s) => {
          if (s.agent_id !== id || s.state !== 'ACTIVE') return s;
          let next = s;
          for (const f of files) next = recordActualWrite(next, f);
          return next;
        });
      }

      return Object.freeze({
        accepted: r.events.length,
        skipped: r.skipped,
        skipped_by_reason: r.skipped_by_reason,
        conflicts: windowConflicts(toWriteEvents(state.events), config.admission),
        label_drift: labelDrift(state.events),
        ambiguous_labels: ambiguousLabels(state.events),
      });
    },

    /**
     * 派工前問一句。這是唯一能在動手前攔下撞車的地方。
     *
     * 回傳 admission 的決策,原樣不加工。宿主自己決定要不要照做。
     * decision 為 ALLOW 時呼叫 openScope() 把佔用登記起來,
     * 不登記的話下一個人問的時候就看不到你。
     */
    requestWrite(request, { candidateFiles = null, importCounts = null, graph = null } = {}) {
      return decideAdmission(request, {
        scopes: state.scopes,
        locks: state.locks,
        now: now(),
        candidateFiles, importCounts, graph,
        config: config.admission,
      });
    },

    /** 登記一段佔用。requestWrite 放行之後才做。 */
    openScope({ agent_id, task_id, declared }) {
      const scope = createWriteScope({ agent_id, task_id, declared, declared_at: now() });
      state.scopes = [...state.scopes, scope];
      return scope;
    },

    /** 結束一段佔用,並回報它有沒有寫出界。 */
    closeScope(task_id) {
      const target = state.scopes.find((s) => s.task_id === task_id && s.state === 'ACTIVE');
      if (!target) return null;
      const out = outOfScopeWrites(target);
      state.scopes = state.scopes.map((s) => (s === target ? releaseScope(s) : s));
      return Object.freeze({ task_id, out_of_scope: Object.freeze(out) });
    },

    /**
     * 一輪做完了。回傳該往哪裡送,以及每一棒要轉述哪些背景。
     *
     * hasOutput 沒給的話,從事件推:這一輪碰過檔案才算有產出。
     * 什麼都沒動的一輪不觸發任何邊 —— 實跑抓到的失敗模式,
     * 一句「收到」被自動推給下游,兩邊都在燒錢做白工。
     */
    completeTurn({ agent_id, chain = [agent_id], hasOutput = null, isRunning = () => false }) {
      const turns = inferTurns(state.events, config.capture).filter((t) => t.agent_id === agent_id);
      const last = turns[turns.length - 1] ?? null;
      const output = hasOutput ?? (last ? last.has_output : false);

      const plan = planHandoff({
        fromNode: agent_id,
        edges: state.edges,
        chain,
        isRunning,
        hasOutput: output,
        config: config.handoff,
      });
      state.stats = applyStats(state.stats, plan, new Date(now()).toISOString());

      // 每一棒附上該轉述什麼,那是 M5 幫 M2 省下來的錢
      const from = state.coverages.get(agent_id) ?? null;
      const packets = plan.dispatch.map((d) => {
        const to = state.coverages.get(d.to) ?? null;
        const delta = (from && to) ? handoffDelta(from, to, config.coverage) : null;
        return buildHandoffPacket({ from: agent_id, to: d.to, result: 'turn_complete', delta });
      });

      return Object.freeze({ ...plan, packets: Object.freeze(packets), turn: last });
    },

    /** 人親手轉交一次。這個數字要往下掉,不記就看不出這套東西有沒有用。 */
    recordManualHandoff() {
      state.stats = recordManual(state.stats, new Date(now()).toISOString());
      return state.stats;
    },

    /** 放行一個閘門。 */
    releaseGate() {
      state.stats = releaseGate(state.stats);
      return state.stats;
    },

    /**
     * 設定交接規則。建規則的當下就擋掉環,不要等執行時靠 chain 防護。
     * 有環就整批拒絕並回報,不部分套用 —— 半套的規則圖比沒有更難查。
     */
    setEdges(edges) {
      const cycles = findCycles(edges);
      if (cycles.length) {
        return Object.freeze({ ok: false, cycles: Object.freeze(cycles), applied: false });
      }
      state.edges = [...edges];
      return Object.freeze({ ok: true, cycles: Object.freeze([]), applied: true });
    },

    /** 這個任務該派給誰:誰的 context 已經熱在那批檔案上。 */
    suggestAssignee(taskFiles) {
      return pickHottest(taskFiles, [...state.coverages.values()], config.coverage);
    },

    // ── 北極星與飄移(M7)──────────────────────────────

    /**
     * 釘北極星。宿主知道目標時就宣告,不知道就別叫這個,
     * 讓 driftCheck() 自己從前幾段推,推出來的錨點會標成 inferred。
     */
    setGoal(topics) {
      state.anchor = createAnchor({ declared: topics });
      return state.anchor;
    },

    /** 宿主宣告轉向。有宣告的方向改變不是飄移,是決定。 */
    declareTurn(at = now()) {
      state.declaredTurns = [...state.declaredTurns, at];
      return state.declaredTurns.length;
    },

    /**
     * 現在離北極星多遠。這是即時的,不是事後分析。
     *
     * 事後分析救不了任何人。這個函式要在每一輪做完時被叫,
     * 讓偏離在還能回頭的時候就講出來。
     */
    driftCheck({ recentSegments = 1, config = {} } = {}) {
      let segs = segment(state.events, { size: config.segmentSize ?? 50 });
      // 事件還不夠切成一整段時,用手上全部的當一段。
      // 即時告警要在早期就能開口,不然它只會在來不及的時候才講話。
      // 這種情況下如果沒有宣告過北極星,就真的判斷不了,因為錨點跟現況會是同一批資料。
      if (!segs.length) {
        if (!state.events.length) {
          return Object.freeze({ level: null, note: 'No events yet; direction cannot be judged.' });
        }
        if (!state.anchor) {
          return Object.freeze({
            level: null,
            note: 'Too few events to infer an anchor, and no goal was declared. Declare one with setGoal() to get a reading now.',
          });
        }
        const topics = new Map();
        for (const e of state.events) {
          const t = e.file_path.split('/').filter(Boolean).slice(0, 3).join('/');
          if (t) topics.set(t, (topics.get(t) ?? 0) + 1);
        }
        const declaredTurn = state.declaredTurns.some(
          (t) => t >= state.events[0].at - (config.turnWindowMs ?? 30 * 60 * 1000),
        );
        return Object.freeze({
          ...driftAlert({ recentTopics: topics, anchor: state.anchor, declaredTurn, config: config.drift }),
          verdict: null,
          segments: 0,
          anchor_topics: Object.freeze([...state.anchor.topics]),
          /** 樣本太少,這是早期讀數不是結論。 */
          early_reading: true,
        });
      }
      const anchor = state.anchor ?? createAnchor({ segments: segs, warmup: 3 });
      const recent = segs.slice(-recentSegments);
      const topics = new Map();
      for (const sg of recent) for (const [k, v] of sg.topics) topics.set(k, (topics.get(k) ?? 0) + v);

      // 最近有沒有人宣告過轉向
      const cutoff = recent[0].from;
      const declaredTurn = state.declaredTurns.some((t) => t >= cutoff - (config.turnWindowMs ?? 30 * 60 * 1000));

      const alert = driftAlert({ recentTopics: topics, anchor, declaredTurn, config: config.drift });
      const rows = trajectory(segs, anchor, config.drift);
      return Object.freeze({
        ...alert,
        verdict: classify(rows, config.drift),
        segments: rows.length,
        anchor_topics: Object.freeze([...anchor.topics]),
      });
    },

    /**
     * 哪些工作被放棄了,以及放棄的那一刻旁邊有沒有失敗訊號。
     *
     * 失敗與摩擦的時間點由宿主用 recordFailure / recordFriction 餵進來。
     * 這裡不讀任何文字,也不判斷任何人的情緒。
     */
    abandonedWork({ config = {} } = {}) {
      const ab = findAbandoned(state.events, { now: now(), config: config.drift });
      return escapeSignals(ab, { failures: state.failures, friction: state.friction, config: config.drift });
    },

    /** 記一次失敗。宿主自己決定什麼算失敗(工具錯誤、build 失敗、測試紅)。 */
    recordFailure(at = now()) { state.failures = [...state.failures, at]; return state.failures.length; },

    /** 記一次摩擦。怎麼判定使用者不滿是宿主的事,這裡只收時間點。 */
    recordFriction(at = now()) { state.friction = [...state.friction, at]; return state.friction.length; },

    // ── 來源鏈(M8)────────────────────────────────────

    /**
     * 登記一次委派。之後 provenanceAudit() 會檢查它有沒有產出。
     * 自白書那個案例:8 個 agent、1.4MB transcript、零產出,
     * 而且那個 workflow 還被拿來當「交叉驗證」增強對主產出的信心。
     */
    recordInvestment({ id, agents, tokens = null }) {
      const inv = { id, at: now(), agents, tokens, ended_at: null, produced_files: [] };
      state.investments = [...state.investments, inv];
      return inv;
    },

    /** 委派結束,附上它實際產出的檔案。沒有產出就傳空陣列,別編一個。 */
    closeInvestment(id, producedFiles = []) {
      state.investments = state.investments.map((i) =>
        (i.id === id ? { ...i, ended_at: now(), produced_files: [...producedFiles] } : i));
      return state.investments.find((i) => i.id === id) ?? null;
    },

    /**
     * 交付前查核一個宣稱:它點名的檔案是自己開過的,還是別人回報的。
     *
     * 這是即時的攔截點。宿主在把一份報告交給人之前叫它,
     * 而不是等對方發現之後回頭查。
     *
     * @param {object} claim { files?: string[], claimed_count?: number }
     */
    checkClaim(claim, { config = {} } = {}) {
      const at = claim.at ?? now();
      const withAt = { ...claim, at };
      const findings = [];
      const a = checkSourceErasure(withAt, state.events, config.provenance);
      if (a) findings.push(a);
      const b = checkScopeInflation(withAt, state.events, config.provenance);
      if (b) findings.push(b);
      return Object.freeze({
        findings: Object.freeze(findings),
        clean: findings.length === 0,
        checked_shapes: SHAPES,
        unchecked_shapes: OUT_OF_SCOPE,
        /** 三個形狀過了不等於乾淨。四個沒驗的必須跟結果一起講。 */
        note: findings.length === 0
          ? 'Clear on the three checkable shapes; four others were not examined.'
          : `${findings.length} finding(s) on three checkable shapes; four others were not examined.`,
      });
    },

    /** 一整批宣稱加上所有委派的完整查核。 */
    provenanceAudit(claims = [], { config = {} } = {}) {
      return audit({
        claims: claims.map((c) => ({ ...c, at: c.at ?? now() })),
        events: state.events,
        investments: state.investments,
        config: config.provenance,
      });
    },

    /**
     * 現在這一段的證據有多少是自己查的。
     *
     * 這是那條界線的即時讀數:第一手是自己跑的工具,
     * 委派是別人查的,自產是讀回自己寫的檔案。
     * 整段平均會把問題稀釋掉,所以這個要配合 checkClaim 逐宣稱看。
     */
    evidenceMix({ lastMs = 30 * 60 * 1000 } = {}) {
      const to = now();
      // 用原始工具呼叫,不用採集層過濾後的事件:委派沒有檔案,但它正是要問的東西。
      return originMix(state.toolCalls, { from: to - lastMs, to, selfWritten: state.selfWritten });
    },

    /**
     * 現在的狀況。這裡刻意把「不知道的事」也列出來。
     *
     * capture_rate 是所有答案的品質上限:採集漏掉的東西,
     * 後面七個模組沒有一個補得回來。
     */
    status() {
      const health = captureHealth({
        total: state.capture.total,
        skipped: state.capture.skipped,
        skipped_by_reason: state.capture.skipped_by_reason,
      });
      const segs = segment(state.events, { size: 50 });
      const anchor = state.anchor ?? (segs.length ? createAnchor({ segments: segs, warmup: 3 }) : null);
      const recent = segs.length ? segs.at(-1).topics : null;
      const drift = (anchor && recent)
        ? driftAlert({ recentTopics: recent, anchor, declaredTurn: false })
        : null;
      const mix = originMix(state.toolCalls, {
        from: now() - 30 * 60 * 1000, to: now(), selfWritten: state.selfWritten,
      });

      return Object.freeze({
        capture: health,
        automation_rate: automationRate(state.stats),
        stats: state.stats,
        active_scopes: state.scopes.filter((s) => s.state === 'ACTIVE').length,
        known_agents: [...state.coverages.keys()].sort(),
        event_count: state.events.length,
        /** 離北極星多遠。錨點是推出來的時 confidence 會標明。 */
        drift,
        /** 最近半小時的證據有多少是自己查的。整段平均會稀釋問題,配合 checkClaim 逐宣稱看。 */
        evidence: mix,
        /** 燒了資源卻零產出的委派。 */
        barren: checkBarrenInvestment(state.investments),
        /** 拿不到的資料一律列在這裡,不用預設值蓋過去。 */
        unavailable: Object.freeze([
          ...(state.edges.length ? [] : ['No handoff rules configured; completeTurn will dispatch nothing']),
          ...(health.capture_rate === null ? ['No events received yet'] : []),
          ...(health.capture_rate !== null && health.capture_rate < 1
            ? [`Capture dropped ${state.capture.skipped} event(s) (largest cause: ${health.worst_reason?.reason}); every answer below is computed from incomplete data`]
            : []),
          ...(state.anchor ? [] : ['No goal declared; drift is measured against an inferred anchor and is weaker for it']),
          ...(state.failures.length || state.friction.length ? [] : ['No failure or friction signals recorded; abandoned work cannot be told apart from finished work']),
        ]),
      });
    },

    /** 存檔用的字串。宿主自己決定放哪裡。 */
    save() {
      return serialize(createSnapshot({
        scopes: state.scopes,
        locks: state.locks,
        capsules: state.capsules,
        coverages: [...state.coverages.values()],
        stats: state.stats,
        edges: state.edges,
        at: now(),
        // 北極星必須跨重啟活著。忘了目標之後,飄移就再也量不出來了。
        goal: state.anchor ? { topics: [...state.anchor.topics], inferred: state.anchor.inferred } : null,
        signals: {
          declaredTurns: state.declaredTurns,
          failures: state.failures,
          friction: state.friction,
          selfWritten: state.selfWritten,
          investments: state.investments,
        },
      }));
    },

    /**
     * 從存檔還原。
     *
     * 回傳裡的 stale_scopes 需要宿主處理:那些是重啟前正在寫的 agent,
     * 這裡不替你判斷它們還活不活著。在你確認之前它們仍然擋人,
     * 因為保守的那一邊比較便宜。
     */
    restore(text) {
      const r = load(text, { now: now() });
      if (!r.state) return r;
      state.scopes = [...r.state.scopes];
      state.locks = [...r.state.locks];
      state.capsules = [...(r.state.capsules ?? [])];
      state.edges = [...(r.state.edges ?? [])];
      state.stats = r.state.stats ?? createStats();
      state.coverages = new Map((r.state.coverages ?? []).map((c) => [c.agent_id, c]));
      const g = r.state.goal;
      state.anchor = g ? createAnchor({ declared: g.inferred ? null : g.topics }) : null;
      const sig = r.state.signals ?? {};
      state.declaredTurns = [...(sig.declaredTurns ?? [])];
      state.failures = [...(sig.failures ?? [])];
      state.friction = [...(sig.friction ?? [])];
      state.selfWritten = sig.selfWritten instanceof Set ? new Set(sig.selfWritten) : new Set(sig.selfWritten ?? []);
      state.investments = [...(sig.investments ?? [])];
      return r;
    },

    /** 內部狀態的唯讀檢視。沒有藏起來的東西。 */
    inspect() {
      return Object.freeze({
        events: Object.freeze([...state.events]),
        scopes: Object.freeze([...state.scopes]),
        coverages: Object.freeze([...state.coverages.values()]),
        edges: Object.freeze([...state.edges]),
        stats: state.stats,
        anchor: state.anchor,
        investments: Object.freeze([...state.investments]),
        self_written: Object.freeze([...state.selfWritten].sort()),
      });
    },
  });
}
