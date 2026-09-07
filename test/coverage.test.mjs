// Forseti M5：Session 覆蓋範圍。驗收對照文件第 7 節。
// 規格裡的禁令一律寫成會紅的測試，不只寫在註解裡。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  COVERAGE_DEPTHS, DEFAULT_CONFIG, COMPACT_RISK_UNKNOWN,
  createCoverage, recordAccess, coverageFromEvents, defaultToolDepth,
  knownFiles, intersect, overlapRatio, duplicateWork,
  handoffDelta, pickHottest, newCoverageCost,
} from '../src/coverage.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const cov = (id, files, extra = {}) =>
  createCoverage({ session_id: id, agent_id: 'a-' + id, files, ...extra });

// ---- 資料模型 ----
t('SessionCoverage 欄位照 7.3 節，恰好 6 個，含不可關閉的 is_upper_bound', () => {
  const c = cov('s1', { 'a.ts': 'READ_FULL' });
  assert.deepEqual(Object.keys(c).sort(),
    ['agent_id', 'compact_risk', 'files', 'is_upper_bound', 'session_id', 'updated_at']);
  assert.equal(c.is_upper_bound, true);
});

t('CoverageDepth 四級照 7.3 節，一字不改', () => {
  assert.deepEqual([...COVERAGE_DEPTHS], ['MENTIONED', 'READ_PARTIAL', 'READ_FULL', 'EDITED']);
});

t('不認得的深度直接拋錯，不靜默接受', () => {
  assert.throws(() => cov('s1', { 'a.ts': 'SKIMMED' }), /Unrecognised CoverageDepth/);
});

t('雷一：is_upper_bound 永遠 true，且物件凍結改不動', () => {
  const c = cov('s1', { 'a.ts': 'EDITED' });
  assert.throws(() => { c.is_upper_bound = false; }, TypeError);
  assert.throws(() => { c.files['b.ts'] = 'EDITED'; }, TypeError);
});

// ---- 誠實條款：compact_risk ----
t('7.5 三：compact_risk 預設 null，拿不到就不估', () => {
  assert.equal(cov('s1', {}).compact_risk, COMPACT_RISK_UNKNOWN);
  assert.equal(COMPACT_RISK_UNKNOWN, null);
});

t('compact_risk 給 0..1 以外的值拋錯，不接受瞎猜的數字', () => {
  assert.throws(() => cov('s1', {}, { compact_risk: 1.5 }), /0\.\.1 or null/);
  assert.throws(() => cov('s1', {}, { compact_risk: 'high' }), /0\.\.1 or null/);
  assert.equal(cov('s1', {}, { compact_risk: 0.8 }).compact_risk, 0.8);
});

t('不自己編時間：沒給 updated_at 就是 null', () => {
  assert.equal(cov('s1', {}).updated_at, null);
});

// ---- 深度累積 ----
t('同一檔案多次存取取最強深度，不會被弱事件蓋掉', () => {
  let c = cov('s1', {});
  c = recordAccess(c, 'a.ts', 'EDITED');
  c = recordAccess(c, 'a.ts', 'MENTIONED');
  assert.equal(c.files['a.ts'], 'EDITED');
});

t('recordAccess 不改動原物件，回傳新的凍結物件', () => {
  const c0 = cov('s1', { 'a.ts': 'MENTIONED' });
  const c1 = recordAccess(c0, 'b.ts', 'EDITED');
  assert.equal(Object.keys(c0.files).length, 1);
  assert.equal(Object.keys(c1.files).length, 2);
});

// ---- 事件流（7.5 一 / 7.7 雷二）----
t('從事件流建 coverage：Read 全讀、帶 offset 是部分讀、Edit 是 EDITED', () => {
  const c = coverageFromEvents({
    session_id: 's1', agent_id: 'a1',
    events: [
      { type: 'tool_use', name: 'Read', input: { file_path: 'full.ts' } },
      { type: 'tool_use', name: 'Read', input: { file_path: 'part.ts', offset: 10, limit: 5 } },
      { type: 'tool_use', name: 'Edit', input: { file_path: 'edit.ts' } },
      { type: 'tool_use', name: 'Grep', input: { file_path: 'seen.ts' } },
    ],
  });
  assert.equal(c.files['full.ts'], 'READ_FULL');
  assert.equal(c.files['part.ts'], 'READ_PARTIAL');
  assert.equal(c.files['edit.ts'], 'EDITED');
  assert.equal(c.files['seen.ts'], 'MENTIONED');
});

