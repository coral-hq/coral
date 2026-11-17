# Contract K4 (subset) and K18: Coral session facade, dispatch and status edges

- **Status:** Draft v1, dark. `coral_lifespan` registers the seven executors
  and the status-edge observers below. Nothing enqueues their effect types yet:
  the engine-to-queue bridge (ENG-04/DUR-04) will do that. This page is the
  bridge's input. The bridge has no live ticket: ENG-04/DUR-04/SES-08 were
  labelled on Done tickets CRL-126/CRL-127 but not built; needs a new ticket.
- **Code:** protocols and value types in `coral/omni/protocols.py`; the
  facade in `coral/omni/server/sessions.py`; dispatch in
  `coral/omni/server/dispatch.py`; the status-edge observer in
  `coral/omni/server/status_edges.py`; close and cancel in
  `coral/slots/close.py`; executors in `coral/slots/executors.py` and
  `coral/workspace/executors.py`; shared executor steps in
  `coral/queue/run_effects.py`; drift in `coral/recovery/drift.py`; wiring in
  `coral/omni/server/plugin.py`.
- **Related:** [`workspace-ops.md`](workspace-ops.md) (K13: the git ops and
  their errors), [`persistence.md`](persistence.md) (the `coral_0002` tables),
  [`plugin.md`](plugin.md) (K17), [`../decisions/ADR-05-topology.md`](../decisions/ADR-05-topology.md)
  (session topology).

## Wiring

`coral_lifespan` wires the engine only on a usable operational database, when
the app has `state.session_event_dispatch` and the plugin services carry the
conversation, agent, artifact, host and project stores, the agent cache, the
host registry and the runner router. Otherwise it logs a warning naming the
missing input and wires nothing; the worker supervisor still starts, so once
engine effects are enqueued on such a server they fail permanently as
`executor.missing`.

1. It builds the three `coral_0002` stores, `OmnigentSessionFacade`,
   `OmnigentSessionDispatch` with a `DriftPreSendHook` (whose pauser stops a
   runner attached to the anchor, see Anchor runner),
   `OmnigentHostWorkspaceChannels`, `CoralStatusEdges` on the server's event
   loop, and one `ConfirmedStops` record.
2. It registers the seven executors (`cancel_sessions` with
   `runs_after_terminal`, see Finished runs), then the S1 observers: `"coral"`
   (`CoralStatusEdges.observe`) and `"coral.confirmed_stops"`
   (`ConfirmedStops.observe`).
3. It starts the supervisor.

On exit it stops the supervisor first: the drain task is cancelled, and an
item in flight keeps its lease and is reclaimed after it expires, so no item is
claimed while its executor is missing. Then it unregisters the observers and
executors in reverse order. A start that fails part-way unregisters what it
registered. Entering again after an exit registers again without a conflict.

One lifespan per process. A second lifespan entered while the first still runs
takes the registrations over at once: from then on the first one's watches and
stop record see no edges. Whichever exits first removes only its own
registrations, so an inner lifespan's exit leaves the outer one with no
executors or observers, and its drainer would fail claimed engine items as
`executor.missing`. The bridge's ticket must fix this before it enables runs.

The built objects are on `app.state` as `coral_session_facade`,
`coral_session_dispatch`, `coral_status_edges` and `coral_confirmed_stops`.

## Ids

All ids are `derived_id(kind, *parts)` (32 lowercase hex, `coral/model/ids.py`).

| Id | Derivation | Notes |
|---|---|---|
| Anchor session | `anchor_session_id(ws, run_id)` = `derived_id("coral-anchor", str(ws), run_id)` | Run-scoped: a re-keyed anchor effect adopts the run's one anchor. The binding's primary key holds one anchor per run. |
| Step session | `effect_session_id(ws, effect_key)` = `derived_id("coral-session", str(ws), effect_key)` | One per `create_session` effect. |
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

- **Effect key.** Every payload carries `effect_key`, at most 512 characters,
  without NUL, starting with `<run_id>:` of the claimed run. Anything else is
  `effect.invalid_payload` or `effect.identity_mismatch`.
