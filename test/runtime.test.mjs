// Forseti Runtime：七個模組收成一個介面之後，接上來的人真的用得起來嗎。
//
// 這一份測的不是邏輯正確(那是各模組自己的測試),
// 是「一個沒讀過原始碼的人照 README 接上去,會不會撞牆」。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRuntime } from '../src/runtime.js';
import { createEdge } from '../src/handoff.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

const T0 = 1_700_000_000_000;
let clock = T0;
const rt = () => createRuntime({ now: () => clock });
const ev = (agent, tool, file, ms, label = null) => ({
  attributed_agent: agent, agent_label: label, name: tool,
  at: T0 + ms, input: { file_path: file }, session_id: agent + '-s',
});

// ---- 開箱狀態要誠實 ----
t('全新的 runtime 說得出自己還不知道什麼', () => {
  const s = rt().status();
  assert.equal(s.capture.capture_rate, null);
  assert.equal(s.automation_rate, null);
  assert.ok(s.unavailable.some((x) => /No events received yet/.test(x)));
  assert.ok(s.unavailable.some((x) => /No handoff rules configured/.test(x)));
});

t('沒設交接規則時,一輪做完也不會送出任何東西', () => {
  const r = rt();
  r.ingest([ev('w1', 'Edit', 'a.js', 0)]);
  assert.equal(r.completeTurn({ agent_id: 'w1' }).dispatch.length, 0);
});

// ---- ingest ----
t('餵事件進去,覆蓋範圍自己就建好了', () => {
  const r = rt();
  r.ingest([ev('w1', 'Read', 'a.js', 0), ev('w1', 'Edit', 'b.js', 1000)]);
  const cov = r.inspect().coverages.find((c) => c.agent_id === 'w1');
  assert.equal(cov.files['a.js'], 'READ_FULL');
  assert.equal(cov.files['b.js'], 'EDITED');
});

t('採集漏掉的東西會浮上來,不會被吞掉', () => {
  const r = rt();
  const out = r.ingest([ev('w1', 'Read', 'a.js', 0), { name: 'Read', at: T0, input: { file_path: 'x' } }]);
  assert.equal(out.accepted, 1);
  assert.equal(out.skipped, 1);
  assert.match(r.status().unavailable.join(), /Capture dropped 1 event/);
});

t('撞名與改名在 ingest 當下就回報,不必等使用者發現送錯', () => {
  const r = rt();
  const out = r.ingest([
    ev('w1', 'Read', 'a.js', 0, 'Dev'),
    ev('w3', 'Read', 'b.js', 1000, 'Dev'),
    ev('w1', 'Read', 'c.js', 2000, 'Backend'),
  ]);
  assert.equal(out.ambiguous_labels.length, 1);
  assert.equal(out.label_drift.length, 1);
});

t('已經撞車的寫入在 ingest 就看得到(事後偵測,不是攔截)', () => {
  const r = rt();
  const out = r.ingest([
    ev('w1', 'Edit', 'shared.js', 0),
    ev('w2', 'Edit', 'shared.js', 3000),
  ]);
  assert.equal(out.conflicts.length, 1);
  assert.equal(out.conflicts[0].gap_seconds, 3);
});

// ---- 攔截 ----
t('派工前問一句,同一個檔案被別人佔著就不會放行', () => {
  const r = rt();
  r.openScope({ agent_id: 'w1', task_id: 't1', declared: ['src/api.js'] });
  const v = r.requestWrite({ agent_id: 'w2', task_id: 't2', declared: ['src/api.js'] });
  assert.notEqual(v.decision, 'ALLOW');
});

t('沒人佔著就放行,而且說得出這是完整判斷', () => {
  const v = rt().requestWrite({ agent_id: 'w1', task_id: 't', declared: ['src/api.js'] });
  assert.equal(v.decision, 'ALLOW');
  assert.equal(v.is_complete, true);
});

t('登記之後實際寫的檔案會回填,關閉時越界看得出來', () => {
  const r = rt();
  r.openScope({ agent_id: 'w1', task_id: 't1', declared: ['src/api.js'] });
  r.ingest([ev('w1', 'Edit', 'src/api.js', 0), ev('w1', 'Edit', 'src/secret.js', 1000)]);
  const closed = r.closeScope('t1');
  assert.deepEqual([...closed.out_of_scope], ['src/secret.js']);
});

t('關閉之後不再擋人', () => {
  const r = rt();
  r.openScope({ agent_id: 'w1', task_id: 't1', declared: ['src/api.js'] });
  r.closeScope('t1');
  assert.equal(r.requestWrite({ agent_id: 'w2', task_id: 't2', declared: ['src/api.js'] }).decision, 'ALLOW');
});

t('關閉一個不存在的佔用回 null,不假裝成功', () =>
  assert.equal(rt().closeScope('nope'), null));

// ---- 交接規則 ----
t('建規則的當下就擋掉環,而且不部分套用', () => {
  const r = rt();
  const out = r.setEdges([createEdge({ id: 'a', from: 'A', to: 'B' }), createEdge({ id: 'b', from: 'B', to: 'A' })]);
  assert.equal(out.ok, false);
  assert.equal(out.applied, false);
  assert.equal(r.inspect().edges.length, 0, '有環就整批不套用,半套的規則圖更難查');
});

t('沒有環的規則套用得上', () => {
  const r = rt();
  assert.equal(r.setEdges([createEdge({ id: 'a', from: 'A', to: 'B' })]).ok, true);
  assert.equal(r.inspect().edges.length, 1);
});

