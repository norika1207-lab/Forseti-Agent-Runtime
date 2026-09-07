// Forseti M0：採集層。
// 這個模組是五個機制的資料入口，它漏掉的東西後面五個都補不回來，
// 所以「被跳過的事件要可查」跟「身分不准用猜的」佔了測試的一半。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ACTIONS, SKIP_REASONS, DEFAULT_CONFIG,
  createEvent, defaultAdapter, normalizeStream,
  toCoverageEvents, coverageDepthOf, toWriteEvents, actualWrites,
  groupByAgent, labelDrift, ambiguousLabels,
  inferTurns, captureHealth,
} from '../src/capture.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

// 一筆宿主原始事件的最小合法形狀
const raw = (over = {}) => ({
  name: 'Read', at: 1000, attributed_agent: 'a1',
  input: { file_path: 'src/x.js' }, ...over,
});

// ---- 中性事件的守門 ----
t('action 四種，一字不改', () =>
  assert.deepEqual([...ACTIONS], ['READ', 'WRITE', 'SEARCH', 'OTHER']));

t('跳過原因五種，一字不改', () =>
  assert.deepEqual([...SKIP_REASONS],
    ['NOT_AN_OBJECT', 'NO_ATTRIBUTION', 'NO_TIMESTAMP', 'NO_FILE', 'UNKNOWN_TOOL']));

t('沒有穩定識別碼就建不出事件', () =>
  assert.throws(() => createEvent({ at: 1, tool: 'Read', action: 'READ', file_path: 'x' }),
    /agent_id is required/));

t('缺時間戳不補假的，直接拋錯', () =>
  assert.throws(() => createEvent({ agent_id: 'a', tool: 'Read', action: 'READ', file_path: 'x' }),
    /millisecond timestamp/));

t('不認得的 action 拋錯，不靜默接受', () =>
  assert.throws(() => createEvent({ at: 1, agent_id: 'a', tool: 'X', action: 'MAYBE', file_path: 'x' }),
    /Unrecognised action/));

t('事件凍結，改不動', () => {
  const e = createEvent({ at: 1, agent_id: 'a', tool: 'Read', action: 'READ', file_path: 'x' });
  assert.throws(() => { e.agent_id = 'b'; }, TypeError);
});

// ---- adapter ----
t('Claude Code 形狀：name + input.file_path', () => {
  const e = defaultAdapter(raw());
  assert.equal(e.action, 'READ');
  assert.equal(e.file_path, 'src/x.js');
  assert.equal(e.partial, false);
});

t('hook 形狀：tool_name + tool_input.path', () => {
  const e = defaultAdapter({ tool_name: 'Write', tool_input: { path: 'a.js' }, at: 5, agent_id: 'a1' });
  assert.equal(e.action, 'WRITE');
  assert.equal(e.file_path, 'a.js');
});

t('Read 帶 offset 算部分讀取', () =>
  assert.equal(defaultAdapter(raw({ input: { file_path: 'x', limit: 50 } })).partial, true));

t('寫入類工具歸 WRITE', () => {
  for (const n of ['Edit', 'MultiEdit', 'Write', 'NotebookEdit', 'apply_patch', 'str_replace']) {
    assert.equal(defaultAdapter(raw({ name: n })).action, 'WRITE', n + ' 應為 WRITE');
  }
});

t('搜尋類工具歸 SEARCH，讀了什麼並不知道', () => {
  for (const n of ['Grep', 'Glob', 'rg', 'ls']) {
    assert.equal(defaultAdapter(raw({ name: n })).action, 'SEARCH', n + ' 應為 SEARCH');
  }
});

t('認得檔案但不認得工具，歸 OTHER 不是丟掉', () =>
  assert.equal(defaultAdapter(raw({ name: 'SomeFutureTool' })).action, 'OTHER'));

