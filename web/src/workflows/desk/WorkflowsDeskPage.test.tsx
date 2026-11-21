import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowsApiError } from "../api/client";
import type * as ClientModule from "../api/client";
import { PR_REVIEW_TEMPLATE } from "../api/msw/handlers";
import type * as RunsApiModule from "../api/runsApi";

const api = vi.hoisted(() => ({ listWorkflows: vi.fn(), saveWorkflow: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  ...api,
}));
const runsApi = vi.hoisted(() => ({ listRuns: vi.fn() }));
vi.mock("../api/runsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof RunsApiModule>()),
  ...runsApi,
}));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => "alice",
  useIdentityReady: () => true,
}));

import { WorkflowsDeskPage } from "./WorkflowsDeskPage";

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function renderDesk(path = "/workflows") {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="/workflows"
            element={
              <>
                <WorkflowsDeskPage />
                <Where />
              </>
            }
          />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const summary = (key: string, runnable = true) => ({
  id: `id-${key}`,
  workflow_key: key,
  name: `Name ${key}`,
  content_hash: "h",
  runnable,
  created_at: 1,
  updated_at: 1,
});

beforeEach(() => {
  api.listWorkflows.mockReset();
  api.saveWorkflow.mockReset();
  runsApi.listRuns.mockReset();
  runsApi.listRuns.mockResolvedValue({ data: [], next_cursor: null });
});
afterEach(cleanup);

describe("WorkflowsDeskPage", () => {
  it("lists workflows and opens one in the editor", async () => {
    api.listWorkflows.mockResolvedValue([summary("daily"), summary("draft", false)]);
    renderDesk();
    expect(await screen.findByText("Name daily")).toBeInTheDocument();
    expect(screen.getAllByText("Draft")).toHaveLength(1);

    fireEvent.click(screen.getAllByRole("button", { name: "Open" })[0]);
    expect(screen.getByTestId("where")).toHaveTextContent("/workflows/daily");
  });

  it("shows an empty state, and retry after a load failure", async () => {
    api.listWorkflows
      .mockRejectedValueOnce(new WorkflowsApiError("down", 403))
      .mockResolvedValueOnce([]);
    renderDesk();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No workflows yet")).toBeInTheDocument();
  });

  it("shows the runs history in the Runs tab, and keeps the tab in the URL", async () => {
    // WHY: a person finds any of their runs, and a reload stays on the tab.
    api.listWorkflows.mockResolvedValue([]);
    renderDesk();
    expect(runsApi.listRuns).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("tab", { name: "Runs" }));
    expect(await screen.findByText("No runs yet. Start one from a workflow.")).toBeInTheDocument();
    expect(runsApi.listRuns).toHaveBeenCalledWith(
      { statuses: [], workflowId: null },
      undefined,
      expect.anything(),
    );
    expect(screen.getByTestId("where")).toHaveTextContent("/workflows?tab=runs");

    await userEvent.click(screen.getByRole("tab", { name: "Your Workflows" }));
    expect(await screen.findByText("No workflows yet")).toBeInTheDocument();
    expect(screen.getByTestId("where").textContent).toBe("/workflows");
  });

  it("opens on the tab the URL names, and on Your Workflows for an unknown one", async () => {
    api.listWorkflows.mockResolvedValue([]);
    renderDesk("/workflows?tab=templates");
    expect(await screen.findByText("PR review")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Templates" })).toHaveAttribute("aria-selected", "true");
    cleanup();

    renderDesk("/workflows?tab=bogus");
    expect(await screen.findByText("No workflows yet")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Your Workflows" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("drops the runs filters when it leaves the Runs tab, and keeps other parameters", async () => {
    // WHY: the filters belong to the runs list, not to the other tabs' URLs.
    api.listWorkflows.mockResolvedValue([]);
    renderDesk("/workflows?tab=runs&status=paused&ref=mail");
    expect(await screen.findByText("No runs match these filters.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Templates" }));
    // Parameters the desk does not own stay.
    expect(screen.getByTestId("where").textContent).toBe("/workflows?tab=templates&ref=mail");
    await userEvent.click(screen.getByRole("tab", { name: "Your Workflows" }));
    expect(screen.getByTestId("where").textContent).toBe("/workflows?ref=mail");
  });

  it("offers the PR review starter and opens it in the editor once saved", async () => {
    api.listWorkflows.mockResolvedValue([]);
    api.saveWorkflow.mockResolvedValue({ ...summary("review-prs") });
    renderDesk();
    await userEvent.click(screen.getByRole("tab", { name: "Templates" }));
    expect(await screen.findByText("PR review")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Use template" }));
    await waitFor(() => expect(api.saveWorkflow).toHaveBeenCalledWith(PR_REVIEW_TEMPLATE.yaml));
    expect(await screen.findByTestId("where")).toHaveTextContent("/workflows/review-prs");
  });
});
