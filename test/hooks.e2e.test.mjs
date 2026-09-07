/**
 * Hook 的端到端測試。
 *
 * 前面所有測試都在測模組。這一份測的是那三個 hook 檔案本身:
 * 真的開一個 node 程序,真的餵 Claude Code 會送的那種 stdin JSON,
 * 真的看 exit code 跟 stderr。
 *
 * 為什麼要獨立成一份:hook 是唯一一段「單元測試全過、實際裝上去
 * 卻可能一次都不會開口」的程式碼。它的正確性不在函式回傳值,
 * 在程序的 exit code 跟它寫進 stderr 的那串 JSON 格式。
 *
 * 這裡有一半的案例在測「不該擋的時候真的沒擋」。那半邊比會擋更重要:
 * 一個誤攔的 hook 會被拔掉,而被拔掉的守衛保護不了任何人。
 */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert';

const HERE = dirname(fileURLToPath(import.meta.url));
const PRE = join(HERE, '..', 'hooks', 'forseti-hook.mjs');
const STOP = join(HERE, '..', 'hooks', 'forseti-stop-hook.mjs');

let pass = 0; let fail = 0;
function t(name, fn) {
  try { fn(); pass += 1; } catch (e) { fail += 1; console.error(`FAIL ${name}\n  ${e.message}`); }
}

/**
 * 開一個真的 hook 程序,回 exit code 跟 stderr。
 *
 * HOME 預設指到一個空目錄。hook 找不到專案的北極星時會回頭找
 * 使用者家目錄的,而測試機器上那個檔案是真的存在的 ——
 * 不隔離的話,「沒有錨點就不准談飄移」那條會讀到真人的北極星而假通過。
 */
const EMPTY_HOME = mkdtempSync(join(tmpdir(), 'forseti-home-'));

function runHook(script, payload, env = {}) {
  const r = spawnSync('node', [script], {
    input: JSON.stringify(payload), encoding: 'utf8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: '', HOME: EMPTY_HOME, USERPROFILE: EMPTY_HOME, ...env },
  });
  return { code: r.status, stderr: r.stderr ?? '', stdout: r.stdout ?? '' };
}

function sandbox(goal) {
  const dir = mkdtempSync(join(tmpdir(), 'forseti-e2e-'));
  mkdirSync(join(dir, '.forseti'), { recursive: true });
  if (goal) writeFileSync(join(dir, '.forseti', 'goal.json'), JSON.stringify(goal));
  return dir;
}

const write = (cwd, session, file) => ({
  hook_event_name: 'PostToolUse', session_id: session, cwd,
  tool_name: 'Write', tool_input: { file_path: file, content: 'x' },
});
const about = (cwd, session, file) => ({
  hook_event_name: 'PreToolUse', session_id: session, cwd,
  tool_name: 'Write', tool_input: { file_path: file, content: 'x' },
});

// ── 撞車 ──────────────────────────────────────────────────────

t('AT-HOOK-01 另一個 session 剛寫過同一個檔,會擋', () => {
  const dir = sandbox();
  runHook(PRE, write(dir, 'session-aaaaaaaa', '/p/shared.js'));
  const r = runHook(PRE, about(dir, 'session-bbbbbbbb', '/p/shared.js'));
  assert.equal(r.code, 2, `預期 exit 2,得到 ${r.code}`);
  const out = JSON.parse(r.stderr);
  assert.equal(out.hookSpecificOutput.permissionDecision, 'ask');
  assert.match(out.systemMessage, /another session wrote/);
  assert.match(out.systemMessage, /session-/, '訊息要指出是誰');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-02 是自己剛寫的,不擋', () => {
  const dir = sandbox();
  runHook(PRE, write(dir, 'same-session', '/p/mine.js'));
  const r = runHook(PRE, about(dir, 'same-session', '/p/mine.js'));
  assert.equal(r.code, 0, '自己寫自己的檔不該被擋');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-03 沒人碰過的檔,不擋', () => {
  const dir = sandbox();
  const r = runHook(PRE, about(dir, 'session-x', '/p/fresh.js'));
  assert.equal(r.code, 0);
  assert.equal(r.stderr, '');
  rmSync(dir, { recursive: true, force: true });
});

// ── 離題 ──────────────────────────────────────────────────────

const GOAL = { north_star: '聚焦完成 Forseti。', scope: ['/proj/forseti'] };

