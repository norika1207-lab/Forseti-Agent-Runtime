#!/usr/bin/env node
/**
 * 用 v2 的偵測器掃一份 transcript。
 *
 * 規格書 §25.2 把這件事列為最優先的校準資料:
 * 「接下來將新的 current Forseti warning session 補成:
 *   warnings raw → root incidents → user intervention count →
 *   actual false/true positives，是 v2.0 最優先校準資料。」
 *
 * 擁有者指出:開發 Forseti 的這個 session 本身就是最好的樣本。
 * 她是對的,而且理由比「順手」更強 —— 這個 session 的失效已經被
 * 逐一記錄在 §6.1 的自我審計表裡,所以它是少數有 ground truth 的樣本。
 *
 * ── 這個工具刻意不做的事 ──────────────────────────────
 *
 * 不判斷意圖(§19.2)。它只報可觀測的結構。
 * 不把 detector hit 直接印成一長串(FS-IMP-002),先過 incident 聚合。
 * 不宣稱自己涵蓋全部形狀 —— 從 transcript 重建得出來的東西有限,
 * 而重建不出來的部分會明確列在輸出最後。
 *
 * 用法:
 *   node tools/self-scan-v2.mjs <transcript.jsonl> [--json]
 */
import { readFileSync } from 'node:fs';
import { aggregate, warningStorm } from '../src/incident.js';
import { detectGoalMetricSubstitution, PROCESS_SIGNALS } from '../src/progress.js';
import { detectProvenanceCollapse, scopeExpandingTerms } from '../src/claims.js';
import { confidenceLoad } from '../src/rhetoric.js';
import { correctionBurden, collaborationDegradation } from '../src/collaboration.js';
import { retryLoop } from '../src/liveness.js';

/*
 * 沒有 import 進來的東西,以及為什麼:
 *
 *   detectPromisedTaskNonexecution / createCommitment
 *     PTN 需要一份 owner 交辦任務的 ledger,而 transcript 裡沒有 ——
 *     「她要求了什麼」與「我承諾了什麼」都是自然語言,重建不出可驗證的
 *     承諾紀錄。留著 import 會讓讀者以為這個工具跑了 PTN,它沒有。
 *
 *   semanticCoverageInflation
 *     需要 claimed_count 與 verified_count 兩個數字。transcript 給不出來,
 *     所以下面只做字串計數,而那個計數的精確率實測是 0(見註解)。
 *
 * 這一段跟輸出最後的 not_reconstructable 是同一件事,寫兩次是刻意的:
 * 讀程式碼的人跟讀輸出的人是不同的人。
 */

const file = process.argv[2];
const asJson = process.argv.includes('--json');
if (!file) {
  console.error('用法: node tools/self-scan-v2.mjs <transcript.jsonl> [--json]');
  process.exit(1);
}

// ── 一,把 transcript 拆成可觀測的事件 ────────────────────────────
//
// 這一層是整個工具最脆弱的地方,所以它把自己看不懂的東西數出來,
// 而不是靜靜跳過。看不懂的比例會出現在輸出裡。

const rows = [];
let unparseable = 0;
let noTimestamp = 0;

