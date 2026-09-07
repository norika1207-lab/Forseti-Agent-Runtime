// Forseti M11：import 解析。
// cost.js 從第一天就等這張圖。它的函式全部寫好、測試全過,
// 但沒有人餵得出輸入,所以它一直算不出任何東西。
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { KINDS, DEFAULT_EXTENSIONS, parseImports, resolve, buildImportRecords } from '../src/imports.js';
import { buildGraph, computeCostVector } from '../src/cost.js';

let pass = 0, fail = 0;
function t(name, fn) {
  try { fn(); console.log('PASS  ' + name); pass++; }
  catch (e) { console.log('FAIL  ' + name + '\n      ' + e.message); fail++; }
}
const specs = (src) => parseImports(src).specifiers.map((x) => x.specifier);

t('四種形式,一字不改', () =>
  assert.deepEqual([...KINDS], ['STATIC', 'REQUIRE', 'DYNAMIC', 'EXPORT_FROM']));

// ---- 抽 specifier ----
t('ESM 各種寫法都抓得到', () => {
  assert.deepEqual(specs("import a from './a.js'"), ['./a.js']);
  assert.deepEqual(specs("import { b } from './b.js'"), ['./b.js']);
  assert.deepEqual(specs("import * as c from './c.js'"), ['./c.js']);
  assert.deepEqual(specs("import './side.js'"), ['./side.js']);
});

t('export from 也是依賴', () =>
  assert.deepEqual(parseImports("export { x } from './x.js'").specifiers[0].kind, 'EXPORT_FROM'));

t('CommonJS 的 require 抓得到', () =>
  assert.deepEqual(specs("const a = require('./a.js')"), ['./a.js']));

t('字面字串的動態 import 抓得到', () => {
  const p = parseImports("await import('./lazy.js')");
  assert.equal(p.specifiers[0].specifier, './lazy.js');
  assert.equal(p.specifiers[0].kind, 'DYNAMIC');
});

t('註解裡的 import 不算', () => {
  assert.deepEqual(specs("// import x from './fake.js'\nimport y from './real.js'"), ['./real.js']);
  assert.deepEqual(specs("/* import x from './fake.js' */\nimport y from './real.js'"), ['./real.js']);
});

t('同一個 specifier 只記一次', () =>
  assert.equal(specs("import a from './a.js'\nimport b from './a.js'").length, 1));

// ---- 這個模組的下界 ----
t('看不到目標的動態載入會被計數,不是假裝沒看到', () => {
  assert.equal(parseImports("await import(`./plugins/${name}.js`)").opaque, 1);
  assert.equal(parseImports("require(base + '/index.js')").opaque, 1);
});

t('看得到有動態載入但猜不到目標時,不編一個出來', () => {
  const p = parseImports("await import(`./x/${n}.js`)");
  assert.equal(p.specifiers.length, 0, '猜不到就不要放進圖裡');
  assert.equal(p.opaque, 1);
});

// ---- 解析 ----
const FILES = new Set(['src/a.js', 'src/b.js', 'src/deep/index.js', 'src/c.ts']);

t('完全相符', () =>
  assert.equal(resolve('src/x.js', './a.js', FILES).target, 'src/a.js'));

t('補副檔名', () => {
  const r = resolve('src/x.js', './a', FILES);
  assert.equal(r.target, 'src/a.js');
  assert.equal(r.reason, 'EXTENSION');
});

t('目錄補 index', () => {
  const r = resolve('src/x.js', './deep', FILES);
  assert.equal(r.target, 'src/deep/index.js');
  assert.equal(r.reason, 'INDEX');
});

t('上層路徑收得平', () =>
  assert.equal(resolve('src/deep/x.js', '../a.js', FILES).target, 'src/a.js'));

t('絕對路徑當 key 時也解得開', () => {
  // 原本 normalize 會吃掉開頭的斜線,於是絕對路徑一律解析失敗,
  // 圖是空的,孤立模組檢查回報全部孤立。25 個模組報了 24 個。
  const ABS = new Set(['/Volumes/X/src/a.js', '/Volumes/X/src/b.js']);
  const r = resolve('/Volumes/X/src/a.js', './b.js', ABS);
  assert.equal(r.target, '/Volumes/X/src/b.js');
});

t('絕對路徑的整包解析也對得起來', () => {
  const proj = {
    '/p/src/app.js': "import { a } from './auth.js'",
    '/p/src/auth.js': "import { u } from './util.js'",
    '/p/src/util.js': '',
  };
  const { imports, stats } = buildImportRecords(proj);
  assert.equal(stats.resolution_rate, 1);
  const g = buildGraph(imports);
  assert.equal(g.reverse.get('/p/src/util.js').size, 1);
});

t('路徑往上跳一層也不會吃掉根斜線', () => {
  const ABS = new Set(['/p/src/a.js', '/p/lib/b.js']);
  assert.equal(resolve('/p/src/a.js', '../lib/b.js', ABS).target, '/p/lib/b.js');
});

