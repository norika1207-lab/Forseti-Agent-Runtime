// Forseti M2：交接規則。
// 前三組是從實跑環境搬過來的回歸基準，行為必須跟已驗證的實作一致。
// 尤其「roundtrip 第二次被擋」那條，釘住的是實跑才發現的計數偏移。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  EDGE_KINDS, DECISIONS, DEFAULT_CONFIG,
  createEdge, edgesFrom, decide,
  createStats, planHandoff, applyStats, recordManual, releaseGate, automationRate,
  findCycles, buildHandoffPacket,
} from '../src/handoff.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const E = (from, to, kind = 'direct') => createEdge({ id: `${from}-${to}`, from, to, kind });
const D = (kind, from, to, chain, running = false) =>
  decide({ edge: { to, kind }, fromNode: from, chain, isRunning: running });

// ---- 回歸基準：direct ----
t('direct：首次放行', () => assert.equal(D('direct', 'A', 'B', ['A']), 'allow'));
t('direct：回頭被擋，A 已在鏈上', () => assert.equal(D('direct', 'B', 'A', ['A', 'B']), 'loop'));
t('direct：往前推進放行', () => assert.equal(D('direct', 'B', 'C', ['A', 'B']), 'allow'));

// ---- 回歸基準：roundtrip（實跑抓到的偏移）----
t('roundtrip：首次放行', () => assert.equal(D('roundtrip', 'A', 'B', ['A']), 'allow'));
t('roundtrip：退回放行，這就是那一次來回', () => assert.equal(D('roundtrip', 'B', 'A', ['A', 'B']), 'allow'));
t('roundtrip：第二次被擋（舊寫法在這裡會放行，多燒一輪）', () =>
  assert.equal(D('roundtrip', 'A', 'B', ['A', 'B', 'A']), 'loop'));

// ---- 回歸基準：其他防線 ----
t('下游正在跑 → busy', () => assert.equal(D('direct', 'A', 'B', ['A'], true), 'busy'));
t('鏈長達上限 → hops', () => assert.equal(D('direct', 'A', 'B', ['a', 'b', 'c', 'd']), 'hops'));
t('busy 優先於 loop', () => assert.equal(D('direct', 'B', 'A', ['A', 'B'], true), 'busy'));

// ---- 資料模型 ----
t('edge 三種型別，一字不改', () => assert.deepEqual([...EDGE_KINDS], ['direct', 'gated', 'roundtrip']));
t('decide 四種結果，一字不改', () => assert.deepEqual([...DECISIONS], ['allow', 'loop', 'busy', 'hops']));
t('不認得的 kind 拋錯，不靜默接受', () =>
  assert.throws(() => createEdge({ id: 'x', from: 'A', to: 'B', kind: 'maybe' }), /不認得的 edge kind/));
t('不允許自己指向自己', () =>
  assert.throws(() => createEdge({ id: 'x', from: 'A', to: 'A' }), /自己指向自己/));
t('edge 凍結，改不動', () => {
  const e = E('A', 'B');
  assert.throws(() => { e.kind = 'gated'; }, TypeError);
});
t('edgesFrom 只回生效的出邊', () => {
  const edges = [E('A', 'B'), { ...E('A', 'C'), enabled: false }, E('B', 'C')];
  assert.deepEqual(edgesFrom(edges, 'A').map((e) => e.to), ['B']);
});

// ---- planHandoff ----
t('direct 邊進 dispatch，chain 往後接上下游', () => {
  const p = planHandoff({ fromNode: 'A', edges: [E('A', 'B')], chain: ['A'] });
  assert.equal(p.dispatch.length, 1);
  assert.deepEqual([...p.dispatch[0].chain], ['A', 'B']);
  assert.equal(p.gates.length, 0);
});

t('gated 邊進閘門佇列，不直接送出', () => {
  const p = planHandoff({ fromNode: 'A', edges: [E('A', 'B', 'gated')], chain: ['A'] });
  assert.equal(p.dispatch.length, 0);
  assert.equal(p.gates.length, 1);
  assert.equal(p.gates[0].to, 'B');
});

t('被擋下的邊記進 blocked 並附理由，不靜默丟棄', () => {
  const p = planHandoff({ fromNode: 'B', edges: [E('B', 'A')], chain: ['A', 'B'] });
  assert.equal(p.dispatch.length, 0);
  assert.deepEqual(p.blocked.map((b) => b.reason), ['loop']);
});

t('roundtrip 達上限時轉成閘門交給人，不是直接丟掉', () => {
  const p = planHandoff({ fromNode: 'A', edges: [E('A', 'B', 'roundtrip')], chain: ['A', 'B', 'A'] });
  assert.equal(p.dispatch.length, 0);
  assert.equal(p.blocked.length, 1);
  assert.equal(p.gates.length, 1);
  assert.match(p.gates[0].reason, /上限/);
});

t('實測過的失敗模式：上游沒有產出就不觸發任何邊', () => {
  const p = planHandoff({ fromNode: 'A', edges: [E('A', 'B'), E('A', 'C')], chain: ['A'], hasOutput: false });
  assert.equal(p.dispatch.length, 0);
  assert.equal(p.gates.length, 0);
  assert.equal(p.skipped_no_output, true);
});

