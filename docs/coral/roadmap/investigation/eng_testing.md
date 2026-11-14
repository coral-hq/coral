# Coral: testing infrastructure, CI, build/dev workflow, fork and upstream-merge operations, rebrand mechanics (non-visual)

Staff Engineer, Agent 3. Read-only audit of the Omnigent fork at `2a9cbe2c2` (0.22.0.dev0, committed 2026-11-08).
Inputs: `coral-design.md` (Draft 4), `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` (audit of Draft 3 at this commit), `coral_UI_DESIGN_LANGUAGE.md`.

Conventions:
- `path:line` refs were opened at HEAD. **UNVERIFIED** marks a claim I could not check in the repo.
- Churn means `git log --since=2026-10-09 --oneline -- <path> | wc -l`. That is a 30-day window ending at HEAD (2026-11-08).
- Change types are **Reuse** (as-is), **Extend**, **Modify** (edit an upstream file, so it is a seam), **New**, **Replace** and **Remove**.
- Deep-dive references are written DD§x. Design references are D§x.

---

## 0. Executive summary

1. **A deterministic, model-free agent path already exists, in four tiers.** The roadmap does not need to build a fake harness.
   - **(a)** In-process `ControllableMockClient`, patched into `omnigent.runtime.workflow._get_llm_client` (`tests/server/conftest.py:183-303, 426-441, 551-592`). It supports scripted text, tool calls, `tool_calls_fn` for arguments known only at runtime, and block/release gates.
   - **(b)** The process-level `tests/server/integration/mock_llm_server.py`. It speaks OpenAI Responses, Anthropic Messages and Chat Completions, keeps keyed queues (by model, by content `match`, by `required_tools`), and supports gates, delays, errors and mid-stream truncation (`mock_llm_server.py:1-62, 1115-1659`). It is driven with the `openai-agents` harness (`tests/e2e/conftest.py:343-545, 1123-1186`; `.claude/skills/polly-e2e-dev/polly_cuj.py:164-205`).
   - **(c)** The **resilience lab** scripts the *real* Claude Code and Codex TUIs against that mock by content marker. It can restart the server mid-turn (`tests/e2e/resilience/lab/driver.py:1-16`; `lab/lab.py:314`; `lab/model_server.py:1-30`). CI's E2E lane installs pinned `claude`, `codex` and `pi` CLIs (`.github/actions/e2e-run/action.yml:101-128`).
   - **(d)** Narrow fakes: the `runner_test_harness` harness module (`tests/_fixtures/runner_test_harness.py:1-15`), `FAKE_ACP_AGENT_SCRIPT` (`tests/_helpers/acp_agent.py:1-12`), and the Codex app-server fakes (`tests/harnesses/codex_native/session/_support.py:19, 112`).
   - **Gap:** there is no deterministic fake for **`claude-sdk`**. Its E2E needs a logged-in CLI (`tests/e2e/test_host_claude_sdk_e2e.py:1-45`), and whether claude-sdk honours a mock `ANTHROPIC_BASE_URL` is UNVERIFIED.

2. **The CI lanes cover Coral almost for free, with five sharp edges.**
   - **Free:** `tests/stores/coral/` and `tests/db/coral/` ride the Postgres 16, CockroachDB 23.2.28 and MySQL 8 lanes (`.github/workflows/ci.yml:231-375`; selectors at `:264, :315, :363`). `tests/coral/` is caught by the `misc` catch-all group (`.github/scripts/ci/python-matrix.json:73-77`). `web/src/workflows/**/*.test.ts(x)` is caught by the vitest glob (`web/vite.config.ts:255-262`).
   - **Edge 1:** pyrefly ignores `coral/`. The hook regex is `^(omnigent/...)` (`.pre-commit-config.yaml:27-32`) and the includes are `omnigent/**` (`pyrefly.toml:1-5`).
   - **Edge 2:** coverage measures only `omnigent` (`ci.yml:198`; `pyproject.toml:539`).
   - **Edge 3:** isort first-party is only `omnigent` (`pyproject.toml:625`).
   - **Edge 4:** per-test truncation wipes `coral_alembic_version` on the external-DB lanes (`tests/conftest.py:736`, S31).
   - **Edge 5:** Coral routes mounted through `extra_routers` will **not** appear in `openapi.json`, because the dump script builds the app without them (`scripts/dump_openapi.py:324-370`). Coral needs its own spec artifact and drift test.

3. **Hidden coupling with the feature map.** `tests/dev/test_verify_omnigent_feature_map.py` fails CI in three cases:
   - a new bench probe is not mapped in `feature-map/harness-acceptance.md` (`:110-127`), which affects S23;
   - a new `tests/e2e_ui/<area>/` or `tests/browser_ui/<area>/` directory is neither mapped nor listed (`:144-155`);
   - a new visible top-level CLI command is not listed (`:158-174`).

   `feature-map/README.md` had 25 commits in 30 days, so it is a conflict-prone seam. The deep dive does not list it.

4. **Merge from nightly tags' first parent, not from release tags.**
   - Release tags are not on `main`: `v0.19.0`, `v0.20.0` and `v0.21.0` are not ancestors of HEAD. `v0.21.0` carries 3 stamp commits and 1 backport that `main` already has (`c42c3c33e` ≡ backport `fe845f60f`).
   - Nightly tags are not ancestors either, but each is exactly one `nightly:` stamp commit on top of the **newest green main commit**. For example, `v0.22.0.dev20261108` = `1dd1a65d2`, whose parent `ee7a319f7` is on main (`.github/workflows/nightly-release.yml:1-24, 100-125`).
   - Merging `vX.Y.Z.devYYYYMMDD^1` therefore gives a CI-green, stamp-free upstream snapshot every day. This **refines** D§16 ("merge from tagged releases") and DD§17.

5. **The hot files for planned seams are hotter than the deep dive shows.** 30-day commits by file:
   - `_sessions/orchestration.py` (S1, S3, S6, S10): 77
   - `omnigent/harnesses/claude_native/bridge.py` (S14): 83
   - `openapi.json`: 69
   - `omnigent/server/app.py` (S1 registration, S32): 64
   - `omnigent/host/connect.py` (S40): 62
   - `omnigent/runner/native/orchestration.py` (S11, S12, S15): 56
   - `web/src/shell/Sidebar.tsx` (S34): 51
   - `_sessions/helpers.py` (S1, S3, S25, S26): 52

   Low-churn homes are available: `session_live_state.py` (3), `pending_elicitations.py` (1), `harness_capabilities.py` (0), `db/migrations/env.py` (0), `CODEOWNERS` (0), `pyrefly.toml` (0), `NOTICE` (0), `justfile` (3), `python-matrix.json` (3). Seams should put a one-line call in the hot file and the logic in a low-churn file or in `coral/`.

6. **Rebrand.** Deferring internal identifiers (DD§16.3 layer 2) is right, but it has **coexistence hazards** the docs do not mention:
   - `omni upgrade` and the update check look for distribution `omnigent` on PyPI (`omnigent/update_check.py:66, 1622, 1843`), so a Coral install would be offered upstream Omnigent.
   - Coral and upstream share `~/.omnigent`: `chat.db`, host identity and auth tokens (`omnigent/cli.py:584-600`; 24 files hardcode `".omnigent"`).
   - Omnigent refuses a database from a newer build (`omnigent/db/utils.py:745-765`), so running a newer upstream against the shared DB locks Coral out.
   - Electron accepts the CLI only if `--version` matches `/\bomni/i` and the binary is named `omnigent` or `omni` (`web/electron/src/omnigent_cli.js:277, 614`).

7. **The fork inherits about 118 workflow files** (≈113 workflows plus their scripts and tests):
   - 36 are gated on `github.repository == 'omnigent-ai/omnigent'` and are inert in the fork.
   - About 14 non-gated ones use secrets or vars.
   - 40 `uses:` lines reference upstream composite actions by pinned SHA (`omnigent-ai/omnigent/.github/actions/setup-uv@c144e4b…` ×14, `setup-harness-cli@c76912d…` ×26).
   - Recommendation: disable unwanted workflows in GitHub settings rather than deleting the files, because deleting them creates modify/delete conflicts on every merge.

---

## 1. Discrepancies: confirmations, refinements and new ones

| ID | Status from this lane | Evidence and refinement |
|---|---|---|
| D1 | **Confirmed** for the items in my area. | `PersistentTaskScheduler` is typed on `ScheduledTask`/`ScheduledTaskRun` (`omnigent/server/scheduled/dispatch_scheduler.py:19, 117`), and its flag `automations_v2` is default-off: no `default_enabled` at `omnigent/server/feature_flags.py:97-104`; "Off" in `designs/FEATURE_FLAGS.md:34`. No push code exists: a grep for `vapid`, `pushManager`, `web-push`, `apns` and `FCM` under `omnigent/` and `web/src` returns nothing, which confirms F6/finding 9. **Testing consequence:** Coral cannot reuse the scheduler's tests as-is. Its lease and timer tests must copy the patterns in `tests/server/scheduled/test_dispatch_scheduler.py` and `test_scheduler.py:44-74` (`FakeClock`, `FakeScheduleSeam`). I did not re-verify F4, F25, F26 or F42; other lanes own them. |
| D2 | **Confirmed.** | `coral-requirements.md` is absent (`ls` fails). Test plans cannot trace to requirement IDs, so acceptance criteria below trace to D§ and DD§ instead. |
| D3 | **Confirmed**, plus build-side facts. | `web/src/components/concerto/`, `web/src/workflows/`, `coral/` and `tests/coral/` do not exist, and nothing in `web/src` matches `concerto`. `/workflows`, `/schemas`, `/profiles` and `/v1/coral` are unused in `web/src/App.tsx` and `omnigent/server`. `web/src/canvas/` and `/canvas` are taken by the `canvas` flag (`App.tsx:194-206`; F43). Build-side: the UI doc's plan to relabel the `omni` palette slot (`coral_UI_DESIGN_LANGUAGE.md:52, 376`) edits `web/src/lib/themePalette.ts:47, 217-218` (4 commits/30d) and the generated CSS, which a pre-commit check guards (`.pre-commit-config.yaml:79-84`). **Lower-conflict alternative:** add a new palette entry and change only `DEFAULT_PALETTE` (a one-line seam). |
| D4 | **Confirmed** (DD§15.3). | **Testing consequence:** the Elephant-Goldfish showcase's "isolation" rule (a goldfish reviewer sees only the document) needs a **negative test** asserting that a reviewer session's first request contains no prior transcript. The mock LLM's captured requests make that assertable (`GET /mock/requests`, `mock_llm_server.py:1607-1620`; `get_mock_requests`, `tests/e2e/conftest.py:508`). |
| D5 (new) | The release-tag merge plan is wrong in detail. | See summary item 4 and §8.1. Even nightly tags are not ancestors of `main`; merge `tag^1`. |
| D6 (new) | The deep dive's seam ledger omits test, CI and doc seams that will break CI. | Missing: `feature-map/README.md` and `feature-map/harness-acceptance.md` (feature-map test), `.github/scripts/ci/python-matrix.json` (dedicated lane), `ci.yml:198` and `pyproject.toml:539, 625` (coverage, isort), `.pre-commit-config.yaml:32` (pyrefly regex), `scripts/dump_openapi.py` or a separate Coral spec, the `justfile` import line, and `omnigent/update_check.py` (rebrand). Full list in §5. |
| D7 (new) | The "`cost_budget`" and "refresh threshold" items are out of my lane. | No testing infrastructure impact beyond their unit tests. |
| D8 (new) | The repo-level `CLAUDE.md` dev-DB rule conflicts with Coral schema iteration. | `CLAUDE.md` says to "Always use the shared `~/.omnigent/chat.db` … unless the user explicitly requests isolated data". Iterating an unreleased `coral_*` migration against the shared DB leaves `coral_alembic_version` at a rewritten revision. Omnigent's own "newer build" guard pattern (`db/utils.py:745-765`) would then refuse it. This needs an explicit fork-level exception, recorded in `coral/CLAUDE.md`. |
| D9 (new) | The deep dive says `tests/coral/` holds "unit and engine fault-injection tests" (DD§4.2). | Fault injection that needs **Postgres or CRDB contention** must be under `tests/stores/coral/`, because the DB lanes only run `tests/stores tests/db` (`ci.yml:264, 315, 363`). `tests/coral/` runs on SQLite only. The persistence lane's C20 makes the same point. |

