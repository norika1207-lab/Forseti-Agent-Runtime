// Forseti 端到端：一串原始工具呼叫進來，六個模組串起來給出可執行的判斷。
//
// 前面每個模組的測試只證明「這個零件自己是對的」。
// 這一份要證明的是另一件事：它們接得起來，而且接起來之後
// 回答的是真實情境裡真正會被問到的問題。
//
// 場景取自實跑環境：兩個 agent 同時在同一個專案上工作。
import assert from 'node:assert/strict';
import { normalizeStream, coverageDepthOf, toWriteEvents, actualWrites, inferTurns, captureHealth } from '../src/capture.js';
import { coverageFromEvents, handoffDelta, pickHottest, overlapRatio } from '../src/coverage.js';
import { windowConflicts, createWriteScope, recordActualWrite, outOfScopeWrites, decideAdmission } from '../src/admission.js';
import { planHandoff, createEdge, createStats, applyStats, automationRate, buildHandoffPacket } from '../src/handoff.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

const T0 = 1_700_000_000_000;
const ev = (agent, tool, file, offsetMs, label = null) => ({
  attributed_agent: agent, agent_label: label, name: tool,
  at: T0 + offsetMs, input: { file_path: file }, session_id: agent + '-sess',
});

// w1 在後端工作，w2 在前端工作，兩人都碰到 shared/config.js
const RAW = [
  ev('w1', 'Read',  'src/server.js',      0,      'Dev'),
  ev('w1', 'Read',  'shared/config.js',   1_000,  'Dev'),
  ev('w1', 'Edit',  'src/server.js',      3_000,  'Dev'),
  ev('w1', 'Grep',  'src/routes.js',      4_000,  'Dev'),

  ev('w2', 'Read',  'src/ui.js',          60_000, 'Audit'),
  ev('w2', 'Read',  'shared/config.js',   61_000, 'Audit'),
  ev('w2', 'Edit',  'shared/config.js',   63_000, 'Audit'),
  ev('w2', 'Edit',  'src/ui.js',          64_000, 'Audit'),
];

// ---------------------------------------------------------------------------
t('採集：八筆原始事件全部認得，沒有一筆被靜默丟掉', () => {
  const r = normalizeStream(RAW);
  assert.equal(r.events.length, 8);
  assert.equal(r.skipped, 0);
  assert.equal(captureHealth(r).capture_rate, 1);
});

t('採集 → M5：每個 agent 的覆蓋範圍算得出來，深度分得出強弱', () => {
  const { events } = normalizeStream(RAW);
  const w1 = coverageFromEvents({
    session_id: 'w1-sess', agent_id: 'w1',
    events: events.filter((e) => e.agent_id === 'w1'),
    toolDepth: coverageDepthOf,
  });
  assert.equal(w1.files['src/server.js'], 'EDITED');        // 讀過又改過，取最強
  assert.equal(w1.files['shared/config.js'], 'READ_FULL');
  assert.equal(w1.files['src/routes.js'], 'MENTIONED');     // 只被 grep 掃到
  assert.equal(w1.is_upper_bound, true);
});

t('採集 → M5：兩人的重疊算得出來，那是正在付兩次的錢', () => {
  const { events } = normalizeStream(RAW);
  const mk = (id) => coverageFromEvents({
    session_id: id + '-sess', agent_id: id,
    events: events.filter((e) => e.agent_id === id), toolDepth: coverageDepthOf,
  });
  const overlap = overlapRatio(mk('w1'), mk('w2'));
  assert.ok(overlap > 0 && overlap < 1, '兩人有交集但不完全重疊，實際: ' + overlap);
});

t('採集 → M5 → M2：交接時該轉述什麼，是集合減法不是判斷題', () => {
  const { events } = normalizeStream(RAW);
  const mk = (id) => coverageFromEvents({
    session_id: id + '-sess', agent_id: id,
    events: events.filter((e) => e.agent_id === id), toolDepth: coverageDepthOf,
  });
  const delta = handoffDelta(mk('w1'), mk('w2'));
  // config.js 兩邊都讀過，不用再講一次
  assert.ok(delta.saved_files.includes('shared/config.js'));
  // server.js 只有 w1 碰過，w2 接手要從頭讀
  assert.ok(delta.need_briefing.some((x) => x.file_path === 'src/server.js'));

  const pkt = buildHandoffPacket({ from: 'w1', to: 'w2', result: 'done', delta });
  assert.ok(pkt.briefing_files.includes('src/server.js'));
  assert.equal(pkt.has_coverage_data, true);
});

