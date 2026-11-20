# Contracts K14, K19 and K7 (subsets): gates, run alerts and the workflow Inbox

- **Status:** Draft v1, live. A gate visit the engine opens is shown as one
  prompt on its run's anchor and one open alert in the owner's workflow
  Inbox; the run owner's answer advances the engine once.
- **Code:** ids, the live rule and lookups in `coral/gates/ids.py`; the
  prompt in `coral/gates/prompt.py`; delivery in `coral/gates/executors.py`;
  answers in `coral/gates/verdict.py`; the republisher in
  `coral/gates/republish.py`; the prompt sweep in `coral/gates/sweep.py`;
  gate rows in `coral/bridge/gate_rows.py`; `EngineBridge.answer_gate` in
  `coral/bridge/service.py`; alert rules in `coral/alerts/rules.py` and
  payloads in `coral/alerts/types.py`; the alert store in
  `coral/stores/alerts.py`; the Inbox routes in `coral/api/inbox.py`; the
  runs API's answer route in `coral/api/runs.py`; the
  Omnigent adapter in `coral/omni/server/gates.py` and
  `coral/omni/server/access.py`; wiring in `coral/omni/server/plugin.py`; the
  web Inbox kind, its cards' Resume and Cancel, and notifications in
  `web/src/workflows/inbox/` and
  `web/src/workflows/notifications/`, mounted by
  `web/src/workflows/CoralRuntime.tsx`.
- **Related:** [`session-facade.md`](session-facade.md) (the bridge's work
  rows, run protection), [`runs-api.md`](runs-api.md) (the runs API, its
  gate answers and its actions), [`persistence.md`](persistence.md) (`coral_0005`),
  [`plugin.md`](plugin.md) (wiring and routes),
  [`../decisions/ADR-05-topology.md`](../decisions/ADR-05-topology.md)
  (probe (e), probe 15).

## One gate end to end

1. A commit opens visit V. In the same compare-and-swap it writes V's
   `coral_gate_visits` row (`OPEN`, a new random prompt id,
   `elicitation_session_id` = the anchor), raises V's gate alert carrying that
   prompt id, and queues a `gate_publish` row.
2. The drainer runs `gate_publish`: it shows V's prompt on the anchor with
   the row's prompt id, reads the run again and withdraws the prompt if V
   closed meanwhile.
3. The owner answers through
   `POST /v1/sessions/{anchor}/elicitations/{id}/resolve` (or an `approval`
   event), or through the runs API's
   `POST /v1/coral/runs/{run}/gates/{node}:answer` with the visit's token.
   The verdict handler checks the anchor (on the prompt route), the owner and
   the visit, then commits `AnswerGate` through `EngineBridge.answer_gate`.
   That commit resolves V's row and its alert and queues the next work.
4. A repeat of the same answer is a duplicate with no second commit: 202
   `duplicate` on the prompt route, 200 `{"result": "duplicate"}` on the runs
   route.
5. After a restart the lease holder shows every open visit's prompt again
   from its row, with the same id and params. The alert never left the feed.

`tests/coral/omni/test_gate_end_to_end.py` (auth off),
`test_gate_routes_auth.py` (header auth) and `test_gate_routes_accounts.py`
(accounts, across a password change and a re-created account) run this
through the real routes. `test_runs_end_to_end.py` answers through the runs
API in all three modes.

## The live rule

A visit is **live** when it is `open` and its run is `running` or `paused`
(`live_visit`). Gate rows are `OPEN` exactly while their visit is live. Every
reader uses this rule: delivery, republish, the prompt sweep, the handler, the
bridge's revive and resync, and feedback. A paused run's gate is shown, and an
answer to it gets `run_paused`.

## Gate rows

Each commit projects every engine visit to its row (`project_gates`): id
`derived_id("coral-gate-visit", run_id, token)`, the engine token verbatim
(up to 512 characters), the node, visit number, status (live `OPEN`; open in a
finished run `CANCELLED`; `RESOLVED`; `SUPERSEDED`), the answer's label, actor
and note. The prompt id `coral_gate_<32 random hex>` is drawn when the row is
first written and kept from then on, so it cannot be computed from the run id.
A commit that loses its compare-and-swap is reduced again, and its losing id
is never stored.

