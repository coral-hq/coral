# Contract K4 (subset) and K18: Coral session facade, dispatch and status edges

- **Status:** Draft v1, live. `coral_lifespan` registers the seven executors,
  the engine bridge's `timer`, `run_resync` and `turn_fact` executors, the
  restart ladder's `recovery.restart` and the wake's `recovery.wake`
  executors, the gate executors `gate_publish` and `gate_withdraw`, and the
  status-edge observers below. The engine bridge queues their work from each
  run's engine log and folds their outcomes back (see "The engine bridge").
- **Code:** protocols and value types in `coral/omni/protocols.py`; the
  facade in `coral/omni/server/sessions.py`; dispatch in
  `coral/omni/server/dispatch.py`; the status-edge observer in
  `coral/omni/server/status_edges.py`; close and cancel in
  `coral/slots/close.py`; executors in `coral/slots/executors.py` and
  `coral/workspace/executors.py`; shared executor steps in
  `coral/queue/run_effects.py`; drift in `coral/recovery/drift.py`; the
  restart ladder in `coral/recovery/ladder.py`; the liveness pass and the wake
  in `coral/recovery/relaunch.py`; the step relauncher
  (`OmnigentStepRelauncher`) in `coral/omni/server/sessions.py`; the engine
  bridge in `coral/bridge/`; step agents in `coral/omni/server/step_agents.py`;
  the turn-fact recorder in `coral/omni/server/turn_facts.py`; gates and
  alerts in `coral/gates/`, `coral/alerts/` and `coral/omni/server/gates.py`;
  wiring in `coral/omni/server/plugin.py`.
- **Related:** [`workspace-ops.md`](workspace-ops.md) (K13: the git ops and
  their errors), [`persistence.md`](persistence.md) (the `coral_0002`,
  `coral_0003` and `coral_0005` tables), [`plugin.md`](plugin.md) (K17),
  [`gates-and-inbox.md`](gates-and-inbox.md) (gates, run alerts and the
  workflow Inbox),
  [`engine-tools.md`](engine-tools.md) (K6),
  [`../decisions/ADR-05-topology.md`](../decisions/ADR-05-topology.md)
  (session topology).

## Wiring

`coral_lifespan` wires Coral only on a usable operational database.

1. It claims the process first (one lifespan per process, below), then builds
   the run and queue stores, the engine bridge (`EngineBridge`) with its
   bound-session index, the bridge's thread pool (8 threads), the engine
   tools' decision pool (4 threads) and the worker supervisor.
2. It registers the run protection below, the engine tools
   ([`engine-tools.md`](engine-tools.md)) and the bridge's own executors,
   `timer` and `run_resync`, which need only Coral's stores. Then gate
   delivery and answers, also without the session engine: the
   `gate_publish` and `gate_withdraw` executors (`gate_withdraw` with
   `runs_after_terminal`), the verdict handler for `coral_gate_` prompts,
   then the anchor's admission of approvals, the S5 observer that tracks this
   process's gate prompts and the per-process prompt sweep
   ([`gates-and-inbox.md`](gates-and-inbox.md)).
3. When the app has `state.session_event_dispatch` and the plugin services
   carry the conversation, agent, artifact, host and project stores, the
   agent cache, the host registry and the runner router, it wires the session
   engine:
   - the three `coral_0002` stores, `OmnigentSessionFacade`,
     `OmnigentSessionDispatch` with a `DriftPreSendHook` (whose pauser pauses
     through the engine bridge and stops a runner attached to the anchor, see
     Anchor runner), `OmnigentHostWorkspaceChannels`, `CoralStatusEdges` on
     the server's event loop, one `ConfirmedStops` record, and
     `OmnigentStepAgents`, which resolves a step's stance to the run owner's
     agent;
   - the seven executors (`cancel_sessions` with `runs_after_terminal`, see
     Finished runs), the bridge's `turn_fact` executor, and the
     `recovery.restart` and `recovery.wake` executors; one
     `OmnigentStepRelauncher` serves both the wake and the dispatch, and the
     resync runs the `LivenessPass` (see "Restarts and runner loss");
   - the turn-fact recorder, then the S1 observers `"coral"`
     (`CoralStatusEdges.observe`), `"coral.confirmed_stops"`
     (`ConfirmedStops.observe`) and `"coral.turn_facts"`
     (`TurnFactRecorder.observe`);
   - the bound-session refresher, which fills the index before the
     supervisor starts.

   Otherwise it logs a warning naming the missing input and wires none of
   these. The supervisor still starts, so a run's session effects are held as
   `executor.missing` for up to 30 minutes, then retried until their attempts
   run out, which pauses the run `infra`.
4. It starts the supervisor last. Its finished items feed the bridge, its
   hold policy is the bridge's, its startup sweep republishes every open
   gate's prompt, and its resync task repairs each active run and shows again
   any gate prompt this process lost (see "The engine bridge").

On exit it stops the supervisor first: the drain workers are cancelled, and an
item in flight keeps its lease and is reclaimed after it expires, so no item is
claimed while its executor is missing. Then it stops the refresher and
unregisters the observers, the recorder and the executors in reverse order. The
gates go in the same order: the prompt sweep stops, the gate prompt observer is
removed, the anchor stops admitting approvals (an answer admitted just before
is told to retry), then the verdict handler and the gate executors go. The
decision pool closes after the engine tools are removed, then the bridge's
pool, and the process claim is released last. A start that fails part-way
unregisters what it registered. Entering again after an exit registers again
without a conflict.

One lifespan per process. A second lifespan entered while the first still
runs raises `RuntimeError` before it registers anything, and the first keeps
its registrations ([`plugin.md`](plugin.md)).

The built objects are on `app.state`: `coral_run_store`, `coral_queue_store`,
`coral_worker_supervisor`, `coral_engine_bridge`, `coral_bound_sessions`,
`coral_runner_liveness` (the liveness pass's reference, which holds a pass
once the session engine is wired), `coral_gate_publisher`, `coral_gate_prompts` and
`coral_alert_store` (which the workflow Inbox routes read), and with the
session engine also `coral_session_facade`, `coral_session_dispatch`,
`coral_status_edges`, `coral_confirmed_stops`, `coral_turn_fact_recorder`,
`coral_bound_session_refresher` and `coral_step_relauncher`.

## Ids

All ids are `derived_id(kind, *parts)` (32 lowercase hex, `coral/model/ids.py`).

| Id | Derivation | Notes |
|---|---|---|
| Anchor session | `anchor_session_id(ws, run_id)` = `derived_id("coral-anchor", str(ws), run_id)` | Run-scoped: a re-keyed anchor effect adopts the run's one anchor. The binding's primary key holds one anchor per run. |
| Step session | `effect_session_id(ws, effect_key)` = `derived_id("coral-session", str(ws), effect_key)` | One per `create_session` effect. The bridge derives it from the slot's latest create, so a send, close or cancel can name it before that create completes. |
| Orchestrator session | `effect_session_id(ws, "<run_id>:orchestrator:<generation>:create_session")` | The run row's `orchestrator_session_id`, written by the commit that opens the run's first decision. Its binding's `slot_id` is `orchestrator`. |
| Store slot | `derived_id("coral-slot", run_id, engine_slot_id)` | The `coral_agent_slots` id; payloads carry it as `slot_id`. |
| Engine message | `effect_message_id(ws, effect_key)` = `derived_id("coral-message", …)` | The message's stable id, recorded in `coral_stable_ids` before the send. |
| Fallback message | `fallback_message_id(stable_id)` = `derived_id("coral-message-fallback", stable_id)` | Used when another item already holds the stable id. |
| Op key | `effect_op_key(ws, effect_key, *qualifiers)` = `derived_id("coral-op", …)` | `workspace.*` use no qualifier; `close_slot`'s commit uses `"commit"`. |
| Attempt | `derived_id("coral-attempt", run_id, engine_slot_id, str(generation))` | Default `Coral-Attempt` trailer when the payload has no `attempt_id`. |
| "Coral runs" project | `derived_id("coral-runs-project", str(ws), owner or "")` | The anchor's project; a renamed folder keeps its id. |

Labels: the anchor gets `coral.run_id` and `coral.role: run`; a step gets
`coral.run_id`, `coral.role` (`orchestrator` for an orchestrator slot, else
`step`), `coral.node_id` when given, `omnigent.parent_wake: off` and
`omnigent.ui: terminal`. Labels are display hints, never identity: the engine
finds sessions only through its bindings (ADR-05 rule 5).

## Preconditions for the bridge

The engine bridge meets each of these (see "The engine bridge").

- **Effect key.** Every payload carries `effect_key`, at most 512 characters,
  without NUL, starting with `<run_id>:` of the claimed run. Anything else is
  `effect.invalid_payload` or `effect.identity_mismatch`.
- **Identity.** Executors act as the stored run's owner and account
  registration, and take host, repository, worktree and branch from the run
  spec. A payload `user_id` or `account_generation` that differs from the run
  row is `effect.identity_mismatch`.
- **Anchor first.** Enqueue the anchor's `create_session` before any step's.
  A step created before its anchor is `initialized` fails with retryable
  `session.anchor_missing`. The bridge queues the anchor in the `StartRun`
  commit, due at once.
- **Slots.** The writer interlock reads `coral_agent_slots`: the bridge
  records each slot's current `session_id` and `session_generation` in the
  commit that folds its create's completion. Until a slot names it, a
  writer's `close_slot` fails with retryable `session.not_ready` rather than
  closing without its commit.
  Bindings keep the engine slot id; the drainer's fencing uses the payload's
  store `slot_id`.
- **Writer close.** A writer's `close_slot` must keep `closed_label` true;
  `false` is `effect.invalid_payload`.
- **Cancel.** `cancel_sessions` must carry `session_id`: an explicit `null`
  for a slot with no create yet. A payload without the key is
  `effect.invalid_payload`, never a silent success. The bridge names the
  session the slot's latest create derives, also while that create is in
  flight; a session this run never bound counts as cancelled.
- **Reset after salvage (SES-06).** The bridge queues no `workspace.*` item: a
  writer's commit runs inside its `close_slot`, and a retried step's salvage
  and reset run inside its `recovery.restart` row, in that order, with the
  salvage commit as the reset's precondition (see "Restarts and runner
  loss"). The standalone `workspace.reset` executor cannot see a salvage and
  checks nothing about it; a caller that queues it must enqueue it only after
  `workspace.salvage` for the same session completed. A salvage whose
  `git_failed` would repeat fails permanently, so it is never retried.
- **One worker.** The torn-row repair assumes one item of a run in flight at
  a time: the `coral.worker.primary` lease admits one leader, and its drain
  workers never run two items of one run at once.
- **Step agents have a Coral bundle's shape.** The facade still accepts only
  agents the server or the run owner authored (`session.agent_not_permitted`
  otherwise). Their spec must then have the shape of a Coral step bundle:
  the claude-sdk harness, `params.coral.generated.stance` fitting the slot
  role (`orchestrator` for an orchestrator slot; `implementer` or `reviewer`
  for the others), and the bundle hygiene rules (`check_hygiene`, which also
  requires the `coral__` name). Any other spec is
  `session.agent_not_supported`, for example the owner's ordinary agents.
  The check is structural: a hand-written spec of that shape passes as well as
  one from `build_step_bundle_yaml` and `materialize`, so no field that
  hygiene does not check (other generator metadata, `executor.config`,
  `mcp_servers`) is trusted to come from the generator. The shape matters
  because `params.coral` on claude-sdk turns on the tool-policy hook that puts
  every tool call of the session through the run's policies.