// ---- 教訓一：身分只信宿主蓋的章 ----
t('教訓一：agent 自報的身分完全不採信', () => {
  const out = defaultAdapter({
    name: 'Read', at: 1, input: { file_path: 'x' },
    self_reported_agent: 'pm', claimed_agent: 'pm', alias: 'pm',   // 全部該被忽略
  });
  assert.equal(out.skip, 'NO_ATTRIBUTION', '只有自報身分時必須跳過，不可採用');
});

t('教訓一：宿主蓋章才算數', () =>
  assert.equal(defaultAdapter(raw({ attributed_agent: 'w2' })).agent_id, 'w2'));

t('教訓一：自報身分即使跟蓋章不同，也以蓋章為準', () => {
  const e = defaultAdapter(raw({ attributed_agent: 'w2', self_reported_agent: 'w9' }));
  assert.equal(e.agent_id, 'w2');
});

// ---- 跳過理由分類 ----
t('非物件 → NOT_AN_OBJECT', () => assert.equal(defaultAdapter('hi').skip, 'NOT_AN_OBJECT'));
t('無時間戳 → NO_TIMESTAMP', () =>
  assert.equal(defaultAdapter({ name: 'Read', attributed_agent: 'a', input: { file_path: 'x' } }).skip, 'NO_TIMESTAMP'));
t('沒動到檔案 → NO_FILE', () =>
  assert.equal(defaultAdapter({ name: 'Bash', attributed_agent: 'a', at: 1, input: {} }).skip, 'NO_FILE'));

t('真實資料抓到的:file_path 不是字串時當成沒有檔案', () => {
  // 有工具把它傳成陣列或物件。放行的話會一路流到下游,
  // 直到某個 .split() 才炸,而且是在別人的機器上。
  for (const bad of [['a.js'], { path: 'a.js' }, 123]) {
    assert.equal(defaultAdapter(raw({ input: { file_path: bad } })).skip, 'NO_FILE');
  }
});

// ---- normalizeStream ----
t('被跳過的事件一律計數並附原因，不靜默丟棄', () => {
  const r = normalizeStream([raw(), 'garbage', { name: 'Read', at: 1, input: { file_path: 'x' } }]);
  assert.equal(r.events.length, 1);
  assert.equal(r.skipped, 2);
  assert.equal(r.total, 3);
  assert.deepEqual(r.skipped_by_reason, { NOT_AN_OBJECT: 1, NO_ATTRIBUTION: 1 });
});

t('輸出依時間排序，宿主餵進來的順序不影響', () => {
  const r = normalizeStream([raw({ at: 300 }), raw({ at: 100 }), raw({ at: 200 })]);
  assert.deepEqual(r.events.map((e) => e.at), [100, 200, 300]);
});

t('normalizeStream 回傳全部凍結', () => {
  const r = normalizeStream([raw()]);
  assert.throws(() => { r.events.push({}); }, TypeError);
});

t('空輸入不炸，回空結果', () => {
  const r = normalizeStream(null);
  assert.equal(r.events.length, 0);
  assert.equal(r.total, 0);
});

// ---- 教訓二：穩定識別碼與顯示名分開 ----
t('教訓二：中性事件同時帶穩定識別碼與顯示名', () => {
  const e = defaultAdapter(raw({ attributed_agent: 'w1', agent_label: 'Dev' }));
  assert.equal(e.agent_id, 'w1');
  assert.equal(e.agent_label, 'Dev');
});

t('教訓二：改名會被抓出來，這就是規則跟畫面脫鉤的那一刻', () => {
  const { events } = normalizeStream([
    raw({ attributed_agent: 'w1', agent_label: 'Dev', at: 1 }),
    raw({ attributed_agent: 'w1', agent_label: 'Forseti Dev', at: 2 }),
  ]);
  const d = labelDrift(events);
  assert.equal(d.length, 1);
  assert.equal(d[0].agent_id, 'w1');
  assert.deepEqual([...d[0].labels], ['Dev', 'Forseti Dev']);
});

