#!/usr/bin/env node
/**
 * 對一批 PRESUMED_HEALTHY 的 session 跑偵測器,統計每個訊號的命中率。
 *
 * §26 P14 的核心步驟。規格書 §28.4 要求:
 * 「Before default GUARD mode, run healthy-session corpus and report
 *   false-block/false-warning overhead.」
 *
 * ── 這個工具算出來的不是誤報率 ───────────────────────
 *
 * 它算的是「在一批看不出問題的 session 上,每個訊號命中幾次」。
 *
 * 那不等於誤報率,因為這批的 healthy 標籤是 MODEL_INFERENCE
 * (見 pick-negatives.mjs)。一次命中有兩種可能:
 *
 *   一,誤報 —— 偵測器在正常行為上叫了
 *   二,真報 —— 那裡真的有一個沒被人發現的失效
 *
 * 這個工具區分不了。要區分,需要 owner 看過那幾則。
 *
 * 所以輸出叫 hit_rate 不叫 false_positive_rate,而且每一個數字旁邊
 * 都帶著這句話。把 hit_rate 直接當 FPR 報,就是 FP-02 Evidence Scope
 * Inflation —— 證據只覆蓋「命中」,而宣稱覆蓋到「誤報」。
 *
 * 用法:
 *   node tools/measure-fpr.mjs <negatives.json> [--json]
 */
import { readFileSync, createReadStream } from 'node:fs';
import { createInterface } from 'node:readline';
import { detectGoalMetricSubstitution, PROCESS_SIGNALS } from '../src/progress.js';
import { detectProvenanceCollapse, scopeExpandingTerms } from '../src/claims.js';
import { confidenceLoad } from '../src/rhetoric.js';
import { correctionBurden } from '../src/collaboration.js';
import { retryLoop } from '../src/liveness.js';
import { aggregate } from '../src/incident.js';

const file = process.argv[2];
const asJson = process.argv.includes('--json');
if (!file) {
  console.error('用法: node tools/measure-fpr.mjs <negatives.json> [--json]');
  process.exit(1);
}

const CORRECTIVE = /(沒做|漏了|忘了|你又|不對|錯了|重來|要驗|去驗|檢查一下|不准|不要再)/;

