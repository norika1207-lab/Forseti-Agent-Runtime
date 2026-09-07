// Claude Code 記錄檔的 adapter。
// 這一份的每條規則都是接上 130 份真實記錄之後才知道要寫的。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { lineToRawEvents, parseTranscript, parseTranscripts, SIDECHAIN_SUFFIX } from '../adapters/claude-code.mjs';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

const T = '2026-09-07T10:00:00.000Z';
const line = (over = {}) => ({
  type: 'assistant', sessionId: 's1', timestamp: T, uuid: 'u1', isSidechain: false,
  message: { content: [{ type: 'tool_use', name: 'Read', input: { file_path: 'a.js' }, id: 'tu1' }] },
  ...over,
});
const jl = (...objs) => objs.map((o) => JSON.stringify(o)).join('\n');

// ---- 基本形狀 ----
t('認得真實的 tool_use 結構', () => {
  const [e] = lineToRawEvents(line());
  assert.equal(e.name, 'Read');
  assert.equal(e.input.file_path, 'a.js');
  assert.equal(e.attributed_agent, 's1');
  assert.equal(e.at, Date.parse(T));
});

t('一行多個 tool_use 全部展開', () => {
  const evs = lineToRawEvents(line({ message: { content: [
    { type: 'tool_use', name: 'Read', input: { file_path: 'a.js' } },
    { type: 'tool_use', name: 'Edit', input: { file_path: 'b.js' } },
  ]}}));
  assert.equal(evs.length, 2);
});

t('非工具呼叫的行回空,不硬湊', () => {
  assert.deepEqual(lineToRawEvents({ type: 'user', sessionId: 's1', timestamp: T }), []);
  assert.deepEqual(lineToRawEvents(null), []);
});

t('沒有可解析的時間戳就跳過,不補一個', () =>
  assert.deepEqual(lineToRawEvents(line({ timestamp: 'not a date' })), []));

t('沒有 sessionId 就跳過', () =>
  assert.deepEqual(lineToRawEvents(line({ sessionId: null })), []));

// ---- sidechain ----
t('subagent 的事件另外標身分,不混進主線', () => {
  const [e] = lineToRawEvents(line({ isSidechain: true }));
  assert.equal(e.attributed_agent, 's1' + SIDECHAIN_SUFFIX);
});

t('混進主線的後果:覆蓋範圍灌水、同一個人不會跟自己撞車', () => {
  const r = parseTranscript(jl(line(), line({ isSidechain: true, uuid: 'u2' })));
  assert.equal(r.sessions.length, 2, '主線與 sidechain 必須分得開');
  assert.ok(r.notes.some((n) => /subagent sidechains/.test(n)));
  assert.ok(r.notes.some((n) => /not\s+recoverable/.test(n)), 'sidechain 真實身分不可考,必須明講');
});

// ---- 壞掉的行 ----
t('寫到一半的行計數,不靜默忽略', () => {
  const r = parseTranscript(JSON.stringify(line()) + '\n{"partial":');
  assert.equal(r.parse_failures, 1);
  assert.equal(r.events.length, 1);
  assert.ok(r.notes.some((n) => /failed to parse/.test(n)));
});

// ---- resume:真實資料抓到的那個 ----
t('resume:同一條對話兩個 sessionId,合併成一個執行者', () => {
  const a = jl(line({ uuid: 'u1' }), line({ uuid: 'u2' }));
  // resume 之後系統開新檔、給新 id,並把舊歷史整段複製過去
  const b = jl(
    line({ sessionId: 's2', uuid: 'u1' }),
    line({ sessionId: 's2', uuid: 'u2' }),
    line({ sessionId: 's2', uuid: 'u3' }),
  );
  const r = parseTranscripts([{ name: 'a', text: a }, { name: 'b', text: b }]);
  assert.equal(r.sessions.length, 1, '同一條對話應該只算一個人');
  assert.equal(r.resume_groups.length, 1);
  assert.deepEqual([...r.resume_groups[0]], ['s1', 's2']);
});

