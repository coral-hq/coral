# Contract K6 v1: Coral engine tools

- **Status:** Draft v1, live. The production catalog (`CATALOG` in
  `coral/tools/catalog.py`) lists both tools, and every server with a usable
  operational database answers them through `StoreDecisionPort`, the engine
  bridge's port over the run store.
- **Code:** declarations in `coral/tools/catalog.py`; argument schemas and the
  reply in `coral/tools/schemas.py`; reply texts in `coral/tools/replies.py`;
  the port protocol in `coral/tools/port.py` and the store port in
  `coral/bridge/port.py`; dedup in `coral/tools/dispatch.py`; the planners in
  `coral/tools/handlers/`; the server side in
  `coral/omni/server/tool_bridge.py`; the runner side in
  `coral/omni/runner/tool_provider.py`.
- **Related:** [`session-facade.md`](session-facade.md) (bindings, the run's
  sessions), [`plugin.md`](plugin.md) (the `omnigent.tool_providers` entry
  point).

## Tools

| Tool | Offered to (bundle stance) | Arguments |
|---|---|---|
| `coral_submit_handoff` | `implementer`, `reviewer` | `activation_id` (1-512), `status` (`done` \| `blocked`), `report` (1-8000 characters), `blocked_reason` (1-2000; only and always with `blocked`), `kind` (`handoff` only), `label` (1-200; a `done` handoff on a step that routes by label), `artifacts` (at most 50 strings of 1-1024) |
| `coral_choose_arrow` | `orchestrator` | `decision_id` (1-512, the decision's engine activation id), `label` (1-200), `reason` (1-4000) |

Both schemas set `additionalProperties: false`. The anchor gets no tool. A
spec on a native harness gets none either. Each tool adds one instruction
sentence to the prompt (S12), after the authored text.

The tools are offered by the bundle's stance (`params.coral.generated.stance`);
only the session's binding authorizes a call. A session no run binds is
offered them too, and every call it makes gets `not_run_member`.

## Reply

A call that reaches the engine answers with JSON text in a normal MCP tool
result, keys sorted:

| Key | When | Meaning |
|---|---|---|
| `accepted` | always | Coral took the call (a repeat of an accepted one included) |
| `reason` | always | `null` when accepted, else a reason below |
| `allowed_values` | always | values the refused field takes: enum values, the step's or decision's labels, the slot's activation id, or the open decision ids; never anything else |
| `next` | always | what the agent should do now |
| `field`, `message` | a field refusal | the one argument to fix |
| `duplicate` | true only | a repeat of an earlier accepted call |
| `loop` | a back arrow chosen | `{used, limit}`: the loop counter after the choice (the pass the back arrow started; the last pass when the limit redirected the choice) and the loop's limit |
| `redirected` | true only | the loop limit sent the choice along its at-limit arrow |

| Reason | Tool | Counted | Meaning |
|---|---|---|---|
| `handoff.invalid` | submit | yes | an argument is wrong |
| `tool.illegal` | choose | no | `label` (the decision's labels), `decision_id` (the open decision ids), `reason` or unknown `arguments` |
| `run.paused` | both | no | the run is paused, by its store row (drift) or its engine state |
| `run_cancelled` | both | no | the run was cancelled |
| `not_run_member` | both | no | no binding, not a step of the run, or the run is gone |
| `slot_closed` | submit | no | the slot is closing or closed with another handoff, or the run finished |
| `evaluation_in_progress` | both | no | submit: a handoff is being evaluated, or the slot is not ready yet (retry); both: Coral is busy (retry) |
| `slot.superseded` | submit | no | a newer session has the slot |
| `decision_closed` | choose | no | the decision was made with another label, or the run finished |
| `not_orchestrator` | choose | no | the caller is not the run's current orchestrator |

`evidence.missing` answers a `done` handoff whose `done_when` commands did not
pass; it spends one of the step's attempts, not a rejected call
([`evidence.md`](evidence.md)). `run.taken_over` and `recipient_closing` are
reserved and never produced. Only `handoff.invalid` counts toward a slot's
rejected-call streak; the third in a row pauses the run, and that reply already says stop.
Every other refusal writes nothing and is logged as one info line with the
tool, session, run and reason, never the arguments. No text for a paused,
cancelled or finished run, or a replaced session, asks for another call.

### `coral_submit_handoff`

First match wins: membership (a step binding, not an orchestrator, at least
`row_created`, naming an engine slot of this run); the session generation
(older: `slot.superseded`; newer: retry); a closing or closed slot (the same
handoff: the duplicate receipt; else `slot_closed`); the run's state; slot
readiness; a handoff being evaluated; the arguments one at a time (counted);
then `HandoffReceived` and `HandoffEvaluated` in one commit. An explicit
`null` for an optional argument reads as left out; unknown argument names are
never echoed. The stored body is the canonical JSON of the checked fields, at
most 12,288 UTF-8 bytes.

### `coral_choose_arrow`

First match wins:

1. The binding is a step binding with slot role `orchestrator`, at least
   `row_created`, of this run, and the run row's `orchestrator_session_id` is
   this session; else `not_orchestrator`. A restarted orchestrator replaces the
   column, which fences the old session.
2. The run: cancelled, finished (`decision_closed`) or paused.
3. Unknown argument names: `tool.illegal` on `arguments`.
4. `decision_id` names a decision activation with a decision row that a
   choice can still reach; else `tool.illegal` listing the open decision ids
   (with none open, `next` says stop).
5. A decided decision: the same label gets the duplicate receipt (`next` and
   `redirected` from the stored choice receipt; no `loop`, which may have moved
   on); another label gets `decision_closed`.
6. `reason`: non-blank, at most 4000 characters, UTF-8 encodable; else
   `tool.illegal`.
7. `label`: one of the decision's choosable labels; else `tool.illegal`
   listing them.
8. Commit `ChooseArrow`. `next` names the node the run goes to (the at-limit
   arrow's target when redirected).

Choose refusals are not counted: the engine counts rejections per slot, and an
orchestrator has none.

## Transport

| Seam | Role |
|---|---|
| S50 | `omnigent.tool_providers` entry point; Coral's provider gives each stance its tools, lists every catalog tool as server-dispatched and adds `coral_runner:2` to the host hello |
| S7 | the runner's `ToolManager` registers the provider's tools |
| S8 | the runner forwards server-dispatched names to the server's `/mcp` |
| S12 | the tools' instruction text is appended to the prompt |
| S10 | `POST /v1/sessions/{id}/mcp` runs a registered server tool after TOOL_CALL policy, only for a session whose spec a provider gave the tool |
| S49 | `runner_proven`: the caller holds a tunnel token bound to the session's runner, or one the server allows |

The tool bridge (`register_engine_tools`) registers one S10 handler per
catalog tool. S10 has already loaded the session and its spec and run
TOOL_CALL policy. Each call is then checked in this order; the first three are
transport faults (JSON-RPC `-32000`), each logged as a warning naming the
session (never the arguments or the operation id), and nothing is read before
them:

1. No operation id: "Coral tools need the runner's operation id".
2. Not runner-proven, on every server: "Coral tools can be called only by the
   session's own runner".
3. No decision port: "Coral's workflow engine is not running on this server".
   A server passes `port=None` only in tests.
4. `find_by_session(current_workspace_id(), session_id)` on the decision
   pool. A store error, or no answer within 10 s, is `-32000` "could not look
   up this session; retry"; no binding is a `not_run_member` reply. The read
   is fresh on every call (the planners read the binding's progress), never a
   cache of found rows, and never a `coral.*` label: `register_engine_tools`
   takes a `FreshBindingLookup` and raises `TypeError`, even for an empty
   catalog, unless its `reads_fresh` is true. A cache that keeps found rows
   must not set it, or a binding cached at `reserved` would answer
   `not_run_member`.
5. The dispatcher: its `TransportError`s are `-32000`. Any other failure of
   the port or the store (a lock timeout, a run that cannot be loaded) is
   logged without SQL text or parameters (`describe_exception`) and answered
   "Coral could not answer this call; retry shortly".

TOOL_RESULT policy is skipped for these results, as for `sys_advise_models`.
Runner proof is runner-granular: anything holding the runner's token can call
as any session that runner serves.

## Dedup

- The key is `sha256` over `coral-op` and the length-prefixed run id, session
  id, tool and operation id, so one session never reads or shares another's
  reply. An operation id must be 1 to 128 characters.
- In one process, a resent call joins the decision still running (a caller that
  goes away does not cancel it). A caller waits at most 30 s, then gets a
  retryable `-32000`; the decision goes on and the next resend gets its reply.
- Decisions on one run run one at a time per process. At most 64 run or wait at
  once, and at most 4 on one run; a new call past either gets an uncounted
  `evaluation_in_progress` "busy" reply. A resend of a call in flight joins it
  and is not counted.
- The binding lookup, `find_reply` and `decide` run on a pool of 4 threads of
  their own (`coral-decision`), never on the event loop's default executor or
  the bridge's pool. A call still waiting for a thread when the server stops
  is answered with a retryable `-32000`; nothing was decided.
- Across processes and restarts, the port's stored reply (below).

## `RunDecisionPort`

`find_reply(workspace_id, run_id, cksum)` returns the stored reply or `None`.
`decide(workspace_id, run_id, planner, cksum, *, actor)` must, on every
attempt:

1. Return the reply stored under `cksum`, if any.
2. Load a snapshot: the run row and its folded engine state, with the graph
   pinned to the run's version hash. A missing run raises `RunNotFound`.
3. Run the planner. A `Reply` is returned as it is, unless a reply was stored
   under `cksum` since step 1 (another server committed the same call), which
   is returned instead; nothing is written.
4. For a `Commit`, apply each input with `transition` in order. If one is
   refused, write nothing: return the reply for an observation (a counted
   refusal), else raise `EngineRefused` (the dispatcher maps the code with the
   call's tool; a code with no reply is a logged `-32000`).
5. Otherwise write every log entry, its effects and the reply under `cksum` in
   one `apply_transition`, compare-and-swap on the snapshot's run version. The
   entries record `actor`, the calling session.
6. On a version conflict start again; after 5 attempts raise `RunContended`
   (`-32000`, "busy").

The planners' fences hold only if the bridge also keeps these rules:

- a retried slot's new session is bound with the slot's current
  `session_generation`, or every handoff from it is `slot.superseded`;
- at most one session is bound to a (run, slot, generation);
- every write to a run row field a planner reads (`status`, `pause_reason`,
  `orchestrator_session_id`) bumps the compare-and-swap version;
- a slot's handoff body is stored and read back byte for byte.

### `StoreDecisionPort`

`coral/bridge/port.py` implements the port over the run store, through the
engine bridge:

- **Replies** live in `coral_tool_replies`, keyed by workspace, run and
  checksum, and are written in the decision's own commit
  ([`persistence.md`](persistence.md)).
- **The snapshot** is the bridge's `load`: the run's rows, the graph pinned in
  `coral_workflow_versions`, the engine config frozen in the run spec, and the
  state folded from the run's engine log. Inputs are applied with that frozen
  config.
- **The commit** is built by the bridge's `build_commit`: the entries as
  engine log rows (actor kind `STEP_AGENT` for a handoff or a counted
  refusal, `ORCHESTRATOR` for a choice; `actor_ref` the calling session), the
  work their effects queue (a close, for example), the run and slot
  projections, and the reply.
- **A retry** follows a version conflict, or an `IntegrityError` on the reply
  key when another writer stored a reply under the same checksum, after a
  jittered wait of about 10 ms. Any other `IntegrityError` is raised.
- **A commit that cannot be built** (more rows than one commit holds, an
  oversized payload) pauses the run `failure_path` visibly; the call is
  planned again and answered `run.paused`. A run that cannot be loaded is
  paused once and the call fails as a retryable transport error.
- **Rules.** (a) holds: a retry bumps the slot's `session_generation` in its
  own commit, the restart's completion emits the new generation's
  `create_session` with that `generation` (a first-generation create names
  none, which reads as 1, so the recorded logs fold unchanged), and the create
  binds the new session at it. A create completion of another generation only
  records its receipt, and a create whose slot moved on before it bound is
  labelled closed, stopped and abandoned
  (`test_a_retried_slots_next_generation_gets_its_own_session_bound_at_it`,
  `tests/coral/omni/test_session_facade.py`;
  `test_a_retried_writer_is_fenced_salvaged_reset_and_briefed_at_generation_two`,
  `tests/coral/omni/test_recovery.py`). A handoff from the old generation's
  session is `slot.superseded`. (b) is the unique index
  `uq_coral_session_bindings_slot_generation`. (c) holds because every
  `apply_transition` bumps the version. (d) holds because the body is stored
  inside the `HandoffReceived` entry's JSON.
- **Bounds.** The port does not log. Each write waits at most 10 s for the
  run row's lock, and 15 s for its statement, on PostgreSQL and CockroachDB;
  MySQL and SQLite keep their own lock waits, and the reads have no statement
  timeout. The dispatcher bounds the caller's wait (30 s), and the tool bridge
  the binding lookup's (10 s).

## Wiring

On a usable operational database `coral_lifespan` builds one binding store,
shared by the session engine and `_wire_guards`, which runs whether or not the
session engine is wired. `_wire_guards` calls
`register_engine_tools(catalog=CATALOG, port=StoreDecisionPort(bridge), ...)`
with the decision pool's `run` as the thread runner. Without a usable
database nothing registers. Registering loads the installed tool providers
first, so S10's grant check never scans entry points on the event loop. Each
registration's unregister is on the lifespan's exit stack, and the decision
pool closes after the tools are removed. A catalog tool that no planner
answers fails registration with `ValueError`. One lifespan per process: a
second one entered while one runs raises before it registers anything
([`plugin.md`](plugin.md)).

## Not in this version

Counting orchestrator rejections (ENG-06); `items` (ENG-08); `refresh_note`
(SES-07); evidence scopes other than `per_agent` and native steps' commands
(HRN-03). Owners are in
[`session-facade.md`](session-facade.md), "Deferred work and owners".

### What the bridge does

Each item below was left to the bridge in v0; each has its line in
[`session-facade.md`](session-facade.md), "The engine bridge".

- **Stored replies.** `coral_tool_replies` stores each reply under its
  checksum, in the same commit as the decision. The snapshot loads the graph
  pinned to the run's version.
- **Orchestrator bindings.** The orchestrator's binding uses
  `slot_id="orchestrator"`, which no engine slot id can take (they all contain
  `|`), slot role `orchestrator` and the run's orchestrator generation (1 until
  a run Retry replaces a lost orchestrator; the old session is then refused
  `not_orchestrator`). The commit that opens a
  run's first decision writes `CoralRun.orchestrator_session_id` and queues
  the orchestrator's create and the decision's request, so `coral_choose_arrow`
  works end to end. Each later decision gets a request; an unanswered one gets
  a reminder at 30 and at 60 minutes, and every return to running asks again.
  At 60 minutes the run owner also gets a `watchdog` alert in the workflow
  Inbox, resolved once the decision is made
  ([`gates-and-inbox.md`](gates-and-inbox.md)).
- **Early submit.** A handoff sent before the brief's `send_input` completes
  is still refused with `evaluation_in_progress` (retry). The brief's row is
  fed back as soon as it finishes, so the window is short, and the retry is
  accepted.
- **Paused handoffs.** The engine still refuses a handoff while the run is
  paused, so the step gets `run.paused` with a stop `next`. The resume
  re-prompts the step with one nudge, and it hands off again. RUL-01's "a
  paused step can still hand off" holds only at the policy layer.
- **Stopped turns.** A resume, or a plan-limit probe that clears its pause,
  re-prompts with one nudge every slot that is `evaluating` with no handoff or
  whose last turn failed. A step's failed turn no rule names (`agent.failed`)
  is not cleared by a resume: a Retry restarts that step in a new session
  generation (see [`session-facade.md`](session-facade.md), "What a resume
  clears" and "Retry"). After a store outage the resync re-gathers the turn
  of each working slot of a running run every five minutes, so a turn end
  lost then is folded and nudged.
- **Nudge lease.** `nudge` is a leased kind (`_LEASED_KINDS` in
  `coral/engine/machines/slot.py`). A turn-end signal for a slot whose send or
  nudge has no receipt yet is held and applied after the receipt.
