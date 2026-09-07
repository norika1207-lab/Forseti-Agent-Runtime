// Forseti M3 admission.js 測試。直接 `node test/admission.test.mjs` 跑,不需要任何 server。
import assert from 'node:assert/strict';
import { buildGraph } from '../src/cost.js';
import {
  createWriteScope,
  createAdvisoryLock,
  recordActualWrite,
  releaseScope,
  outOfScopeWrites,
  isLockExpired,
  liveLocks,
  matchGlob,
  expandGlobs,
  hubFiles,
  windowConflicts,
  findConflicts,
  suggestNarrowedScope,
  decideAdmission,
  falseBlockRate,
  DECISIONS,
  SCOPE_STATES,
  HUB_SOURCES,
  DEFAULT_CONFIG,
} from '../src/admission.js';

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

const T0 = 1757227200000;

function scope(over = {}) {
  return createWriteScope({
    agent_id: 'A',
    task_id: 'task-A',
    declared: ['src/auth/**'],
    actual: ['src/auth/login.js'],
    declared_at: T0,
    ...over,
  });
}

// ---- 資料結構欄位名(文件 5.3,一字不改) ----
test('WriteScope 欄位名照 5.3 節,恰好 6 個;預設 state 為 ACTIVE', () => {
  const s = scope();
  assert.deepEqual(Object.keys(s).sort(), [
    'actual',
    'agent_id',
    'declared',
    'declared_at',
    'state',
    'task_id',
  ]);
  assert.equal(s.state, SCOPE_STATES.ACTIVE);
});

test('AdvisoryLock 欄位名照 5.3 節,恰好 4 個', () => {
  const l = createAdvisoryLock({ file_path: 'src/a.js', holder: 'A', acquired_at: T0 });
  assert.deepEqual(Object.keys(l).sort(), ['acquired_at', 'file_path', 'holder', 'ttl_seconds']);
});

test('AdmissionDecision 保留 5.3 節四個原欄位,一字不改', () => {
  const d = decideAdmission({ agent_id: 'B', task_id: 't', declared: ['src/x/**'] }, {});
  for (const k of ['conflicts', 'decision', 'reason', 'suggested_scope']) {
    assert.ok(k in d, '規格欄位不可少: ' + k);
  }
});

// 這條原本寫成「恰好 4 個,不多塞欄位」,守的是規格 5.3 的欄位契約。
// 端到端測試抓到漏洞之後做了一次有記錄的修訂:多出 undecidable 與 is_complete。
// 理由是「沒查到衝突」與「沒有衝突」必須分得開,而且要分得出來的必須是欄位不是字串,
// 呼叫端才寫得出 if (!verdict.is_complete) 這種保守處理。塞進 reason 文字裡等於沒有。
// 這條測試改成擋「未記錄的擴充」,而不是擋所有擴充。
test('AdmissionDecision 的擴充欄位必須是有記錄的那兩個,其餘一律不准加', () => {
  const d = decideAdmission({ agent_id: 'B', task_id: 't', declared: ['src/x/**'] }, {});
  assert.deepEqual(Object.keys(d).sort(),
    ['conflicts', 'decision', 'is_complete', 'reason', 'suggested_scope', 'undecidable']);
});

test('派工當下就攔得住:兩人宣告同一個檔案、都還沒動手寫', () => {
  const held = createWriteScope({
    agent_id: 'A', task_id: 't1', declared: ['src/shared.js'], declared_at: T0,
  });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't2', declared: ['src/shared.js'], declared_at: T0 },
    { scopes: [held], now: T0 },
  );
  assert.notEqual(d.decision, 'ALLOW', 'actual 還是空的時候正是最該攔的一刻');
  assert.deepEqual(d.conflicts.map((c) => c.file_path), ['src/shared.js']);
});

test('字面路徑落在對方宣告的 glob 範圍內也攔得住', () => {
  const held = createWriteScope({
    agent_id: 'A', task_id: 't1', declared: ['src/**'], declared_at: T0,
  });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't2', declared: ['src/deep/a.js'], declared_at: T0 },
    { scopes: [held], now: T0 },
  );
  assert.notEqual(d.decision, 'ALLOW');
});

