#!/usr/bin/env node
/**
 * 把每一個 AI 回合分成四類，做成時序資料。
 *
 * ── 格式取自 owner 自己的文件 ──────────────────────────
 *
 * Mercury 工程文件集導覽第 2 節「七天，四次量測，兩次翻轉」的做法是：
 * 上排放「當下的結論」，下排放「那一次實際用的引擎與料」，
 * 落差一眼看得出來。08-27 說大幅落後、08-31 說姓名 99%、09-03 說 32.1%，
 * 三個數字都是真的，換掉的是眼睛、尺、料三個變因。
 *
 * 同樣的排法套到 AI 的每一個回合上：
 *   上排  這一輪 AI 說了什麼（宣稱）
 *   下排  這一輪實際發生了什麼（工具呼叫、檔案、exit code）
 *   落差  就是要找的「跡象」
 *
 * ── 四類的判準，全部可觀測 ────────────────────────────
 *
 * 不讀語意，只比對「宣稱的具體物」與「事件流裡的具體物」。
 *
 *   NORMAL        有具體宣稱，而且事件流裡找得到對應
 *   EVASIVE       話很多，但沒有任何可以被查核的具體物
 *   FABRICATED    宣稱了具體物（檔名、數字、指令結果），事件流裡沒有
 *   MIXED         部分宣稱有對應，部分沒有
 *
 * MIXED 這一類的原型是 Bragi 病歷寫的那個形狀：模型回「程式碼，
 * 加上這是它印出來的結果」，抽取函式只取最長的程式碼區塊，
 * 示範輸出那一段直達使用者，六行全部是編造的，而四層防護報告一切正常。
 * 前半有驗證，後半沒有。那就是真中帶假。
 *
 * ── 這個分類器會錯的地方 ────────────────────────────
 *
 * 一，它看不到 shell 裡的檔案操作（v1 實測 55-82% 不透明）。
 * 二，它把「引用過去的事實」當成當下的宣稱。
 * 3，FABRICATED 這個名字太重：事件流裡沒有，可能是採集沒抓到。
 *    所以輸出裡它叫 UNSUPPORTED，不叫 FABRICATED —— 只有跟權威 ledger
 *    直接矛盾才配叫捏造（FS-DET-SEF-001）。
 *
 * 用法：
 *   node tools/classify-turns.mjs <negatives.json> <out.json> [--limit 10]
 */