t('外部套件不是解析失敗,是本來就不該解', () => {
  const r = resolve('src/x.js', 'react', FILES);
  assert.equal(r.target, null);
  assert.equal(r.reason, 'EXTERNAL');
});

t('相對路徑指到不存在的檔案才是真的找不到', () =>
  assert.equal(resolve('src/x.js', './nope.js', FILES).reason, 'NOT_FOUND'));

t('副檔名清單可調', () =>
  assert.equal(resolve('src/x.js', './c', FILES, { extensions: ['.ts'] }).target, 'src/c.ts'));

// ---- 整包 ----
const PROJ = {
  'src/app.js': "import { auth } from './auth.js'\nimport db from './db/index.js'\nimport react from 'react'",
  'src/auth.js': "import { hash } from './util.js'",
  'src/util.js': '',
  'src/db/index.js': "import { conn } from '../util.js'",
};

t('整包解出來的紀錄,cost.js 的 buildGraph 直接吃得下', () => {
  const { imports } = buildImportRecords(PROJ);
  const g = buildGraph(imports);
  assert.ok(g.reverse.has('src/util.js'), 'util 被兩個檔案依賴');
  assert.equal(g.reverse.get('src/util.js').size, 2);
});

t('接起來之後 cost.js 終於算得出東西', () => {
  const { imports } = buildImportRecords(PROJ);
  const v = computeCostVector(buildGraph(imports), 'src/util.js');
  assert.equal(v.d1_count, 2, 'auth 與 db/index 直接依賴 util');
  assert.ok(v.d2_count >= 1, 'app 透過它們間接依賴');
  assert.equal(v.is_lower_bound, true);
});

t('解析率的分母排除外部套件,不然健康的專案看起來很糟', () => {
  const { stats } = buildImportRecords(PROJ);
  assert.equal(stats.external, 1, 'react');
  assert.equal(stats.resolution_rate, 1, '四個內部 import 全部解得開');
});

t('沒有可解的 import 時,解析率是 null 不是 1', () => {
  const { stats } = buildImportRecords({ 'a.js': "import x from 'react'" });
  assert.equal(stats.resolution_rate, null);
});

t('動態載入的次數會出現在統計裡', () => {
  const { stats } = buildImportRecords({ 'a.js': "await import(`./p/${n}.js`)" });
  assert.equal(stats.dynamic_opaque, 1);
});

t('永遠是下界,這個旗標不可關閉', () =>
  assert.equal(buildImportRecords(PROJ).stats.is_lower_bound, true));

t('Map 跟物件都吃', () => {
  const m = new Map(Object.entries(PROJ));
  assert.equal(buildImportRecords(m).stats.files, buildImportRecords(PROJ).stats.files);
});

t('空專案不炸', () => {
  const r = buildImportRecords({});
  assert.equal(r.imports.length, 0);
  assert.equal(r.stats.resolution_rate, null);
});

t('回傳凍結', () => {
  const r = buildImportRecords(PROJ);
  assert.throws(() => { r.imports.push({}); }, TypeError);
});

t('macOS 的 AppleDouble sidecar 不是原始碼', () => {
  // 外接碟的 exFAT 上,每個帶 xattr 的檔案旁邊會多一個 ._ 檔,
  // 同名同副檔名,掃描時會變成一個沒有人依賴的假模組。實測遇過。
  const r = buildImportRecords({
    'src/a.js': "import x from './b.js'",
    'src/b.js': '',
    'src/._a.js': 'binary garbage',
    'src/._b.js': 'binary garbage',
  });
  assert.equal(r.stats.files, 2);
  assert.equal(r.stats.skipped_non_source, 2);
  const g = buildGraph(r.imports);
  assert.ok(!g.reverse.has('src/._b.js'));
});

t('為什麼要濾掉,理由寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/imports.js', import.meta.url), 'utf8');
  assert.ok(/孤立模組檢查突然多出一個/.test(src));
});

// ---- 邊界 ----
t('零依賴：imports.js 沒有任何 import', () => {
  const src = readFileSync(new URL('../src/imports.js', import.meta.url), 'utf8');
  assert.deepEqual(src.match(/^\s*import\s.+$/gm) ?? [], []);
});

t('為什麼不用 AST 解析器,寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/imports.js', import.meta.url), 'utf8');
  assert.ok(/那會引入依賴/.test(src));
  assert.ok(/它會漏,而漏會被誠實標出來/.test(src));
});

t('cost.js 一直等這張圖這件事,寫在原始碼裡', () => {
  const src = readFileSync(new URL('../src/imports.js', import.meta.url), 'utf8');
  assert.ok(/輸入源是斷的/.test(src));
});

console.log(`\n結果：${pass} 通過，${fail} 失敗，共 ${pass + fail} 條`);
process.exit(fail ? 1 : 0);
