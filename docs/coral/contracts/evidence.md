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
        run: ruff format
        may_modify: true
        allow_args: true
```

- `commands` is a list of 1 or more items. `run` must be one plain command,
  under the same rules a recorded line must follow (see "Which runs count").
- `id` defaults to `c1`, `c2` and so on. Ids must be unique within the step.
- `may_modify: true` marks a command, such as a formatter, whose own changes to
  the tree do not count as a change, when the line ran nothing else.
- `allow_args: true` lets a run add arguments after `run`. By default the argv
  must be exactly `run`'s, so `pytest -q --co` does not count for `pytest -q`.
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
A failed write, a record over its 20 s budget, or a cancelled record marks the
session as lagging for 30 s. A shell run that overlapped another call of the
same session is stored with no command, so it is never evidence; it still
counts as a change.

## The check at submit

`tool_bridge` asks `EvidenceChecker.verdict(binding)` for every
`coral_submit_handoff` with `status: done`, and passes the verdict to the
planner as `EngineToolCall.evidence`. A `blocked` handoff is not checked.

1. If the step has no `done_when`, the verdict is none, and the handoff is
   taken on its word.
2. If the run has no worktree, every item is `unverified`.
3. The checker waits up to 10 s for the session's earlier calls to finish
   recording.
4. It takes the L1 digest at submit, capped at 10 s.
5. It reads the session's rows and calls `coral.evidence.evaluate`. A call of
   the session that started during the check makes the answer in progress.

A session answered "in progress" for 120 s in a row gets `unverified` for
every item instead, so a step whose worktree cannot be read cannot loop.

The evaluator walks the rows in order:

- A *change* is any of these:
  - a write or an edit;
  - a shell run whose `l1_after` is unknown, or differs from the last known
    digest, unless the line ran only `may_modify` items;
  - a submit digest that differs from the last known digest.
- An item passes when its latest matching run after the last change exited 0.
- A run whose own digest after could not be read is `unverified`, not
  `predates_change`.

### Which runs count

Matching fails closed (`coral/evidence/match.py`). A line counts only when it
is a chain of plain commands joined by `&&`. Within it, an item counts only in
the trailing run of commands that are all required items: the line exits 0
only if they all passed, and nothing after them can undo what they saw.

- `pytest -q` and `ruff format . && pytest -q` count.
- `pytest -q && mv /tmp/a tests/a` does not: a command follows the test.
- These refuse the whole line:
  - `#`, `$`, a backtick, a newline or `<<` anywhere;
  - a join other than `&&`: `||`, `;`, `|`, `&`;
  - grouping `( ) { }`, or a function definition;
  - an env assignment, e.g. `PYTEST_ADDOPTS=--co pytest -q`;
  - a command that changes the shell: `cd`, `alias`, `trap`, `export`,
    `eval`, `exec`, `source`, `env`, `set` and the like.
- One level of `sh|bash|zsh|dash -c '<script>'` is unwrapped, with flags
  `-e`, `-u` and `-x` only (no `-l` or `-i`, which load startup files). Its
  script follows the same rules.

| Verdict | When | Reply | Written |
|---|---|---|---|
| Pass | every item passes | the handoff is accepted | `HandoffReceived`, `HandoffEvaluated(accepted)` |
| Missing | an item is `never_ran`, `predates_change`, `failed`, `exit_unknown` or `unverified` | `evidence.missing`. The `message` names each item; `next` says to rerun and submit again. | `HandoffReceived`, `HandoffEvaluated(evidence_missing, missing=ids)` |
| In progress | a call is still being recorded or started during the check, a record failed in the last 30 s, the submit digest cannot be read, or the run cannot be loaded; for at most 120 s | `evaluation_in_progress`, retry shortly | nothing |

A missing verdict spends one of the step's `attempts`, which default to
`DEFAULT_ATTEMPTS`. Below the cap the slot goes back to working. At the cap
the step takes its `failure` arrow, or the run pauses with
`attempts_exhausted`. On that last attempt, `next` says stop instead of
asking for another try.

## Limits

- **One server process.** Calls still in flight, overlaps and the 120 s limit
  are tracked per process, so another replica's running call is covered only
  once its row is stored.
- **What a test reads.** Edits to test config (`conftest.py`, `pytest.ini`)
  are changes like any other, and the tests must run again after them. Whether
  those edits are honest is for review, not for this check.
- **Claude SDK steps only.** Commands a step runs through native harness
  tools, not `sys_os_*`, are not seen. This is HRN-03.
- **No per-step scope.** The scope is `per_agent`: one session's own calls.
- **L1 only.** The digest covers HEAD, `git status` and each dirty path's
  content (`coral.evidence.fingerprint.l1_digest`, see
  [`workspace-ops.md`](workspace-ops.md)). L2 is WSP-02.
