# Staff Architect critique of master feature list v1

Input: `decomposition/master_v1.md` and `decomposition/master_v1.json` (85 features, K1-K20). Repository `omnigent-ai/omnigent` at `2a9cbe2c2`, read-only. Date 2026-11-11.

Lens: architectural soundness, contract catalog completeness, module boundaries, dependency correctness, seam placement and hot-file discipline, data-model sequencing, and whether architect.md §2 is fully realized.

Method:

- I read master_v1 in full, all of `investigation/gap_analysis.md`, and architect.md §0, §2, §4, §5, §6 and §8.
- I read the relevant parts of eng_sessions.md, eng_tools.md, eng_workspace.md, eng_persistence.md, eng_testing.md and current_state.md.
- I recomputed contract reachability and critical paths from the JSON. Scripts are in `wf2/arch_tmp/cp.py` and `cp2.py`; weights are S=1, M=2, L=4.5 over hard dependencies.
- I re-opened the code facts cited below at HEAD.

## 1. Verdict

The plan's skeleton is sound:

- the contract-first PH0 packs;
- a pure reducer plus run log and a Coral-owned queue;
- a separate Alembic environment;
- one Coral API namespace;
- one facade;
- a seam ledger from day one.

It realizes most of architect.md §2. It is not yet buildable as written in three areas:

1. **The module boundary contradicts the plan's own key paths.** The FND-01 boundary test allows only `coral.omni`, `coral.policies` and `coral.db` to import Omnigent. Yet at least ten planned modules outside those packages must import Omnigent internals. This is one blocker.
2. **Some cross-team interfaces have no contract, or have one that ships after its consumers:**
   - effect executors;
   - pure reconcile;
   - the plugin registration surface;
   - runner and host capability;
   - DB placement;
   - K19, K18, K9 and K11 timing.
3. **The dependency graph misstates the walking skeleton.** It also carries false hard edges that put pure work behind integration work, and it pre-lands schema ahead of the features that design it.

The issues are in section 9, ranked. None of the TLDs is unsound under this lens. TLD-02 needs one condition made explicit: the run session is a dedicated anchor, not the orchestrator (ARC-15).

## 2. Target architecture (architect.md §2) vs features

| §2 element | Realized by | Gap |
|---|---|---|
| Server-plugin seam: routers, workers, policy modules, tool handlers, observers (§2.1 PLG, C7, ADR-03) | FND-02 (K17) | K17 carries only routers, lifespan hooks and ServerServices. Policy modules come from a separate `policy_modules` config key (RUL-01). Observers and handlers are registered through five different mechanisms. **ARC-02** |
| `coral.omni`, the only importer of Omnigent internals (§2.1, §2.2) | SES-01 (K4) and others | The boundary allows three packages, and many planned paths sit outside all three. **ARC-01** |
| `coral.engine`: reducer, **reconcile**, simulate, all pure (§2.2) | ENG-04..07 | Pure reconcile has no owner. DUR-05 builds reconcile in `coral/reconcile/` with I/O. **ARC-05** |
| `coral.engine.workers`: claim, dispatch effects through `coral.omni`, timers, resync | DUR-04 | The effect-to-facade executor interface has no contract. **ARC-06** |
| `coral.model`, `coral.validate` | ENG-01..03, RUL-02 | Derived joins, regions and the loop table live in the validator, not the compiler. The content-hash basis is unstated. **ARC-11** |
| `coral.tools` (handlers to commands) | TLS-01..04 | The provider path `coral/tools/provider.py` breaks the boundary. eng_tools.md:177 placed it at `coral.omni.tool_schemas:provider`. **ARC-01** |
| `coral.stores` / `coral.db` on the **main DB**, conversation DB may be separate (§2.1 DBM/DBC, N4, K5) | FND-03, DUR-01..03 | Placement is never stated, and no split-DB test exists. **ARC-04** |
| MCP handler registry (S10), live-state observer registry (S1) | TLS-01, SES-02 | Realized. S1b over-scoped. **ARC-13** |
| Gates as elicitations on the run anchor (§2.3 flow 4, C12) | GTE-01 | Anchor identity and bundle are unowned. **ARC-15** |
| `coral.evidence`, `coral.rules`, `coral.policies` | EVD-*, RUL-* | Realized. The `coral/evidence` package mixes pure and Omnigent-touching modules. **ARC-01** |
| Web desks with a generated client (§2.1 WEB, CAPI) | WEB-*, API-01 | Realized. Generated artifacts are missing from the rehearsal regeneration list. **ARC-20** |
| Host / sandbox runner | SES-03, WSP-* | Coral code runs inside the runner and host processes, but no version handshake exists. **ARC-03** |

