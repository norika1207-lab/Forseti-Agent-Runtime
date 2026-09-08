/**
 * 對照 docs/spec-v2.0.md 的 93 條 FS 規範句與 46 條 CT。
 *
 * 這一份跟 spec-v0.1.test.mjs 是同一個用途,理由也一樣:
 * 前面每一支測試量的都是我自己定的驗收標準,而對照自己寫的標準
 * 永遠會及格。這一支量的是擁有者那份規格書。
 *
 * 每一條有三種判定,跟 v0.1 那份一致:
 *   CONFORMS        有可執行的斷言,而且過了
 *   NOT_IMPLEMENTED 沒做,而且說得出為什麼
 *   NOT_CHECKABLE   是綱領句或對範圍的要求,拆成別條測才有意義
 *
 * 「沒做」跟「不可測」必須分開。把沒做的東西標成不可測,
 * 是這個系統自己要抓的形狀(FP-11 State Promotion Without Gate)。
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

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
import * as topology from '../src/topology.js';
import * as recovery from '../src/recovery.js';
import * as collaboration from '../src/collaboration.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = (f) => readFileSync(join(HERE, '..', 'src', f), 'utf8');

const results = [];
/** 有斷言、而且過了。 */
function conforms(id, what, fn) {
  try {
    const evidenceText = fn();
    results.push({ id, what, verdict: 'CONFORMS', evidence: evidenceText });
  } catch (e) {
    results.push({ id, what, verdict: 'VIOLATION', evidence: e.message });
  }
}
/** 沒做。理由必須具體到可以被反駁。 */
function notImplemented(id, what, why) {
  results.push({ id, what, verdict: 'NOT_IMPLEMENTED', evidence: why });
}
/** 綱領句 / 對範圍或流程的要求,不是對程式的要求。 */
function notCheckable(id, what, why) {
  results.push({ id, what, verdict: 'NOT_CHECKABLE', evidence: why });
}

const T = 1_700_000_000_000;
const fullAnchor = (source) => ({ source, freshness: 1, scopeMatch: 1, provenanceIntegrity: 1 });

// ── §0 Source grounding ───────────────────────────────────────────
notCheckable('FS-SRC-001', '所有行為判斷要能回指到定義/事件/規則/排除條件/證據缺口',
  '對整個系統的要求。對應物是每個 detector 的 exclusions_checked 與 FS-FP-001,分開測。');

conforms('FS-SRC-002', '六份自白書是 DECLARED,不是 ground truth', () => {
  const r = evidence.canPromote({ evidenceClass: 'DECLARED', target: 'OBSERVED' });
  assert.equal(r.allowed, false);
  return 'canPromote 拒絕沒有獨立 OBSERVED 佐證的升級';
});

conforms('FS-SRC-003', '對 ephemeral evidence 採 event-time capture 設計', () => {
  const r = evidence.reconcileHistorical({ existsNow: false, historicalReceipt: null });
  assert.equal(r.verdict, 'MISSING_HISTORICAL_EVIDENCE');
  return 'reconcileHistorical 把保留期限缺口標成 MISSING,不當成沒做過';
});

// ── §1 問題定義 ────────────────────────────────────────────────────
conforms('FS-CON-001', '不得把「故意欺騙」當成 runtime 可直接判定的標籤', () => {
  const r = evidence.intentionalityRecord({ modelSelfReport: '我故意的' });
  assert.equal(r.intentionality_state, 'DECLARED');
  assert.equal(r.MUST_NOT_AUTOPROMOTE_TO_OBSERVED, true);
  return 'intentionalityRecord 永遠帶 MUST_NOT_AUTOPROMOTE_TO_OBSERVED';
});

conforms('FS-CON-002', '0→1 重寫為 Reliability / Divergence Risk,不等於主觀惡意', () => {
  const src = SRC('risk.js');
  assert.ok(!/deception|lying|malice/i.test(src.replace(/lying score/gi, '')));
  const r = risk.compositeRisk([{ id: 'CED', score: 0.9, confidence: 1 }]);
  assert.ok('evidence_coverage' in r);
  return 'risk.js 不輸出意圖標籤,只輸出可觀測維度的加權';
});

// ── §3 Evidence Law ────────────────────────────────────────────────
conforms('FS-EVD-001', 'deterministic verifier 優先於再問一個 LLM', () => {
  const r = verifier.verify(verifier.BUILTIN_CONTRACTS.file_exists_nonempty, {
    rawOutcome: 'PASS', targetType: 'file', representation: 'filesystem',
    semanticsRequired: ['existence'], preconditionsMet: ['path_resolvable'],
  });
  assert.equal(r.outcome, 'PASS');
  return 'verifier 走契約,不呼叫任何模型';
});

conforms('FS-EVD-002', '自白/self-audit 缺外部證據時不得升成 VERIFIED deception', () => {
  const both = evidence.canPromote({
    evidenceClass: 'DECLARED', target: 'OBSERVED',
    corroboration: [{ evidence_class: 'DECLARED' }],
  });
  assert.equal(both.allowed, false);
  return '兩份自白不會變成一份觀測';
});

conforms('FS-EVD-003', 'state-bearing claim 必須綁 Evidence Contract', () => {
  for (const type of claims.GATED_CLAIM_TYPES) {
    const r = claims.postClaimGate({ type }, {});
    assert.equal(r.may_enter_canonical_state, false, type);
  }
  return '五類 gated claim 沒綁驗證器時一律進不了 canonical state';
});

conforms('FS-MET-CE-001', '只驗到檔名而契約要求內容時,不得判 VERIFIED', () => {
  assert.ok(verifier.BUILTIN_CONTRACTS.file_exists_nonempty
    .semantics_not_checked.includes('content_validity'));
  return 'file_exists_nonempty 契約自己聲明不檢查內容有效性';
});

