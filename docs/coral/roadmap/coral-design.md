# Coral: Workflow Engine Design on Omnigent

Draft 4. November 9, 2026.

This document describes how Coral's workflow engine is built on a fork of Omnigent. The product requirements are in `coral-requirements.md`. Facts about Omnigent come from its source code at version 0.22.0.dev0 (commit of November 8, 2026). File paths are relative to the Omnigent repository.

This is an architecture document. The detailed build specification for the first phases (file format, database tables, tool contracts, file-level changes and test plan) is a separate, later document.

**Changes from draft 3,** after a full Elephant-Goldfish review:

- Joins are fixed. Draft 3 said a box waits for all incoming arrows, which hangs forever when the arrows are alternatives. A box now waits for all branches only after a parallel split; when paths are alternatives, the first one to arrive continues (section 5.2).
- Multi-agent handoffs and parallel code changes now have defined rules for combining and merging (section 5.3).
- Change detection for "done when" looks only at files that git tracks or would track, so caches and build output no longer count as changes (section 6.1).
- New option: Coral can run the repository's own check commands itself as a final safety net (section 6.2).
- The engine is now a standalone package with its own database migrations, so the fork stays thin (section 16).
- Using Claude or OpenAI API keys is a first-class option, next to subscription sign-in (section 17).
- The session refresh threshold now sits below the agent's own automatic compaction (section 7.5).
- New: a decision log that records the main alternatives we rejected and why (section 19).
- Self-optimization theory moved to an appendix. Fixed a broken cross-reference, and added the sub-agent router fix to the order of work.

---

## 1. Summary

A workflow is a diagram of **steps**. Each step is a chunk of work described in plain language: a goal, a **roster** of agents, and a **handoff**. One **orchestrator** agent receives the user's request and conducts the run. It decides at decision points and coordinates the step agents, but does not do the work itself. The agents choose their own methods and commands.

The **engine** is the rails. It does not think and does not do the work. It makes sure that the run only follows arrows that exist, that each step uses exactly its roster, that each step hands over what it must, that "done" is backed by evidence, and that human approvals are never skipped.

Omnigent provides everything underneath: driving Claude Code and Codex, local and cloud machines, tool-call policies, stored conversations, and live sessions on the web, the desktop and the phone. What Omnigent lacks is anything that holds a multi-step process to a contract. Every multi-step behaviour in Omnigent today is sequenced by a model following instructions.

## 2. Terms

- **Omnigent:** Databricks' open-source "meta-harness" (Apache 2.0) that runs and supervises coding agents. Coral is a fork of it.
- **Harness:** an agent program that Omnigent drives, such as Claude Code or Codex.
- **Agent mode:** how Omnigent drives a harness. There are four that matter to us:
  - `claude-sdk`: headless Claude Code through the Claude Agent SDK.
  - `claude-native`: the real Claude Code terminal, inside tmux.
  - `codex`: headless Codex through its app server.
  - `codex-native`: the real Codex terminal, attached to an app server.
- **Session:** an Omnigent conversation with one agent, stored in its database.
- **Signal queue:** the engine's internal table of events from Omnigent waiting to be processed. It is different from Omnigent's user-facing inbox.
- **MCP (Model Context Protocol):** the standard way to connect tools and data sources to agents.
- **Elicitation:** Omnigent's name for a question or approval request shown to the user, for example "allow this command?".

## 3. Decisions so far

