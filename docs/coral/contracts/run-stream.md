# Contract K8: the run stream

- **Status:** Draft v1, live. A run's owner follows the run as server-sent events: a
  snapshot of its view, then one entry per run-log row with that row's stored view patch.
  A client that reconnects with `Last-Event-ID` gets every row it missed, once, in order.
- **Code:** the hub, watchers, stream loop and response class in `coral/api/stream.py`;
  frames in `coral/runview/types.py`; entries and headers in `coral/api/run_models.py`
  (`entry_frame`, `run_header`); the patch applier in `coral/runview/patch.py`; the route
  in `coral/api/runs.py`; the account re-check in `coral/omni/server/access.py`
  (`account_still_valid`); wiring in `coral/omni/server/plugin.py` (`_run_stream_hub`);
  the web client in `web/src/workflows/stream/` ("The web client").
- **Related:** [`runs-api.md`](runs-api.md) (the routes, the one 404, `allowed_actions`),
  [`session-facade.md`](session-facade.md) (the engine bridge and its view).

## Route

`GET /v1/coral/runs/{run_id}/stream?after_seq=<0..2^63-1>`, with an optional
`Last-Event-ID` header. Before any response, in this order:

1. The caller: 401 or 403 ([`runs-api.md`](runs-api.md)).
2. `after_seq`: anything but an integer from 0 to 2^63-1 is 422, without echoing it. This
   depends only on the request, so it comes before the owner check, whoever owns the run.
3. The runs API and the hub: without `app.state.coral_runs_api` or
   `app.state.coral_run_stream_hub` (before the lifespan publishes them, or with no
   operational database) the run 404. After the lifespan exits their pools are closed, and
   the next step answers 503 `server_busy`.
4. `RunsApi.owned_run`: the run 404, with no slot or watcher taken.
5. `hub.reserve()`:
   - the hub is closed, or the server is shutting down: 503 `server_busy`, "The server is
     shutting down; poll the run's log or try again shortly.", `Retry-After: 5`;
   - past a stream cap: 429 `stream_limit`, "Too many run streams are open; poll the run's
     log or try again shortly.", `Retry-After: 5`;
   - the user already has 4 opening loads running: 503 `server_busy`, "Too many of your run
     streams are starting; try again.", `Retry-After: 1`;
   - past the connect rate: 429 `stream_limit`, `Retry-After: 5`. A refusal above takes no
     connect token.

The response is `text/event-stream` with `Cache-Control: no-store` and
`X-Accel-Buffering: no`.

## The cursor

- `Last-Event-ID` wins over `after_seq` when it is sent.
- An empty header, after stripping, counts as not sent. A browser sends none before its
  first event id.
- A header over 20 characters, not 1-19 digits, or over 2^63-1 is `cursor_invalid`: a
  resync, never a refusal.
- No cursor at all means "start from a snapshot".

## Frames

Each event is `event: <type>\n[id: <seq>\n]data: <json>\n\n`. The data is one compact JSON
line that repeats `type` (`RunStreamFrame`, a union on `type`). Only `snapshot` and `entry`
carry an id, so `Last-Event-ID` is always the last seq the client holds.

| Type | `id` | `data` |
|---|---|---|
| `snapshot` | the head seq | the whole view at that seq |
| `entry` | the row's seq | one run-log row, without its body |
| `run` | none | the run header, when it changed |
| `resync` | none | why the cursor cannot be replayed; a `snapshot` follows |
| `heartbeat` | none | `{"type":"heartbeat"}` after 15 s without a frame |
| end | none | `data: [DONE]`, once the run is finished and every row is sent |

As sent, for a running run its owner pauses (values are examples):

