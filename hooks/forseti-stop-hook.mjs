#!/usr/bin/env node
/**
 * Forseti Stop hook：在回合結束的那一刻檢查有沒有說了不做的事。
 *
 * ── 為什麼需要這個,而 PreToolUse 不夠 ──────────────────
 *
 * 寫入前的 hook 抓得到「要動檔案了」,抓不到「我要停下來了」。
 * 而「說了要做,然後結束回合,零動作」這件事,整件事就發生在後者那一刻。
 *
 * 這是實測的:掃寫出 Forseti 的那個 session,401 輪裡有 23 輪
 * 宣告要動手然後結束時零工具呼叫。當事人以為是兩次。
 * 有 PreToolUse 的那幾十輪裡,它一次都沒有機會開口,
 * 因為那些輪根本沒有工具呼叫可以攔。
 *
 * ── 三條防止它變成折磨的規則 ──────────────────────────
 *
 * 一,同一輪最多擋一次。擋兩次就變成「你不做完不准停」,
 *   而有些事本來就該停下來問人。
 * 二,只擋點名了具體檔案的宣告。說不清楚要做什麼的宣告驗不了,
 *   拿驗不了的東西擋人,是把工具的無能變成使用者的義務。
 * 三,任何內部錯誤都放行。這條跟另一個 hook 一樣:
 *   卡住使用者的守衛會被拔掉,而被拔掉的守衛保護不了任何人。
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname, resolve as resolvePath, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OK = () => process.exit(0);

/**
 * 硬邊界:這個 hook 只准在它自己所屬的 repo 底下作用。
 *
 * 2026-09-08:這三個 hook 曾經被裝進全域設定,對擁有者機器上每一個目錄
 * 生效,擋掉她整晚的工作。那次的錯誤不在門檻,在範圍 —— 我以為我知道
 * 設定的作用範圍,而我理解錯了。
 *
 * 所以範圍不能只靠設定檔的位置來保證。這裡再加一道程式碼層的邊界:
 * repo 根目錄是從這個檔案自己的位置算出來的(hooks/ 的上一層),
 * 所以 repo 搬到哪它就跟到哪,不必維護一份會過期的路徑清單。
 * cwd 不在底下就立刻 exit 0,連狀態檔都不建。
 *
 * 這道邊界不看設定、不看環境變數、不可設定關閉。要放寬範圍必須改這段
 * 程式碼並且說明理由,不能靠改一行 JSON 就悄悄擴張。
 */
const REPO_ROOT = resolvePath(HERE, '..');

function insideRepo(cwd) {
  if (!cwd) return false;
  const c = resolvePath(cwd);
  return c === REPO_ROOT || c.startsWith(REPO_ROOT + sep);
}

/**
 * 對外部專案的保護,預設關閉。完整理由見 forseti-hook.mjs 同名函式的註解 ——
 * 兩份保持一致,是刻意留著的重複,不是漏改;test/hooks.e2e.test.mjs 的
 * AT-HOOK-B4 逐一比對兩個檔案,兩邊不一致會被抓到。
 */
function crossProjectEnabled(cwd) {
  if (!cwd) return false;
  try {
    const p = join(resolvePath(cwd), '.forseti', 'config.json');
    if (!existsSync(p)) return false;
    const cfg = JSON.parse(readFileSync(p, 'utf8'));
    return cfg.cross_project_enabled === true;
  } catch {
    return false;
  }
}

process.on('uncaughtException', OK);
process.on('unhandledRejection', OK);

function root(cwd) { return process.env.CLAUDE_PROJECT_DIR || cwd || process.cwd(); }
function ledgerPath(cwd) { return join(root(cwd), '.forseti', 'declarations.json'); }

function load(cwd) {
  const p = ledgerPath(cwd);
  if (!existsSync(p)) return { open: [], blockedAt: null };
  try { return JSON.parse(readFileSync(p, 'utf8')); } catch { return { open: [], blockedAt: null }; }
}
function save(cwd, data) {
  try {
    mkdirSync(dirname(ledgerPath(cwd)), { recursive: true });
    writeFileSync(ledgerPath(cwd), JSON.stringify(data));
  } catch { /* 存不了就放行 */ }
}