t('resume:重複的事件被去掉,否則會變成 0 秒間隔的假撞車', () => {
  const a = jl(line({ uuid: 'u1' }), line({ uuid: 'u2' }));
  const b = jl(line({ sessionId: 's2', uuid: 'u1' }), line({ sessionId: 's2', uuid: 'u2' }), line({ sessionId: 's2', uuid: 'u3' }));
  const r = parseTranscripts([{ name: 'a', text: a }, { name: 'b', text: b }]);
  assert.equal(r.duplicates_removed, 2);
  assert.equal(r.events.length, 3, 'u1 u2 u3 各一次');
});

t('resume 合併會被明講,不是默默改掉資料', () => {
  const a = jl(line({ uuid: 'u1' }));
  const b = jl(line({ sessionId: 's2', uuid: 'u1' }));
  const r = parseTranscripts([{ name: 'a', text: a }, { name: 'b', text: b }]);
  assert.ok(r.notes.some((n) => /more than one session id/.test(n)));
  assert.ok(r.notes.some((n) => /false conflicts/.test(n)), '為什麼要合併必須寫明');
});

t('真的不相干的兩個 session 不會被合併', () => {
  const a = jl(line({ uuid: 'u1' }), line({ uuid: 'u2' }));
  const b = jl(line({ sessionId: 's2', uuid: 'x1' }), line({ sessionId: 's2', uuid: 'x2' }));
  const r = parseTranscripts([{ name: 'a', text: a }, { name: 'b', text: b }]);
  assert.equal(r.sessions.length, 2);
  assert.equal(r.resume_groups.length, 0);
});

t('合併門檻可調,不是硬編碼', () => {
  // 共用 1/2 = 50%
  const a = jl(line({ uuid: 'u1' }), line({ uuid: 'u2' }));
  const b = jl(line({ sessionId: 's2', uuid: 'u1' }), line({ sessionId: 's2', uuid: 'y2' }));
  assert.equal(parseTranscripts([{ name: 'a', text: a }, { name: 'b', text: b }], { mergeRatio: 0.5 }).sessions.length, 1);
  assert.equal(parseTranscripts([{ name: 'a', text: a }, { name: 'b', text: b }], { mergeRatio: 0.9 }).sessions.length, 2);
});

t('三段 resume 鏈全部併成一個', () => {
  const mk = (sid, uuids) => jl(...uuids.map((u) => line({ sessionId: sid, uuid: u })));
  const r = parseTranscripts([
    { name: 'a', text: mk('s1', ['u1', 'u2']) },
    { name: 'b', text: mk('s2', ['u1', 'u2', 'u3']) },
    { name: 'c', text: mk('s3', ['u2', 'u3', 'u4']) },
  ]);
  assert.equal(r.sessions.length, 1);
  assert.equal(r.resume_groups[0].length, 3);
});

t('事件依時間排序', () => {
  const r = parseTranscripts([{ name: 'a', text: jl(
    line({ uuid: 'u2', timestamp: '2026-09-07T10:00:05.000Z' }),
    line({ uuid: 'u1', timestamp: '2026-09-07T10:00:01.000Z' }),
  )}]);
  assert.ok(r.events[0].at < r.events[1].at);
});

t('回傳凍結', () => {
  const r = parseTranscripts([{ name: 'a', text: jl(line()) }]);
  assert.throws(() => { r.sessions.push('x'); }, TypeError);
});

t('空輸入不炸', () => {
  const r = parseTranscripts([]);
  assert.equal(r.events.length, 0);
  assert.equal(r.sessions.length, 0);
});

// ---- 邊界 ----
t('adapter 只 import 標準函式庫以外的零個東西', () => {
  const src = readFileSync(new URL('../adapters/claude-code.mjs', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('resume 這件事是實測發現,原始碼要寫明來源', () => {
  const src = readFileSync(new URL('../adapters/claude-code.mjs', import.meta.url), 'utf8');
  assert.ok(/跑 130 個真實記錄檔時抓到的/.test(src));
  assert.ok(/記錄流,不是做事的人/.test(src));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
