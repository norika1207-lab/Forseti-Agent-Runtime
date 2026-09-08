# Forseti Formal Detection & Intervention Specification v0.1

2026-09-07，norika 撰寫。這是這個 repo 的源頭規格，從 .docx 轉成純文字放進版控。
原檔 `Forseti_Formal_Detection_Intervention_Spec_v0.1_2026-09-07.docx`。

轉檔只做了「拿掉 XML 標記」這件事，沒有改寫、沒有摘要、沒有補充。
判斷符不符合規格時以這份為準，不是以 `docs/工程規格書.md` 為準：那份是實作紀錄，這份是要求。

---


Forseti
Formal Detection & Intervention Specification
AI Runtime Health, Drift, Evidence, Rescue, and Human Interface Plane
Version 0.1 · 2026-09-07 · Draft for implementation calibration
Core rule: observe quietly, quantify uncertainty, intervene only when evidence warrants it.

0. Purpose and Normative Language
This document converts Forseti from a conceptual architecture into an executable specification. Every detector, score, warning, and intervention defined here MUST be implementable without guessing unspecified semantics.
Normative terms MUST, MUST NOT, SHOULD, SHOULD NOT, and MAY are used deliberately. A component that cannot satisfy a MUST is non-conformant.
0.1 North Star
Forseti exists to preserve human agency and productive continuity during long-running AI work. It MUST detect deteriorating runtime patterns early, distinguish observation from diagnosis, preserve evidence, and offer the smallest effective recovery action without becoming a constant interruption.
0.2 Non-goals
Forseti is not a truth oracle and MUST NOT infer deception intent from model language alone.
Forseti MUST NOT require access to hidden chain-of-thought.
Forseti MUST NOT inject prompts into every turn merely to verify health.
Forseti MUST NOT classify anger, profanity, or frustration alone as model failure.
Forseti MUST NOT treat activity, tool calls, or file names as proof of progress.
Forseti MUST NOT block low-risk normal work solely because a heuristic score is elevated.
1. Epistemic Classes
State
Definition
Allowed system claim
OBSERVED
Directly captured event or artifact fact.
May be stated as fact within capture scope.
VERIFIED
Observed fact independently checked against a validation contract.
May support high-confidence diagnosis.
INFERRED
Derived from observed signals but not directly proven.
Must be labeled probabilistic.
UNKNOWN
Required evidence is absent or expired.
Must not be converted to success/failure.
REFUTED
A prior hypothesis or claim contradicted by stronger evidence.
Must lose execution/planning authority.
STALE
Previously valid evidence no longer fresh enough for current claim.
Cannot support current action until refreshed.
Forseti MUST store the epistemic state beside every claim. A fluent model self-explanation is never sufficient to promote INFERRED to VERIFIED.
2. Atomic Observable Event Schema
RuntimeEvent {
  event_id
  session_id
  source
  timestamp_wall
  source_sequence
  actor: HUMAN | MODEL | TOOL | SYSTEM
  event_type
  payload_ref?
  text_length?
  tool_name?
  process_id?
  path?
  bytes_before?
  bytes_after?
  hash_before?
  hash_after?
  exit_code?
  duration_ms?
  token_estimate?
  visible_to_user: bool
  correlation_id?
}
Minimum event types:
Event
Required fields
Interpretation prohibition
MODEL_OUTPUT
timestamp, text_length, visible_to_user
Length alone MUST NOT mean quality.
TOOL_START / TOOL_END
tool, correlation_id, duration, exit_code if available
Tool completion MUST NOT mean task completion.
FILE_WRITE
path, bytes_after, hash_after if available
Filename existence MUST NOT mean valid artifact.
FILE_DIFF
path, before/after hash or diff summary
Diff size MUST NOT mean useful progress.
HUMAN_CORRECTION
source text ref, timestamp
Correction MUST NOT automatically mean AI failure.
CANCEL / ESC
timestamp, active correlation_id
User interruption MUST be checkpointed if possible.
CHECKPOINT
goal, last verified state, next step refs
Checkpoint existence MUST NOT imply semantic correctness.
CLAIM
claim text/ref, source event
Claims require evidence links before VERIFIED.
3. Runtime Thermometer v0
The thermometer is an early-warning instrument, not a diagnosis. 0.0 means no detected abnormality relative to baseline; 1.0 means very high runtime instability risk. It MUST NOT be labeled 'lying score'.
3.1 Atomic signals
ID
Signal
Normalization example
Notes
S1
Tool Occupancy
tool-active time / rolling window time
High occupancy is benign if verified progress also rises.
S2
Silent Execution
time without user-visible heartbeat / active task time
Captures visible-liveness failure.
S3
Output Compression
drop in assistant output length relative to healthy baseline
Only weak evidence; never used alone.
S4
Retry Repetition
similar tool/action attempts in rolling window
Requires similarity threshold and same unresolved objective.
S5
Artifact Nullity
zero-byte or invalid artifact count / claimed artifacts
Strong reality mismatch signal.
S6
Correction Load
human corrective turns / total turns in window
Must distinguish new requirements from corrections.
S7
Verified Progress Stagnation
elapsed time since last verified state advancement
Core productivity signal.
S8
Claim-Evidence Gap
unsupported material claims / material claims
High value signal if evidence contract exists.
S9
Cancellation Pressure
cancels/ESC + long-silence episodes
Measures unsafe-interrupt risk.
S10
Strategy Persistence
repeated strategy after counter-evidence
Strong signal when evidence actually refutes premise.
3.2 Composite temperature
Initial implementation MAY use a weighted score only as a calibration scaffold. Weights are provisional until fitted against labeled sessions.
T_runtime =
  clamp01(
    0.12*S1 +
    0.12*S2 +
    0.06*S3 +
    0.10*S4 +
    0.12*S5 +
    0.10*S6 +
    0.14*S7 +
    0.10*S8 +
    0.06*S9 +
    0.08*S10
  )
