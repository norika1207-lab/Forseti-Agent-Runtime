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
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OK = () => process.exit(0);
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
  process.stderr.write(
    `Forseti: ${outstanding.length} thing(s) declared this session with no matching action on disk.\n`
    + lines.join('\n')
    + '\n\nEither do them now, or say explicitly that they are dropped. '
    + 'This check fires once per turn and only for declarations that named a concrete file.',
  );
  process.exit(2);
}

main().then(OK).catch(OK);
