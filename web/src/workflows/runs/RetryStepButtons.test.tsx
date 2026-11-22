import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
vi.mock("@/hooks/useViewerId", () => ({ useViewerId: () => "alice" }));

import type { RunDetail, RunSummary } from "../api/generated/coralApi";
import { runQueryKey, runsListPrefixKey } from "../api/runsApi";
import { CONTRACT_DETAIL_GATE_PASS2, CONTRACT_GRAPH } from "../fixtures/runViewContract";
import { isolated, type GraphNodeNames } from "../shared/pauseCopy";
import { coralScope } from "../shared/viewerScope";
import { RETRYING_TEXT, RetryStepButtons, type RetryStepButtonsProps } from "./RetryStepButtons";

const RUN_ID = CONTRACT_DETAIL_GATE_PASS2.run_id;
const IMPLEMENT = "c601458b43d603f0a38687f9fcdf3809";
const APPROVE = "fd21fde5d9f544cb764c4730e596b5f6";
const SLOTS: RetryStepButtonsProps["slots"] = [
  { activation_id: IMPLEMENT, node_id: "implement" },
  { activation_id: APPROVE, node_id: "approve_change" },
];
const RETRY_URL = (activationId: string) =>
  `/v1/coral/runs/${RUN_ID}/activations/${activationId}:retry`;
const RUN_KEY = runQueryKey(coralScope("alice", "/"), RUN_ID);
const RESTARTING: RunSummary = {
  ...CONTRACT_DETAIL_GATE_PASS2,
  status: "paused",
  pause_reason: "infra",
  allowed_actions: ["cancel"],
};

type Answer = Response | (() => Promise<Response>);
// The runs route's message for a retry while a restart stands (`run_service.py`).
const RESTART_IN_PROGRESS_TEXT = "A step of this run is restarting; try again when it is done.";

const wire = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const envelope = (code: string, message: string, details: unknown = null) => ({
  error: { code, message, details },
});

/** Answer every retry post with `answer`, a fresh response each time. */
function serveRetry(answer: Answer) {
  authenticatedFetch.mockImplementation(() =>
    typeof answer === "function" ? answer() : Promise.resolve(answer.clone()),
  );
}

function posts(): [string, unknown][] {
  return authenticatedFetch.mock.calls.map(([url, init]) => [
    url as string,
    JSON.parse((init as RequestInit).body as string) as unknown,
  ]);
}

function tree(props: Partial<RetryStepButtonsProps>, queryClient: QueryClient) {
  return (
    <QueryClientProvider client={queryClient}>
      <RetryStepButtons
        runId={RUN_ID}
        activationIds={[IMPLEMENT]}
        slots={SLOTS}
        graph={CONTRACT_GRAPH}
        restarting={false}
        {...props}
      />
    </QueryClientProvider>
  );
}

function renderButtons(props: Partial<RetryStepButtonsProps> = {}) {
  const queryClient = new QueryClient();
  const view = render(tree(props, queryClient));
  return {
    queryClient,
    rerender: (next: Partial<RetryStepButtonsProps>) => view.rerender(tree(next, queryClient)),
  };
}

const buttonNames = () => screen.queryAllByRole("button").map((button) => button.textContent);
const retryButton = (name: string) => screen.getByRole("button", { name: `Retry ${name}` });
/** The status line; taken before a click, since a pending button's spinner is a status too. */
const statusLine = () => within(screen.getByTestId("run-retry-steps")).getAllByRole("status")[0]!;

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  authenticatedFetch.mockReset();
});