- **Coral hosts.** The run owner's host must advertise `coral_runner:2`
  (Coral's tool provider, [`plugin.md`](plugin.md)); an older or Coral-less
  host, or one with `CORAL_DISABLE_HOST_ENTRY_POINTS` set, is
  `session.host_unsupported`. A create checks it before any row and again
  before the launch, and every later launch of a step's runner that Coral makes checks it
  too: a send that must launch one, and a relaunch (`require_coral_runner`; see
  Residuals and limitations).

## Executors

Every executor parses its payload, loads the run, runs inside the run's
workspace, account-authority and host-owner scopes, calls `ensure_lease()`
before each external side effect, and returns only values a repeat
reproduces. Each passes `run_executor_conformance`.

| `effect_type` | Payload (besides `effect_type`, `effect_key`) | Result |
|---|---|---|
| `create_session` | `role` (`anchor` or `step`). A step adds `engine_slot_id` (≤ 512 chars), `slot_role` (`step_agent`, `orchestrator`, `verifier`, `merge_resolver`), optional `title` (≤ 200), `node_id` (≤ 128), `generation` (1-32,767, default 1), and either `agent_id` (1-64 of `A-Za-z0-9_-`) or a `stance`: `implementer` or `reviewer` with `workflow_slug` (≤ 64), `node_id` and `roster_index` (0-999), or `orchestrator` alone. A stance resolves, inside the run's scopes, to the run owner's agent for that step's bundle (`OmnigentStepAgents`); a bundle the generator refuses is `session.agent_not_supported`. | `{session_id, role, generation}` |
| `send_input` | `session_id`, `text` (≤ 1 MiB as sent, no NUL), `kind` (`brief`, `steer`, `nudge`) | `{session_id, stable_id}` |
| `close_slot` | `session_id`; optional `interrupt` and `closed_label` (default `true`), `message`, `attempt_id`, `diff_from`. `accepted_at_ms`, `node_id` and `item_path` are accepted and ignored. | `{pending_input, queued_input, post_accept_edits, commit, empty, diff_stat}`; the last three are `null` for a reader or when no commit is made |
| `cancel_sessions` | `session_id` (required; `null` for a slot with no session yet), optional `closed_label` (default `true`) | `{session_id}`; `null`, or a session this run never bound, succeeds without action |
| `workspace.commit` | `session_id`, `message`, `attempt_id`; optional `expected_head`, `diff_from`, `node_id` (≤ 128 stored bytes), `item_path` (≤ 1,024 stored bytes) | `{commit, empty, subject, diff_stat, node_id, item_path}` |
| `workspace.salvage` | none | `{ref, commit}` |
| `workspace.reset` | `commit` (full lowercase hex) | `{head}` |

`diff_stat` is `{files_changed, insertions, deletions, paths, paths_truncated}`;
control characters in paths are escaped as `\xNN`. The counts always cover the
whole diff. The host cuts a path list too large for its channel to its sorted
prefix (`paths_truncated: true`), so a large diff never fails after its commit.
Commit ids are full lowercase hex. A step's title is the payload `title`, else
the engine slot id with ` (attempt N)` for generation N > 1, and the facade
adds ` · ` and the first 6 characters of the session id.

**Result budget.** A result is at most 12,288 bytes as the queue stores it
(`json.dumps`, ASCII-escaped). `diff_stat.paths` gets at most 8,192 of them and
is cut first, with `paths_truncated: true`; `subject` keeps at most 256
characters and 1,536 bytes, free text 512 characters and 3,072 bytes. Echoed
ids (`node_id`, `item_path`) are never cut: the payload bounds them before any
side effect, so valid input never reaches `effect.result_too_large`.

**Paused runs.** `create_session` and `send_input` refuse a paused run with
retryable `run.paused`. `close_slot` and `cancel_sessions` still run: a close
finishes an accepted handoff, and a cancel is how a paused run ends. The
`workspace.*` executors and `recovery.restart` also run while a run is paused:
a retry keeps its run paused until its restart finished
(`test_the_restart_runs_while_its_run_is_paused`,
`tests/coral/recovery/test_ladder.py`). `recovery.wake` runs while its run is
paused only for host-offline holds, of any slot; any other pause is a
retryable `run.paused`.

**Finished runs.** The drainer abandons a finished run's items as
`run.terminal`, except an effect type registered with `runs_after_terminal`:
only `cancel_sessions`, because `cancel_run` marks the run cancelled in the
transition that enqueues it. The slot-generation fence still applies.

## Error codes

Permanent unless marked retryable. Messages are trimmed to 2,000 characters
(invalid payloads to 500) and name fields, never payload values. Host error
text lands only in the run owner's work record. The bridge's hold policy
holds some codes without spending an attempt, whatever their retryable flag
(see Holds under "The engine bridge").

| Code | Retryable | When |
|---|---|---|
| `effect.invalid_payload` | no | Payload not a JSON object; a field missing, ill-typed or over its bound; a lone surrogate in text. |
| `effect.identity_mismatch` | no | Payload identity differs from the run row; `effect_key` names another run; another send is recorded for this effect. |
| `effect.run_missing` | no | The run is not in the item's workspace. |
| `effect.result_too_large` | no | A bug: valid input never reaches it. |
| `executor.missing` | yes | Drainer: a claimed item whose effect type has no registered executor (a server whose engine is not wired, or a leader without the executors during an upgrade). Held for up to 30 minutes, then retried. |
| `executor.unhandled_exception` | yes | Drainer: the executor raised an unexpected exception (a bug or a store fault). Retried up to the attempt cap, then failed as `infra.transient`. |
| `executor.cancelled` | yes | Drainer: the executor raised a cancellation its task did not ask for. |
| `executor.invalid_outcome` | no | Drainer: the executor returned something other than an outcome (a bug). |
| `effect.result_unstorable` | no | Drainer: the store refused a success's result (it does not serialize, or it is over the column cap); the item fails without its result. |
| `run.paused` | yes | `create_session` or `send_input` for a paused run; a `turn_fact` signal for a slot still waiting on its effect while the run is paused. Held until the resume. |
| `drift.<cause>` | no | Drift found; the run was paused first (see Drift). Held until the resume. |
| `session.anchor_missing` | yes | A step before its anchor is `initialized`. |
| `session.not_ready` | yes | A send or close before the step's row exists; a writer's close before a slot names its session; a send to the run's orchestrator before its create bound it. |
| `session.host_offline` | yes | The owner's host is not connected, or the server refused for now (`CONFLICT`, `WRONG_REPLICA`, `HOST_OFFLINE`). |
| `session.runner_unavailable` | yes | The launch or session init did not complete. |
| `session.workspace_unverified` | yes | The host could not confirm the run worktree (stat timeout, I/O error). |
| `session.store_conflict` | yes | A concurrent write kept the project or anchor agent from being stored. |
| `session.row_incomplete` | yes | A duplicate-id create found a row without metadata. |
| `session.turn_state_unknown` | yes | `workspace.commit`'s turn-end check has no confirmed stop recorded, or did not answer in 30 s. |
| `session.deleted`, `session.anchor_deleted` | no | Facade codes for the `session_deleted` and `anchor_deleted` drift causes; a send to a gone session. |
| `session.archived`, `session.anchor_archived`, `session.anchor_bound` | no | Facade codes for the other drift causes. |
| `session.title_conflict` | no | Another row holds the step's exact title under the anchor. |
| `session.identity_conflict` | no | The row has no binding in this run, a torn row is not this create's own, or an adopted row differs or has another owner; send, close or cancel of a session that is not a step of this run. |
| `session.binding_conflict` | no | A redelivery would bind the session differently. |
| `session.agent_not_permitted` | no | The agent is missing (an id no agent can have included), owned by another user, or is `coral__anchor`. |
| `session.harness_not_supported` | no | The agent's harness is native, or its stored spec no longer loads. |
| `session.agent_not_supported` | no | The agent's spec does not have a Coral step bundle's shape: claude-sdk, `params.coral.generated.stance` fitting the slot role (`orchestrator` for an orchestrator slot; `implementer` or `reviewer` for the others), and the bundle hygiene rules. A structural check, not a provenance one. Checked after the native refusal, before any row. |
| `session.harness_not_configured`, `session.workspace_missing` | no | The host refused the step's launch, or dispatch's runner wake before a send, for these reasons. |
| `session.host_not_permitted` | no | The host is unknown (an id no host can have included), another user's, another registration's or a managed sandbox. |
| `session.host_unsupported` | no | The owner's live host connection does not advertise `coral_runner:2`: update Coral on that host, or unset `CORAL_DISABLE_HOST_ENTRY_POINTS` there. Checked before any row, again before the launch, and on every relaunch (`require_coral_runner`). |
| `session.not_bound` | no | A relaunch of a session whose binding is not a step's, not `initialized`, or at another generation, or whose run is gone. |
| `session.closed` | no | A relaunch or wake of a step session labelled `omnigent.closed`, also one closed while it relaunched. The wake's failure pauses `failure_path`, which a Retry clears. |
| `session.runner_status_unknown` | yes | The host did not answer a runner-status query, or answered anything but `alive`, `sign_in_pending`, `dead` or `unknown`. |
| `session.runner_changed` | yes | The session's row names another runner than the one the relaunch asked the host about; nothing was stopped. |
| `recovery.runner_alive` | yes | The host says the old runner is alive (`alive`, `sign_in_pending`) while it is not connected. Held, never superseded (see Holds). |
| `recovery.host_offline` | yes | A wake whose step's host is offline. Held; the slot is held `infra.host_offline` (see "Restarts and runner loss"). |
| `slot.generation_mismatch` | no | The abandon code of a row whose slot moved to a newer generation: the drainer's lease check, the relaunch's checks before and after its launch, and a create whose slot moved meanwhile (the session is labelled closed and its runner stopped). No outcome is fed for an abandoned row, except an abandoned `recovery.restart` of the slot's current generation. |
| `session.owner_revoked` | no | The run owner's account was revoked or re-registered. |
| `session.invalid` | no | An ownerless run outside a single-user server; a step run with no worktree on a host; a server with no project store or no host access; another refusal. |
| `dispatch.runner_unavailable` | yes | The runner did not take the event in 120 s, or the server answered `RUNNER_UNAVAILABLE` (a relaunch refusal included), `HOST_OFFLINE`, `WRONG_REPLICA` or `CONFLICT`. |
| `dispatch.stop_unconfirmed` | yes | The server could not confirm that no runner of the session is alive. |
| `dispatch.failed` | yes | Any other server error. |
| `dispatch.policy_denied` | no | The session's input policy denied the message (an ASK policy denies at once). |
| `dispatch.session_closed` | no | The session carries `omnigent.closed`. |
| `dispatch.stable_id_taken` | no | Other items hold the engine's stable id and its fallback. |
| `dispatch.message_too_large` | no | The message is over 1 MiB. |
| `dispatch.not_permitted` | no | The server refused the run owner (403, or 404 on a row that exists). |
| `dispatch.invalid_input` | no | The server refused the event as invalid. |
| `slot.close_blocked` | yes | A prompt is open; the close waits for the user and never interrupts it. |
| `slot.close_restarted` | yes | The session ran again after the close's stop; the retry stops it again. |
| `timer.early` | yes | `timer`: the row came before its timer's due time. |
| `signal.awaiting_effect` | yes | `turn_fact`: the slot's last create, send or nudge has no receipt yet; the signal applies after it. |
| `run.contended` | yes | `timer`, `run_resync`, `turn_fact`: other commits to the run kept winning. |
| `engine.load_failed` | no | `timer`: the run cannot be loaded; it was paused `failure_path`. The resync revives the row while the timer is armed. |
| `engine.commit_unbuildable` | no | `timer`: the firing's commit could not be built, and the run was paused instead. The resync revives the row while the timer is armed. |
| `workspace.host_not_permitted` | no | `HostAccessRefused("not_permitted")`. |
| `workspace.op_host_violation` | no | No binding in the run, another host, not the slot's current generation, a reader, or the turn not ended. |
| `workspace.*` (K13) | per K13 | `timeout` is always retryable; `backend_unavailable` is retryable unless the host marked it permanent; `capability_unavailable`, `worktree_displaced`, `git_failed`, `target_mismatch`, `op_key_conflict` and `invalid_params` are permanent. A `diff_stat` failure after a recorded commit is retryable unless permanent: the retry returns the same commit. |

`target_mismatch` also covers a run spec with no host, repository, worktree or
branch, or a branch other than `run_branch_name(run_id)`.

## Drift

| Cause | Facade code | `detail` |
|---|---|---|
| `anchor_archived` | `session.anchor_archived` | the archive timestamp label, else `archived` |
| `anchor_deleted` | `session.anchor_deleted` | `deleted` |
| `anchor_bound` | `session.anchor_bound` | the anchor's runner or host id |
| `session_archived` | `session.archived` | the archive timestamp label, else `archived` |
| `session_deleted` | `session.deleted` | `deleted` |

- **Where it is found.** The facade's step guard (the anchor, then the step's
  own row, again right before launch), the dispatch pre-send hook (the run's
  anchor, then the target step), and the `turn_fact` executor, which reads a
  live step's session (and, while a decision waits, the orchestrator's) before
  it gathers a turn. Only sessions whose row this run created count. Stop,
  interrupt, close and cancel never consult the hook. The `turn_fact`
  executor skips a step that already handed off: archiving a finished step is
  no drift.
- **What happens.** The pauser commits through the engine bridge: the engine's
  `PauseRun(reason="drift", detail=<cause>)`, after its `StartRun` when the
  engine has not started, and for a STARTING or RUNNING run one `PAUSED` log
  entry, in one commit. The run moves to `paused(drift)` (`pause_reason` 12).
  The entry's body is
  `{"kind": "pause_run", "reason": "drift", "cause": <cause>, "session_id": <session>, "detail": <detail>}`
  and its idempotency checksum is
  `sha256("coral-drift\0<run_id>\0<cause>\0<session_id>\0<run version>")`, so it
  is one entry per pause epoch. On a run already paused only the engine
  records the cause; a finished run is left as it is. A resume clears the
  engine's pause and the row's together. A run resumed while the drift
  persists is paused again by the next engine action. The effect then fails
  as `drift.<cause>`, which the bridge holds until a resume. `anchor_bound` is
  an additive K2 cause; after its pause Coral also stops the anchor's runner,
  best effort (see Anchor runner).

## Engine messages

- Every engine message starts with the fixed line `Message from the Coral
  engine:`, so a brief starting with `!` or `/` is never parsed as a shell or
  slash command. The server also refuses an engine message whose first text
  starts with `!` or `/`, and any engine event other than `message`,
  `interrupt` and `stop_session`. Engine sends are model input only. This
  holds while every harness delivers one message as one input.
- `send_input` records the stable id and the checksum of the exact text before
  it sends. A message counts as already sent only when the item under the id
  (or its fallback) is a user message by the run owner with that exact text.
  An item someone else put under the id moves the send to the fallback id.
- A saved engine item is resent under the same id unless the runner took it:
  the session is `running` or `waiting`, or another item follows it.

## Close and cancel

