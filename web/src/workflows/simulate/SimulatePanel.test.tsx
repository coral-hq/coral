import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  CompiledGraph,
  InvalidResult,
  SimResult,
  SimulatedResult,
} from "../api/generated/coralApi";
import type * as ClientModule from "../api/client";
import { WorkflowsApiError } from "../api/client";
import { REVIEW_LOOP_COMPILED, REVIEW_LOOP_SIMULATIONS } from "../fixtures";
import { isolated } from "../shared/pauseCopy";

const api = vi.hoisted(() => ({ simulateWorkflow: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  ...api,
}));

import { SimulatePanel } from "./SimulatePanel";
import { BUSY_RETRIES, useSimulation } from "./useSimulation";

const { needs_review: NEEDS_REVIEW, needs_gate: NEEDS_GATE } = REVIEW_LOOP_SIMULATIONS;

const simulated = (
  simulation: SimResult | null,
  compiled: CompiledGraph = REVIEW_LOOP_COMPILED,
): SimulatedResult => ({
  valid: true,
  runnable: simulation !== null,
  content_hash: compiled.content_hash,
  problems: [],
  compiled,
  simulation,
});

/** A final simulation of the template, changed by `partial`. */
const ended = (partial: Partial<SimResult>): SimResult => ({
  ...REVIEW_LOOP_SIMULATIONS.approved,
  ...partial,
});

const rejected = (value: string, allowed: string[]): SimResult => ({
  ...NEEDS_REVIEW,
  outcome: "rejected",
  needs_input: null,
  rejection: {
    node_id: "review",
    kind: "label",
    value,
    code: "handoff.invalid",
    allowed_values: allowed,
  },
});

