# Adversarial critique of master feature list v1

Lens: adversarial reviewer. Input: `decomposition/master_v1.md` and `master_v1.json` (85 features, K1-K20). Repository `omnigent-ai/omnigent` at `2a9cbe2c2`. Date 2026-11-11. Ids G-, S-, X-, D-, R-, OQ- refer to `investigation/gap_analysis.md`; DD§ to the deep dive. Code facts were re-opened at HEAD unless marked as cited from a specialist file.

Scratch scripts used for the schedule numbers: `wf2/adv/cp.py` and `wf2/adv/cp2.py` (same weights as the mandate: S=1, M=2, L=4.5).

## 0. Verdict

The master list is well covered and well evidenced. Every G-row and seam has an owner, the contract catalog is complete in shape, and the TLD flags carry code evidence. The problems are not coverage gaps in the G-table. They are in the dependency graph, in failure modes that sit between features, and in a few under-sized features on the M2 path.

Two issues are blockers:

1. **The walking skeleton is scheduled last, not first.** SES-05 merges the skeleton with the M2 acceptance lane and carries 12 hard dependencies. Its earliest start is week 16.5 of the 18.5-week M2 path. The plan's main integration strategy therefore cannot happen as written (ADV-01).
2. **Nothing closes a step session after its handoff is accepted.** claude-sdk buffers mid-turn user input and replays it as a continuation turn after the turn ends (`claude_sdk_executor.py:2323-2332`). The closed check runs only when a message is posted (`routes_events.py:1688-1698`). So an agent can keep editing the run worktree after its handoff was accepted and committed. Reviewers then read a different tree, and done-when "after the last change" silently over-claims. Only TLS-04 (M4) mentions the steering-vs-closing race, and only for `coral_message_agent` (ADV-02).

The majors fall into five groups:

- **Failure modes with no owner:**
  - restart ordering under the session-shell backend (ADV-03);
  - observation ingestion racing the submit scan (ADV-04);
  - failed-turn classification (ADV-05);
  - Coral upgrades with in-flight runs (ADV-06);
  - the turnless anchor's input and identity (ADV-08);
  - five smaller ones listed in ADV-24.
- **Hard dependencies that break contract-first or cut lines:**
  - the `coral` CLI used by DUR-02 belongs to OPS-03 (ADV-07);
  - TLS-03, SES-06, RUL-02 and WEB-03 have hard dependencies that should be soft (ADV-09).
- **Large features hiding XL:** WSP-01, SES-04 and HRN-03 (ADV-13, ADV-14, ADV-15).
- **Late discovery:** security review, SQLite contention and the scope-key design are all first exercised in PH4 or PH5 (ADV-18, ADV-19, ADV-20).
- **Test lanes that prove a different harness from the one shipped:** Tier B runs openai-agents, while M2 ships claude-sdk (ADV-10, ADV-11).

None of TLD-01..21 is unsound. Three need conditions written into the plan:

- **TLD-02:** pin the anchor variant (ADV-08).
- **TLD-10:** the session-shell backend needs a live session that has `os_env` and a connected runner (ADV-03).
- **TLD-21:** scope keys are not exercised by any reducer until PH4 (ADV-18).

## 1. Schedule facts that drive several issues

| Fact | Value | Source |
|---|---|---|
| SES-05 earliest start / finish | 16.5 / 18.5 weeks | `adv/cp2.py` over master hard deps |
| Separate skeleton feature (hard deps FND-04, SES-02, TLS-01, DUR-03, ENG-04) finish | 11.5 weeks | `adv/cp2.py` |
| EVD-02 finish today / with WSP-01 split | 14.0 / 11.5 weeks | `adv/cp2.py` |
| M3 critical path today / with RUL-02→EVD-01 and the other softenings in ADV-09 | 18.0 / 16.5 weeks | `adv/cp.py` |
| Weighted load by milestone | M1 44, **M2 86.5**, M3 21, M4 65.5, post-M4 24 | JSON |
| Idle workstreams | WS-ENGINE PH2 = 0; WS-WORKSPACE PH3 = 0; WS-PLATFORM PH3-PH4 = 0; WS-OPS PH2-PH4 = 0 | task load table |
| Overloaded | WS-INTEGRATION PH2 = 24 weighted weeks | task load table |

M2 carries about twice M4's load and four times M3's. M3 is thin. That supports moving non-mandated work out of M2 (ADV-16, ADV-25) and starting idle teams on PH4 work early (ADV-17, ADV-18).

## 2. Issues

### Blockers

**ADV-01 (blocker, split). The walking skeleton is last on the M2 path.**
Features: SES-05, SES-03, SES-04, TLS-02, GTE-01, ENG-04, WEB-04.

- **What the plan says.** Section 0 says "SES-05 is PH2's first integration target", built against the skeleton slices of ENG-04, SES-03, SES-04, TLS-02 and GTE-01.
- **What the graph does.** The JSON gives SES-05 hard dependencies on FND-04, SES-04, SES-06, TLS-02, TLS-03, GTE-01, DUR-05, EVD-02, WSP-01, PRF-01, HRN-02 and API-02. A hard dependency means it cannot start until each of those features is delivered. Its earliest start is week 16.5, and it closes the 18.5-week M2 path.
- **How it happened.** The product decomposition had the skeleton with hard dependencies only on skeleton slices (`decomp_slice.md:327`). Decision 15 merged it with the acceptance lane.
- **Effect.** The first real integration signal arrives about 7 weeks later than it could (11.5 vs 18.5).

