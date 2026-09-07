// 規格書 v0.1 第 6 節:產物實在性。
// 開頭那句是整節的重點:檔名、終端機的一行字、模型的宣稱、工具開始執行的事件,
// 都不是完成的證據。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CLAIM_KINDS, VERSION, DEFAULT_CONFIG, verifyClaim, artifactNullity, summarize } from '../src/artifact.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('六種宣稱,照規格書第 6 節那張表', () =>
  assert.deepEqual([...CLAIM_KINDS],
    ['FILE_CREATED', 'CODE_MODIFIED', 'TEST_PASSED', 'EXTERNAL_OBJECT', 'TASK_COMPLETE', 'PROCESS_RUNNING']));

t('不認得的宣稱種類拋錯', () =>
  assert.throws(() => verifyClaim({ kind: 'MAYBE' }, {}), /Unrecognised claim kind/));

// ---- 沒去看就是 UNKNOWN ----
t('沒有觀測就是 UNKNOWN,不是失敗', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED', target: 'a.js' }, null);
  assert.equal(r.verdict, 'UNKNOWN');
  assert.match(r.reasons[0], /not evidence of failure/);
});

// ---- 檔案:規格書點名的零位元組 ----
t('零位元組的檔案推翻宣稱', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED' }, { exists: true, bytes: 0 });
  assert.equal(r.verdict, 'REFUTED');
  assert.ok(r.reasons.some((x) => /zero bytes/.test(x)));
});

t('檔案不存在推翻宣稱', () =>
  assert.equal(verifyClaim({ kind: 'FILE_CREATED' }, { exists: false }).verdict, 'REFUTED'));

t('小於預期最小值的檔案推翻宣稱', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED', expected_min_bytes: 500 }, { exists: true, bytes: 100 });
  assert.equal(r.verdict, 'REFUTED');
  assert.ok(r.reasons.some((x) => /below the expected minimum/.test(x)));
});

t('存在但沒查內容,只能是 OBSERVED 不能是 VERIFIED', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900 });
  assert.equal(r.verdict, 'VERIFIED');
  assert.equal(r.epistemic, 'OBSERVED', '沒有 hash 也沒有可讀性檢查,不夠格叫 VERIFIED');
});

t('有 hash 才升到 VERIFIED', () =>
  assert.equal(verifyClaim({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'ab12' }).epistemic, 'VERIFIED'));

t('存在但讀不了,推翻', () =>
  assert.equal(verifyClaim({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, readable: false }).verdict, 'REFUTED'));

t('沒檢查存在性就是 UNKNOWN', () =>
  assert.equal(verifyClaim({ kind: 'FILE_CREATED' }, { bytes: 900 }).verdict, 'UNKNOWN'));

t('說改了程式但磁碟上零行變動,推翻', () => {
  const r = verifyClaim({ kind: 'CODE_MODIFIED' }, { exists: true, bytes: 900, diff_lines: 0 });
  assert.equal(r.verdict, 'REFUTED');
  assert.ok(r.reasons.some((x) => /no diff/.test(x)));
});

// ---- 測試 ----
t('沒有 exit code 就是沒跑過,不能算通過', () => {
  const r = verifyClaim({ kind: 'TEST_PASSED' }, { command: 'npm test' });
  assert.equal(r.verdict, 'UNKNOWN');
  assert.match(r.reasons[0], /cannot have passed/);
});

t('非零 exit code 推翻', () =>
  assert.equal(verifyClaim({ kind: 'TEST_PASSED' }, { exit_code: 1 }).verdict, 'REFUTED'));

t('exit 0 但沒擷取輸出,不知道跑了哪些測試', () => {
  const r = verifyClaim({ kind: 'TEST_PASSED' }, { exit_code: 0, output_captured: false });
  assert.equal(r.verdict, 'UNKNOWN');
  assert.equal(r.epistemic, 'INFERRED');
});

t('宣稱的測試身分跟實際跑的不符,不算通過', () => {
  const r = verifyClaim({ kind: 'TEST_PASSED', test_id: 'auth' },
    { exit_code: 0, output_captured: true, test_id: 'smoke' });
  assert.equal(r.verdict, 'UNKNOWN');
  assert.ok(r.reasons.some((x) => /identifies as/.test(x)));
});

t('全部齊全才算 VERIFIED', () =>
  assert.equal(verifyClaim({ kind: 'TEST_PASSED', test_id: 'auth' },
    { exit_code: 0, output_captured: true, test_id: 'auth' }).verdict, 'VERIFIED'));

