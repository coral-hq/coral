# Contract K7 (subset): the runs API

- **Status:** Draft v1, live. A run's owner can start, list, read, pause, resume and
  cancel the run, answer its gates and follow it as a stream. Anyone else gets one
  fixed 404 and learns nothing about the run.
- **Code:** routes in `coral/api/runs.py`; the service, its pools and its caps in
  `coral/api/run_service.py`; models in `coral/api/run_models.py`; the error shape in
  `coral/api/errors.py`; allowed actions in `coral/runview/actions.py`; spend in
  `coral/api/spend.py` and `coral/omni/server/usage.py`; the store-only cancel in
  `coral/recovery/cancel.py`; the stream in `coral/api/stream.py`; the router table and
  wiring in `coral/omni/server/plugin.py`; the spec in `coral/api/openapi.json`, written
  by `coral/omni/server/openapi.py`; the web client in `web/src/workflows/api/runsApi.ts`.
- **Related:** [`run-stream.md`](run-stream.md) (the stream, K8),
  [`gates-and-inbox.md`](gates-and-inbox.md) (gate answers, the Inbox's Resume and
  Cancel), [`session-facade.md`](session-facade.md) (the engine bridge),
  [`plugin.md`](plugin.md) (wiring).

## Routes

Every route is under `/v1/coral`, tagged `coral`, and has an `operationId`.

| Method and path | `operationId` | Success |
|---|---|---|
| `POST /runs` | `coral_start_run` | 201 `RunSummary` for a new run, 200 for a repeat; `Location: /v1/coral/runs/{id}` |
| `GET /runs?status=&workflow_id=&after=&limit=` | `coral_list_runs` | 200 `RunPage` |
| `GET /runs/{run_id}` | `coral_get_run` | 200 `RunDetail` |
| `GET /runs/{run_id}/graph` | `coral_get_run_graph` | 200 `CompiledGraph`, or 304 |
| `GET /runs/{run_id}/log?after_seq=0&limit=50` | `coral_get_run_log` | 200 `LogPage` |
| `GET /runs/{run_id}/stream?after_seq=` | `coral_stream_run` | 200 `text/event-stream` ([`run-stream.md`](run-stream.md)) |
| `POST /runs/{run_id}:pause` | `coral_pause_run` | 200 `RunSummary` |
| `POST /runs/{run_id}:resume` | `coral_resume_run` | 200 `RunSummary` |
| `POST /runs/{run_id}:cancel` | `coral_cancel_run` | 200 `RunSummary` |
| `POST /runs/{run_id}/gates/{node_id}:answer` | `coral_answer_gate` | 200 `GateAnswerOut` |
| `POST /runs/{run_id}/activations/{activation_id}:retry` | `coral_retry_activation` | 501 |
| `GET /runs/{run_id}/outcome` | `coral_get_run_outcome` | 501 |
| `POST /runs:preflight` | `coral_preflight_run` | 501 |

- Every POST takes a JSON body. Pause, cancel, retry and preflight take `{}`; resume takes
  `{}` or `{"cap": 1..1000}`.
- Run reads and writes send `Cache-Control: private, no-store`. The graph sends
  `Cache-Control: private, no-cache` and `ETag: "<version_id>"`.
- The spec is `coral/api/openapi.json` (OpenAPI 3.1, no `servers` block). Regenerate it and
  the web's types with `just coral openapi`; `just coral openapi-check` fails when either
  is stale. The TS types come from Coral's own emitter (`coral/omni/server/openapi_ts.py`)
  into `web/src/workflows/api/generated/coralApi.ts`. Omnigent's root `openapi.json` is
  left alone.

## Callers, workspaces and the one 404

- The caller comes from `request_viewer` (`coral/omni/server/access.py`), in the request's
  task, before any store read. A configured provider that finds no user is 401
  `unauthenticated` "Authentication required". A caller the account context does not
  prove, or no identity where one is required, is 403 `not_permitted` "Not permitted".
- Runs and workflows use the request's workspace (`current_workspace_id`).
- Request validation (query, path pattern and body) runs next and answers 422 whoever owns
  the run: it depends only on the request. So the fixed 404 below is for well-formed
  requests.
