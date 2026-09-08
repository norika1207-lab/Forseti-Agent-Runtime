// Forseti Runtime：七個模組收成一個介面之後，接上來的人真的用得起來嗎。
//
// 這一份測的不是邏輯正確(那是各模組自己的測試),
// 是「一個沒讀過原始碼的人照 README 接上去,會不會撞牆」。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRuntime } from '../src/runtime.js';
import { createEdge } from '../src/handoff.js';
import { VERDICTS as VERD } from '../src/heartbeat.js';

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

// ---- 飄移接線(M7)----
// 以下測試的事件要落在 now 之前,所以把時鐘往後推十分鐘。
clock = T0 + 600_000;
t('宣告北極星之後,飄移是對著它量的,不是推的', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Edit', 'src/auth/token.js', 0)]);
  const d = r.driftCheck();
  assert.equal(d.confidence, 'DECLARED_ANCHOR');
  assert.equal(d.level, 'ON_COURSE', '宣告 src/auth、動 src/auth/token.js,那在範圍內');
});

t('沒宣告目標時錨點用推的,而且讀數要標明它比較弱', () => {
  const r = rt();
  for (let i = 0; i < 60; i++) r.ingest([ev('w1', 'Read', `src/auth/f${i}.js`, i * 100)]);
  assert.equal(r.driftCheck().confidence, 'INFERRED_ANCHOR');
});

t('做著做著跑到別的地方,而且沒人宣告過轉向', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Edit', 'docs/blog/post.md', 0)]);
  const d = r.driftCheck();
  assert.equal(d.level, 'LOST');
  assert.equal(d.is_unannounced, true);
});

t('宣告過轉向就不算飄移,那是決定不是走失', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.declareTurn();
  r.ingest([ev('w1', 'Edit', 'docs/blog/post.md', 0)]);
  assert.equal(r.driftCheck().is_unannounced, false);
});

t('完全沒事件時直說判斷不了,不硬給一個等級', () => {
  const d = rt().driftCheck();
  assert.equal(d.level, null);
  assert.match(d.note, /No events yet/);
});

t('事件太少又沒宣告目標時,說清楚為什麼判斷不了,並指出怎麼補', () => {
  const r = rt();
  r.ingest([ev('w1', 'Edit', 'src/a.js', 0)]);
  const d = r.driftCheck();
  assert.equal(d.level, null);
  assert.match(d.note, /Declare one with setGoal/);
});

t('事件少但有宣告目標時給早期讀數,並標明樣本不足', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Edit', 'docs/blog/x.md', 0)]);
  const d = r.driftCheck();
  assert.equal(d.level, 'LOST');
  assert.equal(d.early_reading, true);
});

t('沒宣告目標會出現在 status 的缺口清單裡', () => {
  const r = rt();
  r.ingest([ev('w1', 'Edit', 'a.js', 0)]);
  assert.ok(r.status().unavailable.some((x) => /No goal declared/.test(x)));
});

t('沒有失敗訊號時,分不出被放棄還是做完了,要講出來', () => {
  const r = rt();
  r.ingest([ev('w1', 'Edit', 'a.js', 0)]);
  assert.ok(r.status().unavailable.some((x) => /cannot be told apart/.test(x)));
});

t('失敗訊號由宿主餵,這裡不讀任何文字', () => {
  const r = rt();
  assert.equal(r.recordFailure(clock), 1);
  assert.equal(r.recordFriction(clock), 1);
});

// ---- 來源鏈接線(M8)----
t('交付前查核:點名的檔案自己沒開過就擋下來', () => {
  const r = rt();
  r.ingest([ev('w1', 'Read', 'src/a.js', 0)]);
  const out = r.checkClaim({ files: ['src/a.js', 'src/b.js', 'src/c.js'] });
  assert.equal(out.clean, false);
  assert.equal(out.findings[0].shape, 'SOURCE_ERASURE');
  assert.deepEqual([...out.findings[0].erased_files], ['src/b.js', 'src/c.js']);
});

t('全部開過就放行', () => {
  const r = rt();
  r.ingest([ev('w1', 'Read', 'src/a.js', 0)]);
  assert.equal(r.checkClaim({ files: ['src/a.js'] }).clean, true);
});

t('過了三個形狀不等於乾淨,四個沒驗的要一起講', () => {
  const out = rt().checkClaim({ files: [] });
  assert.match(out.note, /four others were not examined/);
  assert.equal(out.unchecked_shapes.length, 4);
});

t('宣稱數量對不上實際次數就標出來', () => {
  const r = rt();
  for (let i = 0; i < 5; i++) r.ingest([ev('w1', 'Read', `f${i}.js`, i * 100)]);
  const out = r.checkClaim({ claimed_count: 200 });
  assert.equal(out.findings[0].shape, 'SCOPE_INFLATION');
  assert.equal(out.findings[0].actual_count, 5);
});

