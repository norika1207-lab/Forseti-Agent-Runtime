// 規格書 §15 第二項:健康基線該用全域預設還是每個使用者自適應。
// 答案是自適應,理由是實測的:全域預設 400 字,而真實中位數是 126。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { VERSION, DEFAULT_CONFIG, fit, deviation, fitPerKey } from '../src/baseline.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const many = (v, n = 30) => Array(n).fill(v);

t('樣本不足時回 null,不回一個勉強算出來的數字', () => {
  const b = fit([1, 2, 3]);
  assert.equal(b.value, null);
  assert.match(b.note, /No baseline - not a default one/);
});

t('樣本夠就算得出中位數', () => {
  const b = fit([...many(100, 15), ...many(200, 15)], { healthyOnly: true });
  assert.ok(b.value >= 100 && b.value <= 200);
  assert.equal(b.samples, 30);
});

t('基線帶著分位數與樣本數,呼叫端看得到它多可信', () => {
  const b = fit(Array.from({ length: 50 }, (_, i) => i), { healthyOnly: true });
  assert.ok(b.p10 < b.value && b.value < b.p90);
  assert.equal(b.samples, 50);
});

// ---- 自適應方案最大的坑 ----
t('沒限定健康時段的基線會被標成可能污染', () => {
  const b = fit(many(100), { healthyOnly: false });
  assert.equal(b.possibly_contaminated, true);
  assert.match(b.note, /teach this baseline that its own dysfunction is normal/);
});

t('限定健康時段的就不標', () => {
  const b = fit(many(100), { healthyOnly: true });
  assert.equal(b.possibly_contaminated, false);
  assert.equal(b.note, null);
});

t('污染警告會傳進每一個基於它的判斷', () => {
  const dirty = fit(many(100), { healthyOnly: false });
  const d = deviation(30, dirty);
  assert.equal(d.baseline_contaminated, true);
  assert.match(d.note, /may have been fitted over unhealthy windows/);
});

// ---- 偏離 ----
t('沒有基線時不拿全域預設頂替', () => {
  const d = deviation(50, fit([1, 2]));
  assert.equal(d.ratio, null);
  assert.match(d.note, /A global default would defeat the purpose/);
});

t('偏離方向與比例算得出來', () => {
  const b = fit(many(100), { healthyOnly: true });
  assert.equal(deviation(50, b).direction, 'BELOW');
  assert.equal(deviation(150, b).direction, 'ABOVE');
  assert.equal(deviation(100, b).direction, 'AT');
});

t('在容忍範圍內不算異常', () => {
  const b = fit(many(100), { healthyOnly: true });
  assert.equal(deviation(80, b).abnormal, false);
  assert.equal(deviation(30, b).abnormal, true);
});

t('容忍度可調', () => {
  const b = fit(many(100), { healthyOnly: true });
  assert.equal(deviation(80, b, { deviationFactor: 0.1 }).abnormal, true);
});

// ---- 每個工具各自的基線 ----
t('不同工具用不同基線,不然慢的永遠告警快的永遠不告警', () => {
  const samples = [
    ...many(0, 0),
    ...Array.from({ length: 30 }, () => ({ key: 'Bash', value: 2000 })),
    ...Array.from({ length: 30 }, () => ({ key: 'Read', value: 50 })),
  ];
  const r = fitPerKey(samples, { healthyOnly: true });
  assert.deepEqual([...r.keys], ['Bash', 'Read']);
  assert.ok(r.baselines.get('Bash').value > r.baselines.get('Read').value * 10);
});

t('樣本不足的工具要列出來,不然呼叫端以為它們正常', () => {
  const samples = [
    ...Array.from({ length: 30 }, () => ({ key: 'Bash', value: 100 })),
    { key: 'Rare', value: 5 },
  ];
  const r = fitPerKey(samples, { healthyOnly: true });
  assert.deepEqual([...r.insufficient], ['Rare']);
  assert.equal(r.baselines.get('Rare').value, null);
});

// ---- 邊界 ----
t('回傳凍結', () => {
  const b = fit(many(100), { healthyOnly: true });
  assert.throws(() => { b.value = 1; }, TypeError);
});

t('每個回傳都帶版本', () => {
  assert.equal(fit([]).version, VERSION);
  assert.equal(deviation(1, null).version, VERSION);
});

t('零依賴：baseline.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/baseline.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('為什麼要自適應,那個實測數字寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/baseline.js', import.meta.url), 'utf8');
  // 註解會跨行,分開比對兩個數字而不是整句
  assert.ok(/全域預設原本是 400 字/.test(src));
  assert.ok(/中位數是 126 字/.test(src));
  assert.ok(/一個數字適用所有人」這個假設錯了/.test(src));
});

t('未校準的常數自己說了', () => {
  const src = readFileSync(new URL('../src/baseline.js', import.meta.url), 'utf8');
  assert.ok(/二十個沒有實測校準/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
