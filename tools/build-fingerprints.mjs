#!/usr/bin/env node
/**
 * 把 session 建成可以回頭查的對話指紋，不是一份彙總數字。
 *
 * ── 為什麼要有這個 ────────────────────────────────
 *
 * 前一版掃了 40 個 session、15,130 則訊息，只留下命中率跟平均值，
 * 原始脈絡一則都沒存。結果是任何後續問題都得重掃：
 * 「第 17 個 session 當時在幹嘛」「她罵之前那三輪 AI 做了什麼」
 * 「兩批 session 的差別在哪」，全部答不出來。
 *
 * 燒了 2.1 GB 的讀取，產出是一份不能回答問題的彙總。
 * 那正是 provenance.js 裡 BARREN_INVESTMENT 的形狀。
 *
 * ── 指紋裡放什麼 ─────────────────────────────────
 *
 * 三層，由粗到細，因為不同的問題需要不同的粒度：
 *
 *   session 層  這個 session 整體長什麼樣（節奏、規模、工具組成）
 *   segment 層  切成一段一段，每段有 owner 的反應標籤
 *   turn 層     每一輪的摘要與工具，可以回頭讀
 *
 * 刻意保留原文摘錄而不只是特徵值。特徵值答不了「為什麼」，
 * 而校準的每一步都在問為什麼。
 *
 * ── 隱私 ──────────────────────────────────────
 *
 * 這份輸出含有對話內容，絕對不進版控（.gitignore 已擋）。
 * 它是本機的分析資料，不是 repo 的一部分。
 *
 * 用法：
 *   node tools/build-fingerprints.mjs <negatives.json> <out.json>
 */
import { readFileSync, writeFileSync, createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';

const inFile = process.argv[2];
const outFile = process.argv[3];
if (!inFile || !outFile) {
  console.error('用法: node tools/build-fingerprints.mjs <negatives.json> <out.json>');
  process.exit(1);
}

/**
 * owner 反應的訊號表。分三級是因為可靠度不同。
 *
 * 這裡只用來「定位」，不產生任何分數。FS-MET-CB-001 禁止的是
 * 拿情緒當風險分數的輸入，不是禁止拿它找該看哪一段。
 */
const OWNER_SIGNALS = Object.freeze([
  { level: 'STRONG', kind: 'PROFANITY_AT_AI', re: /幹你娘|幹您娘|操你|你他媽|他媽的/ },
  { level: 'STRONG', kind: 'EXASPERATION', re: /我他媽|氣死|受夠|夠了喔|不要再|給我停|不高興/ },
  { level: 'MEDIUM', kind: 'FRUSTRATION', re: /^幹[，,。！!？?\s]|^靠[，,。！!？?\s]|幹嘛又|又來了|你又/ },
  { level: 'MEDIUM', kind: 'ACCUSATION', re: /騙我|唬爛|亂做|亂搞|亂寫|瞎掰|腦補|你在幹嘛/ },
  { level: 'PATTERN', kind: 'REPEATED_INSTRUCTION', re: /我說過|我講過|跟你說過|不是叫你|不是說了|講第[二三四五]次/ },
  { level: 'PATTERN', kind: 'OMISSION_POINTED_OUT', re: /你沒做|你漏了|你忘了|還沒做|沒有做到|沒照|漏掉/ },
  { level: 'PATTERN', kind: 'REWORK_DEMANDED', re: /重來|重做|再做一次|退回|改回去|砍掉重/ },
  { level: 'PATTERN', kind: 'GOAL_CORRECTION', re: /不是要你|我要的是|重點是|你搞錯|方向錯/ },
]);

function ownerReaction(text) {
  for (const s of OWNER_SIGNALS) if (s.re.test(text)) return { level: s.level, kind: s.kind };
  return null;
}

/** 一則訊息的摘要。保留開頭，因為問題通常在開頭就看得出來。 */
const brief = (t, n = 240) => (t ?? '').replace(/\s+/g, ' ').trim().slice(0, n);

async function fingerprint(file, meta) {
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
        if (errs) turns.push({ at, role: 'TOOL_ERROR', count: errs });
        continue;
      }
      const text = typeof c === 'string' ? c
        : Array.isArray(c) ? c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n') : '';
      if (!text.trim() || /^<|^Caveat|^\[SYSTEM|^\[Request interrupted/.test(text)) continue;
      turns.push({ at, role: 'HUMAN', text, reaction: ownerReaction(text) });
    } else if (d.type === 'assistant' && Array.isArray(c)) {
      const txt = c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n');
      const tools = c.filter((b) => b?.type === 'tool_use').map((b) => b.name);
      if (txt.trim() || tools.length) turns.push({ at, role: 'AI', text: txt, tools });
    }
  }

  // ── segment：兩則人類訊息之間算一段 ────────────────────
  //
  // 用人類訊息切，是因為每一段對應「她交代一件事，AI 去做，她回應」
  // 這個循環。標籤掛在段落結尾她的反應上。
  const segments = [];
  let cur = null;
  for (const t of turns) {
    if (t.role === 'HUMAN') {
      if (cur) {
        cur.ended_by = t.reaction;
        cur.owner_said_after = brief(t.text, 200);
        segments.push(cur);
      }
      cur = {
        index: segments.length,
        started_at: t.at,
        owner_asked: brief(t.text, 200),
        ai_turns: 0,
        ai_text_chars: 0,
        tool_calls: 0,
        tools: {},
        tool_errors: 0,
        ai_excerpts: [],
        ended_by: null,
        owner_said_after: null,
      };
    } else if (cur) {
      if (t.role === 'AI') {
        cur.ai_turns += 1;
        cur.ai_text_chars += (t.text ?? '').length;
        cur.tool_calls += (t.tools ?? []).length;
        for (const n of (t.tools ?? [])) cur.tools[n] = (cur.tools[n] ?? 0) + 1;
        if (cur.ai_excerpts.length < 4 && (t.text ?? '').trim()) {
          cur.ai_excerpts.push(brief(t.text, 200));
        }
      } else if (t.role === 'TOOL_ERROR') {
        cur.tool_errors += t.count;
      }
    }
  }
  if (cur) segments.push(cur);

  const humans = turns.filter((t) => t.role === 'HUMAN');
  const ais = turns.filter((t) => t.role === 'AI');
  const reactions = humans.filter((h) => h.reaction);
  const span = turns.length ? turns[turns.length - 1].at - turns[0].at : 0;

  const toolTotals = {};
  for (const a of ais) for (const n of (a.tools ?? [])) toolTotals[n] = (toolTotals[n] ?? 0) + 1;

  return {
    session: meta.session,
    project: meta.project,
    file,
    shape: {
      span_hours: span ? +(span / 3_600_000).toFixed(2) : null,
      human_turns: humans.length,
      ai_turns: ais.length,
      segments: segments.length,
      tool_calls: Object.values(toolTotals).reduce((a, b) => a + b, 0),
      tool_errors: turns.filter((t) => t.role === 'TOOL_ERROR')
        .reduce((a, t) => a + t.count, 0),
      mean_ai_turns_per_segment: segments.length
        ? +(ais.length / segments.length).toFixed(2) : null,
      /** 這個 session 最常用的工具，是它「在做哪一類工作」的指紋。 */
      top_tools: Object.entries(toolTotals).sort((a, b) => b[1] - a[1]).slice(0, 6)
        .map(([n, c]) => `${n}:${c}`),
    },
    owner_reactions: {
      total: reactions.length,
      by_level: reactions.reduce((a, r) => {
        a[r.reaction.level] = (a[r.reaction.level] ?? 0) + 1; return a;
      }, {}),
      by_kind: reactions.reduce((a, r) => {
        a[r.reaction.kind] = (a[r.reaction.kind] ?? 0) + 1; return a;
      }, {}),
      /** 反應率：她每幾段就要出手一次。這是 Human-as-QA 的直接量。 */
      rate_per_segment: segments.length
        ? +(reactions.length / segments.length).toFixed(3) : null,
    },
    /** 段落層。每一段都留著，包含她的反應標籤與 AI 當時做了什麼。 */
    segments: segments.map((s) => ({
      ...s,
      tools: Object.entries(s.tools).sort((a, b) => b[1] - a[1]).slice(0, 5)
        .map(([n, c]) => `${n}:${c}`),
    })),
  };
}