t('AT-HOOK-04 離題一兩次不出聲,連續五次才擋', () => {
  const dir = sandbox(GOAL);
  const codes = [];
  for (let i = 1; i <= 5; i += 1) {
    codes.push(runHook(PRE, about(dir, 's', `/elsewhere/other${i}.js`)).code);
  }
  assert.deepEqual(codes.slice(0, 4), [0, 0, 0, 0], '前四次必須安靜');
  assert.equal(codes[4], 2, '第五次才該開口');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-05 離題的提醒要帶著北極星,不然擋了也沒用', () => {
  const dir = sandbox(GOAL);
  let last;
  for (let i = 0; i < 5; i += 1) last = runHook(PRE, about(dir, 's', `/elsewhere/x${i}.js`));
  const out = JSON.parse(last.stderr);
  assert.match(out.systemMessage, /聚焦完成 Forseti/, '提醒必須複述目標');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-06 在範圍內寫再多次都不擋', () => {
  const dir = sandbox(GOAL);
  const codes = [];
  for (let i = 0; i < 8; i += 1) {
    codes.push(runHook(PRE, about(dir, 's', `/proj/forseti/src/m${i}.js`)).code);
  }
  assert.deepEqual(codes, [0, 0, 0, 0, 0, 0, 0, 0]);
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-07 沒宣告目標就完全不談離題,不推測', () => {
  const dir = sandbox();   // 沒有 goal.json
  const codes = [];
  for (let i = 0; i < 8; i += 1) {
    codes.push(runHook(PRE, about(dir, 's', `/anywhere/${i}.js`)).code);
  }
  assert.deepEqual(codes, [0, 0, 0, 0, 0, 0, 0, 0], '沒有錨點時不准說人飄移');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-07b 專案裡沒有北極星時,讀使用者家目錄的', () => {
  // 「這陣子只做 X」這種目標最該開口的場合,正是人跑到別的目錄
  // 做別的事的時候 —— 而那時候專案層的 goal.json 根本不在腳下。
  const home = sandbox(GOAL);          // 北極星放在「家目錄」
  const elsewhere = sandbox();         // 工作目錄自己沒有
  let last;
  for (let i = 0; i < 5; i += 1) {
    last = runHook(PRE, about(elsewhere, 's', `/way/off/${i}.js`), { HOME: home });
  }
  assert.equal(last.code, 2, '離開專案目錄之後偵測不該就此關機');
  assert.match(JSON.parse(last.stderr).systemMessage, /聚焦完成 Forseti/);
  rmSync(home, { recursive: true, force: true });
  rmSync(elsewhere, { recursive: true, force: true });
});

t('AT-HOOK-07c 專案的北極星蓋過家目錄的', () => {
  const home = sandbox({ north_star: '家目錄的目標', scope: ['/nowhere'] });
  const proj = sandbox({ north_star: '專案自己的目標', scope: ['/nowhere'] });
  let last;
  for (let i = 0; i < 5; i += 1) last = runHook(PRE, about(proj, 's', `/x/${i}.js`), { HOME: home });
  assert.match(JSON.parse(last.stderr).systemMessage, /專案自己的目標/);
  rmSync(home, { recursive: true, force: true });
  rmSync(proj, { recursive: true, force: true });
});

// ── 說了沒做 ──────────────────────────────────────────────────

function ledger(dir, open) {
  writeFileSync(join(dir, '.forseti', 'declarations.json'), JSON.stringify({ open, blockedAt: null }));
}

t('AT-HOOK-08 宣告了具體檔案然後零動作就結束,會擋', () => {
  const dir = sandbox();
  ledger(dir, [{ turn: 1, what: '修 imports.js 的路徑解析', targets: ['/p/imports.js'], at: Date.now() }]);
  const r = runHook(STOP, { hook_event_name: 'Stop', cwd: dir });
  assert.equal(r.code, 2, `預期 exit 2,得到 ${r.code}`);
  assert.match(r.stderr, /imports\.js/);
  assert.match(r.stderr, /declared this session with no matching action/);
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-09 同一輪不會擋第二次', () => {
  const dir = sandbox();
  ledger(dir, [{ turn: 1, what: '做某事', targets: ['/p/a.js'], at: Date.now() }]);
  const first = runHook(STOP, { hook_event_name: 'Stop', cwd: dir });
  const second = runHook(STOP, { hook_event_name: 'Stop', cwd: dir });
  assert.equal(first.code, 2);
  assert.equal(second.code, 0, '連擋兩次就變成「不做完不准停」');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-10 講不清楚要動哪個檔的宣告,驗不了就不擋', () => {
  const dir = sandbox();
  ledger(dir, [{ turn: 1, what: '之後再優化一下', targets: [], at: Date.now() }]);
  const r = runHook(STOP, { hook_event_name: 'Stop', cwd: dir });
  assert.equal(r.code, 0, '拿驗不了的東西擋人,是把工具的無能變成使用者的義務');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-11 沒有任何未結宣告時保持安靜', () => {
  const dir = sandbox();
  const r = runHook(STOP, { hook_event_name: 'Stop', cwd: dir });
  assert.equal(r.code, 0);
  assert.equal(r.stderr, '');
  rmSync(dir, { recursive: true, force: true });
});

// ── 壞掉的時候要讓路 ──────────────────────────────────────────

t('AT-HOOK-12 stdin 是垃圾就放行,不是崩在使用者臉上', () => {
  for (const script of [PRE, STOP]) {
    const r = spawnSync('node', [script], { input: 'not json at all', encoding: 'utf8' });
    assert.equal(r.status, 0, `${script} 收到壞輸入應該 exit 0`);
  }
});

t('AT-HOOK-13 狀態檔壞掉就放行', () => {
  const dir = sandbox(GOAL);
  writeFileSync(join(dir, '.forseti', 'state.json'), '{{{ 壞掉的 JSON');
  writeFileSync(join(dir, '.forseti', 'goal.json'), '{{{ 也壞掉');
  const r = runHook(PRE, about(dir, 's', '/anywhere.js'));
  assert.equal(r.code, 0, '壞掉的狀態檔不該擋住任何人的工作');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-14 非寫入工具直接放行', () => {
  const dir = sandbox(GOAL);
  const r = runHook(PRE, {
    hook_event_name: 'PreToolUse', session_id: 's', cwd: dir,
    tool_name: 'Read', tool_input: { file_path: '/elsewhere/anything.js' },
  });
  assert.equal(r.code, 0);
  rmSync(dir, { recursive: true, force: true });
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
