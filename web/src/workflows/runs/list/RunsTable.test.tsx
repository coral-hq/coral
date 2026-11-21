import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";
import { APP_QUERY_DEFAULTS } from "@/lib/queryRetry";
import { formatRunTimestamp } from "@/lib/scheduleText";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => "alice",
  useIdentityReady: () => true,
}));

import type { RunPage, RunSpend, RunSummary } from "../../api/generated/coralApi";
import { jsonResponse } from "../../fixtures/runStreamServer";
import { ACTIVE_POLL_MS, PAUSED_POLL_MS, RunsTable, SPEND_FILL_MS, runsPollMs } from "./RunsTable";

const WORKFLOW_ID = "0123456789abcdef0123456789abcdef";
const OTHER_WORKFLOW_ID = "fedcba9876543210fedcba9876543210";
const NOW_S = 1_767_268_000;

const WORKFLOWS = [
  {
    id: WORKFLOW_ID,
    workflow_key: "ship",
    name: "Ship a change",
    content_hash: "h",
    runnable: true,
    created_at: 1,
    updated_at: 1,
  },
  {
    id: OTHER_WORKFLOW_ID,
    workflow_key: "review",
    name: "Review PRs",
    content_hash: "h",
    runnable: true,
    created_at: 1,
    updated_at: 1,
  },
];

const SPEND: RunSpend = {
  as_of: NOW_S,
  estimate: true,
  live_usd: 1.31,
  sessions: 3,
  tokens: { input: 1200, output: 300, total: 1500, cache_read: 0, cache_creation: 0 },
  unpriced_models: [],
  usd: 1.25,
};

let nextRun = 0;

function summary(overrides: Partial<RunSummary> = {}): RunSummary {
  nextRun += 1;
  const runId = nextRun.toString(16).padStart(32, "0");
  return {
    run_id: runId,
    workflow_id: WORKFLOW_ID,
    version_id: "b".repeat(32),
    title: `Run ${nextRun}`,
    status: "completed",
    pause_reason: null,
    created_at: NOW_S - 600,
    updated_at: NOW_S - 300,
    finished_at: NOW_S - 300,
    activation_count: 3,
    allowed_actions: [],
    spend: SPEND,
    run_branch: `coral/r-${runId.slice(-12)}/base`,
    ...overrides,
  };
}

const page = (data: RunSummary[], next: string | null = null): RunPage => ({
  data,
  next_cursor: next,
});

/** A page, a refusal, or a reply the test releases. */
type PageAnswer = RunPage | Response | Promise<Response>;

/** The runs list's answers by `after` cursor ("" for the first page), in turn; the last repeats. */
let pages: Map<string, PageAnswer[]>;
let workflowsAnswer: () => Response;

function servePages(after: string, ...answers: PageAnswer[]) {
  pages.set(after, answers);
}

function listRequests(): URLSearchParams[] {
  return authenticatedFetch.mock.calls
    .map(([url]) => String(url))
    .filter((url) => url.startsWith("/v1/coral/runs?"))
    .map((url) => new URLSearchParams(url.slice(url.indexOf("?") + 1)));
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function renderTable(path = "/workflows?tab=runs") {
  // The app's own cache rules: 30 s fresh, no refetch on window focus.
  const client = new QueryClient({ defaultOptions: { queries: APP_QUERY_DEFAULTS } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/workflows"
            element={
              <>
                <RunsTable />
                <Where />
              </>
            }
          />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

/**
 * Advance the clock by `ms`, then let the reads it started land. A zero-delay timer set
 * during a tick runs a millisecond later under fake timers, so the flush steps by 1 ms.
 */
const run = async (ms = 0) => {
  await act(() => vi.advanceTimersByTimeAsync(ms));
  await act(() => vi.advanceTimersByTimeAsync(1));
  await act(() => vi.advanceTimersByTimeAsync(1));
  await act(() => vi.advanceTimersByTimeAsync(1));
};
const where = () => screen.getByTestId("where").textContent;
const rows = () => screen.queryAllByTestId("run-row");
const rowOf = (title: string) => rows().find((row) => row.textContent?.includes(title))!;
const chip = (name: string) =>
  within(screen.getByRole("group", { name: "Status" })).getByRole("button", { name });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(NOW_S * 1000);
  nextRun = 0;
  pages = new Map();
  workflowsAnswer = () => jsonResponse(200, WORKFLOWS);
  authenticatedFetch.mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/v1/coral/workflows") return workflowsAnswer();
    if (url.startsWith("/v1/coral/runs?")) {
      const after = new URLSearchParams(url.slice(url.indexOf("?") + 1)).get("after") ?? "";
      const answers = pages.get(after) ?? [page([])];
      const answer = answers.length > 1 ? answers.shift()! : answers[0]!;
      if (answer instanceof Promise) return answer;
      return answer instanceof Response ? answer.clone() : jsonResponse(200, answer);
    }
    return jsonResponse(404, {});
  });
});

