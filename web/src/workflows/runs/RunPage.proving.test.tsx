import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";
import { resetStreamSlotManager, setStreamSlotManagerForTest } from "@/store/streamSlots";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => "alice",
  useIdentityReady: () => true,
}));
// xyflow needs layout APIs jsdom lacks; the double renders each custom node with its data.
vi.mock("@xyflow/react", () => import("../fixtures/xyflowDouble"));
vi.mock("@xyflow/react/dist/style.css", () => ({}));

import type { PauseCause, RunDetail, RunHeader, RunView } from "../api/generated/coralApi";
import {
  countingSlots,
  FakeRunServer,
  jsonResponse,
  liveUpTo,
  snapshotEvent,
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
  CONTRACT_OUTCOME,
  CONTRACT_PAUSE_MESSAGES,
  type ContractEvent,
} from "../fixtures/runViewContract";
import { isolated, LOAD_FAILED_TEXT, type PauseReasonName } from "../shared/pauseCopy";
import { RunPage } from "./RunPage";

// The live run view's proving tests, over the run recorded live from the backend's own
// stream: the page follows step transitions as they arrive, an open gate is answered inline
// and the same stream carries the run on, every pause reason's copy renders, and the finished
// run shows its outcome with the server's checkout command. Only I/O is faked: the stream
// body is released event by event, in the recorded order. These prove the client half of
// resuming a run from its gate and of checking a run out; the server halves are the runs
// route's answer tests, the runs end-to-end test and the real-git outcome test.

const RUN_ID = CONTRACT_DETAIL_GATE_PASS1.run_id;
const DETAIL_URL = `/v1/coral/runs/${RUN_ID}`;
const GRAPH_URL = `/v1/coral/runs/${RUN_ID}/graph`;
const ACK_URL = "/v1/coral/inbox/ack";
const ANSWER_URL = `/v1/coral/runs/${RUN_ID}/gates/approve_change:answer`;
const OUTCOME_URL = `/v1/coral/runs/${RUN_ID}/outcome`;
const MARKS = CONTRACT_LIVE_MARKS;
const REJECT_NOTE = "Add a regression test for the parser.";

/** The seq of the recorded entry of `kind` on the slot `scopeKey`. */
function recordedSeq(kind: string, scopeKey: string): number {
  for (const event of CONTRACT_LIVE) {
    if (event.event !== "entry") continue;
    const frame = JSON.parse(event.data) as { seq: number; kind: string; scope_key: string | null };
    if (frame.kind === kind && frame.scope_key === scopeKey) return frame.seq;
  }
  throw new Error(`the recording has no ${kind} on ${scopeKey}`);
}

/** Pass 1's handoff, and Coral's evaluation of it, in the recording. */
const HANDOFF_1 = recordedSeq("engine.handoff_received", "implement||a4:1:0");
const EVALUATED_1 = recordedSeq("engine.handoff_evaluated", "implement||a4:1:0");

let server: FakeRunServer;
let slots: CountingSlots;
let detail: RunDetail;
/** The answer route's reply; a test may hold it to watch the card while it is sent. */
let answerReply: () => Promise<Response>;
/** Every location the router showed, so a test can tell that nothing navigated. */
let locations: string[];

function RecordLocation() {
  const location = useLocation();
  locations.push(`${location.key} ${location.pathname}${location.search}`);
  return null;
}

function renderPage() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter initialEntries={[`/workflows/runs/${RUN_ID}`]}>
        <RecordLocation />
        <Routes>
          <Route path="/workflows/runs/:runId" element={<RunPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

/** Let fake time pass inside React's act, so queries and effects settle with it. */
const run = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));

/** Keep the stream open after `events`, as a live tail does. */
function openStream(events: readonly ContractEvent[]): TestBody {
  const body = testBody();
  server.reply(sseResponse(body.stream));
  body.send(wireText(events));
  return body;
}

/** The recorded events after entry `from` (and its header frames) through entry `to`'s. */
const between = (from: number, to: number) =>
  CONTRACT_LIVE.slice(liveUpTo(from).length, liveUpTo(to).length);

