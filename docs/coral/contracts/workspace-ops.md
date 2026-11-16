# Contract K13: WorkspaceOps (draft v1)

- **Status:** Draft v1 — not frozen; freeze pending D-K13-1..3 (see "Open
  decisions").
  - The text, the code, an in-memory fake and the conformance suite land
    together.
  - The same suite passing on a real backend gates CRL-128.
- **Code:** `coral/workspace/ops.py` (pure tier) holds the op names, types,
  op-host rule, errors, validators, git defaults and backend interfaces.
  `coral/workspace/fake.py` is the fake. The suite is
  `tests/coral/workspace/conformance/test_workspace_ops.py`.
- **Decisions behind it:** [`../decisions/SPK-04-workspace.md`](../decisions/SPK-04-workspace.md).

K13 is the set of git operations Coral's engine runs on a run's worktrees. It
fingerprints the tree for evidence, commits at accepted handoffs, salvages and
resets on restart, merges agent branches, runs checks and reads files.

Every requirement below is **fail-closed**. When a backend cannot meet one, it
refuses the op; it never runs a weaker version of it.

## Normative text and recipes

- **Normative:** the values, the ops table, each obligation's observable
  results and refusals, the security requirements, the op-host rule, the
  idempotency rules, the git defaults, the errors and the change policy.
  - A flag or setting that a requirement or the git defaults make mandatory,
    such as `--end-of-options`, `--no-ext-diff --no-textconv` or `GIT_ENV`, is
    part of the requirement.
  - L1's three inputs are normative, because digests from different backends
    must compare.
- **Illustrative (non-normative):** the exact git command lines and step
  sequences marked *Recipe*. They show one way to meet an obligation with real
  git, and no real backend has run them yet. A backend may use other commands
  when it gives the same observable results and meets every security
  requirement. The first real backend's run of the conformance suite, and its
  own tests, settle the recipes.

## Values

- **`WorkspaceRef(host_id, root, branch)`** names the worktree an op acts on.
  `root` is the absolute worktree path on the host. `branch` is the branch the
  engine checked out there, for example `coral/r-0a1b2c3d4e5f/base`.
- **An executor** says who addresses the op and in what state. The engine
  builds executors from its own slot state, never from request data.
  - `StepSession(session_id, writable, at_turn_end)` is a step session. Both
    flags must be `bool` (`TypeError` otherwise), and `session_id` must not be
    empty.
    - `writable` is false for a reviewer slot.
    - `at_turn_end` means the engine detected a turn end, or the session is a
      new generation not yet briefed (restart ladder step 4). The tree may
      still change afterwards.
  - `HostChannel(host_id)` is the host's workspace-ops channel. It needs no
    session.
- **A backend** is the mechanism that runs git: a session shell, the host
  channel, or a fake. Each backend instance serves one repository binding.
  - The executor decides whether an op may run. The backend decides how it
    runs.
  - WRITE ops have an extra rule about where they run (see "Op-host rule").

## Ops

Every op is async. It takes `(ref, executor, *, params)` and returns a frozen
dataclass from `ops.py`.

| Op | Class | Params | Result | Repeat with the same `op_key` |
| --- | --- | --- | --- | --- |
| `fingerprint` | READ at `L1`, WRITE at `L2` | `level` | `Fingerprint(level, digest, head, dirty_count)` | no `op_key`: L2 writes only content-addressed objects |
| `head` | READ | none | `HeadResult(head, branch, merge_in_progress)` | no `op_key` |
| `diff_stat` | READ | `from_commit`, `to_commit=None` (HEAD) | `DiffStat(files_changed, insertions, deletions, paths)` | no `op_key` |
| `read` | READ | `path`, `at_commit=None` | `ReadResult(path, content, sha256)` | no `op_key` |
| `commit` | WRITE | `op_key`, `expected_head`, `message`, `trailers=None` | `CommitResult(commit, empty)` | returns HEAD when HEAD is the op's verified record |
| `salvage` | WRITE | `op_key` | `SalvageResult(ref, commit)` | returns the commit at `refs/coral/salvage/<op_key>` when it is the op's verified record |
| `reset` | WRITE | `op_key`, `commit` | `ResetResult(head)` | no-op: HEAD is already at `commit` and the tree is clean |
| `merge` | WRITE | `op_key`, `source_ref`, `message` | `MergeResult(status, merge_commit, conflicts)` | `already_applied` |
| `check` | WRITE | `op_key`, `argv`, `timeout_s` | `CheckResult(exit_code, timed_out, stdout_tail, stderr_tail, duration_ms)` | runs again; `op_key` names the job, and the caller records the result in its K21 effect |

The tables below use these names:

- **`<pathspec>`** is `WORKSPACE_PATHSPEC`, `. ':(exclude).coral/runtime/**'`.
  It is used by `add`, `status` and `diff`.
- **`.coral/runtime/`** holds Coral's own files in a worktree. No op records,
  fingerprints, diffs or cleans it.
- **`<id>`** is a commit id checked by `validate_commit_id`. Before any use it
  is resolved as a commit, passed after `--end-of-options` (*Recipe:* `git
  rev-parse --verify --quiet --end-of-options <id>^{commit}`).

## Obligations

Every backend must do the following. The conformance suite tests each item
marked with a test name.

1. **Op-host rule first.** Call `check_op_host(op, executor, level=...)`
   before any validation or I/O. A refused op changes nothing
   (`test_backend_refuses_write_ops_before_changing_anything`). An executor
   that is neither a `StepSession` nor a `HostChannel` raises `TypeError`
   (`test_check_op_host_rejects_an_unknown_executor`).
2. **Strict params.** Validate every param before touching git:
   - commits must be full lowercase hex ids (`validate_commit_id`,
     `test_ops_reject_commit_ids_that_are_not_full_hex`);
   - refs must be full names under `refs/heads/coral/` or `refs/coral/`
     (`validate_coral_ref`,
     `test_merge_rejects_refs_outside_the_coral_namespaces`);
   - op keys (`validate_op_key`,
     `test_write_ops_reject_op_keys_that_cannot_name_a_ref`);
   - trailers (`validate_trailers`,
     `test_commit_rejects_trailers_that_forge_or_break_records`);
   - `commit` and `merge` messages, which must not be blank or contain NUL
     (`validate_commit_message`,
     `test_commit_and_merge_reject_nul_or_blank_messages`);
   - `check` timeouts (`validate_timeout`,
     `test_check_rejects_unbounded_timeouts`);
   - `read` paths (`validate_workspace_path`,
     `test_validate_workspace_path_refuses_paths_outside_the_root`).

   Any failure raises `ValueError`.
3. **Verified target.** Every WRITE op verifies its target first (security
   requirement 4), including that `ref.branch` is under `coral/`. Otherwise it
   raises `workspace.target_mismatch` and changes nothing
   (`test_backend_refuses_write_ops_on_an_unverified_target`). Every op refuses
   an unknown root, or a host channel to another host, the same way
   (`test_backend_refuses_read_ops_on_an_unverified_target`).
4. **`fingerprint`.**
   - **L1** is a sha256 over three inputs:
     1. HEAD;
     2. the output of
        `git status --porcelain=v2 -z --untracked-files=all -- <pathspec>`,
        which is NUL-delimited and has no `--ignored`;
     3. an entry for each dirty path, in sorted order, built from its
        `os.lstat` result. `lstat` never follows a symlink, and the entry
        records the type, size and `mtime_ns`, plus a blob id computed in
        Python:
        - a **regular file** gives the blob id of its bytes, as
          `git hash-object --no-filters` would compute it in the repo's object
          format. The file is opened `O_NOFOLLOW | O_NONBLOCK` and checked with
          `S_ISREG` after `fstat`. Above `MAX_READ_BYTES` it records size and
          `mtime_ns` only.
        - a **symlink** gives the blob id of its link text.
        - **any other type** records its type only.

     Rules for L1:
     - It never passes paths to git as a newline-delimited list, never runs
       filters, and is never computed with a shell `stat`.
     - EVD-01's shared `l1_digest()` (K11, to be added by EVD-01) fixes the byte
       layout. Every backend calls that one function, so digests from
       different backends compare.
     - L1 changes after any edit to a path git reports, including a same-size
       re-edit of a dirty file, and is stable otherwise
       (`test_l1_is_stable_without_edits_and_changes_on_every_edit`). Equal
       digests mean "unchanged" with high probability. Different digests mean
       "changed".
   - **L2** is the git tree id of what `commit` would record now. *Recipe:*
     1. copy the index at `git rev-parse --git-path index` into a fresh
        `mkstemp` file (mode 0600) in an engine-private directory outside the
        worktree, in Python, without following symlinks;
     2. run `GIT_INDEX_FILE=<tmp> git add -A -- <pathspec>`;
     3. run `GIT_INDEX_FILE=<tmp> git write-tree`;
     4. remove the temporary file.

     L2 is equal for equal tree content, whatever HEAD is
     (`test_l2_is_equal_for_equal_tree_content`).
   - Neither level sees ignored files or `.coral/runtime/`
     (`test_fingerprints_skip_ignored_files_and_coral_runtime`).
     `dirty_count` is the number of paths `git status` reports.
   - READ ops never write `.git`. `GIT_ENV` sets `GIT_OPTIONAL_LOCKS=0`, so
     `git status` does not refresh the index under an agent that may be
     running `git add`.
5. **`head`.** `branch` is `None` when HEAD is detached. `merge_in_progress`
   reports a merge that someone else left unfinished. K13's own `merge` never
   leaves one (`test_head_reports_the_branch_and_no_merge_in_progress`).
6. **`diff_stat`.**
   - It counts changed lines per path between `from_commit` and `to_commit`,
     where `to_commit=None` means HEAD. *Recipe:* `git diff --numstat -z
     --no-renames --no-ext-diff --no-textconv <from> <to> -- <pathspec>`; with
     `-z`, paths come back NUL-delimited instead of C-quoted.
   - It compares two commits only, which is why it stays READ.
   - A rename counts as a delete plus an add. A binary file counts 0 lines.
   - `paths` is sorted
     (`test_diff_stat_between_commits_defaults_to_head`).
7. **`read`.**
   - It returns the file's exact bytes: from the working tree when
     `at_commit` is `None`, otherwise the blob at `<at_commit>:<path>`.
     *Recipe:* for a blob, `git cat-file -s` first, then `cat-file blob`.
   - `path` is a relative POSIX path with no empty, `.` or `..` segment,
     checked with `validate_workspace_path`. Anything else raises `ValueError`
     (`test_read_refuses_paths_outside_the_root`).
   - A missing path, a non-regular file, and a file over `MAX_READ_BYTES` all
     raise `workspace.git_failed`
     (`test_read_returns_exact_bytes_at_a_commit_and_in_the_working_tree` for a
     missing path, `test_read_refuses_a_file_over_the_size_cap` for the cap).
8. **`commit`.** This uses the plumbing path; the engine never runs porcelain
   `git commit`. The git commands in the steps below are a *Recipe*. The record
   and HEAD checks, the empty result, the message layout, the identity, and a
   branch move that succeeds only from `expected_head` are normative.
   1. **Record check.** HEAD is the op's record when it carries
      `Coral-Op: <op_key>` and its parent is `expected_head`. Trust is checked
      first; only then are the params compared:
      - a matching `Coral-Op-Params` digest: run `reset -q`, so an index left
        stale by a first try that stopped after `update-ref` is refreshed, then
        return HEAD;
      - a different digest: raise `workspace.op_key_conflict`.

      Any other HEAD is no record, and the op goes on to step 2. The trailers
      are read from HEAD with `trailer.separators=:` pinned
      (`GIT_HARDENING_CONFIG`), so a repository's own separator setting cannot
      hide them
      (`test_commit_repeated_with_its_op_key_returns_the_first_commit`,
      `test_commit_op_key_reused_with_other_params_conflicts`).
   2. **HEAD check.** HEAD must equal `expected_head`, or the op raises
      `workspace.target_mismatch`. That includes a HEAD that carries the key on
      another parent
      (`test_commit_refuses_when_head_is_not_the_expected_head`).
   3. **Stage and compare.** Run `add -A -- <pathspec>` and `write-tree` on a
      temporary index, as L2 does. When the tree equals `HEAD^{tree}`, return
      `CommitResult(commit=<HEAD>, empty=True)` and write nothing
      (`test_commit_with_nothing_to_record_returns_head_as_empty`).
   4. **Commit.** Compose the message in Python, then feed it to `commit-tree
      --no-gpg-sign -p <expected_head>` on stdin; never use `--trailer`.
      - The message is `message`, a blank line, then one trailer block: the
        caller's trailers in order, then `Coral-Op: <op_key>`,
        `Coral-Op-Params: <commit_params_digest>` and `Coral-Hooks: skipped`.
      - **Identity.** Author and committer are the user's `user.name` and
        `user.email`, read from the full config in the pinned repository with
        the default scopes (not `--global`), so the repository's own `user.*`
        and `includeIf` identities apply. They are passed explicitly
        (`GIT_AUTHOR_*` and `GIT_COMMITTER_*`). `Coral <coral@localhost>` is
        used only when they are unset. Users keep their own authorship, and
        the trailers show the commit is the engine's.
   5. **Move the branch.** Run `update-ref refs/heads/<branch> <new>
      <expected_head>`, then `reset -q` to sync the index
      (`test_commit_records_tracked_and_untracked_changes`).
9. **`salvage`.**
   - **Existing ref.** An existing `refs/coral/salvage/<op_key>` counts only
     when its commit's parent is HEAD. Then the op returns it. Otherwise it
     raises
     `workspace.op_key_conflict`
     (`test_salvage_repeated_with_its_op_key_returns_the_first_salvage`,
     `test_salvage_refuses_a_ref_that_is_not_its_record`).
   - **Clean tree** (nothing `commit` would record): it returns `commit=None`
     and writes nothing
     (`test_salvage_of_a_clean_tree_records_nothing`).
   - **Dirty tree:** the op records the tree `commit` would record in a new
     commit on HEAD, and creates the ref only when it is absent. *Recipe:*
     1. Build the tree on a temporary index, as L2 does.
     2. Run `commit-tree --no-gpg-sign -p HEAD`, with the identity of
        obligation 8.4 and `Coral-Hooks: skipped` as the only trailer.
     3. Run `update-ref <ref> <commit> <zero-oid>`, so a racing salvage cannot
        overwrite it.

     HEAD, the index and the working tree stay unchanged
     (`test_salvage_of_a_dirty_tree_keeps_head_and_working_tree`).
10. **`reset`.** *Recipe:*
    1. Run `git reset --hard <id>`. This also clears an unfinished merge.
    2. Run `git clean -fd -e /.coral/runtime/ -- .` (`CLEAN_EXCLUDE`).

    The result:
    - tracked files return to `commit`;
    - untracked files that are not ignored are removed, including any other
      untracked file under `.coral/`;
    - ignored files and untracked files under `.coral/runtime/` stay
      (`test_reset_restores_tracked_files_removes_untracked_and_keeps_ignored`);
    - an unknown commit raises `workspace.git_failed`
      (`test_reset_to_an_unknown_commit_fails`).

    A pathspec exclusion does not work for `clean`: `clean -d` removes a wholly
    untracked `.coral/` before it applies the exclusion. A salvage never
    captures `.coral/runtime/`, so cleaning it would lose it. `reset` is not a
    clean slate for an untrusted attempt (see "Fingerprint blind spots").
11. **`merge`.**
    1. A `source_ref` already contained in HEAD returns `already_applied`, and
       nothing changes
       (`test_merge_of_a_ref_already_in_head_is_already_applied`).
    2. Otherwise a dirty tree raises `workspace.git_failed`. Dirty means a
       `dirty_count` above 0, as for L1. The reason is that aborting a
       conflicted merge can lose uncommitted changes
       (`test_merge_refuses_a_dirty_working_tree`).
    3. Otherwise the backend merges `source_ref` into HEAD, with the identity
       of obligation 8.4. *Recipe:* `git merge --ff --no-edit --no-verify
       --no-gpg-sign -m <message> --end-of-options <source_ref>`.
       - The `-m` message is composed in Python: `message`, a blank line, then
         `Coral-Hooks: skipped`.
       - A fast-forward is allowed and returns `merge_commit=<source commit>`
         (`test_merge_fast_forwards_onto_a_ref_ahead_of_head`).
    4. On a conflict, the backend lists the conflicting paths and aborts the
       merge (*Recipe:* `git merge --abort`). It returns `conflict`, and HEAD
       and the tree are unchanged
       (`test_merge_conflict_reports_paths_and_leaves_head_and_tree`).
12. **`check`.**
    - It runs `argv` as an argument vector, with no shell, in `root`.
    - `argv` comes from user-authored run config, never from agent output.
    - It runs in a sandbox no weaker than the agent's (see "Security
      requirements").
    - A non-zero exit is a result, not an error.
    - An overrun kills the process group and returns `timed_out=True` and
      `exit_code=None`
      (`test_check_reports_exit_codes_and_timeouts_without_raising`).
    - The tails are the last 64 KiB of each stream, decoded as UTF-8 with
      replacement.

## Security requirements

These keep repository content and agents from making engine git run code, act
on the wrong worktree or forge a record. Each is fail-closed.

1. **No hooks or drivers.** Engine git in K13 ops runs no repository hooks:
   neither hookdir hooks nor config-defined `hook.<name>.*` hooks. Before an op,
   a backend runs two read-only config checks (*Recipe:* `git config
   --get-regexp`); reading config runs no program. Either check refuses with
   `workspace.backend_unavailable`:
   - **Hooks**, in the config the op itself runs under (the repository's,
     with `GIT_ENV`): any `hook.*.command`. Global and system hooks need no
     check, because the op runs with that config disabled.
   - **Drivers**, in the user's full config, global and system included: any
     `filter.*` or `merge.*.driver`. Under the isolated config such a driver
     would silently not run, and `add` or `reset` would corrupt the files it
     manages. Git LFS's `filter.lfs.*` in `~/.gitconfig` is the common case.
     This is D-K13-1's interim rule. **For the person deciding D-K13-1:**
     `git lfs install` writes `filter.lfs.*` to `~/.gitconfig` by default, so
     until D-K13-1 is decided, such a user is refused on every repository,
     LFS or not. A narrower fail-closed variant would refuse only when an
     attributes source names `filter=` or `merge=`.

   `trailer.*.cmd`, `diff.*.textconv` and `diff.external` are not refused,
   because no program can run from them: messages are composed in Python, and
   every diff passes `--no-ext-diff --no-textconv`. The backend writes
   `Coral-Hooks: skipped` only after both checks pass. Engine commits take the
   plumbing path in obligation 8.

   **Scope.** This covers the K13 ops only. Creating a run's worktree is not a
   K13 op: Coral currently creates it with Omnigent's worktree create (`git
   worktree add`), which runs the repository's `post-checkout` hook, and its
   `reference-transaction` hook for the new branch, as Omnigent's own session
   worktrees do. A hookless run-worktree create is a follow-up: an S72
   extension that runs the create with `-c core.hooksPath=/dev/null` and
   refuses config-defined hooks, as this requirement does.
2. **Isolated git config.** Every op runs with the "Git defaults" below
   (`GIT_ENV`, `GIT_HARDENING_CONFIG`, `GIT_DIFF_FLAGS`), so global and system
   config are disabled for the op itself.
   - A few settings are read from the full config, in the pinned repository
     with the default scopes; none runs a program:
     - the driver check above;
     - the identity (obligation 8.4);
     - `core.excludesFile`, `core.attributesFile`, `core.autocrlf` and
       `core.eol`.

     The op receives the last four with `-c`, so it ignores and converts
     exactly as the user's git does. Without them, a global
     `core.excludesFile` would be lost: L1, commit and salvage would see the
     files the user's git ignores, and reset would delete them.
   - Backends need git 2.32 or newer (`GIT_CONFIG_GLOBAL`), and refuse an
     older one with `workspace.backend_unavailable`.
   - Git runs by absolute path, resolved by the engine outside the worktree.
     Inherited `GIT_*` variables are dropped, as Omnigent's anchored git
     environment does.
3. **Pinned repository.** Engine git never finds the repository through the
   worktree's `.git` file, which an agent can rewrite.
   - It runs with `GIT_DIR=<common dir>/worktrees/<name>` and
     `GIT_WORK_TREE=<root>`.
   - `<name>` is found from the bound repository's verified worktree list:
     the admin dir whose `gitdir` file names `<root>/.git`.
   - An agent sandbox never gets write access to `.git` or the common dir. A
     sandbox that unmasks `.git` for reads makes it read-only.
4. **Verified target.** Before any WRITE op, the backend checks all of these:
   - `root` is absolute and canonical;
   - `root` is a linked worktree in the bound repository's list, never the
     main worktree;
   - `git rev-parse --show-toplevel` equals `root`;
   - `ref.branch` is under `coral/`, and `symbolic-ref HEAD` is
     `refs/heads/<ref.branch>`;
   - a `HostChannel` executor's `host_id` equals `ref.host_id`.

   Otherwise it raises `workspace.target_mismatch`. READ ops pin `GIT_DIR` the
   same way, and refuse a `root` that is not in the list, or a host channel to
   another host.
5. **Strict refs and commits.** See obligation 2 and the `<id>` rule. Short
   ref names are rejected, because git's short-name lookup finds
   `refs/<name>` and tags first. Refs that differ only in case collide on a
   case-folding filesystem (the macOS default), so K13 never tells refs apart
   by case.
6. **Idempotency record.**
   - The K21 effect record is authoritative.
   - A git-side record counts only when the record commit's parent equals the
     pre-op HEAD stored in the effect (`commit`'s `expected_head`; HEAD for
     `salvage`). The Coral trailers mark it as the engine's.
   - The committer proves nothing: it is the user's identity, and anyone can
     set it. The parent rule and a common dir no agent can write are the real
     controls.
7. **L1 and `read`.**
   - L1: obligation 4.
   - Working-tree `read` opens each path component with `O_NOFOLLOW`. It
     refuses non-regular files and files over `MAX_READ_BYTES` (10 MiB).
   - `read` output is engine-internal. It is never relayed to an agent beyond
     what that agent's sandbox shows.
8. **Transport.**
   - The session-shell backend refuses with `workspace.backend_unavailable`
     unless a probe confirms the session's shell is POSIX.
   - Each caller value appears only as one `shlex.quote`d word, built with
     `shlex.join`. Environment assignments go through an `env NAME=value` argv
     element. NUL is refused in every value.
   - Git output and file bytes travel base64-encoded, with a Coral-generated
     end marker that carries the byte length and sha256.
   - Truncated output is an error, `workspace.git_failed`. It never feeds a
     digest.
9. **`check` sandbox.** It is no weaker than the agent's sandbox:
   - no write to `.git` or the common dir;
   - no network unless the run spec allows it;
   - only the default environment passthrough plus an explicit allowlist;
   - HOME hidden.

   Every backend refuses `check` without a sandbox, with
   `workspace.backend_unavailable`; there is no unsandboxed fallback.
   `timeout_s` is finite, from 1 to `MAX_CHECK_TIMEOUT_S` (7200 s).
10. **Op-host rule.** It is an interlock against racing an agent, not
    authorization. K4 checks ownership, so only the run owner's engine builds
    refs and executors for a host.
11. **Errors.** `WorkspaceOpError` messages can carry worktree paths and git
    stderr. They are for the run owner only. Git stderr is trimmed before it
    reaches logs or the UI.

## Op-host rule

`check_op_host` encodes the rule.

| Class | Ops | May run for |
| --- | --- | --- |
| READ | `fingerprint(level="L1")`, `head`, `diff_stat`, `read` | any step session with `os_env`, or the host channel |
| WRITE | `commit`, `salvage`, `reset`, `merge`, `check`, `fingerprint(level="L2")` | a writable step session at a detected turn end, or the host channel |

- `fingerprint(L2)` is WRITE because `add` and `write-tree` write objects into
  the git common dir.
- `check` is WRITE because repo commands write build output into the tree, so
  a check must not race an agent's turn.

The conformance matrix covers each WRITE op refused for a read-only session and
for a writable session mid-turn, allowed for a writer at turn end and for the
host channel, and every READ op allowed for every executor.

### Why WRITE ops never run inside the agent's sandbox

A linked worktree keeps its index, objects, refs and hooks in the main
repository's `.git`, not in the worktree.

- `git rev-parse --git-path index` gives `<repo>/.git/worktrees/<name>/index`.
- `git rev-parse --git-common-dir` gives `<repo>/.git`.

Spike 8 recorded both. Every WRITE op therefore needs write access to the git
common dir.

A sandbox that grants that access lets the agent plant hooks or config in the
user's main checkout, for example `.git/hooks/pre-commit` or `core.fsmonitor`
in `.git/config`. That code then runs the next time the user runs git. So:

- **WRITE ops run in an engine-owned executor, never inside the agent's
  sandbox.** The `StepSession` executor authorizes the op through its slot and
  turn state. The process that runs the git is the engine's.
- `check` runs in Coral's own sandbox, never in the agent's.

Omnigent's seatbelt and bwrap sandboxes also mask top-level dotfiles in the
session's cwd unless `cwd_allow_hidden` names them. That includes the
worktree's `.git` file. No sandbox grants the common dir.

## Idempotency

- **`op_key`.** WRITE ops take one; READ ops do not.
  - A key is 1-128 lowercase ASCII letters, digits, `_` or `-`, starting with a
    letter or digit (`validate_op_key`). It can name a ref on a case-folding
    filesystem and can be a trailer value.
  - **A key is unique per repository, across all ops and runs.** The engine
    derives it from the run, step, attempt and op. Salvage refs are shared by
    every worktree of a repository, and commit records live in history that
    branches share.
- **Durable records.** A retry, even after an engine restart, finds the first
  result through these. Write ops are serialized per worktree, so a retry
  always lands before any later op on that worktree.

  | Op | Record | How a repeat finds and trusts it |
  | --- | --- | --- |
  | `commit` | HEAD's trailers `Coral-Op: <op_key>` and `Coral-Op-Params: <digest>` | HEAD only; HEAD's parent is `expected_head`, then the digest must match |
  | `salvage` | ref `refs/coral/salvage/<op_key>` | its commit's parent is HEAD |
  | `reset` | postcondition | HEAD already at `commit` with a clean tree: nothing to do |
  | `merge` | postcondition | `source_ref` already an ancestor of HEAD: `already_applied` |
  | `check` | none | not idempotent; the caller records the result in the K21 effect |

- **`workspace.op_key_conflict`.** A backend raises it when a key's record does
  not match the op.
  - For `commit`, that means a different `commit_params_digest(message,
    trailers)`. The digest is a sha256 over canonical JSON of the message and
    the sorted caller trailers. A retry compares digests, never the stored
    message, which git may normalize
    (`test_commit_op_key_reused_with_other_params_conflicts`).
  - For `salvage`, it means a ref that is not the op's record.
  - `reset`, `merge` and `check` keep no record, so their keys cannot conflict.
- **Limits.**
  - An empty commit or a clean salvage records nothing. A later call with the
    same key, on a tree that has changed since, records the change.
  - A commit retried after an intervening reset finds no record on HEAD, and
    commits again: a second commit with the same `Coral-Op`. The K21 effect
    record, which serializes write ops per worktree, keeps that path from
    happening.
  - Reusing a key is not always detected: a commit whose `expected_head` is
    that key's own record commits again.
  - The K21 effect remains the authority for what happened.

## Git defaults

The constants are in `coral/workspace/ops.py`.

| Default | Value | Constant |
| --- | --- | --- |
| Hardening on every engine git call | `-c core.hooksPath=/dev/null -c core.fsmonitor=false -c commit.gpgSign=false -c gc.auto=0 -c trailer.separators=:` | `GIT_HARDENING_CONFIG` |
| Diff flags | `--no-ext-diff --no-textconv` | `GIT_DIFF_FLAGS` |
| Environment | `LC_ALL=C`, `GIT_TERMINAL_PROMPT=0`, `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, `GIT_OPTIONAL_LOCKS=0` | `GIT_ENV` |
| Pathspec for add, status and diff | `. ':(exclude).coral/runtime/**'` | `WORKSPACE_PATHSPEC`, `RUNTIME_DIR` |
| Clean exclusion | `-e /.coral/runtime/` | `CLEAN_EXCLUDE` |
| Identity | author and committer are the user's `user.name`/`user.email` from the full config, passed explicitly; `Coral <coral@localhost>` only when unset | `FALLBACK_IDENTITY_NAME`, `FALLBACK_IDENTITY_EMAIL` |
| Trailers | `Coral-Op`, `Coral-Op-Params` (commit only); `Coral-Hooks: skipped` (every engine commit); every `Coral-*` key is reserved | `OP_TRAILER_KEY`, `OP_PARAMS_TRAILER_KEY`, `HOOKS_TRAILER_KEY`, `HOOKS_TRAILER_VALUE` |
| Refs | full names under `refs/heads/coral/` or `refs/coral/`; salvage under `refs/coral/salvage/` | `CORAL_REF_PREFIXES`, `SALVAGE_REF_PREFIX`, `salvage_ref_name` |
| Limits | `read` ≤ 10 MiB; `check` timeout 1-7200 s | `MAX_READ_BYTES`, `MAX_CHECK_TIMEOUT_S` |

There are no pushes at M2 (OQ-39). The host channel uses argument vectors only.

## Errors

`WorkspaceOpError(code, message)`. The set of codes is additive.

| Code | Raised when |
| --- | --- |
| `workspace.op_host_violation` | `check_op_host` refused the op |
| `workspace.backend_unavailable` | no backend can run the op safely; for example: no host channel, no sandbox for `check`, git older than 2.32, a non-POSIX shell, hooks in the repository config, or drivers anywhere in the user's full config |
| `workspace.git_failed` | git, or the file read behind `read`, failed; this includes an unknown commit or ref, a missing, non-regular or oversized path, truncated transport output, and a merge onto a dirty tree |
| `workspace.timeout` | the backend's own deadline for a git op passed (a `check` overrun is `CheckResult.timed_out` instead) |
| `workspace.op_key_conflict` | an op key's record does not match the op |
| `workspace.target_mismatch` | the target is not verified: unknown root, main worktree, not the toplevel, a branch outside `coral/` or another branch, a host channel to another host, or HEAD is not `expected_head` |

Invalid params raise `ValueError`. Non-`bool` executor flags, and an executor
that is neither a `StepSession` nor a `HostChannel`, raise `TypeError`. The
fake also raises `NotImplementedError` for a merge that git would resolve with
a three-way merge, and `LookupError` for a `check` argv that no test scripted.

## Backend interfaces

Both are `typing.Protocol`s in `ops.py`, implemented later.

- **`SessionShellBackend.run(session_id, command, *, timeout_s) ->
  ShellOutcome(exit_code, stdout, stderr, timed_out)`** (CRL-128, WSP-06).
  - It wraps the session shell route, which is owner-only and takes an integer
    timeout of at least 1 s. `exit_code` is `None` when the command timed out.
  - It follows the transport rules above, and maps a timed-out git op to
    `workspace.timeout`.
- **`HostChannelBackend.request(host_id, op, *, root, params, timeout_s,
  op_key) -> Mapping[str, object]`** (WSP-02).
  - It sends one op over the host workspace-ops channel (S40) and returns its
    payload.
  - `op_key` is `None` for ops that take none.

## M2 backend per op

**Every op's M2 backend is undecided — CRL-128 decides after a linux_bwrap +
Homebrew-git rerun of spike 8.**

| Ops | Constraint |
| --- | --- |
| READ: `fingerprint(L1)`, `head`, `diff_stat`, `read` | In an agent's sandboxed shell they need `GIT_DIR` pinned, with `.git` and the common dir read-only. Whether their results count as evidence is D-K13-2. |
| WRITE: `fingerprint(L2)`, `commit`, `salvage`, `reset`, `merge`, `check` | Engine-owned, never inside the agent sandbox. `check` runs in Coral's own sandbox. |

At restart, `salvage` and `reset` run at ladder step 4, after the old session
is fenced. The new generation's step session (or the host channel) authorizes
them, and git runs in an engine-owned executor, never inside the agent's
sandbox: a sandboxed session shell cannot run them.

The SPK-04 memo declares the spike-8 contingency triggered. Under the roadmap,
host-channel commit, reset and salvage then move into WSP-06.

## Fingerprint blind spots

These are by design. EVD-01 (K11) must treat them as such.

- **Ignored files.** Files matched by `.gitignore` are invisible to L1, L2 and
  commits, including nested `.gitignore` files an agent writes. K11 should
  treat changes to ignore and attribute files as edits.
- **`.coral/runtime/`** is excluded from every op.
- **Nested repositories.** A directory with its own `.git`, which an agent can
  create without git, hides its contents from status. L1 and L2 should report
  or refuse embedded repositories.
- **Reset survivors.** `reset` keeps ignored files and self-ignoring untracked
  directories, so poisoned caches survive a restore. It is not a clean slate
  for an untrusted attempt.

## Open decisions

These are for a person. K13 is not frozen until they are decided.

- **D-K13-1:** run a repo's own filter/merge drivers (e.g. Git LFS) inside
  Coral's own sandbox, or refuse repos that configure them. Until decided,
  backends refuse such repos.
- **D-K13-2:** whether fingerprints taken in an agent's session shell count as
  evidence (EVD-01/EVD-02).
- **D-K13-3:** whether K13 can still tighten for security after the
  real-backend gate. Until decided, K13 stays draft.

## Conformance and change policy

- `tests/coral/workspace/conformance/test_workspace_ops.py` runs the contract
  obligations against every backend in its `BACKENDS` registry.
  - A registry entry is a factory. It takes the pytest `request`, so it can
    pull fixtures such as a live server and runner, and `tmp_path`.
  - The factory returns an async context manager. That manager yields the
    backend, a `WorkspaceRef` holding the suite's initial files at one commit,
    a writable step session at a turn end, and a `WorkspaceSetup`. It tears
    them down afterwards.
  - `WorkspaceSetup` is the backend-specific hook that mutates the working
    tree and prepares refs and check commands: `write_file`, `delete_file`,
    `ignore` (an `info/exclude` line, never a tracked `.gitignore`),
    `add_ref` (full ref names), `add_conflicting_ref` and `check_argv`.
  - CRL-128 adds `"session_shell"` by adding a factory.
- Today the registry holds only `"fake"`. On the fake, the suite pins this text,
  not real git.
- **The same suite passing on a real backend gates CRL-128.** After that, K13
  text changes only additively: new ops, new optional params, new result
  fields with defaults, and new error codes. Security tightening after the gate
  waits on D-K13-3.
- The fake run cannot prove these real-backend obligations. Each backend's own
  tests must cover them:
  - durable records surviving an engine restart, including the parent check
    and record parsing with `trailer.separators=:` pinned;
  - a commit retry that refreshes the index (`reset -q`) before it returns
    HEAD;
  - the hardening flags, the environment and the git version floor;
  - READ ops writing nothing under `.git` (`GIT_OPTIONAL_LOCKS=0`);
  - refusing repositories with repository-config hooks, or with drivers
    defined anywhere, including drivers defined only in global config;
  - the identity read from the full config in the pinned repository, with the
    fallback when it is unset;
  - a global `core.excludesFile`: L1, commit and salvage skip what it ignores,
    and reset keeps it; `core.attributesFile`, `core.autocrlf` and `core.eol`
    convert as the user's git does;
  - the pinned `GIT_DIR` and the main-worktree and toplevel checks;
  - the temporary index;
  - `O_NOFOLLOW` reads and the non-regular-file refusal;
  - POSIX-shell detection, the base64 end marker and the truncation refusal;
  - `check` sandboxing and the `backend_unavailable` refusal;
  - a real `merge --abort`;
  - the `clean` exclusion on a wholly untracked `.coral/`.

## Not in v1

The roadmap's host channel lists more ops: `probe`, `abort_merge`, `branch`,
`fetch` and `push`, exec jobs, and file copy and materialize. It also lists
extra fingerprint fields (`untracked_count`, `duration_ms`). Roadmap WSP-01
lists a K20 draft appendix as part of K13 v1. All of these arrive additively
with WSP-02 and WSP-06, together with the K20 frames.
