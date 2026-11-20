import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { MemoryRouter, Route, Routes, useNavigate, type NavigateFunction } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";
import { resetStreamSlotManager, setStreamSlotManagerForTest } from "@/store/streamSlots";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
const viewer = vi.hoisted(() => ({ id: "alice" as string | null }));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => viewer.id,
  useIdentityReady: () => true,
}));

import type { RunDetail, RunHeader, RunView } from "../api/generated/coralApi";
import {
  countingSlots,
  FakeRunServer,
  jsonResponse,
  liveThrough,
  sseResponse,
  testBody,
  wireText,
  type CountingSlots,
  type TestBody,
} from "../fixtures/runStreamServer";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_DETAIL_GATE_PASS2,
  CONTRACT_FINAL_DETAIL,
  CONTRACT_FINAL_SNAPSHOT,
  CONTRACT_GRAPH,
  CONTRACT_LIVE,
  CONTRACT_LIVE_MARKS,
  CONTRACT_RESUMED,
  type ContractEvent,
} from "../fixtures/runViewContract";
import { LOAD_FAILED_TEXT, PAUSE_MESSAGES } from "../shared/pauseCopy";
import { LIMITED_RETRY_MS, SLOT_RETRIES, SLOT_RETRY_MS } from "../stream/runStream";
import { RunPage } from "./RunPage";

const RUN_ID = CONTRACT_FINAL_DETAIL.run_id;
const DETAIL_URL = `/v1/coral/runs/${RUN_ID}`;
const GRAPH_URL = `/v1/coral/runs/${RUN_ID}/graph`;
const ACK_URL = "/v1/coral/inbox/ack";
const NOT_FOUND = "Run not found or you don’t have access";
const LOAD_FAILED = "Couldn’t load this run.";
const RUNNING: RunHeader = {
  status: "running",
  pause_reason: null,
  version: 6,
  finished_at: null,
  allowed_actions: ["pause", "cancel"],
  load_error: null,
};

let server: FakeRunServer;
let slots: CountingSlots;
/** The detail read's answer; a fresh response each time. */
let detailReply: () => Promise<Response>;
/** Each POST's answer in turn; an unanswered POST is a 500. */
let postAnswers: (() => Promise<Response>)[];

const answer = (status: number, body: unknown) => () => Promise.resolve(jsonResponse(status, body));

function serveDetail(detail: RunDetail) {
  detailReply = answer(200, detail);
}

function posts(): { url: string; body: unknown }[] {
  return authenticatedFetch.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")
    .map(([url, init]) => ({
      url: url as string,
      body: JSON.parse((init as RequestInit).body as string) as unknown,
    }));
}

const acks = () => posts().filter((post) => post.url === ACK_URL);

/** A snapshot frame as the stream sends it. */
function snapshot(
  header: RunHeader,
  view: RunView | null,
  options: { seq?: number; protocol?: number } = {},
): ContractEvent {
  const seq = options.seq ?? 6;
  const frame = {
    type: "snapshot",
    protocol: options.protocol ?? 1,
    view_version: 1,
    seq,
    run_version: header.version,
    log_version: 1,
    run: header,
    view,
    view_error: view === null ? "engine.load_failed" : null,
  };
  return { event: "snapshot", id: String(seq), data: JSON.stringify(frame) };
}

/** The live recording through entry `seq` and the header frames sent right after it. */
function liveUpTo(seq: number): ContractEvent[] {
  let end = liveThrough(seq).length;
  while (end < CONTRACT_LIVE.length && CONTRACT_LIVE[end]!.event === "run") end += 1;
  return CONTRACT_LIVE.slice(0, end);
}

/** Keep the stream open after `events`, as a live tail does. */
function openStream(events: readonly ContractEvent[]): TestBody {
  const body = testBody();
  server.reply(sseResponse(body.stream));
  body.send(wireText(events));
  return body;
}

