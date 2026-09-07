// Forseti M10：context 溫度計。
// 事後從 transcript 量過一次,量不出來:transcript 是全量記錄,
// context window 是壓縮後的子集。那次失敗釘在下面的測試裡。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  ZONES, DEFAULT_CONFIG, reading, zoneOf, compactionDelta, curve, advice,
} from '../src/thermometer.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}

t('四個溫度區,一字不改', () =>
  assert.deepEqual([...ZONES], ['COLD', 'WARM', 'HOT', 'CRITICAL']));

// ---- 讀數 ----
t('事實比例算得出來', () => {
  const r = reading({ checked: 700, generated: 300 });
  assert.equal(r.fact_ratio, 0.7);
});

t('委派回來的既不算自己查的也不算自己編的,單獨一欄', () => {
  const r = reading({ checked: 500, generated: 300, delegated: 200 });
  assert.equal(r.fact_ratio, 0.5, '把委派算進 checked 就是來源抹除');
  assert.equal(r.delegated, 200);
});

t('沒有資料時比例是 null 不是 0', () =>
  assert.equal(reading({}).fact_ratio, null));

t('拿不到 context 上限就不算填充率,不估', () => {
  assert.equal(reading({ checked: 10, generated: 10 }).fill_ratio, null);
  assert.equal(reading({ checked: 10, generated: 10, window_total: 100 }).fill_ratio, 0.2);
});

t('估出來的數字要標明,不可跟 provider 回報的混用', () => {
  assert.equal(reading({ checked: 1, source: 'ESTIMATED' }).is_estimate, true);
  assert.equal(reading({ checked: 1, source: 'PROVIDER_REPORTED' }).is_estimate, false);
});

// ---- 溫度區 ----
t('事實多就是冷的,事實少就是燙的', () => {
  assert.equal(zoneOf(reading({ checked: 90, generated: 10 })), 'COLD');
  assert.equal(zoneOf(reading({ checked: 50, generated: 50 })), 'WARM');
  assert.equal(zoneOf(reading({ checked: 30, generated: 70 })), 'HOT');
  assert.equal(zoneOf(reading({ checked: 10, generated: 90 })), 'CRITICAL');
});

t('沒資料時不硬給一區', () => assert.equal(zoneOf(reading({})), null));

t('門檻可調,而且原始碼說了它們沒校準過', () => {
  assert.equal(zoneOf(reading({ checked: 50, generated: 50 }), { warmBelow: 0.4 }), 'COLD');
  const src = readFileSync(new URL('../src/thermometer.js', import.meta.url), 'utf8');
  assert.ok(/三條線都沒有實測校準/.test(src));
});

// ---- 壓縮:這個模組真正的價值 ----
t('壓縮之後事實比例掉下來,代表丟掉的多半是工具輸出', () => {
  const before = reading({ checked: 800, generated: 200 });
  const after = reading({ checked: 200, generated: 200 });
  const d = compactionDelta(before, after);
  assert.equal(d.fact_ratio_before, 0.8);
  assert.equal(d.fact_ratio_after, 0.5);
  assert.ok(d.fact_ratio_drop > 0.2);
  assert.equal(d.alarming, true);
  assert.match(d.note, /leans on the model/);
});

t('丟掉的東西裡有多少是查過的,算得出來', () => {
  const d = compactionDelta(reading({ checked: 800, generated: 200 }), reading({ checked: 200, generated: 200 }));
  assert.equal(d.lost_checked, 600);
  assert.equal(d.lost_generated, 0);
  assert.equal(d.lost_was_checked, 1, '丟掉的全部是查過的東西');
});

t('壓縮沒有明顯改變組成就不告警', () => {
  const d = compactionDelta(reading({ checked: 800, generated: 200 }), reading({ checked: 400, generated: 100 }));
  assert.equal(d.alarming, false);
});

t('沒東西可比時直說,不給一個假的差值', () => {
  const d = compactionDelta(reading({}), reading({ checked: 1 }));
  assert.equal(d.fact_ratio_drop, null);
  assert.match(d.note, /Cannot compare/);
});

// ---- 趨勢 ----
t('事實佔比一路往下,溫度就是在升', () => {
  const c = curve([
    reading({ checked: 90, generated: 10 }),
    reading({ checked: 70, generated: 30 }),
    reading({ checked: 40, generated: 60 }),
    reading({ checked: 20, generated: 80 }),
  ]);
  assert.equal(c.trend, 'RISING');
  assert.match(c.note, /thinner ground/);
});

t('穩定就是穩定,不硬說有趨勢', () => {
  const c = curve([
    reading({ checked: 70, generated: 30 }),
    reading({ checked: 72, generated: 28 }),
    reading({ checked: 68, generated: 32 }),
  ]);
  assert.equal(c.trend, 'FLAT');
});

t('只有一筆讀數看不出趨勢,要直說', () => {
  const c = curve([reading({ checked: 1, generated: 1 })]);
  assert.equal(c.trend, null);
  assert.match(c.note, /at least two readings/);
});

t('沒資料的讀數不進曲線', () => {
  const c = curve([reading({}), reading({ checked: 1, generated: 1 })]);
  assert.equal(c.points.length, 1);
});

// ---- 建議 ----
t('燙的時候該做的是把證據落檔,不是清空 context', () => {
  const a = advice(reading({ checked: 10, generated: 90 }));
  assert.equal(a.action, 'PIN_EVIDENCE');
  assert.match(a.why, /re-read instead of remembered/);
});

t('冷的時候不用做什麼', () =>
  assert.equal(advice(reading({ checked: 90, generated: 10 })).action, 'NONE'));

t('溫的時候看著就好', () =>
  assert.equal(advice(reading({ checked: 50, generated: 50 })).action, 'WATCH'));

t('沒資料時不給建議', () =>
  assert.equal(advice(reading({})).action, 'NONE'));

// ---- 邊界 ----
t('回傳凍結', () => {
  const r = reading({ checked: 1 });
  assert.throws(() => { r.checked = 2; }, TypeError);
});

t('零依賴：thermometer.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/thermometer.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('事後量不出來這件事寫在原始碼裡,那是這個模組只能在 runtime 用的理由', () => {
  const src = readFileSync(new URL('../src/thermometer.js', import.meta.url), 'utf8');
  assert.ok(/transcript 是全量記錄/.test(src));
  assert.ok(/那不是限制,是它存在的理由/.test(src));
});

t('那條界線的原話寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/thermometer.js', import.meta.url), 'utf8');
  assert.ok(/我心裡沒有一條可靠的界線/.test(src));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