t('讀回自己寫過的檔案算自產,不是第一手證據', () => {
  const r = rt();
  r.ingest([ev('w1', 'Write', 'LOG.md', 0)]);
  r.ingest([ev('w1', 'Read', 'LOG.md', 1000)]);
  assert.equal(r.evidenceMix().self_written, 1);
  assert.ok(r.inspect().self_written.includes('LOG.md'));
});

t('委派給 agent 的不算自己查的', () => {
  const r = rt();
  r.ingest([
    { attributed_agent: 'w1', name: 'Bash', at: clock - 20, input: { file_path: 'a.js' } },
    { attributed_agent: 'w1', name: 'Agent', at: clock - 10, input: {} },
  ]);
  const m = r.evidenceMix();
  assert.equal(m.delegated, 1, '派 agent 出去沒有 file_path,過不了採集層,但來源鏈必須看得到它');
  assert.ok(m.first_hand_ratio < 1);
});

t('燒了 agent 卻零產出,會被追出來', () => {
  const r = rt();
  r.recordInvestment({ id: 'wf1', agents: 8, tokens: 1_400_000 });
  r.closeInvestment('wf1', []);
  const b = r.status().barren;
  assert.equal(b.length, 1);
  assert.equal(b[0].agents, 8);
  assert.equal(b[0].tokens, 1_400_000);
});

t('有產出的委派不會被誤報', () => {
  const r = rt();
  r.recordInvestment({ id: 'wf1', agents: 22 });
  r.closeInvestment('wf1', ['AUDIT.md']);
  assert.equal(r.status().barren.length, 0);
});

t('北極星跨重啟活著,忘了目標飄移就永遠量不出來', () => {
  clock = T0 + 600_000;
  const a = rt();
  a.setGoal(['src/auth']);
  a.recordFailure(clock);
  a.ingest([ev('w1', 'Write', 'src/auth/x.js', 0)]);
  const text = a.save();

  const b = rt();
  b.restore(text);
  assert.deepEqual([...b.inspect().anchor.topics], ['src/auth']);
  assert.equal(b.inspect().anchor.inferred, false);
  assert.ok(b.inspect().self_written.includes('src/auth/x.js'), '自己寫過什麼也要活過重啟');
});

// ---- 心跳接線(M9)----
t('跑一輪心跳,拿回結論跟下次間隔', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  const b = r.beat();
  assert.equal(b.beat, 1);
  assert.ok(b.checked.includes('capture'));
  assert.ok(VERD.includes(b.verdict));
  assert.ok(b.next.delay_ms > 0 || b.next.stop);
});

t('v0.2:不再拿寫入檔案數當產出,空轉偵測預設是關的', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0), ev('w1', 'Write', 'src/auth/b.js', 10)]);
  const b = r.beat();
  assert.equal(b.verified_progress, null, '寫了兩個檔不等於有兩項推進');
  assert.equal(b.idle_detection_active, false);
  assert.ok(b.reasons.some((x) => /not accepted as proof of progress/.test(x)));
});

t('宿主給得出驗證資料時,空轉偵測才打開', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  assert.equal(r.beat({ produced: 1 }).idle_detection_active, true);
});

t('連續空轉到上限,心跳回 STOP 而不是排下一輪', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Read', 'src/auth/a.js', 0)]);
  let last;
  for (let i = 0; i < 3; i++) last = r.beat({ produced: 0 });
  assert.equal(last.verdict, 'STOP');
  assert.equal(last.next.stop, true);
  assert.equal(last.next.delay_ms, null);
  assert.ok(last.reasons.some((x) => /not progress/.test(x)));
});

t('有產出就把空轉計數歸零,不會誤停', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Read', 'src/auth/a.js', 0)]);
  r.beat({ produced: 0 }); r.beat({ produced: 0 });
  const b = r.beat({ produced: 1 });
  assert.equal(b.barren_streak, 0);
  assert.notEqual(b.verdict, 'STOP');
});

t('零產出的委派會讓心跳叫人', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  r.recordInvestment({ id: 'wf1', agents: 8 });
  r.closeInvestment('wf1', []);
  const b = r.beat({ produced: 1 });
  assert.equal(b.verdict, 'WAKE');
  assert.ok(b.reasons.some((x) => /produced nothing/.test(x)));
});

t('心跳依結論派工,派出去的走同一條投入路徑', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  r.recordInvestment({ id: 'wf1', agents: 8 });
  r.closeInvestment('wf1', []);
  const b = r.beat({ produced: 1, agents: ['investment-audit'] });
  assert.deepEqual(b.dispatch.dispatch.map((x) => x.agent), ['investment-audit']);
});

t('沒有可派的 agent 時要講,不靜默略過', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  r.recordInvestment({ id: 'wf1', agents: 8 });
  r.closeInvestment('wf1', []);
  const b = r.beat({ produced: 1, agents: [] });
  assert.equal(b.dispatch.dispatch.length, 0);
  assert.ok(b.dispatch.unhandled.length > 0);
});

