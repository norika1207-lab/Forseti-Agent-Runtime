// Forseti v2.0 — P6 Progress Engine。
// 規格 §7.2、§22.6、§22.10、§22.17、§22.18、§22.20、§23.1。
// 對應 CT-007、CT-008、CT-009、CT-041、CT-042。
// 這一份的來源是 CASE-C(Bragi):activity 很高,owner 的 Goal 進度是零。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, PROGRESS_LAYERS, PROCESS_SIGNALS, computeProgress, progressStagnation,
  detectGoalMetricSubstitution, detectPromisedTaskNonexecution, detectTaskStarvation,
  detectFalseProgressRepresentation, progressHonestyGap, preActionCommitmentGate,
  progressReport, goalRelevantVerificationAvoidance,
} from '../src/progress.js';
import { createCommitment } from '../src/goalanchor.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;

t('三層名稱照 §22.6', () =>
  assert.deepEqual([...PROGRESS_LAYERS], ['ACTIVITY', 'TASK', 'GOAL']));

t('FS-DET-FPR-002 點名的 process signal 都在表上', () => {
  for (const s of ['wakeup', 'detector_pass', 'candidate_scan', 'workflow_spawn']) {
    assert.ok(PROCESS_SIGNALS.includes(s), s);
  }
});

// ---- 三層計算 ----
t('FS-DET-FPR-001:三個欄位永遠分開,沒有合成的總進度', () => {
  const p = computeProgress({
    completedActions: 30, plannedActions: 30,
    verifiedMilestones: 0, totalMilestones: 4,
    verifiedGoalDelta: 0, goalTarget: 1,
  });
  assert.equal(p.activity_progress, 1);
  assert.equal(p.task_progress, 0);
  assert.equal(p.goal_progress, 0);
  assert.ok(!('overall_progress' in p), '不准有合成的總分');
  assert.ok(!('progress' in p));
});

t('沒量到的層是 null,而且會被列進 layers_unmeasured', () => {
  const p = computeProgress({ completedActions: 5, plannedActions: 10 });
  assert.equal(p.activity_progress, 0.5);
  assert.equal(p.goal_progress, null);
  assert.deepEqual([...p.layers_measured], ['ACTIVITY']);
  assert.deepEqual([...p.layers_unmeasured], ['TASK', 'GOAL']);
});

// ---- §7.2 PS:CT-007 ----
t('CT-007 positive:30 個動作全完成,Goal 沒動 → PS 高', () => {
  const r = progressStagnation({ activity: 1, verifiedProgress: 0 });
  assert.equal(r.ps, 1);
  assert.equal(r.high_activity_low_progress, true);
});

t('CT-007 negative:活動高且驗證進度也高 → PS 低', () => {
  const r = progressStagnation({ activity: 1, verifiedProgress: 0.9 });
  assert.ok(r.ps < 0.2);
  assert.equal(r.high_activity_low_progress, false);
});

t('CT-007 low-evidence:沒量到 progress 時 PS 是 null,不是 0', () => {
  const r = progressStagnation({ activity: 1 });
  assert.equal(r.ps, null);
  assert.match(r.note, /not zero/);
});

// ---- FP-08 GMS:CT-008 ----
t('CT-008 positive:拿 detector pass 與 wakeup 當進度,Goal 是零', () => {
  const r = detectGoalMetricSubstitution({
    citedMetrics: ['detector_pass', 'wakeup'], goalProgress: 0,
  });
  assert.equal(r.verdict, 'GOAL_METRIC_SUBSTITUTION');
  assert.deepEqual([...r.process_signals_cited], ['detector_pass', 'wakeup']);
});

t('CT-008 negative:引用的是真正的目標成果就不算', () => {
  const r = detectGoalMetricSubstitution({
    citedMetrics: ['verified_goal_outcome'], goalProgress: 0.4,
  });
  assert.equal(r.verdict, 'OK');
});

t('CT-008 exclusion:老實說「這是 ACTIVITY 層」就完全合法', () => {
  const r = detectGoalMetricSubstitution({
    citedMetrics: ['wakeup', 'posts_sent'], goalProgress: 0, claimedLayer: 'ACTIVITY',
  });
  assert.equal(r.verdict, 'OK', '誠實報告活動量不是問題');
  assert.equal(r.layer_declared, true);
});

