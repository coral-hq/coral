# Coral on Omnigent: session lifecycle, request-free orchestration, turn signals, server extension points

Agent 3 (Staff Engineer). Repository: `omnigent-ai/omnigent` at `2a9cbe2c2` (0.22.0.dev0).
Inputs: `coral-design.md` (Draft 4), `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` (audit of Draft 3 at this commit), and the code.

Legend. **Verified** = I opened the cited lines at HEAD. **UNVERIFIED** = inferred from code, not exercised.
Verdicts: **Reuse** (as is), **Extend** (add to an existing seam without changing behaviour), **Modify** (change behaviour of upstream code), **New** (new Coral code), **Replace**, **Remove**.
Churn = `git log --since=2026-10-09 --oneline -- <file> | wc -l` (30 days to today, 2026-11-11).

---

## 0. Summary

1. **Request-free orchestration works today, with caveats.** `fire.py` already creates, grants, launches and prompts sessions with no FastAPI `Request` (`omnigent/server/scheduled/fire.py:591-794, 2018-2196`). `coral.omni.sessions` should copy that shape (a `FireDeps`-like bundle plus lazy imports from `omnigent.server.routes.sessions`). The direct dispatch path that `fire.py` uses (`_dispatch_session_event_to_runner`) **skips** three things that only `_post_event_impl` does: server-side REQUEST-phase input policy (`routes_events.py:1706, 1777`), the `omnigent.closed` refusal (`routes_events.py:1688-1698`), and the sub-agent runner-binding heal. For Coral briefs and nudges, that makes S4 (dispatch through `_post_event_impl`) the preferred path, not optional.
2. **S4 is smaller than "closure, needs lifting".** `_post_event_impl` is already handed out through `register_startup_dispatch` (`routes_events.py:3867-3868`). But `app.py` drops the handle when managed sandboxes are not configured, because `startup_inputs` is `None` (`app.py:2286-2291, 3815-3818`). That is the default local-first deployment. It also accepts only two non-Request context types (`_RunnerEventContext`, `StartupInputContext`), and a `StartupInputContext` must be backed by a pending-input row, because its `claim()` gates dispatch (`orchestration.py:8597-8598`). New seams **E-S41** (always store the handle on `app.state`) and **E-S42** (an `EngineEventContext` type) are each about 5 lines.
3. **The S1 observer must also carry the cause of an edge, not only its status.** I mapped every `_publish_status` call (18 server sites in 4 files) and the 2 bypasses. Many `idle` edges are not turn ends: a policy deny before dispatch (`routes_events.py:1768, 1802`), a failed forward (`orchestration.py:7896`; `helpers.py:8252`), an intentional stop or idle shutdown (`orchestration.py:944, 4319, 9212`), and a transcript lull (`routes_events.py:2596`). The existing scheduled-run hook maps **every** one of them to `succeeded` (`helpers.py:5158-5159`). The relay's "turn finished after a transient drop" edge reaches **only** the bypass (`orchestration.py:9560-9582` → `4131-4152`). S1 needs an `origin` slug on every edge, plus `turn_outcome` (**E-S43**).
4. **Turn-end confirmation exists for only one mode.** Only claude-native sends `turn_completed=True` (Stop hook, `harnesses/claude_native/forwarder.py:4722`). codex-native sends neither `turn_completed` nor `turn_outcome` (`harnesses/codex_native/forwarder.py:8273-8319`). The headless runner publishes the same bare `idle` for completed and for interrupted turns (`runner/app.py:4277-4323`). The runner already has a full turn-outcome classifier for native sub-agents (`runner/app.py:7535-7610`; `server/subagent_activity.py:37-53`), and cursor-native already sends `turn_outcome` (`harnesses/cursor_native/forwarder.py:763-783`). S2 should send `turn_outcome`, not only a boolean.
5. **Topology: there is a third option, and the deep dive's default has two blockers.** The deep dive recommends children of the orchestrator (§8.2), but:
   - `_continue_session_in_fork`, the refresh primitive, refuses `kind == "sub_agent"` (`routes_core.py:5013-5017`), so child steps cannot be refreshed that way.
   - Native `/clear` rotation recreates the session top-level, with all labels copied (`harnesses/claude_native/hook.py:562-585`; `harnesses/codex_native/forwarder.py:2986-3030`).

   The third option already exists and is tested: a **child that carries its own `host_id` and `workspace`**. It inherits the parent's runner at create, gets its own runner on relaunch, and stopping it never stops the parent's runner (`tests/server/integration/test_session_host_launch.py:725-742, 4880-4919`; `helpers.py:6260-6300`). The runner resolves the working directory per session from the session's own `workspace` (`runner/app.py:2330-2380, 2887, 5774`). So a child step **can** have its own worktree on a shared runner. The test only covers the same workspace path, so a different worktree path is UNVERIFIED end-to-end.
6. **Reserving the `coral.` label prefix also needs fork, policy-write and rotation paths covered.** Doing it only in `_reject_server_reserved_label_seed` leaves three gaps (**E-S47**):
   - policies write labels straight to the store (`runtime/policies/engine.py:521-546`);
   - forks copy labels (`routes_core.py:4527-4544`);
   - both native rotations copy every label into a `POST /v1/sessions`, which the reservation would then reject (`hook.py:571-585`; `orchestration.py:11717`). That turns `/clear` on run-owned sessions into a hard failure.
7. **The S32 lifespan hook needs a services bundle, and the CLI has to load it.** `app.state` lacks `conversation_store`, `policy_store`, `file_store`, `artifact_store`, `agent_cache`, `project_store` and `auth_provider` (enumerated from `app.py`), so a hook that only receives the `app` cannot build the facade. `omnigent/cli.py:5118-5147` passes neither `extra_routers` nor any hook. **E-S49** proposes a config-driven `server_plugins:` loader that mirrors `policy_modules` and `debug_router_modules`.
8. **Child sessions need an idempotent create, and it already exists.** `ConversationStore.create_conversation(conversation_id=...)` accepts a caller-chosen id and raises `ConversationAlreadyExistsError` on reuse (`stores/conversation_store/sqlalchemy_store.py:1145-1156`). Messages carry an idempotent `stable_id` (32 hex) on both the headless path (`orchestration.py:7287-7308`) and the native pending-input path (`orchestration.py:8317-8390`). Coral effects should derive both from `uuid5(effect_key)`; labels are not needed as the idempotency key.

---

## 1. Discrepancy register

| ID | Statement | Verdict at HEAD | Evidence | Roadmap consequence |
|---|---|---|---|---|
| D1a | Draft 4 §7.6 (l.284): engine uses `PersistentTaskScheduler` for timers **and the signal queue** | **Confirmed false premise** (F10/F29) | Signals come from the status edge (S1), not a schedule. The persistent scheduler exists only with `automations_v2` on (`app.py:2116-2143`), and that flag is off by default (`feature_flags.py:96-103`). Recovery decides from evidence and never re-runs `on_fire` (`fire.py:2653-2715`). | Coral owns a `coral_signals` table, written by the S1 observer and claimed by a lease. Copy the `StartupLease` pattern; do not depend on the scheduler. |
| D1b | Draft 4 §3 table (l.86): the scheduled-run completion hook tells when a turn finished | **Partial / misleading** | `persist_scheduled_run_completion` is called only from `_publish_status`; every idle maps to `"succeeded"` (`helpers.py:5151-5199`), including idles that are not turn ends (§4.2). The bypass edges skip it (`orchestration.py:4131-4152, 13706-13708`). | S1 plus E-S43 (origin and turn_outcome). The reconciler stays authoritative. |
| D1c | Draft 4 §3 (l.107): "`sys_cancel_task` does nothing … Cancellation uses interrupt" | Stale (F25); and interrupt is the wrong cancel primitive | Interrupt is not sticky. The next message runs again, and headless interrupt discards the vendor session (F34). The sticky refusal is the `omnigent.closed` label (`routes_events.py:1688-1698`). | Cancel = interrupt, then `stop_session`, then set `omnigent.closed`, all through `coral.omni.sessions.stop(close=True)` (§7). |
| D1d | Draft 4 §7.5 (l.276): 70% refresh threshold; the deep dive says 80% | Design moved; no code impact here | `coral-design.md:276` | The threshold is engine configuration. This area only provides the refresh primitive (§8). |
| D2 | `coral-requirements.md` is referenced (`coral-design.md:5`) | Confirmed absent | Not in the repo root. | Facade requirements here come from the design and the deep dive only. |
| D3 | UI doc `/schemas`, `/profiles`, `concerto` files | Not in scope for this area | n/a | The server extension point (E-S49) does not care about route names. |
| D4 | Elephant-Goldfish needs persistent sessions and per-member input scoping | Confirmed relevant here | A "persistent session" step option means sending into an existing slot session, the way the `continue` path does it (`fire.py:841-929`; `_make_reuse_dispatch` `fire.py:2107-2150`) | The facade must support `send_message` to an existing session and `wake` (§3, §14). |
| **D5 (new)** | Deep dive §8.2 recommends step sessions as **children** and §8.9 uses `_continue_session_in_fork` for refresh | **Conflict** | `_continue_session_in_fork` refuses sub-agents (`routes_core.py:5013-5017`). Native rotation creates a **top-level** replacement session (`_native_supersession.py:24-51`, no `parent_session_id`). | Either refresh children with Coral's own create-new + brief + close-old sequence (no fork), or use the hybrid topology (§9). |
| **D6 (new)** | Deep dive §4.1, data flow 3: "Almost every status edge passes through `_publish_status`" | Refine | True for the status value, but `_publish_status` cannot tell a turn end from a stop or deny, and it has no origin for non-failed edges (§4). | S1 must add `origin` and `turn_outcome`, not only an observer list. |
| **D7 (new)** | Deep dive §8.1: "`send_message` … as in `fire.py:2153-2185`" | Refine | Direct dispatch skips input policy, the closed check and the child heal (§3.3). | Route Coral messages through `_post_event_impl` (S4 + E-S41 + E-S42). |
| **D8 (new)** | Deep dive S4: `_post_event_impl` "already accepts non-Request contexts" | Partial | It accepts only `_RunnerEventContext` (needs a bound runner) and `StartupInputContext` (needs a pending-input row; `claim()` gates dispatch at `orchestration.py:8597-8598`). The handle is dropped without managed sandboxes (`app.py:3815-3818`). | E-S41 and E-S42. |

---

## 2. Ambient context every Coral worker must enter

| Scope | Definition | Who reads it | Coral rule |
|---|---|---|---|
| `workspace_scope(workspace_id)` | `omnigent/db/db_models.py:146-157` | Every store query filters on `current_workspace_id()`. The live-state executor copies the caller's contextvars (`session_live_state.py:123-160`). | Enter `workspace_scope(run.workspace_id)` around every effect, reconcile and signal claim. OSS always uses 0 (F32). |
| `account_authority_scope(user_id, generation)` | `omnigent/db/account_authority.py:79-90` | Permission resolve cache keys (`stores/permission_store/sqlalchemy_store.py:561, 592`); host send check (`server/host_registry.py:952-957`) | Store `user_id` and `account_generation` on the `coral_runs` row at run start (read `account_generation(user_id)` inside the request). |
| `host_owner_scope(user_id, generation)` | `server/host_registry.py:66-73` | Host frame send refuses when the connection's owner or generation differs (`host_registry.py:944-950`) | Enter it for any launch or worktree RPC. A `ConnectionError("…account ownership changed")` maps to the `auth` pause class (deep dive §6.7). |
| Owner identity override (hosted) | `FireIdentity` (`ScheduledTaskDispatchHooks.fire_identity`, `scheduled/dispatch_scheduler.py:383-407`) | `ClaimedRunExecutor._enter_owner_identity` (`fire.py:2679-2685`) | Optional async-CM hook in Coral's services bundle for deployments that need delegated credentials. |

