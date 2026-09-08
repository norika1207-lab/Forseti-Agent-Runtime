// Forseti v2.0 — P4 Verifier Registry。
// 規格 §22.4 FP-04 VMI、§23.4、§28.2、CT-016。
// 這一份的核心案例是 CASE-E:grep 找不到 hex bytes,回的必須是「我答不了」。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, OUTCOMES, createContract, coverageOf, verify,
  validityConfidence, capConfidence, BUILTIN_CONTRACTS,
} from '../src/verifier.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('四個結果狀態,UNKNOWN_COVERAGE 是其中一個一等公民', () =>
  assert.deepEqual([...OUTCOMES], ['PASS', 'FAIL', 'UNKNOWN_COVERAGE', 'PRECONDITION_UNMET']));

// ---- 契約建構 ----
t('沒有 method_id 的驗證器不准存在,不然事後審不了', () =>
  assert.throws(() => createContract({ semanticsNotChecked: [] }), /methodId is required/));

t('semantics_not_checked 必填,留白等於偷偷宣稱全覆蓋', () => {
  assert.throws(() => createContract({ methodId: 'x' }), /must declare semantics_not_checked/);
  assert.throws(() => createContract({ methodId: 'x' }), /grep-vs-hex/);
  assert.ok(createContract({ methodId: 'x', semanticsNotChecked: [] }));
});

t('契約是凍結的', () =>
  assert.ok(Object.isFrozen(createContract({ methodId: 'x', semanticsNotChecked: [] }))));

// ---- CT-016 這一份的主案例 ----
t('CT-016 positive:grep 對 hex 表示法沒 coverage,0 hit 不准反駁 claim', () => {
  const r = verify(BUILTIN_CONTRACTS.grep_string, {
    rawOutcome: 'FAIL',
    targetType: 'file',
    representation: 'hex_bytes',
    semanticsRequired: ['literal_substring_present'],
    preconditionsMet: ['target_is_text'],
  });
  assert.equal(r.outcome, 'UNKNOWN_COVERAGE');
  assert.equal(r.may_refute_claim, false, '這個 false 就是 CT-016');
  assert.equal(r.raw_outcome, 'FAIL', '原始結果要留著,但不生效');
  assert.match(r.reason, /MUST NOT refute the claim/);
});

t('CT-016 negative:同一個 grep 對 utf8 文字是有效的,FAIL 就是 FAIL', () => {
  const r = verify(BUILTIN_CONTRACTS.grep_string, {
    rawOutcome: 'FAIL',
    targetType: 'file',
    representation: 'utf8_text',
    semanticsRequired: ['literal_substring_present'],
    preconditionsMet: ['target_is_text'],
  });
  assert.equal(r.outcome, 'FAIL');
  assert.equal(r.may_refute_claim, true);
});

t('CT-016 exclusion:要求的語意超出契約,即使表示法對也不給結論', () => {
  const r = verify(BUILTIN_CONTRACTS.grep_string, {
    rawOutcome: 'PASS',
    targetType: 'file',
    representation: 'utf8_text',
    semanticsRequired: ['literal_substring_present', 'semantic_equivalence'],
    preconditionsMet: ['target_is_text'],
  });
  assert.equal(r.outcome, 'UNKNOWN_COVERAGE');
  assert.match(r.reason, /Unchecked semantics: semantic_equivalence/);
});

t('CT-016 low-evidence:前提沒滿足,連 coverage 都不用談', () => {
  const r = verify(BUILTIN_CONTRACTS.grep_string, {
    rawOutcome: 'FAIL',
    targetType: 'file',
    representation: 'utf8_text',
    semanticsRequired: ['literal_substring_present'],
    preconditionsMet: [],
  });
  assert.equal(r.outcome, 'PRECONDITION_UNMET');
  assert.equal(r.may_refute_claim, false);
});