`turn_state`: a pending elicitation, or `running` with `blocked_on`, is an
open prompt; `running` is a running turn; `idle`, `failed`, `waiting` and
unknown statuses are an ended turn.

**Close order** (each step safe to repeat):

1. Watch the session's edges, then read its live status.
2. Turn end: an open prompt raises `slot.close_blocked`. A running turn gets
   up to 120 s to end, then an interrupt and 30 s to settle; past that the stop
   ends it. A prompt that opens meanwhile also raises `slot.close_blocked`.
3. Writers: fingerprint the worktree (L1).
4. Write `omnigent.closed`; from here the server refuses new user messages.
5. Stop the runner, confirmed, and record the stop.
6. Writers: fingerprint again (`post_accept_edits` when the digest changed),
   re-check that the session did not run again (`slot.close_restarted`), then
   commit at the HEAD recorded before the first try. A retry past an earlier
   try's stop (its stop or commit intent is recorded) cannot see the turn-end
   tree: it returns that try's `post_accept_edits`, kept in process, or `true`
   when it was lost.
7. `diff_stat` of the commit.
8. Queued input: any item a client created after the slot's last engine item
   (a user or meta message, a slash command, posted tool output, a pending
   entry not the engine's). The walk reads 50 items a page, newest first, up
   to 1,000; no decision counts as queued input.

`pending_input` is `queued_input or post_accept_edits`. Readers never commit.
The engine keeps a slot whose close reports pending input `closing` and
pauses the run `drift` (detail `pending_input`). The resume closes the slot
with the commit it already made and the run goes on.

**Cancel:** a running turn is interrupted and given 30 s to settle; then the
session is closed (when `closed_label`) and stopped, confirmed. An open prompt
is not waited on.

**A response id this replica did not see.** `LiveStatus.response_observed`
(`coral/omni/protocols.py`) says whether `response_id` came from this
replica's own cache, which its edges fill. A server restarted during a turn
never sees that turn start: it stores the rest of the turn under made-up ids,
so its live read falls back to the newest stored item's id, which may name no
turn (`response_observed: false`). The close then waits for the session's next
end edge, whatever response it names, and interrupts without an id
(`_awaited_response`, `coral/slots/close.py`); `cancel_session` does the same.
A known id keeps the rule that an outcome for another response never ends the
wait. Proof: `test_a_guessed_response_ends_the_wait_at_the_turns_own_end_edge`,
`test_a_guessed_response_is_not_used_to_pick_the_turn_to_interrupt` and
`test_a_known_response_waits_out_another_responses_outcome`
(`tests/coral/slots/test_close.py`), and the in-process
`test_a_close_after_a_restart_mid_turn_ends_at_the_turns_own_end_edge`
(`tests/coral/omni/test_ac2_stop_cancel_end_to_end.py`). Limits:

- With a guessed id, any end edge published once the close watches ends the
  wait, an earlier turn's late outcome included
  (`test_an_earlier_turns_late_end_edge_ends_only_a_guessed_wait_that_saw_it`).
  The stop then ends a turn that is still running, and a writer's later edits
  still show as `post_accept_edits`. No Omnigent path is known to publish
  such a late outcome.
- An observed id is not proof of the running turn: Omnigent can briefly keep
  an earlier turn's id in its cache, and a close that reads in that instant
  waits on the ended turn under the known-id rule.

**Commit gate.** `workspace.commit`'s turn-end check (`StopConfirmedTurnEnd`)
answers `True` only for an `idle` session whose stop a close confirmed in this
process; `running`, `waiting` or an open prompt is `False`
(`op_host_violation`); anything else is retryable `session.turn_state_unknown`.
The closed label alone proves nothing.

## Status edges (K18)

S1 hands every published edge (`omnigent.server.session_live_state.SessionStatusEdge`)
to the registered observers, from any thread, never raising. Coral reads:

| Field | Use |
|---|---|
| `workspace_id`, `session_id` | Watch key: session ids repeat across workspaces. |
| `status` | `TurnFact.live_status`; a `running` edge clears a confirmed stop. |
| `turn_outcome` | `completed`, `cancelled` or `failed` for the turn named by `turn_response_id`. |
| `turn_response_id` | The response the outcome reports on; `TurnFact.response_id`. |
| `response_id` | The response a `running`/`waiting` edge opens; `TurnFact.response_id` when there is no `turn_response_id`. |
| `origin` | `TurnFact.origin`; an origin containing `archive` reads as `archive`. |
| `failure_origin` | `TurnFact.failure_origin` (failed edges). |
| `previous_status`, `blocked_on`, `observed_at_ms` | Kept on the edge view, not on the fact. |

Origins: `relay_turn_end` (a recovered relay turn end, B1), `status_probe`
(a cold-cache probe, B2), `archive_idle` (the archived session's own stop
edge), `runner_disconnect` (the relay's failed edge), else `unknown`, the
main relay edge included.

Outcomes come from the runner (S43) for every headless turn end (native
harnesses' non-failed edges are dropped), carried on the next turn's
`running` edge when buffered input follows, and from the server for a
stop, archive or offline settle (`cancelled`, only for a turn that was
running) and for a runner drop (`failed`). The server reports an inferred
outcome only for a response with none recorded yet. Precedence for consumers:
the latest outcome reported for a response is its outcome, which is the
runner's own when both exist; a plain relayed report and an inferred one both
carry origin `unknown`. An outcome with no response id never matches a
response-keyed wait. A close or cancel wait ends at the first terminal outcome
or ended status for its response. An idle edge without an outcome never says a
turn completed.

`CoralStatusEdges` costs one dict read for an unwatched session. A watched
session's edge becomes a `TurnFact` on the server's loop, resolves the waiters
it matches, and reaches the `TurnFactSink` hook, which the server leaves
unset. Turn ends persist through a second observer, `"coral.turn_facts"`,
which reads every bound session's raw edges (see Turn facts under "The engine
bridge").

**End-to-end proof.** `tests/coral/omni/test_ac2_stop_cancel_end_to_end.py`
drives Coral's `stop`, `cancel_session` and a reader's bounded
`close_session` through the real `_post_event_impl`, relay and an in-process
runner over the WS tunnel, with a stub harness. It covers an interrupted
turn, an interrupt with buffered input, a runner-cancelled turn, a runner that
survived a disconnect (B1), and a close whose turn outlives the bound. That
is the runner-forwarded stop and interrupt, which production also runs first.
It does not cover: the host-owner runner kill and the server's own inferred
`cancelled` edge (component tests only:
`tests/server/routes/test_intentional_runner_stop.py`,
`tests/coral/omni/test_status_edges.py`); a facade-created step under an
anchor (the test's session is hostless and bound with `PATCH runner_id`); a
writer's close and commit (`tests/coral/slots/test_close.py` and the AC3
host-channel test).

## The engine bridge

`coral/bridge/` joins the engine to the queue. It queues the work each engine
effect implies, folds each finished item back into the engine, holds work
that waits on something else, turns status edges into turn facts, and
repairs each run level-triggered.

**It authorizes nothing.** `start_engine_run` (`coral/bridge/start.py`),
`EngineBridge.resume_run` and `EngineBridge.cancel_run` take the actor who
asked and record it as the run log's `actor_ref`; the caller (the runs API)
checks that the actor may start, resume or cancel the run and use its
workflow, and takes the run owner, credentials, workflow and run target from
the server, never from the request. Engine tool calls record the calling
session ([`engine-tools.md`](engine-tools.md)).

**One commit path.** Every engine input (a start, a finished item's outcome, a
timer, a turn fact, a resume or cancel, a drift pause, an engine-tool decision)
goes through `build_commit` (`coral/bridge/commit.py`) and one compare-and-swap
`apply_transition`: the entries as ENGINE log rows, the work their effects
queue, timer rows for new armings, the run, slot and gate-visit projections,
the run's alert raises and resolutions
([`gates-and-inbox.md`](gates-and-inbox.md)), and, on a return to running, the
release of held items and the revival of exhausted effects. Engine state is
never stored: it is the fold of the run's ENGINE rows over the graph pinned at
start, with the config frozen in the run spec
([`persistence.md`](persistence.md)). A run that cannot be loaded is paused
`failure_path` (detail `engine.load_failed`) once, on its row alone. A commit
that cannot be built (more than 64 rows, a profile with no step stance, an
oversized payload) pauses the run `failure_path` instead of being retried.

**Start.** `start_engine_run` compiles and validates the YAML itself, never
taking a graph from the caller, and refuses, before anything is written, with
`RunNotRunnable(code)`: `workflow.invalid`, `workflow.too_large`,
`graph.unresolved`, `graph.no_start`, `profile.unsupported` (a roster profile
other than `implementer` or `reviewer`), `run.owner_required`,
`run.field_invalid` (out-of-range limits, a preset orchestrator, text a column
cannot take), `run.target_invalid` (no host, worktree or repository, or another
branch than `run_branch_name(run_id)`), `graph.leaves_region` (an arrow out of
a parallel branch), `graph.concurrent_writers` (two implementers at once in one
worktree), `graph.too_wide` (more than 32 live slots, or 48 live slots, open
decisions and open gates), `graph.gate_too_large` (a gate with more than 16
outcomes or an outcome over 128 characters), `graph.gate_label_invalid` (a gate
outcome with a control or invisible formatting character, such as a bidi
override or a zero-width space) and `graph.ids_too_long` (an effect key over
512 characters, a gate's `withdraw_gate` key included). It then pins the graph,
starts the run and commits `StartRun`. A repeat with the same key, caller
fields and YAML returns the same run; anything else is `StartKeyConflict`.

**Work.** One row per effect or bridge item, keyed so a repeated commit never
queues it twice. Slot rows carry the store `slot_id` and the slot's
generation, so the drainer abandons a stale one; every payload stays under
15,000 bytes, because message texts are cut to fit.

| Effect or bridge item | Row (`effect_type`) | Idempotency key | Its outcome |
|---|---|---|---|
| The anchor, with `StartRun` | EFFECT `create_session` (`role: anchor`), due at once | `<run_id>:anchor:create_session` | A failure pauses the run (`anchor:<code>`) |
| `create_session` | EFFECT `create_session`: `role: step`, `stance`, `workflow_slug`, `node_id`, `roster_index`, `engine_slot_id`, `slot_role`, `generation` | the effect key | `EffectCompleted` or `EffectFailed` |
| `send_input` (the brief) | EFFECT `send_input`, `kind: brief` | the effect key | same |
| `nudge` | EFFECT `send_input`, `kind: nudge` | the effect key | same |
| `close_slot` | EFFECT `close_slot`, `interrupt` and `closed_label` true | the effect key | same |
| `cancel_sessions` | EFFECT `cancel_sessions`, `session_id` of the slot's latest create, else `null` | the effect key | none: the run is finished |
| `retry_step` | EFFECT `recovery.restart`, fenced by the slot's new generation: `engine_slot_id`, `generation`, `session_id` (the slot's latest create, still the old generation's, or `null`), `writer`, `expected_head` (nullable), `close_key` (the slot's newest close whose commit never reached a receipt, or `null`) | the effect key | `EffectCompleted` `{salvage_ref, salvage_commit, head_verified, head}`, or `EffectFailed`; an abandoned row of the slot's current generation is fed as a permanent failure |
| `runner_lost` | EFFECT `recovery.wake`, fenced by the generation that lost the runner: `engine_slot_id`, `generation`, `session_id`, `runner_id` (nullable) | the effect key | `EffectCompleted` `{outcome: skipped \| runner_back \| relaunched, turn_running, seen_at}`, or `EffectFailed` |
| The orchestrator | EFFECT `create_session`: stance `orchestrator`, slot `orchestrator`, the run's orchestrator generation, due at once | `<run_id>:orchestrator:<N>:create_session` | A failure pauses the run (`orchestrator:<code>`) |
| A decision's request, reminder or re-request | EFFECT `send_input` to the orchestrator | `<run_id>:decision_request:<decision>` (generation 2 on: `<run_id>:orchestrator:<N>:decision_request:<decision>`); the watchdog `notify`'s key; `<run_id>:decision_rerequest:<decision>:<run version>`; a backoff re-ask `<run_id>:orchestrator:<N>:backoff:<decision>:<notify key>` | A failure pauses the run (`decision:<code>`) while the decision is open; a send to a session the row no longer names completes `{"skipped": "stale_orchestrator"}` |
| An old orchestrator's fence; a finished run's wind-down | EFFECT `cancel_sessions`, no bridge item | `<run_id>:orchestrator:<old N>:fence`; `<run_id>:orchestrator:<N>:wind_down` and `<run_id>:anchor:wind_down` | Never fed |
| An armed timer | TIMER `timer`, due at its deadline | `timer:<key>:<generation>:<due_at_us>` | The executor commits `TimerDue` |
| A bound session's turn end; a re-gather | SIGNAL `turn_fact` | `sig:<session>:<response or origin>:<status>:<observed_at_ms>`; `sig:<session>:resync:<five-minute bucket>`; a run's first re-gather in a leader term `sig:<session>:boot:<boot id>` | The executor reconciles the turn |
| The run's repair | SIGNAL `run_resync`, one recurring row per run | `resync` | The executor runs the resync |
| `publish_gate` | EFFECT `gate_publish`, payload the visit's row id only | the effect key | Never fed to the engine; a final failure pauses the run (`gate:<code>`) while its visit is live |
| `withdraw_gate` | EFFECT `gate_withdraw`, run after the run ended too | the effect key | Never fed; a failure never pauses the run |

`notify` (other than a decision reminder) queues no work; it is logged when
committed (`UNMAPPED_KINDS`, `coral/bridge/mapping.py`). Alerts come from the commit itself,
not from `notify` ([`gates-and-inbox.md`](gates-and-inbox.md)). `arm_timer`
needs none: timer rows come from the run's armed timers. Briefs carry the
step's goal, the run request (its `request_preview`, at most 512 characters),
the reports that led to the step and the label and reason of a decision that
sent the run there, quoted line by line as data; every brief and nudge repeats
the activation id. A retried step's brief also says "Coral restarted this step
from its last handoff. The previous attempt's uncommitted work is saved at
<ref> (commit <first 12>), and the worktree was reset.", built only from a
`refs/coral/salvage/` ref and a full commit id (`salvage_note`,
`coral/bridge/messages.py`). Agent sandboxes mask `.git`, so the new session
cannot read that ref itself.

**Feedback.** The drainer finishes a row first; then the bridge's hook folds
its outcome (`coral/bridge/feedback.py`). A SUCCEEDED row becomes
`EffectCompleted` with the result fields the engine reads. A row that failed
after its retries ran out becomes a retryable `EffectFailed`, which pauses the
run `infra` and leaves the effect without a receipt; any other failure is
permanent, receipts the effect and pauses `failure_path`. The receipt marks
the effect consumed, so feeding a row twice changes nothing. A completed
create pushes its session into the bound-session index. Only a resume revives
a FAILED row of an unreceipted effect, and a FAILED `gate_publish` of a live
visit.

**Holds** (`bridge_hold_policy`, `HOLD_RULES` in `coral/bridge/config.py`). A
refused item with one of these codes is re-pended without spending its
attempt. Its horizon counts from `held_since`, the first refusal of the
current hold; past it the item takes the normal retries and a final failure
pauses the run.

| Code | Held for | Horizon | Ended by |
|---|---|---|---|
| `run.paused`, `drift.<cause>` | 300 s | none | the resume commit, which releases them |
| `slot.close_blocked` | 15 s | none (a person answers the prompt) | the next try |
| `session.not_ready`, `session.anchor_missing` | 5 s | 30 min | the next try |
| `session.host_offline`, `session.turn_state_unknown` | 30 s | 30 min | the next try |
| `executor.missing` | 60 s | 30 min | the next try |
| `signal.awaiting_effect`, `timer.early` | 5 s | none | the next try |
| `recovery.host_offline` (a wake whose host is offline) | 30 s | none | the host's return |
| `recovery.runner_alive` (a wake whose old runner the host calls alive) | 30 s | 10 min | the runner reconnecting, or the host calling it gone |

`held_since` starts afresh only when a re-pend moves the row into or out of a
wait for an offline host (`HOST_WAIT_HOLDS`: `session.host_offline`,
`recovery.host_offline`), so time spent waiting for a host never counts
toward another code's horizon, while a normal retry between two holds, or two
horizon codes in turn, keeps the first start
(`test_two_horizon_codes_that_alternate_stay_bounded_by_the_first_holds_start`,
`tests/coral/bridge/test_executors.py`;
`test_each_hold_code_runs_its_own_horizon_across_offline_alive_offline_alive`,
`tests/coral/recovery/test_relaunch.py`).

An effect held just after a resume released the holds is released by the
run's next resync. A commit that leaves a run paused only by host-offline
holds, having cleared some other cause, also releases its `run.paused` rows,
so a waiting wake checks its host again at once
(`test_a_resume_that_leaves_the_host_hold_re_checks_the_host_within_30_seconds`).

**Drain pool and resync.** The supervisor runs `coral_drain_concurrency`
workers (default 4; [`plugin.md`](plugin.md)), never two items of one run at
once in a process, so a slow close holds up only its own run. Every minute it
makes each active run's `run_resync` row due, a paused run's at most every 15
minutes. The resync starts a run whose `StartRun` was lost; feeds the finished
rows of unreceipted effects, the anchor and the orchestrator's create and open
requests, and queues missing ones, a live gate visit's `gate_publish` among
them; restores the rows of armed timers and revives a FAILED one; releases the
holds of a running run; re-gathers the turn of each working slot of a running
run, and of the orchestrator a decision waits on, once every five minutes; and
writes the projection when the rows differ. Hourly, finished SIGNAL and TIMER
rows older than 24 hours are purged; EFFECT rows stay.

**Leader terms.** One replica leads at a time under the `coral.worker.primary`
lease, `coral_worker_lease_seconds` long (10-600, default 120; renewed every
`min(30, lease / 4)` s; [`plugin.md`](plugin.md)). A restarted server leads,
and recovers runs, once the dead leader's lease has run out. At the start of
every term, before the startup sweep, the leader starts its records afresh
(`EngineBridge.begin_leader_term`, `LivenessRef.reset`): a new boot id, no
runner clocks, no record of earlier re-gathers or schedules. So in a new term
a running run's first re-gather is due at once, keyed
`sig:<session>:boot:<boot id>` and repeated, not re-keyed, for the rest of that
five-minute bucket, and the run is recorded only after its signals were
queued; a paused run's first resync is due at once too, so a restart's feed
that a crash lost is fed right away
(`test_a_restarted_bridge_re_gathers_a_working_slot_at_once_and_not_again_in_the_bucket`,
`test_a_run_is_marked_re_gathered_only_after_its_signals_are_queued`,
`tests/coral/bridge/test_turn_facts.py`;
`test_a_restarted_bridge_feeds_a_finished_restart_at_once`,
`test_a_bridge_that_leads_again_resyncs_a_paused_run_at_once`,
`tests/coral/bridge/test_resync.py`). That costs one resync of every
unfinished run at the start of a term, bounded by the drain concurrency.
After a successful resync of a running run the liveness pass runs (see
"Restarts and runner loss"); while one of its clocks runs, the resync's result
carries `next_resync_at` (epoch seconds) and the finished hook moves the row
to that time when it is sooner.

**Turn facts.** `TurnFactRecorder` (`coral/omni/server/turn_facts.py`) is the
S1 observer `"coral.turn_facts"`. For each published edge it does one dict
read of the bound-session index; an edge of a bound step that can end a turn
(a turn outcome, or an `idle` or `failed` status), or of the orchestrator that
failed or was archived, goes to one worker thread through a bounded queue
(1,024 edges, 16 per session; more are dropped and counted). The worker writes
the `turn_fact` signal with the edge's text cut (codes 128 characters, the
message 1,000), retrying a store error twice. The observer never blocks,
raises or reads the store. The index is rebuilt from the binding store at
start and every minute (`BoundSessionRefresher`), so finished runs drop out.

The `turn_fact` executor completes without a commit for a finished run, a
session the slot no longer holds, or a step that already handed off; it holds
a signal while its slot's create, send or nudge has no receipt. Otherwise it
reads the session's stable ids, its transcript (pages of 50, newest first, up
to 1,000 items) and then its live status, and builds the `TurnFact`, keyed by
the engine message that started the turn
(`turn:<session>:<generation>:msg:<stable id>`), so the edge and a re-gather
build the same key. A turn a person typed, a cancelled or archive edge, and a
walk that cannot tell who started the turn change nothing. A failed turn whose
edge was lost is `edge_lost`, and a finished turn too long for the walk is
`turn_unreadable`; the engine treats both as transient. The engine then
reconciles the fact: a completed turn without a handoff is nudged, up to
three times in a row, and the next such turn end pauses the run
`rejected_calls`; a 529 backs off (re-prompts at 30 s and 2 min, then pauses
`infra` at 8 min if the step still fails); a 429 pauses `plan_limit`, and a
probe from 5 minutes, doubling to an hour, clears it and re-prompts; a 401
pauses `auth`. The classifier reads explicit codes and statuses first, then only
the start of the error text: claude-sdk's `API Error: NNN`, `Error code: NNN`,
`status_code=NNN`, the API's error body and the usage-limit notice, and
Omnigent's own `turn failed (status NNN)`, `runner returned status NNN` and
`Could not load the agent spec (... HTTP NNN)`. A failure no rule names
(`agent.failed`) pauses the run `failure_path`.

**What a resume clears.** `ResumeRun` clears the causes `user`,
`rejected_calls`, `infra`, `auth`, `drift`, `plan_limit` and
`authority_revoked`, and `budget` only with a higher activation cap
(`resume_clears`, `coral/engine/lifecycle.py`). It never clears a cause that
holds a slot, `infra` / `infra.host_offline` or `infra` /
`recovery.restarting`, and never any `failure_path` cause, a step's failed
turn no rule names (`agent.failed`) included
(`test_resume_never_clears_a_steps_failed_turn_and_a_retry_restarts_the_step`,
`test_resume_clears_no_failure_path_cause`,
`tests/coral/engine/test_lifecycle.py`). A resume that returns the run to
running re-prompts each failed or stopped step once. A step's `failure_path`
or `liveness` cause, and any `infra` cause a step owns, is cleared by a Retry
of that step (below). Causes no step owns, a permanent anchor, orchestrator,
decision or gate failure (`anchor:*`, `orchestrator:*`, `decision:*`,
`gate:*`), a commit that cannot be built and other run-level `failure_path`
pauses (subject `""`), are not a step's Retry
(`test_a_cause_no_step_owns_is_not_retryable`): the run's own Retry
(`RetryRun`, `retry_run`) clears them all at once, refused
`host_offline_hold` or `restart_in_progress` while a hold or restart stands
and `retry_not_allowed` when there is none. An `orchestrator:*` or
`decision:*` cause also moves the orchestrator to its next generation (below).
A run left with no other cause runs again and is re-asked as a resume does
(`tests/coral/engine/test_orchestrator_lifecycle.py`). A
run paused `failure_path` with detail `engine.load_failed` can be neither
resumed nor retried; the runs API's `:cancel` cancels it on its row alone
([`runs-api.md`](runs-api.md), "Actions"). `engine_upgrade` is cleared by
neither. A run whose log was written before these rules (its `StartRun` carries
no rules marker) folds with the previous rules, which let Resume clear
`agent.failed`, so a stored run never changes state on upgrade (the
`rules < RULES` branch of `resume_clears`, `coral/engine/lifecycle.py`; its
previous edge runner-loss rule is `coral/engine/previous_rules.py`).

**Retry.** `RetryStep` restarts one failed step activation in a new session
generation; the runs API sends it ([`runs-api.md`](runs-api.md), "Actions").
`retryable_activations(state)` is the one rule: empty unless the run is paused
and no slot holds; otherwise the step activations named, in cause order, by a
cause whose reason is `infra`, `failure_path` or `liveness` (a slot subject
names its activation, an activation subject itself, a node subject that node's
newest activation), keeping only activations with slots that did not close
`completed` or `skipped`. Gates and decisions never qualify; a step that
closed `failed` does. A retry clears every cause of the retried step (those
whose subject is one of its slots, the activation itself or its node), plus its
slots' `drift` / `pending_input`, and nothing else: another failed step keeps
the run paused (`test_retrying_one_of_two_failed_steps_clears_only_its_cause`,
`test_retry_refuses_a_completed_step_a_gate_and_a_decision`). It refuses
`host_offline_hold` while a slot is held offline, `restart_in_progress` while
any slot restarts, and `retry_not_allowed` otherwise
(`test_a_retry_while_a_restart_or_a_host_hold_stands_is_refused`). A taken
retry bumps each of the activation's slots to `session_generation + 1`, sets it
`pending` with its handoff, label, pending input, failed turn, nudges and wake
count cleared, resets the activation's attempts, records the cause `infra` /
`recovery.restarting` / slot (so the run stays paused) and emits one
`retry_step {generation, phases, expected_head}` per slot. A wake keeps the
attempts; only a retry resets them.

**The restarting pause.** Four invariants keep a retried step's old session
from acting between the retry and its fence, each with a test:

1. Only a finished restart, a failed or abandoned restart, or a terminal input
   removes `recovery.restarting`: Resume does not clear it, a Retry is refused
   `restart_in_progress`, and holds and other completions remove only their own
   causes
   (`test_only_finishing_or_failing_the_restart_or_a_terminal_input_ends_the_restarting_pause`,
   `tests/coral/engine/test_lifecycle.py`).
2. The pause lifts only after the fence confirmed the old session's stop and
   labelled it `omnigent.closed`, or found no session, an unbound one or a
   deleted one
   (`test_the_restarting_pause_lifts_only_after_the_old_session_is_closed_and_stopped`,
   `tests/coral/omni/test_recovery.py`).
3. A failed restart stays paused, Retry-only, and the next Retry makes the next
   generation and fences the same old session
   (`test_a_failed_restart_stays_paused_for_a_retry_that_fences_the_same_session`).
4. A create of the old generation in flight at the retry leaves no live,
   unlabelled session: its row is abandoned at its next lease check, a create
   whose slot moved is labelled closed and stopped, and a late completion is
   receipt-only
   (`test_a_create_in_flight_at_the_retry_never_leaves_a_live_unlabelled_session`).

From the retry until the restart is claimed, the old session's tool calls are
denied `[run.paused]`; after the restart, `[session.closed]`
(`test_a_retried_writer_is_fenced_salvaged_reset_and_briefed_at_generation_two`).
A finished restart drops the slot's restarting cause and emits the next
generation's `create_session` with `generation` and, when it salvaged,
`salvage_ref` and `salvage_commit`; the create's completion briefs the new
session with the salvage paragraph. When the run runs again it finishes
pending closes and re-prompts as a resume does. A failed restart, or an
ABANDONED `recovery.restart` row of the slot's current generation, which the
resync feeds as a permanent failure with the row's code, replaces the
restarting cause with `failure_path` / `restart:<code>` (code bounded to 128
characters), Retry-only
(`test_an_abandoned_restart_ends_the_restarting_pause_at_the_next_resync`,
`tests/coral/bridge/test_resync.py`). Abandoned rows of older generations stay
skipped. A completion or failure fed for an effect of an older generation is
recorded and changes no cause.

**The orchestrator.** The commit that opens a run's first decision names
`orchestrator_session_id` and queues the orchestrator's create (bundle
`coral__orchestrator`, as the run owner's agent) and the decision's request;
each later decision gets a request. A decision unanswered at 30 and at 60
minutes gets a reminder while the run runs, and every return to running asks
again about each decision still open. While a decision waits, a failed
orchestrator turn pauses the run `plan_limit`, `auth` or `infra` (detail
`orchestrator:<class>`; a failure whose edge was lost is found by the
re-gather once a runner item follows the request, and pauses `infra`), and an archived or deleted orchestrator pauses it
`failure_path` (`orchestrator:drift.<cause>`); the resume asks again. A
transient orchestrator failure (`infra.transient`) does not pause at once: it
re-asks each open decision at 30 s and 2 min and pauses `infra` /
`orchestrator:infra.transient` at 8 min only if no orchestrator turn completed
meanwhile (`ORCHESTRATOR_BACKOFF`).

**Replacing the orchestrator.** The run's Retry of an `orchestrator:*` or
`decision:*` cause raises `orchestrator_generation` (at most 32,767). The
commit that names generation N's session queues its create and a request for
each open decision, keyed by N, and fences the old session (`cancel_sessions`,
key `<run_id>:orchestrator:<old N>:fence`). Feedback from an older generation
is dropped, an older generation's queued sends are skipped, and its
`coral_choose_arrow` is refused. Generation 1 keeps its original keys, so stored
runs fold unchanged.

**Winding down.** The commit that moves a run to `completed`, `failed` or
`cancelled` closes its orchestrator (when the row names one) and its anchor,
once each: the anchor is labelled closed and stopped only if a runner holds it.
The store-only cancel closes the anchor too. A resume commit that cannot hold every
re-request drops the extra ones, which are asked again only at the next
resume; the start bound of 48 keeps a commit from filling up this way.

**Crashes.** Every step is safe to repeat. A run whose `StartRun` was lost is
started by its resync. An item whose worker died is reclaimed when its 60 s
lease expires and runs again: the facade adopts a session the create already
made, a send finds its stable id already delivered, and a close repeated after
a restart past its recorded commit reports `post_accept_edits`, which pauses
the run `drift` until a resume. A restart between the close's stop and its
recorded commit recomputes from the current tree instead, so edits made
between the turn end and the stop are committed without that flag (see
"Post-accept edits on a retry"). An outcome finished but not yet fed is fed by
the resync. A timer that already fired, or a turn fact already applied,
changes nothing when it runs again. A session the index missed is found by its
next rebuild, and an engine tool call resent after its commit gets the stored
reply. `tests/stores/coral/test_bridge_crash_recovery.py` simulates a crash at
each of these points on every database lane, and
`tests/stores/coral/test_bridge_fold.py` checks that the stored log folds to
the stored state.

### Restarts and runner loss (SES-06)

**The restart row** (`recovery.restart`, `coral/recovery/ladder.py`) runs once
per `retry_step`, while its run is paused. The drainer re-reads the slot's
generation at every lease check of a slot row and abandons a row whose slot
moved on (`slot.generation_mismatch`), so a restart, wake or close that lost a
race to a newer retry acts no further
(`test_a_slot_row_superseded_while_it_runs_stops_at_its_next_lease_check`,
`tests/coral/queue/test_drainer.py`). In order, each phase safe to repeat:

1. **Fence** the old session (`fence_session`, shared with `cancel_sessions`):
   end a running turn, label it `omnigent.closed` and stop its runner,
   confirmed. The host ends a Coral step runner's process group before it
   confirms (see "Runner process groups"). An unconfirmed stop fails retryably
   with nothing salvaged; a slot with no session, an unbound session or a
   deleted one counts as fenced.
2. A **reader** ends here: `{salvage_ref: null, salvage_commit: null,
   head_verified: false, head: null}`.
3. **Head check.** HEAD must be the expected head: the newest commit the
   run's receipts record (a writer close's string `commit`, or a restart's kept
   `head`; readers' closes carry `null` and are skipped; `_expected_head`,
   `coral/engine/lifecycle.py`), else the run's `base_commit` (the ladder's
   fallback, `coral/recovery/ladder.py`). So a review
   loop's second pass compares against the writer's commit, not the reviewer's
   null close
   (`test_a_review_loops_second_pass_restarts_from_the_first_pass_commit`).
   A commit this slot's own close made but never fed back also passes, when
   both Coral records agree: the close's op intent names the expected head, and
   the close's own commit op, sent again, answers with HEAD as its record
   (`test_a_head_at_the_steps_own_unreported_close_commit_is_kept`). Any other
   HEAD is a permanent `workspace.head_moved` with nothing salvaged, and its
   message never advises resetting a Coral commit away
   (`test_a_head_coral_did_not_commit_is_head_moved_and_never_advised_away`).
   With no expected head and no base, the restart goes on against HEAD and
   records `head_verified: false`. The verified head is recorded (an op intent)
   before anything is salvaged.