describe("RetryStepButtons", () => {
  it("offers one Retry per failed step, named by its step", () => {
    // WHY: each failed step is restarted on its own, and the owner must see which one.
    renderButtons({ activationIds: [IMPLEMENT, APPROVE] });
    expect(buttonNames()).toEqual([
      `Retry ${isolated("Implement")}`,
      `Retry ${isolated("Approve change")}`,
    ]);
    expect(retryButton(isolated("Implement"))).toHaveAttribute(
      "data-component-id",
      "workflows.run.retry_step",
    );
  });

  it.each<[string, Partial<RetryStepButtonsProps>]>([
    ["no slot names the activation", { activationIds: ["0".repeat(32)] }],
    ["the graph has not loaded", { graph: null }],
    ["the graph lacks the step's node", { graph: { nodes: [] } satisfies GraphNodeNames }],
  ])("calls the step a step when %s", (_name, props) => {
    // WHY: names come only from the graph; an activation id is never shown.
    renderButtons(props);
    expect(buttonNames()).toEqual(["Retry a step"]);
  });

  it("offers a step named twice once", () => {
    // WHY: one step has one Retry, whatever the list repeats.
    renderButtons({ activationIds: [IMPLEMENT, IMPLEMENT] });
    expect(buttonNames()).toEqual([`Retry ${isolated("Implement")}`]);
  });

  it("offers no Retry without ids, keeping only an empty status line", () => {
    // WHY: a run that is held or restarting has no step a Retry may restart; the line stays
    // mounted so a retry that is still answering is announced.
    renderButtons({ activationIds: [] });
    expect(screen.queryByRole("button")).toBeNull();
    expect(statusLine()).toBeEmptyDOMElement();
    expect(statusLine()).toHaveClass("sr-only");
  });

  it("posts an empty body to the step's :retry, says Retrying and refreshes the run", async () => {
    // WHY: the server takes the retry and the run stays paused while it restarts; the page
    // reads the run again for its new causes and steps.
    serveRetry(wire(200, RESTARTING));
    const { queryClient } = renderButtons({ activationIds: [IMPLEMENT, APPROVE] });
    queryClient.setQueryData<RunDetail>(RUN_KEY, {
      ...CONTRACT_DETAIL_GATE_PASS2,
      status: "paused",
      allowed_actions: ["resume", "cancel"],
      retry_activation_ids: [IMPLEMENT, APPROVE],
    });
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const status = statusLine();
    expect(status).toHaveAttribute("aria-live", "polite");
    fireEvent.click(retryButton(isolated("Approve change")));

    await waitFor(() => expect(status).toHaveTextContent(RETRYING_TEXT));
    expect(status).toHaveFocus();
    expect(posts()).toEqual([[RETRY_URL(APPROVE), {}]]);
    const [, init] = authenticatedFetch.mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    // The taken step leaves the cached detail at once; the re-read brings the rest.
    expect(queryClient.getQueryData<RunDetail>(RUN_KEY)).toMatchObject({
      status: "paused",
      allowed_actions: ["cancel"],
      retry_activation_ids: [IMPLEMENT],
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: RUN_KEY });
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: runsListPrefixKey(coralScope("alice", "/")),
    });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["coral-inbox"] });
  });

  it("sends one request per button at a time, and another step's Retry stays usable", async () => {
    // WHY: a second click must not restart the step twice; a different step is its own request.
    serveRetry(() => new Promise<Response>(() => {}));
    renderButtons({ activationIds: [IMPLEMENT, APPROVE] });
    const implement = retryButton(isolated("Implement"));
    fireEvent.click(implement);
    fireEvent.click(implement);
    expect(implement).toBeDisabled();
    expect(implement).toHaveAttribute("aria-busy", "true");
    const approve = retryButton(isolated("Approve change"));
    expect(approve).toBeEnabled();
    fireEvent.click(approve);
    await waitFor(() =>
      expect(posts()).toEqual([
        [RETRY_URL(IMPLEMENT), {}],
        [RETRY_URL(APPROVE), {}],
      ]),
    );
  });

  it("keeps a sent request's button disabled when the banner is shown again", async () => {
    // WHY: the banner can unmount while a retry is in flight; a fresh one must not send another.
    serveRetry(() => new Promise<Response>(() => {}));
    const { rerender } = renderButtons();
    fireEvent.click(retryButton(isolated("Implement")));
    await waitFor(() => expect(posts()).toHaveLength(1));
    rerender({ activationIds: [] });
    rerender({ activationIds: [IMPLEMENT] });
    // Its spinner's label joins its name while it is busy.
    const again = screen.getByRole("button");
    expect(again).toHaveTextContent(`Retry ${isolated("Implement")}`);
    expect(again).toBeDisabled();
    fireEvent.click(again);
    expect(posts()).toHaveLength(1);
  });

  it("shows a conflict's own message and rereads only the run", async () => {
    // WHY: a 409 says why the step cannot be retried now, in the server's words.
    serveRetry(
      wire(
        409,
        envelope("illegal_transition", RESTART_IN_PROGRESS_TEXT, {
          status: "paused",
          pause_reason: "infra",
          reason: "restart_in_progress",
        }),
      ),
    );
    const { queryClient } = renderButtons();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const status = statusLine();
    fireEvent.click(retryButton(isolated("Implement")));
    await waitFor(() => expect(status).toHaveTextContent(RESTART_IN_PROGRESS_TEXT));
    expect(status).toHaveFocus();
    expect(within(status).getByText(RESTART_IN_PROGRESS_TEXT)).toHaveClass("text-destructive");
    expect(invalidate).toHaveBeenCalledWith({ queryKey: RUN_KEY });
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: ["coral-inbox"] });
    expect(retryButton(isolated("Implement"))).toBeEnabled();
  });

  it.each<[string, Answer, string]>([
    [
      "a 404",
      wire(404, envelope("not_found", "Run not found.")),
      "This run is no longer available.",
    ],
    [
      "a 503",
      wire(503, envelope("server_busy", "The server is busy; try again.")),
      "The server is busy; try again.",
    ],
    ["a 422", wire(422, envelope("validation_failed", "Bad id.")), "Couldn’t update the run."],
    [
      "a network failure",
      () => Promise.reject(new TypeError("Failed to fetch")),
      "Couldn’t update the run.",
    ],
  ])("shows %s in the run actions' words", async (_name, answer, text) => {
    // WHY: a failed retry reads like any other failed run action, and can be tried again.
    serveRetry(answer);
    renderButtons();
    const status = statusLine();
    fireEvent.click(retryButton(isolated("Implement")));
    await waitFor(() => expect(status).toHaveTextContent(text));
    expect(retryButton(isolated("Implement"))).toBeEnabled();
  });

  it("announces the same refusal again on a second try", async () => {
    // WHY: the line is cleared when a request starts, so a repeat is read out again.
    serveRetry(wire(409, envelope("illegal_transition", "This step cannot be retried now.")));
    renderButtons();
    const status = statusLine();
    fireEvent.click(retryButton(isolated("Implement")));
    await waitFor(() => expect(status).toHaveTextContent("This step cannot be retried now."));
    fireEvent.click(retryButton(isolated("Implement")));
    expect(status).toBeEmptyDOMElement();
    await waitFor(() => expect(status).toHaveTextContent("This step cannot be retried now."));
    expect(posts()).toHaveLength(2);
  });

  it("keeps the result once the detail stops offering the step, until a new offer", async () => {
    // WHY: after a retry the detail names no step, but the owner still sees what happened;
    // when a restart fails and the step is offered again, the old result no longer applies.
    serveRetry(wire(200, RESTARTING));
    const { rerender } = renderButtons();
    fireEvent.click(retryButton(isolated("Implement")));
    await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
    rerender({ activationIds: [] });
    expect(statusLine()).toHaveTextContent(RETRYING_TEXT);
    expect(screen.queryByRole("button")).toBeNull();
    rerender({ activationIds: [IMPLEMENT] });
    expect(statusLine()).toBeEmptyDOMElement();
    expect(retryButton(isolated("Implement"))).toBeEnabled();
  });

  it("clears the result once the restart it reported ends", async () => {
    // WHY: a run can stay paused for another cause after the restart; "Retrying." would then
    // describe a restart that is over.
    serveRetry(wire(200, RESTARTING));
    const { rerender } = renderButtons();
    fireEvent.click(retryButton(isolated("Implement")));
    await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
    rerender({ activationIds: [], restarting: true });
    expect(statusLine()).toHaveTextContent(RETRYING_TEXT);
    rerender({ activationIds: [], restarting: false });
    expect(statusLine()).toBeEmptyDOMElement();
  });

  it("disables Retry while the browser is offline", async () => {
    // WHY: a request that cannot be sent must not look sent.
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderButtons();
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
    });
    const retry = retryButton(isolated("Implement"));
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });
});

