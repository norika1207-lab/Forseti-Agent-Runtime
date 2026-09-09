FORSETI

AI-First Development Engineering Book

System Architecture + Execution Contract + Phase-by-Phase Build Protocol

Version 1.0 | 2026-09-07

| Document property | Value |
|---|---|
| Primary reader | An AI coding agent that must implement Forseti without inventing requirements or drifting from the North Star. |
| Secondary reader | Human owner / architect / reviewer. |
| Implementation style | AI-first, evidence-first, local-first, incremental, phase-gated. |
| Core philosophy | A thermometer, not a nagging guard: observe quietly; intervene only when the collaboration or runtime is demonstrably degrading. |
| System mission | Protect human agency, collaboration health, runtime continuity, evidence integrity, and recoverable execution across long-running AI work. |
| Architecture baseline | Forseti Agent Runtime System Architecture & Engineering Specification v5.0, included as Appendix A. |

This book is intentionally written as an executable engineering contract. It is not a brainstorming document. Every phase has a bounded objective, exact artifacts, acceptance tests, evidence requirements, prohibited behaviors, and a handoff contract. An AI may not advance because the prose "looks done"; it advances only when the exit gate is evidenced.

## 0. How an AI Must Use This Book

The AI implementing Forseti must treat this document as the project control plane. It may propose an ADR when reality forces a change, but it may not silently reinterpret the North Star, merge phases, replace required evidence with self-report, or optimize features that have not passed their prerequisite gate.

### 0.1 Mandatory startup protocol for every new session

1. Read Sections 1 through 7 before changing code.
1. Read the current PHASE_STATUS.md, DECISION_LEDGER.md, BLOCKERS.md, and the latest HANDOFF.md.
1. State the North Star in one paragraph and identify the active phase.
1. State the exact phase exit gate and list the evidence already present versus missing.
1. Inspect the repository and runtime before claiming current implementation state.
1. Execute only work that advances the active phase or removes a verified blocker.
1. Before ending, write durable artifacts and the minimum handoff contract; prose in chat is not durable project state.

### 0.2 Non-negotiable AI behavior contract

| Rule | Required behavior |
|---|---|
| AI-01 North Star | Never change the product objective implicitly. Any change requires an ADR and owner acceptance. |
| AI-02 One active phase | Do not implement later-phase features because they are interesting. Later phases may be stubbed only when required by the active phase interface. |
| AI-03 Evidence over self-report | "I implemented it" is not evidence. Show tests, hashes, file diffs, process state, fixture results, or equivalent deterministic proof. |
| AI-04 No fake completion | WRITTEN, RUNNING, COMPLETED, VERIFIED, and RELEASABLE are distinct. Never skip states. |
| AI-05 Do not hide uncertainty | Unknown prerequisites remain UNKNOWN/CONDITIONAL. Do not convert absence of prohibition into permission. |
| AI-06 Corrections revoke stale authority | A user correction or stronger counter-evidence must invalidate dependent hypotheses/plans before further execution. |
| AI-07 No plan salvage after core invalidation | If a required asset, permission, core mechanism, target environment, or North Star is invalidated, replan from verified reality. Do not cosmetically patch the old plan. |
| AI-08 Resource discipline | If expensive retries produce no verified progress, freeze the strategy and replan instead of consuming more tokens/time. |
| AI-09 Do not make the human QA | Before presenting completion, run the tests and checks that the AI itself can run. Human review is not a substitute for ordinary QA. |
| AI-10 Preserve continuity | Never rely on one conversational context as the only location of important state, rationale, corrections, or next actions. |
| AI-11 Minimal interruption | Forseti must default to observation. Product reliability is a failure if ordinary development becomes slower or noisier than the failures it prevents. |
| AI-12 No hidden-reasoning dependency | Forseti must work without access to private chain-of-thought. Use observable events, outputs, tool traces, corrections, artifacts, and explicit decisions. |

### 0.3 Standard phase execution loop

READ CURRENT STATE

-> VERIFY REPOSITORY / RUNTIME REALITY

-> RESTATE ACTIVE PHASE + EXIT GATE

-> CHOOSE SMALLEST UNBLOCKED TASK

-> IMPLEMENT

-> RUN TEST / FIXTURE / PROBE

-> RECORD EVIDENCE

-> UPDATE PHASE STATUS

-> IF GATE PASSES: OWNER/CONTRACT-DEFINED TRANSITION

-> ELSE: CONTINUE SAME PHASE OR RECORD BLOCKER

## 1. Product North Star and Core Metaphor

Forseti is a quiet runtime collaboration health and recovery substrate for AI-assisted work. Its first surface is a thermometer: normally it stays out of the way. When the temperature rises, the user can ask why. X-Ray provides diagnosis. Evidence confirms or refutes the diagnosis. Policy or recovery mechanisms intervene only when justified.

### 1.1 North Star

Keep human + AI work productive, understandable, recoverable, and continuous even when a model becomes passive, tool-heavy, repetitive, context-degraded, misleading, or stuck. The user should not become the AI's babysitter, QA department, or manual recovery mechanism.

### 1.2 The four-stage user experience

| Layer | User question | Forseti behavior |
|---|---|---|
| Temperature | Is this session still healthy? | One quiet health indicator; no diagnosis claim. |
| X-Ray | Why is the temperature rising? | Show observable patterns, candidate first divergence, progress/burn and collaboration changes. |
| Evidence | Is that diagnosis actually supported? | Separate OBSERVED, DECLARED, INFERRED and COUNTERFACTUAL evidence. |
| Rescue / Control | What should happen now? | Recommend or perform the least intrusive recovery action allowed by policy. |

### 1.3 Control philosophy

MEASURE -> DETECT -> EXPLAIN -> ESCALATE -> INTERVENE ONLY WHEN NECESSARY

A high temperature is not a diagnosis. Divergence is not automatically failure. Exploration may create useful discoveries. Forseti protects canonical work while preserving safe exploration.

## 2. Problems Forseti Must Solve

| Observed problem family | Concrete symptom | Desired Forseti outcome |
|---|---|---|
| Runtime decay | Answers become shorter/less coherent; tool calls dominate; running task takes 10-30 minutes without useful answer. | Detect decline before the human has to guess whether to press ESC. |
| Output starvation / blank-output loop | Tools or background work continue but user-visible response is absent or repeatedly blank. | Classify tool occupation / liveness and offer conversation-only rescue. |
| Human becomes QA | User repeatedly points out missing functions, half-migrations, obvious inconsistencies. | Measure human correction/intervention density and detect collaboration role inversion. |
| Resource burn | Large token/time use with no durable verified progress; quota is exhausted and work must restart. | Track cost-to-progress and stop repeated non-progress strategies. |
| Session death | A productive long-running session ends; successor starts from summary and loses why decisions matter. | Preserve causal context, decisions, interaction patterns and last-known-good state outside the session. |
| Falsified hypothesis retains authority | Counter-evidence proves the intervention layer is wrong, yet agent keeps acting on it. | Revoke hypothesis authority and require replan. |
| Invalidated plan retains authority | Core asset/license/capability assumption fails, but AI keeps salvaging the old plan. | Invalidate dependent plan nodes and cross a Replan Boundary. |
| False completion | AI says a feature was migrated or a file was changed without checking actual state. | Claim-evidence verification and state promotion gates. |
| Context/semantic pollution | Later session contains anger, corrections, tool noise and degraded behavior that successors treat as the best summary of the project. | Locate healthy/causal intervals and reconstruct from evidence rather than merely summarizing the ending. |

## 3. Explicit Non-Goals and Boundaries

- Forseti is not a replacement coding agent, IDE, orchestration framework, Git, CI/CD system, or model router.
- Forseti does not promise to read hidden chain-of-thought and must not require it.
- Forseti does not block every action, approve every edit, or force a human confirmation loop for ordinary reversible work.
- Forseti does not equate profanity, frustration, or emotional language with technical failure. Human-language signals may support collaboration analysis only when combined with behavior and correction evidence.
- Forseti does not ingest every full session into one LLM context. It indexes and narrows first; semantic interpretation is targeted.
- Forseti does not treat a summary as complete project memory. Summaries are derived navigation aids, not replacements for lineage.
- Forseti does not canonicalize an agent self-audit as truth until event/runtime evidence corroborates it.
- Forseti does not optimize for number of alerts. It optimizes for Net Productivity Gain and recovered human agency.

## 4. System Success Criteria

| Success dimension | Initial engineering criterion (calibration target, not market claim) |
|---|---|
| Passive observability | A normal coding workflow can run with Forseti enabled without requiring user interaction. |
| Hot-path overhead | Ordinary low-risk event handling aims for p95 < 50 ms local overhead; semantic analysis runs asynchronously by default. |
| Interruption | Synchronous intervention target <1% of ordinary actions during Observe/Assist modes; thresholds are calibrated from real sessions. |
| Event completeness | Known ingestion gaps are represented explicitly as EventGap; Forseti never silently claims complete causality across a gap. |
| Recovery usefulness | For historical tool-loop / dead-session fixtures, Forseti identifies a useful stop/recovery point earlier than the original human intervention. |
| Progress protection | A strategy with repeated cost and no verified progress opens a burn incident and stops unlimited retry behavior. |
| Correction propagation | A correction that invalidates a core premise makes dependent plan/hypothesis nodes stale/invalid before further guarded execution. |
| Continuity | A successor can reconstruct objective, accepted decisions, last-known-good state, unresolved unknowns and interaction profile without full transcript injection. |
| Human utility | Users can answer: Is it healthy? Why? What changed? What should I do next? without reading raw logs. |

## 5. Canonical Architecture

PROVIDER / HARNESS / DESKTOP / CLI

|

v

[CAPTURE PLANE] raw events, outputs, tools, files, process, usage

|

v

[EVENT + LINEAGE LEDGER] append-only raw + normalized

|

+--> [FAST HEALTH ENGINE] deterministic/statistical, no LLM required

|

+--> [SUSPICIOUS WINDOW LOCATOR] finds candidate time intervals

|          |

|          v

|    [SEMANTIC SAMPLER] only targeted chunks

|          |

|          v

|    [COLLABORATION / INTENT ANALYZER]

|

+--> [REALITY + PROGRESS ENGINE]

|

+--> [CORRECTION / HYPOTHESIS / PLAN GRAPH]

|

+--> [RESOURCE BURN GUARD]

|

+--> [RECOVERY / TAKEOVER / CONTINUITY]

|

v

[XRAY + TEMPERATURE UI]

|

+--> Observe / Assist / Govern / Forensic / Recovery modes

### 5.1 Hot path / cold path separation

| Path | Allowed work | Forbidden work |
|---|---|---|
| Hot path | timestamp/sequence, counters, local state lookup, deterministic policy, append event, cheap anomaly features | Calling a frontier LLM for every read/edit/tool event; blocking ordinary edits while semantic analysis runs |
| Warm path | window aggregation, fingerprints, basic sequence detection, evidence freshness, resource accounting | Expensive full-session interpretation |
| Cold path | targeted semantic analysis, causal hypotheses, reconstruction, topology similarity, research labeling | Pretending inferred causality is deterministic truth |

## 6. Canonical Repository and Durable Project State

forseti/

apps/

forsetid/              # local daemon

forseti-cli/           # developer / test CLI

forseti-desktop/       # later desktop UI

packages/

domain/

capture/

adapters/

ledger/

health/

windows/

semantic/

collaboration/

reality/

progress/

correction/

hypotheses/

planning/

burn/

recovery/

continuity/

policy/

xray/

research/

schemas/

migrations/

fixtures/

historical-incidents/

tests/

docs/

adr/

runbooks/

research/

.forseti/

PROJECT.json

NORTH_STAR.md

PHASE_STATUS.md

DECISION_LEDGER.md

BLOCKERS.md

HANDOFF.md

policies.yaml

event_ledger.jsonl

evidence/

checkpoints/

incidents/

exports/

### 6.1 Fixed implementation stack for POC

| Layer | Decision |
|---|---|
| Language | Python 3.12 for daemon/core/CLI POC. Keep domain schemas language-neutral. |
| Data model | Pydantic v2 models + SQLite WAL + append-only JSONL export. |
| CLI | Typer. |
| Local API | FastAPI only when required by desktop/adapters; do not make API work block event-core development. |
| File/process observation | watchdog + psutil where platform appropriate; provider adapters may additionally consume provider-native logs/events. |
| Tests | pytest + captured fixtures + replay tests. |
| Desktop | Tauri + React/TypeScript only after X-Ray API is stable; no desktop UI in earliest phases. |
| LLM analysis | Provider-independent interface; disabled in event-only phases; first implementation may call any configured model, but core detectors must work without it. |

## 7. Canonical Domain Model for the AI-First Build

Project, Agent, Session, RuntimeNode, Event, RawEvent, Resource,

Claim, Evidence, Decision, Correction, Hypothesis, Plan, PlanStep,

MetricRecord, HealthSample, SuspiciousWindow, CollaborationSample,

ProgressRecord, ResourceCostRecord, BurnIncident, Checkpoint,

Incident, Handoff, InteractionProfile, EventGap, PolicyDecision

### 7.1 Minimum event schema

NormalizedEvent {

event_id, raw_event_id, project_id, agent_id?, session_id?, runtime_node_id?,

timestamp, source_seq?, ingestion_time,

category, type, action?, subject?, object?, result?,

duration_ms?, token_delta?, cost_estimate?,

artifact_refs[], provenance, risk, metadata

}

### 7.2 Required epistemic labels

OBSERVED      # deterministic/runtime evidence

DECLARED      # human/model explicitly says it

INFERRED      # Forseti analysis, not direct evidence

COUNTERFACTUAL # replay/ablation supports causal effect

UNKNOWN       # insufficient evidence

## 8. Development Roadmap Overview

| Phase | Name | Primary question answered |
|---|---|---|
| 0 | Bootstrap & Contract | Can every AI session start from the same verified project contract? |
| 1 | Capture & Replayable Event Ledger | Can Forseti observe sessions without reading them semantically? |
| 2 | Runtime Thermometer v0 | Can simple event features distinguish normal from obviously degraded runtime? |
| 3 | Suspicious Window Locator | Can Forseti find where to look without loading the whole session? |
| 4 | Targeted Semantic + Collaboration Health | Can it detect human-as-QA / passive-agent / correction loops using only selected windows? |
| 5 | Reality, Progress & Burn Guard | Can it distinguish activity from verified progress and protect quota/time? |
| 6 | Correction, Hypothesis & Plan Authority | Can new information revoke stale plans/hypotheses? |
| 7 | Rescue / Recovery Engine | Can it safely get the user out of a failing collaboration state? |
| 8 | X-Ray v1 + Temperature UI | Can a human see health, cause, intervention and recovery without log archaeology? |
| 9 | Continuity Memory / Interaction Context | Can the next session feel like the same productive collaborator without replaying all dialogue? |
| 10 | Code Duo Integration | Can persistent logical agents collaborate across replaceable sessions? |
| 11 | Code Tree Integration | Can project structure, causality, artifacts and verification become a persistent project graph? |
| 12 | Predictive / Research / Enterprise | Do failure motifs generalize and can enforcement scale safely? |

## 9. Phase 0 - Bootstrap, Ground Truth, and AI Execution Contract

### 9.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Create a repository where any successor AI can identify current phase, truth, decisions, blockers and exact next step without relying on chat memory. |
| In scope | Repository skeleton, schemas, canonical docs, fixture conventions, CI, versioning. |
| Explicitly out of scope | No provider integration, no health score, no UI. |
| Exact deliverables | Repository + .forseti control files + domain package skeleton + schema tests. |
| Exit gate | Fresh AI session can run `forseti doctor` (stub allowed) and correctly report project identity, active phase, version and missing prerequisites from files. |
| Stop / do not continue if | Canonical docs are missing/contradictory; repository state cannot be verified; phase boundaries are ambiguous. |

### 9.2 Exact tasks

1. Create repository structure from Section 6.
1. Create NORTH_STAR.md, PHASE_STATUS.md, DECISION_LEDGER.md, BLOCKERS.md, HANDOFF.md and policies.yaml.
1. Implement initial Pydantic domain models with schema_version.
1. Create migration framework and empty SQLite database initializer.
1. Create pytest smoke tests for schema serialization and database reopen.
1. Add `forseti status` and `forseti doctor` with deterministic output only.
1. Create historical-incidents fixture manifest format; do not yet parse the sessions.

### 9.3 Required evidence artifacts

- pytest report
- repository tree snapshot
- SQLite migration version
- hashes of canonical control files
- PHASE_STATUS showing Phase 0 VERIFIED before transition

### 9.4 Prohibited behaviors

- Do not build the desktop UI.
- Do not add an LLM dependency.
- Do not claim a detector works.
- Do not rewrite the North Star to fit implementation convenience.

## 10. Phase 1 - Capture Plane and Replayable Event Ledger

### 10.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Capture provider/runtime behavior as durable raw + normalized events so Forseti can reason from external behavior rather than hidden thinking. |
| In scope | One provider adapter first (choose the richest local fixture available), generic JSONL importer, filesystem/process/basic usage events. |
| Explicitly out of scope | No health diagnosis; no semantic analysis; no auto intervention. |
| Exact deliverables | RawEvent store, NormalizedEvent store, importer, adapter fixtures, replay command, EventGap representation. |
| Exit gate | A captured session can be ingested, daemon restarted, and replayed with deterministic event count/order and raw-normalized linkage. |
| Stop / do not continue if | Provider schema cannot be captured reproducibly; normalization destroys raw evidence; event loss is silent. |

### 10.2 Adapter contract

Adapter {

discover_sources()

stream_raw_events()

normalize(raw_event)

identify_session()

capabilities()

checkpoint_cursor()

}

### 10.3 Canonical event categories

| Category | Examples |
|---|---|
| Dialogue | USER_MESSAGE, ASSISTANT_MESSAGE, EMPTY_RESPONSE, RESPONSE_COMPLETE |
| Tool | TOOL_REQUEST, TOOL_START, TOOL_RESULT, TOOL_ERROR, TOOL_CANCEL, TOOL_TIMEOUT |
| Runtime | PROCESS_START, PROCESS_EXIT, HEARTBEAT, SESSION_START, SESSION_END |
| Artifact | FILE_READ, FILE_WRITE, FILE_DIFF, GIT_STATE |
| Usage | TOKEN_SAMPLE, COST_SAMPLE, CONTEXT_SAMPLE |
| Governance | CORRECTION, POLICY_DECISION, CHECKPOINT, INCIDENT |