---

## 2. As-is test infrastructure (what Coral reuses)

### 2.1 Placement rules and lanes

Placement rules are in `tests/README.md:7-18` (component tests in owning dirs; `e2e/`, `integration/`, `browser_ui/`, `e2e_ui/`, `e2e_live/` are explicit targets).

**Default pytest:** `testpaths=["tests"]`, and `addopts` ignores `tests/e2e`, `tests/e2e_ui`, `tests/browser_ui`, `tests/e2e_live` and `tests/integration` (`pyproject.toml:480, 487`).

**Unit matrix:** `.github/scripts/ci/python-matrix.json` defines 18 groups, run with `-n 8 --dist loadfile|worksteal --timeout=300 --cov=omnigent -m "not databricks"` (`ci.yml:191-200`). The `misc` group is `tests` minus the explicitly grouped directories (`python-matrix.json:73-77`), so **`tests/coral/` lands in `misc` automatically**.

**DB lanes:** Postgres 16, CRDB 23.2.28 and MySQL 8.0 run `tests/stores tests/db` with `OMNIGENT_TEST_DB_URI` (`ci.yml:231-375`).

**Lane selection:** any non-dependency change runs full CI, including the DB lanes. `database = backend` (`.github/scripts/ci/dependency_scope.py:157-180`). Python CI skips PRs that only touch `web/**`, `docs/**` or `designs/**` (`ci.yml:15-37`).

**Other workflows:**
- E2E: `tests/e2e/` with the mock LLM, on every PR except web-only ones; 8 shards (`.github/workflows/e2e.yml:1-45`). The e2e-run action installs Claude, Codex and Pi CLIs.
- Web: `web-tests.yml` runs on `web/**` and runs `format:check` and `vitest --coverage`.
- Lint: `lint.yml` runs `pre-commit run --all-files` plus `scripts/update_versions.py check`.

**Hang guards:**
- `tests/budgets.py:21-37`, `budget()`, scaled by `OMNIGENT_TEST_TIMEOUT_SCALE=4` in CI (`ci.yml:186`).
- `tests/_helpers/polling.py` (`poll_until`, `poll_until_async`).
- The `sleep-then-assert` custom lint over `tests/` (`dev/lint/lint_sleep_then_assert.py:1-20, 41`).

### 2.2 Primitive catalog (`tests/_helpers/README.md:8-27`) and the primitives Coral uses

| Need in Coral tests | Primitive (exact) | Location | Notes |
|---|---|---|---|
| Per-test DB on any backend | `db_uri`, `_worker_db_uri`, `_sqlite_db_template` | `tests/conftest.py:638-746` | SQLite: a fresh file per test. External backends: one DB per xdist worker, migrated once, then every table except `alembic_version` truncated per test (`:736`; `DELETE` on CRDB). **S31 needed.** |
| Migrated SQLite template for server tests | `_sqlite_db_template` (session, per worker) | `tests/server/conftest.py:519-548` | The Omnigent schema only. Coral API tests should override it to also run `ensure_coral_schema` before the snapshot. |
| In-process server (real stores) | `app`, `client`, `policy_app` / `policy_client`, `auth_app` / `auth_client` | `tests/server/conftest.py:635-776` | `httpx.ASGITransport`. `_app_client` starts a `HarnessProcessManager` and drains relay tasks (`:668-705`). |
| Model stub, in-process | `ControllableMockClient`, `mock_llm` fixture, `runtime_init` | `tests/server/conftest.py:183-303, 426-441, 551-592` | `add_call(text, block, tool_calls, tool_calls_fn, exception, …)`. Used outside `tests/server` via `from tests.server.conftest import ControllableMockClient` (6 call sites, for example `tests/server/integration/test_scheduled_tasks_routes.py:51`). |
| Fake runner and tunnel | `register_test_runner`, `FakeRunnerWebSocket`, `CapturingRunnerClient`, `echo_runner_client` | `tests/server/helpers.py:679-740, 1031-1076, 1129-1140` | `CapturingRunnerClient` records every event the server POSTs to the runner `/events`, which is how to assert briefs and nudges. |
| Session and agent setup | `build_agent_bundle`, `create_test_agent`, `create_test_session`, `create_session_for_agent`, `start_session_stream_collector`, `wait_for_completion`, `policy_tool_call_request` | `tests/server/helpers.py:82, 662, 741, 890, 974, 1158, 1171` | |
| Process-level mock LLM | `mock_llm_server_url` (session), `isolated_mock_llm_server_url` (per test), `configure_mock_llm(key=, match=, required_tools=)`, `reset_mock_llm`, `set_fallback_mock_llm`, `get_mock_requests`, `get_mock_message_requests`, `release_mock_gate` | `tests/e2e/conftest.py:343-545` | Per-agent queues are keyed by model, so give each roster slot its own model key. `match=` keeps tests isolated. |
| Register an operator agent routed at the mock | `register_dir_agent_with_mock_llm` | `tests/e2e/conftest.py:1123-1186` | Stamps `executor.model` and an `auth` block so `openai-agents` hits the mock. |
| Trusted fixtures with Python tools or policies | `operator_agent_store`, `post_operator_session` | `tests/_helpers/operator_agents.py` (catalog row, README:12) | Use for the `coral.policies` `POLICY_REGISTRY` module in E2E. |
| Server and runner lifecycle | `server_runner(...).start_runner(env=)` | `tests/_helpers/server_runner.py` (README:20, 95-103) | |
| Isolated server or host | `isolated_local_server`, `isolated_host`, `reserve_port` | `tests/_helpers/live_server.py`, `host.py` | |
| Session upload and text | `bundle_files`, `post_session_bundle`, `send_user_text` | `tests/_helpers/session.py` | |
| Fail on skipped tests | `-p tests._helpers.required_tests` | `tests/_helpers/required_tests.py:1-20` | Use it in the merge-rehearsal job so the contract suite cannot silently skip. |
| Fake clock and timer seam | `FakeClock`, `FakeScheduleSeam`, `FakeTimer` | `tests/server/scheduled/test_scheduler.py:44-90` | Import directly, as `test_dispatch_scheduler.py:27` does. |
| Frozen recurrence clock | `frozen_recurrence_clock` | `tests/conftest.py:327-336` | |
| Kill or restart the real server mid-turn | `Lab.restart_server(downtime_s=, graceful=)`, `SessionDriver`, `SessionWatcher`, `ScenarioReport` | `tests/e2e/resilience/lab/lab.py:314`; `driver.py:71-296`; `README.md:1-60` | Needs `claude`/`codex` and `tmux`; skips without them. |
| Bench drivers | `Driver` protocol; `SdkInprocDriver`, `FullServerDriver`, native-TUI driver; `CapabilityProbe`; `ALL_PROBES` | `tests/harness_bench/transport.py:11-90`; `probes/base.py:19-48`; `probes/__init__.py:20-33` | Live runs need credentials. CI runs only the offline tests. |

### 2.3 Is there a deterministic fake harness? (Answer: yes, tiered)

| Tier | Mechanism | Plays scripted turns? | Plays scripted tool calls? | Real turn edges and runner? | Cost | Use for Coral |
|---|---|---|---|---|---|---|
| A: in-process | ASGI `client`, no runner bound, plus `CapturingRunnerClient`. Agent tool calls are injected by calling the session MCP handler (`_handle_mcp_tools_call`, as `tests/server/routes/test_sessions_mcp_proxy_policy_retry.py:1-30` does). Turn edges are injected by driving `_publish_status` or the S1 observer registry directly (pattern `tests/server/test_session_live_state.py`). | Simulated | Yes, injected | No (synthesized) | Milliseconds; SQLite only | Engine with `coral.omni`, intercept, gates; the bulk of Phase 1 and 2 behaviour |
| B: process, mock LLM | `server_runner` + `mock_llm_server` + `openai-agents` bundles, one model key per roster member. Scripted `tool_calls` call engine tools; the runner forwards them to the server `/mcp` proxy. | Yes | Yes | Yes (real runner, real `_publish_status`) | Seconds; E2E lane | Runner→server forwarding (S8), turn-end detection, the brief→handoff loop, restart recovery. Topology precedent: `tests/e2e/test_spawn_bounds_subagent_dispatch_e2e.py:1-22`. |
| C: real CLI, mock model | Resilience lab: unmodified Claude Code or Codex TUI → `ANTHROPIC_BASE_URL` → mock (`lab/lab.py:1-20`; `lab/model_server.py:1-30`). | Yes (content marker) | Yes (Bash / exec_command) | Yes (native hooks, tmux) | Tens of seconds; E2E lane, skips without CLIs | `claude-native` step semantics: `turn_completed`, fail-closed hooks (S14), take-over, server-kill mid-run |
| D: narrow fakes | `runner_test_harness`, `FAKE_ACP_AGENT_SCRIPT`, `_FakeCodexAppServerClient`, Codex forwarder `_support.py` | Partial | Partial | Partial | Unit | S2 (Codex `turn/completed`), S8/S9 registration, ACP |

**Gaps:**
- **G1:** No `claude-sdk` fake. Phase 2 starts with `claude-sdk` on API-key auth (DD§19), so its turn-end and tool-gating evidence comes only from live bench runs, which need credentials. Add a bench-only nightly job with an API key. Whether claude-sdk honours a mock base URL like claude-native does is UNVERIFIED; it would enable a Tier C `claude-sdk` lane if it works.
- **G2:** The in-process Tier A cannot prove S8 (runner forwarding) or S11/S12 (native pre-approval and instructions). Those need Tier B or C.

---

## 3. Coral testing strategy per layer

The guiding rules come from repo `CLAUDE.md` and `tests/_helpers/README.md:129-137`:
- Keep input matrices at the lowest reliable layer.
- Use E2E only for distinct process, transport or browser boundaries.
- Extend the nearest scenario.
- Keep faults and assertions in the test.
- Count helper LOC.

### 3.0 Directory and lane map (New)