t('下游正在跑的邊被擋，其他邊照常送', () => {
  const p = planHandoff({
    fromNode: 'A', edges: [E('A', 'B'), E('A', 'C')], chain: ['A'],
    isRunning: (n) => n === 'B',
  });
  assert.deepEqual(p.dispatch.map((d) => d.to), ['C']);
  assert.deepEqual(p.blocked.map((b) => b.reason), ['busy']);
});

t('planHandoff 回傳全部凍結', () => {
  const p = planHandoff({ fromNode: 'A', edges: [E('A', 'B')], chain: ['A'] });
  assert.throws(() => { p.dispatch.push({}); }, TypeError);
});

// ---- 計數：M2 唯一的驗收指標 ----
t('計數欄位恰好五個', () => {
  assert.deepEqual(Object.keys(createStats()).sort(),
    ['auto', 'blocked_loop', 'gated_released', 'manual', 'since']);
});

t('applyStats 累加自動送出與被擋次數，不改動原物件', () => {
  const s0 = createStats();
  const p = planHandoff({ fromNode: 'A', edges: [E('A', 'B'), E('B', 'A')], chain: ['A'] });
  const s1 = applyStats(s0, p, '2026-09-07T00:00:00Z');
  assert.equal(s0.auto, 0);
  assert.equal(s1.auto, 1);
  assert.equal(s1.since, '2026-09-07T00:00:00Z');
});

t('手動轉交會被記下來，那個數字要往下掉', () => {
  const s = recordManual(createStats(), '2026-09-07T00:00:00Z');
  assert.equal(s.manual, 1);
  assert.equal(s.since, '2026-09-07T00:00:00Z');
});

t('自動化率：完全沒轉交紀錄時是 null 不是 0', () => {
  assert.equal(automationRate(createStats()), null);
});

t('自動化率：人按越少、規則送越多，數字越高', () => {
  let s = createStats();
  s = recordManual(s); s = recordManual(s);
  s = applyStats(s, { dispatch: [1, 2, 3, 4, 5, 6], gates: [], blocked: [] });
  assert.equal(automationRate(s), 0.75);
});

t('releaseGate 累加放行次數', () => {
  assert.equal(releaseGate(createStats()).gated_released, 1);
});

// ---- 建規則時就擋環 ----
t('findCycles 抓出 A→B→A 這種環', () => {
  const cycles = findCycles([E('A', 'B'), E('B', 'A')]);
  assert.equal(cycles.length, 1);
  assert.ok(cycles[0].includes('A') && cycles[0].includes('B'));
});

t('findCycles 抓出三節點的環', () => {
  assert.equal(findCycles([E('A', 'B'), E('B', 'C'), E('C', 'A')]).length, 1);
});

t('線性鏈不算環', () => {
  assert.deepEqual(findCycles([E('A', 'B'), E('B', 'C')]), []);
});

t('roundtrip 是刻意雙向，不算環', () => {
  assert.deepEqual(findCycles([E('A', 'B', 'roundtrip'), E('B', 'A', 'roundtrip')]), []);
});

t('停用的邊不算環', () => {
  assert.deepEqual(findCycles([E('A', 'B'), { ...E('B', 'A'), enabled: false }]), []);
});

// ---- 與 M5 的接點 ----
t('交接包附上要轉述哪些檔案，以及省下多少', () => {
  const delta = {
    need_briefing: [{ file_path: 'x.ts', depth: 'EDITED' }],
    saved_files: ['y.ts', 'z.ts'],
    saved_ratio: 0.6667,
  };
  const pkt = buildHandoffPacket({ from: 'A', to: 'B', result: 'done', delta });
  assert.deepEqual([...pkt.briefing_files], ['x.ts']);
  assert.deepEqual([...pkt.saved_files], ['y.ts', 'z.ts']);
  assert.equal(pkt.has_coverage_data, true);
});

t('沒有覆蓋資料時 briefing_files 是 null 不是空陣列', () => {
  const pkt = buildHandoffPacket({ from: 'A', to: 'B', result: 'done' });
  assert.equal(pkt.briefing_files, null);
  assert.equal(pkt.saved_ratio, null);
  assert.equal(pkt.has_coverage_data, false);
});

// ---- 邊界紀律 ----
t('零依賴：handoff.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/handoff.js', import.meta.url), 'utf8');
  const imports = src.match(/^\s*import\s.+$/gm) ?? [];
  assert.deepEqual(imports, [], '應為零 import，實際: ' + JSON.stringify(imports));
});

t('實跑抓到的偏移原因寫在原始碼裡，不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/handoff.js', import.meta.url), 'utf8');
  assert.ok(/偏移一輪/.test(src), '計數偏移的原因必須寫在原始碼裡');
  assert.ok(/真的跑起來才發現/.test(src), '這條是實跑發現而非規格推導，必須標明');
});

t('DEFAULT_CONFIG 是預設不是硬編碼', () => {
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
  const long = ['a', 'b', 'c', 'd'];
  assert.equal(decide({ edge: { to: 'B', kind: 'direct' }, fromNode: 'A', chain: long }), 'hops');
  assert.equal(decide({ edge: { to: 'B', kind: 'direct' }, fromNode: 'A', chain: long, config: { maxHops: 10 } }), 'allow');
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
