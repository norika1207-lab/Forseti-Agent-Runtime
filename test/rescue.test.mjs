// 規格書 v0.1 第 7 節:可見存活與安全中斷。
// 使用者按 ESC 通常不是因為知道出事,是因為不知道有沒有出事。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, SNAPSHOT_FIELDS, DEFAULT_CONFIG,
  createSnapshot, silentExecutionRatio, unsafeInterruptRate, interruptReadiness, livenessReport,
} from '../src/rescue.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;
const M = 60_000;
const FULL = {
  objective: 'ship auth', current_step: 'wire the token refresh',
  last_verified_state: 'tests green at 3f2a1', active_hypothesis: 'refresh races with logout',
  open_tool_calls: [], artifact_refs: ['src/auth.js'], unresolved_decisions: ['cookie vs header'],
  exact_next_step: 'run test/auth.test.mjs and read the first failure', timestamp: T,
};

t('九個欄位照規格書第 7 節,一字不改', () =>
  assert.deepEqual([...SNAPSHOT_FIELDS],
    ['objective', 'current_step', 'last_verified_state', 'active_hypothesis',
     'open_tool_calls', 'artifact_refs', 'unresolved_decisions', 'exact_next_step', 'timestamp']));

// ---- 快照 ----
t('九項齊全才算可用', () => {
  const s = createSnapshot(FULL);
  assert.equal(s.usable, true);
  assert.deepEqual(s.missing, []);
});

t('缺欄位不拋錯,會說自己缺什麼', () => {
  const { objective, ...rest } = FULL;
  const s = createSnapshot(rest);
  assert.equal(s.usable, false);
  assert.deepEqual([...s.missing], ['objective']);
});

t('缺 exact_next_step 特別標,那是唯一真正省時間的欄位', () => {
  const { exact_next_step, ...rest } = FULL;
  const s = createSnapshot(rest);
  assert.equal(s.lacks_next_step, true);
  assert.match(s.note, /re-derive it/);
});

t('每一項缺一個都抓得到', () => {
  for (const f of SNAPSHOT_FIELDS) {
    const p = { ...FULL };
    delete p[f];
    assert.ok(createSnapshot(p).missing.includes(f), '應抓到缺 ' + f);
  }
});

t('空陣列是有效值,不算缺', () => {
  const s = createSnapshot({ ...FULL, open_tool_calls: [], unresolved_decisions: [] });
  assert.equal(s.usable, true, '沒有未決事項是一個回答,不是沒回答');
});

// ---- 沉默執行 ----
t('完全沒有心跳時,使用者整段時間都在猜', () => {
  // 窗口要遠大於校準後的心跳間隔(230 秒),不然扣掉容忍值之後比例算不出來
  const r = silentExecutionRatio([], { activeFrom: T, activeTo: T + 60 * M });
  assert.ok(r.ratio > 0.8);
  assert.match(r.note, /could not tell alive from hung/);
});

t('心跳夠密時沉默比接近零', () => {
  const beats = [];
  for (let i = 1; i <= 10; i++) beats.push(T + i * M);
  const r = silentExecutionRatio(beats, { activeFrom: T, activeTo: T + 10 * M });
  assert.equal(r.ratio, 0);
});

t('長沉默會被數成事件', () => {
  // 校準後一次沉默事件的門檻是 10 分鐘
  const r = silentExecutionRatio([T + 15 * M], { activeFrom: T, activeTo: T + 20 * M });
  assert.ok(r.episodes >= 1);
  assert.ok(r.longest_ms >= 15 * M);
});

t('沒有執行區間就直說,不硬算', () =>
  assert.equal(silentExecutionRatio([], {}).ratio, null));

t('量的是看不看得到,不是有沒有在做事', () => {
  const src = readFileSync(new URL('../src/rescue.js', import.meta.url), 'utf8');
  assert.ok(/一個安靜但正確的長工作,這個數字會很高,而那不是錯誤/.test(src));
});

