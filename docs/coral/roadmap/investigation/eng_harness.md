# Coral: executors and harness modes, capabilities and bench, agent specs and bundles, Agent Profiles, auth

**Author:** Staff Engineer, Agent 3 (harness and profiles area)
**Codebase:** Omnigent fork at `omnigent-ai/omnigent`, HEAD `2a9cbe2c2` (0.22.0.dev0)
**Inputs:** `coral-design.md` (Draft 4), `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` (audit of Draft 3 at this commit), `coral_UI_DESIGN_LANGUAGE.md`
**Method:** I opened every `path:line` cited below at HEAD. No repository file was edited. No app, server, browser or test suite was run. **UNVERIFIED** marks claims I could not confirm from code, such as vendor-CLI runtime behaviour or SDK internals that are not vendored in the repo. Change types follow the brief: **Reuse** (as is), **Extend**, **Modify**, **New**, **Replace**, **Remove**.

---

## 0. Executive summary (what changes the roadmap)

1. **`claude-sdk` is the only mode where Coral can label rules and evidence *Enforced* at this commit. It should be the v1 default for the orchestrator and for step agents, using API-key or provider auth only.** Its base tool set is `["Skill", "ToolSearch", (+AskUserQuestion)]` (`omnigent/inner/claude_sdk_executor.py:2571-2585, 3069`). All workspace work goes through Omnigent `sys_os_*` tools, which are TOOL_CALL-gated on the server. A failed policy round-trip fails *closed* for TOOL_CALL (`omnigent/runner/policy_proxy.py:99-111`). New finding: the `enable_native_tools` flag computed by `prepare_claude_cli_path` is vestigial. It is stored on `self._os_env` (`claude_sdk_executor.py:1898, 1954`) and never read. So no native Bash/Edit can appear today, whatever the sandbox setting. Coral needs a contract test to keep it that way.
2. **The orchestrator's "no heavy work" can be Enforced *by construction* in `claude-sdk`.** A profile that omits `os_env` registers no `sys_os_*` tools at all (`omnigent/tools/manager.py:632-634`), and the SDK exposes no native workspace tools (finding 1). In the native modes the same guarantee depends on PreToolUse hooks, which fail to ASK (`omnigent/harnesses/claude_native/hook.py:1238-1242`; `omnigent/harnesses/codex_native/hook.py:149-153`). **The orchestrator must be `claude-sdk` in v1.**
3. **A Coral Agent Profile should be an Omnigent agent bundle, a server or user agent row, carrying Coral metadata under `params.coral`. Runs pin it by content digest in a new `coral_profile_revisions` table.** Option (a), plus a thin pin table. Profiles reuse `POST /v1/agents`, `PATCH /v1/agents/{id}`, Settings > Custom agents and the GitHub install. A top-level `coral:` key would be dropped silently (`omnigent/spec/parser.py:202-367`, which reads only known keys), while `params` survives both parse and PATCH edits (`parser.py:290`; `omnigent/server/agent_config.py:172-250` round-trips the whole YAML dict).
4. **Step sessions bind to a *generated, content-addressed per-step agent row*.** The row is made with the existing request-free `uploaded_agent_for()` (`omnigent/server/bundles.py:324-377`; id = `sha256(owner, name, files digest, attempt)`, `omnigent/db/utils.py:1149-1160`). Sessions are then created with `agent_id` plus `parent_session_id`. Child *uploads* are the wrong path: they mint a fresh agent row per session (`omnigent/server/routes/_sessions/orchestration.py:12694-12735`), which floods "my agents".
5. **Profile drift has five upstream entry points:** `PATCH /v1/agents/{id}`, reinstall by `POST /v1/agents`, `PUT /v1/sessions/{id}/agent`, session MCP-server edits, and `DELETE ...?force`. The runner follows whichever bundle the row holds on the next turn (`agent_revision`, `omnigent/runner/app.py:8410-8449`). Coral needs a reserved-name guard (new seam **H-S43**) plus a drift check on every turn signal.
6. **Auth (S13) is more than "prefer an API key".** In `claude-sdk`, a launch with no spec auth and no provider falls through to the CLI's own subscription login. The executor also strips `ANTHROPIC_API_KEY` on purpose (`claude_sdk_executor.py:2091-2118`). HTTP-uploaded bundles never expand `${VAR}` on the server (`omnigent/server/bundles.py:110-117`). The CLI install path expands `${VAR}` on the client and **stores literal secrets in the bundle blob** (`omnigent/cli.py:6614-6644`). Requirements: Coral profiles reference credentials only by **provider name** (`executor.auth: {type: provider}`, `omnigent/spec/types.py:456-492`). Coral defers to operator inference bindings, which *raise* on conflicting spec auth (`omnigent/inference_config.py:164-182`). A runner-side guard refuses subscription auth for run-owned `claude-sdk` sessions.
7. **The capability catalog does not expose `claude-native` or `codex-native` to the web.** `harness_catalog()` iterates `harness_labels`, which has no native Claude or Codex key (`omnigent/harness_plugins.py:941-953, 1255-1300`). The web reads only `integration_mode` and `effort` (`web/src/lib/agentLabels.ts:41-47`). Coral's validator must run server-side on `harness_capabilities()`, and the canvas needs a by-spelling capability map (new seam **H-S41**).
8. **Headless `codex` silently loses read-only mode:** `if tools and sandbox_mode == "read-only": sandbox_mode = "workspace-write"` (`omnigent/inner/codex_executor.py:5245-5247`). Engine tools are always present, so a "read-only reviewer" on headless `codex` can never be enforced by Codex's own sandbox (new seam **H-S46**). Headless `codex` also ignores `account/rateLimits/updated` (`codex_executor.py:4569-4576`) and fails *open* when hook trust fails (`codex_executor.py:3304-3318`).
9. **`codex-native` child sessions default to `--dangerously-bypass-approvals-and-sandbox`** (`omnigent/server/routes/_sessions/helpers.py:10631-10720`; docstring at 10647-10658). That turns off Codex's command sandbox. Coral must choose an explicit approval and sandbox stance per step (new seam **H-S47**).
10. **The subagent router is model and harness routing, confirmed.** It is advisory and fail-open, it is started only for Smart Routing SDK sessions (`omnigent/runner/subagent_routing.py:1-8, 375-402, 886-897`; `omnigent/runner/app.py:9032-9073`), and it has no roster. Draft 4 still claims a "fail-closed router" (`coral-design.md` §6, §7.4, §16, §18). That claim is wrong and must be replaced by spec grants plus a `step_roster` TOOL_CALL policy plus S14.
11. **Sandbox scope differs by mode, and the deep dive does not cover this.** In `claude-native` the whole Claude Code TUI inherits `os_env.sandbox`, including `egress_rules` (`omnigent/runner/native/orchestration.py:9880-9890, 9963-9972`). Egress rules must therefore also allow the model-provider host. In `claude-sdk` the CLI runs *outside* a network-denying sandbox, and only the `sys_os_*` helpers are confined (`claude_sdk_executor.py:1601-1607`).
12. **Input scoping (the Elephant-Goldfish template, D4) is breakable today.** `sys_session_list`, `sys_session_get_history` and `sys_session_get_info` are registered for *every* agent and read any session the user can access (`omnigent/tools/manager.py:402-470`; `omnigent/tools/builtins/spawn.py:1545-1548`). A "goldfish" reviewer can read the elephant's or the orchestrator's history unless a DENY policy, or a new `tool_groups` switch (**H-S50**), removes them.

**Modes for v1:** `claude-sdk` (default, orchestrator and steps), plus `claude-native` for subscription users (steps only, separate sessions only, Required rules only after S14). `codex-native` comes in v1.1, after S2, S12-native, S14, S15, S16 and H-S47. Headless `codex` comes last, after S18-S20, H-S45, H-S46 and H-S57, and once the OpenAI terms question is resolved. Details are in §13.

---

## 1. Discrepancies (D1–D4 confirmed and refined, plus new ones in this area)