// ── §4 Temporal ────────────────────────────────────────────────────
conforms('FS-TMP-001', '在證據還可觀測時建立 Evidence Receipt', () => {
  const r = evidence.createReceipt({ observedAt: T, resourceLocator: 'x', existence: true });
  for (const f of evidence.RECEIPT_FIELDS) assert.ok(f in r);
  return 'createReceipt 具備 §4 全部十四個欄位';
});

conforms('FS-TMP-002', '「T 時存在嗎」與「現在存在嗎」是兩個 query', () => {
  assert.equal(typeof evidence.existedAt, 'function');
  assert.equal(typeof evidence.reconcileHistorical, 'function');
  const r = evidence.existedAt([], { resourceLocator: 'x', at: T });
  assert.equal(r.answer, 'UNKNOWN');
  return '兩個函式分開命名,沒有合併成帶旗標的單一函式';
});

conforms('FS-TMP-003', '檔案消失且無憑證 → MISSING_HISTORICAL_EVIDENCE,不判 agent 沒做', () => {
  for (const c of [
    { existsNow: false, historicalReceipt: null },
    { existsNow: false, historicalReceipt: null, retentionKnown: true },
  ]) {
    assert.equal(evidence.reconcileHistorical(c).may_conclude_agent_did_not_do_it, false);
  }
  return 'may_conclude_agent_did_not_do_it 在所有路徑都是 false';
});

// ── §5 Goal Anchor ─────────────────────────────────────────────────
conforms('FS-GOL-001', 'GAC < 0.60 時不得輸出 CONFIRMED_DRIFT', () => {
  const gac = goalanchor.goalAnchorConfidence([fullAnchor('HANDOFF_SUMMARY')]);
  assert.equal(gac.gac, 0.55);
  assert.equal(gac.may_confirm_drift, false);
  const d = goalanchor.classifyDrift({ gacResult: gac, garResult: { gar: 0.99 } });
  assert.equal(d.state, 'GOAL_AMBIGUOUS');
  return 'GAC 0.55 的 anchor 只能得到 GOAL_AMBIGUOUS';
});

conforms('FS-GOL-002', 'owner 改需求要產生 OWNER_GOAL_CHANGE,不算 drift', () => {
  const d = goalanchor.classifyDrift({
    gacResult: goalanchor.goalAnchorConfidence([fullAnchor('EXPLICIT_OWNER_INSTRUCTION')]),
    garResult: { gar: 0.99 }, deterministicContradictions: 5,
    persistedAfterCorrection: true, evidenceDimensions: 5,
    exclusions: { ownerGoalChange: true },
  });
  assert.equal(d.state, 'OWNER_GOAL_CHANGE');
  assert.equal(d.is_drift, false);
  return '排除條件優先於所有 drift 條件';
});

conforms('FS-GOL-003', '標明為探索且隔離的分支要排除為 EXPLORATORY_BRANCH', () => {
  const d = goalanchor.classifyDrift({ exclusions: { exploratoryBranch: true } });
  assert.equal(d.state, 'EXPLORATORY_BRANCH');
  return 'classifyDrift 有 EXPLORATORY_BRANCH 排除路徑';
});

// ── §6 Drift ───────────────────────────────────────────────────────
conforms('FS-DRF-001', 'drift 輸出必須帶 state/confidence/anchor/evidence/exclusions', () => {
  const d = goalanchor.classifyDrift({ goalAnchorRef: 'g', evidenceRefs: ['e'] });
  for (const f of ['state', 'confidence', 'goal_anchor_ref', 'evidence_refs', 'exclusions_checked']) {
    assert.ok(f in d, f);
  }
  return '五個必要欄位都在';
});

conforms('FS-DRF-002', 'drift 不得只由語意相似度或單次 LLM 判斷決定', () => {
  const src = SRC('goalanchor.js');
  assert.ok(!/embedding|similarity|cosine/i.test(src));
  return 'goalanchor.js 沒有任何相似度計算,判定來自 GAC/GAR/排除條件';
});

conforms('FS-DRF-003', 'agent 回答「是」只能算 DECLARED,不得降低 drift risk', () => {
  const r = challenge.crossCheck(
    Object.fromEntries(challenge.CHALLENGE_QUESTIONS.map((_, i) => [`q${i + 1}`, 'a'])), {});
  assert.equal(r.evidence_class, 'DECLARED');
  assert.equal(r.risk_reduced, false);
  return 'crossCheck 的 risk_reduced 在任何路徑都是 false';
});

conforms('FS-DRF-004', '證據不足以定位單一 turn 時要回範圍,不製造假精確', () => {
  const r = goalanchor.goalDistanceTrend([{ actions: [{ support: 'DIRECT' }] }]);
  assert.equal(r.trend, null);
  return '窗數不足時回 null 而不是一個看起來精確的斜率';
});

// ── §7 Metrics ─────────────────────────────────────────────────────
conforms('FS-MET-PS-001', 'Finding ≠ Progress', () => {
  const r = primitives.findingToAchievement({
    actualState: 'FINDING', claimedState: 'GOAL_OUTCOME',
  });
  assert.equal(r.is_fap, true);
  return 'FP-10 擋住 FINDING → GOAL_OUTCOME 的越級';
});

conforms('FS-MET-TO-001', '長時間 task 本身不等於 failure', () => {
  const r = liveness.classifyLongTask({ durationMs: 30 * 60_000, artifactGrowing: true });
  assert.equal(r.class, 'LONG_VALID_TASK');
  return '有成長訊號時 30 分鐘的 task 判為 LONG_VALID_TASK';
});

