# Contract K7 (subset): Simulate and workflow templates

- **Status:** Draft v1, live. A signed-in caller can dry-run any workflow text on the real
  engine with stub sessions, list the built-in templates, and make their own copy of one.
  A simulation reads and stores nothing; using a template only ever inserts.
- **Code:** the simulator in `coral/engine/simulate.py` and its saved cases in
  `coral/engine/simcase.py` (pure tier); the template registry and its package data in
  `coral/templates/`; the simulate route in `coral/api/workflows.py`; the template routes
  in `coral/api/templates.py`; schemas in `coral/api/schemas.py`; the insert-only `create`
  and `workflow_keys` in `coral/stores/workflows.py`; the simulate pool in
  `coral/omni/server/plugin.py` (`simulations_lifespan`) over `InFlight` in
  `coral/api/run_service.py`; the shared activation cap `DEFAULT_RUN_ACTIVATIONS` in
  `coral/bridge/config.py`; the web client in `web/src/workflows/api/client.ts`, the
  desk's Templates tab in `web/src/workflows/desk/`, and the editor's Simulate panel in
  `web/src/workflows/simulate/` and `web/src/workflows/editor/`.
- **Related:** [`runs-api.md`](runs-api.md) (the other workflow routes, preflight's
  estimate, the `InFlight` pattern), [`evidence.md`](evidence.md) (done-when checks),
  [`plugin.md`](plugin.md) (wiring).

## Routes

Every route is under `/v1/coral`, tagged `coral`, and needs a signed-in caller
(`request_viewer`: 401 `unauthenticated`, 403 `not_permitted`). Refusals use Coral's
`{"error": {"code", "message", "details"}}` envelope, and a POST must be JSON.

| Method and path | `operationId` | Body | Success | Refusals |
|---|---|---|---|---|
| `POST /workflows:simulate` | `coral_simulate_workflow` | `SimulateRequest` | 200 `SimulatedResult` or `InvalidResult` | 401, 403, 422, 503 |
| `GET /templates` | `coral_list_templates` | none | 200 `TemplateOut[]` | 401, 403 |
| `POST /templates/{template_id}:use` | `coral_use_template` | `EmptyRequest` (`{}`) | 201 `SavedWorkflowOut` | 401, 403, 404, 409, 413, 422 |

The routes are additive (`CORAL_API_VERSION` stays `"1"`) and are in
`coral/api/openapi.json` and `web/src/workflows/api/generated/coralApi.ts`
(`just coral openapi`).

## Simulate's model

`simulate(graph, script, *, max_activations, max_transitions, max_work)` runs a compiled
graph on the real reducer, `transition()`, with one fixed clock value. Every log entry
comes from `transition`. Simulate never changes engine state itself; it only feeds inputs:

- `StartRun`, then `EffectCompleted` for each stubbed effect;
- for a step, `HandoffReceived` and `HandoffEvaluated` (`accepted` or `evidence_missing`);
- `ChooseArrow` for a decision and `AnswerGate` for a gate.

What a person, an agent or the orchestrator would supply (a label, a done-when result, a
choice, a gate answer) comes from the script. When the script runs out, Simulate stops and
asks (`needs_input`); it never guesses. `simulate()` raises `ValueError` for a graph with
unresolved facts; callers validate first.

### Effects

Every effect kind is in exactly one table (`classify_effect`):

| Table | Kinds | What Simulate does |
|---|---|---|
| Stubbed (`STUBBED_EFFECTS`) | `create_session`, `send_input`, `close_slot`, `nudge`, `steer` | Acknowledges it at once, oldest first, with the payload its executor would report: `{"pending_input": false}` for `close_slot`, `{}` for the rest |
| No-answer (`UNANSWERED_EFFECTS`) | `publish_gate`, `withdraw_gate`, `notify`, `arm_timer` | Nothing: a gate waits for its answer; alerts and timers report nothing |
| Unsupported (`UNSUPPORTED_EFFECTS`) | `retry_step`, `runner_lost`, `cancel_sessions`, `structure.start_item`, `structure.cancel_region` | Ends the simulation with outcome `unsupported`; `unsupported_effect` names the kind |

A kind in no table is unsupported too, so a new reducer effect fails closed. A test checks
that every kind the bridge knows is in one table and that the tables do not overlap.

### The driver

Each driver step takes the first action that applies:

