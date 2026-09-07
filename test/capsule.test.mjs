// Forseti M1 capsule.js 測試。直接 `node test/capsule.test.mjs` 跑,不需要任何 server。
import assert from 'node:assert/strict';
import {
  createCapsule,
  createBudget,
  createContract,
  previewCapsule,
  acceptCapsule,
  rejectCapsule,
  requestResummarize,
  requoteCapsule,
  quoteCapsule,
  shouldAutoAccept,
  validateReturnShape,
  manualReviewRate,
  blockedRawTokens,
  remainingBudget,
  assertLegalTransition,
  LEGAL_TRANSITIONS,
  CAPSULE_STATES,
  TOKEN_SOURCES,
  DEFAULT_CONFIG,
} from '../src/capsule.js';

let pass = 0;
let fail = 0;
function test(name, fn) {
  try {
    fn();
    pass += 1;
    console.log(`PASS  ${name}`);
  } catch (err) {
    fail += 1;
    console.log(`FAIL  ${name}`);
    console.log(`      ${err.message}`);
  }
}

const T0 = 1757227200000; // 固定 timestamp,測試不碰時鐘

function makeCapsule(over = {}) {
  return createCapsule({
    capsule_id: 'cap-1',
    produced_by: 'w3',
    produced_at: T0,
    task_ref: 'task-1',
    payload_ref: 'sha256:abc',
    summary: 'done: 3 files patched',
    token_cost: 500,
    raw_token_size: 40000,
    contract_ref: 'con-1',
    ...over,
  });
}

function makeBudget(over = {}) {
  return createBudget({
    session_id: 'main',
    window_total: 200000,
    consumed: 50000,
    reserved: 10000,
    measured_at: T0,
    source: TOKEN_SOURCES.PROVIDER_REPORTED,
    ...over,
  });
}

function makeContract(over = {}) {
  return createContract({
    contract_id: 'con-1',
    inputs: { file_globs: ['src/**'], upstream_artifacts: [] },
    outputs: { artifact_ids: ['art-1'] },
    return_shape: null,
    max_return_tokens: 2000,
    ...over,
  });
}

// ---- 資料結構欄位名(文件 3.3,一字不改) ----
test('Capsule 欄位名照 3.3 節,恰好 11 個,一字不改;初始 state 為 PENDING', () => {
  const c = makeCapsule();
  assert.deepEqual(Object.keys(c).sort(), [
    'capsule_id',
    'contract_ref',
    'destination',
    'payload_ref',
    'produced_at',
    'produced_by',
    'raw_token_size',
    'state',
    'summary',
    'task_ref',
    'token_cost',
  ]);
  assert.equal(c.state, CAPSULE_STATES.PENDING);
  assert.equal(c.destination, null);
});

test('ContextBudget 欄位名照 3.3 節,恰好 6 個,一字不改', () => {
  const b = makeBudget();
  assert.deepEqual(Object.keys(b).sort(), [
    'consumed',
    'measured_at',
    'reserved',
    'session_id',
    'source',
    'window_total',
  ]);
});

test('TaskContract 欄位名照 3.3 節,一字不改,含 inputs/outputs 內層', () => {
  const con = makeContract();
  assert.deepEqual(Object.keys(con).sort(), [
    'contract_id',
    'inputs',
    'max_return_tokens',
    'outputs',
    'return_shape',
  ]);
  assert.deepEqual(Object.keys(con.inputs).sort(), ['file_globs', 'upstream_artifacts']);
  assert.deepEqual(Object.keys(con.outputs), ['artifact_ids']);
});

// ---- 誠實條款:source ----
test('ContextBudget.source 必填,只認 PROVIDER_REPORTED / ESTIMATED,不給或亂給就拋錯', () => {
  assert.throws(() => makeBudget({ source: undefined }));
  assert.throws(() => makeBudget({ source: 'GUESSED' }));
  const est = makeBudget({ source: TOKEN_SOURCES.ESTIMATED });
  assert.equal(est.source, 'ESTIMATED');
  const real = makeBudget({ source: TOKEN_SOURCES.PROVIDER_REPORTED });
  assert.equal(real.source, 'PROVIDER_REPORTED');
});

// ---- 狀態機:合法路徑 ----
test('合法全程:PENDING→PREVIEWED→SUMMARIZED_AGAIN→PENDING→PREVIEWED→ACCEPTED', () => {
  const budget = makeBudget();
  const contract = makeContract();
  let { capsule } = previewCapsule(makeCapsule(), budget);
  assert.equal(capsule.state, 'PREVIEWED');
  capsule = requestResummarize(capsule);
  assert.equal(capsule.state, 'SUMMARIZED_AGAIN');
  capsule = requoteCapsule(capsule, {
    capsule_id: 'cap-1b',
    summary: 'compressed',
    token_cost: 200,
    produced_at: T0 + 1000,
  });
  assert.equal(capsule.state, 'PENDING');
  assert.equal(capsule.capsule_id, 'cap-1b');
  assert.equal(capsule.token_cost, 200);
  ({ capsule } = previewCapsule(capsule, budget));
  const res = acceptCapsule(capsule, budget, contract);
  assert.equal(res.capsule.state, 'ACCEPTED');
});