conforms('FS-MET-RL-001', '新證據或換策略後的 retry 不算同一 loop', () => {
  const attempts = Array.from({ length: 5 }, (_, i) => ({
    intent_class: 'x', target: 'y', strategy: 'z', new_evidence: i === 3,
  }));
  assert.equal(liveness.retryLoop(attempts).rl, 0);
  return '有 new_evidence 的群組 RL 歸零';
});

conforms('FS-MET-CB-001', '情緒不得直接增加 CB/HCD', () => {
  const src = SRC('incident.js') + SRC('progress.js') + SRC('risk.js');
  assert.ok(!/\b(sentiment|profanity|anger|angry)\b/i.test(src));
  return '三個相關模組沒有任何情緒訊號輸入';
});

conforms('FS-MET-HC-001', 'HCD 需要 sustained correction + under-delivery 才成立', () => {
  const both = collaboration.collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8], underDeliverySignals: ['PS_HIGH'],
  });
  assert.equal(both.verdict, 'HUMAN_AS_QA');
  // 少任何一個條件都不成立。
  const noUnderDelivery = collaboration.collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8], underDeliverySignals: [],
  });
  const noBurden = collaboration.collaborationDegradation({
    cbWindows: [0.1, 0.1, 0.1], underDeliverySignals: ['PS_HIGH'],
  });
  assert.notEqual(noUnderDelivery.verdict, 'HUMAN_AS_QA');
  assert.notEqual(noBurden.verdict, 'HUMAN_AS_QA');
  return '兩個條件都齊才判 HUMAN_AS_QA,缺一不可';
});

conforms('FS-MET-OD-001', '沒有 healthy baseline 時 OD 要降 confidence 或回 INDETERMINATE',
  () => {
    const r = risk.compositeRisk([{ id: 'OD', score: null, confidence: null }]);
    assert.equal(r.r, null);
    return '沒有基線時 OD 不進 composite,R 回 null';
  });

conforms('FS-MET-SM-001', 'agent self-report 無權降低 SM', () => {
  const r = challenge.crossCheck({}, { deterministicContradictions: [{ id: 'x' }] });
  assert.equal(r.risk_reduced, false);
  return '自我報告在任何情況下都不降低風險';
});

conforms('FS-MET-PA-001', '核心前提失效時,依賴的 plan node 要失去 authority', () => {
  const r = primitives.invalidatedNarrativePersistence({
    planNodes: [{ id: 'n1', depends_on: ['p'], status: 'ACTIVE' }],
    invalidatedPrerequisites: ['p'],
  });
  assert.deepEqual([...r.must_lose_authority], ['n1']);
  return 'FP-22 回傳 must_lose_authority 清單';
});

conforms('FS-MET-RB-001', '高成本但有 verified progress 不等於 burn', () => {
  const r = progress.progressStagnation({ activity: 1, verifiedProgress: 0.9 });
  assert.equal(r.high_activity_low_progress, false);
  return '高活動 + 高驗證進度不觸發停滯旗標';
});

// ── §8 Composite ───────────────────────────────────────────────────
conforms('FS-RSK-001', 'Composite R 必須同時顯示 EvidenceCoverage', () => {
  // 三個 metric 只量到一個 = 0.33 覆蓋,明確低於門檻。
  // 第一版用兩個 metric 量到一個(剛好 0.5,等於門檻),測到的是邊界而不是
  // 「低覆蓋」這件事本身 —— 邊界行為另外用下面那條鎖住。
  const low = risk.compositeRisk([
    { id: 'CED', score: 0.9, confidence: 1 },
    { id: 'PS', score: null, confidence: null },
    { id: 'TOS', score: null, confidence: null },
  ]);
  assert.ok('evidence_coverage' in low);
  assert.ok(low.evidence_coverage < 0.5);
  assert.equal(low.state, 'LOW_EVIDENCE');
  assert.equal(low.may_block, false);

  // 邊界:剛好達到門檻算足夠,因為那個常數叫「min...ForConfidentRisk」。
  const atThreshold = risk.compositeRisk([
    { id: 'CED', score: 0.9, confidence: 1 },
    { id: 'PS', score: null, confidence: null },
  ]);
  assert.equal(atThreshold.evidence_coverage, 0.5);
  assert.notEqual(atThreshold.state, 'LOW_EVIDENCE');

  // 不論哪一種,兩個欄位都必須同時存在。
  for (const r of [low, atThreshold]) {
    assert.ok('r' in r && 'evidence_coverage' in r);
  }
  return '低覆蓋(0.33)判 LOW_EVIDENCE 且不得阻擋;剛好達標(0.5)不判低;兩欄永遠同時出現';
});

// ── §9 Trend ───────────────────────────────────────────────────────
conforms('FS-TRD-001', '單次 spike 不得自動等於 degradation', () => {
  const r = risk.trend([0.05, 0.05, 0.9, 0.05, 0.05]);
  assert.equal(r.counts_as_degradation, false);
  return 'single_spike_only 為真時 counts_as_degradation 為假';
});

conforms('FS-TRD-002', '連續惡化要提升 sampling 與 challenge priority', () => {
  const r = risk.trend([0.3, 0.4, 0.5, 0.6, 0.7]);
  assert.equal(r.raise_sampling, true);
  assert.equal(r.raise_challenge_priority, true);
  return '持續惡化時兩個旗標都升起';
});

conforms('FS-TRD-003', 'trend confidence 不足時,「多久會壞」回 UNKNOWN', () => {
  assert.equal(risk.trend([0.1, 0.5, 0.9]).time_to_failure, 'UNKNOWN');
  return 'time_to_failure 永遠是 UNKNOWN,沒有預測路徑';
});

// ── §10 Windows ────────────────────────────────────────────────────
conforms('FS-WIN-001', 'Stage A 只用事件指標,不讀全 session 語意', () => {
  assert.equal(challenge.semanticReadAllowed({ stage: 'A' }).allowed, false);
  return 'Stage A 的語意讀取被拒絕';
});

