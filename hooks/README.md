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

## The Event Ledger writer (`event-ledger.mjs`)

Since phase 1, `forseti-hook.mjs` also records every event it sees into the
Event Ledger, the append-only record of what the AI and the runtime actually
did. `event-ledger.mjs` is the write side of that ledger and nothing else: it
classifies the hook input into one of the canonical v5.0 §6.2 event types
(PreToolUse becomes `TOOL_CALL`, Stop becomes `MODEL_OUTPUT`, PostToolUse
becomes `FILE_WRITE` / `FILE_READ` / `TOOL_RESULT` depending on the tool) and
appends one line per event, raw and normalized representations together.

**Where it writes.** `<project>/.forseti/event_ledger.jsonl`, one JSON line
per event. Any single payload field over 64 KB is stored as
`.forseti/raw_payloads/<sha256>.json` and referenced from the line instead of
inlined, so the ledger stays readable with ordinary text tools. Tests point
the writer at a sandbox via `FORSETI_EVENT_LEDGER_DIR` (the comment at that
env var in `forseti-hook.mjs` records how a test once wrote fake events into
the real ledger, and why the fix was an escape hatch rather than cleanup).
Reading, replay and indexing live on the Python side in
`apps/forseti-cli/event_ledger.py`; its SQLite index is disposable and gets
rebuilt from the JSONL file, which is the only source of truth.

**Why the write side does not go through Python.** The read side is Python,
so the obvious move was to shell out to it. It was measured instead
(2026-09-10, numbers in this file's header): starting a Python interpreter
plus import plus append is p95 140.8 ms end to end, against the phase-1
hot-path budget of p95 < 50 ms (`docs/build-plan.md:330`). The append itself
is 0.173 ms; nearly the whole cost is interpreter startup, not writing. The
hook has already paid Node's startup, so appending from Node is close to
free. This is what "the source of truth is a file, not a database" buys: the
writer does not have to share a language with the reader. The obligation that
creates instead: `canonicalJson()` here must produce byte-identical output to
Python's `canonical_json()` (compared 2026-09-10 on samples with Chinese,
nesting, null, floats, booleans), and the event types emitted here must stay
inside the Python `TYPES` whitelist, or reindexing rejects the line. That
rejection is deliberate: better a refused event than an unrecognized type
lying quietly in the record.

**Same rule as every check above:** no function in `event-ledger.mjs` throws.
Can't classify, can't stash the payload, can't append: it returns null and
the work goes through. A ledger missing a few lines beats an editor blocked
by bookkeeping, which is the 2026-09-08 incident again, and the reason the
whole call in `forseti-hook.mjs` sits inside one try/catch, import included.

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
