# Coral on Omnigent: adversarial review (Agent 2)

| | |
|---|---|
| Repo / commit | `omnigent-ai/omnigent` at `2a9cbe2c205e49f6fe2b676f2a61bdeb25d57896` (0.22.0.dev0). I confirmed HEAD with `git rev-parse HEAD`. |
| Inputs | `coral-design.md` (Draft 4, read in full). `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md`: §1, §2, §3, §4, §5.3-5.5, §6, §7, §8, §9, §10, §11, §12, §13, §14, §15.3, §17-§20 and App. B. `coral_UI_DESIGN_LANGUAGE.md`: the parts on routes, taxonomy and implementation map. |
| Ground rules | Read-only. I edited no repository file and ran no app, server, browser or test suite. Every Omnigent claim below cites a `path:line` I opened at HEAD. **UNVERIFIED** marks anything I could not check in code. |
| Notation | **[D4§n]** is a Draft 4 section. **[DD§n]** is a deep dive section. **S-n** is a deep dive seam (DD§4.3). **R/E/M/N/X/Rm** mean Reuse / Extend / Modify / New / Replace / Remove. |

---

## 0. Verdict in one page

1. **Most load-bearing deep-dive claims hold at HEAD.** I spot-checked 30 claims: 26 HOLD, 4 HOLD with a material refinement, 0 are WRONG, and 2 carry a STALE risk (see §1). The deep dive is a reliable base. Draft 4 still repeats six claims the deep dive disproved (D1 confirmed), and adds new ones that do not hold (D5-D9).
2. **The deep dive under-counts merge pain.** Its churn table lists `helpers.py` (52 commits in 30 days) and `AppShell.tsx` (41). It does not list the files where more of its seams actually land:

   | File | Commits in 30 days | Seams |
   |---|---|---|
   | `orchestration.py` | 77 | S3, S6, S10 |
   | `server/app.py` | 64 | S32 |
   | `runner/app.py` | 62 | |
   | `runner/native/orchestration.py` | 56 | S11, S12 |
   | `harnesses/claude_native/bridge.py` | 83 | S14 |
   | `openapi.json` | 69 | Changes whenever a schema seam changes (S25) |

   The fork will not stay "thin" unless the seams move into low-churn files (§8).
3. **Several things the plan treats as "verify later" are design defects in Omnigent's current behaviour.** The deep dive missed them:
   - **(a)** A native `/clear` creates a new **top-level** session with copied labels and no session policies. That detaches a step from its parent and from its Required rules (§5.6).
   - **(b)** `SubagentBlockNotifier` wakes a parent *agent* when a child has an approval unanswered for 120 s. If step sessions are children of the orchestrator, this starts orchestrator turns the engine never asked for (§6.2).
   - **(c)** `read_only_os` deliberately leaves shell untouched, so "reviewers stay read-only" [D4§5.1] cannot be Enforced with existing policies (§3, D7).
   - **(d)** "Done when evaluated on the merged result" [D4§5.3] has no evidence source. Nobody runs commands after a merge (§3.2, D8).
   - **(e)** No API can read workflow YAML from a repo on a host, which blocks phase 1 as written (§10.3).
4. **The biggest scope risk is breadth.** The plan targets four agent modes, multi-writer merges, LLM-translated policies, two-way YAML/canvas sync, amendments, session refresh, take-over and live inter-agent messaging. Each one alone is a quarter-sized project once Omnigent's edge cases are included. §11 proposes a v1 cut that keeps the product thesis: rails, evidence, gates and fresh context. That cut removes roughly half of the seam ledger.
5. **Twenty-five decisions must be made before parallel implementation starts** (§12). The most blocking:
   - where workflow definitions live and how the server reads them;
   - session topology;
   - v1 agent modes and authentication;
   - whether `submit_handoff` is synchronous or asynchronous;
   - the evidence semantics, including the format-then-test ordering trap;
   - the multi-writer policy;
   - restart fencing after runner loss.

---

## 1. Spot-check of deep-dive claims at HEAD

Verdicts: **HOLDS** (matches the code); **HOLDS+** (matches, with a material refinement the deep dive missed); **STALE-RISK** (true today but scheduled to change); **PARTIAL** (narrower than stated); **WRONG**.