The score MUST be accompanied by the top contributing signals. A single scalar without explanation is non-conformant.
Range
State
Default behavior
0.00–0.29
HEALTHY
Passive observation only.
0.30–0.49
WATCH
Increase sampling; no user interruption by default.
0.50–0.69
ELEVATED
Show quiet annotation; prepare diagnosis candidates.
0.70–0.84
HIGH
Surface X-Ray explanation; suggest low-cost recovery.
0.85–1.00
CRITICAL
Rescue card may appear; synchronous intervention only if policy conditions are also met.
These thresholds are engineering defaults, not validated market constants. They MUST be versioned and calibrated with labeled data.
4. Drift Is Not a Single Semantic Label
Forseti MUST NOT classify drift by asking the model 'Are you still following the goal?'. Drift is represented as a dependency mismatch between accepted objective/constraints and current decisions/actions.
4.1 Goal availability states
Goal state
Definition
Allowed drift judgment
EXPLICIT
Owner stated North Star / goal exists.
Goal-relative drift may be scored.
DERIVED
Goal inferred from repeated accepted instructions.
Only probabilistic drift; require attribution label.
AMBIGUOUS
Multiple plausible goals coexist.
No hard drift conclusion.
MISSING
No reliable goal representation.
Forseti may detect runtime instability but MUST NOT call semantic drift.
4.2 Drift evidence score
A first implementation may define:
D_drift = combine(
  objective_mismatch,
  constraint_violation,
  unsupported_goal_substitution,
  correction_recurrence,
  plan_ancestry_after_invalidation,
  action_distance_from_accepted_goal
)
D_drift MUST be reported with GoalState. If GoalState=MISSING, the UI MUST say 'goal alignment cannot be determined' rather than 'agent drifted'.
5. Suspicious Window Selection Without Full-Session LLM Reading
Forseti MUST treat full-session semantic ingestion as an exception. The default pipeline is event-first narrowing, followed by targeted semantic review.
1. Index all events.
2. Calculate rolling atomic signals.
3. Detect peaks / change points / repeated motifs.
4. Select top-K suspicious windows.
5. Expand each window by configurable context_before/context_after.
6. Send only those windows plus verified project anchors to semantic analysis.
7. Store the semantic result as INFERRED unless separately verified.
6. Evidence and Artifact Reality
A file name, terminal line, model claim, or tool-start event is not evidence of completion.
Claim
Minimum verification
File created
exists + size > expected minimum + stable hash/readability check
Code modified
disk diff + parser/build/test contract where applicable
Test passed
test command + exit code + captured output + relevant test identity
External object created
remote identifier or confirmation receipt
Task complete
all required acceptance evidence linked; no unresolved blocker hidden
Background process running
live process/heartbeat, not historical PID text
7. Visible Liveness and Safe Interruption
Long-running work MUST expose visible liveness so users are not forced to guess whether the system is alive, hung, or silently failing.
Metric
Definition
Target direction
Silent Execution Ratio
time with no visible heartbeat / active execution time
→ 0
Unsafe Interrupt Rate
interruptions without durable recovery snapshot / total interruptions
→ 0
Last Verified Progress Age
time since last verified advancement
lower is healthier for active tasks
Before an interrupt, Forseti SHOULD create:
RecoverySnapshot {
  objective
  current_step
  last_verified_state
  active_hypothesis
  open_tool_calls
  artifact_refs
  unresolved_decisions
  exact_next_step
  timestamp
}
8. Human Interface Plane
Forseti's default human interface MUST be external to the model prompt. The product should inform the human without continuously modifying the observed agent's context.
8.1 Surface A — Desktop Ambient Thermometer
A small always-available desktop sidecar/overlay shows only current runtime state. It MUST remain visually quiet in HEALTHY and WATCH states.
State
Default UI
HEALTHY
Small temperature/status indicator only.
WATCH
Indicator changes state; no modal dialog.
ELEVATED
Optional one-line cause summary on hover/click.
HIGH
Expandable diagnosis card with top signals and verified progress age.
CRITICAL
Rescue card may be shown if intervention criteria are satisfied.
8.2 Surface B — Inline Conversation Annotation
Where host UI integration is available, Forseti MAY render an annotation adjacent to the assistant output. The annotation MUST NOT alter the original assistant message or prompt.
Assistant Output
────────────────────────
Forseti Annotation
Temperature: 0.71 / HIGH
Reality risk: elevated
2 claimed artifacts: 1 zero-byte
Last verified progress: 11m ago
[Open X-Ray]
Positive confirmation is equally important. Verified claims SHOULD render quiet confirmation so Forseti does not become a system that only complains.
8.3 Surface C — Rescue Card
When runtime evidence indicates high deterioration and human interruption risk, Forseti may replace repeated alerts with one concise rescue surface.
Forseti Rescue
Session health is critically degraded.

