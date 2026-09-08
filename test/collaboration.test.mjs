// Forseti v2.0 — CB / HCD。規格 §7.5、§13。對應 CT-027、CT-028。
// 這一份最重要的一條是 CT-027:使用者在罵髒話,但交付是健康的 → HCD 必須是零。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, CORRECTIVE_EVENT_KINDS, DEFAULT_CONFIG,
  correctionBurden, collaborationDegradation,
} from '../src/collaboration.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const ev = (kind) => ({ kind });

t('四種 corrective 事件,照 FS-HQA-001', () =>
  assert.deepEqual([...CORRECTIVE_EVENT_KINDS],
    ['CORRECTION', 'OMISSION_POINTED_OUT', 'FORCED_VERIFICATION', 'OWNER_MICRO_STEP']));

// ---- §7.5 CB ----
t('CT-028 positive:使用者一直指出漏做並被迫要求驗證 → CB 高', () => {
  const r = correctionBurden({
    events: [ev('CORRECTION'), ev('OMISSION_POINTED_OUT'), ev('FORCED_VERIFICATION')],
    autonomousVerifiedProgress: 1,
  });
  assert.equal(r.cb, 0.75);
  assert.equal(r.correction_events, 3);
});

t('CT-028 negative:自主完成很多事時,同樣的糾正次數 CB 低很多', () => {
  const few = correctionBurden({ events: [ev('CORRECTION')], autonomousVerifiedProgress: 1 });
  const many = correctionBurden({ events: [ev('CORRECTION')], autonomousVerifiedProgress: 99 });
  assert.equal(few.cb, 0.5);
  assert.ok(many.cb < 0.02, '分母裡的自主進度是關鍵');
});

t('CT-027 exclusion:情緒事件餵進來會被忽略,完全不影響 CB', () => {
  const clean = correctionBurden({ events: [ev('CORRECTION')], autonomousVerifiedProgress: 5 });
  const angry = correctionBurden({
    events: [ev('CORRECTION'), ev('USER_ANGRY'), ev('PROFANITY'), ev('FRUSTRATION')],
    autonomousVerifiedProgress: 5,
  });
  assert.equal(clean.cb, angry.cb, '罵三句不會讓 CB 動一分一毫');
  assert.equal(angry.non_corrective_events_ignored, 3);
  assert.equal(angry.sentiment_not_an_input, true);
});

t('low-evidence:沒量自主進度時 CB 是 null,不准當 0', () => {
  const r = correctionBurden({ events: [ev('CORRECTION')] });
  assert.equal(r.cb, null);
  assert.match(r.note, /would make every correction look like total failure/);
});

t('CB 分類統計得出來,方便看是哪一種 corrective labor', () => {
  const r = correctionBurden({
    events: [ev('OWNER_MICRO_STEP'), ev('OWNER_MICRO_STEP')],
    autonomousVerifiedProgress: 0,
  });
  assert.equal(r.by_kind.find((k) => k.kind === 'OWNER_MICRO_STEP').count, 2);
});

// ---- §13 HCD:FS-MET-HC-001 兩個條件 ----
t('CT-028 positive:持續高 CB + 客觀交付不足 → HUMAN_AS_QA', () => {
  const r = collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8],
    underDeliverySignals: ['PS_HIGH', 'GOAL_PROGRESS_ZERO'],
  });
  assert.equal(r.verdict, 'HUMAN_AS_QA');
  assert.equal(r.severity_family, 'B');
  assert.equal(r.recommended_response, 'RESCUE_OR_STRATEGY_RESET');
});

t('CT-027 negative:使用者不爽但交付健康 → 不是 HCD', () => {
  const r = collaborationDegradation({
    cbWindows: [0.1, 0.05, 0.1],
    underDeliverySignals: [],
  });
  assert.equal(r.verdict, 'OK');
  assert.notEqual(r.verdict, 'HUMAN_AS_QA');
});

t('FS-MET-HC-001 exclusion:糾正很多但一直有交付 → 不算失衡', () => {
  const r = collaborationDegradation({
    cbWindows: [0.7, 0.8, 0.7],
    underDeliverySignals: [],
  });
  assert.equal(r.verdict, 'CORRECTION_HEAVY_BUT_DELIVERING');
  assert.match(r.note, /Requirements evolving is not.*collaboration failing/s);
});

t('FS-MET-HC-001 exclusion:交付不足但沒有糾正負擔,也不算 HCD', () => {
  const r = collaborationDegradation({
    cbWindows: [0.1, 0.1, 0.1],
    underDeliverySignals: ['PS_HIGH'],
  });
  assert.equal(r.verdict, 'UNDER_DELIVERING_WITHOUT_CORRECTION_BURDEN');
});

t('low-evidence:窗數不足時不判,一兩次糾正是正常協作', () => {
  const r = collaborationDegradation({
    cbWindows: [0.9], underDeliverySignals: ['PS_HIGH'],
  });
  assert.equal(r.verdict, 'INSUFFICIENT_WINDOWS');
  assert.equal(r.hcd, null);
  assert.match(r.note, /collaboration working, not collaboration failing/);
});

t('sustained 是「每一個窗都高」,不是「平均高」', () => {
  const spiky = collaborationDegradation({
    cbWindows: [0.9, 0.1, 0.9], underDeliverySignals: ['PS_HIGH'],
  });
  assert.notEqual(spiky.verdict, 'HUMAN_AS_QA', '中間掉下來就不算 sustained');
});

// ---- FS-HQA-002 ----
t('FS-HQA-002:早期自主性高、後期明顯下滑,記為加強證據', () => {
  const r = collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8],
    underDeliverySignals: ['PS_HIGH'],
    earlyAutonomousBaseline: 10,
    lateAutonomousProgress: 2,
  });
  assert.ok(Math.abs(r.autonomy_drop - 0.8) < 1e-9);
  assert.equal(r.autonomy_evidence, true);
});

t('FS-HQA-002 是 MAY:沒有這個證據也照樣判得出 HCD', () => {
  const withOut = collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8], underDeliverySignals: ['PS_HIGH'],
  });
  assert.equal(withOut.verdict, 'HUMAN_AS_QA');
  assert.equal(withOut.autonomy_drop, null);
});

t('FS-HQA-003:判成 HCD 時建議 reset,而不是再丟更多警告', () => {
  const r = collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8], underDeliverySignals: ['PS_HIGH'],
  });
  assert.match(r.recommendation_reason, /more warnings add to.*the load that caused it/s);
});

// ---- 專案慣例 ----
t('這個模組連情緒參數都沒有', () => {
  const src = readFileSync(new URL('../src/collaboration.js', import.meta.url), 'utf8');
  const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
  assert.ok(!/\b(sentiment|angry|profanity|tone|emotion)\b/i.test(code));
});

t('零依賴', () => {
  const src = readFileSync(new URL('../src/collaboration.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('「糾正多才會不爽,不是不爽才叫失敗」那段因果留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/collaboration.js', import.meta.url), 'utf8');
  assert.match(src, /糾正多才會不爽,\n \* 不是不爽才叫失敗/);
});

t('門檻自己說沒校準', () => {
  assert.equal(DEFAULT_CONFIG.sustainedWindows, 3);
  assert.equal(collaborationDegradation({ cbWindows: [0.5, 0.5, 0.5] })
    .thresholds_uncalibrated, true);
});

t('每個回傳都帶版本', () => {
  assert.equal(correctionBurden({}).version, VERSION);
  assert.equal(collaborationDegradation({}).version, VERSION);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
