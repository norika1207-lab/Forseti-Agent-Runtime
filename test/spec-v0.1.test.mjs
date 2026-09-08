/**
 * 對照源頭規格書逐條驗。
 *
 * `docs/spec-v0.1.md` 有 38 條 MUST / MUST NOT / REQUIRED。規格書自己寫了
 * 「A component that cannot satisfy a MUST is non-conformant」,所以符不符合
 * 不是我說了算,是這 38 條說了算。
 *
 * 這份跟 acceptance.test.mjs 的差別:那份測的是我自己定的十條驗收,
 * 這份測的是別人寫的規格。用自己的尺量自己,量出來永遠會及格。
 *
 * 四種判定,每一種都要附證據:
 *
 *   CONFORMS          有斷言,而且過了
 *   VIOLATES          有斷言,沒過
 *   NOT_IMPLEMENTED   這條要求的東西根本沒做。不是「還沒測」,是「沒有」。
 *   NOT_CHECKABLE     綱領句,機械檢查不了。要附為什麼。
 *
 * 最後一種最容易變成藏東西的地方,所以它必須少,而且「不好測」不算理由。
 */
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const src = (f) => readFileSync(join(HERE, '..', 'src', f), 'utf8');
/** 只看執行碼,把註解剝掉 —— 註解裡提到某個詞不代表程式會做那件事。 */
const code = (f) => src(f).replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

const results = [];
function spec(n, title, kind, fn) {
  if (kind === 'CHECK') {
    try { results.push({ n, title, verdict: 'CONFORMS', ev: fn() }); }
    catch (e) { results.push({ n, title, verdict: 'VIOLATES', ev: e.message }); }
  } else {
    results.push({ n, title, verdict: kind, ev: fn() });
  }
}

const { verifyClaim } = await import('../src/artifact.js');
const { composite } = await import('../src/signals.js');
const { detectorResult, statableAsFact, cannotDetermine, REQUIRED_FIELDS } = await import('../src/conformance.js');
const { classify, createAnchor, driftAlert } = await import('../src/drift.js');
const { createBeatState, planBeat, judgeBeat, nextInterval } = await import('../src/heartbeat.js');
const { canIntervene, recordIntervention, interventionRate, ACTIONS, PLANES } = await import('../src/intervention.js');
const { createSnapshot, interruptReadiness, unsafeInterruptRate, livenessReport } = await import('../src/rescue.js');
const { ORIGINS } = await import('../src/provenance.js');
const { interceptOutcomes } = await import('../src/overhead.js');
const { createRuntime } = await import('../src/runtime.js');

// ── §0 綱領 ─────────────────────────────────────────────────

spec(1, '每個偵測器都要能實作而不用猜語意', 'CHECK', () => {
  const r = detectorResult({});
  assert.equal(r.conformant, false, '空的偵測器不該通過合格性檢查');
  assert.equal(r.missing_fields.length, REQUIRED_FIELDS.length, '七個必要欄位都要點出來');
  return `detectorResult({}) 報 ${r.missing_fields.length} 個缺欄位:${r.missing_fields.join(',')}`;
});

spec(2, 'MUST 不滿足即不合格', 'NOT_CHECKABLE',
  () => '這條定義了「不合格」這個詞,是這份測試存在的理由,不是測試對象。');

spec(3, '早期偵測、觀察與診斷分離、保存證據、最小恢復動作', 'NOT_CHECKABLE',
  () => '總綱。四個子目標分別由第 8、10、18、22、33、35 條覆蓋,拆開測才有意義。');

// ── §0.2 Non-goals ──────────────────────────────────────────

spec(4, '不准只憑模型語言推斷欺騙意圖', 'CHECK', () => {
  const p = src('provenance.js');
  assert.ok(/OUT_OF_SCOPE/.test(p), 'provenance 要明列不做語意判定的形狀');
  assert.ok(!/\bintent\b/.test(code('provenance.js')), '執行碼不出現意圖判定');
  return 'provenance 有 OUT_OF_SCOPE 清單,執行碼不判意圖';
});

spec(5, '不准要求存取隱藏思維鏈', 'CHECK', () => {
  const all = ['capture.js', 'drift.js', 'provenance.js', 'signals.js', 'runtime.js'].map(code).join('\n');
  assert.ok(!/thinking|chain_of_thought|reasoning_content/.test(all));
  return '五個核心模組的執行碼都沒有讀 thinking / chain_of_thought';
});

