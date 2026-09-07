// 規格書 v0.1 第 5 節:事件先收窄,再針對性語意檢視。
// 全 session 語意讀取是例外,不是預設。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { VERSION, DEFAULT_CONFIG, bucketize, findPeaks, findChangePoints, findMotifs, selectWindows } from '../src/windows.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;
const M = 60_000;
const ev = (min, tool = 'Bash', target = 'a.js') => ({ at: T + min * M, tool, target });

// ---- 分桶 ----
t('依時間切桶,不依事件數', () => {
  const bs = bucketize([ev(0), ev(1), ev(20)], { bucketMs: 5 * M });
  assert.equal(bs.length, 5);
  assert.equal(bs[0].count, 2);
  assert.equal(bs[4].count, 1);
  assert.equal(bs[1].count, 0, '空桶要留著,活動密度本身是訊號');
});

t('空輸入回空,不炸', () => assert.deepEqual(bucketize([]), []));

t('桶帶得出時間範圍', () => {
  const bs = bucketize([ev(0), ev(9)], { bucketMs: 5 * M });
  assert.equal(bs[0].from, T);
  assert.equal(bs[1].from, T + 5 * M);
});

// ---- 峰值 ----
t('顯著高於平均的桶才算峰值', () => {
  const scores = [0, 0, 0, 0, 0, 10, 0, 0].map((v, i) => ({ index: i, from: T + i * M, value: v }));
  const p = findPeaks(scores);
  assert.equal(p.length, 1);
  assert.equal(p[0].index, 5);
  assert.equal(p[0].kind, 'PEAK');
});

t('全部一樣高時沒有峰值,而且那不代表沒有異常', () => {
  const flat = [5, 5, 5, 5, 5].map((v, i) => ({ index: i, value: v }));
  assert.deepEqual(findPeaks(flat), [], '標準差為零,這個方法在這裡看不出東西');
});

t('資料太少不硬找', () => assert.deepEqual(findPeaks([{ index: 0, value: 9 }]), []));

t('門檻可調', () => {
  const scores = [1, 1, 1, 3, 1].map((v, i) => ({ index: i, value: v }));
  assert.equal(findPeaks(scores, { minPeakZ: 5 }).length, 0);
  assert.ok(findPeaks(scores, { minPeakZ: 1 }).length > 0);
});

// ---- 變點 ----
t('變點找的是「開始不一樣了」,不是「這裡特別高」', () => {
  // 平緩爬升:有峰值,沒有明顯變點
  const ramp = [1, 2, 3, 4, 5, 6, 7, 20].map((v, i) => ({ index: i, from: T + i * M, value: v }));
  const cp = findChangePoints(ramp);
  assert.ok(cp.length > 0, '最後那一跳是變點');
  assert.equal(cp[0].index, 7);
});

t('完全平穩沒有變點', () => {
  const flat = [3, 3, 3, 3, 3, 3].map((v, i) => ({ index: i, from: T, value: v }));
  assert.deepEqual(findChangePoints(flat), []);
});

// ---- 重複母題 ----
t('同一個桶裡重複夠多次才算母題', () => {
  const bs = bucketize([ev(0), ev(0), ev(0), ev(0)], { bucketMs: 5 * M });
  const m = findMotifs(bs, (e) => `${e.tool}|${e.target}`);
  assert.equal(m.length, 1);
  assert.equal(m[0].value, 4);
});

t('不同目標的相同動作不是同一個母題', () => {
  const bs = bucketize([ev(0, 'Bash', 'a'), ev(0, 'Bash', 'b'), ev(0, 'Bash', 'c')], { bucketMs: 5 * M });
  assert.deepEqual(findMotifs(bs, (e) => `${e.tool}|${e.target}`), []);
});

t('次數門檻可調', () => {
  const bs = bucketize([ev(0), ev(0)], { bucketMs: 5 * M });
  assert.equal(findMotifs(bs, (e) => e.tool).length, 0);
  assert.equal(findMotifs(bs, (e) => e.tool, { motifMinRepeats: 2 }).length, 1);
});

// ---- 選窗口 ----
const mkBuckets = () => bucketize(
  [...Array(60)].map((_, i) => ev(i)), { bucketMs: 5 * M });

t('選前 K 個,並往前後擴脈絡', () => {
  const bs = mkBuckets();
  const cands = [{ index: 6, from: bs[6].from, value: 9, z: 3, kind: 'PEAK' }];
  const r = selectWindows(cands, bs, { topK: 1, contextBefore: 1, contextAfter: 1 });
  assert.equal(r.windows.length, 1);
  assert.deepEqual([...r.windows[0].bucket_range], [5, 7]);
});

