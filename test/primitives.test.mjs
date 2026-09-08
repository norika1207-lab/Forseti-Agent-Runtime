// Forseti v2.0 — Failure Primitive Registry 與其餘十一個 detector。
// 規格 §21、§22.1、§22.5、§22.8、§22.9、§22.12、§22.13、§22.14。
// 對應 CT-005、CT-006、CT-010、CT-012、CT-013、CT-015、CT-018、CT-023、
// CT-038、CT-039。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, REGISTRY, REQUIRED_FIELDS, finding,
  ucwe, independence, evidenceIndependenceCollapse,
  OUTCOME_STATES, findingToAchievement,
  BUILD_STATES, statePromotionWithoutGate,
  unsupportedCausalCompletion, unauthorizedConstraintExpansion,
  prematureClosure, mechanismAttributionSubstitution,
  POPULATION_TERMS, samplingToPopulationInflation,
  correctionAbsorptionFailure, invalidatedNarrativePersistence,
} from '../src/primitives.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;

// ---- §21 registry ----
t('二十五個 primitive,一個不少,編號連續', () => {
  assert.equal(REGISTRY.length, 25);
  REGISTRY.forEach((p, i) => {
    assert.equal(p.id, `FP-${String(i + 1).padStart(2, '0')}`, p.id);
  });
});

t('每個 primitive 都指得出它做在哪個模組', () => {
  for (const p of REGISTRY) {
    assert.ok(p.implemented_in, p.id);
    assert.match(p.implemented_in, /\.js$/, p.id);
  }
});

t('severity family 只有 A/B/C,而 C 只有 FP-06', () => {
  const c = REGISTRY.filter((p) => p.family === 'C');
  assert.deepEqual(c.map((p) => p.id), ['FP-06']);
  for (const p of REGISTRY) assert.ok(['A', 'B', 'C'].includes(p.family), p.id);
});

t('FS-FP-001:六個必要欄位一個都不能少', () => {
  const f = finding({ primitiveId: 'FP-01', verdict: 'OK' });
  for (const k of REQUIRED_FIELDS) assert.ok(k in f, `缺 ${k}`);
});

t('不認得的 primitive 直接炸,不靜靜接受', () =>
  assert.throws(() => finding({ primitiveId: 'FP-99' }), /Unknown primitive/));

// ---- FP-01 UCWE:CT-005 / CT-006 ----
t('CT-005 positive:沒有 speaker label 卻指派了說話者', () => {
  const r = ucwe({
    unknownRef: 'speaker_of_line_42', unknownState: 'MISSING',
    resolvingClaim: { id: 'c1', text: '這句是阿信說的' },
    evidenceBetween: [],
  });
  assert.equal(r.verdict, 'UNCERTAINTY_COLLAPSE_WITHOUT_EVIDENCE');
  assert.equal(r.evidence_gain, 0);
  assert.equal(r.ucwe_score, 1);
});

t('CT-006 negative:期間取得了支持該結論的證據就不算', () => {
  const r = ucwe({
    unknownRef: 'auth_required', unknownState: 'UNKNOWN',
    resolvingClaim: { id: 'c2' },
    evidenceBetween: [{ id: 'e1', supports: 'auth_required' }],
  });
  assert.equal(r.verdict, 'OK');
  assert.equal(r.evidence_gain, 1);
});

t('exclusion:owner 自己給了那個值,不是崩塌是答案', () => {
  const r = ucwe({ unknownState: 'UNKNOWN', resolvingClaim: { id: 'c' }, suppliedByOwner: true });
  assert.equal(r.is_ucwe, false);
  assert.match(r.note, /that is an answer/);
});

t('exclusion:明講推測且下游沒當成事實 = 系統正常運作', () => {
  const r = ucwe({
    unknownState: 'UNKNOWN', resolvingClaim: { id: 'c' },
    claimLabelledAsInference: true, downstreamPromotedToFact: false,
  });
  assert.equal(r.is_ucwe, false);
  assert.match(r.note, /is the system working/);
});

