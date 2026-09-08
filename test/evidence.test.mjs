// Forseti v2.0 — P0 術語凍結 + P2 Evidence Receipt。
// 規格來源 docs/spec-v2.0.md §2/§3/§4。
// 每個斷言都指回一條 FS- 編號,對不上規格的斷言不該存在。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, EVIDENCE_CLASSES, CLASS_AUTHORITY, UNKNOWN, INDETERMINATE,
  canPromote, intentionalityRecord,
  RECEIPT_FIELDS, createReceipt, existedAt, reconcileHistorical,
} from '../src/evidence.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;

// ---- §3.1 evidence classes ----
t('四個 evidence class,名稱與順序照規格書', () =>
  assert.deepEqual([...EVIDENCE_CLASSES], ['OBSERVED', 'DECLARED', 'INFERRED', 'MISSING']));

t('只有 OBSERVED 能自證,也只有它能反駁 claim', () => {
  assert.equal(CLASS_AUTHORITY.OBSERVED.can_self_validate, true);
  assert.equal(CLASS_AUTHORITY.OBSERVED.can_refute_claim, true);
  for (const c of ['DECLARED', 'INFERRED', 'MISSING']) {
    assert.equal(CLASS_AUTHORITY[c].can_self_validate, false, c);
    assert.equal(CLASS_AUTHORITY[c].can_refute_claim, false, c);
  }
});

t('UNKNOWN 與 INDETERMINATE 是兩件事,不可以合併', () => {
  assert.notEqual(UNKNOWN.state, INDETERMINATE.state);
  assert.equal(UNKNOWN.value, null);
  assert.equal(INDETERMINATE.value, null);
});

// ---- FS-EVD-002 自白不得自我升級 ----
t('positive:自白沒有外部佐證,不准升成 OBSERVED', () => {
  const r = canPromote({ evidenceClass: 'DECLARED', target: 'OBSERVED' });
  assert.equal(r.allowed, false);
  assert.equal(r.resulting_class, 'DECLARED');
  assert.match(r.reason, /does not raise its own evidence class/);
});

t('negative:有獨立 OBSERVED 佐證就可以升', () => {
  const r = canPromote({
    evidenceClass: 'DECLARED',
    target: 'OBSERVED',
    corroboration: [{ evidence_class: 'OBSERVED', ref: 'fs:stat' }],
  });
  assert.equal(r.allowed, true);
  assert.equal(r.resulting_class, 'OBSERVED');
});

t('exclusion:佐證本身也是 DECLARED 的話不算數', () => {
  const r = canPromote({
    evidenceClass: 'DECLARED',
    target: 'OBSERVED',
    corroboration: [{ evidence_class: 'DECLARED', ref: '另一份自白' }],
  });
  assert.equal(r.allowed, false, '兩份自白不會變成一份觀測');
});

t('low-evidence:class 名字不認得就拒絕,不猜', () => {
  const r = canPromote({ evidenceClass: 'PROBABLY_FINE', target: 'OBSERVED' });
  assert.equal(r.allowed, false);
  assert.match(r.reason, /Unrecognised/);
});

// ---- §19.2 意圖與行為分欄 ----
t('模型自白動機只能停在 DECLARED', () => {
  const r = intentionalityRecord({ modelSelfReport: '我知道會被發現,還是這樣做了' });
  assert.equal(r.intentionality_state, 'DECLARED');
  assert.equal(r.MUST_NOT_AUTOPROMOTE_TO_OBSERVED, true);
});

t('owner 判定是高權威,但判的是行為不是心裡想什麼', () => {
  const r = intentionalityRecord({ humanAdjudication: '這就是飄移' });
  assert.equal(r.intentionality_state, 'OWNER_ADJUDICATED');
  assert.match(r.note, /not for the.*mental state/s);
  assert.equal(r.MUST_NOT_AUTOPROMOTE_TO_OBSERVED, true, 'owner 判定也不能改這個旗標');
});

t('什麼都沒有的時候是 UNVERIFIED,不是「沒問題」', () => {
  assert.equal(intentionalityRecord({}).intentionality_state, 'UNVERIFIED');
});

// ---- §4 Evidence Receipt ----
t('receipt 欄位照規格書原文,一個不少', () => {
  const r = createReceipt({ observedAt: T, resourceLocator: 'a.js' });
  for (const f of RECEIPT_FIELDS) assert.ok(f in r, `缺 ${f}`);
});

t('existence 只有三態,傳別的直接炸,不准靜靜當成 false', () => {
  assert.throws(() => createReceipt({ existence: null }), /existence must be/);
  assert.throws(() => createReceipt({ existence: 0 }), /not a negative observation/);
  for (const v of [true, false, 'unknown']) {
    assert.equal(createReceipt({ existence: v }).existence, v);
  }
});

