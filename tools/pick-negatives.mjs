#!/usr/bin/env node
/**
 * 從 corpus-profile 的輸出裡挑出 healthy negative 候選。
 *
 * §26 P14 需要兩種樣本:已知有失效的(用來量漏報),以及沒有失效的
 * (用來量誤報)。前者現在有一份 —— 寫出 v2 的那個 session,
 * 見 docs/calibration/2026-09-08-self-scan.md。後者是這個工具在找的。
 *
 * ── 這個工具最重要的一件事是它不能做的事 ─────────────────
 *
 * 它挑不出「健康的 session」。它只挑得出「用四類獨立事實看不出問題的
 * session」,而那兩件事差很遠。
 *
 * 差別在哪:一個 session 可能工具全部成功、產出正常、人類沒有中斷,
 * 而 agent 從頭到尾在做一件 owner 沒有要的事。那正是 CASE-D
 * (框架被偷換)的形狀,而這裡用的四類事實一個都看不到它。
 *
 * 所以輸出的標籤是 `PRESUMED_HEALTHY`,證據等級 `MODEL_INFERENCE`,
 * 而 §25.1 講得很清楚:MODEL_INFERENCE 只能做 candidate/score。
 * 要變成 ground truth,需要 owner 看過。
 *
 * ── 為什麼判準要跟偵測器獨立 ─────────────────────────
 *
 * 如果用 CB、PS、drift 分數挑「健康」的 session,再拿那批量誤報率,
 * 選出來的當然全部低分。那是 FP-05 Evidence Independence Collapse:
 * 兩份證據共用同一個決定性上游,卻被當成互相印證。
 *
 * 所以判準只用 corpus-profile 抽的四類事實,那四類都是宿主寫進
 * transcript 的 runtime fact,不是任何偵測器算出來的。
 *
 * 用法:
 *   node tools/pick-negatives.mjs <profiles.json> [--n 30] [--json]
 */
import { readFileSync } from 'node:fs';

const file = process.argv[2];
const nArg = process.argv.indexOf('--n');
const want = nArg > 0 ? Number(process.argv[nArg + 1]) : 30;
const asJson = process.argv.includes('--json');

if (!file) {
  console.error('用法: node tools/pick-negatives.mjs <profiles.json> [--n 30] [--json]');
  process.exit(1);
}

const profiles = JSON.parse(readFileSync(file, 'utf8'));

/**
 * 排除條件。每一條都附「為什麼這條跟被測的偵測器獨立」。
 *
 * 這些不是「健康的定義」,是「這份樣本能不能拿來量誤報」的前提。
 * 一個被中斷的 session 不代表 agent 有問題,但它的訊號不完整,
 * 拿它量誤報會把「資料缺角」算成「偵測器出錯」。
 */
const EXCLUSIONS = Object.freeze([
  {
    id: 'TOO_SMALL',
    why: '工具呼叫少於 20。太短的 session 沒有足夠的行為可以判斷,'
      + '任何偵測器在上面都不會有 finding,拿它量誤報率會虛假地壓低分母。',
    test: (p) => p.tool_uses < 20,
  },
  {
    id: 'NO_HUMAN',
    why: '沒有人類訊息。完全沒有人參與的 session 缺少 correction 訊號,'
      + '而 CB/HCD 這一整類指標在上面沒有意義。',
    test: (p) => p.human_messages === 0,
  },
  {
    id: 'SUBAGENT',
    /**
     * 這一條是第一次跑完之後補的,而它是一個真實的判準漏洞。
     *
     * 第一版取樣 40 個,其中 18 個來自 subagents 目錄。它們通過了
     * NO_HUMAN 檢查,因為主 agent 給的 prompt 在 transcript 裡被記成
     * user 訊息 —— 看起來「有人類參與」,實際上沒有任何人在場。
     *
     * 拿它們量 CB/HCD 的誤報率會得到一個沒有意義的數字:那些指標
     * 量的是人機協作,而那裡沒有人。
     *
     * 判準是路徑,不是內容 —— 可觀測,不判讀。
     */
    why: 'subagent 的 transcript。主 agent 的 prompt 會被記成 user 訊息,'
      + '所以它看起來有人類參與,實際上沒有。CB/HCD 這類協作指標在上面'
      + '量不出有意義的東西。',
    test: (p) => /\/subagents\//.test(p.file ?? ''),
  },
  {
    id: 'NO_OUTPUT',
    why: '零寫檔。沒有產出的 session 無法區分「順利完成」與「什麼都沒做」,'
      + '而後者正是 FP-24 PTN 要抓的東西 —— 拿它當 healthy 會直接製造假的誤報。',
    test: (p) => p.writes === 0,
  },
  {
    id: 'HIGH_TOOL_ERROR',
    why: '工具錯誤率超過 15%。這是宿主寫的 is_error,不是偵測器的判斷。'
      + '高錯誤率的 session 本身可能真的有問題,不適合當「沒有問題」的樣本。',
    test: (p) => (p.tool_error_rate ?? 0) > 0.15,
  },
  {
    id: 'INTERRUPTED',
    why: '有使用者中斷。中斷是宿主記錄的事件,不判讀語意。'
      + '被打斷的 session 訊號不完整,而且中斷本身常常就是使用者發現了什麼。',
    test: (p) => p.interrupts > 0,
  },
  {
    id: 'PARSE_DAMAGED',
    why: '解析健康度低於 0.99。讀不懂的行超過 1% 時,統計數字的意義就變了。',
    test: (p) => (p.parse_health ?? 1) < 0.99,
  },
]);