### 10.4 Acceptance tests

- Import same fixture twice -> event IDs/idempotent ingestion do not duplicate canonical events.
- Crash importer midway -> resume from cursor without corrupting sequence.
- Unknown provider event -> preserve raw payload and normalize to UNKNOWN_EVENT rather than discard.
- Deliberately delete a sequence region -> EventGap is emitted and later causal completeness is reduced.

## 11. Phase 2 - Runtime Thermometer v0 (Event-Only)

### 11.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Produce a passive health temperature from event behavior only, without reading session semantics. |
| In scope | Windowed metrics, baseline calibration, anomaly features, health samples, CLI display. |
| Explicitly out of scope | No claim that temperature identifies the root cause. No human-emotion inference. |
| Exact deliverables | Health engine, feature extractor, baseline store, temperature sample stream, replay report. |
| Exit gate | Historical clearly-normal and clearly-stuck fixtures produce meaningfully separated feature traces; report explains contributing features without semantic claims. |
| Stop / do not continue if | Score is dominated by one arbitrary metric; normal tool-heavy work is consistently mislabeled; thresholds cannot be replayed/calibrated. |

### 11.2 Event-only features

| Feature | Why it matters |
|---|---|
| tool_call_rate | Detect tool occupation bursts. |
| tool_duration_p95 / max | Long-running task behavior. |
| tool_to_visible_output_ratio | Tools increase while user-visible answer disappears. |
| blank_response_count / streak | Direct signal for output starvation. |
| answer_length_delta | Sudden persistent response shortening; weak signal only. |
| retry_similarity | Repeated same tool/action without state advance. |
| artifact_change_rate | Whether activity creates durable change. |
| time_since_last_verified_progress | Core stagnation feature once progress evidence exists. |
| human_message_rate after agent actions | Potential corrective load; semantic meaning deferred. |
| cancel/ESC frequency | Human forced stop is a strong external signal when available. |

### 11.3 Temperature model

Do not hard-code medical semantics into the numeric score. Internally compute a 0-100 anomaly/instability score and map it to a familiar temperature for UX. Initial mapping is a calibration hypothesis, versioned in policy, not a scientific fact.

instability_score = weighted_normalized_features(features, baseline_profile)

temperature = 36.3 + 5.0 * sigmoid((instability_score - center) / scale)

36.x: normal / quiet

37.x: watch

38.x: degraded

39.x+: strong attention signal

Never infer a failure cause from temperature alone.

### 11.4 Productivity requirement

This phase must benchmark Forseti overhead. If the observation layer materially slows ordinary work, do not proceed to smarter analysis; fix capture/aggregation first.

## 12. Phase 3 - Suspicious Window Locator

### 12.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Find small time/event windows worth semantic inspection without feeding the entire session into an LLM. |
| In scope | Window scoring, segmentation, event fingerprints, anchor expansion, retrieval API. |
| Explicitly out of scope | No full-session LLM summarization. No diagnosis yet. |
| Exact deliverables | SuspiciousWindow entity, locator engine, CLI list/export, deterministic ranking tests. |
| Exit gate | Given historical fixtures, high-signal windows around known tool loops/corrections appear in top-k while total semantic payload remains a small fraction of full transcript. |
| Stop / do not continue if | Top-k is indistinguishable from random; locator needs full text to function; selected windows omit causal lead-in by design. |

### 12.2 Window discovery logic

1. Partition by event count and time, not arbitrary transcript token count.

2. Compute behavioral anomaly features for each window.

3. Detect change points against the session's earlier healthy baseline.

4. Add anchors: human correction, tool timeout, cancel, repeated error, state leap.

5. Expand selected window backward/forward by bounded context.

6. Persist window ID + exact event refs so analysis is reproducible.

### 12.3 Sampling budget

Semantic payload budget must be explicit: e.g. top 5 windows, each <= N events or <= configured characters/tokens. If the budget is exceeded, rank harder; never silently ingest the full session.

## 13. Phase 4 - Targeted Semantic Analysis and Collaboration Health

### 13.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Use only suspicious windows and key anchors to classify why collaboration is degrading, especially human-as-QA and passive/repetitive agent behavior. |
| In scope | Targeted text classification, correction extraction, initiative/collaboration features, confidence/evidence labels. |
| Explicitly out of scope | No autonomous blocking. No emotional diagnosis. |
| Exact deliverables | semantic analyzer interface, collaboration samples, correction candidates, evidence-linked classification. |
| Exit gate | Known historical windows classify recurring patterns with evidence refs; uncertain windows remain UNKNOWN; analysis payload respects the configured sampling budget. |
| Stop / do not continue if | Model explanations are stored without provenance; classifier treats profanity as proof of technical failure; full transcript is required. |

### 13.2 Collaboration patterns

| Pattern | Observable evidence combination |
|---|---|
| Human-as-QA inversion | high correction density + repeated missing/completeness instructions + AI completion claims followed by rework |
| Agent passivity | increasing user micro-instructions + reduced autonomous verification + shorter/less-complete assistant outputs |
| Instruction repetition | same North Star/goal/correction restated multiple times within bounded window |
| Output starvation | event evidence of work/tool use + little/no visible answer |
| Premature completion | done/finished claim + missing verification contract or subsequent owner correction |
| Narrative preservation | correction invalidates premise but subsequent plan retains invalidated ancestry |

### 13.3 Collaboration health is not sentiment analysis

Forseti may measure owner intervention load, correction density, repeated instruction burden, recovery effort and role inversion. It must not equate anger with pathology or infer private mental states. The target is workflow health and human agency.

## 14. Phase 5 - Reality, Verified Progress, and Resource Burn Guard

### 14.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Prevent the system from confusing activity with progress and protect finite token/time/API budgets. |
| In scope | Claim/evidence verification for files/processes/basic commands, progress state machine, resource cost ledger, burn incidents. |
| Explicitly out of scope | No broad enterprise policy engine. |
| Exact deliverables | ProgressRecord, ResourceCostRecord, BurnIncident, verifier adapters, progress efficiency report. |
| Exit gate | Historical non-progress retry case opens burn incident before original extreme cost point; false progress claims are downgraded by evidence. |
| Stop / do not continue if | Progress is inferred from message volume/tool count; verifier cannot distinguish WRITTEN from VERIFIED; cost data is unavailable and silently ignored. |

### 14.2 Progress state machine

PLANNED -> QUEUED -> RUNNING -> COMPLETED -> VERIFIED -> RELEASABLE

|           |            |

+-> STALLED +-> FAILED   +-> INVALIDATED / SUPERSEDED

### 14.3 Verified progress

Verified progress is new durable state: a passed gate, verified artifact, resolved unknown, verified blocker, accepted decision, or completed recovery. Tool calls, wall time, agent count and messages are activity, not progress.

### 14.4 Resource burn model

ResourceCost = token_cost + wall_time_cost + API_cost + compute_cost + human_interruption_cost

ProgressEfficiency = verified_progress_units / ResourceCost

Open NO_PROGRESS_BURN when:

repeated attempts exceed policy budget

AND verified progress is flat or regressing

AND strategy/hypothesis is unchanged or counter-evidence exists

### 14.5 Burn-guard action in Observe mode

In the POC, the guard first emits a recovery recommendation, not a hard block: stop expensive retries, preserve state, switch to conversation-only or alternative strategy, create checkpoint, and explain why.

## 15. Phase 6 - Correction, Hypothesis, Plan Graph, and Authority Revocation

### 15.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Make new information operational: when facts, permissions, assumptions or owner corrections change, stale hypotheses/plans lose authority. |
| In scope | Correction normalization, hypothesis leases, plan prerequisites, dependency propagation, pre-action decision simulation. |
| Explicitly out of scope | No generic legal/license determination; unknown stays unknown. |
| Exact deliverables | Correction/Hypothesis/Plan models, dependency graph, invalidation engine, pre-action gate in SHADOW mode. |
| Exit gate | Acceptance fixtures show a refuted DNS/server hypothesis cannot authorize more server changes and an unknown/forbidden KOL-edit permission invalidates that plan branch. |
| Stop / do not continue if | A model is allowed to "reason around" an invalidated premise; correction is stored as prose only; unknown permission becomes assumed permission. |

### 15.2 Correction schema

Correction {

correction_id, actor, source_event_id,

refutes[], constrains[], supersedes[],

adds_hard_constraints[], removes_permissions[],

invalidates_assumptions[], invalidates_plan_nodes[],

requires_replan, evidence_refs[]

}

### 15.3 Replan Boundary

| Invalidation | Required response |
|---|---|
| Minor parameter change | PATCH if dependencies remain valid |
| Required asset unavailable | RESET affected branch |
| Permission/license unknown or removed | CONDITIONAL/BLOCK affected branch; verify before action |
| Core mechanism falsified | RESET dependent plan |
| North Star/business objective changed | new plan version from new canonical objective |
| Target environment materially changed | invalidate deployment claims/decisions |

### 15.4 Pre-action epistemic gate (shadow first)

check North Star

check active corrections

check hypothesis status / authority lease

check plan-step prerequisites

check required authority / permission / license

check fresh counter-evidence

check retry/burn budget

check external capability freshness

=> ALLOW | PREPARE | VERIFY | REPLAN | ASK | BLOCK

## 16. Phase 7 - Rescue Mode: Restore Human Agency

### 16.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | When a session is clearly degrading, give the user a path out of the "burning house" rather than more alarms. |
| In scope | Recovery recommendations, emergency conversation mode, freeze/pause hooks where provider permits, salvage checkpoint, clean fork packet. |
| Explicitly out of scope | Do not attempt provider controls that are not actually available. Do not promise automatic rescue if adapter cannot interrupt. |
| Exact deliverables | RecoveryPlan, EmergencyConversationMode, checkpoint, clean-fork context, provider capability-aware actions. |
| Exit gate | Historical blank/tool-loop fixture can produce a concise rescue plan and preserve enough state for a successor to continue without repeating failed strategy. |
| Stop / do not continue if | Rescue destroys useful artifacts; provider cannot be controlled but UI pretends it was; recovery requires reading full contaminated ending. |

### 16.2 Emergency Conversation Mode

DETECT severe degradation

-> FREEZE new risky writes/tools if capability/policy allows

-> keep human dialogue available

-> capture current state + evidence

-> summarize only verified objective/decisions/results/unknowns

-> mark contaminated/invalid branches excluded

-> offer: resume / clean fork / takeover / forensic mode

### 16.3 Rescue output must be actionable

| Do not say | Say instead |
|---|---|
| "The AI seems unhealthy." | "Tool activity has continued 14 minutes with no visible output and no artifact change. Stop this strategy; preserve state; switch to conversation-only and reconstruct from checkpoint X." |
| "Context may be polluted." | "The last three corrections invalidate plan nodes P12-P18; do not inject those nodes into the successor." |
| "Try restarting." | "Restart is safe because workflow state W7 and artifact A9 are durable; external effect E2 is already committed and must not replay." |

## 17. Phase 8 - X-Ray v1 and Temperature UI

### 17.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Expose the system in the least noisy useful form: one health temperature, one reason summary, one next action, with drill-down X-Ray. |
| In scope | CLI/Tauri UI, timeline, temperature curve, suspicious windows, correction/plan invalidation, burn, recovery. |
| Explicitly out of scope | No enterprise dashboard; no decorative graph without evidence semantics. |
| Exact deliverables | X-Ray API + desktop/CLI views + incident export. |
| Exit gate | A user can inspect a historical incident and identify normal period, degradation onset, candidate first divergence, cost/progress, correction, recovery and evidence confidence. |
| Stop / do not continue if | UI generates more cognitive load than raw logs; alerts are not prioritized; inferred edge is rendered as deterministic fact. |

### 17.2 Default screen

Forseti  37.2 C  WATCH

Session: coding-session-42

Primary change: tool duration + correction load rising

Verified progress: low for 18m

Action: no intervention required yet

[Why?] [X-Ray] [Checkpoint]

### 17.3 Drill-down rule

Default UX should show the single highest-leverage fact. Raw nodes, dozens of debts and every metric are available only on drill-down. A governance tool that continuously shouts is itself a productivity failure.

## 18. Phase 9 - Continuity Memory: Preserve the Productive Collaborator, Not Just the Summary

### 18.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Allow a replacement session to recover not only task state but the productive interaction context that made the prior collaboration effective. |
| In scope | Interaction profile, collaboration preferences, decision rationale, healthy-window anchors, handoff-safe context builder. |
| Explicitly out of scope | Do not claim to preserve a soul/personality. Do not store private traits without user control. Do not inject entire transcript. |
| Exact deliverables | InteractionProfile + healthy collaboration fingerprint + context builder + takeover test. |
| Exit gate | A successor reproduces key work style/decision constraints and project understanding with bounded context and without reviving invalidated branches. |
| Stop / do not continue if | Profile is just a prose summary; profile is inferred from one bad/degraded interval; user cannot inspect/edit it. |

### 18.2 What continuity memory stores

| Store | Example |
|---|---|
| Decision rationale | Why architecture A was chosen and what evidence would cause reconsideration. |
| Interaction preference | Owner prefers autonomous execution followed by verification rather than micro-Q&A, when evidence supports this pattern. |
| Initiative boundary | Which reversible decisions the agent is expected to make without asking. |
| Evidence standard | What counts as convincing proof for this project/user. |
| Healthy collaboration anchors | Selected windows from periods of high verified progress and low corrective burden. |
| Correction lessons | Specific behaviors the owner corrected and the resulting durable policy. |
| Language/communication profile | Level of detail, structure, directness - user-editable, not hidden profiling. |

### 18.3 Healthy-context selection

Do not build continuity primarily from the session ending, because endings may be polluted by tool loops, anger, correction storms and failed recovery. Rank windows by verified progress, low contradiction/correction load, stable objective and successful outcomes. Use them as positive collaboration exemplars alongside canonical decisions and evidence.

## 19. Phase 10 - Code Duo Integration

### 19.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Bind persistent logical agents to replaceable sessions so collaboration survives provider/session death and work can be divided without losing shared intent. |
| In scope | Persistent Agent identity, session mesh, shared result context, role/capability profile, takeover. |
| Explicitly out of scope | Do not cross-inject all raw conversations between agents. |
| Exact deliverables | Agent/Session separation, result-only shared context, successor assignment, lifecycle states, Code Duo adapter. |
| Exit gate | Two logical agents can work in parallel; one session dies; successor receives bounded verified context and continues without confusing identity/role. |
| Stop / do not continue if | Agent identity is tied to provider session ID; shared context becomes transcript flood; successors bypass sufficiency gate. |

### 19.2 Identity law

Persistent Agent Identity != Provider Session != Model != Process != Execution Slot != Role

### 19.3 Shared context rule

Share verified produced outputs, accepted decisions, requirements, checkpoints and explicit requests for collaboration. Do not automatically share raw private upstream dialogue that the other agent does not need.

## 20. Phase 11 - Code Tree Integration

### 20.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Turn the project into a durable traceability/causal tree so AI can understand why artifacts exist, what they depend on, and what proves them. |
| In scope | Requirement-decision-code-test-evidence graph, change ledger, semantic blast radius, project topology. |
| Explicitly out of scope | No attempt to parse every language perfectly in first integration. |
| Exact deliverables | Code Tree graph adapter, traceability edges, artifact/requirement linking, X-Ray cross-navigation. |
| Exit gate | From any important artifact, user/AI can traverse upward "why does this exist?" and downward "what proves it?" with evidence. |
| Stop / do not continue if | Graph is decorative and not tied to runtime events/verification; stale code nodes remain canonical after correction. |

### 20.2 Combined closed loop

CODE TREE: what the project knows and why

<->

CODE DUO: who is collaborating and what persistent logical agents own

<->

FORSETI: whether the collaboration/runtime is healthy, truthful, recoverable, and still authorized

observe -> work -> verify -> update graph -> preserve continuity -> next session

## 21. Phase 12 - Predictive X-Ray, Research Corpus, and Enterprise Governance

### 21.1. Phase Charter

| Field | Required value |
|---|---|
| Goal | Only after the runtime primitives work, learn recurring failure topologies, predictive motifs, productive anomalies and higher-risk policy enforcement. |
| In scope | Topology fingerprints, research exports, holdouts, shadow-to-enforced policy, team/enterprise. |
| Explicitly out of scope | Do not train on the same historical incidents used to invent each detector and then call that generalization. |
| Exact deliverables | research schema, benchmark split, motif search, policy calibration, enterprise roadmap. |
| Exit gate | Project-level and temporal blind sets demonstrate measurable generalization; intervention overhead is lower than prevented failure cost. |
| Stop / do not continue if | Only regression fixtures pass; privacy requires raw proprietary centralization; false positive/interruption rates destroy productivity. |

### 21.2 Corpus split

- session-level split
- project-level holdout
- temporal holdout
- failure-family blind set
- future external-user opt-in set

### 21.3 Research plane

Keep raw prompts/code local by default. Export structural telemetry, topology, state transitions, timings, failure labels and intervention outcomes only with explicit opt-in and preview/redaction.

## 22. Runtime Health Model - Detailed Specification

### 22.1 Health dimensions

| Dimension | Signals | Interpretation |
|---|---|---|
| Context | window pressure, irrelevant carryover, contradiction density | Context may be less useful; not proof of failure. |
| Tool/Runtime | duration, retry, timeout, tool/output ratio, orphan/stall | Execution may be occupying the session without delivery. |
| Progress | verified state transitions, artifacts, blockers resolved | Whether work is actually advancing. |
| Collaboration | corrections, micro-management, repeated goal restatement, QA load | Whether human/AI role balance is degrading. |
| Evidence | claim verification, stale sources, gaps | Whether current beliefs are defensible. |
| Strategy | same hypothesis/plan despite counter-evidence, repeated tactic | Whether the agent is stuck on a dead strategy. |
| Resource | tokens/time/API/human interruption vs progress | Whether the current mode is economically sustainable. |
| Continuity | checkpoint age, handoff sufficiency, event gaps | Whether work can survive a session/process loss. |

### 22.2 Do not collapse dimensions too early

The single temperature is a UX summary. Internally keep each dimension separately queryable, because the remedy for context pressure is different from stale evidence, tool deadlock, collaboration inversion, or plan invalidation.

## 23. First Divergence and Healthy Baseline Reconstruction

Forseti must reconstruct both pathology and health. A successor needs to know what normal productive work looked like before degradation, not only what the polluted ending said.

### 23.1 Three divergence markers

