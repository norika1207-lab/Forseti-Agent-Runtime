// Forseti M6：持久化。
// 這個模組防的是靜默資料遺失，所以測試的重點不是「存得起來」，
// 而是「存下去再讀回來，東西還在，而且讀不出來的時候有人會知道」。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  SCHEMA_VERSION, SECTIONS, checksum,
  createSnapshot, serialize, deserialize, migrate, restore, load, roundTripCheck,
} from '../src/persist.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

const T0 = 1_700_000_000_000;
const snap = (over = {}) => createSnapshot({ at: T0, ...over });

// ---- 坑一：Set 過不了 JSON ----
t('這個坑是真的：裸 JSON.stringify 會把 Set 變成空物件，而且不報錯', () => {
  const scope = { agent_id: 'a', actual: new Set(['x.js', 'y.js']) };
  const back = JSON.parse(JSON.stringify(scope));
  assert.deepEqual(back.actual, {}, '確認這正是會發生的事：資料沒了，沒有任何錯誤');
});

t('走這個模組的話，Set 活得下來', () => {
  const s = snap({ scopes: [{ agent_id: 'a', actual: new Set(['y.js', 'x.js']) }] });
  const back = deserialize(serialize(s)).snapshot;
  assert.ok(back.scopes[0].actual instanceof Set);
  assert.deepEqual([...back.scopes[0].actual].sort(), ['x.js', 'y.js']);
});

t('巢狀的 Set 也活得下來', () => {
  const s = snap({ scopes: [{ nested: { deep: [{ actual: new Set(['a']) }] } }] });
  const back = deserialize(serialize(s)).snapshot;
  assert.ok(back.scopes[0].nested.deep[0].actual instanceof Set);
});

t('Map 也活得下來', () => {
  const s = snap({ stats: { byAgent: new Map([['w1', 3], ['w2', 5]])} });
  const back = deserialize(serialize(s)).snapshot;
  assert.ok(back.stats.byAgent instanceof Map);
  assert.equal(back.stats.byAgent.get('w2'), 5);
});

t('同樣的狀態產生同樣的字串，diff 才看得出真的變了什麼', () => {
  const a = serialize(snap({ scopes: [{ actual: new Set(['b', 'a']) }] }));
  const b = serialize(snap({ scopes: [{ actual: new Set(['a', 'b']) }] }));
  assert.equal(a, b);
});

t('存檔前自我檢查抓得出過不了來回的區塊', () => {
  const r = roundTripCheck(snap({ scopes: [{ actual: new Set(['x']) }], stats: { auto: 3 } }));
  assert.equal(r.ok, true);
  assert.deepEqual(r.lossy_sections, []);
  assert.ok(r.byte_size > 0);
});

// ---- 完整性 ----
t('checksum 抓得到被截斷的檔案', () => {
  const text = serialize(snap({ stats: { auto: 5 } }));
  const truncated = JSON.stringify({ ...JSON.parse(text), body: JSON.parse(text).body.slice(0, -20) + '}' });
  const r = deserialize(truncated);
  assert.notEqual(r.checksum_ok, true);
});

t('checksum 對得上時標記為通過', () =>
  assert.equal(deserialize(serialize(snap())).checksum_ok, true));

t('沒有信封的裸快照也讀得回來，checksum 標成無法判斷不是失敗', () => {
  const bare = JSON.stringify({ schema_version: 1, at: T0, stats: { auto: 2 } });
  const r = deserialize(bare);
  assert.equal(r.checksum_ok, null);
  assert.equal(r.snapshot.stats.auto, 2);
});

t('checksum 在原始碼裡自己說了它不是安全機制', () => {
  const src = readFileSync(new URL('../src/persist.js', import.meta.url), 'utf8');
  assert.ok(/不是安全檢查/.test(src));
  assert.ok(/擋不住任何有意的竄改/.test(src));
});

t('checksum 對同樣輸入穩定，對不同輸入不同', () => {
  assert.equal(checksum('abc'), checksum('abc'));
  assert.notEqual(checksum('abc'), checksum('abd'));
});

