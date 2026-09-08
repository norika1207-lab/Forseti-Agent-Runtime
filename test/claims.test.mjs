// Forseti v2.0 — P3 Claim & Scope Engine。
// 規格 §22.2 FP-02、§22.3 FP-03、§22.19、§23.2、§23.3。
// 對應 CT-003、CT-004、CT-017、CT-020。
// 每個 primitive 依 FS-CAL-003 至少要有 positive / negative / exclusion / low-evidence。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, SCOPE_DIMENSIONS, createScope, scopeCoverage,
  SCOPE_EXPANDING_TERMS, scopeExpandingTerms, detectScopeInflation,
  compositeEvidencePromotion, LINEAGE_STAGES, detectProvenanceCollapse,
  provenanceIntegrity, semanticCoverageInflation, evidenceScopeCoverage,
  GATE_RESULTS, GATED_CLAIM_TYPES, postClaimGate,
} from '../src/claims.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('七個 scope 維度,照 §22.2 原文', () =>
  assert.deepEqual([...SCOPE_DIMENSIONS],
    ['environment', 'actor', 'stage', 'resource', 'time', 'coverage', 'verifier_method']));

t('沒給的維度是 null,不是空字串', () => {
  const s = createScope({ environment: 'headless' });
  assert.equal(s.environment, 'headless');
  assert.equal(s.actor, null);
});

// ---- scope coverage ----
t('宣稱沒宣告任何 scope 時,覆蓋率是 null 不是 1', () => {
  const c = scopeCoverage(createScope({ environment: 'headless' }), createScope({}));
  assert.equal(c.coverage, null);
  assert.match(c.note, /not complete/);
});

t('證據沒宣告某維度,算沒覆蓋,不算不知道', () => {
  const c = scopeCoverage(createScope({}), createScope({ environment: 'ios_app' }));
  assert.equal(c.coverage, 0);
  assert.deepEqual([...c.undeclared], ['environment']);
});

// ---- FP-02 ESI:CT-003 ----
t('CT-003 positive:headless 跑通,宣稱 owner App 端到端 → ESI 為正', () => {
  const claim = {
    text: '已驗證,你打開 App 就會動,端到端沒問題',
    scope: createScope({ environment: 'ios_app', stage: 'end_to_end' }),
  };
  const r = detectScopeInflation(claim, [
    createScope({ environment: 'headless_cdp', stage: 'end_to_end' }),
  ]);
  assert.equal(r.verdict, 'SCOPE_INFLATION');
  assert.equal(r.esi, 0.5);
  assert.deepEqual([...r.uncovered_dimensions], ['environment']);
  assert.equal(r.must_mark_unverified, true, 'FS-DET-ESI-001');
  assert.ok(r.scope_expanding_terms.length > 0);
});

t('CT-003 negative:證據環境與宣稱相同就不算膨脹', () => {
  const claim = { text: '已驗證', scope: createScope({ environment: 'ios_app' }) };
  const r = detectScopeInflation(claim, [createScope({ environment: 'ios_app' })]);
  assert.equal(r.verdict, 'COVERED');
  assert.equal(r.esi, 0);
  assert.equal(r.must_mark_unverified, false);
});

t('CT-003 exclusion:完全沒有證據時是 NO_EVIDENCE,不是 ESI=1', () => {
  const r = detectScopeInflation({ text: '全部都好了', scope: createScope({ environment: 'x' }) }, []);
  assert.equal(r.verdict, 'NO_EVIDENCE');
  assert.equal(r.esi, null);
  assert.match(r.note, /not an inflation finding/);
});

t('CT-003 low-evidence:宣稱沒 scope 時回 UNSCOPED_CLAIM,不硬給分數', () => {
  const r = detectScopeInflation({ text: '好了' }, [createScope({ environment: 'x' })]);
  assert.equal(r.verdict, 'UNSCOPED_CLAIM');
  assert.equal(r.esi, null);
});