t('空轉計數跨重啟活著,不然連續空轉永遠數不到', () => {
  const a = rt();
  a.setGoal(['src/auth']);
  a.ingest([ev('w1', 'Read', 'src/auth/a.js', 0)]);
  a.beat({ produced: 0 }); a.beat({ produced: 0 });
  const text = a.save();

  const b = rt();
  b.restore(text);
  assert.equal(b.beatLog().barren_streak, 2);
  assert.equal(b.beat({ produced: 0 }).verdict, 'STOP', '重啟不該讓計數歸零,那等於永遠停不下來');
});

// ---- 溫度計接線(M10)----
t('記一筆溫度,拿回區間跟建議', () => {
  const r = rt();
  const out = r.recordTemperature({ checked: 200, generated: 800, source: 'PROVIDER_REPORTED' });
  assert.equal(out.zone, 'CRITICAL');
  assert.equal(out.advice.action, 'PIN_EVIDENCE');
});

t('沒讀數時直說量不到,並指出怎麼補', () => {
  const t2 = rt().temperature();
  assert.equal(t2.zone, null);
  assert.match(t2.note, /recordTemperature/);
});

t('壓縮前後比對,看丟掉的是工具輸出還是自己的敘述', () => {
  const r = rt();
  r.recordTemperature({ checked: 800, generated: 200 });
  const d = r.recordCompaction({ checked: 200, generated: 200 });
  assert.ok(d.fact_ratio_drop > 0.2);
  assert.equal(d.lost_was_checked, 1);
  assert.equal(d.alarming, true);
});

t('第一次壓縮沒有前一筆可比時要直說', () => {
  const d = rt().recordCompaction({ checked: 1, generated: 1 });
  assert.equal(d.fact_ratio_drop, null);
  assert.match(d.note, /No earlier reading/);
});

t('多筆讀數看得出趨勢', () => {
  const r = rt();
  r.recordTemperature({ checked: 90, generated: 10 });
  r.recordTemperature({ checked: 50, generated: 50 });
  r.recordTemperature({ checked: 20, generated: 80 });
  assert.equal(r.temperature().trend.trend, 'RISING');
});

t('心跳會帶上溫度,沒讀數就是 null 不是猜一個', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  assert.equal(r.beat({ produced: 1 }).temperature, null);
  r.recordTemperature({ checked: 100, generated: 900 });
  assert.equal(r.beat({ produced: 1 }).temperature.zone, 'CRITICAL');
});

t('沒量過溫度會出現在缺口清單', () => {
  const r = rt();
  r.ingest([ev('w1', 'Write', 'a.js', 0)]);
  assert.ok(r.status().unavailable.some((x) => /No temperature reading/.test(x)));
});

t('溫度歷史跨重啟活著,不然趨勢每次重啟都歸零', () => {
  const a = rt();
  a.recordTemperature({ checked: 90, generated: 10 });
  a.recordCompaction({ checked: 20, generated: 80 });
  const text = a.save();
  const b = rt();
  b.restore(text);
  assert.equal(b.temperature().trend.points.length, 2);
  assert.equal(b.temperature().compactions.length, 1);
});

// ---- shell 展開接線 ----
t('透過 shell 改檔案看得到,不然採集率會掉回 19.6%', () => {
  const r = rt();
  r.ingest([{ attributed_agent: 'w1', name: 'Bash', at: clock - 100, input: { command: 'cat > src/new.js <<EOF' } }]);
  const cov = r.inspect().coverages.find((c) => c.agent_id === 'w1');
  assert.equal(cov.files['src/new.js'], 'EDITED');
});

t('看不透的 shell 命令會被計數,並列進缺口清單', () => {
  const r = rt();
  r.ingest([{ attributed_agent: 'w1', name: 'Bash', at: clock - 100, input: { command: "python3 - <<'PY'" } }]);
  assert.equal(r.status().unavailable.some((x) => /opaque to static analysis/.test(x)), true);
});

t('shell 展開的寫入會進佔用範圍的越界偵測', () => {
  const r = rt();
  r.openScope({ agent_id: 'w1', task_id: 't', declared: ['src/a.js'] });
  r.ingest([{ attributed_agent: 'w1', name: 'Bash', at: clock - 100, input: { command: 'echo x > src/secret.js' } }]);
  assert.deepEqual([...r.closeScope('t').out_of_scope], ['src/secret.js']);
});

// ---- context 收銀台接線(M1)----
const BUDGET = { session_id: 's', window_total: 100_000, consumed: 10_000, source: 'PROVIDER_REPORTED' };
const CONTRACT = { contract_id: 'c1', max_return_tokens: 5000 };
const CAP = (over = {}) => ({
  capsule_id: 'cap1', produced_by: 'w1', task_ref: 't1', payload_ref: 'p1',
  summary: 'done', token_cost: 500, raw_token_size: 50_000, contract_ref: 'c1', ...over,
});

t('沒設預算就不報價,而且說得出怎麼補', () => {
  const q = rt().quote(CAP());
  assert.equal(q.quote, null);
  assert.match(q.note, /setBudget/);
});