1. Acknowledge the oldest stubbed effect not yet acknowledged.
2. Hand off the first slot in the run state whose status is `working`.
3. Choose for the first decision not yet decided.
4. Answer the first open gate visit.
5. If none applies, stop with `stalled`.

It runs while the run is `running`, nothing has stopped it, and no budget is spent. In a
parallel region the branch whose slot comes first in the run state goes first.

**A step's handoff.**

- A step with done-when commands needs a `done_when` value first (`pass` or `fail`).
- An accepted handoff (`pass`, or no done-when) of a step whose arrows route by label also
  needs a `label`. The allowed labels are the ones the reducer would take
  (`choosable_labels`).
- Every value a handoff needs is checked before any is consumed. If one is missing, the
  outcome is `needs_input` and nothing is consumed.
- `fail` sends `HandoffReceived` with no label, then `HandoffEvaluated(evidence_missing)`
  naming every done-when item. The result is `evidence_missing`, and the attempt spends one
  of the step's `attempts`, as in a real run ([`evidence.md`](evidence.md)). A label is
  consumed only by an accepted handoff.
- An accepted handoff's result is its label, or `done` when the step has none.

**A decision** takes its next `label` value (`ChooseArrow` with the activation's item and
iteration paths). **A gate** takes its next `gate` value; the allowed values are the
gate's outcomes.

### Scripts

`SimScript` is `{"inputs": [{"node_id", "kind", "values"}]}`, with `kind` one of `label`,
`done_when` or `gate`.

- Each `(node_id, kind)` pair has one FIFO queue. A node's activations and seats share it,
  in the order the driver reaches them; a loop's second pass takes the next value.
- Values for a node or kind nothing asks for are not an error. They are returned in
  `unconsumed`, in script order, with the values left over after the run ended.
- Bounds, refused with 422 (`validation_failed`) at the API:
  - at most 200 inputs, each `(node_id, kind)` once;
  - each input 1-100 values, 1000 values in all;
  - `node_id` 1-64 characters; each value 1-255 characters;
  - `done_when` values only `pass` or `fail`;
  - no C0 or C1 control characters, bidirectional controls or surrogates in a `node_id`
    or value. The message names the rule, never the value;
  - unknown fields are refused at every level.

**Script values are narrower than labels.** An authored arrow label or gate outcome is any
non-empty text. A runnable workflow whose label or outcome is over 255 characters, or holds
a control or bidirectional character, gets a `needs_input` whose allowed value the script
cannot carry: sent back, it answers 422. This is deliberate, since responses echo script
values. Real runs are no wider for gates: a gate answer's `outcome` is at most 128
characters with no control or bidirectional characters (`GateAnswerRequest`,
`MAX_GATE_OUTCOME_CHARS`), so a gate outcome over 128 characters cannot be answered in a
real run either.

### Outcomes

| `outcome` | When | Detail |
|---|---|---|
| `completed`, `failed`, `cancelled`, `paused` | The run stopped on its own | A pause's cause is in `view.causes`, for example `attempts_exhausted` or the activation cap |
| `needs_input` | A value the next action needs is missing | `needs_input`: `node_id`, `activation_id`, `kind`, `allowed_values` |
| `rejected` | The reducer refused a script value | `rejection`: `node_id`, `kind`, `value`, and the reducer's own `code` and `allowed_values`. A step label the step does not take is `handoff.invalid`; a decision label or gate value it does not take is `tool.illegal` |
| `stalled` | Nothing can advance, or the reducer refused an input Simulate made itself (an acknowledgement, an unlabelled handoff, an evaluation, the start) | `stall_code`: the reducer's code when it refused one, else `null` |
| `step_limit` | A bound ended the simulation | `limit` names it (below) |
| `unsupported` | An accepted entry emitted an unsupported or unknown effect | `unsupported_effect` |

A test runs every workflow fixture and every built-in template, answering each question,
and asserts none ends `unsupported`, `stalled` or `rejected`.

### The result

`SimResult` sends every field (all are required in the schema):

- `outcome` and `steps`: one `{node_id, activation_id, kind, result}` per answered step,
  decision or gate, in order;
- `loops`: one per loop counter, `{back_arrow_id, iteration_path, passes, limit,
  limit_hit}`; loop limits count passes;
- `gates_reached` (one per visit) and `limits_hit` (back arrows whose limit redirected),
  in order;
- `step_activations` and `sessions` (below);
- `needs_input`, `rejection`, `unsupported_effect`, `stall_code` and `limit`, each `null`
  unless the outcome sets it;
