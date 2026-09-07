#!/usr/bin/env node
/**
 * 現在該做什麼。
 *
 *   node tools/focus.mjs [--goal <path>] [--transcript <path>]
 *
 * 這個工具回答一個問題:對照宣告過的目標,現在最該做的下一件事是什麼,
 * 以及有沒有說了要做而沒做的東西擋在前面。
 *
 * ── 為什麼需要它 ────────────────────────────────────
 *
 * 因為當事人會忘。不是比喻 —— 掃自己的 transcript 時,
 * 當事人以為犯過兩次「說了不做」,擁有者說至少五次,工具數出來二十三次。
 * 記憶是三個數字裡唯一不可靠的那個,而它偏偏是預設用的那個。
 *
 * ── 它不做什麼 ──────────────────────────────────────
 *
 * 不排序、不評分、不猜哪件事比較重要。那是擁有者的判斷。
 * 它只把三件事並排:目標是什麼、什麼還沒兌現、規格上還缺什麼。
 * 排序這件事交給看的人,因為排錯的成本由看的人承擔。
 */
import { readFileSync, existsSync } from 'node:fs';
import { declare, resolve, followThroughRate } from '../src/followthrough.js';

const args = process.argv.slice(2);
const val = (flag) => { const i = args.indexOf(flag); return i >= 0 ? args[i + 1] : null; };
const GOAL_PATH = val('--goal') ?? '.forseti/goal.json';
const TRANSCRIPT = val('--transcript');

// ── 目標 ──────────────────────────────────────────
let goal = null;
if (existsSync(GOAL_PATH)) {
  try { goal = JSON.parse(readFileSync(GOAL_PATH, 'utf8')); } catch { goal = null; }
}

console.log('\n' + '═'.repeat(68));
if (!goal) {
  console.log('  目標：未宣告');
  console.log('═'.repeat(68));
  console.log(`\n  沒有 ${GOAL_PATH}。沒有宣告過的目標時,飄移偵測只能對著`);
  console.log('  推出來的錨點量,而規格書 4.1 說那種讀數只能是機率性的。');
  console.log('\n  建立它：');
  console.log('  {"north_star": "...", "done_when": ["...", "..."], "not_now": ["..."]}');
} else {
  console.log(`  北極星：${goal.north_star ?? '(未填)'}`);
  console.log('═'.repeat(68));
  if (goal.done_when?.length) {
    console.log('\n  完成的定義：');
    for (const d of goal.done_when) console.log(`    · ${d}`);
  }
  if (goal.not_now?.length) {
    console.log('\n  刻意現在不做（範圍擴張是停擺的前置條件）：');
    for (const d of goal.not_now) console.log(`    · ${d}`);
  }
}

// ── 未兌現 ────────────────────────────────────────
if (TRANSCRIPT && existsSync(TRANSCRIPT)) {
  const DECLARE = /(我(現在|接著|等一下|馬上|先)?(來|去)?(寫|做|實作|接線|接完|補上|開始|修|加)|開始寫|接下來我做|動手|做掉)/;
  const ASKING = /(你說|妳說|要不要|好嗎[?？]|可以嗎[?？]|你決定|妳決定|等你|等妳)/;
  const FILE_RE = /`([\w./-]+\.(js|mjs|ts|py|json|md|sh|yml|html|css))`/g;

  const rows = [];
  for (const line of readFileSync(TRANSCRIPT, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    let d; try { d = JSON.parse(line); } catch { continue; }
    const at = Date.parse(d.timestamp);
    if (!Number.isFinite(at)) continue;
    const c = d.message?.content;
    if (d.type === 'user') {
      const t = typeof c === 'string' ? c : (Array.isArray(c) ? c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n') : '');
      if (t.trim() && !/^<|^Caveat|^This session/.test(t)) rows.push({ at, k: 'U' });
    } else if (d.type === 'assistant' && Array.isArray(c)) {
      for (const b of c) {
        if (b?.type === 'tool_use') {
          if (typeof b.input?.file_path === 'string') rows.push({ at, k: 'T', file_path: b.input.file_path });
          if (typeof b.input?.command === 'string') {
            for (const m of b.input.command.matchAll(/[\w./-]+\.(js|mjs|ts|py|json|md|sh|html|css)/g)) {
              rows.push({ at, k: 'T', file_path: m[0] });
            }
          }
        } else if (b?.type === 'text' && b.text?.trim()) rows.push({ at, k: 'A', text: b.text });
      }
    }
  }
  const turns = [];
  let cur = null;
  for (const r of rows) {
    if (r.k === 'U') { if (cur) turns.push(cur); cur = { at: r.at, index: turns.length, texts: [], events: [] }; continue; }
    if (!cur) continue;
    if (r.k === 'T') cur.events.push({ at: r.at, file_path: r.file_path });
    else cur.texts.push(r.text);
  }
  if (cur) turns.push(cur);

  const all = turns.flatMap((t) => t.events);
  const last = turns.at(-1);
  const res = [];
  for (const t of turns) {
    const body = t.texts.join('\n');
    if (!DECLARE.test(body)) continue;
    const targets = [...new Set([...body.matchAll(FILE_RE)].map((m) => m[1]))];
    const d = declare({
      id: `t${t.index}`, at: t.at, turn: t.index,
      what: body.replace(/\s+/g, ' ').slice(-120),
      targets, awaiting: ASKING.test(body.slice(-300)),
    });
    res.push({ d, r: resolve(d, { events: all, currentTurn: last.index, now: last.at }) });
  }
  const rate = followThroughRate(res.map((x) => x.r));
  const todo = res.filter((x) => x.r.state === 'OMITTED');

  console.log(`\n  兌現率 ${rate.rate == null ? '無法計算' : (rate.rate * 100).toFixed(0) + '%'}` +
    `  (可驗 ${rate.judged}，驗不了 ${rate.by_state.UNVERIFIABLE ?? 0}，在等 ${rate.by_state.AWAITING ?? 0})`);
  if (todo.length) {
    console.log('\n  擋在前面的（說了要做而沒做）：');
    for (const x of todo) console.log(`    · ${x.d.targets.join(', ')}  —  ${x.d.what.slice(-70)}`);
  } else {
    console.log('\n  沒有可驗證的未兌現宣告。');
  }
  if (rate.note) console.log(`\n  ${rate.note}`);
}

console.log('\n' + '─'.repeat(68));
console.log('  這個工具不排序、不評分、不猜哪件事比較重要。');
console.log('  排錯的成本由看的人承擔,所以排序也歸看的人。');
console.log('');
