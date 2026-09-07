/**
 * Forseti M11：import 解析
 *
 * cost.js 從第一天就等著一張依賴圖,而沒有人產得出來。
 * 它的函式全部寫好、測試全過,但輸入源是斷的,所以它一直算不出任何東西。
 * 這個模組把那條線接上。
 *
 * 它不讀檔案系統。宿主把「檔名 → 原始碼文字」餵進來,
 * 這裡吐出 cost.js 的 buildGraph() 吃得下的 import 紀錄。
 *
 * ── 這裡永遠只給下界,跟 shell.js 同一個理由 ──────────────
 *
 * 靜態解析看不到的東西:
 *
 *   動態 import      await import(`./plugins/${name}.js`)
 *   字串拼接的路徑    require(base + '/index.js')
 *   執行期註冊        loader.register('./x.js')
 *   設定檔驅動        路徑寫在 json 或 yaml 裡
 *
 * cost.js 的 is_lower_bound 從一開始就永遠為真,理由就是這個。
 * 這個模組看到動態 import 時會記一筆 dynamic,不會裝作沒看到,
 * 也不會猜它可能指到哪裡。
 *
 * 零依賴。不用 AST 解析器,因為那會引入依賴,
 * 而正規表示式在這個用途上的代價是明確的:它會漏,而漏會被誠實標出來。
 */

/** 認得的 import 形式。 */
export const KINDS = Object.freeze(['STATIC', 'REQUIRE', 'DYNAMIC', 'EXPORT_FROM']);

/** 預設會找的副檔名,依序試。 */
export const DEFAULT_EXTENSIONS = Object.freeze(['.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.json']);