| # | Deep-dive claim (where) | Verdict | Evidence at HEAD (opened) |
|---|---|---|---|
| C1 | The completion hook maps every `idle` edge to `succeeded` (F9, finding 4) | **HOLDS+** | `omnigent/server/routes/_sessions/helpers.py:5158-5159` (`elif status == "idle": persist_scheduled_run_completion(session_id, "succeeded")`). **Refinement:** stops and archives also publish `idle` with `persist_live_status=False` (comment at `helpers.py:5133-5135`). The hook still fires on those edges, because the `succeeded` branch at 5158 is not gated on `persist_live_status`, so an archive or stop looks like a successful turn end. The sticky-failed guard is at `helpers.py:5114-5126`. `turn_completed` is a parameter (`helpers.py:5061`) that is not forwarded to the hook. |
| C2 | Live-state writes are best-effort and dropped on failure (F17, §8.7) | **HOLDS+** | `omnigent/server/session_live_state.py:148` (one `ThreadPoolExecutor(max_workers=1)`), `:155` (`except Exception:  # best-effort display state`), hook at `:251-309`. **Refinement:** every live-status mirror, pending count, scheduled-run completion and child-status fan-out (`helpers.py:4931-4961`) is serialized on this one worker thread. A Coral observer that does DB I/O there adds latency to sidebar status for every session. A Coral observer must enqueue cheaply and do its own I/O elsewhere. |
| C3 | Native PreToolUse fails to **ASK**, not deny (F38a, finding 6) | **HOLDS+** | `omnigent/harnesses/claude_native/hook.py:1238-1242` and `omnigent/harnesses/codex_native/hook.py:149-153` call `fail_ask_hook_output`. `fail_closed_hook_output` exists unused next to it (`omnigent/native/native_policy_hook.py:473-542`), and `fail_ask_hook_output` is at `:550-586`. The docstring at `claude_native/hook.py:1174-1187` is stale. **Refinement:** malformed hook JSON (`hook.py:1208-1212`) and a missing active session id (`hook.py:1222`) both return exit 0 with no opinion. That is fail-*open*, not fail-ask. S14 must cover those early returns for run-owned sessions as well. |
| C4 | Headless codex uses `approvalPolicy: "never"` (finding 5) | **HOLDS** | `omnigent/inner/codex_executor.py:3829`. Only `features.shell_tool` is disabled, under `_disable_native_tools` (`:3846-3847`). Web search is turned off only when `enable_web_search` is false and there is no signer (`:5014-5018`); it defaults to `True` (`:4768`). |
| C5 | `claude-sdk` strips `ANTHROPIC_API_KEY` and exposes no native Bash/Read/Edit/Write (F37, F48) | **HOLDS+** | Strip: `omnigent/inner/claude_sdk_executor.py:2096-2118` (`_unset_env_var("ANTHROPIC_API_KEY")` at 2117). Base tools are only `Skill`/`ToolSearch`/`AskUserQuestion` (`:2571-2586`). **Refinement:** `prepare_claude_cli_path` still computes `enable_native_tools=True` in two branches (`:1588`, `:1633-1636`) and stores it in `self._os_env` (`:1954`), but nothing reads it. The plumbing to re-enable native tools exists, so a small upstream change could silently re-expose native Bash and bypass Coral's `sys_os_*`-based evidence. Add a contract test that pins `_base_tools()`. |
| C6 | `PersistentTaskScheduler` is not a generic queue: its store protocol is typed on scheduled-task entities, it is at-most-once, it polls every 30 s and it sits behind `automations_v2` (F10, F29) | **HOLDS / STALE-RISK** | The Protocol is typed on `ScheduledTask`/`ScheduledTaskRun` (`omnigent/stores/scheduled_task_store/dispatch.py:8, 17-138`). Constructor: `omnigent/server/scheduled/dispatch_scheduler.py:413-429`. "Recovery never sends the prompt again" (`omnigent/server/scheduled/README.md:147`). `poll_seconds` is 30 (`omnigent/server/scheduled/config.py:14`). Built only when `automations_v2` is on (`omnigent/server/app.py:2116-2143`), and the flag defaults off (`omnigent/server/feature_flags.py:54, 98-104`). **STALE-RISK:** the flag's `review_by_release="0.20.0"` (`feature_flags.py:103`) is two releases overdue at 0.22, so upstream will likely flip or remove it soon. Do not build on either branch of that flag. |
| C7 | `pending_elicitations` has one observer slot, already taken by `SubagentBlockNotifier` (S5) | **HOLDS** | `omnigent/runtime/pending_elicitations.py:70` (single `_observer`), setter at `:73-87` ("Replaces any previously registered observer"), only caller `omnigent/server/routes/_sessions/orchestration.py:10855`. The module is in-memory and per-replica by its own docstring (`pending_elicitations.py:29-37`). |
| C8 | `create_app` has no generic lifespan or worker hook (S32) | **HOLDS+** | `omnigent/server/app.py:1563-1611` (signature), `_lifespan` internal at `:1933`, `FastAPI(..., lifespan=_lifespan)` at `:2270`. **Refinement:** no production caller passes `extra_routers`. The only production `create_app` call is `omnigent/cli.py:5118-5147`, which passes `policy_modules` and `debug_router_modules` from config but not `extra_routers`. Mounting Coral's API therefore also needs a `cli.py` edit (14,959 lines, 36 commits in 30 days), or abuse of `debug_router_modules`, which skips a missing module silently (`app.py:1679-1685`). That silent skip is a dangerous failure mode for a product API. |
| C9 | Omnigent's migrations `env.py` has no `include_name`/table filter (S30) | **HOLDS** | `omnigent/db/migrations/env.py:51-56` (offline) and `:85-89` (online). Neither sets `include_name` or `include_object`. |
| C10 | Test truncation would wipe Coral's version table (S31) | **HOLDS+** | `tests/conftest.py:735` keeps only `alembic_version`. **Refinement:** the SQLite path copies a schema **template** (`tests/conftest.py:701, 724-725`) built from Omnigent's schema only. Coral store tests on SQLite need either a Coral-aware template or a per-test `ensure_coral_schema`, which costs time on every test. |
| C11 | Held-host relaunch skips sub-agent sessions (F24, ~`app.py:4273`) | **HOLDS** | `omnigent/server/app.py:4273` (`roots = [conv for conv in held if conv.kind != "sub_agent"]`). The docstring says "only the user's next message starts new work" (`:4259-4262`). The `_intentional_stop_sessions` gate it checks is an in-memory cache (`omnigent/server/routes/_sessions/common.py:695`). |
| C12 | The live stream loses events nobody listens for (F16) | **HOLDS** | `omnigent/runtime/session_stream.py:9` ("Events emitted before any subscriber is connected are LOST"); `_SUBSCRIBER_QUEUE_MAX_EVENTS = 1024` (`:54`). |
| C13 | No `coral.` label reservation; editors can upsert labels (S26) | **HOLDS+** | `_reject_server_reserved_label_seed` is at `helpers.py:10884-10940` (no `coral.` prefix). PATCH calls it at `omnigent/server/routes/sessions/routes_core.py:3166-3167`. **Refinement:** reserving `coral.` collides with two existing flows. The native `/clear` rotation copies **all** labels into a fresh `POST /v1/sessions` (`harnesses/claude_native/hook.py:569-584`; `native/_native_supersession.py:24-51`), and `coral.omni` may itself use the public API. Either would be rejected with 400. S26 needs an engine bypass and an explicit `/clear` policy (§5.6). |
| C14 | The sub-agent router is advisory model routing, not a roster gate (F4) | **HOLDS** | `omnigent/runner/subagent_routing.py:1-8` ("The gate is **advisory**"); fail-open in `omnigent/inner/hook_scripts/subagent_router.py:11-15`. |
| C15 | `SupersessionReason` allows only `"clear"` (F46, S25) | **HOLDS** | `omnigent/server/schemas.py:4209`, default at `:4249`. Adding `"refresh"` changes `openapi.json` (§9). |
| C16 | `_continue_session_in_fork` is a closure that takes a `Request` whose caller owns the source (S25) | **HOLDS+** | `routes_core.py:4969-4980`, inside `register_core_routes` (`:439`). **Refinement:** "The fork keeps the source's agent, labels … and run settings" (`routes_core.py:4984-4985`). So a refreshed session inherits `coral.effect_id`/`coral.slot` labels. The deep dive's effect-recovery rule ("look for a session carrying a `coral.effect_id` label", DD§6.1) will then find **two** sessions. The engine must strip or rewrite identity labels on refresh. |
| C17 | User-run hosts hold a turn for up to 72 h (F17) | **HOLDS** | `orchestration.py:8639` (`HOST_OFFLINE_HOLD_S: float = 72 * 3600.0`). |
| C18 | Omnigent runs `create_all` for its two bases after every upgrade (DD§7.3.2) | **HOLDS** | `omnigent/db/utils.py:611-618` (CRDB) and `:614-618` (others). `CoralBase` must not share metadata with `OmnigentBase`/`ConversationBase`. |
| C19 | CRDB refuses to bootstrap a database that already holds tables (DD§7.3.3) | **HOLDS+** | `omnigent/db/cockroachdb.py:139-145`. **Refinement:** an *interrupted* Omnigent CRDB bootstrap refuses to resume when unexpected application tables exist (`cockroachdb.py:168-178`). So `coral_*` tables must never be created unless Omnigent's revision equals head. That is a hard ordering invariant, not just a preference. |
| C20 | Children inherit the parent's runner (DD§8.2) | **HOLDS** | `orchestration.py:12036-12052`. |
| C21 | "Root session policies **and the root spec's guardrails** apply to every child" (DD§9.3, citing `builder.py:728-768`) | **PARTIAL** | Root **session** policies are inherited (`omnigent/runtime/policies/builder.py:756-772`). Spec resolution is per conversation, though: the server resolves `conv.agent_id` (`helpers.py:9352-9373`), and the root bundle spec applies only to *in-bundle* sub-agents (`builder.py:482-514, 728-741`). A child created from its **own uploaded bundle** gets its own agent row (`orchestration.py:12617-12620`, "Child uploads receive separate rows"), so the orchestrator's spec guardrails do **not** leak to it. **Consequence:** put orchestrator-only restrictions (no write, no shell) in the orchestrator's own bundle guardrails, never in a session policy. The label-conditioned CEL workaround in DD§9.3 is then unnecessary. |
| C22 | Engine tools can follow the `sys_advise_models` server-side intercept after policy (S10) | **HOLDS+** | `orchestration.py:13058-13069`. **Refinement:** the handler runs **inside the agent's MCP HTTP request** on the replica that received it. Transport timeouts allow long calls (`MCP_PROXY_FORWARD_TIMEOUT_S = 7200 + 30`, `omnigent/runner/tool_dispatch.py:208, 228`). But a `submit_handoff` that evaluates evidence synchronously (fingerprints, Coral-run checks) ties the evaluation's lifetime to that request. A server restart loses it, and the model retries with a **new** call id. Decide whether submission is synchronous or asynchronous (§4.2). |
| C23 | `cost_budget` ASKs at soft thresholds and DENYs at the cap; it does not pause a run (F42) | **HOLDS** | `omnigent/policies/builtins/cost.py:511-534` (DENY at the cap) and `:535-556` (ASK at thresholds). |
| C24 | Sandboxes have L7 `egress_rules`, not just "network on/off" (F26) | **HOLDS** | `omnigent/inner/datamodel.py:753-765`. |
| C25 | No Web Push, VAPID, APNs or FCM (finding 9) | **HOLDS** | `web/src/lib/browserNotifications.ts:8-10` (page-scoped Notification API; the SW "intercepts nothing"). `grep -rli "vapid\|pushManager\|apns\|firebase-messaging" web/src omnigent` returns nothing. |
| C26 | Native executors yield `TurnComplete` on delivery, not on completion (finding 4) | **HOLDS** | `omnigent/inner/claude_native_executor.py:553`; `omnigent/inner/codex_native_executor.py:1337`. |
| C27 | codex-native status edges carry no `turn_completed` (S2) | **HOLDS** | `_post_status` in `omnigent/harnesses/codex_native/forwarder.py:8273-8319` builds `{"status": status}` only. `grep turn_completed` in that file returns nothing. |
| C28 | Two status edges bypass `_publish_status` (DD§4.1) | **HOLDS** | `orchestration.py:4131-4152` (failed→idle on reconnect) and `:13700-13708` (runner status probe), both writing `_session_status_cache` and `persist_live_status` directly. |
| C29 | `sys_cancel_task` is intercepted runner-side, so it is not a no-op (F25) | **HOLDS** | It is a runner-local tool (`omnigent/runner/tool_dispatch.py:398-404`) included in `_ALL_LOCAL_TOOLS` (`:887-915`). |
| C30 | Migration chain: 121 revisions, single head `f1c7a9e2b406`; Omnigent uses no SKIP LOCKED (F31, DD§6.5) | **HOLDS / STALE-RISK** | `ls omnigent/db/migrations/versions/*.py | wc -l` gives 121; nothing has `down_revision = "f1c7a9e2b406"`; `grep skip_locked` returns nothing. **STALE-RISK:** that head *adds `family_id`* (sibling session families, committed 2026-11-05, `omnigent/db/migrations/versions/f1c7a9e2b406_add_conversation_family_id.py:1-6`). Upstream is actively building a session-grouping model, which bears directly on Coral's topology decision (§6.1). |

Also re-confirmed, without a separate row: `SKIP LOCKED` absent but `with_for_update` used 79 times; `HOST_OFFLINE_HOLD_S`; `automations_v2` default; CLI launch path; F43 (`/workflows` unused, `web/src/App.tsx:176-256`); `SIBLING_SESSIONS` flag at `feature_flags.py:81`; headless codex compact returns 204 (`omnigent/runner/app.py:7893-7911`); unknown top-level spec keys are dropped (`omnigent/spec/parser.py:339-352` builds `AgentSpec` from named keys only).

### 1.1 The tech lead's discrepancies D1-D4, plus new ones