- Every route that names a run then calls `RunsApi.owned_run`. It checks that the id is 32
  lowercase hex, that the row exists, and that `is_owner` holds: the same normalized user,
  and a request that proves the run's account generation when it recorded one. No run
  work comes before it: no fold, spend read, log read, graph, 304, gate admission or stream
  slot.
- These all answer the same bytes: an unknown run, a malformed id, another user's run, a
  gate visit the run does not have, and an answer the gate refuses as `not_permitted`.

  ```json
  {"error":{"code":"not_found","message":"Run not found.","details":null}}
  ```

- Without `app.state.coral_runs_api` (before the lifespan publishes it, or with no
  operational database) every runs route answers that 404 after the caller check and
  request validation. After the lifespan exits, its pools are closed and the routes answer
  503 `server_busy`. `:preflight` names no run, so it answers 501.
- `:retry` checks `activation_id` as 32 lowercase hex with the rest of the request (422).
  It never echoes or logs the id.

## Errors

Every refusal from a Coral route has one shape (`CoralRoute`, `coral/api/errors.py`):

```json
{"error": {"code": "illegal_transition", "message": "The run is completed.",
           "details": {"status": "completed", "pause_reason": null}}}
```

| Code | Status | When |
|---|---|---|
| `unauthenticated` | 401 | No user found |
| `not_permitted` | 403 | The caller is refused; the host refused the owner at start; an accounts-mode start without a proven generation |
| `not_found` | 404 | The run 404 above; "Workflow not found."; the Inbox's texts; a run whose pinned graph cannot be read ("The run's workflow graph cannot be read.", `details.load_error: "engine.load_failed"`) |
| `validation_failed` | 422 | Request validation (`details.errors`: `loc`, `msg`, `type`, never the input); a POST that is not JSON ("The request body must be JSON."); "Invalid run cursor."; "Too many status filters."; a resume `cap` out of bounds; a gate's `invalid_answer` (`details.reason`) |
| `not_runnable` | 422 | A start of a workflow that cannot run (`details.rule`) |
| `not_a_git_repo` | 400 | The start's repository is not a git repository |
| `start_key_conflict` | 409 | The start key was used with another request, or by an older registration of the same user id; a key whose run cannot be read back (`details.reason: "engine.load_failed"`) |
| `workflow_key_taken` | 409 | A save of a key another owner holds |
| `illegal_transition` | 409 | An action the run cannot take (`details.status`, `pause_reason`, and `reason` when known); a gate `already_answered`, `no_longer_waiting` or `run_paused` (`details.reason`); an Inbox ack of an open gate alert |
| `stale_visit` | 409 | A gate visit asked again since |
| `worktree_failed` | 409 | The host could not create the worktree, and it is not locked |
| `payload_too_large` | 413 | A workflow save that is too large |
| `stream_limit` | 429 | Stream caps or the connect rate (`Retry-After: 5`) |
| `not_implemented` | 501 | `:retry`, `/outcome`, `:preflight` |
| `host_offline` | 503 | No host connector, or the host is offline |
| `server_busy` | 503 | Caps, a 30 s timeout, `RunContended`, a closed pool, a gate's `run_busy`; `Retry-After: 1`, `2` for a worktree another start holds locked, `5` for a stream while the server shuts down |

- The JSON check runs first, before the caller. An unauthenticated POST that is not JSON is
  422.
- Any other `HTTPException` with a 4xx status is `validation_failed`. Other errors go to the
  server's own 500 handler. A write that fails this way logs only `describe_exception` and
  raises a new error without its cause, so no statement parameters reach a log.
- **A path or method no Coral route matches is outside `CoralRoute`.** In the Omnigent
  server it gets Omnigent's own 404, `{"error":{"code":"not_found","message":"Not found"}}`,
  without `details`; a wrong method on a Coral path gets this 404 too. An app holding only
  Coral's routers answers Starlette's `{"detail": "Not Found"}` or 405. Clients branch on
  the status; the web client (`apiErrorFromResponse`) reads both shapes.

## Workflows

- `POST /workflows:validate`, `POST /workflows`, `GET /workflows` and
  `GET /workflows/{id}` need a caller. The 2xx bodies are unchanged.
