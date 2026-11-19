import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";
import { ApiError } from "@/lib/sessionsApi";
import type * as sessionsApiModule from "@/lib/sessionsApi";
import type { InboxKindUi } from "@/lib/inboxKinds";
import type { WorkflowAlert } from "../api/types";
import {
  CONTRACT_INBOX_PAGE,
  CONTRACT_PENDING_ELICITATIONS,
  contractAnchorRow,
} from "../fixtures/workflowInboxContract";
import { parseWorkflowInboxPage } from "./workflowInboxApi";
import { workflowEntries, type WorkflowGateEntryData } from "./workflowEntries";
import { WorkflowAlertCard, WorkflowGateCard } from "./WorkflowInboxCard";

const approve = vi.hoisted(() => vi.fn());
// Real ApiError, so refusals take the production parse path.
vi.mock("@/lib/sessionsApi", async (importActual) => ({
  ...(await importActual<typeof sessionsApiModule>()),
  approve,
}));
// Wire tests run the real `approve()` against these responses.
const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));

const ALERTS = parseWorkflowInboxPage(CONTRACT_INBOX_PAGE).data;
const PAUSE_ALERT = ALERTS[0]!;
const GATE_ALERT = ALERTS[1]!;
const GATE_EVENT = CONTRACT_PENDING_ELICITATIONS[0]!;
const GATE_ID = "coral_gate_00000000000000000000000000000001";
const ANCHOR = contractAnchorRow();
const RUN_LINK = `/workflows/runs/${GATE_ALERT.run_id}?node=approve_change&panel=gate`;

/** A minimal stand-in for the Inbox's card primitives: a toggle row, then the body. */
const UI: InboxKindUi = {
  InboxCard: ({
    testId,
    dataKind,
    tile,
    kindLabel,
    title,
    preview,
    unread,
    expanded,
    onToggle,
    children,
  }) => (
    <div data-testid={testId} data-kind={dataKind}>
      <button type="button" aria-expanded={expanded} onClick={onToggle}>
        {kindLabel}: {title}
      </button>
      <span data-testid="preview">{preview}</span>
      {tile}
      {unread && <span>Unread</span>}
      {expanded && children}
    </div>
  ),
  KindTile: ({ tone }) => <span data-testid="tile" data-tone={tone} />,
  InboxActions: ({ children }) => <div data-testid="actions">{children}</div>,
  outlineAction: "outline-action",
  primaryAction: "primary-action",
};

function gateData(
  alerts: readonly WorkflowAlert[] = ALERTS,
  events: readonly Record<string, unknown>[] = [GATE_EVENT],
): WorkflowGateEntryData {
  const entry = workflowEntries(
    alerts,
    events.map((event) => ({ row: ANCHOR, event })),
  ).find((candidate) => candidate.key.startsWith("workflow:gate:"));
  return entry!.data as WorkflowGateEntryData;
}

function promptOnly(params: Record<string, unknown>): WorkflowGateEntryData {
  const base = GATE_EVENT.params as Record<string, unknown>;
  return gateData([], [{ ...GATE_EVENT, params: { ...base, ...params } }]);
}