spec(6, '不准每一輪都注入 prompt 來驗健康', 'CHECK', () => {
  const p = planBeat(createBeatState(), { hasGoal: false, hasSignals: false });
  assert.notEqual(p.inject, true, '沒有訊號時不該注入');
  return `沒有目標也沒有訊號時 planBeat.inject=${p.inject}`;
});

spec(7, '不准只憑憤怒、髒話、挫折就判模型失敗', 'CHECK', () => {
  const r = code('rhetoric.js');
  assert.ok(!/anger|profanity|髒話|憤怒/i.test(r), '執行碼裡沒有情緒判定');
  const t = composite([{ id: 'S9', value: 1 }]);
  assert.notEqual(t.state, 'CRITICAL', '單一個取消壓力訊號拉滿也不該直接判到最高');
  return `rhetoric 執行碼無情緒判定;S9 拉滿 → state=${t.state}`;
});

spec(8, '不准把活動、工具呼叫、檔名當成進度的證明', 'CHECK', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED', observations: { exists: true } });
  assert.notEqual(r.verdict, 'VERIFIED', '光是檔案存在不足以算驗證過');
  assert.ok(/verified_progress/.test(src('heartbeat.js')), 'heartbeat 只認 verified_progress');
  return `檔案存在 → verdict=${r.verdict};heartbeat 只認 verified_progress`;
});

spec(9, '不准只因啟發式分數高就擋低風險的正常工作', 'CHECK', () => {
  const r = canIntervene('BLOCK_HIGH_RISK', { temperature: 0.99 });
  assert.equal(r.allowed, false, '光是溫度高不能硬擋');
  // 閘門對不代表有人問。2026-09-08 的教訓:三個 exit(2) 一個都沒問過它,
  // 而擁有者的夜間工作被擋了九個小時。所以這條要一起驗真的會擋人的那段。
  for (const f of ['forseti-hook.mjs', 'forseti-stop-hook.mjs']) {
    const text = readFileSync(join(HERE, '..', 'hooks', f), 'utf8')
      .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '))
      .replace(/^([^\n]*?)\/\/[^\n]*$/gm, (m, keep) => keep);
    const lines = text.split('\n');
    lines.forEach((line, i) => {
      if (!/process\.exit\(2\)/.test(line)) return;
      const before = lines.slice(Math.max(0, i - 15), i).join('\n');
      assert.match(before, /g\.allowed|gate\(/, `${f}:${i + 1} 有沒問過閘門的 exit(2)`);
    });
  }
  return `溫度 0.99 → allowed=false;兩個 hook 裡沒有繞過閘門的 exit(2)`;
});

spec(10, '每個主張旁邊都要放知識論狀態', 'CHECK', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED', observations: {} });
  assert.equal(r.epistemic, 'UNKNOWN', '沒有觀測就是 UNKNOWN');
  assert.ok(r.reasons?.length, '要說為什麼');
  return `沒有觀測 → epistemic=${r.epistemic}:${r.reasons[0].slice(0, 60)}`;
});

// ── §2 語意規則 ──────────────────────────────────────────────

spec(11, '長度本身不代表品質', 'CHECK', () => {
  const t = code('signals.js') + code('artifact.js');
  assert.ok(!/\.length\s*[><]=?\s*\d{3}/.test(t), '沒有拿長度當品質門檻');
  return 'signals 與 artifact 的執行碼沒有長度門檻';
});

spec(12, '工具跑完不代表任務完成', 'CHECK', () => {
  const r = verifyClaim({ kind: 'TEST_PASSED', observations: { command: 'npm test' } });
  assert.notEqual(r.verdict, 'VERIFIED', '沒有 exit_code 不能算通過');
  return `有指令沒有 exit_code → verdict=${r.verdict}`;
});

spec(13, '檔名存在不代表產出有效', 'CHECK', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED', observations: { exists: true, bytes: 0 } });
  assert.notEqual(r.verdict, 'VERIFIED');
  return `存在但零位元組 → verdict=${r.verdict}`;
});

spec(14, 'diff 大小不代表有用的進度', 'CHECK', () => {
  assert.ok(!/diff_lines\s*[><]=?\s*\d/.test(code('artifact.js') + code('heartbeat.js')));
  return '沒有任何地方拿 diff_lines 當進度判準';
});

