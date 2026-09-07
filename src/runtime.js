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
import {
  createBeatState, planBeat, judgeBeat, applyBeat, nextInterval, dispatchPlan,
} from './heartbeat.js';
import {
  reading, zoneOf, compactionDelta, curve, advice,
} from './thermometer.js';
import { expandBashEvent } from './shell.js';
import { buildImportRecords } from './imports.js';
import { verifyClaim, artifactNullity, summarize as summarizeArtifacts } from './artifact.js';
import {
  s1ToolOccupancy, s2SilentExecution, s3OutputCompression, s4RetryRepetition, s5ArtifactNullity,
  s6CorrectionLoad, s7ProgressStagnation, s8ClaimEvidenceGap, s9CancellationPressure,
  s10StrategyPersistence, composite,
} from './signals.js';
import { bucketize, findPeaks, findChangePoints, findMotifs, selectWindows } from './windows.js';
import {
  createSnapshot as createRecoverySnapshot, silentExecutionRatio, unsafeInterruptRate,
  interruptReadiness, livenessReport,
} from './rescue.js';
import {
  buildProbe, evaluateProbe, canIntervene, recordIntervention, interventionRate,
} from './intervention.js';
import { buildGraph, computeCostVector } from './cost.js';
import {
  createCapsule, createBudget, createContract, remainingBudget,
  previewCapsule, acceptCapsule, rejectCapsule, validateReturnShape,
  shouldAutoAccept, manualReviewRate, blockedRawTokens,
} from './capsule.js';

/**
 * 建一個 runtime。
 *
 * @param {object} p
 * @param {() => number} [p.now]  拿現在時間。預設用系統時鐘,測試時請注入。
 * @param {object} [p.config]     各模組的設定覆寫,依模組名分組
 */
/**
 * 存檔保留多久的事件。
 * 【十分鐘沒有實測校準。】它只需要比最長的時間窗寬就夠,
 * 目前最長的是撞車偵測的十五秒。留寬一點是為了讓宿主自己調窗口時不會突然失效。
 */
