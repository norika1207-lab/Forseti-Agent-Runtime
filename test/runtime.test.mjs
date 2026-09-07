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

t('產出用「寫了幾個檔」當代理值:講話不算做事', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0), ev('w1', 'Write', 'src/auth/b.js', 10)]);
  assert.equal(r.beat().produced, 2);
  // 第二輪沒有新寫入,產出就是 0
  assert.equal(r.beat().produced, 0);
});

t('連續空轉到上限,心跳回 STOP 而不是排下一輪', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Read', 'src/auth/a.js', 0)]);
  let last;
  for (let i = 0; i < 3; i++) last = r.beat();
  assert.equal(last.verdict, 'STOP');
  assert.equal(last.next.stop, true);
  assert.equal(last.next.delay_ms, null);
  assert.ok(last.reasons.some((x) => /not progress/.test(x)));
});

t('有產出就把空轉計數歸零,不會誤停', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Read', 'src/auth/a.js', 0)]);
  r.beat(); r.beat();
  r.ingest([ev('w1', 'Write', 'src/auth/new.js', 100)]);
  const b = r.beat();
  assert.equal(b.barren_streak, 0);
  assert.notEqual(b.verdict, 'STOP');
});

t('零產出的委派會讓心跳叫人', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  r.recordInvestment({ id: 'wf1', agents: 8 });
  r.closeInvestment('wf1', []);
  const b = r.beat();
  assert.equal(b.verdict, 'WAKE');
  assert.ok(b.reasons.some((x) => /produced nothing/.test(x)));
});

t('心跳依結論派工,派出去的走同一條投入路徑', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  r.recordInvestment({ id: 'wf1', agents: 8 });
  r.closeInvestment('wf1', []);
  const b = r.beat({ agents: ['investment-audit'] });
  assert.deepEqual(b.dispatch.dispatch.map((x) => x.agent), ['investment-audit']);
});

t('沒有可派的 agent 時要講,不靜默略過', () => {
  const r = rt();
  r.setGoal(['src/auth']);
  r.ingest([ev('w1', 'Write', 'src/auth/a.js', 0)]);
  r.recordInvestment({ id: 'wf1', agents: 8 });
  r.closeInvestment('wf1', []);
  const b = r.beat({ agents: [] });
  assert.equal(b.dispatch.dispatch.length, 0);
  assert.ok(b.dispatch.unhandled.length > 0);
});

t('空轉計數跨重啟活著,不然連續空轉永遠數不到', () => {
  const a = rt();
  a.setGoal(['src/auth']);
  a.ingest([ev('w1', 'Read', 'src/auth/a.js', 0)]);
  a.beat(); a.beat();
  const text = a.save();

  const b = rt();
  b.restore(text);
  assert.equal(b.beatLog().barren_streak, 2);
  assert.equal(b.beat().verdict, 'STOP', '重啟不該讓計數歸零,那等於永遠停不下來');
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
  assert.equal(r.beat().temperature, null);
  r.recordTemperature({ checked: 100, generated: 900 });
  assert.equal(r.beat().temperature.zone, 'CRITICAL');
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

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
