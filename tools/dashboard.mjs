#!/usr/bin/env node
/**
 * Forseti 本地儀表板。
 *
 *   node tools/dashboard.mjs [project-dir] [--port 7777]
 *
 * 規格書 v0.1 第 8.4 節對 CLI 宿主的建議:terminal side panel、status line
 * 或 local web dashboard。這是第三種。
 *
 * ── 第 8.1 節的規矩,寫死在這裡 ────────────────────────
 *
 *   HEALTHY   只有一個小指示器
 *   WATCH     指示器變狀態,不跳任何對話框
 *   ELEVATED  滑過或點開才顯示一行原因
 *   HIGH      可展開的診斷卡,含最大貢獻訊號與已驗證進展的年齡
 *   CRITICAL  救援卡,而且只有在介入條件也成立時才出現
 *
 * 「安靜」是預設,不是選項。一個在健康狀態下還一直閃的儀表板,
 * 會被關掉,而被關掉的儀表板什麼都保護不了。
 *
 * ── 這個儀表板不碰被觀測的那個 session ────────────────
 *
 * 規格書第 9.1 節:不可以持續盤問被觀測的模型。
 * 所以這裡只讀狀態檔,不送任何東西進去,也不寫入。
 * 它是完全被動的一面鏡子。
 *
 * 零依賴,只用 node 內建的 http 與 fs。
 */
import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const portArg = args.indexOf('--port');
const PORT = portArg >= 0 ? Number(args[portArg + 1]) : 7777;
const PROJECT = args.find((a) => !a.startsWith('--') && a !== String(PORT)) ?? process.cwd();
const STATE = join(PROJECT, '.forseti', 'state.json');

async function readState() {
  if (!existsSync(STATE)) return { error: `No state file at ${STATE}. Install the hook first (see hooks/README.md).` };
  try {
    const { createRuntime } = await import(join(HERE, '..', 'src', 'runtime.js'));
    const rt = createRuntime();
    const restored = rt.restore(readFileSync(STATE, 'utf8'));
    if (!restored.state) return { error: 'State file could not be read.', warnings: restored.warnings };
    return {
      status: rt.status(),
      drift: rt.driftCheck(),
      liveness: rt.liveness(),
      artifacts: rt.artifactHealth(),
      temperature: rt.runtimeTemperature(),
      signals: rt.signals(),
      interventions: rt.interventionStats(),
      warnings: restored.warnings,
      stale: restored.stale_scopes.length,
      gap_ms: restored.gap_ms,
    };
  } catch (e) {
    return { error: 'Failed to read state: ' + e.message };
  }
}

const HTML = readFileSync(join(HERE, 'dashboard.html'), 'utf8');

createServer(async (req, res) => {
  if (req.url === '/state.json') {
    const data = await readState();
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' });
    res.end(JSON.stringify(data));
    return;
  }
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' });
  res.end(HTML);
}).listen(PORT, '127.0.0.1', () => {
  console.log(`Forseti dashboard  http://127.0.0.1:${PORT}`);
  console.log(`Reading  ${STATE}`);
  console.log('Read-only. Nothing is written, and nothing is sent to the observed session.');
});