const excluded = new Map();
const survivors = [];

for (const p of profiles) {
  const hit = EXCLUSIONS.find((e) => e.test(p));
  if (hit) {
    if (!excluded.has(hit.id)) excluded.set(hit.id, []);
    excluded.get(hit.id).push(p.session);
  } else survivors.push(p);
}

/**
 * 從存活者裡取樣。
 *
 * 刻意取「規模分布上均勻的一批」而不是「最大的 N 個」:
 * 最大的那些是長時間、多輪的 session,它們的失效機率跟一般 session
 * 不同。用它們量出來的誤報率不能代表日常使用。
 */
survivors.sort((a, b) => a.tool_uses - b.tool_uses);
const picked = [];
if (survivors.length <= want) {
  picked.push(...survivors);
} else {
  const step = survivors.length / want;
  for (let i = 0; i < want; i += 1) picked.push(survivors[Math.floor(i * step)]);
}

const result = {
  label: 'PRESUMED_HEALTHY',
  evidence_class: 'MODEL_INFERENCE',
  /** §25.1:MODEL_INFERENCE 只能做 candidate/score,不能當 ground truth。 */
  ground_truth: false,
  what_this_label_means:
    '用四類獨立於偵測器的 runtime fact 看不出問題。這不等於沒有問題 —— '
    + '一個工具全部成功、產出正常、沒有中斷的 session，仍然可能整段都在做 '
    + 'owner 沒有要的事(CASE-D 的形狀)，而這四類事實一個都看不到它。',
  what_would_upgrade_it:
    'owner 逐一看過並確認。在那之前，這批上的任何 finding 都有兩種可能 —— '
    + '誤報，或者一個沒被發現的真實失效 —— 而這個工具區分不了。',
  population: profiles.length,
  survivors: survivors.length,
  picked: picked.length,
  exclusions: Object.fromEntries(
    EXCLUSIONS.map((e) => [e.id, { count: excluded.get(e.id)?.length ?? 0, why: e.why }]),
  ),
  sessions: picked.map((p) => ({
    file: p.file,
    session: p.session,
    project: p.project,
    tool_uses: p.tool_uses,
    writes: p.writes,
    human_messages: p.human_messages,
    tool_error_rate: p.tool_error_rate,
    span_hours: p.span_ms ? +(p.span_ms / 3_600_000).toFixed(1) : null,
  })),
};

if (asJson) {
  console.log(JSON.stringify(result, null, 2));
  process.exit(0);
}

console.log(`\n  母體 ${result.population} 個 session\n`);
console.log('  排除（先數出來，理由都寫著）');
for (const [id, info] of Object.entries(result.exclusions)) {
  console.log(`    ${id.padEnd(18)} ${String(info.count).padStart(5)}`);
}
console.log(`\n  存活 ${result.survivors}，取樣 ${result.picked}`);
console.log(`\n  標籤       ${result.label}`);
console.log(`  證據等級   ${result.evidence_class}（§25.1：只能做 candidate，不是 ground truth）`);
console.log('\n  這個標籤的意思');
console.log(`    ${result.what_this_label_means}`);
console.log('\n  怎麼升級');
console.log(`    ${result.what_would_upgrade_it}`);
console.log('');
