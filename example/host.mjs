// A complete host integration, start to finish. Run it:
//
//   node example/host.mjs
//
// Everything a host has to do is in here. Four calls carry the weight:
// ingest, requestWrite, completeTurn, save. Nothing below reaches into
// a module directly - if you find yourself needing to, that is worth
// reporting as a gap in the runtime surface.
import { createRuntime } from '../src/runtime.js';
import { createEdge } from '../src/handoff.js';

const forseti = createRuntime();
const line = (s) => console.log('\n\x1b[1m' + s + '\x1b[0m');

// ---------------------------------------------------------------------------
// 1. Declare your handoff rules once. Cycles are rejected at build time
//    rather than caught at run time, and a cyclic set is rejected whole -
//    a half-applied rule graph is harder to debug than none.
// ---------------------------------------------------------------------------
line('1. Wiring handoff rules');
const wired = forseti.setEdges([
  createEdge({ id: 'dev-to-review', from: 'dev', to: 'review' }),
  createEdge({ id: 'review-to-dev', from: 'review', to: 'dev', kind: 'roundtrip' }),
]);
console.log('   applied:', wired.applied, '| cycles found:', wired.cycles.length);

// ---------------------------------------------------------------------------
// 2. Ask before dispatching. This is the only place a collision can be
//    stopped before it happens - everywhere else you are reading history.
// ---------------------------------------------------------------------------
line('2. Admission control at dispatch time');
const first = forseti.requestWrite({
  agent_id: 'dev', task_id: 'add-auth', declared: ['src/auth.js', 'src/routes.js'],
});
console.log('   dev asking for auth.js + routes.js →', first.decision);
forseti.openScope({ agent_id: 'dev', task_id: 'add-auth', declared: ['src/auth.js', 'src/routes.js'] });

const second = forseti.requestWrite({
  agent_id: 'review', task_id: 'refactor-routes', declared: ['src/routes.js'],
});
console.log('   review asking for the same routes.js →', second.decision);
console.log('   reason:', second.reason);
console.log('   note: neither agent has written a byte yet. That is the point.');

// ---------------------------------------------------------------------------
// 3. Forward tool-call events as they happen. Your adapter needs to stamp
//    each event with who did it - the runtime will not accept an agent's
//    own claim about its identity, and unattributed events are skipped
//    rather than guessed at.
// ---------------------------------------------------------------------------
line('3. Feeding the event stream');
const t = Date.now();
const report = forseti.ingest([
  { attributed_agent: 'dev', agent_label: 'Dev', name: 'Read', at: t, input: { file_path: 'src/routes.js' } },
  { attributed_agent: 'dev', agent_label: 'Dev', name: 'Read', at: t + 900, input: { file_path: 'src/db.js' } },
  { attributed_agent: 'dev', agent_label: 'Dev', name: 'Write', at: t + 2000, input: { file_path: 'src/auth.js' } },
  { attributed_agent: 'dev', agent_label: 'Dev', name: 'Edit', at: t + 3000, input: { file_path: 'src/routes.js' } },

  { attributed_agent: 'review', agent_label: 'Review', name: 'Read', at: t + 90_000, input: { file_path: 'src/db.js' } },

  // No attribution stamp: skipped, and counted, never silently dropped.
  { name: 'Edit', at: t + 4000, input: { file_path: 'src/ghost.js' } },
]);
console.log('   accepted:', report.accepted, '| skipped:', report.skipped, report.skipped_by_reason);

// ---------------------------------------------------------------------------
// 4. Tell it when a turn finishes. You get back a plan, not an action -
//    the runtime never sends anything itself.
// ---------------------------------------------------------------------------
line('4. Turn complete → where does it go');
const plan = forseti.completeTurn({ agent_id: 'dev' });
for (const d of plan.dispatch) console.log('   dispatch →', d.to, '| chain:', d.chain.join(' → '));
for (const p of plan.packets) {
  console.log('   brief them on:', p.briefing_files);
  console.log('   already known, skip:', p.saved_files, '(' + Math.round((p.saved_ratio ?? 0) * 100) + '% saved)');
}
console.log('   these are plans. Sending them is your job, not the runtime\'s.');

// ---------------------------------------------------------------------------
// 5. Closing a scope reports whether the agent wrote outside what it declared.
// ---------------------------------------------------------------------------
line('5. Closing the scope');
console.log('  ', forseti.closeScope('add-auth'));

// review picks up the work and is still mid-flight when we save below.
forseti.openScope({ agent_id: 'review', task_id: 'refactor-routes', declared: ['src/routes.js'] });
console.log('   review is now holding routes.js, and has not finished');

// ---------------------------------------------------------------------------
// 6. Status tells you what it knows AND what it does not.
// ---------------------------------------------------------------------------
line('6. Status, including the gaps');
const s = forseti.status();
console.log('   capture rate:', s.capture.capture_rate, '| automation rate:', s.automation_rate);
console.log('   known agents:', s.known_agents.join(', '));
for (const u of s.unavailable) console.log('   ⚠', u);

// ---------------------------------------------------------------------------
// 7. Persist. One string. Put it wherever you like.
// ---------------------------------------------------------------------------
line('7. Save and restore');
const saved = forseti.save();
console.log('   snapshot size:', saved.length, 'bytes');

const restarted = createRuntime();
const restored = restarted.restore(saved);
console.log('   automation rate survived:', restarted.status().automation_rate);
console.log('   scopes needing your confirmation:', restored.stale_scopes.length,
            '→', restored.stale_scopes.map((s) => s.agent_id + '/' + s.task_id).join(', '));
for (const w of restored.warnings) console.log('   ⚠', w);

// Until you confirm, a stale scope keeps blocking. That is deliberate:
// the conservative failure costs less than two agents in one file.
const blocked = restarted.requestWrite({
  agent_id: 'other', task_id: 'hotfix', declared: ['src/routes.js'],
});
console.log('   someone else asking for routes.js right after restart →', blocked.decision);
console.log();