```text
event: snapshot
id: 12
data: {"type":"snapshot","protocol":1,"view_version":1,"seq":12,"run_version":7,"log_version":3,"run":{"status":"running","pause_reason":null,"version":7,"finished_at":null,"allowed_actions":["pause","cancel"],"load_error":null},"view":{"status":"running","causes":[],"activations":[{"id":"start||","status":"closed","outcome":"completed"},{"id":"approve||","status":"running","outcome":null}],"slots":[],"open_decisions":[],"open_gates":["approve||:1"],"loop_pass_indexes":[],"armed_timer_keys":[]},"view_error":null}

event: entry
id: 13
data: {"type":"entry","seq":13,"run_version":8,"kind":"engine.pause_run","actor_kind":"user","actor":"alice@example.com","node_id":null,"scope_key":null,"at_us":1763500000000000,"rejected":null,"patch":[{"op":"replace","path":"/status","value":"paused"},{"op":"add","path":"/causes/0","value":{"reason":"user","detail":"user","subject":""}}]}

event: run
data: {"status":"paused","pause_reason":"user","version":8,"finished_at":null,"allowed_actions":["resume","cancel"],"load_error":null,"type":"run"}

event: resync
data: {"type":"resync","reason":"cursor_unknown"}

event: heartbeat
data: {"type":"heartbeat"}

data: [DONE]
```

- **`snapshot`.** `protocol` and `view_version` are 1; they change when the frames or
  `RunView` change shape. `run_version` and `log_version` are the run row's. A run that
  cannot be loaded has `view: null`, `view_error: "engine.load_failed"`, and a header that
  offers only Cancel.
- **`entry`.** `kind` is `engine.<input kind>` for an engine row, else `log.<log kind>`
  ([`runs-api.md`](runs-api.md), "Reads"). `rejected` is the rejection code of an
  audit-only engine row. `patch` is the row's stored view patch, verbatim, or `[]`. Every
  row gets an entry (except an unreadable row, below), so `seq` is always the last one
  plus 1. Bodies are left out:
  `/log` serves them.
- **Patches** are RFC 6902 operations on the `RunView` JSON, addressed by array index:
  `{"op": "add" | "remove" | "replace", "path": "/…", "value": …}`, with `"value": null`
  on `remove`. Apply them in seq order to the snapshot's `view`.
- **`run`.** The header: `status`, `pause_reason`, `version`, `finished_at`,
  `allowed_actions` and `load_error`. A finished row wins over what the view says.
  `allowed_actions` comes from the stream's own copy of the view.
- **`resync`.** `reason` is `cursor_invalid`, `cursor_unknown` (the cursor is past the
  head), `replay_too_long` (more than 1,000 rows behind) or `row_unreadable`.

## Opening

The stream reads the run once with `EngineBridge.read()`, which never writes. The head
seq `s` comes from the same read as the view.

| Cursor | Opening frames | Then sends rows after |
|---|---|---|
| none | `snapshot` (id `s`) | `s` |
| invalid | `resync` `cursor_invalid`, `snapshot` | `s` |
| greater than `s` | `resync` `cursor_unknown`, `snapshot` | `s` |
| more than 1,000 behind `s` | `resync` `replay_too_long`, `snapshot` | `s` |
| otherwise | `run` (the header at `s`) | the cursor |

A load whose row is no longer the caller's ends the stream before any frame of it.

## One loop for replay and the live tail

- Rows are read 100 at a time. A full page is followed at once by the next one, without
  waiting.
- Every row after the position is sent as an entry. The stream applies a row's patch to
  its own copy of the view only when the row is past `s`; rows up to `s` are already in it.
  So a row committed between the snapshot and the first page is sent once and applied
  once.
- A `run` frame is sent when the header changed in more than its `version`, when the
  stream holds every row up to the row's head, and when its version is at least that of
  every header and entry sent before. So a header never goes back.
- `[DONE]` follows once the client was sent a finished header and holds every row of the
  row's head.
- A heartbeat follows 15 s without a frame.

## How a stream ends

With `data: [DONE]` only as above. Without it, at its next wake, when:

- 5 minutes have passed since it opened (every stream, in every mode);
- the hub closed or the server is shutting down;
- the request went away;
- the run row is gone, or `is_owner` fails on the watcher's row (a moved account
  generation ends it at once);