| ID | Status | Detail |
|---|---|---|
| **D1** | **Confirmed, and extended** | Draft 4 still says: "fail-closed sub-agent router" (`coral-design.md:82, 104, 205, 270, 392, 415`); `PersistentTaskScheduler` for timers and the signal queue (`:87, 284`); web push (`:83, 182`); `cost_budget` "pauses the run and asks" (`:346`); `sys_cancel_task does nothing` (`:107`); "network on or off only" (`:108`). Draft 4's capability table still says headless `codex` gates tool calls (`:336`), which is wrong (C4). **New internal contradiction:** Draft 4 §7.6 says "Signal delivery is **at least once**" (`:286`) while relying on a scheduler that is at-most-once by design (C6). The 70% threshold (Draft 4 `:276`) replaces the deep dive's 80%. Either way, it is undefined when the context window is unknown (DD§8.9: the litellm lookup returns `None`). |
| **D2** | **Confirmed** | `ls coral-requirements.md` fails ("No such file or directory"). Consequences: there are no acceptance criteria or non-functional requirements (supported OSes, maximum concurrent runs or agents per run, latency targets, data retention, team model). The roadmap must not invent them silently. List them as open items owned by product. |
| **D3** | **Confirmed, with a resolution proposal** | `web/src/components/concerto/` does not exist. `CoralPageHeader`, `--concerto-*`, `/schemas` and `/profiles` are absent (grep over `web/src` returns nothing). The UI doc calls its own names non-binding ("'State Schema' might become Score, Flow…", `coral_UI_DESIGN_LANGUAGE.md:245-246`) and calls the profile form plus localStorage "disposable scaffolding" (`:336`). Proposal: routes `/workflows` (editor and list) and `/workflows/runs/:runId` per DD§14.1; nav label free to choose. Profiles must be **server-side**, because the engine creates sessions from them and localStorage is per viewer (`web/src/canvas/canvasStorage.ts:1-9`, per DD§14.4). Taxonomy mapping: UI "Phase" means Work step; "Gate" means Human gate; "Orchestrator" means Orchestrator node; "Note" is a non-executable canvas annotation and must be excluded from the IR. Start, End and Group are missing from the UI doc and must be added. |
| **D4** | **Confirmed** | Draft 4 §15 still says EGM "maps directly onto Coral's orchestrator and fresh step agents" (`coral-design.md:382`). DD§15.3 shows the elephant is a long-lived *step* agent, and that the template needs (a) a persistent session across loop passes for one roster member and (b) per-member input scoping. Both conflict with fresh context, the refresh mechanism, restart-from-handoff and per-iteration idempotency keys. Defer EGM until after v1 (§11). |
| **D5** (new) | Draft 4 internal | "At-least-once signals" versus reliance on the scheduler that is at-most-once (above). |
| **D6** (new) | Draft 4 vs deep dive | Draft 4: "A box where both cases mix … is shown as an error" (`coral-design.md:151`). Deep dive: "Back-arrows never count toward join arity" (DD§5.3.3). A box that is both a parallel-join target and a loop re-entry (for example "Review after two parallel implementations, re-entered by Fix") is an error under Draft 4 and legal under the deep dive. This is a common pattern, so decide explicitly. Recommendation: the deep dive's rule. |
| **D7** (new) | Draft 4 vs code | Draft 4: "Agents change code: Off by default for steps with more than one agent, which keeps reviewers and researchers read-only" (`coral-design.md:133`). `read_only_os` denies write and edit tools but "Reads, searches, and shell commands are left untouched" (`omnigent/policies/builtins/orchestration.py:655-657`). A shell `sed -i` or `>` redirect still writes. So read-only is **Verified** (fingerprint) or needs a sandbox without workspace write paths (per-step bundle, bwrap/seatbelt only). It cannot be Enforced in native modes, because the vendor's Bash is raw. |
| **D8** (new) | Draft 4 semantic hole | "If every merge applies cleanly, … 'done when' and Coral-run checks are evaluated on the merged result" (`coral-design.md:168`). "Done when" evidence is agent-run commands after the last workspace change [D4§6.1]. After a merge, the merged tree has a new fingerprint, and **no agent ran anything on it**. Evidence therefore always fails for multi-writer steps and parallel joins, unless a Coral-run check or a post-merge agent turn runs. Multi-writer steps effectively *require* Coral-run checks, or an explicit "integrate" activation with its own agent. |
| **D9** (new) | Draft 4 tool gap | §5.3 has the orchestrator "write the combined list" and "read the collection", but the tool table (`coral-design.md:252-258`) has no tool that writes a list or reads handoffs. `choose_arrow` carries only a label and a reason. A `compose_handoff` (or `choose_arrow.items`) tool and a handoff-read path (brief injection or a `read_handoff` tool) are missing contracts. |
| **D10** (new) | Deep dive | C21: orchestrator spec guardrails do not leak to bundled children. Only root session policies leak. |
| **D11** (new) | Deep dive | C8: mounting Coral's API needs a `cli.py` change as well as S32 in `app.py`. |
| **D12** (new) | Deep dive | Its churn table (DD§17) omits the busiest seam files. See §0.2 and the appendix. |
| **D13** (new) | Deep dive internal | S26 (reserve the `coral.` prefix) breaks native `/clear` rotation and a REST-based `coral.omni` unless an engine bypass exists (C13). |
| **D14** (new) | Draft 4 vs deep dive | Restart after runner loss. Draft 4: "restarts in a new session from its incoming handoff" (`coral-design.md:298`), with no workspace rule. The deep dive resets the worktree to the step's start commit (DD§13). Neither addresses **fencing** the old session, which may resume after a 72 h hold (§5.2). |

---

## 2. Hidden complexity in Omnigent that the plan underestimates

### 2.1 Giant, high-churn modules where the seams land

These are 30-day commit counts and current line counts, measured with `git log --since=2026-10-09 --until=2026-11-09` (1,510 commits in the window).

| File | Lines | Commits | Seams that touch it |
|---|---|---|---|
| `omnigent/server/routes/_sessions/orchestration.py` | 14,185 | **77** | S3, S6, S10, S1 bypass (4131-4152, 13700-13708), S26 |
| `omnigent/server/routes/_sessions/helpers.py` | 12,742 | 52 | S1, S3, S25, S26 |
| `omnigent/server/app.py` | 5,525 | **64** | S1 registration, S32 |
| `omnigent/runner/app.py` | 9,387 | **62** | S19 and the compaction branch; refresh |
| `omnigent/runner/native/orchestration.py` | 11,493 | **56** | S11, S12, S15 |
| `omnigent/harnesses/claude_native/bridge.py` | 11,463 | **83** | S14 (hook generation) |
| `omnigent/server/routes/sessions/routes_core.py` | 5,296 | 42 | S25, S26 |
| `omnigent/server/routes/sessions/routes_events.py` | 4,293 | 41 | S4 |
| `omnigent/cli.py` | 14,959 | 36 | S32 (C8) |
| `omnigent/harnesses/codex_native/app_server.py` | 5,753 | 34 | S11, S15 |
| `web/src/shell/Sidebar.tsx` | 7,772 | 51 | S34, rebrand |
| `web/src/shell/NewChatDialog.tsx` | 8,052 | 52 | Rebrand ("Direct the run…") |
| `web/src/shell/AppShell.tsx` | 3,202 | 41 | Avoid |
| `openapi.json` (generated) | — | **69** | Any schema seam (S25), via `tests/server/test_openapi_drift.py` |
| Low-churn (good seam homes) | | | `session_live_state.py` (3), `pending_elicitations.py` (1), `native_policy_hook.py` (1), `harness_capabilities.py` (0), `db/migrations/env.py` (0), `session_policies.py` (0), `policies/builtins/orchestration.py` (0), `runtime/prompt.py` (2), `web/src/App.tsx` (6), `web/src/lib/branding.ts` (0) |

**Implication for the roadmap.** Each seam in a 50-80-commit-per-month file costs a conflict roughly every upstream merge. Budget a standing upstream-merge owner (about 0.25-0.5 FTE, UNVERIFIED estimate), not "merge from tagged releases on a schedule" (D4§16).

### 2.2 Closures and request-scoped helpers that must be lifted

- **`_post_event_impl`** is a closure inside `register_events_routes` (`routes_events.py:947` and `:1215`). S4.
- **`_continue_session_in_fork`** is a closure inside `register_core_routes` (`routes_core.py:439, 4969`) that requires `request: Request` with owner authorization. S25.
- **The `sys_advise_models` intercept** sits inline in the MCP endpoint body (`orchestration.py:13058-13069`), so the S10 registry is a refactor of a 14k-line file, not an addition.
- **Session creation** has several hundred lines of logic, such as smart-routing branches (`orchestration.py:11170-11420`) and child bundle rules (`:12617-12705`). It is reachable only through HTTP handlers or by copying `fire.py`'s sequence.
- **`fire.py` is a template, not a library.** Its helpers are typed on `ScheduledTask` (for example `_create_session` at `omnigent/server/scheduled/fire.py:1572`, `_grant_owner` at `:1793`, `_attach_cost_budget` at `:1714`). Copy-adapting about 2,800 lines of subtle startup and recovery logic creates a second copy that must track upstream fixes. Name this cost explicitly in the roadmap.
- **Mitigation that exists:** the `omnigent.server.routes.sessions` facade re-exports the underscored helpers (`omnigent/server/routes/sessions/__init__.py:370, 581, 584, 611, 640, 689`), and `fire.py` imports through it (`fire.py:2025-2028, 2157-2160`). `coral.omni` must import **only** from that facade, plus a small list of public modules, guarded by contract tests.

### 2.3 Per-replica, in-memory state the engine cannot trust

| State | Where | Coral consequence |
|---|---|---|
| `_session_status_cache` (status truth for edges) | `helpers.py:5127-5130` | Edges happen only on the replica that holds the runner tunnel. The engine worker for a run may be on another replica. |
| Pending-elicitation index and the single observer | `pending_elicitations.py:29-37, 70` | Gates cannot rely on it. They need their own durable rows (DD§11 agrees). |
| Disconnect grace timers | `app.py:4041` | A server restart loses them, so a runner that died during the restart is never marked failed. The engine needs its own `runner_last_seen` staleness rule. |
| `_intentional_stop_sessions` | `common.py:695` | A stop issued by the engine before a restart is forgotten. |
| Live stream | `session_stream.py:9, 54` | Never a source of truth. |
| Runner tunnels / `_get_runner_client` | `orchestration.py:13101-13108` | Effects that talk to a runner must run on the replica holding its tunnel. |

**Recommendation:** v1 is **single-replica only**, and Coral refuses to start its workers when multi-replica is configured. The scheduler already refuses some backends (DD§6.5), so there is precedent.

### 2.4 Ambient scopes background workers must enter

Background code reads `current_workspace_id()` and account authority from ContextVars. `fire.py:581-585` enters both `account_authority_scope` and `host_owner_scope`. `session_live_state.submit` copies the caller's contextvars precisely because a bare executor "would run the write at the default workspace (0)" (`session_live_state.py:123-145`). Every Coral worker, effect and timer must enter `workspace_scope(row.workspace_id)`, `account_authority_scope(user_id, generation)` (`omnigent/db/account_authority.py:79-90`) and `host_owner_scope`. Missing one is a silent multi-tenant no-op, not an error. Write a lint or test for it; `dev/lint/lint_workspace_scoped_cache.py` (S39) is the precedent.

### 2.5 SQLite single writer

- **Configuration:** `PRAGMA busy_timeout=20000` and `BEGIN IMMEDIATE` for write makers (`omnigent/db/utils.py:325, 958-972`). The local default database is SQLite, and the repo's CLAUDE.md mandates a shared `~/.omnigent/chat.db` in development.
- **Where Coral adds writes:**
  - DD§9.2 proposes a fingerprint row after **every** shell or file tool result;
  - a signal row per status edge;
  - log and state rows per transition.

  With 5-10 concurrent agents this roughly doubles write volume on the one lock that also serves transcript appends.
- **Mitigations:** fingerprint only evidence-candidate commands and the final submit (§3.1); poke signals in memory (§11); batch log appends.

### 2.6 Best-effort everywhere

Live status (`session_live_state.py:155`), PostToolUse observer relay (1 s curl, DD§9.1), policy attach failures in the runner precedent (DD§8.1), and native transcript mirroring are all best-effort. The engine's only reliable inputs are the durable transcript (`list_items`) and Coral's own tables. Design reconcile around those two.

---

## 3. Deceptively difficult features (ranked)

Ranking is by expected engineering surprise times centrality. "Size" is a relative signal, not an estimate.

### 3.1 Evidence: "last change" fingerprinting across modes. Rank 1

Why it is deceptive:

1. **The ordering trap.** Formatters and auto-fixers (`prettier --write`, `ruff format`, `eslint --fix`) *are* the checks the author asked for, and they change files. The rule "an evidence command counts only if its before-fingerprint equals the step's final fingerprint" (DD§9.2) invalidates every earlier test run when the format step changes anything. Agents will loop through test, format, test, lint --fix… and burn attempts. Snapshot tests, lockfile rewrites (`npm install` inside test scripts) and generated code that is *not* gitignored cause the same thing. **Decide:** per-check "may modify" flags, with check-only variants for formatters, or a "final pass" semantics: the last run of each required command must come after the last non-check change.
2. **Cost.** `git status` "can take seconds" (comment at `omnigent/runner/resource_routes.py:1240-1241`). Running it after every tool call slows agents and adds SQLite writes.
3. **Four different sources.**
   - claude-sdk: `sys_os_*` via the server MCP path; good.
   - codex: `commandExecution` items, after the fact.
   - claude-native: transcript mirror plus a best-effort PostToolUse relay.
   - codex-native: forwarder items.

   A command record's exit code is `exitCode` in Codex and parsed text in `sys_os_shell` output ("return stdout, stderr, and exit_code", `omnigent/tools/builtins/os_env.py:350`). `bash -c 'pytest || true'` exits 0.
4. **Nested worktrees escape the fingerprint.** Claude worktree sub-agents do this (DD§9.2).
5. **Multi-agent steps.** Whose evidence counts, and against which workspace (DD§20.2 Q5)? It is undefined.

**Reuse the deep dive missed:** the runner already serves a git-status-based changed-files list per session environment: `GET /v1/sessions/{id}/resources/environments/{env}/changes` (`omnigent/runner/resource_routes.py:1230-1276`, proxied by the server at `omnigent/server/routes/sessions/routes_resources.py:2841-2863`). It has `status`, `modified_at` and `lines_added/removed`. Hashing that list plus `HEAD` is a cheap fingerprint without a new host frame (S40). The server can also execute any tool in a session's environment by calling the runner's `POST /v1/sessions/{id}/mcp/execute` (`omnigent/runner/mcp_routes.py:111`; server-side precedent `orchestration.py:13097-13135`). That is a ready channel for Coral-run checks and for `git rev-parse`/`git diff --stat`. It needs a live runner (wake first) and `os_env` on the session's spec (`_require_os_env`, `resource_routes.py:1236`). **UNVERIFIED:** whether native-mode sessions expose an `os_env` environment for this endpoint.

### 3.2 Merging parallel code changes in worktrees. Rank 2

- **D8:** a merged result has no evidence. Something must run checks after every merge.
- **Merges must happen inside the run worktree**, because a branch can be checked out in only one worktree (DD§13). Any agent reading the run worktree (reviewers, the orchestrator) sees a tree that changes under it mid-merge. Reads need a snapshot ref.
- **Per-agent worktrees need setup** (dependency install, `.env` copy). That costs minutes and gigabytes per agent per step, for example `node_modules`.
- **Conflict-resolution loop.** "The orchestrator assigns one of the step's agents to resolve the conflict" means a new activation type, a new tool (none listed in D4§7.2) and a new evidence pass.
- **Branch naming:** `coral/<run>` and `coral/<run>/agent-1` cannot coexist (DD§13).
- **Submodules and LFS.**
- **Recommendation:** cut multi-writer from v1. The validator rejects more than one code-changing agent active in the same region. Parallel read-only reviewers stay allowed.

### 3.3 Derived joins, scope keys, repeat-for-each, loops and failure paths. Rank 3

This is the semantic core. Every table, signal, idempotency key, gate visit and evidence record is keyed by `(run, node, item_path, iteration_path)` (DD§5.3.4).

- **Mixed AND-join and loop re-entry (D6).**
- **Single-entry/single-exit regions (V2)** reject diagrams authors will naturally draw, such as "a critical finding in one parallel branch goes straight to the human gate". The validator's error messages become product UX.
- **Failure paths that leave a parallel region** must cancel siblings (interrupts that discard vendor sessions, C-F34) and leave their worktrees dirty.
- **Repeat-for-each with per-item gates.** With the sequential default, each item waits for a human before the next starts, so ten PRs means ten serial human waits. Gate batching is an unaddressed UX requirement.
- **Multi-agent steps must route through an orchestrator node to branch** [D4§5.3]. Trivial diagrams then need an LLM decision (cost and latency) just to pass a label through.
- **This is tractable** if the validator enforces block structure (series-parallel regions plus structured loops). Block-structured workflow nets are sound by construction, which also makes "exhaustive Simulate" (DD§15.1) redundant (§11).

### 3.4 Session refresh with a stitched transcript. Rank 4

- Lifting a `Request`-bound closure out of a 42-commit-per-month file (C16).
- A new `SupersessionReason` (openapi churn).
- Identity labels copied onto the fork (C16).
- Native modes have no fork path. Their `/clear` is a different, hook-driven rotation (§5.6).
- The window is unknown for some models (DD§8.9).
- It must coordinate with each vendor's own auto-compaction.
- The stitched-view UI is new.
- An in-flight `submit_handoff` from the old session may land after the switch.
- **Value is low for step agents,** which are fresh-context and short-lived by design. Cut from v1 (§11).

### 3.5 Two-way YAML and canvas sync that preserves comments and confirmed translations. Rank 5

- **Comment attachment.** The `yaml` Document API "may associate comments with a different node" (DD§14.4).
- **Stored translations must stay attached** to the text they translate.
- **Stable ids:** the canvas layout file is keyed by node ids that authors could rename.
- **Concurrent edits** in the Monaco pane and on the canvas.
- **The server cannot read or write repository files on a host** (§10.3).
- **Recommendation:** v1 is one-directional.
  - Either the canvas is the editor and YAML is generated (comments not preserved, documented),
  - or YAML is the source and the canvas is a read-only view with structured property panels that issue AST patches for a small set of fields.

### 3.6 LLM translation of rules into enforceable policies with confirmation. Rank 6

- **No model-call facility exists outside sessions** (DD§10.7).
- **Translations must target registered handlers.**
- **Validation against a per-mode capability matrix** that has no probes yet (F2).
- **Invalidation on any change:** text, profile, mode or registry.
- **Partial-order checks for "inner only stricter" (V8)** are hard to do generally on CEL.
- **Recommendation:** v1 has a catalog of about 8 rule templates, each mapped to an existing builtin:
  - `read_only_os`, `worktree_guard`, `blast_radius` and `spawn_bounds` (`omnigent/policies/builtins/orchestration.py:352-757`);
  - `cost_budget`;
  - egress allowlist (`os_env.sandbox.egress_rules`);
  - "ask before editing path X" (a CEL template);
  - "notify if over N minutes" (an engine timer).

  Each takes typed parameters and has a plain-words renderer. The LLM may *suggest* a template and parameters, but it is not the enforcement artifact. Free-form "Required" rules wait for v2.

### 3.7 Native-mode turn-end detection and session rotation. Rank 7

- **Turn end:**
  - `TurnComplete` is a delivery receipt (C26).
  - claude-native's real edge is a Stop-hook `turn_completed=True` that exists only on the live event and is not persisted. A level-triggered reconcile cannot see it after a restart.
  - PTY-quiet idles look identical in `live_status`.
- **codex-native:** no flag (C27), and rotation is triggered by any non-sub-agent, non-ephemeral `thread/started` (`omnigent/harnesses/codex_native/forwarder.py:2901-2945`).
- **`/clear`:** see §5.6.
- **Native hooks fail to ASK, or fail open on early returns (C3).**
- **This is the highest-churn area of the codebase** (`bridge.py` 83 commits, `runner/native/orchestration.py` 56).
- **Recommendation:** no native modes in v1.

### 3.8 Amendments to running runs. Rank 8 (high cost, low v1 value)

A Camunda-style migration (DD§6.8) needs mapping validation, counter carry-over, simulation from current state and a run lock. **Replace in v1 with** "cancel and restart from node X, carrying selected handoffs", a run-start option that reuses Simulate's reducer.

### 3.9 Take-over and hand-back. Rank 9

**Reuse that makes it cheap:**

- **`created_by`** marks human-authored items, but it is `None` in single-user mode, so it cannot tell the engine from the user locally (`omnigent/entities/conversation.py:894-903, 939-950`).
- **`stable_id`** is a deterministic item id with exact-retry detection (`conversation.py:904-910`; `helpers.py:7915-7942`).
- **How to use them:** the engine stamps every message it sends with a `stable_id` derived from the effect key. Any `role=user` item whose id is not engine-derived is user-authored.
- **Take-over then becomes** the same state as "pause this activation" plus a hand-back command that recomputes the fingerprint. No new Omnigent state is needed.

### 3.10 Sandbox sleep at gates. Rank 10

- Managed sandboxes suspend when idle, and non-resumable providers relaunch a new generation (DD§13), which risks unpushed work.
- **Checkpoint pushes need git credentials and a remote**, so non-code and plain-folder workflows have no checkpoint path.
- **v1 (local-first) can defer managed sandboxes entirely.**

### 3.11 Orchestrator conversation semantics. Rank 11, and under-specified

The user chats with the orchestrator ("Talk to the orchestrator to steer", D4§13). The engine also sends decision requests, handoff collections, watchdog reminders and (if children) `SubagentBlockNotifier` wake notices (§6.2), all into the **same** session.

- On claude-sdk, mid-turn input is buffered into a continuation turn (F33). A decision request can sit behind a user chat turn.
- A user asking "skip the tests" produces illegal tool calls that count toward the rejected-call pause [D4§7.3].
- **Unspecified:**
  - how a run starts (the run dialog, or the user typing into an orchestrator that then needs a `start_run` tool);
  - how handoff collections reach the orchestrator (D9);
  - whether runs with no decision nodes still pay for an orchestrator session.

---

## 4. Concurrency and state-consistency problems

### 4.1 Races

