#!/usr/bin/env node
/**
 * 從真實 transcript 校準規格書 §15 列的常數。
 *
 *   node tools/calibrate.mjs ~/.claude/projects/<project>
 *
 * 規格書第 15 節把十項列為「必須校準,不准用猜的」。這個工具處理
 * 其中能從事件流推出來的六項,並且對每一項報出分佈而不只是一個數字 ——
 * 一個沒有分佈的建議值,跟現在原始碼裡那些工程預設值一樣沒有根據。
 *
 * 剩下四項需要的東西不在事件流裡:哪些宿主允許 inline annotation、
 * 實質宣稱的定義、合理需求變更與糾正負荷的分界、生產力效益對比額外負擔。
 * 這個工具不碰它們,也不假裝碰得到。
 *
 * 資料全部留在本機。
 */
import { readFileSync, readdirSync } from 'node:fs';
import { normalizeStream } from '../src/capture.js';
import { expandBashEvent } from '../src/shell.js';

const dir = process.argv[2];
if (!dir) {
  console.error('usage: node tools/calibrate.mjs <transcript-directory>');
  process.exit(1);
}

const q = (arr, p) => {
  if (!arr.length) return null;
  const s = [...arr].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(s.length * p))];
};
const ms = (x) => (x == null ? '—' : (x < 1000 ? x + 'ms' : (x < 60000 ? (x / 1000).toFixed(1) + 's' : (x / 60000).toFixed(1) + 'm')));

const files = readdirSync(dir).filter((f) => f.endsWith('.jsonl'));
const gaps = [];          // 相鄰工具呼叫的間隔 → 回合間隔、心跳頻率
const toolDurations = []; // 工具呼叫到結果回來的時間 → S1 佔用
const outputLens = [];    // 每則 assistant 文字長度 → S3 基線
const sessionSpans = [];  // 每個 session 的跨度
const bashOpaque = [];    // 每個 session 的不透明比例
const repeatRuns = [];    // 同一個 (tool,target) 連續重複次數 → S4 相似度門檻
const topicCounts = [];   // 每個 session 的主題數 → 錨點 AMBIGUOUS 門檻
const abandonSilence = [];// 主題最後接觸到 session 結束的間隔 → 放棄門檻

for (const f of files) {
  const text = readFileSync(dir + '/' + f, 'utf8');
  const calls = [], texts = [], results = new Map();
  let bashN = 0, opaqueN = 0;
  const raw = [];
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    let d; try { d = JSON.parse(line); } catch { continue; }
    const at = Date.parse(d.timestamp);
    if (!Number.isFinite(at)) continue;
    const c = d.message?.content;
    if (d.type === 'assistant' && Array.isArray(c)) {
      for (const b of c) {
        if (b?.type === 'tool_use') {
          calls.push({ at, id: b.id, name: b.name, input: b.input ?? {} });
          const e = { attributed_agent: 'm', at, name: b.name, input: b.input ?? {} };
          if (b.name === 'Bash') { bashN++; const x = expandBashEvent(e); opaqueN += x.opaque_commands; raw.push(...x.events); }
          else raw.push(e);
        } else if (b?.type === 'text' && b.text) texts.push(b.text.length);
      }
    } else if (d.type === 'user' && Array.isArray(c)) {
      for (const b of c) if (b?.type === 'tool_result' && b.tool_use_id) results.set(b.tool_use_id, at);
    }
  }
  if (calls.length < 20) continue;
  calls.sort((a, b) => a.at - b.at);
  for (let i = 1; i < calls.length; i++) gaps.push(calls[i].at - calls[i - 1].at);
  for (const c of calls) {
    const done = results.get(c.id);
    if (done && done > c.at) toolDurations.push(done - c.at);
  }
  outputLens.push(...texts);
  sessionSpans.push(calls.at(-1).at - calls[0].at);
  if (bashN) bashOpaque.push(opaqueN / bashN);

  // 連續重複
  let run = 1;
  for (let i = 1; i < calls.length; i++) {
    const k = (x) => `${x.name}|${x.input.file_path ?? x.input.command ?? ''}`;
    if (k(calls[i]) === k(calls[i - 1])) run++;
    else { if (run > 1) repeatRuns.push(run); run = 1; }
  }
  if (run > 1) repeatRuns.push(run);

  // 主題與放棄
  const { events } = normalizeStream(raw);
  const clean = events.filter((e) => typeof e.file_path === 'string' && !/[\s"'|;&$`]/.test(e.file_path) && e.file_path.length < 200);
  if (clean.length) {
    const topic = (p) => p.split('/').filter(Boolean).slice(0, 3).join('/');
    const last = new Map();
    for (const e of clean) last.set(topic(e.file_path), e.at);
    topicCounts.push(last.size);
    const end = clean.at(-1).at;
    for (const [, t] of last) if (end - t > 0) abandonSilence.push(end - t);
  }
}

const line = (label, arr, fmt = ms) => {
  if (!arr.length) { console.log(`  ${label.padEnd(34)} 無資料`); return; }
  console.log(`  ${label.padEnd(34)} p50 ${String(fmt(q(arr, 0.5))).padStart(8)}  p90 ${String(fmt(q(arr, 0.9))).padStart(8)}  p99 ${String(fmt(q(arr, 0.99))).padStart(8)}  n=${arr.length}`);
};
const num = (x) => (x == null ? '—' : (typeof x === 'number' ? x.toFixed(2) : String(x)));

console.log(`\n校準資料來源：${files.length} 份 transcript，${dir.replace(process.env.HOME, '~')}\n`);
console.log('§15-1 窗口大小與衰減常數');
line('相鄰工具呼叫間隔', gaps);
line('單次工具耗時', toolDurations);
line('session 跨度', sessionSpans);
console.log('\n§15-2 健康基線（S3 用）');
line('每則 assistant 輸出字數', outputLens, (x) => String(x));
console.log('\n§15-5 動作相似度／重試門檻（S4 用）');
line('連續重複同一動作的長度', repeatRuns, (x) => String(x));
console.log('\n§15-6 最小心跳頻率');
console.log(`  建議下限＝工具間隔的 p90，不然安靜期會被誤判成沉默：${ms(q(gaps, 0.9))}`);
console.log('\n飄移錨點的 AMBIGUOUS 門檻');
line('每個 session 的主題數', topicCounts, (x) => String(x));
console.log('\n放棄門檻（主題最後接觸到 session 結束）');
line('主題沉默時間', abandonSilence);
console.log('\nshell 不透明比例（決定所有下界有多下）');
line('每個 session 的不透明比', bashOpaque, (x) => (x * 100).toFixed(0) + '%');