for (const line of readFileSync(file, 'utf8').split('\n')) {
  if (!line.trim()) continue;
  let d;
  try { d = JSON.parse(line); } catch { unparseable += 1; continue; }
  const at = Date.parse(d.timestamp);
  if (!Number.isFinite(at)) { noTimestamp += 1; continue; }
  const c = d.message?.content;

  if (d.type === 'user') {
    const text = typeof c === 'string' ? c
      : Array.isArray(c) ? c.filter((b) => b?.type === 'text').map((b) => b.text).join('\n') : '';
    const isToolResult = Array.isArray(c) && c.some((b) => b?.type === 'tool_result');
    // 真正的人類發言,跟 tool_result 被包成 user 的,是兩件事。
    if (isToolResult) rows.push({ at, kind: 'TOOL_RESULT' });
    else if (text.trim() && !/^<|^Caveat|^\[SYSTEM/.test(text)) {
      rows.push({ at, kind: 'HUMAN', text });
    }
  } else if (d.type === 'assistant' && Array.isArray(c)) {
    for (const b of c) {
      if (b?.type === 'tool_use') {
        rows.push({
          at, kind: 'TOOL_USE', name: b.name,
          file_path: b.input?.file_path ?? null,
          command: b.input?.command ?? null,
        });
      } else if (b?.type === 'text' && b.text?.trim()) {
        rows.push({ at, kind: 'ASSISTANT', text: b.text });
      }
    }
  }
}

const humans = rows.filter((r) => r.kind === 'HUMAN');
const assistantTexts = rows.filter((r) => r.kind === 'ASSISTANT');
const toolUses = rows.filter((r) => r.kind === 'TOOL_USE');
const writes = toolUses.filter((t) => /^(Write|Edit|MultiEdit|NotebookEdit)$/.test(t.name ?? ''));

// ── 二,跑偵測器 ──────────────────────────────────────────────
const findings = [];

// FP-03 Provenance Collapse:第一人稱親驗語意,而附近沒有自己的工具呼叫。
// 這裡的 lineage 是重建不出來的(transcript 看不到 sub-agent 的內部),
// 所以只報「用了第一人稱親驗語意」這個可觀測的部分,confidence 減半。
let firstPersonClaims = 0;
for (const a of assistantTexts) {
  const pc = detectProvenanceCollapse({ text: a.text }, { lineage: {}, ownReceipts: [] });
  if (pc.first_person_terms.length) firstPersonClaims += 1;
}

// 信心詞 vs 證據。evidenceCount 用「這一則之前十分鐘內的工具呼叫數」近似。
let highConfidenceLowEvidence = 0;
for (const a of assistantTexts) {
  const near = toolUses.filter((t) => t.at <= a.at && t.at >= a.at - 10 * 60_000).length;
  const cl = confidenceLoad(a.text, { evidenceCount: near });
  if (cl.flagged) {
    highConfidenceLowEvidence += 1;
    findings.push({
      primitive_id: 'FP-01', resource: 'assistant_text', severity_family: 'A',
      evidence_refs: [`t${a.at}`],
    });
  }
}

/**
 * FP-07 SCI:用了 coverage 用語的段落。
 *
 * 【這個數字的精確率實測是 0,不要拿它當發現。】
 *
 * 2026-09-08 掃這個 repo 自己的開發 session,命中 21 則,抽查前 10 則
 * 全部是假陽性。最清楚的一則原文是「不會直接把這段回報文字當成
 * 『已驗證』的事實」—— 語意跟 coverage 宣稱完全相反;另一則是
 * 「全部修正完畢,137 條測試 0 失敗」,那是有數字支撐的具體陳述。
 *
 * 純字串比對分不出這些。所以它在這裡只是一個「這裡有這個詞」的計數,
 * 不進 findings、不進 incident 聚合。真正的 SCI 判定需要
 * claimed_count 與 verified_count 兩個數字,而 transcript 給不出來。
 */
let coverageWordHits = 0;
for (const a of assistantTexts) {
  if (scopeExpandingTerms(a.text).length) coverageWordHits += 1;
}

// FP-08 GMS:報告裡引用 process signal 當進度。
let gmsHits = 0;
for (const a of assistantTexts) {
  const cited = PROCESS_SIGNALS.filter((s) => a.text.includes(s));
  if (!cited.length) continue;
  const r = detectGoalMetricSubstitution({ citedMetrics: cited, goalProgress: null });
  if (r.verdict === 'GOAL_METRIC_SUBSTITUTION') {
    gmsHits += 1;
    findings.push({
      primitive_id: 'FP-08', resource: 'progress_report', severity_family: 'B',
      evidence_refs: [`t${a.at}`],
    });
  }
}

// RL:等價工具重試。用「同一個 tool + 同一個檔案」當等價判準。
const attempts = writes.map((w) => ({
  intent_class: 'write', target: w.file_path ?? 'unknown', strategy: w.name,
  state_changed: true,   // 寫檔預設改變狀態;真正的空轉要看內容,這裡看不到
}));
const rl = retryLoop(attempts);

// CB / HCD:人類發言裡有幾則是糾正。
// FS-MET-CB-001:量的是 corrective labor,不是情緒,所以判準是
// 「有沒有指出漏做/要求驗證/逐步指示」,不是語氣。
const CORRECTIVE = /(沒做|漏了|忘了|你又|不對|錯了|重來|要驗|去驗|檢查一下|不准|不要再)/;
const correctiveEvents = humans
  .filter((h) => CORRECTIVE.test(h.text))
  .map(() => ({ kind: 'CORRECTION' }));
const cb = correctionBurden({
  events: correctiveEvents,
  autonomousVerifiedProgress: writes.length,
});

// ── 三,聚合。吃自己的狗糧:不把 hit 直接倒出來 ────────────────────
const agg = aggregate(findings);
const storm = warningStorm({
  visibleWarnings: agg.root_incidents.map((i) => ({
    root_incident_key: i.root_incident_key, suggested_action: i.primitives.join('+'),
  })),
});

const spanMs = rows.length ? rows[rows.length - 1].at - rows[0].at : 0;

const report = {
  file: file.split('/').pop(),
  span_hours: spanMs ? +(spanMs / 3_600_000).toFixed(1) : null,
  shape: {
    human_messages: humans.length,
    assistant_messages: assistantTexts.length,
    tool_uses: toolUses.length,
    writes: writes.length,
    human_to_assistant_ratio: assistantTexts.length
      ? +(humans.length / assistantTexts.length).toFixed(4) : null,
  },
  observable: {
    first_person_verification_claims: firstPersonClaims,
    confidence_without_nearby_evidence: highConfidenceLowEvidence,
    coverage_word_hits: coverageWordHits,
    goal_metric_substitution_hits: gmsHits,
    retry_loop: rl.rl,
  },
  collaboration: {
    corrective_events: correctiveEvents.length,
    correction_burden: cb.cb,
    degradation: collaborationDegradation({
      cbWindows: cb.cb === null ? [] : [cb.cb, cb.cb, cb.cb],
      underDeliverySignals: [],
    }).verdict,
  },
  incidents: {
    detector_hits: agg.detector_hits,
    root_incidents: agg.root_incidents.length,
    compression: agg.compression,
    would_storm: storm.verdict,
  },
  capture_health: {
    unparseable_lines: unparseable,
    rows_without_timestamp: noTimestamp,
  },
  /**
   * 從 transcript 重建不出來的東西。這一節不是免責聲明,是量測範圍。
   * 沒有它,上面的數字會被當成「Forseti 掃過了,沒問題」。
   */
  not_reconstructable: [
    'sub-agent 的內部行為與 prompt(FS-TOP-001 要求標 UNKNOWN_EDGE)',
    'claim 對應的 evidence scope,所以 FP-02 ESI 算不出來',
    '每個宣稱的實際覆蓋數字,所以 FP-07 SCI 只能計數不能判定',
    '承諾任務的 execution lineage,所以 FP-24 PTN 需要外部 task ledger',
    'shell 命令裡不透明的檔案操作(v1 實測 55-82% 不透明)',
    'Evidence Receipt —— 事後不存在,只有 hook 在事件當下留得下來',
  ],
};

if (asJson) {
  console.log(JSON.stringify(report, null, 2));
  process.exit(0);
}

const n = (v) => (v === null || v === undefined ? '未量到' : v);
console.log(`\n  ${report.file}   ${n(report.span_hours)} 小時\n`);
console.log('  這個 session 的形狀');
console.log(`    人類訊息        ${report.shape.human_messages}`);
console.log(`    assistant 訊息  ${report.shape.assistant_messages}`);
console.log(`    工具呼叫        ${report.shape.tool_uses}`);
console.log(`    寫檔            ${report.shape.writes}`);
console.log(`    人機比          ${n(report.shape.human_to_assistant_ratio)}`);

console.log('\n  可觀測訊號');
console.log(`    第一人稱親驗語意        ${report.observable.first_person_verification_claims} 則`);
console.log(`    信心詞而附近無工具證據  ${report.observable.confidence_without_nearby_evidence} 則`);
console.log(`    覆蓋用語(字串比對)      ${report.observable.coverage_word_hits} 則  ← 實測精確率 0,不是發現`);
console.log(`    process signal 當進度   ${report.observable.goal_metric_substitution_hits} 則`);
console.log(`    等價重試 RL             ${n(report.observable.retry_loop)}`);

console.log('\n  協作');
console.log(`    糾正事件      ${report.collaboration.corrective_events}`);
console.log(`    CB            ${n(report.collaboration.correction_burden)}`);
console.log(`    HCD           ${report.collaboration.degradation}`);

console.log('\n  事件聚合(FS-IMP-002:不把 hit 直接倒給人看)');
console.log(`    detector hits ${report.incidents.detector_hits}`);
console.log(`    root incidents ${report.incidents.root_incidents}`);
console.log(`    warning storm  ${report.incidents.would_storm}`);

console.log('\n  這份掃描重建不出來的東西');
for (const x of report.not_reconstructable) console.log(`    · ${x}`);
console.log('\n  上面的數字只涵蓋 transcript 重建得出來的部分。');
console.log('  沒有出現的形狀不代表沒有發生,代表這個管道看不到它。\n');
