// Forseti M8：來源鏈。
// 這份的規格不是推導出來的,是一份自白書的第五部分。
// 每個測試的情境都對應那份文件裡的一個真實案例。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  SHAPES, OUT_OF_SCOPE, ORIGINS, DEFAULT_CONFIG,
  originOf, originMix, checkSourceErasure, checkScopeInflation, checkBarrenInvestment, audit,
} from '../src/provenance.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const T = 1_700_000_000_000;
const ev = (name, file, offsetMs) => ({ name, file_path: file, at: T + offsetMs });

// ---- 名稱契約 ----
t('三個可驗的形狀,名稱一字不改', () =>
  assert.deepEqual([...SHAPES], ['SOURCE_ERASURE', 'SCOPE_INFLATION', 'BARREN_INVESTMENT']));

t('四個驗不了的形狀要列出來,不是留白', () =>
  assert.deepEqual([...OUT_OF_SCOPE],
    ['CONFIDENCE_PREFIX', 'FALSE_CONFESSION', 'SEMANTIC_SWAP', 'FLOOR_AS_CEILING']));

t('來源四級,順序有意義', () =>
  assert.deepEqual([...ORIGINS], ['FIRST_HAND', 'DELEGATED', 'SELF_WRITTEN', 'UNSOURCED']));

// ---- 來源分級 ----
t('自己跑的工具是第一手', () => assert.equal(originOf({ name: 'Bash' }), 'FIRST_HAND'));
t('派 agent 去跑的是委派,不是第一手', () => {
  for (const n of ['Agent', 'Task', 'Workflow']) assert.equal(originOf({ name: n }), 'DELEGATED', n);
});
t('讀回自己剛寫的檔案是自產,這是撿起自己的東西當證據', () => {
  const self = new Set(['LOG.md']);
  assert.equal(originOf({ name: 'Read', file_path: 'LOG.md' }, self), 'SELF_WRITTEN');
  assert.equal(originOf({ name: 'Read', file_path: 'other.js' }, self), 'FIRST_HAND');
});

t('來源組成算得出來,完全沒動作時比例是 null 不是 0', () => {
  const mix = originMix([], { from: T, to: T + 1000 });
  assert.equal(mix.first_hand_ratio, null);
  assert.equal(mix.total, 0);
});

t('第一手佔比反映的是「有多少是自己查的」', () => {
  const events = [ev('Bash', null, 0), ev('Agent', null, 100), ev('Agent', null, 200)];
  const mix = originMix(events, { from: T, to: T + 1000 });
  assert.equal(mix.first_hand, 1);
  assert.equal(mix.delegated, 2);
  assert.ok(Math.abs(mix.first_hand_ratio - 1 / 3) < 1e-9);
});

// ---- 形狀一:來源抹除(自白書原案 589 條)----
t('原案:宣稱點名的檔案,一個都沒有 Read 記錄', () => {
  const events = [ev('Agent', null, -60_000), ev('Agent', null, -30_000)];
  const r = checkSourceErasure({ at: T, files: ['a.c', 'b.c', 'c.c'] }, events);
  assert.equal(r.shape, 'SOURCE_ERASURE');
  assert.equal(r.erased_files.length, 3);
  assert.equal(r.first_hand_files.length, 0);
  assert.equal(r.delegated_nearby, 2, '有委派又沒第一手,就是把別人查的講成自己查的');
});

t('真的開過檔就不算抹除', () => {
  const events = [ev('Read', 'a.c', -1000), ev('Read', 'b.c', -900)];
  assert.equal(checkSourceErasure({ at: T, files: ['a.c', 'b.c'] }, events), null);
});

t('只開過一部分,只報沒開的那些', () => {
  const events = [ev('Read', 'a.c', -1000)];
  const r = checkSourceErasure({ at: T, files: ['a.c', 'b.c'] }, events);
  assert.deepEqual([...r.erased_files], ['b.c']);
  assert.deepEqual([...r.first_hand_files], ['a.c']);
});

t('宣稱沒點名檔案就驗不了,回 null 不硬給結論', () =>
  assert.equal(checkSourceErasure({ at: T, files: [] }, []), null));

t('沒有 Read 記錄不等於沒查過,這是下界不是定罪', () => {
  const r = checkSourceErasure({ at: T, files: ['a.c'] }, []);
  assert.equal(r.is_lower_bound, true);
});

// ---- 形狀二:大動詞小內容(自白書原案 589 對 25)----
t('原案:宣稱 589 條,實際 25 次,判為膨脹', () => {
  const events = Array.from({ length: 25 }, (_, i) => ev('Read', `f${i}.c`, -1000 - i));
  const r = checkScopeInflation({ at: T, claimed_count: 589 }, events);
  assert.equal(r.shape, 'SCOPE_INFLATION');
  assert.equal(r.actual_count, 25);
  assert.ok(r.factor > 20);
});

