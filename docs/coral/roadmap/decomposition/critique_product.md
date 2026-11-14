# Critique of master v1: Staff Product lens

Input: `decomposition/master_v1.md` and `master_v1.json` (85 features, K1-K20). Backbone: `investigation/gap_analysis.md`, `investigation/product.md` (PC-01..PC-38, journeys (a)-(m), §5 states, §9 MVP). Code read-only at `2a9cbe2c2`. "PRO-n" ids match the returned issue list.

## 0. Verdict

The plan is structurally sound for a product: every journey has owners, the read-only diagram and run overlay ship with M2 (TLD-14), the cut lines are explicit, and M2 avoids over-claiming by showing no labels. Three things stop the M2 MVP from being trustworthy and lovable as planned:

1. **Over-claim through a missing host dimension (blocker).** The "read-only by sandbox" claim and every sandbox-backed Enforced label assume an FS sandbox that Windows hosts do not have. On Linux without `bwrap`, the session fails when it is built (mid-run), not at preflight.
2. **The core trust moments have no owner.** No feature owns what the user sees when approving the gate (diff, evidence, findings, why here). No feature owns what the user gets at the end (branch, commits, diff). There is no spend visibility while an API key is billed. There is no guarantees panel, even though the claude-sdk registry is bench-tested inside M2.
3. **The Inbox and sidebar would show Coral runs badly.** Gates would appear twice and fire two OS notifications. The run session's sidebar row opens an empty chat whose composer would start a turn the topology assumes never happens.

Everything else is major or minor polish: the pause-reason enum, the UI-state matrix, the naming rule, OQ attachments, M4 UI orphans, metrics, M2 audience and model-access copy.

## 1. Product capability coverage (PC-01..PC-38)

| PC | Owning features | Status |
|---|---|---|
| 01 Brand skin | BRD-01 (M1) | Covered |
| 02 Desk chrome | BRD-02 (M1) | Covered |
| 03 Model access and auth onboarding [MVP] | HRN-02 (M2 guard), HRN-03/HRN-04 (M3) | **Partial.** There is no M2 path to set an API key; HRN-04 onboarding is M3. Subscription users can never run an orchestrated workflow through M4 (PRO-08). |
| 04 Library and storage | DUR-02, WEB-02, WSP-01 import | Covered |
| 05 Validation | ENG-03, WEB-02, RUL-02 (V9) | Covered |
| 06 Translation confirmation | EVD-03 + WEB-03 picker; RUL-03 + WEB-06 | Covered (LLM translation deferred per TLD-19) |
| 07 Agent profiles | PRF-01 (M2 seeds), PRF-02, WEB-07 (M3) | Covered. The nav points at a placeholder until M3 (PRO-16). |
| 08 Promise labels and guarantees panel [MVP] | RUL-02, WEB-06 (M3) | **Gap against the MVP** (PRO-03). Label inputs are incomplete (PRO-01, PRO-11). |
| 09 Templates | ENG-07, WEB-03 | Covered |
| 10 Canvas | WEB-01 (M2 read-only), WEB-08/09 (M4) | Covered |
| 11 YAML pane | WEB-02 | Covered, with a cut line (PRO-23) |
| 12 Simulate | ENG-07, DUR-02, WEB-01 | Covered |
| 13 Start dialog and preflight | WEB-03, API-02 | Covered. Sandbox preflight and spend are missing (PRO-01, PRO-05). |
| 14 Lifecycle | ENG-06, API-02, WEB-04 | Covered |
| 15 Runs list | WEB-04 | Covered. No cost column (PRO-05). |
| 16 Live run view | WEB-04, WEB-10 | Covered. No outcome panel (PRO-02). |
| 17 Orchestrator conversation | WEB-05, WEB-10, SES-07 | Covered |
| 18 Per-agent sessions | WEB-05, SES-03, SES-06 | Covered. The anchor row and page are undefined (PRO-07). |
| 19 Human gates | GTE-01, GTE-02, WEB-04 | Covered. Context (PRO-02), states (PRO-10) and authority (PRO-17) are missing. |
| 20 ask_user | TLS-03 | Covered (first M2 cut) |
| 21 Notifications and Inbox | GTE-02, GTE-03, GTE-04 | Covered. Duplicates (PRO-04); completed and failed alerts missing (PRO-18). |
| 22 Steering | WEB-05, SES-04 | Covered |
| 23 Take-over | SES-07, WEB-10 | Covered (M4) |
| 24 Pauses and recovery | ENG-06, SES-06, DUR-05, WEB-04, HRN-04, SES-07 | Covered. The enum is incomplete (PRO-06). |
| 25 Budgets and cost [MVP basic] | RUL-01 (backstop), RUL-05 (M4) | **Gap.** No spend visibility at M2 and no mapped outcome when the backstop is hit (PRO-05). The M4 budget UI is unowned (PRO-12). |
| 26 Evidence and Coral-run checks | EVD-01..04 | Covered. The M4 check-result UI is unowned (PRO-12). |
| 27 Workspaces and merge outcomes | WSP-01, WSP-03 | **Gap.** No branch or diff view (PRO-02); conflict UI unowned (PRO-12). |
| 28 Amend | ENG-10 | Covered (lite) |
| 29 Rules and reactions | RUL-03, WEB-06, ENG-09 | Covered. The reaction-authoring UI is unowned (PRO-12). |
| 30 Structure | ENG-08, ENG-09, WSP-03, TLS-04, WEB-10 | Covered |
| 31 Suggestions | EXT-01 | Covered (post-M4) |
| 32 Sharing | EXT-03, EXT-04, EXT-05 | Covered (post-M4) |
| 33 Run log, audit, export | WEB-04 (view) | **Export is orphaned** (PRO-19) |
| 34 Versions and diff | WEB-02 list, ENG-10, WEB-10 versions tab | Covered |
| 35 Codex | HRN-05, HRN-06 | Covered |
| 36 Elephant-Goldfish | EXT-02 | Covered |
| 37 Intro and empty states | WEB-02, BRD-02 | Covered |
| 38 Navigation and gate | BRD-02, FND-02 | Covered |

