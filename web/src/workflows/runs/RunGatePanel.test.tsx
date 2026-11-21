import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
vi.mock("@/hooks/useViewerId", () => ({ useViewerId: () => "alice" }));

import type { GateOut, RunDetail, RunView } from "../api/generated/coralApi";
import { jsonResponse } from "../fixtures/runStreamServer";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_DETAIL_GATE_PASS2,
  CONTRACT_GRAPH,
} from "../fixtures/runViewContract";
import { RunGatePanel, type GateFocus } from "./RunGatePanel";

const DETAIL = CONTRACT_DETAIL_GATE_PASS1;
const GATE = DETAIL.gates[0]!;
const RUN_ID = DETAIL.run_id;
const ANSWER_URL = `/v1/coral/runs/${RUN_ID}/gates/approve_change:answer`;

interface PanelOptions {
  detail?: RunDetail;
  view?: RunView | null;
  selectedNodeId?: string | null;
  focus?: GateFocus | null;
  onAnswerSettled?: () => void;
  focusFallback?: React.RefObject<HTMLElement | null>;
}

function panel(options: PanelOptions = {}) {
  return (
    <RunGatePanel
      runId={RUN_ID}
      detail={options.detail ?? DETAIL}
      view={options.view === undefined ? DETAIL.view : options.view}
      graph={CONTRACT_GRAPH}
      selectedNodeId={options.selectedNodeId ?? null}
      focus={options.focus ?? null}
      onAnswerSettled={options.onAnswerSettled ?? (() => {})}
      focusFallback={options.focusFallback}
    />
  );
}

function renderPanel(options: PanelOptions = {}) {
  const client = new QueryClient();
  const wrap = (node: React.ReactNode) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>
  );
  const { rerender } = render(wrap(panel(options)));
  return { rerender: (next: PanelOptions) => rerender(wrap(panel(next))) };
}

function answers(): { url: string; body: unknown }[] {
  return authenticatedFetch.mock.calls.map(([url, init]) => ({
    url: url as string,
    body: JSON.parse((init as RequestInit).body as string) as unknown,
  }));
}

const refusal = (status: number, code: string, message: string, details: unknown = null) =>
  jsonResponse(status, { error: { code, message, details } });

const card = () => screen.getByTestId("inbox-workflow-gate");
const gateStatus = () => within(card()).getByRole("status");
const gate = () => screen.getByTestId("run-gate");

const PASS2_GATE = CONTRACT_DETAIL_GATE_PASS2.gates[0]!;
/** A second gate, on another node, open beside the first. */
const OTHER_GATE: GateOut = {
  ...GATE,
  visit_id: "e".repeat(32),
  node_id: "ship",
  token: "ship||:1",
  elicitation_id: null,
  context: "Ship it?",
};

afterEach(() => {
  cleanup();
  authenticatedFetch.mockReset();
});

