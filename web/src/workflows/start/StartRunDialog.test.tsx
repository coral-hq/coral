import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as ClientModule from "../api/client";

const api = vi.hoisted(() => ({ runPreflight: vi.fn(), startRun: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  ...api,
}));
vi.mock("@/hooks/useHosts", () => ({
  useHosts: () => ({
    isPending: false,
    data: [
      { host_id: "h1", name: "Laptop", status: "online" },
      { host_id: "h2", name: "Offline box", status: "offline" },
    ],
  }),
}));
vi.mock("@/shell/WorkspacePickerDialog", () => ({
  WorkspacePickerDialog: ({
    open,
    hostId,
    onConfirm,
  }: {
    open: boolean;
    hostId: string | null;
    onConfirm: (path: string) => void;
  }) =>
    open ? (
      <button type="button" onClick={() => onConfirm("/repo")}>
        {`pick /repo on ${hostId}`}
      </button>
    ) : null,
}));

import { StartRunDialog } from "./StartRunDialog";

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderDialog() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={["/workflows/demo"]}>
        <Routes>
          <Route
            path="/workflows/demo"
            element={<StartRunDialog workflowKey="demo" open onOpenChange={() => {}} />}
          />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function chooseRepo() {
  fireEvent.click(screen.getByRole("button", { name: "Laptop" }));
  fireEvent.click(screen.getByRole("button", { name: "Choose folder" }));
  fireEvent.click(await screen.findByRole("button", { name: "pick /repo on h1", hidden: true }));
}

beforeEach(() => {
  api.runPreflight.mockReset();
  api.startRun.mockReset();
});
afterEach(cleanup);

describe("StartRunDialog", () => {
  it("lists only online hosts and gates the folder picker on a host", () => {
    renderDialog();
    expect(screen.queryByRole("button", { name: "Offline box" })).toBeNull();
    expect(screen.getByRole("button", { name: "Choose folder" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
  });

  it("shows failed preflight items and blocks the run", async () => {
    api.runPreflight.mockResolvedValue({
      ok: false,
      items: [
        { id: "a", label: "Host is online", ok: true },
        { id: "b", label: "Repository is clean", ok: false, detail: "3 uncommitted files" },
      ],
    });
    renderDialog();
    await chooseRepo();

    expect(await screen.findByText("Repository is clean")).toBeInTheDocument();
    expect(screen.getByText("3 uncommitted files")).toBeInTheDocument();
    expect(api.runPreflight).toHaveBeenCalledWith({
      workflow_key: "demo",
      host_id: "h1",
      workspace_path: "/repo",
    });
    expect(screen.getByRole("button", { name: "Start run" })).toBeDisabled();
  });

  it("starts the run and navigates to its page", async () => {
    api.runPreflight.mockResolvedValue({
      ok: true,
      items: [{ id: "a", label: "Host is online", ok: true }],
    });
    api.startRun.mockResolvedValue({ run_id: "run 1" });
    renderDialog();
    await chooseRepo();

    const submit = screen.getByRole("button", { name: "Start run" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    expect(await screen.findByTestId("where")).toHaveTextContent("/workflows/runs/run%201");
  });

  it("reports a failed start without leaving", async () => {
    api.runPreflight.mockResolvedValue({ ok: true, items: [] });
    api.startRun.mockRejectedValue(new Error("nope"));
    renderDialog();
    await chooseRepo();
    const submit = screen.getByRole("button", { name: "Start run" });
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't start the run");
  });
});