Journeys (a)-(m) all have owners (master §3 table). The gaps are inside journeys:

- (a) has no M2 setup path to an API key.
- (e) and (f) have no spend or outcome.
- (g) has no gate context, duplicates, and a placeholder authority model.
- (i) has an incomplete pause enum.
- (k) has a placeholder desk at M2.

## 2. Milestones: demoable journey and exit criteria

- **M1.** The CLI/API journey satisfies the mandate ("usable through the API"). Step 2 calls `coral workflow upload`, but the `coral` console script belongs to OPS-03 (M2, "may slip to PH5"), and both DUR-02 and OPS-03 claim `coral/cli.py` (PRO-20).
- **M2.** The journey is demoable end to end. Its exit criteria are engineering-only: there is no user-outcome or dogfood criterion and no metric (PRO-14). Exit 9 ("reviewers are read-only by sandbox") is false on Windows hosts (PRO-01). Exit 11 ("no promise labels yet") under-serves PC-08, although nothing blocks a claude-sdk slice (PRO-03).
- **M3.** Journey step 3 ("switch Implement to claude-native … read-only becomes Verified") is inconsistent: Implement is the writer and is never read-only. It also hides that the orchestrator and reviewers still need an API key (PRO-08). Exit 7 ("native auth and egress paths are cleared") is not testable (PRO-22).
- **M4.** The journey is good. Exit 4 ("… all work") is a list, not a test (PRO-22). Several M4 capabilities have no UI owner (PRO-12).
- **Post-M4.** No exit, by design. Acceptable.

## 3. UI states (empty, loading, error, paused, offline, permission denied)

The slice decomposition (`decomp_slice.md` §1, "UI surface ownership") gave each surface one owner for all its states plus extension points. The master dropped that rule. States that are now unowned:

| Surface | Missing states | Proposed owner |
|---|---|---|
| Gate card (Inbox, run view, /approve) | submitting; accepted "by you at 14:02"; already answered elsewhere; stale visit; run no longer waiting; not permitted / waiting for owner; offline (submit disabled); reminder badge "waiting 3 h" (product §5.3) | GTE-02 (card), GTE-01 (server reasons) |
| Run view | loading skeleton; "Couldn't load this run" + retry; 404 "not found or no access"; "Reconnecting…" indicator; final state with outcome and "Run again" (product §5.2) | WEB-04 |
| Inbox workflow kind | empty and error banner (pattern `InboxPage.tsx:170-181`) | GTE-02 |
| Simulate | needs input; deadlock highlight; limit reached; failing saved test with expected vs actual path (product §5.4) | WEB-01 |
| Agent pane | runner or host offline; "Step waiting on you" | WEB-05 |
| Phone width | Inbox card, gate card and simplified run view; D§13 promises approvals "on the phone" (`coral-design.md:363`); OQ-23 is attached to WEB-04, but WEB-10 and WEB-08 exclude mobile layouts | GTE-02, WEB-04 |
| Accessibility at M2 | The xyflow diagram has no accessible equivalent until the WEB-09 outline (M4). The M2 run view needs keyboard and screen-reader access through the timeline and gate panel (product Q-29). | WEB-04, WEB-01 |

## 4. Promise labels per milestone

- **M1.** No run surfaces. Safe.
- **M2.** No labels are shown, but copy and exit criteria still make claims. "Read-only by sandbox" depends on the host backend:
  - Windows `windows_jobobject` provides no filesystem isolation (`omnigent/inner/windows_jobobject_sandbox.py:6-7, 19-20`) and is the platform default on Windows (`omnigent/inner/sandbox.py:1440-1448`).
  - On Linux the `bwrap` backend raises at session build when the binary is missing (`omnigent/inner/bwrap_sandbox.py:301-313`).
  - The host hello frame reports no platform or sandbox field (`omnigent/host/frames.py:319-330`), and `HOST_CAPABILITIES` has no sandbox token (`:76-94`).
  - Preflight (API-02) does not check any of this (PRO-01).
- **M3.** RUL-02 computes labels from harness mode only. Missing inputs:
  - host sandbox (PRO-01);
  - gate integrity on native modes, since the agent can read the bridge-dir bearer (D25). GTE-01 says it "labels" this, but no label engine exists until RUL-02.
  - `egress_rules` do not cover the Claude CLI's own traffic in claude-sdk (`investigation/eng_workspace.md:41`);
  - rosters on claude-native, where vendor sub-agents are reachable unless denied fail-closed;
  - the Verified tooltip for L1 evidence. WSP-02's own proof says L1 misses re-edits that L2 catches.

  See PRO-11.
- **M4.** Budgets (RUL-05) overshoot by a turn, so they must never be labelled Enforced. When WSP-02 adds L2, the label fixture must be updated. No feature states either rule (PRO-11).

## 5. Product open questions OQ-1..OQ-27

All 27 are attached to at least one feature. Defects:

- **OQ-26 (telemetry and success metrics) is attached to EXT-01.** That is product.md's Q-26 (suggestion data), which has no gap id. Telemetry and metrics have no owner (PRO-14).
- **Questions that gate M1/M2 features but are missing from SPK-01's sign-off list** (PRO-13):
  - OQ-5: gate reminder cadence and run expiry. ENG-06 ships gate reminders at M2.
  - OQ-7: hero role. BRD-01 ships the hero at M1.
  - OQ-8: workflow ids. DUR-02 is M1.
  - OQ-15: backstop default. RUL-01 is M2.
  - OQ-16: estimate presentation. WEB-03 is M2.
  - OQ-17, product half: what the sidebar shows; only SPK-02, the technical spike, holds it.
  - OQ-23: phone scope for M2 gates.
  - OQ-24: the inbox-kind visual. SPK-01 defers OQ-24 to "before PH3", but GTE-02 is PH2.
  - OQ-26: metrics.

## 6. User-facing orphans between features