4. **Salvage, then reset under the salvage**, in up to three rounds
   (`MAX_SALVAGE_ROUNDS`). Each round salvages under its own op key (`salvage`,
   `salvage-2`, `salvage-3`), records its reset as an op intent, then sends the
   host's `reset` with `salvage_commit` as a compare-and-swap
   ([`workspace-ops.md`](workspace-ops.md), "Restart ladder"). A
   `workspace.tree_changed` starts the next round; after the third the restart
   fails permanently `workspace.tree_changed` with the tree left as it is. A
   clean salvage skips the reset. The finished restart's salvage is recorded
   once it ends. Nothing is salvaged after a successful reset: a repeat after a
   crash resumes at the last recorded round, and a finished restart names the
   same ref
   (`test_nothing_is_salvaged_after_a_reset_and_a_repeat_names_the_same_record`,
   `test_a_repeat_after_a_crash_at_every_call_boundary_gives_the_uncrashed_result`,
   `tests/coral/recovery/test_ladder.py`;
   `test_a_crash_at_any_restart_phase_still_reaches_generation_two_once`,
   `tests/coral/omni/test_recovery.py`).

The row's result is `{salvage_ref, salvage_commit, head_verified, head}`.
Coral's own log lines for it carry the run id, the phase and codes only. A failure becomes the cause
`failure_path` / `restart:<code>`; the web's texts for these are in
[`runs-api.md`](runs-api.md), "In the web app".

