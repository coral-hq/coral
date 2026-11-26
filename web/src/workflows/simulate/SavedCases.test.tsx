import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SavedCaseOut } from "../api/generated/coralApi";
import type * as ClientModule from "../api/client";
import { WorkflowsApiError } from "../api/client";

const api = vi.hoisted(() => ({ listWorkflowCases: vi.fn(), deleteWorkflowCase: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  ...api,
}));

import { SavedCases } from "./SavedCases";

const savedCase = (partial: Partial<SavedCaseOut>): SavedCaseOut => ({
  id: "c1",
  name: "Approved first time",
  script: { inputs: [{ node_id: "review", kind: "label", values: ["approved"] }] },
  expect: { outcome: "completed" },
  last_result: "passed",
  mismatches: [],
  last_run_at: 2,
  created_at: 1,
  ...partial,
});

const STEPS_LINE = "steps: expected [implement:done, review:approved], got [implement:done]";

function renderCases(onRun = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SavedCases workflowId="w1" onRun={onRun} />
    </QueryClientProvider>,
  );
  return { onRun };
}

const row = (name: string) => screen.getByText(name).closest("li") as HTMLElement;

beforeEach(() => {
  for (const mock of Object.values(api)) mock.mockReset();
});
afterEach(cleanup);

describe("SavedCases", () => {
  it("shows each case's status, and the mismatch lines of failed and error cases", async () => {
    api.listWorkflowCases.mockResolvedValue([
      savedCase({ id: "c1", name: "Passes", mismatches: ["ignored"] }),
      savedCase({ id: "c2", name: "Fails", last_result: "failed", mismatches: [STEPS_LINE] }),
      savedCase({
        id: "c3",
        name: "Errors",
        last_result: "error",
        mismatches: ["workflow: not runnable"],
      }),
      savedCase({ id: "c4", name: "Never run", last_result: null, last_run_at: null }),
    ]);
    renderCases();
    expect(await screen.findByText("Passes")).toBeInTheDocument();
    expect(api.listWorkflowCases).toHaveBeenCalledWith("w1", expect.anything());
    expect(within(row("Passes")).getByText("Passed")).toBeInTheDocument();
    expect(within(row("Passes")).queryByText("ignored")).toBeNull();
    expect(within(row("Fails")).getByText("Failed")).toBeInTheDocument();
    expect(within(row("Fails")).getByText(STEPS_LINE)).toBeInTheDocument();
    expect(within(row("Errors")).getByText("Error")).toBeInTheDocument();
    expect(within(row("Errors")).getByText("workflow: not runnable")).toBeInTheDocument();
    expect(within(row("Never run")).getByText("Not run")).toBeInTheDocument();
  });

  it("runs a case's script as a preset", async () => {
    const script = { inputs: [{ node_id: "review", kind: "label" as const, values: ["no"] }] };
    api.listWorkflowCases.mockResolvedValue([savedCase({ name: "Rejected", script })]);
    const { onRun } = renderCases();
    fireEvent.click(await screen.findByRole("button", { name: "Run Rejected" }));
    expect(onRun).toHaveBeenCalledWith(script);
  });

  it("deletes a case and refetches the list", async () => {
    api.listWorkflowCases
      .mockResolvedValueOnce([savedCase({ id: "c9", name: "Old" })])
      .mockResolvedValueOnce([]);
    api.deleteWorkflowCase.mockResolvedValue(undefined);
    renderCases();
    fireEvent.click(await screen.findByRole("button", { name: "Delete Old" }));
    await waitFor(() => expect(api.deleteWorkflowCase).toHaveBeenCalledWith("w1", "c9"));
    expect(await screen.findByText(/No saved cases yet/)).toBeInTheDocument();
    expect(api.listWorkflowCases).toHaveBeenCalledTimes(2);
  });

  it("says when a delete fails and keeps the case", async () => {
    api.listWorkflowCases.mockResolvedValue([savedCase({ name: "Kept" })]);
    api.deleteWorkflowCase.mockRejectedValue(new WorkflowsApiError("Failed (500)", 500));
    renderCases();
    fireEvent.click(await screen.findByRole("button", { name: "Delete Kept" }));
    expect(await screen.findByText("Couldn't delete the case. Try again.")).toBeInTheDocument();
    expect(screen.getByText("Kept")).toBeInTheDocument();
  });

  it("offers Retry when the cases fail to load", async () => {
    api.listWorkflowCases
      .mockRejectedValueOnce(new WorkflowsApiError("Failed (404)", 404))
      .mockResolvedValueOnce([savedCase({ name: "Back" })]);
    renderCases();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Back")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load saved cases.")).toBeNull();
  });
});
