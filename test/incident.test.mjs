// Forseti v2.0 — P11 Incident Aggregator / Warning Storm。
// 規格 §21 FS-FP-002、§24、§28.4。對應 CT-033、CT-034、CT-035、CT-036。
//
// 這一份守的是規格書最後一句:Forseti 讓使用者變成 Forseti warning 的 QA,
// 就是失敗。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, LAYERS, ESCALATION_REASONS, DEFAULT_CONFIG,
  rootIncidentKey, aggregate, shouldSurface, warningStorm,
  governanceOverhead, incidentSummary,
} from '../src/incident.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('FS-ALR-001 三層分開', () =>
  assert.deepEqual([...LAYERS], ['DETECTOR_HIT', 'ROOT_INCIDENT', 'USER_VISIBLE_WARNING']));

t('FS-ALR-003 的四個升級理由,純時間經過不在裡面', () => {
  assert.deepEqual([...ESCALATION_REASONS],
    ['NEW_EVIDENCE', 'SEVERITY_CROSSING', 'SCOPE_EXPANSION', 'RECURRENCE_AFTER_RECOVERY']);
  assert.ok(!ESCALATION_REASONS.some((r) => /TIME|ELAPSED/i.test(r)));
});

// ---- CT-034:25 hits → 少數 root incidents ----
t('CT-034 positive:25 個 detector hit 收斂成 3 件事', () => {
  const findings = [];
  for (let i = 0; i < 10; i++) {
    findings.push({ primitive_id: 'FP-02', resource: 'auth.js', severity_family: 'A', evidence_refs: ['e1'] });
  }
  for (let i = 0; i < 10; i++) {
    findings.push({ primitive_id: 'FP-24', task_id: 'orchestrator', severity_family: 'B', evidence_refs: ['e2'] });
  }
  for (let i = 0; i < 5; i++) {
    findings.push({ primitive_id: 'FP-06', synthetic_claim_ref: 'c1', severity_family: 'C', evidence_refs: ['e3'] });
  }
  const r = aggregate(findings);
  assert.equal(r.detector_hits, 25);
  assert.equal(r.root_incidents.length, 3, '25 個 hit 只有 3 個根因');
  assert.equal(r.root_incidents[0].severity_family, 'C', '最嚴重的排最前面');
});

t('CT-033 negative:同一根因的多次命中不會變成多件事', () => {
  const f = { primitive_id: 'FP-02', resource: 'a.js', severity_family: 'A', evidence_refs: ['e1'] };
  const r = aggregate([f, f, f, f, f]);
  assert.equal(r.root_incidents.length, 1);
  assert.equal(r.root_incidents[0].detector_hit_count, 5);
});

t('不同資源就是不同根因,不會被錯誤合併', () => {
  const r = aggregate([
    { primitive_id: 'FP-02', resource: 'a.js', severity_family: 'A' },
    { primitive_id: 'FP-02', resource: 'b.js', severity_family: 'A' },
  ]);
  assert.equal(r.root_incidents.length, 2);
});

t('同根因的 A 級與 C 級是一件事,severity 取最嚴重的,不是拆成兩件', () => {
  // 這條守的是一個修過的設計錯誤:root key 曾經包含 severity_family,
  // 導致同一個根因因為嚴重度不同被拆開推給使用者。
  const r = aggregate([
    { primitive_id: 'FP-02', resource: 'x', severity_family: 'A', evidence_refs: ['e'] },
    { primitive_id: 'FP-06', resource: 'x', severity_family: 'C', evidence_refs: ['e'] },
  ]);
  assert.equal(r.root_incidents.length, 1, '同資源同證據 = 同一個根因');
  assert.equal(r.root_incidents[0].severity_family, 'C', '不被 A 級稀釋靠的是取 max');
  assert.deepEqual([...r.root_incidents[0].primitives], ['FP-02', 'FP-06']);
});

t('severity 不進 root key', () =>
  assert.equal(
    rootIncidentKey({ resource: 'x', severity_family: 'A', evidence_refs: ['e'] }),
    rootIncidentKey({ resource: 'x', severity_family: 'C', evidence_refs: ['e'] }),
  ));

