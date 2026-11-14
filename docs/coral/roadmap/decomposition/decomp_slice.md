# Coral roadmap: feature decomposition (Staff Product lens, vertical slices)

Repository `omnigent-ai/omnigent` at `2a9cbe2c2`. Date 2026-11-11. Built on `investigation/gap_analysis.md` (G-, S-, X-, D-, OQ-ids), `investigation/product.md` (PC-ids, journeys §2 (a)-(m), MVP §9.1) and the specialist files. 81 features: PH0 7, PH1 19, PH2 21, PH3 6, PH4 12, PH5 8, PH6 8.

## 1. Approach and key choices

**Lens.** Each feature ends in behaviour someone can see. Enablers exist only where they unblock parallel teams.

**Walking skeleton first (SES-05).** The thin path is: one-step workflow → real session → `coral_submit_handoff` → gate → answer → end, surviving a server kill. It is PH2's first integration target. Each feature it touches (ENG-04, DUR-02/03, SES-02, SES-03, TLS-01/02, GTE-01, WEB-06) ships a **skeleton slice** first. SES-05 owns the wiring, E2E-1/E2E-2 and a stub burn-down list.

**Contract-first.** PH0 has four contract packs (ENG-01, SES-01, API-01, EVD-01). With fixtures, a `FakeOmni` (K4) and an API mock (K6/K7), all teams start in parallel in PH1. K14 and K16 come from their PH1 owners; K15 and K17 come from the phase where their first consumers meet.

**UI surface ownership.** Each surface has one owner, which covers its loading, empty, error, paused and offline states. Later features plug in only through the owner's extension points (overlay layers, inspector tabs, inbox card renderers, banners). Owners: brand chrome BRD-01; nav, routes, Coral gate, desk header BRD-02; diagram and overlay API WEB-01; desk, library, intro, YAML pane, problems WEB-02; Simulate, guarantees panel, badges WEB-03; gallery, Use-template dialog, done-when picker WEB-04; start dialog, runs list WEB-05; run view (header, overlay, inspector, timeline, banners, stream states) WEB-06; sessions pane, steering, run chip WEB-07; gate card and ApprovePage mapping GTE-01; inbox kind and run notifications GTE-02; channel settings GTE-03; profiles desk and picker PRF-02; model-access settings HRN-03; rules panel RUL-03; canvas WEB-09; inspectors and outline WEB-10; stitched transcript and take-over controls SES-06; budget prompt DUR-05; versions and restart-from-node DUR-07; suggestions EXT-01.

**Seams.** The first feature that needs a seam owns it (index in §4). Every hot-file seam (S1, S3, S4, S6, S10, S14, S32, S34, S40, S41, S43, S46, S49, S52, S53, S62, S68, S71, S72, S80, S81, S87) is a one-line call into a registry module. Owners of the generic registries (S1, S5, S6, S10, S32, S50, S52) open upstream PRs.

**Milestone moves (defaults overridden, with reasons).**
- **S13 core credential guard: M3 → M2 (HRN-01).** TLD-07 requires S13 for the MVP. Without it, run-owned claude-sdk sessions can fall through to subscription OAuth (`claude_sdk_executor.py:2091-2118`; `runtime/workflow.py:1123-1400`), which is the OQ-28 terms risk. The full guard stays at M3 (HRN-03).
- **Read-only reviewers Enforced on claude-sdk: M3 → M2 (PRF-01).** The TLD-01 reviewers are read-only. Without `write_paths: []` in the bundle, TLD-11 forces their M2 label to Requested (`read_only_os` leaves shell open, `policies/builtins/orchestration.py:645-660`). The rule costs S. Per-mode labels stay at M3 (RUL-02).
- **Minimal cost guards in M2; run budgets at M4 (DUR-05).** M2 gets loop limits, an activation cap, a session estimate and a per-session `cost_budget` backstop with no soft ASK, because costs multiply once agents run unattended (adv Q5).
- **Plan-limit pause: M3 (HRN-03).** API-key users have no plan windows; subscription users arrive with claude-native.
- **Versions and diff: M4 (DUR-07),** with amendments-lite and export. **Mobile identity: post-M4 (GTE-04).** **Merge rehearsal: PH1 (OPS-01)** per TLD-17; M4 keeps the release drill (OPS-04).

**TLD flags (evidence-based; none re-litigated).**
- **TLD-10, S71 rationale.** Sound decision, imprecise reason. The host reaper corrupts returncodes of **host-owned** subprocesses (`host/connect.py:1417-1423`), and `fs_request`/`fs_write` bypass the guard (`:6027-6034`). MVP exit codes come from the runner (G-39), which this reaper does not touch. S71 really gates repo import, command detection and S40 ops, so it lands in PH1 inside DUR-01.
- **TLD-10 vs M2 "retry".** Retry must reset the worktree to the step's start commit (product §2(i)), but X-17 puts reset under S40 (M4). Plan: K10 is one `WorkspaceOps` interface with two backends. M2 uses the session shell (owner-only, runner, 120 s; `routes_resources.py:3257-3297`), proven by EVD-01; EVD-04 swaps in the host backend.
- **TLD-07 vs product MVP item 2.** Subscription-only users cannot run workflows until M3. Product signs off in SPK-03; HRN-01 ships honest preflight copy.
- **TLD-09 + TLD-02.** Gate publish on a turnless run session (`routes_events.py:2222-2257`) and its Inbox rendering are unverified. Added as SPK-01 probe (e).
- **TLD-11 vs M3 registry.** M2 labels use a static claude-sdk row in K8 shape; the full registry follows at M3.

**Merges (to stay at 81):** probes into one pack; simulate + guarantees; template + detection + picker; gate rows + elicitation; registry + bench + read-only labels; fail-closed hooks + claude-native; refresh + take-over. **XL kept:** only GTE-04 (post-M4 push), with a named split.

## 2. Contract catalog

| K | Name | Producer | Consumers | What it fixes |
|---|---|---|---|---|
| K1 | Workflow authoring schema + compiled IR (+JSON Schema) | ENG-01 | ENG-02/03/07/08/09, DUR-01, WEB-01/02/03/09, PRF-01, TLS-02 | YAML keys (incl. reserved EGM keys, hidden Wait/Sub-workflow), stable ids, node taxonomy (Note layout-only), derived fields, content-hash rule |
| K2 | Reducer I/O types | ENG-01 | ENG-04/05/08, DUR-02/03/04, SES-02, TLS-02, GTE-01 | Commands/observations, effects with `effect_key`, rejection codes, ScopeKey `(run,node,item_path,iteration_path)`, state and pause-reason enums |
| K3 | Run-log entry schema | ENG-01 | ENG-06, DUR-02, API-02, WEB-06/08, EXT-01 | Closed `kind` enum, actor, refs, 16 KiB body cap, `seq`, idempotency key |
| K4 | `coral.omni` facade protocol + FakeOmni | SES-01 | SES-02/03/04, DUR-03, GTE-01, WSP-01, PRF-01, EVD-02 | create/send/interrupt/stop/wake/status/items/turn facts, policies attach, gate publish, profiles resolve, worktrees; idempotency semantics |
| K5 | Evidence-requirement IR | EVD-01 | EVD-02/03/05/06, WEB-04, WEB-06 | Required commands, final-pass semantics, may-modify flags, exit-code source, per-agent scope, missing-item messages |
| K6 | Coral REST API (OpenAPI) | API-01 | API-02, DUR-01, ENG-07, GTE-01/02, PRF-02, WEB-*, BRD-02 | `/v1/coral/*` endpoints, error envelope, ETag/412, `start_key`, access mapping |
| K7 | Run stream protocol | API-01 | API-02, WEB-03/06/07/08 | SSE snapshot then entry patches, `seq` ids, `Last-Event-ID`, heartbeat, `[DONE]` |
| K8 | Capability registry + promise-label rules | SES-01 | WEB-03, RUL-02/03, PRF-02, HRN-02/03 | Field names per mode, effective enforceability, the four labels and their never-over-claim rules |
| K9 | Bundle format + `params.coral` schema | SES-01 | PRF-01, TLS-01/03, RUL-01/03, HRN-01/02 | Generated per-step bundle layout, content address, hygiene, guardrails slot, tool opt-in |
| K10 | WorkspaceOps interface + host frames | EVD-01 | WSP-01/02, EVD-02/04/05/06, SES-06, DUR-07, EXT-02 | Op catalog (status, L1/L2, commit, salvage, reset, exec, `.coral` write), session-shell and host backends, job events |
| K11 | Engine tool schemas + result envelope | SES-01 | TLS-01/02/03/04, PRF-01, HRN-02 | Six `coral_*` tools (TLD-20), fields, rejection codes, `{accepted, reason, allowed_values, next}` |
| K12 | Gate / question / budget elicitation payloads | SES-01 | GTE-01, TLS-03, DUR-05, WEB-06 | Stable ids `coral_gate_<visit>`, authored-outcome mapping, hidden decline/cancel, verdict handler |
| K13 | Labels, reserved names, stable ids | SES-01 | SES-02/03/04, GTE-02, PRF-01, WEB-07, EXT-03 | `coral.run_id/role/slot_id/...`, `coral__` agent prefix, `coral.` policy prefix, `stable_id` scheme |
| K14 | Coral DB conventions + migration contract | FND-01 | DUR-01/02/03/06, PRF-01, WSP-01, EVD-02, GTE-02 | CoralBase, `coral_alembic_version`, derived-id PKs, scope-key columns, enum codecs, caps, ordering after Omnigent |
| K15 | Rule-template catalog IR | RUL-03 | PRF-01 (guardrails), RUL-04, ENG-09 (V8), WEB-10, EXT-06 | Template id, params, target builtin, per-mode enforceability |
| K16 | Seam ledger schema | OPS-01 | every seam-owning feature | `.coral/seams.yaml` entries, `CORAL(Sx)` anchors, budgets, commit prefix |
| K17 | Alert / inbox feed model | GTE-02 | DUR-04, RUL-04, GTE-03, GTE-04 | `coral_alerts`, ack, actions, deep-link payload without secrets |