t('雷二：認不得的事件與沒有檔案路徑的事件一律跳過，不猜', () => {
  const c = coverageFromEvents({
    session_id: 's1', agent_id: 'a1',
    events: [
      { type: 'tool_use', name: 'Bash', input: { command: 'ls' } },   // 無 file_path
      { type: 'thinking' },
      null,
      'garbage',
    ],
  });
  assert.equal(Object.keys(c.files).length, 0);
});

t('toolDepth 可覆寫，因為不同 provider 工具名不同', () => {
  const c = coverageFromEvents({
    session_id: 's1', agent_id: 'a1',
    events: [{ name: 'my_custom_writer', input: { path: 'x.ts' } }],
    toolDepth: (ev) => (ev.name === 'my_custom_writer' ? { file_path: ev.input.path, depth: 'EDITED' } : null),
  });
  assert.equal(c.files['x.ts'], 'EDITED');
});

// ---- 驗收 7.6 一 ----
t('7.6 一：列出知道哪些檔案與深度，由強到弱', () => {
  const c = cov('s1', { 'a.ts': 'MENTIONED', 'b.ts': 'EDITED', 'c.ts': 'READ_FULL' });
  assert.deepEqual(knownFiles(c).map((x) => x.file_path), ['b.ts', 'c.ts', 'a.ts']);
});

t('knownFiles 可用 minDepth 過濾掉只是被提到的檔案', () => {
  const c = cov('s1', { 'a.ts': 'MENTIONED', 'b.ts': 'READ_FULL' });
  assert.deepEqual(knownFiles(c, { minDepth: 'READ_PARTIAL' }).map((x) => x.file_path), ['b.ts']);
});

// ---- 驗收 7.6 二 ----
t('7.6 二：重疊率可查詢，分母取較小集合', () => {
  const a = cov('A', { 'x.ts': 'READ_FULL', 'y.ts': 'READ_FULL', 'z.ts': 'READ_FULL' });
  const b = cov('B', { 'x.ts': 'READ_FULL', 'y.ts': 'READ_FULL' });
  assert.deepEqual(intersect(a, b), ['x.ts', 'y.ts']);
  assert.equal(overlapRatio(a, b), 1);          // b 完全被 a 包住 = 最嚴重的重複付費
});

t('任一邊為空時重疊率是 null 不是 0：沒資料不等於沒重疊', () => {
  assert.equal(overlapRatio(cov('A', {}), cov('B', { 'x.ts': 'READ_FULL' })), null);
  const d = duplicateWork(cov('A', {}), cov('B', { 'x.ts': 'READ_FULL' }));
  assert.equal(d.duplicated, null);
  assert.equal(d.ratio, null);
});

t('去重偵測：超過門檻才警示，門檻可設定', () => {
  const a = cov('A', { 'x.ts': 'READ_FULL', 'y.ts': 'READ_FULL' });
  const b = cov('B', { 'x.ts': 'READ_FULL', 'q.ts': 'READ_FULL' });
  assert.equal(duplicateWork(a, b).duplicated, false);                                  // 0.5 < 0.6
  assert.equal(duplicateWork(a, b, { duplicateThreshold: 0.4 }).duplicated, true);
});

// ---- 驗收 7.6 三：交接差集 ----
t('7.6 三：交接差集 = A 減 B，且回報省下多少（可量測）', () => {
  const from = cov('A', { 'x.ts': 'EDITED', 'y.ts': 'READ_FULL', 'z.ts': 'READ_FULL', 'w.ts': 'MENTIONED' });
  const to = cov('B', { 'y.ts': 'READ_FULL', 'z.ts': 'READ_FULL' });
  const d = handoffDelta(from, to);
  assert.deepEqual(d.need_briefing.map((x) => x.file_path), ['x.ts', 'w.ts']);
  assert.deepEqual([...d.saved_files], ['y.ts', 'z.ts']);
  assert.equal(d.total_from, 4);
  assert.equal(d.saved_ratio, 0.5);
});

t('只被提到過不算已知：接收方 MENTIONED 仍需轉述', () => {
  const from = cov('A', { 'x.ts': 'EDITED' });
  const to = cov('B', { 'x.ts': 'MENTIONED' });
  assert.deepEqual(handoffDelta(from, to).need_briefing.map((x) => x.file_path), ['x.ts']);
  // 門檻放寬到 MENTIONED 才算已知
  assert.deepEqual(handoffDelta(from, to, { knownDepth: 'MENTIONED' }).need_briefing, []);
});

