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
 * editor. The only non-zero exit is a deliberate, explained decision
 * about a real conflict.
 *
 * ── What it does ────────────────────────────────────────────────────
 *
 *   PostToolUse   feed the event in; update coverage, evidence, scopes
 *   PreToolUse    on a write, check whether someone else holds that file
 *
 * State lives in one JSON file per project, because each hook invocation
 * is a fresh process with no memory of the last one.
 */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OK = () => process.exit(0);

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

function stateFile(cwd) {
  const root = process.env.CLAUDE_PROJECT_DIR || cwd || process.cwd();
  return join(root, '.forseti', 'state.json');
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
 * 多久算「同時」。
 * 【15 秒沒有實測校準】,跟 admission.js 用同一個值,理由也一樣:
 * 它是個保守的起點,不是量出來的。太寬會一直誤攔,太窄會漏掉真的撞車。
 */
const WINDOW_MS = 15_000;

async function main() {
  const input = readStdin();
  if (!input) OK();

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

    if (others.length) {
      const who = others
        .map((o) => `${String(o.agent_id).slice(0, 8)} (${o.seconds_ago.toFixed(0)}s ago)`)
        .join(', ');
      process.stderr.write(JSON.stringify({
        hookSpecificOutput: { permissionDecision: 'ask' },
        systemMessage:
          `Forseti: another session wrote ${file} within the last ${WINDOW_MS / 1000}s - ${who}. ` +
          'Your write may overwrite theirs. This is a lower bound: writes made through opaque shell ' +
          'commands are invisible here.',
      }));
      process.exit(2);
    }
    OK();
  }

  if (input.hook_event_name === 'PostToolUse') {
    rt.ingest([event]);
    saveState(rt, path);
    OK();
  }

  OK();
}

main().then(OK).catch(OK);
