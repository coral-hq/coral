# SPK-04: Workspace and evidence decisions

- **Status:** Proposed — pending WORKSPACE-lead sign-off.
  - The K13 text it hands over is **draft v1, not frozen**. The freeze waits on
    three open decisions for a person, D-K13-1 to D-K13-3 (below).
- **Date:** 2026-11-15
- **Decides:**
  - OQ-39, OQ-44 and OQ-10;
  - the L1 and L2 fingerprint algorithms;
  - the spike 8 verdict, and its contingency, which is **declared triggered**;
  - the draft K13 handed to WSP-01, now the K13 draft v1 contract.
- **Evidence:**
  - the probe [`probes/spk04_sandbox_git.py`](probes/spk04_sandbox_git.py);
  - the contract [`../contracts/workspace-ops.md`](../contracts/workspace-ops.md)
    and its conformance suite
    `tests/coral/workspace/conformance/test_workspace_ops.py`;
  - the S71 repro in `tests/host/test_orphan_reaper.py`.

| Item | Decision or verdict | Consumer |
| --- | --- | --- |
| OQ-39 | Engine commits run no repository hooks, say so in a trailer, and are never pushed at M2 | WSP-06, CRL-128 |
| OQ-44 | Sibling `<repo>-worktrees/`; checks sandboxed and refused without a sandbox; `worktree_parent` deferred | WSP-01, WSP-02 |
| OQ-10 | Evidence per agent, plus Coral-run checks after merges | EVD-01, EVD-02 |
| L1 / L2 | Algorithms in the contract (summary below) | EVD-01 (K11) |
| Spike 8 | `darwin_seatbelt`: **blocked**; `linux_bwrap`: **not run** | CRL-128 |
| Contingency | **Triggered**, HIGH confidence; Linux confirmation owned by CRL-128 | WSP-06 schedule |
| Draft K13 | [K13 draft v1](../contracts/workspace-ops.md): not frozen, D-K13-1..3 open | CRL-128, WSP-02, EVD-01 |

## Open decisions for a person

K13 stays draft until these are decided. They gate the K13 freeze and
CRL-128's real backend, not this ticket's acceptance criteria.

- **D-K13-1:** run a repo's own filter/merge drivers (e.g. Git LFS) inside
  Coral's own sandbox, or refuse repos that configure them. Until decided,
  backends refuse such repos.
- **D-K13-2:** whether fingerprints taken in an agent's session shell count as
  evidence (EVD-01/EVD-02).
- **D-K13-3:** whether K13 can still tighten for security after the
  real-backend gate. Until decided, K13 stays draft.

## OQ-39: engine commits and hooks

**Decision.**

- **Hooks.** Engine git in the K13 ops runs no repository hooks, including
  hooks defined in config.
  - **Not yet for run-worktree creation.** That is not a K13 op. It currently
    uses Omnigent's worktree create (`git worktree add`), which runs the
    repository's `post-checkout` hook, and its `reference-transaction` hook for
    the new branch, as Omnigent's own session worktrees do.
  - **Follow-up: a hookless run-worktree create.** An S72 extension runs the
    create with `-c core.hooksPath=/dev/null` and refuses config-defined hooks,
    as the K13 ops do.
- **Config and flags.**
  - The ops run with global and system config disabled, and with the "Git
    defaults" from the contract: hardening flags, and `GIT_OPTIONAL_LOCKS=0`
    so READ ops never write `.git`.
  - Commits use plumbing (`commit-tree`, `update-ref`), never porcelain
    `git commit`.
- **Refusal.** Until D-K13-1 is decided, a repository is refused when its own
  config defines hooks, or when the user's full config (global included)
  defines filter or merge drivers, such as Git LFS. Reading config runs no
  program.
- **Identity.** Commits keep the user's own `user.name` and `user.email`, read
  from the full config. `Coral <coral@localhost>` is used only when they are
  unset.
- **Trailer.** Each engine commit carries `Coral-Hooks: skipped`, written only
  after the backend has verified that no hook can run. The trailers, not the
  identity, show that a commit is the engine's.
- **No pushes.** Nothing is pushed at M2.

