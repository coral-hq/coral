# Contract K11: Done-When Evidence

A step can name commands that must pass before Coral takes its `done` handoff.
Coral records each command the step's session runs, on the server, and checks
them when the step submits. The agent's own report is never the evidence.

## Authoring

```yaml
- id: implement
  kind: step
  goal: Add the endpoint
  attempts: 3
  done_when:
    commands:
      - run: pytest -q tests/api
      - id: fmt
        run: ruff format --check .
        may_modify: false
```

- `commands` is a list of 1 or more items. `run` must be one simple command:
  no `&&`, `||`, `;`, `|` or newline.
- `id` defaults to `c1`, `c2` and so on. Ids must be unique within the step.
- `may_modify: true` marks a command, such as a formatter, whose own changes to
  the tree do not count as a change.
- The compiler stores the commands as `CompiledNode.evidence`
  (`coral/model/compile.py`). A step without `done_when` keeps its graph hash.
- Errors are reported as `EvidenceIRError` with the YAML path
  (`<node>.done_when...`).

## What is recorded

`EvidenceCapture` (`coral/omni/server/observations.py`) is the S105 tool-call
observer `coral.evidence`. It is registered by `coral_lifespan`.

It records a call only when all of these hold:

- the call is `sys_os_shell`, `sys_os_write` or `sys_os_edit`, with or without
  the `mcp__omnigent__` prefix;
- the session is a bound step session in the in-memory `BoundSessions` index,
  and not an orchestrator;
- the step has `done_when` commands.

It writes one `coral_command_observations` row per call, keyed by
`(workspace_id, session_id, op_key)`. The `op_key` is the runner's operation
id, so a retried call is stored once. Each row holds:

| Call | What is stored |
|---|---|
| shell | The command, kept as unknown when it is over 8,000 characters. The exit code and timeout flag, read only from the JSON envelope. The worktree's L1 digest just after the run, as `l1_after`. |
| write, edit | The path written. |

The digest after a run comes from `fingerprint(L1)` through the run owner's
host channel, capped at 5 s. If it fails or times out, `l1_after` is unknown,
and unknown counts as a change.

Recording happens before TOOL_RESULT policy, so before the agent sees the
result. A raise or a timeout is logged, and the tool result is never changed.
A failed write marks the session as lagging for 30 s.

## The check at submit

`tool_bridge` asks `EvidenceChecker.verdict(binding)` for every
`coral_submit_handoff` with `status: done`, and passes the verdict to the
planner as `EngineToolCall.evidence`. A `blocked` handoff is not checked.

1. If the step has no `done_when`, the verdict is none, and the handoff is
   taken on its word.
2. The checker waits up to 10 s for the session's earlier calls to finish
   recording.
3. It takes the L1 digest at submit, capped at 10 s.
4. It reads the session's rows and calls `coral.evidence.evaluate`.

The evaluator walks the rows in order:

- A *change* is any of these:
  - a write or an edit;
  - a shell run whose `l1_after` is unknown, or differs from the last known
    digest, unless the run matched a `may_modify` item;
  - a submit digest that differs from the last known digest.
- An item passes when its latest matching run after the last change exited 0.
- A run matches when one segment of the command starts with the item's argv
  and every join after that segment is `&&`. So `pytest -q || true` does not
  count, and `ruff format && pytest -q` counts for `pytest -q`.

| Verdict | When | Reply | Written |
|---|---|---|---|
| Pass | every item passes | the handoff is accepted | `HandoffReceived`, `HandoffEvaluated(accepted)` |
| Missing | an item is `never_ran`, `predates_change`, `failed` or `exit_unknown` | `evidence.missing`. The `message` names each item; `next` says to rerun and submit again. | `HandoffReceived`, `HandoffEvaluated(evidence_missing, missing=ids)` |
| In progress | a call is still being recorded, a record failed in the last 30 s, the submit digest cannot be read, or the run cannot be loaded | `evaluation_in_progress`, retry shortly | nothing |

A missing verdict spends one of the step's `attempts`, which default to
`DEFAULT_ATTEMPTS`. Below the cap the slot goes back to working. At the cap
the step takes its `failure` arrow, or the run pauses with
`attempts_exhausted`. On that last attempt, `next` says stop instead of
asking for another try.

## Limits

- **One server process.** Calls still in flight are tracked per process, so
  another replica's running call is covered only once its row is stored.
- **Claude SDK steps only.** Commands a step runs through native harness
  tools, not `sys_os_*`, are not seen. This is HRN-03.
- **No per-step scope.** The scope is `per_agent`: one session's own calls.
- **L1 only.** The digest covers HEAD, `git status` and each dirty path's
  content (`coral.evidence.fingerprint.l1_digest`, see
  [`workspace-ops.md`](workspace-ops.md)). L2 is WSP-02.
