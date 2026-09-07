// 規格書 v0.1 第 16 節的一致性契約。
// 這個模組不判斷任何事,它檢查「一個判斷有沒有資格被當成判斷」。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  EPISTEMIC, REQUIRED_FIELDS, GOVERNED_VERDICTS,
  detectorResult, statableAsFact, conformanceSummary, cannotDetermine,
} from '../src/conformance.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const FULL = {
  detector: 'x', verdict: true, epistemic: 'OBSERVED',
  inputs: { events: 10 }, version: 'x@1', thresholds: { a: 1 },
  exclusions: ['not applicable when b'], explanation: 'because a', recovery: { action: 'X' },
};

t('知識論六級,照規格書第 1 節一字不改', () =>
  assert.deepEqual([...EPISTEMIC],
    ['OBSERVED', 'VERIFIED', 'INFERRED', 'UNKNOWN', 'REFUTED', 'STALE']));

t('七項必要欄位,照第 16 節', () =>
  assert.deepEqual([...REQUIRED_FIELDS],
    ['inputs', 'version', 'thresholds', 'exclusions', 'epistemic', 'explanation', 'recovery']));

t('受管的四個字眼,照第 16 節', () =>
  assert.deepEqual([...GOVERNED_VERDICTS], ['drift', 'deception', 'failure', 'safe']));

t('七項齊全才算數', () => {
  const r = detectorResult(FULL);
  assert.equal(r.conformant, true);
  assert.equal(r.experimental, false);
  assert.deepEqual(r.missing_fields, []);
});

t('缺欄位不拋錯,拋錯會讓人填假值進去', () => {
  const r = detectorResult({ detector: 'x', verdict: true });
  assert.equal(r.conformant, false);
  assert.ok(r.missing_fields.length > 0);
});

t('缺欄位就是實驗性,而且這個標記要跟著結論走', () => {
  const { version, ...noVersion } = FULL;
  const r = detectorResult(noVersion);
  assert.equal(r.experimental, true);
  assert.deepEqual([...r.missing_fields], ['version']);
});

t('每一項缺一個都會被抓到', () => {
  for (const f of REQUIRED_FIELDS) {
    const p = { ...FULL };
    delete p[f];
    assert.deepEqual([...detectorResult(p).missing_fields], [f], '應抓到缺少 ' + f);
  }
});

t('沒給知識論狀態就是 UNKNOWN,不是猜一個', () =>
  assert.equal(detectorResult({ detector: 'x' }).epistemic, 'UNKNOWN'));

t('不認得的知識論狀態拋錯,不靜默接受', () =>
  assert.throws(() => detectorResult({ ...FULL, epistemic: 'PROBABLY' }), /Unrecognised epistemic/));

t('recovery 明確給 null 算有填,那跟忘了填不一樣', () => {
  const r = detectorResult({ ...FULL, recovery: null });
  assert.equal(r.conformant, true, 'null 是一個回答,undefined 才是沒回答');
});

// ---- 可不可以當事實講 ----
t('只有 OBSERVED 與 VERIFIED 可以當事實講', () => {
  assert.equal(statableAsFact(detectorResult({ ...FULL, epistemic: 'OBSERVED' })), true);
  assert.equal(statableAsFact(detectorResult({ ...FULL, epistemic: 'VERIFIED' })), true);
  for (const s of ['INFERRED', 'UNKNOWN', 'REFUTED', 'STALE']) {
    assert.equal(statableAsFact(detectorResult({ ...FULL, epistemic: s })), false, s + ' 不可當事實');
  }
});

// ---- 整份報告 ----
t('報告要講出有幾個是實驗性的', () => {
  const s = conformanceSummary([detectorResult(FULL), detectorResult({ detector: 'y' })]);
  assert.equal(s.total, 2);
  assert.equal(s.conformant, 1);
  assert.equal(s.experimental, 1);
  assert.deepEqual([...s.experimental_detectors], ['y']);
});

t('全部都是實驗性時,整份報告就是實驗性的', () => {
  const s = conformanceSummary([detectorResult({ detector: 'a' }), detectorResult({ detector: 'b' })]);
  assert.equal(s.report_is_experimental, true);
});

t('有一個夠格,報告就不算整份實驗性', () => {
  const s = conformanceSummary([detectorResult(FULL), detectorResult({ detector: 'b' })]);
  assert.equal(s.report_is_experimental, false);
});

t('知識論狀態的分佈要看得到', () => {
  const s = conformanceSummary([
    detectorResult({ ...FULL, epistemic: 'OBSERVED' }),
    detectorResult({ ...FULL, epistemic: 'INFERRED' }),
    detectorResult({ ...FULL, epistemic: 'INFERRED' }),
  ]);
  assert.equal(s.by_epistemic.INFERRED, 2);
});

t('空報告不算實驗性,那是沒有東西不是有問題', () =>
  assert.equal(conformanceSummary([]).report_is_experimental, false));

// ---- 判斷不了的標準回覆 ----
t('沒有可靠目標時的回覆只有一個寫法', () => {
  const r = cannotDetermine('drift', 'no goal was declared');
  assert.equal(r.epistemic, 'UNKNOWN');
  assert.equal(r.verdict, null);
  assert.match(r.explanation, /cannot be determined/);
  assert.ok(!/drifted/.test(r.explanation), '規格書第 4.1 節:不准說 agent drifted');
});

t('判斷不了的回覆本身也要夠格,不然它會被當成實驗性的雜訊', () =>
  assert.equal(cannotDetermine('drift', 'no goal').conformant, true));

// ---- 邊界 ----
t('回傳凍結', () => {
  const r = detectorResult(FULL);
  assert.throws(() => { r.exclusions.push('x'); }, TypeError);
});

t('零依賴：conformance.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/conformance.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('七項各自的理由寫在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/conformance.js', import.meta.url), 'utf8');
  for (const why of ['沒有版本', '沒有門檻', '沒有排除', '沒有知識論', '沒有解釋', '沒有復原']) {
    assert.ok(src.includes(why), '缺少理由: ' + why);
  }
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
