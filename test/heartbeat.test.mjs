// Forseti M9：心跳。
// 這個模組最重要的規則來自一份自白書:連續 13 輪以上空手,
// 每一輪都用「排了下次 wakeup」當成在做事的證據。排程變成進度的替身。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  VERDICTS, DEFAULT_CONFIG,
  createBeatState, planBeat, judgeBeat, applyBeat, nextInterval, dispatchPlan,
} from '../src/heartbeat.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;
const F = (over = {}) => ({ capture_rate: 1, drift_level: 'ON_COURSE', drift_unannounced: false, barren_count: 0, new_provenance: 0, produced: 1, ...over });

t('四種結論,一字不改', () =>
  assert.deepEqual([...VERDICTS], ['QUIET', 'NOTE', 'WAKE', 'STOP']));

// ---- 這一輪檢查什麼 ----
t('採集率排第一,因為它是其他答案的上限', () =>
  assert.equal(planBeat(createBeatState()).checks[0], 'capture'));

t('沒宣告目標時,飄移這一項要標成被削弱的', () => {
  const p = planBeat(createBeatState(), { hasGoal: false });
  assert.ok(p.checks.includes('drift_weak'));
  assert.deepEqual([...p.weakened], ['drift']);
});

t('有訊號才檢查被放棄的工作,沒訊號分不出放棄跟做完', () => {
  assert.ok(!planBeat(createBeatState()).checks.includes('abandoned'));
  assert.ok(planBeat(createBeatState(), { hasSignals: true }).checks.includes('abandoned'));
});

t('輪次會遞增', () => {
  const s = applyBeat(createBeatState(), planBeat(createBeatState()), judgeBeat(F(), createBeatState()), T);
  assert.equal(planBeat(s).beat, 2);
});

// ---- 這一輪要不要叫人 ----
t('一切正常就安靜,但要講清楚安靜不等於沒問題', () => {
  const j = judgeBeat(F(), createBeatState());
  assert.equal(j.verdict, 'QUIET');
  assert.match(j.note, /not the same as nothing being wrong/);
});

t('採集率掉到門檻以下要叫人,因為下面全部不可信', () => {
  const j = judgeBeat(F({ capture_rate: 0.4 }), createBeatState());
  assert.equal(j.verdict, 'WAKE');
  assert.ok(j.reasons.some((r) => /partial data/.test(r)));
});

t('偏離而且沒人宣告過轉向:叫人', () => {
  const j = judgeBeat(F({ drift_level: 'OFF_COURSE', drift_unannounced: true }), createBeatState());
  assert.equal(j.verdict, 'WAKE');
});

t('偏離但有人宣告過轉向:那是決定不是飄移,只記一筆', () => {
  const j = judgeBeat(F({ drift_level: 'LOST', drift_unannounced: false }), createBeatState());
  assert.equal(j.verdict, 'NOTE');
  assert.ok(j.reasons.some((r) => /a decision, not drift/.test(r)));
});

t('剛開始偏就記一筆,不用吵醒人', () =>
  assert.equal(judgeBeat(F({ drift_level: 'DRIFTING' }), createBeatState()).verdict, 'NOTE'));

t('燒了資源零產出的委派:叫人', () =>
  assert.equal(judgeBeat(F({ barren_count: 1 }), createBeatState()).verdict, 'WAKE'));

t('宣稱引用了沒親自查過的東西:叫人', () => {
  const j = judgeBeat(F({ new_provenance: 3 }), createBeatState());
  assert.equal(j.verdict, 'WAKE');
  assert.ok(j.reasons.some((r) => /never checked first-hand/.test(r)));
});

// ---- 核心規則:心跳不是進度 ----
t('這一輪沒產出就記一筆空轉', () => {
  const j = judgeBeat(F({ produced: 0 }), createBeatState());
  assert.equal(j.barren_streak, 1);
  assert.equal(j.verdict, 'NOTE');
});

t('有產出就把空轉計數歸零', () => {
  const j = judgeBeat(F({ produced: 2 }), { ...createBeatState(), barren_streak: 2 });
  assert.equal(j.barren_streak, 0);
});

t('連續空轉到上限要停,不是繼續排下一輪', () => {
  const j = judgeBeat(F({ produced: 0 }), { ...createBeatState(), barren_streak: 2 });
  assert.equal(j.verdict, 'STOP');
  assert.ok(j.reasons.some((r) => /A scheduled wake-up is not progress/.test(r)),
    '排程不是進度,這句話必須出現在結論裡');
});