| Race | Failure | Required design |
|---|---|---|
| Gate answer vs watchdog reminder vs run cancel vs amendment | Double advance, or a reminder delivered after resolution | CAS on `coral_gate_visits(status='open')` plus the run `version`. Effects **re-validate state at dispatch time** (drop the reminder if the gate is already resolved). Answers carry the visit token, and an answer to an earlier loop visit is rejected (DD§6.2). |
| Watchdog reminder vs orchestrator's in-flight `choose_arrow` | The orchestrator reads "please decide" after it already decided (claude-sdk buffering) | The reminder effect checks the decision-request state just before sending. Accept that the race window cannot be closed fully, and make the text idempotent ("If you have already chosen, ignore this"). |
| **Duplicate `submit_handoff` from model retries** | A model retry after a timeout uses a **new** `call_id`, so `tool:{session}:{call_id}` keys do not dedupe (DD§7.2) | Slot-state dedup: a slot in `handoff_accepted` rejects with "already accepted, here is the receipt". A slot in `evaluating` returns "evaluation in progress". This requires a per-slot evaluating lease, or two concurrent evaluations can both pass. |
| Duplicate `submit_handoff` after refresh or rotation | The old session's in-flight turn submits after the slot moved | Store a `session_generation` on the slot. Accept only from the slot's current session id, and log late submits as superseded. |
| Submit arrives after cancel, region cancel or take-over | Work lost silently | Reject with an explicit reason and log it. The UI shows "handoff arrived after cancel". |
| Steering vs closing | A user steers a claude-sdk step agent; the input is buffered until the turn ends (F33); the agent has already called `submit_handoff` and the step closes; the steering message lands in a closed step | The step stays open while engine-known pending input exists for any of its sessions, or steering messages are refused once a slot is `evaluating`. The orchestrator relaying the user via `message_agent` has the same problem. |
| Join arrivals on the same scope | A fast source sends twice, and two arrivals are batched into one join firing (DD§5.3.4) | Unique `(activation, arrow, scope)` arrival rows inside the transition transaction. |
| Reducer under asyncio with `to_thread` | Tool handlers (inside HTTP requests) and the reconcile loop both call `apply_transition`. On SQLite `BEGIN IMMEDIATE` serializes the writes, but the reducer ran on a stale read, so the version check fails | A retry loop that **re-reads and re-runs the reducer** (not just the write), with bounded attempts. Optionally a per-run in-process asyncio lock in single-replica v1 to avoid churn. |
| Laptop sleep and wake | Every due timer fires at once on wake: watchdog alerts, reminders, overdue alerts | Coalesce timers per run on wake. The reconcile pass evaluates "is this still relevant" before alerting. |
| Concurrent runs on the same repo | Two runs create worktrees from the same base and both merge back | Out of scope for the engine (the human gate approves the merge), but branch names must be per run, and "merge to main" must not be automatic. |

### 4.2 `submit_handoff`: synchronous or asynchronous (a must-decide)

| Option | Behaviour | Pros | Cons |
|---|---|---|---|
| **Synchronous** | The tool call blocks while the engine fingerprints, checks evidence and maybe runs Coral checks | Simple feedback loop | Evaluation is tied to an HTTP request on one replica (C22). A server restart drops it and the agent retries. Harness-level MCP tool timeouts are **UNVERIFIED** for long evaluations (Claude Agent SDK and Codex `dynamicTools`). |
| **Asynchronous (recommended)** | Validate the schema synchronously and return "received, evaluating; do not end your work yet" or "received, you may stop". Evaluate in a worker, and on failure send a feedback message that starts a new turn | Durable; matches the level-triggered design | One extra turn per failed evidence. The agent may end its turn before the result, which is fine. |

### 4.3 Effect-dispatch crash windows

| Window | What breaks | Fix |
|---|---|---|
| After the session is created, before `session_created(id)` is recorded | Orphan session | Create with a deterministic `coral.effect_id` label and look it up on recovery (DD§6.1). This conflicts with S26 reservation (D13) and with refresh label copying (C16). |
| After the brief is sent, before it is marked sent | Duplicate brief and duplicate work | `stable_id` gives transcript idempotency, but the server **still forwards** an exact retry to the runner ("A persisted retry may still need forwarding…", `orchestration.py:7300-7303`). So `stable_id` alone does not prevent a second turn. **Recovery must read first:** `conversation_store.get_item(session_id, stable_id)` (as `orchestration.py:3137` does), and if the item exists, do not resend. |
| After the policy is attached, before it is marked | Duplicate session policies; counters such as `max_tool_calls_per_session` may double-count | Deterministic policy names, and check-then-create. `fire.py:1695-1700` (`_cost_budget_policy_id`) is the precedent. |
| After the worktree is created, before it is recorded | Orphan worktree | Deterministic path and branch (`fire.py:1613-1638` precedent), so a retry is "already exists, adopt it". |
| Mid-merge | Half-merged tree | `git merge --abort` on recovery when `MERGE_HEAD` exists, then retry. Merges of already-merged branches are no-ops. |
| After the gate elicitation is published, before it is recorded | Duplicate prompt | The gate row is committed *before* publishing (DD§11), and publishing is idempotent by elicitation id derived from the visit token. |

### 4.4 Optimistic versioning on SQLite

On SQLite, `BEGIN IMMEDIATE` already serializes writers, so `runs.version` mostly guards against *stale reads*, not concurrent writers. The real cost is the retry loop in §4.1. On Postgres or CRDB, `run_write_transaction` retries 40001/1213 (`omnigent/db/utils.py:1032-1082`). Make sure the reducer re-runs inside the retry, not just the SQL.

### 4.5 Multi-replica (explicitly out of v1)

The edges, tunnels, elicitation index and grace timers are per replica (§2.3). If multi-replica is ever needed: a durable `coral_signals` table, effects sharded by tunnel owner (the `owned_hosts` contract), Postgres or CRDB only. Keep the store interfaces shaped for it, but do not build it in v1.

---

## 5. Interruption, recovery and resumability edge cases

### 5.1 Server restart mid-effect

- **Lost Omnigent state:** in-memory grace timers (`app.py:4041`), the pending-elicitation index (C7), `_intentional_stop_sessions` (C11), the status cache, and parked elicitation futures.
- **Engine recovery:**
  - re-lease expired effects and apply the read-before-write checks in §4.3;
  - re-publish every open gate from `coral_gate_visits`;
  - mark any slot whose runner has `runner_last_seen` older than T as suspect. T must be engine-owned, because Omnigent's grace timer died with the process.
- **Policy ASKs that were pending inside step sessions** (native `_hold_native_ask_gate_impl`, `orchestration.py:2654`): whether they re-publish after a server restart is **UNVERIFIED**. If they do not, the step hangs in `waiting`. The reconcile pass should alert on "session waiting with zero pending elicitations".

### 5.2 Runner loss mid-step

- **Two different conditions:**
  - the host is offline and Omnigent holds the turn for up to 72 h (C17);
  - the runner died and the host is alive (`_on_runner_exited`, DD§6.7).
- **The fencing hazard nobody covers (D14).** If the engine restarts the step in a **new session** while Omnigent is still holding the old turn, the laptop can wake and the old turn can **resume** (`_hold_for_offline_host` docstring: "usually resumes the turn when it wakes"). Two agents then edit the same worktree. Required:
  - **(a)** do not restart while Omnigent's hold is active for that session; treat it as `paused(infra)`;
  - **(b)** if the engine does restart, first stop the old session (`stop_session` is **non-sticky**, DD§8.1) *and* move the restart to a **fresh worktree or branch**, so a zombie writes somewhere harmless;
  - **(c)** reject any `submit_handoff` from the old session by `session_generation` (§4.1).
- **Worktree policy on restart:**
  - Reset to the start commit (DD§13): clean, but loses partial work and cost.
  - Keep: the new agent inherits unknown partial edits, and the fingerprint baseline is wrong.
  - **Recommendation:** commit a checkpoint of the dirty tree to a side ref for forensics, then reset.
- **Sub-agent children are skipped by Omnigent's relaunch** (C11). The children topology makes the engine the only recovery mechanism.

### 5.3 Host offline for 72 h, and plan-limit pauses lasting days

- **Pause semantics are engine state** (`paused(infra|plan_limit)`), not Omnigent state.
- **During long pauses, reapers fire:**
  - runner idle watchdog, default 1 h (`omnigent/runner/_entry.py:162-199`);
  - native pane reaper, default 1 h (`omnigent/terminals/pane_reaper.py:85-87`), and capped for sub-agent panes (`pane_reaper.py:146-157`), so child-topology native steps are reaped *sooner*;
  - SDK process manager, default 1 h (F13).
- **On resume,** the engine must wake the runner (`ensure_runner_connected`, DD§8.1).
  - Headless modes lose the vendor session after a runner restart (F34), so the next turn replays history. That is a cost and quality hit, so log it.
  - For native modes, whether resuming a reaped pane restores the TUI conversation is **UNVERIFIED**.
- **Long pauses also expire credentials:** OAuth tokens and the direct-path policy bearer (F12, `PolicyHookReauth`). An `auth` error class must pause, never switch accounts (D4§7.8).
- **Show resume times** for weekly plan windows (DD§12).

### 5.4 The user deletes or edits a step session, or its policies

- **Deleting a session** is a hard delete: items are gone and there are no foreign keys. Every evidence record must **snapshot** what it relied on (command, exit code, fingerprint, item id) at acceptance time, not just reference `session_item_id` (DD§7.2 `coral_command_observations` only references it). The engine treats a deleted active session as `infra.runner_lost`, with the user as the cause, and pauses rather than silently restarting.
- **Editing or deleting session policies** needs `LEVEL_EDIT`, and the owner has it (`omnigent/server/routes/session_policies.py:30, 182, 337, 414`). In single-user mode the "attacker" is the user. Options:
  - **(a)** a reserved-prefix policy name that only the engine may mutate (S26);
  - **(b)** reconcile-time drift detection: the engine re-reads attached policies each reconcile, re-attaches missing ones and logs "rule tampered".

  Recommendation: **(b)** in v1. It is non-invasive and works for owners. Add (a) when teams arrive.
- **The owner can change launch args and permission or approval modes** (`routes_core.py:3136-3150`). For native sessions this can move a run-owned session into a mode that prompts on every tool call, which stalls it unattended. `fire.py` already has `session_unattended_disallowed_mode` and `_unattended_permission_problem` (`omnigent/server/scheduled/fire.py:958-997`). **Reuse that check** at brief time and at every nudge.

### 5.5 The user archives a session

Archive (OWNER level) spawns `_spawn_archive_stop(..., delete_worktree=body.delete_worktree)` (`routes_core.py:4098-4108`) and publishes an `idle` edge without persisting it. That edge reaches the completion hook as "succeeded" (C1).

- **Risks:**
  - the engine misreads it as a turn end and nudges, which starts a new turn in an archived session;
  - `delete_worktree=true` removes the run's worktree, although `_remove_session_worktree_best_effort` checks for other live sessions (`exclude_conversation_id`, `helpers.py:10294-10330`).