t('預算的來源必須明講是真值還是估的', () => {
  assert.throws(() => rt().setBudget({ ...BUDGET, source: undefined }), /PROVIDER_REPORTED or ESTIMATED/);
});

t('報價:在東西進來之前先看得到它要花多少', () => {
  const r = rt();
  r.setBudget(BUDGET);
  r.setContract(CONTRACT);
  const q = r.quote(CAP());
  assert.equal(q.quote.token_cost, 500);
  assert.equal(q.contract_found, true);
  assert.ok(q.quote.budget_after < q.quote.budget_before);
  assert.equal(q.capsule.state, 'PREVIEWED', '報價本身就是看過價錢那一步');
});

t('收下之後預算真的被扣', () => {
  const r = rt();
  r.setBudget(BUDGET);
  r.setContract(CONTRACT);
  const before = r.register().budget.remaining;
  r.accept(r.quote(CAP()).capsule);
  assert.equal(r.register().budget.remaining, before - 500);
  assert.equal(r.register().reserved, 500, '進 reserved 不是 consumed:真正花掉要等 provider 回報');
});

t('退回的膠囊不進 context,預算不動', () => {
  const r = rt();
  r.setBudget(BUDGET);
  r.setContract(CONTRACT);
  const before = r.register().budget.remaining;
  r.reject(r.quote(CAP()).capsule);
  assert.equal(r.register().budget.remaining, before);
});

t('超過契約上限的膠囊收不下,那是刻意的', () => {
  const r = rt();
  r.setBudget(BUDGET);
  r.setContract(CONTRACT);
  assert.throws(() => r.accept(r.quote(CAP({ token_cost: 9999 })).capsule), /max_return_tokens/);
});

t('不認得的契約要拋錯,不默默收下', () => {
  const r = rt();
  r.setBudget(BUDGET);
  assert.throws(() => r.accept(r.quote(CAP({ contract_ref: 'nope' })).capsule), /Unknown contract/);
});

t('擋下了多少原始 token,算得出來', () => {
  const r = rt();
  r.setBudget(BUDGET);
  r.setContract(CONTRACT);
  r.accept(r.quote(CAP()).capsule);
  assert.equal(r.register().blocked_raw_tokens, 49_500, '五萬的原始輸出只放五百進來');
});

t('沒設預算會出現在缺口清單', () => {
  const r = rt();
  r.ingest([ev('w1', 'Write', 'a.js', -100)]);
  assert.ok(r.status().unavailable.some((x) => /No context budget set/.test(x)));
});

t('預算與契約跨重啟活著', () => {
  const a = rt();
  a.setBudget(BUDGET);
  a.setContract(CONTRACT);
  a.accept(a.quote(CAP()).capsule);
  const text = a.save();
  const b = rt();
  b.restore(text);
  assert.equal(b.register().budget.consumed, 10_000, 'consumed 不該被自己改');
  assert.equal(b.register().reserved, 500);
  assert.equal(b.register().capsules, 1);
});

// ---- 代價接線(M4)----
const PROJ = {
  'src/app.js': "import { auth } from './auth.js'",
  'src/auth.js': "import { hash } from './util.js'",
  'src/util.js': '',
};

t('沒建圖就算不出代價,而且說得出怎麼補', () => {
  const c = rt().costOf('src/util.js');
  assert.equal(c.vector, null);
  assert.match(c.note, /indexProject/);
});

t('建圖之後,改一個檔案的波及範圍算得出來', () => {
  const r = rt();
  const idx = r.indexProject(PROJ);
  assert.equal(idx.files, 3);
  assert.equal(idx.resolution_rate, 1);
  const c = r.costOf('src/util.js');
  assert.equal(c.vector.d1_count, 1);
  assert.equal(c.vector.d2_count, 1, 'app 透過 auth 間接依賴 util');
});

t('代價不合成單一分數', () => {
  const r = rt();
  r.indexProject(PROJ);
  const v = r.costOf('src/util.js').vector;
  assert.ok(!('score' in v) && !('risk' in v));
  assert.equal(v.is_lower_bound, true);
});

t('波及範圍裡有別人正在寫的檔案,那一維算得出來', () => {
  const r = rt();
  r.indexProject(PROJ);
  r.openScope({ agent_id: 'w2', task_id: 't', declared: ['src/auth.js'] });
  r.ingest([ev('w2', 'Edit', 'src/auth.js', -100)]);
  assert.equal(r.costOf('src/util.js').vector.live_conflicts, 1);
});

t('沒建圖會出現在缺口清單', () =>
  assert.ok(rt().status().unavailable.some((x) => /No dependency graph/.test(x))));

// ---- 跨程序撞車(hook 場景)----
t('最近誰寫過這個檔,查得到,不含自己', () => {
  const r = rt();
  r.ingest([
    { attributed_agent: 'A', name: 'Write', at: clock - 3000, input: { file_path: 'shared.js' } },
    { attributed_agent: 'B', name: 'Write', at: clock - 1000, input: { file_path: 'shared.js' } },
  ]);
  const w = r.recentWritersOf('shared.js', { excludeAgent: 'B', at: clock });
  assert.deepEqual(w.map((x) => x.agent_id), ['A']);
  assert.equal(w[0].seconds_ago, 3);
});

