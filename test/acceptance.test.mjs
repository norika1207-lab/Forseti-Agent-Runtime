// 規格書 v0.1 第 14 節:驗收測試 v0.1。
//
// 這一份跟其他測試檔不同:其他的驗證「模組自己對不對」,
// 這一份驗證「整套符合不符合規格」。每一條的名稱與情境都照規格書那張表,
// 不改寫、不放寬。做不到的那幾條明確標成 NOT IMPLEMENTED 並說明原因,
// 不從清單裡拿掉 —— 從清單裡拿掉會讓通過率看起來比實際好。
import assert from 'node:assert/strict';
import { createRuntime } from '../src/runtime.js';
import { canIntervene, evaluateProbe } from '../src/intervention.js';

let pass = 0, fail = 0, skipped = 0;
function at(id, scenario, fn) {
  try { fn(); console.log(`PASS  ${id}  ${scenario}`); pass++; }
  catch (e) { console.log(`FAIL  ${id}  ${scenario}\n      ${e.message}`); fail++; }
}
function notImplemented(id, scenario, why) {
  console.log(`SKIP  ${id}  ${scenario}\n      NOT IMPLEMENTED: ${why}`);
  skipped++;
}

const T = 1_700_000_000_000;
const M = 60_000;
let clock = T;
const rt = () => createRuntime({ now: () => clock });
const SNAP = {
  objective: 'o', current_step: 's', last_verified_state: 'v', active_hypothesis: 'h',
  open_tool_calls: [], artifact_refs: [], unresolved_decisions: [],
  exact_next_step: 'run the failing test',
};

console.log('規格書 v0.1 第 14 節 驗收測試\n' + '─'.repeat(70));

// AT-UI-01 健康的 30 分鐘寫碼 session:不得有 modal 中斷,環境指示器保持安靜
at('AT-UI-01', 'Healthy coding session for 30m', () => {
  clock = T;
  const r = rt();
  r.setGoal(['src/auth']);
  for (let i = 0; i < 30; i++) {
    clock = T + i * M;
    r.heartbeat();
    r.ingest([{ attributed_agent: 'w1', name: 'Edit', at: clock, input: { file_path: 'src/auth/f' + i + '.js' } }]);
    r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'h' + i });
  }
  const temp = r.runtimeTemperature();
  assert.ok(temp.temperature === null || temp.temperature < 0.5,
    '健康 session 的溫度不該進入 ELEVATED 以上,實際 ' + temp.temperature);
  for (const a of ['SUGGEST_RECOVERY', 'FREEZE_RETRY', 'CREATE_SUCCESSOR']) {
    assert.equal(r.mayIntervene(a).allowed, false, a + ' 不該在健康 session 觸發');
  }
});

// AT-UI-02 工具跑 12 分鐘,有心跳但沒有已驗證進展:UI 要分得出「活著但停滯」與「死了」
at('AT-UI-02', 'Tool runs 12m with heartbeat but no verified progress', () => {
  clock = T;
  const r = rt();
  r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'x' });
  for (let i = 0; i <= 12; i++) { clock = T + i * M; r.heartbeat(); }
  const l = r.liveness({ activeFrom: T, activeTo: clock });
  assert.ok(l.silent_execution_ratio < 0.2, '有心跳,不是死了');
  assert.ok(l.last_verified_progress_age_ms >= 12 * M, '但已驗證進展停在 12 分鐘前');
});

// AT-UI-03 設定的間隔內沒有心跳:沉默執行訊號上升,使用者看得到存活警告
at('AT-UI-03', 'No heartbeat for configured interval', () => {
  clock = T;
  const r = rt();
  clock = T + 20 * M;
  const l = r.liveness({ activeFrom: T, activeTo: clock });
  assert.ok(l.silent_execution_ratio > 0.8, '完全沒有心跳,沉默比應該很高');
  const s = r.status();
  assert.ok(s.unavailable.some((x) => /cannot tell working-quietly from hung/.test(x)));
});

// AT-ART-01 模型宣稱產出檔案,檔案存在但 0 bytes:宣稱不得成為 VERIFIED,要顯示現實風險
at('AT-ART-01', 'Model claims file produced; file exists at 0 bytes', () => {
  clock = T;
  const r = rt();
  const v = r.verifyArtifact({ kind: 'FILE_CREATED', target: 'report.md' }, { exists: true, bytes: 0 });
  assert.equal(v.verdict, 'REFUTED', '不得成為 VERIFIED');
  assert.notEqual(v.epistemic, 'VERIFIED');
  const s5 = r.signals().find((x) => x.id === 'S5');
  assert.equal(s5.value, 1, '現實不符訊號要升起');
});