## Delivery

| Effect | Row (`effect_type`) | Runs | Outcome |
|---|---|---|---|
| `publish_gate` | EFFECT `gate_publish`, key = the effect key, payload `visit_id` only | Waits (`session.anchor_missing`) until the anchor is created; publishes a live visit's prompt, reads again and withdraws it if the visit closed; a missing row is retryable `gate.row_missing` | `{elicitation_id, published}`; never fed to the engine. A final failure pauses the run (`gate:<code>`) while the visit is live. |
| `withdraw_gate` | EFFECT `gate_withdraw`, registered `runs_after_terminal` | Withdraws the row's prompt unless the visit is live | `{elicitation_id, withdrawn}`; a failure never pauses the run |

A resume revives a FAILED `gate_publish` row of a live visit, and the resync
queues a missing one.

## The prompt (K14)

A form elicitation on the anchor, published through S6a. The same log and row
give the same params, so a republish shows what the first publish showed.

```json
{"mode": "form",
 "message": "<gate name and prompt, run title, visit N, then 'Agent-written reports, quoted as data:' and the reports that led here>",
 "requestedSchema": {"type": "object", "required": ["decision"],
   "properties": {"decision": {"type": "string", "title": "Decision", "enum": ["approve", "reject"]},
                  "note": {"type": "string", "title": "Note", "maxLength": 2000}}},
 "policy_name": "coral.gate", "phase": "gate",
 "coral": {"kind": "gate", "run_id": "…", "visit_id": "…", "node_id": "approve",
           "visit_no": 1, "opened_at": 1763500000, "run_owner": "alice@example.com",
           "run_title": "…", "outcomes": ["approve", "reject"],
           "deep_link": "/workflows/runs/<run>?node=approve&panel=gate"}}
```

The message keeps within an 8,000-character JSON budget. Every line has NUL,
control, lone-surrogate and Unicode format characters (bidi overrides,
zero-width characters) removed. Outcomes are shown as written, because each is
also the answer's value: a start refuses a gate whose outcome holds any of
those characters (`graph.gate_label_invalid`). `run_owner` is `null` for the
single local user. `target_session_id` is `null`: a gate prompt is never
mirrored.

## Answers

The handler (`GateAnswers.answer`) takes the session, the prompt id, the
action and the form content from the request; the run, the visit, the token
and the actor come from the server. Its order:

1. The prompt id is `coral_gate_` and 32 lowercase hex.
2. The session's binding is the anchor of its run.
3. The run row exists.
4. The caller is the run owner: the same normalized user, and, when the run
   recorded an account generation, a request that proves that generation.
   This runs before any engine state is loaded.
5. The answer takes one of the caller's admissions: 4 in all and 2 per user
   (normalized owner and generation), shared by both answer routes. Past
   either it is refused `run_busy`, "Too many gate answers at once; try
   again.", before anything is loaded.
6. The run's engine state loads. A run that cannot be loaded answers
   `no_longer_waiting` when it has ended, else `run_paused`.
7. The run's row holding the prompt id names a visit of that run.
8. The label: `accept` with `content.decision` among the gate's outcomes;
   `accept` with no decision on an approve or approve/reject gate is
   `approve`; `decline` on a gate with `reject` is `reject`. A `note` is text
   of at most 2,000 characters.
9. A visit that is not live is classified without the engine; a live one is
   committed once through `EngineBridge.answer_gate`.

| Result | Status | Body or message | Drops a still-pending local prompt |
|---|---|---|---|
| accepted | 202 | `{"queued": false}` | the resolved event clears it |
| duplicate (same label already recorded) | 202 | `{"queued": false, "duplicate": true}` | yes |
| `not_permitted` | 403 | "Only the run owner can answer this gate." | no |
| `no_caller` (a direct resolver call that names no caller; no route makes one) | 403 | "Only a request that names its caller can answer this prompt." | no |
| `already_answered` | 409 | "Already answered: <label>." | yes |
| `stale_visit` | 409 | "This gate was asked again; answer the latest one." | yes |
| `no_longer_waiting` | 409 | "This gate is no longer waiting." | yes |
| `run_paused` | 409 | "The run is paused; resume it, then answer." | no |
| `invalid_answer` | 409 | "Choose one of: <outcomes>." or the note rule | no |
| `run_busy` | 409 | "The run is busy; try again." (also: too many answers in flight, or gates closing at shutdown) | no |