async function main() {
  let input;
  try { input = JSON.parse(readFileSync(0, 'utf8')); } catch { OK(); }
  if (!input || input.hook_event_name !== 'Stop') OK();

  // 邊界最先檢查,在讀任何狀態、建任何目錄之前。
  const cwdForBoundary = process.env.CLAUDE_PROJECT_DIR || input.cwd;
  if (!insideRepo(cwdForBoundary) && !crossProjectEnabled(cwdForBoundary)) OK();

  // 階段 1：Stop 也要進 Event Ledger。
  //
  // 位置在 `if (!open.length) OK()` 之前，那一行很關鍵 ——
  // 大多數的 Stop 都沒有未完成的宣告，會從那裡直接離開。
  // 記在它後面的話，只有「被擋下來的那一輪」會留下紀錄，
  // 正常收尾的每一輪都會消失。那樣的帳本只看得到異常看不到基準，
  // 而異常沒有基準就失去了比較的對象。
  //
  // Stop 對到 v5.0 §6.2 的 MODEL_OUTPUT 是我的映射選擇不是規格明文，
  // 理由寫在 hooks/event-ledger.mjs 的 classify()。
  try {
    const el = await import(join(HERE, 'event-ledger.mjs'));
    const dir = process.env.FORSETI_EVENT_LEDGER_DIR
      || join(root(input.cwd), '.forseti');
    el.appendEvent(dir, input, {
      sessionId: input.session_id || '',
      projectId: REPO_ROOT.split(sep).pop() || '',
    });
  } catch { /* 記不下來就算了，下面每一步都不受影響 */ }

  const cwd = input.cwd;
  const led = load(cwd);
  const open = led.open ?? [];
  if (!open.length) OK();

  // 規則一:同一輪最多擋一次。
  // 用 transcript 路徑加最後一次擋的時間當識別,避免在同一輪反覆擋。
  const now = Date.now();
  if (led.blockedAt && now - led.blockedAt < 30_000) {
    save(cwd, { ...led, blockedAt: null });   // 用掉這次額度,下一輪才能再擋
    OK();
  }

  const { resolve: resolveDeclaration } = await import(join(HERE, '..', 'src', 'followthrough.js'));

  // 讀事件狀態,看那些宣告有沒有被兌現
  let events = [];
  const statePath = join(root(cwd), '.forseti', 'state.json');
  if (existsSync(statePath)) {
    try {
      const { createRuntime } = await import(join(HERE, '..', 'src', 'runtime.js'));
      const rt = createRuntime();
      const r = rt.restore(readFileSync(statePath, 'utf8'));
      events = r.state?.events ?? [];
    } catch { /* 讀不到就當沒有事件,那會讓宣告全部算成未兌現 —— 見下方 */ }
  }

  // 規則二:只擋點名了具體檔案的
  const checkable = open.filter((d) => (d.targets ?? []).length > 0);
  if (!checkable.length) OK();

  const outstanding = [];
  const remaining = [];
  for (const d of checkable) {
    const r = resolveDeclaration(d, { events, currentTurn: (d.turn ?? 0) + 99, now });
    if (r.state === 'OMITTED') outstanding.push(d);
    else if (r.state === 'PENDING') remaining.push(d);
  }
  // 兌現的與被擋過的從帳上移除,不要累積成永遠清不掉的債
  save(cwd, { open: remaining, blockedAt: outstanding.length ? now : null });

  if (!outstanding.length) OK();

  const lines = outstanding.map((d) => `  · ${d.targets.join(', ')} — ${(d.what ?? '').slice(0, 70)}`);

  // ── 擋還是只講 ──────────────────────────────────────
  //
  // 預設只講。說了沒做不是「硬前提未知」,而 intervention.js 的
  // canIntervene 裡 BLOCK_HIGH_RISK 只在硬前提不明時放行。
  // 原本這裡是 exit(2) 而且沒問過那一層,2026-09-08 擋了她九個小時。
  //
  // **owner 可以覆寫。** 她在信任階層的第一級(§3.3),
  // 她明確要求強制介入的時候,規格的預設姿態讓位給她的決定 ——
  // 但讓位要留下痕跡,所以走 config 不走改程式碼,而且有次數上限。
  //
  // 2026-09-16 owner 原話:「我現在要你開啟 Forseti 全自動介入你的工作,
  // 強制介入」。
  let enforce = false;
  let cap = 3;
  try {
    const cfgPath = join(root(cwd), '.forseti', 'config.json');
    if (existsSync(cfgPath)) {
      const cfg = JSON.parse(readFileSync(cfgPath, 'utf8'));
      enforce = cfg.enforce_declarations === true;
      if (Number.isInteger(cfg.enforce_max_per_session)) cap = cfg.enforce_max_per_session;
    }
  } catch { /* 讀不到設定就是沒開。預設永遠是不擋 */ }

  // 次數上限。2026-09-08 那次沒有上限 ——
  // 有上限的最壞情況是被煩三次,沒上限的最壞情況是一整晚沒辦法工作。
  const sid = input.session_id || '';
  const counts = led.enforced ?? {};
  const used = counts[sid] ?? 0;
  if (enforce && used >= cap) enforce = false;

  const body =
    `Forseti: ${outstanding.length} thing(s) declared this session with no matching action on disk.\n`
    + lines.join('\n');

  if (!enforce) {
    process.stderr.write(
      body
      + '\n\nEither do them now, or say explicitly that they are dropped. '
      + 'This is an observation, not a block.\n',
    );
    process.exit(0);
  }

  save(cwd, {
    open: remaining,
    blockedAt: now,
    enforced: { ...counts, [sid]: used + 1 },
  });
  process.stderr.write(
    body
    + `\n\n這一輪宣告了上面的檔案，結束時磁碟上沒有對應的動作。`
    + `\n要嘛現在做完，要嘛明講那幾項不做了。`
    + `\n\n（強制介入由 .forseti/config.json 的 enforce_declarations 開啟，`
    + `這條線第 ${used + 1} 次，上限 ${cap} 次。要關掉把那個欄位改成 false）\n`,
  );
  process.exit(2);
}

main().then(OK).catch(OK);
