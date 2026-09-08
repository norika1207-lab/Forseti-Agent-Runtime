// Forseti v2.0 — P9 Reverse Grill 與 §10 window stage gate。對應 CT-026。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, CHALLENGE_QUESTIONS, FORBIDDEN_QUESTION_PATTERNS, buildChallenge,
  shouldChallenge, crossCheck, WINDOW_STAGES, DEFAULT_SLICE, semanticReadAllowed,
} from '../src/challenge.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const answered = Object.fromEntries(CHALLENGE_QUESTIONS.map((_, i) => [`q${i + 1}`, 'answer']));

t('十個問題,照 §12.1 逐字', () => {
  assert.equal(CHALLENGE_QUESTIONS.length, 10);
  assert.equal(CHALLENGE_QUESTIONS[0], 'State the active objective in one sentence.');
  assert.equal(CHALLENGE_QUESTIONS[9], 'For each claim, provide an independent verifier.');
});

t('FS-CHL-001:拒絕產生「你有沒有飄」這種自我報告題', () => {
  assert.throws(() => buildChallenge({ extraQuestions: ['你有沒有飄?'] }),
    /Refusing to include a self-report question/);
  assert.throws(() => buildChallenge({ extraQuestions: ['Are you still aligned?'] }),
    /no verification power/);
});

t('challenge 一定要被記成 intervention,不然前後觀測會混在一起', () =>
  assert.equal(buildChallenge({}).must_be_logged_as_intervention, true));

t('禁用問法的樣式表有東西,不是空的', () =>
  assert.ok(FORBIDDEN_QUESTION_PATTERNS.length >= 3));

// ---- FS-CHL-003 什麼時候問 ----
t('positive:風險高就問', () =>
  assert.equal(shouldChallenge({ risk: 0.7 }).challenge, true));

t('positive:風險中等但一路惡化也問', () => {
  const r = shouldChallenge({ risk: 0.45, trendDirection: 'WORSENING' });
  assert.equal(r.challenge, true);
  assert.equal(r.reason, 'RISING_RISK');
});

t('negative:風險低就不問,不然 Forseti 自己變成 FP-23', () =>
  assert.equal(shouldChallenge({ risk: 0.1 }).challenge, false));

t('exclusion:剛問過就不再問,連續盤問會改動被觀測的對象', () => {
  const r = shouldChallenge({ risk: 0.9, lastChallengeAgeMs: 1000 });
  assert.equal(r.challenge, false);
  assert.match(r.note, /change the thing being measured/);
});

t('exclusion:確定性矛盾不等門檻,直接問', () => {
  const r = shouldChallenge({ risk: null, hasDeterministicContradiction: true });
  assert.equal(r.challenge, true);
  assert.equal(r.reason, 'DETERMINISTIC_CONTRADICTION');
});

t('low-evidence:沒有風險讀數就不問,沒訊號的打斷只是打斷', () => {
  const r = shouldChallenge({});
  assert.equal(r.challenge, false);
  assert.equal(r.reason, 'NO_RISK_SIGNAL');
});

// ---- FS-CHL-002 / CT-026 ----
t('CT-026 positive:答案再漂亮,也不能蓋過確定性矛盾', () => {
  const r = crossCheck(answered, {
    deterministicContradictions: [{ id: 'x', detail: 'disk says otherwise' }],
  });
  assert.equal(r.verdict, 'CONTRADICTED_BY_EVIDENCE');
  assert.equal(r.risk_reduced, false);
  assert.match(r.note, /does not outrank a deterministic contradiction/);
});

t('CT-026:對得上也不降低風險,只代表還沒發現矛盾', () => {
  const r = crossCheck(answered, {});
  assert.equal(r.verdict, 'CONSISTENT');
  assert.equal(r.risk_reduced, false, '一致不等於證實');
  assert.equal(r.evidence_class, 'DECLARED');
  assert.match(r.note, /does not verify the answers/);
});

t('negative:宣稱存在但驗不到的東西會被列出來', () => {
  const r = crossCheck(answered, {
    claimedArtifacts: ['a.js', 'b.js'], verifiedArtifacts: ['a.js'],
  });
  assert.equal(r.verdict, 'GAPS_FOUND');
  assert.deepEqual([...r.claimed_but_unverified], ['b.js']);
});

t('exclusion:漏答的題目要指名是哪幾題', () => {
  const partial = { ...answered, q5: '', q10: null };
  const r = crossCheck(partial, {});
  assert.deepEqual([...r.unanswered_questions], [5, 10]);
});

t('第七題沒提到真的發生過的更正,會被抓出來', () => {
  const r = crossCheck({ ...answered, q7: '沒有' }, {
    corrections: [{ id: 'corr-42' }],
  });
  assert.deepEqual([...r.unacknowledged_corrections], ['corr-42']);
});

t('low-evidence:沒有 activeGoal 時,目標比對回 null 不硬判', () =>
  assert.equal(crossCheck(answered, {}).goal_statement_matches, null));

// ---- §10 window stages ----
t('四個階段,照 §10 原文', () =>
  assert.deepEqual(WINDOW_STAGES.map((s) => s.stage), ['A', 'B', 'C', 'D']));

t('FS-WIN-001:Stage A/B 不准讀語意', () => {
  for (const s of ['A', 'B']) {
    const r = semanticReadAllowed({ stage: s });
    assert.equal(r.allowed, false, s);
    assert.equal(r.reason, 'EVENT_FIRST');
  }
});

t('FS-WIN-003:Stage C 允許有界切片,而且結果只能是 INFERRED', () => {
  const r = semanticReadAllowed({ stage: 'C', windowTurns: 6 });
  assert.equal(r.allowed, true);
  assert.equal(r.result_epistemic_class, 'INFERRED');
  assert.equal(r.slice.provisional, true);
});

t('FS-WIN-004:Stage D 在 runtime 不准用', () => {
  assert.equal(semanticReadAllowed({ stage: 'D', isRuntime: true }).allowed, false);
  assert.equal(semanticReadAllowed({ stage: 'D', isRuntime: false }).allowed, true);
});

t('FS-WIN-004 的理由寫出來:全 session 讀等於重新製造 context 爆炸', () => {
  const r = semanticReadAllowed({ stage: 'D', isRuntime: true });
  assert.match(r.note, /recreates the context explosion/);
});

t('不認得的階段一律不准', () =>
  assert.equal(semanticReadAllowed({ stage: 'Z' }).allowed, false));

t('切片預設值標成 provisional', () => assert.equal(DEFAULT_SLICE.provisional, true));

// ---- 專案慣例 ----
t('零依賴:challenge.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/challenge.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('「先看矛盾再看答案」的順序理由寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/challenge.js', import.meta.url), 'utf8');
  assert.match(src, /一份好答案會先建立信任/);
});

t('每個回傳都帶版本', () => {
  assert.equal(crossCheck({}, {}).version, VERSION);
  assert.equal(shouldChallenge({}).version, VERSION);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