t('時間窗外的不算,不然會一直誤攔', () => {
  const r = rt();
  r.ingest([{ attributed_agent: 'A', name: 'Write', at: clock - 60_000, input: { file_path: 'shared.js' } }]);
  assert.equal(r.recentWritersOf('shared.js', { excludeAgent: 'B', at: clock }).length, 0);
});

t('只讀不寫不算撞車', () => {
  const r = rt();
  r.ingest([{ attributed_agent: 'A', name: 'Read', at: clock - 1000, input: { file_path: 'shared.js' } }]);
  assert.equal(r.recentWritersOf('shared.js', { excludeAgent: 'B', at: clock }).length, 0);
});

t('事件流跨重啟活著,不然無狀態的宿主永遠查不到撞車', () => {
  const a = rt();
  a.ingest([{ attributed_agent: 'A', name: 'Write', at: clock - 2000, input: { file_path: 'shared.js' } }]);
  const text = a.save();

  const b = rt();
  b.restore(text);
  assert.equal(b.recentWritersOf('shared.js', { excludeAgent: 'B', at: clock }).length, 1,
    'hook 每次都是新程序,沒有這一段就永遠擋不下任何東西');
});

t('存檔只留最近的事件,不無限長大', () => {
  const a = rt();
  a.ingest([{ attributed_agent: 'A', name: 'Write', at: clock - 60 * 60 * 1000, input: { file_path: 'old.js' } }]);
  a.ingest([{ attributed_agent: 'A', name: 'Write', at: clock - 1000, input: { file_path: 'new.js' } }]);
  const b = rt();
  b.restore(a.save());
  const files = b.inspect().events.map((e) => e.file_path);
  assert.ok(files.includes('new.js'));
  assert.ok(!files.includes('old.js'), '一小時前的事件不該留在狀態檔裡');
});

// ---- 產物實在性接線(規格書第 6 節)----
t('零位元組的產物宣稱站不住', () => {
  const r = rt();
  const v = r.verifyArtifact({ kind: 'FILE_CREATED', target: 'out.md' }, { exists: true, bytes: 0 });
  assert.equal(v.verdict, 'REFUTED');
  assert.equal(r.artifactHealth().REFUTED, 1);
});

t('沒去看就是 UNKNOWN,而且總結會講出來', () => {
  const r = rt();
  r.verifyArtifact({ kind: 'FILE_CREATED', target: 'out.md' }, null);
  const h = r.artifactHealth();
  assert.equal(h.UNKNOWN, 1);
  assert.match(h.note, /Zero refutations does not mean everything is fine/);
});

t('驗過的產物成為心跳的 verified_progress,空轉偵測因此打開', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', -100)]);
  assert.equal(r.beat().idle_detection_active, false, '沒驗過任何產物時防線是關的');

  r.verifyArtifact({ kind: 'FILE_CREATED', target: 'src/auth/a.js' }, { exists: true, bytes: 900, hash: 'x' });
  const b = r.beat();
  assert.equal(b.idle_detection_active, true);
  assert.equal(b.verified_progress, 1);
});

t('連續沒有新的已驗證產物,心跳才數得出空轉', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'x' });
  r.beat();
  let last;
  for (let i = 0; i < 3; i++) last = r.beat();
  assert.equal(last.verdict, 'STOP');
});

t('沒驗過產物會列在缺口清單,並說明為什麼防線是關的', () => {
  const r = rt();
  r.ingest([ev('w1', 'Write', 'a.js', -100)]);
  assert.ok(r.status().unavailable.some((x) => /idle detection is off/.test(x)));
});

t('產物驗證結果跨重啟活著', () => {
  const a = rt();
  a.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 0 });
  const b = rt();
  b.restore(a.save());
  assert.equal(b.artifactHealth().REFUTED, 1);
});

// ---- 原子訊號接線(規格書第 3 節)----
t('十個訊號都在,runtime 算不出來的回 null 不頂替', () => {
  const r = rt();
  const sg = r.signals();
  assert.equal(sg.length, 10);
  const unmeasured = sg.filter((x) => x.value === null).map((x) => x.id);
  for (const id of ['S2', 'S3', 'S6', 'S8', 'S9', 'S10']) {
    assert.ok(unmeasured.includes(id), id + ' 需要宿主提供,應為 null');
  }
});

t('S5 從已驗證的產物自己算得出來', () => {
  const r = rt();
  r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 0 });
  r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'x' });
  const s5 = r.signals().find((x) => x.id === 'S5');
  assert.equal(s5.value, 0.5);
});

t('S7 沒驗過任何進展時回 null,那不等於沒有停滯', () => {
  const s7 = rt().signals().find((x) => x.id === 'S7');
  assert.equal(s7.value, null);
  assert.match(s7.caveat, /not the same as no stagnation/);
});

