# Master feature list v2: changelog

Every blocker and major critique issue has a decision below; minor issues are listed when acted on (all were). Conflicts between critics were resolved for correctness first, then parallelism, then simplicity. Mechanical issues in v1: none.

| Severity | Accepted | Partially | Rejected |
|---|---|---|---|
| blocker | 7 | 0 | 0 |
| major | 76 | 10 | 0 |
| minor | 41 | 1 | 0 |

## Id map (v1 -> v2)

Ids are kept; split-off parts take the next free number in their area.

| v1 | v2 |
|---|---|
| SES-05 | SES-05 walking skeleton (narrowed); acceptance half -> OPS-07 |
| SES-04 | SES-04 engine dispatch and close; turn-end facts and outcomes -> SES-08; pure turn-end rule -> ENG-11 |
| SES-06 | SES-06 restart ladder; drift and user actions -> SES-09 |
| TLS-03 | TLS-03 orchestrator and choose_arrow; ask_user -> TLS-05 |
| GTE-01 | GTE-01 Coral gate surfacing; seam pack C -> GTE-05; alerts backend from GTE-02 -> GTE-06 |
| WSP-01 | WSP-01 bindings, worktree, K13; S71 -> WSP-05; commit, salvage, reset, retention -> WSP-06 |
| WSP-02 | WSP-02 host op channel and L2; write ops, swap and parity -> WSP-07 |
| HRN-01 | HRN-01 K9 and claude-sdk row (now M1); bench, S59, S78 and other modes -> HRN-08 |
| HRN-03 | HRN-03 claude-native step launch; /clear rotation following -> HRN-07 |
| HRN-06 | HRN-06 headless codex gating; routing and compaction -> HRN-09 |
| RUL-02 | RUL-02 claude-sdk labels (now M2); multi-mode labels and V9 -> RUL-06 |
| ENG-08 | ENG-08 pure repeat and parallel semantics (starts PH2); integration and showcase -> SES-10 |
| WEB-01 | WEB-01 diagram, overlay and preset Simulate; scenario editor and badges -> WEB-12 |
| WEB-02 | WEB-02 desk and library; YAML editor -> WEB-11 |
| WEB-04 | WEB-04 live run view; runs list, outcome, guarantees panel and phone layout -> WEB-13 |
| FND-01 | FND-01 skeleton, boundary and entry point; tooling roots -> FND-05 |
| SPK-01 | SPK-01 week-1 decisions and threat model; M2-M3 decisions -> SPK-05 |
| new | ENG-11 reconcile and decision functions; OPS-06 M2 security review; OPS-08 and OPS-09 M3 and M4 acceptance lanes |

## Decisions

