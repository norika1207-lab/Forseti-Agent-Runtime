// Forseti M4 cost.js 測試。直接 `node test/cost.test.mjs` 跑,不需要任何 server。
import assert from 'node:assert/strict';
import {
  buildGraph,
  computeCostVector,
  compareCostVectors,
  reverseReachable,
  unresolvedImports,
  resolutionRate,
  PRIORITY_ORDER,
  COVERAGE_LCOV,
  COVERAGE_NONE,
} from '../src/cost.js';

let pass = 0;
let fail = 0;
function test(name, fn) {
  try {
    fn();
    pass += 1;
    console.log(`PASS  ${name}`);
  } catch (err) {
    fail += 1;
    console.log(`FAIL  ${name}`);
    console.log(`      ${err.message}`);
  }
}

// ---- 空圖 ----
test('空圖:所有計數為 0,uncovered_d1 為 null,coverage_source 為 NONE', () => {
  const g = buildGraph([]);
  const v = computeCostVector(g, 'src/a.js');
  assert.equal(v.d1_count, 0);
  assert.equal(v.d2_count, 0);
  assert.equal(v.uncovered_d1, null);
  assert.equal(v.cross_modules, 0);
  assert.equal(v.live_conflicts, 0);
  assert.equal(v.coverage_source, COVERAGE_NONE);
  assert.equal(v.resolution_rate, 1);
  assert.equal(v.is_lower_bound, true);
});

test('欄位名照文件 6.3 節,一字不改,恰好八個', () => {
  const v = computeCostVector(buildGraph([]), 'x.js');
  assert.deepEqual(Object.keys(v).sort(), [
    'coverage_source',
    'cross_modules',
    'd1_count',
    'd2_count',
    'is_lower_bound',
    'live_conflicts',
    'resolution_rate',
    'uncovered_d1',
  ]);
});

// ---- 無覆蓋資料(誠實條款 6.4 條四) ----
test('無覆蓋資料:有下游時 uncovered_d1 仍為 null,不准啟發式估算', () => {
  const g = buildGraph([
    { from: 'src/b.js', to: 'src/a.js' },
    { from: 'src/c.js', to: 'src/a.js' },
  ]);
  const v = computeCostVector(g, 'src/a.js');
  assert.equal(v.d1_count, 2);
  assert.equal(v.uncovered_d1, null);
  assert.equal(v.coverage_source, COVERAGE_NONE);
});

test('有 LCOV 覆蓋資料:uncovered_d1 只數 d1 裡沒被覆蓋的', () => {
  const g = buildGraph([
    { from: 'src/b.js', to: 'src/a.js' },
    { from: 'src/c.js', to: 'src/a.js' },
    { from: 'src/d.js', to: 'src/b.js' }, // d 是二階,不算進 uncovered_d1
  ]);
  const v = computeCostVector(g, 'src/a.js', {
    coverage: { source: COVERAGE_LCOV, covered: ['src/b.js'] },
  });
  assert.equal(v.d1_count, 2);
  assert.equal(v.d2_count, 1);
  assert.equal(v.uncovered_d1, 1); // 只有 c 裸奔;d 在二階
  assert.equal(v.coverage_source, COVERAGE_LCOV);
});

// ---- 循環依賴 ----
test('循環依賴:BFS 終止,target 不算進自己的波及範圍', () => {
  // a→c、c→b、b→a 互相 import 成環(from 依賴 to)
  const g = buildGraph([
    { from: 'src/a.js', to: 'src/c.js' },
    { from: 'src/c.js', to: 'src/b.js' },
    { from: 'src/b.js', to: 'src/a.js' },
  ]);
  const { d1, d2plus } = reverseReachable(g, 'src/a.js');
  assert.deepEqual([...d1], ['src/b.js']);
  assert.deepEqual([...d2plus], ['src/c.js']);
  const v = computeCostVector(g, 'src/a.js');
  assert.equal(v.d1_count, 1);
  assert.equal(v.d2_count, 1);
});

// ---- 樞紐節點 ----
test('樞紐節點:被 10 個檔案直接 import,d1_count = 10', () => {
  const imports = [];
  for (let i = 0; i < 10; i += 1) {
    imports.push({ from: `src/user${i}.js`, to: 'src/hub.js' });
  }
  const g = buildGraph(imports);
  const v = computeCostVector(g, 'src/hub.js');
  assert.equal(v.d1_count, 10);
  assert.equal(v.d2_count, 0);
});

test('同一檔案同時是一階就不重複算進二階', () => {
  // b 直接依賴 a,c 依賴 b 也直接依賴 a → c 應只算一次且算在 d1
  const g = buildGraph([
    { from: 'src/b.js', to: 'src/a.js' },
    { from: 'src/c.js', to: 'src/a.js' },
    { from: 'src/c.js', to: 'src/b.js' },
  ]);
  const v = computeCostVector(g, 'src/a.js');
  assert.equal(v.d1_count, 2);
  assert.equal(v.d2_count, 0);
});