t('重疊的窗口合併,不為同一段脈絡付兩次錢', () => {
  const bs = mkBuckets();
  const cands = [
    { index: 5, value: 9, z: 3, kind: 'PEAK' },
    { index: 6, value: 8, z: 2.5, kind: 'PEAK' },
  ];
  const r = selectWindows(cands, bs, { topK: 2, contextBefore: 1, contextAfter: 1 });
  assert.equal(r.windows.length, 1, '兩個相鄰的候選應合併成一段');
  assert.deepEqual([...r.windows[0].bucket_range], [4, 7]);
  assert.equal(r.windows[0].reasons.length, 2, '合併後兩個理由都要留著');
});

t('分開的窗口不合併', () => {
  const bs = mkBuckets();
  const cands = [
    { index: 1, value: 9, z: 3, kind: 'PEAK' },
    { index: 10, value: 8, z: 2.5, kind: 'PEAK' },
  ];
  assert.equal(selectWindows(cands, bs, { topK: 2 }).windows.length, 2);
});

t('收窄比例算得出來,那是這個模組唯一的效益指標', () => {
  const bs = mkBuckets();
  const r = selectWindows([{ index: 6, value: 9, z: 3, kind: 'PEAK' }], bs, { topK: 1 });
  assert.ok(r.reduction > 0 && r.reduction < 0.3, '應大幅收窄,實際 ' + r.reduction);
});

t('找不到可疑窗口時要說清楚那不等於沒問題', () => {
  const r = selectWindows([], mkBuckets());
  assert.equal(r.windows.length, 0);
  assert.match(r.note, /does not mean nothing is wrong/);
});

t('每個窗口都標明語意結果的知識論上限是 INFERRED', () => {
  const bs = mkBuckets();
  const r = selectWindows([{ index: 6, value: 9, z: 3, kind: 'PEAK' }], bs, { topK: 1 });
  assert.equal(r.windows[0].result_epistemic_ceiling, 'INFERRED',
    '讀了原文不會讓語意結論升級成 VERIFIED');
});

t('窗口帶得出實際事件,宿主才有東西可送', () => {
  const bs = mkBuckets();
  const r = selectWindows([{ index: 6, value: 9, z: 3, kind: 'PEAK' }], bs, { topK: 1 });
  assert.ok(r.windows[0].event_count > 0);
  assert.equal(r.windows[0].events.length, r.windows[0].event_count);
});

// ---- 端到端:注入一個異常,看選不選得到 ----
t('端到端:一個注入的異常窗口要被選進前 K,而且不用送全部', () => {
  // 正常區:每五分鐘一個動作。異常區:第 30 分鐘有 20 次相同動作。
  const evs = [];
  for (let i = 0; i < 60; i += 5) evs.push(ev(i, 'Read', 'f' + i));
  for (let k = 0; k < 20; k++) evs.push(ev(30, 'Bash', 'stuck.sh'));

  const bs = bucketize(evs, { bucketMs: 5 * M });
  const counts = bs.map((b) => ({ index: b.index, from: b.from, value: b.count }));
  const cands = [...findPeaks(counts), ...findMotifs(bs, (e) => `${e.tool}|${e.target}`)];
  const r = selectWindows(cands, bs, { topK: 3 });

  assert.ok(r.windows.length > 0);
  const hit = r.windows.some((w) => w.events.some((e) => e.target === 'stuck.sh'));
  assert.ok(hit, '注入的異常必須落在選出的窗口裡');
  assert.ok(r.reduction < 1, '而且不是把全部都選進來,實際 ' + r.reduction);
});

// ---- 邊界 ----
t('回傳凍結', () => {
  const r = selectWindows([{ index: 0, value: 1, z: 2, kind: 'PEAK' }], mkBuckets());
  assert.throws(() => { r.windows.push({}); }, TypeError);
});

t('零依賴：windows.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/windows.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('這個模組不呼叫任何模型,那是刻意的', () => {
  const src = readFileSync(new URL('../src/windows.js', import.meta.url), 'utf8');
  assert.ok(/這個模組不呼叫任何模型/.test(src));
});

t('稀釋那個理由寫在原始碼裡,那才是真正的動機', () => {
  const src = readFileSync(new URL('../src/windows.js', import.meta.url), 'utf8');
  assert.ok(/稀釋/.test(src));
  assert.ok(/省錢只是副作用/.test(src));
});

t('未校準的常數自己說了', () => {
  const src = readFileSync(new URL('../src/windows.js', import.meta.url), 'utf8');
  assert.ok(/以下全部沒有實測校準/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