## 3. Features by phase

Entry format: **ID Name**, then `workstream · phase · milestone · priority · size · enabler · PC-ids`. Lines below each heading:

- **Obj:** objective.
- **Cov / Dep / K:** G-rows and seams covered; hard and soft dependencies; contracts produced (prod) and consumed (cons).
- **In / Out:** included and excluded scope.
- **OQ:** blocking open questions.

### PH0: Decisions, contracts and spikes

**SPK-01 Session topology spike and decision record**: WS-INTEGRATION · PH0 · M1 · Critical · S · enabler · PC-18
- Obj: Prove or refute option B (TLD-02) in 3 days, and record the ADR with the fallback costed as a contingency.
- Cov: G-22 (decision). Dep: soft SES-01. K: cons K4, K13.
- In: probes (a) a child with its own worktree runs tools in its cwd (claude-sdk); (b) a turnless anchor hosts children; (c) S51 stops parent wakes; (d) sidebar and Inbox; (e) a gate elicitation on the run session renders in Inbox and `/approve`. Out: facade code; S35 code.
- OQ: OQ-32, OQ-17.

**SPK-02 Runtime probe pack**: WS-HARNESS · PH0 · M1 · High · S · enabler
- Obj: Resolve the unverified items behind M2 designs in 4 days, with a go/no-go for each dependent feature.
- Cov: spikes 1, 2, 4, 7, 10, 11, 14-20. Decides S21. Dep: none.
- In:
  - claude-sdk: `can_use_tool` under auto/bypass; Agent/Task unreachable; mock `ANTHROPIC_BASE_URL` (Tier C lane).
  - Runtime: submit timeouts; idle watchdog vs long turns; runner-local impersonation; Smart Routing pin; archived-session posts.
  - Platform: `coral` name collision; lifespan merge; RR route fragments; blob retention; local CredentialStore.
- Out: probes 5, 6, 12, 13 (HRN-02/04); spike 8 (EVD-01); spike 9 (WSP-03).

**SPK-03 Decision records and sign-off pack**: WS-OPS · PH0 · M1 · Critical · S · enabler
- Obj: Record sign-off on TLD-01..21 (with the §1 flags) and on the answers that M1/M2 specs need.
- Cov: D2, R-2, R-20. Dep: none.
- In:
  - Requirements baseline: product.md §1, §7, §9.
  - Semantics: gate outcomes and reject routing, `blocked` routing, watchdog default, D6 join rule, end-of-run output.
  - Legal: claude-sdk auth, "Powered by", name.
  - Ops: merge owner, dev-DB exception, CODEOWNERS.
- Out: Codex terms (HRN-04); retention (DUR-06).
- OQ: OQ-1, 3, 4, 12, 14, 18, 19, 27, 28, 30, 36, 45, 50, 53, 54.

**ENG-01 Engine contracts: IR, reducer I/O, run log**: WS-ENGINE · PH0 · M1 · Critical · M · enabler · PC-05, PC-12
- Obj: Publish K1-K3 as typed Python plus JSON Schema with golden fixtures, so other teams build from week 2.
- Cov: G-01 (schema), G-03 (ScopeKey), G-05 (log schema); TLD-21. Dep: soft SPK-03. K: prod K1, K2, K3.
- In: reserved EGM keys and hidden kinds; ScopeKey on every input, effect and log entry; `effect_key` rules; rejection codes; pause reasons; fixtures (MVP template, D§5.6, deadlock). Out: loader (ENG-02); rules (ENG-03).
- OQ: OQ-3, OQ-12, OQ-19.

**SES-01 Integration contracts**: WS-INTEGRATION · PH0 · M1 · Critical · M · enabler · PC-07, PC-08, PC-19
- Obj: Freeze the Omnigent-facing contracts and ship a FakeOmni, so engine, gate, tool and profile work runs in parallel.
- Cov: G-18, G-35, G-44, G-51 (shapes only). Dep: soft SPK-03. K: prod K4, K8, K9, K11, K12, K13.
- In: K4 and FakeOmni; K11 six tools plus envelope; K12 stable ids and outcome mapping; K9 `params.coral` and bundle layout; K8 static claude-sdk row plus label rules; K13 labels and the `coral__` prefix. Out: implementations.
- OQ: OQ-3, OQ-37, OQ-43.

**API-01 API and stream contracts**: WS-PLATFORM · PH0 · M1 · High · S · enabler · PC-15, PC-16
- Obj: Draft the `/v1/coral` OpenAPI and run-stream protocol with a mock server, so web work starts in PH1.
- Cov: G-74, G-75 (drafts); TLD-03. Dep: soft ENG-01. K: prod K6, K7; cons K1-K3.
- In: endpoint list; error envelope; ETag/412; `start_key`; SSE semantics; MSW fixtures. Out: handlers; TS pipeline (API-02).
- OQ: OQ-45.

**EVD-01 Evidence and workspace-ops spike and contracts**: WS-WORKSPACE · PH0 · M1 · Critical · M · enabler · PC-26, PC-27
- Obj: Define K5 and a two-backend K10, and prove the M2 session-shell backend in 3 days.
- Cov: G-38, G-59 (design), G-40 (IR); spike 8. Dep: soft SES-01. K: prod K5, K10.
- In: K5 final-pass semantics (formatter-then-test does not livelock), may-modify flags, exit-code source; K10 op catalog plus host-frame draft. Probes: request-free shell `git status/commit/reset` with true exit codes; sandboxed commit in a linked worktree. Out: S40 build (EVD-04).
- OQ: OQ-10, OQ-39, OQ-44.

### PH1: Foundations (→ M1)

**FND-01 Coral package, tooling roots and DB environment**: WS-PLATFORM · PH1 · M1 · Critical · L · enabler
- Obj: `coral/` ships in the wheel with its own Alembic env that upgrades after Omnigent on four DB lanes.
- Cov: G-12, G-13; S29, S30, S31, S39, S39b, S39c, S39e, S57, S58, S76. Dep: soft SPK-02. K: prod K14.
- In: config roots; import-boundary test; CoralBase; `ensure_coral_schema` with newer-build, D1 and CockroachDB guards; single-head and round-trip tests; S57 deploy hook; `just coral`. Out: tables; `create_all`.
- OQ: OQ-54.

**FND-02 Server plugin seam and enablement endpoint**: WS-PLATFORM · PH1 · M1 · Critical · S · enabler · PC-38
- Obj: Coral routers and hooks load through an upstreamable `server_plugins:` seam, and `GET /v1/coral/info` gates the product.
- Cov: G-17; S32; TLD-03. Dep: hard FND-01; soft SPK-02. K: cons K6.
- In: ServerServices; routers before the SPA; hooks after the scheduler and before the runner router closes; fatal import errors; 1-line CLI wiring; tests. Out: S33; workers.

**FND-03 Coral test infrastructure**: WS-OPS · PH1 · M1 · High · M · enabler
- Obj: Every feature gets its test lanes on day one: L0/L1 pure, L2 on four DBs, L3 contracts, Tier B E2E.
- Cov: G-87 (scaffold). Dep: hard FND-01. K: cons K2, K4.
- In: `tests/coral` map; Coral-aware SQLite template; seeded fuzz; commit-boundary fault helpers; mock step bundles; `just coral::test`. Out: specific E2Es; live bench (RUL-02).
- OQ: OQ-52.