Refusals travel as `"[<reason>] <text>"` in Omnigent's error message.
`not_permitted` is logged at INFO with the run, prompt and actor ids. Logs
never carry a note or the answer's content. One answer takes at most 30 s in
all; past that, or on an error on the way, it is refused `run_busy`.
The prompt route refuses a note holding NUL or lone surrogates: "The note must
not hold NUL or unpaired surrogate characters."

**The runs API's answer route** (`GateAnswers.answer_visit`) takes the run, the
gate's node id, the visit's token, an outcome and a note. Its owner check comes
first, in the runs API (`owned_run`), and again on the run row; then the
admission; then the load, the owner on the loaded row, and the visit, whose
gate must be the named node. `outcome` is the label only when it is one of the
gate's outcomes, and the closed-visit checks run before `invalid_answer`, as on
the prompt route. It answers 200 `{"result": "accepted" | "duplicate"}`; no
such visit and `not_permitted` are the runs API's one 404; `stale_visit` is 409
`stale_visit`; `already_answered`, `no_longer_waiting` and `run_paused` are 409
`illegal_transition`; `invalid_answer` is 422 `validation_failed`; `run_busy`
is 503 `server_busy`, with `details.reason` on each refusal
([`runs-api.md`](runs-api.md), "Gate answers"). After an answer that closes the
visit it withdraws this process's prompt; other replicas' prompts go with
their sweep.

## Restart, republish and the prompt sweep

Prompts live in the memory of the process that published them.

- **Republish.** On taking the worker lease, the startup sweep groups each
  page of `OPEN` rows by run and republishes four runs at once, each in its
  run scope with a 10 s bound; a failure or timeout is counted for that run
  and the others go on. Every resync tick republishes prompts this process
  lost. A prompt still pending here is never sent again, and a run whose
  anchor is not created yet is left to its `gate_publish` row. A graceful exit
  releases the lease, so the next start republishes at once; after a crash the
  prompts return only once the stale lease expires (120 s,
  `coral/workers/worker_lease.py`). Meanwhile each gate's alert still lists it
  in the Inbox, and its card answers through the anchor.
- **Sweep.** Every process, leader or not, tracks the gate prompts it
  publishes (`LocalGatePrompts`, an S5 observer, at most 10,000) and each
  minute withdraws any that is not a live visit of its session's run. It reads
  each such run's `OPEN` gate rows once (`list_open_gates`, on
  `ix_coral_gate_visits_open`), which are exactly its live visits, and loads no
  engine state. It covers an answer handled on another replica, a commit whose
  reply was lost, and a missed withdraw.
- **Answers need no prompt.** The handler finds the visit through the run's
  rows, so an answer works during a republish and on any replica.

## Run alerts (K19)

Alerts are computed in every bridge commit (`commit_alerts`) and in a
store-only pause (`row_pause_alert`), and written in the same transaction as
the engine entry. A raise is insert-if-absent by a derived id; a resolution
never reopens a row.

| Trigger | Action | Kind | Priority |
|---|---|---|---|
| A gate row becomes `OPEN` | raise | `gate` | normal |
| A gate row leaves `OPEN` | resolve | | |
| The run row pauses for any reason but `user`, or a run paused for `user` gains another cause | raise | `pause` | normal |
| The run row leaves `paused` | resolve | | |
| An accepted watchdog `notify` at its alert stage for an open decision | raise | `watchdog` | normal |
| That decision is decided | resolve | | |
| The run row completes, fails or is cancelled | raise | `run_completed`, `run_failed`, `run_cancelled` | low |
| The run row finishes | resolve every `gate`, `question`, `pause` and `watchdog` alert of the run | | |

Gate watchdogs, reminder stages and `notify {pause}` or `{run_cancelled}`
raise nothing. The kinds `question`, `overdue` and `reaction` are reserved:
nothing raises them.