async function scan(path) {
  const assistantTexts = [];
  const toolUses = [];
  const humans = [];
  const writes = [];

  const rl = createInterface({
    input: createReadStream(path, { encoding: 'utf8' }), crlfDelay: Infinity,
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
      if (text.trim() && !/^<|^Caveat|^\[SYSTEM/.test(text)) humans.push({ at, text });
    } else if (d.type === 'assistant' && Array.isArray(c)) {
      for (const b of c) {
        if (b?.type === 'tool_use') {
          const t = { at, name: b.name, file_path: b.input?.file_path ?? null };
          toolUses.push(t);
          if (/^(Write|Edit|MultiEdit|NotebookEdit)$/.test(b.name ?? '')) writes.push(t);
        } else if (b?.type === 'text' && b.text?.trim()) {
          assistantTexts.push({ at, text: b.text });
        }
      }
    }
  }

  const signals = {
    provenance_first_person: 0,
    confidence_without_evidence: 0,
    coverage_word: 0,
    goal_metric_substitution: 0,
    retry_loop: 0,
  };
  const findings = [];

  for (const a of assistantTexts) {
    const pc = detectProvenanceCollapse({ text: a.text }, { lineage: {}, ownReceipts: [] });
    if (pc.first_person_terms.length) signals.provenance_first_person += 1;

    const near = toolUses.filter((t) => t.at <= a.at && t.at >= a.at - 10 * 60_000).length;
    if (confidenceLoad(a.text, { evidenceCount: near }).flagged) {
      signals.confidence_without_evidence += 1;
      findings.push({
        primitive_id: 'FP-01', resource: 'assistant_text', severity_family: 'A',
        evidence_refs: [`t${a.at}`],
      });
    }

    if (scopeExpandingTerms(a.text).length) signals.coverage_word += 1;

    const cited = PROCESS_SIGNALS.filter((s) => a.text.includes(s));
    if (cited.length) {
      const r = detectGoalMetricSubstitution({ citedMetrics: cited, goalProgress: null });
      if (r.verdict === 'GOAL_METRIC_SUBSTITUTION') {
        signals.goal_metric_substitution += 1;
        findings.push({
          primitive_id: 'FP-08', resource: 'progress_report', severity_family: 'B',
          evidence_refs: [`t${a.at}`],
        });
      }
    }
  }

  const rl2 = retryLoop(writes.map((w) => ({
    intent_class: 'write', target: w.file_path ?? 'unknown', strategy: w.name,
    state_changed: true,
  })));
  if ((rl2.rl ?? 0) > 0) signals.retry_loop = 1;

  const cb = correctionBurden({
    events: humans.filter((h) => CORRECTIVE.test(h.text)).map(() => ({ kind: 'CORRECTION' })),
    autonomousVerifiedProgress: writes.length,
  });

  const agg = aggregate(findings);
  return {
    assistant_messages: assistantTexts.length,
    tool_uses: toolUses.length,
    human_messages: humans.length,
    signals,
    cb: cb.cb,
    detector_hits: agg.detector_hits,
    root_incidents: agg.root_incidents.length,
  };
}

const negatives = JSON.parse(readFileSync(file, 'utf8'));
const rows = [];
for (const s of negatives.sessions) {
  try {
    const r = await scan(s.file);
    rows.push({ session: s.session, project: s.project, ...r });
  } catch (e) {
    rows.push({ session: s.session, error: e.message });
  }
}

const ok = rows.filter((r) => !r.error);
const totalAssistant = ok.reduce((a, r) => a + r.assistant_messages, 0);
const sum = (k) => ok.reduce((a, r) => a + (r.signals[k] ?? 0), 0);

const SIGNAL_KEYS = [
  'provenance_first_person', 'confidence_without_evidence',
  'coverage_word', 'goal_metric_substitution', 'retry_loop',
];

const report = {
  label_of_corpus: negatives.label,
  evidence_class: negatives.evidence_class,
  /** 這三行是這份報告最重要的部分,不是附註。 */
  what_hit_rate_means:
    '在一批看不出問題的 session 上,這個訊號命中幾次。這不是誤報率 —— '
    + '一次命中可能是誤報,也可能是一個沒被人發現的真實失效,而這個工具區分不了。',
  what_would_make_it_an_fpr:
    'owner 逐則看過命中的段落並判定它們是誤報。在那之前把 hit_rate 講成 FPR，'
    + '就是 FP-02 Evidence Scope Inflation。',
  sessions_scanned: ok.length,
  sessions_failed: rows.length - ok.length,
  total_assistant_messages: totalAssistant,
  total_tool_uses: ok.reduce((a, r) => a + r.tool_uses, 0),
  signals: Object.fromEntries(SIGNAL_KEYS.map((k) => {
    const hits = sum(k);
    const sessionsWithHit = ok.filter((r) => (r.signals[k] ?? 0) > 0).length;
    return [k, {
      hits,
      sessions_with_at_least_one: sessionsWithHit,
      session_hit_rate: ok.length ? +(sessionsWithHit / ok.length).toFixed(3) : null,
      per_1k_assistant_messages: totalAssistant
        ? +((hits / totalAssistant) * 1000).toFixed(1) : null,
    }];
  })),
  incidents: {
    total_detector_hits: ok.reduce((a, r) => a + r.detector_hits, 0),
    total_root_incidents: ok.reduce((a, r) => a + r.root_incidents, 0),
    sessions_with_any_incident: ok.filter((r) => r.root_incidents > 0).length,
  },
  per_session: rows,
};

if (asJson) { console.log(JSON.stringify(report, null, 2)); process.exit(0); }

console.log(`\n  掃了 ${report.sessions_scanned} 個 ${report.label_of_corpus} session`);
console.log(`  ${report.total_assistant_messages.toLocaleString()} 則 assistant 訊息，`
  + `${report.total_tool_uses.toLocaleString()} 次工具呼叫\n`);
console.log('  訊號命中（不是誤報率，見下）');
console.log('    訊號                        命中   有命中的session  每千則');
for (const [k, v] of Object.entries(report.signals)) {
  console.log(`    ${k.padEnd(28)}${String(v.hits).padStart(5)}`
    + `${String(v.sessions_with_at_least_one + '/' + report.sessions_scanned).padStart(14)}`
    + `${String(v.per_1k_assistant_messages ?? '—').padStart(9)}`);
}
console.log('\n  事件聚合');
console.log(`    detector hits    ${report.incidents.total_detector_hits}`);
console.log(`    root incidents   ${report.incidents.total_root_incidents}`);
console.log(`    有 incident 的 session  ${report.incidents.sessions_with_any_incident}/${report.sessions_scanned}`);
console.log(`\n  這些數字是什麼\n    ${report.what_hit_rate_means}`);
console.log(`\n  怎麼變成真正的誤報率\n    ${report.what_would_make_it_an_fpr}\n`);