t('拿不到的欄位是 null,不是 0', () => {
  const r = createReceipt({ observedAt: T, resourceLocator: 'a.js' });
  assert.equal(r.byte_size, null);
  assert.equal(r.content_hash, null);
  assert.equal(r.exit_code, null);
});

t('receipt 是凍結的', () => {
  assert.ok(Object.isFrozen(createReceipt({ observedAt: T })));
});

// ---- FS-TMP-002 兩個不同的 query ----
t('positive:當時有 receipt,就答得出「T 那時存在嗎」', () => {
  const receipts = [createReceipt({
    observedAt: T, resourceLocator: 'a.js', existence: true, byteSize: 120,
    contentHash: 'abc', captureMethod: 'PostToolUse',
  })];
  const r = existedAt(receipts, { resourceLocator: 'a.js', at: T + 5000 });
  assert.equal(r.answer, 'YES');
  assert.equal(r.evidence_class, 'OBSERVED');
  assert.equal(r.byte_size, 120);
});

t('negative:沒有任何當時的 receipt,答案是 UNKNOWN 不是 NO', () => {
  const r = existedAt([], { resourceLocator: 'a.js', at: T });
  assert.equal(r.answer, 'UNKNOWN');
  assert.equal(r.evidence_class, 'MISSING');
});

t('exclusion:只有 T 之後的 receipt,不能拿來回答 T 那時的事', () => {
  const receipts = [createReceipt({
    observedAt: T + 60_000, resourceLocator: 'a.js', existence: true,
  })];
  assert.equal(existedAt(receipts, { resourceLocator: 'a.js', at: T }).answer, 'UNKNOWN');
});

t('low-evidence:receipt 的 existence 是 unknown,答案也是 UNKNOWN', () => {
  const receipts = [createReceipt({ observedAt: T, resourceLocator: 'a.js' })];
  const r = existedAt(receipts, { resourceLocator: 'a.js', at: T + 1 });
  assert.equal(r.answer, 'UNKNOWN');
  assert.equal(r.evidence_class, 'MISSING');
});

// ---- FS-TMP-003 / CT-002 / CT-032 ----
t('CT-002 檔案後來被保留期限刪掉,但有當時的憑證 → VERIFIED_AT_TIME', () => {
  const receipt = createReceipt({
    observedAt: T, resourceLocator: 'out.md', existence: true, byteSize: 4096,
  });
  const r = reconcileHistorical({ existsNow: false, historicalReceipt: receipt });
  assert.equal(r.verdict, 'VERIFIED_AT_TIME');
  assert.equal(r.may_conclude_agent_did_not_do_it, false);
});

t('CT-032 檔案不見了、沒有憑證 → MISSING_HISTORICAL_EVIDENCE,不准判 agent 沒做', () => {
  const r = reconcileHistorical({ existsNow: false, historicalReceipt: null, retentionKnown: true });
  assert.equal(r.verdict, 'MISSING_HISTORICAL_EVIDENCE');
  assert.equal(r.may_conclude_agent_did_not_do_it, false);
  assert.match(r.note, /carries no information about what the agent did/);
});

t('現在還在的話,也不准反過來當成 agent 沒做的反證', () => {
  const r = reconcileHistorical({ existsNow: true });
  assert.equal(r.verdict, 'EXISTS_NOW');
  assert.equal(r.may_conclude_agent_did_not_do_it, false);
});

t('不管哪一條路徑,都不准出現「agent 當時沒做」這個結論', () => {
  const cases = [
    { existsNow: true },
    { existsNow: false, historicalReceipt: createReceipt({ observedAt: T, existence: true }) },
    { existsNow: false, historicalReceipt: null },
    { existsNow: 'unknown', historicalReceipt: null, retentionKnown: true },
  ];
  for (const c of cases) {
    assert.equal(reconcileHistorical(c).may_conclude_agent_did_not_do_it, false,
      JSON.stringify(c));
  }
});

// ---- 專案慣例 ----
t('零依賴:evidence.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/evidence.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('每個回傳都帶版本,結果才追得回是哪一版算的', () => {
  assert.equal(existedAt([], { resourceLocator: 'x', at: T }).version, VERSION);
  assert.equal(reconcileHistorical({ existsNow: true }).version, VERSION);
  assert.equal(intentionalityRecord({}).version, VERSION);
});

t('DECLARED 那段誠實標記寫在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/evidence.js', import.meta.url), 'utf8');
  assert.match(src, /說服力正是不能當證據的原因/);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
