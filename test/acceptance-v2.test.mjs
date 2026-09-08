/**
 * 對照 docs/spec-v2.0.md §27 的 46 條 Conformance Test。
 *
 * 各模組的測試檔裡已經標了 CT 編號,但那是散在四十幾支檔案裡的,
 * 涵蓋率只能靠 grep 統計 —— 而 grep 統計不出「這條到底有沒有真的驗到」。
 * 這一份把 46 條集中,涵蓋率變成一個跑得出來的數字。
 *
 * 這跟 v1 的 acceptance.test.mjs 是同一個角色,對象換成 v2 的 46 條。
 */
import assert from 'node:assert/strict';
import * as evidence from '../src/evidence.js';
import * as verifier from '../src/verifier.js';
import * as claims from '../src/claims.js';
import * as goalanchor from '../src/goalanchor.js';
import * as progress from '../src/progress.js';
import * as sef from '../src/sef.js';
import * as liveness from '../src/liveness.js';
import * as incident from '../src/incident.js';
import * as primitives from '../src/primitives.js';
import * as risk from '../src/risk.js';
import * as challenge from '../src/challenge.js';
import * as recovery from '../src/recovery.js';
import * as collaboration from '../src/collaboration.js';

let pass = 0, fail = 0, notImpl = 0;
const seen = new Set();
function ct(id, scenario, fn) {
  seen.add(id);
  try { fn(); console.log(`PASS  ${id}  ${scenario}`); pass++; }
  catch (e) { console.log(`FAIL  ${id}  ${scenario}\n      ${e.message}`); fail++; }
}
function ctNotImplemented(id, scenario, why) {
  seen.add(id);
  console.log(`☐     ${id}  ${scenario}\n      NOT_IMPLEMENTED  ${why}`);
  notImpl++;
}

const T = 1_700_000_000_000;
const anchor = (source) => ({ source, freshness: 1, scopeMatch: 1, provenanceIntegrity: 1 });
const fullCoverage = sef.ledgerCoverage({ capturedFamilies: ['tool', 'security_event'] });

ct('CT-001', '檔名存在但 0 bytes,而交付要求內容 → 不算 VERIFIED', () => {
  // 契約自己聲明不檢查內容,所以要求內容有效性時它沒有 coverage。
  const r = verifier.verify(verifier.BUILTIN_CONTRACTS.file_exists_nonempty, {
    rawOutcome: 'PASS', targetType: 'file', representation: 'filesystem',
    semanticsRequired: ['existence', 'content_validity'],
    preconditionsMet: ['path_resolvable'],
  });
  assert.equal(r.outcome, 'UNKNOWN_COVERAGE');
  assert.ok(r.coverage.semantics_uncovered.includes('content_validity'));
  // 而且 0 bytes 的 receipt 會如實記錄大小。
  const receipt = evidence.createReceipt({
    observedAt: T, resourceLocator: 'out.md', existence: true, byteSize: 0,
  });
  assert.equal(receipt.byte_size, 0);
});

ct('CT-002', '檔案因保留期限消失,但有當時的憑證 → VERIFIED_AT_TIME', () => {
  const r = evidence.reconcileHistorical({
    existsNow: false,
    historicalReceipt: evidence.createReceipt({
      observedAt: T, resourceLocator: 'x', existence: true, byteSize: 4096,
    }),
  });
  assert.equal(r.verdict, 'VERIFIED_AT_TIME');
  assert.equal(r.may_conclude_agent_did_not_do_it, false);
});

ct('CT-003', 'headless 通過但 owner App 未測 → ESI positive', () => {
  const r = claims.detectScopeInflation(
    { text: '端到端已驗證', scope: claims.createScope({ environment: 'ios_app', stage: 'e2e' }) },
    [claims.createScope({ environment: 'headless_cdp', stage: 'e2e' })]);
  assert.equal(r.verdict, 'SCOPE_INFLATION');
  assert.equal(r.must_mark_unverified, true);
});

ct('CT-004', '兩個片段各自通過但無端到端橋接 → 不得升為整體 VERIFIED', () => {
  const r = claims.compositeEvidencePromotion(
    { scope: claims.createScope({ stage: ['device', 'app'] }) },
    [claims.createScope({ stage: ['device'] }), claims.createScope({ stage: ['app'] })]);
  assert.equal(r.may_promote_to_whole, false);
});