t('from 為空時 saved_ratio 是 null 不是 0', () => {
  assert.equal(handoffDelta(cov('A', {}), cov('B', { 'x.ts': 'EDITED' })).saved_ratio, null);
});

t('交接差集結果也標 is_upper_bound', () => {
  assert.equal(handoffDelta(cov('A', { 'x.ts': 'EDITED' }), cov('B', {})).is_upper_bound, true);
});

// ---- 派工挑人 ----
t('派工挑人：挑覆蓋最多任務檔案的那一個', () => {
  const task = ['a.ts', 'b.ts', 'c.ts'];
  const c1 = cov('S1', { 'a.ts': 'READ_FULL' });
  const c2 = cov('S2', { 'a.ts': 'READ_FULL', 'b.ts': 'EDITED' });
  const best = pickHottest(task, [c1, c2]);
  assert.equal(best.session_id, 'S2');
  assert.equal(best.hot_count, 2);
  assert.equal(Number(best.hot_ratio.toFixed(4)), 0.6667);
});

t('沒有任何候選碰過任務檔案時回 null，不硬挑一個', () => {
  assert.equal(pickHottest(['a.ts'], [cov('S1', { 'zzz.ts': 'EDITED' })]), null);
});

t('minHotRatio 可設定：熱度不夠一律不推薦', () => {
  const task = ['a.ts', 'b.ts', 'c.ts', 'd.ts'];
  const c1 = cov('S1', { 'a.ts': 'READ_FULL' });                       // 0.25
  assert.equal(pickHottest(task, [c1], { minHotRatio: 0.5 }), null);
  assert.equal(pickHottest(task, [c1], { minHotRatio: 0.2 }).session_id, 'S1');
});

t('任務檔案為空或無候選時回 null', () => {
  assert.equal(pickHottest([], [cov('S1', { 'a.ts': 'EDITED' })]), null);
  assert.equal(pickHottest(['a.ts'], []), null);
});

// ---- 保命：新增覆蓋成本 ----
t('保命：只算主 session 還不知道的檔案，已知的不重複計費', () => {
  const main = cov('MAIN', { 'a.ts': 'READ_FULL' });
  const r = newCoverageCost(main, ['a.ts', 'b.ts', 'c.ts']);
  assert.deepEqual([...r.new_files], ['b.ts', 'c.ts']);
  assert.equal(r.new_count, 2);
  assert.equal(r.already_known, 1);
});

t('不越界：本模組不換算 token，那是 M1 的職責', () => {
  const r = newCoverageCost(cov('MAIN', {}), ['a.ts']);
  assert.equal('token' in r, false);
  assert.equal('tokens' in r, false);
  assert.equal('cost' in r, false);
});

// ---- 邊界紀律 ----
t('零依賴：coverage.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/coverage.js', import.meta.url), 'utf8');
  const imports = src.match(/^\s*import\s.+$/gm) ?? [];
  assert.deepEqual(imports, [], '應為零 import，實際: ' + JSON.stringify(imports));
});

t('雷一的標註寫在原始碼裡，不可被靜默刪除', () => {
  const src = readFileSync(new URL('../src/coverage.js', import.meta.url), 'utf8');
  assert.ok(src.includes('上界'), 'coverage 是上界這件事必須寫在原始碼裡');
  assert.ok(/不可關閉/.test(src), 'is_upper_bound 不可關閉這條必須寫明');
});

t('DEFAULT_CONFIG 是預設不是硬編碼：同一份資料換門檻結論就換', () => {
  assert.ok(Object.isFrozen(DEFAULT_CONFIG));
  // b 完全被 a 包住，重疊率 = 1.0
  const a = cov('A', { 'x.ts': 'READ_FULL', 'y.ts': 'READ_FULL' });
  const b = cov('B', { 'x.ts': 'READ_FULL' });
  assert.equal(overlapRatio(a, b), 1);
  assert.equal(duplicateWork(a, b).duplicated, true);                              // 1.0 > 0.6
  assert.equal(duplicateWork(a, b, { duplicateThreshold: 1 }).duplicated, false);  // 1.0 不 > 1
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