t('positive:講了推測但下游還是當成事實 → 仍然是 UCWE', () => {
  const r = ucwe({
    unknownRef: 'x', unknownState: 'UNKNOWN', resolvingClaim: { id: 'c' },
    claimLabelledAsInference: true, downstreamPromotedToFact: true,
  });
  assert.equal(r.is_ucwe, true);
});

t('low-evidence:原本就不是 UNKNOWN 的話沒有東西崩塌', () =>
  assert.equal(ucwe({ unknownState: 'OBSERVED', resolvingClaim: { id: 'c' } }).verdict,
    'NOT_APPLICABLE'));

// ---- FP-05 EIC:CT-018 ----
t('CT-018 positive:agent B 只讀 agent A 的輸出,independence 是 0', () => {
  const a = { id: 'ea', upstream: ['report_a'], decisive_upstream: ['report_a'] };
  const b = { id: 'eb', upstream: ['report_a'], decisive_upstream: ['report_a'] };
  assert.equal(independence(a, b), 0);
  const r = evidenceIndependenceCollapse({ evidences: [a, b], claimedAsCorroboration: true });
  assert.equal(r.verdict, 'EVIDENCE_INDEPENDENCE_COLLAPSE');
  assert.match(r.note, /one observation, counted twice/);
});

t('CT-018 negative:決定性路徑真的獨立才算兩份證據', () => {
  const a = { id: 'ea', upstream: ['fs'], decisive_upstream: ['fs'] };
  const b = { id: 'eb', upstream: ['git'], decisive_upstream: ['git'] };
  assert.equal(independence(a, b), 1);
  assert.equal(evidenceIndependenceCollapse({
    evidences: [a, b], claimedAsCorroboration: true,
  }).is_eic, false);
});

t('CT-018 exclusion:沒有宣稱互相印證的話不報', () => {
  const a = { id: 'ea', upstream: ['x'], decisive_upstream: ['x'] };
  assert.equal(evidenceIndependenceCollapse({
    evidences: [a, { ...a, id: 'eb' }], claimedAsCorroboration: false,
  }).is_eic, false);
});

t('CT-018 low-evidence:沒宣告上游時不准假設獨立', () => {
  const r = evidenceIndependenceCollapse({
    evidences: [{ id: 'a' }, { id: 'b' }], claimedAsCorroboration: true,
  });
  assert.equal(r.verdict, 'UPSTREAM_UNKNOWN');
  assert.equal(r.confidence, null);
  assert.match(r.note, /MUST NOT be assumed/);
});

// ---- FP-10 FAP:CT-012 ----
t('六個成果階段,照 §22.8 原文', () =>
  assert.deepEqual([...OUTCOME_STATES], ['OBSERVATION', 'FINDING', 'IMPLEMENTED_ARTIFACT',
    'EXECUTED', 'VERIFIED_EFFECT', 'GOAL_OUTCOME']));

t('CT-012 positive:找到 pattern 卻宣稱是產品成果', () => {
  const r = findingToAchievement({ actualState: 'FINDING', claimedState: 'GOAL_OUTCOME' });
  assert.equal(r.verdict, 'FINDING_TO_ACHIEVEMENT_PROMOTION');
  assert.match(r.note, /A pattern found.*is not a problem solved/s);
});

t('CT-012 negative:有介入也量了效果,可以升到 VERIFIED_EFFECT', () => {
  const r = findingToAchievement({
    actualState: 'EXECUTED', claimedState: 'VERIFIED_EFFECT',
    hasIntervention: true, hasEffectMeasurement: true,
  });
  assert.equal(r.is_fap, false);
});

t('CT-012 exclusion:只有介入沒量效果,天花板停在 EXECUTED', () => {
  const r = findingToAchievement({
    actualState: 'FINDING', claimedState: 'VERIFIED_EFFECT', hasIntervention: true,
  });
  assert.equal(r.is_fap, true);
});

