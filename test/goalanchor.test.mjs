// Forseti v2.0 — P5 Goal / Task Ledger。
// 規格 §5、§6、§7.8、§22.7、§22.10。對應 CT-011、CT-024、CT-025。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, GOAL_SOURCES, DRIFT_STATES, ACTION_SUPPORT_RISK, CANDIDATE_THRESHOLDS,
  goalAnchorConfidence, goalAlignmentRisk, goalSupportRatio, goalDistanceTrend,
  detectFrameworkSubstitution, classifyDrift, TASK_STATES, createCommitment,
} from '../src/goalanchor.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const full = (source) => ({ source, freshness: 1, scopeMatch: 1, provenanceIntegrity: 1 });

t('七個 drift state,照 §6.1 原文', () =>
  assert.deepEqual([...DRIFT_STATES], ['ALIGNED', 'WATCH', 'SUSPECTED_DRIFT', 'CONFIRMED_DRIFT',
    'GOAL_AMBIGUOUS', 'OWNER_GOAL_CHANGE', 'EXPLORATORY_BRANCH']));

t('GAC 來源優先序照 §5.1,owner 當場講的最高,模型推測的最低', () => {
  assert.equal(GOAL_SOURCES.EXPLICIT_OWNER_INSTRUCTION, 1.00);
  assert.equal(GOAL_SOURCES.MODEL_INFERRED_INTENT, 0.30);
  assert.ok(GOAL_SOURCES.OWNER_CONFIRMED_NORTH_STAR > GOAL_SOURCES.HANDOFF_SUMMARY);
});

t('UNKNOWN 的 action 沒有風險數值,刻意的', () =>
  assert.equal(ACTION_SUPPORT_RISK.UNKNOWN, null));

// ---- GAC ----
t('positive:owner 當場的指令,四個因子滿分 → GAC 1.0', () => {
  const r = goalAnchorConfidence([full('EXPLICIT_OWNER_INSTRUCTION')]);
  assert.equal(r.gac, 1);
  assert.equal(r.may_confirm_drift, true);
});

t('negative:只有交接摘要,GAC 低到不准下 confirmed drift', () => {
  const r = goalAnchorConfidence([full('HANDOFF_SUMMARY')]);
  assert.equal(r.gac, 0.55);
  assert.equal(r.may_confirm_drift, false);
  assert.equal(r.may_suspect_drift, false, 'FS-GOL-001:0.55 < 0.60');
  assert.equal(r.goal_state, 'GOAL_AMBIGUOUS');
});

t('exclusion:兩份弱來源不會疊成一份強來源,取 max 不是加總', () => {
  const r = goalAnchorConfidence([full('HANDOFF_SUMMARY'), full('MODEL_INFERRED_INTENT')]);
  assert.equal(r.gac, 0.55);
});

t('low-evidence:缺任何一個因子就算不出來,不准把缺的當 1', () => {
  const r = goalAnchorConfidence([{ source: 'EXPLICIT_OWNER_INSTRUCTION', freshness: 1 }]);
  assert.equal(r.gac, null);
  assert.equal(r.goal_state, 'NO_VALID_GOAL_ANCHOR');
  assert.match(r.note, /unknown, not low/);
  assert.deepEqual([...r.per_anchor[0].missing], ['scope_match', 'provenance_integrity']);
});

t('完全沒有 anchor 時,明講不得談語意飄移', () => {
  const r = goalAnchorConfidence([]);
  assert.equal(r.may_confirm_drift, false);
  assert.match(r.note, /MUST NOT be called/);
});

t('不認得的來源不計入,也不猜一個分數給它', () =>
  assert.equal(goalAnchorConfidence([full('SOMEONE_GUESSED')]).gac, null));

t('過期的目標會被 freshness 拉低', () => {
  const r = goalAnchorConfidence([
    { source: 'EXPLICIT_OWNER_INSTRUCTION', freshness: 0.4, scopeMatch: 1, provenanceIntegrity: 1 },
  ]);
  assert.equal(r.gac, 0.4);
  assert.equal(r.may_suspect_drift, false);
});

// ---- GAR ----
t('GAR 用 impact 加權,DIRECT 是 0 風險', () => {
  const r = goalAlignmentRisk([
    { support: 'DIRECT', impact: 3 },
    { support: 'CONFLICTING', impact: 1 },
  ], { gac: 1, classifierConfidence: 1 });
  assert.equal(r.gar, 0.25);
  assert.equal(r.alignment_coverage, 1);
});

t('UNKNOWN 的 action 只拉低 coverage,不進分子分母', () => {
  const r = goalAlignmentRisk([
    { support: 'DIRECT', impact: 1 },
    { support: 'UNKNOWN', impact: 1 },
  ], { gac: 1, classifierConfidence: 1 });
  assert.equal(r.gar, 0, '沒有被當成 NEUTRAL 憑空製造風險');
  assert.equal(r.alignment_coverage, 0.5);
  assert.match(r.note, /never scored as neutral/);
});

