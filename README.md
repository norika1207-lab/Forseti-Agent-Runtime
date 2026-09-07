<div align="center">

# Forseti Agent Runtime

**Reliability primitives for when several AI agents work on the same codebase.**

Zero dependencies. Pure functions. No framework, no daemon, no lock-in.

`npm test` → 195 assertions, all green.

</div>

---

## The problem

Multi-agent AI coding breaks in ways single-agent coding does not.

Two agents edit the same file and silently overwrite each other. An agent claims it shipped something and changed nothing on disk. Your main conversation fills up, compacts, and the thing you spent two hours briefing is gone. You hand work from one agent to another and have to guess how much background to repeat.

None of these are model problems. They are runtime problems, and they need runtime answers.

Forseti is six such answers, each small enough to adopt on its own.

---

## What's in here

### `capture.js` — the intake

Five of the modules below are pure functions waiting for someone to feed them. This is the feeding hatch. It reads nothing and watches nothing: the host hands it raw tool-call events, and it normalises them into one neutral shape that all five can eat.

Without this layer every host writes five conversions by hand, and gets one of them subtly wrong with nothing to catch it.

Two rules in here were paid for in production, not derived from a spec:

**An agent's self-reported identity is never trusted.** Three ways of identifying who did what were tried live, and all three failed: aliases drift, self-reported identity is inherited wholesale by forked subprocesses, and the UUID that looks most authoritative identifies the *transcript*, not the actor. Routing on self-reported identity misdelivered four times, twice into completely unrelated sessions. The only thing that held up was what the host itself stamped on the event: a timestamp, a tool call, a file. So the adapter reads `attributed_agent` and ignores anything the payload claims about itself. No stamp means the event goes to `skipped` — never to a guess.

**Stable id and display name are separate fields, and routing may only use the stable one.** In production the rules stored an internal id while the panel showed a user-chosen name. Rename something and the two silently decouple; have two windows share a name and you cannot even tell where a message went. The user's word for it was "it sends things to the wrong place." `labelDrift()` and `ambiguousLabels()` surface both conditions so the host can fix the UI before anyone notices the misdelivery.

Nothing is dropped silently. Every skipped event is counted with a reason, and `captureHealth()` reports the capture rate — because the quality of all five mechanisms below is capped by this number, and a capture layer that quietly loses events is the hardest failure to find: everything still runs, every answer is a little wrong, and nothing turns red.

### `cost.js` — what a change actually costs

Every dependency tool answers *"this change affects 87 files."* That number is close to useless. Affecting 200 files that all have tests is safer than affecting 12 that are naked.

`computeCostVector()` returns five dimensions and refuses to collapse them into a score:

```js
{
  d1_count: 12,          // direct dependents
  d2_count: 87,          // transitive
  uncovered_d1: 47,      // ...of the direct ones, how many have no test
  cross_modules: 5,      // how many subsystems get touched
  live_conflicts: 3,     // how many are being edited by another agent RIGHT NOW
  coverage_source: 'LCOV',
  resolution_rate: 0.94,
  is_lower_bound: true
}
```

`live_conflicts` is the one no existing tool can produce. CodeSee, Sourcetrail and GitHub's dependency graph all have the static half. None of them have a world where agents are autonomously editing code, so none of them can tell you *"three of the files you're about to break are open on someone else's desk."*

**Honesty clauses, enforced by tests, not comments.** No coverage report means `uncovered_d1` is `null` and `coverage_source` is `NONE` — never a heuristic guess. `is_lower_bound` is always true, because dynamic imports and string-built paths are invisible to static analysis. Unresolved imports are counted and queryable, never silently swallowed.

### `capsule.js` — a cash register for context

Your main session's context is a finite, non-refundable resource, and right now it's invisible. You guess how much is left, and when you guess wrong you explain yourself from scratch.

This module makes every inbound payload pay a toll:

```js
previewCapsule(capsule, budget, contract)
// → { token_cost, budget_before, budget_after, would_trigger_compact }
```

Nothing raw reaches the main session. Agent output gets wrapped in a capsule with a price tag, and cheap capsules under a configurable threshold auto-clear so the register doesn't become the new bottleneck.

`manualReviewRate()` tells you what fraction of capsules currently need a human, so that threshold gets tuned with data instead of vibes.

Token counts carry their provenance: `PROVIDER_REPORTED` or `ESTIMATED`. An estimate never gets dressed up as a fact.

### `admission.js` — stop the collision before it happens

Two agents writing the same file is the most expensive failure in multi-agent coding, and today you find out from the git diff.

`decideAdmission()` runs at dispatch time and returns one of four verdicts:

| Verdict | Meaning |
|---|---|
| `ALLOW` | No overlap with any active scope |
| `NARROW` | Overlap avoidable — here's a smaller scope |
| `SERIALIZE` | Not avoidable, but it can wait its turn |
| `BLOCK` | Needs a human call |

The design note that matters: **a rendered conflict is a documentary about a disaster. An intercepted conflict is a product.**

Two subtleties are baked in. Intersection uses *declared write sets*, not transitive closure — using the dependency graph makes every barrel file a false positive. And files in the top N% by import count are exempt, because without that exemption the intersection is never empty and the whole mechanism cries wolf forever.