- **Identity.** Executors act as the stored run's owner and account
  registration, and take host, repository, worktree and branch from the run
  spec. A payload `user_id` or `account_generation` that differs from the run
  row is `effect.identity_mismatch`.
- **Anchor first.** Enqueue the anchor's `create_session` before any step's.
  A step created before its anchor is `initialized` fails with retryable
  `session.anchor_missing`.
- **Slots.** The writer interlock reads `coral_agent_slots`: the bridge must
  record each slot's current `session_id` and `session_generation` when a
  create completes. Until a slot names it, a writer's `close_slot` fails with
  retryable `session.not_ready` rather than closing without its commit.
  Bindings keep the engine slot id; the drainer's fencing uses the payload's
  store `slot_id`.
- **Writer close.** A writer's `close_slot` must keep `closed_label` true;
  `false` is `effect.invalid_payload`.
- **Cancel.** `cancel_sessions` must carry `session_id`: an explicit `null`
  for a slot with no session yet. A payload without the key is
  `effect.invalid_payload`, never a silent success.
- **Reset after salvage (SES-06, CRL-137).** Enqueue `workspace.reset` only after
  `workspace.salvage` for the same session completed. The reset executor
  cannot see the salvage and checks nothing about it. A salvage whose
  `git_failed` would repeat fails permanently, so it is never retried.
