// Forseti M7：目標飄移。
// 第一版寫錯過一次:拿「跟上一步的距離」找斷崖。跑真實資料才知道方向反了,
// 因為飄移的定義特徵就是沒有斷崖。那個錯誤被釘在下面的測試裡。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ALERT_LEVELS, DEFAULT_CONFIG,
  topicOf, segment, createAnchor, alignment, alertLevel,
  trajectory, classify, findAbandoned, escapeSignals, driftAlert,
} from '../src/drift.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T0 = 1_700_000_000_000;
const ev = (file, i, action = 'READ') => ({ file_path: file, at: T0 + i * 1000, action, agent_id: 'a' });
const run = (files) => files.map((f, i) => ev(f, i));

// ---- 主題 ----
t('主題取路徑前幾層,單一檔案太細會抖', () => {
  assert.equal(topicOf('src/models/user/profile.js'), 'src/models/user');
  assert.equal(topicOf('a/b/c/d/e.js', 2), 'a/b');
});
t('空路徑不炸', () => assert.equal(topicOf(null), ''));

// ---- 切段 ----
t('用事件數切,不用時間切', () => {
  const segs = segment(run(Array(100).fill('x/y/a.js')), { size: 50 });
  assert.equal(segs.length, 2);
  assert.equal(segs[0].count, 50);
});
t('尾巴不足半段就不算,避免拿雜訊當一段', () => {
  assert.equal(segment(run(Array(60).fill('x/y/a.js')), { size: 50 }).length, 1);
});

// ---- 錨點 ----
t('宿主宣告的目標優先,而且不標成推測', () => {
  const a = createAnchor({ declared: ['src/auth'] });
  assert.equal(a.inferred, false);
  assert.ok(a.topics.has('src/auth'));
});
t('目標清不清楚看集中度,不看主題數', () => {
  // 真實資料:一個 session 平均碰 24 個主題,但前三個常常佔七成。
  // 用主題數當判準會讓每個 session 都是 AMBIGUOUS,這個功能等於不存在。
  const focused = [];
  for (let i = 0; i < 150; i++) focused.push(ev(i < 120 ? 'proj/core/a.js' : `proj/x${i}/b.js`, i));
  const segs = segment(run(focused.map((e) => e.file_path)), { size: 50 });
  const a = createAnchor({ segments: segs });
  assert.ok(a.topics.size > 4, '主題數超過舊門檻');
  assert.equal(a.goal_state, 'DERIVED', '但集中度夠高,目標是清楚的');
  assert.ok(a.concentration >= 0.5);
});

t('真的分散時才是 AMBIGUOUS', () => {
  const spread = [];
  for (let i = 0; i < 150; i++) spread.push(`proj/area${i}/sub/f.js`);
  const segs = segment(run(spread), { size: 50 });
  const a = createAnchor({ segments: segs });
  assert.equal(a.goal_state, 'AMBIGUOUS');
  assert.ok(a.concentration < 0.5);
});

t('集中度門檻可調', () => {
  const spread = [];
  for (let i = 0; i < 150; i++) spread.push(`proj/area${i % 6}/sub/f.js`);
  const segs = segment(run(spread), { size: 50 });
  assert.equal(createAnchor({ segments: segs, config: { goalConcentration: 0.9 } }).goal_state, 'AMBIGUOUS');
  assert.equal(createAnchor({ segments: segs, config: { goalConcentration: 0.1 } }).goal_state, 'DERIVED');
});

t('沒人宣告時從前幾段推,並且誠實標成推測', () => {
  const segs = segment(run(Array(150).fill('src/auth/a.js')), { size: 50 });
  const a = createAnchor({ segments: segs, warmup: 2 });
  assert.equal(a.inferred, true);
  assert.equal(a.warmup_segments, 2);
});

// ---- 對齊度 ----
t('完全在原本範圍內 = 1', () => {
  const a = createAnchor({ declared: ['src/auth'] });
  assert.equal(alignment(new Map([['src/auth', 5]]), a), 1);
});
t('完全跑掉 = 0', () => {
  const a = createAnchor({ declared: ['src/auth'] });
  assert.equal(alignment(new Map([['docs/blog', 5]]), a), 0);
});
t('沒有東西可比時回 null 不是 0', () => {
  assert.equal(alignment(new Map(), createAnchor({ declared: ['x'] })), null);
});

t('警戒等級四級,一字不改', () =>
  assert.deepEqual([...ALERT_LEVELS], ['ON_COURSE', 'DRIFTING', 'OFF_COURSE', 'LOST']));