// ---- 不安全中斷 ----
t('沒有人中斷過時回 null,不是 0', () => {
  const r = unsafeInterruptRate([]);
  assert.equal(r.rate, null, '沒中斷過跟每次都安全是兩件事');
});

t('沒留快照的中斷算不安全', () => {
  const r = unsafeInterruptRate([{ at: T }, { at: T, snapshot: createSnapshot(FULL) }]);
  assert.equal(r.rate, 0.5);
  assert.equal(r.unsafe, 1);
});

t('有快照但缺 exact_next_step 的單獨數', () => {
  const { exact_next_step, ...rest } = FULL;
  const r = unsafeInterruptRate([{ at: T, snapshot: createSnapshot(rest) }]);
  assert.equal(r.without_next_step, 1);
  assert.equal(r.unsafe, 1, '缺欄位的快照本來就不算可用');
});

// ---- 中斷前的準備度 ----
t('沒有快照就還不能安全中斷', () => {
  const r = interruptReadiness({});
  assert.equal(r.ready, false);
  assert.match(r.blockers[0], /No recovery snapshot/);
});

t('還有工具在跑時要講明結果會遺失', () => {
  const r = interruptReadiness({ snapshot: createSnapshot(FULL), openToolCalls: [{ id: 'a' }, { id: 'b' }] });
  assert.equal(r.ready, false);
  assert.ok(r.blockers.some((b) => /results will be lost/.test(b)));
});

t('快照完整且沒有懸空的工具呼叫時可以安全中斷', () => {
  const r = interruptReadiness({ snapshot: createSnapshot(FULL), openToolCalls: [] });
  assert.equal(r.ready, true);
  assert.deepEqual(r.blockers, []);
});

t('距離上一次已驗證推進多久,中斷之後要從那裡接', () => {
  const r = interruptReadiness({ snapshot: createSnapshot(FULL), lastVerifiedAt: T, now: T + 5 * M });
  assert.equal(r.last_verified_progress_age_ms, 5 * M);
});

t('拿不到就是 null,不填 0', () =>
  assert.equal(interruptReadiness({ snapshot: createSnapshot(FULL) }).last_verified_progress_age_ms, null));

// ---- 三個指標一起看 ----
t('三個都量不到時明說,不回一組零', () => {
  const r = livenessReport({ silent: null, unsafe: null, lastVerifiedAgeMs: null });
  assert.equal(r.measured, 0);
  assert.match(r.note, /not a healthy system; it is an unmeasured one/);
});

t('量到幾個就講幾個', () => {
  const r = livenessReport({
    silent: silentExecutionRatio([T + M], { activeFrom: T, activeTo: T + 2 * M }),
    unsafe: unsafeInterruptRate([{ at: T, snapshot: createSnapshot(FULL) }]),
    lastVerifiedAgeMs: 1000,
  });
  assert.equal(r.measured, 3);
  assert.equal(r.note, null);
});

// ---- 邊界 ----
t('回傳凍結', () => {
  const s = createSnapshot(FULL);
  assert.throws(() => { s.artifact_refs.push('x'); }, TypeError);
});

t('每個回傳都帶版本', () => {
  assert.equal(createSnapshot(FULL).version, VERSION);
  assert.equal(interruptReadiness({}).version, VERSION);
});

t('零依賴：rescue.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/rescue.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('這個模組不中斷任何東西,那是刻意的', () => {
  const src = readFileSync(new URL('../src/rescue.js', import.meta.url), 'utf8');
  assert.ok(/這個模組不中斷任何東西/.test(src));
});

t('為什麼中斷發生在最糟的時間點,寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/rescue.js', import.meta.url), 'utf8');
  assert.ok(/不知道的成本比中斷還高/.test(src));
});

t('未校準的常數自己說了', () => {
  const src = readFileSync(new URL('../src/rescue.js', import.meta.url), 'utf8');
  assert.ok(/以下沒有實測校準/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
