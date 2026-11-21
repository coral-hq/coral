import { onlineManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => "alice",
  useIdentityReady: () => true,
}));

import type { RunOutcome } from "../../api/generated/coralApi";
import { jsonResponse } from "../../fixtures/runStreamServer";
import { CONTRACT_OUTCOME } from "../../fixtures/runViewContract";
import { OutcomePanel } from "./OutcomePanel";
import { checkoutHint, ESCAPED_PATH_LABEL, type DiffUnavailable } from "./outcomeText";

const RUN_ID = CONTRACT_OUTCOME.run_id;
const OUTCOME_URL = `/v1/coral/runs/${RUN_ID}/outcome`;
const BRANCH = CONTRACT_OUTCOME.branch!;
const COMMAND = CONTRACT_OUTCOME.checkout.command!;
const WORKTREE_COMMAND = CONTRACT_OUTCOME.checkout.worktree_command!;
const REPO_PATH = CONTRACT_OUTCOME.repo_path!;
const WORKTREE_PATH = CONTRACT_OUTCOME.worktree_path!;

/** The outcome route's answers, in turn; the last one repeats. */
let replies: (() => Response)[];
let writeText: ReturnType<typeof vi.fn>;

const serve = (...answers: (RunOutcome | Response)[]) => {
  replies = answers.map((answer) =>
    answer instanceof Response ? () => answer.clone() : () => jsonResponse(200, answer),
  );
};

/** The recorded outcome with no diff, for `code`. */
function withoutDiff(code: DiffUnavailable, overrides: Partial<RunOutcome> = {}): RunOutcome {
  return {
    ...CONTRACT_OUTCOME,
    head_commit: null,
    diff: null,
    diff_unavailable: code,
    ...overrides,
  };
}

/** The recorded outcome whose paths gave no command: no paths, no commands, the branch only. */
function withoutCommand(unavailable: "unsafe_path" | "non_posix_path"): RunOutcome {
  return {
    ...CONTRACT_OUTCOME,
    repo_path: null,
    worktree_path: null,
    checkout: { command: null, worktree_command: null, unavailable },
  };
}

const outcomeReads = () =>
  authenticatedFetch.mock.calls.filter(([url]) => String(url) === OUTCOME_URL).length;

/** Let fake time pass inside React's act, so queries and effects settle with it. */
const run = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));

function renderPanel() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <OutcomePanel runId={RUN_ID} />
    </QueryClientProvider>,
  );
}

const panel = () => screen.getByRole("region", { name: "Outcome" });
const note = () => screen.getByTestId("run-outcome-note");

beforeEach(() => {
  vi.useFakeTimers();
  serve(CONTRACT_OUTCOME);
  authenticatedFetch.mockImplementation((input: RequestInfo | URL) => {
    if (String(input) !== OUTCOME_URL) return Promise.resolve(jsonResponse(404, {}));
    const reply = replies.length > 1 ? replies.shift()! : replies[0]!;
    return Promise.resolve(reply());
  });
  writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(window.navigator, "clipboard", {
    value: { writeText },
    configurable: true,
  });
});

afterEach(() => {
  cleanup();
  onlineManager.setOnline(true);
  authenticatedFetch.mockReset();
  Reflect.deleteProperty(window.navigator, "clipboard");
  vi.useRealTimers();
});

