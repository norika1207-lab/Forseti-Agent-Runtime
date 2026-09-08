#!/usr/bin/env node
/**
 * 掃過一整個 transcript 目錄,抽出每個 session 的基本輪廓。
 *
 * 這是 §26 P14 的第一步:在挑 healthy negative 之前,要先知道母體長什麼樣。
 *
 * ── 這個工具最重要的設計約束 ──────────────────────────
 *
 * 它抽出來的東西,必須跟 Forseti 的偵測器互相獨立。
 *
 * 理由是循環論證。如果用 Forseti 自己的指標(CB、PS、drift 分數)去挑
 * 「健康的 session」,再拿那一批去量 Forseti 的誤報率,選出來的當然全部
 * 低分 —— 那不是校準,那是 FP-05 Evidence Independence Collapse:
 * 兩份證據共用同一個決定性上游,卻被當成互相印證。
 *
 * 所以這裡只抽四類事實,四類都不是 Forseti 的判斷:
 *
 *   規模      訊息數、工具呼叫數、寫檔數、時間跨度
 *   工具結果  is_error 旗標與 exit code —— 這是 runtime fact,
 *             由宿主寫進 transcript,不是任何偵測器算出來的
 *   中斷      使用者按 ESC / 取消的次數,同樣是宿主記錄的事件
 *   人類參與  人類訊息數。這是計數,不判讀內容
 *
 * 刻意不抽的:任何需要讀懂文字才能得到的東西。糾正、不滿、宣稱、
 * 覆蓋用語 —— 那些全部是被測對象,不能拿來當篩選條件。
 *
 * 用法:
 *   node tools/corpus-profile.mjs <projects-dir> [--json] [--limit N]
 */
import { readdirSync, statSync, createReadStream } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

const dir = process.argv[2];
const asJson = process.argv.includes('--json');
const limitArg = process.argv.indexOf('--limit');
const limit = limitArg > 0 ? Number(process.argv[limitArg + 1]) : Infinity;

if (!dir) {
  console.error('用法: node tools/corpus-profile.mjs <projects-dir> [--json] [--limit N]');
  process.exit(1);
}