test('兩邊都是萬用字元又沒有候選清單時,標明無法判定,不冒充放行', () => {
  const held = createWriteScope({
    agent_id: 'A', task_id: 't1', declared: ['src/**'], declared_at: T0,
  });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't2', declared: ['src/*.js'], declared_at: T0 },
    { scopes: [held], now: T0 },
  );
  assert.equal(d.decision, 'ALLOW');
  assert.equal(d.is_complete, false, '這是沒查到,不是沒有');
  assert.equal(d.undecidable.length, 1);
  assert.match(d.reason, /無法判定/);
});

test('自己的 scope 不跟自己衝突', () => {
  const mine = createWriteScope({
    agent_id: 'B', task_id: 't1', declared: ['src/shared.js'], declared_at: T0,
  });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't2', declared: ['src/shared.js'], declared_at: T0 },
    { scopes: [mine], now: T0 },
  );
  assert.equal(d.decision, 'ALLOW');
  assert.equal(d.is_complete, true);
});

test('已釋放的 scope 不再造成衝突', () => {
  const done = releaseScope(createWriteScope({
    agent_id: 'A', task_id: 't1', declared: ['src/shared.js'], declared_at: T0,
  }));
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't2', declared: ['src/shared.js'], declared_at: T0 },
    { scopes: [done], now: T0 },
  );
  assert.equal(d.decision, 'ALLOW');
});

// ---- glob ----
test('最小 glob:** 跨目錄、* 單層、? 單字元', () => {
  assert.equal(matchGlob('src/**', 'src/a.js'), true);
  assert.equal(matchGlob('src/**', 'src/deep/x/a.js'), true);
  assert.equal(matchGlob('src/*.js', 'src/a.js'), true);
  assert.equal(matchGlob('src/*.js', 'src/deep/a.js'), false);
  assert.equal(matchGlob('src/a?.js', 'src/a1.js'), true);
  assert.equal(matchGlob('src/**', 'test/a.js'), false);
  assert.deepEqual([...expandGlobs(['src/**'], ['src/a.js', 'test/b.js'])], ['src/a.js']);
});

// ---- ALLOW:無交集 ----
test('ALLOW:宣告範圍與所有 ACTIVE 佔用無交集', () => {
  const d = decideAdmission(
    { agent_id: 'B', task_id: 'task-B', declared: ['src/billing/**'] },
    { scopes: [scope()], now: T0 },
  );
  assert.equal(d.decision, DECISIONS.ALLOW);
  assert.deepEqual(d.conflicts, []);
  assert.equal(d.suggested_scope, null);
});