- **One worker.** The torn-row repair assumes one drainer at a time (the
  `coral.worker.primary` lease).
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
- **Coral hosts.** The run owner's host must advertise `coral_runner:1`
  (Coral's tool provider, [`plugin.md`](plugin.md)); an older or Coral-less
  host, or one with `CORAL_DISABLE_HOST_ENTRY_POINTS` set, is
  `session.host_unsupported`.

## Executors

Every executor parses its payload, loads the run, runs inside the run's
workspace, account-authority and host-owner scopes, calls `ensure_lease()`
before each external side effect, and returns only values a repeat
reproduces. Each passes `run_executor_conformance`.

| `effect_type` | Payload (besides `effect_type`, `effect_key`) | Result |
|---|---|---|
| `create_session` | `role` (`anchor` or `step`). A step adds `agent_id` (1-64 of `A-Za-z0-9_-`), `engine_slot_id` (≤ 512 chars), `slot_role` (`step_agent`, `orchestrator`, `verifier`, `merge_resolver`), optional `title` (≤ 200), `node_id` (≤ 128), `generation` (1-32,767, default 1). | `{session_id, role, generation}` |
| `send_input` | `session_id`, `text` (≤ 1 MiB as sent, no NUL), `kind` (`brief`, `steer`, `nudge`) | `{session_id, stable_id}` |
| `close_slot` | `session_id`; optional `interrupt` and `closed_label` (default `true`), `message`, `attempt_id`, `diff_from`. `accepted_at_ms`, `node_id` and `item_path` are accepted and ignored. | `{pending_input, queued_input, post_accept_edits, commit, empty, diff_stat}`; the last three are `null` for a reader or when no commit is made |
| `cancel_sessions` | `session_id` (required; `null` for a slot with no session yet), optional `closed_label` (default `true`) | `{session_id}`; `null` succeeds without action |
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
`workspace.*` executors also run while a run is paused; whether WRITE effects
wait is for CRL-137 (SES-06) and the bridge's ticket to decide.

**Finished runs.** The drainer abandons a finished run's items as
`run.terminal`, except an effect type registered with `runs_after_terminal`:
only `cancel_sessions`, because `cancel_run` marks the run cancelled in the
transition that enqueues it. The slot-generation fence still applies.

## Error codes

Permanent unless marked retryable. Messages are trimmed to 2,000 characters
(invalid payloads to 500) and name fields, never payload values. Host error
text lands only in the run owner's work record.

| Code | Retryable | When |
|---|---|---|
| `effect.invalid_payload` | no | Payload not a JSON object; a field missing, ill-typed or over its bound; a lone surrogate in text. |
| `effect.identity_mismatch` | no | Payload identity differs from the run row; `effect_key` names another run; another send is recorded for this effect. |
| `effect.run_missing` | no | The run is not in the item's workspace. |
| `effect.result_too_large` | no | A bug: valid input never reaches it. |
| `executor.missing` | no | Drainer: a claimed item whose effect type has no registered executor (a server whose engine is not wired). |
| `executor.unhandled_exception` | yes | Drainer: the executor raised an unexpected exception (a bug or a store fault). Retried up to the attempt cap, then failed as `infra.transient`. |
| `run.paused` | yes | `create_session` or `send_input` for a paused run. |
| `drift.<cause>` | no | Drift found; the run was paused first (see Drift). |
| `session.anchor_missing` | yes | A step before its anchor is `initialized`. |
| `session.not_ready` | yes | A send or close before the step's row exists; a writer's close before a slot names its session. |
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
| `session.host_unsupported` | no | The owner's live host connection does not advertise `coral_runner:1`: update Coral on that host, or unset `CORAL_DISABLE_HOST_ENTRY_POINTS` there. Checked before any row, and again before the launch. |
| `session.owner_revoked` | no | The run owner's account was revoked or re-registered. |
| `session.invalid` | no | An ownerless run on a server with auth; a step run with no worktree on a host; a server with no project store or no host access; another refusal. |
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
  own row, again right before launch) and the dispatch pre-send hook (the
  run's anchor, then the target step). Only sessions whose row this run
  created count. Stop, interrupt, close and cancel never consult the hook.
- **What happens.** The run moves from STARTING or RUNNING to
  `paused(drift)` (`pause_reason` 12) with one `PAUSED` log entry, body
  `{"kind": "pause_run", "reason": "drift", "cause": <cause>, "session_id": <session>, "detail": <detail>}`.
  The entry's idempotency checksum is
  `sha256("coral-drift\0<run_id>\0<cause>\0<session_id>\0<run version>")`, so it
  is one entry per pause epoch. A paused or finished run is left as it is. A run
  resumed while the drift persists is paused again by the next engine action.
  The effect then fails as permanent `drift.<cause>`. `anchor_bound` is an
  additive K2 cause; after its pause Coral also stops the anchor's runner,
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

**Cancel:** a running turn is interrupted and given 30 s to settle; then the
session is closed (when `closed_label`) and stopped, confirmed. An open prompt
is not waited on.

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
it matches, and reaches the `TurnFactSink` hook. The hook is unset here, so
nothing is persisted; SES-08's turn-fact gathering fills it (no live ticket:
ENG-04/DUR-04/SES-08 were labelled on Done tickets CRL-126/CRL-127 but not
built; needs a new ticket).

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

## Requirements for the engine bridge

ENG-04/DUR-04 must settle these before it enqueues these effects:

1. **Hold waiting items.** K21 fails an item as `infra.transient` after 8
   attempts, about 1-3 minutes of backoff plus each try's own time. Hold
   `run.paused` items until a resume and `slot.close_blocked` items until the
   prompt is answered (likewise `session.not_ready`, `session.anchor_missing`,
   `session.host_offline` and `session.turn_state_unknown`) instead of
   spending their retries.
2. **No head-of-line blocking.** The supervisor drains one item at a time, and
   a close may wait 120 s for the turn end and 30 s to settle before its host
   ops. Drain with bounded concurrency (per-slot fencing exists), or re-enqueue
   a waiting close with a not-before time, so one close cannot stall every run.
3. **Map the reducer's payloads.** They are not the executors' (see
   Executors): `create_session` and `send_input` carry `{node_id, profile,
   goal}`; the reducer's `nudge` kind has no executor (`executor.missing`),
   while the executors send a nudge as `send_input` with `kind: "nudge"`;
   `cancel_sessions` has no `session_id`; the engine's `item_path` is a list.
   Own a written per-kind mapping with a test per kind.
4. **Record slot sessions** when a create completes, before any writer close
   (see Preconditions).