## 3. Contract catalog

### 3.1 Mechanical reachability

For each consumed contract, I checked for a hard or soft dependency path to its producer:

| Contract | Producer (phase) | Consumer (phase) | Finding |
|---|---|---|---|
| K19 alerts | GTE-02 (PH2) | DUR-05 (PH2) | No path. Also: coral_0002 in DUR-01 (PH1) already lands an alerts table. ENG-06 (PH1) emits watchdog alerts but does not consume K19. |
| K7 API | API-01 (PH0) | FND-02 (PH1) | No path. FND-02 serves `GET /v1/coral/info`, which K7 defines. |
| K4 facade | SES-01 (PH0) | FND-04 (PH1) | No path. Tier B scaffolding needs FakeOmni. |
| K9 capabilities | HRN-01 (PH1) | RUL-03 (PH3) | No path. RUL-03 rejects unenforceable Required rules using K9 and V9 (RUL-02). |

### 3.2 Timing problems the script cannot see

- **K9 (HRN-01) and K18 (SES-02)** are listed in M1 exit 7 as PH1 contracts, but their producers are M2 features. Their consumers either hard-depend on the whole producer (RUL-02 on HRN-01) or need them early (SES-04 per-mode turn end).
- **K11 (EVD-01, PH1)** defines the done-when block that K1 (PH0) must embed. ENG-07's MVP template (M1) must carry it, and DUR-02's version freeze must snapshot the confirmed commands (X-32). ENG-07 has no edge to EVD-01.
- **K2 workspace effects** (commit, salvage, reset) depend on K13 (SPK-04), but ENG-01 has no edge to SPK-04.

### 3.3 Missing contracts

1. **Effect executor registry.** It sits between DUR-04 and the effect owners: SES-03 create, SES-04 send/interrupt/stop, GTE-01 publish, WSP-01 workspace ops, PRF-01 materialize, GTE-02 alerts and SES-03/RUL-01 policies. It should fix the effect kind to executor mapping, the result to `EffectCompleted`/`EffectFailed` mapping, error classes from the K2 taxonomy, who owns retry and backoff, and each kind's idempotency obligation. None of K2, K4 or K5 states this. **ARC-06**
2. **Pure reconcile signature.** The I7 invariant (eng_testing.md:198: "any permutation of a multiset of signals, plus one reconcile, reaches the same state") needs it in the pure layer. **ARC-05**
3. **Plugin registration surface and process map.** Each Coral registration needs a defined process (server, runner or host) and mechanism (plugin export or entry point). **ARC-02**
4. **Runner and host Coral capability.** A token in `HostHelloFrame.capabilities` (`omnigent/host/frames.py:71-94, 329`) would let preflight refuse hosts without Coral entry points. **ARC-03**
5. **coral.policies factory ids and params.** PRF-01 bundles, TLS-03 guard, RUL-03 catalog and EXT-02 all name them. Add this to K12 (the guardrails slot) under ARC-02.

## 4. Module boundaries

The FND-01 rule (master line 12, FND-01 "In"): only `coral.omni`, `coral.policies` and `coral.db` import Omnigent internals. Planned paths that must import Omnigent, outside those packages:

| Path (feature) | Omnigent dependency |
|---|---|
| `coral/server_plugin.py` (FND-02) | ServerServices, app wiring |
| `coral/api/*` (API-01, DUR-02, API-02, GTE-02, EVD-03, RUL-03, PRF-02, ENG-10) | Omnigent auth provider and the access check through the run session (K7) |
| `coral/tools/provider.py` (TLS-01) | ToolManager tool base classes. It runs in **both** server and runner (eng_tools.md:177). |
| `coral/tools/handlers/*` (TLS-02..04) | `ServerToolCall` from `omnigent/server/server_tools.py` |
| `coral/workers/` (DUR-04) | `workspace_scope`, `account_authority_scope`, `host_owner_scope` (fire.py:567-586 pattern) |
| `coral/stores/blobs.py` (DUR-02) | Omnigent `ArtifactStore` |
| `coral/signals/` (SES-04) | Status-edge observer registry (S1) |
| `coral/evidence/capture.py` (EVD-02) | S68 observer in the runner, S69 transport |
| `coral/harness/preflight.py`, `claude_native.py`, `codex_native.py` (HRN-02, HRN-03, HRN-05) | `harness_accounts`, native launch |
| `coral/gates/` (GTE-01) | S6a publish, S6b verdict handlers |
| `coral/host_ops/` (WSP-02, EVD-04, WSP-03, EXT-02) | Host process, S40b entry point, host frames |
| `coral/retention/` (DUR-06) | S56 account callbacks |
| `coral/cli.py` (DUR-02, OPS-03) | Wraps the Omnigent CLI |

Consequences:

- The FND-01 proving test will fail on the first PH1 PRs, or it will be loosened case by case, which defeats the boundary.
- K4 does not cover several of these dependencies: auth/access, artifacts, ambient scopes, usage, harness accounts and observation ingestion.
- `coral/evidence` mixes the pure modules `ir.py` and `evaluate.py` with `capture.py`, which touches Omnigent. This makes a per-package purity lint impossible.
- The FND-01 test checks only `omnigent` imports. It does not stop the pure layer from importing Coral I/O modules (`coral.stores`, `coral.omni`). **ARC-01**

## 5. Dependencies

### 5.1 Critical paths (recomputed, single-owner weeks)

| | Base | With ARC-11 and ARC-12 edge changes |
|---|---|---|
| M1 | 13.5 (FND-01 > ENG-01 > ENG-02 > ENG-04 > ENG-05 > ENG-07) | 11.5 (FND-01 > ENG-01 > ENG-04 > ENG-05 > ENG-07) |
| M2 | 18.5 (session chain) | 18.5 (unchanged; the session chain is genuinely critical) |
| RUL-02 finish | 16 | 9 |
| WEB-06 finish | 18 | 11 |
| EVD-02 finish | 14 | 9.5 |
| TLS-03 finish | 16 | 14 |

Walking skeleton: the skeleton set (SES-03, SES-04, TLS-02, GTE-01, DUR-03, DUR-04) finishes by week 12. SES-05 as modelled cannot start before week 16.5, because it hard-depends on 12 features, including SES-06, EVD-02, WSP-01, HRN-02 and API-02. **ARC-09**

### 5.2 False hard edges

- **ENG-04 to ENG-02.** The reducer runs on K1 IR fixtures.
- **ENG-05 to ENG-03.** Joins only need derivations, and those belong in the compiler (ARC-11).
- **RUL-02 to EVD-02 and HRN-01.** RUL-02 is a pure label API "with a frozen matrix fixture" (its own "In"). It needs K11 and K9, not the capture feature.
- **TLS-03 to TLS-02 and PRF-01.** Decision requests and handoff collections come from the reducer, and the shared transport is TLS-01.
- **EVD-02 to WSP-01.** EVD-02 can build against the K13 fake. Only the S71 guard must precede it (ARC-18).

### 5.3 Missing edges

- **HRN-06** lacks SES-04 (codex turn end) and TLS-01 (tool transport); HRN-05 has both.
- **ENG-10** lacks WSP-01 (a worktree at the carried commit) and WEB-04 (it ships `web/src/workflows/runs/restart/`).
- **DUR-02's `coral workflow upload`** needs the console script that OPS-03 owns. OPS-03 is M2 and "may slip to PH5".
- **FND-02 / FND-03:** the order in which plugin startup calls `ensure_coral_schema` is unstated.
- **ENG-01** lacks SPK-04.
- **ENG-07** lacks EVD-01.
- **DUR-05** lacks GTE-02.
- **FND-02** lacks API-01.
- **FND-04** lacks SES-01.
- **RUL-03** lacks HRN-01 and RUL-02.
- **ENG-08** has no integration edges, yet carries E2E-5. **ARC-16**

## 6. Seams and hot-file discipline

30-day churn at HEAD, from `git log --since=2026-10-12`:

| File | Commits | Seams |
|---|---|---|
| `harnesses/claude_native/bridge.py` | 82 | S14, S68 |
| `_sessions/orchestration.py` | 73 | S1, S6b, S10, S43, S69 |
| `server/app.py` | 63 | S32, S41 |
| `runner/app.py` | 60 | S43, S68 (missing from the master's train table) |
| `host/connect.py` | 58 | S71, S40, S74 |
| `_sessions/helpers.py` | 52 | S1, S1b, S3, S43, S45, S49, S62 |
| `runner/native/orchestration.py` | 51 | S9, S11, S12, S64 |
| `sessions/routes_events.py` | 39 | S1b, S6a, S42, S45, S69(b) |
| `codex_native/app_server.py` | 33 | S11, S15 (missing from the train table) |
| `host/frames.py` | 24 | S72, S40 (missing from the train table) |
| `runner/tool_dispatch.py` | 24 | S8, S9, S68 |
| `inner/claude_sdk_executor.py` | 19 | S13, S21, S24, S63 (missing from the train table) |

Findings:

- **The "one-line registry call" claim is not true for several hot seams.** These are Modify-class behaviour changes:
  - S1b: 18 `_publish_status` sites in four hot files;
  - S43: a signature change;
  - S6b: resolver identity;
  - S14: hook fail-closed;
  - S40: frames plus a dispatcher;
  - S72: worktree create extensions;
  - S62: M size.
- **S1b is optional.** eng_sessions.md:273 says "The phase-2 reconciler works without S1b; S1b only reduces false wake-ups", and §711 marks it "2 (optional)". It is the largest mechanical diff in the hottest files, yet master puts it on the M2 Critical path inside K18. **ARC-13**
- **Dormant seams land phases before a tested consumer:**
  - native S9/S11/S12 sites in TLS-01 (PH1), consumed by HRN-03 (PH3) and HRN-05 (PH5);
  - S69(b), the outbox event in EVD-02 (M2). eng_workspace.md:422-424 shows claude-sdk needs only transport (a); (b) is for Codex and native.

  Anchors with no test rot across daily merges. **ARC-17**
- **Upstreaming is late.** Upstream PRs are planned in SES-02 (S1) and TLS-01 (S10, S50) at landing, but everything else waits for OPS-05 in PH5. That includes S32, S5, S6, S52, S51, S71, S72, S14, S22 and S59, all "Up: Yes". **ARC-14**
- **TLS-01 refactors upstream code in the fork.** It migrates `sys_advise_models` into the new registry inside a 73-commit file. That refactor belongs in the upstream PR. The fork should carry only a lookup added beside the existing intercept. **ARC-13**

## 7. Data-model sequencing

DUR-01 (PH1, M) lands coral_0001 and coral_0002, about 25 tables. Several are designed by later features:

| Table | Designing feature | Note |
|---|---|---|
| questions | TLS-03 (PH2) | |
| step agents | PRF-01 (PH2) | |
| alerts | GTE-02 (PH2) | K19 does not exist yet |
| repo bindings, command patterns | EVD-03 / WSP-01 (PH2) | |
| command observations | EVD-02 (PH2) | S69 shape decided by SPK-04 |
| stable_id map | SES-04 | |
| session bindings | SES-03 | |

Two more problems:

- **Queue layout has two owners.** DUR-04 says "Physical layout chosen here", but DUR-01 already lands the queue and timer tables, and section 6 says to "publish K5 and the queue tables as DUR-01's first PR". OQ-34 cannot be decided in two places.
- **Later table-adding features name no migration PR.** GTE-03 (channel config, delivery state), ENG-09 (saved blocks), EVD-04 (check results), RUL-05 (budgets), WSP-03 (merge state), SES-07 (taken_over), EXT-01, EXT-04 and GTE-04 never say where their schema goes.

Pre-landing tables and then altering them costs extra migrations on all four lanes. On CockroachDB every schema change also needs a SERIALIZABLE prepare (eng_persistence.md:116). **ARC-08**

The plan also never says that Coral tables live on the operational DB, never in the optional conversation DB. That DB is enabled by `conversation_database_uri`: `cli.py:4888` reads the setting and `db_models.py:104-114` defines the separate conversation base. It also never says Coral must avoid joins and cross-DB transactions with conversations (current_state.md:508; eng_persistence.md:56). No lane tests a split DB. **ARC-04**

## 8. Plugin and policy loading facts (ARC-02)

- **`load_registry` skips policy modules that fail to import.** It logs "Failed to import policy module %s; skipping" and continues (`omnigent/policies/registry.py:112-121`). It runs from `create_app` with `policy_modules` from config (`app.py:2046`; `cli.py:5136`).
- **Uploaded agent bundles may only name registered handlers.** The check is `omnigent/inner/loader.py:160-165`, which says "a server admin must add custom handlers via the 'policy_modules' config". `validate_agent_bundle` enforces the allowlist by default (`server/bundles.py:102`).
- **Result:** Coral needs two config keys, `server_plugins` and `policy_modules`. A broken `coral.policies` import is invisible at startup and only surfaces when the first per-step bundle carrying Coral guardrail handlers is rejected at run start. K17's "fatal import failure" covers plugins only.

## 9. Issues

Ranked; the same ids are returned in the structured output.

- **ARC-01 (blocker)** Boundary rule vs planned paths: tiered boundary, process subpackages under `coral.omni`, broader K4, one import shim.
- **ARC-02 (major)** Plugin registration surface split; `policy_modules` fails late.
- **ARC-03 (major)** No runner or host Coral capability handshake.
- **ARC-04 (major)** Coral DB placement (operational DB only) unstated and untested.
- **ARC-05 (major)** Pure reconcile has no owner; I7 cannot be tested.
- **ARC-06 (major)** Effect executor contract missing.
- **ARC-07 (major)** K19, K18, K9 and K11 ship after or inside their consumers; four contract consumers have no path to the producer.
- **ARC-08 (major)** Schema pre-landed in DUR-01; queue layout owned twice; later migrations unnamed.
- **ARC-09 (major)** SES-05 hard dependencies contradict "walking skeleton first".
- **ARC-10 (major)** Seam pack C is blocked in PH2 while packs A and B land in PH1.
- **ARC-11 (major)** IR derivations split across compiler and validator; content-hash basis unstated; false engine edges.
- **ARC-12 (major)** Cross-workstream false hard edges (RUL-02, TLS-03, EVD-02).
- **ARC-13 (major)** Hot seams that are not one-line calls; S1b optional but critical; upstream refactor done in the fork.
- **ARC-14 (major)** Upstream PRs deferred to PH5.
- **ARC-15 (major)** The anchor run session is unowned.
- **ARC-16 (major)** Integration of structure (repeat, parallel) is unowned; E2E-5 sits in a pure engine feature.
- **ARC-17 (minor)** Dormant seams and an incomplete hot-file train table.
- **ARC-18 (minor)** S71 buried as the first PR of an L feature.
- **ARC-19 (minor)** Missing edges (HRN-06, ENG-10, DUR-02/OPS-03, FND-02/FND-03, ENG-01).
- **ARC-20 (minor)** Contract suites and generated artifacts missing from the rehearsal.
- **ARC-21 (minor)** S12 should introduce the CLAUDE.md FrameworkInstructions boundary.
- **ARC-22 (minor)** K13 frozen inside a one-week spike.
- **ARC-23 (minor)** No threat model before the security-relevant contracts freeze.
- **ARC-24 (minor)** Critical-path statements inconsistent between §0, §6 and the script.

Details and proposed changes are in the structured output. The evidence for each is in sections 2-8 above.

## 10. Strengths (keep)

- **Contract-first PH0 packs.** ENG-01, SES-01 and API-01 come with fakes, goldens and a published freeze rule.
- **Scope keys and `session_generation` from day one.** They go into K2, K3 and coral_0001 (TLD-21), which avoids the retrofit migration.
- **Separate Alembic environment, done properly.** It runs after Omnigent head, never uses `create_all`, and is tested on four lanes, including truncation and env.py filters (S30, S31).
- **The S1/S10/S50/S52 registry seams are upstreamable**, and section 6 sequences the hot files as a serial train.
- **The topology spike is time-boxed with the right probes.** Probe (f), engine relaunch of own-runner children, and probe (e), a gate on a turnless session, catch the two facts most likely to break TLD-02.
- **K13 WorkspaceOps has two backends,** so M4 swaps session-shell for the host channel without touching the evaluator or restart code.
- **The unplanned-seam list has reasons for every entry,** with conditional owners (S21, S51, S66, S3) stated.