afterEach(() => {
  cleanup();
  authenticatedFetch.mockReset();
  vi.useRealTimers();
});

describe("RunsTable", () => {
  it("shows each run's title as a link, workflow, status, start, duration, spend and branch", async () => {
    // WHY: the history answers which run did what, what it cost, and where its work is.
    const done = summary({ title: "Ship the bridge" });
    const paused = summary({
      title: "Paused run",
      status: "paused",
      pause_reason: "user",
      finished_at: null,
      created_at: NOW_S - 125,
      spend: null,
      workflow_id: OTHER_WORKFLOW_ID,
    });
    const unpriced = summary({
      title: "Unpriced run",
      spend: { ...SPEND, usd: 0.5, unpriced_models: ["mystery"] },
      workflow_id: "c".repeat(32),
    });
    servePages("", page([done, paused, unpriced]));
    renderTable();
    await run();

    const first = rowOf("Ship the bridge");
    const link = within(first).getByRole("link", { name: "Ship the bridge" });
    expect(link).toHaveAttribute("href", `/workflows/runs/${done.run_id}`);
    expect(first).toHaveTextContent("Ship a change");
    expect(first).toHaveTextContent("Completed");
    expect(first).toHaveTextContent(formatRunTimestamp(done.created_at, new Date())!);
    expect(first).toHaveTextContent("5m");
    expect(first).toHaveTextContent("$1.25");
    expect(within(first).getByText(done.run_branch).tagName).toBe("CODE");

    const second = rowOf("Paused run");
    expect(second).toHaveTextContent("Review PRs");
    expect(second).toHaveTextContent("Paused: by you");
    expect(second).toHaveTextContent("2m 5s so far");
    expect(second).toHaveTextContent("—");

    // A workflow the list no longer holds, and spend that is only a lower bound.
    const third = rowOf("Unpriced run");
    expect(within(third).getAllByRole("cell")[1]).toHaveTextContent(/^—$/);
    expect(third).toHaveTextContent("at least $0.50");
    expect(screen.queryByText("Needs you")).not.toBeInTheDocument();
  });

  it("names the table and keeps a long title readable on hover", async () => {
    // WHY: a screen reader announces which table it is in; the cell cuts long titles.
    const long = "A".repeat(256);
    servePages("", page([summary({ title: long })]));
    renderTable();
    await run();
    expect(screen.getByRole("table", { name: "Runs" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: long })).toHaveAttribute("title", long);
  });

  it("opens a run's page from its title", async () => {
    const target = summary({ title: "Open me" });
    servePages("", page([target]));
    renderTable();
    await run();
    fireEvent.click(screen.getByRole("link", { name: "Open me" }));
    expect(where()).toBe(`/workflows/runs/${target.run_id}`);
  });

  it("reaches and opens a run from the keyboard alone", async () => {
    // WHY: the title link is the row's only way in, so it must take focus and open on Enter.
    const target = summary({ title: "Keyboard run" });
    servePages("", page([target]));
    renderTable();
    await run();
    // user-event schedules its own timers, which the fake clock would hold.
    vi.useRealTimers();
    const user = userEvent.setup();
    const link = screen.getByRole("link", { name: "Keyboard run" });
    // Past the six status chips and the workflow select.
    await user.keyboard("{Tab>8/}");
    expect(link).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(where()).toBe(`/workflows/runs/${target.run_id}`);
  });

  it("shows a spend the first page lacked once the follow-up read has it", async () => {
    // WHY: the list reads cached spend only, so a run's first row often has none yet.
    const finished = summary({ title: "Fresh", spend: null });
    servePages("", page([finished]), page([{ ...finished, spend: SPEND }]));
    renderTable();
    await run();
    expect(rowOf("Fresh")).toHaveTextContent("—");
    expect(listRequests()).toHaveLength(1);

    await run(SPEND_FILL_MS);
    expect(listRequests()).toHaveLength(2);
    expect(rowOf("Fresh")).toHaveTextContent("$1.25");
    await run(PAUSED_POLL_MS * 2);
    expect(listRequests()).toHaveLength(2);
  });

  it("reads once more only when a settled run's spend stays missing", async () => {
    // WHY: a run whose anchor never had a session has no spend, so polling for it never ends.
    servePages("", page([summary({ title: "Sessionless", status: "cancelled", spend: null })]));
    renderTable();
    await run();
    await run(SPEND_FILL_MS);
    expect(listRequests()).toHaveLength(2);
    await run(PAUSED_POLL_MS * 2);
    expect(listRequests()).toHaveLength(2);
    expect(rowOf("Sessionless")).toHaveTextContent("—");
  });

  it("asks for the status chip's runs and keeps the chip in the URL", async () => {
    // WHY: Running covers runs still setting up; the URL keeps the filter on reload.
    renderTable();
    await run();
    expect(listRequests()[0]!.getAll("status")).toEqual([]);
    expect(chip("All")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(chip("Running"));
    await run();
    expect(listRequests().at(-1)!.getAll("status")).toEqual(["starting", "running"]);
    expect(where()).toBe("/workflows?tab=runs&status=running");
    expect(chip("Running")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(chip("Paused"));
    await run();
    expect(listRequests().at(-1)!.getAll("status")).toEqual(["paused"]);
    expect(where()).toBe("/workflows?tab=runs&status=paused");

    fireEvent.click(chip("All"));
    await run();
    expect(where()).toBe("/workflows?tab=runs");
  });

  it("asks for one workflow's runs and keeps it in the URL", async () => {
    renderTable();
    await run();
    const select = screen.getByRole("combobox", { name: "Workflow" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual(["All workflows", "Ship a change", "Review PRs"]);

    fireEvent.change(select, { target: { value: OTHER_WORKFLOW_ID } });
    await run();
    expect(listRequests().at(-1)!.get("workflow_id")).toBe(OTHER_WORKFLOW_ID);
    expect(where()).toBe(`/workflows?tab=runs&workflow=${OTHER_WORKFLOW_ID}`);

    // Back to every workflow within 30 s: the app's cache still holds that list fresh.
    const reads = listRequests().length;
    fireEvent.change(select, { target: { value: "" } });
    await run();
    expect(listRequests()).toHaveLength(reads);
    expect(where()).toBe("/workflows?tab=runs");

    // Past that, going back reads it again.
    fireEvent.change(select, { target: { value: OTHER_WORKFLOW_ID } });
    await run(APP_QUERY_DEFAULTS.staleTime);
    fireEvent.change(select, { target: { value: "" } });
    await run();
    expect(listRequests().at(-1)!.get("workflow_id")).toBeNull();
  });

  it("opens on the filters a link names, and ignores ones the server would refuse", async () => {
    renderTable(`/workflows?tab=runs&status=failed&workflow=${WORKFLOW_ID}`);
    await run();
    expect(listRequests()[0]!.getAll("status")).toEqual(["failed"]);
    expect(listRequests()[0]!.get("workflow_id")).toBe(WORKFLOW_ID);
    expect(chip("Failed")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("combobox", { name: "Workflow" })).toHaveValue(WORKFLOW_ID);
    cleanup();

    authenticatedFetch.mockClear();
    renderTable("/workflows?tab=runs&status=bogus&workflow=nope");
    await run();
    expect(listRequests()[0]!.getAll("status")).toEqual([]);
    expect(listRequests()[0]!.get("workflow_id")).toBeNull();
  });

  it("names a filtered workflow the list does not hold", async () => {
    // WHY: a deleted workflow's runs stay listable from an old link.
    const gone = "d".repeat(32);
    renderTable(`/workflows?tab=runs&workflow=${gone}`);
    await run();
    const select = screen.getByRole("combobox", { name: "Workflow" });
    expect(select).toHaveValue(gone);
    expect(within(select).getByRole("option", { name: "Unknown workflow" })).toBeInTheDocument();
  });

  it("pages with Load more until the last page", async () => {
    // WHY: every run stays reachable, 25 at a time.
    servePages("", page([summary({ title: "Newest" })], "cursor-1"));
    servePages("cursor-1", page([summary({ title: "Older" })], "cursor-2"));
    servePages("cursor-2", page([summary({ title: "Oldest" })]));
    renderTable();
    await run();
    expect(listRequests()[0]!.get("limit")).toBe("25");

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await run();
    expect(listRequests().at(-1)!.get("after")).toBe("cursor-1");
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await run();
    expect(listRequests().at(-1)!.get("after")).toBe("cursor-2");

    expect(rows().map((row) => within(row).getByRole("link").textContent)).toEqual([
      "Newest",
      "Older",
      "Oldest",
    ]);
    expect(screen.queryByRole("button", { name: "Load more" })).not.toBeInTheDocument();
  });

  it("polls one page while a run is starting or running, and stops once all are settled", async () => {
    // WHY: a live run's row follows it without a reload; a settled list costs nothing.
    const live = summary({ title: "Live", status: "running", finished_at: null });
    servePages("", page([live]), page([{ ...live, status: "completed", finished_at: NOW_S }]));
    renderTable();
    await run();
    expect(listRequests()).toHaveLength(1);

    await run(ACTIVE_POLL_MS);
    expect(listRequests()).toHaveLength(2);
    expect(rowOf("Live")).toHaveTextContent("Completed");

    await run(PAUSED_POLL_MS * 2);
    expect(listRequests()).toHaveLength(2);
  });

  it("polls a page whose only unsettled runs are paused more slowly", async () => {
    // WHY: a paused run can wait for days; checking it each minute is enough.
    servePages(
      "",
      page([summary({ status: "paused", pause_reason: "plan_limit", finished_at: null })]),
    );
    renderTable();
    await run();
    await run(ACTIVE_POLL_MS);
    expect(listRequests()).toHaveLength(1);
    await run(PAUSED_POLL_MS - ACTIVE_POLL_MS);
    expect(listRequests()).toHaveLength(2);
  });

  it("stops polling with two pages loaded, and Refresh goes back to the first page", async () => {
    // WHY: a poll would reread every loaded page; Refresh rereads one.
    const live = summary({ title: "Live", status: "running", finished_at: null });
    servePages("", page([live], "cursor-1"));
    servePages("cursor-1", page([summary({ title: "Older" })]));
    renderTable();
    await run();
    expect(screen.queryByRole("button", { name: "Refresh" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await run();
    expect(listRequests()).toHaveLength(2);
    await run(PAUSED_POLL_MS * 2);
    expect(listRequests()).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await run();
    expect(listRequests()).toHaveLength(3);
    expect(listRequests()[2]!.get("after")).toBeNull();
    expect(rows().map((row) => within(row).getByRole("link").textContent)).toEqual(["Live"]);
    expect(screen.queryByRole("button", { name: "Refresh" })).not.toBeInTheDocument();

    // One page again, with a running row: polling is back.
    await run(ACTIVE_POLL_MS);
    expect(listRequests()).toHaveLength(4);
  });

  it("says it is loading, then that there are no runs yet", async () => {
    let release: (response: Response) => void = () => {};
    servePages(
      "",
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
    );
    renderTable();
    await run();
    expect(screen.getByRole("status")).toHaveTextContent("Loading runs…");

    release(jsonResponse(200, page([])));
    await run();
    expect(screen.getByText("No runs yet. Start one from a workflow.")).toBeInTheDocument();
  });

  it("says when no run matches the filters", async () => {
    renderTable("/workflows?tab=runs&status=cancelled");
    await run();
    expect(screen.getByText("No runs match these filters.")).toBeInTheDocument();
    expect(screen.queryByText("No runs yet. Start one from a workflow.")).not.toBeInTheDocument();
  });

  it("offers Retry when the runs cannot be loaded", async () => {
    servePages(
      "",
      jsonResponse(403, { error: { code: "not_permitted", message: "No.", details: null } }),
      page([summary({ title: "Back" })]),
    );
    renderTable();
    await run();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load runs.");

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await run();
    expect(rowOf("Back")).toBeInTheDocument();
  });

  it("keeps the loaded runs when the next page fails, and Load more tries again", async () => {
    servePages("", page([summary({ title: "Newest" })], "cursor-1"));
    servePages(
      "cursor-1",
      jsonResponse(403, { error: { code: "not_permitted", message: "No.", details: null } }),
      page([summary({ title: "Older" })]),
    );
    renderTable();
    await run();
    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await run();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load more runs.");
    expect(rowOf("Newest")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Load more" }));
    await run();
    expect(rowOf("Older")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load more runs.")).not.toBeInTheDocument();
  });

  it("lists runs while the workflows cannot be read", async () => {
    // WHY: the workflow names are a convenience; the history still loads.
    workflowsAnswer = () => jsonResponse(403, {});
    servePages("", page([summary({ title: "Nameless" })]));
    renderTable();
    await run();
    expect(rowOf("Nameless")).toBeInTheDocument();
    expect(
      within(screen.getByRole("combobox", { name: "Workflow" })).getAllByRole("option"),
    ).toHaveLength(1);
  });
});

describe("runsPollMs", () => {
  const onePage = (...runs: RunSummary[]) => ({ pages: [page(runs)], pageParams: [null] });

  it.each<[RunSummary["status"], number | false, number | false]>([
    ["starting", ACTIVE_POLL_MS, ACTIVE_POLL_MS],
    ["running", ACTIVE_POLL_MS, ACTIVE_POLL_MS],
    ["paused", PAUSED_POLL_MS, PAUSED_POLL_MS],
    ["completed", false, SPEND_FILL_MS],
    ["failed", false, SPEND_FILL_MS],
    ["cancelled", false, SPEND_FILL_MS],
  ])(
    "polls a page of %s runs every %s ms, or %s ms on the first read without spend",
    (status, priced, unpriced) => {
      // WHY: a run still setting up moves as fast as a running one; settled runs cost nothing.
      expect(runsPollMs(onePage(summary({ status })), 1)).toBe(priced);
      expect(runsPollMs(onePage(summary({ status, spend: null })), 1)).toBe(unpriced);
      // The spend follow-up happens once.
      expect(runsPollMs(onePage(summary({ status, spend: null })), 2)).toBe(priced);
    },
  );

  it("follows the liveliest run on the page", () => {
    const paused = summary({ status: "paused" });
    expect(runsPollMs(onePage(paused, summary({ status: "starting" })), 3)).toBe(ACTIVE_POLL_MS);
    expect(runsPollMs(onePage(summary(), paused), 3)).toBe(PAUSED_POLL_MS);
  });

  it("never polls before the first page or with more than one page", () => {
    const live = page([summary({ status: "running" })], "cursor-1");
    expect(runsPollMs(undefined, 0)).toBe(false);
    expect(runsPollMs({ pages: [live, live], pageParams: [null, "cursor-1"] }, 1)).toBe(false);
    // Nor for spend: a poll would reread every loaded page.
    const unpriced = page([summary({ spend: null })], "cursor-1");
    expect(runsPollMs({ pages: [unpriced, unpriced], pageParams: [null, "cursor-1"] }, 1)).toBe(
      false,
    );
  });
});
