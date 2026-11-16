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
   Without a runner on the anchor, its children cannot inherit one (DD-3).
   The counter-case is pinned by test (B).
   - The rule does not enforce itself. An owner can still attach a runner to
     the anchor (`PATCH /v1/sessions/{anchor} {"runner_id": …}`, OWNER only,
     `routes_core.py:3157-3165`). Every later step would then ride that runner.
   - So the facade (SES-03) re-reads the anchor before each step create and
     refuses to create the step while `anchor.runner_id` or `anchor.host_id`
     is set.
2. **Every child is created with `host_id` and `workspace`, and with no `git`
   options.** `workspace` is the run worktree that Coral creates once,
   request-free (DESIGN §7.5). The `git` create mode would make a new branch
   and worktree per session.
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
   - Anyone with READ on the anchor can add children to it, with any title,
     agent and labels (`orchestration.py:11803-11815`). Labels are free-form,
     and neither `coral.*` nor `omnigent.parent_wake` is reserved
     (`_sessions/helpers.py:10885`).
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
| Recovery root | A child with a `host_id` counts as independent when its runner connects (`omnigent/server/app.py:4595-4599`). | Each step is the recovery root of its own runner. |
| Stop | A stop stops only the runner the session owns, with no cascade to children (`routes_events.py:2073-2206`; `_stop_host_runner_intentionally`, `orchestration.py:832`). | An anchor stop leaves the steps alone. A step stop ends only that step's runner (test A, live probe). |
| Archive, delete | Neither ends a step runner. Both first call `_best_effort_stop`, which stops only the *turns* of descendants that this replica's in-memory status cache shows as running or waiting (`orchestration.py:730-794`, descendant loop at `:792`); this is what `tests/server/integration/test_sessions_archive.py:209` and `tests/server/routes/test_sessions_crud.py:248` pin. Archive then tears down a host runner only for the archived session itself (`orchestration.py:1024`), and the anchor has none. Delete runs runner cleanup only for the deleted session (`routes_events.py:4133-4158`), never calls `_stop_host_runner_intentionally`, and then hard-deletes the whole subtree (`routes_events.py:4224`). | Rule 4. Idle steps keep their runners until the runner idle reaper fires. A step whose running status this replica missed keeps running with no row and no stop route. SES-09 automates the stop-and-confirm; an upstream fix could tear down descendant-owned runners in archive and delete (open item 5). |
| Relaunch | Only roots relaunch when a held host returns (`app.py:4274`). | A step stays `runner_interrupted` until its next message relaunches it. Engine-driven relaunch is SES-06 (probe (f)). |
| Managed hosts | `host_id` is rejected on a managed child, which "runs on its parent's host" (`omnigent/server/schemas.py:1807-1811`). | Unsupported. Local hosts only through M4 (WSP-04). |
| `_owns_host_runner` | A child owns its runner only if no ancestor shares the runner or is unbound on the same host. A missing ancestor row also makes it "not own" its runner, which leaves the runner up: fail-open for containment (`omnigent/server/routes/_sessions/helpers.py:6261-6315`). A stop on a step that does not own its runner still returns 202 while the runner stays (`routes_events.py:2115-2147`). | With no `host_id` on the anchor, each step owns its runner, and a step stop sends exactly one stop (test A). An anchor with the steps' `host_id` but no runner would make every step "not own" its runner, so a stop or archive would leave it running (a leak, found by reading). |
| Access | Access to a child recurses to its parent; the child's own grants are ignored (`omnigent/server/permissions.py:59-65`). Children get no default-public grant of their own; they follow the parent's (`routes_core.py:1419-1436`). | Every grant on the anchor is a grant on the whole run, and a step cannot be shared on its own. EDIT on the anchor lets a collaborator message, stop and answer approvals on any step. A message to a step whose runner is offline relaunches it on the owner's host (`routes_events.py:3306-3358`, `_sessions/helpers.py:6417-6480`). READ or a public link exposes every step's workspace files (rule 6, open item 4). |
| Parent wake | A block wakes the parent after 120 s (`subagent_block_notifier.py:57`). | S51 label on every child (next section). |

## What S51 fixes, and who can set the label

**What it fixes (DESIGN §18.8).** A runner-less anchor cannot take a wake
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

**Who can set it (PR-02 security F2).**

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

**Per-link rule (PR-02 security F3).** The label governs only the link
between the labelled child and its parent. The ancestor mirror re-publishes a
child's approval on every ancestor. In `R → C → G(off)`, G's block does not
wake C, but C's mirrored copy, being unlabelled, still wakes R.

Coral's sessions are all direct children of the anchor, so this does not
arise today. Any future intermediate session that must stay silent needs the
label too (SES-03).