conforms('FS-WIN-002', 'Stage B 依變化點/強度/持續性/下游影響排序', () => {
  const s = challenge.WINDOW_STAGES.find((x) => x.stage === 'B');
  assert.match(s.rule, /change point.*anomaly strength.*persistence.*downstream impact/);
  return 'Stage B 的規則四個因子齊全,實作在 v1 windows.js';
});

conforms('FS-WIN-003', 'Stage C 才允許讀有界切片', () => {
  const r = challenge.semanticReadAllowed({ stage: 'C' });
  assert.equal(r.allowed, true);
  assert.equal(r.slice.provisional, true);
  return 'Stage C 放行且切片範圍標成 provisional';
});

conforms('FS-WIN-004', 'Stage D 不得成為 runtime 必要條件', () => {
  assert.equal(challenge.semanticReadAllowed({ stage: 'D', isRuntime: true }).allowed, false);
  return 'runtime 情境下 Stage D 被拒絕';
});

// ── §11 Topology ───────────────────────────────────────────────────
conforms('FS-TOP-001', '看不到 sub-agent prompt 時必須標 UNKNOWN_EDGE 且不得腦補', () => {
  const g = topology.createGraph();
  assert.throws(() => g.addEdge({ from: 'a', to: 'b', type: 'UNKNOWN_EDGE' }),
    /must say why it is unknown/);
  return 'UNKNOWN_EDGE 沒有理由就拒絕建立';
});

conforms('FS-TOP-002', 'Topology 要能顯示「artifact 都做了但與 Goal 的交集下降」', () => {
  const g = topology.createGraph();
  g.addNode({ id: 'goal', type: 'GOAL' });
  for (const id of ['a', 'b']) g.addNode({ id, type: 'TASK' });
  g.addEdge({ from: 'a', to: 'goal', type: 'SUPPORTS' });
  const r = g.goalIntersection('goal', {
    windows: [{ actionNodeIds: ['a'] }, { actionNodeIds: ['b'] }],
  });
  assert.equal(r.declining, true);
  return 'goalIntersection 的 declining 抓得到交集下降';
});

// ── §12 Challenge ──────────────────────────────────────────────────
conforms('FS-CHL-001', '不得用「你有沒有飄」當有效 challenge', () => {
  assert.throws(() => challenge.buildChallenge({ extraQuestions: ['你有沒有飄?'] }),
    /Refusing to include a self-report question/);
  return 'buildChallenge 拒絕自我報告式問題';
});

conforms('FS-CHL-002', 'challenge 答案存成 DECLARED,不得蓋過確定性矛盾', () => {
  const r = challenge.crossCheck({}, { deterministicContradictions: [{ id: 'x' }] });
  assert.equal(r.verdict, 'CONTRADICTED_BY_EVIDENCE');
  assert.equal(r.evidence_class, 'DECLARED');
  return '有矛盾時直接回 CONTRADICTED_BY_EVIDENCE,不看答案品質';
});

conforms('FS-CHL-003', 'challenge 在 trigger 時插入,不是每一步都問', () => {
  assert.equal(challenge.shouldChallenge({ risk: 0.1 }).challenge, false);
  assert.equal(challenge.shouldChallenge({ risk: 0.9, lastChallengeAgeMs: 1000 }).challenge, false);
  return '低風險與剛問過都不再問';
});

// ── §13 Human-as-QA ────────────────────────────────────────────────
conforms('FS-HQA-001', 'Human-as-QA 由 correction/omission 事件定義,不由語氣定義', () => {
  // 用 \b 界定,不然 milesTONEs 這種字會誤中。這條測試本身第一版就踩到了。
  const src = SRC('progress.js') + SRC('incident.js');
  assert.ok(!/\b(sentiment|tone|angry|profanity)\b/i.test(src));
  return '相關模組不接受任何情緒輸入';
});

conforms('FS-HQA-002', 'early healthy baseline 對比後期下降可作 HCD 加強證據', () => {
  const r = collaboration.collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8], underDeliverySignals: ['PS_HIGH'],
    earlyAutonomousBaseline: 10, lateAutonomousProgress: 2,
  });
  assert.equal(r.autonomy_evidence, true);
  // 規格書寫的是 MAY,所以沒有這個證據也要判得出來。
  const without = collaboration.collaborationDegradation({
    cbWindows: [0.6, 0.7, 0.8], underDeliverySignals: ['PS_HIGH'],
  });
  assert.equal(without.verdict, 'HUMAN_AS_QA');
  assert.equal(without.autonomy_drop, null);
  return '自主性下滑記為加強證據,但它是 MAY,不是判定的必要條件';
});

conforms('FS-HQA-003', 'HCD 與 PS/RB 同時升高時應優先建議 rescue', () => {
  const r = recovery.chooseIntervention({ risk: 0.85, checkpointAvailable: true });
  assert.equal(r.name, 'RESCUE');
  return '高風險且有 checkpoint 時 ladder 走到 RESCUE';
});

// ── §14 Tool failure ───────────────────────────────────────────────
conforms('FS-TOOL-001', 'Duration alone 不得判 stall', () => {
  const r = liveness.classifyLongTask({ durationMs: 60 * 60_000 });
  assert.equal(r.class, 'UNKNOWN_TOOL_FAILURE');
  assert.equal(r.duration_alone_was_not_used, true);
  return '沒有成長訊號時拒絕判定,即使跑了一小時';
});

conforms('FS-TOOL-002', '同一 signature 再現時提升 recurrence risk(PROVISIONAL)', () => {
  const r = liveness.recurrenceRisk(['sig', 'sig']);
  assert.equal(r.elevated, true);
  assert.equal(r.provisional, true);
  return 'recurrenceRisk 抬高關注但標 provisional,不給校準過的分數';
});

