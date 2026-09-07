<div align="center">

# Forseti Agent Runtime

**Reliability primitives for when several AI agents work on the same codebase.**

Zero dependencies. Pure functions. No framework, no daemon, no lock-in.

`npm test` → 92 assertions, all green.

</div>

---

## The problem

Multi-agent AI coding breaks in ways single-agent coding does not.

Two agents edit the same file and silently overwrite each other. An agent claims it shipped something and changed nothing on disk. Your main conversation fills up, compacts, and the thing you spent two hours briefing is gone. You hand work from one agent to another and have to guess how much background to repeat.

None of these are model problems. They are runtime problems, and they need runtime answers.

Forseti is four such answers, each small enough to adopt on its own.

---

## What's in here

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

---

## Design rules

These are enforced by the test suite. Deleting an honesty annotation makes a test go red.

**Never synthesise a single risk score.** Collapsing five actionable dimensions into one number destroys the only thing that made them actionable.

**Missing data is `null`, never `0`.** No overlap data is not the same as no overlap. No coverage report is not the same as no coverage.

**Unvalidated constants say so in the source.** The 15-second conflict window and the lock TTL are documented as *not empirically calibrated*, and a test asserts that disclaimer still exists.

**Every returned object is frozen.** State changes go through the API or not at all.

**Zero dependencies.** Three of the four modules import nothing at all. The fourth imports one sibling.

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
```

Each module works standalone. Adopt one, ignore the rest.

---

## Status

Core logic is complete and verified. Nothing is wired to a host yet.

| Module | Assertions | State |
|---|---|---|
| `cost.js` | 16 | Verified |
| `capsule.js` | 18 | Verified |
| `admission.js` | 28 | Verified |
| `coverage.js` | 30 | Verified |

**Honest about what's missing.** These are pure functions with no input source. Nothing yet feeds them a live event stream, nothing persists their state across restarts, and nothing calls them at dispatch time. Two constants (`cost.js` sub-100ms on a 20k-node graph, `admission.js` 15-second window) are documented as unmeasured rather than claimed.

A fifth mechanism, persistent handoff rules, is specified but not yet extracted into this repo.

---

## Why "Forseti"

The Norse god who settles disputes. Everyone who comes before him leaves reconciled.

---

## License

MIT
