#!/usr/bin/env node
/**
 * Run Forseti over your own Claude Code transcripts.
 *
 *   node tools/analyze-transcripts.mjs ~/.claude/projects/<your-project-dir>
 *
 * Everything stays on your machine. Nothing is uploaded, nothing is written.
 * File paths from your own transcripts are printed to your own terminal;
 * pipe it to a file if you would rather not have them on screen.
 *
 * What you get:
 *   - what fraction of your tool calls this can actually see
 *   - how many of your shell commands are opaque to static analysis
 *   - whether two of your sessions ever wrote the same file at the same time
 *   - which of your sessions duplicate each other's reading
 */
import { readFileSync, readdirSync } from 'node:fs';
import { parseTranscripts } from '../adapters/claude-code.mjs';
import { normalizeStream, coverageDepthOf, toWriteEvents, captureHealth, groupByAgent } from '../src/capture.js';
import { coverageFromEvents, overlapRatio, handoffDelta } from '../src/coverage.js';
import { windowConflicts } from '../src/admission.js';
import { expandBashEvent } from '../src/shell.js';

const dir = process.argv[2];
if (!dir) {
  console.error('usage: node tools/analyze-transcripts.mjs <transcript-directory>');
  console.error('       (typically ~/.claude/projects/<project>)');
  process.exit(1);
}

const files = readdirSync(dir).filter((f) => f.endsWith('.jsonl'));
if (!files.length) {
  console.error(`No .jsonl transcripts found in ${dir}`);
  process.exit(1);
}

const bold = (s) => '\x1b[1m' + s + '\x1b[0m';
const num = (n) => n.toLocaleString();

const parsed = parseTranscripts(
  files.map((f) => ({ name: f.slice(0, 8), text: readFileSync(dir + '/' + f, 'utf8') })),
);

console.log(bold('\nCapture'));
console.log(`  ${files.length} transcripts, ${num(parsed.lines)} lines, ${num(parsed.events.length)} tool calls`);
for (const n of parsed.notes) console.log('  ! ' + n);

let raw = [];
let opaque = 0;
let bash = 0;
for (const e of parsed.events) {
  if (e.name === 'Bash') {
    bash += 1;
    const x = expandBashEvent(e);
    opaque += x.opaque_commands;
    raw.push(...x.events);
  } else {
    raw.push(e);
  }
}

const norm = normalizeStream(raw);
const health = captureHealth(norm);
console.log(`\n  shell commands: ${num(bash)}, of which ${num(opaque)} are opaque to static analysis` +
  (bash ? ` (${(opaque / bash * 100).toFixed(0)}%)` : ''));
console.log(`  usable events: ${num(norm.events.length)}, dropped: ${num(norm.skipped)}`);
console.log(bold(`  capture rate: ${(health.capture_rate * 100).toFixed(1)}%`) +
  '  <- the ceiling on everything below');

const byAgent = groupByAgent(norm.events);
console.log(`  distinct executors: ${byAgent.size}`);

console.log(bold('\nCollisions (two executors writing one file within 15s)'));
const writes = toWriteEvents(norm.events);
const conflicts = windowConflicts(writes);
console.log(`  ${num(writes.length)} writes examined, ${conflicts.length} collision(s)`);
const byFile = new Map();
for (const c of conflicts) byFile.set(c.file_path, (byFile.get(c.file_path) ?? 0) + 1);
for (const [f, n] of [...byFile].sort((a, b) => b[1] - a[1]).slice(0, 10)) {
  console.log(`  ${String(n).padStart(3)}x  ${f}`);
}
if (!conflicts.length) {
  console.log('  None found. Note this is a lower bound: opaque shell commands are invisible here.');
}

console.log(bold('\nOverlap (who is reading the same code twice)'));
const covs = [];
for (const [id, evs] of byAgent) {
  if (evs.length < 30) continue;
  covs.push(coverageFromEvents({ session_id: id, agent_id: id, events: evs, toolDepth: coverageDepthOf }));
}
console.log(`  ${covs.length} executors with 30+ events`);
const pairs = [];
for (let i = 0; i < covs.length; i += 1) {
  for (let j = i + 1; j < covs.length; j += 1) {
    const r = overlapRatio(covs[i], covs[j]);
    if (r > 0.3) pairs.push({ a: covs[i], b: covs[j], r });
  }
}
pairs.sort((x, y) => y.r - x.r);
if (pairs.length) {
  for (const p of pairs.slice(0, 8)) {
    const d = handoffDelta(p.a, p.b);
    console.log(`  ${(p.r * 100).toFixed(0)}%  ${p.a.agent_id.slice(0, 8)} <-> ${p.b.agent_id.slice(0, 8)}` +
      `  handoff could skip ${d.saved_files.length}/${d.total_from} files`);
  }
} else {
  console.log('  No pair above 30%. Your sessions work on largely separate code.');
}
console.log();