test('PREVIEWED→REJECTED 合法,payload_ref 不動、預算不變(原始輸出留在外面)', () => {
  const budget = makeBudget();
  const { capsule } = previewCapsule(makeCapsule(), budget);
  const rejected = rejectCapsule(capsule);
  assert.equal(rejected.state, 'REJECTED');
  assert.equal(rejected.payload_ref, 'sha256:abc');
  assert.equal(remainingBudget(budget), 140000); // 預算物件根本沒被動過
});

// ---- 狀態機:非法轉移必須拋錯 ----
test('非法轉移一律拋錯,不靜默允許', () => {
  const budget = makeBudget();
  const pending = makeCapsule();
  // PENDING → REJECTED 不在圖上
  assert.throws(() => rejectCapsule(pending), /非法/);
  // PENDING → SUMMARIZED_AGAIN 不在圖上
  assert.throws(() => requestResummarize(pending), /非法/);
  // ACCEPTED 是終態
  const { capsule: previewed } = previewCapsule(pending, budget);
  const { capsule: accepted } = acceptCapsule(previewed, budget, makeContract());
  assert.throws(() => previewCapsule(accepted, budget), /非法/);
  assert.throws(() => rejectCapsule(accepted), /非法/);
  // REJECTED 是終態
  const rejected = rejectCapsule(previewed);
  assert.throws(() => requestResummarize(rejected), /非法/);
  // SUMMARIZED_AGAIN 只能回 PENDING
  const again = requestResummarize(previewed);
  assert.throws(() => rejectCapsule(again), /非法/);
  // 轉移表本身照 3.4 的圖
  assert.deepEqual(LEGAL_TRANSITIONS.PENDING, ['PREVIEWED', 'ACCEPTED']);
  assert.deepEqual(LEGAL_TRANSITIONS.PREVIEWED, ['ACCEPTED', 'SUMMARIZED_AGAIN', 'REJECTED']);
  assert.deepEqual(LEGAL_TRANSITIONS.SUMMARIZED_AGAIN, ['PENDING']);
  assert.deepEqual(LEGAL_TRANSITIONS.ACCEPTED, []);
  assert.deepEqual(LEGAL_TRANSITIONS.REJECTED, []);
  assert.throws(() => assertLegalTransition('ACCEPTED', 'PENDING'), /非法/);
});

// ---- 自動放行(文件 3.4) ----
test('自動放行:token_cost <= 2% window 且 shape 通過 → PENDING 直接 ACCEPTED', () => {
  const budget = makeBudget(); // window 200000,2% = 4000
  const contract = makeContract({ max_return_tokens: 5000 }); // 上限要蓋過 cost,shape 才會過
  const cheap = makeCapsule({ token_cost: 3000 });
  assert.equal(shouldAutoAccept(cheap, budget, contract), true);
  const { capsule, budget: after } = acceptCapsule(cheap, budget, contract);
  assert.equal(capsule.state, 'ACCEPTED');
  assert.equal(after.reserved, 10000 + 3000); // 進 reserved,不假裝已計入 consumed
});

test('超過自動閾值的 PENDING 膠囊直接 accept 要拋錯,必須走 preview', () => {
  const budget = makeBudget();
  const contract = makeContract({ max_return_tokens: 99999 });
  const costly = makeCapsule({ token_cost: 4001 }); // 2% = 4000
  assert.equal(shouldAutoAccept(costly, budget, contract), false);
  assert.throws(() => acceptCapsule(costly, budget, contract), /自動放行/);
});

test('閾值可設定:同一顆膠囊,ratio 調到 0.05 就過,調到 0.001 就不過', () => {
  const budget = makeBudget();
  const contract = makeContract({ max_return_tokens: 99999 });
  const c = makeCapsule({ token_cost: 4001 });
  assert.equal(shouldAutoAccept(c, budget, contract, { auto_accept_ratio: 0.05 }), true);
  const tiny = makeCapsule({ token_cost: 300 });
  assert.equal(shouldAutoAccept(tiny, budget, contract, { auto_accept_ratio: 0.001 }), false);
});

test('return_shape 驗證不過就不自動放行,即使 token 很便宜', () => {
  const budget = makeBudget();
  // token_cost 500 > max_return_tokens 400:超過硬上限,必須先摘要
  const conTight = makeContract({ max_return_tokens: 400 });
  const c = makeCapsule({ token_cost: 500 });
  const check = validateReturnShape(c, conTight);
  assert.equal(check.ok, false);
  assert.match(check.reasons.join(' '), /max_return_tokens/);
  assert.equal(shouldAutoAccept(c, budget, conTight), false);
  // JSON shape:summary 不是 JSON → 不過;補齊必要欄位 → 過
  const conJson = makeContract({
    return_shape: { kind: 'json', required_fields: ['status', 'files'] },
  });
  const bad = makeCapsule({ summary: 'not json' });
  assert.equal(validateReturnShape(bad, conJson).ok, false);
  const good = makeCapsule({ summary: '{"status":"ok","files":3}' });
  assert.equal(validateReturnShape(good, conJson).ok, true);
  assert.equal(shouldAutoAccept(good, budget, conJson), true);
});

