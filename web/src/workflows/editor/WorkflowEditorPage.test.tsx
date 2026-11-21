import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ValidateResponse } from "../api/workflowTypes";
import { MINIMAL_COMPILED, MINIMAL_YAML, PR_REVIEW_COMPILED } from "../fixtures";
import { WorkflowsApiError } from "../api/client";
import type * as ClientModule from "../api/client";

const api = vi.hoisted(() => ({
  getWorkflowByKey: vi.fn(),
  saveWorkflow: vi.fn(),
  validateWorkflow: vi.fn(),
}));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  ...api,
}));
vi.mock("./YamlPane", () => ({
  YamlPane: ({
    value,
    onChange,
    markers,
  }: {
    value: string;
    onChange: (value: string) => void;
    markers: { message: string; startLineNumber: number }[];
  }) => (
    <div>
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
  FlowCanvas: ({ compiled }: { compiled: { nodes: unknown[] } | null }) => (
    <div data-testid="canvas-nodes">{compiled?.nodes.length ?? 0}</div>
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
  for (const mock of Object.values(api)) mock.mockReset();
  api.getWorkflowByKey.mockResolvedValue(detail);
  api.validateWorkflow.mockResolvedValue({
    valid: true,
    runnable: true,
    problems: [],
    compiled: MINIMAL_COMPILED,
  } satisfies ValidateResponse);
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
});