| # | Status | Detail and evidence |
|---|---|---|
| D1 (router) | **Confirmed** | Draft 4 still says "Enforced, in separate-session mode and in sub-agent mode with the fail-closed router" (`coral-design.md` §6 table), "enforced through the sub-agent router in fail-closed mode" (§7.4), and lists "a fail-closed mode for the sub-agent router" as a patch (§16) and in phase 2 (§18). Code: "ask which model the spawn should run on. The gate is **advisory**" (`omnigent/runner/subagent_routing.py:1-8`). The actions are allow, rewrite, redirect, and deny for an unoffered model only (`subagent_routing.py:375-402, 886-897`). It starts only for Smart Routing sessions (`omnigent/runner/app.py:9032-9073`). Matchers are `Agent|Task` (`omnigent/inner/hook_scripts/subagent_router.py:83-84`). **Refinement:** in `claude-sdk` the in-process router hook is registered on `Agent|Task` (`claude_sdk_executor.py:2499-2550`), but those tools are *not in the base tool set* (`claude_sdk_executor.py:2571-2585`). Claude vendor sub-agents are therefore unreachable in `claude-sdk` by construction (UNVERIFIED at runtime; a probe is needed). Sub-agent mode in `claude-sdk` can only mean Omnigent child sessions through `tools.agents`, which are attributable by construction. |
| D1 (80% vs 70%) | Confirmed, **not a code fact** | Draft 4 §7.5 uses 70% "below the agent's own automatic compaction"; the deep dive §8.9 says 80%. Neither is in code. The engine needs a per-mode threshold *derived from* the native auto-compact point (Claude PreCompact; Codex `model_auto_compact_token_limit`), not one constant. The `CompactionConfig` default of "trigger at 80%" (`omnigent/spec/types.py:1510-1512` docstring) applies to Omnigent's own loop, not to `claude-sdk` or `codex`. |
| D1 (API keys "already supported") | **Partial** | `ApiKeyAuth`, `ProviderAuth` and the provider kinds `key`, `subscription`, `gateway`, `local`, `databricks` and `cli-config` exist (`omnigent/spec/types.py:388-497`; `omnigent/onboarding/provider_config.py:373-450`). But (i) uploaded bundles keep `${VAR}` literal (`bundles.py:110-117`), (ii) CLI installs bake resolved secrets into the blob (`cli.py:6614-6644`), and (iii) an operator binding rejects conflicting spec auth (`inference_config.py:164-182`). "First-class API keys in every profile" therefore has to mean **provider references**, not keys. |
| D1 (web push, PersistentTaskScheduler, `cost_budget`, `sys_cancel_task`, sandbox on/off) | Outside this area | Confirmed by the deep dive. I re-verified only the sandbox part: `egress_rules` is an L7 allowlist (`omnigent/inner/datamodel.py:745-770`). Refinement: the sandbox *scope* differs per mode (finding 11). |
| D2 | **Confirmed** | `coral-requirements.md` is not in the repo (`ls` fails). Profile requirements beyond Draft 4 §5.4 and UI §8.3 are unspecified. |
| D3 | **Confirmed and extended** | No `web/src/components/concerto/*`, `CoralPageHeader`, `--concerto-*` tokens, or `/schemas`, `/profiles` or `/workflows` routes (grep of `web/src` and `web/src/App.tsx` is empty). On profiles specifically: the UI doc treats profiles as "possibly localStorage scaffolding" (`coral_UI_DESIGN_LANGUAGE.md:320-336`). The design says profile = agent YAML + description + default rules + capabilities (`coral-design.md` §5.4). **Resolution (this doc §8):** server-resident Omnigent agents plus a Coral pin table, never localStorage. A Profiles desk page can exist (UI doc §5.1 `/profiles`) as a Coral view over `GET /v1/agents?scope=user` plus server agents plus Coral metadata. Upstream already ships a Custom agents settings editor (`web/src/pages/settings/SettingsCustomAgentsSection.tsx`, `CustomAgentConfigForm.tsx`; `designs/CUSTOM_AGENTS_SETTINGS_UI.md`). |
| D4 | **Confirmed and extended** | Persistent-session and input-scoping options are absent from Draft 4. New code facts: input scoping needs the session-read tools removed (finding 12). A persistent session across loop passes needs the slot to keep `session_id` and the per-step agent row stable across passes. Content-addressed rows (§9) make that natural. |
| **D5 (new)** | Draft 4 §9 table, "Gate tool calls: Yes" for `codex` | **Incorrect.** Codex's own shell and `apply_patch` run under `approvalPolicy: "never"` (`codex_executor.py:3829`) and are only *observed* (`codex_executor.py:2774-2834`). Web search is on by default (`codex_executor.py:4768`; disabled only by server-process env, `5014-5018`). |
| **D6 (new)** | Draft 4 §9, "Read context use: Yes" for `claude-sdk` and `codex` | **Partial.** Tokens are reported (`TurnComplete.usage.context_tokens`, `claude_sdk_executor.py:3616-3645`; Codex `thread/tokenUsage/updated`, `codex_executor.py:4277`). The *window* is not: `max_context_tokens()` returns `None` in the base class (`omnigent/inner/executor.py:704-705`). Fraction-of-window needs a server-side lookup or a per-model table. |
| **D7 (new)** | Draft 4 §17 Risk 1, "claude-native ... weaker steering and sub-agent visibility are covered by the validator" | The weaknesses that matter more are **gate failure mode = ASK** (`hook.py:1238-1242`), **hooks installed only when `ap_server_url` is set** (`omnigent/harnesses/claude_native/bridge.py:2651`, per the deep dive), and **the whole-agent egress scope** (finding 11). The validator must encode all three. |
| **D8 (new)** | Draft 4 §7.4: sub-agents allowed in one session "where Coral can verify them" | In `claude-sdk` no vendor sub-agent tool is exposed (D1 refinement). The only in-session fan-out is Omnigent `tools.agents` children, which are separate Omnigent sessions anyway. "Sub-agent mode" therefore differs from "separate sessions" only in topology and tool surface, not in attribution. Recommend treating sub-agent mode as **native-only and post-v1**. |

---

## 2. Fact re-checks in this area (deep dive F-rows) at HEAD

| F | Verdict now | Notes, refinements and exact evidence |
|---|---|---|
| F1 | Confirmed | Event model `omnigent/inner/executor.py:116-375`. `TurnComplete` `169-195` (fields `response`, `modified_by_policy`, `continue_turn`, `usage`). `ExecutorError` `331-375` (`code: str \| None` is free-form; there is no enum and no reset-time field). Sub-agent events `266-320` (ACP-only producers). `omnigent/harnesses/` holds bridges and forwarders, not executors. |
| F2 | Confirmed | DRIFT is computed by `reconcile` (`tests/harness_bench/verdict.py:112-137`). Declarations come from `_declared_from_capabilities` (`tests/harness_bench/manifest.py:55-76`), which also maps `resume`, `steering`, `live_queue`, `images` and `compaction` when declared, but **no probe exists for them** (`tests/harness_bench/README.md:234-235`). `ALL_PROBES` has 12 probes (`tests/harness_bench/probes/__init__.py:20-33`). Official SDK profiles: `{"claude-sdk", "codex", "pi", "openai-agents"}` (`manifest.py:96-102`). All `NATIVE_TUI` harnesses are auto-added (`manifest.py:145-154`). |
| F7 | Confirmed, refined | Two dialects: the single-file YAML compat path (`omnigent/spec/__init__.py:241-251`, 280-290) and bundle `config.yaml` with `spec_version` (`parser.py:202-367`). **Refinement:** in the bundle dialect the harness is selectable *only* through `executor.config.harness`, the field marked "TECH DEBT ... do NOT extend" (`omnigent/spec/types.py:544-556`, field at `619`). `_parse_executor` reads no top-level `executor.harness` (`parser.py:749-828`). Polly and the web bundle builder both use `executor.config.harness` (`examples/polly/agents/claude_code/config.yaml:5-11`; `web/src/lib/agentBundle.ts:55-59`). Coral must *use* `executor.config.harness`, `permission_mode` and `yolo`, but must not *put Coral data* there. |
| F18 | Confirmed | `parent_tool_use_id` is only hard-coded `None` on outbound messages (`claude_sdk_executor.py:763`). Tool metadata carries only `call_id` and `internally_executed` (`claude_sdk_executor.py:1019-1031`). |
| F19 | Confirmed | — |
| F20 | Confirmed | Declarations: `claude-sdk` at `omnigent/harness_plugins.py:591-602`, `codex` `603-614`, `claude-native` `358-371`, `codex-native` `373-386`. |
| F21 | Confirmed | `steering`, `live_queue`, `images` and `compaction` default to `None` (`omnigent/harness_capabilities.py:155-158`). Runtime truth: `claude-sdk` `supports_live_message_queue()` is False (`claude_sdk_executor.py:2419-2422`). True for codex (`codex_executor.py:5042`), claude-native (`omnigent/inner/claude_native_executor.py:148-150`) and codex-native (`omnigent/inner/codex_native_executor.py:911-913`). |
| F22 | Confirmed | The test derives `subagents` from `subagent_wrapper_label` (`tests/test_harness_capabilities.py:75-92`). |
| F33 | Confirmed | `enqueue_session_message` returns False (`claude_sdk_executor.py:2323-2332`). |
| F34 | Confirmed | Interrupt closes the session (`claude_sdk_executor.py:2291-2321`; `codex_executor.py:5045-5076`). |
| F35 | Confirmed (see D6) | — |
| F36 | Confirmed | The runner `compact` dispatch has branches for `claude-native`, `codex-native` and `claude-sdk`; headless `codex` falls through to `Response(status_code=204)` (`omnigent/runner/app.py:7893-7912`). |
| F37 | Confirmed, refined | Default `claude-sdk` permission mode is `"auto"` (`omnigent/inner/claude_sdk_harness.py:135`). `can_use_tool` is installed whenever a policy evaluator *or* an elicitation handler is wired, "in EVERY permission mode" (`claude_sdk_executor.py:3132-3153`). It skips `mcp__omnigent__*` (already gated server-side) and gates connector-native MCP tools (`claude_sdk_executor.py:2727-2790`). Whether the CLI *invokes* `can_use_tool` under `auto` or `bypassPermissions` is **UNVERIFIED** and needs a probe (S21 is the fallback). |
| F38 | Confirmed | — |
| F39 | Confirmed, refined | `description` (`types.py:1607`), `params` (`1614`, parsed verbatim at `parser.py:290`), `guardrails` (`1645`). Unknown top-level keys are dropped because `parse()` builds `AgentSpec` only from known keys (`parser.py:339-367`). There is no unknown-key warning anywhere in `omnigent/spec/`. |
| F40 | Confirmed, extended | Install, list, detail and remove have shipped, and so has **owner-only config read and PATCH** (`omnigent/server/routes/builtin_agents.py:369-441`; `omnigent/server/schemas.py:200-247`; `/v1/info.agent_config_edit`, `omnigent/server/app.py:3677-3679`). Decision 6 (running sessions follow reinstalls) is implemented: `agent_revision` is stamped per turn and the runner rebuilds the spec on change (`omnigent/runner/app.py:8410-8449`). |
| F48 | Confirmed, refined | Auth precedence for `claude-sdk` launches is: inference binding, then ProviderAuth, then legacy Databricks, then ApiKeyAuth, then the global default provider, then the global `auth:`, then the Databricks model, then ambient, then a **saved Claude subscription**, then any provider (`omnigent/runtime/workflow.py:1123-1260`). With no provider and no ApiKey, the CLI uses its own login (`workflow.py:1381-1400`; strip at `claude_sdk_executor.py:2118`). The apiKeyHelper command is `printf %s '<key>'` in a spawn env var (`workflow.py:1393-1395`), so the key is visible in that subprocess's environment. |

---

## 3. What the engine can and cannot rely on from executors