t('多份部分覆蓋不會自動加成全覆蓋,取最好的那一份', () => {
  const claim = { scope: createScope({ environment: 'ios_app', stage: 'end_to_end' }) };
  const r = detectScopeInflation(claim, [
    createScope({ environment: 'ios_app' }),
    createScope({ stage: 'end_to_end' }),
  ]);
  assert.equal(r.esi, 0.5, '兩份各覆蓋一半,不等於全部覆蓋');
});

t('scope-expanding 用語表裡有 FS-DET-ESI-001 點名的那幾個', () => {
  for (const term of ['端到端', '全部', '已解決', '已驗證']) {
    assert.ok(SCOPE_EXPANDING_TERMS.includes(term), term);
  }
  assert.deepEqual(scopeExpandingTerms('這個已驗證,而且是端到端'), ['端到端', '已驗證']);
});

// ---- CT-004 composite ----
t('CT-004 positive:兩段各自通過但沒有跨接縫的證據,不得升為整體', () => {
  const claim = { scope: createScope({ stage: ['device', 'app'] }) };
  const r = compositeEvidencePromotion(claim, [
    createScope({ stage: ['device'] }),
    createScope({ stage: ['app'] }),
  ]);
  assert.equal(r.verdict, 'COMPOSITE_PROMOTION');
  assert.equal(r.may_promote_to_whole, false);
  assert.match(r.note, /not the sum of parts/);
});

t('CT-004 negative:有一份證據橫跨兩段就可以', () => {
  const claim = { scope: createScope({ stage: ['device', 'app'] }) };
  const r = compositeEvidencePromotion(claim, [createScope({ stage: ['device', 'app'] })]);
  assert.equal(r.verdict, 'OK');
  assert.equal(r.may_promote_to_whole, true);
});

t('CT-004 exclusion:宣稱只跨一段就沒有接縫可談', () => {
  const r = compositeEvidencePromotion({ scope: createScope({ stage: 'app' }) }, []);
  assert.equal(r.verdict, 'NOT_APPLICABLE');
});

t('CT-004 low-evidence:某一段根本沒證據時不報 composite,那是別的問題', () => {
  const claim = { scope: createScope({ stage: ['device', 'app'] }) };
  const r = compositeEvidencePromotion(claim, [createScope({ stage: ['device'] })]);
  assert.equal(r.verdict, 'OK');
  assert.equal(r.stages.find((s) => s.stage === 'app').covered, false);
});

// ---- FP-03 PC:CT-017 ----
t('CT-017 positive:589 條別人查的,用第一人稱說成親驗', () => {
  const r = detectProvenanceCollapse(
    { text: '我親自逐一確認了 589 條引用' },
    { lineage: { observing_agent: 'sub-agent-7', user_facing_claim: 'main' }, ownReceipts: [] },
  );
  assert.equal(r.verdict, 'PROVENANCE_COLLAPSE');
  assert.equal(r.delegated_but_claimed_first_hand, true);
  assert.equal(r.own_receipt_count, 0);
  assert.ok(r.first_person_terms.length > 0);
});

t('CT-017 negative:老實說是 sub-agent 查的就不算', () => {
  const r = detectProvenanceCollapse(
    { text: 'sub-agent 回報了 589 條引用' },
    { lineage: { observing_agent: 'sub-agent-7', user_facing_claim: 'main' } },
  );
  assert.equal(r.verdict, 'OK');
});

t('CT-017 exclusion:主 agent 自己有 receipt 就不是抹除', () => {
  const r = detectProvenanceCollapse(
    { text: '我親自確認過' },
    {
      lineage: { observing_agent: 'sub', user_facing_claim: 'main' },
      ownReceipts: [{ resource_locator: 'a.js' }],
    },
  );
  assert.equal(r.verdict, 'OK');
});

