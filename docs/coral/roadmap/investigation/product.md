# Coral: product requirements, experience decomposition and feature completeness

Role: Staff Product (Agent 4). Repository: Omnigent fork at `omnigent-ai/omnigent`, HEAD `2a9cbe2c2` (0.22.0.dev0). Date: 2026-11-11.

Inputs read in full: `coral-design.md` (Draft 4, 452 lines, cited **[D§n]**), `coral_UI_DESIGN_LANGUAGE.md` (413 lines, cited **[UI§n]**), `CORAL_WORKFLOW_ENGINE_DEEP_DIVE.md` (§0-§20 and App. A-B; cited **[DD§n]**, fact checks **F#**, seams **S#**, validation rules **V#**). Also read: `designs/REUSABLE_USER_AGENTS.md` (§1-§6.18), `designs/CUSTOM_AGENTS_SETTINGS_UI.md`, `designs/PROJECTS_PRD.md` (skim), `designs/CUJ-MAP.md`, `feature-map/README.md`, `feature-map/custom-agents.md`, `feature-map/session-orchestration.md`, `feature-map/automations-introduction.md`, `feature-map/automation-templates.md`, `feature-map/sessions.md` (sub-features), and the web code listed in the task.

Evidence conventions:

- `path:line` = opened by me at HEAD in this pass. Refs that I took from the deep dive without re-opening are marked "(per DD, not re-opened)".
- **UNVERIFIED** = a statement I could not confirm in code.
- Reuse classes: **Reuse** (as-is), **Extend**, **Modify**, **New**, **Replace**, **Remove**.
- "Provisional" marks naming that the UI doc explicitly leaves open ([UI§5.3], [UI§8.2], [UI§8.3]).

---

## 0. Ten-line digest

1. Coral sells **trust in a multi-step agent process**: the path, the roster, the gates and "done" are held by rails, not by a prompt. Every user-facing surface must show *which* promises are held and *how strongly* (Enforced / Verified / Requested / Judgment).
2. The product requirements document `coral-requirements.md` referenced at [D§0] (`coral-design.md:5`) **does not exist** in the repo. Personas, success metrics, non-goals and MVP scope are therefore unwritten; this file proposes them, but they need an owner's sign-off.
3. Almost every run-time surface can **reuse** Omnigent screens (transcript, composer, approval cards, inbox, `/approve` link, side-chat pane, run-history template, automation gallery and creation modal). The truly new UI is: the workflow editor (canvas + YAML), Simulate, the run view (diagram overlay + run log), the start-run dialog, profile Coral fields, and the brand skin.
4. Three load-bearing product promises are **not deliverable as Draft 4 states them** at this commit: approvals on a phone when the app is closed (no push exists), budget "pause and ask" via `cost_budget`, and roster enforcement via a "fail-closed router". UX copy must not promise them until replacement work lands.
5. **Default auth is a product decision with legal weight**: `claude-sdk` with subscription login conflicts with Anthropic's published terms [DD§16.1]; the onboarding flow must route users to API keys (headless, strongest guarantees) or `claude-native` (subscription, weaker guarantees and labels).
6. The **Draft 4 example workflow still leaves "reject" at the human gate undefined**, and no artifact defines who may answer a gate, what happens on decline/cancel, or how an unattended gate reaches the user.
7. IA recommendation: one new desk area **Workflows** at `/workflows` (tabs: Your workflows / Runs / Templates; run view at `/workflows/runs/:runId`), plus **Agent Profiles** at `/profiles` as a Coral lens over Omnigent's existing custom agents. The UI doc's "State Schema" `/schemas` label and route are prototype names; keep the label provisional but fix the route segment now.
8. Recommended MVP ("smallest lovable Coral"): author or pick a single-item **"Implement → review → fix loop"** template, Simulate it for free, run it on a local repo with Claude on an API key, watch the path and decisions live, see evidence for "done when", answer the merge gate in the inbox, and get understandable pauses. Repeat-for-each, canvas editing, Codex, amendments and suggestions come after.
9. Bring a **read-only diagram and live run overlay forward** to the first agent-step milestone; Draft 4's order of work [D§18] has the canvas in phase 5, which leaves phases 2-4 with no way for a user to see a run.
10. 38 product capabilities (PC-01..PC-38) and 10 shared platform capabilities (PL-A..PL-J) are inventoried in §3; 36 open product questions in §7; 24 cross-artifact conflicts in §8.

---

## 1. What Coral is for

### 1.1 Problem

Coding agents (Claude Code, Codex) are individually capable, but multi-step work (find PRs → review with two agents → fix → re-review → approve) is today sequenced by **a model following instructions**. Nothing guarantees that a review actually happened, that a human approved before a merge, that tests ran after the last edit, or that a loop stops. [D§1]: "Every multi-step behaviour in Omnigent today is sequenced by a model following instructions." The deep dive confirms the in-tree precedent, Polly, sequences its work in a roughly 270-line prompt with per-call guardrails only (`examples/polly/config.yaml:31-301, 351-380`, per DD, not re-opened).

The user pains Coral addresses:

| Pain | Today in Omnigent | Coral promise |
|---|---|---|
| "The agent skipped a step / approved itself" | Prompted sequencing | The run follows only arrows that exist; human gates cannot be skipped (Enforced) [D§6] |
| "It said tests pass, they didn't run" | Agent self-report | "Done when" backed by the session record and exit codes, after the last workspace change (Verified) [D§6.1] |
| "It looped forever and burned my plan" | No loop limits outside prompts | Loop limits, attempts, rejected-call pause, budgets [D§5.2, D§7.3, D§10] |
| "I can't tell why it went this way" | Transcript archaeology | Every decision recorded with a reason; clicking an arrow shows why it was taken [D§13] |
| "Reviewers saw the implementer's reasoning" | Shared context | Fresh-context step agents, separate sessions by default [D§7.4] |
| "I had to babysit it" | Must be present | Automatic advance, watchdog, alerts, pauses that resume [D§7.2, D§7.3, D§7.8] |

### 1.2 Target user

- **Individuals first, data ready for teams** [D§3 "Users"]. Primary persona (proposed, needs sign-off because `coral-requirements.md` is missing): a senior engineer or tech lead who already runs Claude Code / Codex daily, has a Claude or ChatGPT plan or API keys, works in git repositories on their own machine, and wants repeatable, auditable multi-agent processes (PR review, issue fix, design review) without writing orchestration code.
- Secondary (later): a team lead who shares templates via a git repo [D§3 "Sharing"] and later shares runs [D§13].
- "Team-ready data" is a storage property, not a team feature: every row carries an owner and Omnigent's `workspace_id` [D§7.6]. The deep dive corrects that `workspace_id` is a tenant partition, always `0` in OSS, not a team (F32). So no team UI exists to build on; team features are later.
- Non-users for v1 (proposed): non-technical users (workflows are plain language, but workspaces are git repos), hosted multi-tenant SaaS operators (terms risk [DD§16]), marketplace buyers (later [D§15]).

### 1.3 Core concepts as the user meets them

| Concept | User-visible meaning | Where defined |
|---|---|---|
| Workflow | A named diagram plus file; has versions; runs follow the version they started with | [D§1, D§7.7, D§12] |
| Step (work step) | A box: name, goal, roster, handoff; optional "done when", attempts, failure path, repeat for each, rules, how agents run, expected duration, agents change code, Coral-run checks | [D§5.1] |
| Roster | Which agent profiles do the step, exact or "up to" N; chips on the box | [D§5.1, D§5.2] |
| Handoff | What the step passes on: a report and artifacts; sometimes a checked label or list the user never configures | [D§5.3] |
| Orchestrator | One per run; receives the request; decides at orchestrator nodes with a reason; does not do the work | [D§1, D§3] |
| Orchestrator node | Decision point drawn on canvas; shows the agents' reports and the orchestrator's choice | [D§5.2] |
| Human gate | A person approves, rejects, chooses or answers; cannot be skipped | [D§5.2] |
| Group / block | Container whose rules apply inside; saved group = block; can repeat for each with "3 of 10" badge | [D§5.2] |
| Arrow | Carries handoffs; labelled out of decisions/gates (and single-agent steps [D§5.3]); back-arrows need a limit and an at-limit destination | [D§5.2] |
| Parallel split / join, merge of alternatives | Derived by the validator; the canvas shows the join type on the box | [D§5.2]; [DD§5.3.1] |
| Profile | Agent definition + canvas description + default rules + expected capabilities | [D§5.4] |
| Rule | Plain-language; Required (translated and enforced, or workflow invalid) or Guidance (requested) | [D§9] |
| Reaction | "When X happens, do Y" rule | [D§9] |
| Evidence requirement | The confirmed machine reading of "done when" | [D§6.1] |
| Coral-run check | A command Coral runs itself after agents finish | [D§6.2] |
| Run | One execution; pauses, resumes, cancels; has a run log | [D§7] |
| Amendment | "Apply to this run" edit to not-yet-started steps | [D§7.7] |
| Simulate | Walk the diagram with made-up results, no agents, no cost; save as test case | [D§8] |
| Template | Starting point for most users | [D§12] |

### 1.4 The promise taxonomy, as the user experiences it

Draft 4 labels three promise strengths and lists "deliberately not promised" items without a label [D§6] (`coral-design.md:201-215`). The deep dive names the fourth class **Judgment** ([DD§2], verifier verdicts "stay labelled Judgment" [DD§9.3]). The word "Judgment" does not appear in Draft 4 (grep, `coral-design.md`). Product recommendation: ship four visible labels, because the user must be able to question the unpromised parts ([D§6]: "recorded so that the user can see and question them").

| Label | What the user should understand | Where it appears | Example |
|---|---|---|---|
| **Enforced** | Coral prevents the violation; it cannot happen, or the run stops | Badge on arrows, gates, roster chips, Required rule badges; run view "held" markers | "Human gate: cannot be skipped"; "Never force-push (Enforced on claude-sdk)" |
| **Verified** | Coral checks after the fact against records it trusts; it can be gamed within limits it states | "Done when" badge, handoff checked parts, Coral-run check results | "Tests and lint ran and passed after the last change to `api/users.ts`" |
| **Requested** | Coral told the agent; nothing checks it | Guidance rule badges | "Prefer small commits (Requested)" |
| **Judgment** | A model chose among legal options; Coral records the reason so you can question it | Orchestrator decisions, verifier verdicts, quality of work | "Chose *changes requested*: two blocking findings in auth.ts" |

Experience requirements (proposed):

- **Labels are per mode, not per rule.** The same Required rule may be Enforced on `claude-sdk` and unenforceable on headless `codex` (finding 5, F37) or on native modes until fail-closed hooks ship (finding 6, S14/S15). The validator makes such a workflow invalid [D§9]; the editor must say *which roster profile's mode* breaks it and offer the two remedies in [D§9]: change the profile, or downgrade the rule to Guidance.
- **Labels never over-claim.** Until the replacements in §8 D1 land, the UI must not show Enforced for: rosters in sub-agent mode (no router gate, F4/F28), rules on native modes (hooks fail to ASK, F38a), budgets (per-session policy only, F42).
- **A "What Coral guarantees" panel** per workflow (and per run) lists every promise with its label, generated from the compiled graph and capability matrix. This is the product's core trust artifact and is not specified anywhere yet.
- **Gaming caveat is visible.** [D§6.1] states "Gaming is limited, not impossible"; the Verified tooltip should say what was checked and what was not, and point to verifiers / Coral-run checks.
- **Visual language gap.** The UI doc defines no badge styles for the four labels. Proposed mapping on the Clay palette (provisional, for design to confirm): Enforced = forest `#4D7356` solid; Verified = sage `#9EAB92` with check glyph; Requested = mustard `#C19A55` outline/dashed; Judgment = ink `#523E31` outline with a "reason" glyph. Avoid clay (brand/destructive-adjacent per [UI§2.4]) for normal states.

---

## 2. Core user journeys

Each journey lists entry points, screens, states, and exits. "Reuse" notes point to existing Omnigent surfaces.

### (a) First run, brand and onboarding

- **Entry points:** install the desktop app or open the web app; Electron connect screen; first visit to `/`; first visit to `/workflows`.
- **Screens:**
  1. Electron connect: title "Coral — Connect", cream ground with washes, logo + Newsreader "Coral", accent rail, copy "Run a Coral server…" [UI§7]. Today the title is "Omnigents — Connect" (`web/electron/setup/index.html:6`) and `productName` is "Omnigent" (`web/electron/package.json:3, 43`). **Modify.**
  2. Landing composer (hero) with mark beside "Direct the run…" [UI§4.3]. Today the hero stacks `BrandLogo variant="eyes"` above an `h1` with `useHeading()` (`web/src/shell/NewChatDialog.tsx:7011-7047`, heading from `web/src/lib/branding.ts:5` = "What should we build?"). **Modify.**
  3. **Model access setup (new, required):** choose how Claude is reached for run-owned sessions: (i) API key (Console key or plan-linked Console key; recommended; enables the headless `claude-sdk` mode with the strongest guarantees [DD§10.2]); (ii) "Use my Claude subscription" (routes steps to `claude-native`, the unmodified Claude Code binary, which Anthropic's terms carve out [DD§16.1]; some rules show reduced labels). Existing harness setup and login flows exist in Settings → Customize → Harnesses (`web/src/shell/settingsNav.tsx:109-141`) and host login endpoints (`omnigent/server/routes/hosts.py:1903-2146`). **Extend.**
  4. Connect a workspace: pick a host (the user's machine first [D§3]) and a git repository. Reuse the automation dialog's "Run on" / Repository / Random worktree controls (`web/src/components/scheduled/CreateScheduledTaskDialog.tsx:1102, 1323, 1430`). **Reuse/Extend.**
  5. Workflows first visit: an introduction walkthrough modelled on Automations' intro (feature map `automations-introduction.md`: first-visit, walkthrough, examples, reopen via info button, browser-local dismissal). **New (pattern Reuse).**
- **States:** server info loading (existing `FeatureGatedPage` spinner, `web/src/App.tsx:76-86`); feature flag off → Not found; no host connected; harness not installed / not logged in; API key missing; subscription-only (warn about reduced labels).
- **Exits:** land on Workflows → Templates tab; or skip to a plain Omnigent session (Coral keeps general chat).
- **Open:** whether the hero "Direct the run…" starts a workflow run or a plain session (§7 Q-07).

### (b) Create a workflow from a template

- **Entry:** Workflows → Templates tab (`/workflows?view=templates`), template suggestions below "Your workflows" (pattern: `feature-map/automation-templates.md` `preview`), command palette "Go to Workflows" (extend `web/src/shell/CommandPalette.tsx:195-208`).
- **Screens:**
  1. Template gallery cards: name, one-line purpose, diagram thumbnail, roster summary ("2 Claude reviewers, 1 Claude implementer"), requirements ("Needs: a git repo with tests; GitHub CLI for PR templates"), promise summary ("1 gate, loop limit 3, tests verified").
  2. "Use template" dialog: name, target repository (sets where `.coral/workflows/<id>.yaml` is written [D§12]), parameters the template declares (e.g., PR label), profile substitutions (e.g., which model per reviewer), and the repo's detected test/lint/format commands to confirm [D§6.1].
  3. Translation confirmation (see journey c) for every "done when" and Required rule in the template (templates should ship pre-confirmed translations; re-confirm only if profile/mode differs).
  4. Lands in the editor in Simulate-ready state.
- **States:** gallery loading/failed (templates must still show if the user's workflow list fails, as Automations does: "Templates remain available even if loading the user's automation list fails" `automation-templates.md`); repo not selected; host offline (cannot write the file; offer "Save to my library" if a server-side copy exists, §7 Q-10); command detection found nothing (author types commands); translation pending/failed.
- **Exits:** editor; cancel creates nothing (pattern: "Selecting a template does not create an automation until the modal is submitted").

### (c) Author and edit on canvas + YAML (both ways)

- **Entry:** Workflows list → workflow; "New workflow" (blank: Start → one step → End); open a `.coral/workflows/*.yaml` from a repo.
- **Screens:** editor at `/workflows/:workflowId` with three panes (provisional per [UI§8.2]): left add-palette, center canvas, right inspector; YAML pane toggle (split or tab). [UI§8.4] prototype layout: "left add-palette, center canvas, right inspector".
  - Palette shapes: Start, End, Work step, Orchestrator node, Human gate, Group; hidden advanced: Wait, Sub-workflow [D§5.2]. (UI doc's Phase/Gate/Note/Orchestrator taxonomy is provisional and superseded, §8 D3.)
  - Inspector for a step: name, goal, roster (profile picker + count + exact/up-to), handoff text, done-when (with translation status), attempts, failure path, repeat for each, rules, how agents run, expected duration, agents change code, Coral-run checks [D§5.1].
  - Arrow inspector: label (only where legal), back-arrow limit and at-limit destination [D§5.2].
  - Derived info shown read-only: join type per box (AND-join / merge), checked parts per handoff (label enum / list), loop table [DD§5.1, D§5.3].
- **Two-way sync:** YAML is canonical, canvas edits become AST patches preserving comments and confirmed translations [DD§14.4]; layout in a separate file keyed by stable node ids [D§12; DD§14.4]. Omnigent's existing canvas layout lives in browser localStorage (`web/src/canvas/canvasStorage.ts:1-9`) and cannot back a repo file — **New** layout persistence.
- **Validation:** problems explained on the affected box [D§12]; rules V1-V13 [DD§5.5] (e.g., "This box mixes labelled and unlabelled arrows" V3; "Loop has no limit" V5; "Gate has no reject route; confirm approve-only" V7; "Required rule *read-only* cannot be enforced by `codex` (headless) in roster member 2" V9).
- **Confirming translations:** on save, a model translates each "done when" into an evidence requirement and each Required rule into Omnigent settings; the author confirms in plain words [D§6.1, D§9]. Requires: a confirmation sheet listing original text → plain-words reading → technical summary (e.g., policy names, egress allowlist), a dry-run result [DD§10.7], Confirm / Edit text / Make guidance. Translation uses usage and is counted [D§10]. Invalidation on text, profile/mode, or handler change [DD§10.7].
- **States:** loading file from host; host offline (read-only from last known version or blocked; §7 Q-10); unsaved changes; save in progress; translation pending/failed/needs re-confirmation; validation errors; file changed on disk (git pull) → conflict prompt; YAML parse error (canvas shows last valid graph with a banner); large graph (auto-layout in a worker [DD§14.4]).
- **Exits:** Simulate; Start run; versions list; leave with dirty-draft confirmation (pattern from custom agent editor: "Cancel and the form's back button confirm dirty drafts" `designs/CUSTOM_AGENTS_SETTINGS_UI.md:125-126`).
- **Accessibility gap:** a free-form canvas needs a keyboard/screen-reader equivalent; the YAML pane plus an outline list (steps and arrows as a tree) should be the accessible path. Not specified in any artifact (§7 Q-29).

### (d) Simulate and save as test case

- **Entry:** editor toolbar "Simulate"; validation suggestion ("Simulate to check loops"); template ships with saved simulations.
- **Screens:** Simulate mode overlays the canvas; a script panel lets the user set, per step, made-up results: handoff label, list length, done-when pass/fail, gate answers [D§8]; Step / Run to end / Reset controls; outputs: path, loop counts, gates reached, limits hit, activation count, estimated sessions (Σ activations × roster size) [DD§15.1]. "Save as test case" names the script; saved cases run whenever the workflow file changes [D§8]. Exhaustive check runs at save and reports deadlocks/dead boxes/unreachable at-limit [DD§15.1].
- **States:** script incomplete (engine waits at a step: "Choose a result for *Review*"); deadlock detected (highlight the waiting join and the arrow that can never arrive, with the liveness explanation [DD§5.3.7]); limit reached; saved test failing after an edit (badge on workflow list and editor); exhaustive enumeration capped ("sampled N of M combinations").
- **Exits:** fix and re-simulate; Start run with the estimate pre-filled.

### (e) Start a run

- **Entry:** workflow page "Run"; editor "Start run"; template "Use and run"; (later) the hero composer ("Direct the run…") with a workflow chip (§7 Q-07); (later) triggers [D§5.5].
- **Screen: Start run dialog (New):**
  - Request text (enters at Start; the orchestrator receives it [D§5.6 step 1]).
  - Workspace: host or sandbox, repository, base branch; per-run worktree and branch created automatically [D§11]; per-repo setup command (install deps, copy `.env`) [DD§13]. Reuse automation controls (`CreateScheduledTaskDialog.tsx:1102, 1323, 1430`).
  - Version: latest saved version (pinned for this run [D§7.7]); show unsaved-changes warning.
  - Cost estimate: sessions from Simulate + typical per-step usage from past runs [D§10]; labelled as an estimate; for plan users show plan-window utilization or tokens, not only USD [DD§12].
  - Budget: run spending limit (and per-step if authored) [D§10]; default value is undefined (§7 Q-17).
  - Preflight: profiles resolve to pinned revisions and harnesses are ready on the target host (V10) [DD§5.5]; auth mode check (API key present for `claude-sdk`, S13).
  - Primary action: Start run (idempotent via `start_key` [DD§7.2] so a double click does not start two runs).
- **States:** estimate loading/unavailable (no past runs: show session count only); preflight failures with fix links (install harness, log in, add key); host offline; sandbox repository unsupported for per-run branches (S28: managed sandboxes reject git options; `schemas.py:2012-2013` per DD); budget below estimate warning; workflow invalid (Start disabled with reason).
- **Exits:** run view `/workflows/runs/:runId`; cancel.

### (f) Monitor a live run

- **Entry:** run view after start; Runs tab; inbox card; sidebar (orchestrator session row); browser/desktop notification click; `/approve` link for a gate.
- **Screen: run view (New, `/workflows/runs/:runId`):**
  - Header (CoralPageHeader chrome): workflow name + version, run status pill (Running / Paused: reason / Completed / Failed / Cancelled [DD§6.2]), elapsed, cost so far vs budget, actions (Pause, Resume, Cancel, Apply edit…).
  - Diagram overlay: the pinned version's graph with per-box state (waiting, running, evaluating evidence, closed with outcome, skipped, taken over), arrows taken highlighted, loop counters ("pass 2 of 3"), repeat progress ("3 of 10") [D§5.2, D§13].
  - Click an arrow → "why it was taken" (decision reason or auto-advance) [D§13]; click an untaken arrow → "why not" (needs skipped-path logging [DD§5.3.1]).
  - Click a step → roster chips with live status (reuse `SessionStateBadge`, per DD §14.3), handoffs (report, artifacts, checked parts), evidence results (pass/fail with the missing item, e.g., "No test run after the last change to `api/users.ts`" [D§6.1]), attempts used, rejected calls.
  - Click an orchestrator node → the conversation between agents and orchestrator at that node, plus the chosen label and reason [D§5.2].
  - Run log timeline (append-only: step starts, handoffs, evidence, decisions with reasons, user answers, amendments [D§7.6]), filterable.
  - Focused agent session in a side pane: reuse `SideChatPane fullSession` (`web/src/components/chat/SideChatPane.tsx:166-180`).
- **Live data:** new run stream (`GET /v1/workflow-runs/{id}/stream`, snapshot + tail with cursor [DD§14.2]); session statuses via the session-updates socket; only the focused agent's transcript streams, because browsers cap live SSE conversations at 3 (4 with the grid flag) over HTTP/1.1 and 30 over HTTP/2 (`web/src/store/conversationRegistry.ts:64-84`). Product consequence: the run view shows many agents as status chips and one live transcript at a time.
- **States:** see §5.2.
- **Exits:** gate answer; steer; take over; pause/cancel; open a session full page (`/workflows/runs/:runId/c/:conversationId`).

### (g) Answer human gates and `ask_user` on web, desktop and phone

- **Entry points:** run view gate panel; Inbox card (new `workflow` kind or approval kind on the orchestrator session; Inbox kinds are a closed set today: approval, comment, unread, automation, `web/src/pages/InboxPage.tsx:189-193`); `/approve/:sessionId/:elicitationId` deep link (`web/src/App.tsx:180`, states loading/pending/recovering/resolved in `web/src/pages/ApprovePage.tsx:1-16`); orchestrator session transcript (approval card); Slack, only for Slack-originated sessions (`integrations/slack/README.md:345-348`); desktop/mobile shells load the same SPA.
- **Gate card content (New content in Reused card):** the gate's name, the outcome buttons (explicit labels, e.g., Approve / Reject / "Choose: A, B"), the handoff that reached it (report, diff summary, evidence results, open findings when arriving at loop limit [D§5.6]), why the run is here (normal path vs at-limit), a note field (stored as a note, never interpreted by a model [DD§5.3.9]). Render via `ApprovalCard` / `ElicitationSchemaForm` (enum → select, boolean, number, text; required fields gate submit, `web/src/components/blocks/ElicitationSchemaForm.tsx:1-21`).
- **Semantics the UI must respect:** a gate is never resolved by timeout (gate timeouts remind and escalate, never auto-approve [DD§11]); "Decline"/"Cancel" actions of the generic card (`SubmitApprovalFn` actions `accept | decline | cancel`, `web/src/components/blocks/ApprovalCard.tsx:134-145`) must map to an explicit gate outcome or be hidden (§7 Q-02); answering an earlier gate visit in a loop is rejected with "This approval is no longer current" [DD§6.2].
- **Who may answer:** today anyone with edit level on the session can resolve an elicitation (`ELICITATION_RESOLVE_LEVEL = LEVEL_EDIT`, `omnigent/server/routes/sessions/routes_elicitations.py:55-60`); the code comment notes that raising it to owner "needs a 'waiting for the owner' UI state first". For individuals this is the owner; for teams it is open (§7 Q-03).
- **Phone:** works only while the app is in the foreground. iOS and Android shells provide "foreground local notifications" and explicitly no APNs/background polling (`web/ios/README.md:17-22`; `web/android/README.md:33-37`); browser notifications are page-scoped (`web/src/lib/browserNotifications.ts:8-10`); no VAPID/push code exists (grep for `VAPID|pushManager|PushSubscription|firebase|registerForRemoteNotifications` across `web/src`, `web/ios`, `web/android`, `omnigent` returns nothing). The MVP must say so in the UI ("Coral notifies you while the app is open") and offer an external channel later (§7 Q-05).
- **`ask_user`:** orchestrator-only question outside gates [D§7.2]; rendered as an elicitation form on the orchestrator session; free text allowed (unlike gate outcomes). Step agents can also raise their own prompts (policy ASKs, `AskUserQuestion` in `claude-sdk`, native permission prompts, F37/F38a), which Draft 4 does not model (§8 D14); they must appear in the run view as "Step waiting on you".
- **Exits:** run resumes; run view shows the answer, who answered, from which device, and the note in the run log.

### (h) Steer: talk to the orchestrator, type into an agent session, take over and hand back

- **Talk to the orchestrator:** composer on the orchestrator conversation in the run view [D§13]. Expectation-setting: steering reliability differs by mode (claude-sdk buffers mid-turn input to a follow-up turn, F33; Codex uses `turn/steer`; claude-native pastes into the TUI) [DD§10.2]. Show "will be read after the current turn" vs "delivered now".
- **Type into an agent session:** open any roster chip → session composer [D§13]. The engine must not nudge or count user-initiated turns [DD§6.4, DD§8.10]. UI: a "You are typing into a run-owned step session" notice.
- **Take over:** button on a running step → confirm dialog ("Coral stops reacting to this step until you hand back: no reminders, no refresh, no auto-advance") → step state "Taken over by you" on the diagram [D§13; DD§6.2 `taken_over(by)`]. Omnigent has no such state (F47) → **New**.
- **Hand back:** button → Coral recomputes the workspace fingerprint and evaluates "done when" ("On hand back, 'done when' is still checked" [D§13]); user edits are recorded as made by the user [DD§8.10]. Outcomes: evidence passes → step closes; fails → step continues with the agents with feedback, or the user is told what is missing.
- **Open:** can the user submit the handoff themselves (report text, label) during take-over? Not specified (§7 Q-13).

### (i) Pauses and recovery

The run status model needs one pause reason at a time with a clear "what happens next" and actions. Pause reasons from [DD§6.2]: gate, budget, plan limit, rejected-call limit, infra, liveness, user; plus step-level stall on an approval prompt (R7) and auth failure ([DD§6.7] `auth`).

| Pause | Trigger | What the user sees (proposed copy) | Actions | Source |
|---|---|---|---|---|
| Plan limit | Claude/ChatGPT plan window exhausted | "Paused until Thu 09:00 (your Claude weekly limit resets). Coral resumes automatically." Show resume time, not silence | Resume now (retries), Cancel, (open) switch to API key for the rest of the run? | [D§7.8, D§10]; [DD§12] "Weekly windows can be days away, so show the user the resume time"; S24 |
| Infra loss | Runner/host lost | "Your machine went offline. The *Fix* step will restart from its last handoff when it returns." | Reconnect (reuse reconnect affordance, `feature-map/sessions.md` `reconnect`), Restart step now, Cancel | [D§7.8]; [DD§6.7] `infra.runner_lost` (host held up to 72 h) |
| Budget reached | Run or step limit | "Paused: this run reached its $X budget (estimate)." | Raise budget and resume, Cancel | [D§10]; engine-owned (F42) |
| Rejected calls | 3 rejected calls in a row (default) | "Paused: *Review* agent tried an illegal action 3 times: chose arrow *merge* which does not exist here." | Open session, Steer, Retry step, Cancel | [D§7.3] |
| Liveness | A join waits on an arrow that can never arrive | "Paused: *Summarize* is waiting for *Fix*, which can no longer run." | Edit and Apply to this run, Cancel | [DD§5.3.7] |
| Watchdog | Orchestrator undecided at a node | Reminder once, then alert: "The orchestrator hasn't decided at *Review outcome* for 20 min." | Talk to orchestrator, Choose for it? (open), Cancel | [D§7.3]; default time open [D§20 Q3] |
| Overdue | Step/run exceeds expected duration × factor | Alert with steer / extend / cancel | Steer, Extend, Cancel | [D§7.3] |
| Step stalled on approval | A step agent's own prompt (policy ASK, or native hook outage that fails to ASK) | "*Fix* is waiting for your approval: allow `npm install`?" | Approve/deny in place | F38a, R7 |
| Auth | Login expired / org not allowed | "Claude sign-in expired on this host." Never switches accounts | Re-login, Cancel | [D§7.8]; [DD§6.7] |
| Failure path (default) | Attempts exhausted, or agent `blocked` | "*Fix* couldn't satisfy 'done when' in 3 attempts. Missing: lint after last change." | Retry step (fresh attempts), Skip to at-limit route? (open), Take over, Cancel | [D§5.1] default "pause and ask"; `blocked` [DD§5.4] |
| User | User pressed Pause | "Paused by you" | Resume | [DD§6.2] |

Resume / retry / cancel semantics required:

- **Resume** re-enters on the pinned version [DD§6.8].
- **Retry step** starts fresh attempts in a new session from the incoming handoff; worktree reset to the step's start commit [DD§6.7, DD§13] (user-visible warning: "uncommitted changes in this step will be discarded").
- **Cancel** interrupts sessions, stops new activations, keeps commits already made [DD§5.3.6]; a cancelled run must never send again (Omnigent stop is non-sticky [DD§8.1]).

### (j) Amend a running run ("Apply to this run")

- **Entry:** run view → "Apply edit…"; editor → after saving a new version while runs of the old version are active: banner "2 runs use v3. Apply this change to a run?"
- **Flow:** pick run → Coral shows which steps the change affects; only not-yet-started steps can change [D§7.7]; validator refuses changes incompatible with active steps (Camunda-style mapping: active activations must map to unchanged nodes, counts preserved, counters carried by stable id, simulate from current state [DD§6.8]); the user enters a reason; Apply. Run log records who and why [D§7.7].
- **States:** compatible; incompatible with explanation per step; applying; applied (diagram shows derived version "v3+a1"); race lost ("A step started while you were editing; review again").
- **Permission:** owner today; teams later (open [D§20 Q4]; DD recommends manage level [DD§20.1]).

### (k) Manage agent profiles

- **Entry:** sidebar "Agent Profiles" (`/profiles`, provisional [UI§5.1, §8.3]); profile picker in the step inspector → "Manage profiles"; Settings → Customize → Custom agents (existing, `/settings/custom-agents`, `feature-map/custom-agents.md`).
- **What a profile is:** agent YAML (bundle) + description + default rules + expected capabilities [D§5.4]. Mapping: description = existing `description`; default rules = `guardrails`; capabilities = `params` or a new field (unknown top-level keys are silently dropped) [DD§8.4, F39].
- **Create:** reuse the existing create form fields (Name, Description, Harness, Model, Instructions, MCP servers; `web/src/pages/settings/CustomAgentConfigForm.tsx:174-219, 354-518`) and add Coral fields: default rules (plain language, Required/Guidance), expected capabilities (derived from harness capability matrix, read-only with override), auth mode (API key vs subscription; S13), canvas description.
- **Edit:** existing PATCH with ETag (`omnigent/server/routes/builtin_agents.py:386-441`). **Conflict:** edits and reinstalls reach running sessions on their next turn (`designs/REUSABLE_USER_AGENTS.md:112` decision 6; `designs/CUSTOM_AGENTS_SETTINGS_UI.md:102-106`). Coral must pin revisions per workflow version [DD§6.8, R13]. UX: profile page lists "Used by: 3 workflows (pinned to rev 4), 1 running run"; saving says "Running runs keep revision 4; new runs and new workflow versions use revision 5" — which requires the pin mechanism to exist first.
- **Pin revision:** the bundle location is content-addressed (`<own id>/<sha256>`, `REUSABLE_USER_AGENTS.md` §4; the ETag includes `bundle_location`, `builtin_agents.py:230`). A pin can be `(agent_id, bundle_location)`. Whether old blobs remain retrievable after an edit: no deletion of prior blobs found in `builtin_agents.py` or the agent store (grep), but retention is **UNVERIFIED**.
- **Bind on a step:** roster picker shows profiles with harness, model, capability badges and which of the workflow's Required rules each can enforce (V9 inline).
- **Seeded profiles:** default orchestrator and starter profiles ship as seeded or extra built-in agents [DD§8.4] (`omnigent/server/seeded_agents.py`, per DD, not re-opened). The orchestrator profile must have no write/edit/shell tools, enforced by policy [DD§9.3 item 6].
- **States:** see §5.5.

### (l) Run history and improvement suggestions

- **Run history:** Runs tab (all workflows) and a workflow's runs list, modelled on `TaskDetailPage`'s run history (loading "Loading runs…", error "Couldn't load run history.", empty "No runs yet.", per-run status icon, cost note "Session cost is each session's current recorded total" — `web/src/pages/TaskDetailPage.tsx:537-563`). Columns: status, started, duration, version, path summary (e.g., "Review ×2 → approved → gate: approved"), cost estimate, who started it.
- **Suggestions:** an analysis workflow reads finished run logs and proposes concrete edits with evidence (evidence that usually fails first try; loops hitting limits; growing costs; gates always approved unchanged; orchestrator decisions later reversed) [D§14]; also always-pass evidence and test/config edits in non-test steps [DD§19 phase 8]. UX: suggestions list per workflow, each with evidence links into runs and a proposed YAML diff; Accept creates a new version (or a branch/PR in the repo); Reject records a reason. Never weaken evidence, rules, verifiers or gates [D§App].
- **Open:** where "orchestrator decisions that people later reverse" is detected (a later human gate rejecting? an amendment?) is undefined (§7 Q-26).

### (m) Share via git repositories and templates

- **Now:** workflows are files in `.coral/workflows/` [D§12]; sharing = commit and push; a teammate opens the repo and the workflow appears in their list. Templates are starting points; blocks (saved groups) and profiles are reusable [D§15].
- **Install from git:** profiles can be installed from GitHub (`omnigent agent` GitHub install per DD §8.4, not re-opened); workflows/templates import from a git URL is not specified (§7 Q-27).
- **Later:** session sharing for runs [D§13], marketplace [D§15].
- **Product constraint:** a shared workflow references profiles; a teammate needs the same profiles (pinned revision) installed. Profile resolution on another machine must fail clearly with "Install profile X" (V10).

---

## 3. Product capability inventory

### 3.1 Shared platform capabilities (build once, used by many PCs)

| ID | Platform capability | Used by | Key sources |
|---|---|---|---|
| PL-A | **Engine core**: compiled graph, pure reducer, durable run state, append-only run log, signals, timers, reconciler, pause reasons | PC-12, 13, 14, 16-30 | [D§7]; [DD§6, DD§7] |
| PL-B | **Session facade + engine tools** (`submit_handoff`, `choose_arrow`, `assign_agents`, `message_agent`, `ask_user`) | PC-14, 16-24, 26 | [D§7.1, D§7.2]; [DD§8.1, DD§8.6]; S3-S12 |
| PL-C | **Run stream API** (snapshot + live tail with cursor) and run REST (list, get, pause, resume, cancel, retry, take-over, hand-back, amend) | PC-15, 16, 17, 19, 21, 24, 28 | [DD§14.2] |
| PL-D | **Gate/elicitation bridge**: durable gate rows published as elicitations on the orchestrator session; verdict callback; re-publish after restart | PC-19, 20, 21 | [DD§11]; S5, S6 |
| PL-E | **Translation service**: engine-owned model session translating done-when, rules, reactions; dry-run; invalidation | PC-06, 26, 29, 31 | [DD§10.7] |
| PL-F | **Capability registry**: per-mode capability fields + bench probes, exposed to web | PC-03, 05, 07, 08, 29, 35 | [D§9]; [DD§10.2-10.3]; S22, S23 |
| PL-G | **Workflow file I/O + versions**: read/write `.coral/workflows/*.yaml` and layout on a host, content-hash versions, server-side library copy | PC-04, 09, 10, 11, 28, 32, 34 | [D§12]; [DD§14.4] (host fs API is list-only: `omnigent/server/routes/hosts.py:1599-1625`) |
| PL-H | **Notification fan-out**: inbox `workflow` kind, browser/desktop notification while open, suppression of per-step turn-end notifications, external channel later | PC-19, 20, 21, 24 | [DD§11]; S36, S37 |
| PL-I | **Workspace service**: run worktree/branch, per-agent worktrees, merges, fingerprints, Coral-run checks, setup commands, checkpoint pushes | PC-13, 23, 26, 27, 30 | [D§11, D§5.3]; [DD§9.2, DD§13]; S28, S40 |
| PL-J | **Usage aggregator**: run tree spend, per-step usage medians, estimates, budgets, plan utilization | PC-13, 15, 25, 31 | [D§10]; [DD§12] |

### 3.2 Product capabilities (PC-01 .. PC-38)

Scope keys: **MVP** = smallest lovable Coral (§9.1); **M1..M7** = milestone in §9.2; **Later** = after M7.

#### PC-01 Coral brand skin  [M0, MVP]
- **Problem:** Users must recognise Coral as its own product; the Omnigent name and mascot belong to Databricks [D§16]; Apache-2.0 §6 withholds product names [DD§16.3].
- **Experience:** cream ground, Clay Score accents, terracotta primary (mustard in dark), Newsreader only for wordmark/hero/desk titles/connect, organic circular mark + serif "Coral", soft washes, dock icon on cream plate [UI§1-§4, §7, §8.1].
- **Frontend:** **Modify** `web/src/lib/branding.ts:4-5` defaults (`DEFAULT_APP_NAME`, `DEFAULT_HEADING`); **Modify** default palette slot `omni` (`web/src/lib/themePalette.ts:47, 217-218`, label "Omnigent" → "Coral") and regenerate generated CSS; **Modify** `--font-heading` (`web/src/index.css:45` = `var(--font-sans)` today) to Newsreader; **New** `CoralLogo` as the default fallback in `BrandLogo` (`web/src/components/BrandLogo.tsx`); **Modify** sidebar brand row (`web/src/shell/Sidebar.tsx:1259-1278`: wordmark image or `app_name` span) to mark + serif wordmark; **Modify** hero (`web/src/shell/NewChatDialog.tsx:7011-7047`) to side-by-side mark + heading; **Modify** Electron `productName` (`web/electron/package.json:3, 43`) and connect page (`web/electron/setup/index.html:6`); **Replace** icons in `web/electron/icons/`; add `@fontsource/newsreader` (dependency: follow repo mirror rules in CLAUDE.md).
- **Backend:** none required; operator `branding:` block still overrides (`deploy/README.md:670-690`).
- **Depends on:** none (parallel track).
- **Done when:** checklist [UI§11] "Firm" items all pass in light and dark; no Omnigent starfish or pink in default theme; operator branding still overrides name/heading/logo; "Powered by" decision made (§7 Q-33).
- **Scope:** MVP.

#### PC-02 Desk chrome (`CoralPageHeader`)  [M0, MVP]
- **Problem:** Desk pages must read as one product.
- **Experience:** full-width header band, accent rail of five dots, Newsreader ~24px title, ~13px subcopy, actions right [UI§5.2, §6].
- **Frontend:** **New** `CoralPageHeader` component (UI doc's path `web/src/components/concerto/CoralPageHeader.tsx` does not exist; choose `web/src/components/coral/` and `--coral-*` tokens, the UI doc allows the rename [UI§2.1]); **Modify** Inbox header (`web/src/pages/InboxPage.tsx:874`, `text-2xl font-normal`), Automations header (`web/src/pages/TasksPage.tsx:237-264`, `text-2xl font-semibold` + info button + subcopy + New automation), new Workflows and Profiles pages. TaskDetailPage (`:353`), Canvas (`CanvasPage.tsx:592`) and Settings (`SettingsPage.tsx:415`) are not in the UI doc's list; decide (§7 Q-34).
- **Backend:** none.
- **Done when:** Inbox, Automations, Workflows, Agent Profiles share the header; sidebar labels equal page titles [UI§5.1].
- **Scope:** MVP.

#### PC-03 Model access and auth onboarding  [MVP]
- **Problem:** Users have subscriptions or API keys; terms constrain which mode may use which ([D§17 risk 1]; [DD§16]).
- **Experience:** a clear choice at first run and per profile: "API key (recommended for workflows)" vs "Claude subscription via Claude Code (some guarantees weaker)". Never switch accounts automatically [D§7.8].
- **Frontend:** **Extend** Settings → Harnesses and first-run setup; per-profile auth field; badge on profiles showing auth mode; warnings in run preflight.
- **Backend:** S13 (claude-sdk auth for run-owned sessions: prefer API key / `apiKeyHelper`, refuse or warn on subscription OAuth); existing `executor.auth: {type: api_key}` and server `auth:` block (per DD F48).
- **Depends on:** PC-07, PL-F.
- **Done when:** a run-owned `claude-sdk` session never starts on subscription OAuth without an explicit, recorded user choice; subscription users can run workflows on `claude-native`; roster chips read "Claude", not "Claude Code" [DD§16.1].
- **Scope:** MVP (needs legal answer, §7 Q-06).

#### PC-04 Workflow library and storage  [M1, MVP]
- **Problem:** Users need to find, open and keep workflows.
- **Experience:** Workflows desk "Your workflows" list (name, repo, last edited, version, last run status, saved-test status); files live in `.coral/workflows/` with a separate layout file [D§12].
- **Frontend:** **New** list page (pattern: `TasksPage` search + filters + tabs, `web/src/pages/TasksPage.tsx:229-330`).
- **Backend:** **New** endpoints to read/write workflow files on a host (none exist: host filesystem API lists directories only, `hosts.py:1599-1625`, creates directories at `:1729`); **New** server-side index of known workflows and versions (`coral_workflow_versions` [DD§7.2]); content-hash versions [DD§6.8].
- **Depends on:** PL-G.
- **Done when:** a user can list workflows across their repos, open one, save it back to the repo file, and see it after a host restart; a host-offline state is explicit.
- **Scope:** MVP. Workflows not tied to a repo: open (§7 Q-10).

#### PC-05 Validation and explanations  [M1, MVP]
- **Problem:** Diagrams can deadlock, loop forever or promise what modes can't enforce.
- **Experience:** errors on the affected box with plain explanations [D§12]; derived join type shown [DD§5.3.1].
- **Frontend:** **New** problem list + on-box markers + YAML range mapping.
- **Backend:** V1-V13 [DD§5.5] incl. capability checks (V9) and profile readiness (V10).
- **Depends on:** PL-A (compiler), PL-F.
- **Done when:** the literal Draft 3 join rule deadlock and every V-rule produce a box-anchored message; saving an invalid workflow is allowed as a draft but running it is not (proposed; §7 Q-11).
- **Scope:** MVP (V1-V7, V10-V13); V8-V9 with PC-29.

#### PC-06 Plain-language translation confirmation  [MVP for done-when; M3 for rules]
- **Problem:** Plain language must become something machines check, and the author must agree with the reading [D§6.1, D§9; risk 4].
- **Experience:** confirmation sheet per item: text → plain-words reading → technical summary → dry-run → Confirm / Edit / Make guidance; stored next to the text in YAML [D§12].
- **Frontend:** **New** sheet; pending/failed/stale states; badge "needs re-confirmation".
- **Backend:** PL-E; invalidation rules [DD§10.7]; translations target only registered handlers [DD§8.5].
- **Depends on:** PL-E, PC-26, PC-29.
- **Done when:** no run starts with an unconfirmed translation; changing a profile's mode marks dependent translations stale.
- **Scope:** MVP for "done when"; Required rules at M3.

#### PC-07 Agent profiles  [MVP minimal; M3 full]
- **Problem:** Steps should pick a reusable agent rather than hard-code harness/model/instructions [UI§8.3].
- **Experience:** Profiles desk + picker on steps; profile = agent YAML + description + default rules + expected capabilities [D§5.4].
- **Frontend:** **New** `/profiles` list (lens over `GET /v1/agents` and `?scope=user`, `builtin_agents.py:443`); detail with Coral fields; **Reuse** the Settings create/edit form (`CustomAgentConfigForm.tsx`) for core config; **New** roster picker.
- **Backend:** **Reuse** install/list/detail/config/PATCH/delete (`builtin_agents.py:369-581`); **New** revision pinning per workflow version; **Extend** spec with capabilities in `params` or a new field [DD§8.4]; seeded starter profiles and default orchestrator.
- **Depends on:** PL-F, PC-03.
- **Done when:** editing a profile never changes a running run; a workflow version records each profile's revision; a profile shows which workflows use it.
- **Scope:** MVP = seeded profiles + bind existing custom agents + automatic pinning; M3 = Profiles desk with Coral fields and default rules.

#### PC-08 Promise labels and "What Coral guarantees"  [MVP]
- **Problem:** Users must see what is held and how strongly (§1.4).
- **Experience:** badges on boxes, arrows, rules, evidence; per-workflow and per-run guarantees panel.
- **Frontend:** **New** badge component and panel.
- **Backend:** label computation from compiled graph × capability matrix [DD§10.2].
- **Depends on:** PL-F, PC-05.
- **Done when:** every label shown can be traced to a mechanism; no Enforced label on a mechanism listed in §8 D1 until its replacement ships.
- **Scope:** MVP.

#### PC-09 Templates gallery  [M1, MVP]
- **Problem:** Most users start from templates [D§12].
- **Experience:** Templates tab + suggestions; "Use template" dialog with parameters and command confirmation.
- **Frontend:** **New**, pattern **Reuse** of Automations gallery (client constants in `web/src/components/scheduled/automationTemplates.ts:1-11`; tabs at `TasksPage.tsx:307-312`).
- **Backend:** templates shipped as YAML (server-bundled) with pre-confirmed translations and saved simulations.
- **Depends on:** PC-04, PC-06, PC-12.
- **Done when:** a new user can go from gallery to a saved, simulated workflow in a repo in under five minutes (proposed metric).
- **Scope:** MVP with one or two templates (§9.1).

#### PC-10 Canvas editor  [M4; read-only diagram in M1]
- **Problem:** Authoring by drawing [UI§8.2 "Lucid-like directed graph"].
- **Experience:** palette, drag, connect, inspector, auto-layout, undo/redo; two-way with YAML [D§12].
- **Frontend:** **New** under `web/src/workflows/` (`web/src/canvas/` is taken, F43) on `@xyflow/react` (already a dependency; Omnigent's canvas has one node type and `nodesConnectable={false}`, `web/src/pages/CanvasPage.tsx:84, 668`); thin adapter for the v13 risk [DD§14.4]; ELK vs dagre licensing decision [DD§14.4].
- **Backend:** PL-G (YAML AST patching may be client-side with the `yaml` library).
- **Depends on:** PC-04, PC-05, PC-11.
- **Done when:** every edit round-trips YAML↔canvas without losing comments or confirmed translations; layout file keyed by stable ids.
- **Scope:** read-only rendering at M1 (needed by Simulate and run view); editing at M4.

#### PC-11 YAML editor pane  [M1, MVP]
- **Frontend:** **Reuse** Monaco (`web/src/shell/MonacoCodeEditor.tsx`, per DD §14.3) with schema hints and validator ranges.
- **Done when:** a power user can author an entire workflow in YAML with live validation and diagram preview.
- **Scope:** MVP (it is the primary authoring path until PC-10 editing).

#### PC-12 Simulate and saved test cases  [M1, MVP]
- **Problem:** Prove routing for free [D§8].
- **Experience:** journey (d).
- **Frontend:** **New** simulate overlay and script panel.
- **Backend:** same reducer with stub effects [DD§15.1]; saved cases; exhaustive mode.
- **Depends on:** PL-A, PC-10 (read-only), PC-05.
- **Done when:** the design's example and every template can be simulated through every branch; saved cases re-run on file change and show pass/fail on the list.
- **Scope:** MVP.

#### PC-13 Start-run dialog and preflight  [MVP]
- **Experience:** journey (e).
- **Frontend:** **New** dialog; **Reuse** workspace/repository/worktree controls from `CreateScheduledTaskDialog.tsx:1102-1430`.
- **Backend:** `coral_runs` with `start_key` idempotency [DD§7.2]; preflight V10; estimate via PL-J; worktree creation via `create_worktree_on_host` (per DD §8.1).
- **Depends on:** PC-04, PC-07, PC-12, PC-25, PL-I.
- **Done when:** double-submit starts one run; every preflight failure names the fix.
- **Scope:** MVP (local host only; sandbox later, S28).

#### PC-14 Run lifecycle controls  [MVP]
- **Experience:** Pause, Resume, Cancel, Retry step; status model per [DD§6.2].
- **Backend:** PL-A, PL-C.
- **Done when:** a cancelled run never starts another turn; resume re-enters on the pinned version; a server restart mid-run does not lose state (phase 1 fault tests [D§18]).
- **Scope:** MVP.

#### PC-15 Runs list and history  [MVP]
- **Experience:** journey (l) first half.
- **Frontend:** **New**, pattern **Reuse** of `TaskDetailPage` run history states.
- **Backend:** run list API with pagination (repo DB rules), per-run cost from PL-J.
- **Done when:** the user can find any run, see status, path summary, cost estimate, duration and open the run view.
- **Scope:** MVP.

#### PC-16 Live run view  [MVP basic; M4 full]
- **Experience:** journey (f).
- **Frontend:** **New** run view; **Reuse** `SubagentsGraphView` patterns (status-tinted nodes, animated edges, `web/src/shell/SubagentsGraphView.tsx:128, 248-250`), `SessionStateBadge`, `SideChatPane fullSession`.
- **Backend:** PL-C run stream; S35 watch-set union; skipped-path logging for "why not".
- **Depends on:** PL-A, PL-C, PC-10 (read-only).
- **Done when:** a user can answer "where is my run, why did it go this way, what passed, what is it waiting on" without opening a transcript.
- **Scope:** MVP basic (path, statuses, decisions with reasons, evidence, timeline, focused session); M4 (why-not arrows, stitched orchestrator, take-over markers).

#### PC-17 Orchestrator conversation (stitched) and node conversations  [MVP basic; M3 stitching]
- **Experience:** one continuous orchestrator conversation with a refresh marker [D§7.5]; node conversations drawn at orchestrator nodes [D§5.2].
- **Frontend:** **New** stitched transcript view walking the predecessor chain (F46); today `session.superseded` redirect is followed by viewers (per DD §8.9).
- **Backend:** S25 (`SupersessionReason` "refresh", request-free fork-continue).
- **Done when:** after a refresh, the user scrolls one conversation and sees a marker.
- **Scope:** MVP shows the current orchestrator session only (no refresh in MVP); stitching with PC-24's refresh at M3.

#### PC-18 Per-agent sessions inside a run  [MVP]
- **Experience:** roster chips open sessions; sessions are ordinary Omnigent sessions [D§4.1, D§13].
- **Frontend:** **Reuse** chat transcript/composer; **New** "run-owned" banner on session header linking back to the run; **Modify** sidebar placement (children are filtered from the sidebar today, per DD §8.2; decision on topology §7 Q-19).
- **Backend:** session topology decision (children of the orchestrator recommended [DD§8.2]); `coral.*` labels reserved (S26).
- **Done when:** from any step session, the user can get back to the run; generic actions on run-owned sessions (stop, archive, delete, fork, `/clear`, share) have defined outcomes (§7 Q-20).
- **Scope:** MVP.

#### PC-19 Human gates  [MVP]
- **Experience:** journey (g).
- **Frontend:** **Reuse** `ApprovalCard`/`ElicitationSchemaForm`/`ApprovePage`; **Extend** with gate context (handoff, evidence, why-here) and explicit outcome mapping.
- **Backend:** PL-D (durable `coral_gate_visits`, compare-and-set resolution, re-publish after restart [DD§11]); approver authority check.
- **Depends on:** PL-A, PL-D, PC-21.
- **Done when:** the same answer from two devices advances once; a server restart re-shows open gates; a stale answer is refused with an explanation; no gate ever resolves by timeout.
- **Scope:** MVP.

#### PC-20 `ask_user`  [MVP]
- **Experience:** orchestrator question with optional choices; free text answer.
- **Backend:** engine tool [D§7.2]; elicitation on orchestrator session.
- **Done when:** the question appears in run view and Inbox and the answer is logged.
- **Scope:** MVP.

#### PC-21 Run notifications and Inbox  [MVP in-app; M3 external]
- **Problem:** Unattended gates and pauses must reach the user.
- **Experience:** Inbox `workflow` kind (gate waiting, run paused, run failed, run completed, overdue); browser/desktop notifications while open; per-step turn-end notifications suppressed (S36) and replaced by run-level ones.
- **Frontend:** **Extend** Inbox (kinds at `InboxPage.tsx:189-193`; filters all/unread/awaiting at `:170-181`); **Modify** `useIdleNotifications` (S36).
- **Backend:** run inbox feed (pattern: automation inbox feed, per DD §11); later an external connector (email/Slack/push) [DD§11 (a)-(c)].
- **Done when:** every pause reason and open gate appears in Inbox with a deep link; a run with 6 step sessions produces run-level notifications, not 6 turn-end pings.
- **Scope:** MVP in-app with an explicit "needs the app open" note; external channel M3 (§7 Q-05).

#### PC-22 Steering  [MVP]
- **Experience:** journey (h) first two bullets; mode-aware delivery hints.
- **Backend:** user-turn vs engine-turn distinction [DD§6.4]; S4 event dispatch.
- **Done when:** typing into a step session never triggers a "you ended your turn without a handoff" nudge.
- **Scope:** MVP.

#### PC-23 Take over and hand back  [M4]
- **Experience:** journey (h) last bullets.
- **Backend:** `taken_over(by)` state; fingerprint on hand-back (PL-I, S40).
- **Done when:** while taken over, the run shows no reminders/refresh/auto-advance for that step; hand-back evaluates "done when" with user edits counted.
- **Scope:** M4 (needs evidence fingerprints first).

#### PC-24 Pauses, alerts and recovery  [MVP core; M3 refresh]
- **Experience:** journey (i); also session refresh at the context threshold [D§7.5].
- **Backend:** error taxonomy [DD§6.7]; S24 usage-limit signal; timers; liveness check.
- **Done when:** every pause has reason text, a resume condition (time or action) and actions; plan-limit pauses show the reset time.
- **Scope:** MVP (plan limit, infra, budget, rejected calls, liveness, watchdog, failure path, user); M3 (session refresh, overdue factor UI).

#### PC-25 Budgets and cost  [MVP basic]
- **Experience:** estimate before start; run budget; step budgets; spend so far; labels "estimate" [DD§12].
- **Backend:** engine-owned run pause (not `cost_budget` alone, F42); tree spend sums; `cost_budget`/`subagent_cost_budget` as per-session backstops.
- **Done when:** reaching the run budget pauses the run and asks; plan users see utilization or tokens.
- **Scope:** MVP run budget; step budgets M6.

#### PC-26 Evidence and Coral-run checks  [MVP basic; M3 full]
- **Experience:** done-when results with missing-item messages [D§6.1]; repository command patterns confirmed once [D§6.1]; Coral-run checks off by default, on in code templates [D§6.2]; verifier opt-in [D§10].
- **Backend:** command observations, fingerprints (S40), patterns; Coral-controlled checkout for pinned commands [DD§9.3]; structured test results and integrity diff [DD§9.3].
- **Done when:** "printing 'tests passed' does not count" holds [D§6.1]; evidence explains exactly which command ran after which change.
- **Scope:** MVP: done-when for tests/lint/format on `claude-sdk` (best evidence source [DD§9.1]); M3: Coral-run checks, verifier, integrity diff.

#### PC-27 Workspaces, branches and merge outcomes  [MVP single-coder; M5 multi-coder]
- **Experience:** each run gets a worktree and branch [D§11]; parallel coders get own worktrees and merges at step close/join; conflicts go to the orchestrator then the user [D§5.3]; end-of-run result: a branch (and optionally a PR) the user can inspect.
- **Backend:** PL-I; branch naming scheme (`coral/<run>/base`, `coral/<run>/agent-<n>` [DD§13]); setup command per repo; checkpoint pushes for sandboxes [DD§13].
- **Done when:** the user can open the run's branch/diff from the run view; a conflict shows the files and who resolves.
- **Scope:** MVP single-coder steps; M5 merges.

#### PC-28 Amend a running run  [M6]
- **Experience:** journey (j).
- **Backend:** derived versions; migration rules [DD§6.8]; `coral_amendments`.
- **Scope:** M6 (Draft 4 phase 7).

#### PC-29 Rules and reactions authoring  [M3]
- **Experience:** rules on workflow/group/step/profile; inner stricter only; Required vs Guidance; reactions "when X do Y" [D§9].
- **Backend:** translation targets [DD§10.1]; protected policies (S26) so a user editing a step session's policies cannot silently remove an Enforced rule [DD§10.6].
- **Done when:** every Required rule has a mechanism and label per mode; a reaction "if this step runs over an hour, tell me" produces an alert.
- **Scope:** M3.

#### PC-30 Structure: groups, blocks, repeat-for-each, parallel  [M5]
- **Experience:** groups with inherited rules; saved blocks; repeat-for-each badges; parallel split/join with live messaging [D§5.2, D§3 "Communication"].
- **Backend:** repeat-for-each contract (order, empty list, per-item failure, concurrency) [DD§5.3.5]; region cancellation [DD§5.3.6]; run-level activation cap [DD§5.3.3].
- **Scope:** M5.

#### PC-31 Improvement suggestions  [M7]
- **Experience:** journey (l) second half.
- **Scope:** M7 (Draft 4 phase 8).

#### PC-32 Sharing via git and templates; run sharing  [M7; run sharing Later]
- **Experience:** journey (m).
- **Backend:** import workflow/template from git URL (New); profile install from GitHub (exists per DD).
- **Scope:** git sharing works implicitly from MVP (files in repo); explicit import M7; run sharing Later.

#### PC-33 Run log, audit and export  [MVP view; M7 export]
- **Experience:** timeline in run view; export run log (JSON/Markdown) for audit.
- **Scope:** MVP view; export M7.

#### PC-34 Workflow versions and diff  [M3]
- **Experience:** versions list, which runs used which version, diff between versions (YAML and diagram).
- **Scope:** M3 (needed before amendments).

#### PC-35 Codex support  [M6]
- **Problem:** cross-vendor reviewers [D§5.6]; Codex terms ([DD§16.2]).
- **Backend:** S2, S15, S16 (codex-native first) or S18-S20 (headless).
- **Scope:** M6 (DD recommends after v1 [DD§20.1 Q1]).

#### PC-36 Elephant-Goldfish showcase template  [M7]
- **Needs:** persistent session across loop passes for one roster member; per-member input scoping; typed resolutions; ESCALATE → human gate [DD§15.3].
- **Scope:** M7.

#### PC-37 Workflows introduction and empty states  [MVP]
- **Experience:** first-visit walkthrough (pattern `feature-map/automations-introduction.md`), examples, info button to reopen.
- **Scope:** MVP.

#### PC-38 Navigation, routes and feature flag  [M0, MVP]
- **Frontend:** **Extend** `web/src/App.tsx:181-256` with lazy routes wrapped in `withPageView` (`:24`) and `FeatureGatedPage feature="workflows"` (`:76`); **Extend** `FeatureKey` (`web/src/lib/capabilities.ts:60-74`); **Extend** sidebar primary nav (`web/src/shell/Sidebar.tsx:1299-1449`) and command palette (`CommandPalette.tsx:195-208`).
- **Backend:** `workflows` feature flag (S33) with a removal review release (R16).
- **Scope:** MVP.

### 3.3 Dependency summary (product view)

```
PC-38 nav/flag ─┬─ PC-01/02 skin+chrome (parallel)
                └─ PC-04 library ── PC-11 YAML ── PC-05 validation ── PC-10 (read-only) ── PC-12 Simulate ── PC-09 templates
PL-A engine ─── PC-12 ── PC-13 start run ── PC-14 lifecycle ── PC-15 runs list
PL-B tools ──── PC-16 run view ── PC-17/18 sessions ── PC-22 steering
PL-D gates ──── PC-19 gates ── PC-20 ask_user ── PC-21 notifications
PL-E translate ─ PC-06 confirm ── PC-26 evidence (MVP basic) ── PC-29 rules (M3)
PL-F caps ───── PC-03 auth ── PC-07 profiles ── PC-08 labels
PL-J usage ──── PC-25 budgets ── PC-13 estimate
PL-I workspace ─ PC-27 branches ── PC-23 take-over (M4) ── PC-30 merges (M5)
PC-34 versions ─ PC-28 amend (M6)
run logs ────── PC-31 suggestions (M7)
```

---

## 4. Information architecture and navigation

### 4.1 Reconciliation

| Topic | UI doc | Design / deep dive | Code today | Recommendation |
|---|---|---|---|---|
| Graph surface name | "State Schema" (provisional; might become Score/Flow/Pipeline/Graph) [UI§5.1, §5.3] | "workflow", "canvas" route "for example `/workflows`" [D§12]; DD routes under `/workflows` [DD§14.1] | `/workflows` unused; `/canvas` is the session board behind the off-by-default `canvas` flag (`App.tsx:194-208`; `feature_flags.py:130-134`) | Route segment **`/workflows`** (fixed now; routes are costly to rename, the UI doc only says the *words* are provisional). Sidebar label + `h1` **"Workflows"** (provisional; keep in sync [UI§5.3]). Do not create `/schemas`. |
| Profiles | "Agent Profiles" at `/profiles` (provisional) [UI§5.1, §8.3] | Profile = agent YAML + 3 additions [D§5.4] | Settings → Customize → Custom agents (`settingsNav.tsx:141`; `/settings/custom-agents`) | **`/profiles`** desk page as a Coral lens over custom agents; configuration editing deep-links to (or embeds) the existing form. Label "Agent Profiles" provisional. |
| Runs | Not in UI doc | Run view [D§13]; DD routes `/workflows/runs/:runId` | Automations has a run history on `/tasks/:taskId` (`App.tsx:209-224`) | Runs live under Workflows: a **Runs** tab and `/workflows/runs/:runId`. No separate sidebar entry in MVP (optional later if usage shows runs are the main object). |
| Inbox | Keep, restyle header [UI§5.1] | Notifications: inbox [D§5.5]; `workflow` kind (S37) | `/inbox`, 4 kinds | **Reuse + Extend** with a workflow kind and the Coral header. |
| Automations | Keep `/tasks`, restyle header [UI§5.1] | Triggers later [D§5.5] | `/tasks`, "Automations" label (`Sidebar.tsx:1368`) | **Reuse** as-is plus header. Later: "Run a workflow" as an automation action, not a second scheduler (§7 Q-25). |
| Node taxonomy | Phase / Gate / Note / Orchestrator (prototype guesses) [UI§8.2, §8.4] | Start, End, Work step, Orchestrator node, Human gate, Group; hidden Wait, Sub-workflow [D§5.2] | n/a | **Design wins.** Map accents: Work step = forest, Human gate = mustard, Orchestrator node = clay, Group = sage outline, Start/End = ink. "Note" becomes a non-semantic canvas annotation (optional, Later). |
| Code location | `web/src/components/concerto/…`, `--concerto-*` tokens [UI§2.1, §10] | `web/src/workflows/` [DD§4.2, §14.1] | Neither exists | `web/src/workflows/` for product pages; `web/src/components/coral/` for brand components; `--coral-*` tokens. |

### 4.2 Proposed route map

All routes inside `<Route element={<AppShell />}>` (`App.tsx:181`), each wrapped in `withPageView` and `FeatureGatedPage feature="workflows"`, prefixed by `${prefix}` for embedded mounts.

| Route | Page | Page-view id (proposed) | Notes |
|---|---|---|---|
| `/workflows` | Workflows desk, tab **Your workflows** | `workflows` | Header: "Workflows" + info button + "New workflow" |
| `/workflows?view=runs` | Tab **Runs** (all runs) | `workflows` (tab in query, as Tasks does) | Filters: running / paused / needs you / finished |
| `/workflows?view=templates` | Tab **Templates** | `workflows` | Gallery |
| `/workflows/new` | New workflow (blank or `?template=<id>`) | `workflows.new` | Could be a modal over the desk instead |
| `/workflows/:workflowId` | Workflow detail: editor (canvas/YAML), with side tabs Runs, Tests, Versions | `workflows.editor` | `?mode=simulate`, `?version=<hash>`, `?pane=yaml|canvas|split` |
| `/workflows/runs/:runId` | Run view | `workflows.run` | DD route |
| `/workflows/runs/:runId/c/:conversationId` | Run view with a focused agent session | `workflows.run` | DD route |
| `/profiles` | Agent Profiles list | `profiles` | Lens over `GET /v1/agents` |
| `/profiles/:agentId` | Profile detail (Coral fields; config editing via existing form) | `profiles.detail` | Alternatively `/settings/custom-agents/:id` for config |
| `/approve/:sessionId/:elicitationId` | Existing approval page | existing `approve` | **Reuse** for gate deep links |
| `/inbox`, `/tasks`, `/settings/*`, `/c/:id` | Existing | existing | **Reuse** |

Workflow ids: a workflow lives in a repo file; its URL id must be stable across machines. Proposal: `workflowId` = server index id derived from (owner, repo identity, file path, workflow `id:` key in YAML). Open (§7 Q-10).

### 4.3 Sidebar primary nav (proposed order)

Today (`web/src/shell/Sidebar.tsx`): brand row (`:1259-1277`), New session (`:1299-1342`), Automations (`:1344-1370`), Inbox (`:1371-1409`), Canvas behind flag (`:1411-1421`), extension pages (`:1422-1425`), Usage behind flag (`:1426-1449`).

Proposed: brand row (Coral mark + serif wordmark) → **New session** (keep; general chat stays) → **Workflows** (new; icon lucide `Workflow`, as the prototype used for State Schema [UI§5.1]) → **Inbox** → **Automations** → **Agent Profiles** (new; lucide `UserRound` [UI§5.1]) → Canvas (flag) → extensions → Usage (flag). Active state uses the existing `--sidebar-active` wash [UI§5.1]. Command palette adds "Go to Workflows", "Go to Agent Profiles", "Start a workflow run…".

Open: whether "New session" becomes "New run" or the hero gets a workflow chip (§7 Q-07).

### 4.4 Existing Omnigent surfaces reused unchanged (per [UI§9])

| Surface | Code | Use in Coral |
|---|---|---|
| Chat transcript, composer | `ChatPage`, `SideChatPane fullSession` (`web/src/components/chat/SideChatPane.tsx:166-180`) | Orchestrator and step sessions, steering, typing into a session |
| Approval cards structure | `ApprovalCard` (`web/src/components/blocks/ApprovalCard.tsx:134-145`), `ElicitationSchemaForm` (`:1-21`), `ApprovePage` (`web/src/pages/ApprovePage.tsx:1-16`) | Gates and `ask_user` (content extended, structure unchanged) |
| Sidebar session list / DnD / projects | `Sidebar.tsx` | Orchestrator session row; optionally a "Coral runs" project (pattern: automations default project `DEFAULT_AUTOMATION_PROJECT = "Omnigent Automation"`, `web/src/components/scheduled/CreateScheduledTaskDialog.tsx:96`) |
| Settings IA | `settingsNav.tsx:109-171` | Harness setup, custom agents config, policies; no new settings section required for MVP (an optional "Coral" section for defaults like watchdog time and notification channel later) |
| Density, radii, control sizes | design system | Unchanged |
| Theme picker | `themePalette.ts` | Keep; only the default `omni` slot becomes Coral |
| Inbox structure | `InboxPage.tsx` | Extended with a kind; same cards |
| Automations gallery/modal patterns | `TasksPage.tsx`, `CreateScheduledTaskDialog.tsx` | Templates tab and start-run dialog patterns |
| Run-history template | `TaskDetailPage.tsx:537-563` | Runs list states |

Coral is "a skin + desk chrome + nav additions, not a new component library" [UI§9] for brand work; the workflow editor and run view are the only genuinely new product surfaces.

---

## 5. Loading, streaming, empty, error and offline states

Conventions to reuse: `FeatureGatedPage` spinner while `/v1/info` loads (`App.tsx:76-86`); TaskDetail run history copy ("Loading runs…", "Couldn't load run history.", "No runs yet." `TaskDetailPage.tsx:545-556`); Inbox empty copy by filter (`InboxPage.tsx:170-181`); ApprovePage states loading/pending/recovering/resolved (`ApprovePage.tsx:10-15`); custom agents states "loading, empty, failed requests with retry, and missing agents" (`feature-map/custom-agents.md` `states`).

### 5.1 Workflow editor (canvas + YAML)

| State | Requirement |
|---|---|
| Loading | Skeleton canvas + "Loading workflow from <repo> on <host>…"; YAML pane loads first if smaller |
| Empty (new blank) | Start → one step → End pre-placed, inspector open on the step; CTA "Start from a template instead" |
| Empty canvas (all deleted) | Inline prompt: "Drag a Work step from the palette, or paste YAML" |
| Host offline | Banner: "<host> is offline. Showing the last saved version (read-only)." Save disabled. Requires a server-side copy (§7 Q-10) |
| File missing / moved | "This workflow file no longer exists at `.coral/workflows/x.yaml`" with Locate / Remove from list |
| YAML parse error | Canvas shows last valid graph greyed with "YAML has errors (line N)"; edits on canvas disabled until fixed |
| Validation errors | Problem list with counts; on-box markers; Start run disabled with reason; save allowed as draft (proposed) |
| Translation pending / failed / stale | Per item status chip; Start run blocked until confirmed |
| Unsaved changes | Dirty indicator; leave confirmation |
| External change on disk | "This file changed on disk (git pull?)" → Reload / Keep mine / Compare |
| Saving / saved / save failed | Inline status; failure keeps draft (pattern from custom agents editor) |
| Large graph | Auto-layout progress in a worker; minimap |
| Simulate mode | Clear mode banner and exit; disable editing while simulating (proposed) |
| Mobile | Read-only diagram + YAML viewing; editing not supported in MVP (proposed; §7 Q-30) |

### 5.2 Run list and run view

| State | Run list | Run view |
|---|---|---|
| Loading | "Loading runs…" | Skeleton diagram; header with name once known |
| Empty | "No runs yet. Start one from a workflow." + CTA | n/a |
| Error | "Couldn't load runs." + Retry | "Couldn't load this run." + Retry; 404 → "Run not found or you don't have access" |
| Streaming | Status pills update live | Run stream connected indicator; reconnect resumes from cursor [DD§14.2]; "Reconnecting…" without losing the timeline |
| Stream lost | Polling fallback | Banner "Live updates paused, retrying"; last snapshot stays visible |
| Running | Spinner pill + current step | Active boxes animated; focused transcript streaming |
| Paused (each reason, §2 i) | Pill "Paused: plan limit (resumes Thu 09:00)" | Pause banner with reason, resume condition, actions |
| Needs you | Badge "Needs you" | Gate/ask panel pinned to top |
| Completed / Failed / Cancelled | Final pill + duration + cost | Final path; outcome summary; branch/diff link; "Run again" |
| Many agents | n/a | Status chips for all; one live transcript (SSE caps: `conversationRegistry.ts:64-84`) |
| Phone | List works | Simplified: status, current step, gates, timeline; diagram pinch-zoom read-only |
| Version superseded | Badge "v3 (current is v5)" | Info: "This run follows v3"; "Apply edit…" if allowed |

### 5.3 Gate approval

| State | Requirement |
|---|---|
| Pending | Outcome buttons, context (handoff, evidence, why here), note field |
| Submitting | Buttons disabled; optimistic "Sending…" |
| Accepted | "Approved by you at 14:02 from phone" in card and run log |
| Already resolved elsewhere | "Already answered by <who> from <device>" (compare-and-set) |
| Stale visit | "This approval is from an earlier pass and no longer applies" |
| Run cancelled / finished | "This run is no longer waiting" |
| Not permitted | "Only people with edit access to this run can answer" (§7 Q-03) |
| Delivery uncertain | Reuse ApprovePage "Recovering" pattern |
| Offline | Answer queued? Proposed: no offline queue; show "You're offline" and disable submit |
| Reminder/escalation | Badge "Waiting 3 h"; never auto-resolve |

### 5.4 Simulate

| State | Requirement |
|---|---|
| Needs input | Highlight step and ask for the made-up result |
| Running | Animated path |
| Deadlock / liveness | Highlight the waiting box and the impossible arrow with explanation |
| Limit reached | Mark at-limit route taken |
| Saved test failing | Red badge on workflow list and Tests tab; diff of expected vs actual path |

### 5.5 Profiles

| State | Requirement |
|---|---|
| Loading | Skeleton list |
| Empty (no owned profiles) | Show seeded starter profiles + "Create profile" / "Use an existing custom agent" |
| Error | "Couldn't load profiles." + Retry |
| Missing agent (deleted) | Workflows referencing it show "Profile missing: install or replace" (V10) |
| Server lacks capabilities | Mirror custom agents gating: `agent_install`, `agent_detail`, `agent_config_edit` flags (`feature-map/custom-agents.md` `gating`) |
| In use by runs | "Used by 1 running run (pinned to rev 4)"; editing creates a new revision |
| Editing conflict | ETag 412 → Reload latest (existing behavior, `builtin_agents.py:409-417`) |
| Auth not configured | Badge "Needs API key" or "Uses subscription (claude-native)" |

### 5.6 Start-run dialog

Loading estimate; estimate unavailable; preflight failure per item with fix link; host offline; budget below estimate warning; submitting (idempotent); started → navigate to run view.

---

## 6. Brand and skin as a product capability

### 6.1 Firm (design law) [UI§8.1] and their code touchpoints

| Firm rule | Touchpoint today | Change |
|---|---|---|
| Cream ground `#FEF7F1` + Clay ramp | `themePalette.ts` `omni` slot (`:217-218`) | Replace default palette tokens; label "Coral" |
| Terracotta primary `#864A31`, mustard in dark | same | Replace |
| Newsreader for wordmark + desk titles + hero + connect only | `index.css:45` `--font-heading: var(--font-sans)` | Point to Newsreader; add font dependency |
| Circular organic mark + serif "Coral"; aligned | `Sidebar.tsx:1259-1278` uses `omnigent-wordmark.svg`; `BrandLogo` | New `CoralLogo`; brand row layout per [UI§3.3, §4.2] |
| Dock icon cream plate, mark ~72% | `web/electron/icons/` | Replace assets |
| Shared desk heading chrome | Inbox `:874`, Tasks `:240` | `CoralPageHeader` |
| Soft shell/sidebar washes | shell CSS | Add washes |

### 6.2 Loose (directional) [UI§8.2-8.4]

Graph surface chrome and taxonomy; profile fields and storage; inspector placement; empty states. Product resolves taxonomy and storage (design wins: §4.1; profiles are server agents, not localStorage [UI§8.3 "treat … localStorage store as disposable scaffolding"]).

### 6.3 Acceptance checklist mapping [UI§11]

All "Firm" checklist items are user-observable and can be the DoD of PC-01/PC-02. Additions proposed:

- [ ] Hero shows "Direct the run…" from `DEFAULT_HEADING`, and an operator `branding.heading` still overrides it (`branding.ts:26-28`).
- [ ] Operator `branding.app_name` replaces "Coral" but keeps the layout [UI§4.2].
- [ ] No user-facing string says "Omnigent" or "Omnigents" in default config (Electron connect title today: "Omnigents — Connect").
- [ ] Theme picker lists "Coral" as the default palette.
- [ ] Promise badges use the Clay palette (once design confirms §1.4 mapping).
- [ ] Dark mode passes the same checklist.

### 6.4 Explicitly NOT to redesign [UI§9]

Chat transcript, composer, approval cards structure, sidebar session list / DnD / projects model, settings IA, density/radii/control sizes/easing, theme picker infrastructure. Also (proposed): Inbox card structure, Automations pages beyond the header, Usage page.

### 6.5 Brand risks that need decisions

- "Powered by Omnigent" credit and mascot: `usePoweredBy()` shows the credit only when custom branding is set (`branding.ts:37-41`); counsel question [DD§16.3].
- Internal identifiers (`omnigent` package, `OMNIGENT_*`, `~/.omnigent`) stay [DD§16.3 layer 2]; CLI name and docs strings are a separate decision.
- elkjs licensing and React Flow attribution (Omnigent hides attribution: `CanvasPage.tsx:85`, `SubagentsGraphView.tsx:250`) [DD§14.4].
- Roster chips must say "Claude", not "Claude Code" [DD§16.1].

---

## 7. Missing product requirements and ambiguities (must be clarified)

Each item: the gap, why it matters, a recommendation, and who should decide.

**Q-01 Product requirements document missing.** `coral-design.md:5` points to `coral-requirements.md`; the file is absent (`ls` at repo root). No personas, success metrics, non-goals, MVP scope, pricing constraints or support matrix are written. *Recommendation:* write it from §1, §7 and §9 of this file; owner: product lead. Blocks MVP sign-off.

**Q-02 Reject semantics at human gates.** [D§5.6] defines the gate on "approved" and on loop limit, but not what "reject" does; the deep dive had to invent `a10` "ends the item" [DD§5.2]. Also undefined: whether a gate can have more than approve/reject (choose/answer [D§5.2]), what the generic card's "Decline"/"Cancel" mean (`ApprovalCard.tsx:134-145`), whether reject can route back into the loop with the approver's note as feedback, and V7's "approve-only" confirmation. *Recommendation:* every gate outcome is an authored label with a destination; validator requires a reject (or failure) route unless the author confirms approve-only; generic decline/cancel are hidden for gates.

**Q-03 Who may answer gates and `ask_user`.** Omnigent lets anyone with edit level resolve elicitations (`routes_elicitations.py:55-60`); Draft 4 is silent; [D§20 Q4] covers only amendments. Teams later. Also: does answering from a shared read-only view count? Proposed: owner only in MVP; teams later with edit on the orchestrator session (DD [DD§20.1]); show "waiting for owner" state.

**Q-04 Gate timeouts, reminders, escalation.** Gates never auto-resolve [DD§11]; reminder cadence, escalation target (another person? an external channel?) and the "run expires after N days" policy are undefined. Also: do managed sandboxes stay awake at a gate (R15)?

**Q-05 Notification channel for unattended gates and pauses.** No push exists (§2 g). Options: build push (large), email/Slack connector per run [D§5.5 "chat"], or state the limitation [DD§11]. *Recommendation:* MVP states it and uses in-app + desktop notifications while open; M3 adds one external connector (email or Slack DM). Decide which.

**Q-06 Terms-of-service implications of default auth.** Anthropic: third parties may not offer claude.ai login for Agent SDK products [DD§16.1 W-1]; Omnigent's `claude-sdk` strips `ANTHROPIC_API_KEY` to use subscription auth (F48). OpenAI: app-server auth not permitted for commercial/hosted services [DD§16.2]. *Decisions:* default auth for run-owned sessions (API key), whether subscription users are allowed on `claude-sdk` at all locally, what labels `claude-native` steps get, and the written vendor answers [DD§16.1 "Ask Anthropic before phase 2"]. Business model ("nothing may rule an option out" [D§3]) collides with "may not … intermediate Claude usage" [DD§16.1].

**Q-07 What the landing hero does.** The UI doc sets the hero to "Direct the run…" [UI§1, §4.3], implying the composer starts a workflow run; the design says the orchestrator receives the request at Start [D§5.6] but never names an entry surface. Is the hero (a) a plain session composer with Coral copy, (b) a run composer with a workflow picker chip, or (c) both with a toggle? *Recommendation:* (b) in M2 with a "Workflow" chip defaulting to none (plain session), keeping Omnigent's composer unchanged otherwise.

**Q-08 What a user sees during a multi-day plan-limit pause.** Weekly windows can be days away [DD§12]. Undefined: resume notification, whether the sandbox/worktree is kept, whether the user may continue with an API key for this run (Draft 4: "The engine never switches accounts" [D§7.8] — is a *user-initiated* switch allowed?), whether other runs queue behind it, and expiry. *Recommendation:* show reset time; auto-resume; notify on resume; allow a user-initiated profile auth switch recorded as an amendment (M6).

**Q-09 MVP scope cut.** Draft 4's order of work [D§18] puts the canvas at phase 5 and structure (repeat-for-each) at phase 6, but the PR-review showcase needs repeat-for-each and an orchestrator node, and users need to *see* runs from phase 2. *Recommendation:* §9.1.

**Q-10 Where workflows live.** "A YAML file in `.coral/workflows/`" [D§12] ties a workflow to one repo. Undefined: personal workflows reused across repos, non-code workflows ("plain folder" workspaces [D§11]), how the web app reads/writes host files (no API exists: `hosts.py:1599-1625` lists only), offline viewing, and stable workflow ids across machines. *Recommendation:* server-side library entry per workflow (index + latest content copy) with the repo file as source of truth when present; templates and personal workflows live server-side and can be "saved into repo".

**Q-11 Saving invalid workflows.** Can an invalid workflow be saved (as a draft) to the repo? Saved test cases run "whenever the workflow file changes" [D§8] — where (CI? the app?)? *Recommendation:* allow draft save; block Run; run saved tests in-app on save; CI integration Later.

**Q-12 Evidence in multi-agent steps.** Per agent or per step? ([DD§20.2 Q5]). Affects the run view's evidence panel and attempts counting.

**Q-13 Take-over details.** Can the user submit the handoff/label themselves? Is take-over available on multi-agent steps (whole step or one slot)? What happens to a running agent turn when the user takes over (interrupt? wait)? Note interrupt discards the vendor session in headless modes [DD§8.8].

**Q-14 `blocked` exit.** The deep dive adds `status: blocked` to `submit_handoff` [DD§5.4]; Draft 4 does not. Product must decide whether agents can say "I'm blocked" and where that routes (failure path vs gate) and how it shows ("Agent reports blocked: missing API credentials").

**Q-15 Step agents asking the user directly.** Policy ASKs, `AskUserQuestion`, native permission prompts happen inside step sessions (F37, F38a) and are not modelled in [D§7.2]. Do they pause the step? Count toward watchdog/overdue? Show as gates? *Recommendation:* show as "Step waiting on you" in run view and Inbox (approval kind already covers them); run status "Needs you".

**Q-16 Watchdog default time** [D§20 Q3]; DD: measure first [DD§20.1]. Product needs a placeholder default and a setting location.

**Q-17 Budget defaults.** Is a run budget mandatory? Default amount? USD vs tokens vs plan utilization for subscription users [DD§12]? Step budgets UI? Overshoot by one turn (`cost.py:48-50` per DD) must be disclosed.

**Q-18 Cost estimate presentation.** "Simulate counts sessions and past runs supply typical usage" [D§10]; first runs have no history. Show a range? Session count only? Translation costs at save [D§10]?

**Q-19 Session topology and sidebar noise.** Children of the orchestrator (hidden from sidebar; inherit runner and sharing) vs top-level sessions (listed; per-session grants) [DD§8.2]. Product: what appears in the sidebar for a run? Proposed: the orchestrator session only, titled with the run name, with a "Coral run" badge; steps via the run view.

**Q-20 Generic session actions on run-owned sessions.** Stop session, archive, delete, fork, rename, `/clear` (rotates session id in native modes, R12), share, edit session policies (can remove Enforced rules, [DD§10.6]). Each needs a defined outcome (block, warn, or the engine reacts). Not specified anywhere.

**Q-21 End-of-run outputs.** Does a code run end with a branch, a PR, a merge? The PR-review template's gate "approve the merge" [D§5.6] — who performs the merge (an agent step after the gate? Coral itself?). Worktree cleanup policy (archive offers worktree deletion today, `feature-map/sessions.md` `archive`)?

**Q-22 Repeat-for-each behaviour** (needed by templates): ordering, empty list, per-item failure tolerance, concurrency UI, cancel remaining [DD§5.3.5].

**Q-23 Amendment permissions and UX** [D§20 Q4]; compatible-change rules must be explained to users in plain words.

**Q-24 Codex in v1?** [D§20 Q1]; DD: after v1. Affects the PR-review template's Codex reviewer [D§5.6].

**Q-25 Relationship to Automations.** Coral "triggers (later): schedules, webhooks, polling" [D§5.5] overlap with Automations (scheduled tasks, polling trigger templates). One concept or two? *Recommendation:* Automations gains a "Run workflow" action; Coral does not build a second scheduler.

**Q-26 Improvement suggestions data.** How "orchestrator decisions that people later reverse" [D§14] is detected; where suggestions surface; whether accepting writes to the repo or opens a PR.

**Q-27 Sharing mechanics.** Import a workflow/template from a git URL; profile dependencies; what a teammate sees when a profile is missing; run sharing with read-only viewers (edit-sharing blocks Omnigent orchestration, `feature-map/session-orchestration.md` `sharing`).

**Q-28 Elephant-Goldfish template options.** Persistent session across loop passes for one roster member; per-member input scoping (goldfish see only the document); typed resolutions (propose fix / contest / escalate); ESCALATE → human gate; the elephant is a step agent, not the orchestrator [DD§15.3]. None are in Draft 4 (§8 D4).

**Q-29 Accessibility of the canvas.** No artifact requires keyboard editing or a screen-reader equivalent. *Recommendation:* outline view + YAML as accessible authoring; run view timeline as accessible monitoring.

**Q-30 Mobile scope.** Approvals on phone are required [D§13]; editing on phone is not stated. *Recommendation:* phone = runs list, run status, gates, timeline; no canvas editing.

**Q-31 Promise label visual system.** Not in UI doc (§1.4).

**Q-32 Data retention.** Run logs, handoff artifacts, transcripts per run: retention and deletion (DB rules require hard delete [DD§7.1]); deleting a workflow with runs.

**Q-33 "Powered by Omnigent" and attribution.** Keep credit? (§6.5).

**Q-34 Which pages get the Coral desk header.** UI doc lists four; Task detail, Canvas, Settings, Usage are unlisted.

**Q-35 Telemetry.** Page-view ids for new routes are mandatory by convention (`App.tsx:16-29`); product analytics events (template used, simulate run, run started, gate answered) are unspecified; analytics must not carry workflow content (PII).

**Q-36 Success metrics.** None defined. Proposed: time from template to first successful simulate; % runs completing without manual rescue; % gates answered within 1 h; % evidence failures that were true positives (sampled); runs per active user per week.

---

## 8. Conflicts between artifacts

### 8.1 D1 confirmed and refined (Draft 4 still states things the deep dive found false at this commit)

| # | Draft 4 claim (line) | Deep dive | My verification at HEAD | Product impact |
|---|---|---|---|---|
| D1.1 | Fail-closed sub-agent router enforces rosters (`coral-design.md:82, 104, 205, 270, 392, 415`) | F4/F28: router is Smart-Routing model selection, advisory | `omnigent/runner/subagent_routing.py:1-8` ("which model the spawn should run on. The gate is **advisory**") | Do not label sub-agent-mode rosters Enforced; MVP uses separate sessions only (roster by construction [DD§10.4]) |
| D1.2 | `PersistentTaskScheduler` for timers and signal queue (`:87, 284`) | F10/F29: at-most-once, typed on `ScheduledTask`, built only with `automations_v2` | `omnigent/server/feature_flags.py:54` (`default_enabled: bool = False`) and `:97-104` (`AUTOMATIONS_V2` with no default override) | Engine timers (plan-limit resume, watchdog, gate reminders) need their own durable mechanism; user-facing "resumes automatically" depends on it |
| D1.3 | Web push for approvals (`:83, 182`) | F6 / finding 9: none | No push code (grep); `browserNotifications.ts:8-10`; `web/ios/README.md:17-22`; `web/android/README.md:33-37` | Copy must not promise approvals with the app closed (Q-05) |
| D1.4 | Budget reached "pauses the run and asks… reuses `cost_budget`" (`:346`) | F42 / finding 10: ASK at soft thresholds, DENY at cap, per session | `omnigent/policies/builtins/cost.py` ASK/DENY paths around `:505-560` | Run budget pause is engine work; per-session policy is a backstop |
| D1.5 | `sys_cancel_task` does nothing (`:107`) | F25: stale | Server stub `omnigent/tools/builtins/async_inbox.py:98-110`; runner intercept `omnigent/runner/tool_dispatch.py:400-408` | None for UX; correct the doc |
| D1.6 | Sandboxes network on/off only; web-fetch policy + network-off (`:108`) | F26/F27: `egress_rules` default-deny allowlist exists | `omnigent/inner/datamodel.py:765` (`egress_rules: list[str] \| None`) | "Only these websites" rules can be Enforced on bwrap/seatbelt hosts; label depends on host |
| D1.7 | Refresh threshold 70% (`:276`) | DD restates Draft 3's 80% [DD§2, §8.9] | n/a | Use 70% as Draft 4 says; DD's 80% is stale. Also undefined when the context window is unknown [DD§8.9] |
| D1.8 | Completion hook as turn-end source (`:86`) | Finding 4: maps every idle edge to succeeded | per DD (`helpers.py:5158-5159`, not re-opened) | Users may see steps "finish" falsely unless the reconciler confirms with transcript evidence |
| D1.9 | Approvals "work in the browser, the desktop app and on the phone" (`:363`) | F6 | as D1.3 | Same as D1.3 |
| D1.10 | Draft 4 adopted: derived joins (§5.2), merge rules (§5.3), separate migration env/version table (§7.6), API keys first-class (§17), decision log (§19) | Aligned with findings 1, 7, 11 | n/a | Resolved; specs should cite Draft 4 |

### 8.2 D2 confirmed

`coral-requirements.md` is referenced (`coral-design.md:5`) and absent (`ls: coral-requirements.md: No such file or directory`). See Q-01.

### 8.3 D3 confirmed and extended

- `/schemas` and `/profiles` (UI doc) vs `/workflows` (design `coral-design.md:356`, DD [DD§14.1]): neither exists in `web/src/App.tsx` (routes at `:180-256`). Resolution in §4.1.
- Node taxonomy: UI doc Phase/Gate/Note/Orchestrator [UI§8.4] vs design Start/End/Work step/Orchestrator node/Human gate/Group (+ Wait, Sub-workflow) [D§5.2]. The UI doc itself marks its taxonomy as "prototype guesses" [UI§8.2]. Design wins.
- Profiles: UI doc "localStorage store as disposable scaffolding… whether profiles are local-only desk objects, server resources, or YAML agents under the hood" [UI§8.3] vs design "agent YAML + description + default rules + capabilities" [D§5.4]. Design wins; profiles are server agent rows (reusable user agents).
- Prototype files absent: `web/src/components/concerto/` (no such directory), `CoralLogo.tsx` (absent; assets are `omnigent-wordmark.svg`, `omnigent-starfish-icon.png`, `otto-no-padding.svg` in `web/src/assets/`), `--concerto-*` tokens (absent; `index.css:45` only defines `--font-heading: var(--font-sans)`).
- Additional: the UI doc says the baseline hero is "often 'What should we do?'" [UI§1]; the code default is "What should we build?" (`web/src/lib/branding.ts:5`). UI doc says Inbox and Automations use "plain `text-2xl font-semibold`" [UI§5.2]; Inbox is `font-normal` (`InboxPage.tsx:874`), Automations `font-semibold` (`TasksPage.tsx:240`). Cosmetic, but specs should use the code values.
- Additional: the UI doc's Agent Profiles desk duplicates the existing Settings → Customize → Custom agents surface (`settingsNav.tsx:141`, `feature-map/custom-agents.md`), which the UI doc does not mention. Product must decide "lens + deep link" vs "separate editor" (recommend lens, §4.1).

### 8.4 D4 confirmed and extended

Elephant-Goldfish needs persistent-session and per-member input-scoping step options absent from Draft 4 [DD§15.3]. Further: Draft 4 still says EGM "maps directly onto Coral's orchestrator and fresh step agents" (`coral-design.md:382`), which conflicts with "the orchestrator does not do the work" [D§1]: the elephant drafts the document, so it is a long-lived step agent. Typed resolutions (propose fix / contest / escalate) and attribution (Dave Rensin; `google/elephant-goldfish-model`, Apache-2.0) are also missing. Draft 4 used an "Elephant-Goldfish review" on itself (`coral-design.md:9`), which signals intent to ship it.

### 8.5 New conflicts (D5-D24)

| # | Conflict | Sources | Recommended resolution |
|---|---|---|---|
| D5 | Coral-run "repository checks" use commands detected from the repo's own config (`package.json`, Makefile, CI) [D§6.2] vs the deep dive's requirement that pinned commands be defined in the workflow file and run in a Coral-controlled checkout, because agents can edit `package.json` scripts [DD§9.3 item 3] | `coral-design.md:237`; [DD§9.3] | Snapshot confirmed commands into the workflow file at confirmation; run them from a Coral checkout; integrity diff flags edits to scripts/config. Label stays Verified only if this holds |
| D6 | Four-label taxonomy (task brief, DD) vs Draft 4's three labels + unlabelled "not promised" | `coral-design.md:201-215`; [DD§2, §9.3] | Add **Judgment** as a visible label (§1.4) |
| D7 | Labelled arrows: [D§5.2] says arrows leaving orchestrator nodes or gates carry labels; [D§5.3] also lets a single-agent step lead directly into labelled arrows | `coral-design.md:144, 159` | Follow V4 [DD§5.5]: decisions, gates and single-agent steps |
| D8 | "Subscription or API keys. Both are supported" [D§3] and headless modes by default [D§9] vs terms (subscription not allowed for SDK products) [DD§16] | `coral-design.md:63, 339, 401-403` | Q-06; API key default for headless; subscription → claude-native |
| D9 | "Enforced… or the workflow is invalid" for Required rules [D§6, §9] vs native hooks that fail to ASK (F38a) and headless codex tool calls that are only observed (F37) | [DD§10.2, §10.5] | Validator treats native modes as unable to enforce until S14/S15; headless codex until S20 |
| D10 | Gates published through Omnigent elicitations (DD) vs policy-ASK timeouts that become DENY [DD§11] | `omnigent/runtime/policies/approval.py` (per DD) | Never route gates through policy ASK |
| D11 | Who answers gates: Omnigent edit level (`routes_elicitations.py:55-60`); Draft 4 silent; DD recommends edit for gates, manage for amendments [DD§20.1] | | Q-03 |
| D12 | Sharing runs "built on Omnigent's session sharing" [D§13] vs per-session sharing and edit-sharing blocking orchestration (F47; `feature-map/session-orchestration.md` `sharing`) | | Run-level sharing needs engine-managed grants; Later |
| D13 | Canvas phase 5 [D§18] vs UI doc's graph as a primary desk surface [UI§5.1] | | Read-only diagram and run overlay at M1-M2; editing M4 (§9) |
| D14 | `ask_user` only for the orchestrator [D§7.2] vs step-level prompts that exist anyway (F37, F38a) | | Q-15 |
| D15 | Cost estimate in money [D§10] vs USD is a client estimate and irrelevant for subscription billing [DD§12] | | Show tokens/utilization for plan users; label estimates |
| D16 | Workflow is a repo file [D§12] vs individuals-first library, templates, non-code folders [D§3, §11] and no host file API (`hosts.py:1599-1625`) | | Q-10 |
| D17 | Profiles "follow" reusable user agents [D§5.4] vs reusable agents' decision 6 (reinstall/edit updates running sessions next turn; `REUSABLE_USER_AGENTS.md:112`; `CUSTOM_AGENTS_SETTINGS_UI.md:102-106`) | | Pin per workflow version (PC-07) |
| D18 | Per-run branch "locally or in a sandbox" [D§11] vs managed sandboxes rejecting git options (S28) | per DD | MVP local only |
| D19 | Hero "Direct the run…" [UI§1] implies run entry; design names no entry surface | | Q-07 |
| D20 | Draft 4 order of work still lists "the fail-closed mode of the sub-agent router" in phase 2 (`coral-design.md:415`) and the patch list (`:392`) vs DD replacement (S14 + roster policy) | [DD§4.3 mapping] | Remove from phase 2; add S14/S15 to phase 4 |
| D21 | UI doc's code locations (`web/src/components/concerto/`, `--concerto-*`) vs DD `web/src/workflows/` | [UI§10]; [DD§4.2] | `web/src/workflows/` + `web/src/components/coral/` + `--coral-*` |
| D22 | Draft 4 says the canvas lives "in its own folder under `web/src/`" [D§16]; `web/src/canvas/` is taken (F43) | | `web/src/workflows/` |
| D23 | Gate "cannot be skipped" [D§5.2] vs managed sandboxes that sleep while a run waits at a gate (R15; keepalive only while busy) | per DD §13 | Checkpoint pushes; sandbox runs later |
| D24 | Draft 4 says "Coral-run checks… off by default… templates for code changes turn them on" [D§6.2] vs MVP evidence scope (checks need S40 runner work) | | Templates in MVP rely on done-when evidence only; turn Coral-run checks on at M3 |

---

## 9. Recommended MVP and release sequence

### 9.1 Smallest lovable Coral (MVP)

**Promise to the user:** "Pick a template, see exactly what will happen, run it on your repo, and trust that review, tests and your approval actually happened."

**Template:** **"Implement with review loop"** (single item, no repeat-for-each, no parallel split):

```
Start (request) → Implement [1 Claude implementer; agents change code; done when: relevant tests, lint and format pass after the last change]
  → Review [2 Claude reviewers on different models; read-only; handoff: findings]
  → Orchestrator node "Review outcome" (approved | changes requested)
      changes requested → back to Implement (limit 3; at limit → Human gate with open findings)
      approved → Human gate "Approve the change" (approve → End with branch; reject → End, branch kept, note recorded)
```

This exercises: orchestrator node with reasons, multi-agent handoff collection, loop with limit and at-limit route, merge of alternatives at the gate (derived join), human gate, done-when evidence, fresh-context reviewers. Two Claude reviewers on different models stand in for the Codex reviewer until Codex lands ([DD§20.1 Q2] suggests the same). It diverges from the deep dive's "PR review loop first" because that template needs repeat-for-each (Draft 4 phase 6); the PR loop becomes the M5 showcase.

**In MVP (user can):**

1. See Coral branding and the Workflows / Agent Profiles nav (PC-01, 02, 38).
2. Choose model access (API key recommended; subscription via claude-native with honest labels) (PC-03).
3. Use the template, choose a repo, confirm test/lint/format commands and the done-when translation (PC-09, 06, 26-basic).
4. Edit the YAML with live validation and a read-only diagram (PC-11, 05, 10-read-only, 04).
5. Simulate every branch for free and save test cases (PC-12).
6. Start a run with a session-count estimate and a run budget (PC-13, 25-basic).
7. Watch the run: path, statuses, decisions with reasons, loop counter, evidence results, timeline, focused agent session (PC-16-basic, 17-basic, 18).
8. Type into the orchestrator or any agent session (PC-22).
9. Answer the gate and `ask_user` from run view, Inbox or `/approve` link on web/desktop/phone while the app is open (PC-19, 20, 21-in-app).
10. Understand and act on pauses: plan limit with reset time, infra loss, budget, rejected calls, liveness, failure path; Resume / Retry step / Cancel (PC-14, 24-core).
11. Find past runs and their outcomes (PC-15, 33-view).
12. See "What Coral guarantees" with Enforced / Verified / Requested / Judgment labels that never over-claim (PC-08).

**Explicitly not in MVP:** canvas editing, take-over/hand-back, Required rule translation (beyond orchestrator no-write policy and step roster-by-construction), reactions, session refresh (MVP steps are short; alert instead), Coral-run checks, verifiers, groups/blocks/repeat-for-each/parallel, Codex, amendments, step budgets, suggestions, EGM, external notifications, sandboxes, run sharing, mobile editing.

**MVP engineering prerequisites (from DD phases):** phase 1 (engine core, Simulate, durable gates, derived joins, scope keys, separate Alembic env, S29-S33, S39), phase 2 (S1-S13, session topology decision, `claude-sdk` on API key, end-of-turn and tool-gating probes, `blocked` status), a slice of phase 3 (S40 fingerprints for done-when; command patterns), S35-S37 from phase 5 (run view watch-set, suppress per-step notifications, inbox kind), and the run stream API.

### 9.2 Release sequence (what users can do at each milestone)

| Milestone | Theme | Users can… | Main PCs | DD phase alignment |
|---|---|---|---|---|
| **M0** (internal, flagged) | Skin and shell | See Coral brand, desk headers, empty Workflows/Profiles pages behind `workflows` flag | 01, 02, 38 | parallel track |
| **M1** | Author and simulate (no agents, no cost) | Pick a template, edit YAML with validation, see the diagram, Simulate every branch, save test cases | 04, 05, 09, 10 (read-only), 11, 12, 37 | phase 1 |
| **M2 = MVP** | First real run | Everything in §9.1 | 03, 06 (done-when), 07 (minimal), 08, 13-22, 24 (core), 25 (basic), 26 (basic), 27 (single coder), 33 (view) | phase 2 + part of 3 + S35-S37 |
| **M3** | Trust and guardrails | Coral-run checks, verifier opt-in, integrity diff; Required rules with per-mode labels; reactions; protected rules; session refresh with stitched orchestrator; Profiles desk with default rules; versions list and diff; external notification channel (email or Slack) | 06 (rules), 07 (full), 17, 21 (external), 24 (refresh, overdue), 26 (full), 29, 34 | phases 3-4 |
| **M4** | Visual authoring | Draw and edit on canvas two-way; auto-layout; take over and hand back; "why not taken" arrows | 10 (edit), 16 (full), 23 | phase 5 |
| **M5** | Structure and scale | Groups, blocks, repeat-for-each with progress, parallel steps with live messaging and merges; "Review labelled PRs" showcase | 27 (multi-coder), 30 | phase 6 |
| **M6** | Codex, budgets, amendments | Codex reviewers/implementers (codex-native first), step budgets, plan limits for Codex, "Apply to this run" | 25 (full), 28, 35 | phase 7 |
| **M7** | Learn and share | Improvement suggestions, Elephant-Goldfish template, import from git, run log export | 31, 32, 33 (export), 36 | phase 8 + EGM options |
| **Later** | Teams and ecosystem | Run sharing, team gate approvers, triggers via Automations, push notifications, marketplace, workflows as tools | — | [D§15] |

### 9.3 Parallelization notes for the roadmap

- PC-01/02/38 (skin, chrome, nav) and the profile lens (PC-07 list) have no engine dependency and can start immediately.
- PC-11/05/12 front ends can be built against a compiled-graph JSON contract before the engine exists; Simulate shares the reducer, so the reducer contract (inputs, outputs, log entries) should be fixed first.
- PC-16 run view can be built against the run-stream contract with Simulate as its data source (a simulated run is a run with stub effects), which lets the run view ship in M1 for simulations and light up for real runs in M2.
- PC-19 gate UI reuses existing cards; the blocking work is PL-D (S5/S6) and outcome mapping (Q-02).
- Q-01, Q-02, Q-03, Q-05, Q-06, Q-07, Q-10 must be answered before M2 specs are final.

---

## Appendix: evidence opened at HEAD in this pass

| Claim | Location |
|---|---|
| Routes, page-view wrapper, feature gate | `web/src/App.tsx:24, 76-86, 180, 181, 192, 194-208, 209-224, 239, 256` |
| Sidebar brand row and primary nav | `web/src/shell/Sidebar.tsx:1259-1278, 1299-1342, 1344-1370, 1371-1409, 1411-1421, 1422-1425, 1426-1449` |
| Branding defaults and powered-by | `web/src/lib/branding.ts:4-5, 26-28, 37-41`; `deploy/README.md:670-690` |
| Hero composer | `web/src/shell/NewChatDialog.tsx:2242, 7011-7047` |
| Default palette and heading font | `web/src/lib/themePalette.ts:47, 217-218`; `web/src/index.css:45` |
| Electron naming | `web/electron/package.json:3, 43`; `web/electron/setup/index.html:6` |
| Inbox kinds, empty copy, header, automation card | `web/src/pages/InboxPage.tsx:170-181, 189-193, 487-528, 874` |
| Automations header, tabs | `web/src/pages/TasksPage.tsx:229-264, 307-312` |
| Task detail run history states | `web/src/pages/TaskDetailPage.tsx:1-12, 537-563` |
| Canvas page is a session board | `web/src/pages/CanvasPage.tsx:1-24, 84-85, 592, 668` |
| Graph view reuse | `web/src/shell/SubagentsGraphView.tsx:128, 248-250` |
| Feature keys (no `workflows`) | `web/src/lib/capabilities.ts:60-74` |
| Command palette nav | `web/src/shell/CommandPalette.tsx:195-208` |
| Settings nav (Customize, Admin) | `web/src/shell/settingsNav.tsx:109-171` |
| Custom agent form fields | `web/src/pages/settings/CustomAgentConfigForm.tsx:174-219, 354-518` |
| Agent config API and ETag | `omnigent/server/routes/builtin_agents.py:230, 369-441, 443, 512, 538, 581` |
| Revision propagation to running sessions | `designs/REUSABLE_USER_AGENTS.md:112, 419-438`; `designs/CUSTOM_AGENTS_SETTINGS_UI.md:102-106` |
| Approval/elicitation components | `web/src/components/blocks/ApprovalCard.tsx:134-145`; `web/src/components/blocks/ElicitationSchemaForm.tsx:1-21`; `web/src/pages/ApprovePage.tsx:1-16` |
| Side chat full session | `web/src/components/chat/SideChatPane.tsx:166-180` |
| Live conversation caps | `web/src/store/conversationRegistry.ts:64-84` |
| No push; foreground-only notifications | `web/src/lib/browserNotifications.ts:8-10`; `web/ios/README.md:17-22`; `web/android/README.md:33-37`; grep (no matches) |
| Slack approvals for Slack sessions | `integrations/slack/README.md:345-348` |
| Feature flag defaults | `omnigent/server/feature_flags.py:54, 97-104, 130-134` |
| Router is advisory | `omnigent/runner/subagent_routing.py:1-8` |
| Cost policy ASK/DENY | `omnigent/policies/builtins/cost.py:505-560` |
| `sys_cancel_task` stub vs runner intercept | `omnigent/tools/builtins/async_inbox.py:98-110`; `omnigent/runner/tool_dispatch.py:400-408` |
| Elicitation resolve level | `omnigent/server/routes/sessions/routes_elicitations.py:55-60`; `omnigent/server/auth.py:124-125` |
| Egress rules field | `omnigent/inner/datamodel.py:765` |
| Host filesystem API list-only | `omnigent/server/routes/hosts.py:1599-1625, 1729` |
| Canvas layout in localStorage | `web/src/canvas/canvasStorage.ts:1-9` |
| Automation dialog run target controls, default project | `web/src/components/scheduled/CreateScheduledTaskDialog.tsx:96, 1102, 1323, 1430` |
| Template gallery constants | `web/src/components/scheduled/automationTemplates.ts:1-11` |
| Design doc claim lines | `coral-design.md:5, 63, 82-87, 104-108, 144, 159, 182, 201-215, 237, 270, 276, 284, 339, 346, 356, 363, 382, 392, 401-403, 415` |
| Missing files | `coral-requirements.md`, `web/src/components/concerto/`, `web/src/workflows/` (all absent) |