**OPS-01 Fork guard, CI lanes and merge rehearsal**: WS-OPS · PH1 · M1 · Critical · L · enabler
- Obj: Every upstream edit is ledgered and anchored, and a daily rehearsal merges `nightly^1` (TLD-17).
- Cov: G-83, G-84 (rehearsal, lanes, hygiene); S39d; R-14, R-19. Dep: hard FND-01. K: prod K16.
- In: `seams.yaml` and `upstream.yaml`; `coral-fork-guard` (roots, anchors, budgets, prefix, stale, MODIFICATIONS.md); `coral` CI group with four DB lanes; rerere rehearsal with regeneration; disabled secret-using workflows; branch protection. Out: release drill (OPS-04).
- OQ: OQ-50, OQ-54.

**OPS-02 Distribution identity and licensing basics**: WS-OPS · PH1 · M1 · High · S · enabler
- Obj: Coral and Omnigent coexist on one machine, and Coral ships with correct notices.
- Cov: G-85, G-86 (basics); S75, S77. Dep: hard FND-01; soft OPS-01.
- In: `coral` script with `~/.coral` and update check off; `coral/version.py`; NOTICE addendum; generated MODIFICATIONS.md; `coral/CLAUDE.md` DB rule once approved. Out: counsel sign-off (OPS-04); desktop (BRD-03).
- OQ: OQ-49, OQ-53.

**BRD-01 Coral brand skin**: WS-BRAND · PH1 · M1 · High · M · PC-01
- Obj: Coral looks like Coral by default in light and dark, and operator branding still overrides it.
- Cov: G-78, G-79; S79, S80, S81, S82, S83, S89; R-1, R-15, R-16; TLD-16. Dep: none (needs designer assets).
- In: `omni` slot data → Clay Score; scoped `coral.css`; regenerated CSS and tests; `--font-display` (Newsreader, offline); marks, wordmark, hero, BrandLogo fallback, defaults; favicon; onboarding art. Out: `--font-heading` repoint; native shells.
- OQ: OQ-7, OQ-30.

**BRD-02 Navigation shell and desk chrome**: WS-BRAND · PH1 · M1 · High · S · PC-02, PC-38
- Obj: Users reach Workflows and Agent Profiles from the sidebar, palette and URLs, gated by `/v1/coral/info`, under one header.
- Cov: G-80, G-81 (routes, gate, nav); S34, S84. Dep: hard FND-02; soft BRD-01. K: cons K6.
- In: `coralRoutes(prefix)`; CoralGate (loading, disabled → Not found, error); nav insert; active-item exclusion; palette actions; CoralPageHeader on Inbox, Automations and placeholder desks. Out: desk content.
- OQ: OQ-27.

**ENG-02 Workflow model, loader and compiler**: WS-ENGINE · PH1 · M1 · Critical · L · PC-04, PC-11
- Obj: YAML loads with source marks and compiles to a frozen, content-hashed IR.
- Cov: G-01. Dep: hard ENG-01, FND-01. K: cons K1.
- In: safe-load with `yaml_path` → range; stable and reserved ids; frozen IR; hash; JSON Schema export. Out: validation; layout file.
- OQ: OQ-8.

**ENG-03 Validator and derived joins**: WS-ENGINE · PH1 · M1 · Critical · L · PC-05
- Obj: Invalid workflows get box-anchored plain explanations; valid ones get derived join types and checked parts.
- Cov: G-02, G-03 (validator); R-24. Dep: hard ENG-02. K: cons K1, K8.
- In: V1-V7; V10 hook; V11 as block-structure soundness; V12; V13; regions; AND-join vs merge; back-arrow exemption; loop table; explanation catalog. Out: V8 (ENG-09); V9 (RUL-03); exhaustive enumeration.
- OQ: OQ-9, OQ-19.

**ENG-04 Reducer core**: WS-ENGINE · PH1 · M1 · Critical · L · PC-12, PC-14
- Obj: A pure `transition()` walks start → step → decision → gate → end with typed effects and never throws.
- Cov: G-04 (core), G-03 (scope in state). Dep: hard ENG-01, ENG-02; soft ENG-03. K: cons K1, K2.
- In: Run, Activation, Slot, Attempt, Decision and Gate-visit machines; commands and observations; `effect_key`; rejection tables. Skeleton slice first. Out: loops (ENG-05); lifecycle (DUR-04); structure (ENG-08).
- OQ: OQ-3.

**ENG-05 Loops, joins and failure paths**: WS-ENGINE · PH1 · M1 · Critical · L · PC-12, PC-24
- Obj: Back-arrows, at-limit routes, joins, failure paths and liveness behave exactly as the validator explains.
- Cov: G-04 (control), G-03 (arrivals), G-62 (activation cap). Dep: hard ENG-03, ENG-04. K: cons K1-K3.
- In: loop counters by `iteration_path`; at-limit with open findings; join arrivals and merge; `arrow.skipped`; attempts and failure path; `blocked`; liveness pause; activation cap. Out: dead-path elimination; region cancel.
- OQ: OQ-12, OQ-19.

**ENG-06 Run log and fold invariants**: WS-ENGINE · PH1 · M1 · High · M · enabler · PC-33
- Obj: `fold(log) == state` holds under seeded fuzzing, so durability and the run view can trust the log.
- Cov: G-05. Dep: hard ENG-04; soft FND-03. K: cons K3.
- In: entry builders; fold; receipts; I1-I8 in CI; D§5.6 and deadlock regressions. Out: persistence; stream.

**ENG-07 Simulate API and the MVP template**: WS-ENGINE · PH1 · M1 · Critical · L · PC-09, PC-12
- Obj: Through the API, users walk any workflow for free, and the TLD-01 template ships with saved simulations.
- Cov: G-66 (scripted, saved, estimate), G-69 (package), G-62 (session estimate). Dep: hard ENG-05, ENG-06; soft DUR-01. K: cons K1-K3, K6.
- In: reducer with stub effects; scripts (labels, lists, pass/fail, gate answers); `POST /v1/coral/simulate`; saved cases re-run per version; template YAML and sims as package data. Out: UI (WEB-03); exhaustive mode; PR-review template (ENG-08).
- OQ: OQ-9.

**DUR-01 Workflow library: versions, drafts, upload and import**: WS-PLATFORM · PH1 · M1 · Critical · M · PC-04
- Obj: Workflows are DB-canonical immutable versions plus drafts, imported from a host repo or uploaded (TLD-06).
- Cov: G-14 (library), G-15, G-68 (DB, import, upload); S71. Dep: hard FND-01, FND-02, ENG-02. K: cons K1, K6, K14.
- In: workflow, version, draft, sim-case and blob-ref tables; `coral/v1/{ws}/…` keys with put-then-commit and caps; CRUD, ETag/412, `:validate`; `fs_request` import; `coral workflow upload`; S71 upstream fix. Out: export (DUR-07); UI.
- OQ: OQ-8, OQ-33.

**DUR-02 Run store and transition persistence**: WS-PLATFORM · PH1 · M2 · Critical · L · enabler · PC-14
- Obj: A transition's state, log and effects commit atomically under CAS on every lane.
- Cov: G-14 (run tables). Dep: hard FND-01, ENG-01; soft ENG-04. K: cons K2, K3, K14.
- In: one schema PR covering runs, specs, activations, arrivals, slots, handoffs and items, gate visits, timers, effects, signals, log and bindings, all with scope keys; `start_run` via `start_key`; CAS `apply_transition` with retry; L2 tests on four lanes. Out: other tables; purge.

**DUR-03 Durable queue, workers and reconciler**: WS-PLATFORM · PH1 · M2 · Critical · L · enabler · PC-14, PC-24
- Obj: Signals, timers and effects run at least once under leases, and runs reconcile at startup and periodically (TLD-08).
- Cov: G-11, G-25 (scopes, keys), G-16 (lazy authority checks); R-4. Dep: hard DUR-02, FND-02. K: cons K2, K4, K14.
- In: claim, renew and finish with lease recovery; StartupLease executor; workers in workspace, account and host-owner scopes; effect drainer; timer scan; off-thread signal intake; reconcile and resync; single-replica refusal; `authority_revoked` pause. Out: PersistentTaskScheduler; multi-replica.
- OQ: OQ-34, OQ-42.

**API-02 Coral API, OpenAPI client and run stream**: WS-PLATFORM · PH1 · M2 · Critical · L · PC-15, PC-16
- Obj: Runs are served over `/v1/coral` with a drift-tested OpenAPI, a generated TS client and a resumable stream.
- Cov: G-74, G-75. Dep: hard FND-02, DUR-02; soft API-01, ENG-06. K: cons K3, K6, K7.
- In: router scaffolding; access through the run session; runs list, get and start; `dump_openapi.py --check`; TS client; SSE from the run log; web client with slot acquisition and polling fallback. Out: endpoints owned by DUR-01, ENG-07, GTE-01/02, DUR-04.
- OQ: OQ-45.