/** An answer the test releases. */
function held<T>() {
  let release: (value: T) => void = () => {};
  const promise = new Promise<T>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

function Harness({ yaml, onClose }: { yaml: string; onClose: () => void }) {
  return <SimulatePanel simulation={useSimulation(yaml, true)} onClose={onClose} />;
}

function renderPanel(yaml = "v1") {
  const onClose = vi.fn();
  const view = render(<Harness yaml={yaml} onClose={onClose} />);
  const setYaml = (next: string) => view.rerender(<Harness yaml={next} onClose={onClose} />);
  return { ...view, onClose, setYaml };
}

const button = (name: string) => screen.getByRole("button", { name });
/** The script of the request numbered `call`, zero-based. */
const scriptOf = (call: number) => api.simulateWorkflow.mock.calls[call][1];
const settled = () => waitFor(() => expect(screen.queryByText("Simulating…")).toBeNull());

beforeEach(() => {
  api.simulateWorkflow.mockReset();
  api.simulateWorkflow.mockResolvedValue(simulated(NEEDS_REVIEW));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("SimulatePanel", () => {
  it("asks for each needed result and re-posts the script with every answer", async () => {
    // WHY: the panel builds the script one answer at a time; the server keeps no state.
    renderPanel();
    expect(
      await screen.findByText(`Choose a result for ${isolated("Review")}:`),
    ).toBeInTheDocument();
    expect(scriptOf(0)).toEqual({ inputs: [] });

    const requestChanges = async (next: SimResult) => {
      api.simulateWorkflow.mockResolvedValueOnce(simulated(next));
      fireEvent.click(button("changes_requested"));
      await settled();
    };
    await requestChanges(NEEDS_REVIEW);
    await requestChanges(NEEDS_REVIEW);
    await requestChanges(NEEDS_GATE);
    expect(screen.getByText(`Choose a result for ${isolated("Approve change")}:`)).toBeVisible();
    api.simulateWorkflow.mockResolvedValueOnce(simulated(REVIEW_LOOP_SIMULATIONS.changes_to_limit));
    fireEvent.click(button("approve"));
    expect(await screen.findByText("The run completes.")).toBeInTheDocument();

    expect(scriptOf(4)).toEqual({
      inputs: [
        { node_id: "review", kind: "label", values: Array(3).fill("changes_requested") },
        { node_id: "approve_change", kind: "gate", values: ["approve"] },
      ],
    });
    const path = within(screen.getByRole("list", { name: "Path" })).getAllByRole("listitem");
    const step = (name: string, result: string) => `${isolated(name)}: ${result}`;
    expect(path.map((item) => item.textContent)).toEqual([
      step("Implement", "done"),
      step("Review", "changes requested"),
      step("Implement", "done"),
      step("Review", "changes requested"),
      step("Implement", "done"),
      step("Review", "changes requested"),
      step("Approve change", "approve"),
    ]);
    expect(
      within(screen.getByRole("list", { name: "Loops" })).getByRole("listitem"),
    ).toHaveTextContent(
      `${isolated("Review")} → ${isolated("Implement")}: pass 3 of 3, limit reached`,
    );
    expect(screen.getByText(`Gates reached: ${isolated("Approve change")}`)).toBeInTheDocument();
    expect(screen.getByText("Step activations: 6")).toBeInTheDocument();
    expect(screen.getByText("Estimated sessions: 7")).toBeInTheDocument();
    expect(
      screen.getByText(
        "6 for steps, 0 for an orchestrator and 1 for the run's anchor session. This is an estimate.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "approve" })).toBeNull();
  });

  it("undoes the last answer and resets them all, re-posting each time", async () => {
    renderPanel();
    await screen.findByText(`Choose a result for ${isolated("Review")}:`);
    expect(button("Undo")).toBeDisabled();
    expect(button("Reset")).toBeDisabled();

    api.simulateWorkflow.mockResolvedValue(simulated(NEEDS_REVIEW));
    fireEvent.click(button("changes_requested"));
    await settled();
    fireEvent.click(button("changes_requested"));
    await settled();
    fireEvent.click(button("Undo"));
    await settled();
    expect(scriptOf(3)).toEqual({
      inputs: [{ node_id: "review", kind: "label", values: ["changes_requested"] }],
    });
    fireEvent.click(button("Reset"));
    await settled();
    expect(scriptOf(4)).toEqual({ inputs: [] });
    expect(button("Undo")).toBeDisabled();
  });

  it("disables Answer, Undo and Reset while a request is pending, and takes one answer per click", async () => {
    // WHY: a second click before the answer lands would answer the next question unseen.
    renderPanel();
    await screen.findByText(`Choose a result for ${isolated("Review")}:`);
    api.simulateWorkflow.mockResolvedValueOnce(simulated(NEEDS_REVIEW));
    fireEvent.click(button("changes_requested"));
    await settled();

    const pending = held<SimulatedResult>();
    api.simulateWorkflow.mockReturnValueOnce(pending.promise);
    fireEvent.click(button("approved"));
    fireEvent.click(button("approved"));
    expect(screen.getByText("Simulating…")).toBeInTheDocument();
    for (const name of ["approved", "changes_requested", "Undo", "Reset"]) {
      expect(button(name)).toBeDisabled();
    }
    expect(button("Close")).toBeEnabled();
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(3);
    expect(scriptOf(2)).toEqual({
      inputs: [{ node_id: "review", kind: "label", values: ["changes_requested", "approved"] }],
    });

    await act(async () => pending.release(simulated(NEEDS_GATE)));
    expect(button("approve")).toBeEnabled();
    expect(button("Undo")).toBeEnabled();
  });

  it("disables answers while the workflow changed, until it is simulated again", async () => {
    // WHY: an answer chosen for the old text must not be sent with the new one.
    const { setYaml } = renderPanel();
    await screen.findByText(`Choose a result for ${isolated("Review")}:`);
    api.simulateWorkflow.mockResolvedValueOnce(simulated(NEEDS_REVIEW));
    fireEvent.click(button("changes_requested"));
    await settled();

    setYaml("v2");
    expect(screen.getByText("The workflow changed since this simulation.")).toBeInTheDocument();
    expect(button("approved")).toBeDisabled();
    fireEvent.click(button("approved"));
    expect(button("Undo")).toBeDisabled();
    expect(button("Reset")).toBeEnabled();
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(2);

    fireEvent.click(button("Simulate again"));
    await settled();
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith(
      "v2",
      { inputs: [{ node_id: "review", kind: "label", values: ["changes_requested"] }] },
      expect.anything(),
    );
    expect(screen.queryByText("The workflow changed since this simulation.")).toBeNull();
    expect(button("approved")).toBeEnabled();
  });

  it("shows a refused value's allowed values as text, with Undo and Reset to recover", async () => {
    renderPanel();
    await screen.findByText(`Choose a result for ${isolated("Review")}:`);
    api.simulateWorkflow.mockResolvedValueOnce(
      simulated(rejected("approved", ["changes_requested", "needs_work"])),
    );
    fireEvent.click(button("approved"));

    expect(
      await screen.findByText(`${isolated("Review")} cannot take ${isolated("approved")}.`),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        `Allowed values: ${isolated("changes_requested")}, ${isolated("needs_work")}.`,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "changes_requested" })).toBeNull();
    expect(button("Reset")).toBeEnabled();

    fireEvent.click(button("Undo"));
    await settled();
    expect(scriptOf(2)).toEqual({ inputs: [] });
    // Undone to empty, the question is back and the next answer replaces the refused one.
    expect(button("Undo")).toBeDisabled();
    expect(button("Reset")).toBeDisabled();
    fireEvent.click(button("changes_requested"));
    await settled();
    expect(scriptOf(3)).toEqual({
      inputs: [{ node_id: "review", kind: "label", values: ["changes_requested"] }],
    });
  });

  it.each<[string, SimResult, string[]]>([
    [
      "a pause for a failing check",
      ended({
        outcome: "paused",
        view: {
          ...NEEDS_REVIEW.view,
          status: "paused",
          causes: [
            {
              reason: "failure_path",
              detail: "attempts_exhausted:c1",
              subject: "implement||a4:1:0",
            },
          ],
        },
      }),
      ["The run pauses: step failed.", `Missing evidence: ${isolated("c1")}.`],
    ],
    [
      "a pause at the activation cap",
      ended({
        outcome: "paused",
        view: {
          ...NEEDS_REVIEW.view,
          status: "paused",
          causes: [{ reason: "budget", detail: "activation_cap", subject: "simulation" }],
        },
      }),
      ["The run pauses: activation cap.", "The run reached its activation cap."],
    ],
    [
      "a pause with no known cause",
      ended({ outcome: "paused", view: { ...NEEDS_REVIEW.view, status: "paused", causes: [] } }),
      ["The run pauses."],
    ],
    ["a failed run", ended({ outcome: "failed" }), ["The run fails."]],
    [
      "a failed check on the path and no gate reached",
      ended({
        outcome: "failed",
        gates_reached: [],
        steps: [{ ...NEEDS_REVIEW.steps[0]!, result: "evidence_missing" }],
      }),
      ["The run fails.", `${isolated("Implement")}: checks fail`, "Gates reached: none"],
    ],
    [
      "a value the node takes none of",
      rejected("approved", []),
      [`${isolated("Review")} cannot take ${isolated("approved")}.`, "It takes no value here."],
    ],
    [
      "a stall with no code",
      ended({ outcome: "stalled", stall_code: null }),
      ["No step can advance."],
    ],
    [
      "a stop with no bound named",
      ended({ outcome: "step_limit", limit: null }),
      ["The simulation stopped after too many steps."],
    ],
    [
      "an unsupported effect it cannot name",
      ended({ outcome: "unsupported", unsupported_effect: null }),
      ["The simulation stopped: Simulate cannot model one of the run's actions yet."],
    ],
    ["a cancelled run", ended({ outcome: "cancelled" }), ["The run is cancelled."]],
    [
      "a stall",
      ended({ outcome: "stalled", stall_code: "slot.stale" }),
      ["No step can advance.", "The engine refused an input Simulate made: slot.stale."],
    ],
    [
      "the transition cap",
      ended({ outcome: "step_limit", limit: "transitions" }),
      ["The simulation stopped after too many steps."],
    ],
    [
      "the work budget",
      ended({ outcome: "step_limit", limit: "work" }),
      ["The simulation stopped: the run grew too large to simulate."],
    ],
    [
      "the step seat cap",
      ended({ outcome: "step_limit", limit: "step_seats", entries: 0, steps: [] }),
      ["The workflow cannot be simulated: a step has too many agents."],
    ],
    [
      "the graph seat cap",
      ended({ outcome: "step_limit", limit: "graph_seats", entries: 0, steps: [] }),
      ["The workflow cannot be simulated: its steps have too many agents in all."],
    ],
    [
      "the graph size cap",
      ended({ outcome: "step_limit", limit: "graph_size", entries: 0, steps: [] }),
      ["The workflow cannot be simulated: it has too many nodes or arrows."],
    ],
    [
      "an unsupported effect",
      ended({ outcome: "unsupported", unsupported_effect: "structure.start_item" }),
      [
        `The simulation stopped: Simulate cannot model the ${isolated("structure.start_item")} action yet.`,
      ],
    ],
  ])("explains %s", async (_name, simulation, lines) => {
    api.simulateWorkflow.mockResolvedValue(simulated(simulation));
    renderPanel();
    await screen.findByText(lines[0]!);
    for (const line of lines) expect(screen.getByText(line)).toBeInTheDocument();
  });

  it("leaves out the path and estimate of a workflow refused before its run starts", async () => {
    api.simulateWorkflow.mockResolvedValue(
      simulated(ended({ outcome: "step_limit", limit: "graph_size", entries: 0, steps: [] })),
    );
    renderPanel();
    await screen.findByText("The workflow cannot be simulated: it has too many nodes or arrows.");
    expect(screen.queryByText(/Estimated sessions/)).toBeNull();
    expect(screen.queryByRole("list", { name: "Path" })).toBeNull();
  });

  it("asks for a check's result as pass or fail", async () => {
    api.simulateWorkflow.mockResolvedValueOnce(
      simulated({
        ...NEEDS_REVIEW,
        steps: [],
        needs_input: {
          node_id: "implement",
          activation_id: "implement||a4:1",
          kind: "done_when",
          allowed_values: ["pass", "fail"],
        },
      }),
    );
    renderPanel();
    expect(
      await screen.findByText(`Choose a result for ${isolated("Implement")}:`),
    ).toBeInTheDocument();
    expect(button("Checks pass")).toBeEnabled();
    fireEvent.click(button("Checks fail"));
    await settled();
    expect(scriptOf(1)).toEqual({
      inputs: [{ node_id: "implement", kind: "done_when", values: ["fail"] }],
    });
  });

  it("lists answers no question used once the run has ended", async () => {
    const unconsumed = [{ node_id: "review", kind: "label" as const, values: ["approved", "x"] }];
    api.simulateWorkflow.mockResolvedValueOnce(simulated({ ...NEEDS_REVIEW, unconsumed }));
    renderPanel();
    await screen.findByText(`Choose a result for ${isolated("Review")}:`);
    expect(screen.queryByText("Unused answers")).toBeNull();

    api.simulateWorkflow.mockResolvedValueOnce(simulated(ended({ unconsumed })));
    fireEvent.click(button("approved"));
    await screen.findByText("The run completes.");
    expect(
      within(screen.getByRole("list", { name: "Unused answers" })).getByRole("listitem"),
    ).toHaveTextContent(`${isolated("Review")}: ${isolated("approved")}, ${isolated("x")}`);
  });

  it("explains a text that does not load, and a workflow with errors", async () => {
    const notLoaded: InvalidResult = {
      valid: false,
      runnable: false,
      load_error: {
        code: "invalid_yaml",
        yaml_path: "",
        range: null,
        message: "Bad YAML.",
        issues: [],
      },
    };
    api.simulateWorkflow.mockResolvedValueOnce(notLoaded);
    const { setYaml } = renderPanel();
    expect(await screen.findByText("The workflow does not load.")).toBeInTheDocument();
    expect(screen.getByText("Bad YAML.")).toBeInTheDocument();

    api.simulateWorkflow.mockResolvedValueOnce(simulated(null));
    setYaml("v2");
    fireEvent.click(button("Simulate again"));
    expect(
      await screen.findByText("Fix the workflow's errors to simulate it."),
    ).toBeInTheDocument();
  });

  it("says the server is busy while it waits out Retry-After, then gives up", async () => {
    vi.useFakeTimers();
    api.simulateWorkflow.mockRejectedValue(
      new WorkflowsApiError("Failed to simulate workflow (503)", 503, 1000, "server_busy"),
    );
    renderPanel();
    await act(async () => {});
    expect(screen.getByText("The server is busy; trying again shortly.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000 * BUSY_RETRIES);
    });
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(BUSY_RETRIES + 1);
    expect(screen.getByText("The server is busy; try again.")).toBeInTheDocument();
    api.simulateWorkflow.mockResolvedValueOnce(simulated(NEEDS_REVIEW));
    fireEvent.click(button("Try again"));
    await act(async () => {});
    expect(screen.getByText(`Choose a result for ${isolated("Review")}:`)).toBeInTheDocument();
  });

  it("explains a failed request and offers another try", async () => {
    api.simulateWorkflow.mockRejectedValueOnce(new WorkflowsApiError("Failed", 500));
    renderPanel();
    expect(await screen.findByText("Couldn't simulate the workflow.")).toBeInTheDocument();
    fireEvent.click(button("Try again"));
    expect(
      await screen.findByText(`Choose a result for ${isolated("Review")}:`),
    ).toBeInTheDocument();
  });

  it("points to Undo and Reset when the server refuses an answer", async () => {
    // WHY: sending the same answers again would be refused again.
    renderPanel();
    await screen.findByText(`Choose a result for ${isolated("Review")}:`);
    api.simulateWorkflow.mockRejectedValueOnce(new WorkflowsApiError("Failed", 422));
    fireEvent.click(button("approved"));
    expect(
      await screen.findByText("The server refused one of the answers. Undo it or reset."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
    fireEvent.click(button("Undo"));
    await settled();
    expect(scriptOf(2)).toEqual({ inputs: [] });
  });

  it("offers another try when the server refuses a script with no answers", async () => {
    // WHY: with nothing to undo or reset, another try is the only way on.
    api.simulateWorkflow.mockRejectedValueOnce(new WorkflowsApiError("Failed", 422));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't simulate the workflow.");
    expect(button("Undo")).toBeDisabled();
    fireEvent.click(button("Try again"));
    expect(
      await screen.findByText(`Choose a result for ${isolated("Review")}:`),
    ).toBeInTheDocument();
  });

  it("reports a 503 that is not the server's busy refusal as a failure, without waiting", async () => {
    api.simulateWorkflow.mockRejectedValueOnce(
      new WorkflowsApiError("Failed to simulate workflow (503)", 503, 1000, null),
    );
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't simulate the workflow.");
    expect(screen.queryByText("The server is busy; trying again shortly.")).toBeNull();
    expect(button("Try again")).toBeEnabled();
  });

  it("moves focus to the next question after an answer, and back to Undo after an undo", async () => {
    // WHY: the used button is disabled while its request runs; keyboard focus must not drop.
    renderPanel();
    await screen.findByText(`Choose a result for ${isolated("Review")}:`);
    const heading = screen.getByRole("heading", { name: "Simulation" });
    const pending = held<SimulatedResult>();
    api.simulateWorkflow.mockReturnValueOnce(pending.promise);
    fireEvent.click(button("changes_requested"));
    expect(heading).toHaveFocus();
    await act(async () => pending.release(simulated(NEEDS_REVIEW)));
    expect(
      screen.getByRole("group", { name: `Choose a result for ${isolated("Review")}:` }),
    ).toHaveFocus();

    api.simulateWorkflow.mockResolvedValueOnce(simulated(NEEDS_GATE));
    fireEvent.click(button("approved"));
    await settled();
    fireEvent.click(button("Undo"));
    await settled();
    expect(button("Undo")).toHaveFocus();

    api.simulateWorkflow.mockResolvedValueOnce(simulated(REVIEW_LOOP_SIMULATIONS.approved));
    fireEvent.click(button("approved"));
    await screen.findByText("The run completes.");
    expect(heading).toHaveFocus();
  });

  it("shows names and values from the workflow as text, never as markup", async () => {
    const markup = "<img src=x onerror=alert(1)>";
    const compiled: CompiledGraph = {
      ...REVIEW_LOOP_COMPILED,
      nodes: REVIEW_LOOP_COMPILED.nodes.map((node) =>
        node.id === "review" ? { ...node, name: markup } : node,
      ),
    };
    api.simulateWorkflow.mockResolvedValue(simulated(rejected(markup, [markup]), compiled));
    const { container } = renderPanel();
    expect(
      await screen.findByText(`${isolated(markup)} cannot take ${isolated(markup)}.`),
    ).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("closes", async () => {
    const { onClose } = renderPanel();
    await screen.findByText(`Choose a result for ${isolated("Review")}:`);
    fireEvent.click(button("Close"));
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
