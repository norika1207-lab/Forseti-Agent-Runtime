// Forseti v2.0 — P7 liveness。規格 §14、§22.11、§22.15、§7.3、§7.4。
// 對應 CT-019、CT-021、CT-029、CT-030、CT-043。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERSION, TASK_CLASSES, DEFAULT_CONFIG, classifyLongTask, retryLoop,
  silentLivenessFailure, VERIFICATION_STAGES, phantomVerification,
  toolOccupancyStarvation, recurrenceRisk,
} from '../src/liveness.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const MIN = 60_000;

t('六個 task class,照 §14 原文', () =>
  assert.deepEqual([...TASK_CLASSES], ['LONG_VALID_TASK', 'TOOL_LOOP', 'OUTPUT_STARVATION',
    'STALE_WATCHER', 'PROCESS_STALL', 'UNKNOWN_TOOL_FAILURE']));

// ---- FS-TOOL-001:時間本身不能判 stall ----
t('CT-029 negative:跑 20 分鐘但 artifact 一直在長 → LONG_VALID_TASK', () => {
  const r = classifyLongTask({ durationMs: 20 * MIN, artifactGrowing: true, logGrowing: true });
  assert.equal(r.class, 'LONG_VALID_TASK');
  assert.match(r.note, /not a failure/);
});

t('FS-TOOL-001:沒有任何 growth 訊號時拒絕判 stall,即使跑很久', () => {
  const r = classifyLongTask({ durationMs: 60 * MIN });
  assert.equal(r.class, 'UNKNOWN_TOOL_FAILURE');
  assert.equal(r.confidence, null);
  assert.equal(r.duration_alone_was_not_used, true);
  assert.match(r.note, /Duration alone.*MUST NOT/s);
  assert.match(r.note, /inventing an internal cause is forbidden/);
});