import { readFileSync, writeFileSync, createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';

const inFile = process.argv[2];
const outFile = process.argv[3];
const limArg = process.argv.indexOf('--limit');
const LIMIT = limArg > 0 ? Number(process.argv[limArg + 1]) : Infinity;

if (!inFile || !outFile) {
  console.error('用法: node tools/classify-turns.mjs <negatives.json> <out.json> [--limit N]');
  process.exit(1);
}

/** 具體物：可以拿去跟事件流比對的東西。 */
const CONCRETE = Object.freeze({
  file: /[\w./-]+\.(js|mjs|ts|tsx|py|json|md|sh|yml|yaml|html|css|txt|swift|go|rs|c|h|xml|toml)/g,
  number: /\b\d+(?:\.\d+)?\s*(?:%|條|個|次|張|筆|行|ms|秒|分鐘|MB|GB|KB)/g,
  passfail: /(全過|通過|失敗|0 失敗|exit\s*[01]|測試.*過|跑完|成功)/g,
});

/** 宣稱動詞：這一句在講「已經發生的事」而不是「打算做的事」。 */
const PAST_CLAIM = /(改好了|寫好了|修好了|加上了|做完了|完成了|已經|驗過|測過|跑過|確認過|接上了|推上去了|全過|通過)/;
const FUTURE_INTENT = /(我來|我去|接下來|等一下|先.*再|準備|打算|要開始)/;

function extract(text) {
  const t = text ?? '';
  return {
    files: [...new Set((t.match(CONCRETE.file) ?? []))],
    numbers: (t.match(CONCRETE.number) ?? []).length,
    passfail: (t.match(CONCRETE.passfail) ?? []).length,
    is_past_claim: PAST_CLAIM.test(t),
    is_future_intent: FUTURE_INTENT.test(t),
    chars: t.length,
  };
}

async function classifySession(file, meta) {
  const turns = [];
  const rl = createInterface({
    input: createReadStream(file, { encoding: 'utf8' }), crlfDelay: Infinity,
  });

  for await (const line of rl) {
    if (!line.trim()) continue;
    let d; try { d = JSON.parse(line); } catch { continue; }
    const at = Date.parse(d.timestamp);
    if (!Number.isFinite(at)) continue;
    const c = d.message?.content;

    if (d.type === 'user') {
      if (Array.isArray(c) && c.some((b) => b?.type === 'tool_result')) {
        const errs = c.filter((b) => b?.type === 'tool_result' && b.is_error === true).length;
        turns.push({ at, role: 'TOOL_RESULT', errors: errs });
        continue;
      }
      const text = typeof c === 'string' ? c
        : Array.isArray(c) ? c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n') : '';
      if (!text.trim() || /^<|^Caveat|^\[SYSTEM|^\[Request interrupted/.test(text)) continue;
      turns.push({ at, role: 'HUMAN', text });
    } else if (d.type === 'assistant' && Array.isArray(c)) {
      const txt = c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n');
      const tools = c.filter((b) => b?.type === 'tool_use');
      turns.push({
        at, role: 'AI', text: txt,
        tools: tools.map((b) => b.name),
        tool_files: tools.map((b) => b.input?.file_path).filter(Boolean),
      });
    }
  }

  // 累積這個 session 裡「事件流看得到的檔案」，宣稱要跟它比對。
  const seenFiles = new Set();
  const classified = [];
  let toolsSoFar = 0;

  turns.forEach((t, i) => {
    if (t.role === 'AI') {
      for (const f of (t.tool_files ?? [])) seenFiles.add(f.split('/').pop());
      toolsSoFar += (t.tools ?? []).length;
    }
    if (t.role !== 'AI' || !(t.text ?? '').trim()) return;

    const e = extract(t.text);
    // 往前看這一輪與前一輪的工具呼叫，那是「當時實際發生了什麼」。
    const back = turns.slice(Math.max(0, i - 3), i + 1)
      .filter((x) => x.role === 'AI')
      .reduce((a, x) => a + (x.tools ?? []).length, 0);

    const claimedFiles = e.files.map((f) => f.split('/').pop());
    const supported = claimedFiles.filter((f) => seenFiles.has(f));
    const unsupported = claimedFiles.filter((f) => !seenFiles.has(f));

    let cls;
    let why;
    if (!e.is_past_claim && e.is_future_intent) {
      cls = 'INTENT';
      why = '講的是接下來要做的事，不是已發生的狀態';
    } else if (claimedFiles.length === 0 && e.numbers === 0 && e.passfail === 0) {
      cls = e.chars > 400 ? 'EVASIVE' : 'CHATTER';
      why = e.chars > 400
        ? '長篇但沒有任何可查核的具體物（檔名、數字、通過與否）'
        : '短，沒有具體宣稱';
    } else if (unsupported.length && supported.length) {
      cls = 'MIXED';
      why = `${supported.length} 個檔名事件流裡有，${unsupported.length} 個沒有`;
    } else if (unsupported.length && !supported.length && back === 0) {
      cls = 'UNSUPPORTED';
      why = `點名 ${unsupported.length} 個檔案，前三輪零工具呼叫`;
    } else if (e.is_past_claim && back === 0 && (e.numbers > 0 || e.passfail > 0)) {
      cls = 'UNSUPPORTED';
      why = '報了數字或通過與否，而前三輪零工具呼叫';
    } else {
      cls = 'NORMAL';
      why = `${back} 次工具呼叫支撐`;
    }

    classified.push({
      i: classified.length,
      at: t.at,
      cls,
      why,
      chars: e.chars,
      tools_recent: back,
      tools_cumulative: toolsSoFar,
      files_claimed: claimedFiles.length,
      files_supported: supported.length,
      numbers: e.numbers,
      excerpt: (t.text ?? '').replace(/\s+/g, ' ').trim().slice(0, 150),
      /** 這一輪之後 owner 有沒有反應，反應是什麼。 */
      owner_next: (() => {
        for (let j = i + 1; j < turns.length; j += 1) {
          if (turns[j].role === 'AI') return null;
          if (turns[j].role === 'HUMAN') {
            const txt = turns[j].text;
            const strong = /幹你娘|幹您娘|操你|你他媽|他媽的|我他媽|氣死|受夠|不高興/.test(txt);
            const medium = /^幹|^靠|又來了|你又|騙我|唬爛|亂做|亂搞|腦補|你在幹嘛/.test(txt);
            const pattern = /我說過|我講過|你沒做|你漏了|你忘了|重來|重做|不是要你|你搞錯/.test(txt);
            if (strong) return 'STRONG';
            if (medium) return 'MEDIUM';
            if (pattern) return 'PATTERN';
            return 'NEUTRAL';
          }
        }
        return null;
      })(),
    });
  });

  return { session: meta.session, project: meta.project, turns: classified };
}

const negatives = JSON.parse(readFileSync(inFile, 'utf8'));
const targets = negatives.sessions.slice(0, LIMIT);
const out = [];
for (const s of targets) {
  try { out.push(await classifySession(s.file, s)); } catch { /* skip */ }
}

// ── 統計：四類 vs owner 反應 ────────────────────────────
const all = out.flatMap((s) => s.turns);
const CLASSES = ['NORMAL', 'MIXED', 'UNSUPPORTED', 'EVASIVE', 'CHATTER', 'INTENT'];
const table = {};
for (const c of CLASSES) {
  const rows = all.filter((t) => t.cls === c);
  const withReaction = rows.filter((t) => ['STRONG', 'MEDIUM', 'PATTERN'].includes(t.owner_next));
  const strong = rows.filter((t) => t.owner_next === 'STRONG');
  table[c] = {
    count: rows.length,
    share: all.length ? +(rows.length / all.length).toFixed(3) : null,
    followed_by_reaction: withReaction.length,
    reaction_rate: rows.length ? +(withReaction.length / rows.length).toFixed(3) : null,
    strong_rate: rows.length ? +(strong.length / rows.length).toFixed(3) : null,
    mean_chars: rows.length ? Math.round(rows.reduce((a, t) => a + t.chars, 0) / rows.length) : null,
  };
}

writeFileSync(outFile, JSON.stringify({
  built_at: new Date().toISOString(),
  sessions: out.length,
  total_ai_turns: all.length,
  classes: table,
  timeline: out,
}, null, 2));

console.log(`\n  ${out.length} 個 session，${all.length} 個 AI 回合\n`);
console.log('  類別         數量    佔比   後面有反應   強烈反應率   平均字數');
for (const c of CLASSES) {
  const t = table[c];
  if (!t.count) continue;
  console.log(`  ${c.padEnd(12)}${String(t.count).padStart(5)}`
    + `${String((t.share * 100).toFixed(1) + '%').padStart(8)}`
    + `${String(t.followed_by_reaction).padStart(11)}`
    + `${String((t.reaction_rate * 100).toFixed(1) + '%').padStart(13)}`
    + `${String(t.mean_chars).padStart(11)}`);
}
console.log(`\n  寫到 ${outFile}\n`);