function renderCard(node: ReactNode, queryClient = new QueryClient()) {
  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>{node}</MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

function renderGate(
  data: WorkflowGateEntryData = gateData(),
  { viewerId = "alice", expanded = true }: { viewerId?: string | null; expanded?: boolean } = {},
) {
  return renderCard(
    <WorkflowGateCard
      data={data}
      at={GATE_ALERT.created_at}
      viewerId={viewerId}
      expanded={expanded}
      onToggle={() => {}}
      ui={UI}
    />,
  );
}

function setOnline(online: boolean) {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(online);
  window.dispatchEvent(new Event(online ? "online" : "offline"));
}

beforeEach(() => {
  approve.mockResolvedValue({ queued: false });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
  approve.mockReset();
  authenticatedFetch.mockReset();
});

/** Answer through the real `approve()`, with the resolve route's responses in order. */
async function answerOnTheWire(...responses: Response[]) {
  const actual = await vi.importActual<typeof sessionsApiModule>("@/lib/sessionsApi");
  approve.mockImplementation(actual.approve);
  for (const response of responses) authenticatedFetch.mockResolvedValueOnce(response);
}

function wire(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

function refusal(status: number, message: string): Response {
  return wire(status, { error: { code: status === 403 ? "forbidden" : "conflict", message } });
}

describe("WorkflowGateCard", () => {
  it("shows the run, step, prompt, one button per outcome, a labelled note, Open run and the notice", () => {
    // WHY: the card carries the gate's whole context and every way to act on it.
    renderGate();
    const card = screen.getByTestId("inbox-workflow-gate");
    expect(card).toHaveAttribute("data-kind", "workflow-gate");
    expect(screen.getByTestId("tile")).toHaveAttribute("data-tone", "yellow");
    expect(
      screen.getByRole("button", { name: "Workflow gate: Ship the bridge" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("preview")).toHaveTextContent("Approval needed");
    expect(screen.getByText("Unread")).toBeInTheDocument();
    expect(screen.getByText("Step: Approve change")).toBeInTheDocument();
    expect(card).toHaveTextContent("Approve the change?");
    expect(card).toHaveTextContent("Fixed the parser and added a regression test.");
    expect(screen.getByRole("button", { name: "approve" })).toHaveClass("primary-action");
    expect(screen.getByRole("button", { name: "reject" })).toHaveClass("outline-action");
    const note = screen.getByLabelText("Note");
    expect(note.tagName).toBe("TEXTAREA");
    expect(note).toHaveAttribute("maxLength", "2000");
    expect(screen.getByRole("link", { name: /Open run/ })).toHaveAttribute("href", RUN_LINK);
    expect(screen.getByText("Coral notifies you while the app is open.")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
  });

  it("posts the decision and note to the anchor's resolve route, then shows the answer", async () => {
    // WHY: the gate is answered through the anchor's elicitation, with the chosen label.
    let finish: (value: unknown) => void = () => {};
    approve.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      }),
    );
    const { queryClient } = renderGate();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Looks good" } });
    fireEvent.click(screen.getByRole("button", { name: "approve" }));

    expect(approve).toHaveBeenCalledWith(ANCHOR.id, GATE_ID, {
      action: "accept",
      content: { decision: "approve", note: "Looks good" },
    });
    expect(screen.getByRole("status")).toHaveTextContent("Sending…");
    expect(screen.getByRole("button", { name: "approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "reject" })).toBeDisabled();

    await act(async () => finish({ queued: false }));
    expect(screen.getByRole("status")).toHaveTextContent("Answered: approve.");
    expect(screen.queryByRole("button", { name: "approve" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Note")).not.toBeInTheDocument();
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["conversations"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["coral-inbox"] });
  });

  it("sends no note when none was written", async () => {
    // WHY: the note is optional; an empty one is not part of the answer.
    renderGate();
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "reject" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answered: reject."));
    expect(approve).toHaveBeenCalledWith(ANCHOR.id, GATE_ID, {
      action: "accept",
      content: { decision: "reject" },
    });
  });

  it("answers a gate alert that has no prompt through the alert's anchor", async () => {
    // WHY: the in-memory prompt can be lost; the alert still names the anchor and the id.
    renderGate(gateData([GATE_ALERT], []));
    expect(screen.getByTestId("inbox-workflow-gate")).toHaveTextContent("Approve the change?");
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answered: approve."));
    expect(approve).toHaveBeenCalledWith(GATE_ALERT.session_id, GATE_ID, {
      action: "accept",
      content: { decision: "approve" },
    });
  });

  it("shows a duplicate answer as answered", async () => {
    // WHY: the same answer twice is idempotent on the server, so the card agrees.
    approve.mockResolvedValue({ queued: false, duplicate: true });
    renderGate();
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answered: approve."));
  });

  it.each<[string, unknown, string, boolean]>([
    [
      "not_permitted",
      new ApiError("[not_permitted] Only the run owner can answer this gate.", 403, "forbidden"),
      "Only the run owner can answer this gate.",
      false,
    ],
    [
      "stale_visit",
      new ApiError(
        "[stale_visit] This gate was asked again; answer the latest one.",
        409,
        "conflict",
      ),
      "This gate was asked again. Answer the latest one.",
      false,
    ],
    [
      "already_answered",
      new ApiError("[already_answered] Already answered: reject.", 409, "conflict"),
      "Already answered: reject.",
      false,
    ],
    [
      "no_longer_waiting",
      new ApiError("[no_longer_waiting] This gate is no longer waiting.", 409, "conflict"),
      "This gate is no longer waiting.",
      false,
    ],
    [
      "run_paused",
      new ApiError("[run_paused] The run is paused; resume it, then answer.", 409, "conflict"),
      "The run is paused. Resume it, then answer.",
      true,
    ],
    [
      "run_busy",
      new ApiError("[run_busy] The run is busy; try again.", 409, "conflict"),
      "The run is busy; try again.",
      true,
    ],
    [
      "a network failure",
      new TypeError("Failed to fetch"),
      "Couldn’t send your answer. Try again.",
      true,
    ],
  ])("shows %s and moves focus to it", async (_name, error, text, formKept) => {
    // WHY: a refusal explains itself where a screen reader lands, and keeps the form only if retrying helps.
    approve.mockRejectedValue(error);
    renderGate();
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    const status = screen.getByRole("status");
    await waitFor(() => expect(status).toHaveTextContent(text));
    expect(status).toHaveFocus();
    expect(screen.queryByRole("button", { name: "approve" }) !== null).toBe(formKept);
    expect(screen.queryByLabelText("Note") !== null).toBe(formKept);
    if (formKept) expect(screen.getByRole("button", { name: "approve" })).toBeEnabled();
  });

  it("posts the answer to the anchor's resolve route on the wire", async () => {
    // WHY: the gate answers through Omnigent's own resolve route on the run anchor.
    await answerOnTheWire(wire(202, { queued: false }));
    renderGate();
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Ship it" } });
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answered: approve."));
    const [url, init] = authenticatedFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/v1/sessions/${ANCHOR.id}/elicitations/${GATE_ID}/resolve`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      action: "accept",
      content: { decision: "approve", note: "Ship it" },
    });
  });

  it.each<[string, () => Response, string, boolean]>([
    [
      "a 403 refusal",
      () => refusal(403, "[not_permitted] Only the run owner can answer this gate."),
      "Only the run owner can answer this gate.",
      false,
    ],
    [
      "a 409 refusal",
      () => refusal(409, "[stale_visit] This gate was asked again; answer the latest one."),
      "This gate was asked again. Answer the latest one.",
      false,
    ],
    [
      "a duplicate answer",
      () => wire(202, { queued: false, duplicate: true }),
      "Answered: approve.",
      false,
    ],
    [
      "a validation error",
      () => wire(422, { detail: [{ msg: "Field required" }] }),
      "Couldn’t send your answer. Try again.",
      true,
    ],
  ])("reads %s from the resolve route's response", async (_name, response, text, formKept) => {
    // WHY: the server sends `[reason] text` inside its error envelope; the card must read it from there.
    await answerOnTheWire(response());
    renderGate();
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(text));
    expect(screen.queryByRole("button", { name: "approve" }) !== null).toBe(formKept);
  });

  it("keeps the form after a busy run and answers on the retry", async () => {
    // WHY: a refusal that keeps the form must let the owner answer again.
    await answerOnTheWire(
      refusal(409, "[run_busy] The run is busy; try again."),
      wire(202, { queued: false }),
    );
    renderGate();
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("The run is busy; try again."),
    );
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answered: approve."));
    expect(authenticatedFetch).toHaveBeenCalledTimes(2);
  });

  it("sends one answer however fast the buttons are pressed", () => {
    // WHY: approve and then reject in a hurry must not post two different answers.
    approve.mockReturnValue(new Promise(() => {}));
    renderGate();
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    fireEvent.click(screen.getByRole("button", { name: "reject" }));
    expect(approve).toHaveBeenCalledOnce();
  });

  it("renders a gate prompt with unreadable params without offering an answer", () => {
    // WHY: a malformed prompt must not crash the Inbox or offer outcomes it cannot name.
    renderGate(promptOnly({ message: 42, requestedSchema: "form", coral: [1, 2] }));
    expect(screen.getByRole("button", { name: "Workflow gate: Workflow run" })).toBeInTheDocument();
    expect(screen.getByTestId("preview")).toHaveTextContent("Decision needed");
    expect(screen.queryByLabelText("Note")).not.toBeInTheDocument();
    expect(within(screen.getByTestId("actions")).queryAllByRole("button")).toEqual([]);
    expect(screen.getByRole("link", { name: /Open run/ })).toHaveAttribute(
      "href",
      `/workflows/runs/${GATE_ALERT.run_id}?panel=gate`,
    );
  });

  it("builds Open run from ids, never from the payload's links", () => {
    // WHY: payload links are data; a hostile one must not become the card's link.
    const hostile: WorkflowAlert = {
      ...GATE_ALERT,
      node_id: "x&panel=evil",
      deep_link: "https://evil.example/",
      approve_link: "javascript:alert(1)",
    };
    renderGate(gateData([hostile], []));
    expect(screen.getByRole("link", { name: /Open run/ })).toHaveAttribute(
      "href",
      `/workflows/runs/${GATE_ALERT.run_id}?node=x%26panel%3Devil&panel=gate`,
    );
  });

  it("shows multi-line and bidi text as it arrives, cut at 8,000 characters", () => {
    // WHY: the server strips format characters; the card keeps line breaks and adds no markup.
    const message = `Approve change\nRun: Ship‮it​\n<b>${"x".repeat(9_000)}`;
    renderGate(promptOnly({ message }));
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    const prompt = screen.getByText(
      (_content, element) =>
        element?.tagName === "SPAN" && element.textContent?.startsWith("Approve change\n") === true,
    );
    expect(prompt.textContent).toBe(message.slice(0, 8_000));
    expect(prompt.childElementCount).toBe(0);
  });

  it("is read-only for a viewer who is not the run owner", () => {
    // WHY: only the owner can answer; anyone else sees the gate and waits.
    renderGate(promptOnly({}), { viewerId: "bob" });
    expect(screen.getByRole("status")).toHaveTextContent("Waiting for the run owner.");
    expect(screen.queryByRole("button", { name: "approve" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Note")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open run/ })).toBeInTheDocument();
  });

  it("lets the owner, or anyone on a single-user server, answer a gate with no alert", () => {
    // WHY: with no alert the prompt's run owner decides; a null owner is the single local user.
    renderGate(promptOnly({}), { viewerId: "alice" });
    expect(screen.getByRole("button", { name: "approve" })).toBeEnabled();
    cleanup();
    const coral = {
      ...((GATE_EVENT.params as Record<string, unknown>).coral as object),
      run_owner: null,
    };
    renderGate(promptOnly({ coral }), { viewerId: "local" });
    expect(screen.getByRole("button", { name: "approve" })).toBeEnabled();
  });

  it("answers as the owner when the owner's feed lists the gate", () => {
    // WHY: the feed lists only the caller's own alerts, so an alert proves ownership.
    renderGate(gateData(), { viewerId: null });
    expect(screen.getByRole("button", { name: "approve" })).toBeEnabled();
  });

  it("disables answering while offline", () => {
    // WHY: an answer sent offline would only fail; the card says why it is disabled.
    setOnline(false);
    renderGate();
    expect(screen.getByRole("status")).toHaveTextContent("You’re offline.");
    expect(screen.getByRole("button", { name: "approve" })).toBeDisabled();
    act(() => setOnline(true));
    expect(screen.getByRole("button", { name: "approve" })).toBeEnabled();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("renders markup in the prompt as literal text", () => {
    // WHY: report text is agent-written; it must never become markup.
    const message = 'Ship it? <b>now</b> <img src=x onerror="alert(1)"> **bold**';
    const { container } = renderGate(promptOnly({ message }));
    expect(screen.getByTestId("inbox-workflow-gate")).toHaveTextContent(message);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("strong")).toBeNull();
  });

  it("collapses a long prompt behind Show more", () => {
    // WHY: a gate with long reports stays scannable; the whole text is one click away.
    const message = `${"a".repeat(600)}${"b".repeat(100)}`;
    renderGate(promptOnly({ message }));
    const card = screen.getByTestId("inbox-workflow-gate");
    expect(card).not.toHaveTextContent("b".repeat(100));
    expect(card).toHaveTextContent("a".repeat(600));
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    expect(card).toHaveTextContent(message);
    expect(screen.getByRole("button", { name: "Show less" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("says how long the gate has waited once past an hour", () => {
    // WHY: a gate waiting for hours is holding up a run.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime((GATE_ALERT.created_at + 3 * 3600 + 5) * 1000);
    renderGate();
    expect(screen.getByText("Waiting 3 h")).toBeInTheDocument();
    cleanup();
    vi.setSystemTime((GATE_ALERT.created_at + 3599) * 1000);
    renderGate();
    expect(screen.queryByText(/^Waiting/)).not.toBeInTheDocument();
  });

  it("shows only the toggle row while collapsed", () => {
    // WHY: collapsed cards are one line like every Inbox card.
    renderGate(gateData(), { expanded: false });
    expect(screen.queryByRole("button", { name: "approve" })).not.toBeInTheDocument();
  });

  it("names a gate with several outcomes a decision", () => {
    // WHY: only approve/reject gates are approvals; others ask for a decision.
    const coral = {
      ...((GATE_EVENT.params as Record<string, unknown>).coral as object),
      outcomes: ["ship", "hold", "drop"],
    };
    renderGate(
      promptOnly({
        coral,
        requestedSchema: {
          type: "object",
          properties: { decision: { type: "string", enum: ["ship", "hold", "drop"] } },
        },
      }),
    );
    expect(screen.getByTestId("preview")).toHaveTextContent("Decision needed");
    expect(
      within(screen.getByTestId("actions"))
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["ship", "hold", "drop"]);
  });
});

describe("WorkflowAlertCard", () => {
  function renderAlert(alert: WorkflowAlert, onMarkRead = vi.fn()) {
    renderCard(
      <WorkflowAlertCard
        alert={alert}
        at={alert.created_at}
        expanded
        onToggle={() => {}}
        ui={UI}
        onMarkRead={onMarkRead}
      />,
    );
    return onMarkRead;
  }

  it("shows a pause alert with Open run and Mark as read", () => {
    // WHY: alerts that need no answer are read and cleared on the server.
    const onMarkRead = renderAlert(PAUSE_ALERT);
    const card = screen.getByTestId("inbox-workflow-alert");
    expect(card).toHaveAttribute("data-kind", "workflow-alert");
    expect(screen.getByRole("button", { name: "Run paused: Ship the bridge" })).toBeInTheDocument();
    expect(card).toHaveTextContent("A step kept failing to finish its turn.");
    expect(screen.getByRole("link", { name: /Open run/ })).toHaveAttribute(
      "href",
      `/workflows/runs/${PAUSE_ALERT.run_id}`,
    );
    fireEvent.click(screen.getByRole("button", { name: "Mark as read" }));
    expect(onMarkRead).toHaveBeenCalledWith(PAUSE_ALERT.alert_id);
  });

  it.each<[WorkflowAlert["kind"], string, string]>([
    ["pause", "yellow", "Run paused"],
    ["watchdog", "yellow", "Decision waiting"],
    ["run_completed", "gray", "Run completed"],
    ["run_cancelled", "gray", "Run cancelled"],
    ["run_failed", "red", "Run failed"],
  ])("gives a %s alert its tile and label", (kind, tone, label) => {
    // WHY: the tile colour and label say at a glance what happened to the run.
    renderAlert({ ...PAUSE_ALERT, kind });
    expect(screen.getByTestId("tile")).toHaveAttribute("data-tone", tone);
    expect(screen.getByRole("button", { name: `${label}: Ship the bridge` })).toBeInTheDocument();
  });

  it("links a watchdog alert to its step", () => {
    // WHY: the run view opens on the decision that is waiting.
    renderAlert({ ...PAUSE_ALERT, kind: "watchdog", node_id: "choose" });
    expect(screen.getByRole("link", { name: /Open run/ })).toHaveAttribute(
      "href",
      `/workflows/runs/${PAUSE_ALERT.run_id}?node=choose`,
    );
  });

  it("offers no Mark as read when the alert cannot be marked read", () => {
    // WHY: the server refuses to ack an alert without the mark_read action.
    renderAlert({ ...PAUSE_ALERT, actions: ["open_run"] });
    expect(screen.queryByRole("button", { name: "Mark as read" })).not.toBeInTheDocument();
  });

  it("renders the alert text as plain text", () => {
    // WHY: alert text is never markup.
    renderAlert({ ...PAUSE_ALERT, message: '<img src=x onerror="alert(1)">' });
    expect(screen.getByTestId("inbox-workflow-alert")).toHaveTextContent(
      '<img src=x onerror="alert(1)">',
    );
    expect(document.querySelector("img")).toBeNull();
  });
});
