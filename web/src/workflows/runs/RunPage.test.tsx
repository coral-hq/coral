import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
  type Location,
  type NavigateFunction,
} from "react-router-dom";
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
// xyflow needs layout APIs jsdom lacks; the double renders each custom node with its data.
vi.mock("@xyflow/react", () => import("../fixtures/xyflowDouble"));
vi.mock("@xyflow/react/dist/style.css", () => ({}));

import type { RunDetail, RunHeader } from "../api/generated/coralApi";
import {
  countingSlots,
  FakeRunServer,
  jsonResponse,
  liveThrough,
  liveUpTo,
  snapshotEvent as snapshot,
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
import { LOAD_FAILED_TEXT } from "../shared/pauseCopy";
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

/** Keep the stream open after `events`, as a live tail does. */
function openStream(events: readonly ContractEvent[]): TestBody {
  const body = testBody();
  server.reply(sseResponse(body.stream));
  body.send(wireText(events));
  return body;
}

/** The router's `navigate`, captured so a test can move to another run. */
let navigate: NavigateFunction = () => {};
/** The router's location, captured so a test can see where the page sent it. */
let location: Location | null = null;

function CaptureRouter() {
  navigate = useNavigate();
  location = useLocation();
  return null;
}

function pageTree(client: QueryClient, strict: boolean, path: string) {
  const tree = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <CaptureRouter />
        <Routes>
          <Route path="/workflows/runs/:runId" element={<RunPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  );
  return strict ? <StrictMode>{tree}</StrictMode> : tree;
}

function renderPage(options: { strict?: boolean; path?: string } = {}) {
  const client = new QueryClient();
  const strict = options.strict ?? false;
  const path = options.path ?? `/workflows/runs/${RUN_ID}`;
  const { rerender } = render(pageTree(client, strict, path));
  return { client, rerender: () => rerender(pageTree(client, strict, path)) };
}

const detailReads = () =>
  authenticatedFetch.mock.calls.filter(
    ([url, init]) => url === DETAIL_URL && (init as RequestInit | undefined)?.method !== "POST",
  ).length;

/** Let fake time pass inside React's act, so queries and effects settle with it. */
const run = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));

/** The live recording after the first gate opens, through `[DONE]`. */
const afterGate1 = () => CONTRACT_LIVE.slice(liveThrough(CONTRACT_LIVE_MARKS.gate1_open).length);

/** The run's actions, in order. */
const actionNames = () =>
  within(screen.getByTestId("run-actions"))
    .queryAllByRole("button")
    .map((element) => element.textContent);

const page = () => screen.getByTestId("workflow-run-page");
const canvasNode = (nodeId: string) =>
  screen.getAllByTestId("rf-node").find((element) => element.dataset.id === nodeId)!;
