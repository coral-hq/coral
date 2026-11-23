import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));

import { profilesServer } from "../fixtures/profilesServer";
import { ProfilePicker } from "./ProfilePicker";
import { ProfilesPage } from "./ProfilesPage";

let server: ReturnType<typeof profilesServer>;

beforeEach(() => {
  server = profilesServer();
  authenticatedFetch.mockReset().mockImplementation(server.handle);
});
afterEach(cleanup);

function renderPage(node = <ProfilesPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProfilesPage", () => {
  it("lists seeded and user profiles with source, revision, chips, rules and used-by", async () => {
    renderPage();
    expect(screen.getByLabelText("Loading profiles")).toBeInTheDocument();
    const rows = await screen.findAllByTestId("profile-row");
    expect(rows).toHaveLength(3);

    const seeded = within(rows[0]!);
    expect(seeded.getByText("Seeded")).toBeInTheDocument();
    expect(seeded.queryByText(/^rev /)).toBeNull();
    expect(seeded.queryByRole("link")).toBeNull();

    const mine = within(rows[2]!);
    expect(mine.getByRole("link", { name: "Strict review" })).toHaveAttribute(
      "href",
      "/profiles/reviewer/strict-review",
    );
    expect(mine.getByText("Yours")).toBeInTheDocument();
    expect(mine.getByText("rev 1")).toBeInTheDocument();
    expect(mine.getByText("steering: unknown")).toBeInTheDocument();
    expect(mine.getByText("Never change files under infra/.")).toBeInTheDocument();
    expect(mine.getByText("Used by 1 workflow, 1 running run")).toBeInTheDocument();
  });

  it("shows only the seeded stances when the user has none", async () => {
    authenticatedFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      const response = await server.handle(url, init);
      if (url !== "/v1/coral/profiles") return response;
      const rows = (await response.json()) as { source: string }[];
      return new Response(JSON.stringify(rows.filter((row) => row.source === "seeded")));
    });
    renderPage();
    expect(await screen.findAllByTestId("profile-row")).toHaveLength(2);
    expect(screen.queryByText("Yours")).toBeNull();
  });

  it("creates a profile and opens its page", async () => {
    const handle = server.handle;
    authenticatedFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      if (url !== "/v1/coral/profiles" || init?.method !== "POST") return handle(url, init);
      const detail = (await (await handle("/v1/coral/profiles/reviewer/strict-review")).json()) as {
        profile_ref: string;
      };
      return new Response(JSON.stringify({ ...detail, profile_ref: "reviewer/new-one" }));
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/profiles"]}>
          <Routes>
            <Route path="/profiles" element={<ProfilesPage />} />
            <Route path="/profiles/:stance/:slug" element={<p>opened</p>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "New profile" }));
    const create = screen.getByRole("button", { name: "Create" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Slug"), { target: { value: " new-one " } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New one" } });
    fireEvent.click(create);
    expect(await screen.findByText("opened")).toBeInTheDocument();
    const post = authenticatedFetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(post![1].body)).toMatchObject({
      ref: "reviewer/new-one",
      spec: { name: "New one" },
    });
  });

  it("offers Retry after a failed load and recovers", async () => {
    authenticatedFetch.mockResolvedValueOnce(new Response("{}", { status: 500 }));
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));
    expect(await screen.findAllByTestId("profile-row")).toHaveLength(3);
  });
});

describe("ProfilePicker", () => {
  it("lists seeded rows first and never a reserved coral__ agent", async () => {
    authenticatedFetch.mockImplementation(async (url: string, init?: RequestInit) => {
      const response = await server.handle(url, init);
      if (url !== "/v1/coral/profiles") return response;
      const rows = (await response.json()) as { profile_ref: string; name: string }[];
      const reserved = { ...rows[0]!, profile_ref: "coral__planner", name: "Planner" };
      return new Response(JSON.stringify([rows[2], reserved, ...rows.slice(0, 2)]));
    });
    renderPage(<ProfilePicker onPick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Insert profile" }));
    await screen.findByRole("option", { name: /Strict review/ });
    const names = screen.getAllByRole("option").map((o) => o.getAttribute("data-value"));
    expect(names).toEqual(["implementer", "reviewer", "reviewer/strict-review"]);
  });
});