| Topic | Decision |
|---|---|
| Foundation | A fork of Omnigent, as Cursor is a fork of VS Code. We change Omnigent only where there is a reason to. |
| Upstream | Track closely at first, then diverge over time. |
| Agents | Claude Code first, then Codex. Others later. |
| Orchestrator | Exactly one per run. It is the entry point for the request and the workflow. It conducts and does not do heavy work. |
| Steps | Plain-language chunks of work. Agents choose their own methods. |
| Rosters | One or more agent profiles, with no team lead. Exact by default; "up to" a number if the author allows it. |
| Sessions | Separate sessions by default. Sub-agents inside one session are allowed where Coral can verify them. |
| Communication | Agents in parallel steps may message each other live. Steps in sequence communicate only through handoffs. Step agents report to the orchestrator at orchestrator nodes. |
| Decisions | The orchestrator chooses at orchestrator nodes and gives a reason. Human gates and evidence failures override it. |
| Checked handoff parts | A chosen label where the diagram branches; a list where a later step repeats for each item. |
| Done | "Done when" in plain language, checked against the session record. An optional verifier agent and optional Coral-run checks add certainty. |
| Rules | Plain language. Required rules are enforced, and validation fails if the agent cannot enforce them. Guidance rules are requests and are marked as such. |
| Versions | A run follows the workflow version it started with. Applying an edit to a running run is a separate, recorded action. |
| Joins | After a parallel split, the engine waits for all branches. Where alternative paths meet, the first to arrive continues. |
| Model access | The user's Claude or ChatGPT subscription through the agents' own sign-in, or API keys. Both are supported. |
| Authoring | The file and the canvas are equal views. |
| Places to run | The user's machine first; Omnigent's cloud sandboxes and an always-on server next. |
| Users | Individuals first, with data ready for teams. |
| Improvement | Suggestions now; self-optimization as theory. |
| Sharing | Git repositories and templates now; a marketplace later. |
| Business model | Undecided. Nothing may rule an option out. |

## 4. What Omnigent gives us

### 4.1 Parts we reuse

| Need | Omnigent part | Where |
|---|---|---|
| Drive Claude Code and Codex | Executors with a shared event model | `omnigent/inner/executor.py`, `claude_sdk_executor.py`, `codex_executor.py`, `omnigent/harnesses/` |
| Know what each mode supports | `HarnessCapabilities` | `omnigent/harness_capabilities.py`, `omnigent/harness_plugins.py` |
| Test those claims against real agents | The harness bench | `tests/harness_bench/` |
| Local and cloud machines | Hosts and managed sandboxes | `omnigent/host/`, `omnigent/server/managed_hosts.py` |
| Allow, deny or ask on tool calls | Policies with per-session counters | `docs/POLICIES.md`, `omnigent/runtime/policies/` |
| Limit which sub-agents an agent may start | The sub-agent router hook on `Agent`, `Task` and Codex `spawn_agent` | `omnigent/inner/hook_scripts/subagent_router.py`, `omnigent/runner/subagent_routing.py` |
| Approvals on any device | Elicitations, inbox, web push, mobile apps | `omnigent/runtime/policies/approval.py`, `web/` |
| Describe an agent | Agent YAML | `docs/AGENT_YAML_SPEC.md` |
| Messages between sessions | `sys_session_send` and `sys_session_message` | `docs/session-messaging-tool-boundary.md` |
| Know when a turn finished | The scheduled-run completion hook | `omnigent/server/session_live_state.py:251`, called from `omnigent/server/routes/_sessions/helpers.py` |
| Durable timers and queues | `PersistentTaskScheduler`, which accepts a custom store and callbacks | `omnigent/server/scheduled/dispatch_scheduler.py` |
| Compaction in terminal modes | Native compaction controls | `omnigent/runner/native_controls.py` |
| Policy hook token refresh | `PolicyHookReauth` | `omnigent/native/native_policy_hook.py` |
| Idle cleanup settings | Idle timeout and active-turn check | `omnigent/runtime/harnesses/process_manager.py` |
| Diagrams | `@xyflow/react` | `web/src/pages/CanvasPage.tsx` |
| Feature switches | Feature flags | `omnigent/server/feature_flags.py` |

The orchestrator and every step agent are ordinary Omnigent sessions. The user can open, read, type into, share and approve them with screens that already exist.

### 4.2 Gaps we must close

| Gap | What we do |
|---|---|
| Nothing holds a multi-step process to a contract. | The engine in this document. |
| The live event stream loses events when nobody listens (`omnigent/runtime/session_stream.py`). | Decide from durable database state. Generalize the existing turn-completion hook into the engine's signal queue, with a backstop for signals that never arrive (section 7.6). |
| The completion hook does not fire if a host dies mid-turn, and an idle status does not prove that a turn finished (`omnigent/server/scheduled/run_reconciler.py`, `fire.py`). | A reconciler that checks steps whose signals are overdue. |
| `claude-sdk` does not record which sub-agent made a tool call. Only the ACP executor emits sub-agent events, and the `claude-sdk` mode declares `subagents=False`. | Separate sessions by default. Sub-agents in one session only for steps that need no per-agent evidence, until a harness bench probe proves sub-agent visibility. |
| The sub-agent router fails open: if it cannot be reached, the spawn is allowed. | A fail-closed mode for sessions owned by a run. |
| `HarnessCapabilities` leaves `steering`, `live_queue` and `compaction` undeclared for all four modes. | Fill them in from bench probes, and add the fields Coral needs (section 9). |
| Agent-created timers are in-memory sleeps. | Engine timers use the persistent scheduler. |
| A session is tied to one runner with no failover, and `sys_cancel_task` does nothing (`designs/CUJ-ANALYSIS.md`). | Steps whose runner is lost are restarted in a new session from their last handoff. Cancellation uses interrupt. |
| Sandboxes switch the network fully on or off only. | Website limits combine a web-fetch policy with a network-off sandbox. |
| Possible policy token expiry and idle reaping on long steps. | Retest. Omnigent already has a token refresh and an idle timeout override. Patch only if the tests fail. |

