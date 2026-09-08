// Forseti v2.0 — P10 Composite Risk 與 Trend。規格 §8、§8.1、§9。對應 CT-037。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, METRICS, BANDS, DEFAULT_CONFIG, compositeRisk, bandOf, ewma, trend, reading,
} from '../src/risk.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const m = (id, score, confidence, weight = 1) => ({ id, score, confidence, weight });

t('十一個 atomic metric,照 §7 表格', () => {
  assert.equal(METRICS.length, 11);
  for (const x of ['CED', 'PS', 'GAR', 'HCD']) assert.ok(METRICS.includes(x), x);
});

t('五個 band,照 §8.1 原文', () => {
  assert.deepEqual(BANDS.map((b) => b.state),
    ['NORMAL', 'WATCH', 'UNSTABLE', 'DEGRADED', 'CRITICAL']);
  assert.equal(bandOf(0.1).state, 'NORMAL');
  assert.equal(bandOf(0.85).state, 'CRITICAL');
});

// ---- §8 composite ----
t('R 用 weight×confidence 加權,沒證據的 metric 不進分母', () => {
  const r = compositeRisk([m('CED', 1, 1), m('PS', 0, 1), m('TOS', null, null)]);
  assert.equal(r.r, 0.5);
  assert.deepEqual([...r.unmeasured], ['TOS']);
});

t('FS-RSK-001:R 與 EvidenceCoverage 一定同時出現', () => {
  const r = compositeRisk([m('CED', 0.8, 1), m('PS', null, null)]);
  assert.ok('r' in r && 'evidence_coverage' in r);
  assert.equal(r.evidence_coverage, 0.5);
});

t('CT-037 positive:高風險但覆蓋低 → LOW_EVIDENCE,而且不准擋', () => {
  const r = compositeRisk([
    m('CED', 0.9, 1), m('PS', null, null), m('TOS', null, null), m('RL', null, null),
  ]);
  assert.equal(r.state, 'LOW_EVIDENCE');
  assert.equal(r.may_block, false);
  assert.match(r.note, /MUST NOT be presented as equivalent/);
});

t('CT-037 negative:覆蓋足夠時才給正常的 band', () => {
  const r = compositeRisk([m('CED', 0.9, 1), m('PS', 0.9, 1)]);
  assert.equal(r.state, 'CRITICAL');
  assert.equal(r.may_block, true);
});

t('什麼都沒量到時 R 是 null 不是 0', () => {
  const r = compositeRisk([m('CED', null, null)]);
  assert.equal(r.r, null);
  assert.equal(r.state, 'NO_DATA');
  assert.match(r.note, /an unwired system is not a healthy system/);
});

t('§8 要求單一分數必須附最主要的貢獻訊號', () => {
  const r = compositeRisk([m('CED', 1, 1, 3), m('PS', 0.2, 1), m('TOS', 0.1, 1)]);
  assert.equal(r.top_contributors[0].id, 'CED');
  assert.ok(r.top_contributors.length <= 3);
});

t('信心低的 metric 對 R 的影響比較小', () => {
  const high = compositeRisk([m('CED', 1, 1), m('PS', 0, 1)]).r;
  const low = compositeRisk([m('CED', 1, 0.2), m('PS', 0, 1)]).r;
  assert.ok(low < high);
});

t('band 門檻自己說沒校準', () =>
  assert.equal(compositeRisk([m('CED', 0.5, 1), m('PS', 0.5, 1)]).thresholds_uncalibrated, true));

// ---- §9 EWMA ----
t('EWMA 照公式算', () => {
  const s = ewma([1, 1, 1], { alpha: 0.5 });
  assert.equal(s[0], 1);
  assert.equal(s[1], 1);
});

t('null 的分數被跳過,不是當成 0', () => {
  const s = ewma([0.8, null, 0.8], { alpha: 0.5 });
  assert.equal(s[1], s[0], '沒量到時 EWMA 停在原地');
  assert.ok(s[2] >= 0.8 - 1e-9);
});

// ---- §9 trend ----
t('positive:分數一路上升 → WORSENING,而且要提高採樣', () => {
  const r = trend([0.1, 0.2, 0.35, 0.5, 0.65]);
  assert.equal(r.direction, 'WORSENING');
  assert.ok(r.velocity > 0);
  assert.equal(r.raise_sampling, true);
  assert.equal(r.counts_as_degradation, true);
});

t('negative:分數一路下降 → IMPROVING', () => {
  const r = trend([0.7, 0.5, 0.3, 0.15]);
  assert.equal(r.direction, 'IMPROVING');
  assert.ok(r.velocity < 0);
  assert.equal(r.counts_as_degradation, false);
});

t('FS-TRD-001:單次 spike 不算 degradation', () => {
  const r = trend([0.05, 0.05, 0.9, 0.05, 0.05]);
  assert.equal(r.single_spike_only, true);
  assert.equal(r.counts_as_degradation, false, '一個健康的 session 也會有 spike');
});

t('FS-TRD-001 exclusion:Family C 的確定性硬矛盾可以憑單一事件升級', () => {
  const r = trend([0.05, 0.9], { hasDeterministicContradiction: true });
  assert.equal(r.spike_escalation_allowed, true);
});

t('FS-TRD-002:持續高又惡化才提高 challenge 優先序', () => {
  const worsening = trend([0.3, 0.4, 0.5, 0.6, 0.7]);
  assert.equal(worsening.raise_challenge_priority, true);
  assert.ok(worsening.persistence > 0.5);
});

t('FS-TRD-003:永遠不預測「多久會壞」', () => {
  const r = trend([0.1, 0.3, 0.5, 0.7, 0.9]);
  assert.equal(r.time_to_failure, 'UNKNOWN');
  assert.match(r.time_to_failure_note, /None exists yet/);
});

t('low-evidence:少於兩個量到的窗就沒有方向', () => {
  const r = trend([0.5]);
  assert.equal(r.direction, 'UNKNOWN');
  assert.equal(r.velocity, null);
  assert.match(r.note, /needs at least two points/);
});

t('α 與 k 自己說沒校準', () => {
  assert.equal(DEFAULT_CONFIG.alpha, 0.3);
  assert.equal(trend([0.1, 0.2]).thresholds_uncalibrated, true);
});

// ---- reading ----
t('reading 把三件事一起給:分數、證據、方向', () => {
  const r = reading([m('CED', 0.7, 1), m('PS', 0.7, 1)], [0.2, 0.4, 0.6]);
  assert.ok('composite' in r && 'trend' in r);
  assert.match(r.headline, /DEGRADED, worsening/);
});

t('低證據時 headline 講證據,不講風險', () => {
  const r = reading([m('CED', 0.9, 1), m('PS', null, null), m('TOS', null, null)], []);
  assert.match(r.headline, /Insufficient evidence/);
});

t('什麼都沒接時 headline 直說沒在量', () =>
  assert.match(reading([], []).headline, /Not measuring anything yet/));

// ---- 專案慣例 ----
t('零依賴:risk.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/risk.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('「同一個 0.55 從 22% 訊號算出來是不同的事」那段留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/risk.js', import.meta.url), 'utf8');
  assert.match(src, /22% 的訊號算出來/);
});

t('每個回傳都帶版本', () => {
  assert.equal(compositeRisk([]).version, VERSION);
  assert.equal(trend([]).version, VERSION);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