- **Required:**
  - the engine reads `archived` on reconcile and treats it as a user pause or cancel of that slot;
  - the run worktree is **engine-owned**, not created through a session's `git` options, so no session archive can delete it.
- **UNVERIFIED:** whether posting a message to an archived session unarchives it.

### 5.6 The user types `/clear` in a native session

- **claude-native:** `_rotate_session_on_clear` (`omnigent/harnesses/claude_native/hook.py:419-480`) calls `_create_clear_replacement_session` (`:542-628`). That does GET old → `POST /v1/sessions` with `agent_id` and **all labels** (`:569-584`) → PATCH the runner binding → transfer the terminal → re-key the old session's bridge id to `"-cleared"`. The body is `{"agent_id", "labels", title, project}` only (`omnigent/native/_native_supersession.py:24-51`). The replacement therefore:
  - **(a)** is a **top-level** session, so a step that was a child of the orchestrator leaves the spawn tree, along with root-policy inheritance and the cost tree;
  - **(b)** has **no session policies**, so Required rules attached as session policies silently vanish;
  - **(c)** carries copied `coral.*` labels, or fails with 400 if S26 reserves the prefix.
- **codex-native:** rotation is triggered by `thread/started` (`forwarder.py:2901-2945`).
- **Mitigations:**
  - Follow rotations durably through the copied bridge-id label (`BRIDGE_ID_LABEL_KEY` setdefault at `hook.py:577`) or through Coral labels.
  - Re-attach policies on detection.
  - Or block `/clear` for run-owned sessions. **UNVERIFIED:** whether Claude Code fires `UserPromptSubmit` for built-in slash commands. If it does not, the deep dive's "block `/clear` through the UserPromptSubmit gate" (DD§8.8) is not possible.
- Yet another reason to keep native modes out of v1.

### 5.7 Account revocation or regeneration

Runs record `account_generation` (DD§7.1). Once the generation changes, `require_active_account` (`omnigent/db/account_authority.py:145`) fails every engine write for that run. Without handling, the reconcile loop errors forever. A terminal `failed(auth_revoked)` transition must be writable **without** the account check, or performed by a system authority, and the effect dispatcher must stop.

---

## 6. Agent execution isolation and lifecycle

### 6.1 Session topology: challenging DD§8.2's "children by default"

**Hazards of children that DD§8.2 does not list:**

1. **`SubagentBlockNotifier` wakes the parent agent** when any child's elicitation stays unanswered for `_BLOCK_WAKE_ESCALATION_DELAY_S = 120.0` (`omnigent/runtime/subagent_block_notifier.py:55`). The parent lookup is plain `child.parent_conversation_id` (`:297-300`). Any step agent blocked on an ASK for two minutes therefore injects a notice into the **orchestrator** and starts an orchestrator turn the engine did not request. That turn consumes usage, may call engine tools out of turn, and confuses nudge accounting.
2. **Native child panes get a capped idle timeout** (`pane_reaper.py:146-157`).
3. **Relaunch-on-host-return skips children** (C11).
4. **A native `/clear` detaches a child** into a top-level session (§5.6).
5. **All children share the orchestrator's runner** (C20). That gives one failure domain, one host for every step (no per-step sandbox), and caller identity proven only at runner granularity (DD§8.6.5). Every step agent with shell access shares that runner. **UNVERIFIED:** whether agents can reach runner-local endpoints to impersonate sibling sessions.
6. **Root session policies leak** (C21). Orchestrator spec guardrails do not.

**Benefits of children:** sidebar hiding, `cost_budget` tree spend, inherited sharing, and the existing `child_sessions` watch path.

**Recommendation (UNVERIFIED UX):** **top-level sessions** labelled `coral.run_id`/`coral.step`, filed into a per-run or per-workflow **project** (`project_id` is a first-class create field; `_native_supersession.py:48-50` shows it being carried). This keeps them grouped in the sidebar with `SIDEBAR_GROUPING_UI` on by default (`feature_flags.py` grouping flag `default_enabled=True`), with engine-managed grants (`fire.py:1793` `_grant_owner` precedent). Re-evaluate once upstream's `family_id` sibling sessions ship (C30). They may be the native fit, with a run as a family.

### 6.2 Policy inheritance leaking orchestrator restrictions

Settled by C21: put "no write, no shell" in the **orchestrator's bundle guardrails**, never as a session policy on the orchestrator. If the children topology is chosen, never attach run-wide restrictions as orchestrator session policies, because every child inherits them (`builder.py:756-772`).

### 6.3 Reapers killing long steps or waiting runs

These are all deployment-wide, with no per-session override (F13):

- the runner idle watchdog (`runner.idle_timeout_s`, default 1 h, `omnigent/runner/_entry.py:162-199`);
- the pane reaper (`OMNIGENT_NATIVE_PANE_IDLE_TIMEOUT_S`, `pane_reaper.py:85-87`);
- the SDK process manager;
- managed `keep_warm_s`.

**A gate wait over an hour reaps everything,** which is fine *if* the engine always re-wakes before sending (§5.3). A single *turn* longer than an hour is protected only where the reaper checks active turns: the process manager does (F13); the runner watchdog is **UNVERIFIED**. Retest in phase 2 with a deliberately long turn.

### 6.4 Credentials

- **API keys for claude-sdk** reach the CLI only via `apiKeyHelper` from `executor.auth: {type: api_key}` or the server's global `auth:` (F48). Per-step bundles must reference secrets, not embed them. Bundles are stored as artifacts and bound to agent rows by content hash.
- **Pushing checkpoints and PR side effects** needs GitHub credentials inside sandboxes (`env_passthrough`, `omnigent/inner/datamodel.py:752`).
- **Never switch accounts** [D4§7.8]. Pin the account per run.

---

## 7. Persistence and migration risks

| Risk | Detail | Mitigation |
|---|---|---|
| Separate Alembic env across SQLite, Postgres, CRDB and MySQL | Coral must reproduce Omnigent's CRDB SERIALIZABLE preparation (`omnigent/db/cockroachdb.py:72-109`, private helpers, so more underscored imports), the "database newer than build" guard (`utils.py:745-765`) and MySQL constraints (no TEXT, index length limits, DD§7.1) | Treat `coral/db` as a small port of `omnigent/db/utils.py` patterns, with a contract test against Omnigent's helpers on every merge |
| Ordering | `coral_*` tables must not exist unless Omnigent is at head (C19), or a resumed CRDB bootstrap fails | Run `ensure_coral_schema` strictly after `get_or_create_engine` returns, and assert the Omnigent head |
| `create_all` | Omnigent creates every table on `OmnigentBase` and `ConversationBase` after upgrades (C18) | `CoralBase` is a separate `DeclarativeBase` with separate metadata |
| Autogenerate | Neither env filters tables (C9), so either lineage proposes dropping the other's tables | S30 plus Coral's own `include_name` |
| Test truncation and template | C10 | S31, plus a Coral-aware SQLite template fixture |
| **Shared data directory with stock Omnigent** | The default data dir is `~/.omnigent` (`docs/DATA_DIR_LAYOUT.md:3-13`). A Coral fork based on an older upstream refuses a database migrated by a newer stock Omnigent, which is the rollback-floor behaviour described at `f1c7a9e2b406…py:3-5`. Users with both installed corrupt each other's experience. | **Must-decide:** Coral defaults to its own data dir (cheaply, by setting `OMNIGENT_DATA_DIR` in Coral's launchers), and the dev CLAUDE.md rule about the shared `chat.db` applies to Omnigent development, not Coral |
| No foreign keys, hard deletes | Coral rows dangle when users delete sessions | Snapshot the evidence (§5.4); reconcile treats a missing session as an explicit state |
| `openapi.json` drift | Any Omnigent schema change Coral makes (S25) changes `openapi.json` (69 commits in 30 days) and fails `tests/server/test_openapi_drift.py` until regenerated. Coral's own routes are **absent** from the spec, because `scripts/dump_openapi.py:356` builds `create_app` without `extra_routers` | Regenerate on every merge, never hand-resolve. Decide whether Coral publishes its own OpenAPI document for its API |
| Upstream merge base | Release tags are not on `main` (DD§17) | Merge from `main` at a recorded SHA, or from release branches. Decide (§12) |

---

## 8. Coupling risks of the proposed abstractions

1. **`coral.omni` importing underscored helpers.** The facade (§2.2) reduces the blast radius, but the *semantics* of `_launch_runner_on_host` and `_dispatch_session_event_to_runner` change with upstream refactors (77 commits a month in `orchestration.py`).
   - **Alternative:** for create, send, interrupt, stop, policy CRUD, labels and grants, `coral.omni` calls Omnigent's **public REST API in-process or over loopback**, as the native hooks already do (`hook.py:447-470` uses `POST /v1/sessions` and PATCH). That surface is documented in `openapi.json` and drift-tested, so it is far more stable than private helpers.
   - In single-user local v1 there is no auth problem. Multi-user needs a service identity that acts as the user, which is a must-decide (§12).
   - Keep in-process seams only where no API exists: the turn-edge observer (S1), the engine-tool intercept (S10) and gate resolution callbacks (S6).
2. **Seams in high-churn files.**
   - S1: make the registry live in `session_live_state.py` (3 commits) with a one-line call in `helpers.py`. The deep dive already says so.
   - S10: introduce a module-level `server_tool_handlers` registry in a **new** file, with a 3-line lookup at the intercept site. Do not refactor the intercept.
   - S6 and S25: add new module-level functions in new files that call the closures' underlying primitives. Avoid editing the closures.
   - S34: add nav items through a small registry imported by `Sidebar.tsx` (one line), not inline JSX.
3. **Engine-tool opt-in on `AgentSpec` (S7).** This changes the spec schema, `parser.py` and `types.py`, plus the tool list in the runner (S8) and the native relay allowlist (S9). That is three places that must agree, so add a single contract test.
4. **Copy-adapted `fire.py` logic** (§2.2) is invisible coupling: upstream fixes in fire.py's startup and recovery do not flow to Coral. Mitigation: a CI diff watcher that flags upstream commits touching `fire.py` and `dispatch_scheduler.py` for manual review.
5. **Feature-flag enum (S33).** `tests/server/test_feature_flags.py` asserts exact `frontend_dict` defaults (DD S33), so every upstream flag addition conflicts. Upstream flags are also temporary by policy (`designs/FEATURE_FLAGS.md:42-44`). Coral's "workflows" switch is permanent product gating, so consider a **Coral-owned** setting outside Omnigent's enum.