Precedent order (copy exactly): `with workspace_scope(ws): with account_authority_scope(u, g), host_owner_scope(u, g): …` (`fire.py:567-586`).

---

## 3. Request-free session creation and dispatch

### 3.1 Current sequence (`fire.py`), verified

| Step | Code | Notes for Coral |
|---|---|---|
| Deps captured once | `FireDeps` dataclass `fire.py:215-251`; built in `_lifespan` `app.py:2093-2115` | Template for `CoralOmniDeps`. It needs the same stores plus `runner_session_initializer`, `session_event_dispatch` (E-S41), `auth_provider` and `feature_flags`. |
| Validate | `validate_session_agent`, `validate_existing_host_workspace`, `validate_session_model_metadata` (`routes/_session_create_validation.py:97, 153, 337`; all request-free); `validate_create_harness_readiness` (`routes/_session_harness_readiness.py:23`, request-free) | **Reuse.** The HTTP create runs these plus `require_codex_plan_launch_support` (`orchestration.py:12084-12118`). |
| Optional worktree | `create_worktree_on_host(host_registry, host_conn, repo_path, branch_name, base_branch)` inside `_create_session_resources` (`fire.py:1597-1638`); rollback with `_remove_session_worktree_best_effort` (`fire.py:1674-1687`; `helpers.py:10294`) | **Reuse.** Coral's run worktree and per-agent branches (Draft 4 §5.3) sit on top of this. |
| Create row | `conversation_store.create_conversation(agent_id, title, host_id, workspace, git_branch, terminal_launch_args, labels, project_id)` (`fire.py:1641-1651`); abstract signature `stores/conversation_store/__init__.py:542-564` also takes `parent_conversation_id`, `runner_id`, `kind`, `sub_agent_name`, **`conversation_id`**, overrides | **Reuse.** Use `conversation_id=uuid5(NS_CORAL, effect_key).hex`; a duplicate raises `ConversationAlreadyExistsError` (`sqlalchemy_store.py:1145-1156`). Children need a **unique title per parent** (application-level uniqueness, `sqlalchemy_store.py:1196-1200`). |
| Overrides and presentation labels | `update_conversation(model_override, reasoning_effort)`, `_presentation_labels` (`fire.py:1652-1669`); `_presentation_labels_for_agent` (`helpers.py:9320`) | Reuse. Without presentation labels, native sessions render without the terminal view. |
| Owner grant | `_grant_owner` (`fire.py:1793-1809`): `ensure_user(RESERVED_USER_LOCAL)` only for `None`; `grant(owner, conv, LEVEL_OWNER)` | **Reuse.** Children get access from the root (`permissions.py:59-66`), so grant only top-level sessions. |
| Policies before input | `_attach_cost_budget` pattern (`fire.py:1714-1790`): `policy_store.create(policy_id=uuid5…, session_id, name, type="python", handler, factory_params)`, then `invalidate_session_policy_specs_cache` | **Reuse.** Use deterministic policy ids; treat failure as fatal for run-owned sessions. `fire.py` only warns for new sessions (`fire.py:1785-1790`). |
| Announce | `_announce_session_added(user_id, session_id)` (`helpers.py:674-688`) | Reuse. Skip for children; their parent's `child_sessions` view covers them. |
| Default-public grant | `_grant_default_public` (`fire.py:1812-1832`) | **Do not** use for run sessions. The run controls sharing. |
| Launch (connected host) | `resolve_host_launch` → `_launch_runner_on_host(conv, store, host_registry, host_conn)` → `_wait_for_runner_client(session_id, runner_router, tunnel_registry, runner_id, timeout_s)` (`fire.py:2025-2076`; impls `helpers.py:6416-6486, 5964-6000`) | Reuse through the facade. `_launch_runner_on_host` is single-flight per conversation and stops the superseded runner (`helpers.py:6416-6445`). |
| Wake existing session | `ensure_runner_connected(session_id, conv, app_state, conversation_store, runner_router)` (`orchestration.py:5120-5330`) | Reuse. For a child **without** `host_id` it returns `(None, conv)` unless the runner is already live (only the `conv.host_id is not None` branch relaunches, `orchestration.py:5212-5330`). The child heal (`_heal_subagent_runner_binding_via_parent`, `orchestration.py:3813`) runs only on the message path. |
| Session init | `_ensure_runner_session_initialized(session_id, conv, runner_client, store, initializer=None, *, suppress_recovery_turn, require_success, trigger)` (`orchestration.py:5992-6060`) | Pass `initializer=app.state.runner_session_initializer` (`app.py:2279`) to share single-flight with `_on_runner_connect`. `fire.py:2163-2165` passes none. |
| Dispatch | `_dispatch_session_event_to_runner(session_id, conv, body, store, runner_client, *, agent_name, file_store, artifact_store, created_by, runner_router, agent_revision, startup_input=None, …)` (`orchestration.py:8164-8184`) | **Prefer S4** (§3.3). |
| Managed sandbox still starting | `ManagedStartupInputs.enqueue(session_id, event, user_id, headers, first)` (`startup_inputs.py:147-210`); delivered on the host's replica through `self.dispatch`, which is `_post_event_impl` (`startup_inputs.py:417-470`) | Reuse for briefs to sandbox steps. It exists only when `sandbox_config.managed_launch_supported` (`app.py:2286-2290`). |
| Recovery without resend | `_transcript_evidence` / `_delivered_run_outcome` (`fire.py:2541-2577`); `_inspect_startup` (`fire.py:2687-2715`) | Reuse the rule, with the native caveat in §5.4. |

### 3.2 The HTTP create is not reusable without a Request

`_create_session_from_existing_agent(conversation_store, agent_store, runner_router, body, request: Request, …)` (`orchestration.py:11631-11647`) uses `request.app.state` and headers throughout (for example `prepare_create_inference(request, …)` at `orchestration.py:12025-12032`, and `resolve_client_surface(request.headers…)` at `12285-12288`). The route body then sends the session-init envelope to an inherited runner, grants, launches and announces (`routes_core.py:1257-1440`).

**Verdict:** do **not** fake a Request. `coral.omni.sessions.create_session` re-implements the fire.py subset plus two child-specific pieces from the route:
- inherit `runner_id` from the parent: replicate the owner check at `orchestration.py:12036-12050`;
- send the runner session-init envelope (`build_runner_session_init_payload`, `runner/session_init_protocol.py:62`; route usage `routes_core.py:1290-1340`), or call `_ensure_runner_session_initialized`, which does the same handshake.

Risk: drift from the HTTP path's validations (inference snapshot, MCP registry services, codex plan). The mitigation is a contract test that diffs session rows created by the facade and by `POST /v1/sessions` for the same inputs (§16).

### 3.3 Dispatch: direct (`fire.py`) vs `_post_event_impl` (S4)

| Concern | Direct `_dispatch_session_event_to_runner` | `_post_event_impl` |
|---|---|---|
| REQUEST-phase input policy | **Skipped**. Only `_post_event_impl` calls `_evaluate_input_policy` (`routes_events.py:1706, 1777`; impl `orchestration.py:10543`). Whether the runner evaluates REQUEST policies again for headless sessions is UNVERIFIED. | Evaluated; a deny publishes a deny sentinel plus `idle` (`routes_events.py:1755-1773`) |
| `omnigent.closed` refusal | Skipped | `routes_events.py:1688-1698` |
| Child runner heal, relaunch ladder, managed wake, native terminal readiness, host-launch-failure persistence | Caller's job (`fire.py` does a subset) | Built in: retry/wake `routes_events.py:1890-1970`; child heal `3156-3170`; managed relaunch + host launch + failure persistence `3311-3400` |
| Access check | None | `_authorized_conversation` → `LEVEL_EDIT` (`routes_events.py:1010-1050`) |
| Steering a busy session | Same forward | Same, plus queue semantics |

**Verdict: Extend (S4 + E-S41 + E-S42).** Coral sends briefs, nudges, feedback and agent-to-agent messages through `_post_event_impl` with an `EngineEventContext`. It falls back to `ManagedStartupInputs.enqueue` only when the target is a managed sandbox that is still provisioning.

**Patch sketch (E-S41, `omnigent/server/app.py:3815-3818`):**
```python
register_startup_dispatch=lambda handler: (
    setattr(app.state, "session_event_dispatch", handler),       # new: always kept
    startup_inputs is not None and setattr(startup_inputs, "dispatch", handler),
),
```
**Patch sketch (E-S42, `omnigent/server/startup_inputs.py` next to `StartupInputContext`; `routes_events.py:1019, 1652`):**
```python
@dataclass(frozen=True)
class EngineEventContext:
    """Server-internal sender acting for a session owner (no browser, no pending-input row)."""
    app: Any
    headers: Headers
    user_id: str | None
    async def is_disconnected(self) -> bool:  # matches StartupInputContext
        return False
# routes_events.py:1019  isinstance(request, (_RunnerEventContext, StartupInputContext, EngineEventContext))
# routes_events.py:1652  not isinstance(request, (StartupInputContext, _RunnerEventContext, EngineEventContext))
# 3370/3821/3850 unchanged: an engine context is never a startup input.
```
Risk: `_post_event_impl` is 2,650 lines inside `register_events_routes` (`routes_events.py:1215-3868`; 41 commits in 30 days). New isinstance sites may be added upstream. Mitigation: a contract test that runs a `message`, an `interrupt` and a `stop_session` event through `app.state.session_event_dispatch` with an `EngineEventContext` (§16).

### 3.4 Idempotent sends

- **Headless:** `_forward_event_to_runner` persists under the client `stable_id` (`adopt_stable_id=True`, `orchestration.py:7287-7308`). An exact retry is deduplicated in the store, but **it is forwarded to the runner again** ("A persisted retry may still need forwarding", `orchestration.py:7299-7302`). Coral must check evidence before a re-send and never re-send blindly. This is the StartupLease rule.
- **Native:** `stable_id` maps to the pending input; a repeated send is detected through `pending_id_for_stable_id` (`orchestration.py:8317-8390`). The AP server does not persist the message; the transcript forwarder writes it later (`orchestration.py:8186-8215`).
- Authorship: `created_by` is the run owner for engine and user messages alike, so it cannot tell them apart. Coral records `stable_id → (effect, kind=brief|nudge|feedback|message)` in its own tables, and a turn counts as engine-started only if its triggering input's stable id is in that table (deep dive §8.10).