/** Hold each retry post until the test settles it, by the step it retries. */
function holdRetries() {
  const held = new Map<
    string,
    { resolve: (answer: Response) => void; reject: (error: unknown) => void }
  >();
  authenticatedFetch.mockImplementation(
    (url: string) =>
      new Promise<Response>((resolve, reject) => {
        held.set(url, { resolve, reject });
      }),
  );
  /** The step's post, once the mutation has sent it. */
  const sent = async (activationId: string) => {
    await waitFor(() => expect(held.has(RETRY_URL(activationId))).toBe(true));
    return held.get(RETRY_URL(activationId))!;
  };
  return {
    succeed: async (activationId: string, answer: Response) => {
      const post = await sent(activationId);
      await act(async () => post.resolve(answer));
    },
    fail: async (activationId: string, error: unknown) => {
      const post = await sent(activationId);
      await act(async () => post.reject(error));
    },
  };
}

describe("RetryStepButtons under concurrent clicks and odd input", () => {
  const IMPLEMENT_NAME = isolated("Implement");
  const APPROVE_NAME = isolated("Approve change");

  it("retries two failed steps on their own: a click disables only its own button", async () => {
    // WHY: each failed step restarts by itself; one in flight must not block or settle the other.
    const held = holdRetries();
    const { queryClient } = renderButtons({ activationIds: [IMPLEMENT, APPROVE] });
    const implement = retryButton(IMPLEMENT_NAME);
    const approve = retryButton(APPROVE_NAME);
    const status = statusLine();

    fireEvent.click(implement);
    expect(implement).toBeDisabled();
    expect(approve).toBeEnabled();
    fireEvent.click(approve);
    expect(approve).toBeDisabled();

    await held.succeed(APPROVE, wire(200, RESTARTING));
    await waitFor(() => expect(status).toHaveTextContent(RETRYING_TEXT));
    // A taken retry keeps its button disabled until the detail stops offering the step.
    expect(approve).toBeDisabled();
    expect(approve).not.toHaveAttribute("aria-busy");
    expect(implement).toHaveAttribute("aria-busy", "true");

    await held.succeed(IMPLEMENT, wire(200, RESTARTING));
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(implement).toBeDisabled();
    expect(status).toHaveTextContent(RETRYING_TEXT);
    expect(posts()).toEqual([
      [RETRY_URL(IMPLEMENT), {}],
      [RETRY_URL(APPROVE), {}],
    ]);
  });

  it("shows the latest answer when one step's retry is taken and the other's refused", async () => {
    // WHY: the server lets one restart run at a time, so the second step's 409 is the news.
    const held = holdRetries();
    renderButtons({ activationIds: [IMPLEMENT, APPROVE] });
    const status = statusLine();
    fireEvent.click(retryButton(IMPLEMENT_NAME));
    fireEvent.click(retryButton(APPROVE_NAME));
    await held.succeed(IMPLEMENT, wire(200, RESTARTING));
    await waitFor(() => expect(status).toHaveTextContent(RETRYING_TEXT));
    const refusal = "A step of this run is restarting; try again when it is done.";
    await held.succeed(
      APPROVE,
      wire(409, envelope("illegal_transition", refusal, { reason: "restart_in_progress" })),
    );
    await waitFor(() => expect(status).toHaveTextContent(refusal));
    expect(within(status).getByText(refusal)).toHaveClass("text-destructive");
    expect(posts()).toHaveLength(2);
  });

  it("sends one POST for a double click while the first is in flight", async () => {
    // WHY: a double click must not restart the step twice.
    serveRetry(() => new Promise<Response>(() => {}));
    renderButtons();
    await userEvent.setup().dblClick(retryButton(IMPLEMENT_NAME));
    expect(posts()).toEqual([[RETRY_URL(IMPLEMENT), {}]]);
  });

  it("sends one POST per click under StrictMode", async () => {
    // WHY: development's double render and effects must not send a retry twice.
    serveRetry(wire(200, RESTARTING));
    render(<StrictMode>{tree({}, new QueryClient())}</StrictMode>);
    fireEvent.click(retryButton(IMPLEMENT_NAME));
    await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
    expect(posts()).toEqual([[RETRY_URL(IMPLEMENT), {}]]);
  });

  it("keeps a taken retry's button disabled until the detail stops offering the step", async () => {
    // WHY: the detail offers the step until it is read again, so a double click whose first
    // answer is quick must not send a second POST, whose 409 would replace "Retrying.".
    serveRetry(wire(200, RESTARTING));
    const { queryClient, rerender } = renderButtons();
    const retry = retryButton(IMPLEMENT_NAME);
    fireEvent.click(retry);
    await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    // The detail still offers the step: it has not been read again yet.
    expect(retry).toBeDisabled();
    fireEvent.click(retry);
    expect(posts()).toHaveLength(1);
    // A new offer is a new button.
    rerender({ activationIds: [] });
    rerender({ activationIds: [IMPLEMENT] });
    expect(retryButton(IMPLEMENT_NAME)).toBeEnabled();
  });

  it.each<[string, Response | Error, string]>([
    [
      "a 409 retry_not_allowed",
      wire(
        409,
        envelope("illegal_transition", "This step cannot be retried now.", {
          reason: "retry_not_allowed",
        }),
      ),
      "This step cannot be retried now.",
    ],
    [
      "a 409 host_offline_hold",
      wire(
        409,
        envelope(
          "illegal_transition",
          "The run's machine is offline; steps can be retried once it is back.",
          { reason: "host_offline_hold" },
        ),
      ),
      "The run's machine is offline; steps can be retried once it is back.",
    ],
    [
      "a 409 whose message looks like markup",
      wire(409, envelope("illegal_transition", "<b>no</b> & <img src=x>")),
      "<b>no</b> & <img src=x>",
    ],
    [
      "a 409 without Coral's envelope",
      wire(409, { detail: "Conflict" }),
      "Couldn’t update the run.",
    ],
    [
      "a 422",
      wire(422, envelope("validation_failed", "activation_id: bad")),
      "Couldn’t update the run.",
    ],
    [
      "a 404",
      wire(404, envelope("not_found", "Run not found.")),
      "This run is no longer available.",
    ],
    ["a 503", wire(503, envelope("server_busy", "Busy.")), "The server is busy; try again."],
    ["a 500", wire(500, {}), "Couldn’t update the run."],
    ["a network failure", new TypeError("Failed to fetch"), "Couldn’t update the run."],
  ])("shows %s as text and leaves both steps' Retry usable", async (_name, answer, text) => {
    // WHY: a refusal reads like any other failed run action, and neither step is stuck.
    const held = holdRetries();
    const { container } = render(tree({ activationIds: [IMPLEMENT, APPROVE] }, new QueryClient()));
    const status = statusLine();
    const implement = retryButton(IMPLEMENT_NAME);
    fireEvent.click(implement);
    await (answer instanceof Error
      ? held.fail(IMPLEMENT, answer)
      : held.succeed(IMPLEMENT, answer));
    await waitFor(() => expect(status).toHaveTextContent(text));
    expect(within(status).getByText(text)).toHaveClass("text-destructive");
    expect(container.querySelector("img, b")).toBeNull();
    expect(implement).toBeEnabled();
    expect(retryButton(APPROVE_NAME)).toBeEnabled();
  });

  it("keeps both steps' Retry disabled offline and usable again once back online", async () => {
    // WHY: nothing is sent while offline, and the owner can retry as soon as the network returns.
    const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    renderButtons({ activationIds: [IMPLEMENT, APPROVE] });
    await act(async () => {
      window.dispatchEvent(new Event("offline"));
    });
    for (const name of [IMPLEMENT_NAME, APPROVE_NAME]) {
      expect(retryButton(name)).toBeDisabled();
      fireEvent.click(retryButton(name));
    }
    expect(authenticatedFetch).not.toHaveBeenCalled();
    online.mockReturnValue(true);
    serveRetry(wire(200, RESTARTING));
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });
    fireEvent.click(retryButton(APPROVE_NAME));
    await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
    expect(posts()).toEqual([[RETRY_URL(APPROVE), {}]]);
  });

  it.each<[string, Response, string]>([
    ["taken", wire(200, RESTARTING), RETRYING_TEXT],
    [
      "refused",
      wire(409, envelope("illegal_transition", RESTART_IN_PROGRESS_TEXT)),
      RESTART_IN_PROGRESS_TEXT,
    ],
  ])(
    "still says how a retry went when the ids go away while it is in flight and it is %s",
    async (_name, answer, text) => {
      // WHY: the stream can show the restart, and the detail drop the step, before the POST
      // answers; the banner's line still announces the answer, and a later offer starts clean.
      const errors = vi.spyOn(console, "error");
      const held = holdRetries();
      const { queryClient, rerender } = renderButtons();
      const invalidate = vi.spyOn(queryClient, "invalidateQueries");
      const status = statusLine();
      fireEvent.click(retryButton(IMPLEMENT_NAME));
      rerender({ activationIds: [] });
      expect(screen.queryByRole("button")).toBeNull();
      expect(status).toBeEmptyDOMElement();
      await held.succeed(IMPLEMENT, answer);
      await waitFor(() => expect(queryClient.isMutating()).toBe(0));
      expect(statusLine()).toBe(status);
      expect(status).toHaveTextContent(text);
      expect(status).toHaveFocus();
      // The run is still read again, though the button that sent it is gone.
      expect(invalidate).toHaveBeenCalledWith({ queryKey: RUN_KEY });
      rerender({ activationIds: [IMPLEMENT] });
      expect(statusLine()).toBeEmptyDOMElement();
      expect(retryButton(IMPLEMENT_NAME)).toBeEnabled();
      expect(errors).not.toHaveBeenCalled();
      expect(posts()).toHaveLength(1);
    },
  );

  it("announces a late result without pulling focus from elsewhere on the page", async () => {
    // WHY: the person may have moved on while the retry was in flight.
    const held = holdRetries();
    const { rerender } = renderButtons();
    const elsewhere = document.body.appendChild(document.createElement("input"));
    try {
      fireEvent.click(retryButton(IMPLEMENT_NAME));
      rerender({ activationIds: [] });
      elsewhere.focus();
      await held.succeed(IMPLEMENT, wire(200, RESTARTING));
      await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
      expect(elsewhere).toHaveFocus();
    } finally {
      elsewhere.remove();
    }
  });

  it("shows a refusal that lands after its step was dropped and offered again", async () => {
    // WHY: a new offer clears the old result, but the answer that lands after it is news.
    const held = holdRetries();
    const { rerender } = renderButtons();
    const status = statusLine();
    fireEvent.click(retryButton(IMPLEMENT_NAME));
    rerender({ activationIds: [] });
    rerender({ activationIds: [IMPLEMENT] });
    await held.succeed(
      IMPLEMENT,
      wire(409, envelope("illegal_transition", "This step cannot be retried now.")),
    );
    await waitFor(() => expect(status).toHaveTextContent("This step cannot be retried now."));
    expect(retryButton(IMPLEMENT_NAME)).toBeEnabled();
  });

  it("keeps an answer that lands after its banner went out of a later banner's line", async () => {
    // WHY: the run can go on and pause again while a retry answers; the answer belongs to the
    // banner that sent it, never to the next pause's.
    const errors = vi.spyOn(console, "error");
    const held = holdRetries();
    const queryClient = new QueryClient();
    const view = render(tree({}, queryClient));
    fireEvent.click(retryButton(IMPLEMENT_NAME));
    view.rerender(<QueryClientProvider client={queryClient}>{null}</QueryClientProvider>);
    view.rerender(tree({ activationIds: [] }, queryClient));
    const status = statusLine();
    await held.succeed(IMPLEMENT, wire(200, RESTARTING));
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    expect(status).toBeEmptyDOMElement();
    expect(status).not.toHaveFocus();
    expect(errors).not.toHaveBeenCalled();
  });

  it("keeps an activation id with reserved characters to one encoded path segment", async () => {
    // WHY: the id is the server's, but a bad one must never reach another route.
    const odd = "a b/../c?d=1#e%f$&é";
    serveRetry(wire(200, RESTARTING));
    renderButtons({
      activationIds: [odd],
      slots: [{ activation_id: odd, node_id: "implement" }],
    });
    fireEvent.click(retryButton(IMPLEMENT_NAME));
    await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
    expect(posts()).toEqual([
      [`/v1/coral/runs/${RUN_ID}/activations/a%20b%2F..%2Fc%3Fd%3D1%23e%25f%24%26%C3%A9:retry`, {}],
    ]);
  });

  it("renders a step name that looks like markup as text", () => {
    // WHY: a workflow author's step name is data, never markup.
    const name = '<img src=x onerror="alert(1)">Fix</b>';
    const { container } = render(
      tree({ graph: { nodes: [{ id: "implement", name }] } }, new QueryClient()),
    );
    expect(buttonNames()).toEqual([`Retry ${isolated(name)}`]);
    expect(container.querySelector("img, b")).toBeNull();
  });

  it("gives two activations of one step the same label, each posting its own id", async () => {
    // WHY: activations of one node share its name; each Retry must still restart only its
    // own activation, though the labels alone do not tell them apart.
    const secondItem = "9".repeat(32);
    serveRetry(wire(200, RESTARTING));
    renderButtons({
      activationIds: [IMPLEMENT, secondItem],
      slots: [...SLOTS, { activation_id: secondItem, node_id: "implement" }],
    });
    expect(buttonNames()).toEqual([`Retry ${IMPLEMENT_NAME}`, `Retry ${IMPLEMENT_NAME}`]);
    fireEvent.click(screen.getAllByRole("button")[1]!);
    await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
    expect(posts()).toEqual([[RETRY_URL(secondItem), {}]]);
  });

  it("names the steps it can and calls the rest a step, each posting its own id", async () => {
    // WHY: an unnamed step still restarts; the owner tells it apart by the named ones.
    const unknown = "f".repeat(32);
    serveRetry(wire(200, RESTARTING));
    renderButtons({
      activationIds: [unknown, IMPLEMENT],
      slots: [...SLOTS, { activation_id: unknown, node_id: "gone" }],
    });
    expect(buttonNames()).toEqual(["Retry a step", `Retry ${IMPLEMENT_NAME}`]);
    fireEvent.click(retryButton("a step"));
    await waitFor(() => expect(statusLine()).toHaveTextContent(RETRYING_TEXT));
    expect(posts()).toEqual([[RETRY_URL(unknown), {}]]);
  });
});