**Payloads** (`AlertPayload`): a title, a message, the run title, the step
label and node, the actions (`answer`, `open_run`, `mark_read`; `resume` and
`cancel` are reserved for the runs API), a deep link built from ids, the
prompt id and anchor of a gate, the gate's outcomes and a pause's reason. A
binary gate also gets `approve_link` `/approve/<anchor>/<prompt id>`. Free
text is cleaned like the prompt and cut with "…" to its cap. Payloads hold no
agent-written report text, tokens or host paths.

## Workflow Inbox (K7 subset)

Mounted at `/v1/coral` by the Coral plugin. Refusals use the Coral error
shape, `{"error": {"code", "message", "details"}}` ([`runs-api.md`](runs-api.md),
"Errors"); the statuses are unchanged. The caller is resolved in the
request's task: 401 `unauthenticated` "Authentication required" when the
server's provider finds no user, 403 `not_permitted` "Not permitted" when the
account context names another user or no identity is given where one is
required. Without the alert store (no operational database) both routes answer
404 `not_found` "Coral inbox is not available".

- **`GET /v1/coral/inbox?limit=1..100&after=<cursor>`** → 200
  `{"data": [...], "next_cursor": ...}`, `Cache-Control: private, no-store`.
  The caller's open alerts in the request's workspace: normal priority
  first, newest first within each, by `(priority, created_at, alert_id)`.
  Each item is the alert row merged with its payload (`alert_id`, `run_id`,
  `run_title`, `kind`, `priority`, `created_at`, `title`, `message`,
  `step_label`, `node_id`, `actions`, `deep_link`, `approve_link`,
  `elicitation_id`, `session_id`, `outcomes`, `pause_reason`). The cursor is
  `<1|2>:<created_at>:<32 hex>`, else 422 `validation_failed` "Invalid
  workflow inbox cursor". Rows of a look-alike owner (a database collation can
  fold case or accents) or of another account generation are dropped after
  paging, so a page can be empty and still carry
  a cursor: clients page until `next_cursor` is `null`. An unreadable payload
  is skipped and logged once.
- **`POST /v1/coral/inbox/{alert_id}/ack`** with the JSON body `{}`
  (`application/json`; any other body or media type is 422, so a cross-site
  form cannot post it) → 204 for a marked or already-marked alert; 404
  `not_found` "alert not found" for another user's, another generation's, an
  unknown or a malformed id; 409 `illegal_transition` "Answer the gate to clear
  this alert." for an open gate alert.

Admins see only their own alerts. The owner is stored normalized (the single
local user is `null`) and compared exactly.

**In the web app.** When `GET /v1/coral/info` reports Coral, the web runtime
registers the `workflow` Inbox kind (S37). It loads the whole feed, up to 10
pages (1,000 alerts, then the badge count is marked incomplete), every minute
and whenever a run anchor's pending count changes. It claims a `coral_gate_`
prompt only on a run anchor and only when it is aimed at the anchor itself, so
a mirrored or forged prompt stays an ordinary approval. Each gate is one card,
its prompt joined with its alert by prompt id. A gate alert without a prompt
is still a card that answers through the anchor's resolve route. Every other
alert is a card with "Open run" and "Mark as read". The sidebar badge adds the
normal-priority alerts that no anchor's pending count already counts. While
the app is open, a gate notifies once, from its alert; a step prompt mirrored
onto the anchor notifies once; other alerts notify at most once per run every
10 minutes. Without Coral nothing registers, and a gate prompt shows as an
ordinary approval that still answers.

**Resume and Cancel on a pause card** (`RunActions.tsx`, through
`web/src/workflows/api/runsApi.ts`). Only a `pause` alert's card has them, and
only while it is expanded, which is when it reads the run:
`GET /v1/coral/runs/{id}` under the query key `["coral-run", run_id]`, fresh for
10 s, and retried once only for a failure a retry can fix (never a 404).

- **Resume** (primary) and **Cancel run** (outline) appear only when the run's
  `allowed_actions` list them. Pause is never offered here. "Open run" is an
  outline button on this card, so Resume is its one filled button. A run that
  cannot be loaded shows Cancel only; a finished run shows neither; a failed
  read shows neither and keeps "Open run".
- **Cancel run** opens an inline question, "Cancel this run? Its steps stop.",
  with **Cancel run** (destructive) and **Keep running**. Only the question's
  Cancel run posts. Keep running, or Escape, closes it. A reread that no longer
  offers Cancel closes it for good.