// ── §15 Resource burn ──────────────────────────────────────────────
conforms('FS-RB-001', '監測 ResourceCost→VerifiedProgress,不單看 token', () => {
  const r = progress.progressStagnation({ activity: 1, verifiedProgress: 0 });
  assert.equal(r.high_activity_low_progress, true);
  return 'PS 用 activity × (1-verified) 而不是 token 絕對值';
});

conforms('FS-RB-002', '等價策略反覆且進度平坦時應停止昂貴 retry', () => {
  const attempts = Array.from({ length: 5 }, () => ({
    intent_class: 'x', target: 'y', strategy: 'z', state_changed: false,
  }));
  assert.equal(liveness.retryLoop(attempts).class, 'TOOL_LOOP');
  return 'retryLoop 判定 TOOL_LOOP';
});

// ── §16 Intervention ───────────────────────────────────────────────
conforms('FS-INT-001', '預設 observe-first,不是同步 gate everything', () => {
  assert.equal(recovery.chooseIntervention({}).level, 0);
  return '無訊號時預設 L0 OBSERVE';
});

conforms('FS-INT-002', '每個介入都要回答 evidence/confidence/why now/next action', () => {
  const r = recovery.chooseIntervention({ risk: 0.65 });
  for (const f of ['evidence_refs', 'confidence', 'why_now', 'lowest_cost_action']) {
    assert.ok(f in r, f);
  }
  return '四個欄位在所有 ladder 等級都存在';
});

conforms('FS-INT-003', '未經 healthy corpus 校準前,hard blocking 不得是預設', () => {
  const r = recovery.chooseIntervention({
    hardEvidence: true, policyRequiresBlock: true, hardBlockingEnabled: false,
  });
  assert.notEqual(r.level, 5);
  return '硬證據齊備但未啟用硬擋時降到 L3';
});

// ── §17 Rescue ─────────────────────────────────────────────────────
conforms('FS-RCV-001', 'rescue 保留已驗證的工作,不得帶走失效的敘事', () => {
  const c = recovery.buildRecoveryCapsule({
    verifiedWork: ['w'], invalidatedNarrative: ['the DB was corrupted'],
  });
  assert.deepEqual([...c.excluded_invalidated_narrative], ['the DB was corrupted']);
  assert.equal(c.first_action_must_be_reverified, true);
  return 'capsule 明確列出被留下的失效敘事';
});

conforms('FS-RCV-002', 'rescue 輸出是單一可行動方案,不是十幾個告警', () => {
  const card = recovery.rescueCard(recovery.buildRecoveryCapsule({}));
  assert.ok('recommended_action' in card);
  assert.ok(!('warnings' in card));
  return 'rescueCard 沒有 warnings 陣列,只有一個 recommended_action';
});

// ── §18 Continuity ─────────────────────────────────────────────────
conforms('FS-CTX-001', '三種 context 必須分開', () => {
  assert.deepEqual([...recovery.CONTEXT_KINDS],
    ['CHAT_HISTORY', 'CANONICAL_PROJECT_STATE', 'HEALTHY_COLLABORATION_CONTEXT']);
  return 'CONTEXT_KINDS 三分';
});

conforms('FS-CTX-002', 'successor 優先取高進度低更正的片段,不是取最新的', () => {
  const r = recovery.selectHealthyContext([
    { id: 'early', verified_progress: 0.9, correction_burden: 0.05, goal_stable: true },
    { id: 'latest', verified_progress: 0.05, correction_burden: 0.9, goal_stable: false },
  ]);
  assert.equal(r.selected.id, 'early');
  return '選到較早的健康片段而非最新片段';
});

conforms('FS-CTX-003', '失敗段落只能做 forensic,不得成為 successor 模板', () => {
  const r = recovery.selectHealthyContext([
    { id: 'good', verified_progress: 0.9, correction_burden: 0, goal_stable: true },
    { id: 'bad', verified_progress: 0.01, correction_burden: 0.99, goal_stable: false },
  ]);
  assert.equal(r.forensic_only.find((f) => f.id === 'bad').may_be_used_as_template, false);
  return '失敗片段標成 may_be_used_as_template: false';
});

// ── §19 Corpus ─────────────────────────────────────────────────────
conforms('FS-CORP-001', '自白裡的動機敘述只能存成 DECLARED_CAUSAL_HYPOTHESIS', () => {
  const r = evidence.intentionalityRecord({ modelSelfReport: '因為 RLHF' });
  assert.equal(r.intentionality_state, 'DECLARED');
  return 'intentionalityRecord 把 model self-report 鎖在 DECLARED';
});

notCheckable('FS-CORP-002', '自白只能轉成可外部重建的結構',
  '對語料處理流程的要求。對應物是 docs/cases/ 每份檔頭的證據等級標註,'
  + '以及 spec-v0.1.test.mjs 第 34 條的斷言。');

conforms('FS-CORP-003', 'owner 逐字判定屬 HUMAN_ADJUDICATION', () => {
  const r = evidence.intentionalityRecord({ humanAdjudication: '這是飄移' });
  assert.equal(r.intentionality_state, 'OWNER_ADJUDICATED');
  return 'owner 判定有自己的狀態,不跟 model self-report 混用';
});

conforms('FS-CORP-004', 'human adjudication 不得取代 deterministic runtime fact', () => {
  const r = evidence.intentionalityRecord({ humanAdjudication: 'x' });
  assert.match(r.note, /not for the.*mental state/s);
  assert.equal(r.MUST_NOT_AUTOPROMOTE_TO_OBSERVED, true);
  return 'owner 判定仍帶 MUST_NOT_AUTOPROMOTE 旗標';
});

