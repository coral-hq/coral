import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WORKFLOWS_QUERY_KEY, WorkflowsApiError } from "../api/client";
import type * as ClientModule from "../api/client";
import type * as RunsApiModule from "../api/runsApi";

const api = vi.hoisted(() => ({
  listWorkflows: vi.fn(),
  saveWorkflow: vi.fn(),
  listTemplates: vi.fn(),
  createFromTemplate: vi.fn(),
}));
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

const newClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

function renderDesk(path = "/workflows", client = newClient()) {
  return render(
    <QueryClientProvider client={client}>
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

const TEMPLATE = {
  id: "implement-review-loop",
  name: "Implement with review loop",
  description: "An implementer makes the change, a reviewer approves it.",
  yaml: "id: implement-review-loop\n",
};

const saved = (key: string) => ({ ...summary(key), valid: true, problems: [] });

beforeEach(() => {
  for (const mock of Object.values(api)) mock.mockReset();
  api.listTemplates.mockResolvedValue([TEMPLATE]);
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
    expect(await screen.findByText("Implement with review loop")).toBeInTheDocument();
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

  it("lists the server's templates and makes a new copy each time one is used", async () => {
    // WHY: using a template never replaces a workflow made from it earlier.
    api.listWorkflows.mockResolvedValue([]);
    api.createFromTemplate
      .mockResolvedValueOnce(saved("implement-review-loop"))
      .mockResolvedValueOnce(saved("implement-review-loop-2"));
    renderDesk("/workflows?tab=templates");
    expect(await screen.findByText("Implement with review loop")).toBeInTheDocument();
    expect(screen.getByText(TEMPLATE.description)).toBeInTheDocument();
    expect(screen.queryByText("PR review")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Use template" }));
    await waitFor(() =>
      expect(screen.getByTestId("where").textContent).toBe("/workflows/implement-review-loop"),
    );
    expect(api.createFromTemplate).toHaveBeenCalledWith("implement-review-loop");
    cleanup();

    renderDesk("/workflows?tab=templates");
    fireEvent.click(await screen.findByRole("button", { name: "Use template" }));
    await waitFor(() =>
      expect(screen.getByTestId("where").textContent).toBe("/workflows/implement-review-loop-2"),
    );
    expect(api.createFromTemplate).toHaveBeenCalledTimes(2);
    expect(api.saveWorkflow).not.toHaveBeenCalled();
  });

  it("marks Your Workflows stale after a template is used", async () => {
    api.listWorkflows.mockResolvedValue([]);
    api.createFromTemplate.mockResolvedValue(saved("implement-review-loop"));
    const client = newClient();
    const invalidate = vi.spyOn(client, "invalidateQueries");
    renderDesk("/workflows?tab=templates", client);
    fireEvent.click(await screen.findByRole("button", { name: "Use template" }));
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: WORKFLOWS_QUERY_KEY }));
  });

  it("makes one copy when Use template is double-clicked", async () => {
    // WHY: the button waits for the copy it asked for; a second click must not make another.
    api.listWorkflows.mockResolvedValue([]);
    api.createFromTemplate.mockReturnValue(new Promise(() => {}));
    renderDesk("/workflows?tab=templates");
    const use = await screen.findByRole("button", { name: "Use template" });
    await userEvent.dblClick(use);
    await waitFor(() => expect(use).toBeDisabled());
    expect(api.createFromTemplate).toHaveBeenCalledTimes(1);
  });

  it("says when a template could not be used, and keeps the card", async () => {
    api.listWorkflows.mockResolvedValue([]);
    api.createFromTemplate.mockRejectedValue(new WorkflowsApiError("Failed", 409));
    renderDesk("/workflows?tab=templates");
    fireEvent.click(await screen.findByRole("button", { name: "Use template" }));
    expect(await screen.findByText("Couldn't create the workflow. Try again.")).toBeInTheDocument();
    expect(screen.getByTestId("where")).toHaveTextContent("/workflows?tab=templates");
  });

  it("offers Retry when templates fail to load, and says when there are none", async () => {
    api.listWorkflows.mockResolvedValue([]);
    api.listTemplates
      .mockRejectedValueOnce(new WorkflowsApiError("down", 403))
      .mockResolvedValueOnce([]);
    renderDesk("/workflows?tab=templates");
    expect(await screen.findByText("Couldn't load templates.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("No templates yet.")).toBeInTheDocument();
    expect(api.listTemplates).toHaveBeenCalledTimes(2);
  });

  it("shows a template's name and description as text, never as markup", async () => {
    const markup = "<img src=x onerror=alert(1)>";
    api.listWorkflows.mockResolvedValue([]);
    api.listTemplates.mockResolvedValue([{ ...TEMPLATE, name: markup, description: markup }]);
    const { container } = renderDesk("/workflows?tab=templates");
    expect(await screen.findAllByText(markup)).toHaveLength(2);
    expect(container.querySelector("img")).toBeNull();
  });
});
