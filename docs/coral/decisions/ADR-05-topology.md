# ADR-05: Session topology for a Coral run

- **Status:** Proposed — pending tech-lead and INTEGRATION-lead sign-off.
- **Date:** 2026-11-15
- **Decides:** TLD-02 / X-1 / OQ-32 (roadmap §D.9), option B, anchor variant.
- **Evidence:** permanent tests in
  `tests/server/integration/test_session_host_launch.py` and
  `tests/runtime/test_subagent_block_notifier.py`, plus the live probe
  [`probes/spk02_live_topology.py`](probes/spk02_live_topology.py).

## Context

Coral runs a workflow as a family of Omnigent sessions on the user's host. A
run needs one stable session that owns the run's gates, sharing and sidebar row.
Its step sessions must run on runners of their own, survive an orchestrator or
anchor stop, and never wake that session.

Omnigent's defaults work against this:

- A child created with `parent_session_id` inherits its parent's `runner_id`,
  whatever its own `host_id` (`omnigent/server/routes/_sessions/orchestration.py:12037-12053`).
- The host launch runs only when the new session has a `host_id` and no
  runner is bound yet (`omnigent/server/routes/sessions/routes_core.py:1395`).
- A child blocked on an unanswered approval wakes its parent after 120 s
  (`omnigent/runtime/subagent_block_notifier.py:57`).

So **a child gets its own runner exactly when it has a `host_id` and its
parent has no runner.** If the anchor were created with a `host_id`, it would
own a runner, and every step would silently share that runner with no launch
at all.

## Decision

Option B, anchor variant:

```text
anchor (root; no host_id, so no runner; inert agent; never takes a turn)
 ├─ orchestrator child   host_id=h, workspace=<run worktree>, labels {omnigent.parent_wake: off, coral.*}
 ├─ step child           host_id=h, workspace=<run worktree>, same labels, own runner
 └─ step child           …
```

## Topology rules

1. **The anchor is created without `host_id`, and it never gets a runner.**
   Without a runner on the anchor, its children cannot inherit one.
   The counter-case is pinned by test (B).
   - Omnigent does not enforce the rule: a session's owner can attach a runner
     (`PATCH /v1/sessions/{id} {"runner_id": …}`, OWNER only, or
     `POST /v1/hosts/{host_id}/runners`), and later children would ride it.
     Since CRL-131, Coral's mutation guard (S53) refuses both on a bound
     anchor. A runner attached anyway (data from before the guard, or a path
     the guard does not cover) is `anchor_bound` drift: the run pauses and
     Coral stops that runner (see "Rule 1 and the anchor seed").
   - So the facade (SES-03) re-reads the anchor before each step create and
     refuses to create the step while `anchor.runner_id` or `anchor.host_id`
     is set.
2. **Every child is created with `host_id` and `workspace`, and with no `git`
   options.** `workspace` is the run worktree that Coral creates once,
   request-free (`coral/workspace/run_worktree.py`). The `git` create mode
   would make a new branch and worktree per session.
3. **Every child carries `omnigent.parent_wake: off`.** This covers the
   orchestrator and each step (S51). The facade (SES-03) sets the label at
   create, because the key is not reserved.
4. **Before archiving or deleting an anchor, stop each step and confirm its
   runner is offline.** Use `stop_session` on each step, which ends its runner
   because the step owns it (test (A)). Then confirm with
   `GET /v1/runners/{id}/status`. Archiving or deleting the anchor itself ends
   no step runner (see Consequences). SES-09 owns automating this.
5. **The engine identifies steps only by the session ids it created and
   stored in its run record.** It never identifies a step by listing the
   anchor's children or by filtering on labels.
   - Omnigent lets anyone with READ on the anchor add children to it, with any
     title, agent and labels (`orchestration.py:11803-11815`). Since CRL-131,
     clients cannot set a `coral.*` label on any session (S46), and on a bound
     session Coral's mutation guard (S53) refuses child and sibling creates and
     any change to an `omnigent.*` label (`omnigent.parent_wake` included)
     other than `omnigent.pinned`
     ([`../contracts/session-facade.md`](../contracts/session-facade.md), "Run
     protection").
   - An EDIT collaborator can relabel real steps (`routes_core.py:3141-3156`).
   - `coral.*` labels are display hints only, never identity or authorization.
6. **Anchors stay private or are shared at EDIT only, until the upstream fix
   lands.** Any grant on the anchor applies to every step, and today a
   read-only or public grant exposes every step's workspace files (see
   "Access" below and open item 4). Coral must not run with default-public
   sessions set to `all`, or must revoke `__public__` on anchors at create
   (SES-03).

## Consequences

| Concern | Omnigent behaviour (evidence) | Consequence for Coral |
|---|---|---|
| Runner | A child inherits the parent's runner (`orchestration.py:12037-12053`). The launch runs only when no runner is bound (`routes_core.py:1395`). | The anchor has no runner, so each step launches its own (test A). A host-bound anchor captures every step (test B). |
| Recovery root | A child with a `host_id` counts as independent when its runner connects (`omnigent/server/app.py:4642-4646`). | Each step is the recovery root of its own runner. |
| Stop | A stop stops only the runner the session owns, with no cascade to children (`routes_events.py:2073-2206`; `_stop_host_runner_intentionally`, `orchestration.py:832`). | An anchor stop leaves the steps alone. A step stop ends only that step's runner (test A, live probe). |
| Archive, delete | Neither ends a step runner. Both first call `_best_effort_stop`, which stops only the *turns* of descendants that this replica's in-memory status cache shows as running or waiting (`orchestration.py:730-794`, descendant loop at `:792`); this is what `tests/server/integration/test_sessions_archive.py:209` and `tests/server/routes/test_sessions_crud.py:248` pin. Archive then tears down a host runner only for the archived session itself (`orchestration.py:1024`), and the anchor has none. Delete runs runner cleanup only for the deleted session (`routes_events.py:4133-4158`), never calls `_stop_host_runner_intentionally`, and then hard-deletes the whole subtree (`routes_events.py:4224`). | Rule 4. Idle steps keep their runners until the runner idle reaper fires. A step whose running status this replica missed keeps running with no row and no stop route. SES-09 automates the stop-and-confirm; an upstream fix could tear down descendant-owned runners in archive and delete (open item 5). |
| Relaunch | Only roots relaunch when a held host returns (`omnigent/server/app.py:4326`). | Coral relaunches a lost step's runner in its own session (SES-06; probe (f) in "Addendum: CRL-137 probe verdicts"). |
| Managed hosts | `host_id` is rejected on a managed child, which "runs on its parent's host" (`omnigent/server/schemas.py:1807-1811`). | Unsupported. Local hosts only through M4 (WSP-04). |
| `_owns_host_runner` | A child owns its runner only if no ancestor shares the runner or is unbound on the same host. A missing ancestor row also makes it "not own" its runner, which leaves the runner up: fail-open for containment (`omnigent/server/routes/_sessions/helpers.py:6261-6315`). A stop on a step that does not own its runner still returns 202 while the runner stays (`routes_events.py:2115-2147`). | With no `host_id` on the anchor, each step owns its runner, and a step stop sends exactly one stop (test A). An anchor with the steps' `host_id` but no runner would make every step "not own" its runner, so a stop or archive would leave it running (a leak, found by reading). |
| Access | Access to a child recurses to its parent; the child's own grants are ignored (`omnigent/server/permissions.py:59-65`). Children get no default-public grant of their own; they follow the parent's (`routes_core.py:1419-1436`). | Every grant on the anchor is a grant on the whole run, and a step cannot be shared on its own. EDIT on the anchor lets a collaborator message, stop and answer approvals on any step. A message to a step whose runner is offline relaunches it on the owner's host (`routes_events.py:3306-3358`, `_sessions/helpers.py:6417-6480`). READ or a public link exposes every step's workspace files (rule 6, open item 4). |
| Parent wake | A block wakes the parent after 120 s (`subagent_block_notifier.py:57`). | S51 label on every child (next section). |

## What S51 fixes, and who can set the label

**What it fixes.** A runner-less anchor cannot take a wake
turn anyway:

- The wake attempt finds no runner, logs a warning and returns `False`
  (`orchestration.py:10741-10750`).
- The notifier makes three attempts (`1 + _WAKE_RETRIES`), then releases the
  arm.
- A re-publish of the same approval starts the 120 s escalation again.

The live probe saw exactly those three wake attempts for the unlabelled child.
S51 (`subagent_block_notifier.py`, the guard after the top-level return) removes
that churn for labelled children. It also protects any parent that does have a
runner, such as a future orchestrator-parented step, from wake turns. The
approval itself is unchanged. It stays pending and answerable in the child, in
the ancestor mirrors, in the Inbox and on `/approve`. Completion wakes are not
affected.

**Who can set it.**

- Writing the label on an existing child (`PATCH /v1/sessions/{child}`) needs
  EDIT on the child. Access to a sub-agent delegates to its parent,
  recursively, so this means EDIT on the family root. That is the level that
  answers the child's approval (`ELICITATION_RESOLVE_LEVEL = LEVEL_EDIT`,
  `omnigent/server/routes/sessions/routes_elicitations.py:60`).
- Setting it at create needs only READ on the parent
  (`orchestration.py:11803-11815`). Such a child can run only with a runner:
  - It can inherit a runner, but only one the caller owns. That check holds
    only while the runner is online: `runner_owner()` returns `None` for an
    offline runner (`orchestration.py:12045-12053`,
    `omnigent/runner/routing.py:348-360`). This is one more reason for rule 1.
  - It can get one through a host launch. That needs OWNER on the session,
    which for a child means the root (`omnigent/server/routes/_host_launch.py:274-288`).
    It also needs a host that the caller owns (`_host_launch.py:122-152`).

  So a read-only viewer's labelled child never runs and never blocks.