t('CT-012 low-evidence:狀態不在階梯上就不比', () =>
  assert.equal(findingToAchievement({ actualState: 'WHATEVER', claimedState: 'GOAL_OUTCOME' })
    .verdict, 'INDETERMINATE'));

// ---- FP-11 SPWG:CT-013 ----
t('七個 build state,照 §22.9 原文', () =>
  assert.deepEqual([...BUILD_STATES], ['PLANNED', 'WRITTEN', 'BUILT', 'TESTED', 'DEPLOYED',
    'VERIFIED', 'RELEASABLE']));

t('CT-013 positive:patch written 卻被講成 tested', () => {
  const r = statePromotionWithoutGate({ actualState: 'WRITTEN', claimedState: 'TESTED' });
  assert.equal(r.verdict, 'STATE_PROMOTION_WITHOUT_GATE');
  assert.deepEqual([...r.missing_gates], ['BUILT', 'TESTED']);
  assert.equal(r.required_label, 'WRITTEN_NOT_BUILT');
});

t('CT-013 negative:每一階都有 gate receipt 就合法', () => {
  const r = statePromotionWithoutGate({
    actualState: 'WRITTEN', claimedState: 'TESTED',
    gateReceipts: [{ id: 'g1', reaches: 'BUILT' }, { id: 'g2', reaches: 'TESTED' }],
  });
  assert.equal(r.is_spwg, false);
});

t('CT-013 exclusion:宣稱的狀態不高於實際就沒問題', () =>
  assert.equal(statePromotionWithoutGate({ actualState: 'BUILT', claimedState: 'WRITTEN' })
    .is_spwg, false));

// ---- FP-14 UCC ----
t('positive:症狀直接跳到「DB 被毀了」,中間沒有 verifier', () => {
  const r = unsupportedCausalCompletion({
    symptom: 'quick_check timeout', claimedCause: 'DB corrupted', causalChain: [],
  });
  assert.equal(r.verdict, 'UNSUPPORTED_CAUSAL_COMPLETION');
  assert.equal(r.highest_allowed_state, 'HYPOTHESIS');
});

t('negative:每條因果邊都有 verifier 就成立', () => {
  const r = unsupportedCausalCompletion({
    symptom: 'A', claimedCause: 'C',
    causalChain: [{ from: 'A', to: 'C', verifier_ref: 'v1' }],
  });
  assert.equal(r.is_ucc, false);
  assert.equal(r.highest_allowed_state, 'CONFIRMED_CAUSE');
});

t('exclusion:明講是假設就不算', () => {
  const r = unsupportedCausalCompletion({ claimedCause: 'C', labelledAsHypothesis: true });
  assert.equal(r.is_ucc, false);
});

t('low-evidence:部分邊沒 verifier 也要報,並列出是哪幾條', () => {
  const r = unsupportedCausalCompletion({
    symptom: 'A', claimedCause: 'C',
    causalChain: [{ from: 'A', to: 'B', verifier_ref: 'v1' }, { from: 'B', to: 'C' }],
  });
  assert.equal(r.is_ucc, true);
  assert.deepEqual([...r.unverified_edges], ['B->C']);
});

// ---- FP-15 UCE:CT-010 ----
t('CT-010 positive:不准用 Claude API 被擴張成不准生任何圖', () => {
  const r = unauthorizedConstraintExpansion({
    ownerConstraints: [{ id: 'oc1', text: 'do not use Claude API', scope: ['claude_api'] }],
    appliedConstraint: {
      id: 'ac1', text: 'no image generation of any kind',
      derived_from: 'oc1', scope: ['claude_api', 'local_image_gen', 'pil'],
    },
  });
  assert.equal(r.verdict, 'UNAUTHORIZED_CONSTRAINT_EXPANSION');
  assert.deepEqual([...r.expanded_scope], ['local_image_gen', 'pil']);
  assert.equal(r.may_hard_authorize_plan, false);
});

