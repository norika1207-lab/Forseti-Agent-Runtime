#!/usr/bin/env node
/**
 * Forseti as a Claude Code hook.
 *
 * This is the first place Forseti runs against live work instead of a
 * transcript. Everything before it could only explain what had already
 * gone wrong.
 *
 * Install: see hooks/README.md
 *
 * ── The rule that outranks every check in here ───────────────────────
 *
 * A hook that gets in the way gets uninstalled, and an uninstalled guard
 * protects nobody. So: any internal failure exits 0 and lets the work
 * through. A crash in Forseti must never become a crash in someone's
 * editor.
 *
 * ── 2026-09-08:這裡曾經直接擋人,擋了一個晚上 ──────────────────
 *
 * 這個檔案原本有三個 process.exit(2),一個都沒有問過 intervention.js
 * 的 canIntervene —— 而那個模組存在的唯一理由就是回答「這種程度可不可以
 * 擋人」。它的答案一直都是對的:只有溫度高的時候,六個介入動作裡它只放行
 * QUIET_ANNOTATION,包含 BLOCK_HIGH_RISK 在內的其他五個全部拒絕,理由是
 * 「A high temperature alone is never sufficient」。
 *
 * 沒問的代價:裝上去之後,一個只寫著某個專案路徑的 scope 對整台機器每一個
 * 目錄生效,擁有者其他所有工作連續寫五個檔就被 deny 一次,而 streak 不會
 * 自己清掉。整整九個小時。留下的證據是 streak.json 的
 * total_checked: 12, total_off: 8。
 *
 * 這違反的是規格書自己第 9 條:MUST NOT block low-risk normal work solely
 * because a heuristic score is elevated。系統裡有一個模組專門守這條,
 * 而唯一真的會擋人的程式碼沒有接上它。
 *
 * 現在:每一個攔截點都要先過 gate()。閘門說只能安靜標註,就只說話,exit 0。
 *
 * ── What it does ────────────────────────────────────────────────────
 *
 *   PostToolUse   feed the event in; update coverage, evidence, scopes
 *   PreToolUse    on a write, check two things:
 *                   - is another session writing this same file right now
 *                   - have the last several writes all been outside the declared goal
 *
 * The second one only speaks after a streak, never on a single write. Doing
 * real work means touching things around the edges - configs, other people's
 * implementations, docs, tests. Flagging each of those is the same as flagging
 * none of them, because the whole thing gets switched off.
 *
 * State lives in one JSON file per project, because each hook invocation
 * is a fresh process with no memory of the last one.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync, statSync } from 'node:fs';
import { createHash } from 'node:crypto';
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
 * 對外部專案的保護,預設關閉。
 *
 * 2026-09-08 擁有者的裁決:先把「監控別的專案」這個能力寫出來,
 * 但不准讓它自動生效。上次事故的教訓不是門檻設太敏感,是範圍在
 * 沒有人確認過的情況下自己擴大了 —— 這次不能重蹈覆轍。
 *
 * 所以這裡不是 insideRepo() 的替代品,是疊加在它之上的第二條路:
 * 目標專案必須自己在 `.forseti/config.json` 明確寫
 * `cross_project_enabled: true` 才算數。檔案不存在、讀不到、
 * 格式壞掉、或值不是 true(例如字串 "true"),一律當作 false ——
 * 一個壞掉的設定檔絕不能被解讀成「生效」,那正是安裝腳本
 * (tools/install.mjs)只會寫 false、要人自己動手改的理由。
 *
 * insideRepo() 本身完全不受這個函式影響:Forseti repo 自己的保護
 * 永遠是無條件的,不看設定、不看環境變數。
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


/**
 * 說話,但不擋。
 *
 * 規格書 §8.4 的設計目標是 OBSERVE 99% / INTERRUPT 1%。這個函式是那個
 * 99% 的實作:把觀察到的事講出來,然後讓工作過去。
 *
 * 只走 systemMessage 與 stderr,兩個都是給人看的。
 *
 * 這裡原本還寫了 additionalContext,那個欄位會把文字接進被觀測對象的
 * prompt —— 正是規格書 §8.4 的「MUST be external to the model prompt」
 * 與 §9.1 的 observer-effect prohibition 禁止的事。持續改動被觀測的
 * context,量到的就不再是原本那個東西。
 *
 * 那行是修「擋整晚」的時候順手加的,十分鐘後被規格測試第 26 條抓到。
 * 寫的時候的念頭是「要讓訊息看得到」,而那個念頭直接壓過了規格。
 *
 * 【輸出格式未實測。】要驗證宿主怎麼呈現這段文字,得把 hook 裝回全域,
 * 而那件事現在不做。無論如何都 exit 0。
 */