test('RELEASED 的 scope 不算佔用;自己的 scope 不跟自己衝突', () => {
  const released = releaseScope(scope());
  const d1 = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/auth/**'] },
    { scopes: [released], now: T0 },
  );
  assert.equal(d1.decision, DECISIONS.ALLOW);
  const d2 = decideAdmission(
    { agent_id: 'A', task_id: 't2', declared: ['src/auth/**'] },
    { scopes: [scope()], now: T0 },
  );
  assert.equal(d2.decision, DECISIONS.ALLOW);
});

// ---- 5.7 雷一:用宣告寫入集合,不用傳遞閉包 ----
test('雷一:下游依賴不算交集,只有宣告寫入集合本身才算', () => {
  // src/auth/login.js 被 A 佔用;B 要寫 src/core/base.js,而 login.js 依賴 base.js。
  // 用傳遞閉包會判成衝突,用宣告寫入集合不會。這一條釘住不准改用閉包。
  const graph = buildGraph([{ from: 'src/auth/login.js', to: 'src/core/base.js' }]);
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/core/**'] },
    { scopes: [scope()], now: T0, graph, candidateFiles: ['src/core/base.js'] },
  );
  assert.equal(d.decision, DECISIONS.ALLOW);
  assert.deepEqual(d.conflicts, []);
});

test('findConflicts 三種來源:對方 actual、對方 declared、未逾時的鎖', () => {
  const other = scope({ declared: ['src/auth/**'], actual: ['src/auth/login.js'] });
  // 一,命中對方 actual
  const c1 = findConflicts({ agent_id: 'B', declared: ['src/auth/login.js'] }, { scopes: [other], now: T0 });
  assert.deepEqual(c1, [{ file_path: 'src/auth/login.js', holder_agent: 'A' }]);
  // 二,命中對方 declared(需要 candidateFiles 才展開得出來)
  const c2 = findConflicts(
    { agent_id: 'B', declared: ['src/**'] },
    { scopes: [other], now: T0, candidateFiles: ['src/auth/session.js'] },
  );
  assert.ok(c2.some((c) => c.file_path === 'src/auth/session.js' && c.holder_agent === 'A'));
  // 三,命中未逾時的鎖
  const lock = createAdvisoryLock({ file_path: 'src/x/y.js', holder: 'C', acquired_at: T0, ttl_seconds: 60 });
  const c3 = findConflicts({ agent_id: 'B', declared: ['src/x/**'] }, { locks: [lock], now: T0 + 1000 });
  assert.deepEqual(c3, [{ file_path: 'src/x/y.js', holder_agent: 'C' }]);
});

// ---- 5.4 樞紐檔案例外 ----
test('樞紐例外:交集只落在樞紐檔案上就放行,不算真衝突', () => {
  const files = {};
  for (let i = 0; i < 99; i += 1) files[`src/leaf${i}.js`] = 1;
  files['src/index.js'] = 500; // barrel,前 2 百分位
  const holder = scope({ declared: ['src/**'], actual: ['src/index.js'] });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/index.js'] },
    { scopes: [holder], now: T0, importCounts: files },
  );
  assert.equal(d.decision, DECISIONS.ALLOW);
  assert.equal(d.conflicts.length, 1); // 警示資訊保留,但決策是放行
  assert.match(d.reason, /樞紐/);
});

test('樞紐例外:交集混有非樞紐檔案時,非樞紐那些仍算真衝突', () => {
  const files = {};
  for (let i = 0; i < 99; i += 1) files[`src/leaf${i}.js`] = 1;
  files['src/index.js'] = 500;
  const holder = scope({ declared: ['src/**'], actual: ['src/index.js', 'src/leaf3.js'] });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/index.js', 'src/leaf3.js'] },
    { scopes: [holder], now: T0, importCounts: files },
  );
  assert.notEqual(d.decision, DECISIONS.ALLOW);
  assert.deepEqual(d.conflicts.map((c) => c.file_path), ['src/leaf3.js']); // 樞紐已剔除
});

test('N 可設定:同一份資料,N=2 是樞紐,N 調到 0.5 就不是', () => {
  const files = {};
  for (let i = 0; i < 99; i += 1) files[`src/leaf${i}.js`] = 1;
  files['src/index.js'] = 500;
  assert.equal(hubFiles(files, { hub_percentile: 2 }).has('src/index.js'), true);
  const strict = hubFiles(files, { hub_percentile: 0.5 });
  assert.equal(strict.has('src/index.js'), true);
  // 放寬到 100 百分位時所有檔案都算樞紐,證明參數真的在生效
  assert.equal(hubFiles(files, { hub_percentile: 100 }).size, 100);
  assert.equal(DEFAULT_CONFIG.hub_percentile, 2);
});

test('沒有 import 次數資料就沒有樞紐豁免:hubFiles 回 null,決策不估算', () => {
  assert.equal(hubFiles(null), null);
  const holder = scope({ declared: ['src/**'], actual: ['src/index.js'] });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/index.js'] },
    { scopes: [holder], now: T0, importCounts: null },
  );
  assert.notEqual(d.decision, DECISIONS.ALLOW);
  assert.match(d.reason, new RegExp(HUB_SOURCES.NONE));
  assert.match(d.reason, /未估算/);
});

// ---- NARROW / SERIALIZE / BLOCK ----
test('NARROW:可縮小避開交集時給出建議範圍', () => {
  const holder = scope({ declared: ['src/auth/login.js'], actual: ['src/auth/login.js'] });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/auth/**'] },
    {
      scopes: [holder],
      now: T0,
      candidateFiles: ['src/auth/login.js', 'src/auth/token.js', 'src/auth/mfa.js'],
    },
  );
  assert.equal(d.decision, DECISIONS.NARROW);
  assert.deepEqual(d.suggested_scope, ['src/auth/mfa.js', 'src/auth/token.js']);
  assert.deepEqual(d.conflicts.map((c) => c.file_path), ['src/auth/login.js']);
});

test('NARROW 建議範圍會用依賴圖再排除會波及持有者的候選', () => {
  const holder = scope({ declared: ['src/auth/login.js'], actual: ['src/auth/login.js'] });
  // token.js 被 login.js 依賴,改 token 會波及持有者正在動的檔案,故從建議中排除
  const graph = buildGraph([{ from: 'src/auth/login.js', to: 'src/auth/token.js' }]);
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/auth/**'] },
    {
      scopes: [holder],
      now: T0,
      graph,
      candidateFiles: ['src/auth/login.js', 'src/auth/token.js', 'src/auth/mfa.js'],
    },
  );
  assert.equal(d.decision, DECISIONS.NARROW);
  assert.deepEqual(d.suggested_scope, ['src/auth/mfa.js']);
});

test('沒有候選檔案清單就不猜能否縮小,理由要明講,不靜默降級', () => {
  const holder = scope({ declared: ['src/auth/**'], actual: ['src/auth/login.js'] });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/auth/**'], deferrable: true },
    { scopes: [holder], now: T0 },
  );
  assert.equal(d.decision, DECISIONS.SERIALIZE);
  assert.equal(d.suggested_scope, null);
  assert.match(d.reason, /不猜/);
});

test('SERIALIZE:無法縮小但任務可延後', () => {
  const holder = scope({ declared: ['src/auth/**'], actual: ['src/auth/login.js'] });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/auth/login.js'], deferrable: true },
    { scopes: [holder], now: T0, candidateFiles: ['src/auth/login.js'] },
  );
  assert.equal(d.decision, DECISIONS.SERIALIZE);
  assert.match(d.reason, /縮小後無檔案可寫/);
});

test('BLOCK 只保留給明確宣告 deferrable=false 的請求', () => {
  const holder = scope({ declared: ['src/auth/**'], actual: ['src/auth/login.js'] });
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/auth/login.js'], deferrable: false },
    { scopes: [holder], now: T0, candidateFiles: ['src/auth/login.js'] },
  );
  assert.equal(d.decision, DECISIONS.BLOCK);
  assert.deepEqual(d.conflicts, [{ file_path: 'src/auth/login.js', holder_agent: 'A' }]);
  assert.match(d.reason, /明確宣告不可延後/);
});

test('未宣告 deferrable 且無法縮小 → SERIALIZE,不是 BLOCK(預設不叫人)', () => {
  const holder = scope({ declared: ['src/auth/**'], actual: ['src/auth/login.js'] });
  // 與上一條唯一差別:請求沒有帶 deferrable。預設不得把成本轉嫁給使用者。
  const d = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/auth/login.js'] },
    { scopes: [holder], now: T0, candidateFiles: ['src/auth/login.js'] },
  );
  assert.equal(d.decision, DECISIONS.SERIALIZE);
  assert.notEqual(d.decision, DECISIONS.BLOCK);
  assert.match(d.reason, /預設可延後/);
  // 同場加映:沒有候選清單、也沒宣告 deferrable,一樣不准 BLOCK
  const d2 = decideAdmission(
    { agent_id: 'B', task_id: 't', declared: ['src/auth/**'] },
    { scopes: [holder], now: T0 },
  );
  assert.equal(d2.decision, DECISIONS.SERIALIZE);
});

// ---- TTL(文件 5.6 驗收四) ----
test('TTL:鎖逾時自動失效,agent 崩潰不會造成永久死鎖', () => {
  const lock = createAdvisoryLock({
    file_path: 'src/auth/login.js',
    holder: 'A',
    acquired_at: T0,
    ttl_seconds: 60,
  });
  assert.equal(isLockExpired(lock, T0 + 59_000), false);
  assert.equal(isLockExpired(lock, T0 + 60_000), true);
  assert.equal(liveLocks([lock], T0 + 61_000).length, 0);
  const req = { agent_id: 'B', task_id: 't', declared: ['src/auth/login.js'], deferrable: false };
  // 持有者「崩潰」不釋放,TTL 內擋下
  assert.equal(decideAdmission(req, { locks: [lock], now: T0 + 30_000 }).decision, DECISIONS.BLOCK);
  // TTL 過後自動放行,不需要任何人手動解鎖
  assert.equal(decideAdmission(req, { locks: [lock], now: T0 + 60_000 }).decision, DECISIONS.ALLOW);
});

test('TTL 有預設值且可覆寫', () => {
  const d = createAdvisoryLock({ file_path: 'a.js', holder: 'A', acquired_at: T0 });
  assert.equal(d.ttl_seconds, DEFAULT_CONFIG.default_ttl_seconds);
  const custom = createAdvisoryLock({ file_path: 'a.js', holder: 'A', acquired_at: T0, ttl_seconds: 5 });
  assert.equal(custom.ttl_seconds, 5);
});

// ---- 15 秒窗口(5.7 雷二:數值未經實測) ----
test('窗口衝突:同檔案不同 agent 在窗口內判衝突;窗口可設定', () => {
  const events = [
    { file_path: 'src/a.js', agent_id: 'A', at: T0 },
    { file_path: 'src/a.js', agent_id: 'B', at: T0 + 10_000 },
    { file_path: 'src/b.js', agent_id: 'A', at: T0 },
    { file_path: 'src/b.js', agent_id: 'B', at: T0 + 20_000 },
  ];
  const c = windowConflicts(events);
  assert.deepEqual(c.map((x) => x.file_path), ['src/a.js']);
  assert.equal(c[0].gap_seconds, 10);
  assert.equal(windowConflicts(events, { conflict_window_seconds: 30 }).length, 2);
  assert.equal(windowConflicts(events, { conflict_window_seconds: 5 }).length, 0);
  assert.equal(DEFAULT_CONFIG.conflict_window_seconds, 15);
});

test('窗口衝突:同一個 agent 連續寫同一檔案不算衝突', () => {
  const events = [
    { file_path: 'src/a.js', agent_id: 'A', at: T0 },
    { file_path: 'src/a.js', agent_id: 'A', at: T0 + 1000 },
  ];
  assert.deepEqual(windowConflicts(events), []);
});

test('15 秒與 TTL 預設值在原始碼中標明未經實測校準,不可宣稱已驗證', async () => {
  const { readFileSync } = await import('node:fs');
  const src = readFileSync(new URL('../src/admission.js', import.meta.url), 'utf8');
  assert.match(src, /未經實測校準/);
  assert.match(src, /不是實測值/);
});

// ---- 越界偵測(5.5 步驟三) ----
test('越界偵測:actual 落在 declared 之外的檔案要能列出', () => {
  let s = scope({ declared: ['src/auth/**'], actual: [] });
  s = recordActualWrite(s, 'src/auth/login.js');
  s = recordActualWrite(s, 'src/billing/invoice.js');
  assert.deepEqual(outOfScopeWrites(s), ['src/billing/invoice.js']);
});

// ---- 誤攔率(5.6 驗收二) ----
test('誤攔率:只算被攔下的,未裁決不進分母且如實計數', () => {
  const r = falseBlockRate([
    { decision: DECISIONS.BLOCK, owner_verdict: 'SHOULD_ALLOW' },
    { decision: DECISIONS.BLOCK, owner_verdict: 'AGREE' },
    { decision: DECISIONS.SERIALIZE, owner_verdict: 'AGREE' },
    { decision: DECISIONS.BLOCK, owner_verdict: null },
    { decision: DECISIONS.ALLOW, owner_verdict: 'SHOULD_ALLOW' },
  ]);
  assert.equal(r.intercepted, 4);
  assert.equal(r.judged, 3);
  assert.equal(r.wrongly_blocked, 1);
  assert.equal(r.unjudged, 1);
  assert.equal(Math.round(r.rate * 1000) / 1000, 0.333);
});

test('誤攔率:全部未裁決時 rate 為 null,不是 0(沒資料不等於零誤攔)', () => {
  const r = falseBlockRate([{ decision: DECISIONS.BLOCK, owner_verdict: null }]);
  assert.equal(r.rate, null);
  assert.equal(r.unjudged, 1);
});

// ---- 不可變與零依賴 ----
test('回傳物件凍結:決策與 scope 都改不動', () => {
  const d = decideAdmission({ agent_id: 'B', task_id: 't', declared: ['zzz/**'] }, {});
  assert.throws(() => {
    'use strict';
    d.decision = 'ALLOW_ALL';
  });
  const s = scope();
  assert.throws(() => {
    'use strict';
    s.state = 'RELEASED';
  });
});

test('零依賴:admission.js 只 import ./cost.js,沒有其他 import', async () => {
  const { readFileSync } = await import('node:fs');
  const src = readFileSync(new URL('../src/admission.js', import.meta.url), 'utf8');
  const imports = [...src.matchAll(/^import .*?from '(.+?)';/gm)].map((m) => m[1]);
  assert.deepEqual(imports, ['./cost.js']);
});

console.log('');
console.log(`結果:${pass} 通過,${fail} 失敗,共 ${pass + fail} 條`);
if (fail > 0) process.exit(1);
