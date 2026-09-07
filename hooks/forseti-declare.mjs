#!/usr/bin/env node
/**
 * 記一筆宣告,給 Stop hook 用。
 *
 *   node hooks/forseti-declare.mjs <project-dir> "<what>" <file> [file...]
 *
 * 這是給人或給 agent 主動叫的:說了要做什麼,就登記進去。
 * 回合結束時 Stop hook 會檢查它們有沒有被兌現。
 *
 * 不點名具體檔案的宣告會被拒絕,而且會說為什麼 —— 那種宣告驗不了,
 * 而登記一個驗不了的宣告只會讓帳面好看。
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';

const [dir, what, ...targets] = process.argv.slice(2);
if (!dir || !what) {
  console.error('usage: forseti-declare.mjs <project-dir> "<what>" <file> [file...]');
  process.exit(1);
}
if (!targets.length) {
  console.error('Refused: a declaration with no concrete target cannot be checked later.');
  console.error('Name the files this will touch.');
  process.exit(1);
}

const p = join(dir, '.forseti', 'declarations.json');
let led = { open: [], blockedAt: null };
if (existsSync(p)) { try { led = JSON.parse(readFileSync(p, 'utf8')); } catch { /* 壞了就重來 */ } }

led.open = [...(led.open ?? []), {
  id: 'd' + Date.now(),
  at: Date.now(),
  turn: (led.open ?? []).length,
  what,
  targets,
  awaiting: false,
}];   // 不寫 verifiable:重複的真相來源。resolve() 自己從 targets 算。
mkdirSync(dirname(p), { recursive: true });
writeFileSync(p, JSON.stringify(led));
console.log(`declared: ${targets.join(', ')}`);