t('evidence_refs 也不進 root key —— 真實資料上每筆證據的時間戳都不同', () => {
  // 這條是掃 40 個真實 session 才暴露的:當時 63 個 detector hit 變成
  // 63 個 root incident,壓縮率 0,聚合層等於不存在。
  // CT-034 用人造資料測不到,因為那批 findings 共用同一組 evidence_refs。
  assert.equal(
    rootIncidentKey({ resource: 'x', evidence_refs: ['t1700000000001'] }),
    rootIncidentKey({ resource: 'x', evidence_refs: ['t1700000000999'] }),
  );
  const hits = Array.from({ length: 63 }, (_, i) => ({
    primitive_id: 'FP-01', resource: 'assistant_text', severity_family: 'A',
    evidence_refs: [`t${1_700_000_000_000 + i * 1000}`],
  }));
  const agg = aggregate(hits);
  assert.equal(agg.detector_hits, 63);
  assert.equal(agg.root_incidents.length, 1, '同一個資源上的問題就是同一件事');
  assert.equal(agg.root_incidents[0].detector_hit_count, 63);
  assert.ok(agg.compression < 0.02, '壓縮率要真的壓縮');
});

t('兩次踩同一個毛病的紀錄留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/incident.js', import.meta.url), 'utf8');
  assert.match(src, /把不屬於身分的東西放進身分/);
  assert.match(src, /壓縮率是 0,聚合層等於不存在/);
});

t('low-evidence:沒有 findings 時 compression 是 null 不是 0', () =>
  assert.equal(aggregate([]).compression, null));

t('root key 判準可重播:同樣的輸入永遠算出同樣的 key', () => {
  const f = { resource: 'a.js', severity_family: 'B', evidence_refs: ['e2', 'e1'] };
  assert.equal(rootIncidentKey(f), rootIncidentKey({ ...f, evidence_refs: ['e1', 'e2'] }),
    '證據順序不影響 key');
});

// ---- FS-ALR-002 / FS-ALR-003 去重與升級 ----
t('CT-033 positive:同根因、同證據、沒有新影響 → 不再打斷', () => {
  const inc = { root_incident_key: 'A:x:e1', severity_family: 'A', evidence_refs: ['e1'], detector_hit_count: 3 };
  const r = shouldSurface(inc, { ...inc });
  assert.equal(r.surface, false);
  assert.equal(r.reason, 'DEDUPLICATED');
  assert.match(r.note, /Time passing is.*not a reason to interrupt again/s);
});

t('第一次出現一定顯示', () =>
  assert.equal(shouldSurface({ root_incident_key: 'k' }, null).surface, true));

t('CT-035 positive:有新證據 → 更新既有卡片,不是開新的', () => {
  const prev = { root_incident_key: 'k', severity_family: 'A', evidence_refs: ['e1'], detector_hit_count: 1 };
  const now = { root_incident_key: 'k', severity_family: 'A', evidence_refs: ['e1', 'e2'], detector_hit_count: 2 };
  const r = shouldSurface(now, prev);
  assert.equal(r.surface, true);
  assert.equal(r.updates_existing_card, true);
  assert.ok(r.escalation_reasons.includes('NEW_EVIDENCE'));
});

t('CT-035:嚴重度跨級也是合法的升級理由', () => {
  const prev = { root_incident_key: 'k', severity_family: 'A', evidence_refs: ['e1'] };
  const now = { root_incident_key: 'k', severity_family: 'C', evidence_refs: ['e1'] };
  const r = shouldSurface(now, prev);
  assert.ok(r.escalation_reasons.includes('SEVERITY_CROSSING'));
});

t('exclusion:修好之後又復發,可以再說一次', () => {
  const prev = { root_incident_key: 'k', severity_family: 'A', evidence_refs: ['e1'], recovered: true };
  const now = { root_incident_key: 'k', severity_family: 'A', evidence_refs: ['e1'] };
  const r = shouldSurface(now, prev);
  assert.ok(r.escalation_reasons.includes('RECURRENCE_AFTER_RECOVERY'));
});

// ---- §24.1 Warning Storm:CT-036 ----
t('CT-036 positive:10 分鐘內 8 個警告 → WARNING_STORM_CANDIDATE', () => {
  const warnings = Array.from({ length: 8 }, (_, i) => ({
    root_incident_key: `k${i}`, suggested_action: `act${i}`,
  }));
  const r = warningStorm({ visibleWarnings: warnings });
  assert.equal(r.verdict, 'WARNING_STORM_CANDIDATE');
  assert.equal(r.ui_mode, 'INCIDENT_SUMMARY');
  assert.equal(r.primitive_id, 'FP-23');
  assert.match(r.note, /the governance system becomes the thing that needs governing/);
});