| Issue | Severity | Decision | Note |
|---|---|---|---|
| ARC-01 | blocker | accepted | Three-tier boundary enforced per module by dev/lint (pure layer; coral.omni as the only omnigent importer with server, runner and host subpackages and a coral/omni/_upstream.py shim; coral.db allowlist). coral.policies moved to coral.omni.policies; plugin, tool provider, observer, bundles, sessions, scopes, artifacts, usage and preflight paths relocated under coral/omni/. K4 gains sub-protocols with one implementer each (FND-01, SES-01). |
| ARC-02 | major | accepted | K17 is one PluginRegistration covering routers, hooks, policy modules merged before load_registry (fatal on import failure), observers, verdict and tool handlers, policy providers, account callbacks and seed agents, plus a runner/host process map. RUL-01 drops policy_modules; FND-02's proof covers a broken policy import. |
| ARC-03 | major | accepted | coral_runner:n host token contributed through TLS-01's S50 line in host/frames.py and defined in K17; SES-03 and HRN-02's preflight refuse hosts without it; FND-04 has a missing-token Tier B case. |
| ARC-04 | major | accepted | K5 rule (operational DB only, plain id columns, no joins or shared transactions); FND-03 asserts the engine binding; FND-04 and OPS-02 add a split-DB lane; SES-03 idempotency and DUR-05 commit-boundary suites run on it. |
| ARC-05 | major | accepted | Pure reconcile(graph, state, facts, now) is in K2 and implemented in the new ENG-11 with the per-mode turn-end rule; DUR-05 keeps fact gathering and scheduling; the I7 property test targets ENG-11. |
| ARC-06 | major | accepted | New K21 effect executor registry, shipped in DUR-01's first PR beside K5; DUR-04 implements the drainer, fake drainer and conformance test; every executor feature consumes K21. |
| ARC-07 | major | partially | K18 and K19 schemas moved into SES-01 (PH0) and M1 exit 7 updated; K9 stays with HRN-01, which is now an M1 feature; the done_when authoring block joins K1 but K11 stays with EVD-01 because ADV-27 needs it frozen after SPK-04. Soft edges added: ENG-07->EVD-01, DUR-05->GTE-06, FND-02->API-01, FND-04->SES-01, RUL-03->HRN-08/RUL-02; ENG-06 consumes K19. |
| ARC-08 | major | accepted | DUR-01 ships K5, K21 and coral_0001 only and decides OQ-34; DUR-04 lands the queue and timer tables; every table-adding feature names its coral_00NN_<feature> migration; a train-order table is in the master (section 9). |
| ARC-09 | major | partially | Split as proposed into SES-05 walking skeleton and an M2 acceptance lane, but the acceptance lane is OPS-07 in WS-OPS (DEL-10) rather than the same owner, to unload WS-INTEGRATION in PH2. M2 exit 1 cites OPS-07. |
| ARC-10 | major | accepted | New PH1 enabler GTE-05 owns S5, S6, S6a and S6b with upstream PRs, tested on ordinary sessions; GTE-01 keeps Coral gate surfacing in PH2. |
| ARC-11 | major | accepted | Content hash over the canonical authoring document; join, region, loop-table, label-set and checked-part derivation moved into ENG-02 as K1's Analysis; ENG-04 hard on ENG-01 only; ENG-05 hard on ENG-02 and ENG-04, soft on ENG-03. M1 single-owner path is 11.5 weeks. |
| ARC-12 | major | accepted | RUL-02 hard on ENG-03, EVD-01 and HRN-01 (now M1), soft on EVD-02; TLS-03 soft on TLS-02 and PRF-01; EVD-02 soft on WSP-01 and hard on the S71 feature WSP-05. |
| ARC-13 | major | accepted | S1b out of SES-02 and K18 (origin optional, default 'unknown'); Modify-class seams flagged upstream-first with budget exceptions in OPS-01; S40 dispatcher in a new omnigent/host/workspace_ops.py; TLS-01 adds its lookup beside the sys_advise_models intercept and migrates it only upstream. |
| ARC-14 | major | accepted | Definition-of-done rule: open the upstream PR for each 'Up: Yes' seam at landing and record it in .coral/upstream.yaml; OPS-01 reports gaps; OPS-05 drives PRs to merge and retires anchors. |
| ARC-15 | major | accepted | SES-03 owns a dedicated anchor (coral.role=run, never briefed); PRF-01 seeds the inert anchor agent; K10 adds coral.role and K4 CreateSession.role; rule: no session policies on the anchor; SPK-02 probes (b) and (e) run on this variant; SES-07's refresh test asserts siblings stay reachable. |
| ARC-16 | major | accepted | ENG-08 narrowed to pure repeat and parallel semantics; new SES-10 (WS-INTEGRATION) owns gate batching, sibling cancel, concurrency caps, per-item worktrees, the PR-review template and E2E-5; SES-01 reserves the batch-gate payload in K14. |
| ARC-17 | minor | accepted | S9, S11 and native S12 transport moved to HRN-03, the Codex S11 site to HRN-05, S69(b) to HRN-03; the hot-file table now lists runner/app.py, host/frames.py, app_server.py, claude_sdk_executor.py, bridge.py and more. |
| ARC-18 | minor | accepted | S71 is the standalone PH1 feature WSP-05 with an upstream PR and repro test; WSP-01, EVD-03 and EVD-02 hard-depend on it (EVD-02 hard, not soft, because TLD-10 says no exit code is trusted before S71); M2 exit 10 says which exit codes S71 protects. |
| ARC-19 | minor | accepted | HRN-06 hard on SES-04, SES-08 and TLS-01; ENG-10 soft on WSP-01 and WEB-04; ENG-01 soft on SPK-04; the coral console entry is in FND-01; K17 states ensure_coral_schema runs first and a migration failure aborts startup. |
| ARC-20 | minor | accepted | K4 conformance parameterized over FakeOmni and the real facade and run as L3 in OPS-02; OPS-02's regeneration script adds the Coral OpenAPI, the generated TS client and the K1 JSON Schema. |
| ARC-21 | minor | accepted | TLS-01's S12 introduces a FrameworkInstructions value in prompt.py with ordered, owner-tagged entries; native channels transport only the composed result (HRN-03); proof checks the two existing entries are unchanged. |
| ARC-22 | minor | accepted | SPK-04 outputs a verdict and a draft K13; K13 v1 with fake and conformance tests is WSP-01's first PR, before EVD-02 needs it. |
| ARC-23 | minor | accepted | SPK-01 runs a PH0 threat-model checkpoint feeding the K6, K12 and K14 freeze; WSP-02's K20 PR needs security sign-off; OPS-06 reviews M2 surfaces; OPS-04 closes the review. |
| ARC-24 | minor | accepted | Milestone paths are reported cumulatively through acceptance nodes (OPS-07 -> OPS-08 -> OPS-09) and regenerated; section 10 lists single-owner, staffed and levelled figures. |
| ADV-01 | blocker | accepted | SES-05 is now the walking skeleton with hard deps FND-04, SES-02, TLS-01, GTE-05, DUR-03, DUR-04 and ENG-04, soft deps and named slices on SES-03, SES-04, TLS-02 and GTE-01 (JSON slice_deps); the acceptance half is OPS-07 rather than the proposed SES-08 id. |
| ADV-02 | blocker | accepted | K2 slot closing and post_close_activity (ENG-01, ENG-04); SES-04 close sequence (closing -> turn end -> commit -> pending-input check -> stop -> closed) with paused(drift) on post-accept turns; WEB-05 disables the composer while closing; Tier B queued-input test. |
| ADV-03 | major | accepted | K13 op-host rule in WSP-01; SES-06 ladder fixed (fence and stop, new generation without brief, reconnect, salvage and reset through the new shell, brief); WSP-06 commits in the closing state; SPK-04 tests with the sandbox on in a linked worktree; spike 8 failure moves the host-channel write ops into WSP-06 in PH2 (a planned contingency, not a forward edge). |
| ADV-04 | major | accepted | K11 adds the per-session observation watermark; TLS-02 waits within the spike-7 bound and returns 'evaluation in progress', which never counts toward the rejected-call pause; EVD-02 writes claude-sdk observations synchronously; the outbox (S69 b) moves to HRN-03. |
| ADV-05 | major | accepted | Failed-turn classification at M2: the pure classifier is in ENG-11 and SES-08 gathers facts and maps classes to backoff, paused(auth) or paused(plan_limit); HRN-04 replaces text matching with S24; Tier B 529/429/401 case. |
| ADV-06 | major | accepted | ir_version, state_version and log_version in K1-K3 with N reads N-1; DUR-01 stores engine_version per run; DUR-05 pauses unreadable runs as paused(engine_upgrade); ENG-10 offers restart-from-node; OPS-07 runs the engine-upgrade lane (moved from OPS-02 because it needs M2 features). |
| ADV-07 | major | accepted | FND-01 adds coral = 'coral.cli:main' with an empty click group at M1; OPS-03 keeps data-dir isolation and update identity; DUR-02's CLI resolves the server URL from the active config, tested under two config homes. |
| ADV-08 | major | accepted | ADR-05 picks the anchor; hidden inert anchor agent seeded by PRF-01; input stance is omnigent.closed if probe (e) holds, otherwise a coral.role-keyed DENY from RUL-01's S52 provider (not a session policy, which would leak to children per ARC-15); SES-09 defines anchor archive and delete outcomes. No new seam was needed. |
| ADV-09 | major | accepted | TLS-03->TLS-02 and TLS-03->ENG-05 soft; SES-06->SES-04 soft; RUL-02 hard on EVD-01 with EVD-02 soft; WEB-03 hard on the desk-only WEB-02 after the editor split (WEB-11), which replaces the proposed WEB-02#desk slice. |
| ADV-10 | major | accepted | Spike 4 is the first week-1 probe in SPK-03; FND-04 runs Tier B on claude-sdk against the mock if it passes; otherwise conditional test-only openai-agents support in ENG-11, HRN-01 and PRF-01 with the unprovable M2 criteria listed. |
| ADV-11 | major | accepted | K4 states send is not idempotent and callers read before resend; the conformance suite runs over FakeOmni and the real facade; SES-03 is not done until both pass; OPS-02 runs it as L3. |
| ADV-12 | major | accepted | S1b removed from M2; SES-02 sets origin only at the relay turn end, status-probe notify, archive idle and runner-disconnect sites; full S1b is an upstream-only PR owned by OPS-05. |
| ADV-13 | major | accepted | WSP-01 split into WSP-05 (S71), WSP-01 (K13 freeze, bindings, create and adopt, S72 head_commit with fallback, import, S73 invariant) and WSP-06 (commit, salvage, reset, retention, disk cap); S72 detached mode moved to EVD-04 as a ledger amendment. |
| ADV-14 | major | partially | Split into SES-04 'Engine dispatch' (M) and SES-08 'Turn-end facts and failed-turn outcomes' (M, not L) because the pure turn-end rule and classifier moved to ENG-11; the skeleton depends on SES-04's slice, HRN-03 and HRN-05 depend on SES-08. |
| ADV-15 | major | accepted | HRN-03 'claude-native step launch' (L: channels, level-triggered turn-end fallback, observations, pane-reaper handling, spike 6, E2E-3) and HRN-07 'Native rotation following' (M: S45, re-attach, OQ-46); M3 exit needs both. |
| ADV-16 | major | accepted | HRN-01 (S, K9 types, claude-sdk row, S22 guard tests) and HRN-08 (M, M3: other modes, S59, bench S23, S78, coral-bench.yml). HRN-01 is tagged M1 rather than M2 so K9 is a real M1 deliverable (ADV-30, DEL-26); recorded in the decisions log. |
| ADV-17 | major | accepted | WSP-02 (frames, K20, dispatcher, S40/S40b, probe, head, L2) starts at M2 in PH3 with WSP-01 soft; WSP-07 (write ops, swap, parity) stays in PH4; spike 8 failure moves those write ops into WSP-06 in PH2. |
| ADV-18 | major | accepted | ENG-08 is pure semantics starting in PH2 (milestone M4) with a first PR of item_path depth-2 golden traces merged before M2 exit; SES-10 holds the PH4 integration and template. |
| ADV-19 | major | accepted | New OPS-06 reviews M2 surfaces by M2 exit and signs off native surfaces before HRN-03 merges (HRN-03 hard on OPS-06); OPS-04 keeps M4 closure; RUL-02 adds a per-mode gate-integrity label; SPK-05 decides whether gated runs may use claude-native steps at M3. |
| ADV-20 | major | accepted | Perf smoke (five concurrent mock runs on SQLite; SQLITE_BUSY, p95 transition latency, edge-to-TurnFact lag) in DUR-04's and SES-08's definition of done, gated in OPS-07 on SPK-05 budgets; OPS-04 keeps the full load test. |
| ADV-21 | major | accepted | SPK-05 holds OQ-51 (PH1-end deadline) and OQ-28 (PH2-end deadline, fallback: claude-native on API key behind its flag); OQ-29 has a PH4-start deadline with a two-claude-sdk-reviewer fallback; affected exit criteria are marked conditional. |
| ADV-22 | major | accepted | WSP-03 keys worktrees by (run, node, item_path, agent) with a per-item base ref; WSP-07 adds fetch-ref and push behind consent (OQ-39); SES-10 owns the template's credential and egress profile through RUL-03 templates and settles OQ-18 for the PR case. |
| ADV-23 | major | partially | K8 defines the RunView projection with a per-entry patch emitted by the reducer and stored by DUR-03, so the client never re-implements it; K1 gains the Analysis section, but it is produced by the ENG-02 compiler (ARC-11) rather than by ENG-03. |
| ADV-24 | major | accepted | Failure-mode ownership table added (section 8) with owners and proving tests, including the five new modes: TLS-03 re-brief, conditional S27 at M2, HRN-03 lost-edge fallback, WSP-01 head_commit fallback, SES-04 ensure_runner_connected before every send. |
| ADV-25 | major | accepted | Ranked M2 cut list with weeks saved (section 6.3); items 1-5 of the proposal are already out of M2 by the moves to OPS-05, HRN-08, HRN-03, EVD-04 and WEB-12; the remaining cuts are TLS-05, WEB-11, the WEB-05 composer, OPS-03 and small detection parsers. |
| ADV-26 | minor | accepted | DUR-04 owns the queue migration; K19 is a PH0 schema and the alerts backend is GTE-06 in WS-PLATFORM; WS-WEB's GTE-02 keeps the card, count and S36. |
| ADV-27 | minor | accepted | ENG-01 hard on SPK-01 (OQ-3, 12, 19); EVD-01 hard on SPK-04; K13 is WSP-01's first PR. |
| ADV-28 | minor | accepted | SPK-02 is M with two engineers for one calendar week; SPK-03 keeps only the claude-sdk spikes, and spikes 5, 6, 12 and 13 become first PRs of RUL-04 and HRN-05 so their answers are fresh. |
| ADV-29 | minor | accepted | The seam train is a landing-order guideline enforced by anchors and rebase-on-conflict; conditional dependencies (spikes 1, 4, 8, 16, SPK-02, OQ-28, OQ-29, M2 audience) are in the JSON conditional_deps field and section 6.4. |
| ADV-30 | minor | accepted | K9 and K18 come from M1 features; M2 exit 2 asserts invariants and terminal state; HRN-06/HRN-09 are conditional in M4; single owners: runs list WEB-13 (split from WEB-04), seeds PRF-01, preflight engine HRN-02 with API-02 serving the endpoint. |
| ENG-01 | blocker | accepted | Same split as ADV-01; the acceptance lane is OPS-07; skeleton slices are named first deliverables of ENG-04 (by IM-1), SES-03, SES-04, TLS-02 and GTE-01 (by IM-2). |
| ENG-02 | blocker | accepted | K13 op-host rule; SES-06 restart reorder; engine commit at the accepted handoff's turn end in the closing state (WSP-06); request-free runner shell call in K4 implemented by WSP-06 with a contract test; two SPK-04 probes added; the minimal host-op slice is a planned contingency owned by WS-WORKSPACE. |
| ENG-03 | major | accepted | Wire seams are covered by one versioned coral_runner:n host token rather than one token per group (simpler, same protection); tests/e2e/coral/conftest.py skips without it; Tier B runs in the inherited e2e gate and coral-e2e.yml keeps only the credentialed nightly; OPS-02 adds Coral to the compat review. |
| ENG-04 | major | accepted | All proposed edges changed: ENG-04->ENG-02 soft; SES-04->SES-03 soft; SES-06 hard on SES-03 and DUR-03, soft on SES-04 and DUR-05; EVD-02->WSP-01 soft with WSP-05 hard; RUL-02 hard on EVD-01; WSP-03 hard on WSP-02 only. |
| ENG-05 | major | partially | Hard edges DUR-03->FND-04, DUR-05->FND-04 and FND-04->FND-03 added. SPK-01 split into SPK-01 (week-1 set, hard prerequisite of ENG-01, SES-01, API-01 and FND-02) and SPK-05 (M2-M3 set). HRN-02 does not hard-depend on OQ-28 because API-key-only is the conservative default whatever the answer; HRN-03, which the answer can change, hard-depends on SPK-05 instead. |
| ENG-06 | major | accepted | Each owner's first PR is its standalone migration (SES-03 bindings, SES-04 stable ids, PRF-01 step agents, GTE-06 alerts, TLS-05 questions, WSP-01 repo bindings, EVD-03 patterns, EVD-02 observations) and the train table covers GTE-03, ENG-09, EVD-04, GTE-04, EXT-01 and EXT-04. |
| ENG-07 | major | accepted | Full per-file landing order published (section 6.5); a named WS-INTEGRATION seam-train owner lands hot-file seams serially and dark; RUL-05 uses the S52 provider with no new builder.py edit. |
| ENG-08 | major | accepted | S68 is one fan-out line at the top of pr_observer.observe_tool_completion; S69(a) is the only M2 transport; S69(b) and the bridge site move to HRN-03; K11 states observations are durable before the result returns. |
| ENG-09 | major | accepted | origin is an optional keyword with a default; SES-02 sets it at the archive idle, runner-disconnect, relay turn-end and status-probe sites; the other sites are an upstream PR (S1b, OPS-05). |
| ENG-10 | major | accepted | TLS-01 keeps S7, S8, S10, S12 (headless plus FrameworkInstructions), S49 and S50; S9, S11 and S12 native transport move to HRN-03 and the Codex S11 site to HRN-05, each a one-line provider call. |
| ENG-11 | major | accepted | GET /v1/coral/info returns a sub-feature map (editor, canvas_edit, claude_native_steps, codex_steps, webhooks, budgets, takeover, restart_from_node, profiles_desk) read by CoralGate, pickers and the API; S50 and S52 providers are O(1) no-ops for non-Coral sessions with fast-path tests. |
| ENG-12 | major | accepted | Seam features' first proofs are component tests in the named nearest scenarios (definition-of-done rule 1 and the proving tests of SES-02, TLS-01, GTE-05, RUL-01, PRF-01, WSP-05 and WSP-01); journey proofs live in SES-05 and the OPS acceptance lanes. |
| ENG-13 | major | accepted | WEB-02 is the desk and library (M); WEB-11 is the YAML editor (M); WEB-03 hard on WEB-02 only; WEB-08 and WEB-06 hard on WEB-11. |
| ENG-14 | major | accepted | Split into WSP-05 (S71, PH1, hard on FND-01 only), WSP-01 (bindings, create and adopt, S72, import) and WSP-06 (session-shell ops, retention, disk cap); SES-06 and OPS-07 consume WSP-06. S72 compatibility uses host-hello feature detection with a rev-parse fallback under the coral_runner token. |
| ENG-15 | major | accepted | GTE-01's S6b verdict handler compares resolver identity with the run owner and returns typed not_permitted, tested with an edit-shared run session; ELICITATION_RESOLVE_LEVEL unchanged; the case is in OPS-06's review. |
| ENG-16 | major | accepted | SPK-03 covers only the claude-sdk spikes 1, 2, 4, 7, 16, 19 and 20; spikes 5 and 6 are RUL-04's first PR, 12 and 13 HRN-05's first PR; RUL-04 no longer hard-depends on SPK-03. |
| ENG-17 | minor | accepted | Drift detection and user-action outcomes split into SES-09; SES-06 keeps the restart ladder. |
| ENG-18 | minor | accepted | M2 gates on deterministic lanes (E2E-1, E2E-2, fault suite); the nightly is a soak signal with a threshold from SPK-05 (default 9 of 10); coral-bench.yml waits for the OQ-51 record. |
| ENG-19 | minor | accepted | OPS-02's licence job blocks only new direct dependencies by diffing the upstream lock and records the inherited elkjs for counsel; WEB-01 adds dagre and a direct yaml dependency in one standalone dependency PR. |
| ENG-20 | minor | accepted | Paths fixed (omnigent/server/scheduled/, omnigent/terminals/pane_reaper.py); an own-runner child is defined as a child created with host_id (is_independent, app.py:4594-4597) in SPK-02 and SES-03. |
| ENG-21 | minor | accepted | coral_ask_user is the separate feature TLS-05 (M), hard on TLS-01 and GTE-01. |
| ENG-22 | minor | accepted | GTE-02 adds an inbox-kind registry spread in one line in InboxPage.tsx after BRD-02's S84 edit. |
| ENG-23 | minor | accepted | DUR-04 takes a DB-level worker lease tested with two app instances on Postgres; FND-02 refuses only host_sharded. |
| ENG-24 | minor | accepted | SES-01 freezes topology-independent K4 methods at IM-0 and the create, access and watch sections after ADR-05, with a hard dependency on SPK-02 (one calendar week, run in parallel with FND-01). |
| ENG-25 | minor | accepted | Join-once and duplicate-signal properties are in ENG-08's seeded fuzz and DUR-03's contention tests; E2E-5 in SES-10 covers only two real concurrent sessions. |
| ENG-26 | minor | accepted | Each web feature names its vitest and CI-only browser-lane assertions (definition-of-done rule 7). |
| ENG-27 | minor | accepted | FND-01 creates coral/cli.py and the entry point; DUR-02 adds its subcommand; OPS-03 wraps it. |
| ENG-28 | minor | accepted | OPS-01's first PR seeds S29, S39 and S76 in week 1 in warn-only mode and becomes required once seeded. |
| ENG-29 | minor | accepted | HRN-06 (S20, S61, S67) and HRN-09 (S18, S19, S60; first cut if M4 slips), both M. |
| ENG-30 | minor | accepted | Cumulative milestone paths reported through acceptance nodes; recomputed in section 10. |
| PRO-01 | blocker | accepted | SPK-01 records supported host OSes (OQ-1); WSP-01 computes a host sandbox report advertised with the coral_runner token; K9 is keyed by (mode, host sandbox); RUL-02's property test never yields Enforced without an FS sandbox; HRN-02's preflight (used by API-02 and WEB-03) refuses and fails fast without bwrap; M2 exit 11 rewritten. |
| PRO-02 | major | accepted | K14 gate-context block assembled by GTE-01; WEB-04's gate tab renders it; WSP-06 computes diff_stat in the closing state and stores it with the handoff (no session exists at gate time); API-02 serves a run-outcome resource; WEB-13 shows the outcome panel and copy-checkout command. |
| PRO-03 | major | accepted | RUL-02 (M2) computes claude-sdk labels with the never-over-claim property test; RUL-06 (M3) adds modes and V9; WEB-13 shows a read-only per-run guarantees panel and WEB-03 a promise summary; WEB-06 keeps editor chips and rules at M3; M2 exit 13 replaces the 'no labels' line; label visuals decided in SPK-05 before PH2. Reverses v1 decision 45. |
| PRO-04 | major | accepted | GTE-02's card is canonical for coral_gate_ and coral_question_ ids; the generic collector and elicitation OS notification skip them; GTE-06 auto-resolves alerts when the visit resolves; step prompts show as 'Step waiting on you'; proof is one card, one notification, count 1. |
| PRO-05 | major | accepted | API-02 serves spend so far through the K4 usage adapter; WEB-04 and WEB-13 show it; RUL-01 turns the backstop DENY into paused(budget) with copy naming the cap; WEB-03 shows the cap; SPK-05 decides OQ-15. |
| PRO-06 | major | accepted | K2 carries the closed pause-reason list with resume-condition kinds (plus engine_upgrade from ADV-06); 'needs you' is a status; WEB-04 owns the reason-to-copy table with one fixture test per reason and the salvage wording on Retry. |
| PRO-07 | major | accepted | SPK-05 records the product half of OQ-17; SES-03 titles the anchor and files it into a 'Coral runs' project via fire.py's pattern; WEB-05 owns the anchor page; SPK-02 probe (e) checks the sidebar and page. |
| PRO-08 | major | accepted | WEB-03 deep-links auth failures to HarnessFixDialog; gallery and intro show the 'Needs:' line; SPK-05 signs the TLD-07 consequence; HRN-02's copy is corrected; the claude-native orchestrator is a deferred gap part; HRN-03 ships the single-agent template; M3 journey step 3 rewritten. |
| PRO-09 | major | accepted | WEB-04's first PR is a shared roster-chip and harness-label component with the 'Claude, not Claude Code' rule and a unit test, reused by WEB-03, WEB-05 and GTE-02; SPK-05 records the rule. |
| PRO-10 | major | accepted | UI-surface ownership table (section 11); missing states added to GTE-02, WEB-04, WEB-01 and WEB-05; the phone layout is in WEB-13 (split from WEB-04 to keep it within L); WEB-04 has the accessibility baseline with axe in the CI-only lane. |
| PRO-11 | major | accepted | RUL-02 ships a frozen per-mode never-Enforced fixture covering (a)-(f) and the sandbox-less host; tooltips say what was not checked; GTE-01's D25 note is a RUL-02 input; RUL-03 records a bypass analysis per template; RUL-05 and WSP-07 carry label-fixture updates. |
| PRO-12 | major | partially | Run-view parts (spend vs budget, checks and integrity flags, verifier verdicts, merges and conflicts) moved to WEB-10, resized to L; step budgets, reactions and saved blocks to WEB-09. The start-dialog budget field stays in RUL-05 and the retention setting and delete-with-runs confirmation in DUR-06, as secondary WS-WEB load, because WEB-03 and WEB-02 finish at M2 and cannot hold M4 scope. |
| PRO-13 | major | accepted | OQ-5, 15, 16, 17 (product half), 23, 24 (inbox-kind and label visuals before PH2) and 26 are in SPK-05; OQ-7 and OQ-8 are in SPK-01's week-1 set; defaults recorded. |
| PRO-14 | major | accepted | SPK-05 decides OQ-26 from product Q-36; WEB-01, WEB-02, WEB-03, WEB-13 and GTE-02 emit id-and-enum events through useOmnigentAnalytics; M2 exit 15 adds unaided completion and template-to-simulate under five minutes; EXT-01 gets the new OQ-55 for suggestion data. |
| PRO-15 | major | accepted | SPK-05 records the M2 audience; an external audience adds an M2 release gate (OPS-03 without its cut line, OQ-30 answers from OPS-05, OPS-06 as release review) as conditional dependencies; the M2 journey states web and CLI only. |
| PRO-16 | minor | accepted | The Agent Profiles nav entry is hidden behind the profiles_desk key until WEB-07 flips it. |
| PRO-17 | minor | accepted | SPK-01 decides OQ-4 (default owner-only); GTE-01 enforces it in the S6b handler with typed not_permitted; GTE-02 and WEB-04 show 'Waiting for the run owner' and 'Only the run owner can answer'. |
| PRO-18 | minor | accepted | GTE-06 adds low-priority completed, failed and cancelled alerts auto-acked when the run is opened; WEB-13 adds 'Run again' with a new start_key. |
| PRO-19 | minor | accepted | Run-log export (JSON or Markdown) added to EXT-03. |
| PRO-20 | minor | accepted | FND-01 registers the console entry and owns coral/cli.py; OPS-03 adds only isolation and update identity. |
| PRO-21 | minor | accepted | SPK-01 records OQ-7 default (a) through M4; option (b) is a deferred gap part that would go to WEB-03. |
| PRO-22 | minor | accepted | M3 exit 8 and M4 exit 4 rewritten as testable statements; dogfood user-outcome criteria added to M3 (OPS-08) and M4 (OPS-09). |
| PRO-23 | minor | accepted | ENG-07's template declares the loop limit, reviewer models and the gate's reject route as parameters; WEB-03's dialog exposes them. |
| DEL-01 | blocker | accepted | SES-05 walking skeleton (M rather than S, because it includes the kill-and-restart variant) owns IM-2 with the gate answered via /approve; the acceptance lane is OPS-07 in WS-OPS; skeleton-slice exit items added to ENG-04, SES-03, SES-04, TLS-02 and GTE-01. |
| DEL-02 | major | accepted | SES-04 hard on SES-01 and SES-02, soft on SES-03; GTE-01 hard on GTE-05, ENG-04, SES-01 and DUR-03, soft on SES-03; K4 conformance runs on both sides at IM-2. |
| DEL-03 | major | accepted | SES-06 (restart ladder, relaunch, hold; hard SES-03 and DUR-03) and SES-09 (drift and user actions; hard SES-03); both soft on DUR-05 and the other inputs. |
| DEL-04 | major | accepted | SES-03, PRF-01, WSP-01, HRN-02, EVD-02 and EVD-03 relabelled PH1 with target M2; every feature carries a planned start week from the levelled schedule; phase windows are defined in weeks (section 10). |
| DEL-05 | major | accepted | ENG-04 hard on ENG-01 only; ENG-01 ships compiled-IR fixtures and ENG-02's golden test reproduces them. |
| DEL-06 | major | partially | coral_ask_user split into TLS-05 (M, hard on TLS-01 and GTE-01, soft on TLS-03). TLS-03 is M, but hard on TLS-01, ENG-04 and SES-01 with TLS-02 and PRF-01 soft (ARC-12 and ADV-09), not hard as proposed, because its handler only needs the contracts. |
| DEL-07 | major | accepted | WSP-05 is the S71 feature (PH1, M2); WSP-01 and EVD-03 hard on it; EVD-02 hard on EVD-01, SPK-04, DUR-01 and WSP-05, soft on WSP-01; WSP-02 hard on WSP-05 and SPK-04, soft on WSP-01 and EVD-02. |
| DEL-08 | major | accepted | IM-0..IM-8 defined with owning lead, proving test, dates from the levelled schedule and the features whose exit they are (section 4). |
| DEL-09 | major | accepted | Acceptance nodes OPS-07, OPS-08 (hard on OPS-07) and OPS-09 (hard on OPS-08); stated staffing of 20 engineers; levelled and planned dates published next to the CPM figures; the soak week sits inside OPS-07. |
| DEL-10 | major | accepted | Acceptance lanes are WS-OPS features per milestone (OPS-07, OPS-08, OPS-09) owning journey scripts, fault injection, the credentialed nightly and coral-e2e.yml; feature owners keep their own E2E cases. |
| DEL-11 | major | partially | K19 is a PH0 schema in SES-01 (ARC-07; earlier than the proposed PH1 in DUR-01) and the alerts backend splits out as GTE-06 (WS-PLATFORM, early PH2) with its own migration; GTE-02 is soft on GTE-06 via K19 fixtures. |
| DEL-12 | major | partially | K21 added with the proposed scope, but produced in DUR-01's first PR beside K5 (ARC-06) so executors see it before DUR-04 starts; DUR-04 ships the fake drainer and conformance test; the six executor features consume K21. |
| DEL-13 | major | partially | M2 call sites are pre-planted in the PH1 seam packs (SES-02, TLS-01, GTE-05) or as the owner's first PR (EVD-02's S68 and S69 a), each with a component test, while native sites move to their consumers (ENG-10). The train order is not encoded as hard dependencies (ADV-29): one-line anchors at different lines merge cleanly and hard edges would serialize teams. |
| DEL-14 | major | accepted | OPS-02 lands real merges from nightly^1 every two weeks from PH1 with a rotating merge owner and per-team merge-day budget; OPS-05 keeps the release drill, cherry-pick lane and upstream PRs; OQ-50 is in SPK-01's week-1 set. |
| DEL-15 | major | accepted | ENG-08 semantics start in PH2; RUL-02 starts in PH2; ENG-10 starts in PH3; an Engine integration-support rotation covers IM-2 and IM-3. |
| DEL-16 | major | accepted | PH4 opens at M2 alongside PH3; WSP-02 starts at M2; HRN-05 and DUR-06 move to PH4; GTE-03 moves to WS-PLATFORM. |
| DEL-17 | major | accepted | K20 freezes at M2 as WSP-02's first PR; EVD-04 is soft on WSP-02 with a WSP-02#K20 slice and builds against the K20 fake. |
| DEL-18 | major | accepted | WS-PLATFORM staffed with three through M2; API-02 hard on DUR-01, DUR-03 and API-01, soft on DUR-02; RUL-02 hard on EVD-01. |
| DEL-19 | major | accepted | OQ-51 in SPK-05 with a PH1-end deadline; on-demand credentialed workflow_dispatch lane from IM-2 in OPS-07; spike 4 first in week 1; the soak is a one-week tail inside OPS-07. |
| DEL-20 | major | accepted | Threat-model checkpoint in SPK-01, M2 review in OPS-06, sign-off at the K20 freeze and before HRN-03 merges; fixes owned by producing features; OPS-04 closes. |
| DEL-21 | major | accepted | RUL-04 moved to PH2 (still M3), so HRN-03 starts at M2. |
| DEL-22 | minor | accepted | WEB-02 desk (M) and WEB-11 editor (M); WEB-03 hard on WEB-02, soft on DUR-02 via MSW fixtures; WEB-06 and WEB-08 hard on WEB-11. |
| DEL-23 | minor | accepted | SPK-01 and SPK-05 owned by the tech lead and PM; the I1-I8 harness moved to ENG-01 and ENG-04; FND-04 keeps DB-lane faults and Tier B; WS-OPS staffed with two. |
| DEL-24 | minor | accepted | Decisions staged by deadline (SPK-01 week 1, SPK-05 week 4); SPK-02 staffed by two with (a)-(d) by day 4 and (e), (f), 14, 15 by week 2; SPK-03 trimmed to week-1 claude-sdk spikes. |
| DEL-25 | minor | accepted | Features carry a secondary_workstreams field with weighted weeks (PRF-01, HRN-04, ENG-10, GTE-03, DUR-06, RUL-05, EXT-01); the load table counts it. |
| DEL-26 | minor | accepted | FND-01 is the package skeleton, boundary and entry point; FND-05 holds tooling roots and CODEOWNERS; K9 and K18 come from M1 features. |
| DEL-27 | minor | accepted | HRN-08 owns coral-bench.yml; OPS-07 owns coral-e2e.yml and the credentialed nightly. |
| DEL-28 | minor | partially | BRD-03 starts in PH3 (at M2) so desktop builds can resume early, but stays one feature because S88 covers desktop and mobile names and icons; WS-BRAND's engineer folds into WEB between BRD-02 and BRD-03. |

