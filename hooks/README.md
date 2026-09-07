# Forseti as a Claude Code hook

This is where Forseti stops explaining what already went wrong and starts running against live work.

## What it does

**Before a write** it checks whether another session wrote that same file in the last 15 seconds. If so, the write pauses and asks, naming who and how long ago.

**After every tool call** it feeds the event in — coverage, evidence provenance, and the write history the check above depends on.

That is the whole surface for now. Everything else Forseti computes (drift, temperature, cost, the context register) needs input the hook interface does not carry, and shipping a check that cannot see its inputs would be theatre.

## The rule that outranks every check

A hook that gets in the way gets uninstalled, and an uninstalled guard protects nobody.

So every internal failure exits 0 and lets the work through. A crash in Forseti must never become a crash in your editor. Corrupt state file, missing module, malformed input — all of it exits 0. The only non-zero exit is a deliberate, explained decision about a real conflict, and even that returns `ask`, never `deny`: you decide, it just makes sure you know.

## Install

Add to `~/.claude/settings.json` (or a project's `.claude/settings.json`):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          { "type": "command", "command": "node /absolute/path/to/forseti/hooks/forseti-hook.mjs" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          { "type": "command", "command": "node /absolute/path/to/forseti/hooks/forseti-hook.mjs" }
        ]
      }
    ]
  }
}
```

Restart Claude Code. Node 22+, no dependencies to install.

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

```bash
rm -rf /tmp/fh && \
echo '{"hook_event_name":"PostToolUse","session_id":"A","cwd":"/tmp/fh","tool_name":"Write","tool_input":{"file_path":"/tmp/x.js"}}' | node hooks/forseti-hook.mjs && \
echo '{"hook_event_name":"PreToolUse","session_id":"B","cwd":"/tmp/fh","tool_name":"Write","tool_input":{"file_path":"/tmp/x.js"}}' | node hooks/forseti-hook.mjs
```

The second call should exit 2 and print a message naming session A.
