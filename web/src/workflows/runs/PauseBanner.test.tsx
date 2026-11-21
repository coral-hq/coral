import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
vi.mock("@/hooks/useViewerId", () => ({ useViewerId: () => "alice" }));

import type { PauseCause, RunView } from "../api/generated/coralApi";
import { CONTRACT_DETAIL_GATE_PASS2, CONTRACT_GRAPH } from "../fixtures/runViewContract";
import { isolated, PAUSE_MESSAGES, type GraphNodeNames } from "../shared/pauseCopy";
import { PauseBanner, type PauseBannerProps } from "./PauseBanner";

const OPEN_VIEW = CONTRACT_DETAIL_GATE_PASS2.view!;
const USER_CAUSE: PauseCause = { reason: "user", detail: "", subject: "" };
// The recording's graph, plus a decision the orchestrator answers.
const GRAPH: GraphNodeNames = {
  nodes: [...CONTRACT_GRAPH.nodes, { id: "choose", name: "Choose path" }],
};

function pausedView(changes: Partial<RunView> = {}): RunView {
  return { ...OPEN_VIEW, status: "paused", causes: [USER_CAUSE], ...changes };
}

const RUN_ID = CONTRACT_DETAIL_GATE_PASS2.run_id;
// The recording's two implement slots, as the detail lists them.
const PASS_1 = CONTRACT_DETAIL_GATE_PASS2.slots[0]!;
const PASS_2 = CONTRACT_DETAIL_GATE_PASS2.slots[1]!;
const PASS_2_SLOT = OPEN_VIEW.slots[1]!.id;

function renderBanner(
  reason: string | null,
  view: RunView | null,
  graph: GraphNodeNames | null = GRAPH,
  retry: Pick<PauseBannerProps, "retryActivationIds" | "slots"> = {
    retryActivationIds: [],
    slots: CONTRACT_DETAIL_GATE_PASS2.slots,
  },
) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <PauseBanner reason={reason} view={view} graph={graph} runId={RUN_ID} {...retry} />
    </QueryClientProvider>,
  );
}

const items = () =>
  within(screen.getByRole("region"))
    .queryAllByRole("listitem")
    .map((item) => item.textContent);

afterEach(() => {
  cleanup();
  authenticatedFetch.mockReset();
});