| Directory | Contents | CI lane (today) | Recommended lane |
|---|---|---|---|
| `tests/coral/model/`, `tests/coral/validate/`, `tests/coral/engine/`, `tests/coral/simulate/`, `tests/coral/fork/` | Pure unit and property tests; seam-ledger checker tests | `misc` (catch-all) | New `coral` group in `python-matrix.json`, plus `--ignore=tests/coral` in `misc` (Modify, 3 commits/30d) |
| `tests/stores/coral/` | Stores, apply_transition, leases, contention, fault injection at commit boundaries | `stores` plus Postgres, CRDB and MySQL lanes | Same (free) |
| `tests/db/coral/` | Alembic env, `ensure_coral_schema`, single-head, SQLite-safe guard, ordering with Omnigent migrations | `db` plus DB lanes | Same (free) |
| `tests/server/coral/` | API routes (`extra_routers`), `coral.omni` contract tests against an in-process server, intercept (Tier A), lifespan workers | `server-rest` (`tests/server --ignore=tests/server/integration`) | Same. Inherits the `app`, `client` and `mock_llm` fixtures. |
| `tests/runner/coral/` | Engine tools in `_ALL_LOCAL_TOOLS` / `_NATIVE_RELAY_BUILTIN_TOOLS`; forward contract | `runner-app` | Same |
| `tests/e2e/coral/` | Tier B and Tier C journeys | E2E lane (explicit target) | Same |
| `tests/browser_ui/workflows/` (later) | Built SPA with mocked `/v1/coral` contracts | E2E UI / browser lane (CI only) | Requires a `feature-map/README.md` entry (§0 item 3) |
| `web/src/workflows/**/*.test.ts(x)` | Vitest | `web-tests.yml` | Same |
| Existing upstream test files touched by seams (e.g. `tests/server/test_feature_flags.py`) | Seam regression | Their own lanes | Record them in the ledger's `tests:` field (§9, FO-1) |

### 3.1 L0: model and static validation (pure)

- **What:** the YAML loader (stable ids, D§12), the compiled graph, and validation rules V1–V13 (DD§5.5).
- **Where:** `tests/coral/model/test_loader.py`, `tests/coral/validate/test_rules.py`.
- **Nearest scenarios:** `tests/spec/test_parser.py` and `tests/spec/test_validator.py` (the agent-spec parser and validator), and `tests/runtime/policies/test_yaml_full_roundtrip.py`.
- **Matrix:** one parametrized table per V-rule with minimal fixture graphs as inline YAML strings. Cover a positive case, each distinct negative case, and the error message and location (node and arrow id). V9 (capability enforceability) uses a **frozen capability matrix fixture**, not live `HARNESS_CAPABILITIES`, so upstream changes to capabilities do not flake Coral tests. Add one separate guard test that the fixture matches `omnigent/harness_capabilities.py` for the four Coral modes; this is the deep dive's "guard test" idea.
- **Round-trip:** load → dump → load gives the same ids, and comments survive. If the server never writes YAML, only the web side needs comment-preserving round-trips (§3.10).

### 3.2 L1: reducer, Simulate, invariants, property and fault-injection tests (pure, no DB)

- **Where:** `tests/coral/engine/` and `tests/coral/simulate/`.
- **Reducer under test:** `transition(graph, state, input) -> Transition(state, log, effects, rejections)`, the DD§6.1 shape. It is pure, so every test runs in microseconds.

**State-machine tables:** one parametrized test per entity in DD§6.2 (Run, Activation, Agent slot, Attempt, Decision request, Gate visit, Signal). Assert the legal transitions and assert that every illegal transition yields a `Rejection`, never an exception and never a state change.