const EVENT_RETENTION_MS = 10 * 60 * 1000;
/** 存檔最多留幾筆事件。狀態檔不該無限長大。 */
const MAX_KEPT_EVENTS = 2000;

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
    /** 心跳狀態。空轉計數要跨輪活著,不然「連續空轉」永遠數不到。 */
    beat: createBeatState(),
    /** 上一輪心跳時的產出基準,用來算這一輪產出了什麼。 */
    lastProducedMark: 0,
    /** 溫度讀數的歷史。趨勢要靠多筆才看得出來。 */
    readings: [],
    /** 每一次壓縮的前後對照。 */
    compactions: [],
    /** 看不透的 shell 命令次數。它們動了什麼看不出來,但看得出來有這件事。 */
    opaqueCommands: 0,
    /** context 預算。宿主要餵 provider 的真實用量,拿不到就標 ESTIMATED。 */
    budget: null,
    /** 契約,以 contract_id 索引。 */
    contracts: new Map(),
    /** 依賴圖。沒有它就算不出改一個檔案的代價。 */
    graph: null,
    graphStats: null,
    /** 產物驗證結果。這是 heartbeat 的 verified_progress 的唯一合格來源。 */
    artifacts: [],
    /** 上一輪心跳時已驗證的產物數,用來算這一輪新增了幾項。 */
    lastVerifiedMark: 0,
    /** 可見存活的心跳時間點。沒有它就分不出「安靜在做」跟「掛了」。 */
    beats: [],
    /** 中斷紀錄,每一筆帶當時的快照(或沒有)。 */
    interruptions: [],
    /** 目前這一輪的復原快照。中斷前要能拿得出來。 */
    snapshot: null,
    /** 介入紀錄。有注入的會污染後續觀測,所以一定要記。 */
    interventions: [],
    /** 使用者的回合數,用來算實際介入率。 */
    turns: 0,
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

      // shell 命令要先展開,不然透過 shell 改檔案這條路完全看不到。
      // 第一次把採集層接上真實記錄時,漏掉這一段讓採集率只有 19.6%,
      // 而下游照樣給出乾淨自信的答案。
      const expanded = [];
      for (const raw of (rawEvents ?? [])) {
        const name = String(raw?.name ?? raw?.tool_name ?? raw?.type ?? '');
        if (/^Bash$/i.test(name)) {
          const x = expandBashEvent(raw);
          state.opaqueCommands += x.opaque_commands;
          expanded.push(...x.events);
        } else {
          expanded.push(raw);
        }
      }

      const r = normalizeStream(expanded);
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
        /** 這批裡有幾條 shell 命令是靜態看不透的。它們動了什麼不知道。 */
        opaque_commands: state.opaqueCommands,
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

    /**
     * 最近有誰寫過這個檔案。
     *
     * 這是不靠顯式宣告的撞車偵測。宿主如果是 hook 這種無狀態的短命程序,
     * 沒有人會去 openScope,但「最近誰動過這個檔」在事件流裡一直都在。
     * 真實資料上唯一抓到的一次跨 session 撞車就是這樣看到的:
     * 兩邊在十幾秒內寫同一個協調檔。
     *
     * @returns {Array<{agent_id, at, seconds_ago}>} 不含自己,最近的排前面
     */
    recentWritersOf(file, { windowMs = 15_000, excludeAgent = null, at = null } = {}) {
      const t = at ?? now();
      const hits = state.events.filter((e) =>
        e.action === 'WRITE' && e.file_path === file &&
        e.at <= t && e.at >= t - windowMs &&
        (excludeAgent === null || e.agent_id !== excludeAgent));
      const seen = new Map();
      for (const e of hits) {
        const prev = seen.get(e.agent_id);
        if (!prev || e.at > prev.at) seen.set(e.agent_id, e);
      }
      return Object.freeze([...seen.values()]
        .sort((a, b) => b.at - a.at)
        .map((e) => Object.freeze({ agent_id: e.agent_id, at: e.at, seconds_ago: (t - e.at) / 1000 })));
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
          goal_state: state.anchor.goal_state,
          segments: 0,
          anchor_topics: Object.freeze([...state.anchor.topics]),
          display: 'Early reading from very few events; not a conclusion.',
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
      // anchor 一定要傳進 classify:GoalState 的把關全在裡面。
      // 漏掉這個參數,AMBIGUOUS 與 MISSING 的早退不會發生,
      // 工具會對著一個不可靠的目標下硬結論。驗收測試 AT-DRIFT-01 抓到的。
      const verdict = classify(rows, config.drift, anchor);
      return Object.freeze({
        ...alert,
        verdict,
        /** 目標可靠度。不可靠時 verdict.is_drift 會是 null。 */
        goal_state: anchor.goal_state,
        segments: rows.length,
        anchor_topics: Object.freeze([...anchor.topics]),
        /** 目標不可靠時,這句話是唯一該顯示給人看的東西。 */
        display: verdict.is_drift === null
          ? verdict.reason
          : (verdict.is_drift ? 'Direction moved without anyone changing it.' : 'Still within the declared goal.'),
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
        /** 規格書第 3.2 節的複合溫度。用多少比重的資料算的,看 measured_weight。 */
        runtime_temperature: composite([
          s4RetryRepetition(state.toolCalls.slice(-200).map((c) => ({ tool: c.name, target: c.file_path }))),
          s5ArtifactNullity(artifactNullity(state.artifacts)),
          s7ProgressStagnation((() => {
            const lv = [...state.artifacts].filter((a) => a.verdict === 'VERIFIED').sort((a, b) => b.at - a.at)[0];
            return { lastVerifiedAt: lv?.at ?? null, now: lv ? now() : null };
          })()),
        ], config.signals),
        /** 宣稱的產物有多少站得住。沒驗過任何東西時 total 為 0。 */
        artifacts: Object.freeze({
          ...summarizeArtifacts(state.artifacts),
          nullity: artifactNullity(state.artifacts),
        }),
        /** context 幾度。沒讀數就 null,這個量測只有 runtime 做得到。 */
        temperature: state.readings.length
          ? Object.freeze({ ...state.readings.at(-1), zone: zoneOf(state.readings.at(-1)) })
          : null,
        /** 拿不到的資料一律列在這裡,不用預設值蓋過去。 */
        unavailable: Object.freeze([
          ...(state.edges.length ? [] : ['No handoff rules configured; completeTurn will dispatch nothing']),
          ...(health.capture_rate === null ? ['No events received yet'] : []),
          ...(health.capture_rate !== null && health.capture_rate < 1
            ? [`Capture dropped ${state.capture.skipped} event(s) (largest cause: ${health.worst_reason?.reason}); every answer below is computed from incomplete data`]
            : []),
          ...(state.anchor ? [] : ['No goal declared; drift is measured against an inferred anchor and is weaker for it']),
          ...(state.failures.length || state.friction.length ? [] : ['No failure or friction signals recorded; abandoned work cannot be told apart from finished work']),
          ...(state.readings.length ? [] : ['No temperature reading; the share of context that is checked evidence is unknown']),
          ...(state.artifacts.length ? [] : ['No artifact claims verified; idle detection is off because activity is not accepted as proof of progress']),
          ...(state.beats.length ? [] : ['No visible heartbeats recorded; a user cannot tell working-quietly from hung']),
          ...(state.snapshot?.usable ? [] : ['No usable recovery snapshot; an interruption right now would lose the working state']),
          ...(state.graph ? [] : ['No dependency graph indexed; the cost of changing a file cannot be computed']),
          ...(state.budget ? [] : ['No context budget set; nothing is tracking what agent output costs the main session']),
          ...(state.opaqueCommands > 0
            ? [`${state.opaqueCommands} shell command(s) were opaque to static analysis; whatever files they touched are invisible here`]
            : []),
        ]),
      });
    },

    // ── 原子訊號與複合溫度(規格書第 3 節)────────────────

    /**
     * 算出這一刻的十個原子訊號。
     *
     * runtime 自己算得出來的只有四個(S1、S4、S5、S7),
     * 因為其他六個需要的東西不在事件流裡:
     *
     *   S2 需要「使用者看得見的動靜」的定義,那是宿主的 UI 概念
     *   S3 需要這個使用者自己的健康基線,不是一個全域常數
     *   S6 需要把糾正跟新需求分開,那要讀文字
     *   S8 需要「實質宣稱」的定義與證據契約
     *   S9 需要中斷事件,hook 拿不到
     *   S10 需要反證事件,那是人或另一個系統判定的
     *
     * 拿不到的一律回 null 並列在 unmeasured,不用預設值頂替。
     * 複合溫度會告訴你它是用多少比重的資料算出來的。
     *
     * @param {object} extra 宿主算得出來的那幾個,直接傳進來
     */
    signals(extra = {}) {
      const t = now();
      const win = config.signals?.windowMs ?? 10 * 60 * 1000;
      const recent = state.toolCalls.filter((c) => c.at >= t - win);

      const lastVerified = [...state.artifacts]
        .filter((a) => a.verdict === 'VERIFIED')
        .sort((a, b) => b.at - a.at)[0] ?? null;

      return Object.freeze([
        extra.s1 ?? s1ToolOccupancy(extra.toolOccupancy ?? {}),
        extra.s2 ?? s2SilentExecution(extra.liveness ?? {}),
        extra.s3 ?? s3OutputCompression(extra.output ?? {}),
        s4RetryRepetition(recent.map((c) => ({ tool: c.name, target: c.file_path }))),
        s5ArtifactNullity(artifactNullity(state.artifacts)),
        extra.s6 ?? s6CorrectionLoad(extra.corrections ?? {}),
        s7ProgressStagnation({ lastVerifiedAt: lastVerified?.at ?? null, now: lastVerified ? t : null }),
        extra.s8 ?? s8ClaimEvidenceGap(extra.claims ?? {}),
        extra.s9 ?? s9CancellationPressure(extra.interruptions ?? {}),
        extra.s10 ?? s10StrategyPersistence(extra.strategy ?? {}),
      ]);
    },

    /**
     * 複合溫度 T_runtime。規格書第 3.2 節。
     *
     * 回傳一定帶貢獻最大的訊號 —— 單一純量沒有解釋,規格書判它不合格。
     * 也一定帶 measured_weight:這個分數是用多少比重的資料算出來的。
     */
    runtimeTemperature(extra = {}) {
      return composite(this.signals(extra), config.signals);
    },

    // ── 介入(規格書第 9、10、11 節)────────────────────

    /**
     * 這個介入動作現在可不可以做。
     *
     * 高溫從來不是單獨的理由。一個只看溫度就出手的系統,
     * 會在第一次誤判之後被關掉,而被關掉的防線保護不了任何人。
     */
    mayIntervene(action, extra = {}) {
      const temp = this.runtimeTemperature();
      const lv = [...state.artifacts].filter((a) => a.verdict === 'VERIFIED').sort((a, b) => b.at - a.at)[0];
      const stagnant = lv
        ? (now() - lv.at) > (config.signals?.stagnationFullMs ?? 30 * 60 * 1000)
        : undefined;
      return canIntervene(action, {
        temperature: temp.temperature,
        progress_stagnation: extra.progress_stagnation ?? stagnant,
        checkpoint_available: extra.checkpoint_available ?? (state.snapshot?.usable === true),
        ...extra,
      });
    },

    /**
     * 產生一個診斷探針。
     *
     * 它不問「你是不是飄移了」—— 那只會拿到流利的否認,而流利不是證據。
     * 它問連結與證據,而且問這件事本身就是一次介入,所以會自動記錄。
     */
    probe({ reason = null, windowRef = null } = {}) {
      const p = buildProbe({ reason, windowRef });
      state.interventions = recordIntervention(state.interventions, {
        at: now(), action: 'PROBE', reason, injected: true,
      });
      return p;
    },

    /**
     * 評估探針回答。
     *
     * 自述跟可觀測記錄衝突時,可觀測的勝出。規格書 AT-PROBE-01。
     */
    evaluateProbeAnswers(answers, extra = {}) {
      const lv = [...state.artifacts].filter((a) => a.verdict === 'VERIFIED').length;
      const recent = [...new Set(state.events.slice(-200).map((e) => e.file_path))];
      return evaluateProbe(answers, { verified_progress: lv, recent_files: recent, ...extra });
    },

    /** 記一次非注入式的介入(標註、建議),不污染觀測但仍要記。 */
    noteIntervention(action, reason = null) {
      state.interventions = recordIntervention(state.interventions, {
        at: now(), action, reason, injected: false,
      });
      return state.interventions.length;
    },

    /** 使用者說了一句話。用來算實際介入率的分母。 */
    countTurn() { state.turns += 1; return state.turns; },

    /**
     * 實際的介入率。
     *
     * 規格書第 9 節:OBSERVE 99% / INTERRUPT 1% 是哲學不是常數,
     * 實作必須量實際的中斷率。所以這個數字要看得到。
     */
    interventionStats() {
      return Object.freeze({
        ...interventionRate(state.interventions, state.turns),
        log: Object.freeze([...state.interventions]),
      });
    },

    // ── 可見存活與安全中斷(規格書第 7 節)──────────────

    /**
     * 打一次可見的心跳。
     *
     * 這跟 beat() 是兩件事:beat() 是內部檢查,這個是「讓使用者看得到還活著」。
     * 沒有這個,使用者分不出安靜在做事跟掛掉了,而那個不確定的成本
     * 往往比中斷本身還高 —— 所以她會中斷。
     */
    heartbeat(at = now()) {
      state.beats = [...state.beats, at].slice(-500);
      return state.beats.length;
    },

    /**
     * 更新目前的復原快照。
     *
     * 規格書第 7 節要求中斷之前或之時建立快照。這個函式讓宿主
     * 在工作推進時持續更新它,而不是等到要中斷的那一刻才臨時湊。
     * 臨時湊的快照通常缺 exact_next_step,而那正是唯一真正省時間的欄位。
     */
    updateSnapshot(fields) {
      state.snapshot = createRecoverySnapshot({ ...fields, timestamp: fields.timestamp ?? now() });
      return state.snapshot;
    },

    /** 現在中斷安不安全。宿主在真的中斷之前叫這個。 */
    canInterrupt() {
      const lv = [...state.artifacts].filter((a) => a.verdict === 'VERIFIED').sort((a, b) => b.at - a.at)[0];
      return interruptReadiness({
        snapshot: state.snapshot,
        openToolCalls: [],
        lastVerifiedAt: lv?.at ?? null,
        now: lv ? now() : null,
      });
    },

    /**
     * 記一次中斷,連同當時手上的快照。
     *
     * 沒有快照也要記 —— 不安全中斷率就是靠這些筆數算出來的,
     * 把沒快照的中斷漏掉,那個比率永遠會是零。
     */
    recordInterrupt(at = now()) {
      const entry = Object.freeze({ at, snapshot: state.snapshot });
      state.interruptions = [...state.interruptions, entry];
      return entry;
    },

    /**
     * 第 7 節那三個指標一起看。
     *
     * 三個都拿不到時會明說。三個 null 不是健康,是沒量。
     */
    liveness({ activeFrom = null, activeTo = null } = {}) {
      const lv = [...state.artifacts].filter((a) => a.verdict === 'VERIFIED').sort((a, b) => b.at - a.at)[0];
      const from = activeFrom ?? (state.events[0]?.at ?? null);
      const to = activeTo ?? now();
      return Object.freeze({
        ...livenessReport({
          silent: from != null ? silentExecutionRatio(state.beats, { activeFrom: from, activeTo: to }) : null,
          unsafe: unsafeInterruptRate(state.interruptions),
          lastVerifiedAgeMs: lv ? now() - lv.at : null,
        }),
        snapshot_ready: state.snapshot?.usable ?? false,
      });
    },

    // ── 可疑窗口(規格書第 5 節)────────────────────────

    /**
     * 找出值得細看的幾段,而不是把整個 session 送去語意分析。
     *
     * 規格書第 5 節把全 session 語意讀取列為例外。真正的理由不是省錢:
     * 幾十萬行裡的一個異常,對語意模型來說跟雜訊沒有差別;
     * 收窄之後送三千行,那個異常佔的比重大了兩個數量級。
     *
     * 回傳的每個窗口都標著 result_epistemic_ceiling: 'INFERRED' ——
     * 語意分析讀了原文,結論還是推論,不會因此升級。
     */
    suspiciousWindows(opts = {}) {
      const buckets = bucketize(state.events, opts);
      if (!buckets.length) {
        return Object.freeze({
          windows: Object.freeze([]),
          considered: 0,
          note: 'No events indexed yet.',
        });
      }
      const counts = buckets.map((b) => ({ index: b.index, from: b.from, value: b.count }));
      const writes = buckets.map((b) => ({
        index: b.index, from: b.from,
        value: b.events.filter((e) => e.action === 'WRITE').length,
      }));
      const candidates = [
        ...findPeaks(counts, opts),
        ...findChangePoints(counts, opts),
        ...findPeaks(writes, opts),
        ...findMotifs(buckets, (e) => `${e.tool}|${e.file_path}`, opts),
      ];
      return selectWindows(candidates, buckets, opts);
    },

    // ── 產物實在性(規格書第 6 節)──────────────────────

    /**
     * 驗一個宣稱。宿主去看過之後把觀測傳進來,這裡判斷它夠不夠格。
     *
     * 沒去看就傳 null:結果是 UNKNOWN,不是失敗。
     * 規格書第 1 節:UNKNOWN 不可以被轉換成成功或失敗。
     *
     * 這是 verified_progress 的唯一合格來源。心跳的空轉偵測靠它才打得開,
     * 因為「寫了幾個檔」在規格書 0.2 是明文禁止當進度證據的。
     */
    verifyArtifact(claim, observation) {
      const r = verifyClaim(claim, observation);
      state.artifacts = [...state.artifacts, Object.freeze({ ...r, at: now(), target: claim.target ?? null })];
      return r;
    },

    /**
     * 產物實在性的整體狀況。
     *
     * unchecked_ratio 一定要跟結果一起看:一份「零個被推翻」的報告,
     * 如果其實八成沒查過,跟一份真的查完都沒事的報告長得一模一樣。
     */
    artifactHealth() {
      return Object.freeze({
        ...summarizeArtifacts(state.artifacts),
        nullity: artifactNullity(state.artifacts),
      });
    },

    // ── 代價(M4)──────────────────────────────────────

    /**
     * 建依賴圖。宿主餵「檔名 → 原始碼」,這裡不讀檔案系統。
     *
     * 沒有這張圖,cost.js 的每個函式都寫好了卻算不出任何東西。
     * 這條線斷了很久,現在接上。
     */
    indexProject(sources) {
      const { imports, stats } = buildImportRecords(sources);
      state.graph = buildGraph(imports);
      state.graphStats = stats;
      return Object.freeze({
        files: stats.files,
        imports: stats.total,
        resolution_rate: stats.resolution_rate,
        /** 靜態解析看不到的動態載入次數。它們動了什麼不知道。 */
        dynamic_opaque: stats.dynamic_opaque,
        is_lower_bound: true,
      });
    },

    /**
     * 改這個檔案的代價。
     *
     * 五個維度,不合成單一分數 —— 合成會把唯一有用的東西毀掉:
     * 波及 200 個都有測試的檔案,比波及 12 個沒測試的安全。
     *
     * live_conflicts 是靜態工具給不出來的那一維:
     * 波及範圍裡有幾個檔案,此刻正被別人佔著。
     */
    costOf(file, { coverage = null } = {}) {
      if (!state.graph) {
        return Object.freeze({
          vector: null,
          note: 'No dependency graph. Call indexProject() with the project sources first.',
        });
      }
      const liveScopes = state.scopes
        .filter((sc) => sc.state === 'ACTIVE')
        .map((sc) => ({ files: [...sc.actual] }));
      return Object.freeze({
        vector: computeCostVector(state.graph, file, { coverage, liveScopes }),
        graph_resolution_rate: state.graphStats?.resolution_rate ?? null,
      });
    },

    // ── context 收銀台(M1)────────────────────────────

    /**
     * 設定 context 預算。
     *
     * source 必須明講是 provider 回報的還是估的。拿不到真值就標 ESTIMATED,
     * 不准不標也不准假裝是真值 —— 兩者差一個量級的時候,
     * 所有基於預算的判斷會整個歪掉,而且沒有人會發現。
     */
    setBudget(fields) {
      state.budget = createBudget({ ...fields, measured_at: fields.measured_at ?? now() });
      return Object.freeze({ ...state.budget, remaining: remainingBudget(state.budget) });
    },

    /** 登記一份契約。膠囊要符合它的 return_shape 跟 token 上限才收。 */
    setContract(fields) {
      const c = createContract(fields);
      state.contracts.set(c.contract_id, c);
      return c;
    },

    /**
     * 把一份 agent 產出包成膠囊,並且報價。
     *
     * 不做這一步的話,agent 的原始輸出會直接灌進主 session 的 context,
     * 而主 session 的 context 是有限且不可退款的資源。
     * 報價的意思是:在它進來之前,先看得到它要花多少。
     */
    quote(fields) {
      if (!state.budget) {
        return Object.freeze({
          capsule: null,
          quote: null,
          note: 'No budget set. Call setBudget() with the provider usage numbers before quoting.',
        });
      }
      const cap = createCapsule({ ...fields, produced_at: fields.produced_at ?? now() });
      const contract = state.contracts.get(cap.contract_ref) ?? null;
      // 報價本身就是 PENDING → PREVIEWED 那一步。回傳的膠囊已經是 PREVIEWED,
      // 這樣呼叫端拿到的東西可以直接 accept 或 reject,不用自己補一步。
      const p = previewCapsule(cap, state.budget);
      return Object.freeze({
        capsule: p.capsule,
        quote: p.quote,
        /** 便宜的膠囊自動放行,免得收銀台自己變成新的瓶頸。 */
        auto: contract ? shouldAutoAccept(cap, state.budget, contract) : false,
        contract_found: contract !== null,
      });
    },

    /**
     * 收下一份膠囊,扣預算。
     *
     * 契約不符會拋錯,那是刻意的。狀態機本身允許「人看過價錢就收下」,
     * 但 max_return_tokens 是硬上限 —— 超過的東西該先摘要再送,
     * 不是給人一個「我看過了」的按鈕就放行。所以這裡明確擋。
     */
    accept(capsule) {
      if (!state.budget) throw new TypeError('No budget set; call setBudget() first.');
      const contract = state.contracts.get(capsule.contract_ref);
      if (!contract) throw new TypeError(`Unknown contract: ${capsule.contract_ref}`);
      const shape = validateReturnShape(capsule, contract);
      if (!shape.ok) {
        throw new Error(`Capsule violates its contract: ${shape.reasons.join('; ')}`);
      }
      const out = acceptCapsule(capsule, state.budget, contract);
      state.budget = out.budget;
      state.capsules = [...state.capsules, out.capsule];
      return out;
    },

    /**
     * 退回一份膠囊。原始輸出留在外面,預算不動。
     * 只能退 quote() 回來的膠囊 —— 狀態機不允許跳過報價直接否決,
     * 因為沒看過價錢就否決,跟沒看過價錢就收下一樣是盲目的。
     */
    reject(capsule) {
      const c = rejectCapsule(capsule);
      state.capsules = [...state.capsules, c];
      return c;
    },

    /**
     * 收銀台現在的狀況。
     *
     * manual_review_rate 是這個機制有沒有反而變成瓶頸的唯一硬指標:
     * 人要親自看的比例太高,表示自動放行的門檻設錯了。
     */
    register() {
      if (!state.budget) {
        return Object.freeze({ budget: null, note: 'No budget set; context spending is not being tracked.' });
      }
      const contractsById = Object.fromEntries(state.contracts);
      return Object.freeze({
        budget: Object.freeze({ ...state.budget, remaining: remainingBudget(state.budget) }),
        capsules: state.capsules.length,
        /**
         * 收下的 token 進 reserved 而不是 consumed。
         * consumed 要等 provider 回報才算數 —— 這裡不假裝那件事已經發生。
         */
        reserved: state.budget.reserved,
        manual_review_rate: manualReviewRate(state.capsules, { budget: state.budget, contractsById }),
        /** 被擋在外面的原始 token 量。這是這個機制實際擋下多少東西的量。 */
        blocked_raw_tokens: blockedRawTokens(state.capsules),
      });
    },

    // ── 溫度計(M10)───────────────────────────────────

    /**
     * 記一筆溫度讀數。
     *
     * 量的不是「還剩多少空間」,是「手上這批 context 有多少是查過的」。
     * 這個數字只有在 runtime 當下量得到:事後從 transcript 看,
     * 看到的是全量記錄,不是壓縮後真正留在 context 裡的東西。
     *
     * @param {object} p 見 thermometer.reading()。拿不到 provider 的用量就標 ESTIMATED。
     */
    recordTemperature(p) {
      const r = reading(p);
      state.readings = [...state.readings, r];
      return Object.freeze({ ...r, zone: zoneOf(r), advice: advice(r) });
    },

    /**
     * 通知發生了一次壓縮,附上壓縮後的讀數。
     *
     * 這是溫度計最有價值的一刻:比對前後,看丟掉的是工具輸出還是自己的敘述。
     * 壓縮保留摘要丟掉細節,而摘要是模型自己寫的。
     */
    recordCompaction(afterReading) {
      const before = state.readings.at(-1) ?? null;
      const after = reading(afterReading);
      state.readings = [...state.readings, after];
      const delta = before ? compactionDelta(before, after) : null;
      if (delta) state.compactions = [...state.compactions, Object.freeze({ at: now(), ...delta })];
      return delta ?? Object.freeze({
        fact_ratio_drop: null,
        note: 'No earlier reading to compare against; record one before the next compaction.',
      });
    },

    /** 現在幾度,以及該不該現在就把證據落檔。 */
    temperature() {
      const last = state.readings.at(-1) ?? null;
      if (!last) {
        return Object.freeze({
          zone: null,
          note: 'No temperature reading yet. Call recordTemperature() with the provider\'s usage numbers.',
        });
      }
      return Object.freeze({
        ...last,
        zone: zoneOf(last),
        advice: advice(last),
        trend: curve(state.readings),
        compactions: Object.freeze([...state.compactions]),
      });
    },

    // ── 心跳(M9)──────────────────────────────────────

    /**
     * 跑一輪心跳。宿主的排程器叫它,它不自己排程。
     *
     * 回傳裡有三件事:這一輪的結論、下一次該多久之後再來、
     * 以及要派哪些 agent 去查。派出去的東西走 recordInvestment,
     * 沒交東西下一輪就會被零產出偵測抓到,這條迴路是閉的。
     *
     * @param {object} opts
     * @param {number|null} opts.produced 這一輪有幾項經過驗證契約確認的推進。
     *   不給就是 null,空轉偵測會關掉並明說 —— 活動量不接受當成進度證據。
     * @param {string[]} opts.agents 現在有哪些 agent 可派
     */
    beat({ produced = null, agents = [], config = {} } = {}) {
      const at = now();
      const plan = planBeat(state.beat, {
        hasGoal: state.anchor !== null,
        hasSignals: state.failures.length > 0 || state.friction.length > 0,
      });

      // v0.2:不再拿寫入檔案數當產出。規格書 0.2 明令
      // MUST NOT treat activity, tool calls, or file names as proof of progress。
      //
      // 合格的來源只有一個:經過 verifyArtifact 確認的產物。
      // 宿主自己傳 produced 也可以,但沒傳而且沒驗過任何產物時就是 null,
      // 空轉偵測整個關掉並明說 —— 那比拿活動量頂替誠實。
      let verifiedNow = produced ?? null;
      if (verifiedNow === null && state.artifacts.length > 0) {
        const done = state.artifacts.filter((a) => a.verdict === 'VERIFIED').length;
        verifiedNow = done - state.lastVerifiedMark;
        state.lastVerifiedMark = done;
      }

      const drift = this.driftCheck({ config });
      const health = captureHealth({
        total: state.capture.total,
        skipped: state.capture.skipped,
        skipped_by_reason: state.capture.skipped_by_reason,
      });
      const barren = checkBarrenInvestment(state.investments, config.provenance);
      const lastReading = state.readings.at(-1) ?? null;
      const zone = lastReading ? zoneOf(lastReading, config.thermometer) : null;

      const judged = judgeBeat({
        capture_rate: health.capture_rate,
        drift_level: drift.level,
        drift_unannounced: drift.is_unannounced ?? false,
        barren_count: barren.length,
        new_provenance: 0,   // 宿主要查宣稱的話自己叫 checkClaim,心跳不猜有哪些宣稱
        verified_progress: verifiedNow,
      }, state.beat, config.heartbeat);

      state.beat = applyBeat(state.beat, plan, judged, at);

      return Object.freeze({
        beat: plan.beat,
        checked: plan.checks,
        weakened: plan.weakened,
        verdict: judged.verdict,
        reasons: judged.reasons,
        note: judged.note,
        verified_progress: verifiedNow,
        barren_streak: judged.barren_streak,
        unverifiable_streak: judged.unverifiable_streak,
        idle_detection_active: judged.idle_detection_active,
        next: nextInterval(judged, config.interval),
        dispatch: dispatchPlan(judged, { available: agents }),
        drift,
        /** 手上的證據有多少比例是查過的。沒讀數就 null,不猜。 */
        temperature: lastReading
          ? Object.freeze({ zone, fact_ratio: lastReading.fact_ratio, advice: advice(lastReading, config.thermometer) })
          : null,
      });
    },

    /** 心跳的歷史。連續空轉幾輪、上一輪結論是什麼,看這裡。 */
    beatLog() { return state.beat; },

    /** 存檔用的字串。宿主自己決定放哪裡。 */
    save() {
      return serialize(createSnapshot({
        scopes: state.scopes,
        locks: state.locks,
        capsules: state.capsules,
        budget: state.budget,
        coverages: [...state.coverages.values()],
        stats: state.stats,
        edges: state.edges,
        // 只留最近的事件。撞車偵測只看得到最近幾十秒,而狀態檔不該無限長大。
        // 保留期比任何一個時間窗都寬,但不是全部歷史 —— 那是 transcript 的工作。
        events: state.events.filter((e) => e.at >= now() - EVENT_RETENTION_MS).slice(-MAX_KEPT_EVENTS),
        at: now(),
        // 北極星必須跨重啟活著。忘了目標之後,飄移就再也量不出來了。
        goal: state.anchor ? { topics: [...state.anchor.topics], inferred: state.anchor.inferred } : null,
        signals: {
          beat: state.beat,
          lastProducedMark: state.lastProducedMark,
          readings: state.readings,
          compactions: state.compactions,
          artifacts: state.artifacts,
          lastVerifiedMark: state.lastVerifiedMark,
          beats: state.beats,
          interruptions: state.interruptions,
          snapshot: state.snapshot,
          interventionLog: state.interventions,
          turns: state.turns,
          contracts: [...state.contracts.values()],
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
      state.events = [...(r.state.events ?? [])];
      state.toolCalls = state.events.map((e) => ({ at: e.at, name: e.tool, file_path: e.file_path }));
      state.coverages = new Map((r.state.coverages ?? []).map((c) => [c.agent_id, c]));
      const g = r.state.goal;
      state.anchor = g ? createAnchor({ declared: g.inferred ? null : g.topics }) : null;
      const sig = r.state.signals ?? {};
      state.declaredTurns = [...(sig.declaredTurns ?? [])];
      state.failures = [...(sig.failures ?? [])];
      state.friction = [...(sig.friction ?? [])];
      state.selfWritten = sig.selfWritten instanceof Set ? new Set(sig.selfWritten) : new Set(sig.selfWritten ?? []);
      state.investments = [...(sig.investments ?? [])];
      state.beat = sig.beat ?? createBeatState();
      state.lastProducedMark = sig.lastProducedMark ?? 0;
      state.readings = [...(sig.readings ?? [])];
      state.compactions = [...(sig.compactions ?? [])];
      state.artifacts = [...(sig.artifacts ?? [])];
      state.lastVerifiedMark = sig.lastVerifiedMark ?? 0;
      state.beats = [...(sig.beats ?? [])];
      state.interruptions = [...(sig.interruptions ?? [])];
      state.snapshot = sig.snapshot ?? null;
      state.interventions = [...(sig.interventionLog ?? [])];
      state.turns = sig.turns ?? 0;
      state.budget = r.state.budget ?? null;
      state.contracts = new Map((sig.contracts ?? []).map((c) => [c.contract_id, c]));
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