- A save stamps the caller as owner: `normalize_owner(user_id)`, without an account
  generation. A key another owner holds is 409 `workflow_key_taken`, "A workflow with this
  key already exists.", and that row is left unchanged. A legacy row with no owner is
  claimed by its first saver.
- Get and list show the caller's rows and legacy unowned rows in the request's workspace.
  Any other id is 404 "Workflow not found.".
- A save whose YAML does not load is 422 with `details.load_error`: at most 20 issues, each
  cut to 500 characters, with no server paths.
- A start needs a definition the caller owns exactly. On a single-user server the local
  owner is `null`, so its legacy rows start. Elsewhere an unowned row is readable but does
  not start until someone saves it.

## Start

`POST /runs` with `StartRunRequest`:

| Field | Rule |
|---|---|
| `workflow_id` | 32 lowercase hex |
| `start_key` | `^[A-Za-z0-9_-]{1,64}$` |
| `host_id` | 1-64 characters, no control or bidi characters |
| `repo_path` | 1-2048 characters, no control characters |
| `base_ref` | `null`, or 1-255 characters, no control or bidi characters, not starting with `-` |
| `title` | `null`, or 1-256 characters, no control or bidi characters |
| `request` | at most 512 characters, default `""`; newlines and tabs allowed, other controls and bidi characters not |
| `max_activations` | strict integer 1-1000, default 100 |

Unknown fields are refused. Text fields refuse NUL and lone surrogates. `cap` and
`max_activations` are strict: `true`, `"7"` and `2.0` are 422.

1. In accounts mode a request that does not prove its account generation is 403
   "Starting a run needs a request that proves its account."
2. The run id is `derived_id("coral-run", user_id or "", start_key)`. A start takes a start
   slot (8 in all, 2 per user; 503 past either) and then the run id's turn, so two starts
   of one key run one after the other.