---

## 9. Integration and backward-compatibility risks

- **Branding vs upstream merges.**
  - Cheap: `web/src/lib/branding.ts` (0 commits) and `themePalette.ts` (4).
  - Expensive: `Sidebar.tsx` (51) and `NewChatDialog.tsx` (52) for the hero "Direct the run…", and `index.css` (27).
  - Keep brand CSS in a separate stylesheet imported once, and route copy through `branding.ts`.
  - **Must-decide:** keep the Python package, module and CLI name `omnigent` internally (renaming means every import conflicts on every merge) and rebrand only user-visible strings. Apache-2.0 NOTICE obligations stay.
- **Mobile and Electron.** The shells load the server SPA, so routes ship with the server (DD§14.1). However, the iOS and Android apps and the Electron `productName` are upstream-branded binaries. Rebranding them is a distribution project (signing, store listings), not a code change. Deep links need S38. Push does not exist (C25), so "approvals on the phone" means only while the app is foregrounded.
- **OpenAPI and SDK.** `sdks/python-client` and the openapi site sync (`.github/workflows/sync-openapi-to-site.yml`) document Omnigent only. Coral's API needs its own client generation if external tooling (CLI, VS Code) will drive runs.
- **The engine-tools-on-every-session contract.** The tool surface is fixed at session creation (DD§8.6.2). Existing sessions cannot join a run, and sessions created by native `/clear` inherit the agent (and so the tools) but not run membership.
- **Host daemon version skew.** Any new host frame (S40) requires users' `omnigent host` daemons to run the Coral fork. `HostHelloFrame.capabilities` (`omnigent/host/frames.py:283-330`; the field at `:329`) lets the server feature-detect, so prefer the existing `/mcp/execute` and `/changes` paths (§3.1) and avoid new frames in v1.

---

## 10. Features that cannot be built independently, overlooked dependencies, and sequencing

### 10.1 Shared contracts to freeze first ("contract sprint", before parallel work)

| Contract | Consumers | Why it blocks |
|---|---|---|
| **K1. Workflow IR plus compiled graph** (node, arrow and region ids; derived join types; checked parts; scope-key shape) | Validator, reducer, Simulate, canvas, translation, tool-schema generator, run view | Every component keys on it |
| **K2. Run-log event schema** (kinds, bodies, `seq`, idempotency keys) | Engine, run-view stream, suggestions, replay test | The run view and suggestions can be built in parallel only against a frozen schema |
| **K3. `coral.omni` facade interface** (create, send with `stable_id`, read items and status, interrupt and stop, attach policies, wake, worktree, gate publish and resolve) | Engine effects, gates, tools, evidence | Lets engine work proceed against a fake |
| **K4. Engine-tool JSON contracts and error shapes** (including the missing `compose_handoff`/list tool, D9, and `blocked`) | Tool handlers, brief templates, framework instruction, tests | Prompts and handlers must agree |
| **K5. Evidence-requirement IR** (required commands, may-modify flags, ordering semantics, scope per agent or per step) | Translation UI, evaluator, run view | Resolves the ordering trap (§3.1) up front |
| **K6. Rule-template catalog IR** (template id, params, target builtin, per-mode enforceability) | Validator, bundle generator, UI | Replaces free-form translation in v1 |
| **K7. Per-step bundle generator** (profile plus rules to a bundle; secrets referencing) | Sessions, rules, roster | Single place where Omnigent spec semantics are encoded |
| **K8. Session-identity mapping** (slot to session plus generation; rotation following) | Tools, reconcile, run view | Required for refresh, rotation and restart |

### 10.2 Features that cannot ship independently

- **"Done when"** requires K5, a fingerprint source (`/changes` or S40), a command-observation source per mode, and the `submit_handoff` evaluation mode decision.
- **Multi-agent steps** require handoff collections, the orchestrator read path (D9), and (if code-changing) merging plus post-merge checks (D8).
- **Repeat-for-each** requires scope keys in *every* table from day one. It cannot be bolted on in phase 6, as D4§18 implies.
- **Human gates** require durable rows, elicitation surfacing (S5 and S6, or the public `mcp_elicitation` event), *and* a delivery channel. Without delivery, unattended gates are invisible (C25).
- **The run view** requires the K2 stream endpoint and the topology decision (watch-set S35 vs `child_sessions`).
- **Budgets** require tree spend (children) or engine sums (top-level), so they depend on the topology decision.

### 10.3 Overlooked dependencies

1. **Loading workflow definitions.** D4§12 puts YAML in `.coral/workflows/` in the user's repo. The server cannot read file contents on a host: `GET /v1/hosts/{id}/filesystem/{path}` only *lists* a directory (`omnigent/server/routes/hosts.py:1599-1625`), and file writes are session-scoped (DD§14.4). Phase 1 ("engine core") therefore cannot load a workflow from a repo without one of:
   - **(a)** a session-scoped read via the runner filesystem routes (`resource_routes.py:1032`), which needs a session;
   - **(b)** a new host frame (protocol change);
   - **(c)** storing workflow versions in the DB and importing or exporting them through the web or CLI. **Recommended for v1.**
2. **Gate notification channel.** No phase in D4§18 owns it.
3. **Unattended-mode preflight for sessions:** `fire.py:958-997`, reused (§5.4).
4. **The engine's service identity** for background actions in multi-user mode.
5. **The run-start UX contract** (run dialog vs chatting with the orchestrator; §3.11).

### 10.4 Sequencing corrections

D4§18 and DD§19 order the work: core, then agent steps, then evidence, then rules, then canvas, then structure, then Codex, budgets and amendments, then suggestions. Corrections:

| # | Correction | Reason |
|---|---|---|
| Q1 | **Move reducer-level parallel split/join, repeat-for-each and loop scoping into phase 1.** Defer only group and block *UI* to phase 6 | Scope keys pervade every table, so retrofitting them is a migration plus a rewrite (§10.2) |
| Q2 | **Phase 0, "contract sprint"** (K1-K8, flag, packaging S29, migration env S30/S31, lifespan S32 plus cli.py, data-dir decision) before phase 1 fans out | Enables parallel teams |
| Q3 | **Move a minimal read-only run view** (run-log stream plus path highlighting on a static graph render) **into phase 2** | Debugging agent steps without it is blind. The full canvas editor can stay in phase 5 |
| Q4 | **Move multi-agent merging out of phase 3 (evidence) into phase 6** with parallel steps, or cut it from v1 | It is meaningless before parallel steps and multi-writer exist |
| Q5 | **Move a minimal budget (activation cap plus per-session `cost_budget` backstop) into phase 2** | Cost amplification starts the moment agents run unattended |
| Q6 | **Decide subscription vs API key and the v1 modes before phase 2** | D4§17 already says this; the deep dive agrees. If the answer is "subscription users need claude-native", native hooks and turn-end (S2, S14, S15) jump to phase 2 and the plan's risk profile changes |
| Q7 | **Gate delivery (notification connector or explicit "app must be open") decided in phase 1**, built by the first showcase | Gates are a phase 1 feature |
| Q8 | **Session refresh (D4 phase 4) moved after v1,** except optional orchestrator handling | Step agents are fresh and short by design (§3.4) |
| Q9 | **Exhaustive Simulate (DD phase 1) replaced by block-structure validation** | Soundness by construction (§3.3) |
| Q10 | **Showcase realism.** The PR-review showcase needs repeat-for-each, a multi-agent roster, an orchestrator node, a loop, a gate and evidence. Under D4§18 that is reachable only after phase 6 | With Q1 and Q4 it is reachable after phase 3, with two Claude reviewers (DD§20.1 Q2) |

---

## 11. Simplification opportunities

Each item says what to cut, what remains, and the justification.

| # | Cut or simplify in v1 | What remains | Justification |
|---|---|---|---|
| S-1 | **Native modes (claude-native, codex-native)** | `claude-sdk` with **API key** only | Fail-ask and fail-open hooks (C3); `/clear` rotation that drops policies (§5.6); a turn-end that is not durable (§3.7); highest churn (`bridge.py` 83 commits). claude-sdk routes all workspace tools through gated, observed `sys_os_*` (C5). **Trade-off:** subscription-only users are unserved until v1.1, a product decision tied to the terms risk (DD§16). |
| S-2 | **Codex (headless and native)** | — | Headless codex cannot gate its own tools (C4); `dynamicTools` is experimental (DD§8.6). Matches DD§20.1 Q1. |
| S-3 | **Sub-agents in one session**, the fail-closed router, and the `step_roster` policy | Separate sessions only; deny vendor spawn tools for run sessions | Rosters hold by construction (DD§10.4), and a whole enforcement surface goes away. |
| S-4 | **"Up to" rosters and `assign_agents`** | Exact rosters | Removes one tool and one validation path. |
| S-5 | **Amendments** | "Cancel and restart from node X with carried handoffs" | §3.8. |
| S-6 | **Groups as rule containers, blocks, nested groups** | One level of "repeat-for-each region" (needed by the showcase), no group-scoped rules | V8 partial-order checks disappear. |
| S-7 | **Multi-writer steps and parallel code changes (merging)** | At most one code-changing agent per active region; parallel *read-only* reviewers allowed | D8 and §3.2. |
| S-8 | **Free-form LLM translation of Required rules** | About 8 typed rule templates over existing builtins; the LLM may suggest a template | §3.6. Rules stay "Enforced" only where the template is enforceable in claude-sdk, which simplifies the capability matrix to one column. |
| S-9 | **LLM translation of "done when"** | A picker over repository-detected commands (test, lint, format, typecheck) with "must pass after last change" semantics plus optional Coral-run checks | Same evidence engine, no save-time model calls, no re-confirmation churn. |
| S-10 | **Session refresh for step agents and stitched transcripts** | Vendor auto-compaction as the backstop; the orchestrator can be re-briefed per decision if needed | §3.4. |
| S-11 | **Two-way YAML and canvas sync** | One direction (§3.5); workflow versions stored in the DB, with import and export to `.coral/workflows/` | Also removes the host-file-read dependency (§10.3). |
| S-12 | **Exhaustive Simulate** | Block-structure validation plus user-scripted Simulate | §3.3. |
| S-13 | **`coral_signals` table** | Observer does an in-memory `poke(run_id)`; periodic resync (5-10 s) reads durable state | Signals are hints in the deep dive's own design (DD§6.2, §6.4). Single replica (§2.3) and claude-sdk-only (S-1) make durable turn-end derivable from the transcript plus `live_status` (`fire.py:2550-2577` rule). This avoids SQLite writes on the status hot path. Reintroduce the table for multi-replica or native modes. |
| S-14 | **`PersistentTaskScheduler`** for anything | A `coral_timers` table scanned by the same reconcile loop | C6. |
| S-15 | **S40 host frame** | `/changes` plus `/mcp/execute` (§3.1) | No host-daemon version skew (§9). |
| S-16 | **Verifier as a special feature** | A template pattern: a read-only step after the work step, routing back on "rejected" | Uses existing primitives; no new mechanism. |
| S-17 | **`ask_user` tool** | Gates plus the orchestrator's normal conversation | Fewer tools. Optional: claude-sdk's `AskUserQuestion` bridge already exists (`claude_sdk_executor.py:2556-2586`). |
| S-18 | **`message_agent` live messaging between parallel steps** | Handoffs plus orchestrator relaying at decision nodes | Removes the steering-vs-closing race (§4.1) and the routing tool. |
| S-19 | **Take-over as a distinct state** | "Pause activation" plus hand-back that recomputes the fingerprint; `stable_id`-based attribution | §3.9. |
| S-20 | **Children topology machinery** (S35 watch-set union; inheritance workarounds) | Top-level sessions in a project | §6.1. |
| S-21 | **REST-first `coral.omni`** (instead of underscored helpers) | In-process seams only for S1, S10 and S6 | §8.1. |
| S-22 | **EGM showcase** | PR-review showcase only | D4. |