**Why.** Hooks are not evidence. Coral-run checks and the final PR's CI are
(`docs/coral/roadmap/investigation/eng_workspace.md` §4.3). A repo hook, an
fsmonitor command or a config-defined driver is code from the repository. It
would run on the engine's own executor, outside any agent sandbox.
`core.hooksPath` alone does not stop config-defined hooks, which is why the
backend checks for them and refuses. The trailer puts the choice in each
commit, so the run log can show it.

This covers engine commits on `coral/*` branches only. Agents are never given
`--no-verify` on user branches.

The constants are `GIT_HARDENING_CONFIG`, `GIT_ENV` and the trailer constants
in `coral/workspace/ops.py`.

## OQ-44: where worktrees live and where checks run

**Decision.**

- **Worktrees.** Run worktrees use upstream's sibling directory
  `<repo-parent>/<repo>-worktrees/`. It comes from `_resolve_worktree_path` in
  `omnigent/host/git_worktree.py:419-448`, with the sibling at line 436.
  CRL-124's run worktree is `<repo>-worktrees/coral-r-<run12>-base`.
- **`worktree_parent` is deferred** until a deployment needs a read-only repo
  parent. Nothing consumes it yet, and adding it needs a request field, an
  old-host refusal and a capability token.
- **Checks.** Coral-run checks run sandboxed, under seatbelt or bwrap, in a
  sandbox no weaker than the agent's. Every backend refuses `check` without a
  sandbox, with `workspace.backend_unavailable`.

## OQ-10: whose evidence counts

**Decision.** Evidence is evaluated per agent: each step session's
observations are checked against its own submit fingerprint. In addition,
Coral runs its checks on the merged tree after each merge, because branches
that pass alone can fail once merged.

The post-merge checks use K13 `check`, which is a WRITE op and engine-owned.
K11 (EVD-01) owns the evaluation rules. Whether fingerprints taken in an
agent's session shell count at all is D-K13-2.

## L1 and L2

The contract states both algorithms once (obligation 4). In summary:

- **L1** is cheap and taken per command, before and after, and at submit. It is
  a sha256 over:
  - HEAD;
  - NUL-delimited `git status --porcelain=v2 -z`;
  - an `lstat`-based entry per dirty path, with a blob id computed in Python.

  It never follows symlinks, passes no newline-delimited path list and runs no
  filters. This replaces the roadmap's `git hash-object --stdin-paths`, which
  follows symlinks, applies filters and splits paths on newlines. EVD-01 will
  implement the byte layout once, as `l1_digest()`.
- **L2** is exact and taken at evaluation points. It is the `write-tree` id of
  a temporary copy of the index after `add -A`. L2 is a WRITE op because it
  writes objects into the git common dir.
- Both follow `.gitignore` exactly, skip `.coral/runtime/**`, and use no UI
  skip list. The contract's "Fingerprint blind spots" section lists what they
  cannot see.

**Evidence rule** (eng_workspace §5.4). A command counts if `L1_before(cmd) ==
L1_at_submit`, and the submit-time L2 equals the L2 recorded for that L1 state.

## Spike 8: sandboxed git in a linked worktree

**Question.** Can a sandboxed step-session shell run git's write path inside
a linked worktree? The write path is `add`, `commit`, a temp-index
`write-tree`, `reset --hard` and `clean -fd`.

**Probe.** `probes/spk04_sandbox_git.py` is a rerunnable port of the scratch
probe from the investigation.

- It finds the `omnigent` package itself and grants its directory as an extra
  read root.
- It runs every git command with K13's mandatory hardening, and uses the
  contract's `clean -fd -e /.coral/runtime/ -- .`.
- It builds its temporary index in a probe-only directory outside the
  worktree, which the writer may write, so `$TMPDIR` cannot decide the
  write-tree row.
- It prints one JSON verdict with no machine paths or user names.

Rerun it from the repository root:

```bash
uv run --no-sync python docs/coral/decisions/probes/spk04_sandbox_git.py
uv run --no-sync python docs/coral/decisions/probes/spk04_sandbox_git.py --git /opt/homebrew/bin/git
```

It builds a temporary repository with a linked worktree on `coral/r-probe/base`.
It then runs git through Omnigent's `create_os_environment`, using the platform
default sandbox with no network. Each role runs under two read configurations:

| Role | Write paths |
| --- | --- |
| writer | `["."]`, plus the probe-only index directory |
| reviewer | `[]` |