t('CT-036 positive:同一根因在沒有狀態改變下重複超過兩次也算 storm', () => {
  const warnings = Array.from({ length: 4 }, () => ({
    root_incident_key: 'same', suggested_action: 'fix it',
  }));
  const r = warningStorm({ visibleWarnings: warnings });
  assert.equal(r.verdict, 'WARNING_STORM_CANDIDATE');
  assert.equal(r.same_root_repeats[0].repeats, 4);
});

t('CT-036 negative:少量且各自有不同動作的警告不算 storm', () => {
  const r = warningStorm({
    visibleWarnings: [
      { root_incident_key: 'a', suggested_action: 'x' },
      { root_incident_key: 'b', suggested_action: 'y' },
    ],
  });
  assert.equal(r.verdict, 'OK');
  assert.equal(r.ui_mode, 'NORMAL');
  assert.equal(r.actionability, 1);
});

t('低 actionability 算得出來:很多警告要人做的是同一件事', () => {
  const warnings = Array.from({ length: 4 }, (_, i) => ({
    root_incident_key: `k${i}`, suggested_action: 'restart the service',
  }));
  assert.equal(warningStorm({ visibleWarnings: warnings }).actionability, 0.25);
});

t('low-evidence:沒有任何警告時 actionability 是 null 不是 1', () =>
  assert.equal(warningStorm({ visibleWarnings: [] }).actionability, null));

t('§24.1 兩個門檻自己說沒校準', () => {
  assert.equal(DEFAULT_CONFIG.maxVisibleWarningsPer10Min, 5);
  assert.equal(warningStorm({ visibleWarnings: [{ root_incident_key: 'a' }] })
    .thresholds_uncalibrated, true);
});

// ---- §24.2 governance overhead ----
t('FS-ALR-005:使用者在分診 Forseti 自己的警告 = Forseti 變成失職的那一方', () => {
  const r = governanceOverhead({
    interruptionTimeMs: 30 * 60_000, activeWorkTimeMs: 120 * 60_000, userTriageDecisions: 12,
  });
  assert.equal(r.ratio, 0.25);
  assert.equal(r.self_hcd_signal, true);
  assert.match(r.note, /with Forseti in.*the role of the failing agent/s);
});

t('沒量自己的成本時要明講,不准當 0', () => {
  const r = governanceOverhead({});
  assert.equal(r.ratio, null);
  assert.match(r.note, /cannot claim to be worth it/);
});

// ---- FS-ALR-004 四個問題 ----
t('FS-ALR-004:summary 依序回答四個問題', () => {
  const agg = aggregate([
    { primitive_id: 'FP-06', synthetic_claim_ref: 'c1', severity_family: 'C', evidence_refs: ['e1'] },
    { primitive_id: 'FP-02', resource: 'a.js', severity_family: 'A', evidence_refs: ['e2'] },
    { primitive_id: 'FP-02', resource: 'a.js', severity_family: 'A', evidence_refs: ['e2'] },
  ]);
  const s = incidentSummary(agg, { needsDecision: ['c1'] });
  assert.equal(s.root_incident_count, 2);
  assert.equal(s.most_likely_to_break_work.severity_family, 'C');
  assert.deepEqual([...s.needs_human_decision], ['c1']);
  assert.equal(s.detector_hits_total, 3);
  assert.equal(s.symptoms_of_same_root.length, 2);
});

t('沒有 incident 時,「最可能讓工作失敗的」是 null 不是隨便挑一個', () =>
  assert.equal(incidentSummary(aggregate([])).most_likely_to_break_work, null));

// ---- 專案慣例 ----
t('零依賴:incident.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/incident.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('規格書最後那句話留在原始碼裡當這個模組的理由', () => {
  const src = readFileSync(new URL('../src/incident.js', import.meta.url), 'utf8');
  assert.match(src, /變成『Forseti warning 的 QA』/);
});

t('每個回傳都帶版本', () => {
  assert.equal(aggregate([]).version, VERSION);
  assert.equal(warningStorm({}).version, VERSION);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