Whoever can mute the nudge can therefore already answer the approval, or
created the child themselves. The label grants, hides and resolves nothing.

**Per-link rule.** The label governs only the link
between the labelled child and its parent. The ancestor mirror re-publishes a
child's approval on every ancestor. In `R → C → G(off)`, G's block does not
wake C, but C's mirrored copy, being unlabelled, still wakes R.

Coral's sessions are all direct children of the anchor, so this does not
arise today. Any future intermediate session that must stay silent needs the
label too (SES-03).

## Probe verdicts

The permanent tests are in `tests/server/integration/test_session_host_launch.py`:

- (A) `test_run_anchor_children_own_runners_and_outlive_its_stop`;
- (B) `test_host_bound_anchor_children_ride_its_runner`, kept as the named pin for rule 1;
- (C) `test_run_anchor_woken_only_by_child_without_parent_wake_off`.

They run in process: `_HostFrameResponder` answers the host frames, and no
runner process connects. They are **server-routing proof** through the real
create, stop and event routes and the real notifier, and they are the permanent
CI proof. The live probe adds real processes.

| Probe | Question | Verdict | Evidence |
|---|---|---|---|
| (a) | Do two own-runner claude-sdk children in separate worktrees keep their shell cwd and writes in their own worktree? | **not run** | Not run in this ticket: it needs the claude CLI with credentials (or SPK-03's spike-4 mock). SPK-04 spike 8 found that the default macOS seatbelt blocks git (the Xcode shim) and `$TMPDIR`, so sandboxed shells in a linked worktree are unproven. Owner: CRL-128, with a Linux bwrap rerun of spike 8. |
| (b) | Does a zero-turn anchor host children that run and finish? (roadmap SPK-02) | **pass** — a zero-turn anchor hosts own-runner children that launch, connect and stop. Children taking turns to completion are not exercised: that needs a model, and is covered later by CRL-128/CRL-137. | (A). Counter-case: (B). Live probe: `anchor_has_no_host_or_runner`, `children_own_distinct_runners`, `both_runners_connected`. |
| (c) | Does S51 stop the parent wake? | **pass with S51** | (C), which fails both with the guard removed and when the guard raises instead of returning. Label matrix: `tests/runtime/test_subagent_block_notifier.py::test_parent_wake_label_gates_escalated_wake`. Live probe: `both_blocks_pending_through_grace`, `unlabelled_child_wake_attempted_after_grace`, `labelled_child_wake_never_attempted`. |
| (d) | Stop, then replace, the orchestrator child; do siblings keep running? (roadmap SPK-02) | **pass** — stopping one child stops only its runner, a replacement launches its own, and siblings keep their runners (in-process). The live probe covers stop only. | (A): an anchor stop sends no runner stop; a step stop stops exactly its runner; after the replacement launches, the sibling still has its runner and is not marked as stopped. Live probe: `anchor_stop_keeps_both_runners`, `child_stop_stops_only_its_runner`. |
| (e) | Does an anchor gate count once in the Inbox, resolve once, and resolve after `omnigent.closed`? | **not run** | Needs Inbox and gates (GTE). Owner: CRL-134. |
| (f) | Do children relaunch after a host or runner restart? | **not run** | Needs the relauncher (SES-06). Owner: CRL-128. |
| 14 | What does a post to an archived session do? | **not run** | Owner: CRL-128 (with SES-09). |
| 15 | Can a step agent use a sibling's bridge-dir bearer on its loopback router? | **decided: not blocking for claude-sdk steps** | No such bearer exists for Coral steps; same-user residuals remain. See "Addendum: probe 15". |

### Live probe

`docs/coral/decisions/probes/spk02_live_topology.py` runs on real processes,
with these pieces:

- `tests._helpers.live_server.isolated_local_server` and
  `tests._helpers.host.isolated_host`;
- an SDK agent that is never sent a message;
- a temporary git repo as the workspace.

Isolation:

- The data dir, database, HOME and harness socket root all sit in one private
  temp directory under `/tmp`, as the test suite does for the AF_UNIX path
  limit.
- The server and host start with a minimal environment that has no provider
  credentials.
- The Claude, Codex and Pi CLI paths point at a stub that exits at once.
- By design the probe makes no non-loopback calls.
- SIGINT, SIGTERM and SIGHUP clean up as a normal exit does.
- No CI job runs it, so rerun it before relying on it after changes to the
  helpers it borrows.

The two children differ in label and in liveness:

- Child 1 is unlabelled and is stopped first.
- Child 2 carries the S51 label and stays live.

That does not confound the result. The approval is published on the server
whatever the runner's state:

- `mcp_elicitation` is always published server-side (`routes_events.py:2222-2251`).
- The pending index has no liveness condition (`omnigent/runtime/pending_elicitations.py:152-163`).
- The notifier reads no runner state before the label check
  (`subagent_block_notifier.py:296-305`).

So the stopped control shows that being stopped does not suppress the
escalation. Test (C) isolates the label: both children are in the same state
there, and removing the guard makes the labelled child attempt a wake.

Before waiting out the grace, the probe checks that both approvals are pending.
It checks again after the grace, so the labelled child's silence is a
registered block whose wake attempt was suppressed, not a missing block. The labelled
child blocks first, so its grace ends before the control's.
`unlabelled_first_wake_attempt_after_s` is a lower bound on the delay from the
control's block to its first wake attempt, within one 0.1 s check.

Known probe limits: the processes inherit `TMPDIR`, so the host's startup
cleanup of dead native-bridge and terminal temp dirs runs in the user's temp
folder (on Linux, inside `/tmp/omnigent-<uid>`), as the pytest suite's does.
The host's boot readiness check looks up `claude` and `cursor-agent` directly,
so a copy installed in git's directory, `/usr/local/bin` or `/opt/homebrew/bin`
may be run with `--version` and `auth status` (isolated HOME, no credential
variables). The recorded runs found none installed there.

Rerun from the repository root (about two and a half minutes):

```sh
uv run --no-sync python docs/coral/decisions/probes/spk02_live_topology.py
```

The run recorded here is from 2026-11-16 UTC, on macOS, on commit `24e710dd9`
with a clean working tree (`base_commit_dirty: false`). It exited with code 0
after 136 s and left no stray processes. Earlier runs during development also
passed. Verdict, as printed:

```json
{
  "probe": "spk02_live_topology",
  "verdict": "pass",
  "date": "2026-11-16",
  "base_commit": "24e710dd9",
  "base_commit_dirty": false,
  "platform": "Darwin",
  "python": "3.12.12",
  "grace_s": 120.0,
  "checks": {
    "anchor_has_no_host_or_runner": true,
    "children_own_distinct_runners": true,
    "label_persisted": true,
    "both_runners_connected": true,
    "anchor_stop_keeps_both_runners": true,
    "child_stop_stops_only_its_runner": true,
    "both_blocks_pending_through_grace": true,
    "unlabelled_child_wake_attempted_after_grace": true,
    "labelled_child_wake_never_attempted": true
  },
  "observed": {
    "anchor_stop_status": 202,
    "child_stop_status": 202,
    "block_status": [
      202,
      202
    ],
    "unlabelled_first_wake_attempt_after_s": 120.0,
    "labelled_block_age_at_check_s": 126.1,
    "wake_attempts": {
      "unlabelled": 3,
      "labelled": 0
    }
  },
  "duration_s": 135.7,
  "error": null
}
```

## Fallback

The costed fallback is **not triggered**: (b) passes for own-runner children
that launch, connect and stop (no child takes a turn), and (c) and (d) pass. In the
fallback, steps would be top-level family sessions with engine-managed grants
and the S35 watch-set union, at +3-4 engineer-weeks on SES-03 (roadmap §D.9).

Probe (a) did not run. Its question is a workspace one: whether a sandboxed
shell works in a linked worktree. The SPK-04 spike-8 contingency already
answers it by keeping K13 write ops engine-owned. The fallback should be
reconsidered only if CRL-128's run of (a) fails for a topology reason, for
example a step's shell not starting in its own `workspace`. The same holds for
the turn-to-completion half of (b).

## Open items

1. **Native step children's completion path (CRL-128).** This was traced by
   reading and is not yet verified by a run.
   - `_schedule_subagent_wake` (`omnigent/runner/app.py:5051-5069`) wakes a
     parent only after a delivery into an inbox on the same runner
     (`omnigent/runner/subagent_work.py:857-883`).
   - For a native step child on its own runner:
     1. `_ensure_subagent_work_entry` (`omnigent/runner/subagent_recovery.py:82-102`,
        called at `omnigent/runner/app.py:7547, 7633`) rebuilds a work entry
        whose parent is the anchor.
     2. Delivery returns `MISSING_PARENT_INBOX` (`subagent_work.py:857-883`).
     3. `_parent_is_nested_subagent(anchor)` is `False`
        (`subagent_recovery.py:104-121`).
     4. `_subagent_delivery_not_confirmed_response` returns 503
        (`subagent_work.py:1133-1173`).
   - The anchor is therefore not woken, but every turn-end status from a
     native step child gets a 503, and the forwarder retries it.
   - Non-native children created with `POST /v1/sessions` have no work entry,
     so nothing is delivered.
   - S51 does not cover this path.
2. **Probes (a), (e), (f) and 14**, and the turn-to-completion half of (b),
   with the owners in the table above. The ADR-05 addenda record their
   verdicts. Probe 15 is decided, and its residual probes have owners
   ("Addendum: probe 15").
3. **Facade guards (SES-03).**
   - Re-check the anchor before each step create (rule 1).
   - Never give the anchor a `host_id`. An anchor that has the steps' host but
     no runner makes step stops and archives leave runners up.
   - Identify steps only by stored ids (rule 5).
   - Label every intermediate session that must not wake its parent.
   - Server-side reservation of `coral.*` labels can follow in SES-03/CRL-126.
4. **Upstream fix candidate: workspace reads bypass the file-sharing opt-in
   for child sessions.** This is pre-existing upstream behaviour.
   - The workspace content-read gate admits a caller when
     `access.level is None or access.level >= LEVEL_EDIT or conv.share_workspace_files`
     (`omnigent/server/routes/sessions/routes_resources.py:917`). The comment
     at `:913-916` reads `level is None` on a child as access inherited from
     the parent.
   - For a sub-agent, `level` comes only from grants on the child row, with no
     parent walk (`omnigent/server/routes/_auth_helpers.py:339`). So a viewer
     whose access is inherited from the anchor passes, whatever their real
     level, and the owner's `share_workspace_files` opt-in (off by default) is
     bypassed.
   - This is pinned by `tests/server/routes/test_shell_permission_gate.py:482`
     (case `child-inherited-viewer`, which expects 200 in the test at `:497`).
     The same viewer is denied 403 on every content surface of the parent
     (`:672-686`).
   - Under default-public `all` with sharing `on` or `read_only`, the anchor
     starts public: it is a root with no host and no workspace
     (`_sessions/helpers.py:692-725`; `omnigent/server/sharing_settings.py:399-422`).
   - The restricted-workspace share gate checks only the shared session's own
     `workspace` (`omnigent/server/routes/sessions/routes_permissions.py:131-140`),
     which is `None` for an anchor.
   - **Fix:** in `_authorize_browse_read_with_owner`, resolve a child's
     effective level through the parent chain, and read
     `share_workspace_files` from the root. Treat only
     `permission_store is None` as "permissions disabled". Flip the
     `child-inherited-viewer` expectation to 403 and add a shared-flag case.
   - Rule 6 applies until the fix lands.
5. **Upstream candidate: archive and delete leave descendant-owned runners
   up.** `_archive_stop` and `delete_session` could tear down every
   descendant runner for which `_owns_host_runner(descendant)` holds. Rule 4
   applies until then.
6. **Optional upstream hardening.**
   - Spec-policy label writes can set `omnigent.parent_wake` on the session
     they guard.
   - A suppressed wake leaves no log line.
7. **Sign-off.** The tech lead and the INTEGRATION lead sign ADR-05 v1.

## Addendum: CRL-128 probe verdicts (2026-11-16)

CRL-128 built the request-free session facade, engine dispatch and the
status-edge observers on this topology, so it records the probes it owned. The
topology rules hold as written; the facade enforces rules 1, 2, 3, 5 and 6 at
create (`coral/omni/server/sessions.py`), and drift pauses a run whose anchor
is archived, deleted or bound to a runner
([`../contracts/session-facade.md`](../contracts/session-facade.md), "Drift").

| Probe | Verdict | Evidence or reason | Owner |
|---|---|---|---|
| (a) | **not run** | Needs a real model (Tier B). Its workspace half no longer gates anything: engine git runs on the user's host, outside the agent's sandbox (SPK-04 contingency, [`../contracts/workspace-ops.md`](../contracts/workspace-ops.md)). | CRL-137 (Tier B); verdict in "Addendum: CRL-137 probe verdicts" |
| (b), turn-to-completion half | **not run** | Needs a real model. Coral's view of a turn end through the real server, relay and runner is proven in process, with a stub harness and outside the anchor topology: `tests/coral/omni/test_ac2_stop_cancel_end_to_end.py`. | CRL-137 (Tier B); verdict in "Addendum: CRL-137 probe verdicts" |
| (e) | **not run** | Needs Inbox and gates. | CRL-134 (unchanged) |
| (f) | **not run** | Needs the engine relauncher. Steps are created only through the facade, which never relaunches a step the owner archived or deleted. | CRL-137 (SES-06); verdict in "Addendum: CRL-137 probe verdicts" |
| 14 | **pass for engine sends** | An engine send to a run whose anchor or step is archived or deleted is refused before anything is saved or forwarded, and the run pauses as `paused(drift, <cause>)`: `tests/coral/omni/test_drift.py::test_archived_anchor_pauses_the_run_and_refuses_the_send` (archived anchor, real `PATCH`), `tests/coral/recovery/test_drift.py::test_the_pre_send_hook_pauses_the_run_and_refuses_the_send` (archived anchor, archived step, deleted step). A user's post to an archived session was not probed. | user posts: full SES-09 drift, no live ticket |
| 15 | **not run** | Outside CRL-128's deliverables. | decided by the engine bridge, see "Addendum: probe 15"; run on single-user servers, see "Addendum: CRL-137 probe verdicts" |

Also found or decided in CRL-128:

- **Stop, cancel and close reach the engine as cancelled.** A Coral stop,
  cancel or reader's close of a session ends its turn as `cancelled` for that
  turn's response, never `completed`, for an interrupted turn, an interrupt
  with buffered input, a runner-cancelled turn, a runner that survived a
  disconnect, and a close whose turn outlives its bound:
  `tests/coral/omni/test_ac2_stop_cancel_end_to_end.py::test_coral_stop_and_cancel_reach_coral_as_cancelled`.
  It runs the runner-forwarded stop and interrupt, which production also runs
  first, on a hostless session bound with `PATCH runner_id`, not a facade step.
  The host-owner runner kill and the server's own inferred `cancelled` edge are
  covered only by component tests
  (`tests/server/routes/test_intentional_runner_stop.py`,
  `tests/coral/omni/test_status_edges.py`).
- **Open item 1 (native step completion).** Native-harness steps are refused at
  create (`session.harness_not_supported`) until HRN-03, so the 503 loop cannot
  occur for Coral steps. The open item stays for HRN-03 (CRL-138).
- **Rule 1 and the anchor seed.** If an owner binds a runner to the anchor, the
  run pauses (`anchor_bound`). CRL-128 removed `permission_mode:
  bypassPermissions` from the anchor seed (CRL-132's PRF-01), so the harness
  default applies. Since CRL-131 (RUL-01) the mutation guard refuses a client
  attaching a runner to a bound anchor, every anchor tool call is denied, and
  after an `anchor_bound` pause Coral stops the anchor's session on that runner
  (and the runner itself when the anchor owns a host runner) as the run owner,
  best effort and without unbinding it, unless another session uses that
  runner ([`../contracts/session-facade.md`](../contracts/session-facade.md),
  "Anchor runner").

## Addendum: probe 15 (2026-11-18)

The engine bridge enables claude-sdk runs, so probe 15 had to be decided
first. It was decided by reading the code; no live probe ran.

**Question.** Can a step agent use a sibling's bridge-dir bearer on its
loopback router?

**Findings.**

- **No bridge-dir bearer exists for a Coral step.** The turn router serves
  only the `codex-native` and `claude-native` harnesses
  (`_TURN_HOOK_HARNESSES` in `omnigent/runner/turn_routing.py`), and native
  harnesses are refused as steps (`session.harness_not_supported`). For an SDK
  harness the subagent router starts only when the session's routing class has
  routing on (`ensure_session_router_quietly` in
  `omnigent/runner/subagent_routing.py`). `routing_class_from_snapshot` turns
  it on for `cost_control_mode_override == "on"`, `harness_override == "auto"`
  or the label `omnigent.routing.auto_harness == "1"`. Step and orchestrator
  creates set no `cost_control_mode_override`, no `subagent_routing_override`
  and no harness override, which
  `tests/coral/omni/test_session_facade.py::test_stance_creates_run_the_owners_bundles_and_enable_no_routing`
  pins. The mutation guard refuses every `PATCH` field of a bound session but
  `title`, `archived`, `delete_worktree`, `family_pinned`, `silent` and
  `labels`, and every `omnigent.*` label but `omnigent.pinned`
  (`coral/omni/server/mutation_guard.py`), so `omnigent.routing.auto_harness`
  cannot be set and routing cannot be turned on later.
- **Even with a bearer the router is narrow.** It listens on loopback for its
  own session's path and relays spawn verdicts to an EDIT-checked route; step
  bundles set `spawn: false` (`coral/profiles/bundle_spec.py`).
- **Engine tools need runner proof.** Each step has its own runner (rule 1 and
  test (A)), and the harness child's environment has the runner's
  authentication secrets removed (`strip_runner_auth_secrets` in
  `omnigent/runner/identity.py`, applied by `_build_harness_spawn_env` in
  `omnigent/runtime/harnesses/process_manager.py`).

**Residuals.** Each needs a step shell running as the same OS user that the
sandbox does not confine.

- **(a) The harness socket.** On POSIX each conversation's harness listens on
  a Unix socket that file permissions isolate by user but nothing
  authenticates: the per-spawn bearer is set only on Windows
  (`omnigent/runtime/harnesses/process_manager.py`, the auth check in
  `omnigent/runtime/harnesses/_scaffold.py`). A step shell that can connect to
  a sibling's socket can drive that sibling's turn, including its
  `coral_submit_handoff` through the sibling's own runner, which the server
  accepts. On macOS, since S112, a sandboxed step's connect to a harness
  socket under the configured or the per-user default root is denied,
  measured on 27.2.1 (see "Addendum: CRL-166 harness sockets on macOS").
- **(b) The runner's environment.** A runner's environment as it was at exec
  holds its tunnel binding token (`omnigent/runner/_entry.py`) and, for a
  host-launched runner, the host's initial bearer
  (`OMNIGENT_RUNNER_INITIAL_AUTH_TOKEN`, set by `omnigent/host/connect.py`;
  the runner removes it from `os.environ`, not from that copy). The same user
  can read it through `/proc/<pid>/environ` on Linux and `ps eww` on macOS,
  unless the sandbox hides other processes. The binding token proves that
  runner on `/mcp`, and on a server with authentication that can mint
  (accounts or OIDC) it mints an owner JWT through
  `POST /v1/runners/{runner_id}/token` (`omnigent/server/routes/runner_tunnel.py`).
  A reader can therefore act as the run owner on every route, not only the
  engine tools, so an owner-authenticated gate answer, resume or cancel does
  not prove that a person took it while this residual is open.
  `omnigent run` also sets an allow-listed token, `OMNIGENT_RUNNER_TUNNEL_TOKEN`,
  in its local server's environment; it is that server's runner's binding
  token, and the server accepts it for every session
  (`omnigent/server/mcp_identity.py`). Whether a Coral step can run on such a
  server is unverified.
- **(c) Bridge dirs.** A step shell can read the bridge-dir bearers of the same
  user's native or Smart Routing sessions on the host; Coral steps have none.
- **(d) Credential files.** A step shell can read the user's credential files.

Whether the claude-sdk OS sandbox (seatbelt on macOS, bwrap on Linux) blocks
any of these is unverified.

**Decision.** Probe 15 does not block claude-sdk steps. The surface it asks
about does not exist for Coral steps, and every residual needs a step that
already acts as the user: it shares the run worktree and the user's
credentials. Handoff and gate integrity hold against other users and on the
server's path, not against a same-user step whose shell the sandbox does not
confine ([`../contracts/session-facade.md`](../contracts/session-facade.md),
"Residuals and limitations"). A per-spawn harness bearer on POSIX would be an
Omnigent change, a Coral-owned seam; it is recorded here as an owner decision,
not planned. Reopened by CRL-166: planned as defence in depth in CRL-173 (see
"Addendum: CRL-166 harness sockets on macOS").

| Follow-up | Owner |
|---|---|
| The Tier B sandbox probe on macOS seatbelt and Linux bwrap: connect to a sibling's harness socket, read sibling runners' environments (`/proc/<pid>/environ`, `ps eww`), sibling bridge dirs and the user's credential files; and from the step shell: HTTP to the Omnigent server on loopback and the configured URL, with no credentials and with the CLI's stored credentials; before the walking skeleton is declared done. It also settles whether a Coral step can run on a server with the allow-listed token, and whether a runner started with `OMNIGENT_RUNNER_TUNNEL_TOKEN` exported passes it to the harness child (the strip list does not name it) | **Run on single-user servers only**, without credentials, in CRL-137 (`tests/e2e/coral/test_sandbox_probe.py`). macOS seatbelt, one local run: a step reaches a sibling's harness socket (before S112, now `denied`, see "Addendum: CRL-166 harness sockets on macOS"), other processes' environments and command lines (the model API key in every claude-sdk CLI's among them; before S111, now `denied`, see "Addendum: CRL-165 process reads on macOS") and the server; the three probed credential files (Claude's, Omnigent's secrets and the host's tunnel tokens, in the stack's isolated home), the config file's key and the stack's bridge dir are `denied`; no other credential store was probed. Linux bwrap, the `coral-e2e` lane: the server is reachable and every other target is `hidden`, the step's own CLI included. A step runs on an allow-listed-token server, and the token is in its runner's and harness's environment as read from outside the sandbox; the step's shell read it on macOS only (before S111; now `denied`). Tables, limits and owners (CRL-159, CRL-165 to CRL-168): "Addendum: CRL-137 probe verdicts" |
| Label a gate Enforced only when that probe passes and the server runs a mode that requires identity, in which steps hold no owner credential; gates on single-user or auth-off servers are never Enforced. No gate is labelled Enforced today ([`../contracts/gates-and-inbox.md`](../contracts/gates-and-inbox.md)) | RUL-02 (CRL-159) |
| Run probe 15 on native steps before HRN-03 enables them | CRL-138 |

## Addendum: gates on the anchor (2026-11-19)

Gates now reach people: each live gate visit is one prompt on its run's
anchor and one alert in the owner's workflow Inbox, and the owner's answer
advances the engine once
([`../contracts/gates-and-inbox.md`](../contracts/gates-and-inbox.md)). This
records the probe the gate work owned.

| Probe | Verdict | Evidence or reason | Owner |
|---|---|---|---|
| (e) | **pass** | Through the real routes: one prompt on the anchor and one Inbox item; the anchor labelled `omnigent.closed` still takes the answer, which advances the run once; a repeat is a duplicate; the gate's alert clears; after a restart the same prompt returns and is answerable (`tests/coral/omni/test_gate_end_to_end.py`). Two answers at once commit once (`tests/coral/workers/test_worker_lifespan.py::test_two_answers_at_once_through_the_resolve_route_advance_the_gate_once`). An edit grantee and an admin are refused with the prompt left pending (`tests/coral/omni/test_gate_routes_auth.py`), and so is a re-created account (`test_gate_routes_accounts.py`). In the web app the workflow Inbox kind claims the anchor's gate prompt, so the real Inbox page shows the shared contract's gate as exactly one card while a mirrored step prompt stays an approval, the card answers through the anchor's resolve route, and a gate alert whose prompt is missing is still one answerable card (`web/src/workflows/inbox/workflowInboxKind.test.tsx`). | closed |

Also decided:

- **Who may answer.** Only the run owner, checked by Coral's verdict handler
  after Omnigent's own edit check: an edit grant on the anchor (a grant on the
  whole run) lets a collaborator read the prompt but not answer it, and an
  admin is refused too. The handler takes the run from the anchor's binding,
  so a gate prompt relayed onto any other session cannot answer the gate.
- **Integrity.** On servers that require no identity, any process of the
  owner that can reach the server answers as the owner; on authenticated
  servers a same-user step that escapes the sandbox can mint an owner token
  (probe 15, residual (b)). The labelling rule in the follow-up table above
  applies.

## Addendum: CRL-137 probe verdicts (2026-11-21)

CRL-137 ran Coral on real processes: a server subprocess with the Coral plugin,
a real host daemon that launches each step's runner, and the real `claude`
CLI, with every model call scripted on `mock_llm_server`
([`../testing/tier-b.md`](../testing/tier-b.md)). It records the probes that
needed that, the sandbox probe 15, and what the host now does with a step
runner's processes. Every verdict is from a mock model; no real model ran.

| Probe | Verdict | Evidence | Owner |
|---|---|---|---|
| (a), run-worktree half | **pass** | The implementer and the reviewer, each on its own runner under the anchor, run their shell in the run worktree: the implementer's write and its `grep` there pass the step's `done_when`, the reviewer's write is refused as report-only and leaves the worktree unchanged, and the outcome's checkout command puts the implementer's file in the repository (`tests/e2e/coral/test_skeleton.py::test_the_review_loop_runs_end_to_end_on_a_real_stack`). | closed; the separate-worktrees half is CRL-140 |
| (b), turn-to-completion half | **pass** | The zero-turn anchor hosts four step sessions (two passes of each step) that take turns to completion, hand off and end; one anchor and one session per slot activation, each briefed once, no drift pause, no refused runner event (same test). | closed |
| (f) | **pass** | A step runner whose process group is SIGKILLed is relaunched in the same session and generation within about a second, with one loss and one wake (`tests/e2e/coral/test_runner_loss.py::test_a_killed_step_runner_is_relaunched_in_the_same_session`). A SIGKILLed host daemon holds the step with Cancel only, and the respawned host's return relaunches it in the same session as one loss (`::test_an_offline_host_holds_the_step_and_its_return_relaunches_it`). A SIGKILLed server's step runner reconnects with the same runner id and is not relaunched, mid-step and under the production lease (`tests/e2e/coral/test_skeleton.py::test_the_review_loop_survives_server_sigkills_mid_step_and_at_the_gate`, `::test_a_runner_reconnecting_after_a_default_lease_restart_is_not_relaunched`). macOS seatbelt locally, Linux bwrap in the `coral-e2e` lane. | closed |

For (f), on macOS a `killpg` of a step runner empties its whole group (the
runner, its harness, the sandbox launcher and the CLI) at once, and a host
SIGKILL empties each runner's group within about 5 s through the runner's own
parent-loss kill. On Linux the CLI is a descendant of the runner's group, not a
member: bwrap's `--new-session` puts the in-sandbox launcher and the CLI in a
session of their own, and they end through bwrap's die-with-parent once the
group's `bwrap` is killed. The tests therefore capture the runner's process
tree before the fault, run it only when the tree holds the step's `claude`,
and wait for the group and the tree to end (`group_tree`, `group_tree_ended`
in `tests/e2e/coral/_skeleton.py`). Linux timings are not recorded here.

### S108: a Coral step runner's process group ends with it

The host now ends a Coral step runner's own process group whenever that
runner exits, clean or not, and before it answers a stop of it or a status
query with `dead`; a step runner that outlives its host ends its own group
(seam S108, `.coral/seams.yaml`;
[`../contracts/session-facade.md`](../contracts/session-facade.md), "Runner
process groups"). The host marks a runner as a Coral step runner at spawn
from its workspace alone: a checkout on a Coral run branch. Every runner
outside such a checkout, so every non-Coral session elsewhere, is signalled
exactly as before; a non-Coral session opened in a run worktree is marked too.
The group is recorded at spawn only when the runner leads it and it is neither
the host's nor the zygote's, and members are signalled one by one, only those
whose start time lies between the runner's start and its observed exit. A step
loses every process left in its group when its runner exits, background
processes its agent started included. What escapes: a process that starts its
own session, except inside a bwrap sandbox, whose pid namespace ends with it.
What could be signalled wrongly: a process in a new group that reuses the id
within about 1.5 s of the reap (the exit is observed that late), which needs a
pid wrap to that exact id.

### Probe 15 on single-user servers

`tests/e2e/coral/test_sandbox_probe.py::test_probe_15_from_a_step_shell`
runs `tests/e2e/coral/probe15.sh` from a generated implementer's shell, the
widest stance Coral generates, while a reviewer step on a parallel branch is
held mid-turn so its runner, harness socket and CLI are live. The test
resolves every target on the host side and proves it live right before the
probe call is released and again after the result; a removed target fails as
a failed control, never as a verdict. The probe prints tokens only:
`reachable` (connected, or the canary matched), `denied` (`EACCES`/`EPERM`),
`hidden` (`ENOENT` on a target the host proved exists) and `not_present`;
`mismatch` and `unclassified` fail the test. Each environment target also has
`.api_key` and `.argv_api_key` sub-checks: whether the configured model API
key's canary is in that process's environment, and in its command line.
Canaries are random and planted with exclusive creates; the test never reads
the host's tunnel credential file, only its metadata. The pins are change
detectors, and the test refuses a pinned `reachable` without an owner.

**macOS seatbelt.** `EXPECTED["darwin"]`, pinned from one local run on macOS
27.2.1 with claude 2.1.325 (`RECORDED["darwin"]`):

| Check | Verdict | Names read | API key in environment / command line | Owner |
|---|---|---|---|---|
| `harness_socket` (the reviewer's) | `reachable` | | | CRL-166 (closed by S112, see "Addendum: CRL-166 harness sockets on macOS") |
| `runner_environ` (the reviewer's runner) | `reachable` | `none` | `not_present` / `not_present` | CRL-165 (closed by S111, see "Addendum: CRL-165 process reads on macOS") |
| `cli_environ` (the reviewer's CLI) | `reachable` | `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` and 13 `HARNESS_CLAUDE_SDK_*` names | `reachable` / `reachable` | CRL-165 (closed by S111, see "Addendum: CRL-165 process reads on macOS"); the key CRL-167 |
| `host_environ` | `reachable` | `none` | `not_present` / `not_present` | CRL-165 (closed by S111, see "Addendum: CRL-165 process reads on macOS") |
| `own_cli_environ` (the step's own CLI) | `reachable` | as `cli_environ` | `reachable` / `reachable` | CRL-165 (closed by S111, see "Addendum: CRL-165 process reads on macOS"); the key CRL-167 |
| `credential_files.claude` | `denied` | | | |
| `credential_files.omnigent_secrets` | `denied` | | | |
| `credential_files.host_tunnel` | `denied` | | | |
| `config_api_key` | `denied` (the config file only) | | | |
| `bridge_dir` | `denied` | | | |
| `server_loopback` (`http://127.0.0.1:<port>`) | `reachable` | | | CRL-159 |
| `server_localhost` (`http://localhost:<port>`) | `reachable` | | | CRL-159 |
| `shell_env_names` (the step's own shell) | `not_present` | `none` | | |

**Linux bwrap.** `EXPECTED["linux"]`, pinned from `coral-e2e` lane run
44980984569 on Ubuntu 24.04.5 LTS (kernel 7.0.0-1017-azure) with claude
2.1.295 (`RECORDED["linux"]`):

| Check | Verdict | Names read | API key in environment / command line | Owner |
|---|---|---|---|---|
| `harness_socket` (the reviewer's) | `hidden` | | | |
| `runner_environ` (the reviewer's runner) | `hidden` | | `hidden` / `hidden` | |
| `cli_environ` (the reviewer's CLI) | `hidden` | | `hidden` / `hidden` | |
| `host_environ` | `hidden` | | `hidden` / `hidden` | |
| `own_cli_environ` (the step's own CLI) | `hidden` | | `hidden` / `hidden` | |
| `credential_files.claude` | `hidden` | | | |
| `credential_files.omnigent_secrets` | `hidden` | | | |
| `credential_files.host_tunnel` | `hidden` | | | |
| `config_api_key` | `hidden` | | | |
| `bridge_dir` | `hidden` | | | |
| `server_loopback` (`http://127.0.0.1:<port>`) | `reachable` | | | CRL-159 |
| `server_localhost` (`http://localhost:<port>`) | `reachable` | | | CRL-159 |
| `shell_env_names` (the step's own shell) | `not_present` | `none` | | |

Reading the tables:

- On macOS, `denied` is seatbelt's `(deny default)` with
  `(allow file-read-metadata)`: the shell can `stat` the files but not read
  them. Nothing is `hidden` there: macOS has no pid namespaces. In this run a
  step read other processes' environments and command lines, its own CLI's and
  a sibling CLI's included (CRL-165). The mechanism is in "Addendum: CRL-165
  process reads on macOS", and since S111 those reads are `denied` (measured on
  macOS 27.2.1).
- **Before S111, on macOS the model API key was not protected.**
  `config_api_key: denied` covers only `config.yaml`. The same key was
  `reachable` in every claude-sdk CLI's environment
  (`HARNESS_CLAUDE_SDK_API_KEY_HELPER`, `HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND`)
  and command line (`--settings` `apiKeyHelper`), the step's own CLI and its
  sibling's (the key helper is built in `omnigent/runtime/workflow.py`). Its own
  CLI was enough, so no sibling was needed.
- On Linux, in the lane, `hidden` is a namespace boundary, not a lookup miss
  (see Limits for where that has not been measured). The step's shell runs in
  the runner's `os_env` helper, which bwrap wraps on its own
  (`omnigent/inner/os_env.py`, `wrap_launcher_argv`); the CLI's launcher is
  wrapped separately (`omnigent/inner/sandbox.py`). Each wrap has its own
  `--unshare-pid` namespace (`omnigent/inner/bwrap_sandbox.py`) and its own
  `/tmp` and home mounts, so the step's own CLI, the sibling CLI, the runner
  and the host are all outside the shell's namespace, and the host-side
  controls show each one alive before and after the probe.
- `runner_environ.names` and `host_environ.names` are `none` on macOS only
  because the stack starts from `minimal_env()`. Before S111, a host started
  from a person's shell exported every credential-like name it was started
  with to what a macOS step read there. Names outside the probe's patterns
  (`OMNIGENT_RUNNER_*TOKEN*`, the binding-token name,
  `OMNIGENT_RUNNER_INITIAL_AUTH_TOKEN`, `*API_KEY*`, `HARNESS_CLAUDE_SDK_*`),
  such as `ANTHROPIC_AUTH_TOKEN`, are not reported.
- `harness_socket: reachable` is a connect only. Residual (a) above says a
  connection is enough to drive the sibling's turn; the probe does not. Since
  S112 it is `denied` on macOS (measured on 27.2.1).

**Limits.**

- **Single-user servers only.** Both runs used a header-auth single-user
  server, and the HTTP checks used `/health` with no credentials. Servers that
  require identity (owner-token minting after an environment read, the CLI's
  stored credentials) are CRL-159, RUL-02's ticket. The gate labelling rule in
  the follow-up table above is unchanged: every gate here is on a single-user
  server, and none is Enforced.
- **macOS is one local run, not a regression guard.** No CI lane runs macOS.
- **CI lifts Ubuntu's AppArmor restriction** on unprivileged user namespaces
  (`kernel.apparmor_restrict_unprivileged_userns=0` in `.github/workflows/ci.yml`),
  so bwrap can make its namespaces. A host that keeps the restriction was not
  measured: there bwrap may be unable to make its namespaces (the backend has
  no silent fallback), or an AppArmor profile may change what it can do.
- **The socket root is the stack's own.** Both runs put the harness sockets
  under the stack's private `/tmp/crl-*` root (`OMNIGENT_HARNESS_TMP_PARENT`),
  and the bridge-dir canary under the stack's `TMPDIR`. This is not
  generalized: production sockets sit under `/tmp/omnigent-<uid>` on POSIX,
  macOS included (`omnigent/runtime/harnesses/paths.py`), and production bridge
  dirs under the per-user `$TMPDIR/omnigent-<uid>/claude-native`
  (`omnigent/harnesses/claude_native/bridge.py`). S112 denies the configured
  root and the per-user default root by the same `subpath` rule; its behaviour
  test measures both, a throwaway configured root and a throwaway socket under
  the real `/tmp/omnigent-<uid>` (see "Addendum: CRL-166 harness sockets on
  macOS").
- **Only three credential files were probed**, each a canary in the test host's
  isolated home: `~/.claude/.credentials.json`, `~/.omnigent/secrets.json` and
  `~/.omnigent/auth_tokens.json`. No other store was probed: not the macOS
  Keychain (the step profile allows `mach-lookup`), `~/.aws`, `~/.ssh`, or
  `gh`'s and `databricks`' configs. Residual (d) is narrowed for these files
  only, and credentials the host was started with stay readable in its runners'
  environments to processes outside the sandbox. Since S111 a macOS step's
  shell does not read them directly (measured on 27.2.1).
- **The checkout read grant was on.** The runs used an editable checkout, so
  generated step bundles granted the sandbox read access to the installed
  `omnigent` and `coral` package directories (`checkout_read_paths`,
  `coral/omni/server/step_agents.py`). That also widens what the file tools can
  read; a wheel install grants only the worktree.
- **The host was given `http://127.0.0.1:<port>`**; both spellings were probed.
- The probe ran from the implementer only. The reviewer's `read_only_os`
  policy screens its shell, and probing from it needs a second choreography.

**Owners.** Each pinned `reachable` names a filed ticket, each blocked by
CRL-137, which lands the probe that verifies its fix. None blocks CRL-137
itself: the probe only measures exposures that already exist.

| Exposure | Owner |
|---|---|
| A step connects to another session's harness socket (`harness_socket`, macOS) | CRL-166 (closed by S112, see "Addendum: CRL-166 harness sockets on macOS") |
| A step reads other processes' environments and command lines (`runner_environ`, `cli_environ`, `host_environ`, `own_cli_environ`, macOS) | CRL-165 (closed by S111, see "Addendum: CRL-165 process reads on macOS") |
| Secrets in exec-time environments and argv, the model API key among them (every `.api_key` and `.argv_api_key` `reachable`, macOS, before S111; processes outside the sandbox still read them) | CRL-167 |
| The allow-listed runner token in the step runner's environment (below) | CRL-168 |
| A single-user server takes any local process as its owner (`server_loopback`, `server_localhost`, both platforms) | CRL-159 (RUL-02) |

CRL-166 reopened the decision in "Addendum: probe 15" that a per-spawn harness
bearer on POSIX is recorded but not planned; it is now planned in CRL-173 (see
"Addendum: CRL-166 harness sockets on macOS").

**Open for the owner.** Whether to run Coral steps on untrusted content is the
owner's risk decision, stated with its open tickets in "Addendum: CRL-166
harness sockets on macOS". It is not decided here.

### A step on a server that keeps the allow-listed runner token

`test_a_step_on_a_server_with_the_allow_listed_runner_token` runs one step on
a server that keeps `OMNIGENT_RUNNER_TUNNEL_TOKEN` (the binding token of
`omnigent run`'s local server, which that server accepts for every session),
with the host exporting the same test-only value. The names are read from
outside the sandbox, from each process's environment as another process reads
it (`EXPECTED_TOKEN`):

| Observation | macOS (`EXPECTED_TOKEN["darwin"]`) | Linux (`EXPECTED_TOKEN["linux"]`) |
|---|---|---|
| The step runs and hands off (`step_runs`) | `true` | `true` |
| Token names in the runner's environment (`runner.names`) | `OMNIGENT_RUNNER_TUNNEL_TOKEN` | `OMNIGENT_RUNNER_TUNNEL_TOKEN` |
| In the harness's environment (`harness.names`) | `OMNIGENT_RUNNER_TUNNEL_TOKEN` | `OMNIGENT_RUNNER_TUNNEL_TOKEN` |
| In the sandbox launcher's environment (`launcher.names`) | `none` | `none` |
| In the CLI's environment (`cli.names`) | `none` | `none` |
| In the step's own shell (`shell_env_names`) | `not_present`, names `none` | `not_present`, names `none` |
| The step's shell reading its own runner's environment (`runner_environ`) | `reachable`, names `OMNIGENT_RUNNER_TUNNEL_TOKEN` (CRL-168; before S111, now `denied`) | `hidden` |

So the step runs on such a server; the token is in its runner's and harness's
readable environments on both platforms, and absent from the launcher's, the
CLI's and the shell's. The step's own shell read it from its runner on macOS
only (before S111; now `denied`); on Linux that read is `hidden`.

**Exec-time and live environments.** These are exec-time environments. The
host starts its runner zygote with its whole `os.environ`
(`omnigent/host/runner_zygote.py`, `_spawn_zygote_process`), and a forked
runner, and a harness the zygote forks for it, keep the zygote's exec-time
environment, which is what another process reads. Their live `os.environ`
differs: a forked runner replaces it with the runner environment the host
built (`fork_runner`), and a harness's has the runner's authentication secrets
removed (`strip_runner_auth_secrets`, `omnigent/runner/identity.py`). The
sandbox launcher and the CLI are started with environments of their own, so
what another process reads there is what they started with.

**Caveats recorded with it.**

- A host `unknown` counts as dead, so a relaunch can start while the old runner
  lives on ([`../contracts/session-facade.md`](../contracts/session-facade.md),
  "The one relaunch path").
- On a server like this, runner-id rotation does not fence a runner that
  survived that way, because the server accepts the allow-listed token for every
  session (`omnigent/server/mcp_identity.py`).

**Residual (b), extended.** On the zygote path, a reader sees the host
daemon's whole environment, for runners and zygote-forked harnesses alike. On
the direct-spawn fallback (`OMNIGENT_RUNNER_ZYGOTE=0`, or the zygote
unavailable or dead), it sees the binding token and the initial bearer, as
residual (b) already says (from code: `_build_runner_env`,
`omnigent/host/connect.py`; not measured). Residual (b) is extended, not
replaced. The allow-listed-token test
(`test_a_step_on_a_server_with_the_allow_listed_runner_token`) measured the
zygote path on both platforms. Giving the zygote the filtered runner environment would be an
Omnigent seam (CRL-167).

## Addendum: CRL-165 process reads on macOS (2026-11-22)

CRL-165 closes the process reads that probe 15 found on macOS seatbelt. A
step's shell read the command line and exec-time environment of every
same-user process that is not an Apple platform binary: a sibling runner's
(the host's whole environment on the zygote path), each claude-sdk CLI's (the
model API key in `HARNESS_CLAUDE_SDK_API_KEY_HELPER` and `--settings`) and the
host daemon's. Seam S111 (`.coral/seams.yaml`) adds four rules to
`omnigent/inner/seatbelt_sandbox.py`. Everything here was measured on macOS
27.2.1 (26B131) only, with claude 2.1.325 and a mock model. No CI lane runs
macOS (CRL-170).

**The four read paths.** Sandbox.kext is closed source, so this is measured
behaviour, not documented semantics.

| Path | What it read | Why it was open | Closed by |
|---|---|---|---|
| `sysctl` `KERN_PROCARGS2` and `KERN_PROCARGS` on another pid (psutil `environ()` and `cmdline()`, probe 15's reader) | argv and exec-time environment | Seatbelt checks the names `kern.procargs2.<pid>` and `kern.procargs.<pid>`, and admits the read when either `sysctl-read` allows the name or `process-info` allows the target. The profile allowed `sysctl-read` unfiltered, and `(deny default)` does not cover `process-info*`, so `(allow process-info* (target self))` narrowed nothing. A `sysctl-read` deny alone, the ticket's first proposal, changes nothing | the `process-info*` deny and the `kern.procargs` deny together |
| libproc on another pid (`proc_pidinfo`, `proc_pidpath`, `proc_pidfdinfo`) | path, cwd, the fd list, open-file and socket paths, POSIX shared-memory names | `process-info*` was open for every pid | the `process-info*` deny |
| `sysmond` (`pgrep -lf`, `pkill` and its other clients) | any command line | `(allow mach-lookup)` reaches the root daemon `com.apple.sysmond`, which answers entitled clients such as `pgrep` | the `com.apple.sysmond` deny |
| launchd job introspection (`launchctl print`, `dumpstate`) | any launchd job's environment and arguments (measured on a throwaway job; from code, the `ai.omnigent.host` LaunchAgent holds provider credentials and the host token there) | launchd answered the sandboxed client | the `process-info*` deny: launchd then refuses (rc 1); why is not confirmed |

**The rules.** They sit in `_build_profile`'s baseline block, so every profile
it emits gets them, whatever its network or egress mode:

```
(deny process-info*)
(allow process-info* (target self))   ; existing
(allow process-info-listpids)
...
(allow mach-lookup)                   ; existing
(deny mach-lookup (global-name-prefix "com.apple.sysmond"))
...
(allow sysctl-read)                   ; existing
(deny sysctl-read (sysctl-name-prefix "kern.procargs"))
```

In the orders the design reviews measured, the more specific rule of each
pair decided. Each narrowing deny comes after the broad allow it narrows, and
the `process-info*` deny comes before its two re-allows; that placement does
not prove that order never matters. The profiles are the os_env step shell's
and every spawn-time CLI wrap's (the claude CLI, codex, pi, qwen, goose, kimi,
ACP agents and terminal-launched CLIs), so non-Coral sandboxed sessions on
macOS change too.
Only the claude CLI ran under the rules. Coral's host-ops git jail builds its
own profile and does not get them.

**What was measured.** Reads of other processes' environments, arguments and
open-file paths only; nothing here measures the residuals below.

- Probe 15, two local runs (`EXPECTED["darwin"]`): `runner_environ`,
  `cli_environ`, `host_environ` and `own_cli_environ`, and each one's `.api_key`
  and `.argv_api_key`, are `denied`. Their `.names` lines are gone, because the
  probe prints names only for a `reachable` read. `control_environ` and its
  sub-checks stay `reachable`, every other pin is unchanged, and the run
  completes with no cause. Test 9 (`EXPECTED_TOKEN["darwin"]`): `runner_environ`
  is `denied`. The probe reads only through `KERN_PROCARGS2`.
- `tests/inner/sandbox/test_sandbox_behavior.py::test_sandbox_cannot_read_another_process_command_line_or_environment`
  starts a child that holds random markers in its environment, its argv and an
  open file's name, and loads a launchd job that never runs, holding a marker.
  One reader runs outside the sandbox, and inside it through the os_env helper
  and through a CLI wrap (`create_exec_launcher`). Outside it gets all seven
  reads (both procargs sysctls, psutil `environ()` and `cmdline()`,
  `pgrep -lf`, `launchctl print` and `proc_pidfdinfo`), and inside it gets
  none. Inside it still reads its own environment and lists pids with
  `proc_listallpids`, and the child and the job are still there afterwards.
  Without the rules all seven reads succeed inside. Dropping one rule at a
  time: without the `process-info*` deny, procargs, psutil, `launchctl print`
  and the fd path reopen; without the `kern.procargs` deny, procargs and psutil
  reopen; without the sysmond deny, `pgrep` reopens; without the listpids
  allow, listing pids fails.
  `tests/inner/test_seatbelt_sandbox.py::test_profile_keeps_other_processes_arguments_and_environments_unreadable`
  pins the rules' text and order.
- The existing seatbelt and sandbox suites give the same result with and
  without the rules. Three git tests fail both ways: `/usr/bin/git`'s xcrun
  shim cannot load `libxcrun` inside the sandbox on this Mac.

**Collateral.** Inside every such sandbox, on any other pid, the sandboxed
process's own children included:

- `pgrep` and `pkill` exit 3, and `lsof -p` fails;
- psutil `cmdline()`, `environ()`, `exe()`, `cwd()`, `open_files()`,
  `memory_info()`, `cpu_times()` and `num_threads()` raise `AccessDenied`;
- libproc `proc_name`, `proc_pidpath`, `proc_pidinfo`, `proc_pidfdinfo` and
  `proc_pid_rusage` fail (Rust `sysinfo` and gopsutil use them);
- `launchctl print` and `blame` fail, and so does `dumpstate` (the design
  reviews measured `dumpstate` with the `process-info-pidinfo` deny alone);
- a tmux server started inside such a sandbox loses `pane_current_path`.

Still working: every read of the process itself; pid listing
(`proc_listallpids`, `proc_listchildpids`, psutil `pids()` and `children()`);
`kinfo_proc` (name, ppid, status, start time, uid); and every other sysctl.
The profile already refused signals to other pids, own children included.

**Residuals.** S111 stops the sandboxed reader only, for environments and
command lines, on macOS 27.2.1.

- A step still connects to other sessions' harness sockets, which residual (a)
  says is enough to drive their turns (CRL-166). Since S112 that connect is
  denied for AF_UNIX harness sockets under the configured and per-user default
  roots, measured on macOS 27.2.1 (see "Addendum: CRL-166 harness sockets on
  macOS").
- On a single-user server a step can act as the owner, on both platforms.
  From code, that includes starting a session with no OS sandbox, which S111
  does not cover (CRL-159).
- The secrets stay in exec-time environments and argv, the host LaunchAgent's
  `EnvironmentVariables` included. Processes outside the sandbox still read
  them, and other local accounts read command lines through setuid `ps`
  (CRL-167).
- The allow-listed runner token stays in runner and harness environments, and
  the server accepts it for every session (CRL-168).
- A sandboxed process still reaches the clipboard and Spotlight. Apple Events
  and screen capture were not measured (CRL-171).
- Other macOS releases, and CI (CRL-170). An unknown operation or filter makes
  `sandbox-exec` refuse the profile, which fails closed. A renamed service or
  sysctl name would make a rule a silent no-op instead, and the behaviour test
  and probe 15 detect that only on a Mac that runs them.
- A sandboxed process still lists pids and reads `kinfo_proc` (the 16-character
  name, ppid, uid and start time) of every process.
- The login keychain stays unreadable because of the profile's `~/Library`
  deny (S5 in `omnigent/inner/seatbelt_sandbox.py`), not because of S111.

## Addendum: CRL-166 harness sockets on macOS (2026-11-22)

CRL-166 closes the harness-socket connect that probe 15 found on macOS
seatbelt: a step's shell connected to the live reviewer's harness socket,
`<harness root>/ap-<id>/conv-<session>.sock` (`harness_socket: reachable`).
Seam S112 (`.coral/seams.yaml`) changes `omnigent/inner/sandbox.py`,
`omnigent/inner/seatbelt_sandbox.py` and `omnigent/inner/os_env.py`.
Every measurement here was taken on macOS 27.2.1 (26B131) only, with claude
2.1.325 and a mock model. No CI lane runs macOS (CRL-170). What S112 covers is
AF_UNIX harness sockets under the configured and per-user default roots, other
Omnigent terminals' tmux servers and the user's default tmux socket
(`tmux-<uid>`, with `-L` labels and `TMUX_TMPDIR`); nothing here measures the
residuals below. S111's process-read rules and their evidence are in
"Addendum: CRL-165 process reads on macOS".

**Root cause.**

- With `allow_network: true`, the default, the profile emits
  `(allow network*)`, which admits an AF_UNIX `connect(2)` to any pathname
  socket. The only AF_UNIX denies were `path-literal`s, for a terminal pane's
  own `tmux.sock` and for credential source files, and no harness path was
  among them. Without the network allow, `(deny default)` already refused every
  AF_UNIX connect.
- File permissions did not help. The root and its instance dirs are 0700 and
  the sockets 0600, but a sandboxed step is the same user, and seatbelt
  decides an AF_UNIX connect by its network rules, not its file rules: a
  sandboxed shell could not list `/private/tmp`, yet it connected.
- From code: the harness socket has no bearer on POSIX (residual (a); the
  per-spawn token is minted only on Windows,
  `omnigent/runtime/harnesses/process_manager.py`). The protocol is HTTP over
  the socket (`omnigent/runtime/harnesses/_scaffold.py`). A `message` event
  during the victim's live turn is injected into that turn, and the victim's
  own runner then sends its tool calls, `coral_submit_handoff` included, to
  the server as runner-proven. An `interrupt` cancels every in-flight turn.
- Socket paths were listable: `netstat -an -f unix` read the `net.local`
  pcblist sysctls and printed every bound path.

Three seatbelt behaviours the fix depends on, all measured:

- Seatbelt matches the resolved socket path, so a rule must name the
  realpath; a `/tmp/...` spelling matches nothing.
- A `path-literal` of a directory is a silent no-op, and so is a `path-regex`
  with a `{n}` quantifier.
- A filtered deny beats the unfiltered `(allow network*)` in either order, but
  between filtered rules the later one wins, so a filtered allow after a deny
  reopens it.

**The rules.** A step profile with `allow_network: true`, a configured root
`/tmp/crl-x`, uid 501 and one deny-listed pane socket gains these lines
(`<scratch>` is the child's `$TMPDIR`, `<pane>` a terminal pane's private
dir):

```
(allow sysctl-read)                                       ; existing
(deny sysctl-read (sysctl-name-prefix "kern.procargs"))   ; S111
(deny sysctl-read (sysctl-name-prefix "net.local"))
...
(allow network*)                                          ; existing
;; Omnigent harness and tmux control sockets
(deny network-outbound (remote unix-socket (subpath "/private/tmp/crl-x")))
(deny network-outbound (remote unix-socket (subpath "/private/tmp/omnigent-501")))
(deny network-outbound (remote unix-socket (path-regex #"/omnigent-terminal-[^/]+/tmux\.sock$")))
(deny network-outbound (remote unix-socket (path-regex #"/omnigent-tmux-replies-[^/]+/s$")))
(deny network-outbound (remote unix-socket (path-regex #"/tmux-501/[^/]+$")))
(allow network-outbound (remote unix-socket (subpath "<scratch>")))
(allow network-outbound (remote unix-socket (subpath "/private/tmp/crl-x/c<id>")))
;; AF_UNIX control-socket denials (last-match-wins)
(deny network-outbound (remote unix-socket (path-literal "<pane>/tmux.sock")))  ; existing
(deny file-write* (literal "<pane>/tmux.sock"))
(deny file-write* (literal "<pane>"))
```

- **Roots.** `resolve_sandbox` gives every active policy
  `deny_unix_socket_roots`: the configured root (`OMNIGENT_HARNESS_TMP_PARENT`)
  and the per-user default `/tmp/omnigent-<uid>`, resolved. The field travels
  in the launcher's policy JSON and through every clone. `_build_profile`
  denies each by `subpath` of its realpath, and always adds the per-user
  default, so a policy without roots (an old launcher payload) still gets it.
- **Tmux servers.** Three `path-regex` denies, in any directory: other
  Omnigent terminals' `omnigent-terminal-*/tmux.sock`, the tmux replies
  probe's `omnigent-tmux-replies-*/s`, and the user's default tmux socket,
  `tmux-<uid>/<label>` under `/tmp` or any `TMUX_TMPDIR` (`-L` picks the
  label). A terminal's `clip.sock` is not matched. A server on a `tmux -S`
  path elsewhere is not matched (CRL-174).
- **Placement.** The denies follow every network allow in every network mode,
  the egress and git-ssh `path-literal` allows included.
- **Re-allows.** Only where `(allow network*)` was emitted, the policy's own
  dirs are allowed again after the denies: the scratch the child gets as
  `$TMPDIR` (recorded on the policy by the os_env helper and the launcher host
  pass), and each write root strictly inside a denied root, such as S109's
  per-launch CLI dir (the `c<id>` line). A dir is not reopened if it is or
  holds the temp dir, or holds a denied root or a deny-listed socket, so other
  sessions' dirs and a pane's own tmux dir stay denied. In the other network
  modes AF_UNIX was already denied by default, and nothing is reopened.
- **Rename denies.** The existing literal deny of each `deny_unix_socket_paths`
  entry (today a pane's own `tmux.sock`) stays last, and now also denies
  writing that socket and its dir. A pane can rename neither its socket nor
  its private dir away from the deny; files inside the dir stay editable.
- **`net.local`.** The sysctl deny comes after `(allow sysctl-read)`, beside
  S111's `kern.procargs` deny, so `netstat -f unix` lists nothing.
- **Root resolution never raises.** A configured root that cannot be resolved
  (`~nosuchuser`, a symlink loop, a relative root in a deleted cwd) is left
  out with a warning, once per setting, and the default is kept. So a bad
  setting cannot fail `resolve_sandbox` into an unsandboxed run: the ACP
  executor runs its agent unsandboxed when `resolve_sandbox` raises an
  `OSError` (`omnigent/inner/acp_executor.py`). A relative root, or one that
  holds the temp dir or home, is kept with a warning.
- **Which profiles.** Every policy `resolve_sandbox` returns, Coral or not:
  the os_env step shell and every spawn-time CLI wrap (the claude CLI, codex,
  pi, qwen, goose, kimi, ACP agents and terminal panes). Coral's host-ops git
  jail builds its own profile and does not get them. bwrap ignores the field:
  its `--tmpfs /tmp` already hides the default root, and probe 15's Linux
  `harness_socket` pin stays `hidden`.

**What was measured.** Only connects to the sockets the rules name, and the
renames above.

- **Probe 15.** `EXPECTED["darwin"]["harness_socket"]` is now `denied`
  (`tests/e2e/coral/test_sandbox_probe.py`). Both stack tests pass locally,
  every other pin is unchanged, and
  `test_a_step_on_a_server_with_the_allow_listed_runner_token` still runs its
  step (`step_runs: true`). The stack's sockets sit under its own `/tmp/crl-*`
  root.
- **The behaviour test.**
  `tests/inner/sandbox/test_sandbox_behavior.py::test_sandbox_cannot_connect_to_omnigent_control_sockets`
  binds throwaway listeners and runs one probe outside the sandbox and inside
  it, through the os_env helper and through a CLI wrap
  (`create_exec_launcher`). The listeners are a conv and an mcp socket under a
  throwaway configured root, a socket under the real per-user default root,
  another terminal's `tmux.sock` and `clip.sock`, a replies probe's socket, a
  user tmux server's shape, and a pane socket that is deny-listed in a write
  root. Outside, every connect works. Inside:
  - the harness, default-root and tmux connects are refused;
  - `clip.sock` connects, and so do the probe's own sockets in its `$TMPDIR`
    (a nested terminal's shape included), in a write root under the harness
    root and, on the CLI-wrap path, in S109's launch dir;
  - renaming the pane's socket or its dir is refused, while editing files in
    the dir works;
  - `netstat -f unix` does not list the conv socket.

  The conv listener answers from outside after the run, so a dead listener
  cannot pass as a denial. Without the S112 lines every inside connect and
  rename succeeded.
- **Profile and policy tests.**
  `tests/inner/test_seatbelt_sandbox.py::test_profile_denies_omnigent_control_sockets_after_every_socket_allow`
  pins the rule text, and that the denies follow every network allow, in four
  network modes. `test_profile_does_not_reopen_a_dir_holding_other_sockets`
  and `test_profile_always_denies_the_per_user_default_root` pin the guards.
  `tests/inner/test_sandbox.py` pins the wire and the clones
  (`test_policy_clones_keep_every_field`), and resolution that never raises
  (`test_harness_socket_roots_never_raise_and_keep_the_default`).
- **Path spellings, in the design reviews.** With throwaway sockets, every
  spelling tried was refused: `/tmp` and `/private/tmp`, symlinks, `..` and
  `//`, case variants, the firmlink `/System/Volumes/Data/...`, volfs
  `/.vol/<dev>/<ino>`, and a datagram `sendto`. `connectx(2)` on AF_UNIX
  returns `EOPNOTSUPP` inside and outside the sandbox, and macOS 27.2 has no
  `connectat(2)`. A throwaway tmux server ran `run-shell` outside the sandbox
  under the old profile, and refused it under S112.
- **Existing suites.** The seatbelt, sandbox, os_env, terminal, clipboard and
  harness-auth suites give the same results as before. Three git tests fail
  both ways: `/usr/bin/git`'s xcrun shim cannot load `libxcrun` inside the
  sandbox on this Mac.

**Collateral.**

- Inside every such sandbox `netstat -f unix` prints no sockets, and reading
  the `net.local` sysctls fails.
- A process's own tmux server, or a nested Omnigent's terminals, outside its
  `$TMPDIR` scratch (for example with `TMUX_TMPDIR` in the worktree) cannot be
  connected to. That follows from the rules; it was not measured.
- A terminal pane cannot remove or rename its own private dir; that follows
  from the rule, and only the rename was measured.
- A configured root that holds the temp dir or home only warns. In egress or
  git-ssh mode, where nothing is reopened, it would also deny the policy's own
  broker socket. No Coral configuration does this.
- Unchanged, as measured in the design reviews and both stack tests: the
  process's own sockets in its scratch and its cwd, `clip.sock`, DNS,
  `multiprocessing`, and a full claude-sdk turn and handoff. Binding a socket
  is not affected.

**Residuals.** S112 stops a sandboxed process's connect to the sockets it
names, on macOS 27.2.1.

- Other macOS releases, and CI (CRL-170). An unknown operation or filter makes
  `sandbox-exec` refuse the profile, which fails closed. A change in how
  seatbelt checks AF_UNIX connects would make the rules a silent no-op
  instead, and the behaviour test and probe 15 detect that only on a Mac that
  runs them.
- A harness root other than these two stays reachable, such as another
  Omnigent instance's own `OMNIGENT_HARNESS_TMP_PARENT`, or a relative root
  that another process resolves against a different cwd (CRL-173).
- A harness root inside a sandbox write root is not protected: a step renames
  a socket out of it and connects. No Coral configuration does this (CRL-173).
- A root that does not exist when the profile is built, and is later created
  as a symlink to another directory, is not covered: the rule names the path
  as it resolved then. The harness process manager does not refuse a
  symlinked or foreign root (CRL-173).
- On Linux, a configured root under a path bwrap binds is visible (CRL-173).
- Processes outside the sandbox still connect: the harness socket has no
  bearer on POSIX (CRL-173).
- Other programs' sockets stay reachable, such as Docker Desktop's and
  ssh-agent's, and a tmux server on a custom `tmux -S <path>` socket, which
  runs commands outside the sandbox (measured with a throwaway server). So does
  Claude Code's cross-session inbox, which, read from the CLI binary, takes
  messages without a token on macOS; that was not measured. On Linux, bwrap
  shares the host's network namespace when the network is on
  (`omnigent/inner/bwrap_sandbox.py`), so other programs' abstract sockets stay
  reachable there; that is from code, not measured (CRL-174).
- `netstat` no longer lists socket paths, but the paths are not hidden:
  `fsgetpath(2)` still returns the path of a named inode, and every path's
  metadata is readable. That matters for sockets the rules do not name
  (CRL-174).
- Omnigent listeners outside both roots are not covered: on macOS the
  codex-native app-server socket under `~/.omnigent/codex-native/`, and on
  either platform loopback TCP listeners (the codex-native WebSocket
  app-server, opencode's server, claude-native's relays, the runner's
  direct-attach listener). That is from code, not measured (CRL-177).
- Other Omnigent terminals' clipboard sockets stay reachable (CRL-171).
- On either platform, every claude-sdk CLI wrap can write `~/.claude/plugins`,
  `sessions`, `session-env` and `backups` in the user's real home. A step
  could change a plugin hook, which the user's own Claude Code then runs
  outside the sandbox, and read the inbox keys in `sessions`. That is from
  code, not measured (CRL-176).
- On a single-user server a step acts as the owner on both platforms, so it
  can still send a message into another session, the reviewer's included,
  through the server (CRL-159). S112 does not restore review-gate integrity
  there.
- Secrets in exec-time environments (CRL-167) and the allow-listed runner
  token (CRL-168) are unchanged.

**The bearer decision, reopened.** Probe 15's addendum recorded a POSIX
per-spawn bearer as not planned while the sandbox's effect was unmeasured. It
is now measured: the sandbox did not stop the connect, and paths were
listable. S112 closes the connect on macOS 27.2.1 for harness sockets under
the configured and per-user default roots. The bearer is planned as defence
in depth in CRL-173: delivered off the exec-time environment (the zygote
payload, or an inherited fd on direct exec), removed from the harness's
`os.environ` before it spawns the CLI, and paired with a check that refuses a
harness root that is a symlink or not this user's 0700 directory. Kept off the
exec-time environment, it also stops an unsandboxed same-user process on
macOS, where `task_for_pid` is refused even outside the sandbox (measured in
CRL-165), from driving a harness socket directly; on Linux it does so only
where ptrace between same-user processes is restricted. It does not stop that
process from acting as the owner on a single-user server (CRL-159).

**Open for the owner.** Whether to run Coral steps on untrusted content on
macOS while CRL-171 is open, and on either platform while CRL-174, CRL-176 and
CRL-177 are open, is the owner's risk decision (on a single-user server,
CRL-159 holds on both platforms). S111 and S112 closed the process reads and
the connect to harness sockets under the configured and per-user default
roots, measured on macOS 27.2.1 only (CRL-170). It is not decided here.