### 3.5 Tests nearby (to extend)
- `tests/server/scheduled/test_fire.py` (injectable `LaunchDispatch`; e.g. `test_active_creates_session_grant_and_run` l.651, `test_fired_session_is_pushed_to_the_owners_open_tabs` l.765). Template for facade unit tests.
- `tests/server/scheduled/test_claimed_fire.py` (recovery from evidence).
- `tests/server/integration/test_managed_startup_inputs.py` (`test_saved_input_survives_service_recreation_and_dispatches_once` l.164, `test_queued_input_preserves_identity_and_rechecks_access` l.566). Extend for E-S42.
- `tests/server/integration/test_session_host_launch.py` (child on shared runner, l.725-742 and 4769-4960).

---

## 4. Status edges and the S1 observer registry

### 4.1 `_publish_status` contract (verified `helpers.py:5047-5250`)

Signature: `(session_id, status, error=None, response_id=None, background_task_count=None, background_tasks=None, blocked_on=None, persist_live_status=True, scheduled_run_outcome="auto", failure_origin=None, failure_context=None, failure_intake=None, disconnect_evidence=None, turn_completed=False)`.

Behaviour, in order:
1. A sticky `failed` drops a trailing `idle` unless `turn_completed` (5117-5126).
2. `previous_status` comes from the in-memory `_session_status_cache` (5127). It is per replica and empty after a restart.
3. Cache write, `blocked_on`, then `_publish_child_status_to_parent` on change (5128-5131). That function is itself an observer-shaped fan-out on the ordered live-state worker (`helpers.py:4931-4960`), and is the precedent S1 should copy.
4. `session_pull_requests.notify_turn_end` on running/waiting → idle with persist (5132-5135).
5. `persist_live_status` (5139-5140).
6. Hard-wired scheduled hook (5151-5199): `scheduled_run_outcome=="failed"` gives failed/incomplete; **any `idle` gives "succeeded"**; `failed` logs one ERROR row with `failure_origin` and then persists failed.
7. Response-id cache and background tally (5203-5227); SSE publish (5228-5250).

It is synchronous, runs on the event loop, and is called inside the caller's `workspace_scope`.

### 4.2 Complete call-site inventory (server process)

Found with `grep -rn "_publish_status(" omnigent`. `omnigent/runner/resource_registry.py` has its own runner-local `_publish_status` (l.1736); its edges reach the server through the relay (row 13).

| # | Site | Enclosing function | Status | Today's `failure_origin` | Meaning for Coral | Proposed `origin` |
|---|---|---|---|---|---|---|
| 1 | `helpers.py:5284` | `reconcile_orphaned_running_status` (lazy, on read) | idle, `persist=False`, `scheduled_run_outcome="failed"` | – | Runner gone while the session read `running`: **turn lost** | `orphan_settled` |
| 2 | `helpers.py:8252` | `_dispatch_skill_slash_command_to_runner` | idle | – | Forward failed: **turn never ran** | `forward_failed` |
| 3 | `orchestration.py:944` | `_stop_host_runner_intentionally` | idle, `persist=False` | – | Intentional stop settled | `intentional_stop` |
| 4 | `orchestration.py:4319` | `_mark_runner_sessions_offline_once` (stop path, also idle shutdown) | idle, `persist=False` | – | Stop or idle-shutdown settled | `intentional_stop_settled` |
| 5 | `orchestration.py:4360` | same (crash or drop path) | failed | `runner_offline_sweep` | Runner lost mid-turn | (keep) |
| 6 | `orchestration.py:6383` | `_persist_native_terminal_failure` | failed | `native_terminal_boot_failed` | Native boot failed | (keep) |
| 7 | `orchestration.py:6477` | `_persist_host_launch_failure_turn` | failed | `host_launch_failed` | Launch refused | (keep) |
| 8 | `orchestration.py:7780` | `_forward_event_to_runner` | failed | `runner_rejected_event` | Runner rejected the input | (keep) |
| 9 | `orchestration.py:7896` | `_forward_event_to_runner` | idle | – | Forward failed: **turn never ran** | `forward_failed` |
| 10 | `orchestration.py:9212` | `_relay_runner_stream` (`decision == "intentional_stop"`) | idle | – | Stop | `intentional_stop_relay` |
| 11 | `orchestration.py:9268` | `_relay_runner_stream` (else branch) | failed | `runner_disconnected_mid_turn` | Runner lost | (keep) |
| 12 | `orchestration.py:9443` | `_relay_runner_stream_once` | running (inferred `blocked_on`) | – | Annotation only | `inferred_blocked` |
| 13 | `orchestration.py:9583` | `_relay_runner_stream_once` (runner `session.status`) | any | `relayed_runner_status` | **Headless turn edges**; native PTY or status-file idles | `runner_status` (+ `turn_outcome`, E-S43) |
| 14 | `routes_events.py:1768` | `_post_event_impl` (message input deny) | idle | – | Denied before dispatch | `input_denied` |
| 15 | `routes_events.py:1802` | `_post_event_impl` (skill slash deny) | idle | – | Denied before dispatch | `input_denied` |
| 16 | `routes_events.py:2596` | `_post_event_impl` (`subagent.status` lull) | idle | – | **Not a completion** ("A transcript lull publishes idle but is not a runner completion", 2595) | `transcript_lull` |
| 17 | `routes_events.py:2706` | `_post_event_impl` (`external_session_status`) | any | `external_session_status` | **Native turn edges**; `turn_completed` only from claude-native Stop | `native_status` (+ `turn_outcome`) |
| 18 | `startup_inputs.py:640` | `ManagedStartupInputs._report_failure` | failed | `startup_input_failed` | Brief never delivered | (keep) |

**Bypasses** (never call `_publish_status`):
- **B1** `orchestration.py:4131-4152` in `_publish_runner_recovered_status_impl` (`4087`): writes the cache and live status, then publishes `session.status idle` directly. It is reached from:
  - (a) explicit rebinds and handshakes;
  - (b) passive reconnects with `require_disconnect_code=True`;
  - (c) **the relay**: when the runner finishes a turn the server had written off as a drop, the relay calls this and then `continue`s, so the `_publish_status` at 9583 is skipped (`orchestration.py:9560-9582`). Case (c) is a **real turn end** that today never reaches the scheduled hook either.
- **B2** `orchestration.py:13706-13708` in `_run_runner_status_probe` (`13666`): a cold-cache fill from the runner's `GET /v1/sessions/{id}`. It is a sample, not an edge.
- Also not an edge: native rotation posts `external_session_status idle` to the **old** session (`_native_supersession.py:166-176`). It flows through row 17 with no `turn_completed`.

### 4.3 What fields an observer can get

| Field | Available today? | Source |
|---|---|---|
| `session_id`, `status`, `response_id`, `error` (code, message) | Yes | `_publish_status` args |
| `previous_status` | Yes (in-memory, per replica) | `helpers.py:5127` |
| `turn_completed` | Only from claude-native Stop (row 17) | `routes_events.py:2689`; `harnesses/claude_native/forwarder.py:4722` |
| `turn_outcome` (completed/cancelled/failed) | **Not passed** to `_publish_status`. It is in `external_session_status` data for cursor-native (`cursor_native/forwarder.py:783`) and read only by `native_subagent_terminal_status` (`routes_events.py:2715-2726`) | E-S43 |
| `failure_origin` | Failed edges only | args |
| Cause of an idle edge | **No** | E-S43 `origin` |
| `persist_live_status`, `scheduled_run_outcome` | Yes | args |
| `background_task_count` / `blocked_on` | Yes, when sent | args |
| `workspace_id` | Implicit (`current_workspace_id()`) | contextvar |
| Run/slot identity | No; the observer must look it up | Coral's in-memory index |

### 4.4 Proposed S1 design (Extend `session_live_state.py`; Modify `helpers.py` and the bypass)

```python
# omnigent/server/session_live_state.py  (new block, ~60 LOC)
TurnOutcome = Literal["completed", "cancelled", "failed"]

@dataclass(frozen=True)
class SessionStatusEdge:
    session_id: str
    status: str                       # idle | running | waiting | failed
    previous_status: str | None
    origin: str                       # call-site slug, every edge (table 4.2)
    turn_completed: bool
    turn_outcome: TurnOutcome | None  # E-S43; None = unknown
    response_id: str | None
    error_code: str | None
    error_message: str | None
    failure_origin: str | None
    persist_live_status: bool
    scheduled_run_outcome: Literal["auto", "failed"]
    background_task_count: int | None
    blocked_on: str | None
    workspace_id: int                 # current_workspace_id() at publish time
    observed_at: float

StatusEdgeObserver = Callable[[SessionStatusEdge], None]  # MUST NOT block; event-loop thread
_status_edge_observers: dict[str, StatusEdgeObserver] = {}  # custom-lint: process-wide registry

def register_status_edge_observer(name: str, observer: StatusEdgeObserver) -> Callable[[], None]:
    """Add *observer*; returns an unregister callable. Re-registering a name replaces it."""

def notify_status_edge(edge: SessionStatusEdge) -> None:
    """Call every observer; an observer exception is logged and isolated."""

# configure(store, scheduled_task_store) registers the existing behaviour as one observer:
def _scheduled_run_observer(edge: SessionStatusEdge) -> None:
    if edge.scheduled_run_outcome == "failed":
        persist_scheduled_run_completion(edge.session_id, "failed",
            error_code="incomplete", error="runner disappeared before the turn reached a terminal state")
    elif edge.status == "idle":
        persist_scheduled_run_completion(edge.session_id, "succeeded")   # unchanged semantics
    elif edge.status == "failed":
        persist_scheduled_run_completion(edge.session_id, "failed",
            error_code=edge.error_code, error=edge.error_message)
```

Changes to `_publish_status` (`helpers.py:5047-5199`):
- Add the keyword arguments `origin: str | None = None` and `turn_outcome: str | None = None`.
- Keep the ERROR log at 5171-5193.
- Replace 5151-5159 and 5194-5199 with one `session_live_state.notify_status_edge(SessionStatusEdge(...))`, placed **after** the sticky-failed early return. A dropped trailing idle is not an edge.
- `origin` defaults to `failure_origin or "unattributed"`.

Bypass coverage:
- **B1:** `_publish_runner_recovered_status_impl` gains `origin: str = "runner_recovered"`. The relay call at `orchestration.py:9565-9569` passes `origin="runner_recovered_turn_end"` and `turn_outcome="completed"`. **Caveat:** the relay knows the runner finished a turn only because an idle arrived; whether that idle closed a completed or an interrupted turn is unknown until E-S43. After the cache/stream writes at 4144-4152, call `notify_status_edge(...)` with `previous_status="failed"`.
- **B2:** call `notify_status_edge(... origin="status_probe")` only when the probe actually changed the cache. Observers treat it as a hint.

Registration: **not** in `app.py`. Coral's lifespan hook (E-S49) calls `register_status_edge_observer("coral", coral.omni.signals.observe)` and calls the returned unregister on shutdown, the way `configure_subagent_block_notifier` returns an uninstaller (`app.py:1991-1999, 2247`).