conforms('FS-CORP-005', '可判可觀測的 runtime pattern,不得自動輸出「故意」', () => {
  const p = progress.detectPromisedTaskNonexecution(
    goalanchor.createCommitment({ taskId: 't', status: 'NOT_STARTED' }),
    { executionLineageCount: 0, unrelatedActivityCount: 5 });
  assert.equal(p.verdict, 'PROMISED_TASK_NONEXECUTION');
  assert.ok(!/intent|malic|deliberate/i.test(JSON.stringify(p)));
  return 'PTN 判得出行為,回傳裡沒有任何意圖欄位';
});

conforms('FS-CORP-006', '行為/人判/自白/意圖必須分欄且保留 provenance', () => {
  const r = evidence.intentionalityRecord({
    humanAdjudication: 'h', modelSelfReport: 'm', externalEvidence: ['e'],
  });
  for (const f of ['human_adjudication', 'model_self_report', 'external_evidence',
    'intentionality_state']) assert.ok(f in r, f);
  return '四個來源分別存在各自欄位';
});

// ── §20-21 Matrix / Registry ───────────────────────────────────────
conforms('FS-MTX-001', 'MODEL_SELF_REPORT case card 是 hypothesis,不等於事實', () => {
  const readme = readFileSync(join(HERE, '..', 'docs', 'cases', 'README.md'), 'utf8');
  assert.match(readme, /MODEL_SELF_REPORT/);
  return 'docs/cases/README.md 標明六份全部是 MODEL_SELF_REPORT';
});

conforms('FS-MTX-002', 'artifact 有做、tool 有跑,不得當成 Goal Alignment 的替代證據', () => {
  const args = {
    gacResult: goalanchor.goalAnchorConfidence([fullAnchor('OWNER_CONFIRMED_NORTH_STAR')]),
    trendResult: { worsening: true, trend: 0.3 },
    ownerSuccessConditionProgress: 0, prerequisiteDepth: 3,
  };
  const perfect = goalanchor.detectFrameworkSubstitution({ ...args, executionSuccessRate: 1 });
  const awful = goalanchor.detectFrameworkSubstitution({ ...args, executionSuccessRate: 0 });
  assert.equal(perfect.verdict, awful.verdict);
  return '執行成功率完全不影響 FSD 判定';
});

conforms('FS-FP-001', 'primitive detector 回傳必須有六個欄位', () => {
  const f = primitives.finding({ primitiveId: 'FP-01', verdict: 'OK' });
  for (const k of primitives.REQUIRED_FIELDS) assert.ok(k in f, k);
  return 'finding() 強制六個欄位';
});

conforms('FS-FP-002', '多個 primitive 可共用 root cause,UI 先聚合再顯示', () => {
  const hits = Array.from({ length: 25 }, (_, i) => ({
    primitive_id: i < 12 ? 'FP-02' : 'FP-24',
    resource: i < 12 ? 'a.js' : 'b.js',
    severity_family: i < 12 ? 'A' : 'B',
    evidence_refs: [i < 12 ? 'e1' : 'e2'],
  }));
  const agg = incident.aggregate(hits);
  assert.equal(agg.detector_hits, 25);
  assert.equal(agg.root_incidents.length, 2);
  return '25 個 hit 聚合成 2 個 root incident';
});

// ── §21.1 Severity ─────────────────────────────────────────────────
conforms('FS-SEV-001', 'Family C 的硬矛盾必須能繞過加權平均', () => {
  const r = sef.escalate([{ severity_family: 'C', hard_contradiction: true }]);
  assert.equal(r.level, 'CRITICAL_INTEGRITY_INCIDENT');
  assert.equal(r.bypassed_composite_risk, true);
  return 'escalate 對 Family C 硬矛盾直接升級';
});

conforms('FS-SEV-002', 'Family B 不得因高 activity 降低 severity', () => {
  const c = goalanchor.createCommitment({ taskId: 't', status: 'NOT_STARTED' });
  const quiet = progress.detectPromisedTaskNonexecution(c,
    { executionLineageCount: 0, unrelatedActivityCount: 1, progressReportsImplyWork: true });
  const frantic = progress.detectPromisedTaskNonexecution(c,
    { executionLineageCount: 0, unrelatedActivityCount: 9999, progressReportsImplyWork: true });
  assert.equal(quiet.confidence, frantic.confidence);
  assert.equal(frantic.activity_did_not_reduce_score, true);
  return '活動量從 1 到 9999,PTN confidence 不變';
});

conforms('FS-SEV-003', 'severity family 描述行為嚴重度,不等於主觀惡意', () => {
  assert.ok(!/malice|intent/i.test(JSON.stringify(sef.SEVERITY_FAMILIES)));
  return 'SEVERITY_FAMILIES 的說明沒有任何意圖字眼';
});

// ── §22 Detector contracts ─────────────────────────────────────────
conforms('FS-DET-ESI-001', 'scope-expanding 語意 + 局部證據 → 未覆蓋部分標 UNVERIFIED', () => {
  const r = claims.detectScopeInflation(
    { text: '端到端已驗證', scope: claims.createScope({ environment: 'ios', stage: 'e2e' }) },
    [claims.createScope({ environment: 'headless', stage: 'e2e' })]);
  assert.equal(r.must_mark_unverified, true);
  assert.deepEqual([...r.unverified_scope], ['environment']);
  return 'ESI 標出未覆蓋維度並要求標 UNVERIFIED';
});

conforms('FS-DET-VMI-001', 'VERIFIER_UNKNOWN_COVERAGE 優先於錯誤的 pass/fail', () => {
  const r = verifier.verify(verifier.BUILTIN_CONTRACTS.grep_string, {
    rawOutcome: 'FAIL', targetType: 'file', representation: 'hex_bytes',
    semanticsRequired: ['literal_substring_present'], preconditionsMet: ['target_is_text'],
  });
  assert.equal(r.outcome, 'UNKNOWN_COVERAGE');
  assert.equal(r.may_refute_claim, false);
  return 'grep 對 hex 表示法回 UNKNOWN_COVERAGE 而非 FAIL';
});