Proposed change:

- Split into **SES-05 Walking skeleton** (M, PH2 start):
  - hard dependencies on FND-04, SES-02, TLS-01, DUR-03 and ENG-04;
  - soft dependencies on SES-03, SES-04, TLS-02, GTE-01 and API-02;
  - a named "skeleton slice" first PR in each of those five features;
  - exit: E2E-1 green by PH2 week 3.
- Add **SES-08 M2 acceptance lane** (M), which keeps today's 12 hard dependencies, E2E-2, the fault journey and the nightly.
- Add slice-level dependency targets to the JSON (for example `SES-03#skeleton`) so the script can schedule them.

**ADV-02 (blocker, missing). No owner for post-handoff continuation turns or the steering-vs-closing race at M2.**
Features: SES-04, TLS-02, ENG-04, ENG-06, WEB-05, WSP-01.

- **How it fails.**
  1. A user types into a claude-sdk step during its turn. M2 includes journey (h) steering through WEB-05, and the ordinary chat view allows it anyway.
  2. `enqueue_session_message` returns False, and the adapter replays the message as a continuation turn after the active turn ends (`claude_sdk_executor.py:2323-2332`).
  3. Meanwhile the agent calls `coral_submit_handoff`. The handoff is accepted, and WSP-01 commits.
  4. The buffered message then starts a new turn in the same session and the same run worktree.
- **Why nothing stops it.** The closed check fires only at post time (`routes_events.py:1688-1698`). No feature closes or fences a step session after acceptance. Only cancel runs `interrupt -> stop -> omnigent.closed` (ENG-06). The race is in adversarial §4.1, but master assigns it only to TLS-04 (M4) and only for `message_agent`.
- **Effect.** Reviewers review a tree that differs from the committed one, and evidence over-claims. This breaks the M2 promise "trust that review, tests and your approval actually happened".

Proposed change:

- **ENG-04 / K2:** add a slot `closing` state. The slot completes only when the session has no engine-known pending input.
- **SES-04** owns slot-close effects:
  - interrupt and stop the session, then label it `omnigent.closed` on accept;
  - read the pending-input buffer before declaring close;
  - if a continuation turn starts after accept, mark the slot `post_close_activity`, re-fingerprint, and pause the run as `paused(drift)`.
- **WEB-05:** show the "read after current turn" hint, and disable the composer once the slot is `evaluating` or `closing`.
- **Tests:** add a Tier B test that queues user input during a turn that ends in a handoff.

### Majors: failure modes with no owner

**ADV-03 (major, dependency). The restart ladder cannot run on the K13 session-shell backend as specified.**
Features: SES-06, WSP-01, SPK-04, EVD-02.

- **What the backend needs.** The session shell needs a live runner and a session with `os_env`:
  - the server POST path proxies without `ensure_runner_connected`; only PUT reconnects (`routes_resources.py:2511-2545`);
  - the runner handler calls `_require_os_env` and runs in `env.shell`, which is the agent's own sandboxed environment (`runner/app.py:8296-8346`).
- **Consequences:**
  - The orchestrator (no `os_env`, G-32) and the turnless anchor cannot host ops.
  - After runner loss, salvage through the old session means waking it. That can resume the held turn, the zombie hazard in adversarial §5.2.
  - Engine commits after accept must run before the step session is stopped, which conflicts with ADV-02's close-on-accept.
  - A linked worktree's gitdir is outside the sandbox (spike 8).
- **Contradiction in the plan.** SES-06's proof says "Resume creates a new generation after a salvage ref", but the order of steps is not defined.

Proposed change:

- **K13** states the backend rule: ops run through a designated op-host session that has `os_env`, a reconnected runner and a writable gitdir.
- **SES-06** fixes the ladder:
  1. fence and stop the old generation;
  2. create the new generation without briefing it;
  3. reconnect;
  4. salvage, then reset, through the new session's shell;
  5. brief.
- **WSP-01** commits through the step session inside the `closing` state from ADV-02, before stop.
- **SPK-04** tests with the sandbox on, in a linked worktree. If spike 8 fails, the planned response is to pull WSP-02's commit, reset and salvage ops into PH2 (see ADV-17).

**ADV-04 (major, risk). Observations can arrive after the `submit_handoff` scan.**
Features: EVD-02, TLS-02, HRN-03.

- TLS-02 does a bounded synchronous scan of `coral_command_observations`.
- EVD-02 lands observations through two transports:
  - (a) the server TOOL_RESULT hook (`orchestration.py:13239-13258`);
  - (b) an `external_workspace_observations` event with an outbox reporter.
- Transport (b) and any off-thread enqueue in (a) are asynchronous. A test run followed at once by `submit_handoff` can be scanned before its observation commits. The result is a false "tests not run" rejection, which counts toward the rejected-call pause.
- Native observations (HRN-03, PostToolUse hints over (b)) make this worse.