Coral observer behaviour (New, in `coral/omni/signals.py`):
1. O(1) filter: `edge.session_id in _run_owned_ids`. This is an in-memory set per replica, loaded at startup from `coral_slots`, refreshed every N seconds, and added to at session create. Non-Coral sessions cost one set lookup.
2. Ignore `status == "running"` unless `previous_status in {None, "idle", "failed"}`. That edge is a turn-start hint, used to detect user-initiated turns.
3. Enqueue `coral_signals` rows with key `sig:{session_id}:{response_id or origin}:{status}:{observed_at_ms}` on a **Coral-owned single-worker executor** that copies contextvars, as `session_live_state.submit` does (`session_live_state.py:123-160`), and retries with backoff. The live-state executor is best-effort and drops failures (`session_live_state.py:152-158`).
4. Signals are hints. `reconcile(run_id)` decides from durable state (deep dive §6.4).

Size **S**: about 60 lines in `session_live_state.py`, about 20 in `helpers.py`, and about 15 for the bypasses. The `origin` slugs at the 18 call sites are **S1b, S**, mechanical, spread over 4 files with 41-77 commits per month. The phase-2 reconciler works without S1b; S1b only reduces false wake-ups.

### 4.5 Risks
- **Hot path.** `_publish_status` runs for every running/idle edge of every session. The observer must not do I/O on the event loop; enforce it with an `asyncio.get_running_loop().slow_callback_duration` check in tests.
- **Per-replica caches.** With host-sharded replicas, `previous_status` and Coral's `_run_owned_ids` are local to the replica. The edge arrives on the replica that holds the tunnel or receives the forwarder POST. Mitigation: periodic id-set refresh plus the reconciler.
- **Server restart.** In-memory grace and hold timers are lost (`app.py:4041`; F17). No edge ever comes for a turn that was mid-flight at the restart. The startup reconcile must treat `live_status in {running, waiting}` with a stale `runner_last_seen` (TTL 90 s, `stores/conversation_store/__init__.py:360`) as `infra.runner_lost`.
- **Upstream merge pressure.** Helpers.py has 52 commits in 30 days, but the S1 change touches the function's tail only. Upstreamable.

### 4.6 Tests to extend
- `tests/server/test_session_live_state.py`: the scheduled-run tests (l.446-530) must pass unchanged once the hook is an observer. Add an observer registry test and an isolation test (a raising observer does not break publish).
- `tests/server/routes/test_failed_status_attribution.py`, `test_runner_drop_failure_attribution.py`: assert `origin` on edges.
- `tests/server/routes/test_disconnect_outcome_recovery.py`, `test_sessions_runner_relay.py`: B1 relay recovery now notifies observers.
- `tests/server/routes/test_orphaned_running_session_reconcile.py`: row 1.

---

## 5. Turn end per mode (S2 and E-S43)

### 5.1 Matrix (verified)

| Mode | Edge that reaches the server | Completed vs interrupted distinguishable? | `turn_completed` | Evidence |
|---|---|---|---|---|
| `claude-sdk` (headless) | Runner `_publish_turn_status(conv, "idle"\|"waiting"\|"failed")` → relay `session.status` → row 13 | **No.** Interrupted or cancelled → `idle` (`runner/app.py:4277-4282`); completed → `idle`, or `waiting` when children are running (`4307-4323`). The relay also sees `response.completed/cancelled/failed/incomplete` (`common.py:707-713`; `orchestration.py:9454-9473`) but does not tie them to the status edge. | Never | `runner/app.py:3886-3960, 4270-4323` |
| `codex` (headless) | Same runner path | Same as above | Never | same |
| `claude-native` | `external_session_status` from the Stop hook (`turn_completed=True` on idle) and StopFailure (`failed`), row 17. The runner suppresses its own non-failed status for claude-native (`runner/app.py:3899-3911`). PTY and status-file idles come through the relay path as `session.status` from the resource registry (`runner/resource_registry.py:2090-2101`) | Interrupt fires no Stop hook, so an interrupted turn has **no** confirmed edge, only PTY idle | Stop idle only | `harnesses/claude_native/forwarder.py:4712-4722`; `routes_events.py:2689-2710` |
| `codex-native` | `external_session_status` from `turn/completed`/`turn/failed` (`forwarder.py:4929-4941` → `_post_turn_status_edge` 8322 → `_post_status` 8273-8319). The runner drops its own idle for codex-native (`runner/app.py:3912-3913`) | Partly: interrupted `turn/completed` also posts `external_session_interrupted` (`forwarder.py:6600-6630`); the status edge is a bare idle | **Never** (S2) | `forwarder.py:6265-6330, 8273-8319` |
| cursor-native (reference) | Sends `turn_outcome` | Yes | n/a | `cursor_native/forwarder.py:763-783, 1218-1240` |

The runner already classifies native sub-agent turns: `turn_outcome` wins, then `turn_completed`, then a pending interrupt, then an "ambiguous idle" for forwarder-confirming agents (`claude`, `pi`; `runner/app.py:479, 3881-3884, 7535-7610`). The server has a parallel helper, `native_subagent_terminal_status` (`server/subagent_activity.py:37-53`).

### 5.2 S2 (refined), Modify `harnesses/codex_native/forwarder.py`
- `_post_status(..., turn_outcome: str | None = None, turn_completed: bool | None = None)` adds the fields to `data` (8303-8314).
- `_post_turn_status_edge` (8322-8395) derives:
  - `turn_outcome = "failed"` for a failed edge;
  - `"cancelled"` when `_turn_status_is_interrupted(_turn_status_from_params(params))`. This needs the params on `_CodexTurnStatusEdge` (`forwarder.py:1624-1640`) or a new `interrupted` field;
  - otherwise `"completed"`, and `turn_completed=True` for a completed idle.
- Exclude edges whose `source` ends with `:recovered`, or mark them recovered and let Coral treat them as ambiguous.
- Server: `routes_events.py:2689` reads `turn_outcome` too and passes it to `_publish_status`. A confirmed turn_outcome of `completed` also clears a sticky `failed`, the same as `turn_completed`.
- Size S. Churn: `codex_native/forwarder.py` 28 commits in 30 days; `routes_events.py` 41.

### 5.3 E-S43: outcome on headless edges, Modify `runner/app.py` and `orchestration.py`
- `_publish_turn_status(..., turn_outcome=...)`: `"cancelled"` in the `was_interrupted or cancelled` branch (4277-4282); `"failed"` in the error branch; `"completed"` in the success branch (4323, including `waiting`).
- Relay row 13 passes `turn_outcome=event.get("turn_outcome")`.
- Version skew: an older runner omits the field → `None` → Coral treats the edge as ambiguous and falls back to transcript evidence.
- Size S. `runner/app.py` has 62 commits in 30 days.

### 5.4 Coral turn-end rule (reconciler, New)