- Resume posts `{}` to `:resume`; the question's Cancel run posts `{}` to
  `:cancel`. On success the card patches the cached run's `status` and
  `allowed_actions`, rereads the run and the Inbox, and says "Resumed.", "The
  run is still paused." (a resume that left another cause) or "Cancelled." in
  its `aria-live="polite"` status line.
- Errors: a 409 with Coral's error shape shows the server's message and
  rereads the run, but not the Inbox; a 404 says "This run is no longer
  available." and rereads the run, which hides the buttons; a 503 says "The
  server is busy; try again."; anything else says "Couldn’t update the run.".
- Both buttons are disabled while an action is in flight, also on a card
  reopened meanwhile (the actions share the mutation key
  `["coral-run-action", run_id]`), and while offline, with "You’re offline."
  beside the result.

## Account generations

A run and its alerts record the owner's account generation, and only a
request that proves it answers the run's gates or lists its alerts. A password
change or an admin reset rotates the generation; Omnigent moves the account's
registration work to the new one in the same transaction, and Coral's carrier
(S106, `coral/stores/registration.py`) moves every Coral row the user owns at
the old generation with it: runs (finished ones too), their alerts, and
`coral_workflows` rows in the operational database (none records a generation
yet; the workflow definitions the routes serve live in a separate file). A
moved run gets a new version, so a commit that read it before the move is
reduced again with the new generation. The carrier is registered while Coral's
lifespan runs on the operational database. If it fails, the password change
fails and nothing moves: a savepoint could isolate the carrier, but Coral
aborts instead so a run never silently loses its owner (the old generation is
recorded nowhere else to repair from). Deleting and re-creating an account
starts a new registration: it sees none of the old one's alerts, and its
answers to the old runs' gates are refused. Omnigent answers 404 first, since
the deletion removed the account's grants on the anchor; if a grant survived,
the gate handler answers 403 `not_permitted`, since the request does not prove
the generation the run recorded.

## Seams

Every change to an Omnigent file is a ledgered seam in `.coral/seams.yaml`
with a row in `MODIFICATIONS.md`; all seven are Coral-owned.

| Seam | Files | What it adds |
|---|---|---|
| S5 | `omnigent/runtime/pending_elicitations.py` | Observers beside the primary slot, replaced as a whole tuple; a raising observer is logged and stops no other observer and no delivery |
| S6a | `omnigent/server/elicitation_hooks.py` | `publish_form_elicitation` and `withdraw_elicitation`: a prompt with no request behind it, for ids a handler claims; never mirrored to ancestors |
| S6b | `elicitation_hooks.py`, `_sessions/orchestration.py`, `routes_elicitations.py`, `routes_events.py` | Verdict handlers by id prefix: a claimed id is answered by its handler alone, with the route's caller; a call that names no caller is refused; `elicit_` stays Omnigent's |
| S37 | `web/src/lib/inboxKinds.ts`, `InboxPage.tsx`, `useSidebarData.tsx` | Inbox extension kinds: a kind claims prompts, renders its own cards and adds to the badge |
| S36 | `web/src/hooks/useIdleNotifications.ts` | The idle notifier skips rows a kind silences |
| S85 | `web/src/main.tsx` | Mounts Coral's web runtime, which renders nothing without Coral |
| S106 | `omnigent/server/accounts_store.py` | Registration carriers: a password change's rotation transaction also calls them, so Coral's runs and alerts keep their owner's generation; an error aborts the rotation |

## Residuals

- **Servers that require no identity.** With authentication off, or a
  single-user header server, every request without credentials is the local
  user, so any process of that user that can reach the server (a step shell
  the sandbox lets reach loopback or the server URL, or the `omnigent` CLI)
  can read the prompt and answer the gate as the owner; with a single-user
  server bound to a non-loopback address, so can any network peer. Nothing on
  the server can tell such a process from the person. The random prompt id
  stops blind requests (cross-site, guessing), not a process that can read
  the anchor.
- **Same-user steps on authenticated servers.** A step whose shell the
  sandbox does not confine can mint an owner token from its runner's
  environment, so an owner-authenticated answer does not prove a person took
  it ([`session-facade.md`](session-facade.md), "Same-user steps").
