# Coral roadmap: feature decomposition (risk-first, MVP-minimal)

Lens: adversarial reviewer. Repo `omnigent-ai/omnigent` at `2a9cbe2c2`; date 2026-11-11. Built on `investigation/gap_analysis.md` (G-, S-, X-, D-, OQ-ids and spikes 1-20) and the TLD-01..21 working decisions. Sources: D§ (Draft 4), DD§ (deep dive), UI§ (UI language). 85 features, 18 contracts. A script checks that every G-row and seam is covered or listed in part 4, and that no hard dependency points to a later phase or milestone.

## 1. Approach and key choices

**Method.** I worked from the failure modes and from what is expensive to change later. Each milestone is cut to the smallest feature set that proves its journey. Unknowns become four PH0 spikes with time boxes and costed fallbacks. Interfaces become 18 contracts, each frozen as code with a fake before its consumers start.

**Key choices**

1. **Contract sprint in PH0.** ENG-01 (K1-K3), SES-01 (K4-K7) and OPS-01 (K8) are done in weeks 0-3. PRF-01 publishes K14 as its first PR.
2. **Four spikes cover the 20 unknowns.**
   - SPK-02: topology (spikes 3, 14, 15).
   - SPK-03: harness behaviour (1, 2, 4-7, 12, 13, 16, 20).
   - SPK-04: workspace and evidence (8, 9, L1 fidelity, the S71 hazard).
   - Spikes 10, 11, 17, 18 and 19 are one-hour checks done first in FND-01, FND-02, BRD-01, PRF-01 and HRN-01.
3. **G-04 (an XL) is split.** ENG-04 is the reducer core and log (top of L, two engineers). ENG-05 is lifecycle and timers (M). The invariant harness lives in FND-04.
4. **M2 is small:** claude-sdk only, single writer, local host, in-app gates. Cut lines if it slips: `coral_ask_user` (TLS-03), then OPS-03.
5. **WorkspaceOps (K15) ships at M2 with a session-shell backend.** The M4 host channel (WSP-02) only swaps the backend, so evidence and restart code is not rewritten.
6. **OPS-04 owns the M2 exit.** No claude-sdk fake exists, so it runs E2E plus a credentialed nightly.

**Moves against the mandated placements**

| Item | From → to | Reason |
|---|---|---|
| Credential guard (HRN-01, S13) | M3 → M2 | It is TLD-07's MVP auth. Without S13, run sessions fall through to subscription OAuth (`workflow.py:1123-1400`). |
| claude-sdk reviewer `write_paths: []` (in PRF-01) | M3 → M2 | TLD-01 has read-only reviewers at M2, and `read_only_os` leaves the shell writable (R-23). Cross-mode labels stay at M3 (RUL-03). |
| Per-session cost backstop (RUL-01) | M4 → M2 | Cost amplification starts with the first unattended run (adv Q5). Run budgets stay at M4. |
| YAML editor (WEB-03) | M2 → M3 | Not in the M2 exit list. Keeps CST round-trip risk off the M2 path; upload and import cover M2. |
| Promise labels in the UI | M2 → M3 | Labels come from the M3 registry (TLD-11). Showing none at M2 cannot over-claim. |
| Headless codex (HRN-04) | M4 → post-M4 | codex-native covers Codex reviewers. Headless codex cannot gate its own tools until S20. |
| Sub-workflow kind, step budgets, exhaustive Simulate | → deferred | No M1-M4 journey needs them. |

**TLD soundness flags** (other TLDs are sound as planned)

- **TLD-10 holds only with a condition.**
  - **Mismatched digests.** Per-command L1 in the runner is porcelain plus size and mtime (`eng_workspace.md` §5.4). `/changes` is porcelain only (`resource_routes.py:1230-1245`). The two digests cannot be compared.
  - **Missed re-edits.** Porcelain alone misses a re-edit of a file that is already dirty, so "after the last change" could over-claim. EVD-02 must compute the submit-time digest with the same algorithm.
  - **Evidence ceiling.** The session shell runs in the agent's alterable environment with a 120 s default (`routes_resources.py:3257-3297`), so M2 evidence is "Verified (L1)" at most.
  - **Sandbox risk.** Sandboxed git in a linked worktree is UNVERIFIED (spike 8). SPK-04 owns the contingency.
- **TLD-01 and TLD-07 conflict with the M3 placements** of read-only enforcement and the credential guard. Both are resolved by the moves above.
- **TLD-02:** keep spike 15 even though `own_runner` reduces it, because the fallback shares runners.

**Retrofit-expensive items and where they land**

| Item | Where it lands |
|---|---|
| Scope keys on every input, effect, timer, table and log row | ENG-01 (K2), DUR-01 |
| Idempotency keys: derived ids, `stable_id` plus read-before-resend, deterministic policy, worktree and elicitation ids, operation-id dedup | ENG-01, SES-02, SES-03, RUL-01, WSP-01, GTE-01, TLS-01 |
| Generation fencing (`session_generation`) | ENG-01, DUR-01; checked by TLS-02, SES-04 |
| Migration ordering and a single Coral head | FND-03, DUR-02 |
| Import boundary | FND-01, plus SES-02 contract tests |
| Reserved EGM keys and `StartRun(from_node)` | ENG-01 |
| Seam discipline | OPS-01, from the first PR |

**Failure-mode ownership**

| Failure mode | Owner and mechanism |
|---|---|
| Server restart mid-effect; lost elicitation index | DUR-06 and GTE-01: re-lease, read-before-resend, re-publish; proved by E2E-2 |
| Lost or bypassed turn-end edge | SES-03 records edge facts durably; DUR-06 resync |
| Duplicate queue delivery | DUR-05: idempotency keys; dispatch-time re-validation |
| Duplicate or late handoff; zombie turn after restart | TLS-02: receipts, evaluating lease, generation check. TLS-01: operation-id dedup. SES-04: no restart during the 72 h hold |
| Stale read, version conflict, SQLITE_BUSY | DUR-04 re-runs the reducer on retry |
| Gate answer vs reminder vs cancel; reminder vs in-flight decision | GTE-01: CAS and visit token. TLS-03: re-check before reminding |
| Laptop-sleep timer storm | ENG-05 coalescing |
| Runner loss, host offline | SES-04, with WSP-01 salvage and reset |
| Drift (policy, archive, bundle); native `/clear` | SES-04; PRF-01 digest check; HRN-02 via S45 |
| Unattended prompt stalls a step | SES-02 `fire.py` preflight; PRF-01 denies vendor ask tools |
| Account revoked | DUR-05 writes `failed(auth_revoked)` as system |
| Reaper steals exit codes | WSP-01 (S71); WSP-02 contract test |
| Upstream churn | OPS-01, OPS-02; SES-02 contract tests |
| Cost amplification | ENG-03 V12; RUL-01; DUR-07 |
| Stream-slot deadlock; desktop auto-update into Omnigent | WEB-05 fallback; OPS-02 blocks desktop builds until BRD-02 |

**Hidden dependencies**

- M2 commits and resets run in the step's sandbox, but a linked worktree's git dir lies outside it (spike 8).
- The gate publish target is SPK-02's stable run session.
- The `submit_handoff` scan bound comes from MCP timeouts (spike 7).
- claude-sdk buffers mid-turn input (F33), so steering shows as queued.
- Parallel Coral migrations would split the head; DUR-02 owns the migration train.
- The agent pane must use `?agent=` (R-17).

## 2. Contract catalog

Each contract is code (types, schema or protocol) plus a doc under `docs/coral/contracts/`, with a fake or fixtures so consumers build against stubs. Changes after freeze are additive or go through the producer with consumer sign-off.

