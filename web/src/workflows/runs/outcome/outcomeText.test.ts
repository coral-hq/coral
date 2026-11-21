import { describe, expect, it } from "vitest";
import type { OutcomeDiff } from "../../api/generated/coralApi";
import { CONTRACT_OUTCOME } from "../../fixtures/runViewContract";
import {
  checkoutHint,
  checkoutNote,
  DIFF_NOTES,
  diffNote,
  diffSummary,
  holdsEscape,
  pathsShown,
  shortCommit,
  SHOWN_PATHS,
  type CheckoutUnavailable,
  type DiffUnavailable,
} from "./outcomeText";

const BRANCH = CONTRACT_OUTCOME.branch!;
const DIFF = CONTRACT_OUTCOME.diff!;

/** Every code of the generated unions; `tsc` fails here when the server adds one. */
const DIFF_CODES = [
  "run_not_finished",
  "no_worktree",
  "base_unknown",
  "host_busy",
  "host_offline",
  "worktree_missing",
  "compare_failed",
  "busy",
  "failed",
] as const satisfies readonly DiffUnavailable[];
const CHECKOUT_CODES = [
  "no_worktree",
  "unsafe_path",
  "non_posix_path",
] as const satisfies readonly CheckoutUnavailable[];
const COVERED: [
  | Exclude<DiffUnavailable, (typeof DIFF_CODES)[number]>
  | Exclude<CheckoutUnavailable, (typeof CHECKOUT_CODES)[number]>,
] extends [never]
  ? true
  : false = true;

const diff = (overrides: Partial<OutcomeDiff>): OutcomeDiff => ({ ...DIFF, ...overrides });
const numbered = (count: number) =>
  Array.from({ length: count }, (_, index) => `src/file${String(index).padStart(3, "0")}.py`);

describe("outcomeText", () => {
  it("names every code the server sends", () => {
    // WHY: the real check is `tsc`: COVERED's type is `false` once a generated union gains a
    // code, so the file no longer compiles. At run time this keeps the table whole.
    expect(COVERED).toBe(true);
    expect(Object.keys(DIFF_NOTES).sort()).toEqual([...DIFF_CODES].sort());
  });

  it.each<[DiffUnavailable, string | null, boolean]>([
    [
      "base_unknown",
      "Coral did not record the commit this run started from, so it can’t summarize the run’s changes.",
      false,
    ],
    ["host_busy", "Another run on this host is running or paused. Retry once it ends.", true],
    ["host_offline", "Coral can’t reach this run’s host right now.", false],
    ["worktree_missing", "The run’s worktree or branch is no longer on the host.", false],
    ["compare_failed", "Coral couldn’t compare the run’s commits.", false],
    ["busy", "The host is busy; try again in a moment.", true],
    ["failed", "Coral couldn’t read the run’s changes.", false],
    // The panel is for finished runs, and the checkout note already says there is no worktree.
    ["run_not_finished", null, false],
    ["no_worktree", null, false],
  ])("says why %s left no diff", (code, text, retry) => {
    // WHY: each reason tells the owner what happened and whether trying again can help.
    const note = diffNote(code);
    expect(note === null ? null : note.text).toBe(text);
    expect(note?.retry ?? false).toBe(retry);
  });

  it("reads a code it does not know as a failed read, with no Retry", () => {
    // WHY: a newer server's code still says the changes could not be read.
    expect(diffNote("solar_flare")).toEqual({
      text: "Coral couldn’t read the run’s changes.",
      retry: false,
    });
    expect(diffNote(null)).toBeNull();
  });

  it.each<[CheckoutUnavailable, string]>([
    [
      "unsafe_path",
      `The repository’s path holds characters Coral won’t put in a command. Check out \`${BRANCH}\` yourself.`,
    ],
    ["non_posix_path", `This host’s paths aren’t POSIX. Check out \`${BRANCH}\` yourself.`],
    ["no_worktree", "This run has no worktree to check out."],
  ])("says why %s has no command", (code, text) => {
    // WHY: without a command the owner still learns the branch to check out by hand.
    expect(checkoutNote(code, BRANCH)).toBe(text);
  });

  it("names no branch it was not given, and reads an unknown code as one to check out by hand", () => {
    // WHY: the note never invents a branch name.
    expect(checkoutNote("unsafe_path", null)).toBe(
      "The repository’s path holds characters Coral won’t put in a command. Check out the run’s branch yourself.",
    );
    expect(checkoutNote("solar_flare", BRANCH)).toBe(`Check out \`${BRANCH}\` yourself.`);
  });

  it("says where the command runs, what it does and how to go back", () => {
    // WHY: the command detaches the main checkout and runs its hooks; the hint says so first.
    expect(checkoutHint(null)).toBe(
      "Run in sh, bash, zsh or fish. It moves your checkout to the run’s last commit (detached " +
        "HEAD) and runs your repository’s hooks; `git switch -` goes back. Or open the run’s worktree:",
    );
    expect(checkoutHint("base_unknown")).toBe(checkoutHint(null));
  });

  it("hedges the hint when the host no longer has the worktree or branch", () => {
    // WHY: the command fails once the branch is gone; the hint must not promise it works.
    expect(checkoutHint("worktree_missing")).toBe(
      "If the branch still exists, run in sh, bash, zsh or fish. It moves your checkout to the " +
        "run’s last commit (detached HEAD) and runs your repository’s hooks; `git switch -` goes " +
        "back. Or open the run’s worktree:",
    );
  });

  it.each<[string, Partial<OutcomeDiff>, string]>([
    ["the recorded diff", {}, "3 files changed, +42 −7"],
    ["one file", { files_changed: 1, insertions: 1, deletions: 0 }, "1 file changed, +1 −0"],
    ["nothing", { files_changed: 0, insertions: 0, deletions: 0, paths: [] }, "No files changed"],
  ])("summarizes %s", (_name, overrides, text) => {
    // WHY: the counts cover the whole diff, whatever the path list holds.
    expect(diffSummary(diff(overrides))).toBe(text);
  });

  it("shows the first 20 paths and counts the rest from the whole diff", () => {
    // WHY: the server sends at most 100 paths; the count covers every changed file.
    const paths = numbered(100);
    expect(SHOWN_PATHS).toBe(20);
    expect(pathsShown(diff({ files_changed: 250, paths, paths_truncated: true }))).toEqual({
      paths: paths.slice(0, 20),
      more: 230,
    });
    expect(pathsShown(diff({ files_changed: 20, paths: numbered(20) }))).toEqual({
      paths: numbered(20),
      more: 0,
    });
    expect(pathsShown(DIFF)).toEqual({ paths: DIFF.paths, more: 0 });
  });

  it("never counts fewer than the paths it was sent", () => {
    // WHY: a host whose count disagrees with its list still gets every listed path counted.
    expect(pathsShown(diff({ files_changed: 3, paths: numbered(25) })).more).toBe(5);
  });

  it("marks a path the server escaped", () => {
    // WHY: the server shows every backslash only as the start of an escape, so one marks it.
    expect(holdsEscape(DIFF.paths[0]!)).toBe(true);
    expect(DIFF.paths[0]).toBe("docs/release\\u{202E}notes.md");
    expect(holdsEscape("src/parser.py")).toBe(false);
  });

  it("shortens a commit to 12 characters", () => {
    // WHY: base and head read at a glance; the full id stays in the panel's title.
    expect(shortCommit(DIFF.from_commit)).toBe("3f2a9c41d8e7");
    expect(shortCommit("abc")).toBe("abc");
  });
});