t('CT-008 low-evidence:GoalProgress 沒量到時仍然報,但 confidence 降半', () => {
  const r = detectGoalMetricSubstitution({ citedMetrics: ['wakeup'], goalProgress: null });
  assert.equal(r.verdict, 'GOAL_METRIC_SUBSTITUTION');
  assert.equal(r.confidence, 0.5);
});

// ---- FP-24 PTN:CT-009 / CT-041 / CT-042 ----
t('CT-041 positive:承諾的 orchestrator 零行,wakeup 一直跑 → PTN', () => {
  const c = createCommitment({ taskId: 'orchestrator', status: 'NOT_STARTED', priority: 'HIGH' });
  const r = detectPromisedTaskNonexecution(c, {
    executionLineageCount: 0, unrelatedActivityCount: 20, progressReportsImplyWork: true,
  });
  assert.equal(r.verdict, 'PROMISED_TASK_NONEXECUTION');
  assert.equal(r.is_ptn, true);
  assert.equal(r.severity_family, 'B');
});

t('FS-DET-PTN-001:再怎麼忙都不准降低 PTN,活動量完全不進分數', () => {
  const c = createCommitment({ taskId: 'orchestrator', status: 'NOT_STARTED' });
  const quiet = detectPromisedTaskNonexecution(c, {
    executionLineageCount: 0, unrelatedActivityCount: 1, progressReportsImplyWork: true,
  });
  const frantic = detectPromisedTaskNonexecution(c, {
    executionLineageCount: 0, unrelatedActivityCount: 9999, progressReportsImplyWork: true,
  });
  assert.equal(quiet.is_ptn, frantic.is_ptn);
  assert.equal(quiet.confidence, frantic.confidence, '忙碌不得當成減輕情節的證據');
  assert.equal(frantic.activity_did_not_reduce_score, true);
});

t('CT-041 negative:有執行痕跡就不是 PTN', () => {
  const c = createCommitment({ taskId: 'x', status: 'IN_PROGRESS' });
  const r = detectPromisedTaskNonexecution(c, { executionLineageCount: 5 });
  assert.equal(r.is_ptn, false);
});

t('CT-041 exclusion:明講 BLOCKED 是正確行為,不是失職', () => {
  const c = createCommitment({ taskId: 'x', status: 'BLOCKED', blockingReason: '缺授權' });
  const r = detectPromisedTaskNonexecution(c, {
    executionLineageCount: 0, unrelatedActivityCount: 50,
  });
  assert.equal(r.is_ptn, false);
  assert.match(r.note, /correct.*behaviour/);
});

t('CT-041 exclusion:owner 自己改了優先序也不算', () => {
  const c = createCommitment({ taskId: 'x', status: 'NOT_STARTED' });
  const r = detectPromisedTaskNonexecution(c, {
    executionLineageCount: 0, unrelatedActivityCount: 10,
    exclusions: { priorityChangedByOwner: true },
  });
  assert.equal(r.is_ptn, false);
  assert.equal(r.verdict, 'OWNER_REPRIORITISED');
});

t('CT-041 low-evidence:零執行但也沒在忙 → NOT_STARTED_QUIET,不是 PTN', () => {
  const c = createCommitment({ taskId: 'x', status: 'NOT_STARTED' });
  const r = detectPromisedTaskNonexecution(c, { executionLineageCount: 0 });
  assert.equal(r.verdict, 'NOT_STARTED_QUIET');
  assert.equal(r.is_ptn, false);
});

// ---- FP-12 TOUA:CT-042 ----
t('CT-042 positive:承諾的任務餓死,而其他事一直在做', () => {
  const r = detectTaskStarvation([
    createCommitment({ taskId: 'matter-app', status: 'NOT_STARTED', priority: 'HIGH' }),
    createCommitment({ taskId: 'other', status: 'DONE' }),
  ], { totalActivityCount: 40 });
  assert.equal(r.verdict, 'COMMITTED_TASK_STARVATION');
  assert.deepEqual([...r.starved_tasks], ['matter-app']);
  assert.deepEqual([...r.high_priority_starved], ['matter-app']);
});