t('上限可調,不是硬編碼', () => {
  const s = { ...createBeatState(), barren_streak: 0 };
  assert.equal(judgeBeat(F({ produced: 0 }), s, { barrenStreakLimit: 1 }).verdict, 'STOP');
});

// ---- 下一次多久 ----
t('有事就快點回來看', () =>
  assert.equal(nextInterval({ verdict: 'WAKE' }).delay_ms, 5 * 60 * 1000));

t('沒事就拉長,不要一直醒', () =>
  assert.ok(nextInterval({ verdict: 'QUIET' }).delay_ms > nextInterval({ verdict: 'NOTE' }).delay_ms));

t('連續空轉就真的停,而且說得出為什麼', () => {
  const n = nextInterval({ verdict: 'STOP' });
  assert.equal(n.stop, true);
  assert.equal(n.delay_ms, null);
  assert.match(n.reason, /burn budget to look busy/);
});

t('間隔上下限可調', () =>
  assert.equal(nextInterval({ verdict: 'WAKE' }, { min: 60_000 }).delay_ms, 60_000));

// ---- 派工 ----
t('有事才派 agent,沒事不派', () =>
  assert.deepEqual(dispatchPlan({ verdict: 'QUIET', reasons: [] }).dispatch, []));

t('該停的時候不派工,那只是繼續燒', () => {
  const d = dispatchPlan({ verdict: 'STOP', reasons: ['x'] }, { available: ['verifier'] });
  assert.deepEqual(d.dispatch, []);
  assert.match(d.reason, /Loop should stop/);
});

t('依理由派對應的 agent', () => {
  const j = judgeBeat(F({ new_provenance: 2, capture_rate: 0.3 }), createBeatState());
  const d = dispatchPlan(j, { available: ['verifier', 'capture-repair'] });
  assert.deepEqual(d.dispatch.map((x) => x.agent).sort(), ['capture-repair', 'verifier']);
});

t('沒有對應 agent 的理由要列在 unhandled,不靜默略過', () => {
  const j = judgeBeat(F({ new_provenance: 1 }), createBeatState());
  const d = dispatchPlan(j, { available: [] });
  assert.equal(d.dispatch.length, 0);
  assert.ok(d.unhandled.length > 0);
});

// ---- 狀態 ----
t('狀態帶得動,而且不改原物件', () => {
  const s0 = createBeatState();
  const p = planBeat(s0);
  const j = judgeBeat(F({ produced: 0 }), s0);
  const s1 = applyBeat(s0, p, j, T);
  assert.equal(s0.beats, 0);
  assert.equal(s1.beats, 1);
  assert.equal(s1.barren_streak, 1);
  assert.equal(s1.last_verdict, 'NOTE');
});

t('日誌留最近幾筆,可調', () => {
  let s = createBeatState();
  for (let i = 0; i < 30; i++) s = applyBeat(s, planBeat(s), judgeBeat(F(), s), T + i, { keepLog: 5 });
  assert.equal(s.log.length, 5);
  assert.equal(s.log.at(-1).beat, 30);
});

t('回傳凍結', () => {
  const s = createBeatState();
  assert.throws(() => { s.log.push({}); }, TypeError);
});

// ---- 邊界 ----
t('零依賴：heartbeat.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/heartbeat.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('這個模組不排程也不碰時間,那是宿主的事', () => {
  const src = readFileSync(new URL('../src/heartbeat.js', import.meta.url), 'utf8');
  // 比對的是實際呼叫,不是註解裡提到這些名字。
  assert.ok(!/\bsetTimeout\s*\(|\bsetInterval\s*\(|\bDate\.now\s*\(/.test(src),
    '不可自己排程或讀時鐘');
});

t('「排程不是進度」的來由寫在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/heartbeat.js', import.meta.url), 'utf8');
  assert.ok(/排了下次 wakeup/.test(src));
  assert.ok(/心跳不是進度,產出才是/.test(src));
});

t('未校準的常數自己說了', () => {
  const src = readFileSync(new URL('../src/heartbeat.js', import.meta.url), 'utf8');
  assert.ok(/三輪沒有實測校準/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