- the caller's account fails its re-check (below);
- a read failed, or the run row holds a status or pause-reason code this server cannot
  read.

A stream wakes at least every 500 ms. A client resumes with `Last-Event-ID` set to the
last seq it holds.

## Unreadable rows

A row whose stored text cannot be read, whose patch is not a patch or does not apply to
the stream's view, or that holds a `kind` or `actor_kind` code this server does not know,
gives `resync` `row_unreadable` and a fresh `snapshot` at the current head. The stream
goes on from there, so a reconnect never meets that row again; `/log` shows it as a
`log.unreadable` placeholder.

## Wake-ups and many processes

- One `RunWatcher` per `(workspace, run)` holds the newest run row its streams have seen
  and counts its changes. Each stream's own read seeds it, so it is never older than a
  subscriber's snapshot.
- The run store's post-commit hook (`hub.notify`, registered by the lifespan) pokes the
  watchers of that run id in every workspace, from the committing thread. Each watcher
  then reads its own row.
- Watchers also read their row every 500 ms, so commits by other processes or replicas
  arrive without the hook.
- A stream notes the watcher's counter before it looks at the row and waits only while the
  counter is unchanged, so a change made before it waits is never missed.

## Access re-check

- Every wake checks `is_owner` on the watcher's row.
- Every 60 s, when the caller proved an account generation (accounts mode), the stream
  calls `still_valid(viewer)` on the stream pool. The lifespan wires it to
  `auth_provider.accepts_account_generation(user_id, generation)`, which reads uncached: a
  deleted account or a moved generation answers no. A no, or an error, ends the stream;
  its reconnect is refused (401 for a deleted account).
- A provider without `accepts_account_generation` answers no: the stream fails closed and
  ends at its first re-check.
- The 5-minute lifetime bounds every other revocation, such as an expired token or a
  header proxy that stops vouching for the user.

## Response, caps and pools

- `CoralEventStream` sends each event under a 30 s timeout. A client that stops reading
  ends the response; its slot is freed. The whole response runs at most 330 s (the
  lifetime plus one send) as a backstop. However it ends, it closes the stream and frees
  its slot.
- A slot no response claims within 10 s is freed.
- Caps: 8 streams per run and user, 32 per user in one workspace, 200 per process. Opening
  loads: 4 per user at once, counted until their thread call ends. Connects: 8 at once,
  then 1 a second, per user and run. The user is the normalized owner and account
  generation.
- Reads run on the `coral-stream` pool (8 threads): the opening load, its projection and
  frame encoding, each page of rows, the watchers' reads and the re-check.

## Client rules

- Keep the view from the last `snapshot` and apply each entry's patch in seq order. Each
  entry's seq is the last one plus 1.
- Reconnect with `Last-Event-ID` set to the last seq applied. Every stream ends within 5
  minutes, and a stream without `[DONE]` is not an error.
- **A patch that does not apply means: reconnect without `Last-Event-ID`.** The server never
  applies rows up to its snapshot seq, so a replaying client can meet a stored patch the
  server did not check. This happens only with corrupt data.
- On `resync`, drop the view and take the `snapshot` that follows.
- `RunHeader.version` in a `run` frame is the row version when the header last changed. Use
  the entries' `run_version`, or the snapshot's, for the current row version.
- In replay mode the opening `run` frame is the header at the snapshot head, so it runs
  ahead of the rows from the cursor up to that head.
- A native `EventSource` gives up after any non-200 answer, such as 429 or 503. Retry these
  yourself and honour `Retry-After`, or poll `GET /runs/{id}/log?after_seq=<last seq>` and
  the detail instead.

## The web client

The run view ([`runs-api.md`](runs-api.md), "In the web app") follows a run through
`web/src/workflows/stream/`: `sseParser.ts`, `viewPatch.ts`, `frames.ts`, the controller in
`runStream.ts` and the hook in `useRunStream.ts`. It keeps the client rules above, as
built:

