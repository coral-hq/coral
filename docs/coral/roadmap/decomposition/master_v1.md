# Coral master feature list, version 1

Synthesis of the contract-first (architect), vertical-slice (product) and risk-first (adversarial) decompositions. Repository `omnigent-ai/omnigent` at `2a9cbe2c2` (Omnigent 0.22.0.dev0). Date 2026-11-11. Ids G-, S-, X-, D-, R- and OQ- refer to `investigation/gap_analysis.md`; TLD- to the tech lead working decisions; PC- and journeys (a)-(m) to `investigation/product.md`. Machine-readable copy: `master_v1.json` (same directory).

## 0. Shape at a glance

- **85 features** in 17 areas and 8 workstreams. By phase: PH0 9, PH1 24, PH2 18, PH3 8, PH4 11, PH5 8, PH6 7. By milestone: M1 23, M2 28, M3 8, M4 19, post-M4 7. Sizes: S 9, M 44, L 32; no XL.
- **20 contracts** (K1-K20). Seventeen ship in PH0 or PH1 as standalone deliverables; K15, K19 and K20 ship as the first PR of their producer, before any consumer starts.
- **Coverage.** Every G-01..G-90 row has at least one owning feature; deferred sub-parts are in section 5. Every seam S1..S89 (with S1b, S6a/b, S39b-e, S40b) has exactly one owner or is listed as not planned. A script checks ids, coverage, unique seam ownership, contract producers, that no hard dependency points to a later phase or milestone, and that the combined hard and soft graph has no cycles.
- **Critical path (single owner, S=1, M=2, L=4.5 weeks over hard dependencies).** M1: 13.5 weeks via FND-01 > ENG-01 > ENG-02 > ENG-04 > ENG-05 > ENG-07; M2: 18.5 weeks via FND-01 > SES-01 > SES-03 > SES-04 > SES-06 > SES-05; M3: 18 weeks via FND-01 > FND-03 > DUR-01 > WSP-01 > EVD-02 > RUL-02 > WEB-06; M4: 23 weeks via FND-01 > FND-03 > DUR-01 > WSP-01 > WSP-02 > EVD-04 > WSP-03.
- **Walking skeleton.** SES-05 is PH2's first integration target (one-step workflow -> real session -> submit -> gate -> answer -> end, surviving a kill). It is built against the skeleton slices of ENG-04, SES-03, SES-04, TLS-02 and GTE-01 and grows into the M2 acceptance lane.
- **Boundaries.** Pure engine work (ENG-*, EVD-01, RUL-02) imports nothing from `omnigent`. Only `coral.omni`, `coral.policies` and `coral.db` import Omnigent internals (FND-01 test). Every hot-file seam is a one-line call into a registry module, landed as a serial seam train (section 6).
- **Staffing risk.** WS-INTEGRATION owns 18 features; staff it as a seam and facade sub-team and a tools and policies sub-team (see the decisions log).

## 1. Contract catalog

Each contract is code (types, schema or protocol) plus a doc under `docs/coral/contracts/`, with a fake or fixtures so consumers build against stubs. It is versioned; after freeze it changes only additively or with the producer's approval and sign-off from each consumer lead. Each carries a contract test (JSON Schema golden, OpenAPI drift, facade signature snapshot, conformance suite or ledger schema test).

