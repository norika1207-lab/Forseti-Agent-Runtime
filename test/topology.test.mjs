// Forseti v2.0 — P8 X-Ray Topology。規格 §11。
// §26 P8 的 exit gate:Mercury 那條 framework-substitution 路徑要重建得出來。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, NODE_TYPES, EDGE_TYPES, createGraph, reconstructSubstitutionPath,
} from '../src/topology.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('節點與邊的型別照 §11.1 / §11.2', () => {
  for (const n of ['GOAL', 'CLAIM', 'EVIDENCE_RECEIPT', 'CORRECTION', 'SUB_AGENT']) {
    assert.ok(NODE_TYPES.includes(n), n);
  }
  for (const e of ['DEPENDS_ON', 'SUPPORTS', 'REFUTES', 'SUPERSEDES', 'CLAIMS',
    'VERIFIES', 'DELEGATES_TO', 'IMPLEMENTS', 'UNKNOWN_EDGE']) {
    assert.ok(EDGE_TYPES.includes(e), e);
  }
});

t('不認得的型別直接炸,不靜靜接受', () => {
  const g = createGraph();
  assert.throws(() => g.addNode({ id: 'x', type: 'WHATEVER' }), /Unknown node type/);
  assert.throws(() => g.addEdge({ from: 'a', to: 'b', type: 'MAYBE' }), /Unknown edge type/);
});

// ---- FS-TOP-001 ----
t('FS-TOP-001 positive:UNKNOWN_EDGE 一定要說出為什麼不知道', () => {
  const g = createGraph();
  assert.throws(() => g.addEdge({ from: 'main', to: 'sub', type: 'UNKNOWN_EDGE' }),
    /must say why it is unknown/);
  assert.throws(() => g.addEdge({ from: 'main', to: 'sub', type: 'UNKNOWN_EDGE' }),
    /tempted to fill it in/);
});

t('FS-TOP-001 negative:給了理由就可以加', () => {
  const g = createGraph();
  const e = g.addEdge({
    from: 'main', to: 'sub7', type: 'UNKNOWN_EDGE',
    unobservableReason: 'sub-agent prompt not exposed by this harness',
  });
  assert.equal(e.type, 'UNKNOWN_EDGE');
  assert.match(e.unobservable_reason, /not exposed/);
});

t('看不到的邊不能拿來證明連通', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  g.addNode({ id: 'act', type: 'TASK' });
  g.addEdge({ from: 'act', to: 'goal', type: 'UNKNOWN_EDGE', unobservableReason: 'hidden' });
  const r = g.goalIntersection('goal', { windows: [{ actionNodeIds: ['act'] }, { actionNodeIds: ['act'] }] });
  assert.deepEqual([...r.series], [0, 0], 'UNKNOWN_EDGE 不算連得到 Goal');
});

t('observability 算得出這張圖有多少是猜不到的', () => {
  const g = createGraph();
  g.addEdge({ from: 'a', to: 'b', type: 'SUPPORTS' });
  g.addEdge({ from: 'a', to: 'c', type: 'UNKNOWN_EDGE', unobservableReason: 'no prompt' });
  const o = g.observability();
  assert.equal(o.ratio, 0.5);
  assert.deepEqual([...o.reasons], ['no prompt']);
  assert.match(o.note, /Conclusions drawn from it are.*weaker/s);
});

t('沒有邊的時候 ratio 是 null 不是 0', () =>
  assert.equal(createGraph().observability().ratio, null));

// ---- FS-TOP-002:CASE-D 的形狀 ----
t('FS-TOP-002 positive:每個動作都做完了,而跟 Goal 的交集一路下降', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL', label: 'acceleration' });
  for (const id of ['a1', 'a2', 'b1', 'b2', 'c1', 'c2']) g.addNode({ id, type: 'TASK' });
  // 早期的動作連得回 Goal
  g.addEdge({ from: 'a1', to: 'goal', type: 'SUPPORTS' });
  g.addEdge({ from: 'a2', to: 'goal', type: 'SUPPORTS' });
  // 中期一半連得回
  g.addEdge({ from: 'b1', to: 'goal', type: 'SUPPORTS' });
  // 後期完全沒有連回去的

  const r = g.goalIntersection('goal', {
    windows: [
      { actionNodeIds: ['a1', 'a2'] },
      { actionNodeIds: ['b1', 'b2'] },
      { actionNodeIds: ['c1', 'c2'] },
    ],
  });
  assert.deepEqual([...r.series], [1, 0.5, 0]);
  assert.equal(r.declining, true);
  assert.ok(r.trend < 0);
});