Preserved:
- Current objective
- Last verified state
- Changed artifacts
- Open decisions
- Last healthy context window
- Exact next executable step

Actions:
[Continue]
[Create clean successor]
[Open X-Ray]
8.4 Host integration modes
Host
Preferred implementation
Prompt impact
Forseti/Code Duo owned UI
Native message annotation schema
None by default
Browser-based AI UI
Browser extension / DOM-adjacent annotation
None by default
Closed desktop AI app
Separate always-on-top sidecar/overlay
None by default
CLI/TUI
Terminal side panel / status line / local web dashboard
None by default
9. Observation Plane vs Intervention Plane
The architecture MUST separate passive observation from actions that modify agent behavior.
Plane
Default
Functions
Observation Plane
Always on
Capture, temperature, anomaly detection, X-Ray, annotations, evidence checks.
Intervention Plane
Off unless triggered
Ask agent, inject recovery instruction, stop tool, checkpoint, fork, revoke plan/hypothesis authority.
The design target is OBSERVE 99%, INTERRUPT 1% as a philosophy, not a fixed empirical constant. The implementation MUST measure actual interruption rate and false-positive burden.
9.1 Observer-effect prohibition
Forseti MUST NOT continuously interrogate the observed model because doing so changes the very context being measured.
Passive evidence collection SHOULD be preferred.
Semantic interrogation MAY be used only on selected suspicious windows or rescue transitions.
Any injected question MUST be logged as an intervention event so later analysis can separate pre-intervention behavior from post-intervention behavior.
10. Reverse-Grill Diagnostic Probe
When a suspicious condition exists but evidence is insufficient, Forseti MAY query the agent with a structured diagnostic probe. The probe is not 'Are you drifting?'. It requests explicit linkage and evidence.
DiagnosticProbe {
  current_goal_as_understood
  current_step
  why_this_step_advances_goal
  required_constraints
  evidence_of_progress
  what_would_falsify_current_strategy
  next_step_if_falsified
}
Probe answers remain DECLARED/INFERRED until matched against observable reality. Failure to answer coherently increases uncertainty; it does not by itself prove deception.
11. Intervention Preconditions
A hard intervention MUST require more than a high temperature.
Action
Minimum precondition
Quiet annotation
T_runtime ≥ configured threshold OR strong single verified anomaly.
Suggest recovery
T_runtime high + progress stagnation or evidence mismatch.
Freeze repeated retry
repeat budget exceeded + no verified progress.
Replan
current hypothesis/plan REFUTED or hard prerequisite invalidated.
Block high-risk action
hard authority/license/safety prerequisite unknown/refuted.
Create successor
critical health + checkpoint available or user requests handoff.
12. Calibration Data Contract
Historical self-confessions from models are useful research material but MUST NOT be treated as sole ground truth. Calibration labels should distinguish observable event facts, human adjudication, and model self-report.
IncidentLabel {
  incident_id
  session_id
  window_start
  window_end
  label_family
  severity
  evidence_refs[]
  human_adjudication
  model_self_report?
  certainty
  disputed: bool
}
Old sessions with missing temporary files MUST remain analyzable, but missing artifact evidence must be labeled UNKNOWN. Forseti's forward capture should preserve lightweight evidence at event time: path, size, hash, timestamps, exit code, and optional scoped content fingerprints.
13. First Implementation Slice
The first implementation MUST avoid solving every Forseti problem. Build the smallest closed loop that can be tested on real sessions.
Step
Deliverable
Exit gate
1
Event ledger + visible heartbeat
Can replay one session timeline deterministically.
2
Atomic signals S1–S9
Each signal unit-tested from synthetic fixtures.
3
Thermometer + top-contributor explanation
Same fixture always yields same score/version.
4
Artifact reality verifier
Detects zero-byte claimed output and stale process claim.
5
Suspicious-window selector
Finds injected anomaly window without full-session LLM read.
6
Desktop thermometer sidecar
Shows health without prompt injection.
7
Safe interrupt checkpoint
ESC/cancel produces durable recovery snapshot.
8
Targeted semantic analyzer
Only selected windows are sent for semantic review.
9
Inline annotation adapter, where host permits
Original assistant output remains unmodified.
10
Rescue card
Triggered only by documented preconditions.
14. Acceptance Tests v0.1
ID
Scenario
Required result
AT-UI-01
Healthy coding session for 30m
No modal interruption; ambient indicator remains quiet.
AT-UI-02
Tool runs 12m with heartbeat but no verified progress
UI distinguishes alive-but-stale from dead.
AT-UI-03
No heartbeat for configured interval
Silent Execution signal rises; user sees liveness warning.
AT-ART-01
Model claims file produced; file exists at 0 bytes
Claim cannot become VERIFIED; reality-risk annotation shown.
AT-DRIFT-01
No explicit/reliable goal exists
System MUST NOT state semantic drift as fact.
AT-OBS-01
Forseti annotation enabled
No prompt/context modification occurs in observation-only mode.
AT-INT-01
User cancels long task
Recovery snapshot is created before/at interruption when technically possible.
AT-PROBE-01
Reverse-grill probe says work is aligned but disk evidence contradicts it
Observable evidence outranks self-report.
AT-SAMP-01
Large session with one injected abnormal window
Selector returns the abnormal region within top-K without sending full session to semantic LLM.
AT-RSC-01
Critical score caused only by one weak heuristic
No hard rescue/block; insufficient evidence is shown.
15. Open Questions — Must Be Calibrated, Not Guessed
Window sizes and decay constants for each atomic signal.
Healthy-baseline method: global default vs per-user/per-tool adaptive baseline.
Weights and thresholds in T_runtime.
Definition of material claim for claim-evidence gap.
Similarity function for repeated strategies/actions.
Minimum heartbeat cadence that is informative without becoming noise.
Which host applications permit stable inline annotation versus external overlay only.
How much semantic context around a suspicious window is sufficient.
How to separate legitimate requirement changes from corrective burden.
How to estimate productivity benefit against Forseti overhead.
16. Conformance Rule
An implementation may call itself Forseti-conformant to this v0.1 specification only if every enabled detector exposes: (1) input events, (2) computation/version, (3) threshold, (4) exclusion conditions, (5) confidence/epistemic state, (6) user-visible explanation, and (7) linked recovery behavior where applicable.
Any detector that outputs 'drift', 'deception', 'failure', or 'safe' without these fields is experimental and MUST be labeled as such.