**WEB-01 Read-only workflow diagram**: WS-WEB · PH1 · M2 · Critical · M · PC-10, PC-16
- Obj: One renderer draws any compiled workflow and hosts the Simulate and run overlays (TLD-14).
- Cov: G-71; R-16. Dep: soft ENG-01, ENG-02. K: cons K1.
- In: graph model; one xyflow adapter; design taxonomy (Note layout-only); dagre in a worker; overlay API; states (loading, layout pending, parse error with last valid, too large). Out: editing; ELK.
- OQ: OQ-30.

**WEB-02 Workflows desk and YAML editor**: WS-WEB · PH1 · M2 · Critical · L · PC-04, PC-05, PC-11, PC-37
- Obj: Users find, open and edit workflows in YAML with live server markers and a diagram preview.
- Cov: G-70, G-73 (problem list), G-81 (intro, empty states); TLD-15. Dep: hard BRD-02; soft API-01, DUR-01, WEB-01. K: cons K1, K6.
- In: tabs with all states; intro walkthrough; monacoSetup pane with the `yaml` CST; server-only markers; problem list; save; 412 dialog; dirty guard. Out: guarantees panel; canvas.
- OQ: OQ-9, OQ-27.

### PH2: Stateful engine and first end-to-end run (→ M2)

**SES-02 Session facade and engine dispatch**: WS-INTEGRATION · PH2 · M2 · Critical · L · enabler · PC-18
- Obj: The engine creates, briefs, interrupts and stops run sessions request-free and idempotently, in the SPK-01 topology.
- Cov: G-18, G-19, G-22 (build), G-25 (keys); S4, S41, S42, S51; R-9, R-13. Dep: hard SPK-01, SES-01, FND-02. K: cons K4, K9, K13.
- In: uuid5 ids from `effect_key`; run session plus `own_runner` children; labels; policies before input; `_post_event_impl` with EngineEventContext; read before resend; cancel → stop → `omnigent.closed`; S51; L3 contract tests (signature snapshots, row diff). Out: S35 and grants (contingency); S55.
- OQ: OQ-17, OQ-41, OQ-47.

**SES-03 Turn-end signals**: WS-INTEGRATION · PH2 · M2 · Critical · L · PC-22
- Obj: Coral reliably learns, per mode, that an engine turn ended, and never nudges a user's turn.
- Cov: G-20, G-21; S1, S1b, S43, S44 (optional). Dep: hard FND-02, SES-01; soft DUR-03. K: cons K4, K13.
- In: observer registry with one-line sites (bypasses notify); origin slugs; `turn_outcome` on headless edges; O(1) filter with off-thread enqueue; per-mode rule with `stable_id` map; engine-only nudges. Out: S2 (HRN-04); native Stop hook (HRN-02).
- OQ: OQ-13.

**TLS-01 Engine tool transport**: WS-INTEGRATION · PH2 · M2 · Critical · M · enabler
- Obj: One declaration registers the `coral_*` tools and routes calls to server handlers with identity and dedup.
- Cov: G-26, G-27; S7, S8, S9, S10, S11, S12 (headless), S49, S50; R-10; TLD-04. Dep: hard FND-02, SES-01. K: cons K9, K11.
- In: `tools/extensions.py` provider (registration, dispatch, relay, pre-approval, framework text); `server_tools.py` registry (migrates `sys_advise_models`); operation id, actor and provenance; `(run, operation_id)` dedup; `params.coral` opt-in. Out: native channels; handlers.
- OQ: OQ-43.

**TLS-02 Step tool: submit handoff**: WS-INTEGRATION · PH2 · M2 · Critical · M · PC-18, PC-26
- Obj: Step agents finish through `coral_submit_handoff`; illegal calls are rejected with a reason and counted.
- Cov: G-28; X-15. Dep: hard TLS-01, ENG-04, DUR-03. K: cons K2, K11.
- In: handler → reducer → short transaction; `done|blocked`, report, artifacts, label and items; bounded synchronous evidence hook with an evaluating lease; rejection codes; slot counter; generation check; dedup. Skeleton slice first. Out: `refresh_note` (SES-06); checks (EVD-06).
- OQ: OQ-10, OQ-12.

**TLS-03 Orchestrator decisions and ask_user**: WS-INTEGRATION · PH2 · M2 · Critical · L · PC-17, PC-20
- Obj: The orchestrator chooses arrows with a reason, asks without blocking, and cannot do the work.
- Cov: G-29, G-30, G-32, G-33; R-11; X-10, X-11. Dep: hard TLS-02, PRF-01, GTE-01; soft RUL-01. K: cons K9, K11, K12.
- In:
  - Orchestrator: seeded, claude-sdk, no `os_env`; `orchestrator_guard` in bundle guardrails.
  - Decisions: legal labels plus handoff collections; server-validated label; `items`.
  - Chat: interleaving; user errors not counted; lazy creation.
  - `ask_user`: durable row and form; vendor ask tools denied.
- Out: TLS-04 tools. MVP feedback rides back-arrow handoffs.
- OQ: OQ-7, OQ-13, OQ-14.

**GTE-01 Durable human gates**: WS-INTEGRATION · PH2 · M2 · Critical · L · PC-19
- Obj: Gate visits are durable rows shown as approval cards on the run session. Answers advance once and survive restarts (TLD-09).
- Cov: G-34, G-35; S5, S6 (S6a, S6b); R-7, D32. Dep: hard ENG-04, DUR-03, SES-02. K: cons K2, K12.
- In: row before publish; visit token and CAS; "no longer current"; reminders that never auto-resolve; S5 observer list; S6a stable-id publish; S6b verdict registry with resolver identity; re-publish; answer API; gate context in ApprovalCard/ApprovePage with authored outcomes only. Out: Inbox kind; external delivery.
- OQ: OQ-3, OQ-4, OQ-5.

**GTE-02 Workflow inbox and run notifications**: WS-WEB · PH2 · M2 · Critical · M · PC-21
- Obj: Gates, questions and pauses appear as an Inbox workflow kind with server ack; runs notify at run level while the app is open.
- Cov: G-36; S36, S37, S85; R-6; X-30. Dep: hard GTE-01, BRD-02; soft API-02. K: prod K17; cons K6, K13.
- In: `coral_alerts`; feed, ack and actions; card and sidebar count; per-step pings suppressed while elicitation pings stay; deep-linked run notifications; "app must be open" notice; all states. Out: GTE-03; GTE-04.
- OQ: OQ-24.

**EVD-02 claude-sdk evidence capture**: WS-WORKSPACE · PH2 · M2 · Critical · L · PC-26
- Obj: For claude-sdk steps, each command's exit code and the workspace state after it are recorded durably (TLD-10).
- Cov: G-39 (claude-sdk), G-38 (L1); S68 (runner site), S69 (a). Dep: hard EVD-01, TLS-01, WSP-01; soft DUR-02. K: cons K5, K10.
- In: tool-completion observer registry; `/mcp/execute` response field plus server hook; `coral_command_observations`; L1 via runner `/changes` and the session-shell backend. Out: L2 and other modes (EVD-05).
- OQ: OQ-10.

**EVD-03 Done-when evaluator**: WS-WORKSPACE · PH2 · M2 · Critical · M · PC-26
- Obj: A handoff closes only if the confirmed commands passed after the last change; otherwise the agent is told what is missing.
- Cov: G-40. Dep: hard EVD-02, TLS-02. K: cons K5.
- In: final-pass evaluation; may-modify flags; missing-item messages; synchronous bounded scan; temp-git tests. Out: checks and integrity diff (EVD-06).
- OQ: OQ-10.

**WSP-01 Run worktree, engine commits and retry reset**: WS-WORKSPACE · PH2 · M2 · Critical · L · PC-27, PC-14
- Obj: Each run has its own worktree and branch; the engine commits accepted handoffs, and retry resets a step safely.
- Cov: G-58 (bindings, lifecycle), G-59 (session-shell backend); S72 (`head_commit`), S73 (conditional). Dep: hard EVD-01, FND-01; soft SES-02, DUR-01. K: cons K4, K10, K14.
- In: repo bindings; `coral/r-<run>/base` with a start commit; sessions with `workspace=` and no `git` options; trailer commits; salvage ref, then reset and clean before a retry; retention and disk cap. Out: agent worktrees; host backend; setup.
- OQ: OQ-18, OQ-39, OQ-44.

**PRF-01 Pinned profiles and per-step bundles**: WS-HARNESS · PH2 · M2 · Critical · L · PC-07
- Obj: Steps run generated, content-addressed agents from pinned revisions; a profile edit never changes a running run (TLD-05).
- Cov: G-50 (minimal), G-51, G-52 (S54), G-47 (claude-sdk), G-62 (backstop); S54. Dep: hard SES-01, FND-01; soft RUL-01, DUR-01. K: cons K9, K14.
- In: agent row plus `params.coral`; revisions with byte copy and digest; version pins; drift check; seeded orchestrator, implementer and reviewer; deterministic tar → hidden `coral__` rows; hygiene; `write_paths: []` + `read_only_os` on read-only steps; guardrails slot; `cost_budget` backstop with no soft ASK. Out: desk; S53.
- OQ: OQ-37, OQ-48.