// ---- 外部物件 ----
t('本機 log 的一行字不是遠端確認', () => {
  const r = verifyClaim({ kind: 'EXTERNAL_OBJECT' }, { logged: 'created ok' });
  assert.equal(r.verdict, 'UNKNOWN');
  assert.match(r.reasons[0], /not confirmation/);
});

t('有遠端識別碼就算數', () =>
  assert.equal(verifyClaim({ kind: 'EXTERNAL_OBJECT' }, { remote_id: 'zen-123' }).verdict, 'VERIFIED'));

// ---- 背景程式:規格書挑明的那條 ----
t('歷史 PID 的文字不證明它現在活著', () => {
  const r = verifyClaim({ kind: 'PROCESS_RUNNING' }, { from_ps_text: 'PID 71981 running' });
  assert.equal(r.verdict, 'UNKNOWN');
  assert.ok(r.reasons.some((x) => /does not prove it is alive now/.test(x)));
});

t('實際確認活著才算數', () =>
  assert.equal(verifyClaim({ kind: 'PROCESS_RUNNING' }, { alive: true }).verdict, 'VERIFIED'));

t('確認死了就推翻', () =>
  assert.equal(verifyClaim({ kind: 'PROCESS_RUNNING' }, { alive: false }).verdict, 'REFUTED'));

// ---- 任務完成 ----
t('沒連任何驗收證據就宣稱完成 = UNKNOWN', () =>
  assert.equal(verifyClaim({ kind: 'TASK_COMPLETE' }, {}).verdict, 'UNKNOWN'));

t('連了零筆證據的完成宣稱直接推翻', () =>
  assert.equal(verifyClaim({ kind: 'TASK_COMPLETE' }, { evidence_refs: [] }).verdict, 'REFUTED'));

t('還有未解阻塞就不算完成', () => {
  const r = verifyClaim({ kind: 'TASK_COMPLETE' }, { evidence_refs: ['a'], unresolved_blockers: ['db down'] });
  assert.equal(r.verdict, 'REFUTED');
  assert.ok(r.reasons.some((x) => /unresolved blocker/.test(x)));
});

t('證據齊全且無阻塞才算完成', () =>
  assert.equal(verifyClaim({ kind: 'TASK_COMPLETE' },
    { evidence_refs: ['a', 'b'], unresolved_blockers: [] }).verdict, 'VERIFIED'));

// ---- S5 Artifact Nullity ----
t('沒有任何產物宣稱時比例是 null 不是 0', () =>
  assert.equal(artifactNullity([]).ratio, null));

t('被推翻的比例算得出來', () => {
  const rs = [
    verifyClaim({ kind: 'FILE_CREATED' }, { exists: true, bytes: 0 }),
    verifyClaim({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'x' }),
  ];
  assert.equal(artifactNullity(rs).ratio, 0.5);
});

t('UNKNOWN 不進分子,那是沒查不是查壞', () => {
  const rs = [
    verifyClaim({ kind: 'FILE_CREATED' }, null),
    verifyClaim({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'x' }),
  ];
  const n = artifactNullity(rs);
  assert.equal(n.ratio, 0);
  assert.equal(n.unknown, 1);
  assert.equal(n.coverage, 0.5, '一半沒查,這個訊號本身只有一半可信');
});

// ---- 總結必須帶 UNKNOWN ----
t('零推翻不等於沒事,沒查的比例要一起講', () => {
  const s = summarize([verifyClaim({ kind: 'FILE_CREATED' }, null)]);
  assert.equal(s.REFUTED, 0);
  assert.match(s.note, /Zero refutations does not mean everything is fine/);
  assert.equal(s.unchecked_ratio, 1);
});

t('全部查得到時就直說', () =>
  assert.match(summarize([verifyClaim({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'x' })]).note,
    /All claims were checkable/));

// ---- 邊界 ----
t('每個結果都帶版本', () =>
  assert.equal(verifyClaim({ kind: 'FILE_CREATED' }, null).version, VERSION));

t('回傳凍結', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED' }, null);
  assert.throws(() => { r.reasons.push('x'); }, TypeError);
});

t('零依賴：artifact.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/artifact.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('這個模組不讀檔案系統,那是刻意的', () => {
  const src = readFileSync(new URL('../src/artifact.js', import.meta.url), 'utf8');
  assert.ok(!/readFileSync|existsSync|statSync/.test(src));
  assert.ok(/這個模組不讀檔案系統/.test(src));
});

t('未校準的常數自己說了', () => {
  const src = readFileSync(new URL('../src/artifact.js', import.meta.url), 'utf8');
  assert.ok(/64 bytes 沒有實測校準/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