## 5. The building blocks

### 5.1 What an author writes

**For the workflow:** a name, a purpose, the orchestrator's profile (a default is provided), and optional rules that apply everywhere.

**For a step, required:**

1. A **name**, for example "Review the pull request".
2. The **goal**, in plain language.
3. The **roster**, for example "one Claude reviewer and one Codex reviewer".
4. The **handoff**, in plain language, for example "a review report with findings".

**For a step, optional:**

- **Done when**, for example "relevant unit tests, lint and format checks pass for the code you changed".
- **Attempts:** how many times the step may try to satisfy "done when". The default is three.
- **Failure path:** where to go when the attempts run out. The default is to pause the run and ask the user.
- **Repeat for each:** run the step for each item in a list from an earlier handoff. Items run one at a time unless the author allows more.
- **Rules** (section 9).
- **How agents run:** separate sessions (default), or sub-agents in one session where allowed.
- **Expected duration**, for alerts.
- **Agents change code:** whether the step's agents edit files. Off by default for steps with more than one agent, which keeps reviewers and researchers read-only. See section 5.3 for how changes from several agents are merged.
- **Coral-run checks:** commands that Coral itself runs after the agents finish, either the repository's standard checks or a pinned command such as `npm test` (section 6.2). This is an optional extra on top of "done when".

### 5.2 Shapes on the canvas

- **Start and End.** The user's request enters at Start.
- **Work step.** A box with the step name, roster chips and rule badges.
- **Orchestrator node.** A decision point. The step agents report to the orchestrator here, and it chooses a labelled outgoing arrow, with a reason. The conversation between the agents and the orchestrator is drawn here.
- **Human gate.** A person approves, rejects, chooses or answers. It cannot be skipped.
- **Group.** A container. Rules on a group apply to everything inside. A saved group is a **block**. A group set to "repeat for each" shows a badge with the progress, for example "3 of 10".

**Arrows** carry handoffs. Arrows that leave an orchestrator node or a human gate carry labels. An arrow that points back to an earlier box forms a loop and must have a limit and a destination for when the limit is reached.

**Splits and joins.** Several unlabelled arrows leaving the same box are a **parallel split**: all their targets run at the same time. Several arrows entering the same box can mean two different things, and the engine treats them differently:

- **Parallel join.** The arrows come from the branches of one parallel split. The engine waits for all of those branches, then continues with all of their handoffs.
- **Merge of alternatives.** The arrows come from paths where only one is taken, for example "approved" and "loop limit reached". The engine continues as soon as one arrives, because the others never will.

The validator works out which case applies from the diagram. A box where both cases mix, or where a parallel join has no matching split, is shown as an error. In the example in section 5.6, the human gate is a merge of alternatives: it is reached either on "approved" or when the fix loop reaches its limit.

Hidden advanced kinds: **wait** (for a time or an event) and **sub-workflow**.

### 5.3 Handoffs

Every handoff contains the step's **report** (text) and its **artifacts** (files, diffs, commits). Where the diagram needs it, the handoff also contains a small checked part. The author does not configure it; the validator derives it from the diagram:

- **A label.** If a single-agent step leads directly into labelled arrows, its handoff must name one of those labels. Steps with more than one agent cannot branch directly; they must lead into an orchestrator node, where the orchestrator chooses.
- **A list.** If a later step or group repeats for each item of this step's output, this handoff must contain a list, and each item is passed to one repetition.

The engine checks these parts when the handoff is submitted. A missing or invalid part is returned to the agent with an explanation.

