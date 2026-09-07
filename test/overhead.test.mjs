// 規格書 §15 最後一項:效益對比負擔。
// 負擔可以量,效益只能估,而這個模組拒絕把兩者相減。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { VERSION, cost, benefit, ledger, interceptOutcomes } from '../src/overhead.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('負擔是實測的,算得出總量', () => {
  const c = cost({ perCallMs: 156, calls: 100 });
  assert.equal(c.total_ms, 15600);
});

t('程序啟動的部分分開報,那是換工具跟不裝的差別', () => {
  const c = cost({ perCallMs: 156, calls: 100, processStartMs: 130 });
  assert.equal(c.own_logic_ms, 2600, '自己的邏輯只佔 26ms');
  assert.equal(c.process_start_ms, 130);
});

t('沒有實測就不算', () => assert.equal(cost({}).total_ms, null));

// ---- 效益這一邊 ----
t('不內建「一次互蓋值多少時間」,拒絕自己編一個', () => {
  const b = benefit({ collisionsBlocked: 5 });
  assert.equal(b.saved_ms, null);
  assert.match(b.note, /proving usefulness with a made-up parameter/);
});

t('呼叫端給了估值才算,而且標明是估的', () => {
  const b = benefit({ collisionsBlocked: 5, minutesPerCollision: 20 });
  assert.equal(b.saved_ms, 5 * 20 * 60000);
  assert.equal(b.is_estimate, true);
});

// ---- 拒絕給淨效益 ----
t('刻意不給淨效益,那個數字會被當成實測值', () => {
  const l = ledger(cost({ perCallMs: 156, calls: 100 }), benefit({ collisionsBlocked: 5, minutesPerCollision: 20 }));
  assert.ok(!('net_ms' in l) && !('net' in l));
  assert.match(l.note, /No net figure is given/);
});

t('兩邊哪一邊是量的哪一邊是估的,要標清楚', () => {
  const l = ledger(cost({ perCallMs: 156, calls: 100 }), benefit({ collisionsBlocked: 5, minutesPerCollision: 20 }));
  assert.equal(l.cost_measured, true);
  assert.equal(l.benefit_estimated, true);
  assert.ok(l.ratio > 1);
});

t('效益估不出來時明說兩邊不可相減', () => {
  const l = ledger(cost({ perCallMs: 156, calls: 100 }), benefit({ collisionsBlocked: 5 }));
  assert.equal(l.benefit_ms, null);
  assert.equal(l.ratio, null);
  assert.match(l.note, /must not be subtracted/);
});

// ---- 唯一不靠估值的效益指標 ----
t('被攔下之後使用者選擇取消,那是真的攔到東西', () => {
  const r = interceptOutcomes([
    { outcome: 'CANCELLED' }, { outcome: 'CANCELLED' },
    { outcome: 'PROCEEDED' }, { outcome: 'PROCEEDED' },
  ]);
  assert.equal(r.rate, 0.5);
  assert.equal(r.false_positive_burden, 0.5);
});

t('沒有攔截紀錄不是清白,是沒紀錄', () => {
  const r = interceptOutcomes([]);
  assert.equal(r.rate, null);
  assert.match(r.note, /evidence of no record/);
});

t('還沒決定的不進分母', () => {
  const r = interceptOutcomes([{ outcome: 'CANCELLED' }, { outcome: null }]);
  assert.equal(r.undecided, 1);
  assert.equal(r.rate, 1);
});

t('一次沒發生的互蓋不留紀錄,那個困難寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/overhead.js', import.meta.url), 'utf8');
  assert.ok(/一次沒發生的互蓋,\s*\n?\s*\*?\s*不會在任何地方留下紀錄|一次沒發生的互蓋不會留下紀錄/.test(src));
});

t('負擔可量效益只能估,那條分界寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/overhead.js', import.meta.url), 'utf8');
  assert.ok(/負擔可以量,效益只能估/.test(src));
  assert.ok(/拿自己編的參數證明自己有用/.test(src));
});

t('回傳凍結', () => {
  const c = cost({ perCallMs: 1, calls: 1 });
  assert.throws(() => { c.total_ms = 9; }, TypeError);
});

t('零依賴：overhead.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/overhead.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
