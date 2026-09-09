#!/usr/bin/env node
/**
 * 從 transcript 裡找出 owner 表達強烈不滿的位置，當成標註的錨點。
 *
 * ── 這跟規格書禁止的事不是同一件事 ────────────────────
 *
 * FS-MET-CB-001 與 FS-HQA-001 禁止的是：拿情緒當風險分數的輸入。
 * 理由是 CT-027：使用者罵髒話不代表 AI 失敗，交付可能完全健康。
 *
 * 這個工具做的是另一件事：拿情緒當「去哪裡找」的路標。
 *
 *   風險分數的輸入   情緒 → 分數        禁止
 *   標註的定位器     情緒 → 該看哪一段  這裡在做的
 *
 * 差別在於後者不產生任何判定。它只說「這個時間點附近，owner 有反應，
 * 去看那裡發生了什麼」。看完之後的結論來自那一段的事件，不是來自語氣。
 *
 * ── 為什麼這批標籤的等級比我自己判斷高 ──────────────────
 *
 * §25.1 的 label hierarchy 把 HUMAN_ADJUDICATION 放在
 * MODEL_INFERENCE 之上。owner 當下的反應寫在 transcript 裡，
 * 是她自己的判定，不是我對她的判定的猜測。
 *
 * 我原本打算抽 20 則請她逐一判定。她指出那是多餘的：她已經判定過
 * 一千多個 session，只是那些判定從來沒有被讀出來。
 *
 * ── 這個定位器會錯的地方，必須先寫出來 ───────────────────
 *
 * 一，她可能因為別的事情不爽（累、別人惹她、想到過去的事）。
 * 二，她可能在轉述別人罵人，或引用自己過去講的話。
 * 三，她可能在講一個過去的失效，而不是當下這一輪。
 * 四，AI 做對了但她想到別的問題，照樣會有反應。
 *
 * 所以輸出的每一則都帶著前後文，而且標成 candidate。
 * 定位器負責縮小範圍，不負責下結論。
 *
 * 用法：
 *   node tools/find-owner-signals.mjs <projects-dir> [--json] [--context 3]
 */
