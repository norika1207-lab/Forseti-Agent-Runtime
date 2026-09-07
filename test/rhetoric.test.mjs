// 自白書的信心詞前置與假坦白。
// 這兩個原本被歸進「需要語意判讀,永久不做」,那個歸類本身
// 就是自白書裡的另一條:把一條真理由擴大成假限制。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { VERSION, CONFIDENCE_MARKERS, STILL_OUT_OF_SCOPE, confidenceLoad, falseConfessions } from '../src/rhetoric.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;

t('詞表含自白書原文列的四個', () => {
  for (const m of ['killer', '坐實', '最硬', '負責任講']) {
    assert.ok(CONFIDENCE_MARKERS.includes(m), '缺 ' + m);
  }
});

// ---- 信心詞 ----
t('沒有證據計數時不給比值,絕對數量沒有意義', () => {
  const r = confidenceLoad('這條我可以負責任講,是坐實的');
  assert.equal(r.marker_count, 2);
  assert.equal(r.ratio, null);
  assert.match(r.note, /a well-supported claim may legitimately be stated with confidence/);
});

t('信心詞配上零證據才標出來', () => {
  const r = confidenceLoad('這是 killer,鐵證', { evidenceCount: 0 });
  assert.equal(r.flagged, true);
  assert.match(r.note, /it is a place worth looking/);
});

t('有證據撐著的信心詞不標', () =>
  assert.equal(confidenceLoad('這是 killer', { evidenceCount: 5 }).flagged, false));

t('沒有信心詞就沒有東西可標', () => {
  const r = confidenceLoad('改好了,測試過了', { evidenceCount: 0 });
  assert.equal(r.marker_count, 0);
  assert.equal(r.flagged, false);
});

t('每一筆證據配幾個信心詞,算得出來', () => {
  const r = confidenceLoad('killer 而且坐實', { evidenceCount: 2 });
  assert.equal(r.ratio, 1);
});

t('這個偵測器永遠標成實驗性,它會誤判', () => {
  assert.equal(confidenceLoad('x').experimental, true);
  assert.equal(confidenceLoad('killer', { evidenceCount: 0 }).experimental, true);
});

t('會誤判這件事寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/rhetoric.js', import.meta.url), 'utf8');
  assert.ok(/這兩個偵測器都會誤判,而且必須說出來/.test(src));
  assert.ok(/一個到處都在叫的偵測器會被關掉/.test(src));
});

// ---- 假坦白 ----
t('自我糾錯後來被推翻 = 假坦白', () => {
  const r = falseConfessions([{ id: 'c1', at: T, accuses: 'btmgr/main.cpp:101', verdict: 'OVERTURNED' }]);
  assert.equal(r.overturned.length, 1);
  assert.equal(r.rate, 1);
  assert.match(r.overturned[0].note, /it discredited something that was correct/);
});

t('自我糾錯成立就不是假坦白', () =>
  assert.equal(falseConfessions([{ id: 'c1', at: T, verdict: 'UPHELD' }]).overturned.length, 0));

t('還沒裁決的不進分母,沒裁決不等於成立也不等於不成立', () => {
  const r = falseConfessions([
    { id: 'a', at: T, verdict: 'OVERTURNED' },
    { id: 'b', at: T, verdict: null },
  ]);
  assert.equal(r.undecided, 1);
  assert.equal(r.rate, 1, '只有一筆裁決過,那一筆被推翻');
  assert.match(r.note, /excluded from the rate/);
});

t('全部都還沒裁決時比率是 null', () =>
  assert.equal(falseConfessions([{ id: 'a', at: T, verdict: null }]).rate, null));

t('沒有自我糾錯紀錄不是清白,是沒紀錄', () => {
  const r = falseConfessions([]);
  assert.match(r.note, /Not a clean record - no record/);
});

t('這個偵測器完全不讀文字,只比對時序', () => {
  const src = readFileSync(new URL('../src/rhetoric.js', import.meta.url), 'utf8');
  assert.ok(/這個偵測器完全不讀文字/.test(src));
});

// ---- 仍然不做的那兩個 ----
t('剩下兩個不做的,理由要具體到能被反駁', () => {
  assert.equal(STILL_OUT_OF_SCOPE.length, 2);
  assert.deepEqual(STILL_OUT_OF_SCOPE.map((x) => x.shape), ['SEMANTIC_SWAP', 'FLOOR_AS_CEILING']);
  for (const x of STILL_OUT_OF_SCOPE) {
    assert.ok(x.why.length > 60, x.shape + ' 的理由太短,那種理由沒辦法被檢驗');
  }
});

t('把真理由擴大成假限制,這條來由留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/rhetoric.js', import.meta.url), 'utf8');
  assert.ok(/把一條真理由擴大成假限制/.test(src));
});

// ---- 邊界 ----
t('回傳凍結', () => {
  const r = confidenceLoad('killer', { evidenceCount: 0 });
  assert.throws(() => { r.markers.push({}); }, TypeError);
});

t('每個回傳都帶版本', () => {
  assert.equal(confidenceLoad('x').version, VERSION);
  assert.equal(falseConfessions([]).version, VERSION);
});

t('零依賴：rhetoric.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/rhetoric.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('空輸入不炸', () => {
  assert.equal(confidenceLoad(null).marker_count, 0);
  assert.equal(falseConfessions(null).total, 0);
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