function speak(text) {
  try {
    process.stdout.write(JSON.stringify({ systemMessage: text }));
    process.stderr.write(text + '\n');
  } catch { /* 說不出話也不能擋人 */ }
  process.exit(0);
}

/**
 * 問閘門:這種程度可不可以擋人。
 *
 * ctx 裡刻意不放溫度。溫度高從來不是擋人的理由,而把它放進來只會製造
 * 「調高門檻就可以擋」的錯覺。要擋人只有一條路:證明有一個硬前提是未知的,
 * 而那要拿得出證據,不是算得出分數。
 */
async function gate(ctx) {
  const { canIntervene } = await import(join(HERE, '..', 'src', 'intervention.js'));
  return canIntervene('BLOCK_HIGH_RISK', ctx);
}

// Anything unexpected: get out of the way.
process.on('uncaughtException', OK);
process.on('unhandledRejection', OK);

function readStdin() {
  try {
    return JSON.parse(readFileSync(0, 'utf8'));
  } catch {
    return null;
  }
}

function projectRoot(cwd) {
  return process.env.CLAUDE_PROJECT_DIR || cwd || process.cwd();
}
function stateFile(cwd) { return join(projectRoot(cwd), '.forseti', 'state.json'); }
function goalFile(cwd) { return join(projectRoot(cwd), '.forseti', 'goal.json'); }
function userGoalFile() {
  const home = process.env.HOME || process.env.USERPROFILE;
  return home ? join(home, '.forseti', 'goal.json') : null;
}
function streakFile(cwd) { return join(projectRoot(cwd), '.forseti', 'streak.json'); }

/**
 * 讀宣告過的目標範圍。沒有就回一個不作用的範圍,絕不推測。
 *
 * 先看專案自己的,再看使用者的。兩層是有必要的:
 * 專案層的北極星只在那個 repo 裡讀得到,而「這陣子只做 X」這種北極星
 * 最該開口的場合,正是人跑到別的目錄去做別的事的時候 ——
 * 那時候專案層的檔案根本不在腳下。只讀專案層等於在最需要的場合關機。
 */
function firstExisting(paths) {
  for (const p of paths) { if (p && existsSync(p)) return p; }
  return null;
}

async function loadScope(cwd) {
  const { createScope } = await import(join(HERE, '..', 'src', 'scope.js'));
  const p = firstExisting([goalFile(cwd), userGoalFile()]);
  if (!p) return createScope({});
  try {
    const g = JSON.parse(readFileSync(p, 'utf8'));
    return createScope({ northStar: g.north_star ?? null, paths: g.scope ?? [] });
  } catch {
    return createScope({});
  }
}

function loadStreak(cwd) {
  const p = streakFile(cwd);
  if (!existsSync(p)) return null;
  try { return JSON.parse(readFileSync(p, 'utf8')); } catch { return null; }
}
function saveStreak(cwd, streak) {
  try {
    mkdirSync(dirname(streakFile(cwd)), { recursive: true });
    writeFileSync(streakFile(cwd), JSON.stringify(streak));
  } catch { /* 存不了就算了,不擋工作 */ }
}

function loadState(rt, path) {
  if (!existsSync(path)) return null;
  try {
    return rt.restore(readFileSync(path, 'utf8'));
  } catch {
    return null;   // 壞掉的狀態檔不該擋住工作。下一次寫入會蓋掉它。
  }
}

function saveState(rt, path) {
  try {
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, rt.save());
  } catch {
    // 存不了就算了。丟掉這一輪的狀態,比擋住使用者好。
  }
}

const WRITE_TOOLS = /^(Write|Edit|MultiEdit|NotebookEdit)$/;

/**
 * 超過這個大小就只記大小,不算指紋。
 * 【1 MB 沒有實測校準。】算指紋要把整個檔案讀進來,而這段程式跑在
 * 每一次寫檔的路徑上。讀一個大檔的成本會直接變成使用者的等待。
 */
const MAX_HASH_BYTES = 1024 * 1024;

/**
 * 事件當下的輕量證據:大小與內容指紋。
 *
 * 規格書 §9 要求前向採集在事件當下就留下 path、size、hash、timestamps、
 * exit code。這三樣裡只有 path 跟 timestamp 是事後還問得到的;檔案被改過、
 * 被覆寫、被刪掉之後,當時的大小與指紋就永遠沒有了 —— 而那正是判斷一個
 * 宣稱有沒有兌現的憑據。所以要在這裡量,不是之後補。
 *
 * 量不到就回 null。不填 0:零位元組是一個事實,拿不到是另一回事。
 */
