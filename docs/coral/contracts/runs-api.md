# Contract K7 (subset): the runs API

- **Status:** Draft v1, live. A run's owner can start, list, read, pause, resume and
  cancel the run, retry a failed step, answer its gates, follow it as a stream and, once it ends, read what it
  produced with a command that checks it out. Anyone else gets one fixed 404 and learns
  nothing about the run.
- **Code:** routes in `coral/api/runs.py`; the service, its pools and its caps in
  `coral/api/run_service.py`; models in `coral/api/run_models.py`; the outcome in
  `coral/api/outcome.py`; the error shape in
  `coral/api/errors.py`; allowed actions in `coral/runview/actions.py`; spend in
  `coral/api/spend.py` and `coral/omni/server/usage.py`; the store-only cancel in
  `coral/recovery/cancel.py`; the stream in `coral/api/stream.py`; the router table and
  wiring in `coral/omni/server/plugin.py`; the spec in `coral/api/openapi.json`, written
  by `coral/omni/server/openapi.py`; the web client in `web/src/workflows/api/runsApi.ts`;
  the web's run view, runs history and Start Run in `web/src/workflows/runs/` and
  `web/src/workflows/start/`.
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
| `POST /runs/{run_id}:retry` | `coral_retry_run` | 200 `RunSummary` ("Actions") |
| `POST /runs/{run_id}/gates/{node_id}:answer` | `coral_answer_gate` | 200 `GateAnswerOut` |
| `POST /runs/{run_id}/activations/{activation_id}:retry` | `coral_retry_activation` | 200 `RunSummary` ("Actions") |
| `GET /runs/{run_id}/outcome` | `coral_get_run_outcome` | 200 `RunOutcome` ("Outcome") |
| `POST /runs:preflight` | `coral_preflight_run` | 200 `PreflightResponse` |

- Every POST takes a JSON body. Pause, cancel and retry take `{}`; resume takes
  `{}` or `{"cap": 1..1000}`; preflight takes `{workflow_id, host_id}`.
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
  503 `server_busy`. `:preflight` names no run, so without the runs API it answers that
  same 404 after the caller check and request validation.
- `:retry` checks `activation_id` as 32 lowercase hex with the rest of the request (422,
  before the owner check). Coral never echoes the id and never writes it to its own logs;
  the server's access log records the request line, path included, as it does for every
  path id. The id is a derived hash that grants nothing without the run's ownership.

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
| `illegal_transition` | 409 | An action the run cannot take (`details.status`, `pause_reason`, and `reason` when known); a refused retry (`details.reason`, "Actions"); a gate `already_answered`, `no_longer_waiting` or `run_paused` (`details.reason`); an Inbox ack of an open gate alert |
| `stale_visit` | 409 | A gate visit asked again since |
| `worktree_failed` | 409 | The host could not create the worktree, and it is not locked |
| `payload_too_large` | 413 | A workflow save that is too large |
| `stream_limit` | 429 | Stream caps or the connect rate (`Retry-After: 5`) |
| `host_offline` | 503 | No host connector, or the host is offline |
| `server_busy` | 503 | Caps, a 30 s timeout, `RunContended`, a closed pool, a gate's `run_busy`; `Retry-After: 1`, `2` for a worktree another start holds locked, `5` for a stream while the server shuts down |

- The JSON check runs first, before the caller. An unauthenticated POST that is not JSON is
  422.
- Any other `HTTPException` with a 4xx status is `validation_failed`. Other errors go to the
  server's own 500 handler. A write that fails this way logs only `describe_exception` and
  raises a new error without its cause, so Coral's own logs carry no statement parameters.
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
6. **The start's base.** `base_commit` is the commit the worktree reports it was made at.
   A worktree that reports none (an adoption, a worktree made again on the existing
   branch, an older host) has its `head` read through the starting owner's host channel
   before the run row exists: a 5 s host deadline, 10 s over the channel lookup and the
   read, and no pool thread held. It is kept only when the worktree is on the run branch.
   A refused, failed or slow read never fails the start: `base_commit` stays `null`, the
   outcome then answers `base_unknown`, and one INFO line names the run, the exception's
   type and its code (`Coral could not read run <id>'s start head: <Type> <code>`), never
   its text.
