// 規格書 v0.1 第 9、10、11 節:觀測面與介入面。
// 最硬的一條:不可以持續盤問被觀測的模型,因為那會改變正在被量測的東西。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, PLANES, ACTIONS, PROBE_FIELDS,
  buildProbe, evaluateProbe, canIntervene, recordIntervention, interventionRate,
} from '../src/intervention.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;

t('兩個面,觀測預設開介入預設關', () =>
  assert.deepEqual(Object.keys(PLANES), ['OBSERVATION', 'INTERVENTION']));

t('六種介入動作,照第 11 節那張表', () =>
  assert.deepEqual([...ACTIONS],
    ['QUIET_ANNOTATION', 'SUGGEST_RECOVERY', 'FREEZE_RETRY', 'REPLAN', 'BLOCK_HIGH_RISK', 'CREATE_SUCCESSOR']));

t('探針七欄,照第 10 節一字不改', () =>
  assert.deepEqual([...PROBE_FIELDS],
    ['current_goal_as_understood', 'current_step', 'why_this_step_advances_goal',
     'required_constraints', 'evidence_of_progress',
     'what_would_falsify_current_strategy', 'next_step_if_falsified']));

// ---- 探針 ----
t('探針明確禁止問「你是不是飄移了」', () => {
  const p = buildProbe();
  assert.ok(p.forbidden_phrasings.some((x) => /drifting/i.test(x)));
  assert.ok(p.forbidden_phrasings.some((x) => /still following the goal/i.test(x)));
});

t('探針本身是一次介入,一定要被記錄', () => {
  const p = buildProbe({ reason: 'stagnation' });
  assert.equal(p.must_log_as_intervention, true);
});

t('回答的知識論上限是 INFERRED,不會因為它答得好就升級', () =>
  assert.equal(buildProbe().answer_epistemic_ceiling, 'INFERRED'));

t('答不出「什麼會推翻我」的策略無法被檢驗', () => {
  const r = evaluateProbe({
    current_goal_as_understood: 'a', current_step: 'b', why_this_step_advances_goal: 'c',
    required_constraints: 'd', evidence_of_progress: 'e', next_step_if_falsified: 'g',
  });
  assert.equal(r.unfalsifiable, true);
  assert.ok(r.missing.includes('what_would_falsify_current_strategy'));
});

t('AT-PROBE-01:自述說有進展但可觀測記錄相反時,可觀測的勝出', () => {
  const r = evaluateProbe({ evidence_of_progress: 'tests are passing' }, { verified_progress: 0 });
  assert.ok(r.contradictions.some((x) => /no verified progress exists/.test(x)));
  assert.match(r.note, /the observable record wins/);
});

t('答案裡點名的檔案在記錄裡找不到,算矛盾', () => {
  const r = evaluateProbe({ current_step: 'editing auth' },
    { claimed_files: ['src/auth.js'], recent_files: ['docs/blog.md'] });
  assert.ok(r.contradictions.some((x) => /do not appear in the recent observable record/.test(x)));
});

t('答不出來是提高不確定性,不是證明欺騙', () => {
  const r = evaluateProbe({});
  assert.match(r.note, /do not by themselves prove deception/);
});

t('全部答齊且不矛盾時沒有 contradictions', () => {
  const full = Object.fromEntries(PROBE_FIELDS.map((f) => [f, 'x']));
  const r = evaluateProbe(full, {});
  assert.equal(r.answered, 7);
  assert.deepEqual(r.contradictions, []);
});

// ---- 介入前置條件 ----
t('不認得的動作拋錯', () =>
  assert.throws(() => canIntervene('DELETE_EVERYTHING', {}), /Unrecognised action/));

t('高溫單獨不足以做任何硬介入', () => {
  const hot = { temperature: 0.95 };
  for (const a of ['SUGGEST_RECOVERY', 'FREEZE_RETRY', 'REPLAN', 'BLOCK_HIGH_RISK', 'CREATE_SUCCESSOR']) {
    const r = canIntervene(a, hot);
    assert.equal(r.allowed, false, a + ' 不該只憑高溫就放行');
    assert.match(r.note, /A high temperature alone is never sufficient/);
  }
});

t('安靜標註的門檻最低,那是唯一接近純觀測的動作', () =>
  assert.equal(canIntervene('QUIET_ANNOTATION', { temperature: 0.6 }).allowed, true));

t('單一強異常也能觸發標註,不必等溫度', () =>
  assert.equal(canIntervene('QUIET_ANNOTATION', { temperature: 0.1, verified_anomaly: true }).allowed, true));