describe("PauseBanner", () => {
  it("names a pause the owner made and says so", () => {
    // WHY: the recorded run is paused by its owner with the gate still open.
    renderBanner("user", pausedView());
    const banner = screen.getByRole("region", { name: "Paused: by you" });
    expect(banner).toHaveTextContent("The run paused.");
    expect(items()).toEqual([]);
  });

  it("explains the first cause and lists every other one", () => {
    // WHY: a run paused for several reasons needs each one cleared before it resumes.
    const causes: PauseCause[] = [
      { reason: "plan_limit", detail: "", subject: "implement||a4:2:0" },
      { reason: "budget", detail: "", subject: "" },
      { reason: "drift", detail: "anchor_archived", subject: "" },
    ];
    renderBanner("plan_limit", pausedView({ causes }));
    const banner = screen.getByRole("region", { name: "Paused: plan limit" });
    expect(banner).toHaveTextContent(`${PAUSE_MESSAGES.plan_limit} Coral retries periodically.`);
    expect(items()).toEqual([
      PAUSE_MESSAGES.budget,
      "The run’s session was archived. Unarchive it to continue, or cancel.",
    ]);
  });

  it("lists each cause once, even when two read alike", () => {
    // WHY: two refused-call causes on different steps say the same thing.
    const causes: PauseCause[] = [
      { reason: "budget", detail: "", subject: "" },
      { reason: "rejected_calls", detail: "", subject: "a" },
      { reason: "rejected_calls", detail: "", subject: "b" },
    ];
    renderBanner("budget", pausedView({ causes }));
    expect(items()).toEqual([PAUSE_MESSAGES.rejected_calls]);
  });

  it("names a step someone typed into and a step whose session changed", () => {
    // WHY: those steps need the owner's attention before the run can go on.
    const slots = [
      { ...OPEN_VIEW.slots[0]!, pending_input: true },
      { ...OPEN_VIEW.slots[1]!, drift: true },
    ];
    renderBanner("user", pausedView({ slots }));
    expect(items()).toEqual([
      `Someone typed into ${isolated("Implement")}’s session.`,
      `${isolated("Implement")}’s session was changed outside Coral.`,
    ]);
  });

  it("says a typed-into step once when a cause already names its slot", () => {
    // WHY: the cause's sentence and the slot's flag describe the same event.
    const slot = OPEN_VIEW.slots[1]!;
    const cause: PauseCause = { reason: "drift", detail: "pending_input", subject: slot.id };
    const slots = [
      { ...OPEN_VIEW.slots[0]!, pending_input: true },
      { ...slot, pending_input: true },
    ];
    renderBanner("drift", pausedView({ causes: [USER_CAUSE, cause], slots }));
    expect(items()).toEqual([
      `Someone typed into ${isolated("Implement")}’s session while Coral was finishing it.`,
      `Someone typed into ${isolated("Implement")}’s session.`,
    ]);
  });

  it("names the decisions the orchestrator still has to make", () => {
    // WHY: an open decision is the run waiting on its orchestrator, not stuck.
    renderBanner("user", pausedView({ open_decisions: ["choose||", "pick||x|0"] }));
    expect(items()).toEqual([
      `Waiting for the orchestrator to choose at ${isolated("Choose path")}.`,
      `Waiting for the orchestrator to choose at ${isolated("pick")}.`,
    ]);
  });

  it("speaks of a step plainly while the graph has not loaded", () => {
    // WHY: step names come only from the graph; the banner never shows a slot id.
    const slots = [{ ...OPEN_VIEW.slots[0]!, pending_input: true }];
    renderBanner("user", pausedView({ slots }), null);
    expect(items()).toEqual(["Someone typed into a step’s session."]);
  });

  it("explains a pause by the run's reason when the view has no causes", () => {
    // WHY: a paused header can arrive before the view that carries its causes.
    renderBanner("infra", null);
    const banner = screen.getByRole("region", { name: "Paused: infrastructure" });
    expect(banner).toHaveTextContent(PAUSE_MESSAGES.infra);
  });

  it("offers a Retry for each step the detail names, after what the run waits on", () => {
    // WHY: a failed step is restarted from the banner that explains why it stopped.
    const causes: PauseCause[] = [
      { reason: "failure_path", detail: "blocked", subject: PASS_2_SLOT },
      { reason: "failure_path", detail: "restart:workspace.tree_changed", subject: "x||:0" },
    ];
    renderBanner("failure_path", pausedView({ causes }), GRAPH, {
      retryActivationIds: [PASS_2.activation_id, "0".repeat(32)],
      slots: [PASS_1, PASS_2],
    });
    const banner = screen.getByRole("region", { name: "Paused: step failed" });
    expect(within(banner).getByText(/reported that it is blocked/)).toHaveTextContent(
      `${isolated("Implement")} reported that it is blocked. Retry restarts it from its last handoff.`,
    );
    expect(items()).toEqual(["Coral couldn’t restart a step. Retry tries again."]);
    const retries = within(banner).getByTestId("run-retry-steps");
    expect(
      within(retries)
        .getAllByRole("button")
        .map((element) => element.textContent),
    ).toEqual([`Retry ${isolated("Implement")}`, "Retry a step"]);
  });

  it("posts a step's retry from the banner and says so", async () => {
    // WHY: the banner's Retry is the owner's way out of a failed step.
    authenticatedFetch.mockResolvedValue(
      new Response(
        JSON.stringify({ ...CONTRACT_DETAIL_GATE_PASS2, status: "paused", pause_reason: "infra" }),
        { status: 200 },
      ),
    );
    const causes: PauseCause[] = [
      { reason: "failure_path", detail: "restart:workspace.head_moved", subject: PASS_2_SLOT },
    ];
    renderBanner("failure_path", pausedView({ causes }), GRAPH, {
      retryActivationIds: [PASS_2.activation_id],
      slots: [PASS_1, PASS_2],
    });
    const banner = screen.getByRole("region", { name: "Paused: step failed" });
    expect(banner).toHaveTextContent(
      `The run’s branch moved outside Coral, so ${isolated("Implement")} was not restarted. ` +
        "Reset the branch to the commit of its last handoff, then retry; or cancel the run.",
    );
    const status = within(within(banner).getByTestId("run-retry-steps")).getByRole("status");
    fireEvent.click(within(banner).getByRole("button", { name: `Retry ${isolated("Implement")}` }));
    await waitFor(() => expect(status).toHaveTextContent("Retrying."));
    expect(authenticatedFetch.mock.calls.map(([url]) => url)).toEqual([
      `/v1/coral/runs/${RUN_ID}/activations/${PASS_2.activation_id}:retry`,
    ]);
  });

  it("offers no Retry while the detail names no step", () => {
    // WHY: a held or restarting run can only be cancelled; its banner says why instead.
    const causes: PauseCause[] = [
      { reason: "infra", detail: "infra.host_offline", subject: PASS_2_SLOT },
    ];
    renderBanner("infra", pausedView({ causes }));
    const banner = screen.getByRole("region", { name: "Paused: infrastructure" });
    expect(banner).toHaveTextContent(
      `Your machine went offline. Coral will continue ${isolated("Implement")} when it’s back.`,
    );
    expect(within(banner).queryByRole("button")).toBeNull();
    expect(
      within(within(banner).getByTestId("run-retry-steps")).getByRole("status"),
    ).toBeEmptyDOMElement();
  });

  it("drops a taken retry's result once its restart ends, though the run stays paused", async () => {
    // WHY: the run can stay paused for another cause after the restart; "Retrying." would then
    // describe a restart that is over.
    authenticatedFetch.mockResolvedValue(
      new Response(
        JSON.stringify({ ...CONTRACT_DETAIL_GATE_PASS2, status: "paused", pause_reason: "infra" }),
        { status: 200 },
      ),
    );
    const queryClient = new QueryClient();
    const failed: PauseCause = {
      reason: "failure_path",
      detail: "restart:workspace.tree_changed",
      subject: PASS_2_SLOT,
    };
    const restarting: PauseCause = {
      reason: "infra",
      detail: "recovery.restarting",
      subject: PASS_2_SLOT,
    };
    const banner = (causes: PauseCause[], ids: string[]) => (
      <QueryClientProvider client={queryClient}>
        <PauseBanner
          reason={causes[0]!.reason}
          view={pausedView({ causes })}
          graph={GRAPH}
          runId={RUN_ID}
          retryActivationIds={ids}
          slots={[PASS_1, PASS_2]}
        />
      </QueryClientProvider>
    );
    const { rerender } = render(banner([failed], [PASS_2.activation_id]));
    const status = within(screen.getByTestId("run-retry-steps")).getByRole("status");
    fireEvent.click(screen.getByRole("button", { name: `Retry ${isolated("Implement")}` }));
    await waitFor(() => expect(status).toHaveTextContent("Retrying."));
    rerender(banner([restarting], []));
    expect(status).toHaveTextContent("Retrying.");
    rerender(banner([USER_CAUSE], []));
    expect(screen.getByRole("region", { name: "Paused: by you" })).toBeInTheDocument();
    expect(status).toBeEmptyDOMElement();
  });

  it("says only Paused for a reason this client cannot name", () => {
    // WHY: a newer server's reason must not show as a raw code.
    renderBanner("solar_flare", pausedView({ causes: [] }));
    expect(screen.getByRole("region", { name: "Paused" })).toHaveTextContent("The run paused.");
  });
});

