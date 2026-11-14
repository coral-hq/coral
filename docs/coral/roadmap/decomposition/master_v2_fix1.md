# Coral master feature list, version 2 (fix round 1)

Revision of master v1 after the architect, adversarial, engineer, product and delivery critiques. Repository `omnigent-ai/omnigent` at `2a9cbe2c2` (Omnigent 0.22.0.dev0). Date 2026-11-11. Ids G-, S-, X-, D-, R- and OQ- refer to `investigation/gap_analysis.md`; TLD- to the tech lead working decisions; PC- and journeys (a)-(m) to `investigation/product.md`; ARC-, ADV-, ENG-nn critique, PRO- and DEL- ids to the critique files. Machine-readable copy: `master_v2_fix1.json`. Every critique decision and fix round: `changelog_v2.md`.

## 0. Shape at a glance

- **108 features** (v1: 85) in 17 areas and 8 workstreams. By phase: PH0 11, PH1 34, PH2 24, PH3 13, PH4 13, PH5 6, PH6 7. By milestone: M1 25, M2 41, M3 12, M4 23, post-M4 7. Sizes: S 11, M 72, L 25; no XL. The growth comes from splits the critiques asked for, so cut lines are feature boundaries; the id map is in `changelog_v2.md`.
- **21 contracts** (K1-K21). 13 ship in PH0 and are frozen at IM-0 (week 3); K5, K9, K11, K13, K17, K21 ship in PH1; K15 and K20 ship as their producer's first PR (K20 at M2).
- **Milestones (weeks from PH0 start).** M1: CPM 11.5 single-owner / 9.5 staffed, levelled 9.5, planned 11; M2: CPM 13.5 single-owner / 13.5 staffed, levelled 13.5, planned 16; M3: CPM 19 single-owner / 17 staffed, levelled 21, planned 24.5; M4: CPM 21 single-owner / 20.5 staffed, levelled 26.5, planned 30.5. Paths are cumulative through the acceptance lanes (OPS-07 -> OPS-08 -> OPS-09); the levelled schedule assumes 20 engineers (section 6.2) and the phase gates in section 10.
- **Walking skeleton.** SES-05 reaches IM-2 at week 11.5, built on named skeleton slices of SES-03, SES-04, TLS-02 and GTE-01; OPS-07 owns the M2 acceptance lane, the credentialed soak and the dogfood check.
- **Coverage.** Every G-01..G-90 row has an owning feature, with deferred parts in section 7. Every seam S1..S89 (with S1b, S6a/b, S39b-e, S40b) has exactly one owner or is listed as not planned. A script checks ids, coverage, unique seam ownership, contract producers, that no hard dependency points to a later phase or milestone, that slice dependencies name real features, that every feature covers a G-row or is an enabler, and that the combined hard and soft graph has no cycles.
- **Boundaries.** Three tiers enforced per module: a pure layer, `coral.omni` as the only importer of `omnigent.*`, and `coral.db` with an allowlist. One plugin key registers everything (K17). Every hot-file seam is a one-line call into a registry module; Modify-class seams are upstream-first.
- **What changed most.** Contracts move earlier (K18, K19 in PH0; new K21); tables land with their owners; step close and restart are fenced; claude-sdk promise labels and spend appear at M2; security is reviewed in stages; real upstream merges start in PH1.

## 1. Contract catalog

Each contract is code (types, schema or protocol) plus a doc under `docs/coral/contracts/`, with a fake or fixtures so consumers build against stubs. It is versioned; after freeze it changes only additively or with the producer's approval and sign-off from each consumer lead. Each carries a contract test (JSON Schema golden, OpenAPI drift, facade conformance over FakeOmni and the real facade, executor conformance or ledger schema test).