t('建議復原需要高溫加上停滯或證據不符', () => {
  assert.equal(canIntervene('SUGGEST_RECOVERY', { temperature: 0.75 }).allowed, false);
  assert.equal(canIntervene('SUGGEST_RECOVERY', { temperature: 0.75, progress_stagnation: true }).allowed, true);
});

t('凍結重試要重試預算用盡而且沒有已驗證的進展', () => {
  assert.equal(canIntervene('FREEZE_RETRY', { retry_budget_exceeded: true }).allowed, false);
  assert.equal(canIntervene('FREEZE_RETRY', { retry_budget_exceeded: true, progress_stagnation: true }).allowed, true);
});

t('重新規劃要假設被推翻,溫度無關', () => {
  assert.equal(canIntervene('REPLAN', { temperature: 0.1, hypothesis_refuted: true }).allowed, true);
  assert.equal(canIntervene('REPLAN', { temperature: 0.99 }).allowed, false);
});

t('擋下高風險動作只看硬前提,不看溫度', () => {
  assert.equal(canIntervene('BLOCK_HIGH_RISK', { prerequisite_unknown: true }).allowed, true);
  assert.equal(canIntervene('BLOCK_HIGH_RISK', { temperature: 1 }).allowed, false);
});

t('建立接班要臨界健康加快照,或使用者主動要求', () => {
  assert.equal(canIntervene('CREATE_SUCCESSOR', { temperature: 0.9 }).allowed, false, '沒快照不行');
  assert.equal(canIntervene('CREATE_SUCCESSOR', { temperature: 0.9, checkpoint_available: true }).allowed, true);
  assert.equal(canIntervene('CREATE_SUCCESSOR', { user_requested: true }).allowed, true);
});

t('AT-RSC-01:臨界分數只來自一個弱啟發時,不做硬介入', () => {
  // 只有溫度高,沒有任何其他條件成立
  const r = canIntervene('CREATE_SUCCESSOR', { temperature: 0.95 });
  assert.equal(r.allowed, false);
  assert.ok(r.requires.length > 0, '要說出還缺什麼');
});

// ---- 介入紀錄與比率 ----
t('每一次介入都記下來,有沒有注入要分開', () => {
  let log = recordIntervention([], { at: T, action: 'QUIET_ANNOTATION', injected: false });
  log = recordIntervention(log, { at: T + 1, action: 'PROBE', injected: true });
  assert.equal(log.length, 2);
  assert.equal(log[1].injected, true);
});

t('注入的才會污染觀測,純標註不會', () => {
  const log = [
    { at: T, action: 'QUIET_ANNOTATION', injected: false },
    { at: T, action: 'PROBE', injected: true },
  ];
  const r = interventionRate(log, 100);
  assert.equal(r.rate, 0.02);
  assert.equal(r.injection_rate, 0.01);
});

t('沒有回合時比率是 null,不是零介入', () =>
  assert.equal(interventionRate([], 0).rate, null));

t('沒有回合數時,注入次數仍然要如實回報', () => {
  const r = interventionRate([{ at: 1, action: 'PROBE', injected: true }], 0);
  assert.equal(r.rate, null, '比率算不出來');
  assert.equal(r.injected, 1, '但注入確實發生過,寫死成 0 會讓污染從紀錄裡消失');
  assert.equal(r.interventions, 1);
});

// ---- 邊界 ----
t('回傳凍結', () => {
  const p = buildProbe();
  assert.throws(() => { p.forbidden_phrasings.push('x'); }, TypeError);
});

t('每個回傳都帶版本', () => {
  assert.equal(buildProbe().version, VERSION);
  assert.equal(canIntervene('REPLAN', {}).version, VERSION);
});

t('零依賴：intervention.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/intervention.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('觀測者效應那條的理由寫在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/intervention.js', import.meta.url), 'utf8');
  assert.ok(/問十次之後,你量到的是你自己造成的東西/.test(src));
  assert.ok(/這條沒有例外/.test(src));
});

t('為什麼前置條件比溫度嚴格,寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/intervention.js', import.meta.url), 'utf8');
  assert.ok(/被關掉的防線保護不了任何人/.test(src));
});

t('這個模組不執行任何介入,那是刻意的', () => {
  const src = readFileSync(new URL('../src/intervention.js', import.meta.url), 'utf8');
  assert.ok(/這個模組不執行任何介入/.test(src));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
