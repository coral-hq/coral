# Staff Engineer critique of master feature list v1

Lens: implementability at the code level. Repository `omnigent-ai/omnigent` at `2a9cbe2c2`, read-only. Date 2026-11-11. Inputs: `decomposition/master_v1.md` and `.json`, `investigation/gap_analysis.md` (backbone), `investigation/eng_testing.md`, `investigation/adversarial.md`, `tests/README.md` and `tests/_helpers/README.md`. The scratch script used to recompute critical paths is `wf2/eng_critique/cp.py`.

## 1. Verdict

The plan is close to buildable. Contracts, seam ownership, spikes and cut lines are well structured, and 33 of 35 code references I checked hold at HEAD. Two things are wrong as written:

1. **The walking skeleton cannot start early.** SES-05 has 12 hard dependencies, including SES-06 and DUR-05. By the plan's own rules it starts at week 16.5 of an 18.5-week M2 path.
2. **K13's session-shell backend cannot do salvage and reset where SES-06 needs them.** The environment shell needs a live session with `os_env`, and the restart order puts salvage and reset before the new session exists.

The major issues cluster in four areas:

- **Over-strict hard dependencies.** Converting six of them to soft dependencies through existing contracts gives M1 11.5 weeks (from 13.5), M2 16.0 (from 18.5) and M4 18.5 (from 23).
- **Hot-file exposure.** Some of it can be avoided outright: S68 through `pr_observer.py`, native call sites moved to their first needers, and S1b reduced.
- **CI on old runner builds.** The inherited e2e gate and the 12-hourly cross-version compat sweep will collect `tests/e2e/coral/` and run it against old runner and host builds.
- **The migration train.** DUR-01 designs six other features' tables in PH1, and creates `coral_alerts` before its contract K19 exists.

## 2. Code spot-checks at HEAD (35 references)