5. **One lifespan per process** (see Wiring).

Also known before runs are enabled:

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
  one never matches a response-keyed waiter; a slot-keyed consumer must not
  count it as another turn's outcome.
- **Auth-off tests.** Most facade tests run without an auth provider, which a
  production server always has (single-user mode acts as `"local"`), so the
  owner, grant and launch-permission paths are proven mostly with auth off.

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
- Every other bound session gets `__coral_run_guard` first, then
  `__coral_cost_backstop`, then its role guard:
  - **Orchestrator** (slot role `orchestrator`): `__coral_orchestrator_guard`
    allows only `coral_choose_arrow` (bare or `mcp__omnigent__`) and exactly
    `ToolSearch`.
  - **Other steps:** `__coral_step_roster` denies `sys_session_*`,
    `search_conversations`, `Agent`, `Task` and `*spawn_agent` tools.

Because the run guard and the backstop go first, on a stopped run or at the
cap they decide every tool they do not exempt, so the agent always reads a
stop text. A role guard's text (the roster's points the step at its handoff
report) shows only while the run is starting or running and the session is
under its cap. The verdicts are the same in any order, but this one also
pauses the run on an over-cap call that the role guard would deny. The role
guards are the ones each generated bundle carries
(`coral/omni/policies/guards.py`). The provider's copy is keyed on the binding
row, so it holds even when a session's agent lacks them.

**Run guard** (`coral/omni/policies/run_guard.py`). It decides from the run's
stored status, which also carries drift and budget pauses the engine never
saw, and from the session row's `omnigent.closed` label. Only the label
counts: the legacy `:closed:` title marker does not, so renaming a step never
makes it inert. While the run is starting or running and the session is open
it allows everything. Otherwise it denies every tool call except the exact
engine tools (`coral_submit_handoff`, `coral_choose_arrow`, bare or
`mcp__omnigent__`) and exactly `ToolSearch`, which loads them. An engine tool
call then gets the engine's own answer, for example `run.paused` with a stop
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

**Cost backstop** (`coral/omni/policies/cost_backstop.py`). It reads the
session's spend from its own row's `session_usage`: the larger of
`policy_cost_usd` and `total_cost_usd`, each counted only when it is a finite
number, so an enforcement figure a client posts (`external_session_usage`)
can never hide what the server recorded. That is the session's own row only,
never the run-wide usage other policies see, nor a child session's (steps
cannot start sessions). Unpriced usage (neither figure a finite number)
passes. At or over the cap it pauses the run and denies every tool call
except the exact engine tools and exactly `ToolSearch`; it never asks. The
deny says `[budget] This session has spent about $<spent> of its $<cap> cap
(an estimate), so Coral paused the run. Stop now and end your turn.` when this
call paused the run or found it paused for budget already, and otherwise (the
pause failed, or the run was paused for another reason or finished meanwhile)
`[budget] This session has reached its cost cap: it has spent about $<spent>
of its $<cap> cap (an estimate). Stop now and end your turn.` Amounts show
cents, or two significant digits below a cent. An orchestrator may call only
the exempt tools, so over its cap every one of its tool calls pauses the run,
the exempt ones included; those still pass, and the engine answers
`coral_choose_arrow` with `run.paused`. The anchor gets no backstop (it is
denied every tool already).

The pause goes through the run store (`pause_run_for_session_cap`,
`coral/recovery/pause.py`, the same store-only pause as drift): a starting or
running run moves to `paused(budget)` (`pause_reason` 2) with one `PAUSED` log
entry, body
`{"kind": "pause_run", "reason": "budget", "cause": "session_cap", "session_id": <session>, "spent_usd": <spent>, "cap_usd": <cap>}`,
whose idempotency checksum is
`sha256("coral-budget\0<run_id>\0session_cap\0<session_id>\0<run version>")`,
one entry per pause epoch. `budget` is also the engine's own activation-cap
pause reason; only the entry's `cause: session_cap` tells this pause apart (see
"Deferred work and owners"). A paused or finished run is left as it is. The
pause's commit clears the status cache, so the next call meets the run guard.
A pause that fails is logged; the call is still denied and the next one tries
again.