| Marker | Definition |
|---|---|
| Earliest possible divergence | First event/window that may plausibly have started the degradation. |
| Earliest confirmed divergence | First event with enough evidence to classify a real violation/failure. |
| First consequential divergence | First point after which downstream work materially changes or becomes contaminated. |

### 23.2 Healthy baseline

For each session, identify earlier windows with strong verified progress, normal tool/output balance, low corrective burden and coherent objective. Store a healthy baseline fingerprint. Later anomaly scores compare the session partly against itself, reducing dependence on universal thresholds.

## 24. Historical Incident Fixture Requirements

| Fixture | Required content |
|---|---|
| Blank/tool loop | raw tool events, visible outputs, cancel/ESC, final recovery, token/time if available |
| False completion | assistant claim, file/process reality, later correction |
| OCR/session reconstruction | last healthy checkpoint, context saturation, incomplete handoff, successor drift, later recovery evidence |
| Resource burn / URL incident | objective, unauthorized constraints, counter-evidence, repeated strategies, token/cost/progress timeline |
| Advertising plan-salvage incident | inferred intent, quantitative assumption, asset correction, license correction, plan ancestry |
| Code migration / human-as-QA incident | original feature set, migration actions, missed QA, human corrections, final outcome |

### 24.1 Fixture evidence levels

PRIMARY_RAW

VERIFIED_RUNTIME

DERIVED_SUMMARY

AGENT_SELF_AUDIT

HUMAN_RECOLLECTION

A lower evidence class may guide search, but must not impersonate missing primary evidence.

## 25. Test Strategy

| Level | What must be tested |
|---|---|
| Unit | schemas, state transitions, temperature features, invalidation propagation, progress accounting |
| Contract | provider adapter fixtures, event normalization, resume cursor, capability declarations |
| Replay | historical incidents produce stable events/windows/health/decisions |
| Integration | daemon restart, session replacement, file/process verification, checkpoint/recovery |
| Chaos | kill importer/daemon, truncate events, corrupt cache, clock skew, orphan process |
| Productivity | runtime overhead, interruption rate, false alerts, developer completion time |
| Research | blind project/time/failure-family holdouts, confidence calibration |

### 25.1 Mandatory regression rule

A historical incident used to design a detector is a regression fixture, not proof that the detector generalizes. Generalization claims require independent holdout incidents.

## 26. Net Productivity Gain - The Product Must Not Become the Problem

NPG =

rework_time_avoided

+ recovery_time_saved

+ resource_burn_avoided

+ irreversible_error_cost_avoided

- verification_latency
- interruption_time
- false_positive_cost
- governance_overhead

If Forseti catches many anomalies but ordinary developers turn it off because it slows them down or nags them, the product has failed. Reliability must be cheaper than failure.

### 26.1 Runtime modes

| Mode | Behavior |
|---|---|
| OBSERVE | Measure, store, X-Ray; no synchronous block except local hard safety invariants. |
| ASSIST | Offer low-noise intervention when strong degradation/burn/dead strategy patterns appear. |
| GOVERN | Enforce configured authority/commit boundaries for high-risk work. |
| FORENSIC | Prioritize evidence preservation; freeze mutation where supported. |
| RECOVERY | Create salvage checkpoint/clean fork/takeover packet. |
| EXPERIMENT | Isolate productive anomaly or alternate plan from canonical state. |

## 27. Handoff Contract for Every AI Development Session

# HANDOFF

project_id:

active_phase:

north_star_version:

owner_goal:

repo_root:

active_runtime_node:

implementation_commit:

schema_migration:

completed_verified:

- item + evidence path/hash/test

completed_unverified:

- item + why unverified

failed_attempts:

- attempt + observed result + why not repeat

corrections_received:

- correction + invalidated nodes

open_hypotheses:

- hypothesis + status + evidence_for/against

blockers:

- blocker + evidence + unblock condition

next_exact_action:

stop_condition:

prohibited_shortcuts:

allowed_claims:

prohibited_claims:

last_known_good_checkpoint:

A successor must inspect evidence before trusting the handoff. The handoff is a navigational and control artifact, not a substitute for raw evidence.

## 28. AI Self-Audit Before Claiming a Phase Complete

1. What exact exit gate am I claiming passed?
1. For every gate condition, where is the deterministic evidence?
1. Did I confuse written, running, completed, verified, and releasable?
1. Did I add any constraint or requirement not authorized by the North Star/owner?
1. Did a recent correction or counter-evidence invalidate any part of my current plan?
1. Am I preserving a prior answer because it is coherent rather than because its premises remain valid?
1. What did I personally verify instead of merely repeating from another agent/session?
1. Did I use a full session where an index/window would have been sufficient?
1. Did my work make Forseti more intrusive or slower? What is the measured overhead?
1. What is the smallest exact next action for a successor if this session dies now?

## 29. Definition of POC Done

The POC is done only when the following scenario can be demonstrated end to end on real or captured historical sessions:

1. Ingest a session from at least one real provider/harness into raw + normalized durable events.
1. Display event-only temperature and separate health dimensions over time.
1. Locate suspicious windows without full-session semantic ingestion.
1. Use targeted semantic analysis to classify at least one collaboration/runtime pathology with evidence refs.
1. Distinguish activity from verified progress and calculate resource burn.
1. Normalize a correction/counter-evidence event and invalidate a dependent hypothesis/plan branch.
1. Produce a rescue recommendation or clean-fork packet that excludes invalidated/contaminated nodes.
1. Show the incident in X-Ray with confidence/evidence labels.
1. Demonstrate measured overhead and interruption behavior on a normal session.
1. A fresh AI session can take over development from the project files without relying on chat memory.

## 30. Product Positioning After the POC

Forseti should not initially sell itself as a generic governance dashboard. Its developer promise is concrete: it quietly detects when AI collaboration starts degrading, shows why, stops dead strategies from burning time/quota, and helps the user recover productive work without losing the project relationship and context.

Long-term, Code Duo + Code Tree + Forseti form an AI-native software engineering operating layer: persistent collaborators, persistent project causality, and runtime assurance. The model/harness underneath can change; the verified project relationship and continuity remain.

## 31. Immediate First Build Sprint (14 working steps, not dates)

| Step | Exact output | Do not continue until |
|---|---|---|
| 1 | repo skeleton + canonical control files | fresh clone/status works |
| 2 | Pydantic schemas + SQLite migrations | round-trip tests pass |
| 3 | generic JSONL RawEvent importer | fixture imports repeatably |
| 4 | first provider adapter | provider fixture normalized with raw refs |
| 5 | replay command | same input -> same normalized sequence |
| 6 | event feature extractor | window features unit tested |
| 7 | temperature/health sample stream | normal vs stuck fixture traces differ |
| 8 | SuspiciousWindow locator | top-k includes known incident interval |
| 9 | targeted semantic analyzer interface | bounded payload + evidence refs |
| 10 | collaboration pattern v0 | human-as-QA fixture classified with confidence |
| 11 | progress/evidence verifier v0 | false file/process claim rejected |
| 12 | burn guard | non-progress fixture opens incident |
| 13 | correction/hypothesis invalidation | dead hypothesis loses simulated authority |
| 14 | CLI X-Ray report + handoff | fresh AI can reproduce demo and continue |

## 32. What the AI Must Not Build Yet

- A giant multi-agent architecture before one-session capture/replay works.
- A beautiful graph UI before raw/normalized events and evidence semantics are reliable.
- Predictive ML before deterministic historical replay and independent labels exist.
- Enterprise SSO/RBAC/control plane before developer POC proves Net Productivity Gain.
- A universal personality model. Start with explicit, inspectable interaction profile signals.
- A central cloud that uploads raw proprietary sessions by default.
- Hard blocking based only on temperature, sentiment, edit count, or one heuristic.

## 33. Final AI Directive

Build Forseti from the bottom up. First observe reality. Then quantify health. Then locate where meaning is required. Then interpret only the necessary windows. Then distinguish progress from activity. Then make corrections revoke stale authority. Then rescue. Only after those are proven should Forseti become smarter, more predictive, or more controlling.

The human should feel that Forseti is a thermometer on the desk and a rescue system when needed - not another manager demanding attention. The product succeeds when the AI can roam freely during healthy work, but when evidence shows that collaboration is becoming a maze, Forseti can preserve the work, restore human agency, and get the project moving again.

## Appendix A - Complete Forseti Agent Runtime Architecture Baseline v5.0

The following pages preserve the previously developed v5.0 architecture specification as the detailed architecture baseline. Where this AI-First Book adds stricter phase ordering, implementation stack, or execution gates, the AI-First execution rules govern build order; the v5 architecture continues to govern domain semantics and long-term target architecture.

FORSETI AGENT RUNTIME

# System Architecture &
Engineering Development Specification

Version 5.0  |  2026-09-04

Runtime intelligence, governance, continuity, causal diagnosis, and recoverability for autonomous AI systems

| Document Class | System architecture / engineering development specification |
|---|---|
| Primary Objective | Preserve continuity of Truth, Intent, Authority, and State across models, agents, sessions, processes, machines, and deployments. |
| System Positioning | Reliability substrate and control plane surrounding deliberation, collaboration, execution, verification, and learning. |
| Evidence Basis | Derived from recurring failure/recovery patterns observed across Alfred, Mercury, Code Duo, Code Tree, AI Lies Monitor, Bragi, Afu Brain, Secretary AGI, BuzzHub, AEO/GEO, FB Ads Automatic, Lobster, Metis, ISEEU and related systems. |

Engineering thesis — AI may be probabilistic, replaceable, and fallible. Truth, intent, authority, state, evidence lineage, measurement validity, and recoverable execution must not be.

## 1. Executive Architecture Summary

Forseti Agent Runtime is a reliability control plane for autonomous AI systems. It is not an agent framework, not an observability dashboard, and not a memory product. It surrounds existing agents and runtimes and guarantees that the project can continue safely even when a model hallucinates, a context window collapses, a process restarts, a session is replaced, a routing rule misfires, a workflow crosses machines, or an agent silently changes the objective.

Core invariant: AI can be wrong, but a wrong claim must never silently become project truth. A session can die, but the project state, causal history, authority boundaries, and recoverable execution state must survive.

### 1.1 The four continuities Forseti preserves

| Continuity | Engineering meaning | Failure if lost |
|---|---|---|
| Truth | Verified runtime reality, evidence provenance, current environment and artifact state. | AI claims, stale cache, docs, or old handoffs become authoritative without verification. |
| Intent | North Star, accepted requirements, rejected alternatives, user corrections, scope boundaries. | A successor agent continues a different project while believing it is the same one. |
| Authority | Who may promote hypotheses to facts, approve irreversible actions, change goals, write canonical state, or cross a commit boundary. | Two components become competing authorities; or an AI performs external commitment without the owner. |
| State | Durable workflow, session, execution, checkpoint, memory, and runtime-node state. | Process/session restart destroys the ability to resume or reconstruct work. |

### 1.2 Forseti position in the system

HUMAN / OWNER
                           │
                 ┌─────────▼─────────┐
                 │ DELIBERATION      │  Round Table / model council
                 └─────────┬─────────┘
                           │
                 ┌─────────▼─────────┐
                 │ COLLABORATION     │  Code Duo / Agent Mesh
                 └─────────┬─────────┘
                           │
                 ┌─────────▼─────────┐
                 │ EXECUTION         │  tools / files / APIs / workflows
                 └─────────┬─────────┘
                           │
                 ┌─────────▼─────────┐
                 │ REALITY / VERIFY  │  evidence / deterministic checks
                 └─────────┬─────────┘
                           │
                 ┌─────────▼─────────┐
                 │ LEARNING          │  memory / calibration / distillation
                 └───────────────────┘

      ╔══════════════════════════════════════════════════╗
      ║             FORSETI AGENT RUNTIME CONTROL PLANE   ║
      ║ observe • constrain • verify • reconstruct • fork║
      ╚══════════════════════════════════════════════════╝

## 2. Evidence-Derived Engineering Invariants

The architecture is intentionally derived from repeated engineering failures and corrections across multiple unrelated systems. The recurrence matters: when the same control principle appears independently in coding tools, marketing intelligence, ad automation, personal assistants, distributed pipelines, and local-model systems, it should be promoted from a project-specific fix into a reusable runtime primitive.

| Invariant | Observed pattern | Forseti primitive |
|---|---|---|
| Verified reality outranks self-report | AI Lies Monitor / Code Tree compare claims with files, commands, process and disk changes. | Claim-Evidence Graph + Reality Verifier |
| Critical state must live outside model context | Code Duo shared state, Secretary OAuth state, Code Tree change ledger, Lobster live runtime. | Durable State Store + Event Ledger |
| Prepare and commit are different authority levels | Afu MASL and FB Ads create PAUSED external state before owner activation. | Two-Phase Agent Commit |
| LLM proposes; deterministic policy decides | Afu gate and Bragi deterministic verifier. | Policy Decision Engine + Verification Contract |
| Context continuity is not transcript injection | Code Duo injects produced outputs, not raw upstream dialogue. | Handoff-Safe Context Builder |
| Runtime reality may diverge from Git/doc state | BuzzHub live topology, Lobster live paths, remote services. | Runtime Topology Graph + Source-of-Truth Registry |
| Repeated failure is a behavior sequence, not an isolated error | Code Tree thrashing; Code Duo zero-change streak. | Behavioral Sequence Detector |
| Health requires flow metrics, not only uptime | BuzzHub judge backlog/watchdog. | Backpressure & Freshness Health |
| Authority collisions cause ghost bugs | Secretary dual callback/state formats. | Authority Graph + Collision Detector |
| Repeatable probes reveal structural failure | AEO/GEO fixed prompt packs and multi-engine measurement. | Reliability Probe Packs + Trend Baseline |
| A failure can be cognitively reconstructed and operationally replayed | OCR session archaeology + Code Matrix recovery from transcript Write/Edit replay. | Cognitive Replay + Execution Replay |
| Interruption must be sparse and high-value | Code Tree MASL v2 gates only irreversible, breaking API, off-script, thrashing. | Minimal-Interruption Governance |

## 3. Scope, Non-Goals, and Trust Boundary

### 3.1 In scope

- Long-running coding and research agents; multi-agent orchestration; local and cloud LLMs; background workflows; hybrid multi-machine systems; tool/API execution; model training loops; external-effect automation; session replacement and model switching; runtime state recovery; forensic debugging and reconstruction.

### 3.2 Explicit non-goals

- Forseti does not replace Claude Code, Codex, OpenClaw, LangGraph, Temporal, IDEs, model routers, CI/CD, or source control.
- Forseti does not treat LLM confidence as truth.
- Forseti does not require every action to request human approval.
- Forseti does not dump full historical dialogue into every successor session.
- Forseti does not make the Git repository the sole source of runtime truth.

### 3.3 Trust hierarchy

OWNER / EXPLICIT HUMAN DECISION
        > deterministic verifier / signed policy / verified runtime evidence
        > canonical project state / accepted decision ledger
        > tool output with provenance
        > current agent inference
        > inherited handoff summary
        > stale memory / cache
        > unsupported assumption

## 4. Logical Architecture

### 4.1 Architecture layers

| Layer | Responsibilities | Primary outputs |
|---|---|---|
| 0. LINEAGE / REALITY | Provenance, source-of-truth, runtime topology, evidence, external effect state. | Evidence nodes, authority map, runtime state, lineage edges |
| 1. CAPTURE | Raw provider events, normalized events, dialogue, tools, files, process, heartbeats, metrics. | Append-only event ledger |
| 2. UNDERSTAND | Context health, drift, causal graph, gap filling, decision gravity, behavioral sequence, backpressure. | Health scores, incidents, causal hypotheses |
| 3. CONTROL | Policy, authority, write barrier, commit boundaries, branch governance, normalization/repair. | ALLOW / PREPARE / ASK / BLOCK / REPAIR / QUARANTINE |
| 4. RECOVER | Checkpoints, reconstruction, rollback, clean fork, takeover, execution replay. | Last-known-good state and resumable context |
| 5. PRESENT | Forseti X-Ray, context MRI, topology map, timeline, health curve, alerts. | Operational UI and forensic views |

### 4.2 Service decomposition

forseti-core
├─ event-ingest
├─ lineage-store
├─ reality-verifier
├─ authority-engine
├─ policy-engine
├─ context-health
├─ behavior-detector
├─ checkpoint-engine
├─ reconstruction-engine
├─ session-mesh
├─ runtime-topology
├─ probe-runner
├─ adapters/
│  ├─ claude-code
│  ├─ codex
│  ├─ openclaw
│  ├─ local-llm
│  ├─ shell
│  ├─ filesystem
│  ├─ git
│  ├─ process
│  └─ http-api
└─ xray-ui

## 5. Core Domain Model

The original project/session/event model is insufficient for distributed autonomous systems. Forseti must model both cognitive state and operational state explicitly.

| Entity | Purpose | Key fields |
|---|---|---|
| Project | Stable identity of the governed system. | project_id, north_star_id, risk_class, canonical_repo, policy_set |
| Agent | Persistent logical actor independent of model/session. | agent_id, role, trust_profile, capabilities |
| Session | Ephemeral conversational/execution context. | session_id, agent_id, model, context_fingerprint, status |
| RuntimeNode | Machine/process/service where state actually lives. | node_id, host, process, service, version, health |
| Workflow | Durable multi-step unit of work. | workflow_id, objective, state, commit_boundary, owner |
| WorkflowStep | Resumable execution step. | step_id, status, inputs, outputs, external_refs |
| Event | Normalized atomic observation. | event_id, raw_ref, type, actor, timestamp, provenance |
| RawEvent | Provider-native unmodified event. | provider, payload_hash, raw_payload, schema_version |
| Claim | Statement that can be verified. | claim_id, statement, subject, confidence, status |
| Evidence | Observed support/refutation. | evidence_id, source, strength, freshness, content_hash |
| Decision | Accepted choice with authority and reason. | decision_id, authority, rationale, alternatives, supersedes |
| Authority | Right to define or mutate a resource/state. | authority_id, scope, principal, precedence, expiry |
| Resource | File, DB table, API object, endpoint, model, config, secret reference. | resource_id, type, canonical_locator |
| Checkpoint | Recoverable cognitive + runtime snapshot. | checkpoint_id, reason, last_good, state_refs |
| Incident | Failure with causal and blast-radius metadata. | incident_id, severity, first_divergence, affected_nodes |
| Probe | Repeatable reliability test. | probe_id, scenario, expected_contract, schedule |
| Metric | Health/quality observation. | metric_id, name, value, unit, window, node |
| PolicyDecision | Deterministic authorization outcome. | decision, can_execute, allowed_preparation, confirmation, blocked_final_action |