t('覆蓋到了但沒給有效結果,也是 UNKNOWN_COVERAGE,不是 PASS', () => {
  const r = verify(BUILTIN_CONTRACTS.http_status, {
    rawOutcome: undefined,
    targetType: 'url',
    representation: 'http',
    semanticsRequired: ['status_code'],
  });
  assert.equal(r.outcome, 'UNKNOWN_COVERAGE');
});

// ---- coverage 細節 ----
t('部分覆蓋不等於大致可以,fully_covers 要全中才 true', () => {
  const c = coverageOf(BUILTIN_CONTRACTS.file_exists_nonempty, {
    targetType: 'file',
    representation: 'filesystem',
    semanticsRequired: ['existence', 'content_validity'],
    preconditionsMet: ['path_resolvable'],
  });
  assert.equal(c.fully_covers, false);
  assert.deepEqual([...c.semantics_uncovered], ['content_validity']);
  assert.equal(c.contract_coverage, 0.5);
});

t('§29 HTTP 200 不等於引用內容正確,契約自己講了', () =>
  assert.ok(BUILTIN_CONTRACTS.http_status.semantics_not_checked.includes('citation_title_match')));

t('CASE-E 那一刀寫在 grep 契約的已知假陰性裡', () =>
  assert.ok(BUILTIN_CONTRACTS.grep_string.false_negative_known_cases
    .some((c) => /CASE-E/.test(c))));

t('FP-20:process 活著不等於服務健康,契約自己講了', () =>
  assert.ok(BUILTIN_CONTRACTS.process_liveness.semantics_not_checked.includes('service_healthy')));

// ---- §23.4 validity confidence ----
t('沒人測過的驗證器,validity 是 null 不是 1', () => {
  const v = validityConfidence(BUILTIN_CONTRACTS.grep_string, {
    scope: { targetType: 'file', representation: 'utf8_text', preconditionsMet: ['target_is_text'] },
  });
  assert.equal(v.value, null);
  assert.match(v.note, /does not earn a perfect score by/);
});

t('三個因子都給了才算得出 validity', () => {
  const v = validityConfidence(BUILTIN_CONTRACTS.http_status, {
    scope: { targetType: 'url', representation: 'http' },
    verifierTestQuality: 0.8,
  });
  assert.equal(v.value, 0.8);
});

t('前提沒滿足會拉低 validity,不是直接歸零', () => {
  const v = validityConfidence(BUILTIN_CONTRACTS.grep_string, {
    scope: { targetType: 'file', representation: 'utf8_text', preconditionsMet: [] },
    verifierTestQuality: 1,
  });
  assert.equal(v.precondition_satisfaction, 0);
  assert.equal(v.value, 0);
});

// ---- §28.2 上限規則 ----
t('claim confidence 被 verifier validity 蓋住', () => {
  const v = validityConfidence(BUILTIN_CONTRACTS.http_status, {
    scope: { targetType: 'url', representation: 'http' },
    verifierTestQuality: 0.5,
  });
  const c = capConfidence(0.95, v);
  assert.equal(c.value, 0.5);
  assert.equal(c.capped, true);
});

t('validity 未知時,claim confidence 直接不能主張', () => {
  const c = capConfidence(0.99, { value: null });
  assert.equal(c.value, null);
  assert.equal(c.capped, true);
  assert.match(c.reason, /cannot be asserted at all/);
});

t('本來就低於上限的話不動它', () => {
  const c = capConfidence(0.2, { value: 0.8 });
  assert.equal(c.value, 0.2);
  assert.equal(c.capped, false);
});

// ---- 專案慣例 ----
t('零依賴:verifier.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/verifier.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('每個回傳都帶版本', () => {
  assert.equal(coverageOf(BUILTIN_CONTRACTS.grep_string, {}).version, VERSION);
  assert.equal(capConfidence(1, { value: 1 }).version, VERSION);
});

t('「錯的驗證器比沒有更危險」這句話留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/verifier.js', import.meta.url), 'utf8');
  assert.match(src, /比沒有驗證器更危險/);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