| Read configuration | What the sandbox gets |
| --- | --- |
| `default` | what a step session gets today |
| `git_dirs_readable` | `.git` named in `cwd_allow_hidden`, and the common dir as a read path, so only write access is in question |

`git_dirs_readable` answers a question; it is not a configuration to deploy. A
writer with `.git` unmasked and its cwd writable could rewrite `.git`.

The `mktemp` row reports `$TMPDIR` and is left out of each run's verdict.

The script is Python, not the roadmap's `spk04_*.sh`. It must drive
Omnigent's own sandbox helper exactly as a session does, and a shell script
cannot build that profile.

**Run on 2026-11-15** (the JSON prints the UTC date, 2026-11-16). The host was
macOS on arm64. Git was `/usr/bin/git`, `git version 2.54.0 (Apple Git-157)`,
which is the Xcode shim.

| Backend | writer / default | reviewer / default | writer / git_dirs_readable | reviewer / git_dirs_readable | Verdict |
| --- | --- | --- | --- | --- | --- |
| `darwin_seatbelt` | blocked | blocked | blocked | blocked | **blocked** |
| `linux_bwrap` | not run | not run | not run | not run | **not run** (no Linux host here) |

Exact errors on `darwin_seatbelt` (the probe trims long lines):

- Every git command, in all four runs, exited 1 with:
  `xcrun: error: unable to load libxcrun (dlopen(/Applications/Xcode.app/Contents/Developer/usr/lib/libxcrun.dylib, 0x0005): tried: '/Applications/Xcode.app/Contents/Developer/usr/lib/libxcrun.dylib' (file system sandbox blocked open()), …`.
  `/usr/bin/git` is the xcrun shim, and the default profile blocks the Xcode
  developer directory.
- The `mktemp` row exited 1 with `mktemp: mkstemp failed on <TMPDIR>/tmp.…:
  Operation not permitted`. The inherited `$TMPDIR` is not writable inside the
  profile. The writer's temp-index row created its file in the probe-only
  directory and then failed at the xcrun shim, like every other git row. The
  reviewer's could not create the file, as expected for a role with no write
  grant.

**Finding.** The default seatbelt profile blocks the Xcode git shim and
`$TMPDIR`. Homebrew git was not tried: it lives under `/opt`, which is in the
default read roots, and it is not installed here. The probe never reached the
linked-worktree question on macOS.

The scratch run during the investigation also failed to start the helper: an
editable checkout outside the default read roots raised `PermissionError` on
`omnigent/__init__.py`. That was a probe artefact, and the port grants the
package directory to avoid it.

The probe's stderr also carries Omnigent's own sandbox warnings, which name
the local interpreter path. The JSON verdict carries no such paths.

**Structural check** (VERIFIED in the same run, outside any sandbox):

| Check | Result |
| --- | --- |
| `git rev-parse --git-path index` in the worktree | `<tmp>/repo/.git/worktrees/coral-r-probe-base/index` |
| `git rev-parse --git-common-dir` | `<tmp>/repo/.git` |
| Index inside the main `.git` | true |
| Index inside the worktree | false |
| Common dir is the main `.git` | true |

A linked worktree's index and objects live in the main repository's `.git`.
Every write op needs write access there.

**Read in code, not run.** Omnigent's seatbelt and bwrap backends mask
top-level dotfiles in the session's cwd unless `cwd_allow_hidden` names them.
The default list holds only `.venv` (`omnigent/inner/seatbelt_sandbox.py:231`,
`omnigent/inner/bwrap_sandbox.py:104`). No sandbox code grants the git common
dir.

So, by default, git inside a step session's sandbox cannot see the worktree's
`.git` file or its metadata, and this holds for reads too. The probe's
`default` runs test this on Linux; its `git_dirs_readable` runs isolate the
write question.

## Contingency: declared TRIGGERED

**The spike-8 contingency is triggered, with HIGH confidence. Linux
confirmation is owned by CRL-128.** Two pieces of evidence support it:

1. **The macOS seatbelt default blocks the Xcode git shim and `$TMPDIR`**
   (VERIFIED above). Homebrew git is untried, so this alone does not show that
   sandboxed commits are impossible on macOS.