| # | Claim in master or gap analysis | Result |
|---|---|---|
| 1 | Roots-only relaunch, `app.py:4273` | Holds: `roots = [conv for conv in held if conv.kind != "sub_agent"]` |
| 2 | Recovery skips `host_id` children, `child_session_recovery.py:164` | Holds: `or row.host_id is not None` |
| 3 | Parent wake after 120 s, `subagent_block_notifier.py:55, 297-300` | Holds |
| 4 | Reaper guard counter for host-owned subprocesses, `connect.py:1417-1423` | Holds (`_owned_subprocess_ops`) |
| 5 | `fs_request`/`fs_write` not guarded, `connect.py:6027-6034` | Holds: plain `asyncio.to_thread` |
| 6 | Session shell is owner-only, `routes_resources.py:3257-3297` | Holds. It is a route closure with `request: Request`; `_proxy_fs_response` (`:2480`) lives inside the route factory, so it is not importable. |
| 7 | Runner shell returns `exit_code` | Holds (`runner/app.py:8296-8350`). It calls `_require_os_env(session_id)`, so sessions without `os_env` cannot run it. |
| 8 | Hard-wired idle → succeeded, `helpers.py:5158-5159` | Holds |
| 9 | Single scheduled hook in `session_live_state.configure` | Holds |
| 10 | Tool groups hand-registered, `manager.py:159-193` | Holds |
| 11 | S68 sites `tool_dispatch.py:7297-7307`, `_executor_adapter.py`, `bridge.py:8233-8250`, `tools/mcp.py:717-726` | Holds. All four already call `omnigent.runner.pr_observer.observe_tool_completion` or `observe_hook` (lines 7298, 1173, 8235, 717). |
| 12 | `sys_os_shell` result carries `exit_code` | Holds: a JSON envelope with `exit_code` (`pr_observer.py:433-443`) |
| 13 | `sys_advise_models` inline intercept, `orchestration.py:13058-13069` | Holds |
| 14 | Server sees MCP tool results before returning them, `orchestration.py:13239-13258` | Holds (TOOL_RESULT policy on the proxied output) |
| 15 | Startup dispatch handle only when `startup_inputs` exists, `app.py:3815-3819` | Holds |
| 16 | `_post_event_impl` accepts only Request, runner and startup contexts | Holds (`routes_events.py:1215`; line numbers drifted from the gap's `:1019, :1652`) |
| 17 | Single elicitation observer slot, `pending_elicitations.py:66-87` | Holds |
| 18 | `ELICITATION_RESOLVE_LEVEL = LEVEL_EDIT`, `routes_elicitations.py:55-61` | Holds. The comment says raising it to owner needs a "waiting for the owner" UI first. |
| 19 | `omni` palette label "Omnigent", `themePalette.ts:217-218` | Holds |
| 20 | `DEFAULT_APP_NAME`, `branding.ts:4-5` | Holds |
| 21 | `include = ["omnigent*"]`, `pyproject.toml:460` | Holds |
| 22 | Truncation keeps only `alembic_version`, `tests/conftest.py:736` | Holds |
| 23 | CLI never passes `extra_routers`; mounted at `app.py:5308-5311` | Holds |
| 24 | Session delete removes the worktree, `routes_events.py:4166-4189` | Holds, but narrower: only with `delete_branch=true` and a server-created worktree |
| 25 | Framework instructions in `prompt.py:62-87` | Holds. `prompt.py:96-98` states the rule: an open-ended list must become a structured `FrameworkInstructions` value. |
| 26 | Closed 4-kind Inbox union, `InboxPage.tsx:189-193` | Holds |
| 27 | Provider mount point, `main.tsx:166-172` | Holds |
| 28 | S1 bypasses, `orchestration.py:4131-4152, 13700-13708` | Holds |
| 29 | `_resolve_elicitation`, `orchestration.py:2400` | Holds |
| 30 | claude-sdk strips `ANTHROPIC_API_KEY`, `claude_sdk_executor.py:2091-2118` | Holds |
| 31 | 18 `_publish_status` sites (S1b) | Holds: 11 in `orchestration.py`, 4 in `routes_events.py`, 2 in `helpers.py`, 1 in `startup_inputs.py` |
| 32 | `yaml` 2.9.0 already locked; React Router 7.18 | Holds (`pnpm-lock.yaml:9506`; `react-router-dom` 7.18.4). `@dagrejs/dagre` is not present. `elkjs@0.11.1` is already locked transitively (`pnpm-lock.yaml:5721`). |
| 33 | DB lanes run Coral store tests | Holds: `ci.yml:264, 315` run `pytest tests/stores tests/db`, so `tests/stores/coral/` is collected on Postgres, CockroachDB and MySQL |
| 34 | EXT-05 path `omnigent/scheduled/` | **Wrong.** It is `omnigent/server/scheduled/`. |
| 35 | SES-07 path `omnigent/server/pane_reaper.py` | **Wrong.** It is `omnigent/terminals/pane_reaper.py`. |

Also: `own_runner` (TLD-02, SPK-02, SES-03, SES-06) is not a code concept. A child is independent when it has its own `host_id` (`app.py:4594-4597`, `is_independent`). The roadmap should define the term that way.

## 3. Hot upstream files touched by more than one feature

The commit counts cover 2026-10-12 to 2026-11-11. "Same phase" marks concurrent pairs.

| File | 30-day commits | Features (phase: seams) | Proposed landing order |
|---|---|---|---|
| `omnigent/harnesses/claude_native/bridge.py` | 82 | EVD-02 (PH2: S68 native site), RUL-04 (PH3: S14) | Put S68 in `pr_observer.py` (ENG-08), so only RUL-04 touches this file. |
| `omnigent/server/routes/_sessions/orchestration.py` | 73 | SES-02 (PH1: S1 bypasses, S43, S1b ×11), TLS-01 (PH1: S10), GTE-01 (PH2: S6b), EVD-02 (PH2: S69a). Same phase: SES-02 with TLS-01, and GTE-01 with EVD-02. | SES-02 S1 and S43 → TLS-01 S10 → GTE-01 S6b → EVD-02 S69a. S1b reduced to two or three sites. |
| `omnigent/server/app.py` | 63 | FND-02 (PH1: S32), SES-02 (PH1: S41). Same phase. | FND-02 first, in week 2-3, then SES-02. |
| `omnigent/runner/app.py` | 60 | SES-02 (PH1: S43), SES-07 (PH4: S27 retest), HRN-06 (PH5: S19). **Missing from the master's train table.** | SES-02 → SES-07 → HRN-06 |
| `omnigent/host/connect.py` | 58 | WSP-01 (PH2: S71), WSP-02 (PH4: S40), EXT-03 (PH6: S74) | Land S71 standalone in PH1 (ENG-14). |
| `omnigent/server/routes/_sessions/helpers.py` | 52 | SES-02 (PH1: S1, S43, S1b), TLS-01 (PH1: S49), HRN-03 (PH3: S3, S45), HRN-05 (PH5: S62), EXT-04 (PH6: S26). Same phase: SES-02 with TLS-01. | SES-02 → TLS-01 → HRN-03 → HRN-05 → EXT-04 |
| `omnigent/runner/native/orchestration.py` | 51 | TLS-01 (PH1: S11, S12 native), HRN-03 (PH3: S64) | Move S11 and S12-native into HRN-03, so one feature owns this file (ENG-10). |
| `omnigent/server/routes/sessions/routes_events.py` | 39 | SES-02 (PH1: S42), GTE-01 (PH2: S6a), EVD-02 (PH2: S69b), HRN-03 (PH3: S45), HRN-05 (PH5: S2) | SES-02 → GTE-01 → HRN-03 (S45, plus S69b moved here) → HRN-05 |
| `omnigent/harnesses/codex_native/app_server.py` | 33 | TLS-01 (PH1: S11 Codex site), HRN-05 (PH5: S15) | Move the Codex site into HRN-05. |
| `omnigent/server/schemas.py` | 31 | SES-07 (PH4: S25), WSP-04 (PH6: S28) | Serial; different phases |
| `omnigent/runner/tool_dispatch.py` | 24 | TLS-01 (PH1: S8, S9), EVD-02 (PH2: S68) | TLS-01 S8 only; S9 moves to HRN-03; EVD-02 has no edit here (ENG-08). |
| `pyproject.toml` | 23 | FND-01 (PH0: S29), OPS-03 (PH1: console script) | FND-01 → OPS-03 |
| `omnigent/inner/claude_sdk_executor.py` | 19 | HRN-02 (PH2: S13, S63, conditional S21), HRN-04 (PH3: S24) | HRN-02 → HRN-04 |
| `web/src/pages/InboxPage.tsx` | 11 | BRD-02 (PH1: S84), GTE-02 (PH2: S37, about 80 lines) | BRD-02 → GTE-02 through an inbox-kind registry (ENG-22) |
| `omnigent/inner/codex_executor.py` | 10 | HRN-04 (S24 Codex branch, which the text says lands with HRN-05), HRN-06 (S18-S20, S61, S67) | One owner (HRN-06); the S24 Codex branch lands with HRN-05 |
| `omnigent/runtime/policies/builder.py` | 6 | RUL-01 (PH1: S52), RUL-05 (PH5, listed in its paths) | RUL-05 should use the S52 provider with no new edit. The table says "RUL-01 only", which contradicts RUL-05's paths. |
| `omnigent/server/routes/builtin_agents.py` | 6 | PRF-01 (S54), PRF-02 (S66), EXT-04 (S53) | Serial; low churn |

Recommendation: name one seam-train owner in WS-INTEGRATION. That person lands every hot-file seam PR serially, dark and before the feature logic that uses it, and rebases each open seam PR on the daily `nightly^1` rehearsal.

## 4. Features that cannot land a first independently mergeable PR as written

These features hard-depend on unfinished work in the same phase, so their first PR waits:

- **SES-05.** It depends on 11 same-phase features and starts at week 16.5. This is the skeleton contradiction (ENG-01).
- **WSP-03.** It depends on WSP-02, EVD-04, TLS-04 and ENG-08, all PH4. Merge ops could be built against the K20 fake (ENG-04).
- **SES-06** waits on SES-04 and DUR-05; **SES-04** waits on SES-03; **EVD-02** waits on WSP-01. All three can build against FakeOmni, K5 and temp git repos (ENG-04).
- **WEB-03** waits on all of WEB-02, including the YAML editor that is WEB-02's own cut line (ENG-13).
- **HRN-03** waits on RUL-04, and **RUL-02** waits on EVD-02. RUL-02 only consumes K11 (ENG-04).
- **Natural tails, which are acceptable:** WEB-06 → RUL-02, WEB-07 → PRF-02 and WEB-09 → WEB-08.

## 5. Features that need a merge-dark (flag or gate) strategy

Today the only gate is CoralGate, which turns all of Coral on or off. Proposed gates:

| Gate | Features | Why |
|---|---|---|
| Sub-feature map in `GET /v1/coral/info`, Coral-owned: `editor`, `canvas_edit`, `claude_native_steps`, `codex_steps`, `webhooks`, `budgets`, `takeover`, `restart_from_node` | WEB-11 (proposed editor split), WEB-08, WEB-09, HRN-03, HRN-05, HRN-06, GTE-03, RUL-05, SES-07, ENG-10 | Partly built desks and modes must merge without appearing in pickers or desks. |
| Opt-in no-op: the provider acts only when `params.coral` or `coral.run_id` is present, with an O(1) fast-path test | TLS-01 (S50 is loaded by entry point in every process, because coral ships in the same wheel), RUL-01 (S52 runs on every policy build) | `/mcp` rebuilds the policy engine on every tool call (`eng_testing.md` §3.6). |
| Runner and host capability tokens | SES-02 (S43), TLS-01 (S8), EVD-02 (S69a), WSP-01 (S72), WSP-02 (K20; already has one) | The compat sweep pairs new servers with old runners and hosts (ENG-03). |
| Label-keyed behaviour that never affects non-Coral sessions | GTE-02 (S36), HRN-02 (S13), RUL-04 (S14), PRF-01 (S54) | Already keyed. Add one regression test per seam that a non-Coral session is unchanged. |

## 6. Migrations

K5 and the single-head train check are good. Problems:

- **DUR-01 designs integration tables before their owners and the ADRs.** It lands `coral_0002_integration` in PH1, covering session bindings, the stable_id map, step agents, alerts, questions, repo bindings, command patterns and command observations. The six owning features are in PH2, and ADR-05 and SPK-04 come before them.
- **`coral_alerts` predates its contract.** The table is created by DUR-01 in PH1, but its contract K19 is the first PR of GTE-02 in PH2.
- **Several features need tables but name no migration:** GTE-03 (channels, deliveries), ENG-09 (saved blocks), EVD-04 (check runs, JUnit reports), GTE-04 (push subscriptions), EXT-01 (suggestions) and EXT-04 (run grants).
- **Only three features name a migration:** DUR-01, PRF-02 and ENG-10.
- **Developer databases make bad early schemas expensive.** The repo CLAUDE.md mandates the shared `~/.omnigent/chat.db` for development, so merged migrations reach those databases. A table designed too early cannot be edited in place.

Proposal (ENG-06): DUR-01 ships K5 and `coral_0001` only. Every other table is the standalone first PR of its owning feature, and the roadmap carries a migration-train table listing migration, owner, phase and prerequisite.

## 7. Test strategy at the lowest reliable layer

Most engine and store features are at the right layer:

- L0 and L1 pure tests for ENG-*;
- L2 in `tests/stores/coral/`, which the DB lanes already collect.

Gaps:

- **Seam tests are in the wrong place.** Seam features list only `tests/coral` paths and journey-level proofs. `tests/README.md` places component tests next to the component, and `eng_testing.md` §3.6-3.9 already names the nearest scenario for each seam (ENG-12).
- **CI will run Coral E2E against old runners.** `tests/e2e/coral/` is collected by `.github/actions/e2e-run/action.yml:225` (`uv run pytest tests/e2e/`), so it runs in the normal e2e gate. It also runs in `.github/workflows/server-compat.yml`, which crosses every server version with every runner and host version every 12 hours. The fixtures live in `tests/e2e/conftest.py`, so moving the directory would lose fixture inheritance. A Coral conftest skip on a capability token is the clean fix (ENG-03).
- **The M2 exit gate is non-deterministic.** A credentialed nightly that must pass "five in a row" depends on a real model and on OQ-51 (ENG-18).
- **E2E-5 sits above its natural layer.** It asserts reducer and store properties (ENG-25).
- **Web features do not say which layer tests what.** xyflow runs out of memory in jsdom, and Monaco needs a browser. Each web feature should state which assertions are vitest pure-module tests and which run in the CI-only `tests/browser_ui/workflows/` lane (ENG-26).

## 8. Critical path, recomputed

Weights: S=1, M=2, L=4.5 single-owner weeks, hard dependencies only, cumulative per milestone. Changes modelled:

- ENG-04→ENG-02 soft;
- SES-04→SES-03 soft;
- SES-06→SES-04 and SES-06→DUR-05 soft, with a hard dependency on DUR-03 instead;
- EVD-02→WSP-01 soft, with a hard dependency on the new S71 feature;
- RUL-02→EVD-02 soft, with a hard dependency on EVD-01;
- WSP-03 keeps only WSP-02 as a hard dependency;
- DUR-03 and DUR-05 hard-depend on FND-04, and FND-04 hard-depends on FND-03;
- SES-05 split into a skeleton and an acceptance lane;
- WSP-01 split into S71, WSP-01 and WSP-06.

| Milestone | v1 | Proposed | Proposed path |
|---|---|---|---|
| M1 | 13.5 | 11.5 | FND-01 > ENG-01 > ENG-04 > ENG-05 > ENG-07 |
| M2 | 18.5 | 16.0 | FND-01 > ENG-01 > ENG-04 > TLS-02 > TLS-03 > SES-08 |
| M4 | 23.0 | 18.5 | FND-01 > FND-03 > DUR-01 > PRF-01 > RUL-03 > ENG-09 |

The walking skeleton can then start at week 7 instead of week 16.5.

## 9. Issues (prioritized)

### ENG-01 (blocker, split). SES-05 is not a walking skeleton

- **Evidence.** SES-05 hard-depends on FND-04, SES-04, SES-06, TLS-02, TLS-03, GTE-01, DUR-05, EVD-02, WSP-01, PRF-01, HRN-02 and API-02. Its earliest start is week 16.5 of 18.5, yet section 0 calls it "PH2's first integration target". The slice decomposition (`decomp_slice.md:327`) had hard dependencies on skeleton slices only; merging it with the acceptance lane (decision 15) produced the contradiction.
- **Change.** Split it in two:
  - **SES-05 Walking skeleton** (M, PH2 first target): hard dependencies FND-04, SES-02, TLS-01 and DUR-03; soft dependencies on the skeleton slices.
  - **New SES-08 M2 acceptance lane**: today's hard set plus SES-05.

  Make "skeleton slice" a named first deliverable, with its own proof line, in ENG-04, SES-03, SES-04, TLS-02 and GTE-01.

### ENG-02 (blocker, contract). K13's session-shell backend has no session to run in when salvage and reset are needed, and the engine commit races the agent's turn

- **Evidence.**
  - The runner shell requires `os_env` (`runner/app.py:8306`).
  - The server route is an owner-only, Request-bound closure (`routes_resources.py:3264-3297`).
  - The seeded orchestrator has no `os_env`, and reviewers are `write_paths: []`.
  - SES-06 orders the restart as "stop, bump generation, salvage, reset, new session", so after a runner loss there is no session in which to salvage or reset.
  - WSP-01 commits "at accepted handoffs", but `coral_submit_handoff` runs inside the agent's turn, and the agent can keep editing after it.
  - A linked worktree's gitdir is in the main repo's `.git/worktrees/`, outside the worktree (spike 8).
- **Change.**
  - K13 v1 gets an "ops host" rule: ops run through the slot's current writable step session, only at a detected turn end.
  - SES-06 restart order becomes: stop the old session → create the new one without a brief → salvage and reset through it → brief.
  - WSP-01 commits at the accepted handoff's turn end.
  - K4 adds a request-free runner shell call with a contract test.
  - SPK-04 adds two probes, "commit under the step sandbox from a linked worktree" and "ops with no live session", and pre-plans the minimal S40 commit, salvage and reset slice as the triggered contingency, with a named owner.

### ENG-03 (major, risk). The inherited e2e gate and the compat sweep will run Coral E2E against old runners and hosts, and wire seams have no capability tokens

- **Evidence.** `e2e-run/action.yml:225` runs `pytest tests/e2e/`. `server-compat.yml` sweeps every pair of server and runner/host versions every 12 hours. The host `CAP_*` precedent is in `frames.py:76-88`. The wire seams S8, S43, S69a and S72 have no skew rule; only WSP-02 has one.
- **Change.**
  - Give each wire-seam group a runner or host capability token, owned by the seam feature.
  - API-02's preflight refuses a run on a host that lacks a needed token.
  - `tests/e2e/coral/conftest.py` skips when the pinned runner lacks the token.
  - Drop Tier B from `coral-e2e.yml`, since the e2e gate already runs it, and keep the workflow only for the credentialed nightly.
  - OPS-02 adds a Coral row to the compat review.

### ENG-04 (major, dependency). Over-strict hard dependencies serialize the critical paths

- **Change.** Each of these can build against an existing contract or fake:
  - ENG-04→ENG-02 becomes soft (K1 golden compiled-IR fixtures).
  - SES-04→SES-03, SES-06→SES-04 and SES-06→DUR-05 become soft (FakeOmni K4, K18 and K5).
  - EVD-02→WSP-01 becomes soft (temp git repos; S71 stays hard).
  - RUL-02→EVD-02 becomes soft, and RUL-02→EVD-01 becomes hard (K11 only).
  - WSP-03 keeps only WSP-02 as a hard dependency.

  Section 8 shows the effect.

### ENG-05 (major, dependency). Missing hard edges

- **Evidence.** Decision 14 says DUR-03 and DUR-05 use FND-04's fault and contention helpers, but neither declares the edge. FND-04's Coral-aware SQLite template needs FND-03, which is only a soft dependency. SPK-01 has zero hard dependents, so nothing waits on the decisions it records.
- **Change.**
  - Add hard edges DUR-03→FND-04, DUR-05→FND-04 and FND-04→FND-03.
  - Tie individual decision records to the merges they gate:
    - the K1, K2 and K14 freeze waits on the OQ-3, OQ-12 and OQ-19 records;
    - the HRN-02 merge waits on the OQ-28 vendor answer;
    - the FND-02 and API-01 freeze waits on OQ-36 and OQ-45.

### ENG-06 (major, contract). The migration train is front-loaded and K19 is inverted

See section 6.

- **Change.** DUR-01 ships K5 and `coral_0001` only. These features each land their tables as a standalone first migration PR:
  - SES-04: session bindings and the stable_id map;
  - PRF-01: step agents;
  - GTE-02: alerts, together with K19;
  - TLS-03: questions;
  - WSP-01: repo bindings;
  - EVD-02 and EVD-03: command patterns and command observations.

  Add a migration-train table that also covers GTE-03, ENG-09, EVD-04, GTE-04, EXT-01 and EXT-04.

### ENG-07 (major, reorder). The hot-file train is incomplete

- **Evidence.** Section 3. `runner/app.py` (60 commits in 30 days) is missing from the train table. Same-phase pairs collide on `orchestration.py`, `helpers.py` and `app.py` in PH1, and on `orchestration.py` and `routes_events.py` in PH2. The `builder.py` row contradicts RUL-05's paths.
- **Change.** Publish the per-file landing order from section 3, with one seam-train owner, and land seam PRs dark first.

### ENG-08 (major, boundary). S68 and S69 can avoid four hot call sites and close an ordering race

- **Evidence.** All four sites already call `pr_observer.observe_tool_completion` or `observe_hook`, and `pr_observer.py` has 5 commits in 30 days. The `sys_os_shell` envelope carries `exit_code`. The server proxies claude-sdk MCP calls and sees the result synchronously (`orchestration.py:13230-13258`).
- **Change.**
  - EVD-02 adds the observer fan-out at the top of `observe_tool_completion`, before its `if not successful` return.
  - Use only S69a for claude-sdk.
  - Move S69b and the bridge site to HRN-03.
  - Add to K11: "an observation is durable before the tool result returns to the agent". Without that rule, a submit right after a test run can be rejected as missing evidence.

### ENG-09 (major, scope). S1b means 18 edits in hot files

- **Evidence.** There are 18 server-side `_publish_status` sites, 11 of them in `orchestration.py`. This is not a one-line registry call.
- **Change.** Add an optional `origin` keyword argument with a default. SES-02 sets it only where SES-04's turn-end rule needs it: the archive idle edge, the runner-disconnect edge and the relay turn end. The other sites go to an upstream PR, and the ledger lists them as deferred.

### ENG-10 (major, boundary). TLS-01 lands native and Codex sites two phases early

- **Evidence.** S9, S11 and S12-native go into `native/orchestration.py` (51 commits) and `app_server.py` (33) in PH1, but their first consumers are HRN-03 (PH3) and HRN-05 (PH5). That breaks the first-needer rule and leaves untested code in hot files. S12 also makes the framework-instruction list open-ended, which `prompt.py:96-98` and CLAUDE.md say requires a structured `FrameworkInstructions` value.
- **Change.** TLS-01 keeps S7, S8, S10, S12-headless, S49 and S50. S9, S11 and S12-native move to HRN-03, and the Codex S11 site moves to HRN-05. TLS-01 introduces `FrameworkInstructions` in `prompt.py`.

### ENG-11 (major, risk). No merge-dark strategy

- **Change.** As in section 5:
  - a `/v1/coral/info` sub-feature map read by CoralGate, the pickers and the API;
  - S50 and S52 no-op without opt-in, with fast-path tests;
  - capability tokens.

  Each listed feature names its gate key and flips it at its exit.

### ENG-12 (major, evidence). Seam tests belong next to the Omnigent component

- **Change.** Each seam feature's first proof is a component test in the nearest existing scenario:

  | Seam | Test location |
  |---|---|
  | S1 | `tests/server/test_session_live_state.py` |
  | S5 | `tests/runtime/test_pending_elicitations.py`, `tests/runtime/test_subagent_block_notifier.py` |
  | S6 | `tests/server/integration/test_sessions_elicitation_api.py` |
  | S10 | `tests/server/routes/test_sessions_mcp_proxy_policy_retry.py` |
  | S8 | `tests/runner/test_scheduled_task_tool_dispatch.py` |
  | S52 | `tests/runtime/policies/` |
  | S54 | `tests/stores/test_agent_store.py` |
  | S71, S72 | `tests/host/test_connect.py`, `test_git_worktree.py`, `test_frames.py` |

  Journey proofs move to SES-05 and SES-08. The ledger also covers these upstream test files.

### ENG-13 (major, split). WEB-02 contains its own cut line

- **Change.** Split it in two:
  - **WEB-02**: desk, library, upload and import, and the server problem list (M).
  - **New WEB-11**: the YAML editor, with Monaco via `monacoSetup`, `yaml` CST patches, markers and the 412 dialog (M).

  WEB-03 hard-depends on WEB-02 only, and WEB-08 hard-depends on WEB-11.

### ENG-14 (major, split). WSP-01 is overloaded, and S71 waits for PH2 for no reason

- **Change.** Split WSP-01 three ways:
  - **New S feature in PH1** for S71: the guard plus a host exit-status test and an upstream PR, hard-depending on FND-01 only.
  - **WSP-01** (M): bindings, request-free run worktree create and adopt, S72 with a host capability token, and repo import.
  - **New WSP-06** (M): session-shell ops (commit, salvage, reset), retention and the disk cap. SES-06 and SES-08 depend on it.

### ENG-15 (major, risk). Gate authority is edit level, not owner only

- **Evidence.** `routes_elicitations.py:60` sets `ELICITATION_RESOLVE_LEVEL = LEVEL_EDIT`. An editor of an edit-shared run session can answer a gate.
- **Change.** The Coral S6b verdict handler checks that the resolver identity is the run owner and refuses everyone else. Test it with an edit-shared session, leave the upstream level unchanged, and add the case to the OPS-04 threat list.

### ENG-16 (major, sizing). SPK-03 is "S" but scoped for two weeks, and its native answers will go stale

- **Evidence.** Its own text describes two weeks of work. `bridge.py` has 82 commits in 30 days, so PH0 answers about native behaviour may not hold by PH3.
- **Change.**
  - SPK-03 keeps the claude-sdk spikes 1, 2, 4, 7, 16, 19 and 20 (S, PH0).
  - Spikes 5 and 6 become RUL-04's time-boxed first PR.
  - Spikes 12 and 13 become HRN-05's first PR.
  - Drop RUL-04's hard dependency on SPK-03.

### ENG-17 (minor, split). SES-06 mixes two concerns

- **Change.** Split drift detection, re-attach and the generic-action outcomes into an M feature built against FakeOmni, leaving the runner-loss restart ladder in SES-06.

### ENG-18 (minor, evidence). A non-deterministic M2 exit gate

- **Change.** Gate M2 on E2E-1, E2E-2 and the L2 fault suite. Treat the nightly as a soak with a threshold set in SPK-01, and require the OQ-51 decision record before `coral-bench.yml`.

### ENG-19 (minor, risk). elkjs is already a transitive dependency

- **Evidence.** It comes in through `@lobehub/icons` → `@lobehub/ui` → `beautiful-mermaid@1.1.3` → `elkjs@0.11.1` (`pnpm-lock.yaml:5721, 14622-14624`; `web/package.json:32`).
- **Change.** OPS-02 blocks only new direct dependencies that Coral adds, and records the inherited elkjs for counsel (OQ-30). WEB-01 adds `@dagrejs/dagre` and a direct `yaml` dependency in one standalone dependency PR.

### ENG-20 (minor, evidence). Two wrong paths and one undefined term

- **Change.**
  - EXT-05: `omnigent/server/scheduled/`.
  - SES-07: `omnigent/terminals/pane_reaper.py`.
  - Define "own-runner child" as a child created with `host_id` (`app.py:4594-4597`).

### ENG-21 (minor, split). TLS-03 contains the ask_user cut line

- **Change.** Split `coral_ask_user` into its own S or M feature that depends on GTE-01 and TLS-01.

### ENG-22 (minor, boundary). S37 is about 80 lines in an upstream page

- **Change.** GTE-02 adds an inbox-kind registry that `InboxPage.tsx` spreads in one line, landed after BRD-02's S84.

### ENG-23 (minor, risk). Single-replica refusal cannot see plain multi-replica deployments

- **Evidence.** Only `host_sharded` is detectable (`app.py:1602`).
- **Change.** DUR-04 takes a DB-level worker lease using the StartupLease pattern, tested with two app instances on the Postgres lane.

### ENG-24 (minor, contract). K4 freezes before ADR-05

- **Change.** Freeze K4's topology-independent methods in PH0. The session-create and access sections freeze after ADR-05, so SES-01 hard-depends on SPK-02 for those sections only.

### ENG-25 (minor, evidence). E2E-5 duplicates lower-layer properties

- **Change.** Cover join-once and duplicate-signal behaviour in L1 fuzz and the DUR-03 contention tests. Keep E2E-5 only for the boundary of two real concurrent sessions.

### ENG-26 (minor, evidence). Web test layering is unstated

- **Change.** Each web feature says which assertions are vitest pure-module tests and which run in the CI-only `tests/browser_ui/workflows/` lane, with feature-map rows.

### ENG-27 (minor, boundary). `coral/cli.py` has two concurrent creators

- **Evidence.** DUR-02 adds the upload command and OPS-03 adds the console script, both in PH1.
- **Change.** OPS-03's first PR creates `coral/cli.py` and its entry point, then DUR-02 adds its subcommand. Alternatively, FND-01 adds the stub.

### ENG-28 (minor, reorder). FND-01 edits upstream files before the ledger exists

- **Change.** OPS-01's first PR seeds the FND-01 seam entries and runs the guard in warn-only mode, then makes it required.

### ENG-29 (minor, sizing). HRN-06 is probably XL

- **Evidence.** It carries six seams, two of them M.
- **Change.** Split the S20 gating fix plus S61 and S67 from S18, S19 and S60, and cut the latter first.

### ENG-30 (minor, other). The critical-path text is inconsistent

- **Evidence.** Master section 0 gives M3 as 18 weeks, below M2's 18.5, while the script gives 18.5.
- **Change.** Report cumulative per-milestone paths, and recompute after ENG-04 and ENG-05.

## 10. TLD flags (no TLD found unsound)

- **TLD-02 is sound,** but "own_runner" needs the concrete definition above.
- **TLD-09 is sound,** but owner-only authority must be enforced in Coral's verdict handler, not by the seam level (ENG-15).
- **TLD-10 is sound for L1 fingerprints.** It is conditional for commit, salvage and reset: the session-shell backend needs the ops-host rule and the restart reorder in ENG-02, or the minimal S40 slice arrives in PH2.
- **TLD-17 is sound,** but the inherited compat sweep must be accounted for (ENG-03).

## 11. Strengths

- A contract catalog with producers, phases, fakes and contract tests lets most teams build against stubs.
- Seam ownership is unique and indexed, and every not-planned seam has a reason.
- Spikes are time-boxed with costed contingencies, including the topology fallback and minimal host ops.
- Scope keys and `session_generation` are in from day one. `tests/stores/coral/` runs on all four DB lanes automatically.
- Code references are largely accurate: 33 of 35 spot-checks hold.
- Cut lines are explicit (WEB-02 editor, TLS-03 ask_user, HRN-06), and the one-line hot-file rule is stated.
