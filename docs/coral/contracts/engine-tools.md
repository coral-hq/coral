# Contract K6 v0: Coral engine tools

- **Status:** Draft v0, dark. The production catalog (`CATALOG` in
  `coral/tools/catalog.py`) is empty and no server has a decision port, so no
  agent is offered an engine tool and the bridge registers nothing. The
  engine-to-store bridge (ENG-04/DUR-04) supplies a `RunDecisionPort` and fills
  the catalog; this page is its input.
- **Code:** declarations in `coral/tools/catalog.py`; argument schemas and the
  reply in `coral/tools/schemas.py`; reply texts in `coral/tools/replies.py`;
  the port in `coral/tools/port.py`; dedup in `coral/tools/dispatch.py`; the
  planners in `coral/tools/handlers/`; the server side in
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
| `run.paused` | both | no | the run is paused, by its store row (drift, budget) or its engine state |
| `run_cancelled` | both | no | the run was cancelled |
| `not_run_member` | both | no | no binding, not a step of the run, or the run is gone |
| `slot_closed` | submit | no | the slot is closing or closed with another handoff, or the run finished |
| `evaluation_in_progress` | both | no | submit: a handoff is being evaluated, or the slot is not ready yet (retry); both: Coral is busy (retry) |
| `slot.superseded` | submit | no | a newer session has the slot |
| `decision_closed` | choose | no | the decision was made with another label, or the run finished |
| `not_orchestrator` | choose | no | the caller is not the run's current orchestrator |

`evidence.missing`, `run.taken_over` and `recipient_closing` are reserved and
never produced. Only `handoff.invalid` counts toward a slot's rejected-call
streak; the third in a row pauses the run, and that reply already says stop.
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
| S50 | `omnigent.tool_providers` entry point; Coral's provider gives each stance its tools, lists every catalog tool as server-dispatched and adds `coral_runner:1` to the host hello |
| S7 | the runner's `ToolManager` registers the provider's tools |
| S8 | the runner forwards server-dispatched names to the server's `/mcp` |
| S12 | the tools' instruction text is appended to the prompt |
| S10 | `POST /v1/sessions/{id}/mcp` runs a registered server tool after TOOL_CALL policy, only for a session whose spec a provider gave the tool |
| S49 | `runner_proven`: the caller holds a tunnel token bound to the session's runner, or one the server allows |

The bridge (`register_engine_tools`) registers one S10 handler per catalog
tool. S10 has already loaded the session and its spec and run TOOL_CALL policy.
Each call is then checked in this order; the first three are transport faults
(JSON-RPC `-32000`), each logged as a warning naming the session (never the
arguments or the operation id), and the bridge reads nothing before them:

1. No operation id: "Coral tools need the runner's operation id".
2. Not runner-proven, on every server: "Coral tools can be called only by the
   session's own runner".
3. No decision port: "Coral's workflow engine is not running on this server".
4. `find_by_session(current_workspace_id(), session_id)` in a worker thread.
   A store error is `-32000` "could not look up this session; retry"; no
   binding is a `not_run_member` reply. The read is fresh on every call (the
   planners read the binding's progress), never a cache of found rows, and
   never a `coral.*` label: `register_engine_tools` takes a
   `FreshBindingLookup` and raises `TypeError`, even for an empty catalog,
   unless its `reads_fresh` is true. A cache that keeps found rows must not
   set it, or a binding cached at `reserved` would answer `not_run_member`.
5. The dispatcher: its `TransportError`s are `-32000`.

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
  once; a new call past that gets an uncounted `evaluation_in_progress` "busy"
  reply.
- Across processes and restarts, the port's stored reply (below).

## `RunDecisionPort` (the bridge implements it)

`find_reply(workspace_id, run_id, cksum)` returns the stored reply or `None`.
`decide(workspace_id, run_id, planner, cksum)` must, on every attempt:

1. Return the reply stored under `cksum`, if any.
2. Load a snapshot: the run row and its folded engine state, with the graph
   pinned to the run's version hash. A missing run raises `RunNotFound`.
3. Run the planner. A `Reply` is returned as it is; nothing is written.
4. For a `Commit`, apply each input with `transition` in order. If one is
   refused, write nothing: return the reply for an observation (a counted
   refusal), else raise `EngineRefused` (the dispatcher maps the code with the
   call's tool; a code with no reply is a logged `-32000`).
5. Otherwise write every log entry, its effects and the reply under `cksum` in
   one `apply_transition`, compare-and-swap on the snapshot's run version.
6. On a version conflict start again; after 5 attempts raise `RunContended`
   (`-32000`, "busy").

The port does not log; it bounds each `decide` with database statement and
lock timeouts. The planners' fences hold only if the bridge also keeps these
rules:

- a retried slot's new session is bound with the slot's current
  `session_generation`, or every handoff from it is `slot.superseded`;
- at most one session is bound to a (run, slot, generation);
- every write to a run row field a planner reads (`status`, `pause_reason`,
  `orchestrator_session_id`) bumps the compare-and-swap version;
- a slot's handoff body is stored and read back byte for byte.

## Wiring

On a usable operational database `coral_lifespan` builds one binding store,
shared by the session engine and `_wire_guards`, which runs whether or not the
session engine is wired. `_wire_guards` calls
`register_engine_tools(catalog=CATALOG, port=None, ...)`: with the empty
catalog it registers nothing; once the catalog lists a tool, every call
answers "the engine is not running" until a port is passed. Registering loads
the installed tool providers first, so S10's grant check never scans entry
points on the event loop. Each registration's unregister is on the lifespan's
exit stack. A catalog tool that no planner answers fails registration with
`ValueError`. One lifespan per process: a later one replaces the registrations.

## Not in v0

The bridge and its port; lazy orchestrator creation, decision requests,
reminders and re-briefs; counting orchestrator rejections; `items` (ENG-08);
`refresh_note`; the evidence check.