## Probe verdicts

The permanent tests are in `tests/server/integration/test_session_host_launch.py`:

- (A) `test_run_anchor_children_own_runners_and_outlive_its_stop`;
- (B) `test_host_bound_anchor_children_ride_its_runner`, kept as the named DD-3 pin;
- (C) `test_run_anchor_woken_only_by_child_without_parent_wake_off`.

They run in process: `_HostFrameResponder` answers the host frames, and no
runner process connects. They are **server-routing proof** through the real
create, stop and event routes and the real notifier, and they are the permanent
CI proof (DD-14). The live probe adds real processes.

| Probe | Question | Verdict | Evidence |
|---|---|---|---|
| (a) | Do two own-runner claude-sdk children in separate worktrees keep their shell cwd and writes in their own worktree? | **not run** | Not run in this ticket: it needs the claude CLI with credentials (or SPK-03's spike-4 mock). SPK-04 spike 8 found that the default macOS seatbelt blocks git (the Xcode shim) and `$TMPDIR`, so sandboxed shells in a linked worktree are unproven. Owner: CRL-128, with a Linux bwrap rerun of spike 8. |
| (b) | Does a zero-turn anchor host children that run and finish? (roadmap SPK-02) | **pass** — a zero-turn anchor hosts own-runner children that launch, connect and stop. Children taking turns to completion are not exercised: that needs a model, and is covered later by CRL-128/CRL-137. | (A). Counter-case: (B). Live probe: `anchor_has_no_host_or_runner`, `children_own_distinct_runners`, `both_runners_connected`. |
| (c) | Does S51 stop the parent wake? | **pass with S51** | (C), which fails both with the guard removed and when the guard raises instead of returning. Label matrix: `tests/runtime/test_subagent_block_notifier.py::test_parent_wake_label_gates_escalated_wake`. Live probe: `both_blocks_pending_through_grace`, `unlabelled_child_wake_attempted_after_grace`, `labelled_child_wake_never_attempted`. |
| (d) | Stop, then replace, the orchestrator child; do siblings keep running? (roadmap SPK-02) | **pass** — stopping one child stops only its runner, a replacement launches its own, and siblings keep their runners (in-process). The live probe covers stop only. | (A): an anchor stop sends no runner stop; a step stop stops exactly its runner; after the replacement launches, the sibling still has its runner and is not marked as stopped. Live probe: `anchor_stop_keeps_both_runners`, `child_stop_stops_only_its_runner`. |
| (e) | Does an anchor gate count once in the Inbox, resolve once, and resolve after `omnigent.closed`? | **not run** | Needs Inbox and gates (GTE). Owner: CRL-134. |
| (f) | Do children relaunch after a host or runner restart? | **not run** | Needs the relauncher (SES-06). Owner: CRL-128. |
| 14 | What does a post to an archived session do? | **not run** | Owner: CRL-128 (with SES-09). |
| 15 | Can a step agent use a sibling's bridge-dir bearer on its loopback router? | **not run** | Owner: CRL-128. |

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

The run recorded here is from 2026-11-16 UTC (2026-11-15 local), on macOS. It
used the Step 3 working tree based on `5739bb1c3`, with the uncommitted Step 3
changes (`base_commit_dirty: true`), and exited with code 0. An earlier run of
the first version of the probe, before the isolation changes, also passed.
Verdict:

```json
{
  "probe": "spk02_live_topology",
  "verdict": "pass",
  "date": "2026-11-16",
  "base_commit": "5739bb1c3",
  "base_commit_dirty": true,
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
  "duration_s": 138.3,
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
2. **Probes (a), (e), (f), 14 and 15**, and the turn-to-completion half of
   (b), with the owners in the table above. The ADR-05 addendum records their
   verdicts.
3. **Facade guards (SES-03).**
   - Re-check the anchor before each step create (rule 1).
   - Never give the anchor a `host_id`. An anchor that has the steps' host but
     no runner makes step stops and archives leave runners up.
   - Identify steps only by stored ids (rule 5).
   - Label every intermediate session that must not wake its parent.
   - Server-side reservation of `coral.*` labels can follow in SES-03/CRL-126.
4. **Upstream fix candidate: workspace reads bypass the file-sharing opt-in
   for child sessions.** This is pre-existing upstream behaviour (PR-03
   security F2).
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
   descendant runner for which `_owns_host_runner(descendant)` holds (PR-03
   security F1). Rule 4 applies until then.
6. **Optional upstream hardening (PR-02 security F1, F4).**
   - Spec-policy label writes can set `omnigent.parent_wake` on the session
     they guard.
   - A suppressed wake leaves no log line.
7. **Sign-off.** The tech lead and the INTEGRATION lead sign ADR-05 v1.