const statusRegion = () => screen.getByTestId("run-status");
const button = (name: string) => screen.queryByRole("button", { name });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime((CONTRACT_DETAIL_GATE_PASS1.created_at + 125) * 1000);
  server = new FakeRunServer();
  serveDetail(CONTRACT_DETAIL_GATE_PASS1);
  authenticatedFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      if (url === ACK_URL) return Promise.resolve(jsonResponse(200, { acked: 1 }));
      return answer(500, {})();
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
    expect(button("Pause")).toHaveAttribute("data-component-id", "workflows.run.pause");
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

  it("shows nothing of the graph for a run whose state cannot be loaded", async () => {
    // WHY: with no view, every node would read "Not started", which is not known.
    openStream([snapshot({ ...RUNNING, load_error: "engine.load_failed" }, null)]);
    renderPage();
    await run();
    expect(screen.getByText(LOAD_FAILED_TEXT)).toBeInTheDocument();
    expect(screen.queryByTestId("run-canvas")).toBeNull();
    expect(screen.queryByRole("region", { name: "Steps" })).toBeNull();
  });

  it("pushes ?node= when a step is selected, from the list or the canvas, and shows its panel", async () => {
    // WHY: the selection lives in the URL, so Back returns to the run as it was.
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage({ path: `/workflows/runs/${RUN_ID}?panel=gate` });
    await run();
    const steps = screen.getByRole("region", { name: "Steps" });
    fireEvent.click(within(steps).getByRole("button", { name: /^Implement/ }));
    await run();
    expect(location?.search).toBe("?node=implement");
    expect(screen.getByRole("region", { name: "Implement" })).toHaveAttribute(
      "data-node-id",
      "implement",
    );
    expect(within(steps).getByRole("button", { name: /^Implement/ })).toHaveAttribute(
      "aria-current",
      "true",
    );
    const gateNode = screen
      .getAllByTestId("rf-node")
      .find((element) => element.dataset.id === "approve_change")!;
    fireEvent.click(gateNode);
    await run();
    expect(location?.search).toBe("?node=approve_change");
    expect(screen.getByRole("region", { name: "Approve change" })).toBeInTheDocument();
    act(() => navigate(-1));
    await run();
    expect(location?.search).toBe("?node=implement");
  });

  it("keeps the selected step, its panel and the focus on it as the stream moves on", async () => {
    // WHY: patches redraw the steps; the owner's place on the page stays where it was.
    const body = openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage({ path: `/workflows/runs/${RUN_ID}?node=implement` });
    await run();
    const steps = screen.getByRole("region", { name: "Steps" });
    const implement = within(steps).getByRole("button", { name: /^Implement/ });
    implement.focus();
    const key = location?.key;
    expect(screen.getByTestId("run-node-state")).toHaveTextContent(
      "Step · Completed · pass 1 of 2",
    );
    body.send(
      wireText(
        CONTRACT_LIVE.slice(
          liveThrough(CONTRACT_LIVE_MARKS.gate1_open).length,
          liveThrough(CONTRACT_LIVE_MARKS.pass2_running).length,
        ),
      ),
    );
    await run();
    expect(within(steps).getByRole("button", { name: /^Implement/ })).toBe(implement);
    expect(implement).toHaveFocus();
    expect(implement).toHaveAttribute("aria-current", "true");
    expect(screen.getByTestId("run-node-state")).toHaveTextContent("Step · Running · pass 2 of 2");
    expect(within(canvasNode("implement")).getByTestId("flow-node")).toHaveAttribute(
      "data-selected",
      "true",
    );
    expect(location?.key).toBe(key);
    expect(location?.search).toBe("?node=implement");
  });

  it("adds no history entry when the selected step is selected again", async () => {
    // WHY: a repeated click must not leave Back entries that seem to do nothing.
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage();
    await run();
    const opened = location?.key;
    const implement = () =>
      within(screen.getByRole("region", { name: "Steps" })).getByRole("button", {
        name: /^Implement/,
      });
    fireEvent.click(implement());
    await run();
    const selected = location?.key;
    expect(selected).not.toBe(opened);
    fireEvent.click(implement());
    fireEvent.click(canvasNode("implement"));
    await run();
    expect(location?.key).toBe(selected);
    act(() => navigate(-1));
    await run();
    expect(location?.key).toBe(opened);
    expect(location?.search).toBe("");
  });

  it("keeps the steps, gates and actions working when the graph cannot be laid out", async () => {
    // WHY: the layout recurses per rank and overflows the stack on a very deep graph; the
    // rest of the run page must not go down with the canvas.
    // React reports the caught render error through the console and a window error event.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    const reported = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", reported);
    const chain = Array.from({ length: 2_000 }, (_unused, index) => ({
      ...CONTRACT_GRAPH.nodes[1]!,
      id: `n${index}`,
      name: `Step ${index}`,
      evidence: null,
    }));
    const deep = {
      ...CONTRACT_GRAPH,
      nodes: [...CONTRACT_GRAPH.nodes, ...chain],
      arrows: chain.slice(1).map((node, index) => ({
        ...CONTRACT_GRAPH.arrows[0]!,
        id: `x${index}`,
        source: chain[index]!.id,
        target: node.id,
      })),
    };
    const base = authenticatedFetch.getMockImplementation()!;
    authenticatedFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) =>
      String(input) === GRAPH_URL ? Promise.resolve(jsonResponse(200, deep)) : base(input, init),
    );
    try {
      openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
      renderPage();
      await run();
      expect(within(screen.getByTestId("run-canvas")).getByRole("alert")).toHaveTextContent(
        "Unable to display the run's graph.",
      );
      const steps = screen.getByRole("region", { name: "Steps" });
      expect(within(steps).getByRole("button", { name: /^Approve change/ })).toHaveTextContent(
        "Waiting for you",
      );
      expect(screen.getByTestId("run-gate")).toBeInTheDocument();
      expect(actionNames()).toEqual(["Pause", "Cancel run"]);
    } finally {
      window.removeEventListener("error", reported);
      quiet.mockRestore();
    }
  }, 30_000);

  it("ignores a ?node= the graph does not hold", async () => {
    // WHY: a stale or hand-edited link must not select a node that is not there.
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage({ path: `/workflows/runs/${RUN_ID}?node=ghost&panel=gate` });
    await run();
    expect(screen.queryByTestId("run-node-panel")).toBeNull();
    expect(screen.getByTestId("run-gate")).not.toHaveFocus();
  });

  it("focuses the named gate's card when opened with ?node=&panel=gate", async () => {
    // WHY: the Inbox's "Open run" lands on the gate it named, ready to answer.
    openStream(liveThrough(CONTRACT_LIVE_MARKS.gate1_open));
    renderPage({ path: `/workflows/runs/${RUN_ID}?node=approve_change&panel=gate` });
    await run();
    const gate = screen.getByTestId("run-gate");
    expect(gate).toHaveAttribute("data-node-id", "approve_change");
    expect(gate).toHaveFocus();
    expect(within(gate).getByRole("button", { name: "approve" })).toBeEnabled();
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