| K | Contract | Producer | Ships in | Consumers | What it fixes |
|---|---|---|---|---|---|
| K1 | Workflow authoring schema and compiled IR | ENG-01 | PH0 | API-01, DUR-02, ENG-02, ENG-03, ENG-04, ENG-05, ENG-07, ENG-08, ENG-09, ENG-10, EVD-01, EXT-01, EXT-02, RUL-02, WEB-01, WEB-02, WEB-08, WEB-09 | YAML keys and node kinds (Note layout-only, hidden Wait and Sub-workflow), reserved keys and ids, frozen CompiledGraph, content hash, JSON Schema for TS, stable-id rule, separate layout doc. |
| K2 | Reducer contract | ENG-01 | PH0 | DUR-01, DUR-03, DUR-04, DUR-05, ENG-04, ENG-05, ENG-06, ENG-07, ENG-08, ENG-09, ENG-10, FND-04, GTE-01, SES-01, SES-04, SES-05, SES-06, TLS-02, TLS-03 | transition(graph, state, input, now) -> {state delta, log, effects, rejections}; commands and observations with idempotency keys; effects with effect_key; ScopeKey; session_generation; StartRun(from_node); pause reasons; error taxonomy. |
| K3 | Run-log entry schema and fold | ENG-01 | PH0 | API-02, DUR-01, DUR-03, ENG-04, ENG-05, ENG-06, ENG-07, ENG-08, EXT-01, FND-04, WEB-04, WEB-10 | Closed additive kind enum, seq, actor, scope key, 16 KiB body cap, refs, idempotency key; fold(log) == state. |
| K4 | coral.omni facade protocol and FakeOmni | SES-01 | PH0 | API-02, DUR-05, EVD-03, FND-04, GTE-01, RUL-05, SES-03, SES-04, SES-05, SES-06, SES-07, TLS-04, WSP-01 | Sessions (create, send with stable_id, interrupt, stop, wake, status, items, turn facts), policies, gate publish, profiles, worktrees, host read and capabilities, with idempotency semantics and an in-memory fake. |
| K5 | Coral persistence contract | DUR-01 | PH1 | DUR-02, DUR-03, DUR-04, DUR-05, DUR-06, ENG-10, GTE-03, PRF-02, SES-04, TLS-02 | Table conventions incl. scope keys and derived-id PKs; store protocols (apply_transition CAS, workflow store, queue claim/lease/finish); at-least-once work semantics; migration-train rule. |
| K6 | Engine tool contracts | SES-01 | PH0 | EVD-02, SES-05, SES-07, TLS-01, TLS-02, TLS-03, TLS-04 | The six TLD-20 tools: argument schemas, result envelope, rejection codes, (run, operation_id) dedup, handler signature, params.coral opt-in keys. |
| K7 | Coral REST API and OpenAPI | API-01 | PH0 | API-02, BRD-02, DUR-02, EXT-05, FND-02, GTE-02, GTE-03, WEB-01, WEB-02, WEB-03, WEB-04, WEB-05, WEB-06, WEB-07, WEB-08, WEB-10 | /v1/coral/* endpoints incl. info gate, error envelope, ETag/412, start_key, access mapping, OpenAPI artifact with drift check, generated TS types. |
| K8 | Run stream protocol | API-01 | PH0 | API-02, WEB-04, WEB-10 | SSE snapshot then seq-numbered entry events; Last-Event-ID resume; heartbeat; [DONE]; polling fallback. |
| K9 | Capability registry | HRN-01 | PH1 | HRN-02, HRN-03, HRN-04, HRN-05, HRN-06, RUL-02, RUL-03, RUL-04, RUL-05, SES-04, SES-07, WEB-06, WEB-07, WEB-09 | Capability fields and enums per harness spelling (S22, S59); CapabilityMatrix; effective-enforceability inputs to promise labels and V9. |
| K10 | Identity, labels and derived keys | SES-01 | PH0 | EXT-04, GTE-01, GTE-02, PRF-01, RUL-01, SES-03, WEB-05, WSP-01 | coral.* label keys, uuid5(effect_key) session ids, stable_id per message, deterministic policy ids and worktree paths, coral_gate_<visit> ids, coral__ and coral. prefixes. |
| K11 | Evidence-requirement IR and observation records | EVD-01 | PH1 | EVD-02, EVD-03, EVD-04, HRN-03, RUL-02, SES-07, TLS-02, WEB-03, WSP-02, WSP-03 | Required commands, may-modify flags, exit-code sources, scope, final-pass semantics, observation and fingerprint records, missing-item messages. |
| K12 | Step bundle format and params.coral schema | SES-01 | PH0 | EXT-03, HRN-02, HRN-03, HRN-05, HRN-06, PRF-01, PRF-02, RUL-01, RUL-03, SES-03, TLS-01, TLS-03, WEB-07 | Tar layout, content addressing, params.coral keys, hygiene defaults, approval stance, guardrails slot, provider-reference auth, revision reference. |
| K13 | WorkspaceOps interface | SPK-04 | PH0 | EVD-01, EVD-02, EVD-04, EXT-02, EXT-03, SES-06, WSP-01, WSP-02, WSP-03, WSP-04 | Ops (fingerprint L1/L2, commit, salvage, reset, head, check, merge, read) with op keys; session-shell and host-channel backends; fake backend and conformance tests. |
| K14 | Gate, question and budget elicitation payloads | SES-01 | PH0 | API-01, EXT-04, GTE-01, GTE-02, RUL-05, SES-05, TLS-03 | Form payloads, stable ids, visit token, authored-outcome mapping, hidden decline and cancel, resolver identity, re-publish rule. |
| K15 | Rule-template catalog IR | RUL-03 | PH3 | ENG-09, RUL-02, WEB-06, WEB-09 | Template id, params, target builtin or policy, Required vs Guidance, per-mode enforceability inputs. First PR of RUL-03; bundles reserve the guardrails slot in K12 from PH0. |
| K16 | Seam ledger format | OPS-01 | PH0 | BRD-01, BRD-03, FND-01, FND-02, FND-03, HRN-01, OPS-02, SES-02, TLS-01 | seams.yaml and upstream.yaml: seam id, files, CORAL(Sx) anchors, tests, budget lines, upstream PR, owner feature. |
| K17 | Server plugin registration | FND-02 | PH1 | DUR-02, DUR-04, RUL-01, SES-03 | server_plugins key, ROUTERS, LIFESPAN_HOOKS, ServerServices, hook ordering, fatal import failure, single-replica refusal. |
| K18 | Status-edge observer API and turn facts | SES-02 | PH1 | HRN-03, HRN-05, SES-04 | Observer signature, origin slugs (S1b), turn_outcome (S43), persisted TurnFact fields. |
| K19 | Alert and inbox feed model | GTE-02 | PH2 | DUR-05, ENG-09, GTE-03, GTE-04 | coral_alerts kinds, ack, run actions, deep-link payload without secrets. First PR of GTE-02, consumed by reconcile, reactions and external delivery. |
| K20 | Host workspace-op wire frames | WSP-02 | PH4 | EVD-04, EXT-02, WSP-03, WSP-04 | Frames, workspace_ops:1 capability token, op catalog, job events and journal, reaper-guard rule. First PR of WSP-02; K13 carries a draft appendix from PH0. |

## 2. Features by phase

Header: `workstream · phase · milestone · priority · size · enabler|slice`. **G** gap rows; **S** seams owned; **Hard / Soft** dependencies; **K+** produced, **K-** consumed; **In / Out** scope; **Paths** coarse repo paths; **OQ** open questions that block or shape it; **Proof** the test or demo that proves it done.

### PH0 Decisions, contracts and spikes (runs alongside early PH1)

**SPK-01 Decision records and sign-off pack** — OPS · PH0 · M1 · Critical · S · enabler  
Record signed decisions, or recorded defaults, for every TLD and every open question that gates M1 and M2, plus a minimum NFR list.  
In: Requirements baseline from product.md §1, §7 and §9 with a minimum NFR list (OS support, max concurrent runs and agents, latency) (OQ-1, D2); sign-off on TLD-01..21 and on the TLD flags and milestone moves recorded in this roadmap; gate outcomes and reject routing, owner-only gate authority, blocked-exit routing, step agents asking the user, watchdog default, end-of-run output, D6 back-arrow join rule (OQ-3, 4, 12, 13, 14, 18, 19); claude-sdk auth default with a written vendor answer (OQ-28) and v1 harness modes (OQ-35); naming, Powered-by credit, namespace and Coral gate sign-off (OQ-27, OQ-30, R-2, OQ-45, OQ-36); merge cadence and rehearsal owner, dev-DB exception, CODEOWNERS (OQ-50, OQ-53, OQ-54).  
Out: Codex terms OQ-29 and retention OQ-25 (decide before PH5); promise-label visuals OQ-24 (decide before PH3).  
Paths: `docs/coral/decisions/`, `coral/CLAUDE.md (new, after OQ-53)`  
OQ: OQ-1, OQ-3, OQ-4, OQ-12, OQ-13, OQ-14, OQ-18, OQ-19, OQ-27, OQ-28, OQ-30, OQ-33, OQ-35, OQ-36, OQ-38, OQ-45, OQ-49, OQ-50, OQ-53, OQ-54  
Proof: docs/coral/decisions/ holds a signed or defaulted record for each listed OQ and TLD, and the M2 feature specs cite them.

**SPK-02 Session topology spike and ADR** — INTEGRATION · PH0 · M1 · Critical · S · enabler  
In four days, prove or reject TLD-02 option B (step children of a stable run session with own_runner, plus S51) and record the topology ADR with the fallback costed.  
G: G-22  
In: (a) A child with its own worktree on a shared runner runs tools in its own cwd on claude-sdk (spike 3); (b) a run session that never takes a turn hosts children; (c) an S51 prototype stops parent wakes; (d) stopping the orchestrator spares own_runner steps; (e) a gate elicitation on the run session renders in Inbox and /approve; (f) the engine can relaunch own-runner children after restart (upstream relaunches roots only, app.py:4273; recovery skips host_id children, child_session_recovery.py:164); spikes 14 (posts to archived sessions) and 15 (runner-local impersonation); ADR-05 with the fallback (top-level family + S35 watch-set + engine-managed grants) costed at +3-4 eng-weeks.  
Out: Facade code (SES-03); building the fallback (contingency only).  
Paths: `docs/coral/decisions/ADR-05-topology.md`, `spike branch only`  
OQ: OQ-32, OQ-17  
Proof: A scripted spike run demonstrates probes (a)-(f) and ADR-05 records the verdict with evidence.

**SPK-03 Harness behaviour probes** — HARNESS · PH0 · M1 · Critical · S · enabler  
Answer the claude-sdk unknowns that shape M2 in week 1 and the native and Codex unknowns in week 2, each with a recorded verdict.  
G: G-44  
In: Week 1 claude-sdk: spike 1 can_use_tool under auto/bypass (decides S21), 2 Agent/Task unreachable, 4 mock ANTHROPIC_BASE_URL (Tier C lane), 7 MCP tool-call timeout (handoff scan bound), 16 idle watchdog vs long turns, 19 local CredentialStore, 20 Smart Routing pin; week 2 native and Codex: spike 5 UserPromptSubmit on /clear, 6 native ASK re-publish after restart, 12 codex-native app-server sandbox, 13 Codex context window; verdict memo with a reproducible probe script per spike.  
Out: Bench code (HRN-01); fixes (owning features).  
Paths: `docs/coral/decisions/probes/`, `tests/harness_bench/probes/ (prototype only)`  
OQ: OQ-51  
Proof: Verdict memo lists each spike with a rerunnable probe and marks S21 as needed or not needed.

**SPK-04 Workspace and evidence spike with WorkspaceOps contract** — WORKSPACE · PH0 · M1 · Critical · S · enabler  
Decide how M2 gets trustworthy fingerprints, commits and resets for a claude-sdk single writer without S40, and publish the WorkspaceOps interface (K13).  
G: G-38, G-59 · K+: K13  
In: Spike 8: sandboxed git add, commit and write-tree in a linked worktree; runner /changes porcelain vs re-edits of already-dirty files; one L1 algorithm for per-command and submit-time digests; session-shell timeout and true exit codes (routes_resources.py:3257-3297); S71 reaper hazard repro (connect.py:1417-1423, 6027-6034); K13 WorkspaceOps interface (fingerprint, commit, salvage, reset, head, check, merge, read) with session-shell and host-channel backends and a fake; contingency: if the session sandbox cannot commit or reset, pull minimal host ops into PH2 (+3 eng-weeks on the WSP-01 chain).  
Out: Building the host channel (WSP-02); spike 9 beyond a note.  
Paths: `coral/workspace/ops.py`, `coral/workspace/fake.py`, `docs/coral/contracts/workspace-ops.md`  
OQ: OQ-39, OQ-44, OQ-10  
Proof: Spike report plus the K13 protocol module whose fake backend passes the K13 conformance tests.

**FND-01 Coral package and tooling roots** — PLATFORM · PH0 · M1 · Critical · S · enabler  
Ship the coral package in the same wheel with lint, type, coverage, CI and CODEOWNERS roots and an enforced import boundary.  
G: G-12 · S: S29, S39, S39b, S39c, S39d, S39e, S76 · Soft: OPS-01 · K-: K16  
In: coral* in the wheel with package data for Coral Alembic files and templates (S29); pyrefly, isort, coverage, lint and pre-commit roots; CODEOWNERS; coral CI group in python-matrix.json (S39, S39b-e); just mod coral (S76); import-boundary lint and test: only coral.omni, coral.policies and coral.db import Omnigent internals; spike 10: no dependency ships a top-level coral import name.  
Out: Alembic env (FND-03); fork guard (OPS-01); console script (OPS-03).  
Paths: `pyproject.toml`, `pyrefly.toml`, `.pre-commit-config.yaml`, `.github/CODEOWNERS`, `.github/scripts/ci/python-matrix.json`, `justfile`, `coral/__init__.py`, `coral/coral.just`, `tests/coral/test_import_boundary.py`  
OQ: OQ-54  
Proof: tests/coral/test_import_boundary.py passes and a built wheel imports coral with its package data.

**OPS-01 Seam ledger and coral-fork-guard** — OPS · PH0 · M1 · Critical · M · enabler  
Make every upstream-file edit ledgered, anchored and budgeted from the first Coral PR through a required fork-guard check.  
G: G-83 · K+: K16  
In: .coral/upstream.yaml pinned at nightly^1; .coral/seams.yaml seeded with S1-S89 and sub-ids, owners from this roadmap; coral/fork/check_seams.py: allowed roots, CORAL(Sx) anchors, line budgets, commit prefix, stale entries; MODIFICATIONS.md generation; one-line hot-file rule; required CI check; temp-git tests.  
Out: Merge rehearsal (OPS-02); licence texts (OPS-02).  
Paths: `.coral/seams.yaml`, `.coral/upstream.yaml`, `coral/fork/`, `.github/workflows/coral-fork-guard.yml`, `MODIFICATIONS.md`  
OQ: OQ-50, OQ-54  
Proof: coral-fork-guard fails a PR that edits an upstream file without a ledger entry and anchor, and passes once both exist.

**ENG-01 Engine contracts pack** — ENGINE · PH0 · M1 · Critical · M · enabler  
Publish the workflow schema and IR (K1), reducer contract (K2) and run-log schema (K3) as typed, versioned modules with golden fixtures.  
G: G-01, G-03, G-05 · Hard: FND-01 · Soft: SPK-01 · K+: K1, K2, K3  
In: Authoring models and node taxonomy (Start, End, Work step, Orchestrator node, Human gate, Group; hidden Wait and Sub-workflow); Note is layout-only in a separate layout doc (R-16); reserved ids (runs, templates, new) and EGM keys (session: persistent_across_loop, input_scope) (D4); frozen CompiledGraph, content-hash rule and JSON Schema export; ScopeKey (run, node, item_path, iteration_path) on every input, effect, timer and log entry (TLD-21); effect_key and idempotency-key library; session_generation; reserved StartRun(from_node, carried); pause reasons, error taxonomy, rejection codes; closed additive log kinds with 16 KiB body cap; golden fixtures: MVP template, D§5.6 example, a deadlock.  
Out: Loader and compiler (ENG-02); reducer logic (ENG-04); table layout (DUR-01).  
Paths: `coral/model/`, `coral/engine/types.py`, `coral/engine/log.py`, `docs/coral/contracts/`  
OQ: OQ-3, OQ-12, OQ-19  
Proof: JSON Schema goldens match the fixtures and every fixture round-trips through the type modules.

**SES-01 Integration contracts pack** — INTEGRATION · PH0 · M1 · Critical · M · enabler  
Freeze the Omnigent-facing contracts (facade, tools, identity, bundle format, gate payloads) with a FakeOmni so engine, tool, gate and profile work runs in parallel.  
G: G-18, G-25, G-51 · Hard: FND-01 · Soft: ENG-01, SPK-02 · K+: K4, K6, K10, K12, K14 · K-: K2  
In: K4 coral.omni protocols (create, send with stable_id, interrupt, stop, wake, status, items, turn evidence, policies, gate publish, profiles, worktrees, host read) and an in-memory FakeOmni; K6 six TLD-20 tool schemas, result envelope {accepted, reason, allowed_values, next}, rejection codes, (run, operation_id) dedup, params.coral opt-in keys (TLD-04); K10 coral.* labels, uuid5(effect_key) session ids, stable_id per message, deterministic policy ids and worktree paths, coral_gate_<visit> ids, coral__ and coral. prefixes; K12 per-step bundle tar layout, content address, params.coral keys, hygiene defaults, approval stance, guardrails slot, provider-reference auth (WS-HARNESS co-authors); K14 gate, ask_user and budget form payloads, authored-outcome mapping, hidden decline and cancel, resolver identity, re-publish rule.  
Out: Implementations (SES-03, TLS-*, GTE-01, PRF-01).  
Paths: `coral/omni/protocols.py`, `coral/omni/fake.py`, `coral/tools/schemas.py`, `coral/identity.py`, `coral/omni/bundle_format.py`, `docs/coral/contracts/`  
OQ: OQ-3, OQ-37, OQ-43, OQ-47  
Proof: FakeOmni passes the K4 conformance suite and the tool and bundle schemas match their JSON Schema goldens.

**API-01 Coral API and run-stream contracts** — PLATFORM · PH0 · M1 · Critical · S · enabler  
Publish the /v1/coral/* OpenAPI (K7) and run-stream protocol (K8) with a drift check, generated TS types and stub routers so web work starts in PH1.  
G: G-74, G-75 · Hard: FND-01 · Soft: ENG-01, SES-01 · K+: K7, K8 · K-: K1, K14  
In: Endpoint list, error envelope, ETag/412, start_key, access mapping through the run session; coral/api/dump_openapi.py --check and a drift test (upstream dump omits extra_routers); generated TS types; MSW fixtures and stub routers; K8: SSE snapshot then seq-numbered entry events, Last-Event-ID resume, heartbeat, [DONE], polling fallback.  
Out: Real handlers (DUR-02, API-02); Web stream client (WEB-04).  
Paths: `coral/api/openapi.json`, `coral/api/dump_openapi.py`, `web/src/workflows/api/generated/`, `docs/coral/contracts/run-stream.md`  
OQ: OQ-45  
Proof: The OpenAPI drift test fails on an unregenerated change and the web build type-checks against the generated client.

### PH1 Foundations (to M1; some features target M2)

**FND-02 Server plugin seam and Coral enablement gate** — PLATFORM · PH1 · M1 · Critical · S · enabler  
Load Coral routers and lifespan hooks through an upstreamable server_plugins seam, and gate the product with GET /v1/coral/info.  
G: G-17, G-81 · S: S32 · Hard: FND-01 · Soft: OPS-01 · K+: K17 · K-: K16, K7  
In: server_plugins: config key loading modules that export ROUTERS and LIFESPAN_HOOKS with a ServerServices bundle; routers mount before the SPA; hooks start after the scheduler and stop before the runner router closes; import failure is fatal; one-line CLI wiring; refuse Coral workers under multi-replica or host sharding (TLD-08); spike 11 lifespan merge; coral/server_plugin.py mounting /v1/coral with GET /v1/coral/info (TLD-03, no Feature enum edit).  
Out: Workflow and run endpoints (DUR-02, API-02); workers (DUR-04); S33 upstream flag.  
Paths: `omnigent/server/app.py`, `omnigent/cli.py`, `coral/server_plugin.py`, `coral/api/info.py`, `tests/server/test_app.py`  
OQ: OQ-36  
Proof: tests/server/test_app.py plugin cases: routers mount before the SPA, hook ordering holds, an import failure aborts startup, and /v1/coral/info reports enabled.

**FND-03 Coral DB environment and migration ordering** — PLATFORM · PH1 · M1 · Critical · M · enabler  
Give Coral its own Alembic chain and CoralBase that always migrates after Omnigent reaches head, on all four DB backends.  
G: G-13 · S: S30, S31, S57, S58 · Hard: FND-01 · Soft: OPS-01 · K-: K16  
In: coral/db base, types, ids, enum codecs and migrate; coral_alembic_version; CoralBase on its own DeclarativeBase; ensure_coral_schema strictly after Omnigent head with newer-build, D1-refusal and CockroachDB SERIALIZABLE guards; never create_all; env.py include_name filter (S30); truncation keeps every *alembic_version and skips coral_* in root truncation (S31); deploy entrypoint runs Coral migrations (S57); shared cursor and enum helpers (S58); single-head, round-trip, SQLite-safe and ordering tests on SQLite, Postgres, CockroachDB and MySQL.  
Out: Tables (DUR-01); create_all (never used).  
Paths: `coral/db/`, `coral/db/migrations/`, `omnigent/db/migrations/env.py`, `tests/conftest.py`, `deploy/databricks/src/app.py`, `omnigent/db/enum_codecs.py`  
OQ: OQ-42, OQ-54  
Proof: Migration-ordering test: a fresh DB and an upgrade both reach Omnigent head, then Coral head, on all four lanes.

**FND-04 Coral test infrastructure** — OPS · PH1 · M1 · High · M · enabler  
Give every Coral feature its test lanes on day one: pure invariants, DB-lane faults and Tier B E2E scaffolding.  
G: G-87 · Hard: FND-01 · Soft: FND-03, ENG-01, SPK-03 · K-: K2, K3, K4  
In: tests/coral lane map and conftests; Coral-aware SQLite template; I1-I8 invariant harness and seeded stdlib fuzzing; commit-boundary fault-injection and contention helpers for the DB lanes (tests/stores/coral); Tier B scaffolding: mock LLM and an openai-agents step bundle scripted to call engine tools; just coral::test.  
Out: Specific E2E journeys (SES-05); live bench (HRN-01); claude-sdk fake (deferred).  
Paths: `tests/coral/`, `tests/stores/coral/`, `tests/e2e/coral/`, `coral/coral.just`  
OQ: OQ-52  
Proof: A sample reducer property test and a sample commit-boundary fault test run green in the coral CI group on all four lanes.

**OPS-02 Upstream merge rehearsal, fork CI hygiene and licence basics** — OPS · PH1 · M1 · High · M · enabler  
Rehearse upstream merges daily from nightly^1, keep inherited CI safe, and ship the NOTICE addendum and licence inventory.  
G: G-84, G-86 · S: S77 · Hard: OPS-01 · Soft: FND-03, FND-04 · K-: K16  
In: Daily trial merge from nightly^1 with rerere and a conflict report by seam (TLD-17, R-14); scripted regeneration of uv.lock, pnpm-lock, openapi.json and palette CSS; Coral suites L0-L2 on SQLite, Postgres and CockroachDB, MySQL tested, including migration ordering; L3 joins when SES-03 lands; disable secret-using inherited workflows (R-19) and desktop builds until BRD-03; branch protection; NOTICE append-only addendum (S77); licence inventory CI (yaml ISC, dagre MIT, Newsreader OFL; elkjs blocked).  
Out: Executed release merge drill, security cherry-pick lane and upstream PRs (OPS-05); counsel sign-off (OPS-05).  
Paths: `.github/workflows/coral-upstream-rehearsal.yml`, `NOTICE`, `docs/coral/UPSTREAM_MERGES.md`, `coral/fork/licences.py`  
OQ: OQ-50, OQ-30  
Proof: The rehearsal job merges nightly^1 into a scratch branch each day and posts a green or per-seam conflict report.

**OPS-03 Distribution identity and coexistence** — OPS · PH1 · M2 · Medium · S · slice  
Ship a coral console script with its own data and config dirs and update identity so Coral and Omnigent coexist on one machine.  
G: G-85 · S: S75 · Hard: FND-01 · Soft: SPK-01  
In: coral script sets OMNIGENT_DATA_DIR and OMNIGENT_CONFIG_HOME to ~/.coral; update check disabled or pointed at Coral (S75); coral/version.py; isolation test: no writes to ~/.omnigent and no newer-DB lockout; coral/CLAUDE.md dev-DB exception once OQ-53 is approved; cut line: may slip to PH5 if M2 stays internal.  
Out: Desktop identity (BRD-03); renaming omnigent internals.  
Paths: `pyproject.toml`, `coral/cli.py`, `coral/version.py`, `omnigent/update_check.py`, `coral/CLAUDE.md`  
OQ: OQ-49, OQ-53  
Proof: Isolation test runs coral and omnigent side by side with separate dirs, no shared files and no lockout.

**DUR-01 Core schema, persistence contract and migration train** — PLATFORM · PH1 · M1 · Critical · M · enabler  
Publish the persistence contract (K5) and land coral_0001 and coral_0002 as standalone migrations with scope keys, derived ids and generation fencing.  
G: G-14 · Hard: FND-03, ENG-01 · Soft: SES-01, EVD-01 · K+: K5 · K-: K2, K3  
In: K5 first PR: table conventions (workspace_id leading PK, derived-id PKs, Uuid16, CHECKed enums, CompressedText cap, no FKs, scope-key columns), store protocols (apply_transition CAS, workflow store, queue claim/lease/finish), at-least-once semantics; coral_0001_core: workflows, versions, drafts, runs, run specs, activations, join arrivals, slots with session_generation, handoffs and items, gate visits, timers, queue, run log, simulation cases, blob refs; coral_0002_integration: session bindings, stable_id map, step agents, alerts, questions, repo bindings, command patterns, command observations; migration-train ownership with a single-head CI check; models-match test.  
Out: Store code (DUR-02, DUR-03, DUR-04); profile revisions and later tables, which queue through the train.  
Paths: `coral/db/models/`, `coral/db/migrations/versions/`, `coral/stores/protocols.py`, `docs/coral/contracts/persistence.md`  
OQ: OQ-34  
Proof: Models-match-migrations and single-head tests pass on four lanes, and every run table carries the scope-key columns.

**DUR-02 Workflow library: store, versions and API** — PLATFORM · PH1 · M1 · Critical · L · slice  
Store workflows DB-canonically as drafts plus immutable content-addressed versions and serve them, with validate and simulate, through /v1/coral and the CLI (TLD-06).  
G: G-14, G-15, G-66, G-68, G-74 · Hard: DUR-01, FND-02, ENG-02, API-01 · Soft: ENG-03, ENG-07 · K-: K5, K1, K7, K17  
In: Drafts with ETag/412; immutable versions; library index with stable workflow ids; blob key scheme coral/v1/{ws}/..., put-then-commit, coral_blob_refs ledger, size caps at the API boundary; /v1/coral/workflows CRUD, version freeze, :validate and :simulate endpoints; saved simulation cases; coral workflow upload CLI.  
Out: Repo import (WSP-01); repo export (EXT-03); UI (WEB-02).  
Paths: `coral/stores/workflows.py`, `coral/stores/blobs.py`, `coral/api/workflows.py`, `coral/cli.py`  
OQ: OQ-8, OQ-9, OQ-33  
Proof: API test: upload the template and get a version hash; a broken copy returns yaml_path-anchored problems; simulate returns a deterministic trace.

**DUR-03 Run store with CAS transitions** — PLATFORM · PH1 · M2 · Critical · M · slice  
Commit each reducer transition's state, log, effects and receipts atomically under an optimistic run version on every lane.  
G: G-14, G-07 · Hard: DUR-01 · Soft: ENG-04 · K-: K5, K2, K3  
In: Idempotent start_run via start_key; apply_transition writes state delta, log, effects and receipts in one short transaction; reduce-and-retry on version conflict (run_write_transaction retries only 40001/1213); contention and commit-boundary tests on four lanes.  
Out: Queue and workers (DUR-04); purge (DUR-06).  
Paths: `coral/stores/runs.py`, `tests/stores/coral/test_run_store.py`  
Proof: Two concurrent transitions on one run yield one winner and a reducer re-run, with fold(log) == state on all four lanes.

**DUR-04 Durable work queue and workers** — PLATFORM · PH1 · M2 · Critical · L · enabler  
Own an at-least-once queue for signals, timers and effects with leases and idempotency keys, run by plugin-lifespan workers (TLD-08).  
G: G-11, G-25 · Hard: DUR-01, FND-02 · Soft: DUR-03, ENG-06 · K-: K5, K17, K2  
In: Physical layout chosen here (unified or typed tables); lock-and-recheck claims, StartupLease, renew, finish, backoff; delete on apply; enqueue off the event-loop thread; effect drainer and timer scan started by the plugin lifespan; workers enter workspace, account-authority and host-owner scopes; dispatch-time re-validation; single-replica refusal; never PersistentTaskScheduler (R-4).  
Out: Reconcile and resync (DUR-05); multi-replica sharding (deferred).  
Paths: `coral/queue/`, `coral/workers/`, `tests/stores/coral/test_queue.py`  
OQ: OQ-34, OQ-42  
Proof: A worker killed after claim releases its lease and the effect runs exactly once more with the same idempotency key.

**ENG-02 Loader, compiler and content hash** — ENGINE · PH1 · M1 · Critical · M · slice  
Turn workflow YAML into the frozen, hashed IR with source marks so every error points at a box or arrow.  
G: G-01 · Hard: ENG-01 · K-: K1  
In: Safe-load with source marks and a yaml_path-to-range map; stable and reserved ids; compile to frozen IR; content hash; JSON Schema export wired into the web build; golden tests.  
Out: Validation (ENG-03); comment-preserving edits (WEB-02).  
Paths: `coral/model/loader.py`, `coral/model/compile.py`, `tests/coral/model/`  
OQ: OQ-8  
Proof: The MVP template compiles to the expected IR and hash, and moving a key moves the reported error range.

**ENG-03 Static validator and derived joins** — ENGINE · PH1 · M1 · Critical · M · slice  
Report V1-V7 and V10-V13 problems with box-anchored explanations, and derive join types, regions and checked parts.  
G: G-02, G-03 · Hard: ENG-02 · K-: K1  
In: V1-V7 and V10-V13 with plain explanations; V10 against configured harnesses; block-structure soundness instead of exhaustive V11 (X-25, R-24); regions; loop table; AND-join after a split vs merge of alternatives; back-arrow exemption (D6); V12 activation upper bound as a cost backstop; invalid drafts savable but not runnable (OQ-9).  
Out: V8 (ENG-09); V9 (RUL-02); exhaustive enumeration (deferred).  
Paths: `coral/validate/`, `tests/coral/validate/`  
OQ: OQ-9, OQ-19  
Proof: Each rule has a failing fixture with the expected yaml_path and message, and the MVP template validates clean with derived join types.

**ENG-04 Reducer core and run log** — ENGINE · PH1 · M1 · Critical · L · slice  
Implement the pure transition() for runs, activations, slots, attempts, decisions and gate visits, emitting log entries, keyed effects and rejections, with fold(log) == state.  
G: G-04, G-05, G-03, G-34 · Hard: ENG-01, ENG-02 · Soft: ENG-03, FND-04 · K-: K1, K2, K3  
In: State machines for Run, Activation, Slot, Attempt, Decision request and Gate visit; illegal-transition tables; rejections never throw; handoffs and decision requests carrying legal labels and the per-agent handoff collection (D9); gate visits with visit tokens, stale-visit rejection and authored outcome labels (R-7); log emission, fold and receipts; skeleton slice first (start -> step -> gate -> end); staff two engineers (top of L).  
Out: Loops, joins and failure paths (ENG-05); lifecycle and timers (ENG-06); repeat and parallel (ENG-08).  
Paths: `coral/engine/reducer.py`, `coral/engine/machines/`, `tests/coral/engine/`  
OQ: OQ-3, OQ-12  
Proof: Seeded fuzz over the fixtures holds fold(log) == state and I1-I8, and the skeleton fixture walks start -> step -> gate -> end.

**ENG-05 Loops, joins and failure paths** — ENGINE · PH1 · M1 · Critical · M · slice  
Make back-arrows, at-limit routes, joins, failure paths and blocked exits behave exactly as the validator explains.  
G: G-04, G-03 · Hard: ENG-03, ENG-04 · K-: K1, K2, K3  
In: Back-arrow counters keyed by iteration_path; at_limit routing with open findings; join arrivals unique per (activation, arrow, scope); merge of alternatives; arrow.skipped; attempts and failure path; blocked-exit routing; liveness pause; runtime activation cap.  
Out: Dead-path elimination beyond OQ-19; region cancel (ENG-08).  
Paths: `coral/engine/control.py`, `tests/coral/engine/test_loops_joins.py`  
OQ: OQ-12, OQ-19  
Proof: Scripted reducer test: changes requested x3 routes to the at-limit gate, and a blocked exit follows the failure path.

**ENG-06 Run lifecycle, timers and liveness policies** — ENGINE · PH1 · M2 · Critical · M · slice  
Add start, pause, resume, cancel and retry commands, pause reasons and timer policies to the reducer so runs advance without babysitting.  
G: G-06, G-07, G-34 · Hard: ENG-04 · Soft: ENG-05 · K-: K2, K3  
In: start_key to derived run id; pause-reason enum (infra, plan_limit, auth, budget, rejected_calls, liveness, drift); resume on the pinned version; cancel effect chain interrupt -> stop -> omnigent.closed (R-13) and late-submit rejection; retry step; Auto-advance; decision watchdog (remind once, then alert) with a configurable default (OQ-14); rejected-call pause (3 in a row per slot); gate reminders and escalation that never auto-resolve; overdue timer kind; coalescing after laptop sleep.  
Out: Effect execution (DUR-04, SES-*); budget pause (RUL-05); reactions and overdue alerts (ENG-09).  
Paths: `coral/engine/lifecycle.py`, `coral/engine/timers.py`  
OQ: OQ-14, OQ-13, OQ-5  
Proof: Reducer tests: pause, resume, cancel and retry transitions; the watchdog fires once then alerts; three rejected calls pause the slot; a gate reminder never resolves the gate.

**ENG-07 Simulate engine, saved cases and MVP template** — ENGINE · PH1 · M1 · Critical · M · slice  
Run the reducer with stub effects over scripted scenarios, save cases that re-run per version, and ship the TLD-01 template with saved simulations.  
G: G-66, G-69, G-62 · Hard: ENG-04, ENG-05 · Soft: ENG-06 · K-: K1, K2, K3  
In: Scripted labels, list lengths, pass/fail and gate answers; K3-shaped traces; saved cases re-run on each new version; session-count estimate; "Implement with review loop" template (TLD-01) as package data and golden fixture.  
Out: Exhaustive mode (deferred); Simulate UI (WEB-01); PR-review template (ENG-08).  
Paths: `coral/engine/simulate.py`, `coral/templates/implement_review_loop.yaml`, `tests/coral/simulate/`  
OQ: OQ-2, OQ-9  
Proof: Saved cases approved, changes requested x3 -> at-limit gate, and gate reject re-run deterministically on a new template version.

**EVD-01 Evidence-requirement IR and evaluator** — WORKSPACE · PH1 · M1 · High · M · enabler  
Define the evidence IR (K11) and a pure evaluator with final-pass-after-last-change semantics so formatter-then-test cannot livelock.  
G: G-40 · Hard: ENG-01 · Soft: SPK-04 · K+: K11 · K-: K1, K13  
In: Required commands, may-modify flags for formatters, exit-code source rules, per-agent vs per-step scope; observation and fingerprint record shapes; pure evaluator; missing-item messages; tests over temp git repos.  
Out: Capture (EVD-02); detection (EVD-03); Coral-run checks (EVD-04).  
Paths: `coral/evidence/ir.py`, `coral/evidence/evaluate.py`, `tests/coral/evidence/`  
OQ: OQ-10  
Proof: Formatter-then-test passes, test-then-edit fails with 'tests predate the last change', and messages list the missing items.

**HRN-01 Capability registry and bench** — HARNESS · PH1 · M2 · High · M · enabler  
Fill and extend harness capability fields, expose them per spelling, publish the capability registry (K9), and back values with probes and a nightly bench.  
G: G-44 · S: S22, S23, S59, S78 · Hard: FND-01 · Soft: SPK-03, OPS-01 · K+: K9 · K-: K16  
In: K9 first: fields, enums, CapabilityMatrix and effective-enforceability inputs; fill steering, live_queue and compaction; add the ten G-44 fields; guard tests (S22); capabilities_by_spelling on GET /v1/harnesses including native modes (S59); bench probes with offline verdict tests and feature-map rows (S23, S78); coral-bench.yml nightly, claude-sdk first.  
Out: Label computation (RUL-02); Codex live lanes until HRN-05.  
Paths: `omnigent/harness_capabilities.py`, `omnigent/harness_plugins.py`, `omnigent/server/routes/harnesses.py`, `tests/harness_bench/probes/`, `feature-map/harness-acceptance.md`, `.github/workflows/coral-bench.yml`  
OQ: OQ-51  
Proof: tests/test_harness_capabilities.py guard tests pass with the new fields, and GET /v1/harnesses returns capabilities_by_spelling for claude-sdk and claude-native.

**RUL-01 coral.policies, run guard and cost backstop** — INTEGRATION · PH1 · M2 · Critical · M · slice  
Hold rosters, orchestrator limits and paused or cancelled runs by policy, not by prompt, and cap per-session cost before run budgets exist.  
G: G-45, G-46, G-62 · S: S52 · Hard: FND-02 · Soft: SES-01, DUR-03 · K-: K10, K12, K17  
In: coral.policies via policy_modules: step_roster, orchestrator_guard, engine_tool_guard, input-scope deny (internal_only) (R-3); spec grants spawn: false and tools.agents: []; S52 required-policy provider in builder.py (one-line) keyed on coral.run_id: DENY non-coral_* tools while paused or cancelled; any_policies_apply fast path; deterministic per-session cost_budget backstop with no soft ASK, skipped for unpriced models (D34).  
Out: Rule catalog (RUL-03); run budgets (RUL-05); S26 reserved names (EXT-04).  
Paths: `coral/policies/`, `omnigent/runtime/policies/builder.py`  
OQ: OQ-15  
Proof: A paused run's step session is denied a non-coral tool, and an orchestrator session is denied a write tool by its bundle guardrail.

**SES-02 Seam pack A: status-edge observers and engine dispatch** — INTEGRATION · PH1 · M2 · Critical · M · enabler  
Land the upstreamable session seams as one-line registry calls: status-edge observers with origin and outcome, and in-process engine dispatch.  
G: G-19, G-20 · S: S1, S1b, S43, S4, S41, S42 · Hard: FND-01 · Soft: OPS-01, FND-02 · K+: K18 · K-: K16  
In: Status-edge observer registry in session_live_state.py; the scheduled hook becomes one observer; notify after the sticky-failed return; bypasses B1 (relay turn-end) and B2 notify (S1); origin slugs at the 18 _publish_status sites (S1b); turn_outcome on headless runner edges and relay pass-through (S43); S41 keeps the _post_event_impl handle; S42 EngineEventContext (S4 realized); upstream PR opened for the S1 registry.  
Out: Coral observer and turn-end rule (SES-04); S2 (HRN-05); S44 (not planned).  
Paths: `omnigent/server/session_live_state.py`, `omnigent/server/routes/_sessions/helpers.py`, `omnigent/server/routes/_sessions/orchestration.py`, `omnigent/server/routes/sessions/routes_events.py`, `omnigent/server/startup_inputs.py`, `omnigent/server/app.py`, `omnigent/runner/app.py`  
OQ: OQ-41  
Proof: tests/server/integration/test_engine_event_dispatch.py: an observer sees every edge with origin and turn_outcome, and an EngineEventContext message, interrupt and stop pass input policy.

**TLS-01 Seam pack B: engine tool transport** — INTEGRATION · PH1 · M2 · Critical · M · enabler  
Land the extension tool provider and server tool registry so one declaration registers, forwards, relays, pre-approves and instructs coral_* tools.  
G: G-26, G-27 · S: S50, S7, S8, S9, S10, S11, S12, S49 · Hard: FND-01 · Soft: SES-01, SES-02 · K-: K6, K12, K16  
In: omnigent/tools/extensions.py provider (entry-point loaded) feeding ToolManager registration (S7), runner forwarding (S8), native relay advertisement (S9), native pre-approval sites (S11) and framework instructions (S12: headless prompt.py and native launch channels carrying extension text only), each a one-line call; coral_ prefix with collision error; params.coral opt-in read by the provider (TLD-04); server_tools.py registry with ServerToolCall (operation id, actor, provenance) migrating sys_advise_models (S10); S49 runner-provenance predicate; (run, operation_id) transport dedup; upstream PRs for S10 and S50.  
Out: Handlers (TLS-02, TLS-03); enabling native channels (HRN-03, HRN-05).  
Paths: `omnigent/tools/extensions.py`, `omnigent/tools/manager.py`, `omnigent/runner/tool_dispatch.py`, `omnigent/runner/native/orchestration.py`, `omnigent/harnesses/codex_native/app_server.py`, `omnigent/server/server_tools.py`, `omnigent/runtime/prompt.py`, `coral/tools/provider.py`  
OQ: OQ-43  
Proof: A schema-only coral_ test tool declared once is registered, forwarded by the runner, deduplicated on a repeated operation_id, and its text appears in the headless prompt.

**BRD-01 Coral brand skin** — BRAND · PH1 · M1 · High · M · slice  
Make Coral look like Coral by default in light and dark, without disturbing existing heading users, while operator branding still overrides it.  
G: G-78, G-79 · S: S79, S81, S82, S83, S89 · Soft: OPS-01 · K-: K16  
In: omni palette slot data -> Clay Score light and dark, label Coral (TLD-16, X-21); status, chart, CTA and tag remap scoped to the default palette in web/src/brand/coral.css; regenerated palette CSS and updated CSS contract tests; --font-display (Newsreader, bundled offline); --font-heading untouched (R-15); CoralMark, CoralWordmark, CoralHero; BrandLogo fallback; defaults Coral and the hero line (OQ-7); favicon, index.html, apple-touch icon; onboarding art replacing starfish and Otto; Powered-by per OQ-30 (R-1, R-2).  
Out: Sidebar brand row S80 (BRD-02); native shells (BRD-03).  
Paths: `web/src/lib/themePalette.ts`, `web/src/themePalettes.generated.css`, `web/src/index.css`, `web/src/lib/branding.ts`, `web/src/components/BrandLogo.tsx`, `web/src/shell/NewChatDialog.tsx`, `web/src/brand/`, `web/index.html`  
OQ: OQ-7, OQ-30  
Proof: index.css and palette contract tests pass with Coral tokens, and a stored omni preference renders Clay Score.

**BRD-02 Navigation shell, Coral gate and desk headers** — BRAND · PH1 · M1 · High · M · slice  
Let users reach Workflows and Agent Profiles from the sidebar, palette and URLs, gated by /v1/coral/info, under one desk header.  
G: G-80, G-81 · S: S34, S80, S84 · Hard: FND-02 · Soft: BRD-01, API-01 · K-: K7  
In: coralRoutes(prefix) fragment with withPageView for /workflows, /workflows/runs/:runId, /workflows/:workflowKey and /profiles (spike 17); CoralGate reading /v1/coral/info (loading, disabled -> not found, error) instead of FeatureGatedPage; CoralPrimaryNavigation insert and sidebar brand row -> CoralWordmark (S80); useActiveNavItem exclusion; command palette actions; CoralPageHeader (list and full-bleed) with AccentRail on Inbox, Automations and the Coral desks (S84); ?agent= focus convention (R-17); placeholder desks with empty states.  
Out: Desk content (WEB-*); S33 upstream flag.  
Paths: `web/src/App.tsx`, `web/src/shell/Sidebar.tsx`, `web/src/shell/CommandPalette.tsx`, `web/src/pages/InboxPage.tsx`, `web/src/pages/TasksPage.tsx`, `web/src/workflows/routes.tsx`, `web/src/brand/CoralPageHeader.tsx`  
OQ: OQ-27  
Proof: Route tests: /workflows and /profiles render behind CoralGate, disabling Coral hides nav and returns not found, and unknown routes no longer light New session.

**WEB-01 Read-only diagram and Simulate UI** — WEB · PH1 · M2 · High · L · slice  
Render any compiled workflow read-only through one xyflow adapter whose overlay Simulate and the run view share, and let authors simulate and save cases from the UI (TLD-14).  
G: G-71, G-67 · Hard: ENG-01 · Soft: ENG-02, API-01, BRD-02, ENG-07, DUR-02 · K-: K1, K7  
In: Graph model from the compiled IR; one xyflow adapter folder; design taxonomy with Note layout-only; dagre layout in a worker (ELK behind legal); pure layout tests (xyflow OOMs in jsdom); overlay API shared with the run view; states: loading, layout pending, parse error with last valid, too large; Simulate scenario editor from derived info; overlay of visit counts, taken edges and limits; estimate; saved-test badges.  
Out: Editing (WEB-08); ELK; run data (WEB-04).  
Paths: `web/src/workflows/model/`, `web/src/workflows/layout/`, `web/src/workflows/canvas/`, `web/src/workflows/simulate/`, `web/package.json`  
OQ: OQ-30  
Proof: Layout tests render the MVP template graph model, and a scripted simulation overlays visit counts that match the API trace.

**WEB-02 Workflows desk, library and YAML editor** — WEB · PH1 · M2 · High · L · slice  
Let users find, open and edit workflows in YAML with live server markers, a problem list and comment-preserving saves (TLD-15).  
G: G-70, G-68, G-81, G-73 · Hard: BRD-02, API-01 · Soft: DUR-02, WEB-01 · K-: K7, K1  
In: /workflows tabs (Your workflows, Runs, Templates) with loading, empty and error states; intro walkthrough; library list with versions and last run; upload and import actions; Monaco YAML pane via monacoSetup helpers plus the yaml npm CST; markers and problem list from the server validator only; save with 412 conflict dialog; dirty guard; golden round-trip fixtures; YAML editing is the last PR series and the M2 cut line: ship read-only plus upload if it slips.  
Out: Guarantees panel (WEB-06); canvas (WEB-08); MonacoCodeEditor reuse.  
Paths: `web/src/workflows/desk/`, `web/src/workflows/editor/`, `web/src/shell/monacoSetup.ts`, `web/package.json`  
OQ: OQ-9, OQ-27, OQ-33  
Proof: Editing YAML shows server markers on the right range, saving round-trips comments unchanged, and a concurrent edit opens the 412 dialog.

### PH2 Stateful engine and first end-to-end run (to M2)

**DUR-05 Reconciler and restart recovery** — PLATFORM · PH2 · M2 · Critical · M · slice  
Make runs survive server restarts and lost edges by reconciling durable state with live session facts at startup and on a periodic resync.  
G: G-11, G-16, G-87 · Hard: DUR-03, DUR-04 · Soft: ENG-06, SES-04, GTE-01, SES-03 · K-: K2, K4, K5, K19  
In: Startup reconcile, periodic resync and liveness checks; re-lease expired effects; read before resend; trigger gate re-publish; stale runner_last_seen marks slots suspect; resync re-derives turn ends from persisted edge facts; alert on waiting-with-no-elicitation; lazy authority checks with paused(authority_revoked) written as system; commit-boundary fault suite on every lane.  
Out: Runner-loss restart ladder (SES-06); retention (DUR-06).  
Paths: `coral/reconcile/`, `tests/stores/coral/test_commit_boundaries.py`  
OQ: OQ-14  
Proof: A crash at each commit boundary recovers with no duplicate sessions, briefs, policies, worktrees or gate prompts on all four lanes.

**SES-03 Session facade: request-free create and topology** — INTEGRATION · PH2 · M2 · Critical · L · slice  
Create run-owned sessions idempotently without an HTTP request in the ADR-05 topology, guarded by a facade contract suite.  
G: G-18, G-22, G-25 · S: S51 · Hard: SPK-02, SES-01, FND-02 · Soft: DUR-01, PRF-01 · K-: K4, K10, K12, K17  
In: fire.py-subset create: validators, uuid5(effect_key) conversation id through the store (R-9), unique child titles, presentation labels, policies before input, launch and init; stable run session with own_runner step children (TLD-02 option B); S51 parent-wake exemption (omnigent.parent_wake: off); workspace= with no git options (keeps S73 unneeded); unattended-permission preflight; privates imported only through the omnigent.server.routes.sessions facade; L3 contract suite (signature snapshots, facade-vs-HTTP row diff) added to the rehearsal; fallback (top-level family, S35, engine-managed grants) costed as a +3-4 week contingency, not planned.  
Out: Dispatch and turn end (SES-04); fallback build (contingency); S55 (not planned).  
Paths: `coral/omni/sessions.py`, `omnigent/runtime/subagent_block_notifier.py`, `tests/coral/omni/contract/`  
OQ: OQ-32, OQ-17, OQ-47  
Proof: L3 contract suite: creating the same effect twice yields one session, and the facade row matches an HTTP-created row except for allowed fields.

**SES-04 Step turn loop: dispatch and per-mode turn-end detection** — INTEGRATION · PH2 · M2 · Critical · L · slice  
Brief, nudge, interrupt and stop run sessions through _post_event_impl, and decide durably, per mode, when an engine-started turn ended.  
G: G-19, G-20, G-21, G-07 · Hard: SES-02, SES-03 · Soft: DUR-04, HRN-01 · K-: K4, K18, K2, K9, K5  
In: Brief, nudge, feedback, notice, interrupt and stop via _post_event_impl with stable_id on every message; read before resend; ManagedStartupInputs fallback for provisioning sandboxes; Coral status observer with an O(1) binding filter that enqueues TurnFacts off the hot path (built against the K5 queue protocol); per-mode turn-end rule (idle, engine input consumed, assistant reply, mode confirmation, no pending elicitation), claude-sdk first; nudge only engine-started turns, never cancelled ones; ignore archive idle edges; cancel chain interrupt -> stop -> omnigent.closed.  
Out: Native turn ends (HRN-03, HRN-05); runner loss (SES-06).  
Paths: `coral/omni/dispatch.py`, `coral/signals/`, `coral/engine/turn_end.py`  
OQ: OQ-41, OQ-13  
Proof: Typing into a step session never triggers a nudge, while an engine brief's turn end advances the slot exactly once.

**SES-06 Recovery: runner loss, host offline and drift** — INTEGRATION · PH2 · M2 · High · L · slice  
Handle runner loss, host-offline holds and user actions on run sessions by pausing with an explanation and recovering safely (TLD-12).  
G: G-23, G-24 · Hard: SES-04, DUR-05 · Soft: WSP-01, RUL-01 · K-: K4, K2, K13  
In: Liveness from runner_last_seen; wake via ensure_runner_connected or retry_session; paused(infra) during the 72 h hold; never restart inside it; restart = stop, bump session_generation, salvage, reset, new session; the engine relaunches own-runner children itself; drift checks (policy, label, bundle digest) then re-attach or pause; defined outcomes for archive, delete, stop, fork and rename; spike 14 verdict applied.  
Out: Reserved prefixes and guards (EXT-04); native /clear following (HRN-03); S48 (not planned).  
Paths: `coral/recovery/`, `tests/coral/omni/test_recovery.py`  
OQ: OQ-17, OQ-46  
Proof: Killing the implementer's runner pauses the run as paused(infra); Resume creates a new generation after a salvage ref; a deleted run policy pauses the run within one resync.

**SES-05 Walking skeleton and M2 acceptance lane** — INTEGRATION · PH2 · M2 · Critical · M · slice  
Make a thin end-to-end path the first PH2 integration target, then grow it into the M2 journey with injected faults in CI and on a credentialed claude-sdk lane.  
G: G-87 · Hard: FND-04, SES-04, SES-06, TLS-02, TLS-03, GTE-01, DUR-05, EVD-02, WSP-01, PRF-01, HRN-02, API-02 · Soft: WEB-04, GTE-02, SPK-03 · K-: K2, K4, K6, K14  
In: Skeleton target first: one-step workflow -> real session -> coral_submit_handoff -> gate -> API answer -> end, surviving a server kill; built against skeleton slices and stubs, with a burn-down list; E2E-1 (Tier B mock LLM calls submit; gate answered via API) and E2E-2 (SIGTERM between brief and handoff; no second session); M2 journey with injected faults: runner kill, loop forced to limit 3, pause, resume, cancel and retry; nightly credentialed claude-sdk run of the MVP template; mock base-URL lane if spike 4 passes.  
Out: Native E2E-3 and E2E-4 (HRN-03, RUL-04); browser E2E.  
Paths: `tests/e2e/coral/`, `.github/workflows/coral-e2e.yml`, `.github/workflows/coral-bench.yml`  
OQ: OQ-51  
Proof: E2E-1 and E2E-2 are green in CI, and the credentialed nightly passes the M2 journey five runs in a row.

**TLS-02 coral_submit_handoff** — INTEGRATION · PH2 · M2 · Critical · M · slice  
Accept or reject step handoffs with a bounded synchronous evidence scan, slot-state dedup and generation fencing, with actionable rejections.  
G: G-28 · Hard: TLS-01, ENG-04, DUR-03 · Soft: EVD-02, SES-04, SPK-03 · K-: K6, K2, K5, K11  
In: Fields: activation_id, status done|blocked, report, artifacts, derived label or items, kind handoff|refresh_note; schema check -> reducer command -> one short transaction; bounded synchronous evidence-ledger scan (bound from spike 7) under a per-slot evaluating lease (X-15); rejection codes with reasons; per-slot rejected counter; session_generation check; receipts and slot-state dedup (X-5, R-10); post-cancel submits rejected; skeleton slice first.  
Out: Coral-run checks (EVD-04); refresh_note handling (SES-07).  
Paths: `coral/tools/handlers/submit_handoff.py`, `tests/coral/tools/`  
OQ: OQ-12, OQ-10  
Proof: A duplicate submit returns the original receipt, a stale-generation submit is rejected, and a submit before passing commands lists the missing items.

**TLS-03 Orchestrator: decisions, choose_arrow and ask_user** — INTEGRATION · PH2 · M2 · Critical · L · slice  
Let the orchestrator decide only through coral_choose_arrow and ask through coral_ask_user, under a seeded claude-sdk profile that cannot do the work.  
G: G-29, G-30, G-32, G-33 · Hard: TLS-02, PRF-01, ENG-05 · Soft: GTE-01, RUL-01, SES-04 · K-: K6, K12, K14, K2  
In: Seeded orchestrator on claude-sdk with no os_env (no sys_os_* tools); orchestrator_guard in bundle guardrails plus a label check in the handler (TLD-05, X-11); decision requests listing legal labels and the handoff collection (D9); coral_choose_arrow with a generic label validated server-side, reason and optional items (R-11); chat interleaving with claude-sdk mid-turn buffering; user-induced illegal calls not counted; lazy creation; reminders re-check state; coral_ask_user non-blocking: durable question row, form elicitation, [Coral answer] delivery that suspends the watchdog; vendor AskUserQuestion denied in run sessions; cut line if M2 slips: ask_user first.  
Out: Message and assign tools (TLS-04); orchestrator refresh (SES-07).  
Paths: `coral/tools/handlers/choose_arrow.py`, `coral/tools/handlers/ask_user.py`, `coral/orchestrator/`, `coral/profiles/seeds/orchestrator/`  
OQ: OQ-13, OQ-14, OQ-7  
Proof: With a mock orchestrator, an illegal label is rejected with allowed_values, a legal one routes the loop, and an ask_user answer arrives as a message without blocking the turn.

**GTE-01 Gate elicitation surface (seam pack C)** — INTEGRATION · PH2 · M2 · Critical · M · slice  
Surface durable gate visits, questions and budget prompts as stable-id elicitations on the run session and route answers back once, with resolver identity (TLD-09).  
G: G-35, G-34 · S: S5, S6, S6a, S6b · Hard: ENG-04, SES-03, DUR-03 · Soft: SPK-02 · K-: K14, K4, K10, K2  
In: Gate row written before publish; S5 elicitation observers as a list with per-observer isolation; S6a request-free publish with stable ids coral_gate_<visit>; S6b verdict-handler registry and resolver identity; CAS resolution with visit token; stale answers refused as no longer current; re-publish on startup and on run-session replacement; owner-only authority (LEVEL_EDIT, OQ-4); ApprovalCard and /approve reused with authored outcome labels only; native-bridge bearer risk labelled (D25); ask_user and budget forms on the same path; never policy ASK (R-7).  
Out: Inbox kind (GTE-02); external delivery (GTE-03); team approvers (EXT-04).  
Paths: `omnigent/runtime/pending_elicitations.py`, `omnigent/server/routes/sessions/routes_events.py`, `omnigent/server/routes/_sessions/orchestration.py`, `omnigent/server/routes/sessions/routes_elicitations.py`, `coral/gates/`  
OQ: OQ-3, OQ-4, OQ-5  
Proof: A duplicate answer advances once, a stale answer is refused, and after a server restart the gate is re-published with the same id.

**GTE-02 Workflow Inbox kind and run notifications** — WEB · PH2 · M2 · Critical · M · slice  
Show gates, questions and pauses as an Inbox workflow kind with server-side ack, and notify at run level while the app is open.  
G: G-36 · S: S36, S37, S85 · Hard: GTE-01, BRD-02, DUR-01 · Soft: API-02, ENG-06 · K+: K19 · K-: K7, K14, K10  
In: K19 alert model first: coral_alerts, ack, actions, deep-link payload without secrets; GET /v1/coral/inbox and POST .../ack with server-side ack (X-30); alert producers for gates, questions, pauses and the watchdog; WorkflowInboxCard with run actions (open, resume, cancel, extend); sidebar count; CoralRuntimeProvider mount (S85); suppress per-step turn-end OS notifications for coral.run_id sessions while keeping elicitation ones (S36); deep-linked run notifications; 'App must be open' notice (TLD-09, R-6).  
Out: Webhook and email (GTE-03); push (GTE-04); localStorage read state.  
Paths: `web/src/pages/InboxPage.tsx`, `web/src/hooks/useIdleNotifications.ts`, `web/src/main.tsx`, `web/src/workflows/inbox/`, `coral/api/inbox.py`  
OQ: OQ-24, OQ-6  
Proof: A gate alert appears in the Inbox, acking it on one client clears it on another, and no per-step turn-end notification fires for run sessions.

**EVD-02 claude-sdk evidence capture and done-when at handoff** — WORKSPACE · PH2 · M2 · Critical · L · slice  
Record each claude-sdk command's exit code and the workspace state after it durably, and evaluate done-when at handoff (TLD-10).  
G: G-38, G-39, G-40 · S: S68, S69 · Hard: EVD-01, SPK-04, DUR-01, WSP-01 · Soft: SPK-03 · K-: K11, K13, K6  
In: S68 tool-completion observer registry with one-line calls at the four pr_observer sites; claude-sdk site enabled; S69 transport: runner /mcp/execute response field plus server TOOL_RESULT hook, and an external_workspace_observations event with an outbox reporter; coral_command_observations with command, exit code and L1 fingerprint; one L1 algorithm per command and at submit (never bare /changes porcelain); runner-path exit-status preservation test; evidence result rows; missing-item feedback through TLS-02.  
Out: L2 and the host backend (WSP-02); native and Codex observation sites (HRN-03, HRN-05); Coral-run checks (EVD-04).  
Paths: `omnigent/runner/tool_dispatch.py`, `omnigent/runtime/harnesses/_executor_adapter.py`, `omnigent/runner/mcp_routes.py`, `coral/evidence/capture.py`  
OQ: OQ-10  
Proof: A claude-sdk step that edits after running tests is rejected at handoff, then accepted after re-running, with exit codes recorded per command.

**EVD-03 Repository command detection and confirmation** — WORKSPACE · PH2 · M2 · High · M · slice  
Detect test, lint, format and typecheck commands in a bound repo, let the author confirm them, and snapshot them into the workflow version.  
G: G-41, G-42 · Hard: DUR-01, SES-01 · Soft: EVD-01, WSP-01 · K-: K4, K11  
In: Parsers for package.json, pyproject.toml, justfile, Makefile, CI files and pre-commit, read request-free via host fs_request; per-repo command patterns; confirm API; confirmed commands snapshotted into the workflow version (X-32); picker backend (TLD-19).  
Out: LLM translation (deferred); picker UI (WEB-03); Coral-run checks (EVD-04).  
Paths: `coral/evidence/detect.py`, `coral/api/repos.py`, `tests/coral/evidence/fixtures/`  
OQ: OQ-38  
Proof: Detection over fixture repos returns the expected commands, and confirming them snapshots into a new version.

**PRF-01 Step bundles, seeded profiles and hidden engine agents** — HARNESS · PH2 · M2 · Critical · L · slice  
Run every step from a generated, content-addressed agent pinned by digest, keep those rows out of pickers, and make claude-sdk reviewers read-only by sandbox (TLD-05).  
G: G-47, G-50, G-51, G-52 · S: S54 · Hard: SES-01, DUR-01 · Soft: RUL-01 · K-: K12, K10  
In: coral/omni/bundles.py deterministic tar; uploaded_agent_for content-addressed rows recorded in coral_step_agents; seeded Coral built-ins (orchestrator, implementer, reviewer) pinned by digest; slot-start drift check (spike 18); hygiene: tool groups off, spawn: false, skills none for hermetic steps, agent_session_sharing none, vendor ask tools denied; provider-reference auth; required policies in bundle guardrails; reviewer os_env.sandbox.write_paths: [] plus read_only_os (moved to M2 for TLD-01, R-23); S54 picker and scope=user exclusion for coral__ rows in the store and web hooks; golden bundle tests.  
Out: User profile revisions (PRF-02); desk (WEB-07); S53 mutation guards (EXT-04).  
Paths: `coral/omni/bundles.py`, `coral/profiles/seeds/`, `omnigent/stores/agent_store/sqlalchemy_store.py`, `omnigent/server/routes/builtin_agents.py`, `omnigent/server/bundles.py`, `web/src/hooks/useAvailableAgents.ts`  
OQ: OQ-37, OQ-48  
Proof: The same step yields the same bundle digest across runs, a reviewer write is denied by the sandbox, and coral__ rows are absent from GET /v1/agents?scope=user.

**HRN-02 claude-sdk credential guard** — HARNESS · PH2 · M2 · Critical · S · slice  
Start run-owned claude-sdk sessions only on API-key or provider auth pinned per run, with no vendor workspace tools (TLD-07).  
G: G-54 · S: S13, S63, S21 · Hard: SPK-03, SES-01 · Soft: PRF-01, HRN-01, SPK-01 · K-: K12, K9  
In: Spawn-env flag and executor refusal of subscription OAuth for run-owned sessions (S13); provider references only, never literal keys; operator bindings respected; preflight from harness_accounts; account pinned per run; S63 contract test that no vendor workspace tools are exposed; S21 PreToolUse hook only if spike 1 fails; spikes 19 and 20 applied; honest preflight copy for subscription-only users (they wait for claude-native at M3).  
Out: claude-native subscription path (HRN-03); model-access settings and plan-limit pauses (HRN-04).  
Paths: `omnigent/runtime/workflow.py`, `omnigent/inner/claude_sdk_harness.py`, `omnigent/inner/claude_sdk_executor.py`, `coral/harness/preflight.py`  
OQ: OQ-28  
Proof: A run-owned claude-sdk session with only subscription credentials is refused at preflight and at spawn.

**WSP-01 Repo bindings, run worktree and restart safety** — WORKSPACE · PH2 · M2 · Critical · L · slice  
Own each run's worktree request-free, commit accepted handoffs, and salvage and reset before retries, behind the WorkspaceOps session-shell backend; import workflows from the repo.  
G: G-58, G-59, G-68 · S: S71, S72 · Hard: SPK-04, SES-01, DUR-01 · Soft: SES-03 · K-: K13, K4, K10  
In: S71 reaper guard on fs_request and fs_write as the first PR (may land in PH1; upstreamable bug fix); repo bindings (host, repo root, traits) and binding API; deterministic coral/r-<run>/base created request-free and adopted on retry; S72: create_worktree returns head_commit, adds detached+commit mode and optional worktree_parent; start commit recorded; sessions bound with workspace= and no git options, with an invariant test (S73 stays unneeded); engine commits with trailers at accepted handoffs (hook policy OQ-39); salvage refs refs/coral/salvage/*; reset --hard and clean -fd before retry; K13 session-shell backend; removal, retention and disk cap; workflow import via host fs_request read (TLD-06).  
Out: Per-agent worktrees and merges (WSP-03); host op channel (WSP-02); per-worktree setup (EVD-04).  
Paths: `omnigent/host/connect.py`, `omnigent/host/git_worktree.py`, `omnigent/host/frames.py`, `omnigent/server/routes/_host_worktree.py`, `coral/omni/worktrees.py`, `coral/workspace/`  
OQ: OQ-18, OQ-39, OQ-44  
Proof: Retrying a step salvages its edits to refs/coral/salvage/*, resets to the step start commit, and deleting a run session leaves the branch intact.

**API-02 Runs API, gate answers, preflight and run stream** — PLATFORM · PH2 · M2 · Critical · L · slice  
Serve runs, lifecycle actions, gate answers and preflight, and tail the run log as a resumable SSE stream.  
G: G-74, G-75, G-76, G-07, G-34 · Hard: DUR-02, DUR-03, API-01 · Soft: ENG-06, SES-03, HRN-02, GTE-01 · K-: K7, K8, K3, K4  
In: Runs list, get and idempotent start with start_key; pause, resume, cancel and retry actions; gate answers with visit_token; preflight: V10 configured_harnesses, harness_accounts auth, host online, validity, estimate; SSE tail of the run log with seq, Last-Event-ID, heartbeat and [DONE]; access through the run session.  
Out: Take-over endpoints (SES-07); amendments (ENG-10); budgets (RUL-05).  
Paths: `coral/api/runs.py`, `coral/api/stream.py`, `tests/coral/api/`  
OQ: OQ-4, OQ-16  
Proof: Reconnecting the run stream with Last-Event-ID loses no entries, and a repeated start with the same start_key returns the same run.

**WEB-03 Templates, Use-template and start-run dialogs** — WEB · PH2 · M2 · Critical · L · slice  
Take a new user from the gallery to a saved, simulated workflow on their repo with confirmed done-when commands, then start a run behind a preflight that names every fix.  
G: G-69, G-42, G-76 · Hard: WEB-02, DUR-02 · Soft: EVD-03, API-02, WSP-01, PRF-01, ENG-07, HRN-02 · K-: K7, K11  
In: Gallery tab and Use-template dialog (name, repo, parameters, model per role); detected-command picker and confirmation sheet stored as K11 (TLD-19); start-run dialog: request, host/repo/base via WorkspacePickerDialog and useHostWorktrees, version pin, estimate, activation cap; preflight errors that name each fix; idempotent start; states: gallery failed, host offline, nothing detected.  
Out: Money budgets (RUL-05); profile picker (WEB-07); LLM translation (deferred).  
Paths: `web/src/workflows/templates/`, `web/src/workflows/start/`  
OQ: OQ-2, OQ-16, OQ-18  
Proof: Use template on a fixture repo shows the detected commands, confirming saves a version, and a failing preflight lists the fix.

**WEB-04 Runs list and live run view** — WEB · PH2 · M2 · Critical · L · slice  
Let users see where a run is, why it went that way, what passed and what it waits on, live, without reading a transcript.  
G: G-77, G-75 · Hard: WEB-01, API-01 · Soft: API-02, GTE-01, EVD-02 · K-: K7, K8, K3  
In: Stream client with id: parsing, stream-slot acquisition and polling fallback; runs list with all states; header with lifecycle actions; state overlay with loop counters and open gates; inspector tabs (step, decision reason, gate via ApprovalCard, log); evidence list with missing items; timeline; pause banners with reason, resume condition and actions; first slice: a log list for the walking skeleton.  
Out: Agent panes and steering (WEB-05); promise labels (WEB-06); structure layers and why-not arrows (WEB-10).  
Paths: `web/src/workflows/runs/`, `web/src/workflows/stream/`  
OQ: OQ-17, OQ-23  
Proof: Against a recorded run log, the view shows the loop counter, the open gate and evidence, and resumes after a dropped stream with no gaps.

**WEB-05 Run agent panes and steering** — WEB · PH2 · M2 · High · M · slice  
From the run view, let users open any agent or the orchestrator, type in with honest hints, and get back to the run.  
G: G-77 · S: S86 · Hard: WEB-04 · Soft: SES-03, SES-04 · K-: K7, K10  
In: SubagentTabPane via ?agent=&node= query params, never :conversationId (R-17); current orchestrator pane; 'read after current turn' hint for claude-sdk mid-turn buffering; run-owned banner; 'Part of run' chip in ChatHeader (S86); 'Step waiting on you'.  
Out: Stitched orchestrator and take-over controls (WEB-10).  
Paths: `web/src/workflows/runs/agents/`, `web/src/shell/ChatHeader.tsx`, `web/src/shell/SubagentTab.tsx`  
OQ: OQ-13, OQ-17  
Proof: Opening a step from the run view focuses its session via ?agent= without switching AppShell into chat mode, and the chip links back to the run.

### PH3 Profiles, capabilities and enforcement (to M3)

**PRF-02 Profile revisions and pinning** — HARNESS · PH3 · M3 · High · M · slice  
Make profiles pinned, immutable revisions over custom agents so edits never leak into versioned or running workflows.  
G: G-50, G-14 · S: S66 · Hard: PRF-01, DUR-01 · K-: K12, K5  
In: Profile = agent row plus params.coral metadata (X-12 recommendation); coral_profile_revisions with byte copy and digest through the migration train; version-to-revision pins; drift check at slot start; edits by reinstall create new revisions; /v1/coral/profiles API with used-by; spike 18 result; optional S66: redacted params.coral in agent summaries.  
Out: Desk UI (WEB-07); git import (EXT-03).  
Paths: `coral/profiles/`, `coral/db/migrations/versions/`, `coral/api/profiles.py`  
OQ: OQ-37  
Proof: Editing a profile mid-run leaves the run on rev N and the next run uses rev N+1.

**RUL-02 Capability-aware validation and promise labels** — ENGINE · PH3 · M3 · High · M · slice  
Compute the four promise labels per checked part and mode from the IR and the capability registry, and validate enforceability (V9), so nothing over-claims (TLD-11).  
G: G-73, G-47 · Hard: HRN-01, ENG-03, EVD-02 · Soft: RUL-03, PRF-01 · K-: K9, K1, K11, K15  
In: Enforced, Verified, Requested and Judgment per checked part and mode (D14); V9 per-mode enforceability: native unenforceable until S14, headless codex until S20, codex-native until S15; read-only Enforced only on claude-sdk with write_paths: []; otherwise Verified by before/after fingerprints (X-28); property test that an unknown capability never yields Enforced; pure label API with a frozen matrix fixture.  
Out: Panel UI (WEB-06); rule compilation (RUL-03).  
Paths: `coral/validate/labels.py`, `coral/validate/v9.py`, `tests/coral/validate/test_labels.py`  
OQ: OQ-24  
Proof: Over registry x fixtures no unknown capability yields Enforced, and switching a reviewer to claude-native turns read-only from Enforced to Verified.

**RUL-03 Rules catalog v1: Required and Guidance** — INTEGRATION · PH3 · M3 · High · L · slice  
Let authors add Required and Guidance rules from a typed template catalog over existing builtins, compiled into bundle guardrails (TLD-19).  
G: G-48 · Hard: RUL-01, PRF-01, ENG-03 · K+: K15 · K-: K9, K12  
In: K15 first PR: template id, params, target builtin or policy, Required vs Guidance, enforceability inputs; about 8 templates: worktree_guard, blast_radius, mode-aware egress allowlist (R-12), CEL ask-before-path, never force-push; workflow, step and profile scopes; an unenforceable Required rule fails validation with remedies; compile into bundle guardrails; confirmation API.  
Out: Free-text LLM translation (deferred); reactions and V8 (ENG-09).  
Paths: `coral/rules/catalog/`, `coral/rules/compile.py`, `coral/api/rules.py`  
OQ: OQ-38  
Proof: A Required 'protect infra/**' rule compiles into the step bundle's guardrails and blocks a write in a claude-sdk run.

**RUL-04 Native fail-closed hooks** — HARNESS · PH3 · M3 · Critical · M · slice  
Make native policy hooks fail closed for run-owned sessions and carry sub-agent identity, the prerequisite for any native Enforced label.  
G: G-49 · S: S14, S16 · Hard: HRN-01, RUL-01, SPK-03 · K-: K9  
In: fail_closed_hook_output for run-owned sessions; early returns deny; bridge-config policy_failure_mode; onFailure: block; explicit PreToolUse timeout; hooks-installed check (ap_server_url); CLI-version gating; S16 sub-agent identity in the policy context; spike 6 verdict applied; E2E-4.  
Out: S15 codex-native refusal (HRN-05); S21 (HRN-02, conditional).  
Paths: `omnigent/native/native_policy_hook.py`, `omnigent/harnesses/claude_native/hook.py`, `omnigent/harnesses/codex_native/hook.py`, `omnigent/harnesses/claude_native/bridge.py`  
OQ: OQ-46  
Proof: E2E-4: blackholing the policy endpoint mid-step blocks the next native tool call.

**HRN-03 claude-native step mode** — HARNESS · PH3 · M3 · High · L · slice  
Offer claude-native steps for subscription users behind fail-closed hooks, with launch-time framework text, Stop-hook turn end, /clear handling and honest labels (TLD-07).  
G: G-55, G-39, G-24 · S: S3, S45, S64 · Hard: RUL-04, PRF-01, SES-04, TLS-01 · Soft: RUL-02, HRN-01, EVD-02 · K-: K9, K12, K11, K18  
In: Enable the S12 native launch channel and the S9/S11 relay and pre-approval for coral_* tools landed by TLS-01; S3 terminal_launch_args derivation; Stop-hook turn end; S45 supersession observer: follow native /clear rotation and re-attach policies and labels (OQ-46); S64 egress auto-add of provider hosts; PostToolUse observation hints into the S68/S69 path; separate sessions, steps only (never the orchestrator); E2E-3.  
Out: codex-native (HRN-05); claude-native orchestrator; plan-limit pause (HRN-04).  
Paths: `omnigent/runner/native/orchestration.py`, `omnigent/native/_native_supersession.py`, `omnigent/server/routes/_sessions/helpers.py`, `omnigent/inner/egress/rules.py`, `coral/harness/claude_native.py`  
OQ: OQ-28, OQ-35, OQ-46  
Proof: E2E-3: a claude-native step under a mock model runs Bash, calls coral_submit_handoff, and turn_completed advances the run.

**HRN-04 Model access, plan limits and usage signal** — HARNESS · PH3 · M3 · High · M · slice  
Let users choose how Claude is reached, and pause runs at plan limits with a visible reset time and automatic resume.  
G: G-57, G-54 · S: S24 · Hard: HRN-02, ENG-06 · Soft: HRN-03, PRF-02, WEB-07 · K-: K9  
In: Onboarding and settings route API key vs subscription -> claude-native; per-profile auth badge; S24 usage-limit signal with reset time: claude-sdk RateLimitEvent, ExecutorError reset time, native forwarders (the Codex branch lands with HRN-05); paused(plan_limit) showing paused-until with auto-resume; mock-provider probe.  
Out: Account switching; Codex limits beyond the shared signal (HRN-05).  
Paths: `omnigent/inner/executor.py`, `omnigent/inner/claude_sdk_executor.py`, `omnigent/harnesses/claude_native/forwarder.py`, `web/src/workflows/settings/`  
OQ: OQ-28  
Proof: With a mock provider, a rate-limit event pauses the run as plan_limit with the reset time, and it resumes after it.

**WEB-06 Guarantees panel and rule authoring UI** — WEB · PH3 · M3 · High · M · slice  
Show 'What Coral guarantees' with four per-mode labels, and let authors pick catalog rules with confirmation.  
G: G-73, G-48 · Hard: RUL-02, WEB-02 · Soft: RUL-03 · K-: K9, K15, K7  
In: Guarantees panel and on-box label chips; labels follow mode changes; rule picker with Required vs Guidance and per-mode labels; translation status chips; confirmation sheet.  
Out: Free-text rules (deferred); label computation (RUL-02).  
Paths: `web/src/workflows/guarantees/`, `web/src/workflows/rules/`  
OQ: OQ-24  
Proof: Switching a step's mode in the editor updates its chips, and a Required rule the mode cannot enforce shows a problem with remedies.

**WEB-07 Agent Profiles desk and picker** — WEB · PH3 · M3 · High · M · slice  
Ship /profiles as a lens over custom agents and a cmdk picker with capability chips, used-by and source badges.  
G: G-53 · Hard: PRF-02, BRD-02 · Soft: HRN-01 · K-: K7, K9, K12  
In: /profiles list over custom agents plus Coral metadata, with all states; edits by reinstall ('running runs keep rev N'); capability chips reading Claude, not Claude Code; cmdk picker in the editor and the template and start dialogs.  
Out: localStorage profiles (R-16); editing params via PATCH.  
Paths: `web/src/workflows/profiles/`, `web/src/pages/settings/`  
OQ: OQ-27, OQ-37  
Proof: Picking a profile for Review in the editor shows its capability chips and used-by count, and editing it creates rev N+1.

### PH4 Trust and structure (to M4)

**WSP-02 Host workspace-op channel and L2 fingerprints** — WORKSPACE · PH4 · M4 · Critical · L · enabler  
Run sessionless workspace ops on hosts with true exit codes, move commit, reset and salvage there, and make L2 the authoritative fingerprint.  
G: G-38, G-59 · S: S40, S40b · Hard: WSP-01, SPK-04 · Soft: EVD-02 · K+: K20 · K-: K13, K11  
In: K20 frames first; capability token workspace_ops:1; reaper-guarded host dispatcher; server proxy, pending map, job events and job journal; S40b entry-point op registry; ops: probe, head, fingerprint L1/L2, diff_paths, commit_all, salvage, reset_to, branch; L2 write-tree on a temporary index (tracked plus untracked-not-ignored); version-skew fallback to the session-shell backend; adapter swap with the evaluator unchanged; exit-status contract test.  
Out: Exec jobs (EVD-04); merges (WSP-03); fetch and push.  
Paths: `omnigent/host/frames.py`, `omnigent/host/connect.py`, `omnigent/server/routes/_host_workspace_ops.py`, `omnigent/server/host_registry.py`, `coral/host_ops/`  
OQ: OQ-44  
Proof: The evaluator gives identical verdicts on both K13 backends, and L2 detects a re-edit that L1 porcelain missed.

**EVD-04 Coral-run checks, verifier and worktree setup** — WORKSPACE · PH4 · M4 · High · L · slice  
Run the pinned checks in a Coral-controlled checkout, flag tampering, feed results back into attempts, and offer a verifier step.  
G: G-43, G-58 · Hard: WSP-02, EVD-03, EVD-02 · Soft: ENG-06 · K-: K13, K20, K11  
In: Sandboxed exec jobs with caps on the host channel; detached checkout via the S72 detached mode running the snapshotted commands (X-32); JUnit capture; integrity diff on test and config edits; check-to-attempt loop; read-only verifier step pattern labelled Judgment; per-worktree setup (.coral/repo.yaml, .worktreeinclude fallback).  
Out: Hidden held-out tests; LLM rubric judges; multi-writer merges (WSP-03).  
Paths: `coral/checks/`, `coral/host_ops/exec.py`, `coral/templates/patterns/verifier.yaml`  
OQ: OQ-44, OQ-10  
Proof: An agent that edits package.json scripts is flagged by the integrity diff, and checks re-run in the detached checkout feed the attempt.

**WSP-03 Per-agent worktrees and serial merges** — WORKSPACE · PH4 · M4 · High · L · slice  
Give each code-writing agent its own worktree, merge serially into the run worktree, and resolve conflicts in the agent's worktree with post-merge checks.  
G: G-60 · Hard: WSP-02, EVD-04, TLS-04, ENG-08 · K-: K13, K20, K11  
In: agent-<n> worktrees per writer (D11); serial merges at close or join; conflict sub-state resolved in the agent's own worktree via coral_assign_task (D10); mandatory post-merge Coral-run checks (D8); submodule and LFS probe.  
Out: Unchecked parallel merges; managed sandboxes (WSP-04).  
Paths: `coral/workspace/merge.py`, `coral/host_ops/merge.py`  
OQ: OQ-40  
Proof: Two writers' branches merge serially, a conflict is resolved in the agent's worktree, and post-merge checks run before the step closes.

**ENG-08 Repeat-for-each, parallel regions and PR-review showcase** — ENGINE · PH4 · M4 · High · L · slice  
Execute repeat-for-each and parallel split and join with region cancel, and ship the PR-review loop showcase (TLD-01).  
G: G-08, G-09 · Hard: ENG-05, ENG-06 · K-: K1, K2, K3  
In: Repeat contract: order, empty list, per-item failure, concurrency, per-item gates and batching, '3 of N' progress; parallel split and join with region cancel and failure paths inside regions; validator and Simulate support; PR-review loop template; E2E-5.  
Out: Groups (ENG-09); merges (WSP-03).  
Paths: `coral/engine/repeat.py`, `coral/engine/regions.py`, `coral/templates/pr_review_loop.yaml`, `tests/e2e/coral/test_parallel.py`  
OQ: OQ-2, OQ-19, OQ-40  
Proof: E2E-5: a parallel split with two agents joins once and a duplicate signal is a no-op; repeat over three items reports 3 of 3.

**ENG-09 Groups, saved blocks, Wait and reactions** — ENGINE · PH4 · M4 · Medium · L · slice  
Let authors group steps with inherited rules, save blocks, use Wait timers, and attach 'when X, do Y' reactions such as overdue alerts.  
G: G-10, G-48, G-06 · Hard: ENG-03, ENG-06, RUL-03 · Soft: ENG-08, GTE-02 · K-: K1, K2, K15, K19  
In: Group IR with entry and exit; saved blocks library; V8 inner-stricter rule inheritance; hidden Wait kind with timers; reaction templates on timers and run events; expected_duration x factor overdue alerts into the Inbox.  
Out: Sub-workflow invocation (deferred); group canvas UI (WEB-08, WEB-09); reactions that change the graph.  
Paths: `coral/model/groups.py`, `coral/engine/reactions.py`, `coral/validate/v8.py`  
OQ: OQ-19, OQ-38  
Proof: The validator rejects a group whose inner rule is looser (V8), and a simulated overdue step raises an Inbox alert from a reaction.

**TLS-04 Messaging and assignment tools** — INTEGRATION · PH4 · M4 · Medium · M · slice  
Let parallel agents and the orchestrator message through the engine, use 'up to' rosters, and re-task a member to resolve conflicts.  
G: G-31 · Hard: TLS-03, SES-04 · Soft: ENG-08 · K-: K6, K4  
In: coral_message_agent: engine-routed via dispatch with a [Coral message from ...] prefix, isolation flags, rate limit, steer-vs-closing race; coral_assign_agents for 'up to' rosters; coral_assign_task to re-task a member for conflict resolution (D10).  
Out: sys_session_message reuse; EGM resolutions (EXT-02).  
Paths: `coral/tools/handlers/message_agent.py`, `coral/tools/handlers/assign.py`  
Proof: A message to a closing step is refused cleanly, and assign_task re-tasks a member inside its own worktree.

**SES-07 Slot control: refresh and take-over** — INTEGRATION · PH4 · M4 · Medium · L · slice  
Refresh long sessions by slot restart with a refresh note, and let a user take over a step and hand it back (TLD-13).  
G: G-63, G-64 · S: S25, S27 · Hard: SES-06, HRN-01, EVD-02, ENG-06 · Soft: WSP-02 · K-: K4, K9, K6, K11  
In: Per-mode threshold refresh_threshold_bp=7000 below native auto-compaction (D1.7); wait for turn end; request refresh_note; slot restart: create, brief, close the old session, publish a notice; S25 'refresh' reason literal and web handler; S27 reaper retests (label exemption only if the retest fails); taken_over(by) state with reminders, refresh and auto-advance off; user input detected by stable_id; hand-back re-fingerprints and re-evaluates done-when; salvage guard; endpoints.  
Out: Fork-based refresh (S47, not planned); stitched transcript and controls UI (WEB-10); multi-user take-over.  
Paths: `coral/slots/refresh.py`, `coral/slots/takeover.py`, `omnigent/server/schemas.py`, `omnigent/server/pane_reaper.py`  
OQ: OQ-11, OQ-46  
Proof: A step crossing the threshold restarts with its refresh note, and a taken-over step hands back with a fresh fingerprint and done-when result.

**GTE-03 External notification connector (webhook first)** — INTEGRATION · PH4 · M4 · High · M · slice  
Deliver unattended gates and pauses outside the app through an outbox-driven connector, webhook first, then email or Slack DM.  
G: G-37 · Hard: GTE-02, DUR-04 · Soft: GTE-01 · K-: K19, K5, K7  
In: Per-user channel config and settings UI; outbox-driven delivery, idempotent per channel; secret-free deep links; webhook first, then email or Slack DM.  
Out: Push (GTE-04); slack-originated sessions.  
Paths: `coral/notify/`, `web/src/workflows/settings/notifications/`  
OQ: OQ-6  
Proof: An unattended gate posts one webhook (retries stay idempotent) whose deep link opens the gate.

**WEB-08 Canvas editing core** — WEB · PH4 · M4 · Medium · L · slice  
Let users draw and rewire workflows on the canvas while the YAML keeps its comments and confirmed translations.  
G: G-72 · Hard: WEB-01, WEB-02 · Soft: WEB-07, RUL-03 · K-: K1, K7  
In: Palette; connect, move and delete as canvas intents; intents -> comment-preserving CST patches; layout file keyed by stable ids; one undo stack shared with the YAML pane; server validation; golden round-trips.  
Out: Inspectors (WEB-09); mobile editing.  
Paths: `web/src/workflows/canvas/edit/`, `web/src/workflows/editor/patches/`  
OQ: OQ-22  
Proof: Adding and rewiring a step on the canvas produces a YAML diff that touches only those lines and keeps every comment.

**WEB-09 Canvas inspectors and accessible outline** — WEB · PH4 · M4 · Medium · L · slice  
Make every property editable in an inspector, and give keyboard and screen-reader users an outline view with full parity.  
G: G-72 · Hard: WEB-08 · Soft: WEB-07, WEB-06, ENG-09, WEB-03 · K-: K1, K9, K15  
In: Step, arrow, gate, decision and group inspectors; embedded profile picker, rules panel and done-when picker; outline tree with keyboard and screen-reader parity; a11y tests.  
Out: Freeform layout tools; real-time co-editing.  
Paths: `web/src/workflows/canvas/inspectors/`, `web/src/workflows/outline/`  
OQ: OQ-22  
Proof: Every inspector edit is reachable from the outline by keyboard alone, and an axe check of the outline passes.

**WEB-10 Run view depth and structure visuals** — WEB · PH4 · M4 · Medium · M · slice  
Show repeats, regions, groups, join waits and why-not-taken arrows on diagrams, Simulate and runs, plus take-over and refresh in the run view.  
G: G-77, G-08, G-67 · Hard: WEB-04 · Soft: ENG-08, SES-07, ENG-10, WEB-05 · K-: K8, K3, K7  
In: Overlay layers: '3 of N' repeat badges, region frames, groups, join waits; why-taken and why-not-taken arrows; take-over controls; stitched orchestrator segments with refresh dividers; versions tab.  
Out: Run sharing (EXT-04); mobile layouts.  
Paths: `web/src/workflows/canvas/overlay/`, `web/src/workflows/runs/`  
OQ: OQ-23  
Proof: A recorded PR-review run renders '3 of N' badges and a why-not-taken explanation on a skipped arrow.

### PH5 Production readiness (to M4)

**HRN-05 codex-native step mode** — HARNESS · PH5 · M4 · Medium · L · slice  
Enable codex-native steps with terminal turn outcomes, refusal without hooks and an explicit unattended stance.  
G: G-56, G-20 · S: S2, S15, S62 · Hard: RUL-04, HRN-01, SES-04, TLS-01 · Soft: RUL-02, HRN-04 · K-: K9, K12, K18  
In: S2 turn_outcome and turn_completed on terminal edges; S15 refuse run-owned codex-native when policy hooks are disabled; S62 explicit yolo stance for run sessions with policy-resolved approvals; native S12 text and S11 pre-approval enabled; adapter exit_code observations; Codex branch of S24; spikes 12 and 13; honest labels.  
Out: Headless codex (HRN-06); hosted use before OQ-29; Codex orchestrator.  
Paths: `omnigent/harnesses/codex_native/forwarder.py`, `omnigent/harnesses/codex_native/app_server.py`, `omnigent/server/routes/_sessions/helpers.py`, `coral/harness/codex_native.py`  
OQ: OQ-29  
Proof: A codex-native reviewer step submits a handoff and its terminal edge carries turn_outcome; disabling hooks refuses the run.

**HRN-06 Headless codex mode** — HARNESS · PH5 · M4 · Low · L · slice  
Enable headless Codex steps with thread routing, compaction, hook-based gating and an honest read-only stance; first cut if M4 slips.  
G: G-56 · S: S18, S19, S20, S60, S61, S67 · Hard: HRN-01, RUL-01 · Soft: HRN-05 · K-: K9, K12  
In: threadId routing and collab items (S18); compaction (S19); hooks.json PreToolUse gating (S20); hook-trust failure fails closed for run sessions (S67); per-session native-tool switches from the spec (S60); read-only stance without silent upgrade (S61); gating probe.  
Out: codex-native (HRN-05); hosted use before OQ-29.  
Paths: `omnigent/inner/codex_executor.py`, `omnigent/inner/codex_harness.py`, `omnigent/runtime/workflow.py`  
OQ: OQ-29  
Proof: A headless codex read-only step cannot write, and a tool denied by policy is blocked through hooks.json.

**RUL-05 Run and step budgets** — INTEGRATION · PH5 · M4 · High · M · slice  
Pause a run at its budget and ask to raise or stop, using a spend aggregator over all run sessions, with step budgets and estimates from history.  
G: G-62 · Hard: RUL-01, GTE-01, SES-04 · Soft: ENG-07 · K-: K14, K4, K9  
In: Spend aggregator over all run sessions (policy_cost_usd ?? total_cost_usd); paused(budget) with a raise-or-stop elicitation; run-guard DENY reason; overshoot disclosure; tokens and utilization for plan users (D21); estimate from Simulate sessions x past medians; budget in the start dialog; step budgets.  
Out: cost_budget as the primary mechanism (R-5); provider-side hard caps.  
Paths: `coral/budgets/`, `omnigent/runtime/policies/builder.py`  
OQ: OQ-15, OQ-16  
Proof: A run crossing its budget pauses with a budget elicitation; raising it resumes and stopping cancels.

**ENG-10 Versions, diff and restart-from-node** — ENGINE · PH5 · M4 · Medium · M · slice  
Show version history and diffs, and amend a run by cancelling and restarting it from a chosen node with carried handoffs (TLD-18).  
G: G-65, G-14 · Hard: ENG-06, DUR-03, DUR-02 · K-: K1, K2, K5  
In: Versions list and structural diff API; runs per version; restart-from-node creating a linked run on a chosen version with carried handoffs and a reason; mapping validation; lineage migration through the train; restart dialog in the run view.  
Out: 'Apply to this run' (deferred); counter carry-over.  
Paths: `coral/engine/restart.py`, `coral/api/versions.py`, `web/src/workflows/runs/restart/`  
OQ: OQ-20, OQ-4  
Proof: Restarting a cancelled run from Review on v2 carries the implementer's handoff and links the old and new runs.

**DUR-06 Retention, purge and account lifecycle** — PLATFORM · PH5 · M4 · Medium · M · slice  
Purge run data by policy and carry or purge Coral rows when accounts are revoked or migrated.  
G: G-16 · S: S56 · Hard: DUR-05 · Soft: DUR-02 · K-: K5  
In: Retention policy; batched purge_run with blob GC from the ledger; engine agent-row GC; deleting workflows that have runs; S56 account-lifecycle callbacks for revocation and identity migration.  
Out: Legal hold; run-log export (post-M4).  
Paths: `coral/retention/`, `omnigent/server/accounts_store.py`  
OQ: OQ-25  
Proof: A purged run leaves no Coral rows or blobs, and identity migration carries Coral rows to the new account.

**OPS-04 Production hardening: DB lanes, load and security** — OPS · PH5 · M4 · Critical · L · slice  
Certify Coral for production with all DB lanes, a load scenario and a closed security review (TLD-08).  
G: G-87, G-11 · Hard: OPS-02, DUR-05, SES-06, GTE-01 · Soft: WSP-02, HRN-05, GTE-03  
In: Four DB lanes green with fault suites; release statement: SQLite and Postgres committed, CockroachDB and MySQL tested; Coral load scenario in dev/loadtest (concurrent runs, SQLite contention); threat review with fixes: tool provenance (S49), native bridge bearer (D25), runner-local impersonation (spike 15), host-op token, bundle secrets, gate authority, webhooks.  
Out: Multi-replica (deferred); multi-region.  
Paths: `dev/loadtest/`, `tests/stores/coral/`, `docs/coral/SECURITY_REVIEW.md`  
OQ: OQ-1, OQ-42, OQ-43  
Proof: The load report meets the OQ-1 NFRs and the security review closes with no open high findings.

**OPS-05 Release readiness: merge drill, upstreaming and licensing sign-off** — OPS · PH5 · M4 · High · M · slice  
Complete a real upstream merge by the playbook, upstream the generic registries, and close licensing for release.  
G: G-84, G-86 · Hard: OPS-02 · Soft: OPS-04  
In: A real upstream merge executed by the playbook with re-anchoring; security cherry-pick lane with an SLA; upstream PRs for the generic registries S1, S5, S6, S10, S32, S50 and S52; counsel answers: attribution, Apache §4(b), React Flow attribution, OFL, dagre; DCO decision; release pipeline.  
Out: Store listings; relicensing.  
Paths: `docs/coral/UPSTREAM_MERGES.md`, `.github/workflows/coral-release.yml`, `NOTICE`, `MODIFICATIONS.md`  
OQ: OQ-30, OQ-31, OQ-50  
Proof: One upstream merge lands through the playbook with all Coral lanes green, and the licence inventory is signed off.

**BRD-03 Native shell identity** — BRAND · PH5 · M4 · High · M · slice  
Give the Coral desktop and mobile shells their own names, ids, icons, scheme and update feed, with deep links to runs.  
G: G-82 · S: S38, S87, S88 · Hard: BRD-01 · Soft: OPS-02, OPS-03 · K-: K16  
In: Electron brand.js constants for about 37 literals; productName, appId, coral:// scheme, Coral publish.url updater feed (R-18; required before any desktop build); setup and connect pages; icons including Assets.car; CLI detection accepting coral; iOS and Android display names and icons; run deep links (S38).  
Out: Store listings (OQ-31); mobile push (deferred); mobile editing.  
Paths: `web/electron/package.json`, `web/electron/src/main.js`, `web/electron/src/brand.js`, `web/electron/src/deepLink.js`, `web/ios/`, `web/android/`  
OQ: OQ-31, OQ-23  
Proof: A packaged desktop build reports the Coral appId, checks the Coral update feed, and coral://workflows/runs/<id> opens the run.

### PH6 Post-M4 extensions

**WSP-04 Managed-sandbox runs** — WORKSPACE · PH6 · post-M4 · Low · L · slice  
Run workflows in managed sandboxes that survive sleep and relaunch from checkpoints.  
G: G-61 · S: S28, S70 · Hard: WSP-02, SES-06 · K-: K13, K20  
In: Bind-mode worktrees in managed sandboxes (S28); host-keyed keep-warm lease (S70); checkpoint pushes and relaunch from a checkpoint branch; spike 9.  
Out: Plain-folder shadow repos (deferred); multi-host runs.  
Paths: `omnigent/server/managed_hosts.py`, `omnigent/server/managed_host_keepalive.py`, `coral/workspace/sandbox.py`  
OQ: OQ-5  
Proof: A sandboxed run survives sandbox sleep at a gate and relaunches from its checkpoint branch.

**EXT-01 Improvement suggestions** — ENGINE · PH6 · post-M4 · Low · L · slice  
Propose evidence-backed workflow edits from finished runs, never weakening evidence or gates.  
G: G-88 · Hard: ENG-04, DUR-03 · Soft: ENG-10, WEB-08 · K-: K3, K1  
In: Run-log detectors: first-try evidence failures, loops at limit, cost growth, always-approved gates, reversed decisions, always-pass evidence, test edits in non-test steps; suggestion list with run links and YAML diffs; accepting creates a version.  
Out: Auto-apply; weakening evidence or gates.  
Paths: `coral/suggestions/`, `web/src/workflows/suggestions/`  
OQ: OQ-26  
Proof: A run history with three loops at limit yields a suggestion with a YAML diff, and no suggestion removes a gate or evidence item.

**EXT-02 Elephant-Goldfish showcase** — ENGINE · PH6 · post-M4 · Low · M · slice  
Ship the Elephant-Goldfish template with a persistent elephant step across passes and scoped goldfish inputs.  
G: G-89 · Hard: ENG-08, WSP-02, SES-07 · Soft: TLS-04 · K-: K1, K13, K20  
In: Slot rebinding for session: persistent_across_loop (keys reserved in K1); per-member input scoping with a coral.policies DENY on session-read tools plus a files.materialize host op (S65 not used; TLD-04); typed resolutions; ESCALATE -> gate; persona attribution.  
Out: Elephant as the orchestrator (D4.2); AgentSpec changes (TLD-04).  
Paths: `coral/templates/elephant_goldfish.yaml`, `coral/policies/input_scope.py`, `coral/host_ops/materialize.py`  
OQ: OQ-30  
Proof: A goldfish step cannot read sibling sessions, and the elephant keeps one session across three loop passes.

**EXT-03 Repo export and git import** — WORKSPACE · PH6 · post-M4 · Low · M · slice  
Export workflows to .coral/ in a repo, and import workflows, templates and profiles from git.  
G: G-68, G-90 · S: S74 · Hard: WSP-01, DUR-02 · Soft: PRF-02, WSP-02 · K-: K13, K12  
In: S74 .coral/**-confined write op with an expected-hash precondition; Git-URL import of workflows, templates and profiles with a V10 profile check.  
Out: Repo-canonical editing; sync daemon; marketplace.  
Paths: `omnigent/host/connect.py`, `omnigent/server/routes/_host_filesystem.py`, `coral/sharing/`  
OQ: OQ-33  
Proof: Exporting a version writes .coral/<id>.yaml only when the expected hash matches, and importing it on another machine yields the same content hash.

**EXT-04 Run sharing, teams and protection guards** — INTEGRATION · PH6 · post-M4 · Low · L · slice  
Let teams share runs and answer gates, and protect run sessions and engine agents from mutation (TLD-12).  
G: G-90, G-24, G-52 · S: S26, S46, S53 · Hard: SES-06, GTE-01 · Soft: GTE-03 · K-: K10, K14  
In: Engine-managed grants for run sharing (D18); team approvers; S26 protected coral. policy names and label prefix; S46 reserved labels on non-route write paths with an explicit /clear policy; S53 mutation guards on PUT agent, MCP edits, PATCH, reinstall and non-forced delete.  
Out: Per-session sharing reuse; cross-org sharing.  
Paths: `omnigent/server/routes/session_policies.py`, `omnigent/runtime/policies/engine.py`, `omnigent/server/routes/sessions/routes_agent.py`, `omnigent/server/routes/builtin_agents.py`, `coral/sharing/`  
OQ: OQ-4, OQ-17, OQ-46  
Proof: A teammate with the run grant answers a gate, and a non-engine PATCH to a coral__ agent is refused.

**EXT-05 Automations 'Run workflow' trigger** — PLATFORM · PH6 · post-M4 · Low · M · slice  
Start workflow runs from an Automations action, with no second scheduler.  
G: G-90 · Hard: API-02 · K-: K7  
In: 'Run workflow' Automations action; start_key per fire for idempotent starts.  
Out: Coral-owned schedules; workflows as tools or APIs (deferred).  
Paths: `omnigent/scheduled/`, `web/src/pages/TasksPage.tsx`, `coral/api/runs.py`  
OQ: OQ-21  
Proof: An automation firing twice with the same fire id starts one run.

**GTE-04 Web and desktop push notifications** — WEB · PH6 · post-M4 · Low · L · slice  
Deliver gate and pause notifications through Web Push when the app is closed.  
G: G-37 · Hard: GTE-03 · Soft: BRD-03 · K-: K19  
In: VAPID keys, subscriptions and a service worker; payloads without secrets; desktop shell delivery.  
Out: APNs and FCM mobile push (deferred); email digests.  
Paths: `web/src/workflows/push/`, `web/public/`, `coral/notify/push.py`  
OQ: OQ-6, OQ-23  
Proof: A gate opened while the browser tab is closed shows a push notification that deep-links to the gate.

## 3. Milestone exit criteria and proving journeys

### M1 Foundational Coral (PH0 + PH1)

**Features (23).** SPK-01, SPK-02, SPK-03, SPK-04, FND-01, OPS-01, ENG-01, SES-01, API-01, FND-02, FND-03, FND-04, OPS-02, DUR-01, DUR-02, ENG-02, ENG-03, ENG-04, ENG-05, ENG-07, EVD-01, BRD-01, BRD-02.

**Product journeys exercised.** b, c (YAML via API), d.

**Proving journey.**

1. A developer starts Coral with server_plugins: [coral.server_plugin] and sees the Coral skin and the Workflows and Agent Profiles desks with empty states behind GET /v1/coral/info. Turning Coral off hides them and returns not found.
2. Through the API or CLI only, they upload the MVP template (coral workflow upload) and get v1 with a content hash. A broken copy returns box-anchored problems with yaml_path ranges.
3. They freeze a version and simulate 'approved', 'changes requested x3 -> at-limit gate' and 'gate reject'. The traces are deterministic, show a session-count estimate, and re-run green as saved cases on v2.

**Exit criteria.**

1. coral ships in the wheel; the import-boundary test and the coral CI group are green (FND-01).
2. Coral migrations run strictly after Omnigent head on SQLite and Postgres, with CockroachDB and MySQL lanes green; truncation keeps both version tables; coral_0001 carries scope keys and session_generation (FND-03, DUR-01).
3. The plugin mounts /v1/coral and an import failure stops startup; the web gate reads /v1/coral/info and the upstream Feature enum is untouched (FND-02, BRD-02).
4. coral-fork-guard is a required check, every upstream path is ledgered and anchored, the daily nightly^1 rehearsal reports, and NOTICE and MODIFICATIONS.md are generated (OPS-01, OPS-02).
5. Brand skin and navigation shell are live and the CSS contract tests are rebaselined (BRD-01, BRD-02).
6. V1-V7 and V10-V13 pass; I1-I8 hold under seeded fuzz in PR CI; Simulate works through the API with saved cases (ENG-02..05, ENG-07, DUR-02, FND-04).
7. PH0 contracts (K1-K4, K6-K8, K10, K12-K14, K16) are at v1 and the PH1 contracts (K5, K9, K11, K17, K18) are published with contract tests; ADR-05 and the decision records are signed (SPK-01..04).

### M2 Functional stateful workflow (PH2, MVP)

**Features (28).** OPS-03, DUR-03, DUR-04, ENG-06, HRN-01, RUL-01, SES-02, TLS-01, WEB-01, WEB-02, DUR-05, SES-03, SES-04, SES-06, SES-05, TLS-02, TLS-03, GTE-01, GTE-02, EVD-02, EVD-03, PRF-01, HRN-02, WSP-01, API-02, WEB-03, WEB-04, WEB-05.

**Product journeys exercised.** a, b, c (YAML), d, e, f, g (in-app), h (steer), i (core), l (history).

**Proving journey.**

1. On a local git repo with an Anthropic API key, the user picks 'Implement with review loop', confirms the detected test, lint and format commands, simulates, and starts the run; preflight passes and the estimate shows.
2. The implementer edits in coral/r-<run>/base. Its first coral_submit_handoff is rejected because the tests predate its last edit, and is accepted after a re-run.
3. Two read-only reviewers on different models submit findings; a reviewer write is denied by the sandbox.
4. The orchestrator calls coral_choose_arrow('changes requested') with a reason and the loop counter shows pass 2 of 3.
5. The server is SIGTERMed mid-step and restarted. The run resumes with no duplicate sessions and the gate is re-published.
6. The reviewers approve, the human gate appears in the Inbox with the 'app must be open' notice, the user approves it there, and the run ends with the branch kept.
7. On a second run the user pauses, resumes, cancels and retries a step (worktree reset), and a killed runner pauses the run as paused(infra) until Resume.

**Exit criteria.**

1. The journey passes as Tier B E2E-1 and E2E-2 in CI and the credentialed claude-sdk nightly passes five runs in a row (SES-05).
2. fold(log) == state holds after real commits, and a crash at every commit boundary recovers without duplicates on all lanes (DUR-03, DUR-05).
3. The orchestrator decides only through engine tools; illegal labels are rejected with the allowed values; three rejected calls pause the slot (TLS-02, TLS-03, ENG-06).
4. Loop limit 3 is enforced and at_limit routes to the gate (ENG-05).
5. Pause, resume, cancel and retry work from the run view and the API; cancel runs interrupt -> stop -> omnigent.closed and late submits are rejected; retry resets the worktree (ENG-06, API-02, SES-04, WSP-01).
6. The run view shows a live overlay; reconnecting with Last-Event-ID loses no entries; the polling fallback works (API-02, WEB-04).
7. The gate is answerable from the Inbox, the run view and /approve; duplicate answers advance once, stale answers are refused, no gate auto-resolves, and gates re-publish after restart (GTE-01, GTE-02).
8. Done-when uses claude-sdk exit codes and L1 fingerprints; S71 has landed and the runner-path exit-status test is green (EVD-02, WSP-01).
9. Run-owned claude-sdk sessions refuse subscription OAuth, reviewers are read-only by sandbox, engine rows are hidden from pickers, and every run session has the cost backstop (HRN-02, PRF-01, RUL-01).
10. Drift (a deleted policy, an archived step session) pauses the run within one resync, and typing into a step session never triggers a nudge (SES-06, SES-04).
11. No promise labels are shown yet, and the watchdog p95 is recorded for OQ-14.

### M3 Functional agent profile system (PH3)

**Features (8).** PRF-02, RUL-02, RUL-03, RUL-04, HRN-03, HRN-04, WEB-06, WEB-07.

**Product journeys exercised.** k, a (model access), i (plan limit).

**Proving journey.**

1. In the Agent Profiles desk the user creates a 'Strict reviewer' profile from a custom agent and picks it for Review with capability chips.
2. They add a Required 'protect infra/**' rule and a Guidance rule from the catalog; the guarantees panel shows per-mode labels.
3. They switch Implement to claude-native on a subscription. Labels change honestly (read-only becomes Verified), the run executes under fail-closed hooks, a blackholed policy endpoint blocks the tool call, and /clear is followed.
4. A plan limit pauses the run with its reset time and it resumes on its own. Editing the profile mid-run leaves the run on rev N; the next run uses rev N+1.

**Exit criteria.**

1. Profile revisions are immutable, reinstall creates a new revision, pins hold, and drift is reported at slot start (PRF-02).
2. Capabilities are exposed per spelling; the four labels are computed per mode; V9 rejects Required rules the mode cannot enforce; the property test shows no unknown capability yields Enforced (HRN-01, RUL-02).
3. Catalog rules compile into guardrails with confirmation (RUL-03, WEB-06).
4. E2E-3 and E2E-4 are green and the nightly bench covers claude-sdk and claude-native (RUL-04, HRN-03, HRN-01).
5. Plan-limit pauses show the reset time and auto-resume; accounts are pinned per run (HRN-04, HRN-02).
6. The desk and picker show capability chips and used-by (WEB-07).
7. Native auth and egress paths are cleared against OQ-28 and OQ-35.

### M4 Integrated production-ready Coral (PH4 + PH5)

**Features (19).** WSP-02, EVD-04, WSP-03, ENG-08, ENG-09, TLS-04, SES-07, GTE-03, WEB-08, WEB-09, WEB-10, HRN-05, HRN-06, RUL-05, ENG-10, DUR-06, OPS-04, OPS-05, BRD-03.

**Product journeys exercised.** c (canvas), g (external), h (take-over), i (refresh, budget), j (lite).

**Proving journey.**

1. The user builds the PR-review loop on the canvas and the YAML keeps its comments.
2. The run repeats over labelled PRs ('3 of N', concurrency 2, batched per-item gates) with parallel claude-sdk and codex-native reviewers.
3. A fix uses two writers in their own worktrees with serial merges and mandatory Coral-run checks in a detached checkout; L2 fingerprints come over the host channel.
4. During the run: a budget pause raised from its elicitation, an orchestrator refresh, take-over and hand-back on one step, a webhook for an unattended gate, and a cancel-and-restart from a node with carried handoffs. Afterwards a retention purge removes an old run.

**Exit criteria.**

1. Trust: the host op channel, L2 fingerprints and Coral-run checks with the integrity diff are live; evaluator verdicts are identical across the backend swap; the reaper exit-status test passes (WSP-02, EVD-04).
2. Structure: E2E-5 is green and multi-writer merges always run post-merge checks (ENG-08, ENG-09, WSP-03, TLS-04).
3. Canvas edits and the outline round-trip comments with keyboard and screen-reader parity (WEB-08, WEB-09).
4. Budgets, refresh, take-over, the webhook connector, amendments-lite, codex-native, headless codex and retention purge all work (RUL-05, SES-07, GTE-03, ENG-10, HRN-05, HRN-06, DUR-06, WEB-10).
5. Operations: SQLite and Postgres committed with CockroachDB and MySQL green; load meets the OQ-1 NFRs; the security review is closed; a real upstream merge went through the playbook; generic-seam upstream PRs are open; licensing is signed off; the desktop build updates from the Coral feed (OPS-04, OPS-05, BRD-03).

### post-M4 (PH6)

**Features (7).** WSP-04, EXT-01, EXT-02, EXT-03, EXT-04, EXT-05, GTE-04.

**Product journeys exercised.** l (suggestions), m (sharing via git), g (push).

**Proving journey.**

1. No milestone exit. Each feature is gated by its open questions.

**Exit criteria.**

1. Features: WSP-04, EXT-01..05, GTE-04.
2. Deferred gap parts are listed in section 5.

### Journey coverage

| Product journey | Features | When |
|---|---|---|
| (a) First run, brand and onboarding | BRD-01, BRD-02, OPS-03, HRN-02, HRN-04 | M1 skin; M2 API-key path; M3 model access |
| (b) Create a workflow from a template | ENG-07, DUR-02, WEB-02, WEB-03, EVD-03 | M1 API; M2 UI |
| (c) Author and edit (YAML, canvas) | ENG-02, ENG-03, WEB-02, WEB-08, WEB-09 | M2 YAML; M4 canvas |
| (d) Simulate and save as test case | ENG-07, DUR-02, WEB-01 | M1 API; M2 UI |
| (e) Start a run | WEB-03, API-02, WSP-01, HRN-02 | M2 |
| (f) Monitor a live run | WEB-04, API-02, WEB-10 | M2 basic; M4 depth |
| (g) Answer gates and ask_user | GTE-01, GTE-02, TLS-03, GTE-03, GTE-04 | M2 in-app; M4 webhook; post-M4 push |
| (h) Steer, take over, hand back | WEB-05, SES-04, SES-07, WEB-10 | M2 steer; M4 take-over |
| (i) Pauses and recovery | ENG-06, SES-06, DUR-05, HRN-04, SES-07, RUL-05 | M2 core; M3 plan limit; M4 refresh and budget |
| (j) Amend a running run | ENG-10 | M4 restart-from-node; full amendments deferred |
| (k) Manage agent profiles | PRF-01, PRF-02, WEB-07, RUL-03, WEB-06 | M2 seeded; M3 desk |
| (l) Run history and suggestions | WEB-04, ENG-10, EXT-01 | M2 history; post-M4 suggestions |
| (m) Share via git and templates | EXT-03, EXT-04, EXT-05 | post-M4 |

## 4. Synthesis decisions log

One line per choice, naming the lens followed. 'Move' and 'Kept' lines change or confirm the mandated milestone placements; 'flag' lines record TLD conditions with evidence.

1. Contract catalog: followed the architect (K1-K18 boundaries and producers), added K19 alert/inbox model from product and split host frames out as K20 from the adversarial lens.
2. Spikes: followed the adversarial lens (four time-boxed PH0 spikes: decisions, topology, harness probes, workspace and evidence) and added product's probe (e), a gate on a turnless run session rendering in Inbox, to SPK-02.
3. One-hour unknowns (spikes 10, 11, 17, 18, 19) run as first checks inside FND-01, FND-02, BRD-02, PRF-01 and HRN-02 (adversarial).
4. K13 WorkspaceOps is SPK-04's decision output with session-shell and host backends, so M4 swaps the backend without rewriting evidence or restart code (adversarial and product).
5. Foundations split into package (PH0), plugin seam, DB env and test infra (architect and adversarial) rather than one L package-plus-DB feature (product).
6. GET /v1/coral/info lives in FND-02 (product) so the web Coral gate unblocks in early PH1.
7. Seam packs A (SES-02) and B (TLS-01) start in PH1 and land as a serial seam train per hot file (architect), so PH2 never waits on upstream review.
8. TLS-01 lands every S50 call site, including the native S9, S11 and S12 sites, as one-line calls (architect); enabling native channels stays in HRN-03 and HRN-05.
9. G-04 (XL) split three ways: ENG-04 core with gate visits and log (L, two engineers), ENG-05 loops and joins (M), ENG-06 lifecycle and timers (M); adversarial split, architect's gate-in-engine boundary.
10. ENG-06 lifecycle starts in PH1 as pure reducer work targeting M2 (adversarial), not in PH2 (architect).
11. The MVP template ships as package data with the Simulate engine in ENG-07 (product and adversarial).
12. Workflow store and workflow endpoints merged into DUR-02 so the M1 API journey is one vertical slice (product); repo import stays with repo bindings in WSP-01 (architect).
13. DUR-01 owns K5, both MVP migrations and the migration train with a single-head check (architect for K5, adversarial for the train).
14. Queue (DUR-04) starts in PH1 as the main schedule lever (architect); the reconciler is a separate M feature because fault helpers live in FND-04 (adversarial sizing).
15. Walking skeleton (product) and M2 acceptance lane (adversarial) merged into SES-05: one owner from the first integration target to the M2 exit.
16. Session integration split into facade (SES-03), turn loop (SES-04) and recovery (SES-06) per the architect; SES-04 builds against the K5 queue protocol so it is not hard-blocked on DUR-04.
17. coral_choose_arrow lives with the orchestrator in TLS-03 (product and adversarial), not with submit_handoff (architect); ask_user stays in TLS-03 as the first M2 cut line (adversarial).
18. Gates: visit semantics in the reducer (ENG-04, architect) and the Omnigent elicitation seam pack C in GTE-01 (all three lenses).
19. Evidence: IR in PH1 (all), claude-sdk capture plus handoff evaluation as one L feature (architect and adversarial), detection separate (EVD-03), L2 inside the host channel WSP-02 (architect and adversarial).
20. S71 is WSP-01's first PR with a may-land-in-PH1 note (adversarial); product's flag holds that it guards fs_request git status used by import and detection.
21. S68 and S69 owned whole by EVD-02 (architect); native and Codex observation sites are enabled later by HRN-03 and HRN-05.
22. Credential guard split: core S13/S63 guard at M2 (HRN-02) and model access plus plan limits at M3 (HRN-04) (product).
23. S45 owned by claude-native HRN-03 as the first needer for /clear rotation (adversarial), not by refresh.
24. S21 assigned conditionally to HRN-02 (product and adversarial) rather than unplanned (architect), because a failed spike 1 would block M2 policy enforcement on claude-sdk.
25. S3 assigned to HRN-03 for terminal_launch_args only (architect and product); the rest of S3 is not needed.
26. S65 not planned and EGM uses a coral.policies DENY (architect's TLD-04 flag followed fully).
27. Read-only diagram merged with Simulate UI in WEB-01 so one owner holds the shared overlay API (adversarial).
28. Run view (WEB-04) and agent panes plus steering (WEB-05) kept separate to hold WEB-04 within L (product); runs list sits in WEB-04 (adversarial).
29. Templates, Use-template and start-run dialogs merged into WEB-03 as one dialog family (architect).
30. Refresh and take-over merged into SES-07 slot control (product and adversarial).
31. Reactions and overdue alerts move to PH4 with groups in ENG-09 (adversarial; the mandate puts 'rules depth' in PH4), not M3 (product).
32. Production readiness split into hardening (OPS-04) and release readiness (OPS-05) (adversarial) instead of one L (architect).
33. Native shell identity keeps desktop and mobile names and icons together at M4 (architect) so S88 has one owner; mobile push is a deferred gap part.
34. LLM translation and full amendments are deferred gap parts, not PH6 features (count discipline; TLD-18, TLD-19); workflows-as-tools deferred (product).
35. Every mutual soft-dependency pair was cut to the consumer-to-producer direction so the combined hard+soft graph has no cycles.
36. WS-INTEGRATION owns 18 features: staff it as a seam and facade sub-team (SES-01..06, TLS-01, GTE-01) and a tools and policies sub-team (TLS-02..04, RUL-01, RUL-03, RUL-05, GTE-03, EXT-04) (architect R2).
37. Move: S13/S63 credential guard M3 -> M2 (HRN-02), all three lenses; TLD-07 makes API-key auth the MVP and without S13 run sessions fall through to subscription OAuth (runtime/workflow.py:1123-1400).
38. Move: claude-sdk reviewer write_paths: [] M3 -> M2 (PRF-01), all three lenses; TLD-01 has read-only reviewers at M2 and read_only_os leaves the shell writable (R-23).
39. Move: per-session cost_budget backstop M4 -> M2 (RUL-01), adversarial and product, backed at M1 by the V12 bound (ENG-03) and the runtime activation cap (ENG-05); run and step budgets stay at M4 (RUL-05).
40. Kept: promise-label UI at M3 (architect and adversarial); product's static-row M2 labels rejected so nothing is labelled before the registry is bench-tested (TLD-11).
41. Kept: YAML editor at M2 as WEB-02's last PR series with an explicit cut line (architect and product, with the adversarial cut line).
42. Kept: plan-limit pause at M3 (product); API-key MVP users rarely hit plan windows and G-57 is 'later'.
43. Kept: headless codex at M4 per the mandate (architect and product) at Low priority as the first M4 cut; the adversarial post-M4 move was rejected because HRN-06 carries the S20 gating fix.
44. Kept: step budgets in RUL-05 at M4 (architect and product); adversarial deferral rejected because G-62 and the mandated M4 budgets line include them.
45. Kept: repo export post-M4 in EXT-03 (architect and adversarial; TLD-06), not M4 (product).
46. Kept: versions list and diff with restart-from-node in ENG-10 at M4 (all three).
47. TLD-10 flag: S71 guards only host-owned subprocesses (connect.py:1417-1423, fs handlers at :6027-6034); MVP exit codes come from the runner path, so EVD-02 adds a runner exit-status test, uses one L1 algorithm at command and submit time (bare /changes porcelain misses re-edits of dirty files), and M2 evidence tops out at Verified (L1).
48. TLD-02 flag: option B needs engine-driven relaunch of own-runner children, since upstream relaunches roots only (app.py:4273) and recovery skips host_id children (child_session_recovery.py:164); SPK-02 probe (f) and an SES-06 deliverable.
49. TLD-09 flag: a gate published on a turnless run session and its Inbox rendering are unverified; SPK-02 probe (e) covers it before GTE-01 starts.
50. TLD-17 flag: the L3 coral.omni contract suite exists only once SES-03 lands; the rehearsal runs L0-L2 from day one and adds L3 then.
51. TLD-12 flag: S73 stays unneeded only while run sessions carry workspace= and no git options (session delete otherwise removes the branch, routes_events.py:4166-4189); WSP-01 tests that invariant.
52. TLD-07 flag: subscription-only users cannot run workflows until M3; needs product sign-off in SPK-01, and HRN-02 ships honest preflight copy.
53. TLD-04 flag: seam S65 would be an AgentSpec and parser change, so it is not planned.
54. No TLD was found unsound; the flags above are conditions the plan now carries.

## 5. Deferred gap parts and unplanned seams

Every G-row has an owner in section 2. These sub-parts are not scheduled in M1-M4 or PH6:

| Deferred part | Reason |
|---|---|
| G-10 (Sub-workflow invocation) | No M1-M4 journey or template needs it; the kind stays reserved and hidden in K1. |
| G-11 (multi-replica) | v1 is single replica (TLD-08); FND-02 and DUR-04 refuse to start workers under multi-replica or host sharding. |
| G-37 (APNs and FCM mobile push) | Needs app ids and store decisions (OQ-31) and mobile scope (OQ-23); Web Push (GTE-04) comes first post-M4. |
| G-38 and G-61 (plain-folder workspaces and fingerprints) | Git worktrees only until a non-code persona is confirmed (OQ-1); needs content-hash manifests first. |
| G-42 and G-48 (free-text LLM translation of done-when and rules) | TLD-19: v1 is the detected-command picker (EVD-03, WEB-03) and the typed catalog (RUL-03); an engine-owned translator session is unscheduled post-M4. |
| G-65 (full 'Apply to this run' amendments) | TLD-18: ENG-10 ships cancel-and-restart-from-node; full amendments are unscheduled post-M4 (OQ-20). |
| G-66 (exhaustive Simulate, V11) | Replaced by block-structure validation plus scripted Simulate (X-25, R-24); revisit as a sampling check. |
| G-87 (claude-sdk fake) | None exists; the credentialed nightly (SES-05, HRN-01) and a mock base-URL lane if spike 4 passes stand in. |
| G-90 (workflows as tools or APIs, marketplace) | Mentioned only in D§15 with no product spec; EXT-05 covers the Automations trigger. |

Seams not planned (every other seam has exactly one owner):

| Seam | Reason |
|---|---|
| S17 | claude-sdk sub-agent attribution is moot: run sessions expose no vendor sub-agents (S63 contract test in HRN-02). Revisit only if that changes. |
| S33 | Upstream Feature enum flag replaced by the Coral-owned GET /v1/coral/info gate (TLD-03, R-21). |
| S35 | Watch-set union is needed only under the top-level topology fallback; costed as the SES-03 contingency (TLD-02). |
| S44 | Optional shared turn-outcome classifier; the per-mode rule in SES-04 does not need it. Reconsider if codex-native rules diverge. |
| S47 | Child-capable continue-in-fork: refresh is a slot restart (TLD-13, R-8). |
| S48 | hold_started callback: polling runner_last_seen in SES-06 suffices. |
| S55 | Caller-supplied id through HTTP create: the facade creates sessions through the store with derived ids (X-6). |
| S65 | tool_groups.session_reads is an AgentSpec and parser change, which TLD-04 rules out; EXT-02 scopes inputs with a coral.policies DENY instead. |
| S73 | Run sessions carry workspace= and no git options, so session-delete worktree cleanup never fires; WSP-01 keeps this as a tested invariant (TLD-12). |

Conditional owners: S21 (HRN-02) only if spike 1 shows can_use_tool is skipped; S51 (SES-03) only if SPK-02 confirms children; S66 (PRF-02) optional; S3 (HRN-03) for terminal_launch_args only.

**Seam owner index.** S1 SES-02; S1b SES-02; S2 HRN-05; S3 HRN-03; S4 SES-02; S5 GTE-01; S6 GTE-01; S6a GTE-01; S6b GTE-01; S7 TLS-01; S8 TLS-01; S9 TLS-01; S10 TLS-01; S11 TLS-01; S12 TLS-01; S13 HRN-02; S14 RUL-04; S15 HRN-05; S16 RUL-04; S17 not planned; S18 HRN-06; S19 HRN-06; S20 HRN-06; S21 HRN-02; S22 HRN-01; S23 HRN-01; S24 HRN-04; S25 SES-07; S26 EXT-04; S27 SES-07; S28 WSP-04; S29 FND-01; S30 FND-03; S31 FND-03; S32 FND-02; S33 not planned; S34 BRD-02; S35 not planned; S36 GTE-02; S37 GTE-02; S38 BRD-03; S39 FND-01; S39b FND-01; S39c FND-01; S39d FND-01; S39e FND-01; S40 WSP-02; S40b WSP-02; S41 SES-02; S42 SES-02; S43 SES-02; S44 not planned; S45 HRN-03; S46 EXT-04; S47 not planned; S48 not planned; S49 TLS-01; S50 TLS-01; S51 SES-03; S52 RUL-01; S53 EXT-04; S54 PRF-01; S55 not planned; S56 DUR-06; S57 FND-03; S58 FND-03; S59 HRN-01; S60 HRN-06; S61 HRN-06; S62 HRN-05; S63 HRN-02; S64 HRN-03; S65 not planned; S66 PRF-02; S67 HRN-06; S68 EVD-02; S69 EVD-02; S70 WSP-04; S71 WSP-01; S72 WSP-01; S73 not planned; S74 EXT-03; S75 OPS-03; S76 FND-01; S77 OPS-02; S78 HRN-01; S79 BRD-01; S80 BRD-02; S81 BRD-01; S82 BRD-01; S83 BRD-01; S84 BRD-02; S85 GTE-02; S86 WEB-05; S87 BRD-03; S88 BRD-03; S89 BRD-01.

**G-row owner index.** G-01 ENG-01, ENG-02; G-02 ENG-03; G-03 ENG-01, ENG-03, ENG-04, ENG-05; G-04 ENG-04, ENG-05; G-05 ENG-01, ENG-04; G-06 ENG-06, ENG-09; G-07 DUR-03, ENG-06, SES-04, API-02; G-08 ENG-08, WEB-10; G-09 ENG-08; G-10 ENG-09; G-11 DUR-04, DUR-05, OPS-04; G-12 FND-01; G-13 FND-03; G-14 DUR-01, DUR-02, DUR-03, PRF-02, ENG-10; G-15 DUR-02; G-16 DUR-05, DUR-06; G-17 FND-02; G-18 SES-01, SES-03; G-19 SES-02, SES-04; G-20 SES-02, SES-04, HRN-05; G-21 SES-04; G-22 SPK-02, SES-03; G-23 SES-06; G-24 SES-06, HRN-03, EXT-04; G-25 SES-01, DUR-04, SES-03; G-26 TLS-01; G-27 TLS-01; G-28 TLS-02; G-29 TLS-03; G-30 TLS-03; G-31 TLS-04; G-32 TLS-03; G-33 TLS-03; G-34 ENG-04, ENG-06, GTE-01, API-02; G-35 GTE-01; G-36 GTE-02; G-37 GTE-03, GTE-04; G-38 SPK-04, EVD-02, WSP-02; G-39 EVD-02, HRN-03; G-40 EVD-01, EVD-02; G-41 EVD-03; G-42 EVD-03, WEB-03; G-43 EVD-04; G-44 SPK-03, HRN-01; G-45 RUL-01; G-46 RUL-01; G-47 PRF-01, RUL-02; G-48 RUL-03, WEB-06, ENG-09; G-49 RUL-04; G-50 PRF-01, PRF-02; G-51 SES-01, PRF-01; G-52 PRF-01, EXT-04; G-53 WEB-07; G-54 HRN-02, HRN-04; G-55 HRN-03; G-56 HRN-05, HRN-06; G-57 HRN-04; G-58 WSP-01, EVD-04; G-59 SPK-04, WSP-01, WSP-02; G-60 WSP-03; G-61 WSP-04; G-62 ENG-07, RUL-01, RUL-05; G-63 SES-07; G-64 SES-07; G-65 ENG-10; G-66 DUR-02, ENG-07; G-67 WEB-01, WEB-10; G-68 DUR-02, WEB-02, WSP-01, EXT-03; G-69 ENG-07, WEB-03; G-70 WEB-02; G-71 WEB-01; G-72 WEB-08, WEB-09; G-73 WEB-02, RUL-02, WEB-06; G-74 API-01, DUR-02, API-02; G-75 API-01, API-02, WEB-04; G-76 API-02, WEB-03; G-77 WEB-04, WEB-05, WEB-10; G-78 BRD-01; G-79 BRD-01; G-80 BRD-02; G-81 FND-02, BRD-02, WEB-02; G-82 BRD-03; G-83 OPS-01; G-84 OPS-02, OPS-05; G-85 OPS-03; G-86 OPS-02, OPS-05; G-87 FND-04, DUR-05, SES-05, OPS-04; G-88 EXT-01; G-89 EXT-02; G-90 EXT-03, EXT-04, EXT-05.

## 6. Critical path and hot-file seam train

Single-owner weeks over hard dependencies (S=1, M=2, L=4.5), from PH0 start. Real calendar time depends on staffing; the chains show where a slip moves a milestone.

- **M1:** 13.5 weeks via FND-01 > ENG-01 > ENG-02 > ENG-04 > ENG-05 > ENG-07.
- **M2:** 18.5 weeks via FND-01 > SES-01 > SES-03 > SES-04 > SES-06 > SES-05.
- **M3:** 18 weeks via FND-01 > FND-03 > DUR-01 > WSP-01 > EVD-02 > RUL-02 > WEB-06.
- **M4:** 23 weeks via FND-01 > FND-03 > DUR-01 > WSP-01 > WSP-02 > EVD-04 > WSP-03.

Chains converging on the M2 exit (SES-05), longest first:

- 18.5 weeks: FND-01 > SES-01 > SES-03 > SES-04 > SES-06 > SES-05
- 18 weeks: FND-01 > ENG-01 > ENG-02 > ENG-04 > TLS-02 > TLS-03 > SES-05
- 16 weeks: FND-01 > FND-03 > DUR-01 > WSP-01 > EVD-02 > SES-05
- 16 weeks: FND-01 > FND-03 > DUR-01 > DUR-02 > API-02 > SES-05
- 14 weeks: FND-01 > SES-01 > SES-03 > SES-04 > SES-05
- 13.5 weeks: FND-01 > FND-03 > DUR-01 > DUR-04 > DUR-05 > SES-05

Schedule levers: run SPK-02 in week 1 (a failed spike adds 3-4 weeks to SES-03 and makes the session chain clearly critical); land SES-02 and TLS-01 in PH1; publish K5 and the queue tables as DUR-01's first PR so DUR-04 starts early; staff ENG-04 with two engineers; land S71 in PH1; build SES-04, TLS-02 and GTE-01 against FakeOmni and the K5 queue protocol. Contingencies: topology fallback (+3-4 weeks on SES-03 and WEB-05, adds S35); a failed SPK-04 pulls minimal host ops into PH2 (+3 weeks on WSP-01).

| Hot file | Landing order (feature: seams) |
|---|---|
| `omnigent/server/app.py` | FND-02: S32, then SES-02: S41 |
| `omnigent/server/routes/_sessions/helpers.py` | SES-02: S1, S43, then TLS-01: S49, then HRN-03: S3, S45, then HRN-05: S62 |
| `omnigent/server/routes/_sessions/orchestration.py` | SES-02: S1 bypasses, S43, then TLS-01: S10, then GTE-01: S6b, then EVD-02: S69 |
| `omnigent/server/routes/sessions/routes_events.py` | SES-02: S42, then GTE-01: S6a, then HRN-03: S45 |
| `omnigent/runner/tool_dispatch.py` | TLS-01: S8, S9, then EVD-02: S68 |
| `omnigent/runner/native/orchestration.py, claude_native hook and bridge` | TLS-01: S11, S12 sites, then EVD-02: S68 (bridge), then RUL-04: S14, S16, then HRN-03: S64 |
| `omnigent/runtime/policies/builder.py` | RUL-01: S52 only |
| `omnigent/host/connect.py` | WSP-01: S71, then WSP-02: S40, then EXT-03: S74 |
| `web/src/App.tsx and web/src/shell/Sidebar.tsx` | BRD-02 only (S34, S80) |