- `unconsumed`, the final `view` (the `RunView` a real run's detail shows), `trace_digest`,
  and `entries`, the log length with rejected entries included.

### Bounds

No single bound covers a simulation. These do, and the caller can set none of them: the
route passes `max_activations=DEFAULT_RUN_ACTIVATIONS` (100, the default run's cap) and
the engine's defaults.

| Bound | Value | Checked | Result |
|---|---|---|---|
| Seats on one step | 16 (`MAX_STEP_SEATS`) | before the run starts | `step_limit`, `limit: "step_seats"` |
| Seats on all steps | 64 (`MAX_GRAPH_SEATS`) | before the run starts | `step_limit`, `limit: "graph_seats"` |
| Nodes, arrows | 96, 192 (`MAX_SIMULATED_NODES`, `MAX_SIMULATED_ARROWS`) | before the run starts | `step_limit`, `limit: "graph_size"` |
| Transitions | 5000 log entries (`DEFAULT_MAX_TRANSITIONS`) | before each input; a handoff (two inputs) that would not fit starts nothing and consumes nothing | `step_limit`, `limit: "transitions"` |
| Work | 1 000 000 units (`DEFAULT_MAX_WORK`) | between driver actions | `step_limit`, `limit: "work"` |
| Activations | 100 (`DEFAULT_RUN_ACTIVATIONS`) | by the reducer | `paused`, the activation cap |

- The three caps checked before the run starts bound costs inside one transition, which a
  budget checked between transitions cannot stop: opening a step compares each of its
  seats with every slot so far, and a waiting AND join's liveness check walks the graph
  from every open branch. They are checked in the order above, and the seat caps count
  every step, reachable or not.
- Each applied input charges `state_size × max(1, receipts added) + nodes + arrows`, where
  `state_size` counts the run state's growing tables. The receipt weight charges a choice
  that skips many labelled arrows, which writes one receipt per arrow. The last action can
  overrun the budget by its own charge.
- **A graph refused before its run starts** (a cap above) logs no entries: `entries` is 0,
  every session count is 0 and `steps` is empty.
- **A start the reducer refuses** logs 1 entry, the rejected `StartRun`, ends `stalled`
  with the reducer's code, and reports 0 sessions. Only a graph that skipped validation
  reaches it, for example one with no start node (`not_supported`).

These bound the engine's work. They do not bound validation, which runs in the same pool
slot (below) and grows faster than linearly on large valid documents.

### The session estimate

`sessions` is `{anchor, orchestrator, steps, total}`, labelled an estimate:

- `anchor`: 1, the run's turnless anchor session, once the run started;
- `orchestrator`: 1 when any decision opened, else 0;
- `steps`: one per `create_session` effect, that is one per roster seat per step
  activation. A done-when retry reuses its session;
- `total`: their sum.

This deviates from ENG-07's formula (activations × roster size, plus the orchestrator) in
two ways: it counts the anchor, and it counts the orchestrator only when a decision opens.

**Preflight's count differs.** `POST /runs:preflight`'s `estimate.sessions`
(`estimate_session_count` in `coral/omni/server/preflight.py`) is `2 + every step's seats`:
an anchor and an orchestrator always, each step once. For the built-in template preflight
says 4; Simulate says 3 for the approved path and 7 for three `changes_requested`.

### Determinism and the trace digest

- Every entry carries one clock value (2026-01-01T00:00Z, `SIMULATED_AT`). Nothing sleeps,
  so no timer comes due.
- The run id and start key are `simulation`; handoffs say "Simulated handoff.", choices
  "Simulated choice.", and gate answers are by `simulation`.
- Nothing iterates a set or a dict for order.
- `trace_digest` is SHA-256 over each log entry's canonical JSON
  (`coral.model.canonical.canonical_json`) followed by a newline, one entry at a time.
  Equal graphs and scripts give equal digests, in one process or in another with a
  different `PYTHONHASHSEED`. A digest is comparable only within one engine and log
  version; nothing stores it.
- In the engine, `Simulation` also carries the log, the final state and the `EngineConfig`,
  and `fold(graph, log, config) == state`. The API never sends the log.

### What Simulate does not model

- Repeat-for-each: the reducer runs a `list_from` step once, and its `structure.*` effects
  are unsupported. Scripts have no list lengths.
- Timers, retries, runner loss, failed effects, `blocked` handoffs, turn ends, messages,
  usage limits, pause, resume and cancel: Simulate never feeds those inputs.
- Done-when commands are not run; `pass` and `fail` stand for the check's verdict.
- Arrows taken are not reported; `steps` gives the order.

## The simulate route

`POST /v1/coral/workflows:simulate` takes `SimulateRequest`, `{yaml, script}`. `script`
defaults to an empty script, and unknown fields are refused, so a mistyped `scripts` is a
422 rather than an empty script.

1. The caller is resolved. A body the models refuse takes no pool slot.
2. The whole job runs on the simulate pool through `InFlight`: building the validate
   context, `check_text` (as `:validate` does), and then `simulate()`.
3. A text that does not load answers 200 `InvalidResult`, the same body `:validate` gives.
4. Otherwise it answers 200 `SimulatedResult`: `ValidResult`'s fields plus `simulation`.

`simulation` is `null` whenever the graph cannot be simulated: the guard is
`runnable and not graph.analysis.unresolved`. Today every unresolved fact is an error, so
`null` comes with `runnable: false`, but the schema allows `runnable: true` with
`simulation: null`, and a client should read `null` as "not simulated".

| Input | Answer |
|---|---|
| YAML that does not load: invalid YAML, over 256 KiB, a lone surrogate | 200 `InvalidResult`, `load_error.code` such as `invalid_yaml`, `oversized` or `invalid_text` |
| Blocking problems | 200 `SimulatedResult` with `problems` and `simulation: null` |
| A malformed or oversized script, an unknown field, a lone surrogate in a script value, `node_id` or JSON key | 422 `validation_failed`; the refusal never quotes the value |
| The caller's share or the pool is full, the pool is not published or has closed, or the call ran past its timeout | 503 `server_busy`, `Retry-After: 1` |

**The pool.** `simulations_lifespan` publishes it as `app.state.coral_simulations`: 4
threads (`MAX_SIMULATIONS`), at most 1 simulation per user (`MAX_SIMULATIONS_PER_USER`,
keyed by normalized owner and account generation) and 4 in all, each with its own thread.
Its timeout is `InFlight`'s 30 s. A simulation past the timeout answers 503, but its
thread runs on and keeps the slot until it finishes.

**An aborted request does not stop the server's work.** Closing the panel, or posting
again, aborts the client's request; the server keeps simulating and holds the caller's one
slot until the thread ends, so the caller's next post can get 503.

The route reads and writes no stored workflow. Validation is the slow part of a large
request: one valid document near the 256 KiB cap took about 13 s to validate alone on a
development machine, so a large workflow can reach the timeout. `:validate` and `:save`
run the same validation on Starlette's shared pool, with no Coral cap.

## Templates

### The registry

`coral/templates/__init__.py` lists the built-in templates explicitly:
`BUILTIN_TEMPLATES = ("implement_review_loop",)`, file stems in gallery order. Each is
`<stem>.yaml` beside `<stem>.sim.yaml`, shipped as package data
(`"coral.templates" = ["*.yaml"]`) and read with `importlib.resources`.

- Each call reads and checks every template: it loads, validates runnable, has a
  non-empty description, and its saved cases load. Ids are unique. Anything else raises
  `TemplateError`, a packaging bug that the template tests catch in CI; a route would
  answer it as a 500. There is no cache.
- `builtin_template(template_id)` compares the workflow id only; no path is built from a
  request.
- `pr_review_loop.yaml` and `single_agent_steps.yaml` stay in the package, unlisted. The
  first needs repeat-for-each, which the reducer does not run; the second does not load.
- `with_workflow_id(template, key)` replaces only the source span of the top-level `id`
  and keeps every other byte, comments included. It refuses an invalid or reserved key
  (`ValueError`) and an id not written as a one-line plain scalar (`TemplateError`).

### The built-in template: "Implement with review loop"

`coral/templates/implement_review_loop.yaml`, id `implement-review-loop`:

- `start` → `implement` (roster `[implementer]`, `attempts: 3`) → `review` (roster
  `[reviewer]`, a read-only profile, labels `approved` or `changes_requested`);
- `approved` → the `approve_change` gate (`approve`, `reject`); both outcomes go to `end`;
- `changes_requested` is the back arrow `a4` to `implement`, `limit: 3`, whose at-limit
  arrow `a7` goes to the gate: the third `changes_requested` reaches the gate.

It validates with no problems at all. A test keeps it equal to the review-loop workflow
the end-to-end tests run (`tests/e2e/coral/fixtures/review_loop.yaml`) on every node and
arrow field except copy, done-when, `attempts` and loop limits.

- **One reviewer.** A step with several agents cannot choose an arrow by label (rule V4).
  Two reviewers would need an orchestrator decision to triage them, and the template stays
  on the orchestrator-free path the end-to-end tests prove.
- **No active done-when.** Done-when commands are exact commands that must pass, and any
  default is repository-specific: one that fails would pause every run after three
  attempts. A YAML comment shows how to add the project's commands, and the implementer's
  goal asks it to run the tests, lint and format checks. `attempts: 3` applies once a
  done-when is added.

### Listing

`GET /v1/coral/templates` answers `[{id, name, description, yaml}]` in gallery order; today
exactly `implement-review-loop`, whose `yaml` is the packaged text. It reads no store.

### Using a template

`POST /v1/coral/templates/{template_id}:use` takes the JSON body `{}`; no body, an unknown
field, `[]` or a body that is not JSON is 422, before any store read. It makes the caller's own workflow in the request's workspace and
never replaces one.

1. An unknown `template_id` is one fixed 404, `not_found` "Template not found.". It never
   echoes the id and reads no store.
2. It reads the workspace's taken keys once: every key that starts with the template's id,
   whoever owns it (`workflow_keys`; `_` and `%` match literally).
3. It takes the first usable key not taken: the template's id, then `<id>-2` to
   `<id>-100` (`MAX_TEMPLATE_COPIES = 99`), then `<id>-<6 hex>`, a random suffix, drawn up
   to 3 times. Usable means `validate_workflow_id` accepts it.
4. It rewrites the id with `with_workflow_id`, validates the text, and requires the
   compiled workflow id to equal the key; a mismatch raises `TemplateError` and stores
   nothing.
5. It calls `store.create` once, with the caller as owner, and answers 201
   `SavedWorkflowOut`, the shape `POST /workflows` answers.
6. Only when a concurrent insert took the key does it read the keys again and retry, with
   at most 3 inserts in all. The third takes a random suffix.

The answer is 409 `workflow_key_taken`, "No free workflow key could be chosen for a copy of
this template.", only when no usable key exists: no random draw is usable or free (for
example, a template id near 64 characters), or the random key lost a race on the last
insert. A copy over the stored size cap is 413 `payload_too_large`.

A key another owner holds is skipped, so the copy gets the next key; that tells the caller
only that the key is held, as save's 409 already does.

`WorkflowDefinitionStore.create` only inserts. It refuses a key any definition holds, the
caller's own, another owner's or a legacy one, with `WorkflowKeyTaken`, and an
`IntegrityError` from a concurrent insert becomes `WorkflowKeyTaken` with no retry and no
update. `POST /workflows` keeps its replace semantics.

## Saved cases

A template's `<stem>.sim.yaml` holds its saved simulations (`coral/engine/simcase.py`):

```yaml
cases:
  - name: approved on the first pass
    script:
      inputs:
        - {node_id: review, kind: label, values: [approved]}
        - {node_id: approve_change, kind: gate, values: [approve]}
    expect:
      outcome: completed
      steps: ["implement:done", "review:approved", "approve_change:approve"]
      gates_reached: [approve_change]
      limits_hit: []
      sessions: 3
```

- `cases`: 1-64 cases, names unique, 1-120 characters, under the script values' text rule.
- `script` is a `SimScript`. `expect` needs `outcome`; `steps` (`node_id:result` per
  answered step, in order), `gates_reached`, `limits_hit` and `sessions` (the total,
  0-1 000 000) are optional, and only the fields set are compared. Unknown fields are
  refused.
- `load_cases(text)` reads the file under the workflow loader's guards (256 KiB, no
  aliases or merge keys, string keys only, no duplicates, 32 levels, integers of at most 64
  characters) and accepts only JSON-compatible YAML: strings, numbers written as JSON writes
  them, booleans, null, lists and mappings. A timestamp, `!!set`, `!!binary`, a hex or
  base-60 number or `.inf` is refused. A refusal is `ValueError("<code>: <message>")`.