// ---- 跨模組計數 ----
test('跨模組計數:預設用第一段目錄,數的是波及範圍的相異模組數', () => {
  const g = buildGraph([
    { from: 'auth/login.js', to: 'core/a.js' },
    { from: 'auth/session.js', to: 'core/a.js' },
    { from: 'billing/invoice.js', to: 'auth/login.js' },
    { from: 'ui/panel.js', to: 'billing/invoice.js' },
  ]);
  const v = computeCostVector(g, 'core/a.js');
  assert.equal(v.d1_count, 2); // auth/login、auth/session
  assert.equal(v.d2_count, 2); // billing/invoice、ui/panel
  assert.equal(v.cross_modules, 3); // auth、billing、ui
});

test('跨模組計數:可用自訂 moduleOf', () => {
  const g = buildGraph([
    { from: 'x.js', to: 'a.js' },
    { from: 'y.js', to: 'a.js' },
  ]);
  const v = computeCostVector(g, 'a.js', { moduleOf: () => 'ALL' });
  assert.equal(v.cross_modules, 1);
});

// ---- live_conflicts ----
test('live_conflicts:只數波及範圍內正被 agent 動的檔案', () => {
  const g = buildGraph([
    { from: 'src/b.js', to: 'src/a.js' },
    { from: 'src/c.js', to: 'src/b.js' },
  ]);
  const v = computeCostVector(g, 'src/a.js', {
    liveScopes: [
      { agent_id: 'w3', files: ['src/c.js', 'src/unrelated.js'] },
      { agent_id: 'w4', files: ['src/b.js'] },
    ],
  });
  assert.equal(v.live_conflicts, 2); // b 與 c;unrelated 不在波及範圍
});

// ---- 誠實欄位 ----
test('未解析 import 可查詢,不靜默吞掉;resolution_rate 正確', () => {
  const g = buildGraph([
    { from: 'src/b.js', to: 'src/a.js' },
    { from: 'src/b.js', to: null, specifier: './' + 'dyn_' + 'part' },
    { from: 'src/c.js', to: null, specifier: 'ffi:rust_module' },
    { from: 'src/d.js', to: 'src/a.js' },
  ]);
  const un = unresolvedImports(g);
  assert.equal(un.length, 2);
  assert.deepEqual(un.map((u) => u.from).sort(), ['src/b.js', 'src/c.js']);
  assert.equal(resolutionRate(g), 0.5);
  const v = computeCostVector(g, 'src/a.js');
  assert.equal(v.resolution_rate, 0.5);
});

test('is_lower_bound 永遠是 true,且向量被凍結不可竄改', () => {
  const v = computeCostVector(buildGraph([]), 'a.js');
  assert.equal(v.is_lower_bound, true);
  assert.throws(() => {
    'use strict';
    v.is_lower_bound = false;
  });
  assert.equal(v.is_lower_bound, true);
});

// ---- 排序(文件 6.3 節優先順序) ----
test('PRIORITY_ORDER 照文件:live_conflicts > cross_modules > uncovered_d1 > d1 > d2', () => {
  assert.deepEqual([...PRIORITY_ORDER], [
    'live_conflicts',
    'cross_modules',
    'uncovered_d1',
    'd1_count',
    'd2_count',
  ]);
});

test('比較器:live_conflicts 高的一律代價較高,即使 d1_count 小很多', () => {
  const small = buildGraph([{ from: 'm1/b.js', to: 'm1/a.js' }]);
  const big = buildGraph(
    Array.from({ length: 50 }, (_, i) => ({ from: `m1/u${i}.js`, to: 'm1/hub.js' })),
  );
  const withConflict = computeCostVector(small, 'm1/a.js', {
    liveScopes: [{ agent_id: 'w3', files: ['m1/b.js'] }],
  });
  const noConflict = computeCostVector(big, 'm1/hub.js');
  assert.ok(compareCostVectors(withConflict, noConflict) > 0);
});

test('比較器:uncovered_d1 為 null 視為 -1,「不知道」不墊高代價', () => {
  const g = buildGraph([
    { from: 'm1/b.js', to: 'm1/a.js' },
    { from: 'm1/c.js', to: 'm1/a.js' },
  ]);
  const unknown = computeCostVector(g, 'm1/a.js'); // uncovered_d1 = null
  const knownZero = computeCostVector(g, 'm1/a.js', {
    coverage: { source: COVERAGE_LCOV, covered: ['m1/b.js', 'm1/c.js'] },
  });
  assert.ok(compareCostVectors(unknown, knownZero) < 0);
});

test('模組不輸出任何單一風險分數函數(文件 6.8 雷一)', async () => {
  const mod = await import('../src/cost.js');
  const offenders = Object.keys(mod).filter((k) => /score|risk/i.test(k));
  assert.deepEqual(offenders, []);
});

console.log('');
console.log(`結果:${pass} 通過,${fail} 失敗,共 ${pass + fail} 條`);
if (fail > 0) process.exit(1);
