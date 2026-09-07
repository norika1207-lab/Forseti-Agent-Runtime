// 目標範圍與離題累積。飄移看趨勢,這個看單一動作。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { VERSION, DEFAULT_CONFIG, createScope, inScope, createStreak, check, offScopeRate } from '../src/scope.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const S = createScope({ northStar: 'ship auth', paths: ['src/auth', 'test/auth'] });

t('沒宣告路徑就不作用,而且要明說', () => {
  const empty = createScope({});
  assert.equal(empty.active, false);
  const r = check('anything.js', empty, createStreak());
  assert.equal(r.notice, null);
  assert.match(r.inactive_reason, /does nothing until one exists/);
});

t('這個模組不推測範圍,那條理由寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/scope.js', import.meta.url), 'utf8');
  assert.ok(/範圍是宣告出來的,不是推出來的/.test(src));
  assert.ok(/那比不擋更糟/.test(src));
});

t('範圍內的路徑判得出來,邊界卡在斜線上', () => {
  assert.equal(inScope('src/auth/token.js', S), true);
  assert.equal(inScope('src/auth', S), true);
  assert.equal(inScope('src/authorize/x.js', S), false, 'src/auth 不該匹配 src/authorize');
  assert.equal(inScope('docs/blog.md', S), false);
});

t('沒宣告範圍時一律算在內,不擋任何東西', () =>
  assert.equal(inScope('anything', createScope({})), true));

// ---- 核心:累積才叫,不是碰到就叫 ----
t('第一次離題不叫,做事本來就會碰周邊', () => {
  const r = check('docs/blog.md', S, createStreak());
  assert.equal(r.notice, null);
  assert.equal(r.streak.off, 1);
});

t('連續達門檻才叫', () => {
  let s = createStreak(), r;
  for (let i = 0; i < 5; i++) r = check('docs/x' + i + '.md', S, s), s = r.streak;
  assert.ok(r.notice);
  assert.equal(r.notice.streak, 5);
  assert.match(r.notice.text, /consecutive writes outside/);
});

t('中間碰回範圍內一次,計數歸零', () => {
  let s = createStreak();
  for (let i = 0; i < 4; i++) s = check('docs/x' + i + '.md', S, s).streak;
  assert.equal(s.off, 4);
  s = check('src/auth/token.js', S, s).streak;
  assert.equal(s.off, 0, '回到主線就不算走開,剛才那幾次是繞路');
});

t('提醒是提醒不是阻止,文字裡要講明工具判斷不了', () => {
  let s = createStreak(), r;
  for (let i = 0; i < 5; i++) r = check('docs/x' + i + '.md', S, s), s = r.streak;
  assert.match(r.notice.text, /may be a necessary detour - the tool cannot tell/);
  assert.match(r.notice.text, /declare it so the drift reading stays meaningful/);
});

t('北極星會出現在提醒裡', () => {
  let s = createStreak(), r;
  for (let i = 0; i < 5; i++) r = check('docs/x' + i + '.md', S, s), s = r.streak;
  assert.match(r.notice.text, /ship auth/);
});

t('門檻可調', () => {
  const r = check('docs/a.md', S, createStreak(), { streakBeforeNotice: 1 });
  assert.ok(r.notice);
});

// ---- 回顧 ----
t('離題比例回顧得出來,沒檢查過就是 null', () => {
  assert.equal(offScopeRate(createStreak()).rate, null);
  let s = createStreak();
  s = check('docs/a.md', S, s).streak;
  s = check('src/auth/b.js', S, s).streak;
  const r = offScopeRate(s);
  assert.equal(r.rate, 0.5);
  assert.equal(r.current_streak, 0);
});

// ---- 邊界 ----
t('回傳凍結', () => {
  const r = check('x.js', S, createStreak());
  assert.throws(() => { r.streak.last_off_paths.push('y'); }, TypeError);
});

t('零依賴：scope.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/scope.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('為什麼不是碰到就叫,理由寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/scope.js', import.meta.url), 'utf8');
  assert.ok(/每一次都提醒等於沒有提醒,而且會被關掉/.test(src));
});

t('未校準的常數自己說了', () => {
  const src = readFileSync(new URL('../src/scope.js', import.meta.url), 'utf8');
  assert.ok(/五次沒有實測校準/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