Advisory locks carry a TTL, so a crashed agent can't deadlock the project.

### `coverage.js` — what each session actually knows

A quantity that didn't exist five years ago: which files a live session has seen, and how deeply.

```js
handoffDelta(from, to)
// → { need_briefing: [...], saved_files: [...], saved_ratio: 0.5 }
```

Four things fall out of it:

- **Dispatch** — route work to whoever's context is already warm on those files
- **Deduplication** — two agents with 90% overlap means you're paying twice to read the same code
- **Handoff** — how much background to repeat stops being a judgment call and becomes set subtraction
- **Survival** — compute in advance which task will eat the most of your main session

Depth has four levels (`MENTIONED` → `READ_PARTIAL` → `READ_FULL` → `EDITED`) because a file that merely appeared in a grep result is not a file the next agent can skip reading.

`is_upper_bound` is permanently true and cannot be turned off: a session that compacted remembers less than it read, and this module has no way to know how much less.

### `handoff.js` — stop being the wire

Agent A finishes. Its output needs to reach Agent B. Only you can carry it. Four agents running at full speed all bottleneck on whether you click a button.

This module turns that one-time click into a standing rule:

```js
planHandoff({ fromNode: 'PM', edges, chain: ['PM'] })
// → { dispatch: [...], gates: [...], blocked: [...] }
```

Three edge types: send straight through, hold at a gate for a human, or send and let it come back once.

**The loop guard is not optional.** Every rule-triggered run carries a chain of nodes it has passed through. Before forwarding, three checks: is the target already in the chain, is the chain too long, is the target already busy. Blocked hops are always counted, never silently dropped.

The roundtrip counter has a bug in it that only a real run could find. The obvious implementation counts how many times the target appears in the chain — but the origin is in the chain too, so `A→B→A→B` runs one hop further than "at most one round trip" claims, spending real money on that extra hop. Counting *transitions* instead of *appearances* fixes it. The reason is written into the source, and a test asserts that explanation is still there.

One more thing that only showed up in production: **if the upstream turn produced nothing actionable, no edge fires.** A connectivity test that answers "ack" used to get auto-forwarded, and the downstream agent would reply "there is no executable task here" — twice in a row, both sides burning tokens on nothing.

`automationRate()` is the one number that matters: how much of your handoff traffic is rules versus your own hands. It should climb. If it doesn't, this mechanism isn't earning its keep.

---

## Design rules

These are enforced by the test suite. Deleting an honesty annotation makes a test go red.

**Never synthesise a single risk score.** Collapsing five actionable dimensions into one number destroys the only thing that made them actionable.

**Missing data is `null`, never `0`.** No overlap data is not the same as no overlap. No coverage report is not the same as no coverage.

**Unvalidated constants say so in the source.** The 15-second conflict window, the lock TTL and the turn-gap threshold are documented as *not empirically calibrated*, and a test asserts each disclaimer still exists.

**Every returned object is frozen.** State changes go through the API or not at all.

**Zero dependencies.** Five of the six modules import nothing at all. The sixth imports one sibling.

---

## Install

```bash
git clone https://github.com/norika1207-lab/Forseti-Agent-Runtime
cd Forseti-Agent-Runtime
npm test
```

No install step, no build step, no `node_modules`. Requires Node 22+.

```js
import { computeCostVector } from './src/cost.js';
import { decideAdmission }   from './src/admission.js';
import { handoffDelta }      from './src/coverage.js';
import { previewCapsule }    from './src/capsule.js';
import { planHandoff }       from './src/handoff.js';
import { normalizeStream }   from './src/capture.js';
```

Each module works standalone. Adopt one, ignore the rest.

---

## Status

Core logic is complete and verified. Nothing is wired to a host yet.

| Module | Assertions | State |
|---|---|---|
| `capture.js` | 46 | Verified |
| `cost.js` | 16 | Verified |
| `capsule.js` | 18 | Verified |
| `admission.js` | 34 | Verified |
| `coverage.js` | 30 | Verified |
| `handoff.js` | 38 | Verified |
| end-to-end | 13 | Verified |

**Honest about what's missing.** The host still has to do two things this repo does not: persist state across restarts, and call these functions at dispatch time. Three constants (`cost.js` sub-100ms on a 20k-node graph, `admission.js` 15-second window, `capture.js` 30-second turn gap) are documented as unmeasured rather than claimed.

`handoff.js` and `capture.js` carry logic that ran in production before being extracted. Nine of handoff's assertions are regression baselines from that environment.

**The end-to-end suite earns its keep.** Each module's own tests only prove that the part is correct in isolation. The first run of the integration suite found a real hole in `admission.js`: conflicts were only detected against files already written, or against globs expanded with a full file list the host rarely has. But at dispatch time — the exact moment the mechanism exists for — nothing has been written yet. Two agents declaring the same file and neither having started was waved straight through. The conflict only became visible once someone wrote to disk, by which point the module had degraded into the `git diff` it was built to replace. Fixed by comparing declared sets directly, with a separate `is_complete` flag so "no conflict found" is never reported as "no conflict."

---

## Why "Forseti"

The Norse god who settles disputes. Everyone who comes before him leaves reconciled.

---

## License

MIT