- **A step that shadows or clears the anchor's prompt** cannot answer the
  gate: answers on any session but the run's anchor are refused, the web
  Inbox's workflow kind claims only anchor prompts, and the sweep withdraws
  non-live prompts. The alert still answers through the anchor.
- **One index per process.** Only the lease holder republishes; each process
  sweeps its own prompts. A replica that loses the lease keeps a live visit's
  prompt until the visit closes.
- **Unclaimed ids on the anchor.** While gate answers are admitted, an
  approval for an id no handler claims takes Omnigent's path on the anchor:
  202, and a step prompt mirrored onto the anchor is dropped there without
  being answered. Only the owner or an admin can post it.
- **Answers at shutdown.** An answer admitted just before exit is told to
  retry (`run_busy`); one whose task resumes after the handler is removed
  takes Omnigent's path (202, nothing committed), and the next start shows
  the prompt again.
- **Carrier faults block password changes.** Any fault in Coral's carrier
  (schema drift, missing table privileges, a lock timeout, CockroachDB retries
  running out) fails every password change and admin reset on that server
  until it is fixed or Coral is unloaded. Deleting an account still revokes
  its access: deletion calls no carrier. The carrier assumes the account store
  shares Coral's operational database, as `omnigent server` sets it up; an
  embedder that keeps accounts in another database fails every password change
  on Coral's missing tables.
- **Carry size.** The carry rewrites every row the user owns at the old
  generation under the account lock, finished runs and resolved alerts
  included, so a long-lived heavy user makes a large rotation transaction;
  alert retention (DUR-06) bounds it.
- **Run-end alerts accumulate** until marked read; they are listed after
  normal alerts. A watchdog alert on a decision that closes without being
  decided stays until the run ends. A paused run whose reason changes between
  two non-user reasons keeps its first alert's text.
- **The badge can miss a gate for a while.** The badge leaves out a gate
  alert whenever its anchor reports any pending prompt. If that count comes
  only from a mirrored step prompt while the gate's own prompt is missing
  (after a crash, until the republish), the gate is not counted until its
  prompt returns. The Inbox page still lists it.
- **Shared answers pool.** Answers use the bridge's thread pool with the
  drain's feedback; a burst queues behind drain work (four at a time, two per
  user). The prompt route's binding and run-row reads run on that pool before
  the admission; they are single-row reads by callers who already reach the
  anchor's prompt route.
- **An answer to a running run that cannot be loaded** pauses its row
  `failure_path` (the load does, as every bridge write does), and answers any
  token, an unknown one included, `run_paused` rather than the runs API's 404.
  Only the owner gets that far.
- **The Inbox's run cache is shared and unscoped.** The key
  `["coral-run", run_id]` names no viewer or server; scope it, or clear it when
  the viewer changes, before the run view (CRL-136) shares it. After an action
  the cached run holds the new `status` and `allowed_actions` but the old
  `pause_reason`, causes and view until the reread lands.
- **A resumed or cancelled pause card leaves the list.** The action resolves
  its alert, so the next Inbox read drops the card, and its status line and
  focus go with it. The line is announced first. A card reopened while its
  action is in flight shows no result text; its buttons follow the reread.

## Enforced gates

No gate is labelled Enforced. A gate may be labelled Enforced only when
the sandbox probe in ADR-05's follow-ups passes and the server runs a mode
that requires identity, in which steps hold no owner credential. Gates on
single-user or auth-off servers are never Enforced.

## Deferred work and owners

| Work | Owner |
|---|---|
| The run view, marking a run's alerts read when it is opened, bulk ack (`POST /v1/coral/inbox/ack`); scoping the `["coral-run", id]` query key to the viewer | CRL-136 |
| The sandbox probe also tests, from the step shell, HTTP to the Omnigent server on loopback and the configured URL, with no credentials and with the CLI's stored credentials | CRL-137 |
| Label gates Enforced under the rule above | RUL-02 |
| Retention of marked-read and resolved alerts | DUR-06 |
| External delivery (webhook, email, push), batch gates, team approvers, questions and budget prompts | GTE-03, GTE-04; no live ticket |
| Multi-label gates on `/approve` (their `approve_link` is unset) | no live ticket |
