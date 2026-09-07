// 規格書 v0.1 第 3 節:原子訊號與複合溫度。
// 貫穿全部十個的規則:量不到回 null 不回 0,每個訊號都帶但書,
// 複合分數沒有解釋就是不合格。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  SIGNALS, WEIGHTS, STATES, VERSION, DEFAULT_CONFIG,
  s1ToolOccupancy, s2SilentExecution, s3OutputCompression, s4RetryRepetition, s5ArtifactNullity,
  s6CorrectionLoad, s7ProgressStagnation, s8ClaimEvidenceGap, s9CancellationPressure, s10StrategyPersistence,
  composite, stateOf,
} from '../src/signals.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('十個訊號的代號與名稱,照規格書第 3.1 節一字不改', () => {
  assert.equal(SIGNALS.length, 10);
  assert.deepEqual(SIGNALS.map(([id]) => id),
    ['S1','S2','S3','S4','S5','S6','S7','S8','S9','S10']);
  assert.equal(SIGNALS[6][1], 'Verified Progress Stagnation');
});

t('權重照第 3.2 節,而且加起來是 1', () => {
  assert.equal(WEIGHTS.S7, 0.14, 'S7 權重最高');
  const sum = Object.values(WEIGHTS).reduce((a, b) => a + b, 0);
  assert.ok(Math.abs(sum - 1) < 1e-9, '實際 ' + sum);
});

t('五個狀態區間照第 3.2 節', () =>
  assert.deepEqual([...STATES], ['HEALTHY', 'WATCH', 'ELEVATED', 'HIGH', 'CRITICAL']));

// ---- 貫穿全部十個的第一條:量不到回 null ----
t('十個訊號在沒有資料時全部回 null,一個都不准回 0', () => {
  const all = [
    s1ToolOccupancy({}), s2SilentExecution({}), s3OutputCompression({}),
    s4RetryRepetition([]), s5ArtifactNullity(null), s6CorrectionLoad({}),
    s7ProgressStagnation({}), s8ClaimEvidenceGap({}), s9CancellationPressure({}),
    s10StrategyPersistence({}),
  ];
  for (const s of all) {
    assert.equal(s.value, null, s.id + ' 沒資料時應回 null');
    assert.equal(s.measured, false, s.id);
  }
});

t('每個訊號都帶但書', () => {
  const all = [
    s1ToolOccupancy({ toolActiveMs: 100, windowMs: 200 }),
    s2SilentExecution({ silentMs: 50, activeMs: 100 }),
    s5ArtifactNullity({ ratio: 0.5, claimed: 2, refuted: 1, coverage: 1 }),
    s7ProgressStagnation({ lastVerifiedAt: 0, now: 1000 }),
  ];
  for (const s of all) assert.ok(s.caveat && s.caveat.length > 10, s.id + ' 缺但書');
});

// ---- 個別訊號 ----
t('S1 高佔用的但書要講明「伴隨已驗證進展時是良性的」', () => {
  const s = s1ToolOccupancy({ toolActiveMs: 900, windowMs: 1000 });
  assert.ok(Math.abs(s.value - 0.9) < 1e-9);
  assert.match(s.caveat, /benign if verified progress/);
});

t('S3 是弱證據,但書要寫明不可單獨使用', () =>
  assert.match(s3OutputCompression({ recentAvgChars: 100, baselineChars: 400 }).caveat, /never use it alone/));

t('S4 一次不算重試,重複越多分數越高', () => {
  const once = s4RetryRepetition([{ tool: 'Bash', target: 'x' }]);
  assert.equal(once.value, 0, '做一次不是重試');
  const many = s4RetryRepetition(Array(5).fill({ tool: 'Bash', target: 'x' }));
  assert.equal(many.value, 1);
});

t('S4 不同目標的相同動作不算重試', () => {
  const s = s4RetryRepetition([
    { tool: 'Bash', target: 'a' }, { tool: 'Bash', target: 'b' }, { tool: 'Bash', target: 'c' },
  ]);
  assert.equal(s.value, 0);
});

t('S5 直接吃 artifact 的 nullity,而且沒查完會標成下界', () => {
  const s = s5ArtifactNullity({ ratio: 0.5, claimed: 4, refuted: 2, coverage: 0.5 });
  assert.equal(s.value, 0.5);
  assert.match(s.caveat, /lower bound/);
});

t('S6 沒有把糾正與新需求分開時回 null,不猜', () => {
  const s = s6CorrectionLoad({ corrections: 5, totalTurns: 10 });
  assert.equal(s.value, null);
  assert.match(s.caveat, /guessing it here would produce a confident wrong number/);
});

t('S6 分開了才算', () =>
  assert.equal(s6CorrectionLoad({ corrections: 3, totalTurns: 10, separated: true }).value, 0.3));