| K | Contract | Producer | Ships in | Consumers | What it fixes |
|---|---|---|---|---|---|
| K1 | Workflow authoring schema and compiled IR | ENG-01 | PH0 | API-01, DUR-02, ENG-02, ENG-03, ENG-04, ENG-05, ENG-07, ENG-08, ENG-09, ENG-10, EVD-01, EXT-01, EXT-02, RUL-02, RUL-06, WEB-01, WEB-02, WEB-08, WEB-09, WEB-11, WEB-12 | YAML keys and node kinds (Note layout-only, hidden Wait and Sub-workflow), reserved keys and ids, the done_when authoring block, frozen CompiledGraph with an Analysis section (regions, join types, loop table, decision label sets, checked parts) computed by the ENG-02 compiler, content hash over the canonical authoring document only, ir_version, JSON Schema for TS, separate layout doc. |
| K2 | Reducer contract | ENG-01 | PH0 | DUR-01, DUR-03, DUR-04, DUR-05, ENG-04, ENG-05, ENG-06, ENG-07, ENG-08, ENG-09, ENG-10, ENG-11, GTE-01, OPS-07, RUL-01, SES-01, SES-04, SES-05, SES-06, SES-08, SES-09, SES-10, TLS-02, TLS-03 | transition(graph, state, input, now) and pure reconcile(graph, state, facts, now); commands and observations with idempotency keys; effects with effect_key; ScopeKey; session_generation; slot closing and post_close_activity; StartRun(from_node); closed pause reasons with resume-condition kinds; error taxonomy; I1-I8; state_version with N-reads-N-1. |
| K3 | Run-log entry schema and fold | ENG-01 | PH0 | API-02, DUR-01, DUR-03, ENG-04, ENG-05, ENG-06, ENG-07, ENG-08, EXT-01, EXT-03, WEB-04, WEB-10 | Closed additive kind enum, seq, actor, scope key, 16 KiB body cap, refs, idempotency key, a RunView patch per entry, log_version; fold(log) == state. |
| K4 | coral.omni facade protocol and FakeOmni | SES-01 | PH0 | API-02, DUR-01, DUR-02, DUR-04, DUR-05, EVD-02, EVD-03, FND-02, FND-04, GTE-01, HRN-02, HRN-03, HRN-07, OPS-02, OPS-07, RUL-05, SES-03, SES-04, SES-05, SES-06, SES-07, SES-08, SES-09, SES-10, TLS-04, WSP-01, WSP-06 | Sessions (create with role, send with stable_id and no idempotency, interrupt, stop, wake, status, items, turn facts), policies, gate publish, profiles, worktrees, host read and capabilities, plus sub-protocols for access, artifacts, scopes, usage, harness accounts, observations and the request-free runner shell, each naming its implementer; create, access and watch sections freeze after ADR-05; conformance suite over FakeOmni and the real facade. |
| K5 | Coral persistence contract | DUR-01 | PH1 | DUR-02, DUR-03, DUR-04, DUR-05, DUR-06, ENG-10, EVD-02, EVD-03, GTE-03, GTE-06, PRF-01, PRF-02, SES-03, SES-04, SES-08, TLS-02, TLS-05, WSP-01 | Table conventions incl. scope keys and derived-id PKs; Coral tables on the operational DB only with no joins or shared transactions with conversation tables; store protocols; queue and timer layout (OQ-34); at-least-once semantics; migration-train rule and train-order table. |
| K6 | Engine tool contracts | SES-01 | PH0 | EVD-02, OPS-07, SES-05, SES-07, TLS-01, TLS-02, TLS-03, TLS-04, TLS-05 | The six TLD-20 tools: argument schemas, result envelope incl. 'evaluation in progress', rejection codes, (run, operation_id) dedup, handler signature, params.coral opt-in keys. |
| K7 | Coral REST API and OpenAPI | API-01 | PH0 | API-02, BRD-02, DUR-02, EXT-05, FND-02, GTE-02, GTE-03, GTE-06, WEB-01, WEB-02, WEB-03, WEB-04, WEB-05, WEB-06, WEB-07, WEB-08, WEB-10, WEB-11, WEB-12, WEB-13 | /v1/coral/* endpoints incl. info with a sub-feature map, inbox, run outcome and spend estimate; error envelope, ETag/412, start_key, access mapping; OpenAPI artifact with drift check; generated TS types. |
| K8 | Run stream protocol and RunView projection | API-01 | PH0 | API-02, WEB-04, WEB-10, WEB-13 | SSE RunView snapshot then seq-numbered entries each with its server-computed patch; Last-Event-ID resume; heartbeat; [DONE]; polling fallback; the client never re-implements the reducer. |
| K9 | Capability registry | HRN-01 | PH1 | ENG-11, HRN-02, HRN-03, HRN-04, HRN-05, HRN-06, HRN-08, HRN-09, OPS-08, RUL-02, RUL-03, RUL-04, RUL-05, RUL-06, SES-07, SES-08, WEB-06, WEB-07, WEB-09, WEB-13 | Capability fields and enums per (harness spelling, host sandbox backend) (S22, later S59); CapabilityMatrix; effective-enforceability inputs to promise labels and V9. |
| K10 | Identity, labels and derived keys | SES-01 | PH0 | EXT-04, GTE-01, GTE-02, PRF-01, RUL-01, SES-03, SES-04, SES-09, WEB-05, WSP-01 | coral.* label keys incl. coral.role (run, orchestrator, step), uuid5(effect_key) session ids, stable_id per message, deterministic policy ids, worktree paths keyed (run, node, item_path, agent), coral_gate_ and coral_question_ ids, coral__ and coral. prefixes. |
| K11 | Evidence IR and observation records | EVD-01 | PH1 | EVD-02, EVD-03, EVD-04, HRN-03, RUL-02, RUL-06, SES-07, TLS-02, WEB-03, WSP-02, WSP-03, WSP-07 | Compiled done_when (required commands, may-modify flags, exit-code sources, scope, final-pass semantics), observation and fingerprint records from SPK-04's L1 algorithm, per-session observation watermark, the durable-before-result rule, missing-item messages. |
| K12 | Step bundle format and params.coral schema | SES-01 | PH0 | EXT-03, HRN-02, HRN-03, HRN-05, HRN-06, OPS-08, PRF-01, PRF-02, RUL-01, RUL-03, SES-03, TLS-01, TLS-03, WEB-07 | Tar layout, content addressing, params.coral keys, hygiene defaults, approval stance, guardrails slot, provider-reference auth, the inert anchor agent, revision reference. |
| K13 | WorkspaceOps interface | WSP-01 | PH1 | EVD-01, EVD-02, EVD-04, EXT-02, EXT-03, OPS-09, SES-06, WSP-02, WSP-03, WSP-04, WSP-06, WSP-07 | Ops (fingerprint L1/L2, commit, salvage, reset, head, diff_stat, check, merge, read) with op keys; the op-host rule (write ops through the slot's writable step session at a detected turn end); session-shell and host-channel backends; fake and conformance tests. First PR of WSP-01 from SPK-04's draft. |
| K14 | Gate, question and budget elicitation payloads | SES-01 | PH0 | API-01, EXT-04, GTE-01, GTE-02, GTE-05, OPS-07, RUL-05, SES-05, SES-10, TLS-05 | Form payloads, stable ids, visit token, authored-outcome mapping, gate-context block, reserved batch-gate payload, hidden decline and cancel, resolver identity, typed not_permitted, re-publish rule. |
| K15 | Rule-template catalog IR | RUL-03 | PH3 | ENG-09, RUL-06, WEB-06, WEB-09 | Template id, params, target builtin or policy, Required vs Guidance, per-mode enforceability inputs, bypass analysis. First PR of RUL-03; bundles reserve the guardrails slot in K12 from PH0. |
| K16 | Seam ledger format | OPS-01 | PH0 | BRD-01, BRD-03, FND-01, FND-02, FND-03, FND-05, GTE-05, HRN-01, HRN-08, OPS-02, SES-02, TLS-01 | seams.yaml and upstream.yaml: seam id, files, CORAL(Sx) anchors, tests, budget lines and exceptions, upstream-first flag, upstream PR link, owner feature. |
| K17 | Server plugin registration and process map | FND-02 | PH1 | DUR-02, DUR-04, DUR-06, FND-04, RUL-01, SES-03, TLS-01 | One server_plugins key; PluginRegistration (routers, lifespan hooks, policy modules merged before load_registry, status observers, elicitation observers and verdict handlers, server tool handlers, required-policy providers, account callbacks, seed agents); fatal import failure; ensure_coral_schema first; runner and host entry points; the coral_runner:n host capability token. |
| K18 | Status-edge observer API and turn facts | SES-01 | PH0 | ENG-11, HRN-03, HRN-05, HRN-07, SES-02, SES-08 | Observer signature, optional origin defaulting to 'unknown', turn_outcome (S43), persisted TurnFact fields. Schema in PH0; SES-02 and SES-08 implement. |
| K19 | Alert and inbox feed model | SES-01 | PH0 | API-01, DUR-05, ENG-06, ENG-09, GTE-02, GTE-03, GTE-04, GTE-06, TLS-05 | Alert kinds (gate, question, pause, watchdog, run completed, failed, cancelled), ack, auto-resolve, run actions, secret-free deep links. Schema in PH0; GTE-06 implements. |
| K20 | Host workspace-op wire frames | WSP-02 | PH3 | EVD-04, EXT-02, OPS-09, WSP-03, WSP-04, WSP-07 | Frames, workspace_ops:1 capability token, op catalog, job events and journal, reaper-guard rule. First PR of WSP-02, frozen at M2 with security sign-off; K13 carries a draft appendix from PH1. |
| K21 | Effect executor registry | DUR-01 | PH1 | DUR-04, DUR-05, GTE-01, GTE-03, GTE-06, PRF-01, SES-03, SES-04, SES-05, SES-06, SES-10, WSP-06 | Executor signature per effect kind, result-to-EffectCompleted/EffectFailed mapping, transient/permanent/infra error classes, retry and backoff owned by the drainer, per-kind idempotency obligations (derived id, read-before-resend, deterministic policy id), lease renewal; fake drainer and conformance test from DUR-04. |

## 2. Features by phase

Header: `workstream · phase · milestone · priority · size · enabler|slice · planned weeks`. **G** gap rows; **S** seams owned; **Hard / Soft** dependencies; **Slices** named slice dependencies; **K+** produced, **K-** consumed; **In / Out** scope; **Paths** coarse repo paths; **OQ** open questions that block or shape it; **If** conditional dependencies; **Proof** the test or demo that proves it done.

### PH0 Decisions, contracts and spikes (weeks 0-3, alongside early PH1)

**SPK-01 Decision records: week-1 set and threat-model checkpoint** — OPS · PH0 · M1 · Critical · S · enabler · wk 0-1  
By the end of week 1, record signed decisions or recorded defaults for every TLD and every open question that gates the M1 contracts, and run a threat-model checkpoint whose findings shape the K6, K12 and K14 freeze.  
Owner: Tech lead with the PM; WS-OPS hosts the records.  
In: Sign-off on TLD-01..21 and on the TLD conditions and milestone moves recorded in this roadmap; minimum NFRs (OQ-1): supported host OSes (macOS seatbelt, Linux with bwrap; Windows refused for sandboxed steps), max concurrent runs and agents, latency; engine semantics that freeze K1, K2 and K14: gate outcomes and reject routing (OQ-3), owner-only gate authority (OQ-4), blocked-exit routing (OQ-12), step agents asking the user (OQ-13), the D6 back-arrow join rule (OQ-19); product defaults for M1: hero stays a plain session composer with Coral copy through M4 (OQ-7, option a), workflow ids (OQ-8), naming and Powered-by (OQ-27, OQ-30, R-2), storage (OQ-33); namespace and Coral gate (OQ-45, OQ-36); merge cadence every two weeks with a rotating owner (OQ-50); dev-DB exception (OQ-53); CODEOWNERS (OQ-54); threat-model checkpoint: S49 tool provenance (OQ-43), the native bridge bearer (D25), runner-local impersonation (spike 15), gate authority, bundle secrets and provider-reference auth, the host-op token.  
Out: M2-M3 questions and external answers (SPK-05); the M2 security review itself (OPS-06).  
Paths: `docs/coral/decisions/`, `docs/coral/THREAT_MODEL.md`  
OQ: OQ-1, OQ-3, OQ-4, OQ-7, OQ-8, OQ-12, OQ-13, OQ-19, OQ-27, OQ-30, OQ-33, OQ-36, OQ-43, OQ-45, OQ-50, OQ-53, OQ-54  
Proof: By the end of week 1, docs/coral/decisions/ holds a signed or defaulted record for each listed OQ and TLD, and THREAT_MODEL.md names the contract each finding constrains.

**SPK-05 Decision records: M2-M3 set and external answers** — OPS · PH0 · M2 · Critical · S · enabler · wk 1-2  
By week 4, record signed decisions or defaults for the questions that gate M2 and M3 features, with deadlines and fallbacks for the answers Coral does not control.  
Hard: SPK-01  
Owner: Tech lead with the PM.  
In: Gate reminders and run expiry (OQ-5); watchdog default (OQ-14); cost-backstop default (OQ-15); estimate presentation (OQ-16); end-of-run output (OQ-18); product half of OQ-17: the run session is the run's one sidebar row, titled with the run name, filed into a 'Coral runs' project; phone scope for M2 gates and the run view (OQ-23); inbox-kind and promise-label visuals before PH2, the rest of OQ-24 later; success metrics and product events with ids and enums only (OQ-26, from product Q-36); M2 audience: internal dogfood or external; v1 harness modes (OQ-35) and rules and done-when v1 (OQ-38); naming and version scheme (OQ-49); bench budget and credentials (OQ-51) by the end of PH1; nightly soak threshold (default 9 of 10, each failure triaged); SQLite perf-smoke budgets; written vendor answer on claude-sdk and subscription auth (OQ-28) with a PH2-end deadline; fallback: claude-native ships on API key behind its flag and the M3 journey is rewritten; TLD-07 consequence signed: workflows with an orchestrator need an Anthropic API key through M4; 'Claude, not Claude Code' copy rule recorded with the OQ-28 answer; whether runs with gates may use claude-native steps at M3, given the agent-readable bridge bearer (D25).  
Out: Codex terms OQ-29 (decided before PH4 starts; blocks HRN-05); retention OQ-25 (decided before PH4 starts; blocks DUR-06); OQ-18 for the PR-review case (SES-10).  
Paths: `docs/coral/decisions/`  
OQ: OQ-5, OQ-14, OQ-15, OQ-16, OQ-17, OQ-18, OQ-23, OQ-24, OQ-26, OQ-28, OQ-35, OQ-38, OQ-49, OQ-51  
Proof: By week 4 each listed OQ has a signed or defaulted record; OQ-28 and OQ-51 records carry their deadline and fallback, and the M2 feature specs cite them.

**SPK-02 Session topology spike and ADR-05** — INTEGRATION · PH0 · M1 · Critical · M · enabler · wk 0-1 · two engineers, 1 calendar wk  
With two engineers for one calendar week, prove or reject TLD-02 option B in its anchor variant and record ADR-05 with the fallback costed.  
G: G-22  
In: Anchor variant: a turnless root run session that is never replaced, with the orchestrator and steps as own-runner children (children created with host_id, so is_independent holds, app.py:4594-4597); days 1-4, decides SES-03: (a) an own-runner claude-sdk child with its own worktree runs tools in its own cwd (spike 3); (b) the anchor hosts children; (c) an S51 prototype stops parent wakes; (d) stopping or replacing the orchestrator child spares its siblings; by week 2, feeds GTE-01, SES-06 and SES-09: (e) a gate elicitation on the anchor renders once in Inbox and /approve and still resolves when the anchor is omnigent.closed, plus the sidebar row and run-session page; (f) own-runner children can be relaunched after restart (upstream relaunches roots only, app.py:4273); spikes 14 (posts to archived sessions) and 15 (runner-local impersonation); ADR-05 picks the anchor variant and records the fallback (top-level family + S35 watch-set + engine-managed grants) at +3-4 eng-weeks.  
Out: Facade code (SES-03); the engine relauncher (SES-06); building the fallback (contingency only).  
Paths: `docs/coral/decisions/ADR-05-topology.md`, `spike branch only`  
OQ: OQ-32, OQ-17  
Proof: A scripted spike run demonstrates probes (a)-(f) on the anchor variant, and ADR-05 records each verdict with evidence.

**SPK-03 claude-sdk behaviour probes** — HARNESS · PH0 · M1 · Critical · S · enabler · wk 0-1  
In week 1, answer the claude-sdk unknowns that shape the M2 contracts and test lanes, each with a recorded verdict and a rerunnable probe.  
G: G-44  
In: Spike 4 first (days 1-2): a mock ANTHROPIC_BASE_URL drives claude-sdk deterministically, which decides the Tier B harness for E2E-1 and E2E-2; spike 1 can_use_tool under auto and bypass (decides S21); 2 Agent and Task unreachable; 7 MCP tool-call timeout (bounds the handoff scan and the watermark wait); spike 16 idle watchdog vs long turns (decides whether the S27 retest moves to M2); 19 local CredentialStore; 20 Smart Routing pin; verdict memo with a probe script per spike.  
Out: Native and Codex spikes: 5 and 6 run as RUL-04's first PR, 12 and 13 as HRN-05's first PR; bench code (HRN-08).  
Paths: `docs/coral/decisions/probes/`, `tests/harness_bench/probes/ (prototype only)`  
Proof: The verdict memo lists each spike with a rerunnable probe, marks S21 as needed or not, and states the Tier B harness choice.

**SPK-04 Workspace and evidence spike** — WORKSPACE · PH0 · M1 · Critical · S · enabler · wk 0-1  
Decide how M2 gets trustworthy fingerprints, commits and resets for a claude-sdk single writer without S40, and hand a draft K13 to WSP-01.  
G: G-38, G-59  
In: Spike 8 with the sandbox on: git add, commit and write-tree from a linked worktree whose gitdir is outside the sandbox; ops with no live session, and through a reviewer session with write_paths: []; runner /changes porcelain vs re-edits of already-dirty files; pick one L1 algorithm for per-command and submit-time digests; session-shell timeout and true exit codes (routes_resources.py:3257-3297); S71 reaper hazard repro (connect.py:1417-1423, 6027-6034); draft K13 interface and the op-host rule; contingency: if the session sandbox cannot commit or reset, the host-channel commit, reset and salvage ops move into WSP-06 in PH2 (+3 eng-weeks, WS-WORKSPACE owner).  
Out: Freezing K13 (WSP-01's first PR); building the host channel (WSP-02); spike 9 beyond a note.  
Paths: `docs/coral/decisions/SPK-04-workspace.md`, `coral/workspace/ops.py (draft)`  
OQ: OQ-39, OQ-44, OQ-10  
Proof: The spike report records each verdict with a rerunnable script, and the draft K13 names the backend each op uses at M2.

**FND-01 Coral package skeleton, import boundary and CLI entry** — PLATFORM · PH0 · M1 · Critical · S · enabler · wk 0-1  
Ship the coral package in the same wheel with a three-tier import boundary enforced per module and a bare coral console entry, so the contract packs can start on day two.  
G: G-12, G-85 · S: S29 · Soft: OPS-01 · K-: K16  
In: coral* in the wheel with package data for Coral Alembic files, templates and seed agents (S29); Tier (a) pure: coral.model, coral.validate, coral.engine, coral.evidence.ir and .evaluate, coral.rules.catalog, coral.workspace.ops; they import only stdlib, pydantic, pyyaml and other pure modules; Tier (b) coral.omni is the only importer of omnigent.*, split into coral.omni.server, .runner and .host, with every Omnigent private routed through coral/omni/_upstream.py; tier (c) coral.db may import an explicit allowlist of omnigent.db helpers; everything else (coral.api, stores, queue, workers, gates, tools.handlers, cli) imports pure modules, coral.db and coral.omni protocols only; enforced per module by dev/lint; coral = 'coral.cli:main' with an empty click group; spike 10 (no dependency ships a top-level coral name).  
Out: Tooling roots and CODEOWNERS (FND-05); data-dir isolation and update identity (OPS-03); alembic env (FND-03).  
Paths: `pyproject.toml`, `coral/__init__.py`, `coral/cli.py`, `coral/omni/_upstream.py`, `dev/lint/coral_boundary.py`, `tests/coral/test_import_boundary.py`  
Proof: tests/coral/test_import_boundary.py fails a pure module that imports coral.omni or omnigent and a non-omni module that imports omnigent, and a built wheel runs coral --help.

**FND-05 Tooling roots and coral CI group** — OPS · PH0 · M1 · High · S · enabler · wk 1-2  
Give coral its lint, type, coverage, pre-commit and CODEOWNERS roots and a coral CI group so every later PR runs the same gates as Omnigent.  
G: G-12 · S: S39, S39b, S39c, S39d, S39e, S76 · Hard: FND-01 · Soft: OPS-01 · K-: K16  
In: pyrefly, isort, coverage, lint and pre-commit regex roots for coral/ (S39, S39b-e); CODEOWNERS for coral/ and docs/coral/; coral group in python-matrix.json; just mod coral (S76) with just coral::test.  
Out: Fork guard (OPS-01); test lanes (FND-04).  
Paths: `pyrefly.toml`, `.pre-commit-config.yaml`, `.github/CODEOWNERS`, `.github/scripts/ci/python-matrix.json`, `justfile`, `coral/coral.just`  
OQ: OQ-54  
Proof: A PR touching coral/ runs pyrefly, lint and coverage in the coral CI group and requests review from the CODEOWNERS entry.

**OPS-01 Seam ledger and coral-fork-guard** — OPS · PH0 · M1 · Critical · M · enabler · wk 0-2  
Make every upstream-file edit ledgered, anchored, budgeted and tracked to its upstream PR from the first Coral PR.  
G: G-83 · K+: K16  
In: First PR in week 1: .coral/seams.yaml seeded with the S29, S39 and S76 entries and the guard in warn-only mode; it becomes a required check once seeded; .coral/upstream.yaml pinned at nightly^1; seams.yaml holds S1-S89 and sub-ids with owners from this roadmap, an upstream-first flag and the upstream PR link; coral/fork/check_seams.py: allowed roots, CORAL(Sx) anchors, line budgets with explicit exceptions for the Modify-class seams (S43, S6b, S14, S40, S72, S62), commit prefix, stale entries; reports every 'Up: Yes' seam that has no upstream PR yet; MODIFICATIONS.md generation; temp-git tests.  
Out: Merges and rehearsal (OPS-02); licence texts (OPS-02).  
Paths: `.coral/seams.yaml`, `.coral/upstream.yaml`, `coral/fork/`, `.github/workflows/coral-fork-guard.yml`, `MODIFICATIONS.md`  
OQ: OQ-50, OQ-54  
Proof: coral-fork-guard fails a PR that edits an upstream file without a ledger entry and anchor, passes once both exist, and lists landed 'Up: Yes' seams that lack an upstream PR.

**ENG-01 Engine contracts pack** — ENGINE · PH0 · M1 · Critical · M · enabler · wk 1-3  
Publish the workflow schema and IR (K1), reducer contract (K2) and run-log schema (K3) as typed, versioned modules with golden and compiled-IR fixtures, frozen at IM-0.  
G: G-01, G-03, G-05 · Hard: FND-01, SPK-01 · Soft: SPK-04 · K+: K1, K2, K3  
In: K1: authoring models and node taxonomy (Note layout-only, hidden Wait and Sub-workflow), reserved ids and EGM keys (D4), the done_when authoring block whose compiled form is K11; K1: frozen CompiledGraph with an Analysis section (regions, join types, loop table, decision label sets, checked parts); the content hash covers the canonical authoring document, never derived fields; K2: transition and a pure reconcile(graph, state, facts, now) -> inputs signature; ScopeKey on every input, effect, timer and log entry (TLD-21); effect_key and idempotency keys; session_generation; StartRun(from_node, carried); K2: slot states including closing and post_close_activity; closed pause-reason list with resume-condition kinds (user, failure_path, infra, plan_limit, auth, budget, rejected_calls, liveness, drift, authority_revoked, engine_upgrade); error taxonomy (infra.transient, plan.usage_limit, plan.spend_cap, auth); K3: closed additive log kinds, 16 KiB body cap and a RunView patch per entry (schema in K8); ir_version, state_version and log_version with the rule that build N reads N-1; I1-I8 as executable property checks; golden and compiled-IR fixtures for the MVP template, the D§5.6 example and a deadlock.  
Out: Loader and compiler (ENG-02); reducer logic (ENG-04); table layout (DUR-01).  
Paths: `coral/model/`, `coral/engine/types.py`, `coral/engine/log.py`, `coral/engine/invariants.py`, `docs/coral/contracts/`  
OQ: OQ-3, OQ-12, OQ-19  
Proof: JSON Schema goldens match the fixtures, every fixture round-trips through the type modules, and the I1-I8 checks run against a hand-built trace.

**SES-01 Integration contracts pack** — INTEGRATION · PH0 · M1 · Critical · M · enabler · wk 1-3  
Freeze the Omnigent-facing contracts (facade, tools, identity, bundles, gate payloads, status edges, alerts) with a FakeOmni so engine, tool, gate and profile work runs in parallel.  
G: G-18, G-25, G-51 · Hard: FND-01, SPK-01, SPK-02 · Soft: ENG-01 · K+: K4, K6, K10, K12, K14, K18, K19 · K-: K2  
In: K4 coral.omni protocols: topology-independent methods at IM-0, create, access and watch sections right after ADR-05; CreateSession.role; send is not idempotent, so callers read before resend; K4 sub-protocols, each naming its implementer: access (FND-02), artifacts (DUR-02), scopes (DUR-04), usage (API-02), harness accounts (HRN-02), observations (EVD-02), request-free runner shell (WSP-06), sessions (SES-03, SES-04), gates (GTE-01); in-memory FakeOmni and a K4 conformance suite parameterized over FakeOmni and the real facade (the real side switches on when SES-03 lands); K6 six TLD-20 tool schemas, result envelope {accepted, reason, allowed_values, next} plus 'evaluation in progress', rejection codes, (run, operation_id) dedup, params.coral opt-in keys (TLD-04); K10 coral.* labels with coral.role (run, orchestrator, step), uuid5(effect_key) ids, stable_id per message, deterministic policy ids, worktree paths keyed (run, node, item_path, agent), coral_gate_ and coral_question_ ids, coral__ and coral. prefixes; K12 bundle format including the inert anchor agent, guardrails slot and provider-reference auth (WS-HARNESS co-authors); K14 gate, ask_user and budget payloads with a gate-context block (handoff report ref, evidence summary, open findings, diff stat, why-here), a reserved batch-gate payload, resolver identity and a typed not_permitted reason; K18 status-edge observer signature with optional origin defaulting to 'unknown', turn_outcome and TurnFact fields; K19 alert kinds, ack, auto-resolve, actions and secret-free deep links.  
Out: Implementations (SES-02..04, SES-08, TLS-*, GTE-01, GTE-06, PRF-01).  
Paths: `coral/omni/protocols.py`, `coral/omni/fake.py`, `coral/tools/schemas.py`, `coral/identity.py`, `coral/omni/bundle_format.py`, `tests/coral/omni/conformance/`, `docs/coral/contracts/`  
OQ: OQ-3, OQ-4, OQ-37, OQ-43, OQ-47  
Proof: FakeOmni passes the K4 conformance suite, and the tool, bundle, gate, status-edge and alert schemas match their JSON Schema goldens.

**API-01 Coral API and run-stream contracts** — PLATFORM · PH0 · M1 · Critical · S · enabler · wk 1-2  
Publish the /v1/coral/* OpenAPI (K7) and run-stream protocol (K8) with a drift check, generated TS types and stub routers so web work starts in PH1.  
G: G-74, G-75 · Hard: FND-01, SPK-01 · Soft: ENG-01, SES-01 · K+: K7, K8 · K-: K1, K14, K19  
In: Endpoint list incl. info with a sub-feature map, inbox, run outcome and spend estimate; error envelope, ETag/412, start_key, access through the run session; coral/api/dump_openapi.py --check and a drift test (the upstream dump omits extra_routers); generated TS types; MSW fixtures and stub routers; K8: SSE RunView snapshot then seq-numbered entries, each with the server-computed row patch (the client never re-implements the reducer); Last-Event-ID resume, heartbeat, [DONE], polling fallback.  
Out: Real handlers (DUR-02, API-02, GTE-06); Web stream client (WEB-04).  
Paths: `coral/api/openapi.json`, `coral/api/dump_openapi.py`, `web/src/workflows/api/generated/`, `docs/coral/contracts/run-stream.md`  
OQ: OQ-45  
Proof: The OpenAPI drift test fails on an unregenerated change, and the web build type-checks against the generated client and MSW fixtures.

### PH1 Foundations (week 0 to M1; some features target M2)

**FND-02 Server plugin seam, plugin registration and Coral gate** — PLATFORM · PH1 · M1 · Critical · M · enabler · wk 1-3  
Enable Coral with one server_plugins key that registers everything the server must load, fails startup on any import error, and gates the product with GET /v1/coral/info.  
G: G-17, G-81 · S: S32 · Hard: FND-01, SPK-01 · Soft: OPS-01, API-01, FND-03 · K+: K17 · K-: K16, K7, K4  
In: K17 PluginRegistration: routers, lifespan hooks, policy modules merged into load_registry before it runs (fatal if they fail to import), status observers (S1), elicitation observers and verdict handlers (S5, S6b), server tool handlers (S10), required-policy providers (S52), account callbacks (S56), seed agents from package data; K17 process map: runner entry points (S50 provider, S68 observer), host entry points (S40b), and the coral_runner:n host capability token advertised when they load; lifespan runs ensure_coral_schema first and a migration failure aborts startup; routers mount before the SPA; hooks start after the scheduler and stop before the runner router closes; spike 11; refuse to start only for detectable host sharding (host_sharded); the single active worker replica comes from DUR-04's DB lease; coral.omni.server.plugin with ServerServices and the K4 access adapter (auth principal, run-session access check); GET /v1/coral/info with a sub-feature map: editor, canvas_edit, claude_native_steps, codex_steps, webhooks, budgets, takeover, restart_from_node, profiles_desk.  
Out: Workflow and run endpoints (DUR-02, API-02); workers (DUR-04); S33 upstream flag.  
Paths: `omnigent/server/app.py`, `omnigent/cli.py`, `coral/omni/server/plugin.py`, `coral/api/info.py`, `tests/server/test_app.py`  
OQ: OQ-36  
Proof: tests/server/test_app.py plugin cases: routers mount before the SPA, hook order holds, a broken plugin or coral.omni.policies import aborts startup, a plugin-registered policy passes bundle validation without a policy_modules key, and /v1/coral/info returns the sub-feature map.

**FND-03 Coral DB environment and migration ordering** — PLATFORM · PH1 · M1 · Critical · M · enabler · wk 1-3  
Give Coral its own Alembic chain and CoralBase, bound to the operational database only, that always migrates after Omnigent reaches head on all four backends.  
G: G-13 · S: S30, S31, S57, S58 · Hard: FND-01 · Soft: OPS-01 · K-: K16  
In: coral/db base, types, ids, enum codecs and migrate; coral_alembic_version; CoralBase on its own DeclarativeBase bound to the operational engine, never the optional conversation database; ensure_coral_schema strictly after Omnigent head with newer-build, D1-refusal and CockroachDB SERIALIZABLE guards; never create_all; env.py include_name filter (S30); truncation keeps every *alembic_version and skips coral_* in root truncation (S31); deploy entrypoint runs Coral migrations (S57); shared cursor and enum helpers (S58); single-head, round-trip, SQLite-safe, ordering and engine-binding tests on SQLite, Postgres, CockroachDB and MySQL.  
Out: Tables (DUR-01 and each owning feature); create_all (never used).  
Paths: `coral/db/`, `coral/db/migrations/`, `omnigent/db/migrations/env.py`, `tests/conftest.py`, `deploy/databricks/src/app.py`, `omnigent/db/enum_codecs.py`  
OQ: OQ-42, OQ-54  
Proof: A fresh DB and an upgrade both reach Omnigent head then Coral head on all four lanes, and with conversation_database_uri set CoralBase still binds to the operational engine.

**FND-04 Coral test infrastructure** — OPS · PH1 · M1 · High · M · enabler · wk 3-5  
Give every Coral feature its DB-lane fault tools, a split-DB lane and Tier B E2E scaffolding on the harness spike 4 picks.  
G: G-87 · Hard: FND-01, FND-03, FND-05 · Soft: SES-01, SPK-03, FND-02 · K-: K4, K17  
In: tests/coral lane map and conftests; Coral-aware SQLite template; commit-boundary fault-injection and contention helpers for the DB lanes (tests/stores/coral); Split-DB lane: SQLite operational DB plus a separate SQLite conversation DB; Tier B scaffolding: mock LLM and a step bundle scripted to call engine tools, on claude-sdk against the mock Anthropic Messages endpoint if spike 4 passes; tests/e2e/coral/conftest.py inherits tests/e2e fixtures and skips when the pinned runner or host lacks the coral_runner token; a Tier B case with a host missing the token.  
Out: I1-I8 property harness (ENG-01, ENG-04); journeys (SES-05, OPS-07); live bench (HRN-08).  
Paths: `tests/coral/`, `tests/stores/coral/`, `tests/e2e/coral/conftest.py`, `coral/coral.just`  
OQ: OQ-52  
If: If spike 4 fails: Tier B uses an explicit test-only openai-agents mode (turn-end rule in ENG-11, K9 row in HRN-01, bundle in PRF-01) and lists the M2 exit criteria that lane cannot prove  
Proof: A sample commit-boundary fault test runs green on the four lanes and the split-DB lane, a Tier B sample drives a scripted engine-tool call, and tests/e2e/coral skips against an old pinned runner.

**OPS-02 Upstream merges, fork CI hygiene and licence basics** — OPS · PH1 · M1 · High · M · enabler · wk 2-4  
Merge upstream for real from nightly^1 every two weeks from PH1, rehearse daily, keep inherited CI safe, and ship the NOTICE addendum and licence inventory.  
G: G-84, G-86 · S: S77 · Hard: OPS-01 · Soft: FND-03, FND-04, SES-03 · K-: K16, K4  
In: Real merges from nightly^1 on the OQ-50 cadence (default every two weeks) with rerere; a rotating merge owner (0.25-0.5 FTE) and a merge-day budget per team (TLD-17); daily trial merge with a per-seam conflict report; scripted regeneration of uv.lock, pnpm-lock, openapi.json, palette CSS, coral/api/openapi.json, web/src/workflows/api/generated/ and the K1 JSON Schema; Coral suites L0-L2 on SQLite, Postgres and CockroachDB, MySQL tested, plus the split-DB lane; the K4 conformance suite over FakeOmni and the real facade joins as L3 once SES-03 lands; Coral joins the server-compat review; secret-using inherited workflows (R-19) and desktop builds disabled until BRD-03; branch protection; NOTICE append-only addendum (S77); licence job blocks only new direct dependencies by diffing against the upstream lock; the inherited elkjs is recorded for counsel under OQ-30.  
Out: Release merge drill, security cherry-pick lane and driving upstream PRs to merge (OPS-05); counsel sign-off (OPS-05).  
Paths: `.github/workflows/coral-upstream-rehearsal.yml`, `NOTICE`, `docs/coral/UPSTREAM_MERGES.md`, `coral/fork/licences.py`, `coral/fork/regenerate.py`  
OQ: OQ-50, OQ-30  
Proof: By M1 at least two real merges from nightly^1 have landed with all Coral lanes green, and the daily trial job posts a green or per-seam conflict report.

**OPS-03 Distribution identity and coexistence** — OPS · PH1 · M2 · Medium · S · slice · wk 5-6  
Give the coral command its own data and config dirs and update identity so Coral and Omnigent coexist on one machine.  
G: G-85 · S: S75 · Hard: FND-01 · Soft: SPK-05  
In: The coral entry (FND-01) sets OMNIGENT_DATA_DIR and OMNIGENT_CONFIG_HOME to ~/.coral; update check disabled or pointed at Coral (S75); coral/version.py; isolation test: no writes to ~/.omnigent and no newer-DB lockout; coral/CLAUDE.md dev-DB exception once OQ-53 is approved; cut candidate if M2 stays internal.  
Out: Console entry point (FND-01); desktop identity (BRD-03); renaming omnigent internals.  
Paths: `coral/cli.py`, `coral/version.py`, `omnigent/update_check.py`, `coral/CLAUDE.md`  
OQ: OQ-49, OQ-53  
If: If SPK-05 records an external M2 audience: no cut line, and this is part of the M2 release gate  
Proof: An isolation test runs coral and omnigent side by side with separate dirs, no shared files and no lockout.

**DUR-01 Persistence contract, core schema and migration train** — PLATFORM · PH1 · M1 · Critical · M · enabler · wk 3-5  
Publish the persistence contract (K5) and effect executor registry (K21), land the core engine tables as coral_0001, and run the migration train every later table goes through.  
G: G-14 · Hard: FND-03, ENG-01 · Soft: SES-01 · K+: K5, K21 · K-: K2, K3, K4  
In: K5 first PR: conventions (workspace_id leading PK, derived-id PKs, Uuid16, CHECKed enums, CompressedText cap, no FKs, scope-key columns); Coral tables on the operational DB only, Omnigent ids as plain indexed columns, no joins or shared transactions with conversation tables; K5 store protocols (apply_transition CAS, workflow store, queue claim/lease/finish) and the queue and timer layout decided here (OQ-34); at-least-once semantics; K21 in the same PR: executor signature, result-to-observation mapping, transient/permanent/infra error classes, retry owned by the drainer, per-kind idempotency obligations, lease renewal; coral_0001_core: workflows, versions, drafts, runs with engine_version, run specs, activations, join arrivals, slots with session_generation and closing state, handoffs and items, gate visits, run log with its RunView patch, simulation cases, blob refs; migration train: each later table is its owner's standalone coral_00NN_<feature> PR; single-head and models-match checks on four lanes plus the split-DB lane; train-order table in docs/coral/contracts/persistence.md.  
Out: Queue and timer tables (DUR-04); integration tables (each owning feature); store code (DUR-02, DUR-03, DUR-04).  
Paths: `coral/db/models/`, `coral/db/migrations/versions/`, `coral/stores/protocols.py`, `coral/queue/executors.py`, `docs/coral/contracts/persistence.md`  
OQ: OQ-34  
Proof: Models-match-migrations and single-head tests pass on four lanes and the split-DB lane, and every run table carries the scope-key columns.

**DUR-02 Workflow library: store, versions, API and CLI** — PLATFORM · PH1 · M1 · Critical · L · slice · wk 5-9.5  
Store workflows DB-canonically as drafts plus immutable content-addressed versions and serve them, with validate and simulate, through /v1/coral and the coral CLI (TLD-06).  
G: G-14, G-15, G-66, G-68, G-74 · Hard: FND-01, DUR-01, FND-02, ENG-02, API-01 · Soft: ENG-03, ENG-07 · K-: K5, K1, K7, K17, K4  
In: Drafts with ETag/412; immutable versions; library index with stable workflow ids (OQ-8); blob key scheme coral/v1/{ws}/..., put-then-commit, coral_blob_refs ledger, size caps; implements the K4 artifacts adapter over ArtifactStore; /v1/coral/workflows CRUD, version freeze, :validate and :simulate endpoints; saved simulation cases; coral workflow upload resolving the server URL from the active config, tested under two config homes.  
Out: Repo import (WSP-01); repo export (EXT-03); delete with runs (DUR-06); UI (WEB-02).  
Paths: `coral/stores/workflows.py`, `coral/stores/blobs.py`, `coral/omni/server/artifacts.py`, `coral/api/workflows.py`, `coral/cli.py`  
OQ: OQ-8, OQ-9, OQ-33  
Proof: API test: uploading the template returns a version hash, a broken copy returns yaml_path-anchored problems, and simulate returns a deterministic trace; the CLI upload works under both config homes.

**DUR-03 Run store with CAS transitions** — PLATFORM · PH1 · M2 · Critical · M · slice · wk 5-7  
Commit each reducer transition's state, log with RunView patches, effects and receipts atomically under an optimistic run version on every lane.  
G: G-14, G-07 · Hard: DUR-01, FND-04 · Soft: ENG-04 · K-: K5, K2, K3  
In: Idempotent start_run via start_key; apply_transition writes state delta, log entries with their RunView patches, effects and receipts in one short transaction; reduce-and-retry on version conflict (run_write_transaction retries only 40001/1213); contention and commit-boundary tests on four lanes; join-once and duplicate-signal contention cases.  
Out: Queue and workers (DUR-04); purge (DUR-06).  
Paths: `coral/stores/runs.py`, `tests/stores/coral/test_run_store.py`  
Proof: Two concurrent transitions on one run yield one winner and a reducer re-run, with fold(log) == state and stored patches matching the fold, on all four lanes.

**DUR-04 Durable work queue, effect drainer and workers** — PLATFORM · PH1 · M2 · Critical · L · enabler · wk 5-9.5  
Own an at-least-once queue for signals, timers and effects with leases and idempotency keys, run by one active worker replica (TLD-08).  
G: G-11, G-25 · Hard: DUR-01, FND-02 · Soft: DUR-03, ENG-06 · K-: K5, K17, K2, K21, K4  
In: coral_0002_queue: queue and timer tables in the K5 layout, as this feature's first PR; effect drainer implementing K21 with a fake drainer and the conformance test every executor feature runs; lock-and-recheck claims, renew, finish, backoff; delete on apply; enqueue off the event-loop thread; drainer and timer scan started by the plugin lifespan; DB-level worker lease (StartupLease pattern) so only one replica runs Coral workers, tested with two app instances on the Postgres lane; never PersistentTaskScheduler (R-4); implements the K4 scopes adapter: workers enter workspace, account-authority and host-owner scopes; dispatch-time re-validation; SQLite perf smoke: five concurrent mock runs record SQLITE_BUSY counts and p95 transition latency against the SPK-05 budget.  
Out: Reconcile and resync (DUR-05); multi-replica sharding (deferred).  
Paths: `coral/queue/`, `coral/workers/`, `coral/omni/server/scopes.py`, `tests/stores/coral/test_queue.py`  
OQ: OQ-42  
Proof: A worker killed after claim releases its lease and the effect runs exactly once more with the same idempotency key, and a second app instance never runs workers while the lease is held.

**ENG-02 Loader, compiler, analysis and content hash** — ENGINE · PH1 · M1 · Critical · M · slice · wk 3-5  
Turn workflow YAML into the frozen, hashed IR with its Analysis section and source marks, so every error and every derived fact points at a box or arrow.  
G: G-01, G-03 · Hard: ENG-01 · K-: K1  
In: Safe-load with source marks and a yaml_path-to-range map; stable and reserved ids; compile to the frozen IR; content hash over the canonical authoring document; analysis: join types (AND-join after a split vs merge of alternatives), regions, loop table, decision label sets and checked parts; JSON Schema export wired into the web build; golden test reproduces ENG-01's compiled-IR fixtures.  
Out: Validation rules (ENG-03); comment-preserving edits (WEB-11).  
Paths: `coral/model/loader.py`, `coral/model/compile.py`, `coral/model/analysis.py`, `tests/coral/model/`  
OQ: OQ-8  
Proof: The MVP template compiles to ENG-01's fixture IR and hash, its Analysis matches the golden, and moving a key moves the reported error range.

**ENG-03 Static validator** — ENGINE · PH1 · M1 · Critical · M · slice · wk 5-7  
Report V1-V7 and V10-V13 problems with box-anchored, plain explanations over the compiled IR and its Analysis.  
G: G-02, G-03 · Hard: ENG-02 · K-: K1  
In: V1-V7 and V10-V13 with plain explanations; V10 against configured harnesses; block-structure soundness instead of exhaustive V11 (X-25, R-24); back-arrow exemption from join arity (D6); V12 activation upper bound as a cost backstop; invalid drafts savable but not runnable (OQ-9).  
Out: Derivations (ENG-02); V8 (ENG-09); V9 (RUL-06); exhaustive enumeration (deferred).  
Paths: `coral/validate/`, `tests/coral/validate/`  
OQ: OQ-9, OQ-19  
Proof: Each rule has a failing fixture with the expected yaml_path and message, and the MVP template validates clean.

**ENG-04 Reducer core and run log** — ENGINE · PH1 · M1 · Critical · L · slice · wk 3-5.5 · two engineers, 2.5 calendar wk  
Implement the pure transition() for runs, activations, slots, attempts, decisions and gate visits, emitting log entries with RunView patches, keyed effects and rejections, with fold(log) == state.  
G: G-04, G-05, G-03, G-34 · Hard: ENG-01 · Soft: ENG-02, ENG-03 · K-: K1, K2, K3  
In: State machines for Run, Activation, Slot (incl. closing and post_close_activity), Attempt, Decision request and Gate visit; illegal-transition tables; rejections never throw; A slot completes only when its session has no engine-known pending input; handoffs and decision requests carrying legal labels and the per-agent handoff collection (D9); gate visits with visit tokens, stale-visit rejection and authored outcome labels (R-7); log emission with RunView patches, fold and receipts; I1-I8 seeded fuzz harness; skeleton slice (start -> step -> gate -> end) merged by IM-1; staffed by two engineers.  
Out: Loops, joins and failure paths (ENG-05); lifecycle and timers (ENG-06); reconcile and turn-end rule (ENG-11); repeat and parallel (ENG-08).  
Paths: `coral/engine/reducer.py`, `coral/engine/machines/`, `coral/engine/projection.py`, `tests/coral/engine/`  
OQ: OQ-3, OQ-12  
Proof: Seeded fuzz over the fixtures holds fold(log) == state, patch-fold == projection and I1-I8, and the skeleton fixture walks start -> step -> gate -> end through the closing state.

**ENG-05 Loops, joins and failure paths** — ENGINE · PH1 · M1 · Critical · M · slice · wk 5.5-7.5  
Make back-arrows, at-limit routes, joins, failure paths and blocked exits behave exactly as the validator explains.  
G: G-04, G-03 · Hard: ENG-02, ENG-04 · Soft: ENG-03 · K-: K1, K2, K3  
In: Back-arrow counters keyed by iteration_path; at_limit routing with open findings; join arrivals unique per (activation, arrow, scope); merge of alternatives; arrow.skipped; attempts and failure path with paused(failure_path) for attempts_exhausted and blocked; liveness pause; runtime activation cap.  
Out: Dead-path elimination beyond OQ-19; region cancel (ENG-08).  
Paths: `coral/engine/control.py`, `tests/coral/engine/test_loops_joins.py`  
OQ: OQ-12, OQ-19  
Proof: A scripted reducer test routes changes requested x3 to the at-limit gate with open findings, and a blocked exit follows the failure path.

**ENG-06 Run lifecycle, timers and liveness policies** — ENGINE · PH1 · M2 · Critical · M · slice · wk 7.5-9.5  
Add start, pause, resume, cancel and retry commands, the K2 pause reasons and timer policies to the reducer so runs advance without babysitting.  
G: G-06, G-07, G-34 · Hard: ENG-04 · Soft: ENG-05 · K-: K2, K3, K19  
In: start_key to derived run id; every K2 pause reason with its resume condition; resume on the pinned version; cancel effect chain interrupt -> stop -> omnigent.closed (R-13) and late-submit rejection; retry step; Auto-advance; decision watchdog (remind once, then a K19 alert) with a configurable default (OQ-14); rejected-call pause (3 in a row per slot); gate reminders and escalation that never auto-resolve (OQ-5); overdue timer kind; coalescing after laptop sleep.  
Out: Effect execution (DUR-04 and executor features); budget pause from run budgets (RUL-05); reactions (ENG-09).  
Paths: `coral/engine/lifecycle.py`, `coral/engine/timers.py`  
OQ: OQ-14, OQ-13, OQ-5  
Proof: Reducer tests: pause, resume, cancel and retry transitions for every pause reason; the watchdog fires once then alerts; three rejected calls pause the slot; a gate reminder never resolves the gate.

**ENG-11 Reconcile, turn-end and failed-turn decision functions** — ENGINE · PH1 · M2 · Critical · M · slice · wk 7-9  
Make recovery level-triggered and testable by putting reconcile, the per-mode turn-end rule and failed-turn classification in pure functions over facts.  
G: G-11, G-21, G-23 · Hard: ENG-04 · Soft: ENG-06, HRN-01 · K-: K2, K18, K9  
In: reconcile(graph, state, facts, now) -> inputs over TurnFacts, session status, runner_last_seen, pending elicitations and effect leases; per-mode turn-end rule over TurnFacts, claude-sdk first: idle, engine input consumed, assistant reply, no pending elicitation, no engine-known pending input; failed-turn classifier from failure_origin, ExecutorError class and error text to infra.transient, plan.usage_limit, plan.spend_cap, auth or agent failure; I7 property test: any permutation of signals plus one reconcile reaches the same state.  
Out: Fact gathering and scheduling (DUR-05, SES-08); S24 reset times (HRN-04); native turn-end facts (HRN-03, HRN-05).  
Paths: `coral/engine/reconcile.py`, `coral/engine/turn_end.py`, `coral/engine/classify.py`, `tests/coral/engine/test_reconcile.py`  
If: If spike 4 fails: add a test-only openai-agents turn-end rule for Tier B  
Proof: The I7 property test is green, and table tests cover the claude-sdk turn-end rule and the 529, 429 and 401 classes.

**ENG-07 Simulate engine, saved cases and MVP template** — ENGINE · PH1 · M1 · Critical · M · slice · wk 7.5-9.5  
Run the reducer with stub effects over scripted scenarios, save cases that re-run per version, and ship the TLD-01 template with saved simulations and user-facing parameters.  
G: G-66, G-69, G-62 · Hard: ENG-04, ENG-05 · Soft: ENG-06, EVD-01 · K-: K1, K2, K3  
In: Scripted labels, list lengths, pass/fail and gate answers; K3-shaped traces; saved cases re-run on each new version; session-count estimate; "Implement with review loop" template (TLD-01) as package data with a done_when block, declaring the loop limit, reviewer models and the gate's reject route as parameters.  
Out: Exhaustive mode (deferred); Simulate UI (WEB-01, WEB-12); PR-review template (SES-10).  
Paths: `coral/engine/simulate.py`, `coral/templates/implement_review_loop.yaml`, `tests/coral/simulate/`  
OQ: OQ-2, OQ-9  
Proof: Saved cases approved, changes requested x3 -> at-limit gate, and gate reject re-run deterministically on a new template version and with the loop limit changed to 2.

**EVD-01 Evidence-requirement IR and evaluator** — WORKSPACE · PH1 · M1 · High · M · enabler · wk 3-5  
Define the compiled evidence IR and observation records (K11) and a pure evaluator with final-pass-after-last-change semantics, using SPK-04's L1 algorithm.  
G: G-40 · Hard: ENG-01, SPK-04 · Soft: WSP-01 · K+: K11 · K-: K1, K13  
In: Compiled form of K1's done_when block: required commands, may-modify flags, exit-code source rules, per-agent vs per-step scope; observation and fingerprint records; a per-session observation watermark (last ingested tool-result item seq); rule: an observation is durable before the tool result returns to the agent; pure evaluator returning pass, missing items, or 'evaluation in progress' while the watermark lags; tests over temp git repos.  
Out: Capture (EVD-02); detection (EVD-03); Coral-run checks (EVD-04).  
Paths: `coral/evidence/ir.py`, `coral/evidence/evaluate.py`, `tests/coral/evidence/`  
OQ: OQ-10  
Proof: Formatter-then-test passes, test-then-edit fails with 'tests predate the last change', and a lagging watermark yields 'evaluation in progress', not 'missing'.

**HRN-01 Capability registry contract and claude-sdk row** — HARNESS · PH1 · M1 · High · S · enabler · wk 1-2  
Publish the capability registry (K9) with a host-sandbox dimension and verified claude-sdk values, so M2 labels and the turn-end rule read real data.  
G: G-44 · S: S22 · Hard: FND-01 · Soft: SPK-03, OPS-01 · K+: K9 · K-: K16  
In: K9 fields, enums, CapabilityMatrix and effective-enforceability inputs keyed by (harness spelling, host sandbox backend: seatbelt, bwrap, none); fill steering, live_queue and compaction and add the ten G-44 fields (S22); claude-sdk values from SPK-03 verdicts, other modes 'unknown'; guard tests in tests/test_harness_capabilities.py.  
Out: Other modes' values, S59, bench and feature-map rows (HRN-08); label computation (RUL-02, RUL-06).  
Paths: `omnigent/harness_capabilities.py`, `omnigent/harness_plugins.py`, `coral/harness/registry.py`, `tests/test_harness_capabilities.py`  
If: If spike 4 fails: add a test-only openai-agents row  
Proof: tests/test_harness_capabilities.py guard tests pass with the new fields, and the K9 matrix returns verified claude-sdk values and 'unknown' elsewhere.

**RUL-01 Coral policies, run guard and cost backstop** — INTEGRATION · PH1 · M2 · Critical · M · slice · wk 3-5  
Hold rosters, orchestrator limits and paused or cancelled runs by policy, not by prompt, and cap per-session cost with a visible pause before run budgets exist.  
G: G-45, G-46, G-62 · S: S52 · Hard: FND-02 · Soft: SES-01, DUR-03, SPK-05 · K-: K10, K12, K17, K2  
In: coral.omni.policies registered through K17: step_roster, orchestrator_guard, engine_tool_guard, input-scope deny (internal_only) (R-3); spec grants spawn: false and tools.agents: []; S52 required-policy provider in builder.py (one line) keyed on coral.run_id, an O(1) no-op for other sessions: DENY non-coral_* tools while paused or cancelled; state lives in labels or the run store, never closures, because /mcp rebuilds the policy engine on every call; per-session cost_budget backstop (OQ-15 default, no soft ASK, skipped for unpriced models, D34); its DENY becomes a reducer observation and paused(budget) whose copy names the per-session cap.  
Out: Rule catalog (RUL-03); run budgets (RUL-05); S26 reserved names (EXT-04).  
Paths: `coral/omni/policies/`, `omnigent/runtime/policies/builder.py`, `tests/runtime/policies/`  
OQ: OQ-15  
If: If spike 1 fails: hard on HRN-02's S21 PreToolUse hook for claude-sdk enforcement  
If: If SPK-02 probe (e) shows a closed anchor no longer resolves elicitations: add the anchor input DENY keyed on coral.role=run  
Proof: tests/runtime/policies/: a paused run's step is denied a non-coral tool across a per-call engine rebuild, a non-Coral session is unchanged, and a backstop DENY pauses the run as paused(budget).

**SES-02 Seam pack A: status-edge observers and engine dispatch** — INTEGRATION · PH1 · M2 · Critical · M · enabler · wk 1-3  
Land the upstreamable session seams as one-line registry calls: status-edge observers with optional origin and turn outcome, and in-process engine dispatch.  
G: G-19, G-20 · S: S1, S43, S4, S41, S42 · Hard: FND-01 · Soft: OPS-01, FND-02 · K-: K16, K18  
In: S1 observer registry in session_live_state.py; the scheduled hook becomes one observer; notify after the sticky-failed return; bypasses B1 (relay turn-end) and B2 notify; origin is an optional keyword defaulting to 'unknown', set only at the relay turn end, the status-probe notify, the archive idle edge and the runner-disconnect edge (full S1b goes upstream via OPS-05); S43 turn_outcome on headless runner edges and relay pass-through (upstream-first; covered by the coral_runner token); S41 keeps the _post_event_impl handle; S42 EngineEventContext (S4 realized); upstream PR for S1 opened at landing.  
Out: Coral observer and TurnFacts (SES-08); S1b full origin slugs (OPS-05); S2 (HRN-05); S44 (not planned).  
Paths: `omnigent/server/session_live_state.py`, `omnigent/server/routes/_sessions/helpers.py`, `omnigent/server/routes/_sessions/orchestration.py`, `omnigent/server/routes/sessions/routes_events.py`, `omnigent/server/app.py`, `omnigent/runner/app.py`  
OQ: OQ-41  
Proof: tests/server/test_session_live_state.py: an observer sees every edge with origin set at the four sites and 'unknown' elsewhere; tests/server/integration/test_engine_event_dispatch.py: an EngineEventContext message, interrupt and stop pass input policy.

**TLS-01 Seam pack B: engine tool transport** — INTEGRATION · PH1 · M2 · Critical · M · enabler · wk 1-3  
Land the extension tool provider and server tool registry so one declaration registers, forwards and instructs coral_* tools on headless runners, and advertises the host token.  
G: G-26, G-27 · S: S50, S7, S8, S10, S12, S49 · Hard: FND-01 · Soft: SES-01, SES-02 · K-: K6, K12, K16, K17  
In: omnigent/tools/extensions.py provider (entry-point loaded) feeding ToolManager registration (S7) and runner forwarding (S8), each one line; an O(1) no-op unless params.coral or coral.run_id is present; S12: a FrameworkInstructions value at the prompt.py composition boundary with ordered, owner-tagged entries from S50 providers; the existing two entries unchanged; Coral text in coral.omni.runner; server_tools.py registry with ServerToolCall (operation id, actor, provenance) added beside the sys_advise_models intercept; that migration ships only in the upstream PR (S10); S49 runner-provenance predicate; the provider contributes coral_runner:n to HostHelloFrame.capabilities through one ledgered line in host/frames.py (under S50); coral_ prefix with collision error; (run, operation_id) transport dedup; upstream PRs for S10, S12 and S50.  
Out: Handlers (TLS-02, TLS-03, TLS-05); native relay, pre-approval and launch channels (HRN-03, HRN-05).  
Paths: `omnigent/tools/extensions.py`, `omnigent/tools/manager.py`, `omnigent/runner/tool_dispatch.py`, `omnigent/server/server_tools.py`, `omnigent/runtime/prompt.py`, `omnigent/host/frames.py`, `coral/omni/runner/tool_provider.py`  
OQ: OQ-43  
Proof: tests/server/routes/test_sessions_mcp_proxy_policy_retry.py and tests/runner/test_scheduled_task_tool_dispatch.py: a schema-only coral_ test tool is registered, forwarded and deduplicated, its text appears after the two existing prompt entries, and the host hello advertises coral_runner:1.

**GTE-05 Seam pack C: elicitation observers, request-free publish and verdict handlers** — INTEGRATION · PH1 · M2 · Critical · M · enabler · wk 1-3  
Land the elicitation seams in PH1 against ordinary sessions, so gate work in PH2 never waits on hot-file review.  
G: G-35 · S: S5, S6, S6a, S6b · Hard: FND-01 · Soft: SES-02, FND-02 · K-: K16, K14  
In: S5 elicitation observers as a list with per-observer isolation (pending_elicitations.py); S6a request-free publish with caller-supplied stable ids (routes_events.py, one line into a helper module); S6b verdict-handler registry that passes resolver identity to handlers (orchestration.py, upstream-first); ELICITATION_RESOLVE_LEVEL unchanged; upstream PRs for S5 and S6 opened at landing.  
Out: Coral gate rows, context and authority (GTE-01); Inbox kind (GTE-02).  
Paths: `omnigent/runtime/pending_elicitations.py`, `omnigent/server/routes/sessions/routes_events.py`, `omnigent/server/routes/_sessions/orchestration.py`, `omnigent/server/elicitation_hooks.py`  
Proof: tests/runtime/test_pending_elicitations.py, test_subagent_block_notifier.py and tests/server/integration/test_sessions_elicitation_api.py: a request-free elicitation with a stable id resolves once, a failing observer does not block others, and a handler receives resolver identity.

**WSP-05 S71 reaper guard for host fs operations** — WORKSPACE · PH1 · M2 · Critical · S · enabler · wk 1-2  
Stop the host reaper from stealing exit statuses of fs_request and fs_write subprocesses, the host-path exit codes that import and detection trust (TLD-10).  
G: G-38 · S: S71 · Hard: FND-01 · Soft: OPS-01  
In: Reaper guard on fs_request and fs_write (connect.py:1417-1423, 6027-6034); exit-status test in tests/host/test_connect.py that reproduces the hazard; upstream PR (bug fix) opened at landing; states that runner-path exit codes are covered by EVD-02's test, not by S71.  
Out: Runner-path exit codes (EVD-02); host op channel (WSP-02).  
Paths: `omnigent/host/connect.py`, `tests/host/test_connect.py`  
Proof: tests/host/test_connect.py reproduces a reaped exit status without the guard and passes with it.

**WSP-01 Repo bindings, run worktree and WorkspaceOps contract** — WORKSPACE · PH1 · M2 · Critical · M · slice · wk 5-7  
Freeze K13, bind repos, and create or adopt each run's worktree request-free, with repo import and a host sandbox report.  
G: G-58, G-68 · S: S72 · Hard: SPK-04, WSP-05, DUR-01, SES-01 · Soft: SES-03 · K+: K13 · K-: K4, K10, K5  
In: First PR: K13 v1 from SPK-04's draft (fingerprint L1/L2, commit, salvage, reset, head, diff_stat, check, merge, read), op keys, the op-host rule (write ops only through the slot's current writable step session at a detected turn end; read ops in any session with os_env), session-shell and host-channel backends, fake, conformance tests; coral_00NN_repo_bindings migration (host, repo root, traits) and binding API; deterministic coral/r-<run>/base created request-free and adopted on retry; paths keyed (run, node, item_path, agent); start commit recorded; S72 head_commit and optional worktree_parent, feature-detected through the host hello, falling back to git rev-parse through the session shell; sessions bound with workspace= and no git options, with an invariant test (S73 stays unneeded); repo import via host fs_request read (TLD-06); host sandbox report (platform, FS sandbox backend, bwrap present) computed in coral.omni.host and advertised with the coral_runner token.  
Out: Commit, salvage, reset and retention (WSP-06); S72 detached mode (EVD-04); per-agent worktrees (WSP-03); host op channel (WSP-02).  
Paths: `omnigent/host/git_worktree.py`, `omnigent/host/frames.py`, `omnigent/server/routes/_host_worktree.py`, `coral/workspace/ops.py`, `coral/workspace/fake.py`, `coral/omni/host/`, `docs/coral/contracts/workspace-ops.md`  
OQ: OQ-39, OQ-44  
Proof: tests/host/test_git_worktree.py and test_frames.py: create_worktree returns head_commit, an old host falls back to rev-parse, a retry adopts the same worktree, a repo import yields the expected content hash, and the K13 fake passes conformance.

**EVD-03 Repository command detection and confirmation** — WORKSPACE · PH1 · M2 · High · M · slice · wk 7-9  
Detect test, lint, format and typecheck commands in a bound repo, let the author confirm them, and snapshot them into the workflow version.  
G: G-41, G-42 · Hard: DUR-01, SES-01, WSP-05 · Soft: EVD-01, WSP-01 · K-: K4, K11, K5  
In: Parsers for package.json, pyproject.toml, justfile and Makefile, read request-free via host fs_request; coral_00NN_command_patterns migration; per-repo patterns; confirm API; confirmed commands snapshotted into the workflow version (X-32); picker backend (TLD-19).  
Out: CI-file and pre-commit parsers (EVD-04); LLM translation (deferred); picker UI (WEB-03).  
Paths: `coral/evidence/detect.py`, `coral/api/repos.py`, `tests/coral/evidence/fixtures/`  
OQ: OQ-38  
Proof: Detection over fixture repos returns the expected commands, and confirming them snapshots into a new version.

**EVD-02 claude-sdk evidence capture and done-when at handoff** — WORKSPACE · PH1 · M2 · Critical · M · slice · wk 5-7  
Record each claude-sdk command's exit code and the workspace state after it before the agent sees the result, and evaluate done-when at handoff (TLD-10).  
G: G-38, G-39, G-40 · S: S68, S69 · Hard: EVD-01, SPK-04, DUR-01, WSP-05 · Soft: WSP-01, SPK-03, TLS-01 · K-: K11, K13, K6, K4, K5  
In: S68: observer fan-out at the top of pr_observer.observe_tool_completion, before its 'if not successful' return, so none of the four call sites change; S69(a) only: runner /mcp/execute response field plus the server TOOL_RESULT hook, writing the observation synchronously; implements the K4 observations adapter; coral_00NN_observations migration: command observations with command, exit code and L1 fingerprint, evidence results, watermark; one L1 algorithm per command and at submit (never bare /changes porcelain); runner-path exit-status preservation test; missing-item feedback through TLS-02.  
Out: S69(b) outbox transport and native sites (HRN-03); L2 and the host backend (WSP-02, WSP-07); Coral-run checks (EVD-04).  
Paths: `omnigent/runner/pr_observer.py`, `omnigent/runner/mcp_routes.py`, `omnigent/server/routes/_sessions/orchestration.py`, `coral/omni/runner/observer.py`, `coral/evidence/capture.py`  
OQ: OQ-10  
Proof: A claude-sdk step that edits after running tests is rejected at handoff and accepted after re-running, and an immediate submit after a test run sees the observation.

**HRN-02 claude-sdk credential guard and run preflight engine** — HARNESS · PH1 · M2 · Critical · M · slice · wk 3-5  
Start run-owned claude-sdk sessions only on API-key or provider auth pinned per run, and own the preflight engine that names every fix before a run starts (TLD-07).  
G: G-54, G-76 · S: S13, S63, S21 · Hard: SPK-03, SES-01, HRN-01 · Soft: PRF-01, SPK-05, WSP-01 · K-: K12, K9, K4  
In: Spawn-env flag and executor refusal of subscription OAuth for run-owned sessions (S13); provider references only, never literal keys; operator bindings respected; implements the K4 harness-accounts adapter; account pinned per run; S63 contract test that no vendor workspace tools are exposed; S21 PreToolUse hook only if spike 1 fails; spikes 19 and 20 applied; preflight engine: V10 configured harnesses, auth, host online, coral_runner token, FS sandbox for read-only or path-rule steps (fail fast when bwrap is missing), validity, estimate; each failure carries a fix target; honest copy: workflows with an orchestrator need an Anthropic API key through M4.  
Out: Preflight endpoint (API-02); claude-native subscription path (HRN-03); model-access settings and plan-limit pauses (HRN-04).  
Paths: `omnigent/runtime/workflow.py`, `omnigent/inner/claude_sdk_harness.py`, `omnigent/inner/claude_sdk_executor.py`, `coral/omni/server/preflight.py`  
OQ: OQ-28  
Proof: A run with only subscription credentials is refused at preflight and at spawn, and a host without bwrap or without the coral_runner token fails preflight with its fix.

**PRF-01 Step bundles, seeded agents and hidden engine rows** — HARNESS · PH1 · M2 · Critical · L · slice · wk 5-9.5  
Run every step from a generated, content-addressed agent pinned by digest, seed the Coral built-ins, keep engine rows out of pickers, and make claude-sdk reviewers read-only by sandbox (TLD-05).  
G: G-47, G-50, G-51, G-52, G-32 · S: S54 · Hard: SES-01, DUR-01 · Soft: RUL-01, DUR-04 · K-: K12, K10, K21, K5  
Secondary load: WEB 0.5 wk.  
In: coral.omni.server.bundles deterministic tar; uploaded_agent_for content-addressed rows; coral_00NN_step_agents migration; materialize as a K21 executor; seeded built-ins pinned by digest: the inert anchor (no tools, no os_env), orchestrator (carrying TLS-03's instructions), implementer and reviewer; slot-start drift check (spike 18); hygiene: tool groups off, spawn: false, skills none for hermetic steps, agent_session_sharing none, vendor ask tools including AskUserQuestion denied; provider-reference auth; required policies in bundle guardrails; reviewer os_env.sandbox.write_paths: [] plus read_only_os (R-23); S54 picker and scope=user exclusion for coral__ rows in the store and web hooks; golden bundle tests.  
Out: User profile revisions (PRF-02); desk (WEB-07); S53 mutation guards (EXT-04).  
Paths: `coral/omni/server/bundles.py`, `coral/profiles/seeds/`, `omnigent/stores/agent_store/sqlalchemy_store.py`, `omnigent/server/routes/builtin_agents.py`, `web/src/hooks/useAvailableAgents.ts`  
OQ: OQ-37, OQ-48  
If: If spike 4 fails: add a test-only openai-agents step bundle  
Proof: tests/stores/test_agent_store.py: coral__ rows are absent from scope=user; the same step yields the same digest across runs; a reviewer write is denied by the sandbox.

**SES-03 Session facade: anchor, request-free create and topology** — INTEGRATION · PH1 · M2 · Critical · L · slice · wk 3-7.5  
Create the run anchor and its own-runner children idempotently without an HTTP request, in the ADR-05 topology, proven against both FakeOmni and the real facade.  
G: G-18, G-22, G-25 · S: S51 · Hard: SPK-02, SES-01, FND-02 · Soft: DUR-01, PRF-01, DUR-04, RUL-01 · K-: K4, K10, K12, K17, K21, K5  
In: Anchor: one per run, created first, never briefed, coral.role=run, the inert seeded agent; titled with the run name and filed into a 'Coral runs' project via the fire.py project filing pattern; anchor input stance: omnigent.closed if probe (e) holds, otherwise RUL-01's role-keyed DENY; no session policies on the anchor, step policies on leaf sessions only; orchestrator and steps as own-runner children (created with host_id); S51 parent-wake exemption (omnigent.parent_wake: off); fire.py-subset create: validators, uuid5(effect_key) ids through the store (R-9), unique titles, presentation labels, policies before input, launch and init; coral_00NN_session_bindings migration; create registered as a K21 executor; refuse to place run sessions on hosts that lack the coral_runner token; workspace= with no git options; unattended-permission preflight; privates only through coral/omni/_upstream.py; K4 conformance green on FakeOmni and the real facade; L3 signature snapshots; idempotency tests on the split-DB lane; skeleton slice (create one step child under an anchor) merged by IM-2.  
Out: Dispatch (SES-04); turn-end facts (SES-08); fallback build (contingency); S55 (not planned).  
Paths: `coral/omni/server/sessions.py`, `omnigent/runtime/subagent_block_notifier.py`, `tests/coral/omni/conformance/`, `tests/coral/omni/contract/`  
OQ: OQ-32, OQ-17, OQ-47  
If: If SPK-02 rejects option B: +3-4 weeks for the top-level family fallback; S35 moves from not planned to this feature  
Proof: The K4 conformance suite passes on FakeOmni and the real facade; creating the same effect twice yields one session on the split-DB lane; the facade row matches an HTTP-created row except for allowed fields.

**SES-04 Engine dispatch: brief, steer, interrupt, stop and close** — INTEGRATION · PH1 · M2 · Critical · M · slice · wk 3-5  
Send every engine message through _post_event_impl exactly once in effect, and close a step session safely after its handoff is accepted.  
G: G-19, G-07 · Hard: SES-01, SES-02 · Soft: SES-03, DUR-04, WSP-06 · K-: K4, K2, K5, K21, K10  
In: Brief, nudge, feedback, notice, interrupt and stop via _post_event_impl with stable_id on every message; read before resend because send is not idempotent; always ensure_runner_connected before sending; ManagedStartupInputs fallback; coral_00NN_stable_ids migration; dispatch registered as K21 executors; close sequence on an accepted handoff: closing -> turn end (interrupt after a bound) -> engine commit (WSP-06) -> read the pending-input buffer -> stop -> omnigent.closed; A turn that starts after accept marks post_close_activity, re-fingerprints and pauses the run as paused(drift); cancel chain interrupt -> stop -> omnigent.closed; skeleton slice (brief and stop) merged by IM-2.  
Out: Turn-end facts and outcomes (SES-08); runner loss (SES-06); native turn ends (HRN-03, HRN-05).  
Paths: `coral/omni/server/dispatch.py`, `coral/slots/close.py`, `tests/coral/omni/test_dispatch.py`  
OQ: OQ-41, OQ-13  
Proof: A Tier B test queues user input during a turn that ends in a handoff: the slot closes after the commit, and the queued input either is refused or pauses the run as paused(drift); a repeated brief effect sends once.

**BRD-01 Coral brand skin** — BRAND · PH1 · M1 · High · M · slice · wk 0-2  
Make Coral look like Coral by default in light and dark, without disturbing existing heading users, while operator branding still overrides it.  
G: G-78, G-79 · S: S79, S81, S82, S83, S89 · Soft: OPS-01 · K-: K16  
In: omni palette slot data -> Clay Score light and dark, label Coral (TLD-16, X-21); status, chart, CTA and tag remap scoped to the default palette in web/src/brand/coral.css; regenerated palette CSS and updated CSS contract tests; --font-display (Newsreader, bundled offline); --font-heading untouched (R-15); CoralMark, CoralWordmark, CoralHero; BrandLogo fallback; the hero stays a plain session composer with Coral copy (OQ-7 option a); favicon, index.html, apple-touch icon; onboarding art replacing starfish and Otto; Powered-by per OQ-30 (R-1, R-2).  
Out: Sidebar brand row S80 (BRD-02); hero workflow chip (deferred, OQ-7 option b); native shells (BRD-03).  
Paths: `web/src/lib/themePalette.ts`, `web/src/themePalettes.generated.css`, `web/src/index.css`, `web/src/lib/branding.ts`, `web/src/components/BrandLogo.tsx`, `web/src/shell/NewChatDialog.tsx`, `web/src/brand/`, `web/index.html`  
OQ: OQ-7, OQ-30  
Proof: Vitest: index.css and palette contract tests pass with Coral tokens, and a stored omni preference renders Clay Score.

**BRD-02 Navigation shell, Coral gate and desk headers** — BRAND · PH1 · M1 · High · M · slice · wk 3-5  
Let users reach Workflows (and Agent Profiles once its desk exists) from the sidebar, palette and URLs, gated by /v1/coral/info and its sub-feature map, under one desk header.  
G: G-80, G-81 · S: S34, S80, S84 · Hard: FND-02 · Soft: BRD-01, API-01 · K-: K7  
In: coralRoutes(prefix) fragment with withPageView for /workflows, /workflows/runs/:runId, /workflows/:workflowKey and /profiles (spike 17); CoralGate reading /v1/coral/info and its sub-feature map (loading, disabled -> not found, error) instead of FeatureGatedPage; CoralPrimaryNavigation insert; the Agent Profiles entry stays hidden behind profiles_desk until WEB-07; sidebar brand row -> CoralWordmark (S80); useActiveNavItem exclusion; command palette actions; CoralPageHeader (list and full-bleed) with AccentRail on Inbox, Automations and the Coral desks (S84); ?agent= focus convention (R-17); a placeholder Workflows desk with empty states.  
Out: Desk content (WEB-*); S33 upstream flag.  
Paths: `web/src/App.tsx`, `web/src/shell/Sidebar.tsx`, `web/src/shell/CommandPalette.tsx`, `web/src/pages/InboxPage.tsx`, `web/src/pages/TasksPage.tsx`, `web/src/workflows/routes.tsx`, `web/src/brand/CoralPageHeader.tsx`  
OQ: OQ-27  
Proof: Vitest route tests: /workflows renders behind CoralGate, disabling Coral hides nav and returns not found, profiles_desk off hides Agent Profiles, and unknown routes no longer light New session.

**WEB-01 Read-only diagram, run overlay and preset Simulate** — WEB · PH1 · M2 · High · M · slice · wk 3-5  
Render any compiled workflow read-only through one xyflow adapter whose overlay Simulate and the run view share, and let authors run a template's saved simulations from the UI (TLD-14).  
G: G-71, G-67 · Hard: ENG-01 · Soft: ENG-02, API-01, BRD-02, ENG-07, DUR-02 · K-: K1, K7  
In: Standalone dependency PR: @dagrejs/dagre and a direct yaml dependency (2.9.0, already locked), mirror-checked; graph model from the compiled IR and its Analysis; one xyflow adapter folder; design taxonomy with Note layout-only; dagre layout in a worker (ELK behind legal); overlay API shared with the run view; Simulate button running saved and preset cases with visit counts, taken edges, limits and the estimate; analytics event 'simulate run'; states: loading, layout pending, parse error with last valid, too large, needs input, deadlock highlight, limit reached, failing saved case with expected vs actual path; vitest for graph model, layout and overlay mapping; render checks in the CI-only tests/browser_ui/workflows/ lane.  
Out: Scenario editor and saved-test badges (WEB-12); editing (WEB-08); ELK; run data (WEB-04).  
Paths: `web/src/workflows/model/`, `web/src/workflows/layout/`, `web/src/workflows/canvas/`, `web/src/workflows/simulate/`, `web/package.json`  
OQ: OQ-30  
Proof: Vitest layout tests render the MVP template graph model, and a preset simulation overlays visit counts that match the API trace.

**WEB-02 Workflows desk and library** — WEB · PH1 · M2 · High · M · slice · wk 5-7  
Let users find, open, upload and import workflows, see versions, last run and server problems, and know what the MVP template needs before they start.  
G: G-68, G-81, G-73 · Hard: BRD-02, API-01 · Soft: DUR-02, WEB-01 · K-: K7, K1  
In: /workflows tabs (Your workflows, Runs, Templates) with loading, empty, error and no-access states; the Runs tab hosts WEB-13's list; intro walkthrough and template copy: 'Needs: Anthropic API key, git repo with tests, connected host'; library list with versions and last run; upload and import actions; read-only YAML view with the server problem list; analytics events with ids and enums only (OQ-26).  
Out: YAML editing (WEB-11); runs list (WEB-13); retention setting (DUR-06); canvas (WEB-08).  
Paths: `web/src/workflows/desk/`, `web/src/workflows/library/`  
OQ: OQ-9, OQ-27, OQ-33  
Proof: Vitest: the desk lists uploaded workflows with versions, the problem list shows server problems for a broken version, and each state renders.

### PH2 Stateful engine and first end-to-end run (week 4 to M2; some features target M3 or M4)

**DUR-05 Reconciler and restart recovery** — PLATFORM · PH2 · M2 · Critical · M · slice · wk 9.5-11.5  
Make runs survive server restarts, lost edges and engine upgrades by gathering live facts and applying the pure reconcile at startup and on a periodic resync.  
G: G-11, G-16, G-87 · Hard: DUR-03, DUR-04, FND-04, ENG-11 · Soft: ENG-06, SES-08, GTE-01, SES-03, GTE-06 · K-: K2, K4, K5, K19, K21  
In: Startup reconcile, periodic resync and liveness checks: gather facts through K4, call ENG-11's reconcile, enqueue its inputs; re-lease expired effects; read before resend; trigger gate re-publish; stale runner_last_seen marks slots suspect; resync re-derives turn ends from persisted edge facts; alert on waiting-with-no-elicitation as a K19 alert; lazy authority checks with paused(authority_revoked) written as system; runs whose state or log version this build cannot read pause as paused(engine_upgrade) with cancel offered; commit-boundary fault suite on every lane and the split-DB lane.  
Out: Runner-loss restart ladder (SES-06); restart-from-node for upgraded runs (ENG-10); retention (DUR-06).  
Paths: `coral/reconcile/`, `tests/stores/coral/test_commit_boundaries.py`  
OQ: OQ-14  
Proof: A crash at each commit boundary recovers with no duplicate sessions, briefs, policies, worktrees or gate prompts on all lanes, and a run written with an unknown state_version pauses as paused(engine_upgrade).

**SES-08 Turn-end facts and failed-turn outcomes** — INTEGRATION · PH2 · M2 · Critical · M · slice · wk 9-11  
Record status edges as durable turn facts off the hot path, apply the pure turn-end rule, nudge only when it is safe, and turn failed turns into the right pause.  
G: G-20, G-21, G-23 · Hard: SES-02, ENG-11 · Soft: SES-03, SES-04, HRN-01, DUR-04 · K-: K18, K4, K5, K2, K9  
In: Coral status observer with an O(1) binding filter that enqueues TurnFacts off the hot path; persisted edge facts for resync; applies ENG-11's per-mode rule; nudges only engine-started turns, never cancelled ones; ignores archive idle edges; gathers failure_origin, ExecutorError and error text for the classifier: infra.transient -> backoff then paused(infra); auth -> paused(auth) and an alert; plan.* -> paused(plan_limit) with no reset time, polled with backoff; Tier B case where the mock LLM returns 529, then 429, then 401; SQLite perf smoke for edge-to-TurnFact lag against the SPK-05 budget.  
Out: S24 reset times (HRN-04); native turn-end facts (HRN-03, HRN-05).  
Paths: `coral/signals/`, `coral/omni/server/observers.py`, `tests/coral/omni/test_turn_facts.py`  
OQ: OQ-41  
Proof: Typing into a step session never triggers a nudge, an engine brief's turn end advances the slot exactly once, and 529, 429 and 401 map to backoff, paused(plan_limit) and paused(auth).

**SES-06 Runner-loss restart ladder** — INTEGRATION · PH2 · M2 · High · M · slice · wk 7.5-9.5  
When a runner or host is lost, hold with an explanation, then restart a step in a safe order that never resumes a zombie turn (TLD-12).  
G: G-23 · Hard: SES-03, DUR-03 · Soft: DUR-05, SES-04, WSP-06, SES-08 · K-: K4, K2, K13, K21  
In: Liveness from runner_last_seen; wake via ensure_runner_connected or retry_session; paused(infra) during the 72 h hold; never restart inside it; ladder: fence and stop the old generation, create the new generation without briefing, reconnect, salvage and reset through the new session's shell, then brief; engine relaunch of own-runner children after server restart (probe f).  
Out: Drift and user actions (SES-09); native /clear following (HRN-07); S48 (not planned).  
Paths: `coral/recovery/ladder.py`, `coral/recovery/relaunch.py`, `tests/coral/omni/test_recovery.py`  
OQ: OQ-17  
If: If spike 16 fails: this feature owns the S27 reaper retest at M2 (moved from SES-07)  
Proof: Killing the implementer's runner pauses the run as paused(infra); Resume creates generation N+1, salvages and resets before the brief; after a server restart the engine relaunches the children.

**SES-09 Drift detection and user actions on run sessions** — INTEGRATION · PH2 · M2 · High · M · slice · wk 7.5-9.5  
Detect policy, label and bundle drift and define what archive, delete, stop, fork and rename do to run sessions, including the anchor.  
G: G-24 · Hard: SES-03 · Soft: DUR-05, PRF-01, RUL-01, SES-04 · K-: K4, K2, K10  
In: Drift checks (policy, label, bundle digest) at resync and slot start, then re-attach or paused(drift); defined outcomes for archive, delete, stop, fork and rename on step, orchestrator and anchor sessions; archiving or deleting the anchor pauses the run with an explanation; spike 14 verdict applied (posts to archived sessions).  
Out: Reserved prefixes and mutation guards (EXT-04); native /clear following (HRN-07).  
Paths: `coral/recovery/drift.py`, `tests/coral/omni/test_drift.py`  
OQ: OQ-17, OQ-46  
Proof: A deleted run policy pauses the run within one resync and re-attach restores it, and archiving the anchor pauses the run with its explanation.

**SES-05 Walking skeleton** — INTEGRATION · PH2 · M2 · Critical · M · slice · wk 9.5-11.5  
Prove the thinnest end-to-end path early: a one-step workflow runs in a real session, submits, waits at a gate, is answered and ends, then survives a kill.  
G: G-87 · Hard: FND-04, SES-02, TLS-01, GTE-05, DUR-03, DUR-04, ENG-04 · Soft: SES-03, SES-04, TLS-02, GTE-01, DUR-05, SES-08 · Slices: SES-03#skeleton, SES-04#skeleton, TLS-02#skeleton, GTE-01#skeleton · K-: K2, K4, K6, K14, K21  
In: E2E-1 on Tier B: one-step workflow -> anchor plus step child -> coral_submit_handoff -> gate on the anchor answered via /approve -> end; built against the named skeleton slices of SES-03, SES-04, TLS-02 and GTE-01, with a burn-down list; kill-and-restart variant once DUR-05 lands; owns IM-2.  
Out: M2 journey and fault suite (OPS-07); Web UI (WEB-*); browser E2E.  
Paths: `tests/e2e/coral/test_skeleton.py`  
Proof: E2E-1 is green in the inherited e2e gate at IM-2, and the kill-and-restart variant is green once DUR-05 lands.

**TLS-02 coral_submit_handoff** — INTEGRATION · PH2 · M2 · Critical · M · slice · wk 7-9  
Accept or reject step handoffs with a bounded evidence check, slot-state dedup and generation fencing, with rejections the agent can act on.  
G: G-28 · Hard: TLS-01, ENG-04, DUR-03 · Soft: EVD-02, SES-04, SPK-03 · K-: K6, K2, K5, K11  
In: Fields: activation_id, status done|blocked, report, artifacts, derived label or items, kind handoff|refresh_note; schema check -> reducer command -> one short transaction; evidence check under a per-slot evaluating lease (X-15); waits within the spike-7 bound for the session's observation watermark to cover the submit's preceding item, else returns 'evaluation in progress', which never counts toward the rejected-call pause; rejection codes with reasons; per-slot rejected counter; session_generation check; receipts and slot-state dedup (X-5, R-10); accept moves the slot to closing; post-cancel submits rejected; skeleton slice merged by IM-2.  
Out: Coral-run checks (EVD-04); refresh_note handling (SES-07).  
Paths: `coral/tools/handlers/submit_handoff.py`, `tests/coral/tools/`  
OQ: OQ-12, OQ-10  
Proof: A duplicate submit returns the original receipt, a stale-generation submit is rejected, a submit before passing commands lists the missing items, and a submit racing its own observation is not rejected.

**TLS-03 Orchestrator decisions and coral_choose_arrow** — INTEGRATION · PH2 · M2 · Critical · M · slice · wk 5.5-7.5  
Let the orchestrator decide only through coral_choose_arrow on legal labels, interleaved with user chat, and keep its context when it restarts.  
G: G-29, G-32, G-33 · Hard: TLS-01, ENG-04, SES-01 · Soft: TLS-02, PRF-01, ENG-05, GTE-01, RUL-01, SES-04 · K-: K6, K12, K2  
In: Orchestrator instructions and decision-request rendering for PRF-01's seed (claude-sdk, no os_env); orchestrator_guard in bundle guardrails plus a label check in the handler (TLD-05, X-11); decision requests list legal labels and the handoff collection (D9); coral_choose_arrow with a generic label validated server-side, reason and optional items (R-11); chat interleaving with claude-sdk mid-turn buffering; user-induced illegal calls not counted; lazy creation; reminders re-check state; A restarted orchestrator is re-briefed with the pending decision request, a short run summary and prior decisions.  
Out: coral_ask_user (TLS-05); message and assign tools (TLS-04); orchestrator refresh (SES-07); seed packaging (PRF-01).  
Paths: `coral/tools/handlers/choose_arrow.py`, `coral/orchestrator/`  
OQ: OQ-13, OQ-14  
Proof: With a mock orchestrator, an illegal label is rejected with allowed_values, a legal one routes the loop, and a restarted orchestrator receives the pending request and run summary.

**TLS-05 coral_ask_user** — INTEGRATION · PH2 · M2 · High · M · slice · wk 9-11  
Let the orchestrator ask the user a question without blocking its turn, and deliver the answer back as a message.  
G: G-30 · Hard: TLS-01, GTE-01 · Soft: TLS-03, GTE-06 · K-: K6, K14, K19, K5  
In: coral_00NN_questions migration; durable question row; form elicitation on the anchor through GTE-01's path with coral_question_ ids; question alerts through GTE-06; [Coral answer] delivery as a message that suspends the watchdog; non-blocking; M2 cut candidate 1: if cut, steps report blocked and the orchestrator asks in chat.  
Out: Vendor AskUserQuestion denial (PRF-01 hygiene); step agents asking directly (OQ-13 default: no).  
Paths: `coral/tools/handlers/ask_user.py`, `tests/coral/tools/test_ask_user.py`  
OQ: OQ-13  
Proof: An ask_user call returns at once, its answer arrives as a [Coral answer] message, and the watchdog does not fire while the question is open.

**GTE-01 Coral gate surfacing and authority** — INTEGRATION · PH2 · M2 · Critical · M · slice · wk 7-9  
Surface durable gate visits as stable-id elicitations on the anchor with their context, route answers back once, and accept answers only from the run owner (TLD-09).  
G: G-35, G-34 · Hard: GTE-05, ENG-04, SES-01, DUR-03 · Soft: SES-03, SPK-02, RUL-02 · K-: K14, K4, K10, K2, K21  
In: Gate row written before publish; publish on the anchor with coral_gate_<visit> ids as a K21 executor; gate-context block (handoff report, evidence summary with missing items, open findings, diff stat, why-here) assembled into the elicitation message, so ApprovalCard, Inbox and /approve render it unchanged; CAS resolution with visit token; stale answers refused as no longer current; re-publish on startup and after runner loss; Coral's S6b verdict handler compares resolver identity with the run owner and returns a typed not_permitted; ELICITATION_RESOLVE_LEVEL unchanged; ask_user and budget forms on the same path; never policy ASK (R-7); the native bridge bearer (D25) is a RUL-02 gate-integrity input; skeleton slice (publish and resolve one gate) merged by IM-2.  
Out: Inbox kind (GTE-02); alerts (GTE-06); external delivery (GTE-03); team approvers (EXT-04).  
Paths: `coral/gates/`, `tests/server/integration/test_coral_gates.py`  
OQ: OQ-3, OQ-4, OQ-5  
Proof: An edit-shared teammate's answer is refused with not_permitted, a duplicate answer advances once, a stale answer is refused, and after a server restart the gate is re-published with the same id and context.

**GTE-06 Alerts backend and inbox API** — PLATFORM · PH2 · M2 · Critical · M · slice · wk 9.5-11.5  
Store run alerts durably with server-side ack and serve them as the Inbox workflow feed, resolving them when the thing they point at resolves.  
G: G-36 · Hard: DUR-01, FND-02, API-01 · Soft: DUR-04, GTE-01, ENG-06 · K-: K19, K7, K5, K21  
In: coral_00NN_alerts migration per K19; GET /v1/coral/inbox and POST .../ack with server-side ack (X-30); alert effects as a K21 executor; producers: gates, questions, pauses, watchdog; low-priority run completed, failed and cancelled alerts auto-acked when the run is opened; alerts auto-resolve when the visit or question resolves; deep-link payloads without secrets.  
Out: Inbox card and notifications (GTE-02); webhook and email (GTE-03).  
Paths: `coral/alerts/`, `coral/api/inbox.py`, `tests/coral/api/test_inbox.py`  
Proof: A gate alert appears in the feed, acking it on one client clears it on another, and answering the gate resolves the alert.

**GTE-02 Workflow Inbox kind and run notifications** — WEB · PH2 · M2 · Critical · M · slice · wk 5-7  
Show each gate, question and pause once in the Inbox with its context and run actions, and notify once at run level while the app is open.  
G: G-36 · S: S36, S37, S85 · Hard: BRD-02 · Soft: GTE-06, GTE-01, API-02, WEB-04 · K-: K7, K14, K10, K19  
In: Inbox-kind registry that InboxPage.tsx spreads in one line, after BRD-02's S84 edit (S37); kinds can claim id prefixes; WorkflowInboxCard is canonical for coral_gate_ and coral_question_ ids; the generic approval collector and the elicitation OS notification skip them; step prompts from run-owned children show as 'Step waiting on you' deep-linking /workflows/runs/:id?agent=; card states: submitting, answered by X elsewhere, stale visit, no longer waiting, waiting for the run owner, only the run owner can answer, offline, waiting N hours, phone width; run actions (open, resume, cancel, extend); sidebar count; CoralRuntimeProvider mount (S85); S36 suppresses per-step turn-end notifications; 'app must be open' notice (TLD-09, R-6); uses WEB-04's shared roster-chip and harness-label component; analytics event 'gate answered'; vitest card-state tests plus a CI-only browser lane row.  
Out: Alert storage (GTE-06); webhook and email (GTE-03); push (GTE-04); localStorage read state.  
Paths: `web/src/pages/InboxPage.tsx`, `web/src/hooks/useIdleNotifications.ts`, `web/src/main.tsx`, `web/src/workflows/inbox/`  
OQ: OQ-24, OQ-6, OQ-23  
Proof: One gate yields one card, one OS notification and a count of 1; acking on one client clears another; no per-step turn-end notification fires for run sessions.

**WSP-06 Session-shell workspace ops: commit, salvage, reset and retention** — WORKSPACE · PH2 · M2 · Critical · M · slice · wk 7-9  
Commit accepted work before a step session stops, salvage and reset before retries, and keep worktrees bounded, all through the K13 session-shell backend.  
G: G-59, G-58 · Hard: WSP-01, SES-01 · Soft: SES-03 · K-: K13, K4, K21  
In: K13 session-shell backend over K4's request-free runner shell call (contract-tested); enforces the op-host rule; engine commit with trailers in the closing state before stop (hook policy OQ-39); diff_stat(start_commit, head) computed then and stored with the handoff; salvage refs refs/coral/salvage/*; reset --hard and clean -fd before retry; ops registered as K21 executors; worktree removal, retention and disk cap.  
Out: Host-channel backend (WSP-02, WSP-07); per-agent worktrees (WSP-03).  
Paths: `coral/workspace/session_shell.py`, `coral/omni/server/runner_shell.py`, `tests/coral/workspace/`  
OQ: OQ-18, OQ-39  
If: If spike 8 fails: the host-channel commit, reset and salvage ops move from WSP-02 into this feature in PH2 (+3 weeks, WS-WORKSPACE)  
Proof: A commit made in the closing state contains every accepted edit and none after; a retry salvages to refs/coral/salvage/* and resets to the step start commit; deleting a run session leaves the branch intact.

**API-02 Runs API, gate answers, outcome, spend and run stream** — PLATFORM · PH2 · M2 · Critical · L · slice · wk 7-11.5  
Serve runs, lifecycle actions, gate answers, preflight, the run outcome and spend so far, and tail the run as a resumable stream of server-computed patches.  
G: G-74, G-75, G-76, G-07, G-34, G-62 · Hard: DUR-01, DUR-03, API-01 · Soft: DUR-02, ENG-06, SES-03, HRN-02, GTE-01, WSP-06 · K-: K7, K8, K3, K4  
In: Runs list, get and idempotent start with start_key; pause, resume, cancel and retry actions; gate answers with visit_token; preflight endpoint calling HRN-02's engine; run-outcome resource: branch, start and head commits, commit list, files changed, salvage refs; spend so far as an estimate through the K4 usage adapter (load_session_usage and _sum_subtree_usage over the run tree), tokens where a model is unpriced (D21); SSE RunView snapshot then entries with their stored patches, seq, Last-Event-ID, heartbeat and [DONE]; access through the run session.  
Out: Take-over endpoints (SES-07); amendments (ENG-10); run budgets (RUL-05).  
Paths: `coral/api/runs.py`, `coral/api/stream.py`, `coral/omni/server/usage.py`, `tests/coral/api/`  
OQ: OQ-4, OQ-16  
Proof: Reconnecting the stream with Last-Event-ID loses no entries, a repeated start with the same start_key returns the same run, and the outcome resource lists the run's commits and salvage refs.

**WEB-11 YAML editor** — WEB · PH2 · M2 · High · M · slice · wk 7-9  
Let users edit workflows in YAML with live server markers and comment-preserving saves (TLD-15).  
G: G-70, G-73 · Hard: WEB-02 · Soft: DUR-02 · K-: K7, K1  
In: Monaco YAML pane via monacoSetup helpers plus the yaml npm CST; markers and problem list from the server validator only; save with the 412 conflict dialog; dirty guard; golden round-trip fixtures; merges dark behind the editor sub-feature key; M2 cut candidate 2 (fallback: read-only YAML, upload and template parameters); vitest for marker ranges and CST patches; Monaco checks in the CI-only browser lane.  
Out: Canvas (WEB-08); MonacoCodeEditor reuse.  
Paths: `web/src/workflows/editor/`, `web/src/shell/monacoSetup.ts`  
OQ: OQ-9  
Proof: Vitest: server markers map to the right range and saving round-trips comments unchanged; the CI browser lane shows the 412 dialog on a concurrent edit.

**WEB-03 Templates, Use-template and start-run dialogs** — WEB · PH2 · M2 · Critical · L · slice · wk 7-11.5  
Take a new user from the gallery to a simulated workflow on their repo with confirmed done-when commands, then start a run behind a preflight that names every fix.  
G: G-69, G-42, G-76 · Hard: WEB-02 · Soft: DUR-02, EVD-03, API-02, WSP-01, PRF-01, ENG-07, HRN-02, RUL-02, WEB-04 · K-: K7, K11  
In: Gallery card with a promise summary and 'Needs:' line; Use-template dialog with name, repo, model per role and the template's parameters (loop limit, reviewer models, gate reject route); detected-command picker and confirmation sheet stored as K11 (TLD-19); start-run dialog: request, host, repo and base via WorkspacePickerDialog and useHostWorktrees, version pin, estimate, activation cap, per-session cost cap; preflight errors that name each fix; auth failures deep-link to the existing HarnessFixDialog API-key form; idempotent start; states: gallery failed, host offline, nothing detected; analytics events 'template used' and 'run started'; built against K7 MSW fixtures.  
Out: Money budgets (RUL-05); profile picker (WEB-07); LLM translation (deferred).  
Paths: `web/src/workflows/templates/`, `web/src/workflows/start/`  
OQ: OQ-2, OQ-16, OQ-18  
Proof: Vitest with MSW: Use template on a fixture repo shows the detected commands, confirming saves a version, and a failing auth preflight links to the API-key form.

**WEB-04 Live run view** — WEB · PH2 · M2 · Critical · L · slice · wk 5-9.5  
Let users see where a run is, why it went that way, what passed and what it waits on, live, without reading a transcript.  
G: G-77, G-75 · Hard: WEB-01, API-01 · Soft: API-02, GTE-01, EVD-02, RUL-02 · K-: K7, K8, K3  
In: First PR: shared roster-chip and harness-label component ('Claude', not 'Claude Code', for SDK-mode agents; the vendor name only for claude-native) with a unit test, reused by WEB-03, WEB-05 and GTE-02; stream client that applies server patches with id: parsing, stream-slot acquisition and polling fallback; header with lifecycle actions and spend so far (estimate); state overlay with loop counters and open gates; inspector tabs (step, decision reason, gate with its full context, log); evidence list; timeline; pause banners from a reason-to-copy table with resume condition and actions, one fixture test per K2 reason; Retry copy says uncommitted work is salvaged to refs/coral/salvage/*; states: loading, error with retry, not found or no access, reconnecting, waiting for the run owner; accessibility baseline: keyboard and screen-reader access to the timeline, step list and gate panel, with an axe check in the CI-only browser lane.  
Out: Runs list, outcome panel, guarantees panel and phone layout (WEB-13); agent panes and steering (WEB-05); structure layers (WEB-10).  
Paths: `web/src/workflows/runs/`, `web/src/workflows/stream/`, `web/src/workflows/shared/RosterChip.tsx`  
OQ: OQ-17, OQ-23  
Proof: Vitest against a recorded run log: the view shows the loop counter, the open gate with context and evidence, every pause reason's copy, and resumes after a dropped stream with no gaps.

**WEB-13 Runs list, outcome, guarantees panel and phone layout** — WEB · PH2 · M2 · Critical · M · slice · wk 9-11  
Show every run with its spend, what a finished run produced and how to check it out, what Coral guaranteed, and a phone-width view for approvals on the go.  
G: G-77, G-73 · Hard: WEB-02, API-01 · Soft: WEB-04, API-02, RUL-02 · K-: K7, K8, K9  
In: Runs list with all states and 'Spend so far (estimate)'; final-state outcome panel: branch, commits, files changed, salvage refs, a copy-checkout command, and 'Run again' (prefilled start dialog with a new start_key); read-only guarantees panel per run from RUL-02 labels, with tooltips that state what was not checked; simplified phone layout: status, current step, gates and timeline; analytics events 'run completed', 'run failed' and 'run cancelled'.  
Out: Editor label chips (WEB-06); structure layers (WEB-10).  
Paths: `web/src/workflows/runs/list/`, `web/src/workflows/runs/outcome/`, `web/src/workflows/guarantees/RunGuarantees.tsx`  
OQ: OQ-23, OQ-24  
Proof: Vitest: a finished recorded run shows its outcome panel and checkout command, the guarantees panel shows only labels RUL-02 returns, and the phone layout renders the gate.

**WEB-05 Run agent panes, run-session page and steering** — WEB · PH2 · M2 · High · M · slice · wk 9.5-11.5  
From the run view, let users open any agent or the orchestrator, type in with honest hints, and get back to the run; make the anchor's own page point to the run.  
G: G-77 · S: S86 · Hard: WEB-04 · Soft: SES-03, SES-04 · K-: K7, K10  
In: SubagentTabPane via ?agent=&node= query params, never :conversationId (R-17); current orchestrator pane; 'read after current turn' hint for claude-sdk mid-turn buffering; the composer is disabled while the slot is evaluating or closing; run-session (anchor) page: a run banner linking to /workflows/runs/:runId, and a composer that routes to the orchestrator or is disabled with an explanation; 'Part of run' chip in ChatHeader (S86); 'Step waiting on you'; runner-offline state; M2 cut candidate 3: fall back to read-only panes plus 'open session'.  
Out: Stitched orchestrator and take-over controls (WEB-10).  
Paths: `web/src/workflows/runs/agents/`, `web/src/shell/ChatHeader.tsx`, `web/src/shell/SubagentTab.tsx`  
OQ: OQ-13, OQ-17  
Proof: Vitest: opening a step via ?agent= keeps AppShell out of chat mode, the composer is disabled while the slot is closing, and the anchor page links back to the run.

**RUL-02 claude-sdk promise labels and the never-over-claim fixture** — ENGINE · PH2 · M2 · High · M · slice · wk 9-11  
Compute the four promise labels for claude-sdk runs on (mode, host sandbox) so the MVP shows what Coral guarantees and never claims more than its mechanisms enforce (TLD-11).  
G: G-73, G-47 · Hard: ENG-03, EVD-01, HRN-01 · Soft: EVD-02 · K-: K9, K1, K11  
In: Enforced for path, gates and loop limits, and for read-only reviewers with write_paths: [] on a host with an FS sandbox; Verified (L1) for done-when with its stated limits; Judgment for orchestrator decisions; frozen per-mode 'never Enforced' fixture: native gate integrity (D25), claude-sdk CLI egress, budgets (one-turn overshoot), L1 re-edit gaps, native rosters while vendor sub-agents are reachable, indirect shell for command patterns, and hosts with no FS sandbox; gate-integrity label per mode; anything other than claude-sdk is not Enforced; tooltip text that says what was not checked; pure label API; property test: an unknown capability or a host without an FS sandbox never yields Enforced.  
Out: Multi-mode labels and V9 (RUL-06); editor chips (WEB-06).  
Paths: `coral/validate/labels.py`, `tests/coral/validate/test_labels.py`, `tests/coral/validate/fixtures/never_enforced.yaml`  
OQ: OQ-24  
Proof: Over the registry and fixtures no unknown capability or sandbox-less host yields Enforced, and the MVP template on claude-sdk yields the expected label for each checked part.

**OPS-06 Threat model and M2 security review** — OPS · PH2 · M2 · High · M · enabler · wk 4-6  
Review the M2 security surfaces while they can still change, and set the sign-off steps for the K20 freeze and the native step mode.  
Hard: SPK-01 · Soft: TLS-01, GTE-01, PRF-01, SES-03, HRN-02, SPK-05  
In: Review against the PH0 threat model: S49 tool provenance, gate authority and resolver identity, bundle secrets and provider-reference auth, the spike 15 verdict; findings owned by the producing features, tracked to closure by M2 exit; sign-off procedure for the K20 freeze (WSP-02) and a native-surface review before HRN-03 merges (D25, bridge_dir bearer).  
Out: Final production review and closure (OPS-04); load testing (OPS-04).  
Paths: `docs/coral/SECURITY_REVIEW.md`  
OQ: OQ-43  
If: If SPK-05 records an external M2 audience: this review is part of the M2 release gate  
Proof: docs/coral/SECURITY_REVIEW.md has an M2 section with every finding owned and no open high findings at M2 exit.

**OPS-07 M2 acceptance lane** — OPS · PH2 · M2 · Critical · M · slice · wk 11.5-13.5  
Prove the M2 journey end to end with injected faults on deterministic lanes, soak it on credentialed claude-sdk, and confirm real users can finish it unaided.  
G: G-87 · Hard: SES-05, FND-04, SES-04, SES-08, SES-06, SES-09, TLS-02, TLS-03, GTE-01, GTE-06, GTE-02, DUR-05, EVD-02, EVD-03, WSP-06, PRF-01, HRN-02, API-02, RUL-01, RUL-02, WEB-03, WEB-04, WEB-13 · Soft: WEB-05, TLS-05, WEB-11, OPS-06, OPS-03 · K-: K2, K4, K6, K14  
In: E2E-2 (SIGTERM between brief and handoff; no second session) and the M2 fault journey on Tier B: runner kill, loop forced to limit 3, pause, resume, cancel, retry, 529/429/401, input queued during a closing turn; engine-upgrade lane: start a run on build N, restart on N+1, resume to the end; SQLite perf smoke with five concurrent runs against the SPK-05 budgets; coral-e2e.yml carries only the credentialed nightly (Tier B runs in the inherited e2e gate); an on-demand credentialed workflow_dispatch lane from IM-2; the nightly asserts invariants and a terminal state; path coverage comes from Tier B and a scripted mock reviewer with a real claude-sdk implementer; a one-week soak tail at the SPK-05 threshold; owns IM-3 and IM-4; dogfood: internal users finish the journey on their own repo without help, template to first simulate under five minutes.  
Out: Native E2E-3 and E2E-4 (HRN-03, RUL-04, OPS-08); local browser runs (CI-only lane).  
Paths: `tests/e2e/coral/`, `.github/workflows/coral-e2e.yml`, `docs/coral/acceptance/M2.md`  
OQ: OQ-51, OQ-26  
Proof: E2E-2 and the fault journey are green in CI, the nightly meets the soak threshold over the soak week, and the dogfood record shows the journey finished unaided within the time target.

**HRN-08 Capability bench and multi-mode registry** — HARNESS · PH2 · M3 · High · M · slice · wk 7-9  
Fill the registry for every step mode and back its values with probes and a nightly bench, so M3 labels are bench-tested.  
G: G-44 · S: S23, S59, S78 · Hard: HRN-01 · Soft: SPK-03, OPS-01, SPK-05 · K-: K9, K16  
In: claude-native, codex-native and headless codex values with host-sandbox rows; capabilities_by_spelling on GET /v1/harnesses including native modes (S59); bench probes with offline verdict tests (S23) and feature-map rows (S78); owns coral-bench.yml, gated on the OQ-51 record; claude-sdk and claude-native nightly.  
Out: Label computation (RUL-06); Codex live lanes until HRN-05.  
Paths: `omnigent/server/routes/harnesses.py`, `omnigent/harness_plugins.py`, `tests/harness_bench/probes/`, `feature-map/harness-acceptance.md`, `.github/workflows/coral-bench.yml`  
OQ: OQ-51  
Proof: GET /v1/harnesses returns capabilities_by_spelling for claude-sdk and claude-native, and each bench probe has an offline verdict test.

**RUL-04 Native fail-closed hooks** — HARNESS · PH2 · M3 · Critical · M · slice · wk 5-7  
Make native policy hooks fail closed for run-owned sessions and carry sub-agent identity, the prerequisite for any native Enforced label.  
G: G-49 · S: S14, S16 · Hard: HRN-01, RUL-01 · Soft: HRN-08 · K-: K9  
In: First PR: spikes 5 (UserPromptSubmit on /clear) and 6 (native ASK re-publish after restart), time-boxed, with verdicts; S14 (upstream-first): fail_closed_hook_output for run-owned sessions; early returns deny; bridge-config policy_failure_mode; onFailure: block; explicit PreToolUse timeout; hooks-installed check (ap_server_url); CLI-version gating; S16 sub-agent identity in the policy context; E2E-4; a regression test that non-Coral native sessions are unchanged.  
Out: S15 codex-native refusal (HRN-05); S21 (HRN-02, conditional).  
Paths: `omnigent/native/native_policy_hook.py`, `omnigent/harnesses/claude_native/hook.py`, `omnigent/harnesses/codex_native/hook.py`, `omnigent/harnesses/claude_native/bridge.py`  
OQ: OQ-46  
Proof: E2E-4: blackholing the policy endpoint mid-step blocks the next native tool call, and a non-Coral native session keeps its current behaviour.

**ENG-08 Repeat-for-each and parallel semantics** — ENGINE · PH2 · M4 · High · L · slice · wk 9.5-14  
Define repeat-for-each and parallel split and join in the pure engine, and exercise the scope keys at depth before M2 freezes the state shape.  
G: G-08, G-09 · Hard: ENG-05, ENG-06 · Soft: ENG-03 · K-: K1, K2, K3  
In: First PR, merged before M2 exit: golden traces at item_path depth 2 against the K2 scope keys; repeat contract: order, empty list, per-item failure, concurrency, per-item gates and batching semantics, '3 of N' progress; parallel split and join with region cancel effects; failure paths inside regions; validator and Simulate support; join-once and duplicate-signal properties in L1 seeded fuzz.  
Out: Effect execution, template and E2E-5 (SES-10); groups (ENG-09); merges (WSP-03).  
Paths: `coral/engine/repeat.py`, `coral/engine/regions.py`, `tests/coral/engine/test_repeat_parallel.py`  
OQ: OQ-19, OQ-40  
Proof: Seeded fuzz shows a parallel join fires once and a duplicate signal is a no-op, and a simulated repeat over three items reports 3 of 3.

### PH3 Profiles, capabilities and enforcement (M2 to M3; some features target M4)

**PRF-02 Profile revisions and pinning** — HARNESS · PH3 · M3 · High · M · slice · wk 13.5-15.5  
Make profiles pinned, immutable revisions over custom agents so edits never leak into versioned or running workflows.  
G: G-50, G-14 · S: S66 · Hard: PRF-01, DUR-01 · K-: K12, K5  
In: Profile = agent row plus params.coral metadata (X-12 recommendation); coral_00NN_profile_revisions migration with byte copy and digest; version-to-revision pins; drift check at slot start; edits by reinstall create new revisions; /v1/coral/profiles API with used-by; spike 18 result; optional S66: redacted params.coral in agent summaries.  
Out: Desk UI (WEB-07); git import (EXT-03).  
Paths: `coral/profiles/`, `coral/api/profiles.py`  
OQ: OQ-37  
Proof: Editing a profile mid-run leaves the run on rev N and the next run uses rev N+1.

**RUL-06 Multi-mode labels and V9 enforceability** — ENGINE · PH3 · M3 · High · M · slice · wk 13.5-15.5  
Extend the promise labels to every step mode and reject Required rules a mode cannot enforce, with remedies (TLD-11).  
G: G-73, G-47 · Hard: RUL-02 · Soft: HRN-08, RUL-03, RUL-04 · K-: K9, K1, K11, K15  
In: Labels for claude-native, codex-native and headless codex from HRN-08 values; read-only off claude-sdk is Verified by before/after fingerprints (X-28); V9 per-mode enforceability: native unenforceable until S14, headless codex until S20, codex-native until S15, each with remedies; rule labels from K15 using RUL-03's bypass analysis; never-Enforced fixture extended per mode.  
Out: Editor chips and rule UI (WEB-06); rule compilation (RUL-03).  
Paths: `coral/validate/labels.py`, `coral/validate/v9.py`, `tests/coral/validate/test_labels_modes.py`  
OQ: OQ-24  
Proof: Switching a reviewer to claude-native turns read-only from Enforced to Verified, and V9 flags a Required 'protect infra/**' rule on a claude-native Implement with both remedies.

**RUL-03 Rules catalog v1: Required and Guidance** — INTEGRATION · PH3 · M3 · High · L · slice · wk 13.5-18  
Let authors add Required and Guidance rules from a typed template catalog over existing builtins, compiled into bundle guardrails (TLD-19).  
G: G-48 · Hard: RUL-01, PRF-01, ENG-03 · Soft: HRN-08, RUL-02 · K+: K15 · K-: K9, K12  
In: K15 first PR: template id, params, target builtin or policy, Required vs Guidance, enforceability inputs; about 8 templates: worktree_guard, blast_radius, mode-aware egress allowlist (R-12), CEL ask-before-path, never force-push, plus credential and egress profiles the PR-review template uses; A bypass analysis per template; command-pattern templates are labelled to match (never Enforced against indirect shell); workflow, step and profile scopes; an unenforceable Required rule fails validation with remedies; compile into bundle guardrails; confirmation API.  
Out: Free-text LLM translation (deferred); reactions and V8 (ENG-09).  
Paths: `coral/rules/catalog/`, `coral/rules/compile.py`, `coral/api/rules.py`  
OQ: OQ-38  
Proof: A Required 'protect infra/**' rule compiles into the step bundle's guardrails and blocks a write in a claude-sdk run, and each template's bypass analysis is checked into the catalog.

**HRN-03 claude-native step launch** — HARNESS · PH3 · M3 · High · L · slice · wk 13.5-18  
Offer claude-native steps for subscription users behind fail-closed hooks, with launch-time framework text, reliable turn end, observations and honest labels (TLD-07).  
G: G-55, G-39 · S: S3, S9, S11, S64 · Hard: RUL-04, PRF-01, SES-04, SES-08, TLS-01, SPK-05, OPS-06 · Soft: RUL-06, HRN-08, EVD-02 · K-: K9, K12, K11, K18, K4  
In: S9 relay advertisement and S11 claude-native pre-approval for coral_* tools; native launch channels carry the composed S12 FrameworkInstructions (ledger amendment to S12); S3 terminal_launch_args derivation; Stop-hook turn end with a level-triggered fallback from the transcript or pending-input state when an edge is lost; pane-reaper handling and wake-before-brief (pane_reaper.py:85, 146-157); spike 6 verdict applied; S64 egress auto-add of provider hosts; PostToolUse observation hints through the S69(b) outbox (ledger amendment to S69); separate sessions, steps only; merges dark behind claude_native_steps; native-surface security sign-off before merge (OPS-06); A subscription-runnable template: single-agent steps with labelled arrows and no orchestrator node; E2E-3.  
Out: /clear rotation following (HRN-07); codex-native (HRN-05); claude-native orchestrator (deferred); plan-limit pause (HRN-04).  
Paths: `omnigent/runner/native/orchestration.py`, `omnigent/runner/tool_dispatch.py`, `omnigent/server/routes/_sessions/helpers.py`, `omnigent/server/routes/sessions/routes_events.py`, `omnigent/inner/egress/rules.py`, `coral/omni/runner/claude_native.py`, `coral/templates/single_agent_steps.yaml`  
OQ: OQ-28, OQ-35  
If: If OQ-28 has no written answer by the end of PH2: ship on API key only behind claude_native_steps and rewrite M3 journey step 3  
Proof: E2E-3: a claude-native step under a mock model runs Bash, calls coral_submit_handoff and advances the run; with the turn_completed edge dropped, the fallback still advances it once.

**HRN-07 Native rotation following** — HARNESS · PH3 · M3 · High · M · slice · wk 18-20  
Keep a claude-native step attached to its run when the user or agent runs /clear and the native session rotates.  
G: G-24 · S: S45 · Hard: HRN-03 · Soft: SES-09 · K-: K18, K4  
In: S45 supersession observer following native /clear rotation; re-attach policies, labels and the bundle to the new session; /clear policy (OQ-46).  
Out: Reserved labels on non-route write paths (EXT-04).  
Paths: `omnigent/native/_native_supersession.py`, `omnigent/server/routes/_sessions/helpers.py`, `omnigent/server/routes/sessions/routes_events.py`, `coral/omni/server/rotation.py`  
OQ: OQ-46  
Proof: Running /clear in a claude-native step yields a new session that carries the run's policies, labels and bundle, and the run continues.

**HRN-04 Model access, plan limits and usage signal** — HARNESS · PH3 · M3 · High · M · slice · wk 15.5-17.5  
Let users choose how Claude is reached, and pause runs at plan limits with a visible reset time and automatic resume.  
G: G-57, G-54 · S: S24 · Hard: HRN-02, ENG-06 · Soft: HRN-03, PRF-02, WEB-07, SES-08 · K-: K9  
Secondary load: WEB 1 wk.  
In: Onboarding and settings route API key vs subscription -> claude-native; per-profile auth badge; S24 usage-limit signal with reset time: claude-sdk RateLimitEvent, ExecutorError reset time, native forwarders (Codex branch with HRN-05); replaces SES-08's text matching; paused(plan_limit) showing paused-until with auto-resume; mock-provider probe.  
Out: Account switching; Codex limits beyond the shared signal (HRN-05).  
Paths: `omnigent/inner/executor.py`, `omnigent/inner/claude_sdk_executor.py`, `omnigent/harnesses/claude_native/forwarder.py`, `web/src/workflows/settings/`  
OQ: OQ-28  
Proof: With a mock provider, a rate-limit event pauses the run as plan_limit with the reset time, and it resumes after it.

**WEB-06 Rule authoring and editor label chips** — WEB · PH3 · M3 · High · M · slice · wk 15.5-17.5  
Show per-mode label chips on boxes in the editor and let authors pick catalog rules with confirmation.  
G: G-73, G-48 · Hard: RUL-06, WEB-11 · Soft: RUL-03 · K-: K9, K15, K7  
In: On-box label chips and an editor guarantees panel that follow mode changes; rule picker with Required vs Guidance and per-mode labels; translation status chips; confirmation sheet; vitest for chip derivation; editor checks in the CI-only browser lane.  
Out: Run-view guarantees panel (WEB-13); free-text rules (deferred); label computation (RUL-02, RUL-06).  
Paths: `web/src/workflows/guarantees/`, `web/src/workflows/rules/`  
OQ: OQ-24  
Proof: Switching a step's mode in the editor updates its chips, and a Required rule the mode cannot enforce shows a problem with remedies.

**WEB-07 Agent Profiles desk and picker** — WEB · PH3 · M3 · High · M · slice · wk 15.5-17.5  
Ship /profiles as a lens over custom agents and a cmdk picker with capability chips, used-by and source badges, then turn on its nav entry.  
G: G-53 · Hard: PRF-02, BRD-02 · Soft: HRN-08, WEB-04 · K-: K7, K9, K12  
In: /profiles list over custom agents plus Coral metadata, with all states; edits by reinstall ('running runs keep rev N'); capability chips through the shared roster-chip component; cmdk picker in the editor and the template and start dialogs; flips profiles_desk at exit.  
Out: localStorage profiles (R-16); editing params via PATCH.  
Paths: `web/src/workflows/profiles/`, `web/src/pages/settings/`  
OQ: OQ-27, OQ-37  
Proof: Picking a profile for Review shows its capability chips and used-by count, and editing it creates rev N+1.

**WEB-12 Simulate scenario editor and saved-test badges** — WEB · PH3 · M3 · Medium · M · slice · wk 13.5-15.5  
Let authors write their own simulation scenarios from the workflow's derived info and see which saved cases pass on each version.  
G: G-67 · Hard: WEB-01 · Soft: DUR-02, WEB-11 · K-: K1, K7  
In: Scenario editor generated from the Analysis section (labels, list lengths, pass/fail, gate answers); save as case; saved-test badges per version; failing case diff with expected vs actual path; vitest for scenario generation.  
Out: Exhaustive Simulate (deferred); run data (WEB-04).  
Paths: `web/src/workflows/simulate/editor/`  
OQ: OQ-9  
Proof: An author saves a custom scenario, and changing the workflow so it fails shows a failing badge with the expected and actual paths.

**OPS-08 M3 acceptance lane** — OPS · PH3 · M3 · High · S · slice · wk 20-21  
Prove the M3 profile and enforcement journey end to end on top of the green M2 lane.  
G: G-87 · Hard: OPS-07, HRN-03, HRN-07, RUL-04, RUL-06, RUL-03, WEB-06, WEB-07, PRF-02, HRN-04, HRN-08 · Soft: WEB-12 · K-: K9, K12  
In: M3 journey script; E2E-3 and E2E-4 inside the MVP template with labels switching to Verified (IM-5); OQ-28 and OQ-35 written answers recorded, or the fallback applied; dogfood session passing the M3 journey.  
Out: M4 structure work.  
Paths: `tests/e2e/coral/test_m3_journey.py`, `docs/coral/acceptance/M3.md`  
OQ: OQ-28, OQ-35  
Proof: The M3 journey passes in CI and in a dogfood session, with E2E-3 and E2E-4 green inside the MVP template.

**WSP-02 Host workspace-op channel and L2 fingerprints** — WORKSPACE · PH3 · M4 · Critical · L · enabler · wk 13.5-18  
Run sessionless workspace ops on hosts with true exit codes and make L2 the authoritative fingerprint, with K20 frozen at M2.  
G: G-38, G-59 · S: S40, S40b · Hard: SPK-04, WSP-05, OPS-06 · Soft: WSP-01, EVD-02 · K+: K20 · K-: K13, K11  
In: First PR at M2: K20 frames and the workspace_ops:1 capability token, with security sign-off; frames and the reaper-guarded dispatcher in new omnigent/host/workspace_ops.py with one-line registrations in connect.py and frames.py (S40, upstream-first); server proxy, pending map, job events and journal; S40b entry-point op registry; ops: probe, head, fingerprint L1/L2; L2 write-tree on a temporary index (tracked plus untracked-not-ignored); version-skew fallback to the session-shell backend; contingency: if spike 8 failed, the commit, reset and salvage host ops have already moved into WSP-06 in PH2.  
Out: Write ops, swap and parity (WSP-07); exec jobs (EVD-04); merges (WSP-03).  
Paths: `omnigent/host/workspace_ops.py`, `omnigent/host/frames.py`, `omnigent/host/connect.py`, `omnigent/server/routes/_host_workspace_ops.py`, `coral/omni/host/ops/`  
OQ: OQ-44  
Proof: tests/host/test_frames.py: the token is advertised; L2 detects a re-edit that L1 porcelain missed; a host without workspace_ops:1 falls back to the session-shell backend.

**ENG-10 Versions, diff and restart-from-node** — ENGINE · PH3 · M4 · Medium · M · slice · wk 13.5-15.5  
Show version history and diffs, and amend a run by cancelling and restarting it from a chosen node with carried handoffs (TLD-18).  
G: G-65, G-14 · Hard: ENG-06, DUR-03, DUR-02 · Soft: WSP-01, WEB-04, DUR-05 · K-: K1, K2, K5  
Secondary load: WEB 0.5 wk.  
In: Versions list and structural diff API; runs per version; restart-from-node creating a linked run on a chosen version with carried handoffs, a worktree at the carried commit and a reason; mapping validation; also offered for paused(engine_upgrade) runs; coral_00NN_lineage migration; restart dialog in the run view; merges dark behind restart_from_node.  
Out: 'Apply to this run' (deferred); counter carry-over.  
Paths: `coral/engine/restart.py`, `coral/api/versions.py`, `web/src/workflows/runs/restart/`  
OQ: OQ-20, OQ-4  
Proof: Restarting a cancelled run from Review on v2 carries the implementer's handoff and links the old and new runs.

**BRD-03 Native shell identity** — BRAND · PH3 · M4 · High · M · slice · wk 13.5-15.5  
Give the Coral desktop and mobile shells their own names, ids, icons, scheme and update feed, with deep links to runs.  
G: G-82 · S: S38, S87, S88 · Hard: BRD-01 · Soft: OPS-02, OPS-03 · K-: K16  
In: Electron brand.js constants for about 37 literals; productName, appId, coral:// scheme, Coral publish.url updater feed (R-18; required before any desktop build); starts at M2 so desktop builds can resume early; setup and connect pages; icons including Assets.car; CLI detection accepting coral; iOS and Android display names and icons; run deep links (S38).  
Out: Store listings (OQ-31); mobile push (deferred); mobile editing.  
Paths: `web/electron/package.json`, `web/electron/src/main.js`, `web/electron/src/brand.js`, `web/electron/src/deepLink.js`, `web/ios/`, `web/android/`  
OQ: OQ-31, OQ-23  
Proof: A packaged desktop build reports the Coral appId, checks the Coral update feed, and coral://workflows/runs/<id> opens the run.

### PH4 Trust and structure (opens at M2, to M4)

**WSP-07 Host-backend write ops, swap and parity** — WORKSPACE · PH4 · M4 · High · M · slice · wk 18-20  
Move commit, reset and salvage to the host channel, add fetch and push behind consent, and swap backends without changing a single evaluator verdict.  
G: G-59, G-38 · Hard: WSP-02, WSP-06 · Soft: EVD-02 · K-: K13, K20, K11  
In: Ops: commit_all, salvage, reset_to, branch, diff_paths on the host channel; fetch-ref and push ops behind consent (OQ-39) for the PR-review loop; adapter swap with the evaluator unchanged; exit-status contract test; label fixture update; owns IM-6.  
Out: Exec jobs (EVD-04); merges (WSP-03).  
Paths: `coral/omni/host/ops/write.py`, `coral/workspace/host_backend.py`, `tests/coral/workspace/test_parity.py`  
OQ: OQ-39  
Proof: The evaluator gives identical verdicts on both K13 backends over the parity fixtures, and push is refused without consent.

**EVD-04 Coral-run checks, verifier and worktree setup** — WORKSPACE · PH4 · M4 · High · L · slice · wk 13.5-18  
Run the pinned checks in a Coral-controlled checkout, flag tampering, feed results back into attempts, and offer a verifier step.  
G: G-43, G-58, G-41 · Hard: EVD-03, EVD-02 · Soft: WSP-02, WSP-07, ENG-06 · Slices: WSP-02#K20 · K-: K13, K20, K11  
In: Sandboxed exec jobs with caps on the host channel, built against the K20 fake until WSP-02 lands; S72 detached+commit mode (ledger amendment to S72) for a detached checkout running the snapshotted commands (X-32); coral_00NN_check_runs migration; JUnit capture; integrity diff on test and config edits; check-to-attempt loop; read-only verifier step pattern labelled Judgment; per-worktree setup (.coral/repo.yaml, .worktreeinclude fallback); CI-file and pre-commit command parsers (moved from EVD-03).  
Out: Hidden held-out tests; LLM rubric judges; multi-writer merges (WSP-03).  
Paths: `coral/checks/`, `coral/omni/host/ops/exec.py`, `omnigent/host/git_worktree.py`, `coral/templates/patterns/verifier.yaml`  
OQ: OQ-44, OQ-10  
Proof: An agent that edits package.json scripts is flagged by the integrity diff, and checks re-run in the detached checkout feed the attempt.

**WSP-03 Per-agent and per-item worktrees and serial merges** — WORKSPACE · PH4 · M4 · High · L · slice · wk 18-22.5  
Give each code-writing agent, per repeat item, its own worktree on the right base, merge serially into the run worktree, and resolve conflicts in the agent's worktree with post-merge checks.  
G: G-60 · Hard: WSP-02 · Soft: EVD-04, TLS-04, ENG-08, WSP-07 · K-: K13, K20, K11  
In: Worktrees keyed (run, node, item_path, agent) with a per-item base ref, e.g. each PR's head (D11); coral_00NN_merge_state migration; serial merges at close or join; conflict sub-state resolved in the agent's own worktree via coral_assign_task (D10); mandatory post-merge Coral-run checks (D8); submodule and LFS probe.  
Out: Unchecked parallel merges; managed sandboxes (WSP-04).  
Paths: `coral/workspace/merge.py`, `coral/omni/host/ops/merge.py`  
OQ: OQ-40  
Proof: Two writers' branches merge serially, a conflict is resolved in the agent's worktree, and post-merge checks run before the step closes.

**SES-10 Structure integration and PR-review showcase** — INTEGRATION · PH4 · M4 · High · M · slice · wk 14-16  
Run repeat-for-each and parallel regions for real: per-item gates, sibling cancel, concurrency caps and per-item worktrees, shown by the PR-review loop.  
G: G-08, G-09 · Hard: ENG-08, SES-04, GTE-01, TLS-02 · Soft: WSP-03, RUL-03, WSP-07, DUR-04 · K-: K14, K2, K4, K21  
In: Per-item gates and gate batching on GTE-01 with the K14 batch payload; sibling interrupts executed on region cancel; concurrency caps that respect worker claims; per-item scope reaching WSP-03 worktrees; PR-review loop template (TLD-01 showcase) with its credential and egress profile from RUL-03 templates; OQ-18 settled for the PR case; E2E-5 only at the boundary of two real concurrent sessions submitting; owns IM-7.  
Out: Pure semantics (ENG-08); merges (WSP-03).  
Paths: `coral/structure/`, `coral/templates/pr_review_loop.yaml`, `tests/e2e/coral/test_parallel.py`  
OQ: OQ-2, OQ-18  
Proof: E2E-5: two real sessions in a parallel region submit concurrently and the join fires once; a repeat over three PRs batches its gates and reports 3 of 3.

**ENG-09 Groups, saved blocks, Wait and reactions** — ENGINE · PH4 · M4 · Medium · L · slice · wk 18-22.5  
Let authors group steps with inherited rules, save blocks, use Wait timers, and attach 'when X, do Y' reactions such as overdue alerts.  
G: G-10, G-48, G-06 · Hard: ENG-03, ENG-06, RUL-03 · Soft: ENG-08, GTE-06 · K-: K1, K2, K15, K19  
In: Group IR with entry and exit; V8 inner-stricter rule inheritance; coral_00NN_saved_blocks migration and library; hidden Wait kind with timers; reaction templates on timers and run events; expected_duration x factor overdue alerts into the Inbox.  
Out: Sub-workflow invocation (deferred); group, reaction and saved-block UI (WEB-08, WEB-09); reactions that change the graph.  
Paths: `coral/model/groups.py`, `coral/engine/reactions.py`, `coral/validate/v8.py`  
OQ: OQ-19, OQ-38  
Proof: The validator rejects a group whose inner rule is looser (V8), and a simulated overdue step raises an Inbox alert from a reaction.

**TLS-04 Messaging and assignment tools** — INTEGRATION · PH4 · M4 · Medium · M · slice · wk 13.5-15.5  
Let parallel agents and the orchestrator message through the engine, use 'up to' rosters, and re-task a member to resolve conflicts.  
G: G-31 · Hard: TLS-03, SES-04 · Soft: ENG-08 · K-: K6, K4  
In: coral_message_agent: engine-routed via dispatch with a [Coral message from ...] prefix, isolation flags, rate limit; refused for slots in the closing state; coral_assign_agents for 'up to' rosters; coral_assign_task to re-task a member for conflict resolution (D10).  
Out: sys_session_message reuse; EGM resolutions (EXT-02).  
Paths: `coral/tools/handlers/message_agent.py`, `coral/tools/handlers/assign.py`  
Proof: A message to a closing step is refused cleanly, and assign_task re-tasks a member inside its own worktree.

**SES-07 Slot control: refresh and take-over** — INTEGRATION · PH4 · M4 · Medium · L · slice · wk 13.5-18  
Refresh long sessions by slot restart with a refresh note, and let a user take over a step and hand it back (TLD-13).  
G: G-63, G-64 · S: S25, S27 · Hard: SES-06, HRN-01, EVD-02, ENG-06 · Soft: WSP-02, WSP-07, HRN-08 · K-: K4, K9, K6, K11  
In: Per-mode threshold refresh_threshold_bp=7000 below native auto-compaction (D1.7); wait for turn end; request refresh_note; slot restart: create, brief, close the old session, publish a notice; S25 'refresh' reason literal and web handler; refreshing the orchestrator child leaves every sibling reachable under the anchor; S27 reaper retests (label exemption only if a retest fails), unless spike 16 moved them to SES-06; taken_over(by) with reminders, refresh and auto-advance off; user input detected by stable_id; slot-control columns through the train; hand-back re-fingerprints and re-evaluates done-when; salvage guard; endpoints; merges dark behind takeover.  
Out: Fork-based refresh (S47, not planned); stitched transcript and controls UI (WEB-10); multi-user take-over.  
Paths: `coral/slots/refresh.py`, `coral/slots/takeover.py`, `omnigent/server/schemas.py`, `omnigent/terminals/pane_reaper.py`, `omnigent/runner/app.py`  
OQ: OQ-11, OQ-46  
Proof: A step crossing the threshold restarts with its refresh note, an orchestrator refresh keeps its siblings reachable, and a taken-over step hands back with a fresh fingerprint and done-when result.

**GTE-03 External notification connector (webhook first)** — PLATFORM · PH4 · M4 · High · M · slice · wk 13.5-15.5  
Deliver unattended gates and pauses outside the app through an outbox-driven connector, webhook first, then email or Slack DM.  
G: G-37 · Hard: GTE-06, DUR-04 · Soft: GTE-01 · K-: K19, K5, K7, K21  
Secondary load: WEB 0.5 wk.  
In: coral_00NN_notify migration: per-user channels and deliveries; settings UI; outbox-driven delivery as a K21 executor, idempotent per channel; secret-free deep links; webhook first, then email or Slack DM; merges dark behind webhooks.  
Out: Push (GTE-04); slack-originated sessions.  
Paths: `coral/notify/`, `web/src/workflows/settings/notifications/`  
OQ: OQ-6  
Proof: An unattended gate posts one webhook (retries stay idempotent) whose deep link opens the gate.

**WEB-08 Canvas editing core** — WEB · PH4 · M4 · Medium · L · slice · wk 15.5-20  
Let users draw and rewire workflows on the canvas while the YAML keeps its comments and confirmed translations.  
G: G-72 · Hard: WEB-01, WEB-11 · Soft: WEB-07, RUL-03 · K-: K1, K7  
In: Palette; connect, move and delete as canvas intents; intents -> comment-preserving CST patches; layout file keyed by stable ids; one undo stack shared with the YAML pane; server validation; golden round-trips; vitest for intent-to-patch and layout; canvas interaction in the CI-only browser lane; merges dark behind canvas_edit.  
Out: Inspectors (WEB-09); mobile editing.  
Paths: `web/src/workflows/canvas/edit/`, `web/src/workflows/editor/patches/`  
OQ: OQ-22  
Proof: Vitest: adding and rewiring a step produces a YAML diff that touches only those lines and keeps every comment.

**WEB-09 Canvas inspectors and accessible outline** — WEB · PH4 · M4 · Medium · L · slice · wk 20-24.5  
Make every property editable in an inspector, including budgets, reactions and saved blocks, and give keyboard and screen-reader users an outline with full parity.  
G: G-72 · Hard: WEB-08 · Soft: WEB-07, WEB-06, ENG-09, WEB-03, RUL-05 · K-: K1, K9, K15  
In: Step, arrow, gate, decision and group inspectors; embedded profile picker, rules panel and done-when picker; step budget fields, reaction templates and the saved-blocks library; outline tree with keyboard and screen-reader parity; axe checks in the CI-only browser lane.  
Out: Freeform layout tools; real-time co-editing.  
Paths: `web/src/workflows/canvas/inspectors/`, `web/src/workflows/outline/`  
OQ: OQ-22  
Proof: Every inspector edit is reachable from the outline by keyboard alone, and the CI browser lane's axe check of the outline passes.

**WEB-10 Run view depth: structure, checks, merges and spend** — WEB · PH4 · M4 · Medium · L · slice · wk 17.5-22  
Show repeats, regions, groups, join waits, why-not-taken arrows, Coral-run checks, merges and spend vs budget in the run view, plus take-over and refresh.  
G: G-77, G-08, G-67 · Hard: WEB-04 · Soft: ENG-08, SES-07, ENG-10, WEB-05, RUL-05, EVD-04, WSP-03, SES-10 · K-: K8, K3, K7  
In: Overlay layers: '3 of N' repeat badges, region frames, groups, join waits; why-taken and why-not-taken arrows; Coral-run check results, JUnit output, integrity-diff flags and verifier verdicts labelled Judgment; merge progress, conflicting files and who resolves them; spend vs budget with the overshoot disclosure; take-over controls; stitched orchestrator segments with refresh dividers; versions tab.  
Out: Run sharing (EXT-04); mobile editing.  
Paths: `web/src/workflows/canvas/overlay/`, `web/src/workflows/runs/`  
OQ: OQ-23  
Proof: Vitest over a recorded PR-review run: '3 of N' badges, a why-not-taken explanation, a flagged integrity diff and a merge conflict with its resolver render.

**HRN-05 codex-native step mode** — HARNESS · PH4 · M4 · Medium · L · slice · wk 18-22.5  
Enable codex-native steps with terminal turn outcomes, refusal without hooks and an explicit unattended stance.  
G: G-56, G-20 · S: S2, S15, S62 · Hard: RUL-04, HRN-01, SES-04, SES-08, TLS-01 · Soft: RUL-06, HRN-04, HRN-08 · K-: K9, K12, K18  
In: First PR: spikes 12 (codex-native app-server sandbox) and 13 (Codex context window); S2 turn_outcome and turn_completed on terminal edges; S15 refuse run-owned codex-native when policy hooks are disabled (upstream-first); S62 explicit yolo stance for run sessions with policy-resolved approvals (upstream-first); Codex S11 pre-approval site and native S12 text (ledger amendments); adapter exit_code observations; Codex branch of S24; honest labels; merges dark behind codex_steps.  
Out: Headless codex (HRN-06, HRN-09); hosted use before OQ-29; Codex orchestrator.  
Paths: `omnigent/harnesses/codex_native/forwarder.py`, `omnigent/harnesses/codex_native/app_server.py`, `omnigent/server/routes/_sessions/helpers.py`, `coral/omni/runner/codex_native.py`  
OQ: OQ-29  
If: If OQ-29 has no answer by PH4 start: stays dark behind codex_steps and the M4 journey uses two claude-sdk reviewers  
Proof: A codex-native reviewer step submits a handoff and its terminal edge carries turn_outcome; disabling hooks refuses the run.

**DUR-06 Retention, purge and account lifecycle** — PLATFORM · PH4 · M4 · Medium · M · slice · wk 13.5-15.5  
Purge run data by policy and carry or purge Coral rows when accounts are revoked or migrated.  
G: G-16 · S: S56 · Hard: DUR-05 · Soft: DUR-02 · K-: K5, K17  
Secondary load: WEB 0.5 wk.  
In: Retention policy; batched purge_run with blob GC from the ledger; engine agent-row GC; deleting workflows that have runs, with a confirmation in the desk; retention setting UI; S56 account-lifecycle callbacks registered through K17 for revocation and identity migration.  
Out: Legal hold; run-log export (EXT-03).  
Paths: `coral/retention/`, `omnigent/server/accounts_store.py`, `web/src/workflows/settings/retention/`  
OQ: OQ-25  
Proof: A purged run leaves no Coral rows or blobs, and identity migration carries Coral rows to the new account.

### PH5 Production readiness (M3 to M4)

**HRN-06 Headless codex gating and read-only stance** — HARNESS · PH5 · M4 · Low · M · slice · wk 21-23  
Enable headless Codex steps whose policy gating works through hooks.json and whose read-only stance never upgrades silently.  
G: G-56 · S: S20, S61, S67 · Hard: HRN-01, RUL-01, SES-04, SES-08, TLS-01 · Soft: HRN-05, HRN-08 · K-: K9, K12  
In: hooks.json PreToolUse gating (S20); hook-trust failure fails closed for run sessions (S67); read-only stance without silent upgrade (S61); gating probe.  
Out: Thread routing, compaction and native-tool switches (HRN-09); codex-native (HRN-05).  
Paths: `omnigent/inner/codex_executor.py`, `omnigent/inner/codex_harness.py`  
OQ: OQ-29  
If: If OQ-29 has no answer by PH4 start: stays dark behind codex_steps  
Proof: A headless codex read-only step cannot write, and a tool denied by policy is blocked through hooks.json.

**HRN-09 Headless codex thread routing and compaction** — HARNESS · PH5 · M4 · Low · M · slice · wk 23-25  
Route headless Codex threads and compaction correctly and honour per-session native-tool switches; the first cut if M4 slips.  
G: G-56 · S: S18, S19, S60 · Hard: HRN-06 · K-: K9  
In: threadId routing and collab items (S18); compaction (S19); per-session native-tool switches from the spec (S60).  
Out: Gating and read-only stance (HRN-06).  
Paths: `omnigent/inner/codex_executor.py`, `omnigent/runner/app.py`, `omnigent/runtime/workflow.py`  
OQ: OQ-29  
Proof: A long headless codex step compacts without losing its thread, and a native tool disabled in the spec is unavailable.

**RUL-05 Run and step budgets** — INTEGRATION · PH5 · M4 · High · M · slice · wk 21-23  
Pause a run at its budget and ask to raise or stop, using a spend aggregator over all run sessions, with step budgets and estimates from history.  
G: G-62 · Hard: RUL-01, GTE-01, SES-04 · Soft: ENG-07, API-02 · K-: K14, K4, K9  
Secondary load: WEB 1 wk.  
In: Spend aggregator over all run sessions (policy_cost_usd ?? total_cost_usd); coral_00NN_budgets migration; paused(budget) with a raise-or-stop elicitation; run-guard DENY reason through the existing S52 provider (no new builder.py edit); overshoot disclosure; label fixture update (budgets are never Enforced); tokens and utilization for plan users (D21); estimate from Simulate sessions x past medians; budget field in the start dialog, spend vs budget data for WEB-10, step budget fields for WEB-09; merges dark behind budgets.  
Out: cost_budget as the primary mechanism (R-5); provider-side hard caps.  
Paths: `coral/budgets/`, `web/src/workflows/start/BudgetField.tsx`  
OQ: OQ-15, OQ-16  
Proof: A run crossing its budget pauses with a budget elicitation; raising it resumes and stopping cancels.

**OPS-04 Production hardening: DB lanes, load and security closure** — OPS · PH5 · M4 · Critical · L · slice · wk 21-25.5  
Certify Coral for production with all DB lanes, a load scenario and a closed security review (TLD-08).  
G: G-87, G-11 · Hard: OPS-02, DUR-05, SES-06, GTE-01, OPS-06 · Soft: WSP-02, HRN-05, GTE-03  
In: Four DB lanes and the split-DB lane green with fault suites; release statement: SQLite and Postgres committed, CockroachDB and MySQL tested; Coral load scenario in dev/loadtest (concurrent runs, SQLite contention) against the OQ-1 NFRs; worker-lease behaviour with two replicas; closes the staged security review: remaining M3 and M4 surfaces (host-op token, webhooks, native modes) with fixes owned by producing features; owns IM-8 with OPS-05.  
Out: Multi-replica sharding (deferred); multi-region.  
Paths: `dev/loadtest/`, `tests/stores/coral/`, `docs/coral/SECURITY_REVIEW.md`  
OQ: OQ-1, OQ-42, OQ-43  
Proof: The load report meets the OQ-1 NFRs and the security review closes with no open high findings.

**OPS-05 Release readiness: merge drill, upstreaming and licensing sign-off** — OPS · PH5 · M4 · High · M · slice · wk 21-23  
Run the release merge drill, drive the upstream PRs to merge and retire their anchors, and close licensing for release.  
G: G-84, G-86 · S: S1b · Hard: OPS-02 · Soft: OPS-04  
In: Release merge drill by the playbook with re-anchoring; security cherry-pick lane with an SLA; drive every 'Up: Yes' seam PR to merge and retire its CORAL(Sx) anchor after the next merge; full S1b origin slugs as an upstream-only PR; counsel answers: attribution, Apache §4(b), React Flow attribution, OFL, dagre, the inherited elkjs; DCO decision; release pipeline.  
Out: Store listings; relicensing.  
Paths: `docs/coral/UPSTREAM_MERGES.md`, `.github/workflows/coral-release.yml`, `NOTICE`, `MODIFICATIONS.md`, `.coral/upstream.yaml`  
OQ: OQ-30, OQ-31, OQ-50  
If: If SPK-05 records an external M2 audience: the OQ-30 counsel answers that distribution needs are pulled forward to M2  
Proof: The release drill lands with all Coral lanes green, merged upstream seams have their anchors retired, and the licence inventory is signed off.

**OPS-09 M4 acceptance lane** — OPS · PH5 · M4 · High · M · slice · wk 24.5-26.5  
Prove the integrated M4 journey end to end on top of the green M3 lane.  
G: G-87 · Hard: OPS-08, SES-10, WSP-07, EVD-04, WSP-03, WEB-08, WEB-09, WEB-10, RUL-05, SES-07, GTE-03, ENG-10, DUR-06, BRD-03, ENG-09, TLS-04 · Soft: HRN-05, HRN-06, HRN-09, OPS-04, OPS-05 · K-: K13, K20  
In: M4 journey script on the PR-review loop with the structure, trust and control steps; Codex-native reviewers when OQ-29 allows, otherwise two claude-sdk reviewers; dogfood session passing the M4 journey.  
Out: Post-M4 extensions.  
Paths: `tests/e2e/coral/test_m4_journey.py`, `docs/coral/acceptance/M4.md`  
Proof: The M4 journey passes in CI and in a dogfood session.

### PH6 Post-M4 extensions

**WSP-04 Managed-sandbox runs** — WORKSPACE · PH6 · post-M4 · Low · L · slice · wk 26.5-31  
Run workflows in managed sandboxes that survive sleep and relaunch from checkpoints.  
G: G-61 · S: S28, S70 · Hard: WSP-02, SES-06 · K-: K13, K20  
In: Bind-mode worktrees in managed sandboxes (S28); host-keyed keep-warm lease (S70); checkpoint pushes and relaunch from a checkpoint branch; spike 9.  
Out: Plain-folder shadow repos (deferred); multi-host runs.  
Paths: `omnigent/server/managed_hosts.py`, `omnigent/server/managed_host_keepalive.py`, `coral/workspace/sandbox.py`  
OQ: OQ-5  
Proof: A sandboxed run survives sandbox sleep at a gate and relaunches from its checkpoint branch.

**EXT-01 Improvement suggestions** — ENGINE · PH6 · post-M4 · Low · L · slice · wk 26.5-31  
Propose evidence-backed workflow edits from finished runs, never weakening evidence or gates.  
G: G-88 · Hard: ENG-04, DUR-03 · Soft: ENG-10, WEB-08 · K-: K3, K1  
Secondary load: WEB 1 wk.  
In: Run-log detectors: first-try evidence failures, loops at limit, cost growth, always-approved gates, reversed decisions, always-pass evidence, test edits in non-test steps; coral_00NN_suggestions migration; suggestion list with run links and YAML diffs; accepting creates a version.  
Out: Auto-apply; weakening evidence or gates.  
Paths: `coral/suggestions/`, `web/src/workflows/suggestions/`  
OQ: OQ-55  
Proof: A run history with three loops at limit yields a suggestion with a YAML diff, and no suggestion removes a gate or evidence item.

**EXT-02 Elephant-Goldfish showcase** — ENGINE · PH6 · post-M4 · Low · M · slice · wk 26.5-28.5  
Ship the Elephant-Goldfish template with a persistent elephant step across passes and scoped goldfish inputs.  
G: G-89 · Hard: ENG-08, WSP-02, SES-07 · Soft: TLS-04 · K-: K1, K13, K20  
In: Slot rebinding for session: persistent_across_loop (keys reserved in K1); per-member input scoping with a coral.omni.policies DENY on session-read tools plus a files.materialize host op (S65 not used; TLD-04); typed resolutions; ESCALATE -> gate; persona attribution.  
Out: Elephant as the orchestrator (D4.2); AgentSpec changes (TLD-04).  
Paths: `coral/templates/elephant_goldfish.yaml`, `coral/omni/policies/input_scope.py`, `coral/omni/host/ops/materialize.py`  
OQ: OQ-30  
Proof: A goldfish step cannot read sibling sessions, and the elephant keeps one session across three loop passes.

**EXT-03 Repo export, git import and run-log export** — WORKSPACE · PH6 · post-M4 · Low · M · slice · wk 26.5-28.5  
Export workflows to .coral/ in a repo, import workflows, templates and profiles from git, and export run logs for audit.  
G: G-68, G-90 · S: S74 · Hard: WSP-01, DUR-02 · Soft: PRF-02, WSP-02 · K-: K13, K12, K3  
In: S74 .coral/**-confined write op with an expected-hash precondition; Git-URL import of workflows, templates and profiles with a V10 profile check; run-log export as JSON or Markdown (PC-33).  
Out: Repo-canonical editing; sync daemon; marketplace.  
Paths: `omnigent/host/connect.py`, `omnigent/server/routes/_host_filesystem.py`, `coral/sharing/`  
OQ: OQ-33  
Proof: Exporting a version writes .coral/<id>.yaml only when the expected hash matches, importing it elsewhere yields the same content hash, and a run log exports as JSON.

**EXT-04 Run sharing, teams and protection guards** — INTEGRATION · PH6 · post-M4 · Low · L · slice · wk 26.5-31  
Let teams share runs and answer gates, and protect run sessions and engine agents from mutation (TLD-12).  
G: G-90, G-24, G-52 · S: S26, S46, S53 · Hard: SES-09, GTE-01 · Soft: GTE-03 · K-: K10, K14  
In: Engine-managed grants for run sharing (D18); team approvers; coral_00NN_run_grants migration; S26 protected coral. policy names and label prefix; S46 reserved labels on non-route write paths with an explicit /clear policy; S53 mutation guards on PUT agent, MCP edits, PATCH, reinstall and non-forced delete.  
Out: Per-session sharing reuse; cross-org sharing.  
Paths: `omnigent/server/routes/session_policies.py`, `omnigent/runtime/policies/engine.py`, `omnigent/server/routes/sessions/routes_agent.py`, `omnigent/server/routes/builtin_agents.py`, `coral/sharing/`  
OQ: OQ-4, OQ-17, OQ-46  
Proof: A teammate with the run grant answers a gate, and a non-engine PATCH to a coral__ agent is refused.

**EXT-05 Automations 'Run workflow' trigger** — PLATFORM · PH6 · post-M4 · Low · M · slice · wk 26.5-28.5  
Start workflow runs from an Automations action, with no second scheduler.  
G: G-90 · Hard: API-02 · K-: K7  
In: 'Run workflow' Automations action; start_key per fire for idempotent starts.  
Out: Coral-owned schedules; workflows as tools or APIs (deferred).  
Paths: `omnigent/server/scheduled/`, `web/src/pages/TasksPage.tsx`, `coral/api/runs.py`  
OQ: OQ-21  
Proof: An automation firing twice with the same fire id starts one run.

**GTE-04 Web and desktop push notifications** — WEB · PH6 · post-M4 · Low · L · slice · wk 26.5-31  
Deliver gate and pause notifications through Web Push when the app is closed.  
G: G-37 · Hard: GTE-03 · Soft: BRD-03 · K-: K19  
In: VAPID keys, coral_00NN_push_subscriptions migration and a service worker; payloads without secrets; desktop shell delivery.  
Out: APNs and FCM mobile push (deferred); email digests.  
Paths: `web/src/workflows/push/`, `web/public/`, `coral/notify/push.py`  
OQ: OQ-6, OQ-23  
Proof: A gate opened while the browser tab is closed shows a push notification that deep-links to the gate.

## 3. Milestone exit criteria and proving journeys

Each milestone's date is the finish of its acceptance lane (OPS-07, OPS-08, OPS-09), which hard-depends on the previous lane, so milestone paths are cumulative.

### M1 Foundational Coral (PH0 + PH1)

**Dates.** Levelled week 9.5; planned week 11 (15% integration buffer); single-owner CPM 11.5 via FND-01 > ENG-01 > ENG-04 > ENG-05 > ENG-07.

**Features (25).** SPK-01, SPK-02, SPK-03, SPK-04, FND-01, FND-05, OPS-01, ENG-01, SES-01, API-01, FND-02, FND-03, FND-04, OPS-02, DUR-01, DUR-02, ENG-02, ENG-03, ENG-04, ENG-05, ENG-07, EVD-01, HRN-01, BRD-01, BRD-02.

**Product journeys exercised.** b, c (YAML via API), d.

**Proving journey.**

1. A developer enables Coral with one config key (server_plugins: [coral.server_plugin]) and sees the Coral skin and the Workflows desk with empty states behind GET /v1/coral/info. Agent Profiles stays hidden behind profiles_desk. Turning Coral off hides the desk and returns not found.
2. Through the API or `coral workflow upload`, they upload the MVP template and get v1 with a content hash over the authoring document. A broken copy returns box-anchored problems with yaml_path ranges.
3. They freeze a version and simulate 'approved', 'changes requested x3 -> at-limit gate' and 'gate reject'. The traces are deterministic, show a session-count estimate, and re-run green as saved cases on v2 and with the loop limit parameter changed.

**Exit criteria.**

1. coral ships in the wheel; the three-tier import-boundary lint and the coral CI group are green; coral --help runs (FND-01, FND-05).
2. Coral migrations run strictly after Omnigent head on SQLite and Postgres with CockroachDB, MySQL and split-DB lanes green; CoralBase binds to the operational engine; coral_0001 carries scope keys, session_generation and engine_version (FND-03, FND-04, DUR-01).
3. One plugin key mounts /v1/coral and registers policy modules; a broken plugin or policy import aborts startup; the web gate reads /v1/coral/info and its sub-feature map; the upstream Feature enum is untouched (FND-02, BRD-02).
4. coral-fork-guard is required, every upstream path is ledgered and anchored, landed 'Up: Yes' seams show their upstream PR, at least two real merges from nightly^1 have landed, and NOTICE and MODIFICATIONS.md are generated (OPS-01, OPS-02).
5. Brand skin and navigation shell are live and the CSS contract tests are rebaselined (BRD-01, BRD-02).
6. V1-V7 and V10-V13 pass; I1-I8 hold under seeded fuzz; Simulate works through the API with saved cases (ENG-01..05, ENG-07, DUR-02).
7. IM-0: K1-K4, K6-K8, K10, K12, K14, K16, K18 and K19 are at v1 with contract tests; K5, K9, K11, K17 and K21 are published; K13 v1 is frozen as WSP-01's first PR; ADR-05 and the week-1 decision records and threat model are signed (SPK-01..04).

### M2 Functional stateful workflow (PH2, MVP)

**Dates.** Levelled week 13.5; planned week 16 (15% integration buffer); single-owner CPM 13.5 via FND-01 > FND-03 > DUR-01 > DUR-04 > SES-05 > OPS-07.

**Features (41).** SPK-05, OPS-03, DUR-03, DUR-04, ENG-06, ENG-11, RUL-01, SES-02, TLS-01, GTE-05, WSP-05, WSP-01, EVD-03, EVD-02, HRN-02, PRF-01, SES-03, SES-04, WEB-01, WEB-02, DUR-05, SES-08, SES-06, SES-09, SES-05, TLS-02, TLS-03, TLS-05, GTE-01, GTE-06, GTE-02, WSP-06, API-02, WEB-11, WEB-03, WEB-04, WEB-13, WEB-05, RUL-02, OPS-06, OPS-07.

**Product journeys exercised.** a, b, c (YAML), d (preset), e, f, g (in-app), h (steer), i (core), l (history).

**Proving journey.**

1. Web and CLI only; desktop builds arrive at M4. On a local git repo, on macOS (seatbelt) or Linux with bwrap, with an Anthropic API key, the user opens the 'Implement with review loop' card (promise summary and 'Needs:' line), sets the loop limit and reviewer models, confirms the detected test, lint and format commands, runs the preset simulation, and starts the run. Preflight passes and shows the estimate and the per-session cost cap.
2. The implementer edits in coral/r-<run>/base. Its first coral_submit_handoff is rejected because the tests predate its last edit, and is accepted after a re-run. The slot closes: Coral commits, stops the session and labels it closed; the composer is disabled while it closes.
3. Two read-only reviewers on different models submit findings; a reviewer write is denied by the sandbox; the guarantees panel shows read-only as Enforced on this host.
4. The orchestrator calls coral_choose_arrow('changes requested') with a reason; the loop counter shows pass 2 of 3 and spend so far updates.
5. The server is SIGTERMed mid-step and restarted. The run resumes with no duplicate sessions and the gate is re-published.
6. The reviewers approve. The gate appears once in the Inbox with the handoff report, evidence, diff stat and the 'app must be open' notice; the user approves it there; the run ends with an outcome panel (branch, commits, copy-checkout command) and 'Run again'.
7. On a second run the user pauses, resumes, cancels and retries a step (work salvaged, worktree reset); a killed runner pauses the run as paused(infra) until Resume; a forced 429 pauses it as paused(plan_limit).

**Exit criteria.**

1. Deterministic lanes are green: E2E-1 (SES-05), E2E-2 and the M2 fault journey on Tier B, on claude-sdk against the mock if spike 4 passed, otherwise with the listed exceptions (OPS-07).
2. The credentialed claude-sdk nightly asserts invariants and reaching a terminal state and meets the SPK-05 soak threshold over the soak week; path coverage comes from Tier B and a scripted mock reviewer with a real implementer (OPS-07). Conditional on the OQ-51 record.
3. fold(log) == state after real commits; a crash at every commit boundary recovers without duplicates on all lanes and the split-DB lane; I7 holds; the engine-upgrade lane passes (DUR-03, DUR-05, ENG-11, OPS-07).
4. The orchestrator decides only through engine tools; illegal labels are rejected with the allowed values; three rejected calls pause the slot; 'evaluation in progress' never counts as a rejection (TLS-02, TLS-03, ENG-06).
5. Loop limit 3 is enforced and at_limit routes to the gate with open findings (ENG-05).
6. Pause, resume, cancel and retry work from the run view and the API; cancel runs interrupt -> stop -> omnigent.closed; late submits are rejected; retry salvages and resets through the new generation's shell; every pause reason shows its copy and resume condition (ENG-06, API-02, SES-04, SES-06, WSP-06, WEB-04).
7. An accepted handoff closes its slot with the commit before stop, and any turn after accept pauses the run as paused(drift) (ENG-04, SES-04, WSP-06).
8. The run view shows a live overlay from server patches; reconnecting with Last-Event-ID loses no entries; the polling fallback works (API-02, WEB-04).
9. Each gate shows as one Inbox card with its context and is answerable from the Inbox, the run view and /approve; duplicate answers advance once, stale answers are refused, a non-owner gets not_permitted, no gate auto-resolves, and gates re-publish after restart (GTE-01, GTE-02, GTE-06).
10. Done-when uses claude-sdk exit codes and L1 fingerprints written before the tool result returns; S71 has landed and guards the host-path exit codes that import and detection use; the runner-path exit-status test is green (EVD-02, WSP-05).
11. Run-owned claude-sdk sessions refuse subscription OAuth; on supported hosts (macOS seatbelt, Linux with bwrap) reviewers are read-only by sandbox, elsewhere preflight refuses; engine rows are hidden from pickers; every run session has the cost backstop, which pauses as paused(budget) (HRN-02, PRF-01, RUL-01).
12. Drift pauses the run within one resync; archiving the anchor has its defined outcome; typing into a step session never triggers a nudge; 529, 429 and 401 map to backoff, paused(plan_limit) and paused(auth) (SES-08, SES-09).
13. The guarantees panel shows only labels that trace to a mechanism; the never-over-claim property test is green; SDK-mode agents read 'Claude' (RUL-02, WEB-13, WEB-04).
14. The M2 security review has no open high findings (OPS-06).
15. User outcome: internal users (default three, SPK-05) finish the journey on their own repo without help, and template to first simulate takes under five minutes (OPS-07).
16. The SQLite perf smoke with five concurrent runs meets the SPK-05 budgets, and the watchdog p95 is recorded for OQ-14 (DUR-04, SES-08, OPS-07).

*Conditional:* If SPK-05 records an external M2 audience, M2 also needs OPS-03 without its cut line, the OQ-30 counsel answers that distribution needs (pulled from OPS-05), and OPS-06 as a release gate.

### M3 Functional agent profile system (PH3)

**Dates.** Levelled week 21; planned week 24.5 (15% integration buffer); single-owner CPM 19 via FND-01 > ENG-01 > ENG-04 > ENG-11 > SES-08 > HRN-03 > HRN-07 > OPS-08.

**Features (12).** HRN-08, RUL-04, PRF-02, RUL-06, RUL-03, HRN-03, HRN-07, HRN-04, WEB-06, WEB-07, WEB-12, OPS-08.

**Product journeys exercised.** k, a (model access), i (plan limit), d (scenario editor).

**Proving journey.**

1. In the Agent Profiles desk, now in the nav, the user creates a 'Strict reviewer' profile from a custom agent and picks it for Review with capability chips.
2. They add a Required 'protect infra/**' rule and a Guidance rule from the catalog; the editor shows per-mode label chips.
3. They switch one reviewer to claude-native on a subscription. Read-only changes from Enforced to Verified and gate integrity shows as not Enforced. V9 flags 'protect infra/**' on a claude-native Implement and offers both remedies. The run executes under fail-closed hooks, a blackholed policy endpoint blocks the tool call, and /clear is followed.
4. A plan limit pauses the run with its reset time and it resumes on its own. Editing the profile mid-run leaves the run on rev N; the next run uses rev N+1.
5. A subscription-only user runs the single-agent template, which has no orchestrator, on claude-native.

**Exit criteria.**

1. Profile revisions are immutable, reinstall creates a new revision, pins hold, and drift is reported at slot start (PRF-02).
2. Capabilities are exposed per spelling and bench-tested; labels are computed per (mode, host); V9 rejects Required rules the mode cannot enforce; no unknown capability yields Enforced (HRN-08, RUL-06).
3. Catalog rules compile into guardrails with confirmation, and each template carries its bypass analysis (RUL-03, WEB-06).
4. IM-5: E2E-3 and E2E-4 are green inside the MVP template and the nightly bench covers claude-sdk and claude-native (OPS-08, RUL-04, HRN-03, HRN-07, HRN-08).
5. Plan-limit pauses show the S24 reset time and auto-resume; accounts are pinned per run (HRN-04, HRN-02).
6. The desk and picker show capability chips and used-by, and profiles_desk is on (WEB-07).
7. Authors can write and save their own simulation scenarios with per-version badges (WEB-12).
8. OQ-28 and OQ-35 written answers are recorded in docs/coral/decisions, and E2E-3 is green on subscription auth with the honest copy shown. Conditional: if OQ-28 has no answer, claude-native ships on API key behind its flag and journey step 3 runs on API key.
9. Native surfaces passed OPS-06's review before HRN-03 merged.
10. User outcome: the M3 journey passes in a dogfood session (OPS-08).

*Conditional:* OQ-28 deadline is the end of PH2; the fallback keeps claude-native behind claude_native_steps on API-key auth.

### M4 Integrated production-ready Coral (PH4 + PH5)

**Dates.** Levelled week 26.5; planned week 30.5 (15% integration buffer); single-owner CPM 21 via FND-01 > ENG-01 > ENG-04 > ENG-11 > SES-08 > HRN-03 > HRN-07 > OPS-08 > OPS-09.

**Features (23).** WSP-02, ENG-10, BRD-03, ENG-08, WSP-07, EVD-04, WSP-03, SES-10, ENG-09, TLS-04, SES-07, GTE-03, WEB-08, WEB-09, WEB-10, HRN-05, DUR-06, HRN-06, HRN-09, RUL-05, OPS-04, OPS-05, OPS-09.

**Product journeys exercised.** c (canvas), g (external), h (take-over), i (refresh, budget), j (lite).

**Proving journey.**

1. The user builds the PR-review loop on the canvas and the YAML keeps its comments.
2. The run repeats over labelled PRs ('3 of N', concurrency 2, batched per-item gates) with parallel claude-sdk and codex-native reviewers. Conditional on OQ-29; otherwise two claude-sdk reviewers.
3. A fix uses two writers in per-item worktrees based on each PR's head, with serial merges and mandatory Coral-run checks in a detached checkout; L2 fingerprints come over the host channel; pushing needs consent.
4. During the run: a budget pause raised from its elicitation, an orchestrator refresh that keeps every step reachable, take-over and hand-back on one step, a webhook for an unattended gate, and a cancel-and-restart from a node with carried handoffs. Afterwards a retention purge removes an old run, and the desktop app opens the run from a coral:// link.

**Exit criteria.**

1. IM-6 trust: the host op channel, L2 fingerprints and Coral-run checks with the integrity diff are live, and the evaluator gives identical verdicts across the backend swap (WSP-02, WSP-07, EVD-04).
2. IM-7 structure: E2E-5 is green at the two-session boundary and multi-writer merges always run post-merge checks (ENG-08, SES-10, ENG-09, WSP-03, TLS-04).
3. Canvas edits and the outline round-trip comments with keyboard and screen-reader parity (WEB-08, WEB-09).
4. The proof tests of RUL-05, SES-07, GTE-03, ENG-10, DUR-06, WEB-10 and HRN-05 are green; HRN-06 and HRN-09 are green or dark behind codex_steps if OQ-29 is unanswered.
5. IM-8 operations: SQLite and Postgres committed with CockroachDB, MySQL and split-DB lanes green; load meets the OQ-1 NFRs; the security review is closed; the release merge drill went through the playbook; 'Up: Yes' seams are merged upstream or tracked; licensing is signed off; the desktop build updates from the Coral feed (OPS-04, OPS-05, BRD-03).
6. User outcome: the M4 journey passes in a dogfood session (OPS-09).

*Conditional:* OQ-29 deadline is the start of PH4; the fallback keeps Codex modes dark and uses claude-sdk reviewers in the journey.

### post-M4 (PH6)

**Dates.** Levelled week 31; planned week 36 (15% integration buffer); single-owner CPM 17 via SPK-02 > SES-01 > SES-03 > SES-06 > SES-07 > EXT-02.

**Features (7).** WSP-04, EXT-01, EXT-02, EXT-03, EXT-04, EXT-05, GTE-04.

**Product journeys exercised.** l (suggestions), m (sharing via git), g (push).

**Proving journey.**

1. No milestone exit. Each feature is gated by its open questions.

**Exit criteria.**

1. Features: WSP-04, EXT-01..05, GTE-04.
2. Deferred gap parts are listed in section 7.

### Journey coverage

| Product journey | Features | When |
|---|---|---|
| (a) First run, brand and onboarding | BRD-01, BRD-02, OPS-03, HRN-02, WEB-03, HRN-04 | M1 skin; M2 API-key path and fix links; M3 model access |
| (b) Create a workflow from a template | ENG-07, DUR-02, WEB-02, WEB-03, EVD-03 | M1 API; M2 UI |
| (c) Author and edit (YAML, canvas) | ENG-02, ENG-03, WEB-11, WEB-08, WEB-09 | M2 YAML; M4 canvas |
| (d) Simulate and save as test case | ENG-07, DUR-02, WEB-01, WEB-12 | M1 API; M2 preset UI; M3 scenario editor |
| (e) Start a run | WEB-03, API-02, WSP-01, HRN-02 | M2 |
| (f) Monitor a live run | WEB-04, WEB-13, API-02, WEB-10 | M2 basic; M4 depth |
| (g) Answer gates and ask_user | GTE-01, GTE-02, GTE-06, TLS-05, GTE-03, GTE-04 | M2 in-app; M4 webhook; post-M4 push |
| (h) Steer, take over, hand back | WEB-05, SES-04, SES-07, WEB-10 | M2 steer; M4 take-over |
| (i) Pauses and recovery | ENG-06, SES-06, SES-08, SES-09, DUR-05, HRN-04, SES-07, RUL-05 | M2 core; M3 plan limit; M4 refresh and budget |
| (j) Amend a running run | ENG-10 | M4 restart-from-node; full amendments deferred |
| (k) Manage agent profiles | PRF-01, PRF-02, WEB-07, RUL-03, WEB-06 | M2 seeded; M3 desk |
| (l) Run history and suggestions | WEB-13, ENG-10, EXT-01, EXT-03 | M2 history; post-M4 suggestions and export |
| (m) Share via git and templates | EXT-03, EXT-04, EXT-05 | post-M4 |

## 4. Integration milestones

Each IM is dated by the levelled finish of the features that must converge, owned by one lead, proven by one test, and listed as an exit item of the named features.

| IM | Name | Week (levelled) | Owning lead | Dated by | Proving test | Exit item of |
|---|---|---|---|---|---|---|
| IM-0 | Contract freeze | 3 | Tech lead with the ENGINE and INTEGRATION leads | ENG-01, SES-01, API-01 | K1-K4, K6-K8, K10, K12, K14, K16, K18 and K19 at v1; FakeOmni passes K4 conformance; the OpenAPI drift check runs; a consumer stub in each team compiles against them. | ENG-01, SES-01, API-01, OPS-01 |
| IM-1 | Seam and store spine | 7 | INTEGRATION lead | SES-02, TLS-01, GTE-05, DUR-03, ENG-04 | A scripted coral_ test tool on an HTTP-created session drives an ENG-04 skeleton transition committed by DUR-03 with CAS; an SES-02 observer sees the edge; a GTE-05 request-free elicitation resolves once. | SES-02, TLS-01, GTE-05, DUR-03, ENG-04 |
| IM-2 | Walking skeleton | 11.5 | INTEGRATION lead | SES-05 | E2E-1 on Tier B: one-step workflow -> anchor and step child -> submit -> gate answered via /approve -> end; the K4 conformance suite passes on FakeOmni and the real facade. | SES-05, SES-03, SES-04, TLS-02, GTE-01 |
| IM-3 | MVP template headless | 11.5 | OPS lead | TLS-03, TLS-02, EVD-02, WSP-06, PRF-01, HRN-02, DUR-05, SES-06, SES-08, SES-09, RUL-01 | Tier B run of the TLD-01 template: loop to limit 3, evidence reject then accept, reviewer write denied, close fencing, SIGTERM recovery. | OPS-07, TLS-03, EVD-02, WSP-06, DUR-05, SES-06 |
| IM-4 | UI on a live backend | 11.5 | WEB lead | WEB-03, WEB-04, WEB-13, GTE-02, GTE-06, API-02 | In the CI-only browser lane: start dialog -> live run view over SSE -> one Inbox card per gate -> answer -> outcome panel, against a real server. | OPS-07, WEB-03, WEB-04, WEB-13, GTE-02, API-02 |
| IM-5 | Native step | 20 | HARNESS lead | HRN-03, HRN-07, RUL-04, RUL-06 | E2E-3 and E2E-4 inside the MVP template, with labels switching to Verified. | OPS-08, HRN-03, RUL-04 |
| IM-6 | Workspace backend swap | 20 | WORKSPACE lead | WSP-07 | The evaluator gives identical verdicts on the session-shell and host-channel K13 backends. | WSP-07, WSP-02 |
| IM-7 | Structure showcase | 22.5 | INTEGRATION lead | SES-10, WSP-03, EVD-04 | PR-review loop: repeat (3 of N), parallel reviewers, two writers, serial merges, post-merge checks. | SES-10, WSP-03, EVD-04, OPS-09 |
| IM-8 | Release rehearsal and security closure | 25.5 | OPS lead | OPS-04, OPS-05 | The release merge drill through the playbook with all lanes green; security findings closed; licences signed off. | OPS-04, OPS-05 |

Milestones on the same scale: M1 week 9.5, M2 week 13.5, M3 week 21, M4 week 26.5 (levelled).

## 5. Decisions log

One line per structural choice; per-issue decisions are in `changelog_v2.md`. 'Move' lines change mandated milestone placements; 'condition' lines record what a TLD needs to hold. Ids in trailing parentheses are critique issue ids; there, ENG-nn means the engineer critique, not an engine feature.

1. Kept from v1: contract-first catalog with a fake or fixtures per contract; time-boxed PH0 spikes with costed fallbacks; G-04 split into ENG-04, ENG-05 and ENG-06; the MVP template as package data in ENG-07; DUR-02 as the M1 API slice; credential guard at M2 and model access at M3; S21 conditional in HRN-02; S3 for terminal_launch_args only; S65 not planned.
2. Kept from v1 milestone moves: S13/S63 credential guard M3 -> M2 (HRN-02); claude-sdk reviewer write_paths: [] M3 -> M2 (PRF-01); per-session cost backstop M4 -> M2 (RUL-01); plan-limit pause at M3; repo export post-M4; versions, diff and restart-from-node at M4; headless codex at M4, with HRN-09 as the first cut.
3. Walking skeleton (SES-05) and M2 acceptance (OPS-07) are separate features again, reversing v1 decision 15: the merged feature could not start before week 16.5 (ARC-09, ADV-01, ENG-01, DEL-01). The acceptance lanes move to WS-OPS as OPS-07, OPS-08 and OPS-09, one per milestone, each hard on the previous one (DEL-09, DEL-10).
4. Named skeleton slices (SES-03#skeleton, SES-04#skeleton, TLS-02#skeleton, GTE-01#skeleton) are recorded in the JSON slice_deps field so the schedule can see them; each is an IM-2 exit item of its feature (ADV-01, DEL-01).
5. Import boundary is three tiers enforced per module: a pure layer, coral.omni as the only importer of omnigent.* (server, runner and host subpackages, privates through coral/omni/_upstream.py), and coral.db with an allowlist; K4 gains sub-protocols with one implementer each (ARC-01).
6. One plugin key: K17 PluginRegistration also carries policy modules (fatal on import failure), observers, verdict handlers, tool handlers, policy providers, account callbacks and seed agents; runner and host entry points are listed in a process map with a coral_runner:n host token (ARC-02, ARC-03).
7. Contracts move earlier: K18 and K19 schemas into SES-01 (PH0); K9 producer HRN-01 is now an M1 feature; the done_when authoring block joins K1 while K11 stays with EVD-01 after SPK-04; K13 is frozen as WSP-01's first PR from SPK-04's draft; K20 freezes at M2 as WSP-02's first PR; new K21 effect executor registry ships with K5 (ARC-06, ARC-07, ARC-22, ADV-27, DEL-12, DEL-17).
8. Each table lands with its owner as a standalone coral_00NN_<feature> migration through DUR-01's train; DUR-01 keeps K5, K21 and coral_0001 only; the queue layout (OQ-34) is decided once, in K5, and DUR-04 lands the queue and timer tables (ARC-08, ENG-06, ADV-26).
9. Content hash covers the canonical authoring document only; derivations move into the ENG-02 compiler as K1's Analysis section; ENG-04 builds on ENG-01's compiled-IR fixtures, so the M1 path drops from 13.5 to 11.5 single-owner weeks (ARC-11, ADV-23, DEL-05).
10. Pure reconcile, the per-mode turn-end rule and the failed-turn classifier live in the new ENG-11, so I7 is a pure property test and WS-ENGINE has PH2 work (ARC-05, ADV-05, ADV-14).
11. Step close is fenced: K2 adds closing and post_close_activity; SES-04 runs closing -> turn end -> commit -> pending-input check -> stop -> closed; WEB-05 disables the composer while closing (ADV-02, ADV-03, ENG-02).
12. Restart ladder order is fixed (fence and stop, new generation without brief, reconnect, salvage and reset through the new shell, brief) and K13 states the op-host rule (ADV-03, ENG-02).
13. Observations are durable before the tool result returns: S68 is one fan-out line in pr_observer.py, S69(a) is the only M2 transport, K11 adds a watermark, and TLS-02 returns 'evaluation in progress' instead of a false rejection (ADV-04, ENG-08).
14. Anchor variant pinned: a turnless, never-replaced run session with the orchestrator and steps as own-runner children (created with host_id); no session policies on the anchor; PRF-01 seeds the inert anchor agent; SES-03 files the run row into a 'Coral runs' project; WEB-05 owns the anchor's page (ARC-15, ADV-08, PRO-07, ENG-20).
15. Splits to hold features within L and make cut lines real: SES-04/SES-08, SES-06/SES-09, TLS-03/TLS-05, WSP-01/WSP-05/WSP-06, WSP-02/WSP-07, HRN-01/HRN-08, HRN-03/HRN-07, HRN-06/HRN-09, WEB-02/WEB-11, WEB-04/WEB-13, WEB-01/WEB-12, RUL-02/RUL-06, ENG-08/SES-10, GTE-01/GTE-05, GTE-02/GTE-06, FND-01/FND-05, SPK-01/SPK-05.
16. S1b leaves M2: origin is an optional keyword defaulting to 'unknown', set at the four sites the turn-end rule needs; the other sites go upstream through OPS-05 (ARC-13, ADV-12, ENG-09).
17. Dormant seams move to their first consumer: S9, S11 and the native S12 transport to HRN-03, the Codex S11 site to HRN-05, S69(b) to HRN-03; TLS-01 introduces FrameworkInstructions at the prompt.py boundary (ARC-17, ARC-21, ENG-10).
18. Modify-class hot seams (S43, S6b, S14, S40, S72, S62) are upstream-first with explicit OPS-01 budget exceptions; the S40 dispatcher lives in a new omnigent/host/workspace_ops.py; TLS-01 adds its lookup beside the sys_advise_models intercept (ARC-13).
19. Every seam feature opens its upstream PR at landing; OPS-01 reports gaps; OPS-05 drives them to merge and retires anchors (ARC-14).
20. The seam train is a landing-order guideline with one WS-INTEGRATION seam-train owner, enforced by fork-guard anchors and rebase-on-conflict, not by dependency edges (ENG-07, ADV-29, DEL-13 partly).
21. Real upstream merges from nightly^1 every two weeks start in PH1 with a rotating merge owner; the release drill stays in OPS-05 (DEL-14).
22. Many hard edges become soft where a contract or fake exists (ENG-04, SES-04, GTE-01, TLS-03, SES-06, EVD-02, RUL-02, API-02, WEB-03, WSP-03, EVD-04), and missing hard edges are added (DUR-03 and DUR-05 on FND-04, FND-04 on FND-03, ENG-01 and API-01 on SPK-01, HRN-06 on SES-04 and TLS-01) (ARC-12, ARC-19, ADV-09, ENG-04, ENG-05, DEL-02, DEL-18).
23. Phase labels are start windows in weeks; SES-03, PRF-01, WSP-01, HRN-02, EVD-02 and EVD-03 move to PH1; RUL-04 and HRN-08 start in PH2; the PH4 window opens at M2 with PH3; HRN-05 and DUR-06 move to PH4; BRD-03 starts in PH3 (DEL-04, DEL-16, DEL-21, DEL-28).
24. Merge-dark strategy: /v1/coral/info returns a sub-feature map (editor, canvas_edit, claude_native_steps, codex_steps, webhooks, budgets, takeover, restart_from_node, profiles_desk); S50 and S52 providers are O(1) no-ops for non-Coral sessions; wire seams carry the coral_runner:n token (ENG-03, ENG-11, PRO-16).
25. Security is staged: SPK-01 runs a PH0 threat-model checkpoint, OPS-06 reviews M2 surfaces by M2 exit and signs off the K20 freeze and HRN-03, OPS-04 closes the review at M4; GTE-01's S6b handler enforces owner-only answers (ARC-23, ADV-19, DEL-20, ENG-15, PRO-17).
26. Spend is visible from M2 (API-02 estimate, WEB-04 header, WEB-13 list) and the backstop pauses as paused(budget); run budgets stay in RUL-05 at M4 (PRO-05).
27. Move: claude-sdk promise labels and a read-only guarantees panel M3 -> M2 (RUL-02, WEB-13), reversing v1 decision 45, because PC-08 and product §9.1 item 12 put guarantees in the MVP; every label traces to a tested mechanism and the never-over-claim fixture includes the host sandbox (PRO-01, PRO-03, PRO-11).
28. Move: capability bench, S59, S78 and non-claude-sdk registry values M2 -> M3 (HRN-08); M2 keeps K9 and the claude-sdk row in HRN-01 (ADV-16).
29. Move: Simulate scenario editor and saved-test badges M2 -> M3 (WEB-12); M2 keeps the diagram, overlay and preset simulations (ADV-25, PRO-14).
30. Move: CI-file and pre-commit command parsers M2 -> M4 (EVD-04) (ADV-25).
31. Move: repeat and parallel semantics start in PH2 (ENG-08, still M4) so scope keys are exercised at depth before M2 freezes the state shape (ADV-18, DEL-15).
32. Move: K20 and the host op channel start at M2 (WSP-02 in PH3); write ops and the swap stay in PH4 (WSP-07) (ADV-17, DEL-16, DEL-17).
33. TLD-02 condition: the anchor variant is pinned in ADR-05; option B needs engine relaunch of own-runner children (app.py:4273; child_session_recovery.py:164), which SES-06 builds.
34. TLD-07 condition: workflows with an orchestrator need an Anthropic API key through M4; subscription users get HRN-03's single-agent template at M3; OQ-28 has a PH2-end deadline with a fallback.
35. TLD-08 condition: a single active worker replica comes from DUR-04's DB lease, not from config detection; SQLite contention is smoke-tested at M2.
36. TLD-09 condition: one canonical Inbox card per gate (GTE-02 claims coral_gate_ and coral_question_ ids); native steps cannot hold gate integrity at Enforced (D25).
37. TLD-10 condition: S71 guards host-path exit codes only; runner-path codes are covered by EVD-02's test; observations are durable before the tool result returns.
38. TLD-11 condition: labels are computed per (mode, host sandbox backend); a host without an FS sandbox never yields Enforced.
39. TLD-17 condition: the K4 conformance suite runs over FakeOmni and the real facade as L3 once SES-03 lands; real merges, not only rehearsals, start in PH1.
40. TLD-21 condition: ENG-08's first PR exercises item_path at depth 2 before M2 exit.
41. No TLD was found unsound; the conditions above are carried by named features.

## 6. Delivery rules

### 6.1 Definition of done (all features)

1. Seam features: the first proof is a component test in the nearest existing scenario (S1 test_session_live_state.py; S5 test_pending_elicitations.py and test_subagent_block_notifier.py; S6 test_sessions_elicitation_api.py; S10 test_sessions_mcp_proxy_policy_retry.py; S8 test_scheduled_task_tool_dispatch.py; S52 tests/runtime/policies/; S54 test_agent_store.py; S71 and S72 tests/host/), plus one regression test that a non-Coral session is unchanged.
2. Seam features open the upstream PR for each 'Up: Yes' seam when the fork PR lands and record it in .coral/upstream.yaml; Modify-class seams (S43, S6b, S14, S40, S72, S62) are upstream-first with a ledgered budget exception.
3. Table-adding features: the first PR is a standalone coral_00NN_<feature> migration through DUR-01's train, with models-match and four-lane plus split-DB tests.
4. Effect-executing features register through K21 and pass its conformance test with the fake drainer.
5. Wire seams are covered by the coral_runner:n host token; tests/e2e/coral skips against hosts or runners without it.
6. Partly built desks and modes merge dark behind their /v1/coral/info sub-feature key and flip it at their exit.
7. Web features name which assertions are vitest pure-module tests and which run in the CI-only tests/browser_ui/workflows/ lane; nobody runs browser checks locally.
8. Each IM is an exit item of the features named in section 4.

### 6.2 Staffing assumed by the levelled schedule

| Workstream | Engineers | Notes |
|---|---|---|
| WS-ENGINE | 3 | Three through M2 (ENG-04 takes two); one joins the IM-2 and IM-3 integration-support rotation for K2 changes. |
| WS-PLATFORM | 3 | Three through M2; at M2 one moves to GTE-03, DUR-06 and the OPS-04 load scenario. |
| WS-INTEGRATION | 4 | Includes the seam-train owner who lands hot-file seam PRs serially and dark. |
| WS-HARNESS | 2 | PRF-01 and HRN-02 in PH1; RUL-04 and HRN-08 in PH2; native modes from M2. |
| WS-WORKSPACE | 2 | WSP-05 and WSP-01 in PH1; WSP-02 from M2; owns the spike 8 contingency. |
| WS-WEB | 3 | WS-BRAND's engineer folds into WEB after BRD-02 and returns for BRD-03. |
| WS-BRAND | 1 | BRD-01 and BRD-02 in PH1, BRD-03 from M2. |
| WS-OPS | 2 | Plus the rotating merge owner (0.25-0.5 FTE) and the acceptance lanes. |
| Tech lead and PM | - | Own SPK-01 and SPK-05 (decision brokering), not counted as engineers. |

Total: 20 engineers. With two engine engineers instead of three, M1 slips about 2.5 weeks and M2 about 2 weeks, because ENG-04 occupies both and the M1 engine chain serializes behind it.

### 6.3 M2 cut list (ranked)

Already out of M2 in v2: S1b (OPS-05), the bench, S59 and other modes (HRN-08), S69(b) (HRN-03), CI and pre-commit parsers (EVD-04), the scenario editor and badges (WEB-12).

| Rank | Cut | Fallback | Single-owner weeks saved |
|---|---|---|---|
| 1 | TLS-05 coral_ask_user | Steps report blocked and the orchestrator asks in chat | 2 |
| 2 | WEB-11 YAML editor | Read-only YAML, upload, and the template parameters in WEB-03 | 2 |
| 3 | WEB-05 steering composer | Read-only agent panes plus 'open session' | 1 |
| 4 | OPS-03 distribution identity (only if M2 stays internal) | Run as omnigent with Coral enabled | 1 |
| 5 | EVD-03 justfile and Makefile parsers | Keep package.json and pyproject.toml detection | 0.5 |
| 6 | WEB-01 preset Simulate button | Simulate through the API and CLI | 1 |

### 6.4 Conditional dependencies

| Feature | Trigger and consequence |
|---|---|
| FND-04 | If spike 4 fails: Tier B uses an explicit test-only openai-agents mode (turn-end rule in ENG-11, K9 row in HRN-01, bundle in PRF-01) and lists the M2 exit criteria that lane cannot prove |
| OPS-03 | If SPK-05 records an external M2 audience: no cut line, and this is part of the M2 release gate |
| ENG-11 | If spike 4 fails: add a test-only openai-agents turn-end rule for Tier B |
| HRN-01 | If spike 4 fails: add a test-only openai-agents row |
| RUL-01 | If spike 1 fails: hard on HRN-02's S21 PreToolUse hook for claude-sdk enforcement |
| RUL-01 | If SPK-02 probe (e) shows a closed anchor no longer resolves elicitations: add the anchor input DENY keyed on coral.role=run |
| PRF-01 | If spike 4 fails: add a test-only openai-agents step bundle |
| SES-03 | If SPK-02 rejects option B: +3-4 weeks for the top-level family fallback; S35 moves from not planned to this feature |
| SES-06 | If spike 16 fails: this feature owns the S27 reaper retest at M2 (moved from SES-07) |
| WSP-06 | If spike 8 fails: the host-channel commit, reset and salvage ops move from WSP-02 into this feature in PH2 (+3 weeks, WS-WORKSPACE) |
| OPS-06 | If SPK-05 records an external M2 audience: this review is part of the M2 release gate |
| HRN-03 | If OQ-28 has no written answer by the end of PH2: ship on API key only behind claude_native_steps and rewrite M3 journey step 3 |
| HRN-05 | If OQ-29 has no answer by PH4 start: stays dark behind codex_steps and the M4 journey uses two claude-sdk reviewers |
| HRN-06 | If OQ-29 has no answer by PH4 start: stays dark behind codex_steps |
| OPS-05 | If SPK-05 records an external M2 audience: the OQ-30 counsel answers that distribution needs are pulled forward to M2 |

### 6.5 Hot-file landing order

A landing-order guideline, not a dependency gate: the WS-INTEGRATION seam-train owner lands hot-file seam PRs serially and dark, before the feature logic that uses them, rebased on the nightly^1 merge; fork-guard anchors and rebase-on-conflict enforce it.

| Hot file | Landing order (feature: seams) |
|---|---|
| `omnigent/server/app.py` | FND-02: S32 (plugin registration and policy-module merge), then SES-02: S41 |
| `omnigent/server/routes/_sessions/helpers.py` | SES-02: S1 (origin at two sites), S43, then TLS-01: S49, then HRN-03: S3, then HRN-07: S45, then HRN-05: S62, then EXT-04: S26 |
| `omnigent/server/routes/_sessions/orchestration.py` | SES-02: S1 bypasses, S43, then TLS-01: S10 (lookup beside the intercept), then GTE-05: S6b, then EVD-02: S69(a) |
| `omnigent/server/routes/sessions/routes_events.py` | SES-02: S42 and the archive-idle origin, then GTE-05: S6a, then HRN-03: S69(b), then HRN-07: S45, then HRN-05: S2 |
| `omnigent/runner/app.py` | SES-02: S43, then SES-06: S27 retest (only if spike 16 fails), else SES-07: S27, then HRN-09: S19 |
| `omnigent/runner/tool_dispatch.py` | TLS-01: S8, then HRN-03: S9 |
| `omnigent/runner/pr_observer.py` | EVD-02: S68 (one fan-out line; none of the four call sites change) |
| `omnigent/runner/native/orchestration.py` | HRN-03: S11, S12 native transport, S64 |
| `omnigent/harnesses/claude_native/bridge.py` | RUL-04: S14 only |
| `omnigent/harnesses/codex_native/app_server.py` | HRN-05: S11 Codex site, S15 |
| `omnigent/host/connect.py` | WSP-05: S71, then WSP-02: S40 (one-line registration), then EXT-03: S74 |
| `omnigent/host/frames.py` | TLS-01: S50 capability contribution, then WSP-01: S72, then WSP-02: S40 registration, then EVD-04: S72 detached mode |
| `omnigent/inner/claude_sdk_executor.py` | HRN-02: S13, S63 (S21 if spike 1 fails), then HRN-04: S24 |
| `omnigent/inner/codex_executor.py` | HRN-05: S24 Codex branch, then HRN-06: S20, S61, S67, then HRN-09: S18, S60 |
| `omnigent/runtime/policies/builder.py` | RUL-01: S52 only (RUL-05 uses the provider) |
| `omnigent/runtime/prompt.py` | TLS-01: S12 FrameworkInstructions only |
| `omnigent/server/schemas.py` | SES-07: S25, then WSP-04: S28 |
| `omnigent/server/routes/builtin_agents.py` | PRF-01: S54, then PRF-02: S66, then EXT-04: S53 |
| `web/src/pages/InboxPage.tsx` | BRD-02: S84, then GTE-02: S37 (one-line registry spread) |
| `web/src/App.tsx and web/src/shell/Sidebar.tsx` | BRD-02 only (S34, S80) |
| `pyproject.toml` | FND-01: S29 and the coral entry point, then FND-05: S39 roots |

## 7. Deferred gap parts and unplanned seams

Every G-row has an owner in section 2. These sub-parts are not scheduled in M1-M4 or PH6:

| Deferred part | Reason |
|---|---|
| G-10 (Sub-workflow invocation) | No M1-M4 journey or template needs it; the kind stays reserved and hidden in K1. |
| G-11 (multi-replica sharding) | v1 is single replica (TLD-08): DUR-04's DB worker lease keeps one active worker replica and FND-02 refuses host sharding; sharded workers are unscheduled. |
| G-33 and G-55 (claude-native orchestrator) | The orchestrator stays claude-sdk through M4 (TLD-07), so workflows with an orchestrator need an API key; subscription users get HRN-03's single-agent template at M3. |
| G-37 (APNs and FCM mobile push) | Needs app ids and store decisions (OQ-31) and mobile scope (OQ-23); Web Push (GTE-04) comes first post-M4. |
| G-38 and G-61 (plain-folder workspaces and fingerprints) | Git worktrees only until a non-code persona is confirmed (OQ-1); needs content-hash manifests first. |
| G-42 and G-48 (free-text LLM translation of done-when and rules) | TLD-19: v1 is the detected-command picker (EVD-03, WEB-03) and the typed catalog (RUL-03); an engine-owned translator session is unscheduled post-M4. |
| G-65 (full 'Apply to this run' amendments) | TLD-18: ENG-10 ships cancel-and-restart-from-node; full amendments are unscheduled post-M4 (OQ-20). |
| G-66 (exhaustive Simulate, V11) | Replaced by block-structure validation plus scripted Simulate (X-25, R-24); revisit as a sampling check. |
| G-79 (hero workflow chip, OQ-7 option b) | SPK-01 defaults the hero to a plain session composer with Coral copy through M4; a run-start chip would go to WEB-03 if option b is chosen later. |
| G-87 (claude-sdk fake) | None exists; the mock ANTHROPIC_BASE_URL lane (if spike 4 passes) or a test-only openai-agents lane plus the credentialed nightly stand in. |
| G-90 (workflows as tools or APIs, marketplace) | Mentioned only in D§15 with no product spec; EXT-05 covers the Automations trigger. |

Seams not planned (every other seam has exactly one owner):

| Seam | Reason |
|---|---|
| S17 | claude-sdk sub-agent attribution is moot: run sessions expose no vendor sub-agents (S63 contract test in HRN-02). Revisit only if that changes. |
| S33 | Upstream Feature enum flag replaced by the Coral-owned GET /v1/coral/info gate (TLD-03, R-21). |
| S35 | Watch-set union is needed only under the topology fallback; costed as the SES-03 contingency (TLD-02). |
| S44 | Optional shared turn-outcome classifier; ENG-11's pure rule and classifier do not need it. Reconsider if codex-native rules diverge. |
| S47 | Child-capable continue-in-fork: refresh is a slot restart (TLD-13, R-8). |
| S48 | hold_started callback: polling runner_last_seen in SES-06 suffices. |
| S55 | Caller-supplied id through HTTP create: the facade creates sessions through the store with derived ids (X-6). |
| S65 | tool_groups.session_reads is an AgentSpec and parser change, which TLD-04 rules out; EXT-02 scopes inputs with a coral.omni.policies DENY instead. |
| S73 | Run sessions carry workspace= and no git options, so session-delete worktree cleanup never fires; WSP-01 keeps this as a tested invariant (TLD-12). |

Conditional and amended owners: S21 (HRN-02) only if spike 1 shows can_use_tool is skipped; S51 (SES-03) only if SPK-02 confirms children; S35 moves to SES-03 only under the topology fallback; S66 (PRF-02) optional; S3 (HRN-03) for terminal_launch_args only; S27 moves to SES-06 if spike 16 fails; S1b is an upstream-only PR (OPS-05). Ledger amendments by later features: S12 native transport (HRN-03) and Codex text (HRN-05); S11 Codex site (HRN-05); S69(b) outbox (HRN-03); S72 detached mode (EVD-04).

**Seam owner index.** S1 SES-02; S1b OPS-05; S2 HRN-05; S3 HRN-03; S4 SES-02; S5 GTE-05; S6 GTE-05; S6a GTE-05; S6b GTE-05; S7 TLS-01; S8 TLS-01; S9 HRN-03; S10 TLS-01; S11 HRN-03; S12 TLS-01; S13 HRN-02; S14 RUL-04; S15 HRN-05; S16 RUL-04; S17 not planned; S18 HRN-09; S19 HRN-09; S20 HRN-06; S21 HRN-02; S22 HRN-01; S23 HRN-08; S24 HRN-04; S25 SES-07; S26 EXT-04; S27 SES-07; S28 WSP-04; S29 FND-01; S30 FND-03; S31 FND-03; S32 FND-02; S33 not planned; S34 BRD-02; S35 not planned; S36 GTE-02; S37 GTE-02; S38 BRD-03; S39 FND-05; S39b FND-05; S39c FND-05; S39d FND-05; S39e FND-05; S40 WSP-02; S40b WSP-02; S41 SES-02; S42 SES-02; S43 SES-02; S44 not planned; S45 HRN-07; S46 EXT-04; S47 not planned; S48 not planned; S49 TLS-01; S50 TLS-01; S51 SES-03; S52 RUL-01; S53 EXT-04; S54 PRF-01; S55 not planned; S56 DUR-06; S57 FND-03; S58 FND-03; S59 HRN-08; S60 HRN-09; S61 HRN-06; S62 HRN-05; S63 HRN-02; S64 HRN-03; S65 not planned; S66 PRF-02; S67 HRN-06; S68 EVD-02; S69 EVD-02; S70 WSP-04; S71 WSP-05; S72 WSP-01; S73 not planned; S74 EXT-03; S75 OPS-03; S76 FND-05; S77 OPS-02; S78 HRN-08; S79 BRD-01; S80 BRD-02; S81 BRD-01; S82 BRD-01; S83 BRD-01; S84 BRD-02; S85 GTE-02; S86 WEB-05; S87 BRD-03; S88 BRD-03; S89 BRD-01.

**G-row owner index.** G-01 ENG-01, ENG-02; G-02 ENG-03; G-03 ENG-01, ENG-02, ENG-03, ENG-04, ENG-05; G-04 ENG-04, ENG-05; G-05 ENG-01, ENG-04; G-06 ENG-06, ENG-09; G-07 DUR-03, ENG-06, SES-04, API-02; G-08 ENG-08, SES-10, WEB-10; G-09 ENG-08, SES-10; G-10 ENG-09; G-11 DUR-04, ENG-11, DUR-05, OPS-04; G-12 FND-01, FND-05; G-13 FND-03; G-14 DUR-01, DUR-02, DUR-03, PRF-02, ENG-10; G-15 DUR-02; G-16 DUR-05, DUR-06; G-17 FND-02; G-18 SES-01, SES-03; G-19 SES-02, SES-04; G-20 SES-02, SES-08, HRN-05; G-21 ENG-11, SES-08; G-22 SPK-02, SES-03; G-23 ENG-11, SES-08, SES-06; G-24 SES-09, HRN-07, EXT-04; G-25 SES-01, DUR-04, SES-03; G-26 TLS-01; G-27 TLS-01; G-28 TLS-02; G-29 TLS-03; G-30 TLS-05; G-31 TLS-04; G-32 PRF-01, TLS-03; G-33 TLS-03; G-34 ENG-04, ENG-06, GTE-01, API-02; G-35 GTE-05, GTE-01; G-36 GTE-06, GTE-02; G-37 GTE-03, GTE-04; G-38 SPK-04, WSP-05, EVD-02, WSP-02, WSP-07; G-39 EVD-02, HRN-03; G-40 EVD-01, EVD-02; G-41 EVD-03, EVD-04; G-42 EVD-03, WEB-03; G-43 EVD-04; G-44 SPK-03, HRN-01, HRN-08; G-45 RUL-01; G-46 RUL-01; G-47 PRF-01, RUL-02, RUL-06; G-48 RUL-03, WEB-06, ENG-09; G-49 RUL-04; G-50 PRF-01, PRF-02; G-51 SES-01, PRF-01; G-52 PRF-01, EXT-04; G-53 WEB-07; G-54 HRN-02, HRN-04; G-55 HRN-03; G-56 HRN-05, HRN-06, HRN-09; G-57 HRN-04; G-58 WSP-01, WSP-06, EVD-04; G-59 SPK-04, WSP-06, WSP-02, WSP-07; G-60 WSP-03; G-61 WSP-04; G-62 ENG-07, RUL-01, API-02, RUL-05; G-63 SES-07; G-64 SES-07; G-65 ENG-10; G-66 DUR-02, ENG-07; G-67 WEB-01, WEB-12, WEB-10; G-68 DUR-02, WSP-01, WEB-02, EXT-03; G-69 ENG-07, WEB-03; G-70 WEB-11; G-71 WEB-01; G-72 WEB-08, WEB-09; G-73 WEB-02, WEB-11, WEB-13, RUL-02, RUL-06, WEB-06; G-74 API-01, DUR-02, API-02; G-75 API-01, API-02, WEB-04; G-76 HRN-02, API-02, WEB-03; G-77 WEB-04, WEB-13, WEB-05, WEB-10; G-78 BRD-01; G-79 BRD-01; G-80 BRD-02; G-81 FND-02, BRD-02, WEB-02; G-82 BRD-03; G-83 OPS-01; G-84 OPS-02, OPS-05; G-85 FND-01, OPS-03; G-86 OPS-02, OPS-05; G-87 FND-04, DUR-05, SES-05, OPS-07, OPS-08, OPS-04, OPS-09; G-88 EXT-01; G-89 EXT-02; G-90 EXT-03, EXT-04, EXT-05.

## 8. Failure-mode ownership

| Failure mode | Owner and mechanism | Proving test |
|---|---|---|
| Server restart mid-effect; lost elicitation index | DUR-05 re-leases and reads before resend; GTE-01 re-publishes with stable ids | OPS-07 E2E-2 |
| Lost or bypassed turn-end edge | SES-08 persists edge facts; DUR-05 resync calls ENG-11's reconcile | ENG-11 I7 property test; DUR-05 commit-boundary suite |
| Duplicate queue delivery | K21 per-kind idempotency obligations; DUR-04 dispatch-time re-validation | K21 conformance test |
| Duplicate or late handoff; zombie turn after restart | TLS-02 receipts, evaluating lease and generation check; TLS-01 operation-id dedup; SES-06 never restarts inside the hold | TLS-02 proof; SES-06 proof |
| Stale read, version conflict, SQLITE_BUSY | DUR-03 reduce-and-retry; DUR-04 and SES-08 perf smoke | DUR-03 contention test; OPS-07 perf smoke |
| Gate answer vs reminder vs cancel | GTE-01 CAS and visit token; TLS-03 re-checks before reminding | GTE-01 proof |
| Laptop-sleep timer storm | ENG-06 coalescing | ENG-06 reducer test |
| Steering after an accepted handoff | ENG-04 closing state; SES-04 close sequence; WEB-05 disables the composer | SES-04 Tier B queued-input test |
| Observation arrives after an immediate submit | EVD-02 writes synchronously before the result returns; TLS-02 waits for the watermark | TLS-02 race test |
| Unclassified 529, 429 or 401 | ENG-11 classifier; SES-08 maps classes to backoff or pauses; HRN-04 adds S24 at M3 | SES-08 Tier B 529/429/401 case |
| Engine upgraded under a paused run | K1-K3 versions; DUR-05 paused(engine_upgrade); ENG-10 restart-from-node at M4 | OPS-07 engine-upgrade lane |
| Runner loss or host offline | SES-06 ladder: fence, new generation, reconnect, salvage and reset, then brief | SES-06 proof |
| Anchor archived, deleted or typed into | SES-03 input stance; SES-09 outcomes; WEB-05 anchor page | SES-09 proof |
| Drift (policy, archive, bundle); native /clear | SES-09 drift checks; PRF-01 digest check; HRN-07 via S45 | SES-09 and HRN-07 proofs |
| Orchestrator restarted after runner loss loses context | TLS-03 re-brief with the pending request, run summary and prior decisions | TLS-03 proof |
| A turn longer than the runner idle watchdog | Spike 16; if it fails, SES-06 runs the S27 retest at M2 | SPK-03 verdict; S27 retest |
| Native turn_completed lost between edge and enqueue | HRN-03 level-triggered fallback from transcript or pending input | HRN-03 E2E-3 dropped-edge variant |
| Old host without S72 head_commit or Coral entry points | WSP-01 falls back to rev-parse; SES-03 and HRN-02 refuse hosts without coral_runner | WSP-01 proof; FND-04 missing-token case |
| Runner reaped during a long gate | SES-04 calls ensure_runner_connected before every send | SES-04 dispatch test |
| Account revoked | DUR-05 writes paused(authority_revoked) as system | DUR-05 test |
| Reaper steals exit codes | WSP-05 (host path); EVD-02 runner-path test; WSP-07 contract test | WSP-05 and EVD-02 proofs |
| Cost amplification | ENG-03 V12; ENG-05 activation cap; RUL-01 backstop -> paused(budget) | RUL-01 proof |
| Unattended prompt stalls a step | SES-03 unattended-permission preflight; PRF-01 denies vendor ask tools | PRF-01 golden bundle test |
| A teammate with edit sharing answers a gate | GTE-01 S6b handler checks the run owner | GTE-01 proof |
| A native step approves its own gate (D25) | RUL-02 gate-integrity label; OPS-06 native review before HRN-03 merges | RUL-02 never-Enforced fixture |
| Upstream churn | OPS-01 guard; OPS-02 real merges every two weeks; K4 conformance as L3 | OPS-02 proof |

## 9. Migration train

Every Coral table lands as its owner's standalone migration PR through DUR-01's train (single head, models-match, four DB lanes plus the split-DB lane). Numbers after coral_0002 are assigned at merge in this order.

| Migration | Owner | Phase | Prerequisite |
|---|---|---|---|
| coral_0001_core | DUR-01 | PH1 | FND-03 at head; K5 |
| coral_0002_queue (queue, timers) | DUR-04 | PH1 | coral_0001; K5 layout (OQ-34) |
| session_bindings | SES-03 | PH1 | ADR-05 |
| stable_ids | SES-04 | PH1 | coral_0001 |
| step_agents | PRF-01 | PH1 | K12 |
| repo_bindings | WSP-01 | PH1 | K13 v1 |
| command_patterns | EVD-03 | PH1 | repo_bindings |
| observations (command observations, evidence results, watermark) | EVD-02 | PH1 | SPK-04 verdict; K11 |
| alerts | GTE-06 | PH2 | K19 |
| questions | TLS-05 | PH2 | alerts |
| profile_revisions | PRF-02 | PH3 | step_agents |
| lineage | ENG-10 | PH3 | coral_0001 |
| check_runs | EVD-04 | PH4 | observations |
| merge_state | WSP-03 | PH4 | repo_bindings |
| slot_control columns | SES-07 | PH4 | coral_0001 |
| notify (channels, deliveries) | GTE-03 | PH4 | alerts |
| saved_blocks | ENG-09 | PH4 | coral_0001 |
| budgets | RUL-05 | PH5 | coral_0001 |
| suggestions; run_grants; push_subscriptions | EXT-01; EXT-04; GTE-04 | PH6 | coral_0001; alerts |

## 10. Critical path, levelled schedule and phase windows

Weights: S=1, M=2, L=4.5 single-owner weeks. 'Staffed' uses calendar weeks for the two features staffed by two engineers (ENG-04 2.5, SPK-02 1). 'Levelled' list-schedules every feature by milestone priority within the section 6.2 staffing, with PH2 opening at week 4, PH3 and PH4 at M2, PH5 at M3 and PH6 at M4. 'Planned' adds a 15% integration buffer.

| Milestone | CPM single-owner | CPM staffed | Levelled | Planned | Staffed critical path |
|---|---|---|---|---|---|
| M1 | 11.5 | 9.5 | 9.5 | 11 | FND-01 > FND-03 > DUR-01 > DUR-02 |
| M2 | 13.5 | 13.5 | 13.5 | 16 | FND-01 > FND-03 > DUR-01 > DUR-04 > SES-05 > OPS-07 |
| M3 | 19 | 17 | 21 | 24.5 | FND-01 > FND-03 > DUR-01 > PRF-01 > HRN-03 > HRN-07 > OPS-08 |
| M4 | 21 | 20.5 | 26.5 | 30.5 | FND-01 > FND-03 > DUR-01 > PRF-01 > RUL-03 > ENG-09 > OPS-09 |

Chains converging on the M2 acceptance lane (OPS-07), staffed weeks, longest first:

- 13.5 weeks: FND-01 > FND-03 > DUR-01 > DUR-04 > SES-05 > OPS-07
- 13.5 weeks: FND-01 > FND-03 > DUR-01 > DUR-04 > DUR-05 > OPS-07
- 13.5 weeks: FND-01 > FND-03 > DUR-01 > DUR-03 > API-02 > OPS-07
- 13.5 weeks: FND-01 > FND-02 > BRD-02 > WEB-02 > WEB-03 > OPS-07
- 11.5 weeks: FND-01 > SES-01 > SES-03 > SES-09 > OPS-07
- 11.5 weeks: FND-01 > SES-01 > SES-03 > SES-06 > OPS-07

The M2 front is wide: the platform, web, session and engine chains finish within about two weeks of each other, which is why the planned date carries a buffer. Levers: three engine engineers through M2; SPK-02 with two engineers in week 1; K5 and K21 as DUR-01's first PR; skeleton slices merged by IM-2. Contingencies: topology fallback (+3-4 weeks on SES-03, adds S35); spike 8 failure moves the host-channel write ops into WSP-06 in PH2 (+3 weeks).

| Phase | Window (weeks) |
|---|---|
| PH0 | 0 - 3 |
| PH1 | 0 - 9.5 |
| PH2 | 4 - 13.5 |
| PH3 | 13.5 - 21 |
| PH4 | 13.5 - 26.5 |
| PH5 | 21 - 26.5 |
| PH6 | 26.5 - open |

Weighted load per workstream and phase (single-owner weeks; secondary loads counted on their workstream):

| Workstream | PH0 | PH1 | PH2 | PH3 | PH4 | PH5 | PH6 |
|---|---|---|---|---|---|---|---|
| WS-ENGINE | 2 | 16.5 | 6.5 | 3.5 | 4.5 | - | 5.5 |
| WS-PLATFORM | 2 | 17 | 8.5 | - | 3 | - | 2 |
| WS-INTEGRATION | 4 | 14.5 | 16 | 4.5 | 8.5 | 1 | 4.5 |
| WS-HARNESS | 1 | 7 | 4 | 9.5 | 4.5 | 4 | - |
| WS-WORKSPACE | 1 | 9 | 2 | 4.5 | 11 | - | 6.5 |
| WS-WEB | - | 4.5 | 17 | 7.5 | 14.5 | 1 | 5.5 |
| WS-BRAND | - | 4 | - | 2 | - | - | - |
| WS-OPS | 3 | 5 | 4 | 1 | - | 8.5 | - |
| Tech lead | 2 | - | - | - | - | - | - |

## 11. UI-surface ownership

One owner per surface for its loading, empty, error, paused, offline, permission and phone-width states; each state gets a component test.

| Surface | Owner | States and checks |
|---|---|---|
| Workflows desk and library | WEB-02 | loading, empty, error, no access; read-only YAML with problem list |
| YAML editor | WEB-11 | parse error, markers, 412 conflict, dirty guard, sub-feature off |
| Diagram and preset Simulate | WEB-01 | loading, layout pending, parse error with last valid, too large, needs input, deadlock highlight, limit reached, failing saved case |
| Simulate scenario editor | WEB-12 (M3) | invalid scenario, failing badge with expected vs actual |
| Gallery, Use-template and start dialogs | WEB-03 | gallery failed, host offline, nothing detected, preflight failures with fixes, auth deep link |
| Live run view | WEB-04 | loading, error with retry, not found or no access, reconnecting, each pause reason, waiting for the run owner; keyboard and screen-reader baseline with axe in CI |
| Runs list, outcome and guarantees panel | WEB-13 | empty, loading, error, each final state; phone-width layout (status, current step, gates, timeline) |
| Agent panes and anchor page | WEB-05 | runner offline, slot closing (composer disabled), step waiting on you |
| Inbox workflow kind and gate card | GTE-02 | empty, error, submitting, answered elsewhere, stale visit, no longer waiting, not permitted, waiting for owner, offline, waiting N hours, phone width |
| Agent Profiles desk and picker | WEB-07 (M3); nav hidden by BRD-02 until then | loading, empty, error, used-by, revision notice |
| Editor label chips and rule authoring | WEB-06 (M3) | unenforceable Required rule with remedies |
| Canvas, inspectors and outline | WEB-08, WEB-09 (M4) | round-trip errors; keyboard and screen-reader parity |
| Run view depth | WEB-10 (M4) | repeat, region, join waits, checks, merges, spend vs budget |
| Settings: notifications, model access, retention | GTE-03, HRN-04, DUR-06 (secondary WEB load) | channel test failure, auth state, purge confirmation |

