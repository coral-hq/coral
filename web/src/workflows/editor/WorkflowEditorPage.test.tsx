import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SimResult, SimulatedResult } from "../api/generated/coralApi";
import type { ValidateResponse } from "../api/workflowTypes";
import {
  MINIMAL_COMPILED,
  MINIMAL_YAML,
  PR_REVIEW_COMPILED,
  REVIEW_LOOP_COMPILED,
  REVIEW_LOOP_SIMULATIONS,
} from "../fixtures";
import { isolated } from "../shared/pauseCopy";
import { WorkflowsApiError } from "../api/client";
import type * as ClientModule from "../api/client";

const api = vi.hoisted(() => ({
  getWorkflowByKey: vi.fn(),
  saveWorkflow: vi.fn(),
  validateWorkflow: vi.fn(),
  simulateWorkflow: vi.fn(),
}));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  ...api,
}));
// A stand-in for the Monaco editor the pane hands out: the cursor is a selection.
const yamlEditor = vi.hoisted(() => ({
  getSelection: vi.fn(() => ({ startLineNumber: 3, startColumn: 5 })),
  executeEdits: vi.fn(),
  focus: vi.fn(),
}));
const coral = vi.hoisted(() => ({ profilesDesk: true }));
vi.mock("../gate/useCoralInfo", () => ({
  isCoralAvailable: () => coral.profilesDesk,
  useCoralInfo: () => ({ data: undefined }),
}));
vi.mock("../profiles/ProfilePicker", () => ({
  ProfilePicker: ({ onPick }: { onPick: (ref: string) => void }) => (
    <button type="button" onClick={() => onPick("reviewer/strict-review")}>
      Insert profile
    </button>
  ),
}));
vi.mock("./YamlPane", () => ({
  YamlPane: ({
    value,
    onChange,
    markers,
    onEditorReady,
  }: {
    value: string;
    onChange: (value: string) => void;
    markers: { message: string; startLineNumber: number }[];
    onEditorReady?: (editor: typeof yamlEditor) => void;
  }) => (
    <div ref={() => onEditorReady?.(yamlEditor)}>
      <textarea aria-label="yaml" value={value} onChange={(e) => onChange(e.target.value)} />
      <ul data-testid="markers">
        {markers.map((marker) => (
          <li key={marker.message}>{`${marker.startLineNumber}:${marker.message}`}</li>
        ))}
      </ul>
    </div>
  ),
}));
vi.mock("../canvas/FlowCanvas", () => ({
  FlowCanvas: ({
    compiled,
    overlay,
  }: {
    compiled: { nodes: unknown[]; workflow_id: string } | null;
    overlay?: ReadonlyMap<string, unknown> | null;
  }) => (
    <div
      data-testid="canvas-nodes"
      data-workflow={compiled?.workflow_id ?? ""}
      data-overlay={overlay ? "on" : "off"}
    >
      {compiled?.nodes.length ?? 0}
    </div>
  ),
}));
vi.mock("../start/StartRunDialog", () => ({
  StartRunDialog: ({
    open,
    workflowId,
    workflowKey,
  }: {
    open: boolean;
    workflowId: string;
    workflowKey: string;
  }) => (open ? <div>{`start dialog for ${workflowKey} (${workflowId})`}</div> : null),
}));

import { WorkflowEditorPage } from "./WorkflowEditorPage";

const detail = {
  id: "w1",
  workflow_key: "demo",
  name: "Demo",
  content_hash: "h",
  runnable: true,
  created_at: 1,
  updated_at: 1,
  yaml: MINIMAL_YAML,
  compiled: MINIMAL_COMPILED,
};

const SLOW = { timeout: 3000 };

const BLOCKED: ValidateResponse = {
  valid: true,
  runnable: false,
  compiled: MINIMAL_COMPILED,
  problems: [
    {
      rule: "V2",
      severity: "error",
      message: "deadlock join",
      node_ids: [],
      arrow_ids: [],
      yaml_path: null,
      range: null,
    },
  ],
};

const simulatedReviewLoop = (simulation: SimResult): SimulatedResult => ({
  valid: true,
  runnable: true,
  content_hash: REVIEW_LOOP_COMPILED.content_hash,
  problems: [],
  compiled: REVIEW_LOOP_COMPILED,
  simulation,
});