Proposed change:

- **K11** defines a per-session observation watermark: the last tool-result item seq that has been ingested.
- **TLS-02** waits, within the spike-7 bound, until the watermark reaches the submit's preceding item seq. Otherwise it answers "evaluation in progress", not "missing".
- **EVD-02** writes claude-sdk observations synchronously in the TOOL_RESULT hook. Transport (b) moves to HRN-03 (see ADV-25).

**ADV-05 (major, missing). Failed-turn classification has no owner at M2.**
Features: SES-04, ENG-06, DUR-05, HRN-04.

- DD§6.7 defines `infra.transient` (API 529, transient upstream), `plan.usage_limit`, `plan.spend_cap` (429 without retry-after) and `auth`. Infra retries never use attempts.
- K2 carries the taxonomy, but no feature maps a failed claude-sdk turn to a class. HRN-04 adds S24 reset times only at M3, and G-57 notes that the MVP "falls back to error text, which is fragile".
- API-key runs with two reviewers plus an implementer will see 429 and 529 errors. Unclassified, a failed turn is treated as agent failure. It then uses attempts or takes the failure path.

Proposed change:

- **SES-04** owns a failed-turn classifier at M2, using `failure_origin`, `ExecutorError` and error text:
  - `infra.transient`: backoff, then `paused(infra)`;
  - `auth`: `paused(auth)` with an alert;
  - `plan.*`: `paused(plan_limit)` without a reset time, polled with backoff.
- **HRN-04** replaces the text matching with S24 at M3.
- **Tests:** a Tier B case with the mock LLM returning 529, then 429, then 401.

**ADV-06 (major, missing). Nothing owns Coral upgrades with in-flight runs.**
Features: ENG-01, DUR-01, DUR-05, OPS-02, ENG-10.

- Runs can sit paused for days at gates or plan limits, and the fork merges upstream daily.
- K1 pins the IR snapshot and the persistence design has a `compiler_version` column (`eng_persistence.md:455`). No contract says what happens when the reducer, state shape or IR format changes under a pinned run.
- `fold(log) == state` across builds is undefined, and the plan has no "engine upgrade" pause reason.

Proposed change:

- **K1, K2 and K3** each carry a version (`ir_version`, `state_version`, `log_version`), with the rule that build N reads state from N-1.
- **DUR-01** stores `engine_version` per run.
- **DUR-05**, at startup, pauses any run it cannot read with `paused(engine_upgrade)` and offers cancel. At M4, ENG-10 adds restart-from-node.
- **OPS-02** adds an upgrade lane: start a run on build N, restart the server on N+1, resume to the end.

**ADV-07 (major, dependency). The M1 CLI depends on a later milestone.**
Features: DUR-02, OPS-03, FND-01.

- The M1 proving journey uses `coral workflow upload`, delivered by DUR-02 in `coral/cli.py`.
- The `coral` console script is OPS-03's. It is at M2, with "cut line: may slip to PH5". FND-01 lists "Out: console script (OPS-03)".
- `pyproject.toml` has only `omnigent` and `omni` entry points today.
- This is a hidden hard dependency pointing to a later milestone (rule 5). Data-dir isolation in OPS-03 also changes which config the CLI and the server read.

Proposed change:

- **FND-01** adds the bare `coral = "coral.cli:main"` entry point and an empty click group in M1.
- **OPS-03** keeps data-dir isolation, update identity and coexistence.
- **DUR-02** states that the CLI talks to the server URL from the active config, with a test for both default and `~/.coral` homes.

**ADV-08 (major, risk; TLD-02 condition). The anchor-vs-orchestrator choice is open, and the turnless run session has no owner.**
Features: SPK-02, SES-03, GTE-01, SES-06, SES-07, WEB-05, WEB-10.

- **What is undecided.** TLD-02 and X-1 allow the stable run session to be either an anchor or the orchestrator. SPK-02 probes both: (b) a turnless run session, and (d) stopping the orchestrator.
- **Which features assume which variant:**
  - GTE-01 re-publishes "on run-session replacement", which implies the run session can be replaced;
  - SES-07 refreshes the orchestrator by slot restart;
  - WEB-05 and WEB-10 show "current orchestrator" and "stitched segments".
- **Why the orchestrator variant fails.** If the orchestrator is the run session, its refresh or restart orphans every child (`parent_conversation_id` is fixed), and gates move.
- **Why the anchor variant still needs work:**
  - The anchor needs an agent and an input stance. `architect.md:447` says "possible Extend if the anchor needs a no-turn agent", and no seam is listed for it.
  - The user can click the anchor in the sidebar and type.
  - Delete or archive of the anchor (cascade to children?) has no defined outcome.

Proposed change:

- **ADR-05** must choose the anchor: a turnless root that is never replaced, with the orchestrator as an own-runner child that can be replaced.
- **SES-03** owns a hidden `coral__anchor` agent (no tools, no `os_env`) and an input stance:
  - if probe (e) shows elicitations still resolve on a closed session, use `omnigent.closed`;
  - otherwise use an input DENY policy.
- **SES-06** defines anchor archive and delete outcomes.
- **SPK-02 probe (e)** runs with that stance.
- Record any new seam in the ledger.