2. **The common-dir argument applies to any backend that enforces write roots**
   (VERIFIED by the structural check). The trigger rests on this item.
   - Write ops need write access to `<repo>/.git`.
   - Granting that to the agent's sandbox would let the agent plant hooks or
     config in the user's main checkout.
   - So even a sandbox that could commit with the common dir writable is not
     allowed to.

**Consequence.** K13 makes WRITE ops engine-owned, never inside the agent
sandbox. It leaves the M2 backend per op undecided: CRL-128 decides after a
linux_bwrap + Homebrew-git rerun of this probe. That rerun can decide whether
READ ops may stay on the session shell, subject to D-K13-2. It cannot move
WRITE ops into the agent's sandbox.

**Schedule effect** (roadmap SPK-04, risks): host-channel commit, reset and
salvage move into WSP-06 in PH2, adding 3 eng-weeks for WS-WORKSPACE. A person
must accept this. The ticket comment flags it.

## Sessionless and reviewer probes

Both are expectations; neither probe was run.

- **No live session (roadmap day 2).**
  - *Expected:* there is no request-free exec path without S40. The session
    shell needs a live session and its runner: the owner-only
    `run_environment_shell` (`omnigent/server/routes/sessions/routes_resources.py:3264-3298`),
    then the runner handler (`omnigent/runner/app.py:8297-8350`), which needs
    the session's `os_env`.
  - *Restart is not sessionless.* The roadmap's restart ladder fences the old
    session, creates the next generation unbriefed, and then salvages and
    resets for the new generation (ladder step 4), before the brief. The new
    generation's session authorizes those WRITE ops, and git runs in an
    engine-owned executor, never inside the agent's sandbox; a sandboxed
    session shell cannot run them. The host channel (S40, WSP-02) is the other
    route.
  - *Not run:* S40 does not exist yet.
- **Reviewer, `write_paths: []`.**
  - *Expected:* L1 works, and L2 and the writes fail.
  - K13's op-host rule already encodes this: L1 is READ, and L2 and the writes
    are WRITE.
  - The probe's reviewer runs were blocked on macOS, like the writer runs,
    because the Xcode shim could not start.
  - From the masking above, even L1 needs `.git` unmasked read-only and the
    common dir readable. The `reviewer/git_dirs_readable` run checks this on
    Linux.

## S71 repro (handed to WSP-05)

`tests/host/test_orphan_reaper.py::test_frame_handler_keeps_child_exit_status_while_reaper_sweeps`
is the requested repro.

```bash
uv run --no-sync pytest tests/host/test_orphan_reaper.py -q -k keeps_child_exit_status
```

## Draft K13

See [K13 draft v1](../contracts/workspace-ops.md).

## Probes not run

| Probe (roadmap SPK-04 breakdown) | Why not run | Owner |
| --- | --- | --- |
| Spike 8 on `linux_bwrap` (days 1-2) | No Linux host here | CRL-128 |
| Spike 8 on macOS with Homebrew git | Homebrew git is not installed here | CRL-128 |
| No live session (day 2) | Needs S40, the host workspace-ops channel | WSP-02 |
| L1 matrix: dirty-file re-edit, same-size edit, touch, new untracked directory, ignored file, staged versus unstaged (day 3) | Needs git working in the target executor. The real L1 is EVD-01's `l1_digest()`, with temp-repo tests that EVD-01 will add. K13 conformance pins the contract side on the fake, including the same-size re-edit. | EVD-01 |
| `exit 3`, timeout overrun, and a 600 s timeout over the tunnel (day 4) | Needs a live session shell or S40. The contract fixes the mapping: non-zero exit is a result, overrun is `timed_out`, a git-op deadline is `workspace.timeout`, and `check` timeouts are capped at 7200 s. | CRL-128 |
| Spike 9 | A note only in SPK-04 (below) | WSP-04 |

## Spike 9 (note)

Spike 9 asks whether a session can bind to a managed host id with
`host_type="external"`. The answer picks the shape of S28. WSP-04 owns the
verdict, and nothing here depends on it:

- ADR-05 treats managed hosts as unsupported, with local hosts only through M4.
  A managed child rejects `host_id` (`omnigent/server/schemas.py:1807-1811`).
- The run-worktree adapter (`coral/omni/server/worktrees.py`) refuses a host
  whose `sandbox_provider` is set, as scheduled fires do
  (`omnigent/server/scheduled/fire.py:1983`).