- `check_case(graph, case, max_activations=...)` returns `CaseResult{name, passed,
  mismatches}`, one line per differing field, such as
  `outcome: expected completed, got paused`.

The built-in template ships three cases: approved; `changes_requested` three times, which
hits `a4`'s limit and reaches the gate (7 sessions); and a rejected change. CI runs them in
`tests/coral/templates/test_builtin_templates.py`, with
`max_activations=DEFAULT_RUN_ACTIVATIONS`, and the simulate route's tests check that the
route answers each case as the engine does. The registry refuses a template whose cases do
not load. The cases are not served yet.

**The web fixture.** `tests/coral/api/simulate_contract.py` records what the route answers
for four scripts on the template into `web/src/workflows/fixtures/reviewLoopSimulations.json`,
which the panel's tests replay. A test in `tests/coral/api/test_workflows_api.py` fails
when the checked-in file is out of date; regenerate it with
`uv run --no-sync python -m tests.coral.api.simulate_contract --write` (the web Prettier
hook formats it).

## In the web app

- **Templates tab** (`desk/WorkflowsDeskPage.tsx`): one card per server template, with a
  spinner while loading, "Couldn't load templates." with Retry, and "No templates yet.".
  "Use template" posts `{}` to `:use` with the id URL-encoded, refreshes Your Workflows and
  opens `/workflows/<new key>`. The client never saves the template's text.
