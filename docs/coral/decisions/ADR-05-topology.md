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
  server is unverified. Since S123, on POSIX, a host-launched runner's
  exec-time environment holds neither its binding token nor the initial
  bearer (see "Addendum: CRL-167 secrets out of exec-time
  environments").
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
| The Tier B sandbox probe on macOS seatbelt and Linux bwrap: connect to a sibling's harness socket, read sibling runners' environments (`/proc/<pid>/environ`, `ps eww`), sibling bridge dirs and the user's credential files; and from the step shell: HTTP to the Omnigent server on loopback and the configured URL, with no credentials and with the CLI's stored credentials; before the walking skeleton is declared done. It also settles whether a Coral step can run on a server with the allow-listed token, and whether a runner started with `OMNIGENT_RUNNER_TUNNEL_TOKEN` exported passes it to the harness child (the strip list does not name it) | **Run on single-user servers only**, without credentials, in CRL-137 (`tests/e2e/coral/test_sandbox_probe.py`). macOS seatbelt, one local run: a step reaches a sibling's harness socket (before S112, now `denied`, see "Addendum: CRL-166 harness sockets on macOS"), other processes' environments and command lines (the model API key in every claude-sdk CLI's among them; before S111, now `denied`, see "Addendum: CRL-165 process reads on macOS") and the server; the three probed credential files (Claude's, Omnigent's secrets and the host's tunnel tokens, in the stack's isolated home), the config file's key and the stack's bridge dir are `denied`; no other credential store was probed. Linux bwrap, the `coral-e2e` lane: the server is reachable and every other target is `hidden`, the step's own CLI included. A step runs on an allow-listed-token server, and the token was in its runner's and harness's environment as read from outside the sandbox (before S123; now in neither on the zygote path); the step's shell read it on macOS only (before S111; now `denied`). Tables, limits and owners (CRL-165 to CRL-168; the single-user server rows are an accepted residual): "Addendum: CRL-137 probe verdicts". **Run on an accounts server**, with the CLI's stored credentials and owner-JWT minting, in CRL-159: "Addendum: CRL-159 probe 15 on identity-requiring servers" |
| Label a gate Enforced only when that probe passes and the server runs a mode that requires identity, in which steps hold no owner credential; gates on single-user or auth-off servers are never Enforced | **Built** in CRL-159 as `gate_integrity` on the run detail; `enforced` needs an accounts server, verified config, no native steps and an empty table row for the run's host. Every row has open blockers today: CRL-170, CRL-171, CRL-174, CRL-181, CRL-193, CRL-195 ("Addendum: CRL-159 probe 15 on identity-requiring servers"; [`../contracts/gates-and-inbox.md`](../contracts/gates-and-inbox.md), "Enforced gates") |
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
| `cli_environ` (the reviewer's CLI) | `reachable` | `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` and 13 `HARNESS_CLAUDE_SDK_*` names | `reachable` / `reachable` | CRL-165 (closed by S111, see "Addendum: CRL-165 process reads on macOS"); the key CRL-167 (closed for Coral CLIs by S124, see "Addendum: CRL-167 secrets out of exec-time environments") |
| `host_environ` | `reachable` | `none` | `not_present` / `not_present` | CRL-165 (closed by S111, see "Addendum: CRL-165 process reads on macOS") |
| `own_cli_environ` (the step's own CLI) | `reachable` | as `cli_environ` | `reachable` / `reachable` | CRL-165 (closed by S111, see "Addendum: CRL-165 process reads on macOS"); the key CRL-167 (closed for Coral CLIs by S124, see "Addendum: CRL-167 secrets out of exec-time environments") |
| `credential_files.claude` | `denied` | | | |
| `credential_files.omnigent_secrets` | `denied` | | | |
| `credential_files.host_tunnel` | `denied` | | | |
| `config_api_key` | `denied` (the config file only) | | | |
| `bridge_dir` | `denied` | | | |
| `server_loopback` (`http://127.0.0.1:<port>`) | `reachable` | | | accepted (single-user; "Addendum: CRL-159 probe 15 on identity-requiring servers") |
| `server_localhost` (`http://localhost:<port>`) | `reachable` | | | accepted (single-user; "Addendum: CRL-159 probe 15 on identity-requiring servers") |
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
| `server_loopback` (`http://127.0.0.1:<port>`) | `reachable` | | | accepted (single-user; "Addendum: CRL-159 probe 15 on identity-requiring servers") |
| `server_localhost` (`http://localhost:<port>`) | `reachable` | | | accepted (single-user; "Addendum: CRL-159 probe 15 on identity-requiring servers") |
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
  stored credentials) are measured in "Addendum: CRL-159 probe 15 on
  identity-requiring servers". Every gate here is on a single-user server,
  which is never Enforced.
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
  only, and credentials the host was started with stayed readable in its
  runners' environments to processes outside the sandbox, until S123 took
  them out of a zygote-forked runner's ("Addendum: CRL-167 secrets out of
  exec-time environments"). Since S111 a macOS step's shell does not read
  them directly (measured on 27.2.1).
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
| Secrets in exec-time environments and argv, the model API key among them (every `.api_key` and `.argv_api_key` `reachable`, macOS, before S111; processes outside the sandbox read them until S123 and S124) | CRL-167 (closed for Coral steps on POSIX by S123, S124 and S125, see "Addendum: CRL-167 secrets out of exec-time environments"; what stays open is CRL-197) |
| The allow-listed runner token in the step runner's environment (below) | CRL-168 |
| A single-user server takes any local process as its owner (`server_loopback`, `server_localhost`, both platforms) | accepted: such servers are never Enforced ("Addendum: CRL-159 probe 15 on identity-requiring servers") |

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
it (`EXPECTED_TOKEN`). Since S123 the runner and harness rows read `none`:
measured on macOS 27.2.1, and set by reasoning on Linux until the `coral-e2e`
lane runs on that change (see "Addendum: CRL-167 secrets out of exec-time
environments").

| Observation | macOS (`EXPECTED_TOKEN["darwin"]`) | Linux (`EXPECTED_TOKEN["linux"]`) |
|---|---|---|
| The step runs and hands off (`step_runs`) | `true` | `true` |
| Token names in the runner's environment (`runner.names`) | `none` (before S123: `OMNIGENT_RUNNER_TUNNEL_TOKEN`) | `none`, by reasoning (before S123: `OMNIGENT_RUNNER_TUNNEL_TOKEN`, lane run 44980984569) |
| In the harness's environment (`harness.names`) | `none` (before S123: `OMNIGENT_RUNNER_TUNNEL_TOKEN`) | `none`, by reasoning (before S123: `OMNIGENT_RUNNER_TUNNEL_TOKEN`, lane run 44980984569) |
| In the sandbox launcher's environment (`launcher.names`) | `none` | `none` |
| In the CLI's environment (`cli.names`) | `none` | `none` |
| In the step's own shell (`shell_env_names`) | `not_present`, names `none` | `not_present`, names `none` |
| The step's shell reading its own runner's environment (`runner_environ`) | `denied` since S111 (before: `reachable`, names `OMNIGENT_RUNNER_TUNNEL_TOKEN`) | `hidden` |

So the step runs on such a server. Before S123 the token was in its runner's
and harness's readable environments on both platforms; now it is in none of
the five. The step's own shell read it from its runner on macOS only (before
S111; now `denied`); on Linux that read is `hidden`. The server still accepts
the token for every session (CRL-168).

Since S124 this test's host holds an API key with no gateway, and its
`ANTHROPIC_BASE_URL` names the mock. So each step's CLI runs on the direct-key
path, through its harness's credential proxy (see "Addendum: CRL-167 secrets
out of exec-time environments").

**Exec-time and live environments.** These are exec-time environments. Before
S123 the host started its runner zygote with its whole `os.environ`
(`omnigent/host/runner_zygote.py`, `_spawn_zygote_process`); it now starts it
from the allow-listed runner environment without credential-shaped names. A
forked runner, and a harness the zygote forks for it, keep the zygote's
exec-time environment, which is what another process reads. Their live
`os.environ` differs: a forked runner replaces it with the runner environment
the host built (`fork_runner`), which still holds the allow-listed token in
memory, and a harness's has the runner's authentication secrets removed
(`strip_runner_auth_secrets`, `omnigent/runner/identity.py`). The sandbox
launcher and the CLI are started with environments of their own, so what
another process reads there is what they started with.

**Caveats recorded with it.**

- A host `unknown` counts as dead, so a relaunch can start while the old runner
  lives on ([`../contracts/session-facade.md`](../contracts/session-facade.md),
  "The one relaunch path").
- On a server like this, runner-id rotation does not fence a runner that
  survived that way, because the server accepts the allow-listed token for every
  session (`omnigent/server/mcp_identity.py`).

**Residual (b), extended, then closed by S123.** Before S123, on the zygote
path a reader saw the host daemon's whole environment, for runners and
zygote-forked harnesses alike. On the direct-spawn fallback
(`OMNIGENT_RUNNER_ZYGOTE=0`, or the zygote unavailable or dead), it saw the
binding token and the initial bearer, as residual (b) says. The
allow-listed-token test
(`test_a_step_on_a_server_with_the_allow_listed_runner_token`) measured the
zygote path on both platforms. S123 gives the zygote the filtered runner
environment and hands a direct-spawned runner its auth tokens, this token
among them, over an inherited socket (see "Addendum: CRL-167 secrets out of
exec-time environments"). Still open: a direct-spawned runner's `env=`
carries the credential-shaped names of the runner allow-list and the
forwarded credentials (CRL-197).

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
  does not cover (accepted; "Addendum: CRL-159 probe 15 on
  identity-requiring servers").
- S111 leaves the secrets in exec-time environments and argv, where processes
  outside the sandbox read them, and other local accounts read command lines
  through setuid `ps`. Since CRL-167 a Coral CLI holds no model key in
  either, and a host-launched runner's exec-time environment holds neither
  its tokens nor, on the zygote path, any credential-shaped name (see
  "Addendum: CRL-167 secrets out of exec-time environments"). The host
  LaunchAgent's `EnvironmentVariables` stay (accepted, the user's own
  process), as do other agents' CLIs and the other paths that addendum lists
  (CRL-197).
- The server accepts the allow-listed runner token for every session
  (CRL-168). Since S123 it is no longer in a zygote-forked runner's or
  harness's readable environment; a direct-spawned runner's `env=` still
  carries it (CRL-197).
- A sandboxed process still reaches the clipboard and Spotlight. Apple Events
  and screen capture were not measured (CRL-171).
- Other macOS releases, and CI (CRL-170). An unknown operation or filter makes
  `sandbox-exec` refuse the profile, which fails closed. A renamed service or
  sysctl name would make a rule a silent no-op instead, and the behaviour test
  and probe 15 detect that only on a Mac that runs them.
- A sandboxed process still lists pids and reads `kinfo_proc` (the 16-character
  name, ppid, uid and start time) of every process.
- The login keychain file stays unreadable because no rule grants `~/Library`
  and the profile's `~/Library` deny (S5 in
  `omnigent/inner/seatbelt_sandbox.py`) refuses it, not because of S111 (see
  "Addendum: CRL-176 Claude config isolation").

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
- Loopback TCP listeners. A step with the network on can still connect to
  them, so each one must refuse a caller without its secret. The codex-native
  app-server WebSocket was the only Omnigent one that did not. Since S114 it
  takes a per-spawn token: Omnigent writes it to a 0600 file under
  `<data dir>/codex-native/ws-tokens/`, codex refuses a WebSocket without it
  (HTTP 401), and Omnigent's clients and the codex terminal send it.
  claude-native's relays, the runner's direct-attach listener and opencode's
  server already required their own secrets. The behaviour test, on macOS
  26.3.1 with codex-cli 0.171.0 and opencode 2.1.4, connects to all four from
  a sandboxed step and each refuses it; the step cannot read the codex token
  file or the relay's `bridge.json`. Still open: a codex without `--ws-auth`
  runs with no token and logs a warning; a sandbox read grant over the data
  dir, or a data dir inside a workspace, exposes the token file (no Coral
  configuration does either; under Coral the dir is `~/.coral`); codex's own
  tool sandbox can read the whole disk in workspace-write mode and has none in
  full-access mode, so a codex-native session's commands can read every
  session's token file and drive its siblings; the codex terminal's
  environment holds the token, as opencode's holds its password, which S111 guards on macOS and the
  pid namespace on Linux (moving it off the environment is CRL-173); a
  same-user process outside the sandbox can read the file (CRL-173);
  the old codex-native socket under `~/.omnigent/codex-native/`, which no
  current code starts, has no gate; new loopback listeners, other programs'
  loopback services (CRL-174) and UDP are not covered. Linux was not
  measured.
- Other Omnigent terminals' clipboard sockets stay reachable (CRL-171).
- Since S113 a Coral step's sandboxed Claude CLI, and since S115 every other
  claude-sdk CLI in a bwrap or seatbelt sandbox, no longer gets the user's
  `~/.claude` or `~/.claude.json`. CLIs that run outside a sandbox still do.
  See "Addendum: CRL-176 Claude config isolation" and "Addendum: CRL-178
  Claude config isolation for every sandboxed agent".
- On a single-user server a step acts as the owner on both platforms, so it
  can still send a message into another session, the reviewer's included,
  through the server (accepted; "Addendum: CRL-159 probe 15 on
  identity-requiring servers"). S112 does not restore review-gate integrity
  there.
- S112 does not change secrets in exec-time environments (since closed for
  Coral steps on POSIX, see "Addendum: CRL-167 secrets out of exec-time
  environments"; the rest is CRL-197) or the allow-listed runner token
  (CRL-168).

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
process from acting as the owner on a single-user server (accepted;
"Addendum: CRL-159 probe 15 on identity-requiring servers").

**Open for the owner.** Whether to run Coral steps on untrusted content on
macOS while CRL-171 is open, and on either platform while CRL-174 and CRL-181
are open, is the owner's risk decision (on a single-user server a step acts
as the owner on both platforms, an accepted residual). S111 and S112 closed
the process reads and the connect to harness sockets under the configured and
per-user default roots. S113 closed a sandboxed step CLI's access to the
user's Claude config files (since S125 only model names, switched-on opt-outs
and credential-free network settings of its settings `env` block reach the
CLI, see "Addendum: CRL-167 secrets out of exec-time environments"). All
three were measured on macOS 27.2.1, and no CI lane runs macOS
(CRL-170); S113 is also checked on Linux by a bwrap test in CI. What S113 leaves open is in
"Addendum: CRL-176 Claude config isolation". S114 gates the codex-native
app-server WebSocket, measured on macOS 26.3.1 only. It is not decided here.

## Addendum: CRL-176 Claude config isolation (2026-11-22)

For Coral steps, CRL-176 closes a way out of the sandbox through the user's
own Claude Code config. Before S113 every claude-sdk CLI wrap granted read and
write on `~/.claude/{plugins,sessions,session-env,backups}` in the user's real
home, and on `~/.claude.json` and `~/.claude/.credentials.json` (each only if
it exists). Other Omnigent agents' bwrap and seatbelt wraps did until S115
("Addendum: CRL-178 Claude config isolation for every sandboxed agent"). Seam
S113 (`.coral/seams.yaml`) changes `omnigent/inner/sandbox.py`,
`omnigent/inner/claude_sdk_executor.py`,
`omnigent/inner/claude_sdk_harness.py` and `omnigent/runtime/workflow.py`.
Every local measurement here was taken on macOS 27.2.1, with claude 2.1.325,
throwaway homes and a mock model. Linux is covered only by the bwrap
generator's output, read on a Mac, and by tests that run in CI on Linux. No CI
lane runs macOS (CRL-170). The socket and process-read rules are in the
CRL-165 and CRL-166 addenda.

**Root cause.**

- `prepare_claude_cli_path` (a step's `os_env` wrap) and
  `prepare_tight_cli_process_path` (the Linux wrap of an executor built
  without an `os_env`, which the claude-sdk harness never builds), in
  `omnigent/inner/claude_sdk_executor.py`, add
  `_claude_internal_write_roots()` and `_claude_internal_write_files()` to the
  CLI wrap policy; before S113 they did so for every wrap. Seatbelt renders
  them as read-write `subpath` and `literal` allows, and bwrap as read-write
  `--bind-try` mounts.
- The wrap met the CLI's need for a writable config home by sharing the
  user's own, the one their unsandboxed Claude Code trusts and runs code from.
  `CLAUDE_CONFIG_DIR` was never set for a claude-sdk launch; S109 gave the CLI
  its own temp dir only.
- The grant list predates Coral and gives no reason per directory. It ignores
  a user-set `CLAUDE_CONFIG_DIR`. The CLI tolerates a config home it cannot
  read or write, so leaving other directories out broke nothing visible.

Measured before S113, through the generated profile and through a real CLI
turn: code inside the CLI's wrap overwrote an installed plugin's hook, added a
plugin and planted a `session-env/<session>/` script. It listed, read and
wrote `sessions/` keys, wrote `backups/`, read and rewrote `.claude.json`, and
read `.credentials.json`. The host saw the changes. Read from the CLI binary,
not measured: the user's Claude Code runs plugin hooks and the user-scope MCP
servers in `.claude.json`, prepends `session-env` scripts to its Bash tool's
commands, and keeps each live session's inbox key in `sessions/` (CRL-174).

For a Coral step no direct way in was found. The model has no native shell,
and with `skills: none` the CLI starts no user MCP server (measured) and loads
no user settings or their hooks. The code in the wrap is the CLI itself and
its API key helper, so the hole was one step away: a CLI bug, a future native
tool, or a bundle that adds an MCP server or hooks. The CLI, as trusted code,
also wrote the step's own state into the user's directories (its plugin
store, measured). Other Omnigent agents that run claude-sdk in a sandbox with
`skills: all` did have a way in, which S115 closed for CLIs in a bwrap or
seatbelt sandbox ("Addendum: CRL-178 Claude config isolation for every
sandboxed agent").

**S113 as built.**

- **Coral only.** `omnigent/runtime/workflow.py` sets
  `HARNESS_CLAUDE_SDK_ISOLATE_CLAUDE_CONFIG=1` in its `params.coral` block, and
  `omnigent/inner/claude_sdk_harness.py` passes it to the executor as
  `isolate_claude_config`. A spec cannot set harness env, and the flag only
  narrows the grants. Without it the policy and the CLI's environment are as
  before.
- **No grant into the user's config.** With the flag, both wrap paths grant
  nothing under `~/.claude` and nothing on `~/.claude.json` or
  `.credentials.json`. Of the old list only `~/.npm/_logs` stays, read-write.
  `_claude_internal_write_roots(include_config=False)` creates nothing under
  `~/.claude`.
- **A private config dir for each launch.** The policy names
  `CLAUDE_CONFIG_DIR` in `scratch_dir_env`. In the launcher's in-wrap pass,
  after `activate_sandbox` and before the CLI starts, `export_scratch_dir`
  (`omnigent/inner/sandbox.py`) creates `claude_config_dir`, mode 0700, in the
  launch's private scratch. That scratch is a fresh 0700 `mkdtemp`, already
  granted, and is the CLI's `$TMPDIR`. The dir holds nothing of the user's:
  nothing is copied in or mounted. It is removed with the scratch when the CLI
  exits.
- **Both config variables.** The launcher sets `CLAUDE_CONFIG_DIR` and
  `CLAUDE_SECURESTORAGE_CONFIG_DIR` to the dir's absolute path, over any
  inherited value. The executor also removes both names from the CLI's
  inherited environment and from the user settings `env` block it merges. So
  a value the host forwards cannot redirect the CLI, and the CLI's credential
  store and keychain service name follow the private dir. Both names are set,
  not only removed, so a second connect at the same moment cannot hand the CLI
  the host's values.
- **`projects` cannot be created.** The policy lists `projects` in
  `scratch_dir_files`, so it is an empty 0600 file in the private dir. An
  oversized tool result is then reported unsaved, with the CLI's advice to use
  pagination, as before, rather than as a saved file the model has no tool to
  open.
- **The launcher wire.** The fields travel the launcher's policy JSON and
  survive every clone. A payload without them asks for no dir. A malformed
  one, or one that names a variable other than the two config dir names, fails
  the launch. With the field set and no scratch the launcher raises, and a
  failed `mkdir` (a planted name, a full disk) fails the launch too. Nothing
  falls back to the user's config.
- **Fail closed.** Take a `caller_process` `os_env` that configures a sandbox
  (type not `none`, network on, no operator opt-out). When its CLI is not
  wrapped, the executor refuses the step's turns with
  `coral_sandbox_unavailable` before any CLI starts. That covers no system
  `claude` (the SDK's bundled CLI cannot be wrapped), `resolve_sandbox`
  failing, the sandbox resolving inactive, and the trial wrap failing. So
  Coral steps need a system `claude`, found on `PATH`, in a common install
  dir, or named by `OMNIGENT_CLAUDE_PATH`. The implementer and reviewer
  stances use `os_env` with network on, and no Coral stance turns the network
  off. So a step is newly refused only when its host has no system `claude`
  or its wrap was already failing. From code, Coral's run preflight does not
  check for the CLI: the run starts, and its first step fails.
- **Unwrapped CLIs.** A Coral CLI that runs unwrapped gets a private 0700 dir
  that the executor makes with `mkdtemp` (`omnigent-claude-config-*`, with
  `projects` as a file), passes in both variables, and removes on `close()`.
  By design that happens under the operator's
  `OMNIGENT_CLAUDE_SDK_NO_SANDBOX`, with a network-denying sandbox, and for a
  spec without `os_env`: the orchestrator and anchor, on every platform. For
  such a spec `omnigent/runtime/workflow.py` sends no
  `HARNESS_CLAUDE_SDK_OS_ENV`, so `omnigent/inner/claude_sdk_harness.py`
  builds the executor with a `caller_process` `os_env` whose sandbox is
  `none`, and the CLI runs unwrapped (from code). The Linux tight wrap applies
  only to an executor built with no `os_env` at all, which the harness never
  does. An unwrapped CLI's config is kept off the user's, but the CLI is not
  contained (CRL-180).
- **Unchanged.** Resume does not use the config dir: claude-sdk replays the
  history into a fresh client and runs with `--no-session-persistence`. A
  fresh dir adds no measurable start-up time.

**What was measured.** On macOS 27.2.1, against throwaway homes; Linux only
where stated.

- **The grants.** For the same Coral-shaped inputs, the isolated seatbelt
  profile and bwrap argv differ from the code before S113 by removals only.
  Seatbelt loses the four `~/.claude` subpaths, the two file literals, the
  metadata read of `~/.claude` and a duplicate read allow on `~/.npm/_logs`;
  bwrap loses the six `--bind-try` mounts. The only lines left that name the
  home are `~/.npm/_logs`, metadata reads of `<HOME>` and `<HOME>/.npm`, and
  the `~/Library` deny. Without the flag the profile and argv are byte for
  byte as before. The bwrap argv is generator output, read on a Mac.
- **The behaviour test.**
  `tests/inner/sandbox/test_sandbox_behavior.py::test_claude_cli_wrap_keeps_the_claude_config_out_of_the_home`
  seeds a throwaway home with a plugin hook, a session key, `session-env/`,
  `backups/`, `.claude.json`, `.credentials.json` and a stand-in file at
  `~/Library/Keychains/login.keychain-db`. It runs one probe outside the
  sandbox and one through the CLI wrap that
  `prepare_claude_cli_path(..., isolate_config=True)` builds. Both config
  variables are set to paths in the home, as values the host forwards would
  be. Outside, every home check succeeds, and inside, each one fails. The
  checks overwrite the hook, add a plugin, list `sessions/`, read or write a
  key, and write `session-env/` and `backups/`. They also read and write
  `.claude.json`, read `.credentials.json` and the keychain stand-in,
  hard-link the key and the stand-in, write the hook through a symlink, and
  rename `plugins`. Inside, `$CLAUDE_CONFIG_DIR` is a writable 0700 dir in
  the probe's `$TMPDIR` scratch, `projects` cannot be created there, and
  `$CLAUDE_SECURESTORAGE_CONFIG_DIR` names the same dir. Afterwards the home
  is unchanged and the dir is gone. With S113's isolated branch reverted,
  every home check except the two keychain ones succeeded inside.
- **More bypasses, in the security reviews.** Each of these was denied: a
  `clonefile` of the key, a `renamex_np(RENAME_SWAP)` onto the hook, and
  renaming `.claude.json` out. So were an open of the key through
  `/.vol/<dev>/<ino>`, and a read or write through a symlink to `~/.claude`
  swapped in for the private dir. In the design review's emulation of S113's
  grants, a writable working directory at `$HOME` did not reopen `~/.claude`
  or `~/.claude.json`, because the dotfile mask denies them.
- **A real CLI turn.**
  `tests/e2e/coral/test_tier_b_executor.py::test_a_coral_cli_keeps_its_claude_config_out_of_the_home`
  runs the real CLI in its seatbelt wrap with the Coral flags, API-key auth and
  the mock model. It is a local test, not in a CI lane. The probe runs as the
  API key helper (since S124, in front of the credential proxy's token
  helper), which the CLI starts inside its wrap: every home check
  fails, and the private dir checks pass. The turn completes and the home is
  unchanged. A `security` stub first on `PATH` was asked only for per-dir
  service names (`Claude Code-<8 hex>` and `Claude Code-credentials-<8 hex>`),
  and nothing went out through the proxy. A 162,012-character tool result
  came back as not saved, with the pagination advice and without a saved
  path.
- **Unit tests.** `tests/inner/test_claude_sdk_executor.py` pins the isolated
  grants on both backends and on the Linux tight wrap
  (`test_an_isolated_cli_wrap_grants_nothing_of_the_claude_config_home` and
  `test_an_isolated_tight_cli_wrap_grants_nothing_of_the_claude_config_home`).
  It also pins the refusal rule against every wrap outcome
  (`test_only_a_wrap_fault_leaves_a_requested_wrap_unapplied`), the refusals
  (`test_an_isolated_cli_its_sandbox_cannot_wrap_never_starts`), the CLI's
  environment wrapped and unwrapped
  (`test_an_isolated_cli_gets_only_its_own_claude_config_dir`) and the
  two-connect race
  (`test_a_concurrent_connect_cannot_hand_a_cli_the_hosts_config_names`).
  `tests/inner/test_sandbox.py` pins the wire fields, 15 malformed payloads
  and the in-wrap dir
  (`test_run_launcher_gives_the_target_a_private_dir_in_its_scratch`).
- **Checked in CI, not run locally.** These run on Linux only:
  - The behaviour test's bwrap case asserts the same verdicts under bwrap,
    where only `~/.npm/_logs` of the home is mounted.
  - `tests/e2e/coral/test_skeleton.py::test_the_review_loop_runs_end_to_end_on_a_real_stack`
    plants a plugin hook and a session key in the stack host's home. It
    asserts that the live implement step's CLI has a `CLAUDE_CONFIG_DIR`
    named `claude_config_dir`, inside its `$TMPDIR` and outside the home,
    holding `.claude.json`. It also asserts that both canaries are unchanged
    after the run. It runs in CI's Coral E2E lane with claude 2.1.295.

**Keychain.** On macOS 27.2.1 the login keychain file cannot be opened from
the CLI's sandbox. No rule grants `~/Library`, and S5 in
`omnigent/inner/seatbelt_sandbox.py` denies it as a second layer; the CLI
wrap's own profile has that deny. A stand-in file at the keychain's path did
not open directly, through a hard link or through `/.vol`, and a Data-volume
file did not open through the `/System/Volumes/Data` firmlink. The
`mach-lookup` to securityd stays open. From how the Security framework works,
not measured, that lookup alone reads no file-keychain item, because the
caller must open the keychain file itself; CRL-165 measured
errSecNoSuchKeychain from the same profile generator. No keychain item was
read and no keychain was created. The per-dir service name is not the
control: a process in the sandbox can ask `security` for any name, and the
file denial is what stops it.

**Collateral.**

- A Coral step's CLI no longer reads the user's `~/.claude.json`. Coral steps
  started no user MCP server before (measured) and loaded no user settings, so
  they lose nothing they used.
- Each launch's CLI writes its own `userID` and `machineID` into a fresh
  `.claude.json` (measured), so the CLI's feature-flag bucketing and telemetry
  identity differ per launch.
- A host without a system `claude` now refuses Coral steps, where the SDK's
  bundled CLI used to run unwrapped.

**Residuals.** S113 keeps a Coral step's sandboxed CLI, and what it starts,
away from the user's Claude config files.

- Other Omnigent agents that run claude-sdk in a sandbox kept the shared
  grants until S115. With `skills: all`, a user-scope MCP server from
  `~/.claude.json` started inside such a wrap and rewrote a plugin hook,
  which was measured. What S115 leaves open is in "Addendum: CRL-178 Claude
  config isolation for every sandboxed agent".
- Coral CLIs outside the sandbox: the orchestrator and anchor on every
  platform, whose specs have no `os_env` (from code), any CLI under the
  operator's opt-out, and a step whose sandbox denies the network (no Coral
  stance does). Their config is a private dir, but they run as the user with
  no sandbox, so they and what they start can reach `~/.claude` (CRL-180).
- When the executor kills a CLI, its scratch and private config dir stay in
  the temp dir (measured before S113 for the scratch). Such a scratch holds
  about 16 KB of the CLI's config with no credential keys (measured). Read
  from the binary, it also holds the dead CLI's inbox key when the
  server-side inbox gate is on. The SDK's version check stops the launcher
  the same way, so each connect also leaves one scratch. That one holds only
  a private dir with the empty `projects` file (seen with the real CLI in
  S113's tests). A killed harness leaves the executor's own dir (CRL-179).
  Since S116 (CRL-179) each of these dirs names its owner. At its next
  connect, client teardown or close, a claude-sdk executor removes those whose
  owner has exited; after a killed harness, the next claude-sdk executor of
  the same user with the same temp dir does. Still open, among the residuals
  in "Addendum: CRL-179 launch temp dir cleanup": dirs made before S116; a
  scratch its sandboxed CLI changed so the sweep keeps it (a claim removed or
  rewritten, its mode changed, an entry the sweep cannot remove, or a tree of
  64 or more nested dirs); a dir too large for one sweep, until later sweeps;
  a scratch removed under a seatbelt CLI orphaned before its launcher named
  it, which the CLI can recreate unclaimed; the launcher script; a scratch
  under a `TMPDIR` set through the user settings `env`; an unclaimed dir left
  when a seatbelt launcher is killed between removing its owner claim and
  removing its dir; other agents whose grants cover the temp dir; and
  Windows.
- S113 left the CLI the whole `env` block of the user's
  `~/.claude/settings.json`: the executor read it outside the sandbox and
  merged it into the CLI's environment, minus the two config dir names and
  S13's token names, so code in the wrap could read those values. Closed by
  S125 on POSIX: the CLI gets only model names, switched-on opt-outs and
  credential-free network settings, and the endpoint feeds its credential
  proxy (see "Addendum: CRL-167 secrets out of exec-time environments"). On
  Windows the whole block still merges (CRL-197).
- A relative `CLAUDE_CONFIG_DIR` forwarded by the host makes that merge read
  a `settings.json` under the step's worktree, which a step can create. Since
  S125 such a file can still choose model names and switch opt-outs on, but
  not the endpoint, a proxy or a CA file. S13's token strips can also be
  undone by a concurrent connect on one executor. Both are from code and
  predate S113 (CRL-182).
- A step can create Claude Code project settings in its worktree:
  `.claude/settings.json` hooks and `CLAUDE.md` (measured), or a `.mcp.json`
  that did not exist when its profile was built. The user's own Claude Code
  loads them when that worktree is opened and trusted, which was not
  measured. A step can also create a direnv `.envrc` (measured), which direnv
  runs in the user's shell once allowed (CRL-181). A working directory above
  `$HOME` would also expose `~/.claude`, because the dotfile mask scans only
  the top level. No Coral configuration does this (CRL-184).
- `~/.npm/_logs` stays readable and writable, and a step can plant a symlink
  there (measured); what npm does with it was not measured. It stays, as an
  accepted residual with no ticket, for npm-installed CLIs' error logs.
- On macOS a step can still send the user's own Claude Code sessions a message
  through their inbox sockets, which take messages without a token on macOS
  (read from the binary, not measured). It can also confirm guessed names
  under `~/.claude/sessions` with `stat`, but cannot list or read them
  (CRL-174). A step's own CLI no longer publishes its inbox key in the shared
  `~/.claude/sessions`.
- Other channels to unsandboxed code are unchanged by S113: other programs'
  sockets and loopback services (CRL-174), and the owner on a single-user
  server (accepted; "Addendum: CRL-159 probe 15 on identity-requiring
  servers"). Since S114 Omnigent's loopback listeners each refuse a
  caller without its secret, except a codex-native app-server started by a
  Codex without `--ws-auth` (noted on CRL-177). The rest of what S114 leaves
  open is in "Addendum: CRL-166 harness sockets on macOS". S113 does not
  change secrets in environments (since closed for Coral steps on POSIX, see
  "Addendum: CRL-167 secrets out of exec-time environments"; CRL-197, CRL-168).
- Other macOS releases, and CI (CRL-170). The keychain result rests on the
  file denial. The behaviour test checks only that a stand-in file at the
  keychain's path cannot be opened, and only on a Mac that runs it. A release
  that let securityd open the login keychain on the caller's behalf would
  make keychain items readable from the sandbox without that test noticing.
- Linux was not run locally. `projects` as a file was measured with claude
  2.1.325, and CI runs 2.1.295.

**Open for the owner.** Whether to run Coral steps on untrusted content is
the owner's risk decision, stated with its open tickets in "Addendum: CRL-166
harness sockets on macOS". It is not decided here.

## Addendum: CRL-178 Claude config isolation for every sandboxed agent (2026-11-22)

CRL-176 closed a way out of the sandbox through the user's own Claude Code
config for Coral steps. CRL-178 closes it for every other Omnigent agent whose
claude-sdk CLI runs in a bwrap or seatbelt sandbox. Before S115 such a wrap
granted read and write on `~/.claude/{plugins,sessions,session-env,backups}`
in the user's real home, and on `~/.claude.json` and
`~/.claude/.credentials.json` (each only if it exists). Seam S115
(`.coral/seams.yaml`) changes `omnigent/inner/sandbox.py` and
`omnigent/inner/claude_sdk_executor.py`, and adds an auth note to the
`examples/sentinel` configs. Every local measurement here was taken on macOS
27.2.1, with claude 2.1.325, throwaway homes and a mock model. Linux is
covered only by the bwrap generator's output, read on a Mac, and by a test
that runs in CI on Linux. No CI lane runs macOS (CRL-170). S115 builds on
S113, described in "Addendum: CRL-176 Claude config isolation". Where that
addendum says a CLI without the Coral flag keeps the shared grants, this one
replaces it.

**Root cause.**

- `prepare_claude_cli_path` (the `os_env` wrap) and
  `prepare_tight_cli_process_path` (the Linux wrap of an executor built
  without `os_env`; the claude-sdk harness always passes one, so only a direct
  caller of `ClaudeSDKExecutor` reaches it) isolated a CLI only when asked.
  `isolate_config` defaulted to `False`, and only Coral passed `True`. Every
  other wrap got `_claude_internal_write_roots()` and
  `_claude_internal_write_files()`, read and write.
- The wrap met the CLI's need for a writable config home by sharing the
  user's own. S113 gave Coral CLIs a private, empty one. Other CLIs had none,
  because the user MCP servers they load live in the shared `~/.claude.json`.
  An empty dir would have dropped those servers. It would also have dropped
  the subscription login, whose credential store and keychain name follow
  the config dir.

Measured before S115, with a non-Coral `skills: all` turn through the real
executor: a user MCP server from `~/.claude.json`, started inside the wrap,
rewrote an installed plugin's hook, added a plugin and planted a
`session-env/<session>/` script. It read and wrote `sessions/` keys, wrote
`backups/`, rewrote `.claude.json` and read `.credentials.json`. The host saw
every change, and the CLI itself wrote its plugin store into the real
`plugins/`. 13 of the probe's 15 home checks succeeded inside; the two
keychain checks did not.

What reached such a CLI from the user's config was measured too.
Unsandboxed, the same throwaway home loads `CLAUDE.md`, user skills and
commands, a plugin with its skill, hook and MCP server, and a settings hook.
Under the old wrap only the user-scope MCP servers in `~/.claude.json`
loaded. The wrap never granted `settings.json`, so the CLI saw no
`enabledPlugins` and ran no plugin or hook. It never granted `CLAUDE.md`,
`skills/`, `agents/` or `commands/` either. On Linux the subscription login
is the plaintext `.credentials.json`, which the wrap granted as well.

**S115 as built.**

- **Which wraps.** Both wrap paths isolate by default. On
  `prepare_claude_cli_path` the default (`isolate_config=None`) isolates on
  every backend except Windows' job object (`windows_jobobject`). That backend
  confines processes, not files, so its CLI keeps the shared grants, as
  before. Bwrap, seatbelt and any backend added later are isolated. The tight
  wrap, which only an executor built without an `os_env` uses (the claude-sdk
  harness never builds one), is always bwrap and always isolates. The executor
  passes `True` for Coral, the default for other specs on the `os_env` path,
  and `True` on the tight path. `isolate_config=False` keeps the shared
  grants; no production caller passes it.
- **No grant into the user's config.** An isolated wrap grants nothing under
  `~/.claude` and nothing on `~/.claude.json` or `.credentials.json`. Of the
  old list only `~/.npm/_logs` stays. Each launch gets S113's private 0700
  `claude_config_dir` in its scratch, named by `CLAUDE_CONFIG_DIR` and
  `CLAUDE_SECURESTORAGE_CONFIG_DIR`, with `projects` as an empty file.
- **Who gets a seed.** A non-Coral spec whose `skills` load user settings:
  `all`, a list, or a malformed filter, which the executor treats as `all`.
  Its private dir starts with a filtered copy of the user's global config as
  `.claude.json`. `skills: none` and Coral get an empty dir, because such a
  CLI starts no user MCP server (measured in CRL-176).
- **What the seed holds.** `_claude_config_seed` filters the global config
  file the CLI would read, found by `claude_global_config_path` in the
  claude-native bridge: `$CLAUDE_CONFIG_DIR/.claude.json` when that is set,
  else `~/.claude.json`, or the legacy `.config.json`. It keeps the user's
  `mcpServers`, `userID`, and the legacy top-level `env` (string values only,
  without the two config dir names). For each `projects` entry it keeps only
  `hasTrustDialogAccepted`, `hasClaudeMdExternalIncludesApproved`,
  `disabledMcpServers`, `enabledMcpServers`, `disabledMcpjsonServers`,
  `enabledMcpjsonServers` and `enableAllProjectMcpServers`. A key at the
  CLI's default (`false` or `[]`, read from the 2.1.325 binary) is left out,
  and so is an entry left empty. So a server the user turned off for a
  project stays off, and projects with nothing set are not listed.
- **What it never holds.** Project-level `mcpServers` (local scope), which
  the CLI does not load with the setting sources Omnigent passes (measured in
  the design review). `oauthAccount`, `primaryApiKey`,
  `customApiKeyResponses`, tool permissions, history, caches and every other
  key. No Claude sign-in credential: the seed code never opens
  `.credentials.json` or asks the keychain. Secrets inside the copied MCP
  server entries and legacy `env` are copied (see Residuals).
- **Where it comes from.** A relative or empty `CLAUDE_CONFIG_DIR`, or a
  relative `HOME`, is refused as the source, because the CLI would resolve it
  against a working dir the sandbox may write. The seed is then empty, and a
  warning says why. A missing file gives an empty seed. An unreadable,
  non-UTF-8, malformed or non-object file gives an empty seed and a warning
  naming the file. So do a FIFO, a file over 16 MB, and one nested too deeply
  to parse. The real file is never granted.
- **Lifecycle.** Construction only picks a name,
  `<temp dir>/omnigent-claude-seed-<16 hex>/claude.json`, and reads or makes
  nothing. The name is not a dotfile, which the dotfile mask would hide. Just
  before each new CLI connect, `_write_claude_config_seed` reads the user's
  config again and writes the seed through `mkstemp` and `os.replace`, mode
  0600. The first launch makes the 0700 dir with an exclusive `mkdir`, so a
  dir someone else made under that name fails the launch. If a temp cleaner
  removes it, the next launch makes it again the same way. A dir found there
  later must still be this user's own 0700 directory, not a link, or the
  launch fails. A server the user adds mid-session reaches the next launch,
  not the live one. `close()` and `__del__` remove the dir. A launch after
  that fails with "This agent's Claude CLI could not get its private Claude
  config: the executor is closed", and the dir is not made again. Any write
  error fails the connect with the same text and its reason. An unwrapped CLI
  gets no seed and reads the user's own config, as before.
- **The copy into the sandbox.** The policy's `scratch_dir_seed` names the
  pair `.claude.json` and the seed file. `with_scratch_dir_env` grants the
  seed file as a read root only. In the launcher's in-wrap pass, after
  `activate_sandbox`, `export_scratch_dir` (`omnigent/inner/sandbox.py`)
  copies it into the private dir before it creates `projects`. A version
  query, the target arguments `-v` or `--version` alone, gets the dir without
  the copy: it needs no config, and its caller may kill it before the launcher
  cleans up. The copy opens the seed through `open_regular_file`, without
  following a link and without blocking. It refuses a missing seed, a link, a
  FIFO, a directory or any other non-regular file, and a file that another
  user owns or that group or others can write. It writes a fresh 0600 file
  with `O_CREAT|O_EXCL|O_NOFOLLOW`. Each refusal fails the launch, and the
  scratch is removed. The field travels the launcher's policy JSON and
  survives every clone. A malformed one fails the launch, and an old payload
  asks for no seed.
- **Auth.** A stored subscription login is not carried into the sandbox: the
  CLI's credential store and keychain name follow the private dir, which
  holds none. No copy of any Claude sign-in credential is made. For such a
  CLI without an API key helper,
  `_claude_auth_remediation(..., private_config=True)` gives
  the auth error's next step:
  - With no token variable set, it says the stored login does not reach the
    CLI. It tells the user to run `<cli> setup` for an API key or gateway, or
    to set `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) in the
    host's environment, which the host passes to every runner it starts.
  - With `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_AUTH_TOKEN` set, it says the
    CLI signs in only with that token.
  - The gateway and Databricks texts are unchanged.

  At construction the executor also logs a warning for a wrapped, isolated,
  non-Coral CLI that has no API key helper, no gateway, and none of
  `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`,
  `CLAUDE_CODE_USE_BEDROCK`, `CLAUDE_CODE_USE_VERTEX` or
  `CLAUDE_CODE_USE_FOUNDRY`. It does not refuse, because the CLI may sign in
  another way.
- **Breaking on Linux.** A sandboxed non-Coral agent that relied on the
  stored subscription login now needs an API key, a gateway or
  `CLAUDE_CODE_OAUTH_TOKEN`. On macOS the login is a keychain item, and the
  keychain file cannot be opened from the sandbox (see the CRL-176 addendum).
  So it very likely did not work there before; that was not measured with a
  real login. Its HTTP MCP servers also lose the OAuth sign-ins in the CLI's
  credential store, so they may need sign-in and their tools may be missing
  (from the binary, not measured; see "MCP OAuth" under Collateral).
- **Unchanged.** Coral: its rendered profile and bwrap argv are byte for byte
  as with S113, and its policy gains only an empty `scratch_dir_seed`. Also
  Windows, CLIs that run unwrapped, and the seatbelt and bwrap renderers.

**What was measured.** On macOS 27.2.1, with claude 2.1.325, against
throwaway homes; Linux only where stated.

- **The grants**, in the security review, for the real executor with
  `skills: all`, against the code before S115. Seatbelt loses read and write
  on the four `~/.claude` subpaths, `~/.claude.json` and `.credentials.json`,
  and gains a read of the seed file. Under the home only `~/.npm/_logs`
  stays, as for Coral. Bwrap and the tight wrap lose every `--bind-try` mount
  under the home except `~/.npm/_logs`. They gain one `--ro-bind-try` of the
  seed, after `--tmpfs /tmp`, so a seed under `/tmp` stays visible. That
  bwrap argv is generator output, read on a Mac. Coral's profile and argv are
  identical to S113's, and the Windows job-object policy is unchanged.
- **The behaviour test.**
  `tests/inner/sandbox/test_sandbox_behavior.py::test_claude_cli_wrap_keeps_the_claude_config_out_of_the_home`
  gains a `seeded` row beside S113's `coral` row. It builds the wrap with
  `prepare_claude_cli_path(..., config_seed=seed)` and the default
  `isolate_config`, which is the non-Coral production call, before the seed
  exists. It then writes the seed with `_claude_config_seed` from a throwaway
  home's `.claude.json` that holds one MCP server and an `oauthAccount`.
  Inside the wrap, with both config variables forwarded to that home, each of
  the 15 home checks fails. `$CLAUDE_CONFIG_DIR/.claude.json` is a regular
  file that names the server, and the seed cannot be overwritten. The home
  and the seed dir are unchanged, the private dir is gone after the exit, and
  the seed holds no `oauthAccount`. With the default turned back to the
  shared grants, 13 of the 15 checks succeeded inside, all but the two
  keychain ones.
- **A real CLI turn.**
  `tests/e2e/coral/test_tier_b_executor.py::test_a_sandboxed_agent_loads_its_mcp_servers_without_the_home`
  is a local test, not in a CI lane. It runs a non-Coral executor with
  default skills, a seatbelt `os_env`, API-key auth and the mock model. The
  kit's throwaway `CLAUDE_CONFIG_DIR` is forwarded, as a host would forward
  one. The throwaway `.claude.json` declares two user MCP servers, turns one
  off for the workspace's project, and holds an `oauthAccount`.
  - The turn completes, and the enabled server answers the model's tool call.
  - That server runs the probe when it starts inside the wrap. All 15 home
    checks fail, its private dir holds the seeded copy, and the seed cannot
    be overwritten.
  - The server that was turned off never starts, and in the measured run the
    CLI's init message listed it as `disabled`.
  - The home is unchanged, and the seed dir is gone after `close()`.
  - A `security` stub first on `PATH` was asked only for per-dir names
    (`Claude Code-<8 hex>` and `Claude Code-credentials-<8 hex>`), and
    nothing went out through the proxy.

  With the non-Coral default turned back to the shared grants, the server
  reached the same 13 checks.
- **More checks, in the security review.** Through the real executor's
  launcher on seatbelt, code in the wrap could not overwrite, remove, rename,
  `chmod` or hard-link the seed, or write through a symlink to it. It could
  not list or write the seed's dir, read a planted file beside the seed, read
  another executor's seed, or list `$TMPDIR`. A FIFO or missing seed failed
  the launch in about 0.5 s, and the target never ran.
  `CLAUDE_CODE_OAUTH_TOKEN` reached the wrapped target as it did before S115;
  the new code reads only whether it is set.
- **Design experiments.** A seed of this kind made the sandboxed CLI load the
  same set as the old wrap, the user MCP servers. It added no measurable
  start-up time: 0.86 s against 0.89 s, the median of three. Copying plugins
  instead would cost 2.7 s and 190 MB per executor for eight synthetic
  plugins, and 10 s for a whole 875 MB `plugins/`. With a private dir and no
  credential, the CLI said "Not logged in · Please run /login" and sent no
  request. With `CLAUDE_CODE_OAUTH_TOKEN` in its environment, it sent that
  token.
- **Unit tests.** `tests/inner/test_claude_sdk_executor.py` pins:
  - the exact seed, with a credential file that no open may touch
    (`test_the_seed_keeps_only_mcp_identity_env_and_project_trust_keys`);
  - the config path and the refused sources
    (`test_the_seed_follows_the_clis_config_path_but_never_a_relative_one`),
    and unusable configs
    (`test_a_missing_or_unusable_user_config_gives_an_empty_seed`);
  - the default grants on both backends, a future backend and the tight wrap
    (`test_an_isolated_cli_wrap_grants_nothing_of_the_claude_config_home`,
    `test_an_isolated_tight_cli_wrap_grants_nothing_of_the_claude_config_home`),
    and the Windows row
    (`test_a_windows_job_object_cli_keeps_the_shared_claude_config_by_default`);
  - which CLIs read the user's config
    (`test_only_a_wrapped_non_coral_cli_that_loads_user_settings_reads_the_users_config`);
  - the lifecycle
    (`test_each_launch_gets_a_fresh_copy_and_a_closed_executor_launches_none`,
    `test_a_seed_dir_someone_else_made_fails_the_launch`);
  - the MCP sign-in warning
    (`test_a_seeded_mcp_server_the_host_signs_in_is_named_once`), and the
    auth texts and start warning
    (`test_a_sandboxed_cli_that_cannot_sign_in_names_the_fix`).

  `tests/inner/test_sandbox.py` pins the seed on the wire and 14 malformed
  seeds (`test_a_malformed_scratch_dir_seed_is_refused`), the in-wrap copy
  (`test_run_launcher_gives_the_target_a_private_dir_in_its_scratch`), the
  refused seeds (`test_run_launcher_refuses_a_seed_that_is_not_a_regular_file`)
  and a copy that never writes through an existing target
  (`test_a_seed_copy_never_writes_through_an_existing_target`).
- **Checked in CI, not run locally.** The behaviour test's `linux_bwrap`
  rows assert the same verdicts under bwrap. The seeded row does so against
  a seed that does not exist when the wrap is built, as in production. They
  run on Linux in CI's `inner-rest` lane, and a passing run there is what
  confirms the Linux claims in this addendum.

**Collateral.**

- Plugins, hooks, `CLAUDE.md`, skills, agents and commands from the user's
  config never loaded in a sandboxed CLI, and they still do not. `skills: all`
  still asks for the user and project setting sources, but in the sandbox the
  CLI's user config is the seed.
- **MCP OAuth.** The sign-ins of HTTP MCP servers live in the CLI's
  credential store, under `mcpOAuth` (read from the binary), and that store
  now follows the private dir. So on Linux such servers lose their stored
  tokens in a sandboxed agent: they may show as needing sign-in, and their
  tools may be missing. That was not measured. On macOS the store is the
  keychain, which very likely could not be read from the sandbox before
  either.
- **The needs-sign-in warning.** When the host's MCP sign-in manager reports
  a seeded server, the executor logs one warning per server per executor,
  naming it. Its sign-in stays in the host's store, so the server may not
  connect in the sandbox. Other MCP OAuth servers get no warning. The CLI
  lists MCP servers as `pending` when it starts (measured on 2.1.325), so
  which ones need a sign-in is not known cheaply.
- The start warning can be wrong when the provider is set only in the copied
  legacy `env` or, for `skills: none`, in the user settings `env` (from
  code).
- A `~/.claude.json` over 16 MB gives every sandboxed non-Coral agent an
  empty seed, so none of the user's MCP servers load there. The only sign is
  a warning in the runner log on the host, naming the file and the limit. It
  fails safe: nothing is granted or copied.
- `primaryApiKey`, a legacy console key in `.claude.json`, is not copied, so
  an agent that relied on it gets the auth error.
- `userID` is copied, so the CLI's feature-flag bucketing matches the user's.
  Its feature-flag caches are not copied, so each launch starts from the
  defaults.
- With `CLAUDE_CODE_CUSTOM_OAUTH_URL` set, the CLI reads
  `.claude-custom-oauth.json` instead (read from the binary). It then ignores
  the seed and starts no user MCP server. That is not handled.
- A sandboxed agent's CLI can no longer write its plugin store or inbox key
  into the shared `~/.claude`. The home was unchanged in both tests above.

**Residuals.** S115 keeps a claude-sdk CLI in a bwrap or seatbelt sandbox,
and what it starts, away from the user's Claude config files, except as
listed here.

- CLIs outside a sandbox keep the user's `~/.claude`, as before. By design
  that covers `sandbox: none` and specs without `os_env`, which the
  claude-sdk harness runs with `sandbox: none`; most of Omnigent's example
  agents are among them. It also covers the operator's
  `OMNIGENT_CLAUDE_SDK_NO_SANDBOX` and a sandbox that denies the network. A
  direct caller that builds the executor without an `os_env` on Linux gets
  its CLI unwrapped when the tight wrap cannot be applied, a fault the
  executor tolerates; the claude-sdk harness never builds one. A non-Coral
  agent whose configured sandbox cannot be applied runs its CLI unwrapped
  too, and at most a runner-log line says so. That happens with only the
  SDK's bundled CLI, and when the sandbox fails to resolve, resolves inactive
  or fails its trial wrap (CRL-183).
- A working dir, `read_paths` or `write_paths` entry that is an ancestor of
  the home, such as `/` or `/Users`, exposes `~/.claude` and `~/.claude.json`
  to the wrap, read-write under a write grant. The dotfile mask scans only
  the top level of each root unless `cwd_hidden_scan_recursive` is set (from
  code). The CRL-176 addendum notes this for Coral, where no configuration
  does it; for other agents the spec and the launch folder choose these
  paths (CRL-184).
- Windows' job object keeps the shared grants. It confines no files, so they
  add no access there. No ticket.
- Code in the sandbox can read the seed copy: the copied MCP servers' `env`,
  arguments and headers, the legacy `env`, and the paths of projects that
  have a trust or MCP key set. In the security review's run the copy held the
  user MCP server's entry. The servers need those values to run, and
  before S115 the whole `~/.claude.json` was readable (CRL-197).
- `CLAUDE_CODE_OAUTH_TOKEN`, which the auth error recommends, is a long-lived
  subscription credential. The host passes it to every runner it starts
  (`HARNESS_CREDENTIAL_ENV_VARS` in `omnigent/host/connect.py`), and S13
  strips it only for Coral. In the design security review, on macOS, a stdio
  MCP server in the wrap did not receive it, and `ps -E` of the CLI was
  denied. Hooks, the API key helper, other CLI versions and Linux
  `/proc/<pid>/environ` were not measured (CRL-197). A `skills: none` agent
  without a gateway also still gets the `env` block of the user's
  `~/.claude/settings.json` merged into its CLI's environment, as before;
  S125 changes that for Coral CLIs only (CRL-197).
- Leftover copies of the seed (CRL-179). With S115 a launch scratch can hold
  a copy of the user's MCP servers with their secrets, as a 0600 file in a
  0700 dir.
  - The SDK's version check runs the launcher with `-v`, reads one line and
    stops it, which skips the launcher's cleanup. So each new connect can
    still leave a launch scratch, but that launch copies no seed: its private
    dir holds only the empty `projects` file
    (`test_a_killed_version_check_leaves_no_copy_of_the_seed`, measured on
    macOS 27.2.1; its `linux_bwrap` row runs in CI).
  - A killed CLI still leaves its scratch with the seed copy, and a killed
    harness leaves the executor's seed dir.
  - In QA, an interrupt in the middle of a real CLI turn left two launch
    scratches, each holding `claude_config_dir/.claude.json`: the seed copy,
    and the CLI's rewrite of it. `close()` had removed the seed dir.
  - Since S116 (CRL-179) the scratch and the seed dir name their owner. At
    its next connect, client teardown or close, a claude-sdk executor removes
    those whose owner has exited, seed copies included; after a killed
    harness, the next claude-sdk executor of the same user with the same temp
    dir does. Still open, among the residuals in "Addendum: CRL-179 launch
    temp dir cleanup": copies made before S116; a scratch its sandboxed CLI
    changed so the sweep keeps it (a claim removed or rewritten, its mode
    changed, an entry the sweep cannot remove, or a tree of 64 or more nested
    dirs), with what is left in it, possibly the seed copy; a seed copy in a
    dir too large for one sweep, until later sweeps; a scratch removed under a
    seatbelt CLI orphaned before its launcher named it, which the CLI can
    recreate unclaimed with its config; the launcher script, which holds no
    seed; a scratch under a `TMPDIR` set through the user settings `env`; an
    unclaimed dir left when a seatbelt launcher is killed between removing its
    owner claim and removing its dir; other agents whose grants cover the
    temp dir (next item); and Windows.
- A spec whose `read_paths` cover the temp dir can read other executors'
  seeds (from code). A Claude CLI wrap with such a write grant is refused
  when its launcher is built, but another agent's sandboxed tool helper whose
  `write_paths` cover the temp dir can rewrite them: bwrap mounts write roots
  after read roots, and seatbelt allows writes anywhere under a write root
  (from code). The copy's owner and mode checks pass, because the files are
  the same user's, so a launch that copies a rewritten seed starts from it,
  still inside its own sandbox. Both are accepted residuals with no ticket of
  their own; they belong with CRL-179's temp dir hygiene. CRL-179 left both
  unchanged: S116 removes the dirs of launches and harnesses that are gone,
  but a seed and its live launches' copies still sit in the shared temp dir
  while their executor runs, and such an agent can also change their claims.
- A relative or empty forwarded `CLAUDE_CONFIG_DIR` is refused as the seed
  source, but the settings `env` merge still follows it into the working dir
  (CRL-182). An absolute one under a sandbox write root is not checked, so
  code in the sandbox could write a later launch's seed source (from code; an
  accepted residual with no ticket).
- A sandboxed agent can create Claude Code project settings, `.envrc`, or a
  `.git` where none existed in its working dir, which the user's own tools
  load later. The project settings and `.envrc` were measured in CRL-176; the
  `.git` follows from the rules. With the user's `enableAllProjectMcpServers`
  copied, a planted `.mcp.json` also starts inside later launches'
  sandboxes. Read from the 2.1.325 binary, the CLI also moves the copied
  `*Mcpjson*` keys into the working dir's `.claude/settings.local.json` at
  start when it can, as it could under the old wrap (CRL-181).
- Coral CLIs outside the sandbox are unchanged (CRL-180).
- On macOS code in the sandbox can still send the user's own Claude Code
  sessions a message through their inbox sockets (read from the binary, not
  measured). It can also `stat` guessed names under `~/.claude/sessions`
  (CRL-174). Other channels to unsandboxed code are unchanged: other
  programs' sockets and loopback services (CRL-174), Omnigent's loopback
  listeners, each gated by its secret since S114 except a codex-native
  app-server under a Codex without `--ws-auth` (noted on CRL-177; see
  "Addendum: CRL-166 harness sockets on macOS"), and the owner on a
  single-user server (accepted; "Addendum: CRL-159 probe 15 on
  identity-requiring servers").
- Other macOS releases, and CI (CRL-170). The keychain result rests on the
  file denial described in "Addendum: CRL-176 Claude config isolation".
- Linux was not run locally: the `linux_bwrap` rows run in CI only.

**Open for the owner.** Whether to run Coral steps on untrusted content is
the owner's risk decision, stated with its open tickets in "Addendum: CRL-166
harness sockets on macOS". It is not decided here.

## Addendum: CRL-179 launch temp dir cleanup (2026-11-22)

CRL-179 removes the temp dirs that a stopped or killed claude-sdk CLI launch,
or a killed harness, left in the shared temp dir. Since S113 a launch's
scratch holds the CLI's private config dir, and since S115 that dir can hold a
copy of the user's MCP servers with their secrets ("Addendum: CRL-176 Claude
config isolation", "Addendum: CRL-178 Claude config isolation for every
sandboxed agent"). Seam S116 (`.coral/seams.yaml`) changes
`omnigent/inner/sandbox.py`, `omnigent/inner/seatbelt_sandbox.py`,
`omnigent/inner/claude_sdk_executor.py`, `omnigent/inner/_proc.py` and
`omnigent/native/owner_claim.py`. Every local measurement here was taken on
macOS 27.2.1, with `claude-agent-sdk` 0.2.121, a `/bin/sh` stand-in CLI and
throwaway homes, unless a real CLI is named. On Linux the behaviour is
reasoned from the code; a bwrap test checks this in CI. No CI lane runs macOS
(CRL-170).

**Root cause.**

- The launcher (`run_launcher` in `omnigent/inner/sandbox.py`) makes each
  launch's scratch, `$TMPDIR/omnigent-osenv-*`, in its host pass, but only its
  in-wrap pass removes it, in a `finally` that a signal skips. Nothing else
  could tell a live scratch from a dead one.
- The Agent SDK checks the CLI's version at every connect: it runs the
  launcher with `-v`, reads one chunk and terminates it. So every connect left
  a scratch, 20 of 20 measured. That launch copies no seed (S115).
- The executor's teardown signals the CLI's process tree whenever it cannot
  `disconnect()`: a force close from another task, a cancel eviction, a failed
  connect. That scratch holds the seed copy and the CLI's state.
- Every seatbelt launch left its profile dir, `omnigent-seatbelt-profiles-*`,
  a clean one too (5 of 5), because the dir relied on `atexit`, which a
  launcher that `exec`s never runs.
- The executor's seed dir (`omnigent-claude-seed-*`) and a Coral unwrapped
  CLI's config dir (`omnigent-claude-config-*`) relied on `close()` and
  `__del__`, and a killed harness runs neither.

Measured before S116, through the real executor and SDK with a stand-in CLI
that answers the SDK's control requests:

- One session, then `close()`, left one scratch and two profile dirs; two
  sessions left two scratches and four profile dirs.
- A force close from another task, or a cancel eviction, left two scratches,
  one of them holding the seed copy, and one S109 launch dir.
- A SIGKILLed harness left its seed dir, and a killed Coral harness whose CLI
  ran unwrapped left its config dir.
- The measuring host's shared test temp dir already held 847 scratches and
  1,592 profile dirs from earlier runs.

**Why not signal handlers in the launcher.**

- On seatbelt the profile lets a process signal only itself, so the launcher
  cannot forward a signal to its CLI: `kill` failed with `EPERM` (measured). A
  handler that only exits makes `subprocess.run` try to kill the CLI, which
  fails the same way, and then wait for it; with SIGINT the launcher did not
  exit until the CLI's input closed (measured).
- On bwrap the SDK's signal reaches bwrap's monitor, never the launcher inside
  the namespace (from code).
- SIGKILL, an OOM kill and a killed harness run no handler.

So a sweep is needed in any design, and with the sweep a handler adds nothing.

**S116 as built.**

- **Owner claims.** Every dir the sweep covers names its owner in a
  `.launch-owner` file: a pid, its pid namespace and, on Linux, the boot id
  (`omnigent/native/owner_claim.py`).
  - The launcher's host pass claims its scratch right after making it, before
    S109's sweep and the exec into the wrap. The claim names the pid the SDK
    holds, which every later exec keeps, in the harness's pid namespace. On
    bwrap that pid becomes bwrap's monitor. The namespace can outlive it
    briefly: `--die-with-parent` kills the namespace only after the monitor
    has died.
  - The seatbelt backend claims its profile dir, and its `atexit` cleanup
    removes the claim with the dir.
  - The executor claims its seed dir at each `mkdir`, and the unwrapped
    config dir when it makes it.
  - On seatbelt the in-wrap pass also writes its CLI's pid as `.launch-target`
    in its claimed dirs, because there the CLI can outlive its launcher.
  - Every claim, S109's included, is created exclusively, mode 0600, without
    following a link (`create_owner_claim`). A failed write logs a warning
    naming no path and leaves that dir unclaimed and never swept; S109 keeps
    its own rule and gives that launch no launch dir.
- **The in-wrap cleanup keeps the claims.** For a claimed dir it removes
  everything else first. On seatbelt it then removes the claims and the dir.
  On bwrap the scratch is a bind-mount point it cannot remove, so it leaves
  the claims for the executor's sweep. It removes the claims only once nothing
  else is left, the target's claim first, and puts them back if the dir cannot
  go.
- **What the sweep looks at.** S109's `_remove_orphaned_launch_tmpdirs` takes
  a name pattern. The executor runs it over the temp dir
  (`tempfile.gettempdir()`) for `omnigent-osenv-`,
  `omnigent-seatbelt-profiles-`, `omnigent-claude-seed-` and
  `omnigent-claude-config-` names, each with the exact random part its maker
  uses. It also runs it over the harness socket root for S109's `c????????`
  launch dirs, but only if that root is this user's private real dir.
- **What it removes.** A direct child goes only when its name matches exactly,
  it is this user's real 0700 dir by `lstat`, and its owner, and its recorded
  target if any, are gone in this boot and pid namespace.
  - A pid is gone only when `os.kill(pid, 0)` fails with `ESRCH` or psutil
    sees a zombie. `EPERM`, or a process psutil cannot see, counts as alive.
  - A claim counts only as this user's regular file of at most 4 KiB, opened
    without following a link or blocking. Anything else leaves the dir
    unclaimed, and an unclaimed dir is kept. The check is in
    `read_owner_claim`, so the terminal reaper gets it too. The process
    manager also calls it, but when it refuses a file the process manager
    falls back to its older plain read of that file (see "Smaller limits").
  - Entries go bottom-up relative to the dir's descriptor, never through a
    link, and the claims last. A dir that cannot be emptied keeps its claims,
    and one that cannot be removed once emptied gets them back, so the next
    sweep retries.
- **Bounds.** Each root's sweep stops at a 2 s deadline, checked at every
  entry (listing one dir is not interrupted), or after 64 removals, and a
  dir's removal stops at a dir 64 levels down. Sweeps run off the event loop,
  one at a time per process. The sweep does nothing without
  `os.getuid` (Windows) and never raises. It logs counts and exception types,
  never paths.
- **When it runs.** After each successful connect, at the end of every client
  teardown (`_force_close_client`, which a failed connect also reaches), and
  at the end of `close()`.
  - A connect or teardown waits up to 2 s for its sweep, which then goes on
    in the background, and skips it while another sweep of the process runs.
  - `close()` first waits up to 10 s for pending cancel evictions, then up to
    10 s for its own sweep, including its turn.
- **Force close.** `_force_close_client` now snapshots the CLI's process tree
  before it signals. It waits up to 5 s in all for every member (a zombie
  counts as gone), SIGKILLs what is left, waits at most 1 s more, and only
  then sweeps.
- **Graceful close.** A close in the connecting task snapshots the tree
  before the SDK's `disconnect()`. The SDK's close gives the CLI 5 s after
  its input closes, then signals only the launcher, which on seatbelt can
  leave the CLI running. Afterwards every member still running gets 2 s, is
  SIGKILLed, gets at most 1 s more, and only then is the dir swept.
- **Unchanged.** `SandboxPolicy` and its wire format, the wrap argv and
  profile, `create_private_tmpdir`, the launcher script and the executor's
  public API.

**What was measured, and what is reasoned.** On macOS 27.2.1; Linux only
where stated.

- **The done-when test.**
  `tests/inner/sandbox/test_sandbox_behavior.py::test_a_closed_executor_leaves_no_launch_scratch`
  drives the real executor, Agent SDK and launcher with a POSIX `sh` stand-in
  CLI that answers the SDK's control requests.
  - It plants a scratch claimed by an exited process, holding
    `claude_config_dir/.claude.json`, and a seed dir claimed by the live test
    process.
  - Two sessions of a seeded agent connect. Each connect adds exactly one
    scratch, because its version check's scratch was swept, and both hold
    the seed copy. The planted dead scratch is gone.
  - One session is force-closed from another task, and its scratch is gone
    when that close returns. `close()` closes the other, and its scratch is
    gone too.
  - Afterwards no scratch and no S109 launch dir remain, the live seed dir is
    kept, and every profile dir left is the test process's own. No process of
    either CLI's tree is left, also in a second row whose stand-in ignores its
    input closing and SIGTERM; that row failed without the graceful-close
    wait.
  - On the code before S116 its seatbelt row failed with "the version check's
    launch stayed: 2 new".
- **The killed version check.**
  `test_a_killed_version_check_leaves_no_copy_of_the_seed` kills the version
  check by the SDK's terminate and by the executor's signal to the whole tree,
  with a stand-in that ignores SIGTERM. The scratch stays and names the pid
  the test spawned; that is checked while the stand-in still waits for its
  input, because on bwrap the namespace can run the cleanup in the moment it
  outlives its monitor. On seatbelt a sweep keeps the scratch while the
  stand-in still runs, and after the stand-in exits a sweep removes it.
- Both behaviour tests' `darwin_seatbelt` rows ran locally only; their
  `linux_bwrap` rows run in CI (below).
- **Unit tests.** In `tests/inner/test_sandbox.py`: the name pattern
  (`test_the_orphan_sweep_takes_a_name_pattern`), kernel liveness
  (`test_a_claimed_process_is_gone_only_when_the_kernel_says_so`), the
  in-wrap cleanup's seatbelt and bwrap rules and one cut short
  (`test_the_in_wrap_cleanup_never_drops_a_claim_while_its_dir_stays`), the
  retries (`test_a_dir_the_sweep_cannot_empty_keeps_its_claim_for_the_next_sweep`,
  `test_a_dir_that_cannot_go_once_emptied_gets_its_claims_back`), the bounds
  (`test_a_sweep_stops_at_its_budget_and_the_next_goes_on`,
  `test_a_sweep_stops_at_its_deadline_inside_a_dir`,
  `test_a_dead_tree_past_the_depth_cap_is_left_and_counted`), the claims'
  removal order (`test_a_kill_between_the_claim_removals_leaves_a_dir_still_swept`),
  Windows
  (`test_the_sweep_does_nothing_where_there_are_no_owner_uids`) and a planted
  link at each launcher claim (`test_each_launcher_claim_refuses_a_planted_link`).
  In `tests/native/test_owner_claim.py`: a FIFO, a link to `/dev/zero`, an
  oversized file and another user's file are no claim
  (`test_a_claim_that_is_not_this_users_small_regular_file_is_unknown`). In
  `tests/inner/test_claude_sdk_executor.py`: the three sweep points
  (`test_each_sweep_point_removes_only_dead_owners_temp_dirs`), the force
  close (`test_a_force_close_waits_for_the_whole_process_tree`), a cancelled
  caller's bound (`test_a_cancelled_caller_waits_for_a_stuck_sweep_only_its_bound`)
  and the
  executor's claims (`test_the_executors_claims_refuse_a_planted_link`). In
  `tests/inner/test_seatbelt_sandbox.py`: the profile dir's claim and its
  `atexit` removal
  (`test_a_profile_dir_names_its_owner_and_atexit_still_removes_it`).
- **A real CLI.** Both executor tests in
  `tests/e2e/coral/test_tier_b_executor.py` also assert that `close()` leaves
  no scratch. They ran locally with claude 2.1.325, a throwaway home and the
  mock model, and are in no CI lane.
- **Bounds.** A dead scratch with 100,000 files went in four sweeps (2.04,
  2.03, 2.00 and 0.23 s). One holding a 1,500-deep chain was kept as too deep
  in 0.006 s. A dry scan of a 3,799-entry temp dir took 21-23 ms.
- **Races, from probes on seatbelt.** In 200 of 200 `-v` launches, a SIGTERM
  sent as the SDK sends it landed before the in-wrap cleanup started. In 200
  of 200 launches under CPU load, `.launch-target` named the CLI before its
  first line of output.
- **Reasoned from code; a bwrap test checks this in CI.** On bwrap the claim,
  written in the host pass, names bwrap's monitor in the harness's pid
  namespace. `--die-with-parent` ends the namespace a moment after that pid
  dies: CI showed the in-wrap pass still running its cleanup after the monitor
  was reaped. A sweep in that moment can judge the launch gone; it then
  removes only what the dying launch's own cleanup removes. The in-wrap
  cleanup empties the scratch, a bind-mount point, and keeps its claims, so
  the teardown sweep removes it. The `linux_bwrap` rows of both behaviour
  tests run in CI's `inner-rest` lane.
  On Linux a `/proc` mounted `hidepid` cannot make a live owner look gone,
  because `os.kill` decides (from code).

**Collateral.**

- A client teardown that finds the CLI still running (a force close, a cancel
  eviction, a failed connect) now waits up to 5 s for every process of its
  tree, MCP servers that outlive the CLI included, then SIGKILLs the rest and
  waits at most 1 s more. Before, a tree still running after 5 s was left
  running.
- A graceful close whose CLI's tree outlives the SDK's own close waits up to
  2 s more for it, then SIGKILLs it and waits at most 1 s. The SDK bounds its
  close at about 20 s, so one session's graceful close takes at most about
  25 s with its 2 s sweep wait. A CLI that ignores both its input closing and
  SIGTERM closes in about 7 s on seatbelt: the SDK's 5 s grace plus the 2 s.
  The same 2 s reap applies to unwrapped CLIs, whose slow-exiting
  descendants, such as MCP servers, are now killed after it.
- A connect and each client teardown wait up to 2 s for their sweep.
  `close()` can take up to 10 s longer to wait for cancel evictions, and up to
  10 s for its last sweep.
- `.launch-owner` files now sit in each scratch root (the CLI's `$TMPDIR`),
  the seed dir, the unwrapped config dir and the profile dir, and on seatbelt
  `.launch-target` too. The CLI ignores them. Inside bwrap, the scratch's
  claim shows the launcher's host pid, the host pid namespace and the boot id;
  that is accepted as low value.
- The other users of the launcher, the ACP, pi, qwen, kimi and goose
  executors and the tmux terminal, now claim their scratch too, and a
  claude-sdk executor's sweep removes theirs once their launcher is gone (from
  code).

**What users see.** Copies of the user's MCP server secrets no longer pile up
in the temp dir. Once a launch has exited, its dirs go at its executor's next
connect, client teardown or close; a dir too large for one sweep goes over
several. After a killed runner they go when the next claude-sdk agent of the
same user on the host connects or closes with the same temp dir. Dirs left
before CRL-179 stay until deleted; the other exceptions are listed under
Residuals.

**Residuals.** S116 removes what a launch or a harness that is gone left in
the temp dir, except as listed here.

- **Dirs from before S116.** Temp dirs made before S116, or by a build without
  it, carry no owner claim, and the sweep never removes them. Remove them by
  hand only with every Omnigent server, runner and agent of yours on the host
  stopped: a running one's scratch, seed and config dirs have the same names,
  and a CLI whose dir is removed under it can recreate it, unclaimed. Remove
  only your own `omnigent-osenv-*`, `omnigent-claude-seed-*`,
  `omnigent-claude-config-*` and `omnigent-seatbelt-profiles-*` dirs in the
  temp dir. No ticket.
- **Killed harness.** After a harness is killed, these stay:
  - its seed dir (a copy of the user's MCP servers with their secrets);
  - the unwrapped CLI's config dir;
  - its seatbelt profile dirs;
  - on bwrap, its launches' scratches; on seatbelt, those of launches killed
    with it, seed copies included, as by a kill of its process group, the
    close of its terminal or launchd ending its job's process group. The SDK
    starts the launcher in the harness's process group (from code). A
    seatbelt launch that outlives the harness still removes its own scratch
    when its input closes (measured before S116).

  They stay until another claude-sdk executor of the same user connects or
  closes with the same temp dir, pid namespace and boot. If none does, they
  stay until deleted or until the OS cleans the temp dir.
- **Launch killed while its executor idles.** A launch killed from outside (an
  OOM kill, a user's `kill`) keeps its scratch, with the seed copy, until its
  executor next connects, tears down a client or closes, or another executor
  does.
- **A skipped sweep.** A connect or teardown that finds another sweep of its
  process running skips its own and does not make it up. A dir that sweep had
  already passed waits for the next sweep. `close()` waits up to 10 s for its
  turn, so it skips only behind a sweep stuck that long (see "Smaller
  limits").
- **A sweep's budget.** One sweep removes at most 64 dirs per root and stops
  after 2 s per root. A dead scratch with tens of thousands of files, such as
  a package tree a tool unpacked in `$TMPDIR`, needs several sweeps (100,000
  files took four), and its seed copy can be among the entries left. So can a
  backlog of more than 64 dead dirs. What is left waits for the next sweep.
  After a harness's last `close()`, that is another claude-sdk executor's with
  the same temp dir; if none runs, it stays until deleted.
  - On a host where several users share `/tmp` (Linux's default temp dir),
    another user's entries count against the temp dir's 2 s. With enough of
    them, the sweep can be delayed or kept from ever reaching this user's
    dirs, and each connect and teardown then waits its full 2 s. A per-user
    `TMPDIR` avoids this.
- **The sandboxed CLI can change its own scratch.** It can write both its
  scratch and that scratch's claims.
  - It can keep the scratch after it exits: by removing or rewriting a claim,
    by changing the dir's mode, or by leaving an entry the sweep cannot
    remove, such as a read-only subdir. Tools can leave one by accident: Go's
    module cache is read-only.
  - A tree of 64 or more nested dirs stops its dir's removal at that entry.
    The entries not yet removed, possibly the seed copy, stay, and each later
    sweep stops at the same entry. Only a process that can write in that
    scratch can make one, on purpose or by accident: code in that launch's
    sandbox, an agent whose grants cover the temp dir, or an unsandboxed
    process of the user.
  - It can have the scratch removed while it runs, by naming a dead pid.
  - With default grants, none of this touches another launch's dirs.
  - The sweep reads a claim only as a small regular file and never follows a
    link, so the CLI cannot make the sweep block, read another file, or
    remove another path.
- **An unclaimed dir on seatbelt.** A seatbelt launcher killed after removing
  its owner claim and before removing its dir leaves an empty, unclaimed dir
  that is never swept. The target's claim is removed first, so a kill between
  the two removals leaves a dir that still names its owner and is swept. The
  window is one syscall, and the dir holds no data.
- **Orphaned CLI on macOS.** A CLI whose launcher was killed from outside
  keeps running until its stdin closes (measured before S116). Its scratch
  stays while it runs, because `.launch-target` names it, and goes at the
  first sweep after it exits. If the launcher died before naming it, or could
  not write the name (a failed write only logs a warning), the next sweep
  removes the scratch under it, and anything the CLI writes there
  afterwards makes an unclaimed dir that is never swept.
  - The integration check measured, with stand-ins, two cases in which a CLI
    that ignores its input closing leaks:
    - a graceful close, in which the SDK's close signals only the launcher.
      S116's graceful-close wait now ends that tree;
    - a killed harness. Nothing signals that CLI, and the in-wrap launcher
      may signal only itself, so the launcher and the CLI keep running, and
      their scratch stays while they do. CRL-185.
- **Scope.** Only direct children of the harness's temp dir
  (`tempfile.gettempdir()`) and of the harness socket root are swept. These
  stay:
  - a scratch made under a `TMPDIR` from the user's settings `env`, which
    lands outside the swept temp dir;
  - `omnigent-osenv-*` dirs that other code makes without the launcher (the
    os_env helper, the codex worker, the terminal), which carry no claim and
    which only their owners remove, so a killed owner leaves them; they hold
    no seed copy;
  - a dir in a temp dir shared with another pid namespace or, on Linux,
    another boot or machine, which is never judged gone;
  - a dir whose claim was written where Linux could not read the pid
    namespace or boot id.

  Do not share a temp dir between machines: on macOS a claim carries no boot
  id, so another Mac's live dir can be judged gone.
- **Pid reuse.** If a dead owner's pid is in use again, the owner's dirs stay
  until that process exits. Pid reuse never removes a dir.
- **Exposure while running.** While an executor runs, its seed and its live
  launches' scratches stay in the shared temp dir. Other agents whose sandbox
  grants cover the temp dir can read and write them (ADR-05's accepted
  residual, in "Addendum: CRL-178 Claude config isolation for every sandboxed
  agent"; S116 does not change it). They can also change these dirs' claims,
  so a dir stays after its owner exits or goes while it runs. Code in a
  launch's own sandbox can read its seed copy (CRL-197).
- **Windows.** On Windows the claims and the sweep do nothing; leftovers there
  are unchanged. No ticket.
- **Launcher script.** `omnigent-sandbox-*.sh` holds the encoded policy and no
  secrets. Only the executor's `__del__` removes it, so it can outlive
  `close()`, and a killed harness leaves it (from code). No ticket.
- **Smaller limits, from code.**
  - The profile dir's `atexit` cleanup removes its claim before its `rmdir`.
    If the dir still holds an entry, it stays unclaimed; it holds no secret.
  - A process forked after it made its profile dir shares that dir with its
    parent, and a sweep can remove it under the child once the parent exits.
    The sweep lock is per process, so a fork while a sweep holds it would
    skip that child's sweeps. No known production code forks such a process.
  - A sweep stuck in one blocking call, as on a stalled mount, keeps the
    process's sweep lock. A cancelled `close()` or teardown waits for it only
    up to its own bound (2 s, or 10 s in `close()`), but every later sweep of
    that process is skipped, so that process removes nothing more.
  - The process manager's orphan sweep reads its `AP_PID` claims with
    `read_owner_claim`. When that refuses a file (a link, a FIFO, an oversized
    or foreign file), it falls back to its older plain integer read of the
    same file, which follows links and can block on a FIFO
    (`process_manager.py`). That fallback predates S116; it is not a
    regression.
- **Not run here.** Linux, whose rows run in CI only, and other macOS
  releases; no CI lane runs macOS (CRL-170).

## Addendum: CRL-159 probe 15 on identity-requiring servers (2026-11-23)

CRL-137 ran probe 15 on single-user servers only. CRL-159 runs it on a server
that signs users in with accounts, and turns the labelling rule in "Addendum:
probe 15" into code: each run's detail carries a `gate_integrity` label. No
Omnigent file changed, so there is no seam. The macOS verdicts are from local
runs on macOS 27.2.1 with claude 2.1.325, a mock model and throwaway
credentials. The Linux pins were measured in `coral-e2e` lane run
45187294423 (Ubuntu 24.04.5, claude 2.1.295), which matched every one. No CI
lane runs macOS (CRL-170). CRL-167 later changed how the runner gets its
tokens, what the control run must find and one check (`credential_proxy`);
the text below describes the test as it is now (see "Addendum: CRL-167
secrets out of exec-time environments").

**The identity probe.**
`tests/e2e/coral/test_sandbox_probe.py::test_probe_15_on_a_server_that_requires_identity`
(`:1449`) runs `probe15.sh` from a generated implementer's shell, as the
single-user test does, on a stack from `skeleton_stack(identity=True)`
(`tests/e2e/coral/_skeleton.py:418`):

- The server signs users in with accounts, with a throwaway cookie secret and
  first admin, and without the single-user marker (`_accounts_env`,
  `_skeleton.py:146-156`).
- The owner signs in through `POST /auth/login` (`_owner_login`, `:159`).
  Before the host starts, the JWT is written to the host's
  `~/.omnigent/auth_tokens.json` in `omnigent login`'s shape, mode 0600 and
  created exclusively (`_store_owner_login`, `:178`), and the host signs in
  with it. The test reads only that file's metadata (`_metadata_live`,
  `test_sandbox_probe.py:400`).
- The host spawns the runner directly (`OMNIGENT_RUNNER_ZYGOTE=0`, `:1482`).
  Before S123 such a runner's exec-time environment held its tunnel binding
  token and the host's bearer, and the test checked by name that both were
  there. Since S123 the host hands it both over an inherited socket, so its
  environment holds neither. The test now proves the spawn path another way:
  the runner's parent must be the host daemon, or it fails as a failed control
  (`:1511-1514`). A zygote-forked runner's parent is the zygote.

Each credential is tried on this server's owner route, `GET /v1/coral/runs`:

| Check | Kind | What the step tries |
|---|---|---|
| `owner_bare`, `owner_bare_localhost` | `owner_http` | The owner route on `127.0.0.1` and `localhost` with no credential |
| `own_runner_environ` | `environ` | Read its own runner's environment |
| `own_runner_mint` | `mint` | Read the runner's binding token from its environment, mint a JWT with `POST /v1/runners/{runner_id}/token` (`omnigent/server/routes/runner_tunnel.py:367`), and act as the owner with it |
| `own_runner_bearer`, `host_bearer` | `bearer` | Act as the owner with the host's bearer, from the runner's and from the host daemon's environment |
| `stored_credentials` | `stored` | Act as the owner with the host's stored JWT |
| `server_environ` | `environ` | Read the server's environment, which holds the cookie secret |
| `credential_files.cookie_secret` | `file` | Read a canary where `omnigent server` keeps its cookie secret by default, `~/.omnigent/artifacts/accounts-cookie-secret` in the host's home (`omnigent/cli.py:5091-5096`) |
| `other_unix_socket`, `other_abstract_socket` (Linux), `other_loopback_tcp` | `socket`, `tcp` | Connect to throwaway listeners that stand in for other programs' services: a pathname socket under `/tmp/crl-o-*`, an abstract socket with a random name, and a loopback port (`_other_programs`, `test_sandbox_probe.py:1396`) |
| `worktree_exec_config` | `plant` | Create a nested repository in the worktree whose config names a `core.fsmonitor` hook (`plant_repository`, `probe15.sh:335`) |
| `credential_proxy` | `credential_proxy` | Send a model request to the step's own CLI's credential proxy, by its loopback port: with no key, with a wrong key, and on a path that climbs to the model route (`PROXY`, `probe15.sh:261`) |
| `shell_env_names` | `shell` | Credential-like names in its own environment |

The probe prints verdict tokens and names, never a value.

- It reads a credential once, from stdin, and sends it only to the server it
  belongs to: the stored entry keyed by this server's URL, or an environment
  whose `RUNNER_SERVER_URL` names it. Anything else reads `mismatch` and is
  never sent. It follows no redirect (`IDENTITY`, `probe15.sh:187-256`).
- Every credential kind prints `<check>.read` before what the credential did,
  so a read that worked shows even when the server refused the token.
- Each kind has a closed set: `denied` and `hidden` for reads, connects and
  the plant; `refused`, `denied` and `hidden` for a bare owner request and for
  the credential proxy; and `not_present` for the shell (`CLOSED`,
  `test_sandbox_probe.py:159-178`).
  Any other verdict is open, as is a check of unknown kind, and its pin must
  name an owner (`test_every_pin_names_an_owner_exactly_when_it_is_open`,
  `:2393`).

**The control run.** Right before the step's probe call, the test runs the
same probe outside any sandbox, as the step's user, in the step's worktree
(`_run_probe`, `:1662`; called at `:1579`). It must find exactly this
(`OUTSIDE_IDENTITY`, `:1366-1391`):

- it reads the runner's environment and finds neither token there
  (`own_runner_mint` and `own_runner_bearer` `not_present`, each `.read`
  `reachable`); before S123 it minted an owner JWT from the binding token and
  acted as the owner with the bearer;
- it acts as the owner with the stored JWT;
- it reads the server's environment and the cookie canary;
- it reaches every listener and writes the plant;
- the bare owner route refuses it, and so does the credential proxy, which
  refuses any caller without its session token, sandboxed or not.

The host daemon's environment is read and holds no bearer (`not_present`), a
negative control. Any other outside verdict fails as a broken probe, never as
a verdict, so a closed verdict in the step is the sandbox's. For the two
runner checks that no longer holds by itself: outside they read `not_present`,
so the step's `denied` or `hidden` shows that the sandbox stops the read, and
the outside run shows that the read would find nothing. Host-side checks
also prove each target live before the outside run, between the runs and after
the step's, and the mock's ledger must hold none of the owner JWT, the
canary, the CLI's session token and the probe's own requests to the proxy.
The verdicts, the outside verdicts and the recorded versions are
written to `artifacts/probe15-identity-<platform>.json` before any assertion
(`:1622`), so a failing lane run still leaves them.

**What was measured.** `EXPECTED_IDENTITY` (`:1291-1341`):

| Check | macOS seatbelt (measured) | Linux bwrap (measured) | Owner |
|---|---|---|---|
| `owner_bare`, `owner_bare_localhost` | `refused` | `refused` | |
| `shell_env_names` | `not_present`, names `none` | `not_present`, names `none` | |
| `own_runner_environ` | `denied` | `hidden` | |
| `own_runner_mint`, and its `.read` | `denied` | `hidden` | |
| `own_runner_bearer`, and its `.read` | `denied` | `hidden` | |
| `host_bearer`, and its `.read` | `denied` | `hidden` | |
| `server_environ` | `denied` | `hidden` | |
| `stored_credentials`, and its `.read` | `denied` | `hidden` | |
| `credential_files.cookie_secret` | `denied` | `hidden` | |
| `other_unix_socket` | `reachable` | `hidden` | CRL-174 (macOS) |
| `other_abstract_socket` | not probed | `reachable` | CRL-174 |
| `other_loopback_tcp` | `reachable` | `reachable` | CRL-174 |
| `worktree_exec_config` | `reachable` | `reachable` | CRL-181 |
| `credential_proxy` (added by CRL-167) | `refused` | `refused`, set by reasoning until the `coral-e2e` lane runs on that change | |

So a sandboxed step on an accounts server cannot mint an owner JWT, act as
the owner with the host's bearer or the stored credentials, read the cookie
secret or the server's environment, or make a bare owner request. It can still
reach other programs' sockets and loopback services (CRL-174); a Docker
Desktop, OrbStack or `tmux -S` socket would run commands outside the sandbox
that read the owner's stored JWT. It can also plant worktree exec config
(CRL-181). The probe shows only the write. That the owner's own `git status`
then runs the hook outside the sandbox was measured on macOS 27.2.1 with git
2.54.0 during this ticket's design review.

On Linux, bwrap's pid namespace and mounts hide the other processes, the
homes and `/tmp`, while the network namespace and the worktree are shared.
Lane run 45187294423 measured every one of these pins but `credential_proxy`,
in its `probe15-identity-linux.json` artifact. From a later run, only closed-to-closed
moves and the socket, TCP and plant checks, with their owners, may be
re-pinned; an open verdict on a credential path is escalated, never re-pinned
([`../testing/tier-b.md`](../testing/tier-b.md), "Pinning probe 15").

**The single-user residual, measured.** The single-user test gains
`owner_bare` and `owner_bare_localhost`, the same bare owner request. Both are
`reachable`: measured on macOS, and on Linux in lane run 45187294423. Their
owner, and that of `server_loopback` and `server_localhost` in "Addendum:
CRL-137 probe verdicts", is the accepted residual `ACCEPTED_SINGLE_USER`
(`test_sandbox_probe.py:152`), not CRL-159.
On a server with authentication off, or a single-user header server, every
request without credentials is the owner, so such servers are never Enforced.
To close it, run an accounts server, where the identity probe shows a step's
bare request refused.

**The `gate_integrity` label as built.** The rule is a pure function,
`gate_integrity` (`coral/gates/integrity.py:171-194`). The server's facts are
read once, when the runs API is built (`server_gate_facts`,
`coral/omni/server/gate_integrity.py:45-58`; `coral/omni/server/plugin.py:505`).
The run's own host is read on each detail read (`_gate_integrity`,
`coral/api/run_service.py:549-561`). Its inputs:

| Input | Read from | Verified when |
|---|---|---|
| Server mode | `auth_mode(provider)` | it is `accounts` (`VERIFIED_SERVER_MODES`, `integrity.py:47`) |
| Server config | an allow-listed runner token, a machine client, the device grant, the single-user marker, and server state under a path every seatbelt step reads: the data dir, the config file, the artifact location and each SQLite file, as given and with links followed, case-folded on macOS (`gate_integrity.py:61-146`) | every fact was read and is off (`ServerConfigFacts.verified`, `integrity.py:141-144`) |
| Native steps | the `claude_native_steps` sub-feature | it is off |
| The run's own host | the host's live hello: the reserved `os_sandbox:` backend token and exactly one `coral_sandbox_policy:<rev>`, read only while the run's owner and account registration hold the host (`host_sandbox_reader`, `gate_integrity.py:164-189`) | its policy has a row in the table and both parts are empty |

The reasons, in this order, each at most once (`GateIntegrityReason`,
`integrity.py:27-43`):

| Reason | When |
|---|---|
| `server_mode_not_verified` | not an accounts server: single-user or proxy header, OIDC, a custom provider, or auth off |
| `server_config_not_verified` | a config fact is on or was not read |
| `native_steps_enabled` | the server may create claude-native steps, or the flag was not read |
| `host_sandbox_unknown` | the run has no host or no owner, or its rows cannot be read; the host is offline or held by another owner or registration; it reports no sandbox, two backend tokens, no revision or two that differ, or a policy with no row; or the registry raised (logged by type only) |
| `host_sandbox_open` | the policy's row names a ticket in either part |

`label` is `enforced` only with no reason. Every unknown input fails closed:
a host whose steps run with `OMNIGENT_CLAUDE_SDK_NO_SANDBOX` reports no
revision (`coral/omni/process_map.py:33-35`), and a policy with only one part
recorded has no row (`blocker_table`, `integrity.py:104-115`).
`tests/coral/gates/test_integrity.py` checks the rule over every server mode,
flag value, config fact and host policy it lists, against four tables, and
`tests/coral/omni/test_gate_integrity_facts.py` how each fact is read.

The label describes the run's pending gates as the server reads them now, and
can change between reads. It covers Coral's steps only, not other agents the
owner runs, and never says who answered a gate (`GateIntegrityOut`,
`coral/api/run_models.py:336-350`). The run detail is owner-only, and the
field names no host, backend, revision or ticket
([`../contracts/runs-api.md`](../contracts/runs-api.md), "Reads").

**The table.** Per sandbox backend and policy revision it has two parts, and
Enforced needs both empty (`integrity.py:76-118`):

| Policy | Owners of the open probe pins (`IDENTITY_PROBE_OPEN`) | Declared blockers no probe measures (`UNPROBED_BLOCKERS`) |
|---|---|---|
| seatbelt, revision 1 | CRL-174, CRL-181 | CRL-170, CRL-171, CRL-181, CRL-193, CRL-195 |
| bwrap, revision 1 | CRL-174, CRL-181 | CRL-181, CRL-193, CRL-195 |

The declared blockers:

- CRL-170: no CI lane runs macOS, so an OS or CLI update can void a seatbelt
  rule unseen.
- CRL-171: macOS Mach services, the clipboard and Spotlight are not measured.
- CRL-181: files a step leaves that the owner's tools run, beyond the probe's
  one shape, such as Claude Code project settings or a direnv `.envrc`. It is
  in both parts, so a fix that closes only the nested `.git` cannot flip the
  label.
- CRL-193: the label reads the run's own host only. An owner credential that a
  step of another live run, or of an earlier run, obtained stays usable until
  the owner changes their password. CRL-193 also owns the label's not-checked
  list (Residuals).
- CRL-195: a step that reaches the server can guess the owner's password at
  `/auth/login`, which has no rate limit
  (`omnigent/server/routes/accounts_auth.py:289-320`).

Tests keep the table bound to the pins.
`test_the_gate_label_table_holds_every_open_pin_owner_and_the_declared_blockers`
(`test_sandbox_probe.py:2446-2469`, in the `coral-e2e` lane) requires the
current revision's rows to be exactly the pinned backends'. Every open pin's
owner (identity, single-user and allow-listed-token pins, less the accepted
residual) must be in its row, and what is left after removing each owner once
must equal the declared list.
`test_the_declared_blockers_are_the_open_paths_no_probe_measures` and
`test_every_recorded_row_stays_as_it_was_recorded`
(`tests/coral/gates/test_integrity.py:224-246`) freeze every row.

**Rows are append-only per policy revision.** A host reports the revision of
the rules it runs (`SANDBOX_POLICY_REVISION`, `coral/omni/process_map.py:13`),
so a host on older code keeps the row it was measured under. A new revision is
needed only for a change that alters a gate row: an in-sandbox pin's open or
closed state or its owner, or a sandbox rule probe 15 measures (an Omnigent
sync that touches `seatbelt_sandbox.py`, `bwrap_sandbox.py` or the step's
environment rules included). Outside change detectors (such as
`runner.names`) and outside control maps (`OUTSIDE_IDENTITY`,
`OUTSIDE_PROBE15`) never need one, nor does a new pin that is closed with no
owner; "Addendum: CRL-167 secrets out of exec-time environments" applies
this. When a gate row changes that way, or a server-side change widens what a
step can reach:

1. Bump `SANDBOX_POLICY_REVISION`.
2. Re-run the identity probe on both platforms, re-pin `EXPECTED_IDENTITY`,
   and set each platform's `RECORDED_IDENTITY` `sandbox_policy` to the new
   revision.
3. Add the new revision's rows to `IDENTITY_PROBE_OPEN` and
   `UNPROBED_BLOCKERS`, and to `RECORDED_ROWS` and the policy set in
   `tests/coral/gates/test_integrity.py`.
4. For a host-side change, keep the old rows, so older hosts keep theirs, or
   delete them with their `RECORDED_ROWS` entries, so older hosts read
   `host_sandbox_unknown`. A server-side change that widens what a step can
   reach (the sandbox paths or network in the bundle seeds' `os_env`, the
   checkout read grant, the step harness, the environment rules the server
   sends) must delete every older revision's rows: older hosts receive the
   wider bundle from the server, but their rows were measured under the
   narrower one.
5. Never edit a recorded row, with one exception: a declared blocker in server
   code (CRL-193, CRL-195) leaves every row, and its `RECORDED_ROWS` entries,
   in the change that fixes it and adds its test, since the server fix reaches
   every host at once.

A host on a revision with no rows reads `host_sandbox_unknown`. The pin of
seatbelt's default read roots (`coral/omni/_upstream.py:9`) catches a rename
of that constant, not a grant added under another name, so check each sandbox
change for a bump.

**When it flips.** Today every row names open tickets, so every gate reads
`not_enforced`. On an accounts server with every other fact verified the only
reason is `host_sandbox_open`, as the identity test records on macOS and in
lane run 45187294423 on Linux (`RECORDED_IDENTITY`,
`test_sandbox_probe.py:1343-1361`). A row empties once each of its pins reads
closed and each declared blocker is gone. Closed pins, and a declared blocker
that a probe check pins closed, leave through a new revision. A declared
blocker in server code (CRL-193, CRL-195) leaves through its own fix and test,
which removes it from every row (step 5). Any other declared blocker leaves
only when the owner accepts it in this ADR.

**Residuals and owners.**

- **Login guessing** at `/auth/login` (CRL-195), now a declared blocker on both
  backends.
- **OIDC.** The native sign-in hands an owner JWT to any loopback redirect
  after one owner click, with no consent page
  (`omnigent/server/routes/auth.py:324-328`, `:1074`, `:1296`). OIDC servers
  read `server_mode_not_verified` until a consent step lands and the identity
  probe runs on OIDC (CRL-194).
- **The owner-wide history** (CRL-193), a declared blocker: the owner's other
  live and earlier runs, a host upgraded under live runners (the label reads
  the host's current hello, not each runner's), and showing the label on gate
  cards and the Inbox.
- **Single-user servers**, accepted, as above.
- **Not checked by the label.** CRL-193, a declared blocker on every row, owns
  this list, so none of it is accepted. Each item needs a check before any row
  empties:
  - read roots beyond seatbelt's default subpaths: bwrap's own read-only
    roots, and per-step grants such as the checkout's packages, the
    interpreter prefix and the CLI install;
  - bwrap's `bind_host_proc` under a vetted outer sandbox (`lakebox`,
    `phoenix-kubernetes`; `omnigent/inner/bwrap_sandbox.py:225`), which the
    policy token does not show;
  - databases reached over loopback, beyond the CRL-174 pins: a database on a
    network host does not count as server state;
  - `coral_sandbox_policy:` claims from tool providers, which any installed
    provider can send; claims that differ read unknown;
  - future step-harness flags such as `codex_steps` and `sandbox_runs`
    (`coral/api/sub_features.py:15`, `:24`), which must feed the label before
    they are used;
  - the host's live hello rather than each runner's (CRL-193);
  - replica flapping: the host registry is per replica, so a replica without
    the host's tunnel reads `host_sandbox_unknown`, and the label can change
    between reads;
  - the step model's tools: `step_roster` is a denylist of the tools that
    reach other sessions and agents (`coral/omni/policies/guards.py:98-121`),
    so a new default Omnigent tool reaches steps unseen, and the probe
    measures the shell only;
  - the orchestrator's and anchor's CLIs, which have no `os_env` and run
    outside the sandbox (CRL-180).
- **Not covered by Enforced:** agents the owner runs outside Coral, and other
  accounts that share the owner's OS user; sign-ins the owner approves, such
  as a link a step asks the owner to open (the device grant, when on, reads
  `server_config_not_verified`); tools from tool providers other than
  Coral's; and UDP.
- **Probe limits.** On Linux the step's in-namespace ancestors are measured
  only through the shell's environment. The plant tries the nested `.git`
  shape only. The server's database, the server's own bootstrap copy of an
  owner JWT, and writes to `~/.omnigent` are not targeted.

## Addendum: CRL-167 secrets out of exec-time environments (2026-11-24)

Probe 15 found secrets where any process of the same user can read them: in
the environments and command lines that runners, harnesses and Claude CLIs
start with. S111 stopped a sandboxed step on macOS from reading them, and
bwrap's pid namespace does on Linux. Processes outside the sandbox could
still read them, and code inside a CLI's own sandbox inherits the CLI's
environment. CRL-167 takes the secrets out for Coral, with three seams in
Omnigent files (`.coral/seams.yaml`): S123 for runners, S124 for the model
credential and S125 for the user's settings `env` block.

A Coral CLI below is the Claude CLI of a Coral agent: a step's, the
orchestrator's or the anchor's. Unless a line says otherwise, everything here
is POSIX only, and Windows keeps its behaviour. The macOS results are from
local runs on macOS 27.2.1 with claude 2.1.325, a mock model and fake keys.
Linux has not run: its pins are set by reasoning until the `coral-e2e` lane
runs on this change. The macOS sandbox lane (CRL-170) also runs probe 15 on it.

**Runners (S123).** A forked process's readable environment
(`/proc/<pid>/environ` on Linux, `KERN_PROCARGS2` on macOS) is the one its
parent was exec'd with, whatever it later does to `os.environ`. The host
exec'd its runner zygote with the daemon's whole environment, so the zygote,
every runner it forked and every harness those runners forked showed all of
it.

- **The zygote's base environment.** The host now starts the zygote from
  `_zygote_base_env` (`omnigent/host/connect.py`), read again at each zygote
  spawn. It holds:
  - the runner allow-list: its exact names and the `LC_`, `MLFLOW_`, `OTEL_`
    and `OMNIGENT_OTEL_` prefixes;
  - minus every credential-shaped name: one that, in upper or lower case,
    contains `TOKEN`, `SECRET`, `PASSWORD`, `PASSWD`, `CREDENTIAL`, `BEARER`,
    `API_KEY`, `PRIVATE_KEY` or `COOKIE` (probe 15's set), starts with
    `HARNESS_CLAUDE_SDK_`, or ends with `_HEADERS`, `_PAT`, `_CRED` or
    `_CREDS`;
  - minus every name whose value holds URL userinfo (`scheme://user@host`);
  - plus `MALLOC_ARENA_MAX`, `MALLOC_TRIM_THRESHOLD_`, `LD_LIBRARY_PATH` and
    `PYTHONHOME` when the daemon has them, because the allocator, the loader
    and the interpreter read them once at exec. `LD_LIBRARY_PATH` and
    `PYTHONPATH` keep only their absolute entries: a relative entry would
    search a fork's working directory, which a step can write.
- **Runners lose nothing.** The host still sends each runner every
  allow-listed and forwarded name in the fork payload, which lives in the
  forked runner's memory only.
- **Runner tokens over a socket pair.** When the host spawns a runner directly
  (zygote off, failed or dead), it no longer puts any name of the runner auth
  secret list (`RUNNER_AUTH_SECRET_ENV_VARS`, `omnigent/runner/identity.py`)
  in the runner's `env=`. The list has three names since the allow-listed
  tunnel token joined it (CRL-168): `OMNIGENT_RUNNER_TUNNEL_BINDING_TOKEN`,
  `OMNIGENT_RUNNER_INITIAL_AUTH_TOKEN` and `OMNIGENT_RUNNER_TUNNEL_TOKEN`,
  the last only when the runner's environment holds it. The host writes them
  as one JSON object of at most 16 KiB, room for a bearer JWT with group
  claims, into one end of a UNIX socket pair, closes that end, and passes the
  other to the runner, naming its number in `OMNIGENT_RUNNER_LAUNCH_FD`
  (`omnigent/runner/launch_secrets.py`). It first grows that end's send
  buffer to 32 KiB where the default is smaller (macOS: 8 KiB), so the write
  never waits. It is a socket, not a pipe: on Linux a process of the same
  user can reopen an inherited pipe through `/proc/<pid>/fd`, but not a
  socket. If the tokens cannot be sent, a payload over the cap included, the
  launch fails; nothing falls back to the environment.
- **Tokens held in memory.** The runner's `main()` reads that socket before
  it logs or starts anything. It must be a socket, end within 5 s and hold
  only names from that list, each once; otherwise the runner prints one line
  that names no value and exits 2. Then the runner moves every name in the
  list, all three, out of `os.environ` into a holder in its own memory
  (`omnigent/runner/identity.py`), which also covers a zygote fork's payload
  and a CLI-local runner's environment. So no child the runner starts inherits
  any of them.
- **Forwarded names.** The host also tells each runner which credentials it
  forwarded, by name only, in `OMNIGENT_RUNNER_FORWARDED_NAMES`, so a Coral
  harness can drop them (next).

**Harness config and forwarded credentials (S124).** The Claude Agent SDK
copies the harness's whole `os.environ` into every CLI it starts. The
harness's own config sat there as `HARNESS_CLAUDE_SDK_*` names, the key helper
(`printf %s '<key>'`) among them.

- **Config off the CLI's environment, for every agent.** The harness's
  `create_app()` (`omnigent/inner/claude_sdk_harness.py`) moves every
  `HARNESS_CLAUDE_SDK_*` name out of `os.environ` once, and every executor
  build reads that config. This holds for every claude-sdk agent, on every
  platform.
- **The key off a direct-exec harness's environment.** When a runner starts a
  claude-sdk harness by direct exec (harness zygote off or failed), the two
  config names that can hold a key, `HARNESS_CLAUDE_SDK_API_KEY_HELPER` and
  `HARNESS_CLAUDE_SDK_GATEWAY_AUTH_COMMAND`, travel over a launch socket of
  the same kind (`OMNIGENT_HARNESS_LAUNCH_FD`) and are read straight into the
  config. A zygote-forked harness gets its config in the fork payload, in
  memory only.
- **Forwarded credentials off a Coral CLI's environment.** A Coral harness
  then removes from its `os.environ`, for good:
  - every credential name the host forwards (`HARNESS_CREDENTIAL_ENV_VARS`,
    with the `OMNIGENT_` aliases), such as `ANTHROPIC_API_KEY`,
    `OPENAI_API_KEY` and `GIT_TOKEN`;
  - every name listed in `OMNIGENT_RUNNER_ENV_PASSTHROUGH` or in
    `OMNIGENT_RUNNER_FORWARDED_NAMES`;
  - the provider switches the pinned CLI reads: `CLAUDE_CODE_USE_*` and
    `CLAUDE_CODE_SKIP_*_AUTH` for Bedrock, Vertex, Foundry, Mantle, Anthropic
    on AWS and Anthropic on Google Cloud, and `CLAUDE_CODE_USE_GATEWAY`, which
    the executor sets itself where a gateway needs it;
  - every name whose value contains the configured static key, when that key
    has 20 characters or more;
  - every proxy setting whose value holds an `@`.

  It never removes `PATH`, `HOME`, the temp dir, user, shell, locale and
  terminal names, `ANTHROPIC_MODEL`, the TLS trust names (`SSL_CERT_FILE`,
  `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE`, `NODE_EXTRA_CA_CERTS`) or a proxy
  setting without an `@`. The environment as it was before this scrub stays in
  the harness's memory, for two uses only: running a credential command, and
  the proxy's own connection to the model endpoint.

**The credential proxy (S124).** A Coral CLI no longer gets the model
credential. Its executor holds it, in the harness process, behind a proxy on
loopback. The proxy is `ClaudeGatewayShim`
(`omnigent/inner/claude_gateway_shim.py`), which gateway launches already ran
to restore `thinking.display`, in a new credential mode. It is on for a Coral
executor that has a credential command, with a gateway or on a plain API key.

- **What the CLI holds.** Its `ANTHROPIC_BASE_URL` is the proxy's
  `http://127.0.0.1:<port>`. Its environment holds a session token in
  `OMNIGENT_CLAUDE_PROXY_TOKEN`: `session-` and 256 random bits, made per
  executor, so it never has the shape of an Anthropic key. Its `--settings`
  key helper is `printf %s "$OMNIGENT_CLAUDE_PROXY_TOKEN"`, so no command line
  carries a secret. `127.0.0.1,localhost` is appended to its `NO_PROXY`, so an
  inherited proxy cannot take the loopback hop. There is no fallback that
  hands the CLI the real command or puts the token on a command line.
- **What the proxy holds.** A static key (`printf %s <key>`) is held as its
  value and no shell starts. Any other command is run by the harness: `/bin/sh
  -c`, in its own session, from the user's home directory, with the
  harness's environment from before the scrub. Its stderr is discarded, its
  output is capped at 64 KiB, and it is killed with its process group after
  600 s. One run at a time; the value is cached for the helper's cache time
  (a gateway's refresh interval, 900 s by default; on a plain key the host's
  `CLAUDE_CODE_API_KEY_HELPER_TTL_MS`, else the pinned CLI's own 300 s), and a
  failure for 30 s. A value must be one printable ASCII token of at most
  4 KiB.
- **The proxy's rules,** in this order, before anything is forwarded:
  1. Every `x-api-key` and `Authorization: Bearer` header presented must equal
     the session token, compared in constant time; at least one must be
     present and none repeated. Otherwise the answer is 401 and the body is
     not read.
  2. The raw request path must be plain: no empty, `.` or `..` segment, no
     `@`, backslash or encoded separator, and a model id of letters, digits
     and `._:-` only. Otherwise 400.
  3. Only `POST /v1/messages`, `POST /v1/messages/count_tokens`,
     `GET /v1/models` and `GET /v1/models/<id>` are forwarded. Anything else
     gets 404.
  4. The joined URL must keep the endpoint's scheme, host, port and base path.
     Otherwise 400.
  5. A body over 32 MiB gets 413.
  6. The real credential replaces the token in the header form the CLI used.
     Headers that an upstream gateway could route on (`Forwarded`,
     `X-Forwarded-*`, `X-Original-URL`, `X-Rewrite-URL` and the method
     overrides) are dropped.
  7. When the endpoint answers 401 and the credential is a command, the proxy
     runs it again and resends once, at most once per 30 s.

  Its error answers and log lines name exception types only, never a header,
  a URL with userinfo or a command's output. Redirects are not followed. A
  request head is capped at 16 KiB (the h11 parser), and there is no
  connection limit, since idle sockets without a token would fill one and
  lock the CLI out.
- **Where the credential may go.** On a gateway the endpoint is the gateway's
  URL. On a plain key it is the `ANTHROPIC_BASE_URL` of the user's settings
  block (below), else the host's, else `https://api.anthropic.com`. One check
  covers all three (`check_upstream_url`): `https`, or `http` to loopback; a
  host; a numeric port if any; no user name or password, backslash, control
  character, query or fragment. An endpoint that fails it refuses the turn
  (`coral_credential_upstream_refused`), with a message that repeats no part
  of the URL, before the model listing, which is the first request to carry
  the credential.
- **The proxy's own hop.** The proxy's connection to the endpoint uses the
  forward proxy named for it in the harness's environment from before the
  scrub, where a proxy name from the settings block replaces the harness's:
  the scheme's own variable, then `ALL_PROXY`, none when `NO_PROXY` covers the
  endpoint, and never one for a loopback endpoint. A proxy URL with a user
  name or password reaches this hop only. It must be an `http://` or
  `https://` URL; a SOCKS proxy or a bare `host:port` refuses the turn and
  names the variable. On a plain key a CA file (`NODE_EXTRA_CA_CERTS`) is
  added to the default trust: the settings', else the host's, each an
  absolute path outside the step's working directory. A gateway's proxy takes
  none, as before.
- **The model listing.** A gateway's model listing takes its bearer from the
  same credential, and waits at most 15 s for a command. For every agent, a
  static key goes to the listing as a value, so no shell starts, and a
  listing for a loopback endpoint ignores proxies named in the environment.
- **Fail closed.** Before each new CLI connects, the executor searches the
  environment that CLI would get, its settings and its extra arguments for a
  static key of 20 characters or more. A hit refuses the turn
  (`coral_credential_exposed`) and names variables only. The search does not
  see an encoded or split copy, a shorter key, or a command's value.
- **Closing.** `close()` waits for evicted CLIs, then stops the proxy, so no
  CLI outlives the port it calls. A cancelled or failed close still stops it,
  and a credential command still running is killed.

**The first-party switch (S124).** On a plain Anthropic key the CLI used to
talk to `api.anthropic.com` itself. Behind the proxy its base URL is loopback,
which the pinned CLI treats as a custom endpoint. So the executor sets the
CLI's private switch `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1` exactly when
the proxy's endpoint is the Anthropic API by the CLI's own rule: host
`api.anthropic.com` on its default port. It never does for a URL with
userinfo, a backslash or whitespace, and never on a gateway. What the switch
does is read from the CLI 2.1.325 build, not measured against the Anthropic
API: it restores first-party behaviour at every place that reads the CLI's
effective check, so the CLI keeps its betas, attribution fields and model
handling. A test fails when the installed CLI's build no longer names the
switch
(`tests/e2e/coral/test_sandbox_probe.py::test_the_installed_cli_knows_the_first_party_switch`).

**The settings `env` block (S125).** For a Coral CLI on a plain key the
executor used to merge the whole `env` block of the user's
`~/.claude/settings.json` into the CLI's environment, minus S13's token names
and the config dir names. Now the block is split:

| Names in the block | Go to |
|---|---|
| `ANTHROPIC_MODEL`, `ANTHROPIC_SMALL_FAST_MODEL`, `CLAUDE_CODE_SUBAGENT_MODEL`, the `ANTHROPIC_DEFAULT_*_MODEL` aliases | the CLI |
| `DISABLE_TELEMETRY`, `DISABLE_ERROR_REPORTING`, `DISABLE_AUTOUPDATER`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, when the value is `1` or `true` | the CLI. A settings file can switch an opt-out on, never switch off one the host set |
| `ANTHROPIC_BASE_URL` | the proxy, as its endpoint. The CLI keeps the loopback URL |
| `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY`, `NO_PROXY`, in upper or lower case | the proxy's own hop. Also the CLI, when the value holds no `@` and, for a proxy URL, no path, query or fragment |
| `NODE_EXTRA_CA_CERTS`, an absolute path outside the step's working directory | the proxy's own hop and the CLI |
| Everything else: provider switches (`CLAUDE_CODE_USE_BEDROCK`, `_VERTEX`, `_FOUNDRY`, `_MANTLE`) with their endpoints and credentials, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_CUSTOM_HEADERS`, `AWS_*`, `*_TOKEN`, `CLAUDE_CODE_MAX_OUTPUT_TOKENS`, `CLAUDE_CODE_API_KEY_HELPER_TTL_MS` | dropped |

**The trust rule.** The endpoint, proxy and CA names say where the real
credential goes, so they count only from a settings file a step can neither
place nor write: `CLAUDE_CONFIG_DIR` is absolute or unset (the default
`~/.claude`), and resolving the file's path, one link at a time, never enters
the CLI's working directory. On macOS names are compared without case. The
file is located from the `CLAUDE_CONFIG_DIR` and `HOME` the harness started
with. From any other settings file:

- an `ANTHROPIC_BASE_URL` refuses the turn before the proxy starts, naming the
  variable only, rather than send the key to another endpoint than the one the
  user named;
- proxy and CA names are ignored, with one warning per name in the runner
  log.

Model names and opt-outs are taken from any settings file. Once the proxy
runs, where the key goes is settled: an endpoint written to an untrusted file
later only warns, so a step cannot stop its own later turns. A proxy that
fails to start (a CA file that cannot be loaded, a proxy URL the client
rejects) refuses that turn, and the next turn builds a new one.

A gateway launch never merged the block and still takes none of it.

**What was measured.** With fake keys and a mock model; outside reads are by
name or digest only.

| What | Where | Result |
|---|---|---|
| A real zygote started from `_zygote_base_env` with fake host secrets, a runner it forks and that runner's harness (`tests/host/test_runner_zygote.py::test_forked_runner_and_harness_expose_only_allow_listed_names`) | macOS, local | each shows only allowed names, the control fd and the platform's `__CF_USER_TEXT_ENCODING` and `__PYVENV_LAUNCHER__`; no fake secret |
| A real direct-spawned child that reads its launch socket (`tests/runner/test_launch_secrets.py`) | macOS, local | with a 12 KiB payload, it holds all three runner auth secrets in memory; its readable environment names the fd and none of them; a child it starts inherits none |
| A real direct-exec claude-sdk harness (`tests/runtime/harnesses/test_process_manager.py`) | macOS, local | its readable environment lacks both key-bearing names while its executor config has them |
| The allow-listed-token stack test, `runner.names` and `harness.names` | macOS, local; Linux by reasoning | `none` |
| The identity stack test, run outside the sandbox on a direct-spawned runner | macOS, local; Linux by reasoning | the runner's environment is read and holds neither token (`own_runner_mint`, `own_runner_bearer`: `not_present`) and no credential-like name |
| Probe 15 run outside the sandbox on a single-user stack: the reviewer's runner and CLI, the host and the step's own CLI | macOS, local; Linux by reasoning | each is read (`reachable`); the API key is in none of their environments or command lines (`not_present`; before S124 it was on both CLIs' command lines); each CLI's environment names `OMNIGENT_CLAUDE_PROXY_TOKEN` and no `HARNESS_CLAUDE_SDK_*` name |
| `credential_proxy`: from the step's shell and from outside, a model request to the step's own proxy with no key, with a wrong key, and on a path that climbs to the model route | macOS, local, single-user and identity stacks; Linux by reasoning | `refused`, pinned closed with no owner; the mock received none of the three, and the session token is in no request body it recorded |
| A Coral step's real sandboxed CLI behind the proxy (`tests/e2e/coral/test_tier_b_executor.py`, local only) | macOS, local | the key helper's environment inside the sandbox holds the session token and not the model key; the proxy refused none of the CLI's requests, so the pinned CLI needs no route beyond the four |
| A real CLI on a plain key, with and without the proxy (same file) | macOS, local | the same `anthropic-beta` header and `thinking` field either way; with the first-party answer forced, three more betas and the same `thinking` field |
| The stack test on a plain key with the host's `ANTHROPIC_BASE_URL` naming the mock, every proxy setting of the host naming a recorder that refuses | macOS, local; Linux by reasoning | both steps complete through their proxies; the recorder sees nothing |

The settings block and its trust rule are covered by unit tests only
(`tests/inner/test_claude_sdk_executor.py`); no real CLI run exercises them.

**Not measured.**

- **Linux.** Nothing here has run on Linux. Set by reasoning until the
  `coral-e2e` lane runs: `EXPECTED_TOKEN["linux"]`'s `runner.names` and
  `harness.names`, `credential_proxy` in `EXPECTED["linux"]` and
  `EXPECTED_IDENTITY["linux"]`, and both outside maps. The lane installs
  claude 2.1.295. That this build passes its environment to the key helper,
  names the first-party switch and offers `ToolSearch` on a plain key was
  measured or read only for 2.1.325.
- **The Anthropic API itself.** No test holds a real key, and a mock is not a
  first-party endpoint, so the first-party switch runs only when a local test
  forces it. An opt-in live run on a plain key would be follow-up evidence;
  the live test uses the gateway path.
- **Other routes.** The four routes were enough in tests, which run with
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. A CLI without it may try other
  paths on its base URL; the proxy answers 404 and forwards nothing. A
  Databricks AI Gateway endpoint was not run.
- **The trust rule's link walk and case rule** ran on macOS only.

**What changes for users.**

- **Provider switches in `settings.json` no longer apply to Coral steps.**
  `CLAUDE_CODE_USE_BEDROCK`, `_VERTEX`, `_FOUNDRY` and `_MANTLE`, with their
  endpoints, regions and credentials, are dropped, and so are the same
  switches exported on the host. A Coral step runs on the key or provider set
  with `coral setup`.
- **Other settings names are dropped too**, such as `ANTHROPIC_AUTH_TOKEN`,
  `ANTHROPIC_CUSTOM_HEADERS` and `CLAUDE_CODE_MAX_OUTPUT_TOKENS`. On a plain
  key a helper's cache time comes from the host's environment only.
- **Credential helper commands run in the harness**, outside the step's
  sandbox, from the user's home directory, with the environment the harness
  started with and a 10-minute timeout. A relative helper path resolves
  against the home directory, and the helper does not see the settings
  block's variables. The step's sandbox no longer needs to reach what the
  helper reads.
- **An endpoint in an untrusted settings file stops the step** (the trust
  rule). To fix it, keep the file under an absolute `CLAUDE_CONFIG_DIR`
  outside the step's working directory, or remove the setting.
- **Endpoint and proxy rules.** An endpoint URL with a user name, a password,
  a query or a fragment, or plain `http` to another machine, stops the step,
  on a gateway too. So does a SOCKS or `host:port` proxy for the model
  endpoint, and a CA file that cannot be loaded, where Node only warned.
- **Forwarded credentials no longer reach a Coral CLI,** nor what it starts:
  its key helper, hooks and stdio MCP servers. `GIT_TOKEN` and `GIT_USERNAME`
  are among them.
- **The zygote reads fewer names.** A name outside the allow-list that the
  zygote read at its exec or import now behaves as on direct spawn, where it
  was never passed: for example `OMNIGENT_HARNESS_SHUTDOWN_TIMEOUT_S`,
  `OMNIGENT_HARNESS_HARD_EXIT_TIMEOUT_S`, `WEBSOCKETS_*`,
  `PYDANTIC_DISABLE_PLUGINS`, `PYTHONUSERBASE`, the interpreter's startup
  variables and `OPENSSL_CONF`. Names listed in
  `OMNIGENT_RUNNER_ENV_PASSTHROUGH` reach a zygote-forked runner through the
  payload only, after the zygote's exec and imports.
- **A model listing for a loopback endpoint** ignores proxies named in the
  environment, for every agent.
- **Windows is unchanged:** runners keep their tokens in the environment, a
  Coral CLI keeps the key on its command line and the whole settings block.

**Why the sandbox policy revision stays at 1.** A new revision is needed only
for a change that alters a gate row: an in-sandbox pin's open or closed state
or its owner, or a sandbox rule the probe measures ("Addendum: CRL-159 probe
15 on identity-requiring servers", "Rows are append-only per policy
revision"). This change alters none:

- no sandbox profile, probe check or step environment rule that a pin
  measures changes, and no in-sandbox verdict moves;
- `runner.names` and `harness.names` are outside change detectors, read by
  the test from outside the sandbox;
- `OUTSIDE_IDENTITY` and `OUTSIDE_PROBE15` are outside control maps;
- the one new in-sandbox pin, `credential_proxy`, is closed with no owner on
  both platforms, so it adds nothing to a row.

No row ever named CRL-167, since S111 and the pid namespace already closed
the in-sandbox reads. A host on older code and one on this code therefore
have the same rows, and the label reads the same for both. The table and the
tests that bind it to the pins are unchanged.

**Residuals and owners.**

| Residual | Owner |
|---|---|
| Other Omnigent agents' claude-sdk CLIs keep their key or command on `--settings` (their environment no longer holds the helper config) | CRL-197 |
| `CLAUDE_CODE_OAUTH_TOKEN`, which the host passes to every runner and other agents' CLIs need | CRL-197 |
| The S115 seed copy of MCP server secrets in another agent's private config dir | CRL-197 |
| A direct-spawned runner's `env=` still carries the forwarded credentials and the credential-shaped allow-listed names; a direct-exec harness's still carries the forwarded credentials, a key referenced as `env:VAR` among them under `VAR` | CRL-197 |
| Credential-shaped allow-listed names, such as `MLFLOW_TRACKING_TOKEN`, `OMNIGENT_DEBUG_LOG_CLIENT_SECRET` and the OTel header names, still reach runners, harnesses and CLIs through the payload | CRL-197 |
| A credential in the value of a name that is not credential-shaped, outside URL userinfo (a signed query string, for example), still reaches the zygote | CRL-197 |
| The CLI-local runner of `omnigent run` gets its binding token at exec and inherits the user's environment; its children no longer inherit the token | CRL-197 |
| Windows: tokens in the runner's environment, the key on a Coral CLI's command line, the whole settings block | CRL-197 |
| claude-native steps: the native CLI's own shell inherits its credential. The gate label already reports `native_steps_enabled` | CRL-197 |
| Other agents' CLIs still get the forwarded credentials and the whole settings block in their environment | CRL-182 (an explicit CLI environment), CRL-197 |
| A settings file under a relative `CLAUDE_CONFIG_DIR` still chooses model names and switches opt-outs on; an endpoint a step plants there makes later executors in that worktree refuse until it is removed | CRL-182 |
| The trust rule knows only the CLI's working directory: a settings or CA file under another path that a broad write grant lets a step write is still trusted | CRL-184 |
| A harness socket has no bearer on POSIX; the launch-socket helper is there for it to reuse | CRL-173 |
| A static key shorter than 20 characters is not searched for under other variable names: the harness's scrub and the fail-closed check look only for longer keys by value. The drops by name still apply | CRL-198 |
| The session token. A same-user process outside the sandbox can read it from the CLI's environment, and code inside the CLI's own sandbox inherits it: the key helper, hooks and stdio MCP servers, so also a hook from project settings a step plants (CRL-181). It works only at that loopback proxy, on the four model routes with any server-side tools the API offers, while the harness lives. Before, the same readers got the key itself | accepted |
| An endpoint that echoes request headers in an error body shows the CLI the real credential | accepted |
| Managed settings that override `ANTHROPIC_BASE_URL` or `apiKeyHelper`: the step then fails closed and no key leaks | accepted |
| The host daemon's own environment, the LaunchAgent's `EnvironmentVariables` included | accepted: the user's own process |
| Single-user servers, where a step acts as the owner | accepted ("Addendum: CRL-159 probe 15 on identity-requiring servers") |
| Behind the proxy a CLI on a plain Anthropic key skips its bootstrap call, its fast-mode status prefetch and the key on its telemetry requests, none of them on a turn's path. The first-party switch does not reach the places that test the raw URL: the side-query beta on hook-agent and named model calls, the `cc_project` attribution tag, the resume cache warm-up, a server-flagged reminder experiment, and one resend without `thinking.display` after a 400 or 422. Read from CLI 2.1.325, not measured | accepted; the detail is in S124's note (`.coral/seams.yaml`) |
| A settings proxy with a user name, a password, a path or a query is not given to the CLI, whose other traffic uses the proxy it inherits; the harness's scrub still leaves the CLI a proxy without `@` that has a path or a query | accepted |
| In local Tier B runs a CLI without a private config dir makes two keychain lookups per launch, which the `security` stub records; the base checkout does the same | CRL-180, CRL-197 |

Console-managed settings and policy limits are not on this list: read from
CLI 2.1.325, a CLI whose only credential is a key helper was never eligible
for them, on any base URL, and a Coral step's key has always been a helper's.