**HRN-01 claude-sdk credential guard**: WS-HARNESS · PH2 · M2 · Critical · S · PC-03
- Obj: Run-owned claude-sdk sessions start only on API-key or provider auth (TLD-07).
- Cov: G-54 (core); S13, S63, S21 (conditional). Dep: hard SPK-02, SES-01; soft PRF-01. K: cons K9.
- In: spawn-env flag; executor refusal; `harness_accounts` preflight; provider refs only; `_base_tools` test; honest copy for subscription-only users. Out: HRN-03 scope.
- OQ: OQ-28.

**RUL-01 Coral policies and run guard**: WS-INTEGRATION · PH2 · M2 · Critical · M · PC-08, PC-14
- Obj: Rosters, orchestrator limits and pause/cancel hold by policy, not by prompt.
- Cov: G-45, G-46; S52; R-3. Dep: hard FND-02, SES-01; soft PRF-01. K: cons K9, K13.
- In: `coral.policies` (step_roster, orchestrator_guard, engine_tool_guard, input-scope deny); `spawn: false`; one-line required-policy provider in `builder.py`; DENY non-`coral_*` tools while paused or cancelled. Out: templates; S26.

**DUR-04 Run control: lifecycle, pauses and timers**: WS-ENGINE · PH2 · M2 · Critical · L · PC-14, PC-24
- Obj: Users pause, resume, cancel and retry with one clear pause reason, and runs advance without babysitting.
- Cov: G-06, G-07. Dep: hard ENG-05, DUR-03, SES-02; soft WSP-01, GTE-02. K: cons K2, K3, K17.
- In: idempotent start; pause reasons; resume on the pinned version; cancel with late-submit rejection; retry with reset; auto-advance; watchdog (remind once, then alert); rejected-call pause (3 per slot); endpoints; an alert per pause. Out: overdue; budget pause; plan-limit pause.
- OQ: OQ-14, OQ-18.

**SES-04 Recovery: runner loss, host offline, drift**: WS-INTEGRATION · PH2 · M2 · High · L · PC-24, PC-18
- Obj: Runs survive runner loss, host offline and user actions on their sessions by pausing with an explanation and recovering safely (TLD-12).
- Cov: G-23, G-24 (MVP); D26. Dep: hard SES-02, DUR-03; soft WSP-01, SES-03. K: cons K4, K13.
- In: `runner_last_seen` liveness; wake; no restart during the 72 h hold; generation fencing; engine relaunches children; drift checks with re-attach or pause; outcomes for archive, delete, stop, fork and `/clear`. Out: S26, S46, S53 guards; S48.
- OQ: OQ-17, OQ-46.

**SES-05 Walking skeleton and E2E lane**: WS-INTEGRATION · PH2 · M2 · Critical · M · PC-14, PC-19
- Obj: First integration target: a one-step workflow runs on a real session, submits, opens a gate, is answered, ends, and survives a server kill.
- Cov: G-87 (E2E-1, E2E-2). Dep: hard ENG-04, DUR-03, SES-02, TLS-02, GTE-01 (skeleton slices); soft API-02, SES-03, WEB-06, FND-03. K: cons K2, K4, K11, K12.
- In: wiring; demo script; E2E-1 (Tier B mock calls submit; API gate answer); E2E-2 (SIGTERM between brief and handoff; no second session); credentialed claude-sdk demo; stub burn-down list. Out: the MVP template journey.

**WEB-03 Simulate and guarantees panels**: WS-WEB · PH2 · M2 · High · L · PC-08, PC-12
- Obj: In the editor, users simulate every branch and see "What Coral guarantees" with labels that never over-claim (TLD-11).
- Cov: G-67, G-73 (labels). Dep: hard WEB-01, WEB-02, ENG-07; soft RUL-02. K: cons K1, K6, K8.
- In: script panel from derived info; overlay (visits, edges, limits); estimate; saved-test badges; four-label badges; server-computed panel; states (incomplete script, deadlock, limit hit, failing test). Out: multi-mode labels (RUL-02).
- OQ: OQ-24.

**WEB-04 Templates and "use on my repo"**: WS-WEB · PH2 · M2 · High · L · PC-06, PC-09, PC-26
- Obj: A new user goes from the gallery to a saved, simulated workflow on their repo with confirmed done-when commands (TLD-19).
- Cov: G-69 (gallery, dialog), G-41, G-42 (picker). Dep: hard ENG-07, DUR-01, WEB-02; soft WSP-01, EVD-01. K: cons K5, K6.
- In: gallery; dialog (name, repo, parameters, model per role); detection from manifests, justfile, Makefile, CI and pre-commit; patterns table and confirm API; picker stored as K5; states (gallery failed, host offline, nothing found). Out: LLM translation; profile picker.
- OQ: OQ-38.

**WEB-05 Start a run and runs list**: WS-WEB · PH2 · M2 · Critical · M · PC-13, PC-15, PC-25
- Obj: Users start a run behind a preflight that names every fix, and find any past run.
- Cov: G-76, G-77 (runs list), G-62 (estimate shown). Dep: hard API-02; soft WEB-02, HRN-01, WSP-01, DUR-04. K: cons K6.
- In: dialog (request, host/repo/base, version pin, estimate, activation cap); preflight (V10, API key, host online, validity); idempotent start; runs list with all states. Out: money budgets (DUR-05); sandboxes.
- OQ: OQ-15, OQ-16.

**WEB-06 Live run view**: WS-WEB · PH2 · M2 · Critical · L · PC-14, PC-16, PC-24, PC-33
- Obj: Users can tell where the run is, why it went this way, what passed and what it waits on, without a transcript.
- Cov: G-77 (overlay, inspector, timeline, evidence, banners); R-17. Dep: hard WEB-01, API-02; soft DUR-04, EVD-03, GTE-01. K: cons K3, K7.
- In: header with lifecycle actions; state overlay with loop counters and open gates; inspector (step, decision reason, gate, log); evidence with missing items; timeline; pause banners (reason, resume condition, actions); stream states. First slice: a log list for SES-05. Out: WEB-07; WEB-08.
- OQ: OQ-17, OQ-23.

**WEB-07 Run sessions and steering**: WS-WEB · PH2 · M2 · High · M · PC-17, PC-18, PC-22
- Obj: From the run view, users open any agent or the orchestrator, type in with honest hints, and get back to the run.
- Cov: G-77 (agent pane, composer); S86. Dep: hard WEB-06, SES-02; soft SES-03. K: cons K7, K13.
- In: SubagentTabPane via `?agent=&node=`; current orchestrator; "read after current turn" hint; run-owned banner; "Part of run" chip; "Step waiting on you". Out: stitching and take-over (SES-06).
- OQ: OQ-13.

### PH3: Profiles, capabilities and enforcement (→ M3)

**PRF-02 Agent Profiles desk and picker**: WS-HARNESS · PH3 · M3 · High · L · PC-07, PC-03
- Obj: Users manage profiles as pinned revisions over custom agents and pick them per step with capability chips.
- Cov: G-50 (full), G-53; S66 (optional). Dep: hard PRF-01, BRD-02; soft RUL-02. K: cons K6, K8, K9.
- In: `/v1/coral/profiles` (revisions, used-by); edits by reinstall ("running runs keep rev N"); Coral fields in `params.coral`; `/profiles` with all states; cmdk picker ("Claude" chips, source, used-by). Out: inspector embedding (WEB-10).
- OQ: OQ-27, OQ-37.

**RUL-02 Capability registry, bench and per-mode labels**: WS-HARNESS · PH3 · M3 · Critical · L · PC-08, PC-05
- Obj: Every label is computed per mode from a tested registry, read-only reviewers included.
- Cov: G-44, G-47 (per mode), G-73 (per mode); S22, S23, S59, S78; D14, D17. Dep: hard SES-01, PRF-01; soft SPK-02. K: cons K8.
- In: S22 fields for four modes plus guard tests; S59; enforceability computation; probes with offline verdicts and feature-map rows; nightly bench; read-only Enforced on claude-sdk and Verified by fingerprint diff elsewhere. Out: Codex enablement.
- OQ: OQ-51.

**RUL-03 Rules catalog: Required and Guidance**: WS-INTEGRATION · PH3 · M3 · High · L · PC-29, PC-06
- Obj: Required catalog rules are enforced per mode or make the workflow invalid; Guidance rules show as Requested.
- Cov: G-48 (templates, V9, labels); R-12. Dep: hard RUL-01, RUL-02, PRF-01. K: prod K15; cons K8, K9.
- In: about 8 templates (worktree_guard, blast_radius, mode-aware egress, CEL ask-before-path, never force-push); workflow, step and profile scopes; V9 with remedies; bundle guardrails; rules panel. Out: LLM translation; reactions; V8.
- OQ: OQ-38.