- **Simulate** (`editor/WorkflowEditorPage.tsx`, `simulate/`): the button is disabled while
  validation reports an error and the panel is closed. Opening the panel posts the editor's
  YAML, saved or not, with an empty script.
  - Each `needs_input` shows one button per allowed value; an answer re-posts the whole
    script (`scriptFromAnswers`: one input per node and kind, in answer order). Undo and
    Reset re-post too. A newer request aborts the older one.
  - Label and gate buttons show the raw value, the exact text sent; done-when buttons read
    "Checks pass" and "Checks fail".
  - The panel never re-posts on typing. Once the YAML changes it says "The workflow changed
    since this simulation." with "Simulate again", and the canvas shows the live graph with
    no overlay. While the result is current, the canvas shows the response's own compiled
    graph with `runOverlay(compiled, simulation.view)`.
  - Only a 503 with code `server_busy` is retried: after `Retry-After`, clamped to 1-60 s,
    at most 3 times, for the latest request only. A simulation that timed out answers
    `server_busy` too, so it is retried the same way before the panel says "The server is
    busy; try again.". A 422 with answers says "The server refused one of the answers. Undo
    it or reset."
  - Closing the panel aborts its request and forgets the answers; the server's work goes
    on (above).

## Proof

- `tests/coral/engine/test_simulate.py` and `test_simcase.py`: the driver, every outcome,
  the bounds (seat, size, transition and work caps, each counted, never timed), the effect
  tables against the bridge's kinds, determinism across processes, and the fixture and
  template sweep.