7. The owner, account generation, workflow text and run target come from the server; the
   host id is stored in the form the server's host registry keys it by. The title defaults
   to the workflow's name without control and bidi characters, cut to 256 (or the workflow
   key if that leaves nothing). `start_engine_run` then commits the start: 201. A start
   that lost a race on another replica is answered as a replay, whatever base either
   replica read: the bridge's retry check leaves `base_commit` out.

**Replay.** The same owner and request answer the run the key made: 200 with its summary.
The request is compared with the stored spec: `workflow_id`, `host_id` (the request's and
the stored one in the registry's form), `repo_path`, `base_ref`, `request`,
`max_activations`, and `title` only when the request gives one. Any difference is 409
`start_key_conflict`, "This start key started a run with another request." The definition is not read again, so an edit, rename or deletion since never
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
- **`retry_activation_ids`** on the detail: the store activation ids of the failed steps a
  retry may restart now, in cause order (`retryable_activations` mapped through
  `store_activation_id`, `coral/api/run_models.py`). It is empty while the run is not
  paused, while a host hold or a restart stands, when the run cannot be loaded, and for a
  finished row. Map an id to its step through `slots[].activation_id`. The stream and
  `RunView` do not carry it; a client reads the detail again after an action.
- **Fields the web reads.** Every `RunSummary` (list, detail, action and start answers)
  carries `run_branch`, always `run_branch_name(run_id)` (`coral/r-<12 hex>/base`),
  computed and never read from a row. Each `gates` item carries `context`: the text the
  gate's published prompt asks (`gate_prompt_text`, with the run's title), `null` when the
  run did not load or the visit is not in the engine state. Each `slots` item carries
  `engine_slot_id`, the slot's id in the view (`<activation id>:<roster index>`); its
  activation is the id up to the last `:`. The stream's frames and `RunView` are unchanged.
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
| `:retry` (run) | Retries the run's failures no step owns: the bridge commits `RetryRun` (`EngineBridge.retry_run`), which clears every `failure_path` cause with subject `""` (`anchor:*`, `gate:*`, `orchestrator:*`, `decision:*`, `unbuildable`). An `orchestrator:*` or `decision:*` cause also starts a new orchestrator generation ([`session-facade.md`](session-facade.md), "The orchestrator"). 200 `RunSummary`: running again, re-asked as Resume does, or still paused for another cause. Offered when `allowed_actions` has `retry`. Refusals as below, with "This run cannot be retried now." for `retry_not_allowed` (nothing to retry, a run not paused, or the orchestrator's last generation) and `unbuildable`; there is no `unknown_activation`. |
| `/activations/{id}:retry` | Retries one failed step, named by its store activation id (one of the detail's `retry_activation_ids`): the bridge commits `RetryStep` (`EngineBridge.retry_activation`). A taken retry answers 200 `RunSummary`, still paused (`infra`): the run stays paused while the step's old session is fenced and its work saved, then the step's next session generation starts ([`session-facade.md`](session-facade.md), "Retry"). Refusals below. |

The 409 for a finished run says "The run is completed." (or failed, or cancelled).

**`:retry` refusals** (`RunsApi.retry`, `coral/api/run_service.py`). Every 409 is
`illegal_transition` with `details` `{status, pause_reason}` and, except for a run already
finished when read, `reason`. Every answer sends `Cache-Control: private, no-store`. A
refused retry commits nothing, except the `failure_path` pause of a run that cannot be
loaded or whose commit cannot be built.

| Case | Answer | `details.reason` | Message |
|---|---|---|---|
| Another user's run, or an unknown run | the fixed 404 | | "Run not found." |
| A malformed activation id | 422 `validation_failed` | | |
| A run already finished when read | 409 | none | "The run is completed." (or failed, or cancelled) |
| A run cancelled while the retry commits | 409 | `run_terminal` | "The run is cancelled." |
| A run that cannot be loaded | 409 | `engine.load_failed` | "The run cannot be loaded; it can only be cancelled." (its row is paused `failure_path`, as every bridge write does) |
| An id that is no activation of this run (another run's included), or any id before the engine started | 409 | `unknown_activation` | "The run has no such step." |
| A step a retry does not restart now: a completed step, a gate, a decision, a run not paused | 409 | `retry_not_allowed` | "This step cannot be retried now." |
| A host-offline hold on any step | 409 | `host_offline_hold` | "The run's machine is offline; steps can be retried once it is back." |
| A restart in progress on any step | 409 | `restart_in_progress` | "A step of this run is restarting; try again when it is done." |
| A retry whose commit cannot be built | 409 | `unbuildable` | "This step cannot be retried now." (the run is paused `failure_path`) |
| Busy | 503 `server_busy` | | |

Proof: `tests/coral/api/test_runs_api.py` (`test_a_retry_the_run_cannot_take_is_refused_with_its_reason`,
`test_a_retry_naming_a_malformed_activation_is_refused_before_any_work`,
`test_a_retry_that_meets_a_cancel_is_refused_and_queues_no_restart`,
`test_a_retry_after_the_run_ended_is_refused_before_the_engine_is_asked`,
`test_a_host_hold_on_one_step_keeps_another_failed_step_from_its_retry`,
`test_a_run_retry_clears_its_run_level_failure`, `test_a_run_retry_the_run_cannot_take_is_refused_with_its_reason`) and
`tests/coral/omni/test_runs_end_to_end.py` (a step retry; an archived orchestrator replaced by a run Retry). A retry only restarts a paused run's step, and
a finished run is never retried, so an outcome read needs no re-check of its run's
status.

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

## Outcome

`GET /runs/{run_id}/outcome` answers 200 `RunOutcome` with `Cache-Control: private,
no-store`; its refusals are 401, 403, the run 404, 422 and 503 `server_busy` from the pool.
Whatever stops the diff is answered as `diff_unavailable`, never as an error. The
recorded run's outcome (`web/src/workflows/fixtures/runView.contract.json`):

```json
{"run_id": "84170e76f35c7a90d1280a24a7230fc9", "status": "completed", "finished_at": 1767269280,
 "branch": "coral/r-a0ee7440cfc3/base", "host_id": "host-1",
 "repo_path": "/home/alice/team's repo",
 "worktree_path": "/home/alice/team's repo-worktrees/coral-r-a0ee7440cfc3-base",
 "base_commit": "3f2a9c41d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a3",
 "head_commit": "9d8c7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e1d0c",
 "diff": {"from_commit": "3f2a9c41d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a3",
          "to_commit": "9d8c7b6a5f4e3d2c1b0a9f8e7d6c5b4a3f2e1d0c",
          "files_changed": 3, "insertions": 42, "deletions": 7,
          "paths": ["docs/release\\u{202E}notes.md", "src/parser.py", "tests/test_parser.py"],
          "paths_truncated": false},
 "diff_unavailable": null,
 "checkout": {"command": "git -C '/home/alice/team'\"'\"'s repo' checkout --detach refs/heads/coral/r-a0ee7440cfc3/base",
              "worktree_command": "cd '/home/alice/team'\"'\"'s repo-worktrees/coral-r-a0ee7440cfc3-base'",
              "unavailable": null}}
```

- Exactly one of `diff` and `diff_unavailable` is set. `branch` and `host_id` are `null`
  only when the run has no worktree of its own; `repo_path` and `worktree_path` are also
  `null` when `checkout.unavailable` is `unsafe_path` or `non_posix_path`. `head_commit` is
  the branch tip the host reported for this read.
- An unfinished run answers 200 with `run_not_finished`, not 404: a 404 on a runs route
  always means "not your run".

**Order** (`RunsApi.outcome`):

1. `owned_run`; nothing comes before it.
2. The run's stored rows, on the pool; rows that are gone or cannot be read count as no
   worktree. The target is the spec's host, repository, worktree and branch, and only when
   all are set and the branch is `run_branch_name(run_id)`.
3. The checkout commands, always built (below).
4. No host is contacted when the run is not finished (`run_not_finished`), has no target
   (`no_worktree`) or no base (`base_unknown`), when the server has no host channels
   (`host_offline`), or when an unfinished run of the workspace uses the same host
   (`host_busy`). The last is one indexed read, `RunStore.unfinished_run_hosts(*,
   workspace_id)`, compared in the registry's host-id form. A `paused` run counts with
   `starting` and `running`: its held effects and its step sessions can still act on the
   host, whose two op slots a live run's evidence reads share.
5. Otherwise the host's READ ops `head` and `diff_stat` read the diff through the owner's
   host channel (`HostWorkspaceOps`, `HostChannel` executor). Every argument of the channel
   comes from the stored run (its user, account generation and host), and the channel
   authorizes the owner for the host before any frame. The server never runs git.

**The read.** At most 4 at once in a process and 1 per user (a refused read is `busy`, at
once); one read per `(workspace, run)` at a time, which every caller awaits shielded, so a
cancelled caller never cancels it. A 5 s host deadline per op and one 12 s deadline over
the channel lookup, `head` and `diff_stat`; no pool thread is held during host I/O. A head
on another branch is `worktree_missing`. A cache keyed by `(workspace, run, base, head)`
keeps only the trimmed diff (counts, at most 100 sorted paths, the truncated flag), 256
entries and 2 MiB of path bytes, least recently used out; a hit sends only `head`.

| `diff_unavailable` | When |
|---|---|
| `run_not_finished` | The run is not completed, failed or cancelled |
| `no_worktree` | No target, or another run's branch |
| `base_unknown` | The spec has no `base_commit` |
| `host_busy` | An unfinished run of the workspace uses this host |
| `host_offline` | No host channels; the host is offline, not usable by this owner (`HostAccessRefused`), or its tunnel dropped (a non-permanent `workspace.backend_unavailable`) |
| `worktree_missing` | `workspace.target_mismatch`, `workspace.worktree_displaced`, or a head on another branch |
| `compare_failed` | `workspace.git_failed` or refused params (a base the repository lacks) once `diff_stat` was sent |
| `busy` | Admission refused, `workspace.timeout`, the 12 s deadline |
| `failed` | Anything else: a missing capability, a malformed reply, git failing on `head` |

Each failure logs at INFO `Coral could not read run <id>'s outcome: <Type> <code>`, or a
fixed line for a head on another branch, never the exception's text: host and git messages
hold paths. A refused admission logs at DEBUG with the run id and the reads in flight.

**Paths.** Each diff path shows every backslash, and every character of the categories
Cc, Cf, Cs, Co, Cn, Zl and Zp or of a fixed set of invisible code points (Hangul fillers,
Khmer inherent vowels, Mongolian and other variation selectors, the combining grapheme
joiner, the Braille blank), as `\u{XXXX}`, so every backslash shown starts an escape. A path
is cut at 512 characters, never inside an escape, with a trailing `…`. `paths_truncated`
says the host or the server cut the list.

**Checkout command.** `git -C <repo> checkout --detach refs/heads/<branch>`, with
`cd <worktree>` apart, each argument through `shlex.quote`:

- Plain `git checkout <branch>` and `git switch` fail while the run's worktree holds the
  branch. `--detach` moves the main checkout to the branch tip and leaves the person's
  branches alone; with local files in the way git refuses and changes nothing.
- `refs/heads/` keeps a tag of the same name from changing what is checked out. `git -C`
  rather than `cd … &&`: a failed `cd` cannot run git elsewhere. Both paths start with `/`,
  so neither reads as an option.
- The checkout runs the repository's hooks, and a hook manager whose scripts or config
  are tracked (husky, lefthook, pre-commit's `post-checkout` stage) runs the versions in
  the commit being checked out, which the run's agents wrote. Review the worktree with the
  `cd` command first (Residuals).
- No command and no path when either path holds `\` or one of the refused characters
  above (`unsafe_path`): without backslashes the quoting reads the same in sh, bash, zsh
  and fish. None for a path that is not absolute POSIX (`non_posix_path`), and none without
  a target (`no_worktree`).
- The proof is `test_a_finished_runs_outcome_reads_its_diff_on_the_host_and_its_command_checks_it_out`
  (`tests/coral/api/test_runs_api.py`). It runs the command the route answered through
  `sh -c` on a real repository whose path holds a space, a quote, `$` and a backtick, with
  a colliding tag: the repository's HEAD becomes the run's tip, the plain checkout fails,
  and the diff equals `git diff --numstat`.

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
| paused | paused, with a `failure_path` cause no step owns and no host hold or restart | as above, with `retry` before `cancel` |
| paused | not loaded (a list item) | `resume`, `cancel` when the row's reason is `user`, `rejected_calls`, `auth`, `plan_limit` or `authority_revoked`; else `cancel` |

A list item offers a subset of what its detail offers, for a run that loads (see
"Residuals"). A list item never offers Resume for `infra` (`LIST_RESUMABLE_REASONS`):
its row cannot tell a host hold or a restart, which Resume never clears. `retry` is the
run's own Retry (`run_level_retryable`) and never on a list item; a step's Retry is the
detail's `retry_activation_ids`. A run paused only at its activation
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
| Outcome reads | 4 in flight, 1 per user, one per run shared by its callers; 5 s per host op, 12 s in all; a cache of 256 trimmed diffs and 2 MiB of paths |
| Streams | [`run-stream.md`](run-stream.md): 8 per run and user, 32 per user, 200 in all, 4 opening loads per user, 8 connects then 1 a second per user and run |

## In the web app

Every runs and Inbox query is keyed by the viewer's scope, `JSON.stringify([server
identity, or "mount:<generation>" for an embedded host; the app root; the viewer id])` from
`useCoralScope()`, the one the Inbox uses, and stays disabled while the viewer is unknown:
`["coral-run", scope, id]` (detail), `["coral-run-view", scope, id]` (the streamed view,
written only by the stream client), `["coral-run-graph", scope, id]`,
`["coral-run-outcome", scope, id]`, `["coral-runs", scope, filters]` and the mutation key
`["coral-run-action", scope, id]`. Refusals in Coral's envelope keep their `details` as a
`CoralRequestError`. Paths below are under `web/src/workflows/`.

- **The run view** (`/workflows/runs/:runId`, `runs/RunPage.tsx`). Status, pause reason,
  causes and allowed actions come only from the stream's header and view
  ([`run-stream.md`](run-stream.md), "The web client"); the detail gives the title, spend,
  gates and slots. Before the stream's first frame the detail's status shows as
  provisional, with no actions. The pill reads "Needs you" while the view has an open gate.
  Pause, Resume and Cancel follow `allowed_actions`. A paused run's banner explains its
  first cause, then lists the rest, steps someone typed into or whose session changed,
  and decisions the orchestrator has yet to make; there is no server `stalls[]`. The
  canvas and an accessible step list show each node's state and "pass N of M". An open
  gate is answered inline through `:answer` with the visit's token
  ([`gates-and-inbox.md`](gates-and-inbox.md)). The detail is read again every 30 s while
  the run is unfinished and the page visible (for spend), and when the view and the detail
  disagree on gates, slots or pause causes, at most every 2 s. Spend is shown, never capped.
- **Retry** (`runs/RetryStepButtons.tsx`, in the paused banner). One "Retry <step>"
  button per id in the detail's `retry_activation_ids`, the step named through
  `slots[].activation_id` and the graph, isolated, or "Retry a step" when it cannot be
  named. Each posts `{}` to `:retry` (`retryStep` in `api/runsApi.ts`, mutation key
  `["coral-run-retry", scope, run id, activation id]`), so a retry never disables Pause,
  Resume or Cancel. One request per button is in flight; a button is disabled while the
  browser is offline or the viewer unknown. The banner's status line says "Retrying." on a
  200 and shows the server's message on a 409, and stays mounted, so an answer that
  arrives after its button is gone is still announced. The page reads the detail again
  when the stream's causes change (`runs/detailStaleness.ts`). The banner explains each cause
  (`shared/pauseCopy.ts`; `<step>` is the step's isolated name, "a step" or "A step" when
  unnamed):

  | Cause | Text |
  |---|---|
  | `infra` / `infra.host_offline` | "Your machine went offline. Coral will continue <step> when it’s back." |
  | `infra` / `recovery.restarting` | "Coral is restarting <step> from its last handoff." |
  | `infra` / `infra.runner_lost` | "<step> keeps losing its runner. Resume tries again; Retry restarts it from its last handoff." |
  | `infra` / `recovery.runner_alive` | "<step>’s runner is running but can’t reach Coral. Resume tries again." |
  | `infra` / `session.runner_status_unknown` | "Coral couldn’t check <step>’s runner on your machine. Resume tries again." |
  | `failure_path` / `restart:dispatch.stop_unconfirmed`, `restart:session.host_offline`, `restart:workspace.backend_unavailable` | "Your machine went offline before <step> could restart. Retry when it’s back." |
  | `failure_path` / `restart:workspace.head_moved` | "The run’s branch moved outside Coral, so <step> was not restarted. Reset the branch to the commit of its last handoff, then retry; or cancel the run." |
  | `failure_path` / any other `restart:<code>` | "Coral couldn’t restart <step>. Retry tries again." |
  | `failure_path` / `session.host_unsupported` | "<step>’s machine can’t run Coral steps. Update Coral there, then retry." |
  | `failure_path` / `session.closed` | "<step>’s session was closed, so it can’t go on. Retry starts it again from its last handoff." |
  | `failure_path` / `blocked` | "<step> reported that it is blocked. Retry restarts it from its last handoff." |
  | `failure_path` / `orchestrator:*`, `decision:*` (subject `""`) | "The run’s orchestrator failed. Retry starts a new orchestrator." |
  | `failure_path` / `anchor:*`, `gate:*` (subject `""`) | "A step or one of Coral's own actions failed. Retry tries again." |
  | `failure_path` / `attempts_exhausted:<ids>` (or the ids as subject, as older runs recorded it) | "Missing evidence: <ids>." |

  Every other cause, the wake's other refusals (`session.not_bound`,
  `session.host_not_permitted`, `session.deleted`, `slot.generation_mismatch`) included,
  keeps its reason's general text. The host-offline restart text also shows for a
  `dispatch.stop_unconfirmed` whose runner did not answer, or a permanent
  `workspace.backend_unavailable` from a host that is online. Two unnamed steps get two
  identical "Retry a step" buttons. When `allowed_actions` has `retry`, the banner also
  shows a "Retry" button for the run that posts `{}` to `/runs/{id}:retry` (`postRunAction`,
  mutation key `["coral-run-retry", scope, run id, ""]`), with the same status line. Retry
  is offered only in the run view's banner, not on an Inbox card or a list item.
- **The step drawer** (`?agent=<session>&node=<node>`, `runs/agents/StepDrawer.tsx`). It
  opens only a session the run's own slots list, shows its transcript and prompts (no
  composer) with "Open in Chat", and keeps the URL on the run, so AppShell stays out of chat
  mode. While open it retains its session, so the run stream's eviction never takes it;
  closing releases the stream of a session the drawer opened, never after "Open in Chat"
  and never the chat store's active conversation. A run session's Chat header links back
  to its run (S86, `session/CoralRunChip.tsx`).
- **The outcome panel** (`runs/outcome/OutcomePanel.tsx`), for a finished run only: the
  outcome is read once the stream or the detail says the run finished, not again after
  `[DONE]`. It shows the branch, base → head (12 characters), "N files changed, +I −D", the
  first 20 paths then "and N more", the server's `command` and `worktree_command` verbatim
  with copy buttons that copy exactly what is shown, the hint under the command, and a note
  for each `diff_unavailable` and `checkout.unavailable` code, with Retry for `busy` and
  `host_busy`; nothing reads again on its own. Commands and paths render `dir="ltr"` with
  `unicode-bidi: isolate`; a path the server escaped carries a warning mark with an
  accessible name, and a line explains the `\u{XXXX}` escapes. With `unsafe_path` or
  `non_posix_path` it names the branch and shows no path. A 404 says "Outcome not available
  yet"; any other failed read says "Couldn't load the run's outcome." with Retry. After a
  Retry, focus stays on Retry while it is offered, else moves to the panel's heading. The
  panel never builds a command.
- **Runs history** (the desk's Runs tab, `runs/list/RunsTable.tsx`), with the tab, status
  and workflow in the URL (`?tab=runs&status=…&workflow=<id>`), 25 a page and "Load more".
  With one page loaded it polls every 10 s while a run on it is starting or running, every
  60 s while only paused runs are unsettled, and reads once more after 5 s when the first
  read lacked a run's spend (the list serves cached spend only, and the app never refetches
  on window focus); with more pages loaded, "Refresh" goes back to the first. A start, and
  a pause, resume, cancel or gate answer that succeeds, invalidates `["coral-runs", scope]`.
- **Opening a run** marks its low-priority run-end alert read once the detail has
  loaded, through `POST /v1/coral/inbox/ack` ([`gates-and-inbox.md`](gates-and-inbox.md)).
- **Start Run** (`start/StartRunDialog.tsx`) posts `{workflow_id, start_key, host_id,
  repo_path}`. The start key is a new `randomUUID()` when the dialog opens and whenever the
  host or folder changes, and the same on a retry, so a retried POST replays. 201 or 200
  opens the run. Once a host is chosen it posts `{workflow_id, host_id}` to
  `:preflight` and shows the report; Start stays disabled while `ok` is false.
- **Proof** (Vitest and RTL, over `runView.contract.json`, which
  `tests/coral/api/run_view_contract.py` records from the real stream, serializers and
  outcome assembler, checked by `tests/coral/api/test_run_view_contract.py`):
  `runs/RunPage.proving.test.tsx` follows the recorded run's step transitions live, answers
  its gate inline and lets the same stream carry the run on with no reload, renders every
  pause reason's copy, and shows the finished run's outcome with the fixture's exact
  `checkout.command`. These prove the client halves: the server halves are the answer
  route's tests and `test_runs_end_to_end.py` for the gate, and the real-git outcome test
  for the command.

## Proof

`tests/coral/omni/test_runs_end_to_end.py` runs the routes through the real server and
Coral's lifespan with authentication off, header auth and accounts. A gate run is listed,
read, started again with its key (200, and 409 for another request), followed live,
paused, resumed and answered to its end; another is cancelled; another user gets the same
404 bytes on every runs route; the finished gate run's outcome names its branch and
checkout command (it recorded no base, so `base_unknown`), and the detail's gate carries
its prompt's text as `context`; a blocked step's owner retries it, another user gets the
404, and the run waits on the restart it queued
(`test_the_owner_retries_a_blocked_step_and_the_run_waits_on_the_restart_it_queued`).
`tests/e2e/coral/test_runner_loss.py` retries a blocked step on a real server, host and CLI
through to a completed run. `tests/coral/api/test_runs_api.py` holds the per-route
cases, the real-git outcome and the start-head reads; `tests/coral/api/test_run_outcome.py`
the checkout and path rules, the read's admission, single flight, deadlines, cache, error
map and logs; and `tests/coral/api/test_openapi_drift.py` checks that the spec lists
exactly the mounted Coral routes, is typed, and that the TS types are current.

## Residuals

- **Servers that require no identity, and same-user steps.** Any local process of the user,
  or a step shell that can reach the server, can act as the owner
  ([`gates-and-inbox.md`](gates-and-inbox.md), "Residuals"; ADR-05's probe 15 measured
  a step shell reaching the server, CRL-159). `:retry` is one more owner action; a retried step's old session is refused while the run is
  paused.
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
- **The start's base is what the run branch holds when the start reads it.** After a
  crash between the worktree and the run row, the retry reads the adopted worktree's head.
  Any manual change to the run branch before the run row is written (a commit, a reset, a
  pull, a rebase) becomes the base, so a reset to an older commit makes the outcome
  include commits the run did not make. A same-key start retry that names another `base_ref`
  adopts the branch the first attempt made: `base_commit` is that branch's real start,
  while `base_ref` records the retry's value. Rows that lost their base before this read
  existed keep `null` and answer `base_unknown`; there is no fallback.
- **Two replicas racing one start** can both answer 201 when the bridge's own retry check
  returns the other replica's run; the start-head read widens that window. One run is
  made either way, and the first stored base wins. When both adopt one worktree at once,
  the host refuses the second head read (`workspace.timeout`); if that replica's row
  commits first, the base is `null`.
- **`host_busy` counts paused runs.** A run paused for days (a plan limit, its activation
  cap) keeps every finished run's summary on that host unavailable until it is resumed or
  cancelled; Retry then shows it. A run started on the host while an outcome read is in
  flight is not counted; its first evidence read comes after a step's shell call, past
  the read's 12 s.
- **The outcome cache is per process,** so each replica reads a run's diff once.
- **The checkout command can run code the run wrote.** Tracked hook scripts or hook-manager
  config in the run's commits run in the owner's shell when they paste the command. Step
  shells already run as the owner on that host today (the first residual), so this adds
  little now; once the sandbox confines steps it is a way out of the sandbox (CRL-175); a
  variant with `-c core.hooksPath=/dev/null` would be a design change.
- **The run view's drawer shows every pending prompt a step session has**, as its Chat
  page does: question forms with typed answers, plan-review feedback, schema forms, and
  session-wide permission choices ("Accept & allow all edits", "Approve & switch to auto
  mode", "don't ask again"), which change how that step runs for the rest of its session.
  Each is the run owner answering their own step session, which "Open in Chat" allows one
  click away; hiding some would need an Omnigent edit. The drawer has no composer. ⌘↵ on
  any page accepts the newest prompt of the chat store's active conversation, which with
  the drawer open may be a session not on screen (Omnigent's hotkey; its hint shows only
  on the real target).
- **The run view, as built, is not checked in a browser** (the repository's rule): its
  layout, real xyflow clicks, `SideChatPane` outside the Workspace rail, the outcome's copy
  buttons, `Last-Event-ID` through the dev proxy and real Web Locks slots are listed for a
  manual check. A `?agent=` that names a session the detail has not listed yet shows
  "This session isn't part of this run." until a reread lists it. Closing a drawer over a
  chat that was already live frees no stream slot. A run paused at an open gate still
  shows the gate's buttons; the answer is refused `run_paused`.
- **The runs list** names workflows from the desk's unscoped `["coral-workflows"]` key.
  The server refreshes queued spend one run at a time, so a page of many cold runs may be
  only partly filled after its one follow-up read; the rest fill in on the next read.
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
| Run requests over 512 characters (refused today, never cut) | CRL-152 |
| A durable marker for a pause made on the run row alone | CRL-153 |
| Showing a retried step's salvage ref in the run view | CRL-158 |
| A request-body size cap for every Coral POST: FastAPI parses a body before a route's dependencies | CRL-150 |
| Workflow sharing (K7's view and edit matrix) | CRL-148 |
| Run view cuts: live steering in the drawer (Phase 2); the guarantees panel; the phone layout; Run again; the inspector's Step, Decision and Log tabs and the event timeline; per-command evidence (command, exit code, time); the orchestrator pane; resuming a budget pause with a raised cap; workflow version numbers; analytics; axe | no live ticket |

Activation rows are not projected: the engine state carries them, and the detail's `view`
shows them.