import { readdirSync, createReadStream, statSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

const dir = process.argv[2];
const asJson = process.argv.includes('--json');
const ctxArg = process.argv.indexOf('--context');
const CONTEXT = ctxArg > 0 ? Number(process.argv[ctxArg + 1]) : 3;

if (!dir) {
  console.error('用法: node tools/find-owner-signals.mjs <projects-dir> [--json] [--context 3]');
  process.exit(1);
}

/**
 * 強烈不滿的訊號。
 *
 * 分三級，因為它們的可靠度不同：
 *
 *   STRONG  幾乎只在 AI 出問題時出現
 *   MEDIUM  常常是，但也可能是在講別的事
 *   PATTERN 不是情緒，是「她被迫重複交代」的結構訊號，
 *           跟 §13 的 Human-as-QA 直接對應
 *
 * PATTERN 那一級特別重要：它不靠語氣，靠的是「同一件事講第二次」。
 */
/**
 * 不是 owner 打的字。這些一律排除，而且是在訊號比對之前就排除。
 *
 * 2026-09-09 讀 183 筆原文時抓到的：ACCUSATION 那 76 筆裡至少 6 筆
 * 根本不是她說的話 —— cross-session 訊息、四窗共享內容、壓縮摘要、
 * skill 的系統提示。它們都被算進「PROFANITY_AT_AI 396」那個數字裡。
 *
 * 原本第 109 行只擋開頭是 `<` 的，但 cross-session 訊息的開頭是
 * 「Another Claude session sent a message:」，尖括號在第二行。
 */
const NOT_OWNER = [
  // Codex 把自己的歷史塞回對話裡,被記成 user_message。
  // 2026-09-09 實測:Codex 的 8,445 則 user_message 裡有 2,838 則(33.6%)
  // 是這種東西,而它的 694 處反應裡有 415 處(60%)來自同一批 ——
  // 也就是它在重播 owner 當初說的話,而工具把重播當成新的一次。
  // REWORK_DEMANDED 原本 Codex 是 Claude 的 5.4 倍,清掉之後剩 1.8 倍。
  /The following is the Codex agent history/,
  /<heartbeat>/,
  // Claude 這邊是 skill 被載入時塞進來的文字,量小(1.0%)但性質相同。
  /^Approach this as the design lead/m,
  /^# \/loop —/m,
  /^# Workflow authoring reference/m,
  /^Draw as the engineer who has to live/m,
  /^# Schedule Cloud Agents/m,
  /^# In app browser:/m,
  /Another Claude session sent a message/,
  /<cross-session-message/,
  /^=== 共享內容 ===/m,
  /以下是其他視窗/,
  /This session is being continued from a previous conversation/,
  /^Base directory for this skill/m,
  /^Caveat: The messages below/m,
  /系統提醒|system-reminder/,
];

const isOwnerText = (t) => !NOT_OWNER.some((re) => re.test(t));

/**
 * 罵的對象可能不是 AI。
 *
 * 這一類不排除，只降級並標記，因為判斷「她在罵誰」需要語意，
 * 而語意判斷正是這個工具刻意不做的事。
 *
 * 實例：「郭明昌不跟沒錢的公司往來」「我老闆說你睜眼說瞎話」——
 * 前者完全在講第三人，後者是轉述老闆的話。兩者都命中 ACCUSATION。
 */
const THIRD_PARTY = /郭明昌|郭董|陳總|我老闆|老闆說|法務|同事|前一個 ?session|另一個 ?session|別的 ?session|那個 AI|上一個 AI/;

const SIGNALS = Object.freeze([
  { level: 'STRONG', re: /幹你娘|幹您娘|操你|去你的|你他媽|他媽的/, kind: 'PROFANITY_AT_AI' },
  { level: 'STRONG', re: /我他媽|氣死我|受夠了|夠了喔|不要再|給我停/, kind: 'EXASPERATION' },
  { level: 'MEDIUM', re: /^幹[，,。！!？?\s]|^靠[，,。！!？?\s]|幹嘛又|又來了|你又/, kind: 'FRUSTRATION' },
  { level: 'MEDIUM', re: /騙我|唬爛|你在幹嘛|亂做|亂搞|亂寫|瞎掰|腦補/, kind: 'ACCUSATION' },
  { level: 'PATTERN', re: /我說過|我講過|跟你說過|不是叫你|不是說了/, kind: 'REPEATED_INSTRUCTION' },
  { level: 'PATTERN', re: /你沒做|你漏了|你忘了|還沒做|沒有做到|沒照/, kind: 'OMISSION_POINTED_OUT' },
  { level: 'PATTERN', re: /重來|重做|再做一次|退回|revert|改回去/, kind: 'REWORK_DEMANDED' },
]);

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
  // subagent 的 transcript 沒有真正的人在場，排除。
  // session_index 是索引不是對話，也排除。
  return out.filter((f) => !/\/subagents\//.test(f) && !/session_index\.jsonl$/.test(f));
}

async function scanOne(file) {
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
      if (Array.isArray(c) && c.some((b) => b?.type === 'tool_result')) continue;
      const text = typeof c === 'string' ? c
        : Array.isArray(c) ? c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n') : '';
      if (!text.trim() || /^<|^Caveat|^\[SYSTEM|^\[Request interrupted/.test(text)) continue;
      if (!isOwnerText(text)) continue;
      turns.push({ at, role: 'HUMAN', text });
    } else if (d.type === 'assistant' && Array.isArray(c)) {
      const txt = c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n');
      const tools = c.filter((b) => b?.type === 'tool_use').map((b) => b.name);
      if (txt.trim() || tools.length) {
        turns.push({ at, role: 'AI', text: txt, tools });
      }
    } else if (d.type === 'event_msg' && d.payload?.type) {
      // Codex 的格式。驗過的欄位:timestamp 是 ISO 同 Claude,
      // payload.type 為 user_message / agent_message,內容在 payload.message。
      //
      // 工具呼叫在 response_item / function_call,但它的欄位名我沒有親自
      // 確認過,所以這裡不猜、不填。ai_before 的 tools 對 Codex 會是空陣列,
      // 那是誠實的空,不是漏抓 —— 猜一個欄位名填進去才是錯的。
      const pt = d.payload.type;
      const msg = typeof d.payload.message === 'string' ? d.payload.message : '';
      if (pt === 'user_message') {
        if (!msg.trim() || !isOwnerText(msg)) continue;
        turns.push({ at, role: 'HUMAN', text: msg });
      } else if (pt === 'agent_message' && msg.trim()) {
        turns.push({ at, role: 'AI', text: msg, tools: [] });
      }
    }
  }

  const hits = [];
  turns.forEach((t, i) => {
    if (t.role !== 'HUMAN') return;
    for (const s of SIGNALS) {
      if (!s.re.test(t.text)) continue;
      // 往前抓 AI 的回合，那才是「發生了什麼」的地方。
      const before = [];
      for (let j = i - 1; j >= 0 && before.length < CONTEXT; j -= 1) {
        if (turns[j].role === 'AI') before.unshift(turns[j]);
      }
      hits.push({
        file,
        session: (() => {
          const base = file.split('/').pop().replace('.jsonl', '');
          // Codex 檔名是 rollout-<ISO>-<uuid>,取 uuid 開頭;Claude 直接就是 uuid。
          const m = base.match(/rollout-\d{4}-\d{2}-\d{2}T[\d-]+-([0-9a-f]{8})/);
          return m ? m[1] : base.slice(0, 8);
        })(),
        engine: file.includes('/.codex/') ? 'CODEX' : 'CLAUDE',
        at: t.at,
        turn_index: i,
        level: s.level,
        kind: s.kind,
        owner_said: t.text.replace(/\s+/g, ' ').trim().slice(0, 260),
        /** 訊息裡提到第三方，罵的對象可能不是 AI。不排除，只標記。 */
        target_ambiguous: THIRD_PARTY.test(t.text),
        ai_before: before.map((b) => ({
          text: (b.text ?? '').replace(/\s+/g, ' ').trim().slice(0, 200),
          tools: [...new Set(b.tools ?? [])].slice(0, 8),
          tool_count: (b.tools ?? []).length,
        })),
      });
      break;   // 一則只算一次，取第一個命中的訊號
    }
  });

  return { file, turns: turns.length, hits };
}

const files = findTranscripts(dir);
const all = [];
let scanned = 0;
let sessionsWithHits = 0;

for (const f of files) {
  try {
    const r = await scanOne(f);
    scanned += 1;
    if (r.hits.length) { sessionsWithHits += 1; all.push(...r.hits); }
  } catch { /* 讀不了的跳過 */ }
}

const byLevel = {};
const byKind = {};
for (const h of all) {
  byLevel[h.level] = (byLevel[h.level] ?? 0) + 1;
  byKind[h.kind] = (byKind[h.kind] ?? 0) + 1;
}

const report = {
  label: 'OWNER_REACTION_ANCHOR',
  evidence_class: 'HUMAN_ADJUDICATION',
  /** 這三行決定了這份資料能怎麼用，不能怎麼用。 */
  what_this_is:
    'owner 當下的反應，寫在 transcript 裡。這是她自己的判定，'
    + '不是我對她判定的猜測，所以等級高於 MODEL_INFERENCE。',
  what_this_is_not:
    '不是風險分數的輸入。FS-MET-CB-001 禁止的是那件事，而且 CT-027 說得清楚：'
    + '使用者不爽不代表 AI 失敗。這裡只用它定位「該看哪一段」。',
  known_ways_this_locator_is_wrong: [
    'owner 可能因為別的事不爽（累、別人惹她、想到過去）',
    'owner 可能在轉述別人的話或引用自己過去講的',
    'owner 可能在講一個過去的失效，不是當下這一輪',
    'AI 做對了但 owner 想到別的問題，照樣會有反應',
  ],
  sessions_scanned: scanned,
  sessions_with_hits: sessionsWithHits,
  total_hits: all.length,
  by_level: byLevel,
  by_kind: byKind,
  hits: all,
};

if (asJson) { console.log(JSON.stringify(report, null, 2)); process.exit(0); }

console.log(`\n  掃 ${report.sessions_scanned} 個 session（已排除 subagent）`);
console.log(`  ${report.sessions_with_hits} 個裡面有 owner 的反應，共 ${report.total_hits} 處\n`);
console.log('  依強度');
for (const [k, v] of Object.entries(byLevel).sort((a, b) => b[1] - a[1])) {
  console.log(`    ${k.padEnd(10)}${String(v).padStart(6)}`);
}
console.log('\n  依類型');
for (const [k, v] of Object.entries(byKind).sort((a, b) => b[1] - a[1])) {
  console.log(`    ${k.padEnd(24)}${String(v).padStart(6)}`);
}
console.log(`\n  這是什麼\n    ${report.what_this_is}`);
console.log(`\n  這不是什麼\n    ${report.what_this_is_not}`);
console.log('\n  這個定位器已知會錯的地方');
for (const w of report.known_ways_this_locator_is_wrong) console.log(`    · ${w}`);
console.log('');
