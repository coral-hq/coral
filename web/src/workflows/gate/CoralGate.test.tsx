import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CoralInfoError } from "./useCoralInfo";
import type * as CoralInfoModule from "./useCoralInfo";

const query = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));
vi.mock("./useCoralInfo", async (importOriginal) => ({
  ...(await importOriginal<typeof CoralInfoModule>()),
  useCoralInfo: () => query.current,
}));
vi.mock("@/pages/NotFoundPage", () => ({ NotFoundPage: () => <div>not found</div> }));

import { CoralGate } from "./CoralGate";

afterEach(cleanup);

function renderGate(state: Record<string, unknown>, subFeature?: string) {
  query.current = { data: undefined, error: null, isPending: false, refetch: vi.fn(), ...state };
  render(
    <CoralGate subFeature={subFeature}>
      <p>desk</p>
    </CoralGate>,
  );
  return query.current.refetch as ReturnType<typeof vi.fn>;
}

const info = (sub_features: Record<string, boolean> = {}, enabled = true) => ({
  enabled,
  version: "1",
  sub_features,
});

describe("CoralGate", () => {
  it("shows a spinner, never not-found, while loading", () => {
    renderGate({ isPending: true });
    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
    expect(screen.queryByText("not found")).toBeNull();
    expect(screen.queryByText("desk")).toBeNull();
  });

  it("renders children when enabled", () => {
    renderGate({ data: info() });
    expect(screen.getByText("desk")).toBeInTheDocument();
  });

  it("renders not found when Coral is disabled", () => {
    renderGate({ data: info({}, false) });
    expect(screen.getByText("not found")).toBeInTheDocument();
  });

  it("renders not found when the plugin is absent (404)", () => {
    renderGate({ error: new CoralInfoError("missing", 404) });
    expect(screen.getByText("not found")).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load Coral")).toBeNull();
  });

  it("requires the named sub-feature to be on", () => {
    renderGate({ data: info({ profiles_desk: false }) }, "profiles_desk");
    expect(screen.getByText("not found")).toBeInTheDocument();
    cleanup();
    renderGate({ data: info({ profiles_desk: true }) }, "profiles_desk");
    expect(screen.getByText("desk")).toBeInTheDocument();
  });

  it("offers Retry on an outage and refetches on click", () => {
    const refetch = renderGate({ error: new CoralInfoError("boom", 500) });
    expect(screen.getByRole("heading", { name: "Couldn't load Coral" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("treats a network failure as an outage", () => {
    renderGate({ error: new TypeError("Failed to fetch") });
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("keeps cached info when a background refetch fails", () => {
    renderGate({ data: info(), error: new CoralInfoError("boom", 500) });
    expect(screen.getByText("desk")).toBeInTheDocument();
  });
});
