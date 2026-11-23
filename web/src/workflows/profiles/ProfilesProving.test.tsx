import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));

import { profilesServer } from "../fixtures/profilesServer";
import { ProfileDetailPage } from "./ProfileDetailPage";
import { ProfilePicker } from "./ProfilePicker";

let server: ReturnType<typeof profilesServer>;

beforeEach(() => {
  server = profilesServer();
  authenticatedFetch.mockReset().mockImplementation(server.handle);
});
afterEach(cleanup);

function renderWith(node: ReactNode, path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/" element={node} />
          <Route path="/profiles/:stance/:slug" element={node} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("profiles proving flow", () => {
  it("picks a profile for Review, then saves an edit as rev 2 while running runs keep rev 1", async () => {
    const onPick = vi.fn();
    renderWith(<ProfilePicker label="Profile for Review" onPick={onPick} />);

    fireEvent.click(screen.getByRole("button", { name: "Profile for Review" }));
    const option = await screen.findByRole("option", { name: /Strict review/ });
    expect(within(option).getByText("tool gating: supported")).toBeInTheDocument();
    expect(within(option).getByText("steering: unknown")).toBeInTheDocument();
    expect(within(option).getByText("Used by 1 workflow, 1 running run")).toBeInTheDocument();
    fireEvent.click(option);
    expect(onPick).toHaveBeenCalledWith("reviewer/strict-review");
    cleanup();

    renderWith(<ProfileDetailPage />, "/profiles/reviewer/strict-review");
    const instructions = await screen.findByLabelText("Instructions");
    expect(screen.getByTestId("profile-revision")).toHaveTextContent("rev 1");
    fireEvent.change(instructions, { target: { value: "Review every change; block on infra." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Running runs keep rev 1; new runs use rev 2"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("profile-revision")).toHaveTextContent("rev 2");
    const saves = server.requests.filter((r) => r.method === "POST");
    expect(saves).toEqual([
      {
        method: "POST",
        url: "/v1/coral/profiles/reviewer/strict-review/revisions",
        body: {
          base_revision_no: 1,
          spec: expect.objectContaining({ instructions: "Review every change; block on infra." }),
        },
      },
    ]);
    expect(server.requests.some((r) => r.method === "PATCH")).toBe(false);
  });
});
