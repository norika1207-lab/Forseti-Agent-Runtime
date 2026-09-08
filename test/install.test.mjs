// 安裝腳本的端到端測試:真的跑這個腳本,真的看它寫出來的檔案。
//
// 這個腳本存在的唯一理由是 2026-09-08 那次事故的反面教材:
// 安裝跟啟用不可以是同一步,而且不管裝在哪裡,絕對不准寫進使用者層設定。
// 這裡測的就是這兩條硬約束,加上冪等性跟「不覆蓋已經手動開啟的設定」。
import { spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = dirname(HERE);
const SCRIPT = join(REPO, 'tools', 'install.mjs');

let pass = 0; let fail = 0;
function t(name, fn) {
  try { fn(); pass += 1; } catch (e) { fail += 1; console.error(`FAIL ${name}\n  ${e.message}`); }
}

function run(args) {
  const r = spawnSync('node', [SCRIPT, ...args], { encoding: 'utf8' });
  return { code: r.status, stdout: r.stdout ?? '', stderr: r.stderr ?? '' };
}

t('沒有帶目標目錄就報用法錯誤,不做任何事', () => {
  const r = run([]);
  assert.notEqual(r.code, 0);
  assert.match(r.stderr, /usage/);
});

t('拒絕安裝到家目錄,一個字都不准寫', () => {
  const r = run([homedir()]);
  assert.notEqual(r.code, 0);
  assert.match(r.stderr, /refusing to install/);
  assert.match(r.stderr, /every project on this machine/);
});

t('拒絕安裝到 Forseti repo 自己,那裡本來就無條件受保護', () => {
  const r = run([REPO]);
  assert.notEqual(r.code, 0);
  assert.match(r.stderr, /already protected unconditionally/);
});

t('目標目錄不存在就報錯', () => {
  const r = run([join(tmpdir(), 'forseti-install-does-not-exist-xyz')]);
  assert.notEqual(r.code, 0);
});

t('正常安裝:settings.json 三個 hook 都寫進去,config.json 預設關閉', () => {
  const dir = mkdtempSync(join(tmpdir(), 'forseti-install-'));
  const r = run([dir]);
  assert.equal(r.code, 0, r.stderr);
  assert.match(r.stdout, /does NOT do anything yet/);

  const settings = JSON.parse(readFileSync(join(dir, '.claude', 'settings.json'), 'utf8'));
  assert.equal(settings.hooks.PreToolUse.length, 1);
  assert.equal(settings.hooks.PostToolUse.length, 1);
  assert.equal(settings.hooks.Stop.length, 1);
  assert.match(settings.hooks.PreToolUse[0].hooks[0].command, /forseti-hook\.mjs/);
  assert.match(settings.hooks.Stop[0].hooks[0].command, /forseti-stop-hook\.mjs/);

  const config = JSON.parse(readFileSync(join(dir, '.forseti', 'config.json'), 'utf8'));
  assert.equal(config.cross_project_enabled, false);

  rmSync(dir, { recursive: true, force: true });
});

t('重複安裝不會疊加重複的 hook 項目', () => {
  const dir = mkdtempSync(join(tmpdir(), 'forseti-install-idem-'));
  run([dir]);
  const r2 = run([dir]);
  assert.equal(r2.code, 0, r2.stderr);
  assert.match(r2.stdout, /already present, no change/);
  const settings = JSON.parse(readFileSync(join(dir, '.claude', 'settings.json'), 'utf8'));
  assert.equal(settings.hooks.PreToolUse.length, 1);
  assert.equal(settings.hooks.PostToolUse.length, 1);
  assert.equal(settings.hooks.Stop.length, 1);
  rmSync(dir, { recursive: true, force: true });
});

t('目標已有其他 hook 設定,安裝時不動它,只附加自己的', () => {
  const dir = mkdtempSync(join(tmpdir(), 'forseti-install-merge-'));
  mkdirSync(join(dir, '.claude'), { recursive: true });
  writeFileSync(join(dir, '.claude', 'settings.json'), JSON.stringify({
    hooks: { PreToolUse: [{ matcher: 'Bash', hooks: [{ type: 'command', command: 'echo other' }] }] },
    permissions: { allow: ['Bash(ls:*)'] },
  }));
  const r = run([dir]);
  assert.equal(r.code, 0, r.stderr);
  const settings = JSON.parse(readFileSync(join(dir, '.claude', 'settings.json'), 'utf8'));
  assert.equal(settings.hooks.PreToolUse.length, 2, '既有的那個要留著,自己的附加上去');
  assert.deepEqual(settings.permissions, { allow: ['Bash(ls:*)'] }, '不相干的欄位不准被動到');
  rmSync(dir, { recursive: true, force: true });
});

t('settings.json 存在但不是合法 JSON,拒絕覆蓋,不猜使用者的意思', () => {
  const dir = mkdtempSync(join(tmpdir(), 'forseti-install-badjson-'));
  mkdirSync(join(dir, '.claude'), { recursive: true });
  writeFileSync(join(dir, '.claude', 'settings.json'), '{not valid json');
  const r = run([dir]);
  assert.notEqual(r.code, 0);
  assert.match(r.stderr, /not valid JSON/);
  assert.equal(readFileSync(join(dir, '.claude', 'settings.json'), 'utf8'), '{not valid json',
    '拒絕的話原始檔案要原封不動');
  rmSync(dir, { recursive: true, force: true });
});

t('已經手動開啟的 config.json,重新安裝不准把它關回去', () => {
  const dir = mkdtempSync(join(tmpdir(), 'forseti-install-preserve-on-'));
  mkdirSync(join(dir, '.forseti'), { recursive: true });
  writeFileSync(join(dir, '.forseti', 'config.json'), JSON.stringify({ cross_project_enabled: true }));
  const r = run([dir]);
  assert.equal(r.code, 0, r.stderr);
  assert.match(r.stdout, /already had cross_project_enabled: true - left it as-is/);
  const config = JSON.parse(readFileSync(join(dir, '.forseti', 'config.json'), 'utf8'));
  assert.equal(config.cross_project_enabled, true);
  rmSync(dir, { recursive: true, force: true });
});

t('端到端:裝完預設不生效,手動打開之後 hook 才真的動作', () => {
  // 這條把「安裝腳本寫出來的東西」跟「hook 實際讀的東西」串起來,
  // 不只是各自測過就假設兩邊格式相容。
  const dir = mkdtempSync(join(tmpdir(), 'forseti-install-e2e-'));
  const emptyHome = mkdtempSync(join(tmpdir(), 'forseti-install-e2e-home-'));
  const HOOK = join(REPO, 'hooks', 'forseti-hook.mjs');
  const runPre = () => spawnSync('node', [HOOK], {
    input: JSON.stringify({
      hook_event_name: 'PostToolUse', session_id: 'e2e', cwd: dir,
      tool_name: 'Write', tool_input: { file_path: join(dir, 'a.js') },
    }),
    encoding: 'utf8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: '', HOME: emptyHome, USERPROFILE: emptyHome },
  });

  run([dir]);   // 安裝,預設關閉
  runPre();
  assert.ok(!existsSync(join(dir, '.forseti', 'state.json')),
    '裝完但沒開,hook 不該對這個專案生效');

  const configPath = join(dir, '.forseti', 'config.json');
  const config = JSON.parse(readFileSync(configPath, 'utf8'));
  config.cross_project_enabled = true;
  writeFileSync(configPath, JSON.stringify(config));

  runPre();
  assert.ok(existsSync(join(dir, '.forseti', 'state.json')),
    '手動打開之後,同一個專案的 hook 要真的動作');

  rmSync(dir, { recursive: true, force: true });
  rmSync(emptyHome, { recursive: true, force: true });
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
