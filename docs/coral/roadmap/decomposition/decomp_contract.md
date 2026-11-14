# Coral roadmap: contract-first feature decomposition (Staff Architect lens)

Repository `omnigent-ai/omnigent` at `2a9cbe2c2` (Omnigent 0.22.0.dev0). Date 2026-11-11. Builds on `investigation/gap_analysis.md` (G-, S-, X-, D-, OQ- ids) and the specialist files. Sources: D§ (Draft 4), DD§ (deep dive), UI§ (UI design language).

## 1. Approach and key choices

**Shape.** 85 features across 17 areas and 8 workstreams. Every G-row (G-01..G-90) is covered by at least one feature; six sub-parts are deferred with reasons (§4). Every seam is assigned to exactly one feature or listed as not planned (§4). No feature is XL. A machine check over the feature data confirms coverage, unique seam ownership, and that no hard dependency points to a later phase or milestone.

**Contract-first.** PH0 is a contract sprint. Eighteen contracts (K1-K18, §2) are standalone deliverables owned by the producing workstream. Consumers build against stubs:
- K1 golden fixtures;
- the K4 in-memory facade fake;
- K7 OpenAPI-generated TS types and stub routers;
- K13 behind two adapters (MVP runner, later host channel).

Ten contracts ship in PH0 (K1-K4, K6-K8, K10, K14, K16). The other eight ship as the first PR of a PH1 feature: K5, K9, K11, K12, K13 (frames at draft), K15 (draft), K17 and K18. Change rule: a contract is versioned in `coral/contracts/` (or the OpenAPI file). It changes only with the producer's approval and sign-off from each consumer lead. Each contract carries a contract test: JSON Schema golden, OpenAPI drift, facade signature snapshot, ledger schema test.

**Boundaries.**
- Pure engine work (ENG-*, EVD-01, RUL-02) imports nothing from `omnigent`.
- Only `coral.omni`, `coral.policies` and `coral.db` may import Omnigent internals. FND-01 enforces this with a lint rule and a test.
- Integration lives in SES/TLS/GTE features owned by WS-INTEGRATION.

**Persistence.** Each migration is a standalone PR inside a named feature: `coral_0001_core` (DUR-01), `coral_0002`/`coral_0003` (DUR-06), `coral_0004` profiles (PRF-03), lineage (ENG-10). Scope keys are in every table and key from 0001 (TLD-21).

**Hot upstream files.** Upstream seams are concentrated in four seam-carrying features: FND-02, SES-02 (pack A), TLS-01 (pack B) and GTE-01 (pack C). Each hot-file change is a one-line call into a registry module. They land as a serial "seam train", so no two features touch the same hot file at once:

| Hot file | Landing order (feature: seams) |
|---|---|
| `server/app.py` | FND-02: S32, then SES-02: S41 |
| `server/routes/sessions/helpers.py` | SES-02: S1, S43, then TLS-01: S49, then HRN-03: S3, then SES-06: S45, then HRN-04: S62 |
| `server/routes/sessions/orchestration.py` | SES-02: S1 bypass, S43, then TLS-01: S10, then GTE-01: S6b, then EVD-02: S69 |
| `routes_events.py` | SES-02: S42, then GTE-01: S6a |
| `runner/tool_dispatch.py` | TLS-01: S8, S9, then EVD-02: S68 |
| native `orchestration.py`, `bridge.py`, hooks | TLS-01: S11, S50 sites, then RUL-04: S14, S16, then HRN-03: S64 |
| `host/connect.py` | WSP-01: S71, then WSP-03: S40 |
| `web/src/shell/Sidebar.tsx` | BRD-02 only (S34, S80) |

**Phase vs milestone.** Phase is the start window; milestone is when the feature must be done. Several PH1 features target M2 so the long durability chain starts early: DUR-03, DUR-04, SES-02, TLS-01, RUL-01, HRN-01, WEB-01 and WEB-02.

**Placement moves from the mandated defaults (with reasons).**
- S13/S63 credential guard: M3 → M2 (HRN-02). TLD-07 makes the MVP API-key or provider only, under the S13 guard. Without it, run sessions fall through to subscription OAuth (`workflow.py:1123-1400`).
- claude-sdk read-only reviewer rule (`write_paths: []`): M3 → M2 (PRF-02). TLD-01 puts two read-only reviewers in the MVP. Per-mode labels stay in M3 (RUL-02).
- S24 claude-sdk plan-limit signal: later → M2 (HRN-02). Product's MVP pause list needs a resume time; the error-text fallback is fragile (G-57).
- Promise-label panel: M3 (WEB-07), following the mandate, although G-73 is marked MVP. M2 shows validator problems only.
- Run budget stays at M4 (RUL-05), following the mandate. M2 relies on structural bounds: loop limit 3 and attempts 3 per TLD-01, plus the Simulate session-count estimate. See risk R1.

**TLD review (flags with evidence; no TLD is re-litigated).**
- TLD-10 is necessary but not sufficient. S71 guards only the host `fs_request`/`fs_write` handlers (`connect.py:6027-6034`). MVP exit codes come from the claude-sdk runner path (`tool_dispatch.py:7297-7307`) and the session shell. EVD-02 therefore adds an exit-status-preservation test on the runner path.
- TLD-17: the L3 `coral.omni` contract suite cannot run "on all DB lanes from day one" because it exists only once SES-03 lands (PH2). OPS-02 runs L0-L2 from day one, and SES-03 adds L3 to the rehearsal.
- TLD-04 vs S65: the Elephant-Goldfish input scoping seam S65 (`spec/types.py`, `parser.py`) would be an AgentSpec change. EXT-02 prefers the DENY-policy alternative to keep TLD-04 intact.
- TLD-02: under option B, the engine must relaunch own-runner children itself. Upstream relaunches roots only (`app.py:4273`) and skips own-host children on recovery (`child_session_recovery.py:165`). This is an explicit SPK-01 probe and an SES-05 deliverable.
- TLD-12: S73 is unneeded only because WSP-02 binds sessions with `workspace=` and no git options. That binding rule is load-bearing; session delete otherwise removes the branch (`routes_events.py:4166-4189`).

**Risks the lens surfaces.**
- R1: no spend cap until M4. Mitigation: structural bounds, the estimate shown at start, and the option to pull RUL-05's aggregator into PH3 if dogfooding shows overruns.
- R2: WS-INTEGRATION owns 18 features and every hot seam. Staff it as two sub-teams: a seam/facade team (SES-01..05, TLS-01, GTE-01) and a tools/policies team (TLS-02..04, RUL-01, RUL-03, RUL-05, GTE-03).
- R3: the topology fallback adds 2-3 weeks to SES-03 (S35, engine-managed grants, family grouping).

## 2. Contract catalog