function answerPosts(): { url: string; body: unknown }[] {
  return authenticatedFetch.mock.calls
    .filter(
      ([url, init]) => (init as RequestInit | undefined)?.method === "POST" && url !== ACK_URL,
    )
    .map(([url, init]) => ({
      url: url as string,
      body: JSON.parse((init as RequestInit).body as string) as unknown,
    }));
}

const detailReads = () =>
  authenticatedFetch.mock.calls.filter(
    ([url, init]) => url === DETAIL_URL && (init as RequestInit | undefined)?.method !== "POST",
  ).length;

const page = () => screen.getByTestId("workflow-run-page");
const statusRegion = () => screen.getByTestId("run-status");
/** The pill's kind: `needs_you`, `running`, `paused`, `completed`, … */
const pillKind = () =>
  screen.getByTestId("run-status-pill").querySelector("[data-status]")!.getAttribute("data-status");

const stepItem = (nodeId: string) =>
  within(screen.getByRole("region", { name: "Steps" }))
    .getAllByRole("listitem")
    .find((element) => element.dataset.nodeId === nodeId)!;
const canvasNode = (nodeId: string) =>
  within(
    screen.getAllByTestId("rf-node").find((element) => element.dataset.id === nodeId)!,
  ).getByTestId("flow-node");

/** What the step list and the canvas each say about a node. */
function shown(nodeId: string) {
  const item = stepItem(nodeId);
  const node = canvasNode(nodeId);
  return {
    list: item.dataset.state,
    canvas: node.dataset.state,
    text: within(item).getByTestId("run-step-status").textContent,
    pass: within(item).queryByTestId("run-step-pass")?.textContent ?? null,
    gateOpen: item.dataset.gateOpen === "true" && node.dataset.gateOpen === "true",
  };
}

const gate = () => screen.getByTestId("run-gate");
const gateButton = (name: string) => within(gate()).getByRole("button", { name });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime((CONTRACT_DETAIL_GATE_PASS1.created_at + 125) * 1000);
  server = new FakeRunServer();
  detail = CONTRACT_DETAIL_GATE_PASS1;
  answerReply = () => Promise.resolve(jsonResponse(200, { result: "accepted" }));
  locations = [];
  authenticatedFetch.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (init?.method === "POST") {
      if (url === ACK_URL) return Promise.resolve(jsonResponse(200, { acked: 1 }));
      if (url === ANSWER_URL) return answerReply();
      return Promise.resolve(jsonResponse(500, {}));
    }
    if (url === DETAIL_URL) return Promise.resolve(jsonResponse(200, detail));
    if (url === GRAPH_URL) return Promise.resolve(jsonResponse(200, CONTRACT_GRAPH));
    if (url === OUTCOME_URL) return Promise.resolve(jsonResponse(200, CONTRACT_OUTCOME));
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
  vi.useRealTimers();
});

