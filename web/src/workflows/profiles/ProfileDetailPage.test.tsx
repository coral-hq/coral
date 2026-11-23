import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@/hooks/useIsMobileViewport", () => ({ useIsMobileViewport: () => viewport.mobile }));

import { STRICT_REVIEW_SPEC, profilesServer } from "../fixtures/profilesServer";
import { ProfileDetailPage } from "./ProfileDetailPage";

let server: ReturnType<typeof profilesServer>;

beforeEach(() => {
  viewport.mobile = false;
  server = profilesServer();
  authenticatedFetch.mockReset().mockImplementation(server.handle);
});
afterEach(cleanup);

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/profiles/reviewer/strict-review"]}>
        <Routes>
          <Route path="/profiles/:stance/:slug" element={<ProfileDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProfileDetailPage", () => {
  it("edits a rule's paths and shows the template's statement and bypasses", async () => {
    renderDetail();
    const paths = await screen.findByLabelText("Paths (one per line)");
    expect(paths).toHaveValue("infra");
    expect(
      await screen.findByText(/Example: Never change files under infra\/\..*Not enforced against/),
    ).toBeInTheDocument();
    fireEvent.change(paths, { target: { value: "infra\n\ndeploy " } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(server.specs).toHaveLength(2));
    expect(server.specs[1]!.rules[0]!.params).toEqual({ paths: ["infra", "deploy"] });
  });

  it("asks for a reload when another save got there first", async () => {
    renderDetail();
    await screen.findByLabelText("Instructions");
    // Another tab saves rev 2 before this one does.
    server.specs.push({ ...STRICT_REVIEW_SPEC, instructions: "Theirs." });
    fireEvent.change(screen.getByLabelText("Instructions"), { target: { value: "Mine." } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("This profile changed.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    await waitFor(() => expect(screen.getByLabelText("Instructions")).toHaveValue("Theirs."));
    expect(screen.getByTestId("profile-revision")).toHaveTextContent("rev 2");
    expect(server.specs).toHaveLength(2);
  });

  it("lists the fields a 422 names", async () => {
    renderDetail();
    await screen.findByLabelText("Instructions");
    authenticatedFetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          error: {
            code: "validation_failed",
            message: "Invalid profile.",
            details: { errors: [{ field: "rules[0].params.paths", message: "Bad path." }] },
          },
        }),
        { status: 422 },
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("rules[0].params.paths: Bad path.")).toBeInTheDocument();
    expect(screen.queryByText(/Running runs keep/)).toBeNull();
  });

  it("shows no revision notice when Save changes nothing", async () => {
    renderDetail();
    await screen.findByLabelText("Instructions");
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(server.requests.some((r) => r.method === "POST")).toBe(true));
    expect(server.specs).toHaveLength(1);
    expect(screen.getByTestId("profile-revision")).toHaveTextContent("rev 1");
    expect(screen.queryByText(/Running runs keep/)).toBeNull();
  });

  it("offers Retry when the profile fails to load", async () => {
    authenticatedFetch.mockResolvedValueOnce(new Response("{}", { status: 500 }));
    renderDetail();
    expect(screen.getByLabelText("Loading profile")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findByLabelText("Instructions")).toBeInTheDocument();
  });

  it("is read-only at phone width", async () => {
    viewport.mobile = true;
    renderDetail();
    expect(await screen.findByLabelText("Instructions")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });
});
