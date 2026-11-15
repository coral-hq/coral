# Syncing with Omnigent

Coral keeps Omnigent's full history and merges new Omnigent commits into
`development`, which reaches `main` with the next release. Coral changes
Omnigent's files in two ways, and each one merges differently:

1. **Hand seams.** Small edits marked `CORAL(<seam id>)`, listed in
   `.coral/seams.yaml` and `MODIFICATIONS.md`. They merge like any other edit.
   A conflict means Omnigent changed the same lines; resolve it by hand.
2. **The brand transform (seam S95).** `.coral/tools/rebrand.py` rewrites
   "Omnigent" to "Coral" in user-visible Python strings and in CLI help. The
   rules are in the script, and its tests are in `tests/coral/test_rebrand.py`.
   Hundreds of lines change this way. Coral never merges raw Omnigent code into
   them: each sync first applies the script to the new Omnigent snapshot, so
   both sides of the merge already carry the same rewritten lines.

## The transformed upstream line

`.coral/upstream.yaml` records two commits:

- `merged_sha`: the Omnigent commit Coral is merged up to.
- `transformed_sha`: a commit whose tree is that Omnigent commit after the
  brand transform. Its parents are the previous `transformed_sha` and the
  Omnigent commit, so it records both lines of history.

Each sync adds one transformed commit and merges it into `development`. The merge base
is then the previous transformed commit, so git sees only Omnigent's new
changes, already rewritten.

## Procedure

Run these from Coral's repository root, on a branch off an up-to-date
`development`, and open a pull request into `development`. Merge it with a merge
commit, never squash or rebase: the transformed commit must stay in the history
for the next sync's merge base. The upstream remote is fetch-only: its push URL
is `DISABLED`.

1. Fetch Omnigent and pick the commit to merge:

   ```bash
   git fetch upstream
   UPSTREAM=$(git rev-parse upstream/main)
   PREVIOUS=$(sed -n 's/^transformed_sha: //p' .coral/upstream.yaml)
   ```

2. Build the transformed snapshot in a scratch worktree. Use the script from
   Coral's `development`, so the rules match what it already carries:

   ```bash
   git worktree add --detach ../coral-sync "$UPSTREAM"
   ln -s "$PWD/.venv" ../coral-sync/.venv
   (cd ../coral-sync && .venv/bin/python -I "$OLDPWD/.coral/tools/rebrand.py" apply)
   ```

   `apply` also runs `ruff format` on the files it rewrites, as the commit
   hook would. The transform changes API descriptions, so regenerate the
   committed OpenAPI document too:

   ```bash
   (cd ../coral-sync && PYTHONPATH=. .venv/bin/python scripts/dump_openapi.py)
   ```

   `PYTHONPATH=.` makes Python import the snapshot's `omnigent` package rather
   than the main checkout's, which the editable install points at.

3. Check the snapshot. Run the hooks on the rewritten files, then compare what
   the script keeps against the previous sync:

   ```bash
   cd ../coral-sync
   git add -A
   uv run --no-sync pre-commit run --files $(git diff --cached --name-only)
   .venv/bin/python -I "$OLDPWD/.coral/tools/rebrand.py" report > ../kept.txt
   cd -
   ```

   Read `git -C ../coral-sync diff --cached` for strings that are new since
   the last sync. Some new strings may be contracts rather than prose: a
   marker written to users' files, or text another program parses. Add each
   one to the script's protections, with a test, and repeat from step 2.

4. Record the transformed commit and merge it:

   ```bash
   TREE=$(git -C ../coral-sync write-tree)
   TRANSFORMED=$(git commit-tree "$TREE" -p "$PREVIOUS" -p "$UPSTREAM" \
     -m "CORAL: S95: brand transform of Omnigent ${UPSTREAM:0:9}")
   git merge --no-ff "$TRANSFORMED" -m "CORAL: S95: merge Omnigent ${UPSTREAM:0:9}"
   ```

   Resolve conflicts in hand seams by hand and keep their anchors.
   `README.md` is Coral's own file: keep Coral's version
   (`git checkout --ours README.md`).

5. Confirm the branch is fully rebranded, then update the ledger:

   ```bash
   .venv/bin/python -I .coral/tools/rebrand.py check
   ```

   In `.coral/upstream.yaml`:
   - set `merged_sha` to `$UPSTREAM` and `transformed_sha` to `$TRANSFORMED`;
   - update `merged_at` to the Omnigent commit's date;
   - append the previous pair to `history`.

   Then remove the worktree: `git worktree remove --force ../coral-sync`.

6. Run the tests that cover the merged changes, and commit the ledger update
   with a `CORAL: S95:` message.

## When the rules change

Change the script and its tests on `development` first.

- A rule that rewrites more: run `.venv/bin/python -I .coral/tools/rebrand.py apply`
  on `development` and commit the result with the rule change.
- A rule that rewrites less: `apply` cannot undo earlier rewrites. Rebuild the
  transformed snapshot of the current `merged_sha` with the new script (steps
  2-4, with `PREVIOUS` as the only parent), merge it, and update
  `transformed_sha`. The merge returns those lines to their upstream text.

Either way, the next sync's transformed commit uses the new rules, and its
diff from the previous transformed commit merges cleanly.

## What the transform leaves alone

- the `omnigent` package, imports, identifiers and comments;
- docstrings other than click command help;
- single-word values, header names (`X-Omnigent-*`), paths and file names;
- text about Omnigent itself: omnigent.ai links, install commands, credits, and
  the upstream installer's text;
- text written by code outside its scope (`sdks/`);
- everything outside `omnigent/` and `tests/`, plus the excluded tests listed
  in the script.

Run `rebrand.py report` to list every literal that keeps "Omnigent", with the
reason.