| K | Contract | Producer | Consumers | What it fixes |
|---|---|---|---|---|
| K1 | Workflow authoring schema and compiled IR | ENG-01 (PH0) | API-01, DUR-02, ENG-02, ENG-03, ENG-04, ENG-06, API-02, EVD-01, WEB-01, WEB-02, RUL-02, ENG-08, ENG-09, WEB-08, WEB-09, ENG-10, EXT-01, EXT-02 | YAML keys and node kinds, reserved keys and ids, frozen CompiledGraph, content hash, JSON Schema for TS, stable-id rule, separate layout doc. |
| K2 | Reducer contract | ENG-01 (PH0) | SES-01, FND-04, DUR-01, DUR-03, ENG-04, ENG-05, ENG-06, DUR-05, ENG-07, SES-04, SES-05, TLS-02, ENG-08, ENG-09, SES-07, ENG-10 | transition(graph, state, input, now) -> {state delta, log, effects, rejections}; commands and observations with idempotency keys; effects with effect_key; ScopeKey; pause reasons; error taxonomy. |
| K3 | Run-log entry schema and fold | ENG-01 (PH0) | FND-04, DUR-01, DUR-03, ENG-04, ENG-06, ENG-07, API-03, WEB-03, WEB-05, ENG-08, WEB-10, EXT-01 | Closed kind enum, seq, actor, scope key, 16 KiB body cap, refs; fold(log) == state. |
| K4 | coral.omni facade protocol and fake | SES-01 (PH0) | DUR-05, SES-03, SES-04, SES-05, GTE-01, EVD-03, WSP-02, API-03, TLS-04, SES-06, SES-07, RUL-05 | Sessions, policies, gates, profiles, workspaces and capabilities protocols (create, send with stable_id, interrupt, stop, wake, reads, gate publish, bundles, worktrees, host read) plus an in-memory fake. |
| K5 | Coral persistence contract | DUR-01 (PH1) | DUR-02, DUR-03, DUR-04, API-02, DUR-05, DUR-06, TLS-02, PRF-03, GTE-03, ENG-10, DUR-07 | Table conventions incl. scope keys; store protocols (apply_transition CAS, workflow store, queue claim/lease/finish); at-least-once work semantics. |
| K6 | Engine tool contracts | SES-01 (PH0) | PRF-01, TLS-01, TLS-02, TLS-03, EVD-02, TLS-04, SES-06 | The six TLD-20 tools: argument schemas, result envelope, rejection codes, (run, operation_id) dedup, handler signature, params.coral opt-in keys. |
| K7 | Coral REST API and OpenAPI | API-01 (PH0) | API-02, BRD-02, WEB-01, WEB-02, GTE-02, API-03, WEB-03, WEB-04, WEB-05, WEB-06, WEB-07, GTE-03, WEB-08, WEB-10, EXT-05 | /v1/coral/* endpoints, error envelope, access mapping, OpenAPI artifact with drift check, generated TS types. |
| K8 | Run stream protocol | API-01 (PH0) | API-03, WEB-05, WEB-10 | SSE snapshot, then entry events with seq ids; Last-Event-ID resume; heartbeat; [DONE]; polling fallback. |
| K9 | Capability registry | HRN-01 (PH1) | HRN-02, RUL-02, RUL-03, RUL-04, HRN-03, WEB-06, WEB-07, SES-06, WEB-09, HRN-04, HRN-05, RUL-05 | Capability fields and enums (S22) per spelling (S59); CapabilityMatrix; inputs to promise labels and V9. |
| K10 | Identity, labels and derived keys | SES-01 (PH0) | PRF-01, RUL-01, SES-03, GTE-01, PRF-02, WSP-02, EXT-04 | coral.* label keys, uuid5(effect_key) session ids, stable_id per message, policy ids, worktree paths, coral_gate_<visit> ids, coral__ and coral. prefixes. |
| K11 | Evidence-requirement IR and observations | EVD-01 (PH1) | WSP-01, DUR-06, EVD-02, EVD-03, WEB-04, HRN-03, WSP-03, EVD-04, WSP-04, SES-07 | Required commands, may-modify flags, exit-code sources, scope, final-pass semantics, observation and fingerprint records, messages. |
| K12 | Step bundle format and params.coral schema | PRF-01 (PH1) | RUL-01, TLS-01, DUR-06, TLS-03, PRF-02, HRN-02, RUL-03, PRF-03, HRN-03, WEB-06, HRN-04, HRN-05, EXT-03 | Tar layout, content addressing, params.coral keys, hygiene defaults, approval stance, guardrails, provider-reference auth. |
| K13 | Workspace-ops interface and host frames | WSP-01 (PH1) | SES-05, EVD-02, WSP-02, WSP-03, EVD-04, WSP-04, WSP-05, EXT-02, EXT-03 | WorkspaceOps protocol (fingerprint, check, commit, reset, salvage, merge, read); S40 frame, job and token schema (draft until WSP-03). |
| K14 | Gate elicitation payload | SES-01 (PH0) | API-01, ENG-05, TLS-03, GTE-01, GTE-02, GTE-03, RUL-05, EXT-04 | Forms for gates, ask_user and budgets; stable ids; visit token; label mapping; resolver identity; re-publish. |
| K15 | Rule-template catalog IR | RUL-01 (PH1) | PRF-02, RUL-02, RUL-03, WEB-07, ENG-09, WEB-09 | Template id, params, target builtin or policy, Required vs Guidance, enforceability inputs (draft, then v1 at M3). |
| K16 | Seam ledger format | OPS-01 (PH0) | FND-01, FND-02, FND-03, OPS-02, OPS-03, HRN-01, SES-02, TLS-01, BRD-01, OPS-04, BRD-03 | seams.yaml and upstream.yaml: seam id, files, CORAL(Sx) anchors, tests, budget_lines, upstream PR. |
| K17 | Server plugin registration | FND-02 (PH1) | DUR-04, API-02, RUL-01, SES-03 | server_plugins key, ROUTERS, LIFESPAN_HOOKS, ServerServices, hook ordering, fatal import failure. |
| K18 | Status-edge observer API and turn facts | SES-02 (PH1) | SES-04, HRN-03, HRN-04 | Observer signature, origin slugs (S1b), turn_outcome (S43), persisted TurnFact fields. |

## 3. Features by phase

Header: `workstream (WS- prefix dropped) · phase · milestone · priority · size · enabler|slice`; the area is the ID prefix. **G** gap rows; **S** seams owned (one owner each); **Hard/Soft** dependencies; **K+** contracts produced, **K-** consumed; **In/Out** scope; **OQ** open questions that block or shape the feature. Empty fields are omitted.

### PH0 Decisions, contracts and spikes

**SPK-01 Session topology spike and decision record** — INTEGRATION · PH0 · M1 · Critical · S · enabler  
Three-day spike that proves or rejects TLD-02 option B (children of a stable run session with own_runner, plus S51) and records the topology ADR.  
G: G-22  
In: child worktree on a shared runner uses its own cwd; turnless run session hosts children; stop spares own_runner steps; sidebar, inbox, child recovery.  
Out: facade build (SES-03); fallback build (SES-03 contingency).  
OQ: OQ-32, OQ-17

**SPK-02 claude-sdk behaviour probes** — HARNESS · PH0 · M1 · High · S · enabler  
One-week probes of claude-sdk unknowns that shape tool, evidence and test-lane contracts; output a decision memo.  
G: G-44, G-87  
In: spike 1 can_use_tool under bypass (S21); spikes 2, 4: Agent/Task reach, mock base URL; spikes 7, 16: tool timeout, idle watchdog.  
Out: native and Codex probes; bench automation (HRN-01).  
OQ: OQ-51

**SPK-03 Decision records sign-off** — ENGINE · PH0 · M1 · Critical · S · enabler  
Two-week decision sprint recording sign-off on TLD-01..21 and the open questions that gate M1/M2 contracts.  
G: G-03, G-34, G-54  
In: OQ-1 requirements baseline; OQ-2, OQ-3, OQ-12, OQ-19 semantics; OQ-28, OQ-35 auth; OQ-36, OQ-45 gate and namespace; OQ-53.  
Out: M3+ questions; owner-level choices (OQ-34).  
OQ: OQ-1, OQ-2, OQ-3, OQ-12, OQ-19, OQ-28, OQ-35, OQ-53

**FND-01 Coral package and tooling roots** — PLATFORM · PH0 · M1 · Critical · S · enabler  
Ship the coral/ import package in the wheel with lint, type, coverage, CI and CODEOWNERS roots and the import-boundary rule.  
G: G-12 · S: S29, S39, S39b, S39c, S39d, S39e, S76 · Soft: OPS-01 · K-: K16  
In: pyproject, pyrefly, isort, coverage, pre-commit roots; coral CI group; just mod; boundary lint and test; spike 10.  
Out: Alembic env (FND-03); fork guard (OPS-01).  
OQ: OQ-54

**OPS-01 Seam ledger and coral-fork-guard** — OPS · PH0 · M1 · Critical · M · enabler  
Publish the seam ledger (K16) and a required check that every upstream change is ledgered, anchored and within budget.  
G: G-83 · Soft: FND-01 · K+: K16  
In: seams.yaml seeded S1-S89; upstream.yaml pin; anchors, budgets, commit prefix, stale entries; MODIFICATIONS.md generation.  
Out: merge rehearsal (OPS-02); licence texts (OPS-03).  

**ENG-01 Engine contracts pack** — ENGINE · PH0 · M1 · Critical · M · enabler  
Publish K1 (schema, IR, JSON Schema), K2 (reducer I/O) and K3 (run log, fold) as typed, versioned modules with golden fixtures.  
G: G-01, G-03, G-04, G-05 · Hard: FND-01 · Soft: SPK-03 · K+: K1, K2, K3  
In: authoring models; reserved EGM keys and ids; frozen IR; JSON Schema export; ScopeKey everywhere (TLD-21); log kinds; enums.  
Out: loader and compiler (ENG-02); reducer behaviour (ENG-04).  
OQ: OQ-3, OQ-12, OQ-19

**SES-01 Integration contracts pack** — INTEGRATION · PH0 · M1 · Critical · M · enabler  
Publish the coral.omni protocol with a fake (K4), derived keys (K10), engine tool contracts (K6) and gate payloads (K14).  
G: G-18, G-25, G-28, G-29, G-30, G-31, G-35 · Hard: FND-01 · Soft: ENG-01, SPK-01 · K+: K4, K6, K10, K14 · K-: K2  
In: facade protocols and in-memory fake; uuid5 ids, stable_id, policy ids, gate ids; six tool schemas (TLD-20); envelope; forms.  
Out: facade implementation (SES-03/04); handlers (TLS-02).  
OQ: OQ-43, OQ-47

**API-01 Coral API and run-stream contracts** — PLATFORM · PH0 · M1 · Critical · S · enabler  
Publish the /v1/coral/* OpenAPI (K7) and run-stream protocol (K8) with a drift check, TS types and stub routers.  
G: G-74, G-75 · Hard: FND-01 · Soft: ENG-01, SES-01 · K+: K7, K8 · K-: K1, K14  
In: dump_openapi --check and drift test; generated TS types; fixture stub routers; SSE frame spec.  
Out: real handlers (API-02/03); web client (WEB-05).  
OQ: OQ-45

### PH1 Foundations (to M1; some features target M2)

**FND-02 Server plugin seam** — PLATFORM · PH1 · M1 · Critical · S · enabler  
Add an upstreamable server_plugins key that loads routers and lifespan hooks with ServerServices, wired from the CLI.  
G: G-17 · S: S32 · Hard: FND-01 · Soft: OPS-01 · K+: K17 · K-: K16  
In: routers before SPA; hook ordering; ServerServices; fatal import; spike 11 test.  
Out: Coral routers (API-02); worker start (DUR-04).  

**FND-03 Coral DB environment** — PLATFORM · PH1 · M1 · Critical · M · enabler  
Stand up Coral's Alembic env and CoralBase, applied after Omnigent reaches head on every backend, never create_all.  
G: G-13 · S: S30, S31, S57, S58 · Hard: FND-01 · Soft: OPS-01 · K-: K16  
In: coral/db base, types, ids, codecs, migrate; ensure_coral_schema guards; deploy hook; env filter; truncation; lane tests.  
Out: tables (DUR-01); store code (DUR-02/03).  
OQ: OQ-42, OQ-54

**FND-04 Coral test infrastructure and invariant harness** — OPS · PH1 · M1 · High · L · enabler  
Provide Coral test lanes, fixtures and the L1 invariant and seeded-fuzz harness reused by engine and store features.  
G: G-87, G-05 · Hard: FND-01 · Soft: FND-03, ENG-01, SPK-02 · K-: K2, K3  
In: test dirs and Coral SQLite template; invariants I1-I8, seeded fuzz; Tier B harness (mock LLM).  
Out: claude-sdk fake; browser tests.  
OQ: OQ-52

**OPS-02 Upstream merge rehearsal and fork CI hygiene** — OPS · PH1 · M1 · High · M · enabler  
Run a daily nightly^1 trial merge with rerere and Coral suites on three DB lanes, plus fork CI hygiene.  
G: G-84 · Hard: OPS-01 · Soft: FND-03, FND-04 · K-: K16  
In: rehearsal job; lockfile and CSS regeneration; disable inherited workflows; branch protection; playbook; security lane; upstreaming.  
Out: L3 suite content (SES-03); release pipeline (OPS-04).  
OQ: OQ-50

**OPS-03 Distribution identity and licensing** — OPS · PH1 · M2 · High · M · slice  
Ship a coral console script with its own data dirs so Coral and Omnigent coexist, plus NOTICE and licence inventory.  
G: G-85, G-86 · S: S75, S77 · Hard: FND-01 · Soft: OPS-01 · K-: K16  
In: ~/.coral dirs; no upstream update offers; coexistence test; coral/CLAUDE.md; NOTICE addendum; licence CI.  
Out: renaming omnigent internals; counsel sign-off (OPS-04).  
OQ: OQ-49, OQ-53, OQ-30, OQ-31

**DUR-01 Core schema and store protocols** — PLATFORM · PH1 · M1 · Critical · M · enabler  
Land coral_0001_core as a standalone PR and publish store protocols and work-item semantics (K5).  
G: G-14 · Hard: FND-03 · Soft: ENG-01 · K+: K5 · K-: K2, K3  
In: run, activation, slot, handoff, gate, queue, log, case, blob tables; scope keys and DB conventions; store ABCs incl. CAS and claim.  
Out: phase-2 tables (DUR-06); queue layout choice (owner).  
OQ: OQ-34

**DUR-02 Workflow store and blob ledger** — PLATFORM · PH1 · M1 · High · M · slice  
Store workflows DB-canonically as drafts plus immutable content-addressed versions, with a blob GC ledger.  
G: G-14, G-15, G-68 · Hard: DUR-01 · Soft: ENG-02 · K-: K5, K1  
In: drafts with ETag; immutable versions; blob key scheme, ledger, caps; simulation case storage.  
Out: repo import (WSP-02); repo export (EXT-03).  
OQ: OQ-8, OQ-9

**DUR-03 Run store with CAS transitions** — PLATFORM · PH1 · M2 · Critical · M · slice  
Persist run state and log with one short CAS transaction per transition, proven under contention on all lanes.  
G: G-14 · Hard: DUR-01 · Soft: ENG-04 · K-: K5, K2, K3  
In: idempotent start_key; apply_transition CAS; log seq and receipts; reduce-and-retry; contention tests on 4 lanes.  
Out: queue (DUR-04); purge (DUR-07).  

**DUR-04 Durable work queue** — PLATFORM · PH1 · M2 · Critical · L · enabler  
Build the at-least-once queue for signals, timers and effects on StartupLease and lock-and-recheck patterns, never PersistentTaskScheduler.  
G: G-11 · Hard: DUR-01 · Soft: FND-02, DUR-03 · K-: K5, K17  
In: off-loop enqueue; claim, renew, finish, backoff; drainer and timer scan in lifespan; refuse multi-replica (TLD-08).  
Out: reconcile (DUR-05); PersistentTaskScheduler (R-4).  
OQ: OQ-34, OQ-42

**ENG-02 Loader, compiler and content hash** — ENGINE · PH1 · M1 · Critical · M · slice  
Turn workflow YAML into the frozen, hashed IR with source marks so errors point at a box or arrow.  
G: G-01 · Hard: ENG-01 · K-: K1  
In: safe-load with marks; yaml_path ranges; compile; stable ids; content hash; golden tests.  
Out: validation (ENG-03); comment-preserving edits (WEB-02).  

**ENG-03 Static validator and derived joins** — ENGINE · PH1 · M1 · Critical · M · slice  
Implement V1-V7 and V10-V13 with box-anchored explanations, derived joins and block-structure rules.  
G: G-02, G-03 · Hard: ENG-02 · K-: K1  
In: graph rules, regions, loop table, V12; AND-join vs merge; back-arrow rule; block structure (R-24).  
Out: V8 (ENG-09); V9 (RUL-02).  
OQ: OQ-19, OQ-9

**ENG-04 Reducer core** — ENGINE · PH1 · M1 · Critical · L · slice  
Implement the pure reducer for runs, activations, slots, attempts and decisions, with joins and loop limits, never throwing.  
G: G-04, G-03, G-05 · Hard: ENG-01 · Soft: ENG-03, FND-04 · K-: K1, K2, K3  
In: state machines returning Rejections; handoffs; decision requests with collections (D9); loops, at_limit, joins; fold-safe log.  
Out: gates (ENG-05); lifecycle and timers (ENG-07).  

**ENG-05 Durable gate visits** — ENGINE · PH1 · M1 · Critical · M · slice  
Model gates as durable visits with tokens, CAS resolution and authored outcomes; reminders never auto-resolve (R-7).  
G: G-34 · Hard: ENG-04 · K-: K2, K14  
In: visit tokens; stale rejection; authored outcome labels; reminder and escalation timers.  
Out: elicitation surface (GTE-01); answer API (API-03).  
OQ: OQ-3, OQ-5

**ENG-06 Simulate engine and saved cases** — ENGINE · PH1 · M1 · Critical · M · slice  
Run the reducer with stub effects over scripted scenarios, save cases that re-run per version, and estimate sessions.  
G: G-66 · Hard: ENG-04, ENG-05 · Soft: DUR-02 · K-: K1, K2, K3  
In: scripted labels, lists, gate answers; K3-shaped trace; saved cases; session estimate.  
Out: exhaustive mode (deferred); Simulate UI (WEB-03).  
OQ: OQ-9

**API-02 Coral API foundation and workflow endpoints** — PLATFORM · PH1 · M1 · Critical · M · slice  
Mount /v1/coral/* with the Coral-owned enablement gate and serve workflows, drafts, versions, validate, simulate and CLI upload.  
G: G-74, G-68, G-81, G-15, G-66 · Hard: FND-02, API-01, DUR-02 · Soft: ENG-03, ENG-06 · K-: K7, K17, K5, K1  
In: GET /v1/coral/info (TLD-03); workflows CRUD, ETag/412, version freeze; validate, simulate; upload CLI.  
Out: runs and stream (API-03); repo import (WSP-02).  
OQ: OQ-45, OQ-36

**PRF-01 Bundle format and params.coral schema** — HARNESS · PH1 · M1 · High · S · enabler  
Publish the per-step bundle format and params.coral schema (K12) with a Coral-side linter.  
G: G-51, G-50 · Hard: FND-01 · Soft: SES-01 · K+: K12 · K-: K6, K10  
In: deterministic tar; coral__ naming; params.coral keys; hygiene defaults; provider auth; lint.  
Out: generator (PRF-02); revisions (PRF-03).  
OQ: OQ-37

**WSP-01 Workspace-ops contract and reaper guard** — WORKSPACE · PH1 · M1 · High · S · enabler  
Publish WorkspaceOps and host frame schema (K13) behind MVP and host-channel adapters, and land the S71 reaper fix.  
G: G-38 · S: S71 · Hard: FND-01 · Soft: EVD-01 · K+: K13 · K-: K11  
In: ops: fingerprint, check, commit, reset, salvage, merge; draft S40 frames; S71 fix with exit-status test.  
Out: host channel (WSP-03); evidence logic (EVD-*).  

**EVD-01 Evidence-requirement IR and evaluator** — WORKSPACE · PH1 · M1 · High · M · slice  
Define the evidence IR (K11) and a pure evaluator with final-pass semantics so formatter-then-test cannot livelock.  
G: G-40 · Hard: FND-01 · Soft: ENG-01, WSP-01 · K+: K11 · K-: K1  
In: commands, may-modify, exit-code rules, scope; final-pass evaluation; messages; temp-git tests.  
Out: capture (EVD-02); Coral-run checks (EVD-04).  
OQ: OQ-10

**HRN-01 Capability registry and bench** — HARNESS · PH1 · M2 · High · M · slice  
Fill and extend capability fields, expose them per spelling, publish CapabilityMatrix (K9), and back values with bench probes.  
G: G-44 · S: S22, S23, S59, S78 · Hard: FND-01 · Soft: SPK-02, OPS-01 · K+: K9 · K-: K16  
In: fields and guard tests; capabilities_by_spelling incl. native; claude-sdk probes first; coral-bench.yml.  
Out: label computation (RUL-02); Codex probes before HRN-04.  
OQ: OQ-51

**RUL-01 Coral policies and run guard** — INTEGRATION · PH1 · M2 · Critical · M · slice  
Ship the coral.policies module and a required-policy provider that injects a run guard, and publish the K15 draft.  
G: G-45, G-46 · S: S52 · Hard: FND-02 · Soft: PRF-01, DUR-03 · K+: K15 · K-: K10, K12, K17  
In: step_roster, orchestrator_guard, engine_tool_guard; S52 provider on coral.run_id; run guard DENY when paused or cancelled.  
Out: rules catalog (RUL-03); budget reason (RUL-05).  
OQ: OQ-38

**SES-02 Seam pack A: status edges and engine dispatch** — INTEGRATION · PH1 · M2 · Critical · M · enabler  
Land upstreamable session seams as one-line registry calls: status-edge observers with origin and outcome, and engine dispatch.  
G: G-20, G-19 · S: S1, S1b, S43, S4, S41, S42 · Soft: OPS-01, FND-02 · K+: K18 · K-: K16  
In: observer registry; bypass notify; origin slugs; headless turn_outcome; S41 handle; S42 EngineEventContext.  
Out: Coral observer (SES-04); S2 (HRN-04).  
OQ: OQ-41

**TLS-01 Seam pack B: engine tool transport** — INTEGRATION · PH1 · M2 · Critical · M · enabler  
Land the extension tool provider and server tool registry so one declaration registers, forwards, relays and instructs engine tools.  
G: G-26, G-27 · S: S50, S7, S8, S9, S11, S12, S10, S49 · Hard: FND-01 · Soft: SES-01, SES-02 · K-: K6, K12, K16  
In: extensions.py via entry point; coral_ prefix; one-line sites incl. prompt.py; server_tools registry; S49 provenance.  
Out: handlers (TLS-02); native channel enablement (HRN-03/04).  
OQ: OQ-43

**BRD-01 Coral brand skin** — BRAND · PH1 · M1 · High · M · slice  
Apply Clay Score in the omni slot, --font-display and Coral marks without disturbing existing heading users.  
G: G-78, G-79 · S: S79, S81, S82, S83, S89 · Soft: OPS-01 · K-: K16  
In: omni palette data; scoped remap; CSS tests; --font-display, not --font-heading; marks, hero, favicon, onboarding art.  
Out: sidebar row S80 (BRD-02); native shells (BRD-03).  
OQ: OQ-7, OQ-30

**BRD-02 Navigation shell, Coral gate and desk headers** — BRAND · PH1 · M1 · High · M · slice  
Add /workflows and /profiles, Coral navigation and desk headers behind the Coral gate, with empty states.  
G: G-80, G-81 · S: S34, S80, S84 · Soft: API-01, API-02, BRD-01 · K-: K7  
In: coralRoutes fragment (spike 17); nav; palette actions; CoralGate on /v1/coral/info; CoralPageHeader; ?agent= focus (R-17).  
Out: page content (WEB-*); upstream Feature flag (S33).  
OQ: OQ-27

**WEB-01 Workflow graph model and read-only diagram** — WEB · PH1 · M2 · High · M · slice  
Render compiled workflows as a read-only diagram through one xyflow adapter shared by editor, Simulate and run view.  
G: G-71 · Hard: ENG-01 · Soft: API-01, BRD-02 · K-: K1, K7  
In: graph model from IR; Note layout-only; dagre in a worker; overlay API.  
Out: editing (WEB-08/09); ELK.  
OQ: OQ-30

**WEB-02 Workflow library and YAML editor** — WEB · PH1 · M2 · High · M · slice  
Give authors a library and a Monaco YAML pane with server-validator markers, problem list and comment-preserving edits.  
G: G-70, G-68, G-73 · Hard: API-01 · Soft: API-02, WEB-01, BRD-02 · K-: K7, K1  
In: library; 412 conflict dialog; monacoSetup plus yaml CST (TLD-15); server-only markers; round-trip fixtures.  
Out: promise labels (WEB-07); canvas (WEB-08).  
OQ: OQ-9

### PH2 Stateful engine and first end-to-end run (to M2)

**DUR-05 Reconciler, effect workers and durability faults** — PLATFORM · PH2 · M2 · Critical · L · slice  
Close the durable loop: claim, reconcile and dispatch effects in ambient scopes, recovering from a crash at every commit boundary.  
G: G-11, G-25, G-16, G-87 · Hard: DUR-03, DUR-04, ENG-04 · Soft: SES-01, SES-03 · K-: K2, K4, K5  
In: startup reconcile, resync, liveness; scoped effects; lazy authority checks; commit-boundary faults; E2E-2 restart.  
Out: session semantics (SES-04/05); retention (DUR-07).  

**DUR-06 MVP runtime schema PRs** — PLATFORM · PH2 · M2 · High · S · enabler  
Land coral_0002 (bindings, stable_id map, step agents, alerts, questions) and coral_0003 (repos, patterns, observations).  
G: G-14 · Hard: DUR-01 · Soft: PRF-01, EVD-01 · K-: K5, K11, K12  
In: session bindings; stable_id map; step agents, alerts, questions; repos, patterns, observations.  
Out: profile revisions (PRF-03); lineage (ENG-10).  

**ENG-07 Run lifecycle, timers and liveness policies** — ENGINE · PH2 · M2 · Critical · L · slice  
Add pause, resume, cancel and retry, plus auto-advance, decision watchdog, rejected-call pause and overdue alerts.  
G: G-06, G-07 · Hard: ENG-04 · Soft: ENG-05 · K-: K2, K3  
In: pause reasons; resume on pinned version; retry; cancel chain (R-13); late submits rejected; watchdog; 3-rejection pause; overdue.  
Out: budget pause (RUL-05); take-over (SES-07).  
OQ: OQ-14, OQ-13

**SES-03 Session facade: request-free create and topology** — INTEGRATION · PH2 · M2 · Critical · L · slice  
Implement idempotent request-free session creation per the topology ADR, plus reads, guarded by a facade contract suite.  
G: G-18, G-22 · S: S51 · Hard: SPK-01, SES-01, FND-02 · Soft: PRF-02, WSP-02 · K-: K4, K10, K17  
In: fire.py-subset create; uuid5 ids; policies before input; S51 parent-wake exemption; reads; L3 suite in the rehearsal.  
Out: dispatch (SES-04); fallback build (+2-3 wk contingency).  
OQ: OQ-32, OQ-17, OQ-47

**SES-04 Step turn loop: dispatch and turn-end detection** — INTEGRATION · PH2 · M2 · Critical · L · slice  
Brief, nudge, interrupt and stop run sessions through _post_event_impl, and decide durably per mode when a turn ended.  
G: G-19, G-20, G-21, G-25, G-07 · Hard: SES-02, SES-03, DUR-04 · Soft: DUR-06 · K-: K4, K18, K2  
In: stable_id sends; read before resend; preflight; O(1) observer; TurnFacts enqueued; per-mode turn-end rule.  
Out: native specifics (HRN-03); runner loss (SES-05).  
OQ: OQ-41, OQ-13

**SES-05 Recovery and drift handling** — INTEGRATION · PH2 · M2 · High · L · slice  
Handle runner loss and host offline with generation-fenced slot restarts, and detect, re-attach or pause on drift.  
G: G-23, G-24 · Hard: SES-04, DUR-05 · Soft: WSP-02 · K-: K4, K2, K13  
In: liveness poll; wake; no restart in 72 h hold; fencing, salvage then reset; relaunch children; drift checks; archive and delete; spike 14.  
Out: mutation guards (EXT-04); refresh (SES-06).  
OQ: OQ-17

**TLS-02 submit_handoff and choose_arrow handlers** — INTEGRATION · PH2 · M2 · Critical · M · slice  
Turn coral_submit_handoff and coral_choose_arrow calls into reducer commands in one short transaction with actionable rejections.  
G: G-28, G-29 · Hard: TLS-01, ENG-04, DUR-03 · Soft: EVD-02, SES-04 · K-: K6, K2, K5  
In: handoff fields; generation dedup; operation_id dedup; evaluating lease; generic label; items (D9); counter.  
Out: ask_user (TLS-03); messaging (TLS-04).  
OQ: OQ-12

**TLS-03 Orchestrator: profile, decision protocol and ask_user** — INTEGRATION · PH2 · M2 · Critical · L · slice  
Ship the claude-sdk orchestrator with no OS tools and guard in bundle guardrails, the decision protocol, and coral_ask_user.  
G: G-32, G-33, G-30 · Hard: TLS-02, PRF-02 · Soft: GTE-01, RUL-01 · K-: K6, K12, K14  
In: no os_env; guard in guardrails (TLD-05); chat interleave; lazy orchestrator; ask_user; deny vendor ask tools.  
Out: messaging tools (TLS-04); orchestrator refresh (SES-06).  
OQ: OQ-13

**GTE-01 Gate elicitation surface (seam pack C)** — INTEGRATION · PH2 · M2 · Critical · M · slice  
Surface gates, ask_user and budget prompts as stable-id elicitations on the run session and route answers back with resolver identity.  
G: G-35, G-34 · S: S5, S6, S6a, S6b · Hard: ENG-05, SES-03 · Soft: DUR-05 · K-: K14, K4, K10  
In: S5 observer list; S6a publish; S6b verdict registry; re-publish on startup and replacement; ApprovalCard and /approve reuse.  
Out: Inbox (GTE-02); policy-ASK gates (R-7).  
OQ: OQ-3, OQ-4

**GTE-02 Workflow Inbox: alerts feed and inbox kind** — WEB · PH2 · M2 · Critical · L · slice  
Add a server-acked workflow inbox kind with run actions and notifications, so gates are answered from the Inbox while the app is open.  
G: G-36 · S: S36, S37, S85 · Hard: DUR-06, API-02, GTE-01 · Soft: ENG-07, BRD-02 · K-: K7, K14  
In: inbox feed, ack, run actions; alert producers; card, sidebar count, CoralRuntimeProvider; per-step suppression; app-open notice.  
Out: webhook and email (GTE-03); push (deferred).  
OQ: OQ-24

**EVD-02 Done-when on claude-sdk** — WORKSPACE · PH2 · M2 · Critical · L · slice  
Capture claude-sdk command exit codes, compute L1 fingerprints from runner /changes and the session shell, and evaluate done-when at handoff.  
G: G-39, G-38, G-40 · S: S68, S69 · Hard: EVD-01, WSP-01, DUR-06 · Soft: TLS-02, WSP-02, SPK-02 · K-: K11, K13, K6  
In: S68 registry and claude-sdk site; S69(a); runner exit-status test; K13 MVP adapter; bounded handoff scan.  
Out: L2 and other modes (WSP-03, HRN-*); Coral-run checks (EVD-04).  
OQ: OQ-10

**EVD-03 Repository command detection and confirmation** — WORKSPACE · PH2 · M2 · High · M · slice  
Detect test, lint, format and typecheck commands in a bound repo, let the author confirm, and snapshot them into the version.  
G: G-41, G-42 · Hard: DUR-06, SES-01 · Soft: WSP-02 · K-: K4, K11  
In: parsers via request-free host read; per-repo patterns; confirm API; version snapshot (X-32).  
Out: LLM translation (deferred); picker UI (WEB-04).  

**PRF-02 Step bundles and seeded profiles** — HARNESS · PH2 · M2 · Critical · L · slice  
Generate content-addressed per-step bundles with guardrails and seeded profiles, hidden from pickers, with Enforced read-only reviewers.  
G: G-51, G-50, G-52, G-47 · S: S54 · Hard: PRF-01, DUR-06 · Soft: RUL-01, HRN-02 · K-: K12, K15, K10  
In: bundles.py; golden tests; guardrails; seeded profiles pinned by digest; reviewer write_paths [] (moved to M2); S54.  
Out: user revisions (PRF-03); S53 guards (EXT-04).  
OQ: OQ-48

**HRN-02 claude-sdk run-mode guard: credentials and usage limits** — HARNESS · PH2 · M2 · Critical · M · slice  
Restrict run-owned claude-sdk sessions to API-key or provider auth pinned per run, and map rate limits to a plan-limit pause.  
G: G-54, G-57 · S: S13, S63, S24 · Hard: SPK-03 · Soft: PRF-01, HRN-01 · K-: K12, K9  
In: refuse subscription OAuth; bindings respected; harness_accounts preflight; S63 test; spikes 19, 20; RateLimitEvent with reset time.  
Out: claude-native path (HRN-03); Codex limits (HRN-04/05).  
OQ: OQ-28

**WSP-02 Repo bindings, run worktree and restart safety** — WORKSPACE · PH2 · M2 · Critical · L · slice  
Bind a repo, manage the run worktree request-free, import workflows, and commit, salvage and reset so retries start clean.  
G: G-58, G-59, G-68 · S: S72 · Hard: WSP-01, SES-01, DUR-06 · Soft: SES-03 · K-: K13, K4, K10  
In: run worktree; S72 head_commit; retention; workspace= without git; binding API; repo import; commits, salvage refs, reset; spike 8.  
Out: per-agent worktrees (WSP-04); host channel (WSP-03).  
OQ: OQ-18, OQ-39, OQ-44

**API-03 Runs API, gate answers, preflight and run stream** — PLATFORM · PH2 · M2 · Critical · L · slice  
Serve runs, lifecycle actions, gate answers and preflight, and tail the run log as a resumable SSE stream.  
G: G-74, G-75, G-76, G-07, G-34 · Hard: API-02, DUR-03 · Soft: ENG-07, SES-03, HRN-02 · K-: K7, K8, K3, K4  
In: runs with start_key; pause, resume, cancel, retry; gate answers with visit_token; preflight; SSE with seq and Last-Event-ID.  
Out: take-over endpoints (SES-07); amendments (ENG-10).  
OQ: OQ-4

**WEB-03 Simulate UI** — WEB · PH2 · M2 · High · M · slice  
Let authors script simulations, see visit counts and taken edges on the diagram, and save cases as tests.  
G: G-67 · Hard: WEB-01, API-02 · Soft: ENG-06 · K-: K7, K3  
In: scenario editor; shared overlay; estimate; saved-test badges.  
Out: exhaustive mode (deferred); run data (WEB-05).  

**WEB-04 Templates and run-start dialogs** — WEB · PH2 · M2 · Critical · L · slice  
Ship the MVP template, gallery, Use-template dialog with done-when picker, and the start-run dialog with preflight.  
G: G-69, G-42, G-76 · Hard: WEB-02, API-02 · Soft: EVD-03, API-03, WSP-02, PRF-02, ENG-06 · K-: K7, K11  
In: server-bundled MVP template with saved simulations; Use-template dialog; command picker (TLD-19); start dialog; workspace picker; estimate.  
Out: PR-review template (ENG-08); cmdk picker (WEB-06).  
OQ: OQ-2, OQ-16

**WEB-05 Run view v1 and run stream client** — WEB · PH2 · M2 · Critical · L · slice  
Show a live run with overlay, inspector tabs, evidence, timeline, agent pane, pause banners and steering, fed by a resumable stream.  
G: G-77, G-75 · Hard: WEB-01, API-01 · Soft: API-03, GTE-01, SES-03 · K-: K7, K8, K3  
In: SSE client with id:, slots, polling fallback; overlay, tabs, ApprovalCard; ?agent= pane; banners; steering; controls.  
Out: depth features (WEB-10); labels (WEB-07).  
OQ: OQ-17, OQ-23

### PH3 Profiles, capabilities and enforcement (to M3)

**RUL-02 Capability-aware validation and promise labels** — ENGINE · PH3 · M3 · High · M · slice  
Compute the four promise labels per step and mode from the IR and K9, and validate enforceability (V9) so nothing over-claims.  
G: G-73, G-47, G-44 · Hard: HRN-01, ENG-03, RUL-01 · Soft: PRF-02 · K-: K9, K15, K1  
In: V9; native unenforceable until S14; read-only Enforced only on claude-sdk; pure label API; frozen matrix fixture.  
Out: panel UI (WEB-07); rule compilation (RUL-03).  
OQ: OQ-24

**RUL-03 Rules catalog v1 and reactions** — INTEGRATION · PH3 · M3 · High · L · slice  
Let authors add Required and Guidance rules from a typed template catalog over builtins, with timer reactions (TLD-19).  
G: G-48 · Hard: RUL-01, RUL-02, PRF-02 · Soft: HRN-03, ENG-07 · K-: K15, K9, K12  
In: templates incl. egress allowlist (R-12); compile to guardrails and policies; reactions; K15 v1.  
Out: free-text translation (deferred); V8 groups (ENG-09).  
OQ: OQ-38

**RUL-04 Native fail-closed enforcement** — HARNESS · PH3 · M3 · Critical · M · slice  
Make native policy hooks fail closed for run-owned sessions and carry sub-agent identity.  
G: G-49 · S: S14, S16 · Hard: HRN-01, RUL-01 · Soft: SPK-02 · K-: K9  
In: fail-closed output; early returns deny; timeout; hooks-installed check; S16; E2E-4; spike 6.  
Out: S15 (HRN-04); S21 unless SPK-02 requires it.  

**PRF-03 Profile revisions and pinning** — HARNESS · PH3 · M3 · High · M · slice  
Make profiles pinned, immutable revisions over custom agents so edits never leak into versioned or running workflows.  
G: G-50, G-14 · S: S66 · Hard: PRF-02, FND-03 · Soft: WEB-06 · K-: K12, K5  
In: coral_0004 revisions and pins; drift check; reinstall edits; profiles API; spike 18; optional S66.  
Out: desk UI (WEB-06); git import (EXT-03).  
OQ: OQ-37

**HRN-03 claude-native step mode** — HARNESS · PH3 · M3 · High · L · slice  
Offer claude-native steps for subscription users behind fail-closed hooks, with launch text, Stop-hook turn end and honest labels.  
G: G-55, G-39, G-26 · S: S3, S64 · Hard: RUL-04, PRF-02, SES-04 · Soft: RUL-02, HRN-01 · K-: K9, K12, K11, K18  
In: S3; enable S12 channel; Stop-hook turn end; S64 egress; PostToolUse observations; steps only; E2E-3; /clear policy.  
Out: orchestrator on native; codex-native (HRN-04).  
OQ: OQ-28, OQ-35, OQ-46

**WEB-06 Agent Profiles desk and picker** — WEB · PH3 · M3 · High · M · slice  
Ship /profiles as a lens over custom agents and a cmdk picker with capability chips and 'used by' badges.  
G: G-53 · Hard: PRF-03 · Soft: HRN-01 · K-: K7, K9, K12  
In: list over custom agents plus metadata; capability chips ('Claude'); picker in editor and dialogs.  
Out: localStorage profiles (R-16); agent editing beyond reinstall.  
OQ: OQ-27

**WEB-07 Guarantees panel and rule authoring UI** — WEB · PH3 · M3 · High · M · slice  
Show 'What Coral guarantees' with four per-mode labels and author rules from the catalog with confirmation.  
G: G-73, G-48 · Hard: RUL-02 · Soft: RUL-03, WEB-02 · K-: K9, K15, K7  
In: panel and on-box chips; Required vs Guidance picker; confirmation; labels follow mode changes.  
Out: free-text rules; label computation (RUL-02).  
OQ: OQ-24

### PH4 Trust and structure (to M4)

**WSP-03 Host workspace-op channel and L2 fingerprints** — WORKSPACE · PH4 · M4 · Critical · L · slice  
Build the reaper-guarded host op channel, move fingerprints, commits, resets and salvage onto it, and add L2 fingerprints.  
G: G-38 · S: S40, S40b · Hard: WSP-01, WSP-02 · Soft: EVD-02 · K-: K13, K11  
In: frames, token, guarded dispatcher, proxy, journal; S40b op registry; L2; adapter swap, evaluator unchanged.  
Out: checks (EVD-04); merges (WSP-04).  

**EVD-04 Coral-run checks, verifier pattern and worktree setup** — WORKSPACE · PH4 · M4 · High · L · slice  
Run pinned checks in a Coral-controlled detached checkout with JUnit and integrity diff, feeding results into attempts.  
G: G-43, G-58 · Hard: WSP-03, EVD-03 · Soft: ENG-07 · K-: K13, K11  
In: sandboxed exec jobs; S72 detached mode; JUnit; integrity diff; verifier pattern; per-worktree setup.  
Out: hidden held-out tests; LLM judges.  
OQ: OQ-44

**ENG-08 Repeat-for-each and parallel regions** — ENGINE · PH4 · M4 · High · L · slice  
Add repeat-for-each and parallel split/join with region cancel to reducer, validator and Simulate; ship the PR-review showcase.  
G: G-08, G-09 · Hard: ENG-04, ENG-03 · Soft: SES-04, WSP-04 · K-: K1, K2, K3  
In: order, empty, failure, concurrency, batching; region cancel; E2E-5; PR-review loop template.  
Out: groups (ENG-09); merges (WSP-04).  
OQ: OQ-19, OQ-40

**ENG-09 Groups, saved blocks, Wait and Sub-workflow** — ENGINE · PH4 · M4 · Medium · L · slice  
Add groups and saved blocks with inherited rules (V8) and the hidden Wait and Sub-workflow kinds.  
G: G-10 · Hard: ENG-03, ENG-04 · Soft: ENG-08, RUL-03 · K-: K1, K2, K15  
In: group IR; V8; wait timers; sub-workflow with pinning.  
Out: nesting beyond OQ-19; canvas group UI (WEB-09).  
OQ: OQ-19

**TLS-04 Messaging and assignment tools** — INTEGRATION · PH4 · M4 · Medium · M · slice  
Add coral_message_agent, coral_assign_agents and coral_assign_task for parallel members and re-tasking.  
G: G-31 · Hard: TLS-02, SES-04 · Soft: ENG-08, WSP-04 · K-: K6, K4  
In: engine-routed messages; rate limit; 'up to' rosters; re-task for conflicts (D10).  
Out: EGM resolutions (EXT-02); sys_session_message reuse.  

**WSP-04 Per-agent worktrees and serial merges** — WORKSPACE · PH4 · M4 · High · L · slice  
Give each writer its own worktree, merge serially into the run worktree, resolve conflicts in place, and run post-merge checks.  
G: G-60 · Hard: WSP-03, EVD-04 · Soft: TLS-04, ENG-08 · K-: K13, K11  
In: agent branches; serial merges; conflict sub-state; mandatory post-merge checks (D8); LFS probe.  
Out: sandboxes (WSP-05); parallel writers without checks.  
OQ: OQ-40

**SES-06 Refresh as slot restart** — INTEGRATION · PH4 · M4 · Medium · M · slice  
Refresh long step and orchestrator sessions at a per-mode threshold by restarting the slot with a refresh note (TLD-13).  
G: G-63 · S: S25, S27, S45 · Hard: SES-05, HRN-01 · Soft: WEB-10 · K-: K4, K9, K6  
In: 7000 bp default below auto-compaction; restart with note; S25 literal; S45; S27 retests.  
Out: fork-based refresh (S47); stitched UI (WEB-10).  
OQ: OQ-46

**SES-07 Take-over and hand-back** — INTEGRATION · PH4 · M4 · Medium · M · slice  
Let a user take over a step, pausing engine timers, and hand back with a recomputed fingerprint and done-when.  
G: G-64 · Hard: SES-04, EVD-02, ENG-07 · Soft: WEB-10 · K-: K2, K4, K11  
In: taken_over(by) state; stable_id attribution; endpoints; salvage guard.  
Out: multi-user take-over; UI controls (WEB-10).  
OQ: OQ-11

**GTE-03 External notification connector** — INTEGRATION · PH4 · M4 · High · M · slice  
Notify unattended users of gates and pauses through an outbox-driven connector, webhook first, then email or Slack DM.  
G: G-37 · Hard: GTE-02, DUR-04 · K-: K5, K14, K7  
In: per-user channel config; idempotent delivery via queue; secret-free deep links.  
Out: push (deferred); Slack-originated sessions.  
OQ: OQ-6

**WEB-08 Canvas editing core** — WEB · PH4 · M4 · Medium · L · slice  
Make the diagram editable through comment-preserving YAML patches with a stable-id layout file and one undo stack.  
G: G-72 · Hard: WEB-01, WEB-02 · Soft: WEB-06, RUL-03 · K-: K1, K7  
In: palette, connect, delete as CST patches; layout doc by node id; shared undo; server validation.  
Out: inspectors (WEB-09); structured-model regeneration.  
OQ: OQ-22

**WEB-09 Canvas inspectors and accessible outline** — WEB · PH4 · M4 · Medium · L · slice  
Add step, arrow, gate, decision and group inspectors and an accessible outline view.  
G: G-72 · Hard: WEB-08 · Soft: WEB-06, WEB-07, ENG-09 · K-: K1, K9, K15  
In: inspectors with picker, done-when, rules; outline with keyboard and screen-reader parity.  
Out: mobile editing; free-text rules.  
OQ: OQ-22

**WEB-10 Run view depth** — WEB · PH4 · M4 · Medium · M · slice  
Complete the run view with why-taken and why-not-taken arrows, structure progress, take-over controls and the stitched orchestrator.  
G: G-77, G-08 · S: S86 · Hard: WEB-05 · Soft: ENG-08, SES-06, SES-07 · K-: K8, K3, K7  
In: join waits; '3 of N' badges; refresh dividers; take-over controls; optional 'Part of run' chip.  
Out: run sharing (EXT-04); mobile layouts.  
OQ: OQ-23

### PH5 Production readiness (to M4)

**HRN-04 codex-native mode** — HARNESS · PH5 · M4 · Medium · L · slice  
Enable codex-native steps with terminal turn outcomes, refusal without hooks and an explicit unattended stance.  
G: G-56, G-20, G-57 · S: S2, S15, S62 · Hard: RUL-04, HRN-01, SES-04 · Soft: RUL-02 · K-: K9, K12, K18  
In: S2 outcomes; S15 refusal; S62 stance; native text; observations; rate limits; spike 12.  
Out: headless Codex (HRN-05); hosted use before OQ-29.  
OQ: OQ-29

**HRN-05 Headless codex mode** — HARNESS · PH5 · M4 · Low · L · slice  
Enable headless Codex steps with thread routing, compaction, hook-based gating and an honest read-only stance.  
G: G-56, G-57 · S: S18, S19, S20, S60, S61, S67 · Hard: HRN-01, RUL-01 · Soft: HRN-04 · K-: K9, K12  
In: S18-S20; S60 switches; S61 read-only; S67 fail-closed; spike 13.  
Out: codex-native (HRN-04); hosted use before OQ-29.  
OQ: OQ-29

**RUL-05 Run and step budgets** — INTEGRATION · PH5 · M4 · High · M · slice  
Cap spend with an engine run budget that pauses and asks to raise or stop, plus step budgets and estimates.  
G: G-62 · Hard: RUL-01, GTE-01, SES-04 · Soft: ENG-06 · K-: K14, K4, K9  
In: spend aggregator; paused(budget); elicitation; run guard reason; overshoot; tokens for plan users; step budgets.  
Out: cost_budget as primary (R-5); org billing.  
OQ: OQ-15, OQ-16

**ENG-10 Versions and amendments-lite** — ENGINE · PH5 · M4 · Medium · M · slice  
Show version history and diffs, and cancel-and-restart a run from a chosen node with carried handoffs (TLD-18).  
G: G-65, G-14 · Hard: ENG-07, DUR-03 · Soft: WEB-10 · K-: K1, K2, K5  
In: versions list and diff; restart-from-node with carried handoffs; lineage migration PR.  
Out: 'Apply to this run' (post-M4); counter remapping.  
OQ: OQ-4

**DUR-07 Retention, purge and account lifecycle** — PLATFORM · PH5 · M4 · Medium · M · slice  
Purge runs and blobs under a retention policy and carry or purge Coral rows on account revocation and migration.  
G: G-16 · S: S56 · Hard: DUR-05 · K-: K5  
In: purge_run with blob GC; engine agent-row GC; S56 callbacks; retention jobs.  
Out: legal hold; lazy checks (done in DUR-05).  
OQ: OQ-25

**OPS-04 Production readiness: scale, DB lanes, security and release** — OPS · PH5 · M4 · Critical · L · slice  
Certify release: all DB lanes, a Coral load scenario, a security review, a rehearsed upstream merge and a release pipeline.  
G: G-84, G-86, G-87 · Hard: OPS-02, DUR-05 · Soft: WSP-03, HRN-04 · K-: K16  
In: 4 DB lanes; dev/loadtest scenario; threat review (D25, S49, host tokens, spike 15); counsel sign-off; release pipeline.  
Out: multi-replica (TLD-08); store distribution.  
OQ: OQ-42, OQ-30

**BRD-03 Native shell identity** — BRAND · PH5 · M4 · Medium · M · slice  
Rebrand Electron, iOS and Android shells with Coral ids, icons, scheme and updater feed, and deep-link to runs.  
G: G-82 · S: S38, S87, S88 · Hard: BRD-01 · Soft: OPS-03 · K-: K16  
In: Electron ids, coral:// scheme, Coral updater feed first; Assets.car; iOS and Android names, icons; run deep links.  
Out: store listings (OQ-31); mobile editing.  
OQ: OQ-31, OQ-23

### PH6 Post-M4 extensions

**WSP-05 Managed-sandbox runs** — WORKSPACE · PH6 · post-M4 · Low · L · slice  
Run workflows in managed sandboxes with bind-mode worktrees, host-keyed keep-warm and checkpoint relaunch.  
G: G-61 · S: S28, S70 · Hard: WSP-03 · K-: K13  
In: S28 bind mode, checkpoints; S70 keep-warm; spike 9; plain-folder shadow repos.  
Out: local runs; multi-replica.  
OQ: OQ-5

**EXT-01 Improvement suggestions** — ENGINE · PH6 · post-M4 · Low · L · slice  
Propose workflow improvements from run logs as YAML diffs, never weakening evidence or gates.  
G: G-88 · Hard: DUR-03 · Soft: ENG-10, WEB-08 · K-: K3, K1  
In: log signals (first-try failures, limits, cost, always-approve); proposal UX with diffs.  
Out: auto-apply; evidence weakening.  
OQ: OQ-26

**EXT-02 Elephant-Goldfish showcase** — ENGINE · PH6 · post-M4 · Low · M · slice  
Ship the Elephant-Goldfish template with persistent step sessions across passes, scoped inputs and typed resolutions.  
G: G-89 · S: S65 · Hard: WSP-03, SES-04 · Soft: ENG-08, TLS-04 · K-: K1, K13  
In: slot rebinding for persistent sessions; DENY-policy input scoping preferred over S65; ESCALATE to gate; attribution.  
Out: elephant as orchestrator (D4.2); AgentSpec changes (TLD-04).  
OQ: OQ-30

**EXT-03 Git sharing and repo export** — WORKSPACE · PH6 · post-M4 · Low · M · slice  
Export workflows to .coral/ in a repo and import workflows, templates and profiles from git.  
G: G-90, G-68 · S: S74 · Hard: WSP-02 · Soft: PRF-03 · K-: K13, K12  
In: S74 confined write with expected hash; git import of workflows, templates, profiles.  
Out: marketplace; repo-canonical editing.  
OQ: OQ-33

**EXT-04 Run sharing, teams and session guards** — INTEGRATION · PH6 · post-M4 · Low · L · slice  
Share runs with engine-managed grants and team approvers, and add reserved prefixes and mutation guards (TLD-12).  
G: G-90, G-24, G-52 · S: S26, S46, S53 · Hard: SES-05, GTE-01 · K-: K10, K14  
In: engine-managed grants; team approvers; S26/S46 reserved labels with /clear policy; S53 mutation guards.  
Out: per-session sharing reuse; multi-replica.  
OQ: OQ-4, OQ-46

**EXT-05 Automations trigger and workflows as tools** — PLATFORM · PH6 · post-M4 · Low · M · slice  
Start workflows from an Automations 'Run workflow' action and expose workflows as tools or APIs.  
G: G-90 · Hard: API-03 · K-: K7  
In: Automations action; workflows as tools/APIs.  
Out: a second scheduler; marketplace.  
OQ: OQ-21

## 4. Deferred G-row parts and unplanned seams

All 90 G-rows have an owning feature. These sub-parts are deferred:

| Deferred | Reason |
|---|---|
| G-37 (push part) | Web Push, APNs and FCM are post-M4 (TLD-09; upstream issue #1751); the in-app Inbox (GTE-02) and webhook connector (GTE-03) cover M2-M4. |
| G-42 (LLM translation) | Engine-owned translator session for done-when is post-M4 (TLD-19); v1 is the detected-command picker (EVD-03, WEB-04). |
| G-48 (free-text rules) | Free-text LLM rule translation is post-M4 (TLD-19); v1 is the typed catalog (RUL-03). |
| G-65 (full amendments) | 'Apply to this run' with mapping validation is post-M4 (TLD-18); ENG-10 ships cancel-and-restart-from-node. |
| G-66 (exhaustive mode) | Exhaustive enumeration (V11) is replaced by block-structure validation and scripted Simulate (X-25, R-24); revisit as a sampling check post-M4. |
| G-87 (claude-sdk fake) | No claude-sdk fake exists; a credentialed live bench (HRN-01) and a mock base URL lane if SPK-02 confirms it. |

Seams not planned (all other S-ids, including S1b, S6a/b, S39b-e and S40b, have exactly one owner in §3):

| Seam | Reason |
|---|---|
| S17 | claude-sdk sub-agent attribution: no vendor sub-agents are exposed to run sessions (S63 guard); revisit only if that changes. |
| S21 | claude-sdk PreToolUse hook: needed only if SPK-02 shows can_use_tool is skipped under auto/bypass; then it joins RUL-04. |
| S33 | Upstream Feature enum flag: replaced by the Coral-owned /v1/coral/info gate (TLD-03, R-21). |
| S35 | Watch-set union for top-level run sessions: only under the topology fallback; costed as the SES-03 contingency (TLD-02). |
| S44 | Shared turn-outcome classifier: optional; reconsider when codex-native lands if per-mode rules diverge. |
| S47 | Child-capable continue-in-fork: refresh is a slot restart (TLD-13, R-8). |
| S48 | hold_started callback: polling runner_last_seen suffices (SES-05). |
| S55 | Caller-supplied id through HTTP create: the facade creates through the store directly (X-6). |
| S73 | Skip worktree cleanup on session delete: run sessions carry workspace= and no git options, so upstream cleanup never fires (WSP-02). |

Assigned but conditional: S51 (SES-03) only if SPK-01 confirms children; S65 (EXT-02) only if the DENY policy is rejected; S66 (PRF-03) optional; S3 (HRN-03) native `terminal_launch_args` only.

## 5. Milestones: proving journeys and exit criteria

### M1 Foundational Coral (PH0 + PH1)
**Proving journey.** A developer runs the fork with `server_plugins: [coral.server_plugin]` and sees the Coral skin and nav with empty states behind the `/v1/coral/info` gate. Through API or CLI only, they upload the MVP template, validate a broken copy (problems carry `yaml_path` ranges), freeze a version, and simulate "changes requested ×3 → at-limit gate → approve" and "approved → gate reject". Both traces are deterministic, show a session-count estimate, and re-run green as saved cases on a new version.

**Exit criteria.**
1. `coral` package ships in the wheel; the import-boundary lint and the `coral` CI group are green (FND-01).
2. The Coral Alembic env reaches head after Omnigent on SQLite and Postgres. CockroachDB and MySQL lanes are green. Truncation keeps both version tables (FND-03, DUR-01).
3. The plugin mounts `/v1/coral/*`, and a plugin import failure is fatal. The web gate reads `/v1/coral/info`; the upstream Feature enum is untouched (FND-02, API-02, BRD-02).
4. `coral-fork-guard` is a required check, and every upstream path is ledgered and anchored. The daily `nightly^1` rehearsal is green (OPS-01, OPS-02).
5. Brand skin and nav shell are live; CSS contract tests are rebaselined (BRD-01, BRD-02).
6. Validator V1-V7 and V10-V13 pass. Reducer invariants I1-I8 hold under seeded fuzz in PR CI. The Simulate API works with saved cases (ENG-02..06, FND-04).
7. K1-K18 are published at v1 with owners and contract tests, except K13 frames and K15, which are at draft. ADRs are signed for topology (SPK-01) and SPK-03.

### M2 Functional stateful workflow (PH2)
**Proving journey.** "Implement with review loop" (TLD-01) on a local git repo with a claude-sdk API key:
1. The user picks the template, confirms the detected test, lint and format commands, and starts the run. Preflight passes and the estimate is shown.
2. The implementer edits in `coral/r-<run>/base`. Done-when rejects its first handoff with the missing items and accepts it after the commands pass.
3. Two read-only reviewers on different models submit findings.
4. The orchestrator calls `coral_choose_arrow("changes requested")` and the loop runs again.
5. The server is SIGTERMed mid-step and restarted. The run resumes with no duplicate sessions.
6. The reviewers approve, and the human gate appears in the Inbox (with the "app must be open" notice). The user approves it there, and the run ends with the branch kept.

**Exit criteria.**
1. The journey passes live (credentialed claude-sdk) and as Tier B E2E-1 and E2E-2 with a mock LLM.
2. `fold(log) == state` holds after real commits. A crash at every commit boundary recovers on all DB lanes (DUR-05).
3. The orchestrator decides only through engine tools. Illegal labels are rejected with the allowed values, and three rejected calls pause the slot (TLS-02, TLS-03, ENG-07).
4. Loop limit 3 is enforced, and at_limit routes to the gate in a scripted run (ENG-04).
5. Pause, resume, cancel and retry step work from the run view and the API. Cancel runs interrupt → stop → `omnigent.closed`, and late submits are rejected. Retry resets the worktree (ENG-07, API-03, SES-04, WSP-02).
6. The run view shows a live overlay. Reconnecting with `Last-Event-ID` loses no entries (API-03, WEB-05).
7. The gate is answerable from the Inbox, the run view and `/approve`, and is re-published after a restart (GTE-01, GTE-02).
8. Done-when uses claude-sdk exit codes and L1 fingerprints. S71 has landed and the runner-path exit-status test is green (EVD-02, WSP-01).
9. Run sessions refuse subscription OAuth on claude-sdk, reviewers are read-only by sandbox, and engine rows are hidden from pickers (HRN-02, PRF-02).
10. Drift is detected and the run pauses: a deleted policy or an archived step session (SES-05).

### M3 Functional agent profile system (PH3)
**Proving journey.** The user makes a profile from a custom agent in the Agent Profiles desk and pins it in a workflow; editing the agent leaves the version pinned and drift is reported at slot start. They add a Required rule (protect `infra/**`) and a Guidance rule from the catalog, and the guarantees panel shows Enforced for claude-sdk. Switching the implementer to claude-native (subscription) changes the labels honestly; the run executes under fail-closed hooks, and a blackholed policy endpoint blocks the tool call.

**Exit criteria.**
1. Profile revisions are immutable. Reinstall creates a new revision, and pins hold (PRF-03).
2. Capabilities are exposed per spelling. The four labels are computed per mode. V9 rejects Required rules that the chosen mode cannot enforce (HRN-01, RUL-02).
3. Catalog rules compile to guardrails or policies, with confirmation (RUL-03, WEB-07).
4. A claude-native step runs under fail-closed hooks; E2E-3 and E2E-4 are green (RUL-04, HRN-03).
5. Read-only is Verified, not Enforced, for non-claude-sdk reviewers (RUL-02).
6. The desk and picker show capability chips (WEB-06).

### M4 Integrated production-ready Coral (PH4 + PH5)
**Proving journey.** The PR-review loop showcase, edited on the canvas: repeat-for-each over labelled PRs ("3 of N"), parallel reviewers including codex-native, a writer per PR in its own worktree with serial merges and mandatory Coral-run checks in a detached checkout, and L2 fingerprints via the host channel. During the run: a budget pause the user raises, an unattended gate delivered by webhook, take-over and hand-back on one step, an orchestrator refresh, and a cancel-and-restart from a node with carried handoffs.

**Exit criteria.**
1. Trust: the host op channel, L2 and Coral-run checks with integrity diff are in place, and the evaluator is unchanged across the adapter swap (WSP-03, EVD-04).
2. Structure: E2E-5 is green, and multi-writer merges always run post-merge checks (ENG-08, ENG-09, WSP-04, TLS-04).
3. Canvas editing and the outline round-trip comments, with no YAML diff noise (WEB-08, WEB-09).
4. Budgets, refresh, take-over, the webhook connector, amendments-lite, both Codex modes and retention purge all work (RUL-05, SES-06, SES-07, GTE-03, ENG-10, HRN-04, HRN-05, DUR-07).
5. Operations: four DB lanes green; load scenario meets the OQ-1 NFRs; no open high security findings; at least one real upstream merge through the rehearsal; counsel licensing sign-off; the desktop build updates from the Coral feed (OPS-04, BRD-03).

### post-M4 (PH6)
No milestone exit. Features: WSP-05, EXT-01..05. Deferred: push (G-37), LLM translation (G-42, G-48), full amendments (G-65), exhaustive Simulate (G-66).

## 6. Critical path

Durations are in engineer-weeks from PH0 start, assuming one owner per feature and the TLD defaults hold.

**To M1 (about 12-13 weeks): the engine chain.**
FND-01 (wk 0-1) → ENG-01 (wk 1-3) → ENG-04 reducer (wk 3-9) → ENG-05 gates (wk 9-11) → ENG-06 Simulate (wk 11-13), then wired by API-02.
In parallel and off-path:
- FND-03 → DUR-01 → DUR-02;
- OPS-01 → OPS-02;
- BRD-01 and BRD-02;
- ENG-02 → ENG-03.

**To M2 (about 18-20 weeks): the durability chain is critical.**
FND-01 → FND-03 (wk 1-3) → DUR-01 (wk 3-5) → DUR-04 queue (wk 5-10) → DUR-05 reconciler and faults (wk 10-14) → SES-05 recovery (wk 14-17) → M2 integration: E2E-1, E2E-2 and the live template run (wk 17-19).

Near-critical chains that must converge by about week 15:
- Sessions: SPK-01 and SES-01 (wk 0-2) → SES-03 facade (wk 2-7) → SES-04 turn loop (wk 10-14, gated by DUR-04).
- Tools: ENG-04 (wk 9) → TLS-02 (wk 9-12) → TLS-03 orchestrator (wk 12-16; also needs PRF-02, which runs wk 8-13 after DUR-06).
- Evidence: EVD-01 (PH1) → EVD-02 (wk 8-14), needing DUR-06 by about week 8 and WSP-02 (wk 8-13).
- Web: WEB-01 → WEB-05, needing API-03 (wk 9-13) for live data. WEB-04 needs EVD-03.

Schedule levers:
1. Make DUR-01's first PR the K5 protocol and queue tables, so DUR-04 starts while the rest of 0001 is in review.
2. Land the seam trains (SES-02, TLS-01) in PH1 so PH2 never waits on upstream review.
3. Run SPK-01 in week 1. A failed spike moves SES-03 to the fallback and adds 2-3 weeks to the sessions chain, which then becomes critical.

**To M3 (about 8-10 weeks after M2).**
HRN-01 (done in PH1-PH2) → RUL-04 fail-closed (wk 0-3) → HRN-03 claude-native (wk 3-8).
In parallel:
- RUL-01 → RUL-02 → RUL-03, then WEB-07;
- PRF-02 → PRF-03 → WEB-06.
OQ-28 and OQ-35 (legal) can stop HRN-03 without blocking the rest of M3.

**To M4 (about 16-20 weeks after M3).**
WSP-02 → WSP-03 host channel (L) → EVD-04 checks (L) → WSP-04 merges (L) → PR-review showcase → OPS-04 certification. This chain is the longest.

ENG-08 → ENG-09 and WEB-08 → WEB-09 run beside it. HRN-04 and HRN-05 depend on RUL-04 and the OQ-29 terms answer, which are the main non-engineering risk to the M4 date.