| Engine need | Rely on | Do NOT rely on | Evidence |
|---|---|---|---|
| "The turn finished" | Server-side terminal events (claude-sdk relay `response.completed/failed/cancelled/incomplete`; codex `turn/completed`; claude-native Stop hook with `turn_completed=True`; codex-native `turn/completed`) | A native executor's `TurnComplete`. It is a *delivery receipt*: `yield TurnComplete(response=None)` right after injection (`claude_native_executor.py:553`; `codex_native_executor.py:1336-1337`). `del tools, system_prompt` (`claude_native_executor.py:394`; `codex_native_executor.py:1082`) | deep dive §8.7; code as cited |
| Failure classification | `ExecutorError.retryable`, `undelivered`, `preserve_session`, and `code` (free-form; e.g. `codex_compacting`, `codex_delivery_unconfirmed`, `codex_shell_busy`, `codex_shell_authorization_required` at `codex_native_executor.py:111-124, 624`; `CLAUDE_AUTH_FAILED_CODE` at `claude_sdk_executor.py:3800`) | A usage-limit code. None exists (S24) | `executor.py:331-375` |
| Plan-limit signal | Native only, and only as a category: claude-native `StopFailure` `failure_category` such as `"rate_limit"` (`omnigent/harnesses/claude_native/bridge.py:1096-1099`), forwarded as telemetry `native_error_category` (`omnigent/harnesses/claude_native/forwarder.py:3927`). codex-native classifies `codexErrorInfo` (`usage_limit_exceeded` is noted at `omnigent/harnesses/codex_native/forwarder.py:304-313`) but only for re-auth hints | Headless: `claude-sdk` has no `RateLimitEvent` branch. Only `_StreamEvent`, `AssistantMessage`, `UserMessage`, `ResultMessage` and `SystemMessage` are handled (`claude_sdk_executor.py:3407, 3480, 3548, 3586, 3656`). `codex` explicitly drops `account/rateLimits/updated` (`codex_executor.py:4569-4576`). Whether `native_error_category` lands in a durable status field the engine can read is **UNVERIFIED** (it appears in a telemetry dict). | S24 |
| Context fill | `usage.context_tokens` (claude-sdk last-call prompt size, `claude_sdk_executor.py:3600-3645`; codex token usage, `codex_executor.py:4277`); native labels `omnigent.last_context_tokens` and `omnigent.last_context_window` (deep dive F35) | `max_context_tokens()` (None) | `executor.py:704-705` |
| Compaction events | `CompactionStarted` from Claude `PreCompact` (`claude_sdk_executor.py:3700-3722`) and `CompactionComplete` (`executor.py:233-263`) | Headless codex compaction (none, F36) | — |
| Interrupt as steering | Never. Headless interrupt discards the vendor session (F34) | — | — |
| Instruction delivery | claude-sdk composed session snapshot; codex composed per turn (a prompt change restarts the thread); natives `AGENT_STARTUP_ADDITIVE` (`harness_plugins.py:370, 385, 601, 613`) | Per-turn system prompt in natives | — |

---

## 4. Verified capability matrix for the four Coral modes

### 4.1 Declared today (`_BUILTIN_CAPABILITIES`, `omnigent/harness_plugins.py:356-614`)

| Field | `claude-sdk` (591-602) | `codex` (603-614) | `claude-native` (358-371) | `codex-native` (373-386) |
|---|---|---|---|---|
| integration_mode | sdk-in-process | cli-subprocess | native-tui | native-tui |
| elicitation | none | jsonrpc | hook | jsonrpc |
| resume | cold-only | warm-reattach | warm-reattach | warm-reattach |
| effort | anthropic | openai | anthropic | codex-native |
| model_family | claude | gpt | claude | gpt |
| auth | omnigent-credential | omnigent-credential | omnigent-credential | omnigent-credential |
| subagents | False | False | True | True |
| interrupt / streaming | True / True (bench-verified) | True / True (bench-verified) | True / True (declared) | True / True (declared) |
| steering / live_queue / images / compaction | None ×4 | None ×4 | None ×4 | None ×4 |
| fork_history | none | none | rebuild | rebuild |
| shell_tool_name | None (bench tool probe skipped) | None | Bash | shell |
| instruction_delivery | composed-session-snapshot | composed-per-turn | agent-startup-additive | agent-startup-additive |

Exposure: `HarnessCapabilities.as_dict()` serializes all 17 fields (`omnigent/harness_capabilities.py:164-184`). `GET /v1/harnesses` returns `data: harness_catalog()` (`omnigent/server/routes/harnesses.py:18-30`), but **`claude-native` and `codex-native` are not catalog rows** (labels at `harness_plugins.py:941-953`; the loop at `1275-1283`). The web uses only `integration_mode` and `effort` (`web/src/lib/agentLabels.ts:41-47, 52-60`).

Observation (possible drift, UNVERIFIED): `claude-sdk` declares `elicitation=none`. But `can_use_tool` runs an elicitation handler on ASK verdicts when one is wired (`claude_sdk_executor.py:2790-2820`). The bench `policy_ask` probe on `full-server` would show which is true.

### 4.2 Coral-relevant behaviour (verified at HEAD; "probe" means a bench probe must confirm it)

| Capability | `claude-sdk` | `codex` (headless) | `claude-native` | `codex-native` |
|---|---|---|---|---|
| **Mid-turn input** | Buffered by the adapter into a continuation turn (`claude_sdk_executor.py:2323-2332`) → *next_turn* | `turn/steer` with `expectedTurnId` (`codex_executor.py:4399-4427`) → *mid_turn* | Bracketed paste into tmux under an injection lock (`claude_native_executor.py:122-150`) → *mid_turn, best effort* | `turn/steer` (`codex_native_executor.py:917-943`); refused while compacting (`codex_compacting`, `111`) → *mid_turn* |
| **Interrupt** | Yes; **drops the SDK session** (`2291-2321`) | Yes; **drops the thread** (`5045-5076`) | Escape keystroke, unconfirmed, 20 s grace (deep dive F34) | `turn/interrupt`, acknowledged (deep dive) |
| **TurnComplete meaning** | Model response | Model response | **Delivery receipt** (`553`) | **Delivery receipt** (`1336-1337`) |
| **Authoritative end of turn** | Relay terminal response events | `turn/completed` / `turn/failed` | Stop hook with `turn_completed=True` | `turn/completed` without the flag (S2) |
| **Context tokens / window** | Tokens yes / window from server lookup | Tokens yes / window **UNVERIFIED** (does `thread/tokenUsage/updated` carry `modelContextWindow`?) | statusLine labels (tokens + window) | `thread/tokenUsage/updated` (tokens) / window **UNVERIFIED** |
| **Trigger compaction** | `/compact` turn (`runner/app.py:7910-7911`) | **No** (204, `7912`); S19 | `/compact` typed (`7894-7895`) | `/compact` typed (`7896-7897`); keystrokes unverified |
| **Pre-call gating of workspace tools** | **All** (only Omnigent `sys_os_*`; no native tools) | **Omnigent tools only**; Codex shell and `apply_patch` are observed after the fact (`2774-2834`); web search is neither gated nor observed | Catch-all PreToolUse hook, *if* hooks are installed (`ap_server_url`) | Catch-all PreToolUse hook unless `policy_hook_disabled_reason` is set (`omnigent/harnesses/codex_native/app_server.py:2441-2448, 2501, 2850, 3056`) |
| **Gate failure mode** | **DENY** for TOOL_CALL (`policy_proxy.py:99-111`) | DENY for Omnigent tools (same server path, UNVERIFIED for dynamicTools specifically); n/a for native tools | **ASK** (`hook.py:1238-1242`); no session id or no server URL → no opinion (`hook.py:1221-1222, 1255-1258`) | **ASK** (`codex_native/hook.py:149-153`) |
| **Connector / vendor MCP tools** | Gated by `can_use_tool` (probe under the run-owned permission mode) | Codex MCP is not gated by Omnigent (UNVERIFIED) | Hook catch-all | Hook catch-all |
| **Vendor sub-agents available** | **No** (Agent/Task not in the base tools; UNVERIFIED at runtime) | Yes (`spawn_agent`; collab items ignored) | Yes (Agent/Task, teams) | Yes (`spawn_agent`) |
| **Sub-agent attribution** | n/a (no vendor sub-agents); Omnigent `tools.agents` children are separate sessions | **None** (keys on `turnId`, S18) | Transcript per child; no identity in policy (S16); child end is heuristic | Transcript per child thread; parent-session policy (S16) |
| **Engine-tool transport** | In-process SDK MCP server `omnigent` (deep dive F41) | `dynamicTools` + `experimentalApi: true` (`codex_executor.py:3289, 3838-3840`) | stdio relay with a static allowlist + pre-approval (`omnigent/runner/tool_dispatch.py:488`; S9/S11) | Same as claude-native |
| **Instruction delivery** | Session snapshot (system prompt replaced unless `system_prompt_preset: claude_code`, `claude_sdk_executor.py:3084-3089`) | `developerInstructions` on `thread/start` (`3836-3837`) | Launch-time append only | Launch-time only |
| **OS sandbox / egress scope** | **Helpers only**: the CLI runs unwrapped when the sandbox denies network (`1601-1607`) | Codex's own sandbox mode from `os_env` (`_sandbox_mode`, `2729-2739`), **upgraded to `workspace-write` whenever tools exist** (`5245-5247`); signer-backed rejects `egress_rules` (`4890-4894`) | **Whole agent**: the Claude TUI terminal inherits `os_env.sandbox` and `egress_rules` (`runner/native/orchestration.py:9880-9890, 9963-9972`), so the provider host must be allowlisted | The TUI terminal inherits `os_env` (`orchestration.py:5121-5131`); whether the *app-server process that runs tools* is wrapped is **UNVERIFIED** (no sandbox wrap found in `app_server.py`) |
| **Approval stance when unattended** | Policy only; elicitations only on ASK | `approvalPolicy: "never"` (`3829`) | `executor.config.permission_mode` → `--permission-mode` (`helpers.py:10710-10715`) | **Default bypass** `--dangerously-bypass-approvals-and-sandbox` for child creates unless `yolo: false` (`helpers.py:10647-10658`) |
| **Plan-limit / usage-limit signal** | None (S24) | None; explicitly ignored (`4569-4576`) | `StopFailure` category (telemetry) | `codexErrorInfo` (surface only) |
| **Hermetic "fresh context"** | `skills: none` → `setting_sources=[]` drops user and project settings, CLAUDE.md and user MCP (`claude_sdk_executor.py:3048-3112`; `types.py:1660-1667`) | Private CODEX_HOME per session; global `AGENTS.md` and `hooks.json` handling (`codex_executor.py:202-205, 1180-1200`); project AGENTS.md is UNVERIFIED | Not controllable through the spec (UNVERIFIED) | Not controllable through the spec (UNVERIFIED) |
| **Model override per session** | Yes (`HARNESS_CLAUDE_SDK_MODEL`) | Yes | `/model` typed per turn (`claude_native_executor.py` docstring at 371-382) | `thread/settings/update` (`codex_native_executor.py:1070-1080`) |
| **Bench coverage today** | Live-verified P0 set (official) | Live-verified P0 set (official) | `native-tui` driver (auto profile) | `native-tui` driver (auto profile) |