**Steps with several agents.** Each agent submits its own handoff. The step's handoff is the collection of all of them, each marked with the agent and profile that wrote it, and the next box receives the whole collection. A step with several agents cannot produce a single label or a single list by itself: it must lead into an orchestrator node, where the orchestrator reads the collection and chooses the label or writes the combined list.

**Merging code changes.** When agents change code at the same time, either inside one step with "agents change code" turned on, or in parallel steps, each agent works on its own branch of the run's worktree. When the step closes, or at a parallel join, the engine merges the branches into the run's branch one at a time, in roster or branch order:

- If every merge applies cleanly, the merged result is the step's change, and "done when" and Coral-run checks are evaluated on the merged result.
- If a merge conflicts, the step does not close. The engine reports the conflicting files to the orchestrator, which assigns one of the step's agents to resolve the conflict. If that fails within the step's attempts, the step takes its failure path, which by default pauses the run and asks the user.

Steps where only one agent changes code, and steps that only read, need no merging.

### 5.4 Profiles

A profile is an Omnigent agent definition (agent YAML) with three additions: a short description for the canvas, default rules, and the capabilities it is expected to provide. Upstream is designing reusable user agents (`designs/REUSABLE_USER_AGENTS.md`), which we follow.

### 5.5 Connectors

- **Agents:** Omnigent harnesses.
- **Tools and external domains:** MCP servers on profiles, steps or groups.
- **Triggers** (later): schedules, webhooks, polling.
- **Notifications:** inbox, web push, mobile, chat.
- **Workspaces:** git repositories and folders, local or in a sandbox.

### 5.6 Example, in words

"Review labelled pull requests":

1. **Start.** "Handle the pull requests labelled needs-review."
2. **Find pull requests.** Roster: one Claude agent. Handoff: a list of pull requests. A list is required because the next group repeats for each.
3. **Group, repeat for each pull request:**
   - **Review.** Roster: one Claude reviewer and one Codex reviewer. Handoff: each reviewer's findings.
   - **Orchestrator node.** The orchestrator reads both reviews and chooses "approved" or "changes requested".
   - **Fix,** on "changes requested". Roster: one Claude implementer. Done when: relevant unit tests, lint and format checks pass for the changed code. The arrow back to Review has a limit of three passes. At the limit, the run goes to the human gate with the open findings.
   - **Human gate,** on "approved": approve the merge.
4. **Summarize.** Roster: one Claude agent. Handoff: a report per pull request.
5. **End.**

## 6. What the diagram guarantees

| Promise | Label |
|---|---|
| The run only follows arrows that exist. Loop limits hold. Joins wait for all branches. | Enforced |
| Human gates are never skipped. | Enforced |
| Each step uses exactly its roster, or up to its allowed numbers. | Enforced, in separate-session mode and in sub-agent mode with the fail-closed router |
| Required rules hold. | Enforced, or the workflow is invalid |
| A step cannot close without its handoff and its checked parts. | Verified |
| "Done when" is backed by the session record. | Verified |
| Coral-run checks succeed. | Verified, by Coral running them itself |
| Guidance rules. | Requested |

Some things are deliberately not promised. They are recorded so that the user can see and question them:

- the orchestrator's choice among the arrows that exist at an orchestrator node, which is always recorded with its reason;
- how the agents do their work, and the quality of that work.

### 6.1 How "done when" is checked

When the workflow is saved, a model translates "done when" into an **evidence requirement**, and the author confirms it in plain words. For example, "relevant unit tests, lint and format checks pass" becomes:

- After the last change to the workspace in this step, a test command ran and exited successfully.
- After that change, a lint command and a format check ran and exited successfully.

Three details make this dependable:

- **"Last change" comes from the workspace**, not from the type of tool call. After each command an agent runs, the engine records a fingerprint of the workspace: the files git tracks, plus new files that git would not ignore. Files covered by `.gitignore`, such as caches, `node_modules` and build output, are left out, so running tests does not count as a change. Changes made through shell commands, code generators or `git apply` count like any other edit.
- **Commands are recognized from patterns** stored for each repository, such as the test, lint and format commands the repository uses. They are proposed once from the repository's configuration (for example `package.json`, `pyproject.toml`, a `Makefile` or the CI configuration) and confirmed by the author.
- **The result comes from the exit code** recorded by the agent's tool, not from the command's printed output, so printing "tests passed" does not count.
- **Gaming is limited, not impossible.** An agent could run only an easy subset of the tests, or a command that always succeeds. The check proves that suitable commands ran and passed, not that they were sufficient. That is why the label is Verified, not Enforced. Authors who need more add a verifier (a fresh agent that judges the work) or Coral-run checks (section 6.2).

