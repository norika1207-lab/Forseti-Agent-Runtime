// Forseti v2.0 — P12 ladder / §17 rescue / P13 continuity。對應 CT-040。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, LADDER, chooseIntervention, RESCUE_SEQUENCE, buildRecoveryCapsule,
  rescueCard, CONTEXT_KINDS, selectHealthyContext, verifyFirstResumedAction,
} from '../src/recovery.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('六階 ladder,照 §16.1 原文', () =>
  assert.deepEqual(LADDER.map((l) => l.name),
    ['OBSERVE', 'EXPLAIN', 'CHALLENGE', 'SUGGEST', 'RESCUE', 'GUARD']));

// ---- FS-INT-001 / 002 / 003 ----
t('FS-INT-001:什麼都沒量到時預設 L0,不是預設擋', () => {
  const r = chooseIntervention({});
  assert.equal(r.level, 0);
  assert.equal(r.name, 'OBSERVE');
});

t('FS-INT-002:每次介入都回答四個問題', () => {
  const r = chooseIntervention({ risk: 0.65 });
  for (const f of ['evidence_refs', 'confidence', 'why_now', 'lowest_cost_action']) {
    assert.ok(f in r, `缺 ${f}`);
  }
  assert.ok(r.why_now.length > 0);
});

t('FS-INT-003 positive:硬證據加政策都齊了,但沒開啟硬擋 → 降到 L3', () => {
  const r = chooseIntervention({
    hardEvidence: true, policyRequiresBlock: true, hardBlockingEnabled: false,
  });
  assert.equal(r.level, 3);
  assert.match(r.why_now, /blocking is not a default/);
});

t('FS-INT-003 negative:明確開啟之後才走到 L5', () => {
  const r = chooseIntervention({
    hardEvidence: true, highRiskExternalEffect: true, hardBlockingEnabled: true,
  });
  assert.equal(r.level, 5);
  assert.equal(r.name, 'GUARD');
  assert.match(r.lowest_cost_action, /Block the specific action, not the session/);
});

t('exclusion:只有高分沒有硬證據,永遠到不了 L5', () => {
  const r = chooseIntervention({ risk: 0.99, hardBlockingEnabled: true });
  assert.ok(r.level < 5, '高溫本身從來不是擋人的理由');
});

t('風險分階對應到 ladder', () => {
  assert.equal(chooseIntervention({ risk: 0.1 }).level, 0);
  assert.equal(chooseIntervention({ risk: 0.25 }).level, 1);
  assert.equal(chooseIntervention({ risk: 0.45 }).level, 2);
  assert.equal(chooseIntervention({ risk: 0.65 }).level, 3);
});

t('趨勢惡化會讓中等風險升到 CHALLENGE', () =>
  assert.equal(chooseIntervention({ risk: 0.25, trendDirection: 'WORSENING' }).level, 2));

t('使用者主動要求交接,直接走 RESCUE', () =>
  assert.equal(chooseIntervention({ userRequested: true }).level, 4));

t('危急但沒有 checkpoint 時不會硬走 RESCUE', () =>
  assert.equal(chooseIntervention({ risk: 0.9, checkpointAvailable: false }).level, 3));

// ---- §17 rescue ----
t('rescue 流程八步,照 §17 原文與順序', () => {
  assert.equal(RESCUE_SEQUENCE[0], 'DETECT');
  assert.equal(RESCUE_SEQUENCE[RESCUE_SEQUENCE.length - 1], 'VERIFY_FIRST_RESUMED_ACTION');
  assert.equal(RESCUE_SEQUENCE.length, 8);
});

t('FS-RCV-001 positive:capsule 帶走該帶的,並列出刻意留下的敘事', () => {
  const c = buildRecoveryCapsule({
    verifiedWork: ['w1'], currentArtifacts: ['a.js'], activeGoal: 'ship auth',
    corrections: [{ id: 'c1' }], unknowns: ['does the token refresh?'],
    invalidatedNarrative: ['the DB was corrupted'],
    prohibitedRetries: ['reinstall node_modules'],
    exactNextStep: 'run the auth test',
  });
  assert.equal(c.active_goal, 'ship auth');
  assert.equal(c.unknowns_carried, 1);
  assert.deepEqual([...c.excluded_invalidated_narrative], ['the DB was corrupted']);
  assert.match(c.note, /usually part of what.*broke it/s);
});

t('FS-RCV-001:successor 的第一步一定要重新驗證', () =>
  assert.equal(buildRecoveryCapsule({}).first_action_must_be_reverified, true));

