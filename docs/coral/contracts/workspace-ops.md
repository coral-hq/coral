# Contract K13: WorkspaceOps (draft v1)

- **Status:** Draft v1 — not frozen; freeze pending D-K13-1..3 (see "Open
  decisions").
  - The text, the code, an in-memory fake and the conformance suite land
    together.
  - The real-backend gate is per op: the suite passes on the host channel
    backend for every op it serves (see "Conformance and change policy").
- **Code:** `coral/workspace/ops.py` (pure tier) holds the op names, types,
  op-host rule, errors, validators, git defaults and backend interfaces.
  `coral/workspace/fake.py` is the fake. `coral/workspace/host_backend.py` is
  the M2 backend over the host channel, and `coral/omni/host/ops/` holds the
  host's handlers. The suite is
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
  git. A backend may use other commands when it gives the same observable
  results and meets every security requirement. The host channel backend ran
  the recipes for the ops it serves; where it departs from one, the text says
  so under *Host recipe*.

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
- **A backend** is the mechanism that runs git: the host channel (Coral's M2
  backend) or a fake. A session-shell backend is described below but not
  built. Each backend instance serves one repository binding.
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
| `diff_stat` | READ | `from_commit`, `to_commit=None` (HEAD) | `DiffStat(files_changed, insertions, deletions, paths, paths_truncated)` | no `op_key` |
| `read` | READ | `path`, `at_commit=None` | `ReadResult(path, content, sha256)` | no `op_key` |
| `commit` | WRITE | `op_key`, `expected_head`, `message`, `trailers=None`, `run_id=None`, `attempt_id=None` | `CommitResult(commit, empty)` | returns HEAD when HEAD is the op's verified record |
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
     `test_commit_rejects_trailers_that_forge_or_break_records`); a value
     holds no C0 control character, ESC (terminal escapes) included
     (`test_commit_rejects_control_characters_in_messages_and_trailers`);
   - `commit`'s `run_id` and `attempt_id`, which take the op-key format
     (`validate_record_id`,
     `test_commit_rejects_record_ids_that_could_break_a_trailer`);
   - `commit` and `merge` messages, which must not be blank or contain a C0
     control character other than a tab or newline, NUL and ESC among them
     (`validate_commit_message`;
     `test_commit_and_merge_reject_nul_or_blank_messages` for commit,
     `test_merge_rejects_nul_or_blank_messages` for merge,
     `test_commit_rejects_control_characters_in_messages_and_trailers`,
     `test_commit_messages_may_contain_tabs`);
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
        `git status --porcelain=v2 -z --untracked-files=all --no-show-stash
        --ignore-submodules=dirty -- <pathspec>`, which is NUL-delimited and
        has no `--ignored`. `--no-show-stash` keeps a repository's
        `status.showStash` out of the digest, and `--ignore-submodules=dirty`
        keeps git out of a submodule's own files (security requirement 2)
        while a moved submodule commit still shows;
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
     - `coral.evidence.fingerprint.l1_digest()` (K11) fixes the byte layout.
       Every real backend calls that one function, so digests from different
       backends compare; the in-memory fake keeps its own model digest.
     - L1 changes after any edit to a path git reports, including a same-size
       re-edit of a dirty file, and is stable otherwise
       (`test_l1_is_stable_without_edits_and_changes_on_every_edit`). Equal
       digests mean "unchanged" with high probability. Different digests mean
       "changed".
   - **L2** is the git tree id of what `commit` would record now. *Recipe:*
     1. copy the index at `git rev-parse --git-path index` into a fresh
        `mkstemp` file (mode 0600) in an engine-private directory outside the
        worktree, in Python, without following symlinks, keeping the
        original's mtime: git trusts an entry's stat data unless the entry is
        as new as the index file, so a newer copy would miss a same-size edit
        made in the second the index was written;
     2. stage what `add -A -- <pathspec>` would, with `GIT_INDEX_FILE=<tmp>`,
        by the status-driven staging of obligation 8.3, never by running
        `git add -A` (it starts `git status` inside every populated
        submodule; security requirement 2);
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
   - A backend may cut `paths` to its longest sorted prefix under a size bound
     and set `paths_truncated`; the counts still cover the whole diff.
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
   - A backend may set a lower cap when its transport needs one. The host
     channel serves at most 6,000,000 bytes, so the base64 content and its
     envelope stay under the channel's 8 MiB result limit; a larger file is a
     permanent `workspace.git_failed`. A file between that cap and
     `MAX_READ_BYTES` therefore reads on the fake but not on the host.
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
      hide them. *Host recipe:* it parses `cat-file commit` itself (parents,
      and the last paragraph's `Key: value` lines), which runs no signature
      program and reads no mailmap
      (`test_commit_repeated_with_its_op_key_returns_the_first_commit`,
      `test_commit_op_key_reused_with_other_params_conflicts`).
   2. **HEAD check.** HEAD must equal `expected_head`, or the op raises
      `workspace.target_mismatch`. That includes a HEAD that carries the key on
      another parent
      (`test_commit_refuses_when_head_is_not_the_expected_head`).
   3. **Stage and compare.** On a temporary index, as L2 does, stage the
      tree `git add -A -- <pathspec>` would record on a copy of the index,
      with one exception: an untracked nested repository that is not already
      a gitlink is left out (`add -A` would record it as a gitlink, or fail
      on one without a commit). Then `write-tree`. When the tree equals
      `HEAD^{tree}`, return `CommitResult(commit=<HEAD>, empty=True)` and write
      nothing (`test_commit_with_nothing_to_record_returns_head_as_empty`).
      - A regular file over 100 MiB is refused with a permanent
        `workspace.git_failed` naming it, before git reads it, so an agent
        cannot copy a huge file into the user's repository.
      - *Recipe* (status-driven staging; `add -A` itself is forbidden, see L2):
        1. Take the paths the L1 status command lists, but only those the
           index still has, or that are untracked: a path deleted from the
           index (`X` = `D`), such as a file the user untracked and ignored,
           comes back only when it is also untracked and not ignored. A `?`
           path ending in `/` (a nested repository) is skipped.
        2. Pass one: `update-index --force-remove -z --stdin` for the paths
           that are gone, or that sit behind a symlink or a non-directory
           component (walked without following symlinks): a directory
           replaced by a file or a symlink.
        3. Pass two: `update-index --add --remove --replace -z --stdin` for
           the rest, so a file may replace a directory and the other way
           round. A submodule whose commit moved is re-read in-process.
   4. **Commit.** Compose the message in Python, then feed it to `commit-tree
      --no-gpg-sign -p <expected_head>` on stdin; never use `--trailer`.
      - The message is `message`, a blank line, then one trailer block: the
        caller's trailers in order, then `Coral-Run: <run_id>` and
        `Coral-Attempt: <attempt_id>` (each only when given),
        `Coral-Op: <op_key>`, `Coral-Op-Params: <commit_params_digest>` and
        `Coral-Hooks: skipped` (`commit_record_trailers`).
      - **Identity.** Author and committer are the user's `user.name` and
        `user.email`, read from the full config in the pinned repository with
        the default scopes (not `--global`), so the repository's own `user.*`
        and `includeIf` identities apply. They are passed explicitly
        (`GIT_AUTHOR_*` and `GIT_COMMITTER_*`). `Coral <coral@localhost>` is
        used only when they are unset. Users keep their own authorship, and
        the trailers show the commit is the engine's.
   5. **Move the branch.** Run `update-ref refs/heads/<branch> <new>
      <expected_head>`, then `reset -q` to sync the index
      (`test_commit_records_tracked_and_untracked_changes`). A branch that
      moved since the HEAD check makes `update-ref` refuse; that is
      `workspace.target_mismatch`, and nothing is overwritten.
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
    1. Run `git reset --hard --no-recurse-submodules <id> --`. This also clears
       an unfinished merge. The `--` keeps a file named like the id from
       making the argument ambiguous.
    2. Run `git clean -fd -e /.coral/runtime/ -- .` (`CLEAN_EXCLUDE`).

    When HEAD is already `id`, the L1 status command prints nothing and no
    merge, cherry-pick or revert is pending, the op writes nothing. Status
    output over the backend's cap counts as "not clean", so the reset goes
    ahead.

    The result:
    - tracked files return to `commit`;
    - untracked files that are not ignored are removed, including any other
      untracked file under `.coral/`; an untracked nested repository stays
      (`clean` needs a second `-f` for one);
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
   a backend runs read-only checks of config and attribute files; reading them
   runs no program. Each check refuses with `workspace.backend_unavailable`,
   `permanent`:
   - **Hooks**, in the config the op itself runs under (the repository's,
     with `GIT_ENV`): any `hook.*.command`. Global and system hooks need no
     check, because the op runs with that config disabled.
   - **Repository-declared filters and drivers** (D-K13-1's interim rule,
     narrowed). Under the isolated config no driver is loaded, so a filter
     the repository names would silently not run, and `add` would record the
     smudged content (for LFS, the real files instead of pointers). The
     backend refuses when:
     - the repository config (read under `GIT_ENV`) sets any `filter.*` or
       `merge.*.driver`, or `attr.tree`;
     - an attribute source the op reads names `filter=` on any line,
       `[attr]` macros included, parsed as git does (lines split on LF,
       tokens on spaces, tabs and CR). The sources are every `.gitattributes`
       in the worktree that git lists (matched case-insensitively; the index
       copy when the worktree copy is missing or a symlink),
       `<common>/info/attributes`, and the attributes file git reads: the
       configured `core.attributesFile`, else the XDG default. The system
       attributes file is off (`GIT_ATTR_NOSYSTEM=1`).

     A global `filter.lfs.*` alone, as `git lfs install` writes it, is
     allowed: the op never loads it, and no repository names it. An ignored
     `.gitattributes` is not scanned (a blind spot, see "Fingerprint blind
     spots").

   `trailer.*.cmd`, `diff.*.textconv` and `diff.external` are not refused,
   because no program can run from them: messages are composed in Python, and
   every diff passes `--no-ext-diff --no-textconv`. The backend writes
   `Coral-Hooks: skipped` only after every check passes. Engine commits take
   the plumbing path in obligation 8.

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
   - **Git never looks inside a submodule or a nested repository.** Their
     config and attributes sit in the agent-writable worktree, so a child git
     started there could run the agent's filters. Status and diff calls pass
     `--ignore-submodules=dirty`, which wins over config and an agent-written
     `.gitmodules`, and nothing passes `--recurse-submodules`. The host
     channel backend adds `-c submodule.recurse=false -c
     status.submoduleSummary=false -c diff.submodule=short -c
     log.showSignature=false` to `GIT_HARDENING_CONFIG` on every call
     (`HOST_HARDENING_CONFIG` in `coral/omni/host/ops/_git.py`).
   - A partial clone never fetches: every call sets `GIT_NO_LAZY_FETCH=1`, and
     with git older than 2.44, which ignores it, a partial clone is refused.
3. **Pinned repository.** Engine git never finds the repository through the
   worktree's `.git` file, which an agent can rewrite.
   - It runs with `GIT_DIR=<common dir>/worktrees/<name>` and
     `GIT_WORK_TREE=<root>`.
   - `<name>` is found from the bound repository's verified worktree list:
     the admin dir whose `gitdir` file names `<root>/.git`.
   - An agent sandbox never gets write access to `.git` or the common dir. A
     sandbox that unmasks `.git` for reads makes it read-only.
   - A pinned `GIT_DIR` skips git's own `safe.directory` check, so the backend
     checks ownership itself: the worktree root, the common dir and the admin
     dir belong to the user the engine's git runs as. The admin dir's
     `commondir` file must lead back to the bound repository's common dir.
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
     refuses non-regular files and files over `MAX_READ_BYTES` (10 MiB; the
     host channel's cap is 6,000,000 bytes, obligation 7). The host also
     refuses a path with a `.git` segment in any spelling a file system would
     open as `.git`.
   - `read` output is engine-internal. It is never relayed to an agent beyond
     what that agent's sandbox shows.
8. **Transport.**
   - **Host channel** (built): argument vectors only, never a shell; values
     travel as JSON in the K20 frames (appendix). The host re-validates every
     param and refuses a non-POSIX host with a permanent
     `workspace.backend_unavailable`.
   - **Session shell** (described, not built: CRL-128 chose the host channel).
     The rules below stay for a future session-shell backend.
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
12. **Write jail.** An agent process can outlive its session (on macOS a
    double-forked `setsid` process survives the session's teardown). While a
    host op runs, it can swap a directory of the worktree for a symlink, and
    git, which resolves paths again on every open, would then write, delete
    or read through it. So every git process the backend starts runs in a
    jail the kernel enforces:
    - **Writes.** A WRITE op's git may write only the worktree; in the common
      dir `objects/`, `refs/heads/coral/`, `refs/coral/`, their `logs/`
      counterparts, and `packed-refs` and its lock; the worktree's own admin
      dir `worktrees/<name>/`; the op's private temp dir; and `/dev/null`.
      Never `hooks/`, `config`, `info/` or other refs. A READ op's git may
      write only the temp dir and `/dev/null`. A WRITE op runs its
      repository refusal checks (hooks, filters and drivers, sparse checkout,
      reftable and the rest) read-only, in the READ op's jail, before its
      write jail is built. A repository whose refs live in a reftable is
      refused for WRITE ops (`backend_unavailable`, permanent): its refs are
      one table, not files the jail can open one by one. The host creates a
      missing ref directory the jail opens only inside a real directory; a
      file or symlink in its place is refused the same way.
    - **Reads.** Under the user's home directory git may read file data only
      of those paths, the repository, git's own install (when it is under the
      home directory: its directory and its exec path), the repository's
      config files and their includes, and exactly the global ignore and
      attribute files git consults (the configured `core.excludesFile` and
      `core.attributesFile`, else the XDG `git/ignore` and `git/attributes`).
      Never `~/.gitconfig`, the system config (the ops run with them off) or
      the rest of `~/.config/git`, which can hold the credential store.
      Directories above the readable paths stay listable, which `getcwd()`
      needs. Reads outside the home directory are not limited.
    - The jail never swallows git's exit code, and the deadline's group
      kill reaches git.
    - Without a working jail, WRITE ops refuse with a permanent
      `workspace.capability_unavailable` naming the missing tool; READ ops,
      which write nothing, run unjailed. Without a home directory (`$HOME`
      unset or `/`), WRITE ops refuse with a permanent
      `workspace.backend_unavailable`. The jail tool, like git, must sit
      outside the op's worktree and repository (compared by device and
      inode) before it first runs.

    The host channel uses `sandbox-exec` on macOS and `bwrap` on Linux
    (`coral/omni/host/ops/_jail.py`). On Linux the home directory is an
    empty tmpfs with the readable paths bound back; a symlinked one (a
    dotfile manager's `~/.gitignore_global`) is bound at both its spelling
    and its target, so global ignore rules still apply. Only with the jail
    does a host op touch no path outside the worktree, the common-dir paths
    above and its temp dir.
13. **Move-aside (macOS).** The jail cannot keep a racer out of the paths
    git must write, the worktree and the coral refs among them. On macOS
    an agent's surviving process is confined by its seatbelt profile, which
    grants writes by path. So every WRITE op renames the worktree to the
    sibling `<worktree>.coral-op` (in `<repo>-worktrees/`, which no agent
    can write) before its git runs, runs git there with the pinned
    `GIT_DIR`/`GIT_WORK_TREE`, and renames it back in `finally`. Such a
    process can then write nothing in the tree, not through its cwd and not
    through a directory fd it held. It holds under the worktree lock, which
    follows the moved tree.
    - An aside copy found when an op starts (a host that died mid-op) is
      moved back first, replacing an empty directory at the worktree path
      (all a surviving process can make there). If a non-empty directory, a
      file or a symlink is there, the op fails with a permanent
      `workspace.worktree_displaced` naming both; a person keeps the one with
      the work. The same applies when the tree moves back after an op. While
      an aside copy exists, the worktree lock is keyed on it.
    - Trade-off: other live sessions with that worktree as their cwd (read-only
      reviewers) see it vanish while the op runs. M2 has one writer, and the
      close stops the writer first. A `git worktree prune` run by the user
      during the op could prune the worktree's admin dir.
    - Linux needs no move-aside: agents run under bwrap with a PID
      namespace, so no agent process outlives the stop.
14. **What CI must prove on Linux.** Neither the jail nor its tests have run
    on a Linux host during CRL-128. CI must show:
    - bwrap starts with `--ro-bind / /` on the runner;
    - git's exit codes (1 and 128) pass through bwrap, and the deadline's
      group kill leaves no process behind;
    - the jail tests and the race tests in `tests/coral/omni/host/ops/`
      actually run: under `CI` they fail instead of skipping when no jail
      works;
    - a symlinked global excludes file still applies inside the jail;
    - a `hash-object` of a home file is refused;
    - that the agents' own bwrap PID namespace really kills a `setsid`
      daemon at the stop (move-aside's Linux premise):
      `tests/coral/omni/host/ops/test_agent_sandbox_linux.py`, which also
      fails under `CI` when bwrap cannot run.

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
    trailers, run_id=, attempt_id=)`. The digest is a sha256 over canonical
    JSON of the message and the sorted caller trailers; the run and attempt
    ids join it only when either is set, so a commit without them keeps its
    earlier digest. A retry compares digests, never the stored message, which
    git may normalize (`test_commit_op_key_reused_with_other_params_conflicts`,
    `test_commit_record_includes_its_run_and_attempt_ids`).
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
| Trailers | `Coral-Run`, `Coral-Attempt` (commit only, when given); `Coral-Op`, `Coral-Op-Params` (commit only); `Coral-Hooks: skipped` (every engine commit); every `Coral-*` key is reserved | `RUN_TRAILER_KEY`, `ATTEMPT_TRAILER_KEY`, `OP_TRAILER_KEY`, `OP_PARAMS_TRAILER_KEY`, `HOOKS_TRAILER_KEY`, `HOOKS_TRAILER_VALUE`, `commit_record_trailers` |
| Refs | full names under `refs/heads/coral/` or `refs/coral/`; salvage under `refs/coral/salvage/` | `CORAL_REF_PREFIXES`, `SALVAGE_REF_PREFIX`, `salvage_ref_name` |
| Limits | `read` ≤ 10 MiB (host channel: 6,000,000 bytes); a staged file ≤ 100 MiB (host channel); `check` timeout 1-7200 s | `MAX_READ_BYTES`, `MAX_CHECK_TIMEOUT_S`, `MAX_STAGED_FILE_BYTES` (`coral/omni/host/ops/_write_ops.py`) |

There are no pushes at M2 (OQ-39). The host channel uses argument vectors only.
Security requirement 2 lists what the host channel backend adds to these
defaults.

## Errors

`WorkspaceOpError(code, message, *, permanent=False)`. The set of codes is
additive. `permanent` marks a condition a retry cannot fix: a repository with
hooks, declared filters or a sparse checkout, git older than 2.32, a
non-POSIX host, a host that cannot serve the op. `False` leaves the decision
to the code: an offline host may be back later.

| Code | Raised when |
| --- | --- |
| `workspace.op_host_violation` | `check_op_host` refused the op |
| `workspace.backend_unavailable` | no backend can run the op safely; for example: the host is offline, the tunnel dropped or the host's temp dir is full (retryable), no sandbox for `check`, git older than 2.32, a non-POSIX host, hooks, repository-declared filters or drivers, a sparse checkout, a reftable ref store or no home directory for a WRITE op, a jail tool inside the worktree, or a malformed host reply (each permanent) |
| `workspace.worktree_displaced` | the worktree and its aside copy (`<worktree>.coral-op`, security requirement 13) both exist, or the worktree cannot move back; always permanent: a person decides which copy holds the work |
| `workspace.capability_unavailable` | the backend does not serve the op at all, always permanent: `fingerprint(L2)`, `merge` and `check` on the host channel at M2, a host too old for the channel or with Coral's handlers switched off, or a WRITE op on a host without a working write jail |
| `workspace.git_failed` | git, or the file read behind `read`, failed; this includes an unknown commit or ref, a missing, non-regular or oversized path, a file over the 100 MiB staging limit (permanent), truncated transport output, and a merge onto a dirty tree |
| `workspace.timeout` | the backend's own deadline for a git op passed (a `check` overrun is `CheckResult.timed_out` instead); on the host channel also another git process holding a lock past the lock budget, or another op still running on the worktree; always retryable |
| `workspace.op_key_conflict` | an op key's record does not match the op |
| `workspace.target_mismatch` | the target is not verified: unknown root, main worktree, not the toplevel, a branch outside `coral/` or another branch, a host channel to another host, or HEAD is not `expected_head` (also when the branch moves while a commit is written) |

Invalid params raise `ValueError`, including those the host itself catches
(`workspace.invalid_params` on the wire). Non-`bool` executor flags, and an executor
that is neither a `StepSession` nor a `HostChannel`, raise `TypeError`. The
fake also raises `NotImplementedError` for a merge that git would resolve with
a three-way merge, and `LookupError` for a `check` argv that no test scripted.

## Backend interfaces

Both are `typing.Protocol`s in `ops.py`.

- **`SessionShellBackend.run(session_id, command, *, timeout_s) ->
  ShellOutcome(exit_code, stdout, stderr, timed_out)`**: described, not built.
  CRL-128 chose the host channel, so nothing implements this.
  - It wraps the session shell route, which is owner-only and takes an integer
    timeout of at least 1 s. `exit_code` is `None` when the command timed out.
  - It follows the transport rules above, and maps a timed-out git op to
    `workspace.timeout`.
- **`HostChannelBackend.request(host_id, op, *, root, params, timeout_s,
  op_key) -> Mapping[str, object]`** (CRL-128; WSP-02 extends it).
  - It sends one op over the host workspace-ops channel (S40) and returns its
    payload. Failures raise the K13 error that
    `coral.workspace.host_backend.map_host_reply` maps the host's reply to.
  - `op_key` is `None` for ops that take none.
  - `HostWorkspaceOps` (`coral/workspace/host_backend.py`) is the K13 backend
    over it. It sends `params` with the bound repository's `repo_root` and
    the ref's `branch` added, waits 120 s for READ ops and 600 s for WRITE
    ops, and parses each payload strictly (a malformed one is a permanent
    `workspace.backend_unavailable`).

## M2 backend per op

CRL-128 decided: engine git runs on the user's host, through the host
workspace-op channel, never in an agent's sandbox. The session-shell backend
is not built (SPK-04's CRL-128 decision record).

| Ops | M2 backend |
| --- | --- |
| READ: `head`, `diff_stat`, `read`, `fingerprint(L1)` | host channel |
| WRITE: `commit`, `salvage`, `reset` | host channel |
| `fingerprint(L2)` | not served at M2: `workspace.capability_unavailable` (WSP-02) |
| `merge` | not served at M2: `workspace.capability_unavailable` (WSP-03) |
| `check` | not served at M2: `workspace.capability_unavailable` (EVD-04; Coral's own sandbox) |

- The host serves READ ops too: in a default agent sandbox `.git` is masked,
  so a session shell could not run them, and D-K13-2 is still open.
- At restart, `salvage` and `reset` run at ladder step 4, after the old
  session is fenced, through a `HostChannel` executor.
- A host that does not advertise `workspace_ops:1`, or whose Coral handlers
  are switched off (`CORAL_DISABLE_HOST_ENTRY_POINTS`), answers every op with
  a permanent `workspace.capability_unavailable`; it never makes a silent
  empty commit.
- **Host limits.** At most 2 ops run at once per host, and one per worktree:
  an op on a busy worktree fails at once with a retryable
  `workspace.timeout`. A write retries while another git process holds an
  `index.lock` or ref lock, for at most 30 s or the op's deadline, then fails
  with a retryable `workspace.timeout` naming the lock; the lock is never
  removed. A timed-out git gets SIGTERM and up to 2 s for its whole process
  group to exit (under bwrap, git is the jail's child), then SIGKILL, so it
  can remove its own locks. Only POSIX hosts are served.
- **Stalls.** Git opens some files with a blocking `open()`, so a FIFO an
  agent plants as a `.gitignore` or as a nested repository's or submodule's
  `.git/HEAD` stalls it. The attributes listing every op runs, and the
  status a WRITE op runs, each give up after 30 s with a retryable
  `workspace.timeout`; any other call (L1's status included) can stall until
  the op's deadline. Either way the worktree holds at most one of the host's
  two op slots.
- **Leftovers.** A git killed while it hashes a large file leaves a
  `tmp_pack_*` file in the user's `objects/pack/`. The engine never deletes
  it (it may belong to another git); `git gc` prunes it after two weeks. The
  100 MiB staging limit bounds each one.

## Fingerprint blind spots

These are by design. EVD-01 (K11) must treat them as such.

- **Ignored files.** Files matched by `.gitignore` are invisible to L1, L2 and
  commits, including nested `.gitignore` files an agent writes. K11 should
  treat changes to ignore and attribute files as edits.
- **`.coral/runtime/`** is excluded from every op.
- **Nested repositories.** A directory with its own `.git`, which an agent can
  create without git, hides its contents from status. L1 records it as one
  `directory` entry; `commit` and `salvage` leave it out (obligation 8.3);
  `reset` keeps it.
- **Reset survivors.** `reset` keeps ignored files, self-ignoring untracked
  directories and nested repositories, so poisoned caches survive a restore.
  It is not a clean slate for an untrusted attempt.
- **Ignored attribute files.** An ignored `.gitattributes` is not scanned for
  `filter=` (security requirement 1); with no driver loaded, nothing runs
  from it.

## Open decisions

These are for a person. K13 is not frozen until they are decided.

- **D-K13-1:** run a repo's own filter/merge drivers (e.g. Git LFS) inside
  Coral's own sandbox, or refuse repos that configure them. Until decided,
  backends refuse repositories that declare them (security requirement 1,
  narrowed in CRL-128 so that a global LFS install alone is allowed).
- **D-K13-2:** whether fingerprints taken in an agent's session shell count as
  evidence (EVD-01/EVD-02).
- **D-K13-3:** whether K13 can still tighten for security after the
  real-backend gate. Until decided, K13 stays draft.

## Conformance and change policy

- `tests/coral/workspace/conformance/test_workspace_ops.py` runs the contract
  obligations against every backend in its `BACKENDS` registry.
  - A registry entry is a `BackendEntry(factory, supported_ops)`. The factory
    takes the pytest `request`, so it can pull fixtures such as a live server
    and runner, and `tmp_path`.
  - **The gate is per op.** `supported_ops` names the ops the backend serves,
    with `fingerprint` counted per level (`fingerprint-L1`,
    `fingerprint-L2`). A test of an op the backend does not serve calls
    `_require` and skips with "<op> is not served by this backend (K13
    per-op gate)"; an op-parametrized test does so per parameter.
  - The factory returns an async context manager. That manager yields the
    backend, a `WorkspaceRef` holding the suite's initial files at one commit,
    a writable step session at a turn end, and a `WorkspaceSetup`. It tears
    them down afterwards.
  - `WorkspaceSetup` is the backend-specific hook that mutates the working
    tree and prepares refs and check commands: `write_file`, `delete_file`,
    `ignore` (an `info/exclude` line, never a tracked `.gitignore`),
    `add_ref` (full ref names), `add_conflicting_ref` and `check_argv`.
- The registry holds `"fake"`, which serves every op and pins this text, and
  `"host"`, the real backend: `HostWorkspaceOps` over an in-process host
  channel that sends each op through the channel's real frame codec and
  dispatcher to Coral's host handlers, on real git in `tmp_path`, and maps
  replies with `map_host_reply` as the server does.
- **The suite passing on the `host` entry, for the seven ops it serves, is
  CRL-128's real-backend gate.** After that, K13 text changes only
  additively: new ops, new optional params, new result fields with defaults,
  and new error codes. Security tightening after the gate waits on D-K13-3.
- The fake run cannot prove these real-backend obligations. Each backend's own
  tests must cover them (for the host channel:
  `tests/coral/omni/host/ops/`):
  - durable records surviving an engine restart, including the parent check
    and record parsing with `trailer.separators=:` pinned;
  - a commit retry that refreshes the index (`reset -q`) before it returns
    HEAD;
  - the hardening flags, the environment and the git version floor;
  - READ ops writing nothing under `.git` (`GIT_OPTIONAL_LOCKS=0`);
  - no git started inside a submodule or nested repository, and no nested
    repository recorded by `commit` or `salvage`;
  - the write jail: git cannot write, delete or read through a symlinked
    directory in the worktree, even one an agent process swaps in during the
    op, and WRITE ops refuse without a working jail;
  - the staged tree equal to `add -A`'s on a copy of the index, directory
    and file swaps and a deliberately untracked, ignored file included;
  - lock contention: a held lock retried within the budget, then a retryable
    `workspace.timeout` with the lock left in place;
  - refusing repositories with repository-config hooks or repository-declared
    filters or drivers, while a global filter definition alone is allowed;
  - the identity read from the full config in the pinned repository, with the
    fallback when it is unset;
  - a global `core.excludesFile`: L1, commit and salvage skip what it ignores,
    and reset keeps it; `core.attributesFile`, `core.autocrlf` and `core.eol`
    convert as the user's git does;
  - the pinned `GIT_DIR` and the main-worktree and toplevel checks;
  - the temporary index, which keeps the real index byte-identical and its
    racily-clean entries visible;
  - `O_NOFOLLOW` reads and the non-regular-file refusal;
  - for a session-shell backend: POSIX-shell detection, the base64 end marker
    and the truncation refusal;
  - `check` sandboxing and the `backend_unavailable` refusal;
  - a real `merge --abort`;
  - the `clean` exclusion on a wholly untracked `.coral/`.

## Not in v1

The roadmap's host channel lists more ops: `probe`, `abort_merge`, `branch`,
`fetch` and `push`, exec jobs, and file copy and materialize. It also lists
extra fingerprint fields (`untracked_count`, `duration_ms`), and K20's job
events, journal and `job.status`. All of these arrive additively with WSP-02
and WSP-06. The minimal K20 frames CRL-128 needs are below.

## Appendix: K20 draft (minimal)

The host workspace-op channel as CRL-128 built it (seams S40 and S40b; code in
`omnigent/host/workspace_ops.py` and `omnigent/server/routes/_host_workspace_ops.py`).
WSP-02 extends it.

- **Capability.** A host advertises `workspace_ops:1` in its hello. The server
  never sends a frame to a host without it. The token is a capability, not
  authorization: the server authorizes the host for the run owner first and
  sends inside that owner's host scope.
- **Request** `host.workspace_op`: `request_id` (32 hex), `op`, `root`
  (canonical absolute), `params` (a JSON object; every op carries `repo_root`
  and `branch`), `timeout_s` and `op_key` (K13 format, or `null`). A
  `timeout_s` outside `(0, 900]` is rejected before sending, never clamped.

  ```json
  {"kind": "host.workspace_op", "request_id": "<32 hex>", "op": "commit",
   "root": "/Users/a/repo-worktrees/coral-r-0a1b2c3d4e5f-base",
   "params": {"repo_root": "/Users/a/repo", "branch": "coral/r-0a1b2c3d4e5f/base",
              "expected_head": "<40|64 hex>", "message": "Review: done",
              "trailers": [["Reviewed-By", "x"]], "run_id": "<id>", "attempt_id": "<id>"},
   "timeout_s": 600, "op_key": "<op key>"}
  ```

- **Result** `host.workspace_op_result`: `request_id`, `status` (`ok` with a
  `payload` object, or `failed` with an `error_code`), `error` (at most 2,000
  characters), `exit_code` and `permanent` (absent reads `false`).

  ```json
  {"kind": "host.workspace_op_result", "request_id": "<32 hex>", "status": "failed",
   "payload": null, "error_code": "workspace.backend_unavailable",
   "error": "docs/.gitattributes declares a filter; …", "exit_code": null, "permanent": true}
  ```

- **Params and payloads per op.**

  | Op | Params besides `repo_root`, `branch` | Payload |
  | --- | --- | --- |
  | `head` | none | `{head, branch\|null, merge_in_progress}` |
  | `diff_stat` | `from_commit`, `to_commit\|null` | `{files_changed, insertions, deletions, paths, paths_truncated}`; a list that would take the payload over 4 MiB of JSON is cut, never failed (`paths_truncated` absent reads `false`) |
  | `read` | `path`, `at_commit\|null` | `{path, content_b64, sha256}` |
  | `fingerprint` | `level` (`"L1"` only) | `{level, digest, head, dirty_count}` |
  | `commit` | `expected_head`, `message`, `trailers` (`[[key, value], …]`), `run_id\|null`, `attempt_id\|null`; `op_key` | `{commit, empty}` |
  | `salvage` | none; `op_key` | `{ref, commit\|null}` |
  | `reset` | `commit`; `op_key` | `{head}` |

- **Failure codes.** Frame level: `unknown_op` (no handler: the engine reads
  it as `workspace.capability_unavailable`), `invalid_request`,
  `handler_failed`, `invalid_payload`, `result_too_large` (all read as a
  permanent `workspace.backend_unavailable`). Handler level: the K13
  `workspace.*` codes with their `permanent` flag, plus
  `workspace.invalid_params`, which the engine raises as `ValueError`. The
  engine reads `workspace.capability_unavailable` and
  `workspace.worktree_displaced` as permanent and `workspace.timeout` as
  retryable, whatever the flag says.
- **Limits.** Results at most 8 MiB serialised; at most 2 ops at once per
  host, one per worktree; the server waits `timeout_s` plus 15 s. A timeout or
  dropped tunnel leaves the outcome unknown: callers retry with the same
  `op_key`.
- **Handlers** come from `omnigent.host_workspace_ops` entry points, loaded on
  the first op frame; an op offered by two packages is served by neither.
  Coral's `coral = coral.omni.host.ops:workspace_op_handlers` serves the seven
  ops above, and none while `CORAL_DISABLE_HOST_ENTRY_POINTS` is set.