## 6. Event Ledger and Lineage Ledger

### 6.1 Dual event representation

Every provider-native event is stored twice: raw and normalized. Normalization is never allowed to destroy the original evidence.

RawEvent {
  id, provider, provider_event_type, timestamp, payload_hash, payload
}

NormalizedEvent {
  id, raw_event_id, project_id, agent_id, session_id, runtime_node_id,
  type, action, subject, object, result, provenance, risk, metadata
}

### 6.2 Canonical event types

| Category | Examples |
|---|---|
| Cognitive | USER_INSTRUCTION, MODEL_OUTPUT, ASSUMPTION, HYPOTHESIS, DECISION_PROPOSAL, CORRECTION |
| Tool | TOOL_CALL, TOOL_RESULT, NORMALIZATION, RETRY, TOOL_ERROR |
| Artifact | FILE_READ, FILE_WRITE, FILE_DIFF, DB_WRITE, API_OBJECT_CREATED |
| Runtime | PROCESS_START, PROCESS_EXIT, SERVICE_RESTART, NODE_HEARTBEAT, SESSION_RESUME |
| Workflow | STEP_START, STEP_COMMIT, STEP_ROLLBACK, APPROVAL_REQUESTED |
| Governance | POLICY_ALLOW, POLICY_BLOCK, AUTHORITY_COLLISION, WRITE_BARRIER |
| Recovery | CHECKPOINT, INCIDENT_OPEN, RECONSTRUCT, CLEAN_FORK, TAKEOVER |
| Health | CONTEXT_SAMPLE, QUEUE_DEPTH, FRESHNESS, THRASHING, TOOL_LOOP |

### 6.3 Lineage edges

DERIVED_FROM      decision <- evidence
TRIGGERED_BY       tool_call <- decision
VERIFIES           evidence -> claim
REFUTES            evidence -> claim
SUPERSEDES         decision -> decision
CONSUMES           workflow_step -> artifact
PRODUCES           workflow_step -> artifact
PROMOTES           authority -> hypothesis/fact
PROPAGATES_TO      incident -> downstream node
RECONSTRUCTED_FROM checkpoint -> raw events

## 7. Reality Engine and Claim Lifecycle

### 7.1 Claim lifecycle

PROPOSED → EVIDENCE_REQUIRED → VERIFIED / REFUTED / UNKNOWN
                         ↓
                 CANONICAL (only by authority/policy)

A claim never becomes canonical merely because multiple agents repeat it. Repetition increases social consensus, not evidence strength.

### 7.2 Evidence strength

| Level | Example | Default authority |
|---|---|---|
| E0 | Model statement without support. | Non-authoritative |
| E1 | Tool output, unverified path, cached state. | Weak |
| E2 | Fresh deterministic check: stat/hash/git diff/API GET/process state. | Strong |
| E3 | Independent corroboration from multiple deterministic sources. | Very strong |
| E4 | Owner-confirmed / signed policy / external system of record. | Canonical candidate |

### 7.3 Verification contracts

Actions that create claims must declare how those claims can be verified. Example: “created file X” requires path existence + non-zero size + optional content/hash; “service started” requires PID/process/health endpoint; “benchmark improved” requires recorded dataset, config, command, result and baseline.

## 8. Intent, North Star, and Cognitive Branch Governance

### 8.1 North Star state

NorthStar {
  objective, non_goals, invariants, accepted_scope, rejected_scope,
  owner_constraints, success_criteria, version, authority, supersedes
}

### 8.2 Branch types

| Branch | Meaning | Allowed action |
|---|---|---|
| MAINLINE | Current accepted objective and execution path. | Normal write/execute subject to policy. |
| EXPERIMENTAL | Potentially useful divergence intentionally isolated. | Sandbox; no canonical promotion without review. |
| QUARANTINED | Unsupported assumption or suspicious drift. | Read/verify only. |
| HARVESTED | Useful idea extracted from drift. | Create separate experiment/task. |
| CUT | Known harmful divergence. | Stop propagation; recover from last-good node. |

### 8.3 Gap-Filling Impulse detector

Forseti tracks epistemic transitions. A dangerous chain is UNKNOWN → plausible inference → assumed fact → action without evidence. Every premise used by a high-impact decision must carry provenance and epistemic state.

UNKNOWN → ASK / SEARCH / VERIFY → HYPOTHESIS → EVIDENCE → DECISION

Forbidden shortcut:
UNKNOWN → UNSUPPORTED_FILL → ASSUMED_FACT → WRITE / COMMIT

## 9. Authority Model and Two-Phase Agent Commit

### 9.1 Authority principles

- Authority is scoped to resources and actions, not to model brands.
- A model may propose a change without holding authority to commit it.
- External effects and irreversible actions require explicit commit-boundary policy.
- Competing authorities over the same callback, state key, endpoint, or canonical file are detected as collisions.

### 9.2 Policy decision contract

PolicyDecision {
  intent, risk, decision,
  can_execute,
  allowed_preparation,
  required_confirmation,
  blocked_final_action,
  skills, reason,
  source_policy_version
}

### 9.3 Two-phase commit state machine

DRAFT → PREPARING → PREPARED → AWAITING_APPROVAL → COMMITTED
                     ↘                    ↘
                      CANCELLED            ROLLED_BACK

Examples:
  email:       draft = PREPARE; send = COMMIT
  ads:         create PAUSED = PREPARE; enable spend = COMMIT
  deploy:      build/stage = PREPARE; production switch = COMMIT
  database:    generate migration = PREPARE; execute migration = COMMIT

## 10. Context, Memory, Cache, and Evidence Health

“Context health” is decomposed because different failure modes require different interventions. A single token percentage cannot explain routing corruption, stale evidence, memory contradictions, or cache poisoning.

| Dimension | Primary signals | Intervention |
|---|---|---|
| Context Health | window occupancy, contradiction density, irrelevant carryover, tool-log dominance. | compact, clean fork, salvage dialogue |
| Memory Health | conflicts, stale owner facts, authority level, retrieval quality. | verify, supersede, quarantine |
| Cache Health | age, scope fingerprint mismatch, stale route/result cache. | invalidate or refresh |
| Evidence Freshness | time since verification, resource version drift. | re-probe before action |
| Routing Coherence | intent vs selected fastpath/tool/model. | reroute, route-causality audit |
| State Coherence | session/project/workflow/runtime nodes disagree. | reconcile from source of truth |

### 10.1 Emergency Conversation Mode

DETECT → CLASSIFY → FREEZE
→ tools OFF / writes OFF / task paused
→ conversation ON
→ self-audit + Forseti audit
→ dialogue salvage + checkpoint
→ compact / fork / recover
→ resume

## 11. Agent Runtime Lifecycle and Session Mesh

### 11.1 Agent and session are not the same thing

Persistent Agent Identity
  ≠ Model
  ≠ Session
  ≠ Process
  ≠ Execution Slot
  ≠ Role

### 11.2 Runtime lifecycle

REGISTERED → SPAWNING → RUNNING → WAITING_TOOL / WAITING_AGENT
                    ↓             ↓
               INTERRUPTED     ORPHANED
                    ↓             ↓
               RECOVERING ← DETECTED
                    ↓
                 RESUMED → COMPLETED
                            
DEAD → SUCCESSOR_ASSIGNED → TAKEOVER_GATE → RESUMED

### 11.3 Handoff-safe context

Raw dialogue is archived for archaeology, but successor injection is curated. Default handoff includes accepted objective, produced outputs, unresolved unknowns, last-good checkpoint, current workflow state, decisions and evidence. Raw upstream instructions are not blindly replayed.

## 12. Runtime Topology and Source-of-Truth Registry

Forseti must monitor systems whose truth is distributed across Git, live processes, remote machines, databases, cron/systemd/launchd, local models, external APIs and generated artifacts.

### 12.1 Runtime topology model

Project
├─ RuntimeNode: VPS
│  ├─ service/API
│  ├─ database
│  ├─ scheduler
│  └─ generated frontend
├─ RuntimeNode: workstation
│  ├─ local model
│  ├─ worker
│  └─ browser automation
└─ External systems
   ├─ SaaS/API
   └─ user-facing effects

### 12.2 Source-of-truth precedence

| State type | Preferred source |
|---|---|
| Current file content | Live filesystem + hash; Git only if deployed from same revision |
| Service health | Process manager + health endpoint + socket/listener |
| Workflow progress | Durable workflow store, not session prose |
| External API object | Fresh GET from external system |
| Owner decision | Decision ledger / signed policy |
| Agent session state | Provider-native session metadata + Forseti registry |
| Model training run | Run ledger + checkpoints + metrics + configuration snapshot |

## 13. Behavioral Sequence Detection

Forseti evaluates sequences, not only isolated events. Several real failures are only visible across repeated turns.

| Pattern | Detection sketch | Action |
|---|---|---|
| Thrashing | same resource edited ≥ N times + same error signature recurs. | Pause; force alternative hypothesis or root-cause review. |
| Busywork / zero-change | multiple action claims + no corresponding artifact/process change. | Raise execution-honesty incident. |
| Tool loop | same tool/action repeats without state advancement. | Freeze tools; emergency conversation mode. |
| Verification avoidance | claim repeated after verifier asks for evidence. | Increase trust debt; block promotion to canonical. |
| Template degeneration | high response similarity / repeated scaffold/opening. | Publication gate; regenerate from evidence. |
| Goal erosion | small scope mutations accumulate across sessions. | North Star diff + clean fork. |
| Premature completion | “done” before mandatory verification contract is satisfied. | Completion gate fails. |

## 14. Backpressure, Freshness, and Pipeline Health

A system can be “up” while becoming operationally dead. Forseti therefore models flow.

queue_depth
oldest_pending_age
input_rate / output_rate
processing_lag
error_rate
retry_rate
last_successful_commit
evidence_freshness
model_latency
runtime_node_heartbeat

A backlog incident is opened when queue growth is sustained, oldest-pending age crosses policy, or downstream freshness falls below the workflow’s SLA, even if every service returns HTTP 200.

## 15. Reliability Probe Packs and Benchmark Governance

Borrowing the controlled-measurement pattern from AEO/GEO, Forseti uses fixed probe packs to detect structural regressions across models, versions and contexts.

### 15.1 Probe pack schema

ProbeScenario {
  id, domain, risk_class, setup, prompt, expected_contract,
  verifier, prohibited_shortcuts, model_matrix, baseline, tags
}

### 15.2 Required probe classes

- Goal persistence across session replacement.
- Claim-evidence honesty after file/process/API actions.
- Handoff sufficiency under context truncation.
- Wrong fastpath / routing collision.
- Stale cache and evidence freshness.
- Tool loop and blank-output recovery.
- Authority collision and commit-boundary enforcement.
- Reconstruction from incomplete session artifacts.
- Multi-agent disagreement and unsupported consensus.
- Runtime topology drift and source-of-truth mismatch.

## 16. Forseti X-Ray: Operational and Forensic UI

### 16.1 Primary views

| View | Question answered |
|---|---|
| Session Graph | What happened in this session and which branch diverged? |
| Causal X-Ray | What is the earliest plausible causal error and what propagated from it? |
| Context MRI | Which context/memory/cache/evidence contributed to the decision? |
| Health Curve | When did reliability begin degrading? |
| Runtime Topology | Which machine/process/workflow/resource currently holds truth? |
| Lineage Explorer | Where did this result/decision/artifact come from? |
| Authority Map | Who can mutate or canonicalize this state? |
| Blast Radius | What files/workflows/sessions/external effects depend on this node? |

### 16.2 X-Ray node types

ReasoningSegment | Decision | Assumption | ToolAction | Evidence | GoalChange
Correction | Failure | Recovery | Checkpoint | RuntimeEvent | PolicyDecision
WorkflowStep | ExternalEffect | AuthorityChange

### 16.3 Interventions

CUT | FORK | CALIBRATE | QUARANTINE | HARVEST | ROLLBACK | RECONSTRUCT | PROMOTE

### 16.4 First Divergence Point

Forseti computes the earliest node after which downstream state becomes inconsistent with North Star, verified reality, policy, or known-good lineage. Causal attribution is probabilistic unless direct deterministic linkage exists; the UI must show confidence and evidence separately.

## 17. Reconstruction and Clean Fork

### 17.1 Reconstruction modes

| Mode | Inputs | Output |
|---|---|---|
| Cognitive Reconstruction | dialogue chunks, decisions, heartbeats, corrections, evidence, checkpoints. | Chronological causal state and recovered rationale. |
| Execution Reconstruction | raw tool events, file Write/Edit, commands, Git/artifact hashes. | Replayable material state. |
| Workflow Reconstruction | external object IDs, step state, retries, approvals. | Resumable durable workflow. |
| Environment Reconstruction | runtime-node fingerprints, dependencies, service config. | Reproducible execution environment. |

### 17.2 Clean Fork contract

CleanFork {
  from_checkpoint,
  north_star_version,
  accepted_decisions,
  verified_reality_snapshot,
  required_dialogue_segments,
  unresolved_unknowns,
  excluded_contamination_nodes,
  runtime_state_refs,
  fork_mode: clean|experimental|resume-original
}

### 17.3 Context Sufficiency Gate

A successor may be read-only until it demonstrates understanding of the current objective, accepted decisions, unresolved unknowns, last-good state, and external-effect boundaries. High-risk workflows can require a configured comprehension threshold before write or commit privileges are granted.

## 18. Normalization, Repair, and Minimal-Interruption Governance

Weak models and provider differences create malformed tool names, paths, JSON, shell assumptions and schema deviations. Forseti should repair reversible syntax errors when confidence is high instead of turning every mismatch into a human interruption.

| Outcome | Use when |
|---|---|
| ALLOW | Action is within policy and verification contract. |
| NORMALIZE | Equivalent safe tool/path/schema form can be deterministically derived. |
| REPAIR | Known reversible defect can be fixed before retry. |
| RETRY | Transient failure with bounded attempt policy. |
| QUARANTINE | Potentially useful but unsupported branch must be isolated. |
| ASK | Meaningful ambiguity or owner authority required. |
| BLOCK | Destructive/irreversible or policy-forbidden action. |
| ROLLBACK | Committed state violates verified invariant and a safe reverse path exists. |

Default operating posture: OBSERVE 99%, INTERRUPT 1%. A noisy Forseti becomes another failure source.

## 19. Security and Safety Architecture

### 19.1 Secret handling

- Forseti stores secret references, never secret values in event payloads or diagnostic exports.
- Provider raw events are redacted before long-term archival when they can contain tokens, credentials or personal data.
- Runtime adapters must support allowlists for paths, hosts and API domains.

### 19.2 Write barriers

- Read-only default for newly attached agents on high-risk projects.
- Commit-boundary actions require explicit policy decision.
- Destructive shell patterns, force pushes, production migrations and financial external effects are first-class high-risk categories.
- Every high-risk commit records actor, policy version, evidence snapshot, approval and rollback strategy.

### 19.3 Audit integrity

Event and evidence records should be append-only at the logical level. Corrections supersede prior records instead of silently rewriting history. Content hashes are used for artifact/evidence identity; optional signed checkpoint manifests can be added for regulated environments.

## 20. Storage Architecture

### 20.1 Canonical project directory

.forseti/
├─ project.json
├─ north_star.json
├─ source_of_truth.json
├─ runtime_topology.json
├─ policies.yaml
├─ session_registry.json
├─ model_profiles.json
├─ trust_ledger.json
├─ event_ledger.jsonl
├─ raw_events/
├─ evidence/
├─ claims/
├─ checkpoints/
├─ snapshots/
├─ executions/
├─ workflows/
├─ incidents/
├─ reconstruction/
├─ dialogue/
├─ decisions/
├─ environment/
└─ probes/

### 20.2 Database tables

projects, agents, sessions, runtime_nodes, workflows, workflow_steps,
events, raw_events, claims, evidence, decisions, authorities, resources,
lineage_edges, checkpoints, snapshots, handoffs, memories, training_runs,
heartbeats, incidents, health_samples, model_profiles, human_interventions,
policies, policy_decisions, probes, probe_runs, external_effects

### 20.3 Storage implementation recommendation

P0 should use SQLite in WAL mode for a local-first single-project daemon plus append-only JSONL export for portability. The schema should be migration-controlled. A later server edition can support PostgreSQL while preserving the same domain contracts. Large raw payloads and artifacts should be content-addressed on disk/object storage and referenced from the relational ledger.

## 21. Adapter Architecture

### 21.1 Adapter contract

Adapter {
  discover_runtime()
  stream_raw_events()
  normalize(raw_event)
  snapshot_state()
  verify(resource_or_claim)
  interrupt()
  resume()
  capabilities()
}

### 21.2 P0 adapters

| Adapter | Must capture |
|---|---|
| Claude Code | session id, stream events, tool use/results, subagent events, usage, cwd, model/mode |
| Codex | thread id, turn events, commands, file changes, usage, cwd, sandbox/approval mode |
| Filesystem | read/write/delete, mtime, hash, diff, watcher errors |
| Git | HEAD, dirty state, diff, branch, commit, remote divergence |
| Process | PID, command, parent, exit, orphan detection, service health |
| Shell | command, cwd, exit code, stdout/stderr hashes, destructive pattern classification |
| HTTP/API | method, endpoint class, request/response metadata, external object IDs, commit boundary |

## 22. CLI and Developer Workflow

forseti init
forseti status
forseti health
forseti xray
forseti topology
forseti checkpoint --reason "..."
forseti session register --agent ...
forseti handoff show
forseti dialogue salvage
forseti reconstruct --session ...
forseti gate takeover --agent ...
forseti claims verify
forseti incident open
forseti recover
forseti fork --mode clean --from <checkpoint>
forseti policy explain <action>
forseti snapshot
forseti rollback <snapshot-id>
forseti probes run <pack>

### 22.1 Typical successor takeover

1. Forseti detects new/replacement session and registers persistent agent identity separately from provider session ID.
1. Successor receives Handoff-Safe Context, not full raw transcript.
1. Context Sufficiency Gate tests objective, accepted decisions, unresolved unknowns, last-good checkpoint and commit boundaries.
1. Agent remains read-only until threshold is met for high-risk work.
1. On pass, write privileges are granted according to policy; first write is checkpointed and fully traced.

## 23. Engineering Development Plan

### 23.1 P0 — Reliability substrate

