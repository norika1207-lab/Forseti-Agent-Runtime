#!/usr/bin/env node
/**
 * 量 hook 的延遲。
 *
 * 這個數字決定它會不會被拔掉。一個每次寫檔都要跑的 hook,
 * 慢到有感就會被關掉,而被關掉的守衛保護不了任何人。
 *
 * 量的是整個程序的 wall clock,包含 node 啟動 —— 因為使用者
 * 等的就是那個。只量模組函式的執行時間會得到一個漂亮但無關的數字。
 *
 *   node tools/latency.mjs [次數]
 */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, statSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const N = Number(process.argv[2] ?? 30);
const { createRuntime } = await import(join(HERE, '..', 'src', 'runtime.js'));

const dir = mkdtempSync(join(tmpdir(), 'forseti-lat-'));
mkdirSync(join(dir, '.forseti'), { recursive: true });
writeFileSync(join(dir, '.forseti', 'goal.json'),
  JSON.stringify({ north_star: '量延遲', scope: [dir] }));

function timeIt(script, payload) {
  const t = process.hrtime.bigint();
  spawnSync('node', [join(HERE, '..', 'hooks', script)], {
    input: JSON.stringify(payload), encoding: 'utf8',
  });
  return Number(process.hrtime.bigint() - t) / 1e6;
}

function stats(xs) {
  const s = [...xs].sort((a, b) => a - b);
  const q = (p) => s[Math.min(s.length - 1, Math.floor(s.length * p))];
  return { p50: q(0.5), p95: q(0.95), max: s[s.length - 1] };
}

const cases = {
  'PreToolUse 放行': ['forseti-hook.mjs', {
    hook_event_name: 'PreToolUse', session_id: 's', cwd: dir,
    tool_name: 'Write', tool_input: { file_path: join(dir, 'a.js') },
  }],
  'PostToolUse 記錄': ['forseti-hook.mjs', {
    hook_event_name: 'PostToolUse', session_id: 's', cwd: dir,
    tool_name: 'Write', tool_input: { file_path: join(dir, 'a.js') },
  }],
  'Stop 檢查': ['forseti-stop-hook.mjs', { hook_event_name: 'Stop', cwd: dir }],
};

console.log(`每項 ${N} 次,單位毫秒,含 node 啟動\n`);
console.log('情境                    p50      p95      max');
const rows = [];
for (const [name, [script, payload]] of Object.entries(cases)) {
  timeIt(script, payload);   // 暖機一次,不計入
  const xs = Array.from({ length: N }, () => timeIt(script, payload));
  const s = stats(xs);
  rows.push([name, s]);
  console.log(`${name.padEnd(22)} ${s.p50.toFixed(1).padStart(6)} ${s.p95.toFixed(1).padStart(8)} ${s.max.toFixed(1).padStart(8)}`);
}

// 一個純 node 空程序當底線,才知道多少是 Forseti、多少是 node 本身
const base = [];
for (let i = 0; i < N; i += 1) {
  const t = process.hrtime.bigint();
  spawnSync('node', ['-e', '0']);
  base.push(Number(process.hrtime.bigint() - t) / 1e6);
}
const b = stats(base);
console.log(`${'(node 空程序底線)'.padEnd(20)} ${b.p50.toFixed(1).padStart(6)} ${b.p95.toFixed(1).padStart(8)} ${b.max.toFixed(1).padStart(8)}`);
console.log(`\nForseti 自己的成本 = 上面減去底線。p50 約 ${(rows[0][1].p50 - b.p50).toFixed(1)} 到 ${(rows[2][1].p50 - b.p50).toFixed(1)} 毫秒。`);

/**
 * 規模。上面量的是空狀態,而 PostToolUse 每一次都要讀回整份狀態再寫出去。
 * 事件累積之後如果延遲跟著線性長,這個 hook 就會在長 session 的後半
 * 變成負擔 —— 而那正是最需要它的時候。
 *
 * 這一段是為了找出「什麼時候該截斷事件」,不是為了給一個好看的數字。
 */
console.log('\n事件累積之後(PostToolUse,含 node 啟動)\n');
console.log('事件數      p50      state.json');
for (const n of [0, 100, 500, 2000, 10000]) {
  const d = mkdtempSync(join(tmpdir(), 'forseti-scale-'));
  mkdirSync(join(d, '.forseti'), { recursive: true });
  const post = {
    hook_event_name: 'PostToolUse', session_id: 's', cwd: d,
    tool_name: 'Write', tool_input: { file_path: join(d, 'a.js') },
  };
  // 直接灌進 runtime 再存檔。用 hook 一筆一筆餵的話,
  // 一萬筆就是一萬次 node 啟動,量的會是預填成本而不是延遲。
  if (n > 0) {
    const rt = createRuntime();
    rt.ingest(Array.from({ length: n }, (_, i) => ({
      attributed_agent: 's', session_id: 's', name: 'Write',
      input: { file_path: join(d, `f${i}.js`) }, at: Date.now() - (n - i) * 1000,
    })));
    writeFileSync(join(d, '.forseti', 'state.json'), rt.save());
  }
  const xs = Array.from({ length: 12 }, () => timeIt('forseti-hook.mjs', post));
  const sz = existsSync(join(d, '.forseti', 'state.json'))
    ? (statSync(join(d, '.forseti', 'state.json')).size / 1024).toFixed(0) + ' KB' : '-';
  console.log(`${String(n).padEnd(10)} ${stats(xs).p50.toFixed(1).padStart(6)} ms   ${sz}`);
  rmSync(d, { recursive: true, force: true });
}

rmSync(dir, { recursive: true, force: true });