| K | Contract | Producer | Main consumers | What it fixes |
|---|---|---|---|---|
| K1 | Workflow schema and compiled IR | ENG-01 | ENG-02..06, DUR-03, EVD-01, WEB-01, WEB-03 | YAML keys, stable and reserved ids (incl. EGM keys), compiled graph, content hash, JSON Schema. |
| K2 | Reducer types | ENG-01 | ENG-04, ENG-05, DUR-01, DUR-04..06, TLS-02, GTE-01 | Inputs, effects with effect_key, ScopeKey, rejections, pause reasons, error taxonomy. |
| K3 | Run-log schema | ENG-01 | ENG-04, DUR-04, API-02, WEB-05, EXT-01 | Closed kinds, entry shape, seq, actor, idempotency key, fold invariant. |
| K4 | coral.omni facade protocol | SES-01 | SES-02..04, DUR-06, WSP-01, PRF-01 | Session create, dispatch, status and TurnFact, policies, gate publish, worktrees, profiles; plus a fake. |
| K5 | Engine tool schemas and result envelope | SES-01 | TLS-01, TLS-02, TLS-03, TLS-04, HRN-02, HRN-03 | Six TLD-20 tools, args, rejection codes, envelope, operation-id dedup. |
| K6 | Labels and reserved names | SES-01 | SES-02, PRF-01, RUL-01, GTE-02, WEB-05 | coral.* labels, coral__ agent prefix, coral. policy prefix. |
| K7 | Gate and question elicitation payload | SES-01 | GTE-01, GTE-02, TLS-03, WEB-05, DUR-07 | coral_gate_<visit> ids, label form, visit token, resolver identity. |
| K8 | Seam ledger schema | OPS-01 | all seam-owning features | Ledger fields, anchor format, budgets, commit prefix. |
| K9 | Server plugin interface | FND-02 | API-01, DUR-05, SES-03, TLS-01, RUL-01 | Config key, ROUTERS, LIFESPAN_HOOKS, ServerServices, ordering, failure rules. |
| K10 | Coral DB conventions and migration ordering | FND-03 | DUR-01, DUR-02, DUR-04, DUR-05 | CoralBase, types, derived ids, scope-key columns, ordering, single head. |
| K11 | Coral REST API, OpenAPI and TS client | API-01 | DUR-03, API-02, GTE-02, WEB-*, PRF-02 | /v1/coral/* routes, info gate, errors, TS types with drift test. |
| K12 | Run stream protocol | API-01 | API-02, WEB-05, WEB-09 | Snapshot, seq-numbered entries, Last-Event-ID, heartbeat. |
| K13 | Evidence-requirement IR | EVD-01 | EVD-02, EVD-03, EVD-04, TLS-02, RUL-03, EXT-06 | Commands, final-pass semantics, may-modify flags, exit-code sources, scope. |
| K14 | Per-step bundle format and params.coral | PRF-01 | SES-02, TLS-01, RUL-01, RUL-04, HRN-01, HRN-02, PRF-02 | params.coral, guardrails, stance, hygiene, auth refs, digest, revision ref. |
| K15 | WorkspaceOps interface | WSP-01 | EVD-02, SES-04, WSP-02 | Fingerprint, commit, salvage, reset, head with op_key; two backends. |
| K16 | Capability registry and promise-label rule | RUL-02 | RUL-03, RUL-04, PRF-02, WEB-06, HRN-02, HRN-03, HRN-04 | Per-mode capability fields and the label rule. |
| K17 | Rule-template catalog IR | RUL-04 | RUL-06, WEB-06, WEB-08, EXT-06 | Template, params, builtin, per-mode enforceability, Required/Guidance. |
| K18 | Host workspace-op wire frames | WSP-02 | EVD-04, WSP-03, WSP-04 | Frames, workspace_ops:1 token, ops, job journal, reaper guard. |

## 3. Feature list by phase

Format: id and name · workstream · phase→milestone · priority · size (S ≤ 1, M 1-3, L 3-6 eng-weeks) · enabler. "Hard" dependencies block start or merge. "Soft" ones are integrated through contracts or stubs. A phase is the start window. Some PH1 features finish at M2.

### PH0: decisions, contracts and spikes

**SPK-01 Decision record pack** · OPS · PH0→M1 · Critical · S · enabler  
Get signed decisions, or recorded defaults, for the product, legal and ops questions that gate M1 and M2, plus a minimum NFR list.  
Blocked by: OQ-1, OQ-3, OQ-4, OQ-12, OQ-13, OQ-17, OQ-18, OQ-28, OQ-30, OQ-31, OQ-49, OQ-50, OQ-51, OQ-53, OQ-54  
In: Requirements baseline and NFRs; gate, blocked-exit, step-ask and end-of-run semantics; claude-sdk auth with a written vendor answer; attribution and app ids; naming, merge owner, bench keys, dev DB, CODEOWNERS; sign-off on the TLDs and the moves in part 1. Out: OQ-29 and OQ-25 (before PH5); OQ-24 (before PH3).  

**SPK-02 Session topology spike** · INTEGRATION · PH0→M1 · Critical · S · enabler  
In 4 days, prove or reject option B (children of a stable run session on own_runner, plus S51) and record ADR-05 with the costed fallback.  
G: G-22 · Soft: SES-01 · K in: K4 · Blocked by: OQ-32, OQ-17  
In: Own-worktree child on own_runner runs in its cwd (spike 3); never-turning run session hosts children; S51 prototype; sidebar and Inbox visibility; runner-local impersonation (15); archived-session posts (14). Out: Building the fallback, costed only (+3-4 eng-weeks); facade code (SES-02).  

**SPK-03 Harness behaviour probes** · HARNESS · PH0→M1 · Critical · S · enabler  
Answer the claude-sdk unknowns that shape M2 in week 1, then the native and Codex unknowns in week 2, each with a recorded verdict.  
G: G-44 · Blocked by: OQ-51  
In: Week 1 claude-sdk spikes 1, 2, 4, 7, 16, 20 (S21 need, Agent/Task reach, mock base URL, MCP timeout for the handoff scan, idle watchdog, routing knob); week 2 native and Codex spikes 5, 6, 12, 13. Out: Bench code (RUL-02); fixes.  

**SPK-04 Workspace and evidence spike** · WORKSPACE · PH0→M1 · Critical · S · enabler  
Decide how M2 gets trustworthy fingerprints, commits and resets for a claude-sdk single writer without S40, and draft the op catalog.  
G: G-38, G-59 · Blocked by: OQ-39, OQ-44  
In: Sandboxed git add, commit and write-tree in a linked worktree (spike 8); /changes porcelain vs re-edits of dirty files; one L1 algorithm for per-command and submit time; session-shell timeout and exit codes; S71 hazard repro. Out: Spike 9 beyond a note; building the channel (WSP-02).  
*Contingency: if the session sandbox cannot commit or reset, pull a minimal WSP-02 (fingerprint, commit_all, salvage, reset_to) into PH2, about +3 eng-weeks on the WSP-01 chain.*

**ENG-01 Engine contract sprint** · ENGINE · PH0→M1 · Critical · M · enabler  
Freeze K1 (draft), K2 and K3 as type modules with fixtures so every track builds in parallel against them.  
G: G-01, G-03, G-04, G-05, G-25 · Soft: SPK-01 · K out: K1, K2, K3 · Blocked by: OQ-3, OQ-12, OQ-19  
In: ScopeKey everywhere (TLD-21); effect_key and idempotency-key library; session_generation; closed additive log kinds; pause reasons and error taxonomy; rejection codes; reserved StartRun(from_node) and EGM keys; K1 JSON Schema draft. Out: Loader, compiler and reducer logic; Physical table layout (DUR-01).  

**SES-01 Integration contract sprint** · INTEGRATION · PH0→M1 · Critical · M · enabler  
Freeze the coral.omni facade, engine-tool schemas, labels and elicitation payloads, with an in-memory fake facade for tests.  
G: G-18 · Soft: ENG-01, SPK-02 · K out: K4, K5, K6, K7 · K in: K2 · Blocked by: OQ-3, OQ-4, OQ-43, OQ-47  
In: K4 sessions, dispatch, TurnFact, policies, gates, worktrees, profiles; K5 six tools, envelope, rejection codes; K6 labels and prefixes; K7 gate ids, label form, visit token. Out: Implementations; Native launch channels.  

**OPS-01 Seam ledger and fork guard** · OPS · PH0→M1 · Critical · M · enabler  
Make every upstream-file edit visible and budgeted from the first Coral PR via the seam ledger, anchors and the fork guard.  
G: G-83 · K out: K8 · Blocked by: OQ-50, OQ-54  
In: upstream.yaml at nightly^1 and seams.yaml seeded with S1-S89; check_seams.py for roots, anchors, budgets, commit prefix, stale entries; MODIFICATIONS.md; one-line hot-file rule. Out: Rehearsal job (OPS-02); Upstreaming PRs (OPS-06).  

### PH1: foundations (to M1)

**FND-01 Coral package and import boundary** · PLATFORM · PH1→M1 · Critical · S · enabler  
Ship a top-level coral package in the same wheel with tooling roots and a test that only coral.omni and coral.db import Omnigent internals.  
G: G-12 · Seams: S29, S39, S39b, S39c, S39d, S39e, S76 · Soft: OPS-01, SPK-01 · Blocked by: OQ-53, OQ-54  
In: Package data; pyrefly, isort, coverage, lint roots, pre-commit, CODEOWNERS; coral CI group; just mod; import-name check (spike 10); coral/CLAUDE.md. Out: CLI wrapper (OPS-03); DB environment (FND-03).  

**FND-02 Server plugin seam** · PLATFORM · PH1→M1 · Critical · S · enabler  
Add a generic server_plugins seam so Coral mounts routers, lifespan workers, observers and tool handlers with no further app.py edits.  
G: G-17 · Seams: S32 · Hard: FND-01 · K out: K9  
In: ROUTERS, LIFESPAN_HOOKS, ServerServices; mount before the SPA; start after the scheduler, stop before the runner router; fatal import failure; CLI wiring; refuse workers under host sharding; lifespan merge check (spike 11). Out: Coral routes (API-01); Multi-replica plugin semantics.  

**FND-03 Coral DB environment and migration ordering** · PLATFORM · PH1→M1 · Critical · M · enabler  
Give Coral its own Alembic chain and CoralBase that always migrates after Omnigent reaches head, on SQLite, Postgres, CockroachDB and MySQL.  
G: G-13 · Seams: S30, S31, S57, S58 · Hard: FND-01 · K out: K10 · Blocked by: OQ-42  
In: CoralBase and types; coral_alembic_version; ensure_coral_schema with newer-build, D1 and CockroachDB guards; env.py filter; truncation keeps *alembic_version; deploy hook; single-head, round-trip, ordering tests. Out: Tables (DUR-01); create_all, which is never used.  

**FND-04 Coral test infrastructure** · OPS · PH1→M1 · High · M · enabler  
Provide the directories, fixtures and harnesses every Coral feature tests with, so failure-mode tests are cheap from the start.  
G: G-87 · Hard: FND-01, FND-03 · Blocked by: OQ-52  
In: Lane map and conftests; Coral SQLite template; I1-I8 invariant and seeded fuzz harness; commit-boundary fault and contention harness on all lanes; Tier B scaffolding with a mock-LLM step bundle. Out: The E2E journeys (OPS-04); Bench (RUL-02).  

**OPS-02 Fork CI hygiene, rehearsal and licence inventory** · OPS · PH1→M1 · High · M  
Rehearse upstream merges daily from nightly^1, disable risky inherited workflows, and check licences in CI.  
G: G-84, G-86 · Seams: S77 · Hard: OPS-01 · Soft: FND-04 · Blocked by: OQ-30, OQ-50  
In: Daily rehearsal with rerere and regenerated generated files, conflict report by seam; disable secret-using inherited workflows (R-19) and desktop builds until BRD-02; branch protection; NOTICE addendum; licence inventory (elkjs blocked). Out: Security cherry-pick lane and executed merge drill (OPS-06); Upstreaming PRs (OPS-06).  

**ENG-02 Workflow loader and compiler** · ENGINE · PH1→M1 · Critical · M  
Load authoring YAML with source marks and compile it to the frozen, content-hashed IR with derived join types, loop table and checked parts.  
G: G-01, G-03 · Hard: ENG-01, FND-01 · K in: K1 · Blocked by: OQ-19  
In: Pydantic authoring models; safe-load with marks and a yaml_path-to-range map; stable and reserved ids; derived AND-join vs merge of alternatives; loop table; JSON Schema export for the web. Out: Validation rules (ENG-03); Layout file.  

**ENG-03 Static validator** · ENGINE · PH1→M1 · High · M  
Report V1-V7 and V10-V13 problems with box-anchored explanations, including block-structure soundness and the V12 activation upper bound.  
G: G-02, G-03 · Hard: ENG-02 · Soft: RUL-02 · K in: K1 · Blocked by: OQ-9, OQ-19  
In: Graph and block-structure rules (X-25); back-arrow join exemption (D6); V10 on host harnesses; V12 bound as a cost backstop; invalid drafts savable, not runnable (OQ-9). Out: V8 (RUL-06); V9 (RUL-03); V11 exhaustive mode (deferred).  

**ENG-04 Reducer core and run log** · ENGINE · PH1→M1 · Critical · L  
Implement the pure transition() for step, decision, gate, join, loop and end, emitting log entries, keyed effects and rejections, with fold(log) == state.  
G: G-03, G-04, G-05 · Hard: ENG-01, ENG-02 · Soft: FND-04 · K in: K1, K2, K3 · Blocked by: OQ-12, OQ-19  
In: State machines for run, activation, slot, attempt, decision request, gate visit; join arrivals unique per (activation, arrow, scope); loop limits and at_limit; rejections never throw; fold and receipts; top of L, staff two engineers. Out: Lifecycle and timers (ENG-05); repeat and parallel execution (ENG-07).  

**ENG-05 Run lifecycle, timers and pauses** · ENGINE · PH1→M1 · Critical · M  
Add start, pause, resume, cancel and retry-step commands, pause reasons and timer semantics to the reducer.  
G: G-06, G-07 · Hard: ENG-04 · K in: K2, K3 · Blocked by: OQ-14  
In: start_key to run id; resume on pinned version; cancel chain and late-submit rejection; watchdog, rejected-call pause, overdue timers; coalescing after sleep; pause classes infra, plan_limit, auth, budget. Out: Effect execution (DUR-05, SES-*); Budget pause (DUR-07).  

**ENG-06 Simulate engine, API and MVP template** · ENGINE · PH1→M1 · High · M  
Run the reducer with stub effects over scripted scenarios via POST /v1/coral/simulate, and ship the MVP template with saved simulations.  
G: G-66, G-69 · Hard: ENG-04, API-01 · Soft: ENG-03, ENG-05, DUR-03 · K in: K1, K2, K11 · Blocked by: OQ-2, OQ-9  
In: Scripted labels, list lengths, pass/fail, gate answers; saved cases rerun per version; session estimate; the TLD-01 template as package data and golden fixture. Out: Exhaustive mode (deferred); PR-review showcase (ENG-07).  

**DUR-01 Core schema (coral_0001)** · PLATFORM · PH1→M1 · Critical · M · enabler  
Land the core Coral tables as one standalone migration with scope-key columns, derived-id keys and generation fencing.  
G: G-14 · Hard: FND-03, ENG-01 · K in: K2, K10 · Blocked by: OQ-34  
In: Workflows, versions, runs (CAS version, start_key), run specs, activations, join arrivals, handoffs, gate visits, timers, queue, run log, simulation cases, blob refs, slots with session_generation; models-match test. Out: M2 integration tables (DUR-02); Queue claim logic (DUR-05).  

**DUR-02 Integration schema (coral_0002) and migration train** · PLATFORM · PH1→M2 · High · S · enabler  
Land the M2 integration tables in one standalone migration and own the Coral migration train so parallel features never create two heads.  
G: G-14 · Hard: DUR-01 · K in: K10  
In: Session bindings, step agents, profile revisions and pins, alerts, repositories and patterns, command observations, questions; single-head CI check; later migrations queue through this owner. Out: Amendment and later tables, which their features add through the train; Store code of each table.  

**DUR-03 Workflow library** · PLATFORM · PH1→M1 · High · M  
Store workflows DB-canonically as drafts and immutable content-addressed versions, with API, CLI upload and repo import.  
G: G-15, G-68 · Hard: DUR-01, API-01, ENG-02 · Soft: OPS-03 · K in: K1, K11 · Blocked by: OQ-8, OQ-33  
In: Stores; drafts with ETag/412; artifact keys and blob ledger with caps; workflows, versions and validate endpoints; import via host fs_request read; CLI upload. Out: Repo export via S74 (EXT-03); Version diff UI (WEB-09).  

**API-01 Coral API skeleton and contracts** · PLATFORM · PH1→M1 · Critical · M · enabler  
Mount /v1/coral/* behind the info gate and publish the Coral OpenAPI, generated TS client and run-stream protocol.  
G: G-74, G-81 · Hard: FND-02 · K out: K11, K12 · K in: K9 · Blocked by: OQ-36, OQ-45  
In: GET /v1/coral/info gate with no Feature enum edit (TLD-03); auth reuse; OpenAPI drift test; TS types; K12 stream spec. Out: Endpoint bodies, owned by the feature slices; Upstream Feature enum edit (S33).  

**EVD-01 Evidence-requirement IR and evaluator** · WORKSPACE · PH1→M1 · High · M · enabler  
Define the evidence IR and a pure evaluator with final-pass-after-last-change semantics, so formatter-then-test ordering cannot livelock.  
G: G-40 · Hard: ENG-01 · K out: K13 · K in: K1 · Blocked by: OQ-10  
In: Required commands, may-modify flags for formatters, exit-code source rules, per-agent scope, missing-item messages; tests over temp git repos. Out: Collecting observations (EVD-02); Detection (EVD-03).  

**PRF-01 Profiles v0 and per-step bundles** · HARNESS · PH1→M2 · Critical · L  
Generate content-addressed per-step bundles from pinned profile revisions, hide them from pickers, and seed the MVP profiles.  
G: G-47, G-50, G-51, G-52 · Seams: S54 · Hard: DUR-02, SES-01 · Soft: SPK-03 · K out: K14 · K in: K4, K6 · Blocked by: OQ-37, OQ-48  
In: K14 first (params.coral, TLD-04); revisions with digest, pins, slot-start drift check (spike 18); seeded orchestrator, implementer, reviewer; deterministic tar; hygiene (no spawn, no vendor ask tools, auth by reference); guards in bundle guardrails (TLD-05); reviewer write_paths: []. Out: Desk and picker (PRF-02); rule templates (RUL-04).  

**BRD-01 Brand skin and navigation shell** · BRAND · PH1→M1 · High · L  
Apply the Coral brand and add /workflows and /profiles with desk headers and empty states, via one-line hot-file seams.  
G: G-78, G-79, G-80, G-81 · Seams: S34, S79, S80, S81, S82, S83, S84, S89 · Soft: API-01 · Blocked by: OQ-7, OQ-24, OQ-27, OQ-30  
In: Clay Score in the omni slot, scoped status remap, --font-display (TLD-16); marks, hero, favicon, onboarding assets; coralRoutes, nav, palette actions, empty states (spike 17); CoralPageHeader on four desks; baseline regeneration. Out: Native shells (BRD-02/03); repointing --font-heading.  

**WEB-01 Read-only diagram and Simulate UI** · WEB · PH1→M2 · High · L  
Render the compiled graph read-only with one overlay shared by Simulate and the run view, and ship the Simulate UI.  
G: G-67, G-71 · Hard: ENG-01 · Soft: ENG-06, API-01, BRD-01 · K in: K1, K11 · Blocked by: OQ-30  
In: Graph model from IR; one xyflow adapter folder; Note layout-only; dagre in a worker; pure layout tests; scenario editor, overlay, estimate, saved-test badges. Out: Editing (WEB-07); ELK.  

### PH2: stateful engine and first end-to-end run (to M2)

**DUR-04 Run store with CAS transitions** · PLATFORM · PH2→M2 · Critical · M  
Persist reducer transitions atomically with optimistic run versions, re-reading and re-running the reducer on conflict.  
G: G-07, G-14 · Hard: DUR-01, ENG-01 · Soft: ENG-04 · K in: K2, K3, K10  
In: start_key uniqueness; apply_transition writes state, log, effects and receipts in one short transaction; retry re-runs the reducer; contention and commit-boundary tests on all lanes. Out: Multi-replica; Queue and workers (DUR-05).  

**DUR-05 Durable work queue and workers** · PLATFORM · PH2→M2 · Critical · L  
Own an at-least-once queue for signals, timers and effects with leases and idempotency keys, run by plugin-lifespan workers.  
G: G-11, G-16, G-25 · Hard: DUR-01, FND-02 · Soft: DUR-04, ENG-05 · K in: K2, K9, K10 · Blocked by: OQ-34, OQ-42  
In: Layout chosen here (TLD-08); lock-and-recheck claims, StartupLease, renew, backoff; enqueue off the loop thread; dispatch-time re-validation; ambient scopes; failed(auth_revoked) as system; no PersistentTaskScheduler. Out: Multi-replica sharding; Retention (DUR-08).  

**DUR-06 Reconciler and restart recovery** · PLATFORM · PH2→M2 · Critical · M  
Make runs survive server restarts and lost edges by reconciling durable state with live session facts at startup and on a periodic resync.  
G: G-11 · Hard: DUR-04, DUR-05 · Soft: ENG-05, SES-03, GTE-01 · K in: K2, K4 · Blocked by: OQ-14  
In: Re-lease expired effects; read before resend; re-publish open gates; stale runner_last_seen marks slots suspect; periodic resync re-derives turn ends; alert on waiting-with-no-elicitation. Out: Runner-loss restart ladder (SES-04); Native ASK re-publish (HRN-02).  

**API-02 Runs API and run stream** · PLATFORM · PH2→M2 · Critical · L  
Expose run start, snapshot, lifecycle actions and preflight, and stream the run log as SSE with resume.  
G: G-07, G-74, G-75, G-76 · Hard: API-01, DUR-04 · Soft: DUR-05, ENG-05, HRN-01 · K in: K11, K12 · Blocked by: OQ-16  
In: Idempotent start; snapshot; pause, resume, cancel, retry; preflight (V10, auth, host online, estimate); SSE tail with seq, Last-Event-ID, heartbeat. Out: Gate answers (GTE-01); Budgets (DUR-07).  

**SES-02 Session facade: request-free create** · INTEGRATION · PH2→M2 · Critical · L  
Create run-owned sessions idempotently without an HTTP request, per the topology SPK-02 decides, guarded by facade contract tests.  
G: G-18, G-22, G-25 · Seams: S51 · Hard: SES-01, SPK-02, DUR-02 · Soft: PRF-01 · K in: K4, K6, K14 · Blocked by: OQ-17, OQ-32, OQ-47  
In: uuid5(effect_key) ids; validators, labels, policies before input, launch; stable run session with own_runner children and S51; workspace= without git options; unattended preflight; privates via the sessions facade; signature snapshots and HTTP-create row diff. Out: Fallback topology (contingency); native launch args.  

**SES-03 Turn signals: dispatch, edges and turn-end rule** · INTEGRATION · PH2→M2 · Critical · L  
Deliver engine messages and turn edges durably, and decide turn end per mode, claude-sdk first.  
G: G-19, G-20, G-21 · Seams: S1, S1b, S4, S41, S42, S43 · Hard: SES-01, FND-02 · Soft: DUR-05, SES-02 · K in: K4 · Blocked by: OQ-13, OQ-41  
In: S41/S42 dispatch with stable_id and read-before-resend; S1 observer registry, bypass notify, origin slugs; S43 turn_outcome; O(1) binding filter; turn-end predicate; nudge only engine-started turns; ignore archive idle edges. Out: Native and Codex edges (HRN-02, HRN-03); S44 shared classifier.  

**SES-04 Session failure handling** · INTEGRATION · PH2→M2 · High · L  
Handle runner loss, host-offline holds and run-owned session drift with pause, fencing, salvage and re-attach instead of silent restarts.  
G: G-23, G-24 · Hard: SES-02, DUR-06 · Soft: WSP-01, RUL-01 · K in: K4, K15 · Blocked by: OQ-17, OQ-46  
In: Liveness from runner_last_seen; wake via ensure_runner_connected; paused(infra) during the 72 h hold; restart = stop, bump generation, salvage, reset, new session; drift checks then re-attach or pause (TLD-12); gate-wait wake test. Out: Guards (EXT-04); native /clear (HRN-02).  

**TLS-01 Engine tool transport** · INTEGRATION · PH2→M2 · Critical · M  
Register Coral engine tools once through an extension provider and dispatch them to server handlers with operation-id dedup and provenance.  
G: G-26, G-27 · Seams: S7, S8, S10, S12, S49, S50 · Hard: SES-01, FND-02 · Soft: PRF-01 · K in: K5, K14 · Blocked by: OQ-43  
In: extensions.py provider reading params.coral feeds ToolManager, runner forward and headless instructions; ServerToolCall registry; provenance predicate; operation-id dedup; coral_ collision check. Out: Native relay and pre-approval sites (HRN-02, HRN-03); Per-decision schemas (R-11).  

**TLS-02 coral_submit_handoff** · INTEGRATION · PH2→M2 · Critical · M  
Accept or reject step handoffs with a bounded synchronous evidence scan, slot-state dedup and generation fencing.  
G: G-28 · Hard: TLS-01, DUR-04, ENG-04 · Soft: EVD-02, SPK-03 · K in: K2, K5, K13 · Blocked by: OQ-12  
In: Schema check, reducer, one short transaction; scan bound from spike 7; receipts and evaluating lease; rejected counter; reject stale generation or post-cancel submits; blocked routing; step stays open while steering is pending. Out: Coral-run checks (EVD-04); refresh_note handling (ENG-09).  

**TLS-03 Orchestrator** · INTEGRATION · PH2→M2 · Critical · L  
Let the orchestrator decide only through coral_choose_arrow, and ask through coral_ask_user, under a seeded claude-sdk profile with no OS tools.  
G: G-29, G-30, G-32, G-33 · Hard: TLS-01, ENG-04 · Soft: PRF-01, GTE-01, SES-03 · K in: K5, K7 · Blocked by: OQ-13, OQ-14  
In: Decision requests with legal labels and handoff collection (D9); server-validated label, reason, items; lazy creation; chat interleaving with mid-turn buffering; reminders re-check state; ask_user via the gate path (first cut). Out: message_agent, assign_agents, assign_task (TLS-04); Orchestrator refresh (ENG-09).  

**GTE-01 Durable gates as elicitations** · INTEGRATION · PH2→M2 · Critical · L  
Write gate visits before publishing, surface them as elicitations on the stable run session, and resolve them by CAS with authored labels.  
G: G-34, G-35 · Seams: S5, S6, S6a, S6b · Hard: SES-01, DUR-04, ENG-04 · Soft: SES-02, SPK-02 · K in: K2, K7 · Blocked by: OQ-3, OQ-4, OQ-5  
In: Visit token, CAS, answer endpoint, stale-visit rejection; reminders never auto-resolve; S5 observer list, S6a request-free publish, S6b verdict handlers with resolver identity; re-publish on startup and replacement; owner-only; ApprovalCard reused. Out: Delivery outside the app (GTE-03); Team approvers (EXT-04).  

**GTE-02 Workflow inbox and run notifications** · WEB · PH2→M2 · High · M  
Show gates, pauses and alerts in a workflow Inbox kind with server-side ack, and stop per-step notification noise.  
G: G-36 · Seams: S36, S37, S85 · Hard: API-01, GTE-01, DUR-02 · Soft: BRD-01 · K in: K7, K11 · Blocked by: OQ-6, OQ-24  
In: Alerts feed, inbox and ack endpoints; WorkflowInboxCard; sidebar count; suppress per-step turn-end notifications, keep elicitation ones; run notifications with deep links; app-must-be-open notice (TLD-09). Out: Webhook, email, push (GTE-03, GTE-04); localStorage read state.  

**EVD-02 claude-sdk evidence at handoff** · WORKSPACE · PH2→M2 · Critical · L  
Record claude-sdk command observations with exit codes and fingerprints, and evaluate done-when after the last change at handoff.  
G: G-38, G-39 · Seams: S68, S69 · Hard: EVD-01, SPK-04, WSP-01, DUR-02 · Soft: TLS-02 · K in: K13, K15 · Blocked by: OQ-10  
In: S68 claude-sdk site; S69 response-field transport; observations snapshot command, exit code, fingerprint; one L1 algorithm per command and at submit, never bare /changes porcelain; evidence.result rows; missing-item feedback. Out: L2 and native or Codex observations (WSP-02, HRN-02, HRN-03); Coral-run checks (EVD-04).  

**EVD-03 Command detection and done-when picker** · WORKSPACE · PH2→M2 · High · M  
Detect test, lint, format and typecheck commands from repo files and let authors confirm them into the workflow version.  
G: G-41, G-42 · Hard: EVD-01, DUR-02 · Soft: WSP-01, DUR-03 · K in: K13 · Blocked by: OQ-38  
In: Parsers for package.json, pyproject, justfile, Makefile, CI, pre-commit via host fs_request; per-repo patterns; confirm snapshots into the version (X-32); picker (TLD-19). Out: LLM translation (EXT-06); Coral-run checks (EVD-04).  

**WSP-01 Repo bindings and run worktree lifecycle** · WORKSPACE · PH2→M2 · Critical · L  
Own each run's worktree request-free, commit accepted handoffs, and salvage and reset on restart, behind the WorkspaceOps interface.  
G: G-58, G-59 · Seams: S71, S72 · Hard: SES-01, SPK-04, DUR-02 · K out: K15 · K in: K4 · Blocked by: OQ-18, OQ-39, OQ-44  
In: S71 first (may land in PH1); bindings; deterministic coral/r-<run>/base, adopted on retry; S72 head_commit; commit with trailers at accepted handoffs; salvage refs; reset and clean -fd; session-shell K15 backend; removal and disk cap. Out: Per-agent worktrees, merges, setup files (WSP-03); Host op channel (WSP-02).  

**RUL-01 coral.policies, run guard and cost backstop** · INTEGRATION · PH2→M2 · High · M  
Enforce rosters, orchestrator limits and paused or cancelled runs through Coral policies, and cap per-session cost before budgets exist.  
G: G-45, G-46, G-62 · Seams: S52 · Hard: FND-02, SES-01 · Soft: PRF-01 · K in: K6, K14 · Blocked by: OQ-15  
In: step_roster, orchestrator_guard, engine_tool_guard (internal_only); S52 provider on coral.run_id DENYs non-coral tools when paused or cancelled; deterministic cost_budget backstop on every run session. Out: Rule templates (RUL-04); Run budgets (DUR-07).  

**HRN-01 claude-sdk credential guard** · HARNESS · PH2→M2 · Critical · S  
Refuse subscription fallthrough and literal keys for run-owned claude-sdk sessions, and pin the account per run.  
G: G-54 · Seams: S13, S21, S63 · Hard: FND-01, SPK-01 · Soft: SPK-03 · K in: K14 · Blocked by: OQ-28  
In: Spawn-env flag and executor refusal; provider references only; operator bindings honoured; preflight from harness_accounts; no-vendor-workspace-tools contract test; S21 only if spike 1 fails. Out: claude-native subscription path (HRN-02); Codex auth (HRN-03).  
*Moved from M3 to M2: TLD-07 makes API-key or provider auth the MVP, and without S13 the executor falls through to subscription OAuth.*

**WEB-02 Workflows library and template gallery** · WEB · PH2→M2 · High · M  
List workflows and templates and create a workflow from the MVP template.  
G: G-68, G-69 · Hard: BRD-01, DUR-03 · Soft: ENG-06, WEB-01 · K in: K11 · Blocked by: OQ-8  
In: /workflows list with versions and last run; gallery tab and Use template with defaults; read-only diagram of the latest version; upload and import actions. Out: In-app YAML editing (WEB-03); Canvas (WEB-07).  

**WEB-03 YAML editor pane** · WEB · PH2→M3 · Medium · M  
Edit workflow YAML in-app with server-validator markers and comment-preserving saves.  
G: G-70, G-73 · Hard: WEB-02, DUR-03 · K in: K1, K11 · Blocked by: OQ-9, OQ-33  
In: monacoSetup helpers plus the yaml npm CST (TLD-15); markers and problem list from the server validator; 412 conflict dialog; golden round-trip fixtures. Out: Canvas sync (WEB-07); Standalone file editor reuse (MonacoCodeEditor).  
*Moved from M2 to M3: not in the M2 exit list; its round-trip risk would sit on the M2 web path; upload and import cover M2 authoring.*

**WEB-04 Start-run dialog and done-when confirmation** · WEB · PH2→M2 · High · M  
Start a run with workspace, version, request and confirmed done-when commands after a preflight.  
G: G-42, G-73, G-76 · Hard: WEB-02, API-02 · Soft: EVD-03, HRN-01 · K in: K11 · Blocked by: OQ-16, OQ-18  
In: Host, repo, base pickers (reuse); detected-command picker and confirmation sheet; preflight errors; estimate; idempotent start. Out: Budget entry (DUR-07); Profile picker (PRF-02).  

**WEB-05 Runs list and live run view** · WEB · PH2→M2 · Critical · L  
Show runs and a live run view with overlay, inspectors, evidence, gates, agent panes, pause banners and lifecycle controls.  
G: G-75, G-77 · Hard: WEB-01, API-02 · Soft: GTE-01, SES-02, WEB-04 · K in: K7, K11, K12 · Blocked by: OQ-17, OQ-23  
In: Stream client with slot acquisition and polling fallback; overlay, loop counter, open gates; inspectors; evidence list; timeline; SubagentTabPane via ?agent=; steering shows queued input; pause banners; lifecycle controls. Out: Why-not arrows, take-over, stitched orchestrator (WEB-09); Promise labels (WEB-06).  

**OPS-03 Distribution identity and coexistence** · OPS · PH2→M2 · Medium · S  
Ship a coral console script with its own data and config dirs and update identity so Coral and Omnigent coexist.  
G: G-85 · Seams: S75 · Hard: FND-01, SPK-01 · Blocked by: OQ-49, OQ-53  
In: Wrapper sets OMNIGENT_DATA_DIR and OMNIGENT_CONFIG_HOME to ~/.coral; update check disabled or pointed at Coral; coral/version.py; isolation test. Out: Desktop identity (BRD-02); Renaming internal omnigent modules.  
*Cut line: can slip to PH5 if M2 stays internal.*

**OPS-04 M2 end-to-end acceptance lane** · OPS · PH2→M2 · Critical · M  
Prove the M2 journey and its failure modes end to end in CI and on a credentialed claude-sdk lane.  
G: G-87 · Hard: FND-04, TLS-02, TLS-03, GTE-01, DUR-06, SES-04, EVD-02, WSP-01 · Soft: WEB-05, SPK-03 · Blocked by: OQ-51  
In: E2E-1 and E2E-2 (SIGTERM between brief and handoff); runner-kill and at-limit scenarios; nightly credentialed claude-sdk run; mock base-URL lane if spike 4 passes. Out: Native E2E (HRN-02, RUL-05); Browser E2E.  

### PH3: profiles, capabilities and enforcement (to M3)

**RUL-02 Capability registry and bench** · HARNESS · PH3→M3 · High · M · enabler  
Fill capability fields for each mode, expose them per spelling, and back them with offline probes and a nightly live bench.  
G: G-44 · Seams: S22, S23, S59, S78 · Hard: FND-01 · Soft: SPK-03 · K out: K16 · Blocked by: OQ-51  
In: Existing plus ten new fields; guard tests; capabilities_by_spelling incl. native; probes with offline verdicts; feature-map rows; nightly bench; effective-enforceability computation. Out: Codex values beyond declared ones (HRN-03); Codex live lanes until HRN-03.  
*No hard deps: can start in PH1 if staffed.*

**RUL-03 Promise labels and read-only verification** · ENGINE · PH3→M3 · High · M  
Compute the four promise labels per checked part and mode without over-claiming, and verify read-only steps by fingerprint where not enforced.  
G: G-47, G-73 · Hard: RUL-02, ENG-03, EVD-02 · K in: K1, K13, K16 · Blocked by: OQ-24  
In: V9; label API; property test that unknown capability never yields Enforced; read-only Verified by before/after fingerprints off claude-sdk (R-23). Out: Panel UI (WEB-06); Rule catalog (RUL-04).  

**RUL-04 Rule-template catalog** · INTEGRATION · PH3→M3 · High · M  
Offer a typed catalog of Required and Guidance rules compiled to existing builtins and placed in bundle guardrails.  
G: G-48 · Hard: RUL-01, RUL-02, ENG-03 · Soft: PRF-01 · K out: K17 · K in: K14, K16 · Blocked by: OQ-38  
In: About 8 templates (worktree_guard, blast_radius, mode-aware egress, CEL ask-before-path, ...); per-mode enforceability; unenforceable Required fails validation; compiled into bundles. Out: Reactions and V8 (RUL-06); Free-text translation (EXT-06).  

**RUL-05 Native fail-closed hooks** · HARNESS · PH3→M3 · High · M  
Make native policy hooks fail closed for run-owned sessions and carry sub-agent identity, the prerequisite for any native Enforced label.  
G: G-49 · Seams: S14, S16 · Hard: SPK-03 · Soft: RUL-02 · Blocked by: OQ-46  
In: Fail-closed output; early returns deny; onFailure: block; PreToolUse timeout; policy_failure_mode; hooks-installed check; CLI version gating; E2E-4. Out: S15 Codex refusal (HRN-03); Hook UI.  

**HRN-02 claude-native step mode** · HARNESS · PH3→M3 · High · L  
Run claude-native steps for subscription users behind fail-closed hooks, with native turn ends, /clear following and plan-limit pauses.  
G: G-24, G-26, G-39, G-55, G-57 · Seams: S9, S11, S12, S24, S45, S64, S68 · Hard: RUL-05, TLS-01, SES-03, PRF-01, SPK-01 · Soft: EVD-02, RUL-02 · K in: K5, K14, K16 · Blocked by: OQ-28, OQ-35, OQ-46  
In: Native relay and pre-approval; launch framework text; Stop-hook turn end; S45 follows /clear and re-attaches policies; PostToolUse hints; provider egress hosts; plan-limit pauses with reset time; E2E-3; steps only. Out: Codex modes (HRN-03, HRN-04); claude-native orchestrator.  

**PRF-02 Agent Profiles desk and picker** · WEB · PH3→M3 · High · M  
Manage profiles as a lens over custom agents, with a picker that shows capability chips, 'used by' and source.  
G: G-53 · Seams: S66 · Hard: PRF-01, RUL-02, BRD-01 · K in: K11, K14, K16 · Blocked by: OQ-27, OQ-37  
In: /profiles desk; /v1/coral/profiles; cmdk picker in template and start dialogs; edits by reinstall create new revisions; chips say 'Claude'. Out: Sharing profiles (EXT-03, EXT-04); Editing params via PATCH.  

**WEB-06 Rules and guarantees UX** · WEB · PH3→M3 · High · M  
Let authors pick rules from the catalog and see 'What Coral guarantees' with the four promise labels.  
G: G-48, G-73 · Hard: RUL-03, RUL-04, WEB-02 · Soft: WEB-03 · K in: K16, K17 · Blocked by: OQ-24  
In: Rule picker with Required vs Guidance and per-mode labels; guarantees panel; translation status chips; on-box markers. Out: Canvas inspectors (WEB-08); LLM translation (EXT-06).  

### PH4: trust and structure (to M4)

**WSP-02 Host workspace-op channel and L2 fingerprints** · WORKSPACE · PH4→M4 · High · L · enabler  
Add a reaper-guarded host op channel for sessionless workspace work, switch WorkspaceOps to it, and make L2 the authoritative fingerprint.  
G: G-38, G-59 · Seams: S40, S40b · Hard: WSP-01, SPK-04 · K out: K18 · K in: K15 · Blocked by: OQ-44  
In: Frames, workspace_ops:1 token, reaper-guarded dispatcher, proxy, pending map, job journal; op registry; probe, head, fingerprint L1/L2, diff_paths, commit_all, salvage, reset_to, branch; exit-status contract test. Out: exec jobs (EVD-04); merges (WSP-03); fetch and push (WSP-04).  

**EVD-04 Coral-run checks and verifier pattern** · WORKSPACE · PH4→M4 · High · L  
Run pinned checks in a Coral-controlled checkout and feed the results back into attempts.  
G: G-43 · Seams: S72 · Hard: WSP-02, EVD-02, EVD-03 · K in: K13, K18 · Blocked by: OQ-44  
In: Sandboxed exec jobs with caps; detached checkout (S72); JUnit capture; integrity diff; check-to-attempt loop; verifier as a read-only step. Out: Hidden held-out tests; Multi-writer merges (WSP-03).  

**WSP-03 Per-agent worktrees and serial merges** · WORKSPACE · PH4→M4 · Medium · L  
Give each writer its own worktree, merge serially, and resolve conflicts in the agent's worktree with post-merge checks.  
G: G-58, G-60 · Hard: WSP-02, ENG-07, EVD-04, TLS-04 · K in: K18 · Blocked by: OQ-40  
In: Merge and abort ops; conflict sub-state resolved via assign_task; mandatory post-merge checks (D8); submodule and LFS probe; per-worktree setup. Out: Sandboxes (WSP-04); Parallel code changes without checks.  

**ENG-07 Repeat-for-each and parallel regions** · ENGINE · PH4→M4 · High · L  
Execute repeat-for-each and parallel split and join with region cancel, and ship the PR-review showcase template.  
G: G-08, G-09 · Hard: ENG-04, ENG-05, DUR-04 · Soft: WEB-09 · K in: K1, K2 · Blocked by: OQ-2, OQ-19  
In: Order, empty list, per-item failure, concurrency, per-item gates and batching, progress; AND-joins; region cancel; E2E-5; PR-review showcase (TLD-01). Out: Groups (ENG-08); Multi-writer merges (WSP-03).  

**ENG-08 Groups, saved blocks and Wait** · ENGINE · PH4→M4 · Medium · M  
Support groups and saved blocks as rule containers, and the hidden Wait kind.  
G: G-10 · Hard: ENG-03, ENG-04 · Soft: ENG-07 · K in: K1, K2 · Blocked by: OQ-19  
In: Group IR with entry and exit; saved blocks; Wait timers. Out: Sub-workflow kind (deferred); V8 (RUL-06).  

**ENG-09 Slot control: take-over and refresh** · ENGINE · PH4→M4 · Medium · L  
Let users take over and hand back a step, and refresh long sessions by slot restart.  
G: G-63, G-64 · Seams: S25, S27 · Hard: ENG-05, SES-04, SES-02 · Soft: WSP-02, HRN-02 · K in: K2, K4 · Blocked by: OQ-11  
In: taken_over(by); stable_id attribution; hand-back re-fingerprints and re-evaluates; per-mode refresh threshold, note, new session, notice; S25 literal; S27 retest. Out: Fork-based refresh (S47, not planned); Take-over on native panes beyond stable_id.  

**TLS-04 Team tools** · INTEGRATION · PH4→M4 · Medium · M  
Add coral_message_agent, coral_assign_agents and coral_assign_task for multi-agent and parallel steps.  
G: G-31 · Hard: TLS-03, ENG-07 · K in: K5  
In: Engine-routed messages with isolation flags and rate limit; 'up to' rosters; re-tasking for conflict resolution; steering-vs-closing race handling. Out: Elephant-Goldfish use (EXT-02); Cross-run messaging.  

**RUL-06 Reactions and group rule inheritance** · INTEGRATION · PH4→M4 · Medium · M  
Add timer and event reactions and V8 inner-stricter rule inheritance for groups.  
G: G-48 · Hard: RUL-04, ENG-08 · K in: K17 · Blocked by: OQ-38  
In: Reaction engine on timers and run events; V8; validator labels. Out: Free-text translation (EXT-06); Group UI (WEB-08).  

**GTE-03 External notification connector** · INTEGRATION · PH4→M4 · High · M  
Deliver unattended gates and pauses outside the app, webhook first, then email or Slack DM.  
G: G-37 · Hard: GTE-01, DUR-05 · Soft: GTE-02 · Blocked by: OQ-6  
In: Outbox delivery idempotent per channel; per-user channel config; deep links without secrets. Out: Push (GTE-04, BRD-03); Email digests.  

**WEB-07 Canvas editing: intents and patches** · WEB · PH4→M4 · Medium · L  
Edit the workflow on the canvas, turning intents into comment-preserving YAML patches.  
G: G-72 · Hard: WEB-03, WEB-01 · K in: K1 · Blocked by: OQ-22  
In: Palette, connect, delete; CST patches preserving comments and confirmed translations; layout file keyed by stable ids; one undo stack shared with YAML. Out: Inspectors (WEB-08); Mobile editing.  

**WEB-08 Canvas inspectors and outline view** · WEB · PH4→M4 · Medium · L  
Add step, arrow, gate, decision and group inspectors and an accessible outline view.  
G: G-72 · Hard: WEB-07, PRF-02, WEB-06 · K in: K1, K16, K17 · Blocked by: OQ-22  
In: Inspector suite; profile picker in the step inspector; keyboard and screen-reader outline. Out: Mobile editing; Real-time co-editing.  

**WEB-09 Run view depth** · WEB · PH4→M4 · Medium · M  
Extend the run view for structure, take-over, refresh and versions.  
G: G-65, G-77 · Seams: S86 · Hard: WEB-05 · Soft: ENG-07, ENG-09, ENG-10 · K in: K12  
In: Why-taken and why-not arrows; repeat and parallel badges; take-over controls; stitched orchestrator segments; versions list and diff; 'Part of run' chip. Out: Run sharing (EXT-04); Mobile layouts (BRD-03).  

### PH5: production readiness (to M4)

**HRN-03 codex-native mode** · HARNESS · PH5→M4 · Medium · L  
Add codex-native as a step mode with fail-closed hooks, an explicit yolo stance and policy-resolved approvals.  
G: G-49, G-56, G-57 · Seams: S2, S11, S12, S15, S24, S62, S68 · Hard: RUL-05, RUL-02, TLS-01, SPK-03, SPK-01 · Soft: SES-03 · K in: K5, K16 · Blocked by: OQ-29  
In: turn_outcome edges (S2); refuse run-owned codex-native without hooks (S15); native engine-tool sites; Codex rate limits; adapter observations; probes. Out: Headless codex (HRN-04); Codex orchestrator.  

**DUR-07 Run budgets and estimate** · PLATFORM · PH5→M4 · High · M  
Pause runs at a budget with an elicitation to raise or stop, using a spend aggregator over all run sessions.  
G: G-62 · Hard: RUL-01, DUR-05, GTE-01 · Soft: ENG-06 · K in: K7 · Blocked by: OQ-15, OQ-16  
In: Spend aggregator; paused(budget); overshoot disclosure; tokens for plan users; estimate from Simulate and medians; budget in start dialog. Out: Step budgets (deferred); Hard spend caps at the provider.  

**ENG-10 Amendments-lite and version diff** · ENGINE · PH5→M4 · Medium · M  
Restart a run from node X on a newer version with carried handoffs, and diff versions.  
G: G-65 · Hard: ENG-05, DUR-03 · Soft: WEB-09 · K in: K2 · Blocked by: OQ-20  
In: StartRun(from_node, carried) reserved in K2; mapping validation; reason; link old and new runs. Out: Apply to this run (EXT-07); Counter carry-over (EXT-07).  

**DUR-08 Retention, purge and account lifecycle** · PLATFORM · PH5→M4 · Medium · M  
Purge runs in batches under a retention policy and carry or purge Coral rows on account changes.  
G: G-16 · Seams: S56 · Hard: DUR-04 · Soft: SPK-01 · Blocked by: OQ-25  
In: purge_run; blob GC from the ledger; S56 callbacks; identity-migration carry. Out: Export (post-M4); Legal hold.  

**OPS-05 Production hardening** · OPS · PH5→M4 · High · L  
Certify Coral for production with a security review, load and soak tests, and the DB-lane commitment.  
G: G-87 · Hard: OPS-04 · Soft: WSP-02, HRN-03 · Blocked by: OQ-42, OQ-43  
In: Threat review (tool provenance, native bridge bearer, runner-local impersonation, host-op token, bundle secrets); load and SQLite-contention tests; SQLite and Postgres committed, CockroachDB and MySQL tested. Out: Multi-replica; Multi-region.  

**OPS-06 Release readiness** · OPS · PH5→M4 · High · L  
Execute an upstream merge drill, upstream the generic seams, and close licensing for release.  
G: G-84, G-86 · Hard: OPS-01, OPS-02 · Soft: OPS-05 · Blocked by: OQ-30, OQ-31, OQ-50  
In: Merge drill with all lanes; security cherry-pick lane; playbook; upstream PRs for S1, S5, S6, S10, S32, S50, S52; counsel sign-off, DCO; packaging. Out: Marketplace; Store listings (BRD-03).  

**BRD-02 Desktop identity** · BRAND · PH5→M4 · High · M  
Rebrand the Electron app with its own app id, scheme and update feed, and add run deep links.  
G: G-82 · Seams: S38, S87, S88 · Hard: BRD-01, SPK-01 · Blocked by: OQ-31  
In: brand.js; productName, appId, coral:// scheme, publish.url; icons incl. Assets.car; CLI detection; run deep links. Out: Mobile (BRD-03); Store listings.  

### PH6: post-M4 extensions

All are WS-owned as listed, priority Low, milestone post-M4, not enablers.

| Id | Name · WS · size | Objective and scope | G · seams | Hard (soft) | Blocked by |
|---|---|---|---|---|---|
| EXT-01 | Improvement suggestions · ENGINE · L | Suggest workflow improvements from run logs without ever weakening evidence or gates. In: Analysis over K3 logs; proposal UX with YAML diffs. Out: Auto-apply; Weakening gates or evidence. | G-88 | ENG-04, API-02 | — |
| EXT-02 | Elephant-Goldfish template · ENGINE · M | Ship the Elephant-Goldfish showcase with persistent-across-loop sessions and scoped inputs. In: Slot rebinding for session: persistent_across_loop; input scoping via S65 and files.materialize; typed resolutions; ESCALATE to a gate. Out: Persona licensing beyond attribution; Elephant as the orchestrator (D4.2). | G-89, S65 | ENG-07, WSP-02, ENG-09 | — |
| EXT-03 | Git import and export · WORKSPACE · M | Import and export workflows, templates and profiles through git, including repo export of .coral files. In: S74 .coral/-confined write op with expected-hash precondition; import of templates and profiles. Out: Sync daemon; Profile marketplace. | G-68, G-90, S74 | DUR-03, WSP-02 | OQ-33 |
| EXT-04 | Run sharing, team approvers and protection guards · INTEGRATION · L | Share runs through engine-managed grants, let teams answer gates, and add reserved prefixes and mutation guards. In: Engine-managed grants; team approvers; S26, S46, S53 with an explicit /clear policy. Out: Org admin; Cross-org sharing. | G-24, G-90, S26, S46, S53 | GTE-01, SES-04 | OQ-4, OQ-46 |
| EXT-05 | Automations trigger and workflows as tools · PLATFORM · M | Start workflows from Automations and expose workflows as tools or APIs, without a second scheduler. In: 'Run workflow' Automations action; workflow-as-tool endpoint. Out: New scheduler; Triggers outside Automations. | G-90 | API-02 | OQ-21 |
| EXT-06 | LLM translation of rules and done-when · INTEGRATION · M | Translate plain-text rules and done-when into catalog templates and evidence IR, with confirmation. In: Engine-owned translator session; dry run; invalidation on edit; usage accounting. Out: Unconfirmed translations; Required rules with no template behind them. | G-42, G-48 | RUL-04, EVD-03, SES-02 | OQ-38 |
| EXT-07 | Full amendments · ENGINE · L | Apply a new version to a running run with mapping validation, counter carry-over and a run lock. In: Amendments table; simulate from current state; reason. Out: Amending finished runs; Rewriting past log entries. | G-65 | ENG-10 | OQ-20, OQ-4 |
| GTE-04 | Web Push notifications · WEB · L | Deliver gate and pause notifications through Web Push for web and desktop. In: VAPID keys; subscriptions; payloads without secrets. Out: APNs and FCM (BRD-03); Email digests. | G-37 | GTE-03 | — |
| HRN-04 | Headless codex mode · HARNESS · L | Add headless codex as a step mode once tool gating, read-only stance and hook trust fail closed. In: threadId routing; compaction; hooks.json PreToolUse gating; per-session native-tool switches; read-only fix; hook-trust fail-closed. Out: Codex orchestrator; codex-native work (HRN-03). *Moved from M4 to post-M4: codex-native already covers Codex reviewers at M4, and headless codex cannot gate tools until S20.* | G-56, S18, S19, S20, S60, S61, S67 | RUL-02, TLS-01 (HRN-03) | OQ-29 |
| WSP-04 | Managed sandbox runs · WORKSPACE · L | Run workflows in managed sandboxes with worktrees, a host-keyed keep-warm lease and checkpoint relaunch. In: Bind-mode worktrees; keep-warm lease; checkpoint pushes and relaunch. Out: Plain-folder shadow repos (deferred); Multi-host runs. | G-61, S28, S70 | WSP-02, SES-04 | OQ-5 |
| BRD-03 | Mobile shells: identity, deep links and push · BRAND · L | Rebrand the iOS and Android shells and add run deep links and native push for gates. In: Display names and icons; run deep links; APNs and FCM. Out: Mobile editing; Tablet-specific layouts. | G-37, G-82, S88 | BRD-02 (GTE-04) | OQ-23, OQ-31 |

## 4. Deferred G-rows and unplanned seams

Every G-01..G-90 row maps to at least one feature (checked by script). These parts of rows are not in M1-M4:

| Gap (part) | Reason |
|---|---|
| G-10 (sub-workflow kind) | Hidden kind with no M1-M4 journey; ENG-08 ships groups, blocks and Wait only. |
| G-11 (multi-replica) | v1 is single replica (TLD-08); FND-02 refuses to start workers when sharding is configured. |
| G-61 (plain-folder workspaces) | Git worktrees only until a non-code persona is confirmed (OQ-1). |
| G-62 (step budgets) | The run budget (DUR-07) and per-session backstop (RUL-01) cover cost amplification. |
| G-66 (exhaustive Simulate, V11) | Block-structure validation plus scripted Simulate first (X-25). |
| G-37 (push), G-42/G-48 (LLM translation), G-56 (headless codex), G-61 (sandboxes), G-65 (full amendments), G-68 (repo export), G-82 (mobile), G-24 (guards), G-88..G-90 | Covered by post-M4 features in PH6, not by M1-M4. |

Seams not planned (every other S-id, including S1b, S6a/b, S39b-e and S40b, is owned by the feature that lists it):

| Seam | Reason |
|---|---|
| S3 | Mostly not needed: the facade imports privates through the sessions facade. Only the native terminal_launch_args slice might be needed; HRN-02 pulls it in if so. |
| S17 | claude-sdk exposes no vendor sub-agents (S63 guard), so attribution is moot. |
| S33 | Replaced by the Coral-owned /v1/coral/info gate (TLD-03). |
| S35 | Not needed under option B; becomes WEB-05 scope only if SPK-02 picks the top-level fallback. |
| S44 | Optional shared classifier; the per-mode turn-end rule in SES-03 does not need it. |
| S47 | Refresh is a slot restart, not a fork (TLD-13). |
| S48 | Polling runner_last_seen in SES-04 suffices. |
| S55 | The facade creates sessions through the store with derived ids, not the HTTP create path. |
| S73 | Run sessions carry no git options, so session delete cannot remove Coral worktrees. |

## 5. Milestones: proving journeys and exit criteria

### M1 Foundational Coral

**Journey.** A developer runs the Coral build and sees the Coral skin with Workflows and Agent Profiles empty states. They upload the MVP template with the CLI and get validator results with YAML ranges. They freeze a version, then Simulate three scenarios through the API and save them as test cases: approved first pass; three "changes requested" ending at the at-limit gate; reject at the gate.

**Exit criteria.**

1. `coral/` ships in the wheel; the import-boundary test passes; Coral tests are green on all four DB lanes.
2. Coral migrates only after Omnigent head (ordering and single-head tests). `coral_0001` has scope keys and `session_generation`.
3. Plugin routes mount; disabled Coral means 404 and hidden nav; import failure stops startup.
4. The fork guard rejects an unledgered edit; the daily rehearsal reports conflicts.
5. Brand tokens, `--font-display` and marks land with CSS-contract updates.
6. I1-I8 (`fold(log) == state`) pass under seeded fuzz. Saved simulations rerun on each new version.
7. K1-K14 are published with fakes or fixtures. OQ-28 and OQ-32 are closed, and SPK-01 to SPK-04 are recorded.

### M2 Functional stateful workflow (MVP)

**Journey.** On a local git repo with an Anthropic API key, the user:

1. picks "Implement with review loop", confirms the detected commands and starts the run;
2. sees the implementer's first `coral_submit_handoff` rejected, because the tests predate its last edit, and accepted after a re-run;
3. watches two read-only reviewers report and the orchestrator choose "changes requested" with `coral_choose_arrow`, loop once, then choose "approved";
4. approves the gate from the Inbox. The run ends with a committed branch.

Faults injected during the journey: server SIGTERM between brief and handoff; killing the implementer's runner; forcing the loop to its limit of 3; pause, resume, cancel and retry.

**Exit criteria.**

1. E2E-1 and E2E-2 pass in CI. The credentialed claude-sdk nightly passes 5 runs in a row.
2. Commit-boundary faults on all lanes produce no duplicate sessions, briefs, policies, worktrees or gate prompts.
3. Late or duplicate submits get receipts or rejections, and stale gate answers are rejected. Runner kill leads to `paused(infra)`, then Resume with a salvage ref and a new generation. The at-limit route works.
4. The run view updates live over SSE, resumes with `Last-Event-ID` and falls back to polling. Evidence shows command, exit code and L1 per acceptance.
5. Drift (a deleted policy, an archived step session) pauses the run within one resync interval.
6. The credential guard holds. Run sessions have no vendor ask or spawn tools. A reviewer write is denied by the sandbox. The cost backstop is on every run session.
7. No promise labels are shown. The watchdog p95 is recorded (OQ-14).

### M3 Functional agent profile system

**Journey.** The user creates a profile from a custom agent, which pins a revision, and picks it for a reviewer, with capability chips shown. They add Required and Guidance rules from the catalog and read the per-mode labels. They run a claude-native implementer on a subscription: a blackholed policy endpoint blocks the tool, `/clear` is followed, and a plan limit pauses the run with a reset time. They edit YAML in the app and the comments are preserved.

**Exit criteria.**

1. E2E-3 and E2E-4 pass. The nightly bench covers claude-sdk and claude-native.
2. A property test over registry × catalog shows that an unknown capability never yields Enforced, and that an unenforceable Required rule fails validation.
3. Profile edits never change running runs. A digest mismatch at slot start pauses the run.
4. Native auth and egress paths are cleared against OQ-28 and OQ-35.

### M4 Integrated production-ready Coral

**Journey.** The PR-review showcase:

- repeat-for-each over labelled PRs, concurrency 2, with batched per-item gates;
- parallel claude-sdk and codex-native reviewers;
- a multi-writer fix with serial merges and post-merge Coral-run checks;
- a budget pause raised from its elicitation;
- take-over and hand-back, and an orchestrator refresh;
- a webhook alert for an unattended gate;
- restart from a node with carried handoffs;
- a canvas edit that round-trips comments.

**Exit criteria.**

1. L2 fingerprints and checks run over the host channel, and the exit-code reaper test passes. E2E-5 passes.
2. Load results are recorded. SQLite and Postgres are committed; CockroachDB and MySQL are tested.
3. The security review is closed. The merge drill is green on all lanes. Generic seams have upstream PRs.
4. Licences are signed off. The desktop build uses the Coral feed and app id. The retention purge runs.

### post-M4

No exit criteria: EXT-01 to EXT-07, GTE-04, HRN-04, WSP-04 and BRD-03, each gated by its open questions.

## 6. Critical path

I computed this from hard dependencies, weighting S, M and L as 1, 2.5 and 5 weeks. ENG-04 is weighted at 6 weeks.

**M1 (about 13-14 weeks):** ENG-01 → ENG-02 → ENG-04 → ENG-05 and ENG-06.

FND, DUR-01, DUR-03, API-01 and BRD-01 run beside it with slack. The schedule risk is ENG-04, so it gets two engineers from week 3.

**M2 (about 21-23 weeks):** the binding chain is durability, not the engine.

FND-01 → FND-03 → DUR-01 → DUR-05 (queue) → DUR-06 (reconciler) → SES-04 (failure handling) → OPS-04 (acceptance).

Three near-ties run within 2-4 weeks of it:

- Engine: ENG-01 → ENG-02 → ENG-04 → TLS-03 or GTE-01 → OPS-04.
- Workspace: FND-03 → DUR-01 → DUR-02 → WSP-01 → EVD-02 → OPS-04.
- Web: DUR-01 → DUR-04 → API-02 → WEB-05.

The integration chain SPK-02 → SES-02 (L) → SES-04 joins the binding chain at SES-04.

Levers to shorten it:

- Start FND-03 in week 1.
- Put two engineers on DUR-05.
- Build SES-03, TLS-01 and GTE-01 against the K4 fake, not the real queue.
- Land S71 in PH1.

Contingency costs:

- The topology fallback adds about 3-4 weeks to SES-02 and WEB-05.
- A failed SPK-04 moves a minimal WSP-02 onto the workspace chain, adding about 3 weeks. That would make the workspace chain the binding one.

**M3:** RUL-02 has no hard dependencies and should start in PH2 if staffed. The path is then RUL-02 → RUL-05 → HRN-02, with RUL-03 → WEB-06 (which needs EVD-02 from M2) beside it.

**M4:** WSP-01 → WSP-02 (host channel) → EVD-04 (checks) → WSP-03 (merges). WSP-03 also needs ENG-07 → TLS-04. OPS-05 and OPS-06 close it.

**Top schedule risks:**

- ENG-04 size;
- SES-02, a facade over privates in the 77-commit `orchestration.py`;
- the lack of a claude-sdk fake;
- OQ-28 (legal), which gates M2 auth.