function evidenceFor(file) {
  try {
    const st = statSync(file);
    if (!st.isFile()) return { bytes: null, hash: null };
    const hash = st.size <= MAX_HASH_BYTES
      ? createHash('sha256').update(readFileSync(file)).digest('hex').slice(0, 16)
      : null;
    return { bytes: st.size, hash };
  } catch {
    return { bytes: null, hash: null };
  }
}

/**
 * 多久算「同時」。
 * 【15 秒沒有實測校準】,跟 admission.js 用同一個值,理由也一樣:
 * 它是個保守的起點,不是量出來的。太寬會一直誤攔,太窄會漏掉真的撞車。
 */
const WINDOW_MS = 15_000;

async function main() {
  const input = readStdin();
  if (!input) OK();

  // 邊界最先檢查,在讀任何狀態、建任何目錄之前。
  const cwdForBoundary = process.env.CLAUDE_PROJECT_DIR || input.cwd;
  if (!insideRepo(cwdForBoundary) && !crossProjectEnabled(cwdForBoundary)) OK();

  const { createRuntime } = await import(join(HERE, '..', 'src', 'runtime.js'));
  const rt = createRuntime();
  const path = stateFile(input.cwd);
  loadState(rt, path);

  const event = {
    attributed_agent: input.session_id || 'unknown',
    session_id: input.session_id || null,
    name: input.tool_name,
    input: input.tool_input ?? {},
    at: Date.now(),
  };

  if (input.hook_event_name === 'PreToolUse' && WRITE_TOOLS.test(String(input.tool_name))) {
    const file = input.tool_input?.file_path;
    if (!file) OK();

    // 不靠顯式宣告:hook 是無狀態的,沒有人會去登記佔用範圍。
    // 但「最近誰寫過這個檔」在事件流裡一直都在,而那才是真實撞車的樣子。
    const others = rt.recentWritersOf(file, {
      windowMs: WINDOW_MS,
      excludeAgent: input.session_id || 'unknown',
    });

    // 先看有沒有人正在寫同一個檔。撞車比離題急,而且離題不該蓋掉撞車的訊息。
    if (!others.length) {
      // 沒撞車才看離題。連續數次都在宣告的目標範圍外才說話。
      const { check } = await import(join(HERE, '..', 'src', 'scope.js'));
      const scope = await loadScope(input.cwd);
      if (scope.active) {
        const out = check(file, scope, loadStreak(input.cwd));
        saveStreak(input.cwd, out.streak);
        if (out.notice) {
          // 離題不是硬前提未知,所以閘門不會放行擋人,連問都不必問。
          // 這正是擋掉擁有者一整晚的那一段。
          speak('Forseti: ' + out.notice.text);
        }
      }
      OK();
    }

    if (others.length) {
      const who = others
        .map((o) => `${String(o.agent_id).slice(0, 8)} (${o.seconds_ago.toFixed(0)}s ago)`)
        .join(', ');
      const text =
        `Forseti: another session wrote ${file} within the last ${WINDOW_MS / 1000}s - ${who}. `
        + 'Your write may overwrite theirs. This is a lower bound: writes made through opaque shell '
        + 'commands are invisible here.';

      // 撞車是這裡面最接近「該擋」的一個,所以它要真的去問,不是自己決定。
      // 閘門要的是硬前提未知,而「可能撞車」是機率不是前提,所以它會拒絕。
      // 拒絕的時候把理由一起講出來,不要讓人以為 Forseti 沒看到。
      const g = await gate({ collision: true, other_sessions: others.length });
      if (g.allowed) {
        process.stderr.write(JSON.stringify({
          hookSpecificOutput: { permissionDecision: 'deny' },
          systemMessage: text + ' Blocked: ' + g.requires,
        }));
        process.exit(2);
      }
      speak(text);
    }
    OK();
  }

  if (input.hook_event_name === 'PostToolUse') {
    const file = input.tool_input?.file_path;
    if (file && WRITE_TOOLS.test(String(input.tool_name))) {
      Object.assign(event, evidenceFor(file));
    }
    if (typeof input.tool_response?.exit_code === 'number') {
      event.exit_code = input.tool_response.exit_code;
    }
    rt.ingest([event]);
    saveState(rt, path);
    OK();
  }

  OK();
}

main().then(OK).catch(OK);
