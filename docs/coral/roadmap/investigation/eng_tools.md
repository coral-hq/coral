# Coral roadmap input: engine tools, policies and rule enforcement, elicitations and human gates, notifications and inbox, budgets

**Author role:** Staff Engineer (Agent 3).
**Repo:** `omnigent-ai/omnigent` at `2a9cbe2c2` (0.22.0.dev0).
**Sources:** `coral-design.md` (Draft 4), `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` (audit of Draft 3 at the same commit), `coral_UI_DESIGN_LANGUAGE.md`.
**Method:** I opened every `path:line` cited here at HEAD, except items marked **UNVERIFIED**. I read code and ran grep/find only. Nothing was built, run or edited in the repo.

**Verdict vocabulary:** Reuse (use as-is), Extend (add without changing current behaviour), Modify (change current behaviour), New, Replace, Remove.

**Seam numbering:** S1-S40 are the deep dive's ledger (§4.3). New seams in this document are **T-S41 to T-S47**. Where this document only makes an existing seam concrete, it says "S10, concrete".

---

## 0. Executive summary

1. **Engine tools have a clean transport, but two premises in the deep dive need correcting.**
   - Every mode does converge on `POST /v1/sessions/{id}/mcp`, and the `sys_advise_models` intercept (`omnigent/server/routes/_sessions/orchestration.py:13058-13069`) is the right place to hook in.
   - **Correction 1 (identity).** The endpoint authorizes *any* caller with `LEVEL_EDIT` (`omnigent/server/routes/sessions/routes_agent.py:482-485`). The intercept does not check that the call came from the session's bound runner. Single-user servers cannot always prove it either (`omnigent/server/routes/_sessions/helpers.py:11017-11019`). Engine tools need a runner-provenance check (**T-S41**), which can reuse `_require_cost_control_label_authority` (`helpers.py:11002-11042`).
   - **Correction 2 (idempotency).** The harness `call_id` never reaches the server. Only a per-proxy-call `_omnigent_operation_id` does (`omnigent/runner/proxy_mcp_manager.py:341, 415`; `omnigent/runner/mcp_execution_registry.py:27`). Deduplication is therefore operation-id plus run-level slot and decision state, not `tool:{session}:{call_id}` (deep dive §8.6).
2. **Tool schemas are fixed per conversation, so per-decision schemas will not work.**
   - The runner caches the tool list once per conversation (`omnigent/runner/app.py:5910-5935`).
   - Headless Codex restarts its app session when the tool signature changes (`omnigent/inner/codex_executor.py:5225-5246`).
   - The native relay surface is built once, at launch (`omnigent/runner/app.py:5364-5400`).
   - Consequences: step-agent schemas can carry enums (they are fixed per step bundle). The orchestrator's `choose_arrow` must use a generic `label: string`, validated on the server, with the legal labels listed in the decision message. This contradicts deep dive §5.4's "orchestrator schemas generated per decision activation".
3. **One extension declaration should drive S7, S8, S9, S11 and S12 (T-S42).** Today the tool name must be added by hand to five places: ToolManager, `_ALL_LOCAL_TOOLS`, `_NATIVE_RELAY_BUILTIN_TOOLS`, the Claude `--allowedTools` list and the Codex `approval_mode` table. Tool names "are part of the native approval contract" (`docs/session-messaging-tool-boundary.md:3-6`), and these lists already drift. I recommend an opt-in through `params.coral` in the per-step bundle, which needs no parser or AgentSpec change (`omnigent/spec/parser.py:290`; `omnigent/spec/types.py:1614`). It also respects the repo rule against adding lifecycle metadata to `AgentSpec` (CLAUDE.md, "Framework-owned instructions").
4. **Where Coral policies live matters more than the deep dive says.**
   - Policies inside a generated bundle's `guardrails.policies` are pinned per workflow version. The session-policy CRUD API cannot delete them, and they skip the 30 s session-policy cache.
   - Root *spec* guardrails do **not** flow to engine-created children that have their own `agent_id`. The policy engine loads the spec from `conv.agent_id` (`helpers.py:9352-9374`; `omnigent/runtime/policies/builder.py:613-616`). Only root *session* policies are inherited (`builder.py:761-772`). Root-bundle sub-agents are the exception: `_resolve_sub_agent_spec` resolves them by name (`builder.py:482-516`).
   - This refines deep dive §9.3 item 6. Recommendation: translated Required rules and the orchestrator guard go in bundle guardrails. Run-wide guards (pause, cancel, budget) go in a label-keyed **required-policy provider** (T-S44, which generalizes `_REQUIRED_APPROVAL_SPECS`, `builder.py:101-104`). Session-attached policies are used only for amendments, protected by S26.
5. **"Required rules hold" has more escape paths than S26 covers.** Besides session-policy PATCH/DELETE (`omnigent/server/routes/session_policies.py:308-437`) and session-label PATCH (`omnigent/server/routes/sessions/routes_core.py:3166-3184`):
   - policy-written labels bypass the reserved-label check (`omnigent/runtime/policies/engine.py:521-547`) — **T-S45**;
   - the owner can replace a session's agent bundle (`routes_agent.py:289`, owner-only at 343-347) — **T-S46**;
   - session MCP servers can be edited (`omnigent/server/routes/session_mcp_servers.py:169-222`) — **T-S46**.