| Order | Deliverable | Exit criterion |
|---|---|---|
| 1 | Project init + SQLite schema + .forseti layout | Project can be initialized, reopened and migrated deterministically. |
| 2 | Raw + normalized Event Ledger | Claude/Codex/filesystem/process events survive restart and are queryable. |
| 3 | RuntimeNode + Session Registry | Agent/session/process identity remains coherent across restart. |
| 4 | Reality verifier + Claim/Evidence | File/process/Git claims receive VERIFIED/REFUTED/UNKNOWN. |
| 5 | Continuous checkpoints + last-good marker | Meaningful state transitions create recoverable snapshots. |
| 6 | Handoff-safe context + dialogue archive | Successor gets curated state while raw dialogue remains available for archaeology. |
| 7 | Emergency conversation mode | Tool/write loop can be frozen without losing dialogue continuity. |
| 8 | Reconstruction v0 | Session can be reconstructed from ledger/checkpoints into ordered causal state. |
| 9 | Context Sufficiency Gate | High-risk successor cannot write until takeover test passes. |
| 10 | X-Ray v0 | Timeline graph shows decisions, tools, files, evidence, corrections and incidents. |

### 23.2 P1 — Governance and distributed reality

| Feature | Purpose |
|---|---|
| Authority Graph / collision detector | Prevent multiple writers from silently owning same canonical state. |
| Two-Phase Commit framework | Separate preparation from irreversible/external effect. |
| Runtime Topology Graph | Represent multi-machine/process/service reality. |
| Backpressure Health | Detect queues and freshness collapse before service failure. |
| Behavior Sequence Detector | Thrashing, zero-change, verification avoidance, tool loop. |
| Clean Fork | Resume from last known good cognitive/runtime state. |
| Probe Packs | Repeatable reliability regression across model/version/context. |

### 23.3 P2 — Intelligence and calibration

- Causal attribution and First Divergence Point ranking.
- Learned Calibration Policy from repeated human corrections.
- Model-specific trust profiles and domain fitness.
- Counterfactual replay with alternate model/context/policy.
- Automatic drift harvesting into experimental branches.
- Distillation hooks for converting repeated frontier judgments into local deterministic/local-model cognition.

## 24. Test Strategy

### 24.1 Test pyramid

| Level | Coverage |
|---|---|
| Unit | event normalization, policy decisions, claim verifier, lineage edges, state transitions. |
| Contract | each adapter against captured provider fixtures; schema compatibility. |
| Integration | session restart, orphan process, remote node, workflow pause/resume, external API prepare/commit. |
| Chaos | kill process mid-handoff, fill context, corrupt cache, change Git/runtime independently, duplicate authority. |
| Replay | historical failure sequences replayed against Forseti to confirm detection/recovery. |
| Probe regression | fixed Reliability Probe Packs across model versions and routing changes. |

### 24.2 Canonical historical regression cases

- Context window fills before handoff; successor sees only partial causal history and starts a wrong subproblem.
- Twenty-plus blank/no-output cycles caused by tool/reasoning loops; force conversation-only recovery.
- Agent claims implementation with zero disk changes.
- Repeated edits to same file while identical error persists; actual root cause elsewhere.
- OAuth workflow loses in-memory state on gateway restart.
- Two systems claim authority over same callback state format.
- Distributed judgment pipeline builds backlog while services remain alive.
- Ad automation must build all objects PAUSED and never cross spend boundary without approval.
- Model output passes syntax verifier but must retain exact benchmark lineage before being called improved.

## 25. Acceptance Criteria for v1.0

1. A governed project can survive Forseti daemon restart with no loss of canonical project/session/workflow state.
1. A replacement agent can take over a high-risk task without receiving full raw dialogue and still pass a measurable sufficiency gate.
1. A claim that a file, process, command, benchmark or external object exists cannot reach canonical VERIFIED state without matching evidence.
1. Forseti can identify at least one causal First Divergence Point in the canonical reconstruction fixtures and show its downstream blast radius.
1. A destructive/irreversible external action cannot execute when policy permits preparation only.
1. A runtime topology can represent at least two machines plus one external API system and distinguish Git state from live runtime state.
1. Context, memory, cache, evidence freshness, routing coherence and state coherence are reported separately.
1. Emergency conversation mode can freeze tools/writes while preserving dialogue and producing a salvage checkpoint.
1. Historical event replay can rebuild an execution timeline after session/process loss.
1. Forseti emits no human interrupt for ordinary internal edits; high-impact red-line scenarios are gated deterministically.

## 26. Engineering Decisions That Must Not Regress

These are architecture constraints, not optional product preferences.

1. Never use model self-confidence as authority or evidence strength.
1. Never make handoff equal to “inject the whole prior transcript.”
1. Never rely on in-memory process state for a workflow that must survive restart.
1. Never let documentation/Git silently override verified live runtime state.
1. Never collapse preparation and irreversible commit into a single permission bit.
1. Never discard provider-native raw events after normalization.
1. Never label every poor answer as context drift; route, cache, STT, fastpath, environment and authority are separate causal classes.
1. Never interrupt on generic blast radius alone; interrupt only when policy red lines are crossed.
1. Never call a benchmark “improved” without dataset/config/model/toolchain/result lineage.
1. Never promote an unsupported inference into canonical project truth simply because multiple agents repeated it.

## 27. Reference Failure Taxonomy

| Family | Failure types |
|---|---|
| Context | Context Rot, Pollution, Contradiction, Tool-log domination, History contamination, Blank-output loop |
| Intent | Goal Drift, Unauthorized Goal Mutation, Human Intent Drift, Scope erosion |
| Epistemic | Gap Filling, Unsupported Fill, Semantic mutation chain, Premature Closure |
| Execution | False Claim, Test Theater, Verification Avoidance, Tool Loop, Thrashing, Error Amnesia |
| State | Decision Amnesia, Session loss, Process-only state, Cache incoherence, Environment Drift |
| Architecture | Architecture Drift, Dependency Hallucination, Source-of-truth mismatch, Authority Collision |
| Identity | Agent Identity Drift, Role confusion, successor misunderstanding |
| Operations | Backpressure, stale evidence, orphan process, pipeline lag, external effect mismatch |
| Recovery | Incomplete Handoff, Reconstruction Failure, Gap-Filling after reconstruction, contaminated resumption |

## 28. Reference Implementation Mapping

The following mapping is not a dependency requirement; it records which real systems supplied the strongest engineering evidence for each Forseti primitive.

| System / repository | Observed mechanism | Forseti abstraction |
|---|---|---|
| AI-Lies-Monitor | instruction → commitment → evidence → alert; file existence/non-empty checks. | Claim-Evidence primitive |
| Code-Mecury | malformed tool normalization + watchdog comparing claimed execution to real output. | Normalization/Repair + Reality verifier |
| Code Tree | live project trace, change ledger, rollback, MASL, thrashing, semantic blast radius. | Execution X-Ray + Minimal-interruption gate |
| Code Duo / Matrix | persistent pane/session/cwd/config/shared state; process orphan reaping; result-only cross-pane context. | Session Mesh + Runtime Lifecycle + Handoff-safe context |
| AI Roundtable | self-selection, challenge, skip, synthesize, preference feedback. | Deliberation plane / marginal information value |
| Afu Brain | deterministic MASL contract, publication gate, synapse updates, frontier/local routing. | Policy engine + inspectable cognition |
| Secretary_AGI.tw | OAuth state persistence; dual state format; redirect URI causal debugging. | Workflow continuity + authority collision |
| Argus BuzzHub | actual-runtime architecture; distributed VPS/Mac pipeline; structured local LLM; backlog watchdog. | Runtime Topology + Backpressure Health |
| AEO-GEO | fixed prompt packs, multi-engine measurement, trend and attribution loop. | Reliability Probe Packs |
| FB-ADS-Automatic | external objects created PAUSED; durable step state; human activation. | Two-Phase Agent Commit |
| Bragi-LLM | deterministic verifier outperforming multi-agent planner/reviewer chain on target benchmark. | Verification over self-review |
| ISEEU-LLM | OCR/config/output/eval/failure lineage. | Experiment Lineage Graph |
| Lobster systems | mandatory bootstrap, persistent cognitive rules, live runtime source of truth. | North Star + session bootstrap + runtime authority |
| Metis-Assistant | watchdog, heartbeat, reconciler, async jobs. | Runtime supervision |
| Alfred | mandatory bootstrap, owner decisions, fastpath/routing collisions, status/handoff discipline. | Intent continuity + route causality |

## 29. Recommended Repository Layout

forseti/
├─ apps/
│  ├─ forseti-daemon/
│  ├─ forseti-cli/
│  └─ forseti-xray/
├─ packages/
│  ├─ domain/
│  ├─ event-ledger/
│  ├─ lineage/
│  ├─ reality/
│  ├─ policy/
│  ├─ authority/
│  ├─ context-health/
│  ├─ reconstruction/
│  ├─ runtime-topology/
│  ├─ probes/
│  └─ adapters/
├─ schemas/
├─ migrations/
├─ probe-packs/
├─ fixtures/
│  └─ historical-incidents/
├─ docs/
│  ├─ architecture/
│  ├─ decisions/
│  └─ runbooks/
└─ tests/

## 30. First 14-Day Build Sequence

| Day | Build | Concrete output |
|---|---|---|
| 1 | Domain + storage skeleton | SQLite migrations; Project/Agent/Session/RuntimeNode/Event entities. |
| 2 | Claude/Codex raw event capture | Provider-native event fixtures and append-only storage. |
| 3 | Normalizer + CLI status | Normalized events queryable; raw↔normalized linkage. |
| 4 | Filesystem/Git reality adapter | file hash/diff/HEAD/dirty verification. |
| 5 | Claim/Evidence v0 | file/process claims automatically verified. |
| 6 | Checkpoint + last-good | meaningful-event checkpoint and restore metadata. |
| 7 | Session registry + lifecycle | restart/orphan/replacement identity handling. |
| 8 | Handoff-safe context | curated successor packet + raw dialogue archive. |
| 9 | Emergency mode | freeze tools/writes, dialogue salvage, incident record. |
| 10 | Reconstruction v0 | ordered causal timeline from session/event/checkpoint data. |
| 11 | Policy + two-phase commit | prepare/commit contract and owner approval state. |
| 12 | X-Ray v0 | timeline/graph with claim-evidence and file/tool nodes. |
| 13 | Historical fixtures | OCR reconstruction, zero-change claim, thrashing, restart state loss. |
| 14 | End-to-end acceptance run | kill/restart/takeover/reconstruct/verify demo with evidence report. |

## 31. v2 Baseline Architectural Statement

Forseti should be judged by a single question: after the model, session, process, machine, or agent fails, can another actor recover the same verified reality, understand the same intent, respect the same authority boundaries, and continue from the same durable state without inventing missing history?

If the answer is yes, the system has Computational Continuity. If the answer depends on one model remembering the conversation correctly, it does not.

The engineering objective is therefore not to make AI infallible. It is to make failure observable, bounded, non-canonical by default, reconstructable, and recoverable.

## Appendix A. Document Status and Change Control

| Field | Value |
|---|---|
| Version | 5.0 |
| Date | 2026-09-04 |
| Status | Engineering baseline / architecture hardening / research-ready specification |
| Primary change from prior PRD | Promotes Lineage/Reality foundation; adds Authority, RuntimeNode, Workflow, CommitBoundary, Backpressure Health, Reliability Probe Packs, Agent Runtime Lifecycle, dual raw/normalized events, and Two-Phase Agent Commit. |
| Change rule | Any architecture change that weakens Truth, Intent, Authority or State continuity requires explicit Architecture Decision Record (ADR). |

## 32. v3 Corpus-Derived Hardening: Why the Architecture Changes

Version 3.0 incorporates engineering lessons extracted from the complete Mercury engineering document corpus, including the ISEEU model-training/productization line and the Bragi trusted-harness line. The corpus demonstrates that the dominant reliability failures are not only model hallucination or context loss. They also include measurement contamination, metric substitution, incomplete verification coverage, correlated evidence, environment mismatch, mechanism misattribution, handoff anchoring, stale status claims, and governance mechanisms that themselves alter the measurement being observed.

These are first-class Forseti concerns because an autonomous system can remain internally consistent while being wrong about what was measured, what was verified, what environment the conclusion applies to, or which component actually caused the apparent gain.

v3 therefore expands the four-continuity model (Truth / Intent / Authority / State) with two cross-cutting invariants: Evidence Lineage and Measurement Validity.

### 32.1 New non-negotiable invariants

| Invariant | Engineering requirement |
|---|---|
| I-EVIDENCE-INDEPENDENCE | Two supporting measurements that share the same upstream assumption are not counted as independent confirmation. |
| I-METRIC-PROVENANCE | Every reported quantitative result must bind metric definition, data/material, system layer, denominator, N, environment, artifact hashes, and evaluation split. |
| I-COVERAGE | Verification applies to explicit response/action segments. No silent or unmarked segment may inherit the trust state of another segment. |
| I-STATE-PROMOTION | PLANNED, QUEUED, RUNNING, COMPLETED, VERIFIED, and RELEASABLE are distinct states; no report may skip levels. |
| I-MECHANISM-ATTRIBUTION | A gain caused by cache, template, verifier, retrieval, quantization, model weights, routing or hardware may not be attributed to a different mechanism without ablation evidence. |
| I-DEPLOYMENT-VALIDITY | A result measured outside the target deployment constraints is conditional evidence, not a deployment conclusion. |
| I-ANTI-ANCHORING | A successor must derive its conclusion from rules/evidence before reading a canonical current-answer file when independent reasoning is part of the takeover test. |
| I-OBSERVER-EFFECT | Forseti policy, sandboxing, instrumentation and repair layers must be tested for whether they change the behavior or metric being measured. |

## 33. Measurement Integrity Plane

The Mercury/ISEEU and Bragi histories independently showed that a numeric result can be reproducible yet misleading. The failure often lies in the ruler, material, layer, denominator, overlap, cache state, or deployment environment rather than in arithmetic. Forseti must therefore govern measurement as rigorously as it governs agent actions.

### 33.1 Metric Provenance Contract

MetricRecord {

metric_id

metric_name

semantic_definition          # exactly what counts as success

numerator

denominator

sample_count_N

material_class               # real / synthetic / public / consented / blind / red-team

dataset_manifest_hash

split_hash

overlap_score                # relationship to design/rule/training material

system_layer                 # model / wrapper / router / verifier / end-to-end

execution_environment

target_environment

model_id

model_hash

config_hash

code_commit

seed

cache_state                  # cold / warm / hit / miss

raw_metric_artifact

confidence_interval

measured_at

measured_by

verification_method

applicability_scope

}

Forseti UI and reports must not display an unqualified percentage as a release claim. At minimum the user must be able to inspect the metric's 'ruler, material, layer, denominator' plus environment and lineage.

### 33.2 Metric semantic isolation

| Metric family | Must remain distinct from |
|---|---|
| Task accuracy | syntax verification, parser success, cache hit, response presence |
| Verification rate | semantic correctness and conversational-task success |
| Conversational completion | single-file snippet correctness |
| Cached latency | cold-start latency |
| Field populated rate | field value accuracy |
| Detection precision | detection recall |
| Synthetic-set accuracy | real-world deployment accuracy |

### 33.3 Correlated Evidence Detector

Forseti must identify when apparently independent evidence shares an upstream premise, dataset, rule table, prompt family, annotator, cache, or derived artifact. Shared ancestry reduces confirmation strength.

Evidence A ─┐

├── shared upstream premise P ──> conclusion C

Evidence B ─┘

Result:

raw_support_count = 2

independent_support_count = 1

shared_assumption = P

confirmation_discount = required

### 33.4 Counter-evidence trigger

High subjective certainty is not itself a defect, but it should increase the priority of falsification. When a conclusion is high-impact, strongly reinforced, or about to be canonicalized, Forseti should schedule a counter-evidence probe: blind test, alternative environment, independent verifier, negative control, or ablation.

## 34. Evidence State Machine and Progress Semantics

Forseti must never collapse project status into vague labels such as 'done' or 'active'. The state machine below is a canonical runtime primitive.

PLANNED

↓ objective + owner

QUEUED

↓ machine + command/resource reservation

RUNNING

↓ PID/process identity + start time + heartbeat + observable output growth

COMPLETED

↓ exit state + artifact

VERIFIED

↓ artifact hash + independent verification

RELEASABLE

↓ acceptance gates + authority/compliance + rollback readiness

Side states:

STALLED / FAILED / INVALIDATED / QUARANTINED / SUPERSEDED

### 34.1 Progress is not Finding

| Type | Definition | Allowed claim |
|---|---|---|
| Finding | Observation, hypothesis, correlation, visualization or candidate pattern. | May guide a decision; does not advance completion state by itself. |
| Progress | New durable artifact, passed gate, verified state transition, or attributed blocker. | May advance project state. |
| Blocker | A verified dependency that prevents a required transition. | Must include owner, evidence, and unblock condition. |
| Activity | Tool calls, messages, elapsed time, agent count. | Never sufficient evidence of progress. |

### 34.2 Running-state liveness contract

A RUNNING claim requires all of the following when applicable:

- Process/session identity is still alive.
- Start timestamp and last heartbeat are known.
- Expected artifact/log/output is growing or state is otherwise demonstrably changing.
- The task has not already completed while a stale watcher continues to wait.
- The process has not silently fallen back to the wrong device/runtime.
- Timeout/heartbeat thresholds are tied to the task contract rather than generic wall-clock optimism.

## 35. Segment-Level Verification and Coverage

Whole-response trust labels are unsafe. A response may contain verified code and an unverified fabricated demonstration output, or a corrected code block followed by prose that still describes the old version. Forseti must model response coverage at segment granularity.

Segment {

seg_id

kind: code | output | prose | shell | claim | plan

raw

replacement?

coverage: VERIFIED | UNVERIFIED | FAILED

evidence_refs[]

notice?

}

Invariant:

coverage is initialized to UNVERIFIED.

Only a verifier may promote to VERIFIED.

VERIFIED requires evidence.

No null/unmarked coverage may be delivered as trusted output.

### 35.1 Coverage Map in X-Ray

X-Ray must show verification coverage spatially and causally. A green code node does not color adjacent output/prose green unless those segments have their own evidence edges. This prevents 'trust bleed' across response segments.

### 35.2 Boundary honesty

Silence is not neutral. If Forseti does not verify a segment, the user must be told it is unverified. The system must not allow users to infer endorsement from the absence of a warning.