describe("Live run view proving tests", () => {
  it("1: shows each step transition as the live stream delivers it", async () => {
    // WHY: the view must say where the run is, live, without reading a transcript.
    type Row = [
      seq: number,
      implement: string,
      text: string,
      pass: string,
      gate: string,
      pill: string,
    ];
    const rows: Row[] = [
      [MARKS.implement_running, "running", "Running", "pass 1 of 2", "idle", "running"],
      [HANDOFF_1, "evaluating", "Checking evidence…", "pass 1 of 2", "idle", "running"],
      [EVALUATED_1, "closing", "Committing", "pass 1 of 2", "idle", "running"],
      [MARKS.gate1_open, "completed", "Completed", "pass 1 of 2", "running", "needs_you"],
      // Pass 2 has not reached the gate: its pass-1 answer is history.
      [MARKS.gate1_answered, "running", "Running", "pass 2 of 2", "waiting", "running"],
      [MARKS.pass2_running, "running", "Running", "pass 2 of 2", "waiting", "running"],
    ];
    const body = openStream(liveUpTo(rows[0]![0]));
    renderPage();
    await run();
    let previous = rows[0]![0];
    for (const [seq, implement, text, pass, gateState, pill] of rows) {
      if (seq !== previous) body.send(wireText(between(previous, seq)));
      previous = seq;
      // eslint-disable-next-line no-await-in-loop -- each row waits for its own events
      await run();
      expect({ seq, ...shown("implement") }).toEqual({
        seq,
        list: implement,
        canvas: implement,
        text,
        pass,
        gateOpen: false,
      });
      expect({ seq, gate: shown("approve_change").list }).toEqual({ seq, gate: gateState });
      expect({ seq, pill: pillKind() }).toEqual({ seq, pill });
    }
    // The run has not reached its end, and one connection carried every transition.
    expect(shown("end").list).toBe("idle");
    expect(server.streamRequests()).toHaveLength(1);
  });

  it("1: opens the gate with Needs you, then moves on to pass 2 of 2", async () => {
    // WHY: the loop counter and the open gate, as the recording moves through them.
    const body = openStream(liveUpTo(MARKS.gate1_open));
    renderPage();
    await run();
    expect(shown("approve_change")).toMatchObject({
      list: "running",
      canvas: "running",
      text: "Waiting for you",
      gateOpen: true,
    });
    expect(statusRegion()).toHaveTextContent("Needs you");
    body.send(wireText(between(MARKS.gate1_open, MARKS.pass2_running)));
    await run();
    expect(shown("approve_change")).toMatchObject({
      list: "waiting",
      canvas: "waiting",
      text: "Waiting",
      gateOpen: false,
      pass: "pass 2 of 2",
    });
    expect(shown("implement").pass).toBe("pass 2 of 2");
    expect(within(canvasNode("implement")).getByTestId("flow-node-status")).toHaveTextContent(
      "Running · pass 2 of 2",
    );
    expect(statusRegion()).toHaveTextContent("Running");
  });

  it("2: answers the open gate inline from its context, and the stream carries the run on", async () => {
    // WHY: the ticket's criterion: inline gate approval resumes the run without a page reload.
    const body = openStream(liveUpTo(MARKS.gate1_open));
    renderPage();
    await run();
    const pageElement = page();
    const firstLocation = locations.at(-1);
    expect(pillKind()).toBe("needs_you");
    const visit = CONTRACT_DETAIL_GATE_PASS1.gates[0]!;
    const context = within(gate()).getByText(
      (_content, element) => element?.tagName === "SPAN" && element.textContent === visit.context,
    );
    expect(context.childElementCount).toBe(0);
    expect(
      within(gate())
        .getAllByRole("button")
        .map((element) => element.textContent),
    ).toEqual(["approve", "reject"]);
    expect(
      within(gate())
        .getAllByTestId("run-gate-check")
        .map((element) => element.textContent),
    ).toEqual(["pytest -q · Met at handoff"]);

    let release: (response: Response) => void = () => {};
    answerReply = () =>
      new Promise((resolve) => {
        release = resolve;
      });
    // The recorded owner sent the change back for a second pass, saying why.
    fireEvent.change(within(gate()).getByLabelText("Note"), { target: { value: REJECT_NOTE } });
    fireEvent.click(gateButton("reject"));
    await run();
    expect(gateButton("reject")).toBeDisabled();
    expect(gateButton("approve")).toBeDisabled();
    fireEvent.click(gateButton("reject"));
    await run();
    expect(answerPosts()).toEqual([
      {
        url: ANSWER_URL,
        body: { visit_token: visit.token, outcome: "reject", note: REJECT_NOTE },
      },
    ]);
    // Until the stream says so, the gate is still open.
    expect(pillKind()).toBe("needs_you");
    const readsBefore = detailReads();
    release(jsonResponse(200, { result: "accepted" }));
    await run();
    expect(within(gate()).getByRole("status")).toHaveTextContent("Answered: reject.");
    expect(detailReads()).toBe(readsBefore + 1);

    body.send(wireText(between(MARKS.gate1_open, MARKS.pass2_running)));
    await run();
    expect(screen.queryByTestId("run-gate")).toBeNull();
    expect(pillKind()).toBe("running");
    expect(shown("implement")).toMatchObject({ list: "running", pass: "pass 2 of 2" });
    expect(page()).toBe(pageElement);
    expect(server.streamRequests()).toHaveLength(1);
    expect(new Set(locations)).toEqual(new Set([firstLocation]));
  });

  it("2: approving the second visit ends the wait, and the same stream ends the run", async () => {
    // WHY: an approve lets the run go on to its end, followed live on the page that answered.
    detail = CONTRACT_DETAIL_GATE_PASS2;
    const body = openStream(liveUpTo(MARKS.resumed));
    renderPage();
    await run();
    const pageElement = page();
    const firstLocation = locations.at(-1);
    const visit = CONTRACT_DETAIL_GATE_PASS2.gates[0]!;
    expect(pillKind()).toBe("needs_you");
    expect(gate()).toHaveTextContent("Added the regression test you asked for; pytest -q passes.");
    fireEvent.click(gateButton("approve"));
    await run();
    expect(answerPosts()).toEqual([
      { url: ANSWER_URL, body: { visit_token: visit.token, outcome: "approve" } },
    ]);
    expect(within(gate()).getByRole("status")).toHaveTextContent("Answered: approve.");

    body.send(wireText(CONTRACT_LIVE.slice(liveUpTo(MARKS.resumed).length)));
    await run();
    expect(page()).toHaveAttribute("data-stream", "done");
    expect(screen.queryByTestId("run-gate")).toBeNull();
    expect(pillKind()).toBe("completed");
    for (const node of CONTRACT_GRAPH.nodes) expect(shown(node.id).list).toBe("completed");
    expect(page()).toBe(pageElement);
    expect(server.streamRequests()).toHaveLength(1);
    expect(new Set(locations)).toEqual(new Set([firstLocation]));
  });

  it("2: an answer to a visit asked again is refused, and the card that replaces it is fresh", async () => {
    // WHY: the owner may answer a visit the run has just moved past; the next visit still waits.
    const body = openStream(liveUpTo(MARKS.gate1_open));
    renderPage();
    await run();
    const firstLocation = locations.at(-1);
    const stale = CONTRACT_DETAIL_GATE_PASS1.gates[0]!;
    const next = CONTRACT_DETAIL_GATE_PASS2.gates[0]!;
    // The run moved on to the second visit before this answer reached the server.
    detail = CONTRACT_DETAIL_GATE_PASS2;
    answerReply = () =>
      Promise.resolve(
        jsonResponse(409, {
          error: {
            code: "stale_visit",
            message: "This gate was asked again; answer the latest one.",
            details: { reason: "stale_visit" },
          },
        }),
      );
    const readsBefore = detailReads();
    fireEvent.click(gateButton("approve"));
    await run();
    // The refusal rereads the run, which no longer lists the visit; its card stays, with
    // the refusal, while the stream still holds the visit open.
    expect(detailReads()).toBe(readsBefore + 1);
    expect(gate()).toHaveAttribute("data-token", stale.token);
    expect(within(gate()).getByRole("status")).toHaveTextContent(
      "This gate was asked again. Answer the latest one.",
    );
    expect(within(gate()).queryByRole("button", { name: "approve" })).toBeNull();

    // The stream closes the first visit; the reread already named the second.
    body.send(wireText(between(MARKS.gate1_open, MARKS.gate1_answered)));
    await run();
    expect(screen.queryByTestId("run-gate")).toBeNull();
    body.send(wireText(between(MARKS.gate1_answered, MARKS.gate2_open)));
    await run();
    expect(screen.getAllByTestId("run-gate").map((element) => element.dataset.token)).toEqual([
      next.token,
    ]);
    expect(within(gate()).getByRole("status")).toBeEmptyDOMElement();
    answerReply = () => Promise.resolve(jsonResponse(200, { result: "accepted" }));
    fireEvent.click(gateButton("approve"));
    await run();
    expect(within(gate()).getByRole("status")).toHaveTextContent("Answered: approve.");
    expect(answerPosts()).toEqual([
      { url: ANSWER_URL, body: { visit_token: stale.token, outcome: "approve" } },
      { url: ANSWER_URL, body: { visit_token: next.token, outcome: "approve" } },
    ]);
    expect(server.streamRequests()).toHaveLength(1);
    expect(new Set(locations)).toEqual(new Set([firstLocation]));
  });

  describe("3: every pause reason's copy renders in the banner", () => {
    const BY_REASON = CONTRACT_PAUSE_MESSAGES.by_reason;
    const cause = (reason: PauseCause["reason"], detailCode = "", subject = ""): PauseCause => ({
      reason,
      detail: detailCode,
      subject,
    });
    // Every reason the run header can name; tsc fails when the server adds one.
    const REASON_COPY: Record<PauseReasonName, [PauseCause | null, string, string]> = {
      user: [cause("user", "user"), "Paused: by you", "The run paused."],
      failure_path: [cause("failure_path"), "Paused: step failed", BY_REASON.failure_path],
      infra: [cause("infra"), "Paused: infrastructure", BY_REASON.infra],
      plan_limit: [
        cause("plan_limit"),
        "Paused: plan limit",
        `${BY_REASON.plan_limit} Coral retries periodically.`,
      ],
      auth: [cause("auth"), "Paused: sign-in needed", BY_REASON.auth],
      budget: [cause("budget", "activation_cap"), "Paused: activation cap", BY_REASON.budget],
      rejected_calls: [cause("rejected_calls"), "Paused: refused calls", BY_REASON.rejected_calls],
      liveness: [cause("liveness"), "Paused: step waiting", BY_REASON.liveness],
      drift: [cause("drift"), "Paused: session changed", BY_REASON.drift],
      authority_revoked: [
        cause("authority_revoked"),
        "Paused: account access revoked",
        BY_REASON.authority_revoked,
      ],
      engine_upgrade: [
        cause("engine_upgrade"),
        "Paused: Coral upgraded",
        "Coral was upgraded; this run cannot continue.",
      ],
      gate: [null, "Paused: gate", BY_REASON.gate],
      merge_conflict: [null, "Paused: merge conflict", BY_REASON.merge_conflict],
    };
    const SLOT = "implement||a4:2:0";
    const DETAIL_COPY: [string, PauseReasonName, PauseCause, string][] = [
      [
        "missing evidence",
        "failure_path",
        cause("failure_path", "attempts_exhausted", "pytest -q"),
        `Missing evidence: ${isolated("pytest -q")}.`,
      ],
      [
        "an engine that cannot load the run",
        "failure_path",
        cause("failure_path", "engine.load_failed"),
        LOAD_FAILED_TEXT,
      ],
      [
        "a join waiting on a step that cannot run",
        "liveness",
        cause("liveness", "approve_change is waiting for implement, which can no longer run."),
        `${isolated("Approve change")} is waiting for ${isolated("Implement")}, which can no longer run.`,
      ],
      [
        "an archived session",
        "drift",
        cause("drift", "anchor_archived"),
        "The run’s session was archived. Unarchive it to continue, or cancel.",
      ],
      [
        "a deleted session",
        "drift",
        cause("drift", "anchor_deleted"),
        "The run’s session was deleted. The run can only be cancelled.",
      ],
      [
        "a session someone typed into",
        "drift",
        cause("drift", "pending_input", SLOT),
        `Someone typed into ${isolated("Implement")}’s session while Coral was finishing it.`,
      ],
      [
        "a session that kept working",
        "drift",
        cause("drift", "post_close", SLOT),
        `${isolated("Implement")}’s session kept working after its step closed.`,
      ],
    ];

    async function showPause(reason: string, causes: PauseCause[]) {
      const header: RunHeader = {
        status: "paused",
        pause_reason: reason as PauseReasonName,
        version: 12,
        finished_at: null,
        allowed_actions: ["resume", "cancel"],
        load_error: null,
      };
      const view: RunView = { ...CONTRACT_DETAIL_GATE_PASS2.view!, status: "paused", causes };
      detail = CONTRACT_DETAIL_GATE_PASS2;
      openStream([snapshotEvent(header, view, { seq: 13 })]);
      renderPage();
      await run();
    }

    function expectBanner(title: string, body: string) {
      const banner = screen.getByRole("region", { name: title });
      expect(within(banner).getByRole("heading", { level: 2 })).toHaveTextContent(title);
      expect(within(banner).getByText(body, { selector: "p" })).toBeInTheDocument();
      expect(statusRegion()).toHaveTextContent(title);
    }

    it("covers every reason the server's alerts name, and the owner's own pause", () => {
      // WHY: a reason the fixture names but this table lacks would go untested.
      expect(Object.keys(REASON_COPY).sort()).toEqual([...Object.keys(BY_REASON), "user"].sort());
    });

    it.each(Object.entries(REASON_COPY))("%s", async (reason, [pauseCause, title, body]) => {
      // WHY: each reason says why the run stopped, in the page's own words where it has them.
      await showPause(reason, pauseCause === null ? [] : [pauseCause]);
      expectBanner(title, body);
    });

    it.each(DETAIL_COPY)("%s", async (_name, reason, pauseCause, body) => {
      // WHY: a cause's detail code makes the copy name what to do about it.
      await showPause(reason, [pauseCause]);
      expectBanner(REASON_COPY[reason][1], body);
    });

    it("a reason this client does not know", async () => {
      // WHY: a newer server's reason still reads as a pause, never as a blank banner.
      await showPause("a_future_reason", []);
      expectBanner("Paused", "The run paused.");
    });
  });

  describe("5: the finished run's outcome panel shows the server's checkout command", () => {
    const outcomeReads = () =>
      authenticatedFetch.mock.calls.filter(([url]) => String(url) === OUTCOME_URL).length;
    const outcome = () => screen.getByRole("region", { name: "Outcome" });
    let writeText: ReturnType<typeof vi.fn>;

    beforeEach(() => {
      writeText = vi.fn().mockResolvedValue(undefined);
      Object.defineProperty(window.navigator, "clipboard", {
        value: { writeText },
        configurable: true,
      });
    });

    afterEach(() => {
      Reflect.deleteProperty(window.navigator, "clipboard");
    });

    /** What the panel shows of the recorded outcome. */
    function expectRecordedOutcome() {
      const diff = CONTRACT_OUTCOME.diff!;
      expect(within(outcome()).getByTestId("run-outcome-branch")).toHaveTextContent(
        CONTRACT_OUTCOME.branch!,
      );
      expect(within(outcome()).getByTestId("run-outcome-summary")).toHaveTextContent(
        `${diff.files_changed} files changed, +${diff.insertions} −${diff.deletions}`,
      );
      expect(
        within(within(outcome()).getByTestId("run-outcome-paths"))
          .getAllByRole("listitem")
          .map((item) => item.textContent),
      ).toEqual(diff.paths);
      // Verbatim: the string the real-git outcome test ran through `sh -c`.
      expect(within(outcome()).getByTestId("run-outcome-checkout-command").textContent).toBe(
        CONTRACT_OUTCOME.checkout.command,
      );
      expect(within(outcome()).getByTestId("run-outcome-worktree-command").textContent).toBe(
        CONTRACT_OUTCOME.checkout.worktree_command,
      );
    }

    it("a finished recorded run shows its branch, diff and exact checkout command", async () => {
      // WHY: the ticket's criterion: the outcome panel shows a working checkout command.
      detail = CONTRACT_FINAL_DETAIL;
      server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
      renderPage();
      await run();
      // The finished header mounts the panel, which then reads the outcome.
      await run();
      expect(page()).toHaveAttribute("data-stream", "done");
      expect(pillKind()).toBe("completed");
      expectRecordedOutcome();
      fireEvent.click(within(outcome()).getByTestId("run-outcome-checkout-copy"));
      await run();
      expect(writeText).toHaveBeenCalledWith(CONTRACT_OUTCOME.checkout.command);
    });

    it("a run that ends while watched shows its outcome once the stream says it finished", async () => {
      // WHY: the outcome is read only for a finished run, on the page that watched it end.
      detail = CONTRACT_DETAIL_GATE_PASS2;
      const body = openStream(liveUpTo(MARKS.gate2_open));
      renderPage();
      await run();
      expect(screen.queryByRole("region", { name: "Outcome" })).toBeNull();
      expect(outcomeReads()).toBe(0);
      body.send(wireText(CONTRACT_LIVE.slice(liveUpTo(MARKS.gate2_open).length)));
      await run();
      await run();
      expect(page()).toHaveAttribute("data-stream", "done");
      // The mount's read and the `[DONE]` refetch may coalesce; nothing reads more.
      expect(outcomeReads()).toBeGreaterThan(0);
      expect(outcomeReads()).toBeLessThanOrEqual(2);
      expectRecordedOutcome();
      expect(server.streamRequests()).toHaveLength(1);
    });
  });
});