t('教訓二：兩個視窗同名會被抓出來，這就是「亂送」的根因', () => {
  const { events } = normalizeStream([
    raw({ attributed_agent: 'w1', agent_label: 'Dev', at: 1 }),
    raw({ attributed_agent: 'w3', agent_label: 'Dev', at: 2 }),
  ]);
  const c = ambiguousLabels(events);
  assert.equal(c.length, 1);
  assert.equal(c[0].label, 'Dev');
  assert.deepEqual([...c[0].agent_ids], ['w1', 'w3']);
});

t('沒改名也沒撞名時，兩個檢查都回空', () => {
  const { events } = normalizeStream([
    raw({ attributed_agent: 'w1', agent_label: 'Dev' }),
    raw({ attributed_agent: 'w2', agent_label: 'Audit' }),
  ]);
  assert.deepEqual(labelDrift(events), []);
  assert.deepEqual(ambiguousLabels(events), []);
});

t('分堆用穩定識別碼，不用顯示名', () => {
  const { events } = normalizeStream([
    raw({ attributed_agent: 'w1', agent_label: 'Dev', at: 1 }),
    raw({ attributed_agent: 'w3', agent_label: 'Dev', at: 2 }),
  ]);
  assert.deepEqual([...groupByAgent(events).keys()], ['w1', 'w3']);
});

// ---- 分流 ----
t('深度對應：寫入是 EDITED，搜尋只是 MENTIONED', () => {
  assert.equal(coverageDepthOf({ action: 'WRITE', file_path: 'x' }).depth, 'EDITED');
  assert.equal(coverageDepthOf({ action: 'SEARCH', file_path: 'x' }).depth, 'MENTIONED');
});

t('深度對應：整份讀跟只讀一段是兩件事', () => {
  assert.equal(coverageDepthOf({ action: 'READ', file_path: 'x', partial: false }).depth, 'READ_FULL');
  assert.equal(coverageDepthOf({ action: 'READ', file_path: 'x', partial: true }).depth, 'READ_PARTIAL');
});

t('沒有檔案的事件回 null，不猜一個深度', () =>
  assert.equal(coverageDepthOf({ action: 'READ', file_path: null }), null));

t('餵給衝突偵測時只留寫入，同時讀同一檔不是衝突', () => {
  const { events } = normalizeStream([
    raw({ name: 'Read', attributed_agent: 'a1', at: 1 }),
    raw({ name: 'Read', attributed_agent: 'a2', at: 2 }),
    raw({ name: 'Edit', attributed_agent: 'a2', at: 3 }),
  ]);
  const w = toWriteEvents(events);
  assert.equal(w.length, 1);
  assert.deepEqual({ ...w[0] }, { file_path: 'src/x.js', agent_id: 'a2', at: 3 });
});

t('實際寫過哪些檔：去重、排序、只算指定的人', () => {
  const { events } = normalizeStream([
    raw({ name: 'Edit', attributed_agent: 'a1', at: 1, input: { file_path: 'b.js' } }),
    raw({ name: 'Edit', attributed_agent: 'a1', at: 2, input: { file_path: 'a.js' } }),
    raw({ name: 'Edit', attributed_agent: 'a1', at: 3, input: { file_path: 'a.js' } }),
    raw({ name: 'Edit', attributed_agent: 'a2', at: 4, input: { file_path: 'z.js' } }),
  ]);
  assert.deepEqual([...actualWrites(events, 'a1')], ['a.js', 'b.js']);
});

t('toCoverageEvents 保留原始工具名，對得回宿主紀錄', () => {
  const { events } = normalizeStream([raw({ name: 'MultiEdit' })]);
  assert.equal(toCoverageEvents(events)[0].name, 'MultiEdit');
});

// ---- 回合邊界 ----
t('同一人連續動作算同一輪', () => {
  const { events } = normalizeStream([
    raw({ at: 1000 }), raw({ at: 2000 }), raw({ at: 3000 }),
  ]);
  const turns = inferTurns(events);
  assert.equal(turns.length, 1);
  assert.equal(turns[0].event_count, 3);
});