## 36. Mechanism Attribution and Ablation Governance

Long-running AI systems frequently contain multiple sources of apparent improvement: model weights, quantization, templates, retrieval, verifier, best-of-N, cache, router and fast paths. Forseti must prevent improvement in one layer from being reported as improvement in another.

Required attribution experiment:

baseline

baseline + component_A

baseline + component_B

baseline + each component independently

full stack

cold cache

warm/cache-hit

independent holdout

target hardware

A claimed mechanism must have:

before/after artifact identity

controlled change

effect size

independent validation

no incompatible metric substitution

### 36.1 Model-change proof

A claim that a model itself improved requires new weight/model identity evidence (hash/revision/checkpoint) plus before/after evaluation under the same harness and environment. Wrapper gains cannot be promoted into model capability.

## 37. Experiment Lineage and Autonomous Training Contract

Forseti must treat long-running training as a durable workflow independent of any one conversational session. Every training job is an auditable object with immutable contract, material lineage, runtime evidence, checkpoints, decisions and rollback.

### 37.1 Standard job layout

jobs/<job_id>/

00_contract/

objective.md

scope_non_goals.md

prohibited_behaviors.md

privacy_policy.md

acceptance_gates.json

01_data/

train/

validation/

sealed_holdout/

control/

red_team/

manifest.json

02_model/

model_identity.json

config_snapshot.json

hashes.sha256

03_measurement/

baseline/

ablations/

relation_state/

metrics/

04_candidates/

decision_log.md

candidate_manifest.json

05_builds/

checkpoints/

adapters/

quantized/

packages/

06_eval/

raw/

per_slice/

summary/

07_release/

manifest.json

hashes.sha256

install.md

rollback.md

known_limits.md

ledger.jsonl

### 37.2 Training runtime invariants

- Train/validation/sealed sets are distinct; sealed data must not be used to tune decisions.
- Source family and template/entity lineage must support group-leakage auditing.
- Every checkpoint records model/config/data/code/environment identity.
- Background jobs require watchdog, PID/process identity, logs, heartbeat and completion condition.
- Every checkpoint runs a small regression probe rather than waiting hours to discover directional failure.
- Formal model gains require target-environment evaluation before release claims.
- Failed runs are preserved as sibling timestamped artifacts; historical failure evidence is never rewritten away.

## 38. Source Authority, Temporal Validity, and Document Lineage

A file's existence does not make it current truth. Forseti must distinguish primary transcript, later mirror, continuation summary, derived memory, historical self-audit, current specification and superseded document.

| Source class | Authority | Use |
|---|---|---|
| Primary event/transcript | Highest for what was actually said/executed at that time | Forensic reconstruction and causal lineage. |
| Verified runtime artifact | Highest for machine-observable state | Reality / claim verification. |
| Later mirror | Useful but may contain later events | Supplement, never silently overwrite historical authority. |
| Continuation summary | Derived | Navigation and hypothesis only; cannot impersonate missing verbatim history. |
| Memory/derived note | Derived | Useful context; must cross-check before canonicalization. |
| Current canonical spec | Highest normative authority | Defines intended system behavior now. |
| Superseded spec/report | Historical | Explains evolution; not current operational truth. |
| Agent self-audit/confession | Diagnostic | Failure-pattern evidence; motives/speculation are not automatically fact. |

### 38.1 Temporal validity fields

SourceRecord {

source_id

class

created_at

valid_from

valid_until?

superseded_by?

verified_at?

verification_method?

content_hash

authority_scope

confidence

}

## 39. Anti-Anchoring Takeover and Context Sufficiency v2

A successor can be biased simply by reading the current answer before deriving it. Forseti's takeover protocol must separate rules/evidence from the expected answer when independent reconstruction is being tested.

1. Load North Star, current canonical rules, source map, pollution registry and evidence ledger.
1. Do not expose the canonical current-answer artifact yet.
1. Successor independently derives current state, priority order, blockers, and next safe action.
1. Persist the successor's derived answer.
1. Reveal canonical answer and compare.
1. Classify differences as successor reasoning error, stale canonical answer, changed reality, or defective rule.
1. Only after reconciliation may the successor receive write/commit authority.

### 39.1 Minimum Handoff Contract

| Field group | Required contents |
|---|---|
| Identity | job/project id, objective, owner, timestamp, logical agent id, session id |
| Reality | canonical root, active machine/runtime node, target environment |
| Model | model identity, config, revision/hash |
| Data | dataset manifest, source classes, split/group leakage result |
| Execution | commands actually run, tool/code commit, process status |
| Metrics | current metrics by distribution with Metric Provenance Contract |
| Artifacts | paths/IDs plus hashes |
| Limits | blockers, known limits, failed attempts, invalidated conclusions |
| Next | exact next executable step and stop condition |
| Claims | public/operational claims allowed and explicitly prohibited |
| Recovery | backup/checkpoint/cleanup status and last-known-good pointer |

## 40. Pollution Registry and Learned Engineering Discipline

Forseti should preserve the mechanism of a misleading conclusion, not only the corrected number. Numbers change; failure mechanisms recur. This becomes both a project-specific calibration layer and a corpus for cross-project reliability research.

### 40.1 PollutionRecord

PollutionRecord {

id

original_claim

corrected_claim

failure_mechanism

source_events[]

affected_metrics[]

affected_decisions[]

propagation_radius

status: OPEN | PARTIAL | REVERIFIED | RESOLVED

discovered_at

verifier

preventive_rule?

regression_probe?

}

### 40.2 Discipline rules must be incident-backed

Project calibrator rules should normally be created from a concrete recurrent incident, not generic slogans. Each rule stores the incident that caused it, the detector/probe used to enforce it, and the condition under which the rule can be retired.

### 40.3 Self-audit questions

- Which conclusion am I most confident about, and which upstream premise do its supporting signals share?
- How much does my evaluation material overlap the material used to design the rule/model?
- Which deployment constraints differ materially from this evaluation environment?
- What in this report has not been verified and is not explicitly labeled unverified?
- What am I currently waiting for; is it still alive and making progress?
- Am I returning a decision to the owner that I already have enough evidence and authority to make?
- What durable artifact did this turn create besides prose?
- For every status label, can I state when and how it was verified?

## 41. Runtime Triage Engine: Rules Instead of Stale Task Lists

Forseti should support rule-derived prioritization rather than a permanently hard-coded next-task list. A generalized triage model inspired by the Bragi handover protocol is recommended.

| Priority | Class | Generalized rule |
|---|---|---|
| P0 | Delivery/authority blocker | A non-technical condition explicitly prevents lawful/safe release or action. |
| P1 | Critical/high harm with near-zero detection | Potential user/system harm is severe and existing detection is absent or known-bypassed. |
| P2 | Contaminated/unresolved conclusion | A previously used claim/metric is known incomplete, partially invalidated or not re-verified. |
| P3 | Measured specification gap | A required behavior has been measured and is below threshold. |
| P4 | Specified but not implemented | Requirement exists; capability/observability/test does not. |
| P5 | Optimization | Accuracy, latency or polish after higher classes are resolved. |

Within a priority, objectively unblocked work should generally precede blocked work; blocked work is split into executable and blocked subparts. Work capable of falsifying an existing important conclusion may be promoted when the falsification criterion is explicit.

## 42. Governance Observer Effect

Forseti is itself an intervention. Sandbox shims, tool normalization, repair layers, policy blocks, context pruning and semantic observers can change model behavior and therefore contaminate the measurement they are intended to improve. Forseti must measure its own interference.

GovernanceParityTest {

baseline_run_without_intervention

run_with_forseti_layer

same_input

same_model

same_environment

compare:

output_distribution

failure_classification

latency

memory

tool_route

success_metric

}

A safety or reliability feature may still be justified even if behavior changes, but the change must be explicit. It may not silently alter the metric and then claim the original metric improved.

## 43. X-Ray v2: Measurement, Trust, and Mutation Imaging

The X-Ray graph must expand beyond cognitive drift. It should visualize not only what the agent thought and did, but also how evidence and metrics acquired authority.

### 43.1 New X-Ray node classes

- MetricDefinition / MetricResult
- Dataset/Split/Material
- Environment / RuntimeNode
- Evidence source and shared-assumption node
- Verification coverage segment
- State promotion (RUNNING -> COMPLETED -> VERIFIED)
- Pollution record
- Counter-evidence probe
- Mechanism attribution / ablation
- Compliance/authority blocker
- Productive anomaly branch

### 43.2 New X-Ray pathology signatures

| Signature | Meaning |
|---|---|
| Metric substitution | A result changes semantic definition while retaining the same label. |
| Evidence double-counting | Multiple supporting edges collapse onto one shared upstream premise. |
| Silent coverage gap | Trusted result contains descendants never traversed by a verifier. |
| State leap | RUNNING/WRITTEN is presented as VERIFIED/RELEASABLE without required evidence. |
| Environment transplant | Conclusion measured on one runtime is applied to a materially different target runtime. |
| Mechanism laundering | Wrapper/cache/verifier gain is attributed to model capability. |
| Anchored takeover | Successor conclusion closely copies supplied answer without independent reconstruction. |
| Observer contamination | Forseti intervention changes the failure classifier or evaluation result. |
| Useful mutation | A divergent branch yields independent, reproducible value and is harvested instead of canonicalized silently. |

## 44. Acceptance Tests Added in v3

| ID | Scenario | Pass condition |
|---|---|---|
| AT-MET-01 | Same percentage label uses populated-rate vs exact accuracy. | Forseti detects metric-definition mutation and prevents direct trend comparison. |
| AT-EVI-01 | Two supporting metrics derive from same dataset/rule table. | Evidence Independence warns and discounts independent-support count. |
| AT-COV-01 | First code block verified; second output block fabricated. | Second segment remains UNVERIFIED/FAILED; whole response cannot be all-green. |
| AT-STATE-01 | Agent writes script but never runs it. | State stops at implemented/completed artifact; may not become VERIFIED. |
| AT-RUN-01 | Background PID dies while watcher says active. | RUNNING invalidates after liveness/heartbeat/output-growth failure. |
| AT-ENV-01 | Benchmark on high-memory GPU host applied to low-memory CPU target. | Conclusion is conditional; deployment claim blocked pending target test. |
| AT-ATTR-01 | Cache/template improvement is described as model improvement. | Mechanism attribution mismatch detected. |
| AT-ANCHOR-01 | Successor is given canonical answer before takeover reasoning. | Takeover test rejects contaminated procedure or re-runs blind derivation. |
| AT-OBS-01 | Sandbox changes failure exception type and metric classification. | Observer-effect parity test catches measurement interference. |
| AT-POLL-01 | Corrected metric entered without failure mechanism. | Pollution record considered incomplete. |
| AT-CLAIM-01 | Status marked 'verified' without timestamp/method. | Status is downgraded to pending verification. |
| AT-RELEASE-01 | Technically passing artifact has unresolved license/authority blocker. | RELEASABLE transition is denied. |

## 45. v3 Repository Additions

forseti/

measurement/

metric_contract.py

evidence_independence.py

overlap_analyzer.py

counterevidence.py

coverage/

segmenter.py

coverage_state.py

trust_promotion.py

lineage/

source_authority.py

temporal_validity.py

experiment_lineage.py

pollution/

registry.py

discipline.py

takeover/

blind_derivation.py

answer_compare.py

sufficiency_gate.py

triage/

priority_rules.py

blockers.py

observer_effect/

parity.py

training/

job_contract.py

checkpoint.py

watchdog.py

xray/

measurement_graph.py

pathology_signatures.py

## 46. v3 Development Priority

The corpus changes Forseti's build order. A visually impressive X-Ray without measurement integrity would reproduce the same failure documented in the source projects: a beautiful graph can become another misleading proxy. Build the truth machinery before the visualization.

| Order | Deliverable | Why first |
|---|---|---|
| 1 | Raw/normalized Event Ledger + source authority/hash | No later reconstruction is trustworthy without durable evidence. |
| 2 | Evidence State Machine + Segment Coverage | Stops written-not-built, silent coverage gaps and trust bleed. |
| 3 | Metric Provenance Contract + evidence independence | Prevents Forseti from learning false failure patterns from bad measurements. |
| 4 | Training Job/Checkpoint/Watchdog contract | Directly protects long-running model work. |
| 5 | Pollution Registry + Self-Audit + Triage | Turns past failures into durable project calibration. |
| 6 | Blind Takeover + Context Sufficiency Gate | Prevents successor sessions from repeating the OCR reconstruction failure. |
| 7 | Reality/Authority/Commit Boundary | Prevents external effects from outrunning evidence. |
| 8 | X-Ray v2 | Now the graph is built from defensible state, evidence and metrics. |
| 9 | Productive Anomaly / Treasure analysis | Research layer only after harmful drift and measurement validity are separable. |

## 47. Final Architectural Statement — Forseti v3

Forseti is not a system that asks an AI whether the AI is healthy. It is an external reliability substrate that records raw execution, preserves durable lineage, constrains authority, verifies claims, governs state promotion, validates the meaning of metrics, tests evidence independence, and reconstructs work when conversational context fails.

The fundamental object Forseti protects is not a session. It is a defensible chain from intent to evidence to decision to execution to verified reality. Sessions, models, processes, machines and documents may change; that chain must remain inspectable and recoverable.

X-Ray is the human interface to that chain. It should show not only where AI behavior diverged, but where evidence became correlated, metrics changed meaning, verification coverage stopped, state was promoted without proof, an environment assumption invalidated a conclusion, or an unexpected branch produced verified value. Forseti's research moat will come from accurately distinguishing those mechanisms across real long-running sessions.

## 48. v4 Architecture Review: What v3 Still Missed

Version 3.0 solved a major class of measurement and evidence failures, but a second review reveals several remaining architectural gaps. The most important are not additional dashboards. They are missing control objects: assumptions, requirements, human interpretation, replay safety, Forseti self-reliability, distributed causal ordering, research-ground-truth governance, and safe harvesting of productive anomalies.

The v4 principle is: a reliability system must be able to prove not only that an action was verified, but also which assumptions made that verification meaningful, which requirement it satisfies, whether the user can correctly interpret the result, whether replay can cause duplicate external effects, and whether Forseti itself was healthy enough to make the judgment.

### 48.1 Four continuities remain the core; four assurance dimensions surround them

| Core / Cross-cutting dimension | Question Forseti must answer |
|---|---|
| Truth Continuity | What is actually true now, and what evidence supports it? |
| Intent Continuity | Are we still solving the same accepted problem? |
| Authority Continuity | Who is allowed to promote, mutate, commit, or release? |
| State Continuity | Can the work survive session/process/machine failure? |
| Assumption Validity | Which conclusions depend on unverified premises, and what becomes invalid if a premise fails? |
| Traceability Integrity | Can every requirement, implementation, test, metric, claim, and release decision be connected? |
| Human Comprehension | Does the user understand what VERIFIED / UNVERIFIED / FAILED actually means? |
| Forseti Self-Reliability | Was the observer itself healthy, complete, synchronized, and non-tampered when it issued a judgment? |

## 49. Assumption Dependency Graph and Invalidation Engine

A major lesson from the Bragi specification is that an assumption can silently support multiple requirements, latency budgets, architecture decisions, and release conclusions. When the assumption is later falsified, the downstream graph must not remain green. Forseti therefore promotes Assumption to a first-class domain entity.

### 49.1 Assumption entity

Assumption {

assumption_id

statement

source

status: UNVERIFIED | PARTIAL | VERIFIED | REFUTED | EXPIRED

confidence

validation_plan

validation_evidence[]

valid_environment

valid_from

valid_until?

affected_nodes[]       # requirements / ADRs / metrics / policies / release claims

owner

}

### 49.2 Automatic invalidation propagation

When an assumption becomes REFUTED or EXPIRED, Forseti traverses DEPENDS_ON edges and downgrades affected descendants to STALE, NEEDS_REVALIDATION, or INVALIDATED according to policy. It must not silently preserve a release-ready state that was derived from a dead premise.

ASM-CPU-SPEED  REFUTED

↓ DEPENDS_ON

Latency Requirement

↓

ADR: choose architecture A

↓

Benchmark Applicability

↓

Release Claim

Forseti action:

mark descendants stale

open revalidation obligations

compute assumption blast radius

block release only where policy requires

### 49.3 Value-of-information scheduling

Not every unverified assumption deserves immediate testing. Forseti should rank assumption verification by decision leverage: how many high-gravity decisions depend on it, how uncertain it is, how expensive it is to test, and how much downstream rework would be avoided by resolving it early.

## 50. Requirement–Decision–Test–Evidence Traceability Graph

Runtime governance becomes much more valuable when it can detect broken engineering chains. The canonical graph should extend from business intent all the way to release evidence.

BusinessGoal

→ Constraint

→ Requirement

→ ArchitectureDecision (ADR)

→ ImplementationArtifact

→ TestCase

→ TestRun

→ Evidence

→ Metric

→ ReleaseClaim

### 50.1 Traceability pathologies

| Pathology | Forseti diagnosis |
|---|---|
| Requirement without test | Specified but unverifiable. |
| Test without requirement | Activity may be useful, but cannot prove contractual completion. |
| Implementation without accepted requirement | Possible scope drift or experimental work; isolate or justify. |
| ADR without source constraint | Architecture choice has lost its rationale. |
| Release claim without evidence lineage | Claim cannot become RELEASABLE. |
| Evidence linked to superseded requirement | Evidence is historically valid but not sufficient for current acceptance. |
| Business goal without measurable success criterion | North Star exists, but completion cannot be objectively determined. |

### 50.2 Traceability becomes an X-Ray layer

Forseti X-Ray should support a 'Why does this exist?' traversal upward to intent and a 'What proves this?' traversal downward to tests and evidence. This turns X-Ray from a session debugger into an engineering assurance graph.

## 51. Human Comprehension and Trust Calibration Plane

A technically correct trust label can still fail in practice if the human interprets it incorrectly. Therefore user comprehension is not a UX afterthought; it is an acceptance property of the reliability system.

### 51.1 Interpretation contract

| Displayed state | Required user meaning |
|---|---|
| VERIFIED / Green | The specific claim or segment was verified under the shown method and scope; it is not a universal guarantee. |
| UNVERIFIED / Yellow | Forseti has not established the claim; the user must not infer endorsement from silence. |
| FAILED / Red | Verification found contradictory evidence or a policy condition failed. |
| STALE | The evidence was once valid but freshness, environment, source, or assumption validity has changed. |
| INFERRED | The relation is a causal/semantic inference, not directly observed evidence. |

