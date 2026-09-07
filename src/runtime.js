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
      const r = normalizeStream(rawEvents);
      state.events.push(...r.events);
      state.events.sort((a, b) => a.at - b.at);

      state.capture.total += r.total;
      state.capture.skipped += r.skipped;
      for (const [k, v] of Object.entries(r.skipped_by_reason)) {
        state.capture.skipped_by_reason[k] = (state.capture.skipped_by_reason[k] ?? 0) + v;
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
      return Object.freeze({
        capture: health,
        automation_rate: automationRate(state.stats),
        stats: state.stats,
        active_scopes: state.scopes.filter((s) => s.state === 'ACTIVE').length,
        known_agents: [...state.coverages.keys()].sort(),
        event_count: state.events.length,
        /** 拿不到的資料一律列在這裡,不用預設值蓋過去。 */
        unavailable: Object.freeze([
          ...(state.edges.length ? [] : ['No handoff rules configured; completeTurn will dispatch nothing']),
          ...(health.capture_rate === null ? ['No events received yet'] : []),
          ...(health.capture_rate !== null && health.capture_rate < 1
            ? [`Capture dropped ${state.capture.skipped} event(s) (largest cause: ${health.worst_reason?.reason}); every answer below is computed from incomplete data`]
            : []),
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
      });
    },
  });
}
