import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WorkflowsApiError } from "../api/client";
import type * as ClientModule from "../api/client";
import { PR_REVIEW_TEMPLATE } from "../api/msw/handlers";

const api = vi.hoisted(() => ({ listWorkflows: vi.fn(), saveWorkflow: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  ...api,
}));

import { WorkflowsDeskPage } from "./WorkflowsDeskPage";

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderDesk() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/workflows"]}>
        <Routes>
          <Route path="/workflows" element={<WorkflowsDeskPage />} />
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

  it("shows Runs as coming soon", async () => {
    api.listWorkflows.mockResolvedValue([]);
    renderDesk();
    await userEvent.click(screen.getByRole("tab", { name: "Runs" }));
    expect(await screen.findByText("Coming soon.")).toBeInTheDocument();
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
