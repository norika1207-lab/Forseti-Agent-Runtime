#!/usr/bin/env node
/**
 * 把 Forseti 的即時 hook 接到另一個專案。
 *
 * 裝完不會生效。要生效必須自己手動把目標專案 `.forseti/config.json` 的
 * `cross_project_enabled` 改成 true —— 這個腳本刻意不提供一鍵開啟的選項。
 *
 * 2026-09-08 owner 的裁決:先把「監控別的專案」這個能力寫出來,但不准
 * 讓它自動生效。上次事故的教訓不是門檻設太敏感,是範圍在沒有人確認過
 * 的情況下自己擴大了 —— 這裡不重蹈覆轍:安裝跟啟用是兩個分開的、
 * 都需要人動手的步驟,而且啟用永遠不能靠跑一個腳本完成。
 *
 * 用法:
 *   node tools/install.mjs <target-project-dir>
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname, resolve as resolvePath } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir } from 'node:os';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolvePath(HERE, '..');

function fail(msg) {
  process.stderr.write('install.mjs: ' + msg + '\n');
  process.exit(1);
}

const targetArg = process.argv[2];
if (!targetArg) fail('usage: node tools/install.mjs <target-project-dir>');

const target = resolvePath(targetArg);
if (!existsSync(target)) fail(`${target} does not exist`);

/**
 * 硬擋:絕對不准寫進使用者層設定。
 *
 * 判準只有一條,不用猜:目標目錄本身就是家目錄。Claude Code 的
 * `.claude/settings.json` 放在家目錄下就是 User 層,對整台機器每個
 * 專案生效;放在其他任何資料夾都是 Shared project 層,只對那個資料夾
 * 生效。這條邊界不是提醒,是拒絕執行。
 */
const home = resolvePath(homedir());
if (target === home) {
  fail(
    `refusing to install into ${target} - installing here would write to `
    + `${join(home, '.claude', 'settings.json')}, which Claude Code applies to every `
    + 'project on this machine, not just one. Point this at one specific project '
    + 'directory instead. Full account of what happened the one time this boundary was '
    + 'crossed: docs/工程規格書.md §9.2.',
  );
}
if (target === REPO_ROOT) {
  fail(
    `${target} is this Forseti repo itself - it is already protected unconditionally `
    + '(see insideRepo() in hooks/forseti-hook.mjs), no install needed. This tool is for '
    + 'installing Forseti into a *different* project.',
  );
}

const settingsPath = join(target, '.claude', 'settings.json');
const hookCmd = (name) => `node "${join(REPO_ROOT, 'hooks', name)}"`;

function loadSettings(p) {
  if (!existsSync(p)) return {};
  try {
    return JSON.parse(readFileSync(p, 'utf8'));
  } catch {
    fail(`${p} exists but is not valid JSON. Fix it by hand first - `
      + 'this tool will not overwrite a file it cannot parse.');
  }
}

function hasForsetiHook(list, cmd) {
  return (list ?? []).some((entry) => (entry.hooks ?? []).some((h) => h.command === cmd));
}

const settings = loadSettings(settingsPath);
settings.hooks ??= {};

const preCmd = hookCmd('forseti-hook.mjs');
const stopCmd = hookCmd('forseti-stop-hook.mjs');

let changed = false;
for (const event of ['PreToolUse', 'PostToolUse']) {
  settings.hooks[event] ??= [];
  if (!hasForsetiHook(settings.hooks[event], preCmd)) {
    settings.hooks[event].push({
      matcher: 'Write|Edit|MultiEdit|NotebookEdit',
      hooks: [{ type: 'command', command: preCmd }],
    });
    changed = true;
  }
}
settings.hooks.Stop ??= [];
if (!hasForsetiHook(settings.hooks.Stop, stopCmd)) {
  settings.hooks.Stop.push({ hooks: [{ type: 'command', command: stopCmd }] });
  changed = true;
}

mkdirSync(dirname(settingsPath), { recursive: true });
writeFileSync(settingsPath, JSON.stringify(settings, null, 2) + '\n');

const configPath = join(target, '.forseti', 'config.json');
let config = {};
if (existsSync(configPath)) {
  try { config = JSON.parse(readFileSync(configPath, 'utf8')); } catch { config = {}; }
}
const alreadyEnabled = config.cross_project_enabled === true;
if (config.cross_project_enabled !== true) config.cross_project_enabled = false;

mkdirSync(dirname(configPath), { recursive: true });
writeFileSync(configPath, JSON.stringify(config, null, 2) + '\n');

process.stdout.write(
  `Installed Forseti hooks into ${settingsPath}${changed ? '' : ' (already present, no change)'}.\n`
  + `Wrote ${configPath} with cross_project_enabled: ${config.cross_project_enabled}.\n\n`
  + (alreadyEnabled
    ? 'This project already had cross_project_enabled: true - left it as-is.\n'
    : 'This does NOT do anything yet. Forseti will not touch this project until you '
      + `manually edit ${configPath} and set "cross_project_enabled": true.\n`
      + 'Read hooks/README.md before you do - the 2026-09-08 incident this whole switch '
      + 'exists because of was exactly this kind of scope turning on before anyone had '
      + 'confirmed the effect.\n'),
);