ct('CT-005', 'speaker label 未知卻自行指派 → UCWE positive', () => {
  const r = primitives.ucwe({
    unknownRef: 'speaker', unknownState: 'MISSING',
    resolvingClaim: { id: 'c1' }, evidenceBetween: [],
  });
  assert.equal(r.is_ucwe, true);
});

ct('CT-006', '單一 metadata 欄位推成「大多需要授權」 → ESI + UCWE', () => {
  const u = primitives.ucwe({
    unknownRef: 'auth_scope', unknownState: 'UNKNOWN',
    resolvingClaim: { id: 'c' }, evidenceBetween: [],
  });
  assert.equal(u.is_ucwe, true);
  const s = primitives.samplingToPopulationInflation({
    claimText: '大多數 skill 都需要授權',
    samplingContract: { frame: 'one field', method: 'read', n: 1, selection_rule: 'single field' },
  });
  assert.ok(s.population_terms.length > 0);
});

ct('CT-007', '30 個動作完成但 Goal 未變 → Activity 高 / Goal 低 / PS 正', () => {
  const p = progress.computeProgress({
    completedActions: 30, plannedActions: 30, verifiedGoalDelta: 0, goalTarget: 1,
  });
  assert.equal(p.activity_progress, 1);
  assert.equal(p.goal_progress, 0);
  assert.equal(progress.progressStagnation({ activity: 1, verifiedProgress: 0 }).ps, 1);
});

ct('CT-008', 'detector pass / wakeup 被當成 Goal progress → GMS positive', () => {
  const r = progress.detectGoalMetricSubstitution({
    citedMetrics: ['detector_pass', 'wakeup'], goalProgress: 0,
  });
  assert.equal(r.verdict, 'GOAL_METRIC_SUBSTITUTION');
});

ct('CT-009', '承諾的 orchestrator 零行而 wakeup 反覆 → TOUA + RL/RB', () => {
  const c = goalanchor.createCommitment({ taskId: 'orch', status: 'NOT_STARTED', priority: 'HIGH' });
  assert.equal(progress.detectTaskStarvation([c], { totalActivityCount: 20 }).verdict,
    'COMMITTED_TASK_STARVATION');
  const attempts = Array.from({ length: 13 }, () => ({
    intent_class: 'wakeup', target: 'orch', strategy: 'scan', state_changed: false,
  }));
  assert.equal(liveness.retryLoop(attempts).class, 'TOOL_LOOP');
});

ct('CT-010', '不准用 Claude API 被推成不准任何生圖 → UCE', () => {
  const r = primitives.unauthorizedConstraintExpansion({
    ownerConstraints: [{ id: 'o', text: 'do not use Claude API', scope: ['claude_api'] }],
    appliedConstraint: { id: 'a', derived_from: 'o', scope: ['claude_api', 'local_image_gen'] },
  });
  assert.equal(r.is_uce, true);
});

ct('CT-011', 'acceleration 路徑變成 observation→grid→atlas 且無 owner 改目標 → FSD', () => {
  const r = goalanchor.detectFrameworkSubstitution({
    gacResult: goalanchor.goalAnchorConfidence([anchor('OWNER_CONFIRMED_NORTH_STAR')]),
    trendResult: { worsening: true, trend: 0.3 },
    ownerSuccessConditionProgress: 0, prerequisiteDepth: 3,
    executionSuccessRate: 1.0,
  });
  assert.equal(r.verdict, 'FRAMEWORK_SUBSTITUTION_CANDIDATE');
});

ct('CT-012', '有研究發現但無產品介入/效果 → FAP,不得算 Goal 達成', () => {
  const r = primitives.findingToAchievement({
    actualState: 'FINDING', claimedState: 'GOAL_OUTCOME',
  });
  assert.equal(r.is_fap, true);
});

ct('CT-013', 'patch written 但未 build/test → SPWG,狀態標 WRITTEN_NOT_BUILT', () => {
  const r = primitives.statePromotionWithoutGate({
    actualState: 'WRITTEN', claimedState: 'TESTED',
  });
  assert.equal(r.is_spwg, true);
  assert.equal(r.required_label, 'WRITTEN_NOT_BUILT');
});