// ---- 報價 ----
test('報價欄位照 3.5 節 preview 輸出;budget_before/after 算對', () => {
  const budget = makeBudget(); // remaining = 200000-50000-10000 = 140000
  const c = makeCapsule({ token_cost: 500, raw_token_size: 40000 });
  const q = quoteCapsule(c, budget);
  assert.deepEqual(Object.keys(q).sort(), [
    'budget_after',
    'budget_before',
    'raw_token_size',
    'token_cost',
    'would_trigger_compact',
  ]);
  assert.equal(q.budget_before, 140000);
  assert.equal(q.budget_after, 139500);
  assert.equal(q.would_trigger_compact, false);
});

test('would_trigger_compact:接受後剩餘掉到 20% 以下為 true;門檻可調', () => {
  const budget = makeBudget({ consumed: 150000, reserved: 0 }); // remaining 50000 = 25%
  const c = makeCapsule({ token_cost: 15000 }); // 接受後 35000 = 17.5%
  assert.equal(quoteCapsule(c, budget).would_trigger_compact, true);
  assert.equal(
    quoteCapsule(c, budget, { compact_threshold: 0.1 }).would_trigger_compact,
    false,
  );
});

// ---- 3.8 雷二:人工放行比例可量測 ----
test('manualReviewRate:算出照目前閾值有幾成要人工;調閾值數字跟著動', () => {
  const budget = makeBudget();
  const contract = makeContract({ max_return_tokens: 99999 });
  const contractsById = { 'con-1': contract };
  // 10 顆:3 顆 3000(≤2%=4000 自動),7 顆 8000(要人工)
  const capsules = [
    ...Array.from({ length: 3 }, (_, i) => makeCapsule({ capsule_id: `a${i}`, token_cost: 3000 })),
    ...Array.from({ length: 7 }, (_, i) => makeCapsule({ capsule_id: `m${i}`, token_cost: 8000 })),
  ];
  const r = manualReviewRate(capsules, { budget, contractsById });
  assert.equal(r.total, 10);
  assert.equal(r.auto, 3);
  assert.equal(r.manual, 7);
  assert.equal(r.manual_rate, 0.7);
  // 放寬到 5%(=10000)後全部自動
  const loose = manualReviewRate(capsules, {
    budget,
    contractsById,
    config: { auto_accept_ratio: 0.05 },
  });
  assert.equal(loose.manual_rate, 0);
});

test('manualReviewRate:查不到契約的膠囊算人工並在 missing_contract 如實計數', () => {
  const budget = makeBudget();
  const capsules = [makeCapsule({ contract_ref: 'con-ghost', token_cost: 100 })];
  const r = manualReviewRate(capsules, { budget, contractsById: {} });
  assert.equal(r.manual, 1);
  assert.equal(r.missing_contract, 1);
});

// ---- 擋掉的原始 token(3.7 驗收四的核心計算) ----
test('blockedRawTokens:ACCEPTED 擋 raw−cost,REJECTED 擋整個 raw,未定案不計', () => {
  const budget = makeBudget();
  const contract = makeContract();
  const { capsule: p1 } = previewCapsule(makeCapsule({ raw_token_size: 40000, token_cost: 500 }), budget);
  const { capsule: acc } = acceptCapsule(p1, budget, contract);
  const { capsule: p2 } = previewCapsule(
    makeCapsule({ capsule_id: 'cap-2', raw_token_size: 30000 }),
    budget,
  );
  const rej = rejectCapsule(p2);
  const pending = makeCapsule({ capsule_id: 'cap-3', raw_token_size: 99999 });
  assert.equal(blockedRawTokens([acc, rej, pending]), 39500 + 30000);
});

// ---- 不可變 ----
test('膠囊與預算物件皆凍結,直接竄改狀態會拋錯', () => {
  const c = makeCapsule();
  assert.throws(() => {
    'use strict';
    c.state = 'ACCEPTED';
  });
  const b = makeBudget();
  assert.throws(() => {
    'use strict';
    b.source = 'PROVIDER_REPORTED_FAKE';
  });
});

test('DEFAULT_CONFIG 預設 2%,且是預設不是硬編碼(每個 API 都吃 config)', () => {
  assert.equal(DEFAULT_CONFIG.auto_accept_ratio, 0.02);
  // shouldAutoAccept / quoteCapsule / acceptCapsule / manualReviewRate 都驗過可帶 config,
  // 這裡再釘一次 acceptCapsule 帶寬鬆 config 可讓原本要人工的膠囊自動過
  const budget = makeBudget();
  const contract = makeContract({ max_return_tokens: 99999 });
  const c = makeCapsule({ token_cost: 4001 });
  const { capsule } = acceptCapsule(c, budget, contract, { auto_accept_ratio: 0.05 });
  assert.equal(capsule.state, 'ACCEPTED');
});

console.log('');
console.log(`結果:${pass} 通過,${fail} 失敗,共 ${pass + fail} 條`);
if (fail > 0) process.exit(1);