The cap is per session: server config `coral_session_cost_cap_usd`,
overridden by the environment variable `CORAL_SESSION_COST_CAP_USD`, default
25.0 US dollars (OQ-15, not yet signed off). A value that is not a finite
number above 0 and at most 1,000,000 stops `coral_lifespan` with a
`ValueError` before anything starts. Resuming the run is the bridge's job.
Until a per-run cap exists (WEB-03/API-02), raising the cap means changing the
server setting and restarting the server, and a resumed run whose session is
still at or over the cap pauses again on that session's next tool call.

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
| Events to the anchor or a closed step (`omnigent.closed` = `true`) | every client event type but the allowed ones, items such as `reasoning` or `function_call`, an approval (also through `POST /v1/sessions/{id}/elicitations/{eid}/resolve`) and a peer `session_message` included, and any type Omnigent adds for clients later | `interrupt`, `stop_session` |
| Events to an open step or the orchestrator | `clear` (claude-sdk would move the step into an unbound session), a peer agent's `session_message` | `message`, `slash_command`, `compact`, `retry_session`, items, approvals, `interrupt`, `stop_session` |
| Runner-only event types (`external_*`, `subagent.status`), on any bound session, including the batched `external_conversation_item` path | from a client: Omnigent lets an owner post them, and some write the session (effort, launch args, mode labels, child rows) | from the session's own runner: a tunnel token bound to the row's `runner_id` |
| Runner launch; a grant (public included); a child session (JSON, multipart or orchestrated create) or a sibling (`sibling_source_id`, checked against the family's root); `PUT /v1/sessions/{id}/agent`; a session MCP server create, update, delete or registry select; a scheduled task created or patched to continue it | always | none |
| Revoke, delete, fork (a side chat too, see Residuals), read state, comments, session policies | never | always |

| Change to an agent named `coral__*` (any case) | Refused (409) | Allowed |
|---|---|---|
| `PATCH /v1/agents/{id}` | always: "Agent '<name>' is managed by Coral's workflow engine and can't be edited." | none |
| `DELETE /v1/agents/{id}` | without `force`: "Agent '<name>' is managed by Coral's workflow engine; delete with force=true to remove it anyway (runs that use it pause)." | `force=true`; SES-09 drift then pauses runs that use it |
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
  closed (S52).
- An approval granted for an unrelated ASK (a user's or admin's policy) is not
  re-checked by the S21 hook's ASK gate or the relay path, so a run paused
  during that human wait does not stop the one approved call. `/mcp`
  re-evaluates on its retry.
- A user's or admin's TOOL_CALL ASK policy that matches a `coral_*` tool parks
  an unattended step on its approval, like the ASK limitation for engine
  messages below.
- One lifespan per process: a later lifespan's registration replaces the
  provider and the budget pauser (see Wiring).
- A session on a Coral bundle that no run binds (a user chatting with a
  `coral__` agent, a fork of a step) pays one binding read per policy build,
  because misses are never cached, and fails closed: while that read fails,
  its tool calls are denied with the `[run.state_unavailable]` text.
- A store error, or a status outage longer than 30 s, tells the affected
  sessions to stop and end their turns. Until the engine bridge exists,
  nothing prompts a step again when the store recovers.
- While this process cannot read the store, a pause committed by another
  process can go unseen for up to 30 s (the stale fallback), not 2 s.
- Spend lands when a turn ends (claude-sdk reports usage per turn), and a step
  usually works in one long turn. So a step is not stopped inside the turn in
  which it overspends; the backstop fires on the first tool call of a later
  turn, and the overshoot can be the whole step. The deny says "estimate".
- Usage the server cannot price (a model its pricing catalog lacks; claude-sdk
  reports no cost of its own) is never capped, so on such a deployment the
  backstop never fires.
- An orchestrator over its cap pauses the run at its next tool call, but its
  spend lands per turn and each decision request the engine sends starts a
  turn that spends before any tool call. Bounding that is the bridge's job
  (see "Deferred work and owners").
- A child session's spend is on its own row, not its parent's, and an unbound
  child is never backstopped. Steps cannot reach this today: the roster denies
  starting sessions and the mutation guard refuses child creates on bound
  sessions.
- The budget pause, like the drift pause, changes only the run row; the
  engine's own state stays `running` until the bridge reconciles it.
- The pause runs inside policy evaluation, including a read-only `POST
  /policies/evaluate` by a viewer: Omnigent's read-only evaluation skips label
  and state writes, not a policy's own side effects. It needs a viewer (bound
  sessions are created private and the mutation guard refuses grants, so only
  a grant made some other way) and a session at or over its cap that is not
  closed; closed steps meet the run guard first. A step that went over its cap
  in its last turn and handed off makes no further tool call, so such a viewer
  could pause a run its own calls never would. A fix needs Omnigent to pass
  `read_only` to policies.