t('FS-RCV-002:rescue card 給一個方案,不給一堆告警', () => {
  const c = buildRecoveryCapsule({ activeGoal: 'g', exactNextStep: 'step 4' });
  const card = rescueCard(c);
  assert.match(card.recommended_action, /step 4/);
  assert.ok(!('warnings' in card), '不准有 warnings 陣列');
  assert.ok(Array.isArray([...card.preserved]));
});

t('沒有 next step 時給一個安全的預設方案,不是留白', () =>
  assert.match(rescueCard(buildRecoveryCapsule({})).recommended_action,
    /clean successor and re-verify/));

// ---- §18 continuity:CT-040 ----
t('FS-CTX-001 三種 context 分開', () =>
  assert.deepEqual([...CONTEXT_KINDS],
    ['CHAT_HISTORY', 'CANONICAL_PROJECT_STATE', 'HEALTHY_COLLABORATION_CONTEXT']));

t('CT-040 positive:最新那段又爛又多更正,要選前面健康的那段', () => {
  const r = selectHealthyContext([
    { id: 'early', verified_progress: 0.8, correction_burden: 0.1, goal_stable: true },
    { id: 'middle', verified_progress: 0.5, correction_burden: 0.3, goal_stable: true },
    { id: 'latest', verified_progress: 0.05, correction_burden: 0.9, goal_stable: false },
  ]);
  assert.equal(r.selected.id, 'early');
  assert.equal(r.selected.is_most_recent, false, '不是選最新的');
  assert.match(r.selection_rule, /highest verified progress/);
});

t('CT-040:失敗段落留著查,但明確標成不可當模板', () => {
  const r = selectHealthyContext([
    { id: 'good', verified_progress: 0.9, correction_burden: 0.05, goal_stable: true },
    { id: 'bad', verified_progress: 0.02, correction_burden: 0.95, goal_stable: false },
  ]);
  const bad = r.forensic_only.find((f) => f.id === 'bad');
  assert.ok(bad);
  assert.equal(bad.may_be_used_as_template, false);
  assert.match(bad.reason, /forensics only/);
});

t('CT-040 negative:最新那段剛好也是最健康的,就選它', () => {
  const r = selectHealthyContext([
    { id: 'a', verified_progress: 0.2, correction_burden: 0.5, goal_stable: true },
    { id: 'b', verified_progress: 0.9, correction_burden: 0.05, goal_stable: true },
  ]);
  assert.equal(r.selected.id, 'b');
  assert.equal(r.selected.is_most_recent, true);
});

t('CT-040 low-evidence:沒有量到的話寧可不選,也不退回「拿最新的」', () => {
  const r = selectHealthyContext([{ id: 'a' }, { id: 'b' }]);
  assert.equal(r.selected, null);
  assert.match(r.note, /exactly what FS-CTX-002 forbids/);
});

t('目標不穩的片段會被打折', () => {
  const stable = selectHealthyContext([
    { id: 's', verified_progress: 0.6, correction_burden: 0, goal_stable: true },
    { id: 'u', verified_progress: 0.7, correction_burden: 0, goal_stable: false },
  ]);
  assert.equal(stable.selected.id, 's', '0.6 穩定 勝過 0.7 不穩定');
});

// ---- §28.5 ----
t('successor 第一步沒驗過就不准進入正常模式', () => {
  const r = verifyFirstResumedAction({ action: 'run tests' });
  assert.equal(r.may_enter_normal_mode, false);
  assert.match(r.note, /carries the previous session's.*assumptions forward untested/s);
});

t('驗過而且通過才放行', () => {
  const r = verifyFirstResumedAction({ action: 'x', verifierResult: { outcome: 'PASS' } });
  assert.equal(r.may_enter_normal_mode, true);
});

t('驗了但沒過,一樣不放行', () =>
  assert.equal(verifyFirstResumedAction({ action: 'x', verifierResult: { outcome: 'FAIL' } })
    .may_enter_normal_mode, false));

t('連要做什麼都沒宣告時也不放行', () =>
  assert.equal(verifyFirstResumedAction({}).may_enter_normal_mode, false));

// ---- 專案慣例 ----
t('零依賴:recovery.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/recovery.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('火場那個比喻與它推出的結論留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/recovery.js', import.meta.url), 'utf8');
  assert.match(src, /不需要更多資訊,需要一個出口/);
});

t('每個回傳都帶版本', () => {
  assert.equal(chooseIntervention({}).version, VERSION);
  assert.equal(selectHealthyContext([]).version, VERSION);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