// ---- 壞掉的處理 ----
t('整份無法解析時 snapshot 是 null，不回一個空狀態', () => {
  const r = deserialize('{ 這不是 json');
  assert.equal(r.snapshot, null);
  assert.equal(r.errors.length, 1);
});

t('讀不出來不等於空專案，警告要講清楚', () => {
  const r = load('壞掉的內容', { now: T0 });
  assert.equal(r.state, null);
  assert.match(r.warnings[0], /not the same as an empty project/);
});

t('讀得出來的區塊照樣還原，缺的區塊是 null 不是空陣列', () => {
  const partial = JSON.stringify({ schema_version: 1, at: T0, stats: { auto: 7 } });
  const r = deserialize(partial);
  assert.equal(r.snapshot.stats.auto, 7);
  assert.equal(r.snapshot.coverages, null, '沒存過跟存了空的是兩件事');
});

// ---- 版本 ----
t('沒有版本號的舊資料標成 0，不假裝它是第 1 版', () => {
  const m = migrate({ stats: {} });
  assert.equal(m.migrated_from, 0);
  assert.equal(m.schema_version, SCHEMA_VERSION);
});

t('比目前還新的版本原樣回傳並標明，不猜它多了什麼', () => {
  const m = migrate({ schema_version: SCHEMA_VERSION + 5 });
  assert.equal(m.unknown_future_version, true);
});

t('同版本不動它', () => {
  const raw = { schema_version: SCHEMA_VERSION, stats: {} };
  assert.equal(migrate(raw), raw);
});

t('打包一定要有時間，沒有就拋錯不補假的', () =>
  assert.throws(() => createSnapshot({}), /at is required/));

t('區塊清單一字不改', () =>
  assert.deepEqual([...SECTIONS],
    ['capsules', 'budget', 'scopes', 'locks', 'coverages', 'stats', 'edges', 'goal', 'signals', 'events']));

t('北極星與訊號跨重啟活著,忘了目標就永遠量不出飄移', () => {
  const snap = createSnapshot({
    at: T0,
    goal: { topics: ['src/auth'], inferred: false },
    signals: { failures: [T0], friction: [], selfWritten: new Set(['a.js']), investments: [] },
  });
  const back = deserialize(serialize(snap)).snapshot;
  assert.deepEqual(back.goal.topics, ['src/auth']);
  assert.deepEqual(back.signals.failures, [T0]);
  assert.ok(back.signals.selfWritten instanceof Set, 'selfWritten 是 Set,不能在存讀時被吃掉');
});

// ---- 坑二：重啟後的復甦 ----
t('過期的鎖直接清掉，死掉的持有者不該繼續擋人', () => {
  const s = snap({ locks: [
    { file_path: 'a.js', holder: 'w1', acquired_at: T0 - 600_000, ttl_seconds: 300 },
    { file_path: 'b.js', holder: 'w2', acquired_at: T0 - 10_000, ttl_seconds: 300 },
  ]});
  const r = restore(s, { now: T0 });
  assert.deepEqual(r.state.locks.map((l) => l.file_path), ['b.js']);
  assert.deepEqual(r.expired_locks.map((l) => l.file_path), ['a.js']);
});

t('重啟前 ACTIVE 的佔用範圍標成 stale，不當成還活著', () => {
  const s = snap({ scopes: [
    { agent_id: 'w1', state: 'ACTIVE', declared: ['a.js'] },
    { agent_id: 'w2', state: 'RELEASED', declared: ['b.js'] },
  ]});
  const r = restore(s, { now: T0 + 1000 });
  assert.equal(r.stale_scopes.length, 1);
  assert.equal(r.stale_scopes[0].agent_id, 'w1');
});

t('stale 的不自動釋放：那個 agent 可能還活著，放掉會讓兩人進同一個檔', () => {
  const s = snap({ scopes: [{ agent_id: 'w1', state: 'ACTIVE', declared: ['a.js'] }] });
  const r = restore(s, { now: T0 + 1000 });
  assert.equal(r.state.scopes.length, 1, '仍在狀態裡,只是被標記');
  assert.equal(r.state.scopes[0].state, 'ACTIVE');
  assert.match(r.warnings[0], /both guesses cause damage/);
});