t('CT-010 negative:範圍一樣就不算擴張', () => {
  const r = unauthorizedConstraintExpansion({
    ownerConstraints: [{ id: 'oc1', scope: ['claude_api'] }],
    appliedConstraint: { id: 'ac1', derived_from: 'oc1', scope: ['claude_api'] },
  });
  assert.equal(r.is_uce, false);
  assert.equal(r.may_hard_authorize_plan, true);
});

t('CT-010 exclusion:沒有 owner provenance → 標成模型自訂,不得硬性授權計畫', () => {
  const r = unauthorizedConstraintExpansion({
    appliedConstraint: { id: 'ac1', text: '所以不能生圖', scope: ['image'] },
  });
  assert.equal(r.verdict, 'MODEL_DERIVED_CONSTRAINT');
  assert.equal(r.may_hard_authorize_plan, false);
});

// ---- FP-16 PCLOSE ----
t('positive:ssh 一次失敗就宣告整台機器不通', () => {
  const r = prematureClosure({
    attempts: [{ id: 'a1', approach: 'ssh_key' }],
    conclusion: 'GX10 不通', conclusionScope: 'GLOBAL',
  });
  assert.equal(r.verdict, 'PREMATURE_CLOSURE');
  assert.match(r.note, /One failed.*attempt is not impossibility/s);
});

t('negative:試過多種方法就不算過早收攤', () => {
  const r = prematureClosure({
    attempts: [{ approach: 'ssh_key' }, { approach: 'password' }, { approach: 'tailscale' }],
    conclusion: '不通', conclusionScope: 'GLOBAL',
  });
  assert.equal(r.is_pclose, false);
});

t('exclusion:結論限定在局部範圍就不算', () => {
  const r = prematureClosure({
    attempts: [{ approach: 'ssh_key' }], conclusion: 'ssh key 這條路不通',
    conclusionScope: 'LOCAL',
  });
  assert.equal(r.is_pclose, false);
});

// ---- FP-18 MAS:CT-015 ----
t('CT-015 positive:Ollama 的速度被講成本專案的成果', () => {
  const r = mechanismAttributionSubstitution({
    claimedMechanism: 'Mercury acceleration', actualMechanism: 'Ollama GPU', metricRef: 'm1',
  });
  assert.equal(r.verdict, 'MECHANISM_ATTRIBUTION_SUBSTITUTION');
  assert.match(r.note, /Another system's performance is not this project's progress/);
});

t('CT-015 negative:歸因正確就沒事', () =>
  assert.equal(mechanismAttributionSubstitution({
    claimedMechanism: 'x', actualMechanism: 'x',
  }).is_mas, false));

t('CT-015 low-evidence:沒記錄實際機制就不能判歸因', () => {
  const r = mechanismAttributionSubstitution({ claimedMechanism: 'x' });
  assert.equal(r.verdict, 'MECHANISM_UNKNOWN');
  assert.equal(r.confidence, null);
});

// ---- FP-19 SPI:CT-023 ----
t('CT-023 positive:挑最糟三個推「大部分是雜訊」', () => {
  const r = samplingToPopulationInflation({
    claimText: '大部分都是雜訊',
    samplingContract: { frame: 'all', method: 'manual', n: 3, selection_rule: 'worst 3' },
  });
  assert.equal(r.verdict, 'SAMPLING_TO_POPULATION_INFLATION');
  assert.equal(r.extreme_selection, true);
  assert.equal(r.population_claim_allowed, false);
  assert.equal(r.allowed_phrasing, 'worst-case examples');
});

