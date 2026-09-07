#!/usr/bin/env node
/**
 * 現在生效的北極星是哪一份。
 *
 * hook 找北極星的順序是「先專案,再家目錄」,而那個 fallback 本身
 * 製造了一個新陷阱:兩份檔案可以不一樣,改了不生效的那一份不會有
 * 任何跡象 —— 沒有錯誤、沒有警告,偵測器就是安靜地照舊。
 *
 * 這跟北極星原本從沒進版控、搬碟後整條靜默關閉是同一類問題:
 * 設定失效的時候看起來跟一切正常一模一樣。
 *
 *   node tools/goal.mjs [工作目錄]
 */
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const cwd = process.argv[2] || process.cwd();
const home = process.env.HOME || process.env.USERPROFILE;

const candidates = [
  ['專案', join(cwd, '.forseti', 'goal.json')],
  ['家目錄', home ? join(home, '.forseti', 'goal.json') : null],
].filter(([, p]) => p);

const found = [];
for (const [label, p] of candidates) {
  if (!existsSync(p)) { console.log(`  ${label.padEnd(6)} 沒有  ${p}`); continue; }
  try {
    found.push([label, p, JSON.parse(readFileSync(p, 'utf8'))]);
  } catch (e) {
    console.log(`  ${label.padEnd(6)} 壞了  ${p}\n         ${e.message}`);
    console.log('         hook 讀不動壞掉的檔案時會直接放行,偵測整條關閉。');
  }
}

console.log(`工作目錄  ${cwd}\n`);
if (!found.length) {
  console.log('  找不到任何北極星。離題偵測是關閉的,而且它不會告訴你。');
  console.log('  這是照設計走的:沒有錨點就不准說人飄移。');
  process.exit(1);
}

const [label, path, goal] = found[0];
console.log(`生效的是「${label}」那一份`);
console.log(`  ${path}\n`);
console.log(`  北極星  ${goal.north_star ?? '(沒寫)'}`);
console.log(`  範圍    ${(goal.scope ?? []).length} 條`);
for (const s of goal.scope ?? []) console.log(`            ${s}`);

if (found.length > 1) {
  const other = found[1];
  const same = JSON.stringify(other[2]) === JSON.stringify(goal);
  console.log(`\n另外還有一份「${other[0]}」的:`);
  console.log(`  ${other[1]}`);
  if (same) {
    console.log('  內容一樣,所以現在看不出差別。改動其中一份就會開始分歧。');
  } else {
    console.log('  ★ 內容不一樣。在這個目錄底下工作時,它不會生效。');
    console.log(`     它的北極星是：${other[2].north_star ?? '(沒寫)'}`);
    console.log('     兩份的用途本來就可以不同:專案那份是這個 repo 的完成定義,');
    console.log('     家目錄那份是「我這陣子在做什麼」。不同不見得是錯,');
    console.log('     但改錯邊會完全沒有反應,所以這裡把它講出來。');
  }
}

const done = goal.done_when ?? [];
if (done.length) {
  console.log('\n完成的定義:');
  for (const d of done) console.log(`  · ${d}`);
  console.log('\n  這個工具不判斷它們達成了沒。判斷要靠證據,不是靠讀設定檔。');
}