6. **Gates.** The publish-without-park primitive already exists. It is the `mcp_elicitation` branch of `POST /events` (`omnigent/server/routes/sessions/routes_events.py:2222-2257`), and S6 should lift it into a request-free helper. The verdict path `_resolve_elicitation` (`orchestration.py:2400-2559`) does not know **who** answered, because neither caller passes the user (`routes_events.py:2214`; `omnigent/server/routes/sessions/routes_elicitations.py:127-131`). Approver authority and the run log need that identity (**T-S47**). The pending index lives in memory (`omnigent/runtime/pending_elicitations.py:46-59`), so open gates must be re-published at startup with **stable** elicitation ids, which keeps `/approve/:sid/:eid` links valid.
7. **Elicitation observers.** There is one observer slot, and `SubagentBlockNotifier` holds it (`pending_elicitations.py:68-87`; `orchestration.py:10855`). The notify path has no exception isolation (`pending_elicitations.py:183-198`). With step sessions as children, the notifier will **wake the orchestrator agent** whenever a step blocks on an approval (`omnigent/runtime/subagent_block_notifier.py:297-300`). That wastes turns and confuses the conductor. Run-owned children need an exemption (**T-S43**), on top of S5.
8. **Notifications.**
   - Confirmed: there is no web push, VAPID, APNs, FCM or email anywhere. Grep finds no sender. `web/ios/README.md:22` says "It does not implement APNs". Web Push is an open upstream issue (`designs/prioritization/issue-prioritization-v2.md:639`, #1751).
   - Gates published on the orchestrator session appear in the Inbox **approval** kind automatically, because it is driven by `pending_elicitations_count` (`web/src/pages/InboxPage.tsx:240, 251`).
   - Run alerts need a new `workflow` kind with a server feed and **server-side** acknowledgement. The automation kind keeps read state in localStorage (`web/src/hooks/useSeenAutomationFailures.ts:58-70`), which is wrong for alerts that should clear on every device.
9. **Budgets.**
   - `cost_budget` ASKs at soft thresholds and DENYs at the cap. On an *unpriced* model it **ASKs** (`omnigent/policies/builtins/cost.py:505-508`), although its docstring says DENY (`cost.py:36-41`). That ASK silently stalls an unattended step.
   - Run budgets are engine code. The engine sums `session_usage.policy_cost_usd` (falling back to `total_cost_usd`) across the run's sessions (`builder.py:1437-1494`). A label-keyed `run_guard` policy enforces the pause on every mode, and a budget "gate" elicitation asks the user.
10. **Gate integrity depends on the mode (new risk).**
    - claude-native writes a user bearer into the bridge-dir hook config (`omnigent/runner/native/orchestration.py:9290, 9832`). The agent runs as the same OS user, so its Bash can read the bearer and call the server API, including `POST /v1/sessions/{orch}/events` `approval`.
    - claude-sdk scrubs runner secrets from child processes (`omnigent/runner/identity.py:88-99`).
    - So "Human gates are never skipped: Enforced" holds against model mistakes and prompt injection, but not against a native agent with an unsandboxed shell. The validator should label it accordingly, or require a step sandbox that hides the bridge dir and server (UNVERIFIED whether any current sandbox does).

---

## 1. Discrepancy register for this area

| ID | Statement | Evidence at HEAD | Disposition |
|---|---|---|---|
| D1a | Draft 4 §4.1 and §6 call the "sub-agent router" a roster gate that becomes Enforced in fail-closed mode | `omnigent/runner/subagent_routing.py:1-8` ("which model the spawn should run on. The gate is **advisory**"); `omnigent/inner/hook_scripts/subagent_router.py:9-16, 83-84` | **Confirmed false.** Rosters come from separate sessions plus `coral.policies.step_roster` (§3.4) plus fail-closed native hooks (S14, S15). Remove "fail-closed router" from Draft 4 §16's patch list. |
| D1b | Draft 4 §4.1 and §5.5: "Approvals on any device … web push" | No push sender anywhere. `web/src/lib/browserNotifications.ts:8-10` (page-scoped Notification API; the service worker "intercepts nothing"); `web/ios/README.md:17-22`. `omnigent/runtime/policies/approval.py`'s `_await_elicitation` has test callers only (`tests/runtime/policies/test_ask_with_schema_validation.py:23`, `test_engine_session_state.py:733`). | **Confirmed false.** See §5.3 for delivery options. |
| D1c | Draft 4 §10: "Reaching a limit pauses the run and asks the user. This reuses Omnigent's `cost_budget` policy." | `cost.py:416-558` (ASK at thresholds, DENY at the cap; unpriced → ASK at 505-508) | **Confirmed false.** Run pause is engine code (§6). |
| D1d | Draft 4 §4.2: "`sys_cancel_task` does nothing" | Only the server stub returns `task_not_found` (`omnigent/tools/builtins/async_inbox.py:98-127`). The runner intercepts the call (`omnigent/runner/tool_dispatch.py:404-408, 7219-7225, 9098`). | **Stale.** It is irrelevant to engine cancellation anyway: the engine cancels through the session facade (S4). |
| D1e | Draft 4 §7.6: timers and the signal queue use `PersistentTaskScheduler` | Deep dive F10 and F29 | Out of my scope, but **gate reminders, decision watchdogs and overdue alerts** must be Coral timer rows (deep dive §6.6), not scheduler tasks. |
| D2 | `coral-requirements.md` is referenced (Draft 4 line 5) | `ls` shows only the three coral docs at the repo root | **Confirmed missing.** Product decisions that affect tools (ask_user blocking semantics, who may answer gates, alert channels) cannot be traced to requirements. |
| D3 | The UI doc keeps Inbox upstream-native, restyled (`coral_UI_DESIGN_LANGUAGE.md:153, 214-247`) | No `web/src/components/concerto/*` and no `concerto` string in `web/src` | Inbox stays upstream. The new `workflow` kind (S37) has **no visual spec** in the UI doc and needs one. |
| D4 | The Elephant-Goldfish template needs persistent sessions and per-member input scoping | Deep dive §15.3 | For tools: `activation_id` must be mandatory, a session may serve **several activations** (persistent elephant), and `message_agent` needs per-step isolation rules (a goldfish must not message the elephant). See §2.4. |
| **D5** (new) | Deep dive §5.4: "The orchestrator's schemas are generated per decision activation" | Per-conversation tool cache (`omnigent/runner/app.py:5910-5935`); Codex restarts on a signature change (`codex_executor.py:5225-5246`); relay built at launch (`app.py:5364-5400`) | **Correct it.** The orchestrator gets static, generic schemas. Step agents get static per-step enums. |
| **D6** (new) | Deep dive §8.6: idempotency key `tool:{session}:{call_id}` | The MCP params carry `_omnigent_operation_id` (a uuid4 per proxy call, stable across server reattach), not the harness call id (`proxy_mcp_manager.py:341, 409-418`). The native relay executor receives only `(name, arguments)` (`app.py:5392-5400`). | **Correct it.** Use operation-id for transport retries and run-level slot and decision state for semantic deduplication (agrees with deep dive §6.3). |
| **D7** (new) | Deep dive §8.6 item 5: "Caller identity comes from runner routing, never from the model" | The session id comes from the URL. The caller needs only `LEVEL_EDIT` (`routes_agent.py:482-485`). Runner proof is checked only for orchestration sends (`omnigent/server/session_orchestration.py:104-108`) and `cost_control.*` labels (`routes_core.py:3166-3184`). | **Extend:** T-S41. In single-user mode provenance is "the authenticated user", not "the runner". |
| **D8** (new) | Deep dive §9.3 item 6: "Root session policies and the root spec's guardrails apply to every child" | The spec comes from `conv.agent_id` (`helpers.py:9352-9374`). Child spec guardrails are appended only for `sub_agent_name` children of the root bundle (`builder.py:482-516, 728-751`). Root **session** policies are always inherited (`builder.py:755-772`). | **Refine.** It holds for session policies only. Engine-created children with their own bundle do not inherit root spec guardrails. UNVERIFIED for Coral's create path until S3 exists. |
| **D9** (new) | Draft 4 §5.3: on a merge conflict, the orchestrator "assigns one of the step's agents to resolve the conflict" | The §7.2 tool table says `assign_agents` is "Only for 'up to' rosters" | **Gap.** Add `coral_assign_task` (§2.4, contract 6), or a `mode` on `assign_agents`. |
| **D10** (new) | Draft 4 §7.3: overdue alerts "with the options to steer, extend or cancel" | Inbox cards have fixed per-kind actions (`InboxPage.tsx:486-526` for the automation kind) | The `workflow` inbox kind needs action endpoints (§5.2). |
| **D11** (new) | Draft 4 §9 reactions, e.g. "ask me first" | ASK timeout → DENY (`approval.py:142-146`); default `ask_timeout` = 86400 s (`omnigent/spec/types.py:40`); the native ASK gate behaves the same (`orchestration.py:2654-2690`) | Unanswered reactions on unattended steps silently become DENY after a day. The engine must observe the parked ASK (S5) and alert. |
| **D12** (new) | Draft 4 §7.2: `ask_user` is a "question to the user, outside the human gates", with blocking semantics unspecified | `MCP_PROXY_CALL_TIMEOUT_S` = 7260 s (`tool_dispatch.py:208, 228-229`) | Make it **non-blocking**. The answer is delivered as a message (§2.4, contract 5). |
| **D13** (new) | Deep dive §10.4: `step_roster` counters live in `session_state` | `apply_state_updates` rewrites the whole dict (`engine.py:612-615`). On the `/mcp` path, the build, evaluation and write are serialized per session, **per replica** (`_policy_evaluation_lock`, `orchestration.py:10416-10437`). On the native `/policies/evaluate` path, only the engine *build* is serialized (`routes_hooks.py:149-175`), so parallel native hook calls, or calls on two replicas, can lose increments. | Use stateless DENY lists for separate-session steps. Keep counters in Coral tables for sub-agent mode. |

---

## 2. Engine tools

### 2.1 Current code: how an Omnigent tool is declared, registered, transported and executed

**Tool class and schema format (Reuse).**

- `omnigent/tools/base.py:64-134` defines `Tool(abc.ABC)`:
  - `name()` and `description()` are abstract classmethods;
  - `get_schema()` returns an **OpenAI Chat Completions function schema**: `{"type": "function", "function": {"name", "description", "parameters": <JSON Schema>}}`;
  - `invoke()` raises `NotImplementedError` by default for runner-dispatched tools.
- `ToolContext` (`base.py:28-61`) carries `task_id`, `agent_id`, `workspace` and `conversation_id`. The model never supplies these.
- Schema-only precedent: `omnigent/tools/builtins/advise_models.py:1-155`. Its docstring says "This class exists solely to provide the tool **schema** … Execution is handled server-side". `invoke` raises `RuntimeError` (137-155). The schema uses `additionalProperties: false` and nested `required` (63-135).
- A second schema-only form exists, `_SchemaOnlyTool(tool_name, schema)` (`omnigent/tools/manager.py:59-93`). It is useful when Coral builds per-step schemas dynamically.

**ToolManager registration and opt-ins (Extend).**

- The fixed registration order is at `manager.py:159-193`: skills, builtins, sub-agent tools, session tools, agent-management tools, OS tools, terminals, local tools, client tools, async-inbox tools, timers, task lifecycle, comments, policies, scheduled tasks, browser.
- Spawn opt-in: `if not (self._spec.tools.agents or self._spec.spawn): return` (`manager.py:485`). `sys_advise_models` is added only if `routing_available(get_caps())` (`manager.py:499-502`). `sys_session_create` is added only for `spawn: true` (`manager.py:508-509`).
- The parser reads top-level `spawn`, `timers` and `tool_groups` (`omnigent/spec/parser.py:307-317`). `params` is passed through as a raw dict (`parser.py:290`) into `AgentSpec.params` (`omnigent/spec/types.py:1614`), which is documented as "readable by skills and tools".
- `ToolGroupsConfig` (`types.py:878-899`) controls opt-outs only (browser, scheduled_tasks, comments, policies, agent_discovery). Every group defaults to on.
- Collision handling: the timer registration raises on a name collision (`manager.py:291-296`). Most other groups overwrite silently (`self._tools[name] = …`).

**Runner routing (Extend).**

- `should_dispatch_locally(name)` means `name in _ALL_LOCAL_TOOLS` (`omnigent/runner/tool_dispatch.py:888-915, 950-958`). `_ADVISE_MODELS_TOOLS` is a member (397-399, 897).
- For harness-subprocess modes (claude-sdk, codex), an `action_required` tool call is dispatched by `dispatch_tool_locally` with `mcp_manager=ProxyMcpManager(...)` (`omnigent/runner/app.py:6774-6860`). `execute_tool` therefore sends **every** such call to the server first (`tool_dispatch.py:7045-7052`: "All MCP tool calls are routed through the AP server's /mcp endpoint").
- The server then forwards non-intercepted calls back to the runner's `/v1/sessions/{id}/mcp/execute` (`omnigent/runner/mcp_routes.py:116-140`). There they run with `conversation_id=session_id` taken from the URL (`mcp_routes.py:321-349`).

**Native relay (Extend).**

- `_NATIVE_RELAY_BUILTIN_TOOLS` (`tool_dispatch.py:488-518`) filters the ToolManager schemas that the claude-native and codex-native `serve-mcp` relay advertises (`build_native_relay_tool_schemas`, `tool_dispatch.py:546-645`; filter at 609-615).
- The relay's executor is `ProxyMcpManager(...).call_tool(relay_spec, name, arguments)` (`app.py:5392-5400`). Native calls therefore also converge on server `/mcp`.
- Native PreToolUse hooks **skip** `mcp__omnigent__*` tools because they are relay-enforced (`omnigent/native/native_policy_hook.py:331-336`).

**Per-mode exposure (Reuse).**

| Mode | How Omnigent tools reach the model | Pre-approval | Evidence |
|---|---|---|---|
| claude-sdk | An in-process SDK MCP server named `omnigent`, with tools exposed as `mcp__omnigent__<name>` and a naming-bridge note added to the system prompt | Every Omnigent MCP tool is pre-approved in `auto` (the default) and `bypassPermissions` modes; other modes go through `can_use_tool` | `omnigent/inner/claude_sdk_executor.py:2929-2945, 1127-1165, 2963-2975`; default `auto` at `omnigent/inner/claude_sdk_harness.py:135`. Base native tools are only `Skill`, `ToolSearch` and an optional `AskUserQuestion` (`claude_sdk_executor.py:2570-2585`), so MCP tools may be **deferred behind ToolSearch** |
| codex (headless) | `dynamicTools` on `thread/start`, with `approvalPolicy: "never"` | n/a (never prompts) | `omnigent/inner/codex_executor.py:3826-3847`; `experimentalApi` at 3289 |
| claude-native | The `serve-mcp` relay | `--allowedTools` only for `_ROUTED_SPAWN_ALLOWED_TOOLS` in auto-harness sessions | `omnigent/runner/native/orchestration.py:8807-8819, 8850-8871, 9819-9846` |
| codex-native | The same relay, through `[mcp_servers.omnigent]` in `config.toml` | Per-tool `approval_mode = "approve"` for `_FRAMEWORK_APPROVED_TOOLS = ("sys_session_rename",)`, plus the routed-spawn set | `omnigent/harnesses/codex_native/app_server.py:306, 318-337, 360-379` |

**Server endpoint, policy and intercept (Extend).**

- `POST /v1/sessions/{session_id}/mcp` requires `LEVEL_EDIT` (`routes_agent.py:436-485`). `tools/call` computes `actor = mcp_policy_actor(request, conv, user_id)` (`routes_agent.py:549-567`; `omnigent/server/mcp_identity.py:11-22`).
- `_handle_mcp_tools_call` (`orchestration.py:12789`):
  - parses `_omnigent_operation_id` (12847-12855);
  - loads the spec (12880-12890);
  - evaluates TOOL_CALL policy, with ASK through MRTR `requestState` (12892-13056);
  - **after policy**, intercepts `sys_advise_models` and `mcp__omnigent__sys_advise_models` (13058-13069), returning through `_mcp_tool_result` (`helpers.py:11614-11627`).
- Today's intercepted handler signature is `_handle_advise_models_mcp(rpc_id, conv, arguments, agent_store, *, session_id, runner_router)` (`helpers.py:11630-11638`). It receives **no** actor, request, operation id or provenance.
- The intercept returns before the TOOL_RESULT policy phase. Note there is no grant check either: a session whose spec never registered the tool can still call it by name.
- A second caller, `McpPolicyAdapter.call_tool` (`omnigent/server/mcp_policy_adapter.py:118`), passes `{service}__{name}` names, so a bare-name intercept will not collide with registry tools.

**Identity and provenance (Extend).**

- The runner's `server_client` carries `X-Omnigent-Runner-Tunnel-Token` when the runner was launched with a binding token (`omnigent/runner/_entry.py:1601-1617`). The CLI and host launchers set one (`omnigent/cli.py:4466`; `omnigent/host/connect.py:1041`).
- `token_bound_runner_id(token)` is a hash of the token (`identity.py:200-217`).
- Precedents for "prove the caller is the session's runner": `require_orchestration_source` (`omnigent/server/session_orchestration.py:80-109`) and `_require_cost_control_label_authority` (`helpers.py:11002-11042`). The latter skips the check on single-user servers because "loopback runners may register under stable ids unrelated to any token" (11017-11019).
- The binding token is stripped from child processes (`identity.py:88-99`). However, claude-native hook configs in the bridge dir hold a bearer (`native/orchestration.py:9290` builds `_runner_headers` and passes them as `ap_auth_headers` at 9832). See Risk R3.

**Framework instructions (Extend).** See §2.5.

**Timeouts.** Proxy call ≤ `MCP_PROXY_CALL_TIMEOUT_S` = 7260 s, forward ≤ 7230 s (`tool_dispatch.py:208, 228-229`). Engine tools must return in well under a second, apart from bounded evidence checks.

### 2.2 Verdicts

| Element | Verdict | Notes |
|---|---|---|
| `Tool` base class and OpenAI schema format | Reuse | Coral tool classes subclass `Tool`. Per-step variants are instances, not separate classes. |
| ToolManager registration | Extend | One hook, `_register_extension_tools()`, after `_register_scheduled_task_tools()` (`manager.py:192`). It raises on a collision, like the timers (`manager.py:291-296`). |
| Opt-in | New (no parser change) | `params.coral` in generated bundles (§2.3). The alternative, a typed AgentSpec field like `spawn`, needs `parser.py:307-363` and `types.py:1652-1655` and conflicts with the CLAUDE.md rule. |
| `_ALL_LOCAL_TOOLS` | Extend | Include the extension's static names (S8). |
| `_NATIVE_RELAY_BUILTIN_TOOLS` | Extend | Include the extension's relay names (S9). |
| Native pre-approval | Extend | S11 at both sites. |
| Server intercept | Modify | Replace the hard-coded `if namespaced_name in (...)` with a registry (S10), and move `sys_advise_models` onto it. |
| Provenance check | New | T-S41 |
| Spec-declared MCP server for engine tools | Rejected | Pooled connections and no session metadata (deep dive §8.6 item 6). The registry route takes a client-supplied `X-Omnigent-Session-Id` (`omnigent/server/routes/mcp_gateway.py:19-27`) and needs `app.state.mcp_registry`. |

### 2.3 Seam designs

#### T-S42: extension tool provider (one declaration drives S7, S8, S9, S11 and S12)

The new module is `omnigent/tools/extensions.py` (upstream candidate):

```python
@dataclass(frozen=True)
class ExtensionToolSet:
    """Tools a framework extension adds to one agent spec."""
    tools: tuple[Tool, ...]                      # schema-only Tool instances (S7)
    server_dispatched: frozenset[str]            # bare names intercepted on the server (S8, S10)
    native_relay: frozenset[str]                 # names the native relay advertises (S9)
    native_preapproved: frozenset[str]           # bare names pre-approved in claude-native/codex-native (S11)
    framework_instructions: tuple[str, ...] = () # appended after author text (S12)

ToolProvider = Callable[[AgentSpec], ExtensionToolSet | None]

def register_tool_provider(provider: ToolProvider) -> None: ...
def extension_tool_sets(spec: AgentSpec) -> list[ExtensionToolSet]: ...
def static_server_dispatched_names() -> frozenset[str]: ...  # spec-less check used by should_dispatch_locally
```

**Loading.** Providers come from an entry-point group (`omnigent.tool_providers`), loaded once per process. This matters because ToolManager is constructed in **both** the server and the runner (`app.py:5917-5922`; `tool_dispatch.py:609-615`). Coral declares `coral.omni.tool_schemas:provider` in `pyproject.toml`, next to S29. The fallback, if entry points are disliked, is a module-level import list.

**Call sites** (each is a 1-5 line change):

1. `manager.py:192`: `self._register_extension_tools()`. Register `ext.tools`, and raise `ValueError` on a name collision.
2. `tool_dispatch.py:950-958`: `return tool_name in _ALL_LOCAL_TOOLS or tool_name in static_server_dispatched_names()`.
3. `tool_dispatch.py:609-615`: the relay filter becomes `_NATIVE_RELAY_BUILTIN_TOOLS | ext.native_relay`.
4. `native/orchestration.py:9819-9846`: `allowed_tools = (*routed_spawn_tools, *(f"mcp__omnigent__{n}" for n in ext.native_preapproved))`.
5. `app_server.py:327-337`: `framework_approved_tools(*, routed_spawns, extra: tuple[str, ...] = ())`. **UNVERIFIED:** whether the spec is in scope at the two callers (`app_server.py:1013, 2682`). It may need threading from the launch config.
6. `omnigent/runtime/prompt.py:62-87`: `instructions.extend(t for ext in extension_tool_sets(spec) for t in ext.framework_instructions)`.
7. Native launch channels (S12, §2.5).

**Coral's provider** (`coral/omni/tool_schemas.py`):

- It reads `spec.params.get("coral")` and returns `None` when that is absent or malformed. Example:

  ```yaml
  params:
    coral:
      role: step            # step | orchestrator | verifier
      tools: [submit_handoff, message_agent]
      handoff:              # derived checked parts, frozen per workflow version × step
        label_enum: [approved, changes_requested]
        items: false
  ```
- It builds per-step `submit_handoff` schema instances (label enum, items), the role's tool list and the role's framework instruction.
- It never reads run state, because it runs in the runner as well.

**Wire names.** Use the prefix `coral_` (`coral_submit_handoff` and so on):

- It avoids collisions with local, client and UC tools, which register into the same dict (`manager.py:704-889`).
- It keeps the native approval contract greppable.
- It keeps the `sys_` namespace Omnigent-owned.
- The design-doc names map 1:1.
- claude-sdk and claude-native show `mcp__omnigent__coral_submit_handoff`. The claude-sdk naming bridge already explains this (`claude_sdk_executor.py:1155-1165`).

#### S10, concrete: server tool handler registry

The new module is `omnigent/server/server_tools.py` (upstream candidate):

```python
@dataclass(frozen=True)
class ServerToolCall:
    session_id: str
    conversation: Conversation            # row already loaded in _handle_mcp_tools_call
    tool_name: str                        # bare name ("mcp__omnigent__" stripped)
    arguments: dict[str, object]          # post-TOOL_CALL-policy (possibly transformed) arguments
    actor: dict[str, str] | None          # mcp_policy_actor(...)
    credential_user: str | None
    operation_id: str | None              # params["_omnigent_operation_id"], stable across server reattach
    runner_proven: bool                   # T-S41
    approved_after_ask: bool              # True when reached through the MRTR retry path
    rpc_id: int | str | None

@dataclass(frozen=True)
class ServerToolResult:
    payload: dict[str, object]            # JSON-serialised into one MCP text block

ServerToolHandler = Callable[[ServerToolCall], Awaitable[ServerToolResult]]

def register_server_tool(name: str, handler: ServerToolHandler, *,
                         require_runner_proof: bool = False) -> Callable[[], None]: ...
def lookup_server_tool(name: str) -> ServerToolRegistration | None:  # normalizes the mcp__omnigent__ prefix
    ...
```

The invocation replaces `orchestration.py:13058-13069`:

```python
registration = lookup_server_tool(namespaced_name)
if registration is not None:
    proven = runner_proof(request, conv)            # T-S41
    if registration.require_runner_proof and not proven and multi_user:
        return _mcp_error_response(rpc_id, -32000, "This tool must be called by the session's agent")
    result = await registration.handler(ServerToolCall(...))
    return _mcp_tool_result(rpc_id, json.dumps(result.payload))
```

- `sys_advise_models` becomes the first registration, with `require_runner_proof=False` so behaviour is unchanged.
- Coral registers its five handlers from its startup hook (S32) in the server process only.
- The handler builds a reducer **command**, commits it in a short transaction (`run_write_transaction`, deep dive §6.5) and returns.
- It must not hold a DB transaction across an agent or host call.

#### T-S41: runner provenance for server-dispatched tools

- Lift the core of `_require_cost_control_label_authority` (`helpers.py:11034-11045`) into a predicate:

  ```python
  def runner_proof(token: str | None, bound_runner_id: str | None,
                   allowed_tokens: frozenset[str] | None) -> bool: ...
  ```
- Feed it from `request.headers.get(RUNNER_TUNNEL_TOKEN_HEADER)`, `conv.runner_id` and `request.app.state.runner_tunnel_tokens` (`omnigent/server/app.py:2297`).
- Multi-user servers: Coral handlers require the proof. Single-user servers: Coral accepts the call and records `provenance="user"` in the run log.
- **UNVERIFIED:** the app-state attribute that tells multi-user from single-user inside `_handle_mcp_tools_call` (`permission_store` is a route-factory argument, not obviously on `app.state`).
- The handler must also map `session_id` to an **open slot** of an **active** activation in Coral's store, and reject everything else. The spec opt-in only advertises the tools. It does not authorize them.

### 2.4 Draft contracts for the engine tools

**Common rules for all contracts.**

- The schema format is Omnigent's: the `parameters` block of `{"type": "function", "function": {...}}`.
- Every tool is a schema-only `Tool` subclass whose `invoke` raises, as in `advise_models.py:137-155`.
- Results are a single JSON text block through `_mcp_tool_result`:
  - success: `{"ok": true, ...}`;
  - rejection: `{"ok": false, "error": {"code", "message", "field"?, "allowed"?}}`.
- Transport failures stay JSON-RPC errors.
- Schemas stay flat. There is no `if`/`then`, because MCP-served schemas are not decoded under strict grammar constraints (deep dive §5.4). Conditional requirements are checked on the server.
- **Rejection codes** (deep dive §6.7): `handoff.invalid`, `tool.illegal`, `evidence.missing`, `run.paused`, `run.taken_over`. Every rejection is written to the run log. The "rejected calls in a row" counter (Draft 4 §7.3, default 3) is **per slot** and resets on an accepted call.
- **Deduplication:**
  - (a) transport: `(run_id, operation_id)` unique, returning the stored result;
  - (b) semantic: a closed slot or a decided decision returns the original result when the content is identical, and `tool.illegal` (`slot_closed` or `decision_closed`) when it differs.

**Static versus per-step schemas.** Step tools are frozen per step bundle, so enums are allowed. Orchestrator tools are generic (D5).

#### Contract 1: `coral_submit_handoff` (step agent)

```json
{
  "type": "object",
  "additionalProperties": false,
  "required": ["activation_id", "status", "report"],
  "properties": {
    "activation_id": {"type": "string", "description": "Activation id from your brief, e.g. \"act_7f3a\"."},
    "status": {"type": "string", "enum": ["done", "blocked"]},
    "report": {"type": "string", "minLength": 1, "maxLength": 60000},
    "blocked_reason": {"type": "string", "maxLength": 4000},
    "kind": {"type": "string", "enum": ["handoff", "refresh_note"], "default": "handoff"},
    "artifacts": {"type": "array", "maxItems": 200, "items": {
      "type": "object", "additionalProperties": false, "required": ["kind"],
      "properties": {
        "kind": {"type": "string", "enum": ["file", "commit", "diff", "url", "note"]},
        "path": {"type": "string"}, "ref": {"type": "string"},
        "description": {"type": "string", "maxLength": 2000}}}},
    "label": {"type": "string", "enum": ["<derived labels for this step only>"]},
    "items": {"type": "array", "maxItems": 500, "items": {
      "type": "object", "required": ["id", "title"],
      "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "data": {"type": "object"}}}}
  }
}
```

- `label` and `items` appear only when the step's derived checked part requires them (Draft 4 §5.3).
- **Engine checks:**
  1. The caller session maps to an open slot of `activation_id`, and that activation is `running`.
  2. The run is not paused or cancelled, and the activation is not `taken_over`.
  3. `report` is present. When `status = "blocked"`, `blocked_reason` is present.
  4. When `status = "done"` and the part is derived, `label` is in the enum, or `items` is present and each item is valid.
  5. "Done when" evidence passes (§9 of the deep dive). The synchronous part, the session-record scan, must be bounded at ≤ 30 s. Coral-run checks (Draft 4 §6.2) run **after** acceptance, asynchronously, and their failure comes back as a new `[Coral]` message within the attempt budget.
- **Success:**

  ```json
  {"ok": true, "result": "accepted", "activation_id": "...", "member": "review/claude#1",
   "instruction": "Handoff accepted. Stop working and end your turn."}
  ```

  A multi-agent step closes when every slot has submitted (Draft 4 §7.2).
- **Rejections:**
  - `evidence.missing` carries `missing[]`, `attempt` and `attempts_allowed`, and consumes an attempt;
  - `handoff.invalid` carries `field` and `allowed`;
  - `tool.illegal` carries a `reason` from `{not_run_member, stale_activation, slot_closed, wrong_role}`.
- **Refresh note (Draft 4 §7.5).** `kind = "refresh_note"` is accepted only while the engine has requested a refresh. It never closes the slot.
- **Elephant-Goldfish.** A persistent member submits once per loop pass, each time with that pass's `activation_id`. Typed resolutions (propose fix, contest, escalate) belong in a step-specific `items[].data` schema. ESCALATE maps to `status = "blocked"`, which routes to a gate.

#### Contract 2: `coral_choose_arrow` (orchestrator)

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["decision_id", "label", "reason"],
  "properties": {
    "decision_id": {"type": "string"},
    "label": {"type": "string", "minLength": 1, "maxLength": 200},
    "reason": {"type": "string", "minLength": 1, "maxLength": 4000},
    "items": {"type": "array", "maxItems": 500, "items": {"type": "object", "required": ["id", "title"],
      "properties": {"id": {"type": "string"}, "title": {"type": "string"}, "data": {"type": "object"}}}}
  }
}
```

- **Engine checks:**
  - the caller is the run's **current** orchestrator session (refresh rotates it);
  - the decision request is `requested` or `reminded`;
  - `label` is an outgoing arrow of *this* node;
  - loop limits still apply, so a choice at the limit is redirected to the at-limit destination and the result says so;
  - `items` is required when the target repeats for each item and the inputs came from a multi-agent collection (Draft 4 §5.3).
- **Success:**

  ```json
  {"ok": true, "decision_id": "...", "label": "...", "next": "Fix", "loop": {"used": 2, "limit": 3}, "redirected": false}
  ```
- **Rejection:** `tool.illegal` with `allowed: [labels]`, so the model does not need an enum.

#### Contract 3: `coral_assign_agents` (orchestrator; "up to" rosters only)

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["activation_id", "assignments"],
  "properties": {
    "activation_id": {"type": "string"},
    "assignments": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": false,
      "required": ["profile", "count"],
      "properties": {"profile": {"type": "string"}, "count": {"type": "integer", "minimum": 1, "maximum": 20}}}},
    "reason": {"type": "string", "maxLength": 4000}
  }
}
```