### Majors: the dependency graph

**ADV-09 (major, dependency). Hard dependencies that should be soft through contracts.**
Features: TLS-03, SES-06, RUL-02, WEB-03.

Rule 5 asks for soft dependencies through contracts where possible. Four hard dependencies break that:

- **TLS-03 → TLS-02 and ENG-05.** `choose_arrow` and `ask_user` build reducer commands against K2 and K6. Loop semantics live inside the reducer.
- **SES-06 → SES-04.** The restart ladder needs SES-03, DUR-05 and FakeOmni, not the turn-end rule.
- **RUL-02 → EVD-02.** Labels need K11 (EVD-01), not claude-sdk capture. This dependency alone puts EVD-02 on the M3 critical path.
- **WEB-03 → WEB-02.** WEB-02 says its YAML editor is "the last PR series and the M2 cut line". Using the cut line would block WEB-03, a Critical M2 feature that needs only the desk shell.

Proposed change:

- Make TLS-03→TLS-02 and TLS-03→ENG-05 soft.
- Make SES-06→SES-04 soft.
- Change RUL-02's hard dependency from EVD-02 to EVD-01; keep EVD-02 soft.
- Point WEB-03 at a `WEB-02#desk` slice (tabs, library, upload). The editor becomes a soft dependency.

With the first three, M3's path drops from 18.0 to 16.5 weeks.

**ADV-10 (major, evidence). Tier B proves openai-agents, while M2 ships claude-sdk.**
Features: FND-04, SES-05, SES-04, PRF-01, HRN-01, SPK-03.

- E2E-1 and E2E-2 use openai-agents bundles against the mock LLM (`eng_testing.md:18, 136, 324`).
- The M2 code paths are claude-sdk-specific:
  - the turn-end rule is "claude-sdk first" (SES-04);
  - bundles are claude-sdk (PRF-01);
  - reviewers are read-only through the claude-sdk sandbox;
  - mid-turn buffering is claude-sdk behaviour (F33);
  - the S13 guard applies to claude-sdk;
  - V10 preflight checks the configured harnesses.
- So Tier B needs an openai-agents turn-end rule, a capability row and bundle support, and no feature owns them.
- The only claude-sdk proof is then the credentialed nightly, which needs OQ-51 (see ADV-21).
- `mock_llm_server` already speaks Anthropic Messages (`eng_testing.md:18`), so spike 4 decides whether claude-sdk can run in Tier B.

Proposed change:

- Make spike 4 the first week-1 probe.
- If it passes, E2E-1 and E2E-2 run claude-sdk against the mock, and openai-agents becomes unneeded.
- If it fails, add an explicit "test-only openai-agents mode" to SES-04 (turn-end rule), HRN-01 (K9 row) and PRF-01 (bundle), and list which M2 exit criteria that lane cannot prove.

**ADV-11 (major, contract). FakeOmni can diverge from real Omnigent.**
Features: SES-01, SES-03, SES-04, DUR-05, GTE-01, TLS-02.

- DUR-05, SES-04, TLS-02 and GTE-01 build against FakeOmni from PH0.
- SES-03's proof covers duplicate create and a row diff against HTTP. It does not run the K4 conformance suite against the real facade.
- The riskiest semantics: an exact `stable_id` retry is persisted as deduplicated and **still forwarded** (`orchestration.py:7295-7310`). A fake that treats `send(stable_id)` as idempotent would let every consumer pass while duplicating briefs in production.

Proposed change:

- The K4 conformance suite is parameterized over FakeOmni and real `coral.omni` (Tier A and Tier B).
- SES-03 is not done until both pass.
- K4 documents "send is not idempotent; callers read before resend".
- Add the suite to the OPS-02 rehearsal as L3.

**ADV-12 (major, scope). S1b is optional but scheduled as required M2 work.**
Features: SES-02, SES-04, OPS-01.

- S1b adds an origin slug at the 18 `_publish_status` call sites in four files:
  - 2 in `helpers.py` (52 commits in 30 days);
  - 11 in `orchestration.py` (73);
  - 4 in `routes_events.py` (39);
  - 1 in `startup_inputs.py`.
- `eng_sessions.md:273` says "the phase-2 reconciler works without S1b; S1b only reduces false wake-ups", and the ledger marks it "2 (optional)" (`:711`).
- Eighteen anchors in the hottest files is the largest single source of merge conflicts in the M2 seam set. It is not one call into a registry.

Proposed change:

- Remove S1b from SES-02's M2 scope.
- Tag only the origins SES-04 needs: B1 relay turn-end, B2 status probe and archive idle. Every other site defaults to `origin="unknown"`.
- Move full S1b to an "upstream-first" item in OPS-05: land it upstream, then merge it in.

### Majors: large features hiding XL

**ADV-13 (major, split). WSP-01 is an L hiding an XL.**
Features: WSP-01, EVD-02, EVD-03.

WSP-01 holds a lot of work:

- the S71 bug fix;
- repo bindings and their API;
- three S72 host-side changes (`head_commit`, detached+commit mode, `worktree_parent`) in a 58-commit-per-month file;
- request-free create and adopt;
- engine commits with trailers;
- salvage refs;
- reset and clean;
- the K13 session-shell backend;
- retention and a disk cap;
- workflow import;
- the S73 invariant test;
- the SPK-04 contingency (+3 weeks).