**Detecting a lost runner.** Two detectors feed one loss:

- **The edge.** A failed edge whose class is `infra.runner_lost` (the server
  saw the runner go) becomes a `SessionFailed` carrying the session row's
  `runner_id`, logged as `engine.session_failed`.
- **The liveness pass** (`LivenessPass`, `coral/recovery/relaunch.py`). After
  each successful resync of a running run it reads each working slot's runner
  that is not waiting on an effect (`SessionDispatch.runner_liveness`, at most
  `MAX_LIVE_SLOTS` reads). A runner neither connected on this replica nor fresh
  by the server's own rule starts a clock at this process's first sighting;
  the stamp's age is never used, because the server clears it on a disconnect
  and, while the runner's host is offline, holds the turn without any edge.
  Once `coral_runner_reconnect_grace_s` (30-600, default 90) has passed, the
  pass commits one liveness-only `TurnFact`, logged as `engine.runner_lost`.
  A clock watches one outage, keyed by the session, its runner and the slot's
  connection epoch, and ends when the runner is connected or fresh again, the
  engine ends the outage, the slot stops working, the session or runner
  changes, or the run stops running. A report counts once the engine holds the
  loss; one it dropped is made again at the next pass. A read error is logged
  with the run id and the error type, and keeps the clock. Each pass that
  starts or reports a clock logs `Coral liveness of run <id>: <n> runner
  clock(s) started, <m> runner(s) lost, <k> loss(es) already recorded, <r>
  report(s) to make again`.

