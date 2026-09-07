#!/usr/bin/env node
/**
 * 有沒有模組寫了卻沒有人用。
 *
 *   node tools/orphans.mjs [src-dir]
 *
 * 這個檢查在這個 repo 裡抓到過四次「模組全對，接線漏掉」:
 * shell.js、capsule.js、conformance/followthrough/rhetoric/scope 那批、
 * 以及 baseline 與 overhead。每一次單元測試都是綠的。
 *
 * ── 為什麼要做成工具而不是一行指令 ────────────────────
 *
 * 因為它被各處各自重寫了三次,而第三次寫錯了:
 * 檔案清單沒有濾掉 macOS 的 `._` sidecar,於是那個 sidecar
 * 不在依賴圖裡,就被判成孤立模組,連續兩次產生假警報。
 *
 * 一個到處被複製貼上的檢查,遲早會有一份是錯的。
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildImportRecords } from '../src/imports.js';
import { buildGraph, computeCostVector } from '../src/cost.js';

const dir = process.argv[2] ?? join(fileURLToPath(new URL('..', import.meta.url)), 'src');

/** 進入點:沒有人依賴它是正常的,不是孤立。 */
const ENTRY = /(^|\/)(runtime|index|main)\.js$/;
/** macOS 在 exFAT 與網路磁碟上寫的 AppleDouble sidecar,不是原始碼。 */
const NOT_SOURCE = /(^|\/)\._/;

const files = readdirSync(dir)
  .filter((f) => f.endsWith('.js') && !NOT_SOURCE.test(f))
  .map((f) => join(dir, f));

if (!files.length) {
  console.log('沒有找到任何 .js');
  process.exit(0);
}

const sources = Object.fromEntries(files.map((f) => [f, readFileSync(f, 'utf8')]));
const { imports, stats } = buildImportRecords(sources);
const graph = buildGraph(imports);

const orphans = files.filter((f) => !ENTRY.test(f) && computeCostVector(graph, f).d1_count === 0);

console.log(`掃描 ${files.length} 個模組` + (stats.skipped_non_source ? `（濾掉 ${stats.skipped_non_source} 個非原始碼檔）` : ''));
if (orphans.length) {
  console.log(`\n★ ${orphans.length} 個模組沒有任何人依賴：`);
  for (const o of orphans) console.log(`   ${o.split('/').pop()}`);
  console.log('\n寫了、測了，然後沒有接上。單元測試不會告訴你這件事。');
  process.exit(1);
}
console.log('零孤立模組。');