- The mutation guard leaves the workspace routes on a step's host unguarded:
  `/resources/terminals`, `/resources/files`, `/resources/environments` and
  terminal attach.
- Session policies on a run session stay editable, so a user's ASK or DENY on
  the anchor reaches every step.
- Admins bypass Omnigent's access checks, not the mutation guard.
- A split-database row read torn, without its labels, is not protected until
  the facade repairs it: the `coral.run_id` label is the only pre-filter.
- A scheduled task pointed at a session before it was bound is not checked
  again when it fires or is run now. None can exist while the engine is dark.
- One lifespan per process holds for the mutation guard too: a later
  lifespan's registration replaces it.
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
- **One lifespan per process.** See "Wiring": a second lifespan blinds the
  first on entry, and an inner exit leaves the outer unregistered. The bridge's
  ticket must fix this before it enables runs.
- **`coral_runner:1` is self-reported.** The host token check is a
  compatibility gate, not an authorization boundary: steps still need a live
  connection to a host the run owner owns, with a matching account
  registration, that is not a managed sandbox.
- **The agent is checked at create.** After that the mutation guard keeps a
  `coral__` agent as the engine wrote it: edits are refused, and a delete needs
  `force=true`, after which SES-09 drift pauses the runs that use it.

## Deferred work and owners

| Work | Owner |
|---|---|
| Engine-to-queue bridge and EffectCompleted feedback (ENG-04/DUR-04); turn-fact gathering and the `TurnFactSink` (SES-08) | no live ticket: ENG-04/DUR-04/SES-08 were labelled on Done tickets CRL-126/CRL-127 but not built; needs a new ticket |
| Restart ladder (SES-06): reset only after a completed salvage; relaunch (ADR-05 probe (f)) | CRL-137 |
| Reconcile store-only budget pauses (RUL-01): a `budget` run whose `PAUSED` entry has `cause: session_cap` is a session-spend pause, not the engine's activation-cap pause, so the activation-cap resume rule (raise `max_activations`) must not apply to it; give it its own engine cause and resume rule | the engine bridge ticket (ENG-04/DUR-04; no live ticket yet) |
| Bound an orchestrator's spend between tool calls (RUL-01), for example by checking its session cap before sending it a decision request | the engine bridge ticket (ENG-04/DUR-04; no live ticket yet) |
| Host channel `fingerprint(L2)`, `merge`, `check`, and the backend swap (WSP-02/WSP-07) | CRL-141 |
| Native-harness steps (HRN-03) | CRL-138 |
| `external_session_status` outcome pass-through (HRN-05) | CRL-146 |
| User take-over of a step (SES-07) | CRL-143 |
| L1 capture for evidence (EVD-02) | CRL-133 |
| Unattended-permission preflight (HRN-02) | follow-up: call the CRL-132 preflight from the facade; no live ticket |
| Full drift: policy, label and bundle drift, anchor sharing (SES-09) | no live ticket |
| ADR-05 probe 15 (a sibling's bridge-dir bearer) | unassigned (security); decide before ENG-04 enables runs |