**RUL-04 Reactions and overdue alerts**: WS-ENGINE · PH3 · M3 · Medium · M · PC-29, PC-24
- Obj: "When X happens, do Y" rules work, starting with overdue steps and runs.
- Cov: G-48 (timer reactions), G-06 (overdue). Dep: hard DUR-04, RUL-03; soft GTE-02. K: cons K15, K17.
- In: reaction templates; `expected_duration` × factor timers; inbox alerts; validation. Out: reactions that change the graph.

**HRN-02 claude-native steps behind fail-closed hooks**: WS-HARNESS · PH3 · M3 · High · L · PC-03
- Obj: Subscription users run step agents on claude-native with fail-closed policies and honest labels (TLD-07).
- Cov: G-49 (S14, S16), G-55; S3 (launch args), S12 (native), S14, S16, S24 (native), S64. Dep: hard PRF-01, RUL-01, TLS-01, SES-03; soft RUL-02. K: cons K8, K9, K11.
- In: probes 5 and 6 first; fail-closed output; early returns deny; `onFailure: block`; timeout; hooks-installed check; sub-agent identity; launch framework text; Stop-hook turn end; egress auto-add; steps only; E2E-3 and E2E-4. Out: codex-native.
- OQ: OQ-28, OQ-35, OQ-46.

**HRN-03 Model access, credentials and plan limits**: WS-HARNESS · PH3 · M3 · High · M · PC-03, PC-24
- Obj: Users choose how Claude is reached per profile, runs pin an account, and plan-limit pauses show when they resume.
- Cov: G-54 (full), G-57; S24 (claude-sdk). Dep: hard HRN-01, PRF-02; soft HRN-02. K: cons K8.
- In: onboarding and settings (API key vs subscription → claude-native); per-profile auth badge; operator binding deference; account pinned per run; RateLimitEvent and reset time → paused-until with auto-resume. Out: Codex limits.
- OQ: OQ-28.

### PH4: Trust and structure (→ M4)

**EVD-04 Host workspace-op channel**: WS-WORKSPACE · PH4 · M4 · Critical · L · enabler · PC-26
- Obj: Coral runs sessionless workspace ops on hosts with true exit codes, and moves commit, reset and salvage there.
- Cov: G-38 (channel), G-59 (host backend); S40, S40b; X-17. Dep: hard EVD-01, DUR-03; soft WSP-01. K: cons K10.
- In: frames; `workspace_ops:1`; reaper-guarded dispatcher; server proxy; job journal; entry-point op registry; host backend for status, commit, salvage, reset and exec; skew fallback. Out: L2; checks.
- OQ: OQ-44.

**EVD-05 L2 fingerprints and multi-mode observations**: WS-WORKSPACE · PH4 · M4 · High · M · PC-26
- Obj: Evidence becomes exact (tree hash) and works for native and Codex modes.
- Cov: G-38 (L2), G-39 (other modes); S68 (rest), S69 (b). Dep: hard EVD-04, EVD-03; soft HRN-02. K: cons K5, K10.
- In: `write-tree` on a temporary index; observers at the remaining sites; outbox observation event; native PostToolUse hints; codex `exit_code`. Out: plain-folder manifests.

**EVD-06 Coral-run checks and verifier pattern**: WS-WORKSPACE · PH4 · M4 · High · L · PC-26
- Obj: Coral runs pinned checks in a controlled checkout, flags tampering, and offers a verifier step.
- Cov: G-43, G-58 (setup); S72 (detached); D8, D13, X-32. Dep: hard EVD-04, EVD-05; soft WSP-02. K: cons K5, K10.
- In: sandboxed exec jobs; detached checkout; snapshotted commands; JUnit; integrity diff; `.coral/repo.yaml` setup; read-only verifier step labelled Judgment. Out: hidden tests; rubric judges.
- OQ: OQ-10, OQ-44.

**WSP-02 Per-agent worktrees and serial merges**: WS-WORKSPACE · PH4 · M4 · High · L · PC-27, PC-30
- Obj: Code-writing agents work in their own worktrees and merge serially; conflicts are fixed in the agent's worktree.
- Cov: G-60; D10, D11. Dep: hard EVD-04, EVD-06, ENG-08; soft TLS-04. K: cons K10.
- In: `agent-<n>` worktrees; serial merge at close or join; conflict sub-state via `coral_assign_task`; mandatory post-merge checks; submodule and LFS probe. Out: unchecked merges.
- OQ: OQ-40.

**ENG-08 Repeat-for-each and parallel regions**: WS-ENGINE · PH4 · M4 · High · L · PC-30
- Obj: The PR-review showcase runs: per-item repeats with progress, and parallel branches that join or cancel cleanly.
- Cov: G-08, G-09; E2E-5. Dep: hard ENG-05, DUR-04; soft TLS-04. K: cons K1, K2.
- In: repeat contract (order, empty, per-item failure, concurrency, per-item gates, batching, "3 of 10"); parallel join and region cancel; PR-review template; E2E-5. Out: UI; merges.
- OQ: OQ-2, OQ-19.

**ENG-09 Groups, blocks and Wait**: WS-ENGINE · PH4 · M4 · Medium · L · PC-30, PC-29
- Obj: Authors group steps with inherited rules, save blocks, and use Wait timers.
- Cov: G-10 (except Sub-workflow). Dep: hard ENG-08, RUL-03. K: cons K1, K15.
- In: group IR; V8; blocks library; hidden Wait. Out: Sub-workflow invocation.

**TLS-04 Live messaging and roster tools**: WS-INTEGRATION · PH4 · M4 · Medium · M · PC-30
- Obj: Parallel agents and the orchestrator message through the engine; up-to rosters and conflict re-tasking work.
- Cov: G-31. Dep: hard TLS-03, ENG-08. K: cons K11.
- In: `coral_message_agent` (isolation, rate limit, steer-vs-close race); `coral_assign_agents`; `coral_assign_task`. Out: `sys_session_message`.

**WEB-08 Structure visuals and run-view depth**: WS-WEB · PH4 · M4 · Medium · M · PC-16, PC-30
- Obj: Diagrams, Simulate and runs show repeats, regions, groups and why-not-taken arrows.
- Cov: G-77 (full); structure layers for G-67 and G-71. Dep: hard WEB-06, ENG-08; soft ENG-09. K: cons K1, K3, K7.
- In: WEB-01 overlay layers (repeat badges, region frames, groups); why-taken and why-not; take-over markers. Out: editing.
- OQ: OQ-23.

**WEB-09 Canvas editing core**: WS-WEB · PH4 · M4 · High · L · PC-10
- Obj: Users draw and rewire workflows, and the YAML keeps comments and confirmed translations.
- Cov: G-72 (core); D19. Dep: hard WEB-01, WEB-02. K: cons K1.
- In: palette; connect, move, delete; intents → CST patches; layout file by stable ids; one undo stack; golden round-trips. Out: inspectors.
- OQ: OQ-22.

**WEB-10 Inspectors and accessible outline**: WS-WEB · PH4 · M4 · High · L · PC-10
- Obj: Every property is editable in an inspector, and keyboard and screen-reader users have an outline view.
- Cov: G-72 (inspectors, outline). Dep: hard WEB-09; soft PRF-02, RUL-03, WEB-04. K: cons K1, K15.
- In: step, arrow, gate, decision and group inspectors; embedded picker, rules panel and done-when picker; outline tree; a11y tests. Out: freeform layout tools.
- OQ: OQ-22.

**SES-06 Slot control: refresh and take-over**: WS-INTEGRATION · PH4 · M4 · Medium · L · PC-17, PC-23, PC-24
- Obj: Long sessions refresh by slot restart with a stitched orchestrator view, and users can take over a step and hand it back (TLD-13).
- Cov: G-63, G-64; S25 (lite), S27 (retest), S45; R-8. Dep: hard SES-02, SES-04, EVD-03; soft EVD-05, WEB-07. K: cons K4, K10.
- In: per-mode threshold (70%); wait for turn end; `refresh_note`; restart and close; `"refresh"` literal; supersession observer; stitched transcript; reaper retests; `taken_over(by)` with reminders and auto-advance off; hand-back re-evaluates done-when; controls. Out: S47.
- OQ: OQ-11.

**GTE-03 External notification connector**: WS-INTEGRATION · PH4 · M4 · High · M · PC-21
- Obj: Unattended gates and pauses reach users when the app is closed, starting with a webhook.
- Cov: G-37 (connector). Dep: hard GTE-02, DUR-03. K: cons K17.
- In: per-user channel config; outbox webhook, idempotent per channel; deep links without secrets; email or Slack DM next; settings. Out: push.
- OQ: OQ-6.