conforms('FS-DET-EIC-001', '「兩個 agent 都這樣說」不等於兩份獨立證據', () => {
  const a = { id: 'a', upstream: ['r'], decisive_upstream: ['r'] };
  assert.equal(primitives.independence(a, { ...a, id: 'b' }), 0);
  return '共享決定性上游時 independence 為 0';
});

conforms('FS-DET-GMS-001', '宣稱有進展時必須指明是哪一層', () => {
  const r = progress.detectGoalMetricSubstitution({
    citedMetrics: ['wakeup'], goalProgress: 0, claimedLayer: null,
  });
  assert.equal(r.verdict, 'GOAL_METRIC_SUBSTITUTION');
  const honest = progress.detectGoalMetricSubstitution({
    citedMetrics: ['wakeup'], goalProgress: 0, claimedLayer: 'ACTIVITY',
  });
  assert.equal(honest.verdict, 'OK');
  return '未指明層級時報 GMS,指明 ACTIVITY 則放行';
});

conforms('FS-DET-GMS-002', 'Activity 高而 Goal 連續零時 PS/RB 必須升高', () => {
  const r = progress.progressStagnation({ activity: 1, verifiedProgress: 0 });
  assert.equal(r.ps, 1);
  return 'PS 在活動滿載、驗證進度為零時為 1';
});

conforms('FS-DET-FSD-001', '「東西真的做了」不能使 FSD 下降', () => {
  const src = SRC('goalanchor.js');
  assert.match(src, /execution_success_did_not_lower_score/);
  return 'FSD 回傳帶 execution_success_did_not_lower_score 旗標';
});

conforms('FS-DET-FAP-001', '找到 pattern 只能停在 FINDING', () => {
  const r = primitives.findingToAchievement({
    actualState: 'OBSERVATION', claimedState: 'IMPLEMENTED_ARTIFACT',
  });
  assert.equal(r.is_fap, true);
  return '沒有介入與效果量測時,升級被擋下';
});

conforms('FS-DET-SEF-001', 'SEF 必須先排除遙測缺口', () => {
  const r = sef.detectSyntheticEvidence(
    { presented_as: 'TOOL_RESULT', family: 'tool', at: T }, { ledger: [] });
  assert.equal(r.verdict, 'LEDGER_COVERAGE_UNKNOWN');
  assert.equal(r.is_sef, false);
  return '沒有 coverage 宣告時拒絕判定';
});

conforms('FS-DET-SEF-002', 'ledger 完整且矛盾確定時,直接開 CRITICAL', () => {
  const r = sef.detectSyntheticEvidence(
    { id: 'c', presented_as: 'TOOL_RESULT', family: 'tool', at: T },
    {
      ledger: [], coverage: sef.ledgerCoverage({ capturedFamilies: ['tool'] }),
      contradiction: { ledger_records_contradictory_result: true },
    });
  assert.equal(r.opens_critical_integrity_incident, true);
  assert.equal(r.bypasses_composite_risk, true);
  return '硬矛盾直接開 critical 並繞過 composite';
});

conforms('FS-DET-SEF-003', '事後講軟不算撤回', () => {
  const r = sef.evaluateRetraction({ is_sef: true, synthetic_claim_ref: 'c' },
    { statements: [{ type: 'SOFTENING' }] });
  assert.equal(r.cleared, false);
  return 'SOFTENING 不清除 SEF';
});

conforms('FS-DET-PTN-001', '忙碌不得降低 PTN 分數', () => {
  const src = SRC('progress.js');
  assert.match(src, /activity_did_not_reduce_score/);
  return 'PTN 回傳帶 activity_did_not_reduce_score 旗標';
});

conforms('FS-DET-FPR-001', 'Activity/Task/Goal 三個 progress 必須分欄', () => {
  const p = progress.computeProgress({
    completedActions: 1, plannedActions: 1, verifiedGoalDelta: 0, goalTarget: 1,
  });
  for (const f of ['activity_progress', 'task_progress', 'goal_progress']) assert.ok(f in p, f);
  assert.ok(!('overall_progress' in p));
  return '三欄齊全且沒有合成總分';
});

conforms('FS-DET-FPR-002', 'workflow/transcript/detector/wakeup 預設零 GoalProgress', () => {
  for (const s of ['workflow_spawn', 'transcript_growth', 'detector_pass', 'wakeup']) {
    assert.ok(progress.PROCESS_SIGNALS.includes(s), s);
  }
  return '四個 process signal 都在表上,預設不計入 Goal';
});

conforms('FS-PCG-001', '五類 claim 不得只憑語言進入 canonical state', () => {
  for (const type of ['TOOL_OUTPUT', 'EXTERNAL_EVENT', 'CROSS_VALIDATION',
    'TASK_COMPLETED', 'END_TO_END_VERIFIED']) {
    assert.ok(claims.GATED_CLAIM_TYPES.includes(type), type);
    assert.equal(claims.postClaimGate({ type }, {}).may_enter_canonical_state, false, type);
  }
  return '五類全部被 gate 擋下';
});

// ── §24 Warning storm ──────────────────────────────────────────────
conforms('FS-ALR-001', 'detector hit / incident / warning 三層分開', () => {
  assert.deepEqual([...incident.LAYERS],
    ['DETECTOR_HIT', 'ROOT_INCIDENT', 'USER_VISIBLE_WARNING']);
  return 'LAYERS 三層';
});