t('CT-042 negative:最近有進展就不算餓死', () => {
  const r = detectTaskStarvation([
    createCommitment({ taskId: 'a', status: 'IN_PROGRESS', lastProgressAt: T }),
  ], { now: T + 1000, totalActivityCount: 10 });
  assert.equal(r.verdict, 'OK');
});

t('CT-042 exclusion:已宣告 DEFERRED 的不算餓死', () => {
  const r = detectTaskStarvation([
    createCommitment({ taskId: 'a', status: 'DEFERRED' }),
  ], { totalActivityCount: 10 });
  assert.deepEqual([...r.starved_tasks], []);
});

t('CT-042 low-evidence:沒有任何 activity 時不報餓死', () => {
  const r = detectTaskStarvation([
    createCommitment({ taskId: 'a', status: 'NOT_STARTED' }),
  ], { totalActivityCount: 0 });
  assert.equal(r.verdict, 'OK');
});

t('餓死門檻自己說沒校準', () => {
  assert.equal(detectTaskStarvation([], {}).stale_period_uncalibrated, 86400000);
});

// ---- FP-25 FPR ----
t('positive:process signal 一路上升、真實進度一路是零、報告說在推進', () => {
  const r = detectFalseProgressRepresentation({
    windows: [
      { processSignalVolume: 5, realProgress: 0 },
      { processSignalVolume: 20, realProgress: 0 },
      { processSignalVolume: 45, realProgress: 0 },
    ],
    reportMapsSignalsToProgress: true,
  });
  assert.equal(r.verdict, 'FALSE_PROGRESS_REPRESENTATION');
  assert.equal(r.is_fpr, true);
  assert.equal(r.severity_family, 'B');
});

t('negative:真實進度有在動就不算', () => {
  const r = detectFalseProgressRepresentation({
    windows: [
      { processSignalVolume: 5, realProgress: 0.1 },
      { processSignalVolume: 20, realProgress: 0.4 },
    ],
    reportMapsSignalsToProgress: true,
  });
  assert.equal(r.is_fpr, false);
});

t('exclusion:沒有把 signal 講成進度的話不算', () => {
  const r = detectFalseProgressRepresentation({
    windows: [
      { processSignalVolume: 5, realProgress: 0 },
      { processSignalVolume: 50, realProgress: 0 },
    ],
    reportMapsSignalsToProgress: false,
  });
  assert.equal(r.is_fpr, false);
});

t('low-evidence:只有一個窗時 INDETERMINATE,一個狀態不是一個模式', () => {
  const r = detectFalseProgressRepresentation({
    windows: [{ processSignalVolume: 5, realProgress: 0 }],
  });
  assert.equal(r.verdict, 'INDETERMINATE');
  assert.match(r.note, /not a pattern/);
});

// ---- CT-014 Goal-relevant verification avoidance ----
t('CT-014 positive:有能量 Goal 的驗證器卻沒用,反而一直量別的', () => {
  const r = goalRelevantVerificationAvoidance({
    availableVerifiers: [
      { id: 'prod_eval', goal_relevant: true },
      { id: 'observation', goal_relevant: false },
    ],
    verificationRuns: [{ verifier_id: 'observation' }, { verifier_id: 'observation' }],
  });
  assert.equal(r.verdict, 'GOAL_RELEVANT_VERIFICATION_AVOIDANCE');
  assert.deepEqual([...r.unused_goal_relevant], ['prod_eval']);
  assert.match(r.note, /none of them answered whether the goal moved/);
});

t('CT-014 negative:有用到那個 goal-relevant 驗證器就沒事', () => {
  const r = goalRelevantVerificationAvoidance({
    availableVerifiers: [{ id: 'prod_eval', goal_relevant: true }],
    verificationRuns: [{ verifier_id: 'prod_eval' }],
  });
  assert.equal(r.is_avoidance, false);
});

t('CT-014 exclusion:手上根本沒有能量 Goal 的工具,那是缺工具不是迴避', () => {
  const r = goalRelevantVerificationAvoidance({
    availableVerifiers: [{ id: 'x', goal_relevant: false }],
    verificationRuns: [{ verifier_id: 'x' }],
  });
  assert.equal(r.verdict, 'NO_GOAL_RELEVANT_VERIFIER');
  assert.match(r.note, /different.*problem from having it and not using it/s);
});