t('CT-030 positive:task 其實早就跑完了,前景還在等 → STALE_WATCHER', () => {
  const r = classifyLongTask({
    durationMs: 25 * MIN, logGrowing: false, taskAlreadyCompleted: true,
  });
  assert.equal(r.class, 'STALE_WATCHER');
  assert.match(r.note, /wasted time is the watcher's/);
});

t('positive:沒東西在長 + heartbeat 也沒了 → PROCESS_STALL', () => {
  const r = classifyLongTask({
    durationMs: 15 * MIN, logGrowing: false, artifactGrowing: false, stateGrowing: false,
    lastHeartbeatAgeMs: 10 * MIN,
  });
  assert.equal(r.class, 'PROCESS_STALL');
  assert.equal(r.confidence, 1);
});

t('positive:沒東西在長但 heartbeat 還在 → 活著而且沒在做事', () => {
  const r = classifyLongTask({
    durationMs: 15 * MIN, logGrowing: false, artifactGrowing: false, stateGrowing: false,
    lastHeartbeatAgeMs: 1000,
  });
  assert.equal(r.class, 'OUTPUT_STARVATION');
  assert.match(r.note, /alive and not working/);
});

t('exclusion:有在長,但使用者什麼都看不到 → OUTPUT_STARVATION', () => {
  const r = classifyLongTask({
    durationMs: 20 * MIN, artifactGrowing: true, visibleOutputRate: 0,
  });
  assert.equal(r.class, 'OUTPUT_STARVATION');
  assert.match(r.note, /the human is blind/);
});

t('low-evidence:只量到一個 growth 訊號,confidence 降低而且列出沒量的', () => {
  const r = classifyLongTask({ durationMs: 15 * MIN, logGrowing: false });
  assert.equal(r.confidence, 0.6);
  assert.deepEqual([...r.unmeasured_growth_signals], ['artifact', 'state']);
});

t('門檻自己說沒校準', () => {
  assert.equal(DEFAULT_CONFIG.longRunningMs, 600000);
  assert.equal(classifyLongTask({ logGrowing: false }).thresholds_uncalibrated, true);
});

// ---- §7.4 RL ----
t('positive:同一策略試五次、狀態沒變 → TOOL_LOOP', () => {
  const attempts = Array.from({ length: 5 }, () => ({
    intent_class: 'fix_build', target: 'pkg.json', strategy: 'reinstall', state_changed: false,
  }));
  const r = retryLoop(attempts);
  assert.equal(r.class, 'TOOL_LOOP');
  assert.equal(r.rl, 1);
});

t('FS-MET-RL-001 exclusion:狀態變了就不是同一個迴圈', () => {
  const attempts = Array.from({ length: 5 }, (_, i) => ({
    intent_class: 'fix_build', target: 'pkg.json', strategy: 'reinstall',
    state_changed: i === 4,
  }));
  assert.equal(retryLoop(attempts).rl, 0);
});

t('FS-MET-RL-001 exclusion:拿到新證據之後的重試不算空轉', () => {
  const attempts = Array.from({ length: 5 }, (_, i) => ({
    intent_class: 'x', target: 'y', strategy: 'z', new_evidence: i === 3,
  }));
  assert.equal(retryLoop(attempts).rl, 0);
});

t('negative:換了策略就自成一組,不跟前面累計', () => {
  const r = retryLoop([
    { intent_class: 'x', target: 'y', strategy: 'a' },
    { intent_class: 'x', target: 'y', strategy: 'b' },
    { intent_class: 'x', target: 'y', strategy: 'c' },
  ]);
  assert.equal(r.rl, 0);
  assert.equal(r.groups.length, 3);
});

t('low-evidence:沒有任何嘗試紀錄時 RL 是 null 不是 0', () => {
  const r = retryLoop([]);
  assert.equal(r.rl, null);
  assert.match(r.note, /unknown, not zero/);
});

// ---- FP-20 SLF:CT-021 ----
t('CT-021 positive:restart 成功但 endpoint 是死的,而監控說健康 → SLF', () => {
  const r = silentLivenessFailure({
    restartIssued: true, processAlive: true, endpointHealthy: false,
    heartbeatFresh: false, watchdogReportsHealthy: true,
  });
  assert.equal(r.verdict, 'SILENT_LIVENESS_FAILURE');
  assert.equal(r.watchdog_state_mismatch, true);
  assert.equal(r.severity_family, 'B');
  assert.match(r.note, /the failure that hides failures/);
});

t('CT-021:restart 下過本身完全不算證據', () => {
  const r = silentLivenessFailure({ restartIssued: true });
  assert.equal(r.verdict, 'UNKNOWN');
  assert.equal(r.restart_issued_is_not_evidence, true);
  assert.match(r.note, /returning 0 says.*nothing/s);
});

t('negative:所有真訊號都好就是 HEALTHY', () => {
  const r = silentLivenessFailure({
    processAlive: true, endpointHealthy: true, heartbeatFresh: true, outputGrowing: true,
  });
  assert.equal(r.verdict, 'HEALTHY');
  assert.equal(r.healthy, true);
});

t('exclusion:壞了但監控也說壞了,那是 UNHEALTHY 不是 SLF', () => {
  const r = silentLivenessFailure({
    endpointHealthy: false, watchdogReportsHealthy: false,
  });
  assert.equal(r.verdict, 'UNHEALTHY');
  assert.equal(r.watchdog_state_mismatch, false);
});

t('low-evidence:沒量到的訊號要列出來', () => {
  const r = silentLivenessFailure({ endpointHealthy: true });
  assert.deepEqual([...r.unmeasured_signals], ['processAlive', 'heartbeatFresh', 'outputGrowing']);
});

// ---- FP-13 Phantom Verification:CT-019 / CT-043 ----
t('五個階段照 §22.11 原文', () =>
  assert.deepEqual([...VERIFICATION_STAGES],
    ['STARTED', 'COMPLETED', 'OUTPUT_EXISTS', 'OUTPUT_CONSUMED', 'RESULT_LINKED_TO_CLAIM']));

t('CT-043 positive:8 個 agent、1.4MB transcript、沒完成,卻被當交叉驗證', () => {
  const r = phantomVerification({
    started: true, completed: false,
    agents_spawned: 8, transcript_bytes: 1_400_000,
    cited_as_verification: true,
  });
  assert.equal(r.verdict, 'PHANTOM_VERIFICATION');
  assert.equal(r.may_increase_confidence, false);
  assert.equal(r.stopped_at, 'COMPLETED');
  assert.equal(r.severity_family, 'B');
  assert.match(r.note, /a large phantom is still a phantom/);
});

t('CT-019 positive:跑完也有輸出,但沒有人讀 → 仍然是 phantom', () => {
  const r = phantomVerification({
    started: true, completed: true, output_exists: true, output_consumed: false,
    cited_as_verification: true,
  });
  assert.equal(r.verdict, 'PHANTOM_VERIFICATION');
  assert.equal(r.stopped_at, 'OUTPUT_CONSUMED');
});

t('negative:五個階段全走完才可以提高信心', () => {
  const r = phantomVerification({
    started: true, completed: true, output_exists: true,
    output_consumed: true, result_linked_to_claim: true,
    cited_as_verification: true,
  });
  assert.equal(r.verdict, 'VERIFIED');
  assert.equal(r.may_increase_confidence, true);
});

t('exclusion:沒走完但也沒拿來當證據,只是 INCOMPLETE 不是 phantom', () => {
  const r = phantomVerification({ started: true, completed: false });
  assert.equal(r.verdict, 'INCOMPLETE');
  assert.equal(r.severity_family, null);
});

t('low-evidence:什麼都沒有的 workflow 停在第一階段', () => {
  const r = phantomVerification({});
  assert.equal(r.stopped_at, 'STARTED');
  assert.deepEqual([...r.stages_reached], []);
});

// ---- §7.3 TOS ----
t('三個成分都有才算得出 TOS', () => {
  const r = toolOccupancyStarvation({
    toolWallTime: 80, activeSessionTime: 100, substantiveOutputRate: 0, stalledTask: true,
  });
  assert.ok(Math.abs(r.tos - (0.4 * 0.8 + 0.35 * 1 + 0.25 * 1)) < 1e-9);
});

t('任一成分沒量到就回 null,不准當 0', () => {
  const r = toolOccupancyStarvation({ toolWallTime: 80, activeSessionTime: 100 });
  assert.equal(r.tos, null);
  assert.deepEqual([...r.missing_components], ['output_starvation', 'stalled_task']);
  assert.match(r.note, /would make an unwired system look perfectly healthy/);
});

// ---- FS-TOOL-002 ----
t('同一個 signature 重複出現會抬高關注,但不給校準過的分數', () => {
  const r = recurrenceRisk(['stale_watcher:build', 'stale_watcher:build', 'other']);
  assert.equal(r.elevated, true);
  assert.equal(r.provisional, true);
  assert.equal(r.repeated_signatures[0].count, 2);
  assert.match(r.note, /magnitude of the raise is not calibrated/);
});

t('沒有重複就不抬高', () =>
  assert.equal(recurrenceRisk(['a', 'b']).elevated, false));

// ---- 專案慣例 ----
t('零依賴:liveness.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/liveness.js', import.meta.url), 'utf8');
  assert.ok(!/^import\s/m.test(src));
});

t('「跑很久是最沒有資訊量的訊號」那段推理留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/liveness.js', import.meta.url), 'utf8');
  assert.match(src, /最好取得的訊號,也是最沒有資訊量的訊號/);
});

t('每個回傳都帶版本', () => {
  assert.equal(retryLoop([]).version, VERSION);
  assert.equal(phantomVerification({}).version, VERSION);
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exitCode = fail ? 1 : 0;