/** The router's `navigate`, captured so a test can move to another run. */
let navigate: NavigateFunction = () => {};

function CaptureNavigate() {
  navigate = useNavigate();
  return null;
}

function pageTree(client: QueryClient, strict: boolean) {
  const tree = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/workflows/runs/${RUN_ID}`]}>
        <CaptureNavigate />
        <Routes>
          <Route path="/workflows/runs/:runId" element={<RunPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return strict ? <StrictMode>{tree}</StrictMode> : tree;
}

function renderPage(options: { strict?: boolean } = {}) {
  const client = new QueryClient();
  const strict = options.strict ?? false;
  const { rerender } = render(pageTree(client, strict));
  return { client, rerender: () => rerender(pageTree(client, strict)) };
}

const detailReads = () =>
  authenticatedFetch.mock.calls.filter(
    ([url, init]) => url === DETAIL_URL && (init as RequestInit | undefined)?.method !== "POST",
  ).length;

/** Let fake time pass inside React's act, so queries and effects settle with it. */
const run = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));

/** The live recording after the first gate opens, through `[DONE]`. */
const afterGate1 = () => CONTRACT_LIVE.slice(liveThrough(CONTRACT_LIVE_MARKS.gate1_open).length);

/** The page's buttons, in order: on a ready page, the run's actions. */
const actionNames = () =>
  within(screen.getByTestId("workflow-run-page"))
    .queryAllByRole("button")
    .map((element) => element.textContent);

const page = () => screen.getByTestId("workflow-run-page");
const statusRegion = () => screen.getByTestId("run-status");
const button = (name: string) => screen.queryByRole("button", { name });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime((CONTRACT_DETAIL_GATE_PASS1.created_at + 125) * 1000);
  server = new FakeRunServer();
  serveDetail(CONTRACT_DETAIL_GATE_PASS1);
  postAnswers = [];
  authenticatedFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      if (url === ACK_URL) return Promise.resolve(jsonResponse(200, { acked: 1 }));
      return (postAnswers.shift() ?? answer(500, {}))();
    }
    if (url === DETAIL_URL) return detailReply();
    if (url === GRAPH_URL) return Promise.resolve(jsonResponse(200, CONTRACT_GRAPH));
    return server.fetch(input, init);
  });
  slots = countingSlots();
  setStreamSlotManagerForTest(slots.manager);
});

afterEach(() => {
  cleanup();
  expect(slots.maxHeld()).toBeLessThanOrEqual(1);
  expect(slots.held()).toBe(0);
  resetStreamSlotManager();
  authenticatedFetch.mockReset();
  viewer.id = "alice";
  vi.useRealTimers();
});

describe("RunPage", () => {
  it("shows a spinner while the run loads", async () => {
    // WHY: nothing about the run is known yet, so nothing is guessed.
    detailReply = () => new Promise(() => {});
    renderPage();
    await run();
    expect(page()).toHaveAttribute("data-state", "loading");
    // The pinned graph names the run until its detail loads.
    expect(screen.getByRole("heading", { level: 1, name: "Gated change" })).toBeInTheDocument();
    const message = screen.getByTestId("run-page-message");
    expect(message).toHaveAttribute("role", "status");
    expect(within(message).getByRole("img", { name: "Loading run" })).toBeInTheDocument();
  });

  it("follows the live run: its title, Needs you, elapsed time, spend and allowed actions", async () => {
    // WHY: the page shows where the run is and what it can do, from the stream.
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    expect(page()).toHaveAttribute("data-stream", "live");
    expect(screen.getByRole("heading", { level: 1, name: "Ship the bridge" })).toBeInTheDocument();
    expect(statusRegion()).toHaveTextContent("Needs you");
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("Elapsed 2m 5s");
    expect(screen.getByTestId("run-spend")).toHaveTextContent("Spend so far (estimate) $0.84");
    expect(button("Pause")).toBeInTheDocument();
    expect(button("Cancel run")).toBeInTheDocument();
    expect(button("Resume")).not.toBeInTheDocument();
  });

  it("shows the detail's status as provisional, with no actions, before the stream speaks", async () => {
    // WHY: the detail can be older than the run, so it never decides what the owner can do.
    renderPage();
    await run();
    expect(screen.getByTestId("run-status-pill")).toHaveAttribute("data-provisional", "true");
    expect(statusRegion()).toHaveTextContent("Running");
    expect(button("Pause")).not.toBeInTheDocument();
    expect(button("Cancel run")).not.toBeInTheDocument();
  });

  it("shows the recorded pause with Resume and Cancel, then follows the resume", async () => {
    // WHY: the banner and the actions come from the stream as the run pauses and resumes.
    const paused = liveUpTo(CONTRACT_LIVE_MARKS.paused);
    const body = openStream(paused);
    serveDetail(CONTRACT_DETAIL_GATE_PASS2);
    renderPage();
    await run();
    const banner = screen.getByRole("region", { name: "Paused: by you" });
    expect(banner).toHaveTextContent("The run paused.");
    expect(statusRegion()).toHaveTextContent("Paused: by you");
    expect(button("Resume")).toBeInTheDocument();
    expect(button("Cancel run")).toBeInTheDocument();
    expect(button("Pause")).not.toBeInTheDocument();

    body.send(wireText(liveUpTo(CONTRACT_LIVE_MARKS.resumed).slice(paused.length)));
    await run();
    expect(screen.queryByRole("region", { name: /^Paused/ })).not.toBeInTheDocument();
    expect(statusRegion()).toHaveTextContent("Needs you");
    expect(button("Pause")).toBeInTheDocument();
  });

  it("lists every cause, typed-into and changed steps, and open decisions in the banner", async () => {
    // WHY: everything the run waits on is visible without reading a transcript.
    const view = CONTRACT_DETAIL_GATE_PASS2.view!;
    const paused: RunView = {
      ...view,
      status: "paused",
      causes: [
        { reason: "budget", detail: "", subject: "" },
        { reason: "drift", detail: "pending_input", subject: "implement||a4:2:0" },
      ],
      slots: [
        { ...view.slots[0]!, drift: true },
        { ...view.slots[1]!, pending_input: true },
      ],
      open_decisions: ["implement||a4:2"],
    };
    const header: RunHeader = {
      ...RUNNING,
      status: "paused",
      pause_reason: "budget",
      allowed_actions: ["cancel"],
    };
    serveDetail(CONTRACT_DETAIL_GATE_PASS2);
    openStream([snapshot(header, paused, { seq: 12 })]);
    renderPage();
    await run();
    const banner = screen.getByRole("region", { name: "Paused: activation cap" });
    expect(banner).toHaveTextContent(PAUSE_MESSAGES.budget);
    expect(
      within(banner)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual([
      "Someone typed into Implement’s session while Coral was finishing it.",
      "Implement’s session was changed outside Coral.",
      "Waiting for the orchestrator to choose at Implement.",
    ]);
    expect(button("Cancel run")).toBeInTheDocument();
    expect(button("Resume")).not.toBeInTheDocument();
  });

  it("pauses once, with the button disabled while the request is out", async () => {
    // WHY: a second click must not send a second pause.
    let release: (response: Response) => void = () => {};
    postAnswers = [
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    ];
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    // A pending button shows a spinner, which joins its accessible name.
    const pause = () => screen.getByRole("button", { name: /Pause/ });
    expect(pause()).toHaveAttribute("data-component-id", "workflows.run.pause");
    fireEvent.click(pause());
    await run();
    expect(pause()).toBeDisabled();
    fireEvent.click(pause());
    await run();
    expect(posts()).toEqual([{ url: `${DETAIL_URL}:pause`, body: {} }]);
    const summary = { ...CONTRACT_DETAIL_GATE_PASS1, status: "paused", pause_reason: "user" };
    release(jsonResponse(200, summary));
    await run();
    expect(screen.getByText("Paused.")).toBeInTheDocument();
  });

  it("asks before it cancels", async () => {
    // WHY: a cancel stops every step and cannot be undone.
    postAnswers = [
      answer(200, { ...CONTRACT_DETAIL_GATE_PASS1, status: "cancelled", allowed_actions: [] }),
    ];
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    fireEvent.click(button("Cancel run")!);
    expect(
      screen.getByRole("group", { name: "Cancel this run? Its steps stop." }),
    ).toBeInTheDocument();
    expect(posts()).toEqual([]);
    fireEvent.click(button("Cancel run")!);
    await run();
    expect(posts()).toEqual([{ url: `${DETAIL_URL}:cancel`, body: {} }]);
  });

  it("says a run it cannot see is not found, and marks nothing read", async () => {
    // WHY: another user's run and a missing run look the same; neither changes anything.
    detailReply = answer(404, {
      error: { code: "not_found", message: "Run not found.", details: null },
    });
    server.reply(jsonResponse(404, {}));
    renderPage();
    await run();
    expect(page()).toHaveAttribute("data-state", "not_found");
    // A dead end still has a heading, and its message is announced.
    expect(screen.getByRole("heading", { level: 1, name: "Workflow run" })).toBeInTheDocument();
    expect(screen.getByTestId("run-page-message")).toHaveTextContent(NOT_FOUND);
    expect(button("Retry")).not.toBeInTheDocument();
    expect(acks()).toEqual([]);
  });

  it("says not found when only the stream says so, and stops reading the run", async () => {
    // WHY: the stream checks the owner too; a page that says not found has nothing to refresh.
    server.reply(jsonResponse(404, {}));
    renderPage();
    await run();
    expect(screen.getByText(NOT_FOUND)).toBeInTheDocument();
    await run(3 * 30_000);
    expect(detailReads()).toBe(1);
  });

  it("offers Retry after the detail fails to load, and recovers", async () => {
    // WHY: a server error is passing; Retry reads the run again.
    detailReply = answer(500, {});
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run(5_000);
    expect(page()).toHaveAttribute("data-state", "failed");
    expect(screen.getByText(LOAD_FAILED)).toBeInTheDocument();
    serveDetail(CONTRACT_DETAIL_GATE_PASS1);
    const retry = button("Retry")!;
    retry.focus();
    fireEvent.click(retry);
    await run();
    expect(page()).toHaveAttribute("data-state", "ready");
    expect(screen.getByRole("heading", { level: 1, name: "Ship the bridge" })).toBeInTheDocument();
    // Retry is gone with the failed state, so focus lands on the run's status.
    expect(document.activeElement).toBe(statusRegion());
  });

  it("holds the failed state, its Retry and its focus while the detail keeps failing", async () => {
    // WHY: every reread of a detail that never loaded clears its error while it runs; the page
    // must not flip to the run view and back, dropping Retry and the keyboard user's focus.
    detailReply = answer(500, {});
    const body = openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run(5_000);
    expect(page()).toHaveAttribute("data-state", "failed");
    const retry = button("Retry")!;
    retry.focus();
    const states = new Set<string | undefined>();
    /** Sample the page's state every 100 ms for `ms`, so a flip of about 1 s is seen. */
    const watch = async (ms: number) => {
      /* eslint-disable no-await-in-loop -- each sample waits for the time before it */
      for (let elapsed = 0; elapsed < ms; elapsed += 100) {
        await run(100);
        states.add(page().dataset.state);
      }
      /* eslint-enable no-await-in-loop */
    };
    // The 30 s poll, and the [DONE] that invalidates the detail, each reread it. The rest
    // of the run is sent before the stream's 45 s stall guard would end it.
    await watch(35_000);
    body.send(wireText(afterGate1()));
    await watch(10_000);
    expect(page()).toHaveAttribute("data-stream", "done");
    expect(detailReads()).toBe(6);
    expect([...states]).toEqual(["failed"]);
    expect(button("Retry")).toBe(retry);
    expect(document.activeElement).toBe(retry);
  });

  it("offers Retry after the stream is refused, and Retry opens it again", async () => {
    // WHY: a refused stream ends for good until the owner asks again.
    server.reply(jsonResponse(403, {}));
    renderPage();
    await run();
    expect(page()).toHaveAttribute("data-state", "failed");
    expect(screen.getByText(LOAD_FAILED)).toBeInTheDocument();
    expect(slots.held()).toBe(0);
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    fireEvent.click(button("Retry")!);
    await run();
    expect(server.streamRequests()).toHaveLength(2);
    expect(page()).toHaveAttribute("data-stream", "live");
    expect(statusRegion()).toHaveTextContent("Needs you");
  });

  it("keeps the view while it reconnects, then catches up", async () => {
    // WHY: a dropped connection must not blank the page or lose what happened meanwhile.
    const body = openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    body.fail();
    await run();
    expect(page()).toHaveAttribute("data-stream", "reconnecting");
    expect(statusRegion()).toHaveTextContent("Reconnecting…");
    expect(statusRegion()).toHaveTextContent("Needs you");
    server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
    await run(30_000);
    expect(server.lastEventIds()).toEqual([null, String(CONTRACT_LIVE_MARKS.gate1_open)]);
    expect(statusRegion()).not.toHaveTextContent("Reconnecting…");
    expect(statusRegion()).toHaveTextContent("Completed");
  });

  it("says live updates are limited while no stream slot frees, and clears when one does", async () => {
    // WHY: without a slot the page polls the run, and says so, until the stream comes back.
    slots.setCapacity(0);
    renderPage();
    await run((SLOT_RETRIES + 1) * SLOT_RETRY_MS);
    expect(page()).toHaveAttribute("data-stream", "limited");
    expect(statusRegion()).toHaveTextContent("Live updates limited");
    expect(server.streamRequests()).toHaveLength(0);
    slots.setCapacity(1);
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    await run(LIMITED_RETRY_MS);
    expect(page()).toHaveAttribute("data-stream", "live");
    expect(statusRegion()).not.toHaveTextContent("Live updates limited");
  });

  it("asks for a reload when the server streams a newer protocol", async () => {
    // WHY: this page cannot read the stream, so only a reload brings live updates back.
    openStream([snapshot(RUNNING, CONTRACT_DETAIL_GATE_PASS1.view!, { protocol: 2 })]);
    renderPage();
    await run();
    expect(page()).toHaveAttribute("data-stream", "outdated");
    expect(statusRegion()).toHaveTextContent(
      "This page is out of date. Reload it for live updates.",
    );
  });

  it("offers only Cancel for a run whose state cannot be loaded", async () => {
    // WHY: nothing but a cancel can act on a run the engine cannot read.
    openStream([snapshot({ ...RUNNING, load_error: "engine.load_failed" }, null)]);
    renderPage();
    await run();
    expect(screen.getByText(LOAD_FAILED_TEXT)).toBeInTheDocument();
    expect(button("Cancel run")).toBeInTheDocument();
    expect(button("Pause")).not.toBeInTheDocument();
  });

  it("says the run is being set up while it starts with nothing to show", async () => {
    // WHY: a starting run has no steps yet, which is not a failure.
    const view = {
      ...CONTRACT_DETAIL_GATE_PASS1.view!,
      activations: [],
      slots: [],
      open_gates: [],
    };
    serveDetail({ ...CONTRACT_DETAIL_GATE_PASS1, status: "starting", gates: [], slots: [] });
    openStream([snapshot({ ...RUNNING, status: "starting" }, { ...view, status: null })]);
    renderPage();
    await run();
    expect(statusRegion()).toHaveTextContent("Starting");
    expect(screen.getByText("Setting up the run…")).toBeInTheDocument();
  });

  it("marks a finished run's alerts read once on open, after the detail loads", async () => {
    // WHY: opening a finished run reads its run-end alert; the [DONE] that follows is not news.
    serveDetail(CONTRACT_FINAL_DETAIL);
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    renderPage();
    await run();
    expect(page()).toHaveAttribute("data-stream", "done");
    expect(statusRegion()).toHaveTextContent("Completed");
    expect(button("Pause")).not.toBeInTheDocument();
    expect(button("Cancel run")).not.toBeInTheDocument();
    await run(5_000);
    expect(acks()).toEqual([{ url: ACK_URL, body: { run_id: RUN_ID } }]);
  });

  it("marks a running run's alerts read only once its [DONE] arrives", async () => {
    // WHY: the run-end alert appears when the run ends, which the owner then sees here.
    const body = openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    expect(acks()).toEqual([]);
    body.send(wireText(CONTRACT_LIVE.slice(liveThrough(CONTRACT_LIVE_MARKS.gate1_open).length)));
    await run();
    expect(statusRegion()).toHaveTextContent("Completed");
    await run(5_000);
    expect(acks()).toEqual([{ url: ACK_URL, body: { run_id: RUN_ID } }]);
  });

  it("starts over for another run: no stale header, and only the run that ended in view is read", async () => {
    // WHY: one page component serves every run, so nothing of the last run may leak into the next.
    const otherRun = "b".repeat(32);
    let releaseOther: () => void = () => {};
    const base = authenticatedFetch.getMockImplementation()!;
    authenticatedFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) !== `/v1/coral/runs/${otherRun}`) return base(input, init);
      const other = { ...CONTRACT_FINAL_DETAIL, run_id: otherRun, title: "Other run" };
      return new Promise<Response>((resolve) => {
        releaseOther = () => resolve(jsonResponse(200, other));
      });
    });
    const first = openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    expect(statusRegion()).toHaveTextContent("Needs you");

    act(() => navigate(`/workflows/runs/${otherRun}`));
    await run();
    expect(first.cancelled()).toBe(true);
    expect(page()).toHaveAttribute("data-state", "loading");
    expect(screen.queryByText("Ship the bridge")).not.toBeInTheDocument();
    releaseOther();
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    await run(5_000);
    expect(screen.getByRole("heading", { level: 1, name: "Other run" })).toBeInTheDocument();
    expect(statusRegion()).toHaveTextContent("Completed");
    expect(acks().map((ack) => ack.body)).toEqual([{ run_id: otherRun }]);

    // Back on the first run: its cached view resumes after its seq and is read at its [DONE].
    server.reply(sseResponse(wireText(afterGate1())));
    act(() => navigate(`/workflows/runs/${RUN_ID}`));
    await run(5_000);
    expect(server.lastEventIds()).toEqual([null, null, String(CONTRACT_LIVE_MARKS.gate1_open)]);
    expect(acks().map((ack) => ack.body)).toEqual([{ run_id: otherRun }, { run_id: RUN_ID }]);
  });

  it("marks the run read after Retry when its [DONE] came while the detail was failing", async () => {
    // WHY: the end was seen in view; the post waits only for the detail that confirms the owner.
    detailReply = answer(500, {});
    const body = openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run(5_000);
    body.send(wireText(afterGate1()));
    await run(5_000);
    expect(page()).toHaveAttribute("data-state", "failed");
    expect(acks()).toEqual([]);
    serveDetail(CONTRACT_FINAL_DETAIL);
    fireEvent.click(button("Retry")!);
    await run(5_000);
    expect(statusRegion()).toHaveTextContent("Completed");
    expect(acks()).toEqual([{ url: ACK_URL, body: { run_id: RUN_ID } }]);
  });

  it("marks a run that ends while limited read only at the [DONE] its recovered stream sends", async () => {
    // WHY: a limited-mode poll that shows the run finished is not the owner seeing it end.
    slots.setCapacity(0);
    renderPage();
    await run((SLOT_RETRIES + 1) * SLOT_RETRY_MS);
    expect(page()).toHaveAttribute("data-stream", "limited");
    serveDetail(CONTRACT_FINAL_DETAIL);
    await run(10_000);
    expect(statusRegion()).toHaveTextContent("Completed");
    expect(acks()).toEqual([]);
    slots.setCapacity(1);
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    await run(LIMITED_RETRY_MS);
    expect(page()).toHaveAttribute("data-stream", "done");
    expect(acks()).toEqual([{ url: ACK_URL, body: { run_id: RUN_ID } }]);
  });

  it("resumes after its seq when Retry follows a refusal in the middle of the run", async () => {
    // WHY: Retry restarts from the cached view, so nothing the run did meanwhile is lost.
    const body = openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    body.fail();
    server.reply(jsonResponse(401, {}));
    await run(10_000);
    expect(page()).toHaveAttribute("data-state", "failed");
    server.reply(sseResponse(wireText(afterGate1())));
    fireEvent.click(button("Retry")!);
    await run(5_000);
    const resumeAfter = String(CONTRACT_LIVE_MARKS.gate1_open);
    expect(server.lastEventIds()).toEqual([null, resumeAfter, resumeAfter]);
    expect(statusRegion()).toHaveTextContent("Completed");
    expect(acks()).toHaveLength(1);
  });

  it("stays failed after Retry, with no actions, until the restarted stream sends a frame", async () => {
    // WHY: the cached view is from before the refusal; it is not shown as live until the
    // server speaks again.
    const body = openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    body.fail();
    server.reply(jsonResponse(401, {}));
    await run(10_000);
    expect(page()).toHaveAttribute("data-state", "failed");
    fireEvent.click(button("Retry")!);
    await run(5_000);
    expect(server.streamRequests()).toHaveLength(3);
    expect(page()).toHaveAttribute("data-state", "failed");
    expect(button("Pause")).not.toBeInTheDocument();
    server.reply(sseResponse(wireText(afterGate1())));
    await run();
    expect(page()).toHaveAttribute("data-state", "ready");
    expect(statusRegion()).toHaveTextContent("Completed");
  });

  it("opens one stream and marks a finished run read once under StrictMode", async () => {
    // WHY: development's double effects must not double the stream or the post.
    serveDetail(CONTRACT_FINAL_DETAIL);
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    renderPage({ strict: true });
    await run(5_000);
    expect(server.streamRequests()).toHaveLength(1);
    expect(acks()).toHaveLength(1);
  });

  it("starts a new page for another viewer, which marks the run read for itself", async () => {
    // WHY: what one viewer's page saw or posted never stands for another viewer's.
    serveDetail(CONTRACT_FINAL_DETAIL);
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    const { rerender } = renderPage();
    await run(5_000);
    expect(acks()).toHaveLength(1);
    viewer.id = "bob";
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    rerender();
    await run(5_000);
    expect(server.streamRequests()).toHaveLength(2);
    expect(acks()).toHaveLength(2);
  });

  it.each<[RunHeader["allowed_actions"], RunHeader["load_error"], string[]]>([
    [["pause", "resume", "cancel"], null, ["Pause", "Resume", "Cancel run"]],
    [["pause", "resume", "cancel"], "engine.load_failed", ["Cancel run"]],
    [["pause", "resume"], "engine.load_failed", []],
  ])("offers %j with load error %s as %j", async (allowed, loadError, expected) => {
    // WHY: the stream's actions are offered as given, cut to Cancel for an unloadable run.
    const header: RunHeader = { ...RUNNING, allowed_actions: allowed, load_error: loadError };
    const view = loadError === null ? CONTRACT_DETAIL_GATE_PASS1.view! : null;
    openStream([snapshot(header, view)]);
    renderPage();
    await run();
    expect(actionNames()).toEqual(expected);
  });
});