Both key a loss `runner:<session>:<generation>:<runner id>:<connection
epoch>` (`runner_loss_key`, `coral/engine/facts.py`; with no runner id, the
turn's response tail stands in). So a laptop sleep, seen first by the liveness
pass and then by Omnigent's own disconnect report for the same runner, is one
loss and one wake (`test_a_liveness_loss_and_an_edge_for_one_runner_are_one_loss`,
`test_one_sleep_held_across_its_edge_is_one_loss_and_the_next_outage_is_new`,
`tests/coral/engine/test_reconcile.py`), and a runner lost again after it came
back is a second loss (`test_a_runner_lost_again_after_it_came_back_is_a_new_loss`).
A report observed before the wake saw the runner back belongs to the ended
outage and records only its receipt
(`test_an_edge_that_lands_after_its_wake_saw_the_runner_back_is_not_a_second_loss`).
In the host-outage E2E, Omnigent's own disconnect report after the host's
return is absorbed the same way. A slot wakes at most three times per
generation (`MAX_WAKES`): the fourth loss pauses `infra` / `infra.runner_lost`
/ slot instead, which Resume and Retry both clear. Losses held on an offline
host count toward it
(`test_losses_held_on_an_offline_host_still_count_toward_the_fourth`).

**The wake** (`recovery.wake`, `wake_executor`). Each `runner_lost` effect's
row, in order:

1. A slot that is gone, not `working` or at another generation: `skipped`.
2. A run paused for anything but host-offline holds: retryable `run.paused`.
3. The session's state: archived or deleted pauses the run `drift` and skips;
   closed fails the wake permanently `session.closed` (Retry).
4. `StepRelauncher.ensure_runner` (below): `connected` is `runner_back`, a new
   runner `relaunched`. Then the wake reads the live status, so a turn that
   already runs (the runner's own, after a reconnect) is reported
   `turn_running: true` and not re-prompted; otherwise the engine re-prompts the
   step once with the `runner_lost` nudge.
5. `session.host_offline` commits `RunnerHeld` once (cause `infra` /
   `infra.host_offline` / slot, Cancel only) and holds the row
   `recovery.host_offline`. Any other answer ends that hold
   (`RunnerHoldEnded`) before the wake goes on or fails. A wake that ends
   without the runner (skipped, permanent, out of retries) also ends its
   slot's hold, so a hold never outlives its wake
   (`test_a_hold_ends_when_its_wake_ends_without_the_runner`).

While a wake of the slot's generation has no result, no infra stage re-prompts
that slot (`test_no_infra_stage_re_prompts_a_slot_while_its_wake_is_in_flight`).
Each wake logs `Coral woke run <id>'s step: <outcome>`.

**Hold latency.** A host that goes offline drops its runners' tunnels with no
edge, so the hold starts at the liveness pass's first sighting (the next resync
tick, at most 60 s) plus the grace: measured at about 86 s with a 30 s grace
(`test_an_offline_host_holds_the_step_and_its_return_relaunches_it`,
`tests/e2e/coral/test_runner_loss.py`). It ends at the wake's next 30 s
re-check after the host returns, about 29 s measured there. While held, Resume
never clears the hold, Retry is refused `host_offline_hold`, and the slot's
infra backoff is disarmed.

**The `runner_lost` nudge** says "Your runner stopped and Coral restarted it.
Continue the step; when it is done, call coral_submit_handoff with activation_id
<id>." (`_NUDGES`, `coral/bridge/messages.py`). It also goes to a step whose
runner reconnected by itself (`runner_back` with no turn running), where
nothing was restarted, and a slot brought back while another slot holds the run
gets the resume text instead. Both wordings are accepted as they are.

**The one relaunch path.** After its create, Coral's own paths launch a step's
runner again only through `OmnigentStepRelauncher.ensure_runner`
(`coral/omni/server/sessions.py`), in the same session: the wake, and
`OmnigentSessionDispatch._connect_runner` for any engine send to a session
with a step binding (`coral/omni/server/dispatch.py`;
`test_a_send_to_a_coral_step_brings_its_runner_back_only_through_the_relauncher`,
`tests/coral/omni/test_dispatch.py`). Every other session keeps Omnigent's
`ensure_runner_connected`. Before any side effect, in order:

1. The binding by session must be a step's, `initialized`, at the asked
   generation (else `session.not_bound`); the run row gives the owner, the
   account registration and the host.
2. The session row must exist, not be archived (drift) or closed
   (`session.closed`), and `binding.host_id == conv.host_id == run host`,
   compared in canonical form (else `session.host_not_permitted`).
3. A connected runner answers `connected`.
4. The slot's current generation: moved on is abandoned
   (`slot.generation_mismatch`).
5. `_owner_host`: the host authorization, the owner's live connection
   (retryable `session.host_offline`) and the Coral token
   (`require_coral_runner`, `session.host_unsupported`).
6. The host is asked about the old runner, under the owner's scope:
   `alive` or `sign_in_pending` is retryable `recovery.runner_alive`; no answer,
   or any answer but `dead` or `unknown`, is retryable
   `session.runner_status_unknown`; `dead` or `unknown` (the host lost track of
   it, which counts as dead) leads to a confirmed stop of exactly that runner.
   A session row with no `runner_id` skips the query and goes straight to the
   stop. If the row names another runner by then, nothing is stopped
   (`session.runner_changed`, or `connected`).
7. The facade's own launch (`_launch`: drift re-checks, the owner's host and
   token again, the lease, the owner's scope). A relaunch resumes no turn from
   the runner's history: Coral re-prompts it
   (`test_a_relaunch_resumes_no_turn_from_history_so_its_re_prompt_is_its_one_turn`).
8. After the launch the slot generation and the session row are read again:
   a moved slot, a closed session or a deleted one gets its new runner stopped
   and is refused; a launch that kept the old runner, because it came back, is
   `connected`.

The refusals are pinned by
`test_a_relaunch_is_refused_before_any_stop_or_launch`
(`tests/coral/omni/test_session_facade.py`), the token among them
(`host_without_the_token`). A create binds only while its slot is still at the
create's generation: one the slot left meanwhile is labelled closed, its runner
stopped best effort, and its row abandoned.

**Runner process groups** (seam S108, `.coral/seams.yaml`). Every runner leads
its own process group; a zygote-forked runner stays in the zygote's session, and
the harnesses the zygote forks for it join its group. The host marks a runner as
a Coral step runner at spawn when its workspace is a checkout on a Coral run
branch (`_is_coral_run_workspace`, `omnigent/host/connect.py`), and ends that
runner's recorded group on every exit: when its watcher sees it exit, clean or
not; when a stop of it (the fence, a relaunch's stop) returns or times out,
before the stop is answered; before a status query answers `dead`; and at the
host's shutdown cleanup. A marked runner whose host dies ends the group it leads
as its last act (`omnigent/runner/_entry.py`). Runners outside such a
checkout are signalled exactly as before; a non-Coral session opened in a run
worktree is marked too. A Coral step therefore
loses every process left in its group when its runner exits for any reason,
background processes its agent started included; a process that starts its own
session escapes, except inside a bwrap sandbox, whose pid namespace ends with
it. Tests: `tests/host/test_connect.py`
(`test_only_a_coral_step_runners_group_ends_with_it`,
`test_a_runner_lost_to_sigkill_takes_its_own_group_and_nothing_else`,
`test_runner_status_answers_dead_only_after_the_lost_group_ended`,
`test_a_lost_runners_bwrap_sandbox_ends_with_it_setsid_children_included`),
`tests/host/test_runner_zygote.py` and
`test_a_runner_lost_with_its_host_ends_its_own_group_only`
(`tests/runner/test_runner_entry.py`).

**Proofs on real processes** (`tests/e2e/coral/test_runner_loss.py`, the
`coral-e2e` lane): a step runner's group SIGKILLed is relaunched in the same
session within about a second, with one loss and one wake; a host daemon
SIGKILLed holds the step with Cancel only, and its return relaunches it as one
loss; a retried blocked step is fenced, salvaged, reset and briefed as
generation 2. In process, the same paths run over the bridge test world's
fakes (`tests/coral/bridge/_world.py`) and over the real
`OmnigentSessionFacade`, relauncher and dispatch on an in-process server
(`tests/coral/omni/test_recovery.py`).

### Also known

- **macOS move-aside and `git worktree prune`.** A WRITE op renames the
  worktree to `<root>.coral-op` and back; after a host crash it moves back only
  at the next op. A `git worktree prune` in between (Omnigent's
  `create_worktree` for an existing branch runs one) deletes the worktree's
  admin dir, so the next op refuses with permanent `workspace.worktree_displaced`
  and the uncommitted work stays in `<root>.coral-op`.
- **The anchor is a live chat agent.** Its seed is a `claude-sdk` agent. Coral
  never launches it, but a user can bind a runner to it (see Anchor runner).
- **Two `cancelled` reports.** A force-cancelled interrupt with buffered input
  reports `cancelled` keyed to its response, and the turn's teardown carries a
  second, unkeyed `cancelled` on the continuation's `running` edge. The unkeyed
  one never matches a response-keyed waiter. The engine counts neither:
  reconcile ignores `cancelled`, and a turn fact is keyed by the engine
  message, not by the edge.
- **Auth-off tests.** Most facade tests, and the lifespan tests of the bridge,
  run without an auth provider, which a production server always has
  (single-user mode acts as `"local"`), so the owner, grant and
  launch-permission paths are proven mostly with auth off. Gate answers and
  the workflow Inbox also run through the real routes under header and
  accounts authentication (`tests/coral/omni/test_gate_routes_auth.py`,
  `test_gate_routes_accounts.py`).
- **Error texts.** The 529, 429 and 401 texts the classifier reads are the
  shapes traced in the claude-sdk and runner code, not captured from a real
  run: every Tier B model call is scripted (CRL-156 captures the real ones). A
  text no rule reads pauses `failure_path` (`agent.failed`), which a Retry of
  that step clears.

## Run protection

`coral_lifespan` registers these on a usable operational database whether or
not the session engine is wired (`_wire_guards` in
`coral/omni/server/plugin.py`), and removes them on exit. They are live: they
decide the tool calls of every session that has a binding row and refuse
clients' changes to it.

**Policy provider.** `CoralPolicyProvider` (`coral/omni/policies/provider.py`)
is registered as the S52 required-policy provider `"coral"`, so its policies
go ahead of every other policy in every policy build: `/mcp` (Omnigent tools,
listed to claude-sdk as `mcp__omnigent__*`), `POST
/v1/sessions/{id}/policies/evaluate` (claude-sdk's PreToolUse hook, S21, for
native and connector tools) and the relay tool-call and approval paths.

- It looks at a session whose spec has `params.coral` or whose row has a
  `coral.run_id` label. That is only a hint to look (no read). It then reads
  the session's binding row by session id in the request's workspace, through
  a cache of found rows (4,096, least recently read evicted; a miss always
  reads). Without a binding it adds nothing, so a fork or a session with
  copied `coral.*` labels is an ordinary session.
- **Anchor:** `__coral_anchor_deny_all` denies every tool call ("[anchor] The
  Coral run anchor does not run tools."), engine tools and `ToolSearch`
  included. Nothing else applies to the anchor.
- Every other bound session gets `__coral_run_guard` first, then its role
  guard:
  - **Orchestrator** (slot role `orchestrator`): `__coral_orchestrator_guard`
    allows only `coral_choose_arrow` (bare or `mcp__omnigent__`) and exactly
    `ToolSearch`.
  - **Other steps:** `__coral_step_roster` denies `sys_session_*`,
    `search_conversations`, `Agent`, `Task` and `*spawn_agent` tools.

Because the run guard goes first, on a stopped run it decides every tool it
does not exempt, so the agent always reads a stop text. A role guard's text
(the roster's points the step at its handoff report) shows only while the run
is starting or running. The verdicts are the same in either order. The role
guards are the ones each generated bundle carries
(`coral/omni/policies/guards.py`). The provider's copy is keyed on the binding
row, so it holds even when a session's agent lacks them.

**Run guard** (`coral/omni/policies/run_guard.py`). It decides from the run's
stored status, which also carries drift pauses the engine never saw, and from
the session row's `omnigent.closed` label. Only the label counts: the legacy
`:closed:` title marker does not, so renaming a step never makes it inert.
While the run is starting or running and the session is open it allows
everything. Otherwise it denies every tool call except the exact engine tools
(`coral_submit_handoff`, `coral_choose_arrow`, bare or `mcp__omnigent__`) and
exactly `ToolSearch`, which loads them (bundle hygiene refuses a local tool
with any of these names). An engine tool call then gets the engine's own answer, for example `run.paused` with a stop
`next`. Every deny tells the agent to stop and end its turn and none mentions
a handoff:

| State | Reason |
|---|---|
| session labelled `omnigent.closed` | `[session.closed] Coral closed this step. Stop now and end your turn.` |
| `paused` | `[run.paused] The Coral run is paused (<reason>). Stop now and end your turn; Coral resumes this step when the run resumes.` |
| `cancelled` | `[run.cancelled] The Coral run was cancelled. Stop now and end your turn.` |
| `completed`, `failed` | `[run.finished] The Coral run has finished. Stop now and end your turn.` |
| no run row | `[run.missing] This step's Coral run no longer exists. Stop now and end your turn.` |

An orchestrator is never called a step: its texts say "this session" and its
paused text ends after "end your turn".

**State reads** (`coral/omni/policies/state.py`). Run status is cached per
workspace and run for 2 s (4,096 entries). The run store's post-commit hook
drops a run's entries after every transition committed in this process, so a
pause applies to the session's next tool call, and a read that began before
the commit is not kept. A commit by another server process applies within
the 2 s. Creating a run fires no commit hook, so a missing run is never kept:
each build reads it again. When the store fails, a status read at most 30 s
ago serves; after that, or when the binding read fails (bindings have no
stale fallback), `__coral_state_unavailable` denies the session's tool calls
("[run.state_unavailable] ..."). Coral's policies decide tool calls only, so
engine messages and user prompts are never denied by them, and a store error
never fails the policy build. Each failure logs one warning line; its
traceback is logged once per process and error type.

**Reserved labels** (S46, `omnigent/server/routes/_sessions/helpers.py`). No
client can set a label whose key starts with `coral.`, compared as a case- and
accent-insensitive collation would (so `Coral.Run_Id` or a zero-width-prefixed
key too): JSON and multipart create and PATCH answer 400 `INVALID_INPUT` and
store nothing, and a PATCH can neither change nor clear such a label. A fork,
side chat or claude-sdk `/clear` continuation drops every `coral.*` label, so
it is a plain session. Only the facade writes `coral.*` labels, in the same
create as the row, and nothing removes them.

**Mutation guard** (`coral/omni/server/mutation_guard.py`). `CoralMutationGuard`
is registered as the S53 mutation guard `"coral"`
(`omnigent/server/mutation_guards.py`). Mutating routes ask it after their own
access checks, so a caller without access keeps its 403 or 404 and learns
nothing about the run, and before any side effect. A refusal is 409
`CONFLICT`: "Session <id> is part of a Coral workflow run, so <change> can't be
done here. You can rename, archive, delete, fork or stop it." Owners and admins
are refused alike.

- A session is protected when it has a binding row, read by session id in the
  request's workspace through the policy provider's cache of found rows. The
  `coral.run_id` label is trusted only to say a session is *not* bound:
  clients cannot write or remove it, and the facade writes it with the row. So
  a change to an unlabelled session never reads Coral's store, never waits on a
  worker thread and never fails because that store is down. A change no rule
  could refuse (an ordinary title, an archive, a pin, `interrupt`, a runner-only
  event from the session's own runner) reads nothing either.
  When a labelled session's binding cannot be read, a change a rule could
  refuse answers 500 `INTERNAL_ERROR` ("... retry"): it fails closed.
- Agent rules decide on the name alone and read nothing.

| Change to a bound session | Refused (409) | Allowed |
|---|---|---|
| `PATCH /v1/sessions/{id}` | every field but the allowed ones: `runner_id`, `model_override`, `reasoning_effort`, `collaboration_mode`, `permission_mode`, `approval_mode`, `cost_control_mode_override`, `subagent_routing_override`, `external_session_id`, `terminal_launch_args`, `project_id`, `share_workspace_files` (either value); every label whose key, as a case- and accent-insensitive collation compares it, starts with `omnigent.` (`omnigent.closed` with any value, `omnigent.parent_wake`, `omnigent.wrapper`, `omnigent.ui` and the rest), except exactly `omnigent.pinned`; a title containing `:closed:`, which Omnigent also reads as closed | `title`, `archived` (with `delete_worktree`), `family_pinned`, `silent`, `omnigent.pinned`, labels outside `omnigent.` |
| Renames through `/agent-title` and `/auto-title` | a title containing `:closed:` | any other title |
| Events to the anchor or a closed step (`omnigent.closed` = `true`) | every client event type but the allowed ones, items such as `reasoning` or `function_call`, an approval (also through `POST /v1/sessions/{id}/elicitations/{eid}/resolve`) and a peer `session_message` included, and any type Omnigent adds for clients later | `interrupt`, `stop_session`; on the anchor (closed or not) also an approval, by either route, while Coral's gate verdict handler is registered |
| Events to an open step or the orchestrator | `clear` (claude-sdk would move the step into an unbound session), a peer agent's `session_message` | `message`, `slash_command`, `compact`, `retry_session`, items, approvals, `interrupt`, `stop_session` |
| Runner-only event types (`external_*`, `subagent.status`), on any bound session, including the batched `external_conversation_item` path | from a client: Omnigent lets an owner post them, and some write the session (effort, launch args, mode labels, child rows) | from the session's own runner: a tunnel token bound to the row's `runner_id` |
| Runner launch; a grant (public included); a child session (JSON, multipart or orchestrated create) or a sibling (`sibling_source_id`, checked against the family's root); `PUT /v1/sessions/{id}/agent`; a session MCP server create, update, delete or registry select; a scheduled task created or patched to continue it | always | none |
| Revoke, delete, fork (a side chat too, see Residuals), read state, comments, session policies | never | always |

| Change to an agent named `coral__*` (any case) | Refused (409) | Allowed |
|---|---|---|
| `PATCH /v1/agents/{id}` | always: "Agent '<name>' is managed by Coral's workflow engine and can't be edited." | none |
| `DELETE /v1/agents/{id}` | without `force`: "Agent '<name>' is managed by Coral's workflow engine; delete with force=true to remove it anyway (steps running it can no longer hand off, and their runs pause after repeated nudges)." | `force=true`; no run pauses at once (see Residuals and limitations) |
| `POST /v1/agents` (install), and a bundle uploaded through multipart `POST /v1/sessions` (stored as the caller's agent under its name) | always: "Names starting with coral__ are reserved for Coral's engine agents." | none |

Engine sends (`EngineEventContext`), saved startup inputs and the runner tunnel
(whose events are checked against the row's `runner_id`) are server-internal and
never ask the guard, and the facade writes through stores, so Coral's own work
is never refused. An HTTP event carries whether its tunnel token is bound to the
session's runner. The event sets come from Omnigent (`CLIENT_SESSION_EVENT_TYPES`
and `_RUNNER_SESSION_EVENT_TYPES` through `coral/omni/_upstream.py`): a client
type Omnigent adds later is refused on the anchor and closed steps, and a
runner-only type it adds later passes only from the session's own runner, with
no Coral change. `tests/coral/omni/test_mutation_guard_routes.py` classifies
every mutating route under `/v1/sessions` and every other one that names a
session or an agent, and every WebSocket route; a new upstream route fails that
test until someone classifies it.

**Residuals.**

- A missing agent row makes `POST /policies/evaluate` answer unspecified and
  the relay tool-call path allow before any policy is built; only `/mcp` fails
  closed (S52). A `coral__` agent deleted with `force=true` leaves the live
  steps that run it in this state: they can no longer hand off, and only the
  nudge cap pauses their runs (see "Deferred work and owners").
- An approval granted for an unrelated ASK (a user's or admin's policy) is not
  re-checked by the S21 hook's ASK gate or the relay path, so a run paused
  during that human wait does not stop the one approved call. `/mcp`
  re-evaluates on its retry.
- A user's or admin's TOOL_CALL ASK policy that matches a `coral_*` tool parks
  an unattended step on its approval, like the ASK limitation for engine
  messages below.
- The roadmap's RUL-01 says a paused step can still hand off. That holds only
  at the policy layer: the run guard lets engine tools through, but the
  reducer refuses the handoff while the run is paused, so the step gets
  `run.paused` with a stop `next` and the handoff is not kept. The resume
  re-prompts the step with one nudge, and it hands off again.
- One lifespan per process: a second lifespan entered while one runs raises
  before it registers the provider or the mutation guard (see Wiring).
- A session on a Coral bundle that no run binds (a user chatting with a
  `coral__` agent, a fork of a step) pays one binding read per policy build,
  because misses are never cached, and fails closed: while that read fails,
  its tool calls are denied with the `[run.state_unavailable]` text.
- A store error, or a status outage longer than 30 s, tells the affected
  sessions to stop and end their turns. Once the store answers again, the
  run's resync re-gathers each working step's turn every five minutes, and
  the engine nudges a step whose turn ended without a handoff.
- While this process cannot read the store, a pause committed by another
  process can go unseen for up to 30 s (the stale fallback), not 2 s.
- The mutation guard leaves the workspace routes on a step's host unguarded:
  `/resources/terminals`, `/resources/files`, `/resources/environments` and
  terminal attach.
- Session policies on a run session stay editable, so a user's ASK or DENY on
  the anchor reaches every step.
- Admins bypass Omnigent's access checks, not the mutation guard. An admin's
  or an edit grantee's gate answer reaches the gate handler, which refuses it
  (`not_permitted`): only the run owner answers a gate.
- While the anchor admits approvals, an approval for an id no handler claims
  takes Omnigent's own path there: it answers 202 and drops a step prompt
  mirrored onto the anchor without answering it. Only the owner or an admin
  can post it ([`gates-and-inbox.md`](gates-and-inbox.md), Residuals).
- A split-database row read torn, without its labels, is not protected until
  the facade repairs it: the `coral.run_id` label is the only pre-filter.
- A scheduled task pointed at a session before it was bound is not checked
  again when it fires or is run now. The facade reserves each session's
  binding before it writes the session's row, so no run session exists
  unbound.
- A side chat forked from a step (`POST /v1/sessions/{id}/fork` with
  `side_chat`) is an unbound session that uses the step's runner and workspace
  outside the run's policies, like the workspace routes.

## Residuals and limitations

- **ASK input policies** deny an engine message at once (permanent
  `dispatch.policy_denied`): the engine context has no client connection to
  wait on. Accepted and documented: Coral's own policies never ask, and
  neutralising a user's or admin's ASK would override their policy. A
  TOOL_CALL ASK that matches a `coral_*` tool parks a step the same way (see
  Run protection).
- **Relaunch of a closed session** is refused and inert. Omnigent's closed
  check covers user `message` events only, but the mutation guard lets a
  closed step take only `interrupt` and `stop_session` from clients (runner-only
  events only from its own runner), so a client's `retry_session`, slash
  command, `/compact`, item event or approval gets 409, and a title or label
  that would reopen or reroute it is refused too (see Run protection). The close's commit gate catches a turn that started
  before the commit, and the run guard denies a relaunched step's tool calls.
- **Squatted ids.** A collaborator who posts under both engine ids (the stable
  id and its fallback) makes the send fail permanently and visibly
  (`dispatch.stable_id_taken`). Both ids are predictable.
- **The first line proves nothing.** It only stops command parsing. Anyone can
  write it; agent instructions must never treat it as engine authority.
- **No audit row** is written per engine send yet.
- **In-memory stop record.** `ConfirmedStops` lives in the server process. After
  a restart, `workspace.commit`'s check answers unknown (retryable) until its
  attempts run out. `close_slot` re-checks only the record it wrote itself, never
  one from before a restart. Only an observed `running` edge clears a record, so
  a reconnect that starts no turn does not.
- **Delivery window.** A crash right after a forward, retried before the runner's
  `running` edge or any output, resends once.
- **Edges without an id** (old runners, an init failure, a double teardown)
  can end a wait by status alone. The stop still runs before the commit.
- **Cold counts.** A cold cache's pending-elicitation count comes from the row
  and can block a close until the cache warms.
- **Auth off.** A client's posted tool output carries no author and is not
  counted as queued input; only the owner can post one.
- **Same-author race.** A squat in the moment between the check and the append
  can make a crash retry send a second copy.
- **Post-accept edits on a retry.** After a restart, a retry past the stop
  reports `post_accept_edits: true` (review first), so its result can differ
  from the first try's. A retry recomputes from the current tree only when no
  earlier stop is known: the stop's reply was lost, or a restart came between
  the stop and the commit's recorded HEAD.
- **Shared run worktree.** M2 has one writer per run worktree; readers never
  commit, and the commit runs after the writer's runner stopped.
- **Native harnesses** are refused as steps until HRN-03 (CRL-138). Their
  `external_session_status` outcome pass-through is HRN-05 (CRL-146).
- **Anchor runner.** The mutation guard refuses a client attaching a runner
  to the anchor (`PATCH runner_id`, runner launch; see Run protection). If a
  runner is attached anyway (before the guard was registered, or by a path it
  does not cover), the `anchor_bound` drift pause refuses further engine work,
  and then `AnchorRunnerStopper` (`coral/omni/server/anchor_runner.py`) sends
  the anchor `stop_session` through the engine dispatch, as the run owner from
  the run row, on every detection. The stop is best effort and the primary
  control stays the anchor's deny-all (every anchor tool call is denied, see
  Run protection):
  - What stops is Omnigent's choice. For a runner with no host (an anchor with
    a `runner_id` and no `host_id`), only the anchor's session on that runner
    is stopped and the runner process keeps running. When the anchor owns a
    host runner (it has a `host_id` too), Omnigent ends that runner.
  - A runner that any other session also uses is left running, with one
    warning, because ending it would take that session down. This covers a
    step of this run or another, a chat, and a child made before the guard.
    One read of the sessions pinned to the runner decides, archived ones
    included.
  - A failed stop is logged and the pause stands; the next detection tries
    again. The stop runs inside the effect that found the drift, bounded by
    the dispatch's event timeout, and does not re-check the work lease first.
    That is accepted: the pause has already committed and the stop is safe to
    repeat.
  - An anchor bound to a host only has no runner to stop.
  - The runner stays bound (stop only, no unbind), so its owner can start it
    again; the run stays paused until someone resumes it.

  The anchor seed (`coral/profiles/seeds/anchor.yaml`, from CRL-132's PRF-01)
  no longer sets `permission_mode: bypassPermissions`, so the harness's default
  applies.
- **Anchor sharing.** The anchor is private at create, and the mutation guard
  refuses any later grant (public included) and `share_workspace_files` on a
  bound session. A grant made some other way would still expose every step's
  workspace files (ADR-05 rule 6); detecting it belongs to the full SES-09
  drift (no live ticket).
- **One lifespan per process.** See "Wiring": a second lifespan entered while
  one runs raises before it registers anything.
- **`coral_runner:2` is self-reported.** The host token check is a
  compatibility gate, not an authorization boundary: steps still need a live
  connection to a host the run owner owns, with a matching account
  registration, that is not a managed sandbox. A create, a send that must
  launch a runner, and a relaunch check it (`require_coral_runner`); a send to
  a step whose runner is connected does not. A runner on a host running an
  older Coral gets no engine tools, so its turns end without a handoff and the
  nudge cap pauses its run (`rejected_calls`); a relaunch there fails
  `session.host_unsupported`.
- **"One relaunch path" covers Coral's own paths only.** A person's message to
  an open step session, Omnigent's resource and `retry_session` routes, and an
  engine send whose runner drops after `ensure_runner` answered `connected`
  can still launch a step's runner through Omnigent's own launch, without the
  token, slot or "alive" checks. That launch still lands only on the owner's
  host, closed sessions are refused (see "Relaunch of a closed session"), and
  Omnigent's automatic relaunch when a host returns skips steps, which are
  sub-agent sessions. Closing it needs an Omnigent seam (CRL-162).
- **A stop in progress reads as stopped.** The host forgets a runner when its
  stop starts, before the stop's group sweep ends, so for one sweep pass a
  status query answers `unknown` and a second stop `failed: unknown runner`.
  The fence accepts an early "stopped" there, and the relaunch takes that
  `unknown` as dead and can start a new runner beside the old group for that
  pass. The old runner's `/mcp` and events are already fenced by runner-id
  rotation (except on a server with the allow-listed runner token, below), and
  a dying shell command's write lands in the step's own worktree: after a
  relaunch the re-prompted step sees it, and after a fence the reset's
  compare-and-swap refuses it and salvages again. A host-side "stop in
  progress" answer would close it (CRL-163).
- **`unknown` counts as dead.** A host that lost track of a runner (after its
  own restart, say) answers `unknown`, and the relaunch goes ahead. A runner
  that survived that way is fenced on the server only by runner-id rotation,
  which a server with the allow-listed `OMNIGENT_RUNNER_TUNNEL_TOKEN` does not
  enforce: it accepts that token for every session
  (`omnigent/server/mcp_identity.py`). ADR-05's CRL-137 addendum records what
  such a server does with a Coral step.
- **A write while the host resets is lost.** The host's reset checks the tree
  against the salvage and then resets; a write landing between that read and
  the end of its `clean` is not recorded. Once the runner's group is gone,
  only a person can write there; while a stop reported early still sweeps the
  group (above), a dying command can too. A write after the reset is never
  salvaged; it stays in the worktree for the next generation. A crash between a successful
  reset and its `salvaged` record, plus a write in that gap, makes the repeat
  salvage only that write.
- **A restart on an offline host fails, with the host-offline text.** The
  fence's stop and the host ops are retried, not held, so a host that stays
  offline through a restart's retries (about two minutes) fails it
  `restart:dispatch.stop_unconfirmed` or `restart:workspace.backend_unavailable`,
  Retry-only, with the host-offline text. Nothing was salvaged or reset.
- **A lost restart feed waits for the next resync.** A restart row that
  finished, or was abandoned, before its feed reached the engine is fed by the
  run's resync: at once in a new leader term, else within 15 minutes for a
  paused run.
- **A create across a leader change.** Rows of one run are serialized within a
  process, not across processes. During a handover, a create still running on
  the old leader past its last lease check could write its row after the new
  leader's fence found no binding; its next lease check, or the facade's
  generation check after its launch, stops it before the step can act. The
  window is one side effect wide.
- **Two turns after a relaunch.** A relaunch resumes no turn from history, and
  the wake does not re-prompt a turn already running. If Omnigent's own
  runner-connect start of the history turn wins the race, avoiding a second
  turn rests on the wake's live-status read seeing that turn.
- **A session deleted just after its relaunch** fails the wake permanently
  instead of pausing the run for drift; the run is paused Retry-only.
- **The relaunch's sends carry no lease.** `_connect_runner` passes no lease
  check (the send checked it just before), and each engine send to a step
  reads its binding, run row and session first. A stop of a just-launched
  runner whose session closed is best effort: an unacknowledged one leaves an
  idle runner on a closed session, which nothing can prompt.
- **Clocks live in memory.** A restart or a new leader term starts every
  liveness clock afresh, so a runner that is still reconnecting gets a full
  grace. A runner that drops and returns between two passes is not seen, and
  flaps inside one outage are one outage
  (`test_a_flapping_runner_is_lost_only_when_one_outage_outlasts_its_grace`).
- **Linux steps run their CLI outside the runner's group.** bwrap
  (`--new-session`, `omnigent/inner/bwrap_sandbox.py`) puts the in-sandbox
  launcher and the `claude` CLI in a session of their own. They end through
  bwrap's die-with-parent once the group's `bwrap` is killed, just after the
  group sweep rather than with it; the reset's compare-and-swap is the backstop.
- **The agent is checked at create.** After that the mutation guard keeps a
  `coral__` agent as the engine wrote it: edits are refused, and a delete needs
  `force=true`. No drift pause follows (bundle drift is SES-09's). A live step
  on the deleted agent can no longer hand off, and its other tool calls run
  with only `/mcp` failing closed (see Run protection, Residuals). Each of its
  turns then ends without a handoff, and after three nudges the run pauses
  `rejected_calls`. Later steps materialize the bundle again.
- **Same-user steps.** A step's shell runs as the run owner on the owner's
  host. A shell the claude-sdk sandbox does not confine can act as its
  siblings and as the owner: it can drive a sibling's turn, handoff included,
  through that sibling's harness socket, and it can read other processes'
  environments and command lines. On the zygote path a runner's or harness's
  environment, as another process reads it, is the host daemon's whole
  environment; on the direct-spawn fallback it holds the runner's tunnel
  binding token and the host's initial bearer. A binding token proves the
  runner on `/mcp` and, on a server whose authentication can mint tokens
  (accounts or OIDC), mints an owner JWT (`POST /v1/runners/{runner_id}/token`),
  so the reader can call the server as the run owner on any route. Handoff and
  gate integrity therefore hold against other users and on the server's own
  path, not against such a step, and an owner-authenticated gate answer,
  resume or cancel does not prove a person took it. ADR-05's probe 15 measured
  what the macOS sandbox and the `coral-e2e` lane's Linux sandbox let a step
  reach on single-user servers, with an owner for each exposure
  ([`../decisions/ADR-05-topology.md`](../decisions/ADR-05-topology.md),
  "Addendum: CRL-137 probe verdicts"). On both platforms a step reaches the
  server, so on a single-user server it still acts as the owner, a Linux step
  included (next item; CRL-159). The macOS sandbox keeps other processes'
  environments and command lines unreadable, measured on macOS 27.2.1 only
  (CRL-170). It also denies connecting to other sessions' harness sockets under
  the host's socket root and the per-user default, and to other terminals' tmux
  servers and the user's default tmux socket (`tmux-<uid>`, with `-L` labels
  and `TMUX_TMPDIR`), measured on macOS 27.2.1 only. A sandboxed step can still
  reach other programs' local sockets, a tmux server on a custom `-S` path
  among them (CRL-174). A step with network on can still connect to loopback
  TCP listeners. Omnigent's known ones each refuse a caller without its
  secret, the codex-native app-server WebSocket since S114 (measured on macOS
  26.3.1 only). The exception is one started by a Codex without `--ws-auth`,
  which runs with no token and logs a warning (noted on CRL-177). Other
  programs' loopback services (CRL-174) and UDP are not covered. From code,
  not measured: on Linux a step reaches other programs' abstract sockets
  (CRL-174). Processes outside the sandbox can still connect to a
  harness socket, which has no bearer on POSIX (CRL-173). A Coral step's
  sandboxed Claude CLI keeps its Claude Code state in a private directory for
  each launch. Its sandbox grants nothing of the user's `~/.claude` or
  `~/.claude.json`, so neither it nor anything it starts can read or write
  them. That was measured on macOS 27.2.1 and is checked on Linux by a bwrap
  test in CI. The CLI still receives the `env` block of the user's
  `~/.claude/settings.json` (CRL-167). A step whose sandbox cannot wrap its
  CLI does not start, so Coral steps need a system `claude` CLI: the SDK's
  bundled one cannot be wrapped in the sandbox. Coral CLIs that run outside
  the sandbox get a private config directory but are not confined (CRL-180):
  the orchestrator and anchor on every platform, whose specs have no
  `os_env`, and any CLI under the operator's `OMNIGENT_CLAUDE_SDK_NO_SANDBOX`.
  Other Omnigent agents whose claude-sdk CLI runs in a bwrap or seatbelt
  sandbox also get a private config directory for each launch. When the agent
  loads user settings, it is seeded with a copy of the user's MCP server
  entries, user ID and legacy `env`, and of the trust and MCP on/off keys of
  each project that sets one; with `skills: none` it starts empty. The
  sandbox grants nothing of the user's `~/.claude` or `~/.claude.json` unless
  the agent's own working directory or path grants cover the home from above
  (CRL-184).
  That was measured on macOS 27.2.1, and a bwrap test checks it on Linux in
  CI. Code in that sandbox can read everything copied, MCP server secrets
  included. A stored subscription login does not reach these agents, nor on
  Linux do the MCP OAuth sign-ins the CLI stored. So they need an API key, a
  gateway or `CLAUDE_CODE_OAUTH_TOKEN`, which the host passes to every runner
  and which code in the sandbox may be able to read (CRL-167). Agents whose
  CLI runs outside a sandbox use the user's `~/.claude`, including one whose
  configured sandbox cannot be applied, which only the runner log reports
  (CRL-183). On Windows, whose sandbox confines no files, the CLI uses the
  user's `~/.claude`. A step in its
  worktree, or a sandboxed agent in its working directory, can create Claude
  Code project settings, which the user's own Claude Code loads if the user
  opens and trusts that directory (CRL-181). The full residual lists and
  their owners are in
  [`../decisions/ADR-05-topology.md`](../decisions/ADR-05-topology.md),
  "Addendum: CRL-166 harness sockets on macOS", "Addendum: CRL-176 Claude
  config isolation" and "Addendum: CRL-178 Claude config isolation for every
  sandboxed agent". Whether to run Coral steps on untrusted content on macOS
  while CRL-171 is open, and on either platform while CRL-174 and CRL-181 are
  open, is an open owner decision, recorded in the first.
- **Servers that require no identity.** With authentication off, or on a
  single-user header server, every request without credentials is the local
  user. Any process of that user that can reach the server (a step shell the
  sandbox lets reach loopback or the server URL, or the `omnigent` CLI) can
  read a gate's prompt and answer it as the owner, and with a single-user
  server bound to a non-loopback address so can any network peer. Nothing on
  the server can tell such a process from the person, so no gate is labelled
  Enforced there ([`gates-and-inbox.md`](gates-and-inbox.md)).

## Deferred work and owners

The engine bridge settled the rows it owned: stored replies, the pinned graph
and the port's rules; orchestrator bindings; prompting stopped steps; leasing
nudges; early submits (still refused, and retried by the step); paused
handoffs (still refused, and re-prompted on resume); and one lifespan per
process (see "The engine bridge" and
[`engine-tools.md`](engine-tools.md)).

The runs API settled its rows ([`runs-api.md`](runs-api.md),
[`run-stream.md`](run-stream.md)): routes that start, pause, resume and cancel
runs, answer their gates and stream them, each checking the owner first and
taking the owner, credentials, workflow and run target from the server; a
read that never writes and shows an unloadable run's `engine.load_failed`
cause whatever its row's pause; a cancel on the run row alone for a run the
bridge cannot load; Resume, and Cancel only for a run no resume can clear,
through one `allowed_actions` rule; and Resume and Cancel on the Inbox's pause
card. Activation rows are not projected: the engine state and the run's view
carry them.

The run view settled its rows ([`runs-api.md`](runs-api.md), "Outcome" and "In
the web app"; [`run-stream.md`](run-stream.md), "The web client";
[`gates-and-inbox.md`](gates-and-inbox.md)): a live view of each run with its
pause causes, the steps a person typed into or whose session changed, and its
open decisions; each step's transcript (no composer); the runs history; Start Run
on `POST /runs`; a finished run's outcome, its `diff_stat` read through the
owner's host and a checkout command a real-git test runs; marking a run's
run-end alert read when it is opened, through a low-priority bulk ack; and a
start that reads an adopted worktree's head, so a crash between the worktree
and the run row no longer loses `base_commit`. What it leaves:

- **No server `stalls[]`.** The view shows pause causes, slots with
  `pending_input` or `drift`, and open decisions; a stuck decision's watchdog
  alert reaches the Inbox. A step that is merely slow shows as running.
- **A budget pause offers Cancel only** in the web, as `allowed_actions` says:
  resuming with a higher activation cap is `:resume {"cap"}` on the API, and
  no web control sends it.
- **Bases lost before the head read existed** stay `null`, and those runs'
  outcomes answer `base_unknown`; there is no fallback. A base read at a retry
  is whatever the run branch held then ([`runs-api.md`](runs-api.md),
  "Residuals").

The restart ladder (SES-06) settled its rows: a retry fences, salvages and
resets before the next generation starts, with the reset a compare-and-swap on
the salvage ("Restarts and runner loss"); a lost runner is relaunched in its
session through one path that checks the host token (ADR-05 probe (f),
[`../decisions/ADR-05-topology.md`](../decisions/ADR-05-topology.md)); a
retried slot's new session is bound with the slot's current
`session_generation` ([`engine-tools.md`](engine-tools.md), rule (a)); a
retry clears every cause of the retried step, and a resume never clears
`agent.failed` ("What a resume clears"); the runs API's `:retry`
([`runs-api.md`](runs-api.md)). A real claude-sdk step's runner-only traffic
passes the event guard end to end: no `sending it a '…' event` refusal in the
server log of the review loop, the SIGKILL proofs or a relaunch
(`tests/e2e/coral/test_skeleton.py`, `tests/e2e/coral/test_runner_loss.py`).
With `core.untrackedCache` preset, no Tier B run paused `drift` on the lane's
or a local Mac's hosts; without it, a runner's first start can look like a
drift (CRL-161).

| Work | Owner |
|---|---|
| Resuming a budget pause with a raised cap from the web, and the run view's other cuts ([`runs-api.md`](runs-api.md), "Deferred work and owners") | no live ticket |
| Run requests over 512 characters: a start refuses them today, and briefs carry only `request_preview` | CRL-152 |
| A pause made on the run row alone has no durable marker: a resync repair between the engine's own pause and its plan probe can take over the row's reason, and the probe then lifts the row | CRL-153 |
| Tier B against the real API: the 529, 429 and 401 texts the classifier reads, a credentialed scheduled lane, and the opt-in Tier B samples in `coral-e2e` | CRL-156 |
| A runner's first start in a repo probes git's untracked cache for about 6 s; a turn that ends inside it looks like a drift (`pending_input`). The E2E presets `core.untrackedCache=true` | CRL-161 |
| Omnigent's own launch paths reach a step's runner without Coral's checks ("One relaunch path", Residuals) | CRL-162 |
| A relaunch or a fence that meets another stop of the same runner in progress ("A stop in progress reads as stopped", Residuals) | CRL-163 |
| Probe 15's exposures: secrets in exec-time environments and argv, the model API key among them (CRL-167); the allow-listed runner token on Coral-bound sessions (CRL-168) | CRL-167, CRL-168 |
| Probe 15 on servers that require identity (owner-JWT minting after an environment read, the CLI's stored credentials), and labelling a gate Enforced only when that passes and steps hold no owner credential; never on single-user or auth-off servers. No gate is labelled Enforced today | CRL-159 (RUL-02) |
| A force-deleted `coral__` agent leaves the live steps that run it unable to hand off, with only `/mcp` failing closed, until the nudge cap pauses the run: consult the required-policy provider on the no-agent branch keyed on the binding, or stop the run's sessions on a forced delete | CRL-154 |
| Showing the salvage ref in the web, and the retention and cleanup of `refs/coral/salvage/*` ([`workspace-ops.md`](workspace-ops.md), "Restart ladder") | CRL-158 |
| Separate worktrees per agent, and parallel writers (ADR-05 probe (a), separate-worktrees half) | CRL-140 |
| Host channel `fingerprint(L2)`, `merge`, `check`, and the backend swap (WSP-02/WSP-07); the macOS move-aside after a host crash and `git worktree prune` (see "Also known") | CRL-141 |
| Native-harness steps (HRN-03), after probe 15 runs on native steps | CRL-138 |
| `external_session_status` outcome pass-through (HRN-05) | CRL-146 |
| User take-over of a step (SES-07), with the handoff's `refresh_note`, and attributing a turn a person typed after an engine turn ended | CRL-143 |
| Unattended-permission preflight (HRN-02) | follow-up: call the CRL-132 preflight from the facade; no live ticket |
| Full drift: policy, label and bundle drift, anchor sharing (SES-09) | no live ticket |
| Engine-tool items not built: counting an orchestrator's rejections, `items` | roadmap ENG-06, ENG-08; no ticket named yet |
| Evidence for native-harness steps' commands, and `per_step` scope ([`evidence.md`](evidence.md)) | with HRN-03 (CRL-138) |