t('採集 → M3：兩人在窗口內寫同一個檔，衝突抓得到', () => {
  const { events } = normalizeStream([
    ...RAW,
    ev('w1', 'Edit', 'shared/config.js', 66_000),   // 比 w2 的寫入晚 3 秒
  ]);
  const conflicts = windowConflicts(toWriteEvents(events));
  assert.equal(conflicts.length, 1);
  assert.equal(conflicts[0].file_path, 'shared/config.js');
  assert.deepEqual([...conflicts[0].agents].sort(), ['w1', 'w2']);
  assert.equal(conflicts[0].gap_seconds, 3);
});

t('採集 → M3：只讀不寫不算衝突，這是刻意的', () => {
  const readOnly = [
    ev('w1', 'Read', 'shared/config.js', 0),
    ev('w2', 'Read', 'shared/config.js', 1_000),
  ];
  const { events } = normalizeStream(readOnly);
  assert.deepEqual(windowConflicts(toWriteEvents(events)), []);
});

t('採集 → M3：實際寫的檔案超出宣告範圍時抓得到', () => {
  const { events } = normalizeStream(RAW);
  let scope = createWriteScope({
    agent_id: 'w2', task_id: 'ui-work',
    declared: ['src/ui.js'],           // 只宣告要動前端
    declared_at: T0,
  });
  for (const f of actualWrites(events, 'w2')) scope = recordActualWrite(scope, f);
  // 實際上還動了 shared/config.js
  assert.deepEqual(outOfScopeWrites(scope), ['shared/config.js']);
});

t('採集 → M3：新任務要進來時，衝突在派工當下就擋住', () => {
  const active = [createWriteScope({
    agent_id: 'w2', task_id: 'ui-work',
    declared: ['shared/config.js'], declared_at: T0,
  })];
  const verdict = decideAdmission(
    { agent_id: 'w3', task_id: 'new', declared: ['shared/config.js'], declared_at: T0 + 1000 },
    { scopes: active, now: T0 + 1000 },
  );
  assert.notEqual(verdict.decision, 'ALLOW', '同一個檔案被兩人宣告時不該直接放行');
});

t('採集 → M2：一輪做完了，交接規則自己決定往哪送', () => {
  const { events } = normalizeStream(RAW);
  const turns = inferTurns(events);
  assert.equal(turns.length, 2, '兩人各一輪');

  const w1Turn = turns.find((x) => x.agent_id === 'w1');
  const edges = [createEdge({ id: 'e1', from: 'w1', to: 'w2' })];
  const plan = planHandoff({
    fromNode: 'w1', edges, chain: ['w1'],
    hasOutput: w1Turn.has_output,
    isRunning: () => false,
  });
  assert.deepEqual(plan.dispatch.map((d) => d.to), ['w2']);
});

t('採集 → M2：什麼都沒動的一輪不觸發交接，這是實跑燒過錢的那條', () => {
  const { events } = normalizeStream([]);   // 這一輪只回了一句話，沒動任何檔案
  const turns = inferTurns(events);
  assert.equal(turns.length, 0);
  const plan = planHandoff({
    fromNode: 'w1', edges: [createEdge({ id: 'e1', from: 'w1', to: 'w2' })],
    chain: ['w1'], hasOutput: turns.length > 0,
  });
  assert.equal(plan.dispatch.length, 0);
  assert.equal(plan.skipped_no_output, true);
});

t('M2 計數：自動化率能算，這是整套東西有沒有用的唯一硬指標', () => {
  const { events } = normalizeStream(RAW);
  const edges = [createEdge({ id: 'e1', from: 'w1', to: 'w2' })];
  let stats = createStats();
  for (const turn of inferTurns(events).filter((x) => x.agent_id === 'w1')) {
    stats = applyStats(stats, planHandoff({
      fromNode: 'w1', edges, chain: ['w1'], hasOutput: turn.has_output,
    }), new Date(turn.ended_at).toISOString());
  }
  assert.equal(stats.auto, 1);
  assert.equal(automationRate(stats), 1);   // 這一段全部由規則送出，人沒有按過
});

t('採集 → M5：新任務該派給誰，看誰的 context 已經熱在那批檔案上', () => {
  const { events } = normalizeStream(RAW);
  const mk = (id) => coverageFromEvents({
    session_id: id + '-sess', agent_id: id,
    events: events.filter((e) => e.agent_id === id), toolDepth: coverageDepthOf,
  });
  const pick = pickHottest(['src/server.js', 'src/routes.js'], [mk('w1'), mk('w2')]);
  assert.equal(pick.agent_id, 'w1', '後端檔案該派給已經讀過後端的那個');
});

t('採集品質掉下來時看得見，五個機制的答案上限就是它', () => {
  const dirty = [...RAW, { name: 'Read', at: T0, input: { file_path: 'x.js' } }];  // 宿主沒蓋章
  const r = normalizeStream(dirty);
  const h = captureHealth(r);
  assert.ok(h.capture_rate < 1);
  assert.equal(h.worst_reason.reason, 'NO_ATTRIBUTION');
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