t('FS-TOP-002 negative:一路都連得回去就不算下降', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  g.addNode({ id: 'a', type: 'TASK' });
  g.addEdge({ from: 'a', to: 'goal', type: 'SUPPORTS' });
  const r = g.goalIntersection('goal', {
    windows: [{ actionNodeIds: ['a'] }, { actionNodeIds: ['a'] }],
  });
  assert.equal(r.declining, false);
});

t('low-evidence:只有一個窗就沒有方向', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  const r = g.goalIntersection('goal', { windows: [{ actionNodeIds: ['x'] }] });
  assert.equal(r.trend, null);
  assert.match(r.note, /a direction needs two points/);
});

t('exclusion:窗裡沒有動作時回 null,不算 0%', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  const r = g.goalIntersection('goal', { windows: [{ actionNodeIds: [] }, { actionNodeIds: [] }] });
  assert.deepEqual([...r.series], [null, null]);
});

// ---- §26 P8 exit gate:重建 CASE-D 的路徑 ----
t('P8 exit gate:acceleration → grid → models → atlas 這條鏈重建得出來', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL', label: 'acceleration' });
  g.addNode({ id: 'grid', type: 'PLAN_STEP', label: 'observation grid' });
  g.addNode({ id: 'models', type: 'PLAN_STEP', label: 'more models' });
  g.addNode({ id: 'atlas', type: 'PLAN_STEP', label: 'atlas / viz / paper' });
  g.addEdge({ from: 'grid', to: 'models', type: 'DEPENDS_ON' });
  g.addEdge({ from: 'models', to: 'atlas', type: 'DEPENDS_ON' });

  const r = reconstructSubstitutionPath(g, { goalId: 'goal', terminalNodeId: 'atlas' });
  assert.deepEqual([...r.path], ['grid', 'models', 'atlas']);
  assert.deepEqual([...r.still_connected_to_goal], []);
  assert.equal(r.substitution_detected, true);
  assert.match(r.note, /Each step was defensible; the chain is not/);
});

t('P8 exit gate negative:鏈上還有節點連得回 Goal 就不算替換', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  g.addNode({ id: 's1', type: 'PLAN_STEP' });
  g.addNode({ id: 's2', type: 'PLAN_STEP' });
  g.addNode({ id: 's3', type: 'PLAN_STEP' });
  g.addEdge({ from: 's1', to: 's2', type: 'DEPENDS_ON' });
  g.addEdge({ from: 's2', to: 's3', type: 'DEPENDS_ON' });
  g.addEdge({ from: 's2', to: 'goal', type: 'SUPPORTS' });

  const r = reconstructSubstitutionPath(g, { goalId: 'goal', terminalNodeId: 's3' });
  assert.equal(r.substitution_detected, false);
  assert.ok(r.still_connected_to_goal.includes('s2'));
});

t('exclusion:太短的鏈不判替換,兩步不構成一條路', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  g.addNode({ id: 'a', type: 'PLAN_STEP' });
  g.addNode({ id: 'b', type: 'PLAN_STEP' });
  g.addEdge({ from: 'a', to: 'b', type: 'DEPENDS_ON' });
  assert.equal(reconstructSubstitutionPath(g, { goalId: 'goal', terminalNodeId: 'b' })
    .substitution_detected, false);
});

t('環狀依賴不會讓重建卡死', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  g.addEdge({ from: 'a', to: 'b', type: 'DEPENDS_ON' });
  g.addEdge({ from: 'b', to: 'a', type: 'DEPENDS_ON' });
  const r = reconstructSubstitutionPath(g, { goalId: 'goal', terminalNodeId: 'a' });
  assert.ok(r.path.length <= 3);
});

// ---- 專案慣例 ----
t('零依賴:topology.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/topology.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('「補過的圖比沒有圖更危險」那句留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/topology.js', import.meta.url), 'utf8');
  assert.match(src, /一張補過的圖比沒有圖更危險/);
});

t('每個回傳都帶版本', () => {
  const g = createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  assert.equal(g.observability().version, VERSION);
  assert.equal(g.goalIntersection('goal', {}).version, VERSION);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