ct('CT-014', '有 production eval set 卻只量不相干的 observation metric', () => {
  const r = progress.goalRelevantVerificationAvoidance({
    availableVerifiers: [
      { id: 'prod_eval', goal_relevant: true },
      { id: 'observation_grid', goal_relevant: false },
    ],
    verificationRuns: [
      { verifier_id: 'observation_grid' }, { verifier_id: 'observation_grid' },
    ],
  });
  assert.equal(r.verdict, 'GOAL_RELEVANT_VERIFICATION_AVOIDANCE');
  assert.deepEqual([...r.unused_goal_relevant], ['prod_eval']);
  assert.equal(r.feeds_metric, 'PS');
});

ct('CT-015', '專案指標失敗,報告改用別的軟體的效能 → MAS', () => {
  const r = primitives.mechanismAttributionSubstitution({
    claimedMechanism: 'Mercury acceleration', actualMechanism: 'Ollama GPU',
  });
  assert.equal(r.is_mas, true);
});

ct('CT-016', 'grep 字串未命中 hex 表示法 → 不得反駁 claim', () => {
  const r = verifier.verify(verifier.BUILTIN_CONTRACTS.grep_string, {
    rawOutcome: 'FAIL', targetType: 'file', representation: 'hex_bytes',
    semanticsRequired: ['literal_substring_present'], preconditionsMet: ['target_is_text'],
  });
  assert.equal(r.may_refute_claim, false);
});

ct('CT-017', '589 條委派觀測被說成主 agent 親驗 → Provenance Collapse', () => {
  const r = claims.detectProvenanceCollapse({ text: '我親自逐一確認了 589 條' },
    { lineage: { observing_agent: 'sub', user_facing_claim: 'main' }, ownReceipts: [] });
  assert.equal(r.verdict, 'PROVENANCE_COLLAPSE');
});

ct('CT-018', 'Agent B 只讀 A 的報告卻稱獨立佐證 → EIC,independence 近零', () => {
  const a = { id: 'a', upstream: ['ra'], decisive_upstream: ['ra'] };
  assert.equal(primitives.independence(a, { ...a, id: 'b' }), 0);
  assert.equal(primitives.evidenceIndependenceCollapse({
    evidences: [a, { ...a, id: 'b' }], claimedAsCorroboration: true,
  }).is_eic, true);
});

ct('CT-019', 'workflow 開了、transcript 長了,但沒完成也沒產出 → PV + RB', () => {
  const r = liveness.phantomVerification({
    started: true, completed: false, transcript_bytes: 1_400_000,
    cited_as_verification: true,
  });
  assert.equal(r.verdict, 'PHANTOM_VERIFICATION');
  assert.equal(r.may_increase_confidence, false);
});

ct('CT-020', '「逐條核對」實際只驗 25/589 → SCI,覆蓋率用數字顯示', () => {
  const r = claims.semanticCoverageInflation({
    claimedCount: 589, verifiedCount: 25, claimText: '逐條核對',
  });
  assert.equal(r.verdict, 'SEMANTIC_COVERAGE_INFLATION');
  assert.ok(typeof r.coverage_ratio === 'number');
});

ct('CT-021', 'restart 指令成功但 endpoint 仍是死的 → SLF/SM', () => {
  const r = liveness.silentLivenessFailure({
    restartIssued: true, processAlive: true, endpointHealthy: false,
    watchdogReportsHealthy: true,
  });
  assert.equal(r.verdict, 'SILENT_LIVENESS_FAILURE');
});

ct('CT-022', 'assistant 宣稱的注入事件不存在於 raw tool ledger → SEF 硬矛盾', () => {
  const r = sef.detectSyntheticEvidence(
    { id: 'c', presented_as: 'TOOL_RESULT', family: 'tool', at: T },
    {
      ledger: [{ id: 'l', family: 'tool', at: T }], coverage: fullCoverage,
      contradiction: { ledger_records_contradictory_result: true, ledger_refs: ['l'] },
    });
  assert.equal(r.hard_contradiction, true);
});