describe("OutcomePanel", () => {
  it("shows the run's branch, its commits, its diff and the server's commands verbatim", async () => {
    // WHY: what a finished run produced, and how to check it out, without opening a terminal.
    renderPanel();
    await run();
    expect(within(panel()).getByTestId("run-outcome-branch")).toHaveTextContent(BRANCH);
    const commits = within(panel()).getByTestId("run-outcome-commits");
    expect(commits).toHaveTextContent("3f2a9c41d8e7 → 9d8c7b6a5f4e");
    expect(commits).toHaveAttribute(
      "title",
      `${CONTRACT_OUTCOME.diff!.from_commit} → ${CONTRACT_OUTCOME.diff!.to_commit}`,
    );
    expect(within(panel()).getByTestId("run-outcome-summary")).toHaveTextContent(
      "3 files changed, +42 −7",
    );
    expect(screen.getByTestId("run-outcome-checkout-command").textContent).toBe(COMMAND);
    expect(screen.getByTestId("run-outcome-worktree-command").textContent).toBe(WORKTREE_COMMAND);
    expect(screen.getByTestId("run-outcome-hint")).toHaveTextContent(
      checkoutHint(null).replaceAll("`", ""),
    );
    expect(screen.queryByTestId("run-outcome-note")).toBeNull();
    expect(outcomeReads()).toBe(1);
  });

  it("copies exactly the command it shows", async () => {
    // WHY: the copied text must be the server's string, which a real-git test ran.
    renderPanel();
    await run();
    fireEvent.click(screen.getByTestId("run-outcome-checkout-copy"));
    await run();
    fireEvent.click(screen.getByTestId("run-outcome-worktree-copy"));
    await run();
    expect(writeText.mock.calls).toEqual([[COMMAND], [WORKTREE_COMMAND]]);
  });

  it("shows and copies a right-to-left, oddly spaced path's command byte for byte", async () => {
    // WHY: right-to-left folder names are allowed, so no mark or space may be added or lost.
    const command = "git -C '/home/alice/פרויקט  שלי ' checkout --detach refs/heads/" + BRANCH;
    const worktreeCommand = "cd '/home/alice/פרויקט  שלי -worktrees/coral-r-a0ee7440cfc3-base'";
    serve({
      ...CONTRACT_OUTCOME,
      checkout: { command, worktree_command: worktreeCommand, unavailable: null },
    });
    renderPanel();
    await run();
    expect(screen.getByTestId("run-outcome-checkout").textContent).toBe(command);
    expect(screen.getByTestId("run-outcome-worktree").textContent).toBe(worktreeCommand);
    fireEvent.click(screen.getByTestId("run-outcome-checkout-copy"));
    await run();
    fireEvent.click(screen.getByTestId("run-outcome-worktree-copy"));
    await run();
    expect(writeText.mock.calls).toEqual([[command], [worktreeCommand]]);
    // No bidi mark or isolate character is inserted around what is shown.
    expect(panel().textContent).not.toMatch(/[\u200e\u200f\u202a-\u202e\u2066-\u2069]/);
  });

  it.each([
    ["missing", undefined],
    [
      "refusing",
      { writeText: () => Promise.reject(new DOMException("denied", "NotAllowedError")) },
    ],
  ])(
    "never says Copied when the clipboard is %s, and keeps the command to select",
    async (_, clipboard) => {
      // WHY: plain-HTTP origins have no clipboard API; the command must stay readable and whole.
      Object.defineProperty(window.navigator, "clipboard", {
        value: clipboard,
        configurable: true,
      });
      renderPanel();
      await run();
      const copy = screen.getByTestId("run-outcome-checkout-copy");
      fireEvent.click(copy);
      await run();
      expect(copy).toHaveAccessibleName("Copy command");
      expect(screen.getByTestId("run-outcome-checkout-command").textContent).toBe(COMMAND);
    },
  );

  it("renders the commands and paths left to right, isolated from the text around them", async () => {
    // WHY: right-to-left text nearby must not reorder what the owner reads or pastes.
    renderPanel();
    await run();
    for (const testId of ["run-outcome-checkout", "run-outcome-worktree", "run-outcome-paths"]) {
      const element = screen.getByTestId(testId);
      expect(element).toHaveAttribute("dir", "ltr");
      expect(element.className).toContain("[unicode-bidi:isolate]");
    }
    expect(screen.getByTestId("run-outcome-checkout")).toContainElement(
      screen.getByTestId("run-outcome-checkout-command"),
    );
    expect(screen.getByTestId("run-outcome-worktree")).toContainElement(
      screen.getByTestId("run-outcome-worktree-command"),
    );
  });

  it("lists the diff's paths as the server escaped them, and marks the escaped one", async () => {
    // WHY: a bidi override in a file name must show as its code, never reorder the list.
    renderPanel();
    await run();
    const items = within(screen.getByTestId("run-outcome-paths")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(CONTRACT_OUTCOME.diff!.paths);
    expect(items.map((item) => item.dataset.escaped ?? null)).toEqual(["true", null, null]);
    // The mark is seen and announced on the escaped path alone.
    const marks = items.map(
      (item) => within(item).queryByRole("img", { name: ESCAPED_PATH_LABEL }) !== null,
    );
    expect(marks).toEqual([true, false, false]);
    expect(screen.getByTestId("run-outcome-escapes")).toHaveTextContent(
      "Characters that could disguise a path show as \\u{XXXX}.",
    );
    expect(panel().textContent).not.toContain("\u202e");
  });

  it("lists markup, right-to-left and escaped zero-width paths as plain text", async () => {
    // WHY: a file name is text: markup never becomes an element, and nothing is reordered.
    const paths = ["<img src=x onerror=alert(1)>.md", "docs/\\u{200B}hidden.md", "מסמכים/קובץ.md"];
    serve({ ...CONTRACT_OUTCOME, diff: { ...CONTRACT_OUTCOME.diff!, paths } });
    renderPanel();
    await run();
    const items = within(screen.getByTestId("run-outcome-paths")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(paths);
    expect(items.map((item) => item.dataset.escaped ?? null)).toEqual([null, "true", null]);
    expect(panel().querySelector("img")).toBeNull();
  });

  it("lists two paths cut to the same text as two items", async () => {
    // WHY: the server cuts a path at 512 characters, so two long paths can arrive equal.
    const cut = `src/${"deep/".repeat(101)}…`;
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    serve({
      ...CONTRACT_OUTCOME,
      diff: { ...CONTRACT_OUTCOME.diff!, files_changed: 2, paths: [cut, cut] },
    });
    renderPanel();
    await run();
    const items = within(screen.getByTestId("run-outcome-paths")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([cut, cut]);
    expect(errors.mock.calls.flat().join(" ")).not.toContain("the same key");
    errors.mockRestore();
  });

  it("shows the first 20 paths, then how many more", async () => {
    // WHY: a large diff stays readable; its count still covers every file.
    const paths = Array.from({ length: 100 }, (_, index) => `src/f${index}.py`);
    serve({
      ...CONTRACT_OUTCOME,
      diff: { ...CONTRACT_OUTCOME.diff!, files_changed: 130, paths, paths_truncated: true },
    });
    renderPanel();
    await run();
    const items = within(screen.getByTestId("run-outcome-paths")).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual(paths.slice(0, 20));
    expect(screen.getByTestId("run-outcome-more")).toHaveTextContent("and 110 more");
    expect(screen.queryByTestId("run-outcome-escapes")).toBeNull();
  });

  it.each<[DiffUnavailable, string]>([
    [
      "base_unknown",
      "Coral did not record the commit this run started from, so it can’t summarize the run’s changes.",
    ],
    ["host_offline", "Coral can’t reach this run’s host right now."],
    ["worktree_missing", "The run’s worktree or branch is no longer on the host."],
    ["compare_failed", "Coral couldn’t compare the run’s commits."],
    ["failed", "Coral couldn’t read the run’s changes."],
  ])("says why %s left no diff, with no Retry", async (code, text) => {
    // WHY: each reason says what happened; trying again now would not change it.
    serve(withoutDiff(code));
    renderPanel();
    await run();
    expect(note()).toHaveTextContent(text);
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.queryByTestId("run-outcome-summary")).toBeNull();
    // The command still shows: the branch is on the host as far as the server knows.
    expect(screen.getByTestId("run-outcome-checkout-command").textContent).toBe(COMMAND);
  });

  it.each<[DiffUnavailable, string]>([
    ["host_busy", "Another run on this host is running or paused. Retry once it ends."],
    ["busy", "The host is busy; try again in a moment."],
  ])("says %s and reads the outcome again on Retry", async (code, text) => {
    // WHY: the host frees up; Retry gets the summary without a reload.
    serve(withoutDiff(code), CONTRACT_OUTCOME);
    renderPanel();
    await run();
    expect(note()).toHaveTextContent(text);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await run();
    expect(outcomeReads()).toBe(2);
    expect(screen.queryByTestId("run-outcome-note")).toBeNull();
    expect(screen.getByTestId("run-outcome-summary")).toHaveTextContent("3 files changed, +42 −7");
  });

  it.each<[string, RunOutcome | Response]>([
    ["a note's", withoutDiff("host_busy")],
    [
      "a failed load's",
      jsonResponse(403, {
        error: { code: "not_permitted", message: "Not permitted", details: null },
      }),
    ],
  ])("moves focus to the panel's heading when %s Retry brings the outcome", async (_, first) => {
    // WHY: Retry leaves with the note it answered; focus must not drop to the page.
    serve(first, CONTRACT_OUTCOME);
    renderPanel();
    await run();
    const retry = screen.getByRole("button", { name: "Retry" });
    retry.focus();
    fireEvent.click(retry);
    await run();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Outcome" })).toHaveFocus();
  });

  it("keeps focus on Retry when the read brings the same note", async () => {
    // WHY: the person may want to try again; focus stays where they left it.
    serve(withoutDiff("host_busy"));
    renderPanel();
    await run();
    screen.getByRole("button", { name: "Retry" }).focus();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await run();
    expect(outcomeReads()).toBe(2);
    expect(screen.getByRole("button", { name: "Retry" })).toHaveFocus();
  });

  it("holds Retry disabled while its read is in flight, so a double click reads once", async () => {
    // WHY: a second click would abort the first read and send another to a busy host.
    serve(withoutDiff("host_busy"));
    renderPanel();
    await run();
    let release!: (response: Response) => void;
    authenticatedFetch.mockImplementation(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    const retry = screen.getByRole("button", { name: "Retry" });
    fireEvent.click(retry);
    await run();
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    await run();
    expect(outcomeReads()).toBe(2);
    release(jsonResponse(200, CONTRACT_OUTCOME));
    await run();
    expect(screen.getByTestId("run-outcome-summary")).toHaveTextContent("3 files changed, +42 −7");
  });

  it("sends a Retry made offline once the network is back", async () => {
    // WHY: Retry with no network must not fail the panel; the read goes out on reconnect.
    serve(withoutDiff("host_busy"), CONTRACT_OUTCOME);
    renderPanel();
    await run();
    act(() => onlineManager.setOnline(false));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await run(10_000);
    expect(outcomeReads()).toBe(1);
    expect(note()).toHaveTextContent("Another run on this host is running or paused.");
    act(() => onlineManager.setOnline(true));
    await run();
    expect(outcomeReads()).toBe(2);
    expect(screen.getByTestId("run-outcome-summary")).toHaveTextContent("3 files changed, +42 −7");
  });

  it("hedges the checkout hint when the worktree or branch is gone", async () => {
    // WHY: the command fails once the branch is gone; the hint must not promise it works.
    serve(withoutDiff("worktree_missing"));
    renderPanel();
    await run();
    expect(screen.getByTestId("run-outcome-hint").textContent).toMatch(
      /^If the branch still exists, run in sh, bash, zsh or fish\./,
    );
  });

  it("shows only the base when the run never read its head", async () => {
    // WHY: a commit Coral did not read is never shown as the run's head.
    serve(withoutDiff("host_offline"));
    renderPanel();
    await run();
    expect(screen.getByTestId("run-outcome-commits")).toHaveTextContent(/^Base 3f2a9c41d8e7$/);
  });

  it("shows no commits when the run recorded no base", async () => {
    // WHY: base_unknown comes with a null base; no empty or "null" commit is ever shown.
    serve(withoutDiff("base_unknown", { base_commit: null }));
    renderPanel();
    await run();
    expect(note()).toHaveTextContent("Coral did not record the commit this run started from");
    expect(screen.queryByTestId("run-outcome-commits")).toBeNull();
    expect(panel().textContent).not.toContain("null");
    expect(screen.getByTestId("run-outcome-checkout-command").textContent).toBe(COMMAND);
  });

  it.each<["unsafe_path" | "non_posix_path", string]>([
    [
      "unsafe_path",
      `The repository’s path holds characters Coral won’t put in a command. Check out ${BRANCH} yourself.`,
    ],
    ["non_posix_path", `This host’s paths aren’t POSIX. Check out ${BRANCH} yourself.`],
  ])("names the branch and no path for %s", async (code, text) => {
    // WHY: a path that could be misread is never shown, so it cannot be copied.
    serve(withoutCommand(code));
    renderPanel();
    await run();
    expect(screen.getByTestId("run-outcome-checkout-note")).toHaveTextContent(text);
    expect(screen.getByTestId("run-outcome-branch")).toHaveTextContent(BRANCH);
    expect(screen.queryByTestId("run-outcome-checkout")).toBeNull();
    expect(screen.queryByTestId("run-outcome-worktree")).toBeNull();
    expect(screen.queryByTestId("run-outcome-hint")).toBeNull();
    expect(panel().textContent).not.toContain("team");
    expect(panel().textContent).not.toContain("git -C");
  });

  it("says a run with no worktree has nothing to check out", async () => {
    // WHY: an older or damaged run row names no worktree; the panel says so once.
    serve({
      ...withoutDiff("no_worktree"),
      branch: null,
      host_id: null,
      repo_path: null,
      worktree_path: null,
      base_commit: null,
      checkout: { command: null, worktree_command: null, unavailable: "no_worktree" },
    });
    renderPanel();
    await run();
    expect(screen.getByTestId("run-outcome-checkout-note")).toHaveTextContent(
      "This run has no worktree to check out.",
    );
    expect(screen.queryByTestId("run-outcome-note")).toBeNull();
    expect(screen.queryByTestId("run-outcome-branch")).toBeNull();
    expect(screen.queryByTestId("run-outcome-commits")).toBeNull();
  });

  it("never builds a command the server did not send", async () => {
    // WHY: only the server's command is proven by real git; the paths alone make none.
    serve({
      ...CONTRACT_OUTCOME,
      checkout: { command: null, worktree_command: null, unavailable: "no_worktree" },
    });
    renderPanel();
    await run();
    expect(screen.queryByTestId("run-outcome-checkout")).toBeNull();
    expect(screen.queryByTestId("run-outcome-worktree")).toBeNull();
    expect(panel().textContent).not.toContain("git -C");
    expect(panel().textContent).not.toContain(`cd ${WORKTREE_PATH}`);
    expect(panel().textContent).not.toContain(REPO_PATH);
  });

  it("says nothing of the diff for a run the server still sees as unfinished", async () => {
    // WHY: a reply that raced the run's end is not a failure to explain.
    serve(withoutDiff("run_not_finished"));
    renderPanel();
    await run();
    expect(screen.queryByTestId("run-outcome-note")).toBeNull();
    expect(screen.getByTestId("run-outcome-checkout-command").textContent).toBe(COMMAND);
  });

  it("says the outcome is not available yet on a 404, and does not retry it", async () => {
    // WHY: a 404 is final: the run is gone or not the viewer's.
    serve(
      jsonResponse(404, { error: { code: "not_found", message: "Run not found.", details: null } }),
    );
    renderPanel();
    await run(10_000);
    expect(screen.getByTestId("run-outcome-state")).toHaveTextContent("Outcome not available yet");
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    expect(outcomeReads()).toBe(1);
  });

  it("offers Retry when the outcome cannot be read, and recovers", async () => {
    // WHY: a refused read is not the run's outcome; Retry reads it again.
    serve(
      jsonResponse(403, {
        error: { code: "not_permitted", message: "Not permitted", details: null },
      }),
      CONTRACT_OUTCOME,
    );
    renderPanel();
    await run();
    expect(screen.getByTestId("run-outcome-state")).toHaveTextContent(
      "Couldn’t load the run’s outcome.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await run();
    expect(screen.getByTestId("run-outcome-checkout-command").textContent).toBe(COMMAND);
  });

  it("reaches Retry and both copy buttons from the keyboard alone", async () => {
    // WHY: every control in the panel must work without a pointer.
    serve(withoutDiff("host_busy"));
    renderPanel();
    await run();
    // user-event schedules its own timers, which the fake clock would hold.
    vi.useRealTimers();
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByRole("button", { name: "Retry" })).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(outcomeReads()).toBe(2));
    await user.tab();
    expect(screen.getByTestId("run-outcome-checkout-copy")).toHaveFocus();
    await user.keyboard("{Enter}");
    // user-event's setup puts its own clipboard in place of the mock.
    await waitFor(async () => expect(await navigator.clipboard.readText()).toBe(COMMAND));
    // Past the hint's inline `git switch -` copy button.
    await user.tab();
    await user.tab();
    expect(screen.getByTestId("run-outcome-worktree-copy")).toHaveFocus();
    await user.keyboard(" ");
    await waitFor(async () => expect(await navigator.clipboard.readText()).toBe(WORKTREE_COMMAND));
  });

  it("shows a spinner while the outcome loads", async () => {
    // WHY: the panel holds its place while the host is read.
    authenticatedFetch.mockImplementation(() => new Promise(() => {}));
    renderPanel();
    await run();
    expect(
      within(panel()).getByRole("img", { name: "Loading the run’s outcome" }),
    ).toBeInTheDocument();
  });
});