- **Checks:** the roster is "up to"; every profile is in the roster; per-profile and total counts are within bounds; the activation is `waiting_assignment`.
- The call is idempotent for identical input. A different input after assignment gets `tool.illegal`.
- **Success:** `{"ok": true, "members": [{"member": "review/claude#1", "profile": "..."}]}`.

#### Contract 4: `coral_message_agent` (any run agent)

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["to", "text"],
  "properties": {
    "to": {"type": "string", "description": "\"orchestrator\" or a member id from your brief, e.g. \"review/codex#1\""},
    "text": {"type": "string", "minLength": 1, "maxLength": 8000},
    "reply_to": {"type": "string"}
  }
}
```

- **Checks:**
  - the recipient is the orchestrator, a member of the same activation, or a member of an activation in the same parallel split (Draft 4 §7.2);
  - not self;
  - per-step isolation flags (the Elephant-Goldfish "no messages to the elephant");
  - a per-sender rate limit (e.g. 10 per minute), to stop ping-pong.
- **Delivery.** The engine delivers through the session facade (S4) with a `stable_id` (`omnigent/entities/conversation.py:904-910`, deep dive App. B) and a `[Coral message from <member> (<step>)]` header. It does **not** use `sys_session_message`, which is refused for edit-shared senders and adds its own prefix (`session_orchestration.py:61-69, 111-128`).
- **Effect on the receiver.** A message to an idle recipient starts an engine-originated turn, so a turn that ends without a handoff can be nudged. claude-sdk batches mid-turn messages into a follow-up turn (deep dive F33).
- **Success:** `{"ok": true, "message_id": "...", "delivery": "queued"}`.

#### Contract 5: `coral_ask_user` (orchestrator; non-blocking)

```json
{
  "type": "object", "additionalProperties": false,
  "required": ["question"],
  "properties": {
    "question": {"type": "string", "minLength": 1, "maxLength": 4000},
    "choices": {"type": "array", "minItems": 2, "maxItems": 10, "items": {"type": "string", "minLength": 1, "maxLength": 200}},
    "allow_free_text": {"type": "boolean", "default": true},
    "context": {"type": "string", "maxLength": 8000}
  }
}
```

- The engine writes a durable `coral_user_questions` row, then publishes a form elicitation on the orchestrator session (§4.3). Its `requestedSchema` is `{answer: enum|string, note: string}`, which `web/src/components/blocks/ElicitationSchemaForm.tsx:1-21` renders as a select or text field.
- It returns immediately:

  ```json
  {"ok": true, "question_id": "...", "status": "asked",
   "instruction": "The answer will arrive as a [Coral answer] message; end your turn if you cannot continue without it."}
  ```
- The answer is delivered as a message with a `stable_id`, and the decision watchdog is suspended while a question is open.
- Step agents do not get this tool. They use `submit_handoff(status = "blocked")`.
- Deny native `AskUserQuestion` (claude-sdk `claude_sdk_executor.py:2570-2585`; claude-native through PermissionRequest) and Codex `item/tool/requestUserInput` (`omnigent/harnesses/codex_native/forwarder.py:244`) in run sessions, so questions stay durable and recorded (§3.4 hygiene).

#### Contract 6 (Draft 4 delta, D9): `coral_assign_task` (orchestrator)

- Arguments: `{activation_id, member, task (≤ 8000), reason}`.
- It re-tasks an **existing** member, for example to resolve merge conflicts the engine reported, or for the Elephant-Goldfish elephant on a later pass. Allowed only when the engine has opened a `conflict` sub-state or the step permits re-tasking.
- An alternative is a `mode` field on `assign_agents`. A separate tool keeps each schema simple.

### 2.5 Framework instructions (S12, concrete)

- **The rule.** Author and per-request text come first; framework text is appended (`omnigent/runtime/prompt.py:90-110`). Canonical text and the gate live in the owning module, which here is Coral (CLAUDE.md).
- **Headless modes.** Both are covered by `_framework_instructions_for(spec)` (`prompt.py:62-87`):
  - claude-sdk, through the composed snapshot (`app.py:5779-5790`);
  - codex, through `developerInstructions` (`codex_executor.py:3836-3837`).

  T-S42 call site 6 adds Coral's text there.
- **Native modes.** These receive only `raw_author_instructions(spec)` (`prompt.py:213-225`):
  - claude-native: `--append-system-prompt` (`native/orchestration.py:9840-9844`);
  - codex-native: `developer_instructions` (`native/orchestration.py:5785-5799`).

  The per-turn `framework_instructions=` parameter has no callers (grep shows only docstrings).
- **Precedent.** OpenCode's AGENTS.md already composes spec-level framework text with `build_instructions_nullable(spec, None, [])` (`native/orchestration.py:7727-7746`), so spec-level framework text at launch is an accepted pattern.
- **Recommended change.** Add `_native_startup_extension_instructions(agent_spec) -> str | None`, returning only `ext.framework_instructions`, and join it into both native channels. Do not ship all of `_framework_instructions_for`: that would change upstream behaviour by adding the browser and wake notices.
- **Draft text** (keep it short; do not tell agents to keep working without stopping, per deep dive §8.3 item 5):
  - *Step:* "You are a Coral step agent: one member of a workflow step. Your first message is your brief: goal, inputs and activation id. When the goal is met, call `coral_submit_handoff` once with status `done` and a report. If you cannot proceed, call it with status `blocked` and a reason. Do not start other agents. Messages that begin with `[Coral` come from the workflow engine, not a person."
  - *Orchestrator:* "You conduct this Coral workflow run and do not do the work yourself. At a decision point the engine sends a `[Coral decision]` message that lists the allowed labels. Answer with `coral_choose_arrow` (decision id, label, reason). Use `coral_assign_agents` for "up to" rosters, `coral_message_agent` to talk to step agents, and `coral_ask_user` for questions outside human gates."

### 2.6 Risks for engine tools

| # | Risk | Mitigation |
|---|---|---|
| R1 | Any `LEVEL_EDIT` credential can forge `coral_*` calls by curling `/mcp` | T-S41 in multi-user mode; slot mapping; run-log provenance |
| R2 | claude-sdk defers MCP tools behind `ToolSearch` (`claude_sdk_executor.py:2570-2585`), so the model may not call `coral_submit_handoff` | Name the tool in the framework instruction and the brief; nudge after a turn ends without a handoff (deep dive §6.4); bench probe |
| R3 | Native bridge-dir credentials (§0 item 10) | Validator labelling; sandbox probe |
| R4 | Headless Codex dynamic tools are experimental, and fresh V2 sub-agents do not inherit them (deep dive §8.6) | Separate sessions only; pin the Codex version |
| R5 | A user TOOL_CALL policy DENYs or ASKs a `coral_*` tool. The engine never sees policy denials, so its rejected-call count misses them. | Optional `on_policy_denied` callback in the S10 registry; at minimum, alert on step stalls |
| R6 | Name collision with user tools | `coral_` prefix plus a collision raise (`manager.py:291-296` pattern) |
| R7 | The handler blocks while running evidence checks | Synchronous checks bounded at ≤ 30 s; Coral-run checks asynchronous |

### 2.7 Tests to extend

- **ToolManager registration.** Add next to `tests/tools/test_manager.py:572-605`, which holds the `sys_advise_models` gating tests: tools present only with `params.coral`, a collision raises, and the per-step label enum appears in the schema.
- **Routing and relay.**
  - `tests/runner/test_runner_dispatch.py` (`should_dispatch_locally` asserts near 3873-3879 and 6019-6024);
  - `tests/runner/test_tool_groups_surface.py`;
  - `tests/runner/test_native_tool_metadata.py` (relay surface).
- **Server intercept.** There is no server test of the `sys_advise_models` intercept today. Add `tests/server/routes/test_server_tool_registry.py` next to `tests/server/routes/test_sessions_mcp_proxy_policy_retry.py`. Cover:
  - a DENY policy blocks before the handler;
  - ASK then retry reaches the handler with transformed arguments;
  - runner proof is required in multi-user mode;
  - the `mcp__omnigent__` prefix is normalized;
  - `sys_advise_models` is unchanged.
- **Framework instructions.** `tests/runtime/test_prompt.py`. The native launch argv (claude-native `--append-system-prompt` and `--allowedTools`) goes in `tests/harnesses/claude_native/` and `tests/harnesses/codex_native/app_server/`.
- **Coral handlers.** Unit tests in `tests/coral/`, driven through the reducer, with no server.

---

## 3. Policies and rule enforcement

### 3.1 Current code

**Engine construction.** `build_policy_engine(*, spec, conversation_id, conversation_store, conversation=None, expected_agent_id=None, connection_override=None, default_policies=None, policy_store=None, server_llm=None, host_connection=None)` is at `builder.py:517-529`.

- **Order** (`builder.py:613-654`): session (CRUD), then agent spec guardrails, then admin (DB defaults plus config defaults), then `_REQUIRED_APPROVAL_SPECS`.
- **Required specs** (`builder.py:76-104`): `__ask_on_add_policy` and `__ask_on_scheduled_task_change`, injected into every engine. `any_policies_apply` forces evaluation for those tools (`builder.py:451-457`).
- **Inheritance:**
  - child spec guardrails are appended only for `sub_agent_name` children (`builder.py:728-751`);
  - root **session** policies are prepended for every child (`builder.py:755-772`);
  - root cost approvals are seeded into children (`builder.py:791-803`).
- **Caches:** 30 s TTL for session and default policy lists (`builder.py:120-146, 1715-1841`), with local invalidation on CRUD (`session_policies.py:218, 381, 417`). The cache is per replica.
- **Evaluation** (`engine.py:243-433`):
  - DENY short-circuits; ASK accumulates; ALLOW applies writes;
  - any policy exception becomes a fail-closed DENY (`engine.py:1111-1116`);
  - `data` transforms chain into later policies (`engine.py:396-401`).
- **Event shape for function policies** (`omnigent/policies/function.py:192-260`): `type` (`input | tool_call | tool_result | output | request`), `target`, `data`, and `context` with `{actor, usage, model, harness, labels, subtree_usage, conversation_id, ...}`, plus `session_state` and `llm_client`. There is **no agent or sub-agent identity** (S16). Async callables are supported (`function.py:178-190`).
- **`session_state`.** Keys starting with `_policy_` (and two `subagent_cost_*` keys) are reserved and need an approved ASK (`omnigent/policies/schema.py:119-133`; `engine.py:573-581, 1101-1110`). Exceptions are the three runtime counters hard-wired to `spawn_bounds`, `max_tool_calls_per_session` and `detect_loop` (`function.py:333-342`). Writes rewrite the whole dict (`engine.py:612-615`).
- **Labels.** Policy `set_labels` go through `apply_label_writes`, which validates only `LabelDef.values` and checks **no** reserved prefixes (`engine.py:521-547`).

**Registry.**

- `POLICY_REGISTRY` lists are loaded from `BUILTIN_POLICY_MODULES` plus the server config `policy_modules` (`omnigent/policies/registry.py:92-180`; `omnigent/server/app.py:1579, 2046`).
- `is_registered_handler` is the allowlist used for CRUD and bundle uploads (`registry.py:196-215`).
- `internal_only` only hides an entry from `GET /v1/policy-registry` (`omnigent/server/routes/policy_registry.py:55`). It does not prevent attaching it.

**Builtins worth reusing.**

| Builtin | Location | Notes |
|---|---|---|
| `cel_policy` | `omnigent/policies/builtins/cel.py:103` | |
| `blast_radius` | `omnigent/policies/builtins/orchestration.py:352` | |
| `spawn_bounds` | `orchestration.py:425-507` | Per-turn; `dispatch_tools` is configurable |
| `worktree_guard` | `orchestration.py:563` | |
| `read_only_os` | `orchestration.py:645` | |
| `cost_budget` | `cost.py:416-558` | |
| `subagent_cost_budget` | `cost.py:809` | |
| `ask_on_add_policy` | `omnigent/policies/builtins/safety.py:358` | |
| `NATIVE_WRITE_TOOLS` | `safety.py:43` | Constant |
| `SHELL_TOOLS` | `omnigent/policies/builtins/_shell.py:29-39` | Constant |
| Claude `AGENT_TOOL_NAMES` | `subagent_router.py:83-84` | Constant |
| Codex spawn suffix matcher | `omnigent/inner/hook_scripts/codex_router_hook.py:40, 86` | Constant |

**Session policy CRUD.** All routes require `LEVEL_EDIT`, check the registry allowlist for `python` handlers, and invalidate the cache:

- create: `session_policies.py:158-241`;
- update (`name`, `handler`, `enabled`): `session_policies.py:308-388`;
- delete: `session_policies.py:390-437`.

Nothing protects a policy by name or prefix.

**Native hooks.**

- `hook_payload_to_evaluation_request` builds `"context": {}` (`native_policy_hook.py:289-366`).
- On an unobtainable verdict, the hooks use **`fail_ask_hook_output`**:
  - `omnigent/harnesses/claude_native/hook.py:1238-1242`;
  - `omnigent/harnesses/codex_native/hook.py:149-153`;
  - the claude-native relay at `omnigent/harnesses/claude_native/bridge.py:8447`.
- Devin and Kimi use `fail_closed_hook_output` (`omnigent/harnesses/devin_native/hook.py:155-161`; `omnigent/harnesses/kimi_native/hook.py:156`).
- The claude-native PreToolUse hook is a curl to the relay with a Python fallback and **no `timeout` key** (`bridge.py:2690-2741`, compared with PermissionRequest's 86400 at 2687).
- An optional operator-enabled "no-policy ALLOW" cache can answer hooks locally for up to 300 s (`omnigent/native/policy_allow_cache.py:1-50`). It applies only when the server reports that no policies apply.

### 3.2 Verdicts

| Element | Verdict |
|---|---|
| PolicyEngine, builder, registry, CEL and orchestration builtins | Reuse |
| `coral.policies` module (POLICY_REGISTRY) | New, loaded through `policy_modules` config with no Omnigent patch. Adding it to `BUILTIN_POLICY_MODULES` would be an unnecessary patch. |
| Required-policy injection | Extend (T-S44) |
| Session policy CRUD | Modify (S26: reserved prefix) |
| `apply_label_writes` | Modify (T-S45) |
| Native fail mode | Modify (S14), with the three sites listed above |
| Policy event agent identity | Extend (S16) |
| `cost_budget` as a run budget | Replace by engine code; keep it as an optional per-session backstop with `max_cost_usd` only |

### 3.3 Where Coral policies should live (recommendation)

| Policy | Placement | Why |
|---|---|---|
| Translated Required rules (Draft 4 §9), fixed at version save | **Per-step bundle `guardrails.policies`** | Pinned per workflow version ("the stored translation is what runs"). The session-policy API cannot delete them, they skip the 30 s cache, and they are not inherited by siblings. Bundle uploads still enforce the handler allowlist (`omnigent/server/bundles.py`, `validate_agent_bundle`). |
| `orchestrator_guard` | Orchestrator bundle guardrails, **plus** a label condition inside the handler | It does not leak to engine-created children with their own `agent_id` (D8), and the label check makes it safe even if the topology changes |
| `step_roster` | Step bundle guardrails | Per step, pinned |
| `run_guard` (pause, cancel, budget) | **T-S44 required-policy provider**, keyed on the `coral.run_id` label | Applies to every run session, including refreshed and restarted ones, with no attach step and no cache lag. It cannot be removed through CRUD. `any_policies_apply` becomes true, so the native allow cache never opens for run sessions. |
| Amendment-time rule changes (Draft 4 §7.7) | Session policies under a reserved name prefix, protected by S26, attached before the next input | The only case that needs mutable attachment |

**T-S44: required-policy provider.** Generalize `_REQUIRED_APPROVAL_SPECS`:

```python
# omnigent/runtime/policies/builder.py
RequiredPolicyProvider = Callable[[Conversation | None], Sequence[PolicySpec]]
def register_required_policy_provider(provider: RequiredPolicyProvider) -> None: ...
```

- At `builder.py:654` and in the three rebuilds at 744-772, append `[*_REQUIRED_APPROVAL_SPECS, *provider_specs(conv)]`.
- In `any_policies_apply` (`builder.py:415-480`), return True when any provider yields specs for the conversation. The fast path takes `conversation` (`builder.py:422`).
- Coral's provider returns `[FunctionPolicySpec(name="__coral_run_guard", function=FunctionRef(path="coral.policies.run_guard.run_guard", arguments={}))]` when `conv.labels` has `coral.run_id`.
- The labels themselves must be protected (S26 and T-S45).

### 3.4 Coral policy module sketches

**Common conventions.**

- Policies use the V0 decision dicts already used by builtins (`orchestration.py:30-61`): `{"result": "ALLOW" | "ASK" | "DENY", "reason": "...", "state_updates": [...]}`.
- Every Coral policy first checks `event["context"]["labels"].get("coral.run_id")` and ALLOWs otherwise. Labels are those of the evaluated conversation (`engine.py:873-888`).
- Tool names are normalized with `name.removeprefix("mcp__omnigent__")`. The `/mcp` path may see either form; compare the two names checked at `orchestration.py:13061`.

```python
# coral/policies/roster.py
from omnigent.inner.hook_scripts.subagent_router import AGENT_TOOL_NAMES       # ("Agent", "Task")
from omnigent.inner.hook_scripts.codex_router_hook import SPAWN_AGENT_TOOL_SUFFIX

OMNIGENT_SPAWN_TOOLS = frozenset({"sys_session_create", "sys_session_send", "sys_session_message"})
CLAUDE_TEAM_TOOLS = frozenset({"SendMessage", "ListAgents", "Workflow"})  # names per deep dive [W-8]; UNVERIFIED here

def step_roster(*, allowed_subagent_types: list[str] | None = None, max_spawns: int = 0):
    """DENY any way for a run-owned step session to widen its roster."""
    allowed = frozenset(allowed_subagent_types or ())
    def evaluate(event: dict) -> dict:
        if event.get("type") != "tool_call" or not _run_owned(event):
            return {"result": "ALLOW"}
        name = _bare(event)
        if name in OMNIGENT_SPAWN_TOOLS or name in CLAUDE_TEAM_TOOLS \
                or name.lower().endswith(SPAWN_AGENT_TOOL_SUFFIX):
            return {"result": "DENY", "reason": "This step's roster is fixed; do not start other agents."}
        if name in AGENT_TOOL_NAMES:
            if max_spawns == 0 or _arguments(event).get("subagent_type") not in allowed:
                return {"result": "DENY", "reason": "Sub-agent not in this step's roster."}
            return {"result": "ALLOW", "state_updates": [
                {"key": "coral_roster_spawns", "action": "increment", "value": 1}]}  # sub-agent mode only; racy (D13)
        return {"result": "ALLOW"}
    return evaluate
```

- **Separate-session steps** (the default): `max_spawns = 0`, so the policy is a stateless deny list with no race.
- **Sub-agent mode:** this becomes Enforced only after:
  - S16, which adds `agent_id` to the policy context so the count is attributable;
  - S14 and S15 (fail-closed hooks);
  - the attribution bench probe (Draft 4 §7.4).

  Prefer counting in Coral's tables. The async policy reads the slot count from the store.
- Also set the spec grants: no `tools.agents` and no `spawn` in step bundles (`manager.py:485`). Set Codex `agents.enabled = false` (deep dive §10.4).

```python
# coral/policies/orchestrator.py
from omnigent.policies.builtins.safety import NATIVE_WRITE_TOOLS
from omnigent.policies.builtins._shell import SHELL_TOOLS

_ORCH_ALLOWED = frozenset({
    "coral_choose_arrow", "coral_assign_agents", "coral_assign_task", "coral_message_agent", "coral_ask_user",
    "sys_os_read", "Read", "Glob", "Grep", "LS",              # light inspection of handoff artifacts
    "sys_session_get_history", "sys_session_get_info", "sys_session_list",
    "load_skill", "read_skill_file", "Skill", "ToolSearch", "TodoWrite"})

def orchestrator_guard(*, extra_allowed: list[str] | None = None):
    """Allowlist: the orchestrator conducts and does not do heavy work (deep dive §9.3 item 6)."""
    allowed = _ORCH_ALLOWED | frozenset(extra_allowed or ())
    def evaluate(event: dict) -> dict:
        if event.get("type") != "tool_call" or _labels(event).get("coral.role") != "orchestrator":
            return {"result": "ALLOW"}
        if _bare(event) in allowed:
            return {"result": "ALLOW"}
        return {"result": "DENY", "reason": "The orchestrator conducts the run; delegate work to a step."}
    return evaluate
```

- An allowlist is stronger than a denylist: new vendor tools are denied by default.
- `NATIVE_WRITE_TOOLS` and `SHELL_TOOLS` give the error messages their specificity.
- Under claude-sdk the orchestrator has only `sys_os_*` (`omnigent/tools/builtins/os_env.py:383`), so denying `sys_os_shell`, `sys_os_write` and `sys_os_edit` is sufficient.

```python
# coral/policies/run_guard.py
async def run_guard():
    """Injected through T-S44 for every session labelled coral.run_id."""
    async def evaluate(event: dict) -> dict:
        run_id = _labels(event).get("coral.run_id")
        if not run_id or event.get("type") not in {"tool_call", "request"}:
            return {"result": "ALLOW"}
        state = await coral_run_state_cache.get(run_id)  # 1-2 s TTL, invalidated on transition
        if state.cancelled:
            return {"result": "DENY", "reason": "This workflow run was cancelled."}
        if event["type"] == "tool_call" and state.paused_reason in {"budget", "user", "rejected_calls"} \
                and not _bare(event).startswith("coral_"):
            return {"result": "DENY", "reason": f"Run paused ({state.paused_reason}). Waiting for the user."}
        return {"result": "ALLOW"}
    return evaluate
```

- It runs in the server process for both `/mcp` and `/policies/evaluate`, so it can read Coral's store.
- The engine is rebuilt for every evaluation (`_evaluate_policy_with_fresh_engine`, `orchestration.py:10425-10437`, called at 12915 and 12991), so the factory must be cheap.
- It never DENYs `coral_*` tools, so an agent can still hand off while the run is paused.
- **Hygiene for run bundles** (configuration, not policy):
  - `tool_groups: {policies: false, scheduled_tasks: false, browser: false}` (`types.py:878-899`), so agents cannot attach policies or create unattended work;
  - `agent_session_sharing: none`.

  The vendor-tool parts go in `step_roster`: native `AskUserQuestion` and Codex `requestUserInput` for steps, and claude-native `/clear` through the UserPromptSubmit gate (deep dive §8.8).

**POLICY_REGISTRY entries** follow the shape at `orchestration.py:690-757`: handler, `"kind": "factory"`, name, description and `params_schema`. Mark them `internal_only: True` so they are hidden from the picker. Note that this hides them; it does not protect them.

### 3.5 Protection of Enforced rules (S26, concrete, plus T-S45 and T-S46)

**S26.** A reserved session-policy name prefix `coral.`:

- In `create_policy`, `update_policy` and `delete_policy` (`session_policies.py:158, 308, 390`), refuse when `body.name` or the existing policy's name starts with `coral.`, unless the call comes from the engine. The engine writes through `PolicyStore` directly, not through HTTP.
- Also reserve the `coral.` label prefix in `_reject_server_reserved_label_seed` (`helpers.py:10884-10936`). It already covers `PROFILE_LABEL_PREFIX`, `MCP_SELECTION_PREFIX`, `FAMILY_PIN_LABEL_PREFIX` and others, and it runs on session PATCH (`routes_core.py:3166-3167`) and on create.

**T-S45.** `PolicyEngine.apply_label_writes` (`engine.py:521-547`) must drop or refuse `coral.*` keys. Otherwise a user CEL policy, or an agent's `sys_add_policy` that the user approved (`builder.py:76-86`), can rewrite `coral.run_id` or `coral.role` and slip out of label-keyed guards.

**T-S46: run-owned session mutation guard.** Refuse, or route through an amendment, when `coral.run_id` is present:

- `PUT /v1/sessions/{id}/agent` (`routes_agent.py:289`, owner-only at 343-347). It would replace the step bundle and its guardrails. **UNVERIFIED** whether Coral's bundles become session-scoped agents (PUT allowed) or reusable rows (PUT refused at 337-341).
- Session MCP server edits (`session_mcp_servers.py:169-222`). These would widen the tool surface.
- Archiving or closing a run session outside the engine. Recommendation: allow it, but emit an engine signal.

A small hook in each route is enough: `register_session_mutation_guard(fn(conv, action) -> str | None)`.

### 3.6 Failing closed (S14, S15 and S16, concrete)

- **S14.**
  - Write `policy_failure_mode: "deny"` into the bridge-dir hook config at launch when the spec has `params.coral`. The config is written through `write_hook_config` and `build_hook_settings`, and the launch paths are known (`native/orchestration.py:9828-9846` for Claude; the codex-native equivalent is around `app_server.py:3283`, UNVERIFIED).
  - The three `_fail_closed` sites choose `fail_closed_hook_output` when the mode is "deny". For run-owned sessions, the early "no opinion" returns also deny (`claude_native/hook.py:1221-1222, 1257-1258`).
  - Add an explicit PreToolUse `timeout` (`bridge.py:2723-2728`) and `"onFailure": "block"`, gated on the CLI version (deep dive §10.5; version facts UNVERIFIED here).
- **S15.** Refuse to start a run-owned codex-native session when `policy_hook_disabled_reason` is set (`app_server.py:2441-2448, 2850-2854`, per deep dive). Surface the refusal as an `infra` pause, not as a silent unenforced run.
- **S16.** Extend `hook_payload_to_evaluation_request` (`native_policy_hook.py:338-349`) to copy the Claude `agent_id`/`agent_type` and the Codex thread id into `event.context`. Thread it through `EvaluationContext` and `function._build_event` (`function.py:221-257`).

### 3.7 Risks

| # | Risk | Mitigation |
|---|---|---|
| P1 | An ASK on an unattended step parks for up to a day, then DENYs (D11) | The S5 observer raises an alert; Coral policies set explicit `ask_timeout`; never auto-approve |
| P2 | `session_state` counter race on native hooks and across replicas (D13; `/mcp` is serialized in-replica at `orchestration.py:10416-10437`) | Stateless or store-backed counters |
| P3 | The 30 s cross-replica cache for session-attached policies | Bundle and T-S44 placement; attach amendments before the next input |
| P4 | A user policy transforms `data` ahead of Coral's policy and so rewrites arguments | Coral policies sit in agent (bundle) and required positions. A session policy earlier in the chain can still transform. Accept this, and document that session policies on run sessions are reserved. |
| P5 | Docs and code disagree on `cost_budget` | Translate from code (deep dive R4) |
| P6 | Native mode without a server URL (`bridge.py:2651`) installs no policy hooks | Validator: refuse run-owned claude-native without `ap_server_url` |

### 3.8 Tests to extend

- **Policy factories:** `tests/policies/builtins/` (pattern: `test_safety.py`, `test_cost.py`); new `tests/coral/policies/test_roster.py`, `test_orchestrator_guard.py` and `test_run_guard.py`.
- **Required provider:** `tests/runtime/policies/test_builder.py`, `test_builder_session_policies.py` (inheritance), `test_subagent_guardrails.py` (the D8 refinement) and `test_scheduled_task_approval_gate.py` (the existing required-spec precedent).
- **Label write path:** `tests/runtime/policies/test_label_validation.py`, `test_engine_session_state.py`.
- **CRUD protection:** `tests/server/routes/test_session_policies_crud.py`, `tests/server/integration/test_session_policy_routes.py`.
- **Native fail mode:**
  - `tests/test_native_policy_hook.py`;
  - `tests/harnesses/claude_native/test_claude_native_hook.py`;
  - `tests/harnesses/codex_native/test_codex_native_hook.py`;
  - `tests/harnesses/codex_native/app_server/test_policy_hooks.py`.
- **Registry:** `tests/policies/test_registry.py`, `tests/server/routes/test_policy_registry.py`.

---

## 4. Elicitations and human gates

### 4.1 Current code

**Pending index.**

- `pending_elicitations.record_publish` runs on every `session_stream.publish` (`omnigent/runtime/session_stream.py:354-398`). It is in-memory and per process (`pending_elicitations.py:1-59`).
- It has **one** observer slot (`pending_elicitations.py:68-87`), occupied by `SubagentBlockNotifier`. The notifier is installed at `orchestration.py:10800-10861` and wired from `app.py:1992-1995`.
- `_notify_observer` calls the observer with no try/except (`pending_elicitations.py:183-198`).
- Counts are persisted for other replicas through `set_count_persist_hook` (`app.py:2618`; `omnigent/server/session_live_state.py:312-338`).

**Parked harness elicitations.**

- `_publish_and_wait_for_harness_elicitation(request, *, session_id, params, timeout_s, ...)` (`orchestration.py:470-640`) needs a FastAPI `Request` for disconnect polling, parks an in-process Future, and returns `None` on timeout.
- The futures live in `omnigent/server/_elicitation_registry.py:21-28`.
- The native ASK gate uses it and fails closed (`orchestration.py:2654-2690`).

**Publish-without-park.** The `mcp_elicitation` event branch (`routes_events.py:2222-2257`):

1. creates `elicit_<hex>`;
2. builds `ElicitationRequestParams(mode="form", message, requestedSchema)`;
3. publishes on the session stream;
4. mirrors to ancestors;
5. returns the id.

The verdict arrives later through the `approval` event.

**Resolution.**

- `_resolve_elicitation(session_id, data, runner_router, conversation_store)` (`orchestration.py:2400-2559`):
  - sets a matching harness Future after an owner check;
  - otherwise tombstones the verdict;
  - publishes `response.elicitation_resolved`, which also drains the index;
  - forwards to the runner.
- It has two callers:
  - `POST /events` `approval` (`routes_events.py:2208-2221`, at the events route's edit bar);
  - `POST /sessions/{id}/elicitations/{eid}/resolve` (`routes_elicitations.py:75-131`, `ELICITATION_RESOLVE_LEVEL = LEVEL_EDIT` at 61).
- Neither passes the resolving user into `_resolve_elicitation`.

**Schemas.**

- `ElicitationRequestParams` (`omnigent/server/schemas.py:4585-4643`): `mode`, `message`, `requestedSchema`, `url`, `phase`, `policy_name`, `content_preview`, `target_session_id`, and **`extra="allow"`** (4636-4643).
- `ElicitationResult`: `action` (`accept | decline | cancel`) plus `content`, a flat map of scalars and string lists (`schemas.py:1332-1376`).

**UI.**

- Form rendering: enum → select, boolean → checkbox, number → number field, otherwise text (`ElicitationSchemaForm.tsx:1-21`).
- `/approve/:sessionId/:elicitationId` route (`web/src/App.tsx:180`) reads `GET /elicitations/{eid}` from the in-memory index (`routes_elicitations.py:133-207`).

**ASK timeout semantics.**

- `_await_elicitation` maps a timeout to `False`, which means DENY (`approval.py:142-146`).
- `resolve_ask_timeout` picks the per-policy value or the spec default (`approval.py:274-297`). The default is 86400 (`types.py:40`).

### 4.2 Verdicts

| Element | Verdict |
|---|---|
| Elicitation event shape, Inbox, ApprovalCard, `/approve` page, Slack cards | Reuse as the gate **surface** |
| Policy-ASK path for gates | Do **not** use it (a timeout becomes DENY) |
| Parked-Future primitive for gates | Do **not** use it (in-memory and request-bound) |
| `mcp_elicitation` branch | Extend: lift it into a helper (S6a) |
| `_resolve_elicitation` | Modify: verdict hook plus resolver identity (S6b, T-S47) |
| Observer slot | Modify: list plus isolation (S5); notifier exemption (T-S43) |

### 4.3 Seam designs

**S5, concrete** (`pending_elicitations.py`):

```python
_observers: list[Callable[[str, dict[str, Any]], None]] = []
def add_elicitation_observer(observer) -> Callable[[], None]: ...   # returns an uninstaller
def set_elicitation_observer(observer) -> None: ...                 # kept: replaces the "primary" entry for compatibility
def _notify_observer(conversation_id, event) -> None:
    for observer in tuple(_observers):
        try:
            observer(conversation_id, event)
        except Exception:
            _logger.exception("elicitation observer failed")         # never break session_stream.publish
```

Coral's observer is cheap and non-blocking. It writes a `coral_signals` hint for (session, request or resolved) when the session maps to a slot. That drives the "step waiting on approval" alert and pauses watchdogs.

**T-S43: SubagentBlockNotifier exemption.**

- At `subagent_block_notifier.py:297-300`, return early when `child.labels` marks the session as engine-managed.
- The upstream-friendly form is a generic label such as `omnigent.parent_wake: off`, set by Coral on run children. The alternative is to check `coral.run_id`.
- Without this, the orchestrator agent receives "[System: sub-agent … blocked]" turns.
- Also check the runner-side completion wake. It is keyed on `register_subagent_work` entries (`omnigent/runner/subagent_work.py:266-305`), which come from `sys_session_send` dispatch and recovery (`omnigent/runner/subagent_recovery.py:96`). Engine-created children should never get one (UNVERIFIED; check in phase 2).

**S6a: request-free publish helper** (extracted from `routes_events.py:2222-2257`):

```python
async def publish_form_elicitation(
    session_id: str,
    params: ElicitationRequestParams,
    *,
    elicitation_id: str | None = None,          # Coral passes a STABLE id: f"coral_gate_{visit_id}"
    conversation_store: ConversationStore | None = None,
) -> str: ...
```

- The `mcp_elicitation` branch then calls this helper, so its behaviour is unchanged.
- Coral sets `params.policy_name = "coral.gate"` and `params.phase = "workflow_gate"`, plus an extra field `coral = {"run_id", "gate_visit_id", "node_id", "kind": "gate" | "question" | "budget"}`. `extra="allow"` permits it, and the web can render a "Workflow gate" badge.

**S6b and T-S47: verdict hook with resolver identity.**

```python
ElicitationVerdictHandler = Callable[[str, str, ElicitationResult, str | None], Awaitable[bool]]
#                                    session_id, elicitation_id, verdict, resolved_by
def register_elicitation_verdict_handler(id_prefix: str, handler: ElicitationVerdictHandler) -> Callable[[], None]: ...
async def _resolve_elicitation(session_id, data, runner_router, conversation_store=None, *, resolved_by: str | None = None): ...
```

- Both callers pass `user_id`:
  - `routes_events.py:2214`, where the events route already resolved the user;
  - `routes_elicitations.py:127-131`.
- When the id matches a registered prefix, `_resolve_elicitation` calls the handler **first**. If the handler returns `False` (rejected: a stale visit, or an answer the gate does not allow), it skips the resolved fan-out, so the card stays.
- Coral's handler does a compare-and-set on `coral_gate_visits` (`open → resolved(label, by, note)`) and appends to the run log.
- Approver authority is `LEVEL_EDIT` on the orchestrator session. The entry routes already enforce it; the handler records `resolved_by`. Deep dive §20.1 Q4 recommends manage level for amendments only.

**Gate lifecycle.**

1. The transition transaction inserts a `coral_gate_visits` row before any notification (deep dive §11).
2. An outbox effect calls `publish_form_elicitation` on the **current** orchestrator session, with `requestedSchema`:

   ```json
   {"type": "object", "required": ["decision"],
    "properties": {"decision": {"type": "string", "enum": ["<labels>"], "title": "Decision"},
                   "note": {"type": "string", "title": "Note"}}}
   ```

   For a plain approve/reject gate, `accept` means approve, and `decline` maps to the "rejected" label only when that arrow exists. `cancel` leaves the gate open.
3. **At startup** (S32 lifespan), re-publish every open gate and question with the same id. The index and `/approve` links are in-memory (`pending_elicitations.py:1-35`).
4. After an orchestrator refresh, re-publish on the new session and publish `response.elicitation_resolved` for the old id. The visit row, not the elicitation, is the truth.
5. Reminders and escalations are Coral timer rows. They remind and escalate, and **never** auto-approve.
6. A late answer to a superseded visit is rejected by the CAS (deep dive §6.2).

**`ask_user`** uses the same S6a and S6b with `kind = "question"`. Its answers become messages to the orchestrator.

**Budget prompt** (§6) uses the same path with `kind = "budget"` and choices `{raise_limit, stop_run}`.

### 4.4 Risks

| # | Risk | Mitigation |
|---|---|---|
| G1 | A native step agent with an unsandboxed shell can read the bridge-dir bearer (`native/orchestration.py:9290, 9832`) and POST an `approval` for the orchestrator's gate (same user, `LEVEL_EDIT`) | Validator: label gates *Enforced (assuming no shell access to server credentials)* for native steps; prefer claude-sdk (secrets stripped, `identity.py:88-99`); bench probe for bridge-dir visibility inside the step sandbox (UNVERIFIED) |
| G2 | Single-user server with no auth: any local process can answer | Document it; teams require auth |
| G3 | Multi-replica: the pending index is per replica, and only the count is persisted (`pending_elicitations.py:29-35`) | Re-publish open gates on the replica that runs the engine worker; local-first is a single replica |
| G4 | The approval card's binary Approve/Reject on a multi-label gate | Always send a `requestedSchema` enum; reject `accept` without `content.decision` in the handler (return False, keep the card) |
| G5 | `_resolve_elicitation` forwards Coral ids to the runner | Harmless; the runner ignores unknown ids (UNVERIFIED); or skip the forward when a handler claimed the id |

### 4.5 Tests to extend

- S5: `tests/runtime/test_pending_elicitations.py`, `tests/runtime/test_subagent_block_notifier.py` (also T-S43).
- S6 and T-S47:
  - `tests/server/integration/test_sessions_elicitation_api.py`;
  - `tests/server/integration/test_sessions_elicitation_resolve_url.py`;
  - `tests/server/test_resolve_url_wakes_harness_park.py`;
  - `tests/server/test_resolve_tombstones_zombie_waiter.py` (the tombstone interplay).
- UI rendering of the enum form: `web/src/components/blocks/ElicitationSchemaForm.test.ts`, `ApprovalCard.test.tsx`.
- Engine gate CAS, re-publish and late answers: `tests/coral/` (simulate plus reducer).

---

## 5. Notifications and inbox

### 5.1 Current code

**Inbox.**

- Four kinds in a closed union (`InboxPage.tsx:189-193`):
  - approval: derived from `pending_elicitations_count > 0` plus `getSession` snapshots (`InboxPage.tsx:240-262`);
  - comment;
  - unread;
  - automation: `GET /v1/scheduled-tasks/inbox` (`omnigent/server/routes/scheduled_tasks.py:741-771`), client at `web/src/lib/scheduledTasksApi.ts:504-513`, hook `web/src/hooks/useAutomationInbox.ts:10-44`.
- The automation kind is gated by the server-info field `scheduled_task_inbox` (`app.py:317, 3690`). Its read state is localStorage (`useSeenAutomationFailures.ts:58-70`), and it polls every 300 s.
- The card renderer for the automation kind is at `InboxPage.tsx:486-526`.

**Browser and OS notifications.**

- `browserNotifications.ts:1-16`: page-scoped; Electron uses `nativeNotify`.
- `useIdleNotifications.ts:1-30`: fires on transitions of `running → idle` and on pending-count increases, from the conversations poll.
- iOS and Android: foreground local notifications only (`web/ios/README.md:17-22`).

**Slack.** A separate service (`integrations/slack/src/omnigent_slack/*`) that renders approval cards in the **Slack thread of Slack-originated sessions** (`integrations/slack/README.md:345-348`; `elicitation.py`; `notifications.py`). It is not a general notification channel.

**Absent.** Web Push, VAPID, APNs, FCM, SMTP and email libraries: no matches in `omnigent/`, `integrations/` or `web/src` (the `pnpm-lock.yaml` hits are hash substrings). Upstream issue #1751 (`designs/prioritization/issue-prioritization-v2.md:639`).

### 5.2 Design: the `workflow` inbox kind and server feed (S37, concrete)

**Server (Coral API, mounted through `extra_routers`).** A `coral_alerts` table: `id`, `run_id`, `kind`, `severity`, `created_at`, `ack_at`, `ack_by`, `payload`, plus owner and workspace (deep dive §7).

```
GET  /v1/coral/inbox?limit=50&after=<cursor>  -> {data: [WorkflowAlert], next_cursor}
POST /v1/coral/inbox/{alert_id}/ack           -> 204   (server-side, device-independent)
POST /v1/coral/runs/{run_id}/actions          -> {action: "extend" | "cancel" | "resume" | "steer", ...}   (D10)

WorkflowAlert = {
  alert_id, run_id, run_title, kind, severity: "info" | "warn" | "error",
  created_at, step_label?, message, actions: ["open_run", "extend", "cancel", "resume"],
  deep_link: "/workflows/runs/<run_id>"
}
kind ∈ {decision_overdue, step_overdue, run_paused_rejected_calls, run_paused_budget,
        run_paused_plan_limit, step_waiting_on_approval, run_failed, run_completed (opt-in)}
```

- **Gates and questions are not alerts.** They already appear as **approval** items because they are elicitations on the orchestrator session. A gate reminder raises the elicitation again; the alert row is only for escalation.
- Server info gets a `workflow_inbox: bool` field following `scheduled_task_inbox` (`app.py:317, 3690`), behind the `workflows` flag (S33).

**Web.**

- Add `| { kind: "workflow"; key; at; item: WorkflowAlert }` to `InboxEntry` (`InboxPage.tsx:189-193`).
- Add a `useWorkflowInbox` hook modelled on `useAutomationInbox`, but with server ack.
- Add a card branch modelled on `InboxPage.tsx:486-526`, with action buttons.
- Fold the count into `useSidebarData` (`web/src/hooks/useSidebarData.tsx:239-241`).
- The UI doc has no visual for this kind (D3).

**S36.** Suppress per-step turn-end OS notifications for sessions labelled `coral.run_id`, except for the orchestrator (`useIdleNotifications.ts:122-125, 424-441`). Pending-elicitation notifications stay.

### 5.3 The delivery gap (Draft 4 §5.5 and §13)

Recommendation, in order:

1. **v1:** state plainly in the run dialog and gate cards that unattended gates are seen only when the app is open, or through Slack for Slack-originated runs.
2. **Phase 5-7:** a Coral **notification connector** fed from `coral_alerts` and gate rows, through the same transactional outbox as other effects (deep dive §6.1).
   - Start with a generic HTTPS webhook (for example a Slack incoming webhook), configured per user.
   - Then email (SMTP or provider).
   - Each delivery is idempotent on `(alert_id, channel)`.
   - The payload carries a deep link to `/approve/:sid/:eid` and never secrets.
3. **Later:** Web Push (service worker, VAPID sender, push subscriptions table) and APNs/FCM in the shells. These are large and upstream-tracked (#1751). The `ApprovePage` and `DeepLink.swift` (`web/ios/Omnigent/DeepLink.swift:100-133`, S38) already exist as landing targets.

### 5.4 Tests

- Web: `web/src/pages/InboxPage.test.tsx`, `web/src/hooks/useAutomationInbox.test.tsx` (pattern), `web/src/hooks/useIdleNotifications.test.tsx` (S36), `web/src/hooks/useSidebarData.test.tsx`.
- Server: a new `tests/coral/api/test_inbox.py`. `tests/server/test_feature_flags.py:21-50` (exact frontend defaults) must be updated with S33.
- No browser E2E under the repo rules; use `browser_ui/` contract tests only if needed.

---

## 6. Budgets

### 6.1 Current code

**`cost_budget(max_cost_usd, ask_thresholds_usd, expensive_models)`** (`cost.py:416-558`):

- gated phases are `request` and `tool_call` (`cost.py:139-142`);
- unpriced usage (tokens present, `total_cost_usd` absent) returns `_UNPRICED_ASK` (505-508), although the docstring says DENY (36-41);
- the hard cap DENYs when `_model_blocked_over_budget`;
- `expensive_models` omitted means every model is blocked;
- soft thresholds ASK, with approval recorded in `_policy_cost_ask_approved_usd`, routed to the root (`engine.py:589-610`).

**Usage injected into policies.** `_sum_subtree_usage(tree, root)` over the verified spawn tree (`builder.py:803-816, 1437-1494`). It prefers per-conversation `policy_cost_usd` (claude-native real-time) and falls back to `total_cost_usd`.

**Public helpers.**

- `load_session_usage(conversation_id, store, *, root_conversation_id=None)` (`builder.py:1263-1314`);
- `load_session_usage_and_tree` (1316-1342);
- `load_session_tree` (1344-1375).

**`subagent_cost_budget`** (`cost.py:809`) uses subtree usage (`builder.py:818-826`).

### 6.2 Run-level budget design

**Spend.** For a run, sum `policy_cost_usd ?? total_cost_usd` over every session the run created:

- the orchestrator and its predecessors;
- step members, including refreshed and restarted sessions;
- verifiers;
- save-time translation sessions, attributed to the workflow version, not the run.

The method depends on topology:

- **Children topology** (deep dive §8.2 default): one call, `load_session_usage(orchestrator_root)`, covers the tree. Refreshed orchestrators are new roots, so sum each root.
- **Top-level sessions:** iterate over `coral_agent_slots.session_id` and history rows, calling `load_session_usage` per root.
- Store `coral_runs.spend_usd` and `spend_tokens` snapshots with a monotonic `spend_at`.

**When.**

- On every turn-edge signal (S1), because usage is refreshed at turn boundaries (`cost.py:46-48`).
- Before starting any activation, as a pre-flight against `limit - spent - estimate_for_activation` from Simulate and past medians.
- In the periodic reconcile.

**Pause.** On `spent >= limit`:

- the reducer moves the run to `paused(budget)`: no new activations, briefs, nudges or refreshes;
- `run_guard` (T-S44) DENYs agents' non-`coral_*` tool calls on every mode, so in-flight turns wind down;
- the engine publishes a **budget elicitation** on the orchestrator session (§4.3, `kind = "budget"`) and a `run_paused_budget` alert.

Answering "raise limit" records an amendment-style event and resumes. "Stop" cancels the run.

**Overshoot.** Bounded by roughly one turn per concurrently running session. Show this in the run dialog.

**Steps with their own limits.** Use the same per-slot sums, which pause only that activation.

**Backstops (optional).**

- `cost_budget(max_cost_usd = remaining_run_budget)` with **no** `ask_thresholds_usd`, so it never ASKs on the soft path.
- Unpriced usage still ASKs. Either avoid the policy for unpriced models, or patch `cost.py:505-508` to honour a `fail_mode="deny"` parameter, which would be a fork patch.
- Prefer `run_guard` alone.

**Subscription users.** USD is an estimate (deep dive §12). For plan users, budgets should also be expressible in tokens: the sum of `total_tokens` from the same usage dicts. The plan-limit pause (S24) is separate.

### 6.3 Tests

- `tests/policies/builtins/test_cost.py`, `test_subagent_cost.py` (backstop configuration).
- `tests/server/integration/test_inherited_session_budget.py`, `test_subagent_budget_surprise_block.py` (tree sums).
- `tests/runtime/policies/test_session_cost_ask_routing.py`.
- Engine budget pause and resume: `tests/coral/engine/test_budget.py` with stubbed usage reads.

---

## 7. Seam ledger additions (T-S41 to T-S47) and refinements

| ID | Seam | Location | Size | Phase | Upstream? |
|---|---|---|---|---|---|
| T-S41 | Runner provenance predicate for server-dispatched tools (reusing the cost-control label logic) | `helpers.py:11002-11045` (extract `runner_proof`); used at `orchestration.py:13058` | XS | 2 | Yes |
| T-S42 | Extension tool provider. One declaration feeds ToolManager (S7), `should_dispatch_locally` (S8), the native relay (S9), native pre-approval (S11) and framework instructions (S12). | New `omnigent/tools/extensions.py`; call sites `manager.py:192`, `tool_dispatch.py:609-615, 950-958`, `native/orchestration.py:9819-9846, 5785-5799`, `app_server.py:327-337`, `prompt.py:62-87` | S | 2 | Yes |
| T-S43 | Parent-wake suppression for engine-managed children | `subagent_block_notifier.py:297-300` | XS | 2 | Yes (generic label) |
| T-S44 | Required-policy provider (generalizes `_REQUIRED_APPROVAL_SPECS`) plus the `any_policies_apply` fast path | `builder.py:101-104, 415-480, 654, 744-772` | S | 4 (run_guard needed by phase 7, but pause and cancel in phase 2) | Yes |
| T-S45 | Reserved `coral.` labels in the policy label-write path | `engine.py:521-547` | XS | 4 | Maybe |
| T-S46 | Run-owned session mutation guard (agent bundle PUT, MCP server edits) | `routes_agent.py:289-347`; `session_mcp_servers.py:169-222` | S | 4 | Maybe |
| T-S47 | Resolver identity plus verdict-handler registry in `_resolve_elicitation` | `orchestration.py:2400`; callers `routes_events.py:2214`, `routes_elicitations.py:127-131` | S | 2 | Yes |

**Refinements to existing seams.**

- **S5:** add a list plus per-observer exception isolation (`pending_elicitations.py:183-198`).
- **S6:** S6a is the extracted publish helper, from `routes_events.py:2222-2257`.
- **S7:** use the `params.coral` opt-in instead of a typed AgentSpec field.
- **S10:** see the `ServerToolCall` signature in §2.3, which includes operation-id and provenance.
- **S11:** add the codex site `app_server.py:327-337`.
- **S12:** add native helpers that carry extension text only.
- **S14:** three concrete sites plus the bridge-config fail-mode flag.
- **S26:** add label-prefix reservation in `_reject_server_reserved_label_seed`.
- **S36 and S37:** feed and ack server-side; add the `workflow_inbox` server-info field.

---

## 8. Work packages (dependency-aware)

| WP | Scope | Depends on | Phase | Size |
|---|---|---|---|---|
| ET-1 | T-S42 provider plus Coral `tool_schemas` (six schema-only tools, per-step schema from `params.coral`) | S29 (packaging, entry point) | 2 | M |
| ET-2 | S10 registry plus T-S41, with `sys_advise_models` migrated | none | 2 | S |
| ET-3 | Handlers for `coral_submit_handoff` (structural, checked parts, synchronous evidence hook stub) and `coral_choose_arrow`; rejection log and per-slot counter | Engine reducer (phase 1), ET-1, ET-2, S4 | 2 | M |
| ET-4 | `coral_message_agent` (orchestrator to step in phase 2; parallel peers in phase 6), `coral_ask_user`, `coral_assign_agents`, `coral_assign_task` | ET-3, S6a and S6b (ask_user) | 2 / 6 | M |
| ET-5 | S12 framework instructions (headless plus native launch channels) | ET-1 | 2 | S |
| EG-1 | S5 observer list plus T-S43 | none | 2 | XS |
| EG-2 | S6a, S6b and T-S47; gate outbox effect; startup re-publish; Coral gate, question and budget elicitation builders | Gate rows (phase 1), S32 lifespan | 2 | M |
| EP-1 | `coral.policies` module (orchestrator_guard, step_roster deny-only, hygiene) through `policy_modules`; bundle generator emits guardrails | ET-1 (bundle generator), per-step bundles (deep dive §8.5) | 2 | S |
| EP-2 | T-S44 required-policy provider plus `run_guard` (pause and cancel) | EP-1 | 2-4 | S |
| EP-3 | Protection: S26, T-S45, T-S46 | Labels scheme decided | 4 | S |
| EP-4 | S14, S15 and S16 (native fail-closed, codex refusal, sub-agent identity); `step_roster` counting for sub-agent mode | Bench probes S22 and S23 | 4 | M |
| EN-1 | `coral_alerts` table plus alert producers (watchdog, overdue, rejected-call pause, step waiting on approval) | Timers (phase 1), EG-1 | 2-3 | S |
| EN-2 | Inbox `workflow` kind: feed, ack, actions, server-info field; S36 suppression | EN-1, S33, S34 | 5 | M |
| EN-3 | Notification connector (webhook first) through the outbox | EN-1; product decision | 5-7 | M |
| EB-1 | Run spend aggregator, budget pause, budget elicitation, run_guard budget reason | EP-2, EG-2, S1 | 7 | M |

---

## 9. Open questions

1. Is `params.coral` acceptable as the opt-in, or does the team want a typed `AgentSpec` field? The CLAUDE.md rule leans towards `params`.
2. Should `run_guard` be injected through T-S44 (a fork patch to the hot `builder.py`), or attached as a protected session policy (S26 only)? This trades cache lag against patch size.
3. Gate integrity for native steps (G1): accept the "Enforced, assuming no shell access to server credentials" label, or require claude-sdk (or sandboxed native shells) for runs with gates?
4. Single-user provenance: should Coral refuse engine tools without runner proof, at the cost of loopback runners with stable ids failing (`helpers.py:11017-11019`)?
5. Who may answer gates when teams arrive: edit level (today's elicitation bar) or manage level?
6. Which notification channel comes first (webhook, Slack DM or email), and where is per-user channel configuration stored?
7. Does `ask_user` pause the decision watchdog only, or also the run's overdue clocks?
8. Should Coral-run check failures return synchronously in the `submit_handoff` result (long call), or asynchronously as a message (recommended)?
9. `coral_assign_task` as a separate tool, or a `mode` on `assign_agents` (D9)?
10. Exact Claude Code tool names for teams and workflows (`SendMessage`, `ListAgents`, `Workflow`) and the CLI version that supports `onFailure: "block"`. These come from the deep dive's web sources and were not verified here.