spec(15, '使用者更正不自動代表 AI 失敗', 'CHECK', () => {
  const t = composite([{ id: 'S6', value: 1 }]);
  assert.notEqual(t.state, 'CRITICAL', '更正負擔拉滿也不該單獨判到最高');
  return `S6(更正負擔)拉滿 → state=${t.state},temperature=${t.temperature}`;
});

spec(16, '使用者中斷時盡可能留下 checkpoint', 'CHECK', () => {
  const r = interruptReadiness({ events: [], now: Date.now() });
  assert.ok(r && typeof r === 'object', 'interruptReadiness 要回答「現在中斷的話留得下什麼」');
  const snap = createSnapshot({ at: 1, goal: null, openFiles: [], lastVerified: null });
  assert.ok(snap, 'createSnapshot 存在');
  return 'rescue.js 有 createSnapshot 與 interruptReadiness';
});

spec(17, 'checkpoint 存在不代表語意正確', 'CHECK', () => {
  // 測行為,不測註解裡有沒有寫那句話。
  const snap = createSnapshot({ at: 1, goal: null, openFiles: ['/p/a.js'], lastVerified: null });
  assert.ok(!('correct' in snap) && !('valid' in snap) && !('verified' in snap),
    '快照不准帶「這是對的」這種欄位');
  const r = verifyClaim({ kind: 'FILE_CREATED', observations: { exists: true } });
  assert.notEqual(r.verdict, 'VERIFIED', '存在性證據不能升級成 VERIFIED');
  return '快照不宣稱正確性;存在性證據升不到 VERIFIED';
});

// ── §3 溫度 ─────────────────────────────────────────────────

spec(18, '溫度計不准被標成 lying score', 'CHECK', () => {
  const s = src('signals.js');
  assert.ok(!/lying|說謊分數/i.test(s), '不能有 lying score 的標籤');
  const t = composite([{ id: 'S1', value: 0.9 }]);
  assert.ok('measured_weight' in t, '要說這個數字用了多少比重的資料算的');
  assert.ok(t.note || t.measured_weight >= 0.5, '資料不足時要自己說');
  return `沒有 lying score;measured_weight=${t.measured_weight.toFixed(2)} 且附註記`;
});

spec(19, '分數必須附帶最主要的貢獻訊號', 'CHECK', () => {
  const t = composite([{ id: 'S1', value: 0.8 }, { id: 'S2', value: 0.1 }]);
  assert.ok(Array.isArray(t.top_contributors) && t.top_contributors.length, '要附貢獻訊號');
  assert.ok('contribution' in t.top_contributors[0], '每個貢獻者要有貢獻量');
  return `top_contributors:${t.top_contributors.map((c) => `${c.id}=${c.contribution.toFixed(3)}`).join(', ')}`;
});

spec(20, '門檻是工程預設,必須帶版本並用標記資料校準', 'CHECK', () => {
  for (const f of ['drift.js', 'signals.js', 'followthrough.js', 'scope.js']) {
    assert.ok(/export const VERSION/.test(src(f)), `${f} 要帶 VERSION`);
  }
  assert.ok(/沒有實測校準/.test(src('followthrough.js')), '未校準的常數要自己說');
  return '四個偵測器都帶 VERSION;未校準常數在原始碼裡自己標明';
});

// ── §4 飄移 ─────────────────────────────────────────────────

spec(21, '不准用問模型「你還在照目標做嗎」來判飄移', 'CHECK', () => {
  assert.ok(!/\bask\b|詢問|問模型/.test(code('drift.js')), 'drift 執行碼不問模型');
  return 'drift.js 只吃事件,不問模型';
});

spec(22, '可以偵測執行期不穩,但不准直接說語意飄移', 'CHECK', () => {
  const r = classify([{ at: 1, file_path: '/a/x.js' }], {}, { goal_state: 'MISSING' });
  assert.notEqual(r.is_drift, true, 'GoalState=MISSING 時不准說飄移');
  return `GoalState=MISSING → is_drift=${r.is_drift},${String(r.reason ?? r.state ?? '').slice(0, 60)}`;
});