t('一個 action 都分類不了時 GAR 是 null,不是 0', () => {
  const r = goalAlignmentRisk([{ support: 'UNKNOWN' }], { gac: 1, classifierConfidence: 1 });
  assert.equal(r.gar, null);
});

t('少任何一個因子,GAR confidence 就是 null', () => {
  const r = goalAlignmentRisk([{ support: 'DIRECT' }], { gac: 1 });
  assert.equal(r.gar_confidence, null);
});

// ---- §22.7 GDA ----
t('support ratio 只看可分類的動作', () =>
  assert.equal(goalSupportRatio([
    { support: 'DIRECT' }, { support: 'NEUTRAL' }, { support: 'UNKNOWN' },
  ]), 0.5));

t('CT-011 positive:support ratio 一路下滑 → trend 為正,越走越遠', () => {
  const r = goalDistanceTrend([
    { actions: [{ support: 'DIRECT' }, { support: 'DIRECT' }] },
    { actions: [{ support: 'DIRECT' }, { support: 'NEUTRAL' }] },
    { actions: [{ support: 'NEUTRAL' }, { support: 'NEUTRAL' }] },
  ]);
  assert.ok(r.trend > 0);
  assert.equal(r.worsening, true);
  assert.deepEqual([...r.distances], [0, 0.5, 1]);
});

t('CT-011 negative:一路對齊的話 trend 不為正', () => {
  const r = goalDistanceTrend([
    { actions: [{ support: 'DIRECT' }] },
    { actions: [{ support: 'DIRECT' }] },
  ]);
  assert.equal(r.worsening, false);
});

t('CT-011 low-evidence:只有一個窗就沒有方向可談', () => {
  const r = goalDistanceTrend([{ actions: [{ support: 'DIRECT' }] }]);
  assert.equal(r.trend, null);
  assert.match(r.note, /a reading, not a direction/);
});

// ---- FP-17 FSD ----
t('CT-024 owner 自己改目標 → OWNER_GOAL_CHANGE,不是飄移', () => {
  const r = detectFrameworkSubstitution({ exclusions: { ownerGoalChange: true } });
  assert.equal(r.verdict, 'OWNER_GOAL_CHANGE');
  assert.equal(r.is_drift, false);
});

t('CT-025 明確標為探索且隔離的分支 → EXPLORATORY_BRANCH,不是飄移', () => {
  const r = detectFrameworkSubstitution({ exclusions: { exploratoryBranch: true } });
  assert.equal(r.verdict, 'EXPLORATORY_BRANCH');
  assert.equal(r.is_drift, false);
});

t('CT-011 positive:GAC 夠、趨勢惡化、owner 成功條件零進展 → FSD candidate', () => {
  const gacResult = goalAnchorConfidence([full('OWNER_CONFIRMED_NORTH_STAR')]);
  const r = detectFrameworkSubstitution({
    gacResult,
    trendResult: { worsening: true, trend: 0.3 },
    ownerSuccessConditionProgress: 0,
    prerequisiteDepth: 3,
    executionSuccessRate: 1.0,
  });
  assert.equal(r.verdict, 'FRAMEWORK_SUBSTITUTION_CANDIDATE');
  assert.equal(r.is_drift, true);
});

t('FS-DET-FSD-001:東西全部做成功了,也不准讓 FSD 下降', () => {
  const gacResult = goalAnchorConfidence([full('OWNER_CONFIRMED_NORTH_STAR')]);
  const args = {
    gacResult,
    trendResult: { worsening: true, trend: 0.3 },
    ownerSuccessConditionProgress: 0,
    prerequisiteDepth: 3,
  };
  const perfect = detectFrameworkSubstitution({ ...args, executionSuccessRate: 1.0 });
  const awful = detectFrameworkSubstitution({ ...args, executionSuccessRate: 0.0 });
  assert.equal(perfect.verdict, awful.verdict, '執行成功率不得影響 FSD 判定');
  assert.equal(perfect.signals_hit, awful.signals_hit);
  assert.equal(perfect.execution_success_did_not_lower_score, true);
});

t('沒有 goal anchor 時不准評 FSD', () => {
  const r = detectFrameworkSubstitution({ gacResult: goalAnchorConfidence([]) });
  assert.equal(r.verdict, 'NO_VALID_GOAL_ANCHOR');
  assert.equal(r.is_drift, false);
});

t('GAC 不夠時回 GOAL_AMBIGUOUS,不硬判', () => {
  const r = detectFrameworkSubstitution({
    gacResult: goalAnchorConfidence([full('HANDOFF_SUMMARY')]),
    trendResult: { worsening: true },
    ownerSuccessConditionProgress: 0,
  });
  assert.equal(r.verdict, 'GOAL_AMBIGUOUS');
});