**Semantics regressions (DD§19 Phase-1 list):**
- the D§5.6 example under derived joins completes;
- the literal wait-for-all reading deadlocks (a regression test that Simulate's exhaustive mode reports it);
- per-item loop counters inside repeat-for-each;
- `at_limit` routing at limit N;
- gate answers for a superseded visit token are rejected.

**Invariant catalog**, asserted after every step of every generated sequence:
- I1 `fold(log) == stored_state`, the replay invariant (DD§6.1, DD§19).
- I2 Idempotence: applying input *x* twice equals applying it once (dedup by idempotency key).
- I3 Loop and repeat counters never exceed their limit; `at_limit` fires exactly once per scope.
- I4 No activation without a traversed incoming arrow; join arrivals ≤ incoming arrows.
- I5 Closed slots reject `submit_handoff`. Run-level dedup survives a refresh (new session id, same slot; DD§6.3).
- I6 Effect keys are unique, and every effect is attributable to exactly one log entry.
- I7 Level-triggered convergence: for observation inputs, any permutation of a multiset of signals, plus one `reconcile`, reaches the same state (DD§6.4).
- I8 A run in a terminal status emits no effects.

**Property and fuzz approach, with no new dependency:**
- Use a seeded `random.Random(seed)` generator over "legal plus adversarial" input sequences: duplicates, drops, reordering, late gate answers, illegal arrows.
- Parametrize over a fixed seed list in PR CI. Allow a larger count via an env var such as `CORAL_FUZZ_SEEDS`. The `nightly` marker is not excluded in unit lanes (`ci.yml:193` uses `not databricks`), so do not use it here.
- Print the failing seed and the minimized sequence in the assertion message.
- `hypothesis` is **not** a dependency today (not in the `test` group, `pyproject.toml:346-403`; absent from `uv.lock`). Adding it is an optional dependency decision (§7).

**Exhaustive Simulate (DD§15.1):** enumerate label choices × list lengths {0, 1, 2} × pass/fail × gate answers, bounded by a cap. Assert no deadlock, no dead box and a reachable `at_limit`, and assert that the reported "sampled vs total" is correct when the cap is hit. Saved simulations become regression tests (D§8): a `tests/coral/simulate/test_saved_cases.py` collector parametrizes over `*.sim.yaml` fixtures.

**Fault injection in the pure layer:** model "crash" as truncating the input sequence at any index, then re-reconciling from the stored state. That is I1 plus I7. Real DB commit-boundary faults belong in L2.

### 3.3 L2: stores, migrations and DB-backend behaviour (`tests/stores/coral/`, `tests/db/coral/`)

| Test | Nearest scenario / primitive | Assertion |
|---|---|---|
| CRUD, pagination, named sessions per store | `tests/stores/test_scheduled_task_store.py` (fixture `store(db_uri)` at `:31-40`); `tests/stores/test_project_store.py` | Round-trips. Every list paginates. The session name is semantic (repo `CLAUDE.md` "Database query names"). |
| `apply_transition` atomicity | `tests/db/test_utils.py:130-225` (`run_write_transaction` retries 40001/1213) | Log, state and effects commit together or not at all. Inject an exception **between** log append and effect insert by monkeypatching the store's internal writer: nothing is persisted. |
| Optimistic version conflict | `tests/stores/test_preference_store.py:257` (two stores, one `db_uri`); `tests/stores/test_agent_store.py:818` | Two writers with the same `expected_version`: exactly one wins, and the loser gets a typed conflict. |
| Signal and effect leases | `tests/stores/test_pending_conversation_inputs.py:28` ("restart and concurrent submission claims"); `tests/stores/test_host_store.py:154` (`threading.Barrier`) | A claim is exclusive. An expired lease is re-claimable. An expired claim cannot be revived (mirror `test_dispatch_scheduler.py:888, 1209`). |
| Contention | Same barrier pattern; run under the Postgres and CRDB lanes | "Race two workers on Postgres" (DD§19): N workers, one run, and the final state equals the serial fold. |
| Forced `SQLITE_BUSY` | Precedents grep-found in `tests/stores/test_conversation_store.py`, `tests/stores/test_host_store.py`, `tests/db/test_utils.py` | Hold `BEGIN IMMEDIATE` on a second connection and assert bounded retry, then a typed error. Never a half-written transition. |
| Crash at commit boundaries | New, local helper | Raise a `SimulatedCrash(BaseException)` at injection points: before and after log append, before and after effect dispatch, and after effect execution but before the result is recorded. Then build **fresh** store and worker objects on the same `db_uri` (a new "process"), run `reconcile`, and assert I1 and I2. Effects must be idempotent via `effect_key` and the `coral.effect_id` session label (DD§6.1). |
| Workspace and account scoping | `tests/db/test_workspace_scope.py`; `tests/stores/test_account_revocation.py` | Rows are invisible across `workspace_scope`. Writes fail for a revoked account generation. |
| Coral Alembic env | `tests/db/test_utils.py:679-853` (`initialize_or_verify_schema` fresh, at head, stale and newer-build); `tests/db/test_migration_connections.py:34-37` (single head); `tests/db/test_migrations_sqlite_safe.py` (static batch-mode guard) | `ensure_coral_schema` is idempotent, runs only after Omnigent is at head, refuses a newer Coral DB, and has a single Coral head. Every Coral migration uses batch mode. Omnigent's `alembic_version` is untouched. `CoralBase.metadata ∩ OmnigentBase/ConversationBase.metadata = ∅` (`db/utils.py:611-618` would otherwise `create_all` Coral tables). |
| Ordering with upstream migrations (rehearsal core) | `tests/db/test_migration_scheduled_tasks.py` style | Populate `coral_*` at Coral head, run an Omnigent upgrade from N-k to head, then Coral to head: data intact. On CRDB, the SERIALIZABLE preparation path is exercised (`db/utils.py:600-612`). |
| Autogenerate isolation (S30) | New | With the `include_name` filter, Omnigent autogenerate against a DB containing `coral_*` proposes no drops, and vice versa. |

**S31 (Modify `tests/conftest.py:736`).**
- **Minimal edit:** preserve every table whose name ends in `alembic_version`. This is a generic, upstreamable change ("preserve all Alembic version tables").
- **Without it:** on the external-DB lanes, the second test in a worker sees an empty `coral_alembic_version` and re-runs `CREATE TABLE`, which fails.
- **Alternative with zero upstream edits:** override `db_uri` in `tests/stores/coral/conftest.py` and `tests/db/coral/conftest.py`. That duplicates about 30 lines and contradicts the reuse rule, so it is not recommended.

### 3.4 L3: `coral.omni` contract tests (the boundary that absorbs upstream churn)

- **Purpose:** DD§4.2 makes `coral.omni` the only importer of Omnigent internals. Its contract tests are the **first thing the merge rehearsal runs**.
- **Where:** `tests/server/coral/omni/`. That location inherits `app` and `client` and runs in `server-rest`.
- **What each facade function must prove against a real in-process app** (no runner, `CapturingRunnerClient` installed as `omnigent.runtime._globals._runner_client`, as at `tests/server/helpers.py:1031-1045`):
  - `create_session` creates a session with labels (`coral.effect_id`, the run and slot ids) and is idempotent on re-call with the same effect id;
  - `send_brief` posts exactly one event to the runner;
  - `read_status` and `read_items` return what `_publish_status` wrote;
  - `interrupt` and `stop` are forwarded;
  - `attach_policies` produces policies visible to `build_policy_engine`;
  - `publish_gate` produces an elicitation (S6);
  - `create_worktree` sends `HostCreateWorktreeFrame` (`tests/server/routes/test_host_worktree.py:1-25`, fake host auto-reply).
- **Nearest scenario:** `tests/server/scheduled/test_fire.py:1-60`. `fire.py` is the in-tree precedent for request-free orchestration through injected `FireDeps`, and its tests use fakes plus the real `SqlAlchemyAgentStore` and `LocalArtifactStore`.
- **Import-boundary test (New, zero upstream edits):** `tests/coral/test_import_boundary.py` AST-scans `coral/**` and fails if any module outside `coral/omni/` imports `omnigent.*`. An allowlist covers public, stable modules such as `omnigent.db.utils` helpers and the entities that persistence must use. Prefer this over a new `dev/lint` rule, which would edit `dev/lint/custom_lint.py` (3 commits/30d).

### 3.5 L4: API tests and the Coral OpenAPI contract

- **Where:** `tests/server/coral/api/`.
- **Nearest scenario:** `tests/server/integration/test_scheduled_tasks_routes.py:91-190`, which has a local `_build_app(...)` calling `create_app(...)` with real stores and header auth (`UnifiedAuthProvider(source="header")`). Build the app with `create_app(..., extra_routers=coral_routers(...))` (`omnigent/server/app.py:1578, 5308-5310`).
- **Matrix:** authorization uses LEVEL_EDIT for gate answers and LEVEL_MANAGE for amendments (DD§20.1 Q4; `omnigent/server/auth.py:123-126`). Also test idempotent `start_key` on Run, 404 vs 403 shape, pagination, and CSRF origin (the autouse `_first_party_origin_on_asgi`, `tests/server/conftest.py:594-633`).
- **Flag gating:** with the `workflows` flag off, routers are not mounted or return 404, and `/v1/info` `features.workflows == false`. With it on, the reverse.
- **Lifespan workers (S32):** the nearest scenario is `tests/server/integration/test_scheduler_lifespan.py:1-7`. Workers start on lifespan entry and stop on exit, and no worker starts when the flag is off.
- **OpenAPI:** `scripts/dump_openapi.py:324-370` builds the app **without** `extra_routers`, so Coral routes never enter `openapi.json`. That file is 20,377 lines with 69 commits/30d; avoid it.
  - **New:** a `coral/api/openapi.json` artifact and `coral/api/dump_openapi.py` that builds a FastAPI app with only the Coral routers, reusing `_enrich_spec`-style post-processing if needed.
  - **New:** `tests/server/coral/test_coral_openapi_drift.py`, a byte-for-byte copy of the pattern in `tests/server/test_openapi_drift.py`.
  - There is no TS codegen from OpenAPI in `web/` (grep found no `openapi` in `web/package.json` or `vite.config.ts`), so web types are hand-written.

### 3.6 L5: engine-tool intercept tests (S7–S11)

| Seam | Nearest scenario | Test |
|---|---|---|
| S10 server-side tool handler registry, generalizing `sys_advise_models` (`orchestration.py:13058-13069`) | `tests/server/routes/test_sessions_mcp_proxy_policy_retry.py` (calls `_handle_mcp_tools_call` directly with real stores; no MagicMock) | An engine tool name, both bare and `mcp__omnigent__` namespaced, dispatches to the Coral handler **after** policy DENY/ASK evaluation. A policy-transformed argument reaches the handler. Unknown tools fall through to the runner. Handler exceptions become a JSON-RPC error without internal detail (pattern `tests/server/routes/test_sessions_mcp_proxy.py:1-81`). |
| S7 tool classes and AgentSpec opt-in | `tests/tools/test_manager.py`; `tests/spec/test_parser.py` | Schema-only registration. Tools are absent without the opt-in, and the opt-in parses like `spawn`. |
| S8 and S9 runner forwarding and native relay | `tests/runner/test_scheduled_task_tool_dispatch.py:1-25` (asserts membership in `_ALL_LOCAL_TOOLS` / `_NATIVE_RELAY_BUILTIN_TOOLS` and proxies REST verbs) | Engine tools are members of both sets (`omnigent/runner/tool_dispatch.py:488, 888`) and are forwarded verbatim. A server 4xx becomes clean error JSON. |
| S11 native pre-approval | `tests/runner/test_app_claude_native_launch_args.py`; `tests/harnesses/codex_native/app_server/` | Engine tools are pre-approved in "don't ask" mode. |
| Engine tool semantics (`submit_handoff`, `choose_arrow`, …) | Tier A | Validate, then commit (DD§6.3). Re-sent calls return the original result (idempotency key = harness call id). Rejections are audit-only and counted. A closed slot rejects. |
| Policy engine state | `tests/e2e/test_spawn_bounds_subagent_dispatch_e2e.py:1-22` documents that the `/mcp` proxy **rebuilds the policy engine on every tool call** | Any Coral policy that counts things (rejected calls, fan-out) must keep state in session state or labels, not closures. Add a regression test that calls the intercept twice in one turn. |

### 3.7 L6: policy tests (`coral.policies` registry module, roster enforcement, protected policies)

- **Where:** `tests/coral/policies/`.
- **Nearest scenarios:**
  - `tests/policies/builtins/helpers.py:18-77` (`tool_call_event`, `llm_request_event`, `tool_result_event` builders);
  - `tests/policies/builtins/test_subagent_cost.py`, `test_enforce_sandbox.py`;
  - `tests/policies/test_registry.py` (loading by `POLICY_REGISTRY`, `omnigent/policies/registry.py:103-130`);
  - `tests/runtime/policies/test_subagent_guardrails.py`, `test_four_phase_contract.py`.
- **Matrix:** for `step_roster` and `engine_tool_guard`, test each harness's tool name and namespace form × ALLOW/DENY/ASK × with and without sub-agent identity (S16/S17).
- **S26 protected policies:** non-engine PATCH or DELETE of a reserved prefix returns 403 (nearest: `tests/server/routes/test_session_policies_crud.py`).
- **Fail-closed hooks (S14):** unit tests sit next to `tests/native/` and `tests/harnesses/claude_native/`. One Tier C E2E makes the policy endpoint unreachable and asserts the tool is blocked; that is the `gate_failure_mode` probe (DD§10.3).

### 3.8 L7: runner and host frame tests

- **S2** (Codex `turn/completed` carries `turn_completed`): nearest are `tests/harnesses/codex_native/forwarder/_support.py` and `forwarder/test_turn_errors.py`, plus `tests/harnesses/codex_native/session/_support.py:112` (`_completed_event`).
- **S40** (new host frame for workspace fingerprints and running pinned commands):
  - Frame codec round-trip: `tests/host/test_frames.py` (imports at `:11-63`).
  - Server proxy with a fake host auto-reply: `tests/server/routes/test_host_worktree.py:1-25`.
  - Host handler: `tests/host/test_git_worktree.py`.
  - **Capability negotiation:** the new frame needs a `CAP_*` constant, like `CAP_WORKTREE_CREATE_BUDGET` (`omnigent/host/frames.py:91`). The server must degrade gracefully against older hosts, because the upstream **server-compat** sweep crosses server and runner versions (`.github/workflows/server-compat.yml:1-20`). Add a test for "old host without cap → typed `capability_unavailable`, step pauses (not fails)".
- **Fingerprint correctness** (D§6.1: tracked files plus new non-ignored files): use a pure function on a temp git repo. There is precedent for temp repos in `tests/host/test_git_worktree.py` and `tests/runner/git_provider_fixtures.py`. The matrix covers edit, new file, ignored file, `git apply` and generator output.

### 3.9 L8: turn-edge observers, elicitation observers, gates (S1, S5, S6)

- **S1 observer registry:** nearest is `tests/server/test_session_live_state.py`. Assert that the scheduled-run hook still fires as one observer, and that a Coral observer receives `session_id`, `status`, `turn_completed`, `response_id`, `previous_status`, `failure_origin`, `error` and `persist_live_status`. Also cover the two status edges that bypass `_publish_status` (`orchestration.py:4131-4152, 13706-13708`; DD§4.1); assert that the reconciler catches them if the seam does not.
- **S5 multi-observer:** nearest are `tests/runtime/test_pending_elicitations.py` and `tests/runtime/test_subagent_block_notifier.py` (the current single slot at `omnigent/runtime/pending_elicitations.py:9-28`). The `SubagentBlockNotifier` behaviour must be unchanged with a second observer.
- **S6 request-free gate elicitation and verdict callback:** nearest are `tests/server/integration/test_sessions_elicitation_api.py` and `tests/server/routes/test_terminal_resolved_elicitation.py`. Cover gate re-publish after restart from `coral_gate_visits`, and a stale-token answer being rejected.

### 3.10 L9: harness bench probes (S22, S23)

- **New probes** (`subagent_attribution`, `steering_reliability`, `usage_reporting`, `tool_call_gating`, `end_of_turn_detection`, `gate_failure_mode`; DD§10.3) are new modules under `tests/harness_bench/probes/` plus a registration in `probes/__init__.py:20-33` (0 commits/30d).
- **Coupling:** every probe name must be mapped in `feature-map/harness-acceptance.md`, or `tests/dev/test_verify_omnigent_feature_map.py:110-127` fails.
- **Offline determinism:** the bench's own unit tests (`tests/harness_bench/test_*.py`) run in `misc`. Each new probe needs an offline verdict test with a stub driver, following `tests/harness_bench/test_policy_matrix.py` and `test_cost_tracking.py`.
- **Live:** `python -m tests.harness_bench --live --require-complete --harness <mode> --dimension <new dims> --json --report …` (`tests/harness_bench/README.md:44-66`; exit 2 means incomplete). This needs credentials, so it is **not** a PR gate. Run it as a scheduled Coral job per pinned CLI version (risk R6 in DD§18).

### 3.11 L10: web (vitest)

- **Where:** colocated `web/src/workflows/**/*.test.ts(x)`. They are picked up by `include: ["src/**/*.{test,spec}.?(c|m)[jt]s?(x)"]` with `environment: "jsdom"` and setup at `src/test-setup.ts` (`web/vite.config.ts:255-262`).
- **Key constraint:** `@xyflow/react` **OOMs in jsdom**. The existing graph tests mock React Flow and test pure layout modules instead (`web/src/shell/SubagentsGraphView.test.tsx:19-22`; `web/src/pages/CanvasPage.test.tsx:1`, "React Flow is stubbed to a plain list"). Coral must therefore keep these as **pure modules with no `@xyflow/react` import**, each with vitest unit tests:
  - graph↔YAML mapping;
  - layout (ELK or dagre adapter);
  - two-way YAML AST edits (comment preservation; stable ids);
  - run-view reducers over the run-log stream;
  - validation-message rendering.
- **Components:** page and component tests mock React Flow, as `CanvasPage.test.tsx` does. `ResizeObserver` is already polyfilled (`web/src/test-setup.ts:71-75`).
- **Feature gate:** extend the pattern of `web/src/lib/capabilities.test.ts:209-219` (`isFeatureEnabled(parsed, "automations_v2")`) for `"workflows"`. Route gating uses `FeatureGatedPage` (`web/src/App.tsx:76, 187`).
- **No local browser verification** (repo `CLAUDE.md`). Browser lanes (`tests/browser_ui/workflows/`, `tests/e2e_ui/workflows/`) are CI-only and need feature-map registration.

### 3.12 L11: minimal E2E set

Explicit targets only. Each test must justify a distinct process or transport boundary, per the PR "Test Plan" rule.

| ID | Tier | Journey | Boundary justified | Primitives |
|---|---|---|---|---|
| E2E-1 | B | Two-step workflow (Work step → Human gate → End). The step agent is an `openai-agents` bundle on model key `mock-coral-step-1`, scripted to call `submit_handoff`. The gate is answered via the API. | Runner→server engine-tool forwarding (S8); real turn edges (S1) | `server_runner`, `mock_llm_server_url`, `configure_mock_llm(key=…)`, `register_dir_agent_with_mock_llm`, `poll_until` |
| E2E-2 | B | Same as E2E-1, but the server is SIGTERMed between brief delivery and handoff, then restarted. The run resumes and no second session is created (`session_created` before brief, DD§6.2). | Process restart and durable recovery | `server_runner` restart, or extend `tests/e2e/resilience/lab` `restart_server` |
| E2E-3 | C | A `claude-native` step under a mock model. A scripted Bash plus a `submit_handoff` MCP call, then `turn_completed` drives the advance. | Native hooks, tmux, relay MCP (S9, S11, S12) | Resilience lab `SessionDriver` (content markers) |
| E2E-4 | C | Fail-closed: the policy endpoint is blackholed mid-step and the tool call is blocked (S14). | Native hook failure mode | `Lab` proxies (`proxies.host.blackhole()`, `lab.py:367`) |
| E2E-5 | B (Phase 6) | Parallel split and join with two agents. The join waits for both; a duplicate signal is a no-op. | Concurrency over real processes | As E2E-1 |

Keep the D§5.6 example and the deadlock regressions in L1, not E2E.

### 3.13 Phase-1 test plan (DD§19) mapped to concrete tests

| DD§19 item | Layer and location |
|---|---|
| Crash at every commit boundary | L2 `tests/stores/coral/test_commit_boundary_faults.py` (SQLite plus three DB lanes) |
| Drop signals and recover by periodic reconcile; reorder signals | L1 invariant I7 plus L2 `test_reconcile_recovers_dropped_signals.py` |
| Race two workers on Postgres; force `SQLITE_BUSY` | L2 contention tests (§3.3) |
| Late or stale gate answer; amendment racing a step start | L1 gate-visit tokens plus L2 optimistic version conflict |
| `fold(log) == stored state` | L1 I1 after every step, plus L2 after real commits |
| D§5.6 under derived joins; wait-for-all deadlock regression; per-item loop counters | L1 Simulate |
| Kill the server mid-run (D§18) | E2E-2 (one test), not a matrix |

---

## 4. Required CI changes (Modify/New), by file

| # | File | Change | Type | 30-day churn | Seam |
|---|---|---|---|---|---|
| C1 | `pyproject.toml:460` | `include = ["omnigent*", "coral*"]` | Modify | 23 (file); line rarely touched | S29 |
| C2 | `pyproject.toml:462-472` | package-data `"coral.db" = ["alembic.ini"]`, `"coral.db.migrations" = ["script.py.mako"]`, `"coral.templates" = ["*.yaml"]` | Modify | | S29 |
| C3 | `pyproject.toml:625` | `known-first-party = ["omnigent", "coral"]` | Modify | | S39b (new) |
| C4 | `pyproject.toml:539` and `ci.yml:198` | Coverage `source = ["omnigent", "coral"]`; `--cov=omnigent --cov=coral`. Report-only, so it can be deferred. | Modify | 19 (ci.yml) | S39c (new) |
| C5 | `pyrefly.toml:1-5` | add `"coral/**/*.py"` | Modify | 0 | S39 |
| C6 | `.pre-commit-config.yaml:32` | pyrefly `files:` regex adds `coral/.*\.pyi?` | Modify | 7 | S39 |
| C7 | `dev/lint/lint_workspace_scoped_cache.py:40` | `SCANNED_ROOTS += ("coral/",)` | Modify | 0 | S39 |
| C8 | `.github/CODEOWNERS:1-6` | Replace the upstream maintainer handles with Coral owners, and add `/coral/`, `/coral/db/migrations/`, `/tests/stores/coral/`, `/web/src/workflows/`, `/.coral/` | Modify | 0 | S39 |
| C9 | `.github/scripts/ci/python-matrix.json` | Add a `{"group":"coral","paths":"tests/coral","dist":"worksteal"}` group and `--ignore=tests/coral` in `misc` | Modify | 3 | New (S39d) |
| C10 | `tests/conftest.py:736` | Preserve `*alembic_version` tables | Modify | 9 | S31 |
| C11 | `.github/workflows/coral-fork-guard.yml` | Seam-ledger check, commit-prefix check, import-boundary test, Coral OpenAPI drift | New | n/a | — |
| C12 | `.github/workflows/coral-upstream-rehearsal.yml` | Daily trial merge from the nightly tag's first parent, plus the contract suite on SQLite, Postgres and CRDB (§8.3) | New | n/a | — |
| C13 | `.github/workflows/coral-bench.yml` | Scheduled live bench for the Coral modes and dimensions; credentials as secrets | New | n/a | — |
| C14 | `feature-map/README.md`, `feature-map/harness-acceptance.md` | Map new probes and UI areas, or list them under "Not yet mapped" | Modify | 25 / 11 | New (S23b) |
| C15 | `justfile` | One line: `mod coral 'coral/coral.just'` (§6) | Modify | 3 | New |
| C16 | GitHub settings (not files) | Disable inherited workflows that are irrelevant or need upstream secrets: triage, polly-review, doc-sync, feature-blog, ui-preview and others. Disable Dependabot for upstream-owned manifests. Define branch protection with Coral's required checks (`CI result`, `Pre-commit checks`, `Web result`, E2E shards, `coral-fork-guard`). | Config | — | — |

Notes:
- `ci.yml` needs **no** change for DB-lane coverage of `tests/stores/coral` and `tests/db/coral`.
- `e2e.yml` already triggers on `'**'` minus web and docs (`e2e.yml:30-44`), so `tests/e2e/coral/` runs in the E2E lane.
- `web-tests.yml` already covers `web/**`.

---

## 5. Complete seam additions from this lane (to merge into the S-ledger)

| ID | File | Why | Upstreamable? |
|---|---|---|---|
| S31' | `tests/conftest.py:736` | Generic form: preserve every `*alembic_version` table | Yes (generic) |
| S39b | `pyproject.toml:625` (isort) | `coral` is first-party | No |
| S39c | `pyproject.toml:539`, `ci.yml:198` | Coverage of `coral` | No |
| S39d | `python-matrix.json` | Dedicated `coral` CI group | No |
| S23b | `feature-map/harness-acceptance.md`, `feature-map/README.md` | The feature-map test requires mapping probes, UI areas and CLI commands | Partly (probe rows, if probes go upstream) |
| S41 | `omnigent/update_check.py:66, 1622, 1843` | Distribution name, nightly repo URL and install URL. Without this change, a Coral install is offered upstream Omnigent. | No |
| S42 | `web/electron/src/omnigent_cli.js:277, 614`; `web/electron/package.json` (`productName`, `appId`) | Desktop CLI detection and identity, if the CLI or app is renamed | No |
| S43 | `justfile` (one `mod` line) | Coral dev recipes | No |
| S44 | `NOTICE` (append-only addendum) | Apache §4(d) addendum | No |
| S45 | `.github/CODEOWNERS` | Ownership (also S39) | No |

**Avoid** these, which are tempting but high-conflict:
- adding Coral routes to `openapi.json` (69/30d);
- adding Coral deps to `web/package.json` (29/30d) without a "regenerate the lock" rule;
- changing the `[project].version` line (bumped weekly on main by "Bump version" PRs: `08b7d8043`, `51aef3cdf`, `3679b71cf`, `5f9d79cd2`);
- appending to the end of enum or union lists that upstream also appends to (§6.3).

---

## 6. Dev loop

### 6.1 Proposed `coral/coral.just` (New; imported by one `mod` line in `justfile`)

`just` supports modules. The `justfile` has 3 commits/30d, so one line there is a low-risk seam.

```just
# coral/coral.just — Proposed
test *args:
    uv run --no-sync pytest tests/coral tests/server/coral tests/runner/coral tests/stores/coral tests/db/coral -n 4 --dist loadfile --reruns 0 {{args}}

test-unit *args:          # pure layers only; seconds
    uv run --no-sync pytest tests/coral --reruns 0 {{args}}

test-crdb: (_crdb)        # mirrors scripts/test_crdb_matrix.sh for the Coral subset
    OMNIGENT_TEST_DB_URI="cockroachdb+psycopg://root@localhost:26323/defaultdb?sslmode=disable" \
      uv run --extra all --extra cockroachdb pytest tests/stores/coral tests/db/coral -n 4 --dist loadfile --reruns 0
_crdb:
    just crdb-up

test-e2e *args:           # explicit target; tests/e2e is ignored by addopts
    uv run --no-sync pytest tests/e2e/coral -n 2 --reruns 0 {{args}}

web-test:
    pnpm --filter web exec vitest run src/workflows

simulate file:
    uv run --no-sync python -m coral.engine.simulate {{file}}

openapi *args:            # regenerate or --check the Coral API spec
    uv run --no-sync python -m coral.api.dump_openapi {{args}}

seams:                    # fork guard: diff vs pinned upstream must be inside ledger
    uv run --no-sync python -m coral.fork.check_seams

rehearse ref="":          # trial-merge in a throwaway worktree; never touches main
    uv run --no-sync python -m coral.fork.rehearse {{ref}}
```

Facts the recipes rely on:
- `just crdb-up` starts CRDB 23.2.28 on port 26323 (`justfile:62-66`; `deploy/cockroachdb/docker-compose.yml:2-6`).
- The CRDB matrix script is `scripts/test_crdb_matrix.sh:1-20`.
- `--reruns 0` follows `tests/README.md:54`.

### 6.2 Dev-loop rules for Coral (from repo `CLAUDE.md`, plus fork-specific needs)

- **Standalone local tests are optional.** Use the smallest relevant check, usually `just coral::test-unit`, or one store test with `-k`. Do not run browser verification locally.
- **Formatting and type checks** come from the pre-commit hooks once `just ensure` or `just hooks` has been run. Pyrefly covers `coral/` only after C5 and C6.
- **Dev database (D8).** Upstream `CLAUDE.md` mandates the shared `~/.omnigent/chat.db`. For Coral **schema iteration**, recommend an isolated DB, for example `OMNIGENT_DATA_DIR=$PWD/.coral-dev uv run --no-sync omnigent server --database-uri sqlite:///$PWD/.coral-dev/chat.db`, plus a `coral db downgrade` command. Write this exception into `coral/CLAUDE.md`; nested `CLAUDE.md` files apply to their subtree without editing the root file. A human must approve the deviation.
- **`omnidev` pods** already isolate their own `chat.db` (`dev/omnidev/src/pod.rs:70-75, 180`). The Coral schema gets created there on the first server start, once `ensure_coral_schema` is wired.
- **Builds.** The wheel build compiles the SPA (`setup.py:42, 97-199`; skipped with `OMNIGENT_SKIP_WEB_UI=true`). `web/src/workflows` ships inside `omnigent/server/static/web-ui`. Electron: `just electron-dev` and `just electron-build` (`justfile:116-122`).

### 6.3 Merge-friendly editing conventions for seams (cheap and high-leverage)

- **Insert, do not append.** In `Feature` (`feature_flags.py:23-42`), `FEATURE_DEFINITIONS` (`:57-177`), `FeatureKey` (`web/src/lib/capabilities.ts:60-74`, 31/30d) and the exact dict in `tests/server/test_feature_flags.py:34-50` (17/30d), place the Coral entry at the **top** or in alphabetical position. Upstream appends at the end, and edits to adjacent lines produce textual conflicts.
- **Anchor comments.** Mark every seam with `# CORAL(S10): <one line>` or `// CORAL(S34): …`. The ledger checker verifies that each ledger seam has at least one anchor in its files and that every anchor maps to a ledger seam (§8.2). The anchors also serve as Apache §4(b) "prominent notices" in modified files; that is a counsel question.
- **One-line calls.** A seam in a hot file is a one-line call into a registry that lives in a low-churn file or in `coral/`. DD§17 practice 2 says the same.

---

## 7. Dependencies: rules and concrete status

| Dependency | Current repo state | Rules that apply | Recommendation |
|---|---|---|---|
| `yaml` (npm, for comment-preserving YAML AST editing) | **Not** a direct `web` dependency. `yaml@2.9.0` appears only transitively via vite (`pnpm-lock.yaml:9506, 20103`); `web/package.json` has none. | pnpm `minimumReleaseAge: 10080` (7 days, `pnpm-workspace.yaml:9-15`). `check_npm_peers.py` on changed peers (`web-tests.yml`). `lint_pnpm_override_consistency.py` (`lint.yml`). Lockfile must be current (`lint.yml`, "Check pnpm-lock.yaml is up to date"). | Add the exact version that is already locked (2.9.0) as a direct dependency, so there is no new resolution. |
| `elkjs` | Present transitively: `elkjs@0.11.1` via `beautiful-mermaid@1.1.3` ← `@lobehub/ui` (`pnpm-lock.yaml:5721, 14622-14625, 11092`). Its licence is EPL-2.0 (**UNVERIFIED**; `node_modules` is absent). | Same pnpm rules; licence review | If chosen, pin 0.11.1 to reuse the locked artifact. Counsel review (DD§16.3, DD§20.2 Q6). |
| `dagre` | Absent; only `dagre-d3-es@7.0.14` is transitive (`pnpm-lock.yaml:5497`) | Same | If chosen, a new top-level dependency. MIT (**UNVERIFIED**). |
| `@fontsource/newsreader` (UI doc §143) | Absent. The precedent is `@fontsource-variable/geist-mono` (`web/package.json` dependencies; `pnpm-lock.yaml:1438`). | Same, plus the font licence (OFL-1.1, **UNVERIFIED**) | Add with the OFL text in the Coral NOTICE addendum |
| `@xyflow/react` | Already a dependency (`^12.11.1`) | — | Reuse. jsdom constraint in §3.11. |
| `hypothesis` (Python, optional) | Absent from the `test` group (`pyproject.toml:346-403`) and from `uv.lock` | uv cooldown `exclude-newer = "P7D"` (`uv.toml:13`). `young-dependency-floor` lint (`dev/lint/lint_young_dependency_floor.py:1-30`). `check-internal-mirror` (`justfile:286-292`) needs the Databricks proxy, which Coral cannot reach. `CLAUDE.md` scopes it with "when you can reach". | Defer. The seeded stdlib fuzzing in §3.2 needs no dependency. If added, use a floor older than 7 days, in the `test` group only. |
| `claude-agent-sdk` bump | Floor `>=0.1.62` (`pyproject.toml:101`), locked `0.2.121` (`uv.lock:750-751`) | Same uv rules. Bumping an upstream-owned floor conflicts with upstream's own bumps (`uv.lock` 34/30d). | Do **not** bump in the fork unless a seam needs it. Let upstream merges carry SDK bumps. If unavoidable, raise only the `uv.lock` pin, keep the floor, and ledger it. |
| PyYAML (Python YAML) | Already a dependency (`pyyaml>=6.0,<7`, `pyproject.toml:32`) | — | Reuse for the server-side loader, with marks for line numbers. |

**General fork rules (proposed):**
- Coral adds or bumps only **Coral-owned** dependencies.
- After a merge, regenerate the lockfiles (`uv lock`, `pnpm install --lockfile-only`) rather than hand-resolving them.
- Never run Dependabot on upstream-owned manifests in the fork.

---

## 8. Upstream merge operations

### 8.1 Measurements (local clone at `2a9cbe2c2`)

**Pace:**
- About 1,510 commits on HEAD's lineage between 2026-10-09 and 2026-11-09, roughly 50 per day.
- **0 merge commits**: squash-merge, linear history.
- Minors are weekly: v0.13.0 (2026-09-09) through v0.21.0 (2026-11-05).
- About 9 upstream migration commits in 30 days. There are 121 revisions in `omnigent/db/migrations/versions/`.

**Tag topology:**
- `git merge-base --is-ancestor` fails for `v0.19.0`, `v0.20.0` and `v0.21.0`.
- `git log v0.21.0 ^HEAD` = `2f636330c` (release v0.21.0), `f08ca4a75` (rc2), `fe845f60f` (backport of `c42c3c33e` #12711, which is on main) and `20e15700f` (rc1). The merge-base is `19e95c5c3` (2026-11-02).
- Nightly tags `v0.22.0.dev20261106`, `…07` and `…08` are also **not** ancestors. Each is one `nightly:` stamp commit touching 6 files (`integrations/slack/pyproject.toml`, `omnigent/version.py`, `pyproject.toml`, two SDK pyprojects, `uv.lock`). Its parent is the newest **green** `main` commit (`nightly-release.yml:1-24, 106-125`).

**Version line:** bumped on main weekly by "Bump version" commits (four in 30 days on `pyproject.toml:8`).

30-day churn of the files Coral must touch (commits / current lines):

| File | Churn | Lines | Seams |
|---|---|---|---|
| `omnigent/harnesses/claude_native/bridge.py` | 83 | 11,463 | S14 |
| `omnigent/server/routes/_sessions/orchestration.py` | 77 | 14,185 | S1-bypass, S3, S6, S10 |
| `openapi.json` | 69 | 20,377 | (avoid) |
| `omnigent/server/app.py` | 64 | 5,525 | S1 registration, S32 |
| `omnigent/host/connect.py` | 62 | 6,387 | S40 |
| `omnigent/runner/native/orchestration.py` | 56 | 11,493 | S11, S12, S15 |
| `omnigent/server/routes/_sessions/helpers.py` | 52 | 12,742 | S1, S3, S25, S26 |
| `web/src/shell/Sidebar.tsx` | 51 | 7,772 | S34 |
| `pnpm-lock.yaml` / `uv.lock` | 43 / 34 | — | regenerated |
| `omnigent/server/routes/sessions/routes_core.py` | 42 | 5,296 | S25, S26 |
| `routes_events.py` / `web/src/shell/AppShell.tsx` | 41 / 41 | — | S4 / — |
| `omnigent/cli.py` | 36 | 14,959 | S32 (router wiring) |
| `omnigent/harnesses/codex_native/app_server.py` | 34 | 5,753 | S11, S15 |
| `omnigent/server/schemas.py` | 32 | 5,641 | S25, S28 |
| `web/src/lib/capabilities.ts` | 31 | 705 | S33 |
| `web/package.json` | 29 | — | dependencies |
| `codex_native/forwarder.py` | 28 | 10,109 | S2 |
| `web/src/index.css` | 27 | 2,983 | UI theme |
| `omnigent/host/frames.py`; `feature-map/README.md` | 25; 25 | — | S40; S23b |
| `omnigent/runner/tool_dispatch.py`; `scheduled/fire.py` | 24; 24 | — | S8, S9; (pattern only) |
| `omnigent/server/feature_flags.py`; `tests/server/test_feature_flags.py` | 18; 17 | — | S33 |
| `InboxPage.tsx` / `CommandPalette.tsx` / `tests/conftest.py` | 13 / 9 / 9 | — | S37 / S34 / S31 |
| `App.tsx` / `SessionUpdatesProvider.tsx` / `themePalette.ts` / `harness_plugins.py` / `tools/manager.py` / `spec/types.py` | 6 / 5 / 4 / 4 / 4 / 4 | — | S34 / S35 / UI / S22 / S7 / S7 |
| `session_live_state.py` / `spec/parser.py` / `python-matrix.json` / `justfile` | 3 / 3 / 3 / 3 | — | S1 / S7 / S39d / S43 |
| `prompt.py` / `pending_elicitations.py` / `useIdleNotifications.ts` / `update_check.py` | 2 / 1 / 1 / 1 | — | S12 / S5 / S36 / S41 |
| `harness_capabilities.py` / `db/migrations/env.py` / `pyrefly.toml` / `CODEOWNERS` / `NOTICE` / `session_policies.py` / `lint_workspace_scoped_cache.py` / `dump_openapi.py` | 0 each | — | S22 / S30 / S39 / S39 / S44 / S26 / S39 / — |

### 8.2 Seam-ledger CI check (`coral-fork-guard`)

**Artifacts (New, in an allowed root):**

```yaml
# .coral/upstream.yaml
repo: https://github.com/omnigent-ai/omnigent.git
merged_sha: 2a9cbe2c205e49f6fe2b676f2a61bdeb25d57896
source: main            # or: nightly v0.22.0.dev20261108 (merged at ^1 = ee7a319f7)
merged_at: 2026-11-08
```

```yaml
# .coral/seams.yaml
allowed_roots: [coral/, tests/coral/, tests/stores/coral/, tests/db/coral/, tests/server/coral/,
                tests/runner/coral/, tests/e2e/coral/, web/src/workflows/, .coral/, docs/coral/,
                .github/workflows/coral-]
seams:
  - id: S1
    title: Turn-edge observer registry
    category: upstreamable        # upstreamable | coral-specific | incompatible (Electron-style)
    files: [omnigent/server/session_live_state.py, omnigent/server/routes/_sessions/helpers.py, omnigent/server/app.py]
    tests: [tests/server/test_session_live_state.py]
    phase: 2
    upstream_pr: null
    budget_lines: 40
```

**`coral/fork/check_seams.py` (New) steps:**
1. Read the pin, then `git fetch --no-tags --depth=1 <repo> <merged_sha>` in CI. Require `git merge-base --is-ancestor <merged_sha> HEAD`; otherwise the pin is wrong.
2. Compute `git diff --name-status -M <merged_sha> HEAD`. Every A, M, D or R path must be under `allowed_roots` or listed in some seam's `files`. Fail and print a suggested ledger entry for anything else. Deletions of upstream files are flagged too, which discourages deleting upstream workflows.
3. **Stale entries:** each ledgered file must appear in the diff (warn in a PR, fail on main).
4. **Anchors:** each seam must have at least one `CORAL(<id>)` anchor in its files, and every anchor must map to a known id.
5. **Budget:** `git diff --numstat <merged_sha> HEAD -- <files>` must not exceed `budget_lines`. Warn first, then fail after a grace period.
6. **Commit prefix:** for PR commits touching seam files (`git log <base>..<head> -- <files>`), the subject must match `^CORAL: S\d+[a-z]?:`. This lets the ledger history be generated (DD§4.3).
7. **Emit `MODIFICATIONS.md`** (file → seams → category) as a build artifact for Apache §4(b) and the NOTICE addendum.

**Tests:** `tests/coral/fork/test_check_seams.py` uses a temp `git init` repo in `tmp_path` with synthetic upstream and Coral commits, and covers each failure mode above.

### 8.3 Merge rehearsal job (`coral-upstream-rehearsal`, DD§7.3.6 made concrete)

**Trigger:** schedule daily at about 06:00 UTC (the upstream nightly runs at `30 4 * * *`, `nightly-release.yml:33`), plus `workflow_dispatch(ref)`.

1. **Target.** Fetch upstream `main` and tags. Pick `target = <latest vX.Y.Z.devYYYYMMDD>^1` (green, stamp-free), unless an input ref is given.
2. **Scratch branch.** `git switch -c rehearsal/<date> origin/main` (Coral main). Restore `.git/rr-cache` from `actions/cache` (`git config rerere.enabled true`, `rerere.autoupdate true`). Run `git merge --no-ff --no-edit <target>`; never rebase (DD§17 #1).
3. **Generated-file resolution, scripted.** For conflicts in `uv.lock` run `uv lock`. For `pnpm-lock.yaml` run `pnpm install --lockfile-only`. For `openapi.json` run `uv run python scripts/dump_openapi.py`. For `web/src/themePalettes.generated.css` run `node --experimental-strip-types web/scripts/generate-theme-palettes.mjs`. For the `[project].version` line, take upstream's (Coral's own version lives elsewhere; §9.2). Any remaining conflicted path produces a report artifact listing each file, its seam ids and its 30-day churn, then the job fails and opens or updates an issue.
4. **Gates, in order, fail-fast:**
   - **(a)** `check_seams.py --pin <target>`.
   - **(b)** `pre-commit run --all-files`.
   - **(c)** The `coral.omni` contract suite plus every ledger `tests:` entry, with `-p tests._helpers.required_tests` (skips fail).
   - **(d)** `tests/stores/coral tests/db/coral` on SQLite, Postgres 16 and CRDB 23.2.28 (MySQL optional), including the **ordering test**: populate Coral at the pre-merge schema, run the Omnigent upgrade to the new head, then the Coral upgrade.
   - **(e)** `pytest tests/coral tests/server/coral tests/runner/coral`.
   - **(f)** Web: `pnpm --filter web exec tsc -b` and `vitest run src/workflows`.
   - **(g)** `scripts/dump_openapi.py --check` and the Coral spec check.
   - **(h)** Optional, weekly: E2E-1 and E2E-3.
5. **Outputs.** On green, push `upstream-sync/<date>` and open a PR. A human merges it with a merge commit, and `.coral/upstream.yaml` is updated in the same PR. Persist the rr-cache. Publish a dashboard of conflict counts per seam to drive upstreaming (DD§17 #7).

**Security-fix SLA (DD§17 #6):** a separate `workflow_dispatch` cherry-pick lane for upstream security and auth fixes, with the same gates (a) to (e).

### 8.4 Fork CI hygiene (inherited workflows)

- **Repo-gated and inert in the fork (36):** release, nightly-release, release-omnigent, publish-changelog, polly-review, doc-sync, feature-blog, homebrew-tap-pr, oss-publish-images, benchmark*, and others (grep `github.repository == 'omnigent-ai/omnigent'`, for example `release.yml:66`, `nightly-release.yml:54`, `release-omnigent.yml:56`). Leave the files in place so merges stay clean.
- **Non-gated and using secrets or vars:** `ui-preview` (16), `issue-triage` (15), `security-triage` (12), `issue-prioritization-v2` (11), `ui-snapshot-update` (6), `flake-stress-e2e` (5), `bump-version` (4), `sync-openapi-to-site` (3), `merge-ready` and `maintainer-approval` (2). **Disable** these in repository settings unless Coral wants them. `bump-version` and `sync-openapi-to-site` would act on upstream's process.
- **Cross-repo composite actions are pinned by SHA** (`setup-uv@c144e4b…` ×14, `setup-harness-cli@c76912d…` ×26). They work while upstream stays public. The mitigation is to vendor them under `.github/actions/coral-*` only if upstream access changes; otherwise leave them, to avoid conflicts.
- **The security gate** (`security-gate.yml`, `needs: gate` in `ci.yml:55-59`) evaluates author association on the fork's own PRs. Its behaviour for the fork's org settings is UNVERIFIED and should be checked in the first fork PR.

---

## 9. Packaging, release and rebrand mechanics (non-visual)

### 9.1 Where names live today

| Identity | Location | Notes |
|---|---|---|
| Distribution | `pyproject.toml:6` `name = "omnigent"`, version `:8`, authors "Databricks, Inc." `:12-13` | Lockstep with `omnigent-client`, `omnigent-ui-sdk` and `omnigent-slack` via `==` pins (`pyproject.toml:25-31`; `scripts/update_versions.py:1-48`). Verified by the `version-lockstep` job in `lint.yml`. |
| CLI entry points | `pyproject.toml:409-417` (`omnigent`, `omni` → `omnigent.cli:main`) | `prog_name="omnigent run"` is pinned in places (`omnigent/cli.py:14902-14947`) |
| Update and upgrade | `omnigent/update_check.py:61-66` (`OMNIGENT_NO_UPDATE_CHECK`, `~/.omnigent`, `_DIST_NAME="omnigent"`), `:1622` nightly repo URL, `:1843` `curl https://omnigent.ai/install.sh` | **Must change for any Coral distribution** (S41) |
| State dirs | `omnigent/cli.py:584-600` (`_STATE_DIR = ~/.omnigent`, legacy-rename migration from `~/.omnigents` and `~/.omniagents`); `OMNIGENT_DATA_DIR` and `OMNIGENT_CONFIG_HOME` overrides (`omnigent/config.py:31-33`); 24 files hardcode `".omnigent"` | Upstream's own rename shows a migration pattern (`_migrate_legacy_state_dir`) |
| Env vars | 358 distinct `OMNIGENT_*` names under `omnigent/` | Defer (layer 2) |
| Desktop | `web/electron/package.json` (`productName` "Omnigent", `appId` `ai.omnigent.desktop`, version 0.21.0); CLI discovery `["omnigent","omni"]` and version regex `/\bomni/i` (`web/electron/src/omnigent_cli.js:277, 614`); 23 refs to `ai.omnigent.desktop` or the "Omnigent" product name in Electron src, package.json and the justfile | A distinct `appId` is needed for side-by-side installs |
| Mobile | `web/ios/Omnigent/*`, bundle ids in `Info-*.plist` | Later |
| Web | `branding:` server block (`deploy/README.md:672-690`; `omnigent/server/server_config.py:459-500, 863`) covers app name, heading, logos and `powered_by`. 108 non-test files under `web/src` contain "Omnigent". | Layer 1 is mostly config; changing the hardcoded strings belongs to the UI lane. |
| Docs and examples | `README.md` (10/30d), `CONTRIBUTING.md`, `AGENTS.md` | Coral docs go in `docs/coral/`; leave upstream docs alone |

### 9.2 Recommended layering, as tasks (extends DD§16.3)

| Task | Scope | Acceptance criteria |
|---|---|---|
| **RB-0** Branding config default | Ship a Coral `branding:` default (app_name "Coral", logos, `powered_by` per counsel) via the packaged default config or a Coral server-config overlay. Avoid editing upstream defaults if possible. | `GET /v1/info` returns the Coral brand on a fresh install. No upstream files changed, or one ledgered line. |
| **RB-1a** Isolation without renaming | A `coral` console script, `coral = "coral.cli:main"` (New), sets `OMNIGENT_DATA_DIR` and `OMNIGENT_CONFIG_HOME` defaults to `~/.coral` and `OMNIGENT_NO_UPDATE_CHECK=1` when unset, then delegates to `omnigent.cli:main`. Keep the `omnigent` and `omni` scripts. | Coral and an upstream Omnigent install on one machine use separate `chat.db`, host identity and auth tokens. Add an extension of `tests/test_data_dir_isolation.py:14-22` for the `coral` entry. Any hardcoded `~/.omnigent` path found is listed (24 files to audit). |
| **RB-1b** Distribution rename (decision) | Either keep `name="omnigent"` (internal or fork use only, no PyPI) or rename to a Coral distribution. Renaming needs: the `[project].name` line, S41 (`update_check.py`), the SDK lockstep decision (fork the SDKs or depend on upstream's `omnigent-client`), a Coral release workflow (New), and a Coral `install.sh`. | `omni upgrade --check` never proposes upstream Omnigent. The rehearsal's merge of `pyproject.toml` stays one-line resolvable. |
| **RB-1c** Version scheme | Keep upstream's `[project].version` lineage, which the stamping tools own (DD§17 #5). Carry Coral's product version in `coral/version.py` and expose it in `/v1/info` and `coral --version`. | Upstream "Bump version" commits merge without touching Coral's version. `update_versions.py check` still passes. |
| **RB-1d** Desktop | A distinct `appId` and `productName`. CLI discovery accepts `coral`. The version regex accepts `coral` (S42). | The desktop finds the `coral` CLI and coexists with Omnigent Desktop. |
| **RB-2** Internal identifiers | Deferred: the `omnigent` package, `OMNIGENT_*` variables, `~/.omnigent`, `ai.omnigent.*`. Revisit only if Coral diverges permanently. Reuse the `_migrate_legacy_state_dir` approach. | Not scheduled |

### 9.3 Licensing tasks (DD§16.3)

- **LIC-1** Keep `LICENSE` and `NOTICE` verbatim. `NOTICE` lines 1-3 are the Databricks copyright, and the file has 0 commits/30d. **Append** a Coral addendum section, which Apache §4(d) allows "alongside or as an addendum". The addendum covers Coral's copyright, attribution text such as "based on Omnigent" (§6 permits describing origin), and third-party notices for Coral-added dependencies: `yaml`, `elkjs`/`dagre`, the Newsreader font (OFL), and Elephant-Goldfish personas (Apache-2.0) if reused (DD§15.3).
  *Acceptance:* the `NOTICE` diff vs upstream is append-only, and the guard check enforces "prefix equals upstream NOTICE".
- **LIC-2** Modified-file notices (§4(b)): generate `MODIFICATIONS.md` from the ledger and use `CORAL(Sx)` anchors in each modified file. Counsel must confirm sufficiency.
  *Acceptance:* every ledgered file appears in `MODIFICATIONS.md`, and the check fails if one is missing.
- **LIC-3** Third-party inventory: there is no licence tooling in CI today (grep found none). Add a Coral job listing the licences of Coral-added npm and PyPI dependencies.
  *Acceptance:* the job fails on a disallowed licence class (policy from counsel).
- **LIC-4** DCO: upstream requires sign-off (`CONTRIBUTING.md:395-410`; `DCO`). Decide whether Coral keeps DCO internally. Seams PR'd upstream (S1, S2, S5, S10, S14, S16, S17, S19, S22-S24, S31') need `Signed-off-by`.
- **Counsel questions** (carried from DD§16.3): the "Powered by Omnigent" default, the "Coral" name, the elkjs licence, React Flow attribution, and whether anchor comments satisfy §4(b).

---

## 10. The `workflows` feature flag: lifecycle and tests (S33)

| Step | Concrete change | Test |
|---|---|---|
| Server enum and definition | `Feature.WORKFLOWS = "workflows"` (`omnigent/server/feature_flags.py:23-42`). `FeatureDefinition(feature=WORKFLOWS, description="Coral workflow editor, runs and engine", owner="server", review_by_release=<Coral GA>, frontend_visible=True)`, with `default_enabled` False (`:57-177`). Insert near the top of both lists (§6.3). | `tests/server/test_feature_flags.py:21-50`: add `"workflows": False` to the exact `frontend_dict()` and confirm it is absent from the default enabled set. `:208-215` lifecycle metadata passes automatically. |
| Web key | Add `"workflows"` to `FeatureKey` (`web/src/lib/capabilities.ts:60-74`) | Extend `web/src/lib/capabilities.test.ts:209-219` |
| Routes, nav and palette | `FeatureGatedPage feature="workflows"` (`App.tsx:76`); Sidebar and CommandPalette entries (S34) | Vitest: route hidden when off, rendered when on |
| Server gating | Mount Coral routers and start workers only when enabled. `OMNIGENT_FEATURES=-workflows` is the kill switch; unknown names fail startup (`feature_flags.py:222-265`). | §3.5 lifespan tests |
| Disable semantics (Coral-specific, must be specified) | When off: no new runs; workers stop claiming; existing run rows untouched; run-owned sessions keep working as plain sessions; gates stay pending. When back on: startup reconcile resumes runs. | L2/L4 test "flag off → no claims; on → reconcile resumes" |
| Runner side | Not needed unless engine tools are advertised conditionally. If they are, runner features come from the forwarded `OMNIGENT_FEATURES` (`designs/FEATURE_FLAGS.md:46-52`). | `tests/runner/test_session_orchestration.py:15-25` shows the `runner_features` parametrize pattern |
| Documentation | Add a row to `designs/FEATURE_FLAGS.md` inventory (`:29-40`) | — |
| Removal | At `review_by_release`, make the feature unconditional (`designs/FEATURE_FLAGS.md:42-44`). Upstream does not enforce this: 9 flags have `review_by_release ≤ 0.21.0` while main is 0.22.0.dev0. | Coral-local guard test: fail if Coral's version reaches `review_by_release` and the flag still exists (`tests/coral/test_flag_lifecycle.py`) |

**Open decision:** `review_by_release` uses upstream's version numbers, so in a fork it should name a Coral release. RB-1c's separate Coral version makes the comparison test possible.

---

## 11. Fork-operations workstream: tasks with acceptance criteria

| ID | Task | Depends on | Acceptance criteria |
|---|---|---|---|
| FO-1 | Pin file `.coral/upstream.yaml` and ledger `.coral/seams.yaml`, seeded with S1-S45 from DD§4.3 plus §5 of this doc, each with `files`, `tests`, `category`, `phase` and `budget_lines` | — | Ledger schema validated by a unit test. Every DD seam present. Owners assigned in CODEOWNERS. |
| FO-2 | `coral/fork/check_seams.py` plus `coral-fork-guard.yml` (§8.2) | FO-1 | Fails on an unledgered upstream path, a stale entry (on main), a missing anchor or an over-budget seam. Commit-prefix check on PRs. `MODIFICATIONS.md` artifact. Temp-git-repo tests cover each failure. |
| FO-3 | Tooling roots: C1-C7, C9, C10 (S29, S31', S39, S39b-d) | — | `pyrefly check` covers `coral/`. `ruff` isort treats `coral` as first-party. `tests/coral` runs in its own CI group. DB lanes keep `coral_alembic_version` between tests (proved by a two-test module under `tests/stores/coral/` on the Postgres lane). |
| FO-4 | `coral-upstream-rehearsal.yml` (§8.3) | FO-2, the L3 contract suite, the L2 ordering test | A daily run on `nightly^1`. Generated-file conflicts auto-resolve. A conflict report lists files with seam ids. Green runs open an `upstream-sync/<date>` PR. rr-cache persisted. |
| FO-5 | Security-fix cherry-pick lane | FO-4 | Dispatch with upstream SHA(s). Same gates. SLA documented (days). |
| FO-6 | Workflow and Dependabot hygiene (§8.4) plus branch protection | — | Documented list of enabled and disabled inherited workflows. Required checks configured. Dependabot is off for upstream manifests. |
| FO-7 | Merge playbook `docs/coral/UPSTREAM_MERGES.md` | FO-4 | Covers: target selection (`nightly^1`), merge-not-rebase, regenerate rules, rerere review, seam re-anchoring, the ledger pin update, and who approves |
| FO-8 | Upstreaming pipeline for generic seams | FO-1 | Per seam: an upstream PR link in the ledger, DCO sign-off, and a ledger shrink tracked per release |
| FO-9 | Coral docs placement | — | Move the three root design docs to `docs/coral/` (`ci.yml` and the E2E workflows ignore `docs/**`). Add nested `coral/CLAUDE.md` with the Coral dev rules (D8, import boundary, anchors). |
| TI-1 | Test scaffolding: directories in §3.0, conftests (Coral store fixtures; `_sqlite_db_template` override including the Coral schema), import-boundary test | FO-3 | `just coral::test` green on SQLite. Each new conftest documented in a Test Plan, per repo `CLAUDE.md`. |
| TI-2 | L1 invariant and fuzz harness (seeded) plus exhaustive Simulate | Engine reducer | I1-I8 asserted. Seed reproduction in the failure message. D§5.6 and deadlock regressions. |
| TI-3 | L2 fault-injection and contention suite | Stores | DD§19 crash and contention list green on all 4 backends |
| TI-4 | L3 `coral.omni` contract suite | Facade | One test per facade function, using in-process `app` plus `CapturingRunnerClient`. Run first in the rehearsal. |
| TI-5 | Coral OpenAPI artifact and drift test | API | Drift test mirrors `tests/server/test_openapi_drift.py`. Regeneration command printed on failure. |
| TI-6 | E2E-1 and E2E-2 (Tier B), then E2E-3 and E2E-4 (Tier C) | Phase 2 seams | Pass in the E2E lane. Skip cleanly when a CLI is missing (`tests/e2e/conftest.py:71-87`). |
| TI-7 | Bench probes, feature-map rows, `coral-bench.yml` live job | S22 | Offline probe tests in `misc`. `test_verify_omnigent_feature_map.py` green. Weekly live matrix artifact per pinned CLI. |
| RB-0…RB-1d, LIC-1…LIC-4 | §9 | — | As specified |
| FLAG-1 | `workflows` flag (§10) | — | Tests in §10 green. Kill switch verified via `/v1/info` and an actual route call. |

Dependency-aware order for parallel pickup:
- **Wave 1:** FO-1, FO-3, FO-6, FO-9, TI-1, FLAG-1, LIC-1.
- **Wave 2:** FO-2, TI-2, TI-3, RB-1a, RB-1c.
- **Wave 3:** TI-4, TI-5, FO-4, FO-7.
- **Wave 4:** TI-6, TI-7, FO-5, FO-8, RB-1b, RB-1d, LIC-2 to LIC-4.

---

## 12. Risks (this lane)

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| T1 | Seams in the hottest files (orchestration.py at 77/30d, bridge.py at 83, app.py at 64, connect.py at 62) conflict on most weekly merges | High / Medium | One-line calls with logic elsewhere (§6.3). Daily rehearsal with rerere. Upstream the generic seams first (S1, S5, S10 are all upstreamable). |
| T2 | No deterministic `claude-sdk` fake: Phase 2's first mode depends on live, credentialed runs for turn-end and tool-gating evidence | Medium / High | Tier B (openai-agents) for engine mechanics. A weekly live bench with an API key. Investigate a mock `ANTHROPIC_BASE_URL` for claude-sdk (UNVERIFIED). |
| T3 | Flaky concurrency tests on shared CI runners | Medium / Medium | `budget()` and `poll_until`. Barrier-based deterministic interleavings. Avoid sleep-then-assert (lint-enforced). Assert final states, not timings. |
| T4 | DB-lane truncation without S31 corrupts Coral's version state | High (certain) / High | FO-3 before any Coral store test lands |
| T5 | Feature-map test breaks when probes, UI areas or CLI commands are added | High / Low | S23b rows in the same PR. The "Not yet mapped" list is acceptable as a stopgap. |
| T6 | Coexistence: shared `~/.omnigent`, the "newer DB" lockout, and `omni upgrade` installing upstream | Medium / High (user data) | RB-1a isolation. S41. Never point Coral at an upstream-used `chat.db`. |
| T7 | `@xyflow/react` OOM in jsdom tempts devs to skip canvas tests | Medium / Medium | Pure-module architecture for layout and sync (§3.11). Code review rule. |
| T8 | Inherited secret-using workflows misfire in the fork, or fail noisily | Medium / Low | FO-6 |
| T9 | Generated-file conflicts (`openapi.json`, lockfiles, palette CSS) consume merge time | High / Low | Scripted regeneration in the rehearsal. Never hand-merge generated files. |
| T10 | Dependency floors: Coral cannot run `check-internal-mirror` (Databricks proxy) | Low / Low | Coral adds only Coral-owned dependencies, with old-enough floors. The `young-dependency-floor` lint still runs. |
| T11 | Coverage report drops Coral code silently (`--cov=omnigent`) | Medium / Low | C4, or a Coral-only coverage job |
| T12 | Upstream deletes or renames test primitives Coral imports (`tests/server/conftest.py` `ControllableMockClient`, `tests/e2e/conftest.py` helpers, resilience lab). Churn: `tests/_helpers` 25/30d, `mock_llm_server.py` 5, server conftest 1. | Medium / Medium | Treat imported test primitives as part of the contract. The rehearsal runs Coral tests first. Prefer catalogued `tests/_helpers` primitives. |

---

## 13. Open questions and decisions needed

1. **Distribution and CLI rename timing (RB-1b).** Stay `omnigent` (fork-internal) through Phase 2, or ship a `coral` distribution earlier? This decides whether S41 and S42 are Phase 1 work.
2. **Coral version scheme** (RB-1c) and what `review_by_release` means for the `workflows` flag.
3. **Isolated dev DB for Coral schema work** (D8): approve an exception to the repo `CLAUDE.md` "shared `~/.omnigent/chat.db`" rule for `coral/` development.
4. **The merge target policy**: daily `nightly^1` (recommended), weekly, or release-aligned merge-base? Who owns rehearsal triage?
5. **A credentialed live-bench budget.** Which modes and CLIs go in the weekly matrix, and whose API key pays (vendor terms, DD§16)?
6. **Hypothesis**: adopt it as a test dependency, or keep seeded stdlib fuzzing?
7. **Layout library** (elkjs EPL-2.0, already transitive, vs dagre MIT) and the font licence. Counsel needed.
8. **Whether Apache §4(b)** is satisfied by anchor comments plus a generated `MODIFICATIONS.md`. Counsel needed.
9. **Whether to keep DCO** for Coral-internal contributions.
10. **Whether claude-sdk honours a mock base URL**, which would give a Tier C claude-sdk lane. Needs a spike; UNVERIFIED.
11. **Product requirements source** (D2): until `coral-requirements.md` exists, should test acceptance criteria trace only to D§ and DD§?

---

## Appendix A. Command evidence (read-only)

- `git rev-parse HEAD` → `2a9cbe2c205e49f6fe2b676f2a61bdeb25d57896`.
- `git merge-base --is-ancestor v0.19.0|v0.20.0|v0.21.0 HEAD` → all false. `git log --oneline v0.21.0 ^HEAD` → 4 commits (3 release stamps plus 1 backport). `git log --grep '#12711' HEAD` → `c42c3c33e` on main.
- `git log -3 v0.22.0.dev20261108` → `1dd1a65d2 nightly: …` on top of `ee7a319f7` (main). `git show --stat` → 6 version files.
- `git log --since=2026-10-09 --merges --oneline | wc -l` → 0. `git log --since=2026-10-09 --until=2026-11-09 --oneline HEAD | wc -l` → 1510.
- `ls omnigent/db/migrations/versions/*.py | wc -l` → 121. Migration commits in the window → 9.
- Inherited workflows: `grep -l "github.repository == 'omnigent-ai/omnigent'" .github/workflows/*.yml | wc -l` → 36.
- Brand surface: `grep -rhoE "OMNIGENT_[A-Z0-9_]+" omnigent | sort -u | wc -l` → 358. `grep -rl '"\.omnigent"' omnigent | wc -l` → 24. `grep -rl "Omnigent" web/src` excluding tests → 108.