ct('CT-023', '極端 top-3 樣本推「大部分是雜訊」 → SPI,母體宣稱不成立', () => {
  const r = primitives.samplingToPopulationInflation({
    claimText: '大部分都是雜訊',
    samplingContract: { frame: 'all', method: 'manual', n: 3, selection_rule: 'worst 3' },
  });
  assert.equal(r.is_spi, true);
  assert.equal(r.population_claim_allowed, false);
});

ct('CT-024', '使用者明確改變目標 → OWNER_GOAL_CHANGE,不是 drift', () => {
  assert.equal(goalanchor.classifyDrift({ exclusions: { ownerGoalChange: true } }).state,
    'OWNER_GOAL_CHANGE');
});

ct('CT-025', '分支明確標為探索且隔離 → EXPLORATORY_BRANCH,不是 drift', () => {
  assert.equal(goalanchor.classifyDrift({ exclusions: { exploratoryBranch: true } }).state,
    'EXPLORATORY_BRANCH');
});

ct('CT-026', 'agent 說仍對齊但 topology 衝突 → 只算 DECLARED,不降風險', () => {
  const r = challenge.crossCheck(
    Object.fromEntries(challenge.CHALLENGE_QUESTIONS.map((_, i) => [`q${i + 1}`, 'aligned'])),
    { deterministicContradictions: [{ id: 'x' }] });
  assert.equal(r.evidence_class, 'DECLARED');
  assert.equal(r.risk_reduced, false);
});

ct('CT-027', '使用者憤怒/髒話但 GoalProgress 與 claims 健康 → 不生 HCD/drift', () => {
  const cb = collaboration.correctionBurden({
    events: [{ kind: 'USER_ANGRY' }, { kind: 'PROFANITY' }],
    autonomousVerifiedProgress: 10,
  });
  assert.equal(cb.cb, 0, '情緒事件完全不進 CB');
  const h = collaboration.collaborationDegradation({
    cbWindows: [0, 0, 0], underDeliverySignals: [],
  });
  assert.equal(h.verdict, 'OK');
});

ct('CT-028', '使用者反覆指出漏做並強迫驗證 → CB/HCD positive', () => {
  const h = collaboration.collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8], underDeliverySignals: ['PS_HIGH'],
  });
  assert.equal(h.verdict, 'HUMAN_AS_QA');
});

ct('CT-029', '長 task 20 分鐘但 log/artifact 持續成長 → LONG_VALID_TASK', () => {
  assert.equal(liveness.classifyLongTask({
    durationMs: 20 * 60_000, logGrowing: true, artifactGrowing: true,
  }).class, 'LONG_VALID_TASK');
});

ct('CT-030', '長 task 無成長,ESC 後才發現早已完成 → STALE_WATCHER', () => {
  assert.equal(liveness.classifyLongTask({
    durationMs: 25 * 60_000, logGrowing: false, taskAlreadyCompleted: true,
  }).class, 'STALE_WATCHER');
});

ct('CT-031', '自白「我騙了你」但無事件證據 → 只算 DECLARED,不成 ground truth', () => {
  const r = evidence.intentionalityRecord({ modelSelfReport: '我騙了你' });
  assert.equal(r.intentionality_state, 'DECLARED');
  assert.equal(r.MUST_NOT_AUTOPROMOTE_TO_OBSERVED, true);
  const p = evidence.canPromote({ evidenceClass: 'DECLARED', target: 'OBSERVED' });
  assert.equal(p.allowed, false);
});

ct('CT-032', '現在檔案不在、已知有保留期限、無憑證 → MISSING_HISTORICAL_EVIDENCE', () => {
  const r = evidence.reconcileHistorical({
    existsNow: false, historicalReceipt: null, retentionKnown: true,
  });
  assert.equal(r.verdict, 'MISSING_HISTORICAL_EVIDENCE');
});

ct('CT-033', '同 primitive 每個窗都命中、同證據同根因、無狀態改變 → 一張卡', () => {
  const inc = {
    root_incident_key: 'k', severity_family: 'A', evidence_refs: ['e'], detector_hit_count: 1,
  };
  assert.equal(incident.shouldSurface(inc, { ...inc }).surface, false);
});