// AT-DRIFT-01 沒有明確或可靠的目標:系統不得把語意飄移當成事實陳述
at('AT-DRIFT-01', 'No explicit/reliable goal exists', () => {
  clock = T;
  const r = rt();
  // 前幾段就在做很多不同的事,目標不可靠
  for (let i = 0; i < 200; i++) {
    r.ingest([{ attributed_agent: 'w1', name: 'Read', at: T + i * 1000, input: { file_path: `area${i % 9}/sub/f.js` } }]);
  }
  clock = T + 200 * 1000;
  const d = r.driftCheck();
  assert.notEqual(d.verdict?.is_drift, true, '不得斷言飄移');
  assert.ok(d.verdict === null || d.verdict.is_drift === null);
  const text = JSON.stringify(d);
  assert.ok(/cannot be determined/.test(text), '要說判斷不了');
  assert.ok(!/agent drifted/i.test(text), '不得說 agent drifted');
});

// AT-OBS-01 啟用 Forseti 標註:純觀測模式下不得發生 prompt 或 context 修改
at('AT-OBS-01', 'Forseti annotation enabled, observation-only', () => {
  clock = T;
  const r = rt();
  r.countTurn();
  r.noteIntervention('QUIET_ANNOTATION', 'temperature elevated');
  const s = r.interventionStats();
  assert.equal(s.injected, 0, '標註不得注入');
  assert.equal(s.injection_rate, 0);
  assert.equal(s.interventions, 1, '但仍要記錄');
});

// AT-INT-01 使用者取消長任務:技術上可行時,中斷之前或之時建立復原快照
at('AT-INT-01', 'User cancels long task', () => {
  clock = T;
  const r = rt();
  assert.equal(r.canInterrupt().ready, false, '還沒有快照時不該說可以安全中斷');
  r.updateSnapshot(SNAP);
  assert.equal(r.canInterrupt().ready, true);
  r.recordInterrupt();
  assert.equal(r.liveness().unsafe_interrupt_rate, 0, '有快照的中斷是安全的');
});

// AT-PROBE-01 反向盤問說工作對齊,但磁碟證據相反:可觀測證據勝過自述
at('AT-PROBE-01', 'Probe claims alignment but disk evidence contradicts', () => {
  clock = T;
  const r = rt();
  r.probe({ reason: 'stagnation' });
  const e = r.evaluateProbeAnswers({
    current_goal_as_understood: 'ship auth',
    evidence_of_progress: 'everything is working',
  });
  assert.ok(e.contradictions.length > 0, '要抓到矛盾');
  assert.match(e.note, /observable record wins/);
  assert.equal(r.interventionStats().injected, 1, '探針本身要被記成注入');
});

// AT-SAMP-01 大 session 含一個注入的異常窗口:選取器要在前 K 找到它,不必送全 session
at('AT-SAMP-01', 'Large session with one injected abnormal window', () => {
  clock = T;
  const r = rt();
  const evs = [];
  for (let i = 0; i < 240; i += 5) {
    evs.push({ attributed_agent: 'w1', name: 'Read', at: T + i * M, input: { file_path: 'f' + i + '.js' } });
  }
  for (let k = 0; k < 30; k++) {
    evs.push({ attributed_agent: 'w1', name: 'Edit', at: T + 120 * M, input: { file_path: 'stuck.js' } });
  }
  r.ingest(evs);
  clock = T + 240 * M;
  const out = r.suspiciousWindows({ bucketMs: 5 * M, topK: 5 });
  assert.ok(out.windows.some((w) => w.events.some((e) => e.file_path === 'stuck.js')),
    '注入的異常必須落在前 K 個窗口裡');
  assert.ok(out.reduction < 0.5, '不必送全 session,實際收窄到 ' + (out.reduction * 100).toFixed(0) + '%');
});

// AT-RSC-01 臨界分數只由一個弱啟發造成:不得硬救援或封鎖,要顯示證據不足
at('AT-RSC-01', 'Critical score caused only by one weak heuristic', () => {
  const v = canIntervene('CREATE_SUCCESSOR', { temperature: 0.95 });
  assert.equal(v.allowed, false, '單一弱啟發造成的臨界分數不得觸發硬救援');
  assert.ok(v.requires.length > 0, '要說出還缺什麼');
  assert.match(v.note, /never sufficient/);
  const block = canIntervene('BLOCK_HIGH_RISK', { temperature: 0.99 });
  assert.equal(block.allowed, false, '也不得封鎖');
});

console.log('─'.repeat(70));
console.log(`\n驗收：${pass} 通過，${fail} 失敗，${skipped} 未實作，共 ${pass + fail + skipped} 條`);
console.log(`\n未涵蓋的規格書條目：AT-UI-01 到 03 的介面層(桌面 sidecar、inline annotation、rescue card)`);
console.log(`本檔驗證的是那些介面底下的判斷邏輯,不是介面本身。`);
process.exit(fail ? 1 : 0);