It sits on the M3 and M4 critical paths, and EVD-02 waits for all of it.

Proposed change:

- **WSP-01a** (M, may start PH1): S71, S72 `head_commit` only, bindings, create and adopt, import, the S73 invariant.
- **WSP-01b** (M-L, PH2): commit, salvage and reset through K13 (ordering from ADV-03), retention and disk cap.
- Move S72's detached mode to EVD-04, its only consumer.
- EVD-02 and EVD-03 depend only on WSP-01a. EVD-02 then finishes at 11.5 weeks instead of 14.

**ADV-14 (major, split). SES-04 is an L hiding an XL.**
Features: SES-04, TLS-03, HRN-03, SES-05.

- SES-04 already holds:
  - six message kinds;
  - read-before-resend;
  - the ManagedStartupInputs fallback;
  - the status observer and TurnFact enqueue;
  - the per-mode turn-end rule;
  - nudge rules;
  - archive-edge filtering;
  - the cancel chain.
- ADV-02 and ADV-05 add slot-close effects and failed-turn classification.
- It sits on the 18.5-week M2 critical path.

Proposed change:

- **SES-04a Engine dispatch** (M): `_post_event_impl` sends, `stable_id`, read-before-resend, ManagedStartupInputs, interrupt and stop, the cancel chain, slot-close effects.
- **SES-04b Turn-end and outcome** (L): observer, TurnFacts, the per-mode rule, failed-turn classifier, nudge eligibility.
- TLS-03 and the skeleton need only SES-04a. HRN-03 and HRN-05 extend SES-04b.

**ADV-15 (major, split). HRN-03 (claude-native) is an L hiding an XL.**
Features: HRN-03, RUL-04, SES-06.

- **What HRN-03 holds:**
  - enable S12, S9 and S11 for `coral_*` tools;
  - S3 launch args;
  - Stop-hook turn end;
  - S45 rotation following for `/clear`, with re-attached policies and labels (OQ-46);
  - S64 egress;
  - PostToolUse observations;
  - E2E-3.
- **What it misses:**
  - **Turn end is only on the edge.** A crash between the Stop-hook edge and SES-04's "off the hot path" enqueue loses `turn_completed`. X-3 says a level-triggered reconcile cannot recover it.
  - **Waiting panes get reaped.** The pane reaper spares panes in an active turn but reaps idle ones after 60 minutes (`pane_reaper.py:85, 146-157`). A native step waiting on an orchestrator decision or a gate loses its pane, and resuming a reaped TUI conversation is UNVERIFIED.
  - **Spike 6.** Native ASK re-publish after restart.
- `bridge.py` is the most-churned file in the native path (adversarial S-1).

Proposed change:

- **HRN-03a claude-native step launch** (L): channels, turn end with a transcript or pending-input fallback for lost edges, observations, pane-reaper handling and wake-before-brief, spike 6 applied, E2E-3.
- **HRN-03b Native rotation following** (M): S45, re-attaching policies, labels and bundle, the `/clear` policy (OQ-46).
- The M3 exit needs both.

### Majors: scope, sequencing and staffing

**ADV-16 (major, scope). HRN-01 at M2 is an unrecorded milestone move.**
Features: HRN-01, SES-04, RUL-02, WEB-07.

- The mandate puts "the capability registry and per-mode promise labels" in M3. Master puts HRN-01 at M2.
- The decisions log records three moves (37-39), and this is not one of them.
- M2 needs only K9 and claude-sdk turn-end values, for SES-04. The other parts are for M3 consumers:
  - the ten G-44 fields for four modes;
  - S59 `capabilities_by_spelling`;
  - bench probes, feature-map rows and the credentialed `coral-bench.yml` (OQ-51).

Proposed change:

- **HRN-01a** (S, PH1, M2): K9 types, CapabilityMatrix, claude-sdk values, guard tests.
- **HRN-01b** (M, PH2-PH3, M3): the other modes, S59, the bench and S78.
- Record it in the decisions log. This takes about 2 weighted weeks off M2.

**ADV-17 (major, reorder). Start WSP-02's frames and dispatcher in PH3.**
Features: WSP-02, WSP-01, SPK-04, EVD-04, WSP-03.

- WS-WORKSPACE has zero load in PH3, then 13.5 weighted weeks in PH4 on the 23-week M4 critical path.
- WSP-02's dependency on WSP-01 is needed only for the adapter swap at the end. The frames, capability token, reaper-guarded dispatcher, job journal and version-skew fallback are independent.
- Starting early also covers SPK-04's contingency (sandboxed commit or reset fails). That contingency needs exactly these host ops, and the plan has no team ready for it.

Proposed change:

- Split **WSP-02a Host op channel** (frames, K20, dispatcher, S40/S40b, probe/head/fingerprint L2) into PH3, with WSP-01 as a soft dependency.
- **WSP-02b Backend swap** (commit, reset and salvage moved over, evaluator parity) stays in PH4.
- If spike 8 fails, WSP-02a's commit, reset and salvage ops move into PH2 as the planned response.

