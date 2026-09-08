# Forseti as a Claude Code hook

This is where Forseti stops explaining what already went wrong and starts running against live work.

## What it does

**Before a write** it checks whether another session wrote that same file in the last 15 seconds. If so, the write pauses and asks, naming who and how long ago.

**Before a write, second check:** if the last several writes in a row landed outside your declared goal scope, it says so once — naming the north star and pointing out that it cannot tell a necessary detour from actually wandering off.

It never speaks on a single write. Real work touches things around the edges: configs, other people's implementations, docs, tests. Flagging each of those is the same as flagging none, because the whole thing gets switched off. One write back inside the scope resets the count to zero.

To enable it, put a `.forseti/goal.json` in the project:

```json
{
  "north_star": "Ship the auth refresh",
  "scope": ["src/auth", "test/auth"]
}
```

Without that file the check does nothing and says so. It never infers a scope — imposing the tool's own guess about what you should be working on is worse than not checking at all.

**After every tool call** it feeds the event in — coverage, evidence provenance, and the write history the check above depends on.

That is the whole surface for now. Everything else Forseti computes (drift, temperature, cost, the context register) needs input the hook interface does not carry, and shipping a check that cannot see its inputs would be theatre.

## The rule that outranks every check

A hook that gets in the way gets uninstalled, and an uninstalled guard protects nobody.

So every internal failure exits 0 and lets the work through. A crash in Forseti must never become a crash in your editor. Corrupt state file, missing module, malformed input — all of it exits 0. The only non-zero exit is a deliberate, explained decision about a real conflict, and even that returns `ask`, never `deny`: you decide, it just makes sure you know.

## Install

**Never add this to `~/.claude/settings.json`.** That file applies to every
project on this machine, not just one. On 2026-09-08 that exact mistake
blocked nine hours of unrelated work with no error and no warning - full
account in `docs/工程規格書.md` §9.2 and `.claude/README.md`.

### Into this repo itself

Add to **this repo's** `.claude/settings.json` (already committed there -
you only need this if you deleted it or are setting up a fork):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          { "type": "command", "command": "node \"$CLAUDE_PROJECT_DIR/hooks/forseti-hook.mjs\"" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          { "type": "command", "command": "node \"$CLAUDE_PROJECT_DIR/hooks/forseti-hook.mjs\"" }
        ]
      }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "node \"$CLAUDE_PROJECT_DIR/hooks/forseti-stop-hook.mjs\"" }] }
    ]
  }
}
```

Restart Claude Code. Node 22+, no dependencies to install.

### Into a different project

`insideRepo()` in `forseti-hook.mjs` only ever activates for work done
inside this Forseti repo, wherever it's cloned - pointing another project's
settings at these hook files does nothing by itself. To monitor a different
project:

```bash
node tools/install.mjs /path/to/that/project
```

This writes that project's own `.claude/settings.json` (never the user-level
one - the script refuses if the target resolves to your home directory) and
a `.forseti/config.json` with `cross_project_enabled: false`. **It does
nothing yet.** Forseti will not touch that project until you manually edit
that file and set it to `true` - installing and enabling are two separate,
both-manual steps on purpose, for the same reason as the warning above.

### Why PostToolUse is not on `*`

Measured on this machine: 156 ms per invocation, of which 130 ms is Node process startup. Forseti's own work is 26 ms. The cost is almost entirely the cost of starting a process at all, and nothing in this repo can make that smaller.

On `*`, a session with 2,300 tool calls pays about six minutes of accumulated latency. Matching only write tools cuts that to the small fraction of calls that are writes.

What you lose: read coverage — which sessions have looked at which files. The collision check does not use it (it only reads write history) and the hook does not currently expose the mechanisms that do. When it does, this trade-off should be revisited rather than inherited.

## State

One JSON file per project at `<project>/.forseti/state.json`. Each hook invocation is a fresh process with no memory of the last one, so the file is how the check on your next write knows what happened on the previous one.

It keeps the last 10 minutes of events, capped at 2000, because collision detection only looks at the last few seconds and a state file should not grow without bound. Full history is the transcript's job, not this file's.

Add `.forseti/` to `.gitignore`.

## What it cannot see

Writes made through opaque shell commands. `python3 - <<'PY'` with `open(p,'w')` inside carries no file path on the command line, and roughly half of real shell commands are opaque to static analysis. The hook says so in its own warning rather than implying its silence means safety.

## Watching it

```bash
node tools/dashboard.mjs /path/to/your/project
```

Opens a read-only local dashboard at `http://127.0.0.1:7777`. It reads the state file and nothing else — it never writes, and never sends anything to the observed session, because §9.1 of the specification forbids continuously interrogating what you are measuring.

It follows the spec's §8.1 quiet rule literally. HEALTHY and WATCH show one line and a dot. A cause appears only at ELEVATED, a diagnosis card only at HIGH, a rescue card only at CRITICAL. A dashboard that flashes while everything is fine gets closed, and a closed dashboard protects nobody.

The header always shows what fraction of the weighted signals actually had data behind them. A confident-looking 0.55 computed from 22% of the signals is a different thing from the same number computed from all of them, and the interface refuses to let those look alike.

## Verifying it works

The `cwd` in the example below must be inside this repo - `insideRepo()`
exits 0 without doing anything for any path outside it, silently. A path
like `/tmp/fh` will make this example print nothing and exit 0 on both
calls, which looks like success but has verified nothing.

```bash
FH=$(mktemp -d "$(pwd)/.tmp-verify-XXXXXX") && \
echo "{\"hook_event_name\":\"PostToolUse\",\"session_id\":\"A\",\"cwd\":\"$FH\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$FH/x.js\"}}" | node hooks/forseti-hook.mjs && \
echo "{\"hook_event_name\":\"PreToolUse\",\"session_id\":\"B\",\"cwd\":\"$FH\",\"tool_name\":\"Write\",\"tool_input\":{\"file_path\":\"$FH/x.js\"}}" | node hooks/forseti-hook.mjs; \
rm -rf "$FH"
```

The second call should exit 0 and print a `systemMessage` naming session A -
not exit 2. As of the 2026-09-08 fix (§9.2 of `docs/工程規格書.md`), a
collision only reaches `exit(2)` if `intervention.js`'s `canIntervene`
grants `BLOCK_HIGH_RISK`, which requires a hard prerequisite to be unknown
or refuted. A same-file collision alone never supplies that - it's a
probability, not a missing prerequisite - so this call speaks and lets the
write through every time. That is intentional, not a bug: see `hooks/forseti-hook.mjs`'s
own comment on the incident this replaced. This file said "should exit 2"
for a while after that fix landed and nobody had re-run this example to
notice it no longer matched.