If evidence is missing, the engine tells the step's agents what is missing ("No test run after the last change to `api/users.ts`"), and they continue. When the attempts run out, the step takes its failure path.

### 6.2 Coral-run checks

Agents choose their own commands while they work. Coral-run checks add a safety net that does not depend on those choices: after the agents finish, Coral itself runs commands in the step's workspace and requires each to exit successfully.

- **Repository checks.** The repository's standard test, lint and format commands, detected once and confirmed by the author, as in section 6.1. A workflow or step can turn on "run repository checks when code changed". This is the common case and needs no command written by hand.
- **Pinned commands.** A specific command for a specific step, for example a slow end-to-end test suite.

If a Coral-run check fails, its output goes back to the step's agents, and the step continues, within its attempts. Coral-run checks cost time but no model usage. They are off by default, so that steps stay light and the agents keep their freedom, and templates for code changes turn them on.

## 7. How a run executes

### 7.1 Where the engine lives

The engine runs inside the Omnigent server as background workers. It talks to the rest of Omnigent through a small internal interface: create a session, send an event, read items, read status, and evaluate a policy.

### 7.2 Tools, and who calls them

Agents act through engine tools. Omnigent already serves its own tools to both Claude Code and Codex. The engine checks every call against the workflow and rejects illegal calls with a plain explanation. Every rejection is recorded.

| Tool | Called by | What the engine checks |
|---|---|---|
| `submit_handoff` | Each step agent | The caller belongs to the active step. The report is present, along with the checked parts the step needs. "Done when" evidence passes. |
| `message_agent` | Step agents and the orchestrator | The recipient is the orchestrator, or an agent in the same step or in a step running in parallel. |
| `assign_agents` | Orchestrator | Only for "up to" rosters. The profiles and numbers are within the roster. |
| `choose_arrow` | Orchestrator | The label belongs to an outgoing arrow of the current orchestrator node. A reason is given. Loop limits still apply. |
| `ask_user` | Orchestrator | A question to the user, outside the human gates. |

Arrows without a decision **advance automatically**. When a step closes and its next box needs no decision, the engine starts that box itself. The orchestrator is only needed at orchestrator nodes. With several agents in a step, the step closes when every agent has submitted its handoff.

### 7.3 Keeping the run moving

- **Watchdog.** If the orchestrator does not make a decision at an orchestrator node within a set time, the engine reminds it once and then alerts the user.
- **Rejected calls.** After a set number of rejected calls in a row (three by default), the engine pauses the run and alerts the user, instead of letting an agent loop on illegal actions.
- **Overdue steps.** When a step or run exceeds its expected duration by a factor the user sets, the user is alerted, with the options to steer, extend or cancel.

### 7.4 Sessions and fresh context

Step agents run in **separate sessions** by default. Each agent gets its own rules, steering, workspace if needed, and direct messaging from the user. **Sub-agents in one session** are allowed for steps that need no per-agent evidence, such as several reviewers who only read. They are enforced through the sub-agent router in fail-closed mode. Once a bench probe shows that a mode reports which sub-agent did what, the restriction is lifted for that mode.

Step agents start with a **fresh context**. They receive the goal, the incoming handoff and references to files, not the orchestrator's conversation.

### 7.5 Long sessions: one refresh mechanism

When a session's context use passes a threshold, the engine waits for the end of the current turn. The threshold sits below the point where the agent compacts its own context automatically, so that Coral's refresh normally happens first; the default is 70%. Claude Code and Codex also shorten very large command output and compact on their own when needed, so a single large output in the middle of a turn does not crash the session. The agent's own compaction remains the backstop. It then asks the agent for a short handoff note, ends the session, and continues in a new session that receives the original brief, the run state and the note. Where the mode supports it, the author can choose native compaction instead.

The same mechanism keeps the orchestrator fresh. The user sees one continuous orchestrator conversation in the run view, with a small marker where a refresh happened.

### 7.6 Durable state