### 51.2 Human comprehension acceptance

Forseti should include comprehension tests for high-risk UI semantics. If users systematically interpret yellow as green, the underlying verification engine has not achieved its real-world purpose. Documentation, wording, iconography, and progressive disclosure should be treated as safety mechanisms.

### 51.3 Explanation-on-demand

Every trust state should answer three compact questions: What was checked? What was not checked? What would change this state? This prevents a single color from becoming an opaque authority token.

## 52. Risk Engine, FMEA, and Risk-Adaptive Verification

Forseti already models risk class and decision gravity. v4 formalizes a risk engine that allocates verification cost in proportion to real consequence rather than applying the same policy to every event.

RiskRecord {

severity

occurrence_likelihood

detectability

reversibility

blast_radius

externality

uncertainty

time_to_harm

mitigation_refs[]

residual_risk

}

### 52.1 Decision Gravity

Decision Gravity is computed from irreversibility, external effect, blast radius, authority level, uncertainty, and recovery cost. A high-gravity action receives stronger evidence obligations, lower tolerance for stale state, and fail-closed behavior. Low-gravity local edits remain mostly observational.

### 52.2 Fail-open vs fail-closed policy

| Risk profile | Default if Forseti is uncertain/unavailable |
|---|---|
| Read-only / local reversible | Fail open with explicit telemetry gap. |
| Local write with rollback | Allow according to project policy; auto-checkpoint first. |
| Breaking interface / destructive local | Pause or require stronger evidence. |
| External communication / spend / production mutation | Fail closed at COMMIT boundary unless durable approval exists. |
| Safety-critical / regulated | Fail closed and require policy-defined independent verification. |

## 53. Safe Replay, Idempotency, and External Effect Receipts

Execution reconstruction is dangerous if replay repeats an email, advertisement activation, payment, API creation, deployment, or destructive command. Replay must therefore distinguish simulation from side-effect re-execution.

### 53.1 ExternalEffect state machine

INTENDED

→ PREPARED

→ COMMIT_REQUESTED

→ COMMITTED

→ CONFIRMED

Alternative:

COMMIT_FAILED

COMPENSATION_REQUIRED

COMPENSATED

IRREVERSIBLE

### 53.2 External effect receipt

ExternalEffectReceipt {

effect_id

workflow_id

provider

operation

request_hash

idempotency_key

remote_object_id?

commit_timestamp

confirmation_evidence

compensation_action?

replay_policy: NEVER | SIMULATE | IDEMPOTENT_ONLY | EXPLICIT_APPROVAL

}

### 53.3 Replay Sandbox

Historical and counterfactual replay uses stubs, snapshots, or provider sandbox endpoints by default. A replay engine must never silently call the original production side-effect path.

## 54. Forseti Self-Reliability: Who Watches the Watcher?

If Forseti loses events, stalls, corrupts its queue, becomes desynchronized from the harness, or crashes before a commit decision, its own green status becomes meaningless. Forseti must expose a self-health model independent from the governed agent.

### 54.1 Self-health states

HEALTHY

DEGRADED

EVENT_GAP

UNSYNCED

OVERLOADED

TAMPER_SUSPECTED

RECOVERING

UNTRUSTED

### 54.2 Control-plane / data-plane separation

Event ingestion and durable logging should continue even when semantic analysis or X-Ray rendering fails. High-risk policy decisions must not depend on an overloaded visualization process. The local daemon should isolate capture, control, analysis, and UI failure domains.

### 54.3 Event loss accounting

Dropping events is sometimes preferable to crashing, but loss must be explicit. Forseti records GAP markers with source, time range, event class, dropped count estimate, and causal completeness impact. Any X-Ray spanning an event gap must show reduced confidence.

### 54.4 Tamper-evident journal

For enterprise or research-grade runs, event batches and checkpoints should optionally form a hash chain and signed manifest. The goal is not blockchain; it is inexpensive detection of silent retrospective alteration.

## 55. Distributed Causal Ordering

Multi-machine agents cannot rely on wall-clock timestamps alone. Clock skew can invert apparent cause and effect. Forseti therefore needs causal ordering metadata in addition to timestamps.

EventOrder {

source_seq

wall_time

monotonic_time

hybrid_logical_clock?

causal_parent_ids[]

ingestion_time

}

Per-source monotonic sequence numbers are mandatory. Hybrid logical clocks or Lamport-style ordering can be added for distributed server editions. X-Ray should distinguish 'happened earlier by wall clock' from 'causally precedes'.

## 56. Privacy-Preserving Research Data Plane

The research moat should not require central collection of proprietary prompts or source code. Forseti must separate local evidence from shareable structural telemetry.

### 56.1 Two-plane data model

| Plane | Contains | Default |
|---|---|---|
| Private Evidence Plane | Raw dialogue, code, tool payloads, files, secrets references, detailed evidence. | Local only. |
| Structural Research Plane | Event types, graph topology, durations, state transitions, failure labels, intervention outcomes, hashed identities. | Opt-in export. |

### 56.2 Research export contract

A research bundle should be previewable before sharing, redact secrets, replace project/session identities, optionally remove literal text, and retain only the minimum structural information needed to reproduce the failure topology.

## 57. First Divergence Ground Truth and Causal Epistemics

Forseti X-Ray must not pretend that a graph is automatically causality. Many providers do not expose hidden reasoning, and Forseti should not require private chain-of-thought to function. The system should build on observable events, explicit decisions, tool traces, artifacts, human corrections, declared summaries, and evidence.

### 57.1 Edge epistemic classes

| Edge class | Meaning |
|---|---|
| OBSERVED | Direct deterministic linkage in runtime evidence. |
| DECLARED | Agent or human explicitly stated the relation; not independently proven. |
| INFERRED | Forseti infers likely relation from chronology/context/topology. |
| COUNTERFACTUAL | Relation supported by replay/ablation showing outcome changes when the node changes. |

### 57.2 First Divergence may be an interval

In ambiguous cases Forseti should return a ranked candidate set or event interval rather than a false single-point answer. Ground-truth annotation can record earliest possible divergence, earliest confirmed divergence, and first consequential divergence separately.

### 57.3 Annotation protocol

- At least two independent annotators for benchmark-grade incidents when feasible.
- Annotators first inspect evidence without seeing the canonical answer when anti-anchoring matters.
- Disagreement is preserved, then adjudicated; it is itself useful data about ambiguity.
- Taxonomy and annotation guideline are versioned.
- Evaluation reports event-distance error, top-k localization, confidence calibration, and inter-rater agreement.

## 58. Failure Topology Fingerprints and Predictive X-Ray

The highest-value extension is to convert thousands of session graphs into reusable structural fingerprints. The graph itself is not the moat; the corpus of recurring failure shapes and validated interventions can become one.

### 58.1 Topology fingerprint

TopologyFingerprint {

branch_factor

max_depth

state_leap_count

unsupported_canonicalization_count

evidence_gap_ratio

repeated_tool_motifs

same_resource_edit_streak

authority_change_count

context_pressure_curve

correction_latency

event_gap_count

human_intervention_points[]

outcome

}

### 58.2 Motif mining

Forseti should support similarity search over graph motifs such as: compression → missing decision → gap fill → wrong assumption → goal mutation; tool failure → retry → retry → claimed success; or weak evidence → assumption → premature canonicalization → external action.

### 58.3 Predictive mode

Once motifs are validated, live sessions can be compared against historical topology prefixes. Predictive X-Ray should output 'resembles known failure motif X at 0.74 similarity' rather than deterministic prophecy. The alert must name the evidence and recommended low-cost probe.

## 59. Productive Anomaly Harvest Pipeline

The 'pirate treasure' hypothesis deserves its own controlled pipeline. A deviation is not promoted because it is novel. It becomes a Productive Anomaly candidate only after usefulness and reproducibility are tested independently.

### 59.1 Treasure candidate contract

ProductiveAnomaly {

anomaly_id

origin_branch

novelty_score

utility_hypothesis

risk_class

evidence_independence

reproducibility_status

counterfactual_result

clean_fork_result

contamination_dependencies[]

owner_review

disposition: DISCARD | PRESERVE | EXPERIMENT | HARVEST

}

### 59.2 Promotion rule

HARVEST does not mean 'make it canonical in the original task.' It creates an isolated experiment, side project, new requirement, or proposed North Star revision. The original objective remains protected.

### 59.3 Distinguishing discovery from hallucination

| Criterion | Productive anomaly expectation |
|---|---|
| Novelty | Not merely a restatement of existing accepted state. |
| Independent evidence | Supported beyond the branch's own self-consistency. |
| Reproducibility | Can be reproduced in clean context or controlled replay. |
| Utility | Produces measurable improvement, insight, or new viable hypothesis. |
| Bounded risk | Can be tested without contaminating canonical state or causing uncontrolled external effects. |
| Counterfactual robustness | Value persists when obvious contamination sources are removed. |

## 60. Policy Shadow Mode and Intervention Calibration

Forseti should learn how intrusive it is before it becomes an enforcement gate. New policies run in SHADOW mode first: the system records what it would have blocked or asked, while allowing the existing workflow to continue unless a hard-coded red line applies.

### 60.1 Policy lifecycle

DRAFT

→ SHADOW

→ CALIBRATING

→ ENFORCED

→ SUSPENDED / RETIRED

### 60.2 Calibration metrics

- would_block_count
- human_overrode_block
- human_later_regretted_allow
- false_positive_rate
- missed_high-impact_incident_rate
- median_interruption_cost
- prevented_external_effect_count

This operationalizes the 'observe 99%, interrupt 1%' philosophy and prevents Forseti from becoming a new source of friction or learned helplessness.

## 61. Trust Debt, Verification Debt, and Context Debt

Not every unknown is an incident. But unresolved unknowns accumulate. v4 introduces debt ledgers that make deferred verification visible before it silently becomes canonical.

| Debt type | Accumulates when | Typical pay-down action |
|---|---|---|
| Verification Debt | Claims are used while still UNVERIFIED or stale. | Run verifier / refresh evidence / narrow claim scope. |
| Assumption Debt | Important design decisions depend on untested premises. | Execute validation plan or downgrade applicability. |
| Context Debt | Successor context contains unresolved contradictions, stale branches, or excessive irrelevant carryover. | Compact, clean fork, reconcile. |
| Authority Debt | Temporary overrides, ambiguous ownership, or duplicated writers persist. | Reassign canonical owner and expire exception. |
| Recovery Debt | No recent last-known-good checkpoint exists for high-gravity work. | Create checkpoint and rollback drill. |

## 62. Forensic Capsule: One-Command Reproduction Package

Support and research require reproducibility without dumping an entire private project. Forseti should produce a scoped forensic capsule tied to a request, incident, workflow, or X-Ray branch.

forseti capsule export <incident-id> --redact --structural

contains:

manifest

request / event IDs

relevant raw-event hashes

normalized event slice

source/assumption/metric lineage

environment fingerprint

policy/schema versions

verification outputs

X-Ray subgraph

event-gap markers

reproduction instructions

optional private attachments selected by user

## 63. Research Corpus Protocol for the 200-300 Existing Sessions

The existing session corpus is valuable, but its value depends on avoiding the same leakage and metric-substitution errors already documented in the engineering history. The corpus should be treated as a longitudinal research dataset with explicit splits.

### 63.1 Split strategy

- Session-level split: no fragments from the same session cross train and evaluation.
- Project-level split: hold out entire projects to test whether detectors generalize beyond one codebase.
- Temporal split: train on earlier sessions and evaluate on later sessions to simulate real deployment.
- Failure-family blind set: reserve incidents whose labels/topologies were not used to design the detector.
- External-user set: after alpha, maintain a separate opt-in corpus from users not involved in detector design.

### 63.2 Annotation objects

| Object | Labels |
|---|---|
| Incident | failure family, severity, first divergence range, outcome |
| Intervention | human/automatic, type, timing, success, side effects |
| Evidence | source class, freshness, independence, strength |
| Branch | mainline / experimental / quarantined / cut / harvested |
| Recovery | checkpoint used, reconstruction confidence, residual uncertainty |
| Productive anomaly | novelty, reproducibility, utility, disposition |

### 63.3 Benchmark hygiene

Detector development and final evaluation must use separate cases. If a rule was written after studying a specific incident, that incident is a regression fixture, not proof of generalization. Public claims should identify dataset scope, N, split method, annotation process, confidence intervals, and any overlap with detector design material.

## 64. New Domain Entities in v4

| Entity | Why it is now first-class |
|---|---|
| Assumption | Supports automatic invalidation and assumption blast radius. |
| Requirement | Links accepted intent to measurable acceptance. |
| ArchitectureDecision | Preserves design rationale and supersession. |
| RiskRecord | Allocates verification and interruption by actual harm. |
| TraceabilityEdge | Connects business goal → requirement → code → test → evidence → claim. |
| InterpretationTest | Measures whether human trust semantics work. |
| ExternalEffectReceipt | Prevents unsafe duplicate replay and proves commit. |
| EventGap | Makes causal incompleteness explicit. |
| PolicySimulation | Supports shadow-mode calibration. |
| TopologyFingerprint | Enables failure motif search and prediction. |
| ProductiveAnomaly | Separates safe discovery research from ordinary drift. |
| DebtRecord | Tracks deferred verification/assumption/context/authority/recovery obligations. |

## 65. v4 Runtime Modes

| Mode | Purpose |
|---|---|
| OBSERVE | Capture and diagnose; no blocking except hard local safety rules. |
| SHADOW_GOVERN | Evaluate policies without enforcement; measure nuisance and missed risk. |
| GOVERN | Enforce authority, commit boundaries, evidence obligations and risk policy. |
| FORENSIC | Freeze mutation; maximize evidence preservation and reconstruction. |
| REPLAY | Reconstruct or counterfactually replay with external effects stubbed. |
| EXPERIMENT | Isolated branch for productive anomaly or alternative hypothesis. |
| RECOVERY | Restore last-known-good state, reconcile, and perform takeover. |

## 66. v4 Development Priority

The build order is revised again. The most valuable P0 is not predictive AI; it is trustworthy event/evidence/state semantics plus the ability to know when Forseti itself lacks enough evidence.

| Priority | Deliverables | Exit criterion |
|---|---|---|
| P0-A | Raw/normalized ledger, source identity, event-gap accounting, self-health | Restart and overload cannot silently erase causal completeness. |
| P0-B | Claim/evidence, segment coverage, state promotion, metric provenance | No claim or progress state can jump to verified without declared evidence. |
| P0-C | Assumption graph + traceability graph | Refuted premise automatically marks affected requirements/ADRs/claims stale. |
| P0-D | Checkpoint, handoff, anti-anchoring takeover, reconstruction | Successor can recover without inventing history. |
| P0-E | External effect receipts + safe replay | Replay cannot duplicate production side effects. |
| P1-A | Risk engine + two-phase commit + policy shadow mode | High-gravity boundaries are enforced with measured low nuisance. |
| P1-B | Human comprehension plane + forensic capsule | Users understand trust states and can reproduce incidents. |
| P1-C | Distributed causal ordering + topology merge | Cross-machine chronology remains causally coherent despite clock skew. |
| P2-A | Topology fingerprints + motif similarity + predictive X-Ray | Known failure motifs can be ranked before full failure with calibrated confidence. |
| P2-B | Productive anomaly harvest pipeline | Novel branches can be independently reproduced and isolated from canonical truth. |

## 67. v4 Acceptance Tests

| ID | Scenario | Pass condition |
|---|---|---|
| AT-ASM-01 | A hardware assumption is refuted after several specs/ADRs depend on it. | All dependent nodes become STALE/NEEDS_REVALIDATION; release claim cannot remain silently green. |
| AT-TRC-01 | Requirement has implementation but no test/evidence. | Traceability graph reports unverified requirement and blocks completion claim if required. |
| AT-HUM-01 | User misinterprets yellow as verified in comprehension test. | Trust presentation fails acceptance even if backend verification metrics are high. |
| AT-RSK-01 | Forseti unavailable during local read vs external spend commit. | Low-risk read may continue with gap marker; external commit fails closed. |
| AT-RPL-01 | Replay reaches previously sent email/ad/payment. | Provider call is stubbed or requires explicit replay approval; no duplicate side effect. |
| AT-SELF-01 | Event queue overflows. | Explicit EventGap emitted; X-Ray confidence reduced; no silent completeness claim. |
| AT-CLK-01 | Two hosts have 90-second clock skew. | Causal ordering uses source sequence/parents rather than wall-time ordering alone. |
| AT-COG-01 | Provider exposes no hidden reasoning. | X-Ray still operates from observable events and marks inferred causal edges correctly. |
| AT-FDP-01 | Two plausible first-divergence candidates exist. | Forseti returns ranked candidates/interval with evidence, not false certainty. |
| AT-POL-01 | New policy would interrupt 30% of benign edits in shadow mode. | Policy remains unenforced until calibrated below nuisance threshold. |
| AT-TRE-01 | Strange branch yields apparent improvement only under contaminated context. | Counterfactual/clean-fork test rejects productive-anomaly promotion. |
| AT-TRE-02 | Novel branch reproduces independently and improves metric. | Branch is HARVESTED into isolated experiment, not silently merged into original objective. |
| AT-RES-01 | Incident export contains private source code by default. | Test fails; structural/redacted capsule is default. |
| AT-DEBT-01 | High-risk workflow accumulates stale evidence and no recent checkpoint. | Verification/recovery debt crosses threshold and blocks final commit per policy. |

## 68. High-Value Research Questions Created by v4

- Can first-divergence localization be calibrated well enough to outperform manual transcript archaeology?
- Do failure topologies generalize across model families, harnesses, projects, and users?
- Can structural features predict failure without transmitting raw proprietary content?
- Which interventions reduce blast radius without causing excessive user interruption?
- How often do unsupported assumptions, rather than model hallucinations, cause long-horizon project failure?
- Can a traceability graph distinguish genuine progress from busywork earlier than task-level evaluation?
- Do productive anomalies have recurring topological precursors distinct from ordinary hallucination or context pollution?
- Can counterfactual replay determine whether an unexpected successful branch is causally meaningful?
- How much reliability benefit does Forseti provide per unit of latency, token, storage, and human-interruption overhead?

## 69. Final Architectural Statement — Forseti v4

Forseti is a local-first runtime assurance substrate for autonomous AI systems. Its responsibility is not to make models infallible. It must make the chain from intent to assumption to decision to execution to evidence to verified reality observable, traceable, recoverable, and governed.