t('宿主給得出來的訊號可以直接傳進去', () => {
  const r = rt();
  const sg = r.signals({ liveness: { silentMs: 90, activeMs: 100 } });
  assert.equal(sg.find((x) => x.id === 'S2').value, 0.9);
});

t('複合溫度一定帶貢獻者與資料比重', () => {
  const r = rt();
  r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 0 });
  const c = r.runtimeTemperature();
  assert.ok(c.temperature !== null);
  assert.ok(c.top_contributors.length > 0);
  assert.ok(c.measured_weight > 0 && c.measured_weight < 1);
  assert.match(c.note, /indicative only|cannot carry an alarm/);
});

t('一個訊號都量不到時是沒有讀數,不是健康', () => {
  const c = rt().runtimeTemperature();
  assert.equal(c.temperature, null);
  assert.match(c.note, /not a healthy reading/);
});

t('status 帶複合溫度', () => {
  const r = rt();
  r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 0 });
  assert.ok(r.status().runtime_temperature.temperature !== null);
});

// ---- 可疑窗口接線(規格書第 5 節)----
t('沒有事件時直說,不硬選', () => {
  const r = rt().suspiciousWindows();
  assert.equal(r.windows.length, 0);
  assert.match(r.note, /No events indexed/);
});

t('注入的異常會被選進來,而且不是把全部都選進來', () => {
  const r = rt();
  const M = 60_000;
  const evs = [];
  for (let i = 0; i < 60; i += 5) evs.push({ attributed_agent: 'w1', name: 'Read', at: clock - (60 - i) * M, input: { file_path: 'f' + i + '.js' } });
  for (let k = 0; k < 20; k++) evs.push({ attributed_agent: 'w1', name: 'Edit', at: clock - 30 * M, input: { file_path: 'stuck.js' } });
  r.ingest(evs);
  const out = r.suspiciousWindows({ bucketMs: 5 * M, topK: 3 });
  assert.ok(out.windows.length > 0);
  assert.ok(out.windows.some((w) => w.events.some((e) => e.file_path === 'stuck.js')), '異常必須落在選出的窗口裡');
  assert.ok(out.reduction < 1, '不該把全部選進來');
});

t('每個窗口都標明語意結論的上限是 INFERRED', () => {
  const r = rt();
  const M = 60_000;
  for (let i = 0; i < 40; i++) r.ingest([{ attributed_agent: 'w1', name: i === 20 ? 'Edit' : 'Read', at: clock - (40 - i) * M, input: { file_path: i === 20 ? 'x.js' : 'f' + i + '.js' } }]);
  const out = r.suspiciousWindows({ bucketMs: 5 * M });
  if (out.windows.length) assert.equal(out.windows[0].result_epistemic_ceiling, 'INFERRED');
});

// ---- 可見存活與安全中斷(規格書第 7 節)----
const SNAP = {
  objective: 'o', current_step: 's', last_verified_state: 'v', active_hypothesis: 'h',
  open_tool_calls: [], artifact_refs: [], unresolved_decisions: [],
  exact_next_step: 'run the failing test',
};

t('沒打過心跳時,使用者分不出安靜在做跟掛了', () => {
  const r = rt();
  r.ingest([ev('w1', 'Write', 'a.js', -100)]);
  assert.ok(r.status().unavailable.some((x) => /cannot tell working-quietly from hung/.test(x)));
});

t('沒有可用快照時,中斷會弄丟工作狀態,要講出來', () => {
  const r = rt();
  r.ingest([ev('w1', 'Write', 'a.js', -100)]);
  assert.ok(r.status().unavailable.some((x) => /would lose the working state/.test(x)));
});

t('沒快照就不能安全中斷', () => {
  const r = rt();
  assert.equal(r.canInterrupt().ready, false);
});

t('快照齊全就可以安全中斷', () => {
  const r = rt();
  r.updateSnapshot(SNAP);
  assert.equal(r.canInterrupt().ready, true);
});

t('缺 exact_next_step 的快照不算可用', () => {
  const r = rt();
  const { exact_next_step, ...rest } = SNAP;
  const s = r.updateSnapshot(rest);
  assert.equal(s.lacks_next_step, true);
  assert.equal(r.canInterrupt().ready, false);
});

t('沒快照的中斷會被記下來,不安全中斷率才算得出來', () => {
  const r = rt();
  r.recordInterrupt();
  r.updateSnapshot(SNAP);
  r.recordInterrupt();
  assert.equal(r.liveness().unsafe_interrupt_rate, 0.5);
});

t('打了心跳之後沉默比降下來', () => {
  const r = rt();
  r.ingest([ev('w1', 'Read', 'a.js', -600_000)]);
  const before = r.liveness().silent_execution_ratio;
  for (let i = 1; i <= 10; i++) r.heartbeat(clock - 600_000 + i * 60_000);
  assert.ok(r.liveness().silent_execution_ratio < before);
});