- Gate decision context and run outcome (PRO-02).
- Run-session sidebar row and chat page (PRO-07).
- Spend display and backstop outcome (PRO-05).
- M4 surfaces with backend-only owners (PRO-12). These features have no `web/` path in `master_v1.json`: RUL-05 (budget field, spend vs budget, overshoot disclosure, step budgets), EVD-04 (check results, integrity flags, verifier), WSP-03 (merge and conflict state), ENG-09 (reaction authoring, saved-blocks library) and DUR-06 (retention setting, deleting a workflow that has runs). WEB-10's In list contains none of these.
- Run completed and failed alerts (PRO-18).
- Run-log export (PRO-19).

## 7. Brand and naming placement

Correct:

- the `omni` slot's data changes, `--font-display` is added and `--font-heading` is untouched (TLD-16, R-15, X-21);
- code lives in `web/src/brand/` and `web/src/workflows/`;
- routes are `/workflows` and `/profiles`, with no `/schemas`;
- Note is layout-only (K1);
- desktop builds stay disabled until the BRD-03 updater fix (R-18);
- naming sign-off (OQ-27) and Powered-by (OQ-30) are in SPK-01.

Defects:

- **The vendor naming rule is scheduled too late.** DD§16.1 (`CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md:1308`): "Claude Code" is "Not permitted" for SDK-built products, so roster chips read "Claude". The rule sits only in WEB-07 (M3), but claude-sdk roster chips render at M2 in WEB-03, WEB-04 and WEB-05. The web's built-in display order and labels use "Claude Code" (`web/src/lib/agentGrouping.ts:64`) (PRO-09).
- **The hero is placed without a decision.** BRD-01 ships "Direct the run…" (UI§1 line 14) at M1, while OQ-7 (plain session or run composer) is not in SPK-01, and nothing owns a workflow chip if (b) is chosen (PRO-21).

## 8. Is M2 lovable and trustworthy?

The proving journey is good. A real user would hit these points:

1. **Setup.** A Claude Code user with only a subscription authors and simulates, then is refused at preflight (HRN-02). The fix destination exists: Settings → Harnesses → "Use an API key or gateway URL instead" (`web/src/pages/settings/HarnessFixDialog.tsx:997-1004`; account kind `api_key`, `SettingsHarnessesSection.tsx:392-393`). Nothing links to it or states the requirement up front (PRO-08).
2. **Watching.** No spend is shown while an API key is billed (PRO-05). No panel says what Coral holds (PRO-03).
3. **Approving.** The gate card shows authored outcome buttons but not the change or the evidence (PRO-02). The same gate appears twice in the Inbox. The existing collector lists every pending elicitation of sidebar rows, including child mirrors (`web/src/pages/InboxPage.tsx:240-269`; `web/src/lib/inbox.ts:18-24`; `omnigent/runtime/pending_elicitations.py:277`), and GTE-02 adds a gate alert. Two OS notifications fire, one from the existing elicitation transition (`web/src/hooks/useIdleNotifications.ts:9`) and one from GTE-02's run notification. The generic copy vanishes when the runner is offline (`omnigent/server/routes/_sessions/helpers.py:1608-1617`). The original web design avoided duplicates (`investigation/eng_web.md:711`, N18) (PRO-04).
4. **Finishing.** The run "ends with the branch kept" with no branch name, commit list, diff or checkout command. The existing changed-files view is per session since session start (`web/src/hooks/useWorkspaceChangedFiles.ts:1-15`), so it cannot show a multi-session run's base..head diff (PRO-02).
5. **Sidebar.** Under TLD-02 option B the run session is a root row (the sidebar lists only `parent_conversation_id IS NULL`, `investigation/eng_sessions.md:435`). Opening it shows a turnless chat, and typing would start a turn (PRO-07).

## 9. TLD flags (none found unsound; consequences flagged)