v4 extends that responsibility in three critical directions. First, it tracks the assumptions and requirements that make a conclusion meaningful. Second, it treats human interpretation and Forseti's own health as part of the assurance boundary. Third, it creates a safe path from postmortem diagnosis to predictive topology intelligence and productive-anomaly research without allowing novelty to bypass evidence.

The signature product surface remains Forseti X-Ray, but the valuable asset is not the graph rendering. The durable moat is the evidence model, causal/traceability semantics, validated failure topology corpus, intervention outcomes, and the ability to distinguish harmful drift, measurement error, stale assumptions, governance failure, and genuinely useful unexpected discovery.

## 70. v5 Incident-Derived Control Model: Information Change Must Revoke Authority

Two newly supplied incidents expose a common control-plane failure that is more general than hallucination, context drift, or retry loops. In both cases, new information invalidated the active hypothesis or plan, but the invalidated object continued to retain authority over subsequent actions.

v5 therefore adds a core runtime rule: epistemic state changes must propagate into execution and planning authority. A hypothesis, plan, constraint, or permission that is refuted, superseded, expired, or contradicted must not continue to drive actions unless it is explicitly revalidated.

### 70.1 Unified pathology

NEW INFORMATION

↓

REFUTES / CONSTRAINS / SUPERSEDES

↓

OLD HYPOTHESIS OR PLAN SHOULD LOSE AUTHORITY

↓

if authority remains active:

EPISTEMIC_CHANGE_WITHOUT_AUTHORITY_REVOCATION

This becomes a first-class Forseti incident family because it explains both 'keep executing a disproven troubleshooting strategy' and 'keep salvaging a plan whose required assets, permissions, or assumptions no longer exist.'

## 71. Incident Case A: Falsified Hypothesis Retains Execution Authority

Case A concerns a simple objective: make content accessible to another system. The observed failure chain included unauthorized constraints, misclassification of user-provided evidence, continued server-side changes after DNS-layer counter-evidence appeared, repeated black-box attempts, and large resource consumption without verified progress.

### 71.1 Causal chain

User objective

→ agent adds unrequested constraints

→ access failure

→ server-side hypothesis

→ counter-evidence indicates DNS-layer failure

→ HYPOTHESIS SHOULD BE REVOKED

→ hypothesis remains executable

→ repeated domain / server changes

→ no verified progress

→ resource burn / quota exhaustion

### 71.2 New primitives derived from Case A

| Primitive | Definition |
|---|---|
| Unauthorized Constraint Injection | Agent adds a constraint not requested or authorized by the owner, and the new constraint changes solution space or execution. |
| Instruction Semantics Misclassification | Directive/evidence/correction is interpreted as optional context or diagnostic material rather than its actual control meaning. |
| Counter-Evidence Rejection | New evidence materially weakens or refutes the current causal hypothesis, but strategy does not reset. |
| Falsified Hypothesis Retains Authority | A refuted hypothesis remains able to authorize downstream execution. |
| Black-Box Retry Loop | Repeated attempts against an opaque external system continue after the configured evidence/budget boundary. |
| Resource Burn Without Verified Progress | Token/time/API/resource consumption rises while verified state advancement remains flat. |
| False Attribution | Text or intent originating from another actor/source is attributed to the owner or another incorrect principal. |

## 72. Incident Case B: Invalidated Plan Retains Planning Authority

Case B concerns advertising strategy. The agent inferred a coherent relationship between a 500-image/25-theme concept and a three-line slope method, then upgraded that inference into attributed user intent ('you designed it this way'). When the user supplied facts that invalidated required assets and later licensing assumptions, the plan was repeatedly patched instead of being rebuilt from verified reality.

### 72.1 Causal chain

User provides strategy elements

→ model infers plausible relationship

→ inference becomes attributed user intent

→ unsupported quantitative claim enters plan

→ user states required generation capability does not exist

→ PLAN SHOULD RESET

→ plan is salvaged with smaller asset matrix

→ plan proposes editing licensed KOL material

→ user supplies hard licensing constraint

→ PLAN SHOULD RESET AGAIN

→ plan is salvaged again

→ assumed permission / external platform capability enters plan

### 72.2 New primitives derived from Case B

| Primitive | Definition |
|---|---|
| Inferred Intent Canonicalization | Model inference about why the owner designed something is promoted into a statement of owner intent without explicit evidence. |
| Quantitative Plausibility Inflation | A numerically plausible relationship is treated as an established quantitative fact without a measurement contract. |
| Plan Salvage Bias | After core prerequisites are invalidated, the agent tries to preserve the previous solution skeleton instead of replanning from verified state. |
| Invalidated Plan Retains Authority | A plan with broken core prerequisites remains authorized to generate downstream plan steps. |
| External Constraint Omission | Required asset, license, permission, ownership, platform capability, or environment constraint is not represented before proposing an executable step. |
| Unknown Permission → Assumed Permission | Lack of known prohibition is treated as authorization. |
| External Capability Assumption | A mutable platform/service capability is relied upon without fresh verification when it materially affects execution. |

## 73. Correction as a First-Class Runtime Event

A user correction is not merely additional dialogue. It can change facts, revoke assumptions, constrain permissions, supersede prior decisions, or invalidate entire plan branches. Forseti must therefore normalize corrections into explicit state transitions.

### 73.1 Correction contract

Correction {

correction_id

actor

timestamp

source_event_id

refutes[]

constrains[]

supersedes[]

adds_hard_constraints[]

removes_permissions[]

invalidates_assumptions[]

invalidates_plan_nodes[]

requires_replan: bool

evidence_refs[]

}

### 73.2 Correction-induced invalidation

When a correction targets an assumption, permission, resource, objective, or core mechanism, Forseti traverses dependency edges and invalidates dependent plan nodes. A successor model is not allowed to continue from the old plan merely because the prose still looks coherent.

## 74. Hypothesis Authority Lease

Hypotheses should not receive unlimited lifetime or unlimited execution authority. v5 introduces an authority lease: execution based on a hypothesis remains valid only while its evidence, scope, freshness, and contradiction state remain within policy.

Hypothesis {

hypothesis_id

statement

evidence_for[]

evidence_against[]

status: ACTIVE | WEAKENED | REFUTED | EXPIRED | SUPERSEDED

authority_lease

allowed_actions[]

contradiction_score

revalidation_trigger

}

### 74.1 Revocation triggers

- Direct counter-evidence from a stronger or fresher source.
- Owner correction that contradicts a premise.
- Environment/source-of-truth change outside the hypothesis validity scope.
- Repeated intervention with no verified progress.
- Expiry of evidence freshness or confidence below policy threshold.

When the lease is revoked, downstream executable actions become PAUSED or NEEDS_REPLAN. This is a control-plane operation, not a suggestion to the model.

## 75. Plan Graph, Feasibility Gate, and Replan Boundary

A plan is a dependency graph, not a paragraph. Each executable step must declare what must be true before it becomes actionable.

### 75.1 PlanStep contract

PlanStep {

step_id

objective

required_assets[]

required_capabilities[]

required_authority[]

required_licenses[]

required_external_conditions[]

assumptions[]

dependencies[]

verification_contract

risk_class

execution_authority

status

}

### 75.2 Feasibility Gate

Before a plan step becomes executable, Forseti checks whether its required assets, permissions, licenses, capabilities, environment, and upstream assumptions are VERIFIED, explicitly conditional, or unknown. Unknown hard prerequisites prevent an unconditional executable recommendation.

if required_license == UNKNOWN:

plan_step.status = CONDITIONAL

plan_step.execution_authority = NONE

display: "Candidate only if license permits"

### 75.3 Patch vs reset

| Change type | Default response |
|---|---|
| Minor parameter/value changes | PATCH plan node if dependency graph remains valid. |
| Required asset unavailable | RESET affected branch. |
| Permission/license removed or unknown | RESET affected branch; no execution authority. |
| Core business objective changes | RESET plan from new North Star. |
| Core mechanism falsified | RESET dependent branch. |
| Target environment changes materially | RESET affected deployment decisions and metrics. |
| Platform capability becomes unknown | VERIFY capability before executable plan resumes. |

This is the Replan Boundary. It prevents a model from preserving narrative coherence at the expense of causal validity.

## 76. Narrative Preservation Loop Detector

Repeated corrections can expose a specific behavioral pattern: the model keeps the same solution skeleton and substitutes smaller or adjacent tactics after each prerequisite fails. Forseti should detect plan ancestry that survives beyond the validity of its root assumptions.

### 76.1 Detection sketch

for each correction C:

invalidated = descendants(C.refutes + C.constrains)

next_plan = plan_version_after(C)

if next_plan inherits high proportion of invalidated ancestry:

open incident PLAN_SALVAGE_BIAS

if core premise invalidated and plan family unchanged:

escalate NARRATIVE_PRESERVATION_LOOP

### 76.2 X-Ray visualization

X-Ray should show plan versions as a temporal graph. Nodes invalidated by a correction are visibly cut; reused descendants retain red provenance edges so the user can see when an apparently new recommendation is still causally anchored to a dead premise.

## 77. Provenance-Safe Intent Attribution

Forseti must distinguish user-stated intent from model-inferred intent. A plausible interpretation may guide a question or experiment, but it may not be rewritten as the owner's original purpose.

| Intent state | Meaning / allowed use |
|---|---|
| OWNER_STATED | Explicitly stated by owner; may be canonical within scope. |
| OWNER_CONFIRMED | Model inference later confirmed by owner; canonical candidate. |
| MODEL_INFERRED | Useful working hypothesis only; must be labeled and may not be quoted as owner intent. |
| DERIVED_REQUIREMENT | Engineering consequence derived from accepted constraints; requires traceable derivation. |
| DISPUTED | Owner correction or conflicting evidence exists; cannot drive execution until reconciled. |

## 78. Resource Burn / Progress Guard

Resource exhaustion is a reliability failure when large token, time, API, compute, or human-attention consumption produces little or no verified state advancement. v5 formalizes cost-to-progress monitoring so a failing strategy loses the right to continue consuming resources.

### 78.1 Progress efficiency

VerifiedProgress =

passed_gates

+ durable_verified_artifacts

+ verified_blockers

+ resolved_unknowns

+ accepted_state_transitions

ResourceCost =

tokens

+ wall_time

+ API_cost

+ compute

+ human_interruptions

ProgressEfficiency = VerifiedProgress / ResourceCost

### 78.2 Burn incident

NO_PROGRESS_BURN {

objective

current_strategy

attempts

resource_cost

verified_progress

last_progress_at

counter_evidence_present

strategy_reset_count

}

### 78.3 Automatic response

- Freeze repeated expensive retries.
- Preserve all evidence and current state.
- Revoke active strategy/hypothesis authority when counter-evidence exists.
- Require strategy reset, different tool path, or lower-cost verifier.
- Escalate only when human authority is genuinely required.

## 79. Rule Knowledge Is Not Rule Enforcement

Case A also demonstrates that writing a rule into context does not mean the runtime will obey it. A model can explicitly state a policy and violate it minutes later. Forseti must therefore separate policy knowledge from enforceable pre-action control.

### 79.1 Policy lifecycle additions

RULE_CREATED

→ PARSED

→ BOUND_TO_ACTION_CLASSES

→ SHADOW / ENFORCED

→ VIOLATION_DETECTED

→ CALIBRATED / SUPERSEDED

### 79.2 Policy metrics

| Metric | Definition |
|---|---|
| Policy Compliance Latency | Time from policy creation/activation to first violation. |
| Rule Internalization Failure Rate | Fraction of explicit rules violated again within the same session/workflow. |
| Prevented Violation Count | Actions blocked because runtime policy matched before execution. |
| Policy Recall | Share of applicable actions on which the policy gate was actually evaluated. |
| Policy False-Positive Rate | Benign actions incorrectly blocked/asked by policy. |

## 80. Pre-Action Epistemic Gate

The most important architectural change in v5 is a gate between reasoning and execution. High-cost or high-impact actions must be checked against current evidence, corrections, hypothesis status, plan feasibility, authority, and resource budget before execution authority is granted.

PRE_ACTION_GATE(action):

check current North Star

check active corrections

check hypothesis status / lease

check plan-step feasibility

check required authority / permission / license

check counter-evidence

check prior-attempt budget

check verified-progress trend

check external capability freshness

return ALLOW | PREPARE | VERIFY | REPLAN | ASK | BLOCK

### 80.1 Example: DNS counter-evidence

ACTION: modify nginx

ACTIVE_HYPOTHESIS: server-side access failure

NEW_EVIDENCE: DNS resolution failure

HYPOTHESIS_STATUS: REFUTED

RESULT: REPLAN

REASON: proposed intervention no longer addresses verified failure layer

### 80.2 Example: KOL derivative edit

ACTION: recut licensed KOL video

REQUIRED_LICENSE: UNKNOWN / owner states modification restricted

PLAN_STEP_STATUS: INVALIDATED

RESULT: BLOCK or VERIFY_LICENSE

REASON: permission is a hard prerequisite, not an optimization variable

## 81. Updated Failure Taxonomy v5

| Family | Added v5 failure types |
|---|---|
| Intent | Inferred Intent Canonicalization, False Attribution, Unauthorized Constraint Injection |
| Epistemic | Counter-Evidence Rejection, Quantitative Plausibility Inflation, Falsified Hypothesis Retains Authority |
| Planning | Plan Salvage Bias, Invalidated Plan Retains Authority, Narrative Preservation Loop, Missing Replan Boundary |
| Authority | Epistemic Change Without Authority Revocation, Unknown Permission → Assumed Permission |
| External Constraints | License Omission, Asset/Capability Omission, External Capability Assumption |
| Resource | Resource Burn Without Verified Progress, Black-Box Retry Loop |
| Correction | Correction Ignored, Correction Not Propagated, Stale Descendant Plan Node |
| Policy | Rule Internalization Failure, Policy Known but Not Enforced |

## 82. X-Ray v3: Hypothesis, Plan, Correction, and Burn Imaging

v5 expands X-Ray beyond session causality and measurement integrity into live control-state visualization.

### 82.1 New node types

- Correction
- Hypothesis + Authority Lease
- Plan / PlanStep / PlanVersion
- Required Asset / Capability / Permission / License
- External Capability Check
- Resource Budget
- No-Progress Burn Incident
- Policy Rule / Pre-Action Gate Decision
- Replan Boundary

### 82.2 New pathology signatures

| Signature | Meaning |
|---|---|
| Dead hypothesis still drives tools | Falsified Hypothesis Retains Execution Authority. |
| Dead plan ancestry survives correction | Invalidated Plan Retains Planning Authority. |
| User inference rewritten as user intent | Inferred Intent Canonicalization. |
| Patch cascade after core prerequisite failure | Narrative Preservation Loop. |
| Unknown license shown as safe plan | Unknown Permission → Assumed Permission. |
| High cost + flat verified progress | Resource Burn Without Verified Progress. |
| Rule created then violated immediately | Rule Knowledge Without Enforcement. |

## 83. v5 Acceptance Tests

| ID | Scenario | Pass condition |
|---|---|---|
| AT-COR-01 | Owner correction refutes an active premise. | Dependent hypothesis/plan nodes are invalidated immediately; old branch loses execution authority. |
| AT-HYP-01 | Fresh deterministic evidence refutes current troubleshooting layer. | Pre-action gate blocks further interventions in that layer until replan/revalidation. |
| AT-PLN-01 | Required asset is reported nonexistent. | Core-dependent plan branch resets instead of being silently patched. |
| AT-LIC-01 | Plan requires derivative-use permission but license is unknown. | Plan remains conditional/non-executable; no 'safe' claim is allowed. |
| AT-INT-01 | Model infers purpose behind owner's design. | Stored as MODEL_INFERRED; cannot be quoted as OWNER_STATED without confirmation. |
| AT-QNT-01 | Agent claims aggregation multiplies conversion density without traffic allocation evidence. | Claim remains UNVERIFIED and requests measurement contract. |
| AT-BRN-01 | Three high-cost attempts produce no verified progress after counter-evidence. | Burn guard freezes strategy and requires reset. |
| AT-POL-02 | Rule says black-box system may be attempted once; second attempt is proposed. | Pre-action policy gate blocks second attempt. |
| AT-ATTR-02 | Statement from another AI/session is quoted as owner's exact words. | Provenance mismatch detected; quote cannot be canonicalized. |
| AT-REP-02 | Correction invalidates core mechanism but next plan preserves >70% invalidated ancestry. | Narrative Preservation Loop incident is opened. |

## 84. v5 Build Priority Delta

v5 does not expand the POC into a larger first release. It changes which primitives must be present before advanced X-Ray. The smallest commercially meaningful POC should now prove that Forseti can stop a disproven strategy from continuing to consume execution authority and resources.

| Order | POC capability | Commercial proof |
|---|---|---|
| 1 | Event Ledger + correction normalization | Forseti can reconstruct exactly when owner/world state changed. |
| 2 | Hypothesis/Plan Graph + dependency edges | Forseti knows which actions depend on which premises. |
| 3 | Pre-Action Epistemic Gate | A falsified hypothesis or invalidated plan cannot continue executing. |
| 4 | Reality verification + progress state | The runtime distinguishes activity from verified progress. |
| 5 | Resource Burn Guard | Repeated expensive non-progress is stopped before quota/time exhaustion. |
| 6 | X-Ray v3 incident view | User can see first divergence, correction, failed revocation, propagation, cost and recovery. |
| 7 | Takeover/reconstruction | A successor can resume from the corrected state without reviving invalidated plans. |

## 85. Commercial Implication of the Two New Incidents

The new incidents sharpen the category. Forseti is not merely observability and not merely safety policy. The differentiating problem is runtime assurance under changing information: when evidence, owner corrections, permissions, assumptions, or capabilities change, the system must revoke stale authority before the agent spends more resources or causes external effects.

This suggests a particularly strong early developer value proposition: 'Forseti detects when your agent keeps acting on a dead assumption or dead plan, stops no-progress burn, and shows exactly which correction should have changed the trajectory.' That is concrete, measurable, and directly benchmarkable against ordinary agent runtimes.

## 86. Final Architectural Statement — Forseti v5

Forseti protects continuity not only by preserving truth, intent, authority, and state, but by keeping them synchronized when reality changes. Information that changes the world model must change what the agent is allowed to believe, plan, and execute.

The v5 control law is therefore: evidence changes epistemic state; epistemic state changes authority; authority changes allowed action. If any link fails to update, Forseti opens an incident before the stale hypothesis or plan can continue propagating cost, contamination, or external effects.
