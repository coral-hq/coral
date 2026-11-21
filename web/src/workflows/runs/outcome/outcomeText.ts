import type { OutcomeCheckout, OutcomeDiff, RunOutcome } from "../../api/generated/coralApi";

// What the outcome panel says: why a finished run has no diff, why it has no checkout
// command, the hint under the command, and the diff's summary. Spans in backticks are code.
// Commands themselves are never written here: the panel shows the server's strings.

/** Why the server sent no diff. */
export type DiffUnavailable = NonNullable<RunOutcome["diff_unavailable"]>;
/** Why the server sent no checkout command. */
export type CheckoutUnavailable = NonNullable<OutcomeCheckout["unavailable"]>;

export interface OutcomeNote {
  text: string;
  /** Reading the outcome again soon can give the diff. */
  retry: boolean;
}

const FAILED: OutcomeNote = { text: "Coral couldn’t read the run’s changes.", retry: false };

/** Each reason's note; `null` where the panel says nothing of the diff. */
export const DIFF_NOTES: Readonly<Record<DiffUnavailable, OutcomeNote | null>> = {
  // The panel shows only finished runs; a reply that raced the end has nothing to explain.
  run_not_finished: null,
  // The checkout note says the run has no worktree.
  no_worktree: null,
  base_unknown: {
    text: "Coral did not record the commit this run started from, so it can’t summarize the run’s changes.",
    retry: false,
  },
  // Paused runs count: they can still act on the host. Nothing reads again on its own.
  host_busy: {
    text: "Another run on this host is running or paused. Retry once it ends.",
    retry: true,
  },
  host_offline: { text: "Coral can’t reach this run’s host right now.", retry: false },
  worktree_missing: {
    text: "The run’s worktree or branch is no longer on the host.",
    retry: false,
  },
  compare_failed: { text: "Coral couldn’t compare the run’s commits.", retry: false },
  busy: { text: "The host is busy; try again in a moment.", retry: true },
  failed: FAILED,
};

/** The note for `code`; a code this client does not know reads as a failed read. */
export function diffNote(code: string | null): OutcomeNote | null {
  if (code === null) return null;
  return Object.hasOwn(DIFF_NOTES, code) ? DIFF_NOTES[code as DiffUnavailable] : FAILED;
}

/** Why there is no command, naming the branch to check out by hand. */
export function checkoutNote(code: string, branch: string | null): string {
  const yourself = `Check out ${branch === null ? "the run’s branch" : `\`${branch}\``} yourself.`;
  switch (code) {
    case "no_worktree":
      return "This run has no worktree to check out.";
    case "unsafe_path":
      return `The repository’s path holds characters Coral won’t put in a command. ${yourself}`;
    case "non_posix_path":
      return `This host’s paths aren’t POSIX. ${yourself}`;
    default:
      return yourself;
  }
}

const HINT_AFTER_RUN =
  "in sh, bash, zsh or fish. It moves your checkout to the run’s last commit (detached HEAD) " +
  "and runs your repository’s hooks; `git switch -` goes back. Or open the run’s worktree:";

/** The hint between the checkout command and the worktree's; hedged when the branch may be gone. */
export function checkoutHint(diffUnavailable: string | null): string {
  return diffUnavailable === "worktree_missing"
    ? `If the branch still exists, run ${HINT_AFTER_RUN}`
    : `Run ${HINT_AFTER_RUN}`;
}

/** "N files changed, +I −D" over the whole diff. */
export function diffSummary(diff: OutcomeDiff): string {
  if (diff.files_changed === 0) return "No files changed";
  const files = diff.files_changed === 1 ? "file" : "files";
  return `${diff.files_changed} ${files} changed, +${diff.insertions} −${diff.deletions}`;
}

/** Paths listed before "and N more". */
export const SHOWN_PATHS = 20;

/** The paths to list, and how many of the diff's files they leave out. */
export function pathsShown(diff: OutcomeDiff): { paths: readonly string[]; more: number } {
  const paths = diff.paths.slice(0, SHOWN_PATHS);
  return { paths, more: Math.max(diff.files_changed, diff.paths.length) - paths.length };
}

/**
 * Whether the server escaped a character of `path`: it shows each backslash, and each
 * unsafe or invisible character, as `\u{XXXX}`, so any backslash starts an escape.
 */
export function holdsEscape(path: string): boolean {
  return path.includes("\\");
}

/** A commit as the panel shows it. */
export function shortCommit(commit: string): string {
  return commit.slice(0, 12);
}

export const ESCAPED_PATHS_TEXT = "Characters that could disguise a path show as \\u{XXXX}.";
/** The accessible name of the mark on a path the server escaped. */
export const ESCAPED_PATH_LABEL = "Holds characters shown as \\u{XXXX}";
export const OUTCOME_NOT_AVAILABLE_TEXT = "Outcome not available yet";
export const OUTCOME_LOAD_FAILED_TEXT = "Couldn’t load the run’s outcome.";