t('一輪做完,該送哪裡自己算得出來', () => {
  const r = rt();
  r.setEdges([createEdge({ id: 'e', from: 'w1', to: 'w2' })]);
  r.ingest([ev('w1', 'Edit', 'a.js', 0)]);
  assert.deepEqual(r.completeTurn({ agent_id: 'w1' }).dispatch.map((d) => d.to), ['w2']);
});

t('什麼都沒動的一輪不觸發任何邊', () => {
  const r = rt();
  r.setEdges([createEdge({ id: 'e', from: 'w1', to: 'w2' })]);
  const out = r.completeTurn({ agent_id: 'w1' });
  assert.equal(out.dispatch.length, 0);
  assert.equal(out.skipped_no_output, true);
});

t('每一棒附上要轉述哪些檔案,那是 M5 幫 M2 省下來的', () => {
  const r = rt();
  r.setEdges([createEdge({ id: 'e', from: 'w1', to: 'w2' })]);
  r.ingest([
    ev('w1', 'Read', 'shared.js', 0), ev('w1', 'Edit', 'api.js', 1000),
    ev('w2', 'Read', 'shared.js', 60_000),
  ]);
  const pkt = r.completeTurn({ agent_id: 'w1' }).packets[0];
  assert.ok(pkt.briefing_files.includes('api.js'), 'w2 沒看過 api.js,要轉述');
  assert.ok(pkt.saved_files.includes('shared.js'), 'w2 讀過 shared.js,不必再講一次');
});

t('對方沒有覆蓋資料時,轉述清單是 null 不是空陣列', () => {
  const r = rt();
  r.setEdges([createEdge({ id: 'e', from: 'w1', to: 'w2' })]);
  r.ingest([ev('w1', 'Edit', 'a.js', 0)]);
  assert.equal(r.completeTurn({ agent_id: 'w1' }).packets[0].briefing_files, null);
});

// ---- 指標 ----
t('自動化率會動:規則送越多、人按越少,數字越高', () => {
  const r = rt();
  r.setEdges([createEdge({ id: 'e', from: 'w1', to: 'w2' })]);
  r.ingest([ev('w1', 'Edit', 'a.js', 0)]);
  r.completeTurn({ agent_id: 'w1' });
  assert.equal(r.status().automation_rate, 1);
  r.recordManualHandoff();
  assert.equal(r.status().automation_rate, 0.5);
});

t('派工挑人:誰的 context 熱在那批檔案上', () => {
  const r = rt();
  r.ingest([ev('w1', 'Read', 'api.js', 0), ev('w2', 'Read', 'ui.js', 60_000)]);
  assert.equal(r.suggestAssignee(['api.js']).agent_id, 'w1');
});

// ---- 存讀 ----
t('存下去讀回來,累積的指標與覆蓋範圍都活著', () => {
  const a = rt();
  a.setEdges([createEdge({ id: 'e', from: 'w1', to: 'w2' })]);
  a.ingest([ev('w1', 'Edit', 'api.js', 0)]);
  a.completeTurn({ agent_id: 'w1' });
  const text = a.save();

  clock = T0 + 86_400_000;
  const b = rt();
  b.restore(text);
  assert.equal(b.status().automation_rate, 1);
  assert.equal(b.inspect().coverages[0].files['api.js'], 'EDITED');
  assert.equal(b.inspect().edges.length, 1);
  clock = T0;
});

t('還原時重啟前正在寫的 agent 被標成待確認,而且仍然擋人', () => {
  const a = rt();
  a.openScope({ agent_id: 'w1', task_id: 't', declared: ['api.js'] });
  const text = a.save();

  const b = rt();
  const r = b.restore(text);
  assert.equal(r.stale_scopes.length, 1);
  assert.notEqual(b.requestWrite({ agent_id: 'w9', task_id: 'n', declared: ['api.js'] }).decision, 'ALLOW');
});

t('還原失敗時不覆蓋現有狀態', () => {
  const r = rt();
  r.openScope({ agent_id: 'w1', task_id: 't', declared: ['a.js'] });
  const out = r.restore('壞掉的內容');
  assert.equal(out.state, null);
  assert.equal(r.inspect().scopes.length, 1, '讀失敗不該把現有狀態清掉');
});

// ---- 界線 ----
t('這裡只回答不動作:回傳的東西沒有任何一項是已執行的動作', () => {
  const r = rt();
  r.setEdges([createEdge({ id: 'e', from: 'w1', to: 'w2' })]);
  r.ingest([ev('w1', 'Edit', 'a.js', 0)]);
  const out = r.completeTurn({ agent_id: 'w1' });
  assert.ok('dispatch' in out, '回傳的是計畫');
  assert.ok(!('sent' in out) && !('delivered' in out), '不該出現任何表示已送出的欄位');
});

t('內部狀態看得見,沒有藏起來的東西', () => {
  const r = rt();
  r.ingest([ev('w1', 'Edit', 'a.js', 0)]);
  const i = r.inspect();
  for (const k of ['events', 'scopes', 'coverages', 'edges', 'stats']) assert.ok(k in i, '應可檢視: ' + k);
  assert.throws(() => { i.events.push({}); }, TypeError);
});

t('runtime 只 import 自家模組,沒有任何第三方依賴', () => {
  const src = readFileSync(new URL('../src/runtime.js', import.meta.url), 'utf8');
  const imports = src.match(/from\s+'([^']+)'/g) ?? [];
  for (const im of imports) {
    assert.match(im, /from '\.\/[a-z]+\.js'/, '只准 import 同目錄模組,實際: ' + im);
  }
});

t('只回答不動作這條界線寫在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/runtime.js', import.meta.url), 'utf8');
  assert.ok(/這裡只回答,不動作/.test(src));
  assert.ok(/它就從一組原語/.test(src), '越線的後果必須寫明');
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