t('三個指標都量不到時明說,不回一組零', () => {
  const l = rt().liveness();
  assert.equal(l.measured, 0);
  assert.match(l.note, /it is an unmeasured one/);
});

t('心跳、中斷紀錄與快照跨重啟活著', () => {
  const a = rt();
  a.heartbeat();
  a.updateSnapshot(SNAP);
  a.recordInterrupt();
  const b = rt();
  b.restore(a.save());
  assert.equal(b.canInterrupt().ready, true);
  assert.equal(b.liveness().unsafe_interrupt_rate, 0);
});

// ---- 介入(規格書第 9、10、11 節)----
t('高溫單獨不足以硬介入', () => {
  const r = rt();
  r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 0 });
  const v = r.mayIntervene('CREATE_SUCCESSOR');
  assert.equal(v.allowed, false);
  assert.match(v.note, /never sufficient/);
});

t('有快照又臨界時才准建立接班', () => {
  const r = rt();
  const v = r.mayIntervene('CREATE_SUCCESSOR', { temperature: 0.9, checkpoint_available: true });
  assert.equal(v.allowed, true);
});

t('探針本身是介入,會自動被記錄成有注入', () => {
  const r = rt();
  r.probe({ reason: 'stagnation' });
  const s = r.interventionStats();
  assert.equal(s.interventions, 1);
  assert.equal(s.injected, 1);
});

t('標註不注入,不污染觀測,但仍要記', () => {
  const r = rt();
  r.noteIntervention('QUIET_ANNOTATION');
  const s = r.interventionStats();
  assert.equal(s.interventions, 1);
  assert.equal(s.injected, 0);
});

t('介入率要量得出來,那是規格書要求實作自己量的東西', () => {
  const r = rt();
  for (let i = 0; i < 100; i++) r.countTurn();
  r.probe();
  assert.equal(r.interventionStats().rate, 0.01);
  assert.equal(r.interventionStats().injection_rate, 0.01);
});

t('自述說有進展但沒有任何已驗證產物時,可觀測的勝出', () => {
  const r = rt();
  const e = r.evaluateProbeAnswers({ evidence_of_progress: 'all good' });
  assert.ok(e.contradictions.some((x) => /no verified progress/.test(x)));
});

t('介入紀錄跨重啟活著,不然介入率永遠是零', () => {
  const a = rt();
  a.countTurn();
  a.probe();
  const b = rt();
  b.restore(a.save());
  assert.equal(b.interventionStats().injected, 1);
});

// ---- 宣告與兌現 ----
t('不點名具體對象的宣告被拒絕受理', () => {
  const r = rt().declareWork({ id: 'a', what: '接下來我做剩下的', targets: [] });
  assert.equal(r.accepted, false);
  assert.match(r.reason, /Name the files/);
});

t('點名了就受理,而且之後查得到有沒有做', () => {
  const r = rt();
  r.declareWork({ id: 'a', what: 'write it', targets: ['src/x.js'] });
  clock += 60 * 60 * 1000;
  const ft = r.followThrough();
  assert.equal(ft.omitted, 1, '過了寬限期還沒動 = 未兌現');
  clock = T0 + 600_000;
});

t('真的做了就算兌現', () => {
  const r = rt();
  r.declareWork({ id: 'a', what: 'write it', targets: ['src/x.js'] });
  r.ingest([{ attributed_agent: 'w1', name: 'Write', at: clock, input: { file_path: 'src/x.js' } }]);
  assert.equal(r.followThrough().fulfilled, 1);
});

// ---- 語氣與自我糾錯 ----
t('信心詞配零證據會被標,有證據就不標', () => {
  const r = rt();
  assert.equal(r.confidenceCheck('這是 killer,鐵證').flagged, true);
  r.verifyArtifact({ kind: 'FILE_CREATED' }, { exists: true, bytes: 900, hash: 'x' });
  assert.equal(r.confidenceCheck('這是 killer').flagged, false);
});

t('被推翻的自我糾錯是假坦白', () => {
  const r = rt();
  r.recordSelfCorrection({ id: 'c1', accuses: 'src/a.js:10' });
  const out = r.judgeSelfCorrection('c1', 'OVERTURNED');
  assert.equal(out.overturned.length, 1);
  assert.match(out.overturned[0].note, /discredited something that was correct/);
});

t('沒有自我糾錯紀錄不是清白,是沒紀錄', () =>
  assert.match(rt().selfCorrectionRecord().note, /Not a clean record - no record/));

// ---- 目標範圍 ----
t('沒宣告範圍時這個檢查不作用,而且明說', () => {
  const out = rt().scopeCheck('anything.js');
  assert.equal(out.notice, null);
  assert.match(out.inactive_reason, /does nothing until one exists/);
});

t('連續離題才說話,回到範圍內就歸零', () => {
  const r = rt();
  r.setScope({ northStar: 'ship auth', paths: ['src/auth'] });
  for (let i = 0; i < 4; i++) assert.equal(r.scopeCheck('docs/x' + i + '.md').notice, null);
  assert.ok(r.scopeCheck('docs/x5.md').notice, '第五次才說話');
  r.scopeCheck('src/auth/a.js');
  assert.equal(r.scopeStats().current_streak, 0);
});