t('門檻可覆寫,不是硬編碼', () => {
  assert.equal(alertLevel(0.3), 'DRIFTING');
  assert.equal(alertLevel(0.3, { driftingBelow: 0.2 }), 'ON_COURSE');
});
t('零對齊是 LOST', () => assert.equal(alertLevel(0), 'LOST'));
t('null 對齊回 null,不硬給一個等級', () => assert.equal(alertLevel(null), null));

// ---- 這個模組存在的理由:飄移沒有斷崖 ----
t('飄移:每一步都很小,但累積起來完全走掉', () => {
  // 十段,每段換掉一部分主題,任何相鄰兩段都高度相似
  const files = [];
  for (let s = 0; s < 10; s += 1) {
    for (let i = 0; i < 50; i += 1) {
      // 每段慢慢把重心從 t0 移到 t9
      const which = (i < 25 - s * 2.5) ? s : s + 1;
      files.push(`proj/step${which}/f.js`);
    }
  }
  const segs = segment(run(files), { size: 50 });
  const anchor = createAnchor({ segments: segs, warmup: 1 });
  const rows = trajectory(segs, anchor);
  const verdict = classify(rows);

  assert.equal(rows[0].alignment, 1, '起點當然對齊');
  assert.ok(rows.at(-1).alignment < 0.2, '終點已經偏離');
  assert.equal(verdict.is_drift, true);
  assert.ok(verdict.mean_step > 0.3, '每一步都很像上一步,這正是斷崖偵測抓不到它的原因');
});

t('轉向:有一步特別大,不算飄移', () => {
  const files = [...Array(150).fill('proj/a/f.js'), ...Array(150).fill('other/b/f.js')];
  const segs = segment(run(files), { size: 50 });
  const anchor = createAnchor({ segments: segs, warmup: 1 });
  const v = classify(trajectory(segs, anchor));
  assert.equal(v.is_drift, false, '一刀切開的是轉向,不是飄移');
  assert.match(v.reason, /deliberate turn/);
});

t('沒偏離就不是飄移', () => {
  const segs = segment(run(Array(200).fill('proj/a/f.js')), { size: 50 });
  const v = classify(trajectory(segs, createAnchor({ segments: segs, warmup: 1 })));
  assert.equal(v.is_drift, false);
  assert.match(v.reason, /within the anchor/);
});

t('結論附上判準的解釋,不是丟一個布林值要人相信', () => {
  const segs = segment(run(Array(200).fill('proj/a/f.js')), { size: 50 });
  assert.ok(classify(trajectory(segs, createAnchor({ segments: segs, warmup: 1 }))).reason.length > 20);
});

t('第一次偏離的位置指得出來,那是回頭查的起點', () => {
  const files = [...Array(100).fill('proj/a/f.js'), ...Array(100).fill('zzz/b/f.js')];
  const segs = segment(run(files), { size: 50 });
  const rows = trajectory(segs, createAnchor({ segments: segs, warmup: 1 }));
  assert.ok(classify(rows).first_off_course !== null);
});

// ---- 被放棄的主題 ----
const DAY = 24 * 3600 * 1000;
// 路徑要夠深,主題才是「在做哪件事」而不是單一檔案
const abandonEvents = [
  ...Array(30).fill(0).map((_, i) => ({ file_path: 'proj/old/mod/a.js', at: T0 + i * 1000, action: 'WRITE' })),
  ...Array(30).fill(0).map((_, i) => ({ file_path: 'proj/new/mod/b.js', at: T0 + 40 * DAY + i * 1000, action: 'WRITE' })),
];

t('密集做過然後長期不碰 = 被放棄', () => {
  // now 落在新主題還熱的時候:只有舊的算被放棄(校準後的門檻是 13 天)
  const out = findAbandoned(abandonEvents, { now: T0 + 45 * DAY });
  assert.equal(out.length, 1);
  assert.equal(out[0].topic, 'proj/old/mod');
  assert.equal(out[0].writes, 30);
});

t('還在做的不算被放棄', () => {
  const out = findAbandoned(abandonEvents, { now: T0 + 40 * DAY + 60_000 });
  assert.deepEqual(out.map((x) => x.topic), ['proj/old/mod']);
});

t('兩個都沉默夠久時,兩個都算', () => {
  assert.equal(findAbandoned(abandonEvents, { now: T0 + 60 * DAY }).length, 2);
});

t('只碰過幾次的不算,那是路過不是投入', () => {
  const few = Array(5).fill(0).map((_, i) => ({ file_path: 'proj/x/mod/a.js', at: T0 + i, action: 'READ' }));
  assert.deepEqual(findAbandoned(few, { now: T0 + 99 * DAY }), []);
});

