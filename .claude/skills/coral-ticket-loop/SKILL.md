---
name: coral-ticket-loop
description: >-
  Work the shared Coral Jira board (coralai.atlassian.net, project CRL) one
  ticket at a time: find an unblocked To Do ticket, claim it (In Progress plus a
  claim comment) so no other agent takes it, run coral-pathfind then coral-build
  on a feature branch off development, open one PR into development, merge once
  every check passes, and mark the ticket Done. Use when asked to work Jira
  tickets, pick up the next ticket, or run the ticket loop; repeat it with
  `/loop /coral-ticket-loop`.
---

# Coral ticket loop

People and agents all work from the same Jira board. This is the shared
protocol, so two agents never build the same ticket and nothing merges without
passing checks.

```
1. find an unblocked ticket → 2. claim it (In Progress) → 3. coral-pathfind → coral-build
   on a feature branch → 4. one PR into development → checks pass → merge → ticket Done → 1
```

Run one ticket with `/coral-ticket-loop`. Keep going until the board is empty
with `/loop /coral-ticket-loop`. Each agent works on exactly one ticket at a time.

## Setup (once per machine)

- Atlassian MCP connected with access to `coralai.atlassian.net`:
  `claude mcp add --transport http atlassian https://mcp.atlassian.com/v2/mcp`,
  then sign in from `/mcp`. Tool names vary by install (`mcp__atlassian__*`,
  `mcp__claude_ai_Atlassian__*`, …); use whichever is connected. The site
  hostname works as the `cloudId`.
- `gh` signed in with push access to `coral-hq/coral`.
- `just ensure`, which installs the git hooks.

## Board reference

| What           | Value                                                                                           |
| -------------- | ----------------------------------------------------------------------------------------------- |
| Site / project | `coralai.atlassian.net` / `CRL`                                                                 |
| Statuses       | To Do → In Progress → Done                                                                      |
| Transition IDs | `11` To Do, `21` In Progress, `31` Done (if these fail, look them up by name)                   |
| Blocking       | "Blocks" links. On ticket T, a link with `inwardIssue: X` means T is blocked by X.              |
| Work items     | Tasks and Stories. Epics only group work; never claim one.                                      |
| Source design  | `docs/coral/roadmap/CORAL_ENGINEERING_ROADMAP.md`; ticket descriptions cite its line ranges     |

## 1. Find an available ticket

Search with JQL and request `summary, status, priority, assignee, labels, issuelinks`:

```
project = CRL AND statusCategory = "To Do" AND assignee is EMPTY AND issuetype != Epic
ORDER BY priority DESC, key ASC
```

A ticket is available only when every `Blocks` link with an `inwardIssue` points
at a ticket whose status category is Done. The description's `Blocked by:` line
is a hint; the links are the source of truth. Take the first available ticket.

If nothing is available, report a one-line board summary and stop. Under
`/loop`, check again in about 30 minutes, and end the loop once every non-Epic
ticket is Done.

## 2. Claim it

Jira has no atomic claim, so claim first and then confirm you won:

1. Re-read the ticket. Go back to step 1 if it is no longer To Do, has an
   assignee, or has an unfinished blocker.
2. Transition it to In Progress and assign it to yourself (account ID from the
   Atlassian user-info tool).
3. Comment `coral-ticket-loop claim <claim-id>` with your host and planned
   branch. `<claim-id>` is `<github-user>@<hostname>-<6 random hex>`, so it is
   unique per agent even when one person runs several.
4. A few seconds later, re-read the comments. Among claim comments from the last
   15 minutes that have no later `release <claim-id>` comment, the earliest wins.
   - You won: make sure you are still the assignee (set it again if not).
   - You lost: comment `release <your claim-id>`, leave status and assignee to
     the winner, and go back to step 1.

Never work on a ticket you have not won. Never take over a ticket that is In
Progress, even if it looks idle: its owner may still be working. A person
decides whether a stale ticket goes back to To Do.

## 3. Build it

### Branch and worktree

Use a dedicated worktree, so agents sharing a clone don't switch each other's
branches:

```bash
git fetch origin development
git worktree add -b feat/CRL-124-session-topology ../coral-worktrees/CRL-124 origin/development
cd ../coral-worktrees/CRL-124
```

Name the branch `<type>/<KEY>-<short-slug>` (`feat`, `fix`, `chore`, …). The key
in the name lets Jira link the branch and PR to the ticket.

### Research and design: coral-pathfind

Run `coral-pathfind` with the ticket as the task: its description, scope,
acceptance criteria, the roadmap sections it cites and the pitfalls it lists.
Produce the design doc and the PR-step implementation plan. In this loop:

- Winning the claim is the approval. Run pathfind's final adversarial design
  review, then go straight to coral-build without waiting for a person to
  approve the design.
- Write all pathfind and build working files (`DESIGN.md`, `PR-PLAN.md`,
  `STATUS.md`, `DESIGN-DECISIONS.md`, reports) to `.orchestration/<KEY>/` in the
  worktree. Git ignores dot-directories, so parallel tickets never collide on
  root-level files. Commit only the documents the ticket names as deliverables
  (for example `docs/coral/decisions/ADR-…`).
- Post the design summary and PR-step plan as a ticket comment, so the board
  shows how the ticket is being built.

### Implement: coral-build

Run `coral-build` from `.orchestration/<KEY>/DESIGN.md` and `PR-PLAN.md` until
every plan step is implemented, reviewed and tested. In this loop:

- The git stack is the ticket branch, started from `origin/development`. Each
  plan step lands as one or more commits on it, and the whole ticket ships as
  **one PR**.
- Every acceptance criterion in the ticket must be met, with evidence, before
  the PR opens.
- The repo rules in `AGENTS.md` still apply: proportional checks, no browser
  verification, never `--no-verify`.

## 4. Pull request, merge, Done

1. Push and open one PR into `development`:

   ```bash
   git push -u origin HEAD
   gh pr create --repo coral-hq/coral --base development \
     --title "CORAL: CRL-124: <plain-language summary>"
   ```

   Fill in every section of `.github/pull_request_template.md`. Under Related
   issue, link the Jira ticket (`https://coralai.atlassian.net/browse/CRL-124`)
   in place of `Closes #`. Comment the PR link on the ticket.

2. Wait for checks with `gh pr checks <pr> --repo coral-hq/coral --watch`. Merge
   only when no check is failing or pending (skipped is fine), including checks
   beyond the three the ruleset requires.
   - Failure caused by the change: read the log
     (`gh run view <run> --repo coral-hq/coral --log-failed`), fix it, commit,
     push and watch again.
   - Failure that looks flaky or unrelated: rerun the failed jobs once
     (`gh run rerun <run> --repo coral-hq/coral --failed`). If it fails again,
     escalate instead of merging.
   - Conflicts with `development` because other tickets merged first:
     `git merge origin/development`, resolve, push. Don't force-push.

3. Merge with `gh pr merge <pr> --repo coral-hq/coral --merge --delete-branch`.
4. Transition the ticket to Done and comment with the PR link and merge commit.
5. Remove the worktree (`git worktree remove ../coral-worktrees/<KEY>`) and go
   back to step 1.

## Escalate instead of guessing

Escalate when coral-pathfind or coral-build reaches something it would normally
ask a person about (a design conflict, an ambiguous requirement, a missing
dependency), or when CI keeps failing for a reason you cannot fix:

1. Push what you have and mark the PR as a draft (`gh pr ready <pr> --undo`).
2. Comment on the ticket: what is blocked, the evidence, and the decision needed.
3. Add the `needs-human` label. Leave the ticket In Progress and assigned, so no
   other agent picks it up.
4. Go back to step 1.

## Never

- Work on a ticket without winning its claim, or on two tickets at once.
- Claim an Epic or a ticket with an unfinished blocker.
- Push to `development` or `main` directly, or merge into `main`. Releases are a
  separate flow that people run.
- Merge with failing or pending checks, or bypass the git hooks.
- Mark a ticket Done before its PR has merged.