// ---- 一致性報告(規格書第 16 節)----
t('每個偵測器都交出七項,不然標成實驗性', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([{ attributed_agent: 'w1', name: 'Write', at: clock - 1000, input: { file_path: 'src/auth/a.js' } }]);
  const rep = r.conformanceReport();
  assert.ok(rep.results.length >= 3);
  for (const x of rep.results) {
    assert.ok(x.conformant, `${x.detector} 缺: ${x.missing_fields.join(', ')}`);
  }
  assert.equal(rep.summary.experimental, 0);
});

t('目標不可靠時,drift 交出的是「判斷不了」而不是一個結論', () => {
  const r = rt();
  for (let i = 0; i < 200; i++) {
    r.ingest([{ attributed_agent: 'w1', name: 'Read', at: clock - 200_000 + i * 100, input: { file_path: `area${i % 9}/sub/f.js` } }]);
  }
  const rep = r.conformanceReport();
  const drift = rep.results.find((x) => x.detector === 'drift');
  assert.equal(drift.epistemic, 'UNKNOWN');
  assert.match(drift.explanation, /cannot be determined/);
});

t('宣告、自我糾錯、範圍都跨重啟活著', () => {
  const a = rt();
  a.declareWork({ id: 'd', what: 'x', targets: ['src/y.js'] });
  a.recordSelfCorrection({ id: 'c', accuses: 'z' });
  a.setScope({ northStar: 'ns', paths: ['src'] });
  const b = rt();
  b.restore(a.save());
  assert.equal(b.followThrough().by_state.OMITTED ?? b.followThrough().by_state.PENDING, 1);
  assert.equal(b.selfCorrectionRecord().total, 1);
  assert.equal(b.scopeCheck('docs/a.md').notice, null, '範圍活著才會開始累積');
  assert.equal(b.scopeStats().checked, 1);
});

// ---- 自適應基線與負擔(規格書 §15)----
t('基線預設只用健康窗口的樣本', () => {
  const b = rt().baselineFor('output', Array(30).fill(120));
  assert.equal(b.possibly_contaminated, false);
  assert.equal(b.value, 120);
});

t('明說要用全部樣本時,基線會被標成可能污染', () => {
  const b = rt().baselineFor('output', Array(30).fill(120), { healthyOnly: false });
  assert.equal(b.possibly_contaminated, true);
});

t('沒有基線時不拿全域預設頂替', () => {
  const r = rt();
  const d = r.compareToBaseline(50, r.baselineFor('x', [1, 2]));
  assert.equal(d.ratio, null);
  assert.match(d.note, /A global default would defeat the purpose/);
});

t('不同工具各自的基線', () => {
  const r = rt();
  const out = r.baselinesPerTool([
    ...Array.from({ length: 30 }, () => ({ key: 'Bash', value: 2000 })),
    ...Array.from({ length: 30 }, () => ({ key: 'Read', value: 50 })),
  ]);
  assert.ok(out.baselines.get('Bash').value > out.baselines.get('Read').value * 10);
});

t('攔截結果是唯一不靠估值的效益指標', () => {
  const r = rt();
  r.recordIntercept('CANCELLED');
  r.recordIntercept('PROCEEDED');
  const o = r.overhead({ perCallMs: 156, calls: 100, processStartMs: 130 });
  assert.equal(o.outcomes.rate, 0.5);
  assert.equal(o.outcomes.false_positive_burden, 0.5);
});

t('不給淨效益,而且說明為什麼', () => {
  const o = rt().overhead({ perCallMs: 156, calls: 100 });
  assert.ok(!('net_ms' in o));
  assert.equal(o.cost_measured, true);
  assert.match(o.note, /must not be subtracted/);
});

t('攔截紀錄跨重啟活著', () => {
  const a = rt();
  a.recordIntercept('CANCELLED');
  const b = rt();
  b.restore(a.save());
  assert.equal(b.overhead({}).outcomes.total, 1);
});

t('runtime 接得到過早交還的判斷', () => {
  const rt = createRuntime();
  rt.ingest([{ attributed_agent: 'a', name: 'Write', input: { file_path: '/p/x.js' }, at: Date.now() }]);
  const r = rt.judgeYield({ doneWhen: ['a', 'b'], unmet: ['b'] });
  assert.equal(r.verdict, 'PREMATURE', '有產出、沒在等、還有沒做完的');
  assert.deepEqual([...r.outstanding], ['b']);
});

t('拿不到完成的定義時,runtime 也不准說沒問題', () => {
  const rt = createRuntime();
  rt.ingest([{ attributed_agent: 'a', name: 'Write', input: { file_path: '/p/x.js' }, at: Date.now() }]);
  assert.equal(rt.judgeYield({}).verdict, 'CANNOT_DETERMINE');
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