**ADV-18 (major, reorder; TLD-21 condition). Exercise scope keys before M2 data exists.**
Features: ENG-08, ENG-01, DUR-01, ENG-05.

- TLD-21 threads `item_path` and `iteration_path` through every table from PH1. But no reducer uses non-trivial item paths until ENG-08 in PH4.
- A mistake in the scope-key shape then surfaces after M2 has real runs, which means a migration plus a rewrite. That is the retrofit adversarial Q1 warned against.
- WS-ENGINE has zero load in PH2.

Proposed change:

- Split ENG-08:
  - **ENG-08a Repeat and parallel semantics** (L, PH2-PH3, pure): reducer, validator and Simulate, with golden traces at `item_path` depth 2. It is written against the K2 scope keys before M2 freezes.
  - **ENG-08b** (M, PH4): region-cancel effects, E2E-5, the PR-review template and integration.

**ADV-19 (major, reorder). Security review only at PH5, with unbounded "fixes".**
Features: OPS-04, GTE-01, RUL-02, HRN-03, TLS-01.

- OPS-04 (L) does the threat review "with fixes" in PH5. Several findings would change M2 and M3 designs:
  - S49 provenance and OQ-43;
  - gate authority at LEVEL_EDIT;
  - spike 15 runner-local impersonation;
  - bundle secrets.
- The native bridge writes bearer auth headers into the agent-readable `bridge_dir` (`runner/native/orchestration.py:9284-9290, 9826-9836`). So at M3 a claude-native step can post approvals and answer its own gate (D25). GTE-01 only "labels" the risk, and RUL-02 has no gate-integrity label.
- WS-OPS has zero load in PH2-PH4.

Proposed change:

- **OPS-04a Threat model and M2/M3 review** (M, PH2-PH3):
  - deadline: M2 exit for M2 surfaces;
  - deadline: before HRN-03 merges for native.
- **OPS-04b** keeps the M4 closure.
- **RUL-02** computes a gate-integrity label per mode. Anything other than claude-sdk is not Enforced.
- **SPK-01** decides whether runs with gates may use claude-native steps at M3.

**ADV-20 (major, risk). SQLite contention is first measured in PH5.**
Features: OPS-04, DUR-03, DUR-04, SES-04.

- SQLite is committed (TLD-08) and has a single writer (adversarial §2.5).
- M2 adds several write sources:
  - SES-04 enqueues a TurnFact for every bound status edge;
  - DUR-04 runs workers and timer scans;
  - DUR-03 runs CAS retries;
  - EVD-02 writes command observations;
  - Omnigent's own writes continue.
- Adversarial S-13 warned specifically about SQLite writes on the status hot path. If contention appears in PH5, the queue layout and the observer have to be redesigned after M2 ships.

Proposed change:

- Add a **perf smoke** to DUR-04 and SES-04's definition of done at M2:
  - N concurrent MVP runs (N from OQ-1, with a default of 5) on SQLite with the mock LLM;
  - record `SQLITE_BUSY` counts, p95 transition latency and edge-to-TurnFact lag;
  - gate on budgets agreed in SPK-01.
- OPS-04 keeps the full load test.

**ADV-21 (major, dependency). External decisions gate milestone exits with no fallback.**
Features: SPK-01, SES-05, HRN-01, HRN-03, HRN-05, HRN-06.

- **OQ-51** (live-bench budget and credentials) gates M2 exit 1, the credentialed nightly. It is not in SPK-01's list.
- **OQ-28** (vendor written answer) gates M3 journey step 3 (claude-native on a subscription) and M3 exit 7.
- **OQ-29** (OpenAI terms) gates M4 journey step 2 (codex-native reviewers).
- None of these is in the team's control, and none has a deadline or a fallback.

Proposed change:

- Add OQ-51 to SPK-01 with a PH1-end deadline.
- Give OQ-28 a PH2-end deadline, with a fallback: if refused, M3 ships claude-native on API key or behind a flag, and journey step 3 is rewritten.
- Give OQ-29 a PH4-start deadline, with a fallback of two claude-sdk reviewers in the M4 journey.
- Mark each affected exit criterion as conditional.

**ADV-22 (major, missing). The PR-review showcase has hidden dependencies.**
Features: ENG-08, WSP-02, WSP-03, EVD-04.

- D§5.6 has per-PR Review, then Fix (an implementer), then a gate that approves the merge. The M4 journey runs this with "concurrency 2".
- What that needs:
  - **per-item worktrees** based on each PR's head. WSP-03 has per-writer worktrees, not per-item ones, so two concurrent Fix steps would share the run worktree;
  - **`git fetch` of PR refs and a push or merge.** WSP-02 lists "Out: fetch and push";
  - **GitHub credentials and egress** in reviewer and finder sandboxes (adversarial §6.4);
  - **an owner for the merge action** (OQ-18).
- No feature owns any of this.

Proposed change:

- **WSP-03** keys worktrees by `(run, node, item_path, agent)`, with a per-item base ref.
- **WSP-02** adds fetch-ref and push ops behind consent (OQ-39).
- **ENG-08b** owns the template's credential and egress profile (via RUL-03 templates).
- **SPK-01** settles OQ-18 for the PR case.