Run state lives in a small set of new tables: workflow versions, runs, step attempts and handoffs. Alongside them is an **append-only run log**: every step start, handoff, evidence result, decision with its reason, user answer and amendment. The log explains every path, feeds replay and powers improvement suggestions.

The engine uses Omnigent's `PersistentTaskScheduler` with its own store for timers and for the signal queue, instead of building new lease machinery.

Signal delivery is **at least once**. Every signal carries an idempotency key, and the run log ignores duplicates. On startup, the engine checks the durable state of every active step instead of trusting that no signal was lost.

The engine's tables have their own migration environment and their own version table, separate from Omnigent's migration chain. They can live in the same database as Omnigent's tables, but no Omnigent migration touches them and no engine migration touches Omnigent's tables.

Every row carries an owner and Omnigent's workspace identifier, ready for teams.

### 7.7 Versions and amendments

A run follows the workflow version it started with. Editing the workflow does not change running runs. To change a running run, the user chooses "Apply to this run". The engine creates an amendment that applies only to steps that have not started yet. The validator refuses an amendment that is incompatible with the steps that are currently active. Every amendment records who made it and why.

### 7.8 Pauses

Infrastructure problems and plan usage limits pause a step instead of failing it, and the step resumes when the cause clears. If a step's runner is lost, the step restarts in a new session from its incoming handoff. The engine never switches accounts.

## 8. Simulate

Simulate walks the diagram without agents and without cost. It does not imitate a model; it only feeds made-up results into the engine. For each step, the user or a template supplies made-up results: a handoff label, a list of a given length, or "done when" passing or failing. The run view then shows the path the run would take, the loop counts, which human gates would appear, and where limits would be hit.

It checks the diagram, not the agents. A simulation can be saved as a test case that runs automatically whenever the workflow file changes. Simulate is also how the engine itself is tested in phase 1: every routing rule, join, loop limit and gate can be exercised without starting a single agent. Simulate can also estimate the number of agent sessions a run would start, which feeds the cost estimate (section 10).

## 9. Rules

Rules are written in plain language and attached to the workflow, a group, a step or a profile. Rules on a group apply to everything inside it. An inner rule can only be stricter than the rules around it.

Each rule is either:

- **Required.** A model translates the rule into Omnigent settings: tool policies, MCP allow lists, sandbox settings or sub-agent limits. The author confirms the translation in plain words, and the stored translation is what runs. If the profile's agent mode cannot enforce the translation, the workflow is invalid. The author can change the profile or make the rule guidance instead. Required rules show as **Enforced**.
- **Guidance.** Given to the agents as instructions. Shown as **Requested**.

**Reactions** are rules that act during a step. They take the form "when X happens, do Y", for example "if this step runs for more than an hour, tell me" or "when an agent edits a migration file, ask me first". Reactions follow the same required-or-guidance rule.

To decide what each mode can enforce, we fill in the undeclared capability fields and add new ones:

- sub-agent visibility, kept separate from the existing `subagents` field, which means "can start Omnigent sub-agents";
- steering reliability (none, next turn, mid-turn);
- usage reporting;
- compaction;
- tool-call gating;
- end-of-turn detection.

Every field gets a harness bench probe.

**What each mode supports today,** according to the code (to be confirmed by bench probes):

| Action | `claude-sdk` | `claude-native` | `codex` | `codex-native` |
|---|---|---|---|---|
| Add input during a turn | Batched into a follow-up turn | Best-effort, pasted into the terminal | Yes (`turn/steer`) | Yes (`turn/steer`) |
| Interrupt | Yes | Yes | Yes | Yes |
| Read context use | Yes | Yes | Yes | Yes (`thread/tokenUsage/updated`) |
| Trigger compaction | Yes (`/compact`) | Yes (`omnigent/runner/native_controls.py`) | No | Yes (`omnigent/runner/native_controls.py`) |
| Gate tool calls | Yes | Yes (hooks) | Yes | Yes (hooks) |
| Report which sub-agent did what | No | Not reliably | Not confirmed | Not reliably |

Steps use the headless modes by default for dependable control. The validator applies the table above to every rule and reaction.

## 10. Cost and usage

A run spends usage on the orchestrator, on every step agent, on refreshed sessions, on verifiers, and once per save on translating rules and "done when". A roster with two reviewers that repeats for ten pull requests means at least twenty review sessions.