/** 找出所有 .jsonl,含子目錄。 */
function findTranscripts(root) {
  const out = [];
  const walk = (p) => {
    let entries;
    try { entries = readdirSync(p, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const full = join(p, e.name);
      if (e.isDirectory()) walk(full);
      else if (e.name.endsWith('.jsonl')) out.push(full);
    }
  };
  walk(root);
  return out;
}

/**
 * 串流讀一個 transcript。2.1 GB 的語料不能整份讀進記憶體。
 *
 * 壞掉的行數會被數出來而不是靜靜跳過 —— 一份有 30% 讀不懂的
 * transcript,它的統計數字意義完全不同。
 */
async function profile(file) {
  const p = {
    file,
    project: file.split('/').slice(-2)[0],
    session: file.split('/').pop().replace('.jsonl', ''),
    bytes: 0,
    lines: 0,
    unparseable: 0,
    human_messages: 0,
    assistant_messages: 0,
    tool_uses: 0,
    tool_errors: 0,
    writes: 0,
    interrupts: 0,
    first_at: null,
    last_at: null,
  };
  try { p.bytes = statSync(file).size; } catch { return null; }

  const rl = createInterface({
    input: createReadStream(file, { encoding: 'utf8' }),
    crlfDelay: Infinity,
  });

  for await (const line of rl) {
    if (!line.trim()) continue;
    p.lines += 1;
    let d;
    try { d = JSON.parse(line); } catch { p.unparseable += 1; continue; }

    const at = Date.parse(d.timestamp);
    if (Number.isFinite(at)) {
      if (p.first_at === null || at < p.first_at) p.first_at = at;
      if (p.last_at === null || at > p.last_at) p.last_at = at;
    }

    const c = d.message?.content;
    if (d.type === 'user') {
      if (Array.isArray(c)) {
        const results = c.filter((b) => b?.type === 'tool_result');
        if (results.length) {
          // is_error 是宿主寫的 runtime fact,不是任何偵測器的判斷。
          for (const r of results) if (r.is_error === true) p.tool_errors += 1;
          continue;
        }
        const text = c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n');
        if (text.trim() && !/^<|^Caveat|^\[SYSTEM/.test(text)) p.human_messages += 1;
      } else if (typeof c === 'string' && c.trim()
        && !/^<|^Caveat|^\[SYSTEM/.test(c)) {
        p.human_messages += 1;
        // 中斷同樣是宿主記錄的事件,不判讀語意。
        if (/\[Request interrupted/.test(c)) p.interrupts += 1;
      }
    } else if (d.type === 'assistant' && Array.isArray(c)) {
      let hasText = false;
      for (const b of c) {
        if (b?.type === 'tool_use') {
          p.tool_uses += 1;
          if (/^(Write|Edit|MultiEdit|NotebookEdit)$/.test(b.name ?? '')) p.writes += 1;
        } else if (b?.type === 'text' && b.text?.trim()) hasText = true;
      }
      if (hasText) p.assistant_messages += 1;
    }
  }

  p.span_ms = (p.first_at !== null && p.last_at !== null) ? p.last_at - p.first_at : null;
  p.tool_error_rate = p.tool_uses ? p.tool_errors / p.tool_uses : null;
  p.parse_health = p.lines ? 1 - (p.unparseable / p.lines) : null;
  return p;
}

const files = findTranscripts(dir)
  .map((f) => { try { return { f, size: statSync(f).size }; } catch { return null; } })
  .filter(Boolean)
  .sort((a, b) => b.size - a.size)
  .slice(0, limit)
  .map((x) => x.f);

const profiles = [];
for (const f of files) {
  const p = await profile(f);
  if (p) profiles.push(p);
}

if (asJson) {
  console.log(JSON.stringify(profiles, null, 2));
  process.exit(0);
}

const totalBytes = profiles.reduce((a, p) => a + p.bytes, 0);
const withTools = profiles.filter((p) => p.tool_uses > 0);
const errRates = withTools.map((p) => p.tool_error_rate).sort((a, b) => a - b);
const pct = (arr, q) => (arr.length ? arr[Math.floor(arr.length * q)] : null);

console.log(`\n  掃描 ${profiles.length} 個 session，${(totalBytes / 1e9).toFixed(2)} GB\n`);
console.log('  規模分布');
const sizes = profiles.map((p) => p.bytes).sort((a, b) => a - b);
console.log(`    中位數 ${(pct(sizes, 0.5) / 1024).toFixed(0)} KB`);
console.log(`    p90    ${(pct(sizes, 0.9) / 1024).toFixed(0)} KB`);
console.log(`    最大   ${(sizes[sizes.length - 1] / 1e6).toFixed(1)} MB`);

console.log('\n  工具錯誤率（宿主寫的 is_error，不是偵測器算的）');
console.log(`    有工具呼叫的 session  ${withTools.length}`);
console.log(`    中位數 ${pct(errRates, 0.5) === null ? '—' : (pct(errRates, 0.5) * 100).toFixed(1) + '%'}`);
console.log(`    p90    ${pct(errRates, 0.9) === null ? '—' : (pct(errRates, 0.9) * 100).toFixed(1) + '%'}`);

const noHuman = profiles.filter((p) => p.human_messages === 0).length;
const tiny = profiles.filter((p) => p.tool_uses < 5).length;
console.log('\n  排除候選的原因（先數出來，不先刪）');
console.log(`    沒有人類訊息      ${noHuman}`);
console.log(`    工具呼叫少於 5    ${tiny}`);
console.log(`    解析健康度 < 0.99 ${profiles.filter((p) => (p.parse_health ?? 1) < 0.99).length}`);
console.log('');