// import x from '...' / import '...' / import {a} from '...'
const STATIC_RE = /(?:^|\n)\s*import\s+(?:[\w*\s{},$]+\s+from\s+)?['"]([^'"]+)['"]/g;
// export ... from '...'
const EXPORT_FROM_RE = /(?:^|\n)\s*export\s+(?:[\w*\s{},$]+\s+)?from\s+['"]([^'"]+)['"]/g;
// require('...')
const REQUIRE_RE = /\brequire\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
// import('...') 帶字面字串
const DYNAMIC_LITERAL_RE = /\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
// import(任何非字面的東西) —— 看得到有這件事,看不到它指去哪
const DYNAMIC_OPAQUE_RE = /\bimport\s*\(\s*(?!['"])[^)]*\)/g;
// require(非字面)
const REQUIRE_OPAQUE_RE = /\brequire\s*\(\s*(?!['"])[^)]*\)/g;

/** 把註解與字串以外的干擾降到最低。不是完整的剖析,只是少誤判。 */
function stripComments(src) {
  return String(src ?? '')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1 ');
}

/**
 * 從一份原始碼抽出它 import 了哪些 specifier。
 *
 * @returns {{specifiers: Array<{specifier, kind}>, opaque: number}}
 *   opaque 是「看得到有動態載入但看不到目標」的次數。
 */
export function parseImports(source) {
  const src = stripComments(source);
  const out = [];
  const seen = new Set();
  const push = (spec, kind) => {
    const key = kind + '|' + spec;
    if (seen.has(key)) return;
    seen.add(key);
    out.push(Object.freeze({ specifier: spec, kind }));
  };

  for (const m of src.matchAll(STATIC_RE)) push(m[1], 'STATIC');
  for (const m of src.matchAll(EXPORT_FROM_RE)) push(m[1], 'EXPORT_FROM');
  for (const m of src.matchAll(REQUIRE_RE)) push(m[1], 'REQUIRE');
  for (const m of src.matchAll(DYNAMIC_LITERAL_RE)) push(m[1], 'DYNAMIC');

  const opaque = (src.match(DYNAMIC_OPAQUE_RE) ?? []).length
    + (src.match(REQUIRE_OPAQUE_RE) ?? []).length;

  return Object.freeze({ specifiers: Object.freeze(out), opaque });
}

/** 把 a/b/../c 這種路徑收平。 */
function normalize(path) {
  const parts = [];
  for (const seg of String(path).split('/')) {
    if (seg === '' || seg === '.') continue;
    if (seg === '..') { parts.pop(); continue; }
    parts.push(seg);
  }
  return parts.join('/');
}

function dirOf(file) {
  const i = String(file).lastIndexOf('/');
  return i < 0 ? '' : file.slice(0, i);
}

/**
 * 把一個 specifier 解成專案裡的實際檔案。
 *
 * 只解相對路徑。裸名(react、lodash)是外部套件,不在專案圖裡,
 * 回 null 並標成 EXTERNAL —— 那不是「解析失敗」,是「本來就不該解」,
 * 兩者混在一起會讓未解析率看起來很糟而其實沒事。
 *
 * @param {string} fromFile 誰 import 的
 * @param {string} specifier
 * @param {Set<string>} files 專案裡實際存在的檔案
 */
export function resolve(fromFile, specifier, files, { extensions = DEFAULT_EXTENSIONS } = {}) {
  const spec = String(specifier ?? '');
  if (!spec.startsWith('.') && !spec.startsWith('/')) {
    return Object.freeze({ target: null, reason: 'EXTERNAL' });
  }
  const base = spec.startsWith('/') ? normalize(spec) : normalize(dirOf(fromFile) + '/' + spec);

  if (files.has(base)) return Object.freeze({ target: base, reason: 'EXACT' });
  for (const ext of extensions) {
    if (files.has(base + ext)) return Object.freeze({ target: base + ext, reason: 'EXTENSION' });
  }
  for (const ext of extensions) {
    const idx = base + '/index' + ext;
    if (files.has(idx)) return Object.freeze({ target: idx, reason: 'INDEX' });
  }
  return Object.freeze({ target: null, reason: 'NOT_FOUND' });
}

/**
 * 整個專案 → cost.js 的 buildGraph() 吃得下的 import 紀錄。
 *
 * @param {Map<string,string>|object} sources 檔名 → 原始碼
 * @returns {{imports, stats}}
 *   imports 直接餵給 buildGraph()。to 為 null 的那些會進 unresolved,
 *   那是 cost.js 本來就有的欄位,不用另外處理。
 */
/**
 * 不是原始碼的檔案。
 *
 * macOS 在非 HFS+ 的檔案系統(外接碟的 exFAT、網路磁碟)上,
 * 會為每個帶 extended attribute 的檔案寫一個 `._` 開頭的 sidecar。
 * 那些檔案跟原始碼同名同副檔名,掃描時會被當成模組,
 * 然後在依賴圖裡出現一個沒有人依賴的 `._runtime.js`。
 * 這是實測遇到的:repo 搬到外接碟之後,孤立模組檢查突然多出一個。
 */
const NOT_SOURCE = /(^|\/)\._/;

export function buildImportRecords(sources, { extensions = DEFAULT_EXTENSIONS } = {}) {
  const all = sources instanceof Map ? [...sources.entries()] : Object.entries(sources ?? {});
  const entries = all.filter(([f]) => !NOT_SOURCE.test(f));
  const files = new Set(entries.map(([f]) => f));
  const imports = [];
  const stats = {
    files: entries.length,
    total: 0,
    resolved: 0,
    external: 0,
    not_found: 0,
    dynamic_opaque: 0,
  };

  for (const [file, src] of entries) {
    const parsed = parseImports(src);
    stats.dynamic_opaque += parsed.opaque;
    for (const { specifier, kind } of parsed.specifiers) {
      stats.total += 1;
      const r = resolve(file, specifier, files, { extensions });
      if (r.target) stats.resolved += 1;
      else if (r.reason === 'EXTERNAL') stats.external += 1;
      else stats.not_found += 1;
      imports.push(Object.freeze({ from: file, to: r.target, specifier, kind, resolution: r.reason }));
    }
  }

  return Object.freeze({
    imports: Object.freeze(imports),
    stats: Object.freeze({
      ...stats,
      /** 被當成非原始碼濾掉的檔案數。多半是 macOS 的 AppleDouble sidecar。 */
      skipped_non_source: all.length - entries.length,
      /**
       * 解析率的分母刻意排除外部套件:它們本來就不該解。
       * 把它們算進去會讓一個健康的專案看起來解析率很低。
       * 分母為零時回 null,不是 1。
       */
      resolution_rate: (stats.total - stats.external) === 0
        ? null
        : stats.resolved / (stats.total - stats.external),
      /** 永遠為真。動態載入與字串拼接的路徑,靜態解析看不到。 */
      is_lower_bound: true,
    }),
  });
}