spec(23, 'D_drift 必須跟 GoalState 一起報;MISSING 時要說「無法判定」', 'CHECK', () => {
  const c = cannotDetermine('goal alignment');
  assert.ok(/cannot be determined|無法判定/i.test(JSON.stringify(c)), '要有明確的「無法判定」文案');
  const r = classify([{ at: 1, file_path: '/a/x.js' }], {}, { goal_state: 'MISSING' });
  assert.ok('goal_state' in r || 'state' in r, '飄移結果必須帶著 GoalState 一起回');
  return `cannotDetermine 有制式文案,classify 回傳帶 goal state`;
});

spec(37, '系統不准把語意飄移當事實陳述', 'CHECK', () => {
  const ok = statableAsFact({ verdict: 'drift', epistemic: 'INFERRED' });
  assert.notEqual(ok === true, true, 'INFERRED 的飄移不准當事實講');
  return `statableAsFact(INFERRED 的 drift) → ${JSON.stringify(ok).slice(0, 80)}`;
});

// ── §5 管線 ─────────────────────────────────────────────────

spec(24, '全 session 語意攝取是例外,預設是事件優先收斂', 'CHECK', () => {
  const rt = createRuntime();
  assert.equal(typeof rt.ingest, 'function', '入口是事件');
  assert.ok(!/full_text|whole_session/.test(code('capture.js')), '採集層不吃全文');
  return 'runtime 的入口是 ingest(事件);capture 不讀全文';
});

// ── §6 活性 ─────────────────────────────────────────────────

spec(25, '長時間工作必須露出可見的活性', 'CHECK', () => {
  const r = livenessReport({ events: [], now: Date.now() });
  assert.ok(r && typeof r === 'object', '要有活性報告');
  const j = judgeBeat({ verified_progress: null }, createBeatState());
  assert.ok(j.verdict || j.state || j.reason, '拿不到進度時要說出狀態而不是靜默');
  return `livenessReport 存在;拿不到進度時 judgeBeat 回 ${j.verdict ?? j.state}`;
});

// ── §8 介面 ─────────────────────────────────────────────────