`turn_ended(slot) :=` all of the following:
1. `live_status == "idle"`. Not `"waiting"`: the runner publishes `waiting` when children are still running (`runner/app.py:4317-4323`).
2. The newest engine-started input (stable id from Coral's table) is present in the transcript, **or** the native pending input for it has been consumed. Native user messages are persisted only when the forwarder mirrors them (`orchestration.py:8186-8215`), so before that, the "newest non-bookkeeping item is an assistant reply" rule (`fire.py:2550-2561`) can see the **previous** turn's reply and produce a false "answered".
3. After that input, the newest non-`resource_event` item is an assistant message (`fire.py:2550-2577`).
4. Mode confirmation:
   - claude-native: a `turn_completed` edge after the input's dispatch time;
   - codex-native: `turn_outcome == "completed"` (after S2);
   - headless: `turn_outcome == "completed"` (after E-S43), else `response.completed` observed;
   - all modes: `background_task_count in (None, 0)` for Claude.
5. No pending elicitation (`conv.pending_elicitation_count == 0`, `entities/conversation.py:281`).

A turn whose outcome is `cancelled` never counts as "ended without handoff", so it is never nudged.

**E-S44 (optional, Upstream):** lift the classifier into a shared pure function (for example `omnigent/util/turn_outcome.py`) used by `runner/app.py:7535-7610`, `subagent_activity.py:37-53` and Coral. Size S. If upstream declines, Coral keeps a copy.

### 5.5 Tests
- `tests/harnesses/codex_native/forwarder/test_turn_errors.py`, `test_background_work.py`: assert `turn_outcome` and `turn_completed` in posted data.
- `tests/harnesses/claude_native/forwarder/test_status.py`: existing coverage of `turn_completed`.
- `tests/server/routes/test_subagent_status.py`, `test_native_failure_output.py`: `external_session_status` with `turn_outcome` reaches `_publish_status`.
- Runner: the nearest is `tests/runner/` turn-status tests (look for `_publish_turn_status`; not opened, UNVERIFIED location).

---

## 6. Runner loss, offline sweep, holds, relaunch

### 6.1 Timeline (verified)

| Event | Handler | Edge | Notes |
|---|---|---|---|
| Tunnel drop | `_mark_disconnected_runner_failed` (`app.py:4049-4235`) waits `RUNNER_DISCONNECT_GRACE_S` = 90 s (`orchestration.py:8620`; `stores/conversation_store/__init__.py:360`) through `tunnel_registry.wait_for_runner` | none during the grace | Skipped on server shutdown, handoff, or the runner being live on another replica (`app.py:4108-4157`) |
| Host also offline (user-run host) | `_hold_for_offline_host` up to `HOST_OFFLINE_HOLD_S` = 72 h, rechecked every 60 s (`orchestration.py:8639-8641`; `app.py:4161-4167, 4304-4345`) | **none while held** | The relay decision `held_host_offline` → `pass` (`orchestration.py:9248-9250`). A step can sit `running` for up to 72 h. |
| Hold expired | `error.code="runner_disconnected"`, message "did not come back within 72 hours" (`app.py:4178-4186`) | failed (row 5) | |
| Host back without its runner | `error.code="runner_interrupted"` (`app.py:4187-4199`), then `_relaunch_held_sessions` | failed (row 5), then a relaunch | **Roots only**: `roots = [conv for conv in held if conv.kind != "sub_agent"]` (`app.py:4273`). "Only the user's next message starts new work" (`app.py:4260-4264`). |
| Idle shutdown (runner watchdog) | `_note_runner_idle_shutdown`, then the stop path (`app.py:4209-4220`; `orchestration.py:8740`) | idle, `persist=False` (row 4) | Not a turn end |
| Runner crash reported by the daemon | `_on_runner_exited` (`app.py:4497-4552`) | failed (`runner_process_crash` / `runner_failed_to_start`) | Cancels the grace timer |
| Runner reconnect | `_on_runner_connect` (`app.py:4554+`); `_publish_runner_recovered_status` (B1) | idle (B1) | Eager recovery for non-idle roots. A child **with its own `host_id`** counts as independent (`app.py:4600-4604`). |
| Mid-turn relay loss | `_relay_runner_stream` decisions (`orchestration.py:9209-9295`) | failed (row 11) or idle (row 10) | |
| Sweep for affected children | `_mark_runner_sessions_offline_once` fails only `running`/`waiting` children; idle children are left alone (`orchestration.py:4172-4206, 4323-4373`) | | |

### 6.2 Coral mapping (New, engine side)

| Observation | Coral class (deep dive §6.7) | Action |
|---|---|---|
| failed `runner_disconnected` / `runner_offline_sweep` | `infra.runner_lost` | Try `wake()`: `ensure_runner_connected`, or the child heal through `_post_event_impl`. If that fails, restart the slot in a new session from its incoming handoff (Draft 4 §7.8). |
| No edge, `live_status ∈ {running, waiting}`, `runner_last_seen` stale > 90 s, host offline | `infra.runner_lost(held)` | Pause the step with reason `infra`. Do **not** restart: the 72 h hold may resume the same turn, and a parallel restart would double-execute. Surface "host offline". **E-S51 (optional XS):** a `hold_started(runner_id, session_ids)` callback in `app.py:4161-4167`. Polling is enough for phase 2. |
| failed `runner_interrupted` + relaunch | `infra.runner_lost` | The interrupted input was **not** replayed (`app.py:4260-4264`). The engine re-sends only after transcript evidence shows the brief never ran. |
| idle `intentional_stop*` / `orphan_settled` | ignore / `infra.runner_lost` | |
| `runner_failed_to_start`, `host_launch_failed`, `native_terminal_boot_failed` | `infra.transient` → backoff, then pause | |

### 6.3 Root vs child relaunch
- Roots on a host that returned are relaunched (`app.py:4259-4296`).
- Children: `kind == "sub_agent"` is skipped. A child whose runner is gone is healed to the nearest live ancestor's runner on its next message (`orchestration.py:3813-3870`). A child **with `host_id`** is relaunched onto **its own** runner (`ensure_runner_connected` → `_launch_runner_on_host`, `orchestration.py:5212-5288`; asserted by `test_child_relaunch_does_not_stop_parents_shared_runner`, `tests/server/integration/test_session_host_launch.py:4880-4919`).

### 6.4 Tests
`tests/server/routes/test_runner_drop_failure_attribution.py`, `test_intentional_runner_stop.py`, `test_disconnect_outcome_recovery.py`, `tests/server/test_child_session_recovery.py`, `tests/server/integration/test_sessions_tunnel_three_layer.py`.

---

## 7. Interrupt, stop, close, rotation

| Operation | Path | Semantics (verified) | Coral use |
|---|---|---|---|
| `interrupt` event | `_post_event_impl` (`routes_events.py:1974-2071`) | Cancels saved startup inputs (`1974-1977`); `_publish_interrupted` + fence (`2030-2033`); forwards to the runner with a 5 s timeout; marks pending inputs interrupted if delivered. Codex side-chat children are special-cased. Headless interrupt discards the vendor session (F34). | Cancel or "stop this turn". Not for steering. |
| `stop_session` event | `routes_events.py:1970-1973, 2073-2140` | Owner only. Fences, then `_stop_session_via_runner` (raises when not delivered; `helpers.py:7636`). Stops the host runner **only if the session owns it** (`_owns_host_runner`, `helpers.py:6260-6300`; comment `routes_events.py:2114-2116`). **Non-sticky**: the next message relaunches (`routes_events.py:1279-1286`). | Stopping a child step on the orchestrator's runner leaves the runner up. **Stopping the orchestrator root stops the shared runner and with it every child step that rides it.** |
| Close | `omnigent.closed=true` (`util/session_lifecycle.py:7-8`); user messages are refused in `_post_event_impl` (`routes_events.py:1688-1698`) | Sticky, but only on the `_post_event_impl` path | Cancelled run = interrupt + stop + close. Coral's own sends must check the closed state when using direct dispatch (D7). |
| Native `/clear` rotation | claude-native `_rotate_session_on_clear` → `_create_clear_replacement_session` (`harnesses/claude_native/hook.py:419-477, 562-635`); codex-native `_maybe_rotate_session_on_thread_started` → `_create_thread_replacement_session` (`harnesses/codex_native/forwarder.py:2901-3030`) | GET old → **copy all labels** → `POST /v1/sessions` with **no `parent_session_id`** → bind runner → transfer the terminal → re-key the old bridge id. The old session gets idle + a notice + `external_session_superseded` (`_native_supersession.py:100-200`; server `routes_events.py:2469-2478` → `_publish_session_superseded`, `helpers.py:5732-5765`). | The engine must learn the new id. **E-S46 (XS):** call `notify_status_edge`-style observers (or a second registry) from `_publish_session_superseded`. Alternative: forbid `/clear` for run-owned sessions through the UserPromptSubmit gate (deep dive §8.8), which belongs to another area. |
| Fork | `_fork_session` (`routes_core.py:4280-4700`) copies labels minus a drop set (`4527-4544`) | A forked run session carries `coral.*` labels | Coral ignores sessions not in `coral_slots`; E-S47 drops `coral.*` on fork. |

---

## 8. Refresh: `_continue_session_in_fork` and supersession (S25, E-S48)

Verified shape (`routes_core.py:4969-5296`): a closure in `register_core_routes` (`routes_core.py:439`) with signature `(request, source, *, before_item_id, command, title, notice, reason, prepare=None, copy_history=True) -> str`. It:
- requires `LEVEL_OWNER` on the source (`5009-5011`);
- **refuses `source.kind == "sub_agent"`** (`5013-5017`) and side chats (`5020-5024`);
- refuses while moving or running (`5025-5037`), or while a startup input is undelivered;
- forks with `continue_source=True` and `keep_sandbox_labels=True` through `_fork_session(request, …)`, another closure;
- binds the fork to the source's runner or host, posts a notice, and publishes `session.superseded` (`5240`).

The only caller is the claude-sdk `/clear` (`clear_session_into_fresh_session`, `routes_core.py:5263-5296`), passed into `register_events_routes(clear_session_into_fresh_session=…)` (`routes_events.py:966-975`). `SupersessionReason = Literal["clear"]` (`schemas.py:4209`).

Lifting it to request-free (S25, refined):
1. Module-level `continue_session_in_fork(deps: ForkDeps, *, actor_user_id, source, before_item_id, command, title, notice, reason, prepare, copy_history)`. The access check becomes `check_session_access(actor_user_id, …, LEVEL_OWNER)`.
2. `_fork_session` must be lifted too. It is the bigger part (about 420 lines, `routes_core.py:4280-4700`). It reads `request.app.state.*` for `sandbox_profiles`, `startup_inputs`, host registry and so on.
3. Add `"refresh"` to `SupersessionReason`, plus the web `session.superseded` handler (`web/src/store/chatStore.ts:9425-9441` per the deep dive; not re-opened, UNVERIFIED).
4. **E-S48:** a `allow_child: bool` path, or a separate child refresh. For a child, the "fork" must keep `parent_conversation_id` and `kind="sub_agent"`, and the fork code would need to set them.

Size **M** (`routes_core.py`: 42 commits in 30 days).

**Recommendation for phase 4:** implement refresh **in Coral without forking**:
- create a fresh slot session with `create_session` (same placement and parent, new deterministic id, `coral.refresh_of=<old>`);
- brief it with the original brief, the run state and the note;
- stop and close the old one;
- post a notice item into the old session (an `external_conversation_item` through `_post_event_impl`, as `_native_supersession.py:177-196` does);
- publish `_publish_session_superseded(old, new, reason="refresh")`, which needs only the one-word schema change.

This avoids lifting `_fork_session` and works for children. "Fresh context" is what Coral wants anyway: `copy_history=False` is the refresh semantics. S25 then shrinks to **XS** (the reason literal). Keep the full lift as a later upstream contribution.

Tests: `tests/server/integration/test_sessions_clear.py`, `test_sessions_endpoints.py` (supersession).

---

## 9. Session topology

### 9.1 Effects of `parent_conversation_id` (verified)

| Effect | Mechanism | Evidence |
|---|---|---|
| Runner inheritance | The child copies `parent.runner_id` (with an owner check) at create | `orchestration.py:12034-12050`; stored at `12325-12345` |
| No host launch at create | The route launches only if `resp.runner_id is None` | `routes_core.py:1395` |
| Access | `check_session_access` delegates to the parent, recursively | `permissions.py:59-66` |
| No default-public grant | Children follow parent grants | `routes_core.py:1420-1438, 1807` |
| Policies | Root session policies prepended to the child's; child spec policies appended; no dedup | `runtime/policies/builder.py:728-770` |
| Cost budget seed | Spawn-tree usage summed from the root | `builder.py:782-812` |
| Sidebar | The store's kind filter `parent_conversation_id IS NULL` | `stores/conversation_store/sqlalchemy_store.py:3707-3711`; the web watch set unions `child_sessions` caches (`web/src/hooks/SessionUpdatesProvider.tsx:286-297`) |
| Child status to parent stream | `_publish_child_status_to_parent` | `helpers.py:4931-4960` |
| Relaunch after host return | Children skipped | `app.py:4273` |
| Recovery on connect | A child with `host_id` counts as independent | `app.py:4600-4604` |
| Stop | A child never stops an ancestor-owned runner | `helpers.py:6260-6300`; tests `test_session_host_launch.py:4769-4960` |
| Refresh | `_continue_session_in_fork` refuses | `routes_core.py:5013-5017` |
| Native rotation | Replacement is top-level | `_native_supersession.py:24-51` |
| Title | Unique per parent | `sqlalchemy_store.py:1196-1200` |
| Edit-shared orchestration refusal | Walks to the root | `session_orchestration.py:37-78` |

### 9.2 Can a child have its own workspace or worktree on a shared runner? **Yes (API and runner plumbing); a different path is UNVERIFIED end-to-end.**
- Schema: `parent_session_id` with an external `host_id`, `workspace` and `git` is allowed. Only a managed `host_id` with a parent (`schemas.py:1807-1811`) and `sandbox_profile_id` with a parent (`schemas.py:1540-1541`) are rejected; `git` needs `host_id` (`schemas.py:1739-1753`).
- Create: the worktree is made on `body.host_id` (`orchestration.py:12146-12153`) and stored as the child's `workspace` and `git_branch`; the runner is inherited.
- Runner: per-session cwd comes from that session's own `workspace` (`runner/app.py:2330-2380`), used at harness spawn (`runner/app.py:2887, 5774`) and native dispatch (`runner/app.py:6814`).
- Tested: a child with `host_id` and `workspace` inherits the parent runner (`test_session_host_launch.py:725-742`).
- **Gaps:** nothing checks that the child's `host_id` equals the parent's routing host. Readiness uses `routing_host_id(parent)` (`_session_harness_readiness.py:43-56`) while the worktree is created on `body.host_id`. No test covers a child whose `workspace` differs from the parent's. Sandbox and `os_env` effects for SDK tools are UNVERIFIED: see `_effective_runner_os_env_spec(…, runner_workspace)` at `runner/tool_dispatch.py:7548`.

### 9.3 Options

| Option | Grants / policies / budget | Runner / process isolation | Refresh | Runner-loss recovery | Fit |
|---|---|---|---|---|---|
| A. Children without `host_id` (spawn-style) | From the tree (free) | Shares the orchestrator's runner; orchestrator stop kills steps | Coral's own refresh only (§8) | Heal to the parent on next message; never relaunched alone | Read-only reviewer steps |
| **B. Children with `host_id` and their own `workspace` (hybrid)** | From the tree (free) | Shares the parent runner at create, gets its own runner on relaunch; stop never kills the parent | Coral's own refresh (§8) | `ensure_runner_connected` relaunches on its host | **Recommended default for local-first** |
| C. Top-level sessions with `coral.*` labels | Engine-managed per session | Own runner | `_continue_session_in_fork` usable (root) | Roots relaunched after host return | Different host or sandbox per step |

Recommendation:
- **Option B** is the default.
- In B, the facade can create the child with `runner_id=None` and launch at once, so each step gets its own runner from the start. That avoids an orchestrator stop killing in-flight steps. A child with its own runner owns it (`_owns_host_runner`) and is independent on reconnect.
- **Option C** is for steps that need a different host or sandbox.
- The orchestrator-only policy hazard (root policies leak to children, `builder.py:756-770`) still applies in A and B. Attach orchestrator-only rules with a CEL `condition` on `labels["coral.role"] == "orchestrator"`; labels are visible to policies (`engine.py:873-888`).

Record this as a design decision (deep dive §8.2) and add a **phase-2 probe**: a child with a worktree workspace on the shared runner runs tools in its own cwd, in each of the four modes.

---

## 10. Labels and the `coral.` reservation (S26, E-S47)

| Write path | Current guard | Gap for `coral.*` | Patch |
|---|---|---|---|
| JSON create | `_reject_server_reserved_label_seed(body.labels)` (`orchestration.py:11717`) | none once a prefix is added | Add `if any(k.startswith("coral.") for k in labels): raise …` in `helpers.py:10884-10990`. XS. |
| Multipart create | same (`routes_core.py:1537`) | same | same |
| `PATCH /v1/sessions/{id}` labels | `LEVEL_EDIT`, then the same reject (`routes_core.py:3143-3167`) | same | same |
| Policy label writes | `PolicyEngine.apply_label_writes` → `self._store.set_labels` (`runtime/policies/engine.py:521-546`). Only the schema filter applies. | A session policy (user-attached through `/v1/sessions/{id}/policies`) could write `coral.*` | Filter reserved prefixes in `apply_label_writes`, or reject at policy create. S. |
| Fork | Drop set `routes_core.py:4527-4544` | Copies `coral.*` | Add the prefix to the drop set. XS. |
| Native `/clear` rotation | Copies all labels into `POST /v1/sessions` (`hook.py:571-585`; `codex_native/forwarder.py:3018-3030`) | **With the reservation, rotation fails with 400**. The same is likely true today for scheduled-origin labels, which are also rejected at create and not hidden by `_labels_for_viewer` (`orchestration.py:1159-1195`). Runtime UNVERIFIED. | Either strip reserved prefixes in `clear_replacement_create_body` (`_native_supersession.py:24-51`) and let Coral re-label from the supersession observer (E-S46), or block `/clear` for run sessions. Pick one explicitly. |
| Server-internal writes | `conversation_store.set_labels` directly | none | Coral writes through the facade (direct store) |

Visibility: labels are seeded into the policy engine (`builder.py:771-776`, `_seed_and_load_labels`) and injected into the evaluation context (`engine.py:873-888`). Editors can read them through `GET /sessions/{id}/labels` (`routes_core.py:2010-2049`).

**Rule:** labels are hints for policies and UI only. The authoritative mapping `session_id → (run, slot, attempt)` lives in `coral_slots` (deep dive §6.1 already says the dispatcher "first looks for a session carrying a `coral.effect_id` label"; replace that with the deterministic `conversation_id` from §3.1).

Tests: `tests/server/routes/test_sessions_crud.py` (reserved-label cases near l.767), `tests/server/integration/test_session_orchestration.py`, `tests/runtime/policies/test_builder_session_policies.py`.

---

## 11. `create_app` extension points and the lifespan (S32, E-S49)

### 11.1 What exists (verified `app.py:1563-1611`)

| Param | Effect | Wired by the CLI? |
|---|---|---|
| `extra_routers: list[(router, prefix, tags)]` | Mounted before the SPA catch-all (`app.py:5308-5311`) | **No** (`cli.py:5118-5147`) |
| `debug_router_modules` | Imports modules and mounts `DEBUG_ROUTERS`; import failure is logged and skipped (`app.py:841-880`) | Yes, from config key `debug_router_modules` (`cli.py:5137`) |
| `policy_modules` | `load_registry(extra_modules=…)` in the lifespan (`app.py:2042-2046`) | Yes, `cfg.get("policy_modules")` (`cli.py:5136`) |
| `scheduled_task_dispatch: ScheduledTaskDispatchHooks` | `on_fire`, `on_expired`, `owned_hosts`, `fire_identity`, `dispatch_enabled`, `poll_interval` (`dispatch_scheduler.py:383-407`); used only with `automations_v2` (`app.py:2124-2143`) | No |
| `feature_flags` | Snapshot; default `resolve_feature_flags()` (`app.py:1803`) | No (env) |
| `extension_state` | Browser-only extension manifests: pages and primary-nav contributions through entry-point group `omnigent.extensions` (`extensions/api.py:1-96`; `extensions/registry.py:29`) | auto-discovered |
| Lifespan | `_lifespan` closure (`app.py:1933-2260`); **no** generic startup or shutdown hook | — |

`app.state` exposes `agent_store, host_registry, host_store, managed_launches, permission_store, runner_router, runner_session_initializer, sandbox_config, startup_inputs, tunnel_registry, feature_flags, …`. It does **not** expose `conversation_store, policy_store, file_store, artifact_store, agent_cache, project_store, comment_store` or `auth_provider` (`mcp_registry_auth` happens to equal `auth_provider`, `app.py:2296`). These were enumerated from all `app.state.X =` assignments in `app.py`.

### 11.2 Proposed seam (E-S49, refines S32): Extend `create_app`, Extend `cli.py`
```python
# omnigent/server/app.py
@dataclass(frozen=True)
class ServerServices:                     # what FireDeps grabs, as one public bundle
    agent_store: AgentStore; conversation_store: ConversationStore; file_store: FileStore
    artifact_store: ArtifactStore; agent_cache: AgentCache; policy_store: PolicyStore | None
    permission_store: PermissionStore | None; project_store: ProjectStore | None
    host_store: HostStore | None; host_registry: HostRegistry; tunnel_registry: TunnelRegistry
    runner_router: RunnerRouter; auth_provider: AuthProvider | None
    feature_flags: FeatureFlags; server_config: Mapping[str, Any] | None

ServerLifespanHook = Callable[[FastAPI, ServerServices], AbstractAsyncContextManager[None]]

def create_app(..., extra_routers=None, lifespan_hooks: Sequence[ServerLifespanHook] = (),
               server_plugin_modules: Sequence[str] = (), ...)
# server_plugin_modules: import each; collect module.ROUTERS (list of (router, prefix, tags))
#   and module.LIFESPAN_HOOKS; import failure is FATAL (unlike debug routers).
# Inside _lifespan, after the scheduler start block (≈ app.py:2196) and before `yield`:
#   async with AsyncExitStack() as plugin_stack:
#       for hook in all_hooks: await plugin_stack.enter_async_context(hook(app_inst, services))
#       with monitor_event_loop(): yield
#   → hooks exit BEFORE startup_inputs.shutdown(), runner_router.aclose() (app.py:2244-2252)
# omnigent/cli.py:5118: server_plugin_modules=config_str_list(cfg.get("server_plugins"))
```
Coral then ships `coral/server_plugin.py` with `ROUTERS = [(coral_api_router, "/v1", ["coral"])]` and `LIFESPAN_HOOKS = [coral_lifespan]`. `coral_lifespan`:
- builds `CoralOmniDeps` from `services` + `app.state` (`managed_launches`, `startup_inputs`, `runner_session_initializer`, `session_event_dispatch` from E-S41);
- registers the S1 observer;
- runs the startup reconcile;
- starts the signal-drain, timer-scan, resync and effect workers;
- on exit, cancels the workers and unregisters the observer.

Ordering: the routers must be mounted at construction (before the SPA mount, `app.py:5300-5311`), so the plugin module is imported in `create_app`, not in the lifespan.

Size **S**: `app.py` +40 LOC, `cli.py` +1. Churn: `app.py` 64 and `cli.py` 36 commits in 30 days. Upstreamable: it generalizes `debug_router_modules` and `policy_modules`.

Alternatives rejected:
- Abusing `debug_router_modules`: no lifespan, failures skipped silently, semantically a debug feature.
- Wrapping the app's lifespan from outside (`app.router.lifespan_context` replacement in a launcher): works without an upstream patch, but needs its own launcher, and the CLI builds the app inside `omnigent server`.
- Entry-point auto-discovery: implicit; config is explicit.

Browser side: the `omnigent.extensions` page and nav contributions could host the Coral UI without patching `App.tsx`/`Sidebar.tsx` (S34). This is out of scope here; flagged for the frontend owner (permissions are limited to `navigation`, `projects.*`, `sessions.read`, `storage.user`, `extensions/api.py:16-24`).

### 11.3 Tests
`tests/server/test_app.py` (debug-router safety net near l.2291) gets plugin-module tests: routers mounted, hook entered and exited in order, import failure is fatal. Phase 1 needs S29/S30/S31 (other area) for the package itself.

---

## 12. Feature flag (S33)

- Enum and definitions: `omnigent/server/feature_flags.py:23-41, 57-176`.
- Unknown names in `OMNIGENT_FEATURES` **fail startup** (`feature_flags.py:248-262`), so Coral cannot use the env var without adding an enum member.
- `frontend_dict()` sends every `frontend_visible` flag (`feature_flags.py:190-196`) to `/v1/info` (`app.py:3625`).
- Web: `FeatureKey` union (`web/src/lib/capabilities.ts:59-73`).

Required edits for `Feature.WORKFLOWS = "workflows"` (owner `coral`, `default_enabled=False`, `frontend_visible=True`, `review_by_release` set):
1. `feature_flags.py`: enum member and a definition.
2. `tests/server/test_feature_flags.py:20-49`: the exact `frontend_dict` default map must gain `"workflows": False`. `test_release_flags_have_lifecycle_metadata_and_expected_defaults` (l.208-215) covers metadata automatically.
3. `capabilities.ts`: add `| "workflows"`.

Size XS. Churn: 18, 17 and 31 commits in 30 days. **Conflict-prone**, because every upstream flag edits the same lines.

Policy note: flags are temporary by policy (`designs/FEATURE_FLAGS.md:42-44`, per F15). A permanent Coral flag is a long-lived fork diff.

Alternative: a Coral-owned gate (`coral.enabled` in the server config, exposed as `GET /v1/coral/info` by the Coral router), read by the Coral web module. Zero upstream diff, at the cost of one extra fetch in the web shell. **Recommend the alternative** unless the nav link must be hidden server-side by the same `/v1/info` call.

---

## 13. Proposed `coral.omni.sessions` facade

The only module that imports `omnigent.server.routes.*` privates. It is built from `ServerServices` + `app.state` at lifespan start.

```python
# coral/omni/sessions.py  (Proposed, not existing code)
from __future__ import annotations
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable, Literal, Mapping, Protocol, Sequence

@dataclass(frozen=True)
class RunPrincipal:
    workspace_id: int
    user_id: str | None            # None = single-user/OSS → RESERVED_USER_LOCAL where a grant is needed
    account_generation: str | None

@dataclass(frozen=True)
class WorktreeRequest:
    repo_path: str
    branch: str
    base_branch: str | None

@dataclass(frozen=True)
class SessionPlacement:
    parent_session_id: str | None   # orchestrator id → child (topology A/B); None → top-level (C)
    host_id: str | None             # B/C: required; must equal the parent's routing host for B
    workspace: str | None
    worktree: WorktreeRequest | None = None
    own_runner: bool = True         # B: launch a dedicated runner instead of inheriting the parent's
    project_id: str | None = None

@dataclass(frozen=True)
class SessionCreate:
    effect_key: str                 # deterministic → conversation_id = uuid5(NS_CORAL, effect_key).hex
    agent_id: str                   # pinned per-step bundle / profile revision
    title: str                      # unique per parent
    placement: SessionPlacement
    labels: Mapping[str, str]       # coral.run_id / coral.slot_id / coral.role (hints only)
    model_override: str | None = None
    reasoning_effort: str | None = None
    permission_mode: str | None = None
    policies: Sequence["PolicyAttach"] = ()   # attached BEFORE any input; failure is fatal

@dataclass(frozen=True)
class SessionHandle:
    session_id: str
    runner_id: str | None
    host_id: str | None
    created: bool                   # False → effect already applied (idempotent replay)

@dataclass(frozen=True)
class SendReceipt:
    accepted: bool
    stable_id: str                  # = uuid5(NS_CORAL, effect_key).hex
    item_id: str | None             # headless persisted item
    pending_id: str | None          # native pending input
    queued_for_startup: bool        # managed sandbox still provisioning
    denied_reason: str | None       # REQUEST-phase policy deny

@dataclass(frozen=True)
class SessionStatusView:
    session_id: str
    live_status: str | None         # durable row
    cached_status: str | None       # this replica's _session_status_cache
    runner_id: str | None
    runner_last_seen: int | None
    runner_online: bool
    host_online: bool | None
    blocked_on: str | None
    pending_elicitations: int
    background_work_running: bool | None
    closed: bool
    archived: bool
    last_task_error: Mapping[str, str] | None

@dataclass(frozen=True)
class TurnEvidence:
    input_seen: bool                # engine input (stable id) in transcript / pending consumed
    answered_after_input: bool      # newest non-bookkeeping item after it is an assistant message
    last_item_id: str | None

class CoralSessions(Protocol):
    def principal_scope(self, principal: RunPrincipal) -> AbstractContextManager[None]: ...
    async def create_session(self, spec: SessionCreate, principal: RunPrincipal) -> SessionHandle: ...
    async def attach_policies(self, session_id: str, policies: Sequence["PolicyAttach"]) -> None: ...
    async def ensure_runner(self, session_id: str, *, timeout_s: float = 30.0) -> bool: ...
    async def send_message(self, session_id: str, text: str, *, effect_key: str,
                           principal: RunPrincipal, file_ids: Sequence[str] = ()) -> SendReceipt: ...
    async def interrupt(self, session_id: str, principal: RunPrincipal) -> bool: ...
    async def stop(self, session_id: str, principal: RunPrincipal, *, close: bool = True) -> bool: ...
    async def read_status(self, session_id: str) -> SessionStatusView: ...
    async def read_items(self, session_id: str, *, after: str | None = None, limit: int = 100,
                         order: Literal["asc", "desc"] = "asc", type: str | None = None) -> list: ...
    async def turn_evidence(self, session_id: str, *, input_stable_id: str) -> TurnEvidence: ...
    async def set_labels(self, session_id: str, labels: Mapping[str, str]) -> None: ...
    async def grant(self, session_id: str, user_id: str, level: int) -> None: ...
    async def post_notice(self, session_id: str, text: str, *, effect_key: str) -> None: ...
    async def publish_superseded(self, old_id: str, new_id: str) -> None: ...
    async def create_worktree(self, host_id: str, request: WorktreeRequest) -> "WorktreeResult": ...
    def on_status_edge(self, observer: Callable[["SessionStatusEdge"], None]) -> Callable[[], None]: ...
    def on_supersession(self, observer: Callable[[str, str, str], None]) -> Callable[[], None]: ...
```

### 13.1 Method-by-method mapping

| Method | Building blocks (verified) | Seam needed | Notes |
|---|---|---|---|
| `principal_scope` | `workspace_scope` (`db_models.py:146`); `account_authority_scope` (`account_authority.py:79`); `host_owner_scope` (`host_registry.py:66`); optional `FireIdentity` | none | Order as in `fire.py:567-586` |
| `create_session` | Validators (`_session_create_validation.py:97, 153, 337`; `_session_harness_readiness.py:23`) → optional `create_worktree_on_host` (`routes/_host_worktree.py:190-257`) → `create_conversation(conversation_id=…, parent_conversation_id, runner_id, kind, host_id, workspace, git_branch, terminal_launch_args, labels, model_override, reasoning_effort)` (`stores/conversation_store/__init__.py:542-564`) → presentation labels (`helpers.py:9320`) → `_grant_owner` pattern (top-level only, `fire.py:1793-1809`) → `attach_policies` → `_announce_session_added` (top-level, `helpers.py:674`) → launch: `resolve_host_launch` (`routes/_host_launch.py:213`) + `_launch_runner_on_host` + `_wait_for_runner_client` (`fire.py:2043-2071`); for an inherited runner, session init (`_ensure_runner_session_initialized`, `orchestration.py:5992`) | none (lazy imports from `omnigent.server.routes.sessions`, as `fire.py:2026-2030` does) | On `ConversationAlreadyExistsError`: re-read and return `created=False`; finish any missing grant, policy or launch steps idempotently. Roll back the worktree on failure (`fire.py:1671-1688`). |
| `attach_policies` | `policy_store.create/update` + `invalidate_session_policy_specs_cache` (`fire.py:1738-1779`; `routes/session_policies.py:203-218` per the deep dive) | S26 to protect `coral.` policy names (other area) | Deterministic `policy_id=uuid5(effect_key:policy_name)` |
| `ensure_runner` | `ensure_runner_connected` (`orchestration.py:5120-5330`); child heal `_heal_subagent_runner_binding_via_parent` (`orchestration.py:3813`); managed wake `_await_settled_managed_launch`, `_maybe_wake_stale_resumable_managed_sandbox` | none | For topology A, prefer `send_message` (S4 heals) |
| `send_message` | `app.state.session_event_dispatch(EngineEventContext(app, Headers({...}), user_id), session_id, SessionEventInput(type="message", data={"role":"user","content":[…],"stable_id":sid}))` | **S4 + E-S41 + E-S42** | Fallbacks: managed sandbox not yet bound → `startup_inputs.enqueue(..., first=False)` (`startup_inputs.py:147-210`); without E-S41 → `fire.py` `_send_prompt` path (no input policy and no closed check). The return dict maps to `SendReceipt` (`routes_events.py:3852-3866`). A deny returns `{"queued": False, "denied": True}` (`1770-1773`). |
| `interrupt` | `_post_event_impl` with `type="interrupt"` (`routes_events.py:1985-2071`) | S4 | Discards the headless vendor session (F34) |
| `stop` | `_post_event_impl` `type="stop_session"` (`2073-2140`), then `set_labels({"omnigent.closed": "true"})` (`util/session_lifecycle.py:7-8`) | S4 | The owner level is required; the engine acts as the owner principal |
| `read_status` | `get_conversation` (`live_status`, `runner_id`, `runner_last_seen`, `blocked_on`, `pending_elicitation_count`, `background_work_running`; `entities/conversation.py:280-284`); `get_runner_liveness` (`conversation_store/__init__.py:681`); `runner_router.runner_is_online`; `_session_status_cache` (`routes/_sessions/common.py`); `_last_task_error_from_labels` | none | `launching` is never persisted (`session_live_state.py:58-63`) |
| `read_items` | `list_items(conversation_id, limit, after, before, order, type)` (`conversation_store/__init__.py:828-836`) | none | Inside `workspace_scope` |
| `turn_evidence` | `list_items(order="desc")` + Coral's stable-id table + `pending_inputs.pending_id_for_stable_id` (`runtime/pending_inputs`) for native | none | Generalizes `_transcript_evidence` (`fire.py:2550-2561`), anchored on the engine's input |
| `set_labels` | `conversation_store.set_labels` | E-S47 (reservation for others) | Server-side writes bypass the reservation by design |
| `grant` | `permission_store.ensure_user/grant` | none | Topology C only |
| `post_notice` | `_post_event_impl` `external_conversation_item` (owner path) or `conversation_store.append` with a `stable_id` | S4 | Refresh marker |
| `publish_superseded` | `_publish_session_superseded(old, new, reason=…)` (`helpers.py:5732`) | S25-lite (`"refresh"` in `SupersessionReason`, `schemas.py:4209`) | |
| `create_worktree` | `create_worktree_on_host` (`routes/_host_worktree.py:190-257`) | S40 for engine checkouts (other area) | Inside `host_owner_scope` |
| `on_status_edge` | `register_status_edge_observer` | **S1 (+E-S43)** | §4.4 |
| `on_supersession` | `_publish_session_superseded` hook | **E-S46** | Native rotation |

Facade contract tests (New, `tests/coral/omni/`): pin every imported private symbol with `inspect.signature` snapshots, so an upstream merge fails in one place. Create a session through the facade and through `POST /v1/sessions`, and diff the resulting rows.

---

## 14. Seam ledger for this area

Size: XS < 20 LOC, S < 100, M < 400. Churn = commits in the 30 days to 2026-11-11.

| ID | Seam | Files (lines) | Verdict | Size | Churn | Phase | Upstream |
|---|---|---|---|---|---|---|---|
| S1 | Status-edge observer registry; the scheduled hook becomes one observer; bypasses B1/B2 notify | `server/session_live_state.py:90-110, 251-309`; `routes/_sessions/helpers.py:5047-5199`; `routes/_sessions/orchestration.py:4087-4158, 9560-9582, 13700-13710` | Extend + Modify | S | 3 / 52 / 77 | 2 | Yes |
| S1b | `origin` slug on all 18 `_publish_status` sites | `helpers.py:5284, 8252`; `orchestration.py:944, 4319, 4360, 6383, 6477, 7780, 7896, 9212, 9268, 9443, 9583`; `routes_events.py:1768, 1802, 2596, 2706`; `startup_inputs.py:640` | Modify | S | 52 / 77 / 41 / 5 | 2 (optional) | Yes |
| S2 | codex-native `turn_outcome` + `turn_completed` on terminal edges; server passes it through | `harnesses/codex_native/forwarder.py:1624-1640, 8273-8395`; `routes_events.py:2689-2710` | Modify | S | 28 / 41 | 2 | Yes |
| S3 | Public wrappers for launch, wait, init and dispatch | n/a | **Not needed**; lazy imports work (`fire.py:2026-2030, 2157-2160`); facade contract tests instead | – | – | – | – |
| S4 | Engine dispatch through `_post_event_impl` | see E-S41/E-S42 | Extend | XS | 64 / 41 / 5 | 2 | Yes |
| S25 | `"refresh"` reason (lite); full request-free `_continue_session_in_fork` later | `server/schemas.py:4209`; `routes_core.py:4969-5296, 4280-4700` | Extend (lite) / Modify (full) | XS / M | 32 / 42 | 4 | Yes |
| S26 | Protected `coral.` labels (see E-S47) | `helpers.py:10884-10990` | Modify | XS | 52 | 4 | Maybe |
| S32 | Lifespan hook (refined by E-S49) | `server/app.py:1563-1611, 1933-2260, 5308-5311`; `cli.py:5118-5147` | Extend | S | 64 / 36 | 1 | Yes |
| S33 | `workflows` flag (alternative: Coral-owned gate) | `server/feature_flags.py`; `tests/server/test_feature_flags.py:20-49`; `web/src/lib/capabilities.ts:59-73` | Extend, or **avoid** | XS | 18 / 17 / 31 | 1 | No |
| **E-S41** | Keep the `_post_event_impl` handle on `app.state.session_event_dispatch` even without managed sandboxes | `server/app.py:3815-3818` | Extend | XS | 64 | 2 | Yes |
| **E-S42** | `EngineEventContext` accepted by `_post_event_impl` | `server/startup_inputs.py:90-118`; `routes_events.py:981-1020, 1216, 1652` | Extend | XS | 5 / 41 | 2 | Yes |
| **E-S43** | `turn_outcome` on headless runner status edges + relay pass-through; `turn_outcome` param on `_publish_status` | `runner/app.py:3886-3960, 4270-4323`; `orchestration.py:9583-9613`; `helpers.py:5047-5062` | Modify | S | 62 / 77 / 52 | 2-3 | Yes |
| **E-S44** | Shared pure turn-outcome classifier | `runner/app.py:7535-7610`; `server/subagent_activity.py:37-53` → new `omnigent/util/turn_outcome.py` | Modify (refactor) | S | 62 / 1 | 3 (optional) | Yes |
| **E-S45** | (No patch) child create must replicate runner inheritance + session init from the route | `orchestration.py:12034-12050`; `routes_core.py:1290-1340`; `runner/session_init_protocol.py:62` | New (facade) | – | – | 2 | – |
| **E-S46** | Supersession observer (native `/clear` rotation and refresh) | `helpers.py:5732-5765`; `routes_events.py:2469-2478` | Extend | XS | 52 / 41 | 4 | Yes |
| **E-S47** | Reserved prefix on every write path: create/PATCH reject, policy `apply_label_writes`, fork drop set, native-rotation label copy | `helpers.py:10884-10990`; `runtime/policies/engine.py:521-546`; `routes_core.py:4527-4544`; `native/_native_supersession.py:24-51` | Modify | S | 52 / 2 / 42 / 3 | 4 | Maybe |
| **E-S48** | Child-capable continue-in-fork (only if Coral uses fork-based refresh) | `routes_core.py:5013-5017` + `_fork_session` | Modify | M | 42 | later | Maybe |
| **E-S49** | `ServerServices` bundle + `server_plugins:` config loader (ROUTERS + LIFESPAN_HOOKS); CLI passes it | `server/app.py` (new param, `_lifespan` stack); `cli.py:5118-5147` | Extend | S | 64 / 36 | 1 | Yes |
| **E-S50** | (Finding, no patch if S4 is adopted) direct dispatch bypasses input policy, closed check and child heal | `routes_events.py:1688-1698, 1706, 1777`; `orchestration.py:8164-8620` | – | – | – | 2 | – |
| **E-S51** | Optional `hold_started` callback for host-offline holds; polling is enough for phase 2 | `server/app.py:4161-4167, 4304-4345` | Extend | XS | 64 | later | Maybe |
| **E-S52** | (Finding, no patch) deterministic `conversation_id` gives idempotent session effects | `stores/conversation_store/sqlalchemy_store.py:1145-1156` | Reuse | – | 21 | 2 | – |

Seams from the deep dive in neighbouring areas that touch this one:
- S5/S6 (elicitations, gates): `pending_elicitations.set_count_persist_hook` is wired at `app.py:2618`.
- S35/S36 (web watch set and notifications for run sessions): `SessionUpdatesProvider.tsx:262-298` already unions `child_sessions` caches, so topologies A and B get live status for free.

---

## 15. Risks (this area)

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | False "turn ended" from non-turn idle edges (stop, deny, forward-fail, lull, PTY) | High / High (a wrong nudge or advance) | E-S43 origin and outcome; the §5.4 rule anchored on the engine's input stable id; the reconciler is authoritative |
| R2 | Native transcript lag: the brief is not yet persisted, so the previous reply looks like the answer | Medium / High | Anchor on stable id or pending-input consumption (§3.4, §5.4) |
| R3 | Orchestrator stop or refresh kills child steps that ride its runner | High in topology A | Topology B with `own_runner=True`; Coral refresh never stops a runner it does not own |
| R4 | Native `/clear` on a run session: the rotation either fails (reserved labels) or escapes to a top-level session | Medium / Medium | Decide: strip-and-relabel through E-S46, or block `/clear` through UserPromptSubmit |
| R5 | `_post_event_impl` grows new `isinstance` branches upstream | Medium / Medium | E-S42 contract test; one context type |
| R6 | 72 h host hold leaves a step `running` with no edge | Certain on laptops / Medium | `infra` pause from liveness polling; never restart in parallel |
| R7 | Retry re-forwards a deduplicated headless message (double turn) | Medium / High | StartupLease discipline: check evidence before a re-send (`orchestration.py:7299-7302`) |
| R8 | Facade drifts from HTTP create validations | Medium / Medium | Diff test against `POST /v1/sessions` |
| R9 | Multi-replica: observer index and `previous_status` are per replica | Medium (hosted) / Low (local) | Periodic id-set refresh; reconciler; shard effects by host-owning replica (deep dive §6.5) |
| R10 | Server restart loses in-memory grace and hold timers and the status cache | Certain / Medium | Startup reconcile from durable rows |
| R11 | SQLite writer contention from signal writes | Medium / Medium | Filter non-Coral sessions in memory; batch; `immediate=True` short transactions (deep dive §6.5) |

---

## 16. Tests to add or extend (by work package)

| WP | Test location | What |
|---|---|---|
| S1 | `tests/server/test_session_live_state.py` (l.446-530) | Scheduled observer unchanged; registry add, remove, isolation; workspace scope captured |
| S1/S1b | `tests/server/routes/test_failed_status_attribution.py`, `test_runner_drop_failure_attribution.py`, `test_disconnect_outcome_recovery.py`, `test_sessions_runner_relay.py`, `test_intentional_runner_stop.py` | `origin` per site; B1 relay recovery notifies |
| S2 | `tests/harnesses/codex_native/forwarder/test_turn_errors.py`, `test_background_work.py` | `turn_outcome` completed, cancelled (interrupted), failed |
| E-S43 | runner turn-status tests (location UNVERIFIED) + `tests/server/routes/test_sessions_runner_relay.py` | Relay passes `turn_outcome` |
| E-S41/42 | `tests/server/integration/test_managed_startup_inputs.py` (pattern), new `tests/server/integration/test_engine_event_dispatch.py` | message, interrupt and stop through `app.state.session_event_dispatch` with `EngineEventContext`, with and without `sandbox_config`; closed refusal; input-policy deny |
| E-S47 | `tests/server/routes/test_sessions_crud.py` (~l.767 pattern), `tests/runtime/policies/` | `coral.*` rejected on create/PATCH; dropped on fork; policy writes filtered |
| E-S49 | `tests/server/test_app.py` (~l.2291 pattern) | Plugin routers mounted before the SPA; hooks entered after the scheduler and exited before runner-router close; import failure fatal |
| S33 | `tests/server/test_feature_flags.py:20-49` | Exact `frontend_dict` |
| Topology B probe | `tests/server/integration/test_session_host_launch.py` (extend `_inline_child_session`, l.725) | A child with a different `workspace` (worktree) on the shared runner; relaunch onto its own runner; stop isolation |
| Facade | New `tests/coral/omni/test_sessions_contract.py` | Signature snapshots of imported privates; facade-vs-HTTP create diff; idempotent replay (`ConversationAlreadyExistsError` → `created=False`) |

Keep the input matrices at the unit or route layer. Real-CLI checks (four modes) belong in the harness bench (S23, other area), not here.

---

## 17. Roadmap implications (ordered, dependency-aware)

1. **P1-a E-S49/S32: server plugin loader + `ServerServices`** (S). Blocks everything Coral runs in-process. Independent of the other items.
2. **P1-b Coral gate** (Coral-owned) or S33 (XS). Parallel with P1-a.
3. **P2-a S1 observer registry + bypass B1/B2** (S). P2-b and P2-e depend on it.
4. **P2-b `coral.omni.signals` observer + `coral_signals` writer + reconciler skeleton** (New). Depends on P2-a and on the data-model work from other areas.
5. **P2-c E-S41 + E-S42 (S4)** (XS each), then **`coral.omni.sessions.send_message/interrupt/stop`**.
6. **P2-d `create_session`** (topology B default, deterministic ids, unique child titles, policy attach before input, worktree), plus the facade contract tests. Can start in parallel with P2-c, using the `fire.py` send path as a temporary fallback.
7. **P2-e S2 + E-S43 (turn_outcome) + the §5.4 rule.** Claude-first: claude-native already has `turn_completed`; claude-sdk needs E-S43 or `response.*` tracking.
8. **P2-f Topology B probe test** (child worktree on a shared runner). Gate the decision record on it.
9. **P4-a Refresh, Coral-native** (create + brief + close + notice + `publish_superseded(reason="refresh")`, S25-lite) and **E-S46 supersession observer**.
10. **P4-b E-S47 label reservation** across all write paths, with the native `/clear` decision.
11. **Later:** E-S44 shared classifier upstream; E-S48 full fork lift; E-S51 hold callback.

---

## 18. Open questions

1. Topology decision: B (child with its own host_id and workspace, own runner) as the default? It changes sharing and recovery compared with deep dive §8.2 option A.
2. Native `/clear` on run sessions: block it (UserPromptSubmit) or follow the rotation (strip `coral.*` + E-S46)?
3. Should engine briefs pass through REQUEST-phase input policies (the `_post_event_impl` path), or deliberately bypass them as scheduled prompts do (`fire.py` direct path)? The answer decides whether a user-attached input policy can block a run.
4. Is a runner-side REQUEST-policy evaluation applied to headless messages that arrive via direct dispatch? UNVERIFIED; it matters only if Q3 chooses the bypass.
5. Coral-owned gate vs the upstream `workflows` feature flag (fork-diff cost vs a single `/v1/info` read).
6. Multi-replica scope for v1: SQLite single replica only (refuse multi-replica, as the scheduler refuses D1)?
7. Does a child whose `workspace` differs from its parent's run SDK `sys_os_*` tools in its own cwd under every sandbox mode (`_effective_runner_os_env_spec`, `runner/tool_dispatch.py:7548`)? This needs the P2-f probe.