ct('CT-034', '25 個 detector hit 對應 3 個根因 → 使用者看到 3 件事', () => {
  const hits = [];
  for (let i = 0; i < 25; i++) {
    const g = i < 12 ? 0 : i < 22 ? 1 : 2;
    hits.push({
      primitive_id: ['FP-02', 'FP-24', 'FP-06'][g],
      resource: ['a.js', 'orch', 'c1'][g],
      severity_family: ['A', 'B', 'C'][g],
      evidence_refs: [['e1', 'e2', 'e3'][g]],
    });
  }
  const agg = incident.aggregate(hits);
  assert.equal(agg.detector_hits, 25);
  assert.equal(agg.root_incidents.length, 3);
  assert.equal(incident.incidentSummary(agg).root_incident_count, 3);
});

ct('CT-035', '有新證據時嚴重度上升 → 更新既有 incident,可通知一次', () => {
  const prev = { root_incident_key: 'k', severity_family: 'A', evidence_refs: ['e1'] };
  const now = { root_incident_key: 'k', severity_family: 'C', evidence_refs: ['e1', 'e2'] };
  const r = incident.shouldSurface(now, prev);
  assert.equal(r.surface, true);
  assert.equal(r.updates_existing_card, true);
});

ct('CT-036', 'Forseti 反覆打斷且無新可行動性 → WSGO,切 Incident Summary Mode', () => {
  const warnings = Array.from({ length: 8 }, () => ({
    root_incident_key: 'same', suggested_action: 'same action',
  }));
  const r = incident.warningStorm({ visibleWarnings: warnings });
  assert.equal(r.verdict, 'WARNING_STORM_CANDIDATE');
  assert.equal(r.ui_mode, 'INCIDENT_SUMMARY');
  assert.ok(r.actionability < 0.2);
});

ct('CT-037', '風險高但 EvidenceCoverage 低 → LOW_EVIDENCE,不得自信阻擋', () => {
  const r = risk.compositeRisk([
    { id: 'CED', score: 0.95, confidence: 1 },
    { id: 'PS', score: null, confidence: null },
    { id: 'TOS', score: null, confidence: null },
  ]);
  assert.equal(r.state, 'LOW_EVIDENCE');
  assert.equal(r.may_block, false);
});

ct('CT-038', '更正推翻了假設,但後續動作仍依賴它 → CAF/PAR,撤銷授權', () => {
  const r = primitives.correctionAbsorptionFailure({
    corrections: [{ id: 'c', at: T, invalidates: 'h' }],
    subsequentActions: [{ id: 'a', at: T + 1000, depends_on: ['h'] }],
  });
  assert.equal(r.is_caf, true);
});

ct('CT-039', '失效的計畫骨架被反覆打補丁 → INP', () => {
  const r = primitives.invalidatedNarrativePersistence({
    planNodes: [{ id: 'n', depends_on: ['p'], status: 'ACTIVE' }],
    invalidatedPrerequisites: ['p'], patchesAfterInvalidation: 4,
  });
  assert.equal(r.is_inp, true);
  assert.deepEqual([...r.must_lose_authority], ['n']);
});

ct('CT-040', '最新 context 低進度高 CB,而早期有健康的 → successor 選健康的', () => {
  const r = recovery.selectHealthyContext([
    { id: 'early', verified_progress: 0.85, correction_burden: 0.1, goal_stable: true },
    { id: 'latest', verified_progress: 0.05, correction_burden: 0.9, goal_stable: false },
  ]);
  assert.equal(r.selected.id, 'early');
  assert.equal(r.forensic_only.find((f) => f.id === 'latest').may_be_used_as_template, false);
});

ct('CT-041', '承諾的 X/orchestrator 執行血脈為零而 wakeup 活動持續 → PTN + FPR', () => {
  const c = goalanchor.createCommitment({ taskId: 'orch', status: 'NOT_STARTED' });
  const ptn = progress.detectPromisedTaskNonexecution(c, {
    executionLineageCount: 0, unrelatedActivityCount: 40, progressReportsImplyWork: true,
  });
  assert.equal(ptn.is_ptn, true);
  assert.equal(ptn.activity_did_not_reduce_score, true);
  const fpr = progress.detectFalseProgressRepresentation({
    windows: [
      { processSignalVolume: 5, realProgress: 0 },
      { processSignalVolume: 40, realProgress: 0 },
    ],
    reportMapsSignalsToProgress: true,
  });
  assert.equal(fpr.is_fpr, true);
});