- **Estimate:** Simulate counts the sessions a run would start, and past runs supply typical usage per step. The run dialog shows the estimate before the run starts.
- **Budgets:** each run has a spending limit, and steps may have their own. Reaching a limit pauses the run and asks the user. This reuses Omnigent's `cost_budget` policy.
- **Plan limits:** a step that reaches a Claude or ChatGPT plan limit pauses and resumes when the limit resets.
- **Defaults that save usage:** "repeat for each" runs items one at a time unless the author allows more, and verifiers are opt-in.

## 11. Workspaces and artifacts

Each run gets a git worktree and branch, locally or in a sandbox. Agents that change code at the same time get their own worktrees, and merging is part of a step's work. Artifacts are files in the workspace or commits on the run's branch, recorded in the run log. For work that is not about code, the workspace is a plain folder.

## 12. Authoring

A workflow is a YAML file in `.coral/workflows/`, mostly plain language, with confirmed translations stored next to the text they translate. The canvas layout is a separate file. The canvas is a new route in Omnigent's web application, for example `/workflows`, because Omnigent's `/canvas` route already means something else. Editing works in both directions, and validation explains problems on the affected box. Templates are the starting point for most users.

## 13. Living with a run

- **Talk to the orchestrator** to steer, or open any agent's session and type into it.
- **The live view** shows the path, decisions with reasons, loop and repeat progress, evidence results, and the conversations at orchestrator nodes. Clicking an arrow shows why it was taken.
- **Take over and hand back:** the engine stops reacting while the user works in a step. On hand back, "done when" is still checked.
- **Approvals** work in the browser, the desktop app and on the phone.
- **Sharing** with teammates comes later, built on Omnigent's session sharing.

## 14. Improving workflows

An analysis workflow reads the run logs of finished runs. It looks for evidence that usually fails on the first try, loops that often reach their limit, growing costs, gates that are always approved unchanged, and orchestrator decisions that people later reverse. It proposes concrete edits with evidence, which a person accepts or rejects. Self-optimization, which goes further, is described as theory in the appendix.

## 15. Extensibility

**Now:** profiles, blocks, templates, MCP servers, and Omnigent's harness and sandbox plugins.

**Later, designed for:**

- custom step kinds and rule kinds through Python entry points;
- code steps;
- triggers;
- a marketplace (items containing code need review and sandboxing);
- workflows exposed as tools, API endpoints or agents.

A design-review template in the style of Google's Elephant-Goldfish Model, with an orchestrator holding context and reviewers with fresh contexts, is a strong showcase candidate. The model maps directly onto Coral's orchestrator and fresh step agents.

## 16. Fork and code placement

The fork exists for the product: the canvas inside Omnigent's interface, the Coral name and brand, and a few small changes to Omnigent's own code. The engine itself is kept as independent of the fork as possible, so that upstream merges stay cheap:

- The engine is a standalone Python package with its own tables and migrations (section 7.6). It depends on Omnigent only through the small internal interface in section 7.1, and it does not import Omnigent's internal modules anywhere else. If Omnigent's public API later covers that interface, the engine could run next to an unmodified Omnigent. The name is not "workflow": `omnigent/runtime/workflow.py` is Omnigent's agent loop and is unrelated.
- The canvas lives in its own folder under `web/src/`.
- Changes to Omnigent's files are few and listed in one place:
  - generalizing the completion hook;
  - a fail-closed mode for the sub-agent router;
  - capability fields;
  - the internal session interface;
  - fixes for the token and reaper issues, only if retests fail.
- We merge upstream from tagged releases on a schedule.
- We keep the Apache 2.0 license and notices, and we rebrand, because the name "Omnigent" belongs to Databricks.

## 17. Risks

1. **Subscription terms.** The default mode, `claude-sdk`, uses the Claude Agent SDK with the user's subscription sign-in. Anthropic asks products built on the Agent SDK to use API keys. Resolve this before building agent steps (section 18, phase 2). Two paths remain open either way:
   - **API keys** are a first-class option in every profile, because Omnigent already supports them. This is the safe path for any hosted or commercial use.
   - **`claude-native`** uses the unmodified Claude Code program with the user's own sign-in, which Anthropic's terms explicitly allow. Its weaker steering and sub-agent visibility are covered by the validator.