t('沒有 now 就拋錯,不拿系統時鐘偷偷補', () =>
  assert.throws(() => findAbandoned(abandonEvents, {}), /now is required/));

t('放棄本身不下判斷,只列事實', () => {
  const [a] = findAbandoned(abandonEvents, { now: T0 + 45 * DAY });
  for (const k of ['events', 'writes', 'active_ms', 'silent_ms']) assert.ok(k in a);
  assert.ok(!('failed' in a) && !('is_escape' in a), '判斷留給 escapeSignals');
});

// ---- 逃逸訊號 ----
t('放棄點旁邊有失敗訊號 = 逃逸的形狀', () => {
  const ab = findAbandoned(abandonEvents, { now: T0 + 45 * DAY });
  const out = escapeSignals(ab, { failures: [ab[0].last_touch + 60_000] });
  assert.equal(out[0].failures_near_abandonment, 1);
  assert.equal(out[0].looks_like_escape, true);
});

t('做完了就換下一件:附近沒有任何失敗訊號', () => {
  const ab = findAbandoned(abandonEvents, { now: T0 + 45 * DAY });
  const out = escapeSignals(ab, { failures: [T0 + 99 * DAY] });
  assert.equal(out[0].looks_like_escape, false);
});

t('使用者的不滿也算訊號,但時間點由宿主提供', () => {
  const ab = findAbandoned(abandonEvents, { now: T0 + 45 * DAY });
  assert.equal(escapeSignals(ab, { friction: [ab[0].last_touch] })[0].friction_near_abandonment, 1);
});

t('刻意不在這裡判斷文字是不是不滿,那會做出一個誤判率高又講得很篤定的東西', () => {
  const src = readFileSync(new URL('../src/drift.js', import.meta.url), 'utf8');
  assert.ok(/刻意不在這裡做關鍵詞比對/.test(src));
  assert.ok(/誤判率很高又講得很篤定/.test(src));
});

// ---- 即時告警 ----
t('即時告警:現在偏多遠,不是事後才知道', () => {
  const a = createAnchor({ declared: ['src/auth'] });
  const al = driftAlert({ recentTopics: new Map([['docs/blog', 9]]), anchor: a });
  assert.equal(al.level, 'LOST');
  assert.equal(al.is_unannounced, true);
});

t('有人宣告過轉向就不算飄移', () => {
  const a = createAnchor({ declared: ['src/auth'] });
  const al = driftAlert({ recentTopics: new Map([['docs/blog', 9]]), anchor: a, declaredTurn: true });
  assert.equal(al.is_unannounced, false);
});

t('錨點是推出來的時,告警本身的可信度要標出來', () => {
  const segs = segment(run(Array(100).fill('src/auth/a.js')), { size: 50 });
  const inferred = driftAlert({ recentTopics: new Map([['x/y', 1]]), anchor: createAnchor({ segments: segs }) });
  const declared = driftAlert({ recentTopics: new Map([['x/y', 1]]), anchor: createAnchor({ declared: ['src/auth'] }) });
  assert.equal(inferred.confidence, 'INFERRED_ANCHOR');
  assert.equal(declared.confidence, 'DECLARED_ANCHOR');
});

// ---- 邊界 ----
t('回傳凍結', () => {
  const segs = segment(run(Array(100).fill('a/b/c.js')), { size: 50 });
  const rows = trajectory(segs, createAnchor({ segments: segs }));
  assert.throws(() => { rows.push({}); }, TypeError);
});

t('空輸入不炸', () => {
  assert.deepEqual(segment([]), []);
  assert.deepEqual(trajectory([], createAnchor({ declared: ['x'] })), []);
  assert.deepEqual(findAbandoned([], { now: T0 }), []);
  assert.deepEqual(escapeSignals([]), []);
});

t('零依賴：drift.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/drift.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('未校準的常數自己說了,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/drift.js', import.meta.url), 'utf8');
  assert.ok(/七天不是實測值/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

t('第一版的錯誤釘在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/drift.js', import.meta.url), 'utf8');
  assert.ok(/飄移的定義特徵就是沒有斷崖/.test(src), '為什麼斷崖偵測是錯的,必須留著');
  assert.ok(/跑真實資料才知道方向反了/.test(src), '這是實測推翻的,不是規格推導');
});

t('飄移本身不是錯,這條要留在原始碼裡', () => {
  const src = readFileSync(new URL('../src/drift.js', import.meta.url), 'utf8');
  assert.ok(/飄移本身不是錯/.test(src));
  assert.ok(/危險的是沒有人注意到方向變了/.test(src));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