### 4.3 What this means for the validator (V9) and for labels

- **Enforced rules** (shell, file, website, roster): `claude-sdk` yes. `claude-native` and `codex-native` only after **S14** (fail closed) and **S15** (refuse when hooks are disabled), and only when hooks are confirmed installed. Headless `codex`: invalid until **S20 + H-S45 + H-S46**.
- **Read-only steps:** `claude-sdk` translates to `os_env.sandbox.write_paths: []` or `read_only_os`. On `codex`, Codex's sandbox is overridden (H-S46). On `codex-native`, the default bypass disables Codex's sandbox (H-S47).
- **Website rules:** `egress_rules` works on `claude-sdk` (helpers only, which covers `sys_os_*` and `web_fetch`'s researcher). On `claude-native` it covers the whole agent, so the provider endpoint must be added automatically. Codex signer-backed launches reject it.
- **Per-agent evidence inside one session:** no mode qualifies today. Separate sessions only (V9 rejects sub-agent mode in v1).

---

## 5. Capability model and bench: S22 / S23 made concrete

### 5.1 S22: fields (Extend `omnigent/harness_capabilities.py`)

Keep the frozen dataclass and add **optional** fields that default to `None` (the same pattern as `steering`, `harness_capabilities.py:155-158`), so community plugins are unaffected. Add enums next to the existing ones (`harness_capabilities.py:24-104`).

| Field (Proposed) | Type | Meaning | `claude-sdk` | `codex` | `claude-native` | `codex-native` | How to keep it honest |
|---|---|---|---|---|---|---|---|
| `steering` (existing) | bool | Input can reach an active turn | False | True | True | True | Guard test: equals `executor_cls().supports_live_message_queue()` |
| `live_queue` (existing) | bool | Follow-ups can be queued mid-turn | False (adapter buffers; executor False) | True | True | True | Same guard |
| `compaction` (existing) | bool | Engine can trigger compaction | True | **False** (True after S19) | True | True | Guard test against the runner `compact` dispatch table (`runner/app.py:7893-7912`) |
| `steering_reliability` | enum `none / next_turn / mid_turn / mid_turn_best_effort` | Where an injected message lands | next_turn | mid_turn | mid_turn_best_effort | mid_turn | Probe |
| `turn_complete_semantics` | enum `response / delivery_receipt` | What executor `TurnComplete` means | response | response | delivery_receipt | delivery_receipt | Guard test on native executors (unit) |
| `end_of_turn_detection` | enum `response_terminal / protocol_event / hook / heuristic` | Authoritative turn-end source | response_terminal | protocol_event | hook | protocol_event | Probe |
| `usage_reporting` | enum `none / tokens / tokens_and_window` | Context-fill observability | tokens | tokens (window UNVERIFIED) | tokens_and_window | tokens (window UNVERIFIED) | Probe (extend `cost_tracking`) |
| `tool_call_gating` | enum `all_tools / omnigent_tools_only / hook_catch_all / none` | Pre-call gate coverage | all_tools | omnigent_tools_only | hook_catch_all | hook_catch_all | Probe with the **vendor** shell |
| `gate_failure_mode` | enum `deny / ask / open` | Outcome when no verdict is obtainable | deny | deny (Omnigent tools) | ask (deny after S14) | ask (deny after S14) | Probe with the endpoint made unreachable |
| `subagent_attribution` | enum `none / transcript_only / per_tool_call / not_applicable` | Per-agent evidence inside one session | not_applicable | none | transcript_only | transcript_only | Probe |
| `usage_limit_signal` | enum `none / category_only / structured` | Plan or usage limit carries a reset time | none (S24) | none (S24) | category_only | category_only | Mock-provider probe (§5.3) |
| `egress_scope` | enum `helpers_only / whole_agent / vendor_sandbox` | What `os_env.sandbox` and `egress_rules` confine | helpers_only | vendor_sandbox (UNVERIFIED for helpers) | whole_agent | whole_agent (TUI); app-server UNVERIFIED | Unit guard + probe |
| `exit_status_source` | enum `is_error / exit_code / none` | Evidence quality (deep dive §9.1) | is_error | exit_code | is_error (transcript) | exit_code | Unit, from translators |

Files and tests:
- **Modify** `omnigent/harness_capabilities.py:106-184`: fields, enums, docstrings and `as_dict()`.
- **Extend** `omnigent/harness_plugins.py:358-386, 591-614`: values for the four modes. Leave other harnesses `None`.
- **Modify** `tests/test_harness_capabilities.py:123-163`. The exact-dict assertion `test_optional_bench_capabilities_default_to_unknown` will fail as soon as keys are added. Add guard tests: `steering`/`live_queue` against `supports_live_message_queue()` for the four executor classes; `compaction` against the runner branch list; `turn_complete_semantics` against native executors.
- **Extend** `tests/harness_bench/manifest.py:55-76`: map each new field to a declared `Verdict`. Enums map to SUPPORTED, PARTIAL or UNSUPPORTED per probe. For example `gate_failure_mode=ask` gives PARTIAL for a "fails closed" dimension.
- **Coral-side:** `coral/validate/capabilities.py` (New) computes *effective* enforceability as declared field × host facts (CLI version, `policy_hook_disabled_reason`, `ap_server_url` present) × step settings. Keep the upstream fields generic.

### 5.2 H-S41: expose capabilities for every spelling (Extend)

`harness_catalog()` drops non-picker harnesses (`harness_plugins.py:1275-1283`). Add `capabilities_by_spelling` next to `setup_steps` in `GET /v1/harnesses` (`omnigent/server/routes/harnesses.py:27-30`). Precedent: `harness_setup_steps_by_spelling()` (`harness_plugins.py:1303-1328`) and its test (`tests/test_harness_capabilities.py:250-260`). Size XS. Upstream candidate.

### 5.3 S23: bench probes (test-only; Extend `tests/harness_bench/`)

Pattern: one module per dimension under `probes/` implementing `CapabilityProbe` (`probes/base.py:19-48`), registered in `ALL_PROBES` (`probes/__init__.py:20-33`). Add a semantic method to the `Driver` protocol (`transport.py:11-83`) and implement it in `FullServerDriver`, `NativeTuiDriver` and `SdkInprocDriver` (`transport.py:96-110`). Extend `TurnResult` (`driver.py:138-160`). Unit-test each probe's classification with a fake driver, as `tests/harness_bench/test_policy_matrix.py:41-80` and `test_cost_tracking.py:34-87` do.

| Probe (Proposed) | Driver method | Classification | Notes |
|---|---|---|---|
| `steering_reliability` | `run_steer_turn(marker)`: start a long turn, POST a second user message containing a marker after the first delta, record whether the marker is acknowledged in the *same* turn's text, in the *next* turn, or never | mid / next / none | Also cover the race where a steer arrives just after `turn/completed` [deep dive W-11] |
| `live_queue` / `steering` | Same as above | Derived | Confirms the S22 guard |
| `compaction` | `run_compact_turn()`: POST `{type: "compact"}` | SUPPORTED if `response.compaction.completed` arrives, UNSUPPORTED on 204 | Runner returns 204 for codex today |
| `end_of_turn_detection` | `run_basic_turn` + ordering check that the terminal event comes after the last output item | SUPPORTED / PARTIAL (early terminal) | The native driver already notes `response.completed` fires early (`native_tui_driver.py:73-74, 175-185`) |
| `tool_call_gating_vendor` | `run_vendor_shell_policy_turn(action)`: provoke `shell_tool_name` under a DENY policy | SUPPORTED if blocked before execution | The SDK family uses Omnigent `list_files` today (`full_server.py:53-56`). Headless SDK drivers need a vendor-shell provocation; `claude-sdk` should be N/A because there is no vendor shell |
| `gate_failure_mode` | `run_gate_outage_turn()`: attach a DENY policy, then make the policy endpoint unreachable (kill the relay, or point at a closed port through a test-only env) | deny / ask / open | Needs a fault-injection hook in the driver only, not in production code |
| `subagent_attribution` | `run_subagent_marker_turn(marker)`: ask for a sub-agent that runs `echo <marker>` | SUPPORTED if a child session or child attribution carries the call | N/A for `claude-sdk` |
| `usage_reporting` | Extend `run_basic_turn` snapshot read (`fill_snapshot_cost`, `driver.py:180-187`) with `context_tokens` and `context_window` | tokens / tokens_and_window | — |
| `usage_limit_signal` | `run_usage_limit_turn()` against the **mock provider** returning 429 with reset headers | structured / category / none | Live vendors cannot be forced; mock-only (README notes the mock validates plumbing, `README.md:75-80`) |
| `fresh_context` (Coral) | Plant a `CLAUDE.md`/`AGENTS.md` sentinel in the workspace and user home, then ask the agent to repeat it | Hermetic iff not echoed | Per step option "fresh: hermetic / project" |
| `input_scoping` (Coral) | Ask the agent to call `sys_session_list` and `sys_session_get_history` | Hermetic iff denied | Validates H-S50 or the DENY policy |

Run policy: `python -m tests.harness_bench --live --require-complete --harness <h> --dimension ...` with pinned CLI versions, nightly and on CLI bumps (`README.md:48-80`). Do not gate PRs on live probes. Offline: `--no-live` declared matrix plus probe unit tests. Coral-specific probes live in `tests/coral/bench/` and register through `--harness module:PROFILE` or an extended `ALL_PROBES` behind a flag, so upstream merges stay clean.

---

## 6. Agent specs and bundles: facts Coral must design around

| Fact | Evidence | Consequence |
|---|---|---|
| Bundle `config.yaml` needs `spec_version`; parse reads only known keys | `parser.py:229-236, 339-367` | Coral metadata goes in `params.coral` (preserved verbatim, `parser.py:290`). A new top-level key needs parser + types + validator changes (S7 for `engine_tools`) |
| Harness lives in `executor.config.harness`; `permission_mode`, `yolo`, `system_prompt_preset` and `smart_routing_harness` also live in `executor.config` | `types.py:544-556`; `workflow.py:1424-1441`; `examples/polly/config.yaml:20-31` | Generated bundles set these keys. Coral data never goes in `executor.config` |
| Uploaded bundles: `expand_env=False`, the handler allowlist is enforced, no server-side callables, no escaping cwd | `bundles.py:102-171`; `omnigent/spec/__init__.py:180-201`; `docs/AGENT_YAML_SPEC.md:769-783` | Translated policies must target registered handlers (`coral.policies` POLICY_REGISTRY module through server `policy_modules`, `omnigent/policies/registry.py:90-130`; `app.py:2046`). No secrets in bundles |
| Name pattern `[a-zA-Z0-9_-]+`; reserved `{"ui"}` | `omnigent/spec/validator.py:17-24, 598-626` | Reserved Coral prefix `coral__` is pattern-safe (H-S43) |
| `os_env` omitted → no `sys_os_*` tools | `tools/manager.py:632-634` | The orchestrator profile omits `os_env` |
| `tool_groups` toggles `browser`, `scheduled_tasks`, `comments`, `policies` (`sys_add_policy`), `agent_discovery` | `types.py:877-900`; `parser.py:317` | Generated bundles disable all unneeded groups. `sys_add_policy` is additive (DENY short-circuits), but turn it off for hygiene |
| Session read tools are always registered | `tools/manager.py:402-470` | Input scoping needs a DENY policy or H-S50 |
| `spawn` and `tools.agents` grants | `parser.py:307-317`; `types.py:1572-1583` docstring | Step bundles set `spawn: false`, `tools.agents: []` (separate-session mode) |
| `skills: none` → hermetic `claude-sdk` | `types.py:1660-1667`; `claude_sdk_executor.py:3104-3112` | "Fresh context" step option maps here |
| `executor.auth` types: `api_key`, `databricks`, `provider` | `types.py:388-497`; `parser.py:830-900` | Coral writes only `provider` (§10) |
| `CompactionConfig` and `context_window` exist | `types.py:658-680, 636` | Coral can pin `context_window` for unknown models (refresh threshold denominator) |
| Inference bindings (operator) override and *reject* spec auth | `inference_config.py:99-202` | Coral omits `executor.auth` when a binding exists for the harness |

---

## 7. Reusable user agents, Settings UI and drift

**Shipped, and reusable as is:**
- `GET /v1/agents` (server agents), `?scope=user` (owned, ≤50 per page), `GET /v1/agents/{id}` (with `user_owned`), `POST /v1/agents` (install or reinstall, ≤100 MiB, trusted-origin check), `DELETE /v1/agents/{id}[?force]`, `GET /v1/agents/{id}/config` + `PATCH /v1/agents/{id}` (ETag, merge-style: description, instructions, model, harness, mcp_servers) (`builtin_agents.py:369-626`; `schemas.py:200-247`).
- Request-free functions: `install_user_agent()` (`builtin_agents.py:240-299`; id = `installed_agent_id(owner, name)`, so a reinstall updates *in place*), `uploaded_agent_for()` (`bundles.py:324-377`; id = `uploaded_agent_id(owner, name, digest, attempt)`, so it is content-addressed), `validate_agent_bundle()`, `bundle_content_digest()` (`bundles.py:242-278`), `edit_agent_bundle()` (`agent_config.py:152-250`).
- Server agents: packaged built-ins (filterable by `OMNIGENT_SEEDED_AGENTS`, `omnigent/server/seeded_agents.py:18-49`) and `OMNIGENT_BUILTIN_AGENT_DIRS` (never filtered, operator-authored so `${VAR}` expands server-side, `app.py:1135-1205`).
- CLI: `omnigent agent add <dir|yaml|tgz|owner/repo[/path][@agent]>`, `agent list`, `agent remove` (`cli.py:12592-12760`).
- Web: `web/src/lib/agentsApi.ts` (`installAgentBundle`, `getAgentConfig`, `patchAgentConfig`), `web/src/hooks/useCustomAgents.ts`, `web/src/lib/agentBundle.ts:45` (`buildAgentBundle`), `web/src/pages/settings/SettingsCustomAgentsSection.tsx`, `CustomAgentConfigForm.tsx`. Behind default-on flag `custom_agents_settings_ui` (`omnigent/server/feature_flags.py:36`) and `/v1/info.agent_install`, `agent_detail` and `agent_config_edit` (`app.py:3677-3679`).

**Binding and revision semantics:**
- `conversations.agent_id` points at a row. The row's `bundle_location` is the *current* revision (`omnigent/db/db_models.py:170-215`). Each turn carries `agent_revision`, and the runner rebuilds when it changes (`runner/app.py:8410-8449`). Native TUIs keep their launch config until relaunch (`designs/REUSABLE_USER_AGENTS.md:419-439`).
- **Drift vectors on a run-owned step's row** (all owner-level): `PATCH /v1/agents/{id}` (`builtin_agents.py:386-441`); `POST /v1/agents` with the same name, which only matters for install-keyed rows (`builtin_agents.py:240-299`); `PUT /v1/sessions/{id}/agent` (`omnigent/server/routes/sessions/routes_agent.py:289-345`); session MCP-server edits (`omnigent/server/routes/session_mcp_servers.py`; F40); and `DELETE /v1/agents/{id}?force` (sessions keep running from the runner cache until reload, decision 11).
- **Row pollution:** child bundle uploads create a new row per session (`orchestration.py:12694-12735`). Top-level uploads dedupe by content (`orchestration.py:12694-12709`). Both appear in "my agents" (kind 2 originals, `REUSABLE_USER_AGENTS.md:§6.7`).

---

## 8. Recommendation: what a Coral Agent Profile is

### 8.1 Options evaluated

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| (a) Omnigent agent row (server or user agent) + Coral metadata in the bundle (`params.coral`) + Coral pin table | Reuses install, list, PATCH, GitHub install, Settings UI, validation, picker, artifact store. One "agent" concept for users. `params` round-trips through PATCH | Rows are mutable (decision 6) → needs pinning + drift guard. User-agent names can repeat (decision 13) | **Recommended** |
| (b) Bundle dirs in the repo under `.coral/profiles/` | Versioned with workflows in git (Draft 4 §3 "Sharing: Git repositories"). Portable | The server has no repo filesystem (workspaces live on hosts; `omnigent/server/schemas.py:1739-1752`, "the server has no filesystem"). Would need a host-read seam. Not visible in existing agent UIs | **Import source in v1.1**, not the store |
| (c) New `coral_profiles` table holding YAML | Full control | Duplicates the agent store, validation, editor, MCP editing and UI. Diverges from upstream | Rejected as the *authoring* store. A thin Coral *pin* table is still needed |

### 8.2 Decision

**A Coral Agent Profile is an Omnigent agent whose bundle carries a `params.coral` block. Coral never runs a profile directly.** It pins the profile to an immutable `coral_profile_revisions` row (content digest + Coral-owned copy of the bytes) and generates per-step agents from that revision (§9).

`params.coral` schema (v1, validated by Coral on save and on pin):
```yaml
params:
  coral:
    profile_version: 1
    canvas_description: "Reads a PR diff and reports findings"   # fallback: top-level description
    role_hint: step            # step | orchestrator | verifier  (validator: orchestrator profiles must omit os_env)
    default_rules:             # plain-language, translated like workflow rules (deep dive §10.7)
      - text: "Never push or force-push"
        kind: required
      - text: "Prefer small diffs"
        kind: guidance
    expects:                   # capability expectations, checked against S22 fields (V9)
      tool_call_gating: [all_tools, hook_catch_all]
      steering_reliability: [mid_turn, next_turn]
    credential: { provider: anthropic-key }   # optional default provider name; never a literal key
```
Default rules that are already translated live in `guardrails.policies` (registered handlers only), as F39 recommends. `default_rules` keeps the plain-language source so the canvas can show badges and re-translate.

### 8.3 Data model (New, Coral DB environment; deep dive §7.1 conventions: `workspace_id` leading PK, `Uuid16`, no FKs, `CompressedText` for blobs)

**`coral_profile_revisions`** (immutable)

| Column | Type | Notes |
|---|---|---|
| `workspace_id`, `id` | BigInteger, Uuid16 | PK |
| `user_id`, `account_generation` | String(128) nullable, Integer | Owner (null for Coral built-ins) |
| `profile_key` | String(256) | Logical reference used in workflow YAML, e.g. `reviewer`, `agent:<agent_id>`, `repo:.coral/profiles/reviewer` |
| `source_kind` | SmallInteger enum | `server_agent`, `user_agent`, `repo_bundle`, `coral_builtin` |
| `source_ref` | String(512) | `"<agent_id>@<bundle_location>"` or `"<repo>@<commit>:<path>"` |
| `content_digest` | String(64) | `bundle_content_digest()` of the profile bundle |
| `bundle_location` | String(512) | Coral-owned artifact key `coral/profiles/<digest>.tar.gz` (copy, survives agent deletion) |
| `harness`, `model` | String(64), String(256) nullable | From `executor.config.harness` and `executor.model` |
| `credential_ref` | String(256) nullable | Provider name from `params.coral.credential` or `executor.auth.name` |
| `metadata` | CompressedText | Normalized `params.coral` + description |
| `created_at` | Integer | — |

Unique `(workspace_id, user_id, content_digest)`. Index `(workspace_id, user_id, profile_key, created_at, id)`.

**`coral_step_agents`** (generated per-step agent rows; one per resolution)

| Column | Notes |
|---|---|
| `workspace_id`, `id` | PK |
| `version_id`, `node_id`, `roster_index` | Workflow version and step slot template |
| `profile_revision_id` | → `coral_profile_revisions.id` (plain column) |
| `resolution_hash` | sha256 of (generated bundle digest, harness, model, credential provider + kind, generator version) |
| `agent_id`, `agent_bundle_location` | The Omnigent row from `uploaded_agent_for()`; the location is the **pinned revision** |
| `harness`, `model`, `credential_ref`, `credential_kind` | Resolved values (for V9, V10 and audit) |
| `created_at` | — |

Unique `(workspace_id, version_id, node_id, roster_index, resolution_hash)`.

**`coral_agent_slots`** (deep dive §7.2) gains `step_agent_id`, `agent_revision` (`bundle_location` at session create), `harness` and `credential_kind`.

### 8.4 Lifecycle

1. **Create or import** (Reuse): Settings > Custom agents, `omnigent agent add`, or the Coral Profiles page. The Coral page writes `params.coral` and installs through `POST /v1/agents`, or for edits through PATCH. Note that `AgentConfigPatch` has `extra="forbid"` and cannot edit `params` (`schemas.py:200-235`), so Coral's page re-installs the whole bundle. Coral built-ins (default orchestrator, implementer, reviewer, researcher, verifier) are seeded as server agents through a Coral startup hook (S32) calling the same path as `_ensure_extra_builtin_agents` (`app.py:1145-1205`).
2. **Lint** (Coral, at save): `validate_agent_bundle(enforce_handler_allowlist=True)`, plus these rules. The harness must be in the Coral-supported set for this release. No `executor.auth.type: api_key` with a literal value (precedent: `validate_inference_credentials`, `inference_config.py:53-90`). No `executor.config.smart_routing_harness`. Orchestrator role → no `os_env`, and `tool_groups.browser: false`. `params.coral` validates. `expects` is satisfiable by the harness's S22 fields.
3. **Reference** from workflow YAML: `roster: [{profile: reviewer, count: 1, model: <optional>}]`. Resolution order: repo profile (v1.1), then the caller's user agent by name (error if several share it; ask for the id), then a server agent by name.
4. **Pin** at workflow-version creation, or at run start for unversioned runs. Snapshot the bytes into `coral_profile_revisions`. The workflow version's `content_hash` includes each revision's `content_digest` (deep dive §6.8).
5. **Use:** generate the per-step agents (§9) from the revision bytes, *not* from the live agent row.
6. **Update:** edits create a new agent `bundle_location`. The Coral UI shows "profile changed since version N" and offers a re-pin into a new workflow version. Running runs are unaffected.
7. **Retire:** deleting the agent row does not affect pinned revisions. Revisions unreferenced by any non-archived version are garbage-collected after a retention period (Proposed: 30 days).

---

## 9. Per-step bundle generation and session creation

### 9.1 Why generated per-step agents

Per-step settings that cannot be changed after session create (deep dive §8.5): sandbox and egress, MCP allowlists, sub-agent grants, tool groups and engine-tool opt-in. Session policies *can* be attached later, but editors can disable them (`omnigent/server/routes/session_policies.py:308-437`). Spec-level `guardrails` in an engine-owned bundle cannot be changed through any session-policy route.

### 9.2 Generator (New: `coral/omni/bundles.py`)

**Inputs:** profile revision bytes; the compiled step (role, Required-rule translations, read or write intent, website rules, roster mode, fresh-context option, input scoping); the run credential choice; host facts.

Algorithm:
1. `extract_safe` the revision bytes. Load `config.yaml` as a dict with `_ConfigYamlLoader` (`parser.py:107-120`), preserving unknown keys.
2. **name:** `coral__<wfslug>__<node_id>__m<roster_index>`, ≤256 characters, `[A-Za-z0-9_-]`. **description:** the profile's.
3. **executor:** keep `type: omnigent`. `config.harness` comes from the profile and never from the step. Remove `config.smart_routing_harness`. Set `executor.model` to the roster model, or the profile model. Set the approval stance per mode:

| Mode | Setting | Why |
|---|---|---|
| claude-sdk | `config.permission_mode: bypassPermissions` if the S21 probe shows `can_use_tool` still runs, else `auto` | `can_use_tool` gate (`claude_sdk_executor.py:3132-3153`); no human in the loop |
| claude-native | `config.permission_mode: bypassPermissions` (or `auto` per managed settings) | Translated to `--permission-mode` (`helpers.py:10710-10715`); hooks are the gate (S14) |
| codex-native | Explicit `config.yolo` per step (H-S47); never rely on the default | Default is full bypass (`helpers.py:10647-10658`) |
| codex | n/a (`approvalPolicy: never` is hard-coded) | `codex_executor.py:3829` |

4. **executor.auth:** omit it if an operator inference binding exists for the harness (`inference_config.py:157-182`). Otherwise write `{type: provider, name: <run credential choice or params.coral.credential>}`. Never write `api_key`.
5. **os_env:** start from the profile's and intersect with the step rules. A read-only step gets `sandbox.write_paths: []`. Website rules become `sandbox.egress_rules`, and for `egress_scope=whole_agent` (claude-native) the provider host(s) are appended. Codex signer-backed rejects `egress_rules` (`codex_executor.py:4890-4894`), so the validator rejects that combination. The orchestrator role gets no `os_env`.
6. **guardrails.policies** (order matters; DENY short-circuits): the profile's guardrails, then translated step and group Required rules (reserved name prefix `coral.`), then `coral.policies.step_roster`, then `coral.policies.engine_tool_guard`, then input-scoping DENY on `sys_session_list`, `sys_session_get_history` and `sys_session_get_info` when the step asks for isolation. Handlers must be registered.
7. **tools:** `agents: []`, `spawn: false`, `builtins` filtered: drop `web_search`/`web_fetch` unless a website rule allows them. The web bundle builder adds both by default (`agentBundle.ts:61-64`).
8. **tool_groups:** `browser: false` (an embedded browser is an unaudited network path; UNVERIFIED whether `egress_rules` covers it), `scheduled_tasks: false`, `policies: false`, `agent_discovery: false`. `comments` follows a product decision.
9. `timers: false`, `async: false` (deterministic tool surface; Proposed), `agent_session_sharing: none`.
10. **skills:** `none` for hermetic steps. Otherwise the profile's filter.
11. **engine_tools** (S7, New top-level key): `[submit_handoff, message_agent]` for steps; `[choose_arrow, assign_agents, message_agent, ask_user]` for the orchestrator; `[submit_handoff]` with `kind: verdict` for verifiers.
12. **instructions:** the profile's, unchanged. The framework instruction is appended at runtime by `prompt.py` when `engine_tools` is present (S12), and delivered at launch for native modes. **The brief is never baked in** (deep dive §8.3.3).
13. `params.coral.generated: {profile_revision, workflow_version, node_id, roster_index, generator_version}`. These are version- and node-level only, so content stays stable across runs of the same version.
14. Tar deterministically (`_tar_gz_dir` precedent, `app.py:1185`). Then `validate_agent_bundle(..., enforce_handler_allowlist=True)`, `bundle_content_digest()`, and `uploaded_agent_for(agent_store, artifact_store, owner=run.user_id, spec, bundle_bytes)` (request-free, content-addressed). Upsert `coral_step_agents`.

Example output (abridged):
```yaml
spec_version: 1
name: coral__pr_review__review__m1
description: "Reads a PR diff and reports findings"
executor:
  type: omnigent
  model: claude-sonnet-4-6
  auth: { type: provider, name: anthropic-key }
  config: { harness: claude-sdk, permission_mode: bypassPermissions }
os_env:
  type: caller_process
  cwd: .
  sandbox: { type: auto, write_paths: [], egress_rules: ["GET api.github.com/repos/acme/app/**"] }
guardrails:
  policies:
    coral.rule.no_push: { type: function, function: { path: coral.policies.rules:cel_rule, arguments: {...} } }
    coral.step_roster:  { type: function, function: { path: coral.policies.roster:step_roster, arguments: {max_count: 0} } }
    coral.input_scope:  { type: function, function: { path: coral.policies.scope:deny_session_reads } }
tools: { agents: [], builtins: [] }
spawn: false
timers: false
async: false
tool_groups: { browser: false, scheduled_tasks: false, policies: false, agent_discovery: false }
skills: none
engine_tools: [submit_handoff, message_agent]
params:
  coral: { generated: { profile_revision: "…", workflow_version: "…", node_id: review, roster_index: 1, generator_version: 1 } }
prompt: "<profile instructions>"
```

### 9.3 Creating a step session (sequence; the session facade lives in `coral/omni/sessions.py`)

1. **Preflight (V10).** Check the host's `configured_harnesses[harness] is True` (values: `true`, `false`, `"binary-missing"`, `"needs-auth"`, `"version-too-low"`; precedent `examples/polly/config.yaml:68-90`). Check the credential kind is acceptable from `harness_accounts` (kinds `none`, `chatgpt`, `api_key`, `subscription`, `providers`, `unknown`; `omnigent/harness_accounts.py:10`; host hello `omnigent/host/frames.py:87, 324`; refresh through `request_harness_accounts`, `omnigent/server/host_registry.py:966-980`). Check minimum CLI versions for Enforced labels (S14, S15).
2. **Ensure the per-step agent** (§9.2). Reuse the row if the `resolution_hash` exists.
3. **Create the conversation** request-free (S3; precedent `fire.py` per the deep dive §8.1). Pass `agent_id`; `parent_session_id` = the orchestrator (default topology, deep dive §8.2) or top-level for steps that need a different host or sandbox; labels `coral.run_id`, `coral.step_id`, `coral.slot_id` and `coral.role` (the `coral.` prefix is reserved by S26); `model_override` only if the roster pins one (validated against binding allowlists, `inference_config.py:204-250`). **Never set** `harness_override`, `subagent_routing_override` or `smart_routing_message` (`schemas.py:1722-1727`). Smart Routing would change model or harness per turn. The routing-class knob for run-owned sessions is UNVERIFIED and must be pinned to plain.
4. **Attach any session-level policies** before the first input (deep dive §8.1).
5. **Record** `slot.session_id`, `slot.agent_revision = agent.bundle_location`, `slot.harness` and `slot.credential_kind`.
6. **Send the brief** as the first user message (S4).
7. **Drift check** on every turn signal: compare the row's `bundle_location` with `slot.agent_revision`. If they differ, pause the step and log `profile_drift`. H-S43 makes this unreachable except through an operator.

### 9.4 Harness, model and auth selection

| Dimension | Source of truth | Override allowed | Validator |
|---|---|---|---|
| Harness | Profile revision (`executor.config.harness`) | **No.** A different harness means a different profile (capabilities change) | V9 per step |
| Model | Roster `model` > profile `executor.model` > operator binding `default_model` > provider family default | Roster only; must be in the binding's `model_allowlist` (`ModelNotAllowedError`, `inference_config.py:36-50`) | V10 |
| Credential | Operator binding (if any) > run credential choice (user picks at run start from the host's providers) > `params.coral.credential` | Per run, never per step mid-run ("never switch accounts", Draft 4 §7.8) | S13 rules (§10) |

---

## 10. Auth and vendor terms as engineering requirements (S13 expanded)

| ID | Requirement | Implementation | Evidence |
|---|---|---|---|
| R-AUTH-1 | Run-owned `claude-sdk` sessions **must not** use Claude subscription OAuth by default | (a) The generator always writes a non-subscription `provider` auth. (b) **S13 runner guard:** new spawn env `HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL=1`, set by `_build_claude_sdk_spawn_env` (`workflow.py:1365-1400`) when the spec opts in (S7's `engine_tools` presence, or a dedicated spec flag). The executor refuses to connect unless `api_key_helper`, gateway or provider routing is set, emitting `ExecutorError(code="coral_subscription_auth_refused", retryable=False)` before `client.connect()` (`claude_sdk_executor.py:2066-2118`). (c) The server preflight rejects a resolved provider of kind `subscription` with `cli == "claude"` | `claude_sdk_executor.py:2091-2118`; `workflow.py:1238-1247`; deep dive §16.1 [W-1, W-2] |
| R-AUTH-2 | Subscription users run Claude steps through `claude-native` (unmodified binary, own login) | V9 maps the "subscription" credential choice onto claude-native profiles; label chips "Claude" (not "Claude Code", W-1) | Draft 4 §17 |
| R-AUTH-3 | No literal secrets in profiles, generated bundles or workflow YAML | Lint rejects `executor.auth.api_key` and literal MCP `headers`/`env` credential values in Coral-generated bundles. Uses provider references and `api_key_ref` (`provider_config.py:438-450`) | `cli.py:6614-6644` (CLI bakes secrets); `bundles.py:110-117` |
| R-AUTH-4 | Never switch accounts within a run | Record `credential_ref`, `credential_kind`, the host `harness_accounts` email/org (when present) and `inference_revision()` (`inference_config.py:253-263`) on `coral_runs`. Each step start compares them; a mismatch pauses the run | Draft 4 §7.8 |
| R-AUTH-5 | Defer to operator inference bindings | Omit `executor.auth` when `binding_for_harness()` is set, otherwise launches raise | `inference_config.py:157-182` |
| R-AUTH-6 | Codex: hosted or commercial Coral uses API-key providers only, for **both** `codex` and `codex-native` (both are app-server-backed) | V10 refuses `chatgpt` account kinds when the deployment is marked hosted (new server config, Proposed). Local OSS use keeps ChatGPT login, pending OpenAI's answer | Deep dive §16.2 [W-14, W-76]; app server `omnigent/harnesses/codex_native/app_server.py` |
| R-AUTH-7 | Per-user credentials only | Run-owned sessions execute on the run owner's host or managed sandbox, with that user's providers. No server-global key for multi-user deployments (global `auth:` is process-wide, `workflow.py:1383-1385`) | Deep dive §16.1 [W-2] |
| R-AUTH-8 | Key exposure: `apiKeyHelper` is `printf %s '<key>'` in the harness env | Prefer providers with `api_key_ref` (secret resolver) over inline. Document that sandboxed `sys_os_*` helpers get a stripped env (`env_passthrough`, `datamodel.py:745-752`) | `workflow.py:1393-1395` |
| R-AUTH-9 | Record vendor clarifications | Gate phase 2 on Anthropic's answer, and Codex-mode release on OpenAI's (deep dive §16) | — |

---

## 11. Seam list for this area (upstream-file changes)

Existing IDs are kept and refined. New ones are numbered H-S41 onward. Sizes: XS < 50 LOC, S < 200, M < 600.

| ID | Seam | Location | Change | Size | Phase | Upstream? | Depends on |
|---|---|---|---|---|---|---|---|
| **S13** | Run-owned `claude-sdk` credential guard (R-AUTH-1) | `omnigent/runtime/workflow.py:1365-1400`; `omnigent/inner/claude_sdk_harness.py:110-135, 303`; `omnigent/inner/claude_sdk_executor.py:2066-2118` | Modify | S | 2 | No (Coral policy) | S7 (opt-in flag) |
| **S17** | `claude-sdk` sub-agent attribution | `claude_sdk_executor.py:1019-1031, 3480-3584` | Modify | S | Later (no vendor sub-agents exposed; D8) | Yes | — |
| **S18** | Headless codex: route by `threadId`, translate collab items | `codex_executor.py:3989-4000, 2774-2834` | Modify | M | 7b | Yes | — |
| **S19** | Headless codex compaction (`thread/compact/start`) | `codex_executor.py` (new request); `omnigent/runner/app.py:7893-7912` | Extend | S | 7b | Yes | — |
| **S20** | Headless codex tool gating: catch-all PreToolUse policy hook in the private CODEX_HOME `hooks.json` | `codex_executor.py:1633-1680` (router-hook payload builder to generalize), `1740-1800` (writer), `3304-3318` (trust) | Extend | M | 7b | Yes | H-S57 |
| **S21** | `claude-sdk` PreToolUse policy hook, *if* the `can_use_tool` probe fails under the run-owned permission mode | `claude_sdk_executor.py:3132-3155` | Extend | S | 4 | Yes | S23 probe |
| **S22** | Capability fields (§5.1) | `omnigent/harness_capabilities.py:24-184`; `omnigent/harness_plugins.py:358-386, 591-614`; `tests/test_harness_capabilities.py:123-163` | Extend | S | 2 (fields) / 4 (probe-backed values) | Yes | — |
| **S23** | Bench probes (§5.3) | `tests/harness_bench/probes/`, `transport.py:11-110`, `driver.py:138-187`, `full_server_driver.py`, `native_tui_driver.py`, `manifest.py:55-76` | Extend (test-only) | M | 2-4 | Yes | S22 |
| **S24** | Usage-limit signal: claude-sdk `RateLimitEvent`; codex `account/rateLimits/updated` + `usageLimitExceeded`; native categories → structured status; `ExecutorError` code `usage_limited` + reset time (new optional field `retry_after_s` or `resets_at`) | `claude_sdk_executor.py:3407-3727` (add a branch); `codex_executor.py:4569-4576`; `omnigent/inner/executor.py:331-375`; `omnigent/harnesses/claude_native/forwarder.py:3915-3945`; `omnigent/harnesses/codex_native/forwarder.py:1461-1490` | Extend | S+S | 4 (claude) / 7 (codex) | Yes | — |
| **H-S41** | `GET /v1/harnesses` adds `capabilities_by_spelling` (natives included) | `omnigent/server/routes/harnesses.py:27-30`; `omnigent/harness_plugins.py:1255-1328` | Extend | XS | 4-5 | Yes | S22 |
| **H-S42** | AgentSpec `engine_tools` opt-in (refines S7: name, parse, validate, gate ToolManager registration and prompt framework instruction) | `omnigent/spec/types.py:1605-1656`; `parser.py:300-320, 339-367`; `omnigent/spec/validator.py`; `omnigent/tools/manager.py:159-193`; `omnigent/runtime/prompt.py:62-87` | Extend | S | 2 | Partly | — |
| **H-S43** | Engine-owned agent rows: reserved name prefix `coral__`. (i) Exclude from `list_user_agents` and the picker. (ii) Refuse PATCH, reinstall, `PUT /sessions/{id}/agent`, session MCP edits and non-forced DELETE for non-engine callers. (iii) Allow creation only through a trusted in-process path | `omnigent/stores/agent_store/sqlalchemy_store.py:532-545`; `omnigent/server/routes/builtin_agents.py:240-299, 332-340, 538-626`; `omnigent/server/routes/sessions/routes_agent.py:289-345`; `omnigent/server/routes/session_mcp_servers.py`; `omnigent/server/bundles.py:324-377` (upload path must reject the prefix from HTTP); web `web/src/hooks/useAvailableAgents.ts`, `useCustomAgents.ts` | Modify | S | 2 | Maybe (generic "reserved prefix" hook) | — |
| **H-S44** | Request-free `create_conversation_for_agent(agent_id, parent, labels, model_override, host, workspace)` that also derives `terminal_launch_args` from the spec (`helpers.py:10631`) | Part of S3; `omnigent/server/routes/_sessions/orchestration.py` (JSON create path), `helpers.py:10631-10760` | Extend | S | 2 | Yes | S3 |
| **H-S45** | Per-session codex native-tool switches (`disable_native_tools`, `enable_web_search`) threaded from spec (new spec field, *not* `executor.config`) instead of server-process env; add an `apply_patch` disable if Codex supports one (UNVERIFIED) | `omnigent/runtime/workflow.py:1508-1566`; `omnigent/inner/codex_harness.py:46-52, 410-416`; `codex_executor.py:3846-3847, 5014-5018` | Extend | S | 7b | Yes | — |
| **H-S46** | Headless codex read-only stance: do not upgrade `read-only` → `workspace-write` when the spec marks the session read-only (confirm why the upgrade exists; UNVERIFIED rationale) | `codex_executor.py:5245-5247, 2729-2739` | Modify | XS | 7b | Yes | — |
| **H-S47** | codex-native unattended stance: per-session explicit `yolo` for run-owned sessions, plus *policy-resolved* approvals so `yolo: false` does not stall (answer JSON-RPC approval requests from TOOL_CALL policy, deny on no verdict) | `omnigent/server/routes/_sessions/helpers.py:10631-10760`; codex-native approval/elicitation path (`orchestration.py:2654` `_hold_native_ask_gate_impl` per deep dive F6; exact handler UNVERIFIED) | Modify | M | 7a | Maybe | S15 |
| **H-S48** | Contract guard that `claude-sdk` exposes no vendor workspace tools: remove or clarify the vestigial `enable_native_tools` → `_os_env` | `claude_sdk_executor.py:985-1000, 1560-1636, 1898, 1954, 2571-2585` | Modify (tiny) or test-only | XS | 2 | Yes | — |
| **H-S49** | Egress scope awareness: the claude-native terminal inherits `os_env.sandbox`, so Coral's translator auto-adds provider hosts. Optionally upstream a spec-level `egress_rules` include for "model provider" | `omnigent/runner/native/orchestration.py:9880-9890`; `omnigent/inner/egress/rules.py` | Coral-only (translator) or Extend | XS | 4 | Maybe | — |
| **H-S50** | `tool_groups.session_reads: false` to unregister `sys_session_list`, `get_history` and `get_info` (input scoping; EGM). Alternative with no seam: a DENY policy | `omnigent/spec/types.py:877-900`; `omnigent/tools/manager.py:402-470`; `parser.py:317` | Extend | XS | 6 | Yes | — |
| **H-S51** | Native launch delivery of the framework instruction (refines S12): claude-native `--append-system-prompt` composition and codex-native startup instructions must include the framework text when `engine_tools` is set | `omnigent/runner/native/orchestration.py:7748-7773`; `claude_native_executor.py:373-394` | Extend | S | 4 | Partly | H-S42 |
| **H-S52** | Profile metadata in agent summaries (optional): `_to_agent_object` exposes `params.coral` (redacted) so upstream pickers can show Coral badges. Coral can instead read bundles itself | `omnigent/server/routes/builtin_agents.py:70-153` | Extend | XS | 5 | No | — |
| **H-S57** | Headless codex hook-trust failure must fail closed for run-owned sessions (today it logs and continues) | `codex_executor.py:3304-3318` | Modify | XS | 7b | Yes | S20 |

**No seam needed (Reuse as is):** `install_user_agent`, `uploaded_agent_for`, `validate_agent_bundle`, `bundle_content_digest`, `edit_agent_bundle`, the `agent_revision` propagation, `harness_capabilities()`, `harness_accounts` and `configured_harnesses` host reporting, the `policy_modules` registry, the `skills: none` hermetic mode, and the `tool_groups` flags.

---

## 12. Test infrastructure to extend

| Layer | What to add | Where (nearest scenario) |
|---|---|---|
| Capability guards (unit) | New-field defaults; guards for `steering`, `live_queue`, `compaction` and `turn_complete_semantics`; catalog by-spelling | `tests/test_harness_capabilities.py` (extend `123-163`, `193-260`) |
| Bench probes (unit, offline) | One file per new probe with a fake `_Driver` returning a crafted `TurnResult` | `tests/harness_bench/test_policy_matrix.py`, `test_cost_tracking.py` patterns |
| Bench probes (live, nightly) | `--require-complete` slices per mode with pinned CLI versions | `tests/harness_bench/README.md:48-80` |
| Spec parsing | `engine_tools` and `tool_groups.session_reads` parse and validate; `params.coral` round-trip | `tests/spec/test_parser.py`, `test_validator.py`, `test_types.py` |
| Agent store / routes | Reserved-prefix guard (H-S43): list exclusion, PATCH/PUT/DELETE refusal, trusted creation | `tests/server/routes/test_agent_install.py`, `tests/server/test_agent_config.py`, `tests/stores/test_agent_store.py`, `tests/server/test_bundles.py` |
| Generator (Coral unit) | Deterministic tar + digest stability; per-mode stance table; egress auto-add for claude-native; binding omission; no literal secrets; orchestrator has no `os_env` | `tests/coral/omni/test_bundles.py` (New); reuse `tests/_helpers/session.py` `bundle_files` |
| Auth (unit) | S13 guard: executor refuses without an API credential when the flag is set; spawn-env builder sets the flag | `tests/inner/test_claude_sdk_executor.py`, `test_claude_sdk_harness.py`; `tests/spec/test_single_file_executor_auth_env.py` |
| Provider resolution | Coral credential resolution vs bindings without the dev's config | `tests/_helpers/providers.py` `isolate_provider_resolution` (catalog row) |
| Codex seams | H-S46 read-only stance; H-S57 trust fail-closed; H-S45 per-session switches | `tests/inner/test_codex_executor.py`, `test_codex_hooks_generation.py`, `test_codex_harness.py` |
| Native seams | S14 fail-closed output; H-S47 stance; H-S51 launch instruction | `tests/harnesses/claude_native/`, `tests/harnesses/codex_native/` (directory convention, `tests/README.md:7-16`) |
| Integration (mock provider) | A Coral step session created from a generated agent completes a turn and calls `submit_handoff` through each mode's transport | `tests/server/integration/` mock-provider lane; `tests/_helpers/server_runner.py` `server_runner` |

Per the repo rules (CLAUDE.md "Test changes"): keep input matrices at the unit layer, use E2E only for distinct process or transport boundaries, and no browser runs.

---

## 13. Modes in v1 vs later

| Mode | Release | Role | Gating seams and criteria | Justification |
|---|---|---|---|---|
| `claude-sdk` | **v1 (phase 2)** | Orchestrator (only allowed mode) + default step agent | S7/H-S42, S8-S12, S13, H-S43, H-S44, H-S48; probes for `end_of_turn_detection`, `tool_call_gating` (connector MCP under the chosen permission mode), `fresh_context` | Pre-call gating on every workspace tool; fail-closed policy path; "no heavy work" by construction; best evidence (`sys_os_*` args + results server-side). Weaknesses (next-turn steering, interrupt drops the session, no usage-limit signal) are operational, not guarantee-breaking. Terms: requires API-key or provider auth (R-AUTH-1) |
| `claude-native` | **v1 (phase 4), steps only** | Subscription users' step agents; separate sessions only | S14 (fail-closed + `onFailure: block`, minimum CLI version), hooks-installed check (`ap_server_url`), H-S51, turn-end via the Stop hook, S24 native category, H-S49 egress | The only terms-clean path for Claude subscriptions (W-2). Until S14, Required rules on claude-native steps must be invalid or downgraded to Guidance by the validator. Not for the orchestrator (hooks are the only gate) |
| `codex-native` | **v1.1 (phase 7a)** | Codex steps (e.g. the cross-vendor reviewer in the PR showcase) | S2, S12/H-S51, S14, S15, S16, H-S47; OpenAI terms (R-AUTH-6) | Better than headless today: hook catch-all, `turn/steer`, per-child-thread transcripts. Blockers: fail-to-ASK, hook trust and version gating, default full bypass |
| `codex` (headless) | **Later (phase 7b)** | Codex steps where TUI is undesirable | S18, S19, S20, H-S45, H-S46, H-S57; probe `tool_call_gating=all_tools` after S20 | Today Codex's own shell, `apply_patch` and web search are ungated; the read-only sandbox is silently upgraded; dynamic tools ride `experimentalApi`. Weakest enforcement of the four |

The PR-review showcase in v1 should use two Claude reviewers on different model families or tiers. Deep dive §20.1 Q2 recommends the same.

---

## 14. Dependency-ordered work packages (for roadmap decomposition)

| WP | Scope | Depends on | Est. |
|---|---|---|---|
| WP-H1 | S22 fields + values for four modes + guard tests; H-S41 | — | S |
| WP-H2 | S23 probe framework additions (driver methods, `TurnResult` fields) + offline unit tests | WP-H1 | M |
| WP-H3 | H-S42 `engine_tools` spec field (parse, validate, ToolManager gate, prompt framework instruction) | — | S |
| WP-H4 | `params.coral` schema + Coral profile lint (`coral/profiles/lint.py`) | — | S |
| WP-H5 | `coral_profile_revisions` + `coral_step_agents` stores (Coral Alembic env) + pin service | Coral DB env (other agent) | M |
| WP-H6 | Per-step bundle generator (§9.2) + deterministic tar + `uploaded_agent_for` binding | WP-H3, WP-H4, WP-H5 | M |
| WP-H7 | H-S43 reserved-prefix guard (server + web picker filter) | — | S |
| WP-H8 | S13 credential guard + Coral credential resolution (bindings, run choice, preflight from `harness_accounts`) | WP-H3 | S |
| WP-H9 | Step session creation facade (H-S44 + S3) + drift check | WP-H6, WP-H7, S3/S4 (other agent) | M |
| WP-H10 | Live bench slice for `claude-sdk` (end-of-turn, connector gating, fresh context) → S21 decision | WP-H2 | S |
| WP-H11 | claude-native enablement: S14, H-S49, H-S51, S24-native | WP-H1, WP-H2 | M |
| WP-H12 | Coral Profiles desk page (list over `/v1/agents` + `scope=user` + Coral metadata; edit via reinstall; badges from H-S41) | WP-H4, WP-H7, H-S41 | M |
| WP-H13 | codex-native enablement: S2, S15, S16, H-S47 | WP-H11 | M |
| WP-H14 | Headless codex: S18, S19, S20, H-S45, H-S46, H-S57 | WP-H2 | L |
| WP-H15 | S24 claude-sdk `RateLimitEvent` + codex rate limits → engine pause | WP-H1 | S |

---

## 15. Open questions and UNVERIFIED items

1. Does the Claude CLI invoke `can_use_tool` for connector MCP tools under `auto` and under `bypassPermissions`? (Decides S21 and the run-owned permission mode.) UNVERIFIED; probe.
2. Are `Agent`/`Task` truly unavailable in `claude-sdk` given `tools=["Skill","ToolSearch",…]`? UNVERIFIED at runtime (deep dive §20.2 Q8); probe.
3. Is the codex-native **app-server** process (which executes Codex tools) wrapped by Omnigent's OS sandbox, or only the TUI terminal? UNVERIFIED. Decides whether `egress_rules` and `write_paths` constrain codex-native tool execution.
4. Why does headless codex upgrade `read-only` to `workspace-write` when tools exist (`codex_executor.py:5245-5247`)? If dynamic tools need it, H-S46 must find another read-only mechanism.
5. Does `thread/tokenUsage/updated` carry a context window (`modelContextWindow`)? UNVERIFIED. Affects `usage_reporting` for both Codex modes.
6. Is `native_error_category` persisted where the engine can read it durably (status edge or item), or only in telemetry? UNVERIFIED.
7. Which knob pins a run-owned session to the "plain" Smart Routing class (no per-turn model or harness change)? UNVERIFIED. Look at `SessionRoutingClass` and `session_routing_class` (`runner/app.py:9030-9073`).
8. Do embedded `browser_*` tools bypass `egress_rules`? UNVERIFIED. The generator disables them by default.
9. Hermetic context for native modes (project `CLAUDE.md` / `AGENTS.md` loading) has no spec control. Is "fresh context" for native steps Requested-only?
10. Product: should Coral built-in profiles appear in the generic new-session picker (they are server agents)? `OMNIGENT_SEEDED_AGENTS` cannot filter extra-dir agents (`seeded_agents.py:10`).
11. Product and legal: hosted-deployment flag semantics for R-AUTH-6, and the vendor clarification letters (R-AUTH-9).
12. Requirements gap: `coral-requirements.md` is missing (D2). Profile UX requirements (fields, picker shape, sharing) are unspecified beyond UI doc §8.3.