t('間隔超過門檻就切成兩輪', () => {
  // 校準後的門檻是 230 秒(真實工具間隔的 p90)
  const { events } = normalizeStream([raw({ at: 1000 }), raw({ at: 1000 + 300_000 })]);
  assert.equal(inferTurns(events).length, 2);
});

t('校準後的門檻不會把正常的思考間隔切成新的一輪', () => {
  // 真實工具間隔 p50 是 21.8 秒。舊的 30 秒門檻會把它切開。
  const { events } = normalizeStream([raw({ at: 1000 }), raw({ at: 1000 + 60_000 })]);
  assert.equal(inferTurns(events).length, 1, '一分鐘的間隔仍在同一輪內');
});

t('不同人的動作不會混成同一輪', () => {
  const { events } = normalizeStream([
    raw({ at: 1000, attributed_agent: 'a1' }),
    raw({ at: 1100, attributed_agent: 'a2' }),
  ]);
  const turns = inferTurns(events);
  assert.equal(turns.length, 2);
  assert.deepEqual(turns.map((x) => x.agent_id).sort(), ['a1', 'a2']);
});

t('回合邊界一律標明是推算的，不可冒充 provider 給的事實', () => {
  const { events } = normalizeStream([raw()]);
  assert.equal(inferTurns(events)[0].inferred, true);
});

t('門檻可覆寫，不是硬編碼', () => {
  const { events } = normalizeStream([raw({ at: 1000 }), raw({ at: 1000 + 40_000 })]);
  assert.equal(inferTurns(events).length, 1, '校準後的預設門檻涵蓋這個間隔');
  assert.equal(inferTurns(events, { turn_gap_ms: 30_000 }).length, 2, '調回舊值就切開');
});

t('一輪記下碰過哪些檔，M2 判斷要不要往下送就靠這個', () => {
  const { events } = normalizeStream([
    raw({ at: 1000, input: { file_path: 'a.js' } }),
    raw({ at: 1100, name: 'Edit', input: { file_path: 'b.js' } }),
  ]);
  const turn = inferTurns(events)[0];
  assert.deepEqual([...turn.files], ['a.js', 'b.js']);
  assert.equal(turn.has_output, true);
  assert.equal(turn.wrote_files, true);
});

t('只讀不寫的一輪，wrote_files 為 false', () => {
  const { events } = normalizeStream([raw()]);
  assert.equal(inferTurns(events)[0].wrote_files, false);
});

// ---- 採集健康度 ----
t('採集率算得出來，五個機制的答案上限就是這個數字', () => {
  const r = normalizeStream([raw(), raw(), 'garbage', 'garbage']);
  assert.equal(captureHealth(r).capture_rate, 0.5);
});

t('完全沒事件時採集率是 null 不是 1', () => {
  const h = captureHealth(normalizeStream([]));
  assert.equal(h.capture_rate, null);
  assert.match(h.note, /nothing to judge/);
});

t('指出最大的漏源，才知道該修宿主哪裡', () => {
  const r = normalizeStream([
    { name: 'Read', at: 1, input: { file_path: 'x' } },
    { name: 'Read', at: 2, input: { file_path: 'x' } },
    'garbage',
  ]);
  assert.equal(captureHealth(r).worst_reason.reason, 'NO_ATTRIBUTION');
  assert.equal(captureHealth(r).worst_reason.count, 2);
});

// ---- 邊界紀律 ----
t('零依賴：capture.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/capture.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('未校準的常數在原始碼裡自己說了，不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/capture.js', import.meta.url), 'utf8');
  assert.ok(/沒有實測校準過/.test(src), 'turn_gap_ms 必須標明未校準');
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

t('兩條實測教訓寫在原始碼裡，不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/capture.js', import.meta.url), 'utf8');
  assert.ok(/自己報的身分一律不採信/.test(src), '教訓一必須留在原始碼裡');
  assert.ok(/穩定識別碼與顯示名必須分開存/.test(src), '教訓二必須留在原始碼裡');
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