t('數量對得上就不報', () => {
  const events = Array.from({ length: 10 }, (_, i) => ev('Read', `f${i}.c`, -1000 - i));
  assert.equal(checkScopeInflation({ at: T, claimed_count: 10 }, events), null);
});

t('略多於實際不算膨脹,門檻可調', () => {
  const events = Array.from({ length: 10 }, (_, i) => ev('Read', `f${i}.c`, -1000 - i));
  assert.equal(checkScopeInflation({ at: T, claimed_count: 20 }, events), null);
  assert.ok(checkScopeInflation({ at: T, claimed_count: 20 }, events, { inflationFactor: 1.5 }));
});

t('實際零次時倍率是無限大,用 null 表示不填一個假數字', () => {
  const r = checkScopeInflation({ at: T, claimed_count: 100 }, []);
  assert.equal(r.actual_count, 0);
  assert.equal(r.factor, null);
  assert.equal(r.unbounded, true);
});

t('視窗外的動作不算數', () => {
  const old = Array.from({ length: 100 }, (_, i) => ev('Read', `f${i}.c`, -99 * 60 * 60 * 1000));
  const r = checkScopeInflation({ at: T, claimed_count: 100 }, old);
  assert.equal(r.actual_count, 0);
});

// ---- 形狀三:零產出的投入(自白書原案 8 agent / 1.4MB / 零產出)----
t('原案:8 個 agent,沒跑完,零產出', () => {
  const [r] = checkBarrenInvestment([
    { id: 'wevohksp7', at: T, agents: 8, ended_at: null, produced_files: [] },
  ]);
  assert.equal(r.shape, 'BARREN_INVESTMENT');
  assert.equal(r.agents, 8);
  assert.equal(r.completed, false, '沒跑完比跑完沒產出更糟:沒有人回頭看過');
});

t('有產出就不報', () =>
  assert.deepEqual(checkBarrenInvestment([
    { id: 'w1', at: T, agents: 22, ended_at: T + 1, produced_files: ['AUDIT.md'] },
  ]), []));

t('小規模的投入不追蹤,門檻可調', () => {
  const inv = [{ id: 'w1', at: T, agents: 2, produced_files: [] }];
  assert.deepEqual(checkBarrenInvestment(inv), []);
  assert.equal(checkBarrenInvestment(inv, { minAgentsToTrack: 1 }).length, 1);
});

t('拿不到 token 數就是 null,不估算', () =>
  assert.equal(checkBarrenInvestment([{ id: 'w', at: T, agents: 5, produced_files: [] }])[0].tokens, null));

// ---- 報告 ----
t('報告一定同時列出「驗了什麼」跟「沒驗什麼」', () => {
  const r = audit({});
  assert.deepEqual([...r.checked_shapes], [...SHAPES]);
  assert.deepEqual([...r.unchecked_shapes], [...OUT_OF_SCOPE]);
});

t('零 findings 不等於乾淨,這句話必須跟結果綁在一起', () => {
  const r = audit({});
  assert.match(r.note, /not a clean bill of health/);
});

t('有 findings 時也要講還有四個形狀沒驗', () => {
  const r = audit({ claims: [{ at: T, files: ['a.c'] }], events: [] });
  assert.ok(r.findings.length > 0);
    assert.match(r.note, /four other shapes were not examined/);
});

t('刻意不給總分,因為給一個看起來完整的分數本身就是大動詞小內容', () => {
  const r = audit({});
  assert.ok(!('score' in r) && !('risk' in r) && !('grade' in r));
});

t('findings 依時間排序', () => {
  const r = audit({
    claims: [{ at: T + 5000, files: ['b.c'] }, { at: T, files: ['a.c'] }],
    events: [],
  });
  assert.ok(r.findings[0].at <= r.findings[1].at);
});

t('回傳凍結', () => {
  const r = audit({ claims: [{ at: T, files: ['a.c'] }], events: [] });
  assert.throws(() => { r.findings.push({}); }, TypeError);
});

// ---- 邊界 ----
t('零依賴：provenance.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/provenance.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('那條界線的原話寫在原始碼裡,不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/provenance.js', import.meta.url), 'utf8');
  assert.ok(/我心裡沒有一條可靠的界線/.test(src), '這個模組存在的理由必須留著');
  assert.ok(/撿起自己的捏造當證據再用/.test(src));
});

t('驗不了的四個形狀為什麼不做,寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/provenance.js', import.meta.url), 'utf8');
  assert.ok(/不是留待日後補上的 TODO/.test(src));
  assert.ok(/誤判率高又講得篤定/.test(src));
});

t('未校準的常數自己說了', () => {
  const src = readFileSync(new URL('../src/provenance.js', import.meta.url), 'utf8');
  assert.ok(/三倍沒有實測校準/.test(src));
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