t('S7 從沒有驗證過任何進展時回 null,而且要說那不等於沒有停滯', () => {
  const s = s7ProgressStagnation({});
  assert.equal(s.value, null);
  assert.match(s.caveat, /not the same as no stagnation/);
});

t('S7 停滯越久分數越高,滿分後不再上升', () => {
  const full = DEFAULT_CONFIG.stagnationFullMs;
  assert.ok(Math.abs(s7ProgressStagnation({ lastVerifiedAt: 0, now: full / 2 }).value - 0.5) < 1e-9);
  assert.equal(s7ProgressStagnation({ lastVerifiedAt: 0, now: full * 5 }).value, 1);
});

t('S8 沒有證據契約時,每個宣稱看起來都沒支撐,但書要講', () =>
  assert.match(s8ClaimEvidenceGap({ unsupported: 1, material: 2 }).caveat, /every claim looks unsupported/));

t('S9 量的是不安全中斷風險,不是使用者情緒', () =>
  assert.match(s9CancellationPressure({ cancels: 2, turns: 10 }).caveat, /not user mood/));

t('S10 沒有反證事件就回 null,因為那只是在做同一件事', () => {
  const s = s10StrategyPersistence({ repeatsAfterRefutation: 5, repeatsTotal: 5 });
  assert.equal(s.value, null);
  assert.match(s.caveat, /just doing the same work/);
});

t('S10 有反證之後才算固著', () =>
  assert.equal(s10StrategyPersistence({ refutedAt: 1, repeatsAfterRefutation: 3, repeatsTotal: 6 }).value, 0.5));

// ---- 複合溫度 ----
const measured = () => [
  s1ToolOccupancy({ toolActiveMs: 900, windowMs: 1000 }),
  s7ProgressStagnation({ lastVerifiedAt: 0, now: DEFAULT_CONFIG.stagnationFullMs }),
];

t('複合分數一定附貢獻最大的訊號,單一純量不合格', () => {
  const c = composite(measured());
  assert.ok(c.temperature > 0);
  assert.ok(c.top_contributors.length > 0);
  assert.ok(c.top_contributors[0].caveat, '貢獻者要帶著自己的但書');
});

t('沒量到的訊號不當成 0,而是被排除在分母外', () => {
  const withNull = [...measured(), s3OutputCompression({})];
  const without = measured();
  assert.equal(composite(withNull).temperature, composite(without).temperature,
    '加一個沒量到的訊號不該把溫度拉低');
});

t('用了多少比重的資料算出來的,要看得到', () => {
  const c = composite(measured());
  assert.ok(c.measured_weight > 0 && c.measured_weight < 1);
  assert.ok(Math.abs(c.measured_weight - (WEIGHTS.S1 + WEIGHTS.S7)) < 1e-9);
});

t('資料不到一半時要標明這個數字只能參考', () =>
  assert.match(composite(measured()).note, /indicative only/));

t('一個訊號都量不到時是「沒有讀數」,不是「健康」', () => {
  const c = composite([s1ToolOccupancy({}), s7ProgressStagnation({})]);
  assert.equal(c.temperature, null);
  assert.equal(c.state, null);
  assert.match(c.note, /not a healthy reading; it is no reading/);
});

t('量不到的訊號代號要列出來', () => {
  const c = composite([...measured(), s3OutputCompression({})]);
  assert.deepEqual([...c.unmeasured], ['S3']);
});

t('狀態區間切得對', () => {
  assert.equal(stateOf(0.1), 'HEALTHY');
  assert.equal(stateOf(0.35), 'WATCH');
  assert.equal(stateOf(0.6), 'ELEVATED');
  assert.equal(stateOf(0.8), 'HIGH');
  assert.equal(stateOf(0.9), 'CRITICAL');
  assert.equal(stateOf(null), null);
});

t('權重可覆寫,規格書說它們是暫定的', () => {
  const a = composite(measured());
  const b = composite(measured(), { weights: { S1: 0.9, S7: 0.01 } });
  assert.notEqual(a.temperature, b.temperature);
});

// ---- 邊界 ----
t('每個訊號都帶版本', () =>
  assert.equal(s1ToolOccupancy({}).version, VERSION));

t('回傳凍結', () => {
  const c = composite(measured());
  assert.throws(() => { c.top_contributors.push({}); }, TypeError);
});

t('零依賴：signals.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/signals.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('三條貫穿規則寫在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/signals.js', import.meta.url), 'utf8');
  assert.ok(/拿不到資料就回 null,不回 0/.test(src));
  assert.ok(/每個訊號都附帶它自己的但書/.test(src));
  assert.ok(/窗口大小與衰減常數全部沒有校準/.test(src));
});

t('權重是暫定的這件事寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/signals.js', import.meta.url), 'utf8');
  assert.ok(/provisional|暫定/.test(src));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
