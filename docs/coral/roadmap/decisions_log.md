# Coral roadmap resolution decisions (master v3)

Source: `decomposition/master_v2_fix1.json` -> `master_feature_list.json`. 202 decisions resolve the 90 `[OPEN?]` verifier items and the 219 spec Reviewer-note lines, plus the related untagged open items. Machine-readable form: `decisions_log.json`; coverage map: `verification/coverage.json`.

Outcomes: **assign** (one owner), **split** (explicit included/excluded wording), **edge** (dependency added), **contract** (contract lists or text), **citation** (wrong text corrected), **nongoal** (explicit non-goal), **residual** (open, owned and dated; listed in J.6), **fixed** (already resolved; no action).

Two adversarial challenge passes (CH-01 to CH-15, then CH-16 to CH-28) changed 54 decisions; their 28 entries are in the Challenge log section below and in `master_v3.json` `challenge_log`. Residual decisions keep a J.6 row only while something is still open or a date is being tracked.

Counts: assign 40, citation 25, contract 35, edge 25, fixed 17, nongoal 14, residual 20, split 26.

## Decision table

| RES | Outcome | Features | Decision | Master edits | Spec edits | Section edits | Residual (owner; deadline) |
|---|---|---|---|---|---|---|---|
| RES-001 | assign | SPK-05, DUR-06, HRN-05 | SPK-05 owns the OQ-25 (retention) and OQ-29 (Codex terms) decision records: the OQ-25 default by week 4 (SPK-05's own deadline for Coral-controlled questions), signed by week 13.5; the external OQ-29 answer by week 13.5. DUR-06 and HRN-05/06/09 only implement the recorded outcome. | 5 | 6 | 1 |  |
| RES-002 | split | DUR-04, SES-08, OPS-07, SPK-05 | SQLite perf smoke: DUR-04 owns the one harness (tests/stores/coral/test_sqlite_perf_smoke.py) and its shared helpers; SES-08 adds the edge-to-TurnFact lag case to it; OPS-07 runs it as the M2 gate and keeps a separate e2e case (five concurrent template runs and the watchdog p95, a real-server boundary) that reuses DUR-04's helpers; SPK-05 records the budgets. | 4 | 8 | 0 |  |
| RES-003 | edge | DUR-04, SES-08, OPS-07, SPK-05 | Add soft edges DUR-04, SES-08 and OPS-07 -> SPK-05: they read the SPK-05 perf-smoke and soak budgets. | 3 | 7 | 0 |  |
| RES-004 | split | SES-08, OPS-07 | The 529/429/401 Tier B case is SES-08's; OPS-07's M2 fault journey re-runs it from SES-08's QueuedResponse setup instead of writing its own. | 2 | 1 | 0 |  |
| RES-005 | assign | SPK-05, RUL-01, HRN-02 | SPK-05 signs or defaults the records that week-3 starters consume (OQ-15 for RUL-01; OQ-28 default and OQ-35 for HRN-02) by week 2; the rest by week 4. | 1 | 3 | 0 |  |
| RES-006 | assign | SPK-05, DUR-02, ENG-03, WEB-02 | OQ-9 (saving invalid drafts; where saved tests run) gets a record in SPK-05 by week 2 with the default "draft save allowed, run blocked; saved cases run in the app and in CI". | 2 | 5 | 1 |  |
| RES-007 | assign | SPK-01, SES-01 | SPK-01 records OQ-37 (profile metadata: params.coral, X-12) and OQ-47 (coral.omni coupling: in-process facade, X-8) in week 1, because they shape K4 and K12 at IM-0. | 3 | 5 | 1 |  |
| RES-008 | citation | SPK-02 | SPK-02 probes (e), (f), 14 and 15 run to week 2 while its planned window is weeks 0-1. No downstream start moves and nothing is left to decide; H.3 shows the tail. | 0 | 1 | 1 |  |
| RES-009 | assign | SPK-03, HRN-08 | SPK-03 probe prototypes stay on the spike branch and in docs/coral/decisions/probes/; HRN-08 ports them into upstream tests/harness_bench/probes/ under a ledgered S23 entry. | 2 | 3 | 0 |  |
| RES-010 | edge | SPK-04, FND-01 | Add soft edge SPK-04 -> FND-01: the draft coral/workspace/ops.py needs FND-01's skeleton; until it lands the draft stays in the spike report. | 1 | 3 | 0 |  |
| RES-011 | citation | WSP-05, SPK-04, SES-06 | Correct HEAD citations in master text: child_session_recovery.py:164 -> :165 (decision 33); WSP-05 and SPK-04 S71 ranges connect.py:1417-1423, 6027-6034 -> 1417-1424, 6027-6035; native bearer runner/native/orchestration.py:9832 -> :9833. | 3 | 0 | 5 |  |
| RES-012 | assign | FND-05, FND-01 | Registering the Coral import-boundary rule in dev/lint/custom_lint.RULES belongs to FND-05 (S39, which edits custom_lint.py); FND-01 supplies the rule module. | 2 | 3 | 0 |  |
| RES-013 | citation | FND-01 | The import-boundary lint lives at dev/lint/lint_coral_import_boundary.py (the lint_<name>.py convention, custom_lint.py:18-19), not dev/lint/coral_boundary.py. | 1 | 1 | 1 |  |
| RES-014 | split | FND-03, DUR-01 | Single-head tests: FND-03 owns the environment-level tests (an empty chain plus coral_0000_base has one head; ordering after Omnigent head; engine binding); DUR-01 owns the train-level single-head and models-match checks that every table PR runs. coral_0000_base becomes an explicit FND-03 migration. | 4 | 6 | 2 |  |
| RES-015 | split | FND-04, OPS-02, DUR-01 | Split-DB lane: FND-04 owns the fixtures (SQLite operational DB plus a separate SQLite conversation DB); OPS-02 owns the CI job; DUR-01, DUR-05, SES-03 and OPS-04 only run their tests in it. | 2 | 5 | 0 |  |
| RES-016 | assign | FND-03, OPS-03 | FND-03 owns the manual recovery command python -m coral.db.migrate upgrade (and current), since it owns coral/db/migrate.py. | 2 | 3 | 0 |  |
| RES-017 | assign | OPS-03, FND-03, FND-02 | Docker and Databricks deploy-entrypoint enablement of Coral goes to OPS-03 as a new upstream-first seam row S57b: Docker runs Coral migrations after Omnigent's, and both deploy entrypoints pass server_plugins to create_app. FND-03 keeps S57's Databricks migration step. | 5 | 8 | 0 |  |
| RES-018 | assign | OPS-03, FND-02 | `coral server` turns the Coral plugin on by default: OPS-03's coral entry sets server_plugins: [coral.server_plugin] and passes --config, because the CLI server reads server_plugins only from an explicit --config file (cli.py:4857). FND-02 keeps the key and loader. | 1 | 3 | 0 |  |
| RES-019 | fixed | FND-04 | FND-04's bootstrap appends --config because server_runner passes none (server_runner.py:144-167) and server_plugins is read only from --config; the spec already does this. | 0 | 1 | 0 |  |
| RES-020 | assign | FND-01, OPS-03, DUR-02 | FND-01's tier rule gains named exceptions: tier-(c) omnigent.db helpers on coral.db's allowlist (pinned by signature tests) need not go through _upstream.py; coral/cli.py and coral/server_plugin.py are composition roots; coral.identity (K10) is tier (a). | 2 | 5 | 1 |  |
| RES-021 | contract | FND-02, TLS-01, WSP-01, FND-04 | K17 states the host-token split: FND-02 defines coral_runner:n; TLS-01 lands the HostHelloFrame line (S50), which advertises every Coral token registered through the K17 process map, and honours CORAL_DISABLE_HOST_ENTRY_POINTS=1; WSP-01 registers its sandbox report as a second token, coral_host_sandbox:1:<platform>:<backend>:<0\|1> (the shape in WSP-01's spec), from week 5 with no frames.py edit. WSP-01 consumes K17. | 5 | 7 | 0 |  |
| RES-022 | edge | FND-04, TLS-01 | Add soft edge FND-04 -> TLS-01: the Tier B sample needs TLS-01's S7, S8 and S10 transport and its S50 token. | 1 | 3 | 0 |  |
| RES-023 | citation | FND-01, FND-05, DUR-06, WSP-02, WEB-13, WEB-10, SPK-03 | Key-path amendments that the JSON cannot carry yet (key_paths are not edited in v3) are recorded in master notes: FND-01 lint file rename; FND-05 adds .github/workflows/ci.yml (S39c needs ci.yml:198); DUR-06 adds omnigent/cli.py and identity_migration.py (S56); WSP-02 adds host_registry.py and host_tunnel.py (S40); WEB-13 adds runs/phone/; WEB-10 owns runs/depth/ and canvas/overlay/ only; SPK-03 probes stay off tests/harness_bench/probes/. | 1 | 2 | 0 |  |
| RES-024 | split | ENG-06, SES-04, TLS-02, DUR-05 | Cancel chain: ENG-06 owns the cancel transition, which emits one K21 cancel_sessions effect per live slot (I8), and the reducer's late-submit rejection; SES-04 owns the cancel_sessions executor (interrupt -> stop -> omnigent.closed); TLS-02 owns tool-level post-cancel rejection; DUR-05 enqueues the same cancel_sessions effect for runs it cannot read. | 6 | 9 | 0 |  |
| RES-025 | split | ENG-06, TLS-02 | Rejected-call counter: ENG-06 owns the per-slot counter state and the 3-in-a-row pause (evaluation in progress and evidence.missing never count); TLS-02 only emits rejection observations that feed it. | 2 | 2 | 0 |  |
| RES-026 | split | ENG-03, HRN-02, WSP-01 | V10: ENG-03 owns the pure rule over a configured-harness list passed in; HRN-02 owns the live inputs and calls the rule from its preflight. Add soft edge HRN-02 -> ENG-03 (HRN-02 runs weeks 3-5 against a stub). HRN-02 ends at week 5 with its sandbox and validity ports failing closed; ENG-03 and WSP-01 (both start week 5) bind their checks into those ports in their own PRs. No reverse edge is added, because HRN-02 already soft-depends on both and the reverse would form a cycle. | 5 | 10 | 0 |  |
| RES-027 | split | ENG-02, ENG-08, ENG-09, ENG-01, SES-10 | Groups: ENG-02 resolves group entry, exit and body regions from reserved K1 group keys (no Group IR); ENG-08 repeats over a step or a group-body region; ENG-09 owns the Group IR proper (named, reusable groups, rule inheritance, saved blocks). SES-10 at week 14 therefore needs only ENG-02 and ENG-08. | 5 | 7 | 0 |  |
| RES-028 | contract | SES-01, GTE-06, ENG-06, ENG-09 | K19 adds overdue and reaction alert kinds (additive, signed by SES-01, implemented by GTE-06) so ENG-09 can emit them; K19 types live in the pure tier so ENG-06 and ENG-09 can import them; gates and questions are alerts. ENG-09's author-set overdue reactions are distinct from ENG-06's gate reminders and escalation. | 4 | 6 | 1 |  |
| RES-029 | citation | ENG-06, SPK-05 | Gate reminders are on at M2 (one reminder, then escalation; never auto-resolve), as master ENG-06 and SPK-05's OQ-5 proposal say; sandbox keep-warm is WSP-04 (post-M4). The ENG-06 spec is fixed; section J's OQ-5 default is wrong and must change. | 0 | 0 | 1 |  |
| RES-030 | residual | SPK-05, ENG-06, DUR-05, TLS-03 | The 30-minute watchdog default (OQ-14) and DUR-05's 3x-resync rule have no source. They stay labelled as proposals until SPK-05 records OQ-14. | 0 | 0 | 2 | SPK-05 (PM); Week 4 (TLS-03 starts week 5.5) |
| RES-031 | citation | ENG-06 | Three rejected calls pause the run as paused(rejected_calls), naming the slot (K2 pause reasons are run-level, D§7.3). M2 exit 4 and ENG-06's proving test read "pause the slot" in that sense. | 1 | 1 | 0 |  |
| RES-032 | fixed | ENG-04 | ENG-04's skeleton target "week 4.5" is a target; IM-1 (week 7) is the hard deadline. The spec already says so and agrees with the master. | 0 | 0 | 0 |  |
| RES-033 | contract | API-01, ENG-01, ENG-04 | K8 RunView and patch types live in a pure-tier module (coral/runview/types.py) produced by API-01 and co-signed by ENG-01 at IM-0; ENG-01 (K3 embeds the patch) and ENG-04 (projection.py emits patches) consume K8. No edge is added: API-01 already soft-depends on ENG-01. | 3 | 4 | 0 |  |
| RES-034 | contract | ENG-01, ENG-07, WEB-03 | K1 reserves a parameters block (name, type, default, bounds) for template parameters (loop limit, reviewer models, gate reject route) and an optional per-roster-member model override; ENG-01 reserves both at IM-0, ENG-07 fills them, WEB-03 consumes K1. | 3 | 5 | 0 |  |
| RES-035 | citation | ENG-01, ENG-05, ENG-07, SPK-01 | Loop limits count passes. D§5.6 ('three passes'), M2 journey step 4 ('pass 2 of 3'), the ENG-05 and ENG-07 proofs and IM-3's 'loop to limit 3' all count passes; only DD§5.3.3(a) counts traversals, and it is superseded. SPK-01 writes this into its OQ-19 record on day 3 of week 1; a later switch would be a K1 change. | 2 | 4 | 2 |  |
| RES-036 | split | ENG-04, ENG-11 | I7: ENG-04's fuzz harness checks I7 in reducer form only; ENG-11 owns the full reconcile property test. | 1 | 2 | 0 |  |
| RES-037 | contract | ENG-08, ENG-01, HRN-02, SES-10 | K1 Analysis gains requires_structure_runtime (additive, ENG-08). ENG-08 also adds the preflight check that refuses such runs to HRN-02's pure preflight module (HRN-02 ends week 5, before the flag exists), and SES-10 lifts the refusal at exit. ENG-01 and HRN-02's owner sign the flag when ENG-08's first PR lands. Add soft edge ENG-08 -> HRN-02. | 4 | 6 | 0 |  |
| RES-038 | contract | FND-02, SES-07, WEB-12, ENG-09, WSP-04 | The /v1/coral/info sub-feature map gains four keys, each flipped by its owner: slot_refresh (SES-07), scenario_editor (WEB-12), blocks (ENG-09; the blocks router mounts only when on) and sandbox_runs (WSP-04). | 3 | 7 | 1 |  |
| RES-039 | edge | ENG-08, ENG-09, ENG-07 | Add soft edges ENG-08 -> ENG-07 and ENG-09 -> ENG-07: both proofs run ENG-07's Simulate and ENG-08 extends its list_len input. | 2 | 6 | 0 |  |
| RES-040 | contract | RUL-03, ENG-09 | K15 gives each template a strictness_key and a strictness order in RUL-03's first PR, so ENG-09's V8 can compare inner and outer rules. | 2 | 3 | 0 |  |
| RES-041 | contract | ENG-01, ENG-11, SES-09, HRN-04 | K2 additive taxonomy, ledgered by ENG-01 after IM-0: cause infra.runner_lost (runner-loss origins), the SES-09 drift causes (session_archived, session_deleted, anchor_archived, anchor_deleted, session_stopped, policy_missing, bundle_changed) and a paused_until resume time on paused(plan_limit) (HRN-04). | 2 | 2 | 0 |  |
| RES-042 | contract | ENG-01, DUR-01, TLS-02, SES-06, SES-08 | Slot fields join K2 and DUR-01's coral_0001 slot columns before DUR-01 lands: the evaluating lease (lease_holder, lease_expires_at; X-15), hold_seen_at, restart_attempt_id, last_edge_status, last_turn_outcome and last_edge_at. Edge facts persist as unapplied coral_signals rows plus those columns; no turn_facts table. | 3 | 5 | 1 |  |
| RES-043 | contract | RUL-01, ENG-01, API-02 | RUL-01's SessionCapReached observation and ResumeRun.raise_session_cap_usd are additive K2 changes that ENG-01 ledgers by week 5; API-02's resume action accepts the optional raise_session_cap_usd for paused(budget). | 2 | 2 | 0 |  |
| RES-044 | contract | ENG-01, ENG-09, HRN-07, SES-07 | Later features add K3 log kinds additively (ENG-09 rule resolution, HRN-07 slot rotation, SES-07 take-over); ENG-01 ledgers each as an additive enum value with no fold change. HRN-07, ENG-09 and SES-07 consume K3. | 4 | 3 | 0 |  |
| RES-045 | nongoal | DUR-06 | Legal hold is a non-goal through M4 with no owner (it is not a deferred gap). Retention of Omnigent sessions and transcripts of runs is part of the OQ-25 record (SPK-05) that DUR-06 implements. | 1 | 2 | 0 |  |
| RES-046 | fixed | DUR-02, API-02 | Test-path layout is settled in the specs (DUR-02 API tests in tests/coral/api/, DUR-04 in tests/coral/workers/, DUR-05 in tests/coral/reconcile/, DUR-01 in tests/db/coral/); the API-02 note is already removed. | 0 | 0 | 0 |  |
| RES-047 | contract | DUR-04, DUR-01 | Migration train: coral_0002_queue (DUR-04) holds the queue, timers, effects outbox, signals and the worker lease. | 1 | 2 | 1 |  |
| RES-048 | contract | DUR-06 | Migration train: add DUR-06's retention migration (policy and purge jobs), PH4, prerequisite coral_0001, in the weeks 13.5-18 group after notify, because DUR-06 runs weeks 13.5-15.5. | 1 | 1 | 2 |  |
| RES-049 | residual | DUR-03, DUR-04 | DUR-03 step 3 needs DUR-04's first PR (coral_0002_queue) inside DUR-03's window. No edge can be added (DUR-04 already soft-depends on DUR-03, so the reverse edge forms a cycle). DUR-03 builds step 3 on K5's queue layout and the fake until coral_0002 lands. | 0 | 1 | 1 | PLATFORM lead (DUR-04); Week 6 (coral_0002_queue merged) |
| RES-050 | citation | DUR-02, WEB-11, BRD-03, WSP-02, EVD-03 | Errata for wf1 citations that later sections inherit: get_artifact_store is runtime/__init__.py:120-130 (not 96-106); monacoSetup.ts worker is :52-57 and the "language services unused" comment :9-12 (not 12-17); the shared-runner child helper in test_session_host_launch.py is at :4725 (not 725-742); _decode_fs_request accepts an empty session_id (eng_workspace:116 is wrong); host frame tasks are not cancelled on disconnect (eng_workspace:73 is wrong); iOS maps CFBundleDisplayName in both plists at lines 7-8 (eng_web is wrong); ConversationAlreadyExistsError is raised at sqlalchemy_store.py:1300-1313. | 1 | 2 | 1 |  |
| RES-051 | assign | BRD-02, GTE-03, HRN-04, DUR-06 | Coral settings pages (notifications, model access, retention) mount as Coral routes under /workflows/settings/* in BRD-02's coralRoutes fragment. An entry in the upstream Settings nav (closed SettingsSectionId union, settingsNavGroups) is a non-goal. | 2 | 5 | 0 |  |
| RES-052 | assign | OPS-07, SES-05, WEB-01 | OPS-07 owns the CI-only real-server browser lane (tests/e2e_ui/workflows/) that IM-4 needs, including a real-trace diagram row for WEB-01. OPS-07 owns the IM-3 and IM-4 tests; the WEB lead owns IM-4 convergence. SES-05's browser E2E is OPS-07's lane. | 4 | 7 | 0 |  |
| RES-053 | edge | SES-04, SES-03, DUR-01 | Add soft edge SES-04 -> DUR-01 (K5, K21 and coral_0001 for stable_ids). The session_bindings migration prerequisite becomes "ADR-05; coral_0001". coral_0001 must merge by week 4 so SES-03 and SES-04 can land their migrations; a hard edge would warn (DUR-01 ends week 5). | 2 | 4 | 3 | DUR-01 (PLATFORM lead); Week 4 (coral_0001_core merged) |
| RES-054 | contract | SES-02, SES-08, SES-01 | K18 names the four origin sites: the relay recovery turn end B1 (orchestration.py:9565-9582), the status-probe notify, the archive idle edge (published at orchestration.py:944 in _stop_host_runner_intentionally) and the runner-disconnect edge. The main relay headless edge (orchestration.py:9583) stays "unknown" and relies on turn_outcome (S43). | 2 | 2 | 0 |  |
| RES-055 | citation | SES-02 | Hot-file order correction: the archive-idle origin is set in orchestration.py (published at :944 via _archive_stop, :1027), not routes_events.py. | 1 | 1 | 3 |  |
| RES-056 | edge | SES-02, SES-01 | Add soft edge SES-02 -> SES-01: SES-02 implements K18 in the same weeks SES-01 freezes it. | 1 | 5 | 0 |  |
| RES-057 | edge | SES-03, TLS-01 | Add soft edge SES-03 -> TLS-01: SES-03 refuses hosts without the coral_runner token, which TLS-01 adds; tests use a fake host hello until TLS-01 lands (week 3). | 1 | 3 | 0 |  |
| RES-058 | edge | SES-04, FND-04 | SES-04 closes its feature proof on Tier A (K13 fake, injected SubmitHandoff) at week 5; the Tier B queued-input variant runs as its IM-2 exit item. Add soft edge SES-04 -> FND-04. Until SES-08 lands, SES-04 detects post-close turns through a narrow observer in SES-02's registry. | 2 | 3 | 1 | SES-04 (INTEGRATION lead); IM-2, week 11.5 |
| RES-059 | edge | SES-05, API-02, PRF-01 | Add soft edges SES-05 -> API-02 (run start) and SES-05 -> PRF-01 (inert anchor agent and step bundle); SES-05 keeps a test-only start hook and test agents until they land. | 2 | 5 | 0 |  |
| RES-060 | split | PRF-01, SES-09, PRF-02 | Slot-start drift: PRF-01 checks the pinned bundle digest, re-puts a missing blob and returns the digest; SES-09 alone decides to pause (paused(drift)) on policy, label or digest drift; PRF-02 records profile_changed on a revision mismatch and never pauses. | 4 | 4 | 0 |  |
| RES-061 | contract | SES-07, SES-01, HRN-07 | SES-07's take-over and hand-back endpoints are additive K7 routes, so SES-07 consumes K7; supersede() is an additive K4 change signed by SES-01 (with HRN-07's on_supersession and label query). | 3 | 2 | 0 |  |
| RES-062 | assign | WEB-10, SES-10, GTE-02 | The batched gate card is WEB-10's (WS-WEB, M4, weeks 17.5-22): GTE-02's WorkflowInboxCard extended with a per-item list for SES-10's K14 batch payload, reusing the run view's per-item list. SES-10 keeps per-item gates and batching on GTE-01. GTE-02 excludes the card. | 7 | 9 | 0 |  |
| RES-063 | residual | SES-06, SES-09 | SES-06 and SES-09 finish at week 9.5 but their proving tests need DUR-05 and SES-08 (ending 11.5 and 11), so they close at IM-3 (week 11.5). No schedule change. | 0 | 2 | 1 | SES-06 and SES-09 (INTEGRATION lead); IM-3, week 11.5 |
| RES-064 | assign | SES-10, WSP-03, WSP-07 | SES-10 exits at week 16 with E2E-5 on WSP-03 and WSP-07 fakes. INT-T2, its track, has no other work after week 16 (H.1), so the same engineer carries the IM-7 convergence tail to week 22.5: E2E-5 is re-run against RUL-03's templates (week 18), WSP-07's push (20) and WSP-03's merges (22.5). No split and no new staffing; the IM-7 date stays a tracked risk. | 1 | 4 | 3 | INTEGRATION lead (SES-10); IM-7, week 22.5 |
| RES-065 | edge | SES-08, ENG-06 | Add soft edge SES-08 -> ENG-06: the plan-limit probe uses ENG-06's timer kinds. | 1 | 3 | 0 |  |
| RES-066 | contract | SES-01, SES-08, HRN-03, HRN-04, HRN-07 | K18 TurnFacts gain an optional response_id (keyed (session, response_id)) for HRN-03's level-triggered fallback, a resets_at field for HRN-04, and a supersession observer hook for HRN-07; all additive, signed by SES-01 with SES-08. | 1 | 1 | 0 |  |
| RES-067 | assign | SES-06, SES-07 | If spike 16 fails, the whole S27 seam moves to SES-06, including the coral.keep_alive label exemption, not only the retest. | 2 | 3 | 0 |  |
| RES-068 | nongoal | TLS-04, TLS-05 | Reusing sys_session_message (TLS-04) and step agents asking the user directly (TLS-05, OQ-13 default) are non-goals with no owner; PRF-01 denies vendor ask tools and GTE-02 shows "Step waiting on you". | 2 | 0 | 0 |  |
| RES-069 | assign | SES-10, TLS-04 | Tier B multi-session coverage of the messaging tools goes to SES-10's E2E-5: one coral_message_agent exchange between the two real sessions. Add soft edge SES-10 -> TLS-04 (TLS-04 ends week 15.5, inside SES-10's window). | 3 | 5 | 0 |  |
| RES-070 | assign | TLS-01 | S49 ("Up: Yes") ships in S10's upstream PR; TLS-01's upstream PR list says so. | 1 | 2 | 0 |  |
| RES-071 | edge | TLS-01, FND-02 | Add soft edge TLS-01 -> FND-02 (K17): step 5 merges after FND-02's PluginRegistration PR. | 1 | 3 | 0 |  |
| RES-072 | edge | TLS-03, SES-06 | Add soft edge SES-06 -> TLS-03: SES-06's ladder ends by briefing the new generation, and for an orchestrator that brief is TLS-03's re-brief (TLS-03 ends week 7.5, when SES-06 starts). TLS-03 consumes K10 (coral.role) and K4 (create and send). | 3 | 5 | 0 |  |
| RES-073 | split | TLS-04, WSP-03 | TLS-04 owns coral_assign_task and fakes the conflict sub-state until IM-7; WSP-03 owns the conflict sub-state and calls TLS-04's real tool (TLS-04 lands first, weeks 13.5-15.5). WSP-03's "fake assign_task until TLS-04 lands" is wrong. | 0 | 2 | 0 |  |
| RES-074 | edge | TLS-05, ENG-06, GTE-06 | Add soft edge TLS-05 -> ENG-06 (watchdog suspension) and K2 to TLS-05's consumed contracts. The questions migration no longer needs the alerts table: its prerequisite becomes "coral_0001; K19 (no foreign key to alerts)", so TLS-05's week-9 migration does not wait for GTE-06. | 3 | 5 | 2 |  |
| RES-075 | assign | GTE-06, ENG-04, ENG-06 | GTE-06 adds the gate-open, run_completed and run_failed notify emitters as a small reducer PR reviewed by ENG-04's owner; ENG-06's cancel transition keeps the run_cancelled notify it already emits (eng-a.md, Cancel); ENG-04 emits only publish_gate and withdraw_gate. GTE-06 turns all of them into alerts. ENG-04 and ENG-06 owners sign off in that PR. | 4 | 6 | 0 |  |
| RES-076 | nongoal | GTE-02, GTE-03, GTE-04 | Non-goals with no owner: localStorage read state (server-side ack, X-30), Slack-originated sessions (existing upstream integration) and email digests. | 3 | 3 | 0 |  |
| RES-077 | nongoal | GTE-01, GTE-06 | Answering multi-label gates on /approve is a non-goal through M4: get_elicitation omits requestedSchema, so ApprovePage offers only Approve and Reject. Binary gates work; deep links for multi-label gates open the run view. | 2 | 3 | 0 |  |
| RES-078 | fixed | GTE-02 | GTE-02 (weeks 5-7) proves cross-client ack on MSW only; the live proof runs at IM-4 (week 11.5). The spec already says so. | 0 | 1 | 0 |  |
| RES-079 | citation | GTE-02 | S37 is not a one-line spread: it needs about seven anchored points in InboxPage.tsx plus one useSidebarData line. The S37 budget and the hot-file row are amended. | 2 | 2 | 3 |  |
| RES-080 | nongoal | GTE-02, GTE-06 | The Extend run action is dropped: gates never expire (OQ-5) and no backend owns it. GTE-02's actions are open, resume and cancel; K19 actions never list Extend. | 1 | 5 | 0 |  |
| RES-081 | citation | GTE-05 | omnigent/server/elicitation_hooks.py does not exist at HEAD; it is new upstream-path code counted under S6's budget. | 1 | 2 | 0 |  |
| RES-082 | assign | GTE-04, BRD-03 | GTE-04 owns desktop delivery through an inbox watcher loaded from web/electron/src/main.js under new seam row S87b, landed after BRD-03's S87. CI covers only the push-service HTTP boundary. Electron Web Push availability is unverified. | 2 | 4 | 1 | GTE-04; Week 26.5 (GTE-04 start) |
| RES-083 | nongoal | EVD-04 | Hidden held-out tests and LLM rubric judges are non-goals with no owner (not master-deferred gaps). | 2 | 1 | 0 |  |
| RES-084 | fixed | EVD-04 | The EVD-04 S72 ledger note was stale: master §7 already lists "S72 detached mode (EVD-04)" as a ledger amendment. | 0 | 0 | 0 |  |
| RES-085 | contract | EVD-02, FND-02 | EVD-02 consumes K17 (the S68 observer registers through the process map) and keeps K6 (the evidence opt-in key in params.coral). Add soft edge EVD-02 -> FND-02. | 2 | 4 | 0 |  |
| RES-086 | edge | EVD-03, WSP-01 | Promote EVD-03 -> WSP-01 from soft to hard: the migration train makes repo_bindings a prerequisite of command_patterns. WSP-01 ends week 7, when EVD-03 starts, and the phase and milestone order holds. | 2 | 3 | 0 |  |
| RES-087 | edge | EVD-01, ENG-02 | Add soft edge EVD-01 -> ENG-02. ENG-02 owns a done_when compile hook in its compiler; EVD-01 owns compile_done_when, which the hook calls. | 2 | 4 | 0 |  |
| RES-088 | contract | EVD-01, EVD-02, HRN-03, SPK-04 | K11's watermark is a per-session transport sequence plus EVD-02's in-flight cover rule (claude-sdk has no item seq at ingestion; HRN-03 maps native item seqs onto it). L1 is computed in Python (os.stat, git hash-object --stdin-paths), never with shell stat. | 3 | 3 | 0 |  |
| RES-089 | edge | EVD-02, WSP-06, TLS-02 | Add soft edge EVD-02 -> WSP-06 (session-shell fingerprint). EVD-02's proof needs TLS-02 and WSP-06, so it closes on Tier A at week 7 and its Tier B run is at IM-3 (week 11.5). TLS-02 cannot be an edge (TLS-02 soft-depends on EVD-02). | 1 | 3 | 1 | EVD-02 (WS-WORKSPACE lead); IM-3, week 11.5 |
| RES-090 | contract | EVD-03, DUR-02, API-01 | EVD-03 consumes K7 and gets a soft edge to DUR-02 (the snapshot writes through DUR-02's store). K7 names /v1/coral/repos/{id}/command-patterns routes (EVD-03). | 3 | 6 | 0 |  |
| RES-091 | contract | EVD-04 | EVD-04 consumes K1 (check keys), K2 (observations), K3 (log kinds) and K21 (executor registration). | 4 | 5 | 0 |  |
| RES-092 | contract | OPS-01, API-01, WEB-04, WEB-03, FND-05 | K16 v1 adds anchor_exempt entries (files that cannot carry anchors: JSON, lockfiles, python-matrix.json) and non-seam MF-n entries for dependency-manifest edits. API-01 owns the msw devDependency MF entry; WEB-04 owns the axe devDependency PR and MF entry (WEB-09 reuses it). | 3 | 6 | 0 |  |
| RES-093 | edge | API-02, FND-02 | Add soft edge API-02 -> FND-02 and K17 to API-02's consumed contracts (plugin registration and the K4 access adapter). | 2 | 4 | 0 |  |
| RES-094 | assign | WSP-06, API-02 | Engine commit records: WSP-06 writes {sha, subject, node, item_path} into each commit effect's EffectCompleted log entry; API-02's outcome folds its commit list from those entries. No new table. | 2 | 3 | 0 |  |
| RES-095 | split | RUL-05, API-02 | RUL-05's spend aggregator reuses API-02's K4 usage adapter rather than a second implementation. | 1 | 1 | 0 |  |
| RES-096 | split | EVD-01, EVD-02, WSP-01, WSP-06, WSP-02 | L1 and K13 backends: EVD-01 owns the pure L1 probe and digest code; EVD-02 enforces it per command and at submit; WSP-01 owns the K13 interface, fake and conformance tests; WSP-06 implements the session-shell backend; WSP-02 and WSP-07 implement the host-channel backend. | 2 | 2 | 0 |  |
| RES-097 | assign | HRN-06, EVD-02 | Headless codex command observations (exit code and L1 fingerprint) are unowned; HRN-06 owns them through EVD-02's K4 observations adapter and consumes K11. | 2 | 3 | 0 |  |
| RES-098 | assign | RUL-02, WEB-13, WEB-03 | RUL-02 owns the thin label routes in coral/api/guarantees.py (GET /v1/coral/runs/{id}/guarantees and the version :guarantees POST); they are additive K7 routes, so RUL-02 consumes K7. | 3 | 3 | 0 |  |
| RES-099 | fixed | RUL-03 | The RUL-03 datamodel citation (datamodel.py:593-618 built-in masks) was corrected by the verifier; spec and master agree. | 0 | 0 | 0 |  |
| RES-100 | residual | RUL-03 | An Enforced protect_paths on claude-sdk needs compiled sibling write grants (UNVERIFIED on seatbelt) or an unplanned sandbox seam, because write_paths is an allowlist and shell writes bypass a write-tool DENY. | 0 | 1 | 1 | RUL-03 (WS-HARNESS lead); Week 15.5 (RUL-03 mid-window) |
| RES-101 | citation | RUL-01 | S52 touches four builder.py sites (three assembly sites plus the fast path), not one line. | 1 | 2 | 0 |  |
| RES-102 | citation | RUL-01 | RUL-01's proving test is split: the upstream half in tests/runtime/policies/ and the Coral half in tests/coral/omni/policies/test_run_guard.py, because upstream tests cannot import coral. | 1 | 1 | 0 |  |
| RES-103 | contract | RUL-03, RUL-05 | RUL-03 (authoring keys) and RUL-05 (step budget keys) consume K1. | 2 | 4 | 0 |  |
| RES-104 | citation | RUL-04, HRN-03, HRN-05 | Hot-file order amendment: RUL-04's S14 also touches runner/native/orchestration.py and codex_native/app_server.py (land before HRN-03 and HRN-05), and S16 touches helpers.py and policies/types.py. | 1 | 2 | 1 |  |
| RES-105 | contract | DUR-01, RUL-05, EVD-04, WSP-03, SES-07, ENG-09, EXT-01, EXT-04, GTE-04 | Run budget and spend columns are not in coral_0001; RUL-05's coral_00NN_budgets migration owns them (master train already lists budgets under RUL-05). Every migration-train owner consumes K5, so RUL-05, EVD-04 (check_runs), WSP-03 (merge_state), SES-07 (slot_control columns), ENG-09 (saved_blocks), EXT-01, EXT-04 and GTE-04 (the post-M4 tables) now list it. | 10 | 12 | 0 |  |
| RES-106 | edge | RUL-05, HRN-04 | Add soft edge RUL-05 -> HRN-04: utilization uses HRN-04's S24 data when present; otherwise RUL-05 shows tokens only. | 1 | 3 | 0 |  |
| RES-107 | edge | RUL-02, WSP-01 | Add soft edge RUL-02 -> WSP-01: labels read the host sandbox backend from WSP-01's report. | 1 | 3 | 0 |  |
| RES-108 | split | RUL-01, PRF-01 | Spawn grants: PRF-01 writes spawn: false and tools.agents: [] into bundles; RUL-01 checks them at run start (assert_run_grants). | 2 | 3 | 0 |  |
| RES-109 | split | RUL-01, EXT-02 | Input scoping: RUL-01 owns the whole-step deny_session_reads policy (internal_only); EXT-02 binds it per member and adds files.materialize. | 1 | 2 | 0 |  |
| RES-110 | assign | RUL-01, SES-03, SES-09 | Forks copy coral.* labels, so RUL-01's run-guard provider confirms the session binding (K4 lookup implemented by SES-03, fake until then) rather than trusting labels. | 1 | 2 | 0 |  |
| RES-111 | fixed | RUL-06 | RUL-06's proving test pins the claude-native K9 value to ask in its fixture and adds a deny case; the spec already does this. | 0 | 1 | 0 |  |
| RES-112 | split | HRN-04, HRN-08 | HRN-04 keeps only the usage_limit_signal mock-provider probe; HRN-08 owns the bench harness, the other probes and the nightly. | 2 | 3 | 0 |  |
| RES-113 | split | HRN-04, ENG-11, SES-08 | HRN-04's S24 structured signal feeds ENG-11's classifier through SES-08; it does not replace SES-08's logic. ENG-11 owns the classifier. | 3 | 2 | 0 |  |
| RES-114 | contract | PRF-01, HRN-02, FND-02 | PRF-01 (seed agents) and HRN-02 (token check) consume K17; add soft edges PRF-01 -> FND-02 and HRN-02 -> FND-02 (FND-02 ends week 3; no schedule change). | 4 | 8 | 0 |  |
| RES-115 | contract | HRN-04 | HRN-04 consumes K18 (resets_at) and K2 (paused_until resume time). | 2 | 3 | 0 |  |
| RES-116 | fixed | PRF-02 | PRF-02 follows decision 9 (revision digests stay authoring-only, not in the version content hash); eng_harness §8.4 step 4 is superseded. | 0 | 1 | 1 |  |
| RES-117 | fixed | PRF-01 | PRF-01's allowlist goldens use a test registry until RUL-01's handlers land; the soft edge PRF-01 -> RUL-01 already exists. | 0 | 1 | 0 |  |
| RES-118 | assign | HRN-05, HRN-07 | The codex-native /clear Tier B goes to HRN-05 (codex-native posts the same external_session_superseded event, and HRN-07's follower is harness-neutral). Add soft edge HRN-05 -> HRN-07. | 3 | 5 | 0 |  |
| RES-119 | split | HRN-07, EXT-04 | /clear policy: HRN-07 owns the OQ-46 follow-or-block decision and the follower; EXT-04's S46 applies HRN-07's policy and adds none of its own. Because S46 strips coral.* labels, HRN-07's loss fallback looks up the bridge id. | 2 | 4 | 0 |  |
| RES-120 | edge | HRN-06, RUL-04 | Add hard edge HRN-06 -> RUL-04: gate_failure_mode=deny needs RUL-04's S14 fail-closed output. RUL-04 (PH2, M3) ends week 7, before HRN-06 starts (PH5, M4, week 21). | 1 | 3 | 0 |  |
| RES-121 | citation | HRN-09 | Hot-file order amendment for codex_executor.py: HRN-09 lands S18 and S19 (thread/compact/start) there; S60 changes workflow.py and the parser, not the executor. | 1 | 1 | 1 |  |
| RES-122 | contract | HRN-07, TLS-02, SES-03, SES-01 | After a native /clear rotation, the slot binding records the replacement session id; TLS-02 resolves submits through the binding, so K10's uuid5 ids identify only the original session. HRN-07 consumes K10. SES-03 and TLS-02 sign this before HRN-07 starts. | 2 | 4 | 0 |  |
| RES-123 | assign | HRN-09 | HRN-09 carries the same OQ-29 condition as HRN-06: dark behind codex_steps while OQ-29 is unanswered (matches M4 exit 4). | 2 | 2 | 0 |  |
| RES-124 | assign | OPS-04, HRN-06 | OPS-04's security closure covers HRN-06's S20 runner policy relay as a new security surface. HRN-06 may be larger than M (ENG-29); that stays a residual risk. Add soft edge OPS-04 -> HRN-06 (HRN-06 ends week 23, inside OPS-04's weeks 21-25.5). | 2 | 3 | 1 | HRN-06 (HARNESS lead); Week 21 (HRN-06 start) |
| RES-125 | citation | HRN-05 | The S62 ledger row names the codex-native approval handler: codex_elicitation_request_hook (routes_hooks.py:1262-1340; methods at _codex_elicitation.py:16-18). | 1 | 1 | 0 |  |
| RES-126 | split | HRN-05, HRN-04 | The headless codex_executor.py S24 branch lands in HRN-05 per §6.5, despite HRN-05's headless-codex exclusion; HRN-04 owns the shared signal. | 1 | 2 | 0 |  |
| RES-127 | split | HRN-05, HRN-08, RUL-06 | Codex-native K9 values: HRN-08 keeps egress_scope and usage_reporting "unknown" until HRN-05's spikes 12 and 13 set them; HRN-05 sets K9 values only and RUL-06 computes labels. | 2 | 2 | 0 |  |
| RES-128 | assign | WSP-05 | WSP-05 audits the other plain to_thread frame handlers (connect.py:5950-6052: stat, list_dir, skills, plugins, harness startup, MCP servers) for subprocess spawns and records the result in the S71 row; any that spawn get the same guard as an S71 amendment. | 1 | 3 | 0 |  |
| RES-129 | assign | WSP-05 | S71 includes the WorkspaceReader fix: on the host, WorkspaceReader starts GitFilesystemRegistry with background=False so no git probe runs after the guarded handler returns. | 1 | 3 | 0 |  |
| RES-130 | assign | WSP-07, WEB-03 | The push-consent UI goes to WSP-07: a consent row in WEB-03's start dialog that names the remote and branch prefix, with WEB-lead review. Add soft edge WSP-07 -> WEB-03. | 2 | 4 | 0 |  |
| RES-131 | nongoal | WSP-04 | Managed-sandbox provider onboarding is upstream behaviour and a Coral non-goal. | 0 | 1 | 0 |  |
| RES-132 | assign | WSP-04, WEB-03 | WSP-04 owns the managed-sandbox host choice and the "This provider loses work when it sleeps" refusal in WEB-03's start dialog (post-M4, WEB-lead review). Add soft edge WSP-04 -> WEB-03. | 2 | 4 | 0 |  |
| RES-133 | contract | WSP-01, WSP-03, WSP-04, WSP-07 | Workspace features consume what they use: WSP-01 consumes K7 (bindings API) and K21 (create_run_worktree); WSP-03 consumes K2, K6 and K21; WSP-04 and WSP-07 consume K21. | 7 | 9 | 0 |  |
| RES-134 | contract | WSP-01, WSP-02, WSP-06, WSP-07 | K13 errors are additive; v1 lists op_host_violation, backend_unavailable, git_failed, timeout, and later features add capability_unavailable (WSP-02), disk_cap (WSP-06), push_not_permitted and invalid_ref (WSP-07). | 1 | 0 | 0 |  |
| RES-135 | contract | WSP-01, SPK-04, EVD-01 | K13 v1 text freezes at IM-0 (week 3, M1 exit 7) from SPK-04's draft, signed by the WORKSPACE lead; WSP-01's first PR (week 5) lands it as code without changing it. EVD-01 (weeks 3-5) builds on the frozen text and the fake. | 1 | 1 | 1 | WORKSPACE lead (SPK-04, WSP-01); IM-0, week 3 |
| RES-136 | citation | WSP-01, WSP-02 | S40 and S72 ledger rows add omnigent/server/host_registry.py and host_tunnel.py:999-1011, which the ledger and WSP-02's key paths omit. | 1 | 2 | 0 |  |
| RES-137 | edge | WSP-04, WSP-07 | Add soft edge WSP-04 -> WSP-07: checkpoints use WSP-07's push and consent. | 1 | 3 | 0 |  |
| RES-138 | fixed | WSP-01 | WSP-01's start_commit waits for the first activation when the rev-parse fallback needs WSP-06's shell; this is a spec-level decision. | 0 | 1 | 0 |  |
| RES-139 | citation | WSP-02 | WSP-02's proving test file test_frames.py covers the token; the L2 and fallback asserts live in tests/coral/omni/host/ops/ and K13 conformance. | 1 | 1 | 0 |  |
| RES-140 | assign | DUR-02, WEB-02, WEB-03, ENG-07 | DUR-02 owns GET /v1/coral/templates and POST /v1/coral/templates/{id}:use over ENG-07's package-data templates; K7 names both. | 2 | 3 | 0 |  |
| RES-141 | split | WEB-01, WEB-12 | Failing saved case: WEB-01 lists the expected and actual paths; WEB-12 owns CaseDiff (first divergent box) and reuses WEB-01's failing-case view. | 2 | 3 | 0 |  |
| RES-142 | nongoal | WEB-05, WEB-07, WEB-11 | Edits to web/src/shell/SubagentTab.tsx (WEB-05), web/src/pages/settings/ (WEB-07) and web/src/shell/monacoSetup.ts (WEB-11) are non-goals: these key paths are read-only references with no seam; any edit needs an OPS-01 ledger entry first. | 1 | 3 | 0 |  |
| RES-143 | assign | WEB-13, WEB-06 | There is one label-chip component: WEB-13's PromiseLabelChip (lands at M2). WEB-06 reuses it and adds no LabelChip.tsx. Add soft edge WEB-06 -> WEB-13. | 2 | 5 | 0 |  |
| RES-144 | split | WEB-04, WEB-10, WEB-13, WEB-01 | web/src/workflows/runs/ layout: WEB-04 owns the root; WEB-13 owns runs/list/, runs/outcome/ and runs/phone/; ENG-10 owns runs/restart/; WEB-10 owns runs/depth/ and canvas/overlay/, and its step 1 moves WEB-01's canvas/overlay.ts to canvas/overlay/types.ts. | 1 | 2 | 0 |  |
| RES-145 | assign | WEB-01 | WEB-01's "too large" state uses a 200-node threshold, configurable, and is re-checked with the OQ-1 NFRs. | 1 | 1 | 0 |  |
| RES-146 | fixed | WEB-02, WEB-06, WEB-07, WEB-04 | Accepted sequencing notes that need no master change: WEB-02's Runs tab shows a placeholder until WEB-13 (week 11); until WEB-08, "on-box" means WEB-01's read-only preview; WEB-07 relies on PRF-02's server-side reinstall to keep params.coral; WEB-04's S35 note restates master §6.4. | 0 | 4 | 0 |  |
| RES-147 | nongoal | WEB-03 | No upstream initialPhase edit to HarnessFixDialog: WEB-03's auth failures deep-link to the dialog, and the API-key form is one click away (reconfigure opens on "choose"). | 1 | 2 | 0 |  |
| RES-148 | nongoal | WEB-05 | Changing the upstream anchor composer copy ("This sub-agent session is closed") is a non-goal: no seam covers it, and the S86 banner explains. | 0 | 1 | 0 |  |
| RES-149 | residual | WEB-05, SES-03, RUL-01, SPK-02 | If SPK-02 probe (e) fails, SES-03 uses RUL-01's DENY instead of omnigent.closed; the upstream anchor composer stays enabled and only the S86 banner explains. | 0 | 1 | 1 | SPK-02 (probe e) with SES-03; Week 2 |
| RES-150 | contract | DUR-02, RUL-06, WEB-08, ENG-10, API-02, WEB-10, WEB-09, WEB-06, WEB-11, WEB-12, WEB-13 | Additive K7 fields, one owner each: :validate returns the compiled graph (DUR-02, for WEB-11) and labels (RUL-06, for WEB-06); drafts carry a layout field (WEB-08, a small backend PR in DUR-02's store reviewed by the PLATFORM lead); versions expose case_results (DUR-02, which already stores CaseResult, for WEB-12); the outcome carries repo path and worktree state and runs-list rows carry a path summary (API-02, for WEB-13); the log endpoint gains arrow_id and scope_key filters (WEB-10, reviewed by API-02's owner). WEB-09, RUL-06 and ENG-10 (versions, diff and restart routes) consume K7. Soft edges WEB-08 -> DUR-02 and WEB-10 -> API-02 record the backend PRs. | 12 | 21 | 0 |  |
| RES-151 | contract | API-01, GTE-01, API-02 | K7 picks one stale-answer code: 409 stale_visit for GTE-01 and API-02 (not gate_not_current); typed not_permitted is HTTP 403. The error-code list lives in API-01's spec, so API-01 changes it; GTE-01 returns a K7 code, so it consumes K7. | 2 | 3 | 1 |  |
| RES-152 | split | WEB-08, ENG-09, WEB-09 | WEB-08 step 5 (group-membership patches) builds on K1's group kind and members key, reserved at IM-0 (RES-027), so it does not wait for ENG-09 and never moves to WEB-09. ENG-09's Group IR (named, reusable groups and group rules) reaches the canvas through WEB-09. | 1 | 3 | 0 |  |
| RES-153 | nongoal | WEB-13, SPK-05 | WEB-13's run-end analytics events stay client-side through the host analytics sink (web/src/lib/analytics.ts; the server has no product-analytics pipeline). Each fires once per run and browser and carries the run id, so metrics count distinct run ids and a run opened on two devices is not double counted. Server-side emission is a non-goal through M4; OQ-26 (SPK-05, week 4) still picks the metrics. | 1 | 2 | 1 |  |
| RES-154 | split | BRD-01, BRD-03 | S89 splits: BRD-01 keeps the web brand strings (S89); BRD-03 owns the Electron setup and connect pages as S89b. | 3 | 3 | 0 |  |
| RES-155 | nongoal | BRD-03 | Android run deep links are a non-goal through M4 (no custom-scheme handler, AndroidManifest.xml:39-77); S38 covers Electron and iOS. | 1 | 2 | 0 |  |
| RES-156 | citation | BRD-03, BRD-02 | Master proving-test readings: BRD-03's link is coral://<host>/workflows/runs/<id> (a hostless link parses "workflows" as the host); BRD-02's "unknown routes no longer light New session" means the Coral desk paths. | 1 | 2 | 0 |  |
| RES-157 | citation | BRD-03 | "About 37 literals" counts main.js only; desktop_updater.js, quitConfirmation.js:28 and :31, and ssh_connect.js also show "Omnigent". | 1 | 2 | 0 |  |
| RES-158 | edge | BRD-02, BRD-03, OPS-01 | BRD-02 consumes K16 (it lands three upstream seams) with a soft edge to OPS-01; add soft edge BRD-03 -> BRD-02 (the deep-link proof needs BRD-02's routes). | 3 | 7 | 0 |  |
| RES-159 | citation | BRD-02 | withPageView is module-private (App.tsx:24-29), so the route fragment is coralRoutes(prefix, withPageView). | 1 | 1 | 0 |  |
| RES-160 | fixed | BRD-01, BRD-02, BRD-03 | Spec length overruns (a few specs at 901-974 words) are accepted; deleting the resolved Reviewer notes per this log brings most under 900. | 0 | 0 | 0 |  |
| RES-161 | nongoal | BRD-03, OPS-05 | Store listings, mobile bundle ids and signing are a non-goal through M4 (OQ-31 has no answer and mobile push is deferred, G-37). | 1 | 1 | 0 |  |
| RES-162 | residual | OPS-03, OPS-05 | _default_runner_id_path (runner/identity.py:239-244), admin_list.py:73 and codex_native/app_server.py:1863 ignore OMNIGENT_DATA_DIR. OPS-03's isolation test covers them; any fix is a generic upstream-only PR through OPS-05, not a fork seam. S75 enables no update channel, so _CACHE_DIR needs no fork change. | 1 | 3 | 1 | OPS-03; Week 6 (OPS-03 finish) |
| RES-163 | contract | OPS-01, FND-01 | Upstream PR links live in .coral/upstream.yaml keyed by seam id (with the pin and merge history), as DoD 6.1 item 2 and ten specs say; seams.yaml holds seam definitions and the upstream-first flag. | 2 | 3 | 0 |  |
| RES-164 | fixed | OPS-01 | OPS-01 pins the fork point 2a9cbe2c2 for the first ledger (4 commits past nightly^1); later merges pin a nightly^1. The spec already decides this. | 0 | 1 | 0 |  |
| RES-165 | citation | OPS-02 | OPS-02's proof (two real merges two weeks apart) closes near week 6, after its week-4 planned finish. Nothing depends on OPS-02 before week 13.5 (BRD-03 soft; OPS-04 and OPS-05 hard from week 21), the merges are the rotating merge owner's work, and a failed merge is RK-02. Nothing is left to decide. | 0 | 1 | 1 |  |
| RES-166 | fixed | OPS-02 | coral-compat.yml replaces editing server-compat.yml's path filter (no seam covers it); the spec already decides this. | 0 | 1 | 0 |  |
| RES-167 | assign | OPS-04 | OPS-04 loads the Coral plugin through a BenchEnvironment subclass that overrides _spawn_server (no upstream edit); an upstream extra_server_config parameter is optional through OPS-05. | 1 | 3 | 0 |  |
| RES-168 | assign | OPS-01, OPS-04 | OPS-01 adds dev/loadtest/coral/ to the fork guard's allowed roots as a new-files-only root. | 1 | 2 | 0 |  |
| RES-169 | assign | OPS-05 | OPS-05 finishes at week 23 but co-owns IM-8 at week 25.5, so it re-runs the drill (one day) in week 25 to keep the evidence current. | 1 | 2 | 0 |  |
| RES-170 | residual | OPS-06 | OPS-06 (weeks 4-6) precedes GTE-01, PRF-01, API-02 and GTE-06; it adds a second pass at IM-3 (week 11.5) and sign-offs near weeks 13.5 and 18, about 0.5 week of WS-OPS tail. | 1 | 2 | 1 | OPS-06 (OPS lead); IM-3 (week 11.5), then weeks 13.5 and 18 |
| RES-171 | residual | OPS-02 | OPS-02's "Dependabot off for upstream manifests" has no verified mechanism: editing .github/dependabot.yml is an unledgered upstream edit, and repository settings alone are unverified. | 0 | 0 | 1 | OPS-02; Week 4 |
| RES-172 | residual | OPS-07, SPK-05 | A one-week soak gives seven nightlies against a 9-of-10 threshold. The soak counts the last ten credentialed runs, including on-demand runs from IM-2, which needs the OQ-51 bench budget. | 0 | 1 | 1 | OPS-07 with Ops (OQ-51); Week 9.5 (OQ-51 deadline) |
| RES-173 | residual | OPS-07 | IM-3 and IM-4 are dated week 11.5, OPS-07's own start, so its lane build-out runs from about week 9.5 in OPS-T2 free time; no feature represents that work. | 0 | 1 | 1 | OPS lead (OPS-T2); Week 9.5 |
| RES-174 | fixed | OPS-07 | OPS-07 keeps latency asserts in the nightly (shared-runner budgets in tests/budgets.py), and its engine-upgrade old-build variant adds a coral-e2e.yml input; both are in the spec. | 0 | 1 | 0 |  |
| RES-175 | assign | OPS-08, SPK-05 | OPS-08 checks that SPK-05's OQ-28 and OQ-35 records exist (SPK-05 owns them); M4 structure work is ENG-08 and SES-10 code and OPS-09's journey. | 2 | 1 | 0 |  |
| RES-176 | residual | OPS-08, HRN-07 | OPS-08 starts the day HRN-07 finishes (week 20), so there is no slack before M3; subscription auth cannot be shown in CI, so M3 exit 8 on subscription auth is proven in dogfood. | 0 | 1 | 1 | OPS-08 (OPS lead); Week 20 |
| RES-177 | contract | OPS-09 | OPS-09 lists OQ-29, which decides its reviewer variant. | 1 | 2 | 0 |  |
| RES-178 | residual | OPS-09, WEB-09, BRD-03 | OPS-09 starts the day WEB-09 finishes (week 24.5); the coral:// step has no CI Electron lane and is proven in dogfood on a packaged build. | 0 | 1 | 1 | OPS-09 (OPS lead); Week 24.5 |
| RES-179 | residual | TLS-01, OPS-06, GTE-03 | The CLI server always builds a permission store (cli.py:4912), so multi_user is always true and the single-user early return in _require_cost_control_label_authority never fires. The S49 predicate, the OQ-43 default and GTE-03's loopback-http rule need an explicit single-user definition from TLS-01. | 0 | 0 | 1 | TLS-01 with OPS-06; Week 3 (TLS-01's S49 PR) |
| RES-180 | nongoal | EXT-03, WEB-03 | Web git import and listing imported templates in WEB-03's gallery are non-goals; EXT-03 imports through the CLI and API only. | 1 | 2 | 0 |  |
| RES-181 | citation | EXT-03 | EXT-03's proving-test path .coral/<id>.yaml resolves to .coral/workflows/<key>.yaml (D§12 and WSP-01's import). | 1 | 2 | 0 |  |
| RES-182 | assign | EXT-05, BRD-02 | EXT-05 owns two new seam rows: S90, an upstream-first fire.py hook, and S84b, the TasksPage.tsx 'Run workflow' action, which joins the §6.5 order after BRD-02's S84 (soft edge EXT-05 -> BRD-02). | 6 | 7 | 2 |  |
| RES-183 | edge | EXT-01, DUR-02, API-02, WSP-06 | EXT-01 gets a hard edge to DUR-02 (accepting a suggestion writes a version through DUR-02's store; DUR-02 PH1/M1 ends week 9.5, long before week 26.5), a soft edge to API-02 (spend for cost_growth) and K7. cost_growth reads spend only for runs DUR-06 has not purged. test_edit_in_non_test_step reads changed paths from the diff_stat WSP-06 stores on each handoff (git diff --numstat -z, one row per path). | 4 | 8 | 0 |  |
| RES-184 | edge | EXT-02, TLS-02, ENG-03 | EXT-02 consumes K6 and gets soft edges to TLS-02 (rejection path) and ENG-03 (reserved-key checks). | 3 | 6 | 0 |  |
| RES-185 | contract | EXT-03 | EXT-03's export and import endpoints extend K7, so EXT-03 consumes K7. | 1 | 2 | 0 |  |
| RES-186 | edge | EXT-04, GTE-06, API-02 | EXT-04 consumes K19 and K7 and gets soft edges to GTE-06 (per-recipient alerts) and API-02 (authority changes). | 4 | 7 | 0 |  |
| RES-187 | fixed | EXT-04 | EXT-04's S53 analysis (which paths already refuse coral__ rows) is a verified fact; it becomes plain technical-scope text. | 0 | 1 | 0 |  |
| RES-188 | assign | EXT-01, EXT-03, EXT-04, EXT-05 | Master §11 gains UI-surface rows for EXT-01 (Suggestions tab), EXT-03 (Export dialog), EXT-04 (Share dialog) and EXT-05 (Run-workflow action), each owned by its feature with WEB-lead review. EXT-03, EXT-04 and EXT-05 gain a 0.5-week WS-WEB secondary load (EXT-01 already has 1 week); post-M4 WEB tracks are free after WEB-09 (24.5) apart from GTE-04. | 7 | 0 | 0 |  |
| RES-189 | split | ENG-04, SES-04, DUR-03, ENG-06, DUR-05, GTE-01, SES-06, TLS-03, PRF-01, RUL-01, RUL-03, RUL-06, HRN-03, HRN-05, RUL-05, WEB-09, API-01, OPS-04, DUR-04, HRN-09 | Master wording for splits the specs already agree on: ENG-04 owns the post_close_activity transition and SES-04 detects it; ENG-06 owns the start_key rule and DUR-03 enforces it as a key; DUR-05 triggers gate re-publish and GTE-01 executes it; DUR-05 marks slots suspect and SES-06 runs the ladder; TLS-03 owns the orchestrator allowlist constant, PRF-01 places orchestrator_guard in guardrails and RUL-01 owns the policy code; RUL-03 calls RUL-06's V9; HRN-03 and HRN-05 set fail_closed in native step bundles; RUL-05 owns step-budget data and WEB-09 the fields; API-01 owns the client.ts wrapper; OPS-04 reuses DUR-04's lease fixtures; HRN-03 and HRN-09 own their rows in PRF-01's bundle generator. | 12 | 12 | 0 |  |
| RES-190 | citation |  | Record that the spec reviewer notes and open verifier items are resolved in master v3 (decisions_log.json), and create section J.6 for residual items. | 1 | 0 | 3 |  |
| RES-191 | assign | SPK-01 | The tech lead (IM-0 owner) owns the M1 exit gate and checks master §3's M1 exit criteria against IM-0 and IM-1 evidence and the M1 features' proving tests; M1 has no separate acceptance lane. | 1 | 0 | 1 |  |
| RES-192 | residual | HRN-03, WEB-08 | The early-start levers (HRN-03 at week 11, WEB-08 at M2) change decision 23's windows and need tech-lead sign-off; not adopted in v3. | 0 | 0 | 1 | Tech lead; Before week 11 |
| RES-193 | residual | GTE-03, DUR-06 | At M2 one platform engineer cannot run GTE-03 and DUR-06 in the same weeks (13.5-15.5); DUR-06 can move to 15.5-17.5 on its float. No schedule change here. | 0 | 0 | 1 | PLATFORM lead; Week 13.5 |
| RES-194 | residual | RUL-03, WSP-02, RUL-06, EVD-04 | K15 (RUL-03) and K20 (WSP-02) ship the week their first consumers start; the plan drafts them early in free time (INT-T4 weeks 11-13.5; WSP-T1 weeks 9-13.5). | 0 | 0 | 1 | INTEGRATION and WORKSPACE leads; Week 13.5 |
| RES-195 | residual | SPK-03, FND-04 | The spike-4 fallback (test-only openai-agents Tier B) is not costed; one extra FND-04 week moves levelled M2 by two weeks. | 0 | 0 | 1 | SPK-03 (tech lead); Week 1 (SPK-03 memo) |
| RES-196 | residual | WEB-11, WEB-06, WEB-08 | WEB-11 (cut rank 2) is a hard input of WEB-06 and WEB-08; if cut at M2 it must still land by week 15.5 or M4 slips one-for-one. | 0 | 0 | 1 | WEB lead; Week 15.5 |
| RES-197 | residual | SES-03, SES-09, SES-05, TLS-05 | SES-03 > SES-09 > SES-05 has zero float, so the ADR-05 topology fallback (+3-4 weeks) moves M2 one-for-one; cutting TLS-05 frees INT-T4 for SES-05. | 0 | 0 | 1 | INTEGRATION lead; Day 4 of week 1 (ADR-05) |
| RES-198 | residual | SES-07, BRD-03, OPS-07, HRN-08 | OQ-11 (take-over details), OQ-31 (desktop app id and DCO; OPS-05's spec defaults the update feed to GitHub release assets, and store listings and mobile bundle ids are a non-goal through M4, RES-161) and OQ-51 (bench budget) have no default in the sources; J gives a proposal for OQ-11 only. | 0 | 0 | 1 | PM (OQ-11), Legal and Ops (OQ-31), Ops (OQ-51); OQ-51 week 9.5; OQ-11 and OQ-31 week 13.5 |
| RES-199 | citation | BRD-02 | CoralPageHeader lives at web/src/brand/CoralPageHeader.tsx (BRD-02), not UI§10's web/src/components/concerto/; a Draft 5 correction. | 0 | 0 | 1 |  |
| RES-200 | split | SPK-01, OPS-06 | OQ-43: SPK-01 records the week-1 default (accept single-user calls, provenance 'user'), which K6 and TLS-01's S49 PR (week 3) build on; OPS-06 records the security verdict in week 6 and may tighten it. Default, then verdict. | 1 | 1 | 0 |  |
| RES-201 | contract | SES-01, GTE-01 | K14's "hidden decline and cancel" conflicts with the unchanged ApprovalCard, whose Reject button sends decline. K14 now says decline maps only to an authored reject label and cancel is refused. Section J's OQ-3 default changes to match. | 1 | 0 | 1 |  |
| RES-202 | fixed |  | Boundary splits the verifiers fixed locally that already agree with the master (no action): SPK-02/SES-03 anchor DENY wording, SPK-04 spike 9 owner, S71 repro handoff, FND-01 allowlist mechanism vs FND-03 entries, ENG-06/SES-06 retry ladder, ENG-04/TLS-02 evaluating lease, DUR-03/DUR-05 commit-boundary tests, SES-06 recovery kinds, SES-08 alert producer, TLS-01/FND-02 token, TLS-03/ENG-04 decision requests, GTE-03 links, GTE-02/WEB-05 step chip, EVD-02 submit wait, API-02 amendments, WEB-03 excluded owners, WEB-05 chip, OPS-08 E2E-4 path, OPS-09 desktop row, EXT-01/EXT-02/EXT-04 wording fixes. | 0 | 0 | 0 |  |

## Residual open items (for section J.6)

| RES | Item | Owner | Deadline | Blocking impact |
|---|---|---|---|---|
| RES-030 | The 30-minute watchdog default (OQ-14) and DUR-05's 3x-resync rule have no source. They stay labelled as proposals until SPK-05 records OQ-14. | SPK-05 (PM) | Week 4 (TLS-03 starts week 5.5) | ENG-06, DUR-05 and TLS-03 defaults; the watchdog p95 from OPS-07 re-checks it. |
| RES-049 | DUR-03 step 3 needs DUR-04's first PR (coral_0002_queue) inside DUR-03's window. No edge can be added (DUR-04 already soft-depends on DUR-03, so the reverse edge forms a cycle). DUR-03 builds step 3 on K5's queue layout and the fake until coral_0002 lands. | PLATFORM lead (DUR-04) | Week 6 (coral_0002_queue merged) | DUR-03's week-7 finish slips one-for-one if coral_0002 lands after week 6. |
| RES-053 | Add soft edge SES-04 -> DUR-01 (K5, K21 and coral_0001 for stable_ids). The session_bindings migration prerequisite becomes "ADR-05; coral_0001". coral_0001 must merge by week 4 so SES-03 and SES-04 can land their migrations; a hard edge would warn (DUR-01 ends week 5). | DUR-01 (PLATFORM lead) | Week 4 (coral_0001_core merged) | SES-03's session_bindings and SES-04's stable_ids migrations cannot merge on the single-head train before coral_0001; SES-04 (ends week 5) slips one-for-one. |
| RES-058 | SES-04 closes its feature proof on Tier A (K13 fake, injected SubmitHandoff) at week 5; the Tier B queued-input variant runs as its IM-2 exit item. Add soft edge SES-04 -> FND-04. Until SES-08 lands, SES-04 detects post-close turns through a narrow observer in SES-02's registry. | SES-04 (INTEGRATION lead) | IM-2, week 11.5 | The Tier B queued-input proof (M2 exit 7) is shown only at IM-2. |
| RES-063 | SES-06 and SES-09 finish at week 9.5 but their proving tests need DUR-05 and SES-08 (ending 11.5 and 11), so they close at IM-3 (week 11.5). No schedule change. | SES-06 and SES-09 (INTEGRATION lead) | IM-3, week 11.5 | Feature exits are recorded at IM-3; a slip in DUR-05 or SES-08 delays both exits. |
| RES-064 | SES-10 exits at week 16 with E2E-5 on WSP-03 and WSP-07 fakes. INT-T2, its track, has no other work after week 16 (H.1), so the same engineer carries the IM-7 convergence tail to week 22.5: E2E-5 is re-run against RUL-03's templates (week 18), WSP-07's push (20) and WSP-03's merges (22.5). No split and no new staffing; the IM-7 date stays a tracked risk. | INTEGRATION lead (SES-10) | IM-7, week 22.5 | E2E-5 runs on real merges and push only at IM-7; a WSP-03 or WSP-07 slip delays IM-7 and the M4 journey. |
| RES-082 | GTE-04 owns desktop delivery through an inbox watcher loaded from web/electron/src/main.js under new seam row S87b, landed after BRD-03's S87. CI covers only the push-service HTTP boundary. Electron Web Push availability is unverified. | GTE-04 | Week 26.5 (GTE-04 start) | If Electron has no Web Push service, desktop delivery relies only on the main-process watcher, which needs credentials. |
| RES-089 | Add soft edge EVD-02 -> WSP-06 (session-shell fingerprint). EVD-02's proof needs TLS-02 and WSP-06, so it closes on Tier A at week 7 and its Tier B run is at IM-3 (week 11.5). TLS-02 cannot be an edge (TLS-02 soft-depends on EVD-02). | EVD-02 (WS-WORKSPACE lead) | IM-3, week 11.5 | The handoff evidence proof is green only at IM-3; a TLS-02 or WSP-06 slip delays it. |
| RES-100 | An Enforced protect_paths on claude-sdk needs compiled sibling write grants (UNVERIFIED on seatbelt) or an unplanned sandbox seam, because write_paths is an allowlist and shell writes bypass a write-tool DENY. | RUL-03 (WS-HARNESS lead) | Week 15.5 (RUL-03 mid-window) | If sibling grants fail on seatbelt, protect_paths is labelled Verified, not Enforced, on claude-sdk, and RUL-03's proof uses the write-tool DENY only. |
| RES-124 | OPS-04's security closure covers HRN-06's S20 runner policy relay as a new security surface. HRN-06 may be larger than M (ENG-29); that stays a residual risk. Add soft edge OPS-04 -> HRN-06 (HRN-06 ends week 23, inside OPS-04's weeks 21-25.5). | HRN-06 (HARNESS lead) | Week 21 (HRN-06 start) | If S20 is larger than M, HRN-06 and HRN-09 slip; HRN-09 is the first M4 cut. |
| RES-135 | K13 v1 text freezes at IM-0 (week 3, M1 exit 7) from SPK-04's draft, signed by the WORKSPACE lead; WSP-01's first PR (week 5) lands it as code without changing it. EVD-01 (weeks 3-5) builds on the frozen text and the fake. | WORKSPACE lead (SPK-04, WSP-01) | IM-0, week 3 | If K13 text is not frozen at IM-0, EVD-01 (weeks 3-5) builds on an unstable interface and M1 exit 7 fails. |
| RES-149 | If SPK-02 probe (e) fails, SES-03 uses RUL-01's DENY instead of omnigent.closed; the upstream anchor composer stays enabled and only the S86 banner explains. | SPK-02 (probe e) with SES-03 | Week 2 | If (e) fails, users can type into the anchor; RUL-01 denies the tools and WEB-05's banner is the only explanation. |
| RES-162 | _default_runner_id_path (runner/identity.py:239-244), admin_list.py:73 and codex_native/app_server.py:1863 ignore OMNIGENT_DATA_DIR. OPS-03's isolation test covers them; any fix is a generic upstream-only PR through OPS-05, not a fork seam. S75 enables no update channel, so _CACHE_DIR needs no fork change. | OPS-03 | Week 6 (OPS-03 finish) | If coral can reach a writer that ignores OMNIGENT_DATA_DIR, the isolation test fails until OPS-05's upstream PR merges; coral sets OMNIGENT_RUNNER_ID as a stopgap. |
| RES-170 | OPS-06 (weeks 4-6) precedes GTE-01, PRF-01, API-02 and GTE-06; it adds a second pass at IM-3 (week 11.5) and sign-offs near weeks 13.5 and 18, about 0.5 week of WS-OPS tail. | OPS-06 (OPS lead) | IM-3 (week 11.5), then weeks 13.5 and 18 | About 0.5 week of unplanned WS-OPS load; M2 exit 14 depends on the IM-3 pass. |
| RES-171 | OPS-02's "Dependabot off for upstream manifests" has no verified mechanism: editing .github/dependabot.yml is an unledgered upstream edit, and repository settings alone are unverified. | OPS-02 | Week 4 | Dependabot PRs against upstream manifests would add merge noise. |
| RES-172 | A one-week soak gives seven nightlies against a 9-of-10 threshold. The soak counts the last ten credentialed runs, including on-demand runs from IM-2, which needs the OQ-51 bench budget. | OPS-07 with Ops (OQ-51) | Week 9.5 (OQ-51 deadline) | Without budget for on-demand runs, M2 exit 2 cannot reach ten runs in the soak week. |
| RES-173 | IM-3 and IM-4 are dated week 11.5, OPS-07's own start, so its lane build-out runs from about week 9.5 in OPS-T2 free time; no feature represents that work. | OPS lead (OPS-T2) | Week 9.5 | IM-3 and IM-4 slip if the lanes are not ready by week 11.5. |
| RES-176 | OPS-08 starts the day HRN-07 finishes (week 20), so there is no slack before M3; subscription auth cannot be shown in CI, so M3 exit 8 on subscription auth is proven in dogfood. | OPS-08 (OPS lead) | Week 20 | Any HRN-07 slip moves M3; M3 exit 8 rests on a dogfood run. |
| RES-178 | OPS-09 starts the day WEB-09 finishes (week 24.5); the coral:// step has no CI Electron lane and is proven in dogfood on a packaged build. | OPS-09 (OPS lead) | Week 24.5 | A WEB-09 slip moves M4; the deep-link step is dogfood-only. |
| RES-179 | The CLI server always builds a permission store (cli.py:4912), so multi_user is always true and the single-user early return in _require_cost_control_label_authority never fires. The S49 predicate, the OQ-43 default and GTE-03's loopback-http rule need an explicit single-user definition from TLS-01. | TLS-01 with OPS-06 | Week 3 (TLS-01's S49 PR) | OQ-43's "accept on single-user servers" never applies; the M4 webhook test may need an https receiver. |
| RES-192 | The early-start levers (HRN-03 at week 11, WEB-08 at M2) change decision 23's windows and need tech-lead sign-off; not adopted in v3. | Tech lead | Before week 11 | Without sign-off M3 stays at levelled week 21 and the WEB chain binds M4. |
| RES-193 | At M2 one platform engineer cannot run GTE-03 and DUR-06 in the same weeks (13.5-15.5); DUR-06 can move to 15.5-17.5 on its float. No schedule change here. | PLATFORM lead | Week 13.5 | One of GTE-03 or DUR-06 slips two weeks if only one engineer stays. |
| RES-194 | K15 (RUL-03) and K20 (WSP-02) ship the week their first consumers start; the plan drafts them early in free time (INT-T4 weeks 11-13.5; WSP-T1 weeks 9-13.5). | INTEGRATION and WORKSPACE leads | Week 13.5 | RUL-06 and EVD-04 start against drafts if the early drafting does not happen. |
| RES-195 | The spike-4 fallback (test-only openai-agents Tier B) is not costed; one extra FND-04 week moves levelled M2 by two weeks. | SPK-03 (tech lead) | Week 1 (SPK-03 memo) | An uncosted fallback can move M2 by two weeks. |
| RES-196 | WEB-11 (cut rank 2) is a hard input of WEB-06 and WEB-08; if cut at M2 it must still land by week 15.5 or M4 slips one-for-one. | WEB lead | Week 15.5 | M4 slips one-for-one if a cut WEB-11 lands later. |
| RES-197 | SES-03 > SES-09 > SES-05 has zero float, so the ADR-05 topology fallback (+3-4 weeks) moves M2 one-for-one; cutting TLS-05 frees INT-T4 for SES-05. | INTEGRATION lead | Day 4 of week 1 (ADR-05) | A topology fallback moves M2 by 3-4 weeks unless cut rank 1 is applied. |
| RES-198 | OQ-11 (take-over details), OQ-31 (desktop app id and DCO; OPS-05's spec defaults the update feed to GitHub release assets, and store listings and mobile bundle ids are a non-goal through M4, RES-161) and OQ-51 (bench budget) have no default in the sources; J gives a proposal for OQ-11 only. | PM (OQ-11), Legal and Ops (OQ-31), Ops (OQ-51) | OQ-51 week 9.5; OQ-11 and OQ-31 week 13.5 | SES-07 take-over semantics, BRD-03's desktop app id and the credentialed soak. |

## Details

### RES-001 · assign · SPK-05, DUR-06, HRN-05

SPK-05 owns the OQ-25 (retention) and OQ-29 (Codex terms) decision records: the OQ-25 default by week 4 (SPK-05's own deadline for Coral-controlled questions), signed by week 13.5; the external OQ-29 answer by week 13.5. DUR-06 and HRN-05/06/09 only implement the recorded outcome.

Changed by the challenge pass: CH-03, CH-28.

Master edits:
- SPK-05.open_questions += OQ-25
- SPK-05.open_questions += OQ-29
- SPK-05.included += "Records for OQ-25 (retention, incl. Omnigent sessions and transcripts of runs; default by week 4 from the J.3.1 proposal, signed by week 13.5, the start of PH4) and OQ-29 (Codex terms, an external answer SPK-05 chases, by week 13.5)"
- SPK-05.excluded: "Codex terms OQ-29 (decided before PH4 starts; blocks HRN-05)" -> "Implementing the OQ-29 outcome (HRN-05, HRN-06, HRN-09)"
- SPK-05.excluded: "Retention OQ-25 (decided before PH4 starts; blocks DUR-06)" -> "Implementing the OQ-25 retention policy (DUR-06)"

Spec edits:
- SPK-05: Add OQ-25 to the open questions this spec records or cites (**Risks and open questions.**; RES-001).
- SPK-05: Add OQ-29 to the open questions this spec records or cites (**Risks and open questions.**; RES-001).
- SPK-05: **Ownership boundaries.** Included: add "Records for OQ-25 (retention, incl. Omnigent sessions and transcripts of runs; default by week 4 from the J.3.1 proposal, signed by week 13.5, the start of PH4) and OQ-29 (Codex terms, an external answer SPK-05 chases, by week 13.5)" (RES-001).
- SPK-05: In **Ownership boundaries.** Excluded, replace "Codex terms OQ-29 (before PH4; blocks HRN-05); retention OQ-25 (before PH4; blocks DUR-06)" with "implementing the OQ-29 outcome (HRN-05, HRN-06, HRN-09); implementing the OQ-25 retention policy (DUR-06)". In the records table, add OQ-25 (default by week 4 from J.3.1's proposal, signed by week 13.5; consumer DUR-06) and OQ-29 (external answer by week 13.5; consumers HRN-05, HRN-06, HRN-09). (RES-001)
- DUR-06: In **Risks and open questions.**, change the OQ-25 bullet to say the decision record is SPK-05's (due week 13.5) and DUR-06 implements it. (RES-001)
- SPK-05: In spk.md, delete the bullet `` - Reviewer note: no feature's included list owns deciding OQ-29 or OQ-25 (due week 13.5); HRN-05's and DUR-06's first PRs should add them. `` (resolved by RES-001).

Section edits:
- J: J.3.1 OQ-25 row: set Owner to "PM (record: SPK-05)" and replace the deadline "Before PH4 (DUR-06, week 13.5)" with "Default by week 4 (SPK-05, from this row's proposal); signed by week 13.5, before DUR-06". J.3.2 OQ-29 row: set Owner to "Legal (record: SPK-05)". (RES-001)

### RES-002 · split · DUR-04, SES-08, OPS-07, SPK-05

SQLite perf smoke: DUR-04 owns the one harness (tests/stores/coral/test_sqlite_perf_smoke.py) and its shared helpers; SES-08 adds the edge-to-TurnFact lag case to it; OPS-07 runs it as the M2 gate and keeps a separate e2e case (five concurrent template runs and the watchdog p95, a real-server boundary) that reuses DUR-04's helpers; SPK-05 records the budgets.

Changed by the challenge pass: CH-11.

Master edits:
- DUR-04.included: "SQLite perf smoke: five concurrent mock runs record SQLITE_BUSY counts and p95 transition latency against the SPK-05 budget" -> "SQLite perf-smoke harness (tests/stores/coral/test_sqlite_perf_smoke.py; its budget reader, SQLITE_BUSY counter and p95 recorder are shared helpers): five concurrent mock runs record SQLITE_BUSY counts and p95 transition latency against the SPK-05 budget; SES-08 adds a case to it and OPS-07's e2e case reuses its helpers, so neither forks it"
- SES-08.included: "SQLite perf smoke for edge-to-TurnFact lag against the SPK-05 budget" -> "Edge-to-TurnFact lag case added to DUR-04's perf-smoke harness, against the SPK-05 budget"
- OPS-07.included: "SQLite perf smoke with five concurrent runs against the SPK-05 budgets" -> "Runs DUR-04's perf-smoke harness as an M2 gate; its five-concurrent-template-run case and the watchdog p95 live in tests/e2e/coral/test_perf_smoke.py and reuse DUR-04's helpers (no second harness)"
- failure_modes[Stale read, version conflict, SQLITE_BUSY].owner: "DUR-03 reduce-and-retry; DUR-04 and SES-08 perf smoke" -> "DUR-03 reduce-and-retry; DUR-04's perf-smoke harness (SES-08 adds the lag case, OPS-07 gates M2 on it)"

Spec edits:
- DUR-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "SQLite perf smoke: five concurrent mock runs record SQLITE_BUSY counts and p95 transition latency against the SPK-05 budget" so it says "SQLite perf-smoke harness (tests/stores/coral/test_sqlite_perf_smoke.py; its budget reader, SQLITE_BUSY counter and p95 recorder are shared helpers): five concurrent mock runs record SQLITE_BUSY counts and p95 transition latency against the SPK-05 budget; SES-08 adds a case to it and OPS-07's e2e case reuses its helpers, so neither forks it". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-002).
- SES-08: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "SQLite perf smoke for edge-to-TurnFact lag against the SPK-05 budget" so it says "Edge-to-TurnFact lag case added to DUR-04's perf-smoke harness, against the SPK-05 budget". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-002).
- OPS-07: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "SQLite perf smoke with five concurrent runs against the SPK-05 budgets" so it says "Runs DUR-04's perf-smoke harness as an M2 gate; its five-concurrent-template-run case and the watchdog p95 live in tests/e2e/coral/test_perf_smoke.py and reuse DUR-04's helpers (no second harness)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-002).
- DUR-04: Tests: name tests/stores/coral/test_sqlite_perf_smoke.py as the single perf-smoke harness and expose its budget reader, SQLITE_BUSY counter and p95 recorder as shared helpers for SES-08's case and OPS-07's e2e case. (RES-002)
- SES-08: Ownership boundaries, Included: replace "the Tier B case and the lag smoke" with "the Tier B case and the lag case in DUR-04's perf-smoke harness". (RES-002)
- OPS-07: Implementation breakdown step 6: replace "run DUR-04's smoke; add five concurrent template runs" with "run DUR-04's smoke; the e2e case (tests/e2e/coral/test_perf_smoke.py, five concurrent template runs) reuses DUR-04's harness helpers and adds"; keep test_perf_smoke in the New list for that case only. (RES-002)
- SPK-05: Ownership boundaries, Excluded: replace "perf smoke runs (DUR-04, SES-08)" with "perf smoke runs (DUR-04's harness; SES-08's lag case; OPS-07's M2 gate)". (RES-002)
- SES-08: In ses-b.md, delete the bullet `` - Reviewer note: OPS-07's fault journey also lists 529/429/401, and DUR-04 and OPS-07 also list a perf smoke; OPS-07 should reuse this case. `` (resolved by RES-002).

### RES-003 · edge · DUR-04, SES-08, OPS-07, SPK-05

Add soft edges DUR-04, SES-08 and OPS-07 -> SPK-05: they read the SPK-05 perf-smoke and soak budgets.

Master edits:
- DUR-04.soft_deps += SPK-05 (perf-smoke budgets)
- SES-08.soft_deps += SPK-05 (lag budget)
- OPS-07.soft_deps += SPK-05 (soak threshold and perf-smoke budgets)

Spec edits:
- DUR-04: **Dependencies.** Add SPK-05 to the "Soft:" line (perf-smoke budgets; RES-003).
- SPK-05: **Dependencies.** Add DUR-04 to the soft part of "Downstream, unblocks:" (RES-003).
- SES-08: **Dependencies.** Add SPK-05 to the "Soft:" line (lag budget; RES-003).
- SPK-05: **Dependencies.** Add SES-08 to the soft part of "Downstream, unblocks:" (RES-003).
- OPS-07: **Dependencies.** Add SPK-05 to the "Soft:" line (soak threshold and perf-smoke budgets; RES-003).
- SPK-05: **Dependencies.** Add OPS-07 to the soft part of "Downstream, unblocks:" (RES-003).
- SPK-05: In spk.md, delete the bullet `` - Reviewer note: DUR-04, SES-08 and OPS-07 use these budgets with no edge to SPK-05; add soft edges. `` (resolved by RES-003).

### RES-004 · split · SES-08, OPS-07

The 529/429/401 Tier B case is SES-08's; OPS-07's M2 fault journey re-runs it from SES-08's QueuedResponse setup instead of writing its own.

Master edits:
- OPS-07.included: "retry, 529/429/401, input queued" -> "retry, the 529/429/401 case reused from SES-08's Tier B setup, input queued"
- failure_modes[Unclassified 529, 429 or 401].proof: "SES-08 Tier B 529/429/401 case" -> "SES-08 Tier B 529/429/401 case (re-run in OPS-07's fault journey)"

Spec edits:
- OPS-07: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "retry, 529/429/401, input queued" so it says "retry, the 529/429/401 case reused from SES-08's Tier B setup, input queued". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-004).

### RES-005 · assign · SPK-05, RUL-01, HRN-02

SPK-05 signs or defaults the records that week-3 starters consume (OQ-15 for RUL-01; OQ-28 default and OQ-35 for HRN-02) by week 2; the rest by week 4.

Master edits:
- SPK-05.included += "Records consumed by week-3 starters (OQ-15 for RUL-01; the OQ-28 default and OQ-35 for HRN-02) are signed or defaulted by week 2; the rest by week 4"

Spec edits:
- SPK-05: **Ownership boundaries.** Included: add "Records consumed by week-3 starters (OQ-15 for RUL-01; the OQ-28 default and OQ-35 for HRN-02) are signed or defaulted by week 2; the rest by week 4" (RES-005).
- SPK-05: Implementation breakdown: add a step "Week 2: sign or default OQ-15, the OQ-28 default and OQ-35 (consumed by RUL-01 and HRN-02 from week 3)". (RES-005)
- SPK-05: In spk.md, delete the bullet `` - Reviewer note: proving test week 4 vs planned finish week 2; RUL-01 and HRN-02 start in week 3, so their records are due by week 2. `` (resolved by RES-005).

### RES-006 · assign · SPK-05, DUR-02, ENG-03, WEB-02

OQ-9 (saving invalid drafts; where saved tests run) gets a record in SPK-05 by week 2 with the default "draft save allowed, run blocked; saved cases run in the app and in CI".

Master edits:
- SPK-05.open_questions += OQ-9
- SPK-05.included += "OQ-9 record by week 2 (before DUR-02 starts): invalid drafts can be saved but not run; saved cases run in the app and in CI"

Spec edits:
- SPK-05: Add OQ-9 to the open questions this spec records or cites (**Risks and open questions.**; RES-006).
- SPK-05: **Ownership boundaries.** Included: add "OQ-9 record by week 2 (before DUR-02 starts): invalid drafts can be saved but not run; saved cases run in the app and in CI" (RES-006).
- SPK-05: Add an OQ-9 row to the records table: default "draft save allowed, run blocked; saved cases run in the app and in CI", due week 2, consumers DUR-02, ENG-03, ENG-07, WEB-02, WEB-11, WEB-12. (RES-006)
- ENG-03: In eng-a.md, delete the bullet `` - Reviewer note: OQ-9 is on neither SPK-01's nor SPK-05's list; ENG-03 and DUR-02 assume the default. `` (resolved by RES-006).
- SPK-05: In spk.md, delete the bullet `` - Reviewer note: OQ-9 (invalid drafts) shapes DUR-02 and WEB-02 from week 5 with no record; add it here, default "draft save allowed, run blocked". `` (resolved by RES-006).

Section edits:
- J: J.3.1 OQ-9 row: replace "**No record yet; add it to SPK-05.**" with "Recorded by SPK-05 by week 2." and set the deadline to "Week 2 (before DUR-02, week 5)". (RES-006)

### RES-007 · assign · SPK-01, SES-01

SPK-01 records OQ-37 (profile metadata: params.coral, X-12) and OQ-47 (coral.omni coupling: in-process facade, X-8) in week 1, because they shape K4 and K12 at IM-0.

Master edits:
- SPK-01.open_questions += OQ-37
- SPK-01.open_questions += OQ-47
- SPK-01.included += "Contract-shaping architecture defaults for IM-0: profile metadata in params.coral plus a revisions table (OQ-37, X-12); coral.omni as an in-process facade with contract tests (OQ-47, X-8)"

Spec edits:
- SPK-01: Add OQ-37 to the open questions this spec records or cites (**Risks and open questions.**; RES-007).
- SPK-01: Add OQ-47 to the open questions this spec records or cites (**Risks and open questions.**; RES-007).
- SPK-01: **Ownership boundaries.** Included: add "Contract-shaping architecture defaults for IM-0: profile metadata in params.coral plus a revisions table (OQ-37, X-12); coral.omni as an in-process facade with contract tests (OQ-47, X-8)" (RES-007).
- SPK-01: Add OQ-37 and OQ-47 rows to the week-1 records table with the defaults "params.coral plus a revisions table (X-12)" and "in-process facade with contract tests (X-8)". (RES-007)
- SPK-01: In spk.md, delete the bullet `` - Reviewer note: OQ-37 and OQ-47 shape K4 and K12 at IM-0 but only SES-01 lists them; SPK-01 should record defaults (params.coral, X-12; in-process facade, X-8). `` (resolved by RES-007).

Section edits:
- J: J.3.3 OQ-37 and OQ-47 rows: replace "IM-0. SPK-01 should record it (reviewer note)." / "IM-0; SPK-01 should record it" with "Week 1 (SPK-01 record; IM-0 consumes it)". (RES-007)

### RES-008 · citation · SPK-02

SPK-02 probes (e), (f), 14 and 15 run to week 2 while its planned window is weeks 0-1. No downstream start moves and nothing is left to decide; H.3 shows the tail.

Changed by the challenge pass: CH-12.

Spec edits:
- SPK-02: In spk.md, replace the bullet `` - Reviewer note: the JSON window is weeks 0-1, but (e), (f), 14 and 15 run to week 2 (DEL-24); the schedule should show that tail. No downstream start moves. `` with `` - Probes (e), (f), 14 and 15 run to week 2 (DEL-24), a tail past the planned weeks 0-1; no downstream start moves (H.3). `` (no longer a reviewer note; settled by RES-008).

Section edits:
- H: H.3 track table, INTEGRATION INT-T1 row: replace "ADR-05 by end of week 1; probes (e) and (f) by week 2" with "ADR-05 by end of week 1; probes (e), (f), 14 and 15 by week 2 (a tail past SPK-02's planned weeks 0-1; no downstream start moves)". (RES-008)

### RES-009 · assign · SPK-03, HRN-08

SPK-03 probe prototypes stay on the spike branch and in docs/coral/decisions/probes/; HRN-08 ports them into upstream tests/harness_bench/probes/ under a ledgered S23 entry.

Master edits:
- SPK-03.included: "Verdict memo with a probe script per spike" -> "Verdict memo with a probe script per spike; prototypes stay on the spike branch and in docs/coral/decisions/probes/, never in upstream tests/harness_bench/probes/"
- SPK-03.excluded: "Bench code (HRN-08)" -> "Bench code and porting the probes into tests/harness_bench/probes/ under a ledgered S23 entry (HRN-08)"

Spec edits:
- SPK-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Verdict memo with a probe script per spike" so it says "Verdict memo with a probe script per spike; prototypes stay on the spike branch and in docs/coral/decisions/probes/, never in upstream tests/harness_bench/probes/". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-009).
- SPK-03: **Ownership boundaries.** Excluded: reword the item covering "Bench code (HRN-08)" so it says "Bench code and porting the probes into tests/harness_bench/probes/ under a ledgered S23 entry (HRN-08)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-009).
- SPK-03: In spk.md, delete the bullet `` - Reviewer note: `tests/harness_bench/probes/` is upstream code (`ALL_PROBES`, `__init__.py:20`); landing files there needs a ledger entry. Keep prototypes on the spike branch for HRN-08 to port. `` (resolved by RES-009).

### RES-010 · edge · SPK-04, FND-01

Add soft edge SPK-04 -> FND-01: the draft coral/workspace/ops.py needs FND-01's skeleton; until it lands the draft stays in the spike report.

Master edits:
- SPK-04.soft_deps += FND-01 (coral/workspace/ops.py draft needs the package skeleton)

Spec edits:
- SPK-04: **Dependencies.** Add FND-01 to the "Soft:" line (coral/workspace/ops.py draft needs the package skeleton; RES-010).
- FND-01: **Dependencies.** Add SPK-04 to the soft part of "Downstream, unblocks:" (RES-010).
- SPK-04: In spk.md, delete the bullet `` - Reviewer note: `coral/workspace/ops.py` needs FND-01's skeleton, also weeks 0-1 with no edge; keep the draft in the report until FND-01 lands. `` (resolved by RES-010).

### RES-011 · citation · WSP-05, SPK-04, SES-06

Correct HEAD citations in master text: child_session_recovery.py:164 -> :165 (decision 33); WSP-05 and SPK-04 S71 ranges connect.py:1417-1423, 6027-6034 -> 1417-1424, 6027-6035; native bearer runner/native/orchestration.py:9832 -> :9833.

Changed by the challenge pass: CH-27.

Master edits:
- notes[32]: "child_session_recovery.py:164" -> "child_session_recovery.py:165"
- WSP-05.included: "connect.py:1417-1423, 6027-6034" -> "connect.py:1417-1424, 6027-6035"
- SPK-04.included: "connect.py:1417-1423, 6027-6034" -> "connect.py:1417-1424, 6027-6035"

Section edits:
- D: D.4 step 7 and the D.9 relaunch row: replace "child_session_recovery.py:164" with "child_session_recovery.py:165". D.4 evidence step 6: replace "connect.py:1417-1423" with "connect.py:1417-1424". (RES-011)
- I: I.5 topology bullet: replace "child_session_recovery.py:164" with ":165"; I.5 evidence row: replace "connect.py:1417-1423" with "connect.py:1417-1424". (RES-011)
- C: C.6 orphan-reaper row and C.11 row 14: replace "connect.py:6027-6034" with "connect.py:6027-6035" (and any "1417-1423" with "1417-1424"). (RES-011)
- C: C.4 bridge-credential bullet: replace "runner/native/orchestration.py:9290, 9832" with "9290, 9833". (RES-011)
- J: J.2.1 TLD-02 row: replace "child_session_recovery.py:164" with ":165". J.1.1 D25 row: replace "9290, 9832" with "9290, 9833". In the J writer notes, drop child_session_recovery.py:164 and orchestration.py:9832 from the not-re-verified list (now :165 and :9833). (RES-011)

### RES-012 · assign · FND-05, FND-01

Registering the Coral import-boundary rule in dev/lint/custom_lint.RULES belongs to FND-05 (S39, which edits custom_lint.py); FND-01 supplies the rule module.

Master edits:
- FND-05.included += "Registers the Coral import-boundary rule in dev/lint/custom_lint.RULES (S39); FND-01 supplies the rule module"
- FND-01.excluded += "Registering the rule in dev/lint/custom_lint.RULES (FND-05, S39)"

Spec edits:
- FND-05: **Ownership boundaries.** Included: add "Registers the Coral import-boundary rule in dev/lint/custom_lint.RULES (S39); FND-01 supplies the rule module" (RES-012).
- FND-01: **Ownership boundaries.** Excluded: add "Registering the rule in dev/lint/custom_lint.RULES (FND-05, S39)" (RES-012).
- FND-01: In fnd.md, delete the bullet `` - Reviewer note: the master assigns `custom_lint.RULES` registration to no feature; this spec gives it to FND-05 (S39), which edits `custom_lint.py`. `` (resolved by RES-012).

### RES-013 · citation · FND-01

The import-boundary lint lives at dev/lint/lint_coral_import_boundary.py (the lint_<name>.py convention, custom_lint.py:18-19), not dev/lint/coral_boundary.py.

Changed by the challenge pass: CH-27.

Master edits:
- FND-01.included: "enforced per module by dev/lint" -> "enforced per module by dev/lint/lint_coral_import_boundary.py"

Spec edits:
- FND-01: In fnd.md, delete the bullet `` - Reviewer note: the master path `dev/lint/coral_boundary.py` breaks the `lint_<name>.py` convention (`custom_lint.py:18-19`), so this spec renames it. `` (resolved by RES-013).

Section edits:
- D: D.2 path notes: replace "The FND-01 spec renames master's `dev/lint/coral_boundary.py` to fit the `lint_<name>.py` convention" with "Master v3 uses `dev/lint/lint_coral_import_boundary.py` (the `lint_<name>.py` convention)". (RES-013)

### RES-014 · split · FND-03, DUR-01

Single-head tests: FND-03 owns the environment-level tests (an empty chain plus coral_0000_base has one head; ordering after Omnigent head; engine binding); DUR-01 owns the train-level single-head and models-match checks that every table PR runs. coral_0000_base becomes an explicit FND-03 migration.

Changed by the challenge pass: CH-13.

Master edits:
- FND-03.included: "Single-head, round-trip, SQLite-safe, ordering and engine-binding tests on SQLite, Postgres, CockroachDB and MySQL" -> "Environment-level tests on SQLite, Postgres, CockroachDB and MySQL: coral_0000_base gives an empty chain one head; round-trip, SQLite-safe DDL, ordering after Omnigent head and engine binding"
- FND-03.included += "coral_0000_base, an empty base revision, so the chain has a head before any table lands (utils.py:719-742)"
- DUR-01.included: "single-head and models-match checks on four lanes plus the split-DB lane" -> "train-level single-head and models-match checks that every table PR runs on four lanes plus the split-DB lane (the environment-level single-head test is FND-03's)"
- migration_train += {"migration": "coral_0000_base", "owner": "FND-03", "phase": "PH1", "prerequisite": "Omnigent head"}

Spec edits:
- FND-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Single-head, round-trip, SQLite-safe, ordering and engine-binding tests on SQLite, Postgres, CockroachDB and MySQL" so it says "Environment-level tests on SQLite, Postgres, CockroachDB and MySQL: coral_0000_base gives an empty chain one head; round-trip, SQLite-safe DDL, ordering after Omnigent head and engine binding". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-014).
- FND-03: **Ownership boundaries.** Included: add "coral_0000_base, an empty base revision, so the chain has a head before any table lands (utils.py:719-742)" (RES-014).
- DUR-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "single-head and models-match checks on four lanes plus the split-DB lane" so it says "train-level single-head and models-match checks that every table PR runs on four lanes plus the split-DB lane (the environment-level single-head test is FND-03's)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-014).
- FND-03: Tests: name the env-level single-head test as FND-03's and the per-PR train check as DUR-01's. (RES-014)
- DUR-01: Included: keep "train-level single-head and models-match checks"; Excluded: add "environment-level single-head test and coral_0000_base (FND-03)". (RES-014)
- FND-03: In fnd.md, delete the bullet `` - Reviewer note: an empty chain has no head (`utils.py:719-742`), so this spec adds `coral_0000_base`; the master leaves it implicit. `` (resolved by RES-014).

Section edits:
- D: D.6 migration table: add row 0 "`coral_0000_base` | empty base revision | FND-03 | PH1 | Omnigent head" before coral_0001_core. (RES-014)
- H: H.10 migration-train table: add a first row "| 1-3 | coral_0000_base (FND-03), an empty base revision |". (RES-014)

### RES-015 · split · FND-04, OPS-02, DUR-01

Split-DB lane: FND-04 owns the fixtures (SQLite operational DB plus a separate SQLite conversation DB); OPS-02 owns the CI job; DUR-01, DUR-05, SES-03 and OPS-04 only run their tests in it.

Changed by the challenge pass: CH-15.

Master edits:
- FND-04.included: "Split-DB lane: SQLite operational DB plus a separate SQLite conversation DB" -> "Split-DB lane fixtures: SQLite operational DB plus a separate SQLite conversation DB (OPS-02 wires the CI job)"
- OPS-02.included: "plus the split-DB lane" -> "plus the CI job for FND-04's split-DB lane fixtures"

Spec edits:
- FND-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Split-DB lane: SQLite operational DB plus a separate SQLite conversation DB" so it says "Split-DB lane fixtures: SQLite operational DB plus a separate SQLite conversation DB (OPS-02 wires the CI job)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-015).
- OPS-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "plus the split-DB lane" so it says "plus the CI job for FND-04's split-DB lane fixtures". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-015).
- FND-04: Excluded: add "the split-DB CI job (OPS-02)". (RES-015)
- OPS-02: Excluded: add "split-DB fixtures (FND-04)". (RES-015)
- DUR-01: Technical scope, Tests: after "FND-04's split-DB lane" add " (CI job: OPS-02)". DUR-01 claims no ownership of the lane, so nothing else changes. (RES-015)

### RES-016 · assign · FND-03, OPS-03

FND-03 owns the manual recovery command python -m coral.db.migrate upgrade (and current), since it owns coral/db/migrate.py.

Master edits:
- FND-03.included += "Manual recovery command python -m coral.db.migrate upgrade (and current), documented for operators"
- OPS-03.excluded += "The manual migrate command (FND-03)"

Spec edits:
- FND-03: **Ownership boundaries.** Included: add "Manual recovery command python -m coral.db.migrate upgrade (and current), documented for operators" (RES-016).
- OPS-03: **Ownership boundaries.** Excluded: add "The manual migrate command (FND-03)" (RES-016).
- FND-03: In fnd.md, delete the bullet `` - Reviewer note: the master gives the manual migrate command no owner; confirm here or move to OPS-03. `` (resolved by RES-016).

### RES-017 · assign · OPS-03, FND-03, FND-02

Docker and Databricks deploy-entrypoint enablement of Coral goes to OPS-03 as a new upstream-first seam row S57b: Docker runs Coral migrations after Omnigent's, and both deploy entrypoints pass server_plugins to create_app. FND-03 keeps S57's Databricks migration step.

Changed by the challenge pass: CH-14.

Master edits:
- OPS-03.included += "Deploy entrypoints enable Coral (new seam row S57b, upstream-first): deploy/docker/entrypoint.py runs Coral migrations after Omnigent's (:97), and deploy/docker/entrypoint.py:490 and deploy/databricks/src/app.py:305 pass server_plugins to create_app"
- FND-03.included: "Deploy entrypoint runs Coral migrations (S57)" -> "Databricks deploy entrypoint runs Coral migrations (S57); the Docker migration step and the server_plugins pass-through are OPS-03's S57b"
- FND-02.excluded += "Deploy-entrypoint enablement of Coral in Docker and Databricks (OPS-03)"
- OPS-03.seams += S57b
- notes += "RES-017: Seam ledger amendment: S57 (FND-03) keeps the Databricks migration step; new row S57b (OPS-03, upstream-first) covers the Docker migration step (deploy/docker/entrypoint.py:97) and the server_plugins pass-through at deploy/docker/entrypoint.py:490 and deploy/databricks/src/app.py:305."

Spec edits:
- OPS-03: **Ownership boundaries.** Included: add "Deploy entrypoints enable Coral (new seam row S57b, upstream-first): deploy/docker/entrypoint.py runs Coral migrations after Omnigent's (:97), and deploy/docker/entrypoint.py:490 and deploy/databricks/src/app.py:305 pass server_plugins to create_app" (RES-017).
- FND-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Deploy entrypoint runs Coral migrations (S57)" so it says "Databricks deploy entrypoint runs Coral migrations (S57); the Docker migration step and the server_plugins pass-through are OPS-03's S57b". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-017).
- FND-02: **Ownership boundaries.** Excluded: add "Deploy-entrypoint enablement of Coral in Docker and Databricks (OPS-03)" (RES-017).
- OPS-03: **Technical scope.** Modify or extend upstream: add S57b to the seams this feature lands (RES-017).
- OPS-03: Technical scope > Modify or extend upstream: add "S57b (new seam row, OPS-03, upstream-first): deploy/docker/entrypoint.py runs Coral migrations after run_migrations (:97); create_app calls at deploy/docker/entrypoint.py:490 and deploy/databricks/src/app.py:305 pass server_plugins". Acceptance: a Docker image built from the fork starts with Coral enabled and at Coral head. (RES-017)
- FND-03: Excluded: add "Docker migrations and the server_plugins pass-through (OPS-03)". (RES-017)
- FND-02: In fnd.md, delete the bullet `` - Reviewer note (unowned): S32 wires only `cli.py`; the `create_app` calls at `deploy/databricks/src/app.py:305` and `deploy/docker/entrypoint.py:490` cannot enable Coral. `` (resolved by RES-017).
- FND-03: In fnd.md, delete the bullet `` - Reviewer note: S57 covers only Databricks; `deploy/docker/entrypoint.py:97` migrates Omnigent alone (see the FND-02 deploy note). `` (resolved by RES-017).

### RES-018 · assign · OPS-03, FND-02

`coral server` turns the Coral plugin on by default: OPS-03's coral entry sets server_plugins: [coral.server_plugin] and passes --config, because the CLI server reads server_plugins only from an explicit --config file (cli.py:4857). FND-02 keeps the key and loader.

Master edits:
- OPS-03.included += "coral server defaults server_plugins to [coral.server_plugin] and always passes --config, because the CLI server reads server_plugins only from an explicit --config file (cli.py:4857)"

Spec edits:
- OPS-03: **Ownership boundaries.** Included: add "coral server defaults server_plugins to [coral.server_plugin] and always passes --config, because the CLI server reads server_plugins only from an explicit --config file (cli.py:4857)" (RES-018).
- OPS-03: Acceptance: `coral server` with no config file starts with Coral enabled (GET /v1/coral/info returns 200). Keep the Excluded item "the server_plugins key and loader (FND-02)". (RES-018)
- OPS-03: In ops-a.md, delete the bullet `` - Reviewer note: no feature owns a default `server_plugins` for `coral server`; FND-02 owns only the key. `` (resolved by RES-018).

### RES-019 · fixed · FND-04

FND-04's bootstrap appends --config because server_runner passes none (server_runner.py:144-167) and server_plugins is read only from --config; the spec already does this.

Spec edits:
- FND-04: In fnd.md, replace the bullet `` - Reviewer note: `server_runner` passes no `--config` (`server_runner.py:144-167`), and `server_plugins` is read only from `--config` (`omnigent/cli.py:4857`), so the bootstrap appends `--config`. `` with `` - `server_runner` passes no `--config` (`server_runner.py:144-167`), and `server_plugins` is read only from `--config` (`omnigent/cli.py:4857`), so the bootstrap appends `--config`. `` (no longer a reviewer note; settled by RES-019).

### RES-020 · assign · FND-01, OPS-03, DUR-02

FND-01's tier rule gains named exceptions: tier-(c) omnigent.db helpers on coral.db's allowlist (pinned by signature tests) need not go through _upstream.py; coral/cli.py and coral/server_plugin.py are composition roots; coral.identity (K10) is tier (a).

Master edits:
- FND-01.included: "with every Omnigent private routed through coral/omni/_upstream.py; tier (c) coral.db may import an explicit allowlist of omnigent.db helpers" -> "with every Omnigent private routed through coral/omni/_upstream.py except the named tier-(c) omnigent.db helpers on coral.db's allowlist, which signature tests pin"
- FND-01.included += "Composition roots exempt from the app-tier rule: coral/cli.py and coral/server_plugin.py (server_plugins: [coral.server_plugin]); coral.identity (K10) is tier (a)"

Spec edits:
- FND-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "with every Omnigent private routed through coral/omni/_upstream.py; tier (c) coral.db may import an explicit allowlist of omnigent.db helpers" so it says "with every Omnigent private routed through coral/omni/_upstream.py except the named tier-(c) omnigent.db helpers on coral.db's allowlist, which signature tests pin". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-020).
- FND-01: **Ownership boundaries.** Included: add "Composition roots exempt from the app-tier rule: coral/cli.py and coral/server_plugin.py (server_plugins: [coral.server_plugin]); coral.identity (K10) is tier (a)" (RES-020).
- FND-01: In fnd.md, delete the bullet `` - Reviewer note: "every private through `_upstream.py`" conflicts with FND-03's private `omnigent.db` helpers. This spec allows named tier-c entries pinned by signature tests. `` (resolved by RES-020).
- FND-01: In fnd.md, delete the bullet `` - Reviewer note: `server_plugins: [coral.server_plugin]` needs the root exemption. `` (resolved by RES-020).
- OPS-03: In ops-a.md, delete the bullet `` - Reviewer note: FND-01's tier rule limits the app tier to `coral.omni.protocols`. DUR-02 and this feature need `coral/cli.py` as a composition root. `` (resolved by RES-020).

Section edits:
- D: D.3: state the two composition roots (coral/cli.py, coral/server_plugin.py) and place coral.identity in tier (a) as decided, removing "pending FND-01 confirmation". (RES-020)

### RES-021 · contract · FND-02, TLS-01, WSP-01, FND-04

K17 states the host-token split: FND-02 defines coral_runner:n; TLS-01 lands the HostHelloFrame line (S50), which advertises every Coral token registered through the K17 process map, and honours CORAL_DISABLE_HOST_ENTRY_POINTS=1; WSP-01 registers its sandbox report as a second token, coral_host_sandbox:1:<platform>:<backend>:<0|1> (the shape in WSP-01's spec), from week 5 with no frames.py edit. WSP-01 consumes K17.

Changed by the challenge pass: CH-16.

Master edits:
- K17.description += "The coral_runner:n token is defined here and advertised by TLS-01's S50 line in host/frames.py. That line advertises every Coral host token registered through the K17 process map, so later tokens need no further frames.py edit. CORAL_DISABLE_HOST_ENTRY_POINTS=1 suppresses the host entry points and every Coral token (FND-04's missing-token case; implemented by TLS-01). WSP-01 registers its host sandbox report as coral_host_sandbox:1:<platform>:<backend>:<0\|1> (shape in WSP-01's spec)."
- FND-02.included: "and the coral_runner:n host capability token advertised when they load" -> "and the coral_runner:n host capability token, defined here and advertised by TLS-01's S50 line when they load; CORAL_DISABLE_HOST_ENTRY_POINTS suppresses both"
- TLS-01.included: "through one ledgered line in host/frames.py (under S50)" -> "through one ledgered line in host/frames.py (under S50) that advertises every K17-registered Coral host token (WSP-01 registers coral_host_sandbox:1:<platform>:<backend>:<0\|1> from week 5 with no further frames.py edit), and honours CORAL_DISABLE_HOST_ENTRY_POINTS"
- WSP-01.included: "advertised with the coral_runner token" -> "registered through FND-02's K17 process map as coral_host_sandbox:1:<platform>:<backend>:<0\|1>, which TLS-01's S50 line advertises"
- WSP-01.contracts_consumed += K17; K17.consumers += WSP-01

Spec edits:
- FND-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "and the coral_runner:n host capability token advertised when they load" so it says "and the coral_runner:n host capability token, defined here and advertised by TLS-01's S50 line when they load; CORAL_DISABLE_HOST_ENTRY_POINTS suppresses both". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-021).
- TLS-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "through one ledgered line in host/frames.py (under S50)" so it says "through one ledgered line in host/frames.py (under S50) that advertises every K17-registered Coral host token (WSP-01 registers coral_host_sandbox:1:<platform>:<backend>:<0|1> from week 5 with no further frames.py edit), and honours CORAL_DISABLE_HOST_ENTRY_POINTS". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-021).
- WSP-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "advertised with the coral_runner token" so it says "registered through FND-02's K17 process map as coral_host_sandbox:1:<platform>:<backend>:<0|1>, which TLS-01's S50 line advertises". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-021).
- WSP-01: **Dependencies.** Add K17 to the "Contracts: consumes ..." line (RES-021).
- WSP-01: Technical scope, Sandbox report bullet: keep the token shape `coral_host_sandbox:1:<platform>:<backend>:<0|1>` and replace "through TLS-01's S50." with "registered through FND-02's K17 process map; TLS-01's S50 line advertises it, so WSP-01 makes no frames.py edit for it." (RES-021)
- TLS-01: Implementation breakdown step 4: replace "The `frames.py` host line and host tests." with "The `frames.py` host line, which advertises every K17-registered Coral host token (coral_runner:n now; WSP-01's sandbox token from week 5), and host tests." (RES-021)
- FND-02: In fnd.md, delete the bullet `` - Reviewer note: `CORAL_DISABLE_HOST_ENTRY_POINTS` is a K17 addition for FND-04, implemented by TLS-01. `` (resolved by RES-021).

### RES-022 · edge · FND-04, TLS-01

Add soft edge FND-04 -> TLS-01: the Tier B sample needs TLS-01's S7, S8 and S10 transport and its S50 token.

Master edits:
- FND-04.soft_deps += TLS-01 (Tier B sample uses S7, S8, S10 and the S50 token)

Spec edits:
- FND-04: **Dependencies.** Add TLS-01 to the "Soft:" line (Tier B sample uses S7, S8, S10 and the S50 token; RES-022).
- TLS-01: **Dependencies.** Add FND-04 to the soft part of "Downstream, unblocks:" (RES-022).
- FND-04: In fnd.md, delete the bullet `` - Reviewer note: the sample needs TLS-01's S7, S8 and S10 transport and S50 token, yet TLS-01 is undeclared; recommend a soft edge FND-04 -> TLS-01. `` (resolved by RES-022).

### RES-023 · citation · FND-01, FND-05, DUR-06, WSP-02, WEB-13, WEB-10, SPK-03

Key-path amendments that the JSON cannot carry yet (key_paths are not edited in v3) are recorded in master notes: FND-01 lint file rename; FND-05 adds .github/workflows/ci.yml (S39c needs ci.yml:198); DUR-06 adds omnigent/cli.py and identity_migration.py (S56); WSP-02 adds host_registry.py and host_tunnel.py (S40); WEB-13 adds runs/phone/; WEB-10 owns runs/depth/ and canvas/overlay/ only; SPK-03 probes stay off tests/harness_bench/probes/.

Master edits:
- notes += "RES-023: Key-path amendments (apply when key_paths are regenerated): FND-01 dev/lint/coral_boundary.py -> dev/lint/lint_coral_import_boundary.py; FND-05 + .github/workflows/ci.yml (S39c, ci.yml:198); DUR-06 + omnigent/cli.py and omnigent/server/identity_migration.py (S56); WSP-02 + omnigent/server/host_registry.py and omnigent/server/routes/host_tunnel.py (S40); WEB-13 + web/src/workflows/runs/phone/; WEB-10 web/src/workflows/runs/ narrowed to runs/depth/ and canvas/overlay/; SPK-03 tests/harness_bench/probes/ removed (prototypes stay on the spike branch)."

Spec edits:
- DUR-06: In dur.md, delete the bullet `` - Reviewer note: the remap runs in the CLI outside the lifespan, so S56 also touches `omnigent/cli.py`; key paths omit it and `identity_migration.py`. `` (resolved by RES-023).
- FND-05: In fnd.md, delete the bullet `` - Reviewer note: S39c needs `.github/workflows/ci.yml:198`, because `--cov=omnigent` overrides the config source. The gap_analysis S39 row lists this line, but the master FND-05 key_paths omit `ci.yml`. `` (resolved by RES-023).

### RES-024 · split · ENG-06, SES-04, TLS-02, DUR-05

Cancel chain: ENG-06 owns the cancel transition, which emits one K21 cancel_sessions effect per live slot (I8), and the reducer's late-submit rejection; SES-04 owns the cancel_sessions executor (interrupt -> stop -> omnigent.closed); TLS-02 owns tool-level post-cancel rejection; DUR-05 enqueues the same cancel_sessions effect for runs it cannot read.

Changed by the challenge pass: CH-15.

Master edits:
- ENG-06.included: "Cancel effect chain interrupt -> stop -> omnigent.closed (R-13) and late-submit rejection; retry step" -> "Cancel transition that emits one K21 cancel_sessions effect per live slot (I8) and late-submit rejection in the reducer; retry step"
- SES-04.included: "Cancel chain interrupt -> stop -> omnigent.closed; skeleton slice" -> "cancel_sessions K21 executor: interrupt -> stop -> omnigent.closed (R-13); skeleton slice"
- SES-04.excluded += "The cancel transition and late-submit rejection (ENG-06)"
- ENG-06.excluded += "Executing cancel_sessions (SES-04)"
- TLS-02.included: "Post-cancel submits rejected" -> "Tool-level post-cancel rejection (the reducer's run_cancelled rule is ENG-06's)"
- DUR-05.included += "Cancelling a run whose state this build cannot read enqueues SES-04's cancel_sessions effect through a narrow store path, without the reducer"

Spec edits:
- ENG-06: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Cancel effect chain interrupt -> stop -> omnigent.closed (R-13) and late-submit rejection; retry step" so it says "Cancel transition that emits one K21 cancel_sessions effect per live slot (I8) and late-submit rejection in the reducer; retry step". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-024).
- SES-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Cancel chain interrupt -> stop -> omnigent.closed; skeleton slice" so it says "cancel_sessions K21 executor: interrupt -> stop -> omnigent.closed (R-13); skeleton slice". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-024).
- SES-04: **Ownership boundaries.** Excluded: add "The cancel transition and late-submit rejection (ENG-06)" (RES-024).
- ENG-06: **Ownership boundaries.** Excluded: add "Executing cancel_sessions (SES-04)" (RES-024).
- TLS-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Post-cancel submits rejected" so it says "Tool-level post-cancel rejection (the reducer's run_cancelled rule is ENG-06's)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-024).
- DUR-05: **Ownership boundaries.** Included: add "Cancelling a run whose state this build cannot read enqueues SES-04's cancel_sessions effect through a narrow store path, without the reducer" (RES-024).
- DUR-05: Technical scope, Upgrade bullet: replace "`cancel_unreadable_run` enqueues stops for sessions bound to the run." with "`cancel_unreadable_run` enqueues SES-04's K21 `cancel_sessions` effect (the kind ENG-06's cancel transition emits) through a narrow store path, without the reducer." (RES-024)
- DUR-05: In dur.md, delete the bullet `` - Reviewer note: cancelling an unreadable run cannot use the reducer. ENG-06's cancel is a transition that emits SES-04's `cancel_sessions` effect; the narrow store path should enqueue that same effect kind, which ENG-06 and SES-04 must confirm. `` (resolved by RES-024).
- ENG-06: In eng-a.md, delete the bullet `` - Reviewer note: TLS-02's master scope also lists a per-slot rejected counter, and SES-04's the cancel chain. Here: counter state, and one `cancel_sessions` effect from the cancel transition (I8); TLS-02 feeds rejections; SES-04 executes. `` (resolved by RES-024).

### RES-025 · split · ENG-06, TLS-02

Rejected-call counter: ENG-06 owns the per-slot counter state and the 3-in-a-row pause (evaluation in progress and evidence.missing never count); TLS-02 only emits rejection observations that feed it.

Master edits:
- TLS-02.included: "per-slot rejected counter" -> "rejection observations that feed ENG-06's per-slot rejected counter"
- ENG-06.included: "rejected-call pause (3 in a row per slot)" -> "rejected-call counter state and pause (3 in a row per slot; 'evaluation in progress' and evidence.missing never count, DD§6.7)"

Spec edits:
- TLS-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "per-slot rejected counter" so it says "rejection observations that feed ENG-06's per-slot rejected counter". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-025).
- ENG-06: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "rejected-call pause (3 in a row per slot)" so it says "rejected-call counter state and pause (3 in a row per slot; 'evaluation in progress' and evidence.missing never count, DD§6.7)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-025).

### RES-026 · split · ENG-03, HRN-02, WSP-01

V10: ENG-03 owns the pure rule over a configured-harness list passed in; HRN-02 owns the live inputs and calls the rule from its preflight. Add soft edge HRN-02 -> ENG-03 (HRN-02 runs weeks 3-5 against a stub). HRN-02 ends at week 5 with its sandbox and validity ports failing closed; ENG-03 and WSP-01 (both start week 5) bind their checks into those ports in their own PRs. No reverse edge is added, because HRN-02 already soft-depends on both and the reverse would form a cycle.

Changed by the challenge pass: CH-08, CH-25.

Master edits:
- HRN-02.soft_deps += ENG-03 (V10 rule and validity checks (stubbed until ENG-03 lands))
- ENG-03.included: "V10 against configured harnesses" -> "V10 as a pure rule over a configured-harness list passed in"
- HRN-02.included: "Preflight engine: V10 configured harnesses" -> "Preflight engine: live configured-harness inputs to ENG-03's V10 rule"
- ENG-03.included += "Binds V10 and the validity check into HRN-02's preflight validity port in its V10 PR (the port fails closed until then)"
- WSP-01.included += "Binds the host sandbox report into HRN-02's preflight sandbox port (the port fails closed until then)"

Spec edits:
- HRN-02: **Dependencies.** Add ENG-03 to the "Soft:" line (V10 rule and validity checks (stubbed until ENG-03 lands); RES-026).
- ENG-03: **Dependencies.** Add HRN-02 to the soft part of "Downstream, unblocks:" (RES-026).
- ENG-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "V10 against configured harnesses" so it says "V10 as a pure rule over a configured-harness list passed in". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-026).
- HRN-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Preflight engine: V10 configured harnesses" so it says "Preflight engine: live configured-harness inputs to ENG-03's V10 rule". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-026).
- ENG-03: **Ownership boundaries.** Included: add "Binds V10 and the validity check into HRN-02's preflight validity port in its V10 PR (the port fails closed until then)" (RES-026).
- WSP-01: **Ownership boundaries.** Included: add "Binds the host sandbox report into HRN-02's preflight sandbox port (the port fails closed until then)" (RES-026).
- ENG-03: Implementation breakdown step 4: replace "V12, then V10 with its guard test." with "V12, then V10 with its guard test; the same PR binds V10 and the validity check into HRN-02's preflight validity port." (RES-026)
- HRN-02: Implementation breakdown step 5: replace "sandbox and validity ports fail closed until WSP-01 and ENG-03 land." with "sandbox and validity ports fail closed until WSP-01 and ENG-03 bind them in their own PRs." (RES-026)
- ENG-03: In eng-a.md, delete the bullet `` - Reviewer note: HRN-02's master scope also lists V10 in its preflight engine (weeks 3-5), with no edge to ENG-03 (weeks 5-7). Here: the pure rule; HRN-02: live inputs. Add a soft edge HRN-02 -> ENG-03, or land V10 first. `` (resolved by RES-026).
- HRN-02: In prf-hrn.md, delete the bullet `` - Reviewer note: the validity and sandbox checks read ENG-03 and WSP-01 (week 7); HRN-02 ends week 5 with no ENG-03 edge. Add a soft edge. `` (resolved by RES-026).

### RES-027 · split · ENG-02, ENG-08, ENG-09, ENG-01, SES-10

Groups: ENG-02 resolves group entry, exit and body regions from reserved K1 group keys (no Group IR); ENG-08 repeats over a step or a group-body region; ENG-09 owns the Group IR proper (named, reusable groups, rule inheritance, saved blocks). SES-10 at week 14 therefore needs only ENG-02 and ENG-08.

Changed by the challenge pass: CH-10.

Master edits:
- ENG-02.included: "decision label sets and checked parts" -> "decision label sets, checked parts, and group entry, exit and body regions read from K1 group keys (no Group IR)"
- ENG-09.included: "Group IR with entry and exit" -> "Group IR (named, reusable groups with rule inheritance) over ENG-02's group regions"
- ENG-08.included: "Repeat contract: order" -> "Repeat contract over a step or a group-body region (ENG-02, no Group IR): order"
- ENG-08.excluded: "Groups (ENG-09)" -> "Group IR, saved blocks and group rules (ENG-09)"
- K1.description += "Group keys (the group kind with members, entry and exit; members define the body region) are reserved from PH0, so ENG-02 can resolve group regions, ENG-08 can repeat over them and WEB-08 can edit membership before ENG-09 adds the Group IR."

Spec edits:
- ENG-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "decision label sets and checked parts" so it says "decision label sets, checked parts, and group entry, exit and body regions read from K1 group keys (no Group IR)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-027).
- ENG-09: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Group IR with entry and exit" so it says "Group IR (named, reusable groups with rule inheritance) over ENG-02's group regions". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-027).
- ENG-08: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Repeat contract: order" so it says "Repeat contract over a step or a group-body region (ENG-02, no Group IR): order". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-027).
- ENG-08: **Ownership boundaries.** Excluded: reword the item covering "Groups (ENG-09)" so it says "Group IR, saved blocks and group rules (ENG-09)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-027).
- ENG-09: Excluded: add "group region resolution (ENG-02); repeat over a group body (ENG-08)". (RES-027)
- ENG-02: In eng-a.md, delete the bullet `` - Reviewer note: the D§5.6 fixture needs group entry and exit resolved, but ENG-09's master scope owns "Group IR with entry and exit". This spec only resolves them; group rules stay with ENG-09. `` (resolved by RES-027).
- ENG-08: In eng-b.md, delete the bullet `` - Reviewer note: SES-10 (week 14) repeats over a multi-step group, but master ENG-08 excludes "Groups (ENG-09)" and ENG-09 (weeks 18-22.5) owns the Group IR; this spec reads K1 group keys as an ENG-02 region. The master should confirm or move a group-body IR here. `` (resolved by RES-027).

### RES-028 · contract · SES-01, GTE-06, ENG-06, ENG-09

K19 adds overdue and reaction alert kinds (additive, signed by SES-01, implemented by GTE-06) so ENG-09 can emit them; K19 types live in the pure tier so ENG-06 and ENG-09 can import them; gates and questions are alerts. ENG-09's author-set overdue reactions are distinct from ENG-06's gate reminders and escalation.

Changed by the challenge pass: CH-15, CH-28.

Master edits:
- K19.description: "Alert kinds (gate, question, pause, watchdog, run completed, failed, cancelled)" -> "Alert kinds (gate, question, pause, watchdog, overdue, reaction, run completed, failed, cancelled; overdue and reaction are additive for ENG-09, signed by SES-01 and implemented by GTE-06)"
- K19.description += "Alert types live in the pure tier (coral/alerts/types.py) so engine code emits them without I/O. Gates and questions are alerts."
- GTE-06.included += "overdue and reaction alert kinds for ENG-09 (additive K19)"
- ENG-09.included: "expected_duration x factor overdue alerts into the Inbox" -> "expected_duration x factor overdue alerts into the Inbox (author-set; distinct from ENG-06's gate reminders and escalation)"

Spec edits:
- GTE-06: **Ownership boundaries.** Included: add "overdue and reaction alert kinds for ENG-09 (additive K19)" (RES-028).
- ENG-09: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "expected_duration x factor overdue alerts into the Inbox" so it says "expected_duration x factor overdue alerts into the Inbox (author-set; distinct from ENG-06's gate reminders and escalation)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-028).
- GTE-06: Data model: replace "with a CHECK over gate, question, pause, watchdog, run_completed, run_failed and run_cancelled" with "with a CHECK over gate, question, pause, watchdog, overdue, reaction, run_completed, run_failed and run_cancelled". (RES-028)
- ENG-06: In eng-a.md, delete the bullet `` - Reviewer note: K19 has no overdue kind (ENG-09) and no tier-(a) home. `` (resolved by RES-028).
- ENG-09: In eng-b.md, delete the bullet `` - Reviewer note: K19 has no overdue or reaction kind; needs an additive change signed by SES-01 and GTE-06. `` (resolved by RES-028).
- GTE-06: In gte.md, delete the bullet `` - Reviewer note: K19 lacks the overdue and reaction kinds that ENG-09 needs. Adding them is an additive K19 change that SES-01 must sign off. `` (resolved by RES-028).

Section edits:
- B: B.3: add a row "| D36 | Gates as alerts: eng_tools §5.2 treats gates as separate from alerts; master K19 lists gate and question kinds | eng_tools §5.2 vs master K19 | Resolved in master v3: gates and questions are alerts | TL | SES-01, GTE-06 |". (RES-028)

### RES-029 · citation · ENG-06, SPK-05

Gate reminders are on at M2 (one reminder, then escalation; never auto-resolve), as master ENG-06 and SPK-05's OQ-5 proposal say; sandbox keep-warm is WSP-04 (post-M4). The ENG-06 spec is fixed; section J's OQ-5 default is wrong and must change.

Section edits:
- J: J.3.1 OQ-5 row: replace the default "Gates never auto-resolve; no reminders or expiry at M2; the engine wakes a sleeping host" with "Gates never auto-resolve; one reminder, then escalation (ENG-06, on by default); no expiry; sandbox keep-warm is WSP-04 (post-M4)". (RES-029)

### RES-030 · residual · SPK-05, ENG-06, DUR-05, TLS-03

The 30-minute watchdog default (OQ-14) and DUR-05's 3x-resync rule have no source. They stay labelled as proposals until SPK-05 records OQ-14.

Section edits:
- J: J.3.1 OQ-14 row: append "(30 minutes is unsourced; SPK-05 records it by week 4)". (RES-030)
- J: J.6: add the row "| RES-030 | The 30-minute watchdog default (OQ-14) and DUR-05's 3x-resync rule have no source. They stay labelled as proposals until SPK-05 records OQ-14. | SPK-05 (PM) | Week 4 (TLS-03 starts week 5.5) | ENG-06, DUR-05 and TLS-03 defaults; the watchdog p95 from OPS-07 re-checks it. |".

### RES-031 · citation · ENG-06

Three rejected calls pause the run as paused(rejected_calls), naming the slot (K2 pause reasons are run-level, D§7.3). M2 exit 4 and ENG-06's proving test read "pause the slot" in that sense.

Changed by the challenge pass: CH-15.

Master edits:
- notes += "RES-031: Reading rule: M2 exit criterion 4 and ENG-06's proving test say 'three rejected calls pause the slot'; this means the run pauses as paused(rejected_calls) with the slot named in the cause (K2 pause reasons are run-level, D§7.3)."

Spec edits:
- ENG-06: In eng-a.md, delete the bullet `` - Reviewer note: M2 exit 4 and the proof say "pause the slot"; D§7.3 pauses the run, which this spec follows. `` (resolved by RES-031).

### RES-032 · fixed · ENG-04

ENG-04's skeleton target "week 4.5" is a target; IM-1 (week 7) is the hard deadline. The spec already says so and agrees with the master.

### RES-033 · contract · API-01, ENG-01, ENG-04

K8 RunView and patch types live in a pure-tier module (coral/runview/types.py) produced by API-01 and co-signed by ENG-01 at IM-0; ENG-01 (K3 embeds the patch) and ENG-04 (projection.py emits patches) consume K8. No edge is added: API-01 already soft-depends on ENG-01.

Master edits:
- ENG-01.contracts_consumed += K8; K8.consumers += ENG-01
- ENG-04.contracts_consumed += K8; K8.consumers += ENG-04
- K8.description += "RunView and patch types live in the pure tier (coral/runview/types.py) so ENG-01's K3 and ENG-04's projection import them; API-01 produces them and ENG-01 co-signs at IM-0."

Spec edits:
- ENG-01: **Dependencies.** Add K8 to the "Contracts: consumes ..." line (RES-033).
- ENG-04: **Dependencies.** Add K8 to the "Contracts: consumes ..." line (RES-033).
- ENG-01: In eng-a.md, delete the bullet `` - Reviewer note: K3 embeds K8's patch, but ENG-01 has no edge to API-01 (only API-01's soft edge back), and tier (a) cannot import `coral/api`. API-01 should co-sign a pure RunView module. `` (resolved by RES-033).
- ENG-04: In eng-a.md, delete the bullet `` - Reviewer note: `projection.py` emits K8 patches; add K8 to ENG-04's consumed contracts. `` (resolved by RES-033).

### RES-034 · contract · ENG-01, ENG-07, WEB-03

K1 reserves a parameters block (name, type, default, bounds) for template parameters (loop limit, reviewer models, gate reject route) and an optional per-roster-member model override; ENG-01 reserves both at IM-0, ENG-07 fills them, WEB-03 consumes K1.

Master edits:
- K1.description += "A parameters block (name, type, default, bounds) for template parameters such as the loop limit, reviewer models and the gate reject route, and an optional per-roster-member model override, both reserved in PH0 and filled by ENG-07."
- ENG-01.included += "K1 reserves a parameters block and an optional per-roster-member model override (filled by ENG-07)"
- WEB-03.contracts_consumed += K1; K1.consumers += WEB-03

Spec edits:
- ENG-01: **Ownership boundaries.** Included: add "K1 reserves a parameters block and an optional per-roster-member model override (filled by ENG-07)" (RES-034).
- WEB-03: **Dependencies.** Add K1 to the "Contracts: consumes ..." line (RES-034).
- ENG-01: In eng-a.md, delete the bullet `` - Reviewer note: reserve a K1 `parameters` block now for ENG-07. `` (resolved by RES-034).
- ENG-07: In eng-b.md, delete the bullet `` - Reviewer note: the parameter declaration has no contract home (no K1 `parameters` key or K7 field), yet WEB-03 consumes it; propose an additive K1 block. `` (resolved by RES-034).
- ENG-07: In eng-b.md, delete the bullet `` - Reviewer note: per-reviewer models need a K1 roster model override. `` (resolved by RES-034).

### RES-035 · citation · ENG-01, ENG-05, ENG-07, SPK-01

Loop limits count passes. D§5.6 ('three passes'), M2 journey step 4 ('pass 2 of 3'), the ENG-05 and ENG-07 proofs and IM-3's 'loop to limit 3' all count passes; only DD§5.3.3(a) counts traversals, and it is superseded. SPK-01 writes this into its OQ-19 record on day 3 of week 1; a later switch would be a K1 change.

Changed by the challenge pass: CH-12.

Master edits:
- K1.description += "Loop limits count passes (OQ-19; DD§5.3.3(a)'s traversal count is superseded)."
- SPK-01.included: "the D6 back-arrow join rule (OQ-19)" -> "the D6 back-arrow join rule and pass-counted loop limits (OQ-19)"

Spec edits:
- SPK-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "the D6 back-arrow join rule (OQ-19)" so it says "the D6 back-arrow join rule and pass-counted loop limits (OQ-19)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-035).
- SPK-01: Records table, OQ-19 row: append "; loop limits count passes" to the decision text. (RES-035)
- ENG-01: In eng-a.md, replace the bullet `` - Reviewer note: DD§5.3.3(a) counts traversals, but D§5.6 ("three passes"), M2 journey step 4 ("pass 2 of 3") and the ENG-05 and ENG-07 proofs imply passes. K1 uses passes, pending OQ-19. `` with `` - Loop limits count passes (D§5.6 "three passes", M2 journey step 4 "pass 2 of 3", the ENG-05 and ENG-07 proofs); DD§5.3.3(a)'s traversal count is superseded (master v3; recorded under OQ-19 by SPK-01). `` (no longer a reviewer note; settled by RES-035).
- ENG-05: In eng-a.md, replace the bullet `` - Reviewer note: passes versus traversals is the same open point as in ENG-01; this spec uses passes. `` with `` - Loop limits count passes, as in ENG-01 (master v3, OQ-19). `` (no longer a reviewer note; settled by RES-035).

Section edits:
- J: J.3.1 OQ-19 row: append "; loop limits count passes (D§5.6), superseding DD§5.3.3(a)'s traversals (master v3)" to the Recommendation cell. (RES-035)
- B: B.3: add a row "| D35 | Loop limits: DD§5.3.3(a) counts traversals; D§5.6 and M2 journey step 4 count passes | DD§5.3.3(a) vs D§5.6, M2 journey | Resolved in master v3: loop limits count passes | PM, TL (OQ-19) | ENG-01, ENG-05, ENG-07 |". (RES-035)

### RES-036 · split · ENG-04, ENG-11

I7: ENG-04's fuzz harness checks I7 in reducer form only; ENG-11 owns the full reconcile property test.

Master edits:
- ENG-04.included: "I1-I8 seeded fuzz harness" -> "I1-I8 seeded fuzz harness (I7 in reducer form only; the reconcile property test is ENG-11's)"

Spec edits:
- ENG-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "I1-I8 seeded fuzz harness" so it says "I1-I8 seeded fuzz harness (I7 in reducer form only; the reconcile property test is ENG-11's)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-036).
- ENG-04: In eng-a.md, delete the bullet `` - Reviewer note: I7 needs ENG-11's reconcile, so the proof checks I7 only in reducer form. `` (resolved by RES-036).

### RES-037 · contract · ENG-08, ENG-01, HRN-02, SES-10

K1 Analysis gains requires_structure_runtime (additive, ENG-08). ENG-08 also adds the preflight check that refuses such runs to HRN-02's pure preflight module (HRN-02 ends week 5, before the flag exists), and SES-10 lifts the refusal at exit. ENG-01 and HRN-02's owner sign the flag when ENG-08's first PR lands. Add soft edge ENG-08 -> HRN-02.

Changed by the challenge pass: CH-09, CH-22, CH-25.

Master edits:
- K1.description += "Analysis carries requires_structure_runtime (additive, ENG-08); the preflight refuses such runs (a check ENG-08 adds to HRN-02's module) until SES-10 lifts it at exit."
- ENG-08.included += "The requires_structure_runtime Analysis flag and the preflight check that refuses such runs, added to HRN-02's coral/validate/preflight.py with HARNESS-lead review"
- SES-10.included += "Lifts the requires_structure_runtime preflight refusal at exit, once structured runs pass E2E-5"
- ENG-08.soft_deps += HRN-02 (adds the requires_structure_runtime check to HRN-02's preflight module)

Spec edits:
- ENG-08: **Ownership boundaries.** Included: add "The requires_structure_runtime Analysis flag and the preflight check that refuses such runs, added to HRN-02's coral/validate/preflight.py with HARNESS-lead review" (RES-037).
- SES-10: **Ownership boundaries.** Included: add "Lifts the requires_structure_runtime preflight refusal at exit, once structured runs pass E2E-5" (RES-037).
- ENG-08: **Dependencies.** Add HRN-02 to the "Soft:" line (adds the requires_structure_runtime check to HRN-02's preflight module; RES-037).
- HRN-02: **Dependencies.** Add ENG-08 to the soft part of "Downstream, unblocks:" (RES-037).
- HRN-02: Ownership boundaries, Excluded: add "the requires_structure_runtime check (ENG-08) and lifting it (SES-10)". (RES-037)
- ENG-08: In eng-b.md, delete the bullet `` - Reviewer note: additive K1 Analysis flag `requires_structure_runtime` (read by HRN-02's preflight) needs ENG-01 and HRN-02 sign-off. `` (resolved by RES-037).

### RES-038 · contract · FND-02, SES-07, WEB-12, ENG-09, WSP-04

The /v1/coral/info sub-feature map gains four keys, each flipped by its owner: slot_refresh (SES-07), scenario_editor (WEB-12), blocks (ENG-09; the blocks router mounts only when on) and sandbox_runs (WSP-04).

Changed by the challenge pass: CH-15.

Master edits:
- FND-02.included: "takeover, restart_from_node, profiles_desk" -> "takeover, restart_from_node, profiles_desk, plus slot_refresh (SES-07), scenario_editor (WEB-12), blocks (ENG-09) and sandbox_runs (WSP-04), each flipped by its owner"
- notes[23]: "takeover, restart_from_node, profiles_desk)" -> "takeover, slot_refresh, restart_from_node, profiles_desk, scenario_editor, blocks, sandbox_runs)"
- K7.description += "Sub-feature keys: editor, canvas_edit, claude_native_steps, codex_steps, webhooks, budgets, takeover, slot_refresh, restart_from_node, profiles_desk, scenario_editor, blocks, sandbox_runs; each owner flips its key at exit."

Spec edits:
- FND-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "takeover, restart_from_node, profiles_desk" so it says "takeover, restart_from_node, profiles_desk, plus slot_refresh (SES-07), scenario_editor (WEB-12), blocks (ENG-09) and sandbox_runs (WSP-04), each flipped by its owner". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-038).
- ENG-09: Implementation breakdown step 5: replace "The router mounts only when enabled." with "The router mounts only when the `blocks` sub-feature key is on (flipped by ENG-09 at exit)." (RES-038)
- SES-07: Implementation breakdown step 5: replace "dark behind `coral.refresh_enabled=false`" with "dark behind the `slot_refresh` sub-feature key". (RES-038)
- WEB-12: Definition of done: add "Merges dark behind the scenario_editor sub-feature key, flipped at exit." (RES-038)
- WSP-04: Definition of done: add "Merges dark behind the `sandbox_runs` sub-feature key, flipped at exit." (RES-038)
- WEB-12: In web-b.md, delete the bullet `` - Reviewer note: no `/v1/coral/info` key covers this editor (DoD 6). It merges dark by staying unmounted. `` (resolved by RES-038).
- WSP-04: In wsp.md, delete the bullet `` - Reviewer note: `sandbox_runs` is not in FND-02's sub-feature map. `` (resolved by RES-038).

Section edits:
- D: D.8 merge-dark table: add rows `slot_refresh` | SES-07 | M4 | no automatic refresh; `scenario_editor` | WEB-12 | M3 | preset Simulate only; `blocks` | ENG-09 | M4 | no saved blocks; `sandbox_runs` | WSP-04 | post-M4 | local hosts only. (RES-038)

### RES-039 · edge · ENG-08, ENG-09, ENG-07

Add soft edges ENG-08 -> ENG-07 and ENG-09 -> ENG-07: both proofs run ENG-07's Simulate and ENG-08 extends its list_len input.

Master edits:
- ENG-08.soft_deps += ENG-07 (proof and Simulate support extend ENG-07's Simulate)
- ENG-09.soft_deps += ENG-07 (proof runs ENG-07's Simulate)

Spec edits:
- ENG-08: **Dependencies.** Add ENG-07 to the "Soft:" line (proof and Simulate support extend ENG-07's Simulate; RES-039).
- ENG-07: **Dependencies.** Add ENG-08 to the soft part of "Downstream, unblocks:" (RES-039).
- ENG-09: **Dependencies.** Add ENG-07 to the "Soft:" line (proof runs ENG-07's Simulate; RES-039).
- ENG-07: **Dependencies.** Add ENG-09 to the soft part of "Downstream, unblocks:" (RES-039).
- ENG-08: In eng-b.md, delete the bullet `` - Reviewer note: the proof and Simulate support extend ENG-07; propose a soft edge ENG-08 -> ENG-07. `` (resolved by RES-039).
- ENG-09: In eng-b.md, delete the bullet `` - Reviewer note: the proof runs ENG-07's Simulate, not a listed dependency; propose a soft edge. `` (resolved by RES-039).

### RES-040 · contract · RUL-03, ENG-09

K15 gives each template a strictness_key and a strictness order in RUL-03's first PR, so ENG-09's V8 can compare inner and outer rules.

Master edits:
- K15.description += "Each template carries a strictness_key and a strictness order (for ENG-09's V8 inner-stricter check), in RUL-03's first PR."
- RUL-03.included: "K15 first PR: template id, params" -> "K15 first PR: template id, strictness_key and order (for V8), params"

Spec edits:
- RUL-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "K15 first PR: template id, params" so it says "K15 first PR: template id, strictness_key and order (for V8), params". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-040).
- ENG-09: In eng-b.md, delete the bullet `` - Reviewer note: V8 needs a strictness order per K15 template, absent from RUL-03's first PR; propose an additive field. `` (resolved by RES-040).
- RUL-03: In rul.md, delete the bullet `` - Reviewer note: `strictness_key` is added for ENG-09's V8 (the eng-b note). `` (resolved by RES-040).

### RES-041 · contract · ENG-01, ENG-11, SES-09, HRN-04

K2 additive taxonomy, ledgered by ENG-01 after IM-0: cause infra.runner_lost (runner-loss origins), the SES-09 drift causes (session_archived, session_deleted, anchor_archived, anchor_deleted, session_stopped, policy_missing, bundle_changed) and a paused_until resume time on paused(plan_limit) (HRN-04).

Master edits:
- K2.description += "Additive after IM-0 (ENG-01 ledgers each): cause infra.runner_lost; drift causes session_archived, session_deleted, anchor_archived, anchor_deleted, session_stopped, policy_missing and bundle_changed; paused_until on paused(plan_limit)."
- ENG-01.included: "error taxonomy (infra.transient, plan.usage_limit, plan.spend_cap, auth)" -> "error taxonomy (infra.transient with cause infra.runner_lost, plan.usage_limit, plan.spend_cap, auth)"

Spec edits:
- ENG-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "error taxonomy (infra.transient, plan.usage_limit, plan.spend_cap, auth)" so it says "error taxonomy (infra.transient with cause infra.runner_lost, plan.usage_limit, plan.spend_cap, auth)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-041).
- SES-09: In ses-b.md, delete the bullet `` - Reviewer note: K2 already has the `user` and `drift` reasons (ENG-01). The cause slugs (`session_archived`, `session_deleted`, `anchor_archived`, `anchor_deleted`, `session_stopped`, `policy_missing`, `bundle_changed`) must join K2's cause set with ENG-01 approval. `` (resolved by RES-041).

### RES-042 · contract · ENG-01, DUR-01, TLS-02, SES-06, SES-08

Slot fields join K2 and DUR-01's coral_0001 slot columns before DUR-01 lands: the evaluating lease (lease_holder, lease_expires_at; X-15), hold_seen_at, restart_attempt_id, last_edge_status, last_turn_outcome and last_edge_at. Edge facts persist as unapplied coral_signals rows plus those columns; no turn_facts table.

Master edits:
- DUR-01.included: "slots with session_generation and closing state" -> "slots with session_generation, closing state, the evaluating lease (lease_holder, lease_expires_at), hold_seen_at, restart_attempt_id and last_edge_status, last_turn_outcome, last_edge_at"
- K2.description += "Slot fields: evaluating lease (lease_holder, lease_expires_at; X-15), hold_seen_at, restart_attempt_id, last_edge_status, last_turn_outcome, last_edge_at."
- K5.description += "Edge facts persist as unapplied coral_signals rows plus the slot last_edge_* columns in coral_0001; there is no separate turn_facts table."

Spec edits:
- DUR-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "slots with session_generation and closing state" so it says "slots with session_generation, closing state, the evaluating lease (lease_holder, lease_expires_at), hold_seen_at, restart_attempt_id and last_edge_status, last_turn_outcome, last_edge_at". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-042).
- DUR-01: In dur.md, delete the bullet `` - Reviewer note: SES-08's "persisted edge facts" have no table in §9. They are resolved here as unapplied `coral_signals` rows plus slot fields in coral_0001, matching the SES-08 spec; otherwise SES-08 needs coral_00NN_turn_facts. `` (resolved by RES-042).
- SES-06: In ses-b.md, delete the bullet `` - Reviewer note: `hold_seen_at` and `restart_attempt_id` need ENG-01 (K2) and DUR-01 approval. `` (resolved by RES-042).
- SES-08: In ses-b.md, delete the bullet `` - Reviewer note: §9 lists no table for edge facts. This spec assumes `coral_signals` plus K2 slot fields (as the DUR spec does); confirm, or add a migration. `` (resolved by RES-042).
- TLS-02: In tls.md, delete the bullet `` - Reviewer note: ENG-04's spec has slot `evaluating`, but neither K2's text nor DUR-01's coral_0001_core gives it a lease expiry (X-15); eng_persistence T16's `lease_expires_at`/`lease_holder` could carry it. Confirm, or add it via the train. `` (resolved by RES-042).

Section edits:
- D: D.6 open items: replace the X-15 bullet with "X-15 resolved: the evaluating lease (lease_holder, lease_expires_at) is a K2 slot field and a coral_0001 column." (RES-042)

### RES-043 · contract · RUL-01, ENG-01, API-02

RUL-01's SessionCapReached observation and ResumeRun.raise_session_cap_usd are additive K2 changes that ENG-01 ledgers by week 5; API-02's resume action accepts the optional raise_session_cap_usd for paused(budget).

Master edits:
- K2.description += "Additive for RUL-01 (by week 5): SessionCapReached observation and ResumeRun.raise_session_cap_usd."
- API-02.included: "pause, resume, cancel and retry actions" -> "pause, resume (with an optional raise_session_cap_usd for paused(budget), RUL-01), cancel and retry actions"

Spec edits:
- API-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "pause, resume, cancel and retry actions" so it says "pause, resume (with an optional raise_session_cap_usd for paused(budget), RUL-01), cancel and retry actions". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-043).
- RUL-01: In rul.md, delete the bullet `` - Reviewer note: `SessionCapReached` and `ResumeRun.raise_session_cap_usd` amend ENG-01's K2; API-02's resume action lacks the field. `` (resolved by RES-043).

### RES-044 · contract · ENG-01, ENG-09, HRN-07, SES-07

Later features add K3 log kinds additively (ENG-09 rule resolution, HRN-07 slot rotation, SES-07 take-over); ENG-01 ledgers each as an additive enum value with no fold change. HRN-07, ENG-09 and SES-07 consume K3.

Changed by the challenge pass: CH-24.

Master edits:
- K3.description += "Later features add kinds additively (ENG-09 rule resolution, HRN-07 slot rotation, SES-07 take-over); ENG-01 ledgers each, with no fold change."
- HRN-07.contracts_consumed += K3; K3.consumers += HRN-07
- ENG-09.contracts_consumed += K3; K3.consumers += ENG-09
- SES-07.contracts_consumed += K3; K3.consumers += SES-07

Spec edits:
- HRN-07: **Dependencies.** Add K3 to the "Contracts: consumes ..." line (RES-044).
- ENG-09: **Dependencies.** Add K3 to the "Contracts: consumes ..." line (RES-044).
- SES-07: **Dependencies.** Add K3 to the "Contracts: consumes ..." line (RES-044).

### RES-045 · nongoal · DUR-06

Legal hold is a non-goal through M4 with no owner (it is not a deferred gap). Retention of Omnigent sessions and transcripts of runs is part of the OQ-25 record (SPK-05) that DUR-06 implements.

Master edits:
- DUR-06.excluded: "Legal hold" -> "Legal hold (non-goal through M4; no owner)"

Spec edits:
- DUR-06: **Ownership boundaries.** Excluded: reword the item covering "Legal hold" so it says "Legal hold (non-goal through M4; no owner)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-045).
- DUR-06: Excluded: replace "legal hold (unowned)" with "legal hold (non-goal through M4)" and "Omnigent sessions and transcripts of runs (unowned; OQ-25)" with "Omnigent sessions and transcripts of runs (decided in the OQ-25 record, SPK-05)". (RES-045)

### RES-046 · fixed · DUR-02, API-02

Test-path layout is settled in the specs (DUR-02 API tests in tests/coral/api/, DUR-04 in tests/coral/workers/, DUR-05 in tests/coral/reconcile/, DUR-01 in tests/db/coral/); the API-02 note is already removed.

### RES-047 · contract · DUR-04, DUR-01

Migration train: coral_0002_queue (DUR-04) holds the queue, timers, effects outbox, signals and the worker lease.

Master edits:
- migration_train[coral_0002_queue (queue, timers)].migration: "coral_0002_queue (queue, timers)" -> "coral_0002_queue (queue, timers, effects, signals, worker lease)"

Spec edits:
- DUR-01: In dur.md, delete the bullet `` - Reviewer note: §9's coral_0002_queue row ("queue, timers") omits effects, signals and the worker lease. `` (resolved by RES-047).
- DUR-04: In dur.md, delete the bullet `` - Reviewer note: the §9 row "coral_0002_queue (queue, timers)" should also name effects, signals and the worker-lease row. `` (resolved by RES-047).

Section edits:
- D: D.6 table row 2: set Contents to "queue, timers, effects outbox, signals, worker lease". (RES-047)

### RES-048 · contract · DUR-06

Migration train: add DUR-06's retention migration (policy and purge jobs), PH4, prerequisite coral_0001, in the weeks 13.5-18 group after notify, because DUR-06 runs weeks 13.5-15.5.

Changed by the challenge pass: CH-13.

Master edits:
- migration_train += {"migration": "retention (policy, purge jobs)", "owner": "DUR-06", "phase": "PH4", "prerequisite": "coral_0001"}

Spec edits:
- DUR-06: In dur.md, delete the bullet `` - Reviewer note: §9 has no DUR-06 migration, but the policy and jobs need `coral_00NN_retention`. `` (resolved by RES-048).

Section edits:
- D: D.6 table: add a row "`retention` | retention policy, purge jobs | DUR-06 | PH4 | coral_0001" after row 16 (`notify`) and before `saved_blocks`; renumber the rows after it. (RES-048)
- H: H.10 migration-train table, row 13.5-18: add ", retention (DUR-06)" after "notify (GTE-03, after alerts)". (RES-048)

### RES-049 · residual · DUR-03, DUR-04

DUR-03 step 3 needs DUR-04's first PR (coral_0002_queue) inside DUR-03's window. No edge can be added (DUR-04 already soft-depends on DUR-03, so the reverse edge forms a cycle). DUR-03 builds step 3 on K5's queue layout and the fake until coral_0002 lands.

Spec edits:
- DUR-03: In dur.md, replace the bullet `` - Reviewer note: step 3 needs DUR-04's first PR (coral_0002_queue) inside DUR-03's window, but the master records only DUR-04's soft dependency on DUR-03, nothing in this direction. A slice dependency "DUR-04#queue-schema" would make that visible to the schedule. `` with `` - Open item (RES-049): Step 3 needs DUR-04's first PR (coral_0002_queue) inside this window. No edge is possible (DUR-04 soft-depends on DUR-03); build step 3 on K5's queue layout and the fake, and merge after coral_0002 lands by week 6. ``.

Section edits:
- J: J.6: add the row "| RES-049 | DUR-03 step 3 needs DUR-04's first PR (coral_0002_queue) inside DUR-03's window. No edge can be added (DUR-04 already soft-depends on DUR-03, so the reverse edge forms a cycle). DUR-03 builds step 3 on K5's queue layout and the fake until coral_0002 lands. | PLATFORM lead (DUR-04) | Week 6 (coral_0002_queue merged) | DUR-03's week-7 finish slips one-for-one if coral_0002 lands after week 6. |".

### RES-050 · citation · DUR-02, WEB-11, BRD-03, WSP-02, EVD-03

Errata for wf1 citations that later sections inherit: get_artifact_store is runtime/__init__.py:120-130 (not 96-106); monacoSetup.ts worker is :52-57 and the "language services unused" comment :9-12 (not 12-17); the shared-runner child helper in test_session_host_launch.py is at :4725 (not 725-742); _decode_fs_request accepts an empty session_id (eng_workspace:116 is wrong); host frame tasks are not cancelled on disconnect (eng_workspace:73 is wrong); iOS maps CFBundleDisplayName in both plists at lines 7-8 (eng_web is wrong); ConversationAlreadyExistsError is raised at sqlalchemy_store.py:1300-1313.

Master edits:
- notes += "RES-050: wf1 errata (wf1 files are not edited): get_artifact_store runtime/__init__.py:120-130; monacoSetup.ts worker :52-57, comment :9-12; shared-runner child helper test_session_host_launch.py:4725; _decode_fs_request accepts an empty session_id; host frame tasks are not cancelled on disconnect; iOS CFBundleDisplayName is mapped in both plists (lines 7-8); ConversationAlreadyExistsError raised at sqlalchemy_store.py:1300-1313; archive idle published at orchestration.py:944."

Spec edits:
- DUR-02: In dur.md, delete the bullet `` - Reviewer note: wf1 cites `get_artifact_store` at `runtime/__init__.py:96-106`. At HEAD it is at `:120-130`. `` (resolved by RES-050).
- WEB-11: In web-b.md, delete the bullet `` - Reviewer note: wf1 (G-70, current_state, eng_web) cites `monacoSetup.ts:12-17` for the worker. At HEAD the worker is `:52-57`; the "language services unused" comment is `:9-12`. `` (resolved by RES-050).

Section edits:
- C: C.0 spot-check table: add rows for get_artifact_store (:120-130), monacoSetup.ts (:52-57 worker, :9-12 comment), test_session_host_launch.py child helper (:4725), _decode_fs_request (empty session_id passes), host frame tasks on disconnect (not cancelled; _quiesce_frame_tasks runs only at shutdown), iOS CFBundleDisplayName (mapped at lines 7-8). (RES-050)

### RES-051 · assign · BRD-02, GTE-03, HRN-04, DUR-06

Coral settings pages (notifications, model access, retention) mount as Coral routes under /workflows/settings/* in BRD-02's coralRoutes fragment. An entry in the upstream Settings nav (closed SettingsSectionId union, settingsNavGroups) is a non-goal.

Master edits:
- BRD-02.included: "for /workflows, /workflows/runs/:runId, /workflows/:workflowKey and /profiles" -> "for /workflows, /workflows/runs/:runId, /workflows/:workflowKey, /workflows/settings/* (Coral settings pages; no upstream Settings nav entry) and /profiles"
- ui_surfaces[Settings: notifications, model access, retention].owner: "GTE-03, HRN-04, DUR-06 (secondary WEB load)" -> "GTE-03, HRN-04, DUR-06 (secondary WEB load), mounted under /workflows/settings/* in BRD-02's route fragment; no upstream Settings nav entry (non-goal)"

Spec edits:
- BRD-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "for /workflows, /workflows/runs/:runId, /workflows/:workflowKey and /profiles" so it says "for /workflows, /workflows/runs/:runId, /workflows/:workflowKey, /workflows/settings/* (Coral settings pages; no upstream Settings nav entry) and /profiles". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-051).
- GTE-03: Frontend: name the mount path /workflows/settings/notifications in BRD-02's fragment (it is already a Coral route). (RES-051)
- HRN-04: Frontend: mount model-access settings at /workflows/settings/model-access via BRD-02's fragment. (RES-051)
- DUR-06: Frontend: mount retention at /workflows/settings/retention via BRD-02's fragment. (RES-051)
- DUR-06: In dur.md, delete the bullet `` - Reviewer note: no feature or seam owns a Coral entry in the closed settings union (`web/src/shell/settingsNav.tsx:37-74` `SettingsSectionId`, used by `web/src/pages/SettingsPage.tsx:326-401`); HRN-04 lists `web/src/workflows/settings/` but no shell. `` (resolved by RES-051).

### RES-052 · assign · OPS-07, SES-05, WEB-01

OPS-07 owns the CI-only real-server browser lane (tests/e2e_ui/workflows/) that IM-4 needs, including a real-trace diagram row for WEB-01. OPS-07 owns the IM-3 and IM-4 tests; the WEB lead owns IM-4 convergence. SES-05's browser E2E is OPS-07's lane.

Master edits:
- OPS-07.included += "The CI-only real-server browser lane (tests/e2e_ui/workflows/) for IM-4, with a real-trace diagram row for WEB-01; never run locally"
- OPS-07.included: "Owns IM-3 and IM-4;" -> "Owns the IM-3 and IM-4 tests (the WEB lead owns IM-4 convergence);"
- SES-05.excluded: "Browser E2E" -> "Browser E2E (OPS-07's CI-only IM-4 lane)"
- notes += "RES-052: DoD 6.1 rule 7 reading: real-server browser rows run in the CI-only tests/e2e_ui/ lane (OPS-07); component rows stay in tests/browser_ui/workflows/."

Spec edits:
- OPS-07: **Ownership boundaries.** Included: add "The CI-only real-server browser lane (tests/e2e_ui/workflows/) for IM-4, with a real-trace diagram row for WEB-01; never run locally" (RES-052).
- OPS-07: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Owns IM-3 and IM-4;" so it says "Owns the IM-3 and IM-4 tests (the WEB lead owns IM-4 convergence);". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-052).
- SES-05: **Ownership boundaries.** Excluded: reword the item covering "Browser E2E" so it says "Browser E2E (OPS-07's CI-only IM-4 lane)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-052).
- SES-05: Excluded: replace "browser E2E (CI-only lane, OPS-07)" with "browser E2E (OPS-07's CI-only IM-4 lane, tests/e2e_ui/workflows/)". (RES-052)
- WEB-01: Definition of done: add "a real-trace row runs in OPS-07's IM-4 lane". (RES-052)
- OPS-07: In ops-b.md, delete the bullet `` - Reviewer note: IM-4 needs the real-server `tests/e2e_ui/` lane; DoD rule 7 names only `tests/browser_ui/`. `` (resolved by RES-052).
- WEB-01: In web-a.md, delete the bullet `` - Reviewer note: WEB-01 finishes in week 5, before DUR-02 and ENG-07, so the proof uses fixture traces. Add a real-trace row to IM-4 (OPS-07). `` (resolved by RES-052).

### RES-053 · edge · SES-04, SES-03, DUR-01

Add soft edge SES-04 -> DUR-01 (K5, K21 and coral_0001 for stable_ids). The session_bindings migration prerequisite becomes "ADR-05; coral_0001". coral_0001 must merge by week 4 so SES-03 and SES-04 can land their migrations; a hard edge would warn (DUR-01 ends week 5).

Master edits:
- SES-04.soft_deps += DUR-01 (K5, K21 and coral_0001 (stable_ids prerequisite))
- migration_train[session_bindings].prerequisite: "ADR-05" -> "ADR-05; coral_0001"

Spec edits:
- SES-04: **Dependencies.** Add DUR-01 to the "Soft:" line (K5, K21 and coral_0001 (stable_ids prerequisite); RES-053).
- DUR-01: **Dependencies.** Add SES-04 to the soft part of "Downstream, unblocks:" (RES-053).
- SES-03: In ses-a.md, replace the bullet `` - Reviewer note: DUR-01 is soft, and §9 lists only ADR-05 as the bindings prerequisite, yet the single-head train (DoD 3) needs `coral_0001` (week 5). `` with `` - Open item (RES-053): DUR-01 stays soft (a hard edge would start before it ends), and the single-head train needs `coral_0001` before the bindings migration; coral_0001 must merge by week 4 (tracked in J.6). ``.
- SES-04: In ses-a.md, delete the bullet `` - Reviewer note: SES-04 consumes K5 and K21 and its migration needs `coral_0001` (§9), all from DUR-01 (weeks 3-5), with no edge; recommend soft SES-04 -> DUR-01. `` (resolved by RES-053).

Section edits:
- D: D.6 table row 3: set the session_bindings prerequisite to "ADR-05; coral_0001". (RES-053)
- H: H.10 migration-train timing: state "coral_0001 merges by week 4" as a dated rule. (RES-053)
- J: J.6: add the row "| RES-053 | Add soft edge SES-04 -> DUR-01 (K5, K21 and coral_0001 for stable_ids). The session_bindings migration prerequisite becomes "ADR-05; coral_0001". coral_0001 must merge by week 4 so SES-03 and SES-04 can land their migrations; a hard edge would warn (DUR-01 ends week 5). | DUR-01 (PLATFORM lead) | Week 4 (coral_0001_core merged) | SES-03's session_bindings and SES-04's stable_ids migrations cannot merge on the single-head train before coral_0001; SES-04 (ends week 5) slips one-for-one. |".

### RES-054 · contract · SES-02, SES-08, SES-01

K18 names the four origin sites: the relay recovery turn end B1 (orchestration.py:9565-9582), the status-probe notify, the archive idle edge (published at orchestration.py:944 in _stop_host_runner_intentionally) and the runner-disconnect edge. The main relay headless edge (orchestration.py:9583) stays "unknown" and relies on turn_outcome (S43).

Master edits:
- K18.description += "Origin is set at four sites: the relay recovery turn end (B1, orchestration.py:9565-9582), the status-probe notify, the archive idle edge (orchestration.py:944) and the runner-disconnect edge; the main relay edge (orchestration.py:9583) stays unknown and relies on turn_outcome."
- SES-02.included: "set only at the relay turn end" -> "set only at the relay recovery turn end (B1)"

Spec edits:
- SES-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "set only at the relay turn end" so it says "set only at the relay recovery turn end (B1)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-054).
- SES-02: In ses-a.md, delete the bullet `` - Reviewer note: "relay turn end" is read as B1, per the master's "B1 (relay turn-end)"; the main relay edge (9583) stays `unknown` and relies on `turn_outcome`. Confirm with SES-08. `` (resolved by RES-054).

### RES-055 · citation · SES-02

Hot-file order correction: the archive-idle origin is set in orchestration.py (published at :944 via _archive_stop, :1027), not routes_events.py.

Changed by the challenge pass: CH-15.

Master edits:
- notes += "RES-055: Hot-file order amendment (§6.5): the archive-idle origin lands in omnigent/server/routes/_sessions/orchestration.py (published at :944 in _stop_host_runner_intentionally, via _archive_stop at :1027), not routes_events.py; stop_session's branch in routes_events.py keeps the default."

Spec edits:
- SES-02: In ses-a.md, delete the bullet `` - Reviewer note: §6.5 puts the archive-idle origin in `routes_events.py`; at HEAD it is `orchestration.py:944` (via `_archive_stop`, 1027), and `stop_session` (`routes_events.py:2124`) keeps the default. `` (resolved by RES-055).

Section edits:
- D: D.8 hot-file table, `_sessions/orchestration.py` row: replace "SES-02: S1 bypasses, S43" with "SES-02: S1 bypasses, archive-idle origin, S43" (the routes_events.py row already omits it). (RES-055)
- H: H.4 hot-file table: in the `server/routes/sessions/routes_events.py` row replace "SES-02 S42 and the archive-idle origin, then GTE-05 S6a" with "SES-02 S42, then GTE-05 S6a"; in the `server/routes/_sessions/orchestration.py` row replace "SES-02 S1 bypasses and S43" with "SES-02 S1 bypasses, the archive-idle origin and S43". (RES-055)
- V: V.10 writer note: mark the archive-idle citation as corrected in master v3. (RES-055)

### RES-056 · edge · SES-02, SES-01

Add soft edge SES-02 -> SES-01: SES-02 implements K18 in the same weeks SES-01 freezes it.

Master edits:
- SES-02.soft_deps += SES-01 (implements K18 while SES-01 freezes it)

Spec edits:
- SES-02: **Dependencies.** Add SES-01 to the "Soft:" line (implements K18 while SES-01 freezes it; RES-056).
- SES-01: **Dependencies.** Add SES-02 to the soft part of "Downstream, unblocks:" (RES-056).
- SES-01: In ses-a.md, replace the line `` - Concurrent, coordinate with: none in feature_context.json; SES-02 implements K18 concurrently (Reviewer note). `` with `` - Concurrent, coordinate with: SES-02, which implements K18 in the same weeks (soft edge SES-02 -> SES-01). `` (RES-056).
- SES-01: In ses-a.md, delete the bullet `` - Reviewer note: SES-02 consumes K18 in the same weeks with no edge and no listed coordination; recommend a soft edge SES-02 -> SES-01. `` (resolved by RES-056).
- SES-02: In ses-a.md, delete the bullet `` - Reviewer note: K18 is consumed with no edge to SES-01. `` (resolved by RES-056).

### RES-057 · edge · SES-03, TLS-01

Add soft edge SES-03 -> TLS-01: SES-03 refuses hosts without the coral_runner token, which TLS-01 adds; tests use a fake host hello until TLS-01 lands (week 3).

Master edits:
- SES-03.soft_deps += TLS-01 (coral_runner token on HostHelloFrame)

Spec edits:
- SES-03: **Dependencies.** Add TLS-01 to the "Soft:" line (coral_runner token on HostHelloFrame; RES-057).
- TLS-01: **Dependencies.** Add SES-03 to the soft part of "Downstream, unblocks:" (RES-057).
- SES-03: In ses-a.md, delete the bullet `` - Reviewer note: TLS-01 adds the token to `HostHelloFrame.capabilities` but is not a dependency; until it lands (planned weeks 1-3), every host is refused. `` (resolved by RES-057).

### RES-058 · edge · SES-04, FND-04

SES-04 closes its feature proof on Tier A (K13 fake, injected SubmitHandoff) at week 5; the Tier B queued-input variant runs as its IM-2 exit item. Add soft edge SES-04 -> FND-04. Until SES-08 lands, SES-04 detects post-close turns through a narrow observer in SES-02's registry.

Master edits:
- SES-04.soft_deps += FND-04 (Tier B scaffolding for the queued-input variant)
- notes += "RES-058: SES-04's proving test closes on Tier A at week 5 (K13 fake, injected SubmitHandoff); its Tier B queued-input variant is an IM-2 exit item (week 11.5)."

Spec edits:
- SES-04: **Dependencies.** Add FND-04 to the "Soft:" line (Tier B scaffolding for the queued-input variant; RES-058).
- FND-04: **Dependencies.** Add SES-04 to the soft part of "Downstream, unblocks:" (RES-058).
- SES-04: In ses-a.md, replace the bullet `` - Reviewer note: the Tier B proof needs TLS-02 and WSP-06 (weeks 7-9) plus FND-04, which is not a dependency, yet SES-04 ends at week 5. Recommend closing on Tier A with the K13 fake and an injected SubmitHandoff, and making the Tier B proof an IM-2 exit item. `` with `` - Open item (RES-058): The Tier B proof needs TLS-02 and WSP-06 (weeks 7-9) and FND-04 (now a soft dependency), so this feature closes on Tier A with the K13 fake and an injected SubmitHandoff, and the Tier B variant is its IM-2 exit item (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-058 | SES-04 closes its feature proof on Tier A (K13 fake, injected SubmitHandoff) at week 5; the Tier B queued-input variant runs as its IM-2 exit item. Add soft edge SES-04 -> FND-04. Until SES-08 lands, SES-04 detects post-close turns through a narrow observer in SES-02's registry. | SES-04 (INTEGRATION lead) | IM-2, week 11.5 | The Tier B queued-input proof (M2 exit 7) is shown only at IM-2. |".

### RES-059 · edge · SES-05, API-02, PRF-01

Add soft edges SES-05 -> API-02 (run start) and SES-05 -> PRF-01 (inert anchor agent and step bundle); SES-05 keeps a test-only start hook and test agents until they land.

Master edits:
- SES-05.soft_deps += API-02 (run start endpoint)
- SES-05.soft_deps += PRF-01 (inert anchor agent and step bundle)

Spec edits:
- SES-05: **Dependencies.** Add API-02 to the "Soft:" line (run start endpoint; RES-059).
- API-02: **Dependencies.** Add SES-05 to the soft part of "Downstream, unblocks:" (RES-059).
- SES-05: **Dependencies.** Add PRF-01 to the "Soft:" line (inert anchor agent and step bundle; RES-059).
- PRF-01: **Dependencies.** Add SES-05 to the soft part of "Downstream, unblocks:" (RES-059).
- SES-05: In ses-a.md, delete the bullet `` - Reviewer note: there is no edge to API-02 (run start) or PRF-01 (the inert agent and step bundle), so a test-only start hook and test agents are needed until those land. `` (resolved by RES-059).

### RES-060 · split · PRF-01, SES-09, PRF-02

Slot-start drift: PRF-01 checks the pinned bundle digest, re-puts a missing blob and returns the digest; SES-09 alone decides to pause (paused(drift)) on policy, label or digest drift; PRF-02 records profile_changed on a revision mismatch and never pauses.

Master edits:
- PRF-01.included: "slot-start drift check (spike 18)" -> "slot-start bundle check (spike 18): compare the pinned digest, re-put a missing blob, return the digest"
- SES-09.included: "Drift checks (policy, label, bundle digest) at resync and slot start, then re-attach or paused(drift)" -> "Drift checks (policy, label, and PRF-01's bundle-digest result) at resync and slot start, then re-attach or paused(drift); only SES-09 pauses"
- PRF-02.included: "drift check at slot start" -> "revision-pin check at slot start that records profile_changed (never pauses)"
- failure_modes[Drift (policy, archive, bundle); native /clear].owner: "SES-09 drift checks; PRF-01 digest check; HRN-07 via S45" -> "SES-09 drift checks and the pause; PRF-01 digest check; PRF-02 revision notice; HRN-07 via S45"

Spec edits:
- PRF-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "slot-start drift check (spike 18)" so it says "slot-start bundle check (spike 18): compare the pinned digest, re-put a missing blob, return the digest". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-060).
- SES-09: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Drift checks (policy, label, bundle digest) at resync and slot start, then re-attach or paused(drift)" so it says "Drift checks (policy, label, and PRF-01's bundle-digest result) at resync and slot start, then re-attach or paused(drift); only SES-09 pauses". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-060).
- PRF-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "drift check at slot start" so it says "revision-pin check at slot start that records profile_changed (never pauses)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-060).
- SES-09: In ses-b.md, delete the bullet `` - Reviewer note: the master gives slot-start drift checks to both SES-09 and PRF-01 (spike 18). This spec splits them: PRF-01 compares the bundle, and SES-09 pauses. `` (resolved by RES-060).

### RES-061 · contract · SES-07, SES-01, HRN-07

SES-07's take-over and hand-back endpoints are additive K7 routes, so SES-07 consumes K7; supersede() is an additive K4 change signed by SES-01 (with HRN-07's on_supersession and label query).

Master edits:
- SES-07.contracts_consumed += K7; K7.consumers += SES-07
- K4.description += "Additive after IM-0 (SES-01 signs): sessions.supersede() for SES-07, and on_supersession plus a label query for HRN-07."
- K7.description += "Take-over and hand-back endpoints (SES-07) are additive; a typed not_permitted returns HTTP 403."

Spec edits:
- SES-07: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-061).
- SES-07: In ses-b.md, delete the bullet `` - Reviewer notes: the endpoints change K7, which this feature does not consume; `supersede` changes K4 additively (SES-01 approval); add a `refresh` key to `/v1/coral/info`. `` (resolved by RES-061).

### RES-062 · assign · WEB-10, SES-10, GTE-02

The batched gate card is WEB-10's (WS-WEB, M4, weeks 17.5-22): GTE-02's WorkflowInboxCard extended with a per-item list for SES-10's K14 batch payload, reusing the run view's per-item list. SES-10 keeps per-item gates and batching on GTE-01. GTE-02 excludes the card.

Changed by the challenge pass: CH-02.

Master edits:
- SES-10.included: "Per-item gates and gate batching on GTE-01 with the K14 batch payload" -> "Per-item gates and gate batching on GTE-01 with the K14 batch payload (the batched card is WEB-10's)"
- SES-10.excluded += "Batched gate card UI (WEB-10)"
- WEB-10.included += "Batched gate card: GTE-02's WorkflowInboxCard extended with a per-item list for SES-10's K14 batch payload, sharing the run view's per-item list"
- WEB-10.contracts_consumed += K14; K14.consumers += WEB-10
- WEB-10.soft_deps += GTE-02 (extends WorkflowInboxCard for batched gates)
- GTE-02.excluded += "Batched gate card (WEB-10, M4)"
- ui_surfaces[Inbox workflow kind and gate card].states += ", batched gate with a per-item list (WEB-10, M4)"

Spec edits:
- SES-10: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Per-item gates and gate batching on GTE-01 with the K14 batch payload" so it says "Per-item gates and gate batching on GTE-01 with the K14 batch payload (the batched card is WEB-10's)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-062).
- SES-10: **Ownership boundaries.** Excluded: add "Batched gate card UI (WEB-10)" (RES-062).
- WEB-10: **Ownership boundaries.** Included: add "Batched gate card: GTE-02's WorkflowInboxCard extended with a per-item list for SES-10's K14 batch payload, sharing the run view's per-item list" (RES-062).
- WEB-10: **Dependencies.** Add K14 to the "Contracts: consumes ..." line (RES-062).
- WEB-10: **Dependencies.** Add GTE-02 to the "Soft:" line (extends WorkflowInboxCard for batched gates; RES-062).
- GTE-02: **Dependencies.** Add WEB-10 to the soft part of "Downstream, unblocks:" (RES-062).
- GTE-02: **Ownership boundaries.** Excluded: add "Batched gate card (WEB-10, M4)" (RES-062).
- GTE-02: Excluded: add "batched gate card (WEB-10, M4)". (RES-062)
- SES-10: In ses-b.md, delete the bullet `` - Reviewer note: no feature owns a dedicated batch-gate card. `` (resolved by RES-062).

### RES-063 · residual · SES-06, SES-09

SES-06 and SES-09 finish at week 9.5 but their proving tests need DUR-05 and SES-08 (ending 11.5 and 11), so they close at IM-3 (week 11.5). No schedule change.

Spec edits:
- SES-06: In ses-b.md, replace the bullet `` - Reviewer note: DUR-05 and SES-08 finish after week 9.5, so the proving test closes at IM-3. `` with `` - Open item (RES-063): DUR-05 and SES-08 finish after week 9.5, so the proving test closes at IM-3 (week 11.5; tracked in J.6). ``.
- SES-09: In ses-b.md, replace the bullet `` - Reviewer note: DUR-05 finishes at week 11.5, so the proving test closes at IM-3. `` with `` - Open item (RES-063): DUR-05 finishes at week 11.5, so the proving test closes at IM-3 (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-063 | SES-06 and SES-09 finish at week 9.5 but their proving tests need DUR-05 and SES-08 (ending 11.5 and 11), so they close at IM-3 (week 11.5). No schedule change. | SES-06 and SES-09 (INTEGRATION lead) | IM-3, week 11.5 | Feature exits are recorded at IM-3; a slip in DUR-05 or SES-08 delays both exits. |".

### RES-064 · assign · SES-10, WSP-03, WSP-07

SES-10 exits at week 16 with E2E-5 on WSP-03 and WSP-07 fakes. INT-T2, its track, has no other work after week 16 (H.1), so the same engineer carries the IM-7 convergence tail to week 22.5: E2E-5 is re-run against RUL-03's templates (week 18), WSP-07's push (20) and WSP-03's merges (22.5). No split and no new staffing; the IM-7 date stays a tracked risk.

Changed by the challenge pass: CH-20.

Master edits:
- SES-10.included += "IM-7 convergence tail on INT-T2 (weeks 16-22.5): re-runs E2E-5 against RUL-03 templates, WSP-07 push and WSP-03 merges as they land; the week-16 feature exit uses their fakes"

Spec edits:
- SES-10: **Ownership boundaries.** Included: add "IM-7 convergence tail on INT-T2 (weeks 16-22.5): re-runs E2E-5 against RUL-03 templates, WSP-07 push and WSP-03 merges as they land; the week-16 feature exit uses their fakes" (RES-064).
- SES-10: Definition of done: replace "The IM-7 test is green." with "The IM-7 test is green at the end of the INT-T2 tail (week 22.5); the week-16 feature exit runs E2E-5 with WSP-03 and WSP-07 fakes." (RES-064)
- SES-10: In ses-b.md, replace the bullet `` - Reviewer note: week 16 comes before WSP-03 (week 22.5), WSP-07 (week 20), RUL-03 (week 18) and IM-7 (week 22.5). Split this feature or extend it. `` with `` - Open item (RES-064): This feature exits at week 16 on WSP-03 and WSP-07 fakes; INT-T2 carries E2E-5 to IM-7 (week 22.5) as RUL-03 (18), WSP-07 (20) and WSP-03 (22.5) land (master v3; the IM-7 date is tracked in J.6). ``.
- WSP-03: In wsp.md, replace the bullet `` - Reviewer note: SES-10 (weeks 14-16) soft-depends on WSP-03 and WSP-07, which start in week 18. `` with `` - SES-10 (weeks 14-16) uses fakes for WSP-03 and WSP-07 (from week 18); the real runs are its IM-7 tail on INT-T2 (master v3). `` (no longer a reviewer note; settled by RES-064).

Section edits:
- H: H.1 track table, INT-T2 row: replace "SES-08 9-11, SES-10 14-16" with "SES-08 9-11, SES-10 14-16, then the IM-7 convergence tail to 22.5". (RES-064)
- I: I.8 "Risks to the date." list: add a bullet "- **IM-7 tail.** SES-10 exits at week 16 on fakes; INT-T2 re-runs E2E-5 as RUL-03 (18), WSP-07 (20) and WSP-03 (22.5) land. A WSP-03 slip moves IM-7 (J.6, RES-064)." (RES-064)
- J: J.6: add the row "| RES-064 | SES-10 exits at week 16 with E2E-5 on WSP-03 and WSP-07 fakes. INT-T2, its track, has no other work after week 16 (H.1), so the same engineer carries the IM-7 convergence tail to week 22.5: E2E-5 is re-run against RUL-03's templates (week 18), WSP-07's push (20) and WSP-03's merges (22.5). No split and no new staffing; the IM-7 date stays a tracked risk. | INTEGRATION lead (SES-10) | IM-7, week 22.5 | E2E-5 runs on real merges and push only at IM-7; a WSP-03 or WSP-07 slip delays IM-7 and the M4 journey. |".

### RES-065 · edge · SES-08, ENG-06

Add soft edge SES-08 -> ENG-06: the plan-limit probe uses ENG-06's timer kinds.

Master edits:
- SES-08.soft_deps += ENG-06 (timer kinds for the plan-limit probe)

Spec edits:
- SES-08: **Dependencies.** Add ENG-06 to the "Soft:" line (timer kinds for the plan-limit probe; RES-065).
- ENG-06: **Dependencies.** Add SES-08 to the soft part of "Downstream, unblocks:" (RES-065).
- SES-08: In ses-b.md, delete the bullet `` - Reviewer note: the probe timer uses ENG-06's timer kinds; ENG-06 (finishes week 9.5) is not in SES-08's master deps. `` (resolved by RES-065).

### RES-066 · contract · SES-01, SES-08, HRN-03, HRN-04, HRN-07

K18 TurnFacts gain an optional response_id (keyed (session, response_id)) for HRN-03's level-triggered fallback, a resets_at field for HRN-04, and a supersession observer hook for HRN-07; all additive, signed by SES-01 with SES-08.

Master edits:
- K18.description += "Additive: TurnFact response_id (keyed by session and response_id) for HRN-03's fallback, resets_at for HRN-04, and a supersession observer hook for HRN-07; SES-01 signs with SES-08."

Spec edits:
- HRN-03: In prf-hrn.md, delete the bullet `` - Reviewer note: SES-08 keys facts on `observed_at_ms`; the fallback needs a response-id key, an additive K18 change to coordinate with SES-08. `` (resolved by RES-066).

### RES-067 · assign · SES-06, SES-07

If spike 16 fails, the whole S27 seam moves to SES-06, including the coral.keep_alive label exemption, not only the retest.

Changed by the challenge pass: CH-25.

Master edits:
- SES-06.included += "If spike 16 fails: the whole S27 seam (reaper retest and the coral.keep_alive label exemption) moves here from SES-07"
- SES-06.conditional_deps: "owns the S27 reaper retest at M2 (moved from SES-07)" -> "owns the whole S27 seam at M2 (the reaper retest and the coral.keep_alive label exemption, moved from SES-07)"

Spec edits:
- SES-06: **Ownership boundaries.** Included: add "If spike 16 fails: the whole S27 seam (reaper retest and the coral.keep_alive label exemption) moves here from SES-07" (RES-067).
- SES-06: **Dependencies.** "Slice and conditional:" line: reword the condition covering "owns the S27 reaper retest at M2 (moved from SES-07)" so it says "owns the whole S27 seam at M2 (the reaper retest and the coral.keep_alive label exemption, moved from SES-07)" (RES-067).
- SES-06: In ses-b.md, delete the bullet `` - Reviewer note: §7's conditional-owner line moves all of S27 to SES-06 if spike 16 fails (as §6.5 does), so SES-06 would also own the `coral.keep_alive` exemption; conditional_deps names only the retest. Confirm. `` (resolved by RES-067).

### RES-068 · nongoal · TLS-04, TLS-05

Reusing sys_session_message (TLS-04) and step agents asking the user directly (TLS-05, OQ-13 default) are non-goals with no owner; PRF-01 denies vendor ask tools and GTE-02 shows "Step waiting on you".

Changed by the challenge pass: CH-15.

Master edits:
- TLS-04.excluded: "sys_session_message reuse" -> "sys_session_message reuse (non-goal)"
- TLS-05.excluded: "Step agents asking directly (OQ-13 default: no)" -> "Step agents asking directly (non-goal, OQ-13; PRF-01 denies vendor ask tools and GTE-02 shows 'Step waiting on you')"

### RES-069 · assign · SES-10, TLS-04

Tier B multi-session coverage of the messaging tools goes to SES-10's E2E-5: one coral_message_agent exchange between the two real sessions. Add soft edge SES-10 -> TLS-04 (TLS-04 ends week 15.5, inside SES-10's window).

Changed by the challenge pass: CH-06.

Master edits:
- SES-10.included: "E2E-5 only at the boundary of two real concurrent sessions submitting" -> "E2E-5 only at the boundary of two real concurrent sessions submitting, including one coral_message_agent exchange between them"
- TLS-04.excluded += "Tier B multi-session messaging coverage (SES-10's E2E-5)"
- SES-10.soft_deps += TLS-04 (coral_message_agent for the E2E-5 exchange)

Spec edits:
- SES-10: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "E2E-5 only at the boundary of two real concurrent sessions submitting" so it says "E2E-5 only at the boundary of two real concurrent sessions submitting, including one coral_message_agent exchange between them". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-069).
- TLS-04: **Ownership boundaries.** Excluded: add "Tier B multi-session messaging coverage (SES-10's E2E-5)" (RES-069).
- SES-10: **Dependencies.** Add TLS-04 to the "Soft:" line (coral_message_agent for the E2E-5 exchange; RES-069).
- TLS-04: **Dependencies.** Add SES-10 to the soft part of "Downstream, unblocks:" (RES-069).
- TLS-04: Technical scope: replace "Tier B multi-session coverage stays in SES-10 and OPS-09" with "Tier B multi-session coverage is SES-10's E2E-5 (one coral_message_agent exchange)". (RES-069)

### RES-070 · assign · TLS-01

S49 ("Up: Yes") ships in S10's upstream PR; TLS-01's upstream PR list says so.

Master edits:
- TLS-01.included: "upstream PRs for S10, S12 and S50" -> "upstream PRs for S10 (carrying S49), S12 and S50 (carrying S7 and S8)"

Spec edits:
- TLS-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "upstream PRs for S10, S12 and S50" so it says "upstream PRs for S10 (carrying S49), S12 and S50 (carrying S7 and S8)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-070).
- TLS-01: In tls.md, delete the bullet `` - Reviewer note: S49 is "Up: Yes", but the master lists upstream PRs only for S10, S12, S50; folded into the S10 PR. `` (resolved by RES-070).

### RES-071 · edge · TLS-01, FND-02

Add soft edge TLS-01 -> FND-02 (K17): step 5 merges after FND-02's PluginRegistration PR.

Master edits:
- TLS-01.soft_deps += FND-02 (K17 process map and token definition)

Spec edits:
- TLS-01: **Dependencies.** Add FND-02 to the "Soft:" line (K17 process map and token definition; RES-071).
- FND-02: **Dependencies.** Add TLS-01 to the soft part of "Downstream, unblocks:" (RES-071).
- TLS-01: In tls.md, delete the bullet `` - Reviewer note: K17 is consumed without an FND-02 edge; step 5 merges after FND-02's PluginRegistration PR (suggest soft dependency). `` (resolved by RES-071).

### RES-072 · edge · TLS-03, SES-06

Add soft edge SES-06 -> TLS-03: SES-06's ladder ends by briefing the new generation, and for an orchestrator that brief is TLS-03's re-brief (TLS-03 ends week 7.5, when SES-06 starts). TLS-03 consumes K10 (coral.role) and K4 (create and send).

Changed by the challenge pass: CH-05.

Master edits:
- SES-06.soft_deps += TLS-03 (the ladder's brief step re-briefs a restarted orchestrator with TLS-03's renderer)
- TLS-03.contracts_consumed += K10; K10.consumers += TLS-03
- TLS-03.contracts_consumed += K4; K4.consumers += TLS-03

Spec edits:
- SES-06: **Dependencies.** Add TLS-03 to the "Soft:" line (the ladder's brief step re-briefs a restarted orchestrator with TLS-03's renderer; RES-072).
- TLS-03: **Dependencies.** Add SES-06 to the soft part of "Downstream, unblocks:" (RES-072).
- TLS-03: **Dependencies.** Add K10 to the "Contracts: consumes ..." line (RES-072).
- TLS-03: **Dependencies.** Add K4 to the "Contracts: consumes ..." line (RES-072).
- TLS-03: In tls.md, delete the bullet `` - Reviewer note: SES-06's ladder triggers the re-brief but is not a dependency. K10 (`coral.role`) and K4 (create and send) are used but not listed as consumed. `` (resolved by RES-072).

### RES-073 · split · TLS-04, WSP-03

TLS-04 owns coral_assign_task and fakes the conflict sub-state until IM-7; WSP-03 owns the conflict sub-state and calls TLS-04's real tool (TLS-04 lands first, weeks 13.5-15.5). WSP-03's "fake assign_task until TLS-04 lands" is wrong.

Spec edits:
- WSP-03: Implementation breakdown step 5: replace "The conflict sub-state, using a fake `assign_task` until TLS-04 lands." with "The conflict sub-state, calling TLS-04's `coral_assign_task` (landed by week 15.5)." (RES-073)
- TLS-04: In tls.md, replace the bullet `` - Reviewer note: the conflict sub-state comes from WSP-03 (weeks 18-22.5), which starts after TLS-04, so the worktree proof uses a fake until IM-7. `` with `` - The conflict sub-state comes from WSP-03 (weeks 18-22.5), which starts after TLS-04, so the worktree proof uses a faked sub-state until IM-7. `` (no longer a reviewer note; settled by RES-073).

### RES-074 · edge · TLS-05, ENG-06, GTE-06

Add soft edge TLS-05 -> ENG-06 (watchdog suspension) and K2 to TLS-05's consumed contracts. The questions migration no longer needs the alerts table: its prerequisite becomes "coral_0001; K19 (no foreign key to alerts)", so TLS-05's week-9 migration does not wait for GTE-06.

Changed by the challenge pass: CH-15.

Master edits:
- TLS-05.soft_deps += ENG-06 (watchdog suspension while a question is open)
- TLS-05.contracts_consumed += K2; K2.consumers += TLS-05
- migration_train[questions].prerequisite: "alerts" -> "coral_0001; K19 (no foreign key to alerts)"

Spec edits:
- TLS-05: **Dependencies.** Add ENG-06 to the "Soft:" line (watchdog suspension while a question is open; RES-074).
- ENG-06: **Dependencies.** Add TLS-05 to the soft part of "Downstream, unblocks:" (RES-074).
- TLS-05: **Dependencies.** Add K2 to the "Contracts: consumes ..." line (RES-074).
- TLS-05: In tls.md, delete the bullet `` - Reviewer note: the proof depends on ENG-06's watchdog and on K2, neither of which is a dependency; a soft dependency on ENG-06 is suggested. `` (resolved by RES-074).
- TLS-05: In tls.md, delete the bullet `` - Reviewer note: the migration train sets "alerts" as this table's prerequisite, but GTE-06 (starting week 9.5) is only a soft dependency, and this table's first PR is week 9. `` (resolved by RES-074).

Section edits:
- D: D.6 table row 10: set the questions prerequisite to "coral_0001; K19 (no foreign key to alerts)". (RES-074)
- H: H.10 migration-train table, row 9.5-11.5: replace "alerts (GTE-06, first PR at 9.5), then questions (TLS-05; its window opens at 9 but it lands after alerts)" with "alerts (GTE-06, first PR at 9.5); questions (TLS-05, from week 9; no foreign key to alerts, so it does not wait for alerts)". (RES-074)

### RES-075 · assign · GTE-06, ENG-04, ENG-06

GTE-06 adds the gate-open, run_completed and run_failed notify emitters as a small reducer PR reviewed by ENG-04's owner; ENG-06's cancel transition keeps the run_cancelled notify it already emits (eng-a.md, Cancel); ENG-04 emits only publish_gate and withdraw_gate. GTE-06 turns all of them into alerts. ENG-04 and ENG-06 owners sign off in that PR.

Changed by the challenge pass: CH-18.

Master edits:
- GTE-06.included: "Producers: gates, questions, pauses, watchdog;" -> "Producers: alerts for gate-open, question, pause, watchdog and run-end notify effects; GTE-06 adds the gate-open, run_completed and run_failed emitters as a small reducer PR reviewed by ENG-04's owner (ENG-06's cancel transition already emits run_cancelled);"
- ENG-04.excluded += "Gate-open, run_completed and run_failed notify effects (GTE-06)"
- ENG-06.included: "Cancel transition that emits one K21 cancel_sessions effect per live slot (I8)" -> "Cancel transition that emits one K21 cancel_sessions effect per live slot (I8) plus the run_cancelled K19 notify,"
- ENG-06.excluded += "Gate-open, run_completed and run_failed notify effects (GTE-06)"

Spec edits:
- GTE-06: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Producers: gates, questions, pauses, watchdog;" so it says "Producers: alerts for gate-open, question, pause, watchdog and run-end notify effects; GTE-06 adds the gate-open, run_completed and run_failed emitters as a small reducer PR reviewed by ENG-04's owner (ENG-06's cancel transition already emits run_cancelled);". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-075).
- ENG-04: **Ownership boundaries.** Excluded: add "Gate-open, run_completed and run_failed notify effects (GTE-06)" (RES-075).
- ENG-06: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Cancel transition that emits one K21 cancel_sessions effect per live slot (I8)" so it says "Cancel transition that emits one K21 cancel_sessions effect per live slot (I8) plus the run_cancelled K19 notify,". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-075).
- ENG-06: **Ownership boundaries.** Excluded: add "Gate-open, run_completed and run_failed notify effects (GTE-06)" (RES-075).
- GTE-06: Implementation breakdown step 5: replace "Gate and run-end producers (reducer PR)" with "Gate-open, run_completed and run_failed producers (reducer PR; ENG-06's cancel transition emits run_cancelled)". Ownership boundaries, Included: replace "gate and run-end producers" with "gate-open, run_completed and run_failed producers". (RES-075)
- GTE-06: In gte.md, delete the bullet `` - Reviewer note: no master feature emits gate-open or run-end `notify` effects; this spec takes them per "Producers: gates", touching ENG-04's reducer. `` (resolved by RES-075).

### RES-076 · nongoal · GTE-02, GTE-03, GTE-04

Non-goals with no owner: localStorage read state (server-side ack, X-30), Slack-originated sessions (existing upstream integration) and email digests.

Master edits:
- GTE-02.excluded: "localStorage read state" -> "localStorage read state (non-goal; server-side ack, X-30)"
- GTE-03.excluded: "Slack-originated sessions" -> "Slack-originated sessions (non-goal; existing upstream integration)"
- GTE-04.excluded: "Email digests" -> "Email digests (non-goal)"

Spec edits:
- GTE-02: **Ownership boundaries.** Excluded: reword the item covering "localStorage read state" so it says "localStorage read state (non-goal; server-side ack, X-30)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-076).
- GTE-03: **Ownership boundaries.** Excluded: reword the item covering "Slack-originated sessions" so it says "Slack-originated sessions (non-goal; existing upstream integration)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-076).
- GTE-04: **Ownership boundaries.** Excluded: reword the item covering "Email digests" so it says "Email digests (non-goal)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-076).

### RES-077 · nongoal · GTE-01, GTE-06

Answering multi-label gates on /approve is a non-goal through M4: get_elicitation omits requestedSchema, so ApprovePage offers only Approve and Reject. Binary gates work; deep links for multi-label gates open the run view.

Master edits:
- GTE-01.excluded += "Answering multi-label gates on /approve (non-goal through M4; their deep links open the run view)"
- GTE-06.included: "deep-link payloads without secrets" -> "deep-link payloads without secrets (binary gates to /approve, multi-label gates to the run view)"

Spec edits:
- GTE-01: **Ownership boundaries.** Excluded: add "Answering multi-label gates on /approve (non-goal through M4; their deep links open the run view)" (RES-077).
- GTE-06: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "deep-link payloads without secrets" so it says "deep-link payloads without secrets (binary gates to /approve, multi-label gates to the run view)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-077).
- GTE-01: In gte.md, replace the bullet `` - Reviewer note: `/approve` cannot answer multi-label gates: `get_elicitation` omits `requestedSchema` (`routes_elicitations.py:196-208`), so ApprovePage's non-card branch (`ApprovePage.tsx:174-178, 250-286`) offers only Approve and Reject. Binary gates work. The upstream fix is unowned; until then, links open the run view. `` with `` - Non-goal through M4: `/approve` cannot answer multi-label gates (`get_elicitation` omits `requestedSchema`, `routes_elicitations.py:196-208`; ApprovePage's non-card branch, `ApprovePage.tsx:174-178, 250-286`, offers only Approve and Reject). Binary gates work; multi-label links open the run view. `` (no longer a reviewer note; settled by RES-077).

### RES-078 · fixed · GTE-02

GTE-02 (weeks 5-7) proves cross-client ack on MSW only; the live proof runs at IM-4 (week 11.5). The spec already says so.

Spec edits:
- GTE-02: In gte.md, replace the bullet `` - Reviewer note: this ends at week 7, before GTE-01 (9) and GTE-06 (11.5); cross-client ack is MSW-only until IM-4. `` with `` - This feature ends at week 7, before GTE-01 (9) and GTE-06 (11.5), so cross-client ack is proven on MSW until the IM-4 row runs. `` (no longer a reviewer note; settled by RES-078).

### RES-079 · citation · GTE-02

S37 is not a one-line spread: it needs about seven anchored points in InboxPage.tsx plus one useSidebarData line. The S37 budget and the hot-file row are amended.

Changed by the challenge pass: CH-28.

Master edits:
- GTE-02.included: "Inbox-kind registry that InboxPage.tsx spreads in one line, after" -> "Inbox-kind registry wired into InboxPage.tsx at about seven anchored points plus one useSidebarData line (S37 budget amended), after"
- notes += "RES-079: Hot-file order amendment (§6.5): web/src/pages/InboxPage.tsx row reads 'BRD-02: S84, then GTE-02: S37 (about seven anchored points plus one useSidebarData line)'."

Spec edits:
- GTE-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Inbox-kind registry that InboxPage.tsx spreads in one line, after" so it says "Inbox-kind registry wired into InboxPage.tsx at about seven anchored points plus one useSidebarData line (S37 budget amended), after". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-079).
- GTE-02: In gte.md, delete the bullet `` - Reviewer note: a one-line spread is not achievable; about 7 anchors are the minimum. `` (resolved by RES-079).

Section edits:
- D: D.8 hot-file table: InboxPage.tsx row "BRD-02: S84 → GTE-02: S37, about seven anchors plus one useSidebarData line". (RES-079)
- H: H.5: replace "GTE-02 S37, a one-line registry spread after BRD-02's S84" with "GTE-02 S37 (about seven anchors plus one useSidebarData line) after BRD-02's S84". (RES-079)
- A: A.1 "Seams are one-line registry calls": add "(S37 is the exception: about seven anchored points in InboxPage.tsx plus one useSidebarData line)". (RES-079)

### RES-080 · nongoal · GTE-02, GTE-06

The Extend run action is dropped: gates never expire (OQ-5) and no backend owns it. GTE-02's actions are open, resume and cancel; K19 actions never list Extend.

Master edits:
- GTE-02.included: "Run actions (open, resume, cancel, extend)" -> "Run actions (open, resume, cancel; no Extend, a non-goal because gates never expire)"

Spec edits:
- GTE-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Run actions (open, resume, cancel, extend)" so it says "Run actions (open, resume, cancel; no Extend, a non-goal because gates never expire)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-080).
- GTE-02: Product requirements: remove "and Extend when listed" from the card actions. (RES-080)
- GTE-06: Producers: state that `actions[]` never contains Extend. (RES-080)
- GTE-02: In gte.md, delete the bullet `` - Reviewer note: Extend has no backend owner; API-02 lists pause, resume, cancel, retry. `` (resolved by RES-080).
- GTE-06: In gte.md, delete the bullet `` - Reviewer note: the Extend action has no backend owner. `actions` lists it only once an endpoint exists. `` (resolved by RES-080).

### RES-081 · citation · GTE-05

omnigent/server/elicitation_hooks.py does not exist at HEAD; it is new upstream-path code counted under S6's budget.

Master edits:
- GTE-05.included: "(routes_events.py, one line into a helper module)" -> "(routes_events.py, one line into the new upstream-path module omnigent/server/elicitation_hooks.py, counted under S6)"

Spec edits:
- GTE-05: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "(routes_events.py, one line into a helper module)" so it says "(routes_events.py, one line into the new upstream-path module omnigent/server/elicitation_hooks.py, counted under S6)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-081).
- GTE-05: In gte.md, delete the bullet `` - Reviewer note: `omnigent/server/elicitation_hooks.py` does not exist at HEAD. It is new upstream-path code, and the ledger must count it under S6. `` (resolved by RES-081).

### RES-082 · assign · GTE-04, BRD-03

GTE-04 owns desktop delivery through an inbox watcher loaded from web/electron/src/main.js under new seam row S87b, landed after BRD-03's S87. CI covers only the push-service HTTP boundary. Electron Web Push availability is unverified.

Changed by the challenge pass: CH-23.

Master edits:
- GTE-04.included: "Payloads without secrets; desktop shell delivery" -> "Payloads without secrets; desktop shell delivery through an inbox watcher loaded from web/electron/src/main.js under seam row S87b (after BRD-03's S87); CI covers the push-service HTTP boundary only"
- GTE-04.seams += S87b

Spec edits:
- GTE-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Payloads without secrets; desktop shell delivery" so it says "Payloads without secrets; desktop shell delivery through an inbox watcher loaded from web/electron/src/main.js under seam row S87b (after BRD-03's S87); CI covers the push-service HTTP boundary only". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-082).
- GTE-04: **Technical scope.** Modify or extend upstream: add S87b to the seams this feature lands (RES-082).
- GTE-04: In gte.md, replace the bullet `` - Reviewer note: Electron's Chromium has no push service, so `PushManager.subscribe` should fail (UNVERIFIED). The desktop watcher must load from `web/electron/src/main.js`, an upstream file with no ledgered seam; add an S-row owned by GTE-04, after BRD-03. `` with `` - Open item (RES-082): Electron's Chromium likely has no push service (UNVERIFIED), so desktop delivery uses an inbox watcher loaded from `web/electron/src/main.js` under seam row S87b, after BRD-03's S87 (tracked in J.6). ``.
- GTE-04: In gte.md, replace the bullet `` - Reviewer note: a real push proof needs a live push service, so CI covers only the push-service HTTP boundary. `` with `` - A real push proof needs a live push service, so CI covers only the push-service HTTP boundary. `` (no longer a reviewer note; settled by RES-082).

Section edits:
- J: J.6: add the row "| RES-082 | GTE-04 owns desktop delivery through an inbox watcher loaded from web/electron/src/main.js under new seam row S87b, landed after BRD-03's S87. CI covers only the push-service HTTP boundary. Electron Web Push availability is unverified. | GTE-04 | Week 26.5 (GTE-04 start) | If Electron has no Web Push service, desktop delivery relies only on the main-process watcher, which needs credentials. |".

### RES-083 · nongoal · EVD-04

Hidden held-out tests and LLM rubric judges are non-goals with no owner (not master-deferred gaps).

Changed by the challenge pass: CH-15.

Master edits:
- EVD-04.excluded: "Hidden held-out tests" -> "Hidden held-out tests (non-goal)"
- EVD-04.excluded: "LLM rubric judges" -> "LLM rubric judges (non-goal)"

Spec edits:
- EVD-04: Excluded: replace "held-out tests, LLM rubric judges (unowned, not master-deferred)" with "held-out tests, LLM rubric judges (non-goals)". (RES-083)

### RES-084 · fixed · EVD-04

The EVD-04 S72 ledger note was stale: master §7 already lists "S72 detached mode (EVD-04)" as a ledger amendment.

### RES-085 · contract · EVD-02, FND-02

EVD-02 consumes K17 (the S68 observer registers through the process map) and keeps K6 (the evidence opt-in key in params.coral). Add soft edge EVD-02 -> FND-02.

Master edits:
- EVD-02.contracts_consumed += K17; K17.consumers += EVD-02
- EVD-02.soft_deps += FND-02 (K17 process map for the S68 observer)

Spec edits:
- EVD-02: **Dependencies.** Add K17 to the "Contracts: consumes ..." line (RES-085).
- EVD-02: **Dependencies.** Add FND-02 to the "Soft:" line (K17 process map for the S68 observer; RES-085).
- FND-02: **Dependencies.** Add EVD-02 to the soft part of "Downstream, unblocks:" (RES-085).
- EVD-02: In evd-api.md, delete the bullet `` - Reviewer note: the `evidence` opt-in must be a K6 params.coral key (consumed); the S68 observer registers via K17's process map, which is not consumed. `` (resolved by RES-085).

### RES-086 · edge · EVD-03, WSP-01

Promote EVD-03 -> WSP-01 from soft to hard: the migration train makes repo_bindings a prerequisite of command_patterns. WSP-01 ends week 7, when EVD-03 starts, and the phase and milestone order holds.

Master edits:
- EVD-03.soft_deps -= WSP-01
- EVD-03.hard_deps += WSP-01 (repo_bindings migration precedes command_patterns)

Spec edits:
- EVD-03: **Dependencies.** Add WSP-01 to the "Hard:" line and remove it from "Soft:" if listed (repo_bindings migration precedes command_patterns; RES-086).
- WSP-01: **Dependencies.** List EVD-03 in the hard part of "Downstream, unblocks:" (RES-086).
- EVD-03: In evd-api.md, delete the bullet `` - Reviewer note: the migration train requires WSP-01's `repo_bindings` first, yet WSP-01 is only soft; it finishes week 7, when EVD-03 starts. `` (resolved by RES-086).

### RES-087 · edge · EVD-01, ENG-02

Add soft edge EVD-01 -> ENG-02. ENG-02 owns a done_when compile hook in its compiler; EVD-01 owns compile_done_when, which the hook calls.

Master edits:
- EVD-01.soft_deps += ENG-02 (compile hook for done_when)
- ENG-02.included += "A done_when compile hook that calls EVD-01's compile_done_when (stubbed until it lands)"

Spec edits:
- EVD-01: **Dependencies.** Add ENG-02 to the "Soft:" line (compile hook for done_when; RES-087).
- ENG-02: **Dependencies.** Add EVD-01 to the soft part of "Downstream, unblocks:" (RES-087).
- ENG-02: **Ownership boundaries.** Included: add "A done_when compile hook that calls EVD-01's compile_done_when (stubbed until it lands)" (RES-087).
- EVD-01: In evd-api.md, delete the bullet `` - Reviewer note: step 5 lands in ENG-02's compiler (same weeks 3-5) with no edge; agree the hook with ENG-02. `` (resolved by RES-087).

### RES-088 · contract · EVD-01, EVD-02, HRN-03, SPK-04

K11's watermark is a per-session transport sequence plus EVD-02's in-flight cover rule (claude-sdk has no item seq at ingestion; HRN-03 maps native item seqs onto it). L1 is computed in Python (os.stat, git hash-object --stdin-paths), never with shell stat.

Master edits:
- K11.description: "per-session observation watermark" -> "per-session observation watermark (a transport sequence plus EVD-02's in-flight cover rule; HRN-03 maps native item seqs onto it)"
- K11.description += "L1 is computed in Python (os.stat size and mtime, git hash-object --stdin-paths for dirty paths), never with shell stat."
- EVD-01.included: "(last ingested tool-result item seq)" -> "(a transport sequence plus the in-flight cover rule, K11)"

Spec edits:
- EVD-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "(last ingested tool-result item seq)" so it says "(a transport sequence plus the in-flight cover rule, K11)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-088).
- EVD-01: In evd-api.md, delete the bullet `` - Reviewer note: the master's watermark is the "last ingested tool-result item seq", but claude-sdk has no item seq at ingestion; K11 uses a transport sequence plus EVD-02's in-flight cover rule, and HRN-03 maps item seqs onto it. `` (resolved by RES-088).
- EVD-01: In evd-api.md, delete the bullet `` - Reviewer note: `stat` flags differ between BSD and GNU; `git hash-object --stdin-paths` over dirty paths is portable (SPK-04 to confirm). `` (resolved by RES-088).

### RES-089 · edge · EVD-02, WSP-06, TLS-02

Add soft edge EVD-02 -> WSP-06 (session-shell fingerprint). EVD-02's proof needs TLS-02 and WSP-06, so it closes on Tier A at week 7 and its Tier B run is at IM-3 (week 11.5). TLS-02 cannot be an edge (TLS-02 soft-depends on EVD-02).

Master edits:
- EVD-02.soft_deps += WSP-06 (session-shell fingerprint for the proof)

Spec edits:
- EVD-02: **Dependencies.** Add WSP-06 to the "Soft:" line (session-shell fingerprint for the proof; RES-089).
- WSP-06: **Dependencies.** Add EVD-02 to the soft part of "Downstream, unblocks:" (RES-089).
- EVD-02: In evd-api.md, replace the bullet `` - Reviewer note: the proof needs TLS-02 and WSP-06's session-shell fingerprint (weeks 7-9, no edge), so it closes at IM-3 (week 11.5). `` with `` - Open item (RES-089): The proof needs TLS-02 (no edge possible) and WSP-06 (now soft), so it closes on Tier A at week 7 and the Tier B run is at IM-3 (week 11.5; tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-089 | Add soft edge EVD-02 -> WSP-06 (session-shell fingerprint). EVD-02's proof needs TLS-02 and WSP-06, so it closes on Tier A at week 7 and its Tier B run is at IM-3 (week 11.5). TLS-02 cannot be an edge (TLS-02 soft-depends on EVD-02). | EVD-02 (WS-WORKSPACE lead) | IM-3, week 11.5 | The handoff evidence proof is green only at IM-3; a TLS-02 or WSP-06 slip delays it. |".

### RES-090 · contract · EVD-03, DUR-02, API-01

EVD-03 consumes K7 and gets a soft edge to DUR-02 (the snapshot writes through DUR-02's store). K7 names /v1/coral/repos/{id}/command-patterns routes (EVD-03).

Master edits:
- EVD-03.contracts_consumed += K7; K7.consumers += EVD-03
- EVD-03.soft_deps += DUR-02 (snapshot into a new version through the workflow store)
- K7.description += "Repo routes /v1/coral/repos/{id}/command-patterns (EVD-03) are reserved in the v1 path list."

Spec edits:
- EVD-03: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-090).
- EVD-03: **Dependencies.** Add DUR-02 to the "Soft:" line (snapshot into a new version through the workflow store; RES-090).
- DUR-02: **Dependencies.** Add EVD-03 to the soft part of "Downstream, unblocks:" (RES-090).
- EVD-03: In evd-api.md, delete the bullet `` - Reviewer note: EVD-03 serves `/v1/coral/repos/*` without consuming K7; API-01's spec reserves the paths, but the master K7 text omits them. `` (resolved by RES-090).
- EVD-03: In evd-api.md, delete the bullet `` - Reviewer note: the snapshot writes through DUR-02's store, but there is no edge to DUR-02. `` (resolved by RES-090).
- API-01: In evd-api.md, delete the bullet `` - Reviewer note: the master K7 text omits EVD-03's repo command-pattern routes; this spec reserves them, and the master should name them. `` (resolved by RES-090).

### RES-091 · contract · EVD-04

EVD-04 consumes K1 (check keys), K2 (observations), K3 (log kinds) and K21 (executor registration).

Master edits:
- EVD-04.contracts_consumed += K1; K1.consumers += EVD-04
- EVD-04.contracts_consumed += K2; K2.consumers += EVD-04
- EVD-04.contracts_consumed += K3; K3.consumers += EVD-04
- EVD-04.contracts_consumed += K21; K21.consumers += EVD-04

Spec edits:
- EVD-04: **Dependencies.** Add K1 to the "Contracts: consumes ..." line (RES-091).
- EVD-04: **Dependencies.** Add K2 to the "Contracts: consumes ..." line (RES-091).
- EVD-04: **Dependencies.** Add K3 to the "Contracts: consumes ..." line (RES-091).
- EVD-04: **Dependencies.** Add K21 to the "Contracts: consumes ..." line (RES-091).
- EVD-04: In evd-api.md, delete the bullet `` - Reviewer note: check-to-attempt needs K2 observations, K3 kinds, K21 registration and K1 check keys; none is a consumed contract. `` (resolved by RES-091).

### RES-092 · contract · OPS-01, API-01, WEB-04, WEB-03, FND-05

K16 v1 adds anchor_exempt entries (files that cannot carry anchors: JSON, lockfiles, python-matrix.json) and non-seam MF-n entries for dependency-manifest edits. API-01 owns the msw devDependency MF entry; WEB-04 owns the axe devDependency PR and MF entry (WEB-09 reuses it).

Master edits:
- K16.description += "anchor_exempt entries cover files that cannot carry CORAL(Sx) anchors (JSON, lockfiles, python-matrix.json); non-seam MF-n entries ledger dependency-manifest edits (web/package.json, pyproject.toml)."
- API-01.included += "msw as a direct web devDependency through a K16 MF entry (it is only transitive at HEAD)"
- WEB-04.included += "Standalone axe devDependency PR (mirror-checked, cooldown respected, OPS-02 licence check) through a K16 MF entry; WEB-09 reuses it"

Spec edits:
- API-01: **Ownership boundaries.** Included: add "msw as a direct web devDependency through a K16 MF entry (it is only transitive at HEAD)" (RES-092).
- WEB-04: **Ownership boundaries.** Included: add "Standalone axe devDependency PR (mirror-checked, cooldown respected, OPS-02 licence check) through a K16 MF entry; WEB-09 reuses it" (RES-092).
- API-01: In evd-api.md, delete the bullet `` - Reviewer note: the `web/package.json` edits touch an upstream file that has no seam id, so OPS-01 needs a ledger entry for them. `` (resolved by RES-092).
- OPS-01: In ops-a.md, delete the bullet `` - Reviewer note: `python-matrix.json` (S39d), `web/package.json` and lockfiles cannot carry anchors, and dependency edits have no seam id. This spec adds `anchor_exempt` and non-seam `MF-n` entries to K16 v1. `` (resolved by RES-092).
- WEB-03: In web-a.md, delete the bullet `` - Reviewer note: msw is only a transitive lock entry (`pnpm-lock.yaml:7390`). API-01 must add it as a direct devDependency. `` (resolved by RES-092).
- WEB-04: In web-a.md, delete the bullet `` - Reviewer note: no axe tooling is locked at HEAD (`pnpm-lock.yaml`, `uv.lock`); no master feature names that dependency PR, so step 6 owns it. `` (resolved by RES-092).

### RES-093 · edge · API-02, FND-02

Add soft edge API-02 -> FND-02 and K17 to API-02's consumed contracts (plugin registration and the K4 access adapter).

Master edits:
- API-02.soft_deps += FND-02 (K17 registration and the K4 access adapter)
- API-02.contracts_consumed += K17; K17.consumers += API-02

Spec edits:
- API-02: **Dependencies.** Add FND-02 to the "Soft:" line (K17 registration and the K4 access adapter; RES-093).
- FND-02: **Dependencies.** Add API-02 to the soft part of "Downstream, unblocks:" (RES-093).
- API-02: **Dependencies.** Add K17 to the "Contracts: consumes ..." line (RES-093).
- API-02: In evd-api.md, delete the bullet `` - Reviewer note: API-02 uses FND-02's K17 registration and K4 access adapter with no edge to FND-02. `` (resolved by RES-093).

### RES-094 · assign · WSP-06, API-02

Engine commit records: WSP-06 writes {sha, subject, node, item_path} into each commit effect's EffectCompleted log entry; API-02's outcome folds its commit list from those entries. No new table.

Master edits:
- WSP-06.included: "computed then and stored with the handoff" -> "computed then and stored with the handoff; each engine commit's sha, subject, node and item_path recorded in its EffectCompleted log entry"
- API-02.included: "commit list" -> "commit list folded from WSP-06's commit log entries"

Spec edits:
- WSP-06: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "computed then and stored with the handoff" so it says "computed then and stored with the handoff; each engine commit's sha, subject, node and item_path recorded in its EffectCompleted log entry". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-094).
- API-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "commit list" so it says "commit list folded from WSP-06's commit log entries". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-094).
- API-02: In evd-api.md, delete the bullet `` - Reviewer note: the outcome commit list needs WSP-06 to persist commit records; its scope names only `diff_stat`. `` (resolved by RES-094).

### RES-095 · split · RUL-05, API-02

RUL-05's spend aggregator reuses API-02's K4 usage adapter rather than a second implementation.

Master edits:
- RUL-05.included: "Spend aggregator over all run sessions (policy_cost_usd ?? total_cost_usd)" -> "Spend aggregator over all run sessions through API-02's K4 usage adapter (policy_cost_usd ?? total_cost_usd)"

Spec edits:
- RUL-05: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Spend aggregator over all run sessions (policy_cost_usd ?? total_cost_usd)" so it says "Spend aggregator over all run sessions through API-02's K4 usage adapter (policy_cost_usd ?? total_cost_usd)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-095).

### RES-096 · split · EVD-01, EVD-02, WSP-01, WSP-06, WSP-02

L1 and K13 backends: EVD-01 owns the pure L1 probe and digest code; EVD-02 enforces it per command and at submit; WSP-01 owns the K13 interface, fake and conformance tests; WSP-06 implements the session-shell backend; WSP-02 and WSP-07 implement the host-channel backend.

Master edits:
- WSP-01.included: "session-shell and host-channel backends, fake, conformance tests" -> "the session-shell and host-channel backend interfaces, fake, conformance tests (WSP-06 implements the session-shell backend; WSP-02 and WSP-07 the host channel)"
- EVD-01.included: "Observation and fingerprint records;" -> "Observation and fingerprint records and the pure L1 probe and digest code that EVD-02, WSP-01 and WSP-02 call;"

Spec edits:
- WSP-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "session-shell and host-channel backends, fake, conformance tests" so it says "the session-shell and host-channel backend interfaces, fake, conformance tests (WSP-06 implements the session-shell backend; WSP-02 and WSP-07 the host channel)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-096).
- EVD-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Observation and fingerprint records;" so it says "Observation and fingerprint records and the pure L1 probe and digest code that EVD-02, WSP-01 and WSP-02 call;". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-096).

### RES-097 · assign · HRN-06, EVD-02

Headless codex command observations (exit code and L1 fingerprint) are unowned; HRN-06 owns them through EVD-02's K4 observations adapter and consumes K11.

Master edits:
- HRN-06.included += "Headless codex command observations (exit code and L1 fingerprint) through EVD-02's K4 observations adapter"
- HRN-06.contracts_consumed += K11; K11.consumers += HRN-06

Spec edits:
- HRN-06: **Ownership boundaries.** Included: add "Headless codex command observations (exit code and L1 fingerprint) through EVD-02's K4 observations adapter" (RES-097).
- HRN-06: **Dependencies.** Add K11 to the "Contracts: consumes ..." line (RES-097).
- EVD-02: Excluded: replace "codex (HRN-05, HRN-06)" with "codex-native exit codes (HRN-05); headless codex observations (HRN-06)". (RES-097)

### RES-098 · assign · RUL-02, WEB-13, WEB-03

RUL-02 owns the thin label routes in coral/api/guarantees.py (GET /v1/coral/runs/{id}/guarantees and the version :guarantees POST); they are additive K7 routes, so RUL-02 consumes K7.

Master edits:
- RUL-02.included += "Thin label routes in coral/api/guarantees.py: GET /v1/coral/runs/{id}/guarantees and POST .../versions/{v}:guarantees (additive K7)"
- RUL-02.contracts_consumed += K7; K7.consumers += RUL-02
- K7.description += "Guarantee routes GET /v1/coral/runs/{id}/guarantees and POST .../versions/{v}:guarantees (RUL-02) are additive."

Spec edits:
- RUL-02: **Ownership boundaries.** Included: add "Thin label routes in coral/api/guarantees.py: GET /v1/coral/runs/{id}/guarantees and POST .../versions/{v}:guarantees (additive K7)" (RES-098).
- RUL-02: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-098).
- RUL-02: In rul.md, delete the bullet `` - Reviewer note: no feature owns HTTP exposure of labels for WEB-13 and WEB-03. This spec adds thin routes. `` (resolved by RES-098).

### RES-099 · fixed · RUL-03

The RUL-03 datamodel citation (datamodel.py:593-618 built-in masks) was corrected by the verifier; spec and master agree.

### RES-100 · residual · RUL-03

An Enforced protect_paths on claude-sdk needs compiled sibling write grants (UNVERIFIED on seatbelt) or an unplanned sandbox seam, because write_paths is an allowlist and shell writes bypass a write-tool DENY.

Spec edits:
- RUL-03: In rul.md, replace the bullet `` - Reviewer note: shell writes bypass a write-tool DENY, and `write_paths` (`datamodel.py:621`) is an allowlist whose only nested denies are built-in dotfile and `~/Library` masks (`:593-618`). An Enforced `protect_paths` on claude-sdk needs compiled sibling grants (UNVERIFIED on seatbelt) or an unplanned sandbox seam. `` with `` - Open item (RES-100): Shell writes bypass a write-tool DENY, and `write_paths` (`datamodel.py:621`) is an allowlist whose only nested denies are built-in dotfile and `~/Library` masks (`:593-618`). An Enforced `protect_paths` on claude-sdk needs compiled sibling grants (UNVERIFIED on seatbelt); otherwise it is labelled Verified (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-100 | An Enforced protect_paths on claude-sdk needs compiled sibling write grants (UNVERIFIED on seatbelt) or an unplanned sandbox seam, because write_paths is an allowlist and shell writes bypass a write-tool DENY. | RUL-03 (WS-HARNESS lead) | Week 15.5 (RUL-03 mid-window) | If sibling grants fail on seatbelt, protect_paths is labelled Verified, not Enforced, on claude-sdk, and RUL-03's proof uses the write-tool DENY only. |".

### RES-101 · citation · RUL-01

S52 touches four builder.py sites (three assembly sites plus the fast path), not one line.

Master edits:
- RUL-01.included: "S52 required-policy provider in builder.py (one line)" -> "S52 required-policy provider in builder.py (four sites: three assembly sites plus the fast path)"

Spec edits:
- RUL-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "S52 required-policy provider in builder.py (one line)" so it says "S52 required-policy provider in builder.py (four sites: three assembly sites plus the fast path)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-101).
- RUL-01: In rul.md, delete the bullet `` - Reviewer note: S52 is four `builder.py` sites (three assembly sites plus the fast path), not one line. `` (resolved by RES-101).

### RES-102 · citation · RUL-01

RUL-01's proving test is split: the upstream half in tests/runtime/policies/ and the Coral half in tests/coral/omni/policies/test_run_guard.py, because upstream tests cannot import coral.

Master edits:
- notes += "RES-102: RUL-01's proving test runs in two places: tests/runtime/policies/ (non-Coral unchanged) and tests/coral/omni/policies/test_run_guard.py (the Coral half), because upstream tests cannot import coral."

Spec edits:
- RUL-01: In rul.md, delete the bullet `` - Reviewer note: upstream tests cannot import `coral`, so the proving test's Coral half lives in `tests/coral/omni/policies/test_run_guard.py`. `` (resolved by RES-102).

### RES-103 · contract · RUL-03, RUL-05

RUL-03 (authoring keys) and RUL-05 (step budget keys) consume K1.

Master edits:
- RUL-03.contracts_consumed += K1; K1.consumers += RUL-03
- RUL-05.contracts_consumed += K1; K1.consumers += RUL-05

Spec edits:
- RUL-03: **Dependencies.** Add K1 to the "Contracts: consumes ..." line (RES-103).
- RUL-05: **Dependencies.** Add K1 to the "Contracts: consumes ..." line (RES-103).
- RUL-03: In rul.md, delete the bullet `` - Reviewer note: the authoring keys belong to K1 (ENG-01), but K1 is not listed among this feature's consumed contracts. `` (resolved by RES-103).
- RUL-05: In rul.md, delete the bullet `` - Reviewer note: step budget keys need K1, which this feature does not consume. `` (resolved by RES-103).

### RES-104 · citation · RUL-04, HRN-03, HRN-05

Hot-file order amendment: RUL-04's S14 also touches runner/native/orchestration.py and codex_native/app_server.py (land before HRN-03 and HRN-05), and S16 touches helpers.py and policies/types.py.

Master edits:
- notes += "RES-104: Hot-file order amendment (§6.5): runner/native/orchestration.py row starts with RUL-04: S14, then HRN-03; codex_native/app_server.py row starts with RUL-04: S14, then HRN-05; helpers.py adds RUL-04: S16 after SES-02 and before TLS-01: S49; omnigent/policies/types.py gains RUL-04: S16."

Spec edits:
- RUL-04: In rul.md, delete the bullet `` - Reviewer note: S14 also touches `runner/native/orchestration.py` and `codex_native/app_server.py`, which §6.5 does not list for RUL-04. Land these before HRN-03 and HRN-05. `` (resolved by RES-104).
- RUL-04: In rul.md, delete the bullet `` - Reviewer note: S16 touches `helpers.py` (a hot file) and `policies/types.py`, which neither the gap row nor §6.5 lists. `` (resolved by RES-104).

Section edits:
- D: D.8 hot-file table: prefix the native orchestration.py and codex_native/app_server.py rows with "RUL-04: S14 →"; add "RUL-04: S16" to the helpers.py row after SES-02. (RES-104)

### RES-105 · contract · DUR-01, RUL-05, EVD-04, WSP-03, SES-07, ENG-09, EXT-01, EXT-04, GTE-04

Run budget and spend columns are not in coral_0001; RUL-05's coral_00NN_budgets migration owns them (master train already lists budgets under RUL-05). Every migration-train owner consumes K5, so RUL-05, EVD-04 (check_runs), WSP-03 (merge_state), SES-07 (slot_control columns), ENG-09 (saved_blocks), EXT-01, EXT-04 and GTE-04 (the post-M4 tables) now list it.

Changed by the challenge pass: CH-24.

Master edits:
- K5.description += "Run and step budget and spend columns live in RUL-05's budgets migration, not in coral_0001."
- DUR-01.excluded += "Run budget and spend columns (RUL-05's budgets migration)"
- RUL-05.contracts_consumed += K5; K5.consumers += RUL-05
- EVD-04.contracts_consumed += K5; K5.consumers += EVD-04
- WSP-03.contracts_consumed += K5; K5.consumers += WSP-03
- SES-07.contracts_consumed += K5; K5.consumers += SES-07
- ENG-09.contracts_consumed += K5; K5.consumers += ENG-09
- EXT-01.contracts_consumed += K5; K5.consumers += EXT-01
- EXT-04.contracts_consumed += K5; K5.consumers += EXT-04
- GTE-04.contracts_consumed += K5; K5.consumers += GTE-04

Spec edits:
- DUR-01: **Ownership boundaries.** Excluded: add "Run budget and spend columns (RUL-05's budgets migration)" (RES-105).
- RUL-05: **Dependencies.** Add K5 to the "Contracts: consumes ..." line (RES-105).
- EVD-04: **Dependencies.** Add K5 to the "Contracts: consumes ..." line (RES-105).
- WSP-03: **Dependencies.** Add K5 to the "Contracts: consumes ..." line (RES-105).
- SES-07: **Dependencies.** Add K5 to the "Contracts: consumes ..." line (RES-105).
- ENG-09: **Dependencies.** Add K5 to the "Contracts: consumes ..." line (RES-105).
- EXT-01: **Dependencies.** Add K5 to the "Contracts: consumes ..." line (RES-105).
- EXT-04: **Dependencies.** Add K5 to the "Contracts: consumes ..." line (RES-105).
- GTE-04: **Dependencies.** Add K5 to the "Contracts: consumes ..." line (RES-105).
- DUR-01: Data model: state that coral_0001 carries no run budget or spend columns (it carries none today). (RES-105)
- RUL-05: Data model: name coral_00NN_budgets as the only home of run and step budget and spend columns. (RES-105)
- RUL-05: In rul.md, delete the bullet `` - Reviewer note: eng_persistence T3/T4 put run budget and spend columns in coral_0001. Choose one home before DUR-01 lands. `` (resolved by RES-105).

### RES-106 · edge · RUL-05, HRN-04

Add soft edge RUL-05 -> HRN-04: utilization uses HRN-04's S24 data when present; otherwise RUL-05 shows tokens only.

Master edits:
- RUL-05.soft_deps += HRN-04 (S24 utilization data)

Spec edits:
- RUL-05: **Dependencies.** Add HRN-04 to the "Soft:" line (S24 utilization data; RES-106).
- HRN-04: **Dependencies.** Add RUL-05 to the soft part of "Downstream, unblocks:" (RES-106).
- RUL-05: In rul.md, delete the bullet `` - Reviewer note: utilization needs HRN-04's S24 data, which is not a dependency, so show tokens only. `` (resolved by RES-106).

### RES-107 · edge · RUL-02, WSP-01

Add soft edge RUL-02 -> WSP-01: labels read the host sandbox backend from WSP-01's report.

Master edits:
- RUL-02.soft_deps += WSP-01 (host sandbox report)

Spec edits:
- RUL-02: **Dependencies.** Add WSP-01 to the "Soft:" line (host sandbox report; RES-107).
- WSP-01: **Dependencies.** Add RUL-02 to the soft part of "Downstream, unblocks:" (RES-107).
- RUL-02: In rul.md, delete the bullet `` - Reviewer note: the sandbox backend comes from WSP-01's report, and WSP-01 is not a dependency. `` (resolved by RES-107).

### RES-108 · split · RUL-01, PRF-01

Spawn grants: PRF-01 writes spawn: false and tools.agents: [] into bundles; RUL-01 checks them at run start (assert_run_grants).

Changed by the challenge pass: CH-25.

Master edits:
- RUL-01.included: "Spec grants spawn: false and tools.agents: []" -> "Checks the spec grants spawn: false and tools.agents: [] at run start (assert_run_grants); PRF-01 writes them"
- PRF-01.included: "spawn: false, skills none" -> "spawn: false and tools.agents: [] (RUL-01 checks them at run start), skills none"

Spec edits:
- RUL-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Spec grants spawn: false and tools.agents: []" so it says "Checks the spec grants spawn: false and tools.agents: [] at run start (assert_run_grants); PRF-01 writes them". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-108).
- PRF-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "spawn: false, skills none" so it says "spawn: false and tools.agents: [] (RUL-01 checks them at run start), skills none". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-108).
- RUL-01: In rul.md, delete the bullet `` - Reviewer note: PRF-01's hygiene also lists the grants; PRF-01 writes them, RUL-01 checks them. `` (resolved by RES-108).

### RES-109 · split · RUL-01, EXT-02

Input scoping: RUL-01 owns the whole-step deny_session_reads policy (internal_only); EXT-02 binds it per member and adds files.materialize.

Master edits:
- EXT-02.included: "Per-member input scoping with a coral.omni.policies DENY on session-read tools plus a files.materialize host op" -> "Per-member input scoping that binds RUL-01's deny_session_reads policy per member, plus a files.materialize host op"

Spec edits:
- EXT-02: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Per-member input scoping with a coral.omni.policies DENY on session-read tools plus a files.materialize host op" so it says "Per-member input scoping that binds RUL-01's deny_session_reads policy per member, plus a files.materialize host op". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-109).
- EXT-02: In ext.md, delete the bullet `` - Reviewer note: master RUL-01 includes "input-scope deny (internal_only)" and its spec owns `coral/omni/policies/input_scope.py` (`deny_session_reads`), which is also this feature's key path. Default here: RUL-01 owns the DENY; EXT-02 adds the per-member scope binding. Reconcile in the master. `` (resolved by RES-109).

### RES-110 · assign · RUL-01, SES-03, SES-09

Forks copy coral.* labels, so RUL-01's run-guard provider confirms the session binding (K4 lookup implemented by SES-03, fake until then) rather than trusting labels.

Master edits:
- RUL-01.included: "keyed on coral.run_id, an O(1) no-op" -> "keyed on coral.run_id and confirmed against the session binding (forks copy coral.* labels), an O(1) no-op"

Spec edits:
- RUL-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "keyed on coral.run_id, an O(1) no-op" so it says "keyed on coral.run_id and confirmed against the session binding (forks copy coral.* labels), an O(1) no-op". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-110).
- SES-09: In ses-b.md, delete the bullet `` - Reviewer note: forks copy `coral.*` labels, so RUL-01's provider must check the binding. `` (resolved by RES-110).

### RES-111 · fixed · RUL-06

RUL-06's proving test pins the claude-native K9 value to ask in its fixture and adds a deny case; the spec already does this.

Spec edits:
- RUL-06: In rul.md, replace the bullet `` - Reviewer note: the proving test depends on the claude-native K9 value. Pin `ask` in its fixture and add a `deny` case. `` with `` - The proving test pins the claude-native K9 value to `ask` in its fixture and adds a `deny` case. `` (no longer a reviewer note; settled by RES-111).

### RES-112 · split · HRN-04, HRN-08

HRN-04 keeps only the usage_limit_signal mock-provider probe; HRN-08 owns the bench harness, the other probes and the nightly.

Master edits:
- HRN-04.included: "paused(plan_limit) showing paused-until with auto-resume; mock-provider probe" -> "paused(plan_limit) showing paused-until with auto-resume; the usage_limit_signal mock-provider probe only"
- HRN-04.excluded += "Bench harness, other probes and the nightly (HRN-08)"

Spec edits:
- HRN-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "paused(plan_limit) showing paused-until with auto-resume; mock-provider probe" so it says "paused(plan_limit) showing paused-until with auto-resume; the usage_limit_signal mock-provider probe only". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-112).
- HRN-04: **Ownership boundaries.** Excluded: add "Bench harness, other probes and the nightly (HRN-08)" (RES-112).
- HRN-04: In prf-hrn.md, delete the bullet `` - Reviewer note: master gives HRN-04 the mock-provider probe and HRN-08 all bench probes (S23); this spec keeps only the `usage_limit_signal` probe here. `` (resolved by RES-112).

### RES-113 · split · HRN-04, ENG-11, SES-08

HRN-04's S24 structured signal feeds ENG-11's classifier through SES-08; it does not replace SES-08's logic. ENG-11 owns the classifier.

Master edits:
- HRN-04.included: "; replaces SES-08's text matching" -> "; feeds ENG-11's classifier through SES-08, so structured reset times replace text matching"
- HRN-04.excluded += "The failed-turn classifier (ENG-11)"
- failure_modes[Unclassified 529, 429 or 401].owner: "ENG-11 classifier; SES-08 maps classes to backoff or pauses; HRN-04 adds S24 at M3" -> "ENG-11 classifier; SES-08 maps classes to backoff or pauses; HRN-04 adds the S24 structured signal at M3"

Spec edits:
- HRN-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "; replaces SES-08's text matching" so it says "; feeds ENG-11's classifier through SES-08, so structured reset times replace text matching". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-113).
- HRN-04: **Ownership boundaries.** Excluded: add "The failed-turn classifier (ENG-11)" (RES-113).

### RES-114 · contract · PRF-01, HRN-02, FND-02

PRF-01 (seed agents) and HRN-02 (token check) consume K17; add soft edges PRF-01 -> FND-02 and HRN-02 -> FND-02 (FND-02 ends week 3; no schedule change).

Master edits:
- PRF-01.contracts_consumed += K17; K17.consumers += PRF-01
- HRN-02.contracts_consumed += K17; K17.consumers += HRN-02
- PRF-01.soft_deps += FND-02 (K17 seed-agent registration)
- HRN-02.soft_deps += FND-02 (K17 coral_runner token)

Spec edits:
- PRF-01: **Dependencies.** Add K17 to the "Contracts: consumes ..." line (RES-114).
- HRN-02: **Dependencies.** Add K17 to the "Contracts: consumes ..." line (RES-114).
- PRF-01: **Dependencies.** Add FND-02 to the "Soft:" line (K17 seed-agent registration; RES-114).
- FND-02: **Dependencies.** Add PRF-01 to the soft part of "Downstream, unblocks:" (RES-114).
- HRN-02: **Dependencies.** Add FND-02 to the "Soft:" line (K17 coral_runner token; RES-114).
- FND-02: **Dependencies.** Add HRN-02 to the soft part of "Downstream, unblocks:" (RES-114).
- PRF-01: In prf-hrn.md, delete the bullet `` - Reviewer note: seeds use K17 (FND-02), missing from contracts_consumed; add it (FND-02 ends week 3, no schedule change). `` (resolved by RES-114).
- HRN-02: In prf-hrn.md, delete the bullet `` - Reviewer note: the token check reads K17 (FND-02), absent from contracts_consumed. `` (resolved by RES-114).

### RES-115 · contract · HRN-04

HRN-04 consumes K18 (resets_at) and K2 (paused_until resume time).

Master edits:
- HRN-04.contracts_consumed += K18; K18.consumers += HRN-04
- HRN-04.contracts_consumed += K2; K2.consumers += HRN-04

Spec edits:
- HRN-04: **Dependencies.** Add K18 to the "Contracts: consumes ..." line (RES-115).
- HRN-04: **Dependencies.** Add K2 to the "Contracts: consumes ..." line (RES-115).
- HRN-04: In prf-hrn.md, delete the bullet `` - Reviewer note: HRN-04 adds a K18 field and a K2 resume time but lists only K9; add K18 and K2 to contracts_consumed. `` (resolved by RES-115).

### RES-116 · fixed · PRF-02

PRF-02 follows decision 9 (revision digests stay authoring-only, not in the version content hash); eng_harness §8.4 step 4 is superseded.

Spec edits:
- PRF-02: In prf-hrn.md, replace the bullet `` - Reviewer note: eng_harness §8.4 step 4 puts revision digests in the version content hash; decision 9 keeps it authoring-only. This spec follows decision 9. `` with `` - eng_harness §8.4 step 4 puts revision digests in the version content hash; decision 9 keeps them authoring-only, and this spec follows decision 9. `` (no longer a reviewer note; settled by RES-116).

Section edits:
- B: B.5: add "eng_harness §8.4 step 4 (revision digests in the version hash) vs master decision 9: resolved for decision 9". (RES-116)

### RES-117 · fixed · PRF-01

PRF-01's allowlist goldens use a test registry until RUL-01's handlers land; the soft edge PRF-01 -> RUL-01 already exists.

Spec edits:
- PRF-01: In prf-hrn.md, replace the bullet `` - Reviewer note: the allowlist needs RUL-01's handlers; goldens use a test registry until it lands. `` with `` - The allowlist needs RUL-01's handlers (soft dependency); goldens use a test registry until it lands. `` (no longer a reviewer note; settled by RES-117).

### RES-118 · assign · HRN-05, HRN-07

The codex-native /clear Tier B goes to HRN-05 (codex-native posts the same external_session_superseded event, and HRN-07's follower is harness-neutral). Add soft edge HRN-05 -> HRN-07.

Master edits:
- HRN-05.included += "Tier B for codex-native /clear rotation following, reusing HRN-07's harness-neutral follower"
- HRN-07.excluded += "codex-native /clear Tier B (HRN-05)"
- HRN-05.soft_deps += HRN-07 (rotation follower for codex-native /clear)

Spec edits:
- HRN-05: **Ownership boundaries.** Included: add "Tier B for codex-native /clear rotation following, reusing HRN-07's harness-neutral follower" (RES-118).
- HRN-07: **Ownership boundaries.** Excluded: add "codex-native /clear Tier B (HRN-05)" (RES-118).
- HRN-05: **Dependencies.** Add HRN-07 to the "Soft:" line (rotation follower for codex-native /clear; RES-118).
- HRN-07: **Dependencies.** Add HRN-05 to the soft part of "Downstream, unblocks:" (RES-118).
- HRN-07: Excluded: replace "but no feature owns a codex-native `/clear` Tier B." with "and the codex-native `/clear` Tier B is HRN-05's." (RES-118)

### RES-119 · split · HRN-07, EXT-04

/clear policy: HRN-07 owns the OQ-46 follow-or-block decision and the follower; EXT-04's S46 applies HRN-07's policy and adds none of its own. Because S46 strips coral.* labels, HRN-07's loss fallback looks up the bridge id.

Master edits:
- EXT-04.included: "S46 reserved labels on non-route write paths with an explicit /clear policy" -> "S46 reserved labels on non-route write paths, applying HRN-07's /clear policy (OQ-46)"
- HRN-07.included: "/clear policy (OQ-46)" -> "/clear policy (OQ-46); the label-loss fallback looks up the bridge id, because EXT-04's S46 strips coral.* labels"

Spec edits:
- EXT-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "S46 reserved labels on non-route write paths with an explicit /clear policy" so it says "S46 reserved labels on non-route write paths, applying HRN-07's /clear policy (OQ-46)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-119).
- HRN-07: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "/clear policy (OQ-46)" so it says "/clear policy (OQ-46); the label-loss fallback looks up the bridge id, because EXT-04's S46 strips coral.* labels". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-119).
- EXT-04: In ext.md, delete the bullet `` - Reviewer note: S46 strips the labels HRN-07's loss fallback queries, so HRN-07 must switch to a bridge-id lookup first. The Share UI has no WEB load. `` (resolved by RES-119).
- HRN-07: In hrn.md, delete the bullet `` - Reviewer note: EXT-04's S46 scope also claims "an explicit /clear policy"; OQ-46's follow-or-block decision stays here. `` (resolved by RES-119).

### RES-120 · edge · HRN-06, RUL-04

Add hard edge HRN-06 -> RUL-04: gate_failure_mode=deny needs RUL-04's S14 fail-closed output. RUL-04 (PH2, M3) ends week 7, before HRN-06 starts (PH5, M4, week 21).

Master edits:
- HRN-06.hard_deps += RUL-04 (S14 fail-closed output for gate_failure_mode=deny)

Spec edits:
- HRN-06: **Dependencies.** Add RUL-04 to the "Hard:" line and remove it from "Soft:" if listed (S14 fail-closed output for gate_failure_mode=deny; RES-120).
- RUL-04: **Dependencies.** List HRN-06 in the hard part of "Downstream, unblocks:" (RES-120).
- HRN-06: In hrn.md, delete the bullet `` - Reviewer note: `gate_failure_mode=deny` needs RUL-04's S14 output, yet the master lists no RUL-04 dependency (only via soft HRN-05). Schedule-safe (RUL-04 ends wk 7); make it hard. `` (resolved by RES-120).

### RES-121 · citation · HRN-09

Hot-file order amendment for codex_executor.py: HRN-09 lands S18 and S19 (thread/compact/start) there; S60 changes workflow.py and the parser, not the executor.

Master edits:
- notes += "RES-121: Hot-file order amendment (§6.5): omnigent/inner/codex_executor.py row ends with 'HRN-09: S18, S19 (thread/compact/start)'; S60 lands in omnigent/runtime/workflow.py and the spec parser, not the executor."

Spec edits:
- HRN-09: In hrn.md, delete the bullet `` - Reviewer note: §6.5 lists HRN-09 on `codex_executor.py` as S18 and S60, but S19's `thread/compact/start` request also lands there, while S60 as scoped here changes `workflow.py` and the parser, not the executor. `` (resolved by RES-121).

Section edits:
- D: D.8 hot-file table: codex_executor.py row ends "HRN-09: S18, S19"; note that S60 lands in workflow.py and the parser. (RES-121)

### RES-122 · contract · HRN-07, TLS-02, SES-03, SES-01

After a native /clear rotation, the slot binding records the replacement session id; TLS-02 resolves submits through the binding, so K10's uuid5 ids identify only the original session. HRN-07 consumes K10. SES-03 and TLS-02 sign this before HRN-07 starts.

Master edits:
- HRN-07.contracts_consumed += K10; K10.consumers += HRN-07
- K10.description += "After a native /clear rotation the slot binding records the replacement session id; handlers resolve submitting sessions through the binding, so uuid5 ids identify only the original session."

Spec edits:
- HRN-07: **Dependencies.** Add K10 to the "Contracts: consumes ..." line (RES-122).
- TLS-02: Risks: add "submits from a rotated session resolve through the slot binding (K10 note); SES-03 and TLS-02 sign before week 18". (RES-122)
- HRN-07: In hrn.md, delete the bullet `` - Reviewer note: rotated sessions break K10's uuid5 session ids, so TLS-02 must accept submits from the rebound id (confirm with SES-03, TLS-02). K10 policy ids are used but not listed as consumed. `` (resolved by RES-122).
- HRN-07: In hrn.md, delete the bullet `` - Reviewer note: a rotation audit entry needs a K3 kind (ENG-01); the supersession observer, K4 `on_supersession` and the label query are absent from K18 and K4 (SES-01). `` (resolved by RES-122).

### RES-123 · assign · HRN-09

HRN-09 carries the same OQ-29 condition as HRN-06: dark behind codex_steps while OQ-29 is unanswered (matches M4 exit 4).

Master edits:
- HRN-09.included += "Dark behind codex_steps while OQ-29 is unanswered (same condition as HRN-06)"
- notes += "RES-123: §6.4 amendment: HRN-09 \| If OQ-29 has no answer by PH4 start: stays dark behind codex_steps."

Spec edits:
- HRN-09: **Ownership boundaries.** Included: add "Dark behind codex_steps while OQ-29 is unanswered (same condition as HRN-06)" (RES-123).
- HRN-09: In hrn.md, delete the bullet `` - Reviewer note: the master gives HRN-09 no OQ-29 conditional, but M4 exit 4 treats it as "green or dark behind codex_steps". Add the same conditional as HRN-06. `` (resolved by RES-123).

### RES-124 · assign · OPS-04, HRN-06

OPS-04's security closure covers HRN-06's S20 runner policy relay as a new security surface. HRN-06 may be larger than M (ENG-29); that stays a residual risk. Add soft edge OPS-04 -> HRN-06 (HRN-06 ends week 23, inside OPS-04's weeks 21-25.5).

Changed by the challenge pass: CH-22.

Master edits:
- OPS-04.included: "(host-op token, webhooks, native modes)" -> "(host-op token, webhooks, native modes including HRN-06's S20 runner policy relay)"
- OPS-04.soft_deps += HRN-06 (security closure reviews HRN-06's S20 runner policy relay)

Spec edits:
- OPS-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "(host-op token, webhooks, native modes)" so it says "(host-op token, webhooks, native modes including HRN-06's S20 runner policy relay)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-124).
- OPS-04: **Dependencies.** Add HRN-06 to the "Soft:" line (security closure reviews HRN-06's S20 runner policy relay; RES-124).
- HRN-06: **Dependencies.** Add OPS-04 to the soft part of "Downstream, unblocks:" (RES-124).

Section edits:
- J: J.6: add the row "| RES-124 | OPS-04's security closure covers HRN-06's S20 runner policy relay as a new security surface. HRN-06 may be larger than M (ENG-29); that stays a residual risk. Add soft edge OPS-04 -> HRN-06 (HRN-06 ends week 23, inside OPS-04's weeks 21-25.5). | HRN-06 (HARNESS lead) | Week 21 (HRN-06 start) | If S20 is larger than M, HRN-06 and HRN-09 slip; HRN-09 is the first M4 cut. |".

### RES-125 · citation · HRN-05

The S62 ledger row names the codex-native approval handler: codex_elicitation_request_hook (routes_hooks.py:1262-1340; methods at _codex_elicitation.py:16-18).

Master edits:
- notes += "RES-125: S62 ledger correction: the codex-native approval handler is codex_elicitation_request_hook (omnigent/server/routes/sessions/routes_hooks.py:1262-1340); approval methods at omnigent/server/routes/_codex_elicitation.py:16-18."

Spec edits:
- HRN-05: In hrn.md, delete the bullet `` - Reviewer note: the S62 ledger row leaves the approval handler UNVERIFIED; it is `codex_elicitation_request_hook` (`routes_hooks.py:1262-1340`; approval methods at `omnigent/server/routes/_codex_elicitation.py:16-18`). `` (resolved by RES-125).

### RES-126 · split · HRN-05, HRN-04

The headless codex_executor.py S24 branch lands in HRN-05 per §6.5, despite HRN-05's headless-codex exclusion; HRN-04 owns the shared signal.

Master edits:
- HRN-05.excluded: "Headless codex (HRN-06, HRN-09)" -> "Headless codex (HRN-06, HRN-09), except the S24 usage-limit branch in codex_executor.py, which lands here (§6.5)"

Spec edits:
- HRN-05: **Ownership boundaries.** Excluded: reword the item covering "Headless codex (HRN-06, HRN-09)" so it says "Headless codex (HRN-06, HRN-09), except the S24 usage-limit branch in codex_executor.py, which lands here (§6.5)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-126).
- HRN-05: In hrn.md, delete the bullet `` - Reviewer note: §6.5 assigns the headless `codex_executor.py` S24 branch here despite the headless-codex exclusion; followed here. `` (resolved by RES-126).

### RES-127 · split · HRN-05, HRN-08, RUL-06

Codex-native K9 values: HRN-08 keeps egress_scope and usage_reporting "unknown" until HRN-05's spikes 12 and 13 set them; HRN-05 sets K9 values only and RUL-06 computes labels.

Master edits:
- HRN-05.included: "honest labels" -> "K9 values for honest labels (RUL-06 computes the labels)"
- HRN-08.included: "claude-native, codex-native and headless codex values with host-sandbox rows" -> "claude-native, codex-native and headless codex values with host-sandbox rows (codex-native egress_scope and usage_reporting stay 'unknown' until HRN-05's spikes 12 and 13)"

Spec edits:
- HRN-05: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "honest labels" so it says "K9 values for honest labels (RUL-06 computes the labels)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-127).
- HRN-08: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "claude-native, codex-native and headless codex values with host-sandbox rows" so it says "claude-native, codex-native and headless codex values with host-sandbox rows (codex-native egress_scope and usage_reporting stay 'unknown' until HRN-05's spikes 12 and 13)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-127).

### RES-128 · assign · WSP-05

WSP-05 audits the other plain to_thread frame handlers (connect.py:5950-6052: stat, list_dir, skills, plugins, harness startup, MCP servers) for subprocess spawns and records the result in the S71 row; any that spawn get the same guard as an S71 amendment.

Master edits:
- WSP-05.included += "Audit of the other plain to_thread frame handlers (connect.py:5950-6052) for subprocess spawns, recorded in the S71 ledger row; any that spawn get the same guard as an S71 amendment"

Spec edits:
- WSP-05: **Ownership boundaries.** Included: add "Audit of the other plain to_thread frame handlers (connect.py:5950-6052) for subprocess spawns, recorded in the S71 ledger row; any that spawn get the same guard as an S71 amendment" (RES-128).
- WSP-05: In wsp.md, replace the line `` - Excluded: runner-path exit codes (EVD-02); the host channel (WSP-02); the host channel's exit-status test (WSP-07); other plain `to_thread` frame handlers (`connect.py:5950-6052`; no owner in the master, see Reviewer note). `` with `` - Excluded: runner-path exit codes (EVD-02); the host channel (WSP-02); the host channel's exit-status test (WSP-07). `` (RES-128).
- WSP-05: In wsp.md, delete the bullet `` - Reviewer note: the other plain `to_thread` handlers (stat, list_dir, skills, plugins, harness startup, MCP servers) have no S71 owner; whether any spawns a subprocess is UNVERIFIED. Recommend an OPS-01 ledger follow-up. `` (resolved by RES-128).

### RES-129 · assign · WSP-05

S71 includes the WorkspaceReader fix: on the host, WorkspaceReader starts GitFilesystemRegistry with background=False so no git probe runs after the guarded handler returns.

Master edits:
- WSP-05.included += "Host WorkspaceReader starts GitFilesystemRegistry with background=False, so no git probe runs after the guarded handler returns (workspace_fs.py:172-178, filesystem_registry.py:1082-1092)"

Spec edits:
- WSP-05: **Ownership boundaries.** Included: add "Host WorkspaceReader starts GitFilesystemRegistry with background=False, so no git probe runs after the guarded handler returns (workspace_fs.py:172-178, filesystem_registry.py:1082-1092)" (RES-129).
- WSP-05: In wsp.md, replace the line `` - Proposed, pending a master amendment (Reviewer note): `WorkspaceReader.__init__` (`omnigent/workspace_fs.py:172-178`) calls `GitFilesystemRegistry.start`, whose daemon thread runs git probes after the handler returns (`omnigent/runtime/filesystem_registry.py:1082-1092`; the probe trusts `returncode` at 1175). Add `start(background=False)` for the host's reader. `` with `` - S71 includes (master v3): `WorkspaceReader.__init__` (`omnigent/workspace_fs.py:172-178`) calls `GitFilesystemRegistry.start`, whose daemon thread runs git probes after the handler returns (`omnigent/runtime/filesystem_registry.py:1082-1092`; the probe trusts `returncode` at 1175). Add `start(background=False)` for the host's reader. `` (RES-129).
- WSP-05: In wsp.md, delete the bullet `` - Reviewer note: the master scopes S71 to `connect.py:6027-6034`, but the untracked-cache thread (`filesystem_registry.py:1082-1092`) runs git outside that window. A stolen status there could turn on `core.untrackedCache`. Recommend including it in S71. `` (resolved by RES-129).

### RES-130 · assign · WSP-07, WEB-03

The push-consent UI goes to WSP-07: a consent row in WEB-03's start dialog that names the remote and branch prefix, with WEB-lead review. Add soft edge WSP-07 -> WEB-03.

Changed by the challenge pass: CH-07.

Master edits:
- WSP-07.included: "fetch-ref and push ops behind consent (OQ-39) for the PR-review loop" -> "fetch-ref and push ops behind per-run consent (OQ-39) for the PR-review loop, including the consent row in WEB-03's start dialog (WEB-lead review)"
- WSP-07.soft_deps += WEB-03 (consent row in the start dialog)

Spec edits:
- WSP-07: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "fetch-ref and push ops behind consent (OQ-39) for the PR-review loop" so it says "fetch-ref and push ops behind per-run consent (OQ-39) for the PR-review loop, including the consent row in WEB-03's start dialog (WEB-lead review)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-130).
- WSP-07: **Dependencies.** Add WEB-03 to the "Soft:" line (consent row in the start dialog; RES-130).
- WEB-03: **Dependencies.** Add WSP-07 to the soft part of "Downstream, unblocks:" (RES-130).
- WSP-07: Excluded: remove "the consent UI (WEB-03, not yet in its master scope)"; Included: add "the consent row in the start dialog". (RES-130)

### RES-131 · nongoal · WSP-04

Managed-sandbox provider onboarding is upstream behaviour and a Coral non-goal.

Spec edits:
- WSP-04: Excluded: replace "provider onboarding (upstream)" with "provider onboarding (non-goal; upstream behaviour)". (RES-131)

### RES-132 · assign · WSP-04, WEB-03

WSP-04 owns the managed-sandbox host choice and the "This provider loses work when it sleeps" refusal in WEB-03's start dialog (post-M4, WEB-lead review). Add soft edge WSP-04 -> WEB-03.

Changed by the challenge pass: CH-07.

Master edits:
- WSP-04.included += "The managed-sandbox host choice and the 'This provider loses work when it sleeps' refusal in WEB-03's start dialog (WEB-lead review)"
- WSP-04.soft_deps += WEB-03 (sandbox host choice in the start dialog)

Spec edits:
- WSP-04: **Ownership boundaries.** Included: add "The managed-sandbox host choice and the 'This provider loses work when it sleeps' refusal in WEB-03's start dialog (WEB-lead review)" (RES-132).
- WSP-04: **Dependencies.** Add WEB-03 to the "Soft:" line (sandbox host choice in the start dialog; RES-132).
- WEB-03: **Dependencies.** Add WSP-04 to the soft part of "Downstream, unblocks:" (RES-132).
- WSP-04: Product requirements: replace "WEB-03 renders the choice" with "WSP-04 adds the choice to WEB-03's start dialog"; Excluded: drop "the start dialog (WEB-03)". (RES-132)

### RES-133 · contract · WSP-01, WSP-03, WSP-04, WSP-07

Workspace features consume what they use: WSP-01 consumes K7 (bindings API) and K21 (create_run_worktree); WSP-03 consumes K2, K6 and K21; WSP-04 and WSP-07 consume K21.

Master edits:
- WSP-01.contracts_consumed += K7; K7.consumers += WSP-01
- WSP-01.contracts_consumed += K21; K21.consumers += WSP-01
- WSP-03.contracts_consumed += K2; K2.consumers += WSP-03
- WSP-03.contracts_consumed += K6; K6.consumers += WSP-03
- WSP-03.contracts_consumed += K21; K21.consumers += WSP-03
- WSP-04.contracts_consumed += K21; K21.consumers += WSP-04
- WSP-07.contracts_consumed += K21; K21.consumers += WSP-07

Spec edits:
- WSP-01: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-133).
- WSP-01: **Dependencies.** Add K21 to the "Contracts: consumes ..." line (RES-133).
- WSP-03: **Dependencies.** Add K2 to the "Contracts: consumes ..." line (RES-133).
- WSP-03: **Dependencies.** Add K6 to the "Contracts: consumes ..." line (RES-133).
- WSP-03: **Dependencies.** Add K21 to the "Contracts: consumes ..." line (RES-133).
- WSP-04: **Dependencies.** Add K21 to the "Contracts: consumes ..." line (RES-133).
- WSP-07: **Dependencies.** Add K21 to the "Contracts: consumes ..." line (RES-133).
- WSP-03: In wsp.md, delete the bullet `` - Reviewer note: this feature opens a K2 sub-state, uses K6's `coral_assign_task` and registers K21 executors. Recommend adding K2, K6 and K21 to the contracts it consumes. `` (resolved by RES-133).
- WSP-07: In wsp.md, delete the bullet `` - Reviewer note: push and fetch add K21 kinds with side effects, but this feature does not consume K21. Recommend adding K21. `` (resolved by RES-133).

### RES-134 · contract · WSP-01, WSP-02, WSP-06, WSP-07

K13 errors are additive; v1 lists op_host_violation, backend_unavailable, git_failed, timeout, and later features add capability_unavailable (WSP-02), disk_cap (WSP-06), push_not_permitted and invalid_ref (WSP-07).

Master edits:
- K13.description += "Errors are additive: v1 op_host_violation, backend_unavailable, git_failed, timeout; later capability_unavailable (WSP-02), disk_cap (WSP-06), push_not_permitted and invalid_ref (WSP-07)."

### RES-135 · contract · WSP-01, SPK-04, EVD-01

K13 v1 text freezes at IM-0 (week 3, M1 exit 7) from SPK-04's draft, signed by the WORKSPACE lead; WSP-01's first PR (week 5) lands it as code without changing it. EVD-01 (weeks 3-5) builds on the frozen text and the fake.

Master edits:
- K13.description += "The v1 interface text freezes at IM-0 from SPK-04's draft (signed by the WORKSPACE lead); WSP-01's first PR lands it as code unchanged, and EVD-01 builds on the frozen text and the fake before then."

Spec edits:
- WSP-01: In wsp.md, replace the bullet `` - Reviewer note: M1 exit item 7 has K13 v1 at IM-0 (week 3), but WSP-01 starts in week 5 and EVD-01 (weeks 3-5) consumes K13. Recommend a WSP-01#K13 slice. `` with `` - Open item (RES-135): M1 exit item 7 has K13 v1 at IM-0 (week 3), but WSP-01 starts in week 5 and EVD-01 (weeks 3-5) consumes K13. K13 text freezes at IM-0 from SPK-04's draft; this feature's first PR lands it as code (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-135 | K13 v1 text freezes at IM-0 (week 3, M1 exit 7) from SPK-04's draft, signed by the WORKSPACE lead; WSP-01's first PR (week 5) lands it as code without changing it. EVD-01 (weeks 3-5) builds on the frozen text and the fake. | WORKSPACE lead (SPK-04, WSP-01) | IM-0, week 3 | If K13 text is not frozen at IM-0, EVD-01 (weeks 3-5) builds on an unstable interface and M1 exit 7 fails. |".

### RES-136 · citation · WSP-01, WSP-02

S40 and S72 ledger rows add omnigent/server/host_registry.py and host_tunnel.py:999-1011, which the ledger and WSP-02's key paths omit.

Master edits:
- notes += "RES-136: Ledger amendment: the S72 row adds omnigent/server/routes/host_tunnel.py:999-1011; the S40 row adds omnigent/server/host_registry.py (pending maps, disconnect failure at :704, :755) and host_tunnel.py."

Spec edits:
- WSP-01: In wsp.md, delete the bullet `` - Reviewer note: the bindings API needs K7 and the `create_run_worktree` executor needs K21; neither is consumed. The S72 ledger row omits `host_tunnel.py:999-1011`. `` (resolved by RES-136).
- WSP-02: In wsp.md, delete the bullet `` - Reviewer note: `key_paths` omits `host_registry.py` and `host_tunnel.py`, which S40 edits. `` (resolved by RES-136).

### RES-137 · edge · WSP-04, WSP-07

Add soft edge WSP-04 -> WSP-07: checkpoints use WSP-07's push and consent.

Master edits:
- WSP-04.soft_deps += WSP-07 (checkpoint push and consent)

Spec edits:
- WSP-04: **Dependencies.** Add WSP-07 to the "Soft:" line (checkpoint push and consent; RES-137).
- WSP-07: **Dependencies.** Add WSP-04 to the soft part of "Downstream, unblocks:" (RES-137).
- WSP-04: In wsp.md, delete the bullet `` - Reviewer note: checkpoints rely on WSP-07's push and consent. Recommend a soft edge WSP-04 -> WSP-07. `` (resolved by RES-137).

### RES-138 · fixed · WSP-01

WSP-01's start_commit waits for the first activation when the rev-parse fallback needs WSP-06's shell; this is a spec-level decision.

Spec edits:
- WSP-01: In wsp.md, replace the bullet `` - Reviewer note: the rev-parse fallback needs WSP-06's later runner shell, so `start_commit` waits for the first activation. `` with `` - The rev-parse fallback needs WSP-06's later runner shell, so `start_commit` waits for the first activation. `` (no longer a reviewer note; settled by RES-138).

### RES-139 · citation · WSP-02

WSP-02's proving test file test_frames.py covers the token; the L2 and fallback asserts live in tests/coral/omni/host/ops/ and K13 conformance.

Master edits:
- notes += "RES-139: WSP-02's proving test: the token assert is in tests/host/test_frames.py; the L2 and fallback asserts are in tests/coral/omni/host/ops/ and the K13 conformance suite."

Spec edits:
- WSP-02: In wsp.md, delete the bullet `` - Reviewer note: the proving test names only `test_frames.py`; the L2 and fallback asserts belong in `tests/coral/omni/host/ops/` and K13 conformance. `` (resolved by RES-139).

### RES-140 · assign · DUR-02, WEB-02, WEB-03, ENG-07

DUR-02 owns GET /v1/coral/templates and POST /v1/coral/templates/{id}:use over ENG-07's package-data templates; K7 names both.

Master edits:
- DUR-02.included += "GET /v1/coral/templates and POST /v1/coral/templates/{id}:use over ENG-07's package-data templates (K7)"
- K7.description += "Template routes GET /v1/coral/templates and POST /v1/coral/templates/{id}:use (DUR-02)."

Spec edits:
- DUR-02: **Ownership boundaries.** Included: add "GET /v1/coral/templates and POST /v1/coral/templates/{id}:use over ENG-07's package-data templates (K7)" (RES-140).
- WEB-03: Excluded: name "template endpoints (DUR-02)". (RES-140)
- WEB-03: In web-a.md, delete the bullet `` - Reviewer note: no master feature includes `GET /v1/coral/templates` or `POST .../templates/{id}:use`. Assign them (DUR-02 is the closest fit). `` (resolved by RES-140).

### RES-141 · split · WEB-01, WEB-12

Failing saved case: WEB-01 lists the expected and actual paths; WEB-12 owns CaseDiff (first divergent box) and reuses WEB-01's failing-case view.

Master edits:
- WEB-01.included: "failing saved case with expected vs actual path" -> "failing saved case listing expected and actual paths (the diff view is WEB-12's)"
- WEB-12.included: "failing case diff with expected vs actual path" -> "failing case diff (CaseDiff, first divergent box) on WEB-01's failing-case view"

Spec edits:
- WEB-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "failing saved case with expected vs actual path" so it says "failing saved case listing expected and actual paths (the diff view is WEB-12's)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-141).
- WEB-12: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "failing case diff with expected vs actual path" so it says "failing case diff (CaseDiff, first divergent box) on WEB-01's failing-case view". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-141).
- WEB-01: In web-a.md, delete the bullet `` - Reviewer note: master gives the failing-case expected-vs-actual view to WEB-01 and WEB-12. WEB-01 lists both paths; WEB-12 owns the diff. `` (resolved by RES-141).

### RES-142 · nongoal · WEB-05, WEB-07, WEB-11

Edits to web/src/shell/SubagentTab.tsx (WEB-05), web/src/pages/settings/ (WEB-07) and web/src/shell/monacoSetup.ts (WEB-11) are non-goals: these key paths are read-only references with no seam; any edit needs an OPS-01 ledger entry first.

Master edits:
- notes += "RES-142: Read-only key paths (no seam; edits are non-goals): web/src/shell/SubagentTab.tsx (WEB-05), web/src/pages/settings/ (WEB-07), web/src/shell/monacoSetup.ts (WEB-11)."

Spec edits:
- WEB-05: In web-a.md, delete the bullet `` - Reviewer note: master key_paths list `web/src/shell/SubagentTab.tsx`, but no seam covers it. This spec leaves it unchanged and composes `SideChatPane`. `` (resolved by RES-142).
- WEB-07: In web-a.md, delete the bullet `` - Reviewer note: the master key path `web/src/pages/settings/` is read-only here, and no seam covers an edit. `` (resolved by RES-142).
- WEB-11: In web-b.md, delete the bullet `` - Reviewer note: key_paths list `web/src/shell/monacoSetup.ts`, an upstream file with no seam. It is imported unchanged; any edit needs an OPS-01 ledger entry. `` (resolved by RES-142).

### RES-143 · assign · WEB-13, WEB-06

There is one label-chip component: WEB-13's PromiseLabelChip (lands at M2). WEB-06 reuses it and adds no LabelChip.tsx. Add soft edge WEB-06 -> WEB-13.

Changed by the challenge pass: CH-07.

Master edits:
- WEB-06.included: "On-box label chips" -> "On-box label chips reusing WEB-13's PromiseLabelChip (no second chip component)"
- WEB-06.soft_deps += WEB-13 (imports PromiseLabelChip)

Spec edits:
- WEB-06: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "On-box label chips" so it says "On-box label chips reusing WEB-13's PromiseLabelChip (no second chip component)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-143).
- WEB-06: **Dependencies.** Add WEB-13 to the "Soft:" line (imports PromiseLabelChip; RES-143).
- WEB-13: **Dependencies.** Add WEB-06 to the soft part of "Downstream, unblocks:" (RES-143).
- WEB-06: Technical scope: remove guarantees/LabelChip.tsx; import WEB-13's PromiseLabelChip. (RES-143)
- WEB-13: In web-b.md, delete the bullet `` - Reviewer note: WEB-06 plans its own `LabelChip.tsx` in `guarantees/`, its key path. It should reuse `PromiseLabelChip` instead. `` (resolved by RES-143).

### RES-144 · split · WEB-04, WEB-10, WEB-13, WEB-01

web/src/workflows/runs/ layout: WEB-04 owns the root; WEB-13 owns runs/list/, runs/outcome/ and runs/phone/; ENG-10 owns runs/restart/; WEB-10 owns runs/depth/ and canvas/overlay/, and its step 1 moves WEB-01's canvas/overlay.ts to canvas/overlay/types.ts.

Changed by the challenge pass: CH-02.

Master edits:
- WEB-10.included += "Adds files only under web/src/workflows/runs/depth/ and canvas/overlay/, plus the per-item list in GTE-02's WorkflowInboxCard; first PR moves WEB-01's canvas/overlay.ts to canvas/overlay/types.ts"

Spec edits:
- WEB-10: **Ownership boundaries.** Included: add "Adds files only under web/src/workflows/runs/depth/ and canvas/overlay/, plus the per-item list in GTE-02's WorkflowInboxCard; first PR moves WEB-01's canvas/overlay.ts to canvas/overlay/types.ts" (RES-144).
- WEB-10: In web-b.md, delete the bullet `` - Reviewer note: WEB-01 ships `canvas/overlay.ts`; step 1 should move it to `canvas/overlay/types.ts` so file and folder do not share an import path. `` (resolved by RES-144).

### RES-145 · assign · WEB-01

WEB-01's "too large" state uses a 200-node threshold, configurable, and is re-checked with the OQ-1 NFRs.

Master edits:
- ui_surfaces[Diagram and preset Simulate].states: "too large" -> "too large (over 200 nodes, configurable)"

Spec edits:
- WEB-01: In web-a.md, delete the bullet `` - Reviewer note: "too large" has no threshold. This spec proposes 200 nodes. `` (resolved by RES-145).

### RES-146 · fixed · WEB-02, WEB-06, WEB-07, WEB-04

Accepted sequencing notes that need no master change: WEB-02's Runs tab shows a placeholder until WEB-13 (week 11); until WEB-08, "on-box" means WEB-01's read-only preview; WEB-07 relies on PRF-02's server-side reinstall to keep params.coral; WEB-04's S35 note restates master §6.4.

Spec edits:
- WEB-02: In web-a.md, replace the bullet `` - Reviewer note: WEB-13 finishes in week 11, so the Runs tab shows a placeholder until then. `` with `` - WEB-13 finishes in week 11, so the Runs tab shows a placeholder until then. `` (no longer a reviewer note; settled by RES-146).
- WEB-04: In web-a.md, replace the bullet `` - Reviewer note: S35 stays unneeded only if steps are children of the anchor (ADR-05); otherwise it moves to SES-03 (master §6.4). `` with `` - S35 stays unneeded only if steps are children of the anchor (ADR-05); otherwise it moves to SES-03 (master §6.4). `` (no longer a reviewer note; settled by RES-146).
- WEB-06: In web-a.md, replace the bullet `` - Reviewer note: until WEB-08, "on-box" means WEB-01's read-only preview. `` with `` - Until WEB-08, "on-box" means WEB-01's read-only preview. `` (no longer a reviewer note; settled by RES-146).
- WEB-07: In web-a.md, replace the bullet `` - Reviewer note: `AgentBundleInput` (`lib/agentBundle.ts:26-36`), the input of `buildAgentBundle` (`:45`), has no params field, so a client-side reinstall would drop `params.coral`. This spec relies on PRF-02's server-side reinstall. `` with `` - `AgentBundleInput` (`lib/agentBundle.ts:26-36`), the input of `buildAgentBundle` (`:45`), has no params field, so a client-side reinstall would drop `params.coral`; this spec relies on PRF-02's server-side reinstall. `` (no longer a reviewer note; settled by RES-146).

### RES-147 · nongoal · WEB-03

No upstream initialPhase edit to HarnessFixDialog: WEB-03's auth failures deep-link to the dialog, and the API-key form is one click away (reconfigure opens on "choose").

Master edits:
- WEB-03.included: "auth failures deep-link to the existing HarnessFixDialog API-key form" -> "auth failures deep-link to the existing HarnessFixDialog (the API-key form is one click away; no upstream initialPhase edit)"

Spec edits:
- WEB-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "auth failures deep-link to the existing HarnessFixDialog API-key form" so it says "auth failures deep-link to the existing HarnessFixDialog (the API-key form is one click away; no upstream initialPhase edit)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-147).
- WEB-03: In web-a.md, delete the bullet `` - Reviewer note: for claude-sdk, `reconfigure` opens on `choose` (`pages/settings/HarnessFixDialog.tsx:135-140, 151`), so the API-key form is one click away. An `initialPhase` prop is an upstream edit no seam covers. `` (resolved by RES-147).

### RES-148 · nongoal · WEB-05

Changing the upstream anchor composer copy ("This sub-agent session is closed") is a non-goal: no seam covers it, and the S86 banner explains.

Spec edits:
- WEB-05: In web-a.md, delete the bullet `` - Reviewer note: under `omnigent.closed=true`, the anchor composer reads "This sub-agent session is closed" (`lib/sessionCapabilities.ts:143`). Fixing that copy needs an edit no seam covers, so the S86 banner explains instead. `` (resolved by RES-148).

### RES-149 · residual · WEB-05, SES-03, RUL-01, SPK-02

If SPK-02 probe (e) fails, SES-03 uses RUL-01's DENY instead of omnigent.closed; the upstream anchor composer stays enabled and only the S86 banner explains.

Spec edits:
- WEB-05: In web-a.md, replace the bullet `` - Reviewer note: if SPK-02 probe (e) fails, SES-03 uses RUL-01's DENY instead of `omnigent.closed`; the upstream anchor composer then stays enabled and only the banner explains. `` with `` - Open item (RES-149): If SPK-02 probe (e) fails (week 2), SES-03 uses RUL-01's DENY instead of `omnigent.closed`; the upstream anchor composer then stays enabled and only the banner explains (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-149 | If SPK-02 probe (e) fails, SES-03 uses RUL-01's DENY instead of omnigent.closed; the upstream anchor composer stays enabled and only the S86 banner explains. | SPK-02 (probe e) with SES-03 | Week 2 | If (e) fails, users can type into the anchor; RUL-01 denies the tools and WEB-05's banner is the only explanation. |".

### RES-150 · contract · DUR-02, RUL-06, WEB-08, ENG-10, API-02, WEB-10, WEB-09, WEB-06, WEB-11, WEB-12, WEB-13

Additive K7 fields, one owner each: :validate returns the compiled graph (DUR-02, for WEB-11) and labels (RUL-06, for WEB-06); drafts carry a layout field (WEB-08, a small backend PR in DUR-02's store reviewed by the PLATFORM lead); versions expose case_results (DUR-02, which already stores CaseResult, for WEB-12); the outcome carries repo path and worktree state and runs-list rows carry a path summary (API-02, for WEB-13); the log endpoint gains arrow_id and scope_key filters (WEB-10, reviewed by API-02's owner). WEB-09, RUL-06 and ENG-10 (versions, diff and restart routes) consume K7. Soft edges WEB-08 -> DUR-02 and WEB-10 -> API-02 record the backend PRs.

Changed by the challenge pass: CH-01.

Master edits:
- DUR-02.included += "case_results on the version resource, the read path for the CaseResult rows it already stores (additive K7, for WEB-12's saved-test badges)"
- DUR-02.included += ":validate returns the compiled graph (additive K7, for the WEB-11 preview)"
- RUL-06.included += ":validate returns per-mode labels (additive K7, for WEB-06)"
- WEB-08.included += "Additive K7 layout field on the draft PUT, as a small backend PR in DUR-02's store reviewed by the PLATFORM lead"
- API-02.included += "Outcome repo path and worktree state, and a path summary on runs-list rows (additive K7, for WEB-13)"
- WEB-10.included += "arrow_id and scope_key filters on API-02's log endpoint (additive K7, reviewed by API-02's owner)"
- WEB-09.contracts_consumed += K7; K7.consumers += WEB-09
- RUL-06.contracts_consumed += K7; K7.consumers += RUL-06
- ENG-10.contracts_consumed += K7; K7.consumers += ENG-10
- K7.description += "Additive fields: :validate returns the compiled graph (DUR-02) and labels (RUL-06); drafts carry layout (WEB-08); versions carry case_results (DUR-02); outcome carries repo path and worktree state, and runs-list rows a path summary (API-02); the log takes arrow_id and scope_key filters (WEB-10)."
- WEB-08.soft_deps += DUR-02 (layout field PR in DUR-02's draft store)
- WEB-10.soft_deps += API-02 (arrow_id and scope_key filters on API-02's log endpoint)

Spec edits:
- DUR-02: **Ownership boundaries.** Included: add "case_results on the version resource, the read path for the CaseResult rows it already stores (additive K7, for WEB-12's saved-test badges)" (RES-150).
- DUR-02: **Ownership boundaries.** Included: add ":validate returns the compiled graph (additive K7, for the WEB-11 preview)" (RES-150).
- RUL-06: **Ownership boundaries.** Included: add ":validate returns per-mode labels (additive K7, for WEB-06)" (RES-150).
- WEB-08: **Ownership boundaries.** Included: add "Additive K7 layout field on the draft PUT, as a small backend PR in DUR-02's store reviewed by the PLATFORM lead" (RES-150).
- API-02: **Ownership boundaries.** Included: add "Outcome repo path and worktree state, and a path summary on runs-list rows (additive K7, for WEB-13)" (RES-150).
- WEB-10: **Ownership boundaries.** Included: add "arrow_id and scope_key filters on API-02's log endpoint (additive K7, reviewed by API-02's owner)" (RES-150).
- WEB-09: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-150).
- RUL-06: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-150).
- ENG-10: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-150).
- WEB-08: **Dependencies.** Add DUR-02 to the "Soft:" line (layout field PR in DUR-02's draft store; RES-150).
- DUR-02: **Dependencies.** Add WEB-08 to the soft part of "Downstream, unblocks:" (RES-150).
- WEB-10: **Dependencies.** Add API-02 to the "Soft:" line (arrow_id and scope_key filters on API-02's log endpoint; RES-150).
- API-02: **Dependencies.** Add WEB-10 to the soft part of "Downstream, unblocks:" (RES-150).
- WEB-06: In web-a.md, delete the bullet `` - Reviewer note: K7 does not yet define labels on `:validate`. API-01 must add them additively, with producer approval. `` (resolved by RES-150).
- WEB-08: In web-b.md, delete the bullet `` - Reviewer note: DUR-02's draft has no layout field. K7 must add `layout` additively. `` (resolved by RES-150).
- WEB-09: In web-b.md, delete the bullet `` - Reviewer note: this feature calls K7 endpoints (`:validate`, blocks), but the master lists only K1, K9 and K15. Add K7. `` (resolved by RES-150).
- WEB-10: In web-b.md, delete the bullet `` - Reviewer note: API-02's log endpoint needs `arrow_id` and `scope_key` filters (additive K7), or why-not fails past WEB-04's 2,000-entry ring. `` (resolved by RES-150).
- WEB-11: In web-b.md, delete the bullet `` - Reviewer note: DUR-02 does not say `:validate` returns the compiled graph, which the preview needs; add it additively. `` (resolved by RES-150).
- WEB-12: In web-b.md, delete the bullet `` - Reviewer note: DUR-02 stores `CaseResult` but exposes no read path. K7 needs one additively, for example `case_results` on the version. `` (resolved by RES-150).
- WEB-13: In web-b.md, delete the bullet `` - Reviewer note: API-02's outcome lacks the repo path and worktree state; git refuses to switch to a branch another worktree has checked out. Add both additively. `` (resolved by RES-150).
- WEB-13: In web-b.md, delete the bullet `` - Reviewer note: PC-15 asks for a path summary, which K7 list rows lack. `` (resolved by RES-150).

### RES-151 · contract · API-01, GTE-01, API-02

K7 picks one stale-answer code: 409 stale_visit for GTE-01 and API-02 (not gate_not_current); typed not_permitted is HTTP 403. The error-code list lives in API-01's spec, so API-01 changes it; GTE-01 returns a K7 code, so it consumes K7.

Changed by the challenge pass: CH-17.

Master edits:
- K7.description += "A stale gate answer returns 409 stale_visit everywhere (GTE-01 and API-02)."
- GTE-01.contracts_consumed += K7; K7.consumers += GTE-01

Spec edits:
- GTE-01: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-151).
- API-02: Technical scope, gate answers bullet: replace "A stale token returns 409 `gate_not_current`" with "A stale token returns 409 `stale_visit`". (RES-151)
- API-01: Technical scope, Errors bullet: in the Codes list replace "`illegal_transition`, `gate_not_current`, `stream_limit`" with "`illegal_transition`, `stale_visit`, `stream_limit`". (RES-151)

Section edits:
- D: D.4 "Human gate" step 5: replace "named `stale_visit` in GTE-01 but `gate_not_current` in API-02, so K7 must pick one" with "named `stale_visit` everywhere (K7, master v3)". (RES-151)

### RES-152 · split · WEB-08, ENG-09, WEB-09

WEB-08 step 5 (group-membership patches) builds on K1's group kind and members key, reserved at IM-0 (RES-027), so it does not wait for ENG-09 and never moves to WEB-09. ENG-09's Group IR (named, reusable groups and group rules) reaches the canvas through WEB-09.

Changed by the challenge pass: CH-10.

Master edits:
- WEB-08.included += "Group-membership patches on K1's group kind and members key (reserved at IM-0); named, reusable groups and group rules are ENG-09's and WEB-09's"

Spec edits:
- WEB-08: **Ownership boundaries.** Included: add "Group-membership patches on K1's group kind and members key (reserved at IM-0); named, reusable groups and group rules are ENG-09's and WEB-09's" (RES-152).
- WEB-08: Implementation breakdown step 5: replace "Group-membership patches, once ENG-09's keys are fixed in K1." with "Group-membership patches on K1's group kind and `members` key (reserved at IM-0)." (RES-152)
- WEB-08: In web-b.md, replace the bullet `` - Reviewer note: if ENG-09's group keys (weeks 18-22.5) are not stable by week 19, step 5 moves to WEB-09. `` with `` - Group-membership patches use K1's group kind and `members` key, reserved at IM-0 (master v3), so step 5 does not wait for ENG-09. `` (no longer a reviewer note; settled by RES-152).

### RES-153 · nongoal · WEB-13, SPK-05

WEB-13's run-end analytics events stay client-side through the host analytics sink (web/src/lib/analytics.ts; the server has no product-analytics pipeline). Each fires once per run and browser and carries the run id, so metrics count distinct run ids and a run opened on two devices is not double counted. Server-side emission is a non-goal through M4; OQ-26 (SPK-05, week 4) still picks the metrics.

Changed by the challenge pass: CH-21.

Master edits:
- WEB-13.included: "Analytics events 'run completed', 'run failed' and 'run cancelled'" -> "Analytics events 'run completed', 'run failed' and 'run cancelled', client-side through the host analytics sink, once per run and browser, carrying the run id so metrics count distinct runs (server-side emission is a non-goal through M4)"

Spec edits:
- WEB-13: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Analytics events 'run completed', 'run failed' and 'run cancelled'" so it says "Analytics events 'run completed', 'run failed' and 'run cancelled', client-side through the host analytics sink, once per run and browser, carrying the run id so metrics count distinct runs (server-side emission is a non-goal through M4)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-153).
- WEB-13: In web-b.md, replace the bullet `` - Reviewer note: client-side events can double count across devices; server-side emission is safer (OQ-26). `` with `` - Events fire once per run and browser and carry the run id, so metrics count distinct run ids. Server-side emission is a non-goal through M4: product analytics is the client host sink (`web/src/lib/analytics.ts`), and the server has no analytics pipeline (master v3; OQ-26 picks the metrics). `` (no longer a reviewer note; settled by RES-153).

Section edits:
- J: J.3.1 OQ-26 row: append "; run-end events stay client-side and carry the run id, so metrics count distinct runs (master v3)" to the Recommendation cell. (RES-153)

### RES-154 · split · BRD-01, BRD-03

S89 splits: BRD-01 keeps the web brand strings (S89); BRD-03 owns the Electron setup and connect pages as S89b.

Changed by the challenge pass: CH-14.

Master edits:
- BRD-03.included: "Setup and connect pages" -> "Electron setup and connect pages (S89b, split from BRD-01's S89 row)"
- notes += "RES-154: Seam ledger amendment: S89 (BRD-01) keeps the web brand strings; the Electron setup and connect pages become S89b owned by BRD-03."
- BRD-03.seams += S89b

Spec edits:
- BRD-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Setup and connect pages" so it says "Electron setup and connect pages (S89b, split from BRD-01's S89 row)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-154).
- BRD-03: **Technical scope.** Modify or extend upstream: add S89b to the seams this feature lands (RES-154).
- BRD-01: In brd.md, delete the bullet `` - Reviewer note: S89 (BRD-01) lists the Electron setup and connect pages, which BRD-03 includes. Split the ledger row. `` (resolved by RES-154).

### RES-155 · nongoal · BRD-03

Android run deep links are a non-goal through M4 (no custom-scheme handler, AndroidManifest.xml:39-77); S38 covers Electron and iOS.

Master edits:
- BRD-03.included: "run deep links (S38)" -> "run deep links on Electron and iOS (S38); Android scheme links are a non-goal through M4"

Spec edits:
- BRD-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "run deep links (S38)" so it says "run deep links on Electron and iOS (S38); Android scheme links are a non-goal through M4". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-155).
- BRD-03: In brd.md, delete the bullet `` - Reviewer note: Android has no custom-scheme handler (`web/android/app/src/main/AndroidManifest.xml:39-77`), so S38 covers Electron and iOS only. `` (resolved by RES-155).

### RES-156 · citation · BRD-03, BRD-02

Master proving-test readings: BRD-03's link is coral://<host>/workflows/runs/<id> (a hostless link parses "workflows" as the host); BRD-02's "unknown routes no longer light New session" means the Coral desk paths.

Master edits:
- notes += "RES-156: Proving-test readings: BRD-03's link is coral://<host>/workflows/runs/<id>; BRD-02's 'unknown routes no longer light New session' means the Coral desk paths, the only ones isNewSessionRoute excludes."

Spec edits:
- BRD-02: In brd.md, delete the bullet `` - Reviewer note: the proof's "unknown routes" means Coral desk paths, the only ones excluded. `` (resolved by RES-156).
- BRD-03: In brd.md, delete the bullet `` - Reviewer note: the master's proof link has no host, so `workflows` parses as the host; use `coral://<host>/workflows/runs/<id>`. `` (resolved by RES-156).

### RES-157 · citation · BRD-03

"About 37 literals" counts main.js only; desktop_updater.js, quitConfirmation.js:28 and :31, and ssh_connect.js also show "Omnigent".

Master edits:
- BRD-03.included: "Electron brand.js constants for about 37 literals" -> "Electron brand.js constants for about 37 literals in main.js plus those in desktop_updater.js, quitConfirmation.js and ssh_connect.js"

Spec edits:
- BRD-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Electron brand.js constants for about 37 literals" so it says "Electron brand.js constants for about 37 literals in main.js plus those in desktop_updater.js, quitConfirmation.js and ssh_connect.js". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-157).
- BRD-03: In brd.md, delete the bullet `` - Reviewer note: "about 37 literals" is `main.js` only; `desktop_updater.js`, `quitConfirmation.js:28, 31` and `ssh_connect.js` also show "Omnigent". `` (resolved by RES-157).

### RES-158 · edge · BRD-02, BRD-03, OPS-01

BRD-02 consumes K16 (it lands three upstream seams) with a soft edge to OPS-01; add soft edge BRD-03 -> BRD-02 (the deep-link proof needs BRD-02's routes).

Master edits:
- BRD-02.contracts_consumed += K16; K16.consumers += BRD-02
- BRD-02.soft_deps += OPS-01 (K16 ledger for S34, S80 and S84)
- BRD-03.soft_deps += BRD-02 (run routes for the deep-link proof)

Spec edits:
- BRD-02: **Dependencies.** Add K16 to the "Contracts: consumes ..." line (RES-158).
- BRD-02: **Dependencies.** Add OPS-01 to the "Soft:" line (K16 ledger for S34, S80 and S84; RES-158).
- OPS-01: **Dependencies.** Add BRD-02 to the soft part of "Downstream, unblocks:" (RES-158).
- BRD-03: **Dependencies.** Add BRD-02 to the "Soft:" line (run routes for the deep-link proof; RES-158).
- BRD-02: **Dependencies.** Add BRD-03 to the soft part of "Downstream, unblocks:" (RES-158).
- BRD-02: In brd.md, delete the bullet `` - Reviewer note: the three upstream seams need K16, which the contracts omit. `` (resolved by RES-158).
- BRD-03: In brd.md, delete the bullet `` - Reviewer note: the proof needs BRD-02's routes. Add BRD-02 as a soft dependency. `` (resolved by RES-158).

### RES-159 · citation · BRD-02

withPageView is module-private (App.tsx:24-29), so the route fragment is coralRoutes(prefix, withPageView).

Changed by the challenge pass: CH-27.

Master edits:
- BRD-02.included: "coralRoutes(prefix) fragment with withPageView" -> "coralRoutes(prefix, withPageView) fragment (withPageView is module-private in App.tsx)"

Spec edits:
- BRD-02: In brd.md, delete the bullet `` - Reviewer note: `withPageView` is module-private, so the call is `coralRoutes(prefix, withPageView)`. `` (resolved by RES-159).

### RES-160 · fixed · BRD-01, BRD-02, BRD-03

Spec length overruns (a few specs at 901-974 words) are accepted; deleting the resolved Reviewer notes per this log brings most under 900.

### RES-161 · nongoal · BRD-03, OPS-05

Store listings, mobile bundle ids and signing are a non-goal through M4 (OQ-31 has no answer and mobile push is deferred, G-37).

Changed by the challenge pass: CH-15.

Master edits:
- BRD-03.excluded: "Store listings (OQ-31)" -> "Store listings, mobile bundle ids and signing (non-goal through M4; OQ-31)"

Spec edits:
- BRD-03: Ownership boundaries, Excluded: replace "store listings, mobile bundle ids and signing (OQ-31)" with "store listings, mobile bundle ids and signing (non-goal through M4; OQ-31)". (RES-161)

### RES-162 · residual · OPS-03, OPS-05

_default_runner_id_path (runner/identity.py:239-244), admin_list.py:73 and codex_native/app_server.py:1863 ignore OMNIGENT_DATA_DIR. OPS-03's isolation test covers them; any fix is a generic upstream-only PR through OPS-05, not a fork seam. S75 enables no update channel, so _CACHE_DIR needs no fork change.

Master edits:
- OPS-03.included: "Isolation test: no writes to ~/.omnigent and no newer-DB lockout" -> "Isolation test: no writes to ~/.omnigent and no newer-DB lockout, covering the runner-id, admin-list and codex app-server writers (fixes go upstream through OPS-05)"

Spec edits:
- OPS-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Isolation test: no writes to ~/.omnigent and no newer-DB lockout" so it says "Isolation test: no writes to ~/.omnigent and no newer-DB lockout, covering the runner-id, admin-list and codex app-server writers (fixes go upstream through OPS-05)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-162).
- OPS-03: In ops-a.md, replace the bullet `` - Reviewer note: fixing a reachable writer edits an upstream file that S75 does not cover; it needs a new seam id or an upstream-only PR. `` with `` - Open item (RES-162): Fixing a reachable writer (`_default_runner_id_path`, `admin_list.py:73`, `codex_native/app_server.py:1863`) edits an upstream file that S75 does not cover; it goes upstream through OPS-05, and `coral` sets `OMNIGENT_RUNNER_ID` meanwhile (tracked in J.6). ``.
- OPS-03: In ops-a.md, delete the bullet `` - Reviewer note: if S75 enables a channel, `_CACHE_DIR` also needs the data-dir override (a generic, upstreamable fix). `` (resolved by RES-162).

Section edits:
- J: J.6: add the row "| RES-162 | _default_runner_id_path (runner/identity.py:239-244), admin_list.py:73 and codex_native/app_server.py:1863 ignore OMNIGENT_DATA_DIR. OPS-03's isolation test covers them; any fix is a generic upstream-only PR through OPS-05, not a fork seam. S75 enables no update channel, so _CACHE_DIR needs no fork change. | OPS-03 | Week 6 (OPS-03 finish) | If coral can reach a writer that ignores OMNIGENT_DATA_DIR, the isolation test fails until OPS-05's upstream PR merges; coral sets OMNIGENT_RUNNER_ID as a stopgap. |".

### RES-163 · contract · OPS-01, FND-01

Upstream PR links live in .coral/upstream.yaml keyed by seam id (with the pin and merge history), as DoD 6.1 item 2 and ten specs say; seams.yaml holds seam definitions and the upstream-first flag.

Master edits:
- OPS-01.included: "an upstream-first flag and the upstream PR link" -> "and an upstream-first flag; upstream PR links live in .coral/upstream.yaml keyed by seam id (DoD 6.1 item 2)"
- K16.description: "seams.yaml and upstream.yaml: seam id, files, CORAL(Sx) anchors, tests, budget lines and exceptions, upstream-first flag, upstream PR link, owner feature." -> "seams.yaml: seam id, files, CORAL(Sx) anchors, tests, budget lines and exceptions, upstream-first flag, owner feature; upstream.yaml: the upstream pin, merge history and upstream PR links keyed by seam id."

Spec edits:
- OPS-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "an upstream-first flag and the upstream PR link" so it says "and an upstream-first flag; upstream PR links live in .coral/upstream.yaml keyed by seam id (DoD 6.1 item 2)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-163).
- OPS-01: Technical scope: move `upstream_pr` out of the seams.yaml entry schema into upstream.yaml as `prs: {<seam id>: {url, state}}`; rule 5 ("Upstream-first: such an entry cannot land without `upstream_pr`") checks upstream.yaml. (RES-163)
- OPS-01: In ops-a.md, delete the bullet `` - Reviewer note: §6.1 item 2 says upstream PRs go in `upstream.yaml`; OPS-01's master scope says `seams.yaml`, used here. FND-01's spec follows §6.1. `` (resolved by RES-163).

### RES-164 · fixed · OPS-01

OPS-01 pins the fork point 2a9cbe2c2 for the first ledger (4 commits past nightly^1); later merges pin a nightly^1. The spec already decides this.

Spec edits:
- OPS-01: In ops-a.md, replace the bullet `` - Reviewer note: the fork point `2a9cbe2c2` is 4 commits past nightly^1 (`ee7a319f7`); a nightly^1 pin would flag them as fork edits. This spec pins the fork point; later merges pin a nightly^1. `` with `` - The fork point `2a9cbe2c2` is 4 commits past nightly^1 (`ee7a319f7`); a nightly^1 pin would flag them as fork edits, so the first pin is the fork point and later merges pin a nightly^1. `` (no longer a reviewer note; settled by RES-164).

### RES-165 · citation · OPS-02

OPS-02's proof (two real merges two weeks apart) closes near week 6, after its week-4 planned finish. Nothing depends on OPS-02 before week 13.5 (BRD-03 soft; OPS-04 and OPS-05 hard from week 21), the merges are the rotating merge owner's work, and a failed merge is RK-02. Nothing is left to decide.

Changed by the challenge pass: CH-21.

Spec edits:
- OPS-02: In ops-a.md, replace the bullet `` - Reviewer note: two merges two weeks apart close the proof near week 6, after the week-4 finish. `` with `` - Two merges two weeks apart close the proof near week 6, after the week-4 finish; no dependent starts before week 13.5, and a failed merge is handled as RK-02. `` (no longer a reviewer note; settled by RES-165).

Section edits:
- H: H.1 track table, OPS-T1 row: replace "OPS-01 0-2, OPS-02 2-4, OPS-06 4-6" with "OPS-01 0-2, OPS-02 2-4 (proof to about week 6 through the merge rota), OPS-06 4-6". (RES-165)

### RES-166 · fixed · OPS-02

coral-compat.yml replaces editing server-compat.yml's path filter (no seam covers it); the spec already decides this.

Spec edits:
- OPS-02: In ops-a.md, replace the bullet `` - Reviewer note: `coral-compat.yml` replaces editing `server-compat.yml`'s path filter, which no seam covers. `` with `` - `coral-compat.yml` replaces editing `server-compat.yml`'s path filter, which no seam covers. `` (no longer a reviewer note; settled by RES-166).

### RES-167 · assign · OPS-04

OPS-04 loads the Coral plugin through a BenchEnvironment subclass that overrides _spawn_server (no upstream edit); an upstream extra_server_config parameter is optional through OPS-05.

Master edits:
- OPS-04.included: "Coral load scenario in dev/loadtest (concurrent runs, SQLite contention) against the OQ-1 NFRs;" -> "Coral load scenario in dev/loadtest (concurrent runs, SQLite contention) against the OQ-1 NFRs, loading the plugin through a BenchEnvironment subclass that overrides _spawn_server;"

Spec edits:
- OPS-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Coral load scenario in dev/loadtest (concurrent runs, SQLite contention) against the OQ-1 NFRs;" so it says "Coral load scenario in dev/loadtest (concurrent runs, SQLite contention) against the OQ-1 NFRs, loading the plugin through a BenchEnvironment subclass that overrides _spawn_server;". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-167).
- OPS-04: In ops-a.md, replace the line `` - Modify or extend upstream: None planned; a plugin-config hook is open (reviewer note). `` with `` - Modify or extend upstream: none; the Coral plugin loads through a `BenchEnvironment` subclass that overrides `_spawn_server`. `` (RES-167).
- OPS-04: In ops-a.md, delete the bullet `` - Reviewer note: `BenchEnvironment` hard-codes its server config (`dev/benchmarks/omnigent/environment.py:681-696`), so it cannot load the Coral plugin. Recommend an upstream-first `extra_server_config` parameter under a new seam id. The fallback is a subclass overriding `_spawn_server` (654). `` (resolved by RES-167).

### RES-168 · assign · OPS-01, OPS-04

OPS-01 adds dev/loadtest/coral/ to the fork guard's allowed roots as a new-files-only root.

Master edits:
- OPS-01.included: "coral/fork/check_seams.py: allowed roots" -> "coral/fork/check_seams.py: allowed roots (including dev/loadtest/coral/ as new-files-only)"

Spec edits:
- OPS-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "coral/fork/check_seams.py: allowed roots" so it says "coral/fork/check_seams.py: allowed roots (including dev/loadtest/coral/ as new-files-only)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-168).
- OPS-04: In ops-a.md, delete the bullet `` - Reviewer note: add `dev/loadtest/coral/` to OPS-01's allowed roots as a new-files-only root. `` (resolved by RES-168).

### RES-169 · assign · OPS-05

OPS-05 finishes at week 23 but co-owns IM-8 at week 25.5, so it re-runs the drill (one day) in week 25 to keep the evidence current.

Changed by the challenge pass: CH-12.

Master edits:
- OPS-05.included += "A one-day drill re-run in week 25 so IM-8 evidence is current"

Spec edits:
- OPS-05: **Ownership boundaries.** Included: add "A one-day drill re-run in week 25 so IM-8 evidence is current" (RES-169).
- OPS-05: In ops-a.md, replace the bullet `` - Reviewer note: OPS-05 finishes in week 23 but co-owns IM-8 in week 25.5. Re-run the drill (one day) in week 25 so the evidence is current. `` with `` - This feature finishes in week 23 but co-owns IM-8 in week 25.5, so it re-runs the drill (one day) in week 25 to keep the evidence current. `` (no longer a reviewer note; settled by RES-169).

### RES-170 · residual · OPS-06

OPS-06 (weeks 4-6) precedes GTE-01, PRF-01, API-02 and GTE-06; it adds a second pass at IM-3 (week 11.5) and sign-offs near weeks 13.5 and 18, about 0.5 week of WS-OPS tail.

Master edits:
- OPS-06.included += "Second review pass at IM-3 (week 11.5) for GTE-01's S6b check, API-02 and GTE-06; sign-offs near weeks 13.5 and 18"

Spec edits:
- OPS-06: **Ownership boundaries.** Included: add "Second review pass at IM-3 (week 11.5) for GTE-01's S6b check, API-02 and GTE-06; sign-offs near weeks 13.5 and 18" (RES-170).
- OPS-06: In ops-b.md, replace the bullet `` - Reviewer note: weeks 4-6 precede GTE-01 (7-9) and PRF-01 (to 9.5); tracking runs to 13.5 and sign-offs fall near 13.5 and 18. Budget about 0.5 week of WS-OPS tail. `` with `` - Open item (RES-170): Weeks 4-6 precede GTE-01 (7-9) and PRF-01 (to 9.5); a second pass runs at IM-3 and sign-offs fall near 13.5 and 18, about 0.5 week of WS-OPS tail (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-170 | OPS-06 (weeks 4-6) precedes GTE-01, PRF-01, API-02 and GTE-06; it adds a second pass at IM-3 (week 11.5) and sign-offs near weeks 13.5 and 18, about 0.5 week of WS-OPS tail. | OPS-06 (OPS lead) | IM-3 (week 11.5), then weeks 13.5 and 18 | About 0.5 week of unplanned WS-OPS load; M2 exit 14 depends on the IM-3 pass. |".

### RES-171 · residual · OPS-02

OPS-02's "Dependabot off for upstream manifests" has no verified mechanism: editing .github/dependabot.yml is an unledgered upstream edit, and repository settings alone are unverified.

Section edits:
- J: J.6: add the row "| RES-171 | OPS-02's "Dependabot off for upstream manifests" has no verified mechanism: editing .github/dependabot.yml is an unledgered upstream edit, and repository settings alone are unverified. | OPS-02 | Week 4 | Dependabot PRs against upstream manifests would add merge noise. |".

### RES-172 · residual · OPS-07, SPK-05

A one-week soak gives seven nightlies against a 9-of-10 threshold. The soak counts the last ten credentialed runs, including on-demand runs from IM-2, which needs the OQ-51 bench budget.

Spec edits:
- OPS-07: In ops-b.md, replace the bullet `` - Reviewer note: a soak week has seven nightlies against a "9 of 10" threshold; run twice nightly or widen the window. `` with `` - Open item (RES-172): A soak week has seven nightlies against a "9 of 10" threshold; the soak counts the last ten credentialed runs, including on-demand runs from IM-2, which needs the OQ-51 budget (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-172 | A one-week soak gives seven nightlies against a 9-of-10 threshold. The soak counts the last ten credentialed runs, including on-demand runs from IM-2, which needs the OQ-51 bench budget. | OPS-07 with Ops (OQ-51) | Week 9.5 (OQ-51 deadline) | Without budget for on-demand runs, M2 exit 2 cannot reach ten runs in the soak week. |".

### RES-173 · residual · OPS-07

IM-3 and IM-4 are dated week 11.5, OPS-07's own start, so its lane build-out runs from about week 9.5 in OPS-T2 free time; no feature represents that work.

Spec edits:
- OPS-07: In ops-b.md, replace the bullet `` - Reviewer note: IM-3 and IM-4 are dated week 11.5, this feature's start, so step 1 starts about week 9.5. `` with `` - Open item (RES-173): IM-3 and IM-4 are dated week 11.5, this feature's start, so step 1 starts about week 9.5 in OPS-T2 free time (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-173 | IM-3 and IM-4 are dated week 11.5, OPS-07's own start, so its lane build-out runs from about week 9.5 in OPS-T2 free time; no feature represents that work. | OPS lead (OPS-T2) | Week 9.5 | IM-3 and IM-4 slip if the lanes are not ready by week 11.5. |".

### RES-174 · fixed · OPS-07

OPS-07 keeps latency asserts in the nightly (shared-runner budgets in tests/budgets.py), and its engine-upgrade old-build variant adds a coral-e2e.yml input; both are in the spec.

Spec edits:
- OPS-07: In ops-b.md, replace the bullet `` - Reviewer note: latency asserts on shared runners contradict `tests/budgets.py:21-36`, hence `nightly`. The e2e action builds old servers only from release tags (`action.yml:140-163`); the old-build variant needs a new input, outside credentialed-only `coral-e2e.yml`. `` with `` - Latency asserts on shared runners would contradict `tests/budgets.py:21-36`, so they run in the nightly. The e2e action builds old servers only from release tags (`action.yml:140-163`), so the old-build variant adds an input to `coral-e2e.yml`. `` (no longer a reviewer note; settled by RES-174).

### RES-175 · assign · OPS-08, SPK-05

OPS-08 checks that SPK-05's OQ-28 and OQ-35 records exist (SPK-05 owns them); M4 structure work is ENG-08 and SES-10 code and OPS-09's journey.

Changed by the challenge pass: CH-15.

Master edits:
- OPS-08.included: "OQ-28 and OQ-35 written answers recorded, or the fallback applied" -> "Checks that SPK-05's OQ-28 and OQ-35 records exist, or that the fallback was applied"
- OPS-08.excluded: "M4 structure work" -> "M4 structure work (ENG-08 and SES-10 code; OPS-09 journey)"

Spec edits:
- OPS-08: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "OQ-28 and OQ-35 written answers recorded, or the fallback applied" so it says "Checks that SPK-05's OQ-28 and OQ-35 records exist, or that the fallback was applied". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-175).

### RES-176 · residual · OPS-08, HRN-07

OPS-08 starts the day HRN-07 finishes (week 20), so there is no slack before M3; subscription auth cannot be shown in CI, so M3 exit 8 on subscription auth is proven in dogfood.

Spec edits:
- OPS-08: In ops-b.md, replace the bullet `` - Reviewer note: HRN-07 finishes at week 20, the day this lane starts, so there is no slack before M3. `` with `` - Open item (RES-176): HRN-07 finishes at week 20, the day this lane starts, so there is no slack before M3; subscription-auth proof is dogfood-only (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-176 | OPS-08 starts the day HRN-07 finishes (week 20), so there is no slack before M3; subscription auth cannot be shown in CI, so M3 exit 8 on subscription auth is proven in dogfood. | OPS-08 (OPS lead) | Week 20 | Any HRN-07 slip moves M3; M3 exit 8 rests on a dogfood run. |".

### RES-177 · contract · OPS-09

OPS-09 lists OQ-29, which decides its reviewer variant.

Master edits:
- OPS-09.open_questions += OQ-29

Spec edits:
- OPS-09: Add OQ-29 to the open questions this spec records or cites (**Risks and open questions.**; RES-177).
- OPS-09: In ops-b.md, delete the bullet `` - Reviewer note: OQ-29 governs this lane but is missing from its `open_questions`. `` (resolved by RES-177).

### RES-178 · residual · OPS-09, WEB-09, BRD-03

OPS-09 starts the day WEB-09 finishes (week 24.5); the coral:// step has no CI Electron lane and is proven in dogfood on a packaged build.

Spec edits:
- OPS-09: In ops-b.md, replace the bullet `` - Reviewer note: WEB-09 finishes at week 24.5, the day this lane starts. The `coral://` step has no CI Electron lane; it is proven in dogfood on a packaged build. `` with `` - Open item (RES-178): WEB-09 finishes at week 24.5, the day this lane starts; the `coral://` step has no CI Electron lane and is proven in dogfood on a packaged build (tracked in J.6). ``.

Section edits:
- J: J.6: add the row "| RES-178 | OPS-09 starts the day WEB-09 finishes (week 24.5); the coral:// step has no CI Electron lane and is proven in dogfood on a packaged build. | OPS-09 (OPS lead) | Week 24.5 | A WEB-09 slip moves M4; the deep-link step is dogfood-only. |".

### RES-179 · residual · TLS-01, OPS-06, GTE-03

The CLI server always builds a permission store (cli.py:4912), so multi_user is always true and the single-user early return in _require_cost_control_label_authority never fires. The S49 predicate, the OQ-43 default and GTE-03's loopback-http rule need an explicit single-user definition from TLS-01.

Section edits:
- J: J.6: add the row "| RES-179 | The CLI server always builds a permission store (cli.py:4912), so multi_user is always true and the single-user early return in _require_cost_control_label_authority never fires. The S49 predicate, the OQ-43 default and GTE-03's loopback-http rule need an explicit single-user definition from TLS-01. | TLS-01 with OPS-06 | Week 3 (TLS-01's S49 PR) | OQ-43's "accept on single-user servers" never applies; the M4 webhook test may need an https receiver. |".

### RES-180 · nongoal · EXT-03, WEB-03

Web git import and listing imported templates in WEB-03's gallery are non-goals; EXT-03 imports through the CLI and API only.

Master edits:
- EXT-03.excluded += "Web git import and listing imported templates in WEB-03's gallery (non-goal)"

Spec edits:
- EXT-03: **Ownership boundaries.** Excluded: add "Web git import and listing imported templates in WEB-03's gallery (non-goal)" (RES-180).
- EXT-03: In ext.md, replace the line `` - Excluded: repo-canonical editing, sync daemon, marketplace (deferred); repo import into drafts (WSP-01); profile revisions (PRF-02); gallery cards (WEB-03; listing imported templates there is unowned, Reviewer note); grants (EXT-04); commit and push (the user). `` with `` - Excluded: repo-canonical editing, sync daemon, marketplace (deferred); repo import into drafts (WSP-01); profile revisions (PRF-02); gallery cards (WEB-03); web git import and listing imported templates in the gallery (non-goal); grants (EXT-04); commit and push (the user). `` (RES-180).

### RES-181 · citation · EXT-03

EXT-03's proving-test path .coral/<id>.yaml resolves to .coral/workflows/<key>.yaml (D§12 and WSP-01's import).

Master edits:
- notes += "RES-181: EXT-03's proving test path .coral/<id>.yaml means .coral/workflows/<key>.yaml (D§12; WSP-01's import)."

Spec edits:
- EXT-03: In ext.md, replace the line `` - Proving test (`test_sharing.py`, host tests): exporting a version writes `.coral/<id>.yaml` (here `.coral/workflows/<key>.yaml`; Reviewer note) only when the expected hash matches, importing it elsewhere yields the same content hash, and a run log exports as JSON. `` with `` - Proving test (`test_sharing.py`, host tests): exporting a version writes `.coral/<id>.yaml` (that is, `.coral/workflows/<key>.yaml`) only when the expected hash matches, importing it elsewhere yields the same content hash, and a run log exports as JSON. `` (RES-181).
- EXT-03: In ext.md, delete the bullet `` - Reviewer note: the master proving test says `.coral/<id>.yaml`; D§12 and WSP-01's import use `.coral/workflows/`, followed here. `` (resolved by RES-181).

### RES-182 · assign · EXT-05, BRD-02

EXT-05 owns two new seam rows: S90, an upstream-first fire.py hook, and S84b, the TasksPage.tsx 'Run workflow' action, which joins the §6.5 order after BRD-02's S84 (soft edge EXT-05 -> BRD-02).

Changed by the challenge pass: CH-22, CH-23.

Master edits:
- EXT-05.included += "Seam rows S90 (new upstream-first fire.py hook) and S84b (the TasksPage.tsx 'Run workflow' action, after BRD-02's S84), both owned by EXT-05"
- notes += "RES-182: Hot-file order amendment (§6.5): web/src/pages/TasksPage.tsx row 'BRD-02: S84, then EXT-05: Run-workflow action'; omnigent/server/scheduled/fire.py gains EXT-05's new hook seam."
- EXT-05.soft_deps += BRD-02 (TasksPage.tsx action lands after BRD-02's S84)
- EXT-05.seams += S90
- EXT-05.seams += S84b
- notes += "RES-182: Seam ledger amendment: new rows S84b (EXT-05: TasksPage.tsx 'Run workflow' action, after BRD-02's S84), S87b (GTE-04: inbox watcher loaded from web/electron/src/main.js, after BRD-03's S87) and S90 (EXT-05: upstream-first fire.py hook). With S57b and S89b the ledger has 102 entries, 93 planned with one owner each."

Spec edits:
- EXT-05: **Ownership boundaries.** Included: add "Seam rows S90 (new upstream-first fire.py hook) and S84b (the TasksPage.tsx 'Run workflow' action, after BRD-02's S84), both owned by EXT-05" (RES-182).
- EXT-05: **Dependencies.** Add BRD-02 to the "Soft:" line (TasksPage.tsx action lands after BRD-02's S84; RES-182).
- BRD-02: **Dependencies.** Add EXT-05 to the soft part of "Downstream, unblocks:" (RES-182).
- EXT-05: **Technical scope.** Modify or extend upstream: add S90 to the seams this feature lands (RES-182).
- EXT-05: **Technical scope.** Modify or extend upstream: add S84b to the seams this feature lands (RES-182).
- EXT-05: In ext.md, replace the line `` - Modify or extend upstream: none in the master; this design needs one fire hook (S, upstream-first; Reviewer note): `` with `` - Modify or extend upstream: seam rows S90 (a new `fire.py` hook, S, upstream-first) and S84b (the TasksPage action), both owned by EXT-05: `` (RES-182).
- EXT-05: In ext.md, delete the bullet `` - Reviewer note: the master lists no seam, but this design needs the `fire.py` hook and TasksPage edits; add them to the seam ledger and §6.5. §11 lists no surface for the dialog. `` (resolved by RES-182).

Section edits:
- D: D.8 "Counts by class" table: replace "| Ledger entries | 97 |" with "| Ledger entries | 102 |" and append "; master v3 adds S57b, S84b, S87b, S89b and S90" to that row's members cell; replace "| Planned, one owner each | 88 | 80 base ids plus 8 sub-ids;" with "| Planned, one owner each | 93 | 81 base ids plus 12 sub-ids;"; replace "| Additive | 82 |" with "| Additive | 87 |". Below the table, replace "Upstreamable flag, 89 base ids: Yes 44, No 30, Maybe 11, Partly 4 (planned only: 40, 27, 9, 4)" with "Upstreamable flag, 90 base ids: Yes 45, No 30, Maybe 11, Partly 4 (planned only: 41, 27, 9, 4)", and replace "BRAND 11, OPS 9, WORKSPACE 9, PLATFORM 7, WEB 4. By milestone: M1 22, M2 30, M3 12, M4 18, post-M4 6" with "BRAND 12, OPS 10, WORKSPACE 9, PLATFORM 9, WEB 5. By milestone: M1 22, M2 31, M3 12, M4 19, post-M4 9". (RES-182)
- A: A.1 "Seams are one-line registry calls": replace "Of 97 ledger entries, 88 are planned with one owner each." with "Of 102 ledger entries (master v3 adds S57b, S84b, S87b, S89b and S90), 93 are planned with one owner each." (RES-182)

### RES-183 · edge · EXT-01, DUR-02, API-02, WSP-06

EXT-01 gets a hard edge to DUR-02 (accepting a suggestion writes a version through DUR-02's store; DUR-02 PH1/M1 ends week 9.5, long before week 26.5), a soft edge to API-02 (spend for cost_growth) and K7. cost_growth reads spend only for runs DUR-06 has not purged. test_edit_in_non_test_step reads changed paths from the diff_stat WSP-06 stores on each handoff (git diff --numstat -z, one row per path).

Changed by the challenge pass: CH-19.

Master edits:
- EXT-01.hard_deps += DUR-02 (accept writes a version through the workflow store)
- EXT-01.soft_deps += API-02 (spend for cost_growth)
- EXT-01.contracts_consumed += K7; K7.consumers += EXT-01
- EXT-01.included: "test edits in non-test steps" -> "test edits in non-test steps (changed paths from the diff_stat WSP-06 stores on each handoff: git diff --numstat -z, one row per path)"

Spec edits:
- EXT-01: **Dependencies.** Add DUR-02 to the "Hard:" line and remove it from "Soft:" if listed (accept writes a version through the workflow store; RES-183).
- DUR-02: **Dependencies.** List EXT-01 in the hard part of "Downstream, unblocks:" (RES-183).
- EXT-01: **Dependencies.** Add API-02 to the "Soft:" line (spend for cost_growth; RES-183).
- API-02: **Dependencies.** Add EXT-01 to the soft part of "Downstream, unblocks:" (RES-183).
- EXT-01: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-183).
- EXT-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "test edits in non-test steps" so it says "test edits in non-test steps (changed paths from the diff_stat WSP-06 stores on each handoff: git diff --numstat -z, one row per path)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-183).
- EXT-01: In ext.md, delete the bullet `` - Reviewer note: accept uses DUR-02 and adds K7 endpoints; DUR-02 is not a dependency and K7 is not consumed. `` (resolved by RES-183).
- EXT-01: In ext.md, replace the bullet `` - Reviewer note: cost_growth needs API-02's spend (not in K3; DUR-06 purges it); test_edit_in_non_test_step needs changed paths in handoff refs (WSP-06, UNVERIFIED). §11 lists no Suggestions surface. `` with `` - cost_growth reads API-02's spend only for runs DUR-06 has not purged. test_edit_in_non_test_step reads changed paths from the `diff_stat` WSP-06 stores on each handoff (`git diff --numstat -z <start_commit>..<head>`, one row per path; master v3). `` (no longer a reviewer note; settled by RES-183).

### RES-184 · edge · EXT-02, TLS-02, ENG-03

EXT-02 consumes K6 and gets soft edges to TLS-02 (rejection path) and ENG-03 (reserved-key checks).

Master edits:
- EXT-02.contracts_consumed += K6; K6.consumers += EXT-02
- EXT-02.soft_deps += TLS-02 (typed-handoff rejection path)
- EXT-02.soft_deps += ENG-03 (reserved-key validation)

Spec edits:
- EXT-02: **Dependencies.** Add K6 to the "Contracts: consumes ..." line (RES-184).
- EXT-02: **Dependencies.** Add TLS-02 to the "Soft:" line (typed-handoff rejection path; RES-184).
- TLS-02: **Dependencies.** Add EXT-02 to the soft part of "Downstream, unblocks:" (RES-184).
- EXT-02: **Dependencies.** Add ENG-03 to the "Soft:" line (reserved-key validation; RES-184).
- ENG-03: **Dependencies.** Add EXT-02 to the soft part of "Downstream, unblocks:" (RES-184).
- EXT-02: In ext.md, delete the bullet `` - Reviewer note: typed handoffs need K6, TLS-02's rejection path and ENG-03 changes; none is a dependency or consumed contract. `` (resolved by RES-184).

### RES-185 · contract · EXT-03

EXT-03's export and import endpoints extend K7, so EXT-03 consumes K7.

Master edits:
- EXT-03.contracts_consumed += K7; K7.consumers += EXT-03

Spec edits:
- EXT-03: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-185).
- EXT-03: In ext.md, delete the bullet `` - Reviewer note: the endpoints extend K7, which is not consumed; web git import and imported-template display have no owner. `` (resolved by RES-185).

### RES-186 · edge · EXT-04, GTE-06, API-02

EXT-04 consumes K19 and K7 and gets soft edges to GTE-06 (per-recipient alerts) and API-02 (authority changes).

Master edits:
- EXT-04.contracts_consumed += K19; K19.consumers += EXT-04
- EXT-04.contracts_consumed += K7; K7.consumers += EXT-04
- EXT-04.soft_deps += GTE-06 (per-recipient approver alerts)
- EXT-04.soft_deps += API-02 (authority changes on gate answers)

Spec edits:
- EXT-04: **Dependencies.** Add K19 to the "Contracts: consumes ..." line (RES-186).
- EXT-04: **Dependencies.** Add K7 to the "Contracts: consumes ..." line (RES-186).
- EXT-04: **Dependencies.** Add GTE-06 to the "Soft:" line (per-recipient approver alerts; RES-186).
- GTE-06: **Dependencies.** Add EXT-04 to the soft part of "Downstream, unblocks:" (RES-186).
- EXT-04: **Dependencies.** Add API-02 to the "Soft:" line (authority changes on gate answers; RES-186).
- API-02: **Dependencies.** Add EXT-04 to the soft part of "Downstream, unblocks:" (RES-186).
- EXT-04: In ext.md, delete the bullet `` - Reviewer note: approver alerts need GTE-06's per-recipient producer (K19), and authority changes API-02 (K7); neither is a dependency. `` (resolved by RES-186).

### RES-187 · fixed · EXT-04

EXT-04's S53 analysis (which paths already refuse coral__ rows) is a verified fact; it becomes plain technical-scope text.

Spec edits:
- EXT-04: In ext.md, replace the bullet `` - Reviewer note: `coral__` rows lack `session_id` (`omnigent/server/bundles.py:324-377`), so PUT agent (`routes_agent.py:337-341`) and MCP bundle edits (`session_mcp_servers.py:348-352`) already refuse them; S53's gaps are PATCH (`builtin_agents.py:332-340` admits the owner), reinstall, delete and registry selections (`_bound_agent`, `:290`). `` with `` - `coral__` rows lack `session_id` (`omnigent/server/bundles.py:324-377`), so PUT agent (`routes_agent.py:337-341`) and MCP bundle edits (`session_mcp_servers.py:348-352`) already refuse them; S53's gaps are PATCH (`builtin_agents.py:332-340` admits the owner), reinstall, delete and registry selections (`_bound_agent`, `:290`). `` (no longer a reviewer note; settled by RES-187).

### RES-188 · assign · EXT-01, EXT-03, EXT-04, EXT-05

Master §11 gains UI-surface rows for EXT-01 (Suggestions tab), EXT-03 (Export dialog), EXT-04 (Share dialog) and EXT-05 (Run-workflow action), each owned by its feature with WEB-lead review. EXT-03, EXT-04 and EXT-05 gain a 0.5-week WS-WEB secondary load (EXT-01 already has 1 week); post-M4 WEB tracks are free after WEB-09 (24.5) apart from GTE-04.

Changed by the challenge pass: CH-26.

Master edits:
- ui_surfaces += {"surface": "Suggestions tab", "owner": "EXT-01 (post-M4; WEB-lead review)", "states": "empty, loading, error, suggestion with YAML diff, accepted"}
- ui_surfaces += {"surface": "Export dialog", "owner": "EXT-03 (post-M4; WEB-lead review)", "states": "hash conflict, path_escape, too_large, host offline, written"}
- ui_surfaces += {"surface": "Share dialog and approver list", "owner": "EXT-04 (post-M4; WEB-lead review)", "states": "viewer 403, revoked approver 404, grant added, grant removed"}
- ui_surfaces += {"surface": "Automations 'Run workflow' action", "owner": "EXT-05 (post-M4; WEB-lead review)", "states": "no workflows, invalid version, fire started, duplicate fire"}
- EXT-03.secondary_workstreams += WS-WEB 0.5 weeks
- EXT-04.secondary_workstreams += WS-WEB 0.5 weeks
- EXT-05.secondary_workstreams += WS-WEB 0.5 weeks

### RES-189 · split · ENG-04, SES-04, DUR-03, ENG-06, DUR-05, GTE-01, SES-06, TLS-03, PRF-01, RUL-01, RUL-03, RUL-06, HRN-03, HRN-05, RUL-05, WEB-09, API-01, OPS-04, DUR-04, HRN-09

Master wording for splits the specs already agree on: ENG-04 owns the post_close_activity transition and SES-04 detects it; ENG-06 owns the start_key rule and DUR-03 enforces it as a key; DUR-05 triggers gate re-publish and GTE-01 executes it; DUR-05 marks slots suspect and SES-06 runs the ladder; TLS-03 owns the orchestrator allowlist constant, PRF-01 places orchestrator_guard in guardrails and RUL-01 owns the policy code; RUL-03 calls RUL-06's V9; HRN-03 and HRN-05 set fail_closed in native step bundles; RUL-05 owns step-budget data and WEB-09 the fields; API-01 owns the client.ts wrapper; OPS-04 reuses DUR-04's lease fixtures; HRN-03 and HRN-09 own their rows in PRF-01's bundle generator.

Master edits:
- SES-04.included: "A turn that starts after accept marks post_close_activity, re-fingerprints and pauses the run as paused(drift)" -> "Detects a turn that starts after accept, re-fingerprints and feeds the post_close_activity observation; ENG-04's transition pauses the run as paused(drift)"
- DUR-03.included: "Idempotent start_run via start_key" -> "Idempotent start_run enforcing ENG-06's start_key rule as the key"
- DUR-05.included: "Trigger gate re-publish; stale runner_last_seen marks slots suspect;" -> "Trigger gate re-publish (GTE-01 executes it); stale runner_last_seen marks slots suspect (SES-06 runs the ladder);"
- GTE-01.included: "re-publish on startup and after runner loss" -> "re-publish executor on startup and after runner loss (DUR-05 triggers)"
- TLS-03.included: "orchestrator_guard in bundle guardrails plus a label check in the handler" -> "the orchestrator tool allowlist constant and a label check in the handler (PRF-01 places orchestrator_guard in the guardrails; RUL-01 owns the policy code)"
- RUL-03.included: "an unenforceable Required rule fails validation with remedies" -> "an unenforceable Required rule fails RUL-06's V9 with remedies (a claude-sdk-only interim check until RUL-06 lands)"
- HRN-03.included: "Separate sessions, steps only;" -> "Separate sessions, steps only, with fail_closed set in native step bundles and the claude-native branch of PRF-01's bundle generator;"
- HRN-05.included: "S15 refuse run-owned codex-native when policy hooks are disabled (upstream-first)" -> "S15 refuse run-owned codex-native when policy hooks are disabled (upstream-first); fail_closed set in codex-native step bundles"
- RUL-05.included: "step budget fields for WEB-09" -> "step-budget data and API behind WEB-09's inspector fields"
- API-01.included: "Generated TS types; MSW fixtures and stub routers" -> "Generated TS types, the web/src/workflows/api/client.ts wrapper, MSW fixtures and stub routers"
- OPS-04.included: "worker-lease behaviour with two replicas" -> "worker-lease behaviour with two processes and a SIGKILL, reusing DUR-04's lease fixtures"
- HRN-09.included += "Codex stance row in PRF-01's bundle generator (reviewed by PRF-01's owner)"

Spec edits:
- SES-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "A turn that starts after accept marks post_close_activity, re-fingerprints and pauses the run as paused(drift)" so it says "Detects a turn that starts after accept, re-fingerprints and feeds the post_close_activity observation; ENG-04's transition pauses the run as paused(drift)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- DUR-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Idempotent start_run via start_key" so it says "Idempotent start_run enforcing ENG-06's start_key rule as the key". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- DUR-05: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Trigger gate re-publish; stale runner_last_seen marks slots suspect;" so it says "Trigger gate re-publish (GTE-01 executes it); stale runner_last_seen marks slots suspect (SES-06 runs the ladder);". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- GTE-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "re-publish on startup and after runner loss" so it says "re-publish executor on startup and after runner loss (DUR-05 triggers)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- TLS-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "orchestrator_guard in bundle guardrails plus a label check in the handler" so it says "the orchestrator tool allowlist constant and a label check in the handler (PRF-01 places orchestrator_guard in the guardrails; RUL-01 owns the policy code)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- RUL-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "an unenforceable Required rule fails validation with remedies" so it says "an unenforceable Required rule fails RUL-06's V9 with remedies (a claude-sdk-only interim check until RUL-06 lands)". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- HRN-03: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Separate sessions, steps only;" so it says "Separate sessions, steps only, with fail_closed set in native step bundles and the claude-native branch of PRF-01's bundle generator;". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- HRN-05: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "S15 refuse run-owned codex-native when policy hooks are disabled (upstream-first)" so it says "S15 refuse run-owned codex-native when policy hooks are disabled (upstream-first); fail_closed set in codex-native step bundles". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- RUL-05: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "step budget fields for WEB-09" so it says "step-budget data and API behind WEB-09's inspector fields". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- API-01: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Generated TS types; MSW fixtures and stub routers" so it says "Generated TS types, the web/src/workflows/api/client.ts wrapper, MSW fixtures and stub routers". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- OPS-04: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "worker-lease behaviour with two replicas" so it says "worker-lease behaviour with two processes and a SIGKILL, reusing DUR-04's lease fixtures". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-189).
- HRN-09: **Ownership boundaries.** Included: add "Codex stance row in PRF-01's bundle generator (reviewed by PRF-01's owner)" (RES-189).

### RES-190 · citation · roadmap-wide

Record that the spec reviewer notes and open verifier items are resolved in master v3 (decisions_log.json), and create section J.6 for residual items.

Master edits:
- notes += "RES-190: master_v3 folds in the WF3 resolution pass: every [OPEN?] verifier item and every spec Reviewer note maps to a RES decision in decisions_log.json; residual items are listed in roadmap section J.6."

Section edits:
- J: Create "### J.6 Residual open items" after J.5 with columns RES | Item | Owner | Deadline | Blocking impact, one row per decision in decisions_log.json whose residual is not null (the per-decision J instructions give each row). (RES-190)
- V: V.10 "Structural checks only": replace "The 197 spec reviewer notes are not yet folded into `master_v2_fix1.json`. For example, the soft edges HRN-02 to ENG-03 and SES-02 to SES-01 are absent." with "The 219 spec reviewer notes and 90 open verifier items are resolved in `master_v3.json` (decisions_log.json); residual items are in J.6." Also change "197" to "219" in V.1 and V.3. (RES-190)
- A: A.5: replace "197 spec reviewer notes are not yet folded into the master list." with "Spec reviewer notes are resolved in master v3; residual items are in J.6." (RES-190)

### RES-191 · assign · SPK-01

The tech lead (IM-0 owner) owns the M1 exit gate and checks master §3's M1 exit criteria against IM-0 and IM-1 evidence and the M1 features' proving tests; M1 has no separate acceptance lane.

Changed by the challenge pass: CH-12.

Master edits:
- notes += "RES-191: M1 exit gate: the tech lead (IM-0 owner) owns it and checks master §3's M1 exit criteria against IM-0 and IM-1 evidence and the M1 features' proving tests; M1 has no separate acceptance lane."

Section edits:
- I: I.2 milestone table, M1 row, Exit gate owner: replace "Tech lead as IM-0 owner (proposed; master names no M1 acceptance lane)" with "Tech lead as IM-0 owner (master v3; checks IM-0 and IM-1 evidence and the M1 proving tests; no separate lane)". (RES-191)

### RES-192 · residual · HRN-03, WEB-08

The early-start levers (HRN-03 at week 11, WEB-08 at M2) change decision 23's windows and need tech-lead sign-off; not adopted in v3.

Section edits:
- J: J.6: add the row "| RES-192 | The early-start levers (HRN-03 at week 11, WEB-08 at M2) change decision 23's windows and need tech-lead sign-off; not adopted in v3. | Tech lead | Before week 11 | Without sign-off M3 stays at levelled week 21 and the WEB chain binds M4. |".

### RES-193 · residual · GTE-03, DUR-06

At M2 one platform engineer cannot run GTE-03 and DUR-06 in the same weeks (13.5-15.5); DUR-06 can move to 15.5-17.5 on its float. No schedule change here.

Section edits:
- J: J.6: add the row "| RES-193 | At M2 one platform engineer cannot run GTE-03 and DUR-06 in the same weeks (13.5-15.5); DUR-06 can move to 15.5-17.5 on its float. No schedule change here. | PLATFORM lead | Week 13.5 | One of GTE-03 or DUR-06 slips two weeks if only one engineer stays. |".

### RES-194 · residual · RUL-03, WSP-02, RUL-06, EVD-04

K15 (RUL-03) and K20 (WSP-02) ship the week their first consumers start; the plan drafts them early in free time (INT-T4 weeks 11-13.5; WSP-T1 weeks 9-13.5).

Section edits:
- J: J.6: add the row "| RES-194 | K15 (RUL-03) and K20 (WSP-02) ship the week their first consumers start; the plan drafts them early in free time (INT-T4 weeks 11-13.5; WSP-T1 weeks 9-13.5). | INTEGRATION and WORKSPACE leads | Week 13.5 | RUL-06 and EVD-04 start against drafts if the early drafting does not happen. |".

### RES-195 · residual · SPK-03, FND-04

The spike-4 fallback (test-only openai-agents Tier B) is not costed; one extra FND-04 week moves levelled M2 by two weeks.

Section edits:
- J: J.6: add the row "| RES-195 | The spike-4 fallback (test-only openai-agents Tier B) is not costed; one extra FND-04 week moves levelled M2 by two weeks. | SPK-03 (tech lead) | Week 1 (SPK-03 memo) | An uncosted fallback can move M2 by two weeks. |".

### RES-196 · residual · WEB-11, WEB-06, WEB-08

WEB-11 (cut rank 2) is a hard input of WEB-06 and WEB-08; if cut at M2 it must still land by week 15.5 or M4 slips one-for-one.

Section edits:
- J: J.6: add the row "| RES-196 | WEB-11 (cut rank 2) is a hard input of WEB-06 and WEB-08; if cut at M2 it must still land by week 15.5 or M4 slips one-for-one. | WEB lead | Week 15.5 | M4 slips one-for-one if a cut WEB-11 lands later. |".

### RES-197 · residual · SES-03, SES-09, SES-05, TLS-05

SES-03 > SES-09 > SES-05 has zero float, so the ADR-05 topology fallback (+3-4 weeks) moves M2 one-for-one; cutting TLS-05 frees INT-T4 for SES-05.

Section edits:
- J: J.6: add the row "| RES-197 | SES-03 > SES-09 > SES-05 has zero float, so the ADR-05 topology fallback (+3-4 weeks) moves M2 one-for-one; cutting TLS-05 frees INT-T4 for SES-05. | INTEGRATION lead | Day 4 of week 1 (ADR-05) | A topology fallback moves M2 by 3-4 weeks unless cut rank 1 is applied. |".

### RES-198 · residual · SES-07, BRD-03, OPS-07, HRN-08

OQ-11 (take-over details), OQ-31 (desktop app id and DCO; OPS-05's spec defaults the update feed to GitHub release assets, and store listings and mobile bundle ids are a non-goal through M4, RES-161) and OQ-51 (bench budget) have no default in the sources; J gives a proposal for OQ-11 only.

Changed by the challenge pass: CH-25.

Section edits:
- J: J.6: add the row "| RES-198 | OQ-11 (take-over details), OQ-31 (desktop app id and DCO; OPS-05's spec defaults the update feed to GitHub release assets, and store listings and mobile bundle ids are a non-goal through M4, {RES:store_listings}) and OQ-51 (bench budget) have no default in the sources; J gives a proposal for OQ-11 only. | PM (OQ-11), Legal and Ops (OQ-31), Ops (OQ-51) | OQ-51 week 9.5; OQ-11 and OQ-31 week 13.5 | SES-07 take-over semantics, BRD-03's desktop app id and the credentialed soak. |".

### RES-199 · citation · BRD-02

CoralPageHeader lives at web/src/brand/CoralPageHeader.tsx (BRD-02), not UI§10's web/src/components/concerto/; a Draft 5 correction.

Section edits:
- B: B.4: add "UI§10 CoralPageHeader path → web/src/brand/CoralPageHeader.tsx (BRD-02)". (RES-199)

### RES-200 · split · SPK-01, OPS-06

OQ-43: SPK-01 records the week-1 default (accept single-user calls, provenance 'user'), which K6 and TLS-01's S49 PR (week 3) build on; OPS-06 records the security verdict in week 6 and may tighten it. Default, then verdict.

Changed by the challenge pass: CH-04.

Master edits:
- OPS-06.included: "Review against the PH0 threat model: S49 tool provenance" -> "Review against the PH0 threat model: the week-6 S49 tool-provenance verdict (OQ-43), confirming or tightening the week-1 default that SPK-01 records and K6 and TLS-01 build on"

Spec edits:
- OPS-06: **Ownership boundaries.** Included (and the matching Technical scope bullet): reword the item covering "Review against the PH0 threat model: S49 tool provenance" so it says "Review against the PH0 threat model: the week-6 S49 tool-provenance verdict (OQ-43), confirming or tightening the week-1 default that SPK-01 records and K6 and TLS-01 build on". The quote is master wording; find the item the spec phrases its own way, and leave it if it already says this (RES-200).

### RES-201 · contract · SES-01, GTE-01

K14's "hidden decline and cancel" conflicts with the unchanged ApprovalCard, whose Reject button sends decline. K14 now says decline maps only to an authored reject label and cancel is refused. Section J's OQ-3 default changes to match.

Master edits:
- K14.description: "hidden decline and cancel" -> "decline accepted only where it maps to an authored reject label (ApprovalCard's Reject sends decline) and cancel refused"

Section edits:
- J: J.3.1 OQ-3 row: replace "Decline and Cancel are hidden" with "Reject (decline) maps only to an authored reject label; cancel is refused". (RES-201)

### RES-202 · fixed · roadmap-wide

Boundary splits the verifiers fixed locally that already agree with the master (no action): SPK-02/SES-03 anchor DENY wording, SPK-04 spike 9 owner, S71 repro handoff, FND-01 allowlist mechanism vs FND-03 entries, ENG-06/SES-06 retry ladder, ENG-04/TLS-02 evaluating lease, DUR-03/DUR-05 commit-boundary tests, SES-06 recovery kinds, SES-08 alert producer, TLS-01/FND-02 token, TLS-03/ENG-04 decision requests, GTE-03 links, GTE-02/WEB-05 step chip, EVD-02 submit wait, API-02 amendments, WEB-03 excluded owners, WEB-05 chip, OPS-08 E2E-4 path, OPS-09 desktop row, EXT-01/EXT-02/EXT-04 wording fixes.

## Challenge log

| CH | Kind | Decisions | Finding | Change |
|---|---|---|---|---|
| CH-01 | owner | RES-150 | case_results went to ENG-10 (M4, weeks 13.5-15.5), the same window as its only consumer WEB-12 (M3), with no edge: an M3 badge would wait on an M4 feature. The WEB-12 reviewer note itself says DUR-02 already stores CaseResult. WEB-08 and WEB-10 were also given backend PRs in DUR-02's and API-02's code with no edge. | case_results moves to DUR-02 (M1, ends week 9.5; WEB-12 already soft-depends on DUR-02). K7 text updated. ENG-10 keeps K7 for its own version, diff and restart routes. Added soft edges WEB-08 -> DUR-02 and WEB-10 -> API-02. |
| CH-02 | owner | RES-062 | The batched card (a web component inside GTE-02's WorkflowInboxCard) went to SES-10, a WS-INTEGRATION backend feature whose weeks 14-16 window is already short of IM-7 (its own residual), and SES-10 had no edge to GTE-02. | Moved to WEB-10 (WS-WEB, M4, weeks 17.5-22): it starts after SES-10 ships the K14 batch payload, ends before IM-7 (22.5), already soft-depends on SES-10 and draws the same per-item list in the run view. WEB-10 consumes K14 and soft-depends on GTE-02; SES-10 excludes the card UI; the ui_surfaces state and GTE-02's exclusion name WEB-10. |
| CH-03 | owner | RES-001 | SPK-05's objective is to record Coral-controlled M2-M3 questions by week 4 and chase external answers. OQ-25 is a PM question Coral controls, yet the decision gave it only a week-13.5 deadline; the generated spec edits also quoted master wording that spk.md does not contain, next to a hand edit covering the same line. | OQ-25 gets a week-4 default (J.3.1's proposal) and a week-13.5 signature; OQ-29 stays an external answer due week 13.5. The SPK-05 spec edit now quotes spk.md's actual Excluded text, and the duplicate generated Excluded edits are dropped. |
| CH-04 | master-vs-spec | RES-200 | The master edit said 'SPK-01 only raises it', but spk.md's week-1 records table already records the OQ-43 default that K6 and TLS-01 consume, and TLS-01's S49 PR (week 3) lands before OPS-06's week-6 verdict. 'Only raises it' would leave S49 without a record. | OPS-06's text now says it confirms or tightens SPK-01's week-1 default; the summary states the order default (week 1), S49 (week 3), verdict (week 6). |
| CH-05 | edge | RES-072 | The added soft edge TLS-03 -> SES-06 pointed the wrong way: TLS-03 (weeks 5.5-7.5) produces the re-brief renderer and SES-06 (weeks 7.5-9.5) calls it at the ladder's brief step. The edge made TLS-03 wait on a feature that starts when it ends, and SES-06 still had no link to the renderer it uses. | Replaced by soft edge SES-06 -> TLS-03 (the consumer depends on the producer; TLS-03 finishes as SES-06 starts; no cycle). TLS-03's restart test keeps simulating the generation change itself. |
| CH-06 | edge | RES-069 | SES-10's E2E-5 was given a coral_message_agent exchange, TLS-04's tool, but SES-10 had no edge to TLS-04: a hidden dependency inside SES-10's window. | Added soft edge SES-10 -> TLS-04. |
| CH-07 | edge | RES-143, RES-130, RES-132 | Three assignments made a feature edit or import another feature's component with no edge: WEB-06 imports WEB-13's PromiseLabelChip; WSP-07 and WSP-04 add rows to WEB-03's start dialog. | Added soft edges WEB-06 -> WEB-13, WSP-07 -> WEB-03 and WSP-04 -> WEB-03. Each producer finishes long before its consumer starts, so no schedule moves. |
| CH-08 | split-gap | RES-026 | The V10 split left nobody to wire the parts together: HRN-02 finishes in week 5 with sandbox and validity ports that fail closed 'until WSP-01 and ENG-03 land', and neither ENG-03 nor WSP-01 was told to bind them. Preflight would refuse every run. | ENG-03 binds V10 and the validity check, and WSP-01 binds the sandbox report, into HRN-02's ports in their own PRs. Spec edits for ENG-03 step 4 and HRN-02 step 5. |
| CH-09 | split-gap | RES-037 | K1 said 'HRN-02's preflight refuses such runs until SES-10 lands', but HRN-02 ends in week 5 and ENG-08 adds the flag from week 9.5. No feature wrote the refusal, and none removed it when SES-10 lands. | ENG-08 adds the flag and the refusal check (in HRN-02's module, HARNESS-lead review); SES-10 lifts it at exit. K1 text and HRN-02's Excluded updated. |
| CH-10 | residual-decidable | RES-152, RES-027 | The WEB-08 residual waited for 'ENG-09's group keys' by week 19, but the groups decision already reserves the group keys in K1 at PH0 and ENG-01's spec lists group as a K1 kind; WEB-08 edits only `members`. | Decided: step 5 uses K1's group kind and members key and does not move to WEB-09. K1's group-key text now names members, entry and exit (members define the body). The J.6 row is removed. |
| CH-11 | vague-spec | RES-002 | The OPS-07 spec edit said 'remove any wording that implies a separate smoke file', yet ops-b.md lists tests/e2e/coral/test_perf_smoke.py for five concurrent template runs through a real server, a process boundary DUR-04's store harness cannot cover. Verifier line 9 was about SPK-05's Excluded line, which got no spec edit at all. | DUR-04 exposes the harness helpers; OPS-07 keeps its e2e case and reuses those helpers (no second harness). Spec edits now quote the exact ses-b.md, ops-b.md and spk.md text, including SPK-05's Excluded line. |
| CH-12 | residual-decidable | RES-035, RES-191, RES-008, RES-169 | Four residuals had nothing left to decide. Passes vs traversals: every user-facing source and both proofs count passes, and only DD§5.3.3(a) differs. M1 gate owner: I.2 already names the tech lead (IM-0 owner) and only 'confirm' remained. SPK-02's week-2 tail: impact 'none'. OPS-05's week-25 drill: the re-run is already in OPS-05's scope. | Each is now a decision (citation, assign, citation, assign) with no J.6 row. Passes adds a K1 sentence, SPK-01 wording, J.3.1 and B.3 rows; M1 adds a master note and an I.2 edit; SPK-02's H.3 edit now quotes the real INT-T1 row; the review notes become plain text. |
| CH-13 | schedule | RES-048, RES-014 | The retention migration was inserted after saved_blocks (ENG-09, weeks 18-22.5), but D.6 assigns numbers 'in this order' and DUR-06 runs weeks 13.5-15.5, so DUR-06 would have waited on ENG-09. H.10's dated train table also omitted both new migrations (retention and coral_0000_base). | Retention now sits after notify (GTE-03, weeks 13.5-15.5) in master and D.6; H.10 gains retention in its 13.5-18 row and coral_0000_base as a weeks 1-3 row. |
| CH-14 | seam | RES-154, RES-017 | K16 gives every seam row one owner feature. deploy_entry had OPS-03 land an 'S57 amendment' while S57 stays FND-03's, so two features would edit under one row. s89_split created S89b for BRD-03 but did not add it to BRD-03's seams. | OPS-03 owns a new row S57b (added to its seams, with a ledger note); BRD-03 gains S89b in its seams. FND-03 keeps S57. |
| CH-15 | vague-spec | RES-015, RES-024, RES-031, RES-074, RES-055, RES-038, RES-028, RES-083, RES-068, RES-175, RES-161 | Several spec and section edits could not be applied as written: 'wherever'/'any wording' instructions with no target (DUR-01, DUR-05, I.5, H.11 'or wherever'); quotes absent from the target (D.8 'and the archive-idle origin', H 'alerts should be GTE-06's first PR'); edits with no location (WSP-04 'Add merges dark'); a '(RES)' placeholder in B.3; and generated Excluded edits that quote master wording the specs never used, some already true in the spec (TLS-04, TLS-05, OPS-08, EVD-04). | Each now names its heading and quotes text that exists in the file (checked by wf4/challenge/check_quotes.py), or is dropped when the spec already says it. I.5 needs no edit (it does not paraphrase M2 exit 4). Generated Excluded edits now read 'reword the item covering ...', as Included edits already did. |
| CH-16 | contract | RES-021 | The decision shrank WSP-01's token to coral_host_sandbox:1:<backend>, while wsp.md defines coral_host_sandbox:1:<platform>:<backend>:<0\|1>; its spec edit would have dropped the platform and enabled fields without saying why. It also had TLS-01 (weeks 1-3) advertise a token that WSP-01 only computes from week 5, and WSP-01 did not consume K17. | K17, TLS-01 and WSP-01 use the spec's token shape. TLS-01's S50 line advertises every token registered through the K17 process map, so WSP-01 registers its token in week 5 without touching frames.py. WSP-01 consumes K17. Spec edits quote wsp.md's Sandbox report bullet and tls.md step 4. |
| CH-17 | vague-spec | RES-151 | The spec edit told API-02 to 'use stale_visit in the error-code list', but API-02's section has no such list: the K7 code list with gate_not_current is in API-01's spec (evd-api.md, Errors bullet). D.4 'Human gate' step 5 still says 'K7 must pick one'. K7 now names GTE-01 as returning the code, but GTE-01 did not consume K7. | API-02's edit now quotes only its gate-answers sentence; a new API-01 edit swaps the code in the Codes list; a D.4 edit records the choice; GTE-01 consumes K7. |
| CH-18 | split-gap | RES-075 | GTE-06 took all 'run-end' notify effects, but ENG-06's cancel transition already emits a K19 notify on cancel (eng-a.md: 'emits cancel_sessions, withdraw_gate per visit and a K19 notify'). run_cancelled had two owners, and ENG-06 was not told what it keeps. | GTE-06 adds gate-open, run_completed and run_failed emitters; ENG-06 keeps run_cancelled (its Included says so, and its Excluded names GTE-06's emitters); ENG-04's exclusion is narrowed to the same three. GTE-06's spec step 5 and Included are edited by exact quote. |
| CH-19 | residual-decidable | RES-183 | The EXT-01 residual said changed paths in WSP-06's handoff refs were UNVERIFIED and the detector might be dropped. wsp.md (WSP-06 step 6) already stores `diff --numstat -z <start_commit>..<head>` as diff_stat on each handoff, and numstat lists every changed path. | Decided: the detector reads changed paths from that diff_stat. EXT-01's Included says so, the reviewer note becomes plain text, and the J.6 row is removed. |
| CH-20 | residual-decidable | RES-064 | The residual left 'a staffed tail to IM-7 or a split' open until week 14, but H.1 shows INT-T2 (SES-10's track) has no work after week 16, so a tail needs no new staffing. Its I.8 edit also pointed at an 'M4 watch list' that I.8 does not have (the watch list is in I.10; I.8 has 'Risks to the date'). | Decided: INT-T2 carries the IM-7 tail; SES-10's Included and DoD say so; the H.1 INT-T2 row shows the tail; the I.8 edit now adds a bullet to 'Risks to the date'. The J.6 row stays, now tracking only the IM-7 date. |
| CH-21 | residual-decidable | RES-153, RES-165 | Two more residuals had nothing left to decide. Analytics: the web app's product analytics is a client host sink (web/src/lib/analytics.ts) and the server has no analytics pipeline, so 'server-side emission' would be a new system; events already carry ids, so double counting is avoided by counting distinct run ids. OPS-02's week-6 tail: no dependent starts before week 13.5, and its only risk is RK-02 (the same case CH-12 settled for SPK-02). | Analytics becomes a non-goal decision (client-side, distinct run ids) with WEB-13 and J.3.1 OQ-26 edits; OPS-02 becomes a citation with an H.1 OPS-T1 edit. Both reviewer notes become plain text and both J.6 rows are removed. |
| CH-22 | edge | RES-037, RES-124, RES-182 | Three decisions made a feature edit or review another feature's code with no path between them in the graph: ENG-08 adds the refusal check to HRN-02's preflight module (CH-09); OPS-04's closure reviews HRN-06's S20 relay; EXT-05's TasksPage action must land after BRD-02's S84. | Added soft edges ENG-08 -> HRN-02, OPS-04 -> HRN-06 and EXT-05 -> BRD-02. None forms a cycle; HRN-06 ends inside OPS-04's window, the others finish long before. |
| CH-23 | seam | RES-082, RES-182 | CH-14 gave every new seam row an id and an owner's seams entry (S57b, S89b), but two decisions still created rows with no id: GTE-04's main.js watcher ('a new GTE-04 seam row') and EXT-05's fire.py hook and TasksPage action ('new seam rows'). GTE-04 and EXT-05 list no seams. D.8 and A.1 still count 97 entries and 88 planned. | GTE-04 owns S87b (after BRD-03's S87 in main.js); EXT-05 owns S90 (fire.py, upstream-first) and S84b (TasksPage.tsx, after BRD-02's S84). Both seams lists, a ledger note, the EXT-05 reviewer-note rewording, and D.8 and A.1 counts (102 entries, 93 planned, including S57b and S89b) are updated. |
| CH-24 | contract | RES-044, RES-105 | Contract text added by the decisions names features that neither produce nor consume the contract: K3 names ENG-09 and SES-07 as adding log kinds, but only HRN-07 was made a K3 consumer; K5 names RUL-05's budgets migration, but RUL-05 does not consume K5. The same holds for every other migration-train owner that lacks K5 (EVD-04, WSP-03, SES-07, ENG-09, EXT-01, EXT-04, GTE-04). | ENG-09 and SES-07 consume K3; all eight migration owners consume K5. K3 and K5 consumer lists follow. |
| CH-25 | master-vs-decision | RES-067, RES-108, RES-026, RES-037, RES-198 | Some master fields still contradicted their decisions: SES-06's conditional_deps said it takes only 'the S27 reaper retest' while the decision moves the whole seam; PRF-01's hygiene listed spawn: false but not tools.agents: [], which RUL-01 now says PRF-01 writes; the v10 and structure_flag feature lists omitted WSP-01 and SES-10, which CH-08 and CH-09 gave work; oq_defaults still waited on OQ-31 for store listings, which RES-161 made a non-goal, and said OQ-31 had no default although ops-a.md defaults the update feed. | SES-06's conditional_deps and PRF-01's hygiene item are reworded; the feature lists gain WSP-01 and SES-10; the OQ-31 residual now covers only the desktop app id and DCO. |
| CH-26 | owner | RES-188 | Reviewer note 63 said 'The Share UI has no WEB load'. RES-119 deleted the note after settling only the /clear policy, and RES-188, to which the note is also mapped, gave EXT-03, EXT-04 and EXT-05 UI surfaces but no WS-WEB load, unlike EXT-01 and the master's other secondary WEB loads. | EXT-03, EXT-04 and EXT-05 gain a 0.5-week WS-WEB secondary load (post-M4, when WEB has free tracks). |
| CH-27 | vague-spec | RES-011, RES-013, RES-159 | 89 generated 'reword the item covering "X"' spec edits quote master wording that does not occur in the target spec, because the specs paraphrase the master and the verifiers had already fixed many of them. As written, an editor searches for text that is not there. Four are pure no-ops: wsp.md and spk.md already cite connect.py:1417-1424 and 6027-6035, fnd.md already names lint_coral_import_boundary.py, and brd.md already calls coralRoutes(prefix, withPageView). | Every generated Included and Excluded edit now says the quote is master wording, to find the item the spec phrases its own way, and to leave it if it already says this. The four no-op edits are dropped. |
| CH-28 | vague-spec | RES-001, RES-079, RES-028 | Three edits fixed one place and left a contradiction next to it: CH-03 moved the OQ-25 default to week 4, but J.3.1's OQ-25 deadline still reads 'Before PH4 (DUR-06, week 13.5)'; the A.1 note said S37 is 'about eight lines' while the decision says seven anchored points plus one line; GTE-06 gained the overdue and reaction alert kinds, but its alerts table CHECK in gte.md still lists only the old kinds. | The J.3.1 edit also replaces the OQ-25 deadline; the A.1 note uses the decision's wording; a GTE-06 data-model edit adds overdue and reaction to the CHECK. |

## Coverage index

`[OPEN?]` and other open items in `verification/verifier_issues.md` (by line):

| Line | Item (start) | RES |
|---|---|---|
| 5 | - [OPEN?] (boundary) SPK-05 Excluded names HRN-05 for OQ-29 and DUR-06 for OQ-25, but neither master 'included | RES-001 |
| 6 | - (boundary) SPK-02 Excluded 'anchor input DENY (RUL-01)': RUL-01's master 'included' list does not contain it | RES-202 |
| 7 | - (boundary) SPK-04 Excluded omitted the master's exclusion 'Spike 9 beyond a note'. Added it with owner WSP-0 | RES-202 |
| 8 | - (boundary) SPK-04 Included 'S71 repro' overlaps WSP-05's included 'exit-status test that reproduces the haza | RES-202 |
| 9 | - [OPEN?] (boundary) SPK-05 Excluded 'perf smoke runs (DUR-04, SES-08)': the SQLite perf smoke is also in OPS- | RES-002 |
| 19 | - [OPEN?] (other) Master and wf1 citation drift to fix at the source: master §5 item 33 cites child_session_re | RES-011 |
| 22 | - [OPEN?] (other) The writer's reviewer notes still stand and remain open in the master: OQ-37 and OQ-47 have  | RES-003, RES-005, RES-006, RES-007, RES-008, RES-009, RES-010 |
| 26 | - [OPEN?] (boundary) custom_lint.RULES registration of the boundary rule has no owner in the master. FND-01's  | RES-012 |
| 27 | - (boundary) FND-01's master 'included' owns the tier-c omnigent.db allowlist, but FND-03's master 'included'  | RES-202 |
| 28 | - [OPEN?] (boundary) Master overlap: FND-03 ('Single-head ... tests') and DUR-01 ('single-head and models-matc | RES-014 |
| 29 | - [OPEN?] (boundary) Master overlap: FND-04 (fixture), OPS-02 (CI suites 'plus the split-DB lane') and DUR-01  | RES-015 |
| 32 | - [OPEN?] (boundary) FND-03 adds 'python -m coral.db.migrate upgrade' as a recovery command. No feature owns i | RES-016 |
| 33 | - [OPEN?] (other) Deploy entrypoints: S32 wires server_plugins only in omnigent/cli.py:5136-5137. deploy/datab | RES-017 |
| 37 | - (other) FND-04: the Tier B sample needs TLS-01's S7, S8, S10 and S50, but TLS-01 is not a declared dependenc | RES-022 |
| 39 | - (other) FND-05: S39d edits .github/scripts/ci/python-matrix.json, and JSON cannot hold a CORAL(Sx) anchor co | RES-092 |
| 41 | - (other) FND-05: the master key_paths omit .github/workflows/ci.yml, but S39c needs ci.yml:198 because --cov= | RES-023 |
| 45 | - (other) Carried from the writer (still open): the master path dev/lint/coral_boundary.py was renamed to lint | RES-013, RES-014, RES-020, RES-021 |
| 50 | - [OPEN?] (boundary) ENG-06 vs SES-04: both master 'included' lists claim the cancel chain interrupt -> stop - | RES-024 |
| 51 | - [OPEN?] (boundary) ENG-06 vs TLS-02: TLS-02's master scope lists a 'per-slot rejected counter', and ENG-06's | RES-025 |
| 52 | - (boundary) ENG-06 vs SES-06: decision 12's restart ladder appears in both scopes. ENG-06 retry emits recover | RES-202 |
| 53 | - [OPEN?] (boundary) ENG-03 vs HRN-02: both master scopes name V10 against configured harnesses, with no edge  | RES-026 |
| 54 | - [OPEN?] (boundary) ENG-02 vs ENG-09: ENG-02's compile resolves group entry and exit, which the D§5.6 fixture | RES-027 |
| 55 | - (boundary) ENG-04 vs TLS-02: the slot 'evaluating' state is K2/ENG-04, but the evaluating lease (X-15) and t | RES-202 |
| 56 | - (boundary) ENG-04 vs SES-04: post_close_activity -> paused(drift) appears in both master scopes. The spec ke | RES-189 |
| 57 | - [OPEN?] (boundary) ENG-06 overdue timer kind vs ENG-09 overdue alerts: the split is consistent, but K19 has  | RES-028 |
| 58 | - [OPEN?] (other) Truth fix, ENG-06: gate reminders were shipped 'off at M2', which contradicts the master inc | RES-029 |
| 61 | - [OPEN?] (other) ENG-06: the 30-minute watchdog default is now labelled as SPK-05's unsourced OQ-14 proposal. | RES-030, RES-031 |
| 62 | - [OPEN?] (other) ENG-04: 'week 4.5' for the skeleton comes from the delivery critique, not the master; the ma | RES-032 |
| 68 | - [OPEN?] (other) Writer issues confirmed and carried as reviewer notes: K8 RunView types have no tier-(a) hom | RES-006, RES-026, RES-028, RES-031, RES-033, RES-034, RES-035, RES-036 |
| 74 | - (boundary) ENG-08 Included 'repeat-scoped groups' conflicted with master ENG-08 excluded 'Groups (ENG-09)' a | RES-027 |
| 76 | - (boundary) ENG-08 Excluded 'K14 batch payload (SES-10, GTE-01)': GTE-01's master included does not cover bat | RES-062 |
| 78 | - (boundary) ENG-09 reaction 'gate waits more than N hours -> alert' overlaps ENG-06's master 'Gate reminders  | RES-028 |
| 90 | - [OPEN?] (other) Remaining, writer reviewer notes validated as accurate: K1 and K7 have no home for the templ | RES-028, RES-034, RES-039, RES-040, RES-041, RES-044 |
| 91 | - [OPEN?] (other) Remaining, new reviewer note: ENG-08's `requires_structure_runtime` is an additive K1 Analys | RES-037 |
| 92 | - [OPEN?] (other) Remaining, not fixed because of the word cap: ENG-09 step 5 says the blocks router 'mounts o | RES-038 |
| 96 | - (boundary) DUR-06 Excluded 'the settings shell (HRN-04)' was wrong: HRN-04's master 'included' list has no s | RES-051 |
| 97 | - [OPEN?] (boundary) DUR-06 Excluded 'legal hold (deferred)': legal hold is not in master §7 deferred_gaps and | RES-045 |
| 98 | - (boundary) DUR-03 vs ENG-06: both master 'included' lists claim start_key to run id (ENG-06 has 'start_key t | RES-189 |
| 100 | - (boundary) DUR-05 vs GTE-01: DUR-05 includes 'Trigger gate re-publish', and GTE-01 includes 're-publish on s | RES-189 |
| 101 | - (boundary) DUR-05 vs SES-06: DUR-05 includes 'stale runner_last_seen marks slots suspect', and SES-06 includ | RES-189 |
| 102 | - (boundary) DUR-03 vs DUR-05: both master 'included' lists claim commit-boundary tests. DUR-03 owns the atomi | RES-202 |
| 109 | - [OPEN?] (other) Test-path layout: DUR-02's API test moved to tests/coral/api/ (API-02's master root; this al | RES-046 |
| 112 | - [OPEN?] (other) Writer's reviewer notes kept, since all are valid: §9 omits coral_0002's effects, signals an | RES-023, RES-024, RES-047, RES-048, RES-049, RES-050 |
| 120 | - [OPEN?] (boundary) SES-05 Excluded 'Browser E2E': the master gives no owner. The spec assigns it to OPS-07 t | RES-052 |
| 121 | - (other) I confirmed the writer's issues. (1) SES-02 consumes K18, which SES-01 produces in the same weeks, w | RES-050, RES-053, RES-055, RES-056, RES-057, RES-058, RES-059 |
| 122 | - [OPEN?] (other) New master gap: SES-04 consumes K5 and K21, and its stable_ids migration needs coral_0001 (§ | RES-053 |
| 123 | - [OPEN?] (other) New ambiguity: the master's 'relay turn end' origin site could mean B1 (the relay recovery a | RES-054 |
| 124 | - (other) wf1 truth corrections: gap_analysis and current_state cite sqlalchemy_store.py:1145-1156 for Convers | RES-050 |
| 126 | - [OPEN?] (other) Migration train §9 lists ADR-05 as the only prerequisite for session_bindings, but the singl | RES-053 |
| 127 | - (other) SES-04's post-close detection of a 'running edge' needs a status-edge observer, but SES-08 owns the  | RES-058 |
| 133 | - (boundary) SES-06 (fixed): the ladder defined five new K21 kinds (recovery.create, recovery.salvage_reset, r | RES-202 |
| 136 | - [OPEN?] (boundary) SES-09 vs PRF-01 (master-level overlap): both master 'included' lists claim slot-start dr | RES-060 |
| 137 | - [OPEN?] (boundary) SES-08 vs OPS-07 and DUR-04 (master-level overlap): the 529/429/401 Tier B case is in bot | RES-002, RES-004 |
| 138 | - (boundary) SES-08 (fixed): the spec had SES-08 raising the K19 auth alert. GTE-06's 'included' has 'Producer | RES-202 |
| 139 | - [OPEN?] (boundary) SES-07: the take-over and hand-back endpoints are SES-07's (API-02 excludes 'Take-over en | RES-061 |
| 140 | - [OPEN?] (boundary) SES-10: no feature's 'included' covers how a batched gate card is presented. GTE-02's car | RES-062 |
| 160 | - 'Fork drops only mode labels' was wrong. The fork also drops MCP-selection keys on an agent switch, and the  | RES-110 |
| 171 | - [OPEN?] (other) Writer issues re-checked: | RES-041, RES-067 |
| 174 | - [OPEN?] (other) Master or schedule issues still open (kept as reviewer notes): | RES-038, RES-042, RES-061, RES-063, RES-064, RES-065 |
| 186 | - (boundary) TLS-01 vs FND-02: both master 'included' lists claim the coral_runner:n host token. FND-02's K17  | RES-021 |
| 188 | - (boundary) TLS-03 vs PRF-01 vs RUL-01: TLS-03 includes 'orchestrator_guard in bundle guardrails', PRF-01 inc | RES-189 |
| 189 | - (boundary) TLS-03 vs ENG-04: both master lists include decision requests with legal labels and the per-agent | RES-202 |
| 190 | - [OPEN?] (boundary) TLS-04 Excluded 'sys_session_message reuse' and TLS-05 Excluded 'step agents asking direc | RES-068 |
| 192 | - [OPEN?] (boundary) TLS-04 Technical scope says Tier B multi-session coverage of the messaging tools 'stays i | RES-069 |
| 194 | - [OPEN?] (other) Writer's reviewer notes kept as valid: TLS-01 S49 is 'Up: Yes' but missing from the master's | RES-070, RES-071, RES-072, RES-073, RES-074 |
| 195 | - (other) TLS-01: FND-02's spec adds CORAL_DISABLE_HOST_ENTRY_POINTS to K17 and names TLS-01 as its implemente | RES-021 |
| 196 | - [OPEN?] (other) TLS-02 reviewer note refined. ENG-04's spec (eng-a.md:297-298) already models slot 'evaluati | RES-042 |
| 198 | - (other) Cross-spec: WSP-03's spec says it uses a fake assign_task 'until TLS-04 lands', but TLS-04 (weeks 13 | RES-073 |
| 205 | - [OPEN?] (boundary) GTE-06 Excluded 'Emitting effects: ENG-04, ENG-06, TLS-05, DUR-05 and SES-08' was wrong o | RES-075 |
| 206 | - (boundary) GTE-03 Excluded 'Gate links: GTE-01' did not match the master. GTE-01's 'included' list has no de | RES-202 |
| 207 | - [OPEN?] (boundary) Three Excluded items have no owner feature. GTE-02 'localStorage read state' was dropped  | RES-076 |
| 210 | - (boundary) GTE-02 and WEB-05 both list 'Step waiting on you' in their master 'included' lists. The spec spli | RES-202 |
| 211 | - (other) GTE-01 truth fix: the spec said 'Decline and cancel are hidden on schema forms'. That is false at HE | RES-201 |
| 214 | - [OPEN?] (other) GTE-01 reviewer note corrected. Coral gates never reach ApprovePage.tsx:240 (requestedSchema | RES-077 |
| 219 | - (other) GTE-04 (UNVERIFIED): Electron has no Web Push service. Also unverified: the iOS and Android WebViews | RES-082 |
| 221 | - [OPEN?] (other) Writer issues confirmed and still open: the /approve multi-label fix has no owner. GTE-02 (w | RES-028, RES-051, RES-077, RES-078, RES-079, RES-080, RES-081 |
| 227 | - (boundary) EVD-02 vs TLS-02 (fixed): the EVD-02 evidence port did 'wait (spike-7 bound)', but TLS-02's maste | RES-202 |
| 228 | - (boundary) API-02 Excluded 'amendments (ENG-10)' (fixed): ENG-10's master 'included' covers only restart-fro | RES-202 |
| 229 | - [OPEN?] (boundary) EVD-04 Excluded 'held-out tests, LLM rubric judges (deferred)' (fixed): neither is in the | RES-083 |
| 230 | - (boundary) EVD-02 Excluded 'codex (HRN-05, HRN-06)' (open): HRN-05 includes codex-native adapter exit_code o | RES-097 |
| 231 | - (boundary) L1 fingerprint ownership is split three ways (open). EVD-01's spec owns the shared L1 probe and d | RES-096 |
| 232 | - (boundary) WSP-01 and WSP-06 both claim the K13 session-shell backend (open). WSP-01: 'session-shell and hos | RES-096 |
| 233 | - (boundary) API-02 vs RUL-05 (open): API-02 owns the K4 usage adapter (SES-01 names API-02 as implementer), w | RES-095 |
| 237 | - [OPEN?] (other) Stale reviewer note (fixed), EVD-04: 'the ledger must name EVD-04 as S72 amendment owner'. M | RES-084 |
| 238 | - [OPEN?] (other) Partly wrong reviewer note (fixed), EVD-02: K6, which EVD-02 consumes, carries the 'params.c | RES-085 |
| 239 | - [OPEN?] (other) Stale reviewer note (removed), API-02: dur.md now puts DUR-02 API tests under tests/coral/ap | RES-046 |
| 241 | - (other) Ref (fixed), API-01: msw 2.15.0 is in pnpm-lock.yaml only as @vitest/mocker's optional peer (7390, 1 | RES-092 |
| 244 | - [OPEN?] (other) New reviewer note, EVD-03: the migration train makes WSP-01's repo_bindings a prerequisite o | RES-086 |
| 245 | - [OPEN?] (other) New reviewer note, EVD-01: compile_done_when lands in ENG-02's compiler during the same week | RES-087 |
| 246 | - (other) Master gap, API-01: the K7 contract text omits EVD-03's /v1/coral/repos/*/command-patterns routes. T | RES-090 |
| 247 | - (other) Still-valid master issues from the writer: the K11 watermark definition (no item seq on the claude-s | RES-088, RES-089, RES-090, RES-091, RES-093, RES-094 |
| 252 | - (boundary) RUL-01 vs PRF-01: both master 'included' lists claim the spawn: false grant (PRF-01 hygiene, RUL- | RES-108 |
| 253 | - (boundary) RUL-01 vs EXT-02: both master 'included' lists claim a coral.omni.policies DENY on session-read t | RES-109 |
| 255 | - [OPEN?] (boundary) RUL-01 vs API-02 and ENG-01: RUL-01 adds ResumeRun.raise_session_cap_usd and a SessionCap | RES-043 |
| 257 | - [OPEN?] (boundary) RUL-02: the thin routes in coral/api/guarantees.py (GET /v1/coral/runs/{id}/guarantees an | RES-098 |
| 258 | - (boundary) RUL-03 vs RUL-06: both master 'included' lists claim that an unenforceable Required rule fails va | RES-189 |
| 259 | - (boundary) RUL-04 Excluded names HRN-03 and HRN-05 for 'setting fail_closed in native step bundles', but nei | RES-189 |
| 260 | - (boundary) RUL-05 vs WEB-09: both master 'included' lists contain 'step budget fields'. The spec splits them | RES-189 |
| 266 | - [OPEN?] (other) Fixed in RUL-03: the reviewer note cited datamodel.py:570-640 as 'no nested deny'. Built-in  | RES-099, RES-100 |
| 274 | - [OPEN?] (other) Open reviewer notes kept from the writer: S52 is four builder.py sites, not one line. The pr | RES-040, RES-100, RES-101, RES-102, RES-103, RES-104, RES-105, RES-106, RES-107 |
| 275 | - [OPEN?] (other) New reviewer note (RUL-01): the SessionCapReached observation and ResumeRun.raise_session_ca | RES-043 |
| 280 | - [OPEN?] (boundary) HRN-04 master 'mock-provider probe' overlaps HRN-08 'Bench probes with offline verdict te | RES-112 |
| 281 | - [OPEN?] (boundary) HRN-04 master says it 'replaces SES-08's text matching', but the failed-turn classifier b | RES-113 |
| 285 | - (boundary) PRF-01 Excluded gives 'the claude-native branch' to HRN-03. HRN-03's master included implies it ( | RES-189 |
| 296 | - [OPEN?] (other) Writer's master-level reviewer notes, still open for the master owner: PRF-01 and HRN-02 use | RES-026, RES-041, RES-066, RES-114, RES-115, RES-116 |
| 302 | - [OPEN?] (boundary) HRN-07 excluded 'the codex-native rotation journey (HRN-05)', but HRN-05's master 'includ | RES-118 |
| 303 | - [OPEN?] (boundary) HRN-07 includes '/clear policy (OQ-46)', and EXT-04's master 'included' also claims 'S46  | RES-119 |
| 304 | - (boundary) HRN-05's master 'included' lists 'honest labels', and RUL-06's 'included' lists 'Labels for claud | RES-127 |
| 305 | - (boundary) Two features claim codex-native K9 values: HRN-08 includes 'claude-native, codex-native and headl | RES-127 |
| 306 | - (boundary) HRN-05 and HRN-04 share the S24 Codex branch (HRN-04 includes 'Codex branch with HRN-05'). The he | RES-126 |
| 307 | - (boundary) HRN-09 added 'one stance row in PRF-01's generator', but PRF-01's master 'included' has no codex  | RES-189 |
| 318 | - [OPEN?] (other) Reviewer note added for HRN-06: gate_failure_mode=deny depends on RUL-04's S14 fail-closed o | RES-120 |
| 319 | - [OPEN?] (other) Reviewer note added for HRN-09: §6.5 lists HRN-09 on codex_executor.py as S18 and S60. S19's | RES-121 |
| 320 | - [OPEN?] (other) Reviewer note extended for HRN-07: it uses K10 deterministic policy ids that the master does | RES-044, RES-066, RES-122 |
| 321 | - (other) Writer's S62 note confirmed and reworded: codex-native approval requests (item/commandExecution\|file | RES-125 |
| 322 | - (other) Still open from the writer: HRN-09 needs an OQ-29 conditional to match M4 exit 4. HRN-06's S20 runne | RES-124 |
| 329 | - [OPEN?] (boundary) WSP-05 Excluded named 'other to_thread handlers (an OPS-05 follow-up)', but OPS-05's mast | RES-128 |
| 332 | - [OPEN?] (boundary) WSP-07 Excluded 'the consent UI (WEB-03)', but WEB-03's master scope has no push consent  | RES-130 |
| 333 | - [OPEN?] (boundary) WSP-04 Excluded 'provider onboarding (upstream)', which names no feature id. Left as is b | RES-131 |
| 334 | - [OPEN?] (boundary) WSP-04 says WEB-03 renders the managed-sandbox choice and the 'This provider loses work w | RES-132 |
| 335 | - [OPEN?] (boundary) WSP-01's sandbox report defines its own token 'coral_host_sandbox:1:...' through S50. The | RES-021 |
| 343 | - [OPEN?] (other) WSP-01 registers the K21 executor workspace.create_run_worktree but does not consume K21. Th | RES-133 |
| 344 | - (other) WSP-01's K13 v1 error list (op_host_violation, backend_unavailable, git_failed, timeout) omits error | RES-134 |
| 347 | - [OPEN?] (other) Extended the WSP-03 Reviewer note. SES-10 (weeks 14-16) soft-depends on WSP-07 as well as WS | RES-064 |
| 348 | - [OPEN?] (other) Writer reviewer notes confirmed and kept: K13 v1 at IM-0 week 3 (M1 exit item 7) against WSP | RES-038, RES-129, RES-133, RES-135, RES-136, RES-137 |
| 349 | - [OPEN?] (other) Cross-spec: WSP-06 persists only diff_stat on the handoff, but API-02's run outcome needs a  | RES-094 |
| 355 | - [OPEN?] (boundary) Nothing in the master's 'included' lists covers GET /v1/coral/templates or POST /v1/coral | RES-140 |
| 356 | - (boundary) WEB-03 Excluded is now split by owner: runs and preflight endpoints (API-02), repo bindings (WSP- | RES-202 |
| 357 | - [OPEN?] (boundary) Both WEB-01 (the 'failing saved case with expected vs actual path' state) and WEB-12 (the | RES-141 |
| 358 | - (boundary) The axe dependency PR is in no feature's 'included' list, and both WEB-04 and WEB-09 need axe. St | RES-092 |
| 359 | - [OPEN?] (boundary) Two master key_paths have no seam: web/src/shell/SubagentTab.tsx for WEB-05 and web/src/p | RES-142 |
| 360 | - (boundary) Both WEB-05 (run-view chip) and GTE-02 (Inbox) include 'Step waiting on you'. They are different  | RES-202 |
| 369 | - (other) Kept from the writer, still open (1/2): WEB-01 finishes in week 5, before DUR-02 and ENG-07, so its  | RES-052, RES-145, RES-146 |
| 370 | - (other) Kept from the writer, still open (2/2): msw is only a transitive dependency (pnpm-lock.yaml:7390, th | RES-092, RES-147, RES-150 |
| 376 | - [OPEN?] (boundary) WEB-13 places PromiseLabelChip.tsx and promiseLabel.ts in web/src/workflows/guarantees/,  | RES-143 |
| 377 | - (boundary) WEB-13's PhoneRunView.tsx sat in the web/src/workflows/runs/ root, which is WEB-04's key path. Mo | RES-023 |
| 378 | - [OPEN?] (boundary) Master overlap: WEB-01's included list has the 'failing saved case with expected vs actua | RES-141 |
| 379 | - [OPEN?] (boundary) Master overlap: WEB-10's key_paths include web/src/workflows/runs/, which is also WEB-04' | RES-144 |
| 385 | - [OPEN?] (other) Refined WEB-11's reviewer note: wf1 cites monacoSetup.ts:12-17 for the worker in G-70, curre | RES-050 |
| 386 | - (other) Open (master): WEB-09 calls K7 (:validate, ENG-09's /v1/coral/blocks routes), but contracts_consumed | RES-150 |
| 387 | - (other) Open (producer additions, all additive K7): DUR-02's draft PUT needs a layout field (WEB-08); :valid | RES-150 |
| 388 | - (other) Open: WEB-12 has no /v1/coral/info sub-feature key (DoD 6.1 item 6) and merges dark by staying unmou | RES-038 |
| 389 | - (other) Confirmed at HEAD: there is no axe dependency (no match in pnpm-lock.yaml or uv.lock), so WEB-09's p | RES-092 |
| 391 | - (other) Minor: WEB-10 assumes a 403 for a non-owner take-over, but SES-07's spec says only 'not_permitted' a | RES-151 |
| 396 | - [OPEN?] (boundary) S89 overlap. The master seam owner index gives S89 to BRD-01, but S89's scope (gap_analys | RES-154 |
| 399 | - (boundary) BRD-02 Excluded 'typed client (API-01)'. API-01's master 'included' lists generated TS types, MSW | RES-189 |
| 400 | - [OPEN?] (boundary) BRD-03 Android run deep links have no owner. The master 'included' says 'run deep links ( | RES-155 |
| 401 | - (boundary) BRD-03 Excluded 'store listings, mobile bundle ids and signing (OQ-31)' names an open question, n | RES-161 |
| 407 | - [OPEN?] (other) Master text issue, kept as a reviewer note. BRD-03's proving-test link coral://workflows/run | RES-156 |
| 408 | - [OPEN?] (other) Master text issue, now a reviewer note. BRD-02's proving test says 'unknown routes no longer | RES-156 |
| 409 | - [OPEN?] (other) Master text issue, now a reviewer note. G-82 and BRD-03 say 'about 37 literals'; that is the | RES-157 |
| 410 | - [OPEN?] (other) Writer's issues confirmed as reviewer notes, master unchanged. BRD-02 lands three upstream s | RES-050, RES-158, RES-159 |
| 411 | - [OPEN?] (other) Word counts after corrections are slightly over the 900-word cap: BRD-01 903, BRD-02 907, BR | RES-160 |
| 417 | - [OPEN?] (boundary) OPS-03's Excluded list gave the 'server_plugins default' to FND-02. FND-02's master scope | RES-018 |
| 421 | - (boundary) FND-01's spec (fnd.md:160) still records the upstream PR in .coral/upstream.yaml. OPS-01, K16 and | RES-163 |
| 422 | - (boundary) OPS-04's new two-process lease test overlaps DUR-04's test_worker_lease.py, which runs two app in | RES-189 |
| 423 | - (other) Confirmed the writer's issues: the fork point 2a9cbe2c2 is 4 commits past nightly^1 ee7a319f7, an an | RES-163, RES-164, RES-165, RES-166, RES-167, RES-168, RES-169 |
| 425 | - [OPEN?] (other) New: _default_runner_id_path (omnigent/runner/identity.py:239-244, used at 197 unless OMNIGE | RES-162 |
| 432 | - (other) Open: OPS-02's 'Dependabot off for upstream manifests' has no stated mechanism. Editing .github/depe | RES-171 |
| 440 | - (boundary) OPS-08 'included' says 'OQ-28 and OQ-35 written answers recorded, or the fallback applied', but S | RES-175 |
| 441 | - [OPEN?] (boundary) OPS-08 master 'excluded' says 'M4 structure work' with no owner. The spec now names OPS-0 | RES-175 |
| 442 | - (boundary) OPS-09 Excluded named a 'BRD-03 desktop row' that BRD-03's master 'included' does not cover. BRD- | RES-202 |
| 443 | - (boundary) OPS-06 and SPK-01 overlap on OQ-43: SPK-01's threat-model checkpoint names S49/OQ-43, and OPS-06  | RES-200 |
| 445 | - (other) New verified fact, OPS-06 and OQ-43: the CLI `server` command always builds a SqlAlchemyPermissionSt | RES-179 |
| 447 | - (other) OPS-09: the GTE-03 spec allows loopback http only on single-user servers. Because of the permission- | RES-179 |
| 448 | - (other) OPS-08: E2E-4's file was `tests/e2e/resilience/scenarios/test_s8_policy_outage.py`, which conflicts  | RES-202 |
| 451 | - (other) OPS-07: e2e-run builds an old server only from a release tag that matches a version regex (`action.y | RES-174 |
| 453 | - (other) OPS-07 (writer, still open): a one-week soak gives 7 nightlies against SPK-05's 9-of-10 threshold; I | RES-052, RES-172, RES-173, RES-174 |
| 454 | - (other) OPS-06 (writer, still open): its weeks 4-6 window comes before GTE-01 (weeks 7-9) and PRF-01 (to 9.5 | RES-170 |
| 456 | - (other) OPS-08 (writer, still open): HRN-07 finishes in week 20, the day OPS-08 starts. Whether CI can prese | RES-176 |
| 457 | - (other) OPS-09 (writer, still open): OQ-29 decides the reviewer variant but is missing from OPS-09's open_qu | RES-177, RES-178 |
| 462 | - (boundary) EXT-02 vs RUL-01: master RUL-01 'included' lists 'input-scope deny (internal_only)', and the RUL- | RES-109 |
| 464 | - (boundary) EXT-01 Excluded named ENG-10 for 'running-run edits', but ENG-10 excludes 'Apply to this run' (de | RES-202 |
| 465 | - (boundary) EXT-01 Excluded named EXT-03 for 'repo writes or PRs', but EXT-03 owns only the .coral/ write op  | RES-202 |
| 466 | - (boundary) EXT-02 Excluded named WEB-10 for the 'pass counter', but loop counters are in WEB-04's included ( | RES-202 |
| 467 | - [OPEN?] (boundary) EXT-03 Excluded named WEB-03 for the 'imported-template gallery', but WEB-03's included d | RES-180 |
| 468 | - (boundary) EXT-05: TasksPage.tsx is a BRD-02 key path (S84 header at TasksPage.tsx:237-267, which holds the  | RES-182, RES-188 |
| 469 | - (boundary) EXT-01, EXT-03 and EXT-05 surfaces (Suggestions tab, Export dialog, Run-workflow dialog) and the  | RES-188 |
| 479 | - [OPEN?] (other) EXT-03 DoD now quotes the master proving test path .coral/<id>.yaml and notes that it resolv | RES-181, RES-182 |
| 480 | - [OPEN?] (other) Writer's reviewer notes still open (not master changes): EXT-01 needs DUR-02 and K7 and has  | RES-182, RES-183, RES-184, RES-185, RES-186 |
| 500 | - [D] Stale gate answer code is named differently in two specs: GTE-01 uses 409 `stale_visit`, API-02 uses 409 | RES-151 |
| 501 | - [D] X-15: the TLS-02 spec notes that `coral_0001_core` (DUR-01) has no evaluating-lease field. It must go in | RES-042 |
| 502 | - [D] FND-01 does not assign `coral.identity` (K10) to an import tier. D.3 places it in tier a (no I/O) pendin | RES-020 |
| 503 | - [D] Master FND-01 key path `dev/lint/coral_boundary.py` breaks the `lint_<name>.py` convention (`dev/lint/cu | RES-013 |
| 504 | - [D] UI§10 places CoralPageHeader at `web/src/components/concerto/CoralPageHeader.tsx`. BRD-02 owns it at `we | RES-199 |
| 508 | - [H] Master §6.2 says one platform engineer moves to GTE-03, DUR-06 and the OPS-04 load scenario at M2. But G | RES-193 |
| 509 | - [H] The levelled plan's binding chain into M4 is WEB-08 > WEB-09 > OPS-09, and it is set by WEB staffing rat | RES-192 |
| 510 | - [H] SES-05 has to start at week 9.5 on an engineer who frees up then, and both candidates' features (SES-06  | RES-197 |
| 511 | - [H] OPS-07 owns IM-3 and IM-4 at week 11.5, but its own window also starts at 11.5. The lane build-out has t | RES-173 |
| 512 | - [H] Two migration-train orderings are hidden inside feature windows. The questions table (TLS-05, weeks 9-11 | RES-053, RES-074 |
| 513 | - [H] K15 (RUL-03) and K20 (WSP-02) ship in the same week their first consumers start (RUL-06 and EVD-04, both | RES-194 |
| 518 | - [I] M1 has no acceptance-lane feature and master §3 names no M1 exit gate owner. The section proposes the te | RES-191 |
| 520 | - [I] The spike-4 fallback (master §6.4) is not costed. In a re-run, one extra week on FND-04 moves levelled M | RES-195 |
| 522 | - [I] WEB-11 (cut rank 2) is a hard input of WEB-06 (M3) and WEB-08 (on the M4 levelled path). If it is deferr | RES-196 |
| 523 | - [I] Levelled M3 is bound by the phase gate: HRN-03's last input (SES-08) lands at week 11, but PH3 opens at  | RES-192 |
| 525 | - [I] K13 timing conflict: EVD-01 (weeks 3-5) consumes K13 before WSP-01 (weeks 5-7) freezes it as its first P | RES-135 |
| 526 | - [I] OPS-06 is levelled at weeks 4-6, but M2 exit 14 (no open high findings) covers surfaces that land later: | RES-170 |
| 527 | - [I] The 9-of-10 soak threshold needs ten credentialed runs inside OPS-07's one-week soak tail, and the night | RES-172 |
| 530 | - [J] OQ-9 (saving invalid drafts) has no decision record in SPK-01 or SPK-05, although DUR-02 starts in week  | RES-006 |
| 531 | - [J] OQ-37 (profile metadata) and OQ-47 (coral.omni coupling) shape K4 and K12 at IM-0 but appear only in SES | RES-007 |
| 532 | - [J] OQ-11 (take-over), OQ-25 (retention), OQ-31 (app ids) and OQ-51 (bench budget) have no default in the so | RES-198 |
| 536 | - [J] Some cited lines were not re-verified this session and are carried over from current_state.md or the spe | RES-011 |
| 538 | - [V] The 197 spec reviewer notes are not reflected in master_v2_fix1.json. I confirmed that the recommended s | RES-026, RES-039, RES-056, RES-137, RES-190 |
| 539 | - [V] Only master v1 went through the five critiques. v2 got only the mechanical re-check and the spec-writing | RES-190 |
| 540 | - [V] Master §6.5 places the archive-idle origin in routes_events.py. At HEAD it is published at omnigent/serv | RES-055 |
| 549 | - [A] The early-start levers (HRN-03 at week 11, WEB-08 at M2) come from §I.7 and §I.8 scheduler re-runs, not  | RES-192 |
| 551 | - [A] Master names no M1 acceptance lane or exit-gate owner (§I.2 proposes the tech lead). The executive summa | RES-191 |

Reviewer notes in `verification/reviewer_notes.md` (by line):

| Line | Feature | Note (start) | RES |
|---|---|---|---|
| 3 | BRD-01 | - Reviewer note: S89 (BRD-01) lists the Electron setup and connect pages, which BRD-03 includes. Spl | RES-154 |
| 4 | BRD-02 | - Reviewer note: the three upstream seams need K16, which the contracts omit. | RES-158 |
| 5 | BRD-02 | - Reviewer note: `withPageView` is module-private, so the call is `coralRoutes(prefix, withPageView) | RES-159 |
| 6 | BRD-02 | - Reviewer note: the proof's "unknown routes" means Coral desk paths, the only ones excluded. | RES-156 |
| 7 | BRD-03 | - Reviewer note: "about 37 literals" is `main.js` only; `desktop_updater.js`, `quitConfirmation.js:2 | RES-157 |
| 8 | BRD-03 | - Reviewer note: the master's proof link has no host, so `workflows` parses as the host; use `coral: | RES-156 |
| 9 | BRD-03 | - Reviewer note: the proof needs BRD-02's routes. Add BRD-02 as a soft dependency. | RES-158 |
| 10 | BRD-03 | - Reviewer note: Android has no custom-scheme handler (`web/android/app/src/main/AndroidManifest.xml | RES-155 |
| 11 | DUR-01 | - Reviewer note: SES-08's "persisted edge facts" have no table in §9. They are resolved here as unap | RES-042 |
| 12 | DUR-01 | - Reviewer note: §9's coral_0002_queue row ("queue, timers") omits effects, signals and the worker l | RES-047 |
| 13 | DUR-02 | - Reviewer note: wf1 cites `get_artifact_store` at `runtime/__init__.py:96-106`. At HEAD it is at `: | RES-050 |
| 14 | DUR-03 | - Reviewer note: step 3 needs DUR-04's first PR (coral_0002_queue) inside DUR-03's window, but the m | RES-049 |
| 15 | DUR-04 | - Reviewer note: the §9 row "coral_0002_queue (queue, timers)" should also name effects, signals and | RES-047 |
| 16 | DUR-05 | - Reviewer note: cancelling an unreadable run cannot use the reducer. ENG-06's cancel is a transitio | RES-024 |
| 17 | DUR-06 | - Reviewer note: §9 has no DUR-06 migration, but the policy and jobs need `coral_00NN_retention`. | RES-048 |
| 18 | DUR-06 | - Reviewer note: no feature or seam owns a Coral entry in the closed settings union (`web/src/shell/ | RES-051 |
| 19 | DUR-06 | - Reviewer note: the remap runs in the CLI outside the lifespan, so S56 also touches `omnigent/cli.p | RES-023 |
| 20 | ENG-01 | - Reviewer note: K3 embeds K8's patch, but ENG-01 has no edge to API-01 (only API-01's soft edge bac | RES-033 |
| 21 | ENG-01 | - Reviewer note: reserve a K1 `parameters` block now for ENG-07. | RES-034 |
| 22 | ENG-01 | - Reviewer note: DD§5.3.3(a) counts traversals, but D§5.6 ("three passes"), M2 journey step 4 ("pass | RES-035 |
| 23 | ENG-02 | - Reviewer note: the D§5.6 fixture needs group entry and exit resolved, but ENG-09's master scope ow | RES-027 |
| 24 | ENG-03 | - Reviewer note: OQ-9 is on neither SPK-01's nor SPK-05's list; ENG-03 and DUR-02 assume the default | RES-006 |
| 25 | ENG-03 | - Reviewer note: HRN-02's master scope also lists V10 in its preflight engine (weeks 3-5), with no e | RES-026 |
| 26 | ENG-04 | - Reviewer note: `projection.py` emits K8 patches; add K8 to ENG-04's consumed contracts. | RES-033 |
| 27 | ENG-04 | - Reviewer note: I7 needs ENG-11's reconcile, so the proof checks I7 only in reducer form. | RES-036 |
| 28 | ENG-05 | - Reviewer note: passes versus traversals is the same open point as in ENG-01; this spec uses passes | RES-035 |
| 29 | ENG-06 | - Reviewer note: TLS-02's master scope also lists a per-slot rejected counter, and SES-04's the canc | RES-024, RES-025 |
| 30 | ENG-06 | - Reviewer note: K19 has no overdue kind (ENG-09) and no tier-(a) home. | RES-028 |
| 31 | ENG-06 | - Reviewer note: M2 exit 4 and the proof say "pause the slot"; D§7.3 pauses the run, which this spec | RES-031 |
| 32 | ENG-07 | - Reviewer note: the parameter declaration has no contract home (no K1 `parameters` key or K7 field) | RES-034 |
| 33 | ENG-07 | - Reviewer note: per-reviewer models need a K1 roster model override. | RES-034 |
| 34 | ENG-08 | - Reviewer note: the proof and Simulate support extend ENG-07; propose a soft edge ENG-08 -> ENG-07. | RES-039 |
| 35 | ENG-08 | - Reviewer note: SES-10 (week 14) repeats over a multi-step group, but master ENG-08 excludes "Group | RES-027 |
| 36 | ENG-08 | - Reviewer note: additive K1 Analysis flag `requires_structure_runtime` (read by HRN-02's preflight) | RES-037 |
| 37 | ENG-09 | - Reviewer note: K19 has no overdue or reaction kind; needs an additive change signed by SES-01 and  | RES-028 |
| 38 | ENG-09 | - Reviewer note: the proof runs ENG-07's Simulate, not a listed dependency; propose a soft edge. | RES-039 |
| 39 | ENG-09 | - Reviewer note: V8 needs a strictness order per K15 template, absent from RUL-03's first PR; propos | RES-040 |
| 40 | EVD-01 | - Reviewer note: the master's watermark is the "last ingested tool-result item seq", but claude-sdk  | RES-088 |
| 41 | EVD-01 | - Reviewer note: `stat` flags differ between BSD and GNU; `git hash-object --stdin-paths` over dirty | RES-088 |
| 42 | EVD-01 | - Reviewer note: step 5 lands in ENG-02's compiler (same weeks 3-5) with no edge; agree the hook wit | RES-087 |
| 43 | EVD-02 | - Reviewer note: the proof needs TLS-02 and WSP-06's session-shell fingerprint (weeks 7-9, no edge), | RES-089 |
| 44 | EVD-02 | - Reviewer note: the `evidence` opt-in must be a K6 params.coral key (consumed); the S68 observer re | RES-085 |
| 45 | EVD-03 | - Reviewer note: EVD-03 serves `/v1/coral/repos/*` without consuming K7; API-01's spec reserves the  | RES-090 |
| 46 | EVD-03 | - Reviewer note: the snapshot writes through DUR-02's store, but there is no edge to DUR-02. | RES-090 |
| 47 | EVD-03 | - Reviewer note: the migration train requires WSP-01's `repo_bindings` first, yet WSP-01 is only sof | RES-086 |
| 48 | EVD-04 | - Reviewer note: check-to-attempt needs K2 observations, K3 kinds, K21 registration and K1 check key | RES-091 |
| 49 | API-01 | - Reviewer note: the `web/package.json` edits touch an upstream file that has no seam id, so OPS-01  | RES-092 |
| 50 | API-01 | - Reviewer note: the master K7 text omits EVD-03's repo command-pattern routes; this spec reserves t | RES-090 |
| 51 | API-02 | - Reviewer note: API-02 uses FND-02's K17 registration and K4 access adapter with no edge to FND-02. | RES-093 |
| 52 | API-02 | - Reviewer note: the outcome commit list needs WSP-06 to persist commit records; its scope names onl | RES-094 |
| 53 | EXT-01 | - Reviewer note: accept uses DUR-02 and adds K7 endpoints; DUR-02 is not a dependency and K7 is not  | RES-183 |
| 54 | EXT-01 | - Reviewer note: cost_growth needs API-02's spend (not in K3; DUR-06 purges it); test_edit_in_non_te | RES-183, RES-188 |
| 55 | EXT-02 | - Reviewer note: master RUL-01 includes "input-scope deny (internal_only)" and its spec owns `coral/ | RES-109 |
| 56 | EXT-02 | - Reviewer note: typed handoffs need K6, TLS-02's rejection path and ENG-03 changes; none is a depen | RES-184 |
| 57 | EXT-03 | - Excluded: repo-canonical editing, sync daemon, marketplace (deferred); repo import into drafts (WS | RES-180 |
| 58 | EXT-03 | - Proving test (`test_sharing.py`, host tests): exporting a version writes `.coral/<id>.yaml` (here  | RES-181 |
| 59 | EXT-03 | - Reviewer note: the master proving test says `.coral/<id>.yaml`; D§12 and WSP-01's import use `.cor | RES-181 |
| 60 | EXT-03 | - Reviewer note: the endpoints extend K7, which is not consumed; web git import and imported-templat | RES-180, RES-185 |
| 61 | EXT-04 | - Reviewer note: approver alerts need GTE-06's per-recipient producer (K19), and authority changes A | RES-186 |
| 62 | EXT-04 | - Reviewer note: `coral__` rows lack `session_id` (`omnigent/server/bundles.py:324-377`), so PUT age | RES-187 |
| 63 | EXT-04 | - Reviewer note: S46 strips the labels HRN-07's loss fallback queries, so HRN-07 must switch to a br | RES-119, RES-188 |
| 64 | EXT-05 | - Modify or extend upstream: none in the master; this design needs one fire hook (S, upstream-first; | RES-182 |
| 65 | EXT-05 | - Reviewer note: the master lists no seam, but this design needs the `fire.py` hook and TasksPage ed | RES-182, RES-188 |
| 66 | FND-01 | - Reviewer note: the master path `dev/lint/coral_boundary.py` breaks the `lint_<name>.py` convention | RES-013 |
| 67 | FND-01 | - Reviewer note: "every private through `_upstream.py`" conflicts with FND-03's private `omnigent.db | RES-020 |
| 68 | FND-01 | - Reviewer note: `server_plugins: [coral.server_plugin]` needs the root exemption. | RES-020 |
| 69 | FND-01 | - Reviewer note: the master assigns `custom_lint.RULES` registration to no feature; this spec gives  | RES-012 |
| 70 | FND-02 | - Reviewer note: `CORAL_DISABLE_HOST_ENTRY_POINTS` is a K17 addition for FND-04, implemented by TLS- | RES-021 |
| 71 | FND-02 | - Reviewer note (unowned): S32 wires only `cli.py`; the `create_app` calls at `deploy/databricks/src | RES-017 |
| 72 | FND-03 | - Reviewer note: S57 covers only Databricks; `deploy/docker/entrypoint.py:97` migrates Omnigent alon | RES-017 |
| 73 | FND-03 | - Reviewer note: an empty chain has no head (`utils.py:719-742`), so this spec adds `coral_0000_base | RES-014 |
| 74 | FND-03 | - Reviewer note: the master gives the manual migrate command no owner; confirm here or move to OPS-0 | RES-016 |
| 75 | FND-04 | - Reviewer note: the sample needs TLS-01's S7, S8 and S10 transport and S50 token, yet TLS-01 is und | RES-022 |
| 76 | FND-04 | - Reviewer note: `server_runner` passes no `--config` (`server_runner.py:144-167`), and `server_plug | RES-019 |
| 77 | FND-05 | - Reviewer note: S39c needs `.github/workflows/ci.yml:198`, because `--cov=omnigent` overrides the c | RES-023 |
| 78 | GTE-01 | - Reviewer note: `/approve` cannot answer multi-label gates: `get_elicitation` omits `requestedSchem | RES-077 |
| 79 | GTE-02 | - Reviewer note: this ends at week 7, before GTE-01 (9) and GTE-06 (11.5); cross-client ack is MSW-o | RES-078 |
| 80 | GTE-02 | - Reviewer note: a one-line spread is not achievable; about 7 anchors are the minimum. | RES-079 |
| 81 | GTE-02 | - Reviewer note: Extend has no backend owner; API-02 lists pause, resume, cancel, retry. | RES-080 |
| 82 | GTE-04 | - Reviewer note: Electron's Chromium has no push service, so `PushManager.subscribe` should fail (UN | RES-082 |
| 83 | GTE-04 | - Reviewer note: a real push proof needs a live push service, so CI covers only the push-service HTT | RES-082 |
| 84 | GTE-05 | - Reviewer note: `omnigent/server/elicitation_hooks.py` does not exist at HEAD. It is new upstream-p | RES-081 |
| 85 | GTE-06 | - Reviewer note: K19 lacks the overdue and reaction kinds that ENG-09 needs. Adding them is an addit | RES-028 |
| 86 | GTE-06 | - Reviewer note: the Extend action has no backend owner. `actions` lists it only once an endpoint ex | RES-080 |
| 87 | GTE-06 | - Reviewer note: no master feature emits gate-open or run-end `notify` effects; this spec takes them | RES-075 |
| 88 | HRN-05 | - Reviewer note: the S62 ledger row leaves the approval handler UNVERIFIED; it is `codex_elicitation | RES-125 |
| 89 | HRN-05 | - Reviewer note: §6.5 assigns the headless `codex_executor.py` S24 branch here despite the headless- | RES-126 |
| 90 | HRN-06 | - Reviewer note: `gate_failure_mode=deny` needs RUL-04's S14 output, yet the master lists no RUL-04  | RES-120 |
| 91 | HRN-07 | - Reviewer note: rotated sessions break K10's uuid5 session ids, so TLS-02 must accept submits from  | RES-122 |
| 92 | HRN-07 | - Reviewer note: a rotation audit entry needs a K3 kind (ENG-01); the supersession observer, K4 `on_ | RES-044, RES-061, RES-066, RES-122 |
| 93 | HRN-07 | - Reviewer note: EXT-04's S46 scope also claims "an explicit /clear policy"; OQ-46's follow-or-block | RES-119 |
| 94 | HRN-09 | - Reviewer note: the master gives HRN-09 no OQ-29 conditional, but M4 exit 4 treats it as "green or  | RES-123 |
| 95 | HRN-09 | - Reviewer note: §6.5 lists HRN-09 on `codex_executor.py` as S18 and S60, but S19's `thread/compact/ | RES-121 |
| 96 | OPS-01 | - Reviewer note: the fork point `2a9cbe2c2` is 4 commits past nightly^1 (`ee7a319f7`); a nightly^1 p | RES-164 |
| 97 | OPS-01 | - Reviewer note: §6.1 item 2 says upstream PRs go in `upstream.yaml`; OPS-01's master scope says `se | RES-163 |
| 98 | OPS-01 | - Reviewer note: `python-matrix.json` (S39d), `web/package.json` and lockfiles cannot carry anchors, | RES-092 |
| 99 | OPS-02 | - Reviewer note: two merges two weeks apart close the proof near week 6, after the week-4 finish. | RES-165 |
| 100 | OPS-02 | - Reviewer note: `coral-compat.yml` replaces editing `server-compat.yml`'s path filter, which no sea | RES-166 |
| 101 | OPS-03 | - Reviewer note: fixing a reachable writer edits an upstream file that S75 does not cover; it needs  | RES-162 |
| 102 | OPS-03 | - Reviewer note: no feature owns a default `server_plugins` for `coral server`; FND-02 owns only the | RES-018 |
| 103 | OPS-03 | - Reviewer note: if S75 enables a channel, `_CACHE_DIR` also needs the data-dir override (a generic, | RES-162 |
| 104 | OPS-03 | - Reviewer note: FND-01's tier rule limits the app tier to `coral.omni.protocols`. DUR-02 and this f | RES-020 |
| 105 | OPS-04 | - Modify or extend upstream: None planned; a plugin-config hook is open (reviewer note). | RES-167 |
| 106 | OPS-04 | - Reviewer note: `BenchEnvironment` hard-codes its server config (`dev/benchmarks/omnigent/environme | RES-167 |
| 107 | OPS-04 | - Reviewer note: add `dev/loadtest/coral/` to OPS-01's allowed roots as a new-files-only root. | RES-168 |
| 108 | OPS-05 | - Reviewer note: OPS-05 finishes in week 23 but co-owns IM-8 in week 25.5. Re-run the drill (one day | RES-169 |
| 109 | OPS-06 | - Reviewer note: weeks 4-6 precede GTE-01 (7-9) and PRF-01 (to 9.5); tracking runs to 13.5 and sign- | RES-170 |
| 110 | OPS-07 | - Reviewer note: a soak week has seven nightlies against a "9 of 10" threshold; run twice nightly or | RES-172 |
| 111 | OPS-07 | - Reviewer note: IM-3 and IM-4 are dated week 11.5, this feature's start, so step 1 starts about wee | RES-173 |
| 112 | OPS-07 | - Reviewer note: IM-4 needs the real-server `tests/e2e_ui/` lane; DoD rule 7 names only `tests/brows | RES-052 |
| 113 | OPS-07 | - Reviewer note: latency asserts on shared runners contradict `tests/budgets.py:21-36`, hence `night | RES-174 |
| 114 | OPS-08 | - Reviewer note: HRN-07 finishes at week 20, the day this lane starts, so there is no slack before M | RES-176 |
| 115 | OPS-09 | - Reviewer note: OQ-29 governs this lane but is missing from its `open_questions`. | RES-177 |
| 116 | OPS-09 | - Reviewer note: WEB-09 finishes at week 24.5, the day this lane starts. The `coral://` step has no  | RES-178 |
| 117 | PRF-01 | - Reviewer note: seeds use K17 (FND-02), missing from contracts_consumed; add it (FND-02 ends week 3 | RES-114 |
| 118 | PRF-01 | - Reviewer note: the allowlist needs RUL-01's handlers; goldens use a test registry until it lands. | RES-117 |
| 119 | PRF-02 | - Reviewer note: eng_harness §8.4 step 4 puts revision digests in the version content hash; decision | RES-116 |
| 120 | HRN-02 | - Reviewer note: the validity and sandbox checks read ENG-03 and WSP-01 (week 7); HRN-02 ends week 5 | RES-026 |
| 121 | HRN-02 | - Reviewer note: the token check reads K17 (FND-02), absent from contracts_consumed. | RES-114 |
| 122 | HRN-03 | - Reviewer note: SES-08 keys facts on `observed_at_ms`; the fallback needs a response-id key, an add | RES-066 |
| 123 | HRN-04 | - Reviewer note: HRN-04 adds a K18 field and a K2 resume time but lists only K9; add K18 and K2 to c | RES-115 |
| 124 | HRN-04 | - Reviewer note: master gives HRN-04 the mock-provider probe and HRN-08 all bench probes (S23); this | RES-112 |
| 125 | RUL-01 | - Reviewer note: S52 is four `builder.py` sites (three assembly sites plus the fast path), not one l | RES-101 |
| 126 | RUL-01 | - Reviewer note: upstream tests cannot import `coral`, so the proving test's Coral half lives in `te | RES-102 |
| 127 | RUL-01 | - Reviewer note: `SessionCapReached` and `ResumeRun.raise_session_cap_usd` amend ENG-01's K2; API-02 | RES-043 |
| 128 | RUL-01 | - Reviewer note: PRF-01's hygiene also lists the grants; PRF-01 writes them, RUL-01 checks them. | RES-108 |
| 129 | RUL-02 | - Reviewer note: no feature owns HTTP exposure of labels for WEB-13 and WEB-03. This spec adds thin  | RES-098 |
| 130 | RUL-02 | - Reviewer note: the sandbox backend comes from WSP-01's report, and WSP-01 is not a dependency. | RES-107 |
| 131 | RUL-03 | - Reviewer note: shell writes bypass a write-tool DENY, and `write_paths` (`datamodel.py:621`) is an | RES-100 |
| 132 | RUL-03 | - Reviewer note: the authoring keys belong to K1 (ENG-01), but K1 is not listed among this feature's | RES-103 |
| 133 | RUL-03 | - Reviewer note: `strictness_key` is added for ENG-09's V8 (the eng-b note). | RES-040 |
| 134 | RUL-04 | - Reviewer note: S14 also touches `runner/native/orchestration.py` and `codex_native/app_server.py`, | RES-104 |
| 135 | RUL-04 | - Reviewer note: S16 touches `helpers.py` (a hot file) and `policies/types.py`, which neither the ga | RES-104 |
| 136 | RUL-05 | - Reviewer note: eng_persistence T3/T4 put run budget and spend columns in coral_0001. Choose one ho | RES-105 |
| 137 | RUL-05 | - Reviewer note: step budget keys need K1, which this feature does not consume. | RES-103 |
| 138 | RUL-05 | - Reviewer note: utilization needs HRN-04's S24 data, which is not a dependency, so show tokens only | RES-106 |
| 139 | RUL-06 | - Reviewer note: the proving test depends on the claude-native K9 value. Pin `ask` in its fixture an | RES-111 |
| 140 | SES-01 | - Concurrent, coordinate with: none in feature_context.json; SES-02 implements K18 concurrently (Rev | RES-056 |
| 141 | SES-01 | - Reviewer note: SES-02 consumes K18 in the same weeks with no edge and no listed coordination; reco | RES-056 |
| 142 | SES-02 | - Reviewer note: §6.5 puts the archive-idle origin in `routes_events.py`; at HEAD it is `orchestrati | RES-055 |
| 143 | SES-02 | - Reviewer note: "relay turn end" is read as B1, per the master's "B1 (relay turn-end)"; the main re | RES-054 |
| 144 | SES-02 | - Reviewer note: K18 is consumed with no edge to SES-01. | RES-056 |
| 145 | SES-03 | - Reviewer note: TLS-01 adds the token to `HostHelloFrame.capabilities` but is not a dependency; unt | RES-057 |
| 146 | SES-03 | - Reviewer note: DUR-01 is soft, and §9 lists only ADR-05 as the bindings prerequisite, yet the sing | RES-053 |
| 147 | SES-04 | - Reviewer note: the Tier B proof needs TLS-02 and WSP-06 (weeks 7-9) plus FND-04, which is not a de | RES-058 |
| 148 | SES-04 | - Reviewer note: SES-04 consumes K5 and K21 and its migration needs `coral_0001` (§9), all from DUR- | RES-053 |
| 149 | SES-05 | - Reviewer note: there is no edge to API-02 (run start) or PRF-01 (the inert agent and step bundle), | RES-059 |
| 150 | SES-06 | - Reviewer note: DUR-05 and SES-08 finish after week 9.5, so the proving test closes at IM-3. | RES-063 |
| 151 | SES-06 | - Reviewer note: §7's conditional-owner line moves all of S27 to SES-06 if spike 16 fails (as §6.5 d | RES-067 |
| 152 | SES-06 | - Reviewer note: `hold_seen_at` and `restart_attempt_id` need ENG-01 (K2) and DUR-01 approval. | RES-042 |
| 153 | SES-07 | - Reviewer notes: the endpoints change K7, which this feature does not consume; `supersede` changes  | RES-038, RES-061 |
| 154 | SES-08 | - Reviewer note: §9 lists no table for edge facts. This spec assumes `coral_signals` plus K2 slot fi | RES-042 |
| 155 | SES-08 | - Reviewer note: the probe timer uses ENG-06's timer kinds; ENG-06 (finishes week 9.5) is not in SES | RES-065 |
| 156 | SES-08 | - Reviewer note: OPS-07's fault journey also lists 529/429/401, and DUR-04 and OPS-07 also list a pe | RES-002, RES-004 |
| 157 | SES-09 | - Reviewer note: forks copy `coral.*` labels, so RUL-01's provider must check the binding. | RES-110 |
| 158 | SES-09 | - Reviewer note: K2 already has the `user` and `drift` reasons (ENG-01). The cause slugs (`session_a | RES-041 |
| 159 | SES-09 | - Reviewer note: the master gives slot-start drift checks to both SES-09 and PRF-01 (spike 18). This | RES-060 |
| 160 | SES-09 | - Reviewer note: DUR-05 finishes at week 11.5, so the proving test closes at IM-3. | RES-063 |
| 161 | SES-10 | - Reviewer note: week 16 comes before WSP-03 (week 22.5), WSP-07 (week 20), RUL-03 (week 18) and IM- | RES-064 |
| 162 | SES-10 | - Reviewer note: no feature owns a dedicated batch-gate card. | RES-062 |
| 163 | SPK-01 | - Reviewer note: OQ-37 and OQ-47 shape K4 and K12 at IM-0 but only SES-01 lists them; SPK-01 should  | RES-007 |
| 164 | SPK-02 | - Reviewer note: the JSON window is weeks 0-1, but (e), (f), 14 and 15 run to week 2 (DEL-24); the s | RES-008 |
| 165 | SPK-03 | - Reviewer note: `tests/harness_bench/probes/` is upstream code (`ALL_PROBES`, `__init__.py:20`); la | RES-009 |
| 166 | SPK-04 | - Reviewer note: `coral/workspace/ops.py` needs FND-01's skeleton, also weeks 0-1 with no edge; keep | RES-010 |
| 167 | SPK-05 | - Reviewer note: DUR-04, SES-08 and OPS-07 use these budgets with no edge to SPK-05; add soft edges. | RES-003 |
| 168 | SPK-05 | - Reviewer note: proving test week 4 vs planned finish week 2; RUL-01 and HRN-02 start in week 3, so | RES-005 |
| 169 | SPK-05 | - Reviewer note: OQ-9 (invalid drafts) shapes DUR-02 and WEB-02 from week 5 with no record; add it h | RES-006 |
| 170 | SPK-05 | - Reviewer note: no feature's included list owns deciding OQ-29 or OQ-25 (due week 13.5); HRN-05's a | RES-001 |
| 171 | TLS-01 | - Reviewer note: S49 is "Up: Yes", but the master lists upstream PRs only for S10, S12, S50; folded  | RES-070 |
| 172 | TLS-01 | - Reviewer note: K17 is consumed without an FND-02 edge; step 5 merges after FND-02's PluginRegistra | RES-071 |
| 173 | TLS-02 | - Reviewer note: ENG-04's spec has slot `evaluating`, but neither K2's text nor DUR-01's coral_0001_ | RES-042 |
| 174 | TLS-03 | - Reviewer note: SES-06's ladder triggers the re-brief but is not a dependency. K10 (`coral.role`) a | RES-072 |
| 175 | TLS-04 | - Reviewer note: the conflict sub-state comes from WSP-03 (weeks 18-22.5), which starts after TLS-04 | RES-073 |
| 176 | TLS-05 | - Reviewer note: the proof depends on ENG-06's watchdog and on K2, neither of which is a dependency; | RES-074 |
| 177 | TLS-05 | - Reviewer note: the migration train sets "alerts" as this table's prerequisite, but GTE-06 (startin | RES-074 |
| 178 | WEB-01 | - Reviewer note: WEB-01 finishes in week 5, before DUR-02 and ENG-07, so the proof uses fixture trac | RES-052, RES-052 |
| 179 | WEB-01 | - Reviewer note: "too large" has no threshold. This spec proposes 200 nodes. | RES-145 |
| 180 | WEB-01 | - Reviewer note: master gives the failing-case expected-vs-actual view to WEB-01 and WEB-12. WEB-01  | RES-141 |
| 181 | WEB-02 | - Reviewer note: WEB-13 finishes in week 11, so the Runs tab shows a placeholder until then. | RES-146 |
| 182 | WEB-03 | - Reviewer note: for claude-sdk, `reconfigure` opens on `choose` (`pages/settings/HarnessFixDialog.t | RES-147 |
| 183 | WEB-03 | - Reviewer note: no master feature includes `GET /v1/coral/templates` or `POST .../templates/{id}:us | RES-140 |
| 184 | WEB-03 | - Reviewer note: msw is only a transitive lock entry (`pnpm-lock.yaml:7390`). API-01 must add it as  | RES-092 |
| 185 | WEB-04 | - Reviewer note: no axe tooling is locked at HEAD (`pnpm-lock.yaml`, `uv.lock`); no master feature n | RES-092 |
| 186 | WEB-04 | - Reviewer note: S35 stays unneeded only if steps are children of the anchor (ADR-05); otherwise it  | RES-146 |
| 187 | WEB-05 | - Reviewer note: master key_paths list `web/src/shell/SubagentTab.tsx`, but no seam covers it. This  | RES-142 |
| 188 | WEB-05 | - Reviewer note: under `omnigent.closed=true`, the anchor composer reads "This sub-agent session is  | RES-148 |
| 189 | WEB-05 | - Reviewer note: if SPK-02 probe (e) fails, SES-03 uses RUL-01's DENY instead of `omnigent.closed`;  | RES-149 |
| 190 | WEB-06 | - Reviewer note: K7 does not yet define labels on `:validate`. API-01 must add them additively, with | RES-150 |
| 191 | WEB-06 | - Reviewer note: until WEB-08, "on-box" means WEB-01's read-only preview. | RES-146 |
| 192 | WEB-07 | - Reviewer note: `AgentBundleInput` (`lib/agentBundle.ts:26-36`), the input of `buildAgentBundle` (` | RES-146 |
| 193 | WEB-07 | - Reviewer note: the master key path `web/src/pages/settings/` is read-only here, and no seam covers | RES-142 |
| 194 | WEB-08 | - Reviewer note: DUR-02's draft has no layout field. K7 must add `layout` additively. | RES-150 |
| 195 | WEB-08 | - Reviewer note: if ENG-09's group keys (weeks 18-22.5) are not stable by week 19, step 5 moves to W | RES-152 |
| 196 | WEB-09 | - Reviewer note: this feature calls K7 endpoints (`:validate`, blocks), but the master lists only K1 | RES-150 |
| 197 | WEB-10 | - Reviewer note: API-02's log endpoint needs `arrow_id` and `scope_key` filters (additive K7), or wh | RES-150 |
| 198 | WEB-10 | - Reviewer note: WEB-01 ships `canvas/overlay.ts`; step 1 should move it to `canvas/overlay/types.ts | RES-144 |
| 199 | WEB-11 | - Reviewer note: key_paths list `web/src/shell/monacoSetup.ts`, an upstream file with no seam. It is | RES-142 |
| 200 | WEB-11 | - Reviewer note: wf1 (G-70, current_state, eng_web) cites `monacoSetup.ts:12-17` for the worker. At  | RES-050 |
| 201 | WEB-11 | - Reviewer note: DUR-02 does not say `:validate` returns the compiled graph, which the preview needs | RES-150 |
| 202 | WEB-12 | - Reviewer note: no `/v1/coral/info` key covers this editor (DoD 6). It merges dark by staying unmou | RES-038 |
| 203 | WEB-12 | - Reviewer note: DUR-02 stores `CaseResult` but exposes no read path. K7 needs one additively, for e | RES-150 |
| 204 | WEB-13 | - Reviewer note: API-02's outcome lacks the repo path and worktree state; git refuses to switch to a | RES-150 |
| 205 | WEB-13 | - Reviewer note: PC-15 asks for a path summary, which K7 list rows lack. | RES-150 |
| 206 | WEB-13 | - Reviewer note: WEB-06 plans its own `LabelChip.tsx` in `guarantees/`, its key path. It should reus | RES-143 |
| 207 | WEB-13 | - Reviewer note: client-side events can double count across devices; server-side emission is safer ( | RES-153 |
| 208 | WSP-01 | - Reviewer note: the rev-parse fallback needs WSP-06's later runner shell, so `start_commit` waits f | RES-138 |
| 209 | WSP-01 | - Reviewer note: M1 exit item 7 has K13 v1 at IM-0 (week 3), but WSP-01 starts in week 5 and EVD-01  | RES-135 |
| 210 | WSP-01 | - Reviewer note: the bindings API needs K7 and the `create_run_worktree` executor needs K21; neither | RES-133, RES-136 |
| 211 | WSP-02 | - Reviewer note: `key_paths` omits `host_registry.py` and `host_tunnel.py`, which S40 edits. | RES-136 |
| 212 | WSP-02 | - Reviewer note: the proving test names only `test_frames.py`; the L2 and fallback asserts belong in | RES-139 |
| 213 | WSP-03 | - Reviewer note: this feature opens a K2 sub-state, uses K6's `coral_assign_task` and registers K21  | RES-133 |
| 214 | WSP-03 | - Reviewer note: SES-10 (weeks 14-16) soft-depends on WSP-03 and WSP-07, which start in week 18. | RES-064 |
| 215 | WSP-04 | - Reviewer note: `sandbox_runs` is not in FND-02's sub-feature map. | RES-038 |
| 216 | WSP-04 | - Reviewer note: checkpoints rely on WSP-07's push and consent. Recommend a soft edge WSP-04 -> WSP- | RES-137 |
| 217 | WSP-05 | - Proposed, pending a master amendment (Reviewer note): `WorkspaceReader.__init__` (`omnigent/worksp | RES-129 |
| 218 | WSP-05 | - Excluded: runner-path exit codes (EVD-02); the host channel (WSP-02); the host channel's exit-stat | RES-128 |
| 219 | WSP-05 | - Reviewer note: the master scopes S71 to `connect.py:6027-6034`, but the untracked-cache thread (`f | RES-129 |
| 220 | WSP-05 | - Reviewer note: the other plain `to_thread` handlers (stat, list_dir, skills, plugins, harness star | RES-128 |
| 221 | WSP-07 | - Reviewer note: push and fetch add K21 kinds with side effects, but this feature does not consume K | RES-133 |
