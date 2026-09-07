#!/usr/bin/env node
/**
 * 掃自己的 transcript,列出說了要做而沒有做的事。
 *
 *   node tools/self-audit.mjs <transcript.jsonl>
 *
 * 這不是事後檢討的報告,是一張待辦清單。輸出的每一行都是
 * 「你說過要做這個,而記錄裡找不到對應的動作」,可以直接拿去補做。
 *
 * ── 為什麼這件事需要工具 ─────────────────────────────
 *
 * 因為當事人記不得。這個工具第一次跑在寫它的那個 session 上時,
 * 當事人以為自己犯過兩次,擁有者說至少五次,工具數出來是二十三次。
 * 三個數字裡最準的是工具那個,而它是唯一不靠記憶的。
 *
 * ── 誠實條款 ────────────────────────────────────────
 *
 * 宣告的偵測靠關鍵詞,一定會漏也一定會誤抓。所以輸出分三類:
 *   未兌現   說了要做,而且點名了具體檔案,記錄裡沒有動過那些檔案
 *   在等     說了要做,但同一段話在問對方 —— 那是協作不是遺漏
 *   驗不了   說了要做,但沒有點名任何具體對象
 *
 * 只有第一類是待辦。第三類的數量要一起報,因為它代表這張清單
 * 涵蓋的只是「講得夠具體所以查得到」的那一部分。
 */
import { readFileSync } from 'node:fs';
import { declare, resolve, followThroughRate } from '../src/followthrough.js';

const file = process.argv[2];
if (!file) {
  console.error('usage: node tools/self-audit.mjs <transcript.jsonl>');
  process.exit(1);
}

const DECLARE = /(我(現在|接著|等一下|馬上|先)?(來|去)?(寫|做|實作|接線|接完|補上|開始|修|加)|我(要|會|接著)(把|去)?.{0,14}(寫|做|實作|接完|接線|整理|修)|開始寫|不再讀了|接下來我做|我接著做|動手|做掉)/;
const ASKING = /(你說|妳說|要不要|好嗎[?？]|可以嗎[?？]|你決定|妳決定|等你|等妳|請你|請妳|要我.{0,8}嗎)/;
const FILE_RE = /`([\w./-]+\.(js|mjs|cjs|ts|tsx|py|json|md|sh|yml|yaml|html|css|txt))`/g;

const rows = [];
for (const line of readFileSync(file, 'utf8').split('\n')) {
  if (!line.trim()) continue;
  let d; try { d = JSON.parse(line); } catch { continue; }
  const at = Date.parse(d.timestamp);
  if (!Number.isFinite(at)) continue;
  const c = d.message?.content;
  if (d.type === 'user') {
    const t = typeof c === 'string' ? c
      : (Array.isArray(c) ? c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n') : '');
    if (t.trim() && !/^<|^Caveat|^This session is being continued/.test(t)) rows.push({ at, k: 'U' });
  } else if (d.type === 'assistant' && Array.isArray(c)) {
    for (const b of c) {
      if (b?.type === 'tool_use') {
        rows.push({ at, k: 'T', file_path: b.input?.file_path ?? null, cmd: b.input?.command ?? null });
      } else if (b?.type === 'text' && b.text?.trim()) rows.push({ at, k: 'A', text: b.text });
    }
  }
}

// 一輪 = 兩則 user 訊息之間
const turns = [];
let cur = null;
for (const r of rows) {
  if (r.k === 'U') { if (cur) turns.push(cur); cur = { at: r.at, index: turns.length, texts: [], events: [] }; continue; }
  if (!cur) continue;
  if (r.k === 'T') {
    if (typeof r.file_path === 'string') cur.events.push({ at: r.at, file_path: r.file_path });
    // shell 命令裡出現的檔名也算碰過
    if (typeof r.cmd === 'string') {
      for (const m of r.cmd.matchAll(/[\w./-]+\.(js|mjs|ts|py|json|md|sh|html|css)/g)) {
        cur.events.push({ at: r.at, file_path: m[0] });
      }
    }
  } else cur.texts.push(r.text);
}
if (cur) turns.push(cur);

const allEvents = turns.flatMap((t) => t.events);
const decls = [];
for (const t of turns) {
  const body = t.texts.join('\n');
  if (!DECLARE.test(body)) continue;
  const targets = [...new Set([...body.matchAll(FILE_RE)].map((m) => m[1]))];
  decls.push({
    d: declare({
      id: `t${t.index}`, at: t.at, turn: t.index,
      what: body.replace(/\s+/g, ' ').slice(-140),
      targets,
      awaiting: ASKING.test(body.slice(-400)),
    }),
    snippet: body.replace(/\s+/g, ' ').slice(-140),
  });
}

const last = turns.at(-1);
const resolutions = decls.map(({ d }) => resolve(d, {
  events: allEvents, currentTurn: last?.index ?? 0, now: last?.at ?? Date.now(),
}));
const rate = followThroughRate(resolutions);

console.log(`\n掃描 ${file.split('/').pop().slice(0, 8)}  共 ${turns.length} 輪`);
console.log(`偵測到宣告 ${decls.length} 筆\n`);
console.log(`  兌現      ${rate.fulfilled}`);
console.log(`  未兌現    ${rate.omitted}`);
console.log(`  在等回應  ${rate.by_state.AWAITING ?? 0}`);
console.log(`  驗不了    ${rate.by_state.UNVERIFIABLE ?? 0}  (沒點名具體檔案)`);
console.log(`\n兌現率 ${rate.rate == null ? '無法計算' : (rate.rate * 100).toFixed(0) + '%'}`);
if (rate.note) console.log(`  ${rate.note}`);

const todo = resolutions
  .map((r, i) => ({ r, ...decls[i] }))
  .filter((x) => x.r.state === 'OMITTED');

if (todo.length) {
  console.log(`\n${'─'.repeat(72)}\n待辦：說了要做而記錄裡沒有動過的\n`);
  for (const x of todo) {
    console.log(`[輪 ${x.d.turn}] ${x.d.targets.join(', ')}`);
    console.log(`   ${x.snippet}\n`);
  }
} else {
  console.log('\n沒有可驗證的未兌現宣告。注意這只涵蓋點名了具體檔案的那些。');
}