describe("PauseBanner for each SES-06 cause", () => {
  const STEP = isolated("Implement");
  const TITLES: Record<string, string> = {
    infra: "Paused: infrastructure",
    failure_path: "Paused: step failed",
  };
  const offline =
    "Your machine went offline before " + STEP + " could restart. Retry when it’s back.";
  // [cause reason, detail, subject, body, whether the detail offers the step a Retry]
  const ROWS: [PauseCause["reason"], string, string, string, boolean][] = [
    [
      "infra",
      "infra.host_offline",
      PASS_2_SLOT,
      `Your machine went offline. Coral will continue ${STEP} when it’s back.`,
      false,
    ],
    [
      "infra",
      "recovery.restarting",
      PASS_2_SLOT,
      `Coral is restarting ${STEP} from its last handoff.`,
      false,
    ],
    [
      "infra",
      "infra.runner_lost",
      PASS_2_SLOT,
      `${STEP} keeps losing its runner. Resume tries again; Retry restarts it from its last handoff.`,
      true,
    ],
    [
      "infra",
      "recovery.runner_alive",
      PASS_2_SLOT,
      `${STEP}’s runner is running but can’t reach Coral. Resume tries again.`,
      true,
    ],
    ["failure_path", "restart:dispatch.stop_unconfirmed", PASS_2_SLOT, offline, true],
    ["failure_path", "restart:session.host_offline", PASS_2_SLOT, offline, true],
    ["failure_path", "restart:workspace.backend_unavailable", PASS_2_SLOT, offline, true],
    [
      "failure_path",
      "restart:workspace.head_moved",
      PASS_2_SLOT,
      `The run’s branch moved outside Coral, so ${STEP} was not restarted. ` +
        "Reset the branch to the commit of its last handoff, then retry; or cancel the run.",
      true,
    ],
    [
      "failure_path",
      "restart:workspace.tree_changed",
      PASS_2_SLOT,
      `Coral couldn’t restart ${STEP}. Retry tries again.`,
      true,
    ],
    [
      "failure_path",
      "session.host_unsupported",
      PASS_2_SLOT,
      `${STEP}’s machine can’t run Coral steps. Update Coral there, then retry.`,
      true,
    ],
    [
      "failure_path",
      "blocked",
      PASS_2_SLOT,
      `${STEP} reported that it is blocked. Retry restarts it from its last handoff.`,
      true,
    ],
    [
      "failure_path",
      "attempts_exhausted:pytest -q, ruff check",
      PASS_2_SLOT,
      `Missing evidence: ${isolated("pytest -q, ruff check")}.`,
      true,
    ],
    [
      "failure_path",
      "attempts_exhausted",
      "pytest -q, ruff check",
      `Missing evidence: ${isolated("pytest -q, ruff check")}.`,
      false,
    ],
    [
      "failure_path",
      "session.closed",
      PASS_2_SLOT,
      `${STEP}’s session was closed, so it can’t go on. Retry starts it again from its last handoff.`,
      true,
    ],
    [
      "infra",
      "session.runner_status_unknown",
      PASS_2_SLOT,
      `Coral couldn’t check ${STEP}’s runner on your machine. Resume tries again.`,
      true,
    ],
    ...[
      "session.not_bound",
      "session.host_not_permitted",
      "session.deleted",
      "slot.generation_mismatch",
    ].map((code): [PauseCause["reason"], string, string, string, boolean] => [
      "failure_path",
      code,
      PASS_2_SLOT,
      PAUSE_MESSAGES.failure_path,
      true,
    ]),
    ["infra", "run.contended", PASS_2_SLOT, PAUSE_MESSAGES.infra, true],
  ];

  /** `body` as it reads when the graph cannot name the step. */
  const unnamed = (body: string) => {
    const text = body.replaceAll(STEP, "a step");
    return text.startsWith("a step") ? `A${text.slice(1)}` : text;
  };

  /** The banner's own body: the paragraph after its title. */
  const bodyText = (banner: HTMLElement) => banner.querySelector("h2 + p")?.textContent ?? null;

  it.each(ROWS)(
    "says what %s / %s on %s means and offers Retry as the detail does",
    (reason, detail, subject, body, offered) => {
      // WHY: the full banner, not only its copy, explains a held, restarting or failed step
      // once, and offers a Retry exactly when the detail names the step.
      const view = pausedView({ causes: [{ reason, detail, subject }] });
      const retry = {
        retryActivationIds: offered ? [PASS_2.activation_id] : [],
        slots: [PASS_1, PASS_2],
      };
      const { rerender } = renderBanner(reason, view, GRAPH, retry);
      const banner = screen.getByRole("region", { name: TITLES[reason] });
      expect(bodyText(banner)).toBe(body);
      expect(items()).toEqual([]);
      const buttons = () =>
        within(banner)
          .queryAllByRole("button")
          .map((element) => element.textContent);
      expect(buttons()).toEqual(offered ? [`Retry ${STEP}`] : []);

      rerender(
        <QueryClientProvider client={new QueryClient()}>
          <PauseBanner reason={reason} view={view} graph={null} runId={RUN_ID} {...retry} />
        </QueryClientProvider>,
      );
      expect(bodyText(banner)).toBe(unnamed(body));
      expect(buttons()).toEqual(offered ? ["Retry a step"] : []);
    },
  );

  const REVIEW_SLOT = "review||:0";
  const REVIEW = { ...PASS_2, activation_id: "e".repeat(32), node_id: "review" };
  const TWO_STEPS: GraphNodeNames = { nodes: [...GRAPH.nodes, { id: "review", name: "Review" }] };

  it("explains two failed steps and offers a Retry for each, in cause order", () => {
    // WHY: each failed step is restarted on its own, from the banner that names both.
    const causes: PauseCause[] = [
      { reason: "failure_path", detail: "blocked", subject: PASS_2_SLOT },
      { reason: "failure_path", detail: "session.host_unsupported", subject: REVIEW_SLOT },
    ];
    renderBanner("failure_path", pausedView({ causes }), TWO_STEPS, {
      retryActivationIds: [PASS_2.activation_id, REVIEW.activation_id],
      slots: [PASS_1, PASS_2, REVIEW],
    });
    const banner = screen.getByRole("region", { name: "Paused: step failed" });
    expect(bodyText(banner)).toBe(
      `${STEP} reported that it is blocked. Retry restarts it from its last handoff.`,
    );
    expect(items()).toEqual([
      `${isolated("Review")}’s machine can’t run Coral steps. Update Coral there, then retry.`,
    ]);
    expect(
      within(banner)
        .getAllByRole("button")
        .map((element) => element.textContent),
    ).toEqual([`Retry ${STEP}`, `Retry ${isolated("Review")}`]);
  });

  it("offers no Retry while one of two failed steps restarts, and names both", () => {
    // WHY: one restart runs at a time, so the other step waits with its own explanation.
    const causes: PauseCause[] = [
      { reason: "failure_path", detail: "blocked", subject: REVIEW_SLOT },
      { reason: "infra", detail: "recovery.restarting", subject: PASS_2_SLOT },
    ];
    renderBanner("failure_path", pausedView({ causes }), TWO_STEPS, {
      retryActivationIds: [],
      slots: [PASS_1, PASS_2, REVIEW],
    });
    const banner = screen.getByRole("region", { name: "Paused: step failed" });
    expect(bodyText(banner)).toBe(
      `${isolated("Review")} reported that it is blocked. Retry restarts it from its last handoff.`,
    );
    expect(items()).toEqual([`Coral is restarting ${STEP} from its last handoff.`]);
    expect(within(banner).queryByRole("button")).toBeNull();
  });

  it("renders a step name that looks like markup as text in the body and the button", () => {
    // WHY: a workflow author's step name is data, never markup.
    const name = "<img src=x onerror=alert(1)><b>Impl</b>";
    const graph: GraphNodeNames = { nodes: [{ id: "implement", name }] };
    const causes: PauseCause[] = [
      { reason: "failure_path", detail: "restart:workspace.head_moved", subject: PASS_2_SLOT },
    ];
    renderBanner("failure_path", pausedView({ causes }), graph, {
      retryActivationIds: [PASS_2.activation_id],
      slots: [PASS_1, PASS_2],
    });
    const banner = screen.getByRole("region", { name: "Paused: step failed" });
    expect(bodyText(banner)).toContain(`so ${isolated(name)} was not restarted.`);
    expect(within(banner).getByRole("button")).toHaveTextContent(`Retry ${isolated(name)}`);
    expect(banner.querySelector("img, b")).toBeNull();
  });
});
