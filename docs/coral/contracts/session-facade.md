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
   `OmnigentSessionDispatch` with a `DriftPreSendHook`,
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
| `session.harness_not_configured`, `session.workspace_missing` | no | The host refused the step's launch, or dispatch's runner wake before a send, for these reasons. |
| `session.host_not_permitted` | no | The host is unknown (an id no host can have included), another user's, another registration's or a managed sandbox. |
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
  additive K2 cause.

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

## Residuals and limitations

- **ASK input policies** deny an engine message at once (permanent
  `dispatch.policy_denied`): the engine context has no client connection to
  wait on. Owner: CRL-131 (RUL-01).
- **Relaunch of a closed session.** Omnigent's closed check covers user
  `message` events only, so a user's `retry_session` or slash command (for
  example `/compact`) on a closed session can still relaunch it. The close's
  commit gate catches one that starts a turn before the commit. Owner: CRL-131
  (RUL-01).
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
- **Anchor runner.** If an owner attaches a runner to the anchor, the
  `anchor_bound` drift pause refuses further engine work but does not stop that
  runner. The anchor seed (`coral/profiles/seeds/anchor.yaml`, from CRL-132's
  PRF-01) no longer sets `permission_mode: bypassPermissions`, so the
  harness's default applies and its tool calls still ask for approval. Still
  open, owner CRL-131 (RUL-01, the run guard): a deny-all tool policy for the
  anchor, and stopping or unbinding an anchor runner on detection.
- **Anchor sharing.** The anchor is private at create, but a later read-only or
  public grant exposes every step's workspace files (ADR-05 rule 6). Detecting
  it belongs to the full SES-09 drift (no live ticket).
- **One lifespan per process.** See "Wiring": a second lifespan blinds the
  first on entry, and an inner exit leaves the outer unregistered. The bridge's
  ticket must fix this before it enables runs.
- **No `coral_runner` token check.** Steps need a live connection to a host the
  run owner owns, with a matching account registration, that is not a managed
  sandbox. The token check is TLS-01 (CRL-131).

## Deferred work and owners

| Work | Owner |
|---|---|
| Engine-to-queue bridge and EffectCompleted feedback (ENG-04/DUR-04); turn-fact gathering and the `TurnFactSink` (SES-08) | no live ticket: ENG-04/DUR-04/SES-08 were labelled on Done tickets CRL-126/CRL-127 but not built; needs a new ticket |
| Restart ladder (SES-06): reset only after a completed salvage; relaunch (ADR-05 probe (f)) | CRL-137 |
| Anchor deny-all tool policy; stop or unbind an anchor runner on detection (RUL-01) | CRL-131 |
| ASK input policies for engine sends; closed-session relaunch by `retry_session` or slash command (RUL-01) | CRL-131 |
| `coral_runner` token check (TLS-01) | CRL-131 |
| Host channel `fingerprint(L2)`, `merge`, `check`, and the backend swap (WSP-02/WSP-07) | CRL-141 |
| Native-harness steps (HRN-03) | CRL-138 |
| `external_session_status` outcome pass-through (HRN-05) | CRL-146 |
| User take-over of a step (SES-07) | CRL-143 |
| L1 capture for evidence (EVD-02) | CRL-133 |
| Unattended-permission preflight (HRN-02) | follow-up: call the CRL-132 preflight from the facade; no live ticket |
| Full drift: policy, label and bundle drift, anchor sharing (SES-09) | no live ticket |
| ADR-05 probe 15 (a sibling's bridge-dir bearer) | unassigned (security); decide before ENG-04 enables runs |