### PH5: Production readiness (→ M4)

**HRN-04 codex-native step mode**: WS-HARNESS · PH5 · M4 · High · L · PC-35
- Obj: Codex steps run as codex-native and fail closed.
- Cov: G-56 (native); S2, S15, S62, S16 and S12 (codex parts), S24 (codex). Dep: hard HRN-02, RUL-02; soft SES-03.
- In: probes 12 and 13; turn outcome; refuse without hooks; explicit `yolo` with policy-resolved approvals; rate-limit pause; labels. Out: headless.
- OQ: OQ-29.

**HRN-05 Headless codex mode**: WS-HARNESS · PH5 · M4 · Medium · L · PC-35
- Obj: Codex steps run headless with gated tools and honest read-only behaviour.
- Cov: G-56 (headless); S18, S19, S20, S60, S61, S67. Dep: hard RUL-02; soft HRN-04.
- In: `threadId` routing; compaction; `hooks.json` gating; per-session switches; read-only fix; hook trust fails closed; gating probe. Out: hosted use without a terms answer.
- OQ: OQ-29.

**DUR-05 Run and step budgets**: WS-PLATFORM · PH5 · M4 · High · M · PC-25
- Obj: Hitting a run or step budget pauses the run and asks; users see spend and an estimate from history.
- Cov: G-62; R-5; D21, D34. Dep: hard RUL-01, GTE-01, DUR-04. K: cons K12.
- In: tree spend aggregator; `paused(budget)` with a raise-or-stop elicitation; run-guard DENY; overshoot disclosure; tokens for plan users; median estimates; step budgets. Out: account switching.
- OQ: OQ-15, OQ-16.

**DUR-06 Retention, purge and account lifecycle**: WS-PLATFORM · PH5 · M4 · Medium · M · PC-33
- Obj: Run data is kept and purged by policy, and Coral rows follow account revocation and migration.
- Cov: G-16; S56. Dep: hard DUR-02.
- In: retention policy; batched `purge_run`; blob GC; deleting workflows that have runs; carry-or-purge callbacks. Out: legal hold.
- OQ: OQ-25.

**DUR-07 Versions, repo export and restart-from-node**: WS-PLATFORM · PH5 · M4 · Medium · L · PC-28, PC-34, PC-32
- Obj: Users see versions and diffs, export to `.coral/`, and amend by restarting from a node with carried handoffs (TLD-18).
- Cov: G-65 (lite), G-68 (export); S74. Dep: hard DUR-01, DUR-04, WEB-02; soft EVD-04. K: cons K6, K10.
- In: versions list and diff; runs per version; `.coral/**` write with an expected-hash precondition; restart-from-node dialog creating a linked run. Out: full "Apply to this run".
- OQ: OQ-20.

**OPS-03 Production hardening: load, faults and security**: WS-OPS · PH5 · M4 · Critical · L
- Obj: Coral meets its committed limits under load and passes a security review before release (TLD-08).
- Cov: G-87 (fault suites), G-11 (single replica verified); D25. Dep: hard DUR-03, SES-04, GTE-01; soft GTE-03.
- In: load test of concurrent runs; SQLite contention; CockroachDB/MySQL fault suites; release statement (SQLite, Postgres); threat model (bridge bearer, runner-local endpoints, credentials, gate authority, webhooks) with fixes. Out: multi-replica.
- OQ: OQ-1, OQ-42.

**OPS-04 Release-grade upstream drill and licensing sign-off**: WS-OPS · PH5 · M4 · High · M
- Obj: A real upstream merge is completed by the playbook, and licensing is signed off.
- Cov: G-84 (security lane, playbook), G-86 (inventory); R-2. Dep: hard OPS-01, OPS-02.
- In: real merge with re-anchoring; cherry-pick SLA; `UPSTREAM_MERGES.md`; licence-inventory CI; React Flow, OFL and dagre attribution; counsel answers; DCO. Out: relicensing.
- OQ: OQ-30, OQ-31, OQ-50.

**BRD-03 Desktop identity**: WS-BRAND · PH5 · M4 · High · M · PC-01
- Obj: The Coral desktop app has its own name, icon, scheme and update feed. No Coral desktop build ships before this lands.
- Cov: G-82 (desktop); S38, S87, S88 (desktop); R-18. Dep: hard BRD-01, OPS-02.
- In: `productName`, `appId`, `coral://`, `publish.url`; `brand.js` literals; setup and connect pages; icons incl. `Assets.car`; CLI detection; run deep links. Out: mobile.
- OQ: OQ-31.

### PH6: Post-M4 extensions

**EXT-01 Improvement suggestions**: WS-ENGINE · PH6 · post-M4 · Low · L · PC-31
- Obj: Coral proposes evidence-backed edits from finished runs, and never weakens evidence or gates.
- Cov: G-88. Dep: hard ENG-06, DUR-01; soft DUR-07.
- In: run-log detectors; suggestion list with run links; accepting creates a version. Out: auto-apply.
- OQ: OQ-26.

**EXT-02 Elephant-Goldfish showcase**: WS-ENGINE · PH6 · post-M4 · Low · M · PC-36
- Obj: Ship the EGM template: a persistent elephant step and scoped goldfish.
- Cov: G-89; S65. Dep: hard ENG-08, EVD-04, SES-06.
- In: slot rebinding; per-member input scope (S65 plus materialize op); typed resolutions; ESCALATE → gate. Out: orchestrator as the elephant.
- OQ: OQ-30.

**EXT-03 Run sharing, teams and protected run sessions**: WS-INTEGRATION · PH6 · post-M4 · Low · L · PC-32
- Obj: Teams share runs and answer gates, and run sessions are protected from mutation (TLD-12).
- Cov: G-90 (sharing, approvers), G-24 (guards), G-52 (S53); S26, S46, S53; D18. Dep: hard SES-04, GTE-01; soft GTE-03.
- In: engine-managed grants; team approvers; reserved labels and policy names on every write path; `/clear` policy; agent mutation guards. Out: marketplace.
- OQ: OQ-4, OQ-17, OQ-46.

**EXT-04 Git import and run-log export**: WS-PLATFORM · PH6 · post-M4 · Low · M · PC-32, PC-33
- Obj: Users import workflows, templates and profiles from git, and export run logs for audit.
- Cov: G-90 (import). Dep: hard DUR-07.
- In: git-URL import with a V10 profile check; JSON and Markdown export. Out: sync connectors.

**EXT-05 Automations "Run workflow" trigger**: WS-PLATFORM · PH6 · post-M4 · Low · M · PC-32
- Obj: Automations start workflow runs, with no second scheduler.
- Cov: G-90 (triggers). Dep: hard DUR-04.
- In: a "Run workflow" action; `start_key` per fire. Out: Coral-owned schedules.
- OQ: OQ-21.

**EXT-06 LLM translation for rules and done-when**: WS-INTEGRATION · PH6 · post-M4 · Low · L · PC-06, PC-29
- Obj: Free-text done-when and rules are translated by an engine-owned session, then confirmed (TLD-19).
- Cov: G-42 (option one), G-48 (LLM). Dep: hard RUL-03, WEB-04.
- In: translator role; dry-run; invalidation; usage accounting; confirmation sheet; registered handlers only. Out: untyped policies.
- OQ: OQ-38.

**GTE-04 Push and mobile notifications**: WS-WEB · PH6 · post-M4 · Low · XL · PC-21
- Obj: Approvals reach phones and browsers with the app closed.
- Cov: G-37 (push), G-82 (mobile); S88 (mobile). Dep: hard GTE-03, BRD-03.
- In: Web Push (VAPID, service worker); APNs/FCM; mobile names, icons and deep links. Out: store listings.
- XL kept: two independent stacks, post-M4, split when planned.
- OQ: OQ-6, OQ-23, OQ-31.

**WSP-03 Managed-sandbox runs**: WS-WORKSPACE · PH6 · post-M4 · Low · L · PC-27
- Obj: Runs execute in managed sandboxes and survive sleep and relaunch.
- Cov: G-61; S28, S70; D24. Dep: hard EVD-04, WSP-01.
- In: bind-mode worktrees; host-keyed keep-warm; checkpoint pushes; relaunch from a checkpoint; spike 9. Out: plain-folder shadow repos.
- OQ: OQ-5.

## 4. Deferred G-rows and unplanned seams