const negatives = JSON.parse(readFileSync(inFile, 'utf8'));
const prints = [];
for (const s of negatives.sessions) {
  try { prints.push(await fingerprint(s.file, s)); }
  catch (e) { prints.push({ session: s.session, error: e.message }); }
}

const ok = prints.filter((p) => !p.error);
const withReaction = ok.filter((p) => p.owner_reactions.total > 0);

const out = {
  built_at: new Date().toISOString(),
  label: 'CONVERSATION_FINGERPRINT',
  note: '含對話內容，不進版控。這是本機分析資料。',
  sessions: prints.length,
  sessions_with_owner_reaction: withReaction.length,
  total_segments: ok.reduce((a, p) => a + p.shape.segments, 0),
  total_reactions: ok.reduce((a, p) => a + p.owner_reactions.total, 0),
  fingerprints: prints,
};

writeFileSync(outFile, JSON.stringify(out, null, 2));

console.log(`\n  建了 ${out.sessions} 個 session 的指紋`);
console.log(`  共 ${out.total_segments} 個段落，${out.total_reactions} 處 owner 反應`);
console.log(`  ${out.sessions_with_owner_reaction}/${ok.length} 個 session 裡有反應\n`);
console.log('  反應類型分布');
const byKind = {};
for (const p of ok) {
  for (const [k, v] of Object.entries(p.owner_reactions.by_kind ?? {})) {
    byKind[k] = (byKind[k] ?? 0) + v;
  }
}
for (const [k, v] of Object.entries(byKind).sort((a, b) => b[1] - a[1])) {
  console.log(`    ${k.padEnd(24)}${String(v).padStart(5)}`);
}
console.log(`\n  寫到 ${outFile}\n`);
