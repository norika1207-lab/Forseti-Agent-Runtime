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
import { mkdtempSync, writeFileSync, mkdirSync, rmSync, readFileSync, readdirSync, existsSync } from 'node:fs';
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

const REPO = dirname(HERE);

/**
 * 沙箱建在 repo 底下,不是 /tmp。
 *
 * hook 有一道硬邊界:只在它自己所屬的 repo 底下作用,外面什麼都不做。
 * 那道邊界是 2026-09-08 擋掉擁有者整晚工作之後加的,不可以為了讓測試
 * 好寫就繞過它。所以要測偵測邏輯,就得在邊界之內測。
 *
 * repo 外的沙箱留給邊界測試本身(AT-HOOK-B1/B2)。
 */
function sandbox(goal) {
  const dir = mkdtempSync(join(REPO, '.tmp-e2e-'));
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

t('AT-HOOK-01 另一個 session 剛寫過同一個檔,會講但不擋', () => {
  const dir = sandbox();
  runHook(PRE, write(dir, 'session-aaaaaaaa', join(REPO, '.tmp-shared.js')));
  const r = runHook(PRE, about(dir, 'session-bbbbbbbb', join(REPO, '.tmp-shared.js')));
  assert.equal(r.code, 0, '撞車是機率不是硬前提,閘門不放行擋人');
  assert.match(r.stderr, /another session wrote/, '不擋不等於不說');
  assert.match(r.stderr, /session-/, '訊息要指出是誰');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-02 是自己剛寫的,不擋', () => {
  const dir = sandbox();
  runHook(PRE, write(dir, 'same-session', join(REPO, '.tmp-mine.js')));
  const r = runHook(PRE, about(dir, 'same-session', join(REPO, '.tmp-mine.js')));
  assert.equal(r.code, 0, '自己寫自己的檔不該被擋');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-03 沒人碰過的檔,不擋', () => {
  const dir = sandbox();
  const r = runHook(PRE, about(dir, 'session-x', join(REPO, '.tmp-fresh.js')));
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
  assert.deepEqual(codes, [0, 0, 0, 0, 0], '從頭到尾都不准擋');
  const last = runHook(PRE, about(dir, 's', '/elsewhere/other6.js'));
  assert.match(last.stderr, /scope/i, '不擋,但要開口');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-05 離題的提醒要帶著北極星,不然擋了也沒用', () => {
  const dir = sandbox(GOAL);
  let last;
  for (let i = 0; i < 6; i += 1) last = runHook(PRE, about(dir, 's', `/elsewhere/x${i}.js`));
  assert.equal(last.code, 0);
  assert.match(last.stderr, /聚焦完成 Forseti/, '提醒必須複述目標');
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
  for (let i = 0; i < 6; i += 1) {
    last = runHook(PRE, about(elsewhere, 's', `/way/off/${i}.js`), { HOME: home });
  }
  assert.equal(last.code, 0, '在別人的目錄裡更不准擋');
  assert.match(last.stderr, /聚焦完成 Forseti/, '離開專案目錄之後偵測不該就此關機');
  rmSync(home, { recursive: true, force: true });
  rmSync(elsewhere, { recursive: true, force: true });
});

t('AT-HOOK-07c 專案的北極星蓋過家目錄的', () => {
  const home = sandbox({ north_star: '家目錄的目標', scope: ['/nowhere'] });
  const proj = sandbox({ north_star: '專案自己的目標', scope: ['/nowhere'] });
  let last;
  for (let i = 0; i < 6; i += 1) last = runHook(PRE, about(proj, 's', `/x/${i}.js`), { HOME: home });
  assert.equal(last.code, 0);
  assert.match(last.stderr, /專案自己的目標/);
  rmSync(home, { recursive: true, force: true });
  rmSync(proj, { recursive: true, force: true });
});

// ── 說了沒做 ──────────────────────────────────────────────────

function ledger(dir, open) {
  writeFileSync(join(dir, '.forseti', 'declarations.json'), JSON.stringify({ open, blockedAt: null }));
}

t('AT-HOOK-08 宣告了具體檔案然後零動作就結束,會講但不擋', () => {
  const dir = sandbox();
  ledger(dir, [{ turn: 1, what: '修 imports.js 的路徑解析', targets: ['/p/imports.js'], at: Date.now() }]);
  const r = runHook(STOP, { hook_event_name: 'Stop', cwd: dir });
  assert.equal(r.code, 0, '「你不做完不准停」會把該停下來問人的情況也擋掉');
  assert.match(r.stderr, /imports\.js/);
  assert.match(r.stderr, /not a block/, '要明說這是觀察不是攔阻');
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-09 連續結束回合都不會擋', () => {
  const dir = sandbox();
  ledger(dir, [{ turn: 1, what: '做某事', targets: ['/p/a.js'], at: Date.now() }]);
  const first = runHook(STOP, { hook_event_name: 'Stop', cwd: dir });
  const second = runHook(STOP, { hook_event_name: 'Stop', cwd: dir });
  assert.equal(first.code, 0);
  assert.equal(second.code, 0);
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

// ── 硬邊界:只准在自己的 repo 底下作用 ─────────────────────

t('AT-HOOK-B1 repo 外面完全不動作,連狀態檔都不建', () => {
  // 上次出事的根因不是門檻,是範圍。所以範圍不只靠設定檔的位置保證,
  // 程式碼自己也要守。這條測的是程式碼那一道。
  const outside = mkdtempSync(join(tmpdir(), 'forseti-outside-'));
  const home = sandbox(GOAL);   // 家目錄有北極星,正是上次讓它在外面生效的東西
  for (const payload of [
    write(outside, 'x', join(outside, 'a.js')),
    about(outside, 'x', join(outside, 'a.js')),
  ]) {
    assert.equal(runHook(PRE, payload, { HOME: home }).code, 0);
  }
  assert.equal(runHook(STOP, { hook_event_name: 'Stop', cwd: outside }, { HOME: home }).code, 0);
  assert.equal(readdirSync(outside).length, 0, 'repo 外面連一個檔案都不准建');
  rmSync(outside, { recursive: true, force: true });
  rmSync(home, { recursive: true, force: true });
});

t('AT-HOOK-B2 CLAUDE_PROJECT_DIR 指到外面也擋得住', () => {
  const outside = mkdtempSync(join(tmpdir(), 'forseti-outside2-'));
  const r = runHook(PRE, write(outside, 'x', join(outside, 'a.js')),
    { CLAUDE_PROJECT_DIR: outside });
  assert.equal(r.code, 0);
  assert.equal(readdirSync(outside).length, 0);
  rmSync(outside, { recursive: true, force: true });
});

t('AT-HOOK-B3 repo 裡面照常運作,邊界不是把功能關掉', () => {
  const repo = dirname(HERE);
  const r = runHook(PRE, {
    hook_event_name: 'PostToolUse', session_id: 'insider', cwd: repo,
    tool_name: 'Write', tool_input: { file_path: join(repo, 'src', 'drift.js') },
  });
  assert.equal(r.code, 0);
  const state = join(repo, '.forseti', 'state.json');
  assert.ok(existsSync(state), '在自己家裡要照常記錄');
  rmSync(state, { force: true });
  rmSync(join(repo, '.forseti', 'streak.json'), { force: true });
});

t('AT-HOOK-B4 insideRepo() 本身不可以被設定影響,也不准有無條件繞過開關', () => {
  // 2026-09-08 之後,repo 自己的保護(insideRepo)跟能不能監控別的專案
  // (crossProjectEnabled)是兩條分開的路。這條只守前者:Forseti repo
  // 自己的保護必須永遠是無條件的、寫死的,不能因為任何設定檔而被關掉。
  // 「允許監控別的專案」不是繞過,是 owner 明確要的新功能,見 B5-B7。
  for (const f of ['forseti-hook.mjs', 'forseti-stop-hook.mjs']) {
    const text = readFileSync(join(HERE, '..', 'hooks', f), 'utf8');
    assert.match(text, /insideRepo\(/, `${f} 要呼叫邊界檢查`);
    assert.ok(!/allowOutside|SKIP_BOUNDARY/.test(text),
      `${f} 不准有無條件繞過整條邊界的開關`);
    // insideRepo 的函式本體(從定義到右大括號)不准提到任何設定或環境變數。
    const body = text.match(/function insideRepo\([^)]*\)\s*\{[\s\S]*?\n\}/)?.[0] ?? '';
    assert.ok(body.length > 0, `${f} 要找得到 insideRepo 的函式本體`);
    assert.ok(!/config|process\.env/.test(body),
      `${f} 的 insideRepo() 本身不准看設定或環境變數,那是 crossProjectEnabled 的事`);
  }
});

t('AT-HOOK-E1 PostToolUse 真的留下 Evidence Receipt,而且跨程序讀得回來', () => {
  // FS-TMP-001 只能在事件當下滿足:檔案被改過之後,當時的大小與指紋
  // 就永遠沒有了。這條開真的程序、寫真的檔、再開第二個程序讀回來 ——
  // 同一個 process 裡的測試抓不到這件事,而 hook 每次都是新程序。
  const work = sandbox();
  const target = join(work, 'out.md');
  writeFileSync(target, 'hello receipt');

  const r = runHook(PRE, {
    hook_event_name: 'PostToolUse', session_id: 'e1', cwd: work,
    tool_name: 'Write', tool_input: { file_path: target },
    tool_response: { exit_code: 0 },
  });
  assert.equal(r.code, 0);

  const statePath = join(work, '.forseti', 'state.json');
  assert.ok(existsSync(statePath), 'PostToolUse 要寫下狀態');
  const body = JSON.parse(JSON.parse(readFileSync(statePath, 'utf8')).body);
  assert.ok(Array.isArray(body.receipts), '存檔裡要有 receipts 區塊');
  assert.equal(body.receipts.length, 1);
  const receipt = body.receipts[0];
  assert.equal(receipt.resource_locator, target);
  assert.equal(receipt.existence, true);
  assert.equal(receipt.byte_size, 'hello receipt'.length);
  assert.ok(receipt.content_hash, '指紋要在事件當下留下來');
  assert.match(receipt.capture_method, /^PostToolUse:/);

  rmSync(work, { recursive: true, force: true });
});

t('AT-HOOK-E2 檔案量不到時,憑證的 existence 是 unknown 不是 false', () => {
  const work = sandbox();
  const missing = join(work, 'never-written.md');
  const r = runHook(PRE, {
    hook_event_name: 'PostToolUse', session_id: 'e2', cwd: work,
    tool_name: 'Write', tool_input: { file_path: missing },
  });
  assert.equal(r.code, 0);
  const body = JSON.parse(JSON.parse(readFileSync(join(work, '.forseti', 'state.json'), 'utf8')).body);
  assert.equal(body.receipts[0].existence, 'unknown', '量不到不等於不存在');
  assert.equal(body.receipts[0].byte_size, null, '拿不到的值是 null,不是 0');
  rmSync(work, { recursive: true, force: true });
});

t('AT-HOOK-B5 跨專案開關預設關閉:沒有設定檔的外部目錄完全不動作', () => {
  const outside = mkdtempSync(join(tmpdir(), 'forseti-outside-noconf-'));
  const r = runHook(PRE, write(outside, 'x', join(outside, 'a.js')));
  assert.equal(r.code, 0);
  assert.equal(readdirSync(outside).length, 0, '沒開關就不准動,連狀態檔都不建');
  rmSync(outside, { recursive: true, force: true });
});

t('AT-HOOK-B6 跨專案開關存在但沒開,外部目錄依然不動作', () => {
  const outside = mkdtempSync(join(tmpdir(), 'forseti-outside-off-'));
  mkdirSync(join(outside, '.forseti'), { recursive: true });
  writeFileSync(join(outside, '.forseti', 'config.json'),
    JSON.stringify({ cross_project_enabled: false }));
  const r = runHook(PRE, write(outside, 'x', join(outside, 'a.js')));
  assert.equal(r.code, 0);
  assert.deepEqual(readdirSync(join(outside, '.forseti')), ['config.json'],
    '除了自己寫的設定檔,不該多出任何東西');
  rmSync(outside, { recursive: true, force: true });
});

t('AT-HOOK-B6b 壞掉或非布林值的開關,一律當作關閉,不能意外生效', () => {
  for (const bad of ['{invalid json', JSON.stringify({ cross_project_enabled: 'true' }), '{}']) {
    const outside = mkdtempSync(join(tmpdir(), 'forseti-outside-bad-'));
    mkdirSync(join(outside, '.forseti'), { recursive: true });
    writeFileSync(join(outside, '.forseti', 'config.json'), bad);
    const r = runHook(PRE, write(outside, 'x', join(outside, 'a.js')));
    assert.equal(r.code, 0, `payload=${bad}`);
    assert.deepEqual(readdirSync(join(outside, '.forseti')), ['config.json'], `payload=${bad}`);
    rmSync(outside, { recursive: true, force: true });
  }
});

t('AT-HOOK-B7 設定檔明確寫 cross_project_enabled:true,外部目錄才真的受保護', () => {
  const outside = mkdtempSync(join(tmpdir(), 'forseti-outside-on-'));
  mkdirSync(join(outside, '.forseti'), { recursive: true });
  writeFileSync(join(outside, '.forseti', 'config.json'),
    JSON.stringify({ cross_project_enabled: true }));
  const r = runHook(PRE, write(outside, 'x', join(outside, 'a.js')));
  assert.equal(r.code, 0);
  assert.ok(existsSync(join(outside, '.forseti', 'state.json')),
    '明確開啟之後,PostToolUse 要真的記錄狀態');
  rmSync(outside, { recursive: true, force: true });
});

// ── 2026-09-08 的迴歸:整晚被擋 ─────────────────────────────

t('AT-HOOK-R1 重現整晚被擋的那個場景,一次都不准 deny', () => {
  // 事發經過:家目錄的 goal.json 只寫著某一個專案的路徑,
  // 而 hook 的 fallback 讓那個 scope 對整台機器每一個目錄生效。
  // 擁有者其他所有工作,連續寫五個檔就被 deny 一次,streak 不會自己清掉。
  // 九個小時。留下的證據是 streak.json 的 total_checked:12, total_off:8。
  //
  // 這條測試守的是:不管離題多少次,都不准回非零。
  // 在邊界之內測,不然通過的是邊界不是閘門,而閘門才是這條要守的東西。
  const work = sandbox({ north_star: '只做專案 A', scope: [join(REPO, 'nowhere-near-here')] });
  const codes = [];
  for (let i = 0; i < 30; i += 1) {
    codes.push(runHook(PRE, about(work, 'night-shift', join(work, `file${i}.js`)), {}).code);
  }
  assert.deepEqual(codes, Array(30).fill(0), `30 次全部要放行,實際:${[...new Set(codes)].join(',')}`);
  rmSync(work, { recursive: true, force: true });
});

t('AT-HOOK-R2 撞車也不准 deny,除非閘門真的放行', async () => {
  // 閘門要的是「授權、授權範圍或安全性的硬前提未知」。
  // 撞車是機率,不是前提,所以它拿不到放行。
  const { canIntervene } = await import('../src/intervention.js');
  const g = canIntervene('BLOCK_HIGH_RISK', { collision: true, other_sessions: 3 });
  assert.equal(g.allowed, false, '撞車不該拿得到硬擋的許可');
  const dir = sandbox();
  runHook(PRE, write(dir, 'a', join(REPO, '.tmp-hot.js')));
  for (let i = 0; i < 5; i += 1) {
    assert.equal(runHook(PRE, about(dir, 'b', join(REPO, '.tmp-hot.js'))).code, 0, '連續撞車也不准擋');
  }
  rmSync(dir, { recursive: true, force: true });
});

t('AT-HOOK-R3 三個 hook 的原始碼裡不准有沒問過閘門的 exit(2)', () => {
  for (const f of ['forseti-hook.mjs', 'forseti-stop-hook.mjs']) {
    // 先把註解換成等長的空行,不然這條會抓到解釋這件事的註解本身。
    const text = readFileSync(join(HERE, '..', 'hooks', f), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
      .replace(/^([^\n]*?)\/\/[^\n]*$/gm, (m, keep) => keep);
    const lines = text.split('\n');
    lines.forEach((line, i) => {
      if (!/process\.exit\(2\)/.test(line)) return;
      // 往上找 15 行,必須看得到閘門
      const before = lines.slice(Math.max(0, i - 15), i).join('\n');
      assert.match(before, /g\.allowed|gate\(/,
        `${f}:${i + 1} 有一個沒問過閘門的 exit(2)。這正是擋掉擁有者一整晚的那種寫法。`);
    });
  }
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