t('CT-017 low-evidence:委派了但沒宣告 provenance,標 MISSING 不標 COLLAPSE', () => {
  const r = detectProvenanceCollapse(
    { text: '引用都查過了' },
    { lineage: { user_facing_claim: 'main' } },
  );
  assert.equal(r.verdict, 'OK', '沒有 observing_agent 就不構成委派事實');
});

t('lineage 四階段照 §22.3 原文', () =>
  assert.deepEqual([...LINEAGE_STAGES],
    ['source_actor', 'observing_agent', 'summarizing_agent', 'user_facing_claim']));

t('§23.3 provenance integrity:沒有可追溯來源的 material claim 會拉低分數', () => {
  const r = provenanceIntegrity([
    { material: true, lineage: { observing_agent: 'a' } },
    { material: true, lineage: {} },
  ]);
  assert.equal(r.value, 0.5);
});

t('§23.3 沒有 material claim 時是 null,而且說明「不是乾淨是沒紀錄」', () => {
  const r = provenanceIntegrity([]);
  assert.equal(r.value, null);
  assert.match(r.note, /no record/);
});

// ---- FP-07 SCI:CT-020 ----
t('CT-020 positive:宣稱逐條核對 589,實際 25 → 覆蓋率用數字講出來', () => {
  const r = semanticCoverageInflation({
    claimedCount: 589, verifiedCount: 25, claimText: '逐條核對完畢',
  });
  assert.equal(r.verdict, 'SEMANTIC_COVERAGE_INFLATION');
  assert.ok(Math.abs(r.coverage_ratio - 25 / 589) < 1e-9);
  assert.ok(r.coverage_claim_terms.includes('逐條'));
});

t('CT-020 negative:數量對得上就不算膨脹', () => {
  const r = semanticCoverageInflation({
    claimedCount: 30, verifiedCount: 30, claimText: '全部核對完畢',
  });
  assert.equal(r.verdict, 'OK');
  assert.equal(r.coverage_ratio, 1);
});

t('CT-020 exclusion:沒有用 coverage 用語就不判,只給數字', () => {
  const r = semanticCoverageInflation({
    claimedCount: 589, verifiedCount: 25, claimText: '我看了一部分',
  });
  assert.equal(r.verdict, 'OK');
  assert.ok(r.coverage_ratio < 0.1, '數字照樣算出來,只是不下判定');
});

t('CT-020 low-evidence:任一個數字拿不到就 INDETERMINATE,不准假設完整', () => {
  const r = semanticCoverageInflation({ claimedCount: 589, claimText: '逐條核對' });
  assert.equal(r.verdict, 'INDETERMINATE');
  assert.equal(r.coverage_ratio, null);
  assert.match(r.note, /MUST NOT be assumed complete/);
});

t('0.9 門檻自己說沒校準過', () => {
  const r = semanticCoverageInflation({ claimedCount: 10, verifiedCount: 10, claimText: '全部' });
  assert.equal(r.threshold_uncalibrated, 0.9);
});

// ---- §23.2 ----
t('§23.2 coverage 低時要明說「整體完成」的信心必須跟著降', () => {
  const r = evidenceScopeCoverage([
    { material: true, status: 'VERIFIED', weight: 1 },
    { material: true, status: 'UNVERIFIED', weight: 3 },
  ]);
  assert.equal(r.value, 0.25);
  assert.match(r.note, /confidence in "the whole thing is done" MUST fall/);
});

// ---- §22.19 Post-Claim Gate ----
t('五個閘門結果,照 §22.19 原文', () =>
  assert.deepEqual([...GATE_RESULTS],
    ['VERIFIED', 'PARTIAL', 'UNVERIFIED', 'REFUTED', 'CRITICAL_INTEGRITY_INCIDENT']));

t('FS-PCG-001:被點名的五類 claim 沒綁驗證器就進不了 canonical state', () => {
  for (const type of GATED_CLAIM_TYPES) {
    const r = postClaimGate(
      { type, text: '做完了', scope: createScope({ environment: 'x' }) },
      { evidenceScopes: [createScope({ environment: 'x' })] },
    );
    assert.equal(r.result, 'UNVERIFIED', type);
    assert.equal(r.may_enter_canonical_state, false, type);
  }
});

