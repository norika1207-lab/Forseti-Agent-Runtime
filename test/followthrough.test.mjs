// 自白書七個形狀的最後一個:被動遺漏。
// 這個模組是被自己抓出來才有的 —— 三個實作加四個不做等於七,
// 看起來完整,而清單裡的「被動遺漏」既沒實作也沒被列進不做。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { VERSION, DEFAULT_CONFIG, declare, declareStrict, resolve, followThroughRate } from '../src/followthrough.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;
const M = 60_000;
const D = (over = {}) => declare({ id: 'd1', at: T, turn: 1, what: 'write the module', targets: ['src/x.js'], ...over });

t('宣告沒有位置就驗不了,直接拋錯', () => {
  assert.throws(() => declare({ id: 'a', what: 'something' }), /cannot be checked/);
});

t('宣告了具體對象,而且後來真的動了它', () => {
  const r = resolve(D(), { events: [{ at: T + M, file_path: 'src/x.js' }], currentTurn: 5, now: T + 5 * M });
  assert.equal(r.state, 'FULFILLED');
  assert.deepEqual([...r.touched], ['src/x.js']);
});

t('過了寬限期沒動作也沒再提 = 被動遺漏', () => {
  const r = resolve(D(), { events: [], currentTurn: 9, now: T + 60 * M });
  assert.equal(r.state, 'OMITTED');
  assert.match(r.reason, /Not an active falsehood/);
  assert.match(r.reason, /busy enough to look like it does/);
});

t('還在寬限期內不算遺漏,人本來就會先講再做', () => {
  const r = resolve(D(), { events: [], currentTurn: 2, now: T + M });
  assert.equal(r.state, 'PENDING');
});

t('輪數與時間取先到者', () => {
  assert.equal(resolve(D(), { events: [], currentTurn: 9, now: T + M }).state, 'OMITTED', '輪數先到');
  assert.equal(resolve(D(), { events: [], currentTurn: 1, now: T + 60 * M }).state, 'OMITTED', '時間先到');
});

// ---- 這個偵測器最容易製造噪音的地方 ----
t('宣告後停下來等對方回應,不算遺漏', () => {
  const r = resolve(D({ awaiting: true }), { events: [], currentTurn: 99, now: T + 999 * M });
  assert.equal(r.state, 'AWAITING');
  assert.match(r.reason, /Asking is collaboration, not omission/);
});

t('在等這件事由宿主判斷,這個模組不猜', () => {
  const src = readFileSync(new URL('../src/followthrough.js', import.meta.url), 'utf8');
  assert.ok(/宿主自己判斷,這裡只收布林值/.test(src));
  assert.ok(/這裡不讀文字,不做語意判斷/.test(src));
});

t('沒有具體對象的宣告驗不了,不當成完成也不當成遺漏', () => {
  const r = resolve(D({ targets: [] }), { events: [], currentTurn: 99, now: T + 999 * M });
  assert.equal(r.state, 'UNVERIFIABLE');
  assert.match(r.reason, /nothing can confirm or refute it/);
});

// ---- 讓宣告在說出口的當下就可驗 ----
t('不點名具體對象的宣告被拒絕受理', () => {
  const r = declareStrict({ id: 'x', at: T, turn: 1, what: '接下來我做剩下的四項', targets: [] });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /Name the files, commands, or artifacts/);
});

t('點名了就受理', () => {
  const r = declareStrict({ id: 'x', at: T, turn: 1, what: 'write it', targets: ['src/a.js'] });
  assert.equal(r.accepted, true);
  assert.equal(r.declaration.verifiable, true);
});

t('拒絕時回理由不拋錯,拋錯會讓人乾脆不記錄', () => {
  assert.doesNotThrow(() => declareStrict({ id: 'x', at: T, turn: 1, targets: [] }));
  const src = readFileSync(new URL('../src/followthrough.js', import.meta.url), 'utf8');
  assert.ok(/兌現率會變成一個漂亮的空數字/.test(src));
});

t('83 筆驗不了那個實測數字寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/followthrough.js', import.meta.url), 'utf8');
  assert.ok(/136 筆宣告裡有 83 筆驗不了/.test(src));
});