describe("RunGatePanel", () => {
  it("shows the open gate's context as plain text, its outcomes and its evidence", () => {
    // WHY: the owner answers from the run with everything the Inbox card would show.
    renderPanel();
    expect(
      within(card()).getByRole("heading", { name: "Workflow gate: Approval needed" }),
    ).toBeInTheDocument();
    const context = within(card()).getByText(
      (_content, element) => element?.tagName === "SPAN" && element.textContent === GATE.context,
    );
    expect(context.childElementCount).toBe(0);
    expect(within(card()).getByRole("button", { name: "approve" })).toBeEnabled();
    expect(within(card()).getByRole("button", { name: "reject" })).toBeEnabled();
    expect(within(card()).getByLabelText("Note")).toBeInTheDocument();
    const evidence = within(card()).getByRole("region", { name: "Evidence" });
    expect(evidence).toHaveTextContent("Checked at Implement");
    expect(
      within(evidence)
        .getAllByTestId("run-gate-check")
        .map((element) => element.textContent),
    ).toEqual(["pytest -q · Met at handoff"]);
    // The card already is the run; the Inbox's link and notice are not repeated.
    expect(within(card()).queryByRole("link", { name: /Open run/ })).toBeNull();
    expect(screen.queryByText("Coral notifies you while the app is open.")).toBeNull();
  });

  it("keeps markup in the context as text", () => {
    // WHY: the context quotes agent-written reports; nothing in it is rendered as HTML.
    const context = "Approve change\n<b>bold</b> <img src=x onerror=alert(1)>";
    renderPanel({ detail: { ...DETAIL, gates: [{ ...GATE, context }] } });
    const element = within(card()).getByText(
      (_content, node) => node?.tagName === "SPAN" && node.textContent === context,
    );
    expect(element.childElementCount).toBe(0);
    expect(card().querySelector("img")).toBeNull();
  });

  it("keeps a visit's card while the stream holds it open, after a reread drops it", () => {
    // WHY: the stream says which visits are open; a reread that runs ahead of it must not
    // take away a card, or the refusal it shows, before the stream closes the visit.
    const { rerender } = renderPanel();
    expect(gate()).toHaveAttribute("data-token", GATE.token);
    rerender({ detail: { ...DETAIL, gates: [] } });
    expect(gate()).toHaveAttribute("data-token", GATE.token);
    expect(within(card()).getByRole("button", { name: "approve" })).toBeEnabled();
    rerender({ detail: { ...DETAIL, gates: [] }, view: { ...DETAIL.view!, open_gates: [] } });
    expect(screen.queryByTestId("run-gate")).toBeNull();
    // A visit the view opens again later needs the detail to list it again.
    rerender({ detail: { ...DETAIL, gates: [] } });
    expect(screen.queryByTestId("run-gate")).toBeNull();
  });

  it.each<[string, RunView | null, RunDetail]>([
    ["no view yet", null, DETAIL],
    ["a gate the view no longer holds open", { ...DETAIL.view!, open_gates: [] }, DETAIL],
    ["a gate the detail does not list yet", DETAIL.view, { ...DETAIL, gates: [] }],
  ])("shows nothing for %s", (_name, view, detail) => {
    // WHY: the stream says which gates are open; the detail only supplies their content.
    renderPanel({ view, detail });
    expect(screen.queryByTestId("inbox-workflow-gate")).toBeNull();
  });

  it("puts the selected node's gate first", () => {
    // WHY: a gate the owner came to answer is the first one they see.
    const detail = { ...DETAIL, gates: [GATE, OTHER_GATE] };
    const view = { ...DETAIL.view!, open_gates: [GATE.token, OTHER_GATE.token] };
    const order = () => screen.getAllByTestId("run-gate").map((element) => element.dataset.nodeId);
    const { rerender } = renderPanel({ detail, view });
    expect(order()).toEqual(["approve_change", "ship"]);
    rerender({ detail, view, selectedNodeId: "ship" });
    expect(order()).toEqual(["ship", "approve_change"]);
  });

  it("answers through the runs route with the visit's token and the note, then refreshes", async () => {
    // WHY: the inline card answers the visit it shows, once, and the page rereads the run.
    let release: (response: Response) => void = () => {};
    authenticatedFetch.mockReturnValue(
      new Promise<Response>((resolve) => {
        release = resolve;
      }),
    );
    const onAnswerSettled = vi.fn();
    renderPanel({ onAnswerSettled });
    fireEvent.change(within(card()).getByLabelText("Note"), { target: { value: "Try again" } });
    const reject = within(card()).getByRole("button", { name: "reject" });
    expect(reject).toHaveAttribute("data-component-id", "workflows.run.gate.answer");
    fireEvent.click(reject);
    expect(reject).toBeDisabled();
    expect(within(card()).getByRole("button", { name: "approve" })).toBeDisabled();
    expect(gateStatus()).toHaveTextContent("Sending…");
    fireEvent.click(reject);
    expect(answers()).toEqual([
      {
        url: ANSWER_URL,
        body: { visit_token: GATE.token, outcome: "reject", note: "Try again" },
      },
    ]);
    expect(onAnswerSettled).not.toHaveBeenCalled();
    await act(async () => release(jsonResponse(200, { result: "accepted" })));
    expect(gateStatus()).toHaveTextContent("Answered: reject.");
    expect(onAnswerSettled).toHaveBeenCalledOnce();
  });

  it("sends no note when none was written", async () => {
    // WHY: the note is optional; an empty one is not part of the answer.
    authenticatedFetch.mockResolvedValue(jsonResponse(200, { result: "duplicate" }));
    renderPanel();
    fireEvent.change(within(card()).getByLabelText("Note"), { target: { value: "  " } });
    fireEvent.click(within(card()).getByRole("button", { name: "approve" }));
    await waitFor(() => expect(gateStatus()).toHaveTextContent("Answered: approve."));
    expect(answers()).toEqual([
      { url: ANSWER_URL, body: { visit_token: GATE.token, outcome: "approve" } },
    ]);
  });

  it.each<[string, () => Response, string, boolean]>([
    [
      "a paused run",
      () => refusal(409, "illegal_transition", "The run is paused.", { reason: "run_paused" }),
      "The run is paused. Resume it, then answer.",
      true,
    ],
    [
      "an answer already taken",
      () =>
        refusal(409, "illegal_transition", "Already answered: approve.", {
          reason: "already_answered",
        }),
      "Already answered: approve.",
      false,
    ],
    [
      "a visit asked again",
      () => refusal(409, "stale_visit", "This gate was asked again."),
      "This gate was asked again. Answer the latest one.",
      false,
    ],
    [
      "a visit the run no longer has",
      () => refusal(404, "not_found", "Run not found."),
      "This gate is no longer waiting.",
      false,
    ],
    [
      "a visit that closed while the answer was sent",
      () =>
        refusal(409, "illegal_transition", "This gate is no longer waiting.", {
          reason: "no_longer_waiting",
        }),
      "This gate is no longer waiting.",
      false,
    ],
    [
      "an outcome the gate does not take",
      () =>
        refusal(422, "validation_failed", "Choose one of: approve, reject.", {
          reason: "invalid_answer",
        }),
      "Choose one of: approve, reject.",
      true,
    ],
    [
      "a busy run",
      () => refusal(503, "server_busy", "The run is busy; try again.", { reason: "run_busy" }),
      "The run is busy; try again.",
      true,
    ],
  ])(
    "explains %s from the refusal's reason, and rereads the run",
    async (_name, response, text, formKept) => {
      // WHY: the runs route carries its reason in details.reason; the card reads it there. A
      // refusal means the run moved on, so the page reads it again.
      authenticatedFetch.mockResolvedValue(response());
      const onAnswerSettled = vi.fn();
      renderPanel({ onAnswerSettled });
      fireEvent.click(within(card()).getByRole("button", { name: "approve" }));
      await waitFor(() => expect(gateStatus()).toHaveTextContent(text));
      expect(gateStatus()).toHaveFocus();
      expect(within(card()).queryByRole("button", { name: "approve" }) !== null).toBe(formKept);
      expect(onAnswerSettled).toHaveBeenCalledOnce();
    },
  );

  it("does not reread the run after a network failure", async () => {
    // WHY: with no answer from the server there is nothing new to read, and the read would fail too.
    authenticatedFetch.mockRejectedValue(new TypeError("Failed to fetch"));
    const onAnswerSettled = vi.fn();
    renderPanel({ onAnswerSettled });
    fireEvent.click(within(card()).getByRole("button", { name: "approve" }));
    await waitFor(() =>
      expect(gateStatus()).toHaveTextContent("Couldn’t send your answer. Try again."),
    );
    expect(onAnswerSettled).not.toHaveBeenCalled();
  });

  it("sends nothing while offline, then answers once back online", async () => {
    // WHY: an answer sent offline would only fail; the card says why it waits.
    authenticatedFetch.mockResolvedValue(jsonResponse(200, { result: "accepted" }));
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    try {
      renderPanel();
      const approve = within(card()).getByRole("button", { name: "approve" });
      expect(approve).toBeDisabled();
      expect(gateStatus()).toHaveTextContent("You’re offline.");
      fireEvent.click(approve);
      expect(authenticatedFetch).not.toHaveBeenCalled();
      online.mockReturnValue(true);
      act(() => {
        window.dispatchEvent(new Event("online"));
      });
      fireEvent.click(approve);
      await waitFor(() => expect(gateStatus()).toHaveTextContent("Answered: approve."));
      expect(answers()).toEqual([
        { url: ANSWER_URL, body: { visit_token: GATE.token, outcome: "approve" } },
      ]);
    } finally {
      online.mockRestore();
    }
  });

  it("sends a note at the server's limit as written, line breaks and markup included", async () => {
    // WHY: the runs route takes notes of up to 2,000 characters; the card cuts and trims none.
    authenticatedFetch.mockResolvedValue(jsonResponse(200, { result: "accepted" }));
    renderPanel();
    const note = within(card()).getByLabelText("Note");
    expect(note).toHaveAttribute("maxLength", "2000");
    const head = " <b>Keep</b>\nthe test\n";
    const written = head + "x".repeat(2_000 - head.length);
    fireEvent.change(note, { target: { value: written } });
    fireEvent.click(within(card()).getByRole("button", { name: "reject" }));
    await waitFor(() => expect(gateStatus()).toHaveTextContent("Answered: reject."));
    expect(answers()).toEqual([
      { url: ANSWER_URL, body: { visit_token: GATE.token, outcome: "reject", note: written } },
    ]);
  });

  it("answers each open visit of one gate with its own token", async () => {
    // WHY: a gate over list items waits once per item; one answer settles only its own visit.
    const itemA = { ...GATE, visit_id: "a".repeat(32), token: "approve_change|a|a4:1:1" };
    const itemB = { ...GATE, visit_id: "b".repeat(32), token: "approve_change|b|a4:1:2" };
    authenticatedFetch.mockResolvedValue(jsonResponse(200, { result: "accepted" }));
    renderPanel({
      detail: { ...DETAIL, gates: [itemA, itemB] },
      view: { ...DETAIL.view!, open_gates: [itemA.token, itemB.token] },
    });
    const visits = screen.getAllByTestId("run-gate");
    expect(visits.map((element) => element.dataset.token)).toEqual([itemA.token, itemB.token]);
    fireEvent.click(within(visits[1]!).getByRole("button", { name: "approve" }));
    await waitFor(() =>
      expect(within(visits[1]!).getByRole("status")).toHaveTextContent("Answered: approve."),
    );
    expect(within(visits[0]!).getByRole("button", { name: "approve" })).toBeEnabled();
    expect(answers()).toEqual([
      { url: ANSWER_URL, body: { visit_token: itemB.token, outcome: "approve" } },
    ]);
  });

  it("shows evidence commands and step names as text", () => {
    // WHY: names and commands come from the workflow's YAML; none of it is rendered as HTML.
    const hostile = "Impl‮ement <img src=x onerror=alert(1)>";
    const command = "pytest -q <script>alert(1)</script>";
    const graph = {
      ...CONTRACT_GRAPH,
      nodes: CONTRACT_GRAPH.nodes.map((node) =>
        node.id === "implement"
          ? {
              ...node,
              name: hostile,
              evidence: {
                ...node.evidence!,
                items: [{ ...node.evidence!.items[0]!, run: command }],
              },
            }
          : node,
      ),
    };
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <RunGatePanel
            runId={RUN_ID}
            detail={DETAIL}
            view={DETAIL.view}
            graph={graph}
            selectedNodeId={null}
            focus={null}
            onAnswerSettled={() => {}}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const evidence = within(card()).getByRole("region", { name: "Evidence" });
    expect(evidence).toHaveTextContent(`Checked at ${hostile}`);
    expect(within(evidence).getByTestId("run-gate-check")).toHaveTextContent(
      `${command} · Met at handoff`,
    );
    expect(evidence.querySelector("img, script")).toBeNull();
    // Isolated, so the name's override cannot reorder the fixed words after it.
    expect([...evidence.querySelectorAll("bdi")].map((element) => element.textContent)).toEqual([
      hostile,
      command,
    ]);
  });

  it("focuses the selected node's gate once per request to show it", () => {
    // WHY: "Open run" from the Inbox lands on the gate it named; nothing later takes focus.
    const focus = { nodeId: "approve_change", key: "first" };
    const twoGates = (visit: GateOut) => ({
      detail: { ...DETAIL, gates: [OTHER_GATE, visit] },
      view: { ...DETAIL.view!, open_gates: [OTHER_GATE.token, visit.token] },
      selectedNodeId: "approve_change",
    });
    const gateOf = (nodeId: string) =>
      screen.getAllByTestId("run-gate").find((element) => element.dataset.nodeId === nodeId)!;
    const otherNote = () => within(gateOf("ship")).getByLabelText("Note");
    const { rerender } = renderPanel({ ...twoGates(GATE), focus });
    expect(gateOf("approve_change")).toHaveFocus();
    expect(gateOf("approve_change")).toHaveAttribute("data-token", GATE.token);

    otherNote().focus();
    rerender({ ...twoGates(GATE), focus: { ...focus } });
    expect(otherNote()).toHaveFocus();
    // The gate is asked again while the owner types elsewhere on the page.
    rerender({ ...twoGates(PASS2_GATE), focus: { ...focus } });
    expect(gateOf("approve_change")).toHaveAttribute("data-token", PASS2_GATE.token);
    expect(otherNote()).toHaveFocus();

    rerender({ ...twoGates(PASS2_GATE), focus: { ...focus, key: "again" } });
    expect(gateOf("approve_change")).toHaveFocus();
  });

  it("focuses the gate once its detail arrives", () => {
    // WHY: the page may open on the gate's URL before the detail lists the gate.
    const focus = { nodeId: "approve_change", key: "first" };
    const { rerender } = renderPanel({
      detail: { ...DETAIL, gates: [] },
      selectedNodeId: "approve_change",
      focus,
    });
    expect(screen.queryByTestId("run-gate")).toBeNull();
    rerender({ detail: DETAIL, selectedNodeId: "approve_change", focus });
    expect(screen.getByTestId("run-gate")).toHaveFocus();
  });

  it("spends the request when the linked gate is not open, so a later visit takes no focus", () => {
    // WHY: an old link to a gate already answered must not pull the owner there minutes later.
    const focus = { nodeId: "approve_change", key: "first" };
    const closed = { ...DETAIL.view!, open_gates: [] };
    const { rerender } = renderPanel({ view: closed, selectedNodeId: "approve_change", focus });
    const elsewhere = document.createElement("button");
    document.body.append(elsewhere);
    elsewhere.focus();
    rerender({ selectedNodeId: "approve_change", focus });
    expect(screen.getByTestId("run-gate")).not.toHaveFocus();
    expect(elsewhere).toHaveFocus();
    elsewhere.remove();
  });

  it("hands focus to the run's status when the card holding it closes", () => {
    // WHY: a visit the stream closes takes its card away; focus must not fall to the page body.
    const status = document.createElement("div");
    status.tabIndex = -1;
    document.body.append(status);
    const focusFallback = { current: status };
    const { rerender } = renderPanel({ focusFallback });
    within(card()).getByLabelText("Note").focus();
    rerender({ focusFallback, view: { ...DETAIL.view!, open_gates: [] } });
    expect(screen.queryByTestId("run-gate")).toBeNull();
    expect(status).toHaveFocus();
    status.remove();
  });

  it("leaves focus alone when the card holding it stays", () => {
    // WHY: a re-render that keeps the card must not move the owner's cursor out of the note.
    const status = document.createElement("div");
    status.tabIndex = -1;
    document.body.append(status);
    const focusFallback = { current: status };
    const { rerender } = renderPanel({ focusFallback });
    const note = within(card()).getByLabelText("Note");
    note.focus();
    rerender({ focusFallback, view: { ...DETAIL.view! } });
    expect(note).toHaveFocus();
    status.remove();
  });
});
