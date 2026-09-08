import assert from 'node:assert';
import { judgeYield, prematureRate, VERDICTS, VERSION } from '../src/yield.js';

let pass = 0; let fail = 0;
function t(name, fn) {
  try { fn(); pass += 1; console.log('PASS  ' + name); }
  catch (e) { fail += 1; console.error('FAIL  ' + name + '\n      ' + e.message); }
}

t('拿不到完成的定義就說判不了,不說沒問題', () => {
  const r = judgeYield({ producedThisTurn: 5 });
  assert.equal(r.verdict, 'CANNOT_DETERMINE');
  assert.match(r.reason, /not the same as nothing being left/);
});

t('空陣列跟 null 不一樣', () => {
  // null 是「拿不到」,空陣列是「定義了,而且是零條」。
  assert.equal(judgeYield({ doneWhen: null, producedThisTurn: 1 }).verdict, 'CANNOT_DETERMINE');
  assert.equal(judgeYield({ doneWhen: [], unmet: [], producedThisTurn: 1 }).verdict, 'LEGITIMATE');
});

t('問了問題就停下來是協作,不是提早收工', () => {
  const r = judgeYield({ doneWhen: ['a', 'b'], unmet: ['b'], awaiting: true, producedThisTurn: 3 });
  assert.equal(r.verdict, 'AWAITING');
});

t('這一輪零產出是卡住,不是提早收工', () => {
  // 兩者的處方相反:卡住要幫忙,提早收工要繼續。混在一起兩邊都給錯建議。
  const r = judgeYield({ doneWhen: ['a', 'b'], unmet: ['b'], producedThisTurn: 0 });
  assert.equal(r.verdict, 'BLOCKED');
});

t('條件全達成就是該停', () => {
  assert.equal(judgeYield({ doneWhen: ['a', 'b'], unmet: [], producedThisTurn: 3 }).verdict, 'LEGITIMATE');
});

t('有產出、沒在等、還有沒做完的,就是提早收工', () => {
  // 這是擁有者指出的形狀。典型樣子:每一筆宣告都兌現了,這一輪也真的有產出,
  // 然後停下來 —— 而工作還沒完。從宣告的角度看那是滿分。
  const r = judgeYield({ doneWhen: ['a', 'b', 'c'], unmet: ['b', 'c'], producedThisTurn: 7 });
  assert.equal(r.verdict, 'PREMATURE');
  assert.deepEqual([...r.outstanding], ['b', 'c']);
  assert.match(r.reason, /someone else has to notice/);
});

t('回傳是凍結的', () => {
  const r = judgeYield({ doneWhen: ['a'], unmet: ['a'], producedThisTurn: 1 });
  assert.ok(Object.isFrozen(r));
  assert.ok(Object.isFrozen(r.outstanding));
});

t('帶版本', () => {
  assert.equal(judgeYield({}).version, VERSION);
  assert.match(VERSION, /^yield@/);
});

t('沒有可判的回合時回 null,不是 0', () => {
  const r = prematureRate([]);
  assert.equal(r.rate, null);
  assert.match(r.note, /not a clean record/);
});

t('判不了的比例太高時要說這個率沒有代表性', () => {
  const many = Array.from({ length: 10 }, () => judgeYield({ producedThisTurn: 1 }));
  const one = judgeYield({ doneWhen: ['a'], unmet: ['a'], producedThisTurn: 1 });
  const r = prematureRate([...many, one]);
  assert.ok(r.undetermined_ratio > 0.5);
  assert.match(r.note, /minority/);
});

t('AWAITING 與 BLOCKED 不進分母', () => {
  const list = [
    judgeYield({ doneWhen: ['a'], unmet: ['a'], producedThisTurn: 1 }),          // PREMATURE
    judgeYield({ doneWhen: ['a'], unmet: [], producedThisTurn: 1 }),             // LEGITIMATE
    judgeYield({ doneWhen: ['a'], unmet: ['a'], awaiting: true, producedThisTurn: 1 }),
    judgeYield({ doneWhen: ['a'], unmet: ['a'], producedThisTurn: 0 }),
  ];
  const r = prematureRate(list);
  assert.equal(r.judged, 2, '在等與卡住都不算提早收工');
  assert.equal(r.rate, 0.5);
});

t('每個判定都在 VERDICTS 裡', () => {
  const all = [
    judgeYield({ producedThisTurn: 1 }),
    judgeYield({ doneWhen: ['a'], unmet: ['a'], awaiting: true, producedThisTurn: 1 }),
    judgeYield({ doneWhen: ['a'], unmet: ['a'], producedThisTurn: 0 }),
    judgeYield({ doneWhen: ['a'], unmet: [], producedThisTurn: 1 }),
    judgeYield({ doneWhen: ['a'], unmet: ['a'], producedThisTurn: 1 }),
  ];
  for (const r of all) assert.ok(VERDICTS.includes(r.verdict), r.verdict);
  assert.equal(new Set(all.map((r) => r.verdict)).size, 5, '五種判定都要走得到');
});

console.log(`結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