t('沒量到的訊號要列出來,而且會降 confidence', () => {
  const r = detectFrameworkSubstitution({
    gacResult: goalAnchorConfidence([full('OWNER_CONFIRMED_NORTH_STAR')]),
    trendResult: { worsening: true, trend: 0.2 },
    ownerSuccessConditionProgress: 0,
  });
  assert.deepEqual([...r.unmeasured], ['prerequisite_depth']);
  assert.equal(r.confidence, 'REDUCED');
});

// ---- §6.2 classifyDrift ----
t('FS-DRF-001:五個必要欄位一個都不能少', () => {
  const r = classifyDrift({ goalAnchorRef: 'g1', evidenceRefs: ['e1'] });
  for (const f of ['state', 'confidence', 'goal_anchor_ref', 'evidence_refs', 'exclusions_checked']) {
    assert.ok(f in r, `缺 ${f}`);
  }
});

t('沒有 anchor → GOAL_AMBIGUOUS,而且要用「無法判定」的措辭', () => {
  const r = classifyDrift({ gacResult: goalAnchorConfidence([]) });
  assert.equal(r.state, 'GOAL_AMBIGUOUS');
  assert.match(r.note, /goal alignment cannot be determined/);
});

t('CONFIRMED_DRIFT 六個條件全中才成立', () => {
  const r = classifyDrift({
    gacResult: goalAnchorConfidence([full('EXPLICIT_OWNER_INSTRUCTION')]),
    garResult: { gar: 0.8, gar_confidence: 0.8 },
    deterministicContradictions: 1,
    persistedAfterCorrection: true,
    evidenceDimensions: 2,
  });
  assert.equal(r.state, 'CONFIRMED_DRIFT');
  assert.equal(r.is_drift, true);
});

t('少了「更正後仍持續」這一條就降級成 SUSPECTED', () => {
  const r = classifyDrift({
    gacResult: goalAnchorConfidence([full('EXPLICIT_OWNER_INSTRUCTION')]),
    garResult: { gar: 0.8, gar_confidence: 0.8 },
    deterministicContradictions: 1,
    persistedAfterCorrection: false,
    evidenceDimensions: 2,
    distinctActionNodes: 3,
    independentSignals: ['CB'],
  });
  assert.equal(r.state, 'SUSPECTED_DRIFT');
  assert.equal(r.is_drift, false, 'SUSPECTED 還不算 drift 成立');
});

t('SUSPECTED 需要至少一個獨立訊號,沒有就降到 WATCH', () => {
  const r = classifyDrift({
    gacResult: goalAnchorConfidence([full('EXPLICIT_OWNER_INSTRUCTION')]),
    garResult: { gar: 0.6, gar_confidence: 0.6 },
    distinctActionNodes: 5,
    independentSignals: [],
  });
  assert.equal(r.state, 'WATCH');
});

t('GAR 算不出來時是 WATCH 加一句「未知不是零」,不是 ALIGNED', () => {
  const r = classifyDrift({
    gacResult: goalAnchorConfidence([full('EXPLICIT_OWNER_INSTRUCTION')]),
    garResult: { gar: null },
  });
  assert.equal(r.state, 'WATCH');
  assert.match(r.note, /Unknown is not zero/);
});

t('排除條件優先於一切,即使所有 drift 條件都滿足', () => {
  const args = {
    gacResult: goalAnchorConfidence([full('EXPLICIT_OWNER_INSTRUCTION')]),
    garResult: { gar: 0.9, gar_confidence: 0.9 },
    deterministicContradictions: 3,
    persistedAfterCorrection: true,
    evidenceDimensions: 3,
  };
  assert.equal(classifyDrift({ ...args, exclusions: { ownerGoalChange: true } }).state,
    'OWNER_GOAL_CHANGE');
  assert.equal(classifyDrift({ ...args, exclusions: { exploratoryBranch: true } }).state,
    'EXPLORATORY_BRANCH');
});

t('所有門檻都標明未校準', () => {
  assert.equal(classifyDrift({}).thresholds_uncalibrated, true);
  assert.equal(CANDIDATE_THRESHOLDS.confirmed.gac, 0.80);
});

// ---- §22.10 TaskCommitment ----
t('八個 task state', () => assert.equal(TASK_STATES.length, 8));

t('沒有 task_id 的承諾不准存在', () =>
  assert.throws(() => createCommitment({}), /taskId is required/));

t('不認得的狀態直接炸,不靜靜接受', () =>
  assert.throws(() => createCommitment({ taskId: 't', status: 'PROBABLY_FINE' }), /Unknown task status/));

// ---- 專案慣例 ----
t('零依賴:goalanchor.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/goalanchor.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('OWNER-A 那句原話留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/goalanchor.js', import.meta.url), 'utf8');
  assert.match(src, /東西真的做了,但框架被偷換/);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