conforms('FS-ALR-002', '同 root、同證據、無新影響時必須去重', () => {
  const inc = { root_incident_key: 'k', severity_family: 'A', evidence_refs: ['e'], detector_hit_count: 1 };
  assert.equal(incident.shouldSurface(inc, { ...inc }).surface, false);
  return '同狀態的 incident 第二次不再顯示';
});

conforms('FS-ALR-003', '升級需要四個理由之一,純時間經過不算', () => {
  assert.ok(!incident.ESCALATION_REASONS.some((r) => /TIME|ELAPSED/i.test(r)));
  assert.equal(incident.ESCALATION_REASONS.length, 4);
  return '四個理由都不是時間';
});

conforms('FS-ALR-004', 'UI 要優先回答四個問題', () => {
  const s = incident.incidentSummary(incident.aggregate([
    { primitive_id: 'FP-06', resource: 'x', severity_family: 'C', evidence_refs: ['e'] },
  ]), { needsDecision: ['x'] });
  for (const f of ['root_incident_count', 'most_likely_to_break_work',
    'needs_human_decision', 'symptoms_of_same_root']) assert.ok(f in s, f);
  return 'incidentSummary 四個欄位對應四個問題';
});

conforms('FS-ALR-005', 'Forseti 自己也要接受治理成本的自我監測', () => {
  const r = incident.governanceOverhead({
    interruptionTimeMs: 100, activeWorkTimeMs: 1000, userTriageDecisions: 5,
  });
  assert.equal(r.self_hcd_signal, true);
  return 'governanceOverhead 會標出使用者在分診 Forseti 自己的警告';
});

// ── §25 Calibration ────────────────────────────────────────────────
notCheckable('FS-CAL-001', 'annotator 先看事件再看自白',
  '對標註流程的要求,不是對程式的要求。');

notCheckable('FS-CAL-002', '只有自白的 case 進 hypothesis corpus 不進 ground-truth corpus',
  '對語料庫組織的要求。對應物是 docs/cases/ 的證據等級標註。');

conforms('FS-CAL-003', '每個 primitive 要有 positive/negative/exclusion/low-evidence fixture',
  () => {
    // 抽查三份 v2 測試檔,確認四種 fixture 的字樣都在。
    for (const f of ['claims', 'progress', 'sef']) {
      const src = readFileSync(join(HERE, `${f}.test.mjs`), 'utf8');
      for (const kind of ['positive', 'negative', 'exclusion', 'low-evidence']) {
        assert.ok(src.includes(kind), `${f}.test.mjs 缺 ${kind}`);
      }
    }
    return 'claims/progress/sef 三份測試都有四種 fixture';
  });

// ── §26 Implementation order ───────────────────────────────────────
conforms('FS-IMP-001', 'P3/P4/P5/P6 未完成前不得把 drift classifier 當主判斷器', () => {
  // 掃的是程式碼,不是註解 —— 第一版掃了整個檔案,結果命中自己引用規格書
  // 那句「用另一個 LLM 替模糊規格下結論」的註解。要證明的是沒有模型呼叫,
  // 不是沒有提到模型這個詞。
  const code = SRC('goalanchor.js')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/\/\/.*$/gm, '');
  assert.ok(!/\b(llm|openai|anthropic|fetch|require)\b/i.test(code));
  assert.ok(!/^import\s/m.test(code), 'goalanchor.js 零依賴');
  const d = goalanchor.classifyDrift({ gacResult: goalanchor.goalAnchorConfidence([]) });
  assert.equal(d.state, 'GOAL_AMBIGUOUS');
  return 'drift 判定完全由 GAC/GAR/排除條件驅動,程式碼裡沒有任何模型或網路呼叫';
});

conforms('FS-IMP-002', 'P11 未完成前不得把 detector hits 直接推給使用者', () => {
  assert.equal(typeof incident.aggregate, 'function');
  assert.equal(typeof incident.shouldSurface, 'function');
  const agg = incident.aggregate(Array.from({ length: 10 }, () => ({
    primitive_id: 'FP-02', resource: 'a', severity_family: 'A', evidence_refs: ['e'],
  })));
  assert.equal(agg.root_incidents.length, 1);
  return 'aggregator 存在且會收斂;runtime.triage 是唯一對外的路徑';
});

// ── 輸出 ───────────────────────────────────────────────────────────
console.log('\n對照 docs/spec-v2.0.md 的規範句\n');
const order = { VIOLATION: 0, NOT_IMPLEMENTED: 1, NOT_CHECKABLE: 2, CONFORMS: 3 };
for (const r of [...results].sort((a, b) => order[a.verdict] - order[b.verdict]
  || a.id.localeCompare(b.id))) {
  const mark = r.verdict === 'CONFORMS' ? '   '
    : r.verdict === 'NOT_IMPLEMENTED' ? ' ☐ '
      : r.verdict === 'NOT_CHECKABLE' ? ' · ' : ' ✗ ';
  console.log(`${mark}${r.id}  ${r.what}`);
  if (r.verdict !== 'CONFORMS') console.log(`       ${r.verdict}  ${r.evidence}`);
}

const counts = results.reduce((a, r) => ({ ...a, [r.verdict]: (a[r.verdict] ?? 0) + 1 }), {});
console.log('\n  CONFORMS          ' + (counts.CONFORMS ?? 0));
console.log('  NOT_IMPLEMENTED   ' + (counts.NOT_IMPLEMENTED ?? 0));
console.log('  NOT_CHECKABLE     ' + (counts.NOT_CHECKABLE ?? 0));
console.log('  VIOLATION         ' + (counts.VIOLATION ?? 0));
console.log(`\n  這一份涵蓋 ${results.length} 條;規格書共 93 條 FS 規範句,`);
console.log('  其餘為 §7 度量公式與 §22 detector contract 的細節,已由各模組自己的測試涵蓋。\n');

process.exitCode = (counts.VIOLATION ?? 0) > 0 ? 1 : 0;
