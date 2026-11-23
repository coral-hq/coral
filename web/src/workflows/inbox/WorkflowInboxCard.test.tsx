import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";
import { ApiError } from "@/lib/sessionsApi";
import type * as sessionsApiModule from "@/lib/sessionsApi";
import type { InboxKindUi } from "@/lib/inboxKinds";
import type { RunDetail, RunSummary } from "../api/generated/coralApi";
import { CoralRequestError, runQueryKey, runsListPrefixKey } from "../api/runsApi";
import type { WorkflowAlert } from "../api/types";
import {
  CONTRACT_INBOX_PAGE,
  CONTRACT_PENDING_ELICITATIONS,
  contractAnchorRow,
} from "../fixtures/workflowInboxContract";
import { coralScope } from "../shared/viewerScope";
import { RunActions, type RunActionsProps } from "./RunActions";
import { parseWorkflowInboxPage } from "./workflowInboxApi";
import { workflowEntries, type WorkflowGateEntryData } from "./workflowEntries";
import { WorkflowAlertCard, WorkflowGateCard, type RunViewGate } from "./WorkflowInboxCard";

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
const viewer = vi.hoisted(() => ({ id: "alice" as string | null }));
vi.mock("@/hooks/useViewerId", () => ({ useViewerId: () => viewer.id }));

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
  {
    viewerId = "alice",
    expanded = true,
    runView,
  }: { viewerId?: string | null; expanded?: boolean; runView?: RunViewGate } = {},
) {
  return renderCard(
    <WorkflowGateCard
      data={data}
      at={GATE_ALERT.created_at}
      viewerId={viewerId}
      expanded={expanded}
      onToggle={() => {}}
      ui={UI}
      runView={runView}
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
  viewer.id = "alice";
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
    // The runs history shows the run's new state the next time it shows.
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: runsListPrefixKey(coralScope("alice", "/")),
    });
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