spec(26, '預設人機介面必須在模型 prompt 之外', 'CHECK', () => {
  // 剝掉註解再看,不然會抓到解釋這件事的註解本身。
  const strip = (t) => t.replace(/\/\*[\s\S]*?\*\//g, ' ').replace(/^([^\n]*?)\/\/[^\n]*$/gm, '$1');
  for (const f of ['forseti-hook.mjs', 'forseti-stop-hook.mjs']) {
    const h = strip(readFileSync(join(HERE, '..', 'hooks', f), 'utf8'));
    assert.ok(!/systemPrompt|additionalContext/.test(h),
      `${f} 在注入模型 context。規格書 §9.1 的 observer-effect prohibition:`
      + '持續改動被觀測的 context,量到的就不再是原本那個東西。');
  }
  assert.ok(/stderr/.test(readFileSync(join(HERE, '..', 'hooks', 'forseti-hook.mjs'), 'utf8')),
    '要透過 stderr 對人說話');
  return '兩個 hook 都只走 stderr 與 systemMessage,不碰模型 prompt';
});

spec(27, '桌面常駐溫度計,HEALTHY/WATCH 時保持安靜', 'NOT_IMPLEMENTED',
  () => '沒有桌面 sidecar。tools/dashboard.mjs 是手動跑的網頁,不是常駐 overlay。');

spec(28, 'inline 標註不准改動原訊息', 'NOT_IMPLEMENTED',
  () => 'Claude Code 沒有那個掛鉤點。規格書這條用的是 MAY,goal.json 的 not_now 已列。');

spec(29, '架構必須把被動觀察與會改變 agent 行為的動作分開', 'CHECK', () => {
  assert.ok(PLANES && Object.keys(PLANES).length >= 2, '要有明確的分層');
  return `intervention.PLANES = ${Object.keys(PLANES).join(' / ')}`;
});

spec(30, '必須量實際的干預率與誤報負擔', 'CHECK', () => {
  const rate = interventionRate([]);
  assert.ok(rate === null || typeof rate === 'object', '沒資料時不准回 0');
  const o = interceptOutcomes([]);
  assert.equal(o.rate, null, '沒有攔截紀錄時要回 null,不是乾淨紀錄');
  assert.ok(/no record/i.test(o.note), '要說清楚沒紀錄不等於沒問題');
  return `interceptOutcomes([]) → rate=null,「${o.note.slice(0, 60)}」`;
});

spec(31, '不准持續盤問被觀察的模型', 'CHECK', () => {
  const iv = nextInterval({ verdict: 'HEALTHY' });
  assert.ok(iv.delay_ms > 0, '心跳有間隔,不是每輪');
  return `健康時下一次心跳間隔 ${(iv.delay_ms / 60000).toFixed(0)} 分鐘(${iv.reason})`;
});

spec(32, '任何注入的問題都要記成 intervention 事件', 'CHECK', () => {
  const log = recordIntervention([], { at: 1, action: ACTIONS[0], injected: true });
  assert.equal(log.length, 1);
  assert.equal(log[0].injected, true, '要標明有沒有注入');
  return 'recordIntervention 記下 injected 旗標';
});

spec(33, '硬性介入必須有比高溫更多的理由', 'CHECK', () => {
  const hot = canIntervene('BLOCK_HIGH_RISK', { temperature: 0.99 });
  assert.equal(hot.allowed, false);
  return '只有高溫 → allowed=false';
});

// ── §9 校準 ─────────────────────────────────────────────────

spec(34, '模型自白不准當成唯一的 ground truth', 'CHECK', () => {
  assert.ok(ORIGINS.includes('SELF_WRITTEN'), '自寫的來源要單獨標');
  assert.ok(ORIGINS.includes('FIRST_HAND'), '要跟第一手證據分開');
  return `provenance.ORIGINS = ${ORIGINS.join(' / ')}`;
});

spec(35, '缺證據標 UNKNOWN;前向採集要留 path/size/hash/timestamps/exit code', 'CHECK', () => {
  const r = verifyClaim({ kind: 'FILE_CREATED', observations: {} });
  assert.equal(r.epistemic, 'UNKNOWN', '缺證據要標 UNKNOWN');
  const rt = createRuntime();
  rt.ingest([{
    attributed_agent: 'a', name: 'Write', input: { file_path: '/p/x.js' },
    at: Date.now(), bytes: 512, hash: 'deadbeef', exit_code: 0,
  }]);
  const ev = JSON.parse(JSON.parse(rt.save()).body).events[0];
  const missing = ['bytes', 'hash', 'exit_code'].filter((f) => !(f in ev));
  assert.equal(missing.length, 0,
    `前向採集缺 ${missing.join(', ')};規格書要求事件當下就留 path/size/hash/timestamps/exit code。`
    + '舊 session 的部分符合(缺證據標 UNKNOWN),前向的部分沒做。');
  return '';
});

spec(36, '第一版不要解決所有問題,做最小可測閉環', 'NOT_CHECKABLE',
  () => '對範圍的要求,不是對程式的要求。對應物是 goal.json 的 not_now 三條。');

spec(38, '輸出 drift/deception/failure/safe 而沒有那些欄位的偵測器要標成實驗性', 'CHECK', () => {
  const r = detectorResult({ verdict: 'drift', inputs: { a: 1 }, version: 'v1' });
  assert.equal(r.conformant, false);
  assert.ok(r.missing_fields.length > 0);
  return `欄位不全 → conformant=false,缺 ${r.missing_fields.join(', ')}`;
});

// ── 報告 ────────────────────────────────────────────────────

const by = {};
for (const r of results) by[r.verdict] = (by[r.verdict] ?? 0) + 1;
const covered = new Set(results.map((r) => r.n));
const uncovered = [];
for (let i = 1; i <= 38; i += 1) if (!covered.has(i)) uncovered.push(i);

console.log('\n對照 docs/spec-v0.1.md 的 38 條規範句\n');
for (const r of results.sort((a, b) => a.n - b.n)) {
  const mark = { CONFORMS: '   ', VIOLATES: ' ★ ', NOT_IMPLEMENTED: ' ☐ ', NOT_CHECKABLE: ' · ' }[r.verdict];
  console.log(`${mark}${String(r.n).padStart(2)}. ${r.title}`);
  if (r.verdict !== 'CONFORMS') console.log(`       ${r.verdict}  ${r.ev}`);
}
console.log('');
for (const k of ['CONFORMS', 'VIOLATES', 'NOT_IMPLEMENTED', 'NOT_CHECKABLE']) {
  if (by[k]) console.log(`  ${k.padEnd(18)} ${by[k]}`);
}
if (uncovered.length) console.log(`\n★ 這 ${uncovered.length} 條連檢查都還沒寫：${uncovered.join(', ')}`);
console.log('');
process.exit((by.VIOLATES ?? 0) + uncovered.length > 0 ? 1 : 0);