3. A run with that id already exists: a **replay**, below.
4. Otherwise the definition must be the caller's own (404 "Workflow not found.") and
   runnable (422 `not_runnable`, `rule: workflow.invalid`). `check_startable` then refuses
   graph and shape problems (422 `not_runnable` with the bridge's rule) before any host
   frame.
5. The host is reached as the owner (`connect_run_worktree_host`), then
   `create_or_adopt_run_worktree` makes or adopts the run's worktree. A worktree git lists
   as locked re-reads the run: a replay if it exists now, else 503 `server_busy`,
   `Retry-After: 2`, with the host's "retry later or repair it" text. Other worktree errors
   map by code: `host_offline` 503, `not_permitted` 403, `not_a_git_repo` 400,
   `worktree_failed` 409.
6. The owner, account generation, workflow text and run target come from the server. The
   title defaults to the workflow's name without control and bidi characters, cut to 256
   (or the workflow key if that leaves nothing). `start_engine_run` then commits the start:
   201. A start that lost a race on another replica is answered as a replay.

**Replay.** The same owner and request answer the run the key made: 200 with its summary.
The request is compared with the stored spec: `workflow_id`, `host_id`, `repo_path`,
`base_ref`, `request`, `max_activations`, and `title` only when the request gives one. Any
difference is 409 `start_key_conflict`, "This start key started a run with another
request." The definition is not read again, so an edit, rename or deletion since never
turns a retry into a refusal. A replay never pauses a run: a row still `starting` (a crash
between the row and the engine's start) commits the engine's start only when the run
loads. A run whose stored rows cannot be read is 409 with `details.reason:
"engine.load_failed"`, "This start key's run cannot be read back to compare the request;
it can only be cancelled." A client should not pick a new key for it.

## Reads

- **List.** The caller's runs, newest first (`created_at DESC, id DESC`). `status` may repeat,
  with at most 6 distinct values; `workflow_id` is 32 hex; `limit` is 1-50, default 25. The
  cursor is `<created_at>:<run_id>`, else 422. It always names a run the caller owns, and
  nothing is looked up by it. A page can be short and still carry a cursor; page until
  `next_cursor` is `null`. Spend comes from the cache only (below).
- **Detail.** `RunSummary` plus `version`, `head_seq`, `max_activations`,
  `request_preview`, `target`, `anchor_session_id`, `orchestrator_session_id`, `causes`,
  `load_error`, `view`, `gates` (open visits, with the gate's outcomes) and `slots`. It
  reads with `EngineBridge.read()`, which never writes. A run that cannot be loaded shows
  `load_error: "engine.load_failed"`, `view: null`, the cause
  `{"reason": "failure_path", "detail": "engine.load_failed", "subject": ""}` and only
  Cancel. `target`, `max_activations` and `request_preview` are `null` when its stored rows
  cannot be read. Spend waits up to 10 s.
- **Graph.** The workflow graph the run is pinned to. `If-None-Match` (a list, `W/` tags and
  `*`) gives 304 after the owner check.
- **Log.** Rows after `after_seq` (0 to 2^63-1) in seq order; `limit` 1-100, default 50.
  Each row is the stream's entry plus `body` and `body_truncated`. A body over 256 KiB is
  `null` with `body_truncated: true`. A page holds at most 1 MiB of bodies and patches;
  `next_after_seq` is set only when more rows are known to follow. A row whose stored text
  cannot be read, whose patch is not a patch, or that holds a code this server does not
  know is a placeholder: `kind: "log.unreadable"`, `body: null`, `patch: []`, and
  `actor_kind: null` when that code is the unknown one.

Entry kinds are `engine.<input kind>` for an engine row (for example `engine.start_run`,
`engine.pause_run`, `engine.answer_gate`) and `log.<log kind in lower case>` for the rest
(for example `log.paused`, `log.run_finished`). An engine row whose body names no input is
`log.engine`. `rejected` is the rejection code of an audit-only engine row.

## Actions

Each action starts with `owned_run`, runs its bridge call in the caller's share of the pool
with a 30 s limit, and answers the run read again after its commit, with exact
`allowed_actions`. A 503 after the limit can still see the commit land; a retry is then a
no-op.

| Route | Behaviour |
|---|---|
| `:pause` | A finished run is 409. A paused run is a 200 no-op. Otherwise the bridge pauses it for the user (`PauseRun(reason="user")`, starting it first if needed): 200, or 409 with the engine's refusal code. A run that cannot be loaded is 409 `reason: engine.load_failed`, and that write pauses its row `failure_path`, as every bridge write does. |
| `:resume` | A finished run is 409. A run not paused is a 200 no-op. Otherwise 200 when the engine took the resume or the row left `paused`; a resume that clears one cause of several leaves the run paused, and the answer shows it. Else 409 `reason: resume_not_allowed`. A run that cannot be loaded is 409 `reason: engine.load_failed`. A `cap` out of bounds is 422. |
| `:cancel` | A cancelled run is a 200 no-op. A completed or failed run is 409. Otherwise the bridge cancels it. A run the bridge cannot load, or whose rows are gone, is cancelled on its row alone (below): 200. |

The 409 for a finished run says "The run is completed." (or failed, or cancelled).

**Store-only cancel** (`cancel_run_row`). One commit on an unfinished row:

- sets `cancelled`, clears the pause reason and sets `finished_at`;
- writes one `RUN_FINISHED` row with the body `{"kind": "cancel_run", "status": "cancelled",
  "store_only": true, "cause": "engine.load_failed", "sessions_queued": N,
  "sessions_unreachable": bool, "gates_closed": M}`;
- raises the run-end alerts;
- marks each open gate row `CANCELLED`;
- queues one `cancel_sessions` row per unclosed slot session, plus the orchestrator's, at
  most 33, and only when the run's rows decode.

The route then withdraws this process's prompts of the closed gates; every process's
sweep withdraws the rest within 60 s. When sessions may be left running, the
`run_cancelled` alert has normal priority and says so. A later commit on a cancelled row
whose engine still runs commits `CancelRun` first (convergence), so the row stays
cancelled.

## Gate answers

`POST /runs/{run_id}/gates/{node_id}:answer` with `{"visit_token": 1-512, "outcome": 1-128,
"note": "" (at most 2,000)}`. NUL and lone surrogates are refused in the model.

It goes through `GateAnswers.answer_visit`, sharing the prompt route's rules: the owner is
checked on the run row, then the answer takes one of the caller's admissions (4 in all, 2
per user, shared with the prompt route), and only then is the run loaded
([`gates-and-inbox.md`](gates-and-inbox.md)). A visit that can no longer be answered says
so before an outcome the gate lacks is refused.

| Verdict | Answer |
|---|---|
| accepted, duplicate | 200 `{"result": "accepted"}`, `{"result": "duplicate"}` |
| no such visit, `not_permitted` | the run 404 |
| `stale_visit` | 409 `stale_visit` |
| `already_answered`, `no_longer_waiting`, `run_paused` | 409 `illegal_transition`, `details.reason` |
| `invalid_answer` | 422 `validation_failed`, `details.reason: invalid_answer` |
| `run_busy` (past an admission, a 30 s limit, an error) | 503 `server_busy`, `details.reason: run_busy` |

The messages are the verdict's own texts. After an accepted answer, or one that closes the
prompt, the route withdraws this process's prompt.

## `allowed_actions`

One function, `allowed_actions` (`coral/runview/actions.py`), serves the list, the detail,
the action answers and the stream's `run` frames. `pause` is never offered on a paused run.

| Row status | Engine | Offered |
|---|---|---|
| completed, failed, cancelled | any; the row wins | none |
| any unfinished | cannot be loaded | `cancel` |
| starting, running | any | `pause`, `cancel` |
| paused | not paused (a pause on the row alone) | `resume`, `cancel` |
| paused | paused, and some cause a resume clears | `resume`, `cancel` |
| paused | paused, and no cause a resume clears | `cancel` |
| paused | not loaded (a list item) | `resume`, `cancel` when the row's reason is `user`, `rejected_calls`, `infra`, `auth`, `plan_limit` or `authority_revoked`; else `cancel` |

A list item offers a subset of what its detail offers, for a run that loads (see
"Residuals"). A run paused only at its activation
cap (`budget`) is not offered Resume: `:resume` needs a higher `cap`, and the detail's
`causes` and `max_activations` let a client offer it.

## Spend

`spend` is what the run has spent so far, as last read. It is shown and never capped.

```json
{"estimate": true, "usd": 1.25, "live_usd": 1.31,
 "tokens": {"input": 1200, "output": 300, "total": 1500, "cache_read": 0, "cache_creation": 0},
 "unpriced_models": [], "sessions": 3, "as_of": 1763500000}
```

- One read of the session tree from the run's anchor (`load_session_usage_and_tree`), run
  in the run's workspace. `usd` is `total_cost_usd`, the figure the anchor's badge shows;
  `live_usd` is `policy_cost_usd`, else `total_cost_usd`, and includes spend still in
  flight. Both are `null` when nothing was priced, and a lower bound when
  `unpriced_models` is not empty. `spend` is `null` when the anchor has no sessions yet or
  the read failed.
- A cache per `(workspace, run)`: fresh for 15 s while the run is unfinished or finished
  under 60 s ago, then 300 s; at most 1,024 entries; one read per key at a time; a failure
  shows `null` for 5 s.
- The list uses the cache only and queues background refreshes (at most 64 pending; more
  are dropped). Action and start answers (201, and the 200 replay) carry cached spend only,
  like the list, so they often show `null`. The detail waits up to 10 s; at most 2 detail reads run, 1 per user, and
  past either it answers from the cache at once.
- Reads run on the `coral-spend` pool (3 threads), never the API pool, and only after the
  owner check.

## Fairness

All caps are per process.

| What | Limit |
|---|---|
| Runs API calls (`coral-api` pool, 16 threads) | 16 in flight, 8 per user (normalized owner and generation), 30 s each; past either, 503 at once. A call that timed out keeps its slot until its thread ends. |
| Starts | 8 in flight, 2 per user, one at a time per run id; each pool call inside takes an API slot only for its own length, so host I/O holds no thread |
| Detail spend reads | 2 in flight, 1 per user |
| Gate answers | 4 in flight, 2 per user, taken after the owner check |
| Streams | [`run-stream.md`](run-stream.md): 8 per run and user, 32 per user, 200 in all, 4 opening loads per user, 8 connects then 1 a second per user and run |

## Proof

`tests/coral/omni/test_runs_end_to_end.py` runs the routes through the real server and
Coral's lifespan with authentication off, header auth and accounts. A gate run is listed,
read, started again with its key (200, and 409 for another request), followed live,
paused, resumed and answered to its end; another is cancelled; another user gets the same
404 bytes on every runs route. `tests/coral/api/test_runs_api.py` holds the per-route
cases, and `tests/coral/api/test_openapi_drift.py` checks that the spec lists exactly the
mounted Coral routes, is typed, and that the TS types are current.

## Residuals

- **Servers that require no identity, and same-user steps.** Any local process of the user,
  or a step shell that can reach the server, can act as the owner
  ([`gates-and-inbox.md`](gates-and-inbox.md), "Residuals"). This is tied to CRL-137's
  sandbox probe.
- **Workflows.** Legacy unowned workflows are readable by every caller in the workspace and
  claimed by their first saver. On a single-user server every workflow is saved unowned, so
  turning identity on later makes them legacy rows. A re-created account with the same user
  id keeps that id's workflows. Sharing is CRL-148.
- **Workflow definitions live in one SQLite file per data directory** (`<data dir>/coral.db`,
  so one per replica), not in the operational database. On a server with several replicas
  a start cannot find a workflow saved on another replica.
- **Caps are per process and per replica.**
- **The store-only cancel** cannot interrupt step sessions when the run's rows do not
  decode, and cannot name a session whose create had not finished. Their tool calls are
  refused by the run guard, and the alert says sessions may still run. Convergence is
  opportunistic: only a later commit on the row triggers it.
- **A list item can offer more than its detail** for a run that cannot be loaded: one still
  running lists Pause and Cancel, and one paused `user` before its rows stopped decoding
  lists Resume. The detail offers Cancel only, and `:resume` answers 409
  `engine.load_failed`.
- **A replay can still pause a run** whose stored data stops decoding between its read and
  the engine's start commit, a window of milliseconds; the start then answers 503.
- **A crash between creating the worktree and storing the run** loses `base_commit` for
  good: an adoption cannot report it. Nothing reads it today (CRL-136).
- **Two replicas racing one start** can both answer 201 when the bridge's own retry check
  returns the other replica's run. One run is made either way.
- **`:pause` of a run that cannot be loaded** answers 409 and pauses its row
  `failure_path`, as every bridge write does.
- **Spend.** `unpriced_models` sees only the usage's `by_model` buckets: a session that
  records none leaves `usd` a silent lower bound, and a model priced in one session and
  unpriced in another is not listed. A refresh stuck on a huge tree holds up the queue,
  and refreshes past 64 pending are dropped; lists then show cached or `null` spend.
- **A log row whose stored value is cut short, of an unknown codec or too large** is a
  `/log` placeholder, but the engine's fold raises on it: a `ValueError` there may be a
  reducer defect, so it is not taken for an unloadable run. The run's detail and `:cancel`
  answer 500, and its stream ends at once. The same value in the run's spec, slot or gate
  rows reads as a run that cannot be loaded, which the store-only cancel ends.
- **Folding collations.** On MySQL, look-alike owner ids are dropped after paging, with no
  scan budget, so one list call can read every look-alike row.
- `GET /v1/coral/info` is unauthenticated (pre-existing). Omnigent's own `/openapi.json`
  and `/docs` list the Coral routes; that live spec has a dangling `RunStreamFrame` `$ref`
  ([`run-stream.md`](run-stream.md)).

## Deferred work and owners

| Work | Owner |
|---|---|
| Run preflight (`POST /runs:preflight` answers 501): the CRL-132 facts need an `AgentSpec` per step, and only `materialize` builds them | CRL-137 |
| Step retry (`:retry` answers 501) and the restart ladder | CRL-137 |
| Run requests over 512 characters (refused today, never cut) | CRL-137 |
| A durable marker for a pause made on the run row alone | CRL-137 |
| The run outcome (`GET /runs/{id}/outcome` answers 501) and `diff_stat` | CRL-136 |
| The run view and runs history, start-dialog wiring, marking a run's alerts read when it is opened, bulk ack (`POST /v1/coral/inbox/ack`) | CRL-136 |
| The lost `base_commit` after a crash between the worktree and the run row | CRL-136 |
| Workflow sharing (K7's view and edit matrix) | CRL-148 |

Activation rows are not projected: the engine state carries them, and the detail's `view`
shows them.