- **TLD-07.** Its stated consequence, "subscription-only users wait for claude-native at M3" (HRN-02, decisions log 52), is false for every workflow with an orchestrator node. The orchestrator is claude-sdk only (TLS-03); HRN-03 excludes a "claude-native orchestrator" and HRN-05 a "Codex orchestrator". PC-03's done-when ("subscription users can run workflows on claude-native") is unmet through M4 (PRO-08).
- **TLD-09.** Gates "surfaced as elicitations on the stable run session" plus an "Inbox workflow kind" produces two Inbox cards per gate unless one source is suppressed (PRO-04).
- **TLD-11.** "Computed per mode from the capability registry" needs a host dimension, or it over-claims on Windows (PRO-01).

## 10. Issues (prioritized)

The returned StructuredOutput carries each issue's evidence and proposed change. In short:

| Id | Severity | Summary |
|---|---|---|
| PRO-01 | blocker | Host sandbox backend is missing from K9, labels, preflight and the M2 exit criteria |
| PRO-02 | major | Gate decision context and run outcome (branch, commits, diff, salvage refs) are unowned |
| PRO-03 | major | M2 has no guarantees panel; ship a claude-sdk label slice (RUL-02 finishes at week 16, before the 18.5-week M2 path) |
| PRO-04 | major | Inbox shows each gate twice and fires two notifications; one canonical card per gate |
| PRO-05 | major | No spend visibility at M2; backstop DENY has no run outcome |
| PRO-06 | major | K2 pause-reason enum is incomplete; no owner for reason copy |
| PRO-07 | major | Run anchor session's sidebar row and chat page are undefined |
| PRO-08 | major | Model access: no M2 path to an API key; subscription users blocked through M4; M3 journey step 3 inconsistent |
| PRO-09 | major | Vendor naming rule ("Claude", not "Claude Code") needed at M2, not M3 |
| PRO-10 | major | UI state matrix ownership, including phone width and an M2 accessibility baseline |
| PRO-11 | major | RUL-02 "never Enforced" inputs (D25, claude-sdk CLI egress, budgets, L1 tooltip, native rosters, command rules) |
| PRO-12 | major | M4 backend features with no UI owner |
| PRO-13 | major | Product OQs that gate M1/M2 are missing from SPK-01; OQ-24 timing |
| PRO-14 | major | No success metrics or telemetry; OQ-26 misattached; no user-outcome exit criterion |
| PRO-15 | major | M2 audience undefined; external release gate (OPS-03, licensing, scoped security) |
| PRO-16 | minor | Agent Profiles nav is a placeholder through M2 |
| PRO-17 | minor | GTE-01 says "owner-only (LEVEL_EDIT)"; needs a waiting-for-owner state |
| PRO-18 | minor | Run completed, failed and cancelled alerts plus "Run again" are missing |
| PRO-19 | minor | Run-log export (PC-33) is orphaned |
| PRO-20 | minor | M1 journey depends on the OPS-03 console script; `coral/cli.py` has two owners |
| PRO-21 | minor | Hero OQ-7 is not decided before BRD-01 ships it |
| PRO-22 | minor | M3 exit 7 and M4 exit 4 are not testable; M3 lacks a user outcome |
| PRO-23 | minor | YAML-editor cut line: the Use-template dialog must expose the loop limit and done-when |

## 11. Strengths

- All 38 PCs and 13 journeys map to features. The journey table makes coverage auditable.
- The read-only diagram, Simulate UI and live run overlay ship with M2, so users can see runs from the first real run (TLD-14, D19).
- Honest MVP promises: no gates via policy ASK and no auto-resolve; an "app must be open" notice; no labels before a registry exists; push and an external channel are deferred explicitly.
- Product-correct moves into M2: the S13 credential guard, `write_paths: []` reviewers and the per-session cost backstop.
- Explicit cut lines on WEB-02 YAML editing, TLS-03 ask_user, OPS-03 and HRN-06 protect the M2 date without losing the journey.
- The SES-05 walking skeleton grows into the M2 acceptance lane, with one owner from the first integration to exit.
- Brand decisions follow TLD-16, R-15, R-16 and X-21, and desktop builds stay off until the updater fix.
- 25 of 27 product OQs are attached to the features they block.