- `tests/coral/templates/test_builtin_templates.py`: the registry, validation, the saved
  cases, the shape test and `with_workflow_id`. `tests/coral/test_packaging.py` checks that
  the wheel holds both template files and that the registry reads them installed.
- `tests/coral/api/test_workflows_api.py` and `test_templates_api.py`: the routes, auth,
  the pool's caps, 422s, key choice and races. `tests/coral/stores/test_workflow_store.py`:
  `create` and `workflow_keys`.
- Vitest beside the web files: the client, the Templates tab, the editor and the panel.

## Residuals

- **Validation cost.** Validation runs inside the simulate slot, is not bounded by
  Simulate's caps, and can take seconds on a large valid document, reaching the 30 s
  timeout under contention. With one slot per user, four accounts can keep Simulate busy
  for everyone. The reducer's join liveness walk, which the size caps guard against here,
  costs real runs the same.
- **No request-body cap.** The body is parsed before the route runs; the YAML is refused
  over 256 KiB only after parsing, by the loader.
- **Aborted simulations keep running**, as described above.
- **Script values are narrower than labels**; such a workflow cannot be fully simulated.
- **The seat caps count unreachable steps.**
- **Caps are per process.**

## Deferred work and owners

| Work | Owner |
|---|---|
| Saved test cases per workflow, preset simulations from a template's cases, a Simulate CLI | CRL-186 |
| Timers, retries and blocked handoffs in scripts, a step-through trace, an optional exhaustive check | CRL-187 |
| Template parameters, a Use-template dialog, confirmed done-when commands | CRL-188 |
| More built-in templates: the two-reviewer review loop, PR review, single-agent steps | CRL-189 |
| Run estimates from Simulate: preflight's session count, budget from past medians | CRL-190 |
| Bounding validation and the reducer's join liveness walk on large graphs | CRL-191 |
| A request-body size cap for every Coral route | CRL-150 |
| A runs API preflight test reaches the real `claude auth status` through provider detection | CRL-192 |