t('CT-023 negative:隨機抽樣且契約完整,母體宣稱可以成立', () => {
  const r = samplingToPopulationInflation({
    claimText: '大部分都正常',
    samplingContract: { frame: 'all 913', method: 'random', n: 100, selection_rule: 'uniform random' },
  });
  assert.equal(r.is_spi, false);
  assert.equal(r.population_claim_allowed, true);
});

t('CT-023 exclusion:沒有用母體詞彙就不判', () =>
  assert.equal(samplingToPopulationInflation({ claimText: '這三個是最糟的例子' }).is_spi, false));

t('CT-023 low-evidence:有母體宣稱但完全沒有抽樣契約 → 直接不成立', () => {
  const r = samplingToPopulationInflation({ claimText: 'most of them are noise' });
  assert.equal(r.is_spi, true);
  assert.equal(r.population_claim_allowed, false);
});

t('母體詞彙表中英都有', () => {
  assert.ok(POPULATION_TERMS.includes('大部分'));
  assert.ok(POPULATION_TERMS.includes('most'));
});

// ---- FP-21 CAF:CT-038 ----
t('CT-038 positive:更正之後的動作還在依賴被更正掉的東西', () => {
  const r = correctionAbsorptionFailure({
    corrections: [{ id: 'corr1', at: T, invalidates: 'hypothesis_a' }],
    subsequentActions: [{ id: 'act1', at: T + 1000, depends_on: ['hypothesis_a'] }],
  });
  assert.equal(r.verdict, 'CORRECTION_ABSORPTION_FAILURE');
  assert.equal(r.violations.length, 1);
  assert.match(r.note, /received but not absorbed/);
});

t('CT-038 negative:更正之前的動作不算', () => {
  const r = correctionAbsorptionFailure({
    corrections: [{ id: 'corr1', at: T, invalidates: 'h' }],
    subsequentActions: [{ id: 'act1', at: T - 1000, depends_on: ['h'] }],
  });
  assert.equal(r.is_caf, false);
});

t('CT-038 exclusion:後續動作不依賴被更正的東西就沒事', () => {
  const r = correctionAbsorptionFailure({
    corrections: [{ id: 'c', at: T, invalidates: 'h' }],
    subsequentActions: [{ id: 'a', at: T + 1, depends_on: ['other'] }],
  });
  assert.equal(r.is_caf, false);
});

// ---- FP-22 INP:CT-039 ----
t('CT-039 positive:核心前提失效了,依賴它的計畫節點還在 active', () => {
  const r = invalidatedNarrativePersistence({
    planNodes: [
      { id: 'n1', depends_on: ['prereq_a'], status: 'ACTIVE' },
      { id: 'n2', depends_on: ['other'], status: 'ACTIVE' },
    ],
    invalidatedPrerequisites: ['prereq_a'],
    patchesAfterInvalidation: 3,
  });
  assert.equal(r.verdict, 'INVALIDATED_NARRATIVE_PERSISTENCE');
  assert.deepEqual([...r.still_active_dependent_nodes], ['n1']);
  assert.deepEqual([...r.must_lose_authority], ['n1']);
  assert.match(r.note, /patched 3 time/);
});

t('CT-039 negative:依賴的節點已經停用就沒事', () => {
  const r = invalidatedNarrativePersistence({
    planNodes: [{ id: 'n1', depends_on: ['p'], status: 'SUPERSEDED' }],
    invalidatedPrerequisites: ['p'],
  });
  assert.equal(r.is_inp, false);
});

// ---- 專案慣例 ----
t('零依賴:primitives.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/primitives.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('十一個 detector 的共同形狀寫在原始碼開頭', () => {
  const src = readFileSync(new URL('../src/primitives.js', import.meta.url), 'utf8');
  assert.match(src, /某個東西被升到它沒有資格待的位置/);
});

t('每個回傳都帶版本與 severity family', () => {
  const r = ucwe({ unknownState: 'UNKNOWN', resolvingClaim: { id: 'c' } });
  assert.equal(r.version, VERSION);
  assert.equal(r.severity_family, 'A');
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