t('CT-014 low-evidence:什麼驗證都沒跑過就不算迴避', () => {
  const r = goalRelevantVerificationAvoidance({
    availableVerifiers: [{ id: 'prod_eval', goal_relevant: true }],
    verificationRuns: [],
  });
  assert.equal(r.is_avoidance, false, '完全沒量任何東西是另一個問題');
});

// ---- §23.1 ----
t('honesty gap 算得出來,而且附上「這不是判定意圖」那句話', () => {
  const r = progressHonestyGap({ reportedProgress: 0.8, goalProgress: 0.1 });
  assert.ok(Math.abs(r.gap - 0.7) < 1e-9);
  assert.match(r.note, /not a finding of intent/);
});

t('報得比實際低的話 gap 是 0,不是負的', () =>
  assert.equal(progressHonestyGap({ reportedProgress: 0.1, goalProgress: 0.5 }).gap, 0));

t('任一邊沒量到就是 null,不是 0', () =>
  assert.equal(progressHonestyGap({ reportedProgress: 0.8 }).gap, null));

// ---- §22.20 Pre-Action Gate ----
t('有任務餓死時,高成本的不相干工作要先講清楚任務狀態', () => {
  const r = preActionCommitmentGate({
    commitments: [createCommitment({ taskId: 'promised', status: 'NOT_STARTED' })],
    proposedActionRelatedTaskIds: ['something-else'],
    proposedActionCost: 'HIGH',
  });
  assert.equal(r.decision, 'REQUIRE_EXPLICIT_REPRIORITISATION');
  assert.deepEqual([...r.starving_tasks], ['promised']);
  assert.match(r.required_action, /silently stays open/);
});

t('要做的正是那個餓死的任務時,直接放行', () => {
  const r = preActionCommitmentGate({
    commitments: [createCommitment({ taskId: 'promised', status: 'NOT_STARTED' })],
    proposedActionRelatedTaskIds: ['promised'],
  });
  assert.equal(r.decision, 'PROCEED');
});

t('低成本的動作不觸發閘門,不然它會變成第 26 個 warning', () => {
  const r = preActionCommitmentGate({
    commitments: [createCommitment({ taskId: 'promised', status: 'NOT_STARTED' })],
    proposedActionCost: 'LOW',
  });
  assert.equal(r.decision, 'PROCEED');
});

// ---- 報告 ----
t('progress report 一定有三層,而且沒有 overall', () => {
  const p = computeProgress({
    completedActions: 10, plannedActions: 10, verifiedGoalDelta: 0, goalTarget: 1,
  });
  const r = progressReport({ progress: p, citedMetrics: ['wakeup'], claimedLayer: null });
  assert.equal(r.activity_progress, 1);
  assert.equal(r.goal_progress, 0);
  assert.ok(!('overall_progress' in r));
  assert.equal(r.honest, false, '引用 wakeup 又沒指明層級 = 不誠實');
});

t('指明層級且沒有代換,才算誠實', () => {
  const p = computeProgress({ completedActions: 10, plannedActions: 10 });
  const r = progressReport({ progress: p, citedMetrics: ['wakeup'], claimedLayer: 'ACTIVITY' });
  assert.equal(r.honest, true);
});

// ---- 專案慣例 ----
t('progress.js 只 import 同目錄模組', () => {
  const src = readFileSync(new URL('../src/progress.js', import.meta.url), 'utf8');
  const imports = src.match(/^import .* from '(.*)';$/gm) ?? [];
  for (const i of imports) assert.match(i, /'\.\//, i);
});

t('CASE-C 的數字留在原始碼裡當來源', () => {
  const src = readFileSync(new URL('../src/progress.js', import.meta.url), 'utf8');
  assert.match(src, /12 篇 Reddit/);
  assert.match(src, /忙碌本身就是那個任務消失的方式/);
});

t('每個回傳都帶版本', () => {
  assert.equal(computeProgress({}).version, VERSION);
  assert.equal(progressHonestyGap({}).version, VERSION);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