## Conflicts resolved

- SES-05 split (ARC-09, ADV-01, ENG-01, DEL-01): hard set chosen for correctness (the substrate the skeleton tests), slices kept soft for parallelism; the acceptance half goes to WS-OPS (DEL-10) rather than staying with one owner (ARC-09).
- K19 producer (ARC-07 SES-01, DEL-11 DUR-01, ADV-26 GTE-02/DUR-05, ENG-06 GTE-02): schema in SES-01 at PH0 (earliest, contract-first), table and backend in GTE-06.
- K21 producer (ARC-06 DUR-01 or ENG-01, DEL-12 DUR-04): DUR-01's first PR, the earliest point that is still the platform team's.
- K11 placement (ARC-07 into ENG-01, ADV-27 after SPK-04): authoring block in K1, compiled IR and records in K11 after SPK-04.
- K1 Analysis producer (ADV-23 ENG-03, ARC-11 ENG-02): the compiler (ENG-02), so the IR is complete after compile.
- TLS-03 edges (ARC-12 and ADV-09 soft, DEL-06 hard on TLS-02 and PRF-01): soft, since the handler needs only K2 and K6 and the seed belongs to PRF-01.
- Train order (DEL-13 hard edges, ADV-29 guideline): guideline with a seam-train owner, because one-line anchors merge cleanly and hard edges serialize teams.
- Dormant seams (DEL-13 pre-plant, ARC-17 and ENG-10 move to consumer): M2 sites pre-planted in PH1 seam packs with component tests; PH3+ native and Codex sites move to their consumers.
- Anchor input stance (ADV-08 input DENY policy, ARC-15 no session policies on the anchor): a coral.role-keyed DENY from RUL-01's S52 provider, which does not leak to children, used only if a closed anchor cannot resolve elicitations.
- Queue migration (ARC-08 in coral_0001, ADV-26 in DUR-04): DUR-04 owns its tables; the layout decision stays in K5 so OQ-34 is decided once.
- S71 edge for EVD-02 (ARC-18 soft, ENG-04 and DEL-07 hard): hard, because TLD-10 trusts no exit code before S71 and WSP-05 is an early S feature.


## Fix round 1

Mechanical issues found by the checker in master v2, fixed in `master_v2_fix1.json` and `master_v2_fix1.md`.

| Fix | Issue | Decision | Change |
|---|---|---|---|
| FIX1-01 | OPS-06 covers no G-row and is not marked enabler | accepted | OPS-06 marked enabler. It ships no user-visible behaviour and no G-row asks for a security review (G-27 provenance and G-84 cherry-pick lane belong to TLS-01 and OPS-02/OPS-05); its sign-off gates WSP-02 (K20 freeze), HRN-03 (native merge) and OPS-04, the same class as SPK-01's threat-model checkpoint. Scope, phase, milestone and dependencies are unchanged. |

Re-check after the fix: no errors; every G-row covered; every seam owned once or not planned; every feature covers a G-row or is an enabler; no hard dependency points to a later phase or milestone; no cycles.
