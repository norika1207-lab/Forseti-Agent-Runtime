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

  // 說了沒做不是硬前提未知,所以這裡不擋,只講。
  // 原本這裡是 exit(2),那會變成「你不做完不准停」—— 而有些事本來就該
  // 停下來問人,把那也擋掉就是把工具的意見凌駕在人的判斷之上。
  process.stderr.write(
    `Forseti: ${outstanding.length} thing(s) declared this session with no matching action on disk.\n`
    + lines.join('\n')
    + '\n\nEither do them now, or say explicitly that they are dropped. '
    + 'This is an observation, not a block.\n',
  );
  process.exit(0);
}

main().then(OK).catch(OK);