- **Transport.** A streamed `fetch` through `authenticatedFetch`, not `EventSource`, so
  refusals and `Retry-After` are read; the app's 45 s stall guard. Its own parser keeps
  `id:` and caps an event at 8 MiB. Frames are checked by zod guards, but the patch applier
  works on the raw `JSON.parse` value: zod drops unknown keys and `__proto__`.
- **Patches.** `applyViewPatch` gives the same result or refusal as
  `coral/runview/patch.py` on every case in `viewPatch.contract.json`, which
  `tests/coral/runview/view_patch_contract.py` writes from the Python applier and the
  recorded run's patches. It refuses more, cases a real `RunView` never meets: the tokens
  `__proto__`, `constructor` and `prototype`, a pointer of more than 16 tokens or 1,024
  characters, a patch of more than 10,000 ops. Every token needs an own key or a valid
  index; containers are copied on write and the input never changes.
- **Frames.** A `snapshot` replaces the view, header and seq. An entry at the held seq or
  below is ignored, the next one applies, and a gap reconnects fresh; an unloadable run's
  entries move the seq without a patch. A `run` frame applies at once, unless its `version`
  is below the held header's, so during a replay the pill can lead the canvas. On `resync`
  the view stays on screen until the snapshot. `[DONE]` stops the stream and frees its
  slot. Unknown types are ignored. A snapshot of a newer `protocol` or `view_version` stops
  streaming for good: the page says "This page is out of date. Reload it for live
  updates." and polls the detail.
- **Reconnects.** `Last-Event-ID` is the last seq held. A patch that does not apply, a
  gap, an event over the cap or a malformed frame reconnects without it, keeping the view
  on screen. A body that ended after frames (the 5-minute end) reconnects after the
  shortest backoff; one that ended with none counts as a failure, so the empty 200 for an
  unknown row code never loops fast. A 404 says "Run not found or you don't have access";
  401, 403 and 422 stop, with Retry. A 429 or 503 waits its `Retry-After`, capped at 60 s,
  or the backoff if longer, keeping the slot; three in a row switch to limited mode. Other
  failures back off (`awaitReconnectDelay`).