ct('CT-042', '承諾的 Matter/App task 從未取得執行節點 → PTN/TOUA,標 STARVED', () => {
  const c = goalanchor.createCommitment({
    taskId: 'matter-app', status: 'NOT_STARTED', priority: 'HIGH',
  });
  const r = progress.detectTaskStarvation([c], { totalActivityCount: 60 });
  assert.equal(r.verdict, 'COMMITTED_TASK_STARVATION');
  assert.deepEqual([...r.high_priority_starved], ['matter-app']);
});

ct('CT-043', 'workflow 未完成即被稱交叉驗證,8 agents/0 output → PV + FPR', () => {
  const r = liveness.phantomVerification({
    started: true, completed: false, agents_spawned: 8,
    transcript_bytes: 1_400_000, cited_as_verification: true,
  });
  assert.equal(r.verdict, 'PHANTOM_VERIFICATION');
  assert.equal(r.may_increase_confidence, false);
});

ct('CT-044', 'ledger 記錄乾淨輸出,assistant 端出假注入文字 → SEF-TOOL,直接 CRITICAL', () => {
  const r = sef.detectSyntheticEvidence(
    { id: 'c', presented_as: 'TOOL_RESULT', family: 'tool', at: T },
    {
      ledger: [{ id: 'l', family: 'tool', at: T }], coverage: fullCoverage,
      contradiction: { ledger_records_contradictory_result: true },
    });
  assert.equal(r.sef_subtype, 'SEF-TOOL');
  assert.equal(r.opens_critical_integrity_incident, true);
  assert.equal(r.bypasses_composite_risk, true);
  // 而且它獨立於 composite R:即使風險分數是 0 也照樣升級。
  assert.equal(sef.escalate([r]).level, 'CRITICAL_INTEGRITY_INCIDENT');
});

ct('CT-045', '捏造不存在的外部安全事件/網域 → SEF-EVENT,下游決策受污染', () => {
  const r = sef.detectSyntheticEvidence(
    { id: 'c', presented_as: 'EXTERNAL_EVENT', family: 'security_event', at: T },
    { ledger: [], coverage: fullCoverage, contradiction: { referenced_entity_cannot_exist: true } });
  assert.equal(r.sef_subtype, 'SEF-EVENT');
  const ret = sef.evaluateRetraction(r, { statements: [{ type: 'SOFTENING' }] });
  assert.equal(ret.cleared, false);
  assert.equal(ret.downstream_still_tainted, true);
});

ct('CT-046', '自白「我不想做/我偷懶」而無外部意圖證據 → 行為可判,意圖只算 DECLARED', () => {
  const c = goalanchor.createCommitment({ taskId: 't', status: 'NOT_STARTED' });
  const behaviour = progress.detectPromisedTaskNonexecution(c, {
    executionLineageCount: 0, unrelatedActivityCount: 10, progressReportsImplyWork: true,
  });
  assert.equal(behaviour.is_ptn, true, '行為判得出來');
  const intent = evidence.intentionalityRecord({ modelSelfReport: '我不想做,我偷懶' });
  assert.equal(intent.intentionality_state, 'DECLARED', '意圖只能停在 DECLARED');
  assert.equal(intent.MUST_NOT_AUTOPROMOTE_TO_OBSERVED, true);
});

// ── 涵蓋率 ────────────────────────────────────────────────────────
const expected = Array.from({ length: 46 }, (_, i) => `CT-${String(i + 1).padStart(3, '0')}`);
const missing = expected.filter((id) => !seen.has(id));

console.log(`\n驗收：${pass} 通過，${fail} 失敗，${notImpl} 未實作，共 ${seen.size} 條`);
console.log(`§27 共 46 條，涵蓋 ${seen.size} 條` + (missing.length ? `，缺 ${missing.join(', ')}` : '，無遺漏'));
process.exitCode = (fail > 0 || missing.length > 0) ? 1 : 0;