describe("WorkflowGateCard in the run view", () => {
  /** A gate as the run page builds it: no alert and no prompt id, the owner's own run. */
  const RUN_GATE: WorkflowGateEntryData = {
    type: "gate",
    elicitationId: null,
    alert: null,
    prompt: {
      sessionId: ANCHOR.id,
      message: "Approve change\nApprove the change?",
      outcomes: ["approve", "reject"],
      runId: GATE_ALERT.run_id,
      runTitle: "Ship the bridge",
      nodeId: "approve_change",
      runOwner: null,
      openedAt: GATE_ALERT.created_at,
    },
  };

  function renderRunGate(answer: (outcome: string, note: string | null) => Promise<unknown>) {
    return renderGate(RUN_GATE, { viewerId: null, runView: { answer, evidence: <p>checks</p> } });
  }

  it("answers through the run view, with no prompt id, and never through the anchor", async () => {
    // WHY: the run page answers on the runs route by the visit's token, not the prompt.
    const answer = vi.fn().mockResolvedValue({ result: "accepted" });
    renderRunGate(answer);
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "Looks good" } });
    const approveButton = screen.getByRole("button", { name: "approve" });
    expect(approveButton).toHaveAttribute("data-component-id", "workflows.run.gate.answer");
    fireEvent.click(approveButton);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answered: approve."));
    expect(answer).toHaveBeenCalledExactlyOnceWith("approve", "Looks good");
    expect(approve).not.toHaveBeenCalled();
  });

  it("passes no note when none was written", async () => {
    // WHY: an empty note is not part of the answer.
    const answer = vi.fn().mockResolvedValue({ result: "accepted" });
    renderRunGate(answer);
    fireEvent.click(screen.getByRole("button", { name: "reject" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answered: reject."));
    expect(answer).toHaveBeenCalledExactlyOnceWith("reject", null);
  });

  it("shows the run view's evidence, and no Open run link or Inbox notice", () => {
    // WHY: on the run page the card is already beside the run.
    renderRunGate(vi.fn());
    const card = screen.getByTestId("inbox-workflow-gate");
    expect(card).toHaveTextContent("Approve the change?");
    expect(within(card).getByText("checks")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open run/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Coral notifies you while the app is open.")).not.toBeInTheDocument();
  });

  it("keeps the form after a refusal whose reason says retrying helps", async () => {
    // WHY: the runs route's reason rides in details.reason, which the card reads.
    const answer = vi
      .fn()
      .mockRejectedValueOnce(
        new CoralRequestError("The run is paused.", 409, "illegal_transition", {
          reason: "run_paused",
        }),
      )
      .mockResolvedValueOnce({ result: "accepted" });
    renderRunGate(answer);
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent(
        "The run is paused. Resume it, then answer.",
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Answered: approve."));
    expect(answer).toHaveBeenCalledTimes(2);
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

describe("WorkflowAlertCard run actions", () => {
  const RUN_ID = PAUSE_ALERT.run_id;
  const RUN_URL = `/v1/coral/runs/${RUN_ID}`;
  // The viewer's scope at the app root, as `useCoralScope` builds it under a MemoryRouter.
  const RUN_KEY = runQueryKey(coralScope("alice", "/"), RUN_ID);
  const TOGGLE = { name: "Run paused: Ship the bridge" };

  type RunActionName = RunDetail["allowed_actions"][number];
  /** A POST's answer: a response, or a call that yields one (a rejection is a network failure). */
  type Answer = Response | (() => Promise<Response>);

  function runDetail(
    allowedActions: RunActionName[],
    overrides: Partial<RunDetail> = {},
  ): RunDetail {
    return {
      run_id: RUN_ID,
      workflow_id: "a".repeat(32),
      version_id: "b".repeat(32),
      title: "Ship the bridge",
      status: "paused",
      pause_reason: "infra",
      created_at: 1_767_268_000,
      updated_at: 1_767_268_860,
      finished_at: null,
      activation_count: 3,
      allowed_actions: allowedActions,
      spend: null,
      run_branch: "coral/r-0a1b2c3d4e5f/base",
      version: 7,
      head_seq: 12,
      max_activations: 100,
      request_preview: null,
      target: null,
      anchor_session_id: "c".repeat(32),
      orchestrator_session_id: null,
      causes: [],
      load_error: null,
      view: null,
      gates: [],
      slots: [],
      retry_activation_ids: [],
      gate_integrity: { label: "not_enforced", reasons: ["host_sandbox_unknown"] },
      ...overrides,
    };
  }

  const RESUMABLE = runDetail(["resume", "cancel"]);
  const RUNNING = runDetail(["pause", "cancel"], { status: "running", pause_reason: null });
  const CANCELLED = runDetail([], { status: "cancelled", pause_reason: null });
  const COMPLETED = runDetail([], { status: "completed", pause_reason: null });

  function summaryOf(run: RunDetail): RunSummary {
    const { run_id, workflow_id, version_id, title, status, pause_reason } = run;
    const { created_at, updated_at, finished_at, activation_count, allowed_actions, spend } = run;
    const { run_branch } = run;
    return {
      run_id,
      workflow_id,
      version_id,
      title,
      status,
      pause_reason,
      created_at,
      updated_at,
      finished_at,
      activation_count,
      allowed_actions,
      spend,
      run_branch,
    };
  }

  /** The runs API: GETs read `details` in turn (the last repeats), POSTs take `answers` in turn. */
  function serveRun(details: RunDetail | RunDetail[], ...answers: Answer[]) {
    const reads = Array.isArray(details) ? [...details] : [details];
    authenticatedFetch.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const answer = answers.shift() ?? wire(500, {});
        return answer instanceof Response ? Promise.resolve(answer) : answer();
      }
      const run = reads.length > 1 ? reads.shift()! : reads[0]!;
      return Promise.resolve(wire(200, run));
    });
  }

  const reads = () =>
    authenticatedFetch.mock.calls
      .filter(([, init]) => (init as RequestInit | undefined)?.method !== "POST")
      .map(([url]) => url as string);

  const posts = () =>
    authenticatedFetch.mock.calls
      .filter(([, init]) => (init as RequestInit | undefined)?.method === "POST")
      .map(([url, init]) => [url as string, JSON.parse((init as RequestInit).body as string)]);

  const envelope = (code: string, message: string) => ({ error: { code, message, details: null } });

  /** A card that keeps its body mounted while collapsed, so only the query's gate stops a read. */
  const KEEP_MOUNTED_UI: InboxKindUi = {
    ...UI,
    InboxCard: (props) => UI.InboxCard({ ...props, expanded: true }),
  };

  function ToggledAlert({
    alert,
    initiallyExpanded,
    ui,
  }: {
    alert: WorkflowAlert;
    initiallyExpanded: boolean;
    ui: InboxKindUi;
  }) {
    const [expanded, setExpanded] = useState(initiallyExpanded);
    return (
      <WorkflowAlertCard
        alert={alert}
        at={alert.created_at}
        expanded={expanded}
        onToggle={() => setExpanded((open) => !open)}
        ui={ui}
        onMarkRead={() => {}}
      />
    );
  }

  function renderRunCard({
    alert = PAUSE_ALERT,
    expanded = true,
    ui = UI,
  }: { alert?: WorkflowAlert; expanded?: boolean; ui?: InboxKindUi } = {}) {
    return renderCard(<ToggledAlert alert={alert} initiallyExpanded={expanded} ui={ui} />);
  }

  const actionNames = () =>
    within(screen.getByTestId("actions"))
      .queryAllByRole("button")
      .map((button) => button.textContent?.trim());

  async function runLoaded(queryClient: QueryClient) {
    await waitFor(() => expect(queryClient.getQueryState(RUN_KEY)?.status).toBe("success"));
  }

  it("reads the run only while its pause card is expanded", async () => {
    // WHY: a long Inbox must not read every paused run; opening one card reads one run.
    serveRun(RESUMABLE);
    const { queryClient } = renderRunCard({ expanded: false, ui: KEEP_MOUNTED_UI });
    await act(async () => {});
    expect(authenticatedFetch).not.toHaveBeenCalled();
    expect(queryClient.getQueryState(RUN_KEY)?.fetchStatus ?? "idle").toBe("idle");

    cleanup();
    renderRunCard({ expanded: false });
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", TOGGLE));
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(reads()).toEqual([RUN_URL]);
  });

  it.each<WorkflowAlert["kind"]>(["watchdog", "overdue", "run_completed", "run_failed"])(
    "reads no run for an expanded %s alert",
    async (kind) => {
      // WHY: only a pause can be resumed or cancelled from the Inbox.
      serveRun(RESUMABLE);
      renderRunCard({ alert: { ...PAUSE_ALERT, kind } });
      await act(async () => {});
      expect(authenticatedFetch).not.toHaveBeenCalled();
      expect(actionNames()).toEqual(["Mark as read"]);
    },
  );

  it.each<[string, RunDetail, string[]]>([
    ["a resumable pause", RESUMABLE, ["Resume", "Cancel run"]],
    [
      "a run that cannot be loaded",
      runDetail(["cancel"], {
        pause_reason: "failure_path",
        load_error: "engine.load_failed",
        causes: [{ reason: "failure_path", detail: "engine.load_failed", subject: "" }],
      }),
      ["Cancel run"],
    ],
    ["a running run", RUNNING, ["Cancel run"]],
    ["a finished run", COMPLETED, []],
  ])("offers exactly what %s allows", async (_name, run, buttons) => {
    // WHY: the server's allowed_actions decide the buttons; the card never guesses.
    serveRun(run);
    const { queryClient } = renderRunCard();
    await runLoaded(queryClient);
    expect(actionNames()).toEqual([...buttons, "Mark as read"]);
    expect(screen.getByRole("link", { name: /Open run/ })).toHaveAttribute(
      "href",
      `/workflows/runs/${RUN_ID}`,
    );
  });

  it("makes Resume the primary action of a pause card", async () => {
    // WHY: one filled button per card; Open run steps back beside Resume.
    serveRun(RESUMABLE);
    renderRunCard();
    expect(await screen.findByRole("button", { name: "Resume" })).toHaveClass("primary-action");
    expect(screen.getByRole("button", { name: "Cancel run" })).toHaveClass("outline-action");
    expect(screen.getByRole("link", { name: /Open run/ })).toHaveClass("outline-action");
  });

  it("resumes with an empty body, announces it and refreshes the Inbox, the run and the runs list", async () => {
    // WHY: the owner resumes from the Inbox and sees the result without leaving it.
    serveRun([RESUMABLE, RUNNING], wire(200, summaryOf(RUNNING)));
    const { queryClient } = renderRunCard();
    const inboxKey = ["coral-inbox", "viewer-scope"];
    queryClient.setQueryData(inboxKey, { alerts: [] });
    const runsListKey = [
      ...runsListPrefixKey(coralScope("alice", "/")),
      { statuses: [], workflowId: null },
    ];
    queryClient.setQueryData(runsListKey, { pages: [], pageParams: [] });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const resume = await screen.findByRole("button", { name: "Resume" });
    // Taken before the click: the pending button's spinner is a status too.
    const status = screen.getByRole("status");
    fireEvent.click(resume);

    await waitFor(() => expect(status).toHaveTextContent("Resumed."));
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveFocus();
    expect(posts()).toEqual([[`${RUN_URL}:resume`, {}]]);
    const [, init] = authenticatedFetch.mock.calls.find(([url]) => url === `${RUN_URL}:resume`)!;
    expect(new Headers((init as RequestInit).headers).get("Content-Type")).toBe("application/json");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["coral-inbox"] });
    expect(queryClient.getQueryState(inboxKey)?.isInvalidated).toBe(true);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: RUN_KEY });
    expect(queryClient.getQueryState(runsListKey)?.isInvalidated).toBe(true);
    await waitFor(() => expect(actionNames()).toEqual(["Cancel run", "Mark as read"]));
    await waitFor(() => expect(reads()).toEqual([RUN_URL, RUN_URL]));
  });

  it("asks before cancelling, and Keep running or Escape posts nothing", async () => {
    // WHY: cancelling stops the run's steps for good, so it takes a second, explicit click.
    serveRun(RESUMABLE);
    renderRunCard();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));

    const confirm = screen.getByRole("group", { name: "Cancel this run? Its steps stop." });
    expect(within(confirm).getByRole("button", { name: "Keep running" })).toHaveFocus();
    expect(
      within(within(confirm).getByTestId("actions"))
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Cancel run", "Keep running"]);
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
    fireEvent.click(within(confirm).getByRole("button", { name: "Keep running" }));
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel run" })).toHaveFocus();

    fireEvent.click(screen.getByRole("button", { name: "Cancel run" }));
    fireEvent.keyDown(screen.getByRole("button", { name: "Keep running" }), { key: "Escape" });
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel run" })).toHaveFocus();
    expect(screen.getByRole("button", { name: "Resume" })).toBeEnabled();
    expect(posts()).toEqual([]);
  });

  it("cancels once confirmed, announces it and refreshes the Inbox and the run", async () => {
    // WHY: the confirmed cancel posts once and the card shows the run's new state.
    serveRun([RESUMABLE, CANCELLED], wire(200, summaryOf(CANCELLED)));
    const { queryClient } = renderRunCard();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    const confirm = screen.getByRole("group", { name: "Cancel this run? Its steps stop." });
    const status = screen.getByRole("status");
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel run" }));

    await waitFor(() => expect(status).toHaveTextContent("Cancelled."));
    expect(status).toHaveFocus();
    expect(posts()).toEqual([[`${RUN_URL}:cancel`, {}]]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["coral-inbox"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: RUN_KEY });
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(actionNames()).toEqual(["Mark as read"]);
  });

  it("disables the run's buttons while an action is pending and posts it once", async () => {
    // WHY: a second click must not send a second action while the first is in flight.
    serveRun(RESUMABLE, () => new Promise<Response>(() => {}));
    renderRunCard();
    const resume = await screen.findByRole("button", { name: "Resume" });
    fireEvent.click(resume);
    fireEvent.click(resume);
    fireEvent.click(screen.getByRole("button", { name: "Cancel run" }));
    expect(resume).toBeDisabled();
    expect(resume).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeDisabled();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    await waitFor(() => expect(posts()).toEqual([[`${RUN_URL}:resume`, {}]]));
  });

  it.each<[string, Answer, string]>([
    [
      "a 503",
      new Response(JSON.stringify(envelope("server_busy", "Busy.")), {
        status: 503,
        headers: { "Retry-After": "1" },
      }),
      "The server is busy; try again.",
    ],
    [
      "a 503 with an HTML body and a non-numeric Retry-After",
      new Response("<html>busy</html>", { status: 503, headers: { "Retry-After": "soon" } }),
      "The server is busy; try again.",
    ],
    [
      "a 503 without a code",
      wire(503, { error: { message: "Busy." } }),
      "The server is busy; try again.",
    ],
    ["a 429", wire(429, envelope("stream_limit", "Too many.")), "Couldn’t update the run."],
    ["a 500", wire(500, {}), "Couldn’t update the run."],
    ["a 422", wire(422, envelope("validation_failed", "Bad body.")), "Couldn’t update the run."],
    [
      "a network failure",
      () => Promise.reject(new TypeError("Failed to fetch")),
      "Couldn’t update the run.",
    ],
  ])("shows %s as its text and keeps the buttons for a retry", async (_name, answer, text) => {
    // WHY: each failure says what happened in the owner's terms; trying again stays one click away.
    serveRun(RESUMABLE, answer);
    renderRunCard();
    const resume = await screen.findByRole("button", { name: "Resume" });
    const status = screen.getByRole("status");
    fireEvent.click(resume);
    await waitFor(() => expect(status).toHaveTextContent(text));
    expect(status).toHaveFocus();
    expect(screen.getByRole("button", { name: "Resume" })).toBeEnabled();
    expect(reads()).toEqual([RUN_URL]);
  });

  it("shows a conflict's own message and refetches the run", async () => {
    // WHY: a 409 means the run moved on; the server says how and the buttons follow it.
    serveRun(
      [RESUMABLE, COMPLETED],
      wire(409, envelope("illegal_transition", "The run is completed.")),
    );
    const { queryClient } = renderRunCard();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const resume = await screen.findByRole("button", { name: "Resume" });
    const status = screen.getByRole("status");
    fireEvent.click(resume);
    await waitFor(() => expect(status).toHaveTextContent("The run is completed."));
    expect(status).toHaveFocus();
    await waitFor(() => expect(actionNames()).toEqual(["Mark as read"]));
    await waitFor(() => expect(reads()).toEqual([RUN_URL, RUN_URL]));
    // Reloading the Inbox now could drop the card, and the message with it.
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["coral-inbox"] });
  });

  it("renders a conflict's message as text, never as markup", async () => {
    // WHY: the server's message reaches the page; it must not become HTML.
    const markup = '<img src=x onerror="alert(1)">';
    serveRun(RESUMABLE, wire(409, envelope("illegal_transition", markup)));
    renderRunCard();
    const resume = await screen.findByRole("button", { name: "Resume" });
    const status = screen.getByRole("status");
    fireEvent.click(resume);
    await waitFor(() => expect(status).toHaveTextContent(markup));
    expect(document.querySelector("img")).toBeNull();
  });

  it("cancels from the keyboard, and a retried cancel posts once per confirm", async () => {
    // WHY: keyboard users reach every step, each result takes focus, and a double click posts once.
    let release: (response: Response) => void = () => {};
    serveRun(
      [RESUMABLE, CANCELLED],
      wire(503, envelope("server_busy", "Busy.")),
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    const user = userEvent.setup();
    renderRunCard();
    await screen.findByRole("button", { name: "Resume" });
    const status = screen.getByRole("status");
    await user.tab();
    await user.tab();
    await user.tab();
    expect(screen.getByRole("button", { name: "Cancel run" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Keep running" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Cancel run" })).toHaveFocus();
    await user.keyboard(" ");
    await user.tab({ shift: true });
    await user.keyboard("{Enter}");
    await waitFor(() => expect(status).toHaveTextContent("The server is busy; try again."));
    expect(status).toHaveFocus();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel run" }));
    const confirm = within(screen.getByRole("group")).getByRole("button", { name: "Cancel run" });
    await user.dblClick(confirm);
    expect(confirm).toBeDisabled();
    expect(posts()).toEqual([
      [`${RUN_URL}:cancel`, {}],
      [`${RUN_URL}:cancel`, {}],
    ]);
    release(wire(200, summaryOf(CANCELLED)));
    await waitFor(() => expect(status).toHaveTextContent("Cancelled."));
    expect(status).toHaveFocus();
  });

  it("refreshes the Inbox and the run when the card closes before the action returns", async () => {
    // WHY: the Inbox may drop or fold the card mid-request; the result must still land.
    let release: (response: Response) => void = () => {};
    serveRun(
      [RESUMABLE, RUNNING],
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    const { queryClient } = renderRunCard();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", TOGGLE));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    release(wire(200, summaryOf(RUNNING)));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["coral-inbox"] }));
    expect(queryClient.getQueryData<RunDetail>(RUN_KEY)?.allowed_actions).toEqual([
      "pause",
      "cancel",
    ]);
    fireEvent.click(screen.getByRole("button", TOGGLE));
    await waitFor(() => expect(actionNames()).toEqual(["Cancel run", "Mark as read"]));
    expect(posts()).toEqual([[`${RUN_URL}:resume`, {}]]);
  });

  it("shows an action's result once back online when it returned while offline", async () => {
    // WHY: going offline mid-request must not lose what the server did.
    let release: (response: Response) => void = () => {};
    serveRun(
      [RESUMABLE, RUNNING],
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    renderRunCard();
    const resume = await screen.findByRole("button", { name: "Resume" });
    const status = screen.getByRole("status");
    fireEvent.click(resume);
    await waitFor(() => expect(posts()).toHaveLength(1));
    act(() => setOnline(false));
    release(wire(200, summaryOf(RUNNING)));
    // The returned summary drops Resume, so its absence shows the result has landed.
    await waitFor(() => expect(resume).not.toBeInTheDocument());
    expect(status).toHaveTextContent("You’re offline.");
    act(() => setOnline(true));
    expect(status).toHaveTextContent("Resumed.");
    expect(posts()).toEqual([[`${RUN_URL}:resume`, {}]]);
  });

  it("hides the run's buttons when a reread finds the run gone", async () => {
    // WHY: a run deleted or no longer the caller's must not keep stale buttons.
    serveRun(RESUMABLE);
    const { queryClient } = renderRunCard();
    await screen.findByRole("button", { name: "Resume" });
    authenticatedFetch.mockImplementation(() =>
      Promise.resolve(wire(404, envelope("not_found", "Run not found."))),
    );
    await act(() => queryClient.invalidateQueries({ queryKey: RUN_KEY }));
    await waitFor(() => expect(actionNames()).toEqual(["Mark as read"]));
    expect(screen.getByRole("link", { name: /Open run/ })).toBeInTheDocument();
  });

  it("hides the run's buttons when the run cannot be read, keeping Open run", async () => {
    // WHY: without allowed_actions the card cannot know what the run allows.
    authenticatedFetch.mockResolvedValue(wire(404, envelope("not_found", "Run not found.")));
    const { queryClient } = renderRunCard();
    await waitFor(() => expect(queryClient.getQueryState(RUN_KEY)?.status).toBe("error"));
    expect(actionNames()).toEqual(["Mark as read"]);
    expect(screen.getByRole("link", { name: /Open run/ })).toBeInTheDocument();
    expect(reads()).toEqual([RUN_URL]);
  });

  it("disables the run's buttons while offline and says why", async () => {
    // WHY: an action sent offline would only fail.
    serveRun(RESUMABLE);
    renderRunCard();
    const resume = await screen.findByRole("button", { name: "Resume" });
    act(() => setOnline(false));
    expect(resume).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("You’re offline.");
    act(() => setOnline(true));
    expect(resume).toBeEnabled();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("says the run is still paused when a resume leaves another cause", async () => {
    // WHY: a resume that clears one cause of several answers 200 with the run still paused.
    const stillPaused = runDetail(["cancel"], { pause_reason: "budget" });
    serveRun([RESUMABLE, stillPaused], wire(200, summaryOf(stillPaused)));
    renderRunCard();
    const resume = await screen.findByRole("button", { name: "Resume" });
    const status = screen.getByRole("status");
    fireEvent.click(resume);
    await waitFor(() => expect(status).toHaveTextContent("The run is still paused."));
    expect(status).not.toHaveTextContent("Resumed.");
    expect(status).toHaveFocus();
    await waitFor(() => expect(actionNames()).toEqual(["Cancel run", "Mark as read"]));
  });

  it("patches only the run's status and actions into the cached detail", async () => {
    // WHY: an action's summary has no view, causes or awaited spend; the reread brings those.
    const detail = runDetail(["resume", "cancel"], {
      causes: [{ reason: "infra", detail: "host lost", subject: "" }],
      spend: {
        estimate: true,
        usd: 1.25,
        live_usd: 1.5,
        tokens: { input: 10, output: 20, total: 30, cache_read: 0, cache_creation: 0 },
        unpriced_models: [],
        sessions: 2,
        as_of: 1_767_268_900,
      },
    });
    let read = false;
    authenticatedFetch.mockImplementation((_url: string, init?: RequestInit) => {
      if (init?.method === "POST") return Promise.resolve(wire(200, summaryOf(RUNNING)));
      if (read) return new Promise<Response>(() => {});
      read = true;
      return Promise.resolve(wire(200, detail));
    });
    const { queryClient } = renderRunCard();
    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() =>
      expect(queryClient.getQueryData<RunDetail>(RUN_KEY)?.status).toBe("running"),
    );
    expect(queryClient.getQueryData<RunDetail>(RUN_KEY)).toEqual({
      ...detail,
      status: "running",
      allowed_actions: ["pause", "cancel"],
    });
  });

  it.each<[string, () => Response]>([
    ["a 404", () => wire(404, envelope("not_found", "Run not found."))],
    ["a 404 with no body", () => new Response(null, { status: 404 })],
  ])(
    "shows %s as gone and hides the buttons once the reread finds no run",
    async (_name, answer) => {
      // WHY: a run that is gone cannot be retried; its buttons must not invite another try.
      let gone = false;
      authenticatedFetch.mockImplementation((_url: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          gone = true;
          return Promise.resolve(answer());
        }
        return Promise.resolve(
          gone ? wire(404, envelope("not_found", "Run not found.")) : wire(200, RESUMABLE),
        );
      });
      renderRunCard();
      const resume = await screen.findByRole("button", { name: "Resume" });
      const status = screen.getByRole("status");
      fireEvent.click(resume);
      await waitFor(() => expect(status).toHaveTextContent("This run is no longer available."));
      expect(status).toHaveFocus();
      await waitFor(() => expect(actionNames()).toEqual(["Mark as read"]));
      expect(reads()).toEqual([RUN_URL, RUN_URL]);
    },
  );

  it.each<[string, () => Response]>([
    ["no body", () => new Response(null, { status: 409 })],
    [
      "an HTML body",
      () => new Response("<html>proxy</html>", { status: 409, statusText: "Conflict" }),
    ],
  ])("shows a conflict with %s as a failed update and rereads the run", async (_name, answer) => {
    // WHY: only Coral's envelope explains a conflict; a bare "409" tells the owner nothing.
    serveRun([RESUMABLE, COMPLETED], answer());
    renderRunCard();
    const resume = await screen.findByRole("button", { name: "Resume" });
    const status = screen.getByRole("status");
    fireEvent.click(resume);
    await waitFor(() => expect(status).toHaveTextContent("Couldn’t update the run."));
    expect(status.textContent).toBe("Couldn’t update the run.");
    await waitFor(() => expect(actionNames()).toEqual(["Mark as read"]));
    expect(reads()).toEqual([RUN_URL, RUN_URL]);
  });

  it("shows a refused cancel's message, rereads the run and leaves the Inbox alone", async () => {
    // WHY: the confirmed cancel takes the same conflict path as Resume.
    serveRun(
      [RESUMABLE, COMPLETED],
      wire(409, envelope("illegal_transition", "The run is completed.")),
    );
    const { queryClient } = renderRunCard();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    const confirm = screen.getByRole("group", { name: "Cancel this run? Its steps stop." });
    const status = screen.getByRole("status");
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel run" }));
    await waitFor(() => expect(status).toHaveTextContent("The run is completed."));
    expect(status).toHaveFocus();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    await waitFor(() => expect(actionNames()).toEqual(["Mark as read"]));
    expect(posts()).toEqual([[`${RUN_URL}:cancel`, {}]]);
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["coral-inbox"] });
  });

  it("ignores Escape while a confirmed cancel is in flight", async () => {
    // WHY: the question stays until the server answers the cancel it already sent.
    serveRun(RESUMABLE, () => new Promise<Response>(() => {}));
    renderRunCard();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    const confirm = screen.getByRole("group", { name: "Cancel this run? Its steps stop." });
    fireEvent.click(within(confirm).getByRole("button", { name: "Cancel run" }));
    const keep = within(confirm).getByRole("button", { name: "Keep running" });
    fireEvent.keyDown(keep, { key: "Escape" });
    expect(screen.getByRole("group")).toBe(confirm);
    expect(keep).toBeDisabled();
    await waitFor(() => expect(posts()).toEqual([[`${RUN_URL}:cancel`, {}]]));
  });

  it("keeps a result in place through an offline spell, without saying it again", async () => {
    // WHY: the offline notice comes and goes beside the result; the result node never changes.
    serveRun([RESUMABLE, RUNNING], wire(200, summaryOf(RUNNING)));
    renderRunCard();
    const resume = await screen.findByRole("button", { name: "Resume" });
    const status = screen.getByRole("status");
    fireEvent.click(resume);
    await waitFor(() => expect(status).toHaveTextContent("Resumed."));
    const result = within(status).getByText("Resumed.");

    act(() => setOnline(false));
    expect(status).toHaveTextContent("Resumed. You’re offline.");
    expect(within(status).getByText("Resumed.")).toBe(result);
    act(() => setOnline(true));
    expect(status.textContent).toBe("Resumed.");
    expect(within(status).getByText("Resumed.")).toBe(result);
  });

  it("closes the cancel question for good when the run stops allowing a cancel", async () => {
    // WHY: a reread can take Cancel away; the question must not linger or come back unasked.
    let allowed: RunActionName[] = ["resume", "cancel"];
    authenticatedFetch.mockImplementation(() => Promise.resolve(wire(200, runDetail(allowed))));
    const { queryClient } = renderRunCard();
    fireEvent.click(await screen.findByRole("button", { name: "Cancel run" }));
    expect(screen.getByRole("group")).toBeInTheDocument();

    allowed = [];
    await act(() => queryClient.invalidateQueries({ queryKey: RUN_KEY }));
    await waitFor(() => expect(screen.queryByRole("group")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveFocus();

    allowed = ["resume", "cancel"];
    await act(() => queryClient.invalidateQueries({ queryKey: RUN_KEY }));
    await waitFor(() => expect(actionNames()).toEqual(["Resume", "Cancel run", "Mark as read"]));
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
    expect(posts()).toEqual([]);
  });

  it("keeps the run's buttons disabled when the card is reopened mid-request", async () => {
    // WHY: the Inbox unmounts a closed card; reopening it must not allow a second action.
    let release: (response: Response) => void = () => {};
    serveRun(
      [RESUMABLE, RUNNING],
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    renderRunCard();
    fireEvent.click(await screen.findByRole("button", { name: "Resume" }));
    await waitFor(() => expect(posts()).toHaveLength(1));
    fireEvent.click(screen.getByRole("button", TOGGLE));
    fireEvent.click(screen.getByRole("button", TOGGLE));

    const resume = await screen.findByRole("button", { name: "Resume" });
    expect(resume).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeDisabled();
    fireEvent.click(resume);
    release(wire(200, summaryOf(RUNNING)));
    await waitFor(() => expect(actionNames()).toEqual(["Cancel run", "Mark as read"]));
    expect(screen.getByRole("button", { name: "Cancel run" })).toBeEnabled();
    expect(posts()).toEqual([[`${RUN_URL}:resume`, {}]]);
  });

  it("reads no run until the viewer is known", async () => {
    // WHY: a run read before identity resolves would be cached under no viewer.
    viewer.id = null;
    serveRun(RESUMABLE);
    renderRunCard();
    await act(async () => {});
    expect(authenticatedFetch).not.toHaveBeenCalled();
    expect(actionNames()).toEqual(["Mark as read"]);
  });

  it("keeps the Inbox's component ids", async () => {
    // WHY: click analytics read these ids; the run view's prefix must not change the Inbox's.
    serveRun(RESUMABLE);
    renderRunCard();
    expect(await screen.findByRole("button", { name: "Resume" })).toHaveAttribute(
      "data-component-id",
      "inbox.workflow_alert.resume",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancel run" }));
    expect(screen.getByRole("button", { name: "Cancel run" })).toHaveAttribute(
      "data-component-id",
      "inbox.workflow_alert.confirm_cancel",
    );
    expect(screen.getByRole("button", { name: "Keep running" })).toHaveAttribute(
      "data-component-id",
      "inbox.workflow_alert.keep_running",
    );
  });

  describe("with the run view's actions", () => {
    const PAUSED = runDetail(["resume", "cancel"], { pause_reason: "user" });

    // No `expanded`: with `allowed`, the card has nothing to read when opened.
    function ViewActions(props: Partial<RunActionsProps>) {
      return (
        <RunActions
          runId={RUN_ID}
          ui={UI}
          withPause
          componentIdPrefix="workflows.run"
          allowed={["pause", "cancel"]}
          {...props}
        />
      );
    }

    function renderView(props: Partial<RunActionsProps> = {}) {
      const queryClient = new QueryClient();
      const wrap = (node: ReactNode) => (
        <QueryClientProvider client={queryClient}>
          <MemoryRouter>{node}</MemoryRouter>
        </QueryClientProvider>
      );
      const view = render(wrap(<ViewActions {...props} />));
      return {
        queryClient,
        rerender: (next: Partial<RunActionsProps>) =>
          view.rerender(wrap(<ViewActions {...next} />)),
      };
    }

    it("offers what the given actions allow, under the given prefix, without reading the run", async () => {
      // WHY: the run view's actions come from the stream's header, never from a detail read.
      serveRun(RUNNING);
      renderView();
      await act(async () => {});
      expect(authenticatedFetch).not.toHaveBeenCalled();
      expect(actionNames()).toEqual(["Pause", "Cancel run"]);
      expect(screen.getByRole("button", { name: "Pause" })).toHaveAttribute(
        "data-component-id",
        "workflows.run.pause",
      );
      expect(screen.getByRole("button", { name: "Cancel run" })).toHaveAttribute(
        "data-component-id",
        "workflows.run.cancel",
      );
    });

    it("pauses once with an empty body, disabled while pending, and says Paused.", async () => {
      // WHY: a second click must not post again, and the owner hears that the run paused.
      let release: (response: Response) => void = () => {};
      serveRun(
        PAUSED,
        () =>
          new Promise<Response>((resolve) => {
            release = resolve;
          }),
      );
      const { queryClient } = renderView();
      const invalidate = vi.spyOn(queryClient, "invalidateQueries");
      const status = screen.getByRole("status");
      const pause = screen.getByRole("button", { name: "Pause" });
      fireEvent.click(pause);
      fireEvent.click(pause);
      await waitFor(() => expect(posts()).toHaveLength(1));
      expect(pause).toBeDisabled();
      expect(pause).toHaveAttribute("aria-busy", "true");
      expect(screen.getByRole("button", { name: "Cancel run" })).toBeDisabled();

      release(wire(200, summaryOf(PAUSED)));
      await waitFor(() => expect(status).toHaveTextContent("Paused."));
      expect(posts()).toEqual([[`${RUN_URL}:pause`, {}]]);
      expect(invalidate).toHaveBeenCalledWith({ queryKey: RUN_KEY });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["coral-inbox"] });
    });

    it("follows the actions it is given", () => {
      // WHY: the stream's next header replaces Pause with Resume once the run is paused.
      const { rerender } = renderView();
      expect(actionNames()).toEqual(["Pause", "Cancel run"]);
      rerender({ allowed: ["resume", "cancel"] });
      expect(actionNames()).toEqual(["Resume", "Cancel run"]);
      expect(screen.getByRole("button", { name: "Resume" })).toHaveAttribute(
        "data-component-id",
        "workflows.run.resume",
      );
      rerender({ allowed: [] });
      expect(actionNames()).toEqual([]);
    });

    it("confirms a cancel under the given prefix", () => {
      // WHY: every button the run view shows carries its own page's id.
      renderView();
      fireEvent.click(screen.getByRole("button", { name: "Cancel run" }));
      expect(screen.getByRole("button", { name: "Cancel run" })).toHaveAttribute(
        "data-component-id",
        "workflows.run.confirm_cancel",
      );
      expect(screen.getByRole("button", { name: "Keep running" })).toHaveAttribute(
        "data-component-id",
        "workflows.run.keep_running",
      );
    });

    it("offers no Pause unless asked to", () => {
      // WHY: the Inbox's pause card resumes or cancels; it never pauses.
      renderView({ withPause: false });
      expect(actionNames()).toEqual(["Cancel run"]);
    });

    it("waits for the viewer before acting, so its buttons never stick disabled", async () => {
      // WHY: the viewer's arrival re-keys the action, which drops a request sent before it.
      viewer.id = null;
      const held: ((response: Response) => void)[] = [];
      const releaseAll = () =>
        held.splice(0).forEach((resolve) => resolve(wire(200, summaryOf(PAUSED))));
      authenticatedFetch.mockImplementation((_url: string, init?: RequestInit) =>
        init?.method === "POST"
          ? new Promise<Response>((resolve) => {
              held.push(resolve);
            })
          : Promise.resolve(wire(200, PAUSED)),
      );
      const { rerender } = renderView();
      const pause = screen.getByRole("button", { name: "Pause" });
      fireEvent.click(pause);
      // The viewer arrives while a request sent without one would still be in flight.
      viewer.id = "alice";
      rerender({});
      await act(async () => releaseAll());
      expect(pause).toBeEnabled();
      expect(posts()).toEqual([]);

      const status = screen.getByRole("status");
      fireEvent.click(pause);
      await waitFor(() => expect(posts()).toHaveLength(1));
      await act(async () => releaseAll());
      await waitFor(() => expect(status).toHaveTextContent("Paused."));
      expect(pause).toBeEnabled();
      expect(posts()).toEqual([[`${RUN_URL}:pause`, {}]]);
    });

    it("keeps its buttons disabled until the viewer is known", () => {
      // WHY: an action keyed under no viewer would be filed where no view of the run looks.
      viewer.id = null;
      renderView();
      expect(screen.getByRole("button", { name: "Pause" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Cancel run" })).toBeDisabled();
    });
  });

  it("keeps each viewer's run under its own key in one cache", async () => {
    // WHY: a sign-in as someone else in the same tab must never show or patch the last viewer's run.
    const BOB_KEY = runQueryKey(coralScope("bob", "/"), RUN_ID);
    const BOB_RUN = runDetail(["cancel"], { status: "running", pause_reason: null });
    authenticatedFetch.mockImplementation((_url: string, init?: RequestInit) =>
      Promise.resolve(
        init?.method === "POST"
          ? wire(200, summaryOf(CANCELLED))
          : wire(200, viewer.id === "alice" ? RESUMABLE : BOB_RUN),
      ),
    );
    const queryClient = new QueryClient();
    const tree = () => (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <ToggledAlert alert={PAUSE_ALERT} initiallyExpanded ui={UI} />
        </MemoryRouter>
      </QueryClientProvider>
    );
    const view = render(tree());
    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();

    viewer.id = "bob";
    view.rerender(tree());
    expect(screen.queryByRole("button", { name: "Resume" })).not.toBeInTheDocument();
    await waitFor(() => expect(actionNames()).toEqual(["Cancel run", "Mark as read"]));
    expect(BOB_KEY).not.toEqual(RUN_KEY);
    expect(queryClient.getQueryData<RunDetail>(BOB_KEY)?.allowed_actions).toEqual(["cancel"]);

    fireEvent.click(screen.getByRole("button", { name: "Cancel run" }));
    fireEvent.click(within(screen.getByRole("group")).getByRole("button", { name: "Cancel run" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Cancelled."));
    expect(queryClient.getQueryData<RunDetail>(RUN_KEY)).toEqual(RESUMABLE);
    expect(queryClient.getQueryState(RUN_KEY)?.isInvalidated).toBe(false);
    expect(reads()).toEqual([RUN_URL, RUN_URL, RUN_URL]);
  });

  it("shares one run's action between the Inbox card and the run view", async () => {
    // WHY: both post under one key, so one in flight holds the other's buttons and its result reaches both.
    let release: (response: Response) => void = () => {};
    serveRun(
      [RESUMABLE, RUNNING],
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <section aria-label="Inbox">
            <ToggledAlert alert={PAUSE_ALERT} initiallyExpanded ui={UI} />
          </section>
          <section aria-label="Run">
            <RunActions
              runId={RUN_ID}
              expanded
              ui={UI}
              allowed={["resume", "cancel"]}
              withPause
              componentIdPrefix="workflows.run"
            />
          </section>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const inbox = within(screen.getByRole("region", { name: "Inbox" }));
    const runView = within(screen.getByRole("region", { name: "Run" }));
    expect(await inbox.findByRole("button", { name: "Resume" })).toBeEnabled();

    fireEvent.click(runView.getByRole("button", { name: "Resume" }));
    await waitFor(() => expect(inbox.getByRole("button", { name: "Resume" })).toBeDisabled());
    expect(inbox.getByRole("button", { name: "Cancel run" })).toBeDisabled();
    fireEvent.click(inbox.getByRole("button", { name: "Resume" }));

    release(wire(200, summaryOf(RUNNING)));
    await waitFor(() => expect(runView.getByRole("status")).toHaveTextContent("Resumed."));
    await waitFor(() => expect(inbox.queryByRole("button", { name: "Resume" })).toBeNull());
    expect(inbox.getByRole("button", { name: "Cancel run" })).toBeEnabled();
    expect(posts()).toEqual([[`${RUN_URL}:resume`, {}]]);
  });
});