**Seam index** (owner in brackets): S1, S1b, S43, S44-opt [SES-03]; S2, S15, S62 [HRN-04]; S3-launch-args, S12-native, S14, S16, S64 [HRN-02]; S4, S41, S42, S51 [SES-02]; S5, S6 [GTE-01]; S7, S8, S9, S10, S11, S12-headless, S49, S50 [TLS-01]; S13, S63, S21-cond [HRN-01]; S18, S19, S20, S60, S61, S67 [HRN-05]; S22, S23, S59, S78 [RUL-02]; S24 [HRN-03 sdk, HRN-02 native, HRN-04 codex]; S25, S27, S45 [SES-06]; S26, S46, S53 [EXT-03]; S28, S70 [WSP-03]; S29, S30, S31, S39, S39b, S39c, S39e, S57, S58, S76 [FND-01]; S32 [FND-02]; S34, S84 [BRD-02]; S36, S37, S85 [GTE-02]; S38, S87, S88-desktop [BRD-03]; S88-mobile [GTE-04]; S39d [OPS-01]; S40, S40b [EVD-04]; S52 [RUL-01]; S54 [PRF-01]; S56 [DUR-06]; S65 [EXT-02]; S66-opt [PRF-02]; S68, S69 [EVD-02 sdk, EVD-05 rest]; S71 [DUR-01]; S72 [WSP-01 head_commit, EVD-06 detached]; S73-cond [WSP-01]; S74 [DUR-07]; S75, S77 [OPS-02]; S79, S80, S81, S82, S83, S89 [BRD-01]; S86 [WEB-07].

**Unplanned seams.**

| Seam | Reason |
|---|---|
| S3 (except launch args) | Lazy imports through the sessions facade already work (eng_sessions §14). |
| S17 | claude-sdk exposes no vendor sub-agents (S63 contract test). Revisit only if that changes. |
| S21 | Conditional. Built in HRN-01 only if the SPK-02 `can_use_tool` probe fails. |
| S33 | TLD-03: enablement uses the Coral-owned `/v1/coral/info`, with no Feature enum edit. |
| S35 | Contingency only. Needed only if SPK-01 forces the top-level fallback (TLD-02). |
| S44 | Optional. Added in SES-03 only if outcome classification duplicates. |
| S47 | Refresh is a slot restart (TLD-13, X-9). |
| S48 | Polling `runner_last_seen` suffices (SES-04). |
| S55 | The facade creates sessions directly through the store (X-6). |
| S73 | Run sessions carry no `git` options (TLD-12, WSP-01), so worktree cleanup on delete never triggers. Kept conditional. |

**Deferred G-row parts.** Every G-row has an owner above. These parts are deferred:

| Part | Reason |
|---|---|
| G-66 exhaustive Simulate (V11 enumeration) | Block-structure soundness plus scripted Simulate cover it (X-25, R-24). Revisit as a sampling check. |
| G-10 Sub-workflow invocation | No journey or template needs it. The kind is reserved and hidden in K1. |
| G-65 full "Apply to this run" | TLD-18. Amendments-lite ships in DUR-07. |
| G-90 workflows as tools/APIs, marketplace | Only mentioned in D§15. No product spec exists. |
| G-61 plain-folder workspaces (shadow repo) | Git worktrees only (adv M25). Evidence needs content-hash manifests first. |
| G-38 plain-folder fingerprints | Same reason as G-61. |

## 5. Milestones: proving journeys and exit criteria

**M1 Foundational Coral**: "Prove a workflow without agents" (journeys b, c, d through the API).
- Journey:
  1. `coral server` starts, and `/v1/coral/info` reports Coral enabled.
  2. The web shows the Coral brand in light and dark, and Workflows and Agent Profiles desks with empty states. Turning Coral off hides them.
  3. Import the MVP template from a local repo (or `coral workflow upload`) and get v1 with a hash. A broken copy returns box-anchored V3/V5/V7 problems.
  4. Simulate approved, changes requested ×3 → at-limit gate, and gate reject. Save the cases; they re-run on v2.
- Exit criteria:
  - The journey passes on SQLite and Postgres, and migrations run after Omnigent's on all four lanes.
  - Fork guard is required, the daily `nightly^1` rehearsal is green, and MODIFICATIONS.md and the NOTICE addendum are generated.
  - The import-boundary test passes, and the S32 upstream PR is open.
  - The fold invariant and fuzz tests run in CI.
  - K1-K14 and K16 are published with fixtures, FakeOmni and the API mock.
  - SPK-01..03 are recorded, and the UI§11 Firm checklist passes.

**M2 Functional stateful workflow (MVP)**: "Implement with review loop on my repo" (journeys a, b, c, d, e, f, g, h-steer, i-core, l-history; product §9.1).
- Journey:
  1. Use the template on a local repo, confirm the detected commands, then save and simulate.
  2. The guarantees panel shows: gate Enforced, done-when Verified, reviewers read-only Enforced (claude-sdk), decisions Judgment.
  3. Edit the YAML. Start the run on claude-sdk with an API key; preflight passes and the estimate shows.
  4. Watch done-when fail ("lint after last change") and then pass. Two reviewers run. The orchestrator picks "changes requested" with a reason, and the counter shows pass 2 of 3.
  5. Kill the server during Review. It resumes with no duplicate sessions and re-publishes the gate.
  6. Approve from the Inbox or `/approve`; the run ends and the branch is kept.
  7. On a second run, pause, resume, cancel and retry (with a worktree reset).
- Exit criteria:
  - E2E-1 and E2E-2 run in CI, and a weekly credentialed run passes.
  - Cancelled runs stay silent. Duplicate answers advance once, stale answers are refused, and no gate auto-resolves.
  - Typing into a step session never triggers a nudge, and subscription OAuth is refused.
  - Every label traces to a mechanism, and every pause has a reason, a resume condition and actions.
  - Loop limit, activation cap and the backstop are enforced, and runs list and timeline match the fold.

**M3 Functional agent profile system**: "Profiles you can trust" (journeys k, a-model-access, i-plan-limit).
- Journey:
  1. Create a "Strict reviewer" profile with a Required "never force-push" rule, and pick it for Review with capability chips.
  2. Add a Required egress rule, then switch Implement to claude-native. The validator explains per mode, and the user picks a remedy.
  3. As a subscription user, the claude-native step is blocked when the policy endpoint is blackholed.
  4. Edit the profile mid-run: the run keeps rev N, and the next run uses N+1.
  5. Overdue alerts appear, and plan-limit pauses show their reset time.
- Exit criteria:
  - E2E-3 and E2E-4 pass, and the nightly bench is green for claude-sdk and claude-native.
  - Registry guard tests pass.
  - Every Required rule has a mechanism and a label per mode, and read-only is Verified on claude-native.
  - Accounts are pinned per run.

**M4 Integrated production-ready Coral**: "Review labelled PRs" (journeys c-canvas, h-take-over, i-refresh, j-lite, m-export).
- Journey:
  1. Build the PR-review loop on the canvas; the YAML keeps its comments.
  2. Run it: repeat-for-each ("3 of 10") with parallel Claude and codex-native reviewers. Two writers merge serially with post-merge checks, and L2 evidence shows.
  3. Exercise budget pause and raise, an orchestrator refresh, take-over and hand-back, a webhook for an unattended gate, restart-from-node, export to `.coral/`, and a retention purge.
- Exit criteria:
  - SQLite and Postgres are committed, and the CockroachDB and MySQL lanes are green.
  - Load meets the OQ-1 NFRs, and the security review is closed.
  - A real upstream merge is done by the playbook, and licensing is signed off.
  - The desktop app updates from the Coral feed, and E2E-5 is green.

**post-M4.** EXT-01..06, GTE-04, WSP-03.

## 6. Critical path

**To M2 (binding).** `SPK-03 + ENG-01 → FND-01 → DUR-02 → DUR-03 → SES-05 (skeleton) → TLS-02 → TLS-03 → DUR-04 → WEB-06 → M2 journey`, about 22-26 weeks with 6 teams.

**Near-critical chains that converge on it:**
- **Engine:** `ENG-02 → ENG-04 → ENG-05`. It feeds DUR-04, TLS-03 and the M1 Simulate exit.
- **Integration:** `SPK-01 → SES-02`. It gates SES-05, GTE-01 and SES-04. If SPK-01 fails, the fallback adds about 2-3 weeks to SES-02 and SES-04 (S35, grants).
- **Evidence:** `EVD-01 → WSP-01 → EVD-02 → EVD-03`. It must land before the M2 journey's done-when step.

**To M3.** `PRF-01 → RUL-02 → RUL-03`, with `HRN-02` in parallel. HRN-02 also gates M4 Codex through HRN-04.

**To M4.** `EVD-04 → EVD-05 → EVD-06 → WSP-02` (multi-writer showcase), with `ENG-08 → TLS-04` and `HRN-02 → HRN-04` (Codex reviewer) converging on the showcase. OPS-03 (load and security) runs in the last 6 weeks and is gated on a stable DUR-03, SES-04 and GTE-01.

**Start immediately.**
- PH0 packs, SPK-01..03.
- FND-01, OPS-01, BRD-01.
- ENG-02 against K1.
- WEB-01 against fixtures.
- S71 in DUR-01.