**ADV-23 (major, contract). Two contracts that consumers need are missing.**
Features: API-01, API-02, DUR-03, WEB-04, WEB-01, ENG-03, RUL-02, ENG-07.

- **K8 omits the run projection and per-entry row patches.**
  - `eng_web.md:643` says "the server sends row patches with each entry; the client never re-implements the reducer".
  - Master's K8 says only "snapshot then seq-numbered entry events".
  - If DUR-03 does not store the state delta with each log entry, API-02 cannot stream patches, and WEB-04 ends up reimplementing the fold in TypeScript.
- **K1 omits the validator's derived analysis.** This is the regions, join types, loop table, decision label sets and checked parts. It is consumed by:
  - the WEB-01 scenario editor ("from derived info");
  - the WEB-04 overlay;
  - RUL-02 labels per checked part;
  - ENG-07.

Proposed change:

- **K8** defines a `RunView` projection schema plus a patch per entry.
- **DUR-03** persists the patch with the log row.
- **K1** gains an `Analysis` section produced by ENG-03, with a JSON Schema golden.

**ADV-24 (major, missing). Add a failure-mode ownership table and assign what is left.**
Features: DUR-05, SES-06, TLS-03, SES-07, WSP-01, SES-03.

The risk decomposition had this table (`decomp_risk.md:56-74`). Master dropped it. Beyond ADV-02..06 and ADV-08, these modes have no owner:

| Failure mode | Proposed owner and fix |
|---|---|
| Orchestrator restarted after runner loss loses decision context and the user's chat | TLS-03: re-brief with the pending decision request, a short run summary and prior decisions |
| A single turn longer than the runner idle watchdog (spike 16) | Conditional: if spike 16 fails, move the S27 retest from SES-07 (M4) to SES-06 (M2) |
| Native `turn_completed` lost between the edge and the enqueue | HRN-03a fallback (ADV-15) |
| Old host daemon without the S72 `head_commit` | WSP-01a: feature-detect via `HostHelloFrame` capabilities and fall back to `git rev-parse` through the session shell |
| Wake before brief after a long gate (all reapers fire after 1 h, adversarial §5.3) | SES-04a: always `ensure_runner_connected` before sending |

Proposed change: add the table to section 6 of the master, covering the eight modes in the task lens plus the rows above, each with an owner and a proving test.

**ADV-25 (major, scope). Ranked M2 cut list beyond the existing cut lines.**
Features: SES-02, HRN-01, EVD-02, EVD-03, WEB-01, WEB-05, OPS-03, TLS-03, WEB-02.

The mandate's M2 list does not include Simulate UI, CI-file detection, native observation transport, the bench, or a steering composer. In cut order:

1. S1b origin slugs (ADV-12).
2. HRN-01 bench, S59 and the other modes (ADV-16).
3. EVD-02 transport (b), the outbox reporter, moved to HRN-03a.
4. EVD-03 parsers for CI files and pre-commit. Keep `package.json`, `pyproject.toml`, `justfile` and `Makefile`.
5. WEB-01's Simulate scenario editor and saved-test badges, moved to M3. Keep the read-only diagram, the overlay API and the API traces.
6. WEB-05's steering composer, if ADV-02 is not solved in time. Fall back to a read-only pane plus "open session".
7. OPS-03 (existing cut line).
8. `ask_user` (existing cut line).
9. The YAML editor (existing cut line, after the ADV-09 fix).

Proposed change: add this ordered list to section 6, with the weighted weeks each cut saves.

### Minors

**ADV-26 (minor, reorder). Tables land before their owners design them.**
Features: DUR-01, DUR-04, GTE-02, TLS-03, EVD-03.

- DUR-01's `coral_0001` creates the queue table, but DUR-04 says "physical layout chosen here".
- `coral_0002` pre-bakes alerts, questions, command patterns and observations in PH1. Their contracts or owners arrive in PH2 (K19 in GTE-02, TLS-03, EVD-03, EVD-02).
- GTE-02 is a WS-WEB feature, yet it owns the alert store, the inbox API and the alert producers.

Proposed change:

- DUR-01 ships K5, `coral_0001` without the queue, and the train.
- DUR-04 owns the queue migration.
- Each PH2 owner adds its table through the train.
- Move K19 and the alerts backend (`coral/api/inbox.py`, producers) into a WS-PLATFORM slice of GTE-02 (or into DUR-05). WS-WEB keeps the card, the sidebar count and S36.

**ADV-27 (minor, dependency). Contracts freeze before their decision inputs arrive.**
Features: ENG-01, EVD-01, SPK-01, SPK-04, WSP-01.

- ENG-01 freezes K1 and K2 with only a soft dependency on SPK-01, yet K1/K2 encode OQ-3 (gate outcomes), OQ-12 (blocked routing) and OQ-19 (the D6 join rule).
- EVD-01 freezes K11's fingerprint record before SPK-04 picks the L1 algorithm.
- K13 is produced by a spike, which leaves throwaway ownership for an M4 interface.

Proposed change:

- Make the engine-semantics subset of SPK-01 (OQ-3, 12, 19) a hard dependency for ENG-01's freeze. Both are PH0, so this is allowed.
- Make SPK-04 a hard dependency for EVD-01's freeze.
- Make K13 the first PR of WSP-01a, informed by SPK-04.

**ADV-28 (minor, sizing). Spike time boxes do not match their content.**
Features: SPK-02, SPK-03, HRN-03, HRN-05.

- SPK-03 is described as "week 1" plus "week 2" (11 spikes) but sized S, which is at most 1 engineer-week.
- SPK-02 has 4 days for 8 probes, including (f), "the engine can relaunch own-runner children", which needs a prototype relauncher.
- The native and Codex probes (5, 6, 12, 13) will be stale by PH3, given the churn in the native path.

Proposed change:

- Resize SPK-03 to M, or move its week 2 into a PH2 spike, **SPK-05**, run just before HRN-03 and HRN-05 start.
- Give SPK-02 two engineers for one week, or move probe (f) into SES-06's first PR.

**ADV-29 (minor, dependency). Dependencies that the graph does not model.**
Features: OPS-01, TLS-01, GTE-01, EVD-02, RUL-04, HRN-02, RUL-01, SES-07.

- **The serial seam train adds orderings that are in no dependency list:**
  - `orchestration.py`: SES-02 → TLS-01 → GTE-01 → EVD-02;
  - `tool_dispatch.py`: TLS-01 → EVD-02;
  - native files: TLS-01 → EVD-02 → RUL-04 → HRN-03.
- **Conditional dependencies are missing:**
  - spike 1 fails → RUL-01's guard needs HRN-02's S21;
  - spike 16 fails → S27 is needed at M2;
  - spike 8 fails → host ops move into PH2.

Proposed change:

- Make the train a landing-order guideline, enforced only by fork-guard anchors and rebase-on-conflict, not a gate. One-line anchors at different lines merge cleanly.
- Add the three conditional dependencies to the JSON with their trigger spike.

**ADV-30 (minor, other). Exit-criteria consistency and duplicate scope.**
Features: SES-05, HRN-01, SES-02, HRN-06, WEB-02, WEB-04, TLS-03, PRF-01, API-02, HRN-02.

Exit criteria:

- **M1 exit 7** needs K9 and K18, which come from M2-milestone features (HRN-01, SES-02).
- **M2 exit 1** asks a credentialed nightly to pass a path-specific journey ("pass 2 of 3") five runs in a row. A real model cannot be steered onto that path.
- **M4 exit 4** requires headless codex (HRN-06), which is also the "first cut".

Duplicate scope:

- the runs list is in both WEB-02 (Runs tab) and WEB-04;
- the orchestrator seed is in both TLS-03 and PRF-01;
- preflight is in both API-02 and HRN-02 (`coral/harness/preflight.py`).

Proposed change:

- Move the K9 and K18 first PRs explicitly into the M1 list.
- Rewrite M2 exit 1:
  - the nightly asserts invariants and reaching a terminal state;
  - path coverage comes from Tier B, or from a scripted mock reviewer plus a real claude-sdk implementer.
- Mark HRN-06 as conditional in M4 exit 4.
- Give each duplicate one owner: the runs list to WEB-04, seeds to PRF-01, and the preflight engine to HRN-02, with the API-02 endpoint calling it.

## 3. TLD soundness

| TLD | Verdict | Condition to add |
|---|---|---|
| TLD-02 | Sound | ADR-05 pins the anchor variant, its hidden agent and its input stance (ADV-08) |
| TLD-10 | Sound with master's flag | The session-shell backend needs a reconnected session that has `os_env` and a writable gitdir; restart order is defined (ADV-03); the submit scan waits for the observation watermark (ADV-04) |
| TLD-21 | Sound | A repeat/parallel reducer exercises scope keys before M2 (ADV-18) |
| TLD-09 | Sound | Gate integrity is labelled per mode; native steps can self-approve (ADV-19) |
| TLD-07 | Sound | OQ-28 deadline and fallback for the M3 journey (ADV-21) |
| TLD-08 | Sound | SQLite contention smoke at M2 (ADV-20) |
| Others | Sound as planned | — |

## 4. Strengths to keep

- Complete G-row and seam ownership, with a script-checked index and reasons for every unplanned seam (S17, S33, S35, S44, S47, S48, S55, S65, S73).
- The contract catalog names producer, phase, consumers and a contract test for each of K1-K20, and reserves the K12 guardrails slot before K15 exists.
- TLD flags backed by code: S71 guards only host subprocesses; relaunch covers roots only (`app.py:4273`); S73 holds only without git options.
- Milestone moves come with reasons: S13 and reviewer `write_paths` to M2, and the cost backstop to M2 with V12 and the activation cap.
- Spikes are time-boxed with costed fallbacks (topology +3-4 weeks, workspace +3 weeks) and one-hour checks folded into owning features.
- G-04 (XL) and G-72 (XL) are split along real seams, with ENG-04 explicitly staffed by two engineers.
- Cut lines are named (ask_user, the YAML editor, OPS-03, HRN-06), and deferred gap parts have reasons.
- The import boundary is enforced by a test from FND-01. Hot-file seams are one-line registry calls, with upstream PRs for the generic registries.