**Where the deep dive over-engineers** (keep these on a "later" list, not in the v1 plan):

- Camunda-style amendments.
- Dead-path elimination.
- Exhaustive Simulate.
- Per-rubric-dimension judges with calibration.
- Held-out hidden tests, test-integrity diffs and JUnit parsing in v1. Keep them as phase-3+ hardening.
- ELK in a Web Worker. v1 can use dagre (MIT), which also removes the EPL/GPL licensing question (DD§14.4).
- Thirteen tables. v1 needs about 9: drop signals, merge amendments, and fold join arrivals into activations if derived joins stay block-structured.

**Estimated effect** (UNVERIFIED, judgment): the v1 seam set shrinks from 40 to about 14:

- S1, S4 or REST, S5, S6, S7, S8, S10, S12 (non-native half), S13, S22 (claude-sdk column only), S29-S33, S34 and S39.

These are deferred:

- S2, S9, S11, S14-S21, S24, S25, S26 (replaced by drift detection), S27 (retest only), S28, S35-S38 and S40.

---

## 12. Must-decide-before-coding decisions

Each decision names its blocking scope and a recommendation. "Owner" is a suggestion.

| # | Decision | Blocks | Recommendation |
|---|---|---|---|
| M1 | **Where workflow definitions live and how the server reads them** (repo file on host vs DB) | Phase 1 entirely | DB-stored immutable versions; import and export to `.coral/workflows/` (§10.3) |
| M2 | **Session topology** (children vs top-level plus project vs families) | Sessions, policies, budgets, sharing, run view | Top-level plus project in v1; revisit with `family_id` (§6.1) |
| M3 | **v1 agent modes and authentication** (claude-sdk with API key only? subscription path?) | Phase 2 | claude-sdk with API key (S-1, S13); product signs off on unserved subscription users |
| M4 | **Codex timing** | Capability matrix, showcase roster | After v1 (S-2) |
| M5 | **`submit_handoff` sync vs async evaluation** | Tool contract K4, evidence | Asynchronous (§4.2) |
| M6 | **Evidence semantics:** per agent or per step; fingerprint timing; formatter and fix ordering; may-modify flags; what counts as a change | K5, phase 3 | §3.1 "final pass" semantics with check-only formatter variants |
| M7 | **Multi-writer policy** | Phases 3 and 6, the merge feature | No multi-writer in v1 (S-7) |
| M8 | **Restart semantics after runner loss:** same-session relaunch vs new session; worktree reset vs keep; fencing | Reconciler, worktrees | Respect Omnigent's hold; on restart, stop the old session, use a fresh branch, checkpoint the dirty tree, and gate old submits by generation (§5.2) |
| M9 | **Join and loop semantics:** derived joins; back-arrow exemption (D6); region single-exit; failure paths in parallel regions; loop-limit counting and redirect point | K1, validator | DD§5.3 rules, with back-arrows exempt and block structure required |
| M10 | **Repeat-for-each contract:** ordering, empty list, per-item failure, concurrency, per-item gates and gate batching | K1, reducer | DD§5.3.5, plus a gate-batching UX decision |
| M11 | **Orchestrator model:** run start (dialog vs chat); how handoffs reach it (D9); missing tools; user chat interleaving; lazy creation for decision-free workflows | K4, phase 2 | Run dialog starts runs; handoffs injected into decision requests; add `compose_handoff`/`items` on `choose_arrow`; create the orchestrator lazily |
| M12 | **Gate delivery channel and gate authority** | Gates (phase 1), showcase | v1: inbox kind (S37) plus an explicit "keep the app open" notice; an email or chat connector as the first follow-up. Answers need `LEVEL_EDIT` on the orchestrator session |
| M13 | **Signal mechanism and replica model** | S1 design, tables | Single replica; in-memory poke plus resync (S-13) |
| M14 | **`coral.omni` coupling style** (REST-first vs private helpers) and the service identity for multi-user | All engine effects | REST-first (S-21); single-user only in v1 |
| M15 | **Run-owned session protection** (reserved labels or policies vs drift detection; what owners may do; `/clear`, archive and delete behaviour) | S26, reconcile | Drift detection plus archive and delete handling (§5.4-§5.5); no reserved prefix in v1 |
| M16 | **Profile model and pinning** (reusable user agents; revision pinning per run; where expected capabilities live; server-side, not localStorage) | Phases 2 and 5, D3 | Bundles via reusable agents; pin by content hash; capabilities in `params` (F39) |
| M17 | **Rules v1 shape** (templates vs free-form translation) | K6, phase 4 | Templates (S-8) |
| M18 | **Persistence details:** separate Alembic env, `CoralBase`, ensure ordering, test template, MySQL constraints | Phase 0 | DD§7.3 plus C10 and C19 refinements |
| M19 | **Data dir, package and CLI naming, feature-flag permanence** | Phase 0, distribution | Own data dir via `OMNIGENT_DATA_DIR`; keep the `omnigent` module name internally; a Coral-owned switch outside the upstream flag enum (§8.5) |
| M20 | **Upstream merge base and cadence** (release branches vs `main` SHA; tags are not on `main`) | Fork operations | Merge from `main` at a recorded SHA weekly; security cherry-picks out of band (DD§17) |
| M21 | **Budgets in v1** (activation cap, per-session backstop, estimate labelling) | Phase 2 | Activation cap plus `cost_budget` backstop; USD labelled as an estimate |
| M22 | **Context refresh in v1** | Phase 4 scope | None for steps; vendor auto-compaction as the backstop |
| M23 | **Minimal run view in phase 2?** | UI staffing | Yes, read-only (Q3) |
| M24 | **Requirements of record** (missing `coral-requirements.md`, D2): non-functional requirements, OS support, limits | Acceptance criteria for every feature | Product writes the minimum non-functional list before phase 1 exit |
| M25 | **Plain-folder (non-code) workspaces in v1?** | Evidence (content-hash manifests), restart snapshots | Defer; git worktrees only in v1 |

---

## Appendix A. Reuse the deep dive did not list

| Part | Location | Use | R/E |
|---|---|---|---|
| Changed-files API per session environment (git-status based) | `omnigent/runner/resource_routes.py:1230-1276`; server proxy `omnigent/server/routes/sessions/routes_resources.py:2841-2863` | Cheap workspace fingerprint (hash the list plus `HEAD`) | R |
| Server to runner tool execution | `omnigent/runner/mcp_routes.py:111`; server precedent `omnigent/server/routes/_sessions/orchestration.py:13097-13135` | Coral-run checks and git probes without a new host frame (S40) | E |
| Unattended-permission preflight | `omnigent/server/scheduled/fire.py:958-997` | Refuse or alert when a run session's mode would prompt unattended | R |
| Deterministic policy id precedent | `fire.py:1695-1700` (`_cost_budget_policy_id`), `fire.py:1714` (`_attach_cost_budget`) | Idempotent policy attach | R |
| `stable_id` exact-retry detection (beyond App. B's mention) | `omnigent/server/routes/_sessions/helpers.py:7915-7942`; read-before-write precedent `orchestration.py:3131-3137` | Idempotent briefs and user-vs-engine attribution | R |
| Host capability tokens | `omnigent/host/frames.py:283-330` (`capabilities`) | Feature-detect fork-only host behaviour if ever needed | R |
| Sessions facade re-exports | `omnigent/server/routes/sessions/__init__.py:370-689` | The only import surface for `coral.omni` private needs | R |
| Projects as sidebar grouping | `project_id` on create (`omnigent/native/_native_supersession.py:48-50`) | Group a run's top-level sessions (UNVERIFIED UX) | R |

## Appendix B. Method notes

- **Commands used:** `sed -n`, `grep`, `wc -l`, `git log --since/--until --oneline -- <file> | wc -l` and `git rev-parse HEAD`. No tests or servers were run.
- **Churn window:** 2026-10-09 to 2026-11-09, matching the deep dive's 30-day window. My total is 1,510 commits against the deep dive's 1,498; the window bounds differ slightly.
- **UNVERIFIED items, which need either a probe in phase 0 or 2 or a vendor-doc check:**
  - harness MCP tool-call timeouts for long `submit_handoff`;
  - whether `UserPromptSubmit` fires on built-in `/clear`;
  - whether native pane resume preserves the conversation after reaping;
  - whether native sessions expose `os_env` for `/changes` and `/mcp/execute`;
  - whether posting to an archived session unarchives it;
  - whether agents can reach runner-local endpoints to impersonate sibling sessions;
  - whether the runner idle watchdog spares a long active turn;
  - whether native policy ASKs re-publish after a server restart;
  - whether projects give acceptable sidebar grouping for run sessions;
  - Claude Code's auto-compaction point relative to the 70% threshold.