t('SEF 硬矛盾直接開 CRITICAL,不經過任何加權平均', () => {
  const r = postClaimGate(
    { type: 'TOOL_OUTPUT', text: 'tool 回報了注入攻擊' },
    { sefResult: { hard_contradiction: true, sef_subtype: 'SEF-TOOL' } },
  );
  assert.equal(r.result, 'CRITICAL_INTEGRITY_INCIDENT');
  assert.equal(r.may_enter_canonical_state, false);
  assert.match(r.note, /bypasses.*thermometer/s);
});

t('沒查 SEF 的話要講出來,不准讓沉默看起來像通過', () => {
  const r = postClaimGate(
    { type: 'OTHER', scope: createScope({ environment: 'x' }) },
    { evidenceScopes: [createScope({ environment: 'x' })], verifierResult: { outcome: 'PASS' } },
  );
  assert.equal(r.sef_checked, false);
  assert.match(r.note, /not evidence of integrity/);
});

t('驗證器 FAIL 且有資格反駁 → REFUTED', () => {
  const r = postClaimGate({ type: 'OTHER' }, {
    verifierResult: { outcome: 'FAIL', may_refute_claim: true },
  });
  assert.equal(r.result, 'REFUTED');
});

t('驗證器 FAIL 但沒 coverage 資格 → 不得 REFUTED', () => {
  const r = postClaimGate({ type: 'OTHER', scope: createScope({ environment: 'x' }) }, {
    evidenceScopes: [createScope({ environment: 'x' })],
    verifierResult: { outcome: 'UNKNOWN_COVERAGE', may_refute_claim: false },
  });
  assert.notEqual(r.result, 'REFUTED');
});

t('scope 膨脹 → PARTIAL,而且要列出沒過的那一半', () => {
  const r = postClaimGate(
    { type: 'OTHER', text: '端到端都好了', scope: createScope({ environment: 'ios', stage: 'e2e' }) },
    {
      evidenceScopes: [createScope({ environment: 'headless', stage: 'e2e' })],
      verifierResult: { outcome: 'PASS' },
    },
  );
  assert.equal(r.result, 'PARTIAL');
  assert.deepEqual([...r.unverified_scope], ['environment']);
});

t('provenance collapse → UNVERIFIED,即使驗證器說 PASS', () => {
  const r = postClaimGate(
    {
      type: 'OTHER', text: '我親自驗過了',
      scope: createScope({ environment: 'x' }),
      lineage: { observing_agent: 'sub', user_facing_claim: 'main' },
    },
    {
      evidenceScopes: [createScope({ environment: 'x' })],
      verifierResult: { outcome: 'PASS' },
    },
  );
  assert.equal(r.result, 'UNVERIFIED');
});

t('全部過關才 VERIFIED,而且只有這時候能進 canonical state', () => {
  const r = postClaimGate(
    { type: 'OTHER', text: '寫好了', scope: createScope({ environment: 'x' }) },
    {
      evidenceScopes: [createScope({ environment: 'x' })],
      verifierResult: { outcome: 'PASS' },
      sefResult: { hard_contradiction: false },
    },
  );
  assert.equal(r.result, 'VERIFIED');
  assert.equal(r.may_enter_canonical_state, true);
});

// ---- 專案慣例 ----
t('零依賴:claims.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/claims.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('每個回傳都帶版本', () => {
  assert.equal(detectScopeInflation({}, []).version, VERSION);
  assert.equal(postClaimGate({}, {}).version, VERSION);
});

t('回傳都是凍結的', () => {
  assert.ok(Object.isFrozen(postClaimGate({}, {})));
  assert.ok(Object.isFrozen(detectProvenanceCollapse({}, {})));
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