t('中斷了多久算得出來', () => {
  assert.equal(restore(snap(), { now: T0 + 90_000 }).gap_ms, 90_000);
});

t('快照沒有時間戳時明說判斷不了，不填 0', () => {
  const r = restore({ scopes: [], locks: [] }, { now: T0 });
  assert.equal(r.gap_ms, null);
  assert.ok(r.warnings.some((w) => /length of the interruption/.test(w)));
});

t('沒有現在時間就拋錯，不拿系統時鐘偷偷補', () =>
  assert.throws(() => restore(snap(), {}), /now is required/));

t('未來版本的快照在復甦時也會警告', () => {
  const r = restore({ ...snap(), unknown_future_version: true }, { now: T0 });
  assert.ok(r.warnings.some((w) => /newer than this build/.test(w)));
});

t('沒有 scopes 與 locks 也不炸', () => {
  const r = restore({ at: T0 }, { now: T0 });
  assert.deepEqual(r.state.scopes, []);
  assert.deepEqual(r.state.locks, []);
});

// ---- 一次做完 ----
t('load 一次讀完並復甦，累積的計數活過重啟', () => {
  const text = serialize(snap({
    stats: { manual: 4, auto: 12, since: '2026-09-01T00:00:00Z' },
    locks: [{ file_path: 'a.js', holder: 'w1', acquired_at: T0 - 999_999, ttl_seconds: 300 }],
  }));
  const r = load(text, { now: T0 });
  assert.equal(r.state.stats.auto, 12);
  assert.equal(r.state.stats.since, '2026-09-01T00:00:00Z', '計數的起點要跨重啟活著,否則自動化率沒有意義');
  assert.equal(r.expired_locks.length, 1);
  assert.equal(r.checksum_ok, true);
});

t('回傳物件凍結', () => {
  const r = load(serialize(snap()), { now: T0 });
  assert.throws(() => { r.state.scopes.push({}); }, TypeError);
});

// ---- 邊界紀律 ----
t('零依賴：persist.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/persist.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('兩個靜默吃資料的坑寫在原始碼裡，不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/persist.js', import.meta.url), 'utf8');
  assert.ok(/Set 過不了 JSON/.test(src), '坑一必須留在原始碼裡');
  assert.ok(/幽靈鎖死/.test(src), '坑二必須留在原始碼裡');
});

t('存檔裡的檔案集合有上限,不會無限長大', async () => {
  // 事件早就有上限,但從事件衍生的兩個檔案集合沒有。
  // 實測八千筆事件時它們佔存檔的 87%,而每一次 PostToolUse
  // 都要把整份讀回來再寫出去。
  const { createRuntime } = await import('../src/runtime.js');
  const rt = createRuntime();
  rt.ingest(Array.from({ length: 6000 }, (_, i) => ({
    attributed_agent: 'a', session_id: 'a', name: 'Write',
    input: { file_path: `/p/f${i}.js` }, at: Date.now() - (6000 - i) * 1000,
  })));
  const body = JSON.parse(JSON.parse(rt.save()).body);
  assert.ok(Object.keys(body.coverages[0].files).length <= 2000, 'coverage 的檔案集合要有上限');
  assert.ok(body.signals.selfWritten.length <= 2000, 'selfWritten 要有上限');
  assert.equal(body.coverages[0].files_truncated, true, '截斷了就要說,不能靜靜給一個變小的數字');
});

t('沒超過上限就不會被標成截斷', async () => {
  const { createRuntime } = await import('../src/runtime.js');
  const rt = createRuntime();
  rt.ingest(Array.from({ length: 50 }, (_, i) => ({
    attributed_agent: 'a', session_id: 'a', name: 'Write',
    input: { file_path: `/p/f${i}.js` }, at: Date.now(),
  })));
  const body = JSON.parse(JSON.parse(rt.save()).body);
  assert.equal(body.coverages[0].files_truncated, undefined);
  assert.equal(Object.keys(body.coverages[0].files).length, 50);
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