2. **Orchestrator judgment.** The orchestrator can choose badly among legal arrows. Mitigations: reasons on every choice, human gates, verifiers, improvement suggestions.
3. **Shallow evidence.** Evidence proves that checks ran, not that they were the right checks. Mitigations: verifiers and Coral-run checks.
4. **Translation errors.** A rule or "done when" can be translated wrongly. Mitigation: the author confirms every translation, and the stored translation is what runs.
5. **Upstream pace and alpha quality.** Weekly releases and very large core files make merging expensive.
6. **Agent updates** can silently break capabilities. Mitigation: harness bench probes.

## 18. Order of work

Each phase ends with something that runs, and with tests for its happy path and edge cases.

1. **Engine core and Simulate:** run state, run log, steps, arrows with labels and limits, joins, human gates, and Simulate with saved test cases. Test by killing the server in the middle of runs, by sending duplicate signals, and by forcing illegal arrow choices.
2. **Agent steps:** separate sessions, `submit_handoff` with checked parts, multi-agent handoff collections, fresh context, the signal queue and reconciler, the orchestrator and its tools, automatic advancing, the watchdog, and the fail-closed mode of the sub-agent router. Claude Code first.
3. **Evidence:** translation of "done when", command patterns, workspace change tracking, verifiers, Coral-run checks, and merging of parallel code changes.
4. **Rules and capabilities:** translation of required rules, capability fields with bench probes, validation, reactions, and session refresh.
5. **Canvas:** editing in both directions, then the live view.
6. **Structure:** groups, blocks, repeat for each, and parallel steps with live messaging.
7. **Codex, budgets and amendments.**
8. **Suggestions.**

The next document is the detailed build specification for phases 1 and 2. It covers the YAML schema with a complete example, table definitions, tool contracts, the internal interface, file-level patch locations and the test plan.

## 19. Decision log

The main choices, the alternatives we rejected, and why. This section exists so that later reviewers, who do not know the history, can see that these were decisions and not oversights.

| Decision | Rejected alternatives | Why |
|---|---|---|
| Build on a fork of Omnigent | Build our own harness; build a separate service on Omnigent's public API; build on Archon | Our own harness would rebuild what Claude Code and Codex already do well and would lose subscription use. A separate service could not put the canvas inside Omnigent's interface, whose extension system only allows sandboxed pages. Archon is YAML-first with no single orchestrator. The fork is kept thin (section 16). |
| A custom engine inside the server | Temporal, Prefect, Airflow, LangGraph | Temporal, Prefect and Airflow add a separate cluster or service for a product that must run on a laptop, and none of them knows about agent sessions, handoffs or evidence. LangGraph is a library for writing agents in code, not for supervising Claude Code and Codex. The engine borrows their ideas (durable state, idempotent handlers, a run log) without the infrastructure. |
| Steps in plain language; agents choose their commands | Typed contracts and fixed commands for every step | Rigid steps are tiring to write and feel robotic. Guarantees come from the diagram, evidence and optional Coral-run checks instead. |
| Evidence by default, Coral-run checks as an option | Coral-run commands as the main gate | Keeps agents free to choose relevant checks, and keeps steps cheap. Coral-run checks are one setting away when certainty matters. |
| One orchestrator that proposes; the engine accepts | Fully engine-driven routing; fully agent-driven routing | Model judgment where it helps, guarantees where they matter. |
| Plain, readable writing in workflows and documents | Formal graph terminology | The product and its documents are for people. |

## 20. Open questions

1. Is Codex in the first version, or the one after?
2. Which showcase template comes first: the pull-request review loop, the design review, or both?
3. What is the default watchdog time for orchestrator decisions?
4. Who may apply edits to a running run once teams arrive?
5. When do we revisit workflows as tools or agents?

## Appendix: theory of self-optimizing workflows

Not planned for building. A workflow has a structure (steps, arrows, rosters, gates, required rules) and parameters (goals, models, roster sizes, limits). An optimizer would search the parameters, and possibly the structure, against a set of evaluation tasks. Example methods are reflective rewriting of instructions in the style of GEPA, or choosing models per step by trial.

The hard boundary: the optimizer may never weaken evidence requirements, Coral-run checks, required rules, verifiers or human gates, because the cheapest way to "improve" a workflow is to delete its tests. Results would be measured on tasks the optimizer has not seen. The system may get better at reaching goals that people define. It may not redefine the goals.

Everything this needs is already part of the design: decisions that are recorded, complete run logs, checked handoffs, evidence as an objective signal, and versioned workflow files.