// ---- 兌現率 ----
t('沒有宣告時回 null,不是滿分', () => {
  const r = followThroughRate([]);
  assert.equal(r.rate, null);
  assert.match(r.note, /not a perfect score; it is no data/);
});

t('兌現率只算判得出來的那些', () => {
  const rs = [
    resolve(D({ id: 'a' }), { events: [{ at: T + M, file_path: 'src/x.js' }], currentTurn: 9, now: T + 60 * M }),
    resolve(D({ id: 'b' }), { events: [], currentTurn: 9, now: T + 60 * M }),
    resolve(D({ id: 'c', awaiting: true }), { events: [], currentTurn: 9, now: T + 60 * M }),
    resolve(D({ id: 'd', targets: [] }), { events: [], currentTurn: 9, now: T + 60 * M }),
  ];
  const r = followThroughRate(rs);
  assert.equal(r.judged, 2, '等待與驗不了的不進分母');
  assert.equal(r.rate, 0.5);
  assert.equal(r.by_state.AWAITING, 1);
});

t('驗不了的比例太高時,要說這個率只涵蓋少數', () => {
  const rs = [
    resolve(D({ id: 'a', targets: [] }), { events: [], currentTurn: 9, now: T + 60 * M }),
    resolve(D({ id: 'b', targets: [] }), { events: [], currentTurn: 9, now: T + 60 * M }),
    resolve(D({ id: 'c' }), { events: [{ at: T + M, file_path: 'src/x.js' }], currentTurn: 9, now: T + 60 * M }),
  ];
  const r = followThroughRate(rs);
  assert.ok(r.unverifiable_ratio > 0.5);
  assert.match(r.note, /covers a minority of what was said/);
});

t('寬限期可調', () => {
  assert.equal(resolve(D(), { events: [], currentTurn: 2, now: T + M, config: { graceTurns: 1, graceMs: 1 } }).state, 'OMITTED');
});

// ---- 邊界 ----
t('回傳凍結', () => {
  const d = D();
  assert.throws(() => { d.targets.push('y'); }, TypeError);
});

t('每個回傳都帶版本', () =>
  assert.equal(resolve(D(), { events: [], currentTurn: 1, now: T }).version, VERSION));

t('零依賴：followthrough.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/followthrough.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('這個模組是被自己抓出來的,那段來由不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/followthrough.js', import.meta.url), 'utf8');
  assert.ok(/它自己從清單裡消失了/.test(src));
  assert.ok(/401 輪裡有 116 輪宣告要動手/.test(src));
});

t('未校準的常數自己說了', () => {
  const src = readFileSync(new URL('../src/followthrough.js', import.meta.url), 'utf8');
  assert.ok(/三輪沒有實測校準/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

t('經過 JSON 來回的宣告一樣驗得了', () => {
  // resolve() 原本讀 declaration.verifiable,而 JSON 來回會保留它 ——
  // 但別條寫入路徑不會產生它。Stop hook 就是那條路徑,於是它一次都沒開口過。
  const raw = JSON.parse(JSON.stringify({
    id: 'd1', at: 1000, turn: 1, what: '修 X', targets: ['/p/x.js'], awaiting: false,
  }));
  const r = resolve(raw, { events: [], currentTurn: 99, now: 1000 + 60 * 60 * 1000 });
  assert.equal(r.state, 'OMITTED');
});

t('手寫 verifiable:true 但沒有 targets,騙不過去', () => {
  const r = resolve({ id: 'd2', at: 0, turn: 0, targets: [], verifiable: true },
    { events: [], currentTurn: 99, now: 9e9 });
  assert.equal(r.state, 'UNVERIFIABLE', '可驗證性是 targets 的函數,不是可宣稱的旗標');
});

t('手寫 verifiable:false 但有 targets,也騙不過去', () => {
  const r = resolve({ id: 'd3', at: 0, turn: 0, targets: ['/p/y.js'], verifiable: false },
    { events: [], currentTurn: 99, now: 9e9 });
  assert.equal(r.state, 'OMITTED');
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
