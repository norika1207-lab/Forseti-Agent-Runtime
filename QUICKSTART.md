# Five minutes

No install step. Node 22+, zero dependencies.

```bash
git clone https://github.com/norika1207-lab/Forseti-Agent-Runtime
cd Forseti-Agent-Runtime
npm test
```

That should print a few hundred green assertions and `全部模組通過`. If it does, everything below will work.

## 1. See what it does, on synthetic data (30 seconds)

```bash
node example/host.mjs
```

Walks a whole session lifecycle and prints what each step returns: a write blocked before it happened, a handoff computed, a restart where a scope held by a possibly-dead agent keeps blocking until you confirm.

## 2. Point it at your own transcripts (2 minutes)

If you use Claude Code, you already have the data.

```bash
node tools/analyze-transcripts.mjs ~/.claude/projects/<your-project>
```

Prints your capture rate, how many of your shell commands are opaque to static analysis, whether two of your sessions ever wrote the same file at the same moment, and which of them are paying twice to read the same code.

Everything stays local. Nothing is uploaded.

```bash
node tools/self-audit.mjs ~/.claude/projects/<your-project>/<session>.jsonl
```

Lists the things that were declared and then never done. Expect this one to be uncomfortable.

## 3. Fit the constants to your own work (1 minute)

```bash
node tools/calibrate.mjs ~/.claude/projects/<your-project>
```

Every threshold in this repo is calibrated against one person's 130 transcripts. Yours will differ. This prints the distributions so you can replace them.

## 4. Run it live (2 minutes)

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "Write|Edit|MultiEdit|NotebookEdit",
      "hooks": [{ "type": "command", "command": "node /abs/path/to/Forseti-Agent-Runtime/hooks/forseti-hook.mjs" }]
    }],
    "PostToolUse": [{
      "matcher": "Write|Edit|MultiEdit|NotebookEdit",
      "hooks": [{ "type": "command", "command": "node /abs/path/to/Forseti-Agent-Runtime/hooks/forseti-hook.mjs" }]
    }]
  }
}
```

Restart Claude Code. Now a write pauses if another session touched that same file in the last 15 seconds.

Cost: 156 ms per write, of which 130 ms is Node startup. Add `.forseti/` to your `.gitignore`.

To also get told when you have drifted off your own stated goal, put this in the project:

```json
// .forseti/goal.json
{
  "north_star": "Ship the auth refresh",
  "scope": ["src/auth", "test/auth"]
}
```

It stays silent until several writes in a row land outside that scope, and one write back inside resets the count.

## 5. Watch it (30 seconds)

```bash
node tools/dashboard.mjs /path/to/your/project
```

Read-only, at `http://127.0.0.1:7777`. Quiet by default — a cause line appears only at ELEVATED, a diagnosis card only at HIGH.

---

## What it will not do

It will not tell you an agent is lying. Five separate attempts at that failed against real labelled data, and the negative result is documented in the README rather than buried.

It will not see writes made through opaque shell commands. Roughly half of real shell commands are opaque to static analysis, and it says so in its own warnings rather than letting silence imply safety.

It will not fill in a number it does not have. Everywhere a measurement is missing you get `null` and a sentence explaining what is missing — never a zero standing in for "fine".