function renderEditor() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/workflows/demo"]}>
        <Routes>
          <Route path="/workflows/:workflowKey" element={<WorkflowEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  coral.profilesDesk = true;
  yamlEditor.executeEdits.mockClear();
  for (const mock of Object.values(api)) mock.mockReset();
  api.getWorkflowByKey.mockResolvedValue(detail);
  api.validateWorkflow.mockResolvedValue({
    valid: true,
    runnable: true,
    problems: [],
    compiled: MINIMAL_COMPILED,
  } satisfies ValidateResponse);
  api.simulateWorkflow.mockResolvedValue(simulatedReviewLoop(REVIEW_LOOP_SIMULATIONS.approved));
});
afterEach(cleanup);

describe("WorkflowEditorPage", () => {
  it("shows the stored graph, then follows the compiled graph from validation", async () => {
    api.validateWorkflow.mockResolvedValue({
      valid: true,
      runnable: true,
      problems: [],
      compiled: PR_REVIEW_COMPILED,
    });
    renderEditor();
    expect(await screen.findByTestId("canvas-nodes")).toHaveTextContent("3");

    fireEvent.change(screen.getByLabelText("yaml"), { target: { value: "id: next\n" } });
    await waitFor(
      () =>
        expect(screen.getByTestId("canvas-nodes")).toHaveTextContent(
          String(PR_REVIEW_COMPILED.nodes.length),
        ),
      SLOW,
    );
    expect(api.validateWorkflow).toHaveBeenCalledWith("id: next\n", expect.anything());
  });

  it("draws markers and lists problems from the validate response", async () => {
    api.validateWorkflow.mockResolvedValue({
      valid: true,
      runnable: false,
      compiled: MINIMAL_COMPILED,
      problems: [
        {
          rule: "V2",
          severity: "error",
          message: "deadlock join",
          node_ids: [],
          arrow_ids: [],
          yaml_path: "nodes[1]",
          range: { start_line: 4, start_column: 1, end_line: 4, end_column: 8 },
        },
      ],
    });
    renderEditor();
    expect(await screen.findByText("4:V2: deadlock join", undefined, SLOW)).toBeInTheDocument();
    expect(screen.getByTestId("problem-list")).toHaveTextContent("deadlock join");
    expect(screen.getByRole("button", { name: "Start Run" })).toBeDisabled();
  });

  it("opens Start Run once the unchanged workflow validates as runnable", async () => {
    // WHY: a start names the stored definition's id, which the route's key resolved to.
    renderEditor();
    const start = await screen.findByRole("button", { name: "Start Run" });
    await waitFor(() => expect(start).toBeEnabled(), SLOW);
    fireEvent.click(start);
    expect(screen.getByText("start dialog for demo (w1)")).toBeInTheDocument();
  });

  it("saves edits", async () => {
    api.saveWorkflow.mockResolvedValue({ ...detail });
    renderEditor();
    const save = await screen.findByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("yaml"), { target: { value: `${MINIMAL_YAML}\n` } });
    await waitFor(() => expect(save).toBeEnabled(), SLOW);
    fireEvent.click(save);
    await waitFor(() => expect(api.saveWorkflow).toHaveBeenCalledWith(`${MINIMAL_YAML}\n`));
  });

  it("offers retry when the workflow cannot be loaded", async () => {
    api.getWorkflowByKey.mockRejectedValue(new WorkflowsApiError("Workflow demo not found", 404));
    renderEditor();
    expect(await screen.findByTestId("workflow-editor-error")).toHaveTextContent("not found");
  });

  it("inserts a picked profile's ref at the YAML cursor", async () => {
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Insert profile" }));
    expect(yamlEditor.executeEdits).toHaveBeenCalledWith("coral.insert-profile", [
      { range: { startLineNumber: 3, startColumn: 5 }, text: "reviewer/strict-review" },
    ]);
  });

  it("hides Insert profile without profiles_desk", async () => {
    coral.profilesDesk = false;
    renderEditor();
    await screen.findByRole("button", { name: "Save" });
    expect(screen.queryByRole("button", { name: "Insert profile" })).toBeNull();
  });

  it("opens Simulate below the panes and paints the simulated run on the canvas", async () => {
    // WHY: the overlay belongs to the graph the server simulated, not to the stored one.
    renderEditor();
    const simulate = await screen.findByRole("button", { name: "Simulate" });
    expect(simulate).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(simulate);
    expect(await screen.findByText("The run completes.")).toBeInTheDocument();
    expect(api.simulateWorkflow).toHaveBeenCalledWith(
      MINIMAL_YAML,
      { inputs: [] },
      expect.anything(),
    );
    expect(simulate).toHaveAttribute("aria-expanded", "true");
    const canvas = screen.getByTestId("canvas-nodes");
    expect(canvas).toHaveAttribute("data-workflow", REVIEW_LOOP_COMPILED.workflow_id);
    expect(canvas).toHaveAttribute("data-overlay", "on");

    fireEvent.click(simulate);
    expect(screen.queryByRole("region", { name: "Simulation" })).toBeNull();
    expect(canvas).toHaveAttribute("data-workflow", MINIMAL_COMPILED.workflow_id);
    expect(canvas).toHaveAttribute("data-overlay", "off");
  });

  it("shows the live graph with no overlay while the simulation is stale", async () => {
    // WHY: the canvas always matches the YAML pane; an overlay only paints its own graph.
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Simulate" }));
    await screen.findByText("The run completes.");

    fireEvent.change(screen.getByLabelText("yaml"), { target: { value: "id: next\n" } });
    const canvas = screen.getByTestId("canvas-nodes");
    expect(screen.getByText("The workflow changed since this simulation.")).toBeInTheDocument();
    expect(canvas).toHaveAttribute("data-workflow", MINIMAL_COMPILED.workflow_id);
    expect(canvas).toHaveAttribute("data-overlay", "off");
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Simulate again" }));
    await waitFor(() => expect(canvas).toHaveAttribute("data-overlay", "on"));
    expect(canvas).toHaveAttribute("data-workflow", REVIEW_LOOP_COMPILED.workflow_id);
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith(
      "id: next\n",
      { inputs: [] },
      expect.anything(),
    );
  });

  it("keeps the live graph when an answer lands for a text edited meanwhile", async () => {
    // WHY: the response belongs to the text posted before the edit.
    let release: (response: SimulatedResult) => void = () => {};
    api.simulateWorkflow
      .mockResolvedValueOnce(simulatedReviewLoop(REVIEW_LOOP_SIMULATIONS.needs_review))
      .mockReturnValueOnce(
        new Promise<SimulatedResult>((resolve) => {
          release = resolve;
        }),
      );
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Simulate" }));
    fireEvent.click(await screen.findByRole("button", { name: "approved" }));
    fireEvent.change(screen.getByLabelText("yaml"), { target: { value: "id: next\n" } });

    await act(async () => release(simulatedReviewLoop(REVIEW_LOOP_SIMULATIONS.needs_gate)));
    expect(
      screen.getByText(`Choose a result for ${isolated("Approve change")}:`),
    ).toBeInTheDocument();
    expect(screen.getByText("The workflow changed since this simulation.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "approve" })).toBeDisabled();
    const canvas = screen.getByTestId("canvas-nodes");
    expect(canvas).toHaveAttribute("data-workflow", MINIMAL_COMPILED.workflow_id);
    expect(canvas).toHaveAttribute("data-overlay", "off");
  });

  it("keeps the live graph while the edited text is simulated again", async () => {
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Simulate" }));
    await screen.findByText("The run completes.");
    fireEvent.change(screen.getByLabelText("yaml"), { target: { value: "id: next\n" } });

    api.simulateWorkflow.mockReturnValueOnce(new Promise(() => {}));
    fireEvent.click(screen.getByRole("button", { name: "Simulate again" }));
    const canvas = screen.getByTestId("canvas-nodes");
    expect(canvas).toHaveAttribute("data-workflow", MINIMAL_COMPILED.workflow_id);
    expect(canvas).toHaveAttribute("data-overlay", "off");
  });

  it("shows the stale notice and no result until the edited text's answer lands", async () => {
    // WHY: the previous text's result must never show as the edited text's.
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Simulate" }));
    await screen.findByText("The run completes.");
    fireEvent.change(screen.getByLabelText("yaml"), { target: { value: "id: next\n" } });

    let release: (response: SimulatedResult) => void = () => {};
    api.simulateWorkflow.mockReturnValueOnce(
      new Promise<SimulatedResult>((resolve) => {
        release = resolve;
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Simulate again" }));
    const canvas = screen.getByTestId("canvas-nodes");
    expect(screen.getByText("Simulating…")).toBeInTheDocument();
    expect(screen.getByText("The workflow changed since this simulation.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Simulate again" })).toBeDisabled();
    expect(screen.queryByText("The run completes.")).toBeNull();
    expect(canvas).toHaveAttribute("data-workflow", MINIMAL_COMPILED.workflow_id);
    expect(canvas).toHaveAttribute("data-overlay", "off");

    await act(async () => release(simulatedReviewLoop(REVIEW_LOOP_SIMULATIONS.needs_review)));
    expect(screen.queryByText("The workflow changed since this simulation.")).toBeNull();
    expect(canvas).toHaveAttribute("data-workflow", REVIEW_LOOP_COMPILED.workflow_id);
    expect(canvas).toHaveAttribute("data-overlay", "on");
  });

  it("keeps the live graph while the edited text waits out a busy server", async () => {
    renderEditor();
    fireEvent.click(await screen.findByRole("button", { name: "Simulate" }));
    await screen.findByText("The run completes.");
    fireEvent.change(screen.getByLabelText("yaml"), { target: { value: "id: next\n" } });
    vi.useFakeTimers();
    try {
      api.simulateWorkflow
        .mockRejectedValueOnce(
          new WorkflowsApiError("Failed to simulate workflow (503)", 503, 1000, "server_busy"),
        )
        .mockResolvedValueOnce(simulatedReviewLoop(REVIEW_LOOP_SIMULATIONS.needs_review));
      fireEvent.click(screen.getByRole("button", { name: "Simulate again" }));
      await act(async () => {});
      const canvas = screen.getByTestId("canvas-nodes");
      expect(screen.getByText("The server is busy; trying again shortly.")).toBeInTheDocument();
      expect(screen.getByText("The workflow changed since this simulation.")).toBeInTheDocument();
      expect(screen.queryByText("The run completes.")).toBeNull();
      expect(canvas).toHaveAttribute("data-workflow", MINIMAL_COMPILED.workflow_id);
      expect(canvas).toHaveAttribute("data-overlay", "off");

      await act(async () => {
        await vi.advanceTimersByTimeAsync(1000);
      });
      expect(api.simulateWorkflow).toHaveBeenLastCalledWith(
        "id: next\n",
        { inputs: [] },
        expect.anything(),
      );
      expect(canvas).toHaveAttribute("data-workflow", REVIEW_LOOP_COMPILED.workflow_id);
      expect(canvas).toHaveAttribute("data-overlay", "on");
    } finally {
      vi.useRealTimers();
    }
  });

  it("returns focus to Simulate when the panel's Close is used", async () => {
    // WHY: Close removes the focused control; keyboard focus must not drop to the page.
    renderEditor();
    const simulate = await screen.findByRole("button", { name: "Simulate" });
    fireEvent.click(simulate);
    await screen.findByText("The run completes.");
    const close = within(screen.getByRole("region", { name: "Simulation" })).getByRole("button", {
      name: "Close",
    });
    close.focus();
    fireEvent.click(close);
    expect(screen.queryByRole("region", { name: "Simulation" })).toBeNull();
    expect(simulate).toHaveFocus();
  });

  it("stops waiting for a busy server when the panel is closed", async () => {
    renderEditor();
    const simulate = await screen.findByRole("button", { name: "Simulate" });
    vi.useFakeTimers();
    try {
      api.simulateWorkflow.mockRejectedValueOnce(
        new WorkflowsApiError("Failed to simulate workflow (503)", 503, 5000, "server_busy"),
      );
      fireEvent.click(simulate);
      await act(async () => {});
      const panel = screen.getByRole("region", { name: "Simulation" });
      expect(within(panel).getByText("The server is busy; trying again shortly.")).toBeVisible();

      fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("region", { name: "Simulation" })).toBeNull();
      expect(simulate).toHaveAttribute("aria-expanded", "false");
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("disables Simulate while validation reports an error", async () => {
    api.validateWorkflow.mockResolvedValue(BLOCKED);
    renderEditor();
    const simulate = await screen.findByRole("button", { name: "Simulate" });
    await waitFor(() => expect(simulate).toBeDisabled(), SLOW);
    expect(api.simulateWorkflow).not.toHaveBeenCalled();
  });

  it("keeps Simulate enabled while the panel is open, so an error never traps it open", async () => {
    renderEditor();
    const simulate = await screen.findByRole("button", { name: "Simulate" });
    fireEvent.click(simulate);
    await screen.findByText("The run completes.");

    api.validateWorkflow.mockResolvedValue(BLOCKED);
    fireEvent.change(screen.getByLabelText("yaml"), { target: { value: "id: broken\n" } });
    await waitFor(
      () => expect(screen.getByTestId("problem-list")).toHaveTextContent("deadlock join"),
      SLOW,
    );
    expect(simulate).toBeEnabled();
    fireEvent.click(simulate);
    expect(screen.queryByRole("region", { name: "Simulation" })).toBeNull();
    expect(simulate).toBeDisabled();
  });
});