- **Connection budget.** A page holds at most one of the origin's stream slots. With none
  free it disposes one of this tab's background chats (`conversationRegistry.
  evictLruEvictable()`, which never takes the conversation on screen, an open drawer's
  session or one with unsent work) and tries again every 200 ms, five times. Then "Live
  updates limited": the detail every 5 s, the stream again every 30 s with one more
  eviction, resuming with `Last-Event-ID`. A page hidden for 30 s gives its slot back and
  resumes when shown; a page opened hidden takes no slot until then. A slot granted after
  the page stopped is handed back at once.
- **Cache.** The hook writes each state under `["coral-run-view", scope, runId]`, the
  key's only writer, without structural sharing (which would turn an own `__proto__`
  member into a prototype). A remount within 5 minutes resumes from it with
  `Last-Event-ID`. In limited mode the detail read lands in the detail's key. On `[DONE]`
  the hook invalidates the run's detail.
- **Proof.** `stream/runStream.test.ts` and `stream/useRunStream.test.tsx` drive the
  controller over the live recording in `runView.contract.json` (one stream read while
  the run went through both gates, a pause and a resume, written by
  `tests/coral/api/run_view_contract.py`): a stream dropped after the first gate resumes
  with `Last-Event-ID` and applies every seq once, in order; every path holds at most one
  slot and releases it. `stream/viewPatch.test.ts` runs every patch case.

## OpenAPI and TypeScript

- The checked-in `coral/api/openapi.json` gives the stream's 200 only as
  `text/event-stream` with `$ref: RunStreamFrame`, and holds `RunStreamFrame`, its five
  frames and `RunHeader`. The exporter adds them and fails if one differs from a schema
  FastAPI already wrote.
- The generated TS operation `coral_stream_run` has `response: never` and
  `events: RunStreamFrame`, the type of each event's data.
- The running server's own `/openapi.json` lists the stream route with that `$ref` but no
  `RunStreamFrame` component, and with FastAPI's `application/json` beside it. Use the
  checked-in spec.

## Restart

The hub holds nothing durable. Seqs are assigned under the run row's lock, gapless and in
order. A client that reconnects to any process, after a restart or not, with
`Last-Event-ID = n` gets exactly rows `n+1` up to the head, then the live rows.

## Proof

- **Replay from `Last-Event-ID`:** `tests/coral/omni/test_runs_end_to_end.py` follows a run
  live through the real route and lifespan with authentication off, header auth and
  accounts; after the end it reads the stream again from the snapshot's seq, by
  `Last-Event-ID` (sent with `after_seq=0`, which it beats) and by `after_seq`, and applying
  those entries to the snapshot gives the final view.
  `test_a_restart_resumes_a_stream_from_last_event_id_with_no_gap_or_repeat` exits the
  lifespan with a stream open, commits while no server runs, enters a new lifespan on the
  same database and resumes with `Last-Event-ID`: every row once, in order, then `[DONE]`.
  `tests/stores/coral/test_run_stream_restart.py` does the same on every database lane.
- **The rest:** `tests/coral/api/test_run_stream.py` drives the loop directly: resyncs,
  unreadable rows, wake-ups, heartbeats, the lifetime, the re-check, caps, send timeouts,
  and workspaces that share a run id.
- **Account deletion:** in `test_runs_end_to_end.py` a deleted account's open stream ends at
  its next re-check and its reconnect is 401.

## Residuals

- **The in-band shutdown mark.** Streams end, and new ones are refused with 503, while
  Omnigent's `server_shutting_down()` holds. A runner tunnel closing with code 1012 sets
  that mark too, for 150 s. So one authenticated runner closing with 1012 pushes every
  stream on its replica to polling for 150 s, and can repeat it. Telling the explicit mark
  from the in-band one would need an Omnigent seam.
- **A run row with an unknown status or pause-reason code** ends each stream with an empty
  200. An `EventSource` reconnects into it, slowly: each reconnect is one load, bounded by
  the connect rate and the load cap, and logged once.
- **Row codes are not forward-compatible across a rolling deploy.** A row a newer server
  wrote with a code this one does not know resyncs past it (log rows) or ends the stream
  (run rows).
- **The per-user cap is per workspace,** so a user with runs in several workspaces gets 32
  streams in each. The 200 per process still holds.
- **Caps, watchers and connect buckets are per process.**
- **A cut client logs an uvicorn ERROR.** After a send timeout or the backstop the response
  is left incomplete. uvicorn logs "ASGI callable returned without completing response." at
  ERROR for each such client, and closes the connection.
- **The live `/openapi.json` has a dangling `RunStreamFrame` `$ref`** (above).
- **The web client is not checked in a browser** (the repository's rule): that
  `authenticatedFetch` and the dev proxy pass `Last-Event-ID` unchanged, and that real Web
  Locks slots behave as the tests' counting slots, are left to a manual check.
- **A hostile server can stall the tab.** Each array op costs the array's length, so a
  10,000-op entry on a huge array takes about a second; the event cap bounds it. Real
  views are graph-sized.
- **Limited mode after the end.** A finished run seen only through limited mode stops
  reading its detail, but still tries the stream every 30 s to collect `[DONE]`, and each
  try may dispose one of this tab's background chats while other tabs hold every slot.
  Each limited detail read is cut at its 5 s tick, so a server slower than that never
  updates the page.
- **An out-of-date page never sees `[DONE]`,** so a run that ends while it is open is not
  marked read on open ([`gates-and-inbox.md`](gates-and-inbox.md)).
- **Handing slots back has no bound.** A new slot request waits for this tab's releases;
  Web Locks releases settle, so this is liveness hardening left undone.
